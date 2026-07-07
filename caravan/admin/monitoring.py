"""Local system monitor: metric sampling loop, history ring, incidents,
client labels and hardware state (CPU/GPU/RAM) for the dashboard."""
import json
import os
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from caravan.admin.config_builder import parse_config
from caravan.admin.llama_metrics import parse_llamacpp_metrics, runtime_metrics_sample
from caravan.admin.paths import (
    CLIENT_LABELS_FILE,
    INCIDENT_LOG_FILE,
    INCIDENT_RETENTION_SECONDS,
    MONITOR_HISTORY_FILE,
    MONITOR_RETENTION_DEFAULT,
    MONITOR_SAMPLE_INTERVAL,
    SERVICE_NAME,
)
from caravan.admin.proxies_config import load_agent_proxy_config
from caravan.admin.proxy_stats import (
    agent_proxy_sample,
    iso_seconds,
    nearest_event,
    proxy_item_timestamp,
    requests_by_client,
    summarize_proxy_item,
)
from caravan.admin.state import admin_state, save_admin_state
from caravan.admin.terminal import terminal_frame_to_html, terminal_frame_to_text
from caravan.admin.token_history import (
    controller_gen_tps_samples,
    controller_token_metrics,
    record_controller_gen_tps,
    record_token_history,
)
from caravan.common.errors import AppError
from caravan.common.fsio import atomic_write_text
from caravan.common.fetch import fetch_json, fetch_text
from caravan.common.procs import run


def monitor_snapshot(kind):
    if kind == "nvidia-smi":
        result = run(["nvidia-smi"], timeout=5)
        output = result["stdout"] if result["ok"] else (result["stderr"] or result["stdout"])
        return {"kind": kind, "ok": result["ok"], "output": output.strip(), "time": int(time.time())}

    if kind == "btop":
        rows = 40
        cols = 120
        btop_cmd = f"stty cols {cols} rows {rows}; TERM=xterm-256color btop -p 0 -u 1000 --utf-force"
        result = run(["timeout", "-k", "1s", "2s", "script", "-q", "-c", btop_cmd, "/dev/null"], timeout=6)
        raw = result["stdout"] + result["stderr"]
        output = terminal_frame_to_text(raw, rows=rows, cols=cols)
        output = "\n".join(line for line in output.splitlines() if "Session terminated" not in line and "killing shell" not in line)
        html = terminal_frame_to_html(raw, rows=rows, cols=cols)
        html = "\n".join(line for line in html.splitlines() if "Session terminated" not in line and "killing shell" not in line)
        if output and "Failed to get size of terminal" not in output and "Terminal size too small" not in output:
            return {"kind": kind, "ok": True, "output": output, "html": html, "time": int(time.time()), "source": "btop"}
        fallback = run(["bash", "-lc", "COLUMNS=150 top -b -n 1 -w 150 | head -45"], timeout=5)
        fallback_output = fallback["stdout"] if fallback["ok"] else (fallback["stderr"] or fallback["stdout"])
        note = "btop snapshot unavailable; showing top fallback.\n\n"
        return {"kind": kind, "ok": fallback["ok"], "output": note + fallback_output.strip(), "time": int(time.time()), "source": "top"}

    raise AppError("Unknown monitor", 404)

monitor_history = deque()

# The ring stores SLIM samples (see _slim_sample); the full most-recent sample
# lives here because the UI panels read latest.agentProxies/agentProxyConfig/
# llamaActivity/processes/byProxy. Rebound only in this module, under
# monitor_lock.
monitor_latest_full = None

monitor_lock = threading.Lock()

monitor_last_cpu = None

monitor_last_disk = None

monitor_last_net = None

monitor_last_persist = 0

incident_lock = threading.Lock()

incident_logged_keys = set()

llama_activity_cache = {"time": 0, "data": None}
_llama_activity_lock = threading.Lock()


