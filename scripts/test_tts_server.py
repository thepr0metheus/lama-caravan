#!/usr/bin/env python3
"""Value snapshot: the voice-clone TTS cell (cells/tts_server.py, 1.3.611) — OpenAI's `/v1/audio/speech` in vLLM-Omni's
words for a sample, the voices kept on the machine, and the voice app's own `/v1/audio/speech-clone`.

Until 1.3.611 the cell answered one request, the voice app's form, on any path: the board's voice window and Open WebUI
could not talk to it, and a voice had to be sent with every request. Now it speaks the dialect the controller already
speaks to a Qwen3-TTS cell (rust/crates/admin/src/fleet/cell_talk.rs): a sample in `ref_audio` with its words in `ref_text`, or a
voice kept under a name (`GET`/`POST /v1/audio/voices`).

Pinned by value, each claim with a positive and a negative:
  - the language of a text told from its letters (the script with the most of them; kana takes Han along; Latin is
    English), and how an engine is told it (XTTS's codes, its "zh-cn", a refusal naming its languages);
  - a sample: a data URL or bare base64, nothing fetched from anywhere; any recording, written as a 16-bit WAV (a WAV
    the same bytes, a webm through ffmpeg, no ffmpeg — 415); shorter than a second — 400; one file a sample;
  - the shelf: a voice kept under its name with its words and the consent, never over another (409, case aside), the
    listing in vLLM-Omni's shape, a note that does not hold up is not offered;
  - the request: every refusal with its words, the defaults (wav, speed 1, the language from the text), the voice app's
    form as it always was;
  - the cell: its routes, what waits for the engine and what does not, the engine asked with the told language, the
    sample's words and its pace; an engine's longest sample; pcm only at 24 kHz;
  - where an engine runs: each engine's own need of free VRAM (its measured peak, a fifth more, a tenth up — one 2.5 GB
    stood for all three until 2026-11); through each engine's load, on its card with 1 MB more free than its need, on
    the CPU with 1 MB less, the reason naming the figures; on the CPU the cards hidden before the engine's package is
    imported, a card the cell pins too; TTS_DEVICE over all of it; no CUDA device, a reader that cannot tell — the CPU,
    with the reason; the reader a Python of its own, reading torch's mem_get_info (a stand-in torch);
  - over HTTP, the controller's own code (CellTalk) against a running cell: it speaks in a sample's voice, keeps a voice,
    lists it, speaks in it by name, and a refusal of the cell comes back with its words.

Run: python3 scripts/test_tts_server.py
"""
import base64
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cells"))
sys.path.insert(0, str(ROOT / "scripts"))

import cell_base  # noqa: E402
import tts_server as tts  # noqa: E402
from cell_base import Form, Refusal  # noqa: E402
from test_cell_recording import StandIn, wav  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refusal(fn):
    """(status, words) of the Refusal `fn` raises; None when it raises none; ("raised", what) for anything else."""
    try:
        fn()
    except Refusal as exc:
        return exc.status, str(exc)
    except Exception as exc:  # noqa: BLE001
        return "raised", f"{type(exc).__name__}: {exc}"
    return None


def answer(fn):
    """What `fn` returns, or ("refused" | "raised", ...) instead: a step that breaks is a red check, not the end."""
    try:
        return fn()
    except Refusal as exc:
        return "refused", exc.status, str(exc)
    except Exception as exc:  # noqa: BLE001
        return "raised", f"{type(exc).__name__}: {exc}"


def multipart(fields=(), files=()):
    """(body, headers) of a form: text fields, then files as (name, filename, bytes)."""
    b = "caravan-tts-test"
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields]
    parts += [f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\n'
              f"Content-Type: audio/wav\r\n\r\n".encode() + data + b"\r\n" for k, fn, data in files]
    return b"".join(parts) + f"--{b}--\r\n".encode(), {"Content-Type": f"multipart/form-data; boundary={b}"}


def keep_form(name="Anna", consent="given-on-the-caravan-board", sample=None, words="", files=None):
    fields = [("name", name), ("consent", consent)] + ([("ref_text", words)] if words else [])
    body, headers = multipart(fields, files if files is not None else [("audio_sample", "s.wav", sample)])
    return Form(body, headers["Content-Type"])


#: Samples of 16 kHz speech: 1.5 s, 0.5 s, 40 s (past what CosyVoice takes) and 61 s (past what the shelf keeps).
VOICE = wav([1000, -1000, 2000, -2000] * 6000)
SHORT = wav([1000] * 8000)
LONG = wav([500] * (16000 * 40))
LONGEST = wav([500] * (16000 * 61))


