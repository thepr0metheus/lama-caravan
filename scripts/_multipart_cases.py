"""One table of multipart forms, for every reader of one in the caravan.

Two copies of the rule "where a part of a form ends" are unavoidable: the entry reads a form's text fields on the
controller (rust/crates/rules/src/request_fields.rs, RequestFields) and the cells read the recording and the fields on the
machine that runs them, from a file that ships alone (cells/cell_base.py, Form). A cell cannot import from the
controller, and the controller does not ship the cell. So the two are held to ONE table: a form built here by the
format's own rule (RFC 2046: a part ends where CRLF + "--" + boundary begins), and what every reader must make of it.
A reader that drifts from the other turns its test red.

Not a test: scripts/test_cell_form.py imports it and holds contract/multipart.json, what the program reads, to it.

Each case: `id`, `why`, `body`, `ctype`, `parts` (what a reader that takes every part whole sees: name, is a file,
data — exactly, in order), `closed` (the closing delimiter is there). The entry's answer follows from those: its text
fields by name, the first of a name sent twice, or None for a form that does not close or holds no part.
"""
import random

BOUNDARY = "caravan-test-4f2a9c"
CTYPE = f"multipart/form-data; boundary={BOUNDARY}"
WAV_HEAD = b"RIFF\x24\x00\x00\x00WAVEfmt "      # what a recording starts with: no meaning to a reader, only bytes


def text(name, value, boundary=BOUNDARY, head_extra=""):
    return (name, False, value if isinstance(value, bytes) else value.encode("utf-8"), head_extra)


def file(name, data, filename="rec.wav", head_extra=""):
    return (name, True, data, head_extra, filename)


def build(parts, boundary=BOUNDARY, close=True, preamble=b"", epilogue=b"", pad=b""):
    """A form as a client sends it: each part after `--boundary` + CRLF, its head, a blank line, its data, then CRLF.
    `pad`: spaces after the boundary on its line, which RFC 2046 allows."""
    out = [preamble]
    for part in parts:
        name, is_file, data, head_extra = part[:4]
        filename = part[4] if len(part) > 4 else "rec.wav"
        head = f'Content-Disposition: form-data; name="{name}"' + (f'; filename="{filename}"' if is_file else "")
        head += head_extra
        if is_file:
            head += "\r\nContent-Type: audio/wav"
        out.append(f"--{boundary}".encode() + pad + b"\r\n" + head.encode("utf-8") + b"\r\n\r\n" + data + b"\r\n")
    if close:
        out.append(f"--{boundary}--\r\n".encode())
    out.append(epilogue)
    return b"".join(out)


def case(id, why, parts, ctype=CTYPE, closed=True, body=None, seen=None, **options):
    """`parts` build the body; `seen` (when the body is not whole) is what a reader sees of it: the parts that closed."""
    body = build(parts, **options) if body is None else body
    truth = [(p[0], p[1], p[2]) for p in (parts if seen is None else seen)]
    return {"id": id, "why": why, "body": body, "ctype": ctype, "parts": truth, "closed": closed}