def correlate_activity(sample):
    agent_proxies = sample.get("agentProxies") if isinstance(sample.get("agentProxies"), dict) else {}
    llama_activity = sample.get("llamaActivity") if isinstance(sample.get("llamaActivity"), dict) else {}
    gpu = sample.get("gpu") if isinstance(sample.get("gpu"), dict) else {}
    tokens = sample.get("tokens") if isinstance(sample.get("tokens"), dict) else {}
    agents = agent_proxies.get("agents") if isinstance(agent_proxies.get("agents"), dict) else {}
    active = []
    recent = []
    by_proxy = {}
    timing_events = llama_activity.get("timingEvents") if isinstance(llama_activity.get("timingEvents"), list) else []
    context_events = llama_activity.get("contextEvents") if isinstance(llama_activity.get("contextEvents"), list) else []
    active_slots = llama_activity.get("activeSlots") if isinstance(llama_activity.get("activeSlots"), list) else []
    processing_slots = [slot for slot in active_slots if slot.get("isProcessing")]
    llama_active = []
    llama_active_clients = []
    llama_active_routes = []
    for key, row in agents.items():
        # The proxy keys its agents dict by PORT STRING ("8121"); the human route
        # label ("alice primary") lives in the row. The UI matches activity rows
        # by route label, so items must be stamped with the label, not the key.
        label = str(row.get("label") or key).strip() or str(key)
        route_active = [summarize_proxy_item(label, row, item, "active") for item in row.get("active", []) if isinstance(item, dict)]
        route_recent = [summarize_proxy_item(label, row, item, "recent") for item in row.get("recent", []) if isinstance(item, dict)]
        # isCloud is per-REQUEST, not per-port: a local ("llama") entry port can be
        # routed to a cloud output by the router graph (schedule/byModel/queue), so
        # the entry port's static type mislabels those requests as local. Trust the
        # item's realized upstreamType (stamped by summarize_proxy_item), falling
        # back to the port row for items that predate the stamp.
        def _item_is_cloud(item):
            return str(item.get("upstreamType") or row.get("upstreamType") or "llama") == "cloud"
        for item in route_active:
            item["slots"] = processing_slots
            item["slotIds"] = [slot.get("id") for slot in processing_slots if slot.get("id") is not None]
            item["correlation"] = "active-proxy"
            item["isCloud"] = _item_is_cloud(item)
        for item in route_recent:
            timestamp = proxy_item_timestamp(item)
            timing = nearest_event(timing_events, timestamp, max_delta=30)
            context = nearest_event(context_events, timestamp, max_delta=30)
            if timing:
                item["timing"] = timing
            if context:
                item["context"] = context
            item["correlation"] = "time-window" if timing or context else "proxy-only"
            item["isCloud"] = _item_is_cloud(item)
        by_proxy[label] = {
            "label": label,
            "port": row.get("port"),
            "upstream": row.get("upstream"),
            "upstreamType": row.get("upstreamType", "llama"),
            "active": route_active,
            "recent": route_recent[-8:],
            "last": (route_active[-1:] or route_recent[-1:] or [None])[0],
        }
        active.extend(route_active)
        recent.extend(route_recent)
        llama_active.extend([item for item in route_active if not item.get("isCloud")])
    active_clients = sorted({item.get("client") for item in active if item.get("client")})
    active_routes = sorted({item.get("label") for item in active if item.get("label") and not item.get("isCloud")})
    cloud_active_routes = sorted({item.get("label") for item in active if item.get("label") and item.get("isCloud")})
    llama_active_clients = sorted({item.get("client") for item in llama_active if item.get("client")})
    llama_active_routes = sorted({item.get("label") for item in llama_active if item.get("label")})
    recent_sorted = sorted(recent, key=lambda item: item.get("finishedAt") or item.get("startedAt") or 0, reverse=True)
    return {
        "ok": True,
        "time": sample.get("time"),
        "activeRequests": active,
        "recentRequests": recent_sorted[:20],
        "byProxy": by_proxy,
        "llamaServer": {
            "port": llama_activity.get("port"),
            "activeRequestCount": len(llama_active),
            "activeClients": llama_active_clients,
            "activeRoutes": llama_active_routes,
            "processingSlotCount": len(processing_slots),
            "processingSlots": processing_slots,
            "context": llama_activity.get("context") or {},
            "promptCache": llama_activity.get("promptCache") or {},
            "lastTiming": llama_activity.get("lastTiming") or {},
            "requestsProcessing": tokens.get("requestsProcessing", 0),
            "requestsDeferred": tokens.get("requestsDeferred", 0),
            "promptTokensPerSecond": tokens.get("promptTokensPerSecond", 0),
            "predictedTokensPerSecond": tokens.get("predictedTokensPerSecond", 0),
        },
        "gpu": {
            "activeRequestCount": len(active),
            "activeClients": active_clients,
            "activeRoutes": active_routes,
            "cloudActiveRoutes": cloud_active_routes,
            "processingSlotCount": len(processing_slots),
            "utilPct": gpu.get("utilPct", 0),
            "memoryPct": gpu.get("memoryPct", 0),
            "memoryUsedMiB": gpu.get("memoryUsedMiB"),
            "memoryTotalMiB": gpu.get("memoryTotalMiB"),
            "temperatureC": gpu.get("temperatureC"),
            "powerW": gpu.get("powerW"),
        },
    }

def proxy_incident_for_item(item):
    if not isinstance(item, dict):
        return None
    status = str(item.get("status") or "")
    label = str(item.get("label") or item.get("route") or "")
    title_label = label or "route"
    first_byte = float(item.get("firstByteMs") or 0)
    duration = float(item.get("durationMs") or item.get("elapsedMs") or 0)
    if item.get("error") or (status and not status.startswith("2") and status != "?"):
        error_kind = item.get("errorKind") or ("client_disconnected" if "Broken pipe" in str(item.get("error")) else "")
        if not error_kind and "timed out" in str(item.get("error")):
            error_kind = "upstream_timeout"
        return {
            "kind": error_kind or "failed",
            "title": f"{title_label} {'client disconnected' if error_kind == 'client_disconnected' else 'failed'}",
            "summary": item.get("error") or f"status {status}",
            "cause": proxy_incident_cause(item, error_kind or "failed"),
        }
    if first_byte >= 30000:
        return {
            "kind": "slow_first_byte",
            "title": f"{title_label} slow first byte",
            "summary": f"fb {round(first_byte / 1000)}s - {item.get('chunks') or 0} chunks",
            "cause": proxy_incident_cause(item, "slow_first_byte"),
        }
    if duration >= 120000:
        return {
            "kind": "slow_request",
            "title": f"{title_label} slow request",
            "summary": f"{round(duration / 1000)}s - {item.get('chunks') or 0} chunks",
            "cause": proxy_incident_cause(item, "slow_request"),
        }
    return None

