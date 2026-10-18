"""When each model is open — its schedule, the same in every pool whose row names it.

The owner, 2026-10-12 (visumap scheme caravan-model-schedule): a schedule belongs to the model,
not to a pool or a set. A machine's cell holds a card's memory, and one model may stand as a
row in several pools: a schedule kept on the rows would be one fact in many places. A pool
passes over the row of a model that is closed now, as it passes over a cell that is off
(caravan/proxy/pool_steps.py), so the pools keep to the schedules without one of their own.

cloud-providers.json keeps them under `schedules`, by model key (ModelKey):
`{"acc:<account>/<model>" | "out:<output id>": {"enabled": bool, "windows": [...]}}` — the
windows as caravan/common/week_windows.py reads them. A model with no entry has no schedule and
is open whenever its row can serve. A schedule switched off keeps its windows: switched on
again, it has them again. As with a model's levels, a model taken out of Routing keeps its
schedule, and an account deleted takes its models' schedules with it.
"""
from caravan.common.cloud_pools import CloudPools
from caravan.common.week_windows import WeekWindows


class ModelKey:
    """The one name a model has wherever the caravan keeps something of it — the key Routing
    draws its right column with (static/js/pool-board.js, PoolBoard.key): `acc:<account id>/<model>`
    for an account's model, `out:<output id>` for a machine's cell (`srv:<port>`) or an engine's
    model (`eng:<id>`). An account id holds no "/", so the first one splits the two."""

    ACCOUNT = "acc:"
    OUTPUT = "out:"
    #: The local outputs a pool's row may name: the same rule (CloudPools.OUTPUT).
    OUTPUT_ID = CloudPools.OUTPUT

    @classmethod
    def account(cls, account_id, model):
        account_id, model = str(account_id or "").strip(), str(model or "").strip()
        return f"{cls.ACCOUNT}{account_id}/{model}" if account_id and model and "/" not in account_id else ""

    @classmethod
    def output(cls, output_id):
        output_id = str(output_id or "").strip()
        return f"{cls.OUTPUT}{output_id}" if cls.OUTPUT_ID.match(output_id) else ""

    @classmethod
    def of_row(cls, row):
        """The key of the model a pool's row is cabled to; "" for a row with no cable."""
        row = row if isinstance(row, dict) else {}
        kind = row.get("kind", "account")
        if kind == "output":
            return cls.output(row.get("output"))
        if kind == "account":
            return cls.account(row.get("accountId"), row.get("model"))
        return ""

    @classmethod
    def parse(cls, key):
        """("account", account id, model), ("output", output id), or None for no key at all."""
        key = str(key or "")
        if key.startswith(cls.ACCOUNT):
            account_id, _, model = key[len(cls.ACCOUNT):].partition("/")
            return ("account", account_id, model) if cls.account(account_id, model) == key else None
        if key.startswith(cls.OUTPUT):
            output_id = key[len(cls.OUTPUT):]
            return ("output", output_id) if cls.output(output_id) == key else None
        return None


class ModelSchedules:
    """The schedules of the models of one reading of the file."""

    def __init__(self, data=None):
        stored = data.get("schedules") if isinstance(data, dict) else None
        self.kept = {}
        for key, entry in (stored.items() if isinstance(stored, dict) else ()):
            if ModelKey.parse(key) and isinstance(entry, dict):
                self.kept[str(key)] = {"enabled": entry.get("enabled") is True,
                                       "windows": WeekWindows.clean(entry.get("windows"))}

    def of(self, key):
        """The model's schedule as kept, or None when it has none."""
        entry = self.kept.get(str(key or ""))
        return {"enabled": entry["enabled"], "windows": [dict(w) for w in entry["windows"]]} if entry else None

    def put(self, key, enabled, windows):
        self.kept[str(key)] = {"enabled": bool(enabled), "windows": WeekWindows.clean(windows)}
        return self.of(key)

    def forget(self, key):
        return self.kept.pop(str(key or ""), None) is not None

    def forget_account(self, account_id):
        prefix = f"{ModelKey.ACCOUNT}{str(account_id or '').strip()}/"
        self.kept = {key: entry for key, entry in self.kept.items() if not key.startswith(prefix)}

    def follow(self, old_output, new_output):
        """A cell moved to another port takes its schedule along. True when it had one."""
        old, new = ModelKey.output(old_output), ModelKey.output(new_output)
        if not old or not new or old not in self.kept:
            return False
        self.kept[new] = self.kept.pop(old)
        return True

    def swap(self, output_a, output_b):
        """Two cells that swapped ports swap their schedules. True when either had one."""
        a, b = ModelKey.output(output_a), ModelKey.output(output_b)
        if not a or not b or (a not in self.kept and b not in self.kept):
            return False
        held = {a: self.kept.pop(a, None), b: self.kept.pop(b, None)}
        for key, entry in ((b, held[a]), (a, held[b])):
            if entry is not None:
                self.kept[key] = entry
        return True

    def state(self, key, now, zone):
        """The model's schedule and what it says at `now`: `{enabled, windows, open, until,
        opensAt}` — open always while it is switched off — or None when it has none."""
        entry = self.of(key)
        if entry is None:
            return None
        said = WeekWindows(entry["windows"]).state(now, zone) if entry["enabled"] else \
            {"open": True, "until": None, "opensAt": None}
        return {**entry, **said}

    def closed(self, key, now, zone):
        """None while the model may serve — no schedule, one switched off, or a window open now;
        else `{"opensAt": epoch | None}`, when it opens next."""
        said = self.state(key, now, zone)
        if said is None or said["open"]:
            return None
        return {"opensAt": said["opensAt"]}

    def stored(self):
        """The shape the file keeps under `schedules`."""
        return {key: {"enabled": entry["enabled"], "windows": [dict(w) for w in entry["windows"]]}
                for key, entry in sorted(self.kept.items())}
