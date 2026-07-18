"""Client fleet management: heartbeats, remote llama-node lifecycle via the
route-agent HTTP API, agent auto-provisioning and fleet-registry discovery."""
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from caravan.admin.config_builder import CONFIG_FIELDS, build_remote_llama_args
from caravan.admin.runners import effective_command, effective_health_path, uses_command_path
from caravan.admin.launch import _sanitize_snapshot_name
from caravan.admin.paths import (
    CONTROLLER_HOST_ID,
    FLEET_REGISTRY_URL,
    TOPOLOGY_SERVER_IP,
    SERVER_BACKUPS_DIR,
    TOPOLOGY_CLIENT_TTL,
    is_controller_host,
)
from caravan.admin.proxies_config import (
    load_agent_proxy_config,
    normalize_routers,
    read_agent_proxy_payload,
    write_agent_proxy_payload,
)
from caravan.admin.router_dsl import DEFAULT_ROUTER_ID, normalize_agent_proxy_policy
from caravan.admin.server_cells import (
    assert_server_cell_port_available,
    move_server_cell,
    normalize_topology_agent,
    server_slot_key,
    upsert_server_slot,
)
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.systemd_ctl import restart_agent_proxy
from caravan.admin.telemetry import _normalize_modalities
from caravan.common.errors import AppError
from caravan.common.fetch import fetch_json, post_json


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
    store = topology_store()
    client = store["clients"].get(host_id)
    if not client:
        raise AppError(f"client not registered: {host_id}", 404)
    assignments = store.get("assignments", {})
    agent_url = str(
        (assignments.get(host_id) or {}).get("agentUrl") or
        client.get("agentUrl") or ""
    ).rstrip("/")
    if not agent_url:
        raise AppError(f"no agentUrl for client {host_id}", 400)
    try:
        result = fetch_json(f"{agent_url}/api/monitor/{kind}", timeout=5, headers=_scout_headers())
    except Exception as exc:
        raise AppError(f"client unreachable: {exc}", 502)
    return result

def client_llama_update(body: dict) -> dict:
    """Start a llama.cpp update job on a client scout. Empty tag → latest
    release; the UI passes the controller's commit to converge the fleet."""
    agent_url = _client_agent_url(str((body or {}).get("hostId") or ""))
    payload = {"tag": str((body or {}).get("tag") or "").strip()}
    try:
        return post_json(f"{agent_url}/api/llama-node/update", payload,
                         timeout=15, headers=_scout_headers())
    except Exception as exc:
        raise AppError(f"client unreachable: {exc}", 502)

def client_llama_update_status(host_id: str) -> dict:
    agent_url = _client_agent_url(host_id)
    try:
        return fetch_json(f"{agent_url}/api/llama-node/update-status",
                          timeout=10, headers=_scout_headers())
    except Exception as exc:
        raise AppError(f"client unreachable: {exc}", 502)

def client_llama_builds(host_id: str) -> dict:
    agent_url = _client_agent_url(host_id)
    try:
        return fetch_json(f"{agent_url}/api/llama-node/builds",
                          timeout=10, headers=_scout_headers())
    except Exception as exc:
        raise AppError(f"client unreachable: {exc}", 502)

def client_llama_restore(body: dict) -> dict:
    agent_url = _client_agent_url(str((body or {}).get("hostId") or ""))
    payload = {"id": str((body or {}).get("id") or "").strip()}
    try:
        return post_json(f"{agent_url}/api/llama-node/restore", payload,
                         timeout=15, headers=_scout_headers())
    except Exception as exc:
        raise AppError(f"client unreachable: {exc}", 502)

