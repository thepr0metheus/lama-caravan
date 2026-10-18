"""Topology assembly: the /api/topology tree (clients, servers, GPUs, proxies,
routers) built from heartbeats, probes, systemd and the proxy state files."""
import glob
import json
import os
import pathlib
import re
import time

from caravan.admin.board_layout import ClientOrder, ServerOrder
from caravan.admin.board_providers import ProviderDesk
from caravan.admin.controller_machine import ControllerMachine
from caravan.admin.proxy_stats import embeddings_last_called, proxy_ports_last_seen
from caravan.admin.cloud import cloud_accounts_state, cloud_provider_presets_public
from caravan.admin.pools import PoolDesk
from caravan.admin.config_builder import models_dir_from_config, parse_config
from caravan.admin.cell_assets import cell_source_state
from caravan.admin.runners import (cell_artifact_label, cell_model_ref,
                                   effective_command, effective_health_path,
                                   runner_id, uses_command_path,
                                   uses_token_context)
from caravan.admin.fleet_clients import SCOUT_POLLER, topology_clients, topology_hosts
from caravan.admin.launch_files import LaunchFiles
from caravan.admin.models import display_model_name
from caravan.admin.model_locator import current_locations
from caravan.admin.monitoring import gpu_state
from caravan.admin.paths import AGENT_PROXY_STATE_FILE, CONTROLLER_HOST_ID, TOPOLOGY_SERVER_IP, AGENT_PROXY_BASE_PORT, SERVER_CELL_BASE_PORT, SERVER_CELL_UPPER_PORT
from caravan.admin.model_schedules import ModelScheduleDesk
from caravan.admin.model_sets import SetDesk
from caravan.admin.proxy_entry import AsConsumer, ConsumerAddress, PortDoor
from caravan.admin.proxies_config import (
    ProxyRevisions,
    load_agent_proxy_config,
    read_agent_proxy_payload,
    sync_router_outputs,
    write_agent_proxy_payload,
)
from caravan.admin.router_dsl import normalize_agent_proxy_policy
from caravan.admin.server_cells import server_slot_key
from caravan.admin.state import save_admin_state, topology_store
from caravan.admin.state import topology as topo
from caravan.admin.cell_words import CellWords
from caravan.admin.telemetry import (
    _normalize_modalities,
    _record_cpu_history,
    _record_gpu_history,
    _record_tps_history,
    command_cell_health,
    probe_remote_port,
    remote_cell_about,
    remote_llama_health,
    remote_llama_modalities,
)
from caravan.common.errors import AppError
from caravan.admin.models import MODEL_LIST
from caravan.domain.driver_outlook import DriverOutlook
from caravan.domain.engine import GpuOwners
from caravan.domain.runner import for_config
from caravan.admin.engine_outputs import EngineOutputs
from caravan.admin.machine_models import MachineOutputs
from caravan.common.context_window import effective_window, route_window_inputs
from caravan.common.entry_models import EntryModels
from caravan.common.key_entry import KeyEntry
from caravan.domain.client_proxy import AgentAssignment, PROXY_ID_PREFIX, ProxyRoute
from caravan.proxy.graph import answer_port_question, port_question_reaches
from caravan.proxy.output_health import output_health
from caravan.common.model_kinds import ModelKind


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
        meta["sourceState"] = cell_source_state(runner_id(cfg), meta.get("source"), (cfg or {}).get("COMMAND"))
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


def _saved_command(slot, config):
    """The launch line this cell is saved with.

    A scout's cell has no start.sh on the controller — the controller BUILDS
    the line and hands it to the scout at start (fleet_clients sends
    effective_command(config), one builder), so rendering it here is not a
    guess: it is the command the scout is given, without the runner's
    bootstrap in front.

    Empty means we genuinely do not know. It must never be confused with "this
    cell has no command": the board said "not saved yet" about cells that had
    been serving for hours, first by reading COMMAND (which only a custom cell
    fills) and later by asking for a start.sh that a scout's host never has.
    """
    try:
        return effective_command(config or {})
    except Exception:  # noqa: BLE001
        # A misconfigured cell cannot render a command; that is a fact about the
        # config, not a reason to fail the whole board.
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