def data_url(raw, kind="audio/wav"):
    return f"data:{kind};base64," + base64.b64encode(raw).decode("ascii")


class Fake(tts.VoiceEngine):
    """An engine that writes down what it is asked and answers a known voice."""

    name = "fake"

    def __init__(self, languages=(), max_sample=0, rate=24000):
        self.languages = languages
        self.max_sample = max_sample
        self.rate = rate
        self.asked = []

    def load(self, device):
        pass

    def speak(self, text, lang, sample, speed):
        with open(sample.path, "rb") as f:
            heard = f.read()
        self.asked.append({"text": text, "lang": lang, "wav": heard, "words": sample.words,
                           "seconds": round(sample.seconds, 3), "speed": speed})
        return [0.5, -0.5, 0.25], self.rate


class Box:
    """A folder for the shelf and the samples, put in place of the machine's."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="caravan-tts-"))
        self.samples = self.dir / "samples"
        self.samples.mkdir()
        self.keep_cache = tts.Sample.CACHE
        tts.Sample.CACHE = str(self.samples)

    def shelf(self, name="voices"):
        return tts.VoiceShelf(str(self.dir / name), clock=lambda: 1700000000)

    def close(self):
        tts.Sample.CACHE = self.keep_cache
        shutil.rmtree(self.dir, ignore_errors=True)


def section_language():
    print("the language of a text, told from its letters:")
    cases = {"Hello, world": "en", "Привет, мир": "ru", "你好，世界": "zh", "こんにちは世界": "ja", "東京都庁へ": "ja",
             "안녕하세요": "ko", "مرحبا بالعالم": "ar", "नमस्ते दुनिया": "hi", "Привет, это OpenAI": "ru", "Да, ok": "en",
             "Hello Мир and more words": "en", "12345 !?": "en", "": "en", "Él está aquí": "en"}
    got = {text: tts.TextLanguage.of(text) for text in cases}
    check(got == cases, f"each script to its language; the most letters win, a tie to English; kana takes Han along; "
                        f"no letters — English ({got})")
    check(tts.TextLanguage.of("東京") == "zh", "negative: Han ideographs without kana are Chinese")
    xtts = tts.XttsEngine()
    check([answer(lambda c=code: xtts.told(c)) for code in ("ru", "en", "zh", "zh-cn", "ja")] == ["ru", "en", "zh-cn", "zh-cn", "ja"],
          "XTTS is told its own codes: zh is its zh-cn")
    got = refusal(lambda: xtts.told("uk"))
    check(got is not None and got[0] == 400 and "xtts reads en, es," in got[1] and "not 'uk'" in got[1] and "`language`" in got[1],
          f"negative: a language XTTS does not read — 400 with the ones it does ({got})")
    check([tts.CosyVoiceEngine().told(code) for code in ("uk", "ru", "")] == ["uk", "ru", ""],
          "an engine told no language reads the text as it is: the language passes untouched")


def section_engines():
    print("the engines:")
    check(set(tts.ENGINES) == {"xtts", "cosyvoice", "f5", "mock"}
          and all(issubclass(cls, tts.VoiceEngine) and cls.name == name for name, cls in tts.ENGINES.items()),
          f"a table of four engines by their names ({sorted(tts.ENGINES)})")
    check(tts.VoiceEngine.paced(1.0) == {} and tts.VoiceEngine.paced(1.5) == {"speed": 1.5},
          "the pace: no argument at 1 — the call each engine always had — and `speed` otherwise")
    check(tts.CosyVoiceEngine.max_sample == 30 and tts.XttsEngine.max_sample == 0 and tts.F5Engine.max_sample == 0,
          "CosyVoice takes a voice from 30 s at most; XTTS and F5 cut a longer sample themselves")
    cell = tts.TtsCell(["0", "nope"])
    got = answer(cell.load)
    check(got[0] == "raised" and "unknown engine 'nope'" in got[1] and "xtts/cosyvoice/f5/mock" in got[1],
          f"negative: an engine the table does not hold — the load fails naming the ones it does ({got})")
    cell = tts.TtsCell(["0", "MOCK"])
    got = answer(cell.load)
    check(got is None and isinstance(cell.voice_engine, tts.MockEngine) and cell.extra_health() == {"device": "cpu", "deviceReason": "mock"},
          f"the cell makes the engine it was started with, its name in any case, and /health says where it runs ({got})")
    check(tts.TtsCell(["0"]).engine == "xtts" and tts.TtsCell(["0", "f5"]).kinds == ["tts", "tts.f5"],
          "with no engine named — XTTS; its kinds: the job, then the engine")


GB = 1024 ** 3
MB = 1024 ** 2
XTTS = "tts_models/multilingual/multi-dataset/xtts_v2"


class Probe:
    """A VRAM reader that answers what it is given — free bytes, None (no CUDA device) or an exception it raises — and
    notes the cards the cell's environment showed each time it was asked."""

    def __init__(self, answer):
        self.answer = answer
        self.asked = []

    def free(self, env):
        self.asked.append(env.get("CUDA_VISIBLE_DEVICES"))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class Package(types.ModuleType):
    """An engine's package, in sys.modules while a load runs: when the engine takes its class from it (the import), it
    notes the cards the cell's environment showed then."""

    def __init__(self, name, cls, env, seen):
        super().__init__(name)
        self.cls, self.env, self.seen = cls, env, seen

    def __getattr__(self, attr):
        if attr != self.cls.__name__:
            raise AttributeError(attr)
        self.seen.append(("import", self.env.get("CUDA_VISIBLE_DEVICES")))
        return self.cls


