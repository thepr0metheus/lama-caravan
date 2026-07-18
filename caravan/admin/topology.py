"""Topology assembly: the /api/topology tree (clients, servers, GPUs, proxies,
routers) built from heartbeats, probes, systemd and the proxy state files."""
import glob
import os
import re
import time

from caravan.admin.cloud import cloud_accounts_state, cloud_blocks_state, cloud_provider_presets_public
from caravan.admin.config_builder import models_dir_from_config, parse_config
from caravan.admin.runners import cell_artifact_label, effective_health_path, uses_command_path
from caravan.admin.fleet_clients import assignment_port_claims, refresh_topology_clients_from_agents, topology_clients
from caravan.admin.llama_metrics import runtime_metrics_sample, runtime_phase, vllm_metrics_sample
from caravan.admin.monitoring import (
    cpu_snapshot,
    gpu_compute_apps,
    gpu_state,
    _llama_activity_lock,
    llama_activity_cache,
    llama_activity_sample,
    memory_state,
    runtime_api,
)
from caravan.admin.openclaw import openclaw_configs_snapshot
from caravan.admin.paths import IS_CONTAINER, SERVICE_NAME, TOPOLOGY_SERVER_IP, is_controller_host
from caravan.admin.proxies_config import (
    load_agent_proxy_config,
    read_agent_proxy_payload,
    set_agent_proxy_policy,
    sync_router_outputs,
    write_agent_proxy_payload,
)
from caravan.admin.router_dsl import normalize_agent_proxy_policy
from caravan.admin.server_cells import server_slot_key
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.systemd_ctl import cell_last_error, cell_progress_note, cell_service_name, cell_service_status, cell_unit_pids, service_status, systemd_ts_epoch
from caravan.admin.telemetry import (
    _normalize_modalities,
    _record_cpu_history,
    _record_gpu_history,
    _record_tps_history,
    command_cell_health,
    firewall_port_access,
    probe_remote_port,
    remote_llama_health,
    remote_llama_modalities,
)
from caravan.common.errors import AppError
from caravan.common.fetch import post_json


_SLOT_MODEL_SIZE_CACHE = {}  # model path → (bytes, checked_at)


def _slot_model_size_bytes(model_path, models_dir):
    """Weights-on-disk for a stopped cell's ≈VRAM badge. Controller paths stat
    directly (multi-part GGUFs sum their siblings); client paths fall back to a
    same-basename file under the controller models tree — clients run the same
    GGUFs. 0 = unknown → no badge."""
    if not model_path:
        return 0
    now = time.time()
    hit = _SLOT_MODEL_SIZE_CACHE.get(model_path)
    if hit and now - hit[1] < 300:
        return hit[0]
    size = 0
    try:
        path = model_path
        if not os.path.isfile(path) and models_dir:
            base = os.path.basename(model_path)
            for root, _dirs, files in os.walk(models_dir):
                if base in files:
                    path = os.path.join(root, base)
                    break
        if os.path.isfile(path):
            size = os.path.getsize(path)
            part = re.search(r"-(\d{5})-of-(\d{5})\.gguf$", path)
            if part:
                size = sum(os.path.getsize(p) for p in glob.glob(
                    path[: -len(part.group(0))] + "-*-of-" + part.group(2) + ".gguf"))
    except OSError:
        size = 0
    _SLOT_MODEL_SIZE_CACHE[model_path] = (size, now)
    return size


