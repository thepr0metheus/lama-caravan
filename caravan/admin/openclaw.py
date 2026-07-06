"""OpenClaw config-manager sync: per-agent wait timeouts and the derived
queue-wait thresholds cache (refreshed every 6h in a background loop)."""
import json
import os
import re
import threading
import time
import urllib.parse
from urllib.parse import urlparse

from caravan.admin.config_builder import parse_config
from caravan.admin.paths import OPENCLAW_CONFIG_CACHE_FILE, OPENCLAW_CONFIG_MANAGERS
from caravan.admin.proxies_config import (
    load_agent_proxy_config,
    read_agent_proxy_payload,
    write_agent_proxy_payload,
)
from caravan.admin.router_dsl import normalize_agent_proxy_policy
from caravan.admin.state import admin_state, save_admin_state, topology_store
from caravan.common.fetch import fetch_json
from caravan.common.fsio import atomic_write_text


def notify_openclaw_config_managers():
    config = parse_config()
    model_hint = " ".join(
        str(config.get(key) or "").strip()
        for key in ("ALIAS", "MODEL_FILE", "MMPROJ_FILE")
        if str(config.get(key) or "").strip()
    )
    payload = json.dumps({
        "source": "lama-caravan-admin",
        "modelName": model_hint,
        "modelPath": str(config.get("MODEL_FILE") or ""),
    }).encode("utf-8")
    results = []
    for target in OPENCLAW_CONFIG_MANAGERS:
        url = target["url"].rstrip("/") + "/api/model-runtime-profiles/auto-apply"
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                body = response.read(8192).decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(body)
                except Exception:
                    parsed = {"raw": body}
                results.append({"name": target["name"], "ok": True, "status": response.status, "response": parsed})
        except Exception as exc:
            results.append({"name": target["name"], "ok": False, "error": str(exc)})
    admin_state["openclawConfigManagersLastNotify"] = {
        "time": int(time.time()),
        "modelHint": model_hint,
        "results": results,
    }
    save_admin_state()
    return results

def openclaw_config_manager_state():
    return {
        "targets": OPENCLAW_CONFIG_MANAGERS,
        "lastNotify": admin_state.get("openclawConfigManagersLastNotify"),
    }

OPENCLAW_CONFIG_FETCH_TTL = 300

_openclaw_config_cache = {}
_openclaw_lock = threading.Lock()

def save_openclaw_cache():
    """Persist the last-known-good OpenClaw configs so they survive a restart and an
    agent being temporarily unreachable."""
    try:
        with _openclaw_lock:
            good = {name: entry for name, entry in _openclaw_config_cache.items()
                    if isinstance(entry, dict) and entry.get("data")}
        if not good:
            return
        atomic_write_text(OPENCLAW_CONFIG_CACHE_FILE, json.dumps(good, ensure_ascii=False, indent=2),
                          chmod=0o600, mkdir=True)
    except Exception:
        pass

