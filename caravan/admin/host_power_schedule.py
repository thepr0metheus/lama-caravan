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
  process down with it, exactly as the manual button does. Since step 6.9 the
  board has no controller node: that machine is its scout's host node, and a
  schedule keyed to the controller's own id moves there (see
  `_adopt_controller_schedule`) — until it did, it powered the machine off
  at night with nothing on the board saying it would.

Setting a schedule is deliberately NOT gated behind typing the host name (the
manual button is, because it acts NOW). Enabling a schedule is a considered act
with an off-by-default checkbox and a plain warning in the UI; a daily one the
operator can see and disable on the board any morning.
"""
import time

from caravan.admin.controller_machine import ControllerMachine
from caravan.admin.paths import is_controller_host
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.state import topology as topo
from caravan.common.daytime import hhmm as _hhmm
from caravan.common.errors import AppError


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
    # A fresh enable must not fire retroactively for a time ALREADY PAST today
    # — stamp lastFired so the trigger waits for tomorrow. But a time still
    # AHEAD today must fire today: enabling 22:56 at 22:52 should power off in
    # four minutes, not tomorrow. So stamp only when the target already passed.
    if sched["enabled"]:
        now = time.localtime()
        at_h, at_m = sched["at"].split(":")
        if int(at_h) * 60 + int(at_m) <= now.tm_hour * 60 + now.tm_min:
            sched["lastFired"] = time.strftime("%Y-%m-%d", now)
    schedules[host_id] = sched
    save_admin_state()
    return {"ok": True, "hostId": host_id, "schedule": sched}


def host_power_schedules():
    """{hostId: schedule} for the board to render. Read-only copy."""
    return dict(topo.power_schedules())


def _adopt_controller_schedule(store, schedules):
    """Move a schedule keyed to the controller's own id onto its machine's
    node. Returns True when something moved.

    The board drew that schedule on the controller's node, and the node left
    the board in step 6.9 — its machine is its scout's host node now. The
    schedule stayed armed and was drawn nowhere: an absence that looked like
    "no schedule" while it powered the machine off at night. Under the
    machine's id it is on the node again, where it can be seen and switched
    off, and it fires through that machine's scout — the same machine.

    When the machine's node already has a schedule of its own, that one wins:
    it is the one the operator can see. While the machine's scout has not
    reported, nothing moves, and the old key keeps firing on this machine.
    """
    keys = [key for key in schedules if is_controller_host(key)]
    if not keys:
        return False
    target = ControllerMachine().host_id(store.get("hosts") or {})
    if not target:
        return False
    for key in keys:
        sched = schedules.pop(key)
        if target in schedules:
            print(f"[host-power-schedule] {key}: dropped — {target} has its own schedule")
        else:
            schedules[target] = sched
            print(f"[host-power-schedule] {key}: moved to {target}, the controller's machine")
    return True


def power_schedule_tick(now=None):
    """Fire any host poweroff whose minute has arrived. Called once a minute by
    the shared scheduler thread."""
    # Local import: host_power sits above this module in the layering.
    from caravan.admin.host_power import host_power
    store = topology_store()
    schedules = store.get("hostPowerSchedules") or {}
    if not schedules:
        return
    changed = _adopt_controller_schedule(store, schedules)
    now = now or time.localtime()
    today = time.strftime("%Y-%m-%d", now)
    cur = now.tm_hour * 60 + now.tm_min
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
