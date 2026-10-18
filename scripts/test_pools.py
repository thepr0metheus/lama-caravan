#!/usr/bin/env python3
"""Snapshot of caravan/admin/pools.py: the pools on the controller's files.

The operator, 2026-10-10: a pool is a chain of steps, each an account with one
model and its own switch levels; another model is another pool. The desk runs
against the real files in a scratch data directory: the one-time rewrite of
the old form (model blocks in a pool of subscriptions — the NAS of 2026-10-10
is pinned as it was), a pool made on the board, its steps added, edited,
reordered and taken out, a step's switch levels, a pool deleted with the
answer it asks for when cables or rules hold it, an account deleted with its
steps, the models added to Routing's right column (the owner, 2026-10-12:
only the ones he added, not every model an account offers), and what the
board is handed. systemd is a stand-in; nothing reaches the machine or a
provider.

Run: python3 scripts/test_pools.py
"""
import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-pools-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
for sub in ("state", "config", "secrets"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

import caravan.admin.cloud as cloud  # noqa: E402
import caravan.admin.proxies_config as pc  # noqa: E402
import caravan.admin.systemd_ctl as sc  # noqa: E402
from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE, CLOUD_PROVIDERS_FILE  # noqa: E402
from caravan.admin.added_models import AddedModels  # noqa: E402
from caravan.admin.pools import PoolDesk  # noqa: E402
from caravan.common.cloud_pools import CloudPools  # noqa: E402
from caravan.common.model_levels import ModelLevels  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


sc.IS_CONTAINER = False
sc.systemctl = lambda *a, **kw: {"ok": True, "stderr": ""}

SUB = {"id": "sub", "name": "ChatGPT subscription", "type": "openai-subscription", "accountType": "openai-subscription",
       "baseUrl": "https://chatgpt.com/backend-api", "authMode": "oauth"}
KEY = {"id": "ant", "name": "Anthropic", "type": "anthropic", "baseUrl": "https://api.anthropic.com/v1", "authMode": "apiKey"}
STATE = TMP / "state" / "proxy-state.json"


class Vault:
    """The credential store as the desk uses it: what it was asked to delete."""

    def __init__(self):
        self.deleted = []

    def read(self):
        return {}

    def delete(self, account_id):
        self.deleted.append(account_id)
        return {"oauth": {"accessToken": "t"}} if account_id == "sub" else None


def desk(vault=None, clock=time.time):
    return PoolDesk(state_file=STATE, vault=vault or Vault(), clock=clock)


def write_cloud(doc):
    CLOUD_PROVIDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOUD_PROVIDERS_FILE.write_text(json.dumps(doc), encoding="utf-8")


def write_proxies(routes=(), routers=None):
    payload = {"routes": [{"port": 23001, "label": "agent", "routerId": "router:default"}, *routes],
               "routers": routers if routers is not None else [copy.deepcopy(ROUTER)]}
    Path(AGENT_PROXY_CONFIG_FILE).write_text(json.dumps(payload))


def cfg():
    return pc.load_agent_proxy_config()


def stored():
    return json.loads(CLOUD_PROVIDERS_FILE.read_text(encoding="utf-8"))


def refused(fn):
    try:
        fn()
        return None
    except AppError as err:
        return err.status


ROUTER = {
    "id": "router:default", "name": "Default",
    "outputs": [{"id": "srv:22011", "label": "cell", "upstreamHost": "10.0.0.5", "upstreamPort": 22011, "upstreamType": "llama"},
                {"id": "cb:sol", "label": "☁ sol", "target": "pool:sol", "upstreamHost": "", "upstreamPort": 0,
                 "upstreamType": "cloud", "providerId": "sol"},
                {"id": "cb:luna", "label": "☁ luna", "target": "pool:luna", "upstreamHost": "", "upstreamPort": 0,
                 "upstreamType": "cloud", "providerId": "luna"}],
    "rules": {"default": "cb:sol", "schedule": [], "bySource": [], "failover": []},
    "graph": {"nodes": [{"id": "q", "type": "queue", "config": {"admitEdge": "e0", "spillEdge": "e1"}}],
              "edges": [{"id": "e0", "from": "rule:q", "to": "out:srv:22011"},
                        {"id": "e1", "from": "rule:q", "to": "out:cb:sol"},
                        {"id": "e2", "from": "in:skynet:proxy:23001", "to": "out:cb:sol"}]},
}


def new_form():
    write_cloud({"accounts": [dict(SUB), dict(KEY)], "migrations": [], "pools": [
        {"id": "sol", "name": "gpt-6-sol", "steps": [
            {"id": "sub", "accountId": "sub", "model": "gpt-6-sol", "switchAt": {"18000": 10, "604800": 10}}]},
        {"id": "luna", "name": "gpt-5.6-luna", "steps": [
            {"id": "sub", "accountId": "sub", "model": "gpt-5.6-luna", "switchAt": {"18000": 10, "604800": 10}}]}]})
    write_proxies()


def test_migration_of_the_nas():
    print("the old form, as the NAS kept it on 2026-10-10:")
    models = ["gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]
    ids = [m.replace(".", "-") for m in models]
    write_cloud({"accounts": [{**SUB, "id": "chatgpt-subscription", "usageReserve": {"18000": 10, "604800": 10}}],
                 "pools": [{"id": "openai-pool", "name": "OpenAI pool", "mode": "auto", "manualAccountId": "",
                            "manualUntil": 0, "returnToPrimary": False,
                            "members": [{"accountId": "chatgpt-subscription", "enabled": True, "automatic": True}]}],
                 "blocks": [{"id": i, "accountId": "openai-pool", "name": m, "model": m, "modelMode": "rewrite",
                             "contextAuto": True, "exposed": True, "usageOriginAccountId": "chatgpt-subscription"}
                            for i, m in zip(ids, models)],
                 "deletedModels": {"openai-pool": ["gpt-6-astra-old"]},
                 "migrations": ["contextAuto-2026-09"]})
    rescue = {"id": "router:default", "outputs": [{"id": f"cb:{i}", "upstreamType": "cloud", "providerId": i} for i in ids],
              "rules": {"default": "cb:gpt-6-1-sol"},
              "graph": {"nodes": [{"id": "n1", "type": "onError", "config": {"mainEdge": "a", "rescueEdge": "b"}}],
                        "edges": [{"id": "a", "from": "rule:n1", "to": "out:cb:gpt-6-1-sol"},
                                  {"id": "b", "from": "rule:n1", "to": "out:cb:gpt-5-6-luna"}]}}
    Path(AGENT_PROXY_CONFIG_FILE).write_text(json.dumps({"routes": [], "routers": [rescue]}))
    routers_before = Path(AGENT_PROXY_CONFIG_FILE).read_bytes()
    done = desk().migrate()
    doc = stored()
    check(done == {"pools": ids, "dropped": []}, f"seven models became seven pools, none dropped (got {done})")
    check([(p["id"], p["name"]) for p in doc["pools"]] == list(zip(ids, models)),
          "each pool has its model block's id — Routing's cb:<id> — and its model's name, in order")
    check(all(p["steps"] == [{"id": "chatgpt-subscription", "kind": "account", "accountId": "chatgpt-subscription",
                              "model": m, "enabled": True}]
              for p, m in zip(doc["pools"], models)),
          "one row each: the subscription with that model")
    check(doc["levels"] == {"chatgpt-subscription": {m: {"stopAt": {"18000": 10, "604800": 10},
                                                         "switchAt": {"18000": 10, "604800": 10}} for m in models}},
          f"the 10% the account kept is each model's stop and switch since 1.3.486 (got {doc.get('levels')})")
    check(all(sorted(p) == ["contextAuto", "id", "name", "steps"] and p["contextAuto"] is True for p in doc["pools"]),
          "no mode — a pool goes by its order — and the providers' window as before")
    check(sorted(doc) == ["accounts", "levels", "migrations", "pools"] and "usageReserve" not in doc["accounts"][0],
          "the blocks, the deleted models and the account's reserve are gone from the file")
    check(doc["migrations"] == ["contextAuto-2026-09", "pools-of-rows-2026-10", "pools-of-steps-2026-10"],
          "the rewrite is stamped — and the move of levels onto models with it")
    check(Path(AGENT_PROXY_CONFIG_FILE).read_bytes() == routers_before, "the 🛟 node's cables are not touched")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    check(desk().migrate() is None and CLOUD_PROVIDERS_FILE.read_bytes() == before,
          "negative: a second start finds nothing to rewrite and writes nothing")


def test_migration_keeps_what_is_used():
    print("the old form — which model blocks become pools:")
    write_cloud({"accounts": [dict(SUB, usageReserve={"18000": 30}), dict(KEY)],
                 "pools": [{"id": "p", "name": "P", "mode": "manual", "manualAccountId": "sub", "manualUntil": 99,
                            "members": [{"accountId": "sub", "enabled": True, "automatic": False}]}],
                 "blocks": [{"id": "shown", "accountId": "p", "model": "a", "exposed": True},
                            {"id": "ported", "accountId": "ant", "model": "b"},
                            {"id": "cabled", "accountId": "ant", "model": "c"},
                            {"id": "idle", "accountId": "ant", "model": "d"}]})
    router = {"id": "router:default", "outputs": [{"id": "cb:cabled", "upstreamType": "cloud", "providerId": "cabled"}],
              "graph": {"edges": [{"id": "x", "from": "in:skynet:proxy:23001", "to": "out:cb:cabled"}]}}
    write_proxies(routes=[{"port": 23050, "label": "app", "kind": "service", "upstreamType": "cloud", "providerId": "ported"}], routers=[router])
    done = desk().migrate()
    pools = {p["id"]: p for p in stored()["pools"]}
    check(done == {"pools": ["shown", "cabled"], "dropped": ["ported", "idle"]},
          "in Routing or with a cable — kept; a copy of a list nobody uses — dropped; negative: a block held "
          f"only by a pool's own port is dropped too — that port is gone since 1.3.487 (got {done})")
    levels = stored()["levels"]
    check(not {"mode", "manualStepId", "manualUntil"} & set(pools["shown"])
          and pools["shown"]["steps"] == [{"id": "sub", "kind": "account", "accountId": "sub", "model": "a", "enabled": False}]
          and levels["sub"]["a"] == {"stopAt": {"18000": 30}, "switchAt": {"18000": 30}},
          "the old pool's hand pick is not carried; its manual-only member comes out switched off, its level its model's")
    check(pools["cabled"]["steps"] == [{"id": "ant", "kind": "account", "accountId": "ant", "model": "c", "enabled": True}],
          "an account's block is a pool of its one account")
    check("d" not in levels.get("ant", {}), "negative: a dropped block's model keeps no levels")


def test_create_and_steps():
    print("a pool made on the board, and its steps:")
    new_form()
    made = desk().create("Smart one", "sub", "gpt-6-sol")
    check(made["id"] == "Smart-one" and made["name"] == "Smart one" and made["contextAuto"] is True,
          f"the id comes from the name (got {made['id']})")
    check(made["steps"] == [{"id": "sub", "kind": "account", "accountId": "sub", "model": "gpt-6-sol", "enabled": True}],
          "a pool made with a model starts with that row")
    check(ModelLevels(stored()).of("sub", "gpt-6-sol") == ({"18000": 10, "604800": 10}, {"18000": 10, "604800": 10})
          and "levels" not in stored(),
          "its model stops — and switches — at 10% of each window: nothing is written for a new row")
    check(sorted(made) == ["contextAuto", "id", "name", "steps"], "a new pool has no mode: it goes by its order")
    again = desk().create("", "ant", "claude-opus")
    check((again["id"], again["name"]) == ("claude-opus", "claude-opus")
          and not {"switchAt", "stopAt"} & set(again["steps"][0]),
          "no name — the model's; a row keeps no levels of its own")
    check(desk().create("Smart-one", "ant", "x")["id"] == "Smart-one-2", "a taken id gets a number")
    # A consumer of the entry calls a pool by its name (caravan/common/entry_models.py).
    check(refused(lambda: desk().create("Smart one", "ant", "x")) == 409
          and refused(lambda: desk().create("  smart ONE ", "ant", "x")) == 409,
          "negative: a name another pool carries is refused, whatever its case and spaces")
    check(desk().create("", "ant", "claude-opus")["name"] == "claude-opus 2",
          "no name, and the model's name is taken — the board's own default gets a number, not a refusal")
    check(refused(lambda: desk().create("x", "nobody", "m")) == 404 and refused(lambda: desk().create("x", "sub", " ")) == 400,
          "negative: an unknown account is 404, an account without a model 400")
    empty = desk().create()
    check((empty["id"], empty["name"], empty["steps"]) == ("Pool", "Pool", []),
          f"«+ Pool»: an empty pool, named Pool (got {empty})")
    check(desk().create()["name"] == "Pool 2", "the next empty one is Pool 2")
    pool = desk().add_step("Smart-one", "sub", "gpt-5.6-luna")
    check([s["id"] for s in pool["steps"]] == ["sub", "sub-2"] and pool["steps"][1]["model"] == "gpt-5.6-luna",
          "the same subscription again: a step of its own, under the account's id with -2")
    pool = desk().add_step("Smart-one", "ant", "claude-opus")
    check([s["id"] for s in pool["steps"]] == ["sub", "sub-2", "ant"], "a step is added at the end")
    check(refused(lambda: desk().add_step("nope", "sub", "m")) == 404, "negative: no such pool — 404")
    on_disk = [p for p in stored()["pools"] if p["id"] == "Smart-one"][0]
    check([s["id"] for s in on_disk["steps"]] == ["sub", "sub-2", "ant"], "and it is on disk")


def test_save_pool():
    print("an edit of a pool, sent whole by the board:")
    new_form()
    desk().add_step("sol", "ant", "claude-opus")
    saved = desk().save_pool({"id": "sol", "name": "  Main  ", "steps": [
        {"id": "ant", "enabled": False}, {"id": "sub", "switchAt": {"18000": 50}, "model": "gpt-6.1-sol"}]})
    check([s["id"] for s in saved["steps"]] == ["ant", "sub"] and saved["name"] == "Main",
          "the order is the board's; the name is trimmed")
    check(saved["steps"][0]["enabled"] is False and saved["steps"][0]["model"] == "claude-opus"
          and saved["steps"][1]["model"] == "gpt-6.1-sol",
          "a row keeps what the edit does not send, and takes what it does")
    check(not {"switchAt", "stopAt"} & set(saved["steps"][1])
          and ModelLevels(stored()).of("sub", "gpt-6.1-sol") == ({"18000": 10, "604800": 10}, {"18000": 10, "604800": 10}),
          "negative: a level sent with a row is not kept — levels are the model's (set_level)")
    check(desk().save_pool({"id": "sol", "name": ""})["name"] == "Main", "negative: an empty name keeps the stored one")
    check(desk().save_pool({"id": "sol", "name": "MAIN"})["name"] == "MAIN", "the pool's own name in another case is its own")
    desk().create("Spare", "ant", "claude-opus")
    check(refused(lambda: desk().save_pool({"id": "sol", "name": "spare"})) == 409,
          "negative: renaming to a name another pool carries is refused")
    desk().save_pool({"id": "sol", "name": "Main"})
    check(len(desk().save_pool({"id": "sol", "name": "x" * 200})["name"]) == 80, "a name is cut to 80 characters")
    for bad, why in (({"steps": [{"id": "nope"}]}, "a step the pool does not have"),
                     ({"steps": [{"id": "sub"}, {"id": "sub"}]}, "the same step twice"),
                     ({"steps": [{"id": "sub", "model": ""}]}, "a step without a model"),
                     ({"steps": [{"id": "sub", "accountId": "nobody"}]}, "a step of an unknown account")):
        status = refused(lambda: desk().save_pool({"id": "sol", **bad}))
        check(status in (400, 404), f"negative: {why} is refused (got {status})")
    # A page opened before 1.3.463 still sends the hand pick and the "manual only" flag.
    old_page = desk().save_pool({"id": "sol", "mode": "manual", "manualStepId": "ant", "manualUntil": 77,
                                 "steps": [{"id": "ant", "enabled": True, "automatic": False}, {"id": "sub", "automatic": True}]})
    kept = [p for p in stored()["pools"] if p["id"] == "sol"][0]
    check(not {"mode", "manualStepId", "manualUntil"} & (set(old_page) | set(kept)),
          "an old page's hand pick is not kept, in the answer or on disk")
    check([(s["id"], s["enabled"]) for s in kept["steps"]] == [("ant", False), ("sub", True)]
          and all("automatic" not in s for s in kept["steps"]),
          "its manual-only step is kept switched off; a step in the order stays on")
    for gone in ({"mode": "fast"}, {"manualUntil": "soon"}, {"manualStepId": "nope"}):
        check(refused(lambda: desk().save_pool({"id": "sol", **gone})) is None,
              f"negative: a field the pool no longer has is not an error ({sorted(gone)[0]})")
    check(refused(lambda: desk().save_pool({"id": "nope"})) == 404, "negative: no such pool — 404")


def test_remove_step():
    print("a step taken out:")
    new_form()
    desk().add_step("sol", "ant", "claude-opus")
    pool = desk().remove_step("sol", "ant")
    check([s["id"] for s in pool["steps"]] == ["sub"], "it leaves; the other step stays")
    check(any(a["id"] == "ant" for a in stored()["accounts"]), "its account stays connected")
    pool = desk().remove_step("sol", "sub")
    check(pool["steps"] == [], "the last one too: a pool may wait with no step")
    check(refused(lambda: desk().remove_step("sol", "sub")) == 404, "negative: a step it no longer has — 404")


def test_levels():
    print("a subscription model's two levels on a window (the owner, 2026-10-12: on the model, not the pool):")
    new_form()
    desk().migrate_rows()
    got = desk().set_level("sub", "gpt-6-sol", 18000, 35, "switch")
    check(got == {"switchAt": {"18000": 35, "604800": 10}, "stopAt": {"18000": 10, "604800": 10}},
          f"the five-hour switch moves to 35%; the stop stays at the 10% its step kept (got {got})")
    got = desk().set_level("sub", "gpt-6-sol", 18000, 50, "stop")
    check(got == {"switchAt": {"18000": 50, "604800": 10}, "stopAt": {"18000": 50, "604800": 10}},
          f"a stop raised past the switch takes it along (got {got})")
    got = desk().set_level("sub", "gpt-6-sol", 18000, 5, "stop")
    check((got["stopAt"]["18000"], got["switchAt"]["18000"]) == (5, 50),
          "the stop lowered again leaves the switch where it was taken")
    got = desk().set_level("sub", "gpt-6-sol", 18000, 2, "switch")
    check(got["switchAt"]["18000"] == 5, f"a switch lowered past the stop rests on it (got {got})")
    got = desk().set_level("sub", "gpt-6-sol", "604800", "0", "stop")
    check(got == {"switchAt": {"18000": 5, "604800": 10}, "stopAt": {"18000": 5}},
          f"0 lifts the weekly stop; the weekly switch stays (got {got})")
    check(stored()["levels"]["sub"]["gpt-6-sol"] == {"stopAt": {"18000": 5}, "switchAt": {"18000": 5, "604800": 10}},
          "and both are on disk, under the model")
    desk().add_step("luna", "sub", "gpt-6-sol")
    check(desk().state()[1]["steps"][1]["stopAt"] == {"18000": 5},
          "the same model in another pool stops where the model does: one pair for every pool")
    check(ModelLevels(stored()).of("sub", "gpt-5.6-luna") == ({"18000": 10, "604800": 10}, {"18000": 10, "604800": 10}),
          "negative: another model of the subscription keeps its own levels")
    desk().add_step("sol", "ant", "claude-opus")
    check(refused(lambda: desk().set_level("ant", "claude-opus", 18000, 20, "stop")) == 400,
          "negative: a key's model has no windows — 400")
    check(refused(lambda: desk().set_level("sub", "gpt-6-sol", 18000, 20, "fast")) == 400
          and refused(lambda: desk().set_level("sub", "gpt-6-sol", 18000, 20, None)) == 400,
          "negative: a level that is neither switch nor stop — 400")
    check(refused(lambda: desk().set_level("sub", "gpt-6-sol", 18000, 95, "switch")) == 400
          and refused(lambda: desk().set_level("sub", "gpt-6-sol", 0, 5, "stop")) == 400
          and refused(lambda: desk().set_level("sub", "gpt-6-sol", "x", 5, "stop")) == 400,
          "negative: out of range or no number — 400")
    check(refused(lambda: desk().set_level("nobody", "m", 18000, 5, "stop")) == 404
          and refused(lambda: desk().set_level("sub", " ", 18000, 5, "stop")) == 400,
          "negative: an unknown account — 404, no model — 400")
    check(desk().row_target("sol", "sub") == ("sub", "gpt-6-sol"),
          "a page from before 1.3.486 names the model by its pool and row")
    check(refused(lambda: desk().row_target("sol", "nope")) == 404, "negative: no such row — 404")
    shown = desk().model_levels()
    check(shown == {"max": 90, "default": {"stopAt": {"18000": 10, "604800": 10}, "switchAt": {"18000": 10, "604800": 10}},
                    "set": stored()["levels"]},
          f"Routing's right column reads every model's levels: the ones set, the default of the rest, the ceiling (got {shown})")
    check("gpt-6-astra" not in shown["set"].get("sub", {}) and ModelLevels(stored()).of("sub", "gpt-6-astra")[0] == shown["default"]["stopAt"],
          "negative: a model nobody set is not in `set` — it reads the default, said once, the pair ModelLevels gives it")


def test_rows():
    print("rows in Routing (the owner, 2026-10-12): «+ row», a cable to a model, the cable taken away:")
    new_form()
    pool = desk().add_row("sol")
    check(pool["steps"][1] == {"id": "r1", "kind": "open", "enabled": True}, f"«+ row» adds an open row (got {pool['steps'][1]})")
    pool = desk().add_row("sol", {"output": "srv:22008"})
    check(pool["steps"][2] == {"id": "r2", "kind": "output", "output": "srv:22008", "enabled": True},
          "a row cabled at once to a local cell")
    pool = desk().connect_row("sol", "r1", {"accountId": "sub", "model": "gpt-5.6-luna"})
    check(pool["steps"][1] == {"id": "r1", "kind": "account", "accountId": "sub", "model": "gpt-5.6-luna", "enabled": True},
          "the open row cabled to a subscription's model keeps its id and its place")
    pool = desk().connect_row("sol", "r2", {"output": "eng:abc123def456"})
    check(pool["steps"][2]["output"] == "eng:abc123def456", "a cable moved to an engine's model")
    pool = desk().connect_row("sol", "r1", None)
    check(pool["steps"][1] == {"id": "r1", "kind": "open", "enabled": True},
          "the cable taken away: the row stays, open, in its place")
    check([s["id"] for s in stored()["pools"][0]["steps"]] == ["sub", "r1", "r2"], "and it is on disk in that order")
    for bad, status, why in ((("sol", "r1", {"output": "http://x"}), 400, "an output that is no local model's"),
                             (("sol", "r1", {"accountId": "sub"}), 400, "an account without a model"),
                             (("sol", "r1", {"accountId": "nobody", "model": "m"}), 404, "an unknown account"),
                             (("sol", "nope", None), 404, "a row the pool does not have"),
                             (("nope", "r1", None), 404, "a pool that does not exist"),
                             (("sol", "r1", "srv:22008"), 400, "a target that is not an object")):
        check(refused(lambda: desk().connect_row(*bad)) == status, f"negative: {why} — {status}")
    pool = desk().save_pool({"id": "sol", "steps": [{"id": "r2"}, {"id": "sub"}, {"id": "r1", "enabled": False}]})
    check([(s["id"], s["kind"], s["enabled"]) for s in pool["steps"]] == [("r2", "output", True), ("sub", "account", True),
                                                                         ("r1", "open", False)],
          "the order changes by save; a local row keeps its cable, an open row may be switched off")
    check(desk().add_row("sol")["steps"][-1]["id"] == "r3", "the next row's id is the first free one")


def test_named_after_its_model():
    print("a pool named after its model (1.3.503; the owner, 2026-10-12: a pool of one model is named after it):")
    new_form()
    check([PoolDesk.default_named(n) for n in ("Pool", "Pool 2", "Pool 12", "pool", "Pool x", "My Pool", "Pool 2 b", "", None)]
          == [True, True, True, False, False, False, False, False, False],
          "the board's names are Pool and Pool N; negative: another case, another word, nothing — the operator's or none")
    made = desk().create(target={"output": "srv:22011"}, name_after="Coder")
    check((made["id"], made["name"], made["steps"]) == ("Coder", "Coder", [{"id": "r1", "kind": "output", "output": "srv:22011", "enabled": True}]),
          f"a model carried onto Pools: a pool of it, named by the board's word for it (got {made})")
    again = desk().create(target={"accountId": "sub", "model": "gpt-6-sol"}, name_after="gpt-6-sol")
    check((again["name"], [s["model"] for s in again["steps"]]) == ("gpt-6-sol 2", ["gpt-6-sol"]),
          "the name taken by another pool — the board's word gets a number, not a refusal")
    check(desk().create(target={"accountId": "sub", "model": "gpt-9"})["name"] == "gpt-9"
          and desk().create("Typed", target={"output": "srv:22012"}, name_after="Other")["name"] == "Typed",
          "no word — the account's model id; a name typed by the operator wins over the board's word")
    check(refused(lambda: desk().create(target={"output": "http://x"}, name_after="x")) == 400
          and refused(lambda: desk().create(target="srv:22011")) == 400,
          "negative: a target that is no local model, or no object — 400")
    fresh = desk().create()
    named = desk().add_row(fresh["id"], {"output": "srv:22013"}, "Coder")
    check((named["id"], named["name"]) == (fresh["id"], "Coder 2"),
          f"a pool under the board's name takes its first cable's model as its name, its id kept (got {named['name']})")
    kept = desk().add_row(fresh["id"], {"output": "srv:22014"}, "Other")
    check(kept["name"] == "Coder 2", "negative: a second cable renames nothing")
    mine = desk().create("Mine")
    check(desk().add_row(mine["id"], {"output": "srv:22015"}, "Coder")["name"] == "Mine",
          "negative: a name the operator gave is never taken over")
    empty = desk().create()
    opened = desk().add_row(empty["id"], None, "Ghost")
    check(opened["name"] == empty["name"], "negative: an open row is no cable — the name waits")
    cabled = desk().connect_row(empty["id"], "r1", {"accountId": "sub", "model": "gpt-5.6-luna"}, "gpt-5.6-luna")
    check(cabled["name"] == "gpt-5.6-luna 2", f"a cable drawn from that open row names the pool (got {cabled['name']})")
    check(desk().connect_row(empty["id"], "r1", {"output": "srv:22016"}, "Cell")["name"] == "gpt-5.6-luna 2",
          "negative: a cable moved later renames nothing")
    old = desk().create()
    desk().add_row(old["id"], {"output": "srv:22017"})
    check(desk().add_row(old["id"], {"output": "srv:22018"}, "Late")["name"] == old["name"],
          "negative: a row was cabled before — clients may call the pool by the board's name already; a later cable renames nothing")
    other = desk().create()
    check(desk().add_row(other["id"], {"output": "srv:22019"}, "")["name"] == other["name"],
          "negative: no word for the model — the name stays the board's")


def test_order_and_arrange():
    print("the pools' order in Routing, and «Arrange» by the cables (1.3.503):")
    new_form()
    doc = stored()
    doc["pools"].append({"id": "extra", "name": "Extra", "steps": [{"id": "ant", "accountId": "ant", "model": "claude-opus"}]})
    doc["sets"] = [{"id": "chat", "name": "Chat", "pools": ["luna", "ghost"]}, {"id": "all", "name": "All", "pools": ["sol", "luna"]}]
    doc["addedModels"] = {"sub": ["gpt-6-sol", "gpt-9", "gpt-5.6-luna"], "ant": ["claude-opus"]}
    write_cloud(doc)
    check(desk().order(["extra", "sol", "luna"]) == ["extra", "sol", "luna"] and [p["id"] for p in stored()["pools"]] == ["extra", "sol", "luna"],
          "a carried card's order is the file's order of the pools")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    for bad, why in ((["sol", "luna"], "a pool left out"), (["sol", "luna", "extra", "new"], "a pool the file has not"),
                     (["sol", "sol", "luna", "extra"], "a pool twice"), ("sol", "not a list"), (None, "nothing")):
        check(refused(lambda: desk().order(bad)) == 409, f"negative: {why} — 409, draw the board again")
    check(CLOUD_PROVIDERS_FILE.read_bytes() == before, "and a refused order writes nothing")
    order = desk().arrange()
    doc = stored()
    check(order == ["luna", "sol", "extra"] and [p["id"] for p in doc["pools"]] == ["luna", "sol", "extra"],
          f"«Arrange»: the pools in the order the sets name them, then the rest as they stood; a pool no more there is skipped (got {order})")
    check(doc["addedModels"] == {"sub": ["gpt-5.6-luna", "gpt-6-sol", "gpt-9"], "ant": ["claude-opus"]},
          f"each account's models in the order the arranged pools' rows name them, then the rest (got {doc['addedModels']})")
    check([s["pools"] for s in doc["sets"]] == [["luna", "ghost"], ["sol", "luna"]], "negative: the sets are not touched")
    added = AddedModels({"addedModels": {"sub": ["a", "b", "c"]}})
    added.put_first("sub", ["c", "x", " a ", "c"])
    added.put_first("nobody", ["a"])
    check(added.stored() == {"sub": ["c", "a", "b"]},
          "put first: the named ones in front once each, the rest after as they were; negative: a model not added, an account without models — nothing")


def test_order_doors():
    print("the doors of the order, as the page calls them:")
    import caravan.admin.routes as routes_mod
    new_form()
    sent = []

    class Page:
        def send_json(self, payload, *args, **kwargs):
            sent.append(payload)

    real, routes_mod.topology_state = routes_mod.topology_state, lambda **kw: {"drawn": True}
    try:
        post = routes_mod.POST_ROUTES
        post["/api/pools/order"](Page(), None, {"ids": ["luna", "sol"]})
        post["/api/pools/arrange"](Page(), None, {})
        post["/api/pools/create"](Page(), None, {"target": {"output": "srv:22011"}, "nameAfter": "Coder"})
        post["/api/pools/add-row"](Page(), None, {"poolId": "Coder", "target": {"output": "srv:22012"}, "nameAfter": "Other"})
        try:
            post["/api/pools/order"](Page(), None, {"ids": ["sol"]})
            status = None
        except AppError as err:
            status = err.status
    finally:
        routes_mod.topology_state = real
    check([s.get("order") or s.get("pool", {}).get("name") for s in sent] == [["luna", "sol"], ["luna", "sol"], "Coder", "Coder"]
          and all(s.get("topology") == {"drawn": True} for s in sent),
          f"order, arrange, a pool made of a model and a row added to it — each answers the board (got {sent})")
    check(status == 409, "negative: an order of pools that are not all there — 409")


def test_migrate_rows():
    print("the levels the steps kept move onto their models, once (1.3.486):")
    write_cloud({"accounts": [dict(SUB), dict(KEY)], "migrations": ["pools-of-steps-2026-10"], "pools": [
        {"id": "a", "name": "A", "steps": [
            {"id": "sub", "accountId": "sub", "model": "sol", "switchAt": {"18000": 40}, "stopAt": {"18000": 20}},
            {"id": "ant", "accountId": "ant", "model": "opus"}]},
        {"id": "b", "name": "B", "steps": [
            {"id": "sub", "accountId": "sub", "model": "sol", "switchAt": {"18000": 30, "604800": 50}, "stopAt": {"18000": 25}},
            {"id": "sub-2", "accountId": "sub", "model": "luna", "switchAt": {}, "stopAt": {}}]}]})
    write_proxies()
    done = desk().migrate_rows()
    doc = stored()
    check(done == {"models": 2, "steps": 3}, f"three steps' levels became two models' (got {done})")
    check(doc["levels"]["sub"]["sol"] == {"stopAt": {"18000": 25}, "switchAt": {"18000": 40, "604800": 50}},
          f"a model two steps named keeps the stricter of each level (got {doc['levels']['sub']['sol']})")
    check(doc["levels"]["sub"]["luna"] == {"stopAt": {}, "switchAt": {}},
          "lifted levels stay lifted: a choice, not absence")
    check(all(not {"switchAt", "stopAt"} & set(s) for p in doc["pools"] for s in p["steps"]),
          "no step keeps a level of its own")
    check("opus" not in doc["levels"].get("ant", {}), "negative: a step that kept no levels writes none")
    check("pools-of-rows-2026-10" in doc["migrations"], "stamped")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    check(desk().migrate_rows() is None and CLOUD_PROVIDERS_FILE.read_bytes() == before,
          "negative: a second start moves nothing and writes nothing")


def test_added_models_rule():
    print("the models added to Routing's column, as the file keeps them:")
    got = AddedModels({"addedModels": {"sub": [" sol ", "luna", "sol", "", None], " ": ["x"], "ant": "opus", "key": []}})
    check(got.stored() == {"sub": ["sol", "luna"]},
          f"by account, in the order added, once each; negative: a blank account, a blank model, a list that is no list, "
          f"an empty list — none kept (got {got.stored()})")
    check([AddedModels(None).stored(), AddedModels({"addedModels": ["sol"]}).stored(), AddedModels({}).of("sub")] == [{}, {}, []],
          "boundary: no file, a value that is no map, no account — nothing, not a failure")
    check((got.add("sub", "terra"), got.add("sub", " terra "), got.add("", "m"), got.add("sub", " ")) == (True, False, False, False)
          and got.of("sub") == ["sol", "luna", "terra"],
          "added last; negative: one already there, a blank account or model adds nothing")
    check((got.remove("sub", "luna"), got.remove("sub", "luna"), got.remove("nobody", "sol")) == (True, False, False)
          and got.of("sub") == ["sol", "terra"], "removed once; negative: one not there — nothing")
    got.remove("sub", "sol")
    got.remove("sub", "terra")
    check("sub" not in got.stored(), "an account left with none is not kept")
    got.add("a", "m")
    got.add("b", "m")
    got.forget_account("a")
    check(got.stored() == {"b": ["m"]}, "an account forgotten takes its list; the others stay")


def test_added_models():
    print("Routing's right column holds the models added to it (the owner, 2026-10-12):")
    new_form()
    done = desk().migrate_added()
    doc = stored()
    check(done == {"models": 2} and doc["addedModels"] == {"sub": ["gpt-6-sol", "gpt-5.6-luna"]},
          f"once: the models the rows name are added, in the pools' order — none in use leaves the column (got {done}, {doc.get('addedModels')})")
    check("added-models-2026-10" in doc["migrations"], "stamped")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    check(desk().migrate_added() is None and CLOUD_PROVIDERS_FILE.read_bytes() == before,
          "negative: a second start adds nothing and writes nothing")
    write_cloud({"accounts": [dict(SUB)], "blocks": [{"id": "sol", "accountId": "sub", "model": "gpt-6-sol"}]})
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    check(desk().migrate_added() is None and CLOUD_PROVIDERS_FILE.read_bytes() == before,
          "negative: a file of the old form waits — its pools do not exist yet")

    new_form()
    desk().migrate_added()
    check(desk().add_model("sub", "gpt-6.1-terra") == ["gpt-6-sol", "gpt-5.6-luna", "gpt-6.1-terra"],
          "«＋ model» puts it last, and the answer is the account's list")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    check(desk().add_model("sub", " gpt-6-sol ") == ["gpt-6-sol", "gpt-5.6-luna", "gpt-6.1-terra"]
          and CLOUD_PROVIDERS_FILE.read_bytes() == before,
          "negative: one already there stays where it is, and nothing is written")
    check(desk().add_model("ant", "claude-typed-by-hand") == ["claude-typed-by-hand"],
          "any id is taken, a typed one too: a list lags behind its provider")
    check(refused(lambda: desk().add_model("nobody", "m")) == 404 and refused(lambda: desk().add_model("sub", "  ")) == 400,
          "negative: an unknown account is 404, a blank model 400")

    check(refused(lambda: desk().remove_model("sub", "gpt-6-sol")) == 409
          and "gpt-6-sol" in stored()["addedModels"]["sub"],
          "negative: a model a row is cabled to stays — its ✕ is refused, the cable goes first")
    desk().set_level("sub", "gpt-6.1-terra", 18000, 25, "stop")
    check(desk().remove_model("sub", "gpt-6.1-terra") == ["gpt-6-sol", "gpt-5.6-luna"],
          "✕ takes a model no row names off the column")
    check(ModelLevels(stored()).is_set("sub", "gpt-6.1-terra"),
          "its levels stay: put back, it has them again")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    check(desk().remove_model("sub", "gpt-6.1-terra") == ["gpt-6-sol", "gpt-5.6-luna"] and CLOUD_PROVIDERS_FILE.read_bytes() == before,
          "negative: one not on the column — nothing to do, nothing written")
    check(refused(lambda: desk().remove_model("nobody", "m")) == 404, "negative: an unknown account is 404")

    print("a model a row is cabled to is on the column — and stays when the cable goes:")
    new_form()
    desk().migrate_added()
    desk().add_row("sol")
    desk().connect_row("sol", "r1", {"accountId": "ant", "model": "claude-opus"})
    desk().add_row("sol", {"accountId": "sub", "model": "gpt-6.1-terra"})
    desk().add_row("sol", {"output": "srv:22011"})
    desk().add_step("luna", "ant", "claude-haiku")
    desk().create("Fresh", "sub", "gpt-6.2-astra")
    added = stored()["addedModels"]
    check(added == {"ant": ["claude-opus", "claude-haiku"], "sub": ["gpt-6-sol", "gpt-5.6-luna", "gpt-6.1-terra", "gpt-6.2-astra"]},
          f"a cable drawn, a row cabled at once, a step and a new pool's first row add their model; negative: a local "
          f"cell is no account's model and adds nothing (got {added})")
    desk().connect_row("sol", "r1", None)
    check("claude-opus" in stored()["addedModels"]["ant"], "the cable taken away leaves its model on the column")
    check(desk().remove_model("ant", "claude-opus") == ["claude-haiku"], "and only then may its ✕ take it off")
    desk().save_pool({"id": "luna", "steps": [{"id": "sub", "model": "gpt-6.3-nova"}, {"id": "ant"}]})
    check(stored()["addedModels"]["sub"][-1] == "gpt-6.3-nova", "a row's model changed by a save is added too")

    print("the list rides through every save of the file:")
    cloud.upsert_cloud_account({**KEY, "name": "Anthropic renamed"})
    desk().set_level("sub", "gpt-6-sol", 18000, 20, "stop")
    check(stored()["addedModels"]["ant"] == ["claude-haiku"],
          "an account saved and a level set keep it — a key the save forgot would vanish from the file")
    check(desk().added_models() == stored()["addedModels"], "the board is handed the list as the file keeps it")
    desk().remove_account("ant")
    check("ant" not in stored()["addedModels"], "an account deleted takes its list")


def test_model_doors():
    print("the two doors of the models column, as the page calls them:")
    import caravan.admin.routes as routes
    from caravan.admin.topology import topology_state
    new_form()
    desk().migrate_added()
    doc = json.loads(CLOUD_PROVIDERS_FILE.read_text(encoding="utf-8"))
    doc["pools"][0]["contextLength"] = 200000
    CLOUD_PROVIDERS_FILE.write_text(json.dumps(doc), encoding="utf-8")
    drawn = topology_state(refresh_hosts=False)
    check(drawn["addedModels"] == {"sub": ["gpt-6-sol", "gpt-5.6-luna"]},
          f"the board is handed the added models with the rest of the topology (got {drawn.get('addedModels')})")
    told = [(p["id"], p.get("window", "absent")) for p in drawn["pools"]]
    check(told == [("sol", 200000), ("luna", None)],
          f"each pool comes with the window it states to its clients — Routing's «Pool settings» say it; "
          f"negative: a pool that states none says None, not nothing (got {told})")
    sent = []

    class Page:
        def send_json(self, payload, *args, **kwargs):
            sent.append(payload)

    real, routes.topology_state = routes.topology_state, lambda **kw: {"drawn": True}
    try:
        routes.POST_ROUTES["/api/pools/add-model"](Page(), None, {"accountId": "sub", "model": "gpt-6.1-terra"})
        routes.POST_ROUTES["/api/pools/remove-model"](Page(), None, {"accountId": "sub", "model": "gpt-6.1-terra"})
        refused_door = refused(lambda: routes.POST_ROUTES["/api/pools/remove-model"](Page(), None, {"accountId": "sub", "model": "gpt-6-sol"}))
    finally:
        routes.topology_state = real
    check(sent == [{"ok": True, "models": ["gpt-6-sol", "gpt-5.6-luna", "gpt-6.1-terra"], "topology": {"drawn": True}},
                   {"ok": True, "models": ["gpt-6-sol", "gpt-5.6-luna"], "topology": {"drawn": True}}],
          f"«＋ model» adds, ✕ takes off; each answers the account's list and the topology to draw (got {sent})")
    check(refused_door == 409 and len(sent) == 2, "negative: ✕ on a model a row names is refused at the door, and answers nothing else")


def test_delete():
    print("a pool deleted:")
    new_form()
    client = lambda port, pool: {"port": port, "label": f"client {port}", "kind": "consumer", "apiKey": f"lcv1_c{port}",
                                 "portClosed": True, "pool": pool, "upstreamType": "cloud", "routerId": ""}
    write_proxies(routes=[client(23061, "luna"), client(23062, "sol"), client(23063, "luna")])
    done = desk().delete("luna")
    check(done == {"deleted": "luna", "moved": 0, "cut": 0, "onto": None, "uncabled": 2, "unset": []}
          and [p["id"] for p in stored()["pools"]] == ["sol"],
          f"nothing holds it: it goes without a question — and no port of its own to close (got {done})")
    pools = {r["port"]: r.get("pool") for r in cfg()["routes"] if r.get("kind") == "consumer"}
    check(pools == {23061: "", 23062: "sol", 23063: ""},
          "the clients cabled to it lose their cable: a new pool of that id — ids come from names — "
          "would have opened to them unasked; negative: a client of another pool keeps its cable")
    new_form()
    before = (CLOUD_PROVIDERS_FILE.read_bytes(), cfg())
    check(refused(lambda: desk().delete("sol")) == 409 and (CLOUD_PROVIDERS_FILE.read_bytes(), cfg()) == before,
          "defect-guard: cables and the default hold it — 409 without an answer, nothing touched")
    done = desk().delete("sol", {"cut": True})
    r = cfg()["routers"][0]
    check(done["cut"] == 3 and [e["id"] for e in r["graph"]["edges"]] == ["e0"] and r["rules"]["default"] == "srv:22011"
          and [p["id"] for p in stored()["pools"]] == ["luna"],
          f"cut: the cables went, the default fell to the first output (got {done})")
    new_form()
    done = desk().delete("sol", {"moveTo": "luna"})
    r = cfg()["routers"][0]
    check(done["moved"] == 3 and done["onto"] == "luna" and [e["to"] for e in r["graph"]["edges"]] == ["out:srv:22011", "out:cb:luna", "out:cb:luna"]
          and r["rules"]["default"] == "cb:luna" and r["graph"]["nodes"][0]["config"]["spillEdge"] == "e1",
          "moved: the cables stay where they were (same ids, the queue's spill a role still), the default follows")
    new_form()
    check(refused(lambda: desk().delete("sol", {"moveTo": "sol"})) == 400 and refused(lambda: desk().delete("sol", {"moveTo": "nope"})) == 404
          and refused(lambda: desk().delete("nope")) == 404,
          "negative: onto itself 400, onto a pool that is not there 404, no such pool 404")


def test_refs_name_the_clients():
    print("the delete preflight names the clients that call the pool (2026-10-11):")
    from caravan.admin import routes
    new_form()
    client = lambda port, name, pool: {"port": port, "label": name, "kind": "consumer", "apiKey": f"lcv1_c{port}",
                                       "portClosed": True, "pool": pool, "upstreamType": "cloud", "routerId": ""}
    write_proxies(routes=[client(23061, "Hermes", "luna"), client(23062, "Bot", "sol"), client(23063, "Zed", "luna")])
    sent = []
    handler = type("H", (), {"send_json": lambda self, data, status=200: sent.append(data)})()
    ask = lambda pool_id: (routes._get_api_pools_refs(handler, type("P", (), {"query": f"id={pool_id}"})()), sent[-1]["clients"])[1]
    check(ask("luna") == ["Hermes", "Zed"] and ask("sol") == ["Bot"], "the clients cabled to it now, and only them")
    check(ask("gone") == [], "negative: no such pool — nobody, not an error")


def test_no_door_of_its_own():
    print("a pool has no door of its own any more (the owner, 2026-10-12):")
    from caravan.admin import routes
    gone = [path for path in ("/api/pools/port", "/api/pools/port-close", "/api/app-port") if path in routes.POST_ROUTES]
    check(gone == [] and "/api/pools/delete" in routes.POST_ROUTES,
          f"no address opens or closes a pool's own port, nor mints an app's port; negative: the pools' other doors stay (got {gone})")
    new_form()
    sent = []
    handler = type("H", (), {"send_json": lambda self, data, status=200: sent.append(data)})()
    routes._get_api_pools_refs(handler, type("P", (), {"query": "id=luna"})())
    check(set(sent[-1]) == {"ok", "refs", "held", "clients"} and "bridges" not in sent[-1]["refs"],
          f"the delete preflight names no ports (got {sorted(sent[-1])})")


def test_remove_account():
    print("an account deleted takes its steps:")
    new_form()
    desk().add_step("sol", "ant", "claude-opus")
    vault = Vault()
    gone = desk(vault).remove_account("sub")
    pools = {p["id"]: p for p in stored()["pools"]}
    check([s["id"] for s in pools["sol"]["steps"]] == ["ant"] and pools["luna"]["steps"] == [],
          "its steps left every pool; the others stayed")
    check([a["id"] for a in stored()["accounts"]] == ["ant"] and vault.deleted == ["sub"] and gone,
          "the account and its sign-in are gone; the vault's entry comes back for the sign-out")
    new_form()
    alias = desk().clone_test("sub")
    check(alias["testAliasOf"] == "sub" and desk().clone_test("sub")["id"] == alias["id"],
          "a test alias is made once")
    check(refused(lambda: desk().remove_account("sub")) == 409, "negative: an owner with an alias goes after it")
    check(refused(lambda: desk().clone_test("ant")) == 400, "negative: a key has no alias")


def test_what_the_board_gets():
    print("what the board is handed:")
    new_form()
    desk().add_step("sol", "ant", "claude-opus")
    write_proxies(routes=[])
    now = 1_800_000_000
    STATE.write_text(json.dumps({"time": now, "subscriptionUsage": {"sub": {"windows": [
        {"seconds": 18000, "usedPct": 95, "resetAt": now + 600}, {"seconds": 604800, "usedPct": 20, "resetAt": now + 9000}],
        "readAt": now - 5}},
        "pools": {"pools": {"sol": {"selectedStepId": "ant", "steps": []}}, "events": [{"poolId": "sol"}]}}))
    pools = {p["id"]: p for p in desk(clock=lambda: now).state()}
    sol = pools["sol"]
    check("ports" not in sol and sol["held"] == {"cables": 2, "rules": ["default"]} and sol["inUse"] is True,
          "what holds it and whether anything uses it; negative: no own ports any more")
    hit = {"windowSeconds": 18000, "remainingPct": 5, "reservePct": 10, "resetAt": now + 600}
    check(sol["steps"][0]["stopReached"] == hit and sol["steps"][0]["switchReached"] == hit
          and sol["steps"][0]["readAt"] == now - 5 and sol["steps"][0]["usageAccountId"] == "sub",
          "the subscription's step: its 5% left is at its 10% stop (and switch) — by the proxy's reading and rule")
    check(sol["steps"][1]["switchReached"] is None and sol["steps"][1]["stopReached"] is None and sol["steps"][1]["readAt"] is None,
          "negative: a key's step has no reading — none, not a made-up one")
    desk().set_level("sub", "gpt-6-sol", 18000, 3, "stop")
    desk().set_level("sub", "gpt-6-sol", 18000, 30, "switch")
    step = [p for p in desk(clock=lambda: now).state() if p["id"] == "sol"][0]["steps"][0]
    check(step["stopReached"] is None and step["switchReached"] == {**hit, "reservePct": 30},
          "above its stop, below its switch: the step gives way, and says only that")
    check(pools["luna"]["inUse"] is False and pools["luna"]["held"] == {"cables": 0, "rules": []}, "an unused pool says so")
    runtime = desk(clock=lambda: now + 10).runtime()
    check(runtime["available"] is True and runtime["pools"]["sol"]["selectedStepId"] == "ant" and runtime["events"] == [{"poolId": "sol"}],
          "the proxy's word on the pools, while it is alive")
    check(desk(clock=lambda: now + 3600).runtime() == {"available": False, "pools": {}, "events": []},
          "negative: a silent proxy says nothing")
    accounts = {a["id"]: a for a in cloud.cloud_accounts_state()}
    check(accounts["sub"]["usedIn"] == [{"poolId": "sol", "poolName": "gpt-6-sol", "stepId": "sub"},
                                        {"poolId": "luna", "poolName": "gpt-5.6-luna", "stepId": "sub"}]
          and accounts["sub"]["subscription"] is True and accounts["ant"]["subscription"] is False,
          "an account says which pools' steps name it — what its deletion takes")
    routers = [{"id": "r", "outputs": [], "rules": {}}]
    pc.sync_router_outputs(routers, {"llamaServers": []}, desk().state(), [])
    check([o["id"] for o in routers[0]["outputs"]] == ["cb:sol", "cb:luna"]
          and routers[0]["outputs"][0]["label"] == "☁ gpt-6-sol" and routers[0]["outputs"][0]["target"] == "pool:sol",
          "every pool is an output of Routing, named by the pool")


def main():
    for fn in (test_migration_of_the_nas, test_migration_keeps_what_is_used, test_create_and_steps, test_save_pool,
               test_remove_step, test_levels, test_rows, test_named_after_its_model, test_order_and_arrange, test_order_doors, test_migrate_rows, test_added_models_rule, test_added_models, test_model_doors,
               test_delete, test_refs_name_the_clients,
               test_no_door_of_its_own,
               test_remove_account, test_what_the_board_gets):
        fn()
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("pools OK: пул — строки по порядку (подписка, локальная модель, пустая); уровни — у модели; справа — добавленные модели")
    return 0


if __name__ == "__main__":
    sys.exit(main())
