#!/usr/bin/env python3
"""transcribe.cpp cell — GGUF speech recognition on the ggml runtime.

One engine, many model families: the same binary runs GigaAM, Parakeet, Canary,
Whisper, Moonshine, Qwen3-ASR and others, chosen purely by which .gguf you point
it at — the same shape as a llama.cpp cell, so the caravan's existing model
picker, HF browser and download path all apply unchanged.

    GET  /health                     200 {"status":"ok","model":<slug>,"engine":"transcribe.cpp"}
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
MODEL_PATH = sys.argv[2] if len(sys.argv) > 2 else ""

_state = {"ready": False, "error": "", "phase": "loading"}
_model = None
_session = None
# Read off the loaded model, never hardcoded: each family has its own window
# (gigaam-v3 is 25 s) and the whole point of this runner is that the file
# decides. 0 until the model is up.
_window_ms = 0
_meta = {}
# The engine is one resident session; concurrent requests must not interleave
# inside it. Transcription is fast (tens of ms), so a plain lock is enough and
# avoids a worker pool that would multiply the model's memory.
_lock = threading.Lock()


def _log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _model_slug() -> str:
    """The name the board and any LAN client show for this cell.

    Derived from the file, because the engine is generic: "gigaam-v3-e2e-rnnt"
    tells the operator what is actually running, where "transcribe.cpp" alone
    would leave every such cell looking identical.
    """
    base = os.path.basename(MODEL_PATH or "")
    base = re.sub(r"\.gguf$", "", base, flags=re.I)
    return re.sub(r"-(F16|F32|BF16|Q\d[^-]*)$", "", base, flags=re.I) or "transcribe"


def _load() -> None:
    global _model, _session, _window_ms, _meta
    try:
        if not MODEL_PATH or not os.path.isfile(MODEL_PATH):
            raise FileNotFoundError(f"model file not found: {MODEL_PATH}")
        import transcribe_cpp
        _model = transcribe_cpp.Model(MODEL_PATH)
        _session = _model.session().__enter__()
        caps = getattr(_model, "capabilities", None)
        _window_ms = int(getattr(caps, "max_audio_ms", 0) or 0)
        # What the ENGINE says it loaded, not what argv asked for. A card that
        # reads its identity out of the command line can advertise a model that
        # failed to be what it claimed; these three come off the object.
        _meta = {
            "arch": str(getattr(_model, "arch", "") or ""),
            "variant": str(getattr(_model, "variant", "") or ""),
            "backend": str(getattr(_model, "backend", "") or ""),
            "languages": list(getattr(caps, "languages", ()) or ()),
            "maxAudioMs": _window_ms,
        }
        _state["ready"] = True
        _state["phase"] = "ok"
        _log(f"transcribe: {_model_slug()} ready on :{PORT}")
    except Exception as exc:  # noqa: BLE001
        _state["error"] = str(exc)
        _state["phase"] = "error"
        _log(f"transcribe: load failed: {exc}")


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


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):   # quiet: the cell log is for the engine
        pass

    def _send(self, code: int, payload, ctype="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _path(self):
        return (self.path or "/").split("?")[0].rstrip("/") or "/"

    def do_GET(self):
        if self._path() not in ("/", "/health"):
            self._send(404, {"error": "not found"})
            return
        # "model" and "engine" are what a LAN client names this card by; a bare
        # "ok" once left the whisper cell nameless among its peers. The rest is
        # read off the loaded model, so the card cannot advertise a backend or a
        # language the cell does not actually have.
        if _state["ready"]:
            self._send(200, dict({"status": "ok", "model": _model_slug(),
                                  "engine": "transcribe.cpp", "kinds": ["asr"]}, **_meta))
        elif _state["error"]:
            self._send(500, {"status": "error", "error": _state["error"]})
        else:
            # CARAVAN reads this shape as a "loading" cell phase rather than a
            # silent STARTING (see command_cell_health on the controller).
            self._send(503, {"status": "loading", "downloadedBytes": 0, "totalBytes": 0})

    def do_POST(self):
        if self._path() not in ("/v1/audio/transcriptions", "/transcribe"):
            self._send(404, {"error": "not found"})
            return
        if not _state["ready"] or _session is None:
            self._send(503, {"error": "model loading"})
            return
        ln = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(ln)
        wav = _extract_file(body, self.headers.get("Content-Type", ""))
        if not wav:
            self._send(400, {"error": "need multipart file=wav"})
            return
        try:
            samples, sr = _wav_to_floats(wav)
            samples = _resample_16k(samples, sr)
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"error": f"bad wav: {exc}"})
            return
        try:
            pieces = _split_at_quiet(samples, _window_ms)
            with _lock:
                texts = [(getattr(_session.run(p), "text", "") or "").strip() for p in pieces]
            body = {"text": " ".join(t for t in texts if t)}
            # Say when the recording was cut. The seams are where this cell can
            # lose a word, so the caller gets to know they exist rather than
            # reading a joined transcript as one clean pass.
            if len(pieces) > 1:
                body["chunks"] = len(pieces)
            self._send(200, body)
        except Exception as exc:  # noqa: BLE001
            _log(f"transcribe error: {exc}")
            self._send(500, {"error": str(exc)})


if __name__ == "__main__":
    # Bind first, load after: the port answers 503 with a loading marker while
    # the weights come up, so the board shows "loading" instead of a dead port.
    threading.Thread(target=_load, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