def topology_server(config=None):
    config = config or parse_config()
    service = service_status()
    runtime = runtime_api(config)
    runtime["status"] = runtime_phase(service, runtime)
    raw_gpus = gpu_state().get("gpus", [])
    gpus = []
    for index, gpu in enumerate(raw_gpus):
        row = dict(gpu)
        row.setdefault("index", index)
        gpus.append(row)
    port = int(config.get("PORT") or 8080)

    try:
        controller_pid = int(service.get("MainPID") or 0)
    except (TypeError, ValueError):
        controller_pid = 0
    ctrl_metrics = runtime_metrics_sample()
    # Context window the server was launched with (n_ctx from /props, falling
    # back to the configured CTX_SIZE) and how much of it is currently held in
    # the KV cache (usage ratio × n_ctx) — drops to ~0 when all slots idle.
    ctrl_props = runtime.get("props") if isinstance(runtime, dict) else {}
    ctrl_gen = (ctrl_props or {}).get("default_generation_settings") or {}
    try:
        ctrl_ctx_max = int(ctrl_gen.get("n_ctx") or (ctrl_props or {}).get("n_ctx") or config.get("CTX_SIZE") or 0)
    except (TypeError, ValueError):
        ctrl_ctx_max = 0
    ctrl_ctx_used = None
    if ctrl_metrics.get("ok") and ctrl_ctx_max:
        try:
            ctrl_ctx_used = int(round(float(ctrl_metrics.get("kvCacheUsageRatio") or 0) * ctrl_ctx_max))
        except (TypeError, ValueError):
            ctrl_ctx_used = None
    llama_servers = []
    # Legacy single-server service: keep it visible only when it is actually up.
    # Reserved cells are now the default representation, so a stale config must
    # not create a confusing stopped card on port 8080.
    if service.get("ActiveState") == "active":
        llama_servers.append({
            "id": "current",
            "name": "Current",
            "port": port,
            "host": config.get("HOST") or "0.0.0.0",
            "model": config.get("MODEL_FILE") or "",
            "mmproj": config.get("MMPROJ_FILE") or "",
            "specDraft": config.get("SPEC_DRAFT_MODEL_FILE") or "",
            "specType": config.get("SPEC_TYPE") or "",
            "status": runtime.get("status") or {},
            "service": SERVICE_NAME,
            "gpuIndexes": [row.get("index") for row in gpus if row.get("index") is not None],
            "isRemote": False,
            "isController": True,
            "pid": controller_pid,
            "firewall": firewall_port_access(port),
            # Same token-rate fields as remote servers, so the UI renders both
            # uniformly (no isController special-case in the frontend).
            "promptTps": ctrl_metrics.get("promptTokensPerSecond") if ctrl_metrics.get("ok") else None,
            "genTps": ctrl_metrics.get("predictedTokensPerSecond") if ctrl_metrics.get("ok") else None,
            "ctxMax": ctrl_ctx_max or None,
            "ctxUsed": ctrl_ctx_used,
            # Authoritative input modalities from the controller's own /props.
            "modalities": _normalize_modalities((ctrl_props or {}).get("modalities")),
        })

    # Launch-time context window per remote slot (CTX_SIZE captured when the
    # server was started) — used as the "ctxMax" fallback when the route-agent
    # doesn't report n_ctx itself.
    def _slot_ctx_max(host_id, port):
        slot = topology_store().get("serverSlots", {}).get(server_slot_key(host_id, port)) or {}
        cfg = slot.get("config") or {}
        try:
            return int(cfg.get("CTX_SIZE") or 0) or None
        except (TypeError, ValueError):
            return None

    # Add remote llama-servers from connected clients — running OR still
    # starting up (downloading the model / loading into VRAM).
    startup_phases = ("resolving", "downloading", "loading")
    _tstore = topology_store()
    # A client may run several concurrent slots (translator + whisper + …), each
    # reported as one entry in llamaNodes. Flatten to (client, node) pairs and
    # render one server cell per node. Fall back to the legacy single llamaNode.
    _client_nodes = []
    for client in _tstore.get("clients", {}).values():
        _nodes = client.get("llamaNodes")
        if not isinstance(_nodes, list) or not _nodes:
            _nodes = [client.get("llamaNode") or {}]
        for _n in _nodes:
            _client_nodes.append((client, _n or {}))
    for client, ln in _client_nodes:
        phase = str(ln.get("phase") or "")
        running = bool(ln.get("running"))
        last_error = str(ln.get("lastError") or "").strip()
        # Heartbeat may report phase="" with a lastError when download fails
        # before the server process even starts — treat it as "error".
        if not phase and last_error:
            phase = "error"
        if not running and phase not in startup_phases and phase != "error":
            continue
        client_ip = str(client.get("ip") or "").strip()
        remote_port = ln.get("port")
        # Port may be missing on early failures (download error before bind).
        # Fall back to the saved server slot for this client.
        if not remote_port and phase == "error":
            host_id = str(client.get("id") or "")
            for _slot in _tstore.get("serverSlots", {}).values():
                if str(_slot.get("hostId") or "") == host_id:
                    remote_port = _slot.get("port")
                    break
        if not client_ip or not remote_port:
            continue
        client_name = str(client.get("name") or client.get("id") or "").strip()
        _r_host_id = str(client.get("id") or "")
        _r_slot = _tstore.get("serverSlots", {}).get(server_slot_key(_r_host_id, remote_port))
        model_path = str(ln.get("modelPath") or "")
        # Fall back to slot's saved model when the live server hasn't reported it yet.
        if not model_path and _r_slot:
            model_path = str(_r_slot.get("model") or "")
        model_name = model_path.split("/")[-1] if model_path else ""
        gpu_name = ""
        if client.get("gpus"):
            gpu_name = str((client["gpus"][0] or {}).get("name") or "")
        # The route-agent reports running=True as soon as the process is up, but
        # llama.cpp keeps loading the model into VRAM afterwards (/health → 503).
        # Probe /health so we can show a distinct "loading into VRAM" state.
        _r_cfg = (_r_slot.get("config") or {}) if _r_slot else {}
        slot_is_command = uses_command_path(_r_cfg)
        _cmd_dl = _cmd_tot = 0
        _cmd_phase = ""
        if slot_is_command:
            # Command cells have no llama /health — probe HEALTH_PATH (whisper_server.py
            # reports download/load progress there) or the port.
            # effective_health_path: explicit HEALTH_PATH, else the runner's own
            # (/health for whisper, /v1/models for vLLM) — a bare TCP probe says
            # "running" the moment the port listens, mid-download.
            _ch = command_cell_health(client_ip, remote_port, effective_health_path(_r_cfg)) if running else None
            _cmd_phase = (_ch or {}).get("status") or ""
            _cmd_dl = (_ch or {}).get("downloadedBytes") or 0
            _cmd_tot = (_ch or {}).get("totalBytes") or 0
            health = ("ok" if _cmd_phase == "ok"
                      else "loading" if _cmd_phase in ("downloading", "loading")
                      else "down" if _cmd_phase == "down" else None)
        else:
            health = remote_llama_health(client_ip, remote_port) if running else None
        warming = running and health == "loading"
        effective_phase = "warming" if warming else ("running" if running else phase)
        # A command cell that reports a concrete download/load phase shows it (so
        # "downloading" surfaces the % bar) instead of the generic "warming".
        if slot_is_command and _cmd_phase in ("downloading", "loading"):
            effective_phase = _cmd_phase
        # Authoritative input modalities: probe the remote /props once the model
        # is loaded (cached); fall back to whatever the heartbeat carried.
        remote_mods = None
        if health == "ok" and not slot_is_command:
            remote_mods = remote_llama_modalities(client_ip, remote_port)
        if remote_mods is None:
            remote_mods = _normalize_modalities(ln.get("modalities"))
        llama_servers.append({
            "id": f"remote:{client.get('id')}:{remote_port}",
            "name": client_name,
            "port": remote_port,
            "host": client_ip,
            "model": model_name,
            # What a command cell runs — a llama cell says it with MODEL_FILE,
            # these have only a command, and lists with no room for a card had
            # nothing but the port to show.
            "cellLabel": cell_artifact_label(_r_cfg),
            "modelPath": model_path,
            "mmproj": str(ln.get("mmprojPath") or ""),
            "specDraft": str(ln.get("specPath") or ""),
            "specType": str(ln.get("specType") or ""),
            "status": {"phase": effective_phase if running else (phase or "starting")},
            "service": "",
            "gpuIndexes": [],
            "isRemote": True,
            "clientId": str(client.get("id") or ""),
            "clientIp": client_ip,
            "gpuName": gpu_name,
            "uptimeSec": ln.get("uptimeSec"),
            "pid": ln.get("pid"),
            "phase": effective_phase,
            "modelReady": (health == "ok") if running else None,
            "downloadedBytes": _cmd_dl or int(ln.get("downloadedBytes") or 0),
            "totalBytes": _cmd_tot or int(ln.get("totalBytes") or 0),
            "promptTps": ln.get("promptTps"),
            "genTps": ln.get("genTps"),
            "schedule": (_r_slot or {}).get("schedule") or None,
            "ctxMax": ln.get("ctxMax") or _slot_ctx_max(client.get("id"), remote_port),
            "ctxUsed": ln.get("ctxUsed"),
            "modalities": remote_mods,
            "firewall": ln.get("firewall"),
            "lastError": str(ln.get("lastError") or "")[:300] if phase == "error" else "",
            # Probe the inference port from the admin host so the UI can warn
            # when a host firewall blocks it (only meaningful once running).
            "reachable": probe_remote_port(client_ip, remote_port) if running else None,
            # Mark as slot cell when this port is tracked in serverSlots.
            "isSlot": bool(_r_slot),
            "isController": False,
            "slotConfig": (_r_slot.get("config") or {}) if _r_slot else {},
            "commandHistory": (_r_slot.get("commandHistory") or []) if _r_slot else [],
            "bootEnabled": False,
        })

    # Persistent server slots not currently live → render as stopped servers so
    # the proxy cable stays attached across stop / model change.
    store = _tstore
    live_keys = {
        (s.get("clientId") if s.get("isRemote") else "skynet", s.get("port"))
        for s in llama_servers
    }
    clients_by_id = store.get("clients", {})
    for slot in store.get("serverSlots", {}).values():
        host_id = str(slot.get("hostId") or "")
        port = slot.get("port")
        if (host_id, port) in live_keys:
            continue
        is_controller_slot = is_controller_host(host_id)
        client = {} if is_controller_slot else (clients_by_id.get(host_id) or {})
        client_ip = str(client.get("ip") or "").strip()
        gpu_name = ""
        if client.get("gpus"):
            gpu_name = str((client["gpus"][0] or {}).get("name") or "")
        model_path = str(slot.get("model") or "")
        slot_cfg = slot.get("config") or {}
        slot_is_command = uses_command_path(slot_cfg)
        # A configured command cell has no MODEL_FILE but still counts as
        # "configured" (stopped), not an empty "reserved" slot.
        slot_phase = "stopped" if (model_path or (slot_is_command and (
            slot_cfg.get("COMMAND") or slot_cfg.get("VLLM_MODEL")
            or str(slot_cfg.get("RUNNER") or "").strip().lower() == "whisper"))) else "reserved"
        service_name = SERVICE_NAME if is_controller_slot else ""
        cell_status = {}
        cell_pid = None
        cell_boot = ""
        cell_metrics = {}
        slot_vllm_stats = None
        _cdl = _ctot = 0
        if is_controller_slot:
            cell_status = cell_service_status(port)
            service_name = cell_status.get("service") or cell_service_name(port)
            cell_boot = cell_status.get("UnitFileState") or ""
            try:
                cell_pid = int(cell_status.get("MainPID") or 0) or None
            except (TypeError, ValueError):
                cell_pid = None
            if cell_status.get("ActiveState") == "active":
                if slot_is_command:
                    # Command cells have no llama /health; probe HEALTH_PATH
                    # (whisper reports download/load progress there) or the port.
                    _ch = command_cell_health("127.0.0.1", port, effective_health_path(slot_cfg))
                    _cph = (_ch or {}).get("status") or ""
                    _cdl = (_ch or {}).get("downloadedBytes") or 0
                    _ctot = (_ch or {}).get("totalBytes") or 0
                    slot_phase = ("running" if _cph == "ok"
                                  else _cph if _cph in ("downloading", "loading")
                                  else "starting")
                else:
                    health = remote_llama_health("127.0.0.1", port)
                    if health == "ok":
                        slot_phase = "running"
                    elif health == "loading":
                        slot_phase = "warming"
                    else:
                        slot_phase = "starting"
            elif cell_status.get("ActiveState") == "failed":
                slot_phase = "error"
            elif cell_status.get("ActiveState") in ("activating", "reloading"):
                # auto-restart = the unit is flapping (exec failed / instant
                # crash). Without this branch the card silently shows
                # "stopped" while systemd retries every 3s.
                flapping = cell_status.get("SubState") == "auto-restart" or (
                    cell_status.get("Result") not in ("", "success", None))
                slot_phase = "error" if flapping else "starting"
            # Scrape the cell's own /metrics so token throughput shows for the
            # controller cell too — it isn't a remote client (no heartbeat) and
            # isn't the legacy "current" service, so nothing else samples it.
            # (Command cells aren't llama-server — nothing to scrape.)
            if slot_phase == "running" and not slot_is_command:
                cell_metrics = runtime_metrics_sample(port)
            # vLLM exports its own Prometheus metrics — same card treatment.
            elif slot_phase == "running" and str(slot_cfg.get("RUNNER") or "").strip().lower() == "vllm":
                vm = vllm_metrics_sample(port)
                if vm.get("ok"):
                    cell_metrics = {"ok": True,
                                    "promptTokensPerSecond": vm.get("promptTps"),
                                    "predictedTokensPerSecond": vm.get("genTps")}
                    slot_vllm_stats = vm
        cell_error = None
        if is_controller_slot:
            # Classify WHY it won't start (journal tail, cached) so the card
            # can show a human hint instead of a bare red pill. Also attach it
            # DURING a retry (starting/warming with restart history) — in a
            # crash-loop the card spends most time "loading model into VRAM",
            # and the user must see what the previous attempt died of.
            try:
                restarts = int(cell_status.get("NRestarts") or 0)
            except (TypeError, ValueError):
                restarts = 0
            failing = slot_phase == "error" or (
                restarts > 0 and slot_phase in ("starting", "warming"))
            if failing:
                try:
                    cell_error = cell_last_error(port)
                except Exception:
                    cell_error = None
        # Authoritative modalities for a live cell (controller on 127.0.0.1,
        # remote on its IP). Stopped/reserved cells have no running server.
        progress_note = ""
        if is_controller_slot and slot_phase in ("starting", "warming"):
            try:
                progress_note = cell_progress_note(port)
            except Exception:
                progress_note = ""
        slot_mods = None
        if slot_phase == "running" and not slot_is_command:
            probe_ip = "127.0.0.1" if is_controller_slot else client_ip
            if probe_ip:
                slot_mods = remote_llama_modalities(probe_ip, port)
        controller_name = os.environ.get("LLAMA_TOPOLOGY_SERVER_NAME", "skynet")
        controller_ip = TOPOLOGY_SERVER_IP
        llama_servers.append({
            "id": f"slot:{host_id}:{port}",
            "name": str((controller_name if is_controller_slot else client.get("name")) or host_id),
            "port": port,
            "host": (controller_ip if is_controller_slot else client_ip),
            "model": model_path.split("/")[-1] if model_path else "",
            "cellLabel": cell_artifact_label(slot.get("config") or {}),
            "modelPath": model_path,
            "mmproj": str(((slot.get("config") or {}).get("MMPROJ_FILE")) or ""),
            "specDraft": str(((slot.get("config") or {}).get("SPEC_DRAFT_MODEL_FILE")) or ""),
            "specType": str(((slot.get("config") or {}).get("SPEC_TYPE")) or ""),
            "status": ({"phase": slot_phase,
                        **({"progressNote": progress_note} if progress_note else {}),
                        # When the crash happened — old failures shouldn't read
                        # as "it just died again" on the card.
                        **({"errorAt": systemd_ts_epoch(cell_status.get("ExecMainExitTimestamp"))}
                           if systemd_ts_epoch(cell_status.get("ExecMainExitTimestamp")) else {}),
                        ("error" if slot_phase == "error" else "lastError"): cell_error}
                       if cell_error else
                       ({"phase": slot_phase, "progressNote": progress_note}
                        if progress_note else {"phase": slot_phase})),
            "service": service_name,
            "gpuIndexes": [],
            "isRemote": not is_controller_slot,
            "isController": is_controller_slot,
            "isSlot": True,
            "clientId": "" if is_controller_slot else host_id,
            "clientIp": "" if is_controller_slot else client_ip,
            "gpuName": gpu_name,
            "modalities": slot_mods,
            "phase": slot_phase,
            "downloadedBytes": _cdl,
            "totalBytes": _ctot,
            "ctxMax": _slot_ctx_max(host_id, port),
            # ≈VRAM hint for a parked cell: weights-on-disk size (context/KV
            # overhead not included). Live phases get the real figure from GPU
            # process memory instead.
            "modelSizeBytes": (_slot_model_size_bytes(model_path, str(models_dir_from_config(config)))
                               if slot_phase in ("stopped", "reserved", "error") else 0),
            "promptTps": cell_metrics.get("promptTokensPerSecond") if cell_metrics.get("ok") else None,
            "genTps": cell_metrics.get("predictedTokensPerSecond") if cell_metrics.get("ok") else None,
            "vllmStats": slot_vllm_stats,
            "artifact": slot.get("artifact") or {},
            "schedule": slot.get("schedule") or None,
            "slotConfig": slot.get("config") or {},
            "commandHistory": slot.get("commandHistory") or [],
            "bootEnabled": cell_boot == "enabled",
            "pid": cell_pid,
            # All unit PIDs — vLLM holds the GPU in a forked worker, and the
            # GPU binder must see it or the cell lands in the CPU section.
            "pids": sorted(cell_unit_pids(port)) if (is_controller_slot and slot_phase == "running") else [],
            "lastError": cell_status.get("error") if slot_phase == "error" else "",
            "firewall": firewall_port_access(port) if is_controller_slot else None,
            "reachable": None,
        })

    return {
        "id": "skynet",
        "name": os.environ.get("LLAMA_TOPOLOGY_SERVER_NAME", "skynet"),
        "ip": TOPOLOGY_SERVER_IP,
        "service": service,
        "runtime": runtime,
        "gpus": gpus,
        "llamaServers": llama_servers,
    }

