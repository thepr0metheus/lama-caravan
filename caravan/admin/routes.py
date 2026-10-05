"""HTTP route tables and the request handler.

Every route body moved verbatim from the pre-split Handler if/elif chains.
Dispatch semantics preserved exactly: one prefix route (/api/monitor/) checked
first in GET; POST parses the JSON body before the path lookup (a bad body on
an unknown path is a 500, not a 404); DELETE has no AppError clause (-> 500).
"""
import base64
import gzip
import hashlib
import json
import os
import re
import secrets as secrets_mod
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from collections import deque
from struct import calcsize, unpack
from urllib.parse import urlparse


from caravan.admin.gpu_driver import driver_status, driver_update, set_auto_settings
from caravan.admin.model_card import proxy_model_card
from caravan.common.errors import AppError
from caravan.common.flags import truthy
from caravan.common.fetch import fetch_json, fetch_text, post_json
from caravan.common.fsio import read_text
from caravan.common.jsonx import _INF, _json_safe, json_bytes
from caravan.common.procs import run, run_in
from caravan.admin.paths import (
    CONTROLLER_HOST_ID,
    ADMIN_STATE_FILE,
    AGENT_PROXY_CONFIG_FILE,
    AGENT_PROXY_LOG_DIR,
    AGENT_PROXY_SERVICE_NAME,
    AGENT_PROXY_STATE_FILE,
    CLOUD_PROVIDERS_FILE,
    DEFAULT_MODELS_DIR,
    HOST,
    INCIDENT_LOG_FILE,
    INCIDENT_RETENTION_SECONDS,
    LLAMA_HOME,
    MODEL_PRICING_CACHE_PATH,
    MODEL_PRICING_TTL,
    MODEL_PRICING_URL,
    MONITOR_HISTORY_FILE,
    MONITOR_RETENTION_DEFAULT,
    MONITOR_SAMPLE_INTERVAL,
    PORT,
    PROJECT_ROOT,
    PROVIDER_SECRETS_FILE,
    SERVER_BACKUPS_DIR,
    SERVER_CELL_BASE_PORT,
    SERVICE_NAME,
    START_SCRIPT,
    STATIC_DIR,
    TOKEN_HISTORY_FILE,
    TOKEN_HISTORY_MAX,
    TOKEN_HISTORY_RETENTION_SEC,
    _BENCH_CACHE_DIR,
)
from caravan.admin.state import admin_state, load_admin_state, save_admin_state, topology_store
from caravan import __version__ as APP_VERSION
from caravan.admin.cell_schedule import set_cell_schedule
from caravan.admin.metrics import build_metrics_text
from caravan.admin.model_gc import delete_models, list_unused_models
from caravan.admin import auth as auth_mod
from caravan.admin.api_spec import ApiSpec
from caravan.admin.route_access import ROUTE_ACCESS, RouteAccess
from caravan.admin.status import controller_info, project_git_info, llama_builds_list, llama_cpp_info, llama_update_status, models_disk, start_llama_restore, start_llama_update, state
from caravan.admin.cell_assets import cell_asset_bytes, cell_assets_manifest
from caravan.admin.board_layout import SERVER_ORDER
from caravan.admin.host_power import host_power
from caravan.admin.host_power_schedule import set_host_power_schedule
from caravan.admin.cell_ops import (
    client_server_slot_add,
    client_server_slot_delete,
    script_preview,
    server_cell_action,
    server_cell_save_config,
)
from caravan.admin.telemetry import (
    _cpu_history,
    _gpu_history,
    _tps_history,
    command_cell_health,
    firewall_port_access,
    probe_remote_port,
    remote_llama_health,
    remote_llama_modalities,
)
from caravan.admin.server_cells import (
    assert_server_cell_port_available,
    delete_server_slot,
    move_host_cells,
    move_server_cell,
    next_server_cell_port,
    reserve_server_cell,
    server_slot_key,
    set_server_slot_note,
    upsert_server_slot,
    used_server_cell_ports,
)
from caravan.admin.fleet_clients import (
    HOST_TELEMETRY,
    _backup_meta,
    _backup_target_seg,
    _safe_path_seg,
    client_llama_configs,
    client_llama_configs_delete,
    client_llama_configs_save,
    client_llama_list_cache,
    client_llama_purge_cache,
    client_llama_builds,
    client_llama_restore,
    client_vllm,
    client_vllm_update,
    client_vllm_update_status,
    client_llama_suspect_dismiss,
    client_llama_start,
    client_llama_stop,
    client_llama_update,
    client_llama_update_status,
    client_monitor,
    set_topology_client_alias,
    topology_client_agent_delete,
    fallback_port_for,
    set_topology_agent_alias,
    topology_client_create,
    topology_client_delete,
    topology_clients,
    topology_hosts,
    SCOUT_PAIRING,
    record_host_report,
)
from caravan.admin.topology import (
    apply_topology_assignments,
    bind_agent_to_proxy,
    normalize_topology_assignment,
    set_agent_route_context,
    set_agent_route_model,
    remove_agent_route,
    topology_nodes,
    topology_server,
    topology_state,
)
from caravan.admin.proxy_ops import stop_agent_proxy_route
from caravan.admin.llama_metrics import runtime_phase
from caravan.admin.pricing import fetch_model_pricing
from caravan.admin.oauth import oauth_login_status, refresh_oauth_token, start_oauth_login
from caravan.admin.cloud_api import (
    auto_create_blocks,
    cloud_spend_summary,
    fetch_account_costs,
    fetch_account_models,
    fetch_openrouter_limits,
    fetch_subscription_models,
    fetch_subscription_usage,
    set_account_key,
    test_account_key,
    usage_stats,
)
from caravan.admin.queue_thresholds import QUEUE_THRESHOLDS, compute_queue_thresholds
from caravan.admin.token_history import (
    load_token_history,
    record_token_history,
    save_token_history,
    token_history_query,
)
from caravan.admin.proxy_stats import (
    agent_proxy_sample,
    list_agent_proxy_log_dates,
    load_agent_proxy_logs,
    proxy_daily_stats,
    proxy_usage_tokens,
    summarize_proxy_item,
)
from caravan.admin.monitoring import (
    append_incidents_from_sample,
    cpu_snapshot,
    gpu_compute_apps,
    runtime_api,
    collect_monitor_sample,
    correlate_activity,
    cpu_state,
    gpu_state,
    incident_lock,
    load_incident_log,
    load_monitor_history,
    memory_state,
    monitor_history,
    monitor_lock,
    monitor_retention_seconds,
    monitor_sampler_loop,
    monitor_snapshot,
    persist_monitor_history,
    set_monitor_retention,
    system_monitor_state,
    trim_incident_log,
)
from caravan.admin.router_dsl import (
    DEFAULT_ROUTER_ID,
    DEFAULT_UPSTREAM_HOST,
    DEFAULT_UPSTREAM_PORT,
    normalize_agent_proxy_policy,
    normalize_agent_proxy_route,
    normalize_router,
    normalize_router_graph,
    normalize_router_output,
    normalize_schedule_rule,
    recompute_cloud_fallback_eligibility,
)
from caravan.admin.proxies_config import (
    load_agent_proxy_config,
    mint_bridge_port,
    normalize_routers,
    read_agent_proxy_payload,
    save_agent_proxy_config,
    set_agent_proxy_policy,
    set_agent_proxy_route_policy,
    set_routers,
    sync_router_outputs,
    write_agent_proxy_payload,
)
from caravan.admin.cloud import (
    CLOUD_PROVIDER_PRESETS,
    account_auth_headers,
    account_credential_summary,
    account_secret_entry,
    cloud_accounts_state,
    cloud_blocks_state,
    cloud_provider_presets_public,
    delete_account_credential,
    delete_cloud_account,
    delete_cloud_block,
    load_cloud_data,
    load_provider_secrets,
    normalize_cloud_account,
    normalize_cloud_block,
    save_cloud_data,
    save_provider_secrets,
    mark_cloud_blocks_announced,
    upsert_cloud_account,
    upsert_cloud_block,
)
from caravan.admin.hf_verify import start_verify, verify_status
from caravan.admin.model_staging import (
    drop_prev, live_path_for, prev_overview, restore_prev, start_update,
)
from caravan.admin.model_watch import (
    check_pass, freshness_report, set_watch_settings, watch_settings,
)
from caravan.admin.hf import (
    _derive_model_name,
    _hf_cache,
    hf_list_files,
    hf_local_check,
    hf_local_delete,
    hf_model_tree,
    hf_search,
)
from caravan.admin.benchmarks import (
    _ensure_llm_lb,
    _llm_lb_status,
    hf_bench_search,
    hf_get_aa_scores,
    hf_get_benchmarks,
    hf_get_reference_models,
)
from caravan.admin.settings_bundle import (SETTINGS_BACKUP_DIR, apply_bundle,
                                          encrypt_credentials, export_bundle,
                                          preview_import)
from caravan.admin.downloads import (_download_jobs, _download_jobs_lock, cancel_hf_download,
                                    replaces_on_disk, resume_interrupted_download,
                                    scan_interrupted_downloads, start_hf_download)
from caravan.admin.terminal import terminal_frame_to_html, terminal_frame_to_text
from caravan.admin.models import (
    detect_family,
    embedding_family_defaults,
    extract_runtime_meta,
    list_chat_templates,
    list_gguf_models,
    list_models,
    read_gguf_metadata,
    serve_model_file,
)
from caravan.admin.systemd_ctl import (
    logs,
    read_cmdline,
    repair_user_service,
    service_status,
    systemctl,
    user_service_diagnostics,
    user_systemd_env,
)
from caravan.admin.config_builder import (
    CONFIG_BEGIN,
    CONFIG_END,
    CONFIG_FIELDS,
    FIELD_HELP,
    build_config_block,
    build_llama_args,
    build_local_llama_command,
    command_token_owners,
    build_remote_llama_args,
    is_command_cell,
    models_dir_from_config,
    parse_config,
    parse_config_from_text,
    parse_extra_args,
    parse_value,
    quote_shell_value,
    split_config,
)
from caravan.admin.launch import save_config


# --- HuggingFace Browser ---


# ── HF Benchmarks ─────────────────────────────────────────────────────────────


# ── Open LLM Leaderboard background cache ─────────────────────────────────────


# ── Benchmark result cache (persistent JSON) ──────────────────────────────────


# ── HF Download ───────────────────────────────────────────────────────────────


# ---- OAuth (authorization-code + PKCE) for cloud accounts ----




def _flag(query, name, default=False):
    """A boolean query-string parameter.

    One parser for every route: there used to be four separate spellings of
    this, and two parameters both named `force` understood only the literal
    "1", so `?force=true` was silently read as "no". The dict is shared
    across the caravan, see caravan/common/flags.py.
    """
    values = query.get(name) if query else None
    if not values:
        return bool(default)
    return truthy(values[0])


GET_ROUTES = {}
POST_ROUTES = {}
DELETE_ROUTES = {}


def _route(table, *paths):
    def register(fn):
        for p in paths:
            if p in table:
                raise RuntimeError(f"duplicate route {p}")
            table[p] = fn
        return fn
    return register


def _get_static_subdir(h, parsed):
    """Serve a JavaScript module or stylesheet of the web UI

    `file` — a name made of letters, digits, `.`, `_` and `-` that ends in `.js` or `.css` (a
    `/js/i18n/<code>.js` path is served too); anything else, or a file that is not there, is a
    404. The answer carries an `ETag` and `Cache-Control: no-cache`, and a matching
    `If-None-Match` gets 304.
    """
    # /js/<name>.js and /css/<name>.css — ES modules and split stylesheets —
    # plus /js/i18n/<code>.js, the one nested directory we serve (one language
    # table per file; see static/js/i18n-data.js for why they are separate).
    # Neither name class admits a "/" or a "..", so no traversal is possible and
    # the nesting is a fixed literal rather than a path the caller supplies.
    m = re.fullmatch(r"/(js|css)/((?:i18n/)?[A-Za-z0-9._-]+)", parsed.path)
    ctype = None
    if m and ".." not in m.group(2):
        name = m.group(2)
        if name.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif name.endswith(".css"):
            ctype = "text/css; charset=utf-8"
    if ctype is None:
        h.send_json({"error": "Not found"}, 404)
        return
    h.send_file(STATIC_DIR / m.group(1) / name, ctype)


def _get_api_monitor(h, parsed):
        """Terminal-style snapshot of the controller's machine: nvidia-smi or btop

        `kind` — the last path segment, `nvidia-smi` or `btop`; any other value is a 404.
        Answers `{kind, ok, output, time}`; `btop` adds `source` (`btop`, or `top` when btop
        cannot draw) and, when it drew, an `html` rendering.
        """
        kind = parsed.path.rsplit("/", 1)[-1]
        h.send_json(monitor_snapshot(kind))
        return

@_route(GET_ROUTES, '/api/system-monitor')
def _get_api_system_monitor(h, parsed):
        """Sampled load history of the controller's machine and of each machine with a scout

        `since` — epoch seconds; only newer samples and incidents come back, and
        `newestSample` is the value to send next time. `samples` and `latest` describe the
        controller's own machine, with the requests in flight by route in
        `correlatedActivity`. `hosts` holds each scout machine's samples; `hostsSince`
        (`id:t,id:t`) names the newest row held per machine, and a machine it omits comes
        back whole.
        """
        # ?since=<epoch> — send only samples newer than the caller already has.
        # Omitted, the whole series comes back exactly as before.
        _q = urllib.parse.parse_qs(parsed.query or "")
        since = (_q.get("since") or ["0"])[0]
        payload = system_monitor_state(since)
        # The machines with a scout, second by second: what is here now, and
        # a pull kicked for the next read (HostTelemetry). ?hostsSince=id:t,…
        # is the newest row the board holds of each, by that scout's clock.
        payload["hosts"] = HOST_TELEMETRY.watch((_q.get("hostsSince") or ["0"])[0])
        h.send_json(payload)
        return

@_route(GET_ROUTES, '/api/topology')
def _get_api_topology(h, parsed):
        """Topology of the board: hosts, clients, cells, proxies, routers and cloud accounts

        `hosts` are the machines with a scout, `clients` the operator's hand-made records,
        and `modelsStamp` changes when the model list does. Reading it also kicks a
        background refresh of the scouts' reports (never waited for) and brings the routers'
        outputs in line with the current cells, models and cloud blocks, saving them when
        they changed.
        """
        h.send_json(topology_state())
        return

@_route(GET_ROUTES, '/api/script-preview')
def _get_api_script_preview(h, parsed):
        """Read-only preview of a script that a command cell's COMMAND line refers to

        `path` — a `.sh`, `.bash` or `.py` file under the controller's home directory (`~`
        is expanded, a relative path is taken from home). Answers `{path, size, mtime,
        content, truncated}` with `content` cut at 64 KB. 400 for a missing path, another
        extension or a file outside home; 404 when the file is not there.
        """
        _q = urllib.parse.parse_qs(parsed.query or "")
        h.send_json(script_preview((_q.get("path") or [""])[0]))
        return

@_route(GET_ROUTES, '/api/models')
def _get_api_models(h, parsed):
        """List the GGUF files under the controller's models directory

        The directory is the configured one (`LLAMA_MODELS_DIR` of the saved config, else
        the default) — the one the cell editor's picker lists and downloads are served
        from. Vision projectors, vocab files and files under 1 KiB are skipped. Answers
        `{ok, models, modelsDir}` with rows `{path, name, sizeMiB, dir}`, `path` relative
        to `modelsDir`; when that directory is missing, `ok` is false with an `error`.
        """
        h.send_json(list_gguf_models())
        return

@_route(GET_ROUTES, '/api/models/rows')
def _get_api_models_rows(h, parsed):
        """Rows of the cell editor's model picker, with a stamp that changes when they do

        Each row is a model, `mmproj` or `draft` file (`kind`) with its size, `mtime` and
        freshness; model rows add capability, detected family and GGUF header facts, and a
        file only a library holds is marked `libraryOnly` with its `store`. Answers `{ok,
        models, stamp}` from a list kept for 5 seconds. Fetch it again when the topology's
        `modelsStamp` differs from `stamp`.
        """
        # The cell editor's list, for a board whose topology stamp moved:
        # the caravan's shelf and the picker follow a model downloaded or
        # deleted without reloading the page (ModelList).
        from caravan.admin.models import MODEL_LIST
        rows, stamp = MODEL_LIST.current()
        h.send_json({"ok": True, "models": rows, "stamp": stamp})
        return

@_route(GET_ROUTES, '/api/hf/token')
def _get_api_hf_token(h, parsed):
        """Whether a Hugging Face token is saved, in masked form

        Answers `{ok, set, masked}`; `masked` keeps at most the last four characters, and
        the token itself is never returned.
        """
        token = admin_state.get("hfToken") or ""
        masked = ("●●●●" + token[-4:]) if len(token) >= 8 else ("set" if token else "")
        h.send_json({"ok": True, "set": bool(token), "masked": masked})
        return

@_route(GET_ROUTES, '/api/settings/export')
def _get_api_settings_export(h, parsed):
        """Export every setting the panel can change as one settings bundle

        `secrets` — boolean; when true the bundle also carries the API keys, the HF token
        and the accounts database, otherwise they are replaced by placeholders or left out,
        and the bundle names which. Answers `{ok, bundle}`. Measured history (token history,
        monitor samples, logs) is never part of it.
        """
        # Everything the panel can change, in one file. `secrets=1` opts into
        # carrying the API keys and the HF token; without it they leave as
        # placeholders and the import puts the local ones back.
        _q = urllib.parse.parse_qs(parsed.query or "")
        _sec = _flag(_q, "secrets")
        _bundle = export_bundle(include_secrets=_sec)
        h.send_json({"ok": True, "bundle": _bundle})
        return

@_route(GET_ROUTES, '/api/settings/backups')
def _get_api_settings_backups(h, parsed):
        """List the copies of the settings taken automatically before each import

        Answers `{ok, backups}`: newest first, at most 20 rows of `{name, bytes, mtime}`; an
        unreadable backup directory gives an empty list.
        """
        # The copies taken automatically before each import, newest first.
        _rows = []
        try:
            for _p in sorted(SETTINGS_BACKUP_DIR.glob("*.json"), reverse=True)[:20]:
                _rows.append({"name": _p.name, "bytes": _p.stat().st_size,
                              "mtime": int(_p.stat().st_mtime)})
        except OSError:
            pass
        h.send_json({"ok": True, "backups": _rows})
        return

@_route(GET_ROUTES, '/api/hf/download/status')
def _get_api_hf_download_status(h, parsed):
        """Progress of one Hugging Face download job

        `job` — the job id a download start returned. Answers `{ok: true, ...}` with
        `status`, `done`, `error`, byte counters and the file in progress, or `{ok: false,
        error: "job not found"}` with status 200 for an unknown id. Jobs live in memory
        only, so a restart forgets them.
        """
        _q2 = urllib.parse.parse_qs(parsed.query or "")
        _jid = (_q2.get("job") or [""])[0].strip()
        with _download_jobs_lock:
            _job = dict(_download_jobs.get(_jid) or {})
        h.send_json({"ok": True, **_job} if _job else {"ok": False, "error": "job not found"})
        return

