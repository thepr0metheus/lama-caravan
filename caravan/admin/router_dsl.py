"""Router/graph normalization: routers, outputs, rule/queue/schedule nodes and
proxy-route records. Pure validation — no file I/O."""
import re

from caravan.common.errors import AppError


# ── Router (Роутер) — Stage 1 ──────────────────────────────────────────
# The single shared router every proxy feeds into by default. Users may split
# traffic into more routers later; this one always exists.
DEFAULT_ROUTER_ID = "router:default"

# Canonical address of the controller's local llama-server — the default output.
DEFAULT_UPSTREAM_HOST = "127.0.0.1"

DEFAULT_UPSTREAM_PORT = 8080

def _role_from_label(label):
    """Best-effort primary/fallback role from a 'name primary'/'name fallback' label."""
    match = re.match(r"^.*\s+(primary|fallback)$", str(label or "").strip(), re.IGNORECASE)
    return match.group(1).lower() if match else "primary"

def _default_router_output():
    """The out-of-the-box single output: controller's local llama-server."""
    return {
        "id": "o1",
        "label": f"llama :{DEFAULT_UPSTREAM_PORT}",
        # `target` = topology anchor id for the SVG cable to the Llama Servers lane.
        "target": f"skynet:llama-server:{DEFAULT_UPSTREAM_PORT}",
        # Concrete addressing consumed by agent-proxies.py (self-contained, no topology).
        "upstreamHost": DEFAULT_UPSTREAM_HOST,
        "upstreamPort": DEFAULT_UPSTREAM_PORT,
        "upstreamType": "llama",
        "providerId": "",
    }

def normalize_router_output(out):
    out = out if isinstance(out, dict) else {}
    upstream_type = str(out.get("upstreamType") or "llama").strip().lower()
    if upstream_type not in ("llama", "cloud"):
        upstream_type = "llama"
    norm = {
        "id": str(out.get("id") or "").strip() or "o1",
        "label": str(out.get("label") or "").strip()[:80],
        "target": str(out.get("target") or "").strip(),
        "upstreamHost": str(out.get("upstreamHost") or DEFAULT_UPSTREAM_HOST).strip() or DEFAULT_UPSTREAM_HOST,
        "upstreamPort": int(out.get("upstreamPort") or DEFAULT_UPSTREAM_PORT),
        "upstreamType": upstream_type,
        "providerId": str(out.get("providerId") or "").strip(),
    }
    # Cloud outputs carry the account they belong to (the model = the chosen block
    # in providerId). Cloud has unlimited concurrency (no slot accounting).
    if upstream_type == "cloud":
        norm["accountId"] = str(out.get("accountId") or "").strip()
    return norm

