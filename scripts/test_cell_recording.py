#!/usr/bin/env python3
"""Value snapshot: the cells' one reader of a recording (cells/cell_base.py `Recording`, 1.3.610) and the cells that
hear through it — transcribe.cpp (GigaAM), moonshine, seamless, LFM2.5-Audio.

Open WebUI sends what the browser records (webm), and a client may send mp3 or m4a. Until 1.3.610 moonshine and
transcribe.cpp read a WAV alone and answered anything else "bad wav", seamless had an ffmpeg path of its own, and
LFM2.5-Audio read with soundfile (neither webm, mp3 nor m4a). Now one reader: a 16-bit WAV itself, anything else
through ffmpeg; a machine without ffmpeg refuses (415) and says so.

Pinned by value, each claim with a positive and a negative: a 16-bit WAV read without ffmpeg — mono, the first
channel of a stereo one, at its own rate, or through ffmpeg when the cell names another rate; anything else (and a
WAV of other samples, and a broken one) through ffmpeg with the exact arguments, its float samples read back; no
ffmpeg — 415 with the reason; ffmpeg's own refusal — 400 with its words; an empty recording — 400; the cell base
answers a Refusal with its status and words and any other exception with 500; a recording is written back as the
same bytes (×32768, rounded, clipped); transcribe.cpp and moonshine hand a
compressed recording to their engines as samples; no cell of cells/ reads audio but through the reader.

ffmpeg is a stand-in (a script) that writes down its arguments and its input and answers known samples: the machine's
own ffmpeg is never asked, so the answer is the same on every machine.

Run: python3 scripts/test_cell_recording.py
"""
import array
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELLS = ROOT / "cells"
sys.path.insert(0, str(CELLS))

import cell_base  # noqa: E402
from cell_base import CellServer, Recording, Refusal  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refusal(fn):
    """(status, words) of the Refusal `fn` raises; None when it raises none. Any other exception is a wrong answer
    here, not the end of the run: ("raised", what)."""
    try:
        fn()
    except Refusal as exc:
        return exc.status, str(exc)
    except Exception as exc:  # noqa: BLE001
        return "raised", f"{type(exc).__name__}: {exc}"
    return None


def answer(fn):
    """What `fn` returns, or what it raised instead, as ("refused" | "raised", ...): a step that breaks is a red check."""
    try:
        return fn()
    except Refusal as exc:
        return "refused", exc.status, str(exc)
    except Exception as exc:  # noqa: BLE001
        return "raised", f"{type(exc).__name__}: {exc}"


# The stand-in: its arguments to $LOG, its input to $LOG.in, and the bytes of $FFMPEG_OUT as its output — or, with
# $FFMPEG_FAIL set, those words on stderr and exit 1, as ffmpeg does with a file it cannot read.
FFMPEG = r'''#!/bin/bash
printf '%s\n' "$@" > "$LOG"
cat > "$LOG.in"
if [ -n "$FFMPEG_FAIL" ]; then echo "$FFMPEG_FAIL" >&2; exit 1; fi
cat "$FFMPEG_OUT"
'''


class StandIn:
    """A folder with the stand-in ffmpeg and its log."""

    def __init__(self):
        self.dir = Path(tempfile.mkdtemp(prefix="caravan-recording-"))
        self.bin = self.dir / "ffmpeg"
        self.bin.write_text(FFMPEG)
        self.bin.chmod(0o755)
        self.log = self.dir / "args.log"
        self.out = self.dir / "out.f32"
        os.environ["LOG"] = str(self.log)
        os.environ["FFMPEG_OUT"] = str(self.out)
        os.environ.pop("FFMPEG_FAIL", None)

    def answers(self, floats, extra=b""):
        """The samples the stand-in hands back, as ffmpeg's f32le; `extra` trails them (a cut last sample)."""
        self.out.write_bytes(struct.pack(f"<{len(floats)}f", *floats) + extra)
        if self.log.exists():
            self.log.unlink()

    def args(self):
        return self.log.read_text().splitlines() if self.log.exists() else None

    def got(self):
        return Path(str(self.log) + ".in").read_bytes()

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def wav(samples, rate=16000, channels=1, width=2):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        if width == 2:
            wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        else:
            wf.writeframes(b"".join(int(s).to_bytes(width, "little", signed=True) for s in samples))
    return buf.getvalue()


