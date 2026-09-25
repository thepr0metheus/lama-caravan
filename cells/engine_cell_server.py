#!/usr/bin/env python3
"""A cell whose model runs inside an engine next to it — Ollama or LM Studio.

The engine listens on 127.0.0.1 only, and the cell is the one way in (the
operator's decision, 2026-09-25): this server binds the cell's port and
forwards what it is sent to the engine, naming the cell's model in every
request, so a caller never has to know what the engine calls it. Starting
the cell loads the model and holds it for as long as the cell runs; stopping
the cell unloads it. Everything else a cell has — its port on the board, its
start and stop, autostart, logs, the watchdog — is the ordinary cell
machinery, which is why this is a cell server and not a feature of the scout.

    python3 engine_cell_server.py <port> <engine> <engine_port> <model>

    engine   ollama | lmstudio

Standard library only: it runs next to an engine, not next to a venv.
"""
import http.client
import json
import os
import signal
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cell_base import CellServer, _Server, _handler_for  # noqa: E402


class EngineApi:
    """How one engine is spoken to: the few calls a cell needs, over its
    loopback port. Each answer is (status, parsed JSON or None); a refused
    connection is status 0 — "not answering", said as such, never guessed."""

    label = ""
    #: Seconds a call may take. Loading a model is the slow one.
    TIMEOUT = 10
    LOAD_TIMEOUT = 300

    def __init__(self, port):
        self.port = int(port)

    def call(self, method, path, body=None, timeout=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout or self.TIMEOUT)
        try:
            data = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, body=data,
                         headers={"Content-Type": "application/json"} if data is not None else {})
            resp = conn.getresponse()
            raw = resp.read()
            try:
                payload = json.loads(raw.decode("utf-8") or "null")
            except ValueError:
                payload = None
            return resp.status, payload
        except (OSError, http.client.HTTPException):
            return 0, None
        finally:
            conn.close()

    @staticmethod
    def said(payload, fallback):
        """The engine's own words for a refusal, when it gave any."""
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                err = err.get("message")
            if err:
                return str(err)[:300]
        return fallback

    # What each engine answers differently.
    def alive(self):
        raise NotImplementedError

    def has(self, model):
        """True / False, or None when the engine's list did not answer."""
        raise NotImplementedError

    def job(self, model):
        """"llm" or "embed" — what the model does, as the engine types it."""
        raise NotImplementedError

    def load(self, model, job="llm"):
        """"" once the model is loaded and held, or the reason it is not. `job`
        is what the cell already learned the model does — not asked twice."""
        raise NotImplementedError

    def unload(self, model):
        raise NotImplementedError

    def loaded(self, model):
        """True / False, or None when the engine did not say."""
        raise NotImplementedError

    def hold(self, model):
        """Keep the model loaded after a request that may have loosened it."""
        return ""


class Ollama(EngineApi):
    label = "Ollama"

    def alive(self):
        status, _ = self.call("GET", "/api/version")
        return status == 200

    def _tags(self):
        status, body = self.call("GET", "/api/tags")
        if status != 200 or not isinstance(body, dict):
            return None
        return [str(m.get("name")) for m in body.get("models") or [] if isinstance(m, dict)]

    def has(self, model):
        names = self._tags()
        return None if names is None else model in names

    def job(self, model):
        status, body = self.call("POST", "/api/show", {"model": model})
        caps = body.get("capabilities") if status == 200 and isinstance(body, dict) else None
        if isinstance(caps, list) and "embedding" in caps and "completion" not in caps:
            return "embed"
        return "llm"

    def _hold_body(self, model, keep):
        return {"model": model, "keep_alive": keep}

    def load(self, model, job="llm"):
        # keep_alive -1: until unloaded. An embedding model refuses /api/generate,
        # and /api/embed with the same keep_alive loads it the same way.
        path = "/api/embed" if job == "embed" else "/api/generate"
        body = self._hold_body(model, -1)
        if path == "/api/embed":
            body["input"] = "."
        status, payload = self.call("POST", path, body, timeout=self.LOAD_TIMEOUT)
        return "" if status == 200 else self.said(payload, f"{self.label} refused the load ({status})")

    def unload(self, model):
        status, payload = self.call("POST", "/api/generate", self._hold_body(model, 0))
        return "" if status == 200 else self.said(payload, f"{self.label} refused the unload ({status})")

    def loaded(self, model):
        status, body = self.call("GET", "/api/ps")
        if status != 200 or not isinstance(body, dict):
            return None
        return any(isinstance(m, dict) and m.get("name") == model for m in body.get("models") or [])

    def hold(self, model):
        # A request through Ollama's OpenAI-style paths resets the model's timer
        # to the server's default (five minutes): the model would unload itself
        # under a running cell. Setting it back is a no-op call on a loaded model.
        status, payload = self.call("POST", "/api/generate", self._hold_body(model, -1))
        return "" if status == 200 else self.said(payload, f"{self.label} did not keep the model ({status})")