def normalize_router(router):
    """Validate one router. `inputs` is NOT stored — it is derived from which
    proxy routes carry this router's id (single source of truth). Stage 1 only
    honours rules.default; schedule/bySource are persisted for later stages."""
    router = router if isinstance(router, dict) else {}
    outputs = [normalize_router_output(o) for o in (router.get("outputs") or [])]
    if not outputs:
        outputs = [_default_router_output()]
    out_ids = {o["id"] for o in outputs}
    rules = router.get("rules") if isinstance(router.get("rules"), dict) else {}
    default_out = str(rules.get("default") or "").strip()
    if default_out not in out_ids:
        default_out = outputs[0]["id"]
    schedule = [r for r in (normalize_schedule_rule(r, out_ids) for r in (rules.get("schedule") or [])) if r]
    by_source = [r for r in (normalize_by_source_rule(r, out_ids) for r in (rules.get("bySource") or [])) if r]
    # Failover/overflow chain: ordered output ids. When the chosen output is busy
    # (no free slot), the runtime spills to the next one in this list. Keep only
    # known output ids, de-duplicated, preserving order.
    failover = []
    for oid in (rules.get("failover") or []):
        oid = str(oid)
        if oid in out_ids and oid not in failover:
            failover.append(oid)
    return {
        "id": str(router.get("id") or "").strip() or DEFAULT_ROUTER_ID,
        "name": str(router.get("name") or "").strip()[:80] or "Default",
        "outputs": outputs,
        # audioOutput / embeddingsOutput: fleet-wide short-circuit outputs (apply_router
        # checks them before the graph). Preserved only when they name a real output.
        "rules": {"default": default_out, "schedule": schedule, "bySource": by_source, "failover": failover,
                  **({"audioOutput": str(rules.get("audioOutput"))} if str(rules.get("audioOutput") or "") in out_ids else {}),
                  **({"embeddingsOutput": str(rules.get("embeddingsOutput"))} if str(rules.get("embeddingsOutput") or "") in out_ids else {}),
                  # The default that pointed at a vanished output — stashed by
                  # sync_router_outputs and restored by it when the output returns.
                  **({"dormantDefault": str(rules.get("dormantDefault"))} if str(rules.get("dormantDefault") or "").strip() else {})},
        # Optional n8n-style routing graph (Stage B). Empty ⇒ legacy `rules` apply.
        "graph": normalize_router_graph(router.get("graph"), out_ids),
    }

# ── Router DAG graph (Stage B) ──────────────────────────────────────────────────
# An optional node graph layered over `rules`. Nodes are RULE nodes only; inputs and
# outputs are implicit refs ("in:<proxyId>" / "out:<outputId>"). Edges connect refs.
# The runtime (agent-proxies.resolve_graph) walks it from the request's input node to
# an output; an input not wired in the graph falls back to the legacy rules. Garbage
# is dropped, never raised — a malformed graph just degrades to legacy routing.
ROUTER_NODE_TYPES = ("byModel", "schedule", "weighted", "roundRobin", "failover", "queue", "requestType", "requestSize", "onError")

def _valid_edge_ref(ref, node_ids, out_ids):
    ref = str(ref or "")
    if ref.startswith("in:"):
        return bool(ref[3:])
    if ref.startswith("rule:"):
        return ref[5:] in node_ids
    if ref.startswith("out:"):
        out_id = ref[4:]
        # srv:<port> / cb:<blockId> outputs are stable-keyed — keep canvas edges
        # even when the target is temporarily gone (server offline / model block
        # deleted). The cable simply won't render and the graph walker returns
        # None for the missing output (→ legacy-rules fallback), but the edge —
        # and any queue admit/spill role naming it — is preserved, so the wiring
        # auto-restores the moment an output with the same id reappears.
        if out_id.startswith("srv:") or out_id.startswith("cb:"):
            return True
        return out_id in out_ids
    return False

