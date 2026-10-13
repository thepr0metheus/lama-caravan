#!/usr/bin/env python3
"""A real HTTP proxy in front of a pool of rows: who gets the request, with what.

Two fake subscriptions (A, B) speak the Codex backend; a fake key provider (R)
speaks chat completions; a fake cell (C) speaks llama-server's chat. A pool's
rows run in order. The owner, 2026-10-12: a row may be a local model; the pool
goes on down its rows on a limit refusal (429, 402, 401), an unavailable cell
(no connection, every slot taken while a later row is ready) or a server error,
all before the first byte; a request-specific 4xx is the client's. The file of
the old form — a model block in a pool of subscription members — is routed the
same way.

Only loopback sockets are used; the test alias intentionally shares A. No
production quota is contacted.

Run: python3 scripts/test_pool_forward.py
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-pool-http-"))
for env, filename in (("AGENT_PROXY_CONFIG_FILE", "routes.json"), ("AGENT_PROXY_STATE_FILE", "state.json"),
                      ("CLOUD_PROVIDERS_FILE", "cloud.json"), ("PROVIDER_SECRETS_FILE", "keys.json"),
                      ("MODEL_CATALOG_FILE", "models.json"), ("AGENT_PROXY_LOG_DIR", "logs")):
    os.environ[env] = str(TMP / filename)
sys.path.insert(0, str(ROOT))
from caravan.proxy import handler, state  # noqa: E402
from caravan.proxy.pool_steps import PoolSteps  # noqa: E402
from caravan.proxy.subscription_usage import subscription_usage  # noqa: E402

SUB = "openai-subscription"


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def send(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/backend-api/wham/usage":
            self.send(404, b"{}")
            return
        now = int(time.time())
        self.send(200, json.dumps({"rate_limit": {"primary_window": {
            "used_percent": self.server.short, "limit_window_seconds": 18000, "reset_at": now + 18000},
            "secondary_window": {"used_percent": self.server.weekly, "limit_window_seconds": 604800, "reset_at": now + 604800}}}).encode())

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        auth = self.headers.get("Authorization") or self.headers.get("x-api-key")
        self.server.seen.append((self.path, auth, json.loads(raw)))
        if self.server.fail_once:
            status, self.server.fail_once = self.server.fail_once, 0
            self.send(status, b'{"error":{"message":"refused by the fake"}}')
            return
        if self.path.endswith("/chat/completions"):
            self.send(200, json.dumps({"id": "c1", "object": "chat.completion", "model": json.loads(raw).get("model"),
                                       "choices": [{"index": 0, "message": {"role": "assistant", "content": self.server.name},
                                                    "finish_reason": "stop"}],
                                       "usage": {"prompt_tokens": 3, "completion_tokens": 1}}).encode())
            return
        events = [{"type": "response.output_text.delta", "delta": self.server.name},
                  {"type": "response.output_item.done", "item": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": self.server.name}]}},
                  {"type": "response.completed", "response": {"status": "completed", "usage": {"input_tokens": 3, "output_tokens": 1}}}]
        body = b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events)
        self.send(200, body, "text/event-stream")


class Harness(unittest.TestCase):
    """The proxy, the fakes and the helpers; the tests are its subclasses'."""

    @classmethod
    def setUpClass(cls):
        cls.backends = {}
        for name in ("A", "B", "R"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
            server.name = name
            cls.backends[name] = server
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.proxy = ThreadingHTTPServer(("127.0.0.1", 0), handler.ProxyHandler)
        cls.route = {"label": "pool test", "port": cls.proxy.server_address[1], "enabled": True,
                     "upstreamType": "cloud", "providerId": "stable", "upstreamHost": "127.0.0.1", "upstreamPort": 1}
        cls.proxy.route = cls.route
        (TMP / "routes.json").write_text(json.dumps({"routes": [cls.route], "routers": []}))
        threading.Thread(target=cls.proxy.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for server in [cls.proxy, *cls.backends.values()]:
            server.shutdown()
            server.server_close()

    def url(self, name):
        return f"http://127.0.0.1:{self.backends[name].server_address[1]}"

    def setUp(self):
        for server in self.backends.values():
            server.short = server.weekly = 10
            server.fail_once = 0
            server.seen = []
        self.accounts = [{"id": aid, "name": aid, "type": SUB, "accountType": SUB, "baseUrl": self.url(name), "authMode": "oauth"}
                         for aid, name in (("a", "A"), ("b", "B"))]
        self.accounts.append({**self.accounts[0], "id": "a-test", "testAliasOf": "a"})
        self.accounts.append({"id": "r", "name": "R", "type": "openrouter", "baseUrl": self.url("R") + "/v1", "authMode": "apiKey"})
        self.levels = {"18000": 20, "604800": 10}
        self.pool = {"id": "stable", "name": "Stable", "steps": [self.step("a", "a"), self.step("b", "b")]}
        self.data = {"accounts": self.accounts, "pools": [self.pool]}
        self.save()
        (TMP / "keys.json").write_text(json.dumps({**{i: {"oauth": {"accessToken": "token-" + i}} for i in ("a", "b")},
                                                   "r": {"apiKey": "key-r"}}))
        (TMP / "models.json").write_text(json.dumps({"accounts": {i: {"models": [{"id": "test-model"}, {"id": "small"}]}
                                                                  for i in ("a", "b", "r")}}))
        subscription_usage.clear()
        manager = PoolSteps()
        handler.pool_steps = state.pool_steps = manager
        import caravan.proxy.output_probe as probe
        probe.pool_steps = manager
        self.manager = manager

    def step(self, sid, account, model="test-model", levels=None):
        return {"id": sid, "accountId": account, "model": model, "switchAt": dict(self.levels if levels is None else levels),
                "enabled": True}

    def save(self):
        (TMP / "cloud.json").write_text(json.dumps(self.data))

    def request(self, stream=False, extra=None, chat=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.proxy.server_address[1], timeout=8)
        if chat:
            payload = {"model": "client-model", "messages": [{"role": "user", "content": "hello"}], "stream": stream, **(extra or {})}
            conn.request("POST", "/v1/chat/completions", json.dumps(payload), {"Content-Type": "application/json"})
        else:
            conn.request("POST", "/v1/responses", json.dumps({"model": "client-model", "input": "hello", "stream": stream, **(extra or {})}),
                         {"Content-Type": "application/json"})
        response = conn.getresponse()
        result = response.status, response.read().decode()
        # Every Content-Length the answer carried: an error relayed with its own
        # length and the provider's went out with two (found 2026-10-11).
        self.last_lengths = response.msg.get_all("Content-Length") or []
        conn.close()
        return result

    def selected(self):
        return self.manager.snapshot()["pools"]["stable"]["selectedStepId"]

    def text(self, body):
        """The answer's text: a chat completion, a Responses object, or — a
        subscription answers a chat request as a stream whatever it asked —
        the deltas of a chat stream."""
        if body.startswith("data:"):
            parts = []
            for line in body.splitlines():
                if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]"):
                    for choice in json.loads(line[5:]).get("choices") or []:
                        parts.append((choice.get("delta") or {}).get("content") or "")
            return "".join(parts)
        data = json.loads(body)
        return data["choices"][0]["message"]["content"] if "choices" in data else data["output"][0]["content"][0]["text"]

class Forward(Harness):
    def test_first_step_with_its_model_and_credential(self):
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(self.text(body), "A")
        self.assertEqual(self.backends["A"].seen[0][1], "Bearer token-a")
        self.assertEqual(self.backends["A"].seen[0][2]["model"], "test-model")
        self.assertEqual(self.backends["B"].seen, [])
        self.assertNotIn("cloudPoolId", self.route)  # per-request metadata never mutates the shared route

    def test_short_and_weekly_levels_route_to_the_next_step(self):
        for field, used in (("short", 80), ("weekly", 90)):
            self.setUp()
            setattr(self.backends["A"], field, used)
            status, body = self.request()
            self.assertEqual(status, 200, body)
            self.assertEqual(self.selected(), "b")
            self.assertEqual(self.backends["A"].seen, [])
            self.assertEqual(self.backends["B"].seen[0][1], "Bearer token-b")

    def test_one_subscription_twice_with_two_models(self):
        self.pool["steps"] = [self.step("a", "a", "test-model", {"18000": 50}), self.step("a-2", "a", "small", {"18000": 10})]
        self.save()
        self.backends["A"].short = 60
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(self.selected(), "a-2")
        self.assertEqual([(s[1], s[2]["model"]) for s in self.backends["A"].seen], [("Bearer token-a", "small")])

    def test_a_key_provider_after_the_subscription(self):
        self.pool["steps"] = [self.step("a", "a"), self.step("r", "r", "small", {})]
        self.save()
        self.backends["A"].short = 85
        status, body = self.request(chat=True)
        self.assertEqual(status, 200, body)
        self.assertEqual(self.text(body), "R")
        path, auth, sent = self.backends["R"].seen[0]
        self.assertEqual((path, auth, sent["model"]), ("/v1/chat/completions", "Bearer key-r", "small"))
        self.assertEqual(self.backends["A"].seen, [])

    def test_a_key_provider_out_of_money_goes_on_before_output(self):
        self.pool["steps"] = [self.step("r", "r", "small", {}), self.step("a", "a")]
        self.save()
        self.backends["R"].fail_once = 402
        status, body = self.request(chat=True)
        self.assertEqual(status, 200, body)
        self.assertEqual(self.text(body), "A")
        self.assertEqual((len(self.backends["R"].seen), len(self.backends["A"].seen)), (1, 1))
        # The account rests: the next request does not knock on it again.
        self.request(chat=True)
        self.assertEqual((len(self.backends["R"].seen), len(self.backends["A"].seen)), (1, 2))

    def test_a_server_error_moves_the_pool(self):
        # The owner, 2026-10-12: an error before the first byte sends the request on.
        self.pool["steps"] = [self.step("r", "r", "small", {}), self.step("a", "a")]
        self.save()
        self.backends["R"].fail_once = 500
        status, body = self.request(chat=True)
        self.assertEqual((status, self.text(body)), (200, "A"), body)
        self.assertEqual(len(self.backends["R"].seen), 1)
        status, body = self.request(chat=True)
        self.assertEqual((status, self.text(body)), (200, "R"))  # nothing rests: the next request asks R first

    def test_negative_a_client_error_does_not_move_the_pool(self):
        self.pool["steps"] = [self.step("r", "r", "small", {}), self.step("a", "a")]
        self.save()
        self.backends["R"].fail_once = 400
        status, body = self.request(chat=True)
        self.assertEqual(status, 400, body)
        self.assertEqual(self.last_lengths, [str(len(body.encode()))])   # one length, the body's
        self.assertEqual(self.backends["A"].seen, [])           # a request-specific answer is the client's

    def test_upstream_429_retries_before_output(self):
        self.backends["A"].fail_once = 429
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(self.text(body), "B")
        self.assertEqual((len(self.backends["A"].seen), len(self.backends["B"].seen)), (1, 1))

    def test_back_to_the_first_step_when_it_fits_again(self):
        self.backends["A"].short = 85
        self.request()
        self.assertEqual(self.selected(), "b")
        self.backends["A"].short = 10
        subscription_usage.clear()                              # the next reading comes from the usage page
        self.manager._tried.clear()
        status, body = self.request()
        self.assertEqual((status, self.text(body), self.selected()), (200, "A", "a"))

    def test_test_alias_routes_with_original_login(self):
        self.pool["steps"] = [self.step("a-test", "a-test"), self.step("b", "b")]
        self.save()
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(self.selected(), "a-test")
        self.assertEqual(self.backends["A"].seen[0][1], "Bearer token-a")
        self.assertEqual(self.backends["B"].seen, [])

    def test_alias_does_not_bypass_a_level_and_refusal_reaches_client(self):
        self.pool["steps"][1] = self.step("a-test", "a-test")
        self.backends["A"].short = 90
        self.save()
        status, body = self.request()
        self.assertEqual(status, 429, body)
        self.assertEqual(self.last_lengths, [str(len(body.encode()))])   # the pool's own answer: one length too
        self.assertEqual(json.loads(body)["error"]["type"], "pool_unavailable")
        self.assertEqual((self.backends["A"].seen, self.backends["B"].seen), ([], []))

    def test_stream_stays_on_chosen_step(self):
        status, body = self.request(stream=True)
        self.assertEqual(status, 200, body)
        self.assertIn('"delta": "A"', body)
        self.assertEqual(self.backends["B"].seen, [])

    def test_previous_response_id_is_rejected_without_inference(self):
        status, body = self.request(extra={"previous_response_id": "response-a"})
        self.assertEqual(status, 400, body)
        self.assertEqual(json.loads(body)["error"]["type"], "pool_context_required")
        self.assertEqual((self.backends["A"].seen, self.backends["B"].seen), ([], []))

    def test_the_old_form_routes_the_same(self):
        # A model block in a pool of subscription members, as the file was until
        # 1.3.462: the block's id is the pool, the members its steps.
        for account in self.accounts:
            if account.get("accountType") == SUB:
                account["usageReserve"] = dict(self.levels)
        self.data = {"accounts": self.accounts,
                     "pools": [{"id": "p", "name": "P", "mode": "auto", "members": [
                         {"accountId": "a", "enabled": True, "automatic": True}, {"accountId": "b", "enabled": True, "automatic": True}]}],
                     "blocks": [{"id": "stable", "accountId": "p", "model": "test-model", "modelMode": "rewrite"}]}
        self.save()
        self.backends["A"].short = 80
        status, body = self.request()
        self.assertEqual((status, self.text(body), self.selected()), (200, "B", "b"))
        self.assertEqual(self.backends["B"].seen[0][2]["model"], "test-model")

    def test_the_port_names_the_pool(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.proxy.server_address[1], timeout=8)
        conn.request("GET", "/v1/models")
        data = json.loads(conn.getresponse().read())
        conn.close()
        self.assertEqual([(m["id"], m["owned_by"]) for m in data["data"]], [("Stable", "caravan")])


class Cell(BaseHTTPRequestHandler):
    """A llama-server cell: answers a chat completion with its name, slowly when told."""

    def log_message(self, *args):
        return

    def do_GET(self):
        body = b"{}"
        self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.seen.append((self.path, self.headers.get("Authorization"), json.loads(raw)))
        if self.server.delay:
            time.sleep(self.server.delay)
        if self.server.fail_once:
            status, self.server.fail_once = self.server.fail_once, 0
            body = b'{"error":{"message":"refused by the cell"}}'
        else:
            status = 200
            body = json.dumps({"id": "c1", "object": "chat.completion", "model": "cell-model",
                               "choices": [{"index": 0, "message": {"role": "assistant", "content": self.server.name},
                                            "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 3, "completion_tokens": 1}}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LocalRows(Harness):
    """A pool whose rows are a local cell and a subscription (the owner, 2026-10-12)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cell = ThreadingHTTPServer(("127.0.0.1", 0), Cell)
        cls.cell.name = "C"
        threading.Thread(target=cls.cell.serve_forever, daemon=True).start()
        # A port nothing listens on: a cell that is off.
        probe = ThreadingHTTPServer(("127.0.0.1", 0), Cell)
        cls.off_port = probe.server_address[1]
        probe.server_close()

    @classmethod
    def tearDownClass(cls):
        cls.cell.shutdown()
        cls.cell.server_close()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.cell.seen, self.cell.fail_once, self.cell.delay = [], 0, 0
        from caravan.proxy.output_health import output_health
        output_health.clear()
        outputs = [{"id": "srv:1", "label": "cell", "upstreamHost": "127.0.0.1", "upstreamPort": self.cell.server_address[1],
                    "upstreamType": "llama"},
                   {"id": "srv:2", "label": "off", "upstreamHost": "127.0.0.1", "upstreamPort": self.off_port,
                    "upstreamType": "llama"}]
        (TMP / "routes.json").write_text(json.dumps({"routes": [self.route], "routers": [
            {"id": "router:default", "outputs": outputs, "rules": {"default": "srv:1"}, "graph": {"nodes": [], "edges": []}}],
            "policy": {"maxSlots": 1}}))
        self.pool["steps"] = [{"id": "r1", "output": "srv:1"}, self.step("a", "a")]
        self.save()

    def tearDown(self):
        (TMP / "routes.json").write_text(json.dumps({"routes": [self.route], "routers": []}))

    def reason(self, step_id):
        rows = self.manager.snapshot()["pools"]["stable"]["steps"]
        return next(r["reason"] for r in rows if r["stepId"] == step_id)

    def test_a_local_row_serves_first(self):
        status, body = self.request(chat=True)
        self.assertEqual((status, self.text(body)), (200, "C"), body)
        self.assertEqual(self.selected(), "r1")
        self.assertEqual(self.backends["A"].seen, [])
        self.assertIsNone(self.cell.seen[0][1])                  # the client's key stays with the caravan

    def test_a_cell_that_is_off_sends_the_request_on(self):
        self.pool["steps"] = [{"id": "r1", "output": "srv:2"}, self.step("a", "a")]
        self.save()
        status, body = self.request(chat=True)
        self.assertEqual((status, self.text(body)), (200, "A"), body)
        status, body = self.request(chat=True)
        self.assertEqual((status, self.text(body)), (200, "A"), body)
        self.assertEqual(self.reason("r1"), "unavailable")      # found dead: not asked again for a while

    def test_a_cell_server_error_sends_the_request_on(self):
        self.cell.fail_once = 500
        status, body = self.request(chat=True)
        self.assertEqual((status, self.text(body)), (200, "A"), body)
        self.assertEqual(len(self.cell.seen), 1)

    def test_a_subscription_error_sends_the_request_to_the_cell(self):
        self.pool["steps"] = [self.step("a", "a"), {"id": "r1", "output": "srv:1"}]
        self.save()
        self.backends["A"].fail_once = 503
        status, body = self.request(chat=True)
        self.assertEqual((status, self.text(body)), (200, "C"), body)

    def test_negative_a_client_error_from_the_cell_is_the_clients(self):
        self.cell.fail_once = 400
        status, body = self.request(chat=True)
        self.assertEqual(status, 400, body)
        self.assertEqual(self.backends["A"].seen, [])

    def test_a_busy_cell_gives_way_to_a_ready_row(self):
        self.cell.delay = 1.5
        first = []
        worker = threading.Thread(target=lambda: first.append(self.request(chat=True)))
        worker.start()
        deadline = time.time() + 5
        while not self.cell.seen and time.time() < deadline:
            time.sleep(0.02)
        status, body = self.request(chat=True)                   # the cell's one slot is taken
        self.assertEqual((status, self.text(body)), (200, "A"), body)
        worker.join(10)
        self.assertEqual((first[0][0], self.text(first[0][1])), (200, "C"))

    def test_a_lone_busy_cell_keeps_the_request_waiting(self):
        self.pool["steps"] = [{"id": "r1", "output": "srv:1"}]
        self.save()
        self.cell.delay = 0.8
        answers = []
        started = time.time()
        workers = [threading.Thread(target=lambda: answers.append(self.request(chat=True))) for _ in range(2)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(15)
        took = time.time() - started
        self.assertEqual(sorted((s, self.text(b)) for s, b in answers), [(200, "C"), (200, "C")])
        self.assertEqual(self.backends["A"].seen, [])
        # The cell has one slot: the second request waited for the first, it did not run beside it.
        self.assertGreater(took, 1.3)

    def test_negative_a_cell_nobody_names_is_not_asked(self):
        self.pool["steps"] = [{"id": "r1", "output": "srv:99"}, self.step("a", "a")]
        self.save()
        status, body = self.request(chat=True)
        self.assertEqual((status, self.text(body)), (200, "A"), body)
        self.assertEqual(self.reason("r1"), "output_missing")
        self.assertEqual(self.cell.seen, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
