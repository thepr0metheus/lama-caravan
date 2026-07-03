"""agent-proxies.json I/O and mutation: routes, routers, policy. Every write
funnels through write_agent_proxy_payload (with the kanban-graph autobackup)."""
import json

from caravan.admin.cloud import cloud_blocks_state, load_cloud_data, save_cloud_data
from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE, AGENT_PROXY_SERVICE_NAME
from caravan.admin.router_dsl import (
    DEFAULT_ROUTER_ID,
    normalize_agent_proxy_policy,
    normalize_agent_proxy_route,
    normalize_router,
    normalize_router_output,
    recompute_cloud_fallback_eligibility,
)
from caravan.admin.systemd_ctl import systemctl
from caravan.common.errors import AppError
from caravan.common.fsio import atomic_write_text


DEFAULT_AGENT_PROXY_ROUTES = [
    {"label": "jim", "port": 8083, "upstreamHost": "127.0.0.1", "upstreamPort": 8080, "enabled": True},
    {"label": "pam", "port": 8084, "upstreamHost": "127.0.0.1", "upstreamPort": 8080, "enabled": True},
    {"label": "michael", "port": 8085, "upstreamHost": "127.0.0.1", "upstreamPort": 8080, "enabled": True},
    {"label": "dwight", "port": 8086, "upstreamHost": "127.0.0.1", "upstreamPort": 8080, "enabled": True},
]

def _migrate_legacy_router_payload(payload):
    """Back-compat: upgrade the pre-rename 'switchboard' schema to 'router' in place.

    Old files (e.g. Skynet's agent-proxies.json before this refactor) carry the key
    `switchboards[]`, the id `sb:default`, and per-route `switchboardId`. Rewrite them
    to the new router schema. Idempotent — no-op once the file has been written back
    in the new shape. The OLD literals must NOT be renamed by the rename script, which
    is why this lives in a dedicated function added after the rename."""
    if not isinstance(payload, dict):
        return payload
    legacy_id, new_id = "sb:default", DEFAULT_ROUTER_ID
    if "routers" not in payload and isinstance(payload.get("switchboards"), list):
        payload["routers"] = payload.pop("switchboards")
    for router in (payload.get("routers") or []):
        if isinstance(router, dict) and router.get("id") == legacy_id:
            router["id"] = new_id
    for route in (payload.get("routes") or []):
        if not isinstance(route, dict):
            continue
        if "routerId" not in route and "switchboardId" in route:
            route["routerId"] = route.pop("switchboardId")
        if route.get("routerId") == legacy_id:
            route["routerId"] = new_id
    return payload