class EngineStand:
    """The three engines' packages, stood in for a load: `seen` says when an engine took its package — the cards the
    cell's environment showed then — and what it made of it."""

    def __init__(self, env):
        self.seen = seen = []

        class TTS:
            def __init__(self, name):
                seen.append(("TTS", name))

            def to(self, dev):
                seen.append(("to", dev))
                return self

        class CosyVoice2:
            def __init__(self, model_dir, load_jit, load_trt, fp16):
                seen.append(("CosyVoice2", fp16))

        class F5TTS:
            def __init__(self, device):
                seen.append(("F5TTS", device))

        self.packages = {name: Package(name, cls, env, seen)
                         for name, cls in (("TTS.api", TTS), ("cosyvoice.cli.cosyvoice", CosyVoice2), ("f5_tts.api", F5TTS))}
        self.kept = {}

    def __enter__(self):
        self.kept = {name: sys.modules.get(name) for name in self.packages}
        sys.modules.update(self.packages)
        return self

    def __exit__(self, *exc):
        for name, module in self.kept.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def loaded(engine, env, probe):
    """(the load's answer, the Device, what the engine's packages saw) of `engine` loaded in `env`, its card read by
    `probe`."""
    device = tts.Device(env=env, probe=probe)
    keep = os.environ.get("COQUI_TOS_AGREED")
    try:
        with EngineStand(env) as stand:
            got = answer(lambda: engine.load(device))
    finally:
        if keep is None:
            os.environ.pop("COQUI_TOS_AGREED", None)
        else:
            os.environ["COQUI_TOS_AGREED"] = keep
    return got, device, stand.seen


