"""The stop and switch levels of each subscription model, one pair for every pool.

The owner, 2026-10-12: the limit bars and their levels stand on the models in
the kanban's right column, not in a pool. So a model's levels are the model's
own — `gpt-6.1-sol` of one subscription stops at the same share in every pool
whose row names it. Until 1.3.486 each pool's step kept its own pair
(caravan/common/usage_reserve.py says what the two levels do).

cloud-providers.json keeps them under `levels`, by account and model:
`{"<accountId>": {"<model>": {"stopAt": {"<seconds>": pct}, "switchAt": {…}}}}`.
A model nobody set levels for stops and switches at UsageReserve.NEW_STEP — a
subscription spent to its end before anyone moved a handle is what that default
prevents. Lifted levels are kept as empty maps: "no level" is a choice, and
absence is not.

A file written before 1.3.486 has its levels on the steps. Until the controller
moves them here (caravan/admin/pools.py, PoolDesk.migrate), they speak for their
model — the proxy starts before the controller's migrations run. When two steps
named one model with different levels, the stricter of each wins: a level only
keeps more of a window back, so the stricter one keeps every promise either made.
"""
from caravan.common.usage_reserve import UsageReserve


class ModelLevels:
    """The levels of the models of one reading of the file."""

    KEYS = ("stopAt", "switchAt")

    def __init__(self, data=None):
        data = data if isinstance(data, dict) else {}
        stored = data.get("levels") if isinstance(data.get("levels"), dict) else {}
        self.kept = {}
        for account, models in stored.items():
            if not isinstance(models, dict):
                continue
            for model, entry in models.items():
                if isinstance(entry, dict) and str(account).strip() and str(model).strip():
                    self.kept[(str(account).strip(), str(model).strip())] = self.clean(entry)
        legacy = {}
        for pool in data.get("pools") or []:
            for step in (pool.get("steps") or []) if isinstance(pool, dict) else []:
                if not isinstance(step, dict) or not any(key in step for key in self.KEYS):
                    continue
                key = (str(step.get("accountId") or "").strip(), str(step.get("model") or "").strip())
                if all(key) and key not in self.kept:
                    legacy[key] = self.stricter(legacy[key], self.clean(step)) if key in legacy else self.clean(step)
        self.kept.update(legacy)

    @staticmethod
    def clean(entry):
        """A pair as it is kept: the stop, and the switch never below it. A pair
        written before 1.3.463 had one level, `switchAt`, which stopped the step:
        without a `stopAt` of its own, that level is the stop — and the switch."""
        stop = UsageReserve.normalize(entry["stopAt"] if "stopAt" in entry else entry.get("switchAt"))
        switch = UsageReserve.normalize(entry.get("switchAt"))
        return {"stopAt": stop,
                "switchAt": {key: max(switch.get(key, 0), stop.get(key, 0)) for key in sorted({*switch, *stop}, key=int)}}

    @classmethod
    def stricter(cls, a, b):
        """Of two pairs, each window's higher stop and higher switch."""
        out = {}
        for name in cls.KEYS:
            keys = sorted({*a[name], *b[name]}, key=int)
            out[name] = {key: max(a[name].get(key, 0), b[name].get(key, 0)) for key in keys}
        return cls.clean(out)

    def of(self, account_id, model):
        """The (stop, switch) maps of one model: its own, or NEW_STEP's when unset."""
        entry = self.kept.get((str(account_id or "").strip(), str(model or "").strip()))
        if entry is None:
            return dict(UsageReserve.NEW_STEP), dict(UsageReserve.NEW_STEP)
        return dict(entry["stopAt"]), dict(entry["switchAt"])

    def is_set(self, account_id, model):
        return (str(account_id or "").strip(), str(model or "").strip()) in self.kept

    def put(self, account_id, model, stop, switch):
        """Keep one model's pair, the switch raised to the stop where it is lower."""
        self.kept[(str(account_id).strip(), str(model).strip())] = self.clean({"stopAt": stop, "switchAt": switch})
        return self.of(account_id, model)

    def forget_account(self, account_id):
        self.kept = {key: value for key, value in self.kept.items() if key[0] != str(account_id)}

    def stored(self):
        """The shape the file keeps under `levels`."""
        out = {}
        for (account, model), entry in sorted(self.kept.items()):
            out.setdefault(account, {})[model] = {"stopAt": dict(entry["stopAt"]), "switchAt": dict(entry["switchAt"])}
        return out
