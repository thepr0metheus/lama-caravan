#!/usr/bin/env python3
"""Snapshot of caravan/admin/cloud_ports.py: a cloud model is on the kanban
while it has a port of its own (the operator's rule, 2026-09-27).

CloudModelPorts is read by value over one config. CloudPortDesk runs against
the real files in a scratch data directory — opening and closing ports, the
answer the last port asks for when cables or rules hold the model, and the
one-time move of the old `exposed` flag into ports. The firewall door and
systemd are stand-ins that write down what they were asked; nothing reaches
the machine.

Run: python3 scripts/test_cloud_ports.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-cloudports-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
for sub in ("state", "config", "secrets"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

import caravan.admin.cloud as cloud  # noqa: E402
import caravan.admin.cloud_ports as cp  # noqa: E402
import caravan.admin.proxies_config as pc  # noqa: E402
import caravan.admin.systemd_ctl as sc  # noqa: E402
from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class DoorLog:
    """Stands in for PORT_DOOR: what the firewall would have been asked."""

    def __init__(self):
        self.calls = []

    def open(self, port):
        self.calls.append(("open", port))

    def close(self, port):
        self.calls.append(("close", port))


DOOR = DoorLog()
pc.PORT_DOOR = DOOR
sc.IS_CONTAINER = False
sc.systemctl = lambda *a, **kw: {"ok": True, "stderr": ""}

ROUTER = {
    "id": "router:default", "name": "Default",
    # cb:sol is among the outputs, as the sync of outputs makes it for a model
    # with a port: without it, loading the router resets a default that names it.
    "outputs": [{"id": "srv:22011", "label": "cell :22011", "upstreamHost": "10.0.0.5", "upstreamPort": 22011,
                 "upstreamType": "llama"},
                {"id": "cb:sol", "label": "☁ gpt-6-sol", "target": "cloud:acc", "upstreamHost": "", "upstreamPort": 0,
                 "upstreamType": "cloud", "providerId": "sol", "accountId": "acc"}],
    "rules": {"default": "cb:sol", "schedule": [], "bySource": [], "failover": []},
    "graph": {"nodes": [{"id": "q", "type": "queue", "config": {"admitEdge": "e0", "spillEdge": "e1"}}],
              "edges": [{"id": "e0", "from": "rule:q", "to": "out:srv:22011"},
                        {"id": "e1", "from": "rule:q", "to": "out:cb:sol"},
                        {"id": "e2", "from": "in:skynet:proxy:23001", "to": "out:cb:sol"}]},
}


def seed(routes=(), router=None, flags=()):
    cloud.save_cloud_data({
        "accounts": [{"id": "acc", "name": "OpenAI", "type": "openai"}, {"id": "acc2", "name": "Other", "type": "openai"}],
        "blocks": [dict(b, **({"exposed": True} if b["id"] in flags else {})) for b in (
            {"id": "sol", "accountId": "acc", "model": "gpt-6-sol"},
            {"id": "luna", "accountId": "acc", "model": "gpt-6-luna"},
            {"id": "terra", "accountId": "acc", "model": "gpt-5.6-terra"},
            {"id": "far", "accountId": "acc2", "model": "other"},
        )]})
    payload = {"routes": [{"port": 23001, "label": "agent", "routerId": "router:default"}, *routes],
               "routers": [copy.deepcopy(router or ROUTER)]}
    Path(AGENT_PROXY_CONFIG_FILE).write_text(json.dumps(payload))
    DOOR.calls.clear()


def port_of(model, port):
    return {"port": port, "label": f"bridge {model}", "kind": "service", "upstreamType": "cloud",
            "providerId": model, "routerId": "", "mode": "open"}


def cfg():
    return pc.load_agent_proxy_config()


def shown():
    return sorted(b["id"] for b in cloud.cloud_blocks_state() if b["exposed"])


def refused(fn):
    try:
        fn()
        return None
    except AppError as err:
        return err.status


def test_reading():
    print("CloudModelPorts — чтение значениями:")
    c = {"routes": [port_of("sol", 23004), port_of("sol", 23009), port_of("luna", 23005),
                    {"port": 23001, "label": "agent"}, {"port": 23007, "kind": "service", "providerId": ""}],
         "routers": [copy.deepcopy(ROUTER), {"id": "r2", "rules": {"dormantDefault": "cb:luna", "failover": ["cb:sol"]},
                                              "graph": {"edges": []}}]}
    p = cp.CloudModelPorts(c)
    check(p.of("sol") == [23004, 23009] and p.of("luna") == [23005] and p.of("terra") == [],
          "порты модели — по возрастанию; у модели без порта — пусто")
    check(p.on_kanban() == {"sol", "luna"},
          "на канбане — модели со своим портом; negative: маршрут агента и служебный без модели не в счёт")
    check(p.held("sol") == {"cables": 2, "rules": ["default", "failover"]},
          f"что держит модель: два каната и её правила по всем маршрутизаторам (got {p.held('sol')})")
    check(p.held("luna") == {"cables": 0, "rules": []},
          "negative: запасное «по умолчанию» (dormantDefault) не держит — оно по замыслу ждёт свой выход")
    c2 = copy.deepcopy(c)
    n = cp.CloudModelPorts(c2).cut("sol")
    check(n == 4 and not cp.CloudModelPorts(c2).held("sol")["cables"] and "default" not in c2["routers"][0]["rules"]
          and c2["routers"][1]["rules"]["failover"] == [],
          f"отсоединить: канаты, «по умолчанию» и failover ушли (got {n})")


def test_open():
    print("открыть порт = поставить модель на канбан:")
    seed()
    port = cp.CloudPortDesk().open("terra")
    routes = [r for r in cfg()["routes"] if r.get("providerId") == "terra"]
    check(len(routes) == 1 and routes[0]["kind"] == "service" and routes[0]["port"] == port and 23001 < port < 24000,
          f"модель получила свой порт в диапазоне прокси (got {port})")
    check(shown() == ["terra"] and ("open", port) in DOOR.calls, "она на канбане, дверь фаервола открыта")
    check(cp.CloudPortDesk().open("terra") == port and len([r for r in cfg()["routes"] if r.get("providerId") == "terra"]) == 1,
          "negative: второй раз — тот же порт, второго не появляется")
    check(refused(lambda: cp.CloudPortDesk().open("nope")) == 404, "negative: модели нет — 404")


def test_exposure_is_the_port():
    print("«на канбане» читается из портов, а не из флага:")
    seed(routes=[port_of("sol", 23004)], flags=("luna",))
    check(shown() == ["sol"], "модель с портом — на канбане; флаг без порта (старый) — нет: факт один, это порт")
    blk = cloud.normalize_cloud_block({"id": "x", "accountId": "acc", "model": "m", "exposed": True}, {"acc"})
    check("exposed" not in blk, "negative: флаг, присланный по старинке, в модели не хранится")


def test_close():
    print("закрыть порт:")
    seed(routes=[port_of("luna", 23005)])
    got = cp.CloudPortDesk().close("luna")
    check(got["closed"] == [23005] and got["leaves"] is True and shown() == [] and ("close", 23005) in DOOR.calls,
          "модель ничем не держится — порт закрыт без вопросов, модель ушла с канбана, дверь закрыта")

    seed(routes=[port_of("sol", 23004)])
    before = cfg()
    check(refused(lambda: cp.CloudPortDesk().close("sol")) == 409 and cfg() == before,
          "defect-guard: канаты и «по умолчанию» держат модель — без ответа 409, ничего не тронуто")

    seed(routes=[port_of("sol", 23004), port_of("sol", 23009)])
    got = cp.CloudPortDesk().close_port(23009)
    check(got["closed"] == [23009] and got["leaves"] is False and shown() == ["sol"],
          "не последний порт — закрывается без вопросов, модель остаётся на канбане")

    seed(routes=[port_of("sol", 23004)])
    got = cp.CloudPortDesk().close("sol", resolution={"cut": True})
    r = cfg()["routers"][0]
    check(got["cut"] == 3 and [e["id"] for e in r["graph"]["edges"]] == ["e0"] and r["rules"]["default"] == "srv:22011"
          and r["graph"]["nodes"][0]["config"]["spillEdge"] == "" and shown() == [],
          f"«отсоединить»: канаты ушли, роль перелива очереди очистилась, «по умолчанию» — первый выход (got {got['cut']})")

    seed(routes=[port_of("sol", 23004)])
    got = cp.CloudPortDesk().close("sol", resolution={"moveTo": "luna"})
    c = cfg()
    r = c["routers"][0]
    luna = [x["port"] for x in c["routes"] if x.get("providerId") == "luna"]
    check(got["moved"] == 3 and got["onto"] == "luna" and len(luna) == 1 and shown() == ["luna"],
          "«перецепить»: у luna не было порта — открыт; sol ушла с канбана, luna на нём")
    check([e["to"] for e in r["graph"]["edges"]] == ["out:srv:22011", "out:cb:luna", "out:cb:luna"]
          and r["rules"]["default"] == "cb:luna" and r["graph"]["nodes"][0]["config"]["spillEdge"] == "e1",
          "канаты на месте (id те же, перелив очереди остался ролью), «по умолчанию» — на luna")

    seed(routes=[port_of("sol", 23004)])
    check(refused(lambda: cp.CloudPortDesk().close("sol", resolution={"moveTo": "far"})) == 400
          and refused(lambda: cp.CloudPortDesk().close("sol", resolution={"moveTo": "sol"})) == 400
          and [x["port"] for x in cfg()["routes"] if x.get("providerId") == "sol"] == [23004],
          "negative: перецепить на модель другого провайдера или на саму себя — 400, порт на месте")


def test_close_port_kinds():
    print("✕ у порта — какие маршруты это разрешает:")
    seed(routes=[{"port": 23007, "label": "odd", "kind": "service", "providerId": ""}])
    check(refused(lambda: cp.CloudPortDesk().close_port(23001)) == 400, "negative: маршрут агента — не порт модели, 400")
    check(refused(lambda: cp.CloudPortDesk().close_port(23999)) == 404, "negative: такого порта нет — 404")
    check(refused(lambda: cp.CloudPortDesk().close_port("x")) == 400, "negative: не число — 400")
    got = cp.CloudPortDesk().close_port(23007)
    check(got["closed"] == [23007] and all(r["port"] != 23007 for r in cfg()["routes"]),
          "служебный маршрут без модели ничего не держит на канбане — закрывается сразу")


def test_move_cables():
    print("перенос канатов (окно «новая модель», «⇄ Перецепить…»):")
    seed(routes=[port_of("sol", 23004)])
    moved = cp.CloudPortDesk().move_cables("sol", "terra")
    check(moved == 3 and shown() == ["sol", "terra"],
          "у terra открылся свой порт — она на канбане; sol остаётся со своим портом")
    seed(routes=[port_of("sol", 23004)])
    check(refused(lambda: cp.CloudPortDesk().move_cables("sol", "far")) == 400
          and refused(lambda: cp.CloudPortDesk().move_cables("sol", "nope")) == 400,
          "negative: чужой провайдер, несуществующая модель — 400")


def test_adopt_flags():
    print("разовый переход: флаг «на канбане» → свой порт:")
    seed(routes=[port_of("sol", 23004)], flags=("sol", "luna", "terra"))
    opened = cp.CloudPortDesk().adopt_flags()
    blocks = {b["id"]: b for b in cloud.load_cloud_data()["blocks"]}
    check(len(opened) == 2 and shown() == ["luna", "sol", "terra"],
          f"модели, что были на канбане без порта, получили порты — на доске ничего не изменилось (got {opened})")
    check(not any("exposed" in b for b in blocks.values()), "флаг снят со всех моделей, у sol — только флаг (порт уже был)")
    check(cp.CloudPortDesk().adopt_flags() == [], "negative: второй запуск — делать нечего")

    seed(flags=("luna", "terra"))
    real = cp.CloudPortDesk.open

    def open_but_terra(self, block_id):
        if block_id == "terra":
            raise AppError("no free port", 500)
        return real(self, block_id)
    cp.CloudPortDesk.open = open_but_terra
    try:
        opened = cp.CloudPortDesk().adopt_flags()
    finally:
        cp.CloudPortDesk.open = real
    blocks = {b["id"]: b for b in cloud.load_cloud_data()["blocks"]}
    check(len(opened) == 1 and blocks["terra"].get("exposed") is True and "exposed" not in blocks["luna"],
          "порт не открылся — флаг ждёт следующего старта, а не пропадает молча")


def main():
    test_reading()
    test_open()
    test_exposure_is_the_port()
    test_close()
    test_close_port_kinds()
    test_move_cables()
    test_adopt_flags()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("cloud ports OK: на канбане — модели со своим портом")
    return 0


if __name__ == "__main__":
    sys.exit(main())
