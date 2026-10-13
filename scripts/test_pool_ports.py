#!/usr/bin/env python3
"""Snapshot of caravan/admin/pool_ports.py: a pool's own ports are gone.

Every client comes in through one address, the entry, with its own key (the
owner, 2026-10-12). A pool's own port — a route of kind "service", open
without a key — leaves the file at the controller's start, and the answer
names each port closed, for the line in the log; a file without one is not
written at all. Behind the step: the controller takes no such route in
(caravan/admin/router_dsl.py — a save that brings one back is refused, a
reading passes it by), and the proxy opens no listener on one
(caravan/proxy/config.py). The file is a scratch copy and systemd a stand-in
that writes down what it was asked: nothing on the machine is touched.

Run: python3 scripts/test_pool_ports.py
"""
import copy
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-poolports-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["LLAMA_ADMIN_STATE"] = str(TMP / "admin.json")
for sub in ("state", "config", "secrets"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

import caravan.admin.proxies_config as pc  # noqa: E402
import caravan.admin.systemd_ctl as sc  # noqa: E402
import caravan.proxy.config as proxy_config  # noqa: E402
from caravan.admin.paths import AGENT_PROXY_CONFIG_FILE  # noqa: E402
from caravan.admin.pool_ports import PoolPortsRetired  # noqa: E402
from caravan.admin.router_dsl import normalize_agent_proxy_route  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.proxy.paths import CONFIG_FILE as PROXY_CONFIG_FILE  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


sc.IS_CONTAINER = False
sc.systemctl = lambda *a, **kw: {"ok": True, "stderr": ""}

AGENT = {"port": 23001, "label": "agent", "routerId": "router:default"}
CLIENT = {"port": 23005, "label": "Hermes", "kind": "consumer", "pool": "sol", "apiKey": "lcv1_" + "a" * 48,
          "portClosed": True, "routerId": ""}
POOL_PORT = {"port": 23004, "label": "bridge Standart", "kind": "service", "upstreamType": "cloud",
             "providerId": "sol", "routerId": "", "mode": "open"}


def refused(fn):
    try:
        fn()
        return None
    except AppError as err:
        return (err.status, str(err))


class Desk:
    """The file as the step reads and writes it: a dict, and a list of what was saved."""

    def __init__(self, payload):
        self.payload, self.saved = payload, []

    def step(self):
        return PoolPortsRetired(read=lambda: self.payload, save=lambda p: self.saved.append(copy.deepcopy(p)))


def test_the_step():
    print("при старте свои порты пула уходят из файла, остальное не тронуто:")
    payload = {"routes": [dict(AGENT), dict(POOL_PORT), dict(CLIENT),
                          {"port": 23006, "label": "odd", "kind": " Service "},
                          {"port": "x", "label": "broken", "kind": "service"}],
               "routers": [{"id": "router:default"}], "entry": {"port": 23999}, "policy": {"maxSlots": 4}}
    desk = Desk(payload)
    got = desk.step().migrate()
    check(got == [{"port": 23004, "label": "bridge Standart", "pool": "sol"},
                  {"port": 23006, "label": "odd", "pool": ""}, {"port": 0, "label": "broken", "pool": ""}],
          f"ответ называет каждый закрытый порт, его имя и пул — по порядку файла (got {got})")
    check(len(desk.saved) == 1 and desk.saved[0]["routes"] == [AGENT, CLIENT],
          "записан один раз: маршрут агента и клиент входа остались как были и в том же порядке")
    check(desk.saved and desk.saved[0]["routers"] == [{"id": "router:default"}] and desk.saved[0]["entry"] == {"port": 23999}
          and desk.saved[0]["policy"] == {"maxSlots": 4},
          "маршрутизаторы, вход и политика файла остались")
    clean = Desk({"routes": [dict(AGENT), dict(CLIENT)], "entry": {}})
    check(clean.step().migrate() is None and clean.saved == [],
          "negative: своих портов нет — ответ None, файл не записан")
    for name, odd in (("routes не список", {"routes": "nope"}), ("файла нет", None), ("пустой", {})):
        desk = Desk(odd)
        check(desk.step().migrate() is None and desk.saved == [], f"negative: {name} — None, ничего не записано")


def test_controller_takes_none_in():
    print("контроллер свой порт пула не принимает:")
    why = refused(lambda: normalize_agent_proxy_route(dict(POOL_PORT)))
    check(why is not None and why[0] == 400 and "pool's own port is gone" in why[1] and "entry" in why[1],
          f"маршрут вида service — отказ 400 со словами, куда идти (got {why})")
    check(refused(lambda: normalize_agent_proxy_route({**POOL_PORT, "kind": " SERVICE "})) is not None,
          "тот же вид в другом регистре и с пробелами — тоже отказ")
    client = normalize_agent_proxy_route({**CLIENT, "routerId": "router:default"})
    check(client["kind"] == "consumer" and client["routerId"] == "",
          "клиент входа без маршрутизатора, даже если его прислали")
    agent = normalize_agent_proxy_route({"port": 23001, "label": "agent"})
    check(agent["kind"] == "" and agent["routerId"] == "router:default",
          "negative: порт агента без вида — как был, маршрутизатор по умолчанию")
    odd = normalize_agent_proxy_route({"port": 23003, "label": "app", "kind": "app"})
    check(odd["kind"] == "" and odd["routerId"] == "router:default",
          "as-is: незнакомый вид читается как порт агента — так было и до удаления")
    reading = pc.load_agent_proxy_config({"routes": [dict(AGENT), dict(POOL_PORT)], "routers": []})
    check([r["port"] for r in reading["routes"]] == [23001],
          "чтение файла проходит мимо своего порта пула — остальные маршруты на месте")
    Path(AGENT_PROXY_CONFIG_FILE).write_text(json.dumps({"routes": [dict(AGENT)], "routers": []}))
    why = refused(lambda: pc.save_agent_proxy_config([dict(AGENT), dict(POOL_PORT)]))
    stored = [r["port"] for r in json.loads(Path(AGENT_PROXY_CONFIG_FILE).read_text())["routes"]]
    check(why is not None and why[0] == 400 and stored == [23001],
          f"сохранение, которое возвращает свой порт пула (старая вкладка), отклонено, файл не тронут (got {why}, {stored})")


def test_proxy_serves_none():
    print("прокси не открывает на нём слушателя:")
    check(Path(PROXY_CONFIG_FILE) == Path(AGENT_PROXY_CONFIG_FILE), "прокси и контроллер читают один файл")
    try:
        proxy_config.normalize_route(dict(POOL_PORT))
        raised = False
    except ValueError:
        raised = True
    check(raised, "маршрут вида service — ValueError, и каждый читатель прокси его пропускает")
    Path(AGENT_PROXY_CONFIG_FILE).write_text(json.dumps({"routes": [dict(AGENT), dict(POOL_PORT), dict(CLIENT)]}))
    routes = proxy_config.load_enabled_routes()
    ports = [r["port"] for r in routes if not r.get("portClosed")]   # the choice caravan/proxy/listeners.py makes
    check(ports == [23001] and 23005 in [r["port"] for r in routes],
          f"слушатель — только у порта агента; свой порт пула пропущен, клиент входа без порта (got {ports})")
    check(proxy_config.live_route_for_port(23004) is None and proxy_config.live_route_for_port(23001) is not None,
          "запрос на его номер не находит маршрута")


def test_on_the_file():
    print("на настоящем файле — один раз:")
    Path(AGENT_PROXY_CONFIG_FILE).write_text(json.dumps({"routes": [dict(AGENT), dict(POOL_PORT)], "routers": []}))
    got = PoolPortsRetired().migrate()
    stored = json.loads(Path(AGENT_PROXY_CONFIG_FILE).read_text())
    check(got == [{"port": 23004, "label": "bridge Standart", "pool": "sol"}]
          and [r.get("port") for r in stored["routes"]] == [23001],
          f"порт закрыт в файле, агент остался (got {got})")
    check(PoolPortsRetired().migrate() is None, "negative: второй старт — закрывать нечего")


def main():
    for fn in (test_the_step, test_controller_takes_none_in, test_proxy_serves_none, test_on_the_file):
        fn()
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("pool ports OK: своих портов у пулов нет — все входят по одному адресу со своим ключом")
    return 0


if __name__ == "__main__":
    sys.exit(main())
