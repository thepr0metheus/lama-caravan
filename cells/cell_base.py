#!/usr/bin/env python3
"""What every cell server is, minus what makes it different.

Six servers were six copies of the same skeleton: parse argv, bind the port,
load a model in a thread, answer /health, answer the work path. Two thousand
lines, `_source_stamp()` duplicated six times, and three bugs that were only
possible because each copy could drift from the others —

  * whisper answered 200 with an empty transcript when transcription threw;
  * moonshine reported no `engine`, tts no `model` or `kinds`, so a LAN scan
    could not find them by what they do;
  * seamless and translate said `langs` where transcribe said `languages`.

None of those is possible from here. The base answers /health from the contract
in rust/crates/admin/src/fleet/remote_cells.rs, and it wraps the work path so that an exception
becomes a 500 WITH its reason rather than a success with an empty body. A
subclass cannot forget what it does not write.

What a subclass must say:

    engine        which engine is inside — a LAN scan picks cells by this
    model_name    what it loaded, as the cell itself names it
    kinds         what it can do. At least one BARE job word from
                  asr | tts | translate | speech-translate | llm, optionally
                  with a dotted refinement naming the engine
                  (["asr", "stt.whisper"], ["tts.xtts"]). The bare word is
                  what a consumer choosing by job matches on; without it a
                  cell is discoverable only by those who already know its
                  engine. scripts/check_cell_kinds.py holds the vocabulary.
    load()        fetch and load; raise to fail, set phase for progress
    handle(...)   do the work; return (code, body_bytes, content_type)

and may add fields to /health by overriding `extra_health()`.

A cell that takes a form (a recording, a voice sample, a language) reads it with `Form`, below: one reader for all of them.
A cell that hears reads the recording in it with `Recording`: a WAV itself, anything else (webm, ogg, mp3, m4a — what
a browser and Open WebUI send) through ffmpeg; a cell that writes a WAV writes it with `Recording.wav`. A request it turns
down for a reason of its own is a `Refusal`: answered with that status and those words, where any other exception is a
500.
"""
import array
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _source_stamp(subclass_file):
    """Digest of the code this process is RUNNING — base and subclass together.

    Taken once at import, which is the only moment it is guaranteed to be the
    source the interpreter actually loaded. The controller refreshes these files
    in $HOME when a cell starts, so a long-running process can be older than the
    files sitting next to it; hashing per request would report the files on disk
    and hide exactly that gap.

    BOTH files, because the behaviour now lives in two: a fix to the base with
    an untouched subclass is still a cell running yesterday's code, and a stamp
    that ignored the base would call it current. rust/crates/admin/src/fleet/cell_assets.rs
    computes the same digest over the same files in the same order — if these
    two ever disagree, every cell reports "stale" forever and nobody can tell
    which ones really are.
    """
    parts = []
    for path in sorted({os.path.abspath(__file__), os.path.abspath(subclass_file)}):
        try:
            with open(path, "rb") as fh:
                parts.append(fh.read())
        except OSError:
            return ""
    return hashlib.sha256(b"\n".join(parts)).hexdigest()[:12]


class Part:
    """One part of a form: its name, its filename when it has one, and its data."""

    def __init__(self, name, filename, body, start, end):
        self.name = name
        self.filename = filename
        self._body = body
        self._start = start
        self._end = end

    @property
    def data(self):
        """The part's bytes, exactly as the client sent them. A copy, made when asked for: a recording is a megabyte."""
        return self._body[self._start:self._end]


