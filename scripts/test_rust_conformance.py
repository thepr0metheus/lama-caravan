#!/usr/bin/env python3
"""The proxy against what the proxy promised: requests through its door, and what it said compared with tests/frozen/proxy.jsonl.

The file is what the proxy in Python said when it left the repository (scripts/_frozen_answers.py), with what was decided otherwise written over it
(docs/backend-proxy.md). The program runs alone on the entry's port, with a fake machine and fake providers behind it, scripted by the
model a request names. What must come out the same:

  - what the client got: the status, the fields that mean something, the body;
  - what the model got: the path, the fields, the body;
  - what the journal says: the events in their order and the finished record, field by field.

What may differ is said once, in Differences, each with its reason.

A binary not built is said out loud and skips, on a machine with no Rust; with CARAVAN_RUST_REQUIRED=1, as the CI job that built
it sets, it is a failure.

Run: cargo build --release -p proxy (in rust/), then python3 scripts/test_rust_conformance.py
     python3 scripts/test_rust_conformance.py --only stream-ok   (one scenario)
     python3 scripts/test_rust_conformance.py --slow             (with what takes a keepalive's turn; the CI job runs this)
     python3 scripts/test_rust_conformance.py --write            (keeps what the program says now: its diff is what changed)
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from _frozen_answers import FrozenAnswers, OwnWords
from _ports import free_port

ROOT = Path(__file__).resolve().parent.parent
KEY = "conformance-client-key"
DENIED_KEY = "conformance-denied-key"
PAUSED_KEY = "conformance-paused-key"
OFF_LIST_KEY = "conformance-off-list-key"
SHARED_KEY = "conformance-shared-key"


class Binary:
    """Where the program's program is, or the fact that it is not there."""

    NAMES = ("rust/target/release/caravan-proxy", "rust/target/debug/caravan-proxy")

    @classmethod
    def find(cls):
        said = os.environ.get("CARAVAN_RUST_PROXY_BIN")
        if said:
            return Path(said)
        found = [ROOT / name for name in cls.NAMES if (ROOT / name).exists()]
        return max(found, key=lambda path: path.stat().st_mtime) if found else None


class Keepalive:
    """A silence long enough for the sign of life both proxies send a waiting stream: its turn is 20 s, on both sides."""

    SILENCE = 23
    #: How long the program keeps a stream's head back while its pool has another row: `Watch::HEAD_HELD_BACK`.
    HEAD_HELD_BACK = 2


class Certificates:
    """What a provider's address looks like over TLS, made for one run: an authority both proxies are told to trust, one nobody trusts, and a
    certificate of each for `localhost`, the only name it names."""

    def __init__(self):
        self.folder = Path(tempfile.mkdtemp(prefix="caravan-conformance-tls-"))
        self.authority = self.make_authority("trusted")
        self.make_authority("stranger")

    def run(self, *words):
        subprocess.run(["openssl", *words], check=True, capture_output=True)

    def make_authority(self, name):
        cert, key = self.folder / f"{name}-authority.pem", self.folder / f"{name}-authority.key"
        self.run("req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", str(key), "-out", str(cert),
                 "-days", "2", "-subj", f"/CN=conformance {name} authority", "-addext", "basicConstraints=critical,CA:TRUE",
                 "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        self.make_leaf(name, cert, key)
        return cert

    def make_leaf(self, name, authority, authority_key):
        cert, key, asked, words = (self.folder / f"{name}{tail}" for tail in (".pem", ".key", ".csr", ".ext"))
        self.run("req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", str(key), "-out", str(asked), "-subj", "/CN=localhost")
        words.write_text("subjectAltName=DNS:localhost\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
                         "extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n", encoding="utf-8")
        self.run("x509", "-req", "-in", str(asked), "-CA", str(authority), "-CAkey", str(authority_key), "-CAcreateserial", "-out", str(cert),
                 "-days", "2", "-extfile", str(words))

    def server_side(self, name):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.folder / f"{name}.pem", self.folder / f"{name}.key")
        return context


