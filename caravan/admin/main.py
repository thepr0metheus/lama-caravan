"""Admin server entry point: background threads + ThreadingHTTPServer."""
import os
import threading
from http.server import ThreadingHTTPServer

from caravan.admin.cell_schedule import start_scheduler_thread
from caravan.admin.monitoring import monitor_sampler_loop
from caravan.admin.openclaw import (
    _queue_thresholds_refresh_loop,
    compute_queue_thresholds,
    load_openclaw_cache,
    sync_wait_timeouts_from_openclaw,
)
from caravan.admin.paths import DATA_DIR, HOST, IS_CONTAINER, PORT, PROJECT_ROOT
from caravan.admin.proxies_config import read_agent_proxy_payload, write_agent_proxy_payload
from caravan.admin.router_dsl import recompute_cloud_fallback_eligibility
from caravan.admin.routes import Handler


class _Server(ThreadingHTTPServer):
    """The admin listener, with an accept queue that fits one page load.

    socketserver's default `request_queue_size` is 5 — five connections may wait
    to be accepted, and the kernel drops the rest. Answering HTTP/1.0, this
    server gets ONE CONNECTION PER REQUEST, and a board load is ~46 static
    modules plus its API calls; a second browser doubles that into a queue five
    deep. Measured on the controller: `ss -ltn` showed Send-Q 5 while
    net.core.somaxconn was 4096, and TcpExtListenOverflows stood at 4166.

    An overflow is not a refusal you can see. With tcp_abort_on_overflow=0 the
    kernel silently drops the SYN, the client retries at 1s, 3s, 7s… and the
    page sits there — a 74-second load was measured from outside, and /health,
    being one cheap request, answered green throughout. That is why this went
    unnoticed: nothing logs it on our side.

    128 is generous for a handful of operators and still far under somaxconn,
    which is the real ceiling (listen(2) silently clamps to it).
    """
    request_queue_size = 128
    daemon_threads = True


def main():
    # Same directory systemd's WorkingDirectory points at; keeps every relative
    # path (var/, logs/, git commands) working when launched by hand.
    os.chdir(PROJECT_ROOT)

    # Single-volume layout (container/dev): make sure the tree exists before
    # any writer needs it, and supervise the proxy as a child — the image has
    # no systemd unit to run it (see caravan/admin/proxy_supervisor.py).
    if DATA_DIR:
        for sub in ("state", "config", "logs", "secrets", "models",
                    "server-cells", "server-backups"):
            (DATA_DIR / sub).mkdir(parents=True, exist_ok=True)
    if IS_CONTAINER:
        from caravan.admin import proxy_supervisor
        proxy_supervisor.start()

    # Warm the OpenClaw config cache from disk so wait_timeout sync works even before
    # the agents respond (or while they're down).
    load_openclaw_cache()

    sampler = threading.Thread(target=monitor_sampler_loop, daemon=True)
    sampler.start()

    # Bootstrap ↑☁ cloud-fallback eligibility from current connections (one-shot).
    def _bootstrap_cloud_fallback():
        try:
            payload = read_agent_proxy_payload()
            routes = payload.get("routes") if isinstance(payload, dict) else None
            if isinstance(routes, list):
                before = [(r.get("cloudFallbackEligible"), r.get("cloudFallbackProviderId")) for r in routes if isinstance(r, dict)]
                recompute_cloud_fallback_eligibility(routes)
                after = [(r.get("cloudFallbackEligible"), r.get("cloudFallbackProviderId")) for r in routes if isinstance(r, dict)]
                if before != after:
                    write_agent_proxy_payload(payload)
        except Exception:
            pass
    threading.Thread(target=_bootstrap_cloud_fallback, daemon=True).start()

    # Compute queue thresholds on startup (after OpenClaw configs are cached)
    threading.Thread(target=lambda: (sync_wait_timeouts_from_openclaw(), compute_queue_thresholds()), daemon=True).start()
    # Background refresh every 6 hours
    threading.Thread(target=_queue_thresholds_refresh_loop, daemon=True).start()

    # Per-cell start/stop schedule windows (see caravan/admin/cell_schedule.py).
    start_scheduler_thread()

    server = _Server((HOST, PORT), Handler)
    print(f"lama-caravan listening on http://{HOST}:{PORT}")
    server.serve_forever()