def section_device():
    print("where an engine runs — on its card while the card has the engine's own need free, else on the CPU:")
    for cls, need in ((tts.XttsEngine, 2.9), (tts.CosyVoiceEngine, 5.1), (tts.F5Engine, 2.6)):
        check(cls().need_gb == need, f"{cls.name} needs {need} GB free: its measured peak ({cls.peak_mib} MiB), a fifth "
                                     f"more, rounded up to a tenth ({cls().need_gb})")

    class Measured(tts.VoiceEngine):
        def __init__(self, peak_mib):
            self.peak_mib = peak_mib
    check(Measured(1024).need_gb == 1.2, "a peak of 1024 MiB and its fifth are 1.2 GB exactly — no tenth added")
    check(Measured(1029).need_gb == 1.3, "negative: 1029 MiB and its fifth (1.206 GB) are rounded UP, to 1.3 — not to the "
                                         "nearest 1.2")

    # Each engine through its own load, 1 MB either side of its own need, on a card the cell pins.
    cases = (
        ("xtts", int(2.9 * GB) + MB, "cuda", "2.90 GB VRAM free, needs 2.9 GB", [("import", "1"), ("TTS", XTTS), ("to", "cuda")]),
        ("xtts", int(2.9 * GB) - MB, "cpu", "only 2.89 GB VRAM free, needs 2.9 GB", [("import", ""), ("TTS", XTTS), ("to", "cpu")]),
        ("cosyvoice", int(5.1 * GB) + MB, "cuda", "5.10 GB VRAM free, needs 5.1 GB", [("import", "1"), ("CosyVoice2", True)]),
        ("cosyvoice", int(5.1 * GB) - MB, "cpu", "only 5.09 GB VRAM free, needs 5.1 GB", [("import", ""), ("CosyVoice2", False)]),
        ("f5", int(2.6 * GB) + MB, "cuda", "2.60 GB VRAM free, needs 2.6 GB", [("import", "1"), ("F5TTS", "cuda")]),
        ("f5", int(2.6 * GB) - MB, "cpu", "only 2.59 GB VRAM free, needs 2.6 GB", [("import", ""), ("F5TTS", "cpu")]),
    )
    for name, free, dev, reason, made in cases:
        probe = Probe(free)
        got, device, seen = loaded(tts.ENGINES[name](), {"CUDA_VISIBLE_DEVICES": "1"}, probe)
        said = (got, device.name, device.reason, seen, probe.asked)
        if dev == "cuda":
            check(said == (None, "cuda", reason, made, ["1"]),
                  f"{name}, 1 MB more free than its need on the card it pins: on that card, made there, the reason naming "
                  f"both figures ({said})")
        else:
            check(said == (None, "cpu", reason, made, ["1"]),
                  f"negative: {name}, 1 MB less: the CPU, the reason naming its need, the cards hidden before its package "
                  f"is imported — the card it pins too ({said})")

    probe = Probe(1 * GB)
    got, device, seen = loaded(tts.CosyVoiceEngine(), {"TTS_DEVICE": "CUDA", "CUDA_VISIBLE_DEVICES": "1"}, probe)
    said = (got, device.name, device.reason, seen, probe.asked)
    check(said == (None, "cuda", "TTS_DEVICE", [("import", "1"), ("CosyVoice2", True)], []),
          f"TTS_DEVICE=cuda over the need: CosyVoice2 on the card it pins with 1 GB free, the card not even read ({said})")
    probe = Probe(20 * GB)
    got, device, seen = loaded(tts.XttsEngine(), {"TTS_DEVICE": "cpu"}, probe)
    said = (got, device.name, device.reason, seen, probe.asked)
    check(said == (None, "cpu", "TTS_DEVICE", [("import", ""), ("TTS", XTTS), ("to", "cpu")], []),
          f"negative: TTS_DEVICE=cpu over 20 GB free: the CPU, the cards hidden, the card not even read ({said})")

    env = {}
    device = tts.Device(env=env, probe=Probe(None))
    said = (device.pick(2.9), device.reason, env)
    check(said == ("cpu", "torch sees no CUDA device", {"CUDA_VISIBLE_DEVICES": ""}),
          f"no CUDA device torch can see: the CPU, and the reason says so ({said})")
    env = {}
    device = tts.Device(env=env, probe=Probe(RuntimeError("the VRAM reader said nothing: CUDA error: unknown error")))
    said = (device.pick(2.9), device.reason, env)
    check(said == ("cpu", "probe failed: the VRAM reader said nothing: CUDA error: unknown error", {"CUDA_VISIBLE_DEVICES": ""}),
          f"negative: a reader that cannot tell — the CPU, its words the reason, not a figure ({said})")


#: torch as the VRAM reader sees it: a card while CUDA_VISIBLE_DEVICES does not hide them, its free and total bytes as
#: the environment says, and CUDA's failure when it says one.
FAKE_TORCH = '''import os


class cuda:
    @staticmethod
    def is_available():
        return os.environ.get("CUDA_VISIBLE_DEVICES") != ""

    @staticmethod
    def mem_get_info():
        if os.environ.get("FAKE_CUDA_FAILS"):
            raise RuntimeError(os.environ["FAKE_CUDA_FAILS"])
        return int(os.environ["FAKE_FREE"]), int(os.environ["FAKE_TOTAL"])
'''