def client_llama_start(body: dict) -> dict:
    """Forward a llama-node start request to the named client route-agent."""
    host_id = str(body.get("hostId") or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    store = topology_store()
    assignments = store.get("assignments", {})
    client_meta = store["clients"].get(host_id)
    if not client_meta:
        raise AppError(f"client not registered: {host_id}", 404)
    agent_url = str(
        (assignments.get(host_id) or {}).get("agentUrl") or
        client_meta.get("agentUrl") or ""
    ).rstrip("/")
    if not agent_url:
        raise AppError(f"no agentUrl for client {host_id}", 400)

    payload = {
        "modelPath": str(body.get("modelPath") or "").strip(),
        "port": int(body.get("port") or 8180),
        "gpuLayers": int(body.get("gpuLayers") or 999),
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
        if not payload["command"]:
            raise AppError("command is required for a command cell", 400)
    else:
        # Variant 2: the controller is the single command builder. Send the resolved
        # argument list with path placeholders; the agent only substitutes the real
        # downloaded paths and runs it — no flag logic on the client.
        payload["args"] = build_remote_llama_args(payload["config"])
        if not payload["modelPath"]:
            raise AppError("modelPath is required", 400)
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
        assert_server_cell_port_available(payload["port"], exclude_key=key if key in topology_store().get("serverSlots", {}) else None)

    try:
        result = post_json(f"{agent_url}/api/llama-node/start", payload, timeout=10, headers=_scout_headers())
    except urllib.error.HTTPError as exc:
        # Surface the route-agent's own error message instead of a bare 500.
        detail = ""
        try:
            body = exc.read().decode("utf-8")
            detail = (json.loads(body) or {}).get("error") or body
        except Exception:
            detail = str(exc)
        raise AppError(f"{host_id}: {detail}".strip(), 502)
    except urllib.error.URLError as exc:
        raise AppError(f"{host_id} unreachable: {exc.reason}", 502)
    if result.get("ok"):
        # Persist a server slot so the proxy cable stays attached across
        # stop / model change.
        try:
            upsert_server_slot(host_id, payload["port"], config=payload.get("config"),
                               model=payload["modelPath"])
        except Exception:
            pass
    return {"ok": result.get("ok", False), "hostId": host_id, "result": result}

def _client_agent_url(host_id: str) -> str:
    """Return agentUrl for a registered client, raise AppError if not found."""
    host_id = str(host_id or "").strip()
    if not host_id:
        raise AppError("hostId is required", 400)
    store = topology_store()
    client = store["clients"].get(host_id)
    if not client:
        raise AppError(f"client not registered: {host_id}", 404)
    assignments = store.get("assignments", {})
    agent_url = str(
        (assignments.get(host_id) or {}).get("agentUrl") or
        client.get("agentUrl") or ""
    ).rstrip("/")
    if not agent_url:
        raise AppError(f"no agentUrl for client {host_id}", 400)
    return agent_url

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
    """List cached .gguf model files on a client host's disk."""
    agent_url = _client_agent_url(host_id)
    try:
        result = fetch_json(f"{agent_url}/api/llama-node/list-cache", timeout=5, headers=_scout_headers())
    except Exception as exc:
        raise AppError(f"client unreachable: {exc}", 502)
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
    store = topology_store()
    assignments = store.get("assignments", {})
    client_meta = store["clients"].get(host_id)
    if not client_meta:
        raise AppError(f"client not registered: {host_id}", 404)
    agent_url = str(
        (assignments.get(host_id) or {}).get("agentUrl") or
        client_meta.get("agentUrl") or ""
    ).rstrip("/")
    if not agent_url:
        raise AppError(f"no agentUrl for client {host_id}", 400)
    # Forward the port so the agent stops the RIGHT slot (a client can run several
    # servers now). No port = stop all slots (legacy behaviour).
    stop_body = {}
    if body.get("port"):
        stop_body["port"] = int(body["port"])
    result = post_json(f"{agent_url}/api/llama-node/stop", stop_body, timeout=10, headers=_scout_headers())
    return {"ok": result.get("ok", False), "hostId": host_id, "result": result}

def topology_client_delete(body: dict) -> dict:
    client_id = str(body.get("clientId") or "").strip()
    if not client_id:
        raise AppError("clientId is required", 400)
    store = topology_store()
    if client_id not in store["clients"]:
        raise AppError(f"client not found: {client_id}", 404)
    del store["clients"][client_id]
    # Remove assignments so auto-provisioning doesn't recreate stale proxy entries.
    store.get("assignments", {}).pop(client_id, None)
    save_admin_state()
    return {"ok": True, "clientId": client_id}

def topology_discover_add(body: dict) -> dict:
    """Register a discovered candidate into the fleet registry (the dashboard).

    POSTs {id, name, host, port, ...} to <FLEET_REGISTRY_URL>/api/agents. After this the
    agent is in the single source of truth and will appear via the normal registry path."""
    agent_id = str(body.get("id") or body.get("suggestedId") or "").strip()
    host = str(body.get("host") or body.get("ip") or "").strip()
    try:
        port = int(body.get("port"))
    except (TypeError, ValueError):
        port = 0
    if not agent_id:
        raise AppError("id is required", 400)
    if not host or not port:
        raise AppError("host and port are required", 400)
    if not FLEET_REGISTRY_URL:
        raise AppError("fleet registry is not configured (set FLEET_REGISTRY_URL)", 400)
    entry = {
        "id": agent_id,
        "name": str(body.get("name") or agent_id).strip(),
        "host": host,
        "port": port,
    }
    for opt in ("emoji", "role", "dept", "placement"):
        if body.get(opt):
            entry[opt] = str(body.get(opt)).strip()
    entry.setdefault("placement", f"VM agent-{agent_id}")
    url = FLEET_REGISTRY_URL.rstrip("/") + "/api/agents"
    try:
        result = post_json(url, entry, timeout=8, headers=_scout_headers())
    except Exception as exc:
        raise AppError(f"registry POST failed ({url}): {exc}", 502)
    return {"ok": True, "registered": entry, "registry": url, "result": result}

def topology_client_agent_delete(body: dict) -> dict:
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
    # Record tombstone so refresh_topology_clients_from_agents() doesn't re-add it.
    tombstones = store["deletedAgents"].setdefault(client_id, [])
    if agent_id not in tombstones:
        tombstones.append(agent_id)
    save_admin_state()
    return {"ok": True, "clientId": client_id, "agentId": agent_id}

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


def topology_orphan_assignment_delete(body: dict) -> dict:
    """Delete a dead-agent assignment (agentId no longer reported by the host) and
    free the proxy ports it held. Routes are removed from agent-proxies.json; the
    proxy's listener_watcher unbinds them by mtime — no service restart needed."""
    client_id = str(body.get("clientId") or "").strip()
    agent_id = str(body.get("agentId") or "").strip()
    if not client_id or not agent_id:
        raise AppError("clientId and agentId are required", 400)
    store = topology_store()
    client = store["clients"].get(client_id)
    # Safety: never delete the assignment of a currently-reported (live) agent.
    reported = {str(a.get("id") or "") for a in (client.get("agents") or [])} if client else set()
    if agent_id in reported:
        raise AppError(f"agent '{agent_id}' is currently reported by {client_id} — not orphaned", 400)
    host_entry = (store.get("assignments") or {}).get(client_id) or {}
    assignments = host_entry.get("assignments") or []
    target = next((a for a in assignments if str(a.get("agentId") or "") == agent_id), None)
    if not target:
        raise AppError(f"no assignment for agent '{agent_id}' on '{client_id}'", 404)
    ports = set()
    for route in (target.get("routes") or []):
        pid = str(route.get("proxyId") or "")
        if pid.startswith("skynet:proxy:"):
            try:
                ports.add(int(pid.split(":")[-1]))
            except ValueError:
                pass
    # Only free ports whose SOLE claim is this dead assignment — a successor
    # agent (VM rename) may have adopted the same ports, and dropping their
    # routes would cut its live path.
    claims = assignment_port_claims(store)
    ports = {p for p in ports if claims.get(p, 0) <= 1}
    # Drop the assignment entry.
    host_entry["assignments"] = [a for a in assignments if str(a.get("agentId") or "") != agent_id]
    save_admin_state()
    # Free the ports by removing their routes; listener_watcher unbinds by mtime.
    freed = []
    if ports:
        payload = read_agent_proxy_payload()
        routes = payload.get("routes") or []
        kept = [r for r in routes if int(r.get("port") or 0) not in ports]
        if len(kept) != len(routes):
            freed = sorted(int(r.get("port")) for r in routes if int(r.get("port") or 0) in ports)
            payload["routes"] = kept
            payload["routers"] = normalize_routers(payload.get("routers"), kept)
            write_agent_proxy_payload(payload)
    return {"ok": True, "clientId": client_id, "agentId": agent_id, "freedPorts": freed}

def client_llama_purge_cache(body: dict) -> dict:
    """Ask a client to delete its downloaded model cache (keeps a running model)."""
    host_id = str(body.get("hostId") or "").strip()
    agent_url = _client_agent_url(host_id)
    try:
        result = post_json(f"{agent_url}/api/llama-node/purge-cache", {}, timeout=30, headers=_scout_headers())
    except Exception as exc:
        raise AppError(f"client unreachable: {exc}", 502)
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

def topology_client_from_heartbeat(payload):
    host = payload.get("host") if isinstance(payload.get("host"), dict) else {}
    host_id = str(host.get("id") or host.get("name") or "").strip()[:120]
    if not host_id:
        raise AppError("host.id is required", 400)
    # The controller's own id is a reserved sentinel, and slots are keyed
    # "<hostId>:<port>" — so a client answering to it would write straight into
    # the controller's namespace: two different cells under one key. That is
    # exactly how a running cell went missing from the board once already, and
    # the id here is whatever the client's own config says, so nothing but this
    # check stops it. Refuse the heartbeat rather than merge the two hosts.
    # Case-insensitively on purpose, while is_controller_host() stays exact:
    # the predicate decides behaviour, so it must never take a client whose id
    # differs only in case FOR the controller. A fleet holding both spellings is
    # a reading trap regardless — so refuse the near-miss at the door instead.
    if host_id.casefold() == CONTROLLER_HOST_ID.casefold():
        raise AppError(f'host.id "{CONTROLLER_HOST_ID}" is reserved for the controller — '
                       f"give this client a different hostId", 400)
    agents = []
    for agent in payload.get("agents") or []:
        row = normalize_topology_agent(agent)
        if row:
            agents.append(row)
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
            "promptTps": raw.get("promptTps"),
            "genTps": raw.get("genTps"),
            "requestsProcessing": raw.get("requestsProcessing"),
            "ctxMax": raw.get("ctxMax") or raw.get("nCtx"),
            "ctxUsed": raw.get("ctxUsed"),
            "modalities": _normalize_modalities(raw.get("modalities")),
            "firewall": raw.get("firewall") if isinstance(raw.get("firewall"), dict) else None,
        }
    _raw_nodes = payload.get("llamaNodes")
    llama_nodes = [_san_node(n) for n in _raw_nodes if isinstance(n, dict)] \
        if isinstance(_raw_nodes, list) else []
    llama_node = _san_node(payload.get("llamaNode")) or (llama_nodes[0] if llama_nodes else {})
    if not llama_nodes and llama_node:
        llama_nodes = [llama_node]
    candidates = []
    for cand in (payload.get("candidates") or [])[:32]:
        if not isinstance(cand, dict):
            continue
        machine = str(cand.get("machine") or "").strip()[:120]
        if not machine:
            continue
        row = {
            "machine": machine,
            "suggestedId": str(cand.get("suggestedId") or "").strip()[:80],
            "runtime": str(cand.get("runtime") or "").strip()[:20],
        }
        if cand.get("ip"):
            row["ip"] = str(cand.get("ip")).strip()[:80]
        candidates.append(row)
    now = int(time.time())
    return {
        "id": host_id,
        "name": str(host.get("name") or host_id).strip()[:120],
        "hostname": str(host.get("hostname") or "").strip()[:160],
        "ip": str(host.get("ip") or "").strip()[:80],
        "agentUrl": str(payload.get("agentUrl") or "").strip()[:240],
        "agents": agents,
        "candidates": candidates,
        "gpus": gpus,
        "computeApps": compute_apps,
        "cpu": cpu,
        "platform": platform,
        "llamaNode": llama_node,
        "llamaNodes": llama_nodes,
        "llamaBinaryVersion": str(payload.get("llamaBinaryVersion") or "").strip()[:120],
        "llamaBinaryMtime": str(payload.get("llamaBinaryMtime") or "").strip()[:30],
        "llamaUpdate": payload.get("llamaUpdate") if isinstance(payload.get("llamaUpdate"), dict) else {},
        "assignments": payload.get("assignments") if isinstance(payload.get("assignments"), list) else [],
        "applyStatus": payload.get("applyStatus") if isinstance(payload.get("applyStatus"), dict) else {},
        "firstSeen": now,
        "lastSeen": now,
        "state": "online",
    }

def update_topology_client(payload):
    client = topology_client_from_heartbeat(payload)
    store = topology_store()
    previous = store["clients"].get(client["id"]) or {}
    client["firstSeen"] = previous.get("firstSeen") or client["firstSeen"]
    # Suppress agents that were manually deleted (tombstone list).
    deleted = store["deletedAgents"].get(client["id"]) or []
    if deleted:
        client["agents"] = [a for a in client["agents"] if str(a.get("id") or "") not in deleted]
    store["clients"][client["id"]] = client
    save_admin_state()
    try:
        auto_provision_agent_proxies(client)
        reconcile_proxy_metadata()   # keep proxy labels/clientId/role aligned to assignments
    except Exception:
        pass
    return client

def _next_auto_proxy_primary_port(used_ports):
    """Next odd port >= 8101 where both port and port+1 are free."""
    candidate = 8101
    while candidate in used_ports or (candidate + 1) in used_ports:
        candidate += 2
    return candidate

def _agent_has_full_assignments(agent_id, host_entry, existing_ports):
    """True if the agent already has primary+fallback routes pointing to real proxy ports."""
    by_role = {
        r.get("role"): r
        for a in (host_entry.get("assignments") or []) if a.get("agentId") == agent_id
        for r in (a.get("routes") or [])
    }
    for role in ("primary", "fallback"):
        proxy_id = str(by_role.get(role, {}).get("proxyId") or "")
        if not proxy_id.startswith("skynet:proxy:"):
            return False
        port = int(proxy_id.removeprefix("skynet:proxy:"))
        if port not in existing_ports:
            return False
    return True

def auto_provision_agent_proxies(client):
    """Create proxy port pairs (odd=primary, even=fallback) for agents not yet provisioned."""
    store = topology_store()
    proxy_config = load_agent_proxy_config()
    existing_ports = set(int(r.get("port", 0)) for r in proxy_config.get("routes", []))
    used_ports = set(existing_ports)

    client_id = client["id"]
    server_ip = TOPOLOGY_SERVER_IP
    assignments_store = store.setdefault("assignments", {})
    host_entry = assignments_store.get(client_id, {})

    new_routes = []
    new_agent_ports = {}

    for agent in (client.get("agents") or []):
        agent_id = agent.get("id") or ""
        if not agent_id:
            continue
        if _agent_has_full_assignments(agent_id, host_entry, existing_ports):
            continue

        primary_port = _next_auto_proxy_primary_port(used_ports)
        fallback_port = primary_port + 1
        used_ports.add(primary_port)
        used_ports.add(fallback_port)

        agent_name = str(agent.get("name") or agent_id).strip()
        base = {
            "upstreamHost": "127.0.0.1", "upstreamPort": 8080,
            "upstreamType": "llama", "providerId": "",
            "enabled": True, "mode": "open", "priority": 0, "preemptible": True,
            "clientTimeoutSeconds": 0, "cloudFallbackProviderId": "", "cloudFallbackEligible": False,
            # Router redesign: new proxies feed the shared default router
            # and carry explicit role/client links (no label-suffix guessing).
            "routerId": DEFAULT_ROUTER_ID, "clientId": client_id,
        }
        new_routes.append({**base, "role": "primary", "label": f"{agent_name} primary", "port": primary_port})
        new_routes.append({**base, "role": "fallback", "label": f"{agent_name} fallback", "port": fallback_port})
        new_agent_ports[agent_id] = {"primary": primary_port, "fallback": fallback_port}

    if not new_routes:
        return

    all_routes = sorted(
        proxy_config.get("routes", []) + new_routes,
        key=lambda r: int(r.get("port", 0)),
    )
    write_agent_proxy_payload({
        "routes": all_routes,
        "policy": proxy_config.get("policy") or normalize_agent_proxy_policy({}),
        "routers": normalize_routers(proxy_config.get("routers"), all_routes),
        "stopRequests": proxy_config.get("stopRequests") or [],
    })
    restart_agent_proxy(timeout=30)

    host_mut = assignments_store.setdefault(client_id, {
        "agentUrl": client.get("agentUrl", ""), "assignments": [],
    })
    existing = host_mut.get("assignments") or []
    for agent_id, ports in new_agent_ports.items():
        ag = next((a for a in existing if a.get("agentId") == agent_id), None)
        if ag is None:
            ag = {"agentId": agent_id, "routes": []}
            existing.append(ag)
        assigned_roles = {r.get("role") for r in ag.get("routes", [])}
        for role in ("primary", "fallback"):
            if role not in assigned_roles:
                port = ports[role]
                ag["routes"].append({
                    "role": role,
                    "proxyId": f"skynet:proxy:{port}",
                    "endpoint": f"http://{server_ip}:{port}/v1",
                })
    host_mut["assignments"] = existing
    save_admin_state()

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
                port_meta[port] = {"clientId": host_id, "role": str(r.get("role") or "primary"), "name": name}
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
        if not meta or not meta["name"]:
            continue
        # Only sync clientId and role — the label is now cosmetic / user-set.
        # Port is the source of truth; display names come from clientAliases.
        if (str(route.get("clientId") or "") != meta["clientId"]
                or str(route.get("role") or "") != meta["role"]):
            route["clientId"], route["role"] = meta["clientId"], meta["role"]
            changed = True
    if changed:
        write_agent_proxy_payload(payload)
    return changed

def topology_clients():
    now = int(time.time())
    rows = []
    changed = False
    store = topology_store()
    aliases = store.setdefault("clientAliases", {})
    for client in store["clients"].values():
        row = dict(client)
        reported_name = row.get("name") or row.get("id") or ""
        alias = str(aliases.get(row.get("id")) or "").strip()
        row["reportedName"] = reported_name
        row["alias"] = alias
        if alias:
            row["name"] = alias
        last_seen = int(row.get("lastSeen") or 0)
        row["ageSeconds"] = max(0, now - last_seen) if last_seen else None
        row["state"] = "online" if last_seen and now - last_seen <= TOPOLOGY_CLIENT_TTL else "stale"
        if row["state"] != client.get("state"):
            client["state"] = row["state"]
            changed = True
        rows.append(row)
    if changed:
        save_admin_state()
    return sorted(rows, key=lambda row: (row.get("state") != "online", row.get("name") or row.get("id") or ""))

def refresh_topology_clients_from_agents():
    """Pull fresh state from each registered client route-agent.

    Calls GET /api/state directly instead of triggering a round-trip heartbeat.
    This means GPU inventory and platform info are always current the moment
    the Topology view opens, without waiting for the client's heartbeat interval.
    Falls back gracefully if the client is unreachable.
    """
    store = topology_store()
    for client in list(store["clients"].values()):
        agent_url = str(client.get("agentUrl") or "").strip().rstrip("/")
        if not agent_url:
            continue
        try:
            state = fetch_json(f"{agent_url}/api/state", timeout=2, headers=_scout_headers())
            if not isinstance(state, dict):
                continue
            # Map /api/state response into the heartbeat payload format so
            # update_topology_client() can normalise and store it uniformly.
            payload = {
                "host": state.get("host") or {},
                "agents": state.get("agents") or [],
                "candidates": state.get("candidates") or [],
                "assignments": state.get("assignments") or [],
                "gpus": state.get("gpus") or [],
                "computeApps": state.get("computeApps") or [],
                "cpu": state.get("cpu") or {},
                "platform": state.get("platform") or "",
                "applyStatus": state.get("applyStatus") or {},
                # Carry llama-node status through, otherwise an active refresh
                # between heartbeats would wipe the running remote server.
                "llamaNode": state.get("llamaNode") or {},
                "llamaNodes": state.get("llamaNodes") or [],
                "llamaBinaryVersion": state.get("llamaBinaryVersion") or "",
                "llamaBinaryMtime": state.get("llamaBinaryMtime") or "",
                "llamaUpdate": state.get("llamaUpdate") if isinstance(state.get("llamaUpdate"), dict) else {},
                "agentUrl": agent_url,
                "time": state.get("time") or int(time.time()),
            }
            update_topology_client(payload)
        except Exception:
            continue

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