class LmStudio(EngineApi):
    label = "LM Studio"

    def _models(self):
        status, body = self.call("GET", "/api/v1/models")
        if status != 200 or not isinstance(body, dict):
            return None
        return [m for m in body.get("models") or [] if isinstance(m, dict)]

    def _row(self, model):
        rows = self._models()
        if rows is None:
            return None
        return next((m for m in rows if m.get("key") == model), {})

    def alive(self):
        return self._models() is not None

    def has(self, model):
        row = self._row(model)
        return None if row is None else bool(row)

    def job(self, model):
        row = self._row(model) or {}
        return "embed" if str(row.get("type") or "") == "embedding" else "llm"

    def load(self, model, job="llm"):
        # The REST load holds the model until it is unloaded: no idle limit.
        status, payload = self.call("POST", "/api/v1/models/load", {"model": model}, timeout=self.LOAD_TIMEOUT)
        return "" if status == 200 else self.said(payload, f"{self.label} refused the load ({status})")

    def unload(self, model):
        row = self._row(model) or {}
        ids = [str(i.get("id")) for i in row.get("loaded_instances") or [] if isinstance(i, dict) and i.get("id")]
        for instance in ids:
            status, payload = self.call("POST", "/api/v1/models/unload", {"instance_id": instance})
            if status != 200:
                return self.said(payload, f"{self.label} refused the unload ({status})")
        return ""

    def loaded(self, model):
        row = self._row(model)
        if row is None:
            return None
        return bool(row.get("loaded_instances"))


ENGINES = {"ollama": Ollama, "lmstudio": LmStudio}

#: Headers that belong to one hop and are never passed on.
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "host", "content-length"}


