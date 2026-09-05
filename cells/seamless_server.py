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
import io
import json
import os
import sys
import threading
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer   # noqa: E402

MAX_AUDIO_MS = int(os.environ.get("SEAMLESS_MAX_AUDIO_MS", "30000"))
SAMPLE_RATE = 16000


# Format tokens the /hf downloader uses as the LAST path segment. The layout is
# <model>/<author>/<FORMAT>/, so the basename of a downloaded checkpoint is the
# precision, not a name — reporting it made the board label a cell "FP32", which
# says nothing about which model is running and is the same for every one of them.
_FORMAT_SEGMENTS = {"FP32", "FP16", "BF16", "INT8", "INT4", "FP8", "Q8", "Q4", "ST",
                    "GPTQ", "AWQ", "NVFP4", "MXFP4"}


def _model_name(directory):
    """The model's name from a downloaded checkpoint path.

    Reverses the download layout: drop a trailing format segment, then the
    author segment it sat under. A directory that follows neither convention
    keeps its own basename, which is the best available answer for a folder
    someone assembled by hand.
    """
    parts = [p for p in str(directory or "").rstrip("/").split("/") if p]
    if not parts:
        return "seamless-m4t-v2"
    if parts[-1].upper() in _FORMAT_SEGMENTS:
        parts.pop()                     # .../<model>/<author>/FP32 -> .../<model>/<author>
        if len(parts) >= 2:
            parts.pop()                 # -> .../<model>
    return parts[-1]

_state = {"ready": False, "error": "", "device": "", "dtype": "", "langs": []}
_lock = threading.Lock()
_model = None
_processor = None
_model_dir = ""
_port = 0
#: Целевой язык ячейки. Живёт модулем, потому что _resolve_lang
#: отвечает им на пустой запрос, а вызывают её из хелпера, а не из класса.
_tgt_lang = "rus"


def log(msg):
    # Prefix kept: journalctl shows one unit per host and the cell logs
    # interleave with everything else it started.
    print(f"[seamless] {msg}", flush=True)


