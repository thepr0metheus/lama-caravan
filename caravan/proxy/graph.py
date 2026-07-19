"""Router DAG engine: schedule/rule/queue node evaluation, output picking
with capacity checks, spill re-resolution. Pure over the config dict — the
canonical routing logic (tested by scripts/test_queue_node.py)."""
import fnmatch
import random
import threading
import re
import time

from caravan.proxy.capacity import active_count
from caravan.proxy.paths import UPSTREAM_HOST, UPSTREAM_PORT
from caravan.proxy.runtime import slot_total_cache, slot_total_lock


WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

def _hhmm_to_minutes(value):
    try:
        hh, mm = str(value).split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return None

def _schedule_rule_active(rule, lt):
    """True if a schedule rule covers the local-time struct `lt`. Empty days = every
    day; a window with from > to wraps past midnight (e.g. 22:00→06:00)."""
    days = rule.get("days") or []
    if days and WEEKDAY_NAMES[lt.tm_wday] not in days:
        return False
    start = _hhmm_to_minutes(rule.get("from"))
    end = _hhmm_to_minutes(rule.get("to"))
    if start is None or end is None:
        return False
    cur = lt.tm_hour * 60 + lt.tm_min
    if start <= end:
        return start <= cur <= end
    return cur >= start or cur <= end   # wraps midnight

def _output_has_capacity(out, policy):
    """True if this output can take a request right now without queueing. Cloud
    bypasses the slot queue (always True); a llama output is free when its upstream
    group has fewer active requests than its slot total."""
    if str(out.get("upstreamType") or "llama") == "cloud":
        return True
    group = f"{out.get('upstreamHost') or UPSTREAM_HOST}:{int(out.get('upstreamPort') or UPSTREAM_PORT)}"
    total = None
    with slot_total_lock:
        cached = slot_total_cache.get(group)
        if cached:
            total = cached[0]
    if not total or total <= 0:
        total = max(1, int((policy or {}).get("maxSlots") or 1))
    return active_count(group) < total

def pick_router_output(router, route, now=None, policy=None):
    """Choose which output a router routes a request to.

    Precedence: bySource pin > active schedule window > failover/overflow-aware
    default. An explicit pin/schedule is a HARD route (no spill). Otherwise, if a
    failover chain is set, pick the first output in it that has free capacity now;
    if all are busy, use the first in the chain (queue there). With no failover,
    use the default output. Returns an output dict or None."""
    outputs = router.get("outputs") or []
    if not outputs:
        return None
    by_id = {str(o.get("id")): o for o in outputs}
    rules = router.get("rules") if isinstance(router.get("rules"), dict) else {}

    proxy_id = f"skynet:proxy:{route.get('port')}"
    client_id = str(route.get("clientId") or "")
    # 1) Source pin — request entered via this specific proxy/client (hard route).
    for rule in (rules.get("bySource") or []):
        if not isinstance(rule, dict):
            continue
        rp = str(rule.get("proxyId") or "")
        rc = str(rule.get("clientId") or "")
        if (rp and rp == proxy_id) or (rc and rc == client_id):
            out = by_id.get(str(rule.get("output") or ""))
            if out:
                return out

    # 2) Schedule window — first matching rule wins (hard route).
    lt = time.localtime(now) if now is not None else time.localtime()
    for rule in (rules.get("schedule") or []):
        if isinstance(rule, dict) and _schedule_rule_active(rule, lt):
            out = by_id.get(str(rule.get("output") or ""))
            if out:
                return out

    # 3) Failover/overflow — spill to the first output with free capacity.
    chain = [by_id[oid] for oid in (rules.get("failover") or []) if oid in by_id]
    if chain:
        for out in chain:
            if _output_has_capacity(out, policy):
                return out
        return chain[0]   # all busy → queue on the primary

    # 4) Default.
    default_id = str(rules.get("default") or "")
    return by_id.get(default_id) or outputs[0]

# ── Router DAG graph engine (Stage B) ───────────────────────────────────────────
# Walk the optional node graph (validated in app.normalize_router_graph) from the
# request's input node to an output. Node types: byModel / schedule / weighted /
# roundRobin / failover. Returns an output dict, or None to fall back to the legacy
# pick_router_output (rules). An input proxy not wired in the graph → None (legacy).
_rr_state = {}  # (router_id, node_id) -> counter; ephemeral round-robin cursor
_rr_lock = threading.Lock()