def _bind_servers_to_gpus(gpus, compute_apps, servers):
    """many-to-many: fill server.gpuIndexes (+ per-gpu MiB) from pid→gpu, and
    reverse-fill gpu.serverPorts. Handles N servers on one GPU and one server
    split across N GPUs."""
    uuid_to_index = {str(g.get("uuid")): g.get("index")
                     for g in gpus if g.get("uuid")}
    pid_indexes: dict = {}
    pid_mem: dict = {}
    for app in compute_apps or []:
        idx = uuid_to_index.get(str(app.get("gpuUuid")))
        if idx is None:
            continue
        pid = app.get("pid")
        pid_indexes.setdefault(pid, set()).add(idx)
        pid_mem[(pid, idx)] = app.get("usedMiB", 0)
    gpu_ports: dict = {}
    for s in servers:
        pids = {p for p in [s.get("pid"), *(s.get("pids") or [])] if p}
        idxs = sorted({i for p in pids for i in pid_indexes.get(p, set())},
                      key=lambda x: (x is None, x))
        # Fall back to any pre-set gpuIndexes (e.g. controller default-all).
        if not idxs and s.get("gpuIndexes"):
            idxs = list(s["gpuIndexes"])
        s["gpuIndexes"] = idxs
        s["gpuMem"] = ({str(i): sum(pid_mem.get((p, i), 0) for p in pids) for i in idxs}
                       if pids else {})
        for i in idxs:
            gpu_ports.setdefault(i, set()).add(s.get("port"))
    for g in gpus:
        g["serverPorts"] = sorted(gpu_ports.get(g.get("index"), set()),
                                  key=lambda x: (x is None, x))
    return servers, gpus

