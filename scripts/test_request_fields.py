#!/usr/bin/env python3
"""Value snapshot: what a client's POST asks for — caravan/common/request_fields.py (1.3.501).

The defect: the entry read every body as JSON. A recording to transcribe travels as a form
(multipart/form-data, OpenAI's way where it takes a file), so sinapse's ears were answered 400 and
could not come in by its key.

Pinned. A JSON object is its fields, whatever type the client named; anything else that is not
JSON is no fields. A form gives its text fields by name — quoted or bare boundary, a field sent
twice keeps its first value, a part with a filename is stepped over however its bytes look, a field
too long to be a value is no value — and a form that does not read as one (no boundary, no part,
no end) is no fields at all. The form is read without decoding the file: a megabyte of audio is
stepped over, not walked.

Run: python3 scripts/test_request_fields.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from caravan.common.request_fields import RequestFields  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def form(fields, files=(), boundary="caravan-test", end=True):
    """A form as a client sends it: fields, then files (name, filename, bytes)."""
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode() for n, v in fields]
    parts += [f'--{boundary}\r\nContent-Disposition: form-data; name="{n}"; filename="{f}"\r\n'
              f"Content-Type: audio/wav\r\n\r\n".encode() + data + b"\r\n" for n, f, data in files]
    return b"".join(parts) + (f"--{boundary}--\r\n".encode() if end else b"")


CTYPE = "multipart/form-data; boundary=caravan-test"
# A recording whose bytes hold what a form's text holds: a fake boundary, a blank line, a name.
WAV = b"RIFF\x00\x01" + b"\r\n--caravan\r\n\r\nname=\"model\"\r\n" + bytes(range(256)) * 4


def section_json():
    print("тело JSON — его поля, как раньше:")
    body = json.dumps({"model": "Standart", "messages": []}).encode()
    check(RequestFields.fields("application/json", body) == {"model": "Standart", "messages": []}, "объект JSON — его поля")
    check(RequestFields.fields("", body) == {"model": "Standart", "messages": []}
          and RequestFields.fields("text/plain", body) == {"model": "Standart", "messages": []},
          "тип не назван или назван не тот — тело всё равно читается как JSON: так служили и до форм")
    for raw, why in ((b"[1, 2]", "массив"), (b"model=Econom", "не JSON"), (b"", "пустое тело"), (b"\xff\xfe{}", "не UTF-8")):
        check(RequestFields.fields("application/json", raw) is None, f"negative: {why} — полей нет")


def section_form():
    print("форма — её текстовые поля, файл не читается:")
    body = form([("model", "gigaam-ru"), ("response_format", "verbose_json"), ("timestamp_granularities[]", "word"),
                 ("language", "ru")], [("file", "audio.wav", WAV)])
    check(RequestFields.fields(CTYPE, body) == {"model": "gigaam-ru", "response_format": "verbose_json",
                                              "timestamp_granularities[]": "word", "language": "ru"},
          "поля формы по именам; файл пропущен, хотя в нём есть и граница, и пустая строка, и name=\"model\"")
    check(RequestFields.fields('Multipart/Form-Data; charset=utf-8; boundary="caravan-test"', body)["model"] == "gigaam-ru",
          "тип в любом регистре, граница в кавычках, лишний параметр — та же форма")
    first = form([("model", "whisper"), ("model", "gigaam")], [("file", "a.wav", b"x")])
    check(RequestFields.fields(CTYPE, first)["model"] == "whisper", "поле дважды — берётся первое")
    swapped = form([], [("file", "a.wav", WAV)], end=False) + form([("model", "seamless")])
    check(RequestFields.fields(CTYPE, swapped) == {"model": "seamless"}, "файл раньше полей — поле всё равно найдено")
    named_file = form([], [("model", "model.txt", b"not-a-name")])
    check(RequestFields.fields(CTYPE, named_file) == {}, "negative: часть с именем файла — не значение, даже если её имя model")
    long_field = form([("model", "x" * (RequestFields.FIELD_MAX + 1))])
    check(RequestFields.fields(CTYPE, long_field) == {}, "negative: поле длиннее значения — не значение")
    check(RequestFields.fields(CTYPE, form([("model", "Ухо 🎧")]))["model"] == "Ухо 🎧", "значение в UTF-8")


def section_unreadable():
    print("форма, которая не читается, — не поля:")
    body = form([("model", "gigaam-ru")], [("file", "a.wav", WAV)])
    for ctype, raw, why in (("multipart/form-data", body, "граница не названа"),
                            ("multipart/form-data; boundary=other", body, "граница не та"),
                            (CTYPE, b"", "пустое тело"),
                            (CTYPE, b"--caravan-test--\r\n", "ни одной части"),
                            (CTYPE, form([("model", "x")], end=False)[:-2], "нет конца"),
                            (CTYPE, b"--caravan-test\r\nContent-Disposition: form-data; name=\"model\"", "нет пустой строки после заголовка"),
                            (CTYPE, b"--caravan-testX\r\n", "после границы мусор")):
        check(RequestFields.fields(ctype, raw) is None, f"negative: {why} — None, вход ответит 400")


def section_speed():
    print("файл в мегабайт не читается по байтам:")
    big = form([("model", "gigaam-ru")], [("file", "a.wav", os.urandom(1024 * 1024))])
    start = time.perf_counter()
    for _ in range(20):
        fields = RequestFields.fields(CTYPE, big)
    took = (time.perf_counter() - start) / 20
    check(fields == {"model": "gigaam-ru"} and took < 0.02,
          f"запись в 1 МБ разобрана за {took * 1000:.2f} мс (предел 20 мс): поиск границы, а не разбор файла")


def main():
    for fn in (section_json, section_form, section_unreadable, section_speed):
        fn()
    if _fail:
        print(f"\nrequest fields FAILED: {len(_fail)}")
        for m in _fail:
            print("  - " + m)
        return 1
    print("\nrequest fields OK: JSON — его поля; форма — её текстовые поля, файл не читается; нечитаемое — None")
    return 0


if __name__ == "__main__":
    sys.exit(main())
