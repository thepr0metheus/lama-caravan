"""agent-proxies.json — the document the board is drawn from.

Routes, routers, and the GRAPH: the nodes and cables an operator dragged into
place. Its write is not a write, and every part of that is here because it was
learned the hard way:

  * the payload is normalised on the way out — cloud-fallback eligibility
    recomputed from the current connections, routers re-derived from the routes
    — because this is the single choke point every proxy-config change goes
    through, and anything done anywhere else drifts;

  * the file is backed up whenever the copy on disk still has graph nodes;

  * and a payload with NO graph does not overwrite a file that HAS one. A caller
    can rebuild this document from a narrower source and know nothing about the
    cables; without this, the cables vanish and the file that could prove what
    they were has just been overwritten.

The read upgrades the pre-rename schema in place. Old files carry `switchboards`,
the id `sb:default` and per-route `switchboardId`; those literals must never be
renamed by a search-and-replace, which is why the upgrade lives in a function of
its own rather than inline.
"""
import datetime
import json

from caravan.common.fsio import atomic_write_text
from caravan.store.base import Store, keep_unreadable


class ProxyStore(Store):
    """The proxy document. Its write path is the graph's only protection."""

    #: How many timestamped copies to keep when a write touches a file that
    #: still has graph nodes.
    backup_suffix = "bak-graph"

    def __init__(self, path, legacy_router_id="sb:default", default_router_id="router:default"):
        self.legacy_router_id = legacy_router_id
        self.default_router_id = default_router_id
        # NOT the base's __init__: this document is read per call, not held. The
        # proxy config is written by the panel AND read by a separate proxy
        # process that watches the file's mtime, so a copy cached in memory here
        # would answer with what the panel last wrote rather than what is on
        # disk.
        self.path = path
        self.data = {}

    # ── reading ──────────────────────────────────────────────────────────────
    def payload(self, default):
        """The document as stored, schema-upgraded. `default` when unreadable.

        A file we cannot parse is kept, once, under `.unreadable-<stamp>`: the
        very next write would replace it, and whatever an operator could have
        recovered by hand goes with it. Only once — a caravan that keeps failing
        to read the same file should not fill the directory with copies of it.
        """
        if not self.path.exists():
            return default
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self.keep_unreadable()
            return default
        if not isinstance(raw, dict):
            # Parses, and is still unusable. This branch returned the default
            # without keeping anything, so the docstring's promise held for a
            # truncated file and not for `null` or a bare list — and the next
            # write replaced the original either way.
            self.keep_unreadable()
            return default
        return self.upgrade(raw)

    def keep_unreadable(self):
        keep_unreadable(self.path)

    def upgrade(self, payload):
        """Pre-rename `switchboard` schema → `router`, in place and idempotent.

        A file already in the new shape has nothing left to match, so this is
        safe to run on every read.
        """
        if not isinstance(payload, dict):
            return payload
        legacy, new = self.legacy_router_id, self.default_router_id
        if "routers" not in payload and isinstance(payload.get("switchboards"), list):
            payload["routers"] = payload.pop("switchboards")
        for router in (payload.get("routers") or []):
            if isinstance(router, dict) and router.get("id") == legacy:
                router["id"] = new
        for route in (payload.get("routes") or []):
            if not isinstance(route, dict):
                continue
            if "routerId" not in route and "switchboardId" in route:
                route["routerId"] = route.pop("switchboardId")
            if route.get("routerId") == legacy:
                route["routerId"] = new
        return payload

    # ── writing ──────────────────────────────────────────────────────────────
    @staticmethod
    def graph_nodes(payload):
        """Every graph node in a payload, across all its routers."""
        nodes = []
        for router in ((payload or {}).get("routers") or []):
            if isinstance(router, dict):
                nodes.extend((router.get("graph") or {}).get("nodes") or [])
        return nodes

    def protect_graph(self, payload, stamp):
        """Back the file up, and put its graph back if the payload lost it.

        `stamp` is the timestamp for the backup's name, passed in rather than
        taken here so the caller decides what "now" means.

        Failures are swallowed on purpose: this is a safety net around the
        write, and a net that can refuse the write is worse than no net — the
        panel would stop being able to save at all because a backup directory
        was read-only.
        """
        try:
            if not self.path.exists():
                return payload
            old = json.loads(self.path.read_text(encoding="utf-8"))
            if not self.graph_nodes(old):
                return payload
            backup = self.path.with_name(f"{self.path.stem}.json.{self.backup_suffix}-{stamp}")
            backup.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
            if self.graph_nodes(payload):
                return payload
            old_by_id = {r["id"]: r for r in (old.get("routers") or []) if r.get("id")}
            for router in (payload.get("routers") or []):
                if not (router.get("graph") or {}).get("nodes") and router.get("id") in old_by_id:
                    router["graph"] = old_by_id[router["id"]].get("graph") or router.get("graph") or {}
        except Exception:  # noqa: BLE001
            pass
        return payload

    def write(self, payload):
        """The file, indented, UTF-8 as itself, with a trailing newline.

        Not `serialize()` from the base: this document is read by a person
        during an incident and by `git diff` afterwards, and \\uXXXX escapes
        make both harder.
        """
        atomic_write_text(self.path,
                          json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def stamp():
        return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
