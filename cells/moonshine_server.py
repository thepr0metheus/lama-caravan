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
# Annotations are not evaluated at import: the macOS client runs stock
# Python 3.9, where `str | None` in a signature is a TypeError the moment the
# def executes — the module never loads, the cell never listens, and the board
# just says it did not come up.
from __future__ import annotations

import gc
import io
import json
import os
import re
import sys
import threading
import wave
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer   # noqa: E402

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


def log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


class MoonshineCell(CellServer):
    """Recognition and synthesis in one cell, loaded independently.

    `kinds` is what puts the row in both sections of a LAN client's list; a
    client predating it still reads `model` and treats the cell as a
    recognizer, so shipping this never broke an older one.
    """
    default_port = 8025
    engine = "moonshine"
    kinds = ["asr", "tts"]

    @property
    def language(self):
        return (self.args[0] if self.args else "en").lower()

    @property
    def model_name(self):
        return f"moonshine-{self.language}"

    def extra_health(self):
        return {"langs": [self.language]}

    def load(self):
        global _transcriber
        from moonshine_voice import get_model_for_language
        from moonshine_voice.transcriber import Transcriber
        path, arch = get_model_for_language(self.language)   # downloads on first run
        _transcriber = Transcriber(path, arch)
        log(f"moonshine[{self.language}] ready on :{self.port} ({path})")

    def ready_required(self, path):
        # Synthesis does not wait for the recognizer: the two load
        # independently, and a voice request answered with "model loading"
        # would make the cell look less capable than it is.
        return not path.endswith("/speech")

    def handle_get(self, path, query):
        if not path.endswith("/voices"):
            return None
        lang = "en"
        for kv in query.split("&"):
            if kv.startswith("language="):
                lang = kv.split("=", 1)[1]
        try:
            return 200, json.dumps(_voice_list(lang)).encode(), "application/json"
        except ValueError as e:
            return 400, json.dumps({"error": str(e)}).encode(), "application/json"

    def handle(self, body, headers, path):
        if path.endswith("/speech"):                      # ---- TTS ----
            try:
                req = json.loads(body.decode("utf-8") or "{}")
            except Exception:  # noqa: BLE001
                return 400, json.dumps({"error": "need json {text, language}"}).encode(), "application/json"
            text = (req.get("text") or "").strip()
            if not text:
                return 400, json.dumps({"error": "need json {text, language}"}).encode(), "application/json"
            try:
                samples, sr = _synthesize(text, req.get("language") or "en",
                                          req.get("voice"))
            except ValueError as e:
                return 400, json.dumps({"error": str(e)}).encode(), "application/json"
            return 200, _wav_bytes(samples, sr), "audio/wav"

        if _transcriber is None:                          # ---- STT ----
            return 503, json.dumps({"error": "model loading"}).encode(), "application/json"
        wav = _extract_file(body, headers.get("Content-Type", ""))
        if not wav:
            return 400, json.dumps({"error": "need multipart file=wav"}).encode(), "application/json"
        audio, sr = _wav_to_floats(wav)
        with _lock:                          # one CPU inference at a time
            res = _transcriber.transcribe_without_streaming(audio, sr)
        text = " ".join(
            l.text for l in (getattr(res, "lines", None) or [])).strip()
        return 200, json.dumps({"text": text}).encode(), "application/json"


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
            log(f"moonshine tts[{tag}{' ' + vid if vid else ''}] ready")
            while len(_tts) > max(1, TTS_CACHE_MAX):
                (old_tag, old_vid), dead = _tts.popitem(last=False)
                # close() releases the voice's runtime sessions. Dropping the
                # reference alone does NOT give the memory back — measured:
                # 16 evictions without it still grew the process by ~300 MB.
                try:
                    dead.close()
                except Exception as exc:  # noqa: BLE001
                    log(f"moonshine tts close failed: {exc}")
                del dead
                gc.collect()
                log(f"moonshine tts[{old_tag}{' ' + old_vid if old_vid else ''}]"
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


if __name__ == "__main__":
    MoonshineCell().serve()
