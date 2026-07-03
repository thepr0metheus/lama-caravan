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
from caravan.admin.paths import HOST, PORT, PROJECT_ROOT
from caravan.admin.proxies_config import read_agent_proxy_payload, write_agent_proxy_payload
from caravan.admin.router_dsl import recompute_cloud_fallback_eligibility
from caravan.admin.routes import Handler


def main():
    # Same directory systemd's WorkingDirectory points at; keeps every relative
    # path (var/, logs/, git commands) working when launched by hand.
    os.chdir(PROJECT_ROOT)

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

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"lama-caravan listening on http://{HOST}:{PORT}")
    server.serve_forever()
