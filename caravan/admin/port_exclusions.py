"""Ports the fleet must not put a cell on.

WHY THIS EXISTS. Cell numbering is one flat fleet-wide range starting at
SERVER_CELL_BASE_PORT, and the caravan only knows about the ports IT owns —
cells, proxy routes, bridges, its own web port. Anything else on the box is
invisible to it: on this fleet the range held a leftover FastAPI console on
8091 that the picker cheerfully painted as free. Picking it produced a cell
that reserved fine, configured fine, and then died at `systemctl start` with a
bind error — the failure arriving three steps after the mistake.

Two ways in, because the two problems are different:

  MANUAL — "I keep 8100–8110 for something of my own." The caravan cannot know
  that; the operator says so once and the number stops being offered.

  SCAN — "what is listening right now that I do NOT own?" The host knows this
  and the caravan can just ask, so it does, and offers the answer as one click
  instead of asking the operator to keep a list in their head.

An exclusion is fleet-wide by number, matching the rest of the model: one
number means one thing across every host. It records WHY and WHERE it came
from, because an unexplained hole in a port range is its own small mystery a
year later.
"""
import re
import time

from caravan.admin.paths import SERVER_CELL_BASE_PORT, SERVER_CELL_UPPER_PORT
from caravan.admin.state import save_admin_state, topology_store
from caravan.common.errors import AppError

# How far above the base the scan looks. The picker draws to the same ceiling,
# so a listener past it could never be offered anyway. One number, one home:
# both derive from paths so an operator's CARAVAN_CELL_* env moves everything.
SCAN_UPPER = SERVER_CELL_UPPER_PORT


def _store():
    st = topology_store()
    if not isinstance(st.get("portExclusions"), dict):
        st["portExclusions"] = {}
    return st["portExclusions"]


def excluded_ports() -> set:
    """Just the numbers — what used_server_cell_ports() folds into its set."""
    out = set()
    for k in _store():
        try:
            out.add(int(k))
        except (TypeError, ValueError):
            continue
    return out


def list_exclusions() -> list:
    rows = []
    for k, v in _store().items():
        try:
            port = int(k)
        except (TypeError, ValueError):
            continue
        v = v if isinstance(v, dict) else {}
        rows.append({"port": port, "note": str(v.get("note") or ""),
                     "host": str(v.get("host") or ""), "addedAt": int(v.get("addedAt") or 0),
                     "auto": bool(v.get("auto"))})
    return sorted(rows, key=lambda r: r["port"])


def set_exclusions(body: dict) -> dict:
    """Add and/or remove exclusions in one call, so the UI can apply a whole
    scan result atomically instead of N round-trips."""
    body = body or {}
    store = _store()
    added, removed = [], []
    for item in (body.get("add") or []):
        if isinstance(item, (int, str)):
            item = {"port": item}
        if not isinstance(item, dict):
            continue
        try:
            port = int(item.get("port") or 0)
        except (TypeError, ValueError):
            continue
        if port < 1 or port > 65535:
            raise AppError(f"port {port} is out of range", 400)
        # Refusing here rather than silently winning: a number that already
        # runs a cell is not "reserved for something else", it is taken, and
        # quietly excluding it would hide a live cell from its own picker.
        from caravan.admin.server_cells import used_server_cell_ports
        if port in (used_server_cell_ports() - excluded_ports()):
            raise AppError(f"port {port} already belongs to a cell or proxy — "
                           f"move that first", 409)
        store[str(port)] = {"note": str(item.get("note") or "")[:200],
                            "host": str(item.get("host") or "")[:60],
                            "addedAt": int(time.time()),
                            "auto": bool(item.get("auto"))}
        added.append(port)
    for raw in (body.get("remove") or []):
        try:
            port = int(raw)
        except (TypeError, ValueError):
            continue
        if store.pop(str(port), None) is not None:
            removed.append(port)
    save_admin_state()
    return {"ok": True, "added": added, "removed": removed,
            "exclusions": list_exclusions()}


