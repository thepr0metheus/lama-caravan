#!/usr/bin/env python3
"""OpenAI-compatible faster-whisper server for a voice app's --asr-endpoint.

Serves POST /v1/audio/transcriptions (multipart wav -> {"text": ...}) on your GPU.

Startup progress: the port binds immediately and the model loads in a background
thread, so the health endpoint reports progress. GET <health> returns:
    503 + {"status":"downloading"|"loading","downloadedBytes":N,"totalBytes":M}
    200 + {"status":"ok","model":<size>,"engine":"faster-whisper"} when ready
(CARAVAN surfaces this as a "downloading N% / loading" cell phase instead of a
silent STARTING; the model auto-downloads from HuggingFace on first run.)

Setup (on the GPU box):
    python3 -m venv ~/wsr && ~/wsr/bin/pip install faster-whisper \
        nvidia-cudnn-cu12 nvidia-cublas-cu12
    bash run_whisper.sh 8000 large-v3     # sets LD_LIBRARY_PATH for CTranslate2
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
MODEL = sys.argv[2] if len(sys.argv) > 2 else "large-v3"


def _source_stamp():
    """Digest of THIS file, taken once at import — which is the only moment it
    is guaranteed to be the source the interpreter actually loaded.

    The controller refreshes $HOME/whisper_server.py when a cell starts, so a
    long-running process can be older than the file sitting next to it. Hashing
    on each request would report the file on disk and hide exactly that gap;
    hashing at import reports what is running. The controller compares this to
    the digest it ships and says "restart to pick it up" when they differ.
    """
    try:
        with open(os.path.abspath(__file__), "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:12]
    except Exception:  # noqa: BLE001
        return ""


SOURCE = _source_stamp()

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


def _fields(body, name):
    """EVERY value sent under this field name, in order.

    Repeated names are normal in this API — `timestamp_granularities[]` is sent
    once per granularity, so a client asking for both segment and word sends two
    parts. Reading only the first would silently drop whichever came second.
    """
    key = ('name="%s"' % name).encode()
    out, at = [], 0
    while True:
        i = body.find(key, at)
        if i < 0:
            return out
        s = body.find(b"\r\n\r\n", i)
        if s < 0:
            return out
        s += 4
        e = body.find(b"\r\n", s)
        if e > s:
            out.append(body[s:e].decode(errors="replace"))
        at = e if e > i else i + len(key)


def _field(body, name):
    vals = _fields(body, name)
    return vals[0] if vals else None


def _ts(seconds, comma=False):
    """HH:MM:SS,mmm — the timestamp shape SRT and WebVTT want."""
    ms = int(round(float(seconds) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d%s%03d" % (h, m, s, "," if comma else ".", ms)


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
        # Health: JSON when ready, else 503 (or 500 on error) + progress JSON.
        if _state["ready"]:
            # "model" and "engine" are what a LAN client names the card by — a
            # bare "ok" left it with nowhere to read the model from, so this cell
            # showed up differently from every other one. CARAVAN is unaffected:
            # its command_cell_health() only looks for a loading marker in the
            # body and treats anything else as listening, whether text or JSON.
            self._send(200, json.dumps({
                "status": "ok", "model": MODEL, "engine": "faster-whisper",
                "source": SOURCE,
            }).encode(), "application/json")
            return
        payload = json.dumps({
            "status": _state["phase"],
            "downloadedBytes": _state["downloaded"],
            "totalBytes": _state["total"],
            "error": _state["error"],
            "source": SOURCE,
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
        # WHEN each word was said. A live transcriber re-runs this on a growing
        # buffer and, once a sentence has settled, wants to drop the audio it
        # already covered — which it can only do if it knows where that sentence
        # ended in TIME. Without it the buffer keeps growing and every request
        # re-transcribes the whole thing from the top: a 30 s phrase costs
        # thirty ever-longer passes instead of thirty short ones.
        #
        # Off unless asked. Word timestamps cost an extra alignment pass, and
        # the answer for everyone who does not ask stays byte-for-byte what it
        # was — this endpoint has LAN clients that predate the field.
        fmt = (_field(body, "response_format") or "json").strip().lower()
        grans = [g.strip().lower() for g in _fields(body, "timestamp_granularities[]")
                 + _fields(body, "timestamp_granularities")]
        want_words = "word" in grans
        # Segments are needed by every format that carries timing, not just the
        # verbose one — srt and vtt ARE segment lists, just written differently.
        want_segs = fmt in ("verbose_json", "srt", "vtt") or want_words
        translating = task == "translate"
        text = ""
        failure = ""                          # set when transcription raised
        detected = ""                         # what whisper decided it heard
        out_segs, out_words, duration = [], [], 0.0
        if wav:
            path = tempfile.mktemp(suffix=".wav")
            try:
                with open(path, "wb") as f:
                    f.write(wav)
                segs, info = _model.transcribe(
                    path, language=(lang or None), beam_size=1, vad_filter=False,
                    word_timestamps=want_words,
                    task=("translate" if translating else "transcribe"))
                # `segs` is a GENERATOR — whisper does the work as it is walked,
                # so everything must be collected in this single pass.
                parts = []
                for s in segs:
                    parts.append(s.text.strip())
                    if want_segs:
                        out_segs.append({"id": len(out_segs),
                                         "start": round(float(s.start), 3),
                                         "end": round(float(s.end), 3),
                                         "text": s.text})
                    for w in (getattr(s, "words", None) or []):
                        out_words.append({"word": w.word,
                                          "start": round(float(w.start), 3),
                                          "end": round(float(w.end), 3)})
                text = " ".join(parts).strip()
                # report the auto-detected language: on a short clip whisper's
                # guess is often wrong, and a client that knows which languages
                # are actually in play can only correct it if it's told
                detected = str(getattr(info, "language", "") or "")
                duration = float(getattr(info, "duration", 0.0) or 0.0)
            except Exception as e:  # noqa: BLE001
                sys.stderr.write(f"transcribe error: {e}\n")
                failure = f"{type(e).__name__}: {e}"
            finally:
                try:
                    os.remove(path)
                except OSError:
                    pass
        # A transcription that FAILED is not a transcription of silence. The
        # error was logged and then execution fell through to the normal
        # response, so a caller got 200 with {"text": ""} — indistinguishable
        # from a clip with nothing in it, and the reason (here: the GPU was
        # full) reached nobody. Observed live 2026-08-18: whisper answered
        # empty for twenty minutes while the log filled with CUDA OOM.
        if failure:
            self._send(500, json.dumps({"error": failure}).encode(),
                       "application/json; charset=utf-8")
            return
        # Answer in the shape that was ASKED for. Returning JSON to a client that
        # requested srt is the same class of wrong as returning nothing: it looks
        # like an answer and is not the one requested.
        if fmt == "text":
            self._send(200, (text + "\n").encode(), "text/plain; charset=utf-8")
            return
        if fmt in ("srt", "vtt"):
            lines = ["WEBVTT", ""] if fmt == "vtt" else []
            for i, s in enumerate(out_segs, 1):
                if fmt == "srt":
                    lines.append(str(i))
                lines.append(f"{_ts(s['start'], fmt == 'srt')} --> {_ts(s['end'], fmt == 'srt')}")
                lines.append(s["text"].strip())
                lines.append("")
            ctype = "text/vtt; charset=utf-8" if fmt == "vtt" else "application/x-subrip; charset=utf-8"
            self._send(200, "\n".join(lines).encode(), ctype)
            return
        payload = {"text": text, "language": detected}
        if fmt == "verbose_json":
            payload.update({"task": "translate" if translating else "transcribe",
                            "duration": round(duration, 3),
                            "segments": out_segs})
            # Top level, where the OpenAI schema puts it, and only when asked —
            # an empty list would read as "no words found" rather than "not
            # requested", and a caller cannot tell those apart.
            if want_words:
                payload["words"] = out_words
        self._send(200, json.dumps(payload).encode(), "application/json")


class _Serve(ThreadingHTTPServer):
    """Accept queue deep enough for a caller that pipelines requests.

    socketserver's default is 5, and a queue that shallow does not refuse — the
    kernel drops the SYN and the caller retries at 1s, 3s, 7s, which reads as
    this cell being slow rather than being over its listen limit. A transcription
    client sending chunks back-to-back is exactly that shape of load.
    """
    request_queue_size = 64
    daemon_threads = True


if __name__ == "__main__":
    threading.Thread(target=_load, daemon=True).start()
    _Serve(("0.0.0.0", PORT), H).serve_forever()
