"""admin.json — the panel's own document: topology, pricing, favourites, tokens.

Everything the operator changed that is not a cell config. It is one file rather
than several because it is read whole on every page load and written whole on
every change; splitting it would buy nothing and cost a consistency problem.
"""
from caravan.admin.paths import (
    CONTROLLER_HOST_ID,
    LEGACY_CONTROLLER_HOST_IDS,
    MONITOR_RETENTION_DEFAULT,
)
from caravan.store.base import Store


class AdminStore(Store):
    """The admin document, with its defaults and its one migration."""

    def seed(self):
        self.section("monitor")
        self.data["monitor"].setdefault("retentionSeconds", MONITOR_RETENTION_DEFAULT)
        self.section("topology", "clients", "assignments", "layout")
        # Global manual price for LOCAL tokens (llama servers) — used by the
        # usage-stats panel to estimate "what this would have cost in the
        # cloud". $ per 1M tokens.
        self.section("localPricing")
        self.data["localPricing"].setdefault("inputPer1M", 0.0)
        self.data["localPricing"].setdefault("outputPer1M", 0.0)
        # Manual per-model API price overrides ($ per 1M tokens), keyed by model
        # name. Used as the price when LiteLLM has no entry (e.g.
        # subscription-only slugs like gpt-5.5) — lets the usage panel estimate
        # "what this would have cost at API prices".
        self.section("apiPricing")
        self.data.setdefault("hfToken", "")
        self.data.setdefault("hfFavorites", [])
        # Field keys the user starred to mirror into the launch-form
        # "Favorites" tab.
        self.data.setdefault("favFields", [])

    def topology(self):
        """The topology section, with every subsection this caravan expects.

        Seeded here rather than only at start-up because a document written by
        an older version has sections this one needs, and the first caller
        should find them rather than a KeyError.
        """
        topo = self.section("topology", "clients", "assignments", "clientAliases",
                            "layout")
        # Persistent server slots (host:port declarations) so a proxy cable
        # stays attached even when the server is stopped / its model changes.
        # Keyed by "hostId:port".
        topo.setdefault("serverSlots", {})
        # Manually deleted agents: {clientId: [agentId, ...]} — suppressed on
        # refresh.
        topo.setdefault("deletedAgents", {})
        return topo

    def migrate(self):
        """One-time key migration: the controller's stored host id used to be
        the literal machine name; slots (and the notes/schedules living inside
        them) move to the role-based sentinel.

        Idempotent — a migrated store has no legacy keys left to match. Never
        clobbers an existing canonical key: if both spellings of one port
        somehow exist, the canonical record wins and the legacy one is dropped.
        """
        slots = (self.data.get("topology") or {}).get("serverSlots")
        if not isinstance(slots, dict):
            return
        changed = False
        for key in list(slots):
            head, sep, port = str(key).partition(":")
            if not sep or head not in LEGACY_CONTROLLER_HOST_IDS:
                continue
            slot = slots.pop(key)
            new_key = f"{CONTROLLER_HOST_ID}:{port}"
            if isinstance(slot, dict):
                slot["hostId"] = CONTROLLER_HOST_ID
                slot["id"] = new_key
            slots.setdefault(new_key, slot)
            changed = True
        if changed:
            self.save()
