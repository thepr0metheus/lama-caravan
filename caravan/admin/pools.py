"""The pools on the controller's files: what the kanban edits and what it shows.

A pool is an ordered list of rows — an account with one model, a local model,
or nothing yet (caravan/common/cloud_pools.py) — and what a client's cable goes
to: cloud-providers.json keeps the pools, the accounts and each subscription
model's levels, agent-proxies.json the clients. The proxy chooses the row per
request (caravan/proxy/pool_steps.py); this desk never routes.

The owner, 2026-10-12: a pool is made empty with "+ Pool", a row comes with
"+ row", and the row's output is cabled to a model on the right. A subscription
model's stop and switch levels are the model's, the same in every pool
(caravan/common/model_levels.py): a model nobody set them for keeps 10% of each
window (the operator, 2026-10-08: a new subscription keeps 10% from the start).
The models on the right are the ones the operator added there
(caravan/admin/added_models.py), and a model a row is cabled to is one of them.
"""
import json
import re
import time

from caravan.admin.added_models import AddedModels
from caravan.admin.cloud import load_cloud_data, load_provider_secrets, save_cloud_data
from caravan.admin.cloud_refs import CloudModelRefs, CloudModelRewire
from caravan.admin.paths import AGENT_PROXY_STATE_FILE, PROVIDER_SECRETS_FILE
from caravan.admin.proxies_config import load_agent_proxy_config, pool_output, save_agent_proxy_config
from caravan.common.cloud_pools import CloudPools
from caravan.common.cloud_sources import CloudSources
from caravan.common.credential_vault import CredentialVault
from caravan.common.entry_models import EntryModels, ModelSets
from caravan.common.errors import AppError
from caravan.common.model_levels import ModelLevels
from caravan.common.model_schedules import ModelSchedules
from caravan.common.proxy_heartbeat import ProxyHeartbeat
from caravan.common.usage_reserve import UsageReserve


