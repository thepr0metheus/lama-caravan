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
in caravan/admin/cell_health.py, and it wraps the work path so that an exception
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
"""
import hashlib
import json
import os
import sys
import threading
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
    that ignored the base would call it current. caravan/admin/cell_assets.py
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


class CellServer:
    """One cell: a port, a model loading behind it, and two endpoints."""

    #: Path the work is served on. "" means any path (whisper and tts accept
    #: a POST wherever it lands, and changing that would break their callers).
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
