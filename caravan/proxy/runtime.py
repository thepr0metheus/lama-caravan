"""Shared mutable daemon state (locks, queues, active-request registry) plus
the trivial read/write accessors over it. Globals here are mutated in place and
never rebound — import the objects, don't copy them."""
import threading
import time


lock = threading.Lock()

config_lock = threading.Lock()

active_controls_lock = threading.Lock()

log_lock = threading.Lock()

state_write_lock = threading.Lock()   # serialize agent-proxy-state.json writes (atomic)

queue_condition = threading.Condition()

config_cache = {"mtime": 0, "routes": [], "policy": {}, "stopRequests": []}

active_controls = {}

pending_requests = []

admitted_requests = set()

state = {"startedAt": int(time.time()), "routes": [], "agents": {}}

# Sticky slot: reserve the local slot for the last route after it finishes.
# While active, other routes cannot be admitted even if capacity is free.
# Cleared when the reserved port returns or when the window expires.
# Keyed per upstream queue group ("host:port") so a reservation on one
# llama-server never blocks admission to a different server.
sticky_slots = {}            # group_key -> {"port": int, "expiresAt": float}

slot_total_cache = {}        # group_key -> (total:int|None, ts:float)

slot_total_lock = threading.Lock()

def set_sticky_slot(group, port, duration_sec):
    """Reserve `group`'s slot for `port` for `duration_sec` seconds after a request finishes."""
    if not group or not port or duration_sec <= 0:
        return
    with queue_condition:
        sticky_slots[group] = {"port": int(port), "expiresAt": time.time() + duration_sec}
        queue_condition.notify_all()

def clear_sticky_slot(group=None):
    with queue_condition:
        if group is None:
            sticky_slots.clear()
        else:
            sticky_slots.pop(group, None)
        queue_condition.notify_all()

def sticky_slot_blocks(group, port):
    """True if `group`'s sticky slot is active and reserved for a DIFFERENT port."""
    entry = sticky_slots.get(group)
    if not entry or entry.get("port") is None:
        return False
    if time.time() >= entry["expiresAt"]:
        sticky_slots.pop(group, None)
        return False
    return int(port) != entry["port"]

def sticky_slot_snapshot():
    """Per-group sticky slot info for state/UI: {group: {port, expiresAt, remainingSec}}."""
    out = {}
    now = time.time()
    for group, entry in list(sticky_slots.items()):
        if not entry or entry.get("port") is None or now >= entry["expiresAt"]:
            sticky_slots.pop(group, None)
            continue
        out[group] = {
            "port": entry["port"],
            "expiresAt": round(entry["expiresAt"]),
            "remainingSec": round(entry["expiresAt"] - now, 1),
        }
    return out


def all_active_items():
    items = []
    with lock:
        for agent, row in (state.get("agents") or {}).items():
            for item in row.get("active", []) or []:
                copy = dict(item)
                copy["route"] = copy.get("route") or agent
                items.append(copy)
    return items

def queue_snapshot():
    with queue_condition:
        return [
            {
                "id": item["id"],
                "route": item["route"],
                "port": item["port"],
                "group": item.get("group"),
                "priority": item["priority"],
                "queuedAt": item["queuedAt"],
                "seq": item["seq"],
            }
            for item in pending_requests
        ]

def queue_position(request_id, group=None):
    """Position within the queue. When `group` is given, only requests waiting
    on the same upstream are ranked (per-server FIFO)."""
    pool = [i for i in pending_requests if group is None or i.get("group") == group]
    ordered = sorted(pool, key=lambda item: item["seq"])
    for index, item in enumerate(ordered):
        if item["id"] == request_id:
            return index
    return None
