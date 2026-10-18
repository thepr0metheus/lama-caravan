"""What a consumer of the entry calls: the pools of its set, each by its name — OpenAI's model list.

The owner, 2026-10-12, a step on (step 2 of the visumap scheme caravan-model-sets): a consumer is
cabled to a SET in Routing, and the set to pools — chat, speech, embeddings, each a pool. One
set may serve several consumers. `GET /v1/models` lists the set's pools by name; a request's
`model` picks the pool, as OpenAI's API picks a model, and a name the set has not is 404
`model_not_found`. Below, the history of the one cable to one pool that came before.

The owner, 2026-10-11: the caravan speaks the OpenAI API the way the gateways
of companies do. A consumer knows one address and its own key; `GET /v1/models`
lists what that key may call. The owner, 2026-10-12: a consumer is cabled to
one pool in Routing — "only one cable goes on from a client" — so every
request of its key went to that pool, whatever `model` it named, until the
sets above (1.3.497). The pool is
listed by the name the operator gave it on the board; the providers, accounts
and rows behind it stay the caravan's. A consumer no cable reaches calls
nothing, and is told so.

Until 1.3.486 a consumer kept a list of the pools it might call (`models`:
"all" or pool ids) and named one in each request. A route of that form calls
the first of those pools (ConsumerPool.of) until the controller writes its one
pool down (caravan/admin/consumers.py, ConsumerDesk.migrate): the proxy starts
before the controller's migrations run.

The proxy reads this to list and to route, the board to draw a consumer's
set and its models and to refuse a second pool under a name already taken: one
reading for both, so the two can never disagree about what a key calls.
"""


class ModelAccess:
    """The pools a consumer of a route written before 1.3.486 might call (`models`).

    "all" — every pool, the ones made later too. A list — the pools named by
    their ids. Anything else reads as no pool at all: an empty list, said out
    loud rather than guessed into "all" (docs/why.md). Read only to find that
    consumer's one pool (ConsumerPool.of).
    """

    ALL = "all"
    MAX = 64

    @classmethod
    def clean(cls, raw):
        """`raw` as a route keeps it: "all", or the distinct pool ids in their order."""
        if raw == cls.ALL:
            return cls.ALL
        if not isinstance(raw, list):
            return []
        ids = []
        for item in raw:
            pid = str(item).strip()[:80] if isinstance(item, (str, int)) and not isinstance(item, bool) else ""
            if pid and pid not in ids:
                ids.append(pid)
        return ids[:cls.MAX]


class ConsumerPool:
    """The pool a consumer is cabled to, as its route keeps it (`pool`): a pool's
    id, or "" while no cable reaches the consumer — none, said as none."""

    MAX = 80

    @classmethod
    def clean(cls, raw):
        """A pool id as a route keeps it: trimmed, or "" for anything that is no id."""
        if isinstance(raw, bool) or not isinstance(raw, (str, int)):
            return ""
        return str(raw).strip()[:cls.MAX]

    @classmethod
    def fields(cls, route):
        """A consumer's own fields as both normalizers keep them: its `pool` — or,
        on a route of the old form, its `models`, until the controller rewrites it."""
        if "pool" in route:
            return {"pool": cls.clean(route.get("pool"))}
        return {"models": ModelAccess.clean(route.get("models"))}

    @classmethod
    def of(cls, route, pools):
        """The id of the pool `route` calls, or "" for none. A pool that is gone is
        none. A route of the old form calls the first of the pools it might: of
        "all", the first pool of the board; of a list, the first id a pool still has."""
        ids = [str(p.get("id")) for p in pools or [] if isinstance(p, dict) and p.get("id")]
        if "pool" in route:
            pid = cls.clean(route.get("pool"))
            return pid if pid in ids else ""
        access = ModelAccess.clean(route.get("models"))
        if access == ModelAccess.ALL:
            return ids[0] if ids else ""
        return next((pid for pid in access if pid in ids), "")


