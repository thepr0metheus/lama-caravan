#!/usr/bin/env python3
"""SeamlessM4T v2 cell: speech in one language -> TEXT in another, one model.

WHY THIS EXISTS. The fleet can already turn English speech into Russian text —
whisper transcribes, an LLM translates — but that is two cells and two hops, and
the second one only ever sees the first one's guess. A name whisper misheard is
translated faithfully into the wrong name, and nothing downstream can tell. This
model does the whole trip itself, so the translation is conditioned on the audio
rather than on a transcript of it.

WHAT IT IS NOT. It is not a drop-in whisper. The output is text in the TARGET
language only — ask for Russian and English audio gives Russian, with no English
transcript produced along the way. Callers wanting the source words still want
whisper.

Serves POST /v1/audio/transcriptions (multipart, OpenAI-shaped) so existing
clients need no new code path, plus GET /health.

Usage: seamless_server.py <port> <model_dir> [target_lang]
"""
import hashlib
import io
import json
import os
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8030
MODEL_DIR = sys.argv[2] if len(sys.argv) > 2 else ""
TGT_LANG = (sys.argv[3] if len(sys.argv) > 3 else "rus").lower()

# The model has no input-length parameter: a long clip is simply attended over
# in one go, and memory grows with it. This is the window the cell advertises
# and enforces by chunking — the speech card on the board draws it from here,
# so a number invented in the UI instead of measured here would be a promise
# the cell never made.
MAX_AUDIO_MS = int(os.environ.get("SEAMLESS_MAX_AUDIO_MS", "30000"))
SAMPLE_RATE = 16000


def _source_stamp():
    """Digest of THIS file, taken once at import — the only moment it is
    guaranteed to be the source the interpreter actually loaded. A long-running
    cell can be older than the file beside it; hashing per request would report
    the file and hide exactly that."""
    try:
        with open(os.path.abspath(__file__), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:12]
    except Exception:  # noqa: BLE001
        return ""


SOURCE = _source_stamp()
_state = {"ready": False, "error": "", "device": "", "dtype": ""}
_lock = threading.Lock()
_model = None
_processor = None


def _log(msg):
    print(f"[seamless] {msg}", flush=True)


def _load():
    """Load once, in the background, so the port answers /health immediately.

    SpeechToText, not the full SeamlessM4Tv2Model: the full one carries the
    text-to-speech tower as well — around 800M extra parameters we would pay
    VRAM for and never call, on a box whose GPU is mostly a language model.
    """
    global _model, _processor
    try:
        import torch
        from transformers import AutoProcessor, SeamlessM4Tv2ForSpeechToText
        if not MODEL_DIR or not os.path.isdir(MODEL_DIR):
            raise RuntimeError(f"model dir not found: {MODEL_DIR!r}")
        use_cuda = torch.cuda.is_available()
        # bf16 on GPU: fp32 needs ~5.6 GiB for this tower alone, and this box
        # habitually has a 20 GB language model resident. CPU stays fp32 —
        # bf16 on CPU is slower, not faster, outside AMX hardware.
        dtype = torch.bfloat16 if use_cuda else torch.float32
        _processor = AutoProcessor.from_pretrained(MODEL_DIR)
        model = SeamlessM4Tv2ForSpeechToText.from_pretrained(MODEL_DIR, dtype=dtype)
        model = model.to("cuda" if use_cuda else "cpu").eval()
        _model = model
        _state["device"] = "cuda" if use_cuda else "cpu"
        _state["dtype"] = "bfloat16" if use_cuda else "float32"
        _state["ready"] = True
        _log(f"ready on {_state['device']} ({_state['dtype']}), target={TGT_LANG}")
    except Exception as exc:  # noqa: BLE001
        _state["error"] = f"{type(exc).__name__}: {exc}"
        _log(f"load failed: {_state['error']}")


def _boundary(ctype):
    for part in (ctype or "").split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            return part[len("boundary="):].strip('"')
    return None


def _extract_file(body, ctype):
    b = _boundary(ctype)
    if not b:
        return None
    sep = b"--" + b.encode()
    for part in body.split(sep):
        head, _, rest = part.partition(b"\r\n\r\n")
        if b"filename=" in head and rest:
            return rest.rsplit(b"\r\n", 1)[0]
    return None


