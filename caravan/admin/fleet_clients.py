"""Client fleet management: scout heartbeats (the machine only), remote
llama-node lifecycle through the scout's HTTP API, and the client records the
operator makes by hand — agents, their assignment rows, names."""
import json
import secrets
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from caravan.admin.config_builder import CONFIG_FIELDS, build_remote_llama_args, gpu_layers_int, model_paths
from caravan.admin.model_locator import current_locations
from caravan.admin.runners import effective_command, effective_health_path, uses_command_path
from caravan.admin.launch import render_command_cell_shell_line, _sanitize_snapshot_name
from caravan.admin.paths import (
    CONTROLLER_HOST_ID,
    LEGACY_CONTROLLER_HOST_IDS,
    HOST_REPORT_TTL,
    PORT as ADMIN_PORT,
    SERVER_BACKUPS_DIR,
    TOPOLOGY_SERVER_IP,
    is_controller_host,
)
from caravan.admin.proxies_config import (
    read_agent_proxy_payload,
    write_agent_proxy_payload,
)
from caravan.admin.server_cells import (
    assert_server_cell_port_available,
    move_server_cell,
    server_slot_key,
    upsert_server_slot,
)
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.state import topology as topo
from caravan.admin.systemd_ctl import restart_agent_proxy
from caravan.admin.telemetry import _normalize_modalities
from caravan.common.errors import AppError
from caravan.domain.client import FleetClient
from caravan.domain.host import HostRecord
from caravan.admin.scout_pairing import ScoutPairing
from caravan.admin.scout_poll import ScoutPoller
from caravan.domain.client_proxy import PROXY_ID_PREFIX
from caravan.common.fetch import fetch_json, post_json
from caravan.service.scout import Scout


def _scout_headers():
    """Fleet-token header for controller->scout calls (empty when auth off)."""
    from caravan.admin import auth as _auth
    token = _auth.fleet_token_get() if _auth.auth_enabled() else ""
    return {"X-Caravan-Token": token} if token else {}
from caravan.common.fsio import read_text


