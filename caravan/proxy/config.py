"""agent-proxies.json loading with mtime caching (re-checked every ~2s by the
listener watcher) and route normalization."""
import json

from caravan.proxy.paths import CONFIG_FILE, DEFAULT_POLICY, DEFAULT_ROUTES, UPSTREAM_HOST, UPSTREAM_PORT
from caravan.proxy.runtime import config_cache, config_lock


def load_routes():
    if CONFIG_FILE.exists():
        try:
            payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            routes = payload.get("routes") if isinstance(payload, dict) else payload
            if isinstance(routes, list):
                return routes
        except Exception:
            pass
    return DEFAULT_ROUTES

def load_config():
    payload = {}
    if CONFIG_FILE.exists():
        try:
            payload = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
    routes = payload.get("routes") if isinstance(payload, dict) else payload
    if not isinstance(routes, list):
        routes = DEFAULT_ROUTES
    policy = payload.get("policy") if isinstance(payload, dict) and isinstance(payload.get("policy"), dict) else {}
    stop_requests = payload.get("stopRequests") if isinstance(payload, dict) and isinstance(payload.get("stopRequests"), list) else []
    normalized_policy = dict(DEFAULT_POLICY)
    def _int(key, lo, hi):
        try:
            normalized_policy[key] = min(hi, max(lo, int(policy.get(key, normalized_policy[key]))))
        except Exception:
            pass
    _int("maxSlots", 1, 64)
    _int("cloudFallbackPct", 0, 100)
    _int("priorityPreemptPct", 0, 100)
    _int("queueAbortPct", 1, 100)
    _int("preemptGraceSec", 1, 300)
    _int("stickySlotSec", 0, 120)
    normalized_policy["preemptEnabled"] = bool(policy.get("preemptEnabled", normalized_policy["preemptEnabled"]))
    # Back-compat: a pre-rename file (controller not yet upgraded / not yet rewritten)
    # still uses the `switchboards` key, the `sb:default` id, and per-route
    # `switchboardId`. Read them transparently. app.py rewrites the file in the new
    # shape on its next write; until then we honour the old field names.
    routers = payload.get("routers") if isinstance(payload, dict) and isinstance(payload.get("routers"), list) else None
    if routers is None and isinstance(payload, dict) and isinstance(payload.get("switchboards"), list):
        routers = payload.get("switchboards")
    routers = routers or []
    for router in routers:
        if isinstance(router, dict) and router.get("id") == "sb:default":
            router["id"] = "router:default"
    for route in routes:
        if not isinstance(route, dict):
            continue
        if "routerId" not in route and "switchboardId" in route:
            route["routerId"] = route.get("switchboardId")
        if route.get("routerId") == "sb:default":
            route["routerId"] = "router:default"
    return {"routes": routes, "policy": normalized_policy,
            "routers": routers, "stopRequests": stop_requests[-100:]}

def current_config():
    try:
        mtime = CONFIG_FILE.stat().st_mtime
    except Exception:
        mtime = 0
    with config_lock:
        if not config_cache["routes"] or mtime != config_cache["mtime"]:
            loaded = load_config()
            config_cache.update({"mtime": mtime, **loaded})
        return {
            "routes": [dict(route) for route in config_cache.get("routes", [])],
            "policy": dict(config_cache.get("policy") or DEFAULT_POLICY),
            "routers": [dict(router) for router in (config_cache.get("routers") or [])],
            "stopRequests": list(config_cache.get("stopRequests") or []),
        }

def live_route_for_port(port):
    for raw in current_config().get("routes", []):
        try:
            route = normalize_route(raw)
        except Exception:
            continue
        if int(route.get("port") or 0) == int(port):
            return route
    return None

def normalize_route(route):
    port = int(route.get("port"))
    upstream_host = str(route.get("upstreamHost") or UPSTREAM_HOST).strip() or UPSTREAM_HOST
    upstream_port = int(route.get("upstreamPort") or UPSTREAM_PORT)
    label = str(route.get("label") or f"port-{port}").strip()[:80] or f"port-{port}"
    return {
        "label": label,
        "port": port,
        "upstreamHost": upstream_host,
        "upstreamPort": upstream_port,
        "upstreamType": str(route.get("upstreamType") or "llama").strip().lower(),
        "providerId": str(route.get("providerId") or "").strip(),
        "enabled": bool(route.get("enabled", True)),
        "mode": str(route.get("mode") or "open").strip().lower(),
        "priority": int(route.get("priority") or 0),
        "preemptible": bool(route.get("preemptible", True)),
        # Client wait timeout (seconds) — synced from OpenClaw config by admin.
        # Used as the base for percentage-based queue thresholds.
        "clientTimeoutSeconds": max(0, int(route.get("clientTimeoutSeconds") or 0)),
        # Cloud fallback provider block id — auto-filled by admin from sibling cloud route.
        # When set and cloudFallbackPct threshold is reached, the queued request is
        # transparently forwarded to this cloud provider instead of returning 503.
        "cloudFallbackProviderId": str(route.get("cloudFallbackProviderId") or "").strip(),
        # Router this proxy feeds into (routing decision lives there).
        "routerId": str(route.get("routerId") or "").strip(),
        # Per-route threshold overrides (0-100, null = inherit from global policy).
        # When set, these take precedence over the global policy percentages.
        **{k: max(0, min(100, int(route[k])))
           for k in ("cloudFallbackPct", "priorityPreemptPct", "queueAbortPct")
           if route.get(k) is not None},
    }

def load_enabled_routes():
    seen = set()
    routes = []
    for raw in load_routes():
        try:
            route = normalize_route(raw)
        except Exception:
            continue
        if not route["enabled"] or route["port"] in seen:
            continue
        seen.add(route["port"])
        routes.append(route)
    return routes