def _field(body, name):
    key = ('name="%s"' % name).encode()
    i = body.find(key)
    if i < 0:
        return None
    s = body.find(b"\r\n\r\n", i)
    if s < 0:
        return None
    s += 4
    e = body.find(b"\r\n", s)
    return body[s:e].decode(errors="replace") if e > s else None


def _decode_audio(raw):
    """Bytes -> mono float32 at 16 kHz. WAV is read natively; anything else goes
    through ffmpeg, which every host running a speech cell already has."""
    import numpy as np
    try:
        with wave.open(io.BytesIO(raw), "rb") as wf:
            if wf.getsampwidth() == 2 and wf.getframerate() == SAMPLE_RATE:
                frames = wf.readframes(wf.getnframes())
                data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                if wf.getnchannels() > 1:
                    data = data.reshape(-1, wf.getnchannels()).mean(axis=1)
                return data
    except Exception:  # noqa: BLE001
        pass
    import subprocess
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"],
        input=raw, capture_output=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg: " + proc.stderr.decode(errors="replace")[:200])
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _translate(audio, tgt_lang):
    """One window at a time, joined. Chunking is ours to do: the model exposes
    no input-length limit, so a ten-minute file would otherwise be attended over
    in a single pass and take the cell down with it."""
    import torch
    window = int(SAMPLE_RATE * MAX_AUDIO_MS / 1000)
    chunks = [audio[i:i + window] for i in range(0, max(len(audio), 1), window)] or [audio]
    out = []
    with _lock:
        for chunk in chunks:
            if len(chunk) < SAMPLE_RATE // 10:      # < 100 ms: nothing to say
                continue
            inputs = _processor(audios=chunk, sampling_rate=SAMPLE_RATE,
                                return_tensors="pt")
            inputs = {k: v.to(_model.device) for k, v in inputs.items()}
            if _state["dtype"] == "bfloat16":
                inputs = {k: (v.to(torch.bfloat16) if v.is_floating_point() else v)
                          for k, v in inputs.items()}
            with torch.inference_mode():
                tokens = _model.generate(**inputs, tgt_lang=tgt_lang)
            text = _processor.batch_decode(tokens, skip_special_tokens=True)[0]
            if text.strip():
                out.append(text.strip())
    return " ".join(out)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = (self.path or "").split("?", 1)[0].rstrip("/")
        if not path.endswith("/health") and path not in ("", "/"):
            self._send(404, {"error": "not found"})
            return
        if _state["ready"]:
            # `engine` must be present in the ok branch: a LAN scanner that
            # cannot read it drops the cell as unidentifiable.
            self._send(200, {
                "status": "ok", "engine": "seamless-m4t-v2",
                "model": os.path.basename(MODEL_DIR.rstrip("/")) or "seamless-m4t-v2",
                "kinds": ["asr"], "targetLang": TGT_LANG,
                "device": _state["device"], "dtype": _state["dtype"],
                "maxAudioMs": MAX_AUDIO_MS, "source": SOURCE,
            })
        elif _state["error"]:
            self._send(500, {"status": "error", "error": _state["error"], "source": SOURCE})
        else:
            self._send(503, {"status": "loading", "source": SOURCE})

    def do_POST(self):
        path = (self.path or "").split("?", 1)[0].rstrip("/")
        if not path.endswith("/transcriptions") and not path.endswith("/translations"):
            self._send(404, {"error": "not found"})
            return
        if not _state["ready"]:
            self._send(503, {"error": _state["error"] or "loading"})
            return
        ln = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(ln)
        raw = _extract_file(body, self.headers.get("Content-Type", ""))
        if not raw:
            self._send(400, {"error": "multipart field `file` is required"})
            return
        # `language` is OpenAI's field name and means the TARGET here, which is
        # the one thing about this cell a whisper client must be told.
        tgt = (_field(body, "language") or _field(body, "target_lang") or TGT_LANG).lower()
        try:
            audio = _decode_audio(raw)
            text = _translate(audio, tgt)
        except Exception as exc:  # noqa: BLE001
            _log(f"translate error: {exc}")
            self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._send(200, {"text": text, "language": tgt,
                         "durationMs": int(len(audio) / SAMPLE_RATE * 1000)})


def main():
    threading.Thread(target=_load, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    _log(f"listening on :{PORT} (model={MODEL_DIR!r}, target={TGT_LANG})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
