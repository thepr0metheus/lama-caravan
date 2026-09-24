"""Queue-wait thresholds per proxy port: when a waiting request overflows to
the cloud, preempts, or is aborted — each a share of the port's wait budget
(clientTimeoutSeconds).

The budget used to be synced first from each agent's own OpenClaw config,
fetched from OpenClaw config managers on the client machines; this lived in
admin/openclaw.py with the sync. The managers are gone (2026-09-24): the
budget is the operator's number on the port, and what is left here is the
arithmetic over it. The cache and its lock were module globals; they are one
object's fields now, with one reader (latest()).
"""
import threading
import time

from caravan.admin.proxies_config import (
    load_agent_proxy_config,
    read_agent_proxy_payload,
    write_agent_proxy_payload,
)
from caravan.admin.router_dsl import normalize_agent_proxy_policy


class QueueThresholds:
    """The last computed thresholds, and how to compute them again."""

    REFRESH_SECONDS = 6 * 3600

    def __init__(self):
        self._lock = threading.Lock()
        self._data = None
        self._at = 0

    def compute(self):
        """Compute per-proxy queue event thresholds from the policy and each
        route's clientTimeoutSeconds, keep them, and mirror them into
        agent-proxies.json. Called on startup, on a policy save, on a recalc
        request and every 6 hours by refresh_forever(). None when it fails.
        """
        import datetime as _dt
        try:
            config = load_agent_proxy_config()
            policy = config.get("policy") or normalize_agent_proxy_policy({})
            routes = config.get("routes") or []
            global_cloud_pct    = int(policy.get("cloudFallbackPct")    or 20)
            global_priority_pct = int(policy.get("priorityPreemptPct") or 50)
            global_abort_pct    = int(policy.get("queueAbortPct")       or 85)
            proxies = []
            for route in routes:
                if not isinstance(route, dict):
                    continue
                if str(route.get("upstreamType") or "llama") == "cloud":
                    continue
                wait_sec = int(route.get("clientTimeoutSeconds") or 0)
                if not wait_sec:
                    continue
                # Use per-route override when present, else fall back to global policy
                def _eff(key, global_val):
                    v = route.get(key)
                    return max(0, min(100, int(v))) if v is not None else global_val
                cloud_pct    = _eff("cloudFallbackPct",    global_cloud_pct)
                priority_pct = _eff("priorityPreemptPct",  global_priority_pct)
                abort_pct    = _eff("queueAbortPct",        global_abort_pct)
                entry = {
                    "id": route.get("id"),
                    "label": route.get("label"),
                    "port": route.get("port"),
                    "clientTimeoutSeconds": wait_sec,
                    "queueAbortSec": round(wait_sec * abort_pct / 100),
                    "priorityPreemptSec": round(wait_sec * priority_pct / 100),
                    # Expose effective pct values so the frontend can show overrides
                    "effectiveCloudPct":    cloud_pct,
                    "effectivePriorityPct": priority_pct,
                    "effectiveAbortPct":    abort_pct,
                    "hasCloudOverride":    route.get("cloudFallbackPct")    is not None,
                    "hasPriorityOverride": route.get("priorityPreemptPct") is not None,
                    "hasAbortOverride":    route.get("queueAbortPct")       is not None,
                }
                if route.get("cloudFallbackProviderId"):
                    entry["cloudFallbackSec"] = round(wait_sec * cloud_pct / 100)
                proxies.append(entry)
            result = {
                "proxies": proxies,
                "policy": {"cloudFallbackPct": cloud_pct, "priorityPreemptPct": priority_pct, "queueAbortPct": abort_pct},
                "computedAt": _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            with self._lock:
                self._data = result
                self._at = time.time()
            # Persist the computed per-agent seconds into agent-proxies.json so the values
            # are available on disk without the frontend (transparency / inspection). The
            # proxy service ignores this key; enforcement still computes inline from policy
            # + clientTimeoutSeconds, so this is a readable mirror, not the source of truth.
            try:
                payload = read_agent_proxy_payload()
                if isinstance(payload, dict) and payload.get("computedThresholds") != result:
                    payload["computedThresholds"] = result
                    write_agent_proxy_payload(payload)
            except Exception:
                pass
            return result
        except Exception:
            return None

    def latest(self):
        """The last computed thresholds, or None before the first computation."""
        with self._lock:
            return self._data

    def refresh_forever(self, sleep=time.sleep):
        """Recompute every REFRESH_SECONDS; a failed pass waits for the next."""
        while True:
            sleep(self.REFRESH_SECONDS)
            try:
                self.compute()
            except Exception:
                pass


QUEUE_THRESHOLDS = QueueThresholds()


def compute_queue_thresholds():
    """The name the callers use: compute the thresholds now."""
    return QUEUE_THRESHOLDS.compute()
