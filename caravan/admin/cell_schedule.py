"""Per-cell start/stop schedule.

A cell's slot may carry `schedule = {enabled, start "HH:MM", stop "HH:MM",
days [0..6, Mon=0]}` (empty days = every day). A background tick (1/min)
starts the cell when the window opens and stops it when the window closes —
acting only on window EDGES, so a manual stop inside a window sticks until
the next window opens (`schedState` on the slot remembers the last applied
edge; it survives restarts via admin state).

Overnight windows (22:00 → 08:00) belong to their START day: with days=[Fri]
the cell runs Fri 22:00 → Sat 08:00.
"""
import re
import threading
import time

#: How long before a window opens the cell's model is brought back from a
#: library. Long enough for tens of gigabytes over a gigabit link, and the move
#: itself waits out an outage, so an early start costs nothing.
PREFETCH_MIN = 30

from caravan.admin.server_cells import server_slot_key
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.state import topology as topo
from caravan.common.errors import AppError


def _hhmm(value, default):
    raw = str(value if value not in (None, "") else default).strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if not match:
        raise AppError(f"time must look like HH:MM, got: {raw}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise AppError(f"time out of range: {raw}")
    return f"{hour:02d}:{minute:02d}"


def _mins(hhmm):
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def normalize_schedule(payload):
    if not isinstance(payload, dict):
        raise AppError("schedule must be an object")
    days_raw = payload.get("days")
    days = []
    if isinstance(days_raw, list):
        try:
            days = sorted({int(d) for d in days_raw if 0 <= int(d) <= 6})
        except (TypeError, ValueError):
            raise AppError("days must be integers 0..6 (Mon=0)")
    sched = {
        "enabled": bool(payload.get("enabled")),
        "start": _hhmm(payload.get("start"), "22:00"),
        "stop": _hhmm(payload.get("stop"), "08:00"),
        "days": days,
    }
    if sched["enabled"] and sched["start"] == sched["stop"]:
        raise AppError("start and stop must differ")
    return sched


def set_cell_schedule(body):
    host_id = str(body.get("hostId") or "").strip()
    port = int(body.get("port") or 0)
    if not host_id or not port:
        raise AppError("hostId and port are required", 400)
    key = server_slot_key(host_id, port)
    slot = topo.find_slot(host_id, port)
    if not slot:
        raise AppError(f"no such cell: {key}", 404)
    sched = normalize_schedule(body.get("schedule") or {})
    slot["schedule"] = sched
    # Re-arm the edge detector so the next tick applies the current window.
    slot.pop("schedState", None)
    topo.put_slot(host_id, port, slot)
    save_admin_state()
    return {"ok": True, "hostId": host_id, "port": port, "schedule": sched}


def in_window(sched, now=None):
    now = now or time.localtime()
    days = sched.get("days") or list(range(7))
    cur = now.tm_hour * 60 + now.tm_min
    start = _mins(sched.get("start") or "22:00")
    stop = _mins(sched.get("stop") or "08:00")
    day = now.tm_wday
    if start == stop:
        return False
    if start < stop:
        return day in days and start <= cur < stop
    # Overnight: today's tail belongs to today; the morning belongs to yesterday's window.
    if day in days and cur >= start:
        return True
    return ((day - 1) % 7) in days and cur < stop


def minutes_to_window(sched, now=None):
    """Minutes until this schedule's next window opens, or None when it never
    opens (start == stop, or no day it runs on)."""
    now = now or time.localtime()
    days = sched.get("days") or list(range(7))
    start = _mins(sched.get("start") or "22:00")
    if start == _mins(sched.get("stop") or "08:00") or not days:
        return None
    cur = now.tm_hour * 60 + now.tm_min
    for ahead in range(8):
        if (now.tm_wday + ahead) % 7 not in days:
            continue
        left = ahead * 1440 + start - cur
        if left >= 0:
            return left
    return None


def prefetch_tick(slot, sched, now):
    """Bring a model home before the window opens, so a scheduled cell starts
    from this disk instead of reading over the network.

    Nobody can be asked at 02:00, so the rule decides: the move is tried, and a
    disk with no room for it simply keeps the model where it is — the cell then
    starts from the library. The cell is NOT started here: its window has not
    come, and the model being home is all this does.

    Once per window: the window it was done for is remembered on the slot, so a
    tick a minute later does not queue the same move again.
    """
    left = minutes_to_window(sched, now)
    if left is None or left > PREFETCH_MIN:
        return False
    opens = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.mktime(now) + left * 60))
    if slot.get("schedFetch") == opens:
        return False
    slot["schedFetch"] = opens
    from caravan.admin.cell_ops import bring_home
    from caravan.admin.model_locator import current_locations
    try:
        job = bring_home(slot.get("config") or {}, current_locations(wait=True))
        if job:
            print(f"[cell-schedule] {slot.get('hostId')}:{slot.get('port')}: bringing the model home for {opens}")
    except Exception as exc:  # noqa: BLE001 - a fetch that fails must not stop the tick
        print(f"[cell-schedule] prefetch failed for {slot.get('port')}: {exc}")
    return True


def scheduler_tick(now=None):
    # Local import: cell_ops sits above this module in the layering.
    from caravan.admin.cell_ops import server_cell_action
    store = topology_store()
    now = now or time.localtime()
    changed = False
    for key, slot in list(store.get("serverSlots", {}).items()):
        sched = slot.get("schedule") or {}
        if not sched.get("enabled"):
            if slot.pop("schedState", None) is not None:
                changed = True
            continue
        want = "on" if in_window(sched, now) else "off"
        if want == "off" and prefetch_tick(slot, sched, now):
            changed = True
        last = slot.get("schedState")
        if last == want:
            continue
        slot["schedState"] = want
        changed = True
        if last is None and want == "off":
            # First sighting out-of-window (schedule just configured, or state
            # loaded fresh): arm silently — never stop a manually-running cell
            # just because a schedule appeared. The stop fires on a real
            # on→off edge.
            continue
        action = "start" if want == "on" else "stop"
        try:
            print(f"[cell-schedule] {key}: window -> {action}")
            server_cell_action({"hostId": slot.get("hostId"),
                                "port": slot.get("port"), "action": action})
        except Exception as exc:
            print(f"[cell-schedule] {key}: {action} failed: {exc}")
    if changed:
        save_admin_state()


def start_scheduler_thread():
    # Host poweroff schedules ride the SAME once-a-minute tick — one timer, two
    # kinds of schedule. Imported here (not at module top) so cell_schedule
    # stays free of the host-power layer above it; a failure in one never stops
    # the other.
    from caravan.admin.host_power_schedule import power_schedule_tick
    from caravan.admin.model_watch import model_watch_tick

    def loop():
        time.sleep(20)  # let the board settle after a deploy
        while True:
            try:
                scheduler_tick()
            except Exception as exc:
                print(f"[cell-schedule] tick error: {exc}")
            try:
                power_schedule_tick()
            except Exception as exc:
                print(f"[host-power-schedule] tick error: {exc}")
            try:
                model_watch_tick()
            except Exception as exc:
                print(f"[model-watch] tick error: {exc}")
            time.sleep(60)
    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    return thread