class Form:
    """A multipart/form-data body, read by the rule of RFC 2046 and by nothing else.

    A part's data ends where the delimiter begins, and the delimiter is CRLF + "--" + boundary: the CRLF in front
    of the boundary belongs to the delimiter, not to the data. Nothing is stripped from a part, because nothing at
    the end of it is the form's.

    Five cell servers had five copies of this reader, and two of them took `rstrip(b"\\r\\n-")` for "the CRLF before the
    boundary": it removes EVERY trailing 0x0A, 0x0D and 0x2D of the data. A WAV whose last sample ended in one of them lost
    a byte, and the cell answered 400 "bad wav: bytes length not a multiple of item size"; with two such bytes it lost both
    and read the rest as a shorter recording, saying nothing. sinapse's live ears, which send a growing recording twice a
    second, were refused 1.7 % of the time (275 of 15 896 requests, 2026-10-19), and the panel's strips went red. The reader
    that was right (whisper's: `rsplit(b"\\r\\n", 1)[0]`) was one of the five copies, and the copies had drifted apart.

    A body that does not read as a form — no boundary, a part with no head, a part that never ends, a delimiter with no CRLF
    in front of it — gives the parts that came whole before the break, and `complete` says whether the closing delimiter was seen. It is never guessed at: the old readers handed
    a cut-off recording to the engine as if it were whole.
    """

    #: Where a part's head ends and its data begins.
    HEAD_END = b"\r\n\r\n"
    CRLF = b"\r\n"
    #: `; name="value"` of a header: the value quoted (with escapes) or bare.
    PARAM = re.compile(r';\s*([A-Za-z0-9_*-]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^;]*)')

    def __init__(self, body, content_type=""):
        self.body = body or b""
        self.parts = []
        self.complete = False
        boundary = self.boundary(content_type)
        self.mark = b"--" + boundary.encode("latin-1", errors="replace") if boundary else b""
        if self.mark:
            self._read()

    @classmethod
    def boundary(cls, content_type):
        """The form's boundary from its Content-Type, quoted or bare; "" when it names none."""
        for match in cls.PARAM.finditer(str(content_type or "")):
            if match.group(1).lower() == "boundary":
                return cls._unquote(match.group(2).strip())
        return ""

    @staticmethod
    def _unquote(raw):
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            return re.sub(r"\\(.)", r"\1", raw[1:-1])
        return raw

    def _padded_crlf(self, at):
        """Where the line after position `at` ends — spaces and tabs may pad it, RFC 2046's transport padding — or -1."""
        body = self.body
        while body[at:at + 1] in (b" ", b"\t"):
            at += 1
        return at + 2 if body.startswith(self.CRLF, at) else -1

    def _delimiter(self, start):
        """Where the next delimiter's CRLF stands at or after `start`, or -1. The boundary's letters inside a part's
        data are not a delimiter unless `--` or a line's end follows them."""
        needle = self.CRLF + self.mark
        at = self.body.find(needle, start)
        while at >= 0:
            after = at + len(needle)
            if self.body.startswith(b"--", after) or self._padded_crlf(after) >= 0:
                return at
            at = self.body.find(needle, at + 1)
        return -1

    def _read(self):
        body = self.body
        at = body.find(self.mark)              # the first delimiter: a preamble may stand before it
        while at >= 0:
            at += len(self.mark)
            if body.startswith(b"--", at):     # the closing delimiter: the form is whole
                self.complete = True
                return
            head_at = self._padded_crlf(at)
            if head_at < 0:
                return
            if body.startswith(self.CRLF, head_at):     # no head: RFC 7578 wants every part to name itself, so this is no form
                return
            head_end = body.find(self.HEAD_END, head_at)
            if head_end < 0:
                return
            head, data_at = body[head_at:head_end], head_end + 4
            end = self._delimiter(data_at)
            if end < 0:                         # the part never ends: the body was cut, and what it holds is no part
                return
            name, filename = self._disposition(head)
            self.parts.append(Part(name, filename, body, data_at, end))
            at = end + 2

    @classmethod
    def _disposition(cls, head):
        """(name, filename) of a part from its head's Content-Disposition; None for what it does not say."""
        for line in head.split(cls.CRLF):
            key, _, value = line.partition(b":")
            if key.strip().lower() != b"content-disposition":
                continue
            name = filename = None
            for match in cls.PARAM.finditer(value.decode("utf-8", errors="replace")):
                param, raw = match.group(1).lower(), cls._unquote(match.group(2).strip())
                if param == "name":
                    name = raw
                elif param in ("filename", "filename*"):
                    filename = raw
            return name, filename
        return None, None

    def file(self, name="file"):
        """The data of the first part that carries a filename — else of the part called `name` — or None: no file was sent.
        An empty file is b"", which is no recording but is not absence either."""
        for part in self.parts:
            if part.filename is not None:
                return part.data
        for part in self.parts:
            if part.name == name:
                return part.data
        return None

    def fields(self, name):
        """Every value sent under this name by a part with no filename, in order. `timestamp_granularities[]` arrives once for
        each granularity asked for, and `name[]` and `name` are one name. An empty value is no value."""
        wanted = {name, name[:-2] if name.endswith("[]") else name + "[]"}
        values = (part.data.decode("utf-8", errors="replace") for part in self.parts
                  if part.filename is None and part.name in wanted)
        return [value for value in values if value]

    def field(self, name):
        """The first value of the field, or None when it was not sent or was sent empty."""
        values = self.fields(name)
        return values[0] if values else None