def _server_port_key(s):
    """Stable per-host ordering: by port number only, so a cell keeps its place
    on the card regardless of state. Without this, live cells (assembled from
    heartbeats) sort ahead of stopped slots (appended later), so STARTING a cell
    made it jump up the list."""
    try:
        return int(s.get("port") or 0)
    except (TypeError, ValueError):
        return 0


def topology_nodes(config, server_obj, clients):
    """Host-centric view: one node per machine, each with its GPUs + the
    llama-servers running/declared on it + CPU/RAM. Server↔GPU is bound via
    per-process GPU memory (compute-apps)."""
    nodes = []

    # ── controller node ─────────────────────────────────────────────
    ctrl_gpus = [dict(g) for g in (server_obj.get("gpus") or [])]
    ctrl_servers = [dict(s) for s in (server_obj.get("llamaServers") or [])
                    if not s.get("isRemote")]
    ctrl_servers.sort(key=_server_port_key)
    _bind_servers_to_gpus(ctrl_gpus, gpu_compute_apps(), ctrl_servers)
    _record_gpu_history(server_obj.get("id") or "skynet", ctrl_gpus)
    for s in ctrl_servers:
        s["tpsHistory"] = _record_tps_history(
            f"{server_obj.get('id') or 'skynet'}:{s.get('port')}", s.get("promptTps"), s.get("genTps"))
    ctrl_cpu = {}
    try:
        ctrl_cpu["loadPct"] = cpu_snapshot()
    except Exception:
        pass
    try:
        mem = memory_state()
        if mem.get("ok"):
            ctrl_cpu["ram"] = {
                "usedGb": round(mem.get("usedMiB", 0) / 1024, 1),
                "totalGb": round(mem.get("totalMiB", 0) / 1024, 1),
            }
    except Exception:
        pass
    ctrl_cpu["history"] = _record_cpu_history(server_obj.get("id") or "skynet", ctrl_cpu)
    nodes.append({
        "id": server_obj.get("id") or "skynet",
        "name": server_obj.get("name") or "skynet",
        "ip": server_obj.get("ip"),
        "role": "controller",
        # In container mode the controller cannot host cells (no systemd) —
        # the board hides the reserve/start controls and points at scouts.
        "containerized": IS_CONTAINER,
        "online": True,
        "platform": "linux",
        "cpu": ctrl_cpu,
        "gpus": ctrl_gpus,
        "servers": ctrl_servers,
    })

    # ── client nodes ─────────────────────────────────────────────────────────
    # Servers (running/startup/stopped-slot) already assembled in
    # server_obj.llamaServers — group them by client.
    remote_by_client: dict = {}
    for s in (server_obj.get("llamaServers") or []):
        if s.get("isRemote") and s.get("clientId"):
            remote_by_client.setdefault(str(s["clientId"]), []).append(dict(s))

    for client in clients:
        cid = str(client.get("id") or "")
        cgpus = [dict(g) for g in (client.get("gpus") or []) if g.get("name")]
        for g in cgpus:
            try:
                g["index"] = int(g.get("index")) if g.get("index") is not None else None
            except (TypeError, ValueError):
                g["index"] = None
        servers = remote_by_client.get(cid, [])
        servers.sort(key=_server_port_key)
        _bind_servers_to_gpus(cgpus, client.get("computeApps"), servers)
        _record_gpu_history(cid, cgpus)
        for s in servers:
            s["tpsHistory"] = _record_tps_history(
                f"{cid}:{s.get('port')}", s.get("promptTps"), s.get("genTps"))
        client_cpu = dict(client.get("cpu") or {})
        client_cpu["history"] = _record_cpu_history(cid, client_cpu)
        nodes.append({
            "id": cid,
            "name": client.get("name") or cid,
            "ip": client.get("ip"),
            "role": "client",
            "online": client.get("state") == "online",
            "platform": client.get("platform") or "",
            "cpu": client_cpu,
            "gpus": cgpus,
            "servers": servers,
            "llamaBinaryVersion": client.get("llamaBinaryVersion") or "",
            "llamaBinaryMtime": client.get("llamaBinaryMtime") or "",
            "llamaUpdate": client.get("llamaUpdate") or {},
        })

    return nodes