def section_reader(box):
    print("the VRAM reader — a Python of its own, so CUDA never comes up in the cell's process:")
    (box.dir / "torch").mkdir()
    (box.dir / "torch" / "__init__.py").write_text(FAKE_TORCH, encoding="utf-8")
    base = {key: value for key, value in os.environ.items() if key not in ("CUDA_VISIBLE_DEVICES", "TTS_DEVICE")}
    base.update({"PYTHONPATH": str(box.dir), "PYTHONDONTWRITEBYTECODE": "1", "FAKE_FREE": str(6 * GB),
                 "FAKE_TOTAL": str(24 * GB)})
    reader = tts.VramProbe()
    got = answer(lambda: reader.free(dict(base)))
    check(got == 6 * GB, f"the free bytes of device 0, as torch's mem_get_info says them — not the total ({got})")
    got = answer(lambda: reader.free(dict(base, CUDA_VISIBLE_DEVICES="")))
    check(got is None, f"the cell's environment reaches it: the cards hidden there — no CUDA device, not 0 bytes free ({got})")
    got = answer(lambda: reader.free(dict(base, FAKE_CUDA_FAILS="CUDA error: unknown error")))
    check(got == ("raised", "RuntimeError: the VRAM reader said nothing: RuntimeError: CUDA error: unknown error"),
          f"negative: CUDA fails in the reader — raised with its last words, not a figure ({got})")
    got = answer(lambda: tts.VramProbe(str(box.dir / "no-python")).free(dict(base)))
    check(got[0] == "raised" and "FileNotFoundError" in got[1], f"negative: no Python to read with — raised, not a figure ({got})")
    env = dict(base)
    device = tts.Device(env=env)
    said = (device.pick(5.1), device.reason, env.get("CUDA_VISIBLE_DEVICES"), "torch" in sys.modules)
    check(said == ("cuda", "6.00 GB VRAM free, needs 5.1 GB", None, False),
          f"the whole way: the reader's figure decides, and torch was never imported in this process ({said})")


def section_sample(box):
    print("a sample of a voice:")
    check(tts.Sample.data_url(data_url(b"abc")) == b"abc" and tts.Sample.data_url(base64.b64encode(b"abc").decode()) == b"abc",
          "a data URL, or bare base64")
    for raw, word in (("https://example.org/v.wav", "fetched from nowhere"), ("file:///etc/passwd", "fetched from nowhere"),
                      ("/home/me/v.wav", "fetched from nowhere"), ("data:audio/wav,abc", "in base64"),
                      ("data:audio/wav;base64,@@@", "not base64"), ("@@@", "not base64")):
        got = refusal(lambda: tts.Sample.data_url(raw))
        check(got is not None and got[0] == 400 and word in got[1], f"negative: {raw!r} — 400 ({got})")
    sample = answer(lambda: tts.Sample.of(VOICE, "words"))
    expected = box.samples / f"ttsref-{hashlib.md5(VOICE).hexdigest()}.wav"
    check(isinstance(sample, tts.Sample) and sample.path == str(expected) and expected.read_bytes() == VOICE
          and sample.words == "words" and sample.seconds == 1.5,
          f"a 16-bit WAV: written for the engine as the same bytes, named by them, its words and its length ({getattr(sample, 'path', sample)})")
    check(answer(lambda: tts.Sample.of(VOICE).path) == str(expected), "the same sample is the same file")
    got = refusal(lambda: tts.Sample.of(SHORT))
    check(got == (400, "the sample is 0.5 s: a voice is taken from a few seconds of it — record more"),
          f"negative: half a second holds no voice — 400 ({got})")
    stand = StandIn()
    keep_path = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = f"{stand.dir}{os.pathsep}{keep_path}"
        stand.answers([0.25] * 24000)
        webm = b"\x1aE\xdf\xa3" + b"webm, as a browser records it" * 8
        sample = answer(lambda: tts.Sample.of(webm))
        written = Path(sample.path).read_bytes() if isinstance(sample, tts.Sample) else b""
        check(written == wav([8192] * 24000) and stand.got() == webm and sample.seconds == 1.5,
              f"a webm: read by ffmpeg, written for the engine as a 16-bit WAV at 16 kHz ({getattr(sample, 'seconds', sample)})")
        empty = Path(tempfile.mkdtemp(prefix="caravan-nopath-"))
        os.environ["PATH"] = str(empty)
        got = refusal(lambda: tts.Sample.of(webm))
        check(got is not None and got[0] == 415 and "no ffmpeg" in got[1], f"negative: no ffmpeg on the machine — 415 ({got})")
        check(refusal(lambda: tts.Sample.of(VOICE)) is None, "a WAV is taken on a machine without ffmpeg")
        shutil.rmtree(empty, ignore_errors=True)
    finally:
        os.environ["PATH"] = keep_path
        stand.close()