def _launch_in_library(cell_config, model_path, config, locations):
    """Which launch files only a library holds: {"stores": [{id, name}…],
    "roles": [role…]} — or None when all of them are on this disk, or nowhere
    (a file that is nowhere is the start's own error, and the start says it).

    The files are looked for where the cell's start joins them: its own models
    directory, or the controller's. For a cell of any machine: its scout reads
    a library's file in place where it mounts the library at the same path,
    and names the library it lacks otherwise (fleet_clients sends it where the
    controller reads each file). The chip was drawn for the controller's own
    cells only, and the cells that moved to its machine's scout lost it.
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


def _parked_model_size(model_path, config, locations):
    """Weights-on-disk for a parked cell's ≈VRAM badge: here — or, for weights
    a move put in a library, the library's own measure, so the badge does not
    vanish with the move."""
    return (_slot_model_size_bytes(model_path, str(models_dir_from_config(config)))
            or locations.library_size(model_path))


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


def _freshness_inputs(config):
    """(the watcher's report, the models directory it keys files by) — or an
    empty report when it cannot be read: no ⇪ on any card, never a guess."""
    try:
        from caravan.admin.model_watch import freshness_report
        return freshness_report(), str(models_dir_from_config(config))
    except Exception:
        return {}, ""


def topology_server(config=None):
    """The fleet's cells as the board draws them: every cell a scout reports
    (running or starting), and every stored slot that is not live (stopped or
    reserved), so a proxy cable stays attached across a stop or a model
    change. Since step 6.8 every cell runs through the scout of its machine;
    the controller's machine's cards are its scout's report (gpu_state)."""
    config = config or parse_config()
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
    llama_servers = []

    # Launch-time context window per remote slot (CTX_SIZE captured when the
    # server was started) — used as the "ctxMax" fallback when the route-agent
    # doesn't report n_ctx itself.
    def _slot_ctx_max(host_id, port):
        slot = topo.slot(host_id, port)
        cfg = slot.get("config") or {}
        if not uses_token_context(cfg):
            return None
        # The runner's own field: vLLM's window is MAX_MODEL_LEN and Strata's
        # STRATA_CONTEXT — read as CTX_SIZE, their cards showed the window
        # every config inherits.
        try:
            return int(cfg.get(for_config(cfg).context_field) or 0) or None
        except (TypeError, ValueError):
            return None

    # Add remote llama-servers from connected clients — running OR still
    # starting up (downloading the model / loading into VRAM).
    startup_phases = ("resolving", "downloading", "loading")
    _tstore = topology_store()
    # What the libraries hold, as last measured — once for all the cards, and
    # without waiting for a NAS that may not answer.
    model_locations = current_locations()
    # How the models stand against Hugging Face, as the watcher last measured —
    # once for all the cards (⇪ on a card, for every file of its launch).
    fresh_report, models_dir = _freshness_inputs(config)
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
        # The name, by the one rule a stopped cell's card uses too, and from the
        # model the cell is configured with when it has a slot: the scout reports
        # where IT reads the model, and a checkpoint folder's last segment is its
        # precision — the same seamless cell read "FP32" running and
        # "seamless-m4t-v2-large" stopped.
        model_name = display_model_name(str((_r_slot or {}).get("model") or "") or model_path)
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
        # Only a running command cell gets one; read for every cell below. Set
        # per cell: while it was not, a llama cell read the one its neighbour
        # left (another cell's version and language on its card), or — with no
        # command cell before it — none, and /api/topology answered 500.
        _ch = None
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
        # Its scout says the port does not listen yet (2.7+): a process still
        # starting — vLLM installs and loads for minutes before it listens,
        # and from here a silent port looked like a running cell. Where the
        # start is comes from its last lines, by the words a cell of this
        # controller's journal is read with.
        _starting_note = ""
        if running and ln.get("listening") is False:
            effective_phase = "starting"
            _starting_note = CellWords.progress_note(ln.get("startingTail"))
        # Authoritative input modalities: probe the remote /props once the model
        # is loaded (cached); fall back to whatever the heartbeat carried.
        remote_mods = None
        if health == "ok" and not slot_is_command:
            remote_mods = remote_llama_modalities(client_ip, remote_port)
        if remote_mods is None:
            remote_mods = _normalize_modalities(ln.get("modalities"))
        _crash = _scout_crash_note(ln.get("crash"))
        # A cell this controller holds no settings for — made by the controller that ran on the
        # machine before this one — has no runner on record here: what it runs is what it says
        # about itself (2026-10-12: a faster-whisper cell stood on the board as ":22005" with no
        # name, and every such cell wore the chat mark). Asked only while it runs.
        _about = remote_cell_about(client_ip, remote_port) if running and not _r_cfg else {}
        model_name = model_name or _about.get("model", "")
        _meta = _cell_meta(_ch, _r_cfg, slot_is_command)
        for _said in ("engine", "kinds", "langs", "maxAudioMs", "targetLang"):
            if _said in _about and _said not in _meta:
                _meta[_said] = _about[_said]
        _shown_phase = effective_phase if running else (phase or "starting")
        _progress = {"progressNote": _starting_note} if _starting_note else {}
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
            "cellMeta": _meta,
            "modelPath": model_path,
            # Which of its launch files a library holds — the card's 📚. By the
            # saved config's paths: what the scout reports is where IT reads them.
            "modelStore": _launch_in_library(_r_cfg, str((_r_slot or {}).get("model") or ""), config,
                                             model_locations),
            # ⇪: a launch file differs from Hugging Face; ⟳: the scout says a
            # file it holds changed on disk after the cell started (2.11+).
            "launchFresh": LaunchFiles(_r_cfg, str((_r_slot or {}).get("model") or "")).fresh(fresh_report,
                                                                                            models_dir),
            "launchDiskNewer": LaunchFiles.disk_newer(ln.get("launchDiskNewer")),
            "mmproj": str(ln.get("mmprojPath") or ""),
            "specDraft": str(ln.get("specPath") or ""),
            "specType": str(ln.get("specType") or ""),
            "status": ({"phase": "broken", "error": str((_ch or {}).get("error") or "")}
                       if effective_phase == "broken" else
                       {"phase": _shown_phase, **_progress, **_scout_retry_note(_crash, _shown_phase)}),
            "service": "",
            "gpuIndexes": [],
            "isRemote": True,
            "clientId": str(client.get("id") or ""),
            "clientIp": client_ip,
            "gpuName": gpu_name,
            "uptimeSec": ln.get("uptimeSec"),
            "pid": ln.get("pid"),
            # Bound to the card as the cell's too (_bind_servers_to_gpus).
            "pids": list(ln.get("pids") or []),
            # The memory the cell holds in RAM, in bytes (scout 2.35: the RSS of those processes); None when the scout does not say.
            "ramBytes": ln.get("ramBytes"),
            "phase": effective_phase,
            "modelReady": (health == "ok") if running else None,
            "downloadedBytes": _cmd_dl or int(ln.get("downloadedBytes") or 0),
            "totalBytes": _cmd_tot or int(ln.get("totalBytes") or 0),
            # The file the scout is on, as it names it. The card read this field from the first day and never got it: it
            # said "downloading model" for every file, and a model of two parts gave no sign of which part the numbers were.
            "downloadingFile": str(ln.get("downloadingFile") or ""),
            "promptTps": ln.get("promptTps"),
            "genTps": ln.get("genTps"),
            # How many requests the cell answers now (llama.cpp's own count, vLLM's, Strata's), as its scout says it. None when the scout
            # does not say, and never a 0 in its place: the cell's line breathes on a number above 0 (cell-speed.js), not on a held speed.
            "requestsProcessing": ln.get("requestsProcessing"),
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
            # Whether its scout keeps the model after a stop — the form's
            # switch opens on the cell's own value, not on its default.
            "cacheModels": bool((_r_slot or {}).get("cacheModels")),
            "commandHistory": (_r_slot.get("commandHistory") or []) if _r_slot else [],
            # A RUNNING cell carries its saved line too. It did not, and the cell
            # modal — which shows the command for every runner but llama — told
            # the operator "not saved yet" about a cell that was serving traffic.
            "savedCommand": _saved_command(_r_slot, _r_cfg) if slot_is_command else "",
            # Its scout keeps it and starts it when the machine boots (2.4+);
            # an older scout cannot, and says nothing — not "no".
            # How many times it crashed since it was last started by hand, and
            # why — its scout's watchdog keeps it (2.5+); the kind is ours to
            # tell, from the same words as a cell of this controller.
            "crash": _crash,
            # A vLLM cell's queue and rates, as a cell of this controller has
            # them from its own /metrics — its scout reads them (2.7+).
            "vllmStats": (_scout_vllm_stats(ln) if running and runner_id(_r_cfg) == "vllm" else None),
            "bootEnabled": _as_port(remote_port) in (client.get("autostart") or []),
            "bootSupported": isinstance(client.get("autostart"), list),
        })

    # Persistent server slots not currently live → render as stopped servers so
    # the proxy cable stays attached across stop / model change.
    store = _tstore
    live_keys = {(s.get("clientId"), s.get("port")) for s in llama_servers}
    hosts_by_id = store.get("hosts", {})
    for slot in store.get("serverSlots", {}).values():
        host_id = str(slot.get("hostId") or "")
        port = slot.get("port")
        if (host_id, port) in live_keys:
            continue
        client = hosts_by_id.get(host_id) or {}
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
        # Configured vs empty: a command cell counts as configured when it has
        # a command to run. The test used to be a hand-written list of runner
        # ids, which went stale the moment a runner was added — seamless and
        # translate cells, fully configured, rendered as empty "reserved" slots.
        slot_phase = "stopped" if (model_path or (
            slot_is_command and _saved_command(slot, slot_cfg).strip())) else "reserved"
        llama_servers.append({
            "id": f"slot:{host_id}:{port}",
            "name": str(client.get("name") or host_id),
            "port": port,
            "host": client_ip,
            "model": display_model_name(model_path),
            "cellLabel": cell_artifact_label(slot_cfg),
            "cellMeta": _cell_meta(None, slot_cfg, slot_is_command),
            "modelPath": model_path,
            "modelStore": _launch_in_library(slot_cfg, model_path, config, model_locations),
            "launchFresh": LaunchFiles(slot_cfg, model_path).fresh(fresh_report, models_dir),
            "mmproj": str(slot_cfg.get("MMPROJ_FILE") or ""),
            "specDraft": str(slot_cfg.get("SPEC_DRAFT_MODEL_FILE") or ""),
            "specType": str(slot_cfg.get("SPEC_TYPE") or ""),
            "status": {"phase": slot_phase},
            "service": "",
            "gpuIndexes": [],
            "isRemote": True,
            "isController": False,
            "isSlot": True,
            "clientId": host_id,
            "clientIp": client_ip,
            "gpuName": gpu_name,
            "modalities": None,
            "phase": slot_phase,
            "downloadedBytes": 0,
            "totalBytes": 0,
            "downloadingFile": "",
            # A parked cell keeps only the trained number, in its GGUF header.
            "ctxMax": _slot_ctx_max(host_id, port),
            "ctxServed": None,
            "ctxTrained": _gguf_trained_window(model_path, config),
            # ≈VRAM hint for a parked cell: weights-on-disk size (context/KV
            # overhead not included). Live phases get the real figure from GPU
            # process memory instead.
            "modelSizeBytes": _parked_model_size(model_path, config, model_locations),
            "promptTps": None,
            "genTps": None,
            "requestsProcessing": None,
            "vllmStats": None,
            "schedule": slot.get("schedule") or None,
            "slotConfig": slot_cfg,
            "cacheModels": bool(slot.get("cacheModels")),
            "commandHistory": slot.get("commandHistory") or [],
            # The launch line this cell is saved with. A RUNNING cell carries its
            # line too (above): the cell modal shows the command for every runner
            # but llama, and it once told the operator "not saved yet" about a
            # cell that was serving traffic.
            "savedCommand": _saved_command(slot, slot_cfg) if slot_is_command else "",
            "bootEnabled": _as_port(port) in (client.get("autostart") or []),
            "bootSupported": isinstance(client.get("autostart"), list),
            "pid": None,
            "lastError": "",
            "crash": None,
            "firewall": None,
            "reachable": None,
        })

    return {
        "id": CONTROLLER_HOST_ID,
        # The name of the computer the controller runs on — the board names
        # its machine by its node (its scout's report) and falls back to this
        # when no scout reports from it. It was a display name of its own
        # (LLAMA_TOPOLOGY_SERVER_NAME), and Routing named the machine by it:
        # the controller's old name over its machine's cells (2026-09-25).
        "hostname": ControllerMachine.name(),
        "ip": TOPOLOGY_SERVER_IP,
        "gpus": gpus,
        "gpuError": gpu_error,
        "llamaServers": llama_servers,
    }

