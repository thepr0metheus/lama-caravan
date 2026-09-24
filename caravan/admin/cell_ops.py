"""Server-cell lifecycle actions (start/stop/save/delete across controller
systemd cells and client cells via the route-agent). Sits above status because
the handlers return the composite state()."""
import os
import shutil

from caravan.admin.config_builder import is_command_cell, gpu_layers_int
from caravan.admin.runners import runner_id, uses_command_path
from caravan.domain.runner import for_config
from caravan.admin.fleet_clients import client_llama_start, client_llama_stop
from caravan.admin.cell_assets import assets_for_runner, materialize_local_assets
from caravan.admin.launch import server_cell_dir, write_server_cell_artifacts
from caravan.admin.config_builder import model_paths
from caravan.admin.model_locator import current_locations
from caravan.admin.server_cells import (
    assert_server_cell_port_available,
    delete_server_slot,
    reserve_server_cell,
    server_slot_key,
    upsert_server_slot,
)
from caravan.admin.monitoring import gpu_state
from caravan.admin.paths import is_controller_host
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.state import topology as topo
from caravan.admin.status import state
from caravan.admin.systemd_ctl import cell_service_action, cell_service_name, cell_service_status, listening_pid, systemctl
from caravan.common.errors import AppError


def _vllm_vram_gate(port, cfg):
    """Fail a vLLM start FAST when the GPU cannot host its reservation.
    vLLM pre-allocates util×total VRAM and otherwise dies in a minute-long
    crash loop (live incident: :8010 and :8012 both wanting the one 5090).
    Best-effort: single-GPU cells only, silent when nvidia-smi is absent."""
    tp = str(cfg.get("TENSOR_PARALLEL") or "").strip()
    if tp not in ("", "0", "1"):
        return  # multi-GPU placement is vLLM's own business
    try:
        util = float(str(cfg.get("GPU_MEMORY_UTILIZATION") or "").strip() or 0.9)
    except ValueError:
        util = 0.9
    gs = gpu_state()
    if not gs.get("ok") or not gs.get("gpus"):
        return
    g = gs["gpus"][0]
    try:
        total = float(g.get("memoryTotalMiB") or 0)
        free = float(g.get("memoryFreeMiB") or 0)
    except (TypeError, ValueError):
        return
    want = util * total
    if not total or free >= want:
        return
    holders = []
    for slot in topo.slots().values():
        s_port = int(slot.get("port") or 0)
        if not is_controller_host(slot.get("hostId")) or s_port == port or not s_port:
            continue
        try:
            if cell_service_status(s_port).get("ActiveState") == "active":
                holders.append(f":{s_port}")
        except Exception:
            pass
    hint = (f" — stop {', '.join(sorted(holders))} or lower GPU_MEMORY_UTILIZATION"
            if holders else " — lower GPU_MEMORY_UTILIZATION")
    raise AppError(
        f"vLLM wants {want / 1024:.1f} GiB reserved (utilization {util:.2f} × {total / 1024:.1f} GiB) "
        f"but only {free / 1024:.1f} GiB VRAM is free{hint}", 409)


def client_server_slot_add(body: dict) -> dict:
    """Manually declare a persistent server slot (host:port) so a proxy cable
    can attach to it before/independently of the server actually running."""
    if not body.get("port"):
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
    # A client cell IS the agent's llama-node (not just a stored slot), so also
    # tell the agent to stop/clear it — otherwise a configured/failed cell keeps
    # coming back from the agent's heartbeat and can't be deleted from the UI.
    if not is_controller_host(host_id):
        try:
            client_llama_stop({"hostId": host_id, "port": port})
        except Exception:
            pass
    else:
        # The controller's cell IS a systemd unit, and dropping the slot does not
        # touch it: delete a running one and llama-server keeps serving, holding
        # its VRAM, with nothing left on the board to stop it BY — the card is
        # gone. That is how :8011 came to sit on 27 GB of a 32 GB card while two
        # other cells failed to start and the UI showed no model at all.
        try:
            cell_service_action(port, "stop")
        except Exception:
            pass
        try:
            systemctl("reset-failed", cell_service_name(port), timeout=5)
        except Exception:
            pass
        # Delete mirrors create: write_server_cell_artifacts() laid down
        # var/server-cells/<port>/{cell.json,start.sh}, and leaving them behind
        # is not merely litter. The port outlives the cell — it can be handed to
        # a CLIENT next — and a stale start.sh still describes a controller cell
        # on it, one `systemctl start lama-cell@<port>` away from putting two
        # different cells on one number again.
        try:
            shutil.rmtree(server_cell_dir(port), ignore_errors=True)
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
    slot = upsert_server_slot(host_id, port, config=config, model=model)
    if is_controller_host(host_id):
        # A new config invalidates the previous crash: clear the unit's failed
        # state so the card stops shouting about a config that no longer exists.
        try:
            if cell_service_status(port).get("ActiveState") == "failed":
                systemctl("reset-failed", cell_service_name(port), timeout=5)
        except Exception:
            pass
    if not is_controller_host(host_id):
        slot["cacheModels"] = bool(body.get("cacheModels", False))
        topo.put_slot(host_id, port, slot)
        save_admin_state()
    return {"ok": True, "hostId": host_id, "port": port, "state": state()}