def proxy_incident_cause(item, kind):
    if kind == "client_disconnected":
        return "Client closed the connection while proxy was still streaming the response."
    if kind == "upstream_timeout":
        return "Proxy waited too long for llama.cpp upstream response."
    if kind in ("slow_first_byte", "slow_request"):
        chunks = int(item.get("chunks") or 0)
        first_byte = float(item.get("firstByteMs") or 0)
        if chunks <= 1 and first_byte >= 30000:
            return "Likely queued or busy in llama.cpp prompt processing before first token."
        return "Likely long prompt/context processing or overloaded shared llama.cpp server."
    return "Proxy or upstream returned an error."

def incident_log_key(item, incident):
    request_id = item.get("id") or item.get("requestId")
    if request_id:
        return ":".join(str(part or "") for part in [
            request_id,
            incident.get("kind"),
            item.get("label"),
        ])
    return ":".join(str(part or "") for part in [
        incident.get("kind"),
        item.get("label"),
        item.get("startedAt"),
    ])

def incident_log_record(item, incident):
    request = item.get("request") if isinstance(item.get("request"), dict) else {}
    return {
        "time": int(time.time()),
        "key": incident_log_key(item, incident),
        "kind": incident.get("kind"),
        "title": incident.get("title"),
        "summary": incident.get("summary"),
        "label": item.get("label"),
        "port": item.get("port"),
        "upstreamHost": item.get("upstreamHost"),
        "upstreamPort": item.get("upstreamPort"),
        "client": item.get("client"),
        "method": item.get("method"),
        "path": item.get("path"),
        "status": item.get("status"),
        "error": item.get("error"),
        "errorKind": item.get("errorKind"),
        "cause": incident.get("cause"),
        "startedAt": item.get("startedAt"),
        "finishedAt": item.get("finishedAt"),
        "durationMs": item.get("durationMs"),
        "elapsedMs": item.get("elapsedMs"),
        "firstByteMs": item.get("firstByteMs"),
        "chunks": item.get("chunks"),
        "bytes": item.get("bytes"),
        "requestId": item.get("id"),
        "correlation": item.get("correlation"),
        "model": request.get("model"),
    }

def load_incident_log(limit=200):
    if not INCIDENT_LOG_FILE.exists():
        return []
    rows = []
    cutoff = time.time() - INCIDENT_RETENTION_SECONDS
    try:
        for line in INCIDENT_LOG_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("kind") == "fallback_active":
                continue
            if row.get("time", 0) >= cutoff:
                rows.append(row)
    except Exception:
        return []
    rows.sort(key=lambda row: row.get("time") or row.get("finishedAt") or row.get("startedAt") or 0, reverse=True)
    return rows[:limit]

def trim_incident_log():
    if not INCIDENT_LOG_FILE.exists():
        return
    cutoff = time.time() - INCIDENT_RETENTION_SECONDS
    rows = load_incident_log(limit=10000)
    rows = [row for row in rows if row.get("time", 0) >= cutoff]
    try:
        atomic_write_text(
            INCIDENT_LOG_FILE,
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in sorted(rows, key=lambda row: row.get("time", 0))),
            mkdir=True,
        )
    except Exception:
        pass

def append_incidents_from_sample(sample):
    correlated = sample.get("correlatedActivity") if isinstance(sample.get("correlatedActivity"), dict) else {}
    candidates = []
    candidates.extend(correlated.get("activeRequests") or [])
    candidates.extend(correlated.get("recentRequests") or [])
    records = []
    for item in candidates:
        incident = proxy_incident_for_item(item)
        if not incident:
            continue
        key = incident_log_key(item, incident)
        if key in incident_logged_keys:
            continue
        incident_logged_keys.add(key)
        records.append(incident_log_record(item, incident))
    if not records:
        return
    try:
        INCIDENT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with incident_lock:
            existing_keys = {row.get("key") for row in load_incident_log(limit=10000)}
            new_records = [row for row in records if row.get("key") not in existing_keys]
            if not new_records:
                return
            with INCIDENT_LOG_FILE.open("a", encoding="utf-8") as handle:
                for row in new_records:
                    handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            trim_incident_log()
    except Exception:
        pass

