#!/usr/bin/env python3
"""Stage A unit tests for the router graph QUEUE node.

Covers: app.normalize_router_graph queue config validation, and the
agent-proxies DAG engine (queue spec surfacing, admit path, spill
re-resolution incl. chaining, abort, and the implicit default queue
staying unchanged when no queue node is on the path).

Run: python3 scripts/test_queue_node.py
"""
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# agent-proxies.py reads CONFIG_FILE lazily (current_config) — never at import.
os.environ.setdefault("AGENT_PROXY_CONFIG", str(ROOT / "agent-proxies.json"))
app = _load("app_under_test", "app.py")
ap = _load("agent_proxies_under_test", "agent-proxies.py")

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# ── 1. app.normalize_router_graph: queue node config ─────────────────────────
def test_validation():
    print("normalize_router_graph(queue):")
    raw = {
        "nodes": [{"id": "q1", "type": "queue", "x": 10, "y": 20, "config": {
            "admitEdge": "ea", "spillEdge": "es",
            "maxSlots": 4, "abortPct": 90, "spillPct": 30,
            "stickySlotSec": 5, "keepaliveSec": 20,
        }}],
        "edges": [
            {"id": "ea", "from": "rule:q1", "to": "out:A"},
            {"id": "es", "from": "rule:q1", "to": "out:B"},
        ],
    }
    g = app.normalize_router_graph(raw, {"A", "B"})
    n = g["nodes"][0]
    c = n["config"]
    check(n["type"] == "queue", "queue node survives validation")
    check(c["admitEdge"] == "ea" and c["spillEdge"] == "es", "admit/spill edges kept")
    check(c["maxSlots"] == 4, "maxSlots kept")
    check(c["abortPct"] == 90 and c["spillPct"] == 30, "pcts kept")
    check("preemptPct" not in c and "preemptEnabled" not in c, "no preempt/crown fields on queue node")
    check(c["stickySlotSec"] == 5 and c["keepaliveSec"] == 20, "timers kept")

    # Defaults + clamping + bad edge refs dropped.
    g2 = app.normalize_router_graph({
        "nodes": [{"id": "q2", "type": "queue", "config": {
            "admitEdge": "nope", "spillEdge": "", "maxSlots": "x",
            "abortPct": 999, "spillPct": -5, "keepaliveSec": 1,
        }}],
        "edges": [],
    }, set())
    c2 = g2["nodes"][0]["config"]
    check(c2["admitEdge"] == "", "invalid admit edge dropped")
    check(c2["maxSlots"] is None, "bad maxSlots → None (auto)")
    check(c2["abortPct"] == 100 and c2["spillPct"] == 0, "pcts clamped to [.,100]/[0,.]")
    check(c2["keepaliveSec"] == 5, "keepaliveSec clamped to min 5")
    check(c2["stickySlotSec"] == 20, "stickySlotSec defaults to 20")


# ── helpers to build a router fixture ────────────────────────────────────────
def _router(graph, outputs):
    return {"id": "router:default", "outputs": outputs, "rules": {"default": ""}, "graph": graph}


OUT_A = {"id": "A", "upstreamHost": "10.0.0.1", "upstreamPort": 8080, "upstreamType": "llama"}
OUT_B = {"id": "B", "upstreamHost": "10.0.0.2", "upstreamPort": 8080, "upstreamType": "llama"}
OUT_CLOUD = {"id": "C", "upstreamHost": "api", "upstreamPort": 443, "upstreamType": "cloud",
             "providerId": "blk1", "accountId": "acct1"}


