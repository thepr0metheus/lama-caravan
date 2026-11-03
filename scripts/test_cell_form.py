#!/usr/bin/env python3
"""Value snapshot: how a cell reads a form — `Form` in cells/cell_base.py (1.3.602).

The defect (2026-10-19, sinapse's live ears): five cell servers each carried their own reader of a multipart form, and two of
them — transcribe (the gigaam cells) and moonshine — took `rstrip(b"\\r\\n-")` for "the CRLF before the boundary". It removes
EVERY trailing LF, CR and hyphen of the data. A recording whose last byte was 0x0A, 0x0D or 0x2D came out one byte short, and
the cell answered 400 "bad wav: bytes length not a multiple of item size": 275 of the 15 896 requests of that day, 1.7 %, each one
a red strip on the panel. Two such bytes at the end made an even length, no error, and a sample gone unsaid. The reader that was
right — whisper's, `rsplit(b"\\r\\n", 1)[0]` — was one of the five copies, and the copies had drifted apart.

Pinned by value, each claim with its negative:

  - the table of forms (scripts/_multipart_cases.py — the same one the entry's reader is held to): every case's parts, name by
    name, file by file, byte by byte; a form that is not whole is the parts that closed, and `complete` says so;
  - every possible last byte, every possible pair of last bytes, and three bytes of the three that were lost, in a form: the
    recording comes out whole;
  - what `file()`, `fields()` and `field()` answer, and what they do not;
  - the defect history: the old readers, kept here as they were, lose the byte (and the hyphens of a text value) — and the new
    one does not;
  - the transcribe cell itself, through `handle()` with a fake engine: a recording ending in 0x0A, 0x0D, 0x2D is answered 200;
  - the whisper cell the same way: each field reaches the engine, and the recording whole;
  - moonshine, seamless and tts the same way, with fakes: what each takes from the form, and the recording or the voice whole;
  - speed: a megabyte of recording twice a second is found by `bytes.find`, not walked.

Run: python3 scripts/test_cell_form.py
"""
import base64
import io
import itertools
import json
import os
import sys
import tempfile
import time
import types
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cells"))
sys.path.insert(0, str(ROOT / "scripts"))

import _multipart_cases as table  # noqa: E402
import cell_base  # noqa: E402
from cell_base import Form  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refusal_of(fn):
    """(status, words) of the cell_base.Refusal `fn` raises, or what it answered instead."""
    try:
        return fn()[:2]
    except cell_base.Refusal as exc:
        return exc.status, str(exc)


def seen(form):
    return [(part.name, part.filename is not None, part.data) for part in form.parts]


# ── the readers as they were until 1.3.601: the oracle of the defect history ────────────────────────────────────────

def old_transcribe_extract_file(body, ctype):
    import re
    m = re.search(r'boundary="?([^";,]+)"?', ctype or "")
    if not m:
        return None
    sep = ("--" + m.group(1)).encode()
    for part in body.split(sep):
        if b"filename=" not in part:
            continue
        idx = part.find(b"\r\n\r\n")
        if idx < 0:
            continue
        return part[idx + 4:].rstrip(b"\r\n-")
    return None


def old_transcribe_fields(body, ctype, name):
    import re
    m = re.search(r'boundary="?([^";,]+)"?', ctype or "")
    if not m:
        return []
    sep = ("--" + m.group(1)).encode()
    out = []
    for part in body.split(sep):
        head, _, val = part.partition(b"\r\n\r\n")
        if not _ or b'filename="' in head:
            continue
        hm = re.search(rb'name="([^"]+)"', head)
        if hm and hm.group(1).decode("utf-8", "replace").rstrip("[]") == name:
            out.append(val.rstrip(b"\r\n-").decode("utf-8", "replace").strip())
    return out


