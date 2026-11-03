#!/usr/bin/env python3
"""The scout against what the scout promised, from outside: one scenario, and every answer compared with tests/frozen/scout.jsonl.

The file is what the scout in Python answered when it left (scripts/_frozen_answers.py). The scenario asks what a controller asks: the page and the open paths,
the fleet token's gate, the machine's tables, a llama cell and a command cell from their start to their stop, a model fetched from the controller into the cache
and the keeper's rules over it, a crash and the watchdog, a scout killed under a running cell and the cell held again, the entry by OpenAI's API, an engine next
to the cells, pairing and unpairing. The cells, the card and the controller are stand-ins written here: nothing of the machine is touched but its processes, and
the scout runs in a home of its own under a temporary folder.

What differs by nature is named in `VOLATILE` and `SAID_BY_THE_SYSTEM`; what differs by decision, in the rows kept for it.
Run: python3 scripts/test_rust_scout_conformance.py [--write]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _frozen_answers import FrozenAnswers, OwnWords  # noqa: E402
from _ports import free_port  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RUST = REPO / "rust"
#: The scout's own folder: its `scripts/` lie there, as they lie beside the program on a machine.
SCOUT_ROOT = RUST / "crates" / "scout"
BINARY_NAME = "caravan-scout"
#: Fields whose value changes from one run to the next, wherever they stand.
VOLATILE = {
    "time", "startedAt", "uptimeSec", "pid", "pids", "listenerPid", "at", "generatedAt", "savedAt", "savedAtTs", "lastAt", "since", "created", "modifiedAt",
    "readBytes", "readBytesPerSec", "downloadBytesPerSec", "ramBytes", "freeBytes", "totalBytes", "t", "checkedAt", "cpuPct", "seenAt", "bytes", "tail",
    "startingTail", "ram", "cpu", "boot", "builtAt", "llamaBinaryMtime", "firstSeenAt", "lastSeenAt", "promptTps", "genTps", "uptime",
}
#: Whole answers that are the machine's own and change by the moment: only their shape is compared.
SAID_BY_THE_SYSTEM = {"/api/host/processes", "/api/monitor/btop", "/api/monitor/nvidia-smi", "/api/host/listeners", "/api/telemetry", "/api/host/driver"}
#: What a server said of its window and its places is kept 30 s from the first asking, and a board may first ask before the server is up: whether it is said yet is a race, on either side. tables/probe.json holds the rule.
RACING = {"ctxMax", "ctxUsed", "slots"}
#: What is not compared at all. The driver of the machine it runs on is that machine's: its kernel, what it has loaded.
UNPROMISED = RACING | {"driver"}
GIB = 1 << 30


class StandIns:
    """The programs a scout runs here: a `llama-server` that answers what a cell's server answers, and an `nvidia-smi` of one card."""

    CELL = r'''#!/usr/bin/env python3
"""A cell's server, for the comparison: says what it was asked, computes nothing."""
import json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

argv = sys.argv[1:]
def flag(*names, default=""):
    for name in names:
        if name in argv and argv.index(name) + 1 < len(argv):
            return argv[argv.index(name) + 1]
    return default
port = int(flag("--port", default=os.environ.get("PORT", "0")))
mode = os.environ.get("FAKE_CELL", "")
print(f"cell on {port}, model {flag('-m', '--model')}", flush=True)
for name in sorted(k for k in os.environ if k.startswith(("FAKE_", "LLAMA_MODELS_DIR", "CARAVAN_CELL_SCRATCH", "CUDA"))):
    print(f"env {name}={os.environ[name]}", flush=True)
if mode == "die":
    print("error: Model loading failed: no such thing", flush=True)
    sys.exit(3)
if mode == "corrupt":
    print("error: tensor data is not within the file bounds, model is corrupted or incomplete", flush=True)
    sys.exit(1)

class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload, kind="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path == "/health":
            return self.reply(200, {"status": "ok"})
        if self.path == "/metrics":
            if mode == "no-metrics":
                return self.reply(501, {"error": "metrics not enabled"})
            return self.reply(200, b"# HELP x\nllamacpp:requests_processing 1\nllamacpp:prompt_tokens_seconds 12.5\nllamacpp:predicted_tokens_seconds 33.25\nllamacpp:kv_cache_usage_ratio 0.25\n", "text/plain")
        if self.path == "/props":
            return self.reply(200, {"default_generation_settings": {"n_ctx": 4096}, "total_slots": 2})
        if self.path == "/v1/models":
            return self.reply(200, {"data": [{"id": "own-name", "aliases": ["own-alias"]}]})
        self.reply(404, {"error": "no such path"})
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        seen = {"path": self.path, "fields": sorted(key.lower() for key in self.headers.keys()), "model": body.get("model"), "length": length,
                "authorization": self.headers.get("Authorization"), "custom": self.headers.get("X-Custom")}
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("X-Cell", "said")
            self.end_headers()
            for at in range(3):
                self.wfile.write(f"data: {{\"at\": {at}}}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self.reply(200, seen)
    def log_message(self, *args):
        pass

ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''
    SMI = r'''#!/usr/bin/env python3
"""An nvidia-smi of one card, for the comparison."""
import sys

FIELDS = {"index": "0", "name": "Stand Card 24GB", "uuid": "GPU-stand", "memory.total": "24576", "memory.used": "1024", "memory.free": "23552",
          "utilization.gpu": "0", "temperature.gpu": "41", "power.draw": "31.50", "driver_version": "570.100"}
argv = sys.argv[1:]
gpu = [word.split("=", 1)[1] for word in argv if word.startswith("--query-gpu=")]
apps = [word for word in argv if word.startswith("--query-compute-apps=")]
if gpu:
    print(", ".join(FIELDS[name] for name in gpu[0].split(",")))