def section_shelf(box):
    print("the voices kept on the machine:")
    shelf = box.shelf()
    root = box.dir / "voices"
    check(shelf.listing() == {"voices": [], "uploaded_voices": []}, "nothing kept, the folder not even made: an empty list")
    got = answer(lambda: shelf.keep(keep_form("Anna", sample=VOICE, words="Привет, это мой голос")))
    check(got == {"success": True, "voice": {"name": "Anna", "ref_text": "Привет, это мой голос", "created": 1700000000}},
          f"kept: success, the name as given, its words, when ({got})")
    on_disk = sorted(os.listdir(root)) if root.exists() else []
    note = json.loads((root / "anna.json").read_text(encoding="utf-8")) if on_disk == ["anna.json", "anna.wav"] else None
    check(on_disk == ["anna.json", "anna.wav"] and (root / "anna.wav").read_bytes() == VOICE
          and note == {"name": "Anna", "ref_text": "Привет, это мой голос", "consent": "given-on-the-caravan-board",
                       "created": 1700000000, "seconds": 1.5},
          f"on disk, under its name in lower case: the sample as the engine reads it, and a note with the consent it was "
          f"kept on ({on_disk}, {note})")
    check(shelf.listing() == {"voices": ["Anna"], "uploaded_voices": [{"name": "Anna", "ref_text": "Привет, это мой голос",
                                                                       "created": 1700000000}]},
          "listed in vLLM-Omni's shape: every name a request may give, and each kept from a sample")
    sample = answer(lambda: shelf.sample("anna"))
    check(isinstance(sample, tts.Sample) and sample.path == str(root / "anna.wav")
          and sample.words == "Привет, это мой голос" and sample.seconds == 1.5,
          "a request names it in any case: its WAV, its words, its length")
    got = refusal(lambda: shelf.sample("alloy"))
    check(got is not None and got[0] == 400 and "no voice 'alloy' is kept" in got[1] and "ref_audio" in got[1],
          f"negative: a name nothing is kept under — 400, and the two ways to a voice ({got})")
    check(refusal(lambda: shelf.sample("../anna")) is not None, "negative: a name that is no voice's name is no path either")

    twice = box.shelf("twice")
    answer(lambda: twice.keep(keep_form("Anna", sample=VOICE, words="first")))
    got = refusal(lambda: twice.keep(keep_form("ANNA", sample=VOICE)))
    check(got == (409, "a voice named 'ANNA' is kept already: keep this one under another name")
          and sorted(os.listdir(box.dir / "twice")) == ["anna.json", "anna.wav"]
          and answer(lambda: twice.listing()["uploaded_voices"][0]["ref_text"]) == "first",
          f"negative: the name kept already, in another case — 409, and the voice that was there stays whole ({got})")

    refused = box.shelf("refused")
    for form, word in ((keep_form("a b", sample=VOICE), "name must be"), (keep_form("x" * 65, sample=VOICE), "name must be"),
                       (keep_form("", sample=VOICE), "name must be"), (keep_form("Bob", consent="", sample=VOICE), "consent is empty"),
                       (keep_form("Bob", files=[]), "audio_sample is empty"), (keep_form("Bob", sample=b""), "audio_sample is empty"),
                       (keep_form("Bob", sample=VOICE, words="w" * 4097), "longer than 4096"),
                       (keep_form("Bob", sample=SHORT), "is 0.5 s"), (keep_form("Bob", sample=LONGEST), "at most 60 s")):
        got = refusal(lambda: refused.keep(form))
        check(got is not None and got[0] == 400 and word in got[1], f"negative: {word} — 400 ({got})")
    left = sorted(os.listdir(box.dir / "refused")) if (box.dir / "refused").exists() else []
    check(left == [], f"a refused voice leaves nothing behind ({left})")

    ghosts = box.shelf("ghosts")
    answer(lambda: ghosts.keep(keep_form("Anna", sample=VOICE)))
    folder = box.dir / "ghosts"
    (folder / "ghost.json").write_text(json.dumps({"name": "ghost"}), encoding="utf-8")
    (folder / "other.json").write_text(json.dumps({"name": "someone"}), encoding="utf-8")
    (folder / "other.wav").write_bytes(VOICE)
    (folder / "broken.json").write_text("{", encoding="utf-8")
    (folder / "broken.wav").write_bytes(VOICE)
    check(ghosts.listing()["voices"] == ["Anna"] and refusal(lambda: ghosts.sample("ghost")) is not None
          and refusal(lambda: ghosts.sample("other")) is not None,
          "a note without its WAV, a note naming another voice, a note that does not read: not offered")