def _graph_outgoing(edges, node_ref):
    return [e for e in edges if str(e.get("from")) == node_ref]

def _eval_rule_node(router_id, node, outs, ctx, outputs, policy, now):
    """Pick the outgoing edge's target ('to' ref) for one rule node."""
    ntype = node.get("type")
    cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
    by_id = {str(e.get("id")): e for e in outs}

    def edge_to(eid):
        e = by_id.get(str(eid))
        return e.get("to") if e else None

    if ntype == "byModel":
        model = str((ctx or {}).get("model") or "").strip().lower()
        for case in (cfg.get("cases") or []):
            pat = str(case.get("match") or "").strip().lower()
            if model and pat and fnmatch.fnmatch(model, pat) and edge_to(case.get("edge")):
                return edge_to(case.get("edge"))
        return edge_to(cfg.get("elseEdge")) or outs[0].get("to")
    if ntype == "requestType":
        # Branch on the KIND of request, not its model. Embedding requests
        # (POST /v1/embeddings) leave the dedicated "embed" port; everything
        # else falls through the "__default__" port. Ports are tagged on the
        # edge via schedPortId (reuses the schedule node's port plumbing).
        if (ctx or {}).get("embeddings"):
            e = next((x for x in outs if x.get("schedPortId") == "embed"), None)
            if e and e.get("to"):
                return e.get("to")
        d = (next((x for x in outs if x.get("schedPortId") == "__default__"), None)
             or (outs[0] if outs else None))
        return d.get("to") if d else None
    if ntype == "requestSize":
        # Branch on request SIZE: small asks (max_tokens <= maxTokensAt, e.g.
        # heartbeat replies) leave the "small" port so they don't queue behind
        # big codegen requests. Unknown/absent max_tokens counts as big.
        try:
            thr = int(cfg.get("maxTokensAt") or 300)
        except (TypeError, ValueError):
            thr = 300
        mt = (ctx or {}).get("maxTokens")
        try:
            mt = int(mt) if mt is not None else None
        except (TypeError, ValueError):
            mt = None
        if mt is not None and 0 < mt <= thr:
            e = next((x for x in outs if x.get("schedPortId") == "small"), None)
            if e and e.get("to"):
                return e.get("to")
        d = (next((x for x in outs if x.get("schedPortId") == "__default__"), None)
             or (outs[0] if outs else None))
        return d.get("to") if d else None
    if ntype == "schedule":
        lt = time.localtime(now) if now is not None else time.localtime()
        # New grid-based format
        if "grid" in cfg:
            d, h = lt.tm_wday, lt.tm_hour  # tm_wday: 0=Mon
            grid = cfg.get("grid") or []
            out_id = None
            if d < len(grid):
                row = grid[d]
                if isinstance(row, list) and h < len(row):
                    out_id = row[h]
            if out_id:
                match = next((e for e in outs if e.get("schedPortId") == out_id), None)
                if match:
                    return match.get("to")
            default_e = next((e for e in outs if e.get("schedPortId") == "__default__"), None) or (outs[0] if outs else None)
            return default_e.get("to") if default_e else None
        # Legacy format
        active = any(_schedule_rule_active(w, lt) for w in (cfg.get("windows") or []))
        return edge_to(cfg.get("thenEdge") if active else cfg.get("elseEdge")) or outs[0].get("to")
    if ntype == "weighted":
        weights = [(by_id.get(str(w.get("edge"))), int(w.get("pct") or 0)) for w in (cfg.get("weights") or [])]
        weights = [(e, p) for (e, p) in weights if e and p > 0]
        total = sum(p for _, p in weights)
        if total > 0:
            r, acc = random.uniform(0, total), 0
            for e, p in weights:
                acc += p
                if r <= acc:
                    return e.get("to")
        return outs[0].get("to")
    if ntype == "failover":
        order_ids = cfg.get("order") or [str(e.get("id")) for e in outs]
        chain = [by_id.get(str(eid)) for eid in order_ids if by_id.get(str(eid))] or outs
        for e in chain:
            to = str(e.get("to") or "")
            if to.startswith("out:"):
                out = outputs.get(to[4:])
                if out and _output_has_capacity(out, policy):
                    return to
            else:
                return to   # downstream is another rule node → can't gauge capacity, take it
        return chain[0].get("to")
    if ntype == "roundRobin":
        key = (str(router_id), str(node.get("id")))
        with _rr_lock:
            idx = _rr_state.get(key, 0) % len(outs)
            _rr_state[key] = idx + 1
        return outs[idx].get("to")
    if ntype == "queue":
        # A queue node always routes its happy path down the admit edge; the wait +
        # spill behaviour is run by the handler from the spec resolve_graph surfaces.
        return edge_to(cfg.get("admitEdge")) or outs[0].get("to")
    if ntype == "onError":
        # Happy path always goes down the main edge; the rescue edge is not a
        # routing choice — resolve_graph records it and the handler replays the
        # request there only after the main upstream actually failed.
        return edge_to(cfg.get("mainEdge")) or outs[0].get("to")
    return outs[0].get("to")

