"""What a client's POST asks for, read the way its type says it travels.

The entry picks a consumer's pool by the request's `model` (caravan/proxy/entry.py). OpenAI's API
takes that field in a JSON body almost everywhere, and in a form where it takes a file: speech to
text sends the recording as multipart/form-data (POST /v1/audio/transcriptions). Until 1.3.501 the
entry read every body as JSON and answered such a request 400 — sinapse's ears could not come in by
its key (the owner, 2026-10-12: "everything it needs by its token").

A form is read for its text fields alone, and without a parser that walks the file: the ears send a
growing recording twice a second, up to a megabyte each (sinapse, 2026-10-12), through the NAS's
small processor. The boundary is found by `bytes.find`, a part's head is read up to its blank line,
and a part with a filename is stepped over, never copied or decoded. The body itself goes on to the
pool's row as it came.
"""
import json


class RequestFields:
    """A POST body's fields: the JSON object it is, or a form's text fields by name — None for a
    body that is neither, or does not read as the type it claims."""

    FORM = "multipart/form-data"
    #: The most of a form's text field that is kept. A field is a model's name or a language's
    #: code; a "field" this long is a file without its filename, and is not a value.
    FIELD_MAX = 64 * 1024

    @classmethod
    def is_form(cls, content_type):
        return str(content_type or "").split(";", 1)[0].strip().lower() == cls.FORM

    @classmethod
    def fields(cls, content_type, body):
        """The fields of `body` as `content_type` says it travels. Anything but a form is read as
        JSON, the type named or not: a client that sends JSON without saying so was served before
        forms were read, and still is."""
        if cls.is_form(content_type):
            return cls.form(content_type, body)
        try:
            payload = json.loads(body.decode("utf-8")) if body else None
        except (UnicodeDecodeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def boundary(content_type):
        """The form's boundary from its Content-Type, quoted or bare; "" when it names none."""
        for param in str(content_type or "").split(";")[1:]:
            name, _, value = param.strip().partition("=")
            if name.strip().lower() == "boundary":
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    value = value[1:-1]
                return value
        return ""

    @staticmethod
    def _disposition(head):
        """(name, has a filename) of a part, from its head's Content-Disposition."""
        for line in head.split(b"\r\n"):
            key, _, value = line.partition(b":")
            if key.strip().lower() != b"content-disposition":
                continue
            name, filename = None, False
            for param in value.decode("utf-8", errors="replace").split(";")[1:]:
                key2, _, raw = param.strip().partition("=")
                key2 = key2.strip().lower()
                raw = raw.strip()
                if len(raw) >= 2 and raw[0] == raw[-1] == '"':
                    raw = raw[1:-1]
                if key2 == "name":
                    name = raw
                elif key2 in ("filename", "filename*"):
                    filename = True
            return name, filename
        return None, False

    @classmethod
    def form(cls, content_type, body):
        """A form's text fields by name — the first of a name sent twice — or None for a form that
        does not read as one: no boundary, no part, a part with no head or no end."""
        boundary = cls.boundary(content_type)
        body = body or b""
        if not boundary:
            return None
        mark = b"--" + boundary.encode("latin-1", errors="replace")
        at = body.find(mark)
        if at < 0:
            return None
        fields, parts = {}, 0
        while True:
            at += len(mark)
            if body[at:at + 2] == b"--":
                return fields if parts else None
            if body[at:at + 2] != b"\r\n":
                return None
            head_end = body.find(b"\r\n\r\n", at + 2)
            if head_end < 0:
                return None
            name, is_file = cls._disposition(body[at + 2:head_end])
            nxt = body.find(b"\r\n" + mark, head_end + 4)
            if nxt < 0:
                return None
            parts += 1
            if name and not is_file and name not in fields and nxt - (head_end + 4) <= cls.FIELD_MAX:
                fields[name] = body[head_end + 4:nxt].decode("utf-8", errors="replace")
            at = nxt + 2