class PoolDesk:
    #: The rewrite of the old form, stamped into the file once it is done.
    MIGRATION = "pools-of-steps-2026-10"
    #: The steps' own levels moved onto their models (1.3.486), stamped once.
    ROWS_MIGRATION = "pools-of-rows-2026-10"
    #: The models the rows name added to the kanban's column (1.3.491), stamped once.
    ADDED_MIGRATION = "added-models-2026-10"
    NAME_MAX = 80
    #: The name of a pool made with "+ Pool" before the operator names it.
    NEW_NAME = "Pool"

    def __init__(self, load=None, save=None, proxies=None, save_proxies=None, state_file=None,
                 clock=time.time, vault=None):
        self.load, self.save = load or load_cloud_data, save or save_cloud_data
        self.proxies = proxies or load_agent_proxy_config
        self.save_proxies = save_proxies or save_agent_proxy_config
        self.state_file, self.clock = state_file or AGENT_PROXY_STATE_FILE, clock
        self.vault = vault or CredentialVault(PROVIDER_SECRETS_FILE)

    # ── the old form ────────────────────────────────────────────────────

    def migrate(self):
        """Rewrite a file of the old form as pools of steps, once. A model
        block becomes a pool with its id (caravan/common/cloud_pools.py) when
        it is on the kanban or anything points at it; the rest were copies of a
        provider's list, and go. The accounts' reserves became their steps'
        switch levels. Answers {"pools": ids, "dropped": block ids}, or None
        when there is nothing to rewrite."""
        data = self.load()
        if not CloudPools.legacy(data):
            return None
        refs = CloudModelRefs(self.proxies())
        blocks = data.get("blocks") or []
        keep = {b["id"] for b in blocks if b.get("exposed") or refs.in_use(b["id"])}
        reading = CloudPools(data, self.vault.read())
        converted = reading.pools
        data["pools"] = [converted[b["id"]] for b in blocks if b["id"] in keep and b["id"] in converted]
        dropped = [b["id"] for b in blocks if b["id"] not in keep]
        # The reserve each account kept becomes its models' levels — the step a
        # block becomes carries none of its own since 1.3.486.
        kept_steps = [s for s in reading.legacy_steps
                      if any(s.get("accountId") == r.get("accountId") and s.get("model") == r.get("model")
                             for p in data["pools"] for r in p["steps"])]
        data["levels"] = ModelLevels({"levels": data.get("levels"), "pools": [{"steps": kept_steps}]}).stored()
        for account in data.get("accounts") or []:
            account.pop("usageReserve", None)
        data.pop("blocks", None)
        data.pop("deletedModels", None)
        data["migrations"] = sorted(set(data.get("migrations") or []) | {self.MIGRATION, self.ROWS_MIGRATION})
        self.save(data)
        return {"pools": [p["id"] for p in data["pools"]], "dropped": dropped}

    def migrate_rows(self):
        """Move the levels each step kept onto its model, once (1.3.486): a
        model named by steps with different levels keeps the stricter of each
        (caravan/common/model_levels.py). Answers {"models": count, "steps":
        count} — the models whose levels were set and the steps they came from —
        or None when there is nothing to move."""
        data = self.load()
        if self.ROWS_MIGRATION in (data.get("migrations") or []) or CloudPools.legacy(data):
            return None
        levels = ModelLevels(data)
        moved = 0
        for pool in data.get("pools") or []:
            for step in (pool.get("steps") or []) if isinstance(pool, dict) else []:
                if isinstance(step, dict) and any(key in step for key in ModelLevels.KEYS):
                    moved += 1
                    for key in ModelLevels.KEYS:
                        step.pop(key, None)
        data["levels"] = levels.stored()
        data["migrations"] = sorted(set(data.get("migrations") or []) | {self.ROWS_MIGRATION})
        self.save(data)
        return {"models": sum(len(models) for models in data["levels"].values()), "steps": moved}

    def migrate_added(self):
        """Add the models the pools' rows name to the kanban's column, once
        (1.3.491): until then it showed every model an account offers, and the
        ones in use stay on it. Answers {"models": count} — the models added —
        or None when it was done before, or while the file is of the old form
        (its pools do not exist yet)."""
        data = self.load()
        if self.ADDED_MIGRATION in (data.get("migrations") or []) or CloudPools.legacy(data):
            return None
        added = AddedModels(data)
        count = sum(1 for pool in self._pools(data).values() for row in pool["steps"]
                    if row["kind"] == "account" and added.add(row["accountId"], row["model"]))
        data["addedModels"] = added.stored()
        data["migrations"] = sorted(set(data.get("migrations") or []) | {self.ADDED_MIGRATION})
        self.save(data)
        return {"models": count}

    # ── reading ─────────────────────────────────────────────────────────

    def _pools(self, data):
        return CloudPools(data).pools

    def _pool(self, data, pool_id):
        pool = CloudPools(data).get(pool_id)
        if not pool:
            raise AppError(f"unknown pool: {pool_id}", 404)
        return pool

    def _put(self, data, pool):
        """`pool` in place of its stored self (or last, for a new one), kept by the shared rule."""
        kept = CloudPools.pool(pool)
        pools = [p for p in data.get("pools") or [] if isinstance(p, dict)]
        index = next((i for i, p in enumerate(pools) if p.get("id") == kept["id"]), None)
        if index is None:
            pools.append(kept)
        else:
            pools[index] = kept
        data["pools"] = pools
        return kept

    def _account(self, data, account_id):
        account = CloudSources(data).accounts.get(str(account_id or ""))
        if not account:
            raise AppError(f"unknown account: {account_id}", 404)
        return account

    @staticmethod
    def _model(model):
        model = str(model or "").strip()
        if not model:
            raise AppError("a step needs a model", 400)
        return model

    def _name(self, name, fallback):
        name = str(name or "").strip()[:self.NAME_MAX]
        return name or fallback

    def _unique(self, data, name, but=None):
        """`name`, when no other pool carries it: a consumer of the entry calls a
        pool by its name (caravan/common/entry_models.py), and two pools under
        one name would make one model id call two chains."""
        if EntryModels(list(self._pools(data).values())).taken(name, but=but):
            raise AppError(f"a pool named {name} exists — consumers call a pool by its name, "
                           f"so give this one another", 409)
        return name

    def _free_name(self, data, name):
        """A name of the board's own choosing — a new pool's model, when the
        operator gave none — made free with " 2", " 3"…: a default is not worth
        a refusal."""
        names, candidate, number = EntryModels(list(self._pools(data).values())), name, 2
        while names.taken(candidate):
            candidate, number = f"{name} {number}"[:self.NAME_MAX], number + 1
        return candidate

    @staticmethod
    def _slug(text, taken):
        base = re.sub(r"[^A-Za-z0-9_-]", "-", str(text or ""))[:40].strip("-") or "pool"
        pid, number = base, 2
        while pid in taken:
            pid, number = f"{base}-{number}", number + 1
        return pid

    @classmethod
    def default_named(cls, name):
        """Whether `name` is one the board gave — "Pool", "Pool 2"… — not the operator."""
        return bool(re.fullmatch(re.escape(cls.NEW_NAME) + r"( \d+)?", str(name or "")))

    @staticmethod
    def _cabled(pool):
        return any(s.get("kind") in ("account", "output") for s in pool.get("steps") or [])

    def _named_after(self, data, pool, name_after, cabled_before):
        """A pool the operator never named takes the name of the model its first cable reaches (the
        owner, 2026-10-12: "a pool of one model is named after it" — `name_after`, the board's own
        word for that model). A pool's name is what its clients call it by, so only a pool that
        served nobody yet — the board's name, no row cabled before — is renamed; a name already
        taken gets " 2", " 3"."""
        name = self._name(name_after, "")
        if name and not cabled_before and self.default_named(pool.get("name")):
            pool["name"] = self._free_name(data, name)

    def _new_step(self, data, pool, account_id, model):
        """A step of `account_id` with `model`, under an id the pool does not
        use yet. Its levels are its model's (caravan/common/model_levels.py),
        and its model is on the kanban's column (_keep)."""
        account = self._account(data, account_id)
        step = {"id": CloudPools.step_id(account["id"], {s["id"] for s in pool["steps"]}),
                "accountId": account["id"], "model": self._model(model), "enabled": True}
        self._keep(data, step)
        return step

    @staticmethod
    def _keep(data, target):
        """A model a row is cabled to is one the kanban's column shows
        (caravan/admin/added_models.py): added with the cable, so a cable taken
        away later leaves its model in place. A local output is not a model of
        an account, and adds nothing."""
        if target.get("accountId") and target.get("model"):
            added = AddedModels(data)
            if added.add(target["accountId"], target["model"]):
                data["addedModels"] = added.stored()

    def _target(self, data, target):
        """What a row's output is cabled to, as the row keeps it: an account and
        one of its models, a local output by its id, or None — the cable taken
        away, or never drawn."""
        if target in (None, "", {}):
            return {}
        if not isinstance(target, dict):
            raise AppError("target must be an object: {accountId, model} or {output}", 400)
        if target.get("output"):
            output = str(target["output"]).strip()
            if not CloudPools.OUTPUT.match(output):
                raise AppError(f"not a local model: {output}", 400)
            return {"output": output}
        account = self._account(data, target.get("accountId"))
        return {"accountId": account["id"], "model": self._model(target.get("model"))}

    @staticmethod
    def _untargeted(row):
        return {key: value for key, value in row.items() if key not in ("accountId", "model", "output", "kind")}

    # ── pools ───────────────────────────────────────────────────────────

    def create(self, name="", account_id="", model="", target=None, name_after=""):
        """A new pool. "+ Pool" on the kanban makes it empty, under "Pool" — or
        "Pool 2", "Pool 3" when that name is taken; given an account and a
        model, or a `target` as a row takes it (an account's model or a local
        output), it starts with that row, named after its model — `name_after`,
        the board's word for it, else the account's model id — unless named. Its
        id comes from its name. A name the operator gave must be free; one the
        board chose gets " 2", " 3" instead."""
        data = self.load()
        if target not in (None, "", {}):
            first = self._target(data, target)
        else:
            first = self._target(data, {"accountId": account_id, "model": model}) if account_id or model else {}
        typed = self._name(name, "")
        name = (self._unique(data, typed) if typed
                else self._free_name(data, self._name(name_after, "") or first.get("model") or self.NEW_NAME))
        pool = {"id": self._slug(name, set(self._pools(data))), "name": name, "steps": [], "contextAuto": True}
        if first.get("accountId"):
            pool["steps"].append(self._new_step(data, pool, first["accountId"], first["model"]))
        elif first.get("output"):
            pool["steps"].append({"id": CloudPools.row_id(set()), "enabled": True, **first})
        kept = self._put(data, pool)
        self.save(data)
        return kept

    def add_row(self, pool_id, target=None, name_after=""):
        """One more row at the end of the pool: open, or cabled at once — and a pool the operator
        never named takes the name of the model this first cable reaches (_named_after)."""
        data = self.load()
        pool = self._pool(data, pool_id)
        cabled_before = self._cabled(pool)
        row = {"id": CloudPools.row_id({s["id"] for s in pool["steps"]}), "enabled": True,
               **self._target(data, target)}
        self._keep(data, row)
        pool["steps"].append(row)
        if row.get("accountId") or row.get("output"):
            self._named_after(data, pool, name_after, cabled_before)
        kept = self._put(data, pool)
        self.save(data)
        return kept

    def connect_row(self, pool_id, row_id, target, name_after=""):
        """The row's output cabled to `target`, or its cable taken away (None).
        The row keeps its place and its id. A pool the operator never named takes
        the name of the model its first cable reaches (_named_after)."""
        data = self.load()
        pool = self._pool(data, pool_id)
        if not any(s["id"] == row_id for s in pool["steps"]):
            raise AppError(f"pool {pool_id} has no row {row_id}", 404)
        cabled_before = self._cabled(pool)
        cabled = self._target(data, target)
        self._keep(data, cabled)
        pool["steps"] = [{**self._untargeted(s), **cabled} if s["id"] == row_id else s for s in pool["steps"]]
        if cabled:
            self._named_after(data, pool, name_after, cabled_before)
        kept = self._put(data, pool)
        self.save(data)
        return kept

    def order(self, ids):
        """The pools in the order the kanban's column shows them, from the board's drag: `ids` names
        every pool once. A list that does not is refused 409 — the board drew pools another page has
        since added or deleted, and must draw them again."""
        data = self.load()
        pools = [p for p in data.get("pools") or [] if isinstance(p, dict)]
        by_id = {str(p.get("id")): p for p in pools}
        wanted = [str(i) for i in ids] if isinstance(ids, list) else None
        if wanted is None or len(set(wanted)) != len(wanted) or set(wanted) != set(by_id):
            raise AppError("the pools changed since the board was drawn — draw it again and move the card again", 409)
        data["pools"] = [by_id[i] for i in wanted]
        self.save(data)
        return wanted

    def arrange(self):
        """"Arrange by cables" (the owner, 2026-10-12): the pools in the order the sets name them —
        the first set's pools first — then the rest as they stood; each account's added models in the
        order the arranged pools' rows name them, then the rest. Cables then run more alongside one
        another than across. Answers the pools' new order."""
        data = self.load()
        pools = [p for p in data.get("pools") or [] if isinstance(p, dict)]
        by_id = {str(p.get("id")): p for p in pools}
        order = []
        for model_set in data.get("sets") or []:
            for pid in (model_set.get("pools") or []) if isinstance(model_set, dict) else []:
                if str(pid) in by_id and str(pid) not in order:
                    order.append(str(pid))
        order += [str(p.get("id")) for p in pools if str(p.get("id")) not in order]
        data["pools"] = [by_id[i] for i in order]
        named = {}
        reading = CloudPools(data)
        for pid in order:
            for row in (reading.get(pid) or {}).get("steps") or []:
                if row.get("kind") == "account":
                    named.setdefault(row["accountId"], []).append(row["model"])
        added = AddedModels(data)
        for account_id, models in named.items():
            added.put_first(account_id, models)
        data["addedModels"] = added.stored()
        self.save(data)
        return order

    def save_pool(self, supplied):
        """An edit of a pool as the board sends it whole: its name, window, and
        the steps — their order, switches, levels and models. A step names an
        existing account and a model; a step the stored pool does not have is
        refused (a new one comes by add_step). The hand pick a page from before
        1.3.463 may still send (mode, manualStepId, manualUntil) is not kept:
        a pool goes by its order (caravan/common/cloud_pools.py)."""
        if not isinstance(supplied, dict):
            raise AppError("pool must be an object", 400)
        data = self.load()
        stored = self._pool(data, supplied.get("id"))
        raw = supplied.get("steps", stored["steps"])
        if not isinstance(raw, list):
            raise AppError("pool.steps must be a list", 400)
        known, seen, steps = {s["id"]: s for s in stored["steps"]}, set(), []
        for item in raw:
            if not isinstance(item, dict) or item.get("id") not in known or item["id"] in seen:
                raise AppError("pool.steps: each step once, and only the pool's own", 400)
            seen.add(item["id"])
            row = known[item["id"]]
            # A page from before 1.3.463 sends a "manual only" row as automatic:
            # false — the order passes it by, so it is kept switched off.
            enabled = bool(item.get("enabled", row["enabled"])) and bool(item.get("automatic", True))
            if row["kind"] == "account":
                # An account row's model may be edited here, as before rows.
                account = self._account(data, item.get("accountId", row["accountId"]))
                steps.append({**row, "enabled": enabled, "accountId": account["id"],
                              "model": self._model(item.get("model", row["model"]))})
                self._keep(data, steps[-1])
            else:
                # What another row is cabled to changes by connect_row, not here.
                steps.append({**row, "enabled": enabled})
        window = supplied.get("contextLength", stored.get("contextLength"))
        if window not in (None, "") and CloudPools._positive(window) is None:
            raise AppError("contextLength must be a positive number or empty", 400)
        name = self._name(supplied.get("name", stored["name"]), stored["name"])
        pool = {**stored, "name": self._unique(data, name, but=stored["id"]),
                "steps": steps, "contextLength": window, "contextAuto": bool(supplied.get("contextAuto", stored["contextAuto"]))}
        kept = self._put(data, pool)
        self.save(data)
        return kept

    def add_step(self, pool_id, account_id, model):
        """One more step at the end of the pool."""
        data = self.load()
        pool = self._pool(data, pool_id)
        pool["steps"].append(self._new_step(data, pool, account_id, model))
        kept = self._put(data, pool)
        self.save(data)
        return kept

    def remove_step(self, pool_id, step_id):
        """The step leaves the pool; its account stays connected. A pool may
        be left with no step: a request is then refused with "add one"."""
        data = self.load()
        pool = self._pool(data, pool_id)
        if not any(s["id"] == step_id for s in pool["steps"]):
            raise AppError(f"pool {pool_id} has no step {step_id}", 404)
        pool["steps"] = [s for s in pool["steps"] if s["id"] != step_id]
        kept = self._put(data, pool)
        self.save(data)
        return kept

    #: The two levels of a model's window (caravan/common/usage_reserve.py), by
    #: the name the page sends and the key the model keeps them under.
    LEVELS = {"switch": "switchAt", "stop": "stopAt"}

    def set_level(self, account_id, model, window_seconds, pct, level):
        """One level of one window of a subscription's model: `stop` — the
        share of the window the model never spends — or `switch` — the share
        from which a pool sends requests to its next rows first. 0 lifts it. It
        holds in every pool that names the model. The switch stays at or above
        the stop: a stop raised past it takes it along, and a switch lowered past
        the stop rests on it. Answers both levels after the change, {"switchAt",
        "stopAt"}."""
        key = self.LEVELS.get(str(level or ""))
        if not key:
            raise AppError("level must be switch or stop", 400)
        try:
            seconds, pct = int(window_seconds), int(pct)
        except (TypeError, ValueError):
            raise AppError("windowSeconds and pct must be numbers", 400)
        if seconds <= 0:
            raise AppError("windowSeconds must be positive", 400)
        if not 0 <= pct <= UsageReserve.MAX_PCT:
            raise AppError(f"pct must be 0..{UsageReserve.MAX_PCT}", 400)
        data = self.load()
        account = self._account(data, account_id)
        model = self._model(model)
        if not CloudSources.is_subscription(account):
            # Only a subscription states its windows; a level elsewhere would be
            # a setting that silently does nothing.
            raise AppError("a level is kept only on a ChatGPT subscription's model", 400)
        levels = ModelLevels(data)
        stop, switch = levels.of(account["id"], model)
        pair = {"stopAt": stop, "switchAt": switch}
        # A stop raised past the switch takes it along: ModelLevels keeps the
        # switch at least the stop.
        if pct:
            pair[key][str(seconds)] = pct
        else:
            pair[key].pop(str(seconds), None)
        # A switch lowered past the stop rests on it, as ModelLevels keeps it.
        stop, switch = levels.put(account["id"], model, pair["stopAt"], pair["switchAt"])
        data["levels"] = levels.stored()
        self.save(data)
        return {"switchAt": switch, "stopAt": stop}

    def row_target(self, pool_id, step_id):
        """The account and model a pool's account row names — the page before
        1.3.486 set a level by its pool and step."""
        data = self.load()
        row = next((s for s in self._pool(data, pool_id)["steps"] if s["id"] == step_id), None)
        if not row:
            raise AppError(f"pool {pool_id} has no step {step_id}", 404)
        if row["kind"] != "account":
            raise AppError("a level is kept only on a subscription's model", 400)
        return row["accountId"], row["model"]

    def delete(self, pool_id, resolution=None):
        """Delete a pool. When the routers hold it — cables into it, rules that
        name it — `resolution` says what happens to them: {"moveTo": <another
        pool>} or {"cut": True}; without one the answer is 409, so nothing stops
        reaching its model without a word. It leaves every set of models that
        holds it, in the same write (caravan/admin/model_sets.py): their clients
        lose that model. Answers {"deleted", "moved", "cut", "onto", "uncabled",
        "unset": the sets it left}."""
        data = self.load()
        pool = self._pool(data, pool_id)
        payload = self.proxies()
        refs = CloudModelRefs(payload)
        held = refs.held(pool["id"])
        answer = resolution if isinstance(resolution, dict) else {}
        onto = str(answer.get("moveTo") or "").strip()
        moved = cut = 0
        if held["cables"] or held["rules"]:
            if onto:
                if onto == pool["id"]:
                    raise AppError("move the cables onto another pool", 400)
                moved = CloudModelRewire(payload).move(pool["id"], onto, output=pool_output(self._pool(data, onto)))
            elif answer.get("cut"):
                cut = refs.cut(pool["id"])
            else:
                raise AppError(f"pool {pool['id']}: {held['cables']} cable(s) and rules {held['rules']} lead to it "
                               "on the kanban — move them onto another pool, or disconnect them", 409)
        else:
            onto = ""
        routes = payload.get("routes") or []
        uncabled = self._uncable(routes, pool["id"])
        self.save_proxies(routes, payload.get("routers"))
        data["pools"] = [p for p in data.get("pools") or [] if isinstance(p, dict) and p.get("id") != pool["id"]]
        sets = ModelSets.clean(data.get("sets"))
        unset = [s["name"] for s in sets if pool["id"] in s["pools"]]
        if unset:
            data["sets"] = [{**s, "pools": [pid for pid in s["pools"] if pid != pool["id"]]} for s in sets]
        self.save(data)
        return {"deleted": pool["id"], "moved": moved, "cut": cut, "onto": onto or None, "uncabled": uncabled,
                "unset": unset}

    @staticmethod
    def _uncable(routes, pool_id):
        """The clients cabled to the deleted pool lose their cable, and the count of them.
        Left there, its id waited for the next pool of that id — pool ids come from their names —
        and a client would call a pool the operator never gave it (2026-10-11). Only a client of
        the form before 1.3.497 has a pool of its own; one of a set loses the model with the set."""
        uncabled = 0
        for route in routes:
            if str(route.get("kind") or "") == "consumer" and str(route.get("pool") or "") == pool_id:
                route["pool"] = ""
                uncabled += 1
        return uncabled

    # ── accounts ────────────────────────────────────────────────────────

    def remove_account(self, account_id):
        """Delete one account and every step that names it, in every pool. A
        pool keeps its other steps. Legacy test aliases stay dependent and must
        go first. Answers the credential entry the vault removed, or None."""
        account_id = str(account_id or "").strip()
        data = self.load()
        if any(a.get("testAliasOf") == account_id for a in data["accounts"]):
            raise AppError("delete this account's legacy test aliases first", 409)
        for pool in self._pools(data).values():
            if any(s.get("accountId") == account_id for s in pool["steps"]):
                gone = {s["id"] for s in pool["steps"] if s.get("accountId") == account_id}
                pool["steps"] = [s for s in pool["steps"] if s["id"] not in gone]
                self._put(data, pool)
        levels = ModelLevels(data)
        levels.forget_account(account_id)
        data["levels"] = levels.stored()
        added = AddedModels(data)
        added.forget_account(account_id)
        data["addedModels"] = added.stored()
        schedules = ModelSchedules(data)
        schedules.forget_account(account_id)
        data["schedules"] = schedules.stored()
        data["accounts"] = [a for a in data["accounts"] if a.get("id") != account_id]
        self.save(data)
        return self.vault.delete(account_id)

    def clone_test(self, source_id):
        """A labelled routing-test alias of a subscription: its owner's sign-in
        and quota under another name. Asking again answers the same alias."""
        data = self.load()
        sources = CloudSources(data)
        owner = sources.canonical(source_id)
        if not CloudSources.is_subscription(owner):
            raise AppError("test aliases require an existing ChatGPT subscription", 400)
        existing = next((a for a in data["accounts"] if a.get("testAliasOf") == owner["id"]), None)
        if existing:
            return existing
        stem = owner["id"][:40] + "-test"
        aid, number = stem, 2
        while aid in sources.accounts:
            aid, number = f"{stem}-{number}", number + 1
        alias = {**owner, "id": aid, "name": owner.get("name", owner["id"]) + " · TEST", "testAliasOf": owner["id"]}
        data["accounts"].append(alias)
        self.save(data)
        return alias

    # ── the models on the right ─────────────────────────────────────────

    def add_model(self, account_id, model):
        """Put one of an account's models on the kanban's column ("＋ model"),
        last. One that is there already stays where it is. Any id is taken, the
        list's or a typed one: a list lags behind its provider. Answers the
        account's models, in their order."""
        data = self.load()
        account = self._account(data, account_id)
        added = AddedModels(data)
        if added.add(account["id"], self._model(model)):
            data["addedModels"] = added.stored()
            self.save(data)
        return added.of(account["id"])

    def remove_model(self, account_id, model):
        """Take a model off the kanban's column (its ✕). Refused while a pool's
        row names it: the row's cable would have no model to land on, so that
        cable goes first. Its levels and its schedule stay
        (caravan/common/model_levels.py, model_schedules.py): put back, it has
        them again. One that is not there — nothing to do. Answers the account's
        models left."""
        data = self.load()
        account = self._account(data, account_id)
        model = self._model(model)
        holders = [pool["name"] for pool in self._pools(data).values()
                   if any(row["kind"] == "account" and row["accountId"] == account["id"] and row["model"] == model
                          for row in pool["steps"])]
        if holders:
            raise AppError(f"{model}: a row of {', '.join(holders)} is cabled to it — take that cable away first", 409)
        added = AddedModels(data)
        if added.remove(account["id"], model):
            data["addedModels"] = added.stored()
            self.save(data)
        return added.of(account["id"])

    def added_models(self):
        """The models on the kanban's column, by account, in the order they were
        added (caravan/admin/added_models.py)."""
        return AddedModels(self.load()).stored()

    # ── what the board draws ────────────────────────────────────────────

    def _state(self):
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None

    def runtime(self):
        """The proxy's word on each pool — which step served last, why the
        others did not, the switches — while the proxy is alive to say it."""
        state = self._state()
        if not isinstance(state, dict) or not ProxyHeartbeat.fresh(state.get("time"), self.clock()):
            return {"available": False, "pools": {}, "events": []}
        rows = state.get("pools") or {}
        return {"available": True, "pools": rows.get("pools", {}), "events": rows.get("events", [])}

    def model_levels(self):
        """The levels of the subscription models as the kanban's right column draws
        them (caravan/common/model_levels.py): `set` — the pairs the operator
        set, by account and model; `default` — the pair of a model nobody set;
        `max` — the highest share a level may take. A model is drawn with its
        own pair or the default, the rule ModelLevels.of follows."""
        return {"max": UsageReserve.MAX_PCT,
                "default": {"stopAt": dict(UsageReserve.NEW_STEP), "switchAt": dict(UsageReserve.NEW_STEP)},
                "set": ModelLevels(self.load()).stored()}

    def state(self):
        """Every pool as the board draws it: its steps, each with the levels
        its subscription's windows have reached now — the proxy's last reading,
        judged by the rule the proxy enforces (caravan/common/usage_reserve.py) —
        and what holds the pool on the kanban."""
        data = self.load()
        sources = CloudSources(data, load_provider_secrets())
        state = self._state() or {}
        readings = state.get("subscriptionUsage") if isinstance(state.get("subscriptionUsage"), dict) else {}
        refs = CloudModelRefs(self.proxies())
        now = self.clock()
        levels = ModelLevels(data)
        out = []
        for pool in self._pools(data).values():
            steps = []
            for step in pool["steps"]:
                if step["kind"] != "account":
                    steps.append(dict(step))
                    continue
                owner = sources.quota_owner(step["accountId"])
                reading = readings.get(owner["id"]) if owner else None
                windows = reading.get("windows") if isinstance(reading, dict) else None
                stop, switch = levels.of(step["accountId"], step["model"])
                reached = {name: UsageReserve(pair).verdict(windows, now) if windows is not None else None
                           for name, pair in (("switchAt", switch), ("stopAt", stop))}
                steps.append({**step, "switchAt": switch, "stopAt": stop, "usageAccountId": owner["id"] if owner else None,
                              "switchReached": reached["switchAt"], "stopReached": reached["stopAt"],
                              "readAt": int(reading["readAt"]) if isinstance(reading, dict) and reading.get("readAt") else None})
            out.append({**pool, "steps": steps, "inUse": refs.in_use(pool["id"]),
                        "held": refs.held(pool["id"]), "switchMax": UsageReserve.MAX_PCT})
        return out