def _normalize_node_config(node_type, cfg, edge_ids):
    cfg = cfg if isinstance(cfg, dict) else {}
    if node_type == "byModel":
        cases = []
        for c in (cfg.get("cases") or []):
            if not isinstance(c, dict):
                continue
            edge = str(c.get("edge") or "")
            match = str(c.get("match") or "").strip()
            if edge in edge_ids and match:
                cases.append({"match": match[:120], "edge": edge})
        else_edge = str(cfg.get("elseEdge") or "")
        return {"cases": cases, "elseEdge": else_edge if else_edge in edge_ids else ""}
    if node_type == "schedule":
        # New grid-based format (outputs + grid).  Legacy windows/thenEdge/elseEdge passed through unchanged.
        if "grid" in cfg or "outputs" in cfg:
            outputs = []
            for o in (cfg.get("outputs") or []):
                if not isinstance(o, dict):
                    continue
                oid = str(o.get("id") or "").strip()
                name = str(o.get("name") or "output").strip()[:40]
                if oid:
                    outputs.append({"id": oid, "name": name})
            out_ids_sched = {o["id"] for o in outputs}
            raw_grid = cfg.get("grid") or []
            grid = []
            for row in list(raw_grid)[:7]:
                if not isinstance(row, list):
                    grid.append([None] * 24)
                    continue
                grid.append([(cell if isinstance(cell, str) and cell in out_ids_sched else None) for cell in (list(row) + [None] * 24)[:24]])
            while len(grid) < 7:
                grid.append([None] * 24)
            return {"outputs": outputs, "grid": grid}
        # Legacy format: windows + thenEdge + elseEdge
        windows = []
        for w in (cfg.get("windows") or []):
            if not isinstance(w, dict):
                continue
            days = [d for d in (str(x).strip().lower()[:3] for x in (w.get("days") or [])) if d in WEEKDAY_NAMES]
            windows.append({"days": days, "from": _normalize_hhmm(w.get("from"), "00:00"), "to": _normalize_hhmm(w.get("to"), "23:59")})
        then_edge = str(cfg.get("thenEdge") or "")
        else_edge = str(cfg.get("elseEdge") or "")
        return {"windows": windows, "thenEdge": then_edge if then_edge in edge_ids else "", "elseEdge": else_edge if else_edge in edge_ids else ""}
    if node_type == "weighted":
        weights = []
        for wt in (cfg.get("weights") or []):
            if not isinstance(wt, dict):
                continue
            edge = str(wt.get("edge") or "")
            if edge not in edge_ids:
                continue
            try:
                pct = max(0, min(100, int(wt.get("pct") or 0)))
            except Exception:
                pct = 0
            weights.append({"edge": edge, "pct": pct})
        return {"weights": weights}
    if node_type == "failover":
        order = []
        for eid in (cfg.get("order") or []):
            eid = str(eid)
            if eid in edge_ids and eid not in order:
                order.append(eid)
        return {"order": order}
    if node_type == "queue":
        # A bottleneck node: requests wait here for a slot on the admit-edge upstream.
        # admitEdge = the guarded output (happy path); spillEdge = where to divert at
        # spillPct (generalises the old per-route cloudFallbackProviderId to ANY target).
        # Mechanism params override the global policy for traffic crossing THIS node;
        # null maxSlots = auto-track from the upstream's /slots (--parallel).
        def _qint(key, default, lo, hi):
            try:
                return max(lo, min(hi, int(cfg.get(key, default))))
            except (TypeError, ValueError):
                return default
        admit = str(cfg.get("admitEdge") or "")
        spill = str(cfg.get("spillEdge") or "")
        max_slots = cfg.get("maxSlots")
        if max_slots is not None:
            try:
                max_slots = max(1, min(64, int(max_slots)))
            except (TypeError, ValueError):
                max_slots = None
        # Queue nodes are pure FIFO + spill — NO priority/preempt ("crowns").
        # stickySlotSec = per-block reservation for an agent's follow-up calls (default 20).
        return {
            "admitEdge": admit if admit in edge_ids else "",
            "spillEdge": spill if spill in edge_ids else "",
            "maxSlots": max_slots,  # None ⇒ auto from upstream /slots
            "abortPct": _qint("abortPct", 85, 1, 100),
            "spillPct": _qint("spillPct", 20, 0, 100),
            "stickySlotSec": _qint("stickySlotSec", 20, 0, 120),
            "keepaliveSec": _qint("keepaliveSec", 20, 5, 120),
        }
    if node_type == "onError":
        # Two-exit rescue node: requests route down mainEdge; when the upstream
        # leg FAILS (connect error or HTTP >= 400) before a single byte reached
        # the client, the handler replays the same request down rescueEdge.
        # Capacity plays no part — this is redundancy, not load management.
        main = str(cfg.get("mainEdge") or "")
        resc = str(cfg.get("rescueEdge") or "")
        return {
            "mainEdge": main if main in edge_ids else "",
            "rescueEdge": resc if resc in edge_ids else "",
        }
    if node_type == "requestSize":
        # Small-request branch: keep the max_tokens threshold (ports live on the
        # edges as schedPortId "small"/"__default__", nothing else to persist).
        try:
            thr = max(1, min(100000, int(cfg.get("maxTokensAt", 300))))
        except (TypeError, ValueError):
            thr = 300
        return {"maxTokensAt": thr}
    return {}  # roundRobin (uses all outgoing edges) + unknown

