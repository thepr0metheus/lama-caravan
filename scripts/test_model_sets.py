#!/usr/bin/env python3
"""Snapshot of the sets of models (caravan/admin/model_sets.py, caravan/common/entry_models.py).

The owner, 2026-10-12 (step 2 of the visumap scheme caravan-model-sets): a client of the entry is
cabled to a set, the set to pools; one set may serve several clients; a request's `model` picks a
pool of the client's set and a name the set has not is 404. Pinned by value against the real files
in a scratch data directory: the rule a key's models are read by (a set, or the older forms until
they are rewritten), the sets as the file keeps them, the desk's doors — made, named, filled,
emptied, deleted with its clients uncabled — a pool deleted leaving every set, a client cabled to a
set, the once-only move of the clients of one pool into sets, and the doors as the page calls them.

Run: python3 scripts/test_model_sets.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-model-sets-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
for sub in ("state", "config", "secrets", "logs"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from caravan.admin.consumers import ConsumerDesk  # noqa: E402
from caravan.admin.model_sets import SetDesk  # noqa: E402
from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE, CLOUD_PROVIDERS_FILE  # noqa: E402
from caravan.admin.pools import PoolDesk  # noqa: E402
from caravan.common.entry_models import ConsumerSet, EntryModels, ModelSets  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refused(fn):
    try:
        fn()
        return None
    except AppError as err:
        return err.status


SUB = {"id": "sub", "name": "ChatGPT subscription", "type": "openai-subscription", "accountType": "openai-subscription",
       "baseUrl": "https://chatgpt.com/backend-api", "authMode": "oauth"}
POOLS = [{"id": "std", "name": "Standart", "steps": [{"id": "sub", "accountId": "sub", "model": "gpt-6-sol", "enabled": True}]},
         {"id": "voice", "name": "Voice", "steps": []},
         {"id": "emb", "name": "Embeddings", "steps": []}]


def write_cloud(**extra):
    doc = {"accounts": [dict(SUB)], "pools": [json.loads(json.dumps(p)) for p in POOLS], "migrations": [SetDesk.MIGRATION], **extra}
    CLOUD_PROVIDERS_FILE.write_text(json.dumps(doc), encoding="utf-8")


def write_routes(routes):
    AGENT_PROXY_CONFIG_FILE.write_text(json.dumps({"routes": routes, "routers": [], "entry": {"port": 23999}}), encoding="utf-8")


def cloud():
    return json.loads(CLOUD_PROVIDERS_FILE.read_text(encoding="utf-8"))


def routes():
    return json.loads(AGENT_PROXY_CONFIG_FILE.read_text(encoding="utf-8"))["routes"]


def client(port, label, **extra):
    return {"label": label, "port": port, "kind": "consumer", "apiKey": f"lcv1_{label.lower():x<48}", "portClosed": True,
            "upstreamType": "cloud", "routerId": "", "mode": "open", **extra}


def test_rule():
    print("what a key calls, by its set:")
    pools = [{"id": "std", "name": "Standart"}, {"id": "voice", "name": "Voice"}, {"id": "emb", "name": "Embeddings"}]
    sets = [{"id": "chat", "name": "Chat", "pools": ["voice", "std", "gone", "std"]}, {"id": "none", "pools": []}, "junk", {"name": "no id"}]
    rule = EntryModels(pools, sets)
    hermes = {"kind": "consumer", "set": "chat"}
    names = [EntryModels.name(p) for p in rule.models(hermes)]
    check(names == ["Voice", "Standart"], f"the set's pools by name, in its order, each once; a pool that is gone left out (got {names})")
    check([rule.pick(hermes, m) and rule.pick(hermes, m)["id"] for m in ("Standart", "Voice", "standart", "Embeddings", "", None)]
          == ["std", "voice", None, None, None, None],
          "a request's model picks a pool of its set, spelled as the list spells it; negative: another case, a pool of "
          "another set, no name — none")
    check([rule.models(r) for r in ({"set": ""}, {"set": "nope"}, {"set": "none"}, None)] == [[], [], [], []],
          "negative: no cable, a set that is gone, an empty set, no route — no model")
    check([[p["id"] for p in rule.models(r)] for r in ({"pool": "emb"}, {"pool": "gone"}, {"models": "all"}, {"models": ["voice", "emb"]})]
          == [["emb"], [], ["std"], ["voice"]],
          "a route of an older form calls its one pool until the controller rewrites it: `pool`, or the first of `models`")
    check(rule.set_of(hermes)["name"] == "Chat" and rule.set_of({"set": "nope"}) is None, "the set a route is cabled to, or none")
    check(rule.callers([client(1, "Hermes", set="chat"), client(2, "Bot", set="none"), client(3, "Old", pool="std"), {"label": "agent", "pool": "std"}], "std")
          == ["Hermes", "Old"], "who loses a model when its pool goes: the clients whose sets — or older pool — call it; negative: not an agent")
    check(ModelSets.clean([{"id": " a ", "name": "", "pools": ["x", "x", "", None, 5]}, {"id": "a"}, {"id": ""}])
          == [{"id": "a", "name": "a", "pools": ["x", "5"]}], "the sets as the file keeps them: ids once, pools once; a set with no name is called by its id")
    check([ConsumerSet.fields(r) for r in ({"set": " chat "}, {"set": True}, {"pool": "std"}, {"models": "all"})]
          == [{"set": "chat"}, {"set": ""}, {"pool": "std"}, {"models": "all"}],
          "a route keeps its set; one of an older form keeps its pool or models until it is rewritten")


def test_desk():
    print("the sets on the controller's files:")
    write_cloud()
    write_routes([client(23001, "Hermes", set=""), client(23002, "Bot", set="")])
    desk = SetDesk()
    first, second = desk.create(), desk.create()
    named = desk.create("Voice set")
    check([first["name"], second["name"], named["name"]] == ["Set", "Set 2", "Voice set"]
          and [first["id"], second["id"], named["id"]] == ["Set", "Set-2", "Voice-set"],
          f"«＋ New set»: Set, then Set 2 — a default is made free, not refused; a name given is kept (got {[first, second, named]})")
    check(refused(lambda: desk.create("voice SET")) == 409 and refused(lambda: desk.rename("Set", "Voice set")) == 409
          and refused(lambda: desk.rename("Set", "  ")) == 400 and refused(lambda: desk.rename("nope", "x")) == 404,
          "negative: a name another set has (any case), no name, no such set — refused")
    desk.rename("Set", "Chat")
    desk.add_pool("Set", "std")
    desk.add_pool("Set", "voice")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    desk.add_pool("Set", "std")
    check(CLOUD_PROVIDERS_FILE.read_bytes() == before and refused(lambda: desk.add_pool("Set", "nope")) == 400,
          "negative: a pool the set holds stays where it is, nothing written; a pool that is not — 400")
    check(desk.state()[0] == {"id": "Set", "name": "Chat", "pools": ["std", "voice"]},
          f"renamed, filled in the order the cables came (got {desk.state()[0]})")
    desk.remove_pool("Set", "voice")
    check(desk.state()[0]["pools"] == ["std"], "a cut cable takes the pool out of the set")
    ConsumerDesk().set_set(23001, "Set")
    ConsumerDesk().set_set(23002, "Set")
    check([r.get("set") for r in routes()] == ["Set", "Set"] and all("pool" not in r for r in routes()),
          "two clients on one set — a set may serve several")
    check(refused(lambda: ConsumerDesk().set_set(23001, "nope")) == 400 and refused(lambda: ConsumerDesk().set_set(99, "Set")) == 404,
          "negative: a set that is not, a number that is no client's — refused, not dropped")
    done = desk.delete("Set")
    check(done == {"deleted": "Set", "uncabled": ["Hermes", "Bot"]} and [r.get("set") for r in routes()] == ["", ""]
          and [s["id"] for s in desk.state()] == ["Set-2", "Voice-set"],
          f"a set deleted takes its clients' cable with it — its id would wait for the next set of that id (got {done})")

    print("the sets' order on the kanban (1.3.503: a set card carried):")
    write_cloud(sets=[{"id": "a", "name": "A", "pools": ["std"]}, {"id": "b", "name": "B", "pools": []}, {"id": "c", "name": "C", "pools": ["emb"]}])
    check(SetDesk().order(["c", "a", "b"]) == ["c", "a", "b"] and [x["id"] for x in cloud()["sets"]] == ["c", "a", "b"]
          and cloud()["sets"][1] == {"id": "a", "name": "A", "pools": ["std"]},
          "a carried card's order is the file's order of the sets; each set as it was")
    before = CLOUD_PROVIDERS_FILE.read_bytes()
    for bad, why in ((["c", "a"], "a set left out"), (["c", "a", "b", "d"], "a set the file has not"), (["c", "c", "a", "b"], "a set twice"),
                     ("c", "not a list"), (None, "nothing")):
        check(refused(lambda: SetDesk().order(bad)) == 409, f"negative: {why} — 409, draw the board again")
    check(CLOUD_PROVIDERS_FILE.read_bytes() == before, "and a refused order writes nothing")

    print("a pool deleted leaves every set:")
    write_cloud(sets=[{"id": "a", "name": "A", "pools": ["std", "voice"]}, {"id": "b", "name": "B", "pools": ["voice"]},
                      {"id": "c", "name": "C", "pools": ["emb"]}])
    write_routes([])
    saved = []
    gone = PoolDesk(save_proxies=lambda routes, routers: saved.append(len(routes))).delete("voice")
    check(gone["unset"] == ["A", "B"] and [s["pools"] for s in cloud()["sets"]] == [["std"], [], ["emb"]],
          f"the pool goes out of each set that held it, in the same write, and the answer names them (got {gone.get('unset')})")
    check(cloud()["sets"][2] == {"id": "c", "name": "C", "pools": ["emb"]}, "negative: a set that did not hold it is as it was")


def test_migration():
    print("clients cabled to one pool, moved into sets once:")
    write_cloud()
    doc = cloud()
    doc["migrations"] = []
    CLOUD_PROVIDERS_FILE.write_text(json.dumps(doc), encoding="utf-8")
    write_routes([client(23001, "Hermes", pool="std"), client(23002, "Sinapse", pool="std"), client(23003, "Bot", pool=""),
                  client(23004, "Old", models=["emb"]), client(23005, "New", set="kept"), {"label": "agent", "port": 23050}])
    writes = []
    real = SetDesk()
    desk = SetDesk(save=lambda data: (writes.append("cloud"), real.save(data)),
                   save_proxies=lambda payload: (writes.append("routes"), real.save_proxies(payload)))
    done = desk.migrate()
    by = {r["label"]: r for r in routes()}
    check(done == {"sets": ["Standart", "Embeddings"], "clients": [{"name": "Hermes", "set": "Standart"}, {"name": "Sinapse", "set": "Standart"},
                                                                {"name": "Bot", "set": ""}, {"name": "Old", "set": "Embeddings"}]},
          f"one set per pool so cabled, named as the pool and shared by its clients; a client with no pool gets no set (got {done})")
    check([by[n].get("set") for n in ("Hermes", "Sinapse", "Bot", "Old", "New")] == ["Standart", "Standart", "", "Embeddings", "kept"]
          and not any("pool" in r or "models" in r for r in routes() if r.get("kind") == "consumer") and "set" not in by["agent"],
          "each client keeps its set's id, its old field goes; negative: a client with a set already and an agent are left alone")
    check(cloud()["sets"] == [{"id": "Standart", "name": "Standart", "pools": ["std"]}, {"id": "Embeddings", "name": "Embeddings", "pools": ["emb"]}]
          and SetDesk.MIGRATION in cloud()["migrations"], "the sets in the file, the move stamped")
    check(writes == ["cloud", "routes"], f"the sets are written before the routes: meanwhile the proxy reads a route's old pool (got {writes})")
    before = (CLOUD_PROVIDERS_FILE.read_bytes(), AGENT_PROXY_CONFIG_FILE.read_bytes())
    check(SetDesk().migrate() is None and (CLOUD_PROVIDERS_FILE.read_bytes(), AGENT_PROXY_CONFIG_FILE.read_bytes()) == before,
          "negative: a second start moves nothing and writes nothing")


def test_doors():
    print("the doors, as the page calls them:")
    import caravan.admin.routes as routes_mod
    write_cloud()
    write_routes([client(23001, "Hermes", set="")])
    sent = []

    class Page:
        def send_json(self, payload, *args, **kwargs):
            sent.append(payload)

    real, routes_mod.topology_state = routes_mod.topology_state, lambda **kw: {"drawn": True}
    try:
        post = routes_mod.POST_ROUTES
        post["/api/sets/create"](Page(), None, {"name": "Chat"})
        post["/api/sets/add-pool"](Page(), None, {"id": "Chat", "pool": "std"})
        post["/api/consumers/set"](Page(), None, {"port": 23001, "set": "Chat"})
        post["/api/sets/rename"](Page(), None, {"id": "Chat", "name": "Chat and voice"})
        post["/api/sets/remove-pool"](Page(), None, {"id": "Chat", "pool": "std"})
        post["/api/sets/delete"](Page(), None, {"id": "Chat"})
        gone = "/api/consumers/pool" in post
        SetDesk().create("One")
        SetDesk().create("Two")
        post["/api/sets/order"](Page(), None, {"ids": ["Two", "One"]})
        ordered = sent.pop()
    finally:
        routes_mod.topology_state = real
    check([s.get("set", s.get("deleted")) for s in sent] == [
        {"id": "Chat", "name": "Chat", "pools": []}, {"id": "Chat", "name": "Chat", "pools": ["std"]}, "Chat",
        {"id": "Chat", "name": "Chat and voice", "pools": ["std"]}, {"id": "Chat", "name": "Chat and voice", "pools": []}, "Chat"]
          and all(s.get("topology") == {"drawn": True} for s in sent) and sent[-1].get("uncabled") == ["Hermes"],
          f"made, filled, a client cabled, renamed, emptied, deleted with its client uncabled — each answers the topology (got {sent})")
    check(not gone, "negative: the door that cabled a client to a pool is gone — a client is cabled to a set")
    check(ordered == {"ok": True, "order": ["Two", "One"], "topology": {"drawn": True}} and [x["id"] for x in cloud()["sets"]] == ["Two", "One"],
          f"the sets' order by its door — answered with the board (got {ordered})")


def main():
    for fn in (test_rule, test_desk, test_migration, test_doors):
        fn()
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("model sets OK: клиент — один канат к набору, набор — к пулам, модель выбирает пул")
    return 0


if __name__ == "__main__":
    sys.exit(main())
