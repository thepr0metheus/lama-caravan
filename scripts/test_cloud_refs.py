#!/usr/bin/env python3
"""Snapshot of CloudModelRefs (caravan/admin/cloud_refs.py): everything that
points at a cloud model, by value.

A model the provider stopped offering may leave by itself only when nothing
points at it, and the delete confirm lists what would break. The list it
replaced missed a 🛟 backup's roles, the default a router keeps in reserve, an
agent's own cloud route and its ↑☁ fallback — those are pinned as
defect-history. One config names every kind of reference to one model, and a
second model that nothing touches is the negative.

Run: python3 scripts/test_cloud_refs.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.cloud_refs import CloudModelRefs  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


CFG = {
    "routes": [
        {"port": 23004, "label": "voice app", "kind": "service", "upstreamType": "cloud", "providerId": "sol"},
        {"port": 23009, "label": "old agent", "upstreamType": "cloud", "providerId": "sol"},
        {"port": 23101, "label": "charlie", "cloudFallbackProviderId": "sol"},
        {"port": 23001, "label": "hermes"},
    ],
    "routers": [{
        "id": "router:default",
        "rules": {"default": "srv:22011", "dormantDefault": "cb:sol", "schedule": [{"output": "cb:sol"}],
                  "bySource": [{"output": "srv:22001"}], "failover": ["cb:sol"], "embeddingsOutput": "srv:22001"},
        "graph": {
            "nodes": [
                {"id": "q", "type": "queue", "config": {"admitEdge": "e1", "spillEdge": "e2"}},
                {"id": "b", "type": "onError", "config": {"mainEdge": "e4", "rescueEdge": "e3"}},
                {"id": "w", "type": "weighted", "config": {}},
            ],
            "edges": [
                {"id": "e1", "from": "rule:q", "to": "srv:22011"},
                {"id": "e2", "from": "rule:q", "to": "out:cb:sol"},
                {"id": "e3", "from": "rule:b", "to": "out:cb:sol"},
                {"id": "e4", "from": "rule:b", "to": "rule:q"},
                {"id": "e5", "from": "rule:w", "to": "out:cb:luna"},
            ],
        },
    }],
}


def main():
    refs = CloudModelRefs(CFG)
    got = refs.of("sol")
    print("всё, что указывает на модель:")
    check(got["bridges"] == [{"port": 23004, "label": "voice app"}], f"мост (service) — порт и имя (got {got['bridges']})")
    check([e["id"] for e in got["edges"]] == ["e2", "e3"], f"канаты к cb:sol (got {[e['id'] for e in got['edges']]})")
    check(got["queueRoles"] == [{"router": "router:default", "node": "q", "role": "spill"}],
          "роль очереди — перелив, основной выход очереди идёт в ячейку и сюда не попадает")
    check(got["rules"] == [{"router": "router:default", "rule": "dormantDefault"},
                           {"router": "router:default", "rule": "schedule"},
                           {"router": "router:default", "rule": "failover"}],
          f"правила: резервное «по умолчанию», расписание, failover; default и embeddings идут в ячейки (got {got['rules']})")
    check(got["rescueRoles"] == [{"router": "router:default", "node": "b", "role": "backup"}]
          and got["routes"] == [{"port": 23009, "label": "old agent"}]
          and got["fallbacks"] == [{"port": 23101, "label": "charlie"}],
          "defect-history: запасной выход 🛟, облачный маршрут агента и его ↑☁ — прежний список их не видел, "
          f"и окно удаления говорило «ничего не ссылается» (got {got['rescueRoles']}, {got['routes']}, {got['fallbacks']})")
    check(refs.in_use("sol") is True, "модель в деле")

    print("модель, на которую не указывает ничего, кроме одного каната:")
    luna = refs.of("luna")
    check(luna["edges"] == [{"router": "router:default", "id": "e5", "from": "rule:w", "to": "out:cb:luna"}]
          and not any(v for k, v in luna.items() if k != "edges"),
          "канат из узла весов — только канат, ролей нет")
    check(refs.in_use("luna") is True, "один канат — уже «в деле»")
    free = refs.of("terra")
    check(not any(free.values()) and refs.in_use("terra") is False,
          f"negative: ни одной ссылки — пусто по всем видам, «не в деле» (got {free})")
    check(CloudModelRefs({}).in_use("sol") is False, "negative: пустой конфиг — ничего не в деле")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("cloud refs OK: полный список ссылок на облачную модель")
    return 0


if __name__ == "__main__":
    sys.exit(main())
