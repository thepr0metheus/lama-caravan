"""The sets of models the entry's clients call — Routing's «Набор».

The owner, 2026-10-12 (step 2 of the visumap scheme caravan-model-sets): a client of the entry is
cabled to a set, and the set to pools — chat, speech, embeddings, each a pool. A set may serve
several clients ("shared"), and changing it changes what all of them see. `GET /v1/models` lists a
client's set, a request's `model` picks a pool of it, and a name the set has not is 404
(caravan/common/entry_models.py, the one reading the proxy and the board share).

cloud-providers.json keeps the sets beside the pools they hold, under `sets`:
`[{"id", "name", "pools": [pool ids]}]` — a pool deleted leaves every set in the same write
(caravan/admin/pools.py). A client keeps its set's id as `set` on its route in agent-proxies.json.
Until 1.3.497 a client was cabled to one pool: SetDesk.migrate gives each pool so cabled one set
of that pool, shared by its clients, once.
"""
import re

from caravan.common.cloud_pools import CloudPools
from caravan.common.entry_models import ConsumerPool, ConsumerSet, EntryModels, ModelSets
from caravan.common.errors import AppError


class SetDesk:
    """The sets on the controller's files: made, named, filled with pools, emptied, deleted."""

    #: The clients' one pool moved into sets (1.3.497), stamped once.
    MIGRATION = "model-sets-2026-10"
    NEW_NAME = "Set"
    NAME_MAX = 80

    def __init__(self, load=None, save=None, proxies=None, save_proxies=None):
        # cloud.py and proxies_config.py import Routing's modules at the top; taken here.
        from caravan.admin.cloud import load_cloud_data, save_cloud_data
        from caravan.admin.proxies_config import read_agent_proxy_payload, write_agent_proxy_payload
        self.load, self.save = load or load_cloud_data, save or save_cloud_data
        self.proxies, self.save_proxies = proxies or read_agent_proxy_payload, save_proxies or write_agent_proxy_payload

    # ── reading ──────────────────────────────────────────────────────────

    @staticmethod
    def _pools(data):
        return {p["id"]: p for p in CloudPools(data).all()}

    def state(self, data=None):
        """Every set as the board draws it: its pools that still exist, in its order."""
        data = self.load() if data is None else data
        pools = self._pools(data)
        return [{**s, "pools": [pid for pid in s["pools"] if pid in pools]} for s in ModelSets.clean(data.get("sets"))]

    def _sets(self, data):
        return ModelSets.clean(data.get("sets"))

    def _set(self, sets, set_id):
        sid = ConsumerSet.clean(set_id)
        found = next((s for s in sets if s["id"] == sid), None)
        if found is None:
            raise AppError(f"no set has the id {sid or '(none)'} — reload the board", 404)
        return found

    @staticmethod
    def _key(name):
        return EntryModels.key(name)

    def _name(self, sets, name, but=None):
        """A name the operator gave: required, and not another set's — two sets alike could not be
        told apart in Routing."""
        name = str(name or "").strip()[:self.NAME_MAX]
        if not name:
            raise AppError("a set needs a name", 400)
        if any(self._key(s["name"]) == self._key(name) and s["id"] != but for s in sets):
            raise AppError(f"a set named {name} exists — give this one another name", 409)
        return name

    def _free_name(self, sets, name):
        """A name of the board's own choosing, made free with " 2", " 3"…: a default is not worth a refusal."""
        taken = {self._key(s["name"]) for s in sets}
        candidate, number = name, 2
        while self._key(candidate) in taken:
            candidate, number = f"{name} {number}"[:self.NAME_MAX], number + 1
        return candidate

    @staticmethod
    def _slug(text, taken):
        base = re.sub(r"[^A-Za-z0-9_-]", "-", str(text or ""))[:40].strip("-") or "set"
        sid, number = base, 2
        while sid in taken:
            sid, number = f"{base}-{number}", number + 1
        return sid

    def _new(self, sets, name):
        """A set under a free id, named `name`, put last."""
        made = {"id": self._slug(name, {s["id"] for s in sets}), "name": name, "pools": []}
        sets.append(made)
        return made

    # ── what the operator does ───────────────────────────────────────────

    def create(self, name=""):
        """"＋ New set": an empty set under "Set" — "Set 2" when that is taken — or under the name
        given, which must be free."""
        data = self.load()
        sets = self._sets(data)
        typed = str(name or "").strip()
        made = self._new(sets, self._name(sets, typed) if typed else self._free_name(sets, self.NEW_NAME))
        data["sets"] = sets
        self.save(data)
        return made

    def rename(self, set_id, name):
        data = self.load()
        sets = self._sets(data)
        found = self._set(sets, set_id)
        found["name"] = self._name(sets, name, but=found["id"])
        data["sets"] = sets
        self.save(data)
        return found

    def order(self, ids):
        """The sets in the order Routing's column shows them, from the board's drag (1.3.503):
        `ids` names every set once. A list that does not is refused 409 — the board drew sets
        another page has since made or deleted, and must draw them again."""
        data = self.load()
        sets = self._sets(data)
        by_id = {s["id"]: s for s in sets}
        wanted = [ConsumerSet.clean(i) for i in ids] if isinstance(ids, list) else None
        if wanted is None or len(set(wanted)) != len(wanted) or set(wanted) != set(by_id):
            raise AppError("the sets changed since the board was drawn — draw it again and move the card again", 409)
        data["sets"] = [by_id[i] for i in wanted]
        self.save(data)
        return wanted

    def add_pool(self, set_id, pool_id):
        """A pool becomes a model of the set — a cable from the set onto it. Last, once: a pool the
        set holds already stays where it is."""
        data = self.load()
        sets = self._sets(data)
        found = self._set(sets, set_id)
        pid = ConsumerPool.clean(pool_id)
        if pid not in self._pools(data):
            raise AppError(f"no pool has the id {pid or '(none)'} — reload the board and draw the cable again", 400)
        if pid not in found["pools"]:
            found["pools"].append(pid)
            data["sets"] = sets
            self.save(data)
        return found

    def remove_pool(self, set_id, pool_id):
        """A pool stops being a model of the set — its cable cut. One the set has not: nothing to do."""
        data = self.load()
        sets = self._sets(data)
        found = self._set(sets, set_id)
        pid = ConsumerPool.clean(pool_id)
        if pid in found["pools"]:
            found["pools"].remove(pid)
            data["sets"] = sets
            self.save(data)
        return found

    def delete(self, set_id):
        """Delete a set. Its clients lose their cable — left there, its id would wait for the next
        set of that id, and a client would call models the operator never gave it. Answers
        {"deleted", "uncabled": [the clients' names]}."""
        data = self.load()
        sets = self._sets(data)
        found = self._set(sets, set_id)
        payload = self.proxies()
        uncabled = []
        for route in payload.get("routes") or []:
            if isinstance(route, dict) and str(route.get("kind") or "") == "consumer" \
                    and ConsumerSet.clean(route.get("set")) == found["id"]:
                route["set"] = ""
                uncabled.append(str(route.get("label") or ""))
        data["sets"] = [s for s in sets if s["id"] != found["id"]]
        self.save(data)
        if uncabled:
            self.save_proxies(payload)
        return {"deleted": found["id"], "uncabled": uncabled}

    # ── the old form ─────────────────────────────────────────────────────

    def migrate(self):
        """Every client cabled to one pool (1.3.486–1.3.496, or of the older form that named the
        pools it might call) is cabled to a set instead, once: one set per pool so cabled, named as
        the pool, holding it, shared by the clients that called it. A client with no pool gets no
        set. The sets are written first: until its route is rewritten the proxy reads the client's
        old field (EntryModels.models). Answers {"sets": [the names made], "clients": [{"name",
        "set"}]}, or None when it was done."""
        data = self.load()
        if self.MIGRATION in (data.get("migrations") or []):
            return None
        payload = self.proxies()
        routes = [r for r in payload.get("routes") or [] if isinstance(r, dict)
                  and str(r.get("kind") or "") == "consumer" and "set" not in r]
        pools = CloudPools(data).all()
        names = {p["id"]: EntryModels.name(p) for p in pools}
        sets = self._sets(data)
        made, clients = {}, []
        for route in routes:
            pid = ConsumerPool.of(route, pools)
            if pid and pid not in made:
                made[pid] = self._new(sets, self._free_name(sets, names.get(pid) or pid))
                made[pid]["pools"].append(pid)
            route["set"] = made[pid]["id"] if pid else ""
            route.pop("pool", None)
            route.pop("models", None)
            clients.append({"name": str(route.get("label") or ""), "set": made[pid]["name"] if pid else ""})
        data["sets"] = sets
        data["migrations"] = sorted(set(data.get("migrations") or []) | {self.MIGRATION})
        self.save(data)
        if routes:
            self.save_proxies(payload)
        return {"sets": [s["name"] for s in made.values()], "clients": clients}
