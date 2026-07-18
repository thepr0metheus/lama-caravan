"""Environment-driven constants and repo-relative paths for the admin server.

Every repo-relative anchor lives here, computed from PROJECT_ROOT — no other
module may derive paths from its own __file__ (they'd point into caravan/).
"""
import json
import os
from pathlib import Path

# caravan/admin/paths.py -> parents[2] == repo root (where app.py lives).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Container mode (the Docker image sets both): IS_CONTAINER swaps systemd-based
# service control for in-process supervision and disables host-only operations;
# CARAVAN_DATA_DIR rebases every mutable default below one mountable directory
# (state/, config/, logs/, secrets/, models/, server-cells/, server-backups/).
# Each per-file env var still wins over the rebased default. The proxy daemon
# applies the same rebase in caravan/proxy/paths.py — keep the layouts in sync.
IS_CONTAINER = os.environ.get("CARAVAN_CONTAINER", "").strip() == "1"
DATA_DIR = Path(os.environ.get("CARAVAN_DATA_DIR")).expanduser() \
    if os.environ.get("CARAVAN_DATA_DIR", "").strip() else None

def _default(data_rel, legacy):
    return str(DATA_DIR / data_rel) if DATA_DIR else str(legacy)

HOST = os.environ.get("LLAMACPP_ADMIN_HOST", "0.0.0.0")
PORT = int(os.environ.get("LLAMACPP_ADMIN_PORT", "8090"))
LLAMA_HOME = Path(os.environ.get("LLAMA_HOME", str(Path.home() / "llama.cpp"))).expanduser()
START_SCRIPT = Path(os.environ.get("LLAMA_START_SCRIPT", str(LLAMA_HOME / "start-server.sh"))).expanduser()
DEFAULT_MODELS_DIR = Path(os.environ.get("LLAMA_MODELS_DIR")
    or _default("models", LLAMA_HOME / "models")).expanduser()
SERVICE_NAME = os.environ.get("LLAMA_SERVICE_NAME", "llamacpp-current.service")
STATIC_DIR = PROJECT_ROOT / "static"
SERVER_CELLS_DIR = Path(os.environ.get("LAMA_CARAVAN_SERVER_CELLS_DIR")
    or _default("server-cells", PROJECT_ROOT / "var/server-cells")).expanduser()
# Named launch-config backups for every node (controller + clients), kept ON THE
# CONTROLLER so a client's backups survive the client and show up in its Add-Llama
# modal. Layout: <root>/<hostId>/<gpu-model-or-CPU>/<stamp>-<name>.json
SERVER_BACKUPS_DIR = Path(os.environ.get("LAMA_CARAVAN_SERVER_BACKUPS_DIR")
    or _default("server-backups", PROJECT_ROOT / "var/server-backups")).expanduser()

ADMIN_STATE_FILE = Path(os.environ.get("LLAMA_ADMIN_STATE")
    or _default("state/admin.json", Path.home() / ".local/state/llamacpp-easy-admin/admin.json"))
MONITOR_HISTORY_FILE = Path(os.environ.get("LLAMA_MONITOR_HISTORY")
    or _default("state/monitor-history.json", Path.home() / ".local/state/llamacpp-easy-admin/monitor-history.json"))
INCIDENT_LOG_FILE = Path(os.environ.get("LLAMA_INCIDENT_LOG")
    or _default("state/incident-log.jsonl", Path.home() / ".local/state/llamacpp-easy-admin/incident-log.jsonl"))
MONITOR_SAMPLE_INTERVAL = float(os.environ.get("LLAMA_MONITOR_SAMPLE_INTERVAL", "1"))
MONITOR_RETENTION_DEFAULT = int(os.environ.get("LLAMA_MONITOR_RETENTION_SECONDS", "600"))
INCIDENT_RETENTION_SECONDS = int(os.environ.get("LLAMA_INCIDENT_RETENTION_SECONDS", str(30 * 24 * 60 * 60)))
CLIENT_LABELS_FILE = Path(os.environ.get("LLAMA_CLIENT_LABELS_FILE")
    or _default("state/client-labels.json", PROJECT_ROOT / "client-labels.json"))
AGENT_PROXY_STATE_FILE = Path(os.environ.get("AGENT_PROXY_STATE_FILE")
    or _default("state/agent-proxy-state.json", PROJECT_ROOT / "agent-proxy-state.json"))
AGENT_PROXY_CONFIG_FILE = Path(os.environ.get("AGENT_PROXY_CONFIG_FILE")
    or _default("config/agent-proxies.json", PROJECT_ROOT / "agent-proxies.json"))
CLOUD_PROVIDERS_FILE = Path(os.environ.get("CLOUD_PROVIDERS_FILE")
    or _default("config/cloud-providers.json", PROJECT_ROOT / "cloud-providers.json"))
PROVIDER_SECRETS_FILE = Path(os.environ.get("PROVIDER_SECRETS_FILE")
    or _default("secrets/provider-secrets.json", Path.home() / ".config" / "llamacpp-easy-admin" / "provider-secrets.json"))
MODEL_CATALOG_FILE = Path(os.environ.get("MODEL_CATALOG_FILE")
    or _default("state/model-catalog.json", PROJECT_ROOT / "model-catalog.json"))
