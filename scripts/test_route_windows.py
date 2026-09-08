#!/usr/bin/env python3
"""Snapshot of the three context windows the board shows on a route.

`annotate_route_windows` (caravan/admin/topology.py) puts three figures on
every proxy row: `modelWindow` — what the output a plain request reaches
serves, with `modelWindowSource` naming it; `effectiveWindow` — the figure the
port publishes in /v1/models, by the rule the proxy applies from the same
inputs; the operator's limit and switch already sit on the row. Pinned by
VALUE for every kind of output (a controller cell, a remote cell, a cloud
block, an account passthrough, no output) and, separately, for what must NOT
become a window: a cell's configured CTX_SIZE.

Run: python3 scripts/test_route_windows.py
"""
import pathlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.model_catalog as model_catalog  # noqa: E402
from caravan.admin.paths import TOPOLOGY_SERVER_IP  # noqa: E402
import caravan.admin.topology as topology_mod  # noqa: E402
from caravan.admin.topology import (  # noqa: E402
    MODEL_CARD_TTL_SECONDS, _cell_model_card_windows, _gguf_trained_window,
    _served_windows_by_address, annotate_route_windows,
)

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# Cells as topology_server() lists them. The first serves 60160 of a
# configured 180000 (three slots); the second has a silent /props, so only the
# configured total is known; the third runs on a client host.
SERVER = {"llamaServers": [
    {"port": 22007, "isController": True, "clientIp": "", "ctxServed": 60160, "ctxMax": 180000},
    {"port": 22002, "isController": True, "clientIp": "", "ctxServed": None, "ctxMax": 100000},
    {"port": 22031, "isRemote": True, "clientIp": "172.16.0.7", "ctxServed": 32768, "ctxMax": 32768},
    {"port": 0, "ctxServed": 4096},
    "not a row",
]}


def _router(rid, out):
    return {"id": rid, "outputs": [out], "rules": {"bySource": [], "defaultOutput": out["id"]}}


# A backup node in graph form: main → the cloud block, backup → the chat cell.
# Graph edges name outputs without the out: prefix, unlike the legacy rules.
OE_ROUTER = {"id": "router:oe", "outputs": [
    {"id": "terra2", "upstreamType": "cloud", "providerId": "blk:terra", "accountId": "acc:1"},
    {"id": "chat2", "upstreamHost": "127.0.0.1", "upstreamPort": 22007}],
    "graph": {"nodes": [{"id": "oe", "type": "onError", "config": {"mainEdge": "m", "rescueEdge": "r"}}],
              "edges": [{"id": "in", "from": "in:skynet:proxy:23001", "to": "rule:oe"},
                        {"id": "m", "from": "rule:oe", "to": "out:terra2"},
                        {"id": "r", "from": "rule:oe", "to": "out:chat2"}]}}

CONFIG = {"policy": {}, "routers": [OE_ROUTER,
    _router("router:chat", {"id": "out:chat", "upstreamHost": "127.0.0.1", "upstreamPort": 22007}),
    _router("router:gemma", {"id": "out:gemma", "upstreamHost": "127.0.0.1", "upstreamPort": 22002}),
    _router("router:remote", {"id": "out:remote", "upstreamHost": "172.16.0.7", "upstreamPort": 22031}),
    _router("router:terra", {"id": "out:terra", "upstreamType": "cloud", "providerId": "blk:terra",
                             "accountId": "acc:1"}),
    _router("router:auto", {"id": "out:auto", "upstreamType": "cloud", "providerId": "blk:auto",
                            "accountId": "acc:1"}),
    _router("router:acct", {"id": "out:acct", "upstreamType": "cloud", "providerId": "",
                            "accountId": "acc:1"}),
    _router("router:gone", {"id": "out:gone", "upstreamType": "cloud", "providerId": "blk:gone",
                            "accountId": "acc:1"}),
]}

BLOCKS = [
    {"id": "blk:terra", "accountId": "acc:1", "name": "gpt-5.6-terra", "model": "gpt-5.6",
     "contextLength": 200000, "contextAuto": False},
    {"id": "blk:auto", "accountId": "acc:1", "name": "", "model": "cached-model", "contextAuto": True},
]