class Refusal(Exception):
    """A request the cell turns down for a reason of its own — a recording it cannot read, say: answered with this
    status and these words. Anything else a handler raises is the cell's own failure, and stays a 500."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = int(status)


class Recording:
    """A recording as a cell reads it: mono float samples (`array("f")`, -1..1) and the rate they are at.

    A WAV of 16-bit PCM is read here, at its own rate — the board's voice window and most clients send that. Anything
    else — webm, ogg, mp3, m4a (what a browser records and Open WebUI sends), a WAV of other samples — goes through
    ffmpeg, to `rate` Hz, 16 kHz when the cell names none. Until 1.3.610 moonshine and transcribe.cpp read WAV alone and
    answered anything else "bad wav"; seamless had its own ffmpeg path. A machine without ffmpeg refuses such a recording
    (415) and says so: read as PCM, a compressed file is noise that transcribes to nothing."""

    #: What the recognisers of the fleet read, and what ffmpeg is asked for when the cell names no rate.
    RATE = 16000
    #: The longest ffmpeg may take over one recording, seconds.
    TIMEOUT = 300

    def __init__(self, samples, rate):
        self.samples = samples
        self.rate = int(rate)

    @classmethod
    def decode(cls, raw, rate=None, ffmpeg="ffmpeg"):
        """The Recording in `raw`. A 16-bit WAV is read at its own rate — or, when `rate` is given, only when it is at
        that rate already; everything else is ffmpeg's to decode, to `rate` or RATE. An empty `raw` is refused (400)."""
        if not raw:
            raise Refusal(400, "the recording is empty")
        if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
            try:
                with wave.open(io.BytesIO(raw), "rb") as wf:
                    width, channels, at = wf.getsampwidth(), wf.getnchannels(), wf.getframerate()
                    frames = wf.readframes(wf.getnframes())
            except (wave.Error, EOFError):
                width = 0
            if width == 2 and channels >= 1 and (rate is None or at == rate):
                pcm = array.array("h")
                pcm.frombytes(frames[:len(frames) - len(frames) % 2])
                if sys.byteorder == "big":
                    pcm.byteswap()
                if channels > 1:
                    # The first channel, as moonshine and transcribe.cpp read a stereo WAV before this reader.
                    pcm = pcm[::channels]
                return cls(array.array("f", (s / 32768.0 for s in pcm)), at)
        return cls.through_ffmpeg(raw, rate or cls.RATE, ffmpeg)

    @classmethod
    def through_ffmpeg(cls, raw, rate, ffmpeg="ffmpeg"):
        """`raw` decoded by ffmpeg to mono float samples at `rate`."""
        if shutil.which(ffmpeg) is None:
            raise Refusal(415, "the recording is not a 16-bit WAV, and this machine has no ffmpeg to read it: "
                               "install ffmpeg, or send a WAV")
        try:
            proc = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
                                   "-f", "f32le", "-ac", "1", "-ar", str(int(rate)), "pipe:1"],
                                  input=raw, capture_output=True, timeout=cls.TIMEOUT)
        except subprocess.TimeoutExpired:
            raise Refusal(400, f"ffmpeg did not read the recording in {cls.TIMEOUT} s")
        if proc.returncode != 0:
            said = proc.stderr.decode("utf-8", errors="replace").strip()[:300]
            raise Refusal(400, "ffmpeg could not read the recording" + (f": {said}" if said else ""))
        out = proc.stdout[:len(proc.stdout) - len(proc.stdout) % 4]
        samples = array.array("f")
        samples.frombytes(out)
        if sys.byteorder == "big":
            samples.byteswap()
        return cls(samples, rate)

    @staticmethod
    def pcm16(samples):
        """Float samples (-1..1: an array("f"), a list, an engine's numpy array) as 16-bit little-endian PCM: ×32768,
        rounded and clipped — the inverse of `decode`, so a 16-bit WAV read and written again is the same bytes."""
        values = samples.tolist() if hasattr(samples, "tolist") else samples
        pcm = array.array("h", [max(-32768, min(32767, round(float(v) * 32768.0))) for v in values])
        if sys.byteorder == "big":
            pcm.byteswap()
        return pcm.tobytes()

    def wav(self):
        """The recording as a WAV of 16-bit mono PCM at its rate."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.rate)
            wf.writeframes(self.pcm16(self.samples))
        return buf.getvalue()


class CellServer:
    """One cell: a port, a model loading behind it, and two endpoints."""

    #: Path the work is served on. "" means any path (whisper accepts a POST
    #: wherever it lands, and changing that would break its callers).
    work_path = ""
    #: Phases a caller may see before "ok": the controller renders them as
    #: "downloading 40% / loading" instead of a silent STARTING.
    health_path = "/health"
    #: Paths that answer health. None = any GET does, which is what most of
    #: these cells have always done; a tuple means everything else is a 404.
    #: transcribe answers 404 on an unknown path, and turning that into a health
    #: reply would be a 200 with the wrong body — the failure this base exists
    #: to prevent, produced by the base itself. Compared against a path with its
    #: trailing slashes stripped, EXCEPT that a bare "/" stays "/" — a cell
    #: listing "/" among its health paths would otherwise 404 on its own root.
    health_paths = None
    #: HTTP/1.1 keeps the connection open between requests. A transcription
    #: client sending chunks back-to-back pays a handshake per chunk without it,
    #: so the cell that has such clients asks for it explicitly rather than
    #: inheriting a default that was chosen for something else.
    protocol_version = "HTTP/1.0"
    #: How this cell serialises JSON. seamless and translate answer with text in
    #: the target language and write it as UTF-8 rather than \uXXXX escapes —
    #: the same string either way, different bytes on the wire, and a caller
    #: that reads the body as text sees the difference.
    json_ensure_ascii = True
    json_content_type = "application/json"

    def __init__(self, argv=None):
        argv = list(argv if argv is not None else sys.argv[1:])
        self.port = int(argv[0]) if argv else self.default_port
        self.args = argv[1:]
        self.source = _source_stamp(sys.modules[type(self).__module__].__file__)
        self.state = {"phase": "starting", "ready": False, "error": "",
                      "downloaded": 0, "total": 0}

    # ── what a subclass says about itself ────────────────────────────────────
    default_port = 8000

    @property
    def engine(self):
        raise NotImplementedError

    @property
    def model_name(self):
        raise NotImplementedError

    @property
    def kinds(self):
        raise NotImplementedError

    def load(self):
        """Fetch and load. Raise to fail — the base records the reason."""
        raise NotImplementedError

    def handle(self, body, headers, path):
        """Do the work. Return (status, body_bytes, content_type)."""
        raise NotImplementedError

    def handle_get(self, path, query):
        """A GET this cell serves besides /health, or None to fall through.

        moonshine lists its stock voices on /v1/audio/voices; a base that only
        knew about health would have quietly turned that into a health reply,
        which is a 200 with the wrong body — the shape of failure this whole
        rewrite is trying to stop producing.
        """
        return None

    def ready_required(self, path):
        """Whether this path needs the model loaded.

        Not everything does. moonshine loads recognition and synthesis
        independently: a voice request is answerable while the recognizer is
        still warming, and refusing it with "model loading" would make the cell
        look less capable than it is.
        """
        return True

    def is_health(self, path):
        """Whether this GET path is the health endpoint.

        The tuple covers the cells that name their paths exactly. seamless
        answers health on anything ENDING in /health, which no tuple can say,
        and narrowing it here would 404 a caller that has been working for
        months — so the rule stays a method those cells can restate.
        """
        return self.health_paths is None or path in self.health_paths

    def extra_health(self):
        """Fields this kind of cell adds to /health. See cell_health.OPTIONAL —
        a field not named there is dropped in transit and the board renders the
        absence as if the cell had said nothing."""
        return {}

    # ── the parts no subclass should have to write ───────────────────────────
    def log(self, msg):
        print(msg, flush=True)

    def health(self):
        """(status_code, payload). Required fields always; never a bare 'ok'."""
        payload = {
            "status": "ok" if self.state["ready"] else self.state["phase"],
            "engine": self.engine,
            "model": self.model_name,
            "source": self.source,
            "kinds": self.kinds,
        }
        if self.state["ready"]:
            payload.update(self.extra_health())
            return 200, payload
        if self.state["error"]:
            # A refusal says why. A cell that is merely "not ok" leaves the
            # caller to guess, which is how a broken cell reads as a quiet one.
            payload["error"] = self.state["error"]
            payload["status"] = "error"
            return 500, payload
        payload["downloadedBytes"] = self.state["downloaded"]
        payload["totalBytes"] = self.state["total"]
        return 503, payload

    def _load_thread(self):
        try:
            self.state["phase"] = "loading"
            self.load()
            self.state["ready"] = True
            self.state["phase"] = "ok"
            self.log(f"[{self.engine}] ready on :{self.port} — {self.model_name}")
        except Exception as exc:  # noqa: BLE001
            # Every failure ends up here, which is the point: the six copies
            # each decided for themselves what to do with an exception, and one
            # of them decided to answer 200.
            self.state["phase"] = "error"
            self.state["error"] = f"{type(exc).__name__}: {exc}"
            self.log(f"[{self.engine}] load failed: {self.state['error']}")

    def serve(self):
        """Bind first, load after: a cell that only listened once its model was
        ready would leave the board with nothing to show for minutes, and no way
        to tell 'still loading' from 'never started'."""
        threading.Thread(target=self._load_thread, daemon=True).start()
        _Server(("0.0.0.0", self.port), _handler_for(self)).serve_forever()


class _Server(ThreadingHTTPServer):
    """Accept queue deep enough for a caller that pipelines requests.

    socketserver's default is 5, and a queue that shallow does not refuse — the
    kernel drops the SYN and the caller retries at 1s, 3s, 7s, which reads as
    the cell being slow rather than being over its listen limit. A transcription
    client sending chunks back-to-back is exactly that shape of load, and a
    backlog of 5 on every python listener once hung the board itself.
    """
    request_queue_size = 64
    daemon_threads = True


def _handler_for(cell):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = cell.protocol_version

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=cell.json_ensure_ascii).encode("utf-8")
                ctype = ctype or cell.json_content_type
            elif isinstance(body, str):
                body = body.encode("utf-8")
            ctype = ctype or cell.json_content_type
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            raw = self.path or ""
            path = raw.split("?", 1)[0].rstrip("/") or "/"
            query = raw.split("?", 1)[1] if "?" in raw else ""
            try:
                answer = cell.handle_get(path, query)
            except Exception as exc:  # noqa: BLE001
                cell.log(f"[{cell.engine}] {type(exc).__name__}: {exc}")
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
                return
            if answer is not None:
                code, out, ctype = answer
                self._send(code, out, ctype)
                return
            if not cell.is_health(path):
                self._send(404, {"error": "not found"})
                return
            code, payload = cell.health()
            self._send(code, payload)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length)
            path = (self.path or "").split("?", 1)[0].rstrip("/") or "/"
            if cell.ready_required(path) and not cell.state["ready"]:
                reason = cell.state["error"] or f"model {cell.state['phase']}"
                self._send(503, {"error": reason})
                return
            try:
                code, out, ctype = cell.handle(body, self.headers, path)
            except Refusal as exc:
                # The cell's own word on the request: its status and its reason, not a failure of the cell.
                self._send(exc.status, {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                # THE bug this base exists to make impossible. whisper caught
                # its own exceptions and answered 200 with an empty transcript:
                # the caller got a success, kept none of the audio, and found
                # out weeks later. An exception is an answer of 500, with the
                # reason, always.
                cell.log(f"[{cell.engine}] {type(exc).__name__}: {exc}")
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
                return
            self._send(code, out, ctype)

    return Handler
