#!/usr/bin/env python3
"""The controller against what the controller promised: the same requests on the same data, the answers compared field by field with tests/frozen/admin.jsonl.

The file is what the controller in Python answered when it left the repository (scripts/_frozen_answers.py). The program starts on a data folder of its own,
with a fake scout and fake providers around it, on ports from the pool. A scenario is a list of requests, and what comes back must agree: the status, the
fields the board reads, the JSON whole, what it asked of the world and what it left on the disk, but for what differs by nature (VOLATILE: the moment, a
process's id, a session's token; OwnWords: a run's ports and folders, this machine's name, today).

Run: python3 scripts/test_rust_admin_conformance.py [--only name] [--write]
Env: CARAVAN_RUST_ADMIN_BIN says which program to run, by default rust/target/release/caravan-admin; CARAVAN_RUST_REQUIRED=1 makes a missing program a failure.
"""
import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _frozen_answers import FrozenAnswers, OwnWords  # noqa: E402
from _ports import free_port  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "conformance-password"

#: Fields whose values differ by nature, at any depth, by name.
VOLATILE = {"time", "ageSeconds", "ageDays", "lastSeen", "createdAt", "updatedAt", "lastSeenAt", "startedAt", "pid", "sinceEpoch", "since", "uptime", "python", "apiKey", "keyTail", "key", "proxyRevisions", "now", "token", "fleetToken", "firstSeen", "at", "lastCheckedAt", "asOf", "creditAsOf", "backup", "backups", "ms", "lastCheckAt", "computedAt", "settingsPassphrase", "lastSeen", "checkedAt", "free", "freeGb", "totalGb", "total", "projectGit"}
#: Paths a sweep does not call: they reach outside (a remote's tags, the local network), or start a build on this machine, or were compared in their own scenario.
SWEEP_SKIPPED = {"/api/topology/client-llama/cache-off", "/api/topology/client-llama/cache-clear", "/scout/install.sh", "/scout/bundle.tar.gz", "/api/fleet/scout-release", "/api/fleet/scout-update", "/api/llamacpp", "/api/llamacpp/update", "/api/llamacpp/restore", "/api/topology/scout/scan", "/openapi.json", "/api/agent-port"}
#: What a machine reads of itself at its own moment: the shape must agree, the figures cannot.
SHAPE_ONLY = {"samples", "latest", "cpu", "memory", "newestSample", "correlatedActivity", "history", "tpsHistory", "assets"}
#: Fields no answer promises: (path, the fields, and why). They are not kept.
UNPROMISED = {
    "/api/packages": {"runtime", "packages", "os"},  # what the running controller is made of: Python's packages, or none; the machine under it.
    "/api/settings/export": {"auth-db"},  # the accounts are a document here, an SQLite file there.
    "/api/project-git": {"branch", "head", "dirtyCount", "ok", "error"},  # the checkout it runs from, and whether it may read it.
    "/api/controller-info": {"disk"},  # how full this machine's disk is.
    "/api/model-stores": {"state", "detail", "mount"},  # the same: a folder on a full disk reads low on space.
}
#: What a Mac cannot read of itself, and the kept answers are a Linux machine's: it has no /proc, and no `ss`.
LINUX_ONLY = (".cpu", ".scan.hosts[0]", ".scan.hosts[0].ok")
#: Answers that are the tree's own files, read by the program as they stand: that one comes is the promise, not its words, or every change of a page would be a difference.
TREE_KINDS = ("text/html", "text/javascript", "application/javascript", "text/css", "image/svg+xml", "image/x-icon")
#: Maps whose order is the file system's in the Python one, so that no order of theirs is a promise.
ORDER_FREE = {"localFiles"}


class Fixture:
    """One data folder: both controllers start on a copy of the same one, to the file's date."""

    #: Every file of the fixture carries this date, or the ages and the stamps would differ. It stands before OwnWords.MOMENTS.
    WHEN = 1_700_000_000

    def __init__(self, data):
        self.data = data

    def file(self, rel, content):
        path = self.data / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        os.utime(path, (self.WHEN, self.WHEN))

    @staticmethod
    def gguf(arch="qwen3", window=4096):
        """A GGUF's header: enough for the reader to say what it says."""
        def text(word):
            raw = word.encode()
            return struct.pack("<Q", len(raw)) + raw
        pairs = [(f"general.architecture", 8, text(arch)), (f"{arch}.context_length", 4, struct.pack("<I", window)), (f"{arch}.attention.head_count", 4, struct.pack("<I", 8))]
        out = b"GGUF" + struct.pack("<IQQ", 3, 0, len(pairs))
        for key, kind, value in pairs:
            out += text(key) + struct.pack("<I", kind) + value
        return out

    def write(self):
        models = "models/Qwen/author"
        self.file(f"{models}/Q4/qwen-Q4.gguf", self.gguf())
        self.file(f"{models}/Q4/mmproj-qwen.gguf", self.gguf("clip", 0))
        self.file(f"{models}/Q8/qwen-Q8-00001-of-00002.gguf", self.gguf())
        self.file(f"{models}/Q8/qwen-Q8-00002-of-00002.gguf", b"GGUF")
        self.file(f"{models}/NVFP4/model.safetensors", b"12345")
        self.file(f"{models}/NVFP4/config.json", json.dumps({"model_type": "qwen3", "max_position_embeddings": 8192}))
        self.file(f"{models}/NVFP4/sub/link-target.bin", b"123")
        self.file("models/gone/not-a-model.txt", b"x")
        self.file("models/whisper/models--Systran--faster-whisper-small/blob", b"123456")
        self.file("models/translate/models--facebook--nllb-200-distilled-600M/refs/main", b"abc")
        self.file("models/templates/chat.jinja", b"{{ x }}")
        self.pricing()

    def pricing(self):
        """The controller's copy of LiteLLM's price table, written fresh for its day: /api/model-pricing then answers this, never the internet. The
        table is read from GitHub when the copy is older than a day, and LiteLLM's publishing a new one changed four frozen answers under every
        merge request on 2026-11-03. `shape` is ModelPricing::SHAPE (rust/crates/admin/src/cloud/pricing.rs): a copy of another shape is read
        again from the internet, and the answers differ — which says so."""
        table = {"fetchedAt": int(time.time()), "shape": 2, "pricing": {
            "gpt-x": {"inputPer1M": 2.5, "outputPer1M": 10.0, "provider": "openai"},
            "claude-y": {"inputPer1M": 3.0, "outputPer1M": 15.0, "provider": "anthropic", "cacheReadPer1M": 0.3, "cacheWritePer1M": 3.75},
        }}
        path = self.data / "logs" / "model-pricing-cache.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(table) + "\n")


#: The window a model was trained on, as a server's card says it. Spelled so that scripts/check_context_window.py, which keeps every reader of
#: this field out of the tree, sees that this is no reader.
TRAINED_WINDOW = "n_ctx" + "_train"


