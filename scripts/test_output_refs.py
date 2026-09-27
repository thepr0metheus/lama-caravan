#!/usr/bin/env python3
"""Snapshot of RouterOutputRefs (caravan/admin/output_refs.py) and of the three
rewrites that go through it: a cell moved to another port (remap), two cells
swapping ports (swap), the one-time upgrade of a legacy cloud output (migrate).

Every place a router names an output is listed once, in the table; one router
names "srv:1" in all of them, and "srv:2" beside it is the negative. The legacy
upgrade kept its own copy of the list and never looked at the reserve default,
audio or embeddings — pinned as defect-history.

Run: python3 scripts/test_output_refs.py
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caravan.admin.proxies_config as pc  # noqa: E402
from caravan.admin.output_refs import RouterOutputRefs  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


ROUTER = {
    "id": "router:default",
    "outputs": [{"id": "srv:1", "upstreamPort": 1}, {"id": "srv:2", "upstreamPort": 2}],
    "rules": {
        "default": "srv:1", "dormantDefault": "srv:1", "audioOutput": "srv:1", "embeddingsOutput": "srv:1",
        "schedule": [{"output": "srv:1"}, {"output": "srv:2"}, "junk"],
        "bySource": [{"output": "srv:1", "source": "x"}],
        "failover": ["srv:2", "srv:1"],
    },
    "graph": {"edges": [
        {"id": "e1", "from": "rule:q", "to": "out:srv:1"},
        {"id": "e2", "from": "out:srv:1", "to": "rule:q"},
        {"id": "e3", "from": "rule:q", "to": "out:srv:2"},
        {"id": "e4", "from": "in:srv:1", "to": "rule:q"},
        "junk",
    ]},
}


def to(old, new):
    return lambda v: new if v == old else v


class FakeStore:
    """agent-proxies.json and cloud-providers.json in memory, for the rewrites that load and save."""

    def __init__(self, routers, blocks=None):
        self.payload = {"routes": [], "routers": routers}
        self.cloud = {"accounts": [], "blocks": blocks or []}
        self.saved = []
        self.cloud_saved = 0

    def patch(self):
        pc.load_agent_proxy_config = lambda: self.payload
        pc.save_agent_proxy_config = lambda routes, routers=None: self.saved.append(copy.deepcopy(routers))
        pc.load_cloud_data = lambda: self.cloud
        pc.save_cloud_data = self._save_cloud

    def _save_cloud(self, data):
        self.cloud_saved += 1


def main():
    print("таблица: где маршрутизатор называет выход")
    refs = RouterOutputRefs(ROUTER)
    check(refs.rules_naming("srv:1") == ["default", "dormantDefault", "audioOutput", "embeddingsOutput",
                                         "schedule", "bySource", "failover"],
          f"все правила, что называют выход, по порядку таблицы (got {refs.rules_naming('srv:1')})")
    check(refs.rules_naming("srv:2") == ["schedule", "failover"] and refs.rules_naming("srv:9") == [],
          "negative: соседний выход — только его правила; чужой — пусто")
    check([e["id"] for e in refs.edges_touching("srv:1")] == ["e1", "e2"],
          "канаты выхода — оба конца; «in:srv:1» — вход, а не выход, и не в счёт")
    check(RouterOutputRefs({}).rules_naming("srv:1") == [] and RouterOutputRefs(None).edges_touching("srv:1") == [],
          "negative: маршрутизатор без правил и графа — пусто, без падения")

    router = copy.deepcopy(ROUTER)
    n = RouterOutputRefs(router).rewrite(to("srv:1", "srv:7"))
    rules, edges = router["rules"], {e["id"]: e for e in router["graph"]["edges"] if isinstance(e, dict)}
    check(all(rules[k] == "srv:7" for k in ("default", "dormantDefault", "audioOutput", "embeddingsOutput")),
          "четыре правила-ключа переписаны")
    check(rules["schedule"] == [{"output": "srv:7"}, {"output": "srv:2"}, "junk"]
          and rules["bySource"] == [{"output": "srv:7", "source": "x"}] and rules["failover"] == ["srv:2", "srv:7"],
          "списки правил и failover — только совпавшие, порядок и мусор на месте")
    check(edges["e1"]["to"] == "out:srv:7" and edges["e2"]["from"] == "out:srv:7" and edges["e3"]["to"] == "out:srv:2"
          and edges["e4"]["from"] == "in:srv:1",
          "канаты — оба конца; чужой выход и вход с похожим именем не тронуты")
    check(n == 9, f"девять мест переписано: 4 ключа, 2 списка, failover, 2 конца (got {n})")
    check(router["outputs"] == ROUTER["outputs"], "список выходов — не ссылка, таблица его не трогает")
    same = copy.deepcopy(ROUTER)
    check(RouterOutputRefs(same).rewrite(lambda v: v) == 0 and same == ROUTER,
          "negative: тождественная замена — ноль и ни одного изменения")
    bare = {"id": "r"}
    check(RouterOutputRefs(bare).rewrite(to("srv:1", "srv:7")) == 0 and bare == {"id": "r"},
          "negative: пустой маршрутизатор не получает ключей")

    print("remap: ячейка переехала на другой порт")
    store = FakeStore([copy.deepcopy(ROUTER)])
    store.patch()
    check(pc.remap_router_output_refs("srv:1", "srv:5") is True and len(store.saved) == 1,
          "переписал и сохранил один раз")
    r = store.saved[0][0]
    check(r["outputs"][0] == {"id": "srv:5", "upstreamPort": 5} and r["rules"]["default"] == "srv:5"
          and r["rules"]["embeddingsOutput"] == "srv:5" and r["graph"]["edges"][1]["from"] == "out:srv:5",
          "выход сменил id и порт; правила и канаты — за ним")
    store = FakeStore([copy.deepcopy(ROUTER)])
    store.patch()
    check(pc.remap_router_output_refs("srv:9", "srv:5") is False and store.saved == [],
          "negative: выход, которого нет, — ничего не сохранено")

    print("swap: две ячейки поменялись портами")
    store = FakeStore([copy.deepcopy(ROUTER)])
    store.patch()
    check(pc.swap_router_output_refs("srv:1", "srv:2") is True and len(store.saved) == 1, "поменял и сохранил один раз")
    r = store.saved[0][0]
    check(r["outputs"] == [{"id": "srv:2", "upstreamPort": 2}, {"id": "srv:1", "upstreamPort": 1}],
          "выходы обменялись id и портами")
    check(r["rules"]["failover"] == ["srv:1", "srv:2"] and r["rules"]["schedule"][:2] == [{"output": "srv:2"}, {"output": "srv:1"}]
          and r["rules"]["default"] == "srv:2",
          "одним проходом: правила обменялись, а не стали обе вторым (a→b, потом b→a затёр бы)")
    check(r["graph"]["edges"][0]["to"] == "out:srv:2" and r["graph"]["edges"][2]["to"] == "out:srv:1",
          "канаты обменялись")
    store = FakeStore([copy.deepcopy(ROUTER)])
    store.patch()
    check(pc.swap_router_output_refs("srv:8", "srv:9") is False and store.saved == [],
          "negative: ни одного из двух — ничего не сохранено")

    print("migrate: старый облачный выход «cloud:<аккаунт>» → «cb:<модель>»")
    legacy = {
        "id": "router:default",
        "outputs": [{"id": "cloud:acc", "upstreamType": "cloud", "providerId": "blk"}],
        "rules": {"default": "cloud:acc", "dormantDefault": "cloud:acc", "audioOutput": "cloud:acc",
                  "bySource": [{"output": "cloud:acc"}], "failover": ["cloud:acc"]},
        "graph": {"edges": [{"id": "e1", "from": "rule:q", "to": "out:cloud:acc"}]},
    }
    store = FakeStore([], blocks=[{"id": "blk", "accountId": "acc"}])
    store.patch()
    routers = [copy.deepcopy(legacy)]
    check(pc.migrate_legacy_cloud_outputs(routers, ["acc"]) is True and store.cloud["blocks"][0].get("exposed") is True,
          "модель старого выхода показана на канбане")
    rules = routers[0]["rules"]
    check(rules["default"] == "cb:blk" and rules["bySource"] == [{"output": "cb:blk"}] and rules["failover"] == ["cb:blk"]
          and routers[0]["graph"]["edges"][0]["to"] == "out:cb:blk",
          "правила и канаты — на новый id")
    check(rules["dormantDefault"] == "cb:blk" and rules["audioOutput"] == "cb:blk",
          "defect-history: резервное «по умолчанию» и аудио тоже (своя копия списка их не видела)")
    empty_failover = copy.deepcopy(legacy)
    empty_failover["rules"]["failover"] = []
    no_rules = {"id": "r2", "outputs": [{"id": "cloud:acc", "upstreamType": "cloud", "providerId": "blk"}]}
    routers = [empty_failover, no_rules]
    store = FakeStore([], blocks=[{"id": "blk", "accountId": "acc"}])
    store.patch()
    pc.migrate_legacy_cloud_outputs(routers, ["acc"])
    check("failover" not in routers[0]["rules"] and routers[1]["rules"] == {},
          "as-is: пустой failover снимается ключом; маршрутизатор без правил получает пустые правила")
    store = FakeStore([], blocks=[{"id": "blk", "accountId": "acc"}])
    store.patch()
    routers = [copy.deepcopy(legacy)]
    check(pc.migrate_legacy_cloud_outputs(routers, ["other"]) is False and routers[0] == legacy
          and store.cloud_saved == 0,
          "negative: аккаунт не тот — ничего не переписано и не сохранено")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("output refs OK: одна таблица мест, где маршрутизатор называет выход")
    return 0


if __name__ == "__main__":
    sys.exit(main())