def old_moonshine_extract_file(body, ctype):
    import re
    m = re.search(r'boundary="?([^";,]+)"?', ctype or "")
    if not m:
        return None
    for part in body.split(b"--" + m.group(1).encode()):
        if b'name="file"' in part.split(b"\r\n\r\n", 1)[0]:
            payload = part.split(b"\r\n\r\n", 1)
            if len(payload) == 2:
                return payload[1].rstrip(b"\r\n-")
    return None


def old_whisper_extract_file(body, ctype):
    boundary = None
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[len("boundary="):].strip('"')
    if not boundary:
        return None
    for part in body.split(b"--" + boundary.encode()):
        head, _, rest = part.partition(b"\r\n\r\n")
        if b"filename=" in head and rest:
            return rest.rsplit(b"\r\n", 1)[0]
    return None


def section_the_table():
    print("the table of forms — what every reader must make of them:")
    named = table.cases()
    for one in named:
        form = Form(one["body"], one["ctype"])
        check(seen(form) == one["parts"] and form.complete is one["closed"], f"{one['id']}: {one['why']}")
    wrong = []
    for one in table.random_forms():
        form = Form(one["body"], one["ctype"])
        if seen(form) != one["parts"] or form.complete is not True:
            wrong.append(one["id"])
    check(not wrong, f"400 random forms of form-like bytes (CR, LF, hyphens, the boundary's letters): each one read part by part, byte "
                     f"by byte{'' if not wrong else ' — wrong: ' + ', '.join(wrong[:6])}")
    check(Form(None).parts == [] and Form(b"", None).complete is False and Form(b"x", 7).parts == [],
          "boundary: no body, no Content-Type, a Content-Type that is not text — no parts, and no exception")


def section_the_table_file():
    print("the file the program reads (contract/multipart.json) is this table:")
    rows = json.loads((ROOT / "contract" / "multipart.json").read_text(encoding="utf-8"))["cases"]
    named = {one["id"]: one for one in table.cases()}
    check([row["id"] for row in rows] == list(named), "the file holds this table's cases, in their order")
    wrong = [row["id"] for row in rows if row["id"] in named and (base64.b64decode(row["body"]), row["ctype"], row["fields"]) != (named[row["id"]]["body"], named[row["id"]]["ctype"], table.entry_fields(named[row["id"]]))]
    check(not wrong, f"each form, its header and its fields are the table's: {wrong}")


def wav_form(last, extra=b""):
    data = table.WAV_HEAD + bytes(range(1, 40)) + extra + bytes([last])
    return data, table.build([table.text("model", "gigaam-ru"), table.file("file", data), table.text("language", "ru")])


def section_every_last_byte():
    print("the end of a recording — all of it is the recording:")
    bad = []
    for last in range(256):
        data, body = wav_form(last)
        if Form(body, table.CTYPE).file() != data:
            bad.append(f"{last:#04x}")
    check(not bad, f"each of the 256 possible last bytes: the recording comes out whole{'' if not bad else ' — lost at ' + ', '.join(bad)}")
    bad = []
    for first, last in itertools.product(range(256), repeat=2):
        data = table.WAV_HEAD + bytes([first, last])
        if Form(table.build([table.file("file", data)]), table.CTYPE).file() != data:
            bad.append(f"{first:#04x} {last:#04x}")
    check(not bad, f"each of the 65 536 possible pairs of last bytes{'' if not bad else ' — lost at ' + ', '.join(bad[:6])}")
    alphabet = (0x0A, 0x0D, 0x2D, 0x00, 0x41)
    bad = []
    for tail in itertools.product(alphabet, repeat=3):
        data = table.WAV_HEAD + bytes(tail)
        if Form(table.build([table.file("file", data)]), table.CTYPE).file() != data:
            bad.append(bytes(tail).hex())
    check(not bad, f"each tail of three bytes out of LF, CR, hyphen, NUL, 'A' (125){'' if not bad else ' — lost at ' + ', '.join(bad[:6])}")