def _queue_spec_from_node(node, policy):
    """Build a queue spec from a `queue` graph node's config, falling back to the
    global policy for any unset field. Consumed by wait_for_proxy_slot. `spillRef`
    is filled in by resolve_graph once the spill edge is resolved to a target ref."""
    cfg = node.get("config") if isinstance(node.get("config"), dict) else {}
    pol = policy or {}

    def _i(key, pol_key, default):
        v = cfg.get(key)
        if v is None:
            v = pol.get(pol_key, default)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default
    max_slots = cfg.get("maxSlots")
    try:
        max_slots = int(max_slots) if max_slots is not None else None
    except (TypeError, ValueError):
        max_slots = None
    # NOTE: queue nodes deliberately do NOT use priority/preempt ("crowns") — that
    # mechanic stays only on the implicit default queue (global policy). A queue node
    # is pure FIFO + spill. stickySlotSec defaults to 20 (reserve the slot for the
    # same agent's follow-up calls).
    sticky = cfg.get("stickySlotSec")
    try:
        sticky = int(sticky) if sticky is not None else 20
    except (TypeError, ValueError):
        sticky = 20
    return {
        "nodeId": node.get("id"),
        "maxSlots": max_slots,                                   # None ⇒ auto from /slots
        "abortPct": _i("abortPct", "queueAbortPct", 85),
        "spillPct": _i("spillPct", "cloudFallbackPct", 20),
        "stickySlotSec": sticky,
        "keepaliveSec": _i("keepaliveSec", "queueKeepaliveSec", 20),
        "spillRef": None,                                        # set by resolve_graph
    }

def _label_group(label):
    """Client group from a proxy label, e.g. 'alice fallback' -> 'alice'."""
    m = re.match(r"^(.*)\s+(primary|fallback)$", str(label or "").strip(), re.IGNORECASE)
    return (m.group(1) if m else str(label or "")).strip().lower()

def _effective_input_ref(route, router, config):
    """Which graph input node a request enters at.

    A FALLBACK proxy with no wiring of its own inherits its PRIMARY sibling's input
    (so 'wire the primary' also routes the fallback). Returns 'in:<proxyId>'. If the
    chosen input isn't wired, resolve_graph returns None and we fall back to legacy."""
    pid = f"skynet:proxy:{route.get('port')}"
    edges = (router.get("graph") or {}).get("edges") or []
    def wired(p):
        return any(str(e.get("from")) == f"in:{p}" for e in edges)
    if wired(pid) or str(route.get("role") or "").lower() != "fallback":
        return f"in:{pid}"
    cid = str(route.get("clientId") or "")
    group = _label_group(route.get("label"))
    for r in (config.get("routes") or []):
        if str(r.get("role") or "").lower() != "primary":
            continue
        # Same AGENT (label group) on the same HOST (clientId). clientId alone is the
        # host, so multiple agents share it — match the agent name too.
        same = _label_group(r.get("label")) == group and (not cid or str(r.get("clientId") or "") == cid)
        if same:
            sib_pid = f"skynet:proxy:{r.get('port')}"
            if wired(sib_pid):
                return f"in:{sib_pid}"   # fallback follows primary's route
            break
    return f"in:{pid}"

