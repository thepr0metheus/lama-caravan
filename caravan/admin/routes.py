"""HTTP route tables and the request handler.

Every route body moved verbatim from the pre-split Handler if/elif chains.
Dispatch semantics preserved exactly: one prefix route (/api/monitor/) checked
first in GET; POST parses the JSON body before the path lookup (a bad body on
an unknown path is a 500, not a 404); DELETE has no AppError clause (-> 500).
"""
import base64
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


from caravan.common.errors import AppError
from caravan.common.fetch import fetch_json, fetch_text, post_json
from caravan.common.fsio import read_text
from caravan.common.jsonx import _INF, _json_safe, json_bytes
from caravan.common.procs import run, run_in
from caravan.admin.paths import (
    ADMIN_STATE_FILE,
    AGENT_PROXY_CONFIG_FILE,
    AGENT_PROXY_LOG_DIR,
    AGENT_PROXY_SERVICE_NAME,
    AGENT_PROXY_STATE_FILE,
    CLIENT_LABELS_FILE,
    CLOUD_PROVIDERS_FILE,
    DEFAULT_MODELS_DIR,
    FLEET_REGISTRY_URL,
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
    OPENCLAW_CONFIG_CACHE_FILE,
    OPENCLAW_CONFIG_MANAGERS,
    PORT,
    PROJECT_ROOT,
    PROVIDER_SECRETS_FILE,
    SERVER_BACKUPS_DIR,
    SERVER_CELLS_DIR,
    SERVER_CELL_BASE_PORT,
    SERVICE_NAME,
    START_SCRIPT,
    STATIC_DIR,
    TOKEN_HISTORY_FILE,
    TOKEN_HISTORY_MAX,
    TOKEN_HISTORY_RETENTION_SEC,
    TOPOLOGY_CLIENT_TTL,
    _BENCH_CACHE_DIR,
)
from caravan.admin.state import admin_state, load_admin_state, save_admin_state, topology_store
from caravan.admin.backups import backup_config, backups, delete_backup, resolve_backup_path, revert_latest
from caravan import __version__ as APP_VERSION
from caravan.admin.cell_schedule import set_cell_schedule
from caravan.admin.metrics import build_metrics_text
from caravan.admin.model_gc import delete_models, list_unused_models
from caravan.admin import auth as auth_mod
from caravan.admin.status import controller_info, do_action, llama_builds_list, llama_cpp_info, llama_suspect_dismiss, llama_update_status, models_disk, start_llama_restore, start_llama_update, state
from caravan.admin.cell_ops import (
    client_server_slot_add,
    client_server_slot_delete,
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
    move_server_cell,
    next_server_cell_port,
    normalize_topology_agent,
    reserve_server_cell,
    server_slot_key,
    set_server_slot_note,
    upsert_server_slot,
    used_server_cell_ports,
)
from caravan.admin.fleet_clients import (
    _backup_meta,
    _backup_target_seg,
    _client_agent_url,
    _safe_path_seg,
    auto_provision_agent_proxies,
    client_llama_configs,
    client_llama_configs_delete,
    client_llama_configs_save,
    client_llama_list_cache,
    client_llama_purge_cache,
    client_llama_builds,
    client_llama_restore,
    client_llama_start,
    client_llama_stop,
    client_llama_update,
    client_llama_update_status,
    client_monitor,
    refresh_topology_clients_from_agents,
    set_topology_client_alias,
    topology_client_agent_delete,
    topology_client_delete,
    topology_clients,
    topology_discover_add,
    topology_orphan_assignment_delete,
    update_topology_client,
)
from caravan.admin.topology import (
    apply_topology_assignments,
    normalize_topology_assignment,
    topology_nodes,
    topology_server,
    topology_state,
)
from caravan.admin.proxy_ops import reconcile_agent_proxies, stop_agent_proxy_route
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
from caravan.admin.openclaw import (
    _queue_thresholds_cache,
    _queue_thresholds_lock,
    _queue_thresholds_refresh_loop,
    compute_queue_thresholds,
    fetch_openclaw_config_for,
    load_openclaw_cache,
    notify_openclaw_config_managers,
    openclaw_config_manager_state,
    openclaw_configs_snapshot,
    sync_wait_timeouts_from_openclaw,
)
from caravan.admin.llama_metrics import parse_llamacpp_metrics, runtime_metrics_sample
from caravan.admin.token_history import (
    controller_gen_tps_samples,
    controller_llama_ports,
    controller_token_metrics,
    load_token_history,
    record_controller_gen_tps,
    record_token_history,
    save_token_history,
    token_history_query,
)
from caravan.admin.proxy_stats import (
    agent_proxy_sample,
    iso_seconds,
    list_agent_proxy_log_dates,
    load_agent_proxy_logs,
    nearest_event,
    proxy_daily_stats,
    proxy_item_timestamp,
    proxy_usage_tokens,
    requests_by_client,
    summarize_proxy_item,
)
from caravan.admin.monitoring import (
    append_incidents_from_sample,
    cpu_snapshot,
    gpu_compute_apps,
    llama_activity_cache,
    runtime_api,
    collect_monitor_sample,
    correlate_activity,
    cpu_state,
    gpu_state,
    incident_lock,
    llama_activity_sample,
    llama_clients_sample,
    load_client_labels,
    load_incident_log,
    load_monitor_history,
    memory_state,
    monitor_history,
    monitor_lock,
    monitor_retention_seconds,
    monitor_sampler_loop,
    monitor_snapshot,
    persist_monitor_history,
    save_client_labels,
    set_client_label,
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
    delete_bridge_port,
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
    set_cloud_block_exposed,
    upsert_cloud_account,
    upsert_cloud_block,
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
from caravan.admin.downloads import _download_jobs, _download_jobs_lock, start_hf_download
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
    cell_service_action,
    cell_service_name,
    cell_service_status,
    ensure_cell_service_template,
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
from caravan.admin.launch import (
    LAUNCH_COMMAND_BEGIN,
    LAUNCH_COMMAND_END,
    _sanitize_snapshot_name,
    render_command_cell_script,
    render_launch_script,
    render_server_cell_script,
    save_config,
    server_cell_dir,
    snapshot_config,
    write_server_cell_artifacts,
)


# --- HuggingFace Browser ---


# ── HF Benchmarks ─────────────────────────────────────────────────────────────


# ── Open LLM Leaderboard background cache ─────────────────────────────────────


# ── Benchmark result cache (persistent JSON) ──────────────────────────────────


# ── HF Download ───────────────────────────────────────────────────────────────


# ---- OAuth (authorization-code + PKCE) for cloud accounts ----




GET_PREFIX_ROUTES = []
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
    # /js/<name>.js and /css/<name>.css — ES modules and split stylesheets.
    # The filename class has no "/" or "..", so no traversal is possible.
    m = re.fullmatch(r"/(js|css)/([A-Za-z0-9._-]+)", parsed.path)
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
        kind = parsed.path.rsplit("/", 1)[-1]
        h.send_json(monitor_snapshot(kind))
        return

@_route(GET_ROUTES, '/api/system-monitor')
def _get_api_system_monitor(h, parsed):
        h.send_json(system_monitor_state())
        return

@_route(GET_ROUTES, '/api/topology')
def _get_api_topology(h, parsed):
        h.send_json(topology_state())
        return

@_route(GET_ROUTES, '/api/models')
def _get_api_models(h, parsed):
        h.send_json(list_gguf_models())
        return

@_route(GET_ROUTES, '/api/hf/token')
def _get_api_hf_token(h, parsed):
        token = admin_state.get("hfToken") or ""
        masked = ("●●●●" + token[-4:]) if len(token) >= 8 else ("set" if token else "")
        h.send_json({"ok": True, "set": bool(token), "masked": masked})
        return

@_route(GET_ROUTES, '/api/hf/download/status')
def _get_api_hf_download_status(h, parsed):
        _q2 = urllib.parse.parse_qs(parsed.query or "")
        _jid = (_q2.get("job") or [""])[0].strip()
        with _download_jobs_lock:
            _job = dict(_download_jobs.get(_jid) or {})
        h.send_json({"ok": True, **_job} if _job else {"ok": False, "error": "job not found"})
        return

@_route(GET_ROUTES, '/api/hf/download/jobs')
def _get_api_hf_download_jobs(h, parsed):
        _now = time.time()
        with _download_jobs_lock:
            for _k in [k for k, v in _download_jobs.items()
                       if v.get("finished_at") and _now - v["finished_at"] > 300]:
                _download_jobs.pop(_k, None)
            _jobs = [{"jobId": k, **v} for k, v in _download_jobs.items()
                     if v.get("status") != "done"]
        h.send_json({"ok": True, "jobs": _jobs})
        return

@_route(GET_ROUTES, '/api/hf/favorites')
def _get_api_hf_favorites(h, parsed):
        h.send_json({"ok": True, "favorites": admin_state.get("hfFavorites", [])})
        return

@_route(GET_ROUTES, '/api/hf/search')
def _get_api_hf_search(h, parsed):
        _q = urllib.parse.parse_qs(parsed.query or "")
        _query = (_q.get("q") or [""])[0].strip()
        _limit = (_q.get("limit") or ["20"])[0]
        h.send_json(hf_search(_query, _limit))
        return

@_route(GET_ROUTES, '/api/hf/files')
def _get_api_hf_files(h, parsed):
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        h.send_json(hf_list_files(_repo) if _repo else {"ok": False, "error": "missing repo"})
        return

@_route(GET_ROUTES, '/api/hf/model-tree')
def _get_api_hf_model_tree(h, parsed):
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        h.send_json(hf_model_tree(_repo) if _repo else {"ok": False, "error": "missing repo"})
        return

@_route(GET_ROUTES, '/api/hf/local-check')
def _get_api_hf_local_check(h, parsed):
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        h.send_json(hf_local_check(_repo))
        return

@_route(GET_ROUTES, '/api/hf/benchmarks')
def _get_api_hf_benchmarks(h, parsed):
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        _force = (_q.get("force") or [""])[0] == "1"
        h.send_json(hf_get_benchmarks(_repo, force=_force) if _repo else {"ok": False, "error": "missing repo"})
        return

@_route(GET_ROUTES, '/api/hf/benchmarks/status')
def _get_api_hf_benchmarks_status(h, parsed):
        _ensure_llm_lb()
        h.send_json({"ok": True, **_llm_lb_status()})
        return

@_route(GET_ROUTES, '/api/hf/reference-models')
def _get_api_hf_reference_models(h, parsed):
        _rfq = urllib.parse.parse_qs(parsed.query or "")
        _rf_force = (_rfq.get("force") or [""])[0] == "1"
        h.send_json(hf_get_reference_models(force=_rf_force))
        return

@_route(GET_ROUTES, '/api/hf/bench-search')
def _get_api_hf_bench_search(h, parsed):
        _bsq = urllib.parse.parse_qs(parsed.query or "")
        _bname = (_bsq.get("q") or [""])[0].strip()
        h.send_json(hf_bench_search(_bname))
        return

@_route(GET_ROUTES, '/api/models/download')
def _get_api_models_download(h, parsed):
        serve_model_file(h, parsed.query)
        return

@_route(GET_ROUTES, '/api/topology/client-monitor')
def _get_api_topology_client_monitor(h, parsed):
        import urllib.parse as _up
        _q = _up.parse_qs(parsed.query or "")
        _host = (_q.get("hostId") or [""])[0].strip()
        _kind = (_q.get("kind") or ["nvidia-smi"])[0].strip()
        h.send_json(client_monitor(_host, _kind))
        return

@_route(GET_ROUTES, '/api/fleet/llama-update-status')
def _get_api_fleet_llama_update_status(h, parsed):
        import urllib.parse as _up
        _q = _up.parse_qs(parsed.query or "")
        h.send_json(client_llama_update_status((_q.get("hostId") or [""])[0].strip()))
        return

@_route(GET_ROUTES, '/api/fleet/llama-builds')
def _get_api_fleet_llama_builds(h, parsed):
        import urllib.parse as _up
        _q = _up.parse_qs(parsed.query or "")
        h.send_json(client_llama_builds((_q.get("hostId") or [""])[0].strip()))
        return

@_route(GET_ROUTES, '/api/topology/client-llama/configs')
def _get_api_topology_client_llama_configs(h, parsed):
        import urllib.parse as _up2
        _q2 = _up2.parse_qs(parsed.query or "")
        _host2 = (_q2.get("hostId") or [""])[0].strip()
        h.send_json(client_llama_configs(_host2))
        return

@_route(GET_ROUTES, '/api/topology/client-llama/list-cache')
def _get_api_topology_client_llama_list_cache(h, parsed):
        import urllib.parse as _up3
        _q3 = _up3.parse_qs(parsed.query or "")
        _host3 = (_q3.get("hostId") or [""])[0].strip()
        h.send_json(client_llama_list_cache(_host3))
        return

@_route(GET_ROUTES, '/api/queue-thresholds')
def _get_api_queue_thresholds(h, parsed):
        with _queue_thresholds_lock:
            data = _queue_thresholds_cache.get("data")
        h.send_json({"ok": True, "thresholds": data})
        return

@_route(GET_ROUTES, '/api/agent-proxies/raw')
def _get_api_agent_proxies_raw(h, parsed):
        try:
            content = AGENT_PROXY_CONFIG_FILE.read_text(encoding="utf-8") if AGENT_PROXY_CONFIG_FILE.exists() else ""
        except Exception as exc:
            content = f"(unable to read {AGENT_PROXY_CONFIG_FILE}: {exc})"
        h.send_json({"ok": True, "path": str(AGENT_PROXY_CONFIG_FILE), "content": content})
        return

@_route(GET_ROUTES, '/api/cloud-accounts/oauth/status')
def _get_api_cloud_accounts_oauth_status(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        status = oauth_login_status((query.get("state") or [""])[0])
        if status.get("state") == "done":
            status["topology"] = topology_state(refresh_clients=False)
        h.send_json(status)
        return

@_route(GET_ROUTES, '/api/cloud-accounts/models')
def _get_api_cloud_accounts_models(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        models = fetch_account_models(account_id)
        h.send_json({"ok": True, "models": models})
        return

@_route(GET_ROUTES, '/api/cloud-accounts/subscription-models')
def _get_api_cloud_accounts_subscription_models(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        models = fetch_subscription_models(account_id)
        h.send_json({"ok": True, "models": models})
        return

@_route(GET_ROUTES, '/api/cloud-accounts/subscription-usage')
def _get_api_cloud_accounts_subscription_usage(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        usage = fetch_subscription_usage(account_id)
        h.send_json(usage)
        return

@_route(GET_ROUTES, '/api/cloud-accounts/api-costs')
def _get_api_cloud_accounts_api_costs(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        h.send_json(fetch_account_costs(account_id))
        return

@_route(GET_ROUTES, '/api/cloud-accounts/openrouter-limits')
def _get_api_cloud_accounts_openrouter_limits(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        account_id = (query.get("id") or [""])[0].strip()
        h.send_json(fetch_openrouter_limits(account_id))
        return

@_route(GET_ROUTES, '/api/cloud-accounts/proxy-spend')
def _get_api_cloud_accounts_proxy_spend(h, parsed):
        h.send_json({"ok": True, "spend": cloud_spend_summary()})
        return

@_route(GET_ROUTES, '/api/usage-stats')
def _get_api_usage_stats(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        try:
            days = int((query.get("days") or ["30"])[0])
        except ValueError:
            days = 30
        h.send_json(usage_stats(days))
        return

@_route(GET_ROUTES, '/api/local-pricing')
def _get_api_local_pricing(h, parsed):
        h.send_json({"ok": True, "rate": admin_state.get("localPricing") or {}})
        return

@_route(GET_ROUTES, '/api/api-pricing')
def _get_api_api_pricing(h, parsed):
        h.send_json({"ok": True, "pricing": admin_state.get("apiPricing") or {}})
        return

@_route(GET_ROUTES, '/api/token-history')
def _get_api_token_history(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        h.send_json({
            "samples": token_history_query(
                (query.get("client") or [""])[0].strip(),
                (query.get("range") or ["all"])[0].strip(),
                port=(query.get("port") or [""])[0].strip() or None,
            ),
        })
        return

@_route(GET_ROUTES, '/api/openclaw-config')
def _get_api_openclaw_config(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        force = (query.get("refresh") or ["0"])[0] in {"1", "true", "yes"}
        client = (query.get("client") or [""])[0].strip()
        snapshot = openclaw_configs_snapshot(force=force)
        if client:
            h.send_json(snapshot.get(client) or {"ok": False, "error": "unknown client"})
        else:
            h.send_json(snapshot)
        return

@_route(GET_ROUTES, '/api/topology/agent-openclaw')
def _get_api_topology_agent_openclaw(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        client_id = (query.get("client") or [""])[0].strip()
        agent_id = (query.get("agent") or [""])[0].strip()
        if not client_id or not agent_id:
            h.send_json({"ok": False, "error": "client and agent params required"}, 400)
            return
        assignments = admin_state.get("topology", {}).get("assignments", {})
        agent_url = str((assignments.get(client_id) or {}).get("agentUrl") or "").rstrip("/")
        if not agent_url:
            h.send_json({"ok": False, "error": f"no agentUrl registered for client '{client_id}'"})
            return
        try:
            result = fetch_json(f"{agent_url}/api/agent-config?id={urllib.parse.quote(agent_id)}", timeout=5)
            h.send_json(result)
        except Exception as exc:
            h.send_json({"ok": False, "error": str(exc)})
        return

@_route(GET_ROUTES, '/api/agent-proxy-logs')
def _get_api_agent_proxy_logs(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        h.send_json(load_agent_proxy_logs(
            (query.get("date") or [""])[0],
            (query.get("limit") or ["200"])[0],
            (query.get("event") or [""])[0],
            (query.get("port") or [""])[0],
            (query.get("route") or [""])[0],
            (query.get("client") or [""])[0],
            (query.get("errors") or [""])[0] in ("1", "true", "yes"),
            (query.get("slim") or [""])[0] in ("1", "true", "yes"),
            (query.get("summary") or [""])[0] in ("1", "true", "yes"),
            (query.get("since") or [""])[0],
        ))
        return

@_route(GET_ROUTES, '/api/proxy-daily-stats')
def _get_api_proxy_daily_stats(h, parsed):
        query = urllib.parse.parse_qs(parsed.query or "")
        h.send_json(proxy_daily_stats((query.get("date") or [""])[0] or None))
        return

@_route(GET_ROUTES, '/api/model-pricing')
def _get_api_model_pricing(h, parsed):
        h.send_json({"ok": True, "pricing": fetch_model_pricing()})
        return

@_route(GET_ROUTES, '/api/state')
def _get_api_state(h, parsed):
        h.send_json(state())
        return

@_route(GET_ROUTES, '/api/raw/start-server')
def _get_api_raw_start_server(h, parsed):
        h.send_json({"text": read_text(START_SCRIPT)})
        return

@_route(GET_ROUTES, '/api/controller-info')
def _get_api_controller_info(h, parsed):
        h.send_json(controller_info())
        return

@_route(GET_ROUTES, '/api/models/disk')
def _get_api_models_disk(h, parsed):
        h.send_json(models_disk())
        return

@_route(GET_ROUTES, '/metrics')
def _get_metrics(h, parsed):
        data = build_metrics_text().encode("utf-8")
        h.send_response(200)
        h.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return

@_route(GET_ROUTES, '/api/models/unused')
def _get_api_models_unused(h, parsed):
        h.send_json(list_unused_models())
        return

@_route(GET_ROUTES, '/api/llamacpp')
def _get_api_llamacpp(h, parsed):
        h.send_json(llama_cpp_info(fetch_remote=True))
        return

@_route(GET_ROUTES, '/api/llamacpp/update-status')
def _get_api_llamacpp_update_status(h, parsed):
        h.send_json(llama_update_status())
        return

@_route(GET_ROUTES, '/api/llamacpp/builds')
def _get_api_llamacpp_builds(h, parsed):
        h.send_json(llama_builds_list())
        return

@_route(GET_ROUTES, '/api/backup')
def _get_api_backup(h, parsed):
        query = dict(item.split("=", 1) for item in parsed.query.split("&") if "=" in item)
        h.send_json(backup_config(urllib.parse.unquote(query.get("path", ""))))
        return

@_route(GET_ROUTES, '/', '/index.html')
def _get_root(h, parsed):
        h.send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/hf')
def _get_hf(h, parsed):
        h.send_file(STATIC_DIR / "hf.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/kanban', '/router')
def _get_kanban(h, parsed):
        h.send_file(STATIC_DIR / "kanban.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/system')
def _get_system(h, parsed):
        h.send_file(STATIC_DIR / "system.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/models')
def _get_models(h, parsed):
        h.send_file(STATIC_DIR / "models.html", "text/html; charset=utf-8")
        return

@_route(GET_ROUTES, '/hf.js')
def _get_hf_js(h, parsed):
        h.send_file(STATIC_DIR / "hf.js", "application/javascript; charset=utf-8")
        return

@_route(GET_ROUTES, '/favicon.svg', '/favicon.ico')
def _get_favicon_svg(h, parsed):
        h.send_file(STATIC_DIR / "favicon.svg", "image/svg+xml")
        return


GET_PREFIX_ROUTES = [
    ('/api/monitor/', _get_api_monitor),
    ('/js/', _get_static_subdir),
    ('/css/', _get_static_subdir),
]


@_route(POST_ROUTES, '/api/hf/download')
def _post_api_hf_download(h, parsed, body):
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
        _token = admin_state.get("hfToken") or ""
        _jid = start_hf_download(_repo, _files, _models_dir, _token)
        h.send_json({"ok": True, "jobId": _jid})
        return

@_route(POST_ROUTES, '/api/hf/token')
def _post_api_hf_token(h, parsed, body):
        token = str(body.get("token") or "").strip()
        admin_state["hfToken"] = token
        _hf_cache.clear()
        save_admin_state()
        masked = ("●●●●" + token[-4:]) if len(token) >= 8 else ("set" if token else "")
        h.send_json({"ok": True, "set": bool(token), "masked": masked})
        return

@_route(POST_ROUTES, '/api/hf/favorites')
def _post_api_hf_favorites(h, parsed, body):
        favs = body.get("favorites")
        if isinstance(favs, list):
            admin_state["hfFavorites"] = favs
            save_admin_state()
        h.send_json({"ok": True})
        return

@_route(POST_ROUTES, '/api/aa-scores')
def _post_api_aa_scores(h, parsed, body):
        _ids = body.get("models")
        if not isinstance(_ids, list):
            h.send_json({"ok": False, "error": "models must be a list"})
            return
        h.send_json(hf_get_aa_scores([str(m) for m in _ids][:400],
                                         do_fetch=body.get("fetch", True) is not False))
        return

@_route(POST_ROUTES, '/api/config')
def _post_api_config(h, parsed, body):
        cfg = body.get("config") or {}
        old_cell_port = body.get("cellPort")
        cell_port = None
        if old_cell_port not in (None, ""):
            old_cell_port = int(old_cell_port)
            new_port = int((cfg or {}).get("PORT") or old_cell_port)
            cell_port = new_port
            if new_port != old_cell_port:
                move_server_cell("skynet", old_cell_port, new_port,
                                 config=cfg, model=(cfg or {}).get("MODEL_FILE"))
            else:
                assert_server_cell_port_available(new_port, exclude_key=server_slot_key("skynet", new_port))
                upsert_server_slot("skynet", new_port, config=cfg, model=(cfg or {}).get("MODEL_FILE"))
        backup = None if cell_port else save_config(cfg)
        action_result = None
        if body.get("restart"):
            if cell_port:
                action_result = cell_service_action(cell_port, "restart")
            else:
                action_result = do_action("restart")
        h.send_json({"ok": True, "backup": backup, "action": action_result,
                        "cellPort": cell_port, "state": state()})
        return

@_route(POST_ROUTES, '/api/config/snapshot')
def _post_api_config_snapshot(h, parsed, body):
        snapshot = snapshot_config(body.get("name"), body.get("config"))
        h.send_json({"ok": True, "snapshot": snapshot, "state": state()})
        return

@_route(POST_ROUTES, '/api/llama-command-preview')
def _post_api_llama_command_preview(h, parsed, body):
        cfg = body.get("config") if isinstance(body.get("config"), dict) else {}
        try:
            tokens = build_local_llama_command(cfg)
        except AppError as exc:
            h.send_json({"ok": False, "error": str(exc), "tokens": []})
            return
        h.send_json({"ok": True, "tokens": tokens, "command": " ".join(tokens)})
        return

@_route(POST_ROUTES, '/api/parse-extra-args')
def _post_api_parse_extra_args(h, parsed, body):
        result = parse_extra_args(body.get("extraArgs") or body.get("text") or "")
        h.send_json({"ok": True, **result})
        return

@_route(POST_ROUTES, '/api/config-favorites')
def _post_api_config_favorites(h, parsed, body):
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

@_route(POST_ROUTES, '/api/action')
def _post_api_action(h, parsed, body):
        result = do_action(str(body.get("action", "")))
        h.send_json({"ok": True, "result": result, "state": state()})
        return

@_route(POST_ROUTES, '/api/repair/user-service')
def _post_api_repair_user_service(h, parsed, body):
        result = repair_user_service()
        h.send_json({"ok": True, "result": result, "state": state()})
        return

@_route(POST_ROUTES, '/api/revert')
def _post_api_revert(h, parsed, body):
        result = revert_latest()
        if body.get("restart"):
            result["restart"] = do_action("restart")
        h.send_json({"ok": True, "result": result, "state": state()})
        return

@_route(POST_ROUTES, '/api/backup/delete')
def _post_api_backup_delete(h, parsed, body):
        result = delete_backup(str(body.get("path", "")))
        h.send_json({"ok": True, "result": result, "state": state()})
        return

@_route(POST_ROUTES, '/api/llamacpp/update')
def _post_api_llamacpp_update(h, parsed, body):
        job = start_llama_update(str((body or {}).get("tag") or ""))
        h.send_json({"ok": True, "job": job})
        return

@_route(POST_ROUTES, '/api/llamacpp/restore')
def _post_api_llamacpp_restore(h, parsed, body):
        job = start_llama_restore(str((body or {}).get("id") or ""))
        h.send_json({"ok": True, "job": job})
        return

@_route(POST_ROUTES, '/api/llamacpp/suspect-dismiss')
def _post_api_llamacpp_suspect_dismiss(h, parsed, body):
        h.send_json(llama_suspect_dismiss())
        return

@_route(POST_ROUTES, '/api/system-monitor/settings')
def _post_api_system_monitor_settings(h, parsed, body):
        set_monitor_retention(body.get("retentionSeconds"))
        h.send_json({"ok": True, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/local-pricing')
def _post_api_local_pricing(h, parsed, body):
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

@_route(POST_ROUTES, '/api/system-monitor/client-label')
def _post_api_system_monitor_client_label(h, parsed, body):
        h.send_json({"ok": True, "result": set_client_label(body.get("ip"), body.get("label"))})
        return

@_route(POST_ROUTES, '/api/agent-proxies/config')
def _post_api_agent_proxies_config(h, parsed, body):
        result = save_agent_proxy_config(body.get("routes") or [], body.get("routers"))
        h.send_json({"ok": True, "config": result, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/agent-proxies/policy')
def _post_api_agent_proxies_policy(h, parsed, body):
        result = set_agent_proxy_policy(body.get("policy") or body)
        threading.Thread(target=compute_queue_thresholds, daemon=True).start()
        h.send_json({"ok": True, "config": result, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/agent-proxies/route-policy')
def _post_api_agent_proxies_route_policy(h, parsed, body):
        result = set_agent_proxy_route_policy(body.get("port"), body)
        h.send_json({"ok": True, "config": result, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/agent-proxies/reconcile')
def _post_api_agent_proxies_reconcile(h, parsed, body):
        result = reconcile_agent_proxies()
        h.send_json({"ok": True, "result": result, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/agent-proxies/routers', '/api/agent-proxies/switchboards')
def _post_api_agent_proxies_routers(h, parsed, body):
        result = set_routers(body.get("routers") or body.get("switchboards") or [])
        h.send_json({"ok": True, "config": result, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/agent-proxies/stop')
def _post_api_agent_proxies_stop(h, parsed, body):
        result = stop_agent_proxy_route(body.get("port"), body.get("requestId"))
        h.send_json({"ok": True, "result": result, "monitor": system_monitor_state()})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/bridge-port')
def _post_api_cloud_bridge_port(h, parsed, body):
        route = mint_bridge_port(body.get("blockId"), body.get("label"))
        h.send_json({"ok": True, "route": route})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/bridge-port-delete')
def _post_api_cloud_bridge_port_delete(h, parsed, body):
        h.send_json({"ok": True, **delete_bridge_port(body.get("port"))})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/auto-create-blocks')
def _post_api_cloud_accounts_auto_create_blocks(h, parsed, body):
        account_id = str(body.get("id") or "").strip()
        result = auto_create_blocks(account_id)
        h.send_json({"ok": True, **result, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/save')
def _post_api_cloud_accounts_save(h, parsed, body):
        account = upsert_cloud_account(body.get("account") or {})
        h.send_json({"ok": True, "account": account, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/delete')
def _post_api_cloud_accounts_delete(h, parsed, body):
        delete_cloud_account(body.get("id"))
        h.send_json({"ok": True, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/key')
def _post_api_cloud_accounts_key(h, parsed, body):
        result = set_account_key(body.get("id"), body.get("apiKey"))
        result["topology"] = topology_state(refresh_clients=False)
        h.send_json(result)
        return

@_route(POST_ROUTES, '/api/cloud-accounts/key-delete')
def _post_api_cloud_accounts_key_delete(h, parsed, body):
        delete_account_credential(body.get("id"))
        h.send_json({"ok": True, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/cloud-accounts/oauth/start')
def _post_api_cloud_accounts_oauth_start(h, parsed, body):
        result = start_oauth_login(body.get("id"))
        h.send_json({"ok": True, **result})
        return

@_route(POST_ROUTES, '/api/cloud-blocks/save')
def _post_api_cloud_blocks_save(h, parsed, body):
        block = upsert_cloud_block(body.get("block") or {})
        h.send_json({"ok": True, "block": block, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/cloud-blocks/delete')
def _post_api_cloud_blocks_delete(h, parsed, body):
        delete_cloud_block(body.get("id"))
        h.send_json({"ok": True, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/cloud-blocks/expose')
def _post_api_cloud_blocks_expose(h, parsed, body):
        set_cloud_block_exposed(body.get("id"), bool(body.get("exposed")))
        h.send_json({"ok": True, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/queue-thresholds/recalc')
def _post_api_queue_thresholds_recalc(h, parsed, body):
        threading.Thread(target=lambda: (sync_wait_timeouts_from_openclaw(), compute_queue_thresholds()), daemon=True).start()
        with _queue_thresholds_lock:
            data = _queue_thresholds_cache.get("data")
        h.send_json({"ok": True, "thresholds": data})
        return

@_route(POST_ROUTES, '/api/topology/client-heartbeat')
def _post_api_topology_client_heartbeat(h, parsed, body):
        client = update_topology_client(body)
        h.send_json({"ok": True, "client": client})
        return

@_route(POST_ROUTES, '/api/topology/assignments')
def _post_api_topology_assignments(h, parsed, body):
        result = apply_topology_assignments(body)
        h.send_json({"ok": True, "result": result, "topology": topology_state()})
        return

@_route(POST_ROUTES, '/api/topology/client-alias')
def _post_api_topology_client_alias(h, parsed, body):
        result = set_topology_client_alias(body.get("hostId"), body.get("name"))
        h.send_json({"ok": True, "result": result, "topology": topology_state(refresh_clients=False)})
        return

@_route(POST_ROUTES, '/api/topology/client-llama/start')
def _post_api_topology_client_llama_start(h, parsed, body):
        h.send_json(client_llama_start(body))
        return

@_route(POST_ROUTES, '/api/fleet/llama-update')
def _post_api_fleet_llama_update(h, parsed, body):
        h.send_json(client_llama_update(body))
        return

@_route(POST_ROUTES, '/api/fleet/llama-restore')
def _post_api_fleet_llama_restore(h, parsed, body):
        h.send_json(client_llama_restore(body))
        return

@_route(POST_ROUTES, '/api/topology/client-llama/stop')
def _post_api_topology_client_llama_stop(h, parsed, body):
        h.send_json(client_llama_stop(body))
        return

@_route(POST_ROUTES, '/api/topology/client-llama/purge-cache')
def _post_api_topology_client_llama_purge_cache(h, parsed, body):
        h.send_json(client_llama_purge_cache(body))
        return

@_route(POST_ROUTES, '/api/topology/server-slot/add')
def _post_api_topology_server_slot_add(h, parsed, body):
        h.send_json(client_server_slot_add(body))
        return

@_route(POST_ROUTES, '/api/topology/server-slot/delete')
def _post_api_topology_server_slot_delete(h, parsed, body):
        h.send_json(client_server_slot_delete(body))
        return

@_route(POST_ROUTES, '/api/topology/server-slot/note')
def _post_api_topology_server_slot_note(h, parsed, body):
        h.send_json({"ok": True, **set_server_slot_note(
            body.get("hostId"), body.get("port"), body.get("note"))})
        return

@_route(POST_ROUTES, '/api/topology/server-cell/action')
def _post_api_topology_server_cell_action(h, parsed, body):
        h.send_json(server_cell_action(body))
        return

@_route(POST_ROUTES, '/api/models/gc')
def _post_api_models_gc(h, parsed, body):
        h.send_json(delete_models(body))
        return

@_route(POST_ROUTES, '/api/topology/server-cell/schedule')
def _post_api_topology_server_cell_schedule(h, parsed, body):
        h.send_json(set_cell_schedule(body))
        return

@_route(POST_ROUTES, '/api/topology/server-cell/save-config')
def _post_api_topology_server_cell_save_config(h, parsed, body):
        h.send_json(server_cell_save_config(body))
        return

@_route(POST_ROUTES, '/api/topology/client-llama/configs/save')
def _post_api_topology_client_llama_configs_save(h, parsed, body):
        h.send_json(client_llama_configs_save(body))
        return

@_route(POST_ROUTES, '/api/topology/client-llama/configs/delete')
def _post_api_topology_client_llama_configs_delete(h, parsed, body):
        h.send_json(client_llama_configs_delete(body))
        return

@_route(POST_ROUTES, '/api/topology/client/delete')
def _post_api_topology_client_delete(h, parsed, body):
        h.send_json(topology_client_delete(body))
        return

@_route(POST_ROUTES, '/api/topology/client/agent/delete')
def _post_api_topology_client_agent_delete(h, parsed, body):
        h.send_json(topology_client_agent_delete(body))
        return

@_route(POST_ROUTES, '/api/topology/orphan-assignment/delete')
def _post_api_topology_orphan_assignment_delete(h, parsed, body):
        h.send_json(topology_orphan_assignment_delete(body))
        return

@_route(POST_ROUTES, '/api/topology/discover/add')
def _post_api_topology_discover_add(h, parsed, body):
        h.send_json(topology_discover_add(body))
        return


@_route(DELETE_ROUTES, '/api/hf/local-file')
def _delete_api_hf_local_file(h, parsed):
        _q = urllib.parse.parse_qs(parsed.query or "")
        _repo = (_q.get("repo") or [""])[0].strip()
        _name = (_q.get("name") or [""])[0].strip()
        h.send_json(hf_local_delete(_repo, _name))
        return




# ── Auth guard ────────────────────────────────────────────────────────────────
# Open until the first user exists. Then: session cookie for humans, the fleet
# token (X-Caravan-Token) for machine endpoints, and a small public allowlist.

_AUTH_PUBLIC_GET = {"/login", "/favicon.svg", "/favicon.ico", "/api/auth/me"}
_AUTH_PUBLIC_POST = {"/api/auth/login", "/api/auth/setup"}
_AUTH_MACHINE_GET = {"/api/models/download"}
_AUTH_MACHINE_POST = {"/api/topology/client-heartbeat"}


def _auth_guard(h, path, method):
    """Return True when the request may proceed; otherwise answer it and return False."""
    if not auth_mod.auth_enabled():
        return True
    if method == "GET" and path in _AUTH_PUBLIC_GET:
        return True
    if method == "POST" and path in _AUTH_PUBLIC_POST:
        return True
    machine = (method == "GET" and path in _AUTH_MACHINE_GET) or \
              (method == "POST" and path in _AUTH_MACHINE_POST)
    if method == "GET" and path == "/metrics":
        # Prometheus can't do cookies: accept the fleet token via either
        # X-Caravan-Token or Authorization: Bearer (falls through to the
        # session check so a logged-in browser can peek too).
        bearer = (h.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if auth_mod.fleet_token_verify(h.headers.get("X-Caravan-Token") or "") or \
           auth_mod.fleet_token_verify(bearer):
            return True
    if machine:
        if auth_mod.fleet_token_verify(h.headers.get("X-Caravan-Token") or ""):
            return True
        h.send_json({"error": "fleet token required (X-Caravan-Token)"}, 401)
        return False
    sess = auth_mod.session_from_handler(h)
    if sess:
        # viewer = read-only: every GET, nothing mutating (logout excepted).
        if sess.get("role") == "viewer" and method != "GET" and path != "/api/auth/logout":
            h.send_json({"error": "read-only account"}, 403)
            return False
        return True
    if method == "GET" and (path == "/" or not path.startswith("/api/")):
        # Pages redirect to the login form; API calls get a plain 401.
        h.send_response(302)
        h.send_header("Location", "/login")
        h.send_header("Content-Length", "0")
        h.end_headers()
        return False
    h.send_json({"error": "authentication required"}, 401)
    return False


@_route(GET_ROUTES, '/login')
def _get_login(h, parsed):
        data = auth_mod.LOGIN_PAGE.encode("utf-8")
        h.send_response(200)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(data)))
        h.send_header("Cache-Control", "no-cache")
        h.end_headers()
        h.wfile.write(data)
        return

@_route(GET_ROUTES, '/api/auth/me')
def _get_auth_me(h, parsed):
        sess = auth_mod.session_from_handler(h)
        h.send_json({"enabled": auth_mod.auth_enabled(),
                     "authenticated": bool(sess),
                     "user": sess.get("user", ""), "role": sess.get("role", "")})
        return

@_route(POST_ROUTES, '/api/auth/login')
def _post_auth_login(h, parsed, body):
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
        if body.get("regenerate"):
            h.send_json({"ok": True, "fleetToken": auth_mod.fleet_token_regenerate()})
            return
        h.send_json({"ok": True, "fleetToken": auth_mod.fleet_token_ensure()})
        return


class Handler(BaseHTTPRequestHandler):
    server_version = f"lama-caravan/{APP_VERSION}"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")

    def send_json(self, payload, status=200):
        data = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Without this browsers heuristically cache API fetch() responses:
        # /hf kept rendering a stale /api/hf/files payload even across a hard
        # reload (which only bypasses the cache for documents, not later XHR).
        self.send_header("Cache-Control", "no-store")
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
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if not _auth_guard(self, parsed.path, "GET"):
                return
            for _prefix, _fn in GET_PREFIX_ROUTES:
                if parsed.path.startswith(_prefix):
                    _fn(self, parsed)
                    return
            _fn = GET_ROUTES.get(parsed.path)
            if _fn is None:
                self.send_json({"error": "Not found"}, 404)
                return
            _fn(self, parsed)
        except AppError as exc:
            self.send_json({"error": str(exc)}, exc.status)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

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
            self.send_json({"error": str(exc)}, exc.status)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

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
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)
