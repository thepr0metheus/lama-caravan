#!/usr/bin/env python3
"""transcribe.cpp cell — GGUF speech recognition on the ggml runtime.

One engine, many model families: the same binary runs GigaAM, Parakeet, Canary,
Whisper, Moonshine, Qwen3-ASR and others, chosen purely by which .gguf you point
it at — the same shape as a llama.cpp cell, so the caravan's existing model
picker, HF browser and download path all apply unchanged.

    GET  /health                     200 {"status":"ok","model":<slug>,"engine":"transcribe.cpp"}

    POST /v1/audio/transcriptions honours response_format=json (default) |
    verbose_json | text | srt | vtt, and timestamp_granularities[]=word. Word
    times are DERIVED from the engine's token times — see _words_from_tokens.
                                     | 503 {"status":"loading"} while the model loads
    POST /v1/audio/transcriptions    multipart: file=wav [, language]
                                     -> {"text": "..."}

Why this exists next to the whisper cell: for RUSSIAN, GigaAM-v3 is a different
class — Sber's eval puts it near 8% WER against whisper large-v3's 21-25% across
ten Russian sets, and it emits cased, punctuated text. Measured here on a 5090:
the model loads in 0.1 s and transcribes at ~78x realtime, because the weights
are a 260 MB quantised GGUF rather than a multi-gigabyte torch checkpoint.

THE MODEL STAYS RESIDENT. The engine also ships a CLI, but shelling out per
request would reload the weights every time; the Python binding keeps one Model
and one session alive for the life of the cell, which is what makes this usable
interactively at all.

Setup: scripts/install-transcribe.sh (builds libtranscribe with CUDA/Metal and
installs the binding into ~/transcribe-venv).
Usage: transcribe_server.py <port> <model.gguf>
Licensing: transcribe.cpp is MIT; each MODEL carries its own terms — GigaAM-v3
is MIT, but check the card before assuming (some ASR weights are CC-BY-NC).
"""
from __future__ import annotations

import array
import io
import json
import os
import re
import sys
import threading
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer   # noqa: E402

_model = None
_session = None
_window_ms = 0
_meta = {}
_model_path = ""
_lock = threading.Lock()


def log(msg: str) -> None:
    print(msg, flush=True)


class TranscribeCell(CellServer):
    """GGUF speech recognition through transcribe.cpp.

    Answers 404 on any other path — a health reply to an unknown GET is a 200
    with the wrong body. Speaks HTTP/1.1 because its callers pipeline chunks
    and would otherwise pay a handshake for each one.
    """
    default_port = 8000
    engine = "transcribe.cpp"
    kinds = ["asr"]
    health_paths = ("/", "/health")
    protocol_version = "HTTP/1.1"

    @property
    def model_name(self):
        return _model_slug()

    def extra_health(self):
        # Read off the LOADED model, not off argv: a card that takes its
        # identity from the command line can advertise a model that failed to
        # be what it claimed.
        return dict(_meta)

    def load(self):
        global _model, _session, _window_ms, _meta, _model_path
        _model_path = self.args[0] if self.args else ""
        if not _model_path or not os.path.isfile(_model_path):
            raise FileNotFoundError(f"model file not found: {_model_path}")
        import transcribe_cpp
        _model = transcribe_cpp.Model(_model_path)
        _session = _model.session().__enter__()
        caps = getattr(_model, "capabilities", None)
        _window_ms = int(getattr(caps, "max_audio_ms", 0) or 0)
        _meta = {
            "arch": str(getattr(_model, "arch", "") or ""),
            "variant": str(getattr(_model, "variant", "") or ""),
            "backend": str(getattr(_model, "backend", "") or ""),
            # "langs" is the contract's name for this; "languages" stays one
            # release so a consumer reading the old key is not broken by the
            # rename. Two names for one value is exactly the drift the contract
            # exists to end — the duplicate goes when the release lands.
            "langs": list(getattr(caps, "languages", ()) or ()),
            "languages": list(getattr(caps, "languages", ()) or ()),
            "maxAudioMs": _window_ms,
        }
        log(f"transcribe: {_model_slug()} ready on :{self.port}")

    def handle(self, body, headers, path):
        if path not in ("/v1/audio/transcriptions", "/transcribe"):
            return 404, json.dumps({"error": "not found"}).encode(), "application/json"
        ctype = headers.get("Content-Type", "")
        wav = _extract_file(body, ctype)
        if not wav:
            return 400, json.dumps({"error": "need multipart file=wav"}).encode(), "application/json"
        try:
            samples, sr = _wav_to_floats(wav)
            samples = _resample_16k(samples, sr)
        except Exception as exc:  # noqa: BLE001
            return 400, json.dumps({"error": f"bad wav: {exc}"}).encode(), "application/json"

        fmt = (_fields(body, ctype, "response_format") or ["json"])[0].lower() or "json"
        gran = {g.lower() for g in _fields(body, ctype, "timestamp_granularities")}
        pieces = _split_at_quiet(samples, _window_ms)
        texts, words, segments = [], [], []
        offset_ms = 0.0
        with _lock:
            for piece in pieces:
                res = _session.run(piece)
                text = (getattr(res, "text", "") or "").strip()
                texts.append(text)
                dur_ms = len(piece) / 16.0            # 16 samples per ms at 16 kHz
                if text:
                    # One segment per piece: the engine gives none, and the
                    # seams are the only division we actually know about.
                    segments.append({
                        "id": len(segments), "seek": 0,
                        "start": round(offset_ms / 1000.0, 3),
                        "end": round((offset_ms + dur_ms) / 1000.0, 3),
                        "text": text,
                    })
                words.extend(_words_from_tokens(getattr(res, "tokens", ()), offset_ms))
                offset_ms += dur_ms
        full = " ".join(t for t in texts if t)
        total_s = round(len(samples) / 16000.0, 3)

        if fmt == "text":
            return 200, (full + "\n").encode(), "text/plain; charset=utf-8"
        if fmt in ("srt", "vtt"):
            lines = ["WEBVTT", ""] if fmt == "vtt" else []
            for i, seg in enumerate(segments, 1):
                if fmt == "srt":
                    lines.append(str(i))
                lines.append(f"{_srt_ts(seg['start'], fmt == 'srt')} --> "
                             f"{_srt_ts(seg['end'], fmt == 'srt')}")
                lines.append(seg["text"])
                lines.append("")
            return (200, ("\n".join(lines)).encode(),
                    "application/x-subrip; charset=utf-8" if fmt == "srt"
                    else "text/vtt; charset=utf-8")
        if fmt == "verbose_json":
            out = {"task": "transcribe", "language": (_meta.get("languages") or [""])[0],
                   "duration": total_s, "text": full, "segments": segments}
            # Same rule as the whisper cell: words ride on the explicit
            # granularity, so a caller that asked for segments only is not
            # handed a payload several times larger than it wanted.
            if "word" in gran:
                out["words"] = words
            if len(pieces) > 1:
                out["chunks"] = len(pieces)
            return 200, json.dumps(out).encode(), "application/json"

        body_out = {"text": full}
        # Say when the recording was cut. The seams are where this cell can lose
        # a word, so the caller gets to know they exist rather than reading a
        # joined transcript as one clean pass.
        if len(pieces) > 1:
            body_out["chunks"] = len(pieces)
        return 200, json.dumps(body_out).encode(), "application/json"