def section_ask(box):
    print("what a request to speak asks:")
    shelf = box.shelf()

    def read(doc):
        return tts.SpeechAsk.read(json.dumps(doc).encode() if not isinstance(doc, bytes) else doc, shelf)

    ask = answer(lambda: read({"input": "  Hello  ", "voice": "ANNA", "model": "qwen3-tts-base", "x_vector_only_mode": True}))
    check(isinstance(ask, tts.SpeechAsk) and (ask.text, ask.language, ask.speed, ask.fmt) == ("Hello", "", 1.0, "wav")
          and ask.sample.path.endswith("anna.wav") and ask.sample.words == "Привет, это мой голос",
          "a kept voice by name: the text trimmed, the language left to the text, speed 1, a WAV; model and the rest unread")
    ask = answer(lambda: read({"input": "Hi", "ref_audio": data_url(VOICE), "ref_text": " its words ", "language": "RU",
                               "speed": 1.25, "response_format": "PCM"}))
    check(isinstance(ask, tts.SpeechAsk) and ask.sample.words == "its words" and ask.sample.seconds == 1.5
          and (ask.language, ask.speed, ask.fmt) == ("ru", 1.25, "pcm"),
          "a sample sent along, with its words; the language lower-cased; the pace; pcm")
    check(answer(lambda: read({"input": "Hi", "voice": "anna", "language": "auto"}).language) == "",
          "language auto: told from the text, as with none")
    for doc, word in ((b"not json", "not JSON"), ([1], "JSON object"), ({"voice": "anna"}, "input is empty"),
                      ({"input": "  ", "voice": "anna"}, "input is empty"), ({"input": "x" * 4097, "voice": "anna"}, "longer than 4096"),
                      ({"input": "Hi"}, "no voice"), ({"input": "Hi", "voice": "alloy"}, "no voice 'alloy' is kept"),
                      ({"input": "Hi", "voice": "anna", "ref_audio": data_url(VOICE)}, "voice and ref_audio both"),
                      ({"input": "Hi", "voice": "anna", "ref_text": "words"}, "there is no sample"),
                      ({"input": "Hi", "voice": "anna", "response_format": "mp3"}, "must be wav or pcm"),
                      ({"input": "Hi", "voice": "anna", "speed": 0.1}, "speed must be"),
                      ({"input": "Hi", "voice": "anna", "speed": 5}, "speed must be"),
                      ({"input": "Hi", "voice": "anna", "speed": "fast"}, "speed must be"),
                      ({"input": "Hi", "voice": "anna", "speed": True}, "speed must be"),
                      ({"input": "Hi", "ref_audio": "https://example.org/a.wav"}, "fetched from nowhere")):
        got = refusal(lambda: read(doc))
        check(got is not None and got[0] == 400 and word in got[1], f"negative: {word} — 400 ({got})")
    check(answer(lambda: read({"input": "Hi", "voice": "anna", "speed": 4}).speed) == 4.0
          and answer(lambda: read({"input": "Hi", "voice": "anna", "speed": 0.25}).speed) == 0.25,
          "OpenAI's range of the pace, both ends")

    def form(*fields, ref=VOICE):
        body, headers = multipart(fields, [("ref", "ref.wav", ref)] if ref is not None else [])
        return Form(body, headers["Content-Type"])
    ask = answer(lambda: tts.SpeechAsk.of_form(form(("text", "  hello  "), ("lang", " RU "))))
    check(isinstance(ask, tts.SpeechAsk) and (ask.text, ask.language, ask.speed, ask.fmt) == ("hello", "ru", 1.0, "wav")
          and Path(ask.sample.path).read_bytes() == VOICE,
          "the voice app's form: the text and the language trimmed, the language lower-cased, the sample whole, a WAV")
    check(answer(lambda: tts.SpeechAsk.of_form(form(("text", "hello"))).language) == "en", "its form with no lang: English, as always")
    for fields, ref in ((("text", ""),), VOICE), ((("text", "hello"),), None):
        check(refusal(lambda: tts.SpeechAsk.of_form(form(*fields, ref=ref))) == (400, "need text + ref wav"),
              f"negative: its form with no text or no sample — 400 in its old words ({fields}, sample: {ref is not None})")


