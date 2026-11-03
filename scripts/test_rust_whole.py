#!/usr/bin/env python3
"""The caravan in Rust whole, its three programs together: a controller and its proxy with no Python, and a scout paired from the board.

Each program is compared to its kept answers elsewhere (scripts/test_rust_admin_conformance.py, scripts/test_rust_scout_conformance.py, scripts/test_rust_conformance.py), each
with stand-ins for the other two: what those comparisons cannot see is a seam between two of them. Here a machine is paired as the board pairs it, a model comes from the
controller's library to the scout's cache byte for byte, a cell starts, a client's request goes through the entry to it and is written in the journal, and all of it goes away
again. The card and the cell's server are stand-ins: scripts/test_rust_scout_conformance.py's. Nothing of the machine is touched but its processes.

Run: python3 scripts/test_rust_whole.py    (after `cargo build --release -p proxy -p admin -p scout` in rust/)
"""
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ports import free_port  # noqa: E402
from test_rust_alone import Caravan, Check, SlowClient, listening, until  # noqa: E402
from test_rust_scout_conformance import StandIns  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL = "Qwen/author/Q4/qwen-Q4.gguf"
NAME = "whole-small"


class Scout:
    """The scout of one machine, in a folder of its own: what `install.sh` leaves, with stand-ins for the card and the server."""

    def __init__(self, base, program, host_id=None):
        self.base = base
        self.program = program
        self.port = free_port()
        self.stand_ins = StandIns(base / "stand-ins")
        # The board's talk to a cell comes by the machine's address, as to a real one, which listens on everything; and a real one says its places.
        server = StandIns.CELL.replace('("127.0.0.1", port)', '("0.0.0.0", port)')
        server = server.replace('if self.path == "/props":', 'if self.path == "/slots":\n            return self.reply(200, [{"id": 0}, {"id": 1}])\n        if self.path == "/props":')
        # What it was started with is said in its log: the story reads it.
        server = server.replace('print(f"cell on {port}', 'print("started with " + " ".join(argv), flush=True)\nprint(f"cell on {port}')
        # Asked to, it leaves a child with no environment: the mark gone, as vLLM's engine has it when it renames itself.
        server = server.replace('print("started with "', 'import os, subprocess\nif os.environ.get("STAND_IN_CHILD"): print("a child " + str(subprocess.Popen(["env", "-i", "sleep", "300"]).pid), flush=True)\nprint("started with "')
        self.stand_ins.write("llama-server", server)
        self.cache = base / "cache"
        self.cache.mkdir(parents=True)
        (base / "home").mkdir()
        self.config = base / "config.json"
        named = {"hostId": host_id, "displayName": host_id} if host_id else {}
        self.config.write_text(json.dumps({"llamaServerBin": str(self.stand_ins.cell), "modelsBasePath": str(self.cache), "llamaBuildsKeep": 5, "listenHost": "0.0.0.0", "listenPort": self.port, **named}))
        self.env = dict(os.environ)
        self.env.update({"HOME": str(base / "home"), "PATH": f"{self.stand_ins.folder}{os.pathsep}{self.env.get('PATH', '')}", "LAMA_CARAVAN_SERVER_CELLS_DIR": str(base / "server-cells"), "CARAVAN_SCOUT_ROOT": str(base), "TZ": "UTC"})
        self.log = open(base / "scout.log", "wb")
        self.start()

    def start(self):
        self.process = subprocess.Popen([str(self.program), "--config", str(self.config), "--state", str(self.base / "state.json")], cwd=self.base, env=self.env, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)

    def token(self):
        return json.loads(self.config.read_text()).get("controllerToken") or ""

    def stop(self):
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
            self.process.wait(5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            self.process.kill()
        self.log.close()


class Whole:
    """The one story, step by step: each step reads what the one before left."""

    def __init__(self, caravan, scout, check):
        self.caravan = caravan
        self.scout = scout
        self.check = check
        self.cell = free_port()
        self.host = None
        self.key = None
        self.entry = None

    def ask(self, *args, **kwargs):
        return self.caravan.ask(*args, **kwargs)

    def on_scout(self, method, target, body=None):
        return self.ask(method, target, body, port=self.scout.port, headers={"X-Caravan-Token": self.scout.token()})

    def scouts_cell(self):
        nodes = self.on_scout("GET", "/api/llama-node/status")[1].get("nodes") or []
        return next((node for node in nodes if node.get("port") == self.cell), None)

    def boards_cell(self):
        """The cell as the board reads it: the machine in the topology, and the cell's row in it."""
        for node in self.ask("GET", "/api/topology")[1].get("nodes") or []:
            for cell in node.get("servers") or []:
                if cell.get("port") == self.cell and node.get("id") == self.host:
                    return cell
        return None

    def pair(self):
        status, said, _ = self.ask("POST", "/api/topology/scout/connect", {"address": "127.0.0.1", "port": self.scout.port})
        self.check.that(status == 200 and said.get("hostId"), f"pairing: {status} {said}")
        self.host = said.get("hostId")
        self.check.that(self.scout.token(), "the scout was not given the fleet's token")
        status, _, _ = self.ask("GET", "/api/state", port=self.scout.port)
        self.check.that(status == 401, f"a paired scout without the token: {status}")
        online = lambda: any(row.get("id") == self.host and row.get("online") for row in self.ask("GET", "/api/machines")[1].get("machines", []))  # noqa: E731
        self.check.that(until(online, 30), f"the machine is not online: {self.ask('GET', '/api/machines')[1]}")
        beat = self.ask("GET", "/api/pairing", port=self.scout.port)[1].get("heartbeat") or {}
        self.check.that(beat.get("state") == "ok", f"the scout's word on its heartbeat: {beat}")

    def model_comes(self):
        """A library on another machine: asked by its name, the file comes from the controller into the scout's cache. Beside each other, as here, a cell started from the board reads the library in place."""
        start = {"port": self.cell, "modelPath": MODEL, "args": ["--port", str(self.cell), "-m", "{{MODEL_PATH}}"], "config": {}, "cacheModels": True}
        answer = self.on_scout("POST", "/api/llama-node/start", start)
        self.check.that(answer[0] == 200, f"a start by the model's name: {answer[1]}")
        self.check.that(until(lambda: (self.scouts_cell() or {}).get("phase") == "running", 40), f"the copy did not run: {self.scouts_cell()}")
        copied = self.scout.cache / MODEL
        original = self.caravan.base / "data" / "models" / MODEL
        self.check.that(copied.exists() and copied.read_bytes() == original.read_bytes(), "the model did not come byte for byte")
        self.check.that(self.on_scout("POST", "/api/llama-node/stop", {"port": self.cell})[0] == 200, "the copy's cell did not stop")
        self.check.that(until(lambda: not listening(self.cell), 15), "the copy's cell still holds the port")

    def start_cell(self):
        where = {"hostId": self.host, "port": self.cell}
        self.check.that(self.ask("POST", "/api/topology/server-slot/add", where)[0] == 200, "the slot was not added")
        config = {"MODEL_FILE": MODEL, "CTX_SIZE": "2048", "N_GPU_LAYERS": "99", "MODEL_NAME": NAME, "PORT": str(self.cell)}
        answer = self.ask("POST", "/api/topology/server-cell/save-config", {**where, "config": config, "cacheModels": True})
        self.check.that(answer[0] == 200, f"the config: {answer[1]}")
        answer = self.ask("POST", "/api/topology/server-cell/action", {**where, "action": "start"})
        self.check.that(answer[0] == 200, f"the start: {answer[1]}")
        self.check.that(until(lambda: (self.scouts_cell() or {}).get("phase") == "running", 40), f"the cell did not run: {self.scouts_cell()}")
        self.check.that(until(lambda: listening(self.cell), 10), f"nothing listens on the cell's port: {self.scouts_cell()} {self.on_scout('GET', f'/api/llama-node/log?port={self.cell}&lines=20')[1]}")
        # A beat says it now, not at the minute's end. The pull an open board kicks gives up after 2 s, and on a Mac the scout's state takes longer.
        beat = SlowClient(self.scout.port).post("/api/heartbeat", b"{}", {"X-Caravan-Token": self.scout.token()})
        self.check.that(beat == 200, f"the scout did not beat when asked: {beat}")
        running = lambda: (self.boards_cell() or {}).get("phase") == "running"  # noqa: E731
        self.check.that(until(running, 30), f"the board does not show the cell running: {self.boards_cell()}")

    def places_reach_the_board(self):
        """What a model says of its places, under the name the board looks for them by: the controller names the queue, the proxy counts it. An idle model's strip said "0 of ?" (the owner, 2026-10-26)."""
        def said():
            outputs = [out for router in self.ask("GET", "/api/topology")[1].get("routers") or [] for out in router.get("outputs") or [] if out.get("upstreamPort") in (self.cell, self.scout.port)]
            totals = ((self.ask("GET", "/api/system-monitor")[1].get("latest") or {}).get("agentProxies") or {}).get("slotTotals") or {}
            return outputs, totals
        def counted():
            outputs, totals = said()
            return outputs and all(totals.get(out.get("slotGroup")) == 2 for out in outputs if not out.get("stopped"))
        def proxy_saw():
            """What the board's figure is made of, said when it does not come: the proxy's sample as the monitor read it, and the end of the proxy's
            log. CI went red here two times in three on 2026-11-03 with `{}` and nothing else to read."""
            sample = (self.ask("GET", "/api/system-monitor")[1].get("latest") or {}).get("agentProxies") or {}
            log = self.caravan.base / "data" / "logs" / "rust-proxy.log"
            tail = log.read_text(errors="replace").splitlines()[-12:] if log.exists() else ["no proxy log"]
            return {key: sample.get(key) for key in ("ok", "error", "slotTotals", "pid", "startedAt")}, tail
        self.check.that(until(counted, 60), f"the board does not read the places: {said()} — the proxy: {proxy_saw()}")

    def through_the_entry(self):
        client = self.ask("POST", "/api/consumers/create", {"name": "Whole"})[1]
        self.key = client.get("key")
        self.entry = self.ask("GET", "/api/agent-proxy-entry")[1].get("port")
        auth = {"Authorization": f"Bearer {self.key}"}
        names = lambda: [row.get("id") for row in self.ask("GET", "/v1/models", port=self.entry, headers=auth)[1].get("data", [])]  # noqa: E731
        self.check.that(until(lambda: NAME in names(), 30), f"the client's list: {names()}")
        chat = {"model": NAME, "messages": [{"role": "user", "content": "hi"}]}
        status, said, _ = self.ask("POST", "/v1/chat/completions", chat, port=self.entry, headers=auth)
        self.check.that(status == 200 and said.get("path") == "/v1/chat/completions", f"a chat through the entry: {status} {said}")
        self.check.that(said.get("authorization") != auth["Authorization"], "the client's key went on to the cell")
        status, said, head = self.ask("POST", "/v1/chat/completions", {**chat, "stream": True}, port=self.entry, headers=auth)
        text = said if isinstance(said, str) else said.decode() if isinstance(said, bytes) else json.dumps(said)
        self.check.that(status == 200 and "text/event-stream" in head.get("content-type", "") and text.count("data: ") >= 2 and text.strip().endswith("[DONE]"), f"a stream through the entry: {status} {head} {text[:200]}")
        day = time.strftime("%Y-%m-%d", time.gmtime())
        rows = lambda: self.ask("GET", f"/api/agent-proxy-logs?date={day}&event=finished")[1].get("rows") or []  # noqa: E731
        self.check.that(until(lambda: len(rows()) >= 2, 10), f"the journal: {rows()}")
        talk = self.ask("POST", "/api/cell-talk", {"hostId": self.host, "port": self.cell, "mode": "text-chat", "text": "hi"})
        self.check.that(talk[0] == 200, f"the board's talk to the cell: {talk[0]} {talk[1]}")

    def stop_cell(self):
        where = {"hostId": self.host, "port": self.cell}
        answer = self.ask("POST", "/api/topology/server-cell/action", {**where, "action": "stop"})
        self.check.that(answer[0] == 200, f"the stop: {answer[1]}")
        self.check.that(until(lambda: not listening(self.cell), 15), "the cell's port is still held after the stop")
        self.check.that(until(lambda: not self.scouts_cell(), 15), f"the scout still holds the cell: {self.scouts_cell()}")

    def cache_turned_off(self):
        """The cache turned off from the board: the copies go, a model is read where the library lies on the machine, and one that is not there is refused, not brought."""
        where = {"hostId": self.host}
        said = lambda: (self.ask("POST", "/api/topology/client-llama/cache-keep", {**where, "keep": 1})[1].get("modelCache") or {})  # noqa: E731
        self.check.that(said().get("off") is False, f"a scout that can says so: {said()}")
        copied = self.scout.cache / MODEL
        self.check.that(copied.exists(), "the copy the start brought is not there to clear")
        library = self.scout.base / "library"
        status, answer, _ = self.ask("POST", "/api/topology/client-llama/cache-off", {**where, "off": True, "library": str(library)})
        self.check.that(status == 502 and "must be a folder" in str(answer), f"a library that is not there: {status} {answer}")
        self.check.that(copied.exists() and said().get("off") is False, "a refusal changed something")
        (library / MODEL).parent.mkdir(parents=True)
        (library / MODEL).write_bytes((self.caravan.base / "data" / "models" / MODEL).read_bytes())
        status, answer, _ = self.ask("POST", "/api/topology/client-llama/cache-off", {**where, "off": True, "library": str(library)})
        self.check.that(status == 200 and answer.get("result", {}).get("off") is True, f"turning it off: {status} {answer}")
        self.check.that((answer.get("modelCache") or {}).get("library") == str(library), f"the board does not read the library: {answer.get('modelCache')}")
        self.check.that(not copied.exists(), "the copy stayed after the cache was turned off")
        start = {"port": self.cell, "modelPath": MODEL, "args": ["--port", str(self.cell), "-m", "{{MODEL_PATH}}"], "config": {}, "cacheModels": True}
        self.check.that(self.on_scout("POST", "/api/llama-node/start", start)[0] == 200, "a start with the cache off")
        self.check.that(until(lambda: (self.scouts_cell() or {}).get("phase") == "running", 40), f"it did not run: {self.scouts_cell()}")
        self.check.that(not copied.exists(), "the cache is off, and the model was copied here")
        self.check.that(str(library / MODEL) in " ".join(str(word) for word in (self.scouts_cell() or {}).get("args", [])) or (library / MODEL).exists(), "it does not read from the library")
        self.check.that(self.on_scout("POST", "/api/llama-node/stop", {"port": self.cell})[0] == 200, "its stop")
        self.check.that(until(lambda: not listening(self.cell), 15), "it still holds the port")
        self.check.that((library / MODEL).exists(), "the stop took the library's file")
        missing = {**start, "modelPath": "Qwen/author/Q4/not-there.gguf"}
        self.on_scout("POST", "/api/llama-node/start", missing)
        failed = lambda: "of that size" in str(self.scouts_cell() or {})  # noqa: E731
        self.check.that(until(failed, 20), f"a model the library has not is refused in words: {self.scouts_cell()}")
        self.check.that(not (self.scout.cache / "Qwen/author/Q4/not-there.gguf").exists(), "it was brought after all")
        self.on_scout("POST", "/api/llama-node/stop", {"port": self.cell})
        status, answer, _ = self.ask("POST", "/api/topology/client-llama/cache-off", {**where, "off": False})
        self.check.that(status == 200 and (answer.get("modelCache") or {}).get("off") is False, f"turning it on: {status} {answer}")
        self.check.that((answer.get("modelCache") or {}).get("library") == str(library), "turned on, the machine forgot where its library lies")
        other = self.scout.base / "another-library"
        other.mkdir()
        status, answer, _ = self.ask("POST", "/api/topology/client-llama/cache-off", {**where, "off": False, "library": str(other)})
        self.check.that(status == 200 and (answer.get("modelCache") or {}).get("library") == str(other) and (answer.get("modelCache") or {}).get("off") is False, f"the library named with the cache on: {status} {answer}")

    def cache_cleared(self):
        """Clear from the board: what the scout brought goes, what the library has stays."""
        start = {"port": self.cell, "modelPath": MODEL, "args": ["--port", str(self.cell), "-m", "{{MODEL_PATH}}"], "config": {}, "cacheModels": True}
        self.check.that(self.on_scout("POST", "/api/llama-node/start", start)[0] == 200, "a start with the cache on again")
        self.check.that(until(lambda: (self.scouts_cell() or {}).get("phase") == "running", 40), f"it did not run: {self.scouts_cell()}")
        copied = self.scout.cache / MODEL
        self.check.that(copied.exists(), "the cache is on, and the model did not come")
        status, answer, _ = self.ask("POST", "/api/topology/client-llama/cache-clear", {"hostId": self.host})
        self.check.that(status == 200 and copied.exists(), f"a running cell keeps its files: {status} {answer}")
        self.on_scout("POST", "/api/llama-node/stop", {"port": self.cell})
        self.check.that(until(lambda: not listening(self.cell), 15), "it still holds the port")
        status, answer, _ = self.ask("POST", "/api/topology/client-llama/cache-clear", {"hostId": self.host})
        self.check.that(status == 200 and not copied.exists() and answer.get("result", {}).get("removed", 0) >= 1, f"the clearing: {status} {answer}")
        self.check.that((self.caravan.base / "data" / "models" / MODEL).exists(), "the library's file went with the copy")

    def through_the_controller(self):
        """The cache off by the long way, which is the default (the owner, 2026-11-02): no folder is mounted on the machine, nothing lands on its disk, and a program reads the controller's bytes from a file that is on no disk. Only where the machine has FUSE: elsewhere the step says it was not tried."""
        where = {"hostId": self.host}
        copied = self.scout.cache / MODEL
        self.check.that(not copied.exists(), "the clearing left the copy")
        said = self.ask("POST", "/api/topology/client-llama/cache-keep", {**where, "keep": 1})[1].get("modelCache") or {}
        if not said.get("canThrough"):
            print("rust whole: no FUSE on this machine, the way through the controller was not tried")
            return
        status, answer, _ = self.ask("POST", "/api/topology/client-llama/cache-off", {**where, "off": True, "library": ""})
        self.check.that(status == 200 and (answer.get("modelCache") or {}).get("through") is True, f"turning it off with no folder: {status} {answer}")
        start = {"port": self.cell, "modelPath": MODEL, "args": ["--port", str(self.cell), "-m", "{{MODEL_PATH}}"], "config": {}, "cacheModels": True}
        self.check.that(self.on_scout("POST", "/api/llama-node/start", start)[0] == 200, "a start through the controller")
        self.check.that(until(lambda: (self.scouts_cell() or {}).get("phase") == "running", 40), f"it did not run: {self.scouts_cell()}")
        told = lambda: " ".join(str(line) for line in self.on_scout("GET", f"/api/llama-node/log?port={self.cell}&lines=20")[1].get("lines") or [])  # noqa: E731
        self.check.that(until(lambda: "library-view" in told(), 10), f"the program was not given a file of the view: {told()}")
        path = Path(next(word for word in told().split() if "library-view" in word).rstrip(","))
        whole = (self.caravan.base / "data" / "models" / MODEL).read_bytes()
        self.check.that(path.read_bytes() == whole, "what the program reads is not what the controller holds")
        self.check.that(not copied.exists(), "the model landed on the machine's disk")
        self.on_scout("POST", "/api/llama-node/stop", {"port": self.cell})
        self.check.that(until(lambda: not listening(self.cell), 15), "it still holds the port")
        status, answer, _ = self.ask("POST", "/api/topology/client-llama/cache-off", {**where, "off": False})
        self.check.that(status == 200 and (answer.get("modelCache") or {}).get("through") is False, f"turning it on: {status} {answer}")

    def what_a_cell_left_goes_with_its_stop(self):
        """A server that goes and leaves a child behind, its environment rewritten and the mark with it, holding the card. Its scope knows it, where the machine makes scopes."""
        start = {"port": self.cell, "modelPath": MODEL, "args": ["--port", str(self.cell), "-m", "{{MODEL_PATH}}"], "config": {}, "cacheModels": True, "env": {"STAND_IN_CHILD": "1"}}
        self.check.that(self.on_scout("POST", "/api/llama-node/start", start)[0] == 200, "a start of a server with a child")
        self.check.that(until(lambda: (self.scouts_cell() or {}).get("phase") == "running", 40), f"it did not run: {self.scouts_cell()}")
        told = lambda: " ".join(str(line) for line in self.on_scout("GET", f"/api/llama-node/log?port={self.cell}&lines=20")[1].get("lines") or [])  # noqa: E731
        self.check.that(until(lambda: "a child " in told(), 10), f"it named no child: {told()}")
        child = int(told().split("a child ")[1].split()[0])
        group = Path(f"/proc/{child}/cgroup")
        scoped = group.exists() and "/run-" in group.read_text(encoding="utf-8")
        self.on_scout("POST", "/api/llama-node/stop", {"port": self.cell})
        self.check.that(until(lambda: not listening(self.cell), 15), "it still holds the port")
        if scoped:
            self.check.that(until(lambda: not Path(f"/proc/{child}").exists(), 20), f"what the cell left stayed: pid {child}")
            return
        print("rust whole: the machine makes no scopes here, what a cell leaves behind was not looked for")
        os.kill(child, signal.SIGKILL)

    def comes_back_with_what_was_saved(self):
        """A cell that crashed comes back with the settings saved since, and with the old ones only when nothing changed: a start by itself asks the controller, whose settings they are (the owner, 2026-11-02)."""
        where = {"hostId": self.host, "port": self.cell}
        config = {"MODEL_FILE": MODEL, "CTX_SIZE": "2048", "PARALLEL": "2", "MODEL_NAME": NAME, "PORT": str(self.cell)}
        self.check.that(self.ask("POST", "/api/topology/server-cell/save-config", {**where, "config": config, "cacheModels": True})[0] == 200, "the settings")
        self.check.that(self.ask("POST", "/api/topology/server-cell/action", {**where, "action": "start"})[0] == 200, "the start")
        self.check.that(until(lambda: (self.scouts_cell() or {}).get("phase") == "running", 40) and until(lambda: listening(self.cell), 10), f"it did not run: {self.scouts_cell()}")
        said = lambda: " ".join(str(line) for line in self.on_scout("GET", f"/api/llama-node/log?port={self.cell}&lines=40")[1].get("lines") or [])  # noqa: E731
        self.check.that(until(lambda: "--parallel 2" in said(), 10), f"its first start: {said()[:300]}")
        pid = (self.scouts_cell() or {}).get("pid")
        os.kill(pid, signal.SIGKILL)
        self.check.that(until(lambda: not listening(self.cell), 10), "it did not die")
        changed = {**config, "PARALLEL": "5"}
        self.check.that(self.ask("POST", "/api/topology/server-cell/save-config", {**where, "config": changed, "cacheModels": True})[0] == 200, "the settings saved while it is down")
        came_back = lambda: listening(self.cell) and "--parallel 5" in said()  # noqa: E731
        self.check.that(until(came_back, 40), f"it did not come back with what was saved: {said()[-400:]}")
        again = (self.scouts_cell() or {}).get("pid")
        self.check.that(again and again != pid, f"the same process: {pid} {again}")
        os.kill(again, signal.SIGKILL)
        self.check.that(until(lambda: not listening(self.cell), 10), "it did not die the second time")
        back = lambda: (self.scouts_cell() or {}).get("pid") not in (None, again) and listening(self.cell)  # noqa: E731
        self.check.that(until(back, 40), f"nothing changed, and it did not come back: {self.scouts_cell()}")
        self.check.that("--parallel 5" in said(), f"it came back with something else: {said()[-300:]}")
        self.on_scout("POST", "/api/llama-node/stop", {"port": self.cell})
        self.check.that(until(lambda: not listening(self.cell), 15), "it still holds the port")

    def a_machine_that_was_off_starts_what_was_saved(self):
        """The settings changed while the machine was off, and the scout could not be told: at its boot it asks the controller, and starts what is saved now. Only where a machine says which boot it is: elsewhere nothing starts at boot."""
        if not Path("/proc/sys/kernel/random/boot_id").exists():
            print("rust whole: this machine says no boot id, a start at boot was not tried")
            return
        where = {"hostId": self.host, "port": self.cell}
        config = {"MODEL_FILE": MODEL, "CTX_SIZE": "2048", "PARALLEL": "3", "MODEL_NAME": NAME, "PORT": str(self.cell)}
        self.check.that(self.ask("POST", "/api/topology/server-cell/save-config", {**where, "config": config, "cacheModels": True})[0] == 200, "the settings")
        self.check.that(self.ask("POST", "/api/topology/server-cell/action", {**where, "action": "enable"})[0] == 200, "its autostart")
        self.scout.stop()
        self.check.that(until(lambda: not listening(self.scout.port), 10), "the scout did not stop")
        answer = self.ask("POST", "/api/topology/server-cell/save-config", {**where, "config": {**config, "PARALLEL": "9"}, "cacheModels": True})
        self.check.that(answer[0] == 200, f"the settings saved with the machine off: {answer[1]}")
        state = self.scout.base / "state.json"
        kept = json.loads(state.read_text())
        kept["autostartBoot"] = "the boot before"
        state.write_text(json.dumps(kept))
        self.scout.log = open(self.scout.base / "scout.log", "ab")
        self.scout.start()
        self.check.that(until(lambda: listening(self.scout.port), 15), "the scout did not come up")
        self.check.that(until(lambda: listening(self.cell), 40), f"the cell did not start at the boot: {self.scouts_cell()}")
        said = lambda: " ".join(str(line) for line in self.on_scout("GET", f"/api/llama-node/log?port={self.cell}&lines=40")[1].get("lines") or [])  # noqa: E731
        self.check.that(until(lambda: "--parallel 9" in said(), 10), f"it started with what it kept, not what is saved: {said()[-300:]}")
        self.check.that(self.ask("POST", "/api/topology/server-cell/action", {**where, "action": "disable"})[0] == 200, "its autostart off")
        self.on_scout("POST", "/api/llama-node/stop", {"port": self.cell})
        self.check.that(until(lambda: not listening(self.cell), 15), "it still holds the port")

    def a_mark_outlives_its_model(self):
        """The owner's like stays when the cell and the model's files go, for he may meet the model again on /hf (the owner, 2026-11-02): it is kept by the model's name, apart from both."""
        model = MODEL.split("/")[0]
        self.check.that(self.ask("POST", "/api/model-rating", {"model": model, "rating": "like"})[0] == 200, "the like")
        status, said, _ = self.ask("POST", "/api/topology/server-slot/delete", {"hostId": self.host, "port": self.cell})
        self.check.that(status == 200 and said.get("removed"), f"the cell's deletion: {status} {said}")
        original = self.caravan.base / "data" / "models" / MODEL
        status, said, _ = self.ask("POST", "/api/models/gc", {"files": [MODEL]})
        self.check.that(status == 200 and not original.exists(), f"the model's deletion: {status} {said}")
        self.check.that(self.ask("GET", "/api/model-notes")[1].get("ratings", {}).get(model) == "like", "the like went with the model")
        self.check.that(self.ask("GET", "/api/topology")[1].get("modelRatings", {}).get(model) == "like", "the board lost the like")
        self.check.that(self.ask("POST", "/api/model-rating", {"model": model, "rating": ""})[0] == 200, "taking the like back")
        self.check.that(model not in self.ask("GET", "/api/model-notes")[1].get("ratings", {}), "negative: a like taken back stays gone")

    def cannot_replace_itself(self):
        """A scout run from a build tree does not say a release: the board's button is refused in words, by the controller, before the scout is asked."""
        status, said, _ = self.ask("GET", f"/api/fleet/scout-release?hostId={self.host}")
        self.check.that(status == 200 and said.get("running") is None, f"a scout without a release: {status} {said}")
        status, said, _ = self.ask("POST", "/api/fleet/scout-update", {"hostId": self.host})
        self.check.that(status == 404 and "carries no scout" in str(said), f"no bundle in the release: {status} {said}")
        Bundles(self.caravan).place("eeee5555", Bundles.pack(self.scout.program))
        status, said, _ = self.ask("POST", "/api/fleet/scout-update", {"hostId": self.host})
        self.check.that(status == 409 and "not installed as a release" in str(said), f"a scout without a release is told to update: {status} {said}")
        Bundles(self.caravan).remove()

    def a_cell_to_keep(self):
        where = {"hostId": self.host, "port": self.cell}
        self.check.that(self.ask("POST", "/api/topology/server-slot/add", where)[0] == 200, "the slot to keep was not added")
        config = {"MODEL_FILE": MODEL, "CTX_SIZE": "4096", "PARALLEL": "3", "MODEL_NAME": NAME, "PORT": str(self.cell)}
        self.check.that(self.ask("POST", "/api/topology/server-cell/save-config", {**where, "config": config, "cacheModels": True})[0] == 200, "the settings to keep")
        self.kept = (self.boards_cell() or {}).get("slotConfig")
        self.check.that((self.kept or {}).get("PARALLEL") == "3", f"the board does not hold the settings: {self.kept}")
        status, said, _ = self.ask("POST", "/api/pools/create", {"name": "Keeps a cell"})
        self.check.that(status == 200, f"the pool to keep: {status} {said}")
        status, said, _ = self.ask("POST", "/api/pools/add-row", {"poolId": said.get("pool", {}).get("id"), "target": {"output": f"srv:{self.host}:{self.cell}"}})
        self.check.that(status == 200, f"the pool's row on the cell: {status} {said}")
        self.documents_kept = self.documents()
        # What the operator set on the machine: the new scout is to get it back.
        answer = self.ask("POST", "/api/topology/client-llama/cache-budget", {"hostId": self.host, "budgetBytes": 3 << 30})
        self.check.that(answer[0] == 200, f"the cache's limit: {answer[1]}")
        self.check.that(self.ask("POST", "/api/topology/server-cell/action", {**where, "action": "enable"})[0] == 200, "the cell's autostart")
        beat = SlowClient(self.scout.port).post("/api/heartbeat", b"{}", {"X-Caravan-Token": self.scout.token()})
        self.check.that(beat == 200, f"the scout did not beat when asked: {beat}")
        said = lambda: next((row for row in self.ask("GET", "/api/topology")[1].get("nodes") or [] if row.get("id") == self.host), {})  # noqa: E731
        self.check.that(until(lambda: (said().get("modelCache") or {}).get("budgetBytes") == 3 << 30, 15), f"the board does not read the limit: {said().get('modelCache')}")

    def documents(self):
        """What the controller keeps beside the machine's own record: the cells' settings, the pools and their rows, the clients' routes."""
        data = self.caravan.base / "data"
        admin = json.loads((data / "state" / "admin.json").read_text(encoding="utf-8"))
        kept = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted((data / "config").glob("*.json"))}
        for router in kept.get("agent-proxies.json", {}).get("routers", []):
            router.pop("outputs", None)  # Made anew from what runs at the moment, and from nothing kept: ProxiesConfig::sync_router_outputs.
        kept["topology"] = {key: value for key, value in admin.get("topology", {}).items() if key != "hosts"}
        return kept

    @classmethod
    def differences(cls, before, after, path=""):
        """Where two documents differ, by the path of each place."""
        if isinstance(before, dict) and isinstance(after, dict):
            return [found for key in sorted({*before, *after}) for found in cls.differences(before.get(key), after.get(key), f"{path}.{key}")]
        if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
            return [found for at, pair in enumerate(zip(before, after)) for found in cls.differences(*pair, f"{path}[{at}]")]
        return [] if before == after else [f"{path}: {str(before)[:300]} -> {str(after)[:300]}"]

    def a_new_scout_finds_its_cells(self):
        """A cell's settings are the controller's, not the machine's (the owner, 2026-11-02: "they must be kept on the caravan, not on the machines with a scout"). The
        scout let go and taken off with every file of its own, another one installed under the machine's name finds each cell as it was."""
        machines = lambda: [row.get("id") for row in self.ask("GET", "/api/machines")[1].get("machines", [])]  # noqa: E731
        self.check.that(self.host not in machines(), f"the machine stayed after it was let go: {machines()}")
        self.scout.stop()
        self.scout = Scout(self.scout.base.parent / "scout-anew", self.scout.program, host_id=self.host)
        self.check.that(until(lambda: listening(self.scout.port), 15), "the new scout does not listen")
        self.check.that(not (self.on_scout("GET", "/api/pairing")[1].get("controllerUrl")), "the new scout already names a controller")
        status, said, _ = self.ask("POST", "/api/topology/scout/connect", {"address": "127.0.0.1", "port": self.scout.port})
        self.check.that(status == 200 and said.get("hostId") == self.host, f"pairing the new scout: {status} {said}")
        self.check.that(sorted(said.get("settingsBack") or []) == sorted(["cacheLimit", f"cell:{self.cell}"]), f"what came back: {said}")
        self.check.that(not said.get("settingsNotBack"), f"what did not come back: {said}")
        cache = self.on_scout("GET", "/api/llama-node/cache")[1]
        self.check.that(cache.get("budgetBytes") == 3 << 30, f"the new scout has no limit: {cache}")
        kept_cells = self.on_scout("GET", "/api/state")[1].get("autostart") or []
        self.check.that(self.cell in kept_cells, f"the new scout does not start the cell at boot: {kept_cells}")
        kept = lambda: (self.boards_cell() or {}).get("slotConfig")  # noqa: E731
        self.check.that(until(lambda: kept() == self.kept, 15), f"the cell's settings did not outlive the scout: {kept()} against {self.kept}")
        self.check.that((self.boards_cell() or {}).get("phase") in ("stopped", ""), f"the cell did not stand as it stood: {self.boards_cell()}")
        moved = self.differences(self.documents_kept, self.documents())
        moved = [place for place in moved if not place.startswith(".topology.machineSettings")]
        self.check.that(not moved, f"letting a machine go and pairing it again changed more than its record: {moved}")
        self.scout.stop()

    def let_go(self):
        answer = self.ask("POST", "/api/topology/scout/disconnect", {"hostId": self.host})
        self.check.that(answer[0] == 200, f"letting the scout go: {answer[1]}")
        pairing = lambda: self.ask("GET", "/api/pairing", port=self.scout.port)[1]  # noqa: E731
        self.check.that(until(lambda: not pairing().get("controllerUrl"), 15), f"the scout still names a controller: {pairing()}")

    def run(self):
        for step in (self.pair, self.model_comes, self.start_cell, self.places_reach_the_board, self.through_the_entry, self.stop_cell, self.cache_turned_off, self.cache_cleared, self.through_the_controller, self.what_a_cell_left_goes_with_its_stop, self.comes_back_with_what_was_saved, self.a_machine_that_was_off_starts_what_was_saved, self.a_mark_outlives_its_model, self.cannot_replace_itself, self.a_cell_to_keep, self.let_go, self.a_new_scout_finds_its_cells):
            step()
            if self.check.failed:
                return