class ConsumerSet:
    """The set a consumer is cabled to, as its route keeps it (`set`): a set's id, or "" while no
    cable reaches the consumer — none, said as none."""

    MAX = 80

    @classmethod
    def clean(cls, raw):
        """A set id as a route keeps it: trimmed, or "" for anything that is no id."""
        if isinstance(raw, bool) or not isinstance(raw, (str, int)):
            return ""
        return str(raw).strip()[:cls.MAX]

    @classmethod
    def fields(cls, route):
        """A consumer's own fields as both normalizers keep them: its `set` — or, on a route of an
        older form, its `pool` (1.3.486–1.3.496) or its `models` (before), until the controller
        rewrites it (caravan/admin/model_sets.py, SetDesk.migrate)."""
        if "set" in route:
            return {"set": cls.clean(route.get("set"))}
        return ConsumerPool.fields(route)


class ModelSets:
    """The sets the board keeps (cloud-providers.json `sets`): `[{id, name, pools}]`, each pool once
    and in the set's order — the order of the consumer's model list. Anything that is no set is
    dropped, a set with no name is called by its id."""

    @staticmethod
    def clean(raw):
        out, seen = [], set()
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            sid = ConsumerSet.clean(item.get("id"))
            if not sid or sid in seen:
                continue
            seen.add(sid)
            pools = []
            for pid in item.get("pools") if isinstance(item.get("pools"), list) else []:
                pid = ConsumerPool.clean(pid)
                if pid and pid not in pools:
                    pools.append(pid)
            out.append({"id": sid, "name": str(item.get("name") or "").strip()[:80] or sid, "pools": pools})
        return out


class EntryModels:
    """The pools as the entry names them: a pool is called by its name.

    Two pools under one name would put one name on two models, and the
    operator could not tell on the board which one a consumer calls: the board
    refuses the second name (caravan/admin/pools.py). Names are compared as a
    person reads them, without case; a request for one model by its id must
    still spell it as the list does, as OpenAI's ids are.
    """

    def __init__(self, pools, sets=None):
        self.pools = [p for p in (pools or []) if isinstance(p, dict) and p.get("id")]
        self.sets = ModelSets.clean(sets)

    @staticmethod
    def name(pool):
        """The model id a pool is called by: its name, or its id when it has none."""
        return str(pool.get("name") or "").strip() or str(pool.get("id") or "")

    @classmethod
    def key(cls, name):
        """A name as two names are compared: trimmed, without case."""
        return str(name or "").strip().casefold()

    def taken(self, name, but=None):
        """Whether a pool other than `but` (an id) is already called `name`."""
        wanted = self.key(name)
        return any(self.key(self.name(p)) == wanted and p["id"] != but for p in self.pools)

    def set_of(self, route):
        """The set a consumer's route is cabled to, or None: no cable, or a set that is gone."""
        sid = ConsumerSet.clean((route or {}).get("set"))
        return next((s for s in self.sets if s["id"] == sid), None) if sid else None

    def models(self, route):
        """The pools a consumer's key calls, in its set's order — what /v1/models lists. A pool the
        set names that is gone is left out. A route of an older form (one pool, `pool`, or the pools
        it might call, `models`) calls its one pool until the controller rewrites it."""
        route = route or {}
        by_id = {p["id"]: p for p in self.pools}
        if "set" in route:
            return [by_id[pid] for pid in (self.set_of(route) or {}).get("pools", []) if pid in by_id]
        pid = ConsumerPool.of(route, self.pools)
        return [by_id[pid]] if pid in by_id else []

    def pick(self, route, model):
        """The pool a request's `model` names among the consumer's, spelled as the list spells it
        (OpenAI's ids are); None for a name its key does not call."""
        wanted = str(model or "")
        return next((p for p in self.models(route) if self.name(p) == wanted), None) if wanted else None

    def callers(self, routes, pool_id):
        """The consumers of the entry that call `pool_id`, by name: who loses that model when the
        pool goes (caravan/admin/pools.py). The same reading as `models`."""
        pool_id = str(pool_id or "")
        return [str(r.get("label") or "") for r in routes or []
                if isinstance(r, dict) and str(r.get("kind") or "") == "consumer"
                and any(p["id"] == pool_id for p in self.models(r))]
