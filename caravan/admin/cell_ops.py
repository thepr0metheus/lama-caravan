"""Server-cell lifecycle actions (start/stop/save/delete across controller
systemd cells and client cells via the route-agent). Sits above status because
the handlers return the composite state()."""
from caravan.admin.config_builder import is_command_cell
from caravan.admin.runners import runner_id, uses_command_path
from caravan.admin.fleet_clients import client_llama_start, client_llama_stop
from caravan.admin.launch import write_server_cell_artifacts
from caravan.admin.server_cells import (
    assert_server_cell_port_available,
    delete_server_slot,
    reserve_server_cell,
    server_slot_key,
    upsert_server_slot,
)
from caravan.admin.monitoring import gpu_state
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.status import state
from caravan.admin.systemd_ctl import cell_service_action, cell_service_name, cell_service_status, systemctl
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
    for slot in topology_store().get("serverSlots", {}).values():
        s_port = int(slot.get("port") or 0)
        if str(slot.get("hostId")) != "skynet" or s_port == port or not s_port:
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
    assert_server_cell_port_available(port, exclude_key=key if key in topology_store().get("serverSlots", {}) else None)
    slot = upsert_server_slot(host_id, port,
                              config=body.get("config") if isinstance(body.get("config"), dict) else None,
                              model=body.get("model"), label=body.get("label"))
    slot["kind"] = "serverCell"
    topology_store()["serverSlots"][key] = slot
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
    if host_id != "skynet":
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
    slot = upsert_server_slot(host_id, port, config=config, model=model)
    if host_id == "skynet":
        # A new config invalidates the previous crash: clear the unit's failed
        # state so the card stops shouting about a config that no longer exists.
        try:
            if cell_service_status(port).get("ActiveState") == "failed":
                systemctl("reset-failed", cell_service_name(port), timeout=5)
        except Exception:
            pass
    if host_id != "skynet":
        slot["cacheModels"] = bool(body.get("cacheModels", False))
        topology_store()["serverSlots"][server_slot_key(host_id, port)] = slot
        save_admin_state()
    return {"ok": True, "hostId": host_id, "port": port, "state": state()}

def server_cell_action(body: dict) -> dict:
    host_id = str(body.get("hostId") or "").strip()
    port = int(body.get("port") or 0)
    action_name = str(body.get("action") or "").strip().lower()
    if not host_id or not port:
        raise AppError("hostId and port are required", 400)
    if action_name not in {"start", "stop", "restart", "enable", "disable"}:
        raise AppError("action must be start, stop, restart, enable, or disable", 400)
    if host_id == "skynet":
        slot = topology_store().get("serverSlots", {}).get(server_slot_key(host_id, port)) or {}
        cfg = slot.get("config") if isinstance(slot.get("config"), dict) else {}
        if action_name in {"start", "restart"} and runner_id(cfg) == "vllm":
            _vllm_vram_gate(port, cfg)
        if action_name in {"start", "restart", "enable"} and not (slot.get("artifact") or {}).get("startScript"):
            artifact = write_server_cell_artifacts(host_id, port, cfg)
            if artifact:
                slot["artifact"] = artifact
                topology_store()["serverSlots"][server_slot_key(host_id, port)] = slot
                save_admin_state()
        result = cell_service_action(port, action_name)
        return {"ok": True, "hostId": host_id, "port": port, "action": action_name,
                "result": result, "status": cell_service_status(port)}
    if action_name == "stop":
        result = client_llama_stop({"hostId": host_id, "port": port})
        return {"ok": result.get("ok", False), "hostId": host_id, "port": port, "action": action_name, "result": result}
    if action_name in {"start", "restart"}:
        slot = topology_store().get("serverSlots", {}).get(server_slot_key(host_id, port)) or {}
        cfg = slot.get("config") if isinstance(slot.get("config"), dict) else {}
        model = str(slot.get("model") or cfg.get("MODEL_FILE") or "").strip()
        if uses_command_path(cfg):
            if runner_id(cfg) == "vllm":
                if not str(cfg.get("VLLM_MODEL") or "").strip():
                    raise AppError("vLLM cell has no model — configure it first", 400)
            elif not str(cfg.get("COMMAND") or "").strip():
                raise AppError("command cell has no command — configure it first", 400)
        elif not model:
            raise AppError("cell has no saved model — configure it first", 400)
        result = client_llama_start({
            "hostId": host_id,
            "modelPath": model,
            "port": port,
            "gpuLayers": int(cfg.get("N_GPU_LAYERS") or 999),
            "ctxSize": int(cfg.get("CTX_SIZE") or 4096),
            "cacheModels": bool(slot.get("cacheModels", False)),
            "config": cfg,
            "cellPort": port,
        })
        return {"ok": result.get("ok", False), "hostId": host_id, "port": port, "action": action_name, "result": result}
    raise AppError(f"action '{action_name}' not supported for remote host", 400)