def _bind_servers_to_gpus(gpus, compute_apps, servers, engines=None):
    """many-to-many: fill server.gpuIndexes (+ per-gpu MiB) from pid→gpu, and
    reverse-fill gpu.serverPorts. Handles N servers on one GPU and one server
    split across N GPUs. The memory that is no cell's is named by who holds
    it (`outside`): an engine of the machine by its processes, else the
    process's own name (GpuOwners)."""
    uuid_to_index = {str(g.get("uuid")): g.get("index")
                     for g in gpus if g.get("uuid")}
    pid_indexes: dict = {}
    pid_mem: dict = {}
    pid_name: dict = {}
    for app in compute_apps or []:
        idx = uuid_to_index.get(str(app.get("gpuUuid")))
        if idx is None:
            continue
        pid = app.get("pid")
        pid_indexes.setdefault(pid, set()).add(idx)
        pid_mem[(pid, idx)] = app.get("usedMiB", 0)
        pid_name[pid] = str(app.get("name") or "")
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
    owners = GpuOwners(engines)
    for g in gpus:
        idx = g.get("index")
        g["serverPorts"] = sorted(gpu_ports.get(idx, set()),
                                  key=lambda x: (x is None, x))
        fleet_mib = non_fleet_mib = 0
        foreign = []
        for (pid, i), mib in pid_mem.items():
            if i != idx:
                continue
            if pid in fleet_pids:
                fleet_mib += mib
            else:
                non_fleet_mib += mib
                foreign.append((pid, mib, pid_name.get(pid, "")))
        g["fleetUsedMiB"] = round(fleet_mib)
        g["nonFleetUsedMiB"] = round(non_fleet_mib)
        # nonFleetUsedMiB by who holds it — the same memory, named.
        g["outside"] = owners.split(foreign)
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
    """Host-centric view: one node per machine with a scout, each with its
    GPUs + the llama-servers running/declared on it + CPU/RAM. Server↔GPU is
    bound via per-process GPU memory (compute-apps). The controller runs no
    cell itself since step 6.8 and has no node of its own: its machine is
    the host node of its scout, marked controllerMachine."""
    nodes = []
    # Poweroff schedules, keyed by hostId — attached to each node so the board
    # can show and edit the machine's shutdown time next to its power button.
    _power_scheds = topo.power_schedules()

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
        _bind_servers_to_gpus(hgpus, host.get("computeApps"), servers, host.get("engines"))
        _record_gpu_history(cid, hgpus)
        for s in servers:
            s["tpsHistory"] = _record_tps_history(
                f"{cid}:{s.get('port')}", s.get("promptTps"), s.get("genTps"), s.get("requestsProcessing"))
        host_cpu = dict(host.get("cpu") or {})
        host_cpu["history"] = _record_cpu_history(cid, host_cpu)
        own = ControllerMachine().is_host(host)
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
            "prismRuntime": host.get("prismRuntime") or {},
            "llamaBinaryMtime": host.get("llamaBinaryMtime") or "",
            "llamaUpdate": host.get("llamaUpdate") or {},
            "scoutVersion": host.get("scoutVersion") or "",
            "powerSchedule": _power_scheds.get(cid) or {},
            # Ollama, LM Studio on the machine (scout 2.12+): None when its
            # scout cannot look — the board then draws no block at all. Each
            # model says whether the operator made it a router output.
            "engines": EngineOutputs().annotate(host),
            # The machine's models as its entry lists them (scout 2.28+): each with its state, its
            # places and its copies — the board's word for a pool row's model of the machine. None
            # when its scout cannot say.
            "entryModels": host.get("entryModels") if isinstance(host.get("entryModels"), list) else None,
            # Its model cache (scout 2.34+): the setting and the figures the machine's card shows. None when its scout cannot say.
            "modelCache": host.get("modelCache") if isinstance(host.get("modelCache"), dict) else None,
            # The machine this controller runs on: its node carries the
            # controller's own Server stats panel.
            "controllerMachine": own,
            # Why its card list is empty, when a card cannot be asked (a
            # driver waiting for a reboot): nvidia-smi's words as its scout
            # heard them (scout 2.25+). Only the controller's own machine had
            # it, read by the controller there; now every machine's scout says it.
            "gpuError": str(host.get("gpuError") or ""),
            # What its next boot does to its NVIDIA card, said before the
            # reboot (scout 2.19+; 2026-09-26): [] when nothing, or its scout
            # cannot tell.
            "driverWarnings": DriverOutlook(host.get("driver")).warnings(),
        })

    return nodes

