#!/usr/bin/env python3
"""Voice-clone TTS cell: a text read out in a voice taken from a few seconds of a sample.

One engine a cell — the voice-clone runner's TTS_ENGINE (rust/crates/admin/src/domain/runner/mod.rs VoiceCloneRunner), started as
`run_tts.sh <port> <engine>`. Run several engines on different ports to A/B them:

    POST /v1/audio/speech         json: {"input": "…", "voice": "<a kept voice>"}
                                     or {"input": "…", "ref_audio": "data:audio/wav;base64,…"[, "ref_text": "…"]}
                                     [, "language": "ru"][, "speed": 1.0][, "response_format": "wav" | "pcm"]
                                  -> the text in that voice: a WAV (16-bit mono at the engine's rate, 24 kHz for all
                                     three), or its samples bare (pcm: 16-bit little-endian at 24 kHz, OpenAI's pcm).
                                     OpenAI's request, with a sample in vLLM-Omni's words (ref_audio, ref_text): the
                                     board's voice window and Open WebUI send it here as they send it to a Qwen3-TTS
                                     cell. `model` is not read (the caravan's entry puts a pool's name there), and
                                     neither is a field this list does not name.
    GET  /v1/audio/voices         {"voices": [names], "uploaded_voices": [{"name", "ref_text", "created"}]}
    POST /v1/audio/voices         multipart: audio_sample (a recording of the voice), name, consent[, ref_text]
                                  -> {"success": true, "voice": {"name", "ref_text", "created"}} — kept on the
                                     machine under its name, for every voice-clone cell there (VoiceShelf)
    POST /v1/audio/speech-clone   multipart: text, lang, ref (a recording of the voice) -> audio/wav
                                  the voice app's own request (sinapse), answered as it always was
    GET  /health                  200 {"status":"ok","engine":…,"device":…} | 503 {"status": …} while loading
                                  (same progress protocol as whisper_server.py, so CARAVAN shows downloading/loading
                                  phases; the engine field lets LAN discovery tag it TTS)

Engines (one a process; each one's packages live in the venv run_tts.sh makes for it, imported when the cell loads):
    xtts       Coqui XTTS-v2 — 17 languages, Russian among them; a voice from ~6 s of a sample.
               NB license: Coqui Public Model License = NON-commercial.
    cosyvoice  Alibaba CosyVoice2-0.5B — Chinese, English, Japanese, Korean; Apache-2.0.
               Needs the CosyVoice repo on PYTHONPATH (run_tts.sh does it).
    f5         F5-TTS — English and Chinese; MIT code, base model trained on CC-BY-NC data.
    mock       No GPU and nothing past numpy: a melody of a syllable a word. For plumbing tests on any machine.

Setup: see run_tts.sh (creates ~/tts-<engine> venv and installs the engine).
Usage: tts_server.py [port] [engine]
"""
# Deferred so a signature can never be evaluated at import: the macOS client
# runs stock Python 3.9, where a PEP-604 union in a def is a TypeError that
# stops the module loading — the cell simply never listens.
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer, Form, Recording, Refusal   # noqa: E402


def log(msg):
    print(msg, flush=True)


