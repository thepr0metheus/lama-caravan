"""Reboot a fleet host from the board.

A host sometimes needs a power cycle for reasons the fleet cannot fix in
software — atlas loses a RAM stick on some boots and comes back with half its
memory, which starves cells until someone reboots it. Walking to the machine or
opening a terminal for that is the only reason left to leave the board, so the
board offers the button.

DELIBERATELY NARROW:
- reboot only. No shutdown: a powered-off client cannot be brought back from
  here, and offering a one-way door on a headless box is a trap.
- the controller reboots itself via `systemctl reboot`; a client is asked
  through its scout, which owns process control on that host anyway.
- always confirmed in the UI, and every call is logged with who asked.
The command needs passwordless sudo for `systemctl reboot` (or a root-run
agent). When that is missing the call fails loudly with the sudo error rather
than pretending it worked.
"""
import subprocess
import time

from caravan.admin.fleet_clients import _scout_headers, post_json
from caravan.admin.paths import is_controller_host
from caravan.admin.state import topology_store
from caravan.common.errors import AppError

REBOOT_CMD = ["sudo", "-n", "systemctl", "reboot"]


def _reboot_local() -> dict:
    """Reboot this machine. Returns before the box goes down, by design —
    systemctl reboot detaches, and waiting for the reply would just time out."""
    try:
        res = subprocess.run(REBOOT_CMD, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        # The reboot began and took the shell with it — that is success here.
        return {"ok": True, "detail": "reboot issued"}
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"reboot failed: {exc}", 500)
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip() or f"exit {res.returncode}"
        # The usual cause is no passwordless sudo. Say that, don't just echo.
        hint = (" — passwordless sudo for `systemctl reboot` is required; add a "
                "sudoers rule for the caravan user") if "password" in err.lower() else ""
        raise AppError(f"reboot refused: {err}{hint}", 500)
    return {"ok": True, "detail": "reboot issued"}


def host_reboot(body: dict) -> dict:
    """Reboot the named host: the controller directly, a client via its scout."""
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    if is_controller_host(host_id):
        return {"ok": True, "hostId": host_id, "result": _reboot_local(),
                "at": int(time.time())}

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
        result = post_json(f"{agent_url}/api/host/reboot", {}, timeout=8,
                           headers=_scout_headers())
    except Exception as exc:  # noqa: BLE001
        raise AppError(f"client unreachable: {exc}", 502)
    return {"ok": bool(result.get("ok", True)), "hostId": host_id,
            "result": result, "at": int(time.time())}