def section_the_accessors():
    print("file(), fields(), field():")
    one = table.build([table.text("model", "m"), table.file("file", b"AAA"), table.file("ref", b"BBB")])
    check(Form(one, table.CTYPE).file() == b"AAA" and Form(one, table.CTYPE).file("ref") == b"AAA",
          "file(): the first part that has a filename — whatever it is called")
    bare = table.build([table.text("model", "m"), ("file", False, b"CCC", "")])
    check(Form(bare, table.CTYPE).file() == b"CCC" and Form(bare, table.CTYPE).file("other") is None,
          "file(): no part has a filename — the part called `file` (moonshine read it so); no such part — None")
    check(Form(table.build([table.text("model", "m")]), table.CTYPE).file() is None
          and Form(table.build([table.file("file", b"")]), table.CTYPE).file() == b"",
          "negative: no file sent is None, an empty file is b'' — two answers")
    two = table.build([table.text("timestamp_granularities[]", "word"), table.text("timestamp_granularities", "segment"),
                       table.text("language", ""), table.file("language", b"not a field"), table.text("task", "translate")])
    form = Form(two, table.CTYPE)
    check(form.fields("timestamp_granularities") == ["word", "segment"]
          and form.fields("timestamp_granularities[]") == ["word", "segment"],
          "fields(): every value of a name, in order; `name[]` and `name` are one name, whichever the caller asks")
    check(form.field("language") is None and form.fields("language") == [],
          "negative: an empty value is no value, and a part with a filename is no field (the file called language)")
    check(form.field("task") == "translate" and form.field("absent") is None and form.fields("absent") == [],
          "field(): a name sent once; a name never sent — None, []")
    check(form.field("timestamp_granularities") == "word" and form.field("timestamp_granularities[]") == "word",
          "field(): of a name sent twice, the first — whichever spelling is asked for")
    check(Form(table.build([table.text("response_format", " verbose_json ")]), table.CTYPE).field("response_format") == " verbose_json ",
          "negative: a value is exactly what was sent — a cell trims what it wants trimmed")
    check(Form(table.build([table.text("language", "русский"), table.text("note", b"\xff\xfe")]), table.CTYPE).field("language") == "русский"
          and Form(table.build([table.text("note", b"\xff\xfe")]), table.CTYPE).field("note") == "\ufffd\ufffd",
          "a value is read as UTF-8, and a byte that is not UTF-8 becomes U+FFFD — it does not raise")


def section_defect_history():
    print("defect history — the readers that were, and this one:")
    for last in (0x0A, 0x0D, 0x2D):
        data, body = wav_form(last)
        old_t, old_m = old_transcribe_extract_file(body, table.CTYPE), old_moonshine_extract_file(body, table.CTYPE)
        check(old_t == data[:-1] and old_m == data[:-1] and old_whisper_extract_file(body, table.CTYPE) == data
              and Form(body, table.CTYPE).file() == data,
              f"last byte {last:#04x}: transcribe's and moonshine's old readers lose it, whisper's old reader and this one keep it")
        check(len(data) % 2 == 0 and len(old_t) % 2 == 1,
              f"last byte {last:#04x}: the cut recording is of an odd length where it was even — the cell's 400 «bytes length not a multiple of item size»")
    data, body = wav_form(0x0A, extra=b"\x0a")
    check(len(old_transcribe_extract_file(body, table.CTYPE)) == len(data) - 2 and Form(body, table.CTYPE).file() == data,
          "two trailing LF: the old reader loses both — an even length, no error, a sample gone unsaid; this one keeps them")
    body = table.build([table.text("response_format", "verbose_json---"), table.file("file", b"x")])
    check(old_transcribe_fields(body, table.CTYPE, "response_format") == ["verbose_json"]
          and Form(body, table.CTYPE).field("response_format") == "verbose_json---",
          "a text value ending in hyphens: the old transcribe reader trims them, this one does not")


def pcm_wav(last_high_byte, frames=8000):
    pcm = bytearray(2 * frames)
    pcm[-1] = last_high_byte
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(bytes(pcm))
    return out.getvalue()