class FakeMachine:
    """A machine's entry behind both proxies: answers by the model a request names, and remembers what it was asked."""

    SSE = [
        b'data: {"id":"c1","model":"real","choices":[{"delta":{"role":"assistant"}}]}\n\n',
        'data: {"id":"c1","model":"real","choices":[{"delta":{"content":"Привет"}}]}\n\n'.encode(),
        b'data: {"id":"c1","model":"real","choices":[{"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":3,"completion_tokens":2,"prompt_tokens_details":{"cached_tokens":1}},'
        b'"timings":{"predicted_n":2,"predicted_ms":5.5}}\n\n',
        b"data: [DONE]\n\n",
    ]
    WHOLE = json.dumps({"id": "c2", "object": "chat.completion", "model": "real",
                        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 7, "completion_tokens": 1}, "timings": {"predicted_n": 1}}).encode()

    def __init__(self, port=0, slots=None, tls=None):
        self.lock = threading.Lock()
        #: The connections an answer left open, as the provider holds them.
        self.left_open = []
        self.asked = []
        self.calls = {}
        self.slots = slots or {}
        self.release = threading.Event()
        self.saw_client_leave = threading.Event()
        #: What the provider's token address was asked.
        self.renewals = []
        machine = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                return

            def do_GET(self):
                if self.path == FakeMachine.USAGE_PATH:
                    machine.answer_usage_page(self)
                    return
                name = self.path.rsplit("/", 1)[-1]
                body = json.dumps({"id": name, "caravan": {"slots": machine.slots.get(name, 4), "busy": 0}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                if self.path == "/oauth/token":
                    machine.renewals.append(body.decode())
                    tokens = {"access_token": Data.token_for("renewed-now"), "refresh_token": "a-new-refresh-token", "expires_in": 3600}
                    machine.json_answer(self, 200, json.dumps(tokens).encode())
                    self.close_connection = True
                    return
                form_model = re.search(rb'name="model"\r\n\r\n([^\r]*)\r\n', body)
                payload = ({"model": form_model.group(1).decode()} if form_model else json.loads(body) if body else {})
                model = payload.get("model")
                with machine.lock:
                    machine.calls[model] = machine.calls.get(model, 0) + 1
                    call = machine.calls[model]
                    machine.asked.append({"is_provider": self.path.startswith(("/backend-api/", "/provider/")),
                                          "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                          "forwarded": len(self.headers.get_all("X-Forwarded-For") or []), "body": payload, "raw": body})
                self.close_connection = True
                getattr(machine, "answer_" + str(model).replace("-", "_"), machine.answer_unknown)(self, call)

        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.daemon_threads = True
        if tls:
            # The handshake is the connection's thread's: one a client gives up on stops nothing here, and says nothing to the test's output.
            self.server.socket = tls.wrap_socket(self.server.socket, server_side=True, do_handshake_on_connect=False)
            self.server.handle_error = lambda request, address: None
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close_what_it_left_open(self):
        """A provider closing an idle connection, as they all do in the end."""
        with self.lock:
            for connection in self.left_open:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            self.left_open.clear()

    def forget(self):
        with self.lock:
            self.asked.clear()
            self.calls.clear()
        self.release.clear()
        self.saw_client_leave.clear()

    @staticmethod
    def json_answer(handler, status, body, kind="application/json", extra=()):
        handler.send_response(status)
        handler.send_header("Content-Type", kind)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Connection", "close")
        handler.send_header("X-Provider-Secret", "must-not-reach-a-client")
        for name, value in extra:
            handler.send_header(name, value)
        handler.end_headers()
        handler.wfile.write(body)

    @staticmethod
    def stream_head(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.send_header("Connection", "close")
        handler.send_header("X-Provider-Secret", "must-not-reach-a-client")
        handler.end_headers()

    @staticmethod
    def chunk(handler, data):
        handler.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        handler.wfile.flush()

    USAGE_PATH = "/backend-api/wham/usage"
    #: What a subscription's account has used of its five hours, by the account its token names.
    USED = {"plenty": 5, "low": 95, "giving-way": 85}
    #: What an answer states when it is more than the page said: a window filling up between two requests.
    USED_BY_THE_ANSWER = {"rising": 99}
    #: A reset far enough ahead for any run, and fixed: both sides must read one figure.
    RESET_AT = int(time.time()) + 90_000

    def usage_of(self, handler):
        used = self.USED.get(handler.headers.get("chatgpt-account-id"), 5)
        return used

    def answer_usage_page(self, handler):
        window = {"limit_window_seconds": 18000, "used_percent": self.usage_of(handler), "reset_at": self.RESET_AT}
        self.json_answer(handler, 200, json.dumps({"rate_limit": {"allowed": True, "primary_window": window}}).encode())

    def windows_of(self, handler):
        """What every answer of a subscription states of its windows."""
        used = self.USED_BY_THE_ANSWER.get(handler.headers.get("chatgpt-account-id"), self.usage_of(handler))
        return [("x-codex-primary-window-minutes", "300"), ("x-codex-primary-used-percent", str(used)),
                ("x-codex-primary-reset-at", str(self.RESET_AT))]

    def responses_stream(self, handler, events):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Transfer-Encoding", "chunked")
        handler.send_header("Connection", "close")
        handler.send_header("X-Provider-Secret", "must-not-reach-a-client")
        for name, value in self.windows_of(handler):
            handler.send_header(name, value)
        handler.end_headers()
        for event in events:
            self.chunk(handler, ("event: " + event["type"] + "\n" + "data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode())
        handler.wfile.write(b"0\r\n\r\n")

    SUBSCRIPTION_ANSWER = [{"type": "response.created"}, {"type": "response.output_text.delta", "delta": "При"},
                           {"type": "response.output_text.delta", "delta": "вет \"мир\""},
                           {"type": "response.output_item.done", "item": {"type": "message", "content": []}},
                           {"type": "response.completed", "response": {"usage": {"input_tokens": 3, "output_tokens": 2}}}]
    SUBSCRIPTION_CALL = [{"type": "response.output_item.added", "output_index": 1, "item": {"type": "function_call", "call_id": "k", "name": "read"}},
                         {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "{\"p\":"},
                         {"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "1}"},
                         {"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "k", "name": "read"}},
                         {"type": "response.completed", "response": {"output": [{"type": "function_call"}], "usage": {"input_tokens": 4, "output_tokens": 1}}}]

    def answer_sub_ok(self, handler, call):
        self.responses_stream(handler, self.SUBSCRIPTION_ANSWER)

    def answer_sub_low_model(self, handler, call):
        self.responses_stream(handler, self.SUBSCRIPTION_ANSWER)

    def answer_sub_giving_way(self, handler, call):
        self.responses_stream(handler, self.SUBSCRIPTION_ANSWER)

    def answer_sub_tools(self, handler, call):
        self.responses_stream(handler, self.SUBSCRIPTION_CALL)

    def answer_sub_cut(self, handler, call):
        self.responses_stream(handler, self.SUBSCRIPTION_ANSWER[:2])

    def answer_sub_effort(self, handler, call):
        """A model that takes the efforts it lists, and says so by its refusal."""
        with self.lock:
            asked = (self.asked[-1]["body"].get("reasoning") or {}).get("effort")
        if asked == "none":
            error = {"error": {"param": "reasoning.effort", "message": "Unsupported value: 'none' is not supported with the 'sub-effort' model. "
                                                                       "Supported values are: 'low', 'medium', 'high', and 'max'."}}
            self.json_answer(handler, 400, json.dumps(error).encode(), extra=self.windows_of(handler))
            return
        self.responses_stream(handler, self.SUBSCRIPTION_ANSWER)

    def answer_sub_429(self, handler, call):
        self.json_answer(handler, 429, b'{"error":{"message":"a limit that names someone@example.org"}}', extra=[("Retry-After", "200"), *self.windows_of(handler)])

    ANTHROPIC_EVENTS = [{"type": "message_start", "message": {"usage": {"input_tokens": 3, "cache_read_input_tokens": 10, "output_tokens": 1}}},
                        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
                        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "При\"вет"}},
                        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "read"}},
                        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{}"}},
                        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
                        {"type": "message_stop"}]

    def anthropic_stream(self, handler, events):
        self.stream_head(handler)
        for event in events:
            self.chunk(handler, ("event: " + event["type"] + "\n" + "data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode())
        handler.wfile.write(b"0\r\n\r\n")

    def answer_anth_ok(self, handler, call):
        with self.lock:
            streams = bool(self.asked[-1]["body"].get("stream"))
        if streams:
            self.anthropic_stream(handler, self.ANTHROPIC_EVENTS)
            return
        whole = {"content": [{"type": "text", "text": "При"}, {"type": "tool_use", "id": "t1", "name": "read", "input": {"a": "я", "b": [1, 2.5]}}],
                 "usage": {"input_tokens": 3, "output_tokens": 2, "cache_creation_input_tokens": 4}}
        self.json_answer(handler, 200, json.dumps(whole, ensure_ascii=False).encode())

    def answer_anth_cut(self, handler, call):
        self.anthropic_stream(handler, self.ANTHROPIC_EVENTS[:3])

    def answer_key_ok(self, handler, call):
        self.answer_whole_ok(handler, call)

    def answer_key_stream(self, handler, call):
        self.answer_stream_ok(handler, call)

    def answer_key_429(self, handler, call):
        self.json_answer(handler, 429, b'{"error":{"message":"a limit that names someone@example.org"}}', extra=[("Retry-After", "200")])

    def answer_key_401(self, handler, call):
        self.json_answer(handler, 401, b'{"error":{"message":"a sign-in that names someone@example.org"}}')

    def answer_key_402(self, handler, call):
        self.json_answer(handler, 402, b'{"error":{"message":"money that names someone@example.org"}}')

    def answer_key_500(self, handler, call):
        self.json_answer(handler, 500, b"internal words that name the provider", kind="text/plain")

    def answer_key_400(self, handler, call):
        self.json_answer(handler, 400, b'{"error":{"message":"the context is too long","code":"its_own_code"}}')

    def answer_key_drops(self, handler, call):
        """Keeps its connection open, and when asked on it again closes it without a word: what a stale connection does to a request already written."""
        if getattr(handler, "served_once", False):
            handler.close_connection = True
            handler.connection.shutdown(socket.SHUT_RDWR)
            return
        handler.served_once = True
        self.answer_key_keeps(handler, call)

    def answer_key_keeps(self, handler, call):
        """An answer that leaves its connection open: the next request to this provider comes on it."""
        handler.close_connection = False
        with self.lock:
            self.left_open.append(handler.connection)
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(self.WHOLE)))
        handler.end_headers()
        handler.wfile.write(self.WHOLE)

    def answer_unknown(self, handler, call):
        self.json_answer(handler, 404, b'{"error":{"message":"no such model","code":"model_missing"}}')

    def answer_stream_ok(self, handler, call):
        self.stream_head(handler)
        for frame in self.SSE:
            self.chunk(handler, frame)
        handler.wfile.write(b"0\r\n\r\n")

    def answer_stream_split(self, handler, call):
        """The events cut across chunks, and `[DONE]` with no blank line after it: the frame must still end for the client."""
        self.stream_head(handler)
        whole = b"".join(self.SSE[:-1]) + b"data: [DONE]\n"
        for at in range(0, len(whole), 17):
            self.chunk(handler, whole[at:at + 17])
        handler.wfile.write(b"0\r\n\r\n")

    def answer_stream_nodone(self, handler, call):
        self.stream_head(handler)
        self.chunk(handler, self.SSE[1])
        handler.wfile.write(b"0\r\n\r\n")

    def answer_stream_cut(self, handler, call):
        """A stream that breaks off: its connection closes inside the chunks."""
        self.stream_head(handler)
        self.chunk(handler, self.SSE[1])
        handler.wfile.flush()
        handler.connection.shutdown(socket.SHUT_RDWR)

    def answer_whole_ok(self, handler, call):
        self.json_answer(handler, 200, self.WHOLE, extra=[("Cache-Control", "no-store")])

    def answer_whole_close(self, handler, call):
        """No length and no chunks: the answer ends when the connection closes."""
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(self.WHOLE)

    def answer_refuse_400(self, handler, call):
        self.json_answer(handler, 400, b'{"error":{"message":"the context is too long","code":"context_length_exceeded"}}')

    answer_refuse_400_s = answer_refuse_400

    def answer_fail_500(self, handler, call):
        self.json_answer(handler, 500, b"internal words that name the provider", kind="text/plain")

    answer_fail_500_s = answer_fail_500
    answer_row_500 = answer_fail_500
    answer_row_500_s = answer_fail_500

    def answer_slow_500(self, handler, call):
        """A row that fails only after a client has been told a stream is open."""
        time.sleep(Keepalive.HEAD_HELD_BACK + 2.5)
        self.answer_fail_500(handler, call)

    def answer_embed_model(self, handler, call):
        self.json_answer(handler, 200, json.dumps({"object": "list", "data": [{"embedding": [0.5, 1.5]}], "model": "real",
                                                   "usage": {"prompt_tokens": 4, "total_tokens": 4}}).encode())

    def answer_ear_hears(self, handler, call):
        self.json_answer(handler, 200, json.dumps({"text": "услышано", "language": "ru"}, ensure_ascii=False).encode())

    def answer_a_voice(self, handler, call):
        self.json_answer(handler, 200, b"RIFF\x24\x00\x00\x00WAVE" + bytes(range(256)) * 300, kind="audio/wav")

    def answer_text_model(self, handler, call):
        self.answer_stream_ok(handler, call)
    answer_fail_twice = answer_fail_500

    def answer_spare_served(self, handler, call):
        self.answer_stream_ok(handler, call)

    def answer_both_ways(self, handler, call):
        """Asked for a stream or not, it streams: what a client that asked for one whole answer is relayed."""
        self.answer_stream_ok(handler, call)

    def answer_auth_401(self, handler, call):
        self.json_answer(handler, 401, b'{"error":{"message":"the account of someone@example.org"}}')

    def answer_busy_429(self, handler, call):
        self.json_answer(handler, 429, b'{"error":{"message":"slow down"}}')

    def answer_loading(self, handler, call):
        if call == 1:
            self.json_answer(handler, 503, b'{"error":{"message":"Loading model","type":"unavailable_error"}}')
        else:
            self.json_answer(handler, 200, self.WHOLE)

    def answer_hold(self, handler, call):
        """Answers when the scenario lets it."""
        self.release.wait(30)
        self.json_answer(handler, 200, self.WHOLE)

    answer_hold_gone = answer_hold
    answer_hold_busy = answer_hold
    answer_hold_limit = answer_hold
    answer_hold_limit_s = answer_hold

    def answer_hold_stream(self, handler, call):
        """Sends one event, then waits: for the scenario, or for its client to leave, which it notes."""
        self.stream_head(handler)
        self.chunk(handler, self.SSE[1])
        handler.connection.settimeout(0.1)
        deadline = time.time() + 30
        while time.time() < deadline and not self.release.is_set():
            try:
                if handler.connection.recv(1) == b"":
                    self.saw_client_leave.set()
                    return
            except TimeoutError:
                continue
            except OSError:
                self.saw_client_leave.set()
                return
        try:
            self.chunk(handler, self.SSE[3])
            handler.wfile.write(b"0\r\n\r\n")
        except OSError:
            self.saw_client_leave.set()

    answer_hold_left = answer_hold_stream

    def answer_hold_stopped(self, handler, call):
        """Keeps talking until its client goes: the Python looks for a stop between chunks and not while a model is silent."""
        self.stream_head(handler)
        deadline = time.time() + 20
        try:
            while time.time() < deadline:
                self.chunk(handler, self.SSE[1])
                time.sleep(0.1)
        except OSError:
            self.saw_client_leave.set()

    def answer_silent_a_while(self, handler, call):
        """One event, a silence longer than a keepalive's turn, the end."""
        self.stream_head(handler)
        self.chunk(handler, self.SSE[1])
        time.sleep(Keepalive.SILENCE)
        self.chunk(handler, self.SSE[3])
        handler.wfile.write(b"0\r\n\r\n")


class Client:
    """A client that reads an answer to its last byte, on a raw socket: what it sees is what was sent."""

    @staticmethod
    def request_bytes(method, path, headers, body):
        head = f"{method} {path} HTTP/1.1\r\nHost: entry\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        if body is not None and not any(k.lower() in ("content-length", "transfer-encoding") for k in headers):
            head += f"Content-Length: {len(body)}\r\n"
        return head.encode() + b"\r\n" + (body or b"")

    @staticmethod
    def read_all(sock, timeout=20):
        sock.settimeout(timeout)
        data = bytearray()
        while True:
            try:
                piece = sock.recv(65536)
            except OSError:
                break
            if not piece:
                break
            data += piece
        return bytes(data)

    @classmethod
    def ask(cls, port, method, path, headers=None, body=None, timeout=35):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(cls.request_bytes(method, path, headers or {}, body))
            return Answer.parse(cls.read_all(sock, timeout))


class Answer:
    """An answer's status, fields and body. Interim answers (`100 Continue`) are counted apart."""

    def __init__(self, status, fields, body, interim=0):
        self.status = status
        self.fields = fields
        self.body = body
        self.interim = interim

    @classmethod
    def parse(cls, raw):
        interim = 0
        while raw.startswith(b"HTTP/1.1 100"):
            raw = raw.split(b"\r\n\r\n", 1)[1]
            interim += 1
        head, _, body = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        status = int(lines[0].split()[1]) if lines[0].startswith("HTTP/") else 0
        fields = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            fields[name.strip().lower()] = value.strip()
        return cls(status, fields, body, interim)


class Differences:
    """Where the two sides may differ, once, each with its reason."""

    #: Fields of a reply compared. `Server` and `Date` say who and when; the request id is only there or not.
    REPLY_FIELDS = ("content-type", "cache-control", "x-accel-buffering", "connection", "retry-after", "x-should-retry",
                    "x-provider-secret", "x-agent-proxy-chain")
    #: Fields of the request to the model compared. The request id and the length are checked apart: an id differs by nature, and a
    #: rewritten body is the same JSON with other spaces. `Expect` is left out: the Python passes a client's on to the model with the
    #: body already behind it, where nobody waits for the answer; the program does not.
    MODEL_FIELDS = ("host", "accept-encoding", "content-type", "connection", "x-agent-proxy", "x-forwarded-for", "authorization",
                    "x-api-key", "x-client-note", "x-real-ip", "transfer-encoding", "chatgpt-account-id", "originator", "openai-beta",
                    "accept", "anthropic-version", "user-agent", "x-forwarded-proto")
    #: A finished record's fields that differ by nature: identity and time.
    VOLATILE = ("id", "startedAt", "finishedAt", "durationMs", "proxy")
    #: The words of a socket's failure are the language's own ("[Errno 111] Connection refused" against "Connection refused (os
    #: error 111)"); the kind is what the board branches on, and it is compared.
    FREE_WORDS = ("proxy_error", "upstream_disconnected", "upstream_timeout", "stopped")
    #: Rows that only one side writes, and that say nothing of the request: when a waiting stream was kept alive, and the pool's
    #: choice of a row, which a pool of one row makes once per process.
    QUIET_EVENTS = ("queue_keepalive", "pool_switch")
    #: The running record's fields the board draws a request by, as they stand when it goes to its model.
    RUNNING = ("method", "path", "client", "route", "port", "upstream", "upstreamType", "providerId", "routedOutputId", "routedOutputName",
               "phase", "cloudPoolId", "poolStepId", "priority", "bytes", "chunks")
    #: A wait this long in milliseconds is a wait; below it is the scheduler's noise, and the two sides differ by nature.
    WAITED_MS = 100

    #: A journal row's fields that are no word of the row itself: when, who wrote it, whose it is, what else was running then. What
    #: was running is the record's, compared apart. Decided by the owner 2026-11-02: the program's row no longer carries `active` at all
    #: (half of a row's weight, read by nobody); the kept answers still carry it, so the field stays out of the comparison.
    ROW_VOLATILE = ("time", "timeIso", "requestId", "item", "active", "queue", "proxy")
    #: Decided: a `queued` row's copy of the whole policy is read by nobody (the slim view of the journal drops it, and the board never
    #: asks), so the program's row leaves it out.
    ROW_LEFT_OUT = {"queued": ("policy",),
                    # Decided: the Python's line says less than its own record when a stream breaks off, and every panel reads the record.
                    # The program's line says what its record says; the record is compared.
                    "finished": ("error", "errorKind"),
                    # By nature: the words of a closed socket are the language's own, as in FREE_WORDS; that the row is written is compared.
                    "upstream_reconnect": ("error",)}

    @classmethod
    def event_row(cls, row):
        left_out = cls.ROW_VOLATILE + cls.ROW_LEFT_OUT.get(row["event"], ())
        out = {key: value for key, value in row.items() if key not in left_out}
        said = out.get("upstreamErrorBody")
        if isinstance(said, str) and said.startswith("upstream connect failed:"):
            out["upstreamErrorBody"] = "upstream connect failed: words of the socket"
        elif isinstance(said, str):
            # A pool's refusal says when its rows were read and when they reset, by each side's own clock.
            out["upstreamErrorBody"] = re.sub(r'"(readAt|resetAt|resets_at)": [0-9.]+', r'"\1": "a moment"', said)
        if row["event"] == "machine_entry_spare":
            out["error"] = bool(out.get("error"))
        out.pop("elapsedSec", None)
        if "queuedMs" in out:
            out["queuedMs"] = int(out["queuedMs"] or 0) >= cls.WAITED_MS
        if isinstance(out.get("cloudHeaders"), dict) and "Content-Length" in out["cloudHeaders"]:
            # A rewritten body is the same JSON with other spaces: its length is checked where it arrives.
            out["cloudHeaders"] = {**out["cloudHeaders"], "Content-Length": True}
        return out

    @classmethod
    def record(cls, item):
        out = {key: value for key, value in item.items() if key not in cls.VOLATILE}
        out["firstByteMs"] = item.get("firstByteMs") is not None
        out["latency"] = {key: value is not None for key, value in (item.get("latency") or {}).items()}
        queue = item.get("queue") or {}
        out["queue"] = {"waited": int(queue.get("queuedMs") or 0) >= cls.WAITED_MS, "preempted": queue.get("preempted")}
        if int(item.get("status") or 0) >= 400:
            # A refusal the caravan words itself is the same JSON with other spaces.
            out["bytes"] = int(item.get("bytes") or 0) > 0
        if item.get("errorKind") in cls.FREE_WORDS:
            out["error"] = bool(item.get("error"))
        # An answer the caravan wrote out of a provider's: its id is random.
        if str((item.get("response") or {}).get("id") or "").startswith("chatcmpl-"):
            out["response"] = {key: value for key, value in item["response"].items() if key != "id"}
        return out


class Data:
    """The temporary data folder: the settings both proxies read, and the journal both write."""

    def __init__(self, machine, entry_port, spare_machine, tls_origins):
        self.folder = Path(tempfile.mkdtemp(prefix="caravan-conformance-")).resolve()
        self.closed_ports = []
        for name in ("config", "state", "secrets", "logs/proxy-events"):
            (self.folder / name).mkdir(parents=True)
        self.machine = machine
        self.entry_port = entry_port
        self.spare = spare_machine
        self.policy = {"maxSlots": 1, "queueLimitSec": 0, "queueYieldSec": 0, "loadingModelWaitSec": 30, "stickySlotSec": 0}
        self.stops = []
        #: The routes of one check beside the fixed ones, as the model list's questions need them.
        self.extra_routes = []
        #: The accounts whose provider speaks TLS, each at its address.
        self.tls_origins = tls_origins
        #: The rows of the pool `check_pool_watch` edits, in their order.
        self.pool_watched_rows = ("first", "second")
        self.write_cloud()
        self.write_settings()

    MODELS = ("stream-ok", "stream-split", "stream-nodone", "stream-cut", "whole-ok", "whole-close", "refuse-400", "refuse-400-s", "fail-500",
              "fail-500-s", "auth-401", "busy-429", "loading", "hold", "hold-stream", "hold-limit", "hold-limit-s", "hold-left", "hold-stopped", "both-ways",
              "silent-a-while", "fail-twice", "hold-gone", "text-model", "row-500", "row-500-s", "slow-500", "hold-busy")

    def closed_port(self):
        """A port nothing listens on, and nothing will: drawn, and never bound."""
        self.closed_ports.append(free_port())
        return self.closed_ports[-1]

    def output(self, name, **over):
        return {"id": f"mm:{name}", "upstreamType": "machine", "upstreamModel": name, "name": name, "hostId": "box",
                "upstreamHost": "127.0.0.1", "upstreamPort": self.machine.port, "copyPorts": [self.machine.port], "jobs": ["llm"],
                **over}

    def outputs(self):
        return [self.output(name) for name in self.MODELS] + [
            # The machine's entry is down; a running copy on its own port serves.
            self.output("spare-served", upstreamPort=self.closed_port(), copyPorts=[self.spare.port]),
            # The machine's entry is down, and so are its copies.
            self.output("nobody-home", upstreamPort=self.closed_port(), copyPorts=[self.closed_port()]),
            self.output("nobody-home-s", upstreamPort=self.closed_port(), copyPorts=[self.closed_port()]),
            # A pool's row that goes the same way: rows of their own, a row that failed is doubted for minutes.
            self.output("row-down", upstreamPort=self.closed_port(), copyPorts=[self.closed_port()]),
            self.output("row-down-s", upstreamPort=self.closed_port(), copyPorts=[self.closed_port()]),
            self.output("row-down-last", upstreamPort=self.closed_port(), copyPorts=[self.closed_port()]),
            # What no client can have.
            self.output("stopped-now", copyPorts=[]),
            self.output("stopped-held", stopped=True),
            self.output("an-ear", jobs=["asr"]),
            self.output("ear-hears", jobs=["asr"]),
            self.output("embed-model", jobs=["embed"]),
            self.output("a-voice", jobs=["tts"]),
            self.output("closed-one"),
        ]

    def settings(self):
        routes = [
            {"label": "client", "port": 23201, "kind": "consumer", "apiKey": KEY, "portClosed": True, "enabled": True, "upstreamType": "cloud"},
            {"label": "denied", "port": 23202, "kind": "consumer", "apiKey": DENIED_KEY, "portClosed": True, "enabled": True,
             "upstreamType": "cloud", "deny": ["model:mm:closed-one"]},
            {"label": "held", "port": 23203, "kind": "consumer", "apiKey": PAUSED_KEY, "portClosed": True, "enabled": True,
             "upstreamType": "cloud", "mode": "paused"},
            {"label": "off the list", "port": 23204, "kind": "consumer", "apiKey": OFF_LIST_KEY, "portClosed": True, "enabled": True,
             "upstreamType": "cloud"},
            {"label": "one of two", "port": 23205, "kind": "consumer", "apiKey": SHARED_KEY, "portClosed": True, "enabled": True, "upstreamType": "cloud"},
            {"label": "the other of two", "port": 23206, "kind": "consumer", "apiKey": SHARED_KEY, "portClosed": True, "enabled": True, "upstreamType": "cloud"},
        ] + self.extra_routes
        routers = [{"id": "router:default", "name": "r", "outputs": self.fixed_outputs}]
        return {"routes": routes, "policy": self.policy, "routers": routers, "entry": {"port": self.entry_port}, "stopRequests": self.stops}

    def write_settings(self):
        if not hasattr(self, "fixed_outputs"):
            self.fixed_outputs = self.outputs()
        path = self.folder / "config" / "agent-proxies.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings()), encoding="utf-8")
        tmp.replace(path)

    #: Each account of the scenarios, each under its own limits: a refusal rests an account for minutes, in each side's memory.
    ACCOUNTS = ("fake-provider", "limit-429", "limit-all", "limit-401", "limit-402", "down-500", "refuses-400", "keeps-it", "drops-it", "plain-kept", "dead-provider", "no-such-model")

    @staticmethod
    def token_for(claim):
        """A sign-in's token, its signature never read."""
        payload = json.dumps({"https://api.openai.com/auth": {"chatgpt_account_id": claim}}).encode()
        return "head." + base64.urlsafe_b64encode(payload).decode().rstrip("=") + ".signature"

    def write_cloud(self):
        row = lambda id_, **said: {"id": id_, **said}
        account_row = lambda id_, account, model: row(id_, accountId=account, model=model)
        origin = f"http://127.0.0.1:{self.machine.port}"
        key_account = lambda id_: {"id": id_, "name": id_, "type": "custom", "baseUrl": f"{origin}/provider/v1", "authMode": "apiKey"}
        subscription = lambda id_: {"id": id_, "name": id_, "type": "openai-subscription", "accountType": "openai-subscription", "baseUrl": f"{origin}/backend-api", "authMode": "oauth"}
        accounts = [key_account(id_) for id_ in self.ACCOUNTS if id_ != "dead-provider"]
        accounts += [{"id": "signed-out", "name": "out", "type": "custom", "baseUrl": f"{origin}/provider/v1", "authMode": "apiKey"},
                     {"id": "dead-provider", "name": "dead", "type": "custom", "baseUrl": f"http://127.0.0.1:{self.closed_port()}/v1", "authMode": "apiKey"},
                     {"id": "anthropic-key", "name": "anth", "type": "anthropic", "baseUrl": f"{origin}/provider/v1", "authMode": "apiKey"},
                     {"id": "openai-key", "name": "open", "type": "openai", "baseUrl": f"{origin}/provider/v1", "authMode": "apiKey"},
                     subscription("sub-plenty"), subscription("sub-low"), subscription("sub-giving-way"), subscription("sub-limit"), subscription("sub-rising"), subscription("sub-renews")]
        accounts[-1]["oauthConfig"] = {"tokenUrl": f"{origin}/oauth/token", "clientId": "the-app"}
        accounts += [{"id": id_, "name": id_, "type": "custom", "baseUrl": f"{there}/provider/v1", "authMode": "apiKey"} for id_, there in self.tls_origins.items()]
        one = lambda id_, *rows: {"id": id_, "name": id_.replace("-", " "), "steps": list(rows)}
        on_machine = lambda id_, model: row(id_, output=f"mm:{model}")
        pools = [
            {"id": "pool-one", "name": "pool-one", "steps": [on_machine("r1", "whole-ok")]},
            one("pool-two", on_machine("first", "whole-ok"), on_machine("second", "stream-ok")),
            one("pool-stream", on_machine("first", "stream-ok"), on_machine("second", "whole-ok")),
            one("pool-refuses", on_machine("first", "refuse-400"), on_machine("second", "whole-ok")),
            one("pool-past", row("off", output="mm:stream-ok", enabled=False), row("open"), on_machine("gone", "nothing-here"), on_machine("held", "stopped-held"),
                account_row("out", "signed-out", "m"), on_machine("serves", "whole-ok")),
            one("pool-down", on_machine("first", "row-down"), on_machine("second", "whole-ok")),
            one("pool-down-s", on_machine("first", "row-down-s"), on_machine("second", "stream-ok")),
            one("pool-500", on_machine("first", "row-500"), on_machine("second", "whole-ok")),
            one("pool-500-s", on_machine("first", "row-500-s"), on_machine("second", "stream-ok")),
            one("pool-slow", on_machine("first", "slow-500"), on_machine("second", "stream-ok")),
            one("pool-cloud", account_row("first", "fake-provider", "key-ok"), on_machine("second", "stream-ok")),
            one("pool-after-cloud", on_machine("first", "whole-ok"), account_row("second", "fake-provider", "key-ok")),
            one("pool-busy", on_machine("first", "hold-busy"), on_machine("second", "whole-ok")),
            one("pool-last-down", on_machine("first", "row-down-last"), row("off", output="mm:whole-ok", enabled=False)),
            one("pool-context", on_machine("first", "whole-ok"), on_machine("second", "stream-ok")),
            # A provider's rows.
            one("key-whole", account_row("r1", "fake-provider", "key-ok")),
            one("key-stream", account_row("r1", "fake-provider", "key-stream")),
            one("key-refuses", account_row("r1", "refuses-400", "key-400"), account_row("r2", "fake-provider", "key-ok")),
            one("key-limit", account_row("r1", "limit-429", "key-429"), account_row("r2", "fake-provider", "key-ok")),
            one("key-limit-only", account_row("r1", "limit-all", "key-429")),
            one("key-sign-in", account_row("r1", "limit-401", "key-401"), account_row("r2", "fake-provider", "key-ok")),
            one("key-money", account_row("r1", "limit-402", "key-402"), on_machine("r2", "whole-ok")),
            one("key-fails", account_row("r1", "down-500", "key-500"), account_row("r2", "fake-provider", "key-ok")),
            one("key-fails-only", account_row("r1", "down-500", "key-500")),
            one("key-dead", account_row("r1", "dead-provider", "x"), account_row("r2", "fake-provider", "key-ok")),
            one("key-dead-only", account_row("r1", "dead-provider", "x")),
            one("key-keeps", account_row("r1", "keeps-it", "key-keeps")),
            one("key-drops", account_row("r1", "drops-it", "key-drops")),
            one("key-not-listed", account_row("r1", "no-such-model", "not-on-its-list"), account_row("r2", "fake-provider", "key-ok")),
            one("key-closed", account_row("r1", "fake-provider", "closed-model"), account_row("r2", "fake-provider", "key-ok")),
            one("key-closed-only", account_row("r1", "fake-provider", "closed-model")),
            one("anthropic", account_row("r1", "anthropic-key", "anth-ok")),
            one("anthropic-cut", account_row("r1", "anthropic-key", "anth-cut")),
            one("openai-responses", account_row("r1", "openai-key", "key-ok")),
            one("key-responses", account_row("r1", "fake-provider", "key-ok")),
            one("subscription", account_row("r1", "sub-plenty", "sub-ok")),
            one("subscription-tools", account_row("r1", "sub-plenty", "sub-tools")),
            one("subscription-cut", account_row("r1", "sub-plenty", "sub-cut")),
            one("subscription-effort", account_row("r1", "sub-plenty", "sub-effort")),
            one("subscription-low", account_row("r1", "sub-low", "sub-low-model"), account_row("r2", "fake-provider", "key-ok")),
            one("subscription-rising", account_row("r1", "sub-rising", "sub-low-model"), account_row("r2", "fake-provider", "key-ok")),
            one("subscription-low-only", account_row("r1", "sub-low", "sub-low-model")),
            one("subscription-gives-way", account_row("r1", "sub-giving-way", "sub-giving-way"), account_row("r2", "fake-provider", "key-ok")),
            one("subscription-way-of-none", account_row("r1", "sub-giving-way", "sub-giving-way")),
            one("subscription-limit", account_row("r1", "sub-limit", "sub-429"), account_row("r2", "fake-provider", "key-ok")),
            one("subscription-renews", account_row("r1", "sub-renews", "sub-ok")),
            one("recording-to-a-subscription", account_row("r1", "sub-plenty", "sub-ok")),
            {"id": "the-pool-nobody-edited", "name": "nobody edits it", "steps": [on_machine("r1", "whole-ok")]},
            {"id": "watched", "name": "watched", "steps": [on_machine(name, "whole-ok") for name in self.pool_watched_rows]},
        ]
        pools += [one("over-tls", account_row("r1", "over-tls", "key-ok")), one("over-tls-streams", account_row("r1", "over-tls", "key-stream")),
                  one("over-tls-keeps", account_row("r1", "over-tls-kept", "key-keeps")), one("over-tls-a-stranger", account_row("r1", "tls-stranger", "key-ok")),
                  one("over-tls-another-name", account_row("r1", "tls-another-name", "key-ok")), one("plain-keeps", account_row("r1", "plain-kept", "key-keeps"))]
        cloud = {"accounts": accounts, "pools": pools, "schedules": {"acc:fake-provider/closed-model": {"enabled": True, "windows": []}},
                 "levels": {"sub-giving-way": {"sub-giving-way": {"stopAt": {"18000": 5}, "switchAt": {"18000": 30}}}}}
        (self.folder / "config" / "cloud-providers.json").write_text(json.dumps(cloud), encoding="utf-8")
        (self.folder / "state" / "model-catalog.json").write_text(json.dumps({"accounts": {"no-such-model": {"models": [{"id": "another-one"}]}}}), encoding="utf-8")
        self.write_secrets()

    def write_secrets(self, renewing=False):
        """A key for each account of a key, and for each subscription a sign-in whose token names it; `renewing`: the one that renews is near its end."""
        secrets = {id_: {"apiKey": f"a-key-of-{id_}"} for id_ in self.ACCOUNTS}
        secrets["anthropic-key"] = {"apiKey": "a-key-of-anthropic"}
        secrets["openai-key"] = {"apiKey": "a-key-of-openai"}
        secrets.update({id_: {"apiKey": f"a-key-of-{id_}"} for id_ in self.tls_origins})
        for account, claim in (("sub-plenty", "plenty"), ("sub-low", "low"), ("sub-giving-way", "giving-way"), ("sub-limit", "limited"), ("sub-renews", "renewed"), ("sub-rising", "rising")):
            secrets[account] = {"oauth": {"accessToken": self.token_for(claim), "refreshToken": "a-refresh-token", "expiresAt": int(time.time()) + 90_000}}
        if renewing:
            secrets["sub-renews"]["oauth"].update(accessToken=self.token_for("spent"), expiresAt=int(time.time()) + 10)
        path = self.folder / "secrets" / "provider-secrets.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(secrets), encoding="utf-8")
        tmp.replace(path)

    def journal_rows(self):
        rows = []
        for path in sorted((self.folder / "logs" / "proxy-events").glob("*.jsonl")):
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    rows.append(json.loads(line))
        return rows


class Door:
    """The way in: the entry's port."""

    def __init__(self, port):
        self.port = port


class Observed:
    """What one scenario came to through one door, with what differs by nature taken out."""

    def __init__(self, answer, asked, rows, machine):
        self.status = answer.status if answer else None
        self.fields = {name: (answer.fields.get(name) if answer else None) for name in Differences.REPLY_FIELDS}
        self.has_id = bool(answer and "x-request-id" in answer.fields)
        self.interim = answer.interim if answer else 0
        self.body = self.body_words(answer) if answer else None
        self.keepalives = answer.body.count(b"chatcmpl-keepalive") if answer else 0
        self.asked = [self.asked_words(one) for one in asked]
        self.events = [row["event"] for row in rows if row["event"] not in Differences.QUIET_EVENTS]
        self.event_rows = [Differences.event_row(row) for row in rows if row["event"] not in Differences.QUIET_EVENTS]
        self.running = [{name: (row.get("item") or {}).get(name) for name in Differences.RUNNING}
                        for row in rows if row["event"] in ("received", "upstream_started")]
        finished = [row for row in rows if row["event"] in ("finished", "blocked")]
        self.records = [Differences.record(row.get("item") or {}) for row in finished]
        self.wrote = sorted({row.get("proxy") or "nobody's" for row in rows})
        self.rows = rows
        self.machine = machine

    @staticmethod
    def own_words(answer):
        """An answer the caravan wrote out of a provider's: its id is a random one and its `created` the time."""
        if isinstance(answer, dict) and str(answer.get("id") or "").startswith("chatcmpl-"):
            return {key: value for key, value in answer.items() if key not in ("id", "created")}
        return answer

    @staticmethod
    def body_words(answer):
        kind = answer.fields.get("content-type") or ""
        if kind.startswith("application/json"):
            try:
                return Observed.own_words(json.loads(answer.body))
            except ValueError:
                return answer.body
        if kind.startswith("text/event-stream"):
            return [Observed.frame_words(frame) for frame in answer.body.split(b"\n\n") if b"chatcmpl-keepalive" not in frame]
        return answer.body

    @staticmethod
    def frame_words(frame):
        """An event as its lines: the JSON of one the caravan wrote itself by its fields, a relayed one by its bytes."""
        if frame.startswith(b"event: error"):
            head, _, data = frame.partition(b"\ndata: ")
            return [head, json.loads(data)]
        if frame.startswith(b'data: {"id":"chatcmpl-'):
            return [b"a chunk the caravan wrote", Observed.own_words(json.loads(frame[len(b"data: "):]))]
        return frame

    @staticmethod
    def asked_words(one):
        fields = {name: one["headers"].get(name) for name in Differences.MODEL_FIELDS}
        fields["has-id"] = "x-agent-proxy-request-id" in one["headers"]
        fields["x-forwarded-for-fields"] = one["forwarded"]
        if "multipart" in (one["headers"].get("content-type") or ""):
            fields["the-form-as-it-came"] = hashlib.sha256(one["raw"]).hexdigest()
        length = one["headers"].get("content-length")
        fields["length-is-the-body's"] = length == str(len(one["raw"]))
        fields["anything-of-the-home"] = sorted(name for name in one["headers"] if name in ("x-forwarded-for", "x-real-ip", "x-forwarded-proto") and one["is_provider"])
        return {"path": one["path"], "fields": fields, "body": one["body"]}

    def compared(self):
        return {"status": self.status, "fields": self.fields, "has_id": self.has_id, "interim": self.interim, "body": self.body,
                "asked": self.asked, "events": self.events, "event_rows": self.event_rows, "records": self.records, "running": self.running}


class Canon:
    """A side's words as a file can keep them: bytes as text, and only what JSON has. A text this long is kept as its sum."""

    LONG = 64 * 1024

    @classmethod
    def of(cls, value):
        if isinstance(value, (bytes, bytearray)):
            return {"bytes": cls.of(bytes(value).decode("utf-8", "backslashreplace"))}
        if isinstance(value, str) and len(value) > cls.LONG:
            return {"sha256": hashlib.sha256(value.encode("utf-8", "backslashreplace")).hexdigest(), "characters": len(value)}
        if isinstance(value, dict):
            return {str(key): cls.of(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls.of(item) for item in value]
        return value


class Harness:
    """The processes, and the walk of the scenarios."""

    def __init__(self, binary, writing=False):
        self.binary = binary
        self.machine = FakeMachine(slots={"hold": 1, "hold-gone": 1, "hold-limit": 1, "hold-limit-s": 1, "hold-busy": 1})
        self.spare = FakeMachine()
        self.certificates = Certificates()
        self.over_tls = FakeMachine(tls=self.certificates.server_side("trusted"))
        self.stranger = FakeMachine(tls=self.certificates.server_side("stranger"))
        self.entry_port = free_port()
        tls_origins = {"over-tls": f"https://localhost:{self.over_tls.port}", "over-tls-kept": f"https://localhost:{self.over_tls.port}",
                       "tls-stranger": f"https://localhost:{self.stranger.port}", "tls-another-name": f"https://127.0.0.1:{self.over_tls.port}"}
        self.data = Data(self.machine, self.entry_port, self.spare, tls_origins)
        self.processes = []
        self.failures = []
        self.compared = 0
        self.frozen = FrozenAnswers("proxy", writing=writing)
        self.own = OwnWords({self.data.folder: "<data>", ROOT: "<repo>"}, {self.machine.port: "<machine>", self.spare.port: "<spare>", self.over_tls.port: "<tls>", self.stranger.port: "<stranger>", self.entry_port: "<entry>"})

    def env(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith(("AGENT_PROXY_", "CARAVAN_", "CLOUD_"))}
        env.update({"CARAVAN_DATA_DIR": str(self.data.folder), "AGENT_PROXY_HOST": "127.0.0.1",
                    "CARAVAN_RUST_ENTRY_PORT": str(self.entry_port), "TZ": "UTC", "SSL_CERT_FILE": str(self.certificates.authority)})
        return env

    def start(self):
        log = open(self.data.folder / "processes.log", "ab")
        # A copy: a new version comes as another file over this one, as on the machine that runs it.
        self.program = self.data.folder / "bin" / "caravan-proxy"
        self.program.parent.mkdir()
        shutil.copy2(self.binary, self.program)
        self.processes.append(subprocess.Popen([str(self.program)], env=self.env(), stdout=log, stderr=log, cwd=str(self.data.folder)))
        log.close()
        self.wait_port(self.entry_port)

    def wait_port(self, port):
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError(f"nothing listens on {port}: {(self.data.folder / 'processes.log').read_text(errors='replace')[-2000:]}")

    def stop(self):
        for process in self.processes:
            process.send_signal(signal.SIGTERM)
        for process in self.processes:
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()

    def door(self):
        return Door(self.entry_port)

    def rows_since(self, seen, ended=None):
        """The journal's rows after the first `seen`, once the request's last row is in."""
        deadline = time.time() + 8
        rows = []
        while time.time() < deadline:
            rows = self.data.journal_rows()[seen:]
            if any(row["event"] in ("finished", "blocked") for row in rows) and (ended is None or ended(rows)):
                return rows
            time.sleep(0.03)
        return rows

    def settle(self):
        """Lets the finished request's connection go, so the next one starts on a quiet model."""
        time.sleep(0.03)

    def run_through(self, scenario, door):
        heard_by = (self.machine, self.spare, self.over_tls, self.stranger)
        for machine in heard_by:
            machine.forget()
        seen = len(self.data.journal_rows())
        answer, ended = scenario.drive(self, door)
        rows = self.rows_since(seen, ended)
        asked = []
        for machine in heard_by:
            with machine.lock:
                asked += machine.asked
        self.settle()
        return Observed(answer, asked, rows, self.machine)

    def keep(self, key, value):
        """What is kept for `key`, and what it said now, both in the words of no run."""
        for port in self.data.closed_ports:
            self.own.name_port(port, "<closed port>")
        now = self.own.clean(Canon.of(value))
        return self.frozen.said(key, now), now

    def compare(self, scenario):
        side = self.run_through(scenario, self.door())
        self.check_who_answered(scenario, side)
        said = side.compared()
        kept, now = self.keep(scenario.name, {part: value for part, value in said.items() if part not in scenario.skipped()})
        if kept is FrozenAnswers.NOTHING:
            self.failures.append(f"{scenario.name}: no answer is kept for it, and it said {str(now)[:400]}")
            return
        for part in now:
            self.compared += 1
            left, right = kept.get(part), now[part]
            if part in scenario.any_order:
                left, right = sorted(left), sorted(right)
            if left != right:
                self.failures.append(f"{scenario.name}: {part}\n    kept {left!r}\n    said {right!r}")
        for problem in scenario.check(side):
            self.failures.append(f"{scenario.name}: {problem}")

    def check_who_answered(self, scenario, side):
        self.compared += 1
        if side.wrote not in (["rust"], ["nobody's"], []):
            self.failures.append(f"{scenario.name}: the rows were written by {side.wrote}")


class Scenario:
    """One request, as a client sends it."""

    def __init__(self, name, model=None, stream=False, key=KEY, method="POST", path="/v1/chat/completions",
                 body=None, headers=None, check=None, differs=(), any_order=()):
        self.name = name
        self.model = model
        self.stream = stream
        self.key = key
        self.method = method
        self.path = path
        self.body = body
        self.headers = headers or {}
        self.checker = check
        #: What is not kept here, by a decision written where the scenario stands; its `check` says what the program must do instead.
        self.differs = differs
        #: What is compared whatever its order: two requests at once, and the scheduler says whose row falls first.
        self.any_order = any_order

    def request_body(self):
        if self.body is not None:
            return self.body
        if self.method != "POST" or self.model is None:
            return None
        return json.dumps({"model": self.model, "stream": self.stream,
                           "messages": [{"role": "user", "content": "привет, модель"}]}).encode()

    def request_headers(self):
        fields = {"Content-Type": "application/json", "X-Forwarded-For": "10.1.2.3", "X-Real-IP": "10.1.2.3", "X-Client-Note": "kept",
                  **self.headers}
        if self.key:
            fields["Authorization"] = f"Bearer {self.key}"
        return fields

    def drive(self, harness, door):
        return Client.ask(door.port, self.method, self.path, self.request_headers(), self.request_body()), None

    def skipped(self):
        """The parts not compared. A row's words go with the rows when those are not kept in their order."""
        return (*self.differs, *(("event_rows",) if "events" in self.differs or "events" in self.any_order else ()))

    def check(self, side):
        return self.checker(side) if self.checker else []


class ClientLeaves(Scenario):
    """The client hangs up in the middle of a stream: the upstream's socket goes too, so the cell stops generating into the void."""

    def drive(self, harness, door):
        with socket.create_connection(("127.0.0.1", door.port), timeout=5) as sock:
            sock.sendall(Client.request_bytes("POST", self.path, self.request_headers(), self.request_body()))
            sock.settimeout(10)
            seen = b""
            while "Привет".encode() not in seen:
                piece = sock.recv(4096)
                if not piece:
                    break
                seen += piece
        harness.machine.saw_client_leave.wait(6)
        self.left = harness.machine.saw_client_leave.is_set()
        return None, None

    def check(self, side):
        return [] if self.left else ["the model's socket stayed open after the client left"]


class Queued(Scenario):
    """Two requests for a model of one place: the second waits for the first, and says it did."""

    def drive(self, harness, door):
        answers = []
        def ask():
            answers.append(Client.ask(door.port, "POST", self.path, self.request_headers(), self.request_body(), timeout=20))
        first = threading.Thread(target=ask)
        first.start()
        deadline = time.time() + 5
        while time.time() < deadline and not harness.machine.asked:
            time.sleep(0.01)
        second = threading.Thread(target=ask)
        second.start()
        time.sleep(0.6)
        harness.machine.release.set()
        first.join(20)
        second.join(20)
        return answers[-1], lambda rows: sum(row["event"] == "finished" for row in rows) >= 2


class BusyRow(Scenario):
    """A pool whose first row is full: another client's request holds its one place, and the request goes on to the next row at once."""

    POOL = "pool busy"

    def drive(self, harness, door):
        answers = []
        holder = threading.Thread(target=lambda: Client.ask(door.port, "POST", self.path, self.request_headers(), self.request_body(), timeout=20))
        holder.start()
        deadline = time.time() + 5
        while time.time() < deadline and not harness.machine.asked:
            time.sleep(0.01)
        body = json.dumps({"model": self.POOL, "messages": []}).encode()
        second = threading.Thread(target=lambda: answers.append(Client.ask(door.port, "POST", self.path, self.request_headers(), body, timeout=20)))
        second.start()
        time.sleep(0.6)
        harness.machine.release.set()
        holder.join(20)
        second.join(20)
        return answers[-1], lambda rows: sum(row["event"] == "finished" for row in rows) >= 2


class KeptConnection(Scenario):
    """Two requests to a provider that leaves its connection open."""

    def drive(self, harness, door):
        Client.ask(door.port, self.method, self.path, self.request_headers(), self.request_body())
        time.sleep(0.3)
        second = Client.ask(door.port, self.method, self.path, self.request_headers(), self.request_body())
        return second, lambda rows: sum(row["event"] == "finished" for row in rows) >= 2


class NamedForAll(Scenario):
    """The one name every client goes to the providers under, when the operator has set one: the provider sees it, and only it."""

    def drive(self, harness, door):
        harness.data.policy["clientName"] = "stand client (linux; x64)"
        harness.data.write_settings()
        time.sleep(0.05)
        try:
            answer = Client.ask(door.port, self.method, self.path, {**self.request_headers(), "User-Agent": "its own name"}, self.request_body())
        finally:
            harness.data.policy.pop("clientName", None)
            harness.data.write_settings()
        return answer, lambda rows: any(row["event"] == "finished" for row in rows)


class KeptThenClosed(Scenario):
    """A provider that closes the connection it left open while it sat idle: the next request goes on a fresh one, and nobody is told."""

    @staticmethod
    def close_all(harness):
        for machine in (harness.machine, harness.over_tls):
            machine.close_what_it_left_open()
        time.sleep(0.3)

    def drive(self, harness, door):
        self.close_all(harness)
        Client.ask(door.port, self.method, self.path, self.request_headers(), self.request_body())
        time.sleep(0.3)
        self.close_all(harness)
        second = Client.ask(door.port, self.method, self.path, self.request_headers(), self.request_body())
        return second, lambda rows: sum(row["event"] == "finished" for row in rows) >= 2


class Renewal(Scenario):
    """A sign-in's token near its end: renewed before the request goes, and the new tokens written."""

    #: What the token's address was asked.
    seen = []

    def drive(self, harness, door):
        harness.data.write_secrets(renewing=True)
        time.sleep(0.05)
        harness.machine.renewals.clear()
        answer = Client.ask(door.port, self.method, self.path, self.request_headers(), self.request_body())
        self.seen.append(list(harness.machine.renewals))
        return answer, None


class LeavesTheLine(Scenario):
    """The client hangs up while it waits for a place: it leaves the line at once, and the model never hears of it."""

    def drive(self, harness, door):
        holder = threading.Thread(target=lambda: Client.ask(door.port, "POST", self.path, self.request_headers(),
                                                            json.dumps({"model": self.model, "messages": []}).encode()))
        holder.start()
        deadline = time.time() + 5
        while time.time() < deadline and not harness.machine.asked:
            time.sleep(0.01)
        with socket.create_connection(("127.0.0.1", door.port), timeout=5) as sock:
            sock.sendall(Client.request_bytes("POST", self.path, self.request_headers(), self.request_body()))
            time.sleep(0.5)
        time.sleep(0.8)
        harness.machine.release.set()
        holder.join(20)
        return None, lambda rows: sum(row["event"] == "finished" for row in rows) >= 2


class Twice(Scenario):
    """The same request twice: what the first taught is what the second is judged by. A model that failed is not asked again for a while, and
    an account its provider refused rests."""

    def drive(self, harness, door):
        Client.ask(door.port, self.method, self.path, self.request_headers(), self.request_body())
        second = Client.ask(door.port, self.method, self.path, self.request_headers(), self.request_body())
        return second, lambda rows: sum(row["event"] == "finished" for row in rows) >= 2


class QueueLimit(Scenario):
    """A model of one place, taken, and a limit of one second: the second request is refused, as a queue refuses."""

    def drive(self, harness, door):
        holder = {}
        harness.data.policy["queueLimitSec"] = 1
        harness.data.write_settings()
        time.sleep(0.05)
        def hold():
            holder["answer"] = Client.ask(door.port, "POST", self.path, self.request_headers(),
                                          json.dumps({"model": self.model, "messages": []}).encode(), timeout=20)
        first = threading.Thread(target=hold)
        first.start()
        deadline = time.time() + 5
        while time.time() < deadline and not harness.machine.asked:
            time.sleep(0.01)
        body = json.dumps({"model": self.model, "stream": self.stream, "messages": []}).encode()
        answer = Client.ask(door.port, "POST", self.path, self.request_headers(), body, timeout=10)
        harness.machine.release.set()
        first.join(20)
        harness.data.policy["queueLimitSec"] = 0
        harness.data.write_settings()
        return answer, lambda rows: sum(row["event"] == "finished" for row in rows) >= 2


class Stopped(Scenario):
    """The board asks a running request to stop: the stream ends with an error event and the record says `stopped`."""

    def drive(self, harness, door):
        state_file = harness.data.folder / "state" / "agent-proxy-state.json"
        answers = []
        def ask():
            answers.append(Client.ask(door.port, "POST", self.path, self.request_headers(), self.request_body(), timeout=20))
        asking = threading.Thread(target=ask)
        asking.start()
        request_id = None
        deadline = time.time() + 6
        while time.time() < deadline and not request_id:
            time.sleep(0.05)
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            active = (state.get("agents") or {}).get("23201", {}).get("active") or []
            running = [item for item in active if item.get("phase") == "streaming"]
            request_id = running[0]["id"] if running else None
        harness.data.stops = [{"id": request_id or "none", "route": "client", "reason": "stopped by the test", "requestedAt": int(time.time())}]
        harness.data.write_settings()
        asking.join(15)
        harness.machine.release.set()
        harness.data.stops = []
        harness.data.write_settings()
        return (answers[0] if answers else None), None


class Options(Scenario):
    """A request with no body and no model: only its head says anything."""

    def drive(self, harness, door):
        return Client.ask(door.port, self.method, self.path, self.request_headers(), None), None


class CutBody(Scenario):
    """A body shorter than its length, and the client's side closed: the refusal says so."""

    def drive(self, harness, door):
        with socket.create_connection(("127.0.0.1", door.port), timeout=5) as sock:
            sock.sendall(Client.request_bytes("POST", self.path, {**self.request_headers(), "Content-Length": "50"}, b'{"model"'))
            sock.shutdown(socket.SHUT_WR)
            return Answer.parse(Client.read_all(sock)), None


class ExpectContinue(Scenario):
    """A client that waits for `100 Continue` before its body."""

    def drive(self, harness, door):
        body = self.request_body()
        with socket.create_connection(("127.0.0.1", door.port), timeout=5) as sock:
            head = Client.request_bytes("POST", self.path, {**self.request_headers(), "Expect": "100-continue",
                                                            "Content-Length": str(len(body))}, None)
            sock.sendall(head)
            sock.settimeout(5)
            interim = sock.recv(64)
            if b"100" not in interim:
                return Answer(0, {}, interim), None
            sock.sendall(body)
            return Answer.parse(interim + Client.read_all(sock)), None


def no_provider_word(side):
    """Nothing of the provider behind a model reaches its client."""
    problems = []
    if side.fields.get("x-provider-secret"):
        problems.append("the provider's field reached the client")
    if "someone@example.org" in json.dumps(side.body, default=str) or "names the provider" in json.dumps(side.body, default=str):
        problems.append("the provider's words reached the client")
    return problems


def a_broken_stream_says_so(side):
    """A stream that breaks off. The proxy says what happened, in the way it says any failure once a stream is open: an error event, `[DONE]`, and the kind on the
    record. The Python's http.client read the cut as the stream's end, the defect docs/why.md calls absence drawn as normality."""
    problems = []
    record = side.records[0] if side.records else {}
    if record.get("errorKind") != "upstream_disconnected":
        problems.append(f"the record does not say the stream broke: {record.get('errorKind')!r}")
    if not any(isinstance(frame, list) and frame[0] == b"event: error" for frame in side.body or []):
        problems.append(f"the client was not told: {side.body!r}")
    return problems


def told_code(side):
    """The code of the error event a client got, wherever the event stands; None when it got none."""
    for frame in side.body or []:
        if isinstance(frame, list):
            return frame[1]["error"]["code"]
        if isinstance(frame, bytes) and b"event: error\ndata: " in frame:
            return json.loads(frame.split(b"event: error\ndata: ", 1)[1])["error"]["code"]
    return None


def said_stopped(side):
    """How much came before the stop is a matter of milliseconds; what must hold is that it stopped, that the client was told, and that the error event stands on
    its own: the Python's check fell between an event's line and its blank line, and a parser read the two as one event."""
    problems = []
    record = side.records[0] if side.records else {}
    if record.get("errorKind") != "stopped" or not record.get("error"):
        problems.append(f"the record does not say it stopped: {record.get('errorKind')!r}")
    if told_code(side) != "stopped":
        problems.append(f"the client was not told: {str(side.body)[-300:]}")
    if not any(isinstance(frame, list) for frame in side.body or []):
        problems.append(f"the error event does not stand on its own: {str(side.body)[-300:]}")
    return problems


def the_next_row_served(model):
    """The client's answer came from the pool's next row."""
    def check(side):
        problems = []
        last = side.asked[-1]["body"].get("model") if side.asked else None
        if last != model:
            problems.append(f"the last row asked was {last!r}, not {model!r}")
        if side.status != 200:
            problems.append(f"status {side.status}")
        retry = [row for row in side.rows if row["event"] == "pool_retry"]
        if not any(row.get("stepId") == "first" for row in retry):
            problems.append(f"the journal has no `pool_retry` for the failed row: {retry!r}")
        return problems
    return check


def told_a_limit(side):
    """Every row is held by a limit: the pool says so itself. How long it says to wait moves by the second."""
    return [f"{side.status} {side.fields}"] if side.status != 429 or not side.fields.get("retry-after") else []


def the_second_came_on_a_kept_connection(side):
    """The second request to a provider that keeps its connections says so in its record."""
    finished = [row["item"] for row in side.rows if row["event"] == "finished"]
    said = [(item.get("latency") or {}).get("connReused") for item in finished]
    return [] if said == [False, True] else [f"connections said {said}"]


def the_second_came_on_a_fresh_connection(side):
    """A connection its provider closed is not asked again: both requests answered, each on a connection of its own."""
    finished = [row["item"] for row in side.rows if row["event"] == "finished"]
    said = [(item["status"], (item.get("latency") or {}).get("connReused")) for item in finished]
    return [] if said == [(200, False), (200, False)] else [f"requests said {said}"]


def no_provider_heard_of_it(side):
    """A certificate that does not check out: not a byte of the request goes to that address, its key least of all, and the record says it failed."""
    problems = []
    if side.asked:
        problems.append(f"the provider was asked {side.asked!r}")
    finished = [row["item"] for row in side.rows if row["event"] == "finished"]
    kinds = [(item["status"], item["errorKind"]) for item in finished]
    if kinds != [(502, "proxy_error")]:
        problems.append(f"the record says {kinds}")
    return problems


def the_token_was_renewed(side):
    """The request went with the renewed token, and the provider's token address was asked once."""
    problems = []
    said = side.asked[-1]["fields"].get("authorization") if side.asked else None
    if said != "Bearer " + Data.token_for("renewed-now"):
        problems.append("the request went with another token")
    form = ["grant_type=refresh_token&refresh_token=a-refresh-token&client_id=the-app"]
    if Renewal.seen != [form]:
        problems.append(f"the token's address was asked {Renewal.seen}")
    return problems


def left_the_line(side):
    """Whose row falls first is the scheduler's. What must hold: the one who left named as gone, with the model not asked for it."""
    problems = []
    kinds = sorted(record.get("errorKind") or "" for record in side.records)
    if kinds != ["", "client_disconnected"]:
        problems.append(f"the two records say {kinds}")
    if len(side.asked) != 1:
        problems.append(f"the model was asked {len(side.asked)} times, not once")
    return problems


def kept_alive(side):
    """A silence past the keepalive's turn: a sign of life, none of it in what is compared."""
    return [] if side.keepalives else [f"no sign of life in {Keepalive.SILENCE} s of silence"]


def form_of(model):
    """A recording to transcribe, as a client sends one."""
    return (b'--bound\r\nContent-Disposition: form-data; name="model"\r\n\r\n' + model.encode() + b'\r\n'
            b'--bound\r\nContent-Disposition: form-data; name="file"; filename="rec.wav"\r\nContent-Type: audio/wav\r\n\r\n'
            + b"RIFF" + bytes(range(256)) * 40 + b'\r\n--bound--\r\n')


def scenarios():
    thinking = json.dumps({"model": "whole-ok", "reasoning_effort": "none", "messages": []}).encode()
    big = json.dumps({"model": "whole-ok", "messages": [{"role": "user", "content": "x" * (6 * 1024 * 1024)}]}).encode()
    return [
        Scenario("stream-ok", "stream-ok", stream=True, check=no_provider_word),
        Scenario("a-big-body", body=big),
        Scenario("stream-split-and-unended-done", "stream-split", stream=True),
        Scenario("stream-without-done", "stream-nodone", stream=True),
        Scenario("stream-breaks-off", "stream-cut", stream=True, differs=("body", "records"), check=a_broken_stream_says_so),
        Scenario("whole-ok", "whole-ok", check=no_provider_word),
        Scenario("whole-until-close", "whole-close"),
        Scenario("whole-asked-of-a-stream-model", "both-ways"),
        Scenario("stream-asked-of-a-whole-model", "whole-close", stream=True),
        Scenario("no-thinking-said-the-template-s-way", body=thinking),
        Scenario("refused-400", "refuse-400", check=no_provider_word),
        Scenario("refused-400-in-a-stream", "refuse-400-s", stream=True),
        Scenario("failed-500", "fail-500", check=no_provider_word),
        Scenario("failed-500-in-a-stream", "fail-500-s", stream=True),
        Scenario("sign-in-refused-401", "auth-401", check=no_provider_word),
        Scenario("busy-429", "busy-429"),
        Scenario("still-loading", "loading"),
        Scenario("entry-down-a-copy-serves", "spare-served", stream=True),
        Twice("a-model-that-failed-is-passed-over", "fail-twice"),
        Scenario("nobody-home", "nobody-home"),
        Scenario("nobody-home-in-a-stream", "nobody-home-s", stream=True),
        ClientLeaves("client-leaves-mid-stream", "hold-left", stream=True),
        Queued("two-for-one-place", "hold", differs=("running",), any_order=("events",)),
        LeavesTheLine("client-leaves-the-line", "hold-gone", stream=True, differs=("records", "running"), any_order=("events",), check=left_the_line),
        QueueLimit("queue-limit", "hold-limit"),
        QueueLimit("queue-limit-in-a-stream", "hold-limit-s", stream=True),
        Stopped("stopped-by-the-board", "hold-stopped", stream=True, differs=("body", "records", "status", "fields"), check=said_stopped),
        CutBody("body-cut-short", "whole-ok"),
        ExpectContinue("expect-continue", "whole-ok"),
        # A pool: its first row that may serve goes, and what it does then is what a model called by its name does.
        Scenario("a-pool-of-one-row", "pool-one"),
        Scenario("a-pool-s-first-row", "pool two", check=no_provider_word),
        Scenario("a-pool-s-first-row-in-a-stream", "pool stream", stream=True),
        Scenario("a-pool-passes-over-what-cannot-serve", "pool past"),
        Scenario("a-pool-with-a-cloud-row-after", "pool after cloud"),
        Scenario("a-pool-s-refusal-stays-the-client-s", "pool refuses", check=no_provider_word),
        Scenario("a-pool-s-refusal-in-a-stream", "pool refuses", stream=True),
        Scenario("a-pool-s-last-row-fails", "pool last down"),
        # A row that fails with nothing sent: the entry in Python takes the request on, and the client cannot tell. Both of its rows are
        # the journal's, and the failed row was asked once more there: the Python's own reading of it knows nothing of this try.
        Scenario("a-pool-s-row-is-down", "pool down", check=the_next_row_served("whole-ok")),
        Scenario("a-pool-s-row-is-down-in-a-stream", "pool down s", stream=True, check=the_next_row_served("stream-ok")),
        Scenario("a-pool-s-row-fails", "pool 500", check=the_next_row_served("whole-ok")),
        Scenario("a-pool-s-row-fails-in-a-stream", "pool 500 s", stream=True, check=the_next_row_served("stream-ok")),
        BusyRow("a-pool-s-row-is-full", "hold-busy", differs=("running",), any_order=("events",)),
        Scenario("a-response-to-go-on-from", body=json.dumps({"model": "pool context", "previous_response_id": "resp-1", "input": "x"}).encode(), path="/v1/responses"),
        # A provider's row: a key's, as it came and as it goes.
        Scenario("a-key-s-answer-whole", "key whole", check=no_provider_word),
        Scenario("a-key-s-answer-in-a-stream", "key stream", stream=True, check=no_provider_word),
        Scenario("a-row-of-a-provider-first", "pool cloud", check=no_provider_word),
        Scenario("a-key-s-refusal-stays-the-client-s", "key refuses", check=no_provider_word),
        Scenario("a-key-s-refusal-in-a-stream", "key refuses", stream=True, check=no_provider_word),
        Twice("a-limit-rests-the-account", "key limit", check=no_provider_word),
        Scenario("a-limit-with-no-row-left", "key limit only", differs=("fields",), check=no_provider_word),
        Twice("a-sign-in-refused-rests-the-account", "key sign in", check=no_provider_word),
        Twice("no-money-rests-the-account", "key money", check=no_provider_word),
        Scenario("a-provider-s-failure-goes-on", "key fails", check=no_provider_word),
        Scenario("a-provider-s-failure-with-no-row-left", "key fails only", check=no_provider_word),
        Scenario("a-provider-that-does-not-answer-goes-on", "key dead", check=no_provider_word),
        Scenario("a-provider-that-does-not-answer-with-no-row-left", "key dead only", check=no_provider_word),
        Scenario("a-model-its-provider-no-longer-lists", "key not listed"),
        Scenario("a-model-closed-by-its-schedule-is-passed-over", "key closed"),
        Scenario("a-model-closed-with-no-row-left", "key closed only"),
        KeptConnection("a-provider-s-connection-is-kept", "key keeps", check=the_second_came_on_a_kept_connection),
        # What only some providers take.
        Scenario("responses-to-a-key-that-speaks-it", "openai responses", path="/v1/responses"),
        Scenario("responses-to-a-key-that-does-not", "key responses", path="/v1/responses", differs=("fields",)),
        Scenario("a-form-to-a-key", path="/v1/audio/transcriptions", body=form_of("key whole"), headers={"Content-Type": "multipart/form-data; boundary=bound"}),
        # Anthropic.
        Scenario("anthropic-whole", "anthropic", check=no_provider_word),
        Scenario("anthropic-in-a-stream", "anthropic", stream=True, check=no_provider_word),
        Scenario("anthropic-cut-keeps-what-it-said-it-used", "anthropic cut", stream=True),
        # A subscription.
        Scenario("a-subscription-in-a-stream", "subscription", stream=True, check=no_provider_word),
        Scenario("a-subscription-whole", "subscription", check=no_provider_word),
        Scenario("a-subscription-s-tool-call", "subscription tools", stream=True),
        Scenario("a-subscription-s-tool-call-whole", "subscription tools"),
        Scenario("a-subscription-cut-is-no-whole-answer", "subscription cut"),
        Scenario("a-subscription-cut-in-a-stream", "subscription cut", stream=True),
        Scenario("responses-in-a-stream", path="/v1/responses", body=json.dumps({"model": "subscription", "input": "привет", "stream": True}).encode()),
        Scenario("responses-whole", path="/v1/responses", body=json.dumps({"model": "subscription", "input": [{"role": "user"}], "stream": False}).encode()),
        Scenario("responses-cut-whole", path="/v1/responses", body=json.dumps({"model": "subscription cut", "input": [], "stream": False}).encode()),
        Scenario("a-recording-to-a-subscription", path="/v1/audio/transcriptions", body=form_of("recording to a subscription"),
                 headers={"Content-Type": "multipart/form-data; boundary=bound"}),
        Scenario("a-subscription-below-its-stop", "subscription low"),
        Scenario("a-subscription-below-its-stop-with-no-row-left", "subscription low only", differs=("fields", "body"), check=told_a_limit),
        Scenario("a-subscription-gives-way", "subscription gives way"),
        Scenario("a-subscription-gives-way-to-nobody", "subscription way of none"),
        Twice("a-subscription-s-limit-rests-it", "subscription limit", check=no_provider_word),
        Scenario("an-effort-it-does-not-take-is-asked-again", body=json.dumps({"model": "subscription effort", "reasoning_effort": "none", "messages": []}).encode()),
        Scenario("an-effort-it-learned-goes-at-once", body=json.dumps({"model": "subscription effort", "reasoning_effort": "none", "messages": []}).encode()),
        Renewal("a-token-near-its-end-is-renewed", "subscription renews", check=the_token_was_renewed),
        # A provider over TLS: the only thing a real one adds, and what a key is sent over.
        Scenario("over-tls", "over tls"),
        Scenario("over-tls-in-a-stream", "over tls streams", stream=True),
        KeptConnection("over-tls-a-connection-is-kept", "over tls keeps", check=the_second_came_on_a_kept_connection),
        KeptThenClosed("over-tls-a-kept-connection-closed", "over tls keeps", check=the_second_came_on_a_fresh_connection),
        KeptThenClosed("a-kept-connection-closed", "plain keeps", check=the_second_came_on_a_fresh_connection),
        KeptConnection("a-kept-connection-that-closes-when-asked", "key drops"),
        Scenario("a-client-s-x-api-key-stays-home", "key whole", headers={"x-api-key": KEY}),
        Scenario("a-client-s-x-api-key-stays-home-from-a-subscription", "subscription", headers={"x-api-key": KEY}),
        Scenario("a-client-s-x-api-key-stays-home-from-a-machine", "whole-ok", headers={"x-api-key": KEY}),
        NamedForAll("one-name-to-a-key", "key whole"),
        NamedForAll("one-name-to-a-subscription", "subscription"),
        Twice("what-an-answer-says-of-its-window-counts", "subscription rising"),
        # The two libraries put a refused certificate in their own words, and the journal keeps those.
        Scenario("over-tls-a-stranger-s-certificate", "over tls a stranger", differs=("events", "records"), check=no_provider_heard_of_it),
        Scenario("over-tls-a-certificate-of-another-name", "over tls another name", differs=("events", "records"), check=no_provider_heard_of_it),
        # The other kinds of work of a machine's model.
        Scenario("embeddings", "embed-model", path="/v1/embeddings"),
        Scenario("a-completion-streamed", "text-model", stream=True, path="/v1/completions"),
        Scenario("a-responses-body", "whole-close", path="/v1/responses"),
        Scenario("a-recording-to-transcribe", path="/v1/audio/transcriptions", body=form_of("ear-hears"),
                 headers={"Content-Type": "multipart/form-data; boundary=bound"}),
        Scenario("speech-as-bytes", "a-voice", path="/v1/audio/speech"),
        Scenario("other-work", "embed-model"),
        Scenario("a-recording-to-a-chat-model", path="/v1/audio/transcriptions", body=form_of("whole-ok"),
                 headers={"Content-Type": "multipart/form-data; boundary=bound"}),
        Scenario("no-key", "whole-ok", key=None),
        Scenario("an-unknown-key", "whole-ok", key="nobody"),
        Scenario("a-shared-key", "whole-ok", key=SHARED_KEY),
        Scenario("a-stopped-model", "stopped-now"),
        Scenario("an-unknown-model", "no-such-model"),
        Scenario("a-chat-to-an-ear", "an-ear"),
        Scenario("closed-to-client", "closed-one", key=DENIED_KEY),
        Scenario("a-paused-client", "whole-ok", key=PAUSED_KEY),
        Scenario("a-paused-client-names-a-model-it-has-not", "no-such-model", key=PAUSED_KEY),
        Scenario("half-of-a-letter-in-a-message", body=b'{"model": "whole-ok", "messages": [{"role": "user", "content": "cut \\ud83d"}]}'),
        # Decided: the summary says what it read, and the program reads such a number as nothing. What goes to the model is the body.
        Scenario("a-number-only-python-reads", body=b'{"model": "whole-ok", "temperature": NaN, "messages": []}', differs=("records",)),
        Scenario("a-client-of-its-own-key", "whole-ok", key=OFF_LIST_KEY),
        Scenario("a-client-of-its-own-key-streaming", "stream-ok", stream=True, key=OFF_LIST_KEY),
        Scenario("not-json", body=b"not json"),
        Scenario("no-body", body=b""),
        Scenario("no-model", body=b'{"messages":[]}'),
        Scenario("a-number-for-a-model", body=b'{"model": 5}'),
        Scenario("chunked", body=b'11\r\n{"model":"nobody"}\r\n0\r\n\r\n', headers={"Transfer-Encoding": "chunked"}),
        Scenario("chunks-that-end-in-a-model", body=b'14\r\n{"model":"whole-ok"}\r\n0\r\n\r\n', headers={"Transfer-Encoding": "chunked"}),
        Scenario("another-coding", body=b"x", headers={"Transfer-Encoding": "gzip"}),
        Scenario("a-length-that-is-no-number", body=b"", headers={"Content-Length": "x"}),
        # A request that says both: the chunks win. Read by its length, what follows would be taken for the next request.
        Scenario("chunks-and-a-length", body=b'11\r\n{"model":"nobody"}\r\n0\r\n\r\n',
                 headers={"Transfer-Encoding": "chunked", "Content-Length": "6"}),
        Scenario("a-form-that-names-nothing", body=b"--x\r\n\r\n--x--", headers={"Content-Type": "multipart/form-data; boundary=x"}),
        Scenario("a-path-the-entry-has-not", "whole-ok", path="/v1/other"),
        Scenario("a-form-with-no-boundary", body=b"--x", headers={"Content-Type": "multipart/form-data"}),
        Options("options-of-a-path", path="/v1/chat/completions", method="OPTIONS"),
    ]


def plain_questions():
    """Questions the entry answers without a journal's row, over the scenarios' own documents."""
    return [
        ("models-list", "GET", "/v1/models", KEY),
        ("one-model", "GET", "/v1/models/whole-ok", KEY),
        ("no-such-one-model", "GET", "/v1/models/nobody", KEY),
        ("another-question", "GET", "/v1/other", KEY),
    ]


class ListQuestions:
    """The model list's questions, over the documents of `contract/entry_models.json`: what the rules' table holds by value, here through a real process and real files."""

    ROUTES = (("plain", {}), ("limited", {"contextLength": 16000}), ("preferring", {"contextLength": 16000, "contextAuto": True}),
              ("closed", {"deny": ["pool:p-fixed", "model:mm:a", "account:acc-key", "host:box-2", "pool:nobody"]}))
    #: Who answers, in the `Server` field.
    PROGRAM = "caravan-proxy"
    SHOW = "/api/show"
    #: Bodies of Ollama's question that name a model some other way, or none.
    SHOW_BODIES = (b'{"name": "gemma"}', b'{"model": "", "name": "gemma"}', b'{"model": "gemma", "name": "seer"}', b"{}", b"[1]", b"not json",
                   b'{"model": 5}', b'{"model": "  "}', b'{"model": null, "name": "seer"}')
    #: Spellings of the paths, and paths that are not the list's.
    PATHS = ("/v1/models/", "/v1/models//", "/v1/models?x=1", "/v1/models/gemma/", "/v1/models/GEMMA", "/v1/models/g%65mma", "/v1/models/a%2Fb",
             "/v1/models/%FF", "/v1/models/100%", "/v1/models/%zz", "/v1/models/twin%20(box-1)", "/v1/modelsx", "/v1/other")
    #: Targets `urlsplit` reads in a way of its own: the list is found in them.
    ODD_TARGETS = ("//v1/models", "/v1/models#x", "http://entry/v1/models")

    def __init__(self, harness):
        self.harness = harness
        self.table = json.loads((ROOT / "contract" / "entry_models.json").read_text(encoding="utf-8"))
        self.door = harness.door()

    def key_of(self, name):
        return f"conformance-list-{name}-key"

    def set_up(self):
        data = self.harness.data
        data.extra_routes = [{"label": f"list {name}", "port": 23300 + at, "kind": "consumer", "apiKey": self.key_of(name), "portClosed": True,
                              "enabled": True, "upstreamType": "cloud", **raw} for at, (name, raw) in enumerate(self.ROUTES)]
        self.kept_outputs, data.fixed_outputs = data.fixed_outputs, self.table["outputs"]
        self.write(self.table["cloud"], self.table["secrets"], self.table["catalogue"])
        data.write_settings()

    def write(self, cloud, secrets, catalogue):
        folder = self.harness.data.folder
        (folder / "config" / "cloud-providers.json").write_text(json.dumps(cloud), encoding="utf-8")
        for path, document in ((folder / "secrets" / "provider-secrets.json", secrets), (folder / "state" / "model-catalog.json", catalogue)):
            path.write_text(document if isinstance(document, str) else json.dumps(document), encoding="utf-8")

    def tear_down(self):
        data = self.harness.data
        data.extra_routes, data.fixed_outputs = [], self.kept_outputs
        data.write_cloud()
        data.write_settings()

    @staticmethod
    def words(answer):
        """The answer's JSON without its time, fields in their order; bytes that are no JSON as they are."""
        try:
            return json.dumps(strip_created(json.loads(answer.body)))
        except ValueError:
            return answer.body

    def compare(self, name, method, path, key, body=None):
        """The answer to one question, against what is kept."""
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        answer = Client.ask(self.door.port, method, path, headers, body)
        self.harness.compared += 1
        said = {"status": answer.status, "words": self.words(answer), **{field: answer.fields.get(field) for field in ("content-type", "connection", "retry-after")}}
        kept, now = self.harness.keep(f"list · {name}", said)
        if kept != now:
            self.harness.failures.append(f"{name}: kept {kept!r}\n    said {now!r}")
        if self.PROGRAM and answer.fields.get("server") != self.PROGRAM:
            self.harness.failures.append(f"{name}: answered by {answer.fields.get('server')}, with {answer.status}")

    def run(self):
        self.set_up()
        try:
            self.ask_everything()
            self.ask_after_a_change()
            self.ask_with_a_doubt()
        finally:
            self.tear_down()

    def ask_everything(self):
        names = sorted({row["wanted"] for row in self.table["cases"] if row["wanted"]})
        for route, _ in self.ROUTES:
            key = self.key_of(route)
            self.compare(f"list of {route}", "GET", "/v1/models", key)
            for name in names:
                self.compare(f"one model {name!r} of {route}", "GET", "/v1/models/" + quote(name, safe=""), key)
                self.compare(f"shown {name!r} of {route}", "POST", self.SHOW, key, json.dumps({"model": name}).encode())
        key = self.key_of("plain")
        for path in self.PATHS:
            self.compare(f"path {path}", "GET", path, key)
        for target in self.ODD_TARGETS:
            self.compare(f"target {target}", "GET", target, key)
        for body in self.SHOW_BODIES:
            self.compare(f"shown by {body!r}", "POST", self.SHOW, key, body)
        self.compare("shown by no body", "POST", self.SHOW, key)
        self.compare("shown at its other spelling", "POST", self.SHOW + "/", key, b'{"model": "gemma"}')
        self.compare("the list by another way", "POST", "/v1/models", key, b"{}")
        self.compare("the list's options", "OPTIONS", "/v1/models", key)
        self.compare("the list of a paused client", "GET", "/v1/models", PAUSED_KEY)
        self.compare("the list of a client of its own key", "GET", "/v1/models", OFF_LIST_KEY)
        self.compare("the list without a key", "GET", "/v1/models", None)
        self.compare("the list of an unknown key", "GET", "/v1/models", "nobody's")

    def ask_after_a_change(self):
        """A file changes and the new list is said at the next answer: a sign-in, a window from the catalogue, a pool away."""
        key = self.key_of("plain")
        table = self.table
        secrets = {**table["secrets"], "acc-none": {"apiKey": "x"}}
        cloud = {**table["cloud"], "pools": [pool for pool in table["cloud"]["pools"] if not (isinstance(pool, dict) and pool.get("id") == "p-fixed")]}
        catalogue = {"accounts": {"acc-key": {"models": [{"id": "windowed", "contextLength": 32000}]}}}
        self.write(cloud, secrets, catalogue)
        self.compare("the list after a change", "GET", "/v1/models", key)
        self.compare("a model signed in since", "GET", "/v1/models/no-key-model", key)
        self.compare("a pool gone since", "GET", "/v1/models/for%20agents", key)

    def ask_with_a_doubt(self):
        """A reading it cannot answer for, and a name of any letters."""
        key = self.key_of("plain")
        table = self.table
        doubts = (("a file of the old form", {"blocks": [{"id": "b1", "accountId": "acc-key", "model": "m"}], "accounts": table["cloud"]["accounts"]}, table["secrets"]),
                  ("credentials that do not read", table["cloud"], "not json"))
        self.write({**table["cloud"], "pools": [{"id": "p", "name": "Straße", "steps": []}]}, table["secrets"], table["catalogue"])
        self.compare("the list with a name of any letters", "GET", "/v1/models", key)
        self.compare("one model with a name of any letters", "GET", "/v1/models/gemma", key)
        self.compare("shown with a name of any letters", "POST", self.SHOW, key, b'{"model": "gemma"}')
        for name, cloud, secrets in doubts:
            self.write(cloud, secrets, table["catalogue"])
            self.compare(f"the list with {name}", "GET", "/v1/models", key)
            self.compare(f"one model with {name}", "GET", "/v1/models/gemma", key)
            self.compare(f"shown with {name}", "POST", self.SHOW, key, b'{"model": "gemma"}')


def slow_scenarios():
    """What takes a keepalive's turn twice over: CI runs it, a quick look need not."""
    return [Scenario("kept-alive-through-a-silence", "silent-a-while", stream=True, check=kept_alive),
            Scenario("a-pool-s-row-fails-late", "pool slow", stream=True, check=the_next_row_served("stream-ok"))]


def run_plain_questions(harness):
    door = harness.door()
    for name, method, path, key in plain_questions():
        answer = Client.ask(door.port, method, path, {"Authorization": f"Bearer {key}"})
        harness.compared += 1
        kept, now = harness.keep(f"plain · {name}", {"status": answer.status, "words": strip_created(json.loads(answer.body))})
        if kept != now:
            harness.failures.append(f"{name}: kept {kept!r}\n    said {now!r}")


def strip_created(value):
    if isinstance(value, dict):
        return {key: strip_created(item) for key, item in value.items() if key != "created"}
    if isinstance(value, list):
        return [strip_created(item) for item in value]
    return value


def check_a_new_version(harness):
    """A new version replaces the file, and the controller starts it. A stream through the old one goes on to its last byte, the new one takes
    the port and the state file, and the old one ends by itself."""
    door = harness.door()
    harness.machine.forget()
    answers = []
    body = json.dumps({"model": "hold-left", "stream": True, "messages": []}).encode()
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    asking = threading.Thread(target=lambda: answers.append(Client.ask(door.port, "POST", "/v1/chat/completions", headers, body, timeout=30)))
    asking.start()
    deadline = time.time() + 5
    while time.time() < deadline and not harness.machine.asked:
        time.sleep(0.01)
    old = harness.processes[-1]
    replacement = harness.program.with_name("caravan-proxy.new")
    shutil.copy2(harness.binary, replacement)
    with replacement.open("ab") as handle:
        handle.write(b"\0")
    replacement.replace(harness.program)
    log = open(harness.data.folder / "processes.log", "ab")
    new = subprocess.Popen([str(harness.program)], env=harness.env(), stdout=log, stderr=log, cwd=str(harness.data.folder))
    log.close()
    harness.processes.append(new)
    problems = []
    rows_before = len(harness.data.journal_rows())
    deadline = time.time() + 6
    state_file = harness.data.folder / "state" / "agent-proxy-state.json"
    served_by_new = False
    while time.time() < deadline and not served_by_new:
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            served_by_new = state.get("pid") == new.pid
        except (OSError, ValueError):
            pass
        time.sleep(0.1)
    if not served_by_new:
        problems.append("the new version did not take over the state file")
    harness.compared += 1
    answer = Client.ask(door.port, "POST", "/v1/chat/completions", headers, json.dumps({"model": "whole-ok", "messages": []}).encode())
    rows = harness.data.journal_rows()[rows_before:]
    if answer.status != 200 or not any(row.get("proxy") == "rust" and row["event"] == "finished" for row in rows):
        problems.append(f"the new version does not serve: {answer.status}")
    if old.poll() is not None:
        problems.append("the old version ended with a stream still going")
    harness.machine.release.set()
    asking.join(20)
    stream = answers[0] if answers else None
    if stream is None or not stream.body.endswith(b"[DONE]\n\n"):
        problems.append(f"the stream through the old version was cut: {stream.body[-80:] if stream else None!r}")
    try:
        code = old.wait(8)
        if code != 0:
            problems.append(f"the old version ended with code {code}")
    except subprocess.TimeoutExpired:
        problems.append("the old version did not end after its last request")
    harness.failures.extend(f"a new version: {problem}" for problem in problems)


def check_pool_watch(harness):
    """A pool edited on the board is decided again with no request to ask for it. The rows of `watched` change places."""
    data = harness.data

    def decided(pool):
        state = json.loads((data.folder / "state" / "agent-proxy-state.json").read_text(encoding="utf-8"))
        return ((state.get("pools") or {}).get("pools") or {}).get(pool) or {}

    def decided_at():
        return decided("the-pool-nobody-edited").get("decidedAt")

    # The earlier questions put these files back, and every pool of them was decided again, one by one: `watched` stands last.
    settled = time.time() + 40
    while time.time() < settled and not (decided_at() and decided("watched").get("selectedStepId") == "first"):
        time.sleep(0.1)
    time.sleep(1.5)
    before = decided_at()
    data.pool_watched_rows = ("second", "first")
    data.write_cloud()
    deadline = time.time() + 12
    said = None
    while time.time() < deadline and said != "second":
        said = decided("watched").get("selectedStepId")
        time.sleep(0.1)
    harness.compared += 1
    if said != "second":
        harness.failures.append(f"a pool edited: the row chosen with no request is {said}, not the new first")
    if decided_at() != before:
        harness.failures.append("a pool edited: a pool nothing changed was decided again too")


def check_state_file(harness):
    """The state file reads as the board expects: its `agents`, its counts beside them."""
    deadline = time.time() + 6
    path = harness.data.folder / "state" / "agent-proxy-state.json"
    state = {}
    # The file is written on a beat, not at each answer: what it says of the last request comes a moment later.
    while time.time() < deadline:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if (state.get("counts") or {}).get("served") and not ((state.get("agents") or {}).get("23201") or {}).get("active"):
            break
        time.sleep(0.1)
    harness.compared += 1
    agent = (state.get("agents") or {}).get("23201") or {}
    problems = []
    if not agent.get("recent") or agent.get("label") != "client":
        problems.append(f"no recent request for the client: {str(agent)[:200]}")
    if agent.get("active"):
        problems.append(f"requests still running after the last scenario: {str(agent.get('active'))[:300]}")
    counts = state.get("counts") or {}
    if counts.get("journalFailures") or counts.get("stateFailures"):
        problems.append(f"it counted write failures: {counts}")
    harness.failures.extend(f"state file: {problem}" for problem in problems)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="run the scenarios whose name holds this")
    parser.add_argument("--slow", action="store_true", help="also what takes a keepalive's turn: about a minute more")
    parser.add_argument("--write", action="store_true", help="keep what the program says now as what it promises: its diff is what changed")
    args = parser.parse_args()
    if args.write and args.only:
        raise SystemExit("--write keeps a whole run, not one scenario")
    binary = Binary.find()
    if binary is None or not binary.exists():
        words = "rust conformance: no binary (cargo build --release -p proxy in rust/, or CARAVAN_RUST_PROXY_BIN)"
        if os.environ.get("CARAVAN_RUST_REQUIRED"):
            print(f"{words}: FAILED, this job must have one")
            return 1
        print(f"{words}: SKIPPED, nothing was compared")
        return 0
    harness = Harness(binary, writing=args.write)
    harness.start()
    try:
        whole = args.slow or args.write or os.environ.get("CARAVAN_RUST_REQUIRED")
        every = scenarios() + (slow_scenarios() if whole else [])
        chosen = [one for one in every if not args.only or args.only in one.name]
        for scenario in chosen:
            harness.compare(scenario)
        if not args.only:
            run_plain_questions(harness)
            ListQuestions(harness).run()
            check_state_file(harness)
            check_pool_watch(harness)
            check_a_new_version(harness)
            if whole:
                harness.failures.extend(f"{key}: kept, and nothing asked it" for key in harness.frozen.unasked())
    finally:
        harness.stop()
    if args.write:
        harness.frozen.write()
        print(f"rust conformance: kept {len(harness.frozen.rows)} answers in {harness.frozen.path.relative_to(ROOT)}")
        return 0
    if harness.failures:
        print(f"rust conformance: FAILED, {len(harness.failures)} differences in {harness.compared} comparisons ({binary.name})")
        for failure in harness.failures:
            print(f"  - {failure[:40000]}")
        return 1
    print(f"rust conformance: ok, {harness.compared} comparisons over {len(chosen)} scenarios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