def read_agent_proxy_payload():
    if AGENT_PROXY_CONFIG_FILE.exists():
        try:
            payload = json.loads(AGENT_PROXY_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return _migrate_legacy_router_payload(payload)
        except Exception:
            pass
    return {"routes": DEFAULT_AGENT_PROXY_ROUTES, "policy": normalize_agent_proxy_policy({}),
            "routers": [], "stopRequests": []}

def write_agent_proxy_payload(payload):
    # Keep ↑☁ cloud-fallback eligibility in sync with the current graph connections
    # on every write (this is the single choke point for all proxy-config changes).
    try:
        if isinstance(payload, dict):
            recompute_cloud_fallback_eligibility(payload.get("routes"))
            # Keep routers (default exists, orphans re-pointed, inputs derived)
            # consistent with the routes on every write — single source of truth.
            if "routers" in payload or payload.get("routes"):
                payload["routers"] = normalize_routers(
                    payload.get("routers"), payload.get("routes"))
    except Exception:
        pass
    # ── Защита графа: если новая запись уничтожает непустой граф — сохраняем его ──
    # Перед каждой перезаписью проверяем: если в текущем файле есть nodes/edges,
    # а в новом payload их нет — восстанавливаем граф из старой версии.
    # Также делаем резервную копию каждый раз когда в файле есть граф с узлами.
    try:
        if AGENT_PROXY_CONFIG_FILE.exists():
            old_raw = json.loads(AGENT_PROXY_CONFIG_FILE.read_text(encoding="utf-8"))
            old_graph_nodes = []
            for r in (old_raw.get("routers") or []):
                old_graph_nodes.extend(r.get("graph", {}).get("nodes") or [])
            if old_graph_nodes:
                # Есть живые узлы — сохраняем бэкап
                import datetime as _dt
                ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                bak = AGENT_PROXY_CONFIG_FILE.with_name(f"{AGENT_PROXY_CONFIG_FILE.stem}.json.bak-graph-{ts}")
                bak.write_text(AGENT_PROXY_CONFIG_FILE.read_text(encoding="utf-8"), encoding="utf-8")
                # Если новый payload теряет граф — восстанавливаем из старого
                new_graph_nodes = []
                for r in (payload.get("routers") or []):
                    new_graph_nodes.extend(r.get("graph", {}).get("nodes") or [])
                if not new_graph_nodes:
                    # Перенести граф из старой версии в новую
                    old_by_id = {r["id"]: r for r in (old_raw.get("routers") or []) if r.get("id")}
                    for r in (payload.get("routers") or []):
                        if not r.get("graph", {}).get("nodes") and r.get("id") in old_by_id:
                            r["graph"] = old_by_id[r["id"]].get("graph") or r.get("graph") or {}
    except Exception:
        pass
    atomic_write_text(AGENT_PROXY_CONFIG_FILE, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

def load_agent_proxy_config():
    payload = read_agent_proxy_payload()
    routes = payload.get("routes") if isinstance(payload.get("routes"), list) else DEFAULT_AGENT_PROXY_ROUTES
    cleaned = []
    seen = set()
    for route in routes:
        try:
            row = normalize_agent_proxy_route(route)
        except Exception:
            continue
        if row["port"] in seen:
            continue
        seen.add(row["port"])
        cleaned.append(row)
    routers = normalize_routers(payload.get("routers"), cleaned)
    return {
        "routes": cleaned,
        "policy": normalize_agent_proxy_policy(payload.get("policy")),
        "routers": routers,
        "stopRequests": (payload.get("stopRequests") if isinstance(payload.get("stopRequests"), list) else [])[-100:],
    }

def _router_local_outputs(server_obj):
    """Auto-outputs = one per local llama server. Stable id `srv:<port>` so rules
    keep referencing the same output across restarts."""
    outs = []
    seen = set()
    for s in (server_obj.get("llamaServers") or []):
        port = s.get("port")
        if not port or port in seen:
            continue
        seen.add(port)
        host = "127.0.0.1" if s.get("isController") else (s.get("clientIp") or "127.0.0.1")
        node = "skynet" if s.get("isController") else (s.get("clientIp") or "node")
        model = str(s.get("model") or "").split("/")[-1]
        outs.append({
            "id": f"srv:{port}",
            "label": (f"{model} " if model else "") + f":{port}",
            "target": f"{node}:llama-server:{port}",
            "upstreamHost": host,
            "upstreamPort": int(port),
            "upstreamType": "llama",
            "providerId": "",
        })
    return outs

def _router_cloud_outputs(accounts, blocks):
    """One AUTO-output per EXPOSED cloud model-block (ticked in the router Outputs
    panel). Stable id `cb:<blockId>`; the model = the block's `model`, the account
    is the provider. Cloud = unlimited concurrency. A provider with no exposed blocks
    contributes no outputs (it still shows as a collapsible header in the UI)."""
    acc_by_id = {a.get("id"): a for a in (accounts or []) if a.get("id")}
    outs = []
    for b in (blocks or []):
        if not b.get("exposed"):
            continue
        acc_id = b.get("accountId")
        if acc_id not in acc_by_id:
            continue
        bid = b.get("id")
        model = str(b.get("model") or b.get("name") or bid)
        outs.append({
            "id": f"cb:{bid}",
            "label": f"☁ {model}",
            "target": f"cloud:{acc_id}",
            "upstreamHost": "",
            "upstreamPort": 0,
            "upstreamType": "cloud",
            "providerId": bid,
            "accountId": acc_id,
        })
    return outs

def migrate_legacy_cloud_outputs(routers, account_ids):
    """One-time upgrade: the OLD model was one output `cloud:<accountId>` whose chosen
    model lived in providerId. The NEW model is one output `cb:<blockId>` per EXPOSED
    block. So: expose the previously-chosen block(s) and remap every reference from the
    legacy id → `cb:<blockId>` so nothing routing-related is lost:
      - rules.default / bySource[].output / schedule[].output / failover[]
      - graph edges (edge.from / edge.to that referenced `out:cloud:<accId>`)
    Idempotent (legacy ids vanish after the first sync). Returns True if cloud data
    (block exposure) changed."""
    legacy_ids = {f"cloud:{a}" for a in (account_ids or [])}
    expose = set()
    # Build per-router old-output-id → new-output-id maps from the legacy cloud outputs.
    remaps = []
    for router in routers:
        if not isinstance(router, dict):
            continue
        id_map = {}
        for out in router.get("outputs") or []:
            if out.get("id") in legacy_ids and str(out.get("upstreamType") or "") == "cloud":
                pid = str(out.get("providerId") or "").strip()
                if pid:
                    id_map[out["id"]] = f"cb:{pid}"
                    expose.add(pid)
        if id_map:
            remaps.append((router, id_map))
    if not remaps:
        return False
    for router, id_map in remaps:
        rules = router.get("rules") or {}
        if rules.get("default") in id_map:
            rules["default"] = id_map[rules["default"]]
        for r in rules.get("bySource") or []:
            if isinstance(r, dict) and r.get("output") in id_map:
                r["output"] = id_map[r["output"]]
        for w in rules.get("schedule") or []:
            if isinstance(w, dict) and w.get("output") in id_map:
                w["output"] = id_map[w["output"]]
        rules["failover"] = [id_map.get(o, o) for o in (rules.get("failover") or [])]
        if not rules["failover"]:
            rules.pop("failover", None)
        router["rules"] = rules
        # Graph edges store output refs as `out:<outputId>`.
        graph = router.get("graph") or {}
        edge_map = {f"out:{k}": f"out:{v}" for k, v in id_map.items()}
        for e in graph.get("edges") or []:
            if isinstance(e, dict):
                if e.get("from") in edge_map:
                    e["from"] = edge_map[e["from"]]
                if e.get("to") in edge_map:
                    e["to"] = edge_map[e["to"]]
    data = load_cloud_data()
    changed = False
    for b in data["blocks"]:
        if b.get("id") in expose and not b.get("exposed"):
            b["exposed"] = True
            changed = True
    if changed:
        save_cloud_data(data)
    return changed

def sync_router_outputs(routers, server_obj, cloud_accounts=None, cloud_blocks=None):
    """Outputs are AUTO-derived from the available providers: one per local llama
    server + one per EXPOSED cloud model-block. Replace each router's outputs with the
    desired set; keep rules.default valid. Returns True if changed."""
    account_ids = [a.get("id") for a in (cloud_accounts or []) if a.get("id")]
    if migrate_legacy_cloud_outputs(routers, account_ids):
        cloud_blocks = cloud_blocks_state()   # re-read: exposure just changed
    local = _router_local_outputs(server_obj)
    cloud = _router_cloud_outputs(cloud_accounts, cloud_blocks)
    desired = [normalize_router_output(o) for o in (local + cloud)]
    changed = False
    for router in routers:
        if not isinstance(router, dict):
            continue
        existing = router.get("outputs") or []
        if existing != desired:
            router["outputs"] = [dict(o) for o in desired]
            changed = True
        ids = {o["id"] for o in desired}
        rules = router.setdefault("rules", {})
        # Default prefers a local server (cloud is overflow, not the primary).
        if rules.get("default") not in ids:
            local_ids = [o["id"] for o in desired if o["upstreamType"] != "cloud"]
            rules["default"] = (local_ids or [o["id"] for o in desired] or [""])[0]
            changed = True
    return changed

def normalize_routers(raw, routes):
    """Normalize the router list and keep it consistent with the proxy routes.

    Guarantees: the default router always exists; every route's routerId
    points at a real router (orphans fall back to default); each router's
    `inputs` is derived fresh from the routes that carry its id (single source of
    truth — never trusted from disk)."""
    routers = [normalize_router(s) for s in (raw if isinstance(raw, list) else [])]
    by_id = {}
    for router in routers:
        by_id.setdefault(router["id"], router)
    if DEFAULT_ROUTER_ID not in by_id:
        default_router = normalize_router({"id": DEFAULT_ROUTER_ID, "name": "Default"})
        by_id[DEFAULT_ROUTER_ID] = default_router
    # Re-point routes whose router no longer exists at the default — EXCEPT the
    # intentional "unassigned" state ("" empty), which is left free (runtime → 503).
    for route in (routes or []):
        router_id = route.get("routerId")
        if router_id == "":
            continue
        if router_id not in by_id:
            route["routerId"] = DEFAULT_ROUTER_ID
    # Derive inputs from the routes (skip unassigned "" — they feed no router).
    inputs_by_router = {}
    for route in (routes or []):
        router_id = route.get("routerId")
        if not router_id:
            continue
        inputs_by_router.setdefault(router_id, []).append(f"skynet:proxy:{route.get('port')}")
    ordered = [by_id[DEFAULT_ROUTER_ID]] + [router for sid, router in by_id.items() if sid != DEFAULT_ROUTER_ID]
    for router in ordered:
        router["inputs"] = inputs_by_router.get(router["id"], [])
    return ordered

def save_agent_proxy_config(routes, routers=None):
    cleaned = []
    seen = set()
    for route in routes:
        row = normalize_agent_proxy_route(route)
        if row["port"] in seen:
            raise AppError(f"duplicate proxy port {row['port']}", 400)
        seen.add(row["port"])
        cleaned.append(row)
    current = load_agent_proxy_config()
    # Routers: caller-provided list (Stage 4 UI) or keep the existing one;
    # either way re-normalize against the cleaned routes so inputs stay in sync.
    router_source = routers if routers is not None else current.get("routers")
    payload = {
        "routes": cleaned,
        "policy": current.get("policy") or normalize_agent_proxy_policy({}),
        "routers": normalize_routers(router_source, cleaned),
        "stopRequests": current.get("stopRequests") or [],
    }
    write_agent_proxy_payload(payload)
    result = systemctl("restart", AGENT_PROXY_SERVICE_NAME, timeout=30)
    if not result["ok"]:
        raise AppError(result["stderr"] or "failed to restart agent proxy service", 500)
    return payload

def set_agent_proxy_policy(policy):
    payload = load_agent_proxy_config()
    payload["policy"] = normalize_agent_proxy_policy(policy)
    write_agent_proxy_payload(payload)
    return payload

def set_agent_proxy_route_policy(port, patch):
    payload = load_agent_proxy_config()
    target_port = int(port)
    found = False
    for route in payload["routes"]:
        if int(route.get("port") or 0) != target_port:
            continue
        found = True
        if "label" in patch:
            lbl = str(patch.get("label") or "").strip()[:80]
            if lbl:
                route["label"] = lbl
        if "mode" in patch:
            mode = str(patch.get("mode") or "open").strip().lower()
            if mode not in ("open", "paused", "drain"):
                raise AppError("mode must be open, paused, or drain", 400)
            route["mode"] = mode
        if "priority" in patch:
            route["priority"] = max(0, min(100, int(patch.get("priority") or 0)))
        if "preemptible" in patch:
            route["preemptible"] = bool(patch.get("preemptible"))
        if "upstreamType" in patch:
            utype = str(patch.get("upstreamType") or "llama").strip().lower()
            if utype not in ("llama", "cloud"):
                raise AppError("upstreamType must be llama or cloud", 400)
            route["upstreamType"] = utype
            if utype == "cloud":
                pid = str(patch.get("providerId") or "").strip()
                if not pid:
                    raise AppError("providerId required for cloud upstream", 400)
                route["providerId"] = pid
            else:
                route["providerId"] = ""
        elif "providerId" in patch:
            route["providerId"] = str(patch.get("providerId") or "").strip()
        if "cloudFallbackProviderId" in patch:
            # Toggle the ↑☁ ability on (provider id) or off (""); eligibility/repointing
            # is finalized by recompute_cloud_fallback_eligibility on write.
            route["cloudFallbackProviderId"] = str(patch.get("cloudFallbackProviderId") or "").strip()
        if "routerId" in patch:
            # Re-bind this proxy to another router, or "" to UNASSIGN it (free →
            # runtime 503). No restart — agent-proxies.py re-reads routerId live.
            router_id = str(patch.get("routerId") or "").strip()
            if router_id and router_id not in {s.get("id") for s in (payload.get("routers") or [])}:
                raise AppError("unknown router", 400)
            route["routerId"] = router_id
        # Per-route threshold overrides — null/absent means "inherit from global policy"
        for pct_key in ("cloudFallbackPct", "priorityPreemptPct", "queueAbortPct"):
            if pct_key in patch:
                v = patch[pct_key]
                if v is None:
                    route.pop(pct_key, None)   # remove override → revert to global
                else:
                    route[pct_key] = max(0, min(100, int(v)))
    if not found:
        raise AppError("proxy route not found", 404)
    write_agent_proxy_payload(payload)
    return payload

def set_routers(routers):
    """Replace the router list (the UI sends the full array). No service restart:
    agent-proxies.py re-reads routers from the file by mtime on the next request.
    normalize_routers (via write) keeps inputs/default/orphans consistent."""
    payload = load_agent_proxy_config()
    payload["routers"] = normalize_routers(routers, payload.get("routes"))
    write_agent_proxy_payload(payload)
    return payload