TOKEN_HISTORY_FILE = Path(os.environ.get("TOKEN_HISTORY_FILE")
    or _default("state/token-history.json", PROJECT_ROOT / "token-history.json"))
TOKEN_HISTORY_MAX = int(os.environ.get("TOKEN_HISTORY_MAX", "12000"))
TOKEN_HISTORY_RETENTION_SEC = int(os.environ.get("TOKEN_HISTORY_RETENTION_SEC", str(14 * 24 * 3600)))
AGENT_PROXY_LOG_DIR = Path(os.environ.get("AGENT_PROXY_LOG_DIR")
    or _default("logs/proxy-events", PROJECT_ROOT / "logs" / "proxy-events"))
AGENT_PROXY_SERVICE_NAME = os.environ.get("AGENT_PROXY_SERVICE_NAME", "lama-caravan-proxies.service")
ADMIN_SERVICE_NAME = os.environ.get("LLAMA_ADMIN_SERVICE_NAME", "lama-caravan.service")
TOPOLOGY_CLIENT_TTL = int(os.environ.get("LLAMA_TOPOLOGY_CLIENT_TTL", "45"))
MODEL_PRICING_CACHE_PATH = Path(_default("logs/model-pricing-cache.json",
    PROJECT_ROOT / "logs" / "model-pricing-cache.json"))
MODEL_PRICING_URL = "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
MODEL_PRICING_TTL = 24 * 3600  # cache for 24 hours
# OpenClaw config managers to poll for agent wait-timeouts: a JSON list of
# {"name": ..., "url": ...} in the OPENCLAW_CONFIG_MANAGERS env var. Empty by
# default — queue thresholds then fall back to per-route settings.
try:
    OPENCLAW_CONFIG_MANAGERS = json.loads(os.environ.get("OPENCLAW_CONFIG_MANAGERS", "[]"))
except ValueError:
    OPENCLAW_CONFIG_MANAGERS = []
if not isinstance(OPENCLAW_CONFIG_MANAGERS, list):
    OPENCLAW_CONFIG_MANAGERS = []
# Fleet registry (single source of truth for agent identity), if you run one.
# Discovered candidates are registered by POSTing to <FLEET_REGISTRY_URL>/api/agents.
# Empty (default) disables the discovery "add to fleet" flow.
FLEET_REGISTRY_URL = os.environ.get("FLEET_REGISTRY_URL", "")
# The controller's address as seen by clients — used to build the proxy
# endpoints handed to agents (http://<this>:<port>/v1).
TOPOLOGY_SERVER_IP = os.environ.get("LLAMA_TOPOLOGY_SERVER_IP", "127.0.0.1")
SERVER_CELL_BASE_PORT = 8001
_BENCH_CACHE_DIR = Path(_default("state/bench-cache", PROJECT_ROOT / ".bench_cache"))
# OpenClaw configs (fetched from the configured managers) are the source of each
# agent's wait_timeout. They can contain provider credentials, so the on-disk
# last-known-good cache lives next to provider-secrets.json with 0600 perms and is
# NOT inside the repo tree.
OPENCLAW_CONFIG_CACHE_FILE = Path(os.environ.get("OPENCLAW_CONFIG_CACHE_FILE")
    or _default("secrets/openclaw-config-cache.json",
                Path.home() / ".config" / "llamacpp-easy-admin" / "openclaw-config-cache.json"))

# ── Controller identity ─────────────────────────────────────────────────────
# The controller's host id in STORED state — a role name, not a hostname. Slot
# keys ("<hostId>:<port>"), and with them cell notes and schedules, are
# persisted under it; state.py migrates legacy keys to this value on load. The
# controller's DISPLAY name is a separate, configurable thing
# (LLAMA_TOPOLOGY_SERVER_NAME).
CONTROLLER_HOST_ID = "controller"

# Ids that meant the controller in older stores and older cached frontends.
# Stale tabs keep sending the old id for a while (Chrome serves cached ES
# modules within a session), so the API keeps accepting these — and the
# heartbeat guard keeps REJECTING them from clients: an id that ever meant
# "the controller" may never come to mean one of its clients.
LEGACY_CONTROLLER_HOST_IDS = ("skynet",)


def canonical_host_id(host_id) -> str:
    """Map any spelling of the controller's id to the canonical sentinel;
    client ids pass through untouched. Call at every boundary where a hostId
    enters from outside (API bodies, stored files) so one cell never exists
    under two keys."""
    hid = str(host_id or "").strip()
    return CONTROLLER_HOST_ID if hid in LEGACY_CONTROLLER_HOST_IDS else hid


def is_controller_host(host_id) -> bool:
    """True when a slot/cell belongs to the controller rather than a client.

    Ask this instead of comparing to a literal. These checks decide real
    behaviour — whether a delete stops a systemd unit, whether a start is
    forwarded to an agent — and spelled as a hostname comparison they ask the
    wrong question on any fleet whose controller is named differently (or
    whose CLIENT happens to carry that name).
    """
    return canonical_host_id(host_id) == CONTROLLER_HOST_ID
