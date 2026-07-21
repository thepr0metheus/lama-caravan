#!/usr/bin/env python3
"""Moonshine v2 cell — CPU-only speech recognition AND synthesis, one server.

Dual-role: the same cell answers as an ① recognizer and as a 🗣 voice, so
the voice app's LAN discovery lists it in both sections:

    GET  /health                     200 {"status":"ok","model":"moonshine-<lang>",
                                          "kinds":["asr","tts"]}
                                     | 503 {"status":"loading"} while warming
    POST /v1/audio/transcriptions    multipart: file=wav [, language]
                                     -> {"text": "..."}                    (STT)
    POST /v1/audio/speech            json: {"text": "…", "language": "ru"
                                            [, "voice": "piper_ru_RU-irina-medium"]}
                                     -> audio/wav 16-bit PCM mono          (TTS)
    GET  /v1/audio/voices?language=en   -> {"present": [...], "downloadable": [...]}

«kinds» is what makes the row appear in both sections; a client that predates
it still sees «model» and treats the cell as a recognizer, so deploying this
build never breaks an older client.

A cell holds at most MOONSHINE_TTS_CACHE voices (5 by default), dropping the
least recently used one past that — auditioning many voices cannot balloon the
process. Evicted voices stay on disk, so coming back to one is a local reload.

STT and TTS load independently and lazily: the recognizer is warmed at start,
a TTS voice downloads on the first /v1/audio/speech for that language, so a
recognizer-only cell never pays the voice's memory. NOT a voice clone — the
TTS speaks Moonshine's STOCK voice (the reference-cloning path in the package
is still rough); voice cloning stays on the xtts/f5/cosyvoice cells.

No GPU needed (medium-streaming-en beats Whisper Large V3 WER at 250M params;
~0.7 s for a 6 s clip on a laptop core).
Languages — STT: en es zh ja ko vi uk ar (NO Russian, keep whisper for RU);
TTS: 20 locales INCLUDING ru-ru and uk-ua.
Licensing: EN model is MIT; the others are Moonshine Community License
(free below $1M/yr revenue, registration required, «Powered by Moonshine AI»).

Usage: moonshine_server.py [port] [language]        # defaults: 8025 en
Setup: see run_moonshine.sh (creates ~/moonshine venv, installs the package).
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import threading
from collections import OrderedDict
import gc
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8025
LANG = (sys.argv[2] if len(sys.argv) > 2 else "en").lower()

_state = {"ready": False, "error": ""}
_lock = threading.Lock()
_transcriber = None
_tts_lock = threading.Lock()
# (locale tag, voice id) -> TextToSpeech, most-recently-used LAST. Each held
# voice costs ~180-275 MB of RSS, and a client that lets a user audition
# voices would otherwise grow the cell without bound — so the cache evicts
# its least-recently-used entry past TTS_CACHE_MAX. An evicted voice stays on
# disk; re-selecting it reloads from there, no CDN round trip.
_tts = OrderedDict()
TTS_CACHE_MAX = int(os.environ.get("MOONSHINE_TTS_CACHE", "5") or 5)

# our 2-letter codes -> Moonshine TTS locales (RU/UK available here even though
# the recognizer has no Russian)
TTS_LOCALE = {
    "en": "en-us", "ru": "ru-ru", "de": "de-de", "fr": "fr-fr", "es": "es-es",
    "it": "it-it", "ja": "ja-jp", "ko": "ko-kr", "zh": "zh-hans", "uk": "uk-ua",
    "tr": "tr-tr", "vi": "vi-vn", "pt": "pt-pt", "hi": "hi-in", "ar": "ar-msa",
    "nl": "nl-nl",
}


def _log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def _load():
    global _transcriber
    try:
        from moonshine_voice import get_model_for_language
        from moonshine_voice.transcriber import Transcriber
        path, arch = get_model_for_language(LANG)   # downloads on first run
        _transcriber = Transcriber(path, arch)
        _state["ready"] = True
        _log(f"moonshine[{LANG}] ready on :{PORT} ({path})")
    except Exception as exc:  # noqa: BLE001
        _state["error"] = str(exc)
        _log(f"moonshine[{LANG}]: load failed: {exc}")


def _wav_to_floats(data: bytes):
    """wav bytes -> (list[float] mono, sample_rate). 16-bit PCM expected."""
    wf = wave.open(io.BytesIO(data), "rb")
    sr = wf.getframerate()
    ch = wf.getnchannels()
    raw = wf.readframes(wf.getnframes())
    wf.close()
    import array
    a = array.array("h")
    a.frombytes(raw)
    if ch > 1:                                   # downmix to mono
        a = a[::ch]
    return [s / 32768.0 for s in a], sr


def _synthesize(text: str, lang: str, voice: str | None = None):
    """(samples, sample_rate) with a STOCK voice of `lang`. `voice` picks one of
    the language's voices (60+ for English, 4 for Russian — see
    GET /v1/audio/voices); None = the language default. Each (language, voice)
    is fetched on first use and then cached."""
    tag = TTS_LOCALE.get((lang or "en").split("-")[0].lower())
    if tag is None:
        raise ValueError(f"no TTS voice for language '{lang}'")
    vid = (voice or "").strip() or None
    key = (tag, vid)
    with _tts_lock:
        tts = _tts.get(key)
        if tts is None:
            from moonshine_voice.tts import TextToSpeech
            tts = TextToSpeech(tag, voice=vid)   # downloads the voice once
            _tts[key] = tts
            _log(f"moonshine tts[{tag}{' ' + vid if vid else ''}] ready")
            while len(_tts) > max(1, TTS_CACHE_MAX):
                (old_tag, old_vid), dead = _tts.popitem(last=False)
                # close() releases the voice's runtime sessions. Dropping the
                # reference alone does NOT give the memory back — measured:
                # 16 evictions without it still grew the process by ~300 MB.
                try:
                    dead.close()
                except Exception as exc:  # noqa: BLE001
                    _log(f"moonshine tts close failed: {exc}")
                del dead
                gc.collect()
                _log(f"moonshine tts[{old_tag}{' ' + old_vid if old_vid else ''}]"
                     f" evicted ({len(_tts)}/{TTS_CACHE_MAX} held)")
        else:
            _tts.move_to_end(key)                # keep the freshly used one
        return tts.synthesize(str(text))


def _voice_list(lang: str) -> dict:
    """{"present": [...], "downloadable": [...]} for the language."""
    tag = TTS_LOCALE.get((lang or "en").split("-")[0].lower())
    if tag is None:
        raise ValueError(f"no TTS voice for language '{lang}'")
    import moonshine_voice as mv
    r = mv.list_tts_voices(tag) or {}
    return {"present": list(r.get("present") or []),
            "downloadable": list(r.get("downloadable") or [])}


def _wav_bytes(samples, sr: int) -> bytes:
    buf = io.BytesIO()
    wf = wave.open(buf, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(int(sr))
    wf.writeframes(b"".join(
        int(max(-1.0, min(1.0, float(s))) * 32767).to_bytes(2, "little",
                                                            signed=True)
        for s in samples))
    wf.close()
    return buf.getvalue()


def _extract_file(body: bytes, ctype: str):
    m = re.search(r'boundary="?([^";,]+)"?', ctype or "")
    if not m:
        return None
    for part in body.split(b"--" + m.group(1).encode()):
        if b'name="file"' in part.split(b"\r\n\r\n", 1)[0]:
            payload = part.split(b"\r\n\r\n", 1)
            if len(payload) == 2:
                return payload[1].rstrip(b"\r\n-")
    return None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = (self.path or "").split("?", 1)[0].rstrip("/")
        if path.endswith("/voices"):         # which stock voices this cell offers
            q = (self.path or "").split("?", 1)
            lang = "en"
            if len(q) > 1:
                for kv in q[1].split("&"):
                    if kv.startswith("language="):
                        lang = kv.split("=", 1)[1]
            try:
                self._send(200, _voice_list(lang))
            except ValueError as e:
                self._send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"error": str(e)})
            return
        if _state["ready"]:
            # «model» keeps older clients working (they read it as an ASR cell);
            # «kinds» is what lets a new client also list us as a voice
            self._send(200, {"status": "ok", "model": f"moonshine-{LANG}",
                             "kinds": ["asr", "tts"]})
        elif _state["error"]:
            self._send(500, {"status": "error", "error": _state["error"]})
        else:
            self._send(503, {"status": "loading"})

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(ln)
        path = (self.path or "").split("?", 1)[0].rstrip("/")
        if path.endswith("/speech"):             # ---- TTS ----
            try:
                req = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                self._send(400, {"error": "need json {text, language}"})
                return
            text = (req.get("text") or "").strip()
            if not text:
                self._send(400, {"error": "need json {text, language}"})
                return
            try:
                samples, sr = _synthesize(text, req.get("language") or "en",
                                          req.get("voice"))
                wav = _wav_bytes(samples, sr)
            except ValueError as e:
                self._send(400, {"error": str(e)})
                return
            except Exception as e:  # noqa: BLE001
                _log(f"synthesize error: {e}")
                self._send(500, {"error": str(e)})
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.end_headers()
            self.wfile.write(wav)
            return
        if not _state["ready"] or _transcriber is None:   # ---- STT ----
            self._send(503, {"error": "model loading"})
            return
        wav = _extract_file(body, self.headers.get("Content-Type", ""))
        if not wav:
            self._send(400, {"error": "need multipart file=wav"})
            return
        try:
            audio, sr = _wav_to_floats(wav)
            with _lock:                          # one CPU inference at a time
                res = _transcriber.transcribe_without_streaming(audio, sr)
            text = " ".join(
                l.text for l in (getattr(res, "lines", None) or [])).strip()
            self._send(200, {"text": text})
        except Exception as e:  # noqa: BLE001
            _log(f"transcribe error: {e}")
            self._send(500, {"error": str(e)})


if __name__ == "__main__":
    threading.Thread(target=_load, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
