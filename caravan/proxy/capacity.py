"""Slot capacity accounting: upstream slot totals (llama /props), active
request counts and the has-capacity predicate used for admission."""
import http.client
import json
import time

from caravan.proxy.paths import UPSTREAM_HOST, UPSTREAM_PORT
from caravan.proxy.runtime import (
    admitted_requests,
    all_active_items,
    queue_condition,
    slot_total_cache,
    slot_total_lock,
)


def route_group_key(route):
    """Queue partition key — one queue per upstream llama-server.

    Matches the `upstream` field stamped on each active item
    (f"{upstreamHost}:{upstreamPort}"), so the admin UI can group
    running/queued requests + slot totals per server.
    """
    host = str(route.get("upstreamHost") or UPSTREAM_HOST)
    port = int(route.get("upstreamPort") or UPSTREAM_PORT)
    return f"{host}:{port}"

def upstream_slot_total(route, timeout=0.8, ttl=5.0):
    """Number of slots (llama-server --parallel) for the route's upstream.

    Cached briefly per group. Returns None when /slots is unavailable so the
    caller can fall back to the policy default.
    """
    group = route_group_key(route)
    now = time.time()
    with slot_total_lock:
        cached = slot_total_cache.get(group)
        if cached and now - cached[1] < ttl:
            return cached[0]
    total = None
    try:
        conn = http.client.HTTPConnection(route["upstreamHost"], route["upstreamPort"], timeout=timeout)
        conn.request("GET", "/slots", headers={"Connection": "close"})
        res = conn.getresponse()
        if res.status < 400:
            body = res.read(1024 * 1024)
            slots = json.loads(body.decode("utf-8"))
            if isinstance(slots, list):
                total = len(slots)
        conn.close()
    except Exception:
        total = None
    with slot_total_lock:
        # Preserve last-known-good: /slots latency flaps under load (a failed probe
        # returns None), so don't clobber a previously discovered count with None —
        # otherwise the admin's slot display would flicker back to "auto".
        if total is None:
            prev = slot_total_cache.get(group)
            if prev and prev[0] is not None:
                return prev[0]
        slot_total_cache[group] = (total, now)
    return total

def slot_totals_snapshot():
    """Per-group slot totals (from cache) for the admin UI."""
    with slot_total_lock:
        return {group: count for group, (count, _ts) in slot_total_cache.items()
                if count is not None}

def active_count(group=None):
    """Count requests occupying a slot. When `group` is given, only requests
    whose upstream matches that queue group are counted."""
    counted = 0
    admitted = set()
    with queue_condition:
        admitted = set(admitted_requests)
    for item in all_active_items():
        if group is not None and item.get("upstream") != group:
            continue
        item_id = str(item.get("id") or "")
        if item_id in admitted or item.get("phase") != "queued":
            counted += 1
    return counted

def llama_processing_count(route, timeout=0.8):
    try:
        conn = http.client.HTTPConnection(route["upstreamHost"], route["upstreamPort"], timeout=timeout)
        conn.request("GET", "/slots", headers={"Connection": "close"})
        res = conn.getresponse()
        if res.status >= 400:
            conn.close()
            return None
        body = res.read(1024 * 1024)
        conn.close()
        slots = json.loads(body.decode("utf-8"))
        if not isinstance(slots, list):
            return None
        return sum(1 for slot in slots if isinstance(slot, dict) and slot.get("is_processing"))
    except Exception:
        return None

def proxy_or_llama_has_capacity(route, max_slots, prefer_llama=False):
    proxy_free = active_count(route_group_key(route)) < max_slots
    if not prefer_llama:
        return proxy_free
    llama_busy = llama_processing_count(route)
    if llama_busy is None:
        return proxy_free
    return llama_busy < max_slots
