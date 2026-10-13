"""A pool as both readers of cloud-providers.json see it: an ordered list of rows.

The owner, 2026-10-12: a pool is built on the kanban — made empty, a row added
with "+ row", and each row's output cabled to a model in the right column. A row
(kept under `steps`, the name the file has always used) is one of three:

- `account`: an account at a provider with ONE model — a subscription's model,
  or a key provider's; the same account may stand in a pool more than once;
- `output`: a local model — a cell of a machine with a scout (`srv:<port>`) or
  a model of an engine next to the cells (`eng:<id>`), the ids the controller
  gives its local outputs (caravan/admin/proxies_config.py);
- `open`: a row with nothing cabled to it yet, which serves nothing.

The pool takes the first row that is fit now and goes on down the list
(caravan/proxy/pool_steps.py). A subscription model's stop and switch levels are
the model's own, the same in every pool (caravan/common/model_levels.py); until
1.3.486 each step kept its own.

Until 1.3.462 the file kept model blocks and pools of subscriptions. The
controller turns them into pools of steps once (caravan/admin/pools.py); this
module reads the old form the same way meanwhile, because the proxy starts
before the controller's migrations run, and its first request must not depend
on which of the two came first. A model block becomes a pool with the block's
id — the id the kanban's output `cb:<id>` and a port's providerId already
name — and its steps are the members of the subscription pool it belonged to,
each with the block's model, or its one account.
"""
import re

from caravan.common.cloud_sources import CloudSources
from caravan.common.context_window import pool_window


