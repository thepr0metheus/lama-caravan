"""A cell of this controller moved to the scout of this very machine."""
import shutil
import socket
import time

from caravan.admin.cell_ops import scout_start_body
from caravan.admin.fleet_clients import client_llama_autostart
from caravan.admin.launch import server_cell_dir
from caravan.admin.paths import CONTROLLER_HOST_ID
from caravan.admin.server_cells import server_slot_key
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.systemd_ctl import cell_service_action, cell_service_name, cell_service_status
from caravan.common.errors import AppError


class CellToScout:
    """One cell of this controller, handed to the scout of the machine it
    runs on — step 6.8 of the scout split: the machine's cells run through
    its scout, and the controller stops running cells itself.

    The cell keeps its port, config, model, label, note, schedule and
    command history: its slot is re-keyed, as move_host_cells re-keys a
    renamed machine's. Routes and the kanban's srv:<port> are keyed by
    port and follow; the scout was paired at 127.0.0.1, so a route reaches
    the cell where it reached it before. What only this controller's cell
    has goes: its start.sh and cell.json are kept aside
    (var/server-cells-moved/<port>-<stamp>) and its systemd unit is
    disabled — an enabled unit with a start.sh would start at boot and fight
    the scout for the port. A unit that started with the machine becomes
    the scout's autostart: the scout keeps the start request and starts
    nothing now, and the cell stays stopped.

    Refused, changing nothing: a cell that runs (stop it first), a scout of
    another machine (the cell's files, scripts and environment are this
    one's), a port its machine already has. If the scout does not take the
    autostart, or the unit does not disable, the slot goes back — nothing
    is left half-moved.
    """

    def __init__(self, port, host_id, hostname=None):
        try:
            self.port = int(port)
        except (TypeError, ValueError):
            raise AppError("port must be a number", 400)
        self.host_id = str(host_id or "").strip()
        self.hostname = (hostname or socket.gethostname()).split(".")[0].lower()

    def run(self):
        store = topology_store()
        slots = store["serverSlots"]
        src, dst = server_slot_key(CONTROLLER_HOST_ID, self.port), server_slot_key(self.host_id, self.port)
        slot = slots.get(src)
        if slot is None:
            raise AppError(f"the controller has no cell on :{self.port}", 404)
        host = store.get("hosts", {}).get(self.host_id)
        if not isinstance(host, dict):
            raise AppError(f"no scout has reported for {self.host_id or 'that machine'}", 404)
        if not host.get("agentUrl"):
            raise AppError(f"{self.host_id} reported no scout address", 400)
        if str(host.get("hostname") or "").split(".")[0].lower() != self.hostname:
            raise AppError(f"{self.host_id} is another machine — a cell of this controller moves only to the "
                           f"scout of the machine it runs on", 400)
        if dst in slots:
            raise AppError(f"{self.host_id} already has a cell on :{self.port}", 409)
        unit = cell_service_status(self.port)
        if unit.get("ActiveState") in ("active", "activating", "reloading", "deactivating"):
            raise AppError(f":{self.port} is running — stop it first", 409)
        enabled = unit.get("UnitFileState") == "enabled"

        moved = {k: v for k, v in slot.items() if k != "artifact"}
        moved.update({"id": dst, "hostId": self.host_id, "updatedAt": int(time.time())})
        del slots[src]
        slots[dst] = moved
        save_admin_state()
        try:
            if enabled:
                answer = client_llama_autostart(scout_start_body(self.host_id, self.port, moved), enabled=True)
                if not answer.get("ok"):
                    raise AppError(f"the scout did not take the autostart: {answer.get('result')}", 502)
                try:
                    cell_service_action(self.port, "disable")
                except Exception as exc:
                    client_llama_autostart({"hostId": self.host_id, "port": self.port}, enabled=False)
                    raise AppError(f"{cell_service_name(self.port)} is still enabled ({exc}) — the cell stays "
                                   f"with the controller", 500)
        except Exception:
            del slots[dst]
            slots[src] = slot
            save_admin_state()
            raise
        # The move is done; files that cannot be put aside do not undo it.
        try:
            kept, kept_error = self.keep_aside(), ""
        except OSError as exc:
            kept, kept_error = "", str(exc)
        return {"ok": True, "port": self.port, "from": CONTROLLER_HOST_ID, "to": self.host_id,
                "autostart": enabled, "kept": kept, **({"keptError": kept_error} if kept_error else {})}

    def keep_aside(self):
        """The cell's start.sh and cell.json, moved next to where they were."""
        where = server_cell_dir(self.port)
        if not where.is_dir():
            return ""
        aside = where.parent.parent / "server-cells-moved" / f"{self.port}-{time.strftime('%Y%m%d-%H%M%S')}"
        aside.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(where), str(aside))
        return str(aside)