def host_suspects(hosts):
    """Machines whose scout says a fresh llama.cpp build crashes their cells
    (scout 2.6+): a row each in the board's banner, named as the board names
    the machine, with the build it runs now for the rollback's confirmation."""
    rows = []
    for host in hosts:
        verdict = host.get("llamaSuspect")
        if isinstance(verdict, dict) and verdict.get("suspect") is True:
            rows.append({**verdict, "hostId": str(host.get("id") or ""),
                         "name": str(host.get("name") or host.get("id") or ""),
                         "llamaBinaryVersion": str(host.get("llamaBinaryVersion") or "")})
    return rows


def _scout_crash_note(note):
    """A scout's crash note as the card reads it, or None."""
    if not isinstance(note, dict):
        return None
    try:
        count = int(note.get("count") or 0)
    except (TypeError, ValueError):
        return None
    if count <= 0:
        return None
    reason = str(note.get("reason") or "")[:300]
    # The last lines of the crashed run's log (2.6+), shown on hover.
    tail = str(note.get("tail") or "")[-1500:]
    return {"count": count, "at": str(note.get("at") or ""), "kind": CellWords.crash_kind(reason), "reason": reason,
            **({"tail": tail} if tail else {}),
            **({"gaveUp": True} if note.get("gaveUp") else {})}


