#!/usr/bin/env python3
"""Characterization snapshot for GET /v1/models on a proxy port.

Pins the VALUE the endpoint answers with in every outcome the handler can
reach — open route, route pinned to a dead upstream, route bound to no router,
paused, drain, cloud, and a caller who did not present the route's apiKey —
plus whether the upstream was contacted at all.

Written before the endpoint learned to ask the upstream, so that the change
shows exactly which of the seven outcomes moves and which must not.

Run: python3 scripts/test_proxy_models.py
"""
import copy
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-models-"))
# Every mutable path the proxy touches is redirected into the temp tree BEFORE
# caravan.proxy.paths is imported — it reads these once, at import.
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "agent-proxy-state.json")
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["MODEL_CATALOG_FILE"] = str(TMP / "model-catalog.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
sys.path.insert(0, str(ROOT))

from caravan.proxy.handler import ProxyHandler, _rename_models  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


# ── the fake llama-server ────────────────────────────────────────────────────
# Shaped like a real llama.cpp answer: three top-level keys, an Ollama-style
# `models` block, and a `data` entry carrying the non-standard `aliases` field.
# Values are invented — a real one names a machine and a home directory.
UPSTREAM_BODY = {
    "models": [{"name": "tiny-test.gguf", "model": "tiny-test.gguf",
                "format": "gguf", "capabilities": ["completion"]}],
    "object": "list",
    "data": [{"id": "/models/tiny-test.gguf", "object": "model", "created": 111,
              "owned_by": "llamacpp", "aliases": ["tiny"], "tags": [],
              # The two numbers are deliberately different: n_ctx is what one
              # request may use (per slot), n_ctx_train is what the model was
              # trained for. A reader that takes the larger one overstates the
              # limit, so the snapshot must be able to tell them apart.
              "meta": {"vocab_type": 2, "n_vocab": 100, "n_ctx": 4096,
                       "n_ctx_train": 8192, "n_embd": 64, "n_params": 1,
                       "size": 2, "ftype": "F16"}}],
}
# Every key name the surveyed clients accept as "the context window" (Hermes's
# _CONTEXT_LENGTH_KEYS is the widest list found). The snapshot uses it to assert
# what IS and IS NOT visible at the top level of a data[] entry.
CONTEXT_KEYS = ("context_length", "context_window", "context_size", "max_context_length",
                "max_position_embeddings", "max_model_len", "max_input_tokens",
                "max_sequence_length", "max_seq_len", "n_ctx_train", "n_ctx", "ctx_size")
upstream_hits = []
# Tests append one body here to make the fake server answer with a different
# shape for a single call, then clear it.
UPSTREAM_OVERRIDE = []


class _Upstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        upstream_hits.append(self.path)
        if UPSTREAM_OVERRIDE:
            raw = UPSTREAM_OVERRIDE[0]
            body = raw if isinstance(raw, bytes) else json.dumps(raw).encode("utf-8")
        else:
            body = json.dumps(UPSTREAM_BODY).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


UP_PORT = free_port()
DEAD_PORT = free_port()          # nothing ever listens here
P_OPEN = free_port()
P_DEAD = free_port()
P_UNASSIGNED = free_port()
P_PAUSED = free_port()
P_DRAIN = free_port()
P_CLOUD = free_port()
P_KEYED = free_port()
P_TOCLOUD = free_port()
P_CLOUD_DECLARED = free_port()
P_CLOUD_CACHED = free_port()
P_CLOUD_AUTO = free_port()
P_OWN_LLAMA = free_port()
P_OWN_CLOUD = free_port()
P_NAMED = free_port()
P_NAMED_CLOUD = free_port()
P_NAMED_OPEN = free_port()        # name written, lock open: the model's own id wins
P_NAMED_CLOUD_OPEN = free_port()
P_OWN_AUTO = free_port()
P_OWN_BELOW = free_port()      # limit below the served window
P_OWN_PREFER = free_port()     # limit below, switch on: the served window wins
P_PREFER_NOMODEL = free_port() # switch on, but the block reports no window


def _route(port, **extra):
    base = {"label": f"route-{port}", "port": port, "enabled": True,
            "upstreamHost": "127.0.0.1", "upstreamPort": UP_PORT,
            "routerId": "router:default"}
    base.update(extra)
    return base


CONFIG = {
    "routes": [
        _route(P_OPEN),
        _route(P_DEAD),
        _route(P_UNASSIGNED, routerId=""),
        _route(P_PAUSED, mode="paused"),
        _route(P_DRAIN, mode="drain"),
        _route(P_CLOUD, upstreamType="cloud", providerId="blk:test"),
        _route(P_KEYED, apiKey="s3cret"),
        _route(P_TOCLOUD),
        _route(P_CLOUD_DECLARED, upstreamType="cloud", providerId="blk:declared"),
        _route(P_CLOUD_CACHED, upstreamType="cloud", providerId="blk:cached"),
        _route(P_CLOUD_AUTO, upstreamType="cloud", providerId="blk:auto"),
        # The number the operator set FOR THIS port: a copy of the setting on
        # the client's proxy cell, carried here by reconcile_proxy_metadata.
        _route(P_OWN_LLAMA, contextLength=32768),
        _route(P_OWN_CLOUD, upstreamType="cloud", providerId="blk:declared", contextLength=32768),
        _route(P_NAMED, contextLength=32768, modelName="main-model"),
        _route(P_NAMED_CLOUD, upstreamType="cloud", providerId="blk:declared", modelName="main-model"),
        # The same route with an OPEN lock: the operator's name stays in the
        # record, but the port advertises the model under its own name.
        _route(P_NAMED_OPEN, contextLength=32768, modelName="main-model", modelNameAuto=True),
        _route(P_NAMED_CLOUD_OPEN, upstreamType="cloud", providerId="blk:declared",
               modelName="main-model", modelNameAuto=True),
        _route(P_OWN_AUTO, upstreamType="cloud", providerId="blk:declared",
               contextLength=32768, contextAuto=True),
        _route(P_OWN_BELOW, contextLength=2048),
        _route(P_OWN_PREFER, contextLength=2048, contextAuto=True),
        _route(P_PREFER_NOMODEL, upstreamType="cloud", providerId="blk:cached",
               contextLength=32768, contextAuto=True),
    ],
    "routers": [{
        "id": "router:default",
        "outputs": [
            {"id": "out:up", "name": "up", "upstreamHost": "127.0.0.1", "upstreamPort": UP_PORT},
            {"id": "out:dead", "name": "dead", "upstreamHost": "127.0.0.1", "upstreamPort": DEAD_PORT},
            {"id": "out:cloud", "name": "cloud", "upstreamType": "cloud", "providerId": "blk:test",
             "accountId": "acc:test", "upstreamHost": "api.invalid", "upstreamPort": 443},
        ],
        # A source pin is a hard route: it makes "which output" a fact of the
        # fixture rather than of the default-picking policy.
        "rules": {"bySource": [
            {"proxyId": f"skynet:proxy:{P_DEAD}", "output": "out:dead"},
            {"proxyId": f"skynet:proxy:{P_TOCLOUD}", "output": "out:cloud"},
        ], "defaultOutput": "out:up"},
    }],
}
Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).write_text(json.dumps(CONFIG), encoding="utf-8")
Path(os.environ["CLOUD_PROVIDERS_FILE"]).write_text(json.dumps({
    "accounts": [{"id": "acc:test", "type": "anthropic", "baseUrl": "https://example.invalid"}],
    "blocks": [
        {"id": "blk:test", "accountId": "acc:test", "model": "test-cloud-model"},
        # The operator states a window here; the catalogue disagrees on purpose,
        # so precedence is pinned rather than assumed.
        {"id": "blk:declared", "accountId": "acc:test", "model": "declared-model",
         "contextLength": 200000},
        {"id": "blk:cached", "accountId": "acc:test", "model": "cached-model"},
        # Same model, but the operator handed the decision to the provider.
        {"id": "blk:auto", "accountId": "acc:test", "model": "cached-model", "contextAuto": True},
    ],
}), encoding="utf-8")
Path(os.environ["MODEL_CATALOG_FILE"]).write_text(json.dumps({"accounts": {"acc:test": {"models": [
    {"id": "declared-model", "name": "D", "contextLength": 111111},
    {"id": "cached-model", "name": "C", "contextLength": 131072},
    {"id": "test-cloud-model", "name": "T"},
]}}}), encoding="utf-8")