def normalize_router_graph(raw, out_ids):
    """Validate the optional routing graph. Returns {nodes:[], edges:[]} (empty when
    absent/garbage). Edge refs are checked against node ids + output ids; node configs
    are checked against the surviving edge ids."""
    raw = raw if isinstance(raw, dict) else {}
    nodes, node_ids = [], set()
    for n in (raw.get("nodes") or []):
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or "").strip()
        ntype = str(n.get("type") or "").strip()
        if not nid or nid in node_ids or ntype not in ROUTER_NODE_TYPES:
            continue
        node_ids.add(nid)
        try:
            x, y = int(n.get("x") or 0), int(n.get("y") or 0)
        except Exception:
            x, y = 0, 0
        nodes.append({"id": nid, "type": ntype, "x": x, "y": y, "config": n.get("config") if isinstance(n.get("config"), dict) else {}})
    edges, edge_ids, seen_pairs = [], set(), set()
    for e in (raw.get("edges") or []):
        if not isinstance(e, dict):
            continue
        frm, to = str(e.get("from") or "").strip(), str(e.get("to") or "").strip()
        if frm == to or not _valid_edge_ref(frm, node_ids, out_ids) or not _valid_edge_ref(to, node_ids, out_ids):
            continue
        if (frm, to) in seen_pairs:
            continue
        eid = str(e.get("id") or "").strip() or f"e{len(edges) + 1}"
        while eid in edge_ids:
            eid = f"e{len(edges) + 1}_{eid}"
        seen_pairs.add((frm, to))
        edge_ids.add(eid)
        edge_dict = {"id": eid, "from": frm, "to": to}
        sched_port = str(e.get("schedPortId") or "").strip()
        if sched_port:
            edge_dict["schedPortId"] = sched_port
        edges.append(edge_dict)
    for n in nodes:
        n["config"] = _normalize_node_config(n["type"], n.get("config"), edge_ids)
    # Per-input source overrides keyed by proxyId ("skynet:proxy:<port>"). Currently just
    # clientTimeoutSeconds — the client's wait budget that the queue %% thresholds scale against.
    # A 0/absent override means "use the auto-synced route value".
    inputs = {}
    raw_inputs = raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {}
    for pid, cfg in raw_inputs.items():
        if not isinstance(cfg, dict):
            continue
        try:
            wt = max(0, min(86400, int(cfg.get("clientTimeoutSeconds") or 0)))
        except (TypeError, ValueError):
            wt = 0
        if wt > 0:
            inputs[str(pid)] = {"clientTimeoutSeconds": wt}
    return {"nodes": nodes, "edges": edges, "inputs": inputs}

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

def _normalize_hhmm(value, fallback):
    """Clamp a 'HH:MM' string to a valid 24h time; return fallback on garbage."""
    match = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(value or ""))
    if not match:
        return fallback
    hh = min(23, max(0, int(match.group(1))))
    mm = min(59, max(0, int(match.group(2))))
    return f"{hh:02d}:{mm:02d}"

def normalize_schedule_rule(rule, out_ids):
    """A time-window rule: {days:[mon..sun], from:'HH:MM', to:'HH:MM', output}.
    Empty days = every day. A window with from > to wraps past midnight. Dropped
    (→ None) if the output is unknown."""
    if not isinstance(rule, dict):
        return None
    output = str(rule.get("output") or "").strip()
    if output not in out_ids:
        return None
    days = [d for d in (str(x).strip().lower()[:3] for x in (rule.get("days") or [])) if d in WEEKDAY_NAMES]
    return {
        "days": days,
        "from": _normalize_hhmm(rule.get("from"), "00:00"),
        "to": _normalize_hhmm(rule.get("to"), "23:59"),
        "output": output,
    }

