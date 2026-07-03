"""Prometheus text exposition (/metrics) — cheap reads only.

Sources: the proxy daemon's live state file (route activity/queues), today's
proxy log (request counters), the topology store (clients, cells), nvidia-smi
via the cached gpu_state(), and disk_usage on the models dir. When sign-in is
enabled the endpoint wants the fleet token (X-Caravan-Token or
`Authorization: Bearer <token>`), so a Prometheus scrape config stays one
static header away.
"""
import shutil
import time

from caravan import __version__ as APP_VERSION
from caravan.admin.config_builder import models_dir_from_config, parse_config
from caravan.admin.monitoring import gpu_state
from caravan.admin.proxy_stats import agent_proxy_sample, proxy_daily_stats
from caravan.admin.state import topology_store
from caravan.admin.systemd_ctl import systemctl


def _esc(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def build_metrics_text():
    lines = []

    def metric(name, help_text, mtype="gauge"):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {mtype}")

    def sample(name, value, labels=None):
        if value is None:
            return
        label_str = ""
        if labels:
            label_str = "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items()) + "}"
        lines.append(f"{name}{label_str} {value}")

    metric("caravan_build_info", "Static build info", "gauge")
    sample("caravan_build_info", 1, {"version": APP_VERSION})

    # ── clients ──────────────────────────────────────────────────────────────
    now = time.time()
    store = topology_store()
    metric("caravan_client_online", "1 when the client heartbeated within 3 minutes")
    metric("caravan_client_last_seen_seconds", "Seconds since the client's last heartbeat")
    for client in (store.get("clients") or {}).values():
        host = str(client.get("id") or "")
        last = float(client.get("lastSeen") or 0)
        if not host:
            continue
        sample("caravan_client_online", 1 if now - last < 180 else 0, {"host": host})
        if last:
            sample("caravan_client_last_seen_seconds", round(now - last, 1), {"host": host})

    # ── cells ────────────────────────────────────────────────────────────────
    slots = store.get("serverSlots") or {}
    metric("caravan_cells_total", "Declared server cells (slots)")
    sample("caravan_cells_total", len(slots))
    units = systemctl("list-units", "lama-cell@*", "--no-legend", "--plain", timeout=5)
    if units.get("ok"):
        running = sum(1 for line in units["stdout"].splitlines() if " running " in f" {line} ")
        metric("caravan_cells_running_local", "lama-cell@ units in the running state")
        sample("caravan_cells_running_local", running)

    # ── models disk ──────────────────────────────────────────────────────────
    try:
        usage = shutil.disk_usage(str(models_dir_from_config(parse_config())))
        metric("caravan_models_disk_bytes", "Models-dir filesystem size/free", "gauge")
        sample("caravan_models_disk_bytes", usage.total, {"kind": "total"})
        sample("caravan_models_disk_bytes", usage.free, {"kind": "free"})
    except OSError:
        pass

    # ── GPUs (cached nvidia-smi) ─────────────────────────────────────────────
    try:
        gpus = (gpu_state() or {}).get("gpus") or []
    except Exception:
        gpus = []
    metric("caravan_gpu_vram_used_mib", "GPU memory used (MiB)")
    metric("caravan_gpu_util_pct", "GPU utilization percent")
    metric("caravan_gpu_temperature_c", "GPU temperature")
    metric("caravan_gpu_power_w", "GPU power draw")
    for g in gpus:
        labels = {"gpu": str(g.get("index", 0)), "name": str(g.get("name") or "")}
        sample("caravan_gpu_vram_used_mib", g.get("memoryUsedMiB"), labels)
        sample("caravan_gpu_util_pct", g.get("utilizationGpuPct"), labels)
        sample("caravan_gpu_temperature_c", g.get("temperatureC"), labels)
        sample("caravan_gpu_power_w", g.get("powerDrawW"), labels)

    # ── routes: live activity + today's counters ─────────────────────────────
    state = agent_proxy_sample()
    metric("caravan_route_active_requests", "Requests currently streaming on the route")
    metric("caravan_route_queue_depth", "Requests waiting in the route's queue")
    agents = state.get("agents") if isinstance(state.get("agents"), dict) else {}
    for port, row in agents.items():
        if not isinstance(row, dict):
            continue
        labels = {"port": str(port), "route": str(row.get("route") or row.get("name") or port)}
        sample("caravan_route_active_requests", row.get("active") or 0, labels)
        queue = row.get("queue")
        depth = len(queue) if isinstance(queue, list) else (queue if isinstance(queue, (int, float)) else 0)
        sample("caravan_route_queue_depth", depth, labels)

    daily = proxy_daily_stats()
    metric("caravan_route_requests_today", "Requests received today (resets at midnight)", "gauge")
    for route, entry in (daily.get("routes") or {}).items():
        sample("caravan_route_requests_today", entry.get("total", 0), {"route": route, "result": "total"})
        sample("caravan_route_requests_today", entry.get("failed", 0), {"route": route, "result": "failed"})
        sample("caravan_route_requests_today", entry.get("paused", 0), {"route": route, "result": "paused"})

    return "\n".join(lines) + "\n"