_servers = []
for _r in CONFIG["routes"]:
    srv = ThreadingHTTPServer(("127.0.0.1", _r["port"]), ProxyHandler)
    srv.route = _r
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _servers.append(srv)
_up = ThreadingHTTPServer(("127.0.0.1", UP_PORT), _Upstream)
threading.Thread(target=_up.serve_forever, daemon=True).start()


def get_models(port, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request("GET", "/v1/models", headers=headers or {})
    resp = conn.getresponse()
    raw = resp.read().decode("utf-8", "replace")
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except Exception:
        return resp.status, raw


# ── 1. open route, upstream alive ────────────────────────────────────────────
def test_open():
    print("open route, upstream answering:")
    before = len(upstream_hits)
    status, body = get_models(P_OPEN)
    check(status == 200, f"status is 200 (got {status})")
    check(len(upstream_hits) == before + 1, "the upstream WAS contacted")
    check(upstream_hits[-1:] == ["/v1/models"], f"on its own /v1/models (got {upstream_hits[-1:]})")
    # Not "unchanged" any more — but the change must be exactly two added keys
    # and nothing else, so strip them back off and compare the whole document.
    stripped = copy.deepcopy(body)
    for e in stripped.get("data", []):
        e.pop("context_length", None)
        e.pop("max_model_len", None)
    check(stripped == UPSTREAM_BODY, "nothing but those two keys is changed anywhere in the answer")
    entry = (body.get("data") or [{}])[0]
    check(entry.get("id") == "/models/tiny-test.gguf", f"id is the MODEL's (got {entry.get('id')!r})")
    check(entry.get("owned_by") == "llamacpp", f"owned_by is the model's (got {entry.get('owned_by')!r})")
    check("models" in body, "the upstream's `models` block survives")
    check("aliases" in entry, "the upstream's `aliases` field survives")
    check(entry.get("meta", {}).get("n_ctx") == 4096, "meta.n_ctx survives the relay")
    check(entry.get("meta", {}).get("n_ctx_train") == 8192, "meta.n_ctx_train survives the relay")
    top = sorted(k for k in CONTEXT_KEYS if k in entry)
    check(top == ["context_length", "max_model_len"], f"context published at the TOP level (got {top})")
    check(entry.get("context_length") == 4096, f"context_length is the SERVED n_ctx (got {entry.get('context_length')})")
    check(entry.get("max_model_len") == 4096, f"max_model_len is the SERVED n_ctx (got {entry.get('max_model_len')})")
    check(entry.get("context_length") != 8192, "the TRAINED context is never published as the window")


# ── 2. route pinned to an upstream that is not listening ─────────────────────
def test_dead_upstream():
    print("route pinned to a dead upstream:")
    status, body = get_models(P_DEAD)
    check(status == 502, f"status is 502 (got {status})")
    err = body.get("error") or {}
    check(err.get("type") == "upstream_unavailable", f"type=upstream_unavailable (got {err.get('type')!r})")
    check(f"127.0.0.1:{DEAD_PORT}" in (err.get("message") or ""), "the message names the upstream it could not reach")


# ── 3. route bound to no router at all ───────────────────────────────────────
def test_unassigned():
    print("route bound to no router:")
    status, body = get_models(P_UNASSIGNED)
    check(status == 503, f"status is 503 (got {status})")
    err = body.get("error") or {}
    check(err.get("type") == "unrouted", f"type=unrouted (got {err.get('type')!r})")
    check("unassigned" in (err.get("message") or ""), "the message says why it is unrouted")


# ── 4/5. paused and drain ────────────────────────────────────────────────────
def test_modes():
    print("paused / drain:")
    for port, mode in ((P_PAUSED, "paused"), (P_DRAIN, "drain")):
        status, body = get_models(port)
        check(status == 503, f"{mode}: status 503 (got {status})")
        check(body.get("kind") == "blocked", f"{mode}: kind=blocked")
        check(body.get("error") == f"proxy route route-{port} is {mode}", f"{mode}: error names route and mode")


# ── 6. cloud bridge ──────────────────────────────────────────────────────────
def test_cloud():
    print("cloud bridge:")
    status, body = get_models(P_CLOUD)
    check(status == 200, f"status is 200 (got {status})")
    entry = (body.get("data") or [{}])[0]
    check(entry.get("id") == "test-cloud-model", f"id is the block's model (got {entry.get('id')!r})")
    check(entry.get("owned_by") == "anthropic", f"owned_by is the account type (got {entry.get('owned_by')!r})")
    check([k for k in CONTEXT_KEYS if k in entry] == [],
          "the cloud bridge advertises NO context — nothing here knows it")


# ── 7. api key required ──────────────────────────────────────────────────────
def test_api_key():
    print("route with an apiKey:")
    status, body = get_models(P_KEYED)
    check(status == 401, f"no key: 401 (got {status})")
    check((body.get("error") or {}).get("type") == "unauthorized", "no key: type=unauthorized")
    status, body = get_models(P_KEYED, {"Authorization": "Bearer s3cret"})
    check(status == 200, f"right key: 200 (got {status})")
    status, _ = get_models(P_KEYED, {"x-api-key": "wrong"})
    check(status == 401, f"wrong key: 401 (got {status})")


# ── 9. the shapes the promotion must and must not touch ──────────────────────
def _one_entry(body):
    UPSTREAM_OVERRIDE[:] = [body]
    try:
        return get_models(P_OPEN)
    finally:
        UPSTREAM_OVERRIDE[:] = []


def test_promotion_shapes():
    print("context promotion, shape by shape:")

    # vLLM/SGLang already answer on the card — republished under the other name,
    # and their own key is left exactly as they wrote it.
    status, body = _one_entry({"object": "list", "data": [
        {"id": "m", "object": "model", "created": 1, "owned_by": "vllm", "max_model_len": 32768}]})
    e = (body.get("data") or [{}])[0]
    check(status == 200 and e.get("max_model_len") == 32768, "vLLM: its own max_model_len is untouched")
    check(e.get("context_length") == 32768, f"vLLM: context_length mirrors it (got {e.get('context_length')})")

    # A LoRA card carries max_model_len: null. That is an absence, not a size.
    status, body = _one_entry({"object": "list", "data": [
        {"id": "lora", "object": "model", "created": 1, "owned_by": "vllm", "max_model_len": None}]})
    e = (body.get("data") or [{}])[0]
    check("context_length" not in e, "vLLM LoRA card (max_model_len null) gains nothing")

    # A cell still loading has no meta at all.
    status, body = _one_entry({"object": "list", "data": [
        {"id": "loading", "object": "model", "created": 1, "owned_by": "llamacpp"}]})
    e = (body.get("data") or [{}])[0]
    check([k for k in CONTEXT_KEYS if k in e] == [], "an entry with no size reported gains no size")

    # Only n_ctx_train known — the trained number must NOT become the window.
    status, body = _one_entry({"object": "list", "data": [
        {"id": "trained-only", "object": "model", "created": 1, "owned_by": "llamacpp",
         "meta": {"n_ctx_train": 131072}}]})
    e = (body.get("data") or [{}])[0]
    check([k for k in CONTEXT_KEYS if k in e] == ["n_ctx_train"] or "context_length" not in e,
          f"trained-only entry gains no window (got {sorted(k for k in CONTEXT_KEYS if k in e)})")

    # An upstream that already answers under our name keeps its own value.
    status, body = _one_entry({"object": "list", "data": [
        {"id": "own", "object": "model", "created": 1, "owned_by": "x",
         "context_length": 999, "meta": {"n_ctx": 4096}}]})
    e = (body.get("data") or [{}])[0]
    check(e.get("context_length") == 999, f"an upstream's own context_length is not corrected (got {e.get('context_length')})")

    # Not a model list, and not JSON at all: relayed untouched, no new failure.
    status, body = _one_entry({"object": "list", "data": "not-a-list"})
    check(status == 200 and body.get("data") == "not-a-list", "an unreadable data field is relayed as-is")
    UPSTREAM_OVERRIDE[:] = [b"<html>not json</html>"]
    try:
        status, body = get_models(P_OPEN)
    finally:
        UPSTREAM_OVERRIDE[:] = []
    check(status == 200 and body == "<html>not json</html>", "a non-JSON body is relayed byte-for-byte")


# ── 10. a cloud model's window: stated, cached, or unknown ───────────────────
def test_cloud_context():
    print("cloud context, by what is known:")
    status, body = get_models(P_CLOUD_DECLARED)
    e = (body.get("data") or [{}])[0]
    check(status == 200 and e.get("context_length") == 200000,
          f"the operator's stated window is published (got {e.get('context_length')})")
    check(e.get("context_length") != 111111,
          "the operator's figure WINS over the catalogue's")
    check(e.get("max_model_len") == 200000, "published under both read names")

    # The catalogue knows 131072 for this model, and the block states nothing.
    # That number is NOT published: the operator never chose it, and a window
    # nobody chose is the same trap as a guessed one. It takes the block's
    # contextAuto switch to hand that decision to the provider.
    status, body = get_models(P_CLOUD_CACHED)
    e = (body.get("data") or [{}])[0]
    check([k for k in CONTEXT_KEYS if k in e] == [],
          f"nothing stated and the switch off: the cached 131072 is NOT published (got {e.get('context_length')})")

    status, body = get_models(P_CLOUD_AUTO)
    e = (body.get("data") or [{}])[0]
    check(e.get("context_length") == 131072 and e.get("max_model_len") == 131072,
          f"switch on: the provider's cached figure is published (got {e.get('context_length')})")

    status, body = get_models(P_CLOUD)
    e = (body.get("data") or [{}])[0]
    check([k for k in CONTEXT_KEYS if k in e] == [],
          "a model neither states nor has a cached window advertises NONE")


# ── 8. llama route whose router resolves to a cloud output ───────────────────
def test_routed_to_cloud():
    print("llama route, router resolves to a cloud block:")
    status, body = get_models(P_TOCLOUD)
    check(status == 200, f"status is 200 (got {status})")
    entry = (body.get("data") or [{}])[0]
    check(entry.get("id") == "test-cloud-model", f"id is the block the router chose (got {entry.get('id')!r})")
    check(entry.get("owned_by") == "anthropic", f"owned_by is that account's type (got {entry.get('owned_by')!r})")



# ── 10. the paths a client tries before it knows what this port is ───────────
# A client that has just connected asks llama.cpp's /props and /version, then
# Ollama's /api/tags and /api/show, then OpenAI's /v1/models/<id>. On a llama
# route every one of them belongs to the upstream and must keep being
# forwarded — narrowing what a proxy passes through is not safe. On a CLOUD
# route none of them exists: the subscription branch sends every path to
# /backend-api/codex/responses, so live these came back "Method Not Allowed",
# and POST /api/show reached the paid API as a request with no input at all.
PROBE_PATHS = ["/props", "/v1/props", "/version", "/api/tags", "/api/v1/models",
               "/v1/models/main-model"]


def _req(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body=body,
                 headers={**({"Content-Type": "application/json"} if body else {}), **(headers or {})})
    resp = conn.getresponse()
    raw = resp.read().decode("utf-8", "replace")
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except Exception:
        return resp.status, raw


def test_probe_paths_llama():
    print("probe paths on a llama route — forwarded, every one:")
    for path in PROBE_PATHS:
        before = len(upstream_hits)
        status, _body = _req(P_OPEN, "GET", path)
        check(status == 200 and len(upstream_hits) > before,
              f"GET {path} reaches the upstream (got {status}, hit={len(upstream_hits) > before})")


def test_probe_paths_cloud():
    print("probe paths on a cloud route — answered by the port, no cloud call:")
    for label, port in (("static cloud", P_CLOUD), ("routed to cloud", P_TOCLOUD)):
        for path in PROBE_PATHS:
            if path.startswith("/v1/models/"):
                continue          # a real OpenAI endpoint — its own case below
            status, body = _req(port, "GET", path)
            check(status == 404, f"{label}: GET {path} -> 404 (got {status})")
            check(isinstance(body, dict) and (body.get("error") or {}).get("type") == "not_found",
                  f"{label}: GET {path} says not_found, not a cloud-leg error")
        status, body = _req(port, "POST", "/api/show", body=b'{"name":"m"}')
        check(status == 404 and (body.get("error") or {}).get("type") == "not_found",
              f"{label}: POST /api/show -> 404, never reaches the paid API (got {status})")


def test_retrieve_model_on_cloud():
    print("GET /v1/models/<id> on a cloud route:")
    for label, port in (("static cloud", P_CLOUD), ("routed to cloud", P_TOCLOUD)):
        status, body = _req(port, "GET", "/v1/models/main-model")
        check(status == 404 and (body.get("error") or {}).get("type") == "not_found",
              f"{label}: an id this port does not serve -> 404 (got {status})")
        status, body = _req(port, "GET", "/v1/models/test-cloud-model")
        check(status == 200 and body.get("id") == "test-cloud-model" and body.get("object") == "model",
              f"{label}: the id it does serve -> the model object (got {status} {body})")
        check(body.get("owned_by") == "anthropic",
              f"{label}: same source as /v1/models — owned_by from the account (got {body.get('owned_by')!r})")


def test_probe_paths_keyed():
    print("a route with an apiKey:")
    status, _body = _req(P_KEYED, "GET", "/v1/models/anything")
    check(status == 401, f"llama route, no key: forwarded to proxy(), which refuses — unchanged (got {status})")
    status, _body = _req(P_KEYED, "GET", "/v1/models/anything", headers={"Authorization": "Bearer s3cret"})
    check(status == 200, f"llama route, right key: forwarded to the upstream (got {status})")
    # A cloud port answers the absent paths WITHOUT asking for a key, the same
    # way /health does: 404 names no model, no account and no upstream, and a
    # caller learns nothing from it that 401 would not have told them.
    status, body = _req(P_CLOUD, "GET", "/props")
    check(status == 404 and (body.get("error") or {}).get("type") == "not_found",
          f"cloud route: an absent path answers 404 without a key check (got {status})")


def test_health_on_cloud():
    print("/health on a cloud route:")
    for label, port in (("static cloud", P_CLOUD), ("routed to cloud", P_TOCLOUD)):
        status, body = _req(port, "GET", "/health")
        check(status == 503 and isinstance(body, dict) and body.get("status") == "degraded",
              f"{label}: answered by the port, 503 degraded (got {status} {body})")
        check((body or {}).get("reason") == "no credentials for account",
              f"{label}: the reason names the missing credential (got {(body or {}).get('reason')!r})")
    status, _body = _req(P_OPEN, "GET", "/health")
    check(status == 200 and len(upstream_hits) > 0,
          f"llama route: /health still goes to the upstream (got {status})")


# ── 11. context window set for a SINGLE consumer ────────────────────────────
# The model's own number is shared by everyone routing to it. Here the
# operator states how much is allowed for this client, and the port
# publishes the SMALLER of the two numbers — the larger one would make the
# client send more than the server will accept. The "model, if larger"
# checkbox hands the model's number over its own; while there's no model
# number, the limit stays in force.
def test_own_context_window():
    print("окно контекста этого потребителя:")
    status, body = get_models(P_OWN_LLAMA)
    e = (body.get("data") or [{}])[0]
    check(status == 200 and e.get("context_length") == 4096 and e.get("max_model_len") == 4096,
          f"llama-маршрут: предел 32768 выше обслуживаемых 4096 — публикуется меньшее (got {e.get('context_length')})")
    check((e.get("meta") or {}).get("n_ctx") == 4096,
          "вложенный meta.n_ctx НЕ переписан — там факт о запущенном сервере")

    status, body = get_models(P_OWN_BELOW)
    e = (body.get("data") or [{}])[0]
    check(e.get("context_length") == 2048 and e.get("max_model_len") == 2048,
          f"предел 2048 ниже обслуживаемых 4096 — публикуется предел, под обоими именами (got {e.get('context_length')})")

    status, body = get_models(P_OWN_PREFER)
    e = (body.get("data") or [{}])[0]
    check(e.get("context_length") == 4096 and e.get("max_model_len") == 4096,
          f"галка «модель, если больше»: обслуживаемые 4096 поверх предела 2048 (got {e.get('context_length')})")

    status, body = get_models(P_OWN_CLOUD)
    e = (body.get("data") or [{}])[0]
    check(e.get("context_length") == 32768 and e.get("max_model_len") == 32768,
          f"облачный маршрут: предел 32768 ниже числа блока 200000 — публикуется предел (got {e.get('context_length')})")

    status, body = get_models(P_OWN_AUTO)
    e = (body.get("data") or [{}])[0]
    check(e.get("context_length") == 200000,
          f"галка на облачном маршруте: число блока 200000 поверх предела 32768 (got {e.get('context_length')})")

    status, body = get_models(P_PREFER_NOMODEL)
    e = (body.get("data") or [{}])[0]
    check(e.get("context_length") == 32768 and e.get("max_model_len") == 32768,
          f"галка при блоке без числа: предел остаётся — снимать его нечем (got {e.get('context_length')})")

    # The name the port advertises the model under. A client looks up ITS OWN
    # id in the response and, not finding it, falls back to its built-in
    # default — a window honestly published never reaches it at all then.
    status, body = get_models(P_NAMED)
    e = (body.get("data") or [{}])[0]
    check(e.get("id") == "main-model",
          f"llama-порт объявляет модель именем оператора (got {e.get('id')!r})")
    check(e.get("context_length") == 4096,
          f"и окно при этом — по тому же правилу, меньшее из 32768 и 4096 (got {e.get('context_length')})")
    # AS-IS: llama.cpp returns TWO lists of the same model — OpenAI's `data`
    # and the Ollama-compatible `models`. Only the first used to be renamed.
    ollama = (body.get("models") or [{}])[0]
    check(ollama.get("name") == "main-model" and ollama.get("model") == "main-model",
          f"positive: и в Ollama-списке — имя оператора: закрытый замок держит имя для ВСЕХ "
          f"читателей, а не только для тех, кто читает `data` "
          f"(got name={ollama.get('name')!r} model={ollama.get('model')!r})")
    check(ollama.get("format") == "gguf",
          "остальные поля Ollama-записи не тронуты — переименование, а не подмена записи")
    check((body.get("data") or [{}])[0].get("aliases") == ["tiny"],
          "прежние псевдонимы на месте: замок меняет, КАК порт себя называет, "
          "а не то, на что он отзывается")
    # The upstream is free to return several models. We have no right to pick
    # on the client's behalf which one is "the" model — so we touch NOTHING,
    # in either list.
    two = json.dumps({
        "models": [{"name": "a.gguf", "model": "a.gguf"}, {"name": "b.gguf", "model": "b.gguf"}],
        "data": [{"id": "a.gguf"}, {"id": "b.gguf"}],
    }).encode("utf-8")
    kept = json.loads(_rename_models(two, "main-model").decode("utf-8"))
    check([m["name"] for m in kept["models"]] == ["a.gguf", "b.gguf"]
          and [d["id"] for d in kept["data"]] == ["a.gguf", "b.gguf"],
          f"negative: моделей несколько — не переименовываем ни одной, "
          f"угадывать «ту самую» за клиента нельзя (got {kept})")
    status, one = _req(P_NAMED_CLOUD, "GET", "/v1/models/main-model")
    check(status == 200 and one.get("id") == "main-model",
          f"облачный retrieve-model отвечает на объявленное имя (got {status} {one.get('id')!r})")
    status, body = get_models(P_NAMED_CLOUD)
    check((body.get("data") or [{}])[0].get("id") == "main-model",
          "и список объявляет то же имя — один порт, один ответ")
    # A SINGLE entry gets renamed. A list of several models stays as-is: the
    # port has no right to pick on the client's behalf which one is "the"
    # model, and renaming whichever one comes first would lie about the rest.
    import json as _json
    two = _json.dumps({"object": "list", "data": [{"id": "a"}, {"id": "b"}]}).encode()
    check(_json.loads(_rename_models(two, "main-model"))["data"] == [{"id": "a"}, {"id": "b"}],
          "список из двух моделей не переименовывается — выбирать за клиента порт не вправе")
    one = _json.dumps({"object": "list", "data": [{"id": "a"}]}).encode()
    check(_json.loads(_rename_models(one, "main-model"))["data"][0]["id"] == "main-model",
          "единственная запись переименовывается")
    check(_rename_models(one, "") == one, "пустое имя ничего не трогает")
    check(_rename_models(b"not json", "main-model") == b"not json",
          "неразбираемое тело возвращается как есть, а не теряется")
    check(_json.loads(_rename_models(_json.dumps({"object": "list", "data": []}).encode(),
                                     "main-model"))["data"] == [],
          "пустой список остаётся пустым — имени неоткуда взяться")

    # Open lock: the operator's name is recorded, but the model's own name is
    # in force. A client configured for one model per port will find it as
    # the sole entry; a client looking for ITS OWN id will see the real name.
    status, body = get_models(P_NAMED_OPEN)
    e = (body.get("data") or [{}])[0]
    check(e.get("id") == "/models/tiny-test.gguf",
          f"открытый замок на llama-порту: объявляется имя апстрима (got {e.get('id')!r})")
    check(e.get("context_length") == 4096,
          f"и окно считается по прежнему правилу — замок про имя, не про окно (got {e.get('context_length')})")
    o = (body.get("models") or [{}])[0]
    check(o.get("name") == "tiny-test.gguf" and o.get("model") == "tiny-test.gguf",
          f"negative: открытый замок не трогает и Ollama-список — оба списка меняются ВМЕСТЕ "
          f"или не меняются вовсе (got name={o.get('name')!r})")
    status, body = get_models(P_NAMED_CLOUD_OPEN)
    check((body.get("data") or [{}])[0].get("id") == "declared-model",
          f"открытый замок на облачном порту: объявляется модель блока "
          f"(got {(body.get('data') or [{}])[0].get('id')!r})")
    status, one = _req(P_NAMED_CLOUD_OPEN, "GET", "/v1/models/declared-model")
    check(status == 200 and one.get("id") == "declared-model",
          f"и retrieve-model отвечает на то же имя (got {status} {one.get('id')!r})")
    status, _one = _req(P_NAMED_CLOUD_OPEN, "GET", "/v1/models/main-model")
    check(status == 404,
          f"а на имя оператора при открытом замке — 404: порт его больше не подаёт (got {status})")

    # NEGATIVE: no name set — whatever the upstream called itself is published.
    status, body = get_models(P_OPEN)
    check((body.get("data") or [{}])[0].get("id") == "/models/tiny-test.gguf",
          "без своего имени порт публикует имя апстрима, как и было")

    # One port, one answer. The model list and retrieve-model must agree: a
    # client asks one or the other, and there's no room for them to diverge —
    # that would be exactly the lie this window feature was built to prevent.
    status, one = _req(P_OWN_CLOUD, "GET", "/v1/models/declared-model")
    check(status == 200 and one.get("context_length") == 32768 and one.get("max_model_len") == 32768,
          f"retrieve-model отдаёт число ОПЕРАТОРА, как и список (got {status} {one.get('context_length')})")
    status, one = _req(P_OWN_AUTO, "GET", "/v1/models/declared-model")
    check(one.get("context_length") == 200000,
          f"галка «от модели»: retrieve-model отдаёт модельное, как и список (got {one.get('context_length')})")
    # Negative: with no number of its own, retrieve-model doesn't invent a window.
    status, one = _req(P_CLOUD, "GET", "/v1/models/test-cloud-model")
    check([k for k in CONTEXT_KEYS if k in one] == [],
          f"без своего и без модельного retrieve-model не публикует окна (got {one})")

    # Negative: with no number of its own, the port publishes exactly what it did before.
    status, body = get_models(P_CLOUD_DECLARED)
    e = (body.get("data") or [{}])[0]
    check(e.get("context_length") == 200000, "без своего числа — число модели, как и было")
    status, body = get_models(P_OPEN)
    e = (body.get("data") or [{}])[0]
    check(e.get("context_length") == UPSTREAM_BODY["data"][0]["meta"]["n_ctx"],
          f"llama-порт без своего числа отдаёт размер апстрима (got {e.get('context_length')})")

for fn in (test_own_context_window, test_open, test_dead_upstream, test_unassigned, test_modes, test_cloud,
           test_api_key, test_routed_to_cloud, test_promotion_shapes, test_cloud_context,
           test_probe_paths_llama, test_probe_paths_cloud, test_retrieve_model_on_cloud,
           test_probe_paths_keyed, test_health_on_cloud):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all /v1/models snapshots hold")
