"""Topology assembly: the /api/topology tree (clients, servers, GPUs, proxies,
routers) built from heartbeats, probes, systemd and the proxy state files."""
import glob
import json
import os
import pathlib
import re
import time

from caravan.admin.proxy_stats import proxy_ports_last_seen
from caravan.admin.cloud import cloud_accounts_state, cloud_blocks_state, cloud_provider_presets_public
from caravan.admin.config_builder import models_dir_from_config, parse_config
from caravan.admin.cell_assets import cell_source_state
from caravan.admin.runners import (cell_artifact_label, cell_model_ref,
                                   effective_command, effective_health_path,
                                   runner_id, uses_command_path,
                                   uses_token_context)
from caravan.admin.fleet_clients import SCOUT_POLLER, topology_clients, topology_hosts
from caravan.admin.llama_metrics import runtime_metrics_sample, runtime_phase, vllm_metrics_sample
from caravan.admin.models import display_model_name
from caravan.admin.load_progress import LOAD_WATCH
from caravan.admin.model_locator import current_locations
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
from caravan.admin.paths import AGENT_PROXY_STATE_FILE, CONTROLLER_HOST_ID, IS_CONTAINER, SERVICE_NAME, TOPOLOGY_SERVER_IP, is_controller_host, AGENT_PROXY_BASE_PORT, SERVER_CELL_BASE_PORT, SERVER_CELL_UPPER_PORT
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
from caravan.admin.state import topology as topo
from caravan.admin.systemd_ctl import active_cell_unit_ports, cell_crash_note, cell_last_error, cell_progress_note, cell_service_name, cell_service_status, cell_unit_pids, service_status, systemd_ts_epoch
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
from caravan.common.context_window import block_window, effective_window, route_window_inputs, served_window, trained_window
from caravan.domain.client_proxy import AgentAssignment, PROXY_ID_PREFIX, ProxyRoute
from caravan.common.fetch import fetch_json, post_json
from caravan.proxy.graph import PLAIN_REQUEST_CTX, apply_router
from caravan.proxy.output_health import output_health


_SLOT_MODEL_SIZE_CACHE = {}  # model path → (bytes, checked_at)


def _cell_meta(health, cfg, is_command):
    """What a command cell says about itself, plus our verdict on the version it
    is running.

    A cell server is materialized into $HOME at start, so the file next to a
    long-running process can already be newer than the process. The disk says
    "current" while the cell still answers with months-old behaviour, and until
    now nothing anywhere could tell the two apart — the board was green, the
    health check was green, and a consumer got the wrong response shape with no
    way to find out why. So the cell reports the digest it loaded and we compare
    it to what we ship; see cell_assets.cell_source_state for why "unknown" is
    kept distinct from "stale".
    """
    meta = dict((health or {}).get("meta") or {})
    if is_command and (health or {}).get("status") == "ok":
        meta["sourceState"] = cell_source_state(runner_id(cfg), meta.get("source"))
    # What language a translating cell writes. The card wants this and was
    # reading a `targetLang` nothing ever produced, so it silently fell through
    # to the config's SEAMLESS_TGT_LANG — which every cell inherits from the
    # controller defaults. An NLLB cell configured for rus_Cyrl therefore wore
    # the SEAMLESS cell's language. The running cell reports the truth on its
    # health path; the config is the fallback for a stopped one, keyed by the
    # runner so one runner's field can never label another's cell.
    tgt = str((health or {}).get("targetLang") or "").strip()
    if not tgt:
        _key = {"seamless": "SEAMLESS_TGT_LANG", "translate": "TRANSLATE_TGT_LANG"}.get(runner_id(cfg))
        tgt = str((cfg or {}).get(_key) or "").strip() if _key else ""
    if tgt:
        meta["targetLang"] = tgt
    return meta


def _saved_command(slot, config, on_controller):
    """The launch line this cell is saved with — for a cell on EITHER kind of host.

    A controller cell has a start.sh: a snapshot taken when the operator pressed
    Apply. Starting a cell does not re-render it, so the file is the only honest
    answer, and its disagreement with the fresh preview is the signal to press
    Apply. Re-rendering here would hide exactly that.

    A client cell has no start.sh on the controller — the controller BUILDS the
    line and hands it to the scout at start (fleet_clients sends
    effective_command(config, with_bootstrap=True), one builder for both hosts so
    the two cannot drift). Rendering it here is therefore not a guess: it is the
    same string the client is given.

    Empty means we genuinely do not know — a controller slot that has never been
    applied. It must never be confused with "this cell has no command": the board
    said "not saved yet" about cells that had been serving for hours, first by
    reading COMMAND (which only a custom cell fills) and later by asking for a
    start.sh that a client host never has.
    """
    if on_controller:
        # `or {}`, not a two-argument default: the second only fires when the key
        # is ABSENT, and a slot carrying "artifact": null would then raise out of
        # topology_server() — which nothing wraps, so the whole board renders
        # blank instead of one field being empty. admin.json is hand-edited during
        # incidents, which is exactly when that must not happen. Same rule as
        # TopologyStore._section, and as the sibling read 450 lines below.
        return _start_script_command(((slot or {}).get("artifact") or {}).get("startScript"))
    try:
        return effective_command(config or {}, with_bootstrap=True)
    except Exception:  # noqa: BLE001
        # A misconfigured cell cannot render a command; that is a fact about the
        # config, not a reason to fail the whole board.
        return ""


def _start_script_command(path):
    """The exec line inside a generated start.sh — what the cell WILL run.

    start.sh is a snapshot taken when the operator pressed Apply; starting a
    cell does not re-render it. So this is the only honest answer to "what is
    this cell saved with", and when it disagrees with the freshly-built preview
    the editor shows both, which is the signal to press Apply.
    """
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("exec "):
                    return line[5:].strip()
    except OSError:
        return ""
    return ""


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


# A running cell's model card, by port: fetched once a minute at most.
_MODEL_CARD_CACHE = {}
MODEL_CARD_TTL_SECONDS = 60


def _model_disk_newer(model_path, cell_status):
    """The model file on disk is newer than the moment the cell was launched.

    Two measured times are compared: the file's mtime and the unit's
    ExecMainStartTimestamp. No "probably": if the file was swapped after
    launch, the process is still running the old weights — it holds the
    INODE, not the name.
    """
    started = systemd_ts_epoch((cell_status or {}).get("ExecMainStartTimestamp"))
    if not started:
        return False
    try:
        from caravan.admin.config_builder import models_dir_from_config, parse_config
        path = pathlib.Path(str(model_path or ""))
        if not path.is_absolute():
            path = pathlib.Path(models_dir_from_config(parse_config())) / path
        return int(path.stat().st_mtime) > int(started)
    except OSError:
        return False


#: Files a llama.cpp cell takes from the models directory at launch, and each
#: one's role on the card. All three come from Hugging Face and all three get
#: re-issued: mmproj and the draft alongside the model, under the same
#: commit. Watching freshness only on MODEL_FILE means asking about one file
#: out of three and printing the answer as if it were about the whole launch.
LAUNCH_FILE_FIELDS = (("MODEL_FILE", "model"),
                      ("MMPROJ_FILE", "mmproj"),
                      ("SPEC_DRAFT_MODEL_FILE", "draft"))


