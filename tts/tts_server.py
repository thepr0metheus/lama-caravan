#!/usr/bin/env python3
"""Voice-clone TTS cell for the voice app's speak-for-me experiment.

One unified HTTP contract, pluggable engines — run several cells (one per
engine, different ports) and A/B them from the client app by switching the URL:

    POST /v1/audio/speech-clone   multipart: text, lang, ref (wav of YOUR voice)
                                  -> audio/wav (16-bit PCM mono, engine rate)
    GET  /                        health: 200 "ok" | 503 {"status": ...}
                                  (same progress protocol as whisper_server.py,
                                  so CARAVAN shows downloading/loading phases)

Engines (pick one per process; deps are imported lazily):
    xtts       Coqui XTTS-v2 — 17 langs incl ru/en, clone from ~6 s sample.
               NB license: Coqui Public Model License = NON-commercial.
    cosyvoice  Alibaba CosyVoice2-0.5B — cross-lingual clone, Apache-2.0.
               Needs the CosyVoice repo on PYTHONPATH (run_tts.sh does it).
    f5         F5-TTS — flow matching, MIT code (base model CC-BY-NC data).
    mock       No GPU/deps beyond numpy: returns a spoken-rhythm sine melody.
               For plumbing tests on any machine.

Setup: see run_tts.sh (creates ~/tts-<engine> venv and installs the engine).
Usage: tts_server.py [port] [engine]
"""
import hashlib
import io
import json
import os
import sys
import threading
import wave

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8021
ENGINE = (sys.argv[2] if len(sys.argv) > 2 else "xtts").lower()

_state = {"phase": "starting", "downloaded": 0, "total": 0, "ready": False,
          "error": "", "engine": ENGINE}
_synth = None                 # (text, lang, ref_path) -> (float32 mono, sr)
_lock = threading.Lock()      # serialize GPU work


def _log(msg):
    print(msg, flush=True)


# --------------------------- engines ------------------------------------- #
def _load_xtts():
    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    from TTS.api import TTS                      # pip install coqui-tts
    import numpy as np
    _state["phase"] = "loading"
    _log("xtts: loading tts_models/multilingual/multi-dataset/xtts_v2 …")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cuda")
    lang_map = {"zh": "zh-cn"}                   # XTTS's one odd code

    def synth(text, lang, ref_path):
        wav = tts.tts(text=text, speaker_wav=ref_path,
                      language=lang_map.get(lang, lang))
        return np.asarray(wav, dtype=np.float32), 24000
    return synth


def _load_cosyvoice():
    # run_tts.sh puts ~/CosyVoice(+Matcha-TTS) on PYTHONPATH and downloads
    # pretrained_models/CosyVoice2-0.5B on first run.
    from cosyvoice.cli.cosyvoice import CosyVoice2
    _state["phase"] = "loading"
    model_dir = os.path.expanduser(
        os.environ.get("COSYVOICE_MODEL", "~/CosyVoice/pretrained_models/CosyVoice2-0.5B"))
    _log(f"cosyvoice: loading {model_dir} …")
    cv = CosyVoice2(model_dir, load_jit=False, load_trt=False, fp16=True)

    def synth(text, lang, ref_path):
        try:
            # current API: prompt_wav is a file path (frontend loads it itself)
            chunks = [out["tts_speech"] for out in
                      cv.inference_cross_lingual(text, ref_path, stream=False)]
        except Exception:
            # pre-2026 API took a 16 kHz tensor
            from cosyvoice.utils.file_utils import load_wav
            prompt = load_wav(ref_path, 16000)
            chunks = [out["tts_speech"] for out in
                      cv.inference_cross_lingual(text, prompt, stream=False)]
        import torch
        a = torch.cat(chunks, dim=1).squeeze(0).cpu().numpy()
        return a.astype("float32"), cv.sample_rate
    return synth


def _load_f5():
    from f5_tts.api import F5TTS                 # pip install f5-tts
    _state["phase"] = "loading"
    _log("f5: loading F5-TTS …")
    f5 = F5TTS()

    def synth(text, lang, ref_path):
        # ref_text="" -> F5 transcribes the reference itself (its own whisper)
        wav, sr, _ = f5.infer(ref_file=ref_path, ref_text="", gen_text=text)
        return wav.astype("float32"), sr
    return synth