@_route(GET_ROUTES, '/api/hf/download/jobs')
def _get_api_hf_download_jobs(h, parsed):
        """Unfinished Hugging Face download jobs, plus partial files no job owns

        Running, retrying and failed jobs are listed with their `jobId`; a `.part` file with
        no job behind it comes back as `status: "interrupted"`, and `resumable` says whether
        its manifest survived. Finished and cancelled jobs are not listed (a cancelled job's
        partial is). Answers `{ok, jobs}`.
        """
        _now = time.time()
        with _download_jobs_lock:
            for _k in [k for k, v in _download_jobs.items()
                       if v.get("finished_at") and _now - v["finished_at"] > 300]:
                _download_jobs.pop(_k, None)
            # A cancelled job is over; what it fetched is listed below as an
            # interrupted partial, the row that can be resumed.
            _jobs = [{"jobId": k, **v} for k, v in _download_jobs.items()
                     if v.get("status") not in ("done", "cancelled")]
        # Partials with no running job behind them: a download the service was
        # restarted out from under. Reporting them is the difference between
        # "interrupted at 15 of 39 GB" and a blank panel that reads as success.
        try:
            _jobs += scan_interrupted_downloads(str(models_dir_from_config(parse_config())))
        except Exception:
            pass  # the live list must survive a bad models dir
        h.send_json({"ok": True, "jobs": _jobs})
        return

@_route(GET_ROUTES, '/api/hf/favorites')
def _get_api_hf_favorites(h, parsed):
        """List the repositories starred in the Hugging Face browser

        Answers `{ok, favorites}`, the list exactly as the page last saved it.
        """
        h.send_json({"ok": True, "favorites": admin_state.get("hfFavorites", [])})
        return

@_route(GET_ROUTES, '/api/hf/search')
def _get_api_hf_search(h, parsed):
        """Search Hugging Face for GGUF repositories, most downloaded first

        `q` — search words; a query containing `/` is an exact `author/repo` and answers
        that repository's own record (just `{id}` when Hugging Face cannot give it). `limit`
        — number of results, held to 5 to 100, default 20. Answers `{ok, repos}` with `{id,
        downloads, likes, createdAt, pipelineTag, tags}` per repo, or `{ok: false, error}`
        with status 200 for an empty query or a failed search.
        """
        _q = urllib.parse.parse_qs(parsed.query or "")
        _query = (_q.get("q") or [""])[0].strip()
        _limit = (_q.get("limit") or ["20"])[0]
        h.send_json(hf_search(_query, _limit))
        return

@_route(GET_ROUTES, '/api/hf/files')
def _get_api_hf_files(h, parsed):
        """List a Hugging Face repository's GGUF files, classified by kind and quantization

        `repo` — `author/name`. Answers `{ok, repo, files, lastModified}`; each GGUF file
        has `kind` (`model`, `mmproj`, `mtp` or `vocab`), `quant`, `size`, `date` and `oid`
        (its LFS sha256). A repo with safetensors weights also gets a `safetensors` bundle,
        other files go to `otherFiles`, and a missing or malformed `repo` answers `{ok:
        false, error}` with status 200.
        """
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        h.send_json(hf_list_files(_repo) if _repo else {"ok": False, "error": "missing repo"})
        return

@_route(GET_ROUTES, '/api/hf/model-tree')
def _get_api_hf_model_tree(h, parsed):
        """Quantized variants of a Hugging Face repository, and its base model's siblings

        `repo` — `author/name`. Answers `{ok, repo, quantizations, base, siblings}`: up to
        30 quantized descendants of the repo by downloads and, when it is itself a quant,
        its `base` model and that model's other quants as `siblings`, each as `{id,
        downloads, likes, format}`. A missing or malformed `repo` answers `{ok: false,
        error}` with status 200.
        """
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        h.send_json(hf_model_tree(_repo) if _repo else {"ok": False, "error": "missing repo"})
        return

@_route(GET_ROUTES, '/api/hf/local-check')
def _get_api_hf_local_check(h, parsed):
        """Which GGUF files of a Hugging Face repository are already on disk or in a library

        `repo` — `author/name`. Answers `{ok, localNames, localFiles, libraryFiles}`:
        `localFiles` maps each file name on the controller's models disk to `{size, mtime,
        path}`, and `libraryFiles` maps a name to the libraries holding it, from their last
        measurement (no mount is read). An empty `repo` answers `{ok: false, error}` with
        status 200.
        """
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        h.send_json(hf_local_check(_repo))
        return

@_route(GET_ROUTES, '/api/models/freshness')
def _get_api_models_freshness(h, parsed):
        """Whether the local models still match Hugging Face, with the watcher's settings

        Answers `{ok, checkedAt, repos, watch, prev}`: `repos` is the last comparison
        against Hugging Face (as of `checkedAt`; 0 and empty when never checked) with each
        file's local side measured now. `watch` holds the watcher's settings and `prev` the
        kept previous builds by file path.
        """
        h.send_json({"ok": True, **freshness_report(), "watch": watch_settings(),
                     "prev": prev_overview()})
        return

@_route(GET_ROUTES, '/api/hf/verify')
def _get_api_hf_verify(h, parsed):
        """Progress and result of a sha256 check of a repository's local files

        `job` — a job id from the verify start; without it, `repo` picks that repository's
        newest job. Answers `{ok, job}` with `job: null` when none is known. Progress is
        `bytesDone` of `totalBytes`; per file, `state` is `same`, `differs`, `unknown`
        (Hugging Face gave no hash) or `unreadable`.
        """
        _q = urllib.parse.parse_qs(parsed.query or "")
        h.send_json(verify_status((_q.get("job") or [""])[0].strip(),
                                  (_q.get("repo") or [""])[0].strip()))
        return

@_route(GET_ROUTES, '/api/hf/benchmarks')
def _get_api_hf_benchmarks(h, parsed):
        """Benchmark scores of a GGUF repository, judged by its base model

        `repo` — `author/name`; `force` — skip the on-disk cache (results are kept 3
        months). Scores are looked up for the repo's base model (inferred from its model
        card or name) in model-card results, the Open LLM Leaderboard and Chatbot Arena
        (needs an HF token), with the Artificial Analysis index as a fallback. Answers `{ok,
        repo, data_from, scores, ...}`, or `{ok: false, error}` with status 200 for a
        missing or malformed `repo`.
        """
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        _force = _flag(_q, "force")
        h.send_json(hf_get_benchmarks(_repo, force=_force) if _repo else {"ok": False, "error": "missing repo"})
        return

@_route(GET_ROUTES, '/api/hf/benchmarks/status')
def _get_api_hf_benchmarks_status(h, parsed):
        """Warm-up status of the Open LLM Leaderboard score cache

        Also starts the background load when the cache is empty or older than a day. Answers
        `{ok, loaded, count, loading, age_hours}`; `age_hours` is null until a load has
        finished.
        """
        _ensure_llm_lb()
        h.send_json({"ok": True, **_llm_lb_status()})
        return

@_route(GET_ROUTES, '/api/hf/reference-models')
def _get_api_hf_reference_models(h, parsed):
        """Frontier reference models with their Artificial Analysis Intelligence Index

        `force` — fetch fresh scores from Artificial Analysis now, waiting for them; without
        it, the copy an earlier `force` left (kept 12 hours) or the built-in defaults answer
        at once. Answers `{ok, models, source}` with `models` as `{name, org, slug, aa}` and
        `source` one of `aa`, `cache` or `default`.
        """
        _rfq = urllib.parse.parse_qs(parsed.query or "")
        _rf_force = _flag(_rfq, "force")
        h.send_json(hf_get_reference_models(force=_rf_force))
        return

@_route(GET_ROUTES, '/api/hf/bench-search')
def _get_api_hf_bench_search(h, parsed):
        """Find cached benchmark scores of a model by a fuzzy name match

        `q` — at least three characters of the model name; only results already cached by
        the benchmarks lookup are searched and nothing is fetched. Answers the first match
        as `{ok: true, ...}` with its scores, or `{ok: false}` (with `error` for a too short
        `q`) and status 200.
        """
        _bsq = urllib.parse.parse_qs(parsed.query or "")
        _bname = (_bsq.get("q") or [""])[0].strip()
        h.send_json(hf_bench_search(_bname))
        return

@_route(GET_ROUTES, '/api/models/download')
def _get_api_models_download(h, parsed):
        """Download a model file from the controller's models directory

        `path` — the file's path relative to the configured models directory (`modelsDir`
        of `GET /api/models`). Streams the raw bytes as an attachment; a missing `path`
        answers 400, a path that leaves the directory 403 and a file that is not there 404,
        each with an empty body.
        """
        serve_model_file(h, parsed.query)
        return

@_route(GET_ROUTES, '/api/topology/client-monitor')
def _get_api_topology_client_monitor(h, parsed):
        """nvidia-smi snapshot of a client machine, read through its scout

        `hostId` — the machine (400 when missing, 404 when no scout has reported for it);
        `kind` — only `nvidia-smi`, the default, is supported (400 otherwise). Answers the
        scout's `{kind, ok, output, ...}` snapshot, or `{ok: false, error}` with status 200
        when the scout cannot be reached.
        """
        import urllib.parse as _up
        _q = _up.parse_qs(parsed.query or "")
        _host = (_q.get("hostId") or [""])[0].strip()
        _kind = (_q.get("kind") or ["nvidia-smi"])[0].strip()
        h.send_json(client_monitor(_host, _kind))
        return

@_route(GET_ROUTES, '/api/fleet/llama-update-status')
def _get_api_fleet_llama_update_status(h, parsed):
        """Progress of the llama.cpp update job on a machine with a scout

        `hostId` — the machine (400 when missing, 404 when no scout has reported for it).
        Answers the scout's job record: `running`, `done`, `rc`, `error`, `startedAt`, `tag`
        and the last output `lines`. A scout that cannot be reached gives `{ok: false,
        error}` with status 200.
        """
        import urllib.parse as _up
        _q = _up.parse_qs(parsed.query or "")
        h.send_json(client_llama_update_status((_q.get("hostId") or [""])[0].strip()))
        return

@_route(GET_ROUTES, '/api/fleet/vllm')
def _get_api_fleet_vllm(h, parsed):
        """vLLM install state of one machine with a scout, and the machines to choose from

        `hostId` — the machine to ask; omitted, this controller's own machine. Answers
        `{machines, hostId, pinnedDefault}` (the version a first vLLM start installs) merged
        with the scout's view: `version`, `history` and the install `job`. `ok` is false
        with an `error` when no machine has reported, the id is unknown, its scout is older
        than 2.9.0 or it cannot be reached.
        """
        # vLLM on a machine with a scout (its venv, history, install job) and
        # the machines to choose from; none named = this controller's machine.
        import urllib.parse as _up
        _q = _up.parse_qs(parsed.query or "")
        h.send_json(client_vllm((_q.get("hostId") or [""])[0].strip()))
        return

@_route(GET_ROUTES, '/api/fleet/vllm/update-status')
def _get_api_fleet_vllm_update_status(h, parsed):
        """Progress of the vLLM install job on a machine with a scout

        `hostId` — the machine (400 when missing, 404 when no scout has reported for it).
        Answers the scout's job record: `running`, `done`, `rc`, `error`, `startedAt`, `tag`
        and the last output `lines`. A scout that cannot be reached gives `{ok: false,
        error}` with status 200.
        """
        import urllib.parse as _up
        _q = _up.parse_qs(parsed.query or "")
        h.send_json(client_vllm_update_status((_q.get("hostId") or [""])[0].strip()))
        return

@_route(GET_ROUTES, '/api/fleet/llama-builds')
def _get_api_fleet_llama_builds(h, parsed):
        """Archived llama.cpp builds on a machine with a scout (rollback points)

        `hostId` — the machine (400 when missing, 404 when no scout has reported for it).
        Answers the scout's `{ok, builds}`, newest first, each build with the `id` a restore
        takes. A scout that cannot be reached gives `{ok: false, error}` with status 200.
        """
        import urllib.parse as _up
        _q = _up.parse_qs(parsed.query or "")
        h.send_json(client_llama_builds((_q.get("hostId") or [""])[0].strip()))
        return

@_route(GET_ROUTES, '/api/topology/client-llama/configs')
def _get_api_topology_client_llama_configs(h, parsed):
        """List a machine's saved launch configs, kept on the controller

        `hostId` — the machine (400 when missing). Answers `{ok, hostId, configs}`, each
        `{filename, target, savedAt, name, config, ...}` plus the config's `modelName`,
        `modelPath`, `port`, `ctxSize` and `gpuLayers`. `filename` (`<target>/<file>.json`)
        is what the delete call takes, and `target` is `CPU` or the GPU model the config was
        made for.
        """
        import urllib.parse as _up2
        _q2 = _up2.parse_qs(parsed.query or "")
        _host2 = (_q2.get("hostId") or [""])[0].strip()
        h.send_json(client_llama_configs(_host2))
        return

@_route(GET_ROUTES, '/api/topology/client-llama/list-cache')
def _get_api_topology_client_llama_list_cache(h, parsed):
        """List the GGUF model files cached on a client machine's disk

        `hostId` — the machine (400 when missing, 404 when no scout has reported for it).
        Answers `{ok, hostId, models}` with `{path, sizeBytes}` per file, as its scout
        reports them. When the scout cannot be asked, the answer is `{ok: false, hostId,
        error, models: []}` with status 200.
        """
        import urllib.parse as _up3
        _q3 = _up3.parse_qs(parsed.query or "")
        _host3 = (_q3.get("hostId") or [""])[0].strip()
        h.send_json(client_llama_list_cache(_host3))
        return

@_route(GET_ROUTES, '/api/queue-thresholds')
def _get_api_queue_thresholds(h, parsed):
        """Queue wait thresholds per local proxy port, computed from the queue policy

        Answers `{ok, thresholds}`, the last computation, which is null before the first.
        For each local route with a `clientTimeoutSeconds` budget it gives the seconds at
        which a waiting request overflows to the cloud (`cloudFallbackSec`, only on a route
        with a cloud fallback), preempts (`priorityPreemptSec`) or is aborted
        (`queueAbortSec`), plus the effective percentages and whether each is a per-route
        override.
        """
        h.send_json({"ok": True, "thresholds": QUEUE_THRESHOLDS.latest()})
        return

@_route(GET_ROUTES, '/api/agent-proxies/raw')
def _get_api_agent_proxies_raw(h, parsed):
        """Raw text of the agent proxies config file (agent-proxies.json)

        Answers `{ok, path, content}`; `content` is empty when the file does not exist and a
        short `(unable to read ...)` note when it cannot be read. The text is the file as
        stored, so it includes the routes' `apiKey` values.
        """
        try:
            content = AGENT_PROXY_CONFIG_FILE.read_text(encoding="utf-8") if AGENT_PROXY_CONFIG_FILE.exists() else ""
        except Exception as exc:
            content = f"(unable to read {AGENT_PROXY_CONFIG_FILE}: {exc})"
        h.send_json({"ok": True, "path": str(AGENT_PROXY_CONFIG_FILE), "content": content})
        return

@_route(GET_ROUTES, '/api/cloud-accounts/oauth/status')
def _get_api_cloud_accounts_oauth_status(h, parsed):
        """Progress of a cloud account's OAuth login

        `state` — the state string the login start returned. Answers `{state}` with the
        value `pending`, `done` (plus `email` and a fresh `topology`), `error` (plus
        `error`) or `unknown` for a login it does not hold. A login still pending after 5
        minutes turns into `error` with `timeout`.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        status = oauth_login_status((query.get("state") or [""])[0])
        if status.get("state") == "done":
            status["topology"] = topology_state(refresh_hosts=False)
        h.send_json(status)
        return

@_route(GET_ROUTES, '/api/cloud-accounts/models')
def _get_api_cloud_accounts_models(h, parsed):
        """Live model list of a cloud account, asked of the provider's API

        `id` — the account id. Answers `{ok, models}` sorted by id, each `{id, name}` plus
        `contextLength` when the provider states one. 404 for an unknown account, 400 when
        the account type has no model listing, 502 when the provider fails and 503 while the
        endpoint's circuit breaker is tripped.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        models = fetch_account_models(account_id)
        h.send_json({"ok": True, "models": models})
        return

@_route(GET_ROUTES, '/api/cloud-accounts/subscription-models')
def _get_api_cloud_accounts_subscription_models(h, parsed):
        """Live model list of a ChatGPT subscription account

        `id` — the account id. Answers `{ok, models}` with `{id, name}` for the models
        chatgpt.com lists as visible and supported in the API. 404 for an unknown account,
        400 without a stored OAuth login, 502 when chatgpt.com fails and 503 while the
        endpoint's circuit breaker is tripped.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        models = fetch_subscription_models(account_id)
        h.send_json({"ok": True, "models": models})
        return

@_route(GET_ROUTES, '/api/cloud-accounts/subscription-usage')
def _get_api_cloud_accounts_subscription_usage(h, parsed):
        """Usage limits and credits of a ChatGPT subscription, with the operator's reserve

        `id` — the account id. Answers `{ok, limits, credits, planType, limitReached, ...}`
        from chatgpt.com, each limit with `label`, `remainingPct`, `resetsAt` and
        `windowSeconds`, merged with `reserve`, `reserveKept`, `reserveMax` and
        `reserveReadAt`: the reserve the operator keeps and the proxy's verdict on it.
        Errors are those of the subscription model list: 404, 400, 502 and 503.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        usage = fetch_subscription_usage(account_id)
        # Beside the bars: the operator's reserve and whether the proxy keeps it now.
        from caravan.admin.usage_reserve_desk import UsageReserveDesk
        h.send_json({**usage, **UsageReserveDesk().view(account_id)})
        return

@_route(GET_ROUTES, '/api/cloud-accounts/subscription-resets')
def _get_api_cloud_accounts_subscription_resets(h, parsed):
        """Read available banked resets of one ChatGPT subscription without consuming any

        `id` names an individual account; test aliases share their original list.
        Returns {ok, accountId, usageAccountId, availableCount, credits, pending,
        readAt}. Each credit has id, resetType, status, expiresAt, title,
        description and usable. Pending attempts retain their idempotencyKey and
        creditId. Unknown details/provider failures return 502, never an empty list.
        """
        from caravan.admin.subscription_resets import SubscriptionResetDesk
        query = urllib.parse.parse_qs(parsed.query or "")
        h.send_json(SubscriptionResetDesk().list((query.get("id") or [""])[0]))

@_route(GET_ROUTES, '/api/cloud-accounts/api-costs')
def _get_api_cloud_accounts_api_costs(h, parsed):
        """Official 30-day spend of a cloud account, where the provider offers one

        `id` — the account id. Asks the provider's `/organization/costs` (needs a key with
        the `api.usage.read` scope) and answers `{ok, total, currency, windowDays, days}`
        with `days` as `{t, cost}`; this is spend, not a balance. A refusal or failure comes
        back as `{ok: false, error}` with status 200 (`disabled: true` while the circuit
        breaker is tripped); 404 for an unknown account.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        h.send_json(fetch_account_costs(account_id))
        return

@_route(GET_ROUTES, '/api/cloud-accounts/openrouter-limits')
def _get_api_cloud_accounts_openrouter_limits(h, parsed):
        """Limits and usage of an OpenRouter account's key

        `id` — the account id. Answers `{ok, isFreeTier, label, usage, limit, rateLimit}` as
        OpenRouter reports them for the key. A failure comes back as `{ok: false, error}`
        with status 200 (`authError: true` for an invalid or revoked key, `disabled: true`
        while the circuit breaker is tripped); 404 for an unknown account.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        h.send_json(fetch_openrouter_limits(account_id))
        return

