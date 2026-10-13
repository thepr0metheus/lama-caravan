"""A request's body, read whole before the request goes on (1.3.505)."""
import re


class RequestBody:
    """The body a client sends, taken off the connection whole: by its Content-Length, or chunk by
    chunk when it comes so (`Transfer-Encoding: chunked` — curl uploading a pipe, a client streaming
    a file it does not measure first).

    The proxy read the length alone until 1.3.505. A body sent in chunks went upstream as none: a
    cell was asked an empty question, a consumer of the entry was told its request was neither JSON
    nor a form — and the chunks were left unread on a connection the answer then closed, which can
    reset it under the answer. Read whole either way, the body goes upstream with its own length,
    never with the client's framing (HOP_HEADERS drops Transfer-Encoding, and the length is said
    again for the body that goes).

    No limit on the size: a body by its length never had one here, and one for chunks alone would
    make the two ways answer differently. A body that cannot be read as the request says it is sent
    is `Malformed`: its caller refuses it with 400, and the connection goes with the answer.
    """

    class Malformed(ValueError):
        """The body cannot be read as the request says it is sent; the message says why."""

    #: The longest line a chunk's size may take, its extensions with it.
    LINE = 4096
    #: The most trailer lines after the last chunk: a client sends none or a few.
    TRAILERS = 64
    SIZE = re.compile(rb"[0-9A-Fa-f]+")

    @classmethod
    def read(cls, headers, rfile):
        """The body as bytes; None when the request carries none (no length, or 0, and no chunks).
        `headers` is the request's http.client.HTTPMessage: a header given twice is read as one."""
        codings = [c.strip().lower() for value in (headers.get_all("Transfer-Encoding") or [])
                   for c in value.split(",") if c.strip()]
        if codings:
            if codings != ["chunked"]:
                raise cls.Malformed(f"Transfer-Encoding {', '.join(codings)} is not read: "
                                    "send the body by its length or in chunks")
            return cls.chunks(rfile)
        lengths = {str(v).strip() for v in (headers.get_all("Content-Length") or [])}
        if len(lengths) > 1:
            raise cls.Malformed("Content-Length is given twice, differently")
        raw = lengths.pop() if lengths else ""
        if not raw:
            return None
        if not (raw.isascii() and raw.isdigit()):
            raise cls.Malformed("Content-Length is not a number")
        length = int(raw)
        if not length:
            return None
        body = rfile.read(length)
        if len(body) < length:
            raise cls.Malformed(f"the body ended after {len(body)} of its {length} bytes")
        return body

    @classmethod
    def chunks(cls, rfile):
        """The chunks' data joined: each a hex size line (`;` extensions stepped over), its bytes, a
        line end; the last of size 0, then the trailers up to a blank line — read and let go."""
        parts = []
        while True:
            line = rfile.readline(cls.LINE + 1)
            if not line.endswith(b"\n"):
                raise cls.Malformed("a chunk's size line is too long" if len(line) > cls.LINE
                                    else "the body ended inside its chunks")
            size = line.split(b";", 1)[0].strip()
            if not cls.SIZE.fullmatch(size):
                raise cls.Malformed("a chunk's size is not a hex number")
            count = int(size, 16)
            if not count:
                cls.trailers(rfile)
                return b"".join(parts)
            data = rfile.read(count)
            if len(data) < count:
                raise cls.Malformed("the body ended inside a chunk")
            parts.append(data)
            if rfile.readline(cls.LINE + 1) not in (b"\r\n", b"\n"):
                raise cls.Malformed("a chunk does not end where its size says")

    @classmethod
    def trailers(cls, rfile):
        """The fields after the last chunk, up to the blank line that ends the body. A client that
        closes after the last chunk has ended it too."""
        for _ in range(cls.TRAILERS):
            line = rfile.readline(cls.LINE + 1)
            if line in (b"\r\n", b"\n", b""):
                return
        raise cls.Malformed(f"more than {cls.TRAILERS} trailer lines")