def resolve_graph(router, route, ctx=None, policy=None, now=None, input_ref=None, plan_out=None):
    """Walk the DAG from `input_ref` (or the route's input proxy) to an output.

    When `plan_out` is given and the walk crosses a `queue` node, the FIRST such
    node's spec (+ resolved spill target ref) is recorded in plan_out so the handler
    can run the wait/spill loop. The returned output is the queue's ADMIT branch."""
    graph = router.get("graph") if isinstance(router.get("graph"), dict) else None
    if not graph:
        return None
    edges = [e for e in (graph.get("edges") or []) if isinstance(e, dict)]
    if not edges:
        return None
    nodes = {str(n.get("id")): n for n in (graph.get("nodes") or []) if isinstance(n, dict)}
    outputs = {str(o.get("id")): o for o in (router.get("outputs") or [])}
    router_id = router.get("id")
    start = input_ref or f"in:skynet:proxy:{route.get('port')}"
    # Unwired-input guard applies only to `in:` starts; explicit out:/rule: starts
    # (used by spill re-resolution) are always walkable.
    if start.startswith("in:") and not _graph_outgoing(edges, start):
        return None  # this input isn't wired → legacy rules
    cur, visited, steps = start, set(), 0
    while steps < 64:
        steps += 1
        if cur.startswith("out:"):
            return outputs.get(cur[4:])
        if cur in visited:
            return None  # cycle guard
        visited.add(cur)
        outs = _graph_outgoing(edges, cur)
        if not outs:
            return None
        if cur.startswith("in:"):
            nxt = outs[0].get("to")
        else:
            node = nodes.get(cur[5:]) if cur.startswith("rule:") else None
            if not node:
                return None
            if (node.get("type") == "queue" and plan_out is not None
                    and not plan_out.get("spec")):
                by_id = {str(e.get("id")): e for e in outs}
                spill_edge = by_id.get(str((node.get("config") or {}).get("spillEdge")))
                spec = _queue_spec_from_node(node, policy)
                spec["spillRef"] = spill_edge.get("to") if spill_edge else None
                plan_out["spec"] = spec
            if node.get("type") == "onError" and plan_out is not None:
                # Collect every rescue exit crossed on the way to the output, in
                # encounter order — the handler consumes them one failure at a time.
                _oe_by_id = {str(e.get("id")): e for e in outs}
                _oe_resc = _oe_by_id.get(str((node.get("config") or {}).get("rescueEdge")))
                if _oe_resc and _oe_resc.get("to"):
                    plan_out.setdefault("rescueRefs", []).append(str(_oe_resc.get("to")))
            nxt = _eval_rule_node(router_id, node, outs, ctx, outputs, policy, now)
        if not nxt:
            return None
        cur = str(nxt)
    return None