class Device:
    """Where the engine runs, and why there.

    The answer is recorded, not just logged: a cell that fell back to CPU
    because VRAM was short looks exactly like one running on the GPU the
    operator picked, and runs many times slower. One line at start-up is not
    somewhere anybody looks afterwards — /health says it (device, deviceReason).
    """

    #: The VRAM an engine wants FREE before it goes on the card, GB.
    NEED_GB = 2.5

    def __init__(self, env=None):
        self.env = os.environ if env is None else env
        self.name = ""
        self.reason = ""

    def pick(self, need_gb=NEED_GB):
        """cuda when TTS_DEVICE says so or enough VRAM is actually FREE, else cpu.
        The GPU cells (gemma/whisper) usually own almost all VRAM — starting one
        more CUDA model would OOM, and a CPU XTTS (~1-3 s per sentence) beats a
        dead cell. TTS_DEVICE=cuda|cpu overrides the guess."""
        dev = str(self.env.get("TTS_DEVICE", "")).lower()
        if dev in ("cuda", "cpu"):
            self.name, self.reason = dev, "TTS_DEVICE"
            return dev
        try:
            import torch
            if torch.cuda.is_available():
                free, _total = torch.cuda.mem_get_info()
                if free >= need_gb * 1024 ** 3:
                    self.name = "cuda"
                    return "cuda"
                log(f"device: only {free / 1024 ** 3:.1f} GB VRAM free "
                    f"(< {need_gb} GB) -> cpu")
                self.reason = f"only {free / 1024 ** 3:.1f} GB VRAM free, needs {need_gb} GB"
        except Exception as e:  # noqa: BLE001
            log(f"device probe failed ({e}) -> cpu")
            self.reason = f"probe failed: {e}"
        self.name = "cpu"
        return "cpu"


class VoiceEngine:
    """One engine in the cell's process: its package imported and its model loaded once (`load`), then a text read out
    in the voice of a sample (`speak`) — mono float samples and their rate. A table of engines (ENGINES), not a branch
    on the name: the cell makes the one it was started with."""

    name = ""
    #: The languages the engine is told, as it names them; empty: it is told none, and reads the text as it is.
    languages = ()
    #: Another name a request may give one of `languages`.
    aliases = {}
    #: The longest sample the engine takes a voice from, seconds; 0: any — it cuts a longer one itself.
    max_sample = 0

    def told(self, lang):
        """The language as the engine is told it — refused when the engine reads no such language."""
        if not self.languages:
            return lang
        code = self.aliases.get(lang, lang)
        if code not in self.languages:
            raise Refusal(400, f"{self.name} reads {', '.join(self.languages)} — not {lang!r}: name one in `language`")
        return code

    @staticmethod
    def paced(speed):
        """The engine's `speed` argument: none at 1, which is the call each engine has always been made with."""
        return {} if speed == 1.0 else {"speed": speed}

    def load(self, device):
        raise NotImplementedError

    def speak(self, text, lang, sample, speed):
        raise NotImplementedError