def llama_activity_sample():
    now = time.time()
    with _llama_activity_lock:
        cached = llama_activity_cache.get("data")
        cached_at = llama_activity_cache.get("time", 0)
    if cached and now - cached_at < 3:
        return cached
    try:
        config = parse_config()
        port = config.get("PORT") or "8080"
    except Exception:
        port = "8080"
    slots_raw = fetch_json(f"http://127.0.0.1:{port}/slots", timeout=5)
    slot_error = None
    if isinstance(slots_raw, list):
        slots = slots_raw
    else:
        slots = []
        if isinstance(slots_raw, dict):
            slot_error = slots_raw.get("error") or "unexpected /slots response"
        else:
            slot_error = "unexpected /slots response"
    result = run(["journalctl", "--user", "-u", SERVICE_NAME, "-n", "500", "-o", "short-iso", "--no-pager"], timeout=4)
    recent_requests = []
    log_slot_activity = {}
    last_timing = {}
    context = {}
    prompt_cache = {}
    prompt_cache_rows = []
    timing_events = []
    context_events = []
    current_timing = {}
    try:
        context_limit = int(parse_config().get("CTX_SIZE") or 0)
    except Exception:
        context_limit = 0
    if result["ok"]:
        for line in result["stdout"].splitlines():
            if "done request:" in line and "/v1/chat/completions" in line:
                match = re.search(r"^(\S+).*done request:\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)", line)
                if match:
                    recent_requests.append({
                        "time": match.group(1),
                        "method": match.group(2),
                        "path": match.group(3),
                        "clientIp": match.group(4),
                        "clientName": known_client_name(match.group(4)) or match.group(4),
                        "status": match.group(5),
                    })
                continue
            progress = re.search(
                r"^(\S+).*slot update_slots: id\s+(\d+)\s+\|\s+task\s+(\d+)\s+\|\s+prompt processing progress, n_tokens = (\d+), batch.n_tokens = (\d+), progress = ([0-9.]+)",
                line,
            )
            if progress:
                slot_id = progress.group(2)
                log_slot_activity[slot_id] = {
                    "time": progress.group(1),
                    "id": int(slot_id),
                    "taskId": int(progress.group(3)),
                    "phase": "prompt",
                    "tokens": int(progress.group(4)),
                    "batchTokens": int(progress.group(5)),
                    "progressPct": round(float(progress.group(6)) * 100, 1),
                }
                continue
            launch = re.search(r"^(\S+).*slot launch_slot_: id\s+(\d+)\s+\|\s+task\s+(\d+)\s+\|\s+processing task", line)
            if launch:
                slot_id = launch.group(2)
                log_slot_activity.setdefault(slot_id, {
                    "time": launch.group(1),
                    "id": int(slot_id),
                    "taskId": int(launch.group(3)),
                    "phase": "processing",
                })
                continue
            prompt_eval = re.search(r"prompt eval time =\s+([0-9.]+) ms /\s+(\d+) tokens.*?([0-9.]+) tokens per second", line)
            if prompt_eval:
                current_timing.update({
                    "time": line.split()[0],
                    "promptMs": float(prompt_eval.group(1)),
                    "promptTokens": int(prompt_eval.group(2)),
                    "promptTps": float(prompt_eval.group(3)),
                })
                last_timing.update(current_timing)
                continue
            eval_time = re.search(r"^\S+.*\beval time =\s+([0-9.]+) ms /\s+(\d+) tokens.*?([0-9.]+) tokens per second", line)
            if eval_time:
                current_timing.update({
                    "time": line.split()[0],
                    "evalMs": float(eval_time.group(1)),
                    "evalTokens": int(eval_time.group(2)),
                    "evalTps": float(eval_time.group(3)),
                })
                last_timing.update(current_timing)
                continue
            total_time = re.search(r"total time =\s+([0-9.]+) ms /\s+(\d+) tokens", line)
            if total_time:
                current_timing.update({
                    "time": line.split()[0],
                    "totalMs": float(total_time.group(1)),
                    "totalTokens": int(total_time.group(2)),
                })
                last_timing = dict(current_timing)
                timing_events.append(dict(current_timing))
                current_timing = {}
                continue
            release = re.search(r"^(\S+).*slot\s+release: id\s+(\d+)\s+\|\s+task\s+(\d+)\s+\| stop processing: n_tokens = (\d+), truncated = (\d+)", line)
            if release:
                tokens = int(release.group(4))
                context = {
                    "time": release.group(1),
                    "slotId": int(release.group(2)),
                    "taskId": int(release.group(3)),
                    "tokens": tokens,
                    "limit": context_limit,
                    "remaining": max(0, context_limit - tokens) if context_limit else None,
                    "pct": round(100 * tokens / context_limit, 1) if context_limit else None,
                    "truncated": bool(int(release.group(5))),
                }
                context_events.append(dict(context))
                continue
            cache = re.search(r"cache state: (\d+) prompts, ([0-9.]+) MiB \(limits: ([0-9.]+) MiB, (\d+) tokens, (\d+) est\)", line)
            if cache:
                prompt_cache = {
                    "prompts": int(cache.group(1)),
                    "usedMiB": float(cache.group(2)),
                    "limitMiB": float(cache.group(3)),
                    "tokenLimit": int(cache.group(4)),
                    "estTokens": int(cache.group(5)),
                    "pct": round(100 * float(cache.group(2)) / float(cache.group(3)), 1) if float(cache.group(3)) else None,
                }
                prompt_cache_rows = []
                continue
            cache_row = re.search(r"- prompt (0x[0-9a-fA-F]+):\s+(\d+) tokens, checkpoints:\s+(\d+),\s+([0-9.]+) MiB", line)
            if cache_row:
                prompt_cache_rows.append({
                    "id": cache_row.group(1),
                    "tokens": int(cache_row.group(2)),
                    "checkpoints": int(cache_row.group(3)),
                    "sizeMiB": float(cache_row.group(4)),
                })
    active_slots = []
    for slot in slots:
        next_token = (slot.get("next_token") or [{}])[0]
        params = slot.get("params") or {}
        active_slots.append({
            "id": slot.get("id"),
            "isProcessing": bool(slot.get("is_processing")),
            "taskId": slot.get("id_task"),
            "promptTokens": params.get("n_tokens") or params.get("prompt_n_tokens"),
            "maxTokens": params.get("max_tokens") or params.get("n_predict"),
            "stream": params.get("stream"),
            "chatFormat": params.get("chat_format"),
            "decoded": next_token.get("n_decoded"),
            "remain": next_token.get("n_remain"),
            "hasNextToken": next_token.get("has_next_token"),
        })
    data = {
        "ok": True,
        "port": int(port) if str(port).isdigit() else port,
        "slotError": slot_error,
        "slotStatus": "ok" if slot_error is None else "unavailable",
        "totalSlots": len(slots),
        "activeSlots": active_slots,
        "logSlotActivity": list(log_slot_activity.values())[-4:],
        "lastTiming": last_timing,
        "context": context,
        "promptCache": {**prompt_cache, "rows": prompt_cache_rows[-5:]} if prompt_cache else {},
        "timingEvents": timing_events[-20:],
        "contextEvents": context_events[-20:],
        "recentByClient": requests_by_client(recent_requests, timing_events, context_events),
        "recentRequests": recent_requests[-8:],
    }
    with _llama_activity_lock:
        llama_activity_cache["time"] = now
        llama_activity_cache["data"] = data
    return data