def _compute_orphaned_agents(clients, store):
    """Dead agents to surface in the UI: assignment entries whose agentId is no
    longer reported by an ONLINE host (left behind after a rename/removal). We
    only flag online hosts — an offline/unknown host may just be silent, not dead.
    Each carries the proxy ports it still holds so deleting it frees them."""
    assignments_store = store.get("assignments") or {}
    by_id = {c.get("id"): c for c in clients}
    # Deleting an orphan only frees ports it is the SOLE claimant of (a rename
    # successor may share them) — show exactly those, so the strip's port list
    # matches what the ✕ will actually free.
    claims = assignment_port_claims(store)
    orphaned = []
    for host_id, host_entry in assignments_store.items():
        client = by_id.get(host_id)
        if not client or client.get("state") != "online":
            continue
        reported = {str(a.get("id") or "") for a in (client.get("agents") or [])}
        for assignment in (host_entry.get("assignments") or []):
            agent_id = str(assignment.get("agentId") or "")
            if not agent_id or agent_id in reported:
                continue
            ports = []
            for route in (assignment.get("routes") or []):
                pid = str(route.get("proxyId") or "")
                if pid.startswith("skynet:proxy:"):
                    try:
                        port = int(pid.split(":")[-1])
                    except ValueError:
                        continue
                    if claims.get(port, 0) <= 1:
                        ports.append(port)
            orphaned.append({
                "clientId": host_id,
                "clientName": client.get("name") or host_id,
                "agentId": agent_id,
                "ports": sorted(set(ports)),
            })
    return orphaned

