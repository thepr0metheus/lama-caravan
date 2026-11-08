#!/usr/bin/env python3
"""The caravan with no Python in it: the controller in Rust, the proxy in Rust as its child, the entry on the entry's own port.

What can be seen only with the two running together: a client made on the board calls through the entry, the entry moves and closes as the
board says, the journal and the board read what the proxy wrote, and a new release ends the old process.

Run: python3 scripts/test_rust_alone.py
Env: CARAVAN_RUST_ADMIN_BIN, CARAVAN_RUST_PROXY_BIN say which programs to run; CARAVAN_RUST_REQUIRED=1 makes a missing one a failure.
"""
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ports import free_port  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "alone-password"
RELEASE_LOOKS_EVERY = 5  # seconds; Startup::release_watch


class Provider(BaseHTTPRequestHandler):
    """A provider and a machine's entry: answers a list and a chat."""

    def log_message(self, *args):
        pass

    def say(self, payload, status=200):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.say({"object": "list", "data": [{"id": "gpt-x", "object": "model", "owned_by": "fake", "context_length": 128000}]})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.server.asked.append({"path": self.path, "model": body.get("model"), "authorization": self.headers.get("Authorization")})
        time.sleep(self.server.hold)
        self.say({"id": "c1", "object": "chat.completion", "model": body.get("model"), "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}})


class Check:
    """What was expected and did not come."""

    def __init__(self):
        self.failed = []

    def that(self, fact, words):
        if not fact:
            self.failed.append(words)
            print(f"FAIL {words}")


class Caravan:
    """The controller in a folder of its own, a release under a link."""

    def __init__(self, base, program, proxy_program, more_env=None):
        self.base = base
        self.port = free_port()
        self.cookie = ""
        self.proxy_pid = 0
        self.release = self.make_release("one", program, proxy_program)
        self.link = base / "current"
        self.link.symlink_to(self.release)
        self.log = open(base / "controller.log", "wb")
        env = {key: value for key, value in os.environ.items() if not key.startswith(("CARAVAN_", "LLAMA", "AGENT_PROXY"))}
        env.update({
            "CARAVAN_DATA_DIR": str(base / "data"), "CARAVAN_CONTAINER": "1", "CARAVAN_ROOT": str(self.link),
            "LLAMACPP_ADMIN_PORT": str(self.port), "LLAMACPP_ADMIN_HOST": "127.0.0.1", "LLAMA_TOPOLOGY_SERVER_IP": "192.0.2.1",
            "AGENT_PROXY_HOST": "127.0.0.1", "HOME": str(base / "home"), "TZ": "UTC",
        })
        env.update({name: value.format(port=self.port) for name, value in (more_env or {}).items()})
        (base / "home").mkdir(parents=True)
        (base / "data").mkdir(exist_ok=True)
        self.process = subprocess.Popen([str(self.link / "caravan-admin")], cwd=base, env=env, stdout=self.log, stderr=subprocess.STDOUT)

    def make_release(self, name, program, proxy_program):
        folder = self.base / "releases" / name
        (folder / "bin").mkdir(parents=True)
        os.symlink(program, folder / "caravan-admin")
        os.symlink(proxy_program, folder / "bin" / "caravan-proxy")
        os.symlink(ROOT / "static", folder / "static")
        os.symlink(ROOT / "cells", folder / "cells")
        return folder

    def ask(self, method, target, body=None, port=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", port or self.port, timeout=30)
        fields = dict(headers or {})
        if self.cookie and port is None:
            fields["Cookie"] = self.cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            fields["Content-Type"] = "application/json"
        connection.request(method, target, data, fields)
        response = connection.getresponse()
        raw = response.read()
        head = {key.lower(): value for key, value in response.getheaders()}
        connection.close()
        try:
            said = json.loads(raw)
        except ValueError:
            said = raw
        return response.status, said, head

    def wait(self):
        for _ in range(300):
            if self.process.poll() is not None:
                raise SystemExit("the controller ended at its start:\n" + (self.base / "controller.log").read_text(errors="replace")[-3000:])
            try:
                if self.ask("GET", "/healthz")[0] == 200:
                    return
            except OSError:
                time.sleep(0.1)
        raise SystemExit("the controller did not answer")

    def sign_in(self):
        answer = self.ask("POST", "/api/auth/setup", {"username": "owner", "password": PASSWORD})
        self.cookie = answer[2].get("set-cookie", "").split(";")[0]

    def note_the_proxy(self):
        services = self.ask("GET", "/api/controller-info")[1].get("services") or []
        child = next((row for row in services if row.get("unit") == "agent-proxies (child)"), {})
        self.proxy_pid = int(child.get("pid") or self.proxy_pid)

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.log.close()


class SlowClient:
    """A client whose body comes after its head: what a long body on a slow line looks like to a server that refuses at the head, or needs no body.
    Such a server has answered before the body arrives. Whether the client gets to read that answer is what is asked here."""

    PAUSE = 0.2

    def __init__(self, port):
        self.port = port

    def post(self, target, body=b"{}", fields=None):
        """The status of the answer, or the failure that took it."""
        lines = [f"POST {target} HTTP/1.1", "Host: 127.0.0.1", "Connection: close", f"Content-Length: {len(body)}", *(f"{name}: {value}" for name, value in (fields or {}).items()), "", ""]
        with socket.create_connection(("127.0.0.1", self.port), timeout=20) as client:
            client.sendall("\r\n".join(lines).encode())
            time.sleep(self.PAUSE)
            try:
                client.sendall(body)
                answer = b""
                while piece := client.recv(65536):
                    answer += piece
            except OSError as error:
                return repr(error)
        return int(answer.split(b" ", 2)[1]) if answer.startswith(b"HTTP/") else f"no answer: {answer[:80]!r}"


def listening(port):
    with socket.socket() as probe:
        probe.settimeout(0.3)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def until(fact, seconds=15):
    limit = time.time() + seconds
    while time.time() < limit:
        if fact():
            return True
        time.sleep(0.1)
    return False


def main():
    program = Path(os.environ.get("CARAVAN_RUST_ADMIN_BIN") or ROOT / "rust/target/release/caravan-admin").resolve()
    proxy_program = Path(os.environ.get("CARAVAN_RUST_PROXY_BIN") or ROOT / "rust/target/release/caravan-proxy").resolve()
    if not program.exists() or not proxy_program.exists():
        if os.environ.get("CARAVAN_RUST_REQUIRED"):
            raise SystemExit(f"{program} or {proxy_program} is not there")
        print("rust alone: skipped, the programs are not there")
        return
    provider = ThreadingHTTPServer(("127.0.0.1", free_port()), Provider)
    provider.asked = []
    provider.hold = 0
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{provider.server_address[1]}/v1"
    check = Check()
    with tempfile.TemporaryDirectory(prefix="rust-alone-") as raw:
        # With no Python in it, nobody else takes a journal's old days away.
        journal = Path(raw).resolve() / "data" / "logs" / "proxy-events"
        journal.mkdir(parents=True)
        (journal / "2001-01-01.jsonl").write_text("{}\n")
        caravan = Caravan(Path(raw).resolve(), program, proxy_program)
        try:
            caravan.wait()
            caravan.sign_in()
            run(caravan, check, base_url, provider)
        finally:
            caravan.stop()
    with tempfile.TemporaryDirectory(prefix="rust-alone-killed-") as raw:
        a_killed_controller_takes_its_proxy_along(Path(raw).resolve(), program, proxy_program, check)
    if check.failed:
        raise SystemExit(f"rust alone: {len(check.failed)} failed")
    print("rust alone: ok, the caravan runs with no Python in it")


def run(caravan, check, base_url, provider):
    asked = caravan.ask
    # The entry the built-in clients opened at the start.
    entry = asked("GET", "/api/agent-proxy-entry")[1]
    first_port = entry.get("port")
    check.that(first_port, f"no entry at the start: {entry}")
    check.that(until(lambda: listening(first_port)), f"the proxy does not listen on the entry's port {first_port}")
    # A client, an account with a key and a pool: as the board makes them.
    client = asked("POST", "/api/consumers/create", {"name": "Hermes"})[1]
    key = client.get("key")
    check.that(key, f"no key for the client: {client}")
    asked("POST", "/api/cloud-accounts/save", {"account": {"id": "key1", "type": "custom", "name": "A key", "baseUrl": base_url}})
    asked("POST", "/api/cloud-accounts/key", {"id": "key1", "apiKey": "sk-test"})
    pool = asked("POST", "/api/pools/create", {"name": "Fast", "accountId": "key1", "model": "gpt-x"})[1]
    check.that(pool.get("pool"), f"no pool: {pool}")
    auth = {"Authorization": f"Bearer {key}"}
    status, listed, _ = asked("GET", "/v1/models", port=first_port, headers=auth)
    names = [row.get("id") for row in listed.get("data", [])] if isinstance(listed, dict) else []
    check.that(status == 200 and "Fast" in names, f"the client's list: {status} {listed}")
    status, said, _ = asked("POST", "/v1/chat/completions", {"model": "Fast", "messages": [{"role": "user", "content": "hi"}]}, port=first_port, headers=auth)
    check.that(status == 200 and said.get("choices"), f"a chat through the entry: {status} {said}")
    check.that(provider.asked and provider.asked[-1]["authorization"] == "Bearer sk-test", f"what the provider got: {provider.asked}")
    # A port of its own is no more: nothing would listen on it. The owner's word of 2026-11-02.
    made = asked("POST", "/api/agent-port", {"clientId": "x", "agentId": "x", "label": "x"})
    check.that(made[0] == 404, f"a new port of its own: {made[0]} {made[1]}")
    reopened = asked("POST", "/api/agent-proxies/route-policy", {"routeId": client.get("routeId"), "portClosed": False})
    check.that(reopened[0] == 410, f"a client's port opened again: {reopened[0]} {reopened[1]}")
    # A client is known by its record's id and has no number (the owner, 2026-11-07).
    routes = asked("GET", "/api/topology")[1].get("proxies") or []
    check.that(routes and all(row.get("id") and "port" not in row and "portClosed" not in row for row in routes),
               f"every client stands by its id, with no number: {routes}")
    by_port = asked("POST", "/api/consumers/key", {"port": 23001})
    check.that(by_port[0] == 400 and "routeId" in str(by_port[1]), f"a client asked by a number: {by_port[0]} {by_port[1]}")
    # What the entry used to hand to Python.
    status, said, _ = asked("PUT", "/v1/chat/completions", {}, port=first_port, headers=auth)
    check.that(status == 501, f"a method no client uses: {status} {said}")
    status, said, _ = asked("GET", "http://x/v1/models", port=first_port, headers=auth)
    check.that(status == 200, f"a target with an address in it: {status} {said}")
    status, said, _ = asked("GET", "/v1/models", port=first_port, headers={"Authorization": "Bearer nobody"})
    check.that(status == 401, f"a key that names nobody: {status} {said}")
    # A refusal does not wait for the body it refuses, and the client still reads it.
    slow = SlowClient(first_port)
    check.that(slow.post("/v1/chat/completions", b"{}", {"Authorization": "Bearer nobody"}) == 401, "a slow client of the entry lost its refusal")
    long = slow.post("/v1/chat/completions", b"x" * (8 << 20), {"Authorization": "Bearer nobody"})
    check.that(long == 401, f"a long body lost its refusal: {long}")
    refused = SlowClient(caravan.port).post("/api/consumers/create", b"x" * (8 << 20))
    check.that(refused == 401, f"a slow client of the board lost its refusal: {refused}")
    # What the board reads of the proxy.
    day = time.strftime("%Y-%m-%d", time.gmtime())
    logs = asked("GET", f"/api/agent-proxy-logs?date={day}&event=finished")[1]
    check.that(logs.get("rows"), f"the journal has the chat: {logs}")
    check.that(not (caravan.base / "data" / "logs" / "proxy-events" / "2001-01-01.jsonl").exists(), "the journal's old day was not taken away")
    def monitor_sees():
        latest = asked("GET", "/api/system-monitor")[1].get("latest") or {}
        return (latest.get("agentProxies") or {}).get("ok") is True
    check.that(until(monitor_sees, 30), "the monitor does not read the proxy's state")
    door = asked("GET", "/api/topology")[1].get("portsReachable")
    check.that(door is False, f"the board's word on the door of a proxy that listens on loopback: {door}")
    services = asked("GET", "/api/controller-info")[1].get("services") or []
    child = next((row for row in services if row.get("unit") == "agent-proxies (child)"), {})
    check.that(child.get("active") == "active", f"the board's word on the proxy child: {services}")
    # The entry moves; it does not close under its clients.
    moved = free_port()
    answer = asked("POST", "/api/agent-proxy-entry", {"port": moved})
    check.that(answer[0] == 200, f"the entry did not move: {answer[1]}")
    check.that(until(lambda: listening(moved)), f"nothing listens on the entry's new port {moved}")
    check.that(until(lambda: not listening(first_port)), f"the old port {first_port} is still held")
    status, said, _ = asked("GET", "/v1/models", port=moved, headers=auth)
    check.that(status == 200, f"the client on the new port: {status} {said}")
    answer = asked("POST", "/api/agent-proxy-entry", {"port": 0})
    check.that(answer[0] == 409 and listening(moved), f"an entry its clients stand on stays open: {answer[1]}")
    # A new release waits for the request under way, then ends the old process, for the container's restart to start the new one.
    provider.hold = RELEASE_LOOKS_EVERY * 2
    provider.asked.clear()
    answers = []
    chat = {"model": "Fast", "messages": [{"role": "user", "content": "hi"}]}
    slow = threading.Thread(target=lambda: answers.append(asked("POST", "/v1/chat/completions", chat, port=moved, headers=auth)), daemon=True)
    slow.start()
    check.that(until(lambda: provider.asked), "the slow chat did not reach the provider")
    # A really new file of the proxy, as a release brings: the old one lets the port go and finishes what it holds, and the state file is the new one's.
    new_proxy = caravan.base / "caravan-proxy-two"
    shutil.copy(os.readlink(caravan.release / "bin" / "caravan-proxy"), new_proxy)
    second = caravan.make_release("two", os.readlink(caravan.release / "caravan-admin"), new_proxy)
    temporary = caravan.base / "current.new"
    temporary.symlink_to(second)
    caravan.note_the_proxy()
    old_proxy = caravan.proxy_pid
    os.replace(temporary, caravan.link)
    check.that(until(lambda: caravan.note_the_proxy() or caravan.proxy_pid != old_proxy, 5), "the new file of the proxy did not start")
    check.that(until(lambda: asked("GET", "/v1/models", port=moved, headers=auth)[0] == 200, 8), "the new proxy does not answer on the entry")
    time.sleep(RELEASE_LOOKS_EVERY)
    check.that(caravan.process.poll() is None, "the old process ended while the replaced proxy still held a request")
    slow.join(30)
    check.that(answers and answers[0][0] == 200, f"the request under way when the release came: {answers}")
    check.that(until(lambda: caravan.process.poll() is not None, 20), "the old process did not end for the new release")
    check.that(caravan.process.poll() == 0, f"it ended with {caravan.process.poll()}")
    # Nothing else ends a proxy in a session of its own: left behind, it would hold the entry's port against the proxy of the next controller.
    check.that(until(lambda: not listening(moved), 8), "the proxy outlived the controller that ended and holds the entry's port")


def a_killed_controller_takes_its_proxy_along(raw, program, proxy_program, check):
    """The same with no word from the controller: a `kill -9`, or a preview pane closing. It is told by its parent, not by a goodbye."""
    caravan = Caravan(raw, program, proxy_program)
    try:
        caravan.wait()
        caravan.sign_in()
        port = caravan.ask("GET", "/api/agent-proxy-entry")[1].get("port")
        check.that(until(lambda: listening(port)), f"the proxy does not listen on the entry's port {port}")
        caravan.process.kill()
        caravan.process.wait(5)
        check.that(until(lambda: not listening(port), 8), "the proxy of a killed controller holds the entry's port")
        said = raw / "data" / "logs" / "rust-proxy.log"
        check.that(until(lambda: "this version ends" in said.read_text(errors="replace"), 8), "the proxy of a killed controller did not end")
        check.that("the controller that keeps it is gone" in said.read_text(errors="replace"), "the proxy does not say why it left")
    finally:
        caravan.stop()


if __name__ == "__main__":
    main()
