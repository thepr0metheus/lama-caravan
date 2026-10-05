#!/usr/bin/env python3
"""Real HTTP proxy with two fake subscriptions: routing, refusal and streaming.

Only loopback sockets are used. The fake accounts have different credentials;
the test alias intentionally shares A. No production quota is contacted.
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
from caravan.proxy import handler, state
from caravan.proxy.subscription_pool import SubscriptionPools
from caravan.proxy.subscription_usage import subscription_usage, reserve_gate


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
        self.server.seen.append((self.path, self.headers.get("Authorization"), json.loads(raw)))
        if self.server.fail_once:
            status, self.server.fail_once = self.server.fail_once, 0
            self.send(status, b'{"error":{"message":"quota exhausted"}}')
            return
        events = [{"type": "response.output_text.delta", "delta": self.server.name},
                  {"type": "response.output_item.done", "item": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": self.server.name}]}},
                  {"type": "response.completed", "response": {"status": "completed", "usage": {"input_tokens": 3, "output_tokens": 1}}}]
        body = b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events)
        self.send(200, body, "text/event-stream")


class Forward(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backends = []
        for name in ("A", "B"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
            server.name = name
            cls.backends.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.proxy = ThreadingHTTPServer(("127.0.0.1", 0), handler.ProxyHandler)
        cls.route = {"label": "pool test", "port": cls.proxy.server_address[1], "enabled": True,
                     "upstreamType": "cloud", "providerId": "stable", "upstreamHost": "127.0.0.1", "upstreamPort": 1}
        cls.proxy.route = cls.route
        (TMP / "routes.json").write_text(json.dumps({"routes": [cls.route], "routers": []}))
        threading.Thread(target=cls.proxy.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for server in [cls.proxy, *cls.backends]:
            server.shutdown()
            server.server_close()

    def setUp(self):
        for server in self.backends:
            server.short = server.weekly = 10
            server.fail_once = 0
            server.seen = []
        accounts = [{"id": aid, "name": aid, "type": "openai-subscription", "accountType": "openai-subscription",
                     "baseUrl": f"http://127.0.0.1:{server.server_address[1]}", "authMode": "oauth",
                     "usageReserve": {"18000": 20, "604800": 10}} for aid, server in zip(("a", "b"), self.backends)]
        accounts.append({**accounts[0], "id": "a-test", "testAliasOf": "a"})
        self.pool = {"id": "p", "name": "P", "mode": "auto", "members": [{"accountId": "a", "enabled": True, "automatic": True}, {"accountId": "b", "enabled": True, "automatic": True}]}
        self.data = {"accounts": accounts, "pools": [self.pool], "blocks": [{"id": "stable", "accountId": "p", "model": "test-model", "modelMode": "rewrite"}]}
        self.save()
        (TMP / "keys.json").write_text(json.dumps({i: {"oauth": {"accessToken": "token-" + i}} for i in ("a", "b")}))
        (TMP / "models.json").write_text(json.dumps({"accounts": {i: {"models": [{"id": "test-model"}]} for i in ("a", "b")}}))
        subscription_usage.clear()
        reserve_gate.clear()
        manager = SubscriptionPools()
        handler.subscription_pools = state.subscription_pools = manager
        self.manager = manager

    def save(self):
        (TMP / "cloud.json").write_text(json.dumps(self.data))

    def request(self, stream=False, extra=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.proxy.server_address[1], timeout=8)
        conn.request("POST", "/v1/responses", json.dumps({"model": "client-model", "input": "hello", "stream": stream, **(extra or {})}), {"Content-Type": "application/json"})
        response = conn.getresponse()
        result = response.status, response.read().decode()
        conn.close()
        return result

    def test_priority_keeps_client_port_model_and_credential(self):
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["output"][0]["content"][0]["text"], "A")
        self.assertEqual(self.backends[0].seen[0][1], "Bearer token-a")
        self.assertEqual(self.backends[0].seen[0][2]["model"], "test-model")
        self.assertEqual(self.backends[1].seen, [])
        self.assertNotIn("cloudPoolId", self.route)  # per-request metadata never mutates the shared route

    def test_short_and_weekly_reserves_route_to_b(self):
        for field, used in (("short", 80), ("weekly", 90)):
            self.setUp()
            setattr(self.backends[0], field, used)
            status, body = self.request()
            self.assertEqual(status, 200, body)
            self.assertEqual(self.manager.snapshot()["pools"]["p"]["selectedAccountId"], "b")
            self.assertEqual(self.backends[0].seen, [])
            self.assertEqual(self.backends[1].seen[0][1], "Bearer token-b")

    def test_upstream_429_retries_before_output(self):
        self.backends[0].fail_once = 429
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["output"][0]["content"][0]["text"], "B")
        self.assertEqual(len(self.backends[0].seen), 1)
        self.assertEqual(len(self.backends[1].seen), 1)

    def test_manual_test_alias_routes_with_original_login(self):
        self.pool["members"][1]["accountId"] = "a-test"
        self.pool.update(mode="manual", manualAccountId="a-test")
        self.save()
        status, body = self.request()
        self.assertEqual(status, 200, body)
        self.assertEqual(self.manager.snapshot()["pools"]["p"]["selectedAccountId"], "a-test")
        self.assertEqual(self.backends[0].seen[0][1], "Bearer token-a")
        self.assertEqual(self.backends[1].seen, [])

    def test_alias_does_not_bypass_reserve_and_refusal_reaches_client(self):
        self.pool["members"][1]["accountId"] = "a-test"
        self.backends[0].short = 90
        self.save()
        status, body = self.request()
        self.assertEqual(status, 429, body)
        self.assertEqual(json.loads(body)["error"]["type"], "subscription_pool_unavailable")
        self.assertEqual(self.backends[0].seen, [])
        self.assertEqual(self.backends[1].seen, [])

    def test_stream_stays_on_chosen_account(self):
        status, body = self.request(stream=True)
        self.assertEqual(status, 200, body)
        self.assertIn('"delta": "A"', body)
        self.assertEqual(self.backends[1].seen, [])

    def test_previous_response_id_is_rejected_without_inference(self):
        status, body = self.request(extra={"previous_response_id": "response-a"})
        self.assertEqual(status, 400, body)
        self.assertEqual(json.loads(body)["error"]["type"], "subscription_pool_context_required")
        self.assertEqual(self.backends[0].seen, [])
        self.assertEqual(self.backends[1].seen, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
