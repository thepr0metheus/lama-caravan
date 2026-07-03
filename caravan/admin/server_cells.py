"""Server slot/cell bookkeeping: persistent host:port slot records and cell
artifacts. Pure data layer — the start/stop actions live in cell_ops.py."""
import time

from caravan.admin.config_builder import is_command_cell
from caravan.admin.launch import write_server_cell_artifacts
from caravan.admin.paths import SERVER_CELL_BASE_PORT
from caravan.admin.state import save_admin_state, topology_store
from caravan.common.errors import AppError


def server_slot_key(host_id, port):
    return f"{str(host_id).strip()}:{int(port)}"

def used_server_cell_ports(exclude_key=None):
    store = topology_store()
    used = set()
    for key, slot in store.get("serverSlots", {}).items():
        if exclude_key and str(key) == str(exclude_key):
            continue
        try:
            used.add(int(slot.get("port") or 0))
        except (TypeError, ValueError):
            pass
    return {p for p in used if p > 0}

def next_server_cell_port():
    used = used_server_cell_ports()
    port = SERVER_CELL_BASE_PORT
    while port in used:
        port += 1
    return port

def assert_server_cell_port_available(port, exclude_key=None):
    port = int(port)
    if port < 1 or port > 65535:
        raise AppError("port must be between 1 and 65535")
    if port in used_server_cell_ports(exclude_key=exclude_key):
        raise AppError(f"server cell port {port} is already reserved", 409)

def upsert_server_slot(host_id, port, config=None, model=None, label=None):
    """Record/refresh a persistent server slot for host:port."""
    store = topology_store()
    key = server_slot_key(host_id, port)
    slot = store["serverSlots"].get(key) or {"createdAt": int(time.time())}
    slot.update({
        "id": key,
        "hostId": str(host_id).strip(),
        "port": int(port),
        "updatedAt": int(time.time()),
    })
    if model is not None:
        slot["model"] = str(model)[:300]
    if label is not None:
        slot["label"] = str(label)[:120]
    if isinstance(config, dict):
        # Keep the saved launch config for re-start / display. IMPORTANT: keep
        # empty ("") values too — an empty field is a DELIBERATELY-removed flag
        # (e.g. an embeddings cell drops CACHE_TYPE_K / CACHE_TYPE_V / SPEC_TYPE).
        # Dropping empties made the edit form re-inherit the controller's default
        # for that key via {...state.config, ...slotConfig}, so a removed flag kept
        # "coming back" in the UI on reopen — even though the launched start.sh was
        # always correct (it's rendered from the full config, which has the "").
        # Command cell: remember the previous command so the UI can offer a
        # one-click revert (a lightweight "backup of the last command").
        if is_command_cell(config):
            old_cfg = slot.get("config") or {}
            old_cmd = str(old_cfg.get("COMMAND") or "").strip()
            new_cmd = str(config.get("COMMAND") or "").strip()
            if old_cmd and old_cmd != new_cmd:
                hist = [h for h in (slot.get("commandHistory") or [])
                        if isinstance(h, dict) and h.get("command") != old_cmd]
                hist.insert(0, {"command": old_cmd,
                                "env": str(old_cfg.get("ENV") or ""),
                                "workdir": str(old_cfg.get("WORKDIR") or ""),
                                "healthPath": str(old_cfg.get("HEALTH_PATH") or ""),
                                "ts": int(time.time())})
                slot["commandHistory"] = hist[:10]
        slot["config"] = {k: v for k, v in config.items() if v is not None}
        if str(host_id).strip() == "skynet":
            artifact = write_server_cell_artifacts(host_id, port, config)
            if artifact:
                slot["artifact"] = artifact
    store["serverSlots"][key] = slot
    save_admin_state()
    return slot

def reserve_server_cell(body):
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    raw_port = body.get("port")
    port = int(raw_port) if raw_port not in (None, "") else next_server_cell_port()
    key = server_slot_key(host_id, port)
    assert_server_cell_port_available(port, exclude_key=key if key in topology_store().get("serverSlots", {}) else None)
    slot = upsert_server_slot(host_id, port, label=body.get("label"))
    slot["kind"] = "serverCell"
    topology_store()["serverSlots"][server_slot_key(host_id, port)] = slot
    save_admin_state()
    return {"ok": True, "cell": slot, "nextPort": next_server_cell_port()}

def move_server_cell(host_id, old_port, new_port, config=None, model=None):
    old_key = server_slot_key(host_id, old_port)
    new_key = server_slot_key(host_id, new_port)
    assert_server_cell_port_available(new_port, exclude_key=old_key)
    store = topology_store()
    old = store.get("serverSlots", {}).pop(old_key, None)
    slot = upsert_server_slot(host_id, new_port, config=config, model=model,
                              label=(old or {}).get("label"))
    slot["createdAt"] = (old or {}).get("createdAt", slot.get("createdAt"))
    slot["kind"] = "serverCell"
    store["serverSlots"][new_key] = slot
    save_admin_state()
    return slot

def delete_server_slot(host_id, port):
    store = topology_store()
    removed = store["serverSlots"].pop(server_slot_key(host_id, port), None)
    if removed is not None:
        save_admin_state()
    return removed is not None

def normalize_topology_agent(agent):
    if not isinstance(agent, dict):
        return None
    agent_id = str(agent.get("id") or agent.get("name") or "").strip()[:120]
    if not agent_id:
        return None
    row = {
        "id": agent_id,
        "name": str(agent.get("name") or agent_id).strip()[:120],
        "kind": str(agent.get("kind") or "manual").strip()[:80],
        "status": str(agent.get("status") or "configured").strip()[:80],
    }
    for key, limit in {
        "runtime": 80,
        "scope": 80,
        "container": 120,
        "port": 20,
        "endpoint": 240,
        "url": 240,
        "description": 240,
    }.items():
        value = agent.get(key)
        if value is not None and str(value).strip():
            row[key] = str(value).strip()[:limit]
    rd = agent.get("runtimeDetected")
    if rd is not None:
        row["runtimeDetected"] = bool(rd)
    return row