WEBM = b"\x1aE\xdf\xa3" + b"webm, as a browser records it" * 8
ARGS = ["-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"]


def section_the_wav(box):
    print("a 16-bit WAV is read without ffmpeg:")
    box.answers([9.0])
    rec = Recording.decode(wav([0, 16384, -16384, 32767]), ffmpeg=str(box.bin))
    check(list(rec.samples) == [0.0, 0.5, -0.5, 32767 / 32768] and rec.rate == 16000 and box.args() is None,
          f"mono at 16 kHz: its samples, its rate, ffmpeg not asked ({list(rec.samples)}, {rec.rate})")
    check(rec.samples.typecode == "f", "the samples are floats of 32 bits, as every engine of the fleet takes them")
    rec = Recording.decode(wav([1000, -1000, 2000, -2000], channels=2), ffmpeg=str(box.bin))
    check(list(rec.samples) == [1000 / 32768, 2000 / 32768] and box.args() is None,
          f"stereo: the first channel, as moonshine and transcribe.cpp read it ({list(rec.samples)})")
    rec = Recording.decode(wav([100, 200, 300], rate=48000), ffmpeg=str(box.bin))
    check(rec.rate == 48000 and len(rec.samples) == 3 and box.args() is None,
          "at 48 kHz with no rate asked: read at its own rate — the cell resamples (transcribe.cpp) or takes the rate (moonshine)")
    box.answers([0.125, -0.125])
    raw = wav([100, 200, 300], rate=48000)
    rec = Recording.decode(raw, rate=16000, ffmpeg=str(box.bin))
    check(box.args() == ARGS and box.got() == raw and list(rec.samples) == [0.125, -0.125] and rec.rate == 16000,
          f"at 48 kHz when the cell wants 16 kHz (seamless): ffmpeg brings it there ({box.args()})")
    box.answers([0.25])
    rec = Recording.decode(wav([1, 2, 3], rate=16000), rate=16000, ffmpeg=str(box.bin))
    check(box.args() is None and rec.rate == 16000, "negative: a WAV already at the rate asked is not sent to ffmpeg")


def section_everything_else(box):
    print("anything else goes through ffmpeg:")
    box.answers([0.25, -0.25, 0.5])
    rec = answer(lambda: Recording.decode(WEBM, ffmpeg=str(box.bin)))
    check(box.args() == ARGS, f"ffmpeg is asked for mono float samples at 16 kHz on its standard output: {box.args()}")
    check(box.got() == WEBM, "the recording goes to ffmpeg as it came, on its input")
    check(isinstance(rec, Recording) and list(rec.samples) == [0.25, -0.25, 0.5] and rec.rate == 16000 and rec.samples.typecode == "f",
          f"its samples are read back as floats at the rate asked ({getattr(rec, 'samples', rec)})")
    box.answers([0.75])
    rec = Recording.decode(WEBM, rate=24000, ffmpeg=str(box.bin))
    check(box.args()[-2:] == ["24000", "pipe:1"] and rec.rate == 24000, "a cell that names its rate gets it from ffmpeg")
    for name, raw in (("a WAV of 24-bit samples", wav([1, -1, 2], width=3)),
                      ("a broken WAV (its header, then nothing a WAV holds)", b"RIFF\x24\x00\x00\x00WAVE" + b"\x00" * 7),
                      ("an mp3", b"ID3\x04\x00" + b"\x00" * 40), ("an ogg", b"OggS" + b"\x00" * 40)):
        box.answers([0.5])
        rec = Recording.decode(raw, ffmpeg=str(box.bin))
        check(box.args() == ARGS and list(rec.samples) == [0.5], f"{name}: read by ffmpeg, not taken for PCM")
    box.answers([0.5, 0.25], extra=b"\x01\x02")
    rec = answer(lambda: Recording.decode(WEBM, ffmpeg=str(box.bin)))
    check(isinstance(rec, Recording) and list(rec.samples) == [0.5, 0.25], f"a cut last sample is dropped, not read as a number ({rec})")


