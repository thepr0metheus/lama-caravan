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
- the controller acts on itself via systemctl; a client is asked through its
  scout, which owns process control on that host anyway.
- every call is logged with the action and the host before anything happens.

Cells are not stopped first: systemd takes them down with the machine, and on a
reboot autostart brings back whatever should come back.

Both commands need passwordless sudo (or a root-run agent). When that is missing
the call fails loudly with the sudo error rather than pretending it worked.
"""
import subprocess
import time

from caravan.admin.fleet_clients import _scout_headers, post_json
from caravan.admin.paths import is_controller_host
from caravan.admin.state import topology_store
from caravan.common.errors import AppError

ACTIONS = ("reboot", "poweroff")


def _local(action: str) -> dict:
    """Act on this machine. Returns before the box goes down, by design —
    systemctl detaches, and waiting for the reply would just time out."""
    try:
        res = subprocess.run(["sudo", "-n", "systemctl", action],
                             capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        # It began and took the shell with it — that is success here.
        return {"ok": True, "detail": f"{action} issued"}
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"{action} failed: {exc}", 500)
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip() or f"exit {res.returncode}"
        # The usual cause is no passwordless sudo. Say that, don't just echo.
        hint = (f" — passwordless sudo for `systemctl {action}` is required; add a "
                "sudoers rule for the caravan user") if "password" in err.lower() else ""
        raise AppError(f"{action} refused: {err}{hint}", 500)
    return {"ok": True, "detail": f"{action} issued"}


def host_power(body: dict, action: str = "reboot") -> dict:
    """Reboot or power off the named host: the controller directly, a client via
    its scout. `action` comes from the ROUTE, never from the body — the caller
    cannot ask for the irreversible one by getting a field wrong."""
    if action not in ACTIONS:
        raise AppError(f"unknown action: {action}", 400)
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    if is_controller_host(host_id):
        return {"ok": True, "hostId": host_id, "action": action,
                "result": _local(action), "at": int(time.time())}

    store = topology_store()
    meta = (store.get("clients") or {}).get(host_id)
    if not meta:
        raise AppError(f"client not registered: {host_id}", 404)
    agent_url = str(
        ((store.get("assignments") or {}).get(host_id) or {}).get("agentUrl")
        or meta.get("agentUrl") or ""
    ).rstrip("/")
    if not agent_url:
        raise AppError(f"no agentUrl for client {host_id}", 400)
    try:
        # Short timeout on purpose: the scout answers before rebooting, and a
        # box that is already going down must not hold the board's request open.
        result = post_json(f"{agent_url}/api/host/{action}", {}, timeout=8,
                           headers=_scout_headers())
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"client unreachable: {exc}", 502)
    return {"ok": bool(result.get("ok", True)), "hostId": host_id, "action": action,
            "result": result, "at": int(time.time())}


def host_reboot(body: dict) -> dict:
    """Kept so nothing that imported it breaks."""
    return host_power(body, "reboot")
