"""Server-cell lifecycle actions (start/stop/save/delete of cells, each run
through the scout of its machine). Sits above status because the handlers
return the composite state(). The controller runs no cell itself since step
6.8: its own machine's cells are its scout's."""
import os

from caravan.admin.config_builder import gpu_layers_int
from caravan.admin.runners import uses_command_path
from caravan.domain.runner import for_config
from caravan.admin.fleet_clients import client_llama_autostart, client_llama_start, client_llama_stop
from caravan.admin.config_builder import model_paths
from caravan.admin.server_cells import (
    assert_server_cell_port_available,
    delete_server_slot,
    refuse_controller_host,
    reserve_server_cell,
    server_slot_key,
    upsert_server_slot,
)
from caravan.admin.engine_cells import EngineCellFit
from caravan.admin.paths import canonical_host_id
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.state import topology as topo
from caravan.admin.status import state
from caravan.common.errors import AppError


def client_server_slot_add(body: dict) -> dict:
    """Manually declare a persistent server slot (host:port) so a proxy cable
    can attach to it before/independently of the server actually running."""
    # A cell in an engine is reserved with its plan (engine_cells.py), on a
    # port of its own or the next free one; the plain slot below would take
    # the engine's model name for a file.
    if not body.get("port") or body.get("engine"):
        result = reserve_server_cell(body)
        return {"ok": True, "slot": result["cell"], "cell": result["cell"], "nextPort": result["nextPort"]}
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    port = int(body.get("port") or 0)
    if not port:
        raise AppError("port is required", 400)
    key = server_slot_key(host_id, port)
    assert_server_cell_port_available(port, exclude_key=key if topo.has_slot(host_id, port) else None)
    slot = upsert_server_slot(host_id, port,
                              config=body.get("config") if isinstance(body.get("config"), dict) else None,
                              model=body.get("model"), label=body.get("label"))
    slot["kind"] = "serverCell"
    topo.put_slot(host_id, port, slot)
    save_admin_state()
    return {"ok": True, "slot": slot, "cell": slot}

def client_server_slot_delete(body: dict) -> dict:
    host_id = str(body.get("hostId") or "").strip()
    port = int(body.get("port") or 0)
    if not host_id or not port:
        raise AppError("hostId and port are required", 400)
    removed = delete_server_slot(host_id, port)
    # A scout's cell IS its node there (not just a stored slot), so also tell
    # the scout to stop and clear it — otherwise a configured/failed cell keeps
    # coming back from the scout's report and can't be deleted from the UI.
    try:
        client_llama_stop({"hostId": host_id, "port": port})
    except Exception:
        pass
    return {"ok": True, "removed": removed}

def server_cell_save_config(body: dict) -> dict:
    """Save config for a server cell slot without starting the server."""
    host_id = str(body.get("hostId") or "").strip()
    port = int(body.get("port") or 0)
    config = body.get("config") if isinstance(body.get("config"), dict) else {}
    model = str(config.get("MODEL_FILE") or "").strip() or None
    if not host_id or not port:
        raise AppError("hostId and port are required", 400)
    # A cell made by its first Apply — the caravan shelf's "+" opens the editor
    # on a port nobody reserved (2026-09-26) — takes its port here, so the port
    # is checked here as a reserve checks it. Saving a cell that exists keeps
    # the port it has.
    if not topo.has_slot(host_id, port):
        assert_server_cell_port_available(port)
    slot = upsert_server_slot(host_id, port, config=config, model=model)
    autostart = None
    slot["cacheModels"] = bool(body.get("cacheModels", False))
    topo.put_slot(host_id, port, slot)
    save_admin_state()
    # A cell that starts with its machine starts from the request its scout
    # keeps; new settings go there too, or the next boot brings back the old
    # ones. Said in the answer when the scout would not take them.
    host = (topology_store().get("hosts") or {}).get(host_id) or {}
    if port in (host.get("autostart") or []):
        try:
            autostart = client_llama_autostart(scout_start_body(host_id, port, slot), enabled=True)
        except Exception as exc:  # noqa: BLE001 — the settings are saved either way
            autostart = {"ok": False, "error": str(exc)}
    doc = {"ok": True, "hostId": host_id, "port": port, "state": state()}
    if autostart is not None:
        doc["autostart"] = {"ok": bool(autostart.get("ok")), **({"error": autostart["error"]} if autostart.get("error") else {})}
    return doc

def bring_home(config, locations):
    """Bring a scheduled cell's model home from the library it sits in, before
    the cell's window opens — when there is room for it; when there is not,
    the cell reads it where it lies. Returns the move that was started, or
    None: the model is on this disk already, or it stays in the library.

    No second copy of the space arithmetic: the planner already refuses
    "no-room", and that refusal IS the answer. The cell is not started — its
    window has not come. (The controller's own cells asked their operator
    "disk or library" at start, and a move could start them when the file
    arrived; those cells are its machine's scout's since step 6.8.)
    """
    away = [at for at in model_paths(config, locations).values() if at.in_library]
    if not away:
        return None
    from caravan.admin.model_stores import StoreRegistry
    from caravan.admin.store_moves import MoveRefused, runner as move_runner
    started = None
    by_store = {}
    for at in away:
        by_store.setdefault(at.store["id"], []).append(at.rel)
    try:
        # One job per library the files are spread over.
        for store_id, rels in by_store.items():
            started = move_runner().start(sorted(rels), StoreRegistry.LOCAL_ID, source_id=store_id, then={})
    except MoveRefused:
        return None
    return started