def bring_home(host_id, port, config, choice, locations, then_start=True):
    """Decide where this cell reads its model from, and act on it.

    Returns the move that was started, or None when the cell may start right
    now — either because its model is on this disk already, or because it will
    be read from the library it sits in.

    `choice` is what the operator answered: "disk" brings the model back and
    starts the cell when it is here, "library" starts now and reads it there.
    Empty means nobody could be asked — a schedule, a restart after a crash —
    and then the model comes home if there is room for it and is read where it
    lies if there is not. No second copy of the space arithmetic: the planner
    already refuses "no-room", and that refusal IS the answer.

    `then_start` is False when the move is only a preparation — the schedule
    fetching a model before its window opens. The cell is not started then: its
    window has not come.
    """
    away = [at for at in model_paths(config, locations).values() if at.in_library]
    if not away or choice == "library":
        return None
    from caravan.admin.model_stores import StoreRegistry
    from caravan.admin.store_moves import MoveRefused, runner as move_runner
    then = {"start": {"hostId": host_id, "port": port}} if then_start else {}
    started = None
    by_store = {}
    for at in away:
        by_store.setdefault(at.store["id"], []).append(at.rel)
    try:
        # One job per library the files are spread over; the promise to start
        # rides on the last one. The start script checks every file anyway, so
        # a cell whose earlier job failed refuses to start and says which file.
        for store_id, rels in by_store.items():
            started = move_runner().start(sorted(rels), StoreRegistry.LOCAL_ID, source_id=store_id, then=then)
    except MoveRefused:
        if choice == "disk":
            raise
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
    if is_controller_host(host_id):
        slot = topo.slot(host_id, port)
        cfg = slot.get("config") if isinstance(slot.get("config"), dict) else {}
        if action_name in {"start", "restart"} and for_config(cfg).vram_gated:
            _vllm_vram_gate(port, cfg)
        # Preflight: llama.cpp reports a taken port as a bind error buried deep
        # in its log. Say it up front, with WHO holds it — unless the holder is
        # this cell's own unit (then start is a no-op / restart is the point).
        if action_name in {"start", "restart"}:
            try:
                _own = cell_service_status(port).get("ActiveState") == "active"
            except Exception:
                _own = False
            if not _own:
                _lpid, _lcomm = listening_pid(port)
                if _lpid or _lcomm:
                    raise AppError(
                        f"port {port} is already in use by "
                        f"{_lcomm or 'another process'}"
                        f"{f' (pid {_lpid})' if _lpid else ''} — stop it first", 409)
        where = current_locations(wait=True) if action_name in {"start", "restart", "enable"} else None
        # A model that lives in a library: bring it home first, or read it
        # there. The answer may be a move, and then the cell starts when the
        # move ends — not now.
        if action_name in {"start", "restart"}:
            bringing = bring_home(host_id, port, cfg, str(body.get("modelFrom") or ""), where)
            if bringing:
                return {"ok": True, "hostId": host_id, "port": port, "action": action_name,
                        "bringing": bringing, "state": state()}
        # The script is written again at every start, not only when it is
        # missing: where a model lives can change between two starts. A file
        # moved into a library since the last one has to be read from there,
        # and the script written back then still points at this disk.
        if action_name in {"start", "restart", "enable"}:
            artifact = write_server_cell_artifacts(host_id, port, cfg, locations=where)
            if artifact:
                slot["artifact"] = artifact
                topo.put_slot(host_id, port, slot)
                save_admin_state()
        # The command names $HOME/run_<runner>.sh — put the current one there.
        # Same step a scout performs over HTTP before starting a client cell;
        # here the source is simply this repo. Failures are logged inside and
        # never block the start: an existing copy is better than no cell.
        if action_name in {"start", "restart"} and uses_command_path(cfg):
            materialize_local_assets(assets_for_runner(runner_id(cfg)))
        result = cell_service_action(port, action_name)
        return {"ok": True, "hostId": host_id, "port": port, "action": action_name,
                "result": result, "status": cell_service_status(port)}
    if action_name == "stop":
        result = client_llama_stop({"hostId": host_id, "port": port})
        return {"ok": result.get("ok", False), "hostId": host_id, "port": port, "action": action_name, "result": result}
    if action_name in {"start", "restart"}:
        slot = topo.slot(host_id, port)
        cfg = slot.get("config") if isinstance(slot.get("config"), dict) else {}
        model = str(slot.get("model") or cfg.get("MODEL_FILE") or "").strip()
        if uses_command_path(cfg):
            # Each runner refuses for its own reason, or does not refuse at all
            # (whisper and moonshine have a default size and language). The chain
            # of `elif rid ==` that used to be here had to be extended by hand
            # for every runner, and the runner added last was the one forgotten.
            for_config(cfg).preflight_start(cfg, model)
        elif not model:
            raise AppError("cell has no saved model — configure it first", 400)
        # A model in a library is no reason to refuse: client_llama_start tells
        # the scout where this controller reads it, and a scout that mounts the
        # library at the same path reads it there. One that does not says which
        # library it lacks — a download from here could only answer 404.
        result = client_llama_start({
            "hostId": host_id,
            "modelPath": model,
            "port": port,
            "gpuLayers": gpu_layers_int(cfg.get("N_GPU_LAYERS")),
            "ctxSize": int(cfg.get("CTX_SIZE") or 4096),
            "cacheModels": bool(slot.get("cacheModels", False)),
            "config": cfg,
            "cellPort": port,
        })
        return {"ok": result.get("ok", False), "hostId": host_id, "port": port, "action": action_name, "result": result}
    raise AppError(f"action '{action_name}' not supported for remote host", 400)

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
