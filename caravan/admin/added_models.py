"""The models the operator added to Routing's right column, by account.

The owner, 2026-10-12: Routing showed every model a subscription offers —
a dozen nobody meant to use, each with its limit bars — and is to show only
the ones he added. A model is added there with "＋ model" from its account's
list, and leaves by its ✕ while no pool's row names it: a row's cable must
have a model to land on. A model a row is cabled to is added with the cable
(caravan/admin/pools.py), so a cable taken away leaves its model in place.

cloud-providers.json keeps them under `addedModels`, by account, in the order
they were added: `{"<accountId>": ["<model>", …]}`. A file from before 1.3.491
has none: the models its rows name are added once (PoolDesk.migrate_added).
"""


class AddedModels:
    """The added models of one reading of the file."""

    def __init__(self, data=None):
        stored = data.get("addedModels") if isinstance(data, dict) else None
        self.kept = {}
        for account, models in (stored.items() if isinstance(stored, dict) else ()):
            for model in models if isinstance(models, list) else ():
                self.add(account, model)

    @staticmethod
    def _clean(value):
        return str(value or "").strip()

    def of(self, account_id):
        """The account's models in the order they were added; none — an empty list."""
        return list(self.kept.get(self._clean(account_id), []))

    def add(self, account_id, model):
        """Add one at the end. True when it was not there yet; a blank account
        or model adds nothing."""
        account, model = self._clean(account_id), self._clean(model)
        if not account or not model or model in self.kept.get(account, []):
            return False
        self.kept.setdefault(account, []).append(model)
        return True

    def remove(self, account_id, model):
        """True when it was there. An account left with none is not kept."""
        account, model = self._clean(account_id), self._clean(model)
        models = self.kept.get(account, [])
        if model not in models:
            return False
        models.remove(model)
        if not models:
            del self.kept[account]
        return True

    def put_first(self, account_id, models):
        """The account's models with `models` in front, in that order, and the rest after them as they
        were: the order Routing draws them in ("arrange by cables", 1.3.503). A model the account
        has not added is no part of it."""
        account = self._clean(account_id)
        kept = self.kept.get(account, [])
        first = []
        for model in models or ():
            model = self._clean(model)
            if model in kept and model not in first:
                first.append(model)
        if kept:
            self.kept[account] = first + [m for m in kept if m not in first]

    def forget_account(self, account_id):
        self.kept.pop(self._clean(account_id), None)

    def stored(self):
        """The shape the file keeps under `addedModels`."""
        return {account: list(models) for account, models in sorted(self.kept.items())}