def section_refusals(box):
    print("what the reader refuses:")
    got = refusal(lambda: Recording.decode(WEBM, ffmpeg="no-such-ffmpeg-here"))
    check(got is not None and got[0] == 415 and "no ffmpeg" in got[1] and "send a WAV" in got[1],
          f"no ffmpeg on the machine: 415, and what to do ({got})")
    check(refusal(lambda: Recording.decode(wav([1, 2]), ffmpeg="no-such-ffmpeg-here")) is None,
          "negative: a 16-bit WAV is read on a machine without ffmpeg")
    os.environ["FFMPEG_FAIL"] = "Invalid data found when processing input"
    try:
        got = refusal(lambda: Recording.decode(WEBM, ffmpeg=str(box.bin)))
    finally:
        os.environ.pop("FFMPEG_FAIL", None)
    check(got == (400, "ffmpeg could not read the recording: Invalid data found when processing input"),
          f"a recording ffmpeg cannot read: 400 with ffmpeg's own words ({got})")
    check(refusal(lambda: Recording.decode(b"", ffmpeg=str(box.bin))) == (400, "the recording is empty"),
          "an empty recording: 400, and ffmpeg is not asked")


def section_written_back():
    print("a recording written back (Recording.wav, 1.3.611):")
    raw = wav([0, 16384, -16384, 32767, -32768, 1, -1, 12345])
    check(Recording.decode(raw).wav() == raw, "a 16-bit WAV read and written again: the same bytes, header and samples")
    check(Recording.pcm16([1.5, -2.0, 0.5, -0.5, 1.0]) == struct.pack("<5h", 32767, -32768, 16384, -16384, 32767),
          "×32768 and clipped at both ends: the inverse of the reader's ÷32768")
    check(Recording.pcm16([0.5 / 32768, 1.5 / 32768, 2.5 / 32768]) == struct.pack("<3h", 0, 2, 2),
          "rounded, half to even — not cut toward zero")
    check(Recording.pcm16([0.5]) != struct.pack("<h", 16383),
          "negative: not the old writers' ×32767 cut, which turned a read WAV into another one")

    class EngineArray:
        """What an engine answers (a numpy array): read through its tolist()."""

        def tolist(self):
            return [0.25, -0.25]
    check(Recording.pcm16(EngineArray()) == struct.pack("<2h", 8192, -8192), "an engine's array: through its tolist()")
    out = Recording([0.25, -0.25], 24000).wav()
    with wave.open(io.BytesIO(out), "rb") as wf:
        said = (wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.readframes(wf.getnframes()))
    check(said == (1, 2, 24000, struct.pack("<2h", 8192, -8192)), f"a WAV of 16-bit mono at the recording's rate ({said[:3]})")


class Speaker(CellServer):
    """A cell for the base's answers: what it does is what the test tells it."""

    engine = "test"
    model_name = "test"
    kinds = ["asr"]

    def __init__(self, then):
        super().__init__(["0"])
        self.then = then
        self.state.update(ready=True, phase="ok")

    def load(self):
        pass

    def handle(self, body, headers, path):
        return self.then()