def load_openclaw_cache():
    """Warm _openclaw_config_cache from disk at startup so wait_timeout sync works even
    before (or without) the agents responding."""
    try:
        if not OPENCLAW_CONFIG_CACHE_FILE.exists():
            return
        data = json.loads(OPENCLAW_CONFIG_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            with _openclaw_lock:
                for name, entry in data.items():
                    if isinstance(entry, dict) and entry.get("data") and name not in _openclaw_config_cache:
                        _openclaw_config_cache[name] = entry
    except Exception:
        pass

def _extract_port_from_url(url):
    """Extract the port number from a URL string. Returns None if not found."""
    try:
        parsed = urlparse(str(url or ""))
        if parsed.port:
            return parsed.port
        # Fallback: look for :NNNN pattern
        m = re.search(r":(\d{2,5})(?:/|$)", str(url or ""))
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None

def sync_wait_timeouts_from_openclaw():
    """Read all cached OpenClaw configs, build a port→timeoutSec map,
    then update clientTimeoutSeconds and cloudFallbackProviderId in agent-proxies.json
    for any routes where the value has changed.

    port→timeoutSec: tries cfg.models.providers[X].timeoutSeconds for each provider,
    falls back to cfg.agents.defaults.timeoutSeconds.

    cloudFallbackProviderId: for each llama route, find the first cloud route in the
    same client group (same name/alias prefix or same assignment) that uses the same
    upstream port, and store its providerId.  As a simpler heuristic: find the cloud
    route whose port appears in the same OpenClaw client's provider list.
    """
    # Ensure the OpenClaw configs are loaded (the cache is otherwise filled lazily by
    # topology_state, which may not have run yet at startup).
    try:
        openclaw_configs_snapshot()
    except Exception:
        pass

    # Build port → timeoutSec map from all cached OpenClaw configs
    port_to_timeout = {}
    with _openclaw_lock:
        _oc_items = list(_openclaw_config_cache.items())
    for name, entry in _oc_items:
        if not isinstance(entry, dict) or not entry.get("ok"):
            continue
        data = entry.get("data") or {}
        agents_defaults_timeout = None
        try:
            agents_defaults_timeout = int(
                ((data.get("agents") or {}).get("defaults") or {}).get("timeoutSeconds") or 0
            ) or None
        except Exception:
            pass
        models = data.get("models") or {}
        providers = models.get("providers") or []
        if isinstance(providers, dict):
            providers = list(providers.values())
        elif not isinstance(providers, list):
            continue
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            base_url = str(provider.get("baseUrl") or "")
            port = _extract_port_from_url(base_url)
            if not port:
                continue
            timeout = None
            try:
                t = int(provider.get("timeoutSeconds") or 0)
                if t > 0:
                    timeout = t
            except Exception:
                pass
            if timeout is None and agents_defaults_timeout:
                timeout = agents_defaults_timeout
            if timeout and timeout > 0:
                # Prefer the larger timeout if multiple providers map to same port
                existing = port_to_timeout.get(port)
                if existing is None or timeout > existing:
                    port_to_timeout[port] = timeout

    # Also apply each host's agents.defaults.timeoutSeconds to every proxy port that
    # host is assigned to route to (topology assignments). This mirrors the frontend's
    # proxyEffectiveWaitTimeout, so agents that aren't listed as named providers
    # still inherit the correct wait_timeout.
    try:
        store = topology_store()
        assignments = store.get("assignments") or {}
        for host, row in assignments.items():
            with _openclaw_lock:
                entry = _openclaw_config_cache.get(host)
            if not isinstance(entry, dict) or not entry.get("ok"):
                continue
            data = entry.get("data") or {}
            try:
                host_default = int(
                    ((data.get("agents") or {}).get("defaults") or {}).get("timeoutSeconds") or 0
                ) or None
            except Exception:
                host_default = None
            if not host_default:
                continue
            for assignment in (row.get("assignments") or []):
                for route in (assignment.get("routes") or []):
                    port = _extract_port_from_url(str(route.get("endpoint") or ""))
                    if not port:
                        continue
                    # Provider-specific timeout (already in the map) wins over the default.
                    if port not in port_to_timeout:
                        port_to_timeout[port] = host_default
    except Exception:
        pass

    if not port_to_timeout:
        return

    # Update agent-proxies.json if any route's clientTimeoutSeconds differs
    try:
        payload = read_agent_proxy_payload()
        routes = payload.get("routes") if isinstance(payload.get("routes"), list) else []
        changed = False
        for route in routes:
            if not isinstance(route, dict):
                continue
            if str(route.get("kind") or "") == "service":
                continue  # bridge ports have no OpenClaw agent behind them
            # Match by the proxy's own listening port — OpenClaw's baseUrl points here
            port = int(route.get("port") or 0)
            new_timeout = port_to_timeout.get(port)
            if new_timeout and int(route.get("clientTimeoutSeconds") or 0) != new_timeout:
                route["clientTimeoutSeconds"] = new_timeout
                changed = True
        if changed:
            write_agent_proxy_payload(payload)
    except Exception:
        pass

_queue_thresholds_lock = threading.Lock()

_queue_thresholds_cache = {"data": None, "computedAt": 0}

def compute_queue_thresholds():
    """Compute per-proxy queue event thresholds from policy + each proxy's clientTimeoutSeconds.
    Called on startup, on policy save, and every 6 hours by background thread.
    """
    import datetime as _dt
    try:
        config = load_agent_proxy_config()
        policy = config.get("policy") or normalize_agent_proxy_policy({})
        routes = config.get("routes") or []
        global_cloud_pct    = int(policy.get("cloudFallbackPct")    or 20)
        global_priority_pct = int(policy.get("priorityPreemptPct") or 50)
        global_abort_pct    = int(policy.get("queueAbortPct")       or 85)
        proxies = []
        for route in routes:
            if not isinstance(route, dict):
                continue
            if str(route.get("upstreamType") or "llama") == "cloud":
                continue
            wait_sec = int(route.get("clientTimeoutSeconds") or 0)
            if not wait_sec:
                continue
            # Use per-route override when present, else fall back to global policy
            def _eff(key, global_val):
                v = route.get(key)
                return max(0, min(100, int(v))) if v is not None else global_val
            cloud_pct    = _eff("cloudFallbackPct",    global_cloud_pct)
            priority_pct = _eff("priorityPreemptPct",  global_priority_pct)
            abort_pct    = _eff("queueAbortPct",        global_abort_pct)
            entry = {
                "id": route.get("id"),
                "label": route.get("label"),
                "port": route.get("port"),
                "clientTimeoutSeconds": wait_sec,
                "queueAbortSec": round(wait_sec * abort_pct / 100),
                "priorityPreemptSec": round(wait_sec * priority_pct / 100),
                # Expose effective pct values so the frontend can show overrides
                "effectiveCloudPct":    cloud_pct,
                "effectivePriorityPct": priority_pct,
                "effectiveAbortPct":    abort_pct,
                "hasCloudOverride":    route.get("cloudFallbackPct")    is not None,
                "hasPriorityOverride": route.get("priorityPreemptPct") is not None,
                "hasAbortOverride":    route.get("queueAbortPct")       is not None,
            }
            if route.get("cloudFallbackProviderId"):
                entry["cloudFallbackSec"] = round(wait_sec * cloud_pct / 100)
            proxies.append(entry)
        result = {
            "proxies": proxies,
            "policy": {"cloudFallbackPct": cloud_pct, "priorityPreemptPct": priority_pct, "queueAbortPct": abort_pct},
            "computedAt": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with _queue_thresholds_lock:
            _queue_thresholds_cache["data"] = result
            _queue_thresholds_cache["computedAt"] = time.time()
        # Persist the computed per-agent seconds into agent-proxies.json so the values
        # are available on disk without the frontend (transparency / inspection). The
        # proxy service ignores this key; enforcement still computes inline from policy
        # + clientTimeoutSeconds, so this is a readable mirror, not the source of truth.
        try:
            payload = read_agent_proxy_payload()
            if isinstance(payload, dict) and payload.get("computedThresholds") != result:
                payload["computedThresholds"] = result
                write_agent_proxy_payload(payload)
        except Exception:
            pass
        return result
    except Exception:
        return None

def _queue_thresholds_refresh_loop():
    """Background thread: recompute queue thresholds every 6 hours."""
    while True:
        time.sleep(6 * 3600)
        try:
            sync_wait_timeouts_from_openclaw()
            compute_queue_thresholds()
        except Exception:
            pass

def fetch_openclaw_config_for(name, url, force=False):
    now = time.time()
    with _openclaw_lock:
        cached = _openclaw_config_cache.get(name)
    if not force and cached and now - cached.get("fetchedAt", 0) < OPENCLAW_CONFIG_FETCH_TTL:
        return cached
    fetch_url = url.rstrip("/") + "/api/config"
    fetched_ok = False
    try:
        data = fetch_json(fetch_url, timeout=4)
        if isinstance(data, dict):
            entry = {"ok": True, "data": data, "fetchedAt": int(now), "url": url}
            fetched_ok = True
        else:
            entry = {"ok": False, "error": "unexpected response", "fetchedAt": int(now), "url": url}
    except Exception as exc:
        entry = {"ok": False, "error": str(exc), "fetchedAt": int(now), "url": url}
    if not fetched_ok and cached and cached.get("data"):
        # Agent unreachable / bad response — keep serving the last-known-good config
        # (mark it stale) instead of dropping the data we already have.
        entry = {**cached, "ok": cached.get("ok", True), "stale": True,
                 "error": entry.get("error"), "lastTryAt": int(now)}
    with _openclaw_lock:
        _openclaw_config_cache[name] = entry
    if fetched_ok:
        save_openclaw_cache()
    # After updating the cache, sync clientTimeoutSeconds into agent-proxies.json
    try:
        sync_wait_timeouts_from_openclaw()
    except Exception:
        pass
    return entry

def openclaw_configs_snapshot(force=False):
    result = {}
    for target in OPENCLAW_CONFIG_MANAGERS:
        result[target["name"]] = fetch_openclaw_config_for(target["name"], target["url"], force=force)
    return result