def cases():
    out = []
    audio = WAV_HEAD + bytes(range(256)) * 3
    out.append(case("plain", "a form as curl sends it: fields, then the recording", [
        text("model", "gigaam-ru"), text("response_format", "verbose_json"), file("file", audio)]))
    out.append(case("file-first", "the recording first, its fields after it", [
        file("file", audio), text("language", "ru"), text("timestamp_granularities[]", "word")]))
    # The tail of the data: the byte 0x0A, 0x0D or 0x2D (an LF, a CR, a hyphen) at the end of a recording is what two cells
    # took for the form's own and cut off (the old reader: rstrip(b"\r\n-")).
    for byte in (0x0A, 0x0D, 0x2D, 0x00, 0xF6, 0x2C):
        out.append(case(f"tail-{byte:02x}", f"the recording ends in the byte {byte:#04x}: all of it is the recording", [
            text("model", "gigaam-ru"), file("file", audio + bytes([byte]))]))
    out.append(case("tail-two-lf", "two LF at the end: one sample would be lost, and the length stays even", [
        file("file", audio + b"\x0a\x0a")]))
    out.append(case("tail-three-hyphens", "three hyphens at the end of the data", [file("file", audio + b"---")]))
    out.append(case("tail-crlf", "the data ends in a CRLF of its own, before the form's", [file("file", audio + b"\r\n")]))
    out.append(case("tail-crlf-twice", "two CRLF of its own", [file("file", audio + b"\r\n\r\n")]))
    out.append(case("tail-delimiter-look", "the data ends in what looks like a delimiter without a boundary", [
        file("file", audio + b"\r\n--")]))
    out.append(case("empty-file", "a file with no bytes is b'', not nothing", [text("model", "m"), file("file", b"")]))
    out.append(case("empty-field", "a field sent empty is a part with no data", [text("language", ""), file("file", audio)]))
    out.append(case("field-ends-in-hyphens", "a text value keeps its hyphens: it is not the form's", [
        text("response_format", "verbose_json---"), file("file", audio)]))
    out.append(case("field-with-crlf", "a text value of two lines keeps both", [text("note", "a\r\nb"), file("file", audio)]))
    out.append(case("field-utf8", "a text value in UTF-8", [text("language", "русский"), file("file", audio)]))
    out.append(case("field-twice", "a name sent twice: both parts are there, in order", [
        text("timestamp_granularities[]", "word"), text("timestamp_granularities[]", "segment"), file("file", audio)]))
    out.append(case("data-looks-like-form", "the data holds a CRLF, a blank line and the look of a part's head", [
        file("file", b"x\r\n--" + BOUNDARY[:6].encode() + b"\r\n\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nz")]))
    out.append(case("data-holds-boundary-letters", "the data holds CRLF + the boundary + other letters: not a delimiter", [
        file("file", b"\x01\r\n--" + BOUNDARY.encode() + b"x\x02" + b"\r\n--" + BOUNDARY.encode() + b"-\x03")]))
    out.append(case("data-holds-boundary-no-crlf", "the data holds the boundary without a CRLF in front of it", [
        file("file", b"\x01--" + BOUNDARY.encode() + b"\x02")]))
    out.append(case("quoted-boundary", "the boundary quoted, and with a space in it", [text("model", "m"), file("file", audio)],
                    ctype='multipart/form-data; boundary="two words"', boundary="two words"))
    out.append(case("boundary-among-params", "parameters before and after the boundary", [file("file", audio)],
                    ctype=f"multipart/form-data; charset=utf-8; boundary={BOUNDARY}; x=y"))
    out.append(case("boundary-name-in-capitals", "the parameter's name in capitals", [file("file", audio)],
                    ctype=f"multipart/form-data; BOUNDARY={BOUNDARY}"))
    out.append(case("preamble-and-epilogue", "bytes before the first boundary and after the closing one are nobody's", [
        text("model", "m"), file("file", audio)], preamble=b"this is a preamble\r\n", epilogue=b"epilogue\r\n--x"))
    out.append(case("padding-after-boundary", "spaces after the boundary on its line (RFC 2046's transport padding)", [
        text("model", "m"), file("file", audio)], pad=b"  \t"))
    out.append(case("bare-name", "a name with no quotes", [text("model", "m"), file("file", audio)]) | {
        "body": build([text("model", "m"), file("file", audio)]).replace(b'name="model"', b"name=model")})
    out.append(case("header-in-lower-case", "header and parameter names are case-insensitive: lower case", [text("model", "m"), file("file", audio)]) | {
        "body": build([text("model", "m"), file("file", audio)]).replace(b"Content-Disposition", b"content-disposition")})
    out.append(case("header-in-capitals", "header and parameter names are case-insensitive: capitals", [text("model", "m"), file("file", audio)]) | {
        "body": build([text("model", "m"), file("file", audio)]).replace(b"Content-Disposition", b"CONTENT-DISPOSITION")
        .replace(b"; name=", b"; NAME=").replace(b"; filename=", b"; FILENAME=")})
    out.append(case("filename-star", "a filename in RFC 5987's spelling", [text("model", "m"), file("file", audio)]) | {
        "body": build([text("model", "m"), file("file", audio)]).replace(b'filename="rec.wav"', b"filename*=UTF-8''r%20c.wav")})
    out.append(case("file-without-filename", "a part called file that carries no filename is a field to a form's reader", [
        text("model", "m"), ("file", False, audio, "")]))
    out.append(case("two-files", "two files: both are parts, in order", [file("file", audio), file("ref", b"\x01\x02")]))
    # Forms that are not whole. What a reader sees is the parts that closed before the break.
    whole = build([text("model", "m"), file("file", audio)])
    out.append(case("cut-in-the-file", "the body ends in the middle of the recording", [], closed=False,
                    body=whole[:whole.index(b"RIFF") + 40], seen=[text("model", "m")]))
    out.append(case("no-closing-delimiter", "no closing delimiter: the last part has no end, and is no part",
                    [text("model", "m"), file("file", audio)], closed=False, close=False, seen=[text("model", "m")]))
    out.append(case("no-crlf-before-boundary", "the data runs into the boundary with no CRLF between: no delimiter, no part", [],
                    closed=False, body=f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a\"\r\n\r\n"
                                       f"DATA--{BOUNDARY}--\r\n".encode(), seen=[]))
    out.append(case("part-without-head", "a part with no head names nothing: no form from there on, and what came before it stays", [],
                    closed=False, seen=[text("model", "m")],
                    body=build([text("model", "m")], close=False) + f"--{BOUNDARY}\r\n\r\nbare data\r\n".encode() + build([text("x", "v")])))
    out.append(case("junk-after-the-boundary", "the boundary's letters followed by junk, not by a line's end: no delimiter, no form", [], closed=False, seen=[],
                    body=f"--{BOUNDARY}junk\r\nContent-Disposition: form-data; name=\"x\"\r\n\r\nv\r\n--{BOUNDARY}--\r\n".encode()))
    out.append(case("lf-only", "lines ended by LF alone are no form", [], closed=False,
                    body=f"--{BOUNDARY}\nContent-Disposition: form-data; name=\"a\"\n\nv\n--{BOUNDARY}--\n".encode(), seen=[]))
    out.append(case("closing-only", "a form with no part at all", [], body=f"--{BOUNDARY}--\r\n".encode(), seen=[]))
    out.append(case("empty-body", "no bytes", [], closed=False, body=b"", seen=[]))
    out.append(case("no-boundary-named", "a Content-Type that names no boundary", [text("model", "m"), file("file", audio)],
                    ctype="multipart/form-data", closed=False, seen=[]))
    out.append(case("not-a-form", "a JSON body with a form's Content-Type absent", [], ctype="application/json", closed=False,
                    body=b'{"model": "m"}', seen=[]))
    return out