class SeamlessCell(CellServer):
    """SeamlessM4T v2: speech in one language, TEXT in another.

    `engine` is present in the ok branch because a LAN scanner that cannot read
    it drops the cell as unidentifiable. The language list comes off the
    checkpoint so a UI builds its options from the cell rather than from a table
    of its own that can disagree with what is loaded.
    """
    default_port = 8030
    engine = "seamless-m4t-v2"
    kinds = ["asr"]
    def is_health(self, path):
        # Anything ending in /health, and the root. Not a fixed list: this cell
        # has always answered /v1/health as well, and a caller that relies on it
        # would meet a 404 with no way to tell it from the cell being gone.
        return path == "/" or path.endswith("/health")

    def ready_required(self, path):
        # A POST to a path this cell does not serve is a 404 whether or not the
        # model is up. Answering 503 "model loading" first would send the caller
        # off to wait for a load that was never going to make that path exist.
        return path.endswith("/transcriptions") or path.endswith("/translations")

    protocol_version = "HTTP/1.1"
    json_ensure_ascii = False
    json_content_type = "application/json; charset=utf-8"

    @property
    def model_name(self):
        return _model_name(self.args[0] if self.args else "")

    @property
    def target_lang(self):
        return (self.args[1] if len(self.args) > 1 else "rus").lower()

    def extra_health(self):
        return {
            "targetLang": self.target_lang,
            "langs": _state.get("langs") or [],
            "codeset": "iso639-3",
            "acceptsIso639_1": True,
            # Stated rather than left to be discovered: the model detects the
            # source language itself and reports no verdict, so there is nothing
            # for a caller to set and nothing honest to return.
            "srcLang": "auto",
            "device": _state["device"], "dtype": _state["dtype"],
            "maxAudioMs": MAX_AUDIO_MS,
        }

    def load(self):
        global _model_dir, _port, _tgt_lang
        _model_dir = self.args[0] if self.args else ""
        _port = self.port
        _tgt_lang = self.target_lang
        _load()
        if _state.get("error"):
            raise RuntimeError(_state["error"])

    def handle(self, body, headers, path):
        if not path.endswith("/transcriptions") and not path.endswith("/translations"):
            return 404, {"error": "not found"}, None
        raw = _extract_file(body, headers.get("Content-Type", ""))
        if not raw:
            return 400, {"error": "multipart field `file` is required"}, None
        # Field names, in order of preference:
        #   tgt_lang   — unambiguous, and what a caller should use
        #   language   — OpenAI's name. In THAT protocol it means the language
        #                being SPOKEN; here it is the language written. The
        #                collision is real and cannot be resolved silently, so
        #                the unambiguous name exists and this one is kept only so
        #                clients written against the first release keep working.
        #   src_lang   — accepted and NOT used: this model detects the source
        #                from the audio itself. /health says so, so a caller can
        #                see it without running an experiment.
        requested = (_field(body, "tgt_lang") or _field(body, "target_lang")
                     or _field(body, "language") or "")
        try:
            tgt = _resolve_lang(requested)
        except LangError as exc:
            # 400, not 500: a language this cell cannot serve is the caller's to
            # fix, and a 500 is indistinguishable from the cell having died.
            return 400, {
                "error": f"unsupported language {exc.args[0]!r}",
                "accepted": _state.get("langs") or [],
                "codeset": "iso639-3",
                "hint": "two-letter ISO 639-1 codes are accepted where unambiguous",
            }, None
        audio = _decode_audio(raw)
        text = _translate(audio, tgt)
        return 200, {"text": text, "language": tgt, "tgtLang": tgt,
                     "srcLang": None,   # not knowable: see /health srcLang
                     "durationMs": int(len(audio) / SAMPLE_RATE * 1000)}, None


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
        if not _model_dir or not os.path.isdir(_model_dir):
            raise RuntimeError(f"model dir not found: {_model_dir!r}")
        use_cuda = torch.cuda.is_available()
        # bf16 on GPU: fp32 needs ~5.6 GiB for this tower alone, and this box
        # habitually has a 20 GB language model resident. CPU stays fp32 —
        # bf16 on CPU is slower, not faster, outside AMX hardware.
        dtype = torch.bfloat16 if use_cuda else torch.float32
        _processor = AutoProcessor.from_pretrained(_model_dir)
        model = SeamlessM4Tv2ForSpeechToText.from_pretrained(_model_dir, dtype=dtype)
        model = model.to("cuda" if use_cuda else "cpu").eval()
        _model = model
        # Which target languages this checkpoint has, from the map generate()
        # itself validates against — generation_config's text_decoder_lang_to_code_id.
        # An earlier version scanned the tokenizer for __xxx__ tokens of a fixed
        # length and lost cmn_Hant, which is longer: the list looked complete and
        # was short by one, and the only symptom would have been a 400 for a
        # language the model can in fact produce.
        try:
            gen = getattr(model, "generation_config", None)
            codes = list(getattr(gen, "text_decoder_lang_to_code_id", None) or {})
            if not codes:                      # older configs: fall back to the file
                with open(os.path.join(_model_dir, "generation_config.json"), "rb") as fh:
                    codes = list(json.load(fh).get("text_decoder_lang_to_code_id") or {})
            _state["langs"] = sorted(codes)
        except Exception:  # noqa: BLE001
            _state["langs"] = []
        _state["device"] = "cuda" if use_cuda else "cpu"
        _state["dtype"] = "bfloat16" if use_cuda else "float32"
        _state["ready"] = True
        log(f"ready on {_state['device']} ({_state['dtype']}), target={_tgt_lang}")
    except Exception as exc:  # noqa: BLE001
        _state["error"] = f"{type(exc).__name__}: {exc}"
        log(f"load failed: {_state['error']}")