def section_the_cell():
    print("the transcribe cell, through handle() with a fake engine:")
    import transcribe_server as ts

    class Session:
        def run(self, piece):
            return types.SimpleNamespace(text="ok", tokens=())
    keep = ts._session, ts._window_ms, ts._meta
    ts._session, ts._window_ms, ts._meta = Session(), 0, {}
    try:
        cell = ts.TranscribeCell(["8000"])
        for last in (0x00, 0x0A, 0x0D, 0x2D, 0xF6):
            wav = pcm_wav(last)
            code, out, _ = cell.handle(table.build([table.text("model", "gigaam-ru"), table.file("file", wav)]),
                                       {"Content-Type": table.CTYPE}, "/v1/audio/transcriptions")
            check(code == 200 and b'"ok"' in out, f"a recording whose last sample ends in {last:#04x}: answered 200 with its text (got {code} {out[:70]!r})")
        code, out, _ = cell.handle(table.build([table.text("model", "m")]), {"Content-Type": table.CTYPE}, "/v1/audio/transcriptions")
        check(code == 400 and b"need multipart file: a recording" in out, "negative: a form with no file — 400, and the words say what to send")
        # A file that is no WAV goes to ffmpeg (cells/cell_base.py Recording, 1.3.610). Asked on a PATH with no ffmpeg,
        # so the answer is the machine's own nowhere: the refusal of a machine that cannot read it.
        path = os.environ.get("PATH", "")
        os.environ["PATH"] = tempfile.mkdtemp(prefix="caravan-no-ffmpeg-")
        try:
            cell.handle(table.build([table.file("file", b"not a wav")]), {"Content-Type": table.CTYPE}, "/v1/audio/transcriptions")
            refused = None
        except cell_base.Refusal as exc:
            refused = (exc.status, str(exc))
        finally:
            os.environ["PATH"] = path
        check(refused is not None and refused[0] == 415 and "no ffmpeg" in refused[1],
              f"negative: a file that is no WAV, on a machine without ffmpeg, is refused (415) — the refusal is for the recording, not the form ({refused})")
        def ask(*fields):
            return cell.handle(table.build([*fields, table.file("file", pcm_wav(0x00))]), {"Content-Type": table.CTYPE},
                               "/v1/audio/transcriptions")
        code, out, ctype = ask(table.text("response_format", " TEXT "))
        check(code == 200 and out == b"ok\n" and ctype.startswith("text/plain"),
              "response_format ' TEXT ': the cell trims it and lower-cases it — the plain text")
        code, out, ctype = ask(table.text("response_format", "srt"))
        check(code == 200 and b" --> " in out and ctype.startswith("application/x-subrip"), "response_format srt: subtitles")
        both = ask(table.text("response_format", "verbose_json"), table.text("timestamp_granularities[]", "segment"),
                   table.text("timestamp_granularities[]", " WORD "))
        answer = json.loads(both[1])
        check(both[0] == 200 and "words" in answer and answer["segments"][0]["text"] == "ok",
              "verbose_json with the granularities segment and ' WORD ' sent as two parts: the words are in the answer, the second one too")
        only = json.loads(ask(table.text("response_format", "verbose_json"), table.text("timestamp_granularities[]", "segment"))[1])
        check("words" not in only and only["segments"], "negative: segment alone — no words in the answer")
        for fields, what in (((), "no response_format"), ((table.text("response_format", ""),), "an empty response_format"),
                             ((table.text("response_format", "  "),), "a response_format of two spaces")):
            code, out, _ = ask(*fields)
            check(code == 200 and json.loads(out) == {"text": "ok"}, f"negative: {what} — JSON with the text, as before")
        cut = table.build([table.file("file", pcm_wav(0x01))], close=False)[:-30]
        code, out, _ = cell.handle(cut, {"Content-Type": table.CTYPE}, "/v1/audio/transcriptions")
        check(code == 400 and b"need multipart file: a recording" in out, "negative: a body cut off in the recording is no recording — not a shorter one handed to the engine")
    finally:
        ts._session, ts._window_ms, ts._meta = keep


