#!/usr/bin/env python3
"""Snapshot of caravan/admin/board_providers.py: the cloud providers on the main board.

The owner, 2026-10-12: "+ Add cloud provider" puts an empty provider on the
board, and the "+" in its block adds an account to it — the same sign-in may
be added twice; an empty provider is taken off by its ✕, one with accounts is
not. Pinned against the real files in a scratch data directory: which provider
an account stands under (a subscription by its plan, the rest by type), the
list as the file keeps it, what the board is handed, putting a provider there
and taking it off, an account saved putting its provider there, the once-only
move of a file from before, the list riding through every save of the file,
and the two doors as the page calls them.

Run: python3 scripts/test_board_providers.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-board-providers-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
for sub in ("state", "config", "secrets", "logs"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

import caravan.admin.cloud as cloud  # noqa: E402
from caravan.admin.board_providers import BoardProviders, ProviderDesk  # noqa: E402
from caravan.admin.paths import CLOUD_PROVIDERS_FILE  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


SUB = {"id": "sub", "name": "ChatGPT subscription", "type": "openai-subscription", "accountType": "openai-subscription",
       "baseUrl": "https://chatgpt.com/backend-api", "authMode": "oauth"}
# The first subscriptions were made as type `openai`: their plan says what they are.
OLD_SUB = {"id": "old", "name": "Old subscription", "type": "openai", "accountType": "openai-subscription",
           "baseUrl": "https://chatgpt.com/backend-api", "authMode": "oauth"}
KEY = {"id": "or", "name": "OpenRouter", "type": "openrouter", "baseUrl": "https://openrouter.ai/api/v1", "authMode": "apiKey"}


def write_cloud(doc):
    CLOUD_PROVIDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOUD_PROVIDERS_FILE.write_text(json.dumps(doc), encoding="utf-8")


def stored():
    return json.loads(CLOUD_PROVIDERS_FILE.read_text(encoding="utf-8"))


def refused(fn):
    try:
        fn()
        return None
    except AppError as err:
        return err.status


def test_rule():
    print("the provider an account stands under, and the list as the file keeps it:")
    check([BoardProviders.kind(a) for a in (SUB, OLD_SUB, KEY, {"type": "anthropic"}, {"type": ""}, {}, None)]
          == ["openai-subscription", "openai-subscription", "openrouter", "anthropic", "custom", "custom", "custom"],
          "a subscription by its plan — the first ones were made as type openai — the rest by type; "
          "negative: no type is the custom provider, not a guess")
    got = BoardProviders({"boardProviders": [" openrouter ", "openrouter", "", None, "openai-subscription"]})
    check(got.stored() == ["openrouter", "openai-subscription"], f"in the order put there, once each; negative: blanks dropped (got {got.stored()})")
    check([BoardProviders(None).stored(), BoardProviders({"boardProviders": {"a": 1}}).stored()] == [[], []],
          "boundary: no file, a value that is no list — none")
    check((got.add("anthropic"), got.add("anthropic"), got.add(" "), got.remove("openrouter"), got.remove("openrouter"))
          == (True, False, False, True, False) and got.stored() == ["openai-subscription", "anthropic"],
          "added last, once; removed once; negative: a blank adds nothing, one not there removes nothing")
    shown = BoardProviders({"boardProviders": ["anthropic", "openai-subscription"]}).shown([SUB, KEY, OLD_SUB])
    check(shown == [{"kind": "anthropic", "accounts": []}, {"kind": "openai-subscription", "accounts": ["sub", "old"]},
                    {"kind": "openrouter", "accounts": ["or"]}],
          "the board gets each provider with its accounts — an empty one too — and a provider the list lacks after "
          f"them: an account is never left off the board (got {shown})")


def test_desk():
    print("putting a provider on the board and taking it off:")
    write_cloud({"accounts": [dict(SUB)], "pools": [], "migrations": [], "boardProviders": ["openai-subscription"]})
    desk = ProviderDesk()
    got = desk.add("openrouter")
    check(got == [{"kind": "openai-subscription", "accounts": ["sub"]}, {"kind": "openrouter", "accounts": []}]
          and stored()["boardProviders"] == ["openai-subscription", "openrouter"],
          "«＋ Add cloud provider» puts an empty provider last, and the answer is the board's list")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    check(desk.add("openrouter") == got and CLOUD_PROVIDERS_FILE.read_bytes() == before,
          "negative: one already there stays where it is, and nothing is written")
    check(refused(lambda: desk.add("myspace")) == 400 and refused(lambda: desk.add("")) == 400,
          "negative: a provider the controller does not know — 400")
    check(refused(lambda: desk.remove("openai-subscription")) == 409 and "openai-subscription" in stored()["boardProviders"],
          "negative: a provider with an account stays — its ✕ is refused, the account goes first")
    check(desk.remove("openrouter") == [{"kind": "openai-subscription", "accounts": ["sub"]}]
          and stored()["boardProviders"] == ["openai-subscription"], "an empty provider's ✕ takes it off")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    check(desk.remove("openrouter") == [{"kind": "openai-subscription", "accounts": ["sub"]}]
          and CLOUD_PROVIDERS_FILE.read_bytes() == before, "negative: one not on the board — nothing to do, nothing written")

    print("an account saved stands under its provider:")
    write_cloud({"accounts": [], "pools": [], "migrations": [ProviderDesk.MIGRATION]})
    cloud.upsert_cloud_account(dict(KEY))
    cloud.upsert_cloud_account({**SUB, "id": "sub-2", "name": "ChatGPT subscription 2"})
    cloud.upsert_cloud_account({**SUB, "id": "sub-3", "name": "Same sign-in again"})
    check(stored()["boardProviders"] == ["openrouter", "openai-subscription"],
          f"its provider is put on the board when it is missing, once (got {stored().get('boardProviders')})")
    check(ProviderDesk().state() == [{"kind": "openrouter", "accounts": ["or"]},
                                     {"kind": "openai-subscription", "accounts": ["sub-2", "sub-3"]}],
          "a second subscription — the same sign-in may be added twice — stands in the same block")
    ProviderDesk().add("anthropic")
    cloud.upsert_cloud_account({**KEY, "name": "OpenRouter renamed"})
    check(stored()["boardProviders"] == ["openrouter", "openai-subscription", "anthropic"],
          "the list rides through an account's save — a key the save forgot would vanish from the file")
    cloud.delete_cloud_account("or")
    check(stored()["boardProviders"] == ["openrouter", "openai-subscription", "anthropic"]
          and ProviderDesk().state()[0] == {"kind": "openrouter", "accounts": []},
          "an account deleted leaves its provider on the board, empty — the provider's ✕ takes it off")


def test_migration():
    print("a file from before the providers:")
    write_cloud({"accounts": [dict(KEY), dict(OLD_SUB), dict(SUB)], "pools": [], "migrations": ["pools-of-rows-2026-10"]})
    done = ProviderDesk().migrate()
    doc = stored()
    check(done == {"providers": ["openrouter", "openai-subscription"]}
          and doc["boardProviders"] == ["openrouter", "openai-subscription"],
          f"the providers of its accounts are put there once, in the accounts' order (got {done})")
    check(ProviderDesk.MIGRATION in doc["migrations"] and "pools-of-rows-2026-10" in doc["migrations"], "stamped, the others kept")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    check(ProviderDesk().migrate() is None and CLOUD_PROVIDERS_FILE.read_bytes() == before,
          "negative: a second start puts nothing there and writes nothing")
    write_cloud({"accounts": [], "pools": [], "migrations": []})
    check(ProviderDesk().migrate() == {"providers": []} and "boardProviders" not in stored(),
          "boundary: no account — no provider, only the stamp")


def test_doors():
    print("the two doors, as the page calls them:")
    import caravan.admin.routes as routes
    from caravan.admin.topology import topology_state
    write_cloud({"accounts": [dict(SUB)], "pools": [], "migrations": [ProviderDesk.MIGRATION], "boardProviders": ["openai-subscription"]})
    drawn = topology_state(refresh_hosts=False)
    check(drawn["boardProviders"] == [{"kind": "openai-subscription", "accounts": ["sub"]}],
          f"the board is handed its providers with the rest of the topology (got {drawn.get('boardProviders')})")
    sent = []

    class Page:
        def send_json(self, payload, *args, **kwargs):
            sent.append(payload)

    real, routes.topology_state = routes.topology_state, lambda **kw: {"drawn": True}
    try:
        routes.POST_ROUTES["/api/board-providers/add"](Page(), None, {"kind": "anthropic"})
        routes.POST_ROUTES["/api/board-providers/remove"](Page(), None, {"kind": "anthropic"})
        held = refused(lambda: routes.POST_ROUTES["/api/board-providers/remove"](Page(), None, {"kind": "openai-subscription"}))
    finally:
        routes.topology_state = real
    check(sent == [{"ok": True, "providers": [{"kind": "openai-subscription", "accounts": ["sub"]}, {"kind": "anthropic", "accounts": []}],
                    "topology": {"drawn": True}},
                   {"ok": True, "providers": [{"kind": "openai-subscription", "accounts": ["sub"]}], "topology": {"drawn": True}}],
          f"«＋ Add cloud provider» puts it there, its ✕ takes it off; each answers the list and the topology (got {sent})")
    check(held == 409 and len(sent) == 2, "negative: ✕ on a provider with an account is refused at the door, and answers nothing else")


def main():
    for fn in (test_rule, test_desk, test_migration, test_doors):
        fn()
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("board providers OK: провайдер на главной доске — блок своих аккаунтов; пустой — до его ✕")
    return 0


if __name__ == "__main__":
    sys.exit(main())