CATALOGUE = {"acc:1": {"models": [{"id": "cached-model", "contextLength": 131072},
                                   {"id": "gpt-5.6", "contextLength": 999999}]}}


def _proxy(port, router_id, **extra):
    row = {"id": f"skynet:proxy:{port}", "port": port, "label": f"p{port}", "routerId": router_id,
           "upstreamHost": "127.0.0.1", "upstreamPort": 8080}
    row.update(extra)
    return row


def annotate(**extra):
    row = _proxy(23001, extra.pop("router", "router:chat"), **extra)
    catalogue_calls = []
    real = model_catalog.cached_models_entry

    def fake(account_id):
        catalogue_calls.append(account_id)
        return CATALOGUE.get(account_id)

    model_catalog.cached_models_entry = fake
    try:
        annotate_route_windows([row], CONFIG, SERVER, BLOCKS)
    finally:
        model_catalog.cached_models_entry = real
    row["_catalogueCalls"] = catalogue_calls
    return row


def facts(row):
    return (row.get("modelWindow"), row.get("modelWindowSource", {}).get("kind"), row.get("effectiveWindow"))


def main():
    print("a controller cell that serves 60160 of a configured 180000:")
    row = annotate(contextLength=256000)
    check(facts(row) == (60160, "cell", 60160),
          f"limit 256000 above the served 60160 → model 60160, advertised 60160 (got {facts(row)})")
    check(row["modelWindowSource"] == {"kind": "cell", "host": "127.0.0.1", "port": 22007},
          f"the source names the cell by the address the output uses (got {row['modelWindowSource']})")
    row = annotate(contextLength=2048)
    check(facts(row) == (60160, "cell", 2048), f"limit 2048 below → advertised 2048 (got {facts(row)})")
    row = annotate(contextLength=2048, contextAuto=True)
    check(facts(row) == (60160, "cell", 60160),
          f"switch on: the model's 60160 above the limit 2048 (got {facts(row)})")
    row = annotate()
    check(facts(row) == (60160, "cell", 60160), f"no limit → the model's own (got {facts(row)})")

    print("a cell whose /props is silent — only the configured total is known:")
    row = annotate(router="router:gemma", contextLength=256000)
    check(facts(row) == (None, "cell", 256000),
          f"model unknown → the limit is advertised as is (got {facts(row)})")
    check(row["modelWindow"] != 100000, "the configured CTX_SIZE 100000 never becomes the model's window")
    row = annotate(router="router:gemma")
    check(facts(row) == (None, "cell", None), f"no limit and no model → nothing advertised (got {facts(row)})")
    row = annotate(router="router:gemma", contextLength=4096, contextAuto=True)
    check(facts(row) == (None, "cell", 4096),
          f"switch on but the model silent → the limit still applies (got {facts(row)})")

    print("a cell on a client host:")
    row = annotate(router="router:remote", contextLength=65536)
    check(facts(row) == (32768, "cell", 32768), f"named by the client's IP (got {facts(row)})")
    check(row["modelWindowSource"]["host"] == "172.16.0.7", "the source carries that IP")

    print("a cloud block:")
    row = annotate(router="router:terra", contextLength=256000)
    check(facts(row) == (200000, "block", 200000),
          f"the block's declared 200000 below the limit 256000 (got {facts(row)})")
    check(row["modelWindowSource"] == {"kind": "block", "name": "gpt-5.6-terra", "model": "gpt-5.6"},
          f"the source names the block (got {row['modelWindowSource']})")
    check(row["_catalogueCalls"] == [], "switch off on the block: the catalogue is not read at all")
    row = annotate(router="router:terra", contextLength=100000)
    check(facts(row) == (200000, "block", 100000), f"limit 100000 below the block → 100000 (got {facts(row)})")
    row = annotate(router="router:auto")
    check(facts(row) == (131072, "block", 131072),
          f"block switch on: the catalogue's 131072 is the model's window (got {facts(row)})")
    check(row["modelWindowSource"]["name"] == "cached-model", "a nameless block is named by its model")
    check(row["_catalogueCalls"] == ["acc:1"], f"the catalogue is read once (got {row['_catalogueCalls']})")

    print("outputs that pin no window:")
    row = annotate(router="router:acct", contextLength=8192)
    check(facts(row) == (None, "account", 8192),
          f"an account passthrough pins no model → only the limit (got {facts(row)})")
    row = annotate(router="", contextLength=4096)
    check(facts(row) == (None, "unrouted", None),
          f"unassigned port: nothing advertised even with a limit — it answers 503 (got {facts(row)})")
    check(row["modelWindowSource"].get("reason") == "unassigned", "and the reason is spelled out")
    row = annotate(router="router:missing", contextLength=4096)
    check(facts(row) == (None, "unrouted", None), f"a missing router is unrouted too (got {facts(row)})")
    row = annotate(router="router:gone", contextLength=4096)
    check(facts(row) == (None, "unrouted", None),
          f"an output naming a deleted block: unrouted, not the limit (got {facts(row)})")

    print("a backup node: the board resolves the exit the proxy would take:")
    import time as _time
    real_snapshot = topology_mod._proxy_output_health
    topology_mod._proxy_output_health = lambda: {}
    try:
        row = annotate(router="router:oe", contextLength=256000)
        check(facts(row) == (200000, "block", 200000), f"no verdicts → main, the block's 200000 (got {facts(row)})")
        now = _time.time()
        topology_mod._proxy_output_health = lambda: {"terra2": {"state": "error", "status": 429, "kind": "http 429", "message": "quota", "checkedAt": now, "source": "probe"}}
        row = annotate(router="router:oe", contextLength=256000)
        check(facts(row) == (60160, "cell", 60160),
              f"main known dead in the proxy's file → the backup cell's 60160, and the port advertises it (got {facts(row)})")
        check(row["modelWindowSource"]["port"] == 22007, "the source names the backup cell")
        topology_mod._proxy_output_health = lambda: {"terra2": {"state": "error", "status": 429, "checkedAt": now - 400}}
        row = annotate(router="router:oe", contextLength=256000)
        check(facts(row) == (200000, "block", 200000), f"an expired verdict → main again (got {facts(row)})")
        # The real reader against a file that does not exist: no verdicts, no crash.
        topology_mod._proxy_output_health = real_snapshot
        real_file = topology_mod.AGENT_PROXY_STATE_FILE
        topology_mod.AGENT_PROXY_STATE_FILE = pathlib.Path("/nonexistent/agent-proxy-state.json")
        try:
            row = annotate(router="router:oe", contextLength=256000)
            check(facts(row) == (200000, "block", 200000), "a missing state file is no verdicts, not a crash")
        finally:
            topology_mod.AGENT_PROXY_STATE_FILE = real_file
        # And a reader that throws must not sink the board either.
        topology_mod._proxy_output_health = lambda: (_ for _ in ()).throw(OSError("boom"))
        row = annotate(router="router:oe", contextLength=256000)
        check(facts(row)[1] == "block", "a throwing reader is swallowed — the board still draws")
    finally:
        topology_mod._proxy_output_health = real_snapshot
        from caravan.proxy.output_health import output_health as _oh
        _oh.clear()

    print("the address map:")
    served = _served_windows_by_address(SERVER)
    check(served.get(("127.0.0.1", 22007)) == 60160 and served.get(("localhost", 22007)) == 60160
          and served.get((TOPOLOGY_SERVER_IP, 22007)) == 60160,
          "a controller cell answers under loopback, localhost and the board's own IP")
    check(("127.0.0.1", 22002) not in served, "a silent /props leaves no entry — the configured total is not one")
    check(served.get(("172.16.0.7", 22031)) == 32768 and ("127.0.0.1", 22031) not in served,
          "a client cell answers only under its host's IP")
    # The board's own IP may coincide with loopback on a developer machine.
    controller_names = len({"127.0.0.1", "localhost", TOPOLOGY_SERVER_IP})
    check(len(served) == controller_names + 1,
          f"nothing else: a port of 0 and a non-row are skipped (got {len(served)}, expected {controller_names + 1})")

    rows = [_proxy(23001, "router:chat", contextLength=2048), "junk"]
    annotate_route_windows(rows, CONFIG, SERVER, BLOCKS)
    check(rows[0]["effectiveWindow"] == 2048 and rows[1] == "junk", "a non-dict row is left alone")

    print("a running cell's model card, both windows, cached a minute:")
    calls = []
    real_fetch = topology_mod.fetch_json

    def fake_fetch(url, timeout=None):
        calls.append(url)
        return {"data": [{"id": "m", "object": "model",
                          "meta": {"n_ctx": 60160, "n_ctx_train": 131072}}]}

    def failing_fetch(url, timeout=None):
        calls.append(url)
        raise OSError("refused")

    topology_mod._MODEL_CARD_CACHE.clear()
    topology_mod.fetch_json = fake_fetch
    try:
        check(_cell_model_card_windows(22007, now=1000) == (60160, 131072),
              "llama.cpp card: served meta.n_ctx and the trained number, apart")
        check(calls == ["http://127.0.0.1:22007/v1/models"], f"one local GET (got {calls})")
        topology_mod.fetch_json = failing_fetch
        check(_cell_model_card_windows(22007, now=1000 + MODEL_CARD_TTL_SECONDS - 1) == (60160, 131072)
              and len(calls) == 1, "within the minute the card is not asked again")
        check(_cell_model_card_windows(22007, now=1000 + MODEL_CARD_TTL_SECONDS + 1) == (None, None)
              and len(calls) == 2, "after the minute it is asked again; a refusal is (None, None), not a size")
        check(_cell_model_card_windows(22007, now=1000 + MODEL_CARD_TTL_SECONDS + 2) == (None, None)
              and len(calls) == 2, "the refusal is cached too — a dead cell is not hammered")
        topology_mod.fetch_json = fake_fetch
        check(_cell_model_card_windows(22008, now=1000) == (60160, 131072) and len(calls) == 3,
              "another port is another entry")
    finally:
        topology_mod.fetch_json = real_fetch
        topology_mod._MODEL_CARD_CACHE.clear()
    vllm = {"data": [{"id": "v", "max_model_len": 32768}]}
    topology_mod.fetch_json = lambda url, timeout=None: vllm
    try:
        check(_cell_model_card_windows(22010, now=5) == (32768, None), "vLLM card: served max_model_len, no trained number")
    finally:
        topology_mod.fetch_json = real_fetch
        topology_mod._MODEL_CARD_CACHE.clear()

    print("the server object's real key:")
    import inspect
    from caravan.admin.topology import topology_server
    check('"llamaServers": llama_servers' in inspect.getsource(topology_server),
          "topology_server() lists cells under `llamaServers` — the key this map reads")
    check(_served_windows_by_address({"servers": SERVER["llamaServers"]}) == {},
          "defect-history: the map once read `servers` (a per-node key) and was silently empty on prod")

    print("the trained number never becomes a route's window:")
    served = _served_windows_by_address({"llamaServers": [
        {"port": 22009, "isController": True, "clientIp": "", "ctxServed": None, "ctxTrained": 131072}]})
    check(served == {}, f"a cell with only a trained number serves no known window (got {served})")

    print("the GGUF header of a parked cell's file:")
    import caravan.admin.models as models_mod
    import tempfile
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="caravan-gguf-"))
    (tmp / "x.gguf").write_bytes(b"GGUF")
    real_read, real_extract = models_mod.read_gguf_metadata_cached, models_mod.extract_runtime_meta
    models_mod.read_gguf_metadata_cached = lambda path: {"path": str(path)}
    models_mod.extract_runtime_meta = lambda meta: {"contextLength": 131072}
    try:
        cfg = {"LLAMA_MODELS_DIR": str(tmp)}
        check(_gguf_trained_window("x.gguf", cfg) == 131072, "a relative path is resolved under the models dir")
        check(_gguf_trained_window(str(tmp / "x.gguf"), cfg) == 131072, "an absolute path is read as is")
        check(_gguf_trained_window("/home/someone/llama-model-cache/y.gguf", cfg) is None,
              "a file that is not on this host — every client cell's — is no file: None, not a guess")
        check(_gguf_trained_window("x.safetensors", cfg) is None and _gguf_trained_window("", cfg) is None,
              "not a GGUF, or nothing: None")
    finally:
        models_mod.read_gguf_metadata_cached, models_mod.extract_runtime_meta = real_read, real_extract

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("all route-window snapshots hold")


if __name__ == "__main__":
    main()