# ISO 639-1 -> 639-3, for the languages this family serves. The OpenAI API and
# most clients speak two-letter codes; this model speaks three. Without the
# bridge, `language=en` — the single most likely value any whisper client will
# send — reached the model as an unknown token and came back a 500.
#
# This is an ADDITIVE convenience, deliberately: an alias missing from here
# degrades to "pass the three-letter code", never to a wrong language. The
# authoritative list is what the checkpoint itself reports.
#
# Ambiguous on purpose, where 639-1 is coarser than the model:
#   ar -> arb  (Modern Standard Arabic, not ary/arz dialects the model also has)
#   zh -> cmn  (Mandarin, not yue)
#   az -> azj  (North Azerbaijani)  fa -> pes (Western Persian)
#   mn -> khk  (Halh Mongolian)     ms -> zsm (Standard Malay)
#   uz -> uzn  (Northern Uzbek)     sw -> swh (Coastal Swahili)

_ISO1_TO_3 = {
    "af": "afr", "am": "amh", "ar": "arb", "as": "asm", "az": "azj", "be": "bel",
    "bn": "ben", "bs": "bos", "bg": "bul", "ca": "cat", "cs": "ces", "cy": "cym",
    "da": "dan", "de": "deu", "el": "ell", "en": "eng", "et": "est", "eu": "eus",
    "fa": "pes", "fi": "fin", "fr": "fra", "ga": "gle", "gl": "glg", "gu": "guj",
    "he": "heb", "hi": "hin", "hr": "hrv", "hu": "hun", "hy": "hye", "id": "ind",
    "ig": "ibo", "is": "isl", "it": "ita", "ja": "jpn", "jv": "jav", "ka": "kat",
    "kk": "kaz", "km": "khm", "kn": "kan", "ko": "kor", "ky": "kir", "lo": "lao",
    "lt": "lit", "lv": "lvs", "mk": "mkd", "ml": "mal", "mn": "khk", "mr": "mar",
    "ms": "zsm", "mt": "mlt", "my": "mya", "ne": "npi", "nl": "nld", "no": "nob",
    "pa": "pan", "pl": "pol", "ps": "pbt", "pt": "por", "ro": "ron", "ru": "rus",
    "sd": "snd", "sk": "slk", "sl": "slv", "sn": "sna", "so": "som", "es": "spa",
    "sr": "srp", "sv": "swe", "sw": "swh", "ta": "tam", "te": "tel", "tg": "tgk",
    "th": "tha", "tl": "tgl", "tr": "tur", "uk": "ukr", "ur": "urd", "uz": "uzn",
    "vi": "vie", "yo": "yor", "zh": "cmn", "zu": "zul",
}


class LangError(ValueError):
    """A language code this cell cannot serve. Carries the accepted list so the
    caller is told what WOULD work, rather than left to guess."""


def _resolve_lang(code):
    """Normalise a requested language to a code this checkpoint has."""
    raw = str(code or "").strip().replace("-", "_").strip("_")
    if not raw:
        return _tgt_lang
    known = _state.get("langs") or []
    # Case-insensitive, canonical spelling out. Not all codes are lower-case —
    # cmn_Hant carries a capital, and lower-casing the request made the one
    # language the list had just been fixed to include unreachable anyway.
    index = {k.lower(): k for k in known}
    hit = index.get(raw.lower())
    if hit:
        return hit
    mapped = _ISO1_TO_3.get(raw[:2].lower()) if len(raw) in (2, 5) else None
    if mapped:
        return index.get(mapped.lower(), mapped) if known else mapped
    if not known:                      # config unreadable: let the model judge
        return raw
    raise LangError(raw)

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
            # transformers renamed this argument: `audios` through 4.x,
            # `audio` from 5.0, and the old name now raises rather than warns.
            # Try the current spelling and fall back, so one server file works
            # on whichever version a host's venv resolved to.
            try:
                inputs = _processor(audio=chunk, sampling_rate=SAMPLE_RATE,
                                    return_tensors="pt")
            except (TypeError, ValueError):
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


if __name__ == "__main__":
    SeamlessCell().serve()