@_route(GET_ROUTES, '/api/cloud-accounts/proxy-spend')
def _get_api_cloud_accounts_proxy_spend(h, parsed):
        """Spend through the proxy over the last 30 days, per cloud account and model

        Answers `{ok, spend}` keyed by account id, each with `total`, `requests`,
        `promptTokens`, `completionTokens`, `windowDays` and a `byModel` list. It is the
        proxy's own estimate — logged tokens times the LiteLLM price table, so a model
        missing there adds 0 — not the provider's bill.
        """
        h.send_json({"ok": True, "spend": cloud_spend_summary()})
        return

@_route(GET_ROUTES, '/api/usage-stats')
def _get_api_usage_stats(h, parsed):
        """Usage and spend statistics over the proxy's request logs

        `days` — window length, 1 to 365, default 30 (a non-number counts as 30); it reaches
        back only as far as the logs are kept. Answers `{ok, windowDays, rate, cloud, local,
        daily}`: cloud spend per account and model, local tokens with what they would have
        cost at the manual local rate, and a per-day series.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        try:
            days = int((query.get("days") or ["30"])[0])
        except ValueError:
            days = 30
        h.send_json(usage_stats(days))
        return

@_route(GET_ROUTES, '/api/local-pricing')
def _get_api_local_pricing(h, parsed):
        """The manual price per million tokens used to value local model usage

        Answers `{ok, rate}` with `rate` as `{inputPer1M, outputPer1M}`, or `{}` when none
        was set. It only prices the estimate of what local tokens would have cost in the
        cloud.
        """
        h.send_json({"ok": True, "rate": admin_state.get("localPricing") or {}})
        return

@_route(GET_ROUTES, '/api/api-pricing')
def _get_api_api_pricing(h, parsed):
        """Manual per-model price overrides for cloud API usage

        Answers `{ok, pricing}`, a map from model name to `{inputPer1M, outputPer1M}` in
        dollars per million tokens (`{}` when there are none). An override beats the LiteLLM
        price table in the usage statistics.
        """
        h.send_json({"ok": True, "pricing": admin_state.get("apiPricing") or {}})
        return

@_route(GET_ROUTES, '/api/token-history')
def _get_api_token_history(h, parsed):
        """Token generation and prompt speed of completed proxy requests

        `port` — only that proxy port's requests (wins over `client`); `client` — only that
        client IP; `range` — `1h`, `12h` or `24h`, anything else returns everything kept (14
        days by default). Answers `{samples}`, one row per completed request with generated
        tokens: `t`, `promptTps`, `evalTps`, `promptTokens`, `evalTokens`, `promptMs`,
        `genMs`, `cacheTokens`, `finish`, `port`, `route` and `client`.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        h.send_json({
            "samples": token_history_query(
                (query.get("client") or [""])[0].strip(),
                (query.get("range") or ["all"])[0].strip(),
                port=(query.get("port") or [""])[0].strip() or None,
            ),
        })
        return

@_route(GET_ROUTES, '/api/gpu-driver')
def _get_api_gpu_driver(h, parsed):
        """NVIDIA driver state of the controller's machine: running, installed, available

        Answers `{ok, running, installed, available, updateAvailable, rebootRequired,
        secureBoot, moduleRejected, ...}` from a copy kept for 2 minutes. `running` is the
        version in the kernel and `installed` the newest driver package; `rebootRequired`
        covers both a driver switch waiting for a reboot and the OS's own pending reboot.
        `moduleRejected` means Secure Boot kept an installed driver from loading.
        """
        h.send_json(driver_status())
        return

@_route(GET_ROUTES, '/api/agent-proxy-model-card')
def _get_api_agent_proxy_model_card(h, parsed):
        """Ask a proxy port what it reports on /v1/models, as its clients read it

        `port` is the proxy route's port: 400 if it is not a number, 404 if no route has it.
        The controller asks the port itself, so the route's API key never leaves it (`keyed`
        says whether the port wants one); a port that does not answer still gives a 200
        answer with `ok: false`, `status` and `error`. The answer also carries `tookMs`, the
        parsed `entries` (id, window sizes, aliases) and the `raw` body.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        h.send_json(proxy_model_card((query.get("port") or [""])[0]))
        return

@_route(GET_ROUTES, '/api/agent-proxy-logs')
def _get_api_agent_proxy_logs(h, parsed):
        """Proxy request log of one day, newest first, filterable by port, route, client or errors

        `date` is YYYY-MM-DD (default: the newest day logged), `limit` caps the rows at
        1-2000 (default 200), `since` keeps only the last N minutes of that day, and
        `event`, `port`, `route` (label substring) and `client` (exact IP) filter the rows.
        `errors=1` keeps failed requests, `slim=1` drops the bulky queue and active
        snapshots, and `summary=1` answers per-port counters (`total`, `errors`, `byKind`,
        `topClient`) instead of rows. Answers `{date, dates, rows, limit}` (`dates` lists
        the days that have a log); 400 for a malformed `date`, `port` or `since`.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        h.send_json(load_agent_proxy_logs(
            (query.get("date") or [""])[0],
            (query.get("limit") or ["200"])[0],
            (query.get("event") or [""])[0],
            (query.get("port") or [""])[0],
            (query.get("route") or [""])[0],
            (query.get("client") or [""])[0],
            _flag(query, "errors"),
            _flag(query, "slim"),
            _flag(query, "summary"),
            (query.get("since") or [""])[0],
        ))
        return

@_route(GET_ROUTES, '/api/proxy-daily-stats')
def _get_api_proxy_daily_stats(h, parsed):
        """Per-route request counts for one day of the proxy log

        `date` is YYYY-MM-DD (default: today). Each route in `routes` has `total` requests
        received, `failed` (blocked, 5xx, stopped or timed out) and `paused` (turned away
        because the route was paused or draining); a day with no log has no routes.
        """
        query = urllib.parse.parse_qs(parsed.query or "")
        h.send_json(proxy_daily_stats((query.get("date") or [""])[0] or None))
        return

@_route(GET_ROUTES, '/api/model-pricing')
def _get_api_model_pricing(h, parsed):
        """Model prices per 1M tokens: the LiteLLM table plus the operator's manual overrides

        Answers `{ok, pricing}` keyed by model name, each entry `{inputPer1M, outputPer1M,
        provider}`. The LiteLLM table is cached for 24 hours and is empty when it cannot be
        fetched; a manual API price replaces the table's price for that model, or adds the
        model with provider `manual`.
        """
        # LiteLLM community table overlaid with the manual apiPricing overrides,
        # so a hand-entered price shows up next to the model everywhere the UI
        # displays price tags — not only in the spend accounting.
        pricing = dict(fetch_model_pricing())
        for model, row in (admin_state.get("apiPricing") or {}).items():
            base = dict(pricing.get(model) or {})
            base["inputPer1M"] = row.get("inputPer1M", 0)
            base["outputPer1M"] = row.get("outputPer1M", 0)
            base.setdefault("provider", "manual")
            pricing[model] = base
        h.send_json({"ok": True, "pricing": pricing})
        return

@_route(GET_ROUTES, '/api/state')
def _get_api_state(h, parsed):
        """Composite state of the controller: launch config, models, services, hardware, llama.cpp

        Heavy: every call runs several local commands (systemctl, journalctl, git,
        llama-server), so read it once on page load, not on a timer. Carries `config` with
        its `fields` and `help`, `models` with `modelsStamp`, `service`, `runtime`, `cpu`,
        `gpu`, `memory`, `llamaCpp`, `logs` and `projectGit`.
        """
        h.send_json(state())
        return

@_route(GET_ROUTES, '/api/project-git')
def _get_api_project_git(h, parsed):
        """Git branch, head commit and dirty-file count of the controller's own checkout

        Much cheaper than `/api/state`, and what the board polls. Answers `{ok, branch,
        head, dirtyCount, error}`; an install without git (the Docker image) reports branch
        `docker` and the commit baked into it.
        """
        # The board's live beat reads only this: the git chip. It fetched the
        # whole /api/state for it — every 1.5 s per open tab, two llama-server
        # launches, a dozen git/systemctl/journalctl runs and probes of the
        # controller's absent single server. The classic page, which read the
        # rest, went in step 6.9.
        h.send_json(project_git_info())
        return

@_route(GET_ROUTES, '/api/controller-info')
def _get_api_controller_info(h, parsed):
        """What the controller's machine runs: services, git checkout, Python and models disk

        Answers `{ok, appVersion, python, container, projectGit, services, disk, models,
        time}`. `services` gives the admin and proxy units' systemd state, `disk` the models
        directory's filesystem (`totalGb`, `freeGb`, `usedGb`), and `models` the count and
        size of the GGUF files under it.
        """
        h.send_json(controller_info())
        return

@_route(GET_ROUTES, '/api/models/disk')
def _get_api_models_disk(h, parsed):
        """Free and total space of the disk holding the controller's models directory

        Answers `{ok, path, totalGb, freeGb}`, or `ok: false` with `error` when the
        directory cannot be read.
        """
        h.send_json(models_disk())
        return

@_route(GET_ROUTES, '/metrics')
def _get_metrics(h, parsed):
        """Prometheus metrics: machines, cells, GPUs, models disk and per-route traffic

        Plain text in the Prometheus exposition format (version 0.0.4), not JSON; every
        series is prefixed `caravan_`.
        """
        data = build_metrics_text().encode("utf-8")
        h.send_response(200)
        h.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return

@_route(GET_ROUTES, '/api/cell-assets')
def _get_api_cell_assets(h, parsed):
        """Manifest of the cell server files this controller hands out, with hashes

        Answers `{assets, runners}`: each file's `sha256`, `size` and `executable` flag, and
        the files each runner needs, so a scout fetches only what it does not already match.
        """
        # Manifest of the cell servers this controller serves, hashed so a scout
        # fetches only what it does not already match.
        h.send_json(cell_assets_manifest())
        return

@_route(GET_ROUTES, '/api/cell-assets/file')
def _get_api_cell_assets_file(h, parsed):
        """Download one cell server or launcher file, raw

        `name` must be a file listed in the manifest (`/api/cell-assets`): 404 for anything
        else, 500 when a listed file is missing on the controller. Answered as
        `application/octet-stream`.
        """
        import urllib.parse as _upa
        _qa = _upa.parse_qs(parsed.query or "")
        name = (_qa.get("name") or [""])[0].strip()
        data = cell_asset_bytes(name)          # raises 404 for anything unlisted
        h.send_response(200)
        h.send_header("Content-Type", "application/octet-stream")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return

@_route(GET_ROUTES, '/api/models/unused')
def _get_api_models_unused(h, parsed):
        """List every model file on the controller's disk with whether a cell uses it

        Each row has `path`, `sizeGb`, `ageDays`, `referenced`, `referencedBy` (host:port of
        the cells that name it), `readBy` (of those, the ones running, or on a machine that
        does not report) and `group` (the parts of a multi-part GGUF share one). Whisper and
        safetensors folders are one row with a `kind`; the answer adds `unusedCount` and
        `unusedGb`, and is `ok: false` when the models directory is missing.
        """
        h.send_json(list_unused_models())
        return

@_route(GET_ROUTES, '/api/model-stores')
def _get_api_model_stores(h, parsed):
        """List the model stores (the controller's disk and its libraries) with their measured state

        `force=1` measures again instead of reusing the last 15 seconds. Each store has
        `id`, `name`, `path`, `role` (`local` or `library`), `state` (`ok`, `low-space`,
        `read-only`, `foreign`, `not-mounted`, `missing` or `unknown`), `detail`, and `free`
        and `total` bytes when it is really there; a store that is not `ok` also carries
        `mount` facts. Every look happens in a child process with an 8 s deadline, so a dead
        NAS answers `unknown` instead of hanging the request.
        """
        # Every look inside a store happens in a child process with a
        # deadline (caravan/admin/model_stores.py): a dead NAS answers
        # "unknown" here instead of holding this request thread.
        from caravan.admin.model_stores import registry
        import urllib.parse as _upa
        h.send_json({"ok": True, "stores": registry().statuses(
            force=_flag(_upa.parse_qs(parsed.query or ""), "force"))})
        return

@_route(GET_ROUTES, '/api/model-stores/moves')
def _get_api_model_stores_moves(h, parsed):
        """List the model move jobs, newest first, with progress per file

        Read from memory, so it never waits on a store. Each job has `status` (`queued`,
        `running`, `waiting`, `done`, `failed` or `cancelled`) with `reason`, byte totals,
        and a row per file or model folder with its `phase`, `done`, `size`, `note` and
        `removeIn` (seconds until the original is deleted once its copy is proven).
        """
        # From memory: the mover's thread is the only one that touches the
        # library, and a request never waits for it.
        from caravan.admin.store_moves import runner
        h.send_json({"ok": True, "jobs": runner().summaries()})
        return

@_route(GET_ROUTES, '/api/model-stores/files')
def _get_api_model_stores_files(h, parsed):
        """List the GGUF files and model folders each library holds

        `force=1` measures the libraries again instead of reusing the last look. Answers
        `{ok, libraries}`: each library has `id`, `name`, `state`, `path` and `files` (path
        from the library root, `size`, `ageDays`, and `kind` for a model folder), capped at
        5000 entries of each kind with the rest counted in `more`. A library that is not
        there lists no files and says its state.
        """
        # The libraries' GGUF files for the tree on /models — from the same
        # look (a child process with a deadline) that counts them for the panel.
        from caravan.admin.model_stores import registry
        import urllib.parse as _upa
        h.send_json({"ok": True, "libraries": registry().library_files(
            force=_flag(_upa.parse_qs(parsed.query or ""), "force"))})
        return

@_route(GET_ROUTES, '/api/llamacpp')
def _get_api_llamacpp(h, parsed):
        """llama.cpp build on the controller's machine, compared with the newest upstream release

        Always asks the upstream remote (git ls-remote, up to 30 s each), so it can be slow.
        The answer names the binary (`binary`, `binaryMtime`, `version`) and its `git`
        state: local branch, head and dirty counts, plus `upstreamBuild` (the newest `bNNNN`
        tag) and its commit.
        """
        h.send_json(llama_cpp_info(fetch_remote=True))
        return

@_route(GET_ROUTES, '/api/llamacpp/update-status')
def _get_api_llamacpp_update_status(h, parsed):
        """Progress of the controller's running build or install job

        Only one build or install job runs at a time (a llama.cpp update, an archived-build
        restore or a GPU driver install) and they all report here: `running`, `done`, `rc`,
        `error`, `startedAt` and the last 200 output `lines`. `tag` says which job: the
        requested llama.cpp release (empty for the latest), `restore:<build id>` or
        `driver:<package>`.
        """
        h.send_json(llama_update_status())
        return

@_route(GET_ROUTES, '/api/llamacpp/builds')
def _get_api_llamacpp_builds(h, parsed):
        """List the archived llama.cpp builds on the controller, newest first (rollback points)

        Answers `{ok, builds, keep}`: each build is its archived `meta.json` plus an `id`
        (what `POST /api/llamacpp/restore` takes), and `keep` is how many builds the archive
        retains.
        """
        h.send_json(llama_builds_list())
        return

@_route(GET_ROUTES, '/board')
def _get_root(h, parsed):
        """The board page (HTML): the fleet topology"""
        h.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/', '/index.html')
def _get_root_redirect(h, parsed):
        """Redirect `/` and `/index.html` to the board page at `/board`"""
        _redirect(h, "/board")
        return