def _scout_retry_note(crash, phase):
    """While a scout's watchdog brings a crashed cell back, what the attempt
    before died of — the ⚠ on its card. Nothing when the cell is not coming
    back."""
    if not crash or crash.get("gaveUp") or phase not in ("starting", "warming"):
        return {}
    tail = crash.get("tail") or ""
    return {"lastError": {"kind": CellWords.failure_kind(tail or crash["reason"]), "detail": crash["reason"],
                          "tail": tail}}


def _scout_vllm_stats(ln):
    """A scout's vLLM cell's queue and rates in the shape the card reads for a
    vLLM cell of this controller (llama_metrics.vllm_metrics_sample), or None
    when its scout does not say them (older than 2.7)."""
    if ln.get("requestsProcessing") is None:
        return None
    return {"ok": True, "requestsRunning": int(ln.get("requestsProcessing") or 0),
            "requestsWaiting": int(ln.get("requestsWaiting") or 0),
            "genTps": ln.get("genTps"), "promptTps": ln.get("promptTps")}


def _as_port(value):
    """A port as the number a scout's autostart list holds, or None."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _router_outputs(proxy_config):
    """Output id → the routers' output, as the proxy reads them: a cell's address and what its
    model does (caravan/common/model_kinds.py)."""
    return {str(out.get("id")): out for router in (proxy_config or {}).get("routers") or []
            for out in router.get("outputs") or [] if isinstance(out, dict) and out.get("id")}


def _pool_window_resolver(pools, outputs=None):
    """pool id → (window, pool): the figure a pool stands for, by the pool's own rule.

    The catalogues are consulted only for a pool whose switch is on — the same
    condition under which the proxy reads them (caravan/proxy/cloud_auth.py),
    and with the same rule (CloudPools.window), so the board and the port
    derive the pool's number from the same sources: a cell's row counts by the
    window its router output carries (`outputs`, 1.3.502).
    """
    from caravan.common.cloud_pools import CloudPools
    by_id = {str(p.get("id")): p for p in (pools or []) if isinstance(p, dict)}
    catalogues = {}

    def named(account_id, model):
        if account_id not in catalogues:
            try:
                from caravan.admin.model_catalog import cached_models_entry
                models = (cached_models_entry(account_id) or {}).get("models") or []
            except Exception:
                models = []
            catalogues[account_id] = {m.get("id"): m.get("contextLength")
                                      for m in models if isinstance(m, dict)}
        return catalogues[account_id].get(model)

    def resolve(pool_id):
        pool = by_id.get(str(pool_id or ""))
        if pool is None:
            return None, None
        # A step's catalogue is its credential's: a test alias's is its original's.
        steps = [{**s, "accountId": s.get("usageAccountId") or s["accountId"]} if s.get("kind", "account") == "account"
                 else s for s in pool.get("steps") or []]
        local = (lambda output_id: (outputs.get(str(output_id)) or {}).get("contextLength")) if outputs else None
        return CloudPools.window({**pool, "steps": steps}, named, local), pool

    return resolve


def annotate_pool_kinds(pools, accounts, outputs):
    """Every pool with what its rows do together (`kind`, caravan/common/model_kinds.py): the
    jobs and a chat's inputs the entry tells its clients, `{"mixed": true}` when the rows do
    different work, None when a row that may serve says nothing of itself. Routing draws it
    on the pool and on the sets that hold it, and works none of it out itself."""
    by_id = {str(a.get("id")): a for a in accounts or [] if isinstance(a, dict)}
    for pool in pools or []:
        if isinstance(pool, dict):
            kind = ModelKind.of_pool(pool, lambda account_id: by_id.get(str(account_id)),
                                     lambda output_id: (outputs or {}).get(str(output_id)))
            pool["kind"] = kind.state() if kind is not None else None
    return pools


def annotate_pool_windows(pools, outputs=None):
    """Every pool with the window it states to its clients (`window`): the
    figure GET /v1/models gives them, by the pool's own rule — the operator's
    number, or the smallest its enabled rows' providers name when the switch is
    on (_pool_window_resolver, CloudPools.window) — and None when it states
    none. Routing says it under the pool's settings and works none of it
    out itself; a board that could not read it has no `window` at all, which
    is not None."""
    resolve = _pool_window_resolver(pools, outputs)
    for pool in pools or []:
        if isinstance(pool, dict):
            pool["window"] = resolve(pool.get("id"))[0]
    return pools


def _route_window_facts(route, proxy_config, served, resolve_pool):
    """What the output the port answers /v1/models from serves: (window, source).

    The same resolution GET /v1/models goes through — answer_port_question —
    so the board names the output the proxy answers from.
    `source` says where the number comes from, or why there is none: a dash
    with no reason would be absence rendered as normality (docs/why.md).
    """
    try:
        resolved = answer_port_question(route, proxy_config)
    except Exception as exc:
        return None, {"kind": "error", "reason": str(exc)[:120]}
    upstream_type = port_question_reaches(resolved)
    if not upstream_type:
        return None, {"kind": "unrouted", "reason": str(resolved.get("unrouted"))}
    if upstream_type == "cloud":
        pool_id = str(resolved.get("providerId") or "")
        if not pool_id:
            # An account passthrough pins no model, so no single window exists.
            return None, {"kind": "account", "account": str(resolved.get("cloudAccountId") or "")}
        window, pool = resolve_pool(pool_id)
        if pool is None:
            return None, {"kind": "unrouted", "reason": "pool missing"}
        return window, {"kind": "pool", "name": str(pool.get("name") or pool_id),
                        "models": [s.get("model") or s.get("output") for s in pool.get("steps") or []
                                   if s.get("enabled", True) and s.get("kind", "account") != "open"]}
    host = str(resolved.get("upstreamHost") or "127.0.0.1")
    port = _positive_int(resolved.get("upstreamPort")) or 0
    if upstream_type == "engine":
        # An engine next to the cells tells the proxy no window, so the port
        # advertises the operator's limit only — said as an engine's model,
        # not as a cell that went silent.
        return None, {"kind": "engine", "model": str(resolved.get("upstreamModel") or ""),
                      "host": host, "port": port}
    if upstream_type == "machine":
        # A model of a machine's entry: the smallest window its copies serve, as its output says it
        # (machine_models.MachineOutputs) — the scout's port serves many models, no one window.
        out = _router_outputs(proxy_config).get(str(resolved.get("routedOutputId") or "")) or {}
        return _positive_int(out.get("contextLength")), {"kind": "machine", "model": str(resolved.get("upstreamModel") or ""),
                                                         "host": host}
    return served.get((host, port)), {"kind": "cell", "host": host, "port": port}


def _proxy_output_health():
    """The proxy's verdicts as its state file last wrote them, or nothing."""
    try:
        payload = json.loads(AGENT_PROXY_STATE_FILE.read_text(encoding="utf-8"))
        rows = payload.get("outputHealth") if isinstance(payload, dict) else None
        return rows if isinstance(rows, dict) else {}
    except Exception:
        return {}


