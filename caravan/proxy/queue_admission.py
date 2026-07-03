"""Admission control: the wait_for_proxy_slot blocking loop (queue depth,
deadlines, sticky slots, preemption, SSE keepalive), stop-request watching and
the proxy flow-control exceptions. queue_seq is rebound here — keep every
rebinding function in this module."""
import json
import socket
import time

from caravan.proxy.capacity import (
    active_count,
    proxy_or_llama_has_capacity,
    route_group_key,
    upstream_slot_total,
)
from caravan.proxy.config import current_config, live_route_for_port, load_config
from caravan.common.fsio import atomic_write_text
from caravan.proxy.events import write_proxy_event
from caravan.proxy.paths import CONFIG_FILE, DEFAULT_POLICY
from caravan.proxy.runtime import (
    active_controls,
    active_controls_lock,
    admitted_requests,
    all_active_items,
    config_cache,
    config_lock,
    pending_requests,
    queue_condition,
    queue_position,
    sticky_slot_blocks,
    sticky_slots,
)
from caravan.proxy.state import update_active, write_state


queue_seq = 0

def stop_requested(request_id):
    if not request_id:
        return False
    return any(str(row.get("id") or "") == str(request_id) for row in current_config().get("stopRequests", []))

def stop_requested_for_route(route_label):
    for row in current_config().get("stopRequests", []):
        if str(row.get("route") or "") == str(route_label) and str(row.get("scope") or "") == "route":
            return True
    return False

def choose_preemption_victim(priority, group=None):
    candidates = []
    for item in all_active_items():
        if item.get("phase") == "queued":
            continue
        if group is not None and item.get("upstream") != group:
            continue
        route = live_route_for_port(item.get("port")) or {}
        route_priority = int(route.get("priority") or 0)
        if route_priority > 0:
            # Crowned requests (priority > 0) in an active slot are protected —
            # they always get to finish, regardless of the queued request's priority.
            continue
        if route.get("preemptible", True) is False:
            continue
        candidates.append((route_priority, int(item.get("startedAt") or 0), item))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][2]

