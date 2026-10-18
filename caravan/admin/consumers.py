"""A consumer of the entry, made on the board: a name, its own key and the set of models it calls."""
from caravan.admin.cloud import load_cloud_data
from caravan.admin.proxies_config import (
    KeyAudit,
    RouteKeys,
    load_agent_proxy_config,
    next_free_proxy_port,
    read_agent_proxy_payload,
    write_agent_proxy_payload,
)
from caravan.common.cloud_pools import CloudPools
from caravan.common.entry_models import ConsumerPool, ConsumerSet, EntryModels, ModelSets
from caravan.common.errors import AppError


class ConsumerDesk:
    """The board's consumers of the entry (the owner, 2026-10-11).

    A consumer is what a company's gateway calls a client: a name, its own key,
    and the set of models a cable in Routing leads it to (the owner,
    2026-10-12; caravan/common/entry_models.py, caravan/admin/model_sets.py). It
    calls one address, the entry, and a request's `model` picks a pool of its
    set. A new consumer has no set: no cable leads anywhere until the operator
    draws one.

    It is kept as a route of kind "consumer": the journal, the queue and the
    board know a route, and a route's number is its name in all of them. The
    number comes from the proxy range and never listens — the entry is a
    consumer's only way in, so the entry must be on before one is made.

    A key is answered once, when it is made: afterwards the board shows its
    last four characters. A key the consumer lost is replaced, not shown again,
    and the old one stops working in the same write.
    """

    KIND = "consumer"
    NAME_MAX = 80

    def __init__(self, load=None, save=None, pools=None, keys=None, free_port=None, read=None, sets=None):
        self.load = load or load_agent_proxy_config
        self.save = save or write_agent_proxy_payload
        self.read = read or read_agent_proxy_payload
        self.pools = pools or (lambda: CloudPools(load_cloud_data()).all())
        self.sets = sets or (lambda: ModelSets.clean(load_cloud_data().get("sets")))
        self.keys = keys or RouteKeys()
        self.free_port = free_port or next_free_proxy_port

    def create(self, name):
        """A new consumer, cabled to no set yet: `{port, name, key, set}` — the key this once."""
        payload = self.load()
        if not int((payload.get("entry") or {}).get("port") or 0):
            raise AppError("the entry is off — set up the entry first: a consumer's only way in is the entry", 409)
        name = self.clean_name(name, payload["routes"])
        route = {"label": name, "port": self.free_port(payload["routes"]), "kind": self.KIND,
                 "apiKey": self.keys.new(), "portClosed": True, "set": "",
                 "upstreamType": "cloud", "routerId": "", "mode": "open"}
        payload["routes"].append(route)
        KeyAudit(payload["routes"]).enforce()
        self.save(payload)
        return {"port": route["port"], "name": name, "key": route["apiKey"], "set": ""}

    def set_set(self, port, set_id):
        """The set a consumer's cable leads to from now on, "" taking the cable away: `{port, set}`."""
        payload = self.load()
        route = self._consumer(payload, port)
        route["set"] = self._set(set_id)
        route.pop("pool", None)
        route.pop("models", None)
        self.save(payload)
        return {"port": route["port"], "set": route["set"]}

    def new_key(self, port):
        """A new key for a consumer, answered this once: `{port, name, key}`. The old key stops working now."""
        payload = self.load()
        route = self._consumer(payload, port)
        route["apiKey"] = self.keys.new()
        KeyAudit(payload["routes"]).enforce()
        self.save(payload)
        return {"port": route["port"], "name": route.get("label") or "", "key": route["apiKey"]}

    # ── reading what the operator sent ───────────────────────────────────────

    @classmethod
    def clean_name(cls, raw, routes, own_port=None):
        """The consumer's name: required, and not one another consumer has — two
        "Hermes" on the board could not be told apart, nor in the journal. A new
        consumer is named here, and a renamed one too (the route's door, `own_port`
        being the consumer itself): until 2026-10-11 a rename took any name."""
        name = str(raw or "").strip()[:cls.NAME_MAX]
        if not name:
            raise AppError("name is required: the consumer's name, as the board and the journal show it", 400)
        taken = {EntryModels.key(r.get("label")) for r in routes
                 if str(r.get("kind") or "") == cls.KIND and int(r.get("port") or 0) != int(own_port or 0)}
        if EntryModels.key(name) in taken:
            raise AppError(f"a consumer named {name} exists — give this one another name", 409)
        return name

    def _set(self, raw):
        """"" (no cable), or the id of a set that exists now. An id no set has is
        refused, not dropped: the operator cabled something the board no longer has."""
        if raw is None or raw == "":
            return ""
        sid = ConsumerSet.clean(raw)
        if not sid:
            raise AppError('set must be a set\'s id, or "" to take the cable away', 400)
        if sid not in {s["id"] for s in self.sets()}:
            raise AppError(f"no set has the id {sid} — reload the board and draw the cable again", 400)
        return sid

    # ── the old form ─────────────────────────────────────────────────────────

    def migrate(self):
        """Every consumer of the form before 1.3.486 — the pools it might call,
        `models` — is given its one pool, once: the first of them, as the proxy
        reads it meanwhile (ConsumerPool.of), or none when none is left. Its
        router goes too: no router decides for a consumer. SetDesk.migrate moves
        that pool into a set right after (caravan/admin/model_sets.py). Answers
        `[{"name", "pool"}]` of the consumers rewritten, or None when there were none."""
        payload = self.read()
        routes = payload.get("routes") if isinstance(payload, dict) else None
        old = [r for r in routes or [] if isinstance(r, dict) and str(r.get("kind") or "") == self.KIND
               and "set" not in r and ("pool" not in r or "models" in r or str(r.get("routerId") or ""))]
        if not old:
            return None
        pools = self.pools()
        names = {p["id"]: EntryModels.name(p) for p in pools}
        done = []
        for route in old:
            route["pool"] = ConsumerPool.of(route, pools)
            route.pop("models", None)
            route["routerId"] = ""
            done.append({"name": str(route.get("label") or ""), "pool": names.get(route["pool"], "")})
        self.save(payload)
        return done

    def _consumer(self, payload, port):
        try:
            target = int(port)
        except (TypeError, ValueError):
            raise AppError("port must be a number", 400)
        route = next((r for r in payload["routes"] if int(r.get("port") or 0) == target), None)
        if route is None or str(route.get("kind") or "") != self.KIND:
            raise AppError(f"no consumer has the number {target}", 404)
        return route
