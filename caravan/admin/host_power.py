"""Reboot or power off a fleet host from the board.

A host sometimes needs a power cycle for reasons the fleet cannot fix in
software — a host can lose a RAM stick on some boots and come back with half its
memory, which starves cells until someone reboots it. Walking to the machine or
opening a terminal for that is the only reason left to leave the board, so the
board offers the button.

POWEROFF IS A ONE-WAY DOOR and is treated as one. Nothing on this board can
switch a machine back on: a powered-off client needs someone physically present,
or a BMC the caravan does not talk to. This module offered reboot only for
exactly that reason, and poweroff was added deliberately rather than by
relaxing the rule — so the asymmetry is kept everywhere it can be:

- separate endpoints, not a flag. `/api/host/reboot` and `/api/host/poweroff`
  cannot be confused by a mistyped field, and a scout too old to know the second
  answers 404 instead of guessing which of the two was meant.
- the UI confirms poweroff by making the operator type the host's name, the same
  gate model deletion uses, and says in the dialog that the board cannot undo it.
- every machine is asked through its scout, which owns process control on
  that host anyway — the controller's own machine too: the controller does
  nothing on its machine itself (caravan/admin/machine_scout.py), and a
  machine without a scout says so.
- every call is logged with the action and the host before anything happens.

Cells are not stopped first: systemd takes them down with the machine, and on a
reboot autostart brings back whatever should come back.

The scout needs passwordless sudo for both commands (or runs as root). When
that is missing it fails loudly with the sudo error rather than pretending it
worked.
"""
import time

from caravan.admin.fleet_clients import _scout_headers
from caravan.admin.machine_scout import machine_scout
from caravan.admin.paths import is_controller_host
from caravan.admin.state import topology as topo
from caravan.common.errors import AppError
from caravan.service.scout import Scout

ACTIONS = ("reboot", "poweroff")


def host_power(body: dict, action: str = "reboot") -> dict:
    """Reboot or power off the named host through its scout — the controller's
    own machine through the scout on it. `action` comes from the ROUTE, never
    from the body — the caller cannot ask for the irreversible one by getting a
    field wrong."""
    if action not in ACTIONS:
        raise AppError(f"unknown action: {action}", 400)
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    if is_controller_host(host_id):
        # The controller's old name for its own machine: that machine's scout.
        host_id = machine_scout.host_id()
        if not host_id:
            raise AppError(machine_scout.NO_SCOUT, 409)

    # Short timeout on purpose: the scout answers before rebooting, and a box
    # that is already going down must not hold the board's request open. A
    # refusal (sudo without a password, say) comes back in the scout's words:
    # this was the last call that named an answering host "unreachable".
    result = Scout.for_host(host_id, topo, headers=_scout_headers()).post(f"/api/host/{action}", {}, timeout=8)
    return {"ok": bool(result.get("ok", True)), "hostId": host_id, "action": action,
            "result": result, "at": int(time.time())}


def host_reboot(body: dict) -> dict:
    """Kept so nothing that imported it breaks."""
    return host_power(body, "reboot")