class XttsEngine(VoiceEngine):
    """Coqui XTTS-v2: 17 languages, Russian among them, and it must be told which."""

    name = "xtts"
    languages = ("en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "hu", "ko", "ja", "hi")
    #: XTTS's one odd code.
    aliases = {"zh": "zh-cn"}

    def load(self, device):
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        from TTS.api import TTS                      # pip install coqui-tts
        dev = device.pick()
        log(f"xtts: loading tts_models/multilingual/multi-dataset/xtts_v2 ({dev}) …")
        self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(dev)

    def speak(self, text, lang, sample, speed):
        import numpy as np
        wav = self.tts.tts(text=text, speaker_wav=sample.path, language=lang, **self.paced(speed))
        return np.asarray(wav, dtype=np.float32), 24000


class CosyVoiceEngine(VoiceEngine):
    """Alibaba CosyVoice2-0.5B. With the sample's words it clones zero-shot — it hears what the voice says in the
    sample; without them, cross-lingually."""

    name = "cosyvoice"
    #: Its speech tokenizer takes no longer prompt: it asserts on one past 30 s, and the cell said so as a 500.
    max_sample = 30

    def load(self, device):
        # run_tts.sh puts ~/CosyVoice(+Matcha-TTS) on PYTHONPATH and downloads
        # pretrained_models/CosyVoice2-0.5B on first run.
        # CosyVoice2 takes no device argument — cosyvoice/cli/model.py hardcodes
        # cuda-if-visible, so a cell asking for CPU used to land there only via the
        # CUDA_VISIBLE_DEVICES= the Device tile writes alongside TTS_DEVICE. Ask
        # the Device anyway: it is what keeps a low-VRAM host off the GPU, fp16 is
        # a CUDA-only ask, and this log line is the only place the device is stated.
        dev = device.pick()
        if dev == "cpu":
            # Bites only while nothing has touched CUDA yet — true for an explicit
            # TTS_DEVICE=cpu, which returns before torch is ever imported.
            os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
        from cosyvoice.cli.cosyvoice import CosyVoice2
        model_dir = os.path.expanduser(
            os.environ.get("COSYVOICE_MODEL", "~/CosyVoice/pretrained_models/CosyVoice2-0.5B"))
        log(f"cosyvoice: loading {model_dir} ({dev}) …")
        self.cv = CosyVoice2(model_dir, load_jit=False, load_trt=False, fp16=(dev == "cuda"))

    def _infer(self, text, prompt, words, speed):
        if words:
            return self.cv.inference_zero_shot(text, words, prompt, stream=False, **self.paced(speed))
        return self.cv.inference_cross_lingual(text, prompt, stream=False, **self.paced(speed))

    def speak(self, text, lang, sample, speed):
        try:
            # current API: prompt_wav is a file path (frontend loads it itself)
            chunks = [out["tts_speech"] for out in self._infer(text, sample.path, sample.words, speed)]
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
                prompt = load_wav(sample.path, 16000)
                chunks = [out["tts_speech"] for out in self._infer(text, prompt, sample.words, speed)]
            except Exception as e2:
                log(f"cosyvoice tensor-API fallback failed too: {e2!r}")
                raise e1
        import torch
        a = torch.cat(chunks, dim=1).squeeze(0).cpu().numpy()
        return a.astype("float32"), self.cv.sample_rate


class F5Engine(VoiceEngine):
    """F5-TTS: flow matching. Without the sample's words it transcribes the sample itself, with a Whisper of its own
    that it downloads the first time."""

    name = "f5"

    def load(self, device):
        from f5_tts.api import F5TTS                 # pip install f5-tts
        dev = device.pick()
        log(f"f5: loading F5-TTS ({dev}) …")
        self.f5 = F5TTS(device=dev)

    def speak(self, text, lang, sample, speed):
        wav, sr, _ = self.f5.infer(ref_file=sample.path, ref_text=sample.words, gen_text=text, **self.paced(speed))
        return wav.astype("float32"), sr


class MockEngine(VoiceEngine):
    """No GPU and nothing past numpy: a melody of a syllable a word — audible, obviously synthetic."""

    name = "mock"

    def load(self, device):
        device.name, device.reason = "cpu", "mock"

    def speak(self, text, lang, sample, speed):
        import numpy as np
        sr, out = 24000, []
        rng = np.random.default_rng(abs(hash(text)) % (2 ** 32))
        for _ in range(max(1, len(text.split()))):
            f = float(rng.uniform(140, 320))
            n = int(sr * 0.18 / speed)
            k = np.arange(n) / sr
            out.append(np.sin(2 * np.pi * f * k) * np.hanning(n) * 0.4)
            out.append(np.zeros(int(sr * 0.06 / speed)))
        return np.concatenate(out).astype(np.float32), sr


#: The engines by the name a cell is started with.
ENGINES = {engine.name: engine for engine in (XttsEngine, CosyVoiceEngine, F5Engine, MockEngine)}


class TextLanguage:
    """The language a text is read in when its request names none, told from its letters: XTTS must be told one, and
    neither Open WebUI nor the board's voice window says it. The script with the most letters wins; kana, which only
    Japanese writes, takes along the Han ideographs Japanese writes with them. Latin letters are read as English: they
    could be a dozen languages, and a request in Spanish says so (`language`)."""

    #: (language, its letters), the first winning a tie — English, so a text of no letters at all is English too.
    SCRIPTS = (
        ("en", re.compile("[A-Za-z\u00c0-\u024f]")),
        ("ru", re.compile("[\u0400-\u04ff]")),
        ("zh", re.compile("[\u4e00-\u9fff]")),
        ("ja", re.compile("[\u3040-\u30ff]")),
        ("ko", re.compile("[\uac00-\ud7af]")),
        ("ar", re.compile("[\u0600-\u06ff]")),
        ("hi", re.compile("[\u0900-\u097f]")),
    )

    @classmethod
    def of(cls, text):
        counts = {lang: len(letters.findall(str(text or ""))) for lang, letters in cls.SCRIPTS}
        if counts["ja"]:
            counts["ja"], counts["zh"] = counts["ja"] + counts["zh"], 0
        return max(cls.SCRIPTS, key=lambda script: counts[script[0]])[0]


class SpeechAnswer:
    """The voice as the request asked for it (`response_format`)."""

    #: format -> its Content-Type. wav: 16-bit mono at the engine's rate; pcm: the samples bare, 16-bit little-endian at
    #: 24 kHz, as OpenAI's pcm is. mp3, opus, aac and flac are not made here: no client of the caravan asks for them (the
    #: board and Open WebUI take a WAV), and each would be ffmpeg's work on every answer.
    FORMATS = {"wav": "audio/wav", "pcm": "audio/pcm"}
    PCM_RATE = 24000

    @classmethod
    def of(cls, fmt, samples, rate):
        """(status, body, Content-Type) of the voice in `fmt`."""
        voice = Recording(samples, rate)
        if fmt != "pcm":
            return 200, voice.wav(), cls.FORMATS["wav"]
        if voice.rate != cls.PCM_RATE:
            # Every engine here speaks at 24 kHz; one that does not cannot give pcm without a resampler the cell lacks.
            raise Refusal(400, f"pcm is {cls.PCM_RATE} Hz, and this engine speaks at {voice.rate} Hz: ask for wav")
        return 200, voice.pcm16(voice.samples), cls.FORMATS["pcm"]


class Sample:
    """A voice's sample as an engine reads it: a WAV file (every engine takes a path), the words it says ("" when they
    were not sent) and how long it is. Any recording ffmpeg reads is taken — a browser's webm, an mp3 — and so is a
    16-bit WAV without it (cell_base.Recording); the engine is given a 16-bit WAV of its first channel."""

    #: Shorter, a sample holds no voice to take.
    MIN_SECONDS = 1.0
    #: Where the WAV an engine reads is written: one file a sample, named by what it holds, so the same sample is the
    #: same file — an engine that keeps a voice's latents by its path finds them again.
    CACHE = "/tmp"

    def __init__(self, path, words="", seconds=0.0):
        self.path = path
        self.words = words
        self.seconds = float(seconds)

    @staticmethod
    def seconds_of(rec):
        return len(rec.samples) / rec.rate if rec.rate else 0.0

    @classmethod
    def wav_of(cls, raw):
        """(the WAV an engine reads, seconds) of a recording — refused when it is no recording or shorter than
        MIN_SECONDS."""
        rec = Recording.decode(raw)
        seconds = cls.seconds_of(rec)
        if seconds < cls.MIN_SECONDS:
            raise Refusal(400, f"the sample is {seconds:.1f} s: a voice is taken from a few seconds of it — record more")
        return rec.wav(), seconds

    @classmethod
    def of(cls, raw, words="", cache=None):
        wav, seconds = cls.wav_of(raw)
        path = os.path.join(cache or cls.CACHE, f"ttsref-{hashlib.md5(wav).hexdigest()}.wav")
        if not os.path.exists(path):
            part = f"{path}.part-{os.getpid()}-{threading.get_ident()}"
            with open(part, "wb") as f:
                f.write(wav)
            os.replace(part, path)
        return cls(path, words, seconds)

    @staticmethod
    def data_url(raw):
        """The bytes of a recording sent as a data URL (`data:audio/wav;base64,…`) or as bare base64. A URL of
        anywhere else is refused: the cell fetches nothing on a request's word."""
        text = str(raw or "").strip()
        if re.match(r"(?i)(https?|file|ftp):", text) or text.startswith("/"):
            raise Refusal(400, "ref_audio is fetched from nowhere: send the recording itself, as a data URL "
                               "(data:audio/wav;base64,…)")
        if text.startswith("data:"):
            head, sep, text = text.partition(",")
            if not sep or ";base64" not in head:
                raise Refusal(400, "ref_audio must be a data URL in base64 (data:audio/wav;base64,…)")
        try:
            return base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            raise Refusal(400, "ref_audio is not base64")


class VoiceShelf:
    """The voices kept on this machine from a sample, each under a name: a WAV and a note of its words, in a folder every
    voice-clone cell of the machine reads (~/.cache/caravan-tts/voices), past a restart. A request names a kept voice as
    its `voice`. vLLM-Omni keeps its own the same way (~/.cache/vllm-omni/speakers) through the same request, and the
    board's voice window keeps a voice through it (rust/crates/admin/src/fleet/cell_talk.rs CellTalk.store_voice)."""

    PATH = "/v1/audio/voices"
    HOME = "~/.cache/caravan-tts/voices"
    #: A voice's name, as the board's window and vLLM-Omni take it (rust/crates/admin/src/domain/runner/mod.rs TalkSpec.VOICE_NAME). The
    #: names are compared without regard to case, as vLLM-Omni compares them.
    NAME = re.compile(r"[A-Za-z0-9_.-]{1,64}")
    #: The longest sample kept: a voice is seconds of speech, and a minute holds any.
    MAX_SECONDS = 60.0
    #: The longest note of a sample's words, characters.
    MAX_WORDS = 4096

    def __init__(self, root=None, clock=time.time):
        self.root = os.path.expanduser(root or self.HOME)
        self.clock = clock

    def _paths(self, stem):
        return os.path.join(self.root, stem + ".wav"), os.path.join(self.root, stem + ".json")

    def _note(self, stem):
        """The note of a kept voice, or None: none kept, its WAV gone, or a note that does not read."""
        wav, note = self._paths(stem)
        if not os.path.isfile(wav):
            return None
        try:
            with open(note, encoding="utf-8") as f:
                doc = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            log(f"voices: the note of {stem!r} does not read ({exc}) — the voice is not offered")
            return None
        if not isinstance(doc, dict) or str(doc.get("name") or "").lower() != stem:
            log(f"voices: the note of {stem!r} names another voice — the voice is not offered")
            return None
        return doc

    def kept(self):
        """The notes of the voices kept, by name."""
        try:
            names = sorted(os.listdir(self.root))
        except FileNotFoundError:
            return []
        notes = (self._note(name[:-len(".json")]) for name in names if name.endswith(".json"))
        return [note for note in notes if note is not None]

    def listing(self):
        """The answer to GET /v1/audio/voices, in vLLM-Omni's shape: every name a request may give (`voices`), and
        which of them were kept from a sample (`uploaded_voices`) — here, all of them."""
        kept = self.kept()
        return {"voices": [note["name"] for note in kept],
                "uploaded_voices": [{"name": note["name"], "ref_text": str(note.get("ref_text") or ""),
                                     "created": note.get("created") or 0} for note in kept]}

    def sample(self, name):
        """The Sample of the voice kept under `name`, refused when none is."""
        stem = str(name or "").strip().lower()
        note = self._note(stem) if self.NAME.fullmatch(stem) else None
        if note is None:
            raise Refusal(400, f"no voice {name!r} is kept on this machine: keep one (POST {self.PATH}; "
                               f"GET lists them), or send a sample of one (ref_audio)")
        wav, _ = self._paths(stem)
        with open(wav, "rb") as f:
            seconds = Sample.seconds_of(Recording.decode(f.read()))
        return Sample(wav, str(note.get("ref_text") or ""), seconds)

    def keep(self, form):
        """Keep the voice of a form's sample (`audio_sample`) under its `name`, with its words (`ref_text`) and the
        word that it may be kept (`consent`). A name that is kept already is refused (409): a voice is changed by
        keeping it under another name, never by losing the one that was there."""
        name = (form.field("name") or "").strip()
        if not self.NAME.fullmatch(name):
            raise Refusal(400, "name must be 1..64 letters, digits, '.', '_' or '-'")
        consent = (form.field("consent") or "").strip()
        if not consent:
            raise Refusal(400, "consent is empty: a voice is kept on the word that the voice is the speaker's own, "
                               "or that its owner agreed")
        raw = form.file("audio_sample")
        if not raw:
            raise Refusal(400, "audio_sample is empty: send the recording of the voice")
        words = (form.field("ref_text") or "").strip()
        if len(words) > self.MAX_WORDS:
            raise Refusal(400, f"ref_text is longer than {self.MAX_WORDS} characters")
        wav, seconds = Sample.wav_of(raw)
        if seconds > self.MAX_SECONDS:
            raise Refusal(400, f"the sample is {seconds:.1f} s: a voice is kept from at most {self.MAX_SECONDS:.0f} s "
                               f"— send a shorter one")
        os.makedirs(self.root, exist_ok=True)
        stem = name.lower()
        wav_path, note_path = self._paths(stem)
        part = f"{wav_path}.part-{os.getpid()}-{threading.get_ident()}"
        with open(part, "wb") as f:
            f.write(wav)
        note = {"name": name, "ref_text": words, "consent": consent, "created": int(self.clock()),
                "seconds": round(seconds, 2)}
        try:
            # The note is claimed first and only once ("x"): two cells keeping one name at once cannot both win.
            with open(note_path, "x", encoding="utf-8") as f:
                json.dump(note, f, ensure_ascii=False)
        except FileExistsError:
            os.remove(part)
            raise Refusal(409, f"a voice named {name!r} is kept already: keep this one under another name")
        try:
            os.replace(part, wav_path)
        except OSError:
            # A note without its WAV would hold the name while offering no voice: neither stays.
            os.remove(note_path)
            os.remove(part)
            raise
        return {"success": True, "voice": {"name": name, "ref_text": words, "created": note["created"]}}


class SpeechAsk:
    """What a request to speak asks — the text, the voice's sample, the language, the pace and the answer's format —
    read from OpenAI's JSON (`read`) or from the voice app's form (`of_form`), and refused (400) when it cannot be
    said."""

    #: The longest text, characters: OpenAI's limit.
    MAX_TEXT = 4096
    #: OpenAI's range of `speed`.
    SPEEDS = (0.25, 4.0)

    def __init__(self, text, sample, language="", speed=1.0, fmt="wav"):
        self.text = text
        self.sample = sample
        #: "" — tell it from the text (TextLanguage).
        self.language = language
        self.speed = speed
        self.fmt = fmt

    @classmethod
    def speed_of(cls, raw):
        if raw is None:
            return 1.0
        low, high = cls.SPEEDS
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not low <= raw <= high:
            raise Refusal(400, f"speed must be a number from {low} to {high}")
        return float(raw)

    @classmethod
    def read(cls, body, shelf):
        """The ask of a POST /v1/audio/speech."""
        try:
            doc = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            raise Refusal(400, 'the body is not JSON: send {"input": "…", "voice": "…"}')
        if not isinstance(doc, dict):
            raise Refusal(400, "the body must be a JSON object")
        text = str(doc.get("input") or "").strip()
        if not text:
            raise Refusal(400, "input is empty: send the text to read out")
        if len(text) > cls.MAX_TEXT:
            raise Refusal(400, f"input is longer than {cls.MAX_TEXT} characters")
        voice = str(doc.get("voice") or "").strip()
        ref = doc.get("ref_audio")
        if ref and voice:
            raise Refusal(400, "voice and ref_audio both: a request speaks in one voice — one kept on the machine, "
                               "by its name, or the one of the sample it sends")
        words = str(doc.get("ref_text") or "").strip()
        if words and not ref:
            raise Refusal(400, "ref_text is the words of a sample, and there is no sample (ref_audio)")
        if ref:
            sample = Sample.of(Sample.data_url(ref), words)
        elif voice:
            sample = shelf.sample(voice)
        else:
            raise Refusal(400, f"no voice: name one kept on this machine (voice; GET {VoiceShelf.PATH} lists them), "
                               f"or send a sample of one (ref_audio)")
        language = str(doc.get("language") or "").strip().lower()
        fmt = str(doc.get("response_format") or "wav").strip().lower()
        if fmt not in SpeechAnswer.FORMATS:
            raise Refusal(400, f"response_format must be {' or '.join(SpeechAnswer.FORMATS)}: this cell does not "
                               f"make {fmt}")
        return cls(text, sample, "" if language == "auto" else language, cls.speed_of(doc.get("speed")), fmt)

    @classmethod
    def of_form(cls, form):
        """The ask of the voice app's POST /v1/audio/speech-clone: its text, its language (English when it names
        none) and its recording of the voice."""
        text = (form.field("text") or "").strip()
        lang = (form.field("lang") or "en").strip().lower()
        ref = form.file("ref")
        if not text or not ref:
            raise Refusal(400, "need text + ref wav")
        return cls(text, Sample.of(ref), lang)


class TtsCell(CellServer):
    """Voice cloning: a text and a voice's sample in, the text in that voice out.

    The engine is named in /health even when ready. A bare "ok" is
    indistinguishable from any other healthy server, so the voice app's LAN
    scan could not tell a ready TTS cell from a plain endpoint and dropped it.
    """
    default_port = 8021

    def __init__(self, argv=None, shelf=None):
        super().__init__(argv)
        self.device = Device()
        self.shelf = shelf or VoiceShelf()
        #: The engine the cell was started with, once it is loaded.
        self.voice_engine = None
        #: One synthesis at a time: one engine holds one model on one device.
        self.lock = threading.Lock()

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
        return {"device": self.device.name, "deviceReason": self.device.reason}

    def load(self):
        if self.engine not in ENGINES:
            raise ValueError(f"unknown engine '{self.engine}' (use: {'/'.join(ENGINES)})")
        engine = ENGINES[self.engine]()
        engine.load(self.device)
        self.voice_engine = engine
        log(f"tts[{self.engine}] ready on :{self.port}")

    def ready_required(self, path):
        # Only speaking waits for the engine: a voice is kept, and an unknown path answered, while it loads.
        return path == "/v1/audio/speech" or path.endswith("/speech-clone")

    def handle_get(self, path, query):
        if path != VoiceShelf.PATH:
            return None
        return 200, self.shelf.listing(), "application/json"

    def handle(self, body, headers, path):
        # (the form's fields and its file are read by cell_base.Form, like every cell's)
        ctype = headers.get("Content-Type", "")
        if path == "/v1/audio/speech":
            return self.speak(SpeechAsk.read(body, self.shelf))
        if path == VoiceShelf.PATH:
            return 200, self.shelf.keep(Form(body, ctype)), "application/json"
        if path.endswith("/speech-clone"):
            return self.speak(SpeechAsk.of_form(Form(body, ctype)))
        raise Refusal(404, f"no POST {path} here: /v1/audio/speech, {VoiceShelf.PATH} or /v1/audio/speech-clone")

    def speak(self, ask):
        engine = self.voice_engine
        lang = engine.told(ask.language or TextLanguage.of(ask.text))
        if engine.max_sample and ask.sample.seconds > engine.max_sample:
            raise Refusal(400, f"the sample is {ask.sample.seconds:.1f} s: {self.engine} takes a voice from at most "
                               f"{engine.max_sample} s of it — send a shorter one")
        with self.lock:
            samples, rate = engine.speak(ask.text, lang, ask.sample, ask.speed)
        return SpeechAnswer.of(ask.fmt, samples, rate)


if __name__ == "__main__":
    TtsCell().serve()