def apply_router(route, config, ctx=None):
    """Overlay the router-chosen upstream onto a route (in place on a copy).

    The proxy port is a thin entry point; the router owns the upstream choice.
    A proxy that is UNASSIGNED ("" routerId), bound to a missing router, or
    bound to a router with no usable output is marked `unrouted` → the handler
    returns 503 (the user must bind it to a router with an output). Cloud routes
    are passed through unchanged for now."""
    if str(route.get("upstreamType") or "llama") == "cloud":
        return route
    router_id = str(route.get("routerId") or "")
    if not router_id:
        route = dict(route); route["unrouted"] = "unassigned"; return route
    router = next((s for s in (config.get("routers") or []) if str(s.get("id")) == router_id), None)
    if not router:
        route = dict(route); route["unrouted"] = "router missing"; return route
    # Audio uploads (e.g. POST /v1/audio/transcriptions) go to a dedicated output that accepts an
    # audio file — NOT the chat route, which for a cloud output gets translated to a chat API and
    # 400s on the multipart body. Configurable per-router via rules.audioOutput (an output id);
    # picking a local "llama" output makes the handler forward the upload untouched.
    if ctx and ctx.get("audio"):
        audio_out_id = str((router.get("rules") or {}).get("audioOutput") or "")
        if audio_out_id:
            aout = next((o for o in (router.get("outputs") or []) if str(o.get("id")) == audio_out_id), None)
            if aout:
                return _overlay_output(route, aout)
    # Embeddings are a fleet-wide concern: EVERY client posts /v1/embeddings, so they
    # get a single global output (rules.embeddingsOutput) checked here, before the
    # graph — no per-route wiring, no requestType node. Empty = unconfigured → the
    # request falls through to the chat graph (and 400s), which the UI flags.
    if ctx and ctx.get("embeddings"):
        embed_out_id = str((router.get("rules") or {}).get("embeddingsOutput") or "")
        if embed_out_id:
            eout = next((o for o in (router.get("outputs") or []) if str(o.get("id")) == embed_out_id), None)
            if eout:
                return _overlay_output(route, eout)
    # n8n-style graph first (when this input is wired); else legacy rules. A fallback
    # proxy with no wiring of its own inherits its primary sibling's input node.
    input_ref = _effective_input_ref(route, router, config)
    plan = {}
    out = resolve_graph(router, route, ctx=ctx, policy=config.get("policy"),
                        input_ref=input_ref, plan_out=plan)
    if out is None:
        out = pick_router_output(router, route, policy=config.get("policy"))
    if not out:
        route = dict(route); route["unrouted"] = "no output"; return route
    resolved = _overlay_output(route, out, plan.get("spec"))
    if plan.get("rescueRefs"):
        resolved["rescueRefs"] = plan["rescueRefs"]
    # Per-input override: graph.inputs[<proxyId>].clientTimeoutSeconds (set on the canvas input
    # node) wins over the auto-synced route value. input_ref is "in:<proxyId>".
    inputs = (router.get("graph") or {}).get("inputs") if isinstance(router.get("graph"), dict) else None
    if isinstance(inputs, dict):
        ov = inputs.get(str(input_ref)[3:]) if str(input_ref).startswith("in:") else None
        wt = int((ov or {}).get("clientTimeoutSeconds") or 0)
        if wt > 0:
            resolved["clientTimeoutSeconds"] = wt
    return resolved

def _overlay_output(route, out, queue_spec=None):
    """Overlay a resolved output onto a route copy. When queue_spec is set (the path
    crossed a queue node), stash it under `queuePlan` for the handler's wait/spill loop."""
    resolved = dict(route)
    resolved["upstreamHost"] = str(out.get("upstreamHost") or route.get("upstreamHost"))
    resolved["upstreamPort"] = int(out.get("upstreamPort") or route.get("upstreamPort"))
    out_type = str(out.get("upstreamType") or "llama")
    resolved["upstreamType"] = out_type
    resolved["routedOutputId"] = str(out.get("id") or "")
    resolved["routedOutputName"] = str(out.get("name") or "")
    if out_type == "cloud":
        # providerId = a model-block; empty = passthrough → resolve the account directly.
        resolved["providerId"] = str(out.get("providerId") or "")
        resolved["cloudAccountId"] = str(out.get("accountId") or "")
    resolved.pop("queuePlan", None)
    resolved.pop("rescueRefs", None)
    if queue_spec:
        resolved["queuePlan"] = {"spec": queue_spec}
    return resolved

def apply_router_spill(route, config, spill_ref, ctx=None):
    """Re-resolve a route from a queue node's spill target (an out:/rule: ref) when
    its queue overflows. Returns a new resolved route (possibly carrying its own
    queuePlan for a chained queue), or None if the spill target is unroutable."""
    router_id = str(route.get("routerId") or "")
    router = next((s for s in (config.get("routers") or []) if str(s.get("id")) == router_id), None)
    if not router or not spill_ref:
        return None
    plan = {}
    out = resolve_graph(router, route, ctx=ctx, policy=config.get("policy"),
                        input_ref=str(spill_ref), plan_out=plan)
    if not out:
        return None
    resolved = _overlay_output(route, out, plan.get("spec"))
    if plan.get("rescueRefs"):
        resolved["rescueRefs"] = plan["rescueRefs"]
    return resolved