def topology_state(refresh_clients=True):
    if refresh_clients:
        refresh_topology_clients_from_agents()
    config = parse_config()
    store = topology_store()
    proxy_config = load_agent_proxy_config()
    policy = proxy_config.get("policy") or normalize_agent_proxy_policy({})
    total_slots = _llama_total_slots()
    if total_slots and int(policy.get("maxSlots") or 0) != total_slots:
        policy = dict(policy)
        policy["maxSlots"] = total_slots
        try:
            set_agent_proxy_policy(policy)
        except Exception:
            pass
    proxies = []
    _routers_by_id = {str(r.get("id")): r for r in (proxy_config.get("routers") or [])}
    for route in proxy_config.get("routes", []):
        proxy = {
            **route,
            "id": f"skynet:proxy:{route.get('port')}",
            "endpoint": f"http://{TOPOLOGY_SERVER_IP}:{route.get('port')}/v1",
            "upstreamId": f"skynet:llama-server:{route.get('upstreamPort')}",
        }
        # Resolve the actual upstream the proxy routes to via its router graph outputs.
        # route.upstreamPort is a legacy placeholder (:8080); the graph output is authoritative.
        router = _routers_by_id.get(str(route.get("routerId") or ""))
        if router:
            outputs = router.get("outputs") or []
            default_id = str((router.get("rules") or {}).get("default") or "")
            out = next((o for o in outputs if str(o.get("id")) == default_id), None)
            if not out:
                out = next((o for o in outputs if str(o.get("upstreamType") or "llama") != "cloud"), None)
            if out and int(out.get("upstreamPort") or 0):
                proxy["resolvedUpstreamHost"] = str(out.get("upstreamHost") or "127.0.0.1")
                proxy["resolvedUpstreamPort"] = int(out.get("upstreamPort"))
        proxies.append(proxy)
    server_obj = topology_server(config)
    # Auto-sync router outputs to the available providers (local llama servers
    # now; cloud later). Persist once when they change so agent-proxies.py routes.
    try:
        routers = proxy_config.get("routers") or []
        if sync_router_outputs(routers, server_obj, cloud_accounts_state(), cloud_blocks_state()):
            # Re-read fresh payload before writing to avoid overwriting concurrent
            # label/policy changes that happened since proxy_config was loaded above.
            fresh = read_agent_proxy_payload()
            fresh["routers"] = routers
            write_agent_proxy_payload(fresh)
            proxy_config["routers"] = routers
    except Exception:
        pass
    clients = topology_clients()
    # Cloud state + catalog annotation: unlisted marks on blocks, background
    # model-list refreshes, endpoint-health report. Annotation must never sink
    # the board — degrade to plain state on any failure.
    cloud_accounts = cloud_accounts_state()
    cloud_blocks = cloud_blocks_state()
    try:
        from caravan.admin.cloud_api import annotate_cloud_topology
        cloud_api_health = annotate_cloud_topology(cloud_accounts, cloud_blocks)
    except Exception:
        cloud_api_health = {"endpoints": {}, "codexClientVersion": {}}
    # Crash watchdog verdict (cached 60s inside): a fresh llama.cpp build plus
    # crashing cells → the board banner offers a consented rollback.
    from caravan.admin.status import llama_crash_suspect
    return {
        "server": server_obj,
        "llamaSuspect": llama_crash_suspect(),
        # Host-centric model (Stage 1): one node per machine with its GPUs +
        # servers + CPU/RAM, server↔GPU bound via compute-apps. The UI still
        # reads server/clients for now; `nodes` is the new spine.
        "nodes": topology_nodes(config, server_obj, clients),
        "proxies": proxies,
        # Routers (Роутеры) — the routing layer between proxies and servers.
        # inputs already derived from routes by normalize_routers.
        "routers": proxy_config.get("routers") or [],
        "proxyPolicy": policy,
        "effectiveSlots": total_slots or int(policy.get("maxSlots") or 1),
        "clients": clients,
        "assignments": store.get("assignments", {}),
        # Dead agents (assignment exists but agent no longer reported by an online
        # host) — surfaced so the user can delete them and free their proxy ports.
        "orphanedAgents": _compute_orphaned_agents(clients, store),
        # User notes on cell slots, keyed "hostId:port" — shown on the board
        # cards and edited in the cell detail modal.
        "cellNotes": {key: str(slot.get("note") or "")
                      for key, slot in (store.get("serverSlots") or {}).items()
                      if isinstance(slot, dict) and str(slot.get("note") or "").strip()},
        "clientAliases": store.get("clientAliases", {}),
        "layout": store.get("layout", {}),
        "openclawConfigs": openclaw_configs_snapshot(),
        "cloudAccounts": cloud_accounts,
        "cloudProviders": cloud_blocks,
        # Tripped upstream endpoints + effective codex client_version — the
        # provider cards render this as the "API issues" panel.
        "cloudApiHealth": cloud_api_health,
        "cloudProviderPresets": cloud_provider_presets_public(),
        "time": int(time.time()),
    }