def client_monitor(host_id: str, kind: str) -> dict:
    """Proxy a monitor snapshot request to a connected client route-agent."""
    host_id = str(host_id or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    if kind not in ("nvidia-smi",):
        raise AppError(f"unsupported monitor kind: {kind}", 400)
    return _scout(host_id).read(f"/api/monitor/{kind}", timeout=5)

def client_llama_update(body: dict) -> dict:
    """Start a llama.cpp update job on a client scout. Empty tag → latest
    release; the UI passes the controller's commit to converge the fleet."""
    scout = _scout(str((body or {}).get("hostId") or ""))
    payload = {"tag": str((body or {}).get("tag") or "").strip()}
    return scout.post("/api/llama-node/update", payload, timeout=15)

def client_llama_update_status(host_id: str) -> dict:
    return _scout(host_id).read("/api/llama-node/update-status", timeout=10)

def client_llama_builds(host_id: str) -> dict:
    return _scout(host_id).read("/api/llama-node/builds", timeout=10)

def client_llama_restore(body: dict) -> dict:
    scout = _scout(str((body or {}).get("hostId") or ""))
    payload = {"id": str((body or {}).get("id") or "").strip()}
    return scout.post("/api/llama-node/restore", payload, timeout=15)


def client_llama_suspect_dismiss(body: dict) -> dict:
    """Hide a machine's "fresh build, crashing cells" banner — for that
    build; its scout remembers (2.6+). The host record says so at once, so
    the banner does not come back until the next report."""
    host_id = str((body or {}).get("hostId") or "")
    result = _scout(host_id).post("/api/llama-node/suspect-dismiss", {}, timeout=10)
    host = topology_store().get("hosts", {}).get(host_id)
    if result.get("ok") and isinstance(host, dict):
        host["llamaSuspect"] = {"suspect": False}
        save_admin_state()
    return result

def scout_start_payload(body: dict) -> dict:
    """The request that starts a cell on a scout's machine — sent by a start,
    and kept by the scout for a cell that starts with the machine
    (client_llama_autostart): one sentence, written here."""
    payload = {
        "modelPath": str(body.get("modelPath") or "").strip(),
        "port": int(body.get("port") or 8180),
        "gpuLayers": gpu_layers_int(body.get("gpuLayers")),
        "ctxSize": int(body.get("ctxSize") or 4096),
        # When False (default) the remote re-downloads every start and purges
        # on stop — no GGUF persists on the client disk. When True it keeps the
        # model on disk and reuses it (and keeps only the active model).
        "cacheModels": bool(body.get("cacheModels", False)),
        # Full form config — kept for download/heartbeat metadata and as a
        # fallback for older agents that still rebuild the command themselves.
        "config": body.get("config") if isinstance(body.get("config"), dict) else {},
    }
    # Command-path cells run an arbitrary managed process — no llama args.
    # custom cells send their stored COMMAND; vllm cells compile their fields
    # into one bootstrap+serve line. The scout runs either via bash -lc, so no
    # agent-side knowledge of runners is needed.
    if uses_command_path(payload["config"]):
        payload["cellKind"] = "command"
        payload["command"] = effective_command(payload["config"], with_bootstrap=True)
        payload["healthPath"] = effective_health_path(payload["config"])
        # The whole start line, not just the command: exports, workdir and the
        # shell flags. The agent used to assemble this itself from `command` and
        # the config, mirroring render_command_cell_script() — and the mirror had
        # already lost `set -euo pipefail`, so one config behaved differently on a
        # client than on the controller. Now there is one sentence, written here.
        payload["shellLine"] = render_command_cell_shell_line(payload["config"], payload["port"])
        if not payload["command"]:
            raise AppError("command is required for a command cell", 400)
    else:
        # Variant 2: the controller is the single command builder. Send the resolved
        # argument list with path placeholders; the agent only substitutes the real
        # downloaded paths and runs it — no flag logic on the client.
        payload["args"] = build_remote_llama_args(payload["config"])
        if not payload["modelPath"]:
            raise AppError("modelPath is required", 400)
    # Where this controller reads each model file, keyed by the path the scout
    # is sent. A scout that has the same file there — on this machine, or a
    # library mounted at the same path — reads it in place instead of copying
    # it into its cache; one that has not falls back to its cache and the
    # download, or names the library it lacks.
    model_cfg = dict(payload["config"])
    if payload["modelPath"] and "cellKind" not in payload:
        model_cfg["MODEL_FILE"] = payload["modelPath"]
    hints = {at.rel: at.hint() for at in model_paths(model_cfg, current_locations(wait=True)).values()}
    payload["inPlace"] = {rel: hint for rel, hint in hints.items() if hint}
    return payload


def client_llama_start(body: dict) -> dict:
    """Forward a llama-node start request to the named client route-agent."""
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    # Refuses an unknown host or one without a scout address before anything
    # is moved or reserved below.
    scout = _scout(host_id)
    payload = scout_start_payload(body)
    old_cell_port = body.get("cellPort")
    if old_cell_port not in (None, ""):
        old_cell_port = int(old_cell_port)
        if old_cell_port != payload["port"]:
            move_server_cell(host_id, old_cell_port, payload["port"],
                             config=payload.get("config"), model=payload["modelPath"])
        else:
            key = server_slot_key(host_id, payload["port"])
            assert_server_cell_port_available(payload["port"], exclude_key=key)
    else:
        key = server_slot_key(host_id, payload["port"])
        assert_server_cell_port_available(payload["port"], exclude_key=key if topo.has_slot(host_id, payload["port"]) else None)

    result = scout.post("/api/llama-node/start", payload, timeout=10)
    if result.get("ok"):
        # Persist a server slot so the proxy cable stays attached across
        # stop / model change.
        try:
            upsert_server_slot(host_id, payload["port"], config=payload.get("config"),
                               model=payload["modelPath"])
        except Exception:
            pass
    return {"ok": result.get("ok", False), "hostId": host_id, "result": result}

def client_llama_autostart(body: dict, enabled: bool) -> dict:
    """Turn a scout cell's autostart on or off. On, the scout keeps the very
    request a start sends (scout_start_payload), so it starts the cell when
    its machine boots, with no controller at hand. The host record takes the
    scout's answer at once — the next report says the same — so ↟ does not
    wait a report to show what was pressed."""
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    scout = _scout(host_id)
    port = int(body.get("port") or 0)
    payload = scout_start_payload(body) if enabled else None
    result = scout.post("/api/llama-node/autostart",
                        {"port": port, "enabled": bool(enabled), "payload": payload}, timeout=10)
    ports = result.get("autostart") if isinstance(result, dict) else None
    host = topology_store().get("hosts", {}).get(host_id)
    if isinstance(ports, list) and isinstance(host, dict):
        host["autostart"] = ports
        save_admin_state()
    return {"ok": bool(isinstance(result, dict) and result.get("ok")), "hostId": host_id, "port": port,
            "result": result}

def _scout(host_id):
    """The scout of a machine that reported, ready to be called."""
    return Scout.for_host(host_id, topo, headers=_scout_headers())

def _safe_path_seg(value, fallback="_"):
    """Sanitize one path segment (host id / GPU model) for use as a folder name."""
    seg = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-.")
    return seg[:80] or fallback

def _backup_target_seg(config, gpu_name=""):
    """Folder for a backup's compute target: 'CPU' when offload is off (n-gpu-layers
    0), otherwise the sanitized GPU model the config was built for."""
    if str((config or {}).get("N_GPU_LAYERS") or "").strip() == "0":
        return "CPU"
    return _safe_path_seg(gpu_name, "GPU")

def _backup_meta(config):
    cfg = config or {}
    return {
        "modelName": Path(str(cfg.get("MODEL_FILE") or "")).name,
        "modelPath": str(cfg.get("MODEL_FILE") or ""),
        "port": str(cfg.get("PORT") or ""),
        "ctxSize": str(cfg.get("CTX_SIZE") or ""),
        "gpuLayers": str(cfg.get("N_GPU_LAYERS") or ""),
    }

def client_llama_configs(host_id: str) -> dict:
    """List a node's saved launch-config backups (kept on the controller).

    Walks <SERVER_BACKUPS_DIR>/<host>/<target>/*.json. `filename` is the path
    relative to the host dir (target/file.json) so save/load/delete round-trip.
    """
    host_id = str(host_id or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    host_dir = SERVER_BACKUPS_DIR / _safe_path_seg(host_id)
    rows = []
    if host_dir.is_dir():
        for path in sorted(host_dir.glob("*/*.json"), reverse=True):
            try:
                payload = json.loads(read_text(path))
            except Exception:
                continue
            cfg = payload.get("config") or {}
            meta = _backup_meta(cfg)
            rows.append({
                "filename": f"{path.parent.name}/{path.name}",
                "target": path.parent.name,
                "savedAt": str(payload.get("savedAt") or ""),
                "name": str(payload.get("name") or ""),
                "config": cfg,
                **meta,
            })
    return {"ok": True, "hostId": host_id, "configs": rows}

def client_llama_configs_save(body: dict) -> dict:
    """Save the posted launch config as a named backup under
    <SERVER_BACKUPS_DIR>/<host>/<gpu-model-or-CPU>/<stamp>-<name>.json."""
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    config = body.get("config")
    if not isinstance(config, dict) or not str(config.get("MODEL_FILE") or "").strip():
        raise AppError("a config with MODEL_FILE is required", 400)
    name = _sanitize_snapshot_name(body.get("name"))
    if not name:
        raise AppError("Snapshot name is required", 400)
    target = _backup_target_seg(config, body.get("gpuName"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_dir = SERVER_BACKUPS_DIR / _safe_path_seg(host_id) / _safe_path_seg(target)
    target_dir.mkdir(parents=True, exist_ok=True)
    merged = {key: str(config.get(key, "")).strip() for key in CONFIG_FIELDS}
    payload = {"hostId": host_id, "target": target, "name": name,
               "savedAt": stamp, "config": merged}
    dest = target_dir / f"{stamp}-{name}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "hostId": host_id, "filename": f"{target}/{dest.name}", "savedAt": stamp}

def client_llama_list_cache(host_id: str) -> dict:
    """List cached .gguf model files on a client host's disk.

    A failure is reported as a failure. This used to hardcode `"ok": True` and
    read `models` with an empty default, so a host that could not be asked came
    back as "fine, and its cache is empty" — the operator was shown an answer
    where there was none. `models` stays present either way, because callers
    iterate it without looking first.
    """
    result = _scout(host_id).read("/api/llama-node/list-cache", timeout=5)
    if not result.get("ok", True):
        return {"ok": False, "hostId": host_id,
                "error": result.get("error") or "", "models": []}
    return {"ok": True, "hostId": host_id, "models": result.get("models", [])}

def client_llama_configs_delete(body: dict) -> dict:
    """Delete a node's launch-config backup from the controller store. `filename`
    is the host-relative path (target/file.json) returned by client_llama_configs."""
    host_id = str(body.get("hostId") or "").strip()
    filename = str(body.get("filename") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    if not filename:
        raise AppError("filename is required", 400)
    host_dir = (SERVER_BACKUPS_DIR / _safe_path_seg(host_id)).resolve()
    target = (host_dir / filename).resolve()
    # Path-safety: the resolved target must stay inside this host's backup dir.
    if host_dir not in target.parents or target.suffix != ".json":
        raise AppError("invalid backup path", 400)
    if not target.exists():
        raise AppError("Backup file was not found", 404)
    target.unlink()
    return {"ok": True, "hostId": host_id, "deleted": filename}

def client_llama_stop(body: dict) -> dict:
    """Forward a llama-node stop request to the named client route-agent."""
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    # Forward the port so the agent stops the RIGHT slot (a client can run several
    # servers now). No port = stop all slots (legacy behaviour).
    stop_body = {}
    if body.get("port"):
        stop_body["port"] = int(body["port"])
    result = _scout(host_id).post("/api/llama-node/stop", stop_body, timeout=10)
    return {"ok": result.get("ok", False), "hostId": host_id, "result": result}

def fallback_port_for(assignment) -> int | None:
    """The port next to primary, for a fallback role — or None.

    A +1 gap is deliberately left next to every issued primary — a fossil of
    retired pairs. That's exactly the one to occupy when an operator adds a
    fallback by hand: otherwise an agent's second port drifts to the end of
    the range, and the pair stops reading at a glance. None means "there is
    no neighbor", not "zero": without a primary, no neighbor is defined, and
    a neighbor already taken by another agent is never offered.
    """
    routes = (assignment or {}).get("routes") if isinstance(assignment, dict) else None
    primary = next((r for r in (routes or [])
                    if isinstance(r, dict) and str(r.get("role") or "primary") == "primary"), None)
    if not primary:
        return None
    pid = str(primary.get("proxyId") or "")
    tail = pid.rsplit(":", 1)[-1]
    if not tail.isdigit():
        return None
    candidate = int(tail) + 1
    for host_id, entry in (topology_store().get("assignments") or {}).items():
        for row in (entry.get("assignments") or []):
            for route in (row.get("routes") or []):
                if str(route.get("proxyId") or "").rsplit(":", 1)[-1] == str(candidate):
                    return None
    return candidate


def topology_client_create(body: dict) -> dict:
    """Create a client by hand. It's an ordinary one — it just hasn't answered yet.

    `lastSeen` isn't set, so the record honestly reads as silent
    (`state: "stale"`, age unknown), not as alive.

    Its first agent is created along with the client, under the same name.
    This used to leave the agent list empty "as a fact", and the operator got
    not a card but a header row with a ＋ and a ✕: assigning a port meant
    guessing to press ＋ and typing the same name a second time. A card with
    empty primary/fallback slots is what creating a client is actually asking
    for; an agent nobody wanted is removed with a single ✕.
    """
    store = topology_store()
    row = FleetClient.new(body.get("hostId") or body.get("id"),
                          name=body.get("name"), ip=body.get("ip"))
    if row["id"] in store["clients"]:
        raise AppError(f'client already exists: {row["id"]}', 409)
    FleetClient.add_agent(row, row["id"], name=row.get("name") or row["id"])
    store["clients"][row["id"]] = row
    save_admin_state()
    return row


def topology_client_delete(body: dict) -> dict:
    client_id = str(body.get("clientId") or "").strip()
    if not client_id:
        raise AppError("clientId is required", 400)
    store = topology_store()
    if client_id not in store["clients"]:
        raise AppError(f"client not found: {client_id}", 404)
    del store["clients"][client_id]
    # The assignment row goes with its client: left behind, it would claim the
    # ports for agents nobody draws. The machine's host record is not touched —
    # a client and a host share an id, never a record.
    store.get("assignments", {}).pop(client_id, None)
    save_admin_state()
    return {"ok": True, "clientId": client_id}


def topology_client_agent_delete(body: dict) -> dict:
    """Remove an agent from its client: the record and its assignment row.

    The ports it went through stay — unclaimed, on the kanban among the free
    ones, ready to be bound to another agent or deleted in the port's window.
    Deleting a port is its own decision: it takes the port's key and settings
    with it. `freedPorts` names the ports no agent claims any more.

    The row used to stay behind, and the agent's ports then showed up as an
    orphan with a skull and a second delete of their own.

    The last agent takes its client with it (`clientRemoved`). On the board a
    client is its agents' cards; a client with none is a record no card
    shows, and it used to surface as a bare name row with a delete of its own
    — the row whose ✕ an operator took for a leftover and pressed, taking ten
    agents with it (2026-09-24). A card's own ✕ now removes exactly that card.
    """
    client_id = str(body.get("clientId") or "").strip()
    agent_id = str(body.get("agentId") or "").strip()
    if not client_id:
        raise AppError("clientId is required", 400)
    if not agent_id:
        raise AppError("agentId is required", 400)
    store = topology_store()
    client = store["clients"].get(client_id)
    if not client:
        raise AppError(f"client not found: {client_id}", 404)
    before = len(client.get("agents") or [])
    client["agents"] = [a for a in (client.get("agents") or []) if str(a.get("id") or "") != agent_id]
    if len(client.get("agents") or []) == before:
        raise AppError(f"agent not found: {agent_id}", 404)
    claims = assignment_port_claims(store)
    host_entry = (store.get("assignments") or {}).get(client_id) or {}
    rows = host_entry.get("assignments") or []
    held = set()
    for row in rows:
        if str(row.get("agentId") or "") != agent_id:
            continue
        for route in row.get("routes") or []:
            pid = str(route.get("proxyId") or "")
            if pid.startswith(PROXY_ID_PREFIX):
                try:
                    held.add(int(pid.removeprefix(PROXY_ID_PREFIX)))
                except ValueError:
                    pass
    if rows:
        host_entry["assignments"] = [r for r in rows if str(r.get("agentId") or "") != agent_id]
    client_removed = not client.get("agents")
    if client_removed:
        del store["clients"][client_id]
        store.get("assignments", {}).pop(client_id, None)
    save_admin_state()
    freed = sorted(port for port in held if claims.get(port, 0) <= 1)
    return {"ok": True, "clientId": client_id, "agentId": agent_id, "freedPorts": freed,
            "clientRemoved": client_removed}

def assignment_port_claims(store) -> dict:
    """port → how many assignment entries (any host, any agent) route through it.
    A dead agent's port is only truly free when its own assignment is the SOLE
    claim — after a VM rename the successor agent adopts the same ports, and
    deleting the dead twin must not cut the live route."""
    claims = {}
    for host_entry in (store.get("assignments") or {}).values():
        for assignment in (host_entry.get("assignments") or []):
            seen = set()   # a port listed twice within ONE assignment is one claim
            for route in (assignment.get("routes") or []):
                pid = str(route.get("proxyId") or "")
                if pid.startswith("skynet:proxy:"):
                    try:
                        port = int(pid.split(":")[-1])
                    except ValueError:
                        continue
                    if port not in seen:
                        seen.add(port)
                        claims[port] = claims.get(port, 0) + 1
    return claims


def client_llama_purge_cache(body: dict) -> dict:
    """Ask a client to delete its downloaded model cache (keeps a running model)."""
    host_id = str(body.get("hostId") or "").strip()
    result = _scout(host_id).post("/api/llama-node/purge-cache", timeout=30)
    return {"ok": result.get("ok", False), "hostId": host_id, "result": result}

def normalize_client_gpus(raw):
    """Sanitize the GPU inventory a client route agent reports in its heartbeat.

    Field names match gpu_state() (the controller's own GPUs) so the topology UI can
    render client GPUs with the same card. Values are kept as short strings."""
    if not isinstance(raw, list):
        return []
    fields = (
        "index", "uuid", "name", "vendor", "driverStatus",
        "memoryTotalMiB", "memoryUsedMiB", "memoryFreeMiB",
        "utilizationGpuPct", "temperatureC", "powerDrawW",
    )
    gpus = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        row = {}
        for key in fields:
            value = item.get(key)
            if value is not None and str(value).strip():
                row[key] = str(value).strip()[:80]
        if row.get("name"):
            gpus.append(row)
    return gpus

def scout_suspect(raw):
    """A scout's word on its fresh llama.cpp build (2.6+) as the host record
    keeps it: {"suspect": False}, or the incident — how many crashes, which
    build, since when, and the archived build to offer. None when the scout
    does not say: an older one cannot tell, and "no" would draw that as a
    machine that was watched and is fine."""
    if not isinstance(raw, dict):
        return None
    if raw.get("suspect") is not True:
        return {"suspect": False}

    def number(key):
        try:
            return int(raw.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    cand = raw.get("restoreCandidate")
    return {"suspect": True, "crashes15m": number("crashes15m"), "builtAt": number("builtAt"),
            "currentCommit": str(raw.get("currentCommit") or "")[:40],
            "firstSeenAt": number("firstSeenAt"), "lastSeenAt": number("lastSeenAt"),
            "restoreCandidate": ({k: cand[k] for k in ("id", "commit", "version", "builtAt", "sizeMb") if k in cand}
                                 if isinstance(cand, dict) and cand.get("id") else None)}


def host_from_report(payload):
    host = payload.get("host") if isinstance(payload.get("host"), dict) else {}
    # The id rule is one rule for both ways of creating a client, in
    # caravan/domain/client.py — the explanation of what happens to a client
    # under the controller's name lives there too. While there was only one
    # path, the rule lived here as a comment.
    host_id = FleetClient.validate_id(host.get("id") or host.get("name"))
    gpus = normalize_client_gpus(payload.get("gpus"))
    compute_apps = []
    for app in (payload.get("computeApps") or [])[:64]:
        if not isinstance(app, dict):
            continue
        try:
            compute_apps.append({
                "gpuUuid": str(app.get("gpuUuid") or "")[:80],
                "pid": int(app.get("pid") or 0),
                "usedMiB": int(app.get("usedMiB") or 0),
            })
        except (TypeError, ValueError):
            continue
    raw_cpu = payload.get("cpu") if isinstance(payload.get("cpu"), dict) else {}
    cpu = {}
    if raw_cpu:
        if raw_cpu.get("loadPct") is not None:
            cpu["loadPct"] = raw_cpu.get("loadPct")
        # Core counts feed the admin's CPU/GPU compute-target picker (threads default).
        for _k in ("ncpu", "logicalCores", "physicalCores", "availableCores"):
            if raw_cpu.get(_k) is not None:
                cpu[_k] = raw_cpu.get(_k)
        if isinstance(raw_cpu.get("ram"), dict):
            cpu["ram"] = {
                "usedGb": raw_cpu["ram"].get("usedGb"),
                "totalGb": raw_cpu["ram"].get("totalGb"),
            }
    platform = str(payload.get("platform") or "").strip()[:40]
    # llama-node status reported by route-agent (one or more slots per client).
    def _san_node(raw):
        if not isinstance(raw, dict):
            return {}
        return {
            "running": bool(raw.get("running")),
            "port": raw.get("port"),
            "modelPath": str(raw.get("modelPath") or "")[:300],
            "mmprojPath": str(raw.get("mmprojPath") or "")[:300],
            "specPath": str(raw.get("specPath") or "")[:300],
            "specType": str(raw.get("specType") or "")[:40],
            "uptimeSec": raw.get("uptimeSec"),
            "pid": raw.get("pid"),
            "lastError": str(raw.get("lastError") or "")[:200],
            "phase": str(raw.get("phase") or "")[:20],
            "downloadedBytes": int(raw.get("downloadedBytes") or 0),
            "totalBytes": int(raw.get("totalBytes") or 0),
            # Which file a download is on ("model-q4.gguf (1/2)"). The scout
            # always said it; this record dropped it, and a client's card
            # showed the generic "downloading…" through a multi-file fetch.
            "downloadingFile": str(raw.get("downloadingFile") or "")[:200],
            "promptTps": raw.get("promptTps"),
            "genTps": raw.get("genTps"),
            "requestsProcessing": raw.get("requestsProcessing"),
            "ctxMax": raw.get("ctxMax") or raw.get("nCtx"),
            "ctxUsed": raw.get("ctxUsed"),
            "modalities": _normalize_modalities(raw.get("modalities")),
            "firewall": raw.get("firewall") if isinstance(raw.get("firewall"), dict) else None,
            # Its scout's watchdog: crashes since the last start by hand (2.5+).
            # Dropped here, the 💥 never reached the card although the scout
            # kept it (2026-09-24).
            "crash": raw.get("crash") if isinstance(raw.get("crash"), dict) else None,
        }
    _raw_nodes = payload.get("llamaNodes")
    llama_nodes = [_san_node(n) for n in _raw_nodes if isinstance(n, dict)] \
        if isinstance(_raw_nodes, list) else []
    llama_node = _san_node(payload.get("llamaNode")) or (llama_nodes[0] if llama_nodes else {})
    if not llama_nodes and llama_node:
        llama_nodes = [llama_node]
    now = int(time.time())
    return {
        "id": host_id,
        "name": str(host.get("name") or host_id).strip()[:120],
        "hostname": str(host.get("hostname") or "").strip()[:160],
        "ip": str(host.get("ip") or "").strip()[:80],
        "agentUrl": str(payload.get("agentUrl") or "").strip()[:240],
        "gpus": gpus,
        "computeApps": compute_apps,
        "cpu": cpu,
        "platform": platform,
        "llamaNode": llama_node,
        "llamaNodes": llama_nodes,
        "llamaBinaryVersion": str(payload.get("llamaBinaryVersion") or "").strip()[:120],
        "llamaBinaryMtime": str(payload.get("llamaBinaryMtime") or "").strip()[:30],
        "llamaUpdate": payload.get("llamaUpdate") if isinstance(payload.get("llamaUpdate"), dict) else {},
        # Named by scouts since 2.0, in the heartbeat and /api/state alike.
        # Empty is a 1.x scout, which still reports agents nobody reads.
        "scoutVersion": str(payload.get("scoutVersion") or "").strip()[:40],
        # The ports that start with the machine (scout 2.4+). None, not an
        # empty list, when the scout does not say: an older scout cannot keep
        # them, and "none" would draw that as a machine that simply has none.
        "autostart": (sorted({int(p) for p in payload["autostart"] if str(p).isdigit()})
                      if isinstance(payload.get("autostart"), list) else None),
        # Cells crashing after a fresh llama.cpp build on that machine: the
        # board's banner offers a rollback (scout 2.6+).
        "llamaSuspect": scout_suspect(payload.get("llamaSuspect")),
        "firstSeen": now,
        "lastSeen": now,
    }

def record_host_report(payload):
    """Store what a scout says about its machine: the whole of its host record.

    The scout owns that record and replaces it with each report; only when the
    machine was first heard is carried over. No client is touched: a client
    is the operator's record, in its own section, and a machine that is both
    is two records under one id (HostRecord). Until 2026-09-24 one record held
    both, the report replaced it wholesale, and every operator field had to be
    carried back through it by hand — the agent list was lost that way. Old
    scouts still send agents, candidates, assignments and applyStatus; they are
    not read (host_from_report).
    """
    report = host_from_report(payload)
    store = topology_store()
    previous = store["hosts"].get(report["id"]) or {}
    report["firstSeen"] = previous.get("firstSeen") or report["firstSeen"]
    store["hosts"][report["id"]] = report
    save_admin_state()
    return report


def reconcile_proxy_metadata():
    """Keep each proxy route's label / clientId / role in sync with the LIVE assignments
    (the reliable proxy↔agent link). Provisioning reuses ports without updating the old
    label, so labels drift (e.g. :8111 labelled 'qa' while it serves pam) and clientId
    can point at the wrong host. Idempotent — only writes when something actually changed.
    Routing is unaffected (label is cosmetic; clientId/role only feed the agent grouping
    + fallback-follows-primary). Returns True if it rewrote the file."""
    store = topology_store()
    assignments = store.get("assignments") or {}
    clients = store.get("clients") or {}
    port_meta = {}   # port -> {clientId, role, name}
    contested = set()  # ports two assignments both claim at once
    for host_id, entry in assignments.items():
        client_entry = clients.get(host_id) or {}
        # Prefer client (host) display name over agent name so that hosts whose
        # agent is named generically (e.g. "OpenClaw") still get a meaningful
        # proxy label ("alice primary") rather than "OpenClaw primary".
        client_name = str(client_entry.get("name") or "").strip()
        agents = {a.get("id"): a for a in client_entry.get("agents", [])}
        for ag in (entry.get("assignments") or []):
            aid = ag.get("agentId")
            agent_name = str((agents.get(aid) or {}).get("name") or aid or "").strip()
            name = client_name or agent_name
            for r in (ag.get("routes") or []):
                pid = str(r.get("proxyId") or "")
                if not pid.startswith("skynet:proxy:"):
                    continue
                try:
                    port = int(pid.removeprefix("skynet:proxy:"))
                except ValueError:
                    continue
                if port in port_meta:
                    # TWO assignments claimed this port. The bridge is keyed
                    # by port, so the "winner" here is simply whichever one
                    # came later in the dict's iteration order; publishing
                    # one client's window on another's traffic is out, and
                    # silently picking one is too. No owner means no copy
                    # either: the port falls back to the model's own number,
                    # which is an honest answer instead of someone else's.
                    contested.add(port)
                    continue
                port_meta[port] = {
                    "clientId": host_id, "role": str(r.get("role") or "primary"), "name": name,
                    # The context window is set on the assignment — that's
                    # where the operator edits it — but it's the PROXY that
                    # publishes it, and the proxy never sees the controller's
                    # document at all: it only reads its own files. So the
                    # number rides the same one-way bridge that already
                    # carries clientId and role. No second source of truth is
                    # created: the assignment stays the owner, the route is
                    # the copy, and a cleared setting must be cleared here too.
                    "contextLength": r.get("contextLength"),
                    "modelName": (str(r.get("modelName")).strip()[:120] or None)
                                 if r.get("modelName") else None,
                    "modelNameAuto": bool(r.get("modelNameAuto")) or None,
                    "contextAuto": bool(r.get("contextAuto")) or None,
                }
    if not port_meta:
        return False
    payload = read_agent_proxy_payload()
    changed = False
    for route in (payload.get("routes") or []):
        try:
            port = int(route.get("port"))
        except (TypeError, ValueError):
            continue
        meta = port_meta.get(port)
        if port in contested:
            # A contested port: clear the copy, leave everything else alone —
            # there is nothing here to fix the collision with, and there's no
            # need to keep lying either.
            for key in ("contextLength", "contextAuto", "modelName", "modelNameAuto"):
                if key in route:
                    route.pop(key)
                    changed = True
            continue
        if port not in port_meta:
            # A port NO assignment claims: its settings copy is left without
            # an owner. This happens right after a rewire — the old route
            # lives on in the file until the next reconcile — and the whole
            # time it kept publishing the window of a client that no longer
            # sits on it. Only the copy is cleared; everything else on an
            # abandoned route isn't our business, reconcile removes it.
            for key in ("contextLength", "contextAuto", "modelName", "modelNameAuto"):
                if key in route:
                    route.pop(key)
                    changed = True
            continue
        if not meta or not meta["name"]:
            continue
        # Only sync clientId and role — the label is now cosmetic / user-set.
        # Port is the source of truth; display names come from clientAliases.
        if (str(route.get("clientId") or "") != meta["clientId"]
                or str(route.get("role") or "") != meta["role"]):
            route["clientId"], route["role"] = meta["clientId"], meta["role"]
            changed = True
        # A cleared setting must be cleared on the copy too: otherwise the
        # proxy would keep publishing a number the operator already removed
        # — exactly "absence drawn as normal" (docs/why.md).
        for key in ("contextLength", "contextAuto", "modelName", "modelNameAuto"):
            want = meta.get(key)
            if want is None:
                if key in route:
                    route.pop(key)
                    changed = True
            elif route.get(key) != want:
                route[key] = want
                changed = True
    if changed:
        write_agent_proxy_payload(payload)
    return changed

def _aliased(row, aliases):
    """A row with the operator's name for it applied on read, never stored."""
    reported_name = row.get("name") or row.get("id") or ""
    alias = str(aliases.get(row.get("id")) or "").strip()
    row["reportedName"] = reported_name
    row["alias"] = alias
    if alias:
        row["name"] = alias
    return row


def topology_clients():
    """The operator's client records as the board reads them: names with their
    aliases, agents with theirs. A client has no liveness of its own — no
    report speaks for it; its agents' traffic is what shows whether it works.
    """
    store = topology_store()
    aliases = store.setdefault("clientAliases", {})
    agent_aliases = store.setdefault("agentAliases", {})
    rows = []
    for client in store["clients"].values():
        row = dict(client)
        # An agent alias is applied HERE, on read, and never written into the
        # record: renaming is the board's word about the block, not an edit of
        # what the operator created.
        if row.get("agents"):
            row["agents"] = [dict(a, **({"reportedName": a.get("name"),
                                         "name": agent_aliases[f"{row.get('id')}::{a.get('id')}"]}
                                        if agent_aliases.get(f"{row.get('id')}::{a.get('id')}") else {}))
                             for a in row["agents"] if isinstance(a, dict)]
        rows.append(_aliased(row, aliases))
    return sorted(rows, key=lambda row: row.get("name") or row.get("id") or "")


def topology_hosts():
    """Machines with a scout as the board reads them: the report, its liveness
    computed on read (HostRecord.liveness, never stored — a stored "online" is
    stale the moment it is written), and the operator's name for the machine.
    Online first, then by name.
    """
    now = int(time.time())
    store = topology_store()
    aliases = store.setdefault("clientAliases", {})
    rows = []
    for host in store["hosts"].values():
        row = _aliased(dict(host), aliases)
        row["state"], row["ageSeconds"] = HostRecord.liveness(row, now, HOST_REPORT_TTL)
        rows.append(row)
    return sorted(rows, key=lambda row: (row.get("state") != "online", row.get("name") or row.get("id") or ""))


def refresh_hosts_from_scouts():
    """Pull fresh state from each machine's scout between its heartbeats.

    GET /api/state rather than waiting for the next beat, so GPU inventory and
    the cells' startup progress stay current while the board is open. It runs
    in the background (SCOUT_POLLER, caravan/admin/scout_poll.py), never inside
    a board read. An unreachable scout is skipped; its host record stays as its
    last report left it.
    """
    store = topology_store()
    for host in list(store["hosts"].values()):
        agent_url = str(host.get("agentUrl") or "").strip().rstrip("/")
        if not agent_url:
            continue
        try:
            state = fetch_json(f"{agent_url}/api/state", timeout=2, headers=_scout_headers())
            if not isinstance(state, dict):
                continue
            record_host_report(scout_payload_from_state(state, agent_url))
        except Exception:
            continue


def scout_payload_from_state(state, agent_url):
    """A scout's /api/state in the shape of its heartbeat, so record_host_report
    stores the pull and the beat alike.

    Whichever of the two arrives last replaces the host record, so they must
    carry the same fields under the same names: a field only one carries
    blinks in and out every minute. Checked against the scout's own report
    sample (scripts/test_scout_report_sample.py).
    """
    return {
        "host": state.get("host") or {},
        "gpus": state.get("gpus") or [],
        "computeApps": state.get("computeApps") or [],
        "cpu": state.get("cpu") or {},
        "platform": state.get("platform") or "",
        # Carry llama-node status through, otherwise an active refresh
        # between heartbeats would wipe the running remote server.
        "llamaNode": state.get("llamaNode") or {},
        "llamaNodes": state.get("llamaNodes") or [],
        "llamaBinaryVersion": state.get("llamaBinaryVersion") or "",
        "llamaBinaryMtime": state.get("llamaBinaryMtime") or "",
        "llamaUpdate": state.get("llamaUpdate") if isinstance(state.get("llamaUpdate"), dict) else {},
        "scoutVersion": state.get("scoutVersion") or "",
        "autostart": state.get("autostart") if isinstance(state.get("autostart"), list) else None,
        "llamaSuspect": state.get("llamaSuspect") if isinstance(state.get("llamaSuspect"), dict) else None,
        "agentUrl": agent_url,
        "time": state.get("time") or int(time.time()),
    }


#: Adding a machine's scout from the board and letting it go (scout_pairing.py).
SCOUT_PAIRING = ScoutPairing(topology_store, save_admin_state, _scout_headers, ADMIN_PORT, TOPOLOGY_SERVER_IP)

#: The one poller of the fleet: board reads kick it (topology_state), and it
#: runs refresh_hosts_from_scouts in the background.
SCOUT_POLLER = ScoutPoller(lambda: refresh_hosts_from_scouts())

def set_topology_agent_alias(host_id, agent_id, name):
    """What an agent's block is named on the board. An alias, not a record edit.

    A client's agent name arrives from the scout's REPORT and is replaced
    wholesale on every heartbeat: editing the record itself would only last
    until the next poll and vanish silently — exactly the failure client
    aliases exist to avoid. So the name lives alongside the record, not
    inside it, and survives the report.

    Empty clears it: the agent's own self-reported name is shown again.
    """
    host_id = str(host_id or "").strip()[:120]
    agent_id = str(agent_id or "").strip()[:80]
    if not host_id or not agent_id:
        raise AppError("hostId and agentId are required", 400)
    alias = str(name or "").strip()[:120]
    store = topology_store()
    aliases = store.setdefault("agentAliases", {})
    key = f"{host_id}::{agent_id}"
    if alias:
        aliases[key] = alias
    else:
        aliases.pop(key, None)
    save_admin_state()
    return {"hostId": host_id, "agentId": agent_id, "alias": alias}


def set_topology_client_alias(host_id, name):
    host_id = str(host_id or "").strip()[:120]
    if not host_id:
        raise AppError("hostId is required", 400)
    alias = str(name or "").strip()[:120]
    store = topology_store()
    if alias:
        store["clientAliases"][host_id] = alias
    else:
        store["clientAliases"].pop(host_id, None)
    save_admin_state()
    return {"hostId": host_id, "alias": alias}