def annotate_route_windows(proxies, proxy_config, server_obj, pools):
    """Three windows on every proxy row: the model's, the operator's, the advertised one.

    `modelWindow` is what the output a plain request reaches serves, with
    `modelWindowSource` naming it; `effectiveWindow` is
    effective_window(limit, modelWindow, switch) — the figure the port publishes
    in /v1/models, which the proxy computes from the same inputs with the same
    rule. The limit and the switch are already on the row (`contextLength`,
    `contextAuto`), copied there from the assignment by reconcile_proxy_metadata.
    """
    served = _served_windows_by_address(server_obj)
    resolve_pool = _pool_window_resolver(pools, _router_outputs(proxy_config))
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
        window, source = _route_window_facts(proxy, proxy_config, served, resolve_pool)
        limit, prefer = route_window_inputs(proxy)
        proxy["modelWindow"] = window
        proxy["modelWindowSource"] = source
        # A port that reaches no output answers /v1/models with 503, not with a
        # list: it advertises nothing, whatever limit is written on it.
        proxy["effectiveWindow"] = (None if source.get("kind") in ("unrouted", "error")
                                    else effective_window(limit, window, prefer))
    return proxies


def annotate_consumer_set(proxies, entry_models):
    """Every consumer of the entry with the set its cable leads to and the models its key calls
    (caravan/common/entry_models.py): `set` the set's id and `setName` its name, both "" when no
    cable reaches the consumer — a set that is gone included — and `models` the names its
    `GET /v1/models` lists, in order. The board draws the cable and the names from here and never
    works them out of its own; the fields of an older form (`pool`, `models` as pool ids) are not
    handed on."""
    for proxy in proxies or []:
        if isinstance(proxy, dict) and str(proxy.get("kind") or "") == "consumer":
            found = entry_models.set_of(proxy)
            proxy["models"] = [EntryModels.name(pool) for pool in entry_models.models(proxy)]
            proxy.pop("pool", None)
            proxy["set"] = found["id"] if found else ""
            proxy["setName"] = found["name"] if found else ""
    return proxies