def server_cell_action(body: dict) -> dict:
    host_id = str(body.get("hostId") or "").strip()
    port = int(body.get("port") or 0)
    action_name = str(body.get("action") or "").strip().lower()
    if not host_id or not port:
        raise AppError("hostId and port are required", 400)
    if action_name not in {"start", "stop", "restart", "enable", "disable"}:
        raise AppError("action must be start, stop, restart, enable, or disable", 400)
    refuse_controller_host(host_id)
    force = body.get("force") is True
    if action_name == "stop":
        result = client_llama_stop({"hostId": host_id, "port": port})
        return {"ok": result.get("ok", False), "hostId": host_id, "port": port, "action": action_name, "result": result}
    if action_name in {"start", "restart", "enable", "disable"}:
        slot = topo.slot(host_id, port)
        if action_name in {"start", "restart"} and not force:
            # A cell in an engine whose model would not fit into the cards'
            # free memory does not start: the answer is a question to the
            # operator, and the same start with `force` starts anyway. An
            # autostart has nobody to ask, and is not checked.
            host = (topology_store().get("hosts") or {}).get(canonical_host_id(host_id))
            short = EngineCellFit(host, slot.get("config")).short()
            if short:
                return {"ok": False, "hostId": host_id, "port": port, "action": action_name, "short": short}
        body = scout_start_body(host_id, port, slot, check=action_name != "disable")
        if action_name in {"enable", "disable"}:
            # The scout keeps the request that starts the cell and starts it
            # when its machine boots — what `systemctl enable` does for a cell
            # of this controller.
            result = client_llama_autostart(body, enabled=action_name == "enable")
        else:
            # A model in a library is no reason to refuse: client_llama_start
            # tells the scout where this controller reads it, and a scout that
            # mounts the library at the same path reads it there. One that does
            # not says which library it lacks — a download from here could only
            # answer 404.
            result = client_llama_start(body)
        return {"ok": result.get("ok", False), "hostId": host_id, "port": port, "action": action_name, "result": result}
    raise AppError(f"action '{action_name}' not supported", 400)


def scout_start_body(host_id, port, slot, check=True):
    """What starts a scout's cell, from its saved slot — for a start and for
    its autostart alike. `check` refuses a cell that could not start: one
    without a model, or one its runner refuses."""
    cfg = slot.get("config") if isinstance(slot.get("config"), dict) else {}
    model = str(slot.get("model") or cfg.get("MODEL_FILE") or "").strip()
    if check:
        if uses_command_path(cfg):
            # Each runner refuses for its own reason, or does not refuse at all
            # (whisper and moonshine have a default size and language). The chain
            # of `elif rid ==` that used to be here had to be extended by hand
            # for every runner, and the runner added last was the one forgotten.
            for_config(cfg).preflight_start(cfg, model)
        elif not model:
            raise AppError("cell has no saved model — configure it first", 400)
    return {
        "hostId": host_id,
        "modelPath": model,
        "port": port,
        "gpuLayers": gpu_layers_int(cfg.get("N_GPU_LAYERS")),
        "ctxSize": int(cfg.get("CTX_SIZE") or 4096),
        "cacheModels": bool(slot.get("cacheModels", False)),
        "config": cfg,
        "cellPort": port,
    }

_SCRIPT_PREVIEW_EXT = {".sh", ".bash", ".py"}
_SCRIPT_PREVIEW_MAX = 64 * 1024

def script_preview(raw_path):
    """Read-only peek at a script referenced by a command cell's COMMAND line.

    Controller-local files only, restricted to text scripts under $HOME —
    the editor aside shows the content so "bash ~/run_tts.sh" isn't a black box."""
    p = str(raw_path or "").strip().strip('"').strip("'")
    if not p:
        raise AppError("path required", 400)
    expanded = os.path.expanduser(p)
    if not os.path.isabs(expanded):
        expanded = os.path.join(os.path.expanduser("~"), expanded)
    real = os.path.realpath(expanded)
    home = os.path.realpath(os.path.expanduser("~"))
    if real != home and not real.startswith(home + os.sep):
        raise AppError("only scripts under the home directory are readable", 400)
    if os.path.splitext(real)[1].lower() not in _SCRIPT_PREVIEW_EXT:
        raise AppError("only .sh / .bash / .py scripts are readable", 400)
    if not os.path.isfile(real):
        raise AppError("script not found", 404)
    with open(real, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read(_SCRIPT_PREVIEW_MAX + 1)
    truncated = len(content) > _SCRIPT_PREVIEW_MAX
    return {"path": real, "size": os.path.getsize(real),
            "mtime": int(os.path.getmtime(real)),
            "content": content[:_SCRIPT_PREVIEW_MAX], "truncated": truncated}