def append_stop_request(request_id, route_label="", reason="preempted"):
    if not request_id:
        return
    with config_lock:
        payload = load_config()
        stops = [row for row in payload.get("stopRequests", []) if str(row.get("id") or "") != str(request_id)]
        stops.append({
            "id": str(request_id),
            "route": str(route_label or ""),
            "reason": reason,
            "requestedAt": int(time.time()),
        })
        payload["stopRequests"] = stops[-100:]
        atomic_write_text(CONFIG_FILE, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        config_cache["mtime"] = 0
    write_proxy_event("stop_requested", route_label=route_label, request_id=request_id, reason=reason)

def register_active_control(request_id, route_label, conn):
    with active_controls_lock:
        active_controls[str(request_id)] = {
            "conn": conn,
            "route": route_label,
            "stopReason": "",
        }

def unregister_active_control(request_id):
    with active_controls_lock:
        active_controls.pop(str(request_id), None)

def close_active_request(request_id, reason="stopped"):
    control = None
    with active_controls_lock:
        control = active_controls.get(str(request_id))
        if control:
            control["stopReason"] = reason
    if not control:
        return False
    conn = control.get("conn")
    try:
        sock = getattr(conn, "sock", None)
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
        conn.close()
        return True
    except Exception:
        return False

def active_control_stop_reason(request_id):
    with active_controls_lock:
        return str((active_controls.get(str(request_id)) or {}).get("stopReason") or "")

def stop_request_watcher():
    seen = set()
    last_slot_probe = 0.0
    while True:
        try:
            for row in current_config().get("stopRequests", []):
                request_id = str(row.get("id") or "")
                if not request_id or request_id in seen:
                    continue
                if close_active_request(request_id, row.get("reason") or "stopped"):
                    seen.add(request_id)
        except Exception:
            pass
        # Proactively probe each distinct llama upstream's /slots (every ~10s) so the
        # admin can show slot totals even while idle — otherwise a group's count is only
        # known after its first request. Covers ALL router outputs (queue node admit
        # targets), not just the proxies' default upstreams.
        now = time.time()
        if now - last_slot_probe >= 10:
            last_slot_probe = now
            try:
                cfg = current_config()
                probed = set()
                for router in (cfg.get("routers") or []):
                    for out in (router.get("outputs") or []):
                        if str(out.get("upstreamType") or "llama") == "cloud":
                            continue
                        host = str(out.get("upstreamHost") or "").strip()
                        port = int(out.get("upstreamPort") or 0)
                        if not host or not port or (host, port) in probed:
                            continue
                        probed.add((host, port))
                        # Generous timeout: a loaded /slots (big ctx / active slot) can
                        # exceed the 0.8s request-path default; this is a bg thread.
                        upstream_slot_total({"upstreamHost": host, "upstreamPort": port}, timeout=3.0)
                if probed:
                    write_state()   # flush refreshed slotTotals for the admin to read
            except Exception:
                pass
        time.sleep(0.25)

def keepalive_sse_bytes(model=""):
    """SSE keepalive that carries a REAL content-bearing delta — `reasoning_content`.

    Proven by logs (2026-06-07): OpenClaw resets its ~90s read-timeout ONLY on chunks with
    actual token text (content / reasoning_content). It IGNORES `: comment` lines, role-only
    chunks, and content:null — so those keepalives didn't stop "client disconnected" at
    first_byte+90s when Qwen stalled. We send reasoning_content (a single space): it counts
    as token activity (resets the timer) but is the model's THINKING channel, so it never
    pollutes the visible answer (`content`). This finally makes a queued/slow request survive
    as long as one genuinely streaming tokens."""
    payload = json.dumps({
        "choices": [{"finish_reason": None, "index": 0, "delta": {"reasoning_content": " "}}],
        "created": int(time.time()),
        "id": "chatcmpl-keepalive",
        "model": model or "",
        "object": "chat.completion.chunk",
    }, ensure_ascii=False)
    return ("data: " + payload + "\n\n").encode("utf-8")

class ProxyRequestStopped(Exception):
    pass

class ProxyCloudError(Exception):
    pass

class ProxyRequestBlocked(Exception):
    def __init__(self, status, message, kind):
        super().__init__(message)
        self.status = status
        self.kind = kind

class ProxyCloudFallback(Exception):
    """Raised by wait_for_proxy_slot when cloudFallbackPct threshold is reached.
    Signals the proxy to transparently forward the queued request to a cloud provider."""
    def __init__(self, provider_id, queued_ms):
        super().__init__(f"cloud fallback after {queued_ms}ms")
        self.provider_id = provider_id
        self.queued_ms = queued_ms

class ProxyQueueSpill(Exception):
    """Raised by wait_for_proxy_slot when a graph queue node's spillPct is reached.
    Carries the spill edge's target ref so the handler can re-resolve the route to
    another output/queue (generalises ProxyCloudFallback to ANY spill target)."""
    def __init__(self, spill_ref, queued_ms, deadline_epoch=0.0):
        super().__init__(f"queue spill to {spill_ref} after {queued_ms}ms")
        self.spill_ref = spill_ref
        self.queued_ms = queued_ms
        self.deadline_epoch = deadline_epoch

class ProxyClientDisconnected(Exception):
    """Raised by wait_for_proxy_slot when the client closes the connection
    while waiting in queue (detected via broken-pipe on SSE keep-alive write)."""

def remove_pending_request(request_id):
    before = len(pending_requests)
    pending_requests[:] = [item for item in pending_requests if item["id"] != request_id]
    return len(pending_requests) != before

def wait_for_proxy_slot(route, request_id, keepalive_writer=None, spec=None, client_gone=None):
    """Block until a slot on the route's upstream is free, or a threshold fires.

    Two modes share this loop:
      • spec=None — the IMPLICIT default queue: slots/thresholds from the global
        policy + per-route fields; spill = legacy ProxyCloudFallback(providerId).
      • spec=<queue node spec> — an EXPLICIT graph queue node governs this path:
        slots/thresholds/preempt/sticky come from the node; spill raises
        ProxyQueueSpill(spillRef) so the handler can divert to any output/queue.

    client_gone — optional zero-cost probe of the client socket; when it turns
    True the request leaves the queue immediately (ProxyClientDisconnected)
    instead of waiting for the next keepalive write to hit the broken pipe."""
    global queue_seq
    policy = current_config().get("policy") or DEFAULT_POLICY
    # Per-upstream queue: this request only competes for the slots of its own
    # llama-server. maxSlots is auto-tracked from the upstream's --parallel
    # (length of /slots), falling back to the spec/policy default when unavailable.
    group = route_group_key(route)
    slot_total = upstream_slot_total(route)
    if spec and spec.get("maxSlots"):
        slots_default = max(1, int(spec.get("maxSlots")))
    else:
        slots_default = max(1, int(policy.get("maxSlots") or 1))
    max_slots = slot_total if slot_total and slot_total > 0 else slots_default
    priority = int(route.get("priority") or 0)
    mode = str(route.get("mode") or "open").lower()
    if mode in ("paused", "drain"):
        raise ProxyRequestBlocked(503, f"proxy route {route['label']} is {mode}", "blocked")

    # Percentage-based thresholds derived from the route's client wait_timeout.
    # If clientTimeoutSeconds is 0 (not yet synced), fall back to a large default so the
    # proxy still works — but the UI will warn the user to configure it.
    #
    # deadlineEpoch: when spilling across chained queue nodes, the first node sets an
    # absolute deadline (unix epoch seconds) so each subsequent node works off the
    # REMAINING budget rather than the full clientTimeoutSeconds. This prevents a
    # second queue from granting a fresh full timeout after the first already consumed
    # part of the client's budget.
    started = time.time()
    deadline_epoch = float(route.get("deadlineEpoch") or 0)
    if deadline_epoch > started:
        wait_timeout_sec = max(1.0, deadline_epoch - started)
    else:
        wait_timeout_sec = max(10, int(route.get("clientTimeoutSeconds") or 0) or 3600)
        deadline_epoch = started + wait_timeout_sec
    if spec:
        # Explicit queue node: thresholds come straight from the node spec.
        # Queue nodes are pure FIFO + spill — NO priority/preempt ("crowns").
        prio_pct  = 0
        spill_pct = max(0, min(100, int(spec.get("spillPct", 20))))
        spill_ref = spec.get("spillRef")
        cloud_id  = ""   # node path spills via the graph, not a legacy provider id
        preempt_enabled = False
        preempt_grace   = 20
        keepalive_interval = float(spec.get("keepaliveSec") or 20)
    else:
        # Implicit default queue: per-route overrides take precedence over global policy.
        def _pct(route_key, policy_key, default):
            v = route.get(route_key)
            if v is not None:
                return max(0, min(100, int(v)))
            return max(0, min(100, int(policy.get(policy_key) or default)))
        prio_pct  = max(0, _pct("priorityPreemptPct", "priorityPreemptPct", 50))
        spill_pct = max(0, _pct("cloudFallbackPct",   "cloudFallbackPct",   20))
        spill_ref = None
        cloud_id  = str(route.get("cloudFallbackProviderId") or "").strip()
        preempt_enabled = bool(policy.get("preemptEnabled", True))
        preempt_grace   = max(1, int(policy.get("preemptGraceSec") or 20))
        keepalive_interval = float(policy.get("queueKeepaliveSec") or 20)
    prio_at  = wait_timeout_sec * prio_pct / 100.0
    cloud_at = wait_timeout_sec * spill_pct / 100.0   # spill/cloud threshold

    last_keepalive = started
    entry = {
        "id": str(request_id),
        "route": route["label"],
        "port": route.get("port"),
        "group": group,
        "priority": priority,
        "queuedAt": int(started),
        "seq": 0,
        "preemptTried": False,
        "cloudTried": False,
        "queueNodeId": (spec or {}).get("nodeId"),
        "thresholds": {
            "priorityAt": round(prio_at, 1),
            "cloudAt": round(cloud_at, 1) if (cloud_id or spill_ref) else None,
            "clientTimeoutSeconds": wait_timeout_sec,
        },
    }
    admitted = False
    with queue_condition:
        queue_seq += 1
        entry["seq"] = queue_seq
        pending_requests.append(entry)
        queue_condition.notify_all()
    write_proxy_event("queued", route_label=route["label"], request_id=request_id, item=entry, policy=policy)

    try:
        while True:
            now = time.time()
            elapsed = now - started

            # ── Vanished client: leave the queue at once, free the wait slot ──
            if client_gone is not None and client_gone():
                write_proxy_event("client_disconnected_queued", route_label=route["label"],
                                  request_id=request_id, elapsedSec=round(elapsed, 1))
                raise ProxyClientDisconnected()

            # ── SSE keep-alive: send comment byte to reset client read-timeout ──
            if keepalive_writer is not None and now - last_keepalive >= keepalive_interval:
                try:
                    keepalive_writer()
                    last_keepalive = now
                    write_proxy_event("queue_keepalive", route_label=route["label"],
                                      request_id=request_id, elapsedSec=round(elapsed, 1))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    write_proxy_event("client_disconnected_queued", route_label=route["label"],
                                      request_id=request_id, elapsedSec=round(elapsed, 1))
                    raise ProxyClientDisconnected()

            # ── Spill / cloud fallback — triggers first, before abort ──────────
            if not entry["cloudTried"] and cloud_at > 0 and elapsed >= cloud_at:
                if spill_ref:
                    entry["cloudTried"] = True
                    write_proxy_event("queue_spill_trigger", route_label=route["label"],
                                      request_id=request_id, item=entry, elapsedSec=round(elapsed, 2),
                                      spillRef=spill_ref)
                    raise ProxyQueueSpill(spill_ref, round(elapsed * 1000), deadline_epoch)
                if cloud_id:
                    entry["cloudTried"] = True
                    write_proxy_event("cloud_fallback_trigger", route_label=route["label"],
                                      request_id=request_id, item=entry, elapsedSec=round(elapsed, 2))
                    raise ProxyCloudFallback(cloud_id, round(elapsed * 1000))

            with queue_condition:
                position = queue_position(entry["id"], group)
                update_active(str(route["port"]), request_id, {
                    "phase": "queued",
                    "queue": {
                        "queuedMs": round(elapsed * 1000),
                        "position": position,
                        "priority": priority,
                    },
                })
                # Check sticky slot (scoped to this upstream group): if another port
                # reserved this server's slot, block admission. The reserved port
                # bypasses the block and clears the sticky immediately.
                port = route.get("port")
                sticky_blocked = sticky_slot_blocks(group, port)
                sticky_entry = sticky_slots.get(group)
                if sticky_blocked:
                    pass  # slot is reserved for another port on this server — stay in queue
                else:
                    if sticky_entry and sticky_entry.get("port") is not None:
                        # This is the reserved port returning — clear sticky
                        sticky_slots.pop(group, None)
                    if position == 0 and active_count(group) < max_slots:
                        remove_pending_request(entry["id"])
                        admitted_requests.add(entry["id"])
                        admitted = True
                        queue_condition.notify_all()
                        write_proxy_event("admitted", route_label=route["label"], request_id=request_id,
                                          item=entry, queuedMs=round(elapsed * 1000))
                        return {"queuedMs": round(elapsed * 1000), "preempted": "", "cloudFallback": False}

            # ── Priority preempt — only for routes with priority > 0 ───────────
            if (priority > 0 and preempt_enabled
                    and not entry["preemptTried"] and prio_at >= 0 and elapsed >= prio_at):
                victim = choose_preemption_victim(priority, group)
                entry["preemptTried"] = True
                if victim:
                    reason = f"preempted by {route['label']}"
                    write_proxy_event("preempt_requested", route_label=route["label"], request_id=request_id,
                                      item=entry, victim=victim, reason=reason)
                    append_stop_request(victim.get("id"), victim.get("route"), reason)
                    update_active(str(victim.get("port") or ""), victim.get("id"), {
                        "phase": "preempting",
                        "preemptedBy": route["label"],
                        "preemptedAt": int(time.time()),
                    })
                    closed = close_active_request(victim.get("id"), reason)
                    deadline = time.time() + preempt_grace
                    while time.time() < deadline:
                        with queue_condition:
                            position = queue_position(entry["id"], group)
                            if position == 0 and proxy_or_llama_has_capacity(route, max_slots, prefer_llama=True):
                                remove_pending_request(entry["id"])
                                admitted_requests.add(entry["id"])
                                admitted = True
                                queue_condition.notify_all()
                                write_proxy_event(
                                    "admitted_after_preempt",
                                    route_label=route["label"],
                                    request_id=request_id,
                                    item=entry,
                                    victim=victim,
                                    queuedMs=round((time.time() - started) * 1000),
                                )
                                return {
                                    "queuedMs": round((time.time() - started) * 1000),
                                    "preempted": victim.get("route") or victim.get("id") or "",
                                    "preemptedId": victim.get("id") or "",
                                    "preemptClosed": closed,
                                    "cloudFallback": False,
                                }
                        time.sleep(0.25)

            with queue_condition:
                queue_condition.wait(timeout=0.25)
    finally:
        with queue_condition:
            remove_pending_request(entry["id"])
            if not admitted:
                admitted_requests.discard(entry["id"])
            queue_condition.notify_all()