def annotate_consumer_misses(proxies, misses=None):
    """Every client of the entry with what it asked and was answered with an error over the last
    30 days (`misses`: {items, more}, caravan/admin/client_misses.py): Routing's client card
    lists them. A journal that cannot be read leaves the key out — not known is not "none"."""
    from caravan.admin.client_misses import CLIENT_MISSES
    reader = misses or CLIENT_MISSES
    clients = [p for p in proxies or [] if isinstance(p, dict) and str(p.get("kind") or "") == "consumer"]
    found = reader.of([int(p.get("port") or 0) for p in clients])
    if found is None:
        return proxies
    for proxy in clients:
        proxy["misses"] = found.get(int(proxy.get("port") or 0), {"items": [], "more": 0})
    return proxies


def _board_proxy(route, *, holders, last_seen, routers_by_id, address=None):
    """One proxy route as the board is handed it: the route's own fields plus
    its id and address, when it last served, where its router actually sends
    it, and who holds it. The address is the consumer's (ConsumerAddress): the
    entry's once the port is closed. `keyTail` is the key's last four
    characters — what the board shows of a key.

    Its own function so that what a proxy carries can be checked by value —
    topology_state around it reaches twenty collaborators.
    """
    served = last_seen.get(int(route.get("port") or 0) or -1)
    proxy = {
        **route,
        "id": f"skynet:proxy:{route.get('port')}",
        "endpoint": (address.of(route.get("port") or 0) if address
                     else ProxyRoute.port_url(TOPOLOGY_SERVER_IP, route.get("port") or 0)),
        "keyTail": KeyEntry.tail(route.get("apiKey")),
        "upstreamId": f"skynet:llama-server:{route.get('upstreamPort')}",
        "lastRequestAt": int(served) if served else 0,
    }
    if str(route.get("kind") or "") == "consumer":
        # A consumer's key is shown once, when it is made (caravan/admin/consumers.py):
        # the board gets its last four characters, and a save from the page keeps
        # the stored key (PolicyOwnedFields).
        proxy.pop("apiKey", None)
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
    # One reading for the lists the board draws and for their versions: a save
    # made from this answer names the version of exactly what it was shown.
    proxy_reading = read_agent_proxy_payload()
    proxy_revisions = ProxyRevisions.of(proxy_reading)
    proxy_config = load_agent_proxy_config(proxy_reading)
    policy = proxy_config.get("policy") or normalize_agent_proxy_policy({})
    proxies = []
    _routers_by_id = {str(r.get("id")): r for r in (proxy_config.get("routers") or [])}
    # Traffic is proof a route is used — the board promotes "unverified" to
    # "confirmed" on it, since most agents never report their own config.
    _last_seen = proxy_ports_last_seen()
    _holders = _port_holders()
    door = PortDoor().open()
    address = ConsumerAddress(proxy_config, TOPOLOGY_SERVER_IP, door)
    for route in proxy_config.get("routes", []):
        proxies.append(_board_proxy(route, holders=_holders, last_seen=_last_seen, routers_by_id=_routers_by_id,
                                    address=address))
    server_obj = topology_server(config)
    hosts = topology_hosts()
    # Auto-sync router outputs to the available providers: the cells, the
    # engine models the operator made outputs, the models of the machines'
    # entries (1.3.506), the pools.
    # Persist once when they change so agent-proxies.py routes.
    desk = PoolDesk()
    try:
        routers = proxy_config.get("routers") or []
        if sync_router_outputs(routers, server_obj, desk.state(), EngineOutputs().outputs(hosts),
                               MachineOutputs().outputs(hosts, server_obj)):
            # Re-read fresh payload before writing to avoid overwriting concurrent
            # label/policy changes that happened since proxy_config was loaded above.
            fresh = read_agent_proxy_payload()
            fresh["routers"] = routers
            write_agent_proxy_payload(fresh)
            proxy_config["routers"] = routers
            proxy_revisions = ProxyRevisions.of(read_agent_proxy_payload())
    except Exception:
        pass
    clients = topology_clients()
    # Cloud state + catalog annotation: unlisted marks on steps, background
    # model-list refreshes, endpoint-health report. Annotation must never sink
    # the board — degrade to plain state on any failure.
    cloud_accounts = cloud_accounts_state()
    pools = desk.state()
    sets = SetDesk().state()
    entry_models = EntryModels(pools, sets)
    annotate_consumer_set(proxies, entry_models)
    try:
        annotate_consumer_misses(proxies)
    except Exception:
        pass
    # The three context windows of every route (model / limit / advertised):
    # a board fact, never a reason for the board to sink.
    try:
        annotate_route_windows(proxies, proxy_config, server_obj, pools)
    except Exception:
        pass
    try:
        annotate_pool_windows(pools, _router_outputs(proxy_config))
    except Exception:
        pass
    try:
        annotate_pool_kinds(pools, cloud_accounts, _router_outputs(proxy_config))
    except Exception:
        pass
    try:
        from caravan.admin.cloud_api import annotate_cloud_topology
        cloud_api_health = annotate_cloud_topology(cloud_accounts, pools)
    except Exception:
        cloud_api_health = {"endpoints": {}, "codexClientVersion": {}}
    return {
        "server": server_obj,
        # A fresh llama.cpp build crashing a machine's cells: its scout keeps
        # the verdict, and the board's banner offers a consented rollback.
        "hostSuspects": host_suspects(hosts),
        # Host-centric model: one node per machine with a scout, with its
        # GPUs + servers + CPU/RAM, server↔GPU bound via compute-apps.
        "nodes": topology_nodes(config, server_obj, hosts),
        "proxies": proxies,
        # The fleet's port ranges, so the picker grid and the front-side port
        # preview draw the REAL window instead of a hardcoded copy of it — the
        # copies are what went stale when the controller moved off 8090.
        "cellPortRange": {"from": SERVER_CELL_BASE_PORT, "to": SERVER_CELL_UPPER_PORT,
                          "proxyBase": AGENT_PROXY_BASE_PORT},
        # The stamp of the models the cell editor offers: when it moves, the
        # board fetches the list again (the caravan's shelf reads it).
        "modelsStamp": MODEL_LIST.stamp(),
        # Routers — the routing layer between proxies and servers.
        # inputs already derived from routes by normalize_routers.
        "routers": proxy_config.get("routers") or [],
        # The version of `routes` and `routers` this answer was drawn from: a save
        # sends it back, and a save from an older one is refused (ProxyRevisions).
        "proxyRevisions": proxy_revisions,
        "proxyPolicy": policy,
        "effectiveSlots": int(policy.get("maxSlots") or 1),
        # Two records under one id, never one merged row: a machine's report
        # and liveness are in `hosts`, the operator's clients in `clients`
        # (docs/scout-split.md). The merged rows the board read until it read
        # `hosts` are gone with that reading.
        "hosts": hosts,
        "clients": clients,
        # Each route's address rebuilt from the controller's current one
        # (ProxyRoute.address): the stored copy is the address at bind time.
        # A closed port's route names the entry (ConsumerAddress).
        "assignments": _assignments_at_current_address(store.get("assignments", {}), address),
        # The one address every consumer with a key may use, and its port; none when it is off.
        "entry": address.entry(),
        # The tests a client's card sends as the client, from the table that sends them.
        "clientProbes": AsConsumer.probes(),
        # Whether other machines reach the ports (PortDoor): False where they
        # listen on loopback only (a port then has no address of its own), None
        # while the proxy has said nothing fresh.
        "portsReachable": door,
        # When a client last asked for /v1/embeddings (7 days; 0 for not at all): Routing's
        # unset embeddings slot is red only then.
        "embeddingsCalledAt": embeddings_last_called(),
        # User notes on cell slots, keyed "hostId:port" — shown on the board
        # cards and edited in the cell detail modal.
        "cellNotes": {key: str(slot.get("note") or "")
                      for key, slot in (store.get("serverSlots") or {}).items()
                      if isinstance(slot, dict) and str(slot.get("note") or "").strip()},
        "clientAliases": store.get("clientAliases", {}),
        # The order of the server cards — the pools and the machines in one
        # list — and its revision (board_layout.py), read
        # from the same document as everything else in this answer.
        "layout": {**ServerOrder(section=lambda: store).layout(), **ClientOrder(section=lambda: store).layout()},
        "cloudAccounts": cloud_accounts,
        # The pools — what an agent's cable goes to — with their steps, and the
        # proxy's word on which step served each one last (caravan/admin/pools.py).
        "pools": pools,
        # The sets of models the entry's clients call (caravan/admin/model_sets.py), Routing's «Набор».
        "sets": sets,
        "poolsRuntime": desk.runtime(),
        # The levels of every subscription model, in a pool or not: Routing
        # draws them on the models of its right column (PoolDesk.model_levels).
        "modelLevels": desk.model_levels(),
        # The models that column shows, by account: the ones the operator added
        # there, not every model an account offers (caravan/admin/added_models.py).
        "addedModels": desk.added_models(),
        # When each model is open, and the caravan's zone its hours are written in
        # (caravan/admin/model_schedules.py): the ⏱ on a model and a pool's row read it.
        "modelSchedules": ModelScheduleDesk().state(),
        # The cloud providers on the main board, each with its accounts, in the
        # operator's order (caravan/admin/board_providers.py).
        "boardProviders": ProviderDesk().state(),
        # Tripped upstream endpoints + effective codex client_version — the
        # pool cards render this as the "API issues" panel.
        "cloudApiHealth": cloud_api_health,
        "cloudProviderPresets": cloud_provider_presets_public(),
        "time": int(time.time()),
    }

def _assignments_at_current_address(assignments, address=None):
    """The stored assignments as the board is handed them: a copy in which
    every route names its port at the controller's CURRENT address — or, its
    port closed, the entry's (ConsumerAddress). The store itself is not
    touched; a route the class refuses is passed on as stored."""
    out = {}
    for host_id, entry in (assignments or {}).items():
        if not isinstance(entry, dict):
            out[host_id] = entry
            continue
        rows = []
        for row in entry.get("assignments") or []:
            if isinstance(row, dict) and isinstance(row.get("routes"), list):
                routes = []
                for raw in row["routes"]:
                    try:
                        route = ProxyRoute.from_raw(raw)
                        routes.append({**raw, "endpoint": (address.of(route.port) if address and route.port
                                                           else route.address(TOPOLOGY_SERVER_IP))})
                    except (AppError, TypeError, ValueError):
                        routes.append(raw)
                row = {**row, "routes": routes}
            rows.append(row)
        out[host_id] = {**entry, "assignments": rows}
    return out


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
    Routing says so out loud.
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