def monitor_retention_seconds():
    try:
        value = int(admin_state.get("monitor", {}).get("retentionSeconds", MONITOR_RETENTION_DEFAULT))
    except Exception:
        value = MONITOR_RETENTION_DEFAULT
    return max(60, min(value, 3600))

def set_monitor_retention(seconds):
    try:
        value = int(seconds)
    except Exception:
        raise AppError("retentionSeconds must be a number")
    admin_state.setdefault("monitor", {})["retentionSeconds"] = max(60, min(value, 3600))
    save_admin_state()
    trim_monitor_history()
    persist_monitor_history(force=True)

def read_cpu_times():
    # No /proc on macOS — return an empty reading so the sampler keeps running
    # on dev machines (cpu% degrades to 0, loadavg still carries the signal).
    rows = []
    try:
        text = Path("/proc/stat").read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        if parts[0] != "cpu" and not parts[0][3:].isdigit():
            continue
        values = [int(value) for value in parts[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        rows.append((parts[0], total, idle))
    return rows

def cpu_percentages(previous, current):
    if not previous:
        return {"total": 0, "cores": []}
    prev_map = {name: (total, idle) for name, total, idle in previous}
    cores = []
    total_pct = 0
    for name, total, idle in current:
        old = prev_map.get(name)
        if not old:
            pct = 0
        else:
            total_delta = total - old[0]
            idle_delta = idle - old[1]
            pct = round(100 * (1 - idle_delta / total_delta), 1) if total_delta > 0 else 0
        if name == "cpu":
            total_pct = pct
        else:
            cores.append(pct)
    return {"total": total_pct, "cores": cores}

def read_disk_counters():
    read_sectors = 0
    write_sectors = 0
    try:
        for line in Path("/proc/diskstats").read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 14:
                continue
            name = parts[2]
            if name.startswith(("loop", "ram", "zram", "sr")):
                continue
            if re.search(r"\d+$", name) and not name.startswith(("nvme", "mmcblk")):
                continue
            read_sectors += int(parts[5])
            write_sectors += int(parts[9])
    except Exception:
        pass
    return {"readBytes": read_sectors * 512, "writeBytes": write_sectors * 512}

def read_net_counters():
    rx = 0
    tx = 0
    try:
        for line in Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]:
            iface, raw = line.split(":", 1)
            iface = iface.strip()
            if iface == "lo":
                continue
            parts = raw.split()
            rx += int(parts[0])
            tx += int(parts[8])
    except Exception:
        pass
    return {"rxBytes": rx, "txBytes": tx}

def rate_delta(previous, current, elapsed, keys):
    if not previous or elapsed <= 0:
        return {key + "PerSec": 0 for key in keys}
    return {
        key + "PerSec": max(0, round((current.get(key, 0) - previous.get(key, 0)) / elapsed))
        for key in keys
    }

def gpu_sample():
    result = run([
        "nvidia-smi",
        "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu,power.draw",
        "--format=csv,noheader,nounits",
    ], timeout=3)
    if not result["ok"]:
        return {"ok": False, "error": result["stderr"].strip()}
    line = result["stdout"].splitlines()[0] if result["stdout"].splitlines() else ""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < 6:
        return {"ok": False, "error": "nvidia-smi returned no GPU row"}
    def number(index):
        try:
            return float(parts[index])
        except Exception:
            return 0
    used = number(2)
    total = number(3)
    return {
        "ok": True,
        "utilPct": number(0),
        "memoryUtilPct": number(1),
        "memoryUsedMiB": used,
        "memoryTotalMiB": total,
        "memoryPct": round(100 * used / total, 1) if total else 0,
        "temperatureC": number(4),
        "powerW": number(5),
    }

# Built-in labels for well-known addresses; everything else is labelled at
# runtime via client-labels.json (the ✎ button in the monitors).
KNOWN_LLAMA_CLIENTS = {
    "127.0.0.1": "local",
    "::1": "local",
}

def load_client_labels():
    try:
        if CLIENT_LABELS_FILE.exists():
            payload = json.loads(CLIENT_LABELS_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return {str(k): str(v) for k, v in payload.items() if str(v).strip()}
    except Exception:
        pass
    return {}

def save_client_labels(labels):
    atomic_write_text(CLIENT_LABELS_FILE, json.dumps(labels, ensure_ascii=False, indent=2) + "\n")

def endpoint_parts(value):
    endpoint = str(value or "").strip()
    if not endpoint:
        return "", None
    if endpoint.startswith("[") and "]:" in endpoint:
        host, port_text = endpoint.rsplit("]:", 1)
        host = host.lstrip("[")
    elif ":" in endpoint:
        host, port_text = endpoint.rsplit(":", 1)
        host = host.strip("[]")
    else:
        return endpoint, None
    try:
        port = int(port_text)
    except Exception:
        port = None
    return host, port

def parse_ss_client_line(line):
    parts = line.split(maxsplit=5)
    if len(parts) < 4:
        return None
    if parts[0].isalpha() or parts[0].upper() in {"ESTAB", "ESTABLISHED"}:
        state = parts[0]
        local = parts[3] if len(parts) >= 4 else ""
        peer = parts[4] if len(parts) >= 5 else ""
        process = parts[5] if len(parts) >= 6 else ""
    else:
        state = "ESTAB"
        local = parts[2]
        peer = parts[3]
        process = parts[4] if len(parts) >= 5 else ""
    local_ip, local_port = endpoint_parts(local)
    peer_ip, peer_port = endpoint_parts(peer)
    if not peer_ip:
        return None
    return {
        "state": state,
        "localIp": local_ip,
        "localPort": local_port,
        "clientIp": peer_ip,
        "clientPort": peer_port,
        "process": process,
    }

def known_client_name(ip):
    normalized = str(ip or "")
    if normalized.startswith("::ffff:"):
        normalized = normalized.removeprefix("::ffff:")
    custom = load_client_labels().get(normalized)
    return custom or KNOWN_LLAMA_CLIENTS.get(normalized, "")

def set_client_label(ip, label):
    normalized = str(ip or "").strip()
    if normalized.startswith("::ffff:"):
        normalized = normalized.removeprefix("::ffff:")
    if not re.match(r"^[0-9a-fA-F:.]+$", normalized):
        raise AppError("client ip is invalid")
    labels = load_client_labels()
    text = str(label or "").strip()
    if text:
        labels[normalized] = text[:80]
    else:
        labels.pop(normalized, None)
    save_client_labels(labels)
    return {"ip": normalized, "label": labels.get(normalized, ""), "labels": labels}

def llama_clients_sample():
    try:
        config = parse_config()
        port = int(config.get("PORT") or "8080")
    except Exception:
        port = 8080
    result = run(["ss", "-Htnp", "state", "established"], timeout=3)
    if not result["ok"]:
        return {"ok": False, "port": port, "clients": [], "error": result["stderr"].strip() or "ss failed"}
    clients = []
    seen = set()
    for line in result["stdout"].splitlines():
        row = parse_ss_client_line(line)
        if not row or row.get("localPort") != port:
            continue
        process = row.get("process") or ""
        if process and "llama-server" not in process:
            continue
        key = (row.get("clientIp"), row.get("clientPort"), row.get("localIp"), row.get("localPort"))
        if key in seen:
            continue
        seen.add(key)
        row["clientName"] = known_client_name(row.get("clientIp"))
        clients.append(row)
    clients.sort(key=lambda row: (row.get("clientName") or row.get("clientIp") or "", row.get("clientPort") or 0))
    return {"ok": True, "port": port, "clients": clients}

def memory_sample():
    memory = memory_state()
    if not memory.get("ok"):
        return memory
    total = memory.get("totalMiB") or 0
    used = memory.get("usedMiB") or 0
    memory["usedPct"] = round(100 * used / total, 1) if total else 0
    return memory

def top_processes():
    result = run(["ps", "-eo", "pid,comm,user,%cpu,%mem,rss", "--sort=-%cpu"], timeout=3)
    if not result["ok"]:
        # macOS ps has no --sort; -r sorts by cpu
        result = run(["ps", "-eo", "pid,comm,user,%cpu,%mem,rss", "-r"], timeout=3)
    rows = []
    if not result["ok"]:
        return rows
    for line in result["stdout"].splitlines()[1:8]:
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        try:
            rows.append({
                "pid": int(parts[0]),
                "name": parts[1],
                "user": parts[2],
                "cpuPct": float(parts[3]),
                "memPct": float(parts[4]),
                "rssMiB": round(int(parts[5]) / 1024, 1),
            })
        except Exception:
            continue
    return rows

def trim_monitor_history():
    cutoff = time.time() - monitor_retention_seconds()
    with monitor_lock:
        while monitor_history and monitor_history[0].get("time", 0) < cutoff:
            monitor_history.popleft()

def persist_monitor_history(force=False):
    global monitor_last_persist
    now = time.time()
    if not force and now - monitor_last_persist < 10:
        return
    monitor_last_persist = now
    try:
        with monitor_lock:
            samples = list(monitor_history)
        atomic_write_text(MONITOR_HISTORY_FILE, json.dumps({
            "retentionSeconds": monitor_retention_seconds(),
            "samples": samples,
        }), mkdir=True)
    except Exception:
        pass

def load_monitor_history():
    if not MONITOR_HISTORY_FILE.exists():
        return
    try:
        payload = json.loads(MONITOR_HISTORY_FILE.read_text(encoding="utf-8"))
        cutoff = time.time() - monitor_retention_seconds()
        for sample in payload.get("samples", []):
            if sample.get("time", 0) >= cutoff:
                # Pre-slimming files stored ~180 KB fat samples; slim on load
                # (idempotent for already-slim ones).
                monitor_history.append(_slim_sample(sample))
    except Exception:
        pass

def collect_monitor_sample():
    global monitor_last_cpu, monitor_last_disk, monitor_last_net
    now = time.time()
    cpu_now = read_cpu_times()
    disk_now = read_disk_counters()
    net_now = read_net_counters()
    previous_time = monitor_history[-1]["time"] if monitor_history else now
    elapsed = max(0.001, now - previous_time)
    load1, load5, load15 = os.getloadavg()
    tokens = controller_token_metrics()
    record_controller_gen_tps(tokens, now)
    sample = {
        "time": int(now),
        "cpu": cpu_percentages(monitor_last_cpu, cpu_now),
        "cpuLoad": [round(load1, 2), round(load5, 2), round(load15, 2)],
        "gpu": gpu_sample(),
        "llamaClients": llama_clients_sample(),
        "llamaActivity": llama_activity_sample(),
        "agentProxies": agent_proxy_sample(),
        "agentProxyConfig": load_agent_proxy_config(),
        "tokens": tokens,
        "memory": memory_sample(),
        "disk": rate_delta(monitor_last_disk, disk_now, elapsed, ["readBytes", "writeBytes"]),
        "net": rate_delta(monitor_last_net, net_now, elapsed, ["rxBytes", "txBytes"]),
        "processes": top_processes(),
    }
    sample["correlatedActivity"] = correlate_activity(sample)
    try:
        record_token_history(sample)
    except Exception:
        pass
    append_incidents_from_sample(sample)
    monitor_last_cpu = cpu_now
    monitor_last_disk = disk_now
    monitor_last_net = net_now
    global monitor_latest_full
    with monitor_lock:
        monitor_latest_full = sample
        monitor_history.append(_slim_sample(sample))
    trim_monitor_history()
    persist_monitor_history()

def monitor_sampler_loop():
    load_monitor_history()
    while True:
        try:
            collect_monitor_sample()
        except Exception:
            pass
        time.sleep(MONITOR_SAMPLE_INTERVAL)

_SLIM_ITEM_FIELDS = (
    "id", "label", "port", "state", "phase", "isCloud", "client", "method", "path",
    "status", "startedAt", "finishedAt", "durationMs", "elapsedMs", "firstByteMs",
    "error", "errorKind", "queuedMs", "upstream", "upstreamHost", "upstreamPort",
    "upstreamType", "providerId",
)

def _slim_item(item):
    return {k: item[k] for k in _SLIM_ITEM_FIELDS if k in item}

def _slim_sample(sample):
    """History samples for /api/system-monitor: keep only what the charts and the
    route-activity timeline read. The per-second agentProxies/agentProxyConfig
    snapshots and the request/response previews made every sample ~180 KB — the
    endpoint shipped >70 MB and could not answer within the 1 s poll cadence.
    The UI reads the heavy fields from `latest` only, which stays full."""
    slim = {k: sample.get(k) for k in ("time", "cpuLoad", "cpu", "memory", "disk", "net", "gpu", "tokens") if k in sample}
    la = sample.get("llamaActivity")
    if isinstance(la, dict) and la.get("lastTiming") is not None:
        slim["llamaActivity"] = {"lastTiming": la.get("lastTiming")}
    ca = sample.get("correlatedActivity")
    if isinstance(ca, dict):
        slim["correlatedActivity"] = {
            "ok": ca.get("ok", True),
            "time": ca.get("time"),
            "activeRequests": [_slim_item(i) for i in ca.get("activeRequests") or [] if isinstance(i, dict)],
            "recentRequests": [_slim_item(i) for i in ca.get("recentRequests") or [] if isinstance(i, dict)],
            "llamaServer": {
                "activeRoutes": (ca.get("llamaServer") or {}).get("activeRoutes") or [],
                "activeClients": (ca.get("llamaServer") or {}).get("activeClients") or [],
            },
            "gpu": {
                "activeRoutes": (ca.get("gpu") or {}).get("activeRoutes") or [],
                "cloudActiveRoutes": (ca.get("gpu") or {}).get("cloudActiveRoutes") or [],
            },
        }
    return slim

def system_monitor_state():
    trim_monitor_history()
    with monitor_lock:
        samples = list(monitor_history)
        latest_full = monitor_latest_full
    return {
        "ok": True,
        "intervalSeconds": MONITOR_SAMPLE_INTERVAL,
        "retentionSeconds": monitor_retention_seconds(),
        "clientLabels": load_client_labels(),
        "samples": samples,
        # Generation-only token-speed points (controller): the Token Speed chart
        # draws these, not the per-second gauge, so idle never paints a plateau.
        "tokenGenSamples": controller_gen_tps_samples(),
        "latest": latest_full or (samples[-1] if samples else None),
        "incidents": load_incident_log(limit=200),
        "incidentRetentionSeconds": INCIDENT_RETENTION_SECONDS,
        "time": int(time.time()),
    }

def runtime_api(config):
    port = config.get("PORT") or "8080"
    base = f"http://127.0.0.1:{port}"
    health = fetch_json(f"{base}/health", timeout=1)
    props = fetch_json(f"{base}/props")
    models = fetch_json(f"{base}/v1/models")
    metrics_text = fetch_text(f"{base}/metrics")
    metrics = parse_llamacpp_metrics(metrics_text)
    return {"health": health, "props": props, "models": models, "metrics": metrics}

def pcie_bandwidth_gbs(gen, width):
    per_lane = {
        1: 0.250,
        2: 0.500,
        3: 0.985,
        4: 1.969,
        5: 3.938,
        6: 7.877,
    }
    try:
        return round(per_lane.get(int(gen), 0) * int(width), 1)
    except Exception:
        return 0

def known_gpu_memory_bandwidth_gbs(name):
    normalized = name.lower()
    if "rtx 3090 ti" in normalized:
        return 1008
    if "rtx 3090" in normalized:
        return 936
    if "rtx 4090" in normalized:
        return 1008
    return 0

def gpu_compute_apps():
    """Controller pid -> gpu_uuid map (per-process GPU memory), to bind a local
    llama-server PID to the GPU(s) it occupies. Returns [{gpuUuid,pid,usedMiB}]."""
    result = run([
        "nvidia-smi",
        "--query-compute-apps=gpu_uuid,pid,used_memory",
        "--format=csv,noheader,nounits",
    ], timeout=5)
    apps = []
    if not result["ok"]:
        return apps
    for line in result["stdout"].splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        apps.append({"gpuUuid": parts[0], "pid": int(parts[1]),
                     "usedMiB": int(parts[2]) if parts[2].isdigit() else 0})
    return apps

def gpu_state():
    result = run([
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory,temperature.gpu,power.draw,pci.bus_id,pcie.link.gen.gpucurrent,pcie.link.gen.max,pcie.link.width.current,pcie.link.width.max,clocks.current.memory,clocks.max.memory,uuid",
        "--format=csv,noheader,nounits",
    ], timeout=5)
    if not result["ok"]:
        return {"ok": False, "error": result["stderr"]}
    rows = []
    for idx, line in enumerate(result["stdout"].splitlines()):
        parts = [part.strip() for part in line.split(",")]
        if len(parts) >= 15:
            current_pcie = pcie_bandwidth_gbs(parts[9], parts[11])
            max_pcie = pcie_bandwidth_gbs(parts[10], parts[12])
            rows.append({
                "index": idx,
                "uuid": parts[15] if len(parts) > 15 else "",
                "name": parts[0],
                "memoryTotalMiB": parts[1],
                "memoryUsedMiB": parts[2],
                "memoryFreeMiB": parts[3],
                "utilizationGpuPct": parts[4],
                "utilizationMemoryPct": parts[5],
                "temperatureC": parts[6],
                "powerDrawW": parts[7],
                "pciBusId": parts[8],
                "pcieGenCurrent": parts[9],
                "pcieGenMax": parts[10],
                "pcieWidthCurrent": parts[11],
                "pcieWidthMax": parts[12],
                "pcieBandwidthCurrentGBs": current_pcie,
                "pcieBandwidthMaxGBs": max_pcie,
                "memoryClockMHz": parts[13],
                "memoryClockMaxMHz": parts[14],
                "memoryBandwidthGBs": known_gpu_memory_bandwidth_gbs(parts[0]),
            })
    return {"ok": True, "gpus": rows}

def cpu_snapshot():
    first = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
    time.sleep(0.12)
    second = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
    a = [int(value) for value in first]
    b = [int(value) for value in second]
    idle_a = a[3] + (a[4] if len(a) > 4 else 0)
    idle_b = b[3] + (b[4] if len(b) > 4 else 0)
    total_delta = sum(b) - sum(a)
    idle_delta = idle_b - idle_a
    if total_delta <= 0:
        return 0
    return round(100 * (1 - idle_delta / total_delta), 1)

def cpu_state():
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        model = "unknown"
        for line in cpuinfo.splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
        logical = os.cpu_count() or 0
        physical_ids = set()
        core_ids = set()
        current_physical = ""
        for line in cpuinfo.splitlines():
            if line.startswith("physical id"):
                current_physical = line.split(":", 1)[1].strip()
                physical_ids.add(current_physical)
            elif line.startswith("core id"):
                core_ids.add((current_physical, line.split(":", 1)[1].strip()))
        physical = len(core_ids) or logical
        load1, load5, load15 = os.getloadavg()
        # Cores actually available to this process — respects cpuset/cgroup limits,
        # so on a core-pinned VM this reflects the slice, not the host total. Used
        # as the CPU-mode --threads default. Falls back to logical where unsupported.
        try:
            available = len(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            available = logical
        return {
            "ok": True,
            "model": model,
            "logicalCores": logical,
            "physicalCores": physical,
            "availableCores": available,
            "sockets": len(physical_ids) or 1,
            "load1": round(load1, 2),
            "load5": round(load5, 2),
            "load15": round(load15, 2),
            "usagePct": cpu_snapshot(),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def _memory_state_darwin():
    total_out = run(["sysctl", "-n", "hw.memsize"], timeout=3)
    vm_out = run(["vm_stat"], timeout=3)
    if not total_out.get("ok") or not vm_out.get("ok"):
        return {"ok": False, "error": "sysctl/vm_stat unavailable"}
    try:
        total_b = int(total_out["stdout"].strip())
        page = 4096
        pages = {}
        for line in vm_out["stdout"].splitlines():
            if line.startswith("Mach Virtual Memory Statistics"):
                m = re.search(r"page size of (\d+)", line)
                if m:
                    page = int(m.group(1))
                continue
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            pages[key.strip()] = int(raw.strip().rstrip("."))
        free_b = (pages.get("Pages free", 0) + pages.get("Pages speculative", 0)) * page
        # покупаемая память ≈ free + inactive + purgeable
        avail_b = free_b + (pages.get("Pages inactive", 0) + pages.get("Pages purgeable", 0)) * page
        used_b = max(0, total_b - avail_b)
        return {
            "ok": True,
            "totalMiB": round(total_b / 1048576),
            "availableMiB": round(avail_b / 1048576),
            "freeMiB": round(free_b / 1048576),
            "usedMiB": round(used_b / 1048576),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

def memory_state():
    if not Path("/proc/meminfo").exists():
        return _memory_state_darwin()
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            parts = raw.strip().split()
            if parts:
                values[key] = int(parts[0])
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", values.get("MemFree", 0))
    free = values.get("MemFree", 0)
    used = max(0, total - available)
    return {
        "ok": True,
        "totalMiB": round(total / 1024),
        "availableMiB": round(available / 1024),
        "freeMiB": round(free / 1024),
        "usedMiB": round(used / 1024),
    }
