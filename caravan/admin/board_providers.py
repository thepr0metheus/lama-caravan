"""The cloud providers on the main board, each a block of its accounts.

The owner, 2026-10-12: "＋ Add cloud provider" puts an empty provider on the
board — ChatGPT subscriptions, OpenRouter, the OpenAI API… — and the "＋" in
its block adds an account to it: a subscription signed in by code, or a key.
The same sign-in may be added more than once. A provider stays on the board
with no account until its ✕ takes it off; one with accounts cannot be taken
off — they go first. The scouts' machines are not providers.

Which provider an account stands under is one rule, `BoardProviders.kind`: a
ChatGPT subscription — told by its plan, since the first ones were made as
type `openai` — under "openai-subscription", any other account under its type.
The board is handed each provider with its accounts (`state`) and works none
of it out itself.

cloud-providers.json keeps the providers under `boardProviders`, in the order
they were put there: `["openai-subscription", "openrouter"]`. An account saved
puts its provider there when it is missing (caravan/admin/cloud.py). A file
from before 1.3.492 has none: the providers of its accounts are put there once
(ProviderDesk.migrate).
"""
from caravan.common.cloud_sources import CloudSources
from caravan.common.errors import AppError


class BoardProviders:
    """The providers of one reading of the file, and the rule that puts an
    account under one."""

    SUBSCRIPTION = CloudSources.SUBSCRIPTION

    def __init__(self, data=None):
        stored = data.get("boardProviders") if isinstance(data, dict) else None
        self.kinds = []
        for kind in stored if isinstance(stored, list) else ():
            self.add(kind)

    @classmethod
    def kind(cls, account):
        """The provider an account stands under."""
        if CloudSources.is_subscription(account):
            return cls.SUBSCRIPTION
        return str((account or {}).get("type") or "").strip() or "custom"

    def add(self, kind):
        """Put one last. True when it was not there; a blank kind adds nothing."""
        kind = str(kind or "").strip()
        if not kind or kind in self.kinds:
            return False
        self.kinds.append(kind)
        return True

    def remove(self, kind):
        kind = str(kind or "").strip()
        if kind not in self.kinds:
            return False
        self.kinds.remove(kind)
        return True

    def stored(self):
        """The shape the file keeps under `boardProviders`."""
        return list(self.kinds)

    def shown(self, accounts):
        """What the board draws: each provider with the ids of its accounts, in
        the order the providers were put there — then any provider an account
        stands under that the list lacks (a file edited by hand): an account is
        never left off the board."""
        order = list(self.kinds)
        groups = {kind: [] for kind in order}
        for account in accounts:
            kind = self.kind(account)
            if kind not in groups:
                order.append(kind)
                groups[kind] = []
            groups[kind].append(account["id"])
        return [{"kind": kind, "accounts": groups[kind]} for kind in order]


class ProviderDesk:
    """The providers on the controller's file: put one on the board, take an
    empty one off, and the move of a file from before them."""

    #: The providers of the accounts put on the board (1.3.492), stamped once.
    MIGRATION = "board-providers-2026-10"

    def __init__(self, load=None, save=None, presets=None):
        # cloud.py keeps an account's provider on the board as it saves it, so
        # its readers are taken here, not at the top.
        from caravan.admin.cloud import CLOUD_PROVIDER_PRESETS, load_cloud_data, save_cloud_data
        self.load, self.save = load or load_cloud_data, save or save_cloud_data
        self.presets = presets if presets is not None else CLOUD_PROVIDER_PRESETS

    @staticmethod
    def _accounts(data):
        return list(CloudSources(data).accounts.values())

    def state(self, data=None):
        """Every provider on the board with its accounts, as the board draws them."""
        data = self.load() if data is None else data
        return BoardProviders(data).shown(self._accounts(data))

    def add(self, kind):
        """Put a provider on the board, last; one already there stays where it
        is. Only a provider the controller knows — the picker's own list."""
        kind = str(kind or "").strip()
        if kind not in self.presets:
            raise AppError(f"unknown provider: {kind}", 400)
        data = self.load()
        providers = BoardProviders(data)
        if providers.add(kind):
            data["boardProviders"] = providers.stored()
            self.save(data)
        return self.state(data)

    def remove(self, kind):
        """Take a provider off the board while no account stands under it.
        With accounts — refused: each goes first, by Delete in its window. One
        that is not there — nothing to do."""
        kind = str(kind or "").strip()
        data = self.load()
        held = [a for a in self._accounts(data) if BoardProviders.kind(a) == kind]
        if held:
            raise AppError(f"{kind}: {len(held)} account(s) stand under it — delete them first", 409)
        providers = BoardProviders(data)
        if providers.remove(kind):
            data["boardProviders"] = providers.stored()
            self.save(data)
        return self.state(data)

    def migrate(self):
        """Put the providers of the accounts on the board, once (1.3.492): until
        then the board showed each account by itself, and none may vanish.
        Answers {"providers": the kinds put there}, or None when it was done."""
        data = self.load()
        if self.MIGRATION in (data.get("migrations") or []):
            return None
        providers = BoardProviders(data)
        added = [kind for kind in (BoardProviders.kind(a) for a in self._accounts(data)) if providers.add(kind)]
        data["boardProviders"] = providers.stored()
        data["migrations"] = sorted(set(data.get("migrations") or []) | {self.MIGRATION})
        self.save(data)
        return {"providers": added}