elif not apps:
    print("| NVIDIA-SMI 570.100   Driver Version: 570.100   CUDA Version: 13.3 |")
'''

    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        self.cell = self.write("llama-server", self.CELL)
        self.write("nvidia-smi", self.SMI)

    def write(self, name: str, text: str) -> Path:
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)
        return path


class FakeController:
    """The controller, as a scout sees it: takes the heartbeats, serves the model files and the cell servers, and says the cells it keeps."""

    FILES = {"dl/model.gguf": b"M" * 4096, "dl/part-00001-of-00002.gguf": b"A" * 100, "dl/part-00002-of-00002.gguf": b"B" * 200, "dl/mmproj.gguf": b"P" * 50,
             "folder/config.json": b"{}", "folder/sub/weights.bin": b"W" * 300}
    FOLDER = {"files": [{"path": "config.json", "size": 2}, {"path": "sub/weights.bin", "size": 300}], "links": [{"path": "link.bin", "target": "sub/weights.bin"}], "size": 302}

    def __init__(self, port: int):
        self.port = port
        self.beats: list[dict] = []
        self.tokens: list[str] = []
        self.cells: list | None = None
        self.refuse_token = ""
        controller = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self, status, payload):
                body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                asked = urllib.parse.parse_qs(parsed.query)
                if parsed.path == "/api/models/download":
                    name = asked.get("path", [""])[0]
                    return self.reply(200, controller.FILES[name]) if name in controller.FILES else self.reply(404, {"error": "no such file"})
                if parsed.path == "/api/models/folder":
                    return self.reply(200, controller.FOLDER)
                if parsed.path == "/api/cell-assets":
                    return self.reply(200, {"runners": {"stand": ["run_stand.sh"]}, "assets": {"run_stand.sh": {"sha256": "", "executable": True}}})
                if parsed.path == "/api/cell-assets/file":
                    return self.reply(200, b"#!/bin/sh\nexit 0\n")
                self.reply(404, {"error": "not found"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                token = self.headers.get("X-Caravan-Token") or ""
                controller.tokens.append(token)
                if controller.refuse_token and token == controller.refuse_token:
                    return self.reply(401, {"error": "bad token"})
                controller.beats.append(json.loads(raw or b"{}"))
                answer = {"ok": True}
                if controller.cells is not None:
                    answer["cells"] = controller.cells
                self.reply(200, answer)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class FakeOllama:
    """An Ollama next to the cells, on its usual port, when that port is free here."""

    def __init__(self):
        self.unloaded: list[str] = []
        self.deleted: list[str] = []
        engine = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self, payload, status=200):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    return self.reply({"version": "0.9.0"})
                if self.path == "/api/ps":
                    return self.reply({"models": [{"name": "loaded:1", "size": 2000, "size_vram": 1000, "context_length": 4096, "expires_at": "2099-01-01T00:00:00Z"}]})
                if self.path == "/api/tags":
                    return self.reply({"models": [
                        {"name": "loaded:1", "size": 1500, "details": {"format": "gguf", "family": "fam", "parameter_size": "7B", "quantization_level": "Q4"}},
                        {"name": "idle:1", "size": 900, "details": {}},
                        {"name": "cloud:1", "size": 1, "remote_host": "https://elsewhere"},
                    ]})
                self.reply({"error": "no"}, 404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                engine.unloaded.append(body.get("model"))
                self.reply({"done": True})

            def do_DELETE(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                engine.deleted.append(body.get("model"))
                if body.get("model") == "idle:1":
                    return self.reply({"error": {"message": "cannot delete it"}}, 500)
                self.reply({})

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 11434), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Answer:
    """What a scout said."""

    def __init__(self, status: int, fields: dict, raw: bytes):
        self.status, self.fields, self.raw = status, fields, raw

    @property
    def json(self):
        try:
            return json.loads(self.raw)
        except ValueError:
            return None


class Asker:
    """A raw HTTP client: what goes out is what is written here, and the answer is read to its end."""

    def __init__(self, port: int):
        self.port = port

    def ask(self, method: str, path: str, body=None, fields: dict | None = None, raw: bytes | None = None, timeout: float = 30) -> Answer:
        data = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
        head = [f"{method} {path} HTTP/1.1", f"Host: 127.0.0.1:{self.port}", "Connection: close"]
        if body is not None or (raw is not None and not any(key.lower() == "content-length" for key in (fields or {}))):
            head.append(f"Content-Length: {len(data)}")
        head += [f"{key}: {value}" for key, value in (fields or {}).items()]
        with socket.create_connection(("127.0.0.1", self.port), timeout=timeout) as sock:
            sock.sendall(("\r\n".join(head) + "\r\n\r\n").encode() + data)
            sock.shutdown(socket.SHUT_WR)
            got = b""
            try:
                while True:
                    part = sock.recv(65536)
                    if not part:
                        break
                    got += part
            except (ConnectionResetError, TimeoutError):
                pass
        top, _, rest = got.partition(b"\r\n\r\n")
        lines = top.decode("latin-1").split("\r\n")
        status = int(lines[0].split()[1]) if lines and len(lines[0].split()) > 1 else 0
        said = {}
        for line in lines[1:]:
            key, _, value = line.partition(":")
            said[key.strip().lower()] = value.strip()
        return Answer(status, said, rest)


class Side:
    """One scout, in a home of its own. The home's path is the same on both sides: what a path says needs no translating."""

    def __init__(self, name: str, root: Path, ports: dict, stand_ins: StandIns, argv: list[str]):
        self.name, self.root, self.ports, self.argv = name, root, ports, argv
        self.stand_ins = stand_ins
        self.home = root / "home"
        self.config_path = root / "config.json"
        self.state_path = root / "state.json"
        self.log = root / f"{name}.log"
        self.process: subprocess.Popen | None = None
        self.asker = Asker(ports["scout"])

    def write_config(self, token: str = "") -> None:
        config = {"hostId": "stand-host", "displayName": "stand", "listenHost": "127.0.0.1", "listenPort": self.ports["scout"],
                  "controllerUrl": f"http://127.0.0.1:{self.ports['controller']}", "heartbeatIntervalSeconds": 3600,
                  "llamaServerBin": str(self.stand_ins.cell), "modelsBasePath": str(self.home / "cache"), "llamaNodeDefaultPort": self.ports["cell"]}
        if token:
            config["controllerToken"] = token
        self.config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    def environment(self) -> dict:
        env = dict(os.environ)
        env.update({"HOME": str(self.home), "PATH": f"{self.stand_ins.folder}{os.pathsep}{env.get('PATH', '')}", "LAMA_CARAVAN_SERVER_CELLS_DIR": str(self.root / "server-cells"),
                    "CARAVAN_SCOUT_ROOT": str(SCOUT_ROOT), "TZ": "UTC", "LLAMA_BUILDS_DIR": str(self.root / "builds")})
        return env

    def start(self) -> None:
        with open(self.log, "ab") as log:
            self.process = subprocess.Popen([*self.argv, "--config", str(self.config_path), "--state", str(self.state_path)], cwd=str(self.root), env=self.environment(), stdout=log, stderr=log, start_new_session=True)
        for _ in range(200):
            try:
                if self.asker.ask("GET", "/api/health", timeout=1).status == 200:
                    return
            except OSError:
                pass
            if self.process.poll() is not None:
                raise RuntimeError(f"{self.name} did not start: {self.log.read_text(errors='replace')[-2000:]}")
            time.sleep(0.05)
        raise RuntimeError(f"{self.name} did not answer: {self.log.read_text(errors='replace')[-2000:]}")

    def kill(self) -> None:
        """The scout alone: its cells live on, as they do when systemd kills a scout."""
        if self.process is not None:
            self.process.kill()
            self.process.wait(timeout=10)
            self.process = None

    def stop_all(self) -> None:
        try:
            self.asker.ask("POST", "/api/llama-node/stop", {}, timeout=30)
        except OSError:
            pass
        self.kill()


class Record:
    """What one run said, step by step."""

    def __init__(self):
        self.steps: list[tuple[str, object]] = []

    def add(self, name: str, said) -> None:
        self.steps.append((name, said))


class Shape:
    """An answer brought to what can be compared."""

    @classmethod
    def clean(cls, value, key: str = ""):
        if key in VOLATILE and value is not None:
            return f"<{type(value).__name__}>" if not isinstance(value, (list, dict)) else "<some>"
        if isinstance(value, dict):
            return {name: cls.clean(inner, name) for name, inner in value.items() if name not in UNPROMISED}
        if isinstance(value, list):
            return [cls.clean(inner, key) for inner in value]
        if isinstance(value, float) and value == int(value):
            return int(value)
        return value

    @classmethod
    def of(cls, value):
        """The shape of a machine's own table: its keys and kinds, not its figures."""
        if isinstance(value, dict):
            return {name: cls.of(inner) for name, inner in value.items() if name not in UNPROMISED}
        if isinstance(value, list):
            return ["<list>"] if value else []
        if value is None:
            return None
        return type(value).__name__


class Scenario:
    """What a controller asks of a scout, in order. Each step's answer goes into the record; a step that needs a state first waits for it."""

    def __init__(self, side: Side, controller: FakeController, ports: dict, record: Record, engine: FakeOllama | None):
        self.side, self.controller, self.ports, self.record, self.engine = side, controller, ports, record, engine
        self.cell = ports["cell"]
        self.home = side.home

    def ask(self, method, path, body=None, fields=None, raw=None, timeout=30) -> Answer:
        return self.side.asker.ask(method, path, body, fields, raw, timeout)

    def step(self, name, method, path, body=None, fields=None, raw=None, shape=False, status_only=False) -> Answer:
        answer = self.ask(method, path, body, fields, raw)
        if status_only:
            self.record.add(name, {"status": answer.status})
        elif shape or path.split("?")[0] in SAID_BY_THE_SYSTEM:
            self.record.add(name, {"status": answer.status, "shape": Shape.of(answer.json)})
        else:
            self.record.add(name, {"status": answer.status, "json": Shape.clean(answer.json) if answer.json is not None else answer.raw.decode("utf-8", "replace"), "type": answer.fields.get("content-type"), "cache": answer.fields.get("cache-control")})
        return answer

    def wait_cell(self, port, test, what, seconds=20):
        deadline = time.time() + seconds
        last = None
        while time.time() < deadline:
            nodes = self.ask("GET", "/api/llama-node/status").json.get("nodes") or []
            last = next((node for node in nodes if node.get("port") == port), None)
            if test(last):
                return last
            time.sleep(0.1)
        raise RuntimeError(f"{self.side.name}: :{port} never {what}: {last}")

    def running(self, port=None, seconds=20):
        port = port or self.cell
        node = self.wait_cell(port, lambda node: bool(node) and node.get("running") and node.get("listening") is not False and self.answers(port), "ran", seconds)
        # What the server said while it was coming up is kept for two seconds: both scouts read it fresh from here on.
        time.sleep(2.1)
        return self.wait_cell(port, bool, "stayed")

    def answers(self, port) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            return False

    def surface(self):
        for path in ("/", "/index.html", "/?x=1", "/api/health", "/api/pairing", "/openapi.json", "/nope", "/api/health?x=1", "/v1/models", "/v1/models/none", "/v1/nope"):
            self.step(f"GET {path}", "GET", path)
        self.step("no model", "POST", "/v1/chat/completions", {"messages": []})
        self.step("a model of no cell", "POST", "/v1/chat/completions", {"model": "none"})
        self.step("a body that is no JSON", "POST", "/v1/chat/completions", raw=b"nonsense", fields={"Content-Type": "application/json"})
        self.step("a chunked body", "POST", "/v1/chat/completions", raw=b"10\r\n{\"model\": \"x\"  }\r\n0\r\n\r\n", fields={"Transfer-Encoding": "chunked"})
        self.step("a broken chunk", "POST", "/v1/chat/completions", raw=b"zz\r\n", fields={"Transfer-Encoding": "chunked"})
        self.step("too long", "POST", "/v1/chat/completions", raw=b"", fields={"Content-Length": str(300 << 20)})
        self.step("a negative length", "POST", "/v1/chat/completions", raw=b"", fields={"Content-Length": "-1"})
        self.step("a length of no number", "POST", "/v1/chat/completions", raw=b"", fields={"Content-Length": "x"})
        self.step("POST nowhere", "POST", "/nope", {})
        self.step("a list for a body", "POST", "/api/llama-node/stop", [1])
        self.step("broken JSON", "POST", "/api/llama-node/stop", raw=b"{bad", status_only=True)

    def tables(self):
        for path in ("/api/llama-node/status", "/api/monitor/nvidia-smi", "/api/monitor/btop", "/api/host/processes", "/api/host/driver/install-status", "/api/host/listeners",
                     "/api/llama-node/configs", "/api/llama-node/update-status", "/api/llama-node/builds", "/api/llama-node/list-cache", "/api/llama-node/cache", "/api/vllm",
                     "/api/vllm/update-status", "/api/telemetry?since=0", "/api/llama-node/log", "/api/llama-node/log?port=x", "/api/llama-node/log?port=1", "/api/telemetry?since=9999999999"):
            self.step(f"GET {path}", "GET", path)
        self.step("the driver", "GET", "/api/host/driver")
        self.step("state", "GET", "/api/state")

    def refusals(self):
        start = "/api/llama-node/start"
        command = {"cellKind": "command", "port": self.cell, "shellLine": f"exec python3 {self.side.stand_ins.cell} --port {self.cell}"}
        self.step("no model", "POST", start, {})
        self.step("an unknown runner", "POST", start, {"config": {"RUNNER": "nope", "MODEL_FILE": "x"}})
        self.step("a bad env", "POST", start, {"modelPath": "x", "env": {"1bad": "x"}})
        self.step("an env of no text", "POST", start, {"modelPath": "x", "env": {"A": 1}})
        self.step("the scout's own mark", "POST", start, {"modelPath": "x", "env": {"CARAVAN_SCOUT_CELL": "1"}})
        self.step("no command", "POST", start, {"cellKind": "command"})
        self.step("no start line", "POST", start, {"cellKind": "command", "command": "x"})
        self.step("model files of no list", "POST", start, {**command, "command": "x", "modelFiles": "x"})
        self.step("a card too small", "POST", start, {**command, "command": "x", "vram": {"device": 0, "reserveMiB": 900000, "who": "vLLM", "why": "util", "lower": "utilization"}})
        self.step("a card short of room", "POST", start, {**command, "command": "x", "vram": {"device": 0, "reserveMiB": 24000}})
        self.step("a card that is not here is no refusal", "POST", start, {**command, "command": "x", "vram": {"device": 7, "reserveMiB": 24000}})
        self.running()
        self.step("it stops", "POST", "/api/llama-node/stop", {"port": self.cell})
        self.step("configs delete, a bad name", "POST", "/api/llama-node/configs/delete", {"filename": "other.json"})
        self.step("configs delete, none", "POST", "/api/llama-node/configs/delete", {"filename": "llama-node.bak.x.json"})
        self.step("restore of no build", "POST", "/api/llama-node/restore", {})
        self.step("vllm, no venv", "POST", "/api/vllm/update", {})
        self.step("stop, a port of no number", "POST", "/api/llama-node/stop", {"port": "x"}, status_only=True)
        self.step("a heartbeat now", "POST", "/api/heartbeat", {})
        self.step("dismiss nothing", "POST", "/api/llama-node/suspect-dismiss", {})

    def llama_cell(self):
        model = self.home / "library" / "held.gguf"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"G" * 2048)
        payload = {"port": self.cell, "modelPath": str(model), "args": ["--port", str(self.cell), "-m", "{{MODEL_PATH}}", "--mmproj", "{{MMPROJ_PATH}}"],
                   "config": {"MODEL_NAME": "my model", "N_GPU_LAYERS": "auto", "CTX_SIZE": 2048, "SPEC_TYPE": "mtp"}, "env": {"FAKE_ONE": "a b"}, "cacheModels": False}
        self.step("a llama cell starts", "POST", "/api/llama-node/start", payload)
        node = self.running()
        self.record.add("its view", Shape.clean(node))
        self.step("a second start is refused", "POST", "/api/llama-node/start", payload)
        self.step("listed by its name", "GET", "/v1/models")
        self.step("one model", "GET", "/v1/models/my%20model")
        self.step("metrics reach the view", "GET", "/api/llama-node/status")
        self.step("by its name", "POST", "/v1/chat/completions?x=1", {"model": "my model"}, fields={"Authorization": "Bearer secret", "X-Custom": "kept", "Connection": "X-Custom"})
        self.step("its answer's fields", "POST", "/v1/chat/completions", {"model": "my model"}, fields={"Authorization": "Bearer secret", "X-Custom": "kept"})
        answer = self.ask("POST", "/v1/chat/completions", {"model": "my model", "stream": True})
        self.record.add("a stream", {"status": answer.status, "body": answer.raw.decode(), "type": answer.fields.get("content-type"), "cell": answer.fields.get("x-cell")})
        form = b"--XX\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nmy model\r\n--XX--\r\n"
        self.step("a form", "POST", "/v1/audio/transcriptions", raw=form, fields={"Content-Type": "multipart/form-data; boundary=XX"})
        self.step("its log", "GET", f"/api/llama-node/log?port={self.cell}")
        self.step("a run of no log", "GET", f"/api/llama-node/log?port={self.cell}&run=nope")
        for name in ("start.sh", "cell.json"):
            path = self.side.root / "server-cells" / str(self.cell) / name
            text = path.read_text(encoding="utf-8") if path.exists() else "(none)"
            self.record.add(f"the cell's {name}", Shape.clean(json.loads(text)) if name.endswith(".json") else text)
        self.step("it stops", "POST", "/api/llama-node/stop", {"port": self.cell})
        self.step("stopped", "GET", "/api/llama-node/status")
        self.step("a stop of nothing", "POST", "/api/llama-node/stop", {"port": self.cell})
        self.record.add("its model stays", model.exists())

    def cache(self):
        payload = {"port": self.cell, "modelPath": "dl/model.gguf", "args": ["--port", str(self.cell), "-m", "{{MODEL_PATH}}"], "config": {}, "cacheModels": True}
        self.step("a model fetched", "POST", "/api/llama-node/start", payload)
        self.running()
        self.step("the cache", "GET", "/api/llama-node/cache")
        self.step("list-cache", "GET", "/api/llama-node/list-cache")
        self.step("a bad keep", "POST", "/api/llama-node/cache/keep", {"keep": 6})
        self.step("a keep of text", "POST", "/api/llama-node/cache/keep", {"keep": "2"})
        self.step("keep two", "POST", "/api/llama-node/cache/keep", {"keep": 2})
        self.step("a bad budget", "POST", "/api/llama-node/cache/budget", {"budgetBytes": 5})
        self.step("a budget", "POST", "/api/llama-node/cache/budget", {"budgetBytes": GIB})
        self.step("no budget", "POST", "/api/llama-node/cache/budget", {"budgetBytes": None})
        self.step("purge keeps what runs", "POST", "/api/llama-node/purge-cache", {})
        self.step("it stops, its model stays", "POST", "/api/llama-node/stop", {"port": self.cell})
        self.record.add("kept on the disk", (self.home / "cache" / "dl" / "model.gguf").exists())
        foreign = self.home / "cache" / "theirs" / "other.gguf"
        foreign.parent.mkdir(parents=True, exist_ok=True)
        foreign.write_bytes(b"F" * 512)
        self.step("the foreign file shows", "GET", "/api/llama-node/cache")
        self.step("delete foreign, the wrong size", "POST", "/api/llama-node/cache/delete-foreign", {"expectBytes": 1})
        self.step("delete foreign, no size", "POST", "/api/llama-node/cache/delete-foreign", {})
        self.step("delete foreign", "POST", "/api/llama-node/cache/delete-foreign", {"expectBytes": 512})
        self.record.add("the foreign file went", foreign.exists())
        split = {"port": self.cell, "modelPath": "dl/part-00001-of-00002.gguf", "args": ["--port", str(self.cell), "-m", "{{MODEL_PATH}}"], "config": {"MMPROJ_FILE": "dl/mmproj.gguf"}, "cacheModels": False}
        self.step("a split model", "POST", "/api/llama-node/start", split)
        node = self.running()
        self.record.add("its files", sorted(path.name for path in (self.home / "cache" / "dl").iterdir()))
        self.record.add("what the view says of them", {key: node.get(key) for key in ("modelBytes", "modelPath", "mmprojPath")})
        self.step("purge at a stop", "POST", "/api/llama-node/stop", {"port": self.cell})
        self.record.add("what is left", sorted(path.name for path in (self.home / "cache" / "dl").iterdir()) if (self.home / "cache" / "dl").exists() else [])
        self.step("a file the controller lacks", "POST", "/api/llama-node/start", {**payload, "modelPath": "dl/none.gguf"})
        node = self.wait_cell(self.cell, lambda node: bool(node) and node.get("phase") == "error", "failed")
        self.record.add("its error", node.get("lastError", "").split(":")[0])
        self.step("the failed one goes", "POST", "/api/llama-node/stop", {"port": self.cell})
        self.step("a new folder, not absolute", "POST", "/api/llama-node/cache/dir", {"path": "rel/path"})
        self.step("a new folder, none", "POST", "/api/llama-node/cache/dir", {})
        self.step("a new folder, the same", "POST", "/api/llama-node/cache/dir", {"path": str(self.home / "cache")})
        self.step("a new folder, inside", "POST", "/api/llama-node/cache/dir", {"path": str(self.home / "cache" / "inner")})
        self.step("a new folder", "POST", "/api/llama-node/cache/dir", {"path": str(self.home / "moved")})
        self.step("the cache there", "GET", "/api/llama-node/cache")

    def command_cell(self):
        script = self.side.stand_ins.cell
        hint = {"folder": {"dir": True}}
        payload = {"cellKind": "command", "port": self.cell, "command": f"python3 {script} --port $PORT", "shellLine": f"exec python3 {script} --port {self.cell}", "healthPath": "/health",
                   "modelFiles": ["folder"], "inPlace": hint, "env": {"FAKE_ONE": "b"}, "cacheModels": True, "config": {"MODEL_NAME": "voice", "RUNNER": "strata"}}
        self.step("a command cell starts", "POST", "/api/llama-node/start", payload)
        node = self.running()
        self.record.add("its view", Shape.clean(node))
        self.record.add("its folder", sorted(str(path.relative_to(self.home / "moved")) for path in (self.home / "moved" / "folder").rglob("*")))
        self.record.add("its link", os.readlink(self.home / "moved" / "folder" / "link.bin"))
        self.step("its log says its environment", "GET", f"/api/llama-node/log?port={self.cell}&lines=20")
        self.step("two kinds of one name, first", "GET", "/v1/models")
        self.step("autostart without a request", "POST", "/api/llama-node/autostart", {"port": self.cell, "enabled": True})
        self.step("autostart of a bad port", "POST", "/api/llama-node/autostart", {"port": 70000, "enabled": False})
        self.step("autostart on", "POST", "/api/llama-node/autostart", {"port": self.cell, "enabled": True, "payload": payload})
        self.step("kept in the state", "GET", "/api/state", shape=True)
        self.record.add("the kept request", Shape.clean(json.loads(self.side.state_path.read_text()).get("autostart")))
        self.step("autostart off", "POST", "/api/llama-node/autostart", {"port": self.cell, "enabled": False})
        self.step("it stops", "POST", "/api/llama-node/stop", {"port": self.cell})

    def strata_shelf(self):
        """The folder for Strata's files, a shelf of its own (2026-11-03): a start marked `workFolder` is refused while none is chosen, then copies its model there with the cache off,
        keeps it after the stop, and the folder's limit and its move say what they did."""
        script = self.side.stand_ins.cell
        payload = {"cellKind": "command", "port": self.cell, "command": f"python3 {script} --port $PORT", "shellLine": f"exec python3 {script} --port {self.cell}", "healthPath": "/health",
                   "modelFiles": ["dl/model.gguf"], "cacheModels": False, "workFolder": True, "config": {"MODEL_NAME": "strata", "RUNNER": "strata"}}
        self.step("a Strata cell with no folder", "POST", "/api/llama-node/start", payload)
        self.step("a folder for Strata's files", "POST", "/api/llama-node/cache/work", {"path": str(self.home / "ssd" / "strata")})
        self.step("a limit too small", "POST", "/api/llama-node/cache/work/budget", {"budgetBytes": 5})
        self.step("a limit", "POST", "/api/llama-node/cache/work/budget", {"budgetBytes": 2 * GIB})
        self.step("the cache goes off", "POST", "/api/llama-node/cache/off", {"off": True, "library": str(self.home / "library")})
        self.step("a Strata cell starts", "POST", "/api/llama-node/start", payload)
        self.running()
        self.record.add("its copy and its files", sorted(str(path.relative_to(self.home / "ssd" / "strata")) for path in (self.home / "ssd" / "strata").rglob("*") if path.is_file()))
        self.step("it stops", "POST", "/api/llama-node/stop", {"port": self.cell})
        self.record.add("the copy stays", (self.home / "ssd" / "strata" / "dl" / "model.gguf").exists())
        self.step("the shelf as the board reads it", "GET", "/api/llama-node/cache", shape=True)
        self.step("the limit taken off", "POST", "/api/llama-node/cache/work/budget", {"budgetBytes": None})
        self.step("the folder removed", "POST", "/api/llama-node/cache/work", {"path": ""})
        self.record.add("nothing of the scout's is left there", sorted(str(path.relative_to(self.home / "ssd")) for path in (self.home / "ssd").rglob("*")))
        self.step("the cache back on", "POST", "/api/llama-node/cache/off", {"off": False})

    def crash(self):
        script = self.side.stand_ins.cell
        payload = {"cellKind": "command", "port": self.cell, "command": f"python3 {script}", "shellLine": f"FAKE_CELL=die exec python3 {script} --port {self.cell}", "cacheModels": True, "config": {}}
        self.step("a cell that dies", "POST", "/api/llama-node/start", payload)
        node = self.wait_cell(self.cell, lambda node: bool(node) and (node.get("crash") or {}).get("count"), "crashed")
        self.record.add("its note", Shape.clean({key: (node.get("crash") or {}).get(key) for key in ("count", "reason", "gaveUp", "neverReady")}))
        self.record.add("its card", {key: node.get(key) for key in ("phase", "running", "exitCode", "crashed", "lastError")})
        node = self.wait_cell(self.cell, lambda node: bool(node) and (node.get("crash") or {}).get("count", 0) >= 2, "crashed twice", 20)
        self.record.add("restarted the same way", Shape.clean((node.get("crash") or {}).get("reason")))
        self.step("a start by hand clears the note", "POST", "/api/llama-node/stop", {"port": self.cell})

    def survivors(self):
        payload = {"port": self.cell, "modelPath": str(self.home / "library" / "held.gguf"), "args": ["--port", str(self.cell), "-m", "{{MODEL_PATH}}"], "config": {"MODEL_NAME": "survivor"}, "cacheModels": False}
        self.step("a cell", "POST", "/api/llama-node/start", payload)
        self.running()
        self.side.kill()
        self.side.start()
        node = self.running()
        self.record.add("held again", Shape.clean({key: node.get(key) for key in ("running", "adopted", "phase", "port", "modelPath", "pids")}))
        self.step("its name kept", "GET", "/v1/models")
        self.step("it stops", "POST", "/api/llama-node/stop", {"port": self.cell})
        self.wait_cell(self.cell, lambda node: not node, "went")
        self.record.add("nothing runs it", self.answers(self.cell))

    def known(self):
        self.controller.cells = [{"port": self.cell, "config": {"MODEL_NAME": "kept one", "RUNNER": "vllm", "SECRET": "x"}, "modelPath": "a/b.gguf"},
                                 {"port": self.cell + 1, "config": {"MODEL_NAME": "kept one", "RUNNER": "llama-server"}},
                                 {"port": self.cell + 2, "config": {"MODEL_FILE": "c/d-00001-of-00002.gguf"}},
                                 {"port": "nope"}]
        self.step("a beat brings the cells", "POST", "/api/heartbeat", {})
        self.step("the list says them", "GET", "/v1/models")
        self.step("a request for a stopped one", "POST", "/v1/chat/completions", {"model": "kept one@vllm"})
        self.controller.cells = None

    def beats(self):
        last = self.controller.beats[-1] if self.controller.beats else {}
        self.record.add("what a beat says, its keys", sorted(last))
        for key in ("host", "platform", "gpus", "gpuError", "computeApps", "scoutVersion", "autostart", "autostartRequests", "telemetry", "llamaUpdate", "llamaSuspect", "prismRuntime", "engines"):
            self.record.add(f"a beat's {key}", Shape.clean(last.get(key)))
        self.record.add("a beat's address", last.get("agentUrl"))

    def engines(self):
        if self.engine is None:
            return
        deadline = time.time() + 25
        state = {}
        while time.time() < deadline:
            state = self.ask("GET", "/api/state").json
            if state.get("engines"):
                break
            time.sleep(0.2)
        self.record.add("the engine found", Shape.clean(state.get("engines")))
        act = "/api/engines/unload"
        self.step("an action of no engine", "POST", act, {"kind": "none", "port": 1, "model": "x"})
        self.step("a port of no number", "POST", act, {"kind": "ollama", "port": "x", "model": "x"})
        self.step("a model not listed", "POST", act, {"kind": "ollama", "port": 11434, "model": "none"})
        self.step("not loaded", "POST", act, {"kind": "ollama", "port": 11434, "model": "idle:1"})
        self.step("delete, loaded", "POST", "/api/engines/delete", {"kind": "ollama", "port": 11434, "model": "loaded:1"})
        self.step("a server of no way to start", "POST", "/api/engines/start", {"kind": "ollama", "port": 11434})
        answer = self.step("unload", "POST", act, {"kind": "ollama", "port": 11434, "model": "loaded:1"})
        self.record.add("unload's answer", answer.status)
        self.settle_engine("loaded:1")
        answer = self.step("delete that fails", "POST", "/api/engines/delete", {"kind": "ollama", "port": 11434, "model": "idle:1"})
        failed = self.settle_engine("idle:1")
        self.record.add("the failure stays on the model", Shape.clean((failed or {}).get("actionError")))
        self.record.add("what the engine heard", {"unloaded": list(self.engine.unloaded), "deleted": list(self.engine.deleted)})
        self.engine.unloaded.clear()
        self.engine.deleted.clear()

    def settle_engine(self, model):
        deadline = time.time() + 10
        row = None
        while time.time() < deadline:
            engines = self.ask("GET", "/api/state").json.get("engines") or []
            rows = [row for view in engines for row in (view.get("models") or []) if row.get("name") == model]
            row = rows[0] if rows else None
            if row is None or "action" not in row:
                return row
            time.sleep(0.1)
        return row

    def pairing(self):
        pair = "/api/controller-url"
        address = f"http://127.0.0.1:{self.ports['controller']}"
        self.step("no address", "POST", pair, {})
        self.step("no web address", "POST", pair, {"url": "ftp://x"})
        self.step("paired again", "POST", pair, {"url": address + "/"})
        self.step("the page says it", "GET", "/api/pairing")
        self.step("let go", "POST", "/api/unpair", {})
        self.step("the page says that", "GET", "/api/pairing")
        self.step("no controller for a beat", "POST", "/api/heartbeat", {})
        self.record.add("the file forgot it", json.loads(self.side.config_path.read_text()).get("controllerUrl"))
        self.step("paired with a token", "POST", pair, {"url": address, "token": "fleet-one"})
        self.record.add("the token in the file", json.loads(self.side.config_path.read_text()).get("controllerToken"))
        self.record.add("the beat carried it", self.controller.tokens[-1])
        for name, path, fields in (("no token", "/api/state", None), ("a wrong one", "/api/state", {"X-Caravan-Token": "wrong"}), ("an unknown path", "/nope", None), ("the page", "/", None),
                                   ("open health", "/api/health", None), ("open list", "/v1/models", None), ("open spec", "/openapi.json", None)):
            self.step(f"gate: {name}", "GET", path, fields=fields, shape=path in ("/openapi.json",))
        self.step("gate: the right one", "GET", "/api/llama-node/status", fields={"X-Caravan-Token": "fleet-one"})
        self.step("gate: unknown with it", "GET", "/nope", fields={"X-Caravan-Token": "fleet-one"})
        self.step("gate: POST", "POST", "/api/llama-node/stop", {})
        self.step("gate: POST nowhere", "POST", "/nope", {})
        self.step("gate: a form's token", "POST", pair, {"url": "http://other:1", "token": "fleet-one"}, status_only=True)
        self.step("gate: another address, a wrong token", "POST", pair, {"url": "http://other:1", "token": "wrong"})
        self.controller.refuse_token = "refused"
        self.step("gate: a token the controller refuses", "POST", pair, {"url": address, "token": "refused"}, fields={"X-Caravan-Token": "no"})
        self.controller.refuse_token = ""
        self.step("back to the controller", "POST", pair, {"url": address, "token": "fleet-one"}, fields={"X-Caravan-Token": "fleet-one"})
        self.step("a rotated token, same controller", "POST", pair, {"url": address, "token": "fleet-two"})
        self.record.add("taken", json.loads(self.side.config_path.read_text()).get("controllerToken"))
        self.step("let go at last", "POST", "/api/unpair", {}, fields={"X-Caravan-Token": "fleet-two"})

    def run(self):
        self.controller.beats.clear()
        self.controller.tokens.clear()
        self.side.write_config()
        self.home.mkdir(parents=True, exist_ok=True)
        self.side.start()
        for part in (self.surface, self.tables, self.refusals, self.llama_cell, self.cache, self.command_cell, self.strata_shelf, self.crash, self.survivors, self.known, self.beats, self.engines,
                     self.pairing):
            part()
        self.side.stop_all()


class Differences:
    """What the run said against what is kept."""

    #: What the program has and the scout in Python never had: it takes a new release of itself from its controller, and it can turn its cache off.
    NEWER = {"/api/scout/update", "/api/llama-node/cache/off", "off", "library"}

    def __init__(self, frozen: FrozenAnswers, own: OwnWords):
        self.frozen, self.own = frozen, own
        self.found: list[str] = []

    @classmethod
    def walk(cls, left, right, where=""):
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                if key not in left:
                    if key not in cls.NEWER:
                        yield f"{where}.{key}: only said now: {str(right[key])[:160]}"
                elif key not in right:
                    yield f"{where}.{key}: only kept: {str(left[key])[:160]}"
                else:
                    yield from cls.walk(left[key], right[key], f"{where}.{key}")
        elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
            for at, (one, other) in enumerate(zip(left, right)):
                yield from cls.walk(one, other, f"{where}[{at}]")
        elif left != right:
            yield f"{where}: kept {str(left)[:220]} | said {str(right)[:220]}"

    def compare(self, record: Record, engine_ran: bool) -> list[str]:
        for name, said in record.steps:
            now = self.own.clean(said)
            kept = self.frozen.said(name, now)
            if kept is FrozenAnswers.NOTHING:
                self.found.append(f"{name}: no answer is kept for it, and it said {str(now)[:200]}")
            else:
                self.found.extend(f"{name}{line}" for line in self.walk(kept, now))
        if engine_ran:
            self.found.extend(f"{key}: kept, and nothing asked it" for key in self.frozen.unasked())
        return self.found


class Binary:
    """The Rust scout to compare."""

    @staticmethod
    def find() -> Path | None:
        said = os.environ.get("CARAVAN_RUST_SCOUT_BIN")
        if said:
            return Path(said).resolve()
        found = [RUST / "target" / kind / BINARY_NAME for kind in ("debug", "release")]
        found = [path for path in found if path.exists()]
        return max(found, key=lambda path: path.stat().st_mtime) if found else None


def run_side(name, argv, root, ports, controller, engine, stand_ins):
    shutil.rmtree(root / "home", ignore_errors=True)
    shutil.rmtree(root / "server-cells", ignore_errors=True)
    for file in ("state.json", "config.json"):
        (root / file).unlink(missing_ok=True)
    side = Side(name, root, ports, stand_ins, argv)
    record = Record()
    scenario = Scenario(side, controller, ports, record, engine)
    try:
        scenario.run()
    except Exception:
        print(f"{name}: the scenario stopped at step {len(record.steps)}: {record.steps[-1][0] if record.steps else 'none'}")
        print(side.log.read_text(errors="replace")[-3000:] if side.log.exists() else "")
        raise
    finally:
        side.stop_all()
        for port in (ports["cell"],):
            leftover = subprocess.run(["pgrep", "-f", f"--port {port}"], capture_output=True, text=True).stdout.split()
            for pid in leftover:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except OSError:
                    pass
    return record


class Run:
    """One whole run of the scenario on the program."""

    @staticmethod
    def argv(binary):
        """The command that starts it."""
        return [str(binary)]

    @classmethod
    def go(cls, binary, writing):
        frozen = FrozenAnswers("scout", writing=writing)
        with tempfile.TemporaryDirectory(prefix="scout-compare-") as folder:
            root = Path(folder).resolve()
            ports = {"scout": free_port(), "controller": free_port(), "cell": free_port()}
            stand_ins = StandIns(root / "bin")
            controller = FakeController(ports["controller"])
            engine = None
            try:
                engine = FakeOllama()
            except OSError:
                print("port 11434 is taken here: the engines are not compared")
            try:
                record = run_side("program", cls.argv(binary), root, ports, controller, engine, stand_ins)
            finally:
                controller.close()
                if engine is not None:
                    engine.close()
            own = OwnWords({root: "<root>", SCOUT_ROOT: "<scout>"}, {ports["scout"]: "<scout port>", ports["controller"]: "<controller port>", ports["cell"]: "<cell port>", ports["cell"] + 1: "<cell port + 1>", ports["cell"] + 2: "<cell port + 2>"})
            differences = Differences(frozen, own)
            differences.compare(record, engine is not None)
        return frozen, differences.found, len(record.steps)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="keep what the program says now as what it promises: its diff is what changed")
    args = parser.parse_args()
    binary = Binary.find()
    if binary is None:
        print("rust scout conformance: the scout's binary is not here: nothing compared")
        return 1 if os.environ.get("CARAVAN_RUST_REQUIRED") else 0
    if sys.platform != "linux":
        print(f"rust scout conformance: the kept answers are a Linux machine's, and this is {sys.platform}: nothing compared")
        return 0
    frozen, found, steps = Run.go(binary, args.write)
    if args.write:
        frozen.write()
        print(f"rust scout conformance: kept {len(frozen.rows)} answers in {frozen.path.relative_to(REPO)}")
        return 0
    if found:
        print(f"rust scout conformance: FAILED, {len(found)} differences in {steps} steps")
        for line in found:
            print(" -", line)
        return 1
    print(f"rust scout conformance: ok, {steps} steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
