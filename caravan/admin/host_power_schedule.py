"""Scheduled power-off for a fleet host.

The board already powers a host off by hand ([[host_power]]); this adds "do it
at a time". A host carries `powerSchedule = {enabled, at "HH:MM", daily}` in the
admin state, keyed by hostId, and the same one-per-minute tick that drives cell
schedules fires the poweroff when the clock reaches `at`.

It is a MOMENT, not a window, and that shapes every decision here:

- Poweroff is a one-way door (see host_power) — nothing on the board turns a
  machine back on — so there is no "on" edge to pair with, only the single
  "off" instant. `cell_schedule`'s on/off window model does not fit; this is a
  fire-once-per-day trigger instead.
- Firing is deduped by `lastFired` (a YYYY-MM-DD date), not by an edge flag: the
  tick fires when the local clock is at or just past `at` and the date has not
  fired yet. A minute of slack absorbs a tick that lands a few seconds late; a
  controller that was DOWN at `at` simply misses it — which is harmless, the
  machine was already off.
- `daily` false means once: after firing, `enabled` is cleared so a one-shot
  schedule cannot resurrect on the next matching date.
- This can schedule the CONTROLLER'S OWN poweroff. That is intentional — "turn
  my machine off at night" is the whole request — and it takes the admin
  process down with it, exactly as the manual button does.

Setting a schedule is deliberately NOT gated behind typing the host name (the
manual button is, because it acts NOW). Enabling a schedule is a considered act
with an off-by-default checkbox and a plain warning in the UI; a daily one the
operator can see and disable on the board any morning.
"""
import re
import time

from caravan.admin.state import save_admin_state, topology_store
from caravan.common.errors import AppError


def _hhmm(value, default="03:00"):
    raw = str(value if value not in (None, "") else default).strip()
    match = re.match(r"^(\d{1,2}):(\d{2})$", raw)
    if not match:
        raise AppError(f"time must look like HH:MM, got: {raw}")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise AppError(f"time out of range: {raw}")
    return f"{hour:02d}:{minute:02d}"


def normalize_power_schedule(payload):
    if not isinstance(payload, dict):
        raise AppError("schedule must be an object")
    return {
        "enabled": bool(payload.get("enabled")),
        "at": _hhmm(payload.get("at"), "03:00"),
        # Daily unless explicitly turned off — the requested default.
        "daily": bool(payload.get("daily", True)),
    }


def _store_schedules(store):
    return store.setdefault("hostPowerSchedules", {})


def set_host_power_schedule(body):
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    sched = normalize_power_schedule(body.get("schedule") or {})
    store = topology_store()
    schedules = _store_schedules(store)
    # A fresh enable must not fire retroactively for a time already past today:
    # stamp lastFired with today so the trigger waits for the NEXT occurrence.
    if sched["enabled"]:
        sched["lastFired"] = time.strftime("%Y-%m-%d", time.localtime())
    schedules[host_id] = sched
    save_admin_state()
    return {"ok": True, "hostId": host_id, "schedule": sched}


def host_power_schedules():
    """{hostId: schedule} for the board to render. Read-only copy."""
    return dict(topology_store().get("hostPowerSchedules") or {})


def power_schedule_tick(now=None):
    """Fire any host poweroff whose minute has arrived. Called once a minute by
    the shared scheduler thread."""
    # Local import: host_power sits above this module in the layering.
    from caravan.admin.host_power import host_power
    store = topology_store()
    schedules = store.get("hostPowerSchedules") or {}
    if not schedules:
        return
    now = now or time.localtime()
    today = time.strftime("%Y-%m-%d", now)
    cur = now.tm_hour * 60 + now.tm_min
    changed = False
    for host_id, sched in list(schedules.items()):
        if not isinstance(sched, dict) or not sched.get("enabled"):
            continue
        if sched.get("lastFired") == today:
            continue
        at_h, at_m = (sched.get("at") or "03:00").split(":")
        at_min = int(at_h) * 60 + int(at_m)
        # Fire in a THREE-minute window at/after the target, deduped by date.
        # The loop is sleep(60)+work, so its period drifts past a minute and a
        # one-minute window would occasionally skip the minute entirely —
        # silently postponing a shutdown by a day. Three minutes absorbs the
        # drift; lastFired stops a second shot, and enabling a schedule stamps
        # lastFired=today so a time just past cannot fire retroactively. The
        # window must not wrap midnight: a target of 23:59 ends at day close
        # (min(...) below), and the missed remainder is covered the next day.
        if not (at_min <= cur < min(at_min + 3, 24 * 60)):
            continue
        sched["lastFired"] = today
        if not sched.get("daily"):
            sched["enabled"] = False   # one-shot: do not resurrect tomorrow
        changed = True
        try:
            print(f"[host-power-schedule] {host_id}: poweroff at {sched.get('at')}")
            host_power({"hostId": host_id}, "poweroff")
        except Exception as exc:  # noqa: BLE001
            print(f"[host-power-schedule] {host_id}: poweroff failed: {exc}")
    if changed:
        save_admin_state()
