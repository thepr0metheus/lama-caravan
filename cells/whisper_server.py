#!/usr/bin/env python3
"""OpenAI-compatible faster-whisper server for a voice app's --asr-endpoint.

Serves POST /v1/audio/transcriptions (multipart wav -> {"text": ...}) on your GPU.

Startup progress: the port binds immediately and the model loads in a background
thread, so the health endpoint reports progress. GET <health> returns:
    503 + {"status":"downloading"|"loading","downloadedBytes":N,"totalBytes":M}
    200 "ok"  when the model is ready
(CARAVAN surfaces this as a "downloading N% / loading" cell phase instead of a
silent STARTING; the model auto-downloads from HuggingFace on first run.)

Setup (on the GPU box):
    python3 -m venv ~/wsr && ~/wsr/bin/pip install faster-whisper \
        nvidia-cudnn-cu12 nvidia-cublas-cu12
    bash run_whisper.sh 8000 large-v3     # sets LD_LIBRARY_PATH for CTranslate2
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
MODEL = sys.argv[2] if len(sys.argv) > 2 else "large-v3"

_state = {"phase": "starting", "downloaded": 0, "total": 0, "ready": False, "error": ""}
_model = None


def _log(msg):
    print(msg, flush=True)


def _download_with_progress():
    """Fetch the model files first, updating _state with byte progress so the
    admin UI can show a percentage. Best-effort: on any problem we return None
    and let WhisperModel download on load (just without the percentage)."""
    try:
        from faster_whisper.utils import _MODELS
        import huggingface_hub
        from huggingface_hub.utils import tqdm as _hf_tqdm
    except Exception as exc:  # noqa: BLE001
        _log(f"whisper: progress hook unavailable ({exc})")
        return None
    repo = _MODELS.get(MODEL, MODEL) if isinstance(_MODELS, dict) else MODEL
    try:
        info = huggingface_hub.HfApi().model_info(repo, files_metadata=True)
        _state["total"] = sum(int(getattr(f, "size", 0) or 0) for f in (info.siblings or []))
    except Exception:  # noqa: BLE001
        _state["total"] = 0

    class _T(_hf_tqdm):  # sum bytes across all downloaded files
        def update(self, n=1):
            try:
                _state["downloaded"] += int(n or 0)
            except Exception:  # noqa: BLE001
                pass
            return super().update(n)

    _state["phase"] = "downloading"
    _log(f"whisper: downloading '{MODEL}' ({_state['total'] / 1e9:.1f} GB) …")
    return huggingface_hub.snapshot_download(repo, tqdm_class=_T)


def _load():
    global _model
    try:
        from faster_whisper import WhisperModel
        model_ref = _download_with_progress() or MODEL
        _state["phase"] = "loading"
        _log(f"whisper: loading '{MODEL}' on CUDA …")
        _model = WhisperModel(model_ref, device="cuda", compute_type="float16")
        _state["downloaded"] = _state["total"] or _state["downloaded"]
        _state["phase"] = "ready"
        _state["ready"] = True
        _log(f"whisper server ready on :{PORT}")
    except Exception as exc:  # noqa: BLE001
        _state["phase"] = "error"
        _state["error"] = str(exc)
        _log(f"whisper: load failed: {exc}")


def _boundary(ctype):
    for part in ctype.split(";"):
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


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # Health: 200 "ok" when ready, else 503 (or 500 on error) + progress JSON.
        if _state["ready"]:
            self._send(200, b"ok")
            return
        payload = json.dumps({
            "status": _state["phase"],
            "downloadedBytes": _state["downloaded"],
            "totalBytes": _state["total"],
            "error": _state["error"],
        }).encode()
        self._send(500 if _state["phase"] == "error" else 503, payload, "application/json")

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(ln)
        if not _state["ready"] or _model is None:
            self._send(503, json.dumps({"error": f"model {_state['phase']}"}).encode(),
                       "application/json")
            return
        wav = _extract_file(body, self.headers.get("Content-Type", ""))
        lang = _field(body, "language")
        task = _field(body, "task")           # "translate" -> whisper any->en
        text = ""
        detected = ""                         # what whisper decided it heard
        if wav:
            path = tempfile.mktemp(suffix=".wav")
            try:
                with open(path, "wb") as f:
                    f.write(wav)
                segs, info = _model.transcribe(
                    path, language=(lang or None), beam_size=1, vad_filter=False,
                    task=("translate" if task == "translate" else "transcribe"))
                text = " ".join(s.text.strip() for s in segs).strip()
                # report the auto-detected language: on a short clip whisper's
                # guess is often wrong, and a client that knows which languages
                # are actually in play can only correct it if it's told
                detected = str(getattr(info, "language", "") or "")
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"transcribe error: {e}\n")
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._send(200, json.dumps({"text": text, "language": detected}).encode(),
                   "application/json")


if __name__ == "__main__":
    threading.Thread(target=_load, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