def _llama_total_slots():
    with _llama_activity_lock:
        cached = llama_activity_cache.get("data") if isinstance(llama_activity_cache, dict) else None
    if isinstance(cached, dict):
        total = cached.get("totalSlots")
        if isinstance(total, int) and total > 0:
            return total
    try:
        sample = llama_activity_sample()
    except Exception:
        return 0
    if isinstance(sample, dict):
        total = sample.get("totalSlots")
        if isinstance(total, int) and total > 0:
            return total
    return 0

def normalize_topology_assignment(assignment):
    if not isinstance(assignment, dict):
        raise AppError("assignment must be an object", 400)
    agent_id = str(assignment.get("agentId") or "").strip()
    if not agent_id:
        raise AppError("assignment.agentId is required", 400)
    routes = assignment.get("routes") or []
    if not isinstance(routes, list):
        raise AppError("assignment.routes must be a list", 400)
    normalized_routes = []
    seen_roles = set()
    for route in routes:
        if not isinstance(route, dict):
            raise AppError("route must be an object", 400)
        role = str(route.get("role") or "primary").strip()
        endpoint = str(route.get("endpoint") or "").strip()
        proxy_id = str(route.get("proxyId") or "").strip()
        if not endpoint:
            raise AppError("route.endpoint is required", 400)
        if role in seen_roles:
            raise AppError(f"duplicate route role: {role}", 400)
        seen_roles.add(role)
        normalized_routes.append({"role": role, "proxyId": proxy_id, "endpoint": endpoint})
    return {"agentId": agent_id, "routes": normalized_routes}

def apply_topology_assignments(payload):
    host_id = str(payload.get("hostId") or "").strip()
    assignments = payload.get("assignments")
    if not host_id:
        raise AppError("hostId is required", 400)
    if not isinstance(assignments, list):
        raise AppError("assignments must be a list", 400)
    normalized = [normalize_topology_assignment(row) for row in assignments]
    store = topology_store()
    row = {
        "hostId": host_id,
        "assignments": normalized,
        "desiredAt": int(time.time()),
        "applyStatus": {"state": "pending"},
    }
    client = store["clients"].get(host_id)
    if client and client.get("agentUrl"):
        try:
            from caravan.admin.fleet_clients import _scout_headers
            result = post_json(client["agentUrl"].rstrip("/") + "/api/routing/apply", {"assignments": normalized}, headers=_scout_headers())
            row["applyStatus"] = {"state": "ok" if result.get("ok") else "error", "result": result, "appliedAt": int(time.time())}
        except Exception as exc:
            row["applyStatus"] = {"state": "error", "error": str(exc), "appliedAt": int(time.time())}
    else:
        row["applyStatus"] = {"state": "stored", "detail": "client is not registered or has no agentUrl"}
    store["assignments"][host_id] = row
    save_admin_state()
    return row