def _load_mock():
    import numpy as np
    _state["phase"] = "loading"

    def synth(text, lang, ref_path):
        # one "syllable" of melody per word — audible, obviously synthetic
        sr, out = 24000, []
        rng = np.random.default_rng(abs(hash(text)) % (2 ** 32))
        for _ in range(max(1, len(text.split()))):
            f = float(rng.uniform(140, 320))
            n = int(sr * 0.18)
            k = np.arange(n) / sr
            out.append(np.sin(2 * np.pi * f * k) * np.hanning(n) * 0.4)
            out.append(np.zeros(int(sr * 0.06)))
        return np.concatenate(out).astype(np.float32), sr
    return synth


_LOADERS = {"xtts": _load_xtts, "cosyvoice": _load_cosyvoice,
            "f5": _load_f5, "mock": _load_mock}


def _load():
    global _synth
    try:
        if ENGINE not in _LOADERS:
            raise ValueError(f"unknown engine '{ENGINE}' (use: {'/'.join(_LOADERS)})")
        _synth = _LOADERS[ENGINE]()
        _state["phase"] = "ready"
        _state["ready"] = True
        _log(f"tts[{ENGINE}] ready on :{PORT}")
    except Exception as exc:  # noqa: BLE001
        _state["phase"] = "error"
        _state["error"] = str(exc)
        _log(f"tts[{ENGINE}]: load failed: {exc}")


# --------------------------- HTTP plumbing ------------------------------- #
# (multipart helpers copied from whisper_server.py — stdlib only, no deps)
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


def _ref_cache(wav_bytes):
    """Reference sample -> stable temp path (same sample = same file, so
    engines that cache speaker latents by path get hits for free)."""
    h = hashlib.md5(wav_bytes).hexdigest()
    path = os.path.join("/tmp", f"ttsref-{h}.wav")
    if not os.path.exists(path):
        with open(path + ".part", "wb") as f:
            f.write(wav_bytes)
        os.replace(path + ".part", path)
    return path


def _to_wav(a, sr):
    import numpy as np
    pcm = (np.clip(a, -1.0, 1.0) * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    wf = wave.open(buf, "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(sr)
    wf.writeframes(pcm.tobytes())
    wf.close()
    return buf.getvalue()


from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


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
        if _state["ready"]:
            # Advertise the engine even when ready. A bare "ok" is
            # indistinguishable from any other healthy server, so LAN discovery
            # (the voice app's scan) couldn't tell a ready TTS cell apart from a
            # plain-"ok" endpoint and dropped it. The caravan board's own
            # command-cell probe reads status=ok all the same.
            self._send(200,
                       json.dumps({"status": "ok", "engine": ENGINE}).encode(),
                       "application/json")
            return
        payload = json.dumps({
            "status": _state["phase"], "engine": ENGINE,
            "downloadedBytes": _state["downloaded"],
            "totalBytes": _state["total"], "error": _state["error"],
        }).encode()
        self._send(500 if _state["phase"] == "error" else 503,
                   payload, "application/json")

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(ln)
        if not _state["ready"] or _synth is None:
            self._send(503, json.dumps({"error": f"model {_state['phase']}"}).encode(),
                       "application/json")
            return
        text = (_field(body, "text") or "").strip()
        lang = (_field(body, "lang") or "en").strip().lower()
        ref = _extract_file(body, self.headers.get("Content-Type", ""))
        if not text or not ref:
            self._send(400, json.dumps({"error": "need text + ref wav"}).encode(),
                       "application/json")
            return
        try:
            with _lock:
                a, sr = _synth(text, lang, _ref_cache(ref))
            self._send(200, _to_wav(a, sr), "audio/wav")
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"synth error: {e}\n")
            self._send(500, json.dumps({"error": str(e)}).encode(),
                       "application/json")


if __name__ == "__main__":
    threading.Thread(target=_load, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
