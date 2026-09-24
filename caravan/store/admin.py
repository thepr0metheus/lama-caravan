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
    """The admin document, with its defaults and its migrations."""

    def seed(self):
        self.section("monitor")
        self.data["monitor"].setdefault("retentionSeconds", MONITOR_RETENTION_DEFAULT)
        self.section("topology", "clients", "hosts", "assignments", "layout")
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
        topo = self.section("topology", "clients", "hosts", "assignments",
                            "clientAliases", "layout")
        # Persistent server slots (host:port declarations) so a proxy cable
        # stays attached even when the server is stopped / its model changes.
        # Keyed by "hostId:port".
        topo.setdefault("serverSlots", {})
        return topo

    #: What scouts' reports and adoption left in the document, and what no code
    #: reads since 2026-09-24 — a scout reports its machine only, and every
    #: client is made by hand. Per place: the keys that go.
    SCOUT_WORDS = {
        # `state`/`ageSeconds` are liveness an older controller stored on the
        # record itself. A client has no liveness of its own — its agents'
        # traffic says whether it works — and a machine's is computed on read
        # (HostRecord.liveness), never stored. The host split took them off
        # records that had a scout; a client made by hand kept a frozen
        # "stale" nobody reads and nobody can correct.
        "client": ("manual", "candidates", "assignments", "applyStatus", "state", "ageSeconds"),
        "agent": ("manual", "runtimeDetected"),
        "assignment entry": ("agentUrl", "applyStatus", "desiredAt"),
        "assignment row": ("manual",),
    }

    def migrate(self):
        """One-time repairs, each idempotent: a store that has been migrated
        has nothing left to match. Saved once, and only if something changed."""
        rekeyed = self._rekey_legacy_controller_slots()
        dropped = self._forget_what_reports_said()
        split = self._split_hosts_from_clients()
        if rekeyed or dropped or split:
            self.save()
        if dropped:
            print("store: dropped what scout reports and adoption left: "
                  + ", ".join(f"{n} {what}" for what, n in dropped.items()), flush=True)
        if split:
            print("store: machines split into host and client records: "
                  + ", ".join(f"{host_id} ({what})" for host_id, what in split), flush=True)

    def _rekey_legacy_controller_slots(self):
        """The controller's stored host id used to be the literal machine name;
        slots (and the notes/schedules living inside them) move to the
        role-based sentinel. Never clobbers an existing canonical key: if both
        spellings of one port somehow exist, the canonical record wins and the
        legacy one is dropped. True if anything moved."""
        slots = (self.data.get("topology") or {}).get("serverSlots")
        if not isinstance(slots, dict):
            return False
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
        return changed

    def _split_hosts_from_clients(self):
        """One combined record per machine becomes a host record (what its
        scout reports) and a client record (what the operator made), by
        HostRecord.split. A host already in `hosts` is left as it is — its
        scout's next report owns it. Returns [(id, "host+client" | "host only")].
        """
        from caravan.domain.host import HostRecord
        topo = self.data.get("topology")
        if not isinstance(topo, dict) or not isinstance(topo.get("clients"), dict):
            return []
        hosts = topo.setdefault("hosts", {})
        split = []
        for client_id in list(topo["clients"]):
            host, client = HostRecord.split(topo["clients"][client_id])
            if host is None:
                continue
            hosts.setdefault(client_id, host)
            if client is None:
                del topo["clients"][client_id]
                split.append((client_id, "host only"))
            else:
                topo["clients"][client_id] = client
                split.append((client_id, "host+client"))
        return split

    def _forget_what_reports_said(self):
        """Drop SCOUT_WORDS and the tombstones of deleted agents (nothing brings
        a deleted agent back any more). Kept as they are: every agent, every
        assignment route, every name. Returns {what: count} of what went, empty
        when there was nothing."""
        topo = self.data.get("topology")
        if not isinstance(topo, dict):
            return {}
        dropped = {}

        def drop(row, what):
            for key in self.SCOUT_WORDS[what]:
                if isinstance(row, dict) and key in row:
                    row.pop(key)
                    dropped[f"{what} {key}"] = dropped.get(f"{what} {key}", 0) + 1

        for client in (topo.get("clients") or {}).values():
            drop(client, "client")
            for agent in (client.get("agents") or []) if isinstance(client, dict) else []:
                drop(agent, "agent")
        for entry in (topo.get("assignments") or {}).values():
            drop(entry, "assignment entry")
            for row in (entry.get("assignments") or []) if isinstance(entry, dict) else []:
                drop(row, "assignment row")
        if "deletedAgents" in topo:
            tombstones = topo.pop("deletedAgents")
            count = sum(len(v) for v in tombstones.values() if isinstance(v, list)) \
                if isinstance(tombstones, dict) else 0
            dropped["tombstones"] = count
        return dropped