@_route(GET_ROUTES, '/hf')
def _get_hf(h, parsed):
        """Hugging Face browser page (HTML): search, download and verify GGUF models"""
        h.send_file(STATIC_DIR / "hf.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/router')
def _get_router_alias(h, parsed):
        """Redirect the old /router address to /kanban, keeping the query string"""
        # Kept as a redirect, not a route: an old bookmark still lands, and the
        # address bar ends up saying which page this actually is.
        _redirect(h, "/kanban" + (("?" + parsed.query) if parsed.query else ""))
        return

@_route(GET_ROUTES, '/kanban')
def _get_kanban(h, parsed):
        """Kanban page (HTML): the router canvas

        `id` in the query, read by the page and not by the server, picks the router (default
        `router:default`).
        """
        h.send_file(STATIC_DIR / "kanban.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/system')
def _get_system(h, parsed):
        """System page (HTML): controller, llama.cpp, GPU driver, diagnostics, security, settings"""
        h.send_file(STATIC_DIR / "system.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/models')
def _get_models(h, parsed):
        """Models page (HTML): the model tree across the disk and libraries, moves and cleanup"""
        h.send_file(STATIC_DIR / "models.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/favicon.svg', '/favicon.ico')
def _get_favicon_svg(h, parsed):
        """Site icon (SVG), served at both /favicon.svg and /favicon.ico"""
        h.send_file(STATIC_DIR / "favicon.svg", "image/svg+xml")
        return


class PrefixRoute:
    """A GET route that owns every path under a prefix; the rest of the path is
    its one parameter, named so the API description can say what it is.
    Prefix routes are checked before the exact ones, in order."""

    def __init__(self, prefix, handler, param):
        self.prefix, self.handler, self.param = prefix, handler, param

    @property
    def template(self):
        return f"{self.prefix}{{{self.param}}}"

    def matches(self, path):
        return path.startswith(self.prefix)


GET_PREFIX_ROUTES = [
    PrefixRoute('/api/monitor/', _get_api_monitor, "kind"),
    PrefixRoute('/js/', _get_static_subdir, "file"),
    PrefixRoute('/css/', _get_static_subdir, "file"),
]


@_route(POST_ROUTES, '/api/settings/export')
def _post_api_settings_export(h, parsed, body):
        """Export the controller's settings as one JSON bundle, secrets only on request

        Answers `{ok, bundle}`, which holds the controller config, the board state
        (topology, cells, schedules), the proxy routes, cloud providers and the model
        catalog. Without `secrets` the route API keys and the HF token become placeholders
        (named in `redacted`) and the accounts database and cloud keys are left out. With
        `secrets` they travel, and `passphrase` locks the accounts database and cloud keys
        with AES-256-GCM (400 if this host lacks the `cryptography` package).
        """
        # POST, not GET with a query parameter: a passphrase in a URL lands in
        # logs, in history and in a referrer. Same answer as the GET form
        # otherwise.
        _sec = bool(body.get("secrets"))
        _pass = str(body.get("passphrase") or "")
        _bundle = export_bundle(include_secrets=_sec)
        if _pass:
            _bundle = encrypt_credentials(_bundle, _pass)
        h.send_json({"ok": True, "bundle": _bundle})
        return

@_route(POST_ROUTES, '/api/settings/import')
def _post_api_settings_import(h, parsed, body):
        """Restore settings from an exported bundle, or preview what a restore would change

        `bundle` is an export from this API, `passphrase` unlocks credentials the bundle
        carries locked, and `dryRun` only lists the changes (`changes`: `replace`, `same`,
        `skip` or `locked` per section) and writes nothing. A real restore first saves the
        current settings to a `backup` file, then overwrites every section the bundle
        carries and answers `{ok, written, skipped, backup}`. A bad or missing bundle, or a
        wrong passphrase, is a 200 answer with `ok: false` and `error`.
        """
        # dryRun answers "what would this change" before anything is written —
        # a restore that surprises the operator is the failure mode worth
        # designing against, since the reason to restore is usually a surprise.
        _bundle = body.get("bundle")
        if not isinstance(_bundle, dict):
            h.send_json({"ok": False, "error": "no settings bundle in the request"})
            return
        try:
            if body.get("dryRun"):
                h.send_json({"ok": True, "dryRun": True, **preview_import(_bundle)})
                return
            _res = apply_bundle(_bundle, str(body.get("passphrase") or ""))
            h.send_json({"ok": True, **_res})
        except AppError as exc:
            h.send_json({"ok": False, "error": str(exc)})
        return

@_route(POST_ROUTES, '/api/hf/download')
def _post_api_hf_download(h, parsed, body):
        """Start a background download of GGUF files from a Hugging Face repo

        `repo` is the Hugging Face repo id and `files` lists `{path, name, size, destDir}`
        with `destDir` relative to the models directory. Answers `{ok, jobId}` (the running
        job's id when the same files are already downloading); without `replace: true`, a
        file that already exists on disk starts nothing and the answer is `{ok: false, code:
        exists, files}`. Other refusals (missing `repo` or `files`, an invalid `destDir`)
        are also 200 with `ok: false` and `error`.
        """
        _repo = str(body.get("repo") or "").strip()
        _files = body.get("files") or []
        if not _repo or not _files:
            h.send_json({"ok": False, "error": "missing repo or files"})
            return
        for _f in _files:
            _dd = str(_f.get("destDir") or "")
            if ".." in _dd or _dd.startswith("/"):
                h.send_json({"ok": False, "error": "invalid destDir"})
                return
        _models_dir = str(models_dir_from_config(parse_config()))
        # Writing over a model that is already on disk needs a yes: the page
        # asks, then sends replace:true. Without it the answer names the files,
        # instead of starting a job that ends by replacing them.
        if not truthy(body.get("replace")):
            _taken = replaces_on_disk(_files, _models_dir)
            if _taken:
                h.send_json({"ok": False, "code": "exists", "files": _taken,
                             "error": "already on disk: " + ", ".join(_taken)})
                return
        _token = admin_state.get("hfToken") or ""
        _jid = start_hf_download(_repo, _files, _models_dir, _token)
        h.send_json({"ok": True, "jobId": _jid})
        return

@_route(POST_ROUTES, '/api/models/freshness/check')
def _post_api_models_freshness_check(h, parsed, body):
        """Compare the local model files with Hugging Face now

        Runs even when the daily auto-check is off; with auto-download on, files that differ
        start being replaced at once. Answers the fresh report: `checkedAt` and, per
        repository in `repos`, each file's `state` (`same`, `size`, `date` or `unknown`),
        plus `checked`, `unreachable`, `differs` and `fetched`.
        """
        # A pressed button is a direct request: reach the network even with
        # the checkbox off.
        h.send_json({"ok": True, **check_pass(force=True), **freshness_report()})
        return

@_route(POST_ROUTES, '/api/models/staged/download')
def _post_api_models_staged_download(h, parsed, body):
        """Download the newer Hugging Face build of a local model file over it

        `file` is the file's path relative to the models directory, as named in the last
        freshness report. The new build is written as a partial file and swapped in when
        whole, so a running cell keeps its loaded weights until it restarts; with the
        keep-previous setting on, the old build stays as `<file>.prev`. Answers `{ok, jobId,
        file, path, prev}`, or 200 with `ok: false` and `error` when the file is not in the
        report, has nothing newer, is gone, or the disk lacks room.
        """
        try:
            h.send_json(start_update(str((body or {}).get("file") or "")))
        except AppError as exc:
            h.send_json({"ok": False, "error": str(exc)})
        return

@_route(POST_ROUTES, '/api/models/staged/revert')
def _post_api_models_staged_revert(h, parsed, body):
        """Put back the previous build of a model file that a download replaced

        `file` is the path relative to the models directory, as named in the last freshness
        report. It needs the `<file>.prev` copy that the keep-previous setting leaves; the
        newer file is discarded, since Hugging Face still has it. Answers `{ok, restored}`,
        or 200 with `ok: false` and `error` when no previous build was kept or the file is
        not in the report.
        """
        try:
            h.send_json(restore_prev(live_path_for(str((body or {}).get("file") or ""))))
        except AppError as exc:
            h.send_json({"ok": False, "error": str(exc)})
        return

@_route(POST_ROUTES, '/api/models/staged/drop-prev')
def _post_api_models_staged_drop_prev(h, parsed, body):
        """Delete the kept previous build of a model file to free its space

        `file` is the path relative to the models directory, as named in the last freshness
        report. Answers `{ok, freed}` with the bytes freed (0 when no previous build was
        kept), or 200 with `ok: false` and `error` when the file is not in the report.
        """
        try:
            h.send_json(drop_prev(live_path_for(str((body or {}).get("file") or ""))))
        except AppError as exc:
            h.send_json({"ok": False, "error": str(exc)})
        return

@_route(POST_ROUTES, '/api/models/freshness/watch')
def _post_api_models_freshness_watch(h, parsed, body):
        """Save the daily Hugging Face freshness-check settings

        `check` looks once a day, `at` is the local time (`HH:MM`, default the saved one),
        `download` replaces files that differ (and implies `check`), and `keepPrev` keeps
        the previous build as `.prev`; a flag left out of the body turns that option off.
        400 for an `at` that is not `HH:MM`. Answers `{ok, watch}` with the saved settings
        and the outcome of the last check.
        """
        h.send_json({"ok": True, "watch": set_watch_settings(body or {})})
        return

@_route(POST_ROUTES, '/api/model-stores/add')
def _post_api_model_stores_add(h, parsed, body):
        """Add a library (a folder such as a mounted NAS share) to the model stores

        `path` must be absolute, `name` is an optional label, and `force` accepts a bare
        directory that is not a mount point. Unless the folder already carries a library
        mark it gets a hidden `.caravan-store.json` written into its root, and an existing
        mark is adopted. Answers `{ok, store}` (with `adopted`); a refusal is 200 with `ok:
        false`, `error` and `code` (`no-path`, `not-absolute`, `duplicate`, `nested`,
        `missing`, `unreachable`, `not-a-mount`, `not-writable`).
        """
        # A refusal carries its code: the page offers a second, confirmed try
        # for a bare directory ("not-a-mount") and for nothing else.
        from caravan.admin.model_stores import StoreRefused, registry
        _b = body or {}
        try:
            h.send_json({"ok": True, "store": registry().add(
                _b.get("path"), _b.get("name"), force=truthy(_b.get("force")))})
        except StoreRefused as exc:
            h.send_json({"ok": False, "error": str(exc), "code": exc.code})
        return

@_route(POST_ROUTES, '/api/model-stores/repath')
def _post_api_model_stores_repath(h, parsed, body):
        """Point a library at another path on this host

        `id` names the library and `path` is the new absolute folder, which must carry the
        same library mark. Answers `{ok, store}`; a refusal is 200 with `ok: false`, `error`
        and `code` (`other-library`, `not-a-mount`, `unknown-id`, `builtin` for the
        controller's own disk, and the checks Add makes).
        """
        # The share moved, or its mount point did. The library keeps its
        # identity: the new folder must carry the same mark, and the refusal
        # says so by code, so the page can offer Add instead.
        from caravan.admin.model_stores import StoreRefused, registry
        _b = body or {}
        try:
            h.send_json({"ok": True, **registry().repath(_b.get("id"), _b.get("path"))})
        except StoreRefused as exc:
            h.send_json({"ok": False, "error": str(exc), "code": exc.code})
        return

@_route(POST_ROUTES, '/api/model-stores/remove')
def _post_api_model_stores_remove(h, parsed, body):
        """Take a library off the model stores list; its files and mark stay

        `id` names the library. Answers `{ok, removed}`; a refusal is 200 with `ok: false`,
        `error` and `code` (`unknown-id`, or `builtin` for the controller's own disk).
        """
        # Off the list only: the library's files and its mark stay where they are.
        from caravan.admin.model_stores import StoreRefused, registry
        try:
            h.send_json({"ok": True, **registry().remove((body or {}).get("id"))})
        except StoreRefused as exc:
            h.send_json({"ok": False, "error": str(exc), "code": exc.code})
        return

@_route(POST_ROUTES, '/api/model-stores/move')
def _post_api_model_stores_move(h, parsed, body):
        """Start moving models between stores: copy, verify by sha256, then delete the original

        `files` are paths relative to the source store's root (a picked part brings its
        whole multi-part group, a model folder moves whole), `to` is the target store id and
        `from` the source store id (default: the controller's disk). Everything is checked
        before a byte moves; the answer is `{ok, job}` and the job then runs in the
        background (follow it with `GET /api/model-stores/moves`). A refusal is 200 with
        `ok: false`, `error` and `code` (`empty`, `same-store`, `unknown-file`, `in-use`,
        `busy`, `no-room`, `target-<state>` and others).
        """
        # Everything is checked before a byte moves (caravan/admin/store_moves.py);
        # a refusal carries its code, like the stores' own.
        from caravan.admin.store_moves import MoveRefused, runner
        _b = body or {}
        _files = _b.get("files") if isinstance(_b.get("files"), list) else []
        try:
            # "from" is the store the files sit in now — the models disk unless
            # the page says otherwise (a move back from a library, or between two).
            h.send_json({"ok": True, "job": runner().start(_files, str(_b.get("to") or ""),
                                                           str(_b.get("from") or "") or None)})
        except MoveRefused as exc:
            h.send_json({"ok": False, "error": str(exc), "code": exc.code})
        return

@_route(POST_ROUTES, '/api/model-stores/moves/cancel')
def _post_api_model_stores_moves_cancel(h, parsed, body):
        """Cancel a model move job

        `id` is the job's id. It stops between blocks: the file being carried stays at the
        source and its unfinished copy at the target is deleted, and a job still in line
        ends at once. Answers `{ok, job}`, or 200 with `ok: false` and code `unknown-job`.
        """
        # Stopping deletes nothing here: the file in progress stays, its
        # unfinished copy in the library goes.
        from caravan.admin.store_moves import MoveRefused, runner
        try:
            h.send_json({"ok": True, "job": runner().cancel((body or {}).get("id"))})
        except MoveRefused as exc:
            h.send_json({"ok": False, "error": str(exc), "code": exc.code})
        return

@_route(POST_ROUTES, '/api/hf/verify')
def _post_api_hf_verify(h, parsed, body):
        """Start hashing a repo's local files against the sha256 Hugging Face reports

        `repo` is the Hugging Face repo id; the file list comes from Hugging Face, and only
        that repo's files already on the models disk are hashed, which takes minutes for
        large ones. Answers `{ok, jobId}` (the running job's id if the repo is already being
        verified); poll `GET /api/hf/verify` with `job` or `repo`. Failures (invalid repo,
        Hugging Face unreachable, nothing of the repo on disk) are 200 with `ok: false` and
        `error`.
        """
        # Hashing a terabyte on someone else's say-so is out of the question:
        # the file list comes from HF by repository name, not from the request body.
        _repo = str(body.get("repo") or "").strip()
        _listing = hf_list_files(_repo)
        if not _listing.get("ok"):
            h.send_json(_listing)
            return
        _local = hf_local_check(_repo)
        try:
            _jid = start_verify(_repo, _listing.get("files") or [],
                                _local.get("localFiles") or {})
        except AppError as exc:
            h.send_json({"ok": False, "error": str(exc)})
            return
        h.send_json({"ok": True, "jobId": _jid})
        return

@_route(POST_ROUTES, '/api/hf/download/cancel')
def _post_api_hf_download_cancel(h, parsed, body):
        """Cancel a running Hugging Face download job

        `jobId` names the job. The transfer stops where it is and the bytes fetched so far
        stay as a resumable partial. Answers `{ok, jobId}`, or 200 with `ok: false` and
        `error` for a missing `jobId` or a job that is unknown or already finished.
        """
        # Stops the transfer where it is; the bytes stay as a resumable partial.
        _jid = str((body or {}).get("jobId") or "").strip()
        if not _jid:
            h.send_json({"ok": False, "error": "missing jobId"})
            return
        _job = cancel_hf_download(_jid)
        if _job is None:
            h.send_json({"ok": False, "error": "job not found or already finished"})
            return
        h.send_json({"ok": True, "jobId": _jid})
        return

@_route(POST_ROUTES, '/api/hf/download/resume')
def _post_api_hf_download_resume(h, parsed, body):
        """Resume an interrupted Hugging Face download from its partial file

        `destDir` (relative to the models directory) and `name` identify the partial, as
        listed among the interrupted rows of `GET /api/hf/download/jobs`. The repo and file
        are read from the partial's manifest. Answers `{ok, jobId}`, or 200 with `ok: false`
        and `error` for missing fields, an invalid `destDir` or a partial without a
        manifest.
        """
        _dd = str(body.get("destDir") or "").strip()
        _name = str(body.get("name") or "").strip()
        if not _dd or not _name:
            h.send_json({"ok": False, "error": "missing destDir or name"})
            return
        _models_dir = str(models_dir_from_config(parse_config()))
        _token = admin_state.get("hfToken") or ""
        try:
            _jid = resume_interrupted_download(_models_dir, _token, _dd, _name)
        except ValueError as exc:
            h.send_json({"ok": False, "error": str(exc)})
            return
        h.send_json({"ok": True, "jobId": _jid})
        return

@_route(POST_ROUTES, '/api/hf/token')
def _post_api_hf_token(h, parsed, body):
        """Save the Hugging Face access token (an empty token clears it)

        `token` is used for Hugging Face API calls and downloads; every save clears the
        cached Hugging Face responses. Answers `{ok, set, masked}`, where `masked` shows at
        most the last four characters; the token itself is never returned.
        """
        token = str(body.get("token") or "").strip()
        admin_state["hfToken"] = token
        _hf_cache.clear()
        save_admin_state()
        masked = ("●●●●" + token[-4:]) if len(token) >= 8 else ("set" if token else "")
        h.send_json({"ok": True, "set": bool(token), "masked": masked})
        return

@_route(POST_ROUTES, '/api/hf/favorites')
def _post_api_hf_favorites(h, parsed, body):
        """Replace the saved list of starred Hugging Face repos

        `favorites` is the whole new list of records (`id` plus optional counts and tags)
        and replaces the old one. A body without a `favorites` list changes nothing but
        still answers `{ok: true}`.
        """
        favs = body.get("favorites")
        if isinstance(favs, list):
            admin_state["hfFavorites"] = favs
            save_admin_state()
        h.send_json({"ok": True})
        return

@_route(POST_ROUTES, '/api/aa-scores')
def _post_api_aa_scores(h, parsed, body):
        """Look up Artificial Analysis Intelligence Index scores for model ids

        `models` is a list of ids (only the first 400 are used) and `fetch: false` answers
        from what is already known without visiting Artificial Analysis pages. Answers `{ok,
        scores, misses}`: `misses` are ids confirmed to have no page, and an id in neither
        was skipped by the cap of 12 page fetches per call, so ask again for it. A `models`
        that is not a list is a 200 answer with `ok: false` and `error`.
        """
        _ids = body.get("models")
        if not isinstance(_ids, list):
            h.send_json({"ok": False, "error": "models must be a list"})
            return
        h.send_json(hf_get_aa_scores([str(m) for m in _ids][:400],
                                         do_fetch=body.get("fetch", True) is not False))
        return

@_route(POST_ROUTES, '/api/config')
def _post_api_config(h, parsed, body):
        """Save the controller's own launch config (models directory, defaults for new cells)

        `config` replaces the whole saved config and is written into the controller's
        `start-server.sh`, so send it complete: the `config` of `/api/state` with the change
        made. 400 for an invalid config, such as a missing `MODEL_FILE` or a non-numeric
        `PORT`. Answers `{ok, backup, state}`, where `state` is the fresh `/api/state`
        payload and `backup` is always null.
        """
        # The controller's own settings (the models directory, the defaults a
        # new cell starts from). A cell's config is saved on its slot
        # (/api/topology/server-cell/save-config); the controller runs none.
        backup = save_config(body.get("config") or {})
        h.send_json({"ok": True, "backup": backup, "state": state()})
        return

@_route(POST_ROUTES, '/api/llama-command-preview')
def _post_api_llama_command_preview(h, parsed, body):
        """Preview the llama-server command line that a launch config would run

        `config` is the launch config (fields such as `MODEL_FILE`). `tokens` is the
        argument list with the binary first, `command` the same joined by spaces, and
        `owners` the config field behind each token (null when none). A config that cannot
        be built answers `ok: false` with an `error` and empty `tokens`, still with status
        200.
        """
        cfg = body.get("config") if isinstance(body.get("config"), dict) else {}
        # The preview says what this cell runs, so it reads the model from
        # wherever it lives — the library included. Without waiting: the editor
        # asks again on every keystroke, and a NAS that is thinking must not
        # hold up a person typing.
        from caravan.admin.model_locator import current_locations
        where = current_locations(wait=False)

        def build(config, **kw):
            return build_local_llama_command(config, locations=where, **kw)

        try:
            tokens = build(cfg)
        except AppError as exc:
            h.send_json({"ok": False, "error": str(exc), "tokens": []})
            return
        # Which field produced each token — drives hover-a-token-find-the-field
        # in the config editor. Measured per request so it can never describe a
        # command other than the one shown next to it, which is also why it is
        # measured with the SAME builder.
        owners = command_token_owners(cfg, builder=build)
        h.send_json({"ok": True, "tokens": tokens, "command": " ".join(tokens),
                     "owners": owners})
        return

@_route(POST_ROUTES, '/api/parse-extra-args')
def _post_api_parse_extra_args(h, parsed, body):
        """Split a raw EXTRA_ARGS string into launch-config fields and leftover flags

        `extraArgs` (or `text`) is the raw string. Answers `{ok, recognized, remaining}`:
        `recognized` maps config field names to values and `remaining` is the string of
        flags that were not recognized. Model, projector, draft-model and chat-template file
        flags are never hoisted; they stay in `remaining`.
        """
        result = parse_extra_args(body.get("extraArgs") or body.get("text") or "")
        h.send_json({"ok": True, **result})
        return

@_route(POST_ROUTES, '/api/config-favorites')
def _post_api_config_favorites(h, parsed, body):
        """Save the starred launch-config fields (Favorites tab)

        `favorites` is a list of config field names; unknown names and repeats are dropped
        and the order is kept. Answers `{ok, favFields}` with the cleaned list; a
        `favorites` that is not a list answers `ok: false` with status 200.
        """
        favs = body.get("favorites")
        if not isinstance(favs, list):
            h.send_json({"ok": False, "error": "favorites must be a list"})
            return
        # Keep order, dedupe, only known fields.
        seen = set()
        clean = []
        for f in favs:
            f = str(f)
            if f in CONFIG_FIELDS and f not in seen:
                seen.add(f)
                clean.append(f)
        admin_state["favFields"] = clean
        save_admin_state()
        h.send_json({"ok": True, "favFields": clean})
        return

@_route(POST_ROUTES, '/api/repair/user-service')
def _post_api_repair_user_service(h, parsed, body):
        """Reload systemd's user units and restart the llama-server user service

        Runs `systemctl --user daemon-reload`, then `restart` of the unit named by
        `LLAMA_SERVICE_NAME` (default `llamacpp-current.service`). Answers `{ok, result,
        state}`: `result.steps` holds each command with its outcome and `state` is the
        dashboard state of `GET /api/state`. 400 inside the container image, 500 when a step
        fails.
        """
        result = repair_user_service()
        h.send_json({"ok": True, "result": result, "state": state()})
        return

@_route(POST_ROUTES, '/api/llamacpp/update')
def _post_api_llamacpp_update(h, parsed, body):
        """Start a background llama.cpp update and rebuild on the controller's machine

        `tag` is the release tag to build; empty takes the latest upstream release. Answers
        `{ok, job}` at once with the job's status, and a build takes minutes, so follow it
        on `GET /api/llamacpp/update-status`. 409 while another build or install job is
        running, 400 in the container image.
        """
        job = start_llama_update(str((body or {}).get("tag") or ""))
        h.send_json({"ok": True, "job": job})
        return

@_route(POST_ROUTES, '/api/llamacpp/restore')
def _post_api_llamacpp_restore(h, parsed, body):
        """Restore an archived llama.cpp build over the controller's current one

        `id` is an archived build's id from `GET /api/llamacpp/builds`. It runs as the same
        background job as the update: answers `{ok, job}` at once, and progress is on `GET
        /api/llamacpp/update-status`. 400 without an `id` or in the container image, 409
        while another build or install job is running.
        """
        job = start_llama_restore(str((body or {}).get("id") or ""))
        h.send_json({"ok": True, "job": job})
        return

@_route(POST_ROUTES, '/api/system-monitor/settings')
def _post_api_system_monitor_settings(h, parsed, body):
        """Set how many seconds of system-monitor history the controller keeps

        `retentionSeconds` is clamped to 60-3600 and older samples are trimmed at once.
        Answers `{ok, monitor}` with the system-monitor payload (samples, latest reading,
        incidents, `retentionSeconds`); 400 when it is not a number.
        """
        set_monitor_retention(body.get("retentionSeconds"))
        h.send_json({"ok": True, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/local-pricing')
def _post_api_local_pricing(h, parsed, body):
        """Set the manual price per 1M tokens that local models are valued at

        `inputPer1M` and `outputPer1M` are dollars per million tokens; a negative value
        becomes 0 and a missing one is 0. The usage statistics use this one global rate to
        estimate what local traffic would have cost in the cloud. Answers `{ok, rate}`; 400
        when either is not a number.
        """
        try:
            in_rate = max(0.0, float(body.get("inputPer1M") or 0))
            out_rate = max(0.0, float(body.get("outputPer1M") or 0))
        except (TypeError, ValueError):
            raise AppError("inputPer1M/outputPer1M must be numbers", 400)
        admin_state.setdefault("localPricing", {})
        admin_state["localPricing"]["inputPer1M"] = in_rate
        admin_state["localPricing"]["outputPer1M"] = out_rate
        save_admin_state()
        h.send_json({"ok": True, "rate": admin_state["localPricing"]})
        return

@_route(POST_ROUTES, '/api/api-pricing')
def _post_api_api_pricing(h, parsed, body):
        """Set or clear the manual per-1M-token price of one API model

        `model` is the model id and `inputPer1M`, `outputPer1M` are dollars per million
        tokens; sending both as 0 removes the override, and a stored price wins over the
        LiteLLM price table. Answers `{ok, pricing}` with every model's override. 400
        without `model` or with a non-number.
        """
        model = str(body.get("model") or "").strip()
        if not model:
            raise AppError("model required", 400)
        try:
            in_rate = max(0.0, float(body.get("inputPer1M") or 0))
            out_rate = max(0.0, float(body.get("outputPer1M") or 0))
        except (TypeError, ValueError):
            raise AppError("inputPer1M/outputPer1M must be numbers", 400)
        admin_state.setdefault("apiPricing", {})
        if in_rate or out_rate:
            admin_state["apiPricing"][model] = {"inputPer1M": in_rate, "outputPer1M": out_rate}
        else:
            admin_state["apiPricing"].pop(model, None)  # clearing both removes the override
        save_admin_state()
        h.send_json({"ok": True, "pricing": admin_state["apiPricing"]})
        return

@_route(POST_ROUTES, '/api/agent-proxies/config')
def _post_api_agent_proxies_config(h, parsed, body):
        """Save the full list of proxy routes, and optionally the routers

        `routes` is the whole list: a route left out is removed and its firewall port closed
        (best effort); `routers` replaces the kanban routers and is kept as it is when
        omitted. The proxy service is started if it is down, never restarted; it re-reads
        the file itself. Answers `{ok, config, monitor}` with the saved config; 400 for a
        duplicate port or an invalid route (no `label`, a port outside 1024-65535), 500 when
        the proxy service cannot be started.
        """
        result = save_agent_proxy_config(body.get("routes") or [], body.get("routers"))
        h.send_json({"ok": True, "config": result, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/agent-proxies/policy')
def _post_api_agent_proxies_policy(h, parsed, body):
        """Save the global queue and preemption policy of the proxy

        Send the policy keys (`maxSlots`, `cloudFallbackPct`, `priorityPreemptPct`,
        `queueAbortPct`, `preemptGraceSec`, `preemptEnabled`, `stickySlotSec`,
        `loadingModelWaitSec`) as the body or under `policy`; keys left out retain
        their saved values and supplied values are clamped. All graph queues share
        `cloudFallbackPct`, `stickySlotSec` and `loadingModelWaitSec`; obsolete node
        overrides of these fields are ignored. Queue thresholds are
        recalculated in the background afterwards. Answers `{ok, config, monitor}` with the
        saved config.
        """
        result = set_agent_proxy_policy(body.get("policy") or body)
        threading.Thread(target=compute_queue_thresholds, daemon=True).start()
        h.send_json({"ok": True, "config": result, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/agent-proxies/route-policy')
def _post_api_agent_proxies_route_policy(h, parsed, body):
        """Patch one proxy route's label, mode, priority, upstream, router or queue thresholds

        `port` picks the route; only the fields sent change: `label`, `mode` (open, paused
        or drain), `priority` (0-100), `preemptible`, `upstreamType` (llama or cloud; cloud
        needs `providerId`), `cloudFallbackProviderId`, `routerId` (empty unassigns the
        port) and the overrides `cloudFallbackPct`, `priorityPreemptPct`, `queueAbortPct`
        (null inherits the global policy). Answers `{ok, config, monitor}`; 404 for an
        unknown route, 400 for an invalid value or an unknown router.
        """
        result = set_agent_proxy_route_policy(body.get("port"), body)
        h.send_json({"ok": True, "config": result, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/agent-proxies/route-delete')
def _post_api_agent_proxies_route_delete(h, parsed, body):
        """Delete a proxy route (agent, bridge or app port) with its router wiring

        `port` is the route's port; `force` deletes it even while an agent is still assigned
        to it. The router edges that start at the port go too, and its firewall port is
        closed, best effort. Answers `{ok, result: {deleted, label}, topology}`; 404 when no
        route has that port, 409 while an agent is assigned to it and `force` is not set,
        400 for a non-numeric port.
        """
        from caravan.admin.proxies_config import delete_proxy_route
        result = delete_proxy_route(body.get("port"), bool((body or {}).get("force")))
        h.send_json({"ok": True, "result": result, "topology": topology_state()})
        return

@_route(POST_ROUTES, '/api/agent-proxies/routers', '/api/agent-proxies/switchboards')
def _post_api_agent_proxies_routers(h, parsed, body):
        """Save the routers, including each kanban graph (nodes and edges)

        `routers` is the full list (the old body key `switchboards` still works): a router
        left out is dropped and the default router always exists.
        `/api/agent-proxies/switchboards` is the old name of this same route.
        Local outputs with incoming graph cables receive automatic queue nodes.
        Their `modelOutputId` names the owner and `modelQueueActive` is derived by
        the server. Disconnecting the last cable keeps the node settings but sets
        it inactive. Existing direct local queue nodes are adopted with their
        settings; conflicting policies for one model return 409. Answers `{ok,
        config, topology}`; nothing restarts, the proxy re-reads the file by itself.
        """
        result = set_routers(body.get("routers") or body.get("switchboards") or [])
        h.send_json({"ok": True, "config": result, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/agent-proxies/stop')
def _post_api_agent_proxies_stop(h, parsed, body):
        """Stop the in-flight requests of a proxy route, or one request by id

        `port` stops every in-flight request of that route and `requestId` stops just that
        one. It writes stop requests that the proxy picks up, so the answer says what was
        asked to stop, not that it has stopped. Answers `{ok, result: {stopped}, monitor}`;
        404 for an unknown `port`.
        """
        result = stop_agent_proxy_route(body.get("port"), body.get("requestId"))
        h.send_json({"ok": True, "result": result, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/bridge-port')
def _post_api_cloud_bridge_port(h, parsed, body):
        """Open a port of its own for one cloud model, straight to that model

        `blockId` is the model block and `label` an optional name (default `bridge
        <model>`). The port comes from the proxy range, is opened in the controller's
        firewall (best effort) and puts the model on the kanban. Answers `{ok, route}`; 400
        without `blockId`, 404 for an unknown block.
        """
        route = mint_bridge_port(body.get("blockId"), body.get("label"))
        h.send_json({"ok": True, "route": route})
        return

@_route(POST_ROUTES, '/api/app-port')
def _post_api_app_port(h, parsed, body):
        """Mint an entry port with its own API key for an external app

        `name` is the port's label (required, cut to 80 characters). The port comes from the
        proxy range, is opened in the controller's firewall (best effort) and feeds the
        default router's graph, like agent traffic. Answers `{ok, route}` where `route.port`
        is the port and `route.apiKey` the generated data-plane key; 400 without a `name`.
        """
        from caravan.admin.proxies_config import mint_app_port
        route = mint_app_port(body.get("name"))
        h.send_json({"ok": True, "route": route})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/usage-reserve')
def _post_api_cloud_accounts_usage_reserve(h, parsed, body):
        """Keep a share of a subscription's limit window for the operator

        `id` is the ChatGPT subscription account, `windowSeconds` the window's length (18000
        for five hours, 604800 for a week) and `pct` the share to keep, 0 to 90 (0 lifts
        it). While a window has no more than that left, the proxy answers the account's
        requests itself with 429. Answers `{ok, reserve, reserveKept, reserveMax,
        reserveReadAt}`, where `reserveKept` is the window closing the account now, or null;
        400 for a non-subscription account or an out-of-range value, 404 for an unknown
        account.
        """
        # The share of one limit window the operator keeps for themselves; the
        # proxy refuses requests to the account once the window is down to it.
        from caravan.admin.usage_reserve_desk import UsageReserveDesk
        desk = UsageReserveDesk()
        account_id = str(body.get("id") or "").strip()
        desk.set(account_id, body.get("windowSeconds"), body.get("pct"))
        h.send_json({"ok": True, **desk.view(account_id)})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/bridge-port-delete')
def _post_api_cloud_bridge_port_delete(h, parsed, body):
        """Close one cloud-model port; a model's last port takes it off the kanban

        `port` is the port to close. When it is the model's last port and cables or rules
        still lead to the model, `resolution` must be `{moveTo: <block id of the same
        provider>}` or `{cut: true}`. Answers `{ok, deleted, closed, leaves, moved, cut,
        onto, topology}`; 404 for an unknown port, 400 for a route that is not a model's
        port (an agent route), 409 without a needed `resolution`.
        """
        # A model's last port takes it off the kanban: when cables or rules
        # hold it, `resolution` says where they go (cloud_ports.py), else 409.
        from caravan.admin.cloud_ports import CloudPortDesk
        done = CloudPortDesk().close_port(body.get("port"), body.get("resolution"))
        h.send_json({"ok": True, "deleted": int(body.get("port")), **done, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/auto-create-blocks')
def _post_api_cloud_accounts_auto_create_blocks(h, parsed, body):
        """Check an account's model list now and sync its model blocks with it

        `id` is the account; new chat models get blocks (not on the kanban), and a block
        whose model is missing from repeated lists is removed once nothing points at it and
        it was not added by hand. Answers `{ok, created, total, skipped, gone, removed,
        topology}`: `created`, `gone` (missing but kept) and `removed` count blocks, `total`
        counts the chat models listed and `skipped` the non-chat ones left out. 404 for an
        unknown account, 502 when the provider fails, 503 while its endpoint is disabled by
        the failure breaker.
        """
        account_id = str(body.get("id") or "").strip()
        result = auto_create_blocks(account_id)
        h.send_json({"ok": True, **result, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-pools/save')
def _post_api_cloud_pools_save(h, parsed, body):
        """Create or update a subscription pool

        `pool` contains id, name, ordered members ({accountId, enabled, automatic}),
        mode (auto/manual), manualAccountId, optional manualUntil (Unix seconds), and
        returnToPrimary. Optional adoptAccountId moves that member's model blocks to
        this pool while preserving their ids, ports and cables. Returns {ok, pool,
        adoptedModels, topology}. Invalid members/policy give 400.
        """
        from caravan.admin.cloud_pools import CloudPoolDesk
        result = CloudPoolDesk().upsert(body.get("pool") or {}, body.get("adoptAccountId"))
        h.send_json({"ok": True, **result, "topology": topology_state(refresh_hosts=False)})

@_route(POST_ROUTES, '/api/cloud-pools/connect-account')
def _post_api_cloud_pools_connect_account(h, parsed, body):
        """Create an additional real subscription directly inside a pool

        `poolId` identifies an existing pool and `account` is a new OAuth
        subscription. Adds a disabled pendingLogin member in the same save;
        successful OAuth enables it. No credentials are duplicated, model ids
        and ports are preserved. Returns {ok, account, topology}; duplicate id
        gives 409, unknown pool 404, non-subscription 400. No member-count cap.
        """
        from caravan.admin.cloud_pools import CloudPoolDesk
        account = CloudPoolDesk().connect_account(body.get("poolId"), body.get("account") or {})
        h.send_json({"ok": True, "account": account, "topology": topology_state(refresh_hosts=False)})

@_route(POST_ROUTES, '/api/cloud-accounts/subscription-reset')
def _post_api_cloud_accounts_subscription_reset(h, parsed, body):
        """Explicitly consume one selected banked OpenAI reset

        Requires id (individual account), creditId, UUID idempotencyKey and
        confirmed=true. Returns {ok, outcome, idempotencyKey}; outcome is reset,
        already_redeemed, nothing_to_reset or no_credit. A timeout must be retried
        with the SAME key; conflicting/new unresolved attempts give 409. Confirmed
        resets invalidate proxy quota readings. Routing never calls this action.
        """
        from caravan.admin.subscription_resets import SubscriptionResetDesk
        h.send_json(SubscriptionResetDesk().consume(body.get("id"), body.get("creditId"),
                    body.get("idempotencyKey"), body.get("confirmed")))

@_route(POST_ROUTES, '/api/cloud-pools/test-alias')
def _post_api_cloud_pools_test_alias(h, parsed, body):
        """Create a labelled routing-test alias of an existing subscription

        `id` is the original account. Returns {ok, account, topology}. The alias
        shares its owner's credentials, quota and reserve; no token is copied.
        Repeating this call returns the existing alias. Non-subscriptions give 400.
        """
        from caravan.admin.cloud_pools import CloudPoolDesk
        alias = CloudPoolDesk().clone_test(body.get("id"))
        h.send_json({"ok": True, "account": alias, "topology": topology_state(refresh_hosts=False)})

@_route(POST_ROUTES, '/api/cloud-pools/delete')
def _post_api_cloud_pools_delete(h, parsed, body):
        """Delete an empty subscription pool

        `id` identifies the pool. Model blocks must be moved or removed first (409).
        Returns {ok, topology}; accounts and their credentials remain available.
        """
        from caravan.admin.cloud_pools import CloudPoolDesk
        CloudPoolDesk().delete(str(body.get("id") or ""))
        h.send_json({"ok": True, "topology": topology_state(refresh_hosts=False)})

@_route(POST_ROUTES, '/api/cloud-accounts/save')
def _post_api_cloud_accounts_save(h, parsed, body):
        """Create or update a cloud provider account

        `account` is the account object; its `id` (1-48 letters, digits, `_` or `-`) picks
        the account, and an existing account keeps the fields an edit leaves out. Answers
        `{ok, account, topology}` with the account as stored; 400 for a bad `id` or a
        `baseUrl` that is not http(s).
        """
        account = upsert_cloud_account(body.get("account") or {})
        h.send_json({"ok": True, "account": account, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/delete')
def _post_api_cloud_accounts_delete(h, parsed, body):
        """Delete a cloud provider account with its model blocks and stored credential

        `id` is one registration, even when another logs into the same OpenAI
        identity. Detaches it from pools that have other members, preserving
        their model blocks and ports. Removing a manual choice restores auto
        mode. The last pool member and an owner with legacy test aliases give
        409; an unknown `id` is ignored. Answers `{ok, topology}`.
        """
        delete_cloud_account(body.get("id"))
        h.send_json({"ok": True, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/key')
def _post_api_cloud_accounts_key(h, parsed, body):
        """Check an account's API key against its provider and store it when it works

        `id` is the account and `apiKey` the key. The key is tried with a request to the
        provider first, and a key that fails is not stored: the answer is then `ok: false`
        with the `test` result, still with status 200. On success answers `{ok, test, last4,
        topology}`; 404 for an unknown account, 400 without a key.
        """
        result = set_account_key(body.get("id"), body.get("apiKey"))
        result["topology"] = topology_state(refresh_hosts=False)
        h.send_json(result)
        return

@_route(POST_ROUTES, '/api/cloud-accounts/key-delete')
def _post_api_cloud_accounts_key_delete(h, parsed, body):
        """Remove an account's stored API key or OAuth login

        `id` is the account. The account and its models stay; an unknown `id` or an account
        without a credential is not an error. Answers `{ok, topology}`.
        """
        delete_account_credential(body.get("id"))
        h.send_json({"ok": True, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/oauth/start')
def _post_api_cloud_accounts_oauth_start(h, parsed, body):
        """Start an OAuth (PKCE) login for a cloud account and return the sign-in URL

        `id` is the account; a callback listener binds `127.0.0.1` of the controller's
        machine on its redirect port (1455 by default). A remote browser can complete login
        by submitting its returned localhost URL to `/api/cloud-accounts/oauth/complete`.
        A login left unfinished expires after five minutes and a new
        start replaces the pending one of that account. Answers `{ok, authorizeUrl, state,
        redirectUri}` (open `authorizeUrl`, then poll `GET
        /api/cloud-accounts/oauth/status?state=`); 404 for an unknown account, 400 when it
        does not use OAuth, 500 when the port cannot be bound.
        """
        result = start_oauth_login(body.get("id"))
        h.send_json({"ok": True, **result})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/oauth/complete')
def _post_api_cloud_accounts_oauth_complete(h, parsed, body):
        """Complete remote-browser OAuth with the returned localhost callback URL

        `state` is the pending login and `callbackUrl` its full localhost URL.
        Validates origin, path, state, code and 5-minute expiry; exchanges the
        code with the stored PKCE verifier once. Enables only pendingLogin pool
        members. Returns {state, email?, error?, topology}; invalid URL gives 400,
        simultaneous/reused unsuccessful completion 409. The URL is not logged.
        """
        from caravan.admin.oauth import OAuthLoginDesk
        result = OAuthLoginDesk.paste_callback(body.get("state"), body.get("callbackUrl"))
        h.send_json({**result, "topology": topology_state(refresh_hosts=False)})

@_route(GET_ROUTES, '/api/cloud-upstream-errors')
def _get_api_cloud_upstream_errors(h, parsed):
        """List the failed cloud requests of the last 24 hours, per account, model and error code

        Failures of requests routed to cloud providers, read from the proxy's event logs.
        `byAccount` maps each account id to at most eight rows, most frequent first, each
        with `model`, `code`, `count`, `firstAt`, `lastAt`, the last `error` text and
        `okSince` (requests of the account that succeeded after its newest failure). The
        controller's own refusal that enforces the operator's reserve is a row of its own,
        not an HTTP 429.
        """
        from caravan.admin.cloud_api import cloud_upstream_errors
        h.send_json(cloud_upstream_errors())
        return

@_route(GET_ROUTES, '/openapi.json')
def _get_openapi(h, parsed):
        """This API as OpenAPI 3.1: every route, what it does, what it reads, who may call it

        Built from the route tables and the handlers' docstrings and code when the controller
        starts; `info.version` is the controller's version and `info.x-commit` its commit.
        """
        # Open without sign-in, like /health: the home rule (visumap,
        # apps-openapi.md) — every app serves its API description here.
        h.send_json(API_SPEC.document())
        return


@_route(GET_ROUTES, '/health', '/api/health')
def _get_health(h, parsed):
        """Liveness probe: answers with version, git commit and whether sign-in is required

        Served at `/health` and `/api/health`. Answers `{ok, service, version, commit,
        authRequired, time}` without probing any host. `commit` is empty when the checkout
        has no git, `authRequired` says whether the other routes need a session (false on a
        fresh install) and `time` is the server clock in epoch seconds.
        """
        # Liveness, cheaply and without credentials. The contract is deliberately
        # tiny and STABLE — a test suite starts with this, and a monitor polls it
        # forever, so anything added here can never be taken away:
        #   ok       always true when the process answers at all
        #   service  who is answering, so a wrong-port hit is obvious
        #   version  ties a test run to a build
        #   commit   the same, at git granularity ("" when the checkout has no git)
        #   authRequired  whether a session is needed for everything else — a
        #                 fresh install answers false, and a suite that expects
        #                 to log in can say so before it wastes a browser on it
        #   time     so a stale cached answer is visible as one
        #
        # It never touches the fleet: no host probes, no config, nothing that
        # could make the liveness check itself slow or flaky.
        commit = ""
        try:
            commit = str((project_git_info() or {}).get("head") or "")
        except Exception:
            pass
        h.send_json({"ok": True, "service": "lama-caravan",
                     "version": APP_VERSION, "commit": commit,
                     "authRequired": bool(auth_mod.auth_enabled()),
                     "time": int(time.time())})
        return

@_route(GET_ROUTES, '/api/port-exclusions')
def _get_api_port_exclusions(h, parsed):
        """List the ports kept free of cells, optionally with a scan for foreign listeners

        `exclusions` lists each excluded `port` with its `note`, `host`, `addedAt` and
        `auto` flag. `scan=1` also scans the cell port range on the controller and on every
        machine with a scout for listeners the fleet does not own, and returns them under
        `scan`; it takes seconds, so ask only when needed. A machine that cannot be scanned
        is listed with `ok: false` and an `error`, not as clean.
        """
        from caravan.admin.port_exclusions import list_exclusions, scan_foreign_listeners
        # ?scan=1 walks the range on every host — seconds, not milliseconds, so
        # the picker asks for it only when the operator opens the scan.
        payload = {"ok": True, "exclusions": list_exclusions()}
        if (parsed.query or "").find("scan=1") >= 0:
            payload["scan"] = scan_foreign_listeners()
        h.send_json(payload)
        return

@_route(POST_ROUTES, '/api/port-exclusions')
def _post_api_port_exclusions(h, parsed, body):
        """Add and remove port exclusions (ports the fleet must not put a cell on)

        `add` is a list of ports or `{port, note, host, auto}` entries and `remove` a list
        of ports to lift; both are applied in one call. Answers `{ok, added, removed,
        exclusions}` with the resulting full list. 400 for a port outside 1-65535, 409 for a
        port that a cell or proxy route already uses.
        """
        from caravan.admin.port_exclusions import set_exclusions
        h.send_json(set_exclusions(body))
        return

@_route(GET_ROUTES, '/api/cloud-blocks/refs')
def _get_api_cloud_blocks_refs(h, parsed):
        """List everything that references a cloud model block (the delete preflight)

        `id` is the block. `refs` groups what points at it: `bridges` (its own ports),
        `routes`, `fallbacks`, `edges` (cables), `queueRoles`, `rescueRoles` and `rules`.
        `held` counts the cables and rules that closing its last port would strand and
        `ports` lists its own port numbers; an unknown `id` gives empty lists, not a 404.
        """
        from caravan.admin.cloud_ports import CloudModelPorts
        from caravan.admin.cloud_refs import CloudModelRefs
        query = urllib.parse.parse_qs(parsed.query or "")
        block_id = (query.get("id") or [""])[0].strip()
        cfg = load_agent_proxy_config()
        ports = CloudModelPorts(cfg)
        # `held`: what the kanban holds on the model — what closing its last
        # port must first move or disconnect (the rule lives in cloud_ports.py).
        h.send_json({"ok": True, "refs": CloudModelRefs(cfg).of(block_id),
                     "held": ports.held(block_id), "ports": ports.of(block_id)})
        return

@_route(POST_ROUTES, '/api/cloud-api-health/retry')
def _post_api_cloud_api_health_retry(h, parsed, body):
        """Clear a tripped provider endpoint's failure record so it is tried again

        `key` is an endpoint key taken from `cloudApiHealth.endpoints` in the topology, such
        as `<accountId>:models`. It only forgets the recorded failures, so the next call to
        that endpoint goes out to the provider; an unknown key is ignored. Answers `{ok,
        topology}`.
        """
        from caravan.admin import model_catalog
        model_catalog.retry_endpoint(str(body.get("key") or ""))
        h.send_json({"ok": True, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-blocks/save')
def _post_api_cloud_blocks_save(h, parsed, body):
        """Create or update a cloud model block

        `block` is the block object (`id` of 1-48 letters, digits, `_` or `-`, the
        `accountId` of an existing account, `name`, `model`, `modelMode` of `rewrite` or
        `passthrough`); a new `id` makes a block the model sync never removes, and fields an
        edit leaves out keep their values. `block.exposed` set also opens the model's own
        port, so it is on the kanban. Answers `{ok, block, port, topology}` (`port` is null
        unless a port was opened); 400 for a bad `id` or an unknown account.
        """
        wanted = body.get("block") or {}
        block = upsert_cloud_block(wanted)
        port = None
        if isinstance(wanted, dict) and wanted.get("exposed"):
            # "Show it on the kanban" = a port of its own (cloud_ports.py).
            from caravan.admin.cloud_ports import CloudPortDesk
            port = CloudPortDesk().open(block["id"])
        h.send_json({"ok": True, "block": block, "port": port, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-blocks/restore')
def _post_api_cloud_blocks_restore(h, parsed, body):
        """Bring back a model block that the model sync removed within the last day

        `accountId` and `id` name the account and the removed block (the topology lists them
        as `cloudRemoved`). The block returns as the operator's own (`manual`), so a later
        sync does not remove it again. Answers `{ok, block, topology}`; 404 when there is
        nothing to bring back: it was removed more than a day ago, or already restored.
        """
        from caravan.admin.cloud_api import CLOUD_SYNC
        block = CLOUD_SYNC.restore(body.get("accountId"), body.get("id"))
        if not block:
            raise AppError("nothing to bring back — it was removed more than a day ago, or already restored", 404)
        h.send_json({"ok": True, "block": block, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-blocks/delete')
def _post_api_cloud_blocks_delete(h, parsed, body):
        """Delete a cloud model block

        `id` is the block; an unknown `id` is ignored. Only the block record is removed, so
        read `GET /api/cloud-blocks/refs` first to see what still points at it. Answers
        `{ok, topology}`.
        """
        delete_cloud_block(body.get("id"))
        h.send_json({"ok": True, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-blocks/move-cables')
def _post_api_cloud_blocks_move_cables(h, parsed, body):
        """Move the cables and rules of one cloud model onto another of the same provider

        `from` and `to` are block ids of two different models of one account. Cables keep
        their roles, and the rules and cloud fallbacks that named `from` now name `to`; `to`
        gets a port of its own if it had none, so it is on the kanban, and is marked
        announced. Answers `{ok, moved, topology}` with the number of references moved; 400
        for the same model twice, an unknown block or two providers.
        """
        # The "new model" window and "⇄ Move cables…": everything that pointed
        # at one model of a provider now points at another of the same
        # provider, roles kept; that one is on the kanban from now on — with a
        # port of its own if it had none (cloud_ports.py).
        from caravan.admin.cloud_ports import CloudPortDesk
        src, dst = str(body.get("from") or "").strip(), str(body.get("to") or "").strip()
        moved = CloudPortDesk().move_cables(src, dst)
        mark_cloud_blocks_announced([dst])
        h.send_json({"ok": True, "moved": moved, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-blocks/announced')
def _post_api_cloud_blocks_announced(h, parsed, body):
        """Mark new cloud models as announced, optionally putting them on the kanban

        `ids` are the block ids that the board's 'new model' window was answered for; it
        will not ask about them again. With `expose` set each also gets a port of its own,
        which is what puts a model on the kanban. Answers `{ok, topology}`.
        """
        ids = [str(i) for i in (body.get("ids") or [])]
        mark_cloud_blocks_announced(ids)
        if body.get("expose"):
            # "Just add it": on the kanban = a port of its own.
            from caravan.admin.cloud_ports import CloudPortDesk
            for block_id in ids:
                CloudPortDesk().open(block_id)
        h.send_json({"ok": True, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/cloud-blocks/expose')
def _post_api_cloud_blocks_expose(h, parsed, body):
        """Put a cloud model on the kanban or take it off, by opening or closing its ports

        `id` is the block; `exposed` true opens a port of its own for it (answers `{ok,
        port, topology}`), false closes all its ports (answers `{ok, closed, leaves, moved,
        cut, onto, topology}`). When cables or rules still lead to the model, `resolution`
        must say where they go: `{moveTo: <block id of the same provider>}` or `{cut:
        true}`. 409 without a needed `resolution`; 404 for an unknown block (opening) or a
        model with no port to close.
        """
        # The kanban's tick: on = the model gets a port of its own; off = all its
        # ports close, and what the routers hold on it goes where `resolution`
        # says (cloud_ports.py), or the answer is 409.
        from caravan.admin.cloud_ports import CloudPortDesk
        desk = CloudPortDesk()
        if body.get("exposed"):
            done = {"port": desk.open(str(body.get("id") or "").strip())}
        else:
            done = desk.close(body.get("id"), None, body.get("resolution"))
        h.send_json({"ok": True, **done, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/engine-outputs/expose')
def _post_api_engine_outputs_expose(h, parsed, body):
        """Make a model of a machine's engine (Ollama, LM Studio) a router output, or stop it

        `hostId`, `kind` (the engine) and `model` name the model and `exposed` says whether
        it is an output. Its output id is `eng:<hash>`; only a model that the machine's last
        report lists can become one, and one that runs on the engine's own cloud is refused.
        Answers `{ok, id, exposed, topology}`; 400 for a missing field or a cloud model, 404
        for a model the report does not list.
        """
        # A model of an engine next to the cells (Ollama, LM Studio) becomes a
        # router output, or stops being one (docs/foreign-engines.md, step 2).
        from caravan.admin.engine_outputs import EngineOutputs
        result = EngineOutputs().set(topology_hosts(), body.get("hostId"), body.get("kind"), body.get("model"),
                                     bool(body.get("exposed")))
        h.send_json({"ok": True, **result, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/engines/unload', '/api/engines/delete')
def _post_api_engines_act(h, parsed, body):
        """Unload or delete a model of a machine's engine (Ollama, LM Studio) through its scout

        `hostId`, `kind` (the engine) and `model` name the model; the path's last segment
        (`unload` or `delete`) is the action. The scout answers at once and acts on its own
        thread, and the model shows as being acted on at the next read. Answers `{ok,
        hostId, kind, model, op, topology}`; 404 for a machine with no report or an engine
        it does not report, 502 with the scout's own words when it refuses or cannot be
        reached.
        """
        # A model of an engine next to a machine's cells, unloaded or deleted
        # through its scout (docs/foreign-engines.md, step 3). No load: a cell
        # in the engine loads its model when it starts (2026-09-26).
        from caravan.admin.engine_actions import EngineActions
        from caravan.admin.fleet_clients import _scout
        op = parsed.path.rsplit("/", 1)[-1]
        result = EngineActions(_scout, topology_hosts).act(body.get("hostId"), op, body.get("kind"), body.get("model"))
        h.send_json({**result, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/engines/start', '/api/engines/stop')
def _post_api_engines_serve(h, parsed, body):
        """Start or stop the server of a machine's engine (Ollama, LM Studio) through its scout

        `hostId` and `kind` (the engine) name the engine; the path's last segment (`start`
        or `stop`) is the action. The scout answers at once and waits for the server on its
        own thread: the engine shows as starting or stopping (`serverAction`) on the next
        read, and a refusal stays as `serverError`. Answers `{ok, hostId, kind, op,
        topology}`; 404 for a machine with no report or an engine it does not report, 502
        with the scout's own words when it refuses or cannot be reached.
        """
        # The server of an engine next to a machine's cells started or
        # stopped through its scout (docs/foreign-engines.md, step 3г).
        from caravan.admin.engine_actions import EngineActions
        from caravan.admin.fleet_clients import _scout
        op = parsed.path.rsplit("/", 1)[-1]
        result = EngineActions(_scout, topology_hosts).serve(body.get("hostId"), op, body.get("kind"))
        h.send_json({**result, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/queue-thresholds/recalc')
def _post_api_queue_thresholds_recalc(h, parsed, body):
        """Recompute the queue-wait thresholds of the proxy ports in the background

        The thresholds come from the global policy and each route's `clientTimeoutSeconds`.
        Answers `{ok, thresholds}` at once with the thresholds computed before (null until
        the first computation), not the ones now being computed; read `GET
        /api/queue-thresholds` a moment later for the new values.
        """
        threading.Thread(target=compute_queue_thresholds, daemon=True).start()
        h.send_json({"ok": True, "thresholds": QUEUE_THRESHOLDS.latest()})
        return

@_route(POST_ROUTES, '/api/topology/client-heartbeat')
def _post_api_topology_client_heartbeat(h, parsed, body):
        """Record a scout's heartbeat: the state of one machine

        `host` names the machine (`host.id`, or `host.name`) and the rest of the body is
        what the scout reports about it: GPUs, compute apps, CPU and RAM, engines, llama.cpp
        cells and build versions. The machine's host record is replaced whole and no client
        record is touched. Answers `{ok, host}` with the record as stored; 400 without a
        host id or with the controller's reserved name.
        """
        host = record_host_report(body)
        h.send_json({"ok": True, "host": host})
        return

@_route(POST_ROUTES, '/api/topology/assignments')
def _post_api_topology_assignments(h, parsed, body):
        """Store the agent-to-proxy-port assignments of one client

        `hostId` is the client and `assignments` its full list of `{agentId, routes: [{role,
        proxyId, endpoint}]}` rows, which replaces what was stored. The rows are only
        stored, nothing is pushed to the machine, and the proxy routes' client, role,
        context window and model name are then synced from them. Answers `{ok, result,
        topology}`; 400 without `hostId`, for an `assignments` that is not a list, a row
        without `agentId` or a route without `endpoint`.
        """
        result = apply_topology_assignments(body)
        h.send_json({"ok": True, "result": result, "topology": topology_state()})
        return

@_route(POST_ROUTES, '/api/agent-port')
def _post_api_agent_port(h, parsed, body):
        """Create a proxy port for an agent and bind the agent to it

        `clientId` and `agentId` name the agent, `label` is an optional port name and `role`
        is `primary` (default) or `fallback`; `port` picks the number, else the next free
        one in the proxy range comes (a fallback takes the neighbour of the primary's port
        when that is free). Answers `{ok, route, result, topology}`; 400 for a missing id or
        a port out of range, 409 for a taken port. A client or agent the operator's record
        lacks answers 404 only after the port has already been created.
        """
        from caravan.admin.proxies_config import mint_agent_port
        # The role rides along on the wire. Without it a new port always
        # landed on primary, so a request for "give me a second port" would
        # silently replace the working route instead.
        role = str(body.get("role") or "primary").strip() or "primary"
        port = body.get("port")
        if not port and role == "fallback":
            # A +1 gap is deliberately left next to primary — that's the one
            # we take, or the port pair stops reading at a glance. If it's
            # taken, let the allocator pick its own — that's not a reason to
            # refuse.
            rows = ((topology_store().get("assignments") or {})
                    .get(str(body.get("clientId") or "")) or {}).get("assignments") or []
            row = next((r for r in rows if r.get("agentId") == body.get("agentId")), None)
            port = fallback_port_for(row)
        route = mint_agent_port(body.get("clientId"), body.get("agentId"),
                                body.get("label"), port)
        # Created FOR an agent, so bind it in the same breath — a new port the
        # operator then has to attach by hand is two steps where they asked for
        # one, and the gap between them is a port nobody uses.
        bind = bind_agent_to_proxy({"hostId": body.get("clientId"),
                                    "agentId": body.get("agentId"),
                                    "role": role,
                                    "port": route["port"]})
        h.send_json({"ok": True, "route": route, "result": bind,
                     "topology": topology_state()})
        return

@_route(POST_ROUTES, '/api/topology/agent-proxy-bind')
def _post_api_topology_agent_proxy_bind(h, parsed, body):
        """Point an agent at a proxy port for one role (primary or fallback)

        `hostId` and `agentId` name the agent in the operator's record, `port` is a port
        that has a proxy route, and `role` is `primary` (default) or `fallback`. The binding
        is only recorded: the agent itself is pointed at the port by hand, in its own
        settings. Answers `{ok, result, topology}`; 404 for a client or agent the record
        lacks, 400 without a port, for a port with no route or for another role, 409 when
        another agent already holds the port.
        """
        result = bind_agent_to_proxy(body)
        h.send_json({"ok": True, "result": result, "topology": topology_state()})
        return

@_route(POST_ROUTES, '/api/topology/client-alias')
def _post_api_topology_client_alias(h, parsed, body):
        """Set the board name of a client or of a machine with a scout

        `hostId` is the id of the client or machine and `name` its new display name, cut to
        120 characters; an empty `name` clears the alias so the reported name shows again.
        Answers `{ok, result: {hostId, alias}, topology}`; 400 without `hostId`.
        """
        result = set_topology_client_alias(body.get("hostId"), body.get("name"))
        h.send_json({"ok": True, "result": result, "topology": topology_state(refresh_hosts=False)})
        return

@_route(POST_ROUTES, '/api/topology/server-order')
def _post_api_topology_server_order(h, parsed, body):
        """Set the order of the cards under Model servers

        `order` lists card keys, `node:<machine id>` for a machine and `cloud:<account id>` for a
        cloud provider or pool, in the order the board draws them; the kanban's Servers panel
        follows it. A card the list does not name stands after the named ones, in the board's own
        order, and an empty list returns the board to its own order. The list is stored whole,
        for every browser and account. Answers `{ok, order, rev}`, where `rev` grows by one with
        every save and comes back in GET /api/topology as `layout.serverOrderRev`; 400 when
        `order` is not a list of distinct card keys (at most 500, each up to 200 characters).
        """
        h.send_json(SERVER_ORDER.save(body.get("order")))
        return

@_route(POST_ROUTES, '/api/topology/client-llama/start')
def _post_api_topology_client_llama_start(h, parsed, body):
        """Start a cell on a machine through its scout, from the launch request in the body

        The launch request comes in the body (`hostId`, `port`, `modelPath`, `gpuLayers`,
        `ctxSize`, `cacheModels`, `config`, and `cellPort` when the start moves the cell),
        not from the saved slot. On success the cell's slot is saved so its cables stay
        attached. Answers `{ok, hostId, result}` with the scout's reply; 404 for an unknown
        machine, 409 for a reserved port, 502 when the scout is unreachable or refuses.
        """
        h.send_json(client_llama_start(body))
        return

@_route(POST_ROUTES, '/api/fleet/llama-update')
def _post_api_fleet_llama_update(h, parsed, body):
        """Start a llama.cpp update job on a machine through its scout

        `hostId` names the machine and `tag` a release tag or commit to build; empty means
        the latest release. The answer is the scout's job status (`running`, `tag`, `lines`,
        `done`, `rc`, `error`), followed with `GET /api/fleet/llama-update-status`; running
        cells keep the old binary until restarted. A scout that is busy, unreachable or
        refusing comes back as 502 with its words.
        """
        h.send_json(client_llama_update(body))
        return

@_route(POST_ROUTES, '/api/fleet/llama-restore')
def _post_api_fleet_llama_restore(h, parsed, body):
        """Restore an archived llama.cpp build on a machine through its scout

        `hostId` names the machine and `id` the archived build (see `GET
        /api/fleet/llama-builds`). 400 without an `id`, and the scout is not asked: scout
        2.21 takes an empty one for an ordinary update. The answer is the job's status,
        followed with `GET /api/fleet/llama-update-status`; running cells keep their binary
        until restarted. 502 with the scout's words when it is busy or unreachable.
        """
        h.send_json(client_llama_restore(body))
        return

@_route(POST_ROUTES, '/api/fleet/vllm/update')
def _post_api_fleet_vllm_update(h, parsed, body):
        """Install another vLLM version on a machine through its scout

        `hostId` names the machine and `version` pins a vLLM release (a rollback is an older
        pin); empty installs the latest. The answer is the scout's job status, followed with
        `GET /api/fleet/vllm/update-status`. 502 with the scout's words when vLLM is not
        installed there yet (its first cell start creates it), the version is malformed, or
        an install is already running.
        """
        h.send_json(client_vllm_update(body))
        return

@_route(POST_ROUTES, '/api/fleet/llama-suspect-dismiss')
def _post_api_fleet_llama_suspect_dismiss(h, parsed, body):
        """Dismiss the crashing-build warning for a machine's current llama.cpp build

        `hostId` names the machine; its scout remembers the dismissal for that build (scout
        2.6+), and the machine's record reads as not suspect at once. Answers the scout's
        `{ok, dismissed}`.
        """
        h.send_json(client_llama_suspect_dismiss(body))
        return

@_route(POST_ROUTES, '/api/host/reboot')
def _post_api_host_reboot(h, parsed, body):
        """Reboot a machine: the controller's own, or a fleet host through its scout

        `hostId` names the machine; the reserved id `controller` is the controller's own
        machine, rebooted with `sudo systemctl`. Cells are not stopped first, and the answer
        `{ok, hostId, action, result, at}` comes before the machine goes down. 404 for a
        machine no scout has reported for, 500 when sudo refuses, 502 when the scout is
        unreachable.
        """
        # Power-cycling a host is confirmed in the UI and logged here: it drops
        # every cell on that machine, so "who asked" matters after the fact.
        _hid = str((body or {}).get("hostId") or "")
        print(f"[host] reboot requested for {_hid or '?'}")
        h.send_json(host_power(body or {}, "reboot"))
        return

@_route(POST_ROUTES, '/api/host/poweroff')
def _post_api_host_poweroff(h, parsed, body):
        """Power a machine off; nothing on the board can switch it back on

        `hostId` names the machine; the reserved id `controller` is the controller's own
        machine, powered off with `sudo systemctl`, and any other goes through its scout.
        The answer `{ok, hostId, action, result, at}` comes before the machine goes down.
        404 for a machine no scout has reported for, 500 when sudo refuses, 502 when the
        scout is unreachable.
        """
        # Its own route rather than a flag on the one above. Poweroff cannot be
        # undone from this board — nothing here can switch a machine on — so it
        # must not be reachable by getting a field wrong, and a scout that does
        # not know it answers 404 instead of guessing which was meant.
        _hid = str((body or {}).get("hostId") or "")
        print(f"[host] POWEROFF requested for {_hid or '?'} — not reversible from here")
        h.send_json(host_power(body or {}, "poweroff"))
        return

@_route(POST_ROUTES, '/api/host/power-schedule')
def _post_api_host_power_schedule(h, parsed, body):
        """Set when a machine powers itself off, once or every day

        `hostId` names the machine and `schedule` is `{enabled, at, daily}`: `at` is `HH:MM`
        on the controller's clock (03:00 when empty) and `daily` defaults to true, while a
        schedule with `daily` false disables itself after firing. Enabling with a time
        already past today waits for tomorrow. Answers `{ok, hostId, schedule}`; 400 for a
        missing `hostId` or a malformed time.
        """
        # Stores WHEN to power a host off; the once-a-minute scheduler thread
        # fires it. Storing a schedule is not itself destructive, so unlike the
        # manual button it needs no typed-name gate — the UI gates ENABLING with
        # a plain warning and an off-by-default checkbox.
        _hid = str((body or {}).get("hostId") or "")
        _en = bool(((body or {}).get("schedule") or {}).get("enabled"))
        print(f"[host] power-schedule {'ENABLED' if _en else 'set'} for {_hid or '?'}")
        h.send_json(set_host_power_schedule(body or {}))
        return

@_route(POST_ROUTES, '/api/topology/client-llama/stop')
def _post_api_topology_client_llama_stop(h, parsed, body):
        """Stop one cell on a machine through its scout, or every cell when no port is given

        `hostId` names the machine and `port` the cell. A stopped cell leaves the machine's
        report, and the model files it downloaded are removed unless it runs with
        `cacheModels`. Answers `{ok, hostId, result}` with the scout's reply; 502 when the
        scout is unreachable or refuses.
        """
        h.send_json(client_llama_stop(body))
        return

@_route(POST_ROUTES, '/api/topology/client-llama/purge-cache')
def _post_api_topology_client_llama_purge_cache(h, parsed, body):
        """Delete the model files a machine's scout has downloaded to its cache

        `hostId` names the machine; files held by cells that are running are kept. Answers
        `{ok, hostId, result}` where `result` is the scout's `{ok, removed, freedBytes}`;
        502 when the scout is unreachable or refuses.
        """
        h.send_json(client_llama_purge_cache(body))
        return

@_route(POST_ROUTES, '/api/topology/server-slot/add')
def _post_api_topology_server_slot_add(h, parsed, body):
        """Reserve a cell slot (host and port) on a machine before anything runs on it

        `hostId` is required. Omit `port` to take the next free one; `engine` (`ollama` or
        `lmstudio`) with `model` reserves a cell inside that engine, checked against the
        machine's report first. Answers `{ok, slot, cell}`, plus `nextPort` (what the next
        reservation would get) when `port` was omitted or `engine` given; 409 for a port
        already reserved, and 404 or 409 when the engine or its model is not there.
        """
        h.send_json(client_server_slot_add(body))
        return

@_route(POST_ROUTES, '/api/topology/server-slot/delete')
def _post_api_topology_server_slot_delete(h, parsed, body):
        """Remove a cell's slot from a machine and ask its scout to stop the cell

        `hostId` and `port` are required. The stop request to the scout is best effort, so
        an unreachable scout does not fail the call. Answers `{ok, removed}`, where
        `removed` says whether a slot was stored.
        """
        h.send_json(client_server_slot_delete(body))
        return

@_route(POST_ROUTES, '/api/topology/server-slot/note')
def _post_api_topology_server_slot_note(h, parsed, body):
        """Set the free-text note on a cell's card; an empty note clears it

        `hostId` and `port` pick the cell, and `note` is cut to 280 characters. Answers
        `{ok, key, note}`; 404 when the cell has no slot.
        """
        h.send_json({"ok": True, **set_server_slot_note(
            body.get("hostId"), body.get("port"), body.get("note"))})
        return

@_route(POST_ROUTES, '/api/topology/server-cell/action')
def _post_api_topology_server_cell_action(h, parsed, body):
        """Start, stop or restart a cell, or switch its autostart on or off, through its scout

        `action` is `start`, `stop`, `restart`, `enable` or `disable`; the last two turn the
        cell's autostart on or off, and a start uses the launch config saved on the cell. A
        `start` or `restart` of an engine cell whose model would not fit the free GPU memory
        answers `{ok: false, short}` (status 200) unless `force` is `true`. Answers `{ok,
        hostId, port, action, result}`; 400 for an unknown action, the controller's own id
        or a cell with no saved model.
        """
        h.send_json(server_cell_action(body))
        return

@_route(POST_ROUTES, '/api/models/gc')
def _post_api_models_gc(h, parsed, body):
        """Delete unreferenced model files from the controller's models directory

        `files` is a non-empty list of paths relative to that directory: GGUF files, or
        whole artifact folders such as a whisper cache or a checkpoint. Answers `{ok,
        deleted, freedGb}`; 409 refuses a model any cell references (a multi-part group
        counts as one), and 400 an empty list, a path outside the directory, or a path that
        is neither a GGUF nor a known folder.
        """
        h.send_json(delete_models(body))
        return

@_route(POST_ROUTES, '/api/topology/server-cell/schedule')
def _post_api_topology_server_cell_schedule(h, parsed, body):
        """Set the time window in which a cell is started and stopped by the clock

        `hostId` and `port` pick the cell; `schedule` is `{enabled, start, stop, days}`:
        `start` and `stop` are `HH:MM` (22:00 and 08:00 when empty), `days` are weekdays 0-6
        with Monday 0 (empty means every day), and a window may cross midnight. Answers
        `{ok, hostId, port, schedule}`; 404 when the cell has no slot, 400 for a malformed
        time or equal `start` and `stop` on an enabled window.
        """
        h.send_json(set_cell_schedule(body))
        return

@_route(POST_ROUTES, '/api/topology/server-cell/reassign-port')
def _post_api_topology_server_cell_reassign_port(h, parsed, body):
        """Move a cell to another free port, its cables following it

        `hostId`, `port` and `newPort` are required; `newPort` is checked against every
        cell, proxy route and port exclusion in the fleet, and the cell's saved config and
        its router references move with it. Meant for a stopped cell, which is not checked
        here. Answers `{ok, key, port, topology}`; 404 when the cell has no slot, 409 when
        `newPort` is taken, 400 when it equals `port`.
        """
        from caravan.admin.server_cells import reassign_server_slot_port
        result = reassign_server_slot_port(body)
        result["topology"] = topology_state(refresh_hosts=False)
        h.send_json(result)
        return

@_route(POST_ROUTES, '/api/topology/server-cell/swap-port')
def _post_api_topology_server_cell_swap_port(h, parsed, body):
        """Swap the ports of two cells, each keeping its cables

        `hostId` and `port` pick one cell and `targetPort` is the other cell's port, on any
        machine; both saved configs and router references trade places. Meant for stopped
        cells, which is not checked here. Answers `{ok, a, b, topology}` with each cell's
        new `{host, port}`; 404 when the first cell has no slot, 400 when `targetPort` is
        not a cell or equals `port`.
        """
        from caravan.admin.server_cells import swap_server_slot_ports
        result = swap_server_slot_ports(body)
        result["topology"] = topology_state(refresh_hosts=False)
        h.send_json(result)
        return

@_route(POST_ROUTES, '/api/topology/server-cell/save-config')
def _post_api_topology_server_cell_save_config(h, parsed, body):
        """Save a cell's launch config without starting it

        `hostId`, `port`, `config` and `cacheModels` are read; a cell that does not exist
        yet is created, its port checked as a reserve checks it (409 when taken). If the
        cell has autostart on, the scout's saved start request is refreshed too, and the
        answer carries `autostart: {ok, error?}`. Answers `{ok, hostId, port, state}` with
        `state` as in `GET /api/state`; 400 without `hostId` or `port`.
        """
        h.send_json(server_cell_save_config(body))
        return

@_route(POST_ROUTES, '/api/topology/client-llama/configs/save')
def _post_api_topology_client_llama_configs_save(h, parsed, body):
        """Save a launch config as a named backup for a machine, on the controller

        `hostId`, `name` and `config` (which must name `MODEL_FILE`) are required; `gpuName`
        picks the folder the file lands in, or `CPU` when `N_GPU_LAYERS` is 0. Answers `{ok,
        hostId, filename, savedAt}`; list the backups with `GET
        /api/topology/client-llama/configs`. 400 when a required field is missing.
        """
        h.send_json(client_llama_configs_save(body))
        return

@_route(POST_ROUTES, '/api/topology/client-llama/configs/delete')
def _post_api_topology_client_llama_configs_delete(h, parsed, body):
        """Delete a saved launch-config backup from the controller's store

        `hostId` and `filename` are required; `filename` is the host-relative path
        (`target/file.json`) that `GET /api/topology/client-llama/configs` lists. Answers
        `{ok, hostId, deleted}`; 404 when the backup does not exist, 400 for a missing field
        or a path outside that machine's folder.
        """
        h.send_json(client_llama_configs_delete(body))
        return

@_route(POST_ROUTES, '/api/topology/agent-route/context')
def _post_api_topology_agent_route_context(h, parsed, body):
        """Set the context window one agent gets on its primary or fallback port

        `hostId`, `agentId` and `role` (`primary` by default, or `fallback`) pick the route;
        `contextLength` is the token limit for this agent, and `contextAuto` publishes the
        model's own window even above that limit. Both are read together, so an omitted one
        is cleared. Answers the client's assignment row `{hostId, assignments}`; 404 when
        the agent has no such route.
        """
        h.send_json(set_agent_route_context(body))
        return

@_route(POST_ROUTES, '/api/topology/client/agent-alias')
def _post_api_topology_client_agent_alias(h, parsed, body):
        """Set the board name of one agent of a client; an empty name restores its own

        `hostId` and `agentId` pick the agent, and `name` is cut to 120 characters. Answers
        `{hostId, agentId, alias}`; 400 without `hostId` or `agentId`.
        """
        h.send_json(set_topology_agent_alias(body.get("hostId"), body.get("agentId"), body.get("name")))

@_route(POST_ROUTES, '/api/topology/agent-route/remove')
def _post_api_topology_agent_route_remove(h, parsed, body):
        """Remove one role's route (its port assignment) from an agent

        `hostId`, `agentId` and `role` (`primary` or `fallback`) are required. The port
        itself keeps listening and belongs to no agent afterwards. Answers the client's
        assignment row `{hostId, assignments}`; 404 when the agent has no assignment or no
        route in that role.
        """
        h.send_json(remove_agent_route(body))

@_route(POST_ROUTES, '/api/gpu-driver/update')
def _post_api_gpu_driver_update(h, parsed, body):
        """Install a GPU driver package on the controller's machine as a background job

        `package` must be a name such as `nvidia-driver-610-open` that apt offers (400 for
        another shape, 404 for one apt does not list). Under Secure Boot the matching signed
        kernel modules are installed with it when apt has them, and the running driver
        changes only after a reboot. Answers the job's state and log, the same shared job
        `GET /api/llamacpp/update-status` follows; 409 while another build or install job
        runs.
        """
        h.send_json(driver_update((body or {}).get("package")))
        return

@_route(POST_ROUTES, '/api/gpu-driver/auto')
def _post_api_gpu_driver_auto(h, parsed, body):
        """Turn the GPU driver watcher's checking and automatic installing on or off

        `check` and `install` are read together, so an omitted one means off, and `install`
        turns `check` on too. Answers the saved settings `{check, install, lastCheckAt,
        lastInstall}`.
        """
        h.send_json(set_auto_settings(body or {}))
        return

@_route(POST_ROUTES, '/api/topology/agent-route/model')
def _post_api_topology_agent_route_model(h, parsed, body):
        """Set the model name that one agent's port advertises to it

        `hostId`, `agentId` and `role` (`primary` by default) pick the route; `modelName`
        (cut to 120 characters) is the name the port advertises its model under in
        `/v1/models`, and `modelNameAuto` advertises the model under its own name instead.
        Both are read together, so an omitted one is cleared. Answers the client's
        assignment row `{hostId, assignments}`; 404 when the agent has no such route.
        """
        h.send_json(set_agent_route_model(body))

@_route(POST_ROUTES, '/api/topology/client/create')
def _post_api_topology_client_create(h, parsed, body):
        """Create a client record by hand, with one agent of the same name

        `hostId` (or `id`) is the new client's id, `name` its display name (the id when
        empty) and `ip` an optional source address. Answers the new record `{id, name,
        agents}` (plus `ip` when given); 400 for an empty id or one reserved for the
        controller, 409 when the client exists.
        """
        h.send_json(topology_client_create(body))
        return

@_route(POST_ROUTES, '/api/topology/client/delete')
def _post_api_topology_client_delete(h, parsed, body):
        """Delete a client record with its agents and assignment row

        `clientId` is required. A machine's host record with the same id is not touched.
        Answers `{ok, clientId}`; 404 for an unknown client.
        """
        h.send_json(topology_client_delete(body))
        return

@_route(POST_ROUTES, '/api/topology/scout/connect')
def _post_api_topology_scout_connect(h, parsed, body):
        """Add a machine to the fleet by pairing with the scout at its address

        `address` is a name or IP (a scheme or `:port` inside it is understood) and `port`
        defaults to 8092. The controller hands the scout its own address and the fleet token
        and returns once the scout's first heartbeat arrives; adding a scout that is here
        already is the connection test. Answers `{ok, hostId, name, scoutVersion, scoutUrl,
        controllerUrl}`; 409 for a scout older than 2.0 or paired with another controller,
        502 when nothing answers or the scout cannot reach the controller back.
        """
        h.send_json(SCOUT_PAIRING.connect(body.get("address"), body.get("port")))
        return

@_route(POST_ROUTES, '/api/topology/host/move-cells')
def _post_api_topology_host_move_cells(h, parsed, body):
        """Move every cell configured on one machine to another machine

        `from` and `to` are machine ids, for a machine that comes back under another name.
        Ports, router cables and each cell's config, model, label, note and history stay as
        they are. Answers `{ok, from, to, ports}`; 400 when an id is missing, both are the
        same or either is the controller, 404 when `from` has no cells, 409 when `to`
        already holds one of those ports (nothing is moved then).
        """
        h.send_json(move_host_cells(body))
        return

@_route(POST_ROUTES, '/api/topology/scout/disconnect')
def _post_api_topology_scout_disconnect(h, parsed, body):
        """Forget a machine and ask its scout to let go of this controller

        `hostId` is required. A silent scout (or one older than 2.1) cannot be told, so the
        machine is forgotten all the same (`unpaired: false`) and comes back with its next
        heartbeat if it still holds the controller's address; clients and cells are not
        touched. Answers `{ok, hostId, unpaired}`; 404 for an unknown machine, 502 when the
        scout refuses.
        """
        h.send_json(SCOUT_PAIRING.disconnect(body.get("hostId")))
        return

@_route(POST_ROUTES, '/api/topology/client/agent/delete')
def _post_api_topology_client_agent_delete(h, parsed, body):
        """Remove one agent from a client, with its assignment row

        `clientId` and `agentId` are required. The agent's ports stay, unclaimed
        (`freedPorts` names those no agent holds now), and the last agent takes its client
        with it. Answers `{ok, clientId, agentId, freedPorts, clientRemoved}`; 404 for an
        unknown client or agent.
        """
        h.send_json(topology_client_agent_delete(body))
        return


@_route(DELETE_ROUTES, '/api/hf/local-file')
def _delete_api_hf_local_file(h, parsed):
        """Delete one downloaded GGUF file of a Hugging Face repo from the models directory

        `repo` is the repo id (`author/name`) and `name` the file name, with no path
        separators; empty folders left behind are removed. Unlike `POST /api/models/gc` it
        does not check whether a cell uses the file. Answers `{ok: true}`, or `{ok: false,
        error}` with status 200 when a parameter is missing, the name is invalid, or the
        repo folder or file is not found.
        """
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        _name = (_q.get("name") or [""])[0].strip()
        h.send_json(hf_local_delete(_repo, _name))
        return




# ── Auth guard ────────────────────────────────────────────────────────────────
# Who may call what is ROUTE_ACCESS (caravan/admin/route_access.py): one rule
# for this guard, which enforces it, and for /openapi.json, which states it.


def _auth_guard(h, path, method):
    """Return True when the request may proceed; otherwise answer it and return False.

    EVERY rejection here ends the connection. do_POST calls this BEFORE
    read_body(), so a rejected POST leaves its body unread in the socket — and
    with keep-alive the next thing parsed off that socket is the leftover body,
    not a request line. It parses as garbage: the server answers
    `501 Unsupported method ('{"username":"a",…}GET')` and the real next request
    is never seen. Under HTTP/1.0 the close hid this; it is a rejection, so
    closing costs nothing and there is no reason to keep it.
    """
    if not auth_mod.auth_enabled():
        return True
    kind = ROUTE_ACCESS.kind(method, path)
    if kind == RouteAccess.PUBLIC:
        return True
    if kind == RouteAccess.METRICS:
        # The fleet token via either X-Caravan-Token or Authorization: Bearer;
        # without it, falls through to the session check.
        bearer = (h.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if auth_mod.fleet_token_verify(h.headers.get("X-Caravan-Token") or "") or \
           auth_mod.fleet_token_verify(bearer):
            return True
    if kind == RouteAccess.MACHINE:
        if auth_mod.fleet_token_verify(h.headers.get("X-Caravan-Token") or ""):
            return True
        h.close_connection = True
        h.send_json({"error": "fleet token required (X-Caravan-Token)"}, 401)
        return False
    sess = auth_mod.session_from_handler(h)
    if sess:
        if sess.get("role") == "viewer" and not ROUTE_ACCESS.viewer_may(method, path):
            h.close_connection = True
            h.send_json({"error": "read-only account"}, 403)
            return False
        return True
    if method == "GET" and (path == "/" or not path.startswith("/api/")):
        # Pages redirect to the login form; API calls get a plain 401.
        h.close_connection = True
        h.send_response(302)
        h.send_header("Location", "/login")
        h.send_header("Content-Length", "0")
        h.end_headers()
        return False
    h.close_connection = True
    h.send_json({"error": "authentication required"}, 401)
    return False


def _send_auth_page(h, page_html):
        # Built by hand rather than through send_file (the page is a string, not
        # a file on disk), which is why it was the one response left uncompressed
        # after everything else started gzipping — 22 KB, and the first thing
        # anyone gets, before they are even signed in.
        data, enc = h._maybe_gzip(page_html.encode("utf-8"))
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        if enc:
            h.send_header("Content-Encoding", enc)
            h.send_header("Vary", "Accept-Encoding")
        h.send_header("Content-Length", str(len(data)))
        h.send_header("Cache-Control", "no-cache")
        h.end_headers()
        h.wfile.write(data)


def _redirect(h, where):
        h.send_response(302)
        h.send_header("Location", where)
        h.send_header("Cache-Control", "no-cache")
        h.send_header("Content-Length", "0")
        h.end_headers()


# /login and /setup are a pair: each form has its own URL, and the server
# bounces to the one that matches the controller's auth state. Both redirects
# are load-bearing, not politeness — /login on a fresh controller is a form
# nobody can possibly sign in through (there are no accounts), and /setup on
# an enabled one advertises a wizard the API will refuse anyway.

@_route(GET_ROUTES, '/login')
def _get_login(h, parsed):
        """The sign-in page (HTML)

        Redirects (302) to `/setup` while the controller has no accounts.
        """
        if not auth_mod.auth_enabled():
            _redirect(h, "/setup")
            return
        _send_auth_page(h, auth_mod.login_page())
        return

@_route(GET_ROUTES, '/setup')
def _get_setup(h, parsed):
        """The first-run page that creates the first account (HTML)

        Redirects (302) to `/login` once an account exists.
        """
        if auth_mod.auth_enabled():
            _redirect(h, "/login")
            return
        _send_auth_page(h, auth_mod.setup_page())
        return

@_route(GET_ROUTES, '/api/auth/me')
def _get_auth_me(h, parsed):
        """Who the caller is: whether sign-in is on, and the session's user and role

        Answers `{enabled, authenticated, user, role}`; `user` and `role` are empty when
        there is no live session.
        """
        sess = auth_mod.session_from_handler(h)
        h.send_json({"enabled": auth_mod.auth_enabled(),
                     "authenticated": bool(sess),
                     "user": sess.get("user", ""), "role": sess.get("role", "")})
        return

@_route(POST_ROUTES, '/api/auth/login')
def _post_auth_login(h, parsed, body):
        """Sign in with a username and password and start a session

        Body: `username` and `password`. Sets the `caravan_session` cookie (HttpOnly, 30
        days) and answers `{ok, user}`; 401 for wrong credentials, 429 while the caller's
        address is locked out after repeated failures.
        """
        user = auth_mod.verify_login(str(body.get("username") or ""),
                                     str(body.get("password") or ""),
                                     ip=h.client_address[0])
        token = auth_mod.create_session(user["id"], ip=h.client_address[0],
                                        ua=h.headers.get("User-Agent") or "")
        data = json_bytes({"ok": True, "user": user["username"]})
        h.send_response(200)
        h.send_header("Content-Type", "application/json; charset=utf-8")
        h.send_header("Set-Cookie", auth_mod.session_cookie_header(token))
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return

@_route(POST_ROUTES, '/api/auth/setup')
def _post_auth_setup(h, parsed, body):
        """Create the first account, turn sign-in on and start its session

        Body: `username` (at most 64 characters) and `password` (at least 8); the account is
        an admin one and the fleet token is created with it. Sets the session cookie and
        answers `{ok, user, fleetToken}`; 409 once sign-in is already on.
        """
        # First-account bootstrap: only while auth is still off.
        if auth_mod.auth_enabled():
            raise AppError("auth is already enabled", 409)
        user = auth_mod.create_user(str(body.get("username") or ""),
                                    str(body.get("password") or ""))
        fleet = auth_mod.fleet_token_ensure()
        row = auth_mod.verify_login(user["username"], str(body.get("password") or ""),
                                    ip=h.client_address[0])
        token = auth_mod.create_session(row["id"], ip=h.client_address[0],
                                        ua=h.headers.get("User-Agent") or "")
        data = json_bytes({"ok": True, "user": user["username"], "fleetToken": fleet})
        h.send_response(200)
        h.send_header("Content-Type", "application/json; charset=utf-8")
        h.send_header("Set-Cookie", auth_mod.session_cookie_header(token))
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return

@_route(POST_ROUTES, '/api/auth/logout')
def _post_auth_logout(h, parsed, body):
        """End the caller's session and clear its cookie

        Always answers `{ok: true}`, also when there was no session.
        """
        raw = h.headers.get("Cookie") or ""
        from http import cookies as _ck
        try:
            jar = _ck.SimpleCookie(raw)
            morsel = jar.get(auth_mod.SESSION_COOKIE)
            if morsel:
                auth_mod.delete_session(morsel.value)
        except Exception:
            pass
        data = json_bytes({"ok": True})
        h.send_response(200)
        h.send_header("Content-Type", "application/json; charset=utf-8")
        h.send_header("Set-Cookie", auth_mod.session_cookie_header("", clear=True))
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return

@_route(GET_ROUTES, '/api/auth/overview')
def _get_auth_overview(h, parsed):
        """Accounts, live sessions and fleet-token status for the Security panel

        Answers `{enabled, user, role, users, sessions, fleetTokenSet}`: `users` are
        `{username, createdAt, role}` and `sessions` are `{id, username, createdAt,
        lastSeen, ip, ua}`, where the short `id` is what `POST /api/auth/sessions/revoke`
        takes. The token itself is never included.
        """
        sess = auth_mod.session_from_handler(h)
        h.send_json({
            "enabled": auth_mod.auth_enabled(),
            "user": sess.get("user", ""),
            "role": sess.get("role", ""),
            "users": auth_mod.list_users(),
            "sessions": auth_mod.list_sessions(),
            "fleetTokenSet": bool(auth_mod.fleet_token_get()),
        })
        return

@_route(POST_ROUTES, '/api/auth/users')
def _post_auth_users(h, parsed, body):
        """Manage accounts: create one, change its role or password, or delete it

        `action` is `create` (the default), `set-role`, `delete` or `set-password`, acting
        on `username` with `password` (8 characters at least) and `role` (`admin` or
        `viewer`). `create` answers `{ok, username, role}` and the others `{ok}`; deleting
        an account also ends its sessions. 404 for an unknown user, 409 for a name already
        taken, 400 for demoting the last admin, deleting the last user, a short password or
        an unknown action.
        """
        action = str(body.get("action") or "create")
        if action == "create":
            h.send_json({"ok": True, **auth_mod.create_user(
                str(body.get("username") or ""), str(body.get("password") or ""),
                role=str(body.get("role") or "admin"))})
            return
        if action == "set-role":
            auth_mod.set_role(str(body.get("username") or ""), str(body.get("role") or ""))
            h.send_json({"ok": True})
            return
        if action == "delete":
            auth_mod.delete_user(str(body.get("username") or ""))
            h.send_json({"ok": True})
            return
        if action == "set-password":
            auth_mod.set_password(str(body.get("username") or ""),
                                  str(body.get("password") or ""))
            h.send_json({"ok": True})
            return
        raise AppError("unknown action")

@_route(POST_ROUTES, '/api/auth/sessions/revoke')
def _post_auth_sessions_revoke(h, parsed, body):
        """End one session by its id, or every session except the caller's own

        Body: `id` (from `GET /api/auth/overview`) for one session, or `others: true` for
        all the rest. Answers `{ok}`, or `{ok, revoked}` with the count for `others`; 400
        without an `id`, 404 when no session is listed under exactly that `id` (the start
        of one does not name it). Nothing is ended in either case.
        """
        if body.get("others"):
            from http import cookies as _ck
            token = ""
            try:
                morsel = _ck.SimpleCookie(h.headers.get("Cookie") or "").get(auth_mod.SESSION_COOKIE)
                token = morsel.value if morsel else ""
            except Exception:
                pass
            h.send_json({"ok": True, "revoked": auth_mod.revoke_other_sessions(token)})
            return
        auth_mod.revoke_session(str(body.get("id") or ""))
        h.send_json({"ok": True})
        return

@_route(POST_ROUTES, '/api/auth/fleet-token')
def _post_auth_fleet_token(h, parsed, body):
        """Get the fleet token scouts use, creating it if missing, or replace it

        `regenerate: true` issues a new token and the old one stops working; a new token
        reaches each scout when it is added again with `POST /api/topology/scout/connect`.
        Answers `{ok, fleetToken}`.
        """
        if body.get("regenerate"):
            h.send_json({"ok": True, "fleetToken": auth_mod.fleet_token_regenerate()})
            return
        h.send_json({"ok": True, "fleetToken": auth_mod.fleet_token_ensure()})
        return


class Handler(BaseHTTPRequestHandler):
    server_version = f"lama-caravan/{APP_VERSION}"

    # Persistent connections. Answering HTTP/1.0 meant a fresh TCP connection per
    # request, and a cold board load is ~46 static modules plus its API calls —
    # which is how a five-deep accept queue came to be overflowed by a second
    # browser (see caravan/admin/main.py). A browser opens at most six sockets
    # per origin and reuses them, so the same load now costs six connections.
    #
    # This is only safe because every response here is framed: send_json and
    # send_file set an exact Content-Length, serve_model_file counts what it
    # actually wrote, _fail() refuses to write a second response into a body it
    # already began, and _auth_guard closes rather than leave an unread POST body
    # in the socket. Do NOT set this on BaseHTTPRequestHandler — oauth.py has a
    # handler that writes bodies with no length and must stay 1.0.
    protocol_version = "HTTP/1.1"

    # Without this the inherited timeout is None, and StreamRequestHandler.setup()
    # only calls settimeout when it is not None — so an idle kept-alive connection
    # would hold its thread until the client felt like closing. 30s is far longer
    # than any poll interval on the board and short enough that a walked-away tab
    # frees its threads. handle_one_request already treats a timeout as
    # close_connection.
    timeout = 30

    def send_response(self, *a, **kw):
        # Remember that a status line is on the wire. The catch-alls at the
        # bottom of do_GET/do_POST/do_DELETE answer with send_json, and for a
        # handler that fails BEFORE responding that is exactly right — but a
        # handler can also fail halfway through a body it has already begun.
        # serve_model_file streams a GGUF under a Content-Length taken from
        # stat(); a plain OSError mid-read (BrokenPipe and ConnectionReset it
        # handles itself) lands in the catch-all, which then writes a second
        # status line and a JSON error INTO the middle of the model. The scout
        # reads its Content-Length worth of bytes and stores a file that is part
        # weights, part HTTP — with a 200 and no error anywhere.
        self._responded = True
        return super().send_response(*a, **kw)

    def _fail(self, exc, status=500):
        """Answer an unhandled error, or — if the answer has already started —
        end the connection instead of corrupting what was being sent."""
        if getattr(self, "_responded", False):
            self.close_connection = True
            self.log_error("failed mid-response on %s: %r", self.path, exc)
            return
        self.send_json({"error": str(exc)}, status)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")

    # Below this, compressing costs more than it saves — the gzip header alone is
    # 18 bytes and a small JSON reply is mostly structure the CPU walks anyway.
    _GZIP_MIN = 1400

    def _maybe_gzip(self, data):
        """(body, encoding) — gzipped when the client asked and it is worth it.

        Nothing here was compressed, and this is JSON: the board's payloads are
        long runs of repeated keys, which is the shape gzip is best at. Measured
        on the real responses, roughly ten to one. It is also the change with the
        least in it — no payload moves, no logic moves, and a client that does
        not advertise gzip gets exactly the bytes it got before.

        level 6 rather than 9: past 6 the ratio barely moves on JSON and the CPU
        cost climbs, and this runs on the box that is also serving models.
        """
        if len(data) < self._GZIP_MIN:
            return data, None
        if "gzip" not in (self.headers.get("Accept-Encoding") or "").lower():
            return data, None
        try:
            return gzip.compress(data, 6), "gzip"
        except Exception:  # noqa: BLE001 — a failed compress must not lose the reply
            return data, None

    def send_json(self, payload, status=200):
        data, enc = self._maybe_gzip(json_bytes(payload))
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Without this browsers heuristically cache API fetch() responses:
        # /hf kept rendering a stale /api/hf/files payload even across a hard
        # reload (which only bypasses the cache for documents, not later XHR).
        self.send_header("Cache-Control", "no-store")
        if enc:
            self.send_header("Content-Encoding", enc)
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path, content_type):
        # Validate against an mtime+size ETag and force revalidation (no-cache), so a
        # redeploy is picked up immediately instead of serving a stale browser cache —
        # while still answering 304 when the file is unchanged.
        try:
            st = path.stat()
        except OSError:
            self.send_error(404)
            return
        etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        # Text compresses; a png or a woff2 is already compressed and gzipping it
        # spends CPU to add bytes.
        data = path.read_bytes()
        enc = None
        if content_type.split("/")[0] == "text" or content_type.split(";")[0] in (
                "application/javascript", "application/json", "image/svg+xml"):
            data, enc = self._maybe_gzip(data)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if enc:
            self.send_header("Content-Encoding", enc)
            # The ETag identifies the FILE, and both encodings carry the same
            # one — so a cache keyed on the ETag alone could hand a gzipped body
            # to a client that never asked for one.
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        # Content-Length is how we know where this request ends, and with
        # keep-alive it is also how we know where the NEXT one begins — so a
        # header we cannot act on has to end the connection rather than leave
        # the socket pointing into the middle of a body. Nothing in the fleet
        # sends chunked (urllib and the browser both set a length), but "we do
        # not expect it" is not a frame.
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            self.close_connection = True
            raise AppError("chunked request bodies are not accepted", 411)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            self.close_connection = True
            raise AppError("bad Content-Length", 400)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        # Every POST route here reads its input with body.get(...) — 46 of the 80
        # do it on the first line — so what reaches them has to be an object.
        # Left to json.loads alone, `null`, `[1,2]`, `"x"`, `5` and unparseable
        # bytes each became an AttributeError or a JSONDecodeError, which the
        # dispatcher turned into a 500 carrying the Python message to the client.
        # A client error announced as a server error is not just untidy: the
        # official OpenAI SDKs retry any 5xx twice, so a request that can never
        # succeed cost three round trips. No route wants a non-object body.
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise AppError("request body is not valid JSON", 400)
        if not isinstance(parsed, dict):
            # Named in the sender's vocabulary, not the interpreter's: the caller
            # wrote JSON and has no reason to know what NoneType is.
            kind = {type(None): "null", bool: "boolean", int: "number",
                    float: "number", str: "string", list: "array"}.get(type(parsed), "value")
            raise AppError(f"request body must be a JSON object, not {kind}", 400)
        return parsed

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if not _auth_guard(self, parsed.path, "GET"):
                return
            for route in GET_PREFIX_ROUTES:
                if route.matches(parsed.path):
                    route.handler(self, parsed)
                    return
            _fn = GET_ROUTES.get(parsed.path)
            if _fn is None:
                self.send_json({"error": "Not found"}, 404)
                return
            _fn(self, parsed)
        except AppError as exc:
            self._fail(exc, exc.status)
        except Exception as exc:
            self._fail(exc)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            if not _auth_guard(self, parsed.path, "POST"):
                return
            body = self.read_body()
            _fn = POST_ROUTES.get(parsed.path)
            if _fn is None:
                self.send_json({"error": "Not found"}, 404)
                return
            _fn(self, parsed, body)
        except AppError as exc:
            self._fail(exc, exc.status)
        except Exception as exc:
            self._fail(exc)

    def do_DELETE(self):
        try:
            parsed = urlparse(self.path)
            if not _auth_guard(self, parsed.path, "DELETE"):
                return
            _fn = DELETE_ROUTES.get(parsed.path)
            if _fn is None:
                self.send_json({"error": "Not found"}, 404)
                return
            _fn(self, parsed)
        except AppError as exc:
            # GET and POST have always honoured the status an AppError carries;
            # DELETE dropped it, so a handler raising AppError(..., 404) answered
            # 500 with the right words. One verb behaving differently from its
            # two neighbours is a defect waiting for the next DELETE route.
            self._fail(exc, exc.status)
        except Exception as exc:
            self._fail(exc)


def _spec_commit():
    # The same commit /health names; "" when the checkout has no git.
    try:
        return str((project_git_info() or {}).get("head") or "")
    except Exception:
        return ""


# The API as OpenAPI 3.1, for GET /openapi.json: built from the tables above,
# so it is defined after every route is registered.
API_SPEC = ApiSpec(GET_ROUTES, POST_ROUTES, DELETE_ROUTES, GET_PREFIX_ROUTES, ROUTE_ACCESS, APP_VERSION,
                   commit=_spec_commit)
