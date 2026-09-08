#!/usr/bin/env python3
"""Voice-clone TTS cell for the voice app's speak-for-me experiment.

One unified HTTP contract, pluggable engines — run several cells (one per
engine, different ports) and A/B them from the client app by switching the URL:

    POST /v1/audio/speech-clone   multipart: text, lang, ref (wav of YOUR voice)
                                  -> audio/wav (16-bit PCM mono, engine rate)
    GET  /                        health: 200 {"status":"ok","engine":...}
                                  | 503 {"status": ...} while loading
                                  (same progress protocol as whisper_server.py,
                                  so CARAVAN shows downloading/loading phases;
                                  the engine field lets LAN discovery tag it TTS)

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
# Deferred so a signature can never be evaluated at import: the macOS client
# runs stock Python 3.9, where a PEP-604 union in a def is a TypeError that
# stops the module loading — the cell simply never listens.
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import threading
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer   # noqa: E402

_state = {"phase": "starting", "downloaded": 0, "total": 0, "ready": False,
          "error": "", "device": "", "deviceReason": ""}
_synth = None                 # (text, lang, ref_path) -> (float32 mono, sr)
_lock = threading.Lock()      # serialize GPU work


def log(msg):
    print(msg, flush=True)


class TtsCell(CellServer):
    """Voice cloning: text plus a reference clip in, wav out.

    The engine is named in /health even when ready. A bare "ok" is
    indistinguishable from any other healthy server, so the voice app's LAN
    scan could not tell a ready TTS cell from a plain endpoint and dropped it.
    """
    default_port = 8021

    @property
    def engine(self):
        return (self.args[0] if self.args else "xtts").lower()

    #: The engine IS the model identity here: the cell is started as
    #: `run_tts.sh $PORT <engine>` and each engine ships one voice model.
    @property
    def model_name(self):
        return self.engine

    @property
    def kinds(self):
        # "tts" first, then the engine. Only the engine was reported before, so
        # a LAN scan looking for a synthesizer by its JOB found nothing and the
        # cell was reachable only by whoever already knew it ran cosyvoice —
        # the very gap cell_base's own header describes.
        return ["tts", f"tts.{self.engine}"]

    def extra_health(self):
        return {"device": _state.get("device") or "",
                "deviceReason": _state.get("deviceReason") or ""}

    def load(self):
        global _synth
        if self.engine not in _LOADERS:
            raise ValueError(f"unknown engine '{self.engine}' (use: {'/'.join(_LOADERS)})")
        _synth = _LOADERS[self.engine]()
        log(f"tts[{self.engine}] ready on :{self.port}")

    def handle(self, body, headers, path):
        text = (_field(body, "text") or "").strip()
        lang = (_field(body, "lang") or "en").strip().lower()
        ref = _extract_file(body, headers.get("Content-Type", ""))
        if not text or not ref:
            return 400, json.dumps({"error": "need text + ref wav"}).encode(), "application/json"
        with _lock:
            a, sr = _synth(text, lang, _ref_cache(ref))
        return 200, _to_wav(a, sr), "audio/wav"


def _pick_device(need_gb: float = 2.5) -> str:
    # The answer is recorded, not just logged: a cell that fell back to CPU
    # because VRAM was short looks exactly like one running on the GPU the
    # operator picked, and runs many times slower. One line at start-up is not
    # somewhere anybody looks afterwards.
    """cuda when TTS_DEVICE says so or enough VRAM is actually FREE, else cpu.
    The GPU cells (gemma/whisper) usually own almost all VRAM — starting one
    more CUDA model would OOM, and a CPU XTTS (~1-3 s per sentence) beats a
    dead cell. TTS_DEVICE=cuda|cpu overrides the guess."""
    dev = os.environ.get("TTS_DEVICE", "").lower()
    if dev in ("cuda", "cpu"):
        _state["device"] = dev
        _state["deviceReason"] = "TTS_DEVICE"
        return dev
    try:
        import torch
        if torch.cuda.is_available():
            free, _total = torch.cuda.mem_get_info()
            if free >= need_gb * 1024 ** 3:
                _state["device"] = "cuda"
                return "cuda"
            log(f"device: only {free / 1024 ** 3:.1f} GB VRAM free "
                 f"(< {need_gb} GB) -> cpu")
            _state["deviceReason"] = (f"only {free / 1024 ** 3:.1f} GB VRAM free, "
                                      f"needs {need_gb} GB")
    except Exception as e:
        log(f"device probe failed ({e}) -> cpu")
        _state["deviceReason"] = f"probe failed: {e}"
    _state["device"] = "cpu"
    return "cpu"


def _load_xtts():
    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    from TTS.api import TTS                      # pip install coqui-tts
    import numpy as np
    _state["phase"] = "loading"
    dev = _pick_device()
    log(f"xtts: loading tts_models/multilingual/multi-dataset/xtts_v2 ({dev}) …")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(dev)
    lang_map = {"zh": "zh-cn"}                   # XTTS's one odd code

    def synth(text, lang, ref_path):
        wav = tts.tts(text=text, speaker_wav=ref_path,
                      language=lang_map.get(lang, lang))
        return np.asarray(wav, dtype=np.float32), 24000
    return synth


def _load_cosyvoice():
    # run_tts.sh puts ~/CosyVoice(+Matcha-TTS) on PYTHONPATH and downloads
    # pretrained_models/CosyVoice2-0.5B on first run.
    # CosyVoice2 takes no device argument — cosyvoice/cli/model.py hardcodes
    # cuda-if-visible, so a cell asking for CPU used to land there only via the
    # CUDA_VISIBLE_DEVICES= the Device tile writes alongside TTS_DEVICE. Ask
    # _pick_device anyway: it is what keeps a low-VRAM host off the GPU, fp16 is
    # a CUDA-only ask, and this log line is the only place the device is stated.
    dev = _pick_device()
    if dev == "cpu":
        # Bites only while nothing has touched CUDA yet — true for an explicit
        # TTS_DEVICE=cpu, which returns above before torch is ever imported.
        os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    from cosyvoice.cli.cosyvoice import CosyVoice2
    _state["phase"] = "loading"
    model_dir = os.path.expanduser(
        os.environ.get("COSYVOICE_MODEL", "~/CosyVoice/pretrained_models/CosyVoice2-0.5B"))
    log(f"cosyvoice: loading {model_dir} ({dev}) …")
    cv = CosyVoice2(model_dir, load_jit=False, load_trt=False, fp16=(dev == "cuda"))

    def synth(text, lang, ref_path):
        try:
            # current API: prompt_wav is a file path (frontend loads it itself)
            chunks = [out["tts_speech"] for out in
                      cv.inference_cross_lingual(text, ref_path, stream=False)]
        except Exception as e1:
            # The FIRST failure is the real diagnosis — on a current checkout
            # the path API is the right one, so when it breaks, the fallback
            # below breaks too ("Invalid file: tensor(...)" out of soundfile)
            # and used to be the only error anyone saw. A silent except here
            # cost a debugging session on both sides of the fleet: the visible
            # error was the fallback's, the cause was discarded unlogged.
            log(f"cosyvoice path-API failed: {e1!r}")
            try:
                # pre-2026 API took a 16 kHz tensor
                from cosyvoice.utils.file_utils import load_wav
                prompt = load_wav(ref_path, 16000)
                chunks = [out["tts_speech"] for out in
                          cv.inference_cross_lingual(text, prompt, stream=False)]
            except Exception as e2:
                log(f"cosyvoice tensor-API fallback failed too: {e2!r}")
                raise e1
        import torch
        a = torch.cat(chunks, dim=1).squeeze(0).cpu().numpy()
        return a.astype("float32"), cv.sample_rate
    return synth


def _load_f5():
    from f5_tts.api import F5TTS                 # pip install f5-tts
    _state["phase"] = "loading"
    log("f5: loading F5-TTS …")
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

_LOADERS = {"xtts": _load_xtts, "cosyvoice": _load_cosyvoice,
            "f5": _load_f5, "mock": _load_mock}


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


if __name__ == "__main__":
    TtsCell().serve()