def random_forms(count=400, seed=20261019):
    """Forms of random parts, their data drawn to look like a form's own bytes: CR, LF, hyphens, the boundary's letters."""
    rng = random.Random(seed)
    alphabet = [b"\r", b"\n", b"-", b"--", b"\r\n", b"\r\n--", b"\r\n--" + BOUNDARY[:rng.randrange(1, len(BOUNDARY))].encode(),
                BOUNDARY.encode(), b"\r\n\r\n", b"A", b"\x00", b"\xff", b"name=", b'"']
    out = []
    for index in range(count):
        parts = []
        for part in range(rng.randrange(1, 5)):
            data = b"".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 12)))
            # A boundary run followed by `--` or a line's end would be a delimiter, and the sender must not write one.
            if (b"\r\n--" + BOUNDARY.encode()) in data:
                data = data.replace(BOUNDARY.encode(), b"B")
            if rng.random() < 0.5:
                parts.append(file(f"f{part}", data))
            else:
                parts.append(text(f"t{part}", data))
        out.append(case(f"random-{index:03d}", "random parts of form-like bytes", parts))
    return out


def entry_fields(one):
    """What the entry's reader must make of a case: its text fields by name (the first of a name sent twice), or None."""
    if not one["closed"] or not one["parts"]:
        return None
    fields = {}
    for name, is_file, data in one["parts"]:
        if name and not is_file and name not in fields:
            fields[name] = data.decode("utf-8", errors="replace")
    return fields