def section_cell(box):
    print("the cell:")
    shelf = box.shelf()
    cell = tts.TtsCell(["0", "xtts"], shelf=shelf)
    engine = Fake(languages=tts.XttsEngine.languages)
    engine.aliases = tts.XttsEngine.aliases
    cell.voice_engine = engine
    headers = {"Content-Type": "application/json"}

    def speak(doc, path="/v1/audio/speech"):
        return answer(lambda: cell.handle(json.dumps(doc).encode(), headers, path))
    got = speak({"input": "Привет, как дела?", "voice": "anna"})
    check(got[0] == 200 and got[2] == "audio/wav" and got[1] == wav([16384, -16384, 8192], rate=24000)
          and engine.asked[-1] == {"text": "Привет, как дела?", "lang": "ru", "wav": VOICE, "words": "Привет, это мой голос",
                                   "seconds": 1.5, "speed": 1.0},
          f"spoken in a kept voice: the engine told Russian from the letters, given the voice's WAV and words; a WAV back ({got[:1]})")
    got = speak({"input": "你好", "ref_audio": data_url(VOICE), "speed": 0.5, "response_format": "pcm"})
    check(got[0] == 200 and got[2] == "audio/pcm" and got[1] == struct.pack("<3h", 16384, -16384, 8192)
          and engine.asked[-1]["lang"] == "zh-cn" and engine.asked[-1]["speed"] == 0.5 and engine.asked[-1]["words"] == "",
          f"in a sample's voice: Chinese told as XTTS's zh-cn, the pace, the samples bare ({got[:1]})")
    got = speak({"input": "Hello", "voice": "anna", "language": "uk"})
    check(got[:2] == ("refused", 400) and "reads en, es, fr" in got[2] and "not 'uk'" in got[2] and engine.asked[-1]["text"] != "Hello",
          f"negative: a language the engine does not read — 400, the engine not asked ({got})")
    engine.rate = 16000
    got = speak({"input": "Hello", "voice": "anna", "response_format": "pcm"})
    check(got[:2] == ("refused", 400) and "pcm is 24000 Hz" in got[2] and "ask for wav" in got[2],
          f"negative: pcm from an engine not at 24 kHz — refused rather than played at the wrong pace ({got})")
    check(speak({"input": "Hello", "voice": "anna"})[0] == 200, "the same engine's WAV says its own rate")
    engine.rate = 24000
    long_shelf = box.shelf("long")
    long_cell = tts.TtsCell(["0", "cosyvoice"], shelf=long_shelf)
    long_cell.voice_engine = Fake(max_sample=30)
    got = answer(lambda: long_cell.handle(json.dumps({"input": "Hi", "ref_audio": data_url(LONG)}).encode(), headers, "/v1/audio/speech"))
    check(got[:2] == ("refused", 400) and "the sample is 40.0 s: cosyvoice takes a voice from at most 30 s" in got[2]
          and long_cell.voice_engine.asked == [],
          f"negative: a sample longer than the engine takes — 400 before the engine is asked ({got})")
    got = answer(lambda: long_cell.handle(json.dumps({"input": "Hi", "ref_audio": data_url(VOICE)}).encode(), headers, "/v1/audio/speech"))
    check(got[0] == 200, "a sample within it is spoken")
    body, form_headers = multipart([("text", "hello"), ("lang", "en")], [("ref", "ref.wav", VOICE)])
    for path in ("/v1/audio/speech-clone", "/speech-clone"):
        got = answer(lambda: cell.handle(body, form_headers, path))
        check(got[0] == 200 and got[2] == "audio/wav" and engine.asked[-1]["lang"] == "en" and engine.asked[-1]["wav"] == VOICE,
              f"the voice app's form on {path}: spoken, a WAV back")
    body, form_headers = multipart([("name", "Boris"), ("consent", "yes")], [("audio_sample", "s.wav", VOICE)])
    got = answer(lambda: cell.handle(body, form_headers, "/v1/audio/voices"))
    check(got[0] == 200 and got[1]["success"] is True and got[1]["voice"]["name"] == "Boris" and got[2] == "application/json",
          "a voice kept through the cell")
    check(cell.handle_get("/v1/audio/voices", "")[1]["voices"] == ["Anna", "Boris"] and cell.handle_get("/health", "") is None,
          "listed through the cell's GET; any other GET is the base's (health)")
    got = refusal(lambda: cell.handle(b"{}", headers, "/v1/audio/transcriptions"))
    check(got is not None and got[0] == 404 and "no POST /v1/audio/transcriptions here" in got[1],
          f"negative: a path the cell does not answer — 404 naming the ones it does, not a voice ({got})")
    check([cell.ready_required(p) for p in ("/v1/audio/speech", "/v1/audio/speech-clone", "/speech-clone", "/v1/audio/voices", "/x")]
          == [True, True, True, False, False],
          "only speaking waits for the engine: a voice is kept, and an unknown path answered, while it loads")


def main():
    box = Box()
    try:
        section_language()
        section_engines()
        section_device()
        section_reader(box)
        section_sample(box)
        section_shelf(box)
        section_ask(box)
        section_cell(box)
    finally:
        box.close()
    print()
    if _fail:
        print(f"tts server: {len(_fail)} FAILED")
        return 1
    print("tts server OK: a voice from a sample, kept or sent along, through OpenAI's request and the voice app's")
    return 0


if __name__ == "__main__":
    sys.exit(main())