def post(port):
    request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/audio/transcriptions", data=b"x", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def section_the_base():
    print("the cell base answers a refusal with its own status:")
    for name, then, want in (
            ("a Refusal", lambda: (_ for _ in ()).throw(Refusal(415, "no ffmpeg here")), (415, {"error": "no ffmpeg here"})),
            ("any other exception", lambda: (_ for _ in ()).throw(ValueError("boom")), (500, {"error": "ValueError: boom"})),
            ("an answer", lambda: (200, {"text": "ok"}, "application/json"), (200, {"text": "ok"}))):
        server = cell_base._Server(("127.0.0.1", 0), cell_base._handler_for(Speaker(then)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            got = post(server.server_address[1])
        finally:
            server.shutdown()
            server.server_close()
        check(got == want, f"{name}: {got}")


def form(raw, fields=()):
    b = "caravan-test"
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="talk.webm"\r\n'
                 f"Content-Type: audio/webm\r\n\r\n".encode() + raw + b"\r\n")
    return b"".join(parts) + f"--{b}--\r\n".encode(), {"Content-Type": f"multipart/form-data; boundary={b}"}


class Said:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def section_the_cells(box):
    print("the cells that hear read through it:")
    # The stand-in is the machine's ffmpeg for the cells: first on the PATH.
    os.environ["PATH"] = f"{box.dir}{os.pathsep}{os.environ.get('PATH', '')}"
    import transcribe_server as ts
    heard = []

    class Session:
        def run(self, piece):
            heard.append(list(piece))
            return Said(text="привет", tokens=())

    box.answers([0.25, -0.25, 0.5])
    keep = ts._session
    ts._session = Session()
    try:
        body, headers = form(WEBM)
        got = answer(lambda: ts.TranscribeCell(["0", "m.gguf"]).handle(body, headers, "/v1/audio/transcriptions"))
    finally:
        ts._session = keep
    check(got[0] == 200 and json.loads(got[1]) == {"text": "привет"} and heard == [[0.25, -0.25, 0.5]] and box.args() == ARGS,
          f"transcribe.cpp (GigaAM): a webm reaches the engine as ffmpeg's samples, at 16 kHz ({got[:2]}, {heard})")
    body, headers = form(wav([16384, -16384]))
    heard.clear()
    ts._session = Session()
    try:
        got = answer(lambda: ts.TranscribeCell(["0", "m.gguf"]).handle(body, headers, "/v1/audio/transcriptions"))
    finally:
        ts._session = keep
    check(got[0] == 200 and heard == [[0.5, -0.5]], f"negative: a WAV still reaches it as before, without ffmpeg ({got[:2]})")
    os.environ["FFMPEG_FAIL"] = "Invalid data found when processing input"
    try:
        ts._session = Session()
        body, headers = form(b"\x00garbage")
        got = refusal(lambda: ts.TranscribeCell(["0", "m.gguf"]).handle(body, headers, "/v1/audio/transcriptions"))
    finally:
        os.environ.pop("FFMPEG_FAIL", None)
        ts._session = keep
    check(got is not None and got[0] == 400 and "Invalid data" in got[1],
          f"a recording nobody can read: the reader's refusal, which the base answers with 400 ({got})")

    import moonshine_server as ms
    taken = []

    class Transcriber:
        def transcribe_without_streaming(self, audio, rate):
            taken.append((list(audio), rate))
            return Said(lines=[Said(text="hello")])

    box.answers([0.5, 0.25])
    keep = ms._transcriber
    ms._transcriber = Transcriber()
    try:
        body, headers = form(WEBM)
        got = answer(lambda: ms.MoonshineCell(["0", "en"]).handle(body, headers, "/v1/audio/transcriptions"))
    finally:
        ms._transcriber = keep
    check(got[0] == 200 and json.loads(got[1]) == {"text": "hello"} and taken == [([0.5, 0.25], 16000)],
          f"moonshine: a webm reaches it as samples and their rate ({got[:2]}, {taken})")


#: What reading a recording looks like in a cell's code. Only cell_base may do it.
READERS = re.compile(r'soundfile\.read|librosa\.load|torchaudio\.load|wave\.open\([^)]*"rb"|"ffmpeg"')


def section_one_reader():
    print("one reader in cells/:")
    found = {p.name: READERS.findall(p.read_text(encoding="utf-8")) for p in sorted(CELLS.glob("*.py")) if p.name != "cell_base.py"}
    readers = {name: hits for name, hits in found.items() if hits}
    check(readers == {}, f"no cell reads a recording but through cell_base.Recording: {readers}")
    check(bool(READERS.findall((CELLS / "cell_base.py").read_text(encoding="utf-8"))),
          "the rule sees the reader where it is (cell_base): it is no rule that finds nothing anywhere")
    planted = 'wav, rate = soundfile.read(io.BytesIO(raw))\nproc = subprocess.run(["ffmpeg", "-i", "pipe:0"])\nwave.open(b, "rb")'
    check(len(READERS.findall(planted)) == 3, "negative: the three ways a reader came back are seen (soundfile, ffmpeg, wave)")
    hearing = ("transcribe_server.py", "moonshine_server.py", "seamless_server.py", "lfm_audio_server.py")
    check(all("Recording.decode(" in (CELLS / name).read_text(encoding="utf-8") for name in hearing),
          f"the four cells that hear a recording read it with Recording.decode: {hearing}")


def main():
    box = StandIn()
    try:
        section_the_wav(box)
        section_everything_else(box)
        section_refusals(box)
        section_written_back()
        section_the_base()
        section_the_cells(box)
        section_one_reader()
    finally:
        box.close()
    print()
    if _fail:
        print(f"cell recording: {len(_fail)} FAILED")
        return 1
    print("cell recording OK: one reader of a recording for every cell that hears")
    return 0


if __name__ == "__main__":
    sys.exit(main())