def section_the_whisper_cell():
    print("the whisper cell, through handle() with a fake model — each field reaches the engine, the recording whole:")
    import whisper_server as ws

    class Segment:
        text, start, end, words = " hello ", 0.0, 1.0, []

    class Model:
        def __init__(self):
            self.calls = []

        def transcribe(self, path, **kwargs):
            with open(path, "rb") as fh:
                self.calls.append((fh.read(), kwargs))
            return iter([Segment()]), types.SimpleNamespace(language="ru", duration=1.0)
    cell = ws.WhisperCell(["8000"])
    cell.model = Model()
    wav = pcm_wav(0x2D)
    body = table.build([table.text("model", "whisper-1"), table.text("language", "ru"), table.text("task", "translate"),
                        table.text("response_format", " VERBOSE_JSON "), table.text("timestamp_granularities[]", "segment"),
                        table.text("timestamp_granularities[]", " Word "), table.file("file", wav)])
    code, out, _ = cell.handle(body, {"Content-Type": table.CTYPE}, "/v1/audio/transcriptions")
    sent, kwargs = cell.model.calls[0] if cell.model.calls else (b"", {})
    answer = json.loads(out) if code == 200 else {}
    check(sent == wav, "the recording reaches the engine whole (its last byte is a hyphen)")
    check(kwargs.get("language") == "ru" and kwargs.get("task") == "translate" and kwargs.get("word_timestamps") is True,
          "language, task and the word granularity — sent twice, as `timestamp_granularities[]` — reach the engine")
    check(code == 200 and answer.get("task") == "translate" and answer.get("language") == "ru" and "words" in answer
          and answer.get("text") == "hello",
          "and the answer is the one asked for: ' VERBOSE_JSON ' read as verbose_json, translating, with its words from ' Word '")
    code, out, _ = cell.handle(table.build([table.file("file", wav)]), {"Content-Type": table.CTYPE}, "/v1/audio/transcriptions")
    check(code == 200 and cell.model.calls[-1][1].get("language") is None and cell.model.calls[-1][1].get("task") == "transcribe"
          and "words" not in json.loads(out),
          "negative: no fields sent — the language is left to the engine, the task is transcribe, no words")