# ── 2. resolve_graph surfaces queue spec + admit path ────────────────────────
def test_resolve_admit():
    print("resolve_graph admit + spec:")
    graph = {
        "nodes": [{"id": "q1", "type": "queue", "x": 0, "y": 0, "config": {
            "admitEdge": "ea", "spillEdge": "es", "maxSlots": 3, "spillPct": 25}}],
        "edges": [
            {"id": "ein", "from": "in:skynet:proxy:8101", "to": "rule:q1"},
            {"id": "ea", "from": "rule:q1", "to": "out:A"},
            {"id": "es", "from": "rule:q1", "to": "out:B"},
        ],
    }
    router = _router(graph, [OUT_A, OUT_B])
    route = {"port": 8101, "upstreamHost": "x", "upstreamPort": 1}
    plan = {}
    out = ap.resolve_graph(router, route, input_ref="in:skynet:proxy:8101", plan_out=plan)
    check(out is OUT_A, "admit path resolves to output A")
    check(plan.get("spec") is not None, "queue spec surfaced into plan_out")
    check(plan["spec"]["maxSlots"] == 3, "spec maxSlots from node")
    check(plan["spec"]["spillRef"] == "out:B", "spec spillRef = spill edge target")


# ── 3. apply_router attaches queuePlan; spill re-resolves ────────────────────
def test_apply_and_spill():
    print("apply_router + apply_router_spill:")
    graph = {
        "nodes": [{"id": "q1", "type": "queue", "config": {
            "admitEdge": "ea", "spillEdge": "es"}}],
        "edges": [
            {"id": "ein", "from": "in:skynet:proxy:8101", "to": "rule:q1"},
            {"id": "ea", "from": "rule:q1", "to": "out:A"},
            {"id": "es", "from": "rule:q1", "to": "out:C"},
        ],
    }
    router = _router(graph, [OUT_A, OUT_CLOUD])
    cfg = {"routers": [router], "policy": {}}
    route = {"port": 8101, "routerId": "router:default", "upstreamType": "llama",
             "upstreamHost": "x", "upstreamPort": 1, "label": "alice primary"}
    resolved = ap.apply_router(route, cfg)
    check(resolved["upstreamHost"] == "10.0.0.1", "apply_router → admit upstream A")
    check(resolved.get("queuePlan", {}).get("spec") is not None, "queuePlan attached")
    spill_ref = resolved["queuePlan"]["spec"]["spillRef"]
    check(spill_ref == "out:C", "spill ref points at cloud output C")

    spilled = ap.apply_router_spill(resolved, cfg, spill_ref)
    check(spilled is not None and spilled["upstreamType"] == "cloud", "spill re-resolves to cloud")
    check(spilled.get("providerId") == "blk1", "spilled cloud carries providerId")
    check("queuePlan" not in spilled, "cloud spill target has no queue plan")


# ── 4. chained queues: spill target carries its own queue node ───────────────
def test_chained_spill():
    print("chained queue spill:")
    graph = {
        "nodes": [
            {"id": "q1", "type": "queue", "config": {"admitEdge": "ea1", "spillEdge": "es1"}},
            {"id": "q2", "type": "queue", "config": {"admitEdge": "ea2", "spillEdge": "es2"}},
        ],
        "edges": [
            {"id": "ein", "from": "in:skynet:proxy:8101", "to": "rule:q1"},
            {"id": "ea1", "from": "rule:q1", "to": "out:A"},
            {"id": "es1", "from": "rule:q1", "to": "rule:q2"},   # spill → second queue
            {"id": "ea2", "from": "rule:q2", "to": "out:B"},
            {"id": "es2", "from": "rule:q2", "to": "out:C"},
        ],
    }
    router = _router(graph, [OUT_A, OUT_B, OUT_CLOUD])
    cfg = {"routers": [router], "policy": {}}
    route = {"port": 8101, "routerId": "router:default", "upstreamType": "llama",
             "upstreamHost": "x", "upstreamPort": 1, "label": "alice primary"}
    r1 = ap.apply_router(route, cfg)
    check(r1["upstreamHost"] == "10.0.0.1", "first admit = A")
    ref1 = r1["queuePlan"]["spec"]["spillRef"]
    check(ref1 == "rule:q2", "first spill → second queue node")
    r2 = ap.apply_router_spill(r1, cfg, ref1)
    check(r2["upstreamHost"] == "10.0.0.2", "second queue admit = B")
    check(r2["queuePlan"]["spec"]["spillRef"] == "out:C", "second spill → cloud C")