def _model_slug() -> str:
    """The name the board and any LAN client show for this cell.

    Derived from the file, because the engine is generic: "gigaam-v3-e2e-rnnt"
    tells the operator what is actually running, where "transcribe.cpp" alone
    would leave every such cell looking identical.
    """
    base = os.path.basename(_model_path or "")
    base = re.sub(r"\.gguf$", "", base, flags=re.I)
    return re.sub(r"-(F16|F32|BF16|Q\d[^-]*)$", "", base, flags=re.I) or "transcribe"

def _wav_to_floats(data: bytes):
    """wav bytes -> (list[float] mono, sample_rate). 16-bit PCM expected."""
    wf = wave.open(io.BytesIO(data), "rb")
    sr = wf.getframerate()
    ch = wf.getnchannels()
    raw = wf.readframes(wf.getnframes())
    wf.close()
    a = array.array("h")
    a.frombytes(raw)
    if ch > 1:                                   # downmix to mono
        a = a[::ch]
    return [s / 32768.0 for s in a], sr


def _resample_16k(samples, sr: int):
    """Resample to 16 kHz. The engine takes 16 kHz mono float32 and does NOT
    resample; clients send whatever their capture produced.

    DOWNSAMPLING LOW-PASSES FIRST. Plain linear interpolation is fine going up,
    but 48k->16k without a filter folds everything above 8 kHz back into the
    speech band, and aliasing on a cell whose entire justification is Russian
    WER produces slightly-worse text that nobody can attribute to anything. A
    boxcar average over the decimation factor is a weak filter, but it is a
    filter, and it costs one pass instead of a scipy dependency."""
    if sr == 16000 or not samples:
        return samples
    if sr > 16000:
        k = int(sr // 16000)
        if k >= 2:
            n = len(samples) - (len(samples) % k)
            acc, sm = 0.0, [0.0] * (n // k)
            for i in range(0, n, k):
                acc = 0.0
                for j in range(k):
                    acc += samples[i + j]
                sm[i // k] = acc / k
            samples, sr = sm, sr / k
            if abs(sr - 16000.0) < 1e-6:
                return samples
    ratio = 16000.0 / float(sr)
    out_len = int(len(samples) * ratio)
    out = [0.0] * out_len
    for i in range(out_len):
        pos = i / ratio
        lo = int(pos)
        hi = min(lo + 1, len(samples) - 1)
        frac = pos - lo
        out[i] = samples[lo] * (1.0 - frac) + samples[hi] * frac
    return out


def _split_at_quiet(samples, window_ms: int):
    """Cut audio longer than the model's window into pieces, preferring silence.

    THIS IS A CORRECTNESS FIX, NOT A FEATURE. GigaAM has a SOFT window: hand it
    60 s and the engine writes a WARN to stderr, returns 200, and hands back
    degraded text — in testing here, an empty string. The caller sees a healthy
    cell and a successful request that quietly lost the recording. That is the
    caravan's catalogued "absence rendered as normality" defect, so the cell
    refuses to produce it: anything past the window is split and rejoined.

    Boundaries land at 80% of the window, then slide up to 1.5 s either way to
    the quietest 20 ms frame nearby — cutting mid-word costs a word at every
    seam. Worst case a piece is 0.8w + 1.5 s, still inside the window for any
    model whose window is over ~8 s.
    """
    win = int(16000 * (window_ms / 1000.0))
    if win <= 0 or len(samples) <= win:
        return [samples]
    step = max(int(win * 0.8), 1)
    band = int(16000 * 1.5)
    frame = 320                                    # 20 ms at 16 kHz
    out, start = [], 0
    while start < len(samples):
        nominal = start + step
        if nominal >= len(samples):
            out.append(samples[start:])
            break
        lo = max(start + frame, nominal - band)
        hi = min(len(samples) - frame, nominal + band)
        cut, best = nominal, None
        for pos in range(lo, hi, frame):
            energy = sum(abs(samples[pos + j]) for j in range(0, frame, 4))
            if best is None or energy < best:
                best, cut = energy, pos
        out.append(samples[start:cut])
        start = cut
    out = [c for c in out if c]
    # A sub-2 s tail is not an utterance, it is the remainder of the division —
    # transcribing it alone gives the model no context and invites a hallucinated
    # fragment. Fold it back when the merge still fits the window.
    # pop() FIRST, into a name. `out[-2] = out[-2] + out.pop()` evaluates the
    # right side before resolving the target, so the pop shortens the list and
    # the assignment lands on out[-1] of the SHORTER list — the first chunk,
    # which gets overwritten and its audio silently lost.
    if len(out) > 1 and len(out[-1]) < 16000 * 2 and len(out[-2]) + len(out[-1]) <= win:
        tail = out.pop()
        out[-1] = out[-1] + tail
    return out


def _fields(body: bytes, ctype: str, name: str):
    """Every value sent under `name` — timestamp_granularities[] arrives twice
    when a caller asks for words AND segments, and reading only the first drops
    one of them."""
    m = re.search(r'boundary="?([^";,]+)"?', ctype or "")
    if not m:
        return []
    sep = ("--" + m.group(1)).encode()
    out = []
    for part in body.split(sep):
        head, _, val = part.partition(b"\r\n\r\n")
        if not _ or b'filename="' in head:
            continue
        hm = re.search(rb'name="([^"]+)"', head)
        if hm and hm.group(1).decode("utf-8", "replace").rstrip("[]") == name:
            out.append(val.rstrip(b"\r\n-").decode("utf-8", "replace").strip())
    return out


def _words_from_tokens(tokens, offset_ms: float):
    """Group the engine's TOKEN times into words.

    GigaAM reports `max_timestamp_kind = token`: it fills `result.tokens` with
    t0/t1 at 40 ms and leaves `result.words` an EMPTY TUPLE — including when the
    caller explicitly asks for word timestamps, which the C layer accepts
    without complaint because token is the finer grain. Measured on
    gigaam-v3-e2e-rnnt: `timestamps="word"` → 200, words=(), no error. A
    consumer that reads that as "this audio had no words" is reading absence as
    a fact, so we derive the words rather than pass the emptiness on.

    SentencePiece marks a word start with "▁"; `token.word_index` is -1 here, so
    the marker is what we group on. `offset_ms` shifts a chunk's times back onto
    the whole recording — piece-local times restart at zero, and a caller that
    advances its window by the last word's end would rewind at every seam.
    """
    words, cur, t0, t1 = [], "", None, None

    def flush():
        if cur.strip():
            words.append({"word": cur.strip(),
                          "start": round((offset_ms + t0) / 1000.0, 3),
                          "end": round((offset_ms + t1) / 1000.0, 3)})

    for tok in tokens or ():
        text = str(getattr(tok, "text", "") or "")
        piece = text.replace("▁", " ")
        if text.startswith("▁") and cur.strip():
            flush()
            cur, t0, t1 = "", None, None
        cur += piece
        tt0, tt1 = getattr(tok, "t0_ms", 0) or 0, getattr(tok, "t1_ms", 0) or 0
        t0 = tt0 if t0 is None else min(t0, tt0)
        t1 = tt1 if t1 is None else max(t1, tt1)
    flush()
    return words


def _srt_ts(sec: float, comma=True):
    ms = max(0, int(round(sec * 1000)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{',' if comma else '.'}{ms:03d}"


def _extract_file(body: bytes, ctype: str):
    m = re.search(r'boundary="?([^";,]+)"?', ctype or "")
    if not m:
        return None
    sep = ("--" + m.group(1)).encode()
    for part in body.split(sep):
        if b"filename=" not in part:
            continue
        idx = part.find(b"\r\n\r\n")
        if idx < 0:
            continue
        return part[idx + 4:].rstrip(b"\r\n-")
    return None


if __name__ == "__main__":
    TranscribeCell().serve()