def section_the_other_cells():
    print("moonshine, seamless and tts, through handle() with fakes — each reads its form with Form, the recording whole:")
    import moonshine_server as ms
    import seamless_server as se
    import tts_server as tt

    class Transcriber:
        def __init__(self):
            self.heard = []

        def transcribe_without_streaming(self, audio, sr):
            self.heard.append((len(audio), sr))
            return types.SimpleNamespace(lines=[types.SimpleNamespace(text="hello")])
    keep = ms._transcriber
    ms._transcriber = Transcriber()
    try:
        cell = ms.MoonshineCell(["8000"])
        for last in (0x00, 0x0A, 0x0D, 0x2D):
            code, out, _ = cell.handle(table.build([table.text("model", "moonshine"), table.file("file", pcm_wav(last))]),
                                       {"Content-Type": table.CTYPE}, "/v1/audio/transcriptions")
            check(code == 200 and json.loads(out) == {"text": "hello"} and ms._transcriber.heard[-1] == (8000, 16000),
                  f"moonshine, a recording whose last byte is {last:#04x}: the engine hears all 8000 samples")
        code, out, _ = cell.handle(table.build([table.text("model", "m")]), {"Content-Type": table.CTYPE}, "/v1/audio/transcriptions")
        check(code == 400 and b"need multipart file: a recording" in out, "negative: moonshine, a form with no file — 400")
    finally:
        ms._transcriber = keep

    asked, raws = [], []
    keep = se._decode_audio, se._translate, se._resolve_lang
    se._decode_audio = lambda raw: raws.append(raw) or [0.0] * 16000
    se._translate = lambda audio, tgt: "translated into " + tgt
    se._resolve_lang = lambda code: asked.append(code) or (code or "eng")
    try:
        cell = se.SeamlessCell(["8000"])
        wav = pcm_wav(0x0A)
        path = "/v1/audio/translations"

        def say(*fields):
            return cell.handle(table.build([*fields, table.file("file", wav)]), {"Content-Type": table.CTYPE}, path)
        code, out, _ = say(table.text("tgt_lang", "A"), table.text("target_lang", "B"), table.text("language", "C"))
        check(code == 200 and asked[-1] == "A" and out["text"] == "translated into A" and out["durationMs"] == 1000 and raws[-1] == wav,
              "seamless: tgt_lang wins over target_lang and language; the recording arrives whole (its last byte is an LF)")
        say(table.text("tgt_lang", ""), table.text("target_lang", "B"), table.text("language", "C"))
        check(asked[-1] == "B", "seamless: an empty tgt_lang is no value — target_lang is next")
        say(table.text("language", "C"))
        check(asked[-1] == "C", "seamless: language, when it is the only one sent")
        say(table.text("model", "m"))
        check(asked[-1] == "", "negative: seamless, none of the three sent — the cell asks for no language, and the default is the rule's")
        code, out, _ = cell.handle(table.build([table.text("tgt_lang", "A")]), {"Content-Type": table.CTYPE}, path)
        check(code == 400 and "file" in out["error"], "negative: seamless, a form with no file — 400")
    finally:
        se._decode_audio, se._translate, se._resolve_lang = keep

    calls = []

    class Engine(tt.VoiceEngine):
        def speak(self, text, lang, sample, speed):
            with open(sample.path, "rb") as f:
                calls.append((text, lang, f.read()))
            return [0.0], 16000

    keep = tt.Sample.CACHE
    with tempfile.TemporaryDirectory() as cache:
        tt.Sample.CACHE = cache
        try:
            cell = tt.TtsCell(["8000"], shelf=tt.VoiceShelf(os.path.join(cache, "voices")))
            cell.voice_engine = Engine()
            voice = pcm_wav(0x2D, frames=16000)

            def speak(*fields):
                return cell.handle(table.build(list(fields)), {"Content-Type": table.CTYPE}, "/v1/audio/speech-clone")
            code, out, ctype = speak(table.text("text", "  hello  "), table.text("lang", " RU "), table.file("ref", voice))
            check(code == 200 and out[:4] == b"RIFF" and ctype == "audio/wav" and calls[-1] == ("hello", "ru", voice),
                  "tts: the text and the language trimmed, the language lower-cased, the voice sample whole (its last byte is a hyphen)")
            speak(table.text("text", "hello"), table.file("ref", voice))
            check(calls[-1][1] == "en", "tts: no lang sent — English")
            for fields in ((table.text("text", ""), table.file("ref", voice)), (table.text("text", "hello"),)):
                check(refusal_of(lambda: speak(*fields)) == (400, "need text + ref wav"),
                      "negative: tts, no text or no voice sample — 400")
        finally:
            tt.Sample.CACHE = keep


def section_speed():
    print("a megabyte of recording, twice a second:")
    audio = os.urandom(1 << 20)
    body = table.build([table.text("model", "gigaam-ru"), table.file("file", audio), table.text("language", "ru")])
    began = time.perf_counter()
    form = Form(body, table.CTYPE)
    found = time.perf_counter() - began
    began = time.perf_counter()
    got = form.file()
    copied = time.perf_counter() - began
    check(got == audio and found < 0.02 and copied < 0.02,
          f"found in {found * 1000:.2f} ms, copied once in {copied * 1000:.2f} ms (limit 20 ms each): the boundary is found with find, the recording is not walked")


def main():
    section_the_table()
    section_the_table_file()
    section_every_last_byte()
    section_the_accessors()
    section_defect_history()
    section_the_cell()
    section_the_whisper_cell()
    section_the_other_cells()
    section_speed()
    print()
    if _fail:
        print(f"cell form FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("cell form OK: the table, every last byte, the accessors, the defect history, the five cells, the speed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
