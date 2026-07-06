"""Environment constants and repo-relative paths for the proxy daemon."""
import os
from pathlib import Path

# caravan/proxy/paths.py -> parents[2] == repo root (where agent-proxies.py lives).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# CARAVAN_DATA_DIR rebases the mutable defaults below one mountable directory —
# same layout as caravan/admin/paths.py (the admin sets it for the whole
# container, both daemons must resolve the shared files identically).
DATA_DIR = Path(os.environ.get("CARAVAN_DATA_DIR")).expanduser() \
    if os.environ.get("CARAVAN_DATA_DIR", "").strip() else None

def _default(data_rel, legacy):
    return str(DATA_DIR / data_rel) if DATA_DIR else str(legacy)


UPSTREAM_HOST = os.environ.get("AGENT_PROXY_UPSTREAM_HOST", "127.0.0.1")

UPSTREAM_PORT = int(os.environ.get("AGENT_PROXY_UPSTREAM_PORT", "8080"))

STATE_FILE = Path(os.environ.get("AGENT_PROXY_STATE_FILE")
    or _default("state/agent-proxy-state.json", PROJECT_ROOT / "agent-proxy-state.json"))

CONFIG_FILE = Path(os.environ.get("AGENT_PROXY_CONFIG_FILE")
    or _default("config/agent-proxies.json", PROJECT_ROOT / "agent-proxies.json"))

CLOUD_PROVIDERS_FILE = Path(os.environ.get("CLOUD_PROVIDERS_FILE")
    or _default("config/cloud-providers.json", PROJECT_ROOT / "cloud-providers.json"))

PROVIDER_SECRETS_FILE = Path(os.environ.get("PROVIDER_SECRETS_FILE")
    or _default("secrets/provider-secrets.json", Path.home() / ".config" / "llamacpp-easy-admin" / "provider-secrets.json"))

LOG_DIR = Path(os.environ.get("AGENT_PROXY_LOG_DIR")
    or _default("logs/proxy-events", PROJECT_ROOT / "logs" / "proxy-events"))

LOG_RETENTION_DAYS = int(os.environ.get("AGENT_PROXY_LOG_RETENTION_DAYS", "30"))

HOST = os.environ.get("AGENT_PROXY_HOST", "0.0.0.0")

DEFAULT_ROUTES = [
    {"label": "agent-a", "port": 8083, "upstreamHost": UPSTREAM_HOST, "upstreamPort": UPSTREAM_PORT, "enabled": True},
    {"label": "agent-b", "port": 8084, "upstreamHost": UPSTREAM_HOST, "upstreamPort": UPSTREAM_PORT, "enabled": True},
    {"label": "agent-c", "port": 8085, "upstreamHost": UPSTREAM_HOST, "upstreamPort": UPSTREAM_PORT, "enabled": True},
    {"label": "agent-d", "port": 8086, "upstreamHost": UPSTREAM_HOST, "upstreamPort": UPSTREAM_PORT, "enabled": True},
]

HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

STREAM_DONE_MARKER = b"data: [DONE]"

BODY_CAPTURE_LIMIT = 1024 * 1024

TEXT_PREVIEW_LIMIT = 180

DEFAULT_POLICY = {
    "maxSlots": int(os.environ.get("AGENT_PROXY_MAX_SLOTS", "1")),
    # Percentage-based thresholds (applied to each route's clientTimeoutSeconds)
    "cloudFallbackPct": int(os.environ.get("AGENT_PROXY_CLOUD_FALLBACK_PCT", "20")),
    "priorityPreemptPct": int(os.environ.get("AGENT_PROXY_PRIORITY_PREEMPT_PCT", "50")),
    "queueAbortPct": int(os.environ.get("AGENT_PROXY_QUEUE_ABORT_PCT", "85")),
    "preemptGraceSec": int(os.environ.get("AGENT_PROXY_PREEMPT_GRACE_SEC", "20")),
    "preemptEnabled": os.environ.get("AGENT_PROXY_PREEMPT_ENABLED", "1") not in ("0", "false", "False"),
    "stickySlotSec": int(os.environ.get("AGENT_PROXY_STICKY_SLOT_SEC", "0")),
}