class Bundles:
    """The scout a release of the controller carries: what deploy/nas/release_ship.py leaves in its folder."""

    def __init__(self, caravan):
        self.folder = caravan.release

    @staticmethod
    def pack(program):
        """The bundle of `program`: a path, or the text of a small script."""
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode="w:gz") as bundle:
            if isinstance(program, Path):
                bundle.add(program, arcname="caravan-scout")
            else:
                info = tarfile.TarInfo("caravan-scout")
                info.size, info.mode, info.mtime = len(program), 0o755, int(time.time())
                bundle.addfile(info, io.BytesIO(program))
            bundle.add(ROOT / "rust/crates/scout/scripts", arcname="scripts")
        return out.getvalue()

    def place(self, commit, packed, named=None):
        (self.folder / "scout-bundle.tar.gz").write_bytes(packed)
        (self.folder / "scout-bundle.json").write_text(json.dumps({"commit": commit, "sha256": named or hashlib.sha256(packed).hexdigest(), "bytes": len(packed)}))

    def remove(self):
        (self.folder / "scout-bundle.tar.gz").unlink()
        (self.folder / "scout-bundle.json").unlink()


class TakingARelease:
    """A machine's scout takes a new release from the board, as the ⋯ menu asks: the real controller and the real scout, installed as install.sh leaves it."""

    OLD = "aaaa1111"
    NEW = "bbbb2222"
    HOST = "whole-release"

    def __init__(self, caravan, base, program, check):
        self.caravan = caravan
        self.check = check
        self.bundles = Bundles(caravan)
        self.program = program
        self.home = base / "scout-home"
        (self.home / "releases" / self.OLD).mkdir(parents=True)
        shutil.copy2(program, self.home / "releases" / self.OLD / "caravan-scout")
        (self.home / "current").symlink_to(Path("releases") / self.OLD)
        base.mkdir(exist_ok=True)
        self.scout = Scout(base, self.home / "current" / "caravan-scout", host_id=self.HOST)

    def ask(self, *args, **kwargs):
        return self.caravan.ask(*args, **kwargs)

    def open_door(self, path):
        """A new machine has no token and no session: what it fetches is open."""
        return self.ask("GET", path, port=self.caravan.port)

    def status(self, host=""):
        return self.ask("GET", f"/api/fleet/scout-release?hostId={host}")

    def link(self):
        return os.readlink(self.home / "current")

    def nothing_to_hand_out(self):
        status, said, _ = self.status()
        self.check.that((status, said) == (200, {"ok": True, "release": None, "running": None, "installCommand": None}), f"no bundle: {status} {said}")
        for path in ("/scout/install.sh", "/scout/bundle.tar.gz"):
            status, said, _ = self.open_door(path)
            self.check.that(status == 404 and "carries no scout" in str(said), f"{path} with no bundle: {status} {str(said)[:200]}")

    def handed_out(self):
        packed = Bundles.pack(self.program)
        self.bundles.place(self.NEW, packed)
        sum_of = hashlib.sha256(packed).hexdigest()
        status, said, _ = self.status()
        self.check.that(status == 200 and said.get("release") == {"commit": self.NEW, "sha256": sum_of, "bytes": len(packed)}, f"the release on offer: {status} {said}")
        self.check.that(said.get("installCommand") == f"curl -fsSL http://127.0.0.1:{self.caravan.port}/scout/install.sh | bash", f"the command: {said.get('installCommand')}")
        status, _, _ = self.open_door("/api/fleet/scout-release")
        self.check.that(status == 401, f"what the board reads is not open: {status}")
        status, said, _ = self.open_door("/scout/bundle.tar.gz")
        self.check.that(status == 200 and said == packed, f"the bundle is not the file that was placed: {status}, {len(said)} bytes")
        status, script, _ = self.open_door("/scout/install.sh")
        script = script.decode() if isinstance(script, bytes) else str(script)
        for word in (self.NEW, sum_of, f"http://127.0.0.1:{self.caravan.port}"):
            self.check.that(status == 200 and word in script, f"the script does not say {word}: {status}")
        self.check.that("@@" not in script, "the script has a blank left in it")
        checked = subprocess.run(["bash", "-n"], input=script, capture_output=True, text=True)
        self.check.that(checked.returncode == 0, f"the script is not whole: {checked.stderr}")

    def pair(self):
        until(lambda: listening(self.scout.port), 15)
        status, said, _ = self.ask("POST", "/api/topology/scout/connect", {"address": "127.0.0.1", "port": self.scout.port})
        self.check.that(status == 200 and said.get("hostId") == self.HOST, f"pairing: {status} {said}")
        says = lambda: self.status(self.HOST)[1].get("running")  # noqa: E731
        self.check.that(until(lambda: says() == self.OLD, 30), f"the board does not read the release it runs: {says()}")

    def refused_and_nothing_changes(self):
        """A bundle that is not what was named, and a program that does not run: said by the scout, the link unmoved, the process alive."""
        self.bundles.place("cccc3333", Bundles.pack(self.program), named="0" * 64)
        status, said, _ = self.ask("POST", "/api/fleet/scout-update", {"hostId": self.HOST})
        self.check.that(status == 502 and "not what the controller named" in str(said), f"a wrong sum: {status} {said}")
        self.bundles.place("dddd4444", Bundles.pack(b"#!/bin/sh\nexit 3\n"))
        status, said, _ = self.ask("POST", "/api/fleet/scout-update", {"hostId": self.HOST})
        self.check.that(status == 502 and "does not run on this machine" in str(said), f"a program that does not run: {status} {said}")
        self.check.that(self.link() == f"releases/{self.OLD}", f"the link moved: {self.link()}")
        self.check.that(sorted(path.name for path in (self.home / "releases").iterdir()) == [self.OLD], f"a refusal left a folder: {list((self.home / 'releases').iterdir())}")
        self.check.that(self.scout.process.poll() is None, "a refusal ended the scout")

    def taken(self):
        self.bundles.place(self.NEW, Bundles.pack(self.program))
        status, said, _ = self.ask("POST", "/api/fleet/scout-update", {"hostId": self.HOST})
        self.check.that(status == 200 and said.get("commit") == self.NEW and said.get("restarting") is True, f"the update: {status} {said}")
        try:
            self.check.that(self.scout.process.wait(15) == 0, f"the scout ended with {self.scout.process.returncode}: its service would not read that as done")
        except subprocess.TimeoutExpired:
            self.check.that(False, "the scout did not end for its service to start the new one")
        self.check.that(self.link() == f"releases/{self.NEW}", f"the link: {self.link()}")
        release = self.home / "releases" / self.NEW
        self.check.that((release / "caravan-scout").is_file() and (release / "scripts/update-llama.sh").is_file(), "the program and its scripts are not in the release")
        self.check.that(not (release / "bundle.tar.gz").exists(), "the file it came in was left behind")
        self.check.that((self.home / "releases" / self.OLD).is_dir(), "the release before it is gone: there is no way back by hand")

    def service_starts_the_new_one(self):
        self.scout.start()
        until(lambda: listening(self.scout.port), 15)
        says = lambda: self.status(self.HOST)[1].get("running")  # noqa: E731
        self.check.that(until(lambda: says() == self.NEW, 30), f"the board does not read the new release: {says()}")
        status, said, _ = self.ask("POST", "/api/fleet/scout-update", {"hostId": self.HOST})
        self.check.that(status == 200 and said.get("restarting") is False, f"the same release again: {status} {said}")
        time.sleep(1)
        self.check.that(self.scout.process.poll() is None, "the same release asked twice restarted the scout")

    def run(self):
        for step in (self.nothing_to_hand_out, self.handed_out, self.pair, self.refused_and_nothing_changes, self.taken, self.service_starts_the_new_one):
            step()
            if self.check.failed:
                return