def _launch_files(config, model_path):
    """[(role, path)] for every file involved in the launch. Empty ones skipped."""
    out = []
    seen = set()
    config = config or {}
    for field, role in LAUNCH_FILE_FIELDS:
        ref = str((config.get(field) if field != "MODEL_FILE" else
                   (config.get(field) or model_path)) or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        out.append((role, ref))
    return out


def _launch_fresh(config, model_path):
    """Freshness of EVERY launch file: [{"role", "file", "state"}].

    Only what's diverged or unchecked is in the list — "matches" is never
    drawn on the card at all: a ✓ over an unchecked file was the original
    defect.
    """
    rows = []
    for role, ref in _launch_files(config, model_path):
        state = _model_fresh_state(ref)
        if state in ("size", "date", "unknown"):
            rows.append({"role": role, "file": ref.rsplit("/", 1)[-1], "state": state})
    return rows


def _launch_disk_newer(config, model_path, cell_status):
    """Which launch files on disk are newer than the cell's start time: [role…].

    A cell holds ALL three files through mmap, so a swap of any one of them
    only reaches it on restart — and the mark is needed for any of them, not
    just the weights.
    """
    return [role for role, ref in _launch_files(config, model_path)
            if _model_disk_newer(ref, cell_status)]


def _launch_in_library(cell_config, model_path, config, locations):
    """Which launch files only a library holds: {"stores": [{id, name}…],
    "roles": [role…]} — or None when all of them are on this disk, or nowhere
    (a file that is nowhere is the start's own error, and the start says it).

    The files are looked for where the cell's start joins them: its own models
    directory, or the controller's. For a controller cell only: the libraries
    are mounted here, and a client cell reads its own disk.
    """
    models_dir = models_dir_from_config({"LLAMA_MODELS_DIR": (cell_config or {}).get("LLAMA_MODELS_DIR")
                                         or (config or {}).get("LLAMA_MODELS_DIR")})
    roles, stores = [], []
    for role, ref in _launch_files(cell_config, model_path):
        hit = locations.locate(ref, models_dir)
        if hit is None or not hit.in_library:
            continue
        roles.append(role)
        store = {"id": hit.store["id"], "name": hit.store["name"]}
        if store not in stores:
            stores.append(store)
    return {"stores": stores, "roles": roles} if roles else None


def _load_file_size(path, locations):
    """(bytes, library name or None) of a file a starting cell reads — or None
    when that is not known. A library's file is measured by the library's last
    look and never stat()ed here, usable or not: a NAS that stops answering
    would hold the board. A file on this disk is stat()ed, all its parts."""
    hit = locations.library_file(path)
    if hit is None:
        size = _slot_model_size_bytes(path, "")
        return (size, None) if size else None
    store, size = hit
    return (size, store["name"]) if store and size else None


def _cell_load(port, phase, locations):
    """How far a controller cell has read its model files — or None. Only a
    starting or warming cell is asked about; any other is forgotten, so a cell
    that loaded once keeps no old reading. A measurement that fails leaves the
    card its old line, never a broken board."""
    if phase not in ("starting", "warming"):
        LOAD_WATCH.forget(port)
        return None
    try:
        return LOAD_WATCH.look(port, cell_unit_pids(port), lambda path: _load_file_size(path, locations))
    except Exception:
        return None


def _parked_model_size(model_path, config, locations):
    """Weights-on-disk for a parked cell's ≈VRAM badge: here — or, for weights
    a move put in a library, the library's own measure, so the badge does not
    vanish with the move."""
    return (_slot_model_size_bytes(model_path, str(models_dir_from_config(config)))
            or locations.library_size(model_path))


def _model_fresh_state(model_path):
    """The model file's state from the watcher's latest report — or "".

    The key is the PATH relative to the models directory, exactly as in the
    report. It used to be the name, on the claimed assumption that this was
    safe: "same-named files sit in different branches". A 2026-09-07
    measurement showed the opposite — one name sits in ONE repository twice,
    in two quants, and by name a cell's card got the verdict of the copy it
    hadn't loaded.

    An empty string means "not checked", and the card must tell that apart
    from "matches": a ✓ over an unchecked file is that exact defect. A path
    absent from the report also means "not checked": a stranger's answer here
    is worse than silence.
    """
    ref = str(model_path or "").strip()
    if not ref:
        return ""
    try:
        from caravan.admin.model_watch import freshness_report
        repos = freshness_report().get("repos") or {}
    except Exception:
        return ""
    if os.path.isabs(ref):
        # A cell config's path can be absolute too. The report stores it
        # relative to the models directory — bring both to the same shape.
        try:
            from caravan.admin.config_builder import models_dir_from_config, parse_config
            ref = str(pathlib.Path(ref).relative_to(models_dir_from_config(parse_config())))
        except (ValueError, OSError):
            return ""
    for repo in repos.values():
        row = (repo.get("files") or {}).get(ref)
        if row:
            return str(row.get("state") or "")
    return ""


def _cell_model_card_windows(port, now=None):
    """(served, trained) as a running cell's own model card states them, cached a minute.

    llama.cpp puts both on /v1/models (meta.n_ctx and the trained number);
    vLLM states max_model_len and no trained number. The card of a running
    instance does not change, so one small local GET per cell per minute is
    the whole cost. A cell that does not answer yields (None, None) and is
    asked again a minute later: absence is not a size.
    """
    now = time.time() if now is None else now
    key = int(port or 0)
    hit = _MODEL_CARD_CACHE.get(key)
    if hit and now - hit[0] < MODEL_CARD_TTL_SECONDS:
        return hit[1]
    try:
        card = fetch_json(f"http://127.0.0.1:{key}/v1/models", timeout=2)
        entry = next((e for e in ((card or {}).get("data") or []) if isinstance(e, dict)), None)
        found = (served_window(entry), trained_window(entry))
    except Exception:
        found = (None, None)
    _MODEL_CARD_CACHE[key] = (now, found)
    return found


def _gguf_trained_window(model_path, config):
    """The trained window from a GGUF header on THIS host, or None.

    A parked cell has no model card, but its file carries the same number the
    card would state. A path that is not a file here — every client cell's —
    is no file: the number is not guessed from the name.
    """
    text = str(model_path or "").strip()
    if not text.lower().endswith(".gguf"):
        return None
    path = pathlib.Path(text).expanduser()
    if not path.is_absolute():
        path = pathlib.Path(models_dir_from_config(config)) / text
    try:
        if not path.is_file():
            return None
        from caravan.admin.models import extract_runtime_meta, read_gguf_metadata_cached
        return _positive_int((extract_runtime_meta(read_gguf_metadata_cached(path)) or {}).get("contextLength"))
    except Exception:
        return None


def topology_server(config=None):
    config = config or parse_config()
    service = service_status()
    runtime = runtime_api(config)
    runtime["status"] = runtime_phase(service, runtime)
    gpu_read = gpu_state()
    raw_gpus = gpu_read.get("gpus", [])
    # Why there are no cards in the list. "No cards" and "can't ask" look the
    # same on the board until the reason arrives: after a driver update,
    # before a reboot, nvidia-smi answers "Driver/library version mismatch",
    # and the node used to write "no GPU" about a card that's sitting right
    # there and working.
    gpu_error = "" if raw_gpus else str(gpu_read.get("error") or "")[:200]
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
    # The SERVED window is kept apart from that fallback: CTX_SIZE is the total
    # across slots, which no single request may use, and a route that
    # advertises it tells the client to send more than the cell accepts
    # (caravan/common/context_window.py). None while /props is silent.
    try:
        ctrl_ctx_served = int(ctrl_gen.get("n_ctx") or (ctrl_props or {}).get("n_ctx") or 0) or None
    except (TypeError, ValueError):
        ctrl_ctx_served = None
    try:
        ctrl_ctx_max = int(ctrl_ctx_served or config.get("CTX_SIZE") or 0)
    except (TypeError, ValueError):
        ctrl_ctx_max = 0
    # What the weights were trained with, from the same model card — shown
    # beside the model's name, never advertised (caravan/common/context_window.py).
    ctrl_models = runtime.get("models") if isinstance(runtime, dict) else {}
    ctrl_ctx_trained = trained_window(next((e for e in ((ctrl_models or {}).get("data") or [])
                                            if isinstance(e, dict)), None))
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
            "ctxServed": ctrl_ctx_served,
            "ctxTrained": ctrl_ctx_trained,
            "ctxUsed": ctrl_ctx_used,
            # Authoritative input modalities from the controller's own /props.
            "modalities": _normalize_modalities((ctrl_props or {}).get("modalities")),
        })

    # Launch-time context window per remote slot (CTX_SIZE captured when the
    # server was started) — used as the "ctxMax" fallback when the route-agent
    # doesn't report n_ctx itself.
    def _slot_ctx_max(host_id, port):
        slot = topo.slot(host_id, port)
        cfg = slot.get("config") or {}
        if not uses_token_context(cfg):
            return None
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
    # A machine's cells are what its scout reports: its host record, not a client.
    for client in _tstore.get("hosts", {}).values():
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
                      else "broken" if _cmd_phase == "broken"
                      else "down" if _cmd_phase == "down" else None)
        else:
            health = remote_llama_health(client_ip, remote_port) if running else None
        warming = running and health == "loading"
        effective_phase = "warming" if warming else ("running" if running else phase)
        # A command cell that reports a concrete download/load phase shows it (so
        # "downloading" surfaces the % bar) instead of the generic "warming".
        if slot_is_command and _cmd_phase in ("downloading", "loading"):
            effective_phase = _cmd_phase
        # A health path answering with an error is a live process around a dead
        # engine — running as far as the OS cares, broken for every caller.
        if running and slot_is_command and _cmd_phase == "broken":
            effective_phase = "broken"
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
            # What the cell says about itself on its health path. Beats the
            # config for anything the config cannot describe — see telemetry.
            "cellMeta": _cell_meta(_ch, _r_cfg, slot_is_command),
            "modelPath": model_path,
            "mmproj": str(ln.get("mmprojPath") or ""),
            "specDraft": str(ln.get("specPath") or ""),
            "specType": str(ln.get("specType") or ""),
            "status": ({"phase": "broken", "error": str((_ch or {}).get("error") or "")}
                       if effective_phase == "broken" else
                       {"phase": effective_phase if running else (phase or "starting")}),
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
            # As the cell's host agent reported it, never the configured
            # CTX_SIZE: the route's advertised window is built from this.
            "ctxServed": _positive_int(ln.get("ctxMax")),
            # A scout that reports the trained number wins; a file on this host
            # (rare for a client cell) is the fallback; nothing is guessed.
            "ctxTrained": _positive_int(ln.get("ctxTrained")) or _gguf_trained_window(model_path, config),
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
            # A RUNNING cell carries its saved line too. It did not, and the cell
            # modal — which shows the command for every runner but llama — told
            # the operator "not saved yet" about a cell that was serving traffic.
            "savedCommand": (_saved_command(_r_slot, _r_cfg, False)
                             if slot_is_command else ""),
            "bootEnabled": False,
        })

    # Persistent server slots not currently live → render as stopped servers so
    # the proxy cable stays attached across stop / model change.
    store = _tstore
    live_keys = {
        (s.get("clientId") if s.get("isRemote") else CONTROLLER_HOST_ID, s.get("port"))
        for s in llama_servers
    }
    hosts_by_id = store.get("hosts", {})
    # What the libraries hold, as last measured — once for all the cards, and
    # without waiting for a NAS that may not answer.
    model_locations = current_locations()
    for slot in store.get("serverSlots", {}).values():
        host_id = str(slot.get("hostId") or "")
        port = slot.get("port")
        if (host_id, port) in live_keys:
            continue
        is_controller_slot = is_controller_host(host_id)
        client = {} if is_controller_slot else (hosts_by_id.get(host_id) or {})
        client_ip = str(client.get("ip") or "").strip()
        gpu_name = ""
        if client.get("gpus"):
            gpu_name = str((client["gpus"][0] or {}).get("name") or "")
        slot_cfg = slot.get("config") or {}
        # Ask the runner where its model lives. The stored `model` is whatever
        # the save form sent — for a non-llama cell that is the model picker's
        # leftover MODEL_FILE, i.e. a model the cell is not running.
        model_path = cell_model_ref(slot_cfg) or str(slot.get("model") or "")
        slot_is_command = uses_command_path(slot_cfg)
        # A configured command cell has no MODEL_FILE but still counts as
        # "configured" (stopped), not an empty "reserved" slot.
        # Configured vs empty: a command cell counts as configured when it has
        # a command to run. The test used to be a hand-written list of runner
        # ids, which went stale the moment a runner was added — seamless and
        # translate cells, fully configured, rendered as empty "reserved" slots.
        slot_phase = "stopped" if (model_path or (
            slot_is_command and effective_command(slot_cfg).strip())) else "reserved"
        service_name = SERVICE_NAME if is_controller_slot else ""
        cell_status = {}
        cell_crash = None
        cell_pid = None
        cell_boot = ""
        cell_metrics = {}
        slot_vllm_stats = None
        _cdl = _ctot = 0
        _ch = None          # only a running command cell gets one; read below
        if is_controller_slot:
            cell_status = cell_service_status(port)
            service_name = cell_status.get("service") or cell_service_name(port)
            # Whether it has crashed since it was last started by hand.
            # systemd brings the cell back up, and a minute later it's
            # "running" again — without this mark, an evening with three
            # crashes looked like smooth operation on the board (2026-09-06).
            cell_crash = cell_crash_note(port, cell_status.get("NRestarts"))
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
                                  else _cph if _cph in ("downloading", "loading", "broken")
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
        # A broken cell's diagnosis comes from its own health body, not the
        # journal — the unit is active and systemd has nothing to complain about.
        if slot_phase == "broken":
            cell_error = str((_ch or {}).get("error") or "health error")
        # Authoritative modalities for a live cell (controller on 127.0.0.1,
        # remote on its IP). Stopped/reserved cells have no running server.
        progress_note = ""
        load_progress = None
        if is_controller_slot and slot_phase in ("starting", "warming"):
            try:
                progress_note = cell_progress_note(port)
            except Exception:
                progress_note = ""
        if is_controller_slot:
            load_progress = _cell_load(port, slot_phase, model_locations)
        slot_mods = None
        if slot_phase == "running" and not slot_is_command:
            probe_ip = "127.0.0.1" if is_controller_slot else client_ip
            if probe_ip:
                slot_mods = remote_llama_modalities(probe_ip, port)
        controller_name = os.environ.get("LLAMA_TOPOLOGY_SERVER_NAME", CONTROLLER_HOST_ID)
        controller_ip = TOPOLOGY_SERVER_IP
        _card_served, _card_trained = (
            _cell_model_card_windows(port)
            if is_controller_slot and slot_phase == "running" and not slot_is_command
            else (None, None))
        llama_servers.append({
            "id": f"slot:{host_id}:{port}",
            "name": str((controller_name if is_controller_slot else client.get("name")) or host_id),
            "port": port,
            "host": (controller_ip if is_controller_slot else client_ip),
            "model": display_model_name(model_path),
            "cellLabel": cell_artifact_label(slot.get("config") or {}),
            "cellMeta": _cell_meta(_ch, slot.get("config") or {}, slot_is_command),
            "modelPath": model_path,
            # What the model watcher last said about THIS file. Empty means
            # not checked: the card then stays silent, instead of showing a ✓.
            # ONLY for controller-slot cells: the report is built from ITS
            # models directory, while a client cell's weights sit on its own
            # host. The first cut compared by filename alone — and hung a
            # chip on a client cell, reporting on a file it had never seen
            # (found by a live check).
            "modelFresh": _model_fresh_state(model_path) if is_controller_slot else "",
            # About EVERY launch file, not just the weights: mmproj and the
            # draft also come from HF and also get re-issued. The first cut
            # asked about one file out of three, yet answered as if for the
            # whole launch.
            "launchFresh": (_launch_fresh(slot.get("config") or {}, model_path)
                            if is_controller_slot else []),
            # The file on disk is newer than what the cell loaded. A fact, not
            # a guess: the file's mtime against the unit's start time. Swapping
            # the file doesn't touch a running cell (it holds the inode
            # through mmap), and without this mark "already updated" would
            # look like "already running the update".
            "modelDiskNewer": (_model_disk_newer(model_path, cell_status)
                               if is_controller_slot and slot_phase == "running" else False),
            "launchDiskNewer": (_launch_disk_newer(slot.get("config") or {}, model_path, cell_status)
                                if is_controller_slot and slot_phase == "running" else []),
            # Which launch files only a library holds: they were moved off this
            # disk, and the cell starts from there. Controller cells only — that
            # is where the libraries are mounted.
            "modelStore": (_launch_in_library(slot_cfg, model_path, config, model_locations)
                           if is_controller_slot else None),
            "mmproj": str(((slot.get("config") or {}).get("MMPROJ_FILE")) or ""),
            "specDraft": str(((slot.get("config") or {}).get("SPEC_DRAFT_MODEL_FILE")) or ""),
            "specType": str(((slot.get("config") or {}).get("SPEC_TYPE")) or ""),
            "status": ({"phase": slot_phase,
                        **({"progressNote": progress_note} if progress_note else {}),
                        # When the crash happened — old failures shouldn't read
                        # as "it just died again" on the card.
                        **({"errorAt": systemd_ts_epoch(cell_status.get("ExecMainExitTimestamp"))}
                           if systemd_ts_epoch(cell_status.get("ExecMainExitTimestamp")) else {}),
                        ("error" if slot_phase in ("error", "broken") else "lastError"): cell_error}
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
            **({"loadProgress": load_progress} if load_progress else {}),
            "downloadedBytes": _cdl,
            "totalBytes": _ctot,
            # A running llama or vLLM cell on this host states its windows on
            # its own model card; the served one is the truth over CTX_SIZE
            # (the configured total across slots). A parked one keeps only the
            # trained number, in its GGUF header.
            "ctxMax": _card_served or _slot_ctx_max(host_id, port),
            "ctxServed": _card_served,
            "ctxTrained": _card_trained or _gguf_trained_window(model_path, config),
            # ≈VRAM hint for a parked cell: weights-on-disk size (context/KV
            # overhead not included). Live phases get the real figure from GPU
            # process memory instead.
            "modelSizeBytes": (_parked_model_size(model_path, config, model_locations)
                               if slot_phase in ("stopped", "reserved", "error") else 0),
            "promptTps": cell_metrics.get("promptTokensPerSecond") if cell_metrics.get("ok") else None,
            "genTps": cell_metrics.get("predictedTokensPerSecond") if cell_metrics.get("ok") else None,
            "vllmStats": slot_vllm_stats,
            "artifact": slot.get("artifact") or {},
            "schedule": slot.get("schedule") or None,
            "slotConfig": slot.get("config") or {},
            "commandHistory": slot.get("commandHistory") or [],
            # The launch line this cell is SAVED with — read from the start.sh
            # that would actually run, not re-rendered from the config. The two
            # differ whenever the controller's command builder has changed since
            # the operator last pressed Apply, and that difference is exactly
            # what the operator needs to see: re-rendering here would hide it and
            # claim the cell already runs the new line. (Only a custom cell keeps
            # its command in COMMAND, which is why reading that key told everyone
            # else "not saved yet" about cells running for hours.)
            "savedCommand": (_saved_command(slot, slot_cfg, is_controller_slot)
                             if slot_is_command else ""),
            "bootEnabled": cell_boot == "enabled",
            "pid": cell_pid,
            # All unit PIDs — vLLM holds the GPU in a forked worker, and the
            # GPU binder must see it or the cell lands in the CPU section.
            "pids": sorted(cell_unit_pids(port)) if (is_controller_slot and slot_phase == "running") else [],
            "lastError": cell_status.get("error") if slot_phase == "error" else "",
            # Crashes since the last manual start: {count, at, kind, reason}.
            # Empty means it hasn't crashed; None for client cells, which the
            # controller's systemd knows nothing about (the scout doesn't
            # report this yet).
            "crash": cell_crash,
            "firewall": firewall_port_access(port) if is_controller_slot else None,
            "reachable": None,
        })

    return {
        "id": CONTROLLER_HOST_ID,
        "name": os.environ.get("LLAMA_TOPOLOGY_SERVER_NAME", CONTROLLER_HOST_ID),
        "ip": TOPOLOGY_SERVER_IP,
        "service": service,
        "runtime": runtime,
        "gpus": gpus,
        "gpuError": gpu_error,
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
    # Split each card's compute memory into fleet vs everything else. The board
    # already draws total `used`, but that lumps a training run or any outside
    # process in with the cells — and when no cell sits on the card it labels it
    # "idle" while an outside job is really holding VRAM. pid_mem carries every
    # compute app; the ones whose pid belongs to a cell are the fleet's, the
    # rest are not. (Graphics like Xorg aren't in --query-compute-apps, so a few
    # MiB of overhead just falls into the free remainder — close enough.)
    fleet_pids = {p for s in servers for p in [s.get("pid"), *(s.get("pids") or [])] if p}
    for g in gpus:
        idx = g.get("index")
        g["serverPorts"] = sorted(gpu_ports.get(idx, set()),
                                  key=lambda x: (x is None, x))
        fleet_mib = non_fleet_mib = 0
        for (pid, i), mib in pid_mem.items():
            if i != idx:
                continue
            if pid in fleet_pids:
                fleet_mib += mib
            else:
                non_fleet_mib += mib
        g["fleetUsedMiB"] = round(fleet_mib)
        g["nonFleetUsedMiB"] = round(non_fleet_mib)
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


def topology_nodes(config, server_obj, hosts):
    """Host-centric view: one node per machine, each with its GPUs + the
    llama-servers running/declared on it + CPU/RAM. Server↔GPU is bound via
    per-process GPU memory (compute-apps)."""
    nodes = []
    # Poweroff schedules, keyed by hostId — attached to each node so the board
    # can show and edit the machine's shutdown time next to its power button.
    _power_scheds = topo.power_schedules()

    # ── controller node ─────────────────────────────────────────────
    ctrl_gpus = [dict(g) for g in (server_obj.get("gpus") or [])]
    ctrl_servers = [dict(s) for s in (server_obj.get("llamaServers") or [])
                    if not s.get("isRemote")]
    ctrl_servers.sort(key=_server_port_key)
    _ctrl_apps = gpu_compute_apps()
    _bind_servers_to_gpus(ctrl_gpus, _ctrl_apps, ctrl_servers)
    _record_gpu_history(server_obj.get("id") or CONTROLLER_HOST_ID, ctrl_gpus)
    for s in ctrl_servers:
        s["tpsHistory"] = _record_tps_history(
            f"{server_obj.get('id') or CONTROLLER_HOST_ID}:{s.get('port')}", s.get("promptTps"), s.get("genTps"))
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
    ctrl_cpu["history"] = _record_cpu_history(server_obj.get("id") or CONTROLLER_HOST_ID, ctrl_cpu)
    # Cells running OUTSIDE the registry: a live lama-cell@ unit with no slot
    # record. The board renders the store, so without this list such a cell is
    # invisible by construction — the exact failure that once hid a 27 GB model
    # while two other cells starved for the VRAM it held.
    orphan_cells = []
    if not IS_CONTAINER:
        try:
            known_ports = {int(s.get("port") or 0) for s in ctrl_servers}
            for _op in sorted(active_cell_unit_ports() - known_ports):
                _ost = cell_service_status(_op)
                try:
                    _opid = int(_ost.get("MainPID") or 0)
                except (TypeError, ValueError):
                    _opid = 0
                _opids = cell_unit_pids(_op)
                _ovram = sum(int(a.get("usedMiB") or 0) for a in (_ctrl_apps or [])
                             if a.get("pid") in _opids)
                _olabel = ""
                try:
                    _oargs = [a for a in pathlib.Path(f"/proc/{_opid}/cmdline")
                              .read_bytes().decode(errors="replace").split("\0") if a]
                    if "--model" in _oargs:
                        _olabel = _oargs[_oargs.index("--model") + 1].split("/")[-1]
                    elif _oargs:
                        _olabel = " ".join(_oargs[-2:])[:48]
                except Exception:
                    pass
                orphan_cells.append({"port": _op, "pid": _opid or None,
                                     "model": _olabel, "vramMiB": _ovram})
        except Exception:
            orphan_cells = []
    nodes.append({
        "id": server_obj.get("id") or CONTROLLER_HOST_ID,
        "name": server_obj.get("name") or CONTROLLER_HOST_ID,
        "ip": server_obj.get("ip"),
        "role": "controller",
        # In container mode the controller cannot host cells (no systemd) —
        # the board hides the reserve/start controls and points at scouts.
        "containerized": IS_CONTAINER,
        "online": True,
        # Why the card list is empty — the node carries this along with the
        # list itself: "no cards" and "can't ask a card" render identically
        # until the reason reaches the UI.
        "gpuError": server_obj.get("gpuError") or "",
        "platform": "linux",
        "cpu": ctrl_cpu,
        "gpus": ctrl_gpus,
        "servers": ctrl_servers,
        "orphanCells": orphan_cells,
        "powerSchedule": _power_scheds.get(server_obj.get("id") or CONTROLLER_HOST_ID) or {},
    })

    # ── host nodes ───────────────────────────────────────────────────────────
    # One per machine whose scout reported. Servers (running/startup/
    # stopped-slot) are already assembled in server_obj.llamaServers, keyed by
    # the machine's id — group them by it.
    remote_by_host: dict = {}
    for s in (server_obj.get("llamaServers") or []):
        if s.get("isRemote") and s.get("clientId"):
            remote_by_host.setdefault(str(s["clientId"]), []).append(dict(s))

    for host in hosts:
        cid = str(host.get("id") or "")
        hgpus = [dict(g) for g in (host.get("gpus") or []) if g.get("name")]
        for g in hgpus:
            try:
                g["index"] = int(g.get("index")) if g.get("index") is not None else None
            except (TypeError, ValueError):
                g["index"] = None
        servers = remote_by_host.get(cid, [])
        servers.sort(key=_server_port_key)
        _bind_servers_to_gpus(hgpus, host.get("computeApps"), servers)
        _record_gpu_history(cid, hgpus)
        for s in servers:
            s["tpsHistory"] = _record_tps_history(
                f"{cid}:{s.get('port')}", s.get("promptTps"), s.get("genTps"))
        host_cpu = dict(host.get("cpu") or {})
        host_cpu["history"] = _record_cpu_history(cid, host_cpu)
        nodes.append({
            "id": cid,
            "name": host.get("name") or cid,
            "ip": host.get("ip"),
            "role": "host",
            "online": host.get("state") == "online",
            # How long the scout has been silent — the node says it when the
            # scout stops answering; None only for a record with no report.
            "ageSeconds": host.get("ageSeconds"),
            "platform": host.get("platform") or "",
            "cpu": host_cpu,
            "gpus": hgpus,
            "servers": servers,
            "llamaBinaryVersion": host.get("llamaBinaryVersion") or "",
            "llamaBinaryMtime": host.get("llamaBinaryMtime") or "",
            "llamaUpdate": host.get("llamaUpdate") or {},
            "powerSchedule": _power_scheds.get(cid) or {},
        })

    return nodes

def _positive_int(value):
    """A size, or None: zero, rubbish and booleans are absences, not sizes."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _served_windows_by_address(server_obj):
    """(host, port) → the window each running cell serves, keyed as a router output names it.

    Only the SERVED number, as the cell itself reported it: the configured
    CTX_SIZE that the board's `ctxMax` falls back to is the total across slots,
    which no single request may use (caravan/common/context_window.py). A
    controller cell answers under every name an output may use for this host.
    """
    found = {}
    # `llamaServers` is topology_server()'s key — `servers` is a per-node list
    # in topology_nodes(). Read off the wrong one, this map was silently empty
    # and every route to a cell showed no model window at all.
    for row in (server_obj or {}).get("llamaServers") or []:
        if not isinstance(row, dict):
            continue
        port = _positive_int(row.get("port"))
        window = _positive_int(row.get("ctxServed"))
        if port is None or window is None:
            continue
        hosts = {str(row.get("clientIp") or "").strip()} - {""}
        if row.get("isController"):
            hosts |= {"127.0.0.1", "localhost", str(TOPOLOGY_SERVER_IP or "")} - {""}
        # A client cell with no address answers under no name: keyed as the
        # controller's, it lent the controller's port a window it does not have.
        for host in hosts:
            found[(host, port)] = window
    return found


def _block_window_resolver(cloud_blocks):
    """block id → (window, block): the figure a cloud block stands for, by the block's own rule.

    The catalogue is consulted only for a block whose switch is on — the same
    condition under which the proxy reads it (caravan/proxy/cloud_auth.py), so
    the board and the port derive the block's number from the same sources.
    """
    blocks = {str(b.get("id")): b for b in (cloud_blocks or []) if isinstance(b, dict)}
    catalogues = {}

    def reported(block):
        account_id = str(block.get("accountId") or "")
        if account_id not in catalogues:
            try:
                from caravan.admin.model_catalog import cached_models_entry
                models = (cached_models_entry(account_id) or {}).get("models") or []
            except Exception:
                models = []
            catalogues[account_id] = {m.get("id"): m.get("contextLength")
                                      for m in models if isinstance(m, dict)}
        return catalogues[account_id].get(block.get("model"))

    def resolve(block_id):
        block = blocks.get(str(block_id or ""))
        if block is None:
            return None, None
        prefer = bool(block.get("contextAuto"))
        return block_window(block.get("contextLength"), reported(block) if prefer else None, prefer), block

    return resolve


def _route_window_facts(route, proxy_config, served, resolve_block):
    """What the output a plain request reaches serves: (window, source).

    The same resolution GET /v1/models goes through — apply_router with
    PLAIN_REQUEST_CTX — so the board names the output the proxy answers from.
    `source` says where the number comes from, or why there is none: a dash
    with no reason would be absence rendered as normality (docs/why.md).
    """
    try:
        resolved = apply_router(dict(route), proxy_config, ctx=dict(PLAIN_REQUEST_CTX))
    except Exception as exc:
        return None, {"kind": "error", "reason": str(exc)[:120]}
    upstream_type = str(resolved.get("upstreamType") or "llama")
    if resolved.get("unrouted") and upstream_type != "cloud":
        return None, {"kind": "unrouted", "reason": str(resolved.get("unrouted"))}
    if upstream_type == "cloud":
        block_id = str(resolved.get("providerId") or "")
        if not block_id:
            # An account passthrough pins no model, so no single window exists.
            return None, {"kind": "account", "account": str(resolved.get("cloudAccountId") or "")}
        window, block = resolve_block(block_id)
        if block is None:
            return None, {"kind": "unrouted", "reason": "block missing"}
        return window, {"kind": "block", "name": str(block.get("name") or block.get("model") or ""),
                        "model": str(block.get("model") or "")}
    host = str(resolved.get("upstreamHost") or "127.0.0.1")
    port = _positive_int(resolved.get("upstreamPort")) or 0
    return served.get((host, port)), {"kind": "cell", "host": host, "port": port}


def _proxy_output_health():
    """The proxy's verdicts as its state file last wrote them, or nothing."""
    try:
        payload = json.loads(AGENT_PROXY_STATE_FILE.read_text(encoding="utf-8"))
        rows = payload.get("outputHealth") if isinstance(payload, dict) else None
        return rows if isinstance(rows, dict) else {}
    except Exception:
        return {}


def annotate_route_windows(proxies, proxy_config, server_obj, cloud_blocks):
    """Three windows on every proxy row: the model's, the operator's, the advertised one.

    `modelWindow` is what the output a plain request reaches serves, with
    `modelWindowSource` naming it; `effectiveWindow` is
    effective_window(limit, modelWindow, switch) — the figure the port publishes
    in /v1/models, which the proxy computes from the same inputs with the same
    rule. The limit and the switch are already on the row (`contextLength`,
    `contextAuto`), copied there from the assignment by reconcile_proxy_metadata.
    """
    served = _served_windows_by_address(server_obj)
    resolve_block = _block_window_resolver(cloud_blocks)
    # The proxy's verdicts first: a backup node whose main is known dead sends
    # the next request down its backup exit, and the window the port really
    # advertises is that exit's — the board must resolve the same way.
    try:
        output_health.load_snapshot(_proxy_output_health())
    except Exception:
        pass
    for proxy in proxies:
        if not isinstance(proxy, dict):
            continue
        window, source = _route_window_facts(proxy, proxy_config, served, resolve_block)
        limit, prefer = route_window_inputs(proxy)
        proxy["modelWindow"] = window
        proxy["modelWindowSource"] = source
        # A port that reaches no output answers /v1/models with 503, not with a
        # list: it advertises nothing, whatever limit is written on it.
        proxy["effectiveWindow"] = (None if source.get("kind") in ("unrouted", "error")
                                    else effective_window(limit, window, prefer))
    return proxies


def _board_proxy(route, *, holders, last_seen, routers_by_id):
    """One proxy route as the board is handed it: the route's own fields plus
    its id and address, when it last served, where its router actually sends
    it, and who holds it.

    Its own function so that what a proxy carries can be checked by value —
    topology_state around it reaches twenty collaborators.
    """
    served = last_seen.get(int(route.get("port") or 0) or -1)
    proxy = {
        **route,
        "id": f"skynet:proxy:{route.get('port')}",
        "endpoint": f"http://{TOPOLOGY_SERVER_IP}:{route.get('port')}/v1",
        "upstreamId": f"skynet:llama-server:{route.get('upstreamPort')}",
        "lastRequestAt": int(served) if served else 0,
    }
    # Who holds the port — the same reading the bind check refuses by, so the
    # port picker can offer only what a bind will accept.
    proxy["holders"] = [{"hostId": h, "agentId": a, "role": r}
                        for h, a, r in holders.get(proxy["id"], [])]
    # Resolve the actual upstream the proxy routes to via its router graph outputs.
    # route.upstreamPort is a legacy placeholder (:8080); the graph output is authoritative.
    router = routers_by_id.get(str(route.get("routerId") or ""))
    if router:
        outputs = router.get("outputs") or []
        default_id = str((router.get("rules") or {}).get("default") or "")
        out = next((o for o in outputs if str(o.get("id")) == default_id), None)
        if not out:
            out = next((o for o in outputs if str(o.get("upstreamType") or "llama") != "cloud"), None)
        if out and int(out.get("upstreamPort") or 0):
            proxy["resolvedUpstreamHost"] = str(out.get("upstreamHost") or "127.0.0.1")
            proxy["resolvedUpstreamPort"] = int(out.get("upstreamPort"))
    return proxy


def topology_state(refresh_hosts=True):
    if refresh_hosts:
        # A board read asks for fresher scout reports and never waits for them:
        # the pull runs in the background, and the next read sees what it
        # brought (caravan/admin/scout_poll.py).
        SCOUT_POLLER.kick()
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
    # Traffic is proof a route is used — the board promotes "unverified" to
    # "confirmed" on it, since most agents never report their own config.
    _last_seen = proxy_ports_last_seen()
    _holders = _port_holders()
    for route in proxy_config.get("routes", []):
        proxies.append(_board_proxy(route, holders=_holders, last_seen=_last_seen, routers_by_id=_routers_by_id))
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
    hosts = topology_hosts()
    # Cloud state + catalog annotation: unlisted marks on blocks, background
    # model-list refreshes, endpoint-health report. Annotation must never sink
    # the board — degrade to plain state on any failure.
    cloud_accounts = cloud_accounts_state()
    cloud_blocks = cloud_blocks_state()
    # The three context windows of every route (model / limit / advertised):
    # a board fact, never a reason for the board to sink.
    try:
        annotate_route_windows(proxies, proxy_config, server_obj, cloud_blocks)
    except Exception:
        pass
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
        # Host-centric model: one node per machine — the controller and every
        # host with a scout — with its GPUs + servers + CPU/RAM, server↔GPU
        # bound via compute-apps.
        "nodes": topology_nodes(config, server_obj, hosts),
        "proxies": proxies,
        # The fleet's port ranges, so the picker grid and the front-side port
        # preview draw the REAL window instead of a hardcoded copy of it — the
        # copies are what went stale when the controller moved off 8090.
        "cellPortRange": {"from": SERVER_CELL_BASE_PORT, "to": SERVER_CELL_UPPER_PORT,
                          "proxyBase": AGENT_PROXY_BASE_PORT},
        # Routers — the routing layer between proxies and servers.
        # inputs already derived from routes by normalize_routers.
        "routers": proxy_config.get("routers") or [],
        "proxyPolicy": policy,
        "effectiveSlots": total_slots or int(policy.get("maxSlots") or 1),
        # Two records under one id, never one merged row: a machine's report
        # and liveness are in `hosts`, the operator's clients in `clients`
        # (docs/scout-split.md). The merged rows the board read until it read
        # `hosts` are gone with that reading.
        "hosts": hosts,
        "clients": clients,
        "assignments": store.get("assignments", {}),
        # User notes on cell slots, keyed "hostId:port" — shown on the board
        # cards and edited in the cell detail modal.
        "cellNotes": {key: str(slot.get("note") or "")
                      for key, slot in (store.get("serverSlots") or {}).items()
                      if isinstance(slot, dict) and str(slot.get("note") or "").strip()},
        "clientAliases": store.get("clientAliases", {}),
        "layout": store.get("layout", {}),
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
    """The record's shape and its refusals live in caravan/domain/client_proxy.py.

    All that's left here is dict in / dict out: this path rebuilds the record
    from scratch, and a field the class doesn't name disappears on the next
    save. The field list used to live here, and had to be remembered — now
    it's one list, shared by every writer.
    """
    return AgentAssignment.from_raw(assignment).to_dict()

def _port_holders():
    """{proxyId: [(hostId, agentId, role), ...]} — who holds each proxy port,
    read from the stored assignments in their stored order.

    The one reading of ownership: the bind check refuses by it (_port_holder)
    and the board is handed it on every proxy (topology_state), so the port
    picker offers exactly the ports a bind will accept. Before, the picker
    listed every port and the server refused most of them — on 2026-09-23 all
    fifteen were held, and every row of the menu ended in a 409.
    """
    held = {}
    for host_id, entry in (topology_store().get("assignments") or {}).items():
        for row in (entry.get("assignments") or []):
            agent_id = str(row.get("agentId") or "")
            for route in (row.get("routes") or []):
                pid = str(route.get("proxyId") or "")
                if pid:
                    held.setdefault(pid, []).append((host_id, agent_id, str(route.get("role") or "primary")))
    return held


def _port_holder(port, exclude=()):
    """Who already holds this port: (hostId, agentId, role), or None.

    `exclude` is the claimant itself, as a (hostId, agentId) pair: an agent
    doesn't conflict with itself. Its own role, moving the port between its
    OWN roles, and re-saving the same setting don't count as a conflict —
    otherwise ordinary editing would fail. A different agent, whether on this
    client or a neighboring one, is a conflict: the port grid is shared
    across the whole fleet.
    """
    for holder in _port_holders().get(f"{PROXY_ID_PREFIX}{int(port)}", []):
        if tuple(exclude) == holder[:2]:
            continue
        return holder
    return None


def bind_agent_to_proxy(payload):
    """Point one agent at one proxy port, by hand, and keep it there.

    Everything needed for this already existed — the assignment store, the
    apply path, the port list — but no caller ever put them together, so the
    only way an agent got a port was for the provisioner to choose one. That
    made the arrangement unexplainable ("why is this agent on 23117?") and
    unchangeable.

    A port is required. Passing none used to mean "back to automatic" — the
    manual mark cleared and provisioning chose on the next heartbeat. With
    ports made by hand only (2026-09-24) there is nothing to go back to; a
    role is removed with remove_agent_route.
    """
    host_id = str(payload.get("hostId") or "").strip()
    agent_id = str(payload.get("agentId") or "").strip()
    if not host_id or not agent_id:
        raise AppError("hostId and agentId are required", 400)

    store = topology_store()
    # Only an agent the operator's record has. A bind for any other id wrote a
    # row nobody draws: its port read as held, by an agent no screen showed
    # and no ✕ could remove.
    client = (store.get("clients") or {}).get(host_id)
    if client is None:
        raise AppError(f"client not found: {host_id}", 404)
    if not any(str(a.get("id") or "") == agent_id for a in (client.get("agents") or [])):
        raise AppError(f"agent not found: {agent_id}", 404)
    row = dict(store.get("assignments", {}).get(host_id) or {})
    rows = [dict(a) for a in (row.get("assignments") or [])]
    entry = next((a for a in rows if a.get("agentId") == agent_id), None)
    if entry is None:
        entry = {"agentId": agent_id, "routes": []}
        rows.append(entry)

    # The role widens what's accepted, not narrows it: a caller that never
    # sends it gets the old behaviour.
    role = str(payload.get("role") or "primary").strip()
    if role not in ("primary", "fallback"):
        raise AppError(f'role must be "primary" or "fallback", got "{role}"', 400)

    port = payload.get("port")
    if port in (None, "", 0):
        raise AppError("port is required — a role is removed with its own action", 400)
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise AppError("port must be a number", 400)
    known = {int(r.get("port", 0)) for r in load_agent_proxy_config().get("routes", [])}
    if port not in known:
        # Binding to a port with no route would leave the agent pointing at
        # a closed socket while the panel showed a tidy assignment.
        raise AppError(f"no proxy route on port {port}", 400)
    # One port, one owner. The settings copy rides the route BY PORT, so
    # two agents on the same port can't both work: whichever wrote last
    # erases the other's settings, silently and without a trace. The
    # whole fleet is checked, not just one client: the port grid is shared.
    holder = _port_holder(port, exclude=(host_id, agent_id))
    if holder:
        raise AppError(f"port {port} is already bound to agent "
                       f"{holder[1]} ({holder[2]})", 409)
    # The fourth place that builds a route record — missed by grep during
    # the phase 1 audit because of a line wrap. Now it goes through the
    # class too: one field list for every writer, otherwise a new field
    # survives a save at three writers out of four.
    assignment = AgentAssignment.from_raw(entry)
    assignment.set_route(ProxyRoute.for_port(role, port, TOPOLOGY_SERVER_IP))
    entry.clear()
    entry.update(assignment.to_dict())

    return apply_topology_assignments({"hostId": host_id, "assignments": rows})


def set_agent_route_context(payload):
    """The context window FOR ONE consumer — one agent's role.

    The model's own number is shared by everyone routing to it; here the
    operator states how much is allowed for THIS client, and that wins. An
    empty value clears it back to the model's number — clearing and "set to
    zero" are different things, so zero is never saved.

    The setting lives on the saved route, and the scout's live report doesn't
    carry it and never will: the board's merge takes only the port and
    endpoint from the report.

    BOTH fields are set together: the form sends the number and the checkbox
    as one, so a missing field means "clear", not "leave alone". Same
    contract as the cloud block, for the same reason — otherwise there'd be
    no way to clear the field.
    """
    host_id = str(payload.get("hostId") or "").strip()
    agent_id = str(payload.get("agentId") or "").strip()
    role = str(payload.get("role") or "primary").strip()
    if not host_id or not agent_id:
        raise AppError("hostId and agentId are required", 400)
    if role not in ("primary", "fallback"):
        raise AppError(f'role must be "primary" or "fallback", got "{role}"', 400)

    store = topology_store()
    rows = [dict(a) for a in ((store.get("assignments", {}).get(host_id) or {}).get("assignments") or [])]
    raw = next((a for a in rows if a.get("agentId") == agent_id), None)
    if raw is None:
        raise AppError(f"no assignment for agent {agent_id} on {host_id}", 404)
    assignment = AgentAssignment.from_raw(raw)
    route = assignment.route(role)
    if route is None:
        raise AppError(f"agent {agent_id} has no {role} route", 404)
    route.context_length = ProxyRoute._positive_int(payload.get("contextLength"))
    route.context_auto = bool(payload.get("contextAuto")) or None
    raw.clear()
    raw.update(assignment.to_dict())
    return apply_topology_assignments({"hostId": host_id, "assignments": rows})


def remove_agent_route(payload):
    """Remove an agent's role: it stops using this port.

    "Unbind" used to mean only clearing a "manual" mark — the route stayed,
    the port still counted as taken, and there was no way at all to remove a
    fallback created by mistake. Now the role disappears from the record
    entirely.

    THE PORT ITSELF keeps listening. That's not an oversight: the port is a
    live listener that an outside agent may reach independently of our
    records, and killing it over a record edit would tear into someone
    else's traffic as a side effect. It belongs to nobody after this, and the
    kanban says so out loud.
    """
    host_id = str(payload.get("hostId") or "").strip()
    agent_id = str(payload.get("agentId") or "").strip()
    role = str(payload.get("role") or "").strip()
    if not host_id or not agent_id or not role:
        raise AppError("hostId, agentId and role are required", 400)
    store = topology_store()
    rows = [dict(a) for a in ((store.get("assignments", {}).get(host_id) or {}).get("assignments") or [])]
    raw = next((a for a in rows if a.get("agentId") == agent_id), None)
    if raw is None:
        raise AppError(f"no assignment for agent {agent_id} on {host_id}", 404)
    assignment = AgentAssignment.from_raw(raw)
    if assignment.route(role) is None:
        raise AppError(f"agent {agent_id} has no {role} route", 404)
    assignment.routes = [r for r in assignment.routes if r.role != role]
    raw.clear()
    raw.update(assignment.to_dict())
    return apply_topology_assignments({"hostId": host_id, "assignments": rows})


def set_agent_route_model(payload):
    """The name a port advertises its model under, for one agent role.

    A client asks `/v1/models` and looks up ITS OWN id there. Not finding it,
    it falls back to its built-in default, and a window honestly published
    under the upstream's name never reaches it at all. Here the operator
    states what name the port should call itself so the client recognizes it.

    Empty clears it: then whatever the upstream calls itself is published. A
    separate call, not bundled with the window: these are different
    decisions, and putting them in one form would mean editing one silently
    erases the other.

    NAME AND LOCK are set together — it's one decision about how the port is
    named, and an open lock must leave the name sitting there: closing it
    again must not require retyping the name, or there'd be nothing to close
    it back to. So both fields are sent together, and a missing one means
    "clear", same as the window.
    """
    host_id = str(payload.get("hostId") or "").strip()
    agent_id = str(payload.get("agentId") or "").strip()
    role = str(payload.get("role") or "primary").strip()
    if not host_id or not agent_id:
        raise AppError("hostId and agentId are required", 400)
    store = topology_store()
    rows = [dict(a) for a in ((store.get("assignments", {}).get(host_id) or {}).get("assignments") or [])]
    raw = next((a for a in rows if a.get("agentId") == agent_id), None)
    if raw is None:
        raise AppError(f"no assignment for agent {agent_id} on {host_id}", 404)
    assignment = AgentAssignment.from_raw(raw)
    route = assignment.route(role)
    if route is None:
        raise AppError(f"agent {agent_id} has no {role} route", 404)
    route.model_name = str(payload.get("modelName") or "").strip()[:120] or None
    route.model_name_auto = bool(payload.get("modelNameAuto")) or None
    raw.clear()
    raw.update(assignment.to_dict())
    return apply_topology_assignments({"hostId": host_id, "assignments": rows})


def apply_topology_assignments(payload):
    host_id = str(payload.get("hostId") or "").strip()
    assignments = payload.get("assignments")
    if not host_id:
        raise AppError("hostId is required", 400)
    if not isinstance(assignments, list):
        raise AppError("assignments must be a list", 400)
    normalized = [normalize_topology_assignment(row) for row in assignments]
    store = topology_store()
    # Stored, not pushed. The row used to be POSTed to the scout's
    # /api/routing/apply, which rewrote each agent's own config — over SSH for
    # the VMs — and restarted it. The scout knows nothing of agents any more
    # (2026-09-24): an agent is pointed at its port by hand, in its own
    # settings, and the bind's toast says so.
    row = {"hostId": host_id, "assignments": normalized}
    store["assignments"][host_id] = row
    save_admin_state()
    # The settings copy rides the route HERE, not at some later point. The
    # bridge used to be called only from heartbeat handling — and for a
    # client created by hand it never fired at all: it exists and is
    # configured, but isn't required to ever report in. For a live client the
    # setting used to arrive with a delay, on the next poll, and the whole
    # time the board showed one thing while the port published another.
    try:
        from caravan.admin.fleet_clients import reconcile_proxy_metadata
        reconcile_proxy_metadata()
    except Exception:
        pass
    return row