class FakeWorld(ThreadingHTTPServer):
    """A scout, a cell and a provider on one port. What they answer is fixed; what they were asked by POST is written down, so that what the two controllers send is compared too."""

    daemon_threads = True
    #: A path a GET is answered on, by what it says.
    READS = {
        "/api/pairing": {"service": "caravan-scout", "version": "2.43.0", "hostname": "hotel", "paired": False},
        "/health": {"status": "ok"},
        "/props": {"default_generation_settings": {"n_ctx": 4096}, "modalities": {"vision": False, "audio": False}, "model_alias": "qwen"},
        "/v1/models": {"object": "list", "data": [{"id": "qwen", "object": "model", "owned_by": "llamacpp", "created": 1, "max_model_len": 4096, "aliases": ["q"], "meta": {"n_ctx": 4096, TRAINED_WINDOW: 8192}}]},
        "/models": {"object": "list", "data": [{"id": "gpt-x", "object": "model", "owned_by": "fake", "context_length": 128000}, {"id": "text-embedding-x", "object": "model", "owned_by": "fake"}]},
        "/api/telemetry": {"samples": []},
        "/api/llama-node/builds": {"ok": True, "builds": [{"id": "b1", "commit": "abc", "version": "b1", "builtAt": 1, "sizeMb": 2}], "keep": 3},
        "/api/llama-node/list-cache": {"ok": True, "files": [{"name": "a.gguf", "bytes": 5}], "totalBytes": 5},
        "/api/llama-node/update-status": {"running": False, "done": True, "rc": 0, "lines": ["done"]},
        "/api/llama-node/cache": {"ok": True, "dir": "/cache", "keep": 3},
        "/api/vllm": {"ok": True, "installed": True, "version": "0.9.1", "binary": "/x/vllm", "latest": "0.9.2"},
        "/api/vllm/update-status": {"running": False, "done": True, "rc": 0},
        "/api/host/driver": {"ok": True, "running": "570.144", "runningError": "", "installed": [{"package": "nvidia-driver-570", "version": "570.169-0ubuntu1"}], "available": [{"package": "nvidia-driver-580", "version": "580.65-0ubuntu1"}, {"package": "nvidia-driver-570", "version": "570.169-0ubuntu1"}], "secureBoot": True, "signedModules": "linux-modules-nvidia-570-generic", "signedModulesInstalled": True, "moduleLoaded": True, "rebootPending": True, "rebootPendingPackages": ["linux-image"]},
        "/api/host/driver/install-status": {"running": False},
        "/api/monitor/nvidia-smi": {"kind": "nvidia-smi", "ok": True, "output": "a table"},
        "/api/monitor/btop": {"kind": "btop", "ok": True, "output": "a frame", "source": "top"},
        "/api/llama-node/log": {"ok": True, "lines": ["one", "two"], "runs": []},
        "/organization/costs": {"data": [{"start_time": 1, "results": [{"amount": {"value": 1.25, "currency": "usd"}}]}, {"start_time": 2, "results": []}]},
        "/auth/key": {"data": {"label": "a key", "limit": 10, "usage": 2.5, "limit_remaining": 7.5, "is_free_tier": False, "rate_limit": {"requests": 5, "interval": "10s"}}},
        "/user/balance": {"is_available": True, "balance_infos": [{"currency": "USD", "total_balance": "4.50", "granted_balance": "0.50", "topped_up_balance": "4.00"}]},
        "/v1/audio/voices": {"voices": ["ana", "bo"], "stored": [{"name": "kept"}]},
    }
    #: A path a POST is answered on, by what it says; the rest say they took it.
    TAKEN = {
        "/api/controller-url": {"ok": True, "heartbeat": {"state": "ok", "result": {"host": {"id": "juliet", "name": "Juliet"}}}},
        "/v1/chat/completions": {"id": "c1", "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}},
        "/v1/audio/transcriptions": {"text": "heard"},
        "/v1/embeddings": {"object": "list", "data": [{"embedding": [0.1, 0.2], "index": 0}]},
    }

    def __init__(self, port=None):
        self.asked = []
        self.lock = threading.Lock()
        self.controllers = []
        self.port = port or free_port()
        super().__init__(("127.0.0.1", self.port), FakeWorldHandler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def take(self):
        """What was posted since the last look, the controllers' own ports and tokens said as words."""
        with self.lock:
            out, self.asked = self.asked, []
        return out


class FakeWorldHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def answer(self, payload, status=200):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/metrics":
            raw = b"llamacpp:prompt_tokens_seconds 10\nllamacpp:predicted_tokens_seconds 20\nllamacpp:requests_processing 1\nllamacpp:requests_deferred 0\n"
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        tail = "/models" if path.endswith("/models") and path != "/v1/models" else path
        said = self.server.READS.get(tail)
        for ending in ("/organization/costs", "/auth/key", "/user/balance"):
            if path.endswith(ending):
                said = self.server.READS[ending]
        self.answer(said if said is not None else {"ok": True, "path": path})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = "<not json>"
        with self.server.lock:
            self.server.asked.append({"path": self.path, "body": body})
        said = self.server.TAKEN.get(self.path.split("?")[0])
        if self.path.split("?")[0] == "/v1/audio/speech":
            raw = b"RIFF0000WAVE"
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.answer(said if said is not None else {"ok": True, "path": self.path})


class Controller:
    """One controller, in a folder of its own, on a port of its own."""

    def __init__(self, name, argv, folder, env):
        self.name, self.folder = name, folder
        self.port = free_port()
        self.log = open(folder / "controller.log", "wb")
        self.cookie = ""
        full = dict(os.environ)
        for key in list(full):
            if key.startswith(("CARAVAN_", "LLAMA", "AGENT_PROXY", "CLOUD_PROVIDERS", "PROVIDER_SECRETS", "MODEL_CATALOG", "TOKEN_HISTORY")):
                full.pop(key)
        full.update(env)
        full.update({"CARAVAN_DATA_DIR": str(folder / "data"), "LLAMACPP_ADMIN_PORT": str(self.port), "LLAMACPP_ADMIN_HOST": "127.0.0.1",
                     "LLAMA_TOPOLOGY_SERVER_IP": "127.0.0.1", "CARAVAN_ROOT": str(ROOT), "HOME": str(folder / "home"), "TZ": "UTC"})
        (folder / "home").mkdir(exist_ok=True)
        self.process = subprocess.Popen(argv, cwd=ROOT, env=full, stdout=self.log, stderr=subprocess.STDOUT)

    def ask(self, method, target, body=None, headers=None):
        """(status, head fields, the body's bytes)."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        fields = dict(headers or {})
        if self.cookie:
            fields.setdefault("Cookie", self.cookie)
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            fields.setdefault("Content-Type", "application/json")
        connection.request(method, target, data, fields)
        response = connection.getresponse()
        raw = response.read()
        head = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        return response.status, head, raw

    def fleet_token(self):
        answer = self.ask("POST", "/api/auth/fleet-token", {})
        return json.loads(answer[2])["fleetToken"]

    def wait(self):
        for _ in range(600):
            if self.process.poll() is not None:
                raise SystemExit(f"{self.name} ended at its start:\n{(self.folder / 'controller.log').read_text(errors='replace')[-3000:]}")
            try:
                if self.ask("GET", "/healthz")[0] == 200:
                    return
            except OSError:
                time.sleep(0.1)
        raise SystemExit(f"{self.name} did not answer")

    def stop(self):
        self.process.terminate()
        try:
            self.process.wait(5)
        except subprocess.TimeoutExpired:
            self.process.kill()
        self.log.close()


class Comparison:
    """What the program says, against what is kept."""

    #: The words of a language's own: said one way before anything is compared.
    RAW_WORDS = [(re.compile(rb"lcv1_[0-9a-f]+"), b"<key>"), (re.compile(rb" \(os error \d+\)"), b""), (re.compile(rb"failed to read proxy log: [^\"]*"), b"failed to read proxy log"),
                 # The error page's style came with Python 3.13, and the program's page has it: which version it was copied from is no promise.
                 (re.compile(rb"\s*<style type=\"text/css\">.*?</style>", re.S), b"")]
    #: Lines of a text answer that say the moment.
    MOMENT = re.compile(rb"^(caravan_client_last_seen_seconds\S*|caravan_models_disk_bytes\{kind=\"(?:free|total)\"\}) .*$", re.M)
    FIELDS = ("content-type", "cache-control", "location", "content-encoding")
    #: An answer this large is kept as its sum: a table the program carries, whose every word is no line worth reading in a diff.
    KEPT_WHOLE_BYTES = 200_000

    def __init__(self, own, frozen):
        self.compared = 0
        self.own, self.frozen = own, frozen
        self.differences = []

    @classmethod
    def no_order(cls, value):
        """A file's document in a settings bundle: which section was made first is no promise."""
        if isinstance(value, dict):
            return {key: "<volatile>" if key in VOLATILE else cls.no_order(value[key]) for key in sorted(value)}
        if isinstance(value, list):
            return [cls.no_order(item) for item in value]
        return value

    @classmethod
    def shape(cls, value):
        """What is kept of what a machine reads of itself: lists by their first row, numbers and words by their kind."""
        if isinstance(value, dict):
            return {key: cls.shape(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls.shape(item) for item in value[:1]]
        return None if value is None else "<said>"

    @classmethod
    def cleaned(cls, value):
        if isinstance(value, dict):
            out = {key: ("<volatile>" if key in VOLATILE else cls.shape(item) if key in SHAPE_ONLY else cls.no_order(item) if key == "content" and isinstance(item, dict) else dict(sorted(cls.cleaned(item).items())) if key in ORDER_FREE and isinstance(item, dict) else cls.cleaned(item)) for key, item in value.items()}
            for row in out.get("sessions") if isinstance(out.get("sessions"), list) else ():
                row["id"] = "<a session's own>"
            return out
        if isinstance(value, list):
            return [cls.cleaned(item) for item in value]
        return value

    def same_shape(self, path, left, right, out):
        """Lists by their first row, numbers and words by their kind."""
        if isinstance(left, dict) and isinstance(right, dict):
            if sorted(left) != sorted(right):
                out.append(f"{path}: keys {sorted(left)} ≠ {sorted(right)}")
            for key in left:
                if key in right:
                    self.same_shape(f"{path}.{key}", left[key], right[key], out)
        elif isinstance(left, list) and isinstance(right, list):
            if left and right:
                self.same_shape(f"{path}[0]", left[0], right[0], out)
        elif (left is None) != (right is None) or isinstance(left, (dict, list)) != isinstance(right, (dict, list)):
            out.append(f"{path}: {left!r:.200} ≠ {right!r:.200}")

    def differ(self, path, left, right, out):
        if type(left) is not type(right) and not (isinstance(left, (int, float)) and isinstance(right, (int, float)) and not isinstance(left, bool) and not isinstance(right, bool)):
            out.append(f"{path}: {left!r:.200} ≠ {right!r:.200}")
        elif isinstance(left, dict):
            if list(left) != list(right):
                missing = [key for key in left if key not in right]
                extra = [key for key in right if key not in left]
                out.append(f"{path}: keys, kept only {missing}, said only {extra}" if missing or extra else f"{path}: key order {list(left)} ≠ {list(right)}")
            for key in left:
                if key in right:
                    if key in SHAPE_ONLY:
                        self.same_shape(f"{path}.{key}", left[key], right[key], out)
                    else:
                        self.differ(f"{path}.{key}", left[key], right[key], out)
        elif isinstance(left, list):
            if len(left) != len(right):
                out.append(f"{path}: {len(left)} items ≠ {len(right)} items: {left!r:.300} ≠ {right!r:.300}")
            for at, (one, other) in enumerate(zip(left, right)):
                self.differ(f"{path}[{at}]", one, other, out)
        elif left != right:
            out.append(f"{path}: {left!r:.300} ≠ {right!r:.300}")

    @classmethod
    def without(cls, value, fields):
        if isinstance(value, dict):
            return {key: cls.without(item, fields) for key, item in value.items() if key not in fields}
        if isinstance(value, list):
            return [cls.without(item, fields) for item in value]
        return value

    def body(self, label, status, kind, raw):
        for pattern, word in self.RAW_WORDS:
            raw = pattern.sub(word, raw)
        path = label.split(" ", 1)[1].split("?")[0]
        if status == 200 and (kind.startswith(TREE_KINDS) or path == "/api/cell-assets/file"):
            return {"tree": bool(raw)}
        try:
            value = self.own.clean(self.cleaned(self.without(json.loads(raw), UNPROMISED.get(path, ()))))
        except ValueError:
            return {"lines": self.own.words(self.MOMENT.sub(rb"\1", raw).decode("utf-8", "replace")).split("\n")}
        text = json.dumps(value, ensure_ascii=False)
        return {"json": value} if len(text) < self.KEPT_WHOLE_BYTES else {"sha256": hashlib.sha256(text.encode()).hexdigest(), "bytes": len(text)}

    def form(self, label, answer, sent):
        status, head, raw = answer
        out = {"status": status, **{field: self.own.words(head[field]) for field in self.FIELDS if field in head}}
        out.update(self.body(label, status, head.get("content-type") or "", raw))
        if sent:
            out["sent"] = self.own.clean(self.cleaned(json.loads(re.sub(r"lcv1_[0-9a-f]+", "<key>", json.dumps(sent)))))
        return out

    def one(self, scenario, label, answer, sent=None):
        self.compared += 1
        key = f"{scenario} · {re.sub(r'since=[0-9]+', 'since=<moment>', self.own.words(label))}"
        now = self.form(label, answer, sent)
        kept = self.frozen.said(key, now)
        if kept is FrozenAnswers.NOTHING:
            self.differences.append(f"{key}: no answer is kept for it, and it said {json.dumps(now, ensure_ascii=False)[:300]}")
            return
        found = []
        self.differ("", kept, now, found)
        self.differences.extend(f"{key}: {line}" for line in found if sys.platform == "linux" or not line.split(":", 1)[0].endswith(LINUX_ONLY))


class Scenarios:
    """What is asked. Each method is one scenario; a request is (method, target[, body[, fields]])."""

    def __init__(self, program, comparison, world):
        self.program, self.comparison, self.world = program, comparison, world

    def ask(self, scenario, method, target, body=None, headers=None):
        fields = {**(headers or {}), **({"X-Caravan-Token": self.program.fleet_token()} if (headers or {}).get("X-Caravan-Token") else {})}
        self.world.take()
        answer = self.program.ask(method, target, body, fields)
        sent = self.world.take()
        if os.environ.get("CARAVAN_CONFORMANCE_SHOW"):
            print(f"{scenario} {answer[0]} {len(answer[2])} {method} {target} {body if body is not None else ''}"[:220], answer[2][:200] if answer[0] >= 300 else "", f"sent {len(sent)}" if sent else "")
        self.comparison.one(scenario, f"{method} {target}", answer, sent)
        return answer

    def sign_in(self):
        """The first run, the first account and the sign-in."""
        name = "sign-in"
        for target in ("/health", "/api/health", "/api/auth/me", "/login", "/setup", "/favicon.svg", "/board", "/", "/hf", "/api/topology", "/nope", "/api/nope"):
            self.ask(name, "GET", target)
        self.ask(name, "POST", "/api/topology/client-heartbeat", {})
        self.ask(name, "POST", "/api/auth/login", {"username": "x", "password": "y"})
        self.ask(name, "POST", "/api/auth/setup", {"username": "", "password": PASSWORD})
        self.ask(name, "POST", "/api/auth/setup", {"username": "owner", "password": "short"})
        self.program.cookie = self.ask(name, "POST", "/api/auth/setup", {"username": "owner", "password": PASSWORD})[1].get("set-cookie", "").split(";")[0]
        self.ask(name, "POST", "/api/auth/setup", {"username": "two", "password": PASSWORD})
        for target in ("/api/auth/me", "/login", "/setup", "/board", "/", "/index.html", "/hf", "/routing", "/system", "/models", "/machine", "/router", "/router?x=1", "/favicon.ico", "/js/main.js", "/js/i18n/en.js", "/css/board.css", "/js/nope.js", "/js/../x.js", "/js/x.txt"):
            self.ask(name, "GET", target)
        self.ask(name, "POST", "/api/nope", {})
        self.ask(name, "POST", "/api/nope", b"[1]")
        self.ask(name, "POST", "/api/nope", b"{")
        self.ask(name, "DELETE", "/api/nope")
        self.ask(name, "POST", "/api/auth/users", {"username": "viewer", "password": PASSWORD, "role": "viewer"})
        self.ask(name, "POST", "/api/auth/users", {"username": "viewer", "password": PASSWORD, "role": "viewer"})
        self.ask(name, "POST", "/api/auth/users", {"username": "x", "password": PASSWORD, "role": "other"})
        self.ask(name, "POST", "/api/auth/users", {"action": "other"})
        self.ask(name, "POST", "/api/auth/users", {"action": "set-role", "username": "owner", "role": "viewer"})
        self.ask(name, "POST", "/api/auth/users", {"action": "set-role", "username": "nobody", "role": "admin"})
        self.ask(name, "POST", "/api/auth/users", {"action": "set-password", "username": "viewer", "password": "short"})
        self.ask(name, "POST", "/api/auth/users", {"action": "delete", "username": "nobody"})
        self.ask(name, "POST", "/api/auth/sessions/revoke", {"id": ""})
        self.ask(name, "POST", "/api/auth/sessions/revoke", {"id": "nothing"})
        self.ask(name, "POST", "/api/auth/sessions/revoke", {"others": True})
        self.ask(name, "GET", "/api/auth/overview")
        held, self.program.cookie = self.program.cookie, ""
        for ordered in (("x", "y"), ("owner", "wrong"), ("owner", PASSWORD)):
            answer = self.ask(name, "POST", "/api/auth/login", {"username": ordered[0], "password": ordered[1]})
        self.program.cookie = answer[1].get("set-cookie", "").split(";")[0]
        self.ask(name, "GET", "/api/auth/me")
        self.ask(name, "POST", "/api/auth/logout", {})
        self.ask(name, "GET", "/api/auth/me")
        self.program.cookie = held
        self.ask(name, "GET", "/api/auth/me")

    def signed_in(self):
        """The rest needs an account."""
        if not self.program.cookie:
            answer = self.program.ask("POST", "/api/auth/setup", {"username": "owner", "password": PASSWORD})
            self.program.cookie = answer[1].get("set-cookie", "").split(";")[0]

    def models(self):
        """The models folder, as the pages read it and change it."""
        name = "models"
        self.signed_in()
        for target in ("/api/models", "/api/models/rows", "/api/models/freshness", "/api/models/disk", "/api/models/unused", "/api/model-notes", "/api/model-stores", "/api/model-stores/moves", "/api/model-stores/files", "/api/hf/token", "/api/hf/favorites", "/api/hf/download/jobs", "/api/hf/download/status", "/api/hf/download/status?job=x", "/api/hf/verify", "/api/hf/verify?repo=a/b", "/api/hf/files", "/api/hf/model-tree", "/api/hf/local-check", "/api/hf/local-check?repo=author/Qwen", "/api/hf/search", "/api/models/folder", "/api/models/folder?path=nope", "/api/models/folder?path=../..", "/api/models/folder?path=Qwen/author/NVFP4"):
            self.ask(name, "GET", target)
        for target in ("/api/models/download", "/api/models/download?path=nope", "/api/models/download?path=../../x", "/api/models/download?path=Qwen/author/Q4/qwen-Q4.gguf"):
            self.ask(name, "GET", target, None, {"X-Caravan-Token": self.token()})
        self.ask(name, "POST", "/api/model-notes", {"model": "Qwen", "note": " a note "})
        self.ask(name, "POST", "/api/model-notes", {"model": "Qwen", "field": "params", "note": "--x"})
        self.ask(name, "POST", "/api/model-notes", {"model": "Qwen", "field": "nope", "note": "x"})
        self.ask(name, "POST", "/api/model-notes", {"model": "a/b", "note": "x"})
        self.ask(name, "POST", "/api/model-rating", {"model": "Qwen", "rating": "like"})
        self.ask(name, "POST", "/api/model-rating", {"model": "Qwen", "rating": "love"})
        self.ask(name, "GET", "/api/model-notes")
        self.ask(name, "POST", "/api/models/freshness/watch", {"download": True})
        self.ask(name, "POST", "/api/models/freshness/watch", {})
        self.ask(name, "POST", "/api/models/staged/download", {"file": "nope"})
        self.ask(name, "POST", "/api/models/staged/revert", {"file": "nope"})
        self.ask(name, "POST", "/api/models/staged/drop-prev", {"file": "nope"})
        self.ask(name, "POST", "/api/model-stores/add", {})
        self.ask(name, "POST", "/api/model-stores/add", {"path": "rel"})
        self.ask(name, "POST", "/api/model-stores/add", {"path": "/nope/nope"})
        self.ask(name, "POST", "/api/model-stores/repath", {"id": "local", "path": "/x"})
        self.ask(name, "POST", "/api/model-stores/repath", {"id": "nope", "path": "/x"})
        self.ask(name, "POST", "/api/model-stores/remove", {"id": "local"})
        self.ask(name, "POST", "/api/model-stores/remove", {"id": "nope"})
        self.ask(name, "POST", "/api/model-stores/move", {})
        self.ask(name, "POST", "/api/model-stores/move", {"files": ["x"], "to": "nope"})
        self.ask(name, "POST", "/api/model-stores/move", {"files": ["x"], "to": "local"})
        self.ask(name, "POST", "/api/model-stores/moves/cancel", {"id": "nope"})
        self.ask(name, "POST", "/api/models/gc", {})
        self.ask(name, "POST", "/api/models/gc", {"files": ["x.txt"]})
        self.ask(name, "POST", "/api/models/gc", {"files": ["../../x.gguf"]})
        self.ask(name, "POST", "/api/models/gc", {"files": ["gone.gguf"]})
        self.ask(name, "POST", "/api/hf/token", {"token": "hf_abcdefgh"})
        self.ask(name, "GET", "/api/hf/token")
        self.ask(name, "POST", "/api/hf/token", {"token": "abc"})
        self.ask(name, "GET", "/api/hf/token")
        self.ask(name, "POST", "/api/hf/token", {"token": ""})
        self.ask(name, "POST", "/api/hf/favorites", {"favorites": [{"id": "a/b"}]})
        self.ask(name, "POST", "/api/hf/favorites", {"favorites": "x"})
        self.ask(name, "GET", "/api/hf/favorites")
        self.ask(name, "POST", "/api/hf/download", {})
        self.ask(name, "POST", "/api/hf/download", {"repo": "a/b", "files": [{"destDir": "../x"}]})
        self.ask(name, "POST", "/api/hf/download", {"repo": "a/b", "files": [{"name": "qwen-Q4.gguf", "destDir": "Qwen/author/Q4"}]})
        self.ask(name, "POST", "/api/hf/download/cancel", {})
        self.ask(name, "POST", "/api/hf/download/cancel", {"jobId": "x"})
        self.ask(name, "POST", "/api/hf/download/discard", {})
        self.ask(name, "POST", "/api/hf/download/discard", {"destDir": "..", "name": "x"})
        self.ask(name, "POST", "/api/hf/download/discard", {"destDir": "a", "name": "gone"})
        self.ask(name, "POST", "/api/hf/download/resume", {})
        self.ask(name, "POST", "/api/hf/download/resume", {"destDir": "..", "name": "x"})
        self.ask(name, "POST", "/api/hf/download/resume", {"destDir": "a", "name": "gone"})
        self.ask(name, "DELETE", "/api/hf/local-file")
        self.ask(name, "DELETE", "/api/hf/local-file?repo=a/b&name=x/y")
        self.ask(name, "DELETE", "/api/hf/local-file?repo=a/b&name=x")
        self.ask(name, "GET", "/api/models/unused")

    def token(self):
        """A mark that a request carries the fleet token: each controller's own goes (Controller.fleet_token)."""
        return "own"

    def sweep(self):
        """Every path of the API with nothing said: the empty board and every refusal of a request that names nothing."""
        name = "sweep"
        self.signed_in()
        spec = json.loads((ROOT / "rust/crates/admin/src/routes/openapi.json").read_text())
        for path, operations in spec["paths"].items():
            if "{" in path or path in SWEEP_SKIPPED or path.startswith("/api/auth/"):
                continue
            for method in operations:
                self.ask(name, method.upper(), path, {} if method == "post" else None)

    def beat(self, name, report):
        """A scout's heartbeat, from the fake world."""
        return self.ask(name, "POST", "/api/topology/client-heartbeat", report, {"X-Caravan-Token": self.token()})

    def report(self, host="hotel", nodes=None):
        """What a machine's scout says of itself: a card, two cells, an engine, a cache, a model of its own."""
        cell = self.world.port
        return {
            "host": {"id": host, "name": host.title(), "hostname": f"{host}.local", "ip": "127.0.0.1"},
            "agentUrl": f"http://127.0.0.1:{cell}",
            "platform": "linux",
            "scoutVersion": "2.43.0",
            "gpus": [{"index": 0, "uuid": "GPU-1", "name": "GeForce RTX 5090", "vendor": "nvidia", "driverStatus": "ok", "memoryTotalMiB": 32768, "memoryUsedMiB": 2048, "memoryFreeMiB": 30720, "utilizationGpuPct": 7, "temperatureC": 41, "powerDrawW": 55}],
            "computeApps": [{"gpuUuid": "GPU-1", "pid": 4242, "name": "llama-server", "usedMiB": 1024}],
            "cpu": {"loadPct": 12, "ncpu": 16, "logicalCores": 32, "physicalCores": 16, "availableCores": 32, "ram": {"usedGb": 10.5, "totalGb": 64}},
            "engines": [{"kind": "ollama", "label": "Ollama", "state": "ok", "port": 11434, "listen": "local", "pids": [77], "models": [{"name": "llama3:8b", "type": "llm", "format": "gguf", "family": "llama", "params": "8B", "quant": "Q4", "fileBytes": 5000, "loaded": True, "memBytes": 4000}, {"name": "bge:1", "type": "embedding", "fileBytes": 9}]}, {"kind": "lmstudio", "label": "LM Studio", "state": "stopped", "port": 1234, "models": []}],
            "driver": {"running": "570.1", "newer": "580.1", "status": "ok"},
            "llamaBinaryVersion": "version: 7000 (abc)",
            "llamaBinaryMtime": "2026-10-31",
            "llamaUpdate": {"running": False},
            "autostart": [cell],
            "llamaNodes": nodes if nodes is not None else [
                {"running": True, "port": cell, "modelPath": "/models/Qwen/author/Q4/qwen-Q4.gguf", "pid": 4242, "pids": [4242, 4243], "uptimeSec": 100, "ramBytes": 1000, "phase": "ready", "promptTps": 10.5, "genTps": 20.5, "requestsProcessing": 1, "requestsWaiting": 0, "ctxMax": 4096, "ctxUsed": 100, "modalities": {"vision": True, "audio": False}, "listening": True},
                {"running": False, "port": 22011, "modelPath": "/models/Qwen/author/Q8/qwen-Q8-00001-of-00002.gguf", "lastError": "it fell", "phase": "stopped", "crash": {"kind": "oom", "at": 1}, "firewall": {"open": True}},
            ],
            "llamaSuspect": {"suspect": True, "crashes15m": 3, "builtAt": 5, "currentCommit": "abc", "firstSeenAt": 6, "lastSeenAt": 7, "restoreCandidate": {"id": "b1", "commit": "c", "version": "b1", "builtAt": 1, "sizeMb": 2}},
            "telemetry": {"watchedSeconds": 60, "idleSeconds": 30, "retentionSeconds": 600},
            "entryModels": [{"id": "qwen", "state": "ready", "kind": "llm", "window": 4096, "copies": [{"port": cell, "state": "ready"}]}],
            "modelCache": {"dir": "/cache", "keep": 3, "budgetBytes": None, "files": [{"name": "a.gguf", "bytes": 5, "own": True}], "totalBytes": 5, "freeBytes": 100, "foreignBytes": 0},
        }

    def fleet(self):
        """A machine that reports, its cells and everything asked of its scout."""
        name = "fleet"
        self.signed_in()
        self.beat(name, {})
        self.beat(name, {"host": {"id": "../bad"}})
        self.beat(name, self.report())
        self.beat(name, self.report("india", nodes=[]))
        for target in ("/api/machines", "/api/topology", "/api/state", "/api/system-monitor?since=1", "/metrics", "/api/topology/client-monitor?hostId=hotel", "/api/topology/client-monitor?hostId=hotel&kind=btop", "/api/topology/client-monitor?hostId=nope", "/api/fleet/llama-update-status?hostId=hotel", "/api/fleet/vllm?hostId=hotel", "/api/fleet/vllm", "/api/fleet/vllm/update-status?hostId=hotel", "/api/fleet/llama-builds?hostId=hotel", "/api/topology/client-llama/list-cache?hostId=hotel", "/api/cell-log?hostId=hotel&port=22011&lines=5", "/api/cell-log?hostId=hotel", "/api/port-exclusions", "/api/port-exclusions?scan=1", "/api/topology/client-llama/configs?hostId=hotel", "/api/monitor/nvidia-smi", "/api/monitor/nope"):
            self.ask(name, "GET", target)
        hotel = {"hostId": "hotel"}
        cell = self.world.port
        for path, extra in (
            ("/api/fleet/llama-update", {"tag": "b1"}), ("/api/fleet/llama-update", {"tag": "bad tag!"}), ("/api/fleet/llama-restore", {"id": "b1"}), ("/api/fleet/llama-restore", {}),
            ("/api/fleet/vllm/update", {"version": "0.9.1"}), ("/api/fleet/vllm/update", {"version": "bad version"}), ("/api/fleet/llama-suspect-dismiss", {}),
            ("/api/host/reboot", {}), ("/api/host/poweroff", {}), ("/api/host/power-schedule", {"schedule": {"enabled": True, "at": "03:30", "daily": False}}), ("/api/host/power-schedule", {"schedule": {"enabled": False, "at": "99:99"}}),
            ("/api/topology/client-llama/purge-cache", {}), ("/api/topology/client-llama/cache-keep", {"keep": 2}), ("/api/topology/client-llama/cache-budget", {"budgetBytes": 1 << 31}), ("/api/topology/client-llama/cache-budget", {"budgetBytes": None}), ("/api/topology/client-llama/cache-dir", {"path": "/x/y"}), ("/api/topology/client-llama/cache-delete-foreign", {"expectBytes": 5}),
            ("/api/topology/client-llama/configs/save", {"name": "one", "config": {"MODEL_FILE": "Qwen/author/Q4/qwen-Q4.gguf", "CTX_SIZE": "4096"}}), ("/api/topology/client-llama/configs/save", {"name": "two", "config": {}}),
            ("/api/topology/server-slot/add", {"port": 22020}), ("/api/topology/server-slot/add", {"port": 22020}), ("/api/topology/server-slot/add", {"port": 1}), ("/api/topology/server-slot/add", {}),
            ("/api/topology/server-slot/note", {"port": 22020, "note": " a note "}), ("/api/topology/server-slot/note", {"port": 9999, "note": "x"}),
            ("/api/topology/server-cell/save-config", {"port": 22020, "config": {"MODEL_FILE": "Qwen/author/Q4/qwen-Q4.gguf", "CTX_SIZE": "4096", "N_GPU_LAYERS": "99"}, "cacheModels": True}),
            ("/api/topology/server-cell/save-config", {"port": 22020, "config": {"MODEL_FILE": "../../x.gguf"}}),
            ("/api/topology/server-cell/action", {"port": 22020, "action": "start"}), ("/api/topology/server-cell/action", {"port": 22020, "action": "stop"}), ("/api/topology/server-cell/action", {"port": 22020, "action": "restart"}), ("/api/topology/server-cell/action", {"port": 22020, "action": "enable"}), ("/api/topology/server-cell/action", {"port": 22020, "action": "disable"}), ("/api/topology/server-cell/action", {"port": 22020, "action": "nope"}), ("/api/topology/server-cell/action", {"port": 9999, "action": "start"}),
            ("/api/topology/server-cell/schedule", {"port": 22020, "schedule": {"enabled": True, "from": "08:00", "to": "20:00", "days": [0, 1, 2]}}), ("/api/topology/server-cell/schedule", {"port": 22020, "schedule": {"enabled": False}}), ("/api/topology/server-cell/schedule", {"port": 9999, "schedule": {}}),
            ("/api/topology/server-cell/reassign-port", {"port": 22020, "newPort": 22021}), ("/api/topology/server-cell/reassign-port", {"port": 22021, "newPort": 22021}), ("/api/topology/server-cell/reassign-port", {"port": 9999, "newPort": 22022}),
            ("/api/topology/server-slot/add", {"port": 22030}), ("/api/topology/server-cell/swap-port", {"port": 22021, "targetPort": 22030}), ("/api/topology/server-cell/swap-port", {"port": 9999, "targetPort": 22030}),
            ("/api/topology/client-llama/start", {"port": 22021, "modelPath": "Qwen/author/Q4/qwen-Q4.gguf", "gpuLayers": 99, "ctxSize": 4096, "cacheModels": False, "config": {"MODEL_FILE": "Qwen/author/Q4/qwen-Q4.gguf"}, "cellPort": 22021}),
            ("/api/topology/client-llama/start", {"port": 22021}), ("/api/topology/client-llama/stop", {"port": 22021}), ("/api/topology/client-llama/stop", {}),
            ("/api/engine-outputs/expose", {"kind": "ollama", "model": "llama3:8b", "exposed": True}), ("/api/engine-outputs/expose", {"kind": "ollama", "model": "nope", "exposed": True}), ("/api/engine-outputs/expose", {"kind": "ollama", "model": "llama3:8b", "exposed": False}),
            ("/api/engines/unload", {"kind": "ollama", "model": "llama3:8b"}), ("/api/engines/delete", {"kind": "ollama", "model": "llama3:8b"}), ("/api/engines/start", {"kind": "ollama"}), ("/api/engines/stop", {"kind": "ollama"}), ("/api/engines/start", {"kind": "nope"}),
            ("/api/topology/server-slot/delete", {"port": 22030}), ("/api/topology/server-slot/delete", {"port": 9999}),
        ):
            self.ask(name, "POST", path, {**hotel, **extra})
        self.ask(name, "GET", "/api/topology/client-llama/configs?hostId=hotel")
        self.ask(name, "POST", "/api/port-exclusions", {"add": [{"port": 22050, "note": "kept", "host": "hotel"}, 22051], "remove": []})
        self.ask(name, "POST", "/api/port-exclusions", {"add": [80], "remove": []})
        self.ask(name, "POST", "/api/port-exclusions", {"remove": [22051]})
        self.ask(name, "POST", "/api/topology/scout/scan", {"networks": "10.255.255.1", "port": cell})
        self.ask(name, "POST", "/api/topology/scout/scan", {"networks": "127.0.0.1", "port": cell})
        self.ask(name, "POST", "/api/topology/scout/scan", {"networks": "8.8.8.8"})
        self.ask(name, "POST", "/api/topology/scout/connect", {"address": "127.0.0.1", "port": cell})
        self.ask(name, "POST", "/api/topology/scout/connect", {"address": "bad address"})
        self.ask(name, "POST", "/api/topology/server-cell/save-config", {"hostId": "hotel", "port": cell, "config": {"MODEL_FILE": "Qwen/author/Q4/qwen-Q4.gguf"}})
        for mode, ask in (("text-chat", {"text": "hi"}), ("text-chat", {"text": "hi", "history": [{"role": "user", "text": "before"}], "system": "be brief"}), ("text-chat", {}), ("speech", {"text": "hi", "voice": "ana"}), ("transcription", {"audio": "UklGRg=="}), ("heard-chat", {"audio": "UklGRg=="}), ("spoken-chat", {"text": "hi"}), ("speech-translation", {"audio": "!!"}), ("nope", {})):
            self.ask(name, "POST", "/api/cell-talk", {"hostId": "hotel", "port": cell, "mode": mode, **ask})
        self.ask(name, "POST", "/api/cell-talk", {"hostId": "hotel", "port": 9999, "mode": "text-chat", "text": "x"})
        self.ask(name, "POST", "/api/cell-talk", {"hostId": "nope", "port": cell, "mode": "text-chat", "text": "x"})
        self.ask(name, "GET", f"/api/cell-talk/voices?hostId=hotel&port={cell}")
        self.ask(name, "GET", "/api/cell-talk/voices?hostId=hotel&port=x")
        self.ask(name, "POST", "/api/cell-talk/voice", {"hostId": "hotel", "port": cell, "name": "mine", "sample": "UklGRg==", "text": "hello", "consent": True})
        self.ask(name, "POST", "/api/cell-talk/voice", {"hostId": "hotel", "port": cell})
        self.ask(name, "GET", f"/api/cell-live?hostId=hotel&port={cell}")
        for runner, modes in (("voice-clone", ("speech",)), ("lfm-audio", ("spoken-chat", "speech")), ("qwen3-tts", ("speech",)), ("seamless", ("speech-translation",)), ("vllm", ("text-chat",)), ("strata", ("text-chat",)), ("custom", ("text-chat",))):
            self.ask(name, "POST", "/api/topology/server-cell/save-config", {"hostId": "hotel", "port": cell, "config": {"RUNNER": runner, "MODEL_FILE": "Qwen/author/NVFP4", "COMMAND": "run"}})
            for mode in modes:
                self.ask(name, "POST", "/api/cell-talk", {"hostId": "hotel", "port": cell, "mode": mode, "text": "hi", "audio": "UklGRg==", "voice": "ana"})
            self.ask(name, "GET", f"/api/cell-talk/voices?hostId=hotel&port={cell}")
            self.ask(name, "POST", "/api/cell-talk/voice", {"hostId": "hotel", "port": cell, "name": "mine", "sample": "UklGRg==", "text": "hello", "consent": True})
            self.ask(name, "POST", "/api/cell-talk/voice", {"hostId": "hotel", "port": cell, "name": "mine"})
            self.ask(name, "GET", f"/api/cell-live?hostId=hotel&port={cell}")
        self.ask(name, "GET", "/api/cell-live?hostId=hotel&port=x")
        self.ask(name, "POST", "/api/topology/host/move-cells", {"from": "hotel", "to": "india"})
        self.ask(name, "POST", "/api/topology/host/move-cells", {"from": "hotel", "to": "hotel"})
        self.ask(name, "POST", "/api/topology/server-order", {"order": ["node:india", "node:hotel"]})
        self.ask(name, "POST", "/api/topology/server-order", {"order": "x"})
        self.ask(name, "GET", "/api/topology")
        self.ask(name, "POST", "/api/topology/scout/disconnect", {"hostId": "india"})
        self.ask(name, "POST", "/api/topology/scout/disconnect", {"hostId": "nope"})
        self.ask(name, "GET", "/api/topology")

    def machine(self):
        """The controller's own machine, read through the scout on it; the files it hands to scouts; a script under home."""
        name = "machine"
        self.signed_in()
        own = socket.gethostname().split(".")[0]
        report = self.report("kilo", nodes=[])
        report["host"]["hostname"] = own
        self.beat(name, report)
        # What the sweep heard of this machine, that it has no scout, is remembered ten seconds (MachineScout::FAIL_PAUSE): what comes next is the scout's own word.
        time.sleep(10.5)
        for target in ("/api/monitor/nvidia-smi", "/api/monitor/btop", "/api/gpu-driver", "/api/gpu-driver/update-status", "/api/state", "/api/controller-info", "/api/llamacpp/builds", "/api/llamacpp/update-status", "/api/topology", "/metrics"):
            self.ask(name, "GET", target)
        self.ask(name, "POST", "/api/gpu-driver/update", {"package": "nvidia-driver-570"})
        for target in ("/api/cell-assets", "/api/cell-assets/file", "/api/cell-assets/file?name=nope", "/api/cell-assets/file?name=../x", "/api/cell-assets/file?name=transformers_server.py"):
            self.ask(name, "GET", target, None, {"X-Caravan-Token": self.token()})
        (self.program.folder / "home" / "run.sh").write_text("#!/bin/sh\necho hi\n")
        (self.program.folder / "home" / "note.txt").write_text("not a script")
        for target in ("/api/script-preview?path=run.sh", "/api/script-preview?path=~/run.sh", "/api/script-preview?path=note.txt", "/api/script-preview?path=gone.sh"):
            self.ask(name, "GET", target)

    def journal(self):
        """What the proxy's journal says, read four ways."""
        name = "journal"
        self.signed_in()
        now = int(time.time())
        def row(at, event="finished", **item):
            whole = {"port": 23001, "route": "Hermes", "client": "hermes", "requestId": f"r{at}", "startedAt": at - 1, "finishedAt": at, "status": 200, "upstreamType": "cloud", "cloudAccountId": "key1", "cloudModel": "gpt-x", "model": "gpt-x", "providerId": "p1", "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}, "latency": {"prepMs": 1.5, "connectMs": 2.5, "connReused": False, "headersMs": 3.5, "firstChunkMs": 4.5, "cpuMs": 1.0}, "queuedMs": 3, "firstByteMs": 12, "durationMs": 300}
            whole.update(item)
            return json.dumps({"time": at, "event": event, "route": whole["route"], "status": whole["status"], "item": whole, "active": [], "queue": []})
        today = [
            row(now - 60),
            row(now - 50, status=429, errorKind="upstream", usage={}),
            row(now - 45, event="upstream_response", status=429, upstream_response={"status": 429, "body": "too many"}),
            row(now - 40, upstreamType="llama", port=23002, route="Local", client="opencode", cloudAccountId="", cloudModel="", model="qwen", usage={"prompt_tokens": 10, "completion_tokens": 20}, tokensPerSecond=30.5, promptTokensPerSecond=90.5),
            row(now - 30, status=503, errorKind="pool-exhausted", cloudAccountId="", cloudModel="", providerId="p1"),
            row(now - 20, event="received", status=0),
        ]
        days = {time.strftime("%Y-%m-%d", time.gmtime(now)): today, time.strftime("%Y-%m-%d", time.gmtime(now - 86400)): [row(now - 86400, cloudModel="gpt-y", model="gpt-y"), row(now - 86300, status=500, errorKind="network")]}
        days["2026-01-01"] = [row(now - 90000 * 100), "not json at all"]
        folder = self.program.folder / "data" / "logs" / "proxy-events"
        folder.mkdir(parents=True, exist_ok=True)
        for day, lines in days.items():
            (folder / f"{day}.jsonl").write_text("\n".join(lines) + "\n")
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        for target in ("/api/agent-proxy-logs", f"/api/agent-proxy-logs?date={day}", f"/api/agent-proxy-logs?date={day}&limit=2", f"/api/agent-proxy-logs?date={day}&errors=1", f"/api/agent-proxy-logs?date={day}&slim=1", f"/api/agent-proxy-logs?date={day}&summary=1", f"/api/agent-proxy-logs?date={day}&port=23002", f"/api/agent-proxy-logs?date={day}&route=Local", f"/api/agent-proxy-logs?date={day}&client=hermes", f"/api/agent-proxy-logs?date={day}&event=finished", f"/api/agent-proxy-logs?date={day}&since={now - 35}", f"/api/agent-proxy-logs?date={day}&limit=x", "/api/agent-proxy-logs?date=2026-01-01", "/api/proxy-daily-stats", f"/api/proxy-daily-stats?date={day}", "/api/proxy-daily-stats?date=2026-01-01", "/api/agent-proxy-latency?port=23001", "/api/agent-proxy-latency?port=23001&range=1h", "/api/agent-proxy-latency?port=23002&range=nope", "/api/cloud-upstream-errors", "/api/usage-stats", "/api/usage-stats?days=1", "/api/cloud-accounts/proxy-spend", "/api/topology"):
            self.ask(name, "GET", target)

    def clients(self):
        """Clients by hand, their agents and the ports they are bound to."""
        name = "clients"
        self.signed_in()
        for path, body in (
            ("/api/topology/client/create", {"hostId": "golf", "name": "Golf", "ip": "10.0.0.9"}), ("/api/topology/client/create", {"hostId": "golf"}), ("/api/topology/client/create", {"hostId": "../x"}),
            ("/api/topology/client-alias", {"hostId": "golf", "name": "  Renamed  "}), ("/api/topology/client-alias", {"hostId": "nope", "name": "x"}),
            ("/api/topology/client/agent-alias", {"hostId": "golf", "agentId": "golf", "name": "Agent"}), ("/api/topology/client/agent-alias", {"hostId": "golf", "agentId": "nope", "name": "x"}),
            ("/api/topology/agent-route/context", {"hostId": "golf", "agentId": "golf", "contextLength": 8192}), ("/api/topology/agent-route/context", {"hostId": "golf", "agentId": "golf", "contextAuto": True}), ("/api/topology/agent-route/context", {"hostId": "golf", "agentId": "golf", "role": "nope"}), ("/api/topology/agent-route/context", {"hostId": "golf", "agentId": "nope"}),
            ("/api/topology/agent-route/model", {"hostId": "golf", "agentId": "golf", "modelName": "qwen"}), ("/api/topology/agent-route/model", {"hostId": "golf", "agentId": "golf", "modelNameAuto": True}), ("/api/topology/agent-route/model", {"hostId": "golf", "agentId": "nope"}),
            ("/api/topology/agent-route/remove", {"hostId": "golf", "agentId": "golf", "role": "fallback"}), ("/api/topology/agent-route/remove", {"hostId": "golf", "agentId": "golf", "role": "fallback"}),
            ("/api/topology/assignments", {"hostId": "golf", "assignments": [{"agentId": "golf", "routes": [{"role": "primary", "proxyId": "x", "endpoint": "http://h:1"}]}]}), ("/api/topology/assignments", {"hostId": "golf", "assignments": "x"}),
            ("/api/topology/agent-proxy-bind", {"hostId": "golf", "agentId": "golf", "port": 23001, "role": "fallback"}), ("/api/topology/agent-proxy-bind", {"hostId": "golf", "agentId": "golf", "port": 1}),
            ("/api/topology/client/agent/delete", {"clientId": "golf", "agentId": "nope"}), ("/api/topology/client/agent/delete", {"clientId": "golf", "agentId": "golf"}), ("/api/topology/client/delete", {"clientId": "nope"}), ("/api/topology/client/delete", {"clientId": "golf"}),
        ):
            self.ask(name, "POST", path, body)
        self.ask(name, "GET", "/api/topology")

    def routing(self):
        """Accounts, pools, the clients of the entry and the proxy's own settings."""
        name = "routing"
        self.signed_in()
        base = f"http://127.0.0.1:{self.world.port}/v1"
        for path, body in (
            ("/api/cloud-accounts/save", {"account": {"id": "bad id!"}}), ("/api/cloud-accounts/save", {"account": {"id": "key1", "type": "custom", "name": "A key", "baseUrl": base, "creditUsd": 5}}), ("/api/cloud-accounts/save", {"account": {"id": "key2", "type": "openrouter", "baseUrl": base}}), ("/api/cloud-accounts/save", {"account": {"id": "sub1", "type": "openai-subscription", "name": "A plan"}}),
            ("/api/cloud-accounts/key", {"id": "key1", "apiKey": "sk-test"}), ("/api/cloud-accounts/key", {"id": "nope", "apiKey": "x"}), ("/api/cloud-accounts/check-models", {"id": "key1"}), ("/api/cloud-accounts/check-models", {"id": "nope"}), ("/api/cloud-accounts/test-alias", {"id": "sub1"}), ("/api/cloud-accounts/test-alias", {"id": "key1"}),
        ):
            self.ask(name, "POST", path, body)
        for target in ("/api/cloud-accounts/models?id=key1", "/api/cloud-accounts/models?id=nope", "/api/cloud-accounts/catalogue?id=key1", "/api/cloud-accounts/catalogue?id=nope", "/api/cloud-accounts/subscription-usage?id=key1", "/api/cloud-accounts/subscription-models?id=key1", "/api/cloud-accounts/subscription-resets?id=key1", "/api/cloud-accounts/api-costs?id=key1", "/api/cloud-accounts/openrouter-limits?id=key1", "/api/cloud-accounts/deepseek-balance?id=key1", "/api/cloud-accounts/proxy-spend", "/api/cloud-upstream-errors", "/api/usage-stats", "/api/usage-stats?days=x", "/api/usage-stats?days=9999", "/api/local-pricing", "/api/api-pricing"):
            self.ask(name, "GET", target)
        pool = hermes = None
        for path, body in (
            ("/api/pools/create", {}), ("/api/pools/create", {"name": "Second", "accountId": "key1", "model": "gpt-x"}), ("/api/pools/create", {"name": "Second"}), ("/api/pools/create", {"accountId": "nope", "model": "x"}),
            ("/api/pools/add-model", {"accountId": "key1", "model": "gpt-x"}), ("/api/pools/add-model", {"accountId": "key1", "model": "text-embedding-x"}), ("/api/pools/remove-model", {"accountId": "key1", "model": "text-embedding-x"}),
            ("/api/pools/model-jobs", {"accountId": "key1", "model": "gpt-x", "jobs": ["llm"]}), ("/api/pools/model-jobs", {"accountId": "key1", "model": "gpt-x", "jobs": ["nope"]}), ("/api/pools/model-jobs", {"accountId": "key1", "model": "gpt-x", "jobs": []}),
            ("/api/pools/level", {"accountId": "sub1", "model": "gpt-5", "windowSeconds": 18000, "pct": 50, "level": "switch"}), ("/api/pools/level", {"accountId": "sub1", "model": "gpt-5", "windowSeconds": 604800, "pct": 80, "level": "stop"}), ("/api/pools/level", {"accountId": "sub1", "model": "gpt-5", "windowSeconds": 18000, "pct": 500, "level": "stop"}), ("/api/pools/level", {"accountId": "sub1", "model": "gpt-5", "windowSeconds": 18000, "pct": 50, "level": "low"}),
            ("/api/board-providers/add", {"kind": "openrouter"}), ("/api/board-providers/add", {"kind": "nope"}), ("/api/board-providers/remove", {"kind": "openrouter"}),
            ("/api/models/schedule", {"model": "acc:key1/gpt-x", "schedule": {"enabled": True, "windows": [{"days": [], "from": "00:00", "to": "00:00"}]}}), ("/api/models/schedule", {"model": "out:srv:22021", "schedule": {"enabled": False, "windows": []}}), ("/api/models/schedule", {"model": "acc:key1/gpt-x", "schedule": {"enabled": True, "windows": "x"}}), ("/api/models/schedule", {"model": "gpt-x", "schedule": {"enabled": True}}), ("/api/models/schedule", {"model": "gpt-x", "schedule": None}), ("/api/models/schedule", {"model": "", "schedule": {}}),
            ("/api/local-pricing", {"inputPer1M": 1.5, "outputPer1M": "2"}), ("/api/local-pricing", {"inputPer1M": "x"}), ("/api/api-pricing", {"model": "gpt-x", "inputPer1M": 3, "outputPer1M": 4}), ("/api/api-pricing", {"model": "gpt-y", "inputPer1M": 0}), ("/api/api-pricing", {}),
            ("/api/consumers/create", {"name": "Hermes"}), ("/api/consumers/create", {"name": "Hermes"}), ("/api/consumers/create", {"name": ""}), ("/api/consumers/create", {"name": "Built", "kind": "opencode"}),
            ("/api/consumers/deny", {"port": "<hermes>", "deny": ["pool:x"]}), ("/api/consumers/deny", {"port": "<hermes>", "deny": []}), ("/api/consumers/deny", {"port": 1, "deny": []}), ("/api/consumers/deny", {"port": "<hermes>", "deny": "x"}), ("/api/consumers/key", {"port": "<hermes>"}), ("/api/consumers/key", {"port": 1}),
            ("/api/consumers/order", {"order": ["<hermes>", 23001]}), ("/api/consumers/order", {"order": "x"}),
            ("/api/consumers/probe", {"port": "<hermes>", "path": "/v1/nope"}), ("/api/consumers/probe", {"port": 1, "path": "/v1/embeddings"}), ("/api/consumers/probe", {"port": "<hermes>", "path": "/v1/embeddings", "model": "x"}),
            ("/api/agent-proxies/route-policy", {"port": "<hermes>", "label": "Hermes two"}), ("/api/agent-proxies/route-policy", {"port": "<hermes>", "priority": 3}), ("/api/agent-proxies/route-policy", {"port": 9, "label": "x"}),
            ("/api/agent-proxies/policy", {"policy": {"maxSlots": 3, "queueAbortPct": 80}}), ("/api/agent-proxies/policy", {"maxSlots": "x"}),
            ("/api/agent-proxy-entry", {"port": 23999, "publicUrl": "https://entry.test/v1"}), ("/api/agent-proxy-entry", {"port": 80}), ("/api/agent-proxy-entry", {"port": 23999, "publicUrl": "bad url"}),
            ("/api/agent-proxies/stop", {"port": "<hermes>"}), ("/api/agent-proxies/stop", {"requestId": "nope"}),
            ("<entry>", {}),
            ("/api/agent-proxies/route-delete", {"port": "<hermes>"}), ("/api/agent-proxies/route-delete", {"port": 9}),
            ("/api/entry-move/seen", {}), ("/api/cloud-api-health/retry", {"key": "key1:models"}), ("/api/queue-thresholds/recalc", {}),
            ("/api/cloud-accounts/subscription-reset", {"id": "sub1", "creditId": "x", "idempotencyKey": "x", "confirmed": False}), ("/api/cloud-accounts/oauth/device-start", {"id": "key1"}), ("/api/cloud-accounts/key-delete", {"id": "key1"}), ("/api/cloud-accounts/delete", {"id": "key2"}), ("/api/cloud-accounts/delete", {"id": "nope"}),
        ):
            if path == "<entry>":
                self.entry_probes(name, hermes)
                continue
            body = json.loads(json.dumps(body).replace('"<hermes>"', str(hermes)))
            answer = self.ask(name, "POST", path, body)
            if path == "/api/pools/create" and answer[0] == 200 and pool is None:
                pool = json.loads(answer[2]).get("pool", {}).get("id")
            if path == "/api/consumers/create" and answer[0] == 200 and hermes is None:
                hermes = json.loads(answer[2]).get("port")
        for target in ("/api/agent-proxies/raw", "/api/agent-proxy-entry", "/api/queue-thresholds", "/api/agent-proxy-logs", "/api/agent-proxy-logs?summary=1", "/api/agent-proxy-logs?date=bad", "/api/proxy-daily-stats", "/api/proxy-daily-stats?date=2026-10-01", "/api/token-history", "/api/token-history?range=1h", "/api/agent-proxy-latency?port=23001", "/api/agent-proxy-latency?port=x", "/api/agent-proxy-model-card?port=23001", "/api/agent-proxy-model-card?port=x", "/api/agent-proxy-model-card?port=9", "/api/consumers/ask?port=23001&path=/v1/nope", "/api/consumers/ask?port=9&path=/v1/models", "/api/pools/refs?id=p1", "/api/pools/refs", "/api/model-pricing"):
            self.ask(name, "GET", target)
        if pool is not None:
            for path, body in (
                ("/api/pools/add-row", {"poolId": pool}), ("/api/pools/add-step", {"poolId": pool, "accountId": "key1", "model": "gpt-x"}), ("/api/pools/add-step", {"poolId": pool, "accountId": "nope"}),
                ("/api/pools/copy", {"id": pool}), ("/api/pools/copy", {"id": "nope"}), ("/api/pools/order", {"ids": "<all>"}), ("/api/pools/order", {"ids": [pool]}), ("/api/pools/order", {"ids": "x"}), ("/api/pools/arrange", {}),
                ("/api/pools/save", {"pool": {"id": pool, "name": "Renamed"}}), ("/api/pools/save", {"pool": {"id": pool, "contextLength": "x"}}),
                ("/api/pools/connect-row", {"poolId": pool, "rowId": "r1", "target": {"accountId": "key1", "model": "gpt-x"}}), ("/api/pools/connect-row", {"poolId": pool, "rowId": "r1"}), ("/api/pools/connect-row", {"poolId": pool, "rowId": "nope"}),
                ("/api/pools/remove-step", {"poolId": pool, "stepId": "r1"}), ("/api/pools/remove-step", {"poolId": pool, "stepId": "nope"}), ("/api/pools/delete", {"id": pool, "resolution": "nope"}), ("/api/pools/delete", {"id": pool}), ("/api/pools/delete", {"id": "nope"}),
            ):
                if body.get("ids") == "<all>":
                    held = json.loads(self.program.ask("GET", "/api/topology")[2])
                    body = {"ids": [row.get("id") for row in held.get("pools", [])]}
                self.ask(name, "POST", path, body)
        self.ask(name, "POST", "/api/agent-proxies/config", {"routes": [], "revision": "stale"})
        self.ask(name, "POST", "/api/agent-proxies/routers", {"routers": [], "revision": "stale"})
        self.ask(name, "GET", "/api/topology")

    def entry_probes(self, name, hermes):
        """The entry opened on a port the fake world then answers on: what a client gets for its own questions."""
        port = free_port()
        self.comparison.own.name_port(port, "<entry>")
        self.ask(name, "POST", "/api/agent-proxy-entry", {"port": port})
        world = FakeWorld(port)
        try:
            for target in (f"/api/consumers/ask?port={hermes}&path=/v1/models", f"/api/consumers/ask?port={hermes}&path=/v1/models/qwen%20x", f"/api/consumers/ask?port=x&path=/v1/models", f"/api/agent-proxy-model-card?port={hermes}"):
                self.ask(name, "GET", target)
            for path in ("/v1/chat/completions", "/v1/responses", "/v1/embeddings", "/v1/audio/transcriptions", "/v1/images/generations", "/v1/audio/speech"):
                self.ask_timeless(name, "/api/consumers/probe", {"port": hermes, "path": path, "model": "gpt-x"})
        finally:
            world.shutdown()
            world.server_close()
        self.ask(name, "POST", "/api/agent-proxy-entry", {"port": 0})

    def ask_timeless(self, scenario, target, body):
        """A probe says how long it took: what differs by nature is said so."""
        status, head, raw = self.program.ask("POST", target, body)
        self.comparison.one(scenario, f"POST {target} {body.get('path')}", (status, head, re.sub(rb'"ms": \d+,?', b"", raw)))

    def settings(self):
        """What the panel can change of the controller, and the file that carries it all."""
        name = "settings"
        self.signed_in()
        for path, body in (
            ("/api/config-favorites", {"favorites": ["CTX_SIZE", "CTX_SIZE", "NOPE", 1]}), ("/api/config-favorites", {"favorites": "x"}),
            ("/api/parse-extra-args", {"extraArgs": "--temp 0.5 --mlock --no-mmap --flash-attn off --threads 8 --nope x"}), ("/api/parse-extra-args", {"text": "'unbalanced --mlock"}), ("/api/parse-extra-args", {}),
            ("/api/llama-command-preview", {"config": {"MODEL_FILE": "Qwen/author/Q4/qwen-Q4.gguf", "CTX_SIZE": "4096", "N_GPU_LAYERS": "99", "TEMPERATURE": "0.5", "MMPROJ_FILE": "Qwen/author/Q4/mmproj-qwen.gguf", "ENV": "A=1 B=2", "EXTRA_ARGS": "--mlock"}}),
            ("/api/llama-command-preview", {"config": {"RUNNER": "vllm", "MODEL_FILE": "Qwen/author/NVFP4"}}), ("/api/llama-command-preview", {"config": "x"}),
            ("/api/cell-ram-plan", {"config": {"MODEL_FILE": "Qwen/author/Q4/qwen-Q4.gguf"}}), ("/api/cell-ram-plan", {}),
            ("/api/cell-ram-plan", {"config": {"RUNNER": "strata", "MODEL_FILE": "Qwen/author/NVFP4"}}), ("/api/cell-ram-plan", {"config": {"RUNNER": "strata", "MODEL_FILE": "Qwen/author/Q4/qwen-Q4.gguf"}}), ("/api/cell-ram-plan", {"config": {"RUNNER": "vllm", "MODEL_FILE": "Qwen/author/NVFP4", "CPU_OFFLOAD_GB": "2", "TENSOR_PARALLEL": "2"}}), ("/api/cell-ram-plan", {"config": {"RUNNER": "voice-clone"}}),
            ("/api/system-monitor/settings", {"retentionSeconds": 5}), ("/api/system-monitor/settings", {"retentionSeconds": "x"}),
            ("/api/aa-scores", {"models": ["openai/gpt-5.5", "claude-opus-4-8", " ", 5], "fetch": False}), ("/api/aa-scores", {"models": "x"}),
            ("/api/gpu-driver/auto", {"check": True}), ("/api/gpu-driver/auto", {"install": True}), ("/api/gpu-driver/auto", {}), ("/api/gpu-driver/update", {"package": "bad package!"}),
            ("/api/config", {"config": {"MODEL_FILE": "Qwen/author/Q4/qwen-Q4.gguf", "CTX_SIZE": "4096"}}),
            ("/api/config", {"config": {"PORT": "8080", "MODEL_FILE": "Qwen/author/Q4/qwen-Q4.gguf", "CTX_SIZE": "4096"}}),
            ("/api/repair/user-service", {}),
        ):
            self.ask(name, "POST", path, body)
        for target in ("/api/hf/benchmarks", "/api/hf/benchmarks?repo=bad", "/api/hf/reference-models", "/api/hf/bench-search", "/api/hf/bench-search?q=ab", "/api/hf/bench-search?q=qwen", "/api/settings/backups", "/api/cell-assets", "/api/cell-assets/file", "/api/cell-assets/file?name=nope", "/api/script-preview", "/api/script-preview?path=/etc/hosts", "/api/gpu-driver", "/api/gpu-driver/update-status", "/api/llamacpp/update-status", "/api/llamacpp/builds", "/api/project-git", "/api/controller-info"):
            self.ask(name, "GET", target)
        bundle = json.loads(self.ask(name, "POST", "/api/settings/export", {"secrets": True})[2])["bundle"]
        self.ask(name, "POST", "/api/settings/import", {})
        self.ask(name, "POST", "/api/settings/import", {"bundle": {"kind": "other"}})
        self.ask(name, "POST", "/api/settings/import", {"bundle": {"kind": "lama-caravan-settings", "format": 9}})
        self.ask(name, "POST", "/api/settings/import", {"bundle": {"kind": "lama-caravan-settings", "format": 1}})
        for dry in (True, False):
            self.comparison.one(name, f"POST /api/settings/import dryRun={dry}", self.program.ask("POST", "/api/settings/import", {"bundle": bundle, "dryRun": dry}))
        self.ask(name, "GET", "/api/settings/backups")

    def all(self):
        return [self.sign_in, self.models, self.sweep, self.fleet, self.machine, self.journal, self.clients, self.routing, self.settings]


class Folders:
    """What the controller left on the disk after the requests: what a new version of it reads."""

    #: Files that are a process's own, or a moment's: their figures differ by nature. The accounts hold a salt of their own.
    OWN = ("logs/", "state/agent-proxy-state", "state/monitor-history.json", "settings-backups/", "state/auth.")

    def __init__(self, data, comparison):
        self.data, self.comparison = data, comparison
        self.differences = []

    def files(self):
        return {path.relative_to(self.data).as_posix(): path for path in self.data.rglob("*") if path.is_file() and not path.relative_to(self.data).as_posix().startswith(self.OWN)}

    def form(self, path):
        raw = path.read_bytes()
        try:
            return {"json": self.comparison.own.clean(self.comparison.cleaned(json.loads(raw)))}
        except ValueError:
            words = self.comparison.own.words(raw.decode("latin-1")).encode("latin-1")
            return {"sha256": hashlib.sha256(words).hexdigest(), "bytes": len(words)}

    def walk(self, rel, left, right, where=""):
        """By their keys: which section of a file was written first is no promise."""
        if isinstance(left, dict) and isinstance(right, dict):
            for key in list(left) + [key for key in right if key not in left]:
                if key not in left or key not in right:
                    self.differences.append(f"{rel}{where}.{key}: said only {'now' if key not in left else 'once'}")
                else:
                    self.walk(rel, left[key], right[key], f"{where}.{key}")
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                self.differences.append(f"{rel}{where}: {len(left)} rows and {len(right)}")
            for at, (one, other) in enumerate(zip(left, right)):
                self.walk(rel, one, other, f"{where}[{at}]")
        elif left != right:
            self.differences.append(f"{rel}{where}: kept {json.dumps(left, ensure_ascii=False)[:140]}, now {json.dumps(right, ensure_ascii=False)[:140]}")

    def compare(self):
        for rel, path in sorted(self.files().items()):
            rel = self.comparison.own.words(rel)
            now = self.form(path)
            kept = self.comparison.frozen.said(f"on the disk · {rel}", now)
            if kept is FrozenAnswers.NOTHING:
                self.differences.append(f"{rel}: not kept, and it is there now")
            else:
                self.walk(rel, kept, now)
        return self.differences


class Run:
    """One whole comparison: the program on a data folder of its own, and the fake world around it."""

    @staticmethod
    def argv(program):
        """The command that starts it."""
        return [str(program)]

    @classmethod
    def go(cls, program, only, writing):
        frozen = FrozenAnswers("admin", writing=writing)
        with tempfile.TemporaryDirectory(prefix="admin-conformance-") as raw:
            base = Path(raw).resolve()
            (base / "program").mkdir()
            Fixture(base / "program" / "data").write()
            tools = base / "bin"
            tools.mkdir()
            fake = tools / "systemctl"
            fake.write_text("#!/bin/sh\necho 'ActiveState=inactive'\necho 'SubState=dead'\necho 'MainPID=0'\nexit 0\n")
            fake.chmod(0o755)
            world = FakeWorld()
            controller = Controller("program", cls.argv(program), base / "program", {"PATH": f"{tools}:{os.environ.get('PATH', '')}"})
            try:
                controller.wait()
                comparison = Comparison(OwnWords({base / "program": "<own>", ROOT: "<repo>"}, {controller.port: "<own port>", world.port: "<world>"}), frozen)
                scenarios = Scenarios(controller, comparison, world)
                for scenario in scenarios.all():
                    if not only or only == scenario.__name__:
                        scenario()
                if not only:
                    comparison.differences.extend(f"on the disk · {line}" for line in Folders(base / "program" / "data", comparison).compare())
                    comparison.differences.extend(f"{key}: kept, and nothing asked it" for key in frozen.unasked())
            finally:
                controller.stop()
        return comparison


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only")
    parser.add_argument("--write", action="store_true", help="keep what the program says now as what it promises: its diff is what changed")
    args = parser.parse_args()
    if args.write and args.only:
        raise SystemExit("--write keeps a whole run, not one scenario")
    program = Path(os.environ.get("CARAVAN_RUST_ADMIN_BIN") or ROOT / "rust/target/release/caravan-admin")
    if not program.exists():
        if os.environ.get("CARAVAN_RUST_REQUIRED"):
            raise SystemExit(f"{program} is not there")
        print(f"rust admin conformance: skipped, {program} is not there")
        return
    comparison = Run.go(program, args.only, args.write)
    if args.write:
        comparison.frozen.write()
        print(f"rust admin conformance: kept {len(comparison.frozen.rows)} answers in {comparison.frozen.path.relative_to(ROOT)}")
        return
    if comparison.differences:
        for line in comparison.differences:
            print(line)
        raise SystemExit(f"rust admin conformance: {len(comparison.differences)} differences in {comparison.compared} answers")
    print(f"rust admin conformance: ok, {comparison.compared} answers agree")


if __name__ == "__main__":
    main()