def programs():
    """The three programs, or None when this copy has not built them."""
    release = ROOT / "rust" / "target" / "release"
    named = {"admin": ("CARAVAN_RUST_ADMIN_BIN", "caravan-admin"), "proxy": ("CARAVAN_RUST_PROXY_BIN", "caravan-proxy"), "scout": ("CARAVAN_RUST_SCOUT_BIN", "caravan-scout")}
    found = {key: Path(os.environ.get(variable) or release / name).resolve() for key, (variable, name) in named.items()}
    return found if all(path.exists() for path in found.values()) else None


def main():
    found = programs()
    if found is None:
        if os.environ.get("CARAVAN_RUST_REQUIRED"):
            raise SystemExit("the three programs are not there")
        print("rust whole: skipped, the programs are not there")
        return 0
    check = Check()
    with tempfile.TemporaryDirectory(prefix="rust-whole-") as raw:
        base = Path(raw).resolve()
        library = base / "controller" / "data" / "models" / MODEL
        library.parent.mkdir(parents=True)
        library.write_bytes(b"GGUF" + bytes(range(256)) * 64)
        caravan = Caravan(base / "controller", found["admin"], found["proxy"], {"LLAMA_TOPOLOGY_SERVER_URL": "http://127.0.0.1:{port}"})
        scout = None
        try:
            caravan.wait()
            caravan.sign_in()
            (base / "machine").mkdir()
            scout = Scout(base / "machine", found["scout"])
            until(lambda: listening(scout.port), 15)
            Whole(caravan, scout, check).run()
            if not check.failed:
                scout.stop()
                scout = None
                (base / "machine-two").mkdir()
                taking = TakingARelease(caravan, base / "machine-two", found["scout"], check)
                scout = taking.scout
                taking.run()
            if check.failed:
                for log in (base / "machine" / "scout.log", base / "machine-two" / "scout.log", base / "controller" / "controller.log"):
                    if not log.exists():
                        continue
                    print("\n".join(line for line in log.read_text(errors="replace").splitlines() if '"GET /' not in line and '"POST /' not in line)[-1500:])
        finally:
            if scout:
                scout.stop()
            caravan.stop()
    if check.failed:
        raise SystemExit(f"rust whole: {len(check.failed)} failed")
    print("rust whole: ok, a machine, a model, a cell and a client's request, in Rust from end to end, and a scout that takes a new release from the board")
    return 0


if __name__ == "__main__":
    sys.exit(main())