def normalize_by_source_rule(rule, out_ids):
    """A source-pin rule: route requests entering via a given proxy/client to an
    output. {proxyId?, clientId?, output}. Needs at least one selector + valid output."""
    if not isinstance(rule, dict):
        return None
    output = str(rule.get("output") or "").strip()
    if output not in out_ids:
        return None
    proxy_id = str(rule.get("proxyId") or "").strip()
    client_id = str(rule.get("clientId") or "").strip()
    if not proxy_id and not client_id:
        return None
    return {"proxyId": proxy_id, "clientId": client_id, "output": output}

def normalize_agent_proxy_route(route):
    label = str(route.get("label") or "").strip()[:80]
    port = int(route.get("port"))
    upstream_host = str(route.get("upstreamHost") or "127.0.0.1").strip()
    upstream_port = int(route.get("upstreamPort") or 8080)
    if not label:
        raise AppError("label is required", 400)
    if port < 1024 or port > 65535:
        raise AppError("proxy port must be 1024..65535", 400)
    if upstream_port < 1 or upstream_port > 65535:
        raise AppError("upstream port must be 1..65535", 400)
    if not re.match(r"^[A-Za-z0-9_.:-]+$", upstream_host):
        raise AppError("upstream host contains unsupported characters", 400)
    upstream_type = str(route.get("upstreamType") or "llama").strip().lower()
    if upstream_type not in ("llama", "cloud"):
        upstream_type = "llama"
    provider_id = str(route.get("providerId") or "").strip()
    # "" = an agent port (default). "service" = a bridge port for an external
    # consumer (e.g. a voice app): route-level cloud upstream, no router, no agent
    # semantics — the kanban, OpenClaw sync and ↑☁ eligibility all skip it.
    kind = str(route.get("kind") or "").strip().lower()
    if kind not in ("", "service"):
        kind = ""
    return {
        "label": label,
        "port": port,
        "kind": kind,
        "upstreamHost": upstream_host,
        "upstreamPort": upstream_port,
        "upstreamType": upstream_type,
        "providerId": provider_id,
        "enabled": bool(route.get("enabled", True)),
        "mode": str(route.get("mode") or "open").strip().lower(),
        # Data-plane auth: when set, the proxy port demands this key as
        # `Authorization: Bearer …` (or x-api-key). Empty = open (default).
        "apiKey": str(route.get("apiKey") or "").strip()[:128],
        "priority": int(route.get("priority") or 0),
        "preemptible": bool(route.get("preemptible", True)),
        # Client wait timeout (seconds) — synced from OpenClaw config by admin.
        # Used as base for percentage-based queue thresholds.
        "clientTimeoutSeconds": max(0, int(route.get("clientTimeoutSeconds") or 0)),
        # Cloud fallback provider block id — set when the user activates the ↑☁ ability.
        # Non-empty = ability ACTIVE (queued request forwards to this cloud provider).
        "cloudFallbackProviderId": str(route.get("cloudFallbackProviderId") or "").strip(),
        # Whether the ↑☁ toggle button is OFFERED on this proxy card. Recomputed from
        # graph connections (true only for a local route whose client group has a cloud
        # sibling). Presence of the button does NOT grant the ability — the user must
        # still toggle it on, just like the priority crown.
        "cloudFallbackEligible": bool(route.get("cloudFallbackEligible", False)),
        # Per-route queue threshold overrides (0-100). When present they take precedence
        # over the global policy percentages for this specific route.
        # null / absent = inherit from global policy.
        **{k: max(0, min(100, int(route[k])))
           for k in ("cloudFallbackPct", "priorityPreemptPct", "queueAbortPct")
           if route.get(k) is not None},
        # ── Router redesign (Stage 1) ──────────────────────────────────────
        # A proxy port is now a thin entry point that feeds a router
        # (Роутер). The router owns the routing decision (which upstream
        # server, by schedule/source). `routerId` binds this proxy to one.
        # `role`/`clientId` make the proxy↔client/primary-fallback relationship
        # explicit instead of being inferred from the label suffix.
        # An ABSENT routerId defaults to router:default (fresh proxy); an EXPLICIT
        # empty string ("") means "unassigned" (free) — not routed by any router,
        # which the runtime treats as 503 until the user binds it. Bridge ports
        # are ALWAYS router-free: their routing is the route-level cloud pin,
        # and no client rebuild may re-attach them to a router.
        "routerId": ("" if kind == "service"
                     else DEFAULT_ROUTER_ID if route.get("routerId") is None
                     else str(route.get("routerId")).strip()),
        "role": (str(route.get("role") or "").strip().lower() or _role_from_label(route.get("label"))),
        "clientId": str(route.get("clientId") or "").strip(),
    }