class CloudPools:
    """The pools of one reading of the file, in either form.

    Reading takes any id that is a word: the ids the controller makes are slugs
    (caravan/admin/pools.py), but a reader stricter than the writers ever were
    would lose a pool a port still names."""

    def __init__(self, data, secrets=None):
        self.data = data if isinstance(data, dict) else {}
        self.sources = CloudSources(self.data, secrets)
        #: The steps a file of the old form becomes, as written — with the levels
        #: their accounts kept, which a row does not carry (ModelLevels reads them).
        self.legacy_steps = []
        self.pools = self._read()

    def get(self, pool_id):
        return self.pools.get(str(pool_id or ""))

    def all(self):
        return list(self.pools.values())

    @classmethod
    def legacy(cls, data):
        """Whether the file is in the old form: model blocks, or a pool of members."""
        data = data if isinstance(data, dict) else {}
        return bool(data.get("blocks")) or any(isinstance(p, dict) and "members" in p for p in data.get("pools") or [])

    def _read(self):
        if self.legacy(self.data):
            pools = [self._from_block(b) for b in self.data.get("blocks") or []
                     if isinstance(b, dict) and self._id(b.get("id"))]
        else:
            pools = [self.pool(p) for p in self.data.get("pools") or []]
        return {p["id"]: p for p in pools if p}

    #: A local output a row may name: a cell's, an engine model's or a machine model's id
    #: (`mm:`, 1.3.506), as the controller writes them (proxies_config.sync_router_outputs).
    OUTPUT = re.compile(r"^(srv|eng|mm):[A-Za-z0-9._:-]{1,80}$")

    @classmethod
    def step(cls, raw):
        """One row as it is kept, or None without an id. Its `kind` says what it
        names: an account and a model, a local output, or nothing yet ("open").
        A row naming half of an account and model names nothing it could serve
        from, and reads as open.

        Until 1.3.463 a step could be "manual only" (`automatic: false`): the
        order passed it by, and it served only when the operator picked it by
        hand. The hand pick is gone (the operator, 2026-10-11: a pool always
        goes by the order set), so such a step reads as switched off — what the
        order did with it before — rather than starting to serve unasked. Levels
        a step kept before 1.3.486 are not a row's: ModelLevels reads them."""
        if not isinstance(raw, dict):
            return None
        sid, account, model, output = (str(raw.get(k) or "").strip() for k in ("id", "accountId", "model", "output"))
        if not sid:
            return None
        enabled = bool(raw.get("enabled", True)) and bool(raw.get("automatic", True))
        if account and model:
            return {"id": sid, "kind": "account", "accountId": account, "model": model, "enabled": enabled}
        if cls.OUTPUT.match(output):
            return {"id": sid, "kind": "output", "output": output, "enabled": enabled}
        return {"id": sid, "kind": "open", "enabled": enabled}

    @classmethod
    def pool(cls, raw):
        """One pool as it is kept, or None. Steps that cannot be routed to drop
        out, and so does a second step under an id already taken: the board and
        the proxy name a step by its id.

        A pool kept before 1.3.463 may still carry `mode`, `manualStepId` and
        `manualUntil` — the hand pick the operator dropped on 2026-10-11. They
        are not read: every pool goes by its order, and its next save leaves
        them out."""
        if not isinstance(raw, dict) or not cls._id(raw.get("id")):
            return None
        steps, seen = [], set()
        for item in raw.get("steps") or []:
            step = cls.step(item)
            if step and step["id"] not in seen:
                seen.add(step["id"])
                steps.append(step)
        pid = cls._id(raw["id"])
        out = {"id": pid, "name": str(raw.get("name") or pid).strip() or pid, "steps": steps,
               "contextAuto": bool(raw.get("contextAuto", False))}
        window = cls._positive(raw.get("contextLength"))
        if window:
            out["contextLength"] = window
        return out

    @staticmethod
    def _id(value):
        return str(value or "").strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""

    @staticmethod
    def _positive(value):
        if isinstance(value, bool):
            return None
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @staticmethod
    def step_id(account_id, taken):
        """The id a new step of `account_id` gets in a pool whose step ids are
        `taken`: the account's id, and `-2`, `-3`… when it stands there already."""
        base = str(account_id)[:44]
        sid, number = base, 2
        while sid in taken:
            sid, number = f"{base}-{number}", number + 1
        return sid

    @staticmethod
    def row_id(taken):
        """The id of a row added on the kanban: `r1`, `r2`… — the first one the
        pool does not use. It stays the row's whatever is cabled to it later."""
        number = 1
        while f"r{number}" in taken:
            number += 1
        return f"r{number}"

    def _from_block(self, block):
        """A model block of the old form as the pool it becomes."""
        account_id, model = str(block.get("accountId") or ""), str(block.get("model") or "").strip()
        old = self.sources.pools.get(account_id)
        raw = {"id": self._id(block["id"]), "name": block.get("name") or model or block["id"],
               "contextLength": block.get("contextLength"), "contextAuto": block.get("contextAuto", False)}
        if old is not None and "members" in old:
            raw["steps"] = [self._legacy_step(m.get("accountId"), model, m.get("enabled", True), m.get("automatic", True))
                            for m in old.get("members") or [] if isinstance(m, dict) and m.get("accountId")]
        else:
            raw["steps"] = [self._legacy_step(account_id, model, True, True)]
        self.legacy_steps.extend(raw["steps"])
        return self.pool(raw)

    def _legacy_step(self, account_id, model, enabled, automatic):
        """A member (or a block's own account) of the old form as a step: its
        levels are the reserve its quota owner kept — the levels that closed it
        to the caravan until now, its stop (`levels` above). A member kept out
        of automatic choice comes out switched off (`step` above says why)."""
        source = self.sources.source(account_id) or {}
        return {"id": account_id, "accountId": account_id, "model": model, "switchAt": source.get("usageReserve") or {},
                "enabled": enabled, "automatic": automatic}

    @staticmethod
    def window(pool, catalogue, local=None):
        """The context window a pool stands for, by pool_window's rule
        (caravan/common/context_window.py): the operator's figure, or — when
        they ticked "use the providers' figure" — the smallest window any
        enabled row names, and none when one of them names none: a pool answers
        from whichever row serves, so promising the larger window of the first
        would let a client send more than a later row accepts.
        `catalogue(account_id, model)` is what an account row's provider named;
        `local(output_id)` the window a local row's cell serves, as its router
        output carries it (caravan/common/model_kinds.py, 1.3.502 — before it a
        pool with a cell in it stated none)."""
        pool = pool or {}
        reported = None
        if pool.get("contextAuto"):
            rows = [s for s in pool.get("steps") or [] if s.get("enabled", True) and s.get("kind", "account") != "open"]
            named = [CloudPools._positive(catalogue(s["accountId"], s["model"])) if s.get("kind", "account") == "account"
                     else CloudPools._positive(local(s.get("output"))) if local else None for s in rows]
            reported = min(named) if named and None not in named else None
        return pool_window(pool.get("contextLength"), reported, bool(pool.get("contextAuto")))
