"""agent-proxy-state.json maintenance (atomic unique-temp writes) and the
active/recent request bookkeeping the admin dashboard reads."""
import json
import os
import threading
import time

from caravan.proxy.config import current_config
from caravan.proxy.capacity import slot_totals_snapshot
from caravan.proxy.graph import apply_router
from caravan.proxy.paths import DEFAULT_POLICY, STATE_FILE
from caravan.proxy.runtime import (
    admitted_requests,
    lock,
    queue_condition,
    state,
    state_write_lock,
    sticky_slot_snapshot,
    sticky_slots,
)


def _resolved_upstream_url(route, cfg):
    """Return the effective upstream URL for a route by running it through apply_router.
    Falls back to the raw config value only if the route is unroutable."""
    resolved = apply_router(route, cfg)
    if resolved.get("unrouted"):
        return f"http://{route['upstreamHost']}:{route['upstreamPort']}"
    host = str(resolved.get("upstreamHost") or "127.0.0.1")
    port = int(resolved.get("upstreamPort") or 0)
    if not port:
        return f"http://{route['upstreamHost']}:{route['upstreamPort']}"
    return f"http://{host}:{port}"

def sync_agents_state(routes):
    """Reconcile the monitor's per-port agent entries with the live route set:
    add entries for new ports, drop ports that went away, and refresh label/
    upstream for ports that stay — without clearing their active/recent lists."""
    cfg = current_config()
    desired = {str(route["port"]): route for route in routes}
    # Resolve upstream URLs before taking the state lock (apply_router reads config).
    upstreams = {key: _resolved_upstream_url(route, cfg) for key, route in desired.items()}
    with lock:
        state["routes"] = routes
        state["policy"] = cfg.get("policy") or DEFAULT_POLICY
        for key in list(state["agents"]):
            if key not in desired:
                state["agents"].pop(key, None)
        for key, route in desired.items():
            row = state["agents"].get(key)
            if row is None:
                state["agents"][key] = {
                    "label": route["label"],
                    "active": [],
                    "recent": [],
                    "port": route["port"],
                    "upstream": upstreams[key],
                    "upstreamType": route["upstreamType"],
                }
            else:
                row["label"] = route["label"]
                row["port"] = route["port"]
                row["upstream"] = upstreams[key]
                row["upstreamType"] = route["upstreamType"]

def write_state():
    cfg = current_config()
    state["policy"] = cfg.get("policy") or DEFAULT_POLICY
    state["routes"] = [r for r in cfg.get("routes", []) if r.get("enabled", True)]
    payload = {
        **state,
        "time": int(time.time()),
        "stickySlots": sticky_slot_snapshot(),
        "slotTotals": slot_totals_snapshot(),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    # Atomic + concurrency-safe: many threads call write_state (per request + the slot-probe
    # watcher). A shared ".tmp" path raced (one thread's replace() removed the file the other
    # was about to rename → Errno 2). Serialize with a lock and use a unique temp per write.
    tmp = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with state_write_lock:
        try:
            tmp.write_text(body, encoding="utf-8")
            tmp.replace(STATE_FILE)
        except OSError:
            # Best-effort: a failed monitor-snapshot write must never fail a live request.
            try:
                tmp.unlink()
            except OSError:
                pass

def add_active(agent, item):
    with lock:
        state["agents"].setdefault(agent, {"active": [], "recent": []})
        state["agents"][agent]["active"].append(item)
        write_state()

def update_active(agent, request_id, patch):
    with lock:
        row = state["agents"].setdefault(agent, {"active": [], "recent": []})
        for item in row.get("active", []):
            if item.get("id") == request_id:
                item.update(patch)
                break
        write_state()

def finish_active(agent, request_id, result):
    with lock:
        row = state["agents"].setdefault(agent, {"active": [], "recent": []})
        row["active"] = [item for item in row.get("active", []) if item.get("id") != request_id]
        row.setdefault("recent", []).append(result)
        row["recent"] = row["recent"][-20:]
        write_state()
    with queue_condition:
        admitted_requests.discard(str(request_id))
        # Set sticky slot for local (llama) routes so the same port is preferred
        # for the next admission window (agent follow-up tool calls).
        port = result.get("port")
        group = result.get("upstream") or ""
        upstream_type = str((result.get("route") and
                             next((r.get("upstreamType","llama") for r in (current_config().get("routes") or [])
                                   if r.get("port") == port), "llama")) or "llama")
        # Per-block sticky (from the governing queue node) wins; else global policy.
        if result.get("stickySlotSec") is not None:
            sticky_sec = int(result.get("stickySlotSec") or 0)
        else:
            sticky_sec = int((current_config().get("policy") or {}).get("stickySlotSec") or 0)
        if port and group and upstream_type != "cloud" and sticky_sec > 0:
            sticky_slots[group] = {"port": int(port), "expiresAt": time.time() + sticky_sec}
        queue_condition.notify_all()

def add_recent(agent, result):
    with lock:
        row = state["agents"].setdefault(agent, {"active": [], "recent": []})
        row.setdefault("recent", []).append(result)
        row["recent"] = row["recent"][-20:]
        write_state()