def scan_foreign_listeners() -> dict:
    """Ports inside the cell range that are LISTENING but are not ours.

    "Not ours" means: not a cell slot, not a proxy/bridge route, not the
    controller's own web port, not already excluded. What is left is either
    something the operator runs deliberately (exclude it) or something they
    forgot about (also worth knowing).

    Client hosts answer through their scout; a host that does not respond is
    reported as such rather than as "nothing found" — an unscanned host and a
    clean host must not look the same.
    """
    from caravan.admin.server_cells import used_server_cell_ports
    from caravan.admin.systemd_ctl import listening_pid
    from caravan.admin.paths import CONTROLLER_HOST_ID

    ours = used_server_cell_ports() | _caravan_owned_ports()
    hosts = []

    found = []
    for port in range(SERVER_CELL_BASE_PORT, SCAN_UPPER + 1):
        if port in ours:
            continue
        pid, comm = listening_pid(port)
        if pid or comm:
            found.append({"port": port, "proc": comm or "?", "pid": pid or 0})
    hosts.append({"hostId": CONTROLLER_HOST_ID, "ok": True, "ports": found})

    for entry in _client_scans(ours):
        hosts.append(entry)

    return {"ok": True, "hosts": hosts,
            "rangeFrom": SERVER_CELL_BASE_PORT, "rangeTo": SCAN_UPPER}


def _caravan_owned_ports() -> set:
    """Every port the caravan itself listens on, beyond the model cells.

    The scan reports a listener it does not recognise as a foreign occupant and
    offers to hold the number. Cells were the only thing it recognised, so any
    other part of the caravan inside the scanned range was reported as somebody
    else's process — and on 2026-07-29 that is exactly what happened: the scan
    flagged port 8092 on foreman, which is the caravan's OWN scout, and the
    resulting exclusion held one of its own agents' ports for three weeks.

    Both ranges are configurable, so "they do not overlap today" is a fact about
    this deployment, not a property of the design.
    """
    owned = set()
    try:
        from caravan.admin.paths import PORT as CONTROLLER_PORT
        owned.add(int(CONTROLLER_PORT))
    except Exception:
        pass
    try:
        from caravan.admin.proxies_config import load_agent_proxy_config
        for route in load_agent_proxy_config().get("routes", []):
            try:
                owned.add(int(route.get("port") or 0))
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    # Each scout's own listen port, taken from the URL the controller reaches
    # it on — the scout is a caravan process like any other.
    try:
        store = topology_store()
        urls = [str((c or {}).get("agentUrl") or "") for c in (store.get("clients") or {}).values()]
        urls += [str((a or {}).get("agentUrl") or "") for a in (store.get("assignments") or {}).values()]
        for url in urls:
            match = re.search(r":(\d+)", url.split("//")[-1])
            if match:
                owned.add(int(match.group(1)))
    except Exception:
        pass
    owned.discard(0)
    return owned


def _client_scans(ours: set) -> list:
    """Ask every registered scout what is listening on it. Best-effort per host."""
    out = []
    try:
        from caravan.admin.fleet_clients import _scout_headers
        from caravan.common.fetch import fetch_json
    except Exception:
        return out
    store = topology_store()
    assignments = store.get("assignments", {}) or {}
    for host_id, client in (store.get("clients") or {}).items():
        base = str((assignments.get(host_id) or {}).get("agentUrl")
                   or (client or {}).get("agentUrl") or "").rstrip("/")
        if not host_id or not base:
            continue
        try:
            data = fetch_json(f"{base}/api/host/listeners", timeout=6,
                              headers=_scout_headers())
            rows = [r for r in (data.get("ports") or [])
                    if isinstance(r, dict)
                    and SERVER_CELL_BASE_PORT <= int(r.get("port") or 0) <= SCAN_UPPER
                    and int(r.get("port") or 0) not in ours]
            out.append({"hostId": host_id, "ok": True, "ports": rows})
        except Exception as exc:  # noqa: BLE001
            # Says WHY, so "scout too old" reads differently from "host down".
            out.append({"hostId": host_id, "ok": False, "error": str(exc)[:160],
                        "ports": []})
    return out