def _proxy_group_key(label):
    """Group proxies by their label prefix, e.g. 'alice primary'/'alice fallback' -> 'alice'."""
    match = re.match(r"^(.*)\s+(primary|fallback)$", str(label or "").strip(), re.IGNORECASE)
    base = (match.group(1) if match else str(label or "")).strip().lower()
    return base

def recompute_cloud_fallback_eligibility(routes):
    """Re-evaluate the ↑☁ cloud-fallback eligibility for every route, in place.

    A local (llama) route is eligible when its client group (same label prefix) has at
    least one cloud route with a providerId. Ineligible routes have their active toggle
    cleared; active eligible routes are re-pointed to the group's current cloud provider
    (handles the cloud sibling being reconnected to a different provider)."""
    if not isinstance(routes, list):
        return
    group_cloud = {}
    for route in routes:
        if not isinstance(route, dict):
            continue
        if str(route.get("kind") or "") == "service":
            continue  # bridge ports never act as a group's cloud sibling
        if str(route.get("upstreamType") or "llama").strip().lower() == "cloud":
            pid = str(route.get("providerId") or "").strip()
            if pid:
                group_cloud.setdefault(_proxy_group_key(route.get("label")), pid)
    for route in routes:
        if not isinstance(route, dict):
            continue
        if str(route.get("kind") or "") == "service":
            continue  # ↑☁ is an agent-route ability; leave bridges untouched
        is_cloud = str(route.get("upstreamType") or "llama").strip().lower() == "cloud"
        cloud_pid = group_cloud.get(_proxy_group_key(route.get("label")), "")
        eligible = bool(cloud_pid) and not is_cloud
        route["cloudFallbackEligible"] = eligible
        if eligible:
            # Keep the active toggle pointed at the group's current cloud provider.
            if str(route.get("cloudFallbackProviderId") or "").strip():
                route["cloudFallbackProviderId"] = cloud_pid
        else:
            route["cloudFallbackProviderId"] = ""

def normalize_agent_proxy_policy(policy):
    policy = policy if isinstance(policy, dict) else {}
    def int_value(key, default, minimum, maximum):
        try:
            value = int(policy.get(key, default))
        except Exception:
            value = default
        return min(max(value, minimum), maximum)
    return {
        "maxSlots": int_value("maxSlots", 1, 1, 64),
        "cloudFallbackPct": int_value("cloudFallbackPct", 20, 0, 100),
        "priorityPreemptPct": int_value("priorityPreemptPct", 50, 0, 100),
        "queueAbortPct": int_value("queueAbortPct", 85, 1, 100),
        "preemptGraceSec": int_value("preemptGraceSec", 20, 1, 300),
        "preemptEnabled": bool(policy.get("preemptEnabled", True)),
        "stickySlotSec": int_value("stickySlotSec", 0, 0, 120),
    }
