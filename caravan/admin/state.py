"""Persistent admin panel state (admin.json): the single shared mutable store.

`admin_state` is created exactly once at import; every other module imports the
object and mutates it in place, then calls save_admin_state(). Never rebind it.
"""
import json

from caravan.admin.paths import ADMIN_STATE_FILE, MONITOR_RETENTION_DEFAULT
from caravan.common.fsio import atomic_write_text


def load_admin_state():
    if ADMIN_STATE_FILE.exists():
        try:
            return json.loads(ADMIN_STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_admin_state():
    atomic_write_text(ADMIN_STATE_FILE, json.dumps(admin_state, indent=2), mkdir=True)


admin_state = load_admin_state()
admin_state.setdefault("monitor", {})
admin_state["monitor"].setdefault("retentionSeconds", MONITOR_RETENTION_DEFAULT)
admin_state.setdefault("topology", {})
admin_state["topology"].setdefault("clients", {})
admin_state["topology"].setdefault("assignments", {})
admin_state["topology"].setdefault("layout", {})
# Global manual price for LOCAL tokens (llama servers) — used by the usage-stats
# panel to estimate "what this would have cost in the cloud". $ per 1M tokens.
admin_state.setdefault("localPricing", {})
admin_state["localPricing"].setdefault("inputPer1M", 0.0)
admin_state["localPricing"].setdefault("outputPer1M", 0.0)
# Manual per-model API price overrides ($ per 1M tokens), keyed by model name. Used as the
# price when LiteLLM has no entry (e.g. subscription-only slugs like gpt-5.5) — lets the
# usage panel estimate "what this would have cost at API prices".
admin_state.setdefault("apiPricing", {})
admin_state.setdefault("hfToken", "")
admin_state.setdefault("hfFavorites", [])
# Field keys the user starred to mirror into the launch-form "Favorites" tab.
admin_state.setdefault("favFields", [])


def topology_store():
    admin_state.setdefault("topology", {})
    admin_state["topology"].setdefault("clients", {})
    admin_state["topology"].setdefault("assignments", {})
    admin_state["topology"].setdefault("clientAliases", {})
    admin_state["topology"].setdefault("layout", {})
    # Persistent server slots (host:port declarations) so a proxy cable stays
    # attached even when the server is stopped / its model changes. Keyed by
    # "hostId:port".
    admin_state["topology"].setdefault("serverSlots", {})
    # Manually deleted agents: {clientId: [agentId, ...]} — suppressed on refresh.
    admin_state["topology"].setdefault("deletedAgents", {})
    return admin_state["topology"]