class EngineCell(CellServer):
    """The cell: its port, the engine behind it, and the model it holds."""

    default_port = 22000
    health_paths = ("/health",)
    #: How long a start waits for the engine to answer: the machine may be
    #: bringing it up at the same moment it brings up this cell.
    ENGINE_WAIT = 90
    #: How often /health asks the engine whether the model is still there.
    CHECK_EVERY = 5
    #: A reply may stream for as long as the model writes.
    READ_TIMEOUT = 3600

    def __init__(self, argv=None, engines=None, clock=time.monotonic, sleep=time.sleep):
        super().__init__(argv)
        engine, engine_port, model = (list(self.args) + ["", "", ""])[:3]
        self.engine_id = str(engine).strip().lower()
        kind = (engines or ENGINES).get(self.engine_id)
        if kind is None:
            raise SystemExit(f"unknown engine {engine!r}: expected one of {', '.join(sorted(ENGINES))}")
        self.api = kind(int(engine_port or 0))
        self.model = str(model).strip()
        if not self.model:
            raise SystemExit("no model named: the cell has nothing to serve")
        self.clock = clock
        self.sleep = sleep
        self.job = "llm"
        self._checked_at = None
        self._verdict = ""

    # ── what the cell says about itself ──────────────────────────────────────
    @property
    def engine(self):
        return self.engine_id

    @property
    def model_name(self):
        return self.model

    @property
    def kinds(self):
        # What the model does, as the engine types it — learned at load. The
        # common case is written last: check_cell_kinds reads the last return.
        if self.job == "embed":
            return ["embed"]
        else:
            return ["llm"]

    def where(self):
        return f"{self.api.label} on 127.0.0.1:{self.api.port}"

    # ── start and stop ───────────────────────────────────────────────────────
    def load(self):
        deadline = self.clock() + self.ENGINE_WAIT
        self.state["phase"] = "waiting"
        while not self.api.alive():
            if self.clock() >= deadline:
                raise RuntimeError(f"{self.where()} is not answering")
            self.sleep(1)
        self.state["phase"] = "loading"
        present = self.api.has(self.model)
        if present is False:
            raise RuntimeError(f"{self.api.label} has no model {self.model}")
        if present is None:
            raise RuntimeError(f"{self.where()} did not list its models")
        self.job = self.api.job(self.model)
        reason = self.api.load(self.model, self.job)
        if reason:
            raise RuntimeError(reason)

    def stop(self):
        """Let the model go — the cell no longer holds it."""
        reason = self.api.unload(self.model)
        self.log(f"[{self.engine}] {'unload refused: ' + reason if reason else 'unloaded ' + self.model}")
        return reason

    # ── health: the model must still be there ────────────────────────────────
    def verdict(self):
        """"" while the engine holds the model, else what is wrong — asked at
        most every CHECK_EVERY seconds: the board polls, the engine need not."""
        now = self.clock()
        if self._checked_at is not None and now - self._checked_at < self.CHECK_EVERY:
            return self._verdict
        self._checked_at = now
        held = self.api.loaded(self.model)
        if held is None:
            self._verdict = f"{self.where()} is not answering"
        elif not held:
            self._verdict = f"{self.model} is no longer loaded in {self.api.label}"
        else:
            self._verdict = ""
        return self._verdict

    def not_ready(self):
        """Why the cell cannot serve yet, in words: its failure, or what it is
        waiting on — never a bare phase for a caller to guess from."""
        if self.state["error"]:
            return self.state["error"]
        if self.state["phase"] == "waiting":
            return f"waiting for {self.where()} to answer"
        return f"loading {self.model} into {self.api.label}"

    def health(self):
        code, payload = super().health()
        if code == 503:
            payload["detail"] = self.not_ready()
        if code == 200:
            reason = self.verdict()
            if reason:
                # Up as a process around an engine that let the model go: broken,
                # and said so — not an "ok" drawn over an empty engine.
                payload.update(status="error", error=reason)
                return 500, payload
        return code, payload

    # ── the way in ───────────────────────────────────────────────────────────
    def named(self, body, ctype):
        """The request with the cell's model in it: a caller need not know what
        the engine calls the model, and cannot reach another one through here."""
        if "json" not in str(ctype or "").lower():
            return body
        try:
            data = json.loads(body.decode("utf-8") or "null")
        except (ValueError, UnicodeDecodeError):
            return body
        if not isinstance(data, dict):
            return body
        data["model"] = self.model
        return json.dumps(data).encode("utf-8")

    def models_reply(self):
        """/v1/models through the cell lists the cell's own model, and only it."""
        return 200, {"object": "list", "data": [{"id": self.model, "object": "model",
                                                 "owned_by": self.engine}]}, None

    def handle_get(self, path, query):
        if path == "/v1/models":
            return self.models_reply()
        return None

    def handle(self, body, headers, path):
        # Never reached: POST goes through the forwarding handler below, because
        # a reply may stream and the base answers whole bodies only. Said as an
        # answer rather than raised, in case a future base routes here.
        return 500, json.dumps({"error": "the engine cell forwards; nothing is handled here"}).encode("utf-8"), \
            "application/json"

    def forward(self, writer, method, body=b""):
        """Pass one request to the engine and its reply back, as it arrives —
        a streamed reply streams through."""
        conn = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=self.READ_TIMEOUT)
        headers = {k: v for k, v in writer.headers.items() if k.lower() not in HOP}
        try:
            conn.request(method, writer.path, body=body or None, headers=headers)
            resp = conn.getresponse()
        except (OSError, http.client.HTTPException) as exc:
            conn.close()
            writer._send(502, {"error": f"{self.where()}: {type(exc).__name__}: {exc}"})
            return 502
        try:
            writer.send_response(resp.status)
            for key, value in resp.getheaders():
                if key.lower() not in HOP:
                    writer.send_header(key, value)
            writer.send_header("Connection", "close")
            writer.end_headers()
            while True:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                writer.wfile.write(chunk)
                writer.wfile.flush()
        except OSError:
            pass        # the caller went away mid-reply; nothing to answer to
        finally:
            conn.close()
        return resp.status

    def after(self, path):
        """Once a request is through: hold the model again where the engine may
        have loosened it (Ollama resets its timer on the OpenAI-style paths)."""
        if path.startswith("/v1/"):
            threading.Thread(target=self.api.hold, args=(self.model,), daemon=True).start()

    def handler_class(self):
        """The base's handler, forwarding instead of answering whole bodies."""
        cell = self
        base = _handler_for(self)

        class Handler(base):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length)
                path = (self.path or "").split("?", 1)[0].rstrip("/") or "/"
                if not cell.state["ready"]:
                    self._send(503, {"error": cell.not_ready()})
                    return
                cell.forward(self, "POST", cell.named(body, self.headers.get("Content-Type")))
                cell.after(path)

            def do_GET(self):
                path = (self.path or "").split("?", 1)[0].rstrip("/") or "/"
                if cell.is_health(path) or path == "/v1/models":
                    return super().do_GET()
                if not cell.state["ready"]:
                    self._send(503, {"error": cell.not_ready()})
                    return
                cell.forward(self, "GET")

        return Handler

    def serve(self):
        """Bind, load behind the port, and unload before the process goes."""
        def on_stop(signum, frame):
            self.stop()
            os._exit(0)

        signal.signal(signal.SIGTERM, on_stop)
        signal.signal(signal.SIGINT, on_stop)
        threading.Thread(target=self._load_thread, daemon=True).start()
        _Server(("0.0.0.0", self.port), self.handler_class()).serve_forever()


if __name__ == "__main__":
    EngineCell().serve()