# ── 5. implicit default queue: no queue node → no plan, legacy path ──────────
def test_no_queue_node():
    print("no queue node (implicit default queue):")
    graph = {
        "nodes": [],
        "edges": [{"id": "e", "from": "in:skynet:proxy:8101", "to": "out:A"}],
    }
    router = _router(graph, [OUT_A])
    cfg = {"routers": [router], "policy": {}}
    route = {"port": 8101, "routerId": "router:default", "upstreamType": "llama",
             "upstreamHost": "x", "upstreamPort": 1, "label": "alice primary"}
    resolved = ap.apply_router(route, cfg)
    check(resolved["upstreamHost"] == "10.0.0.1", "direct edge resolves to A")
    check("queuePlan" not in resolved, "no queuePlan when no queue node on path")


# ── 6. _queue_spec_from_node policy fallback ─────────────────────────────────
def test_spec_fallback():
    print("_queue_spec_from_node policy fallback:")
    node = {"id": "q", "type": "queue", "config": {"abortPct": 70}}  # rest unset
    policy = {"cloudFallbackPct": 33, "queueKeepaliveSec": 12}
    s = ap._queue_spec_from_node(node, policy)
    check(s["abortPct"] == 70, "explicit abortPct wins")
    check(s["spillPct"] == 33, "spillPct falls back to policy.cloudFallbackPct")
    check(s["keepaliveSec"] == 12, "keepalive from policy")
    check(s["stickySlotSec"] == 20, "stickySlotSec defaults to 20")
    check("preemptPct" not in s and "preemptEnabled" not in s, "no preempt/crown in spec")
    check(s["maxSlots"] is None, "unset maxSlots → None (auto)")


# ── 7. per-input clientTimeoutSeconds override (Stage C) ───────────────────────────
def test_input_wait_override():
    print("graph.inputs clientTimeoutSeconds override:")
    # validation: garbage dropped, 0 dropped, valid kept + clamped
    g = app.normalize_router_graph({
        "nodes": [], "edges": [],
        "inputs": {"skynet:proxy:8101": {"clientTimeoutSeconds": 120},
                   "skynet:proxy:8102": {"clientTimeoutSeconds": 0},
                   "skynet:proxy:8103": {"clientTimeoutSeconds": 999999},
                   "bad": "nope"},
    }, set())
    check(g["inputs"].get("skynet:proxy:8101") == {"clientTimeoutSeconds": 120}, "valid override kept")
    check("skynet:proxy:8102" not in g["inputs"], "0 override dropped (use synced)")
    check(g["inputs"]["skynet:proxy:8103"]["clientTimeoutSeconds"] == 86400, "override clamped to 86400")
    check("bad" not in g["inputs"], "non-dict input dropped")

    # engine: override wins over the route's synced clientTimeoutSeconds
    graph = {"nodes": [], "edges": [{"id": "e", "from": "in:skynet:proxy:8101", "to": "out:A"}],
             "inputs": {"skynet:proxy:8101": {"clientTimeoutSeconds": 150}}}
    router = _router(graph, [OUT_A])
    cfg = {"routers": [router], "policy": {}}
    route = {"port": 8101, "routerId": "router:default", "upstreamType": "llama",
             "upstreamHost": "x", "upstreamPort": 1, "label": "alice primary", "clientTimeoutSeconds": 30}
    resolved = ap.apply_router(route, cfg)
    check(resolved.get("clientTimeoutSeconds") == 150, "input override wins over route value")

    # no override → keep route's synced value
    router2 = _router({"nodes": [], "edges": [{"id": "e", "from": "in:skynet:proxy:8101", "to": "out:A"}]}, [OUT_A])
    resolved2 = ap.apply_router(route, {"routers": [router2], "policy": {}})
    check(resolved2.get("clientTimeoutSeconds") == 30, "no override → route value kept")


if __name__ == "__main__":
    test_validation()
    test_resolve_admit()
    test_apply_and_spill()
    test_chained_spill()
    test_no_queue_node()
    test_spec_fallback()
    test_input_wait_override()
    print()
    if _fail:
        print(f"{len(_fail)} FAILURE(S)")
        sys.exit(1)
    print("ALL PASS")
