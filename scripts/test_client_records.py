#!/usr/bin/env python3
"""Snapshot of a client's record and its proxy — before management moves onto the page.

Today a client appears ONLY from the scout's heartbeat, and its proxy only
from provisioning. The page creates nothing. The snapshot pins this as-is, so
the transition has something to check against: what provisioning writes,
what it never writes, what survives a client going silent, and what
disappears only through explicit deletion.

The VALUE is pinned. The ABSENCE of what will appear later is pinned
separately: provisioning never creates fallback roles, there's no context
window in the record, there's no way to create a client without a heartbeat.
These aren't nitpicks — they are exactly the spots the new code will land
on, and the snapshot must turn red once they change.

Run: python3 scripts/test_client_records.py
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


import caravan.admin.fleet_clients as fc  # noqa: E402


def harness(assignments=None, routes=None, clients=None, hosts=None):
    """The module's collaborators pointed at in-memory state.

    The module reaches its collaborators through module-level globals rather
    than an injected object, so they are pointed at dicts and lists here.
    """
    store = {"assignments": dict(assignments or {}), "clients": dict(clients or {}),
             "hosts": dict(hosts or {})}
    routes = list(routes or [])
    fc.topology_store = lambda: store
    fc.load_agent_proxy_config = lambda: {"routes": list(routes), "policy": {},
                                          "routers": [], "stopRequests": []}
    fc.normalize_agent_proxy_policy = lambda _p: {}
    fc.normalize_routers = lambda _r, _routes: []
    fc.write_agent_proxy_payload = lambda payload: routes.__setitem__(slice(None), payload["routes"])
    fc.save_admin_state = lambda: None
    fc.restart_agent_proxy = lambda **kw: None
    return store, routes




def test_delete_is_explicit():
    print("удаление — только явное:")
    store, routes = harness(clients={"client-a": {"id": "client-a"}},
                            assignments={"client-a": {"agentUrl": "", "assignments": []}})
    fc.topology_client_delete({"clientId": "client-a"})
    check("client-a" not in store["clients"], "клиент удалён")
    check("client-a" not in store["assignments"], "и его назначения вместе с ним")
    store2, _r = harness(clients={"client-a": {"id": "client-a"}})
    try:
        fc.topology_client_delete({"clientId": "nope"})
        check(False, "удаление несуществующего должно быть ошибкой")
    except Exception as exc:
        check(getattr(exc, "status", None) == 404 or "not found" in str(exc),
              f"удаление несуществующего — 404, а не тихий успех (got {exc!r})")


def test_staleness_is_a_display_state():
    print("живость машины — состояние показа, а не существования:")
    now = int(time.time())
    store, _r = harness(hosts={
        "fresh": {"id": "fresh", "name": "F", "lastSeen": now},
        "silent": {"id": "silent", "name": "S", "lastSeen": now - fc.HOST_REPORT_TTL - 60},
        "never": {"id": "never", "name": "N"},
    })
    rows = {r["id"]: r for r in fc.topology_hosts()}
    check(len(rows) == 3, f"молчащие машины остаются в списке (got {len(rows)})")
    check(rows["fresh"]["state"] == "online", "свежая — online")
    check(rows["silent"]["state"] == "stale", "замолчавшая — stale, но не удалена")
    check(rows["never"]["state"] == "stale" and rows["never"]["ageSeconds"] is None,
          "ни разу не отвечавшая — stale и возраст неизвестен (не ноль)")
    check(all("state" not in h and "ageSeconds" not in h for h in store["hosts"].values()),
          "negative: живость считается при чтении и в документ не пишется — записанное «online» устаревает сразу")



def test_normalizer_rebuilds_the_row():
    """Куда бы ни легла новая настройка, её обязан НАЗВАТЬ нормализатор.

    normalize_topology_assignment пересобирает запись с нуля: поле, которого он
    не знает, исчезает при следующем сохранении. Так уже было — флаг `manual`
    пришлось называть отдельно, и комментарий в коде объясняет почему. Пин
    закрепляет обе половины, чтобы Ф2 не положила настройку туда, где она
    молча испарится.
    """
    from caravan.admin.topology import normalize_topology_assignment as norm
    print("нормализатор назначения:")
    out = norm({"agentId": "a", "routes": [
        {"role": "primary", "proxyId": "skynet:proxy:23001", "endpoint": "http://h:23001/v1",
         "contextLength": 131072, "contextAuto": True, "whatever": 1}]})
    route = out["routes"][0]
    check(sorted(route.keys()) == ["contextAuto", "contextLength", "endpoint", "proxyId", "role"],
          f"переживают ровно те поля, что НАЗВАНЫ классом (got {sorted(route.keys())})")
    check("whatever" not in route,
          "а ключ, которого класс не знает, по-прежнему исчезает — правило не ослабло")
    check(sorted(out.keys()) == ["agentId", "routes"],
          f"и на уровне агента остаются только два (got {sorted(out.keys())})")
    dropped = norm({"agentId": "a", "manual": True, "routes": [
        {"role": "primary", "endpoint": "http://h:1/v1"}]})
    check("manual" not in dropped,
          "старая пометка `manual` больше не названа классом (ушла вместе с провижинингом) — "
          "при сохранении она исчезает, как любой неизвестный ключ")
    # The default role and required fields are also part of the record's shape.
    dflt = norm({"agentId": "a", "routes": [{"endpoint": "http://h:1/v1"}]})
    check(dflt["routes"][0]["role"] == "primary" and dflt["routes"][0]["proxyId"] == "",
          "без роли — primary; без proxyId — пустая строка, а не отсутствие ключа")
    for bad, why in ((({"agentId": "", "routes": []}), "пустой agentId"),
                     (({"agentId": "a", "routes": [{"role": "primary"}]}), "маршрут без endpoint"),
                     (({"agentId": "a", "routes": [{"role": "p", "endpoint": "e"},
                                                   {"role": "p", "endpoint": "e2"}]}), "две одинаковые роли")):
        try:
            norm(bad)
            check(False, f"{why} должен быть отказом")
        except Exception as exc:
            check(getattr(exc, "status", None) == 400, f"{why} — отказ 400 (got {exc!r})")


def _topology_harness(store, routes):
    """The same trick for caravan.admin.topology: collaborators are module-level."""
    import caravan.admin.topology as T
    T.topology_store = lambda: store
    T.load_agent_proxy_config = lambda: {"routes": [{"port": p} for p in routes]}
    T.save_admin_state = lambda: None
    T.post_json = lambda *a, **kw: {"ok": True}
    return T


def test_manual_client_is_an_ordinary_client():
    print("клиент, заведённый руками:")
    store, _routes = harness()
    row = fc.topology_client_create({"hostId": "box-a", "ip": "10.0.0.9"})
    check(row["id"] == "box-a" and row["name"] == "box-a",
          "имя по умолчанию — сам id")
    check("manual" not in row, "пометки «заведён руками» нет: руками заведён каждый клиент, отличать не от кого")
    agents = row.get("agents") or []
    check(len(agents) == 1 and agents[0].get("id") == "box-a" and agents[0].get("name") == "box-a"
          and "manual" not in agents[0],
          "вместе с клиентом заведён его первый агент с тем же именем — карточка появляется сразу, не заголовок")
    check(not (agents[0].get("routes") or []), "у первого агента нет маршрутов: порты назначает оператор")
    check("lastSeen" not in row,
          "lastSeen НЕ выдуман: он значит «отвечал вот тогда», а клиент ещё не отвечал")
    check(store["clients"]["box-a"] is row, "запись легла в документ контроллера")
    named = fc.topology_client_create({"hostId": "box-b", "name": "  Кухня  "})
    check(named["name"] == "Кухня" and "ip" not in named,
          "имя обрезается; поля, которых не дали, не выдумываются")
    check((named.get("agents") or [{}])[0].get("name") == "Кухня" and named["agents"][0].get("id") == "box-b",
          "первый агент носит показанное имя клиента, а id — id клиента")
    # And the same list, the way the board sees it: a client has no liveness
    # of its own — no report speaks for it.
    rows = {r["id"]: r for r in fc.topology_clients()}
    check("state" not in rows["box-a"] and "ageSeconds" not in rows["box-a"],
          "у клиента нет живости от отчёта — ни online, ни stale: работает ли он, показывает трафик его агентов")
    probed = fc.topology_client_create({"hostId": "box-c", "agentUrl": "http://10.0.0.9:8092"})
    check("agentUrl" not in probed,
          "negative: адрес скаута клиенту не записывается — это сведение о машине, его приносит её отчёт")


def test_manual_client_id_rules():
    print("правило про id — одно на оба пути:")
    from caravan.domain.client import FleetClient
    store, _routes = harness()
    for bad in ("controller", "CONTROLLER", "Controller", "skynet", "SkyNet"):
        try:
            fc.topology_client_create({"hostId": bad})
            check(False, f"id {bad!r} должен быть отвергнут")
        except Exception as exc:
            check(getattr(exc, "status", None) == 400 and "reserved" in str(exc),
                  f"id {bad!r} отвергнут как зарезервированный")
    try:
        fc.topology_client_create({"hostId": "   "})
        check(False, "пустой id должен быть отвергнут")
    except Exception as exc:
        check(getattr(exc, "status", None) == 400, "пустой id — отказ 400")
    fc.topology_client_create({"hostId": "dup"})
    try:
        fc.topology_client_create({"hostId": "dup"})
        check(False, "повтор должен быть отвергнут")
    except Exception as exc:
        check(getattr(exc, "status", None) == 409,
              f"повторный id — 409, а не тихая перезапись (got {exc!r})")
    check(FleetClient.validate_id("  box  ") == "box", "id обрезается по краям")


def test_report_changes_only_the_machine():
    """A scout's report is the whole of its host record, and touches no client.

    Since 2026-09-24 a report carries no agents; old scouts still send them,
    and they are not read. The report used to replace ONE combined record, and
    each operator field had to be carried back through it by hand; the agent
    list was lost that way. Now the machine is a host record the scout owns,
    and a client under the same id is the operator's record in its own section.
    """
    print("отчёт скаута — это запись хоста, и только она:")
    client = {"id": "box", "name": "Имя оператора", "ip": "10.0.0.7",
              "agents": [{"id": "a1", "name": "A", "kind": "openclaw"}]}
    store, routes = harness(
        clients={"box": dict(client)},
        hosts={"box": {"id": "box", "name": "old", "firstSeen": 5, "lastSeen": 6, "gpus": []}},
        routes=[{"port": 23001, "label": "A primary"}])
    after = fc.record_host_report({
        "host": {"id": "box", "name": "hostname-says", "ip": "10.0.0.9"}, "agentUrl": "http://10.0.0.9:8092",
        "gpus": [{"index": "0", "name": "GPU"}], "platform": "linux",
        "agents": [{"id": "a1", "name": "renamed", "runtimeDetected": True}, {"id": "new", "name": "N"}],
        "candidates": [{"machine": "agent-y"}], "assignments": [{"agentId": "new"}],
        "applyStatus": {"state": "error"}})
    check(store["clients"]["box"] == client,
          "запись клиента не тронута ни одним полем: ни агенты, ни имя, ни адрес")
    host = store["hosts"]["box"]
    check(host["gpus"] == [{"index": "0", "name": "GPU"}] and host["platform"] == "linux"
          and host["agentUrl"] == "http://10.0.0.9:8092" and host["ip"] == "10.0.0.9"
          and host["name"] == "hostname-says",
          "запись хоста — то, что сказал отчёт")
    check(host["firstSeen"] == 5, "первое появление машины не сдвинуто отчётом")
    check(host.get("scoutVersion") == "",
          "negative: скаут 1.x версию не называет — в записи пусто, а не выдуманный номер")
    after2 = fc.record_host_report({"host": {"id": "box", "name": "h"}, "scoutVersion": " 2.0.0 ", "agentUrl": "u"})
    check(store["hosts"]["box"].get("scoutVersion") == "2.0.0" and after2.get("scoutVersion") == "2.0.0",
          "скаут 2.0 называет свою версию — запись хоста её хранит")
    check(all(k not in host for k in ("agents", "candidates", "assignments", "applyStatus", "state")),
          f"ни агентов, ни находок, ни назначений, ни статуса применения, ни записанной живости (got {sorted(host)})")
    check(routes == [{"port": 23001, "label": "A primary"}] and store["assignments"] == {},
          "ни порта, ни строки назначений отчёт не создаёт")
    check(after == host, "ответ пульсу — запись хоста")
    fresh = fc.record_host_report({"host": {"id": "box-new"}, "agents": [{"id": "x", "name": "X"}]})
    check("box-new" in store["hosts"] and "box-new" not in store["clients"] and "agents" not in fresh,
          "negative: новая машина — это новый хост, а не клиент: клиента заводят руками")


def test_new_port_comes_from_the_agent_base():
    """«＋ New port» without a number: the next odd port from the agent base.

    The +1 neighbour must be free too — it is where a fallback's "New port"
    goes (fallback_port_for). The shared register and the kernel are asked as
    well: a number free on paper and bound in fact fails three steps later.
    """
    import caravan.admin.proxies_config as pc
    from caravan.admin.paths import AGENT_PROXY_BASE_PORT as BASE
    print("порт для «＋ New port»:")
    taken, listening = set(), set()
    # Stubbed for this test only: a stub that outlives its test makes the next
    # one depend on run order.
    _saved = pc._all_taken_ports, pc.port_is_listening
    pc._all_taken_ports = lambda routes=None: set(taken)
    pc.port_is_listening = lambda port: port in listening
    try:
        _check_agent_port_steps(pc, BASE, taken, listening)
    finally:
        pc._all_taken_ports, pc.port_is_listening = _saved


def _check_agent_port_steps(pc, BASE, taken, listening):
    check(pc._next_agent_port(set()) == BASE, f"пусто — сама база {BASE}")
    check(pc._next_agent_port({BASE}) == BASE + 2, "база занята маршрутом — следующий нечётный шаг")
    check(pc._next_agent_port({BASE + 1}) == BASE + 2, "занят сосед +1 — тоже шаг: сосед нужен для fallback")
    taken.add(BASE + 2)
    check(pc._next_agent_port({BASE}) == BASE + 4, "общий реестр (ячейки, исключения) тоже считается")
    listening.add(BASE + 4)
    check(pc._next_agent_port({BASE}) == BASE + 6, "и ядро: порт, который уже слушают, не выдаётся")
    taken.clear(); listening.clear()
    check(pc._next_agent_port({BASE, BASE + 2}) == BASE + 4, "negative: шаг ровно два — чётные не выдаются")


def test_bind_writes_the_role_it_was_given():
    print("ручная привязка по ролям:")
    store = {"assignments": {}, "clients": {"h": {"id": "h", "agents": [{"id": "a"}]}}}
    T = _topology_harness(store, [23001, 23002])
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23001, "role": "primary"})
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23002, "role": "fallback"})
    row = store["assignments"]["h"]["assignments"][0]
    check([(r["role"], r["proxyId"]) for r in row["routes"]]
          == [("primary", "skynet:proxy:23001"), ("fallback", "skynet:proxy:23002")],
          f"обе роли записаны своими портами (got {row['routes']})")
    check("manual" not in row, "привязка не ставит пометку «руками»: иначе порты не выбираются")
    check(all(r["endpoint"].endswith("/v1") for r in row["routes"]),
          "endpoint собран классом, а не переписан на месте")
    # Binding the same role again REPLACES it, rather than adding a second one.
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23002, "role": "primary"})
    row = store["assignments"]["h"]["assignments"][0]
    check(len(row["routes"]) == 2 and row["routes"][0]["proxyId"] == "skynet:proxy:23002",
          f"перепривязка роли заменяет её маршрут (got {row['routes']})")
    for bad_role in ("middle", "PRIMARY", "", " "):
        try:
            T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23001, "role": bad_role})
            if bad_role.strip():
                check(False, f"роль {bad_role!r} должна быть отвергнута")
        except Exception as exc:
            check(getattr(exc, "status", None) == 400, f"роль {bad_role!r} — отказ 400")
    try:
        T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 29999, "role": "primary"})
        check(False, "порт без маршрута должен быть отвергнут")
    except Exception as exc:
        check("no proxy route" in str(exc), f"порт без маршрута — внятный отказ (got {exc!r})")
    # With no port there is nothing to return to: "automatic" went with provisioning.
    try:
        T.bind_agent_to_proxy({"hostId": "h", "agentId": "a"})
        refused = None
    except Exception as exc:
        refused = getattr(exc, "status", None)
    check(refused == 400, f"привязка без порта — отказ 400, а не «назад к автомату», которого больше нет (got {refused})")
    check(len(store["assignments"]["h"]["assignments"][0]["routes"]) == 2,
          "и отказ ничего не тронул: обе роли на месте")


def test_agent_added_by_hand():
    """Агента клиенту можно добавить руками — и он это переживает.

    Клиента завести было можно, а агента ему — нечем: в карточке ручного
    клиента жили только «переименовать» и «удалить», поэтому назначить прокси
    было некому. Запись существовала и настраиваться не могла.

    Отчёт скаута агентов больше не несёт (2026-09-24), поэтому добавленный
    руками живёт, пока его не удалят: ни пометки, ни защиты от отчёта ему не
    нужно.
    """
    print("агент, добавленный руками:")
    from caravan.domain.client import FleetClient
    store, _routes = harness(clients={"box-a": FleetClient.new("box-a", name="A")})
    fc.topology_store = lambda: store

    row = fc.topology_client_add_agent({"hostId": "box-a", "agentId": "  ag-1  ", "name": " Один "})
    agents = store["clients"]["box-a"]["agents"]
    check([a["id"] for a in agents] == ["ag-1"], f"агент добавлен, id обрезан (got {agents!r})")
    check("manual" not in agents[0], "пометки «ручной» нет — отчёт агентов не трогает, защищать не от чего")
    check(agents[0].get("name") == "Один", f"имя обрезано (got {agents[0].get('name')!r})")
    check(row.get("id") == "ag-1", f"ответ называет заведённого агента (got {row!r})")

    # NEGATIVE: an empty id and a duplicate are refusals, not silent no-ops.
    for bad in ("", "   "):
        try:
            fc.topology_client_add_agent({"hostId": "box-a", "agentId": bad})
            check(False, f"пустой id ({bad!r}) должен быть отказом")
        except Exception as exc:
            check(getattr(exc, "status", None) == 400, f"пустой id — 400 (got {exc!r})")
    try:
        fc.topology_client_add_agent({"hostId": "box-a", "agentId": "ag-1"})
        check(False, "дубль должен быть отказом")
    except Exception as exc:
        check(getattr(exc, "status", None) == 409, f"дубль — 409 (got {exc!r})")
    try:
        fc.topology_client_add_agent({"hostId": "nobody", "agentId": "x"})
        check(False, "клиента нет — отказ")
    except Exception as exc:
        check(getattr(exc, "status", None) == 404, f"неизвестный клиент — 404 (got {exc!r})")
    check(len(store["clients"]["box-a"]["agents"]) == 1, "ни один отказ ничего не записал")

    # And the main point: the scout's report doesn't erase it.
    fc.client_aliases = lambda: {}
    fc.record_host_report({"host": {"id": "box-a", "name": "A"},
                               "agents": [{"id": "reported", "name": "R"}]})
    ids = sorted(a["id"] for a in store["clients"]["box-a"]["agents"])
    check(ids == ["ag-1"],
          f"ручной агент пережил отчёт, а названный отчётом «reported» не добавился — у ручного клиента "
          f"агентов заводят руками (got {ids})")
    # NEGATIVE: a report that names no agents at all takes none away.
    fc.record_host_report({"host": {"id": "box-a", "name": "A"}, "agents": []})
    ids = sorted(a["id"] for a in store["clients"]["box-a"]["agents"])
    check(ids == ["ag-1"], f"отчёт без агентов никого не убирает (got {ids})")


def test_new_port_for_a_fallback_is_the_neighbour():
    """A fallback's new port is primary's neighbor, and it lands on ITS OWN role.

    The "mint a port" endpoint used to bind it with no role, meaning always
    onto primary: the operator asked for a second port for the agent, and
    got the working one overwritten instead. And the number it picked was
    "next free", even though a +1 gap is deliberately left next to every
    primary — the very one left over from retired pairs.
    """
    print("новый порт для фолбэка:")
    import caravan.admin.proxies_config as pc
    store = {"assignments": {}, "clients": {"h": {"id": "h", "agents": [{"id": "a"}, {"id": "b"}]}}}
    T = _topology_harness(store, [23001, 23002])
    fc.topology_store = lambda: store
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23001, "role": "primary"})

    port = fc.fallback_port_for(store["assignments"]["h"]["assignments"][0])
    check(port == 23002, f"сосед праймари — 23002 (got {port!r})")
    check(port % 2 == 0, "и он чётный: нечётные заняты праймари")

    # NEGATIVE: with no primary there's no neighbor; a taken neighbor is never offered.
    check(fc.fallback_port_for({"agentId": "b", "routes": []}) is None,
          "нет праймари — соседа не существует, а не «ноль»")
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "b", "port": 23002, "role": "primary"})
    check(fc.fallback_port_for(store["assignments"]["h"]["assignments"][0]) is None,
          "сосед уже занят другим агентом — предлагать его нельзя")


def test_route_can_be_removed():
    """A role can be removed. The port keeps listening while it happens."""
    print("удаление роли маршрута:")
    store = {"assignments": {"h": {"agentUrl": "", "assignments": [
        {"agentId": "a", "manual": True, "routes": [
            {"role": "primary", "proxyId": "skynet:proxy:23001", "endpoint": "http://x:23001/v1",
             "contextLength": 8192},
            {"role": "fallback", "proxyId": "skynet:proxy:23002", "endpoint": "http://x:23002/v1"}]}]}},
        "clients": {"h": {"id": "h", "agents": [{"id": "a"}, {"id": "b"}]}}}
    T = _topology_harness(store, [23001, 23002])
    fc.topology_store = lambda: store
    row = lambda: store["assignments"]["h"]["assignments"][0]

    T.remove_agent_route({"hostId": "h", "agentId": "a", "role": "fallback"})
    check([r["role"] for r in row()["routes"]] == ["primary"],
          f"фолбэк убран, праймари цел (got {row()['routes']})")
    check(row()["routes"][0].get("contextLength") == 8192,
          "и настройки уцелевшей роли не тронуты")
    # The port is now free — it can be given to another agent.
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "b", "port": 23002, "role": "primary"})
    check(any(r["proxyId"] == "skynet:proxy:23002"
              for r in store["assignments"]["h"]["assignments"][1]["routes"]),
          "освободившийся порт достаётся другому агенту — вот чего не хватало «отвязке»")
    # NEGATIVE: a nonexistent role and an unknown agent are both refusals.
    for payload, code in (({"hostId": "h", "agentId": "a", "role": "fallback"}, 404),
                          ({"hostId": "h", "agentId": "nobody", "role": "primary"}, 404),
                          ({"hostId": "h", "agentId": "a"}, 400)):
        try:
            T.remove_agent_route(payload)
            check(False, f"{payload!r} должен быть отказом")
        except Exception as exc:
            check(getattr(exc, "status", None) == code, f"{payload.get('role') or 'без роли'} — {code} (got {exc!r})")
    check([r["role"] for r in row()["routes"]] == ["primary"], "ни один отказ ничего не удалил")
    # Removing the last role is allowed: the agent ends up with no routes, not gone.
    T.remove_agent_route({"hostId": "h", "agentId": "a", "role": "primary"})
    check(row()["routes"] == [] and row()["agentId"] == "a",
          f"агент без маршрутов остаётся записью (got {row()!r})")


def test_agent_alias_survives_the_report():
    """Имя блока агента — псевдоним, а не правка записи.

    Отчёт скаута заменяет список агентов ЦЕЛИКОМ, поэтому правка внутри записи
    держалась бы до первого опроса и исчезала молча. Псевдоним живёт рядом и
    применяется при чтении.
    """
    print("переименование агента:")
    from caravan.domain.client import FleetClient
    store, _routes = harness(clients={"box-a": dict(FleetClient.new("box-a", name="A"),
                                                    agents=[{"id": "ag-1", "name": "ag-1"}])})
    fc.topology_store = lambda: store
    fc.client_aliases = lambda: {}

    fc.set_topology_agent_alias("box-a", "ag-1", "  Кухонный  ")
    rows = {r["id"]: r for r in fc.topology_clients()}
    agent = rows["box-a"]["agents"][0]
    check(agent["name"] == "Кухонный", f"псевдоним показывается вместо имени (got {agent['name']!r})")
    check(agent.get("reportedName") == "ag-1",
          f"а как агент зовёт себя сам — рядом, не потеряно (got {agent.get('reportedName')!r})")
    check(store["clients"]["box-a"]["agents"][0]["name"] == "ag-1",
          "сама ЗАПИСЬ не тронута — иначе отчёт её перезапишет")

    # A scout report arrives and does NOT cancel the alias.
    fc.record_host_report({"host": {"id": "box-a", "name": "A"},
                               "agents": [{"id": "ag-1", "name": "ag-1"}]})
    rows = {r["id"]: r for r in fc.topology_clients()}
    check(rows["box-a"]["agents"][0]["name"] == "Кухонный",
          "псевдоним пережил отчёт")

    # Empty clears it: the name the agent calls itself is shown again.
    fc.set_topology_agent_alias("box-a", "ag-1", "   ")
    rows = {r["id"]: r for r in fc.topology_clients()}
    check(rows["box-a"]["agents"][0]["name"] == "ag-1", "пусто снимает псевдоним")
    check("reportedName" not in rows["box-a"]["agents"][0],
          "и лишнего поля не остаётся — псевдонима нет, рассказывать нечего")
    for bad in (("", "ag-1"), ("box-a", "")):
        try:
            fc.set_topology_agent_alias(bad[0], bad[1], "X")
            check(False, f"пустой ключ {bad!r} должен быть отказом")
        except Exception as exc:
            check(getattr(exc, "status", None) == 400, f"пустой ключ — 400 (got {exc!r})")


def test_model_name_is_per_role():
    """The name a port advertises its model under — on a SINGLE agent's role."""
    print("имя модели на маршруте:")
    store = {"assignments": {"h": {"agentUrl": "", "assignments": [
        {"agentId": "a", "routes": [
            {"role": "primary", "proxyId": "skynet:proxy:23001", "endpoint": "http://x:23001/v1"},
            {"role": "fallback", "proxyId": "skynet:proxy:23002", "endpoint": "http://x:23002/v1"}]}]}},
        "clients": {}}
    T = _topology_harness(store, [23001, 23002])
    fc.topology_store = lambda: store
    routes = lambda: store["assignments"]["h"]["assignments"][0]["routes"]

    T.set_agent_route_model({"hostId": "h", "agentId": "a", "role": "primary",
                             "modelName": "  main-model  "})
    check(routes()[0].get("modelName") == "main-model", f"имя записано обрезанным (got {routes()[0]!r})")
    check("modelName" not in routes()[1], "соседняя роль не тронута")
    # Clearing: empty means the upstream's name is published, the key VANISHES.
    T.set_agent_route_model({"hostId": "h", "agentId": "a", "role": "primary", "modelName": "   "})
    check("modelName" not in routes()[0], f"пусто СНИМАЕТ имя, а не пишет пустую строку (got {routes()[0]!r})")
    # The window and the name don't interfere with each other.
    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "primary", "contextLength": 8192})
    T.set_agent_route_model({"hostId": "h", "agentId": "a", "role": "primary", "modelName": "main-model"})
    check(routes()[0].get("contextLength") == 8192 and routes()[0].get("modelName") == "main-model",
          f"имя и окно живут вместе — правка одного не стирает другое (got {routes()[0]!r})")
    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "primary", "contextLength": 4096})
    check(routes()[0].get("modelName") == "main-model",
          "правка окна имя не трогает")
    # The lock. Opening it leaves the name sitting there — otherwise closing
    # it again would only be possible by retyping the name; the model's own
    # name is what's in force meanwhile.
    T.set_agent_route_model({"hostId": "h", "agentId": "a", "role": "primary",
                             "modelName": "main-model", "modelNameAuto": True})
    check(routes()[0].get("modelNameAuto") is True and routes()[0].get("modelName") == "main-model",
          f"открытый замок записан, имя лежит рядом (got {routes()[0]!r})")
    check("modelNameAuto" not in routes()[1], "соседняя роль не тронута и замком")
    T.set_agent_route_model({"hostId": "h", "agentId": "a", "role": "primary", "modelName": "main-model"})
    check("modelNameAuto" not in routes()[0],
          f"закрыть замок — ключ ИСЧЕЗАЕТ, а не пишется False (got {routes()[0]!r})")
    # NEGATIVE: nobody ever set a lock — so there isn't one.
    T.set_agent_route_model({"hostId": "h", "agentId": "a", "role": "fallback", "modelName": "other"})
    check("modelNameAuto" not in routes()[1],
          f"замок, которого не ставили, не выдумывается (got {routes()[1]!r})")
    # Refusals are refusals.
    try:
        T.set_agent_route_model({"hostId": "h", "agentId": "a", "role": "fallback2", "modelName": "x"})
        check(False, "роль без маршрута — отказ")
    except Exception as exc:
        check(getattr(exc, "status", None) == 404, f"роль без маршрута — 404 (got {exc!r})")


def test_set_route_names_every_setting():
    """Setting a role's route carries over EVERY setting the incoming route has.

    `set_route` swaps liveness in place and copies the settings that the
    incoming route names. A field it doesn't name silently fails to make the
    trip — the same shape of defect as the four rebuild boundaries, just
    inside a class this time. Checked by value: both what's set and what isn't.
    """
    print("set_route переносит настройки:")
    from caravan.domain.client_proxy import AgentAssignment, ProxyRoute
    a = AgentAssignment.from_raw({"agentId": "a", "routes": [
        {"role": "primary", "proxyId": "skynet:proxy:23001", "endpoint": "http://x:23001/v1",
         "contextLength": 8192, "modelName": "old-name"}]})
    incoming = ProxyRoute(role="primary", proxy_id="skynet:proxy:23002", endpoint="http://x:23002/v1",
                          context_length=4096, context_auto=True,
                          model_name="new-name", model_name_auto=True)
    a.set_route(incoming)
    got = a.to_dict()["routes"][0]
    check(got.get("proxyId") == "skynet:proxy:23002" and got.get("modelName") == "new-name"
          and got.get("modelNameAuto") is True and got.get("contextLength") == 4096
          and got.get("contextAuto") is True,
          f"названные во входящем настройки переезжают все до одной (got {got!r})")
    # NEGATIVE: an incoming route with no settings erases nothing — it only carries liveness.
    b = AgentAssignment.from_raw({"agentId": "a", "routes": [
        {"role": "primary", "proxyId": "skynet:proxy:23001", "endpoint": "http://x:23001/v1",
         "contextLength": 8192, "modelName": "old-name", "modelNameAuto": True}]})
    b.set_route(ProxyRoute.for_port("primary", 23002, "10.0.0.1"))
    got = b.to_dict()["routes"][0]
    check(got.get("modelName") == "old-name" and got.get("modelNameAuto") is True
          and got.get("contextLength") == 8192,
          f"перенос порта настроек не отменяет (got {got!r})")


def test_bind_refuses_a_port_someone_else_holds():
    """One port, one owner.

    The settings copy rides the route BY PORT, so two agents on one port
    isn't "both work" — it's "whichever wrote last erased the first one's
    settings", silently and without a trace. Binding used to check only
    that the port existed at all.
    """
    print("занятость порта при ручной привязке:")
    store = {"assignments": {}, "clients": {"h1": {"id": "h1", "agents": [{"id": "a1"}, {"id": "a2"}]}, "h2": {"id": "h2", "agents": [{"id": "a9"}]}}}
    T = _topology_harness(store, [23001, 23002])
    T.bind_agent_to_proxy({"hostId": "h1", "agentId": "a1", "port": 23001, "role": "primary"})

    before = json.dumps(store["assignments"], sort_keys=True)
    for who in ({"hostId": "h1", "agentId": "a2", "port": 23001, "role": "primary"},
                {"hostId": "h2", "agentId": "a9", "port": 23001, "role": "fallback"}):
        try:
            T.bind_agent_to_proxy(who)
            check(False, f"порт 23001 занят — привязка {who['agentId']} должна быть отказом")
        except Exception as exc:
            check(getattr(exc, "status", None) == 409,
                  f"занятый порт — 409 для {who['agentId']} (got {exc!r})")
    check(json.dumps(store["assignments"], sort_keys=True) == before,
          "отказ ничего не записал — запись владельца не тронута")

    # Negative: an agent's own port and own role are not a conflict.
    T.bind_agent_to_proxy({"hostId": "h1", "agentId": "a1", "port": 23001, "role": "primary"})
    check(store["assignments"]["h1"]["assignments"][0]["routes"][0]["proxyId"] == "skynet:proxy:23001",
          "повторная привязка того же агента на тот же порт — не отказ")
    T.bind_agent_to_proxy({"hostId": "h1", "agentId": "a2", "port": 23002, "role": "primary"})
    check(len(store["assignments"]["h1"]["assignments"]) == 2,
          "свободный порт другому агенту выдаётся как прежде")
    # A bind with no port is refused: "back to automatic" went with
    # provisioning. The port stays with its agent — freeing it is
    # remove_agent_route's job — so giving it to a neighbour is still a refusal.
    try:
        T.bind_agent_to_proxy({"hostId": "h1", "agentId": "a1"})
        refused = None
    except Exception as exc:
        refused = getattr(exc, "status", None)
    check(refused == 400, f"привязка без порта — отказ, а не «вернуть автомату» (got {refused})")
    try:
        T.bind_agent_to_proxy({"hostId": "h1", "agentId": "a2", "port": 23001, "role": "fallback"})
        check(False, "порт всё ещё за прежним агентом — ожидался отказ")
    except Exception as exc:
        check(getattr(exc, "status", None) == 409,
              f"порт освобождает только remove_agent_route (got {exc!r})")


def test_saving_the_window_reaches_the_port_without_a_heartbeat():
    """Настройку сохранили — и она обязана уехать на маршрут ТУТ ЖЕ.

    Мост «назначение → маршрут» звался только из обработки сердцебиения. У
    клиента, заведённого руками, сердцебиения нет и не будет: он существует и
    настроен, но отзываться не обязан. Значит его окно не доезжало до порта
    никогда, а у живого клиента — доезжало когда-нибудь потом, и оператор
    видел на доске одно, а порт публиковал другое.
    """
    print("сохранение настройки без сердцебиения:")
    store = {"assignments": {"h": {"agentUrl": "", "assignments": [
        {"agentId": "a", "routes": [{"role": "primary", "proxyId": "skynet:proxy:23001",
                                     "endpoint": "http://x:23001/v1"}]}]}},
        "clients": {"h": {"id": "h", "name": "H", "agents": [{"id": "a"}]}}}
    live = [{"port": 23001, "label": "H primary", "clientId": "h", "role": "primary"}]
    T = _topology_harness(store, [23001])
    fc.topology_store = lambda: store
    fc.read_agent_proxy_payload = lambda: {"routes": live}
    fc.write_agent_proxy_payload = lambda payload: None
    fc.restart_agent_proxy = lambda **kw: None

    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "primary",
                               "contextLength": 8192})
    check(live[0].get("contextLength") == 8192,
          f"сохранил — копия на маршруте получила окно сразу (got {live[0].get('contextLength')!r})")
    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "primary",
                               "contextAuto": True})
    check(live[0].get("contextAuto") is True and "contextLength" not in live[0],
          f"переключил на «от модели» — копия следует за настройкой (got {live[0]!r})")
    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "primary"})
    check("contextAuto" not in live[0] and "contextLength" not in live[0],
          f"снял всё — копия тоже чистая, а не с прошлым числом (got {live[0]!r})")


def test_bridge_carries_the_window_to_the_route():
    """The bridge from an assignment to its copy on the route.

    The proxy process never sees the controller's document — it only reads
    its own files — so the number travels to it as a copy. This bridge
    could have been deleted entirely and NOTHING would have turned red: the
    guard saw field names sitting in a neighboring dict of the same function
    and counted them as named. Verified by hand on a gutted tree. Now the
    bridge is pinned by value.
    """
    print("мост «назначение → маршрут»:")
    def _bridge_harness(assignments, routes, clients):
        # The bridge reads read_agent_proxy_payload, not
        # load_agent_proxy_config: the first version of these pins stubbed
        # the wrong function and turned the WHOLE tree red. An unexpected red
        # — suspect the check itself first.
        store, live = harness(assignments=assignments, routes=routes, clients=clients)
        fc.read_agent_proxy_payload = lambda: {"routes": live}
        return store, live

    ASG = lambda **kw: {"client-a": {"assignments": [
        {"agentId": "agent-a", "routes": [dict(
            {"role": "primary", "proxyId": "skynet:proxy:23001",
             "endpoint": "http://10.0.0.1:23001/v1"}, **kw)]}]}}

    # (a) The operator set a window — the copy gets it.
    store, routes = _bridge_harness(ASG(contextLength=8192),
                                    [{"port": 23001, "label": "old", "clientId": "client-a"}],
                                    {"client-a": {"id": "client-a", "name": "A", "agents": []}})
    changed = fc.reconcile_proxy_metadata()
    check(changed is True and routes[0].get("contextLength") == 8192,
          f"заданное окно доезжает до маршрута (changed={changed}, got {routes[0].get('contextLength')!r})")

    # (b) The operator CLEARED the setting — the copy must lose it too, not keep it.
    store, routes = _bridge_harness(ASG(),
                                    [{"port": 23001, "label": "l", "clientId": "client-a",
                                      "contextLength": 8192}],
                                    {"client-a": {"id": "client-a", "name": "A", "agents": []}})
    changed = fc.reconcile_proxy_metadata()
    check(changed is True and "contextLength" not in routes[0],
          f"снятая настройка снимается и с копии (got {routes[0]!r})")

    # (c) The "from the model" checkbox rides the same bridge.
    store, routes = _bridge_harness(ASG(contextAuto=True),
                                    [{"port": 23001, "label": "l", "clientId": "client-a"}],
                                    {"client-a": {"id": "client-a", "name": "A", "agents": []}})
    fc.reconcile_proxy_metadata()
    check(routes[0].get("contextAuto") is True,
          f"включённая галка доезжает (got {routes[0].get('contextAuto')!r})")

    # (c1) The model name rides the same bridge: without it the port
    # advertises the upstream's name, a client can't find its own id, and
    # falls back to its built-in default.
    store, routes = _bridge_harness(ASG(modelName="main-model"),
                                    [{"port": 23001, "label": "l", "clientId": "client-a"}],
                                    {"client-a": {"id": "client-a", "name": "A", "agents": []}})
    fc.reconcile_proxy_metadata()
    check(routes[0].get("modelName") == "main-model",
          f"заданное имя доезжает до маршрута (got {routes[0].get('modelName')!r})")
    # (c2) The lock rides the same bridge: the proxy reads it from ITS OWN
    # file and never sees the controller's document at all.
    store, routes = _bridge_harness(ASG(modelName="main-model", modelNameAuto=True),
                                    [{"port": 23001, "label": "l", "clientId": "client-a"}],
                                    {"client-a": {"id": "client-a", "name": "A", "agents": []}})
    fc.reconcile_proxy_metadata()
    check(routes[0].get("modelNameAuto") is True and routes[0].get("modelName") == "main-model",
          f"открытый замок доезжает вместе с именем (got {routes[0]!r})")
    store, routes = _bridge_harness(ASG(modelName="main-model"),
                                    [{"port": 23001, "label": "l", "clientId": "client-a",
                                      "modelNameAuto": True}],
                                    {"client-a": {"id": "client-a", "name": "A", "agents": []}})
    fc.reconcile_proxy_metadata()
    check("modelNameAuto" not in routes[0],
          f"закрытый назад замок снимается и с копии (got {routes[0]!r})")
    store, routes = _bridge_harness(ASG(),
                                    [{"port": 23001, "label": "l", "clientId": "client-a",
                                      "modelName": "main-model"}],
                                    {"client-a": {"id": "client-a", "name": "A", "agents": []}})
    fc.reconcile_proxy_metadata()
    check("modelName" not in routes[0],
          f"снятое имя снимается и с копии (got {routes[0]!r})")

    # (c2) An agent got rewired onto a different port. The old route stays
    # alive in the proxy file until the next reconcile — and kept publishing
    # the window of a client that no longer sits on it. The copy has no
    # owner, so there shouldn't be a copy either.
    store, routes = _bridge_harness(
        {"client-a": {"assignments": [
            {"agentId": "agent-a", "routes": [{"role": "primary",
                                               "proxyId": "skynet:proxy:23002",
                                               "endpoint": "http://10.0.0.1:23002/v1",
                                               "contextLength": 4096}]}]}},
        [{"port": 23001, "label": "A primary", "clientId": "client-a", "role": "primary",
          "contextLength": 8192, "contextAuto": True},
         {"port": 23002, "label": "A primary", "clientId": "client-a", "role": "primary"}],
        {"client-a": {"id": "client-a", "name": "A", "agents": []}})
    fc.reconcile_proxy_metadata()
    old_route = next(r for r in routes if r["port"] == 23001)
    new_route = next(r for r in routes if r["port"] == 23002)
    check("contextLength" not in old_route and "contextAuto" not in old_route,
          f"брошенный порт перестаёт публиковать чужое окно (got {old_route!r})")
    check(old_route.get("clientId") == "client-a",
          f"остальное на брошенном маршруте не трогаем — это не его уборка (got {old_route!r})")
    check(new_route.get("contextLength") == 4096,
          f"а новый порт получил настройку (got {new_route.get('contextLength')!r})")

    # (c3) TWO assignments claimed one port. Manual binding rejects this now,
    # but a scout's report doesn't: agents just report what's in their own
    # configs. The bridge is keyed by port, so the "winner" here is
    # arbitrary, and publishing one client's window on another's traffic
    # would be a lie. No owner means no copy: the port falls back to the
    # model's own number, which is honest.
    store, routes = _bridge_harness(
        {"client-a": {"assignments": [
            {"agentId": "agent-a", "routes": [{"role": "primary",
                                               "proxyId": "skynet:proxy:23001",
                                               "endpoint": "http://10.0.0.1:23001/v1",
                                               "contextLength": 4096}]}]},
         "client-b": {"assignments": [
            {"agentId": "agent-b", "routes": [{"role": "primary",
                                               "proxyId": "skynet:proxy:23001",
                                               "endpoint": "http://10.0.0.1:23001/v1",
                                               "contextLength": 8192}]}]}},
        [{"port": 23001, "label": "A primary", "clientId": "client-a", "role": "primary",
          "contextLength": 4096}],
        {"client-a": {"id": "client-a", "name": "A", "agents": []},
         "client-b": {"id": "client-b", "name": "B", "agents": []}})
    fc.reconcile_proxy_metadata()
    check("contextLength" not in routes[0],
          f"спорный порт не публикует ничьё окно (got {routes[0]!r})")
    check(routes[0].get("clientId") == "client-a",
          f"и владельца себе не выдумывает — прежнее поле остаётся (got {routes[0]!r})")

    # (d) NEGATIVE: nothing is set — nothing appears on the route either,
    # and the bridge itself reports no change.
    store, routes = _bridge_harness(ASG(),
                                    [{"port": 23001, "label": "A primary", "clientId": "client-a",
                                      "role": "primary"}],
                                    {"client-a": {"id": "client-a", "name": "A", "agents": []}})
    changed = fc.reconcile_proxy_metadata()
    check("contextLength" not in routes[0] and "contextAuto" not in routes[0],
          f"незаданное не выдумывается на копии (got {routes[0]!r})")
    check(changed is False, f"нечего менять — мост молчит и файл не переписывает (got {changed!r})")


def test_route_context_is_per_consumer():
    print("окно контекста на клиентской прокси-ячейке:")
    from caravan.domain.client_proxy import ProxyRoute
    store = {"assignments": {"h": {"agentUrl": "", "assignments": [
        {"agentId": "a", "routes": [
            {"role": "primary", "proxyId": "skynet:proxy:23001", "endpoint": "http://x:23001/v1"},
            {"role": "fallback", "proxyId": "skynet:proxy:23002", "endpoint": "http://x:23002/v1"}]}]}},
        "clients": {"h": {"id": "h", "agents": [{"id": "a"}]}}}
    T = _topology_harness(store, [23001, 23002])
    routes = lambda: store["assignments"]["h"]["assignments"][0]["routes"]

    check(sorted(routes()[0].keys()) == ["endpoint", "proxyId", "role"],
          "до правки маршрут остаётся трёхключевым — переход не требует миграции")
    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "primary", "contextLength": 131072})
    check(routes()[0].get("contextLength") == 131072, "число оператора записано")
    check("contextAuto" not in routes()[0],
          "галка, которую не ставили, не выдумывается — иначе читалась бы как решение")
    check(sorted(routes()[1].keys()) == ["endpoint", "proxyId", "role"],
          "соседняя роль не тронута — настройка живёт на РОЛИ, а не на агенте")
    # The form sends both fields together, so a missing one means "clear".
    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "primary", "contextAuto": True})
    check(routes()[0].get("contextAuto") is True and "contextLength" not in routes()[0],
          "галка включена, число снято — оба поля задаются вместе")
    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "primary", "contextLength": 0})
    check(sorted(routes()[0].keys()) == ["endpoint", "proxyId", "role"],
          "ноль СНИМАЕТ число, а не задаёт предел в ноль")
    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "fallback", "contextLength": "65536"})
    check(routes()[1].get("contextLength") == 65536, "числовая строка из формы принимается")
    for bad in (-1, "abc", None, False, ""):
        T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "fallback", "contextLength": bad})
        check("contextLength" not in routes()[1], f"contextLength={bad!r} оставляет ключ ОТСУТСТВУЮЩИМ")
    for payload, why, code in (
            ({"hostId": "h", "agentId": "nope", "role": "primary"}, "агент без назначения", 404),
            ({"hostId": "zzz", "agentId": "a", "role": "primary"}, "неизвестный хост", 404),
            ({"hostId": "h", "agentId": "a", "role": "middle"}, "чужая роль", 400),
            ({"hostId": "", "agentId": "a", "role": "primary"}, "пустой хост", 400)):
        try:
            T.set_agent_route_context(payload)
            check(False, f"{why} должен быть отказом")
        except Exception as exc:
            check(getattr(exc, "status", None) == code, f"{why} — отказ {code} (got {exc!r})")
    # A role with no route is also a refusal, not a route silently created into nowhere.
    store["assignments"]["h"]["assignments"].append({"agentId": "b", "routes": []})
    try:
        T.set_agent_route_context({"hostId": "h", "agentId": "b", "role": "primary", "contextLength": 8})
        check(False, "роль без маршрута должна быть отказом")
    except Exception as exc:
        check(getattr(exc, "status", None) == 404, f"роль без маршрута — 404 (got {exc!r})")
    # And the whole reason the field is named in the class: moving the port doesn't cancel the setting.
    T.set_agent_route_context({"hostId": "h", "agentId": "a", "role": "primary", "contextLength": 4096})
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23002, "role": "primary"})
    check(routes()[0].get("contextLength") == 4096 and routes()[0]["proxyId"] == "skynet:proxy:23002",
          "перепривязка порта переставляет ЖИВОСТЬ, настройку не трогая")


def test_the_board_is_told_who_holds_each_port():
    """One reading of ownership, for the bind check and for the board.

    The port picker used to list every port while the server refused any port
    another agent held: on 2026-09-23 all fifteen were held, and every row of
    the menu ended in a 409. Now each proxy reaches the board carrying its
    holders, read by the same function the refusal is decided by.

    The one line in topology_state that hands the reading to _board_proxy is
    checked on the live board, not here: topology_state reaches twenty
    collaborators, and a harness for all of them would test the harness.
    """
    print("кто держит порт — одно чтение для отказа и для доски:")
    store = {"assignments": {}, "clients": {"h1": {"id": "h1", "agents": [{"id": "a1"}]}, "h2": {"id": "h2", "agents": [{"id": "b1"}]}}}
    T = _topology_harness(store, [23001, 23002, 23003])
    T.bind_agent_to_proxy({"hostId": "h1", "agentId": "a1", "port": 23001, "role": "primary"})
    T.bind_agent_to_proxy({"hostId": "h2", "agentId": "b1", "port": 23002, "role": "fallback"})
    held = T._port_holders()
    check(held == {"skynet:proxy:23001": [("h1", "a1", "primary")],
                   "skynet:proxy:23002": [("h2", "b1", "fallback")]},
          f"держатели по порту, со своей ролью, через весь флот (got {held})")
    check("skynet:proxy:23003" not in held, "никем не взятого порта в чтении нет — пустота, а не выдуманный хозяин")

    # as-is: a port held twice (a record from before the one-owner rule) lists
    # both, in stored order — and the refusal still finds the other one.
    store["assignments"]["h3"] = {"assignments": [{"agentId": "c1", "routes": [
        {"role": "primary", "proxyId": "skynet:proxy:23001"}]}]}
    check(T._port_holders()["skynet:proxy:23001"] == [("h1", "a1", "primary"), ("h3", "c1", "primary")],
          "as-is: дважды взятый порт (запись до правила «один хозяин») — оба держателя, в порядке хранения")
    check(T._port_holder(23001, exclude=("h1", "a1")) == ("h3", "c1", "primary"),
          "проверка при привязке по-прежнему видит второго держателя, исключив самого просящего")
    check(T._port_holder(23003) is None, "свободный порт — никто")

    board = T._board_proxy({"port": 23001, "upstreamPort": 8080}, holders=T._port_holders(),
                           last_seen={23001: 1700000000}, routers_by_id={})
    check(board["holders"] == [{"hostId": "h1", "agentId": "a1", "role": "primary"},
                               {"hostId": "h3", "agentId": "c1", "role": "primary"}],
          "порт уходит на доску со всеми держателями — теми же, по которым решается отказ")
    check(board["id"] == "skynet:proxy:23001" and board["endpoint"].endswith(":23001/v1")
          and board["lastRequestAt"] == 1700000000 and board["upstreamId"] == "skynet:llama-server:8080",
          "вынесенная сборка порта даёт те же поля, что давала внутри topology_state")
    free = T._board_proxy({"port": 23003}, holders=T._port_holders(), last_seen={}, routers_by_id={})
    check(free["holders"] == [] and free["lastRequestAt"] == 0,
          "свободный порт — пустой список держателей, а не отсутствующее поле")
    routed = T._board_proxy({"port": 23003, "routerId": "r1"}, holders={}, last_seen={},
                            routers_by_id={"r1": {"outputs": [{"id": "o1", "upstreamPort": 22003, "upstreamHost": "10.0.0.2"}],
                                                  "rules": {"default": "o1"}}})
    check((routed.get("resolvedUpstreamHost"), routed.get("resolvedUpstreamPort")) == ("10.0.0.2", 22003),
          "куда порт идёт на самом деле — по выходу роутера по умолчанию, как прежде")


def test_agent_delete_takes_its_row_and_leaves_its_ports():
    """An agent's ✕: the record and its assignment row go, its ports stay.

    The row used to stay behind, and the agent's ports then showed up on the
    kanban as an orphan with a skull and a second delete. A port is deleted in
    its own window: it takes the port's key and settings with it.
    """
    print("удаление агента: запись и строка назначений уходят, порты остаются:")
    store, routes = harness(
        clients={"box": {"id": "box", "manual": True,
                         "agents": [{"id": "a1", "name": "A"}, {"id": "a2", "name": "B"}]}},
        assignments={"box": {"assignments": [
            {"agentId": "a1", "routes": [{"role": "primary", "proxyId": "skynet:proxy:23001"},
                                         {"role": "fallback", "proxyId": "skynet:proxy:23003"}]},
            {"agentId": "a2", "routes": [{"role": "primary", "proxyId": "skynet:proxy:23003"}]}]}},
        routes=[{"port": 23001, "label": "A primary"}, {"port": 23003, "label": "shared"}])
    before = [dict(r) for r in routes]
    res = fc.topology_client_agent_delete({"clientId": "box", "agentId": "a1"})
    check([a["id"] for a in (store["clients"].get("box") or {}).get("agents") or []] == ["a2"], "агент ушёл из записи")
    check([r["agentId"] for r in (store["assignments"].get("box") or {}).get("assignments") or []] == ["a2"],
          "его строка назначений ушла вместе с ним — сироты на канбане не остаётся")
    check(res["freedPorts"] == [23001],
          f"свободным назван только порт, который больше никто не держит; общий :23003 держит второй агент "
          f"(got {res['freedPorts']})")
    check(routes == before, "сами порты не тронуты: ни один не удалён и не переписан")
    check(((store["assignments"].get("box") or {}).get("assignments") or [{}])[0].get("routes") ==
          [{"role": "primary", "proxyId": "skynet:proxy:23003"}], "строка второго агента цела")
    try:
        fc.topology_client_agent_delete({"clientId": "box", "agentId": "a1"})
        refused = None
    except fc.AppError as exc:
        refused = exc.status
    check(refused == 404, f"negative: повторное удаление — 404, а не тихий успех (got {refused})")
    check(res.get("clientRemoved") is False and "box" in store["clients"],
          "negative: у клиента остался агент — клиент остаётся")

    res = fc.topology_client_agent_delete({"clientId": "box", "agentId": "a2"})
    check(res.get("clientRemoved") is True and "box" not in store["clients"] and "box" not in store["assignments"],
          "defect-history: последний агент уносит клиента и его строку назначений — пустой клиент вставал "
          "на доске строкой-подписью со своим ✕, и её приняли за мусор (2026-09-24)")
    check(res["freedPorts"] == [23003] and routes == before,
          "его порт назван свободным, сами порты не тронуты")


def test_apply_stores_and_calls_no_scout():
    """A bind is stored on the controller, and nothing is sent to the machine.

    The row used to be POSTed to the scout's /api/routing/apply, which rewrote
    each agent's own config — over SSH for the VMs — and restarted it. The
    scout knows nothing of agents now; the operator points an agent at its
    port by hand.
    """
    print("привязка хранится на контроллере, скауту ничего не шлётся:")
    store = {"assignments": {}, "clients": {"h": {"id": "h", "agentUrl": "http://10.0.0.9:8092",
                                                  "agents": [{"id": "a"}]}}}
    T = _topology_harness(store, [23001])
    posted = []
    T.post_json = lambda *a, **kw: posted.append(a) or {"ok": True}
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23001, "role": "primary"})
    check(posted == [], f"на машину со скаутом не ушло ни одного запроса (got {len(posted)})")
    row = store["assignments"]["h"]
    check(sorted(row) == ["assignments", "hostId"],
          f"строка — хост и назначения: ни статуса применения, ни времени «желаемого» (got {sorted(row)})")
    check(row["assignments"][0]["routes"][0]["proxyId"] == "skynet:proxy:23001", "а сама привязка на месте")


def test_a_scouts_address_lives_on_its_host():
    """One reading of a scout's address: the machine's host record.

    There were four copies of the lookup, and one skipped the override an
    assignment row could carry; the override went with the scout's word about
    agents. A client record never carries the address.
    """
    print("адрес скаута — у записи хоста, и только там:")
    from caravan.service.scout import Scout
    from caravan.admin.state import topology as real_topo

    class Topo:
        def __init__(self, hosts):
            self._hosts = hosts
        def hosts(self):
            return self._hosts
    scout = Scout.for_host("m", Topo({"m": {"id": "m", "agentUrl": "http://10.0.0.9:8092/"}}))
    check(scout.agent_url == "http://10.0.0.9:8092", "адрес берётся из отчёта машины, без хвостового /")
    for hosts, status, why in (({}, 404, "машина не отчитывалась"),
                               ({"m": {"id": "m"}}, 400, "отчёт без адреса")):
        try:
            Scout.for_host("m", Topo(hosts))
            got = None
        except fc.AppError as exc:
            got = exc.status
        check(got == status, f"negative: {why} — {status}, а не догадка (got {got})")
    check(callable(getattr(real_topo, "hosts", None)), "у хранилища есть раздел хостов")


def test_the_payload_keeps_machines_and_clients_apart():
    """/api/topology hands the board two lists under one id, never merged rows.

    Until the board read `hosts`, each client row carried its machine's report
    and liveness, and a machine without a client showed as a client with no
    agents — a row whose ✕ could only answer 404. The board reads the machine
    from `hosts` now, and the rows are the records as they are.
    """
    print("ответ доски — машины и клиенты порознь:")
    import caravan.admin.topology as T
    import caravan.admin.cloud_api as cloud_api
    import caravan.admin.status as status
    clients = [{"id": "both", "name": "Client", "ip": "10.0.0.7", "agents": [{"id": "a"}]},
               {"id": "hand", "name": "Hand", "agents": [{"id": "b"}]}]
    hosts = [{"id": "both", "name": "machine", "ip": "10.0.0.9", "gpus": [{"name": "G"}],
              "agentUrl": "u", "state": "online", "ageSeconds": 3},
             {"id": "donor", "name": "Donor", "gpus": [{"name": "G2"}], "state": "stale", "ageSeconds": None}]
    patch = {
        "parse_config": lambda: {},
        "topology_store": lambda: {"assignments": {}, "serverSlots": {}, "clientAliases": {}, "layout": {}},
        "load_agent_proxy_config": lambda: {"routes": [], "routers": [], "policy": {"maxSlots": 1}},
        "_llama_total_slots": lambda: 0,
        "proxy_ports_last_seen": lambda: {},
        "_port_holders": lambda: {},
        "topology_server": lambda _config: {"id": "controller", "name": "Ctl", "llamaServers": []},
        "sync_router_outputs": lambda *a: False,
        "cloud_accounts_state": lambda: [],
        "cloud_blocks_state": lambda: [],
        "topology_clients": lambda: [dict(c) for c in clients],
        "topology_hosts": lambda: [dict(h) for h in hosts],
        "annotate_route_windows": lambda *a: None,
        "topology_nodes": lambda *a: [],
        "cloud_provider_presets_public": lambda: [],
    }
    patch["SCOUT_POLLER"] = T.SCOUT_POLLER
    saved = {k: getattr(T, k) for k in patch}
    saved_cloud, saved_suspect = cloud_api.annotate_cloud_topology, status.llama_crash_suspect
    saved_pull = fc.refresh_hosts_from_scouts
    try:
        for k, v in patch.items():
            setattr(T, k, v)
        cloud_api.annotate_cloud_topology = lambda *a: {"endpoints": {}, "codexClientVersion": {}}
        status.llama_crash_suspect = lambda: None
        payload = T.topology_state(refresh_hosts=False)
        kicks = []
        T.SCOUT_POLLER = type("Poller", (), {"kick": lambda self: kicks.append(1)})()

        def pulled_inline():
            raise AssertionError("the read pulled the scouts itself")
        fc.refresh_hosts_from_scouts = pulled_inline
        try:
            board_read, inline = T.topology_state(), False
        except AssertionError:
            board_read, inline = {}, True
        quiet = len(kicks)
        T.topology_state(refresh_hosts=False)
    finally:
        for k, v in saved.items():
            setattr(T, k, v)
        cloud_api.annotate_cloud_topology, status.llama_crash_suspect = saved_cloud, saved_suspect
        fc.refresh_hosts_from_scouts = saved_pull
    check(payload["clients"] == clients,
          "клиенты — записи оператора как есть: у строки с тем же id, что у машины, нет её карт, адреса скаута и живости")
    check([c["id"] for c in payload["clients"]] == ["both", "hand"],
          "negative: машина без клиента не становится клиентом без агентов — её ✕ мог ответить только 404")
    check(payload["hosts"] == hosts, "машины — отдельным списком, с живостью, посчитанной при чтении")
    check(not inline and board_read.get("clients") == clients and quiet == 1,
          "чтение доски только пинает фоновый опрос скаутов и не опрашивает их само — выключенная машина больше не добавляет 2 с к каждому опросу доски")
    check(len(kicks) == 1, "negative: ответы на действия (refresh_hosts=False) опрос не пинают")


def test_the_pull_keeps_the_scout_version():
    """The background pull maps /api/state into the same record the heartbeat
    writes; a field one of them carries and the other does not would be erased
    every minute by the other. The scout's version travels both ways."""
    print("опрос скаута тоже несёт его версию:")
    store, _r = harness(hosts={"m": {"id": "m", "name": "M", "agentUrl": "http://10.0.0.9:8092", "lastSeen": 1}})
    saved = fc.fetch_json
    try:
        fc.fetch_json = lambda url, timeout=None, headers=None: {
            "host": {"id": "m", "name": "M"}, "scoutVersion": "2.0.0", "llamaUpdate": {"running": True}}
        fc.refresh_hosts_from_scouts()
    finally:
        fc.fetch_json = saved
    host = store["hosts"]["m"]
    check(host.get("scoutVersion") == "2.0.0" and host.get("llamaUpdate") == {"running": True},
          "версия скаута и статус обновления из /api/state — в записи хоста, как из пульса")


def test_bind_refuses_an_agent_the_record_does_not_have():
    """A bind names an agent of the operator's record, or it is refused.

    It used to accept any id: the row it wrote was drawn by nobody, and its
    port read as held — by an agent no screen showed and no ✕ could remove.
    """
    print("привязка — только агента из записи:")
    store = {"assignments": {}, "clients": {"h": {"id": "h", "agents": [{"id": "a"}]}}}
    T = _topology_harness(store, [23001])
    for who, why in (({"hostId": "ghost", "agentId": "a"}, "клиента нет"),
                     ({"hostId": "h", "agentId": "ghost"}, "у клиента нет такого агента")):
        try:
            T.bind_agent_to_proxy({**who, "port": 23001, "role": "primary"})
            status = None
        except fc.AppError as exc:
            status = exc.status
        check(status == 404, f"negative: {why} — 404, а не строка, которую никто не нарисует (got {status})")
    check(store["assignments"] == {}, "отказы ничего не записали")
    try:
        T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23001, "role": "primary"})
        bound = [r.get("agentId") for r in store["assignments"]["h"]["assignments"]]
    except fc.AppError as exc:
        bound = exc.status
    check(bound == ["a"], f"агент из записи привязывается как прежде (got {bound})")


def test_a_cell_of_an_unknown_machine_has_no_address():
    """A cell whose machine nobody can reach — forgotten on the board, or whose
    scout never said its address — gets no address at all, never 127.0.0.1.

    The router output used to fall back to loopback: the cell's traffic went to
    whatever the controller runs on that port. The served-window map keyed it
    under the controller's names and lent that port a window it does not have.
    """
    print("ячейка машины без адреса — без адреса, а не 127.0.0.1:")
    from caravan.admin.proxies_config import _router_local_outputs
    from caravan.admin.topology import _served_windows_by_address
    rows = [{"port": 22001, "isController": True, "clientIp": "", "model": "a.gguf", "ctxServed": 8192},
            {"port": 22011, "isController": False, "isRemote": True, "clientIp": "10.0.0.9", "model": "b.gguf",
             "ctxServed": 4096},
            {"port": 22021, "isController": False, "isRemote": True, "clientIp": "", "model": "c.gguf",
             "ctxServed": 2048}]
    outs = {o["id"]: o for o in _router_local_outputs({"llamaServers": rows})}
    check(sorted(outs) == ["srv:22001", "srv:22011"],
          f"выход есть у ячейки контроллера и у ячейки машины с адресом (got {sorted(outs)})")
    check("srv:22021" not in outs,
          "negative: ячейка машины без адреса — не выход: роутер считает её сервером, который лёг, и вернёт с отчётом")
    check((outs["srv:22001"]["upstreamHost"], outs["srv:22011"]["upstreamHost"]) == ("127.0.0.1", "10.0.0.9"),
          "контроллер — loopback, машина — её адрес")
    served = _served_windows_by_address({"llamaServers": rows})
    check(not any(port == 22021 for _host, port in served),
          f"negative: окно ячейки без адреса не приписано адресам контроллера (got {sorted(served)})")
    check(served.get(("10.0.0.9", 22011)) == 4096 and served.get(("127.0.0.1", 22001)) == 8192,
          "остальные ячейки — под своими адресами, как были")


def test_metrics_read_the_boards_liveness():
    """The online gauge and the node's banner are one rule over one window.

    The gauge counted three minutes while the board counted 45 seconds, and a
    machine could be online on the dashboard and silent on the board at once.
    """
    print("метрика «онлайн» — то же правило, что у доски:")
    import caravan.admin.metrics as M
    now = int(time.time())
    hosts = {"fresh": {"id": "fresh", "lastSeen": now},
             "quiet": {"id": "quiet", "lastSeen": now - 100},
             "gone": {"id": "gone", "lastSeen": now - fc.HOST_REPORT_TTL - 30},
             "never": {"id": "never"}}
    harness(hosts=hosts)
    # Everything the gauge text reads besides the hosts is pointed at values,
    # so the machine the test runs on (a GPU, logs, a config) cannot show up.
    fakes = {"topology_store": lambda: {"hosts": hosts, "serverSlots": {}},
             "systemctl": lambda *a, **kw: {"ok": False},
             "parse_config": lambda: {},
             "models_dir_from_config": lambda _c: ROOT / "no-such-models-dir",
             "gpu_state": lambda: {},
             "agent_proxy_sample": lambda: {},
             "proxy_daily_stats": lambda: {}}
    saved = {k: getattr(M, k) for k in fakes}
    try:
        for k, v in fakes.items():
            setattr(M, k, v)
        text = M.build_metrics_text()
    finally:
        for k, v in saved.items():
            setattr(M, k, v)
    gauge = {line.split('"')[1]: line.rsplit(" ", 1)[1] for line in text.splitlines()
             if line.startswith("caravan_client_online{")}
    board = {row["id"]: ("1" if row["state"] == "online" else "0") for row in fc.topology_hosts()}
    check(gauge == board, f"метрика и доска говорят одно о каждой машине (got {gauge} vs {board})")
    check(gauge.get("quiet") == "1",
          "машина между двумя пульсами (100 с) — онлайн: окно в три пульса, а не короче одного")
    ages = [line for line in text.splitlines() if line.startswith("caravan_client_last_seen_seconds{")]
    check(not any('"never"' in line for line in ages),
          "negative: у машины без единого отчёта нет строки возраста — ноль был бы враньём")
    # An operator's CARAVAN_HOST_REPORT_TTL moves both, since both read it.
    saved_ttl = (M.HOST_REPORT_TTL, fc.HOST_REPORT_TTL)
    saved = {k: getattr(M, k) for k in fakes}
    try:
        for k, v in fakes.items():
            setattr(M, k, v)
        M.HOST_REPORT_TTL = fc.HOST_REPORT_TTL = 60
        short = {line.split('"')[1]: line.rsplit(" ", 1)[1] for line in M.build_metrics_text().splitlines()
                 if line.startswith("caravan_client_online{")}
        short_board = {row["id"]: ("1" if row["state"] == "online" else "0") for row in fc.topology_hosts()}
    finally:
        for k, v in saved.items():
            setattr(M, k, v)
        M.HOST_REPORT_TTL, fc.HOST_REPORT_TTL = saved_ttl
    check(short == short_board and short.get("quiet") == "0",
          "negative: окно, заданное оператором короче (60 с), двигает и метрику, и доску — своего числа у метрики нет")


def test_forgetting_a_machine_touches_nothing_else():
    """A silent scout's machine is forgotten by hand: its host record, only.

    The client with the same id is the operator's record, and the cells
    configured on the machine come back with it — neither is touched. A scout
    that still answers is refused: its next report would undo the delete.
    """
    print("забыть машину — только её запись хоста:")
    now = int(time.time())
    silent = {"id": "m", "name": "M", "agentUrl": "http://10.0.0.9:8092",
              "lastSeen": now - fc.HOST_REPORT_TTL - 60}
    store, _r = harness(hosts={"m": dict(silent)},
                        clients={"m": {"id": "m", "name": "Client M", "agents": [{"id": "a"}]}},
                        assignments={"m": {"assignments": [{"agentId": "a", "routes": []}]}})
    out = fc.topology_host_delete({"hostId": " m "})
    check(out == {"ok": True, "hostId": "m"} and "m" not in store["hosts"],
          "молчащая машина забыта — её записи хоста больше нет")
    check((store["clients"].get("m") or {}).get("agents") == [{"id": "a"}] and "m" in store["assignments"],
          "negative: клиент с тем же id и его назначения не тронуты — это запись оператора")

    def refused(body, hosts):
        harness(hosts=hosts)
        try:
            fc.topology_host_delete(body)
            return None
        except fc.AppError as exc:
            return exc.status
    check(refused({"hostId": "m"}, {"m": dict(silent, lastSeen=now)}) == 409,
          "negative: скаут отвечает — 409: следующий отчёт вернул бы машину, и удаление выглядело бы несработавшим")
    check(refused({"hostId": "nope"}, {"m": dict(silent)}) == 404, "negative: такой машины нет — 404, а не тихий успех")
    check(refused({"hostId": "  "}, {}) == 400, "negative: без hostId — 400")
    store, _r = harness(hosts={"m": {"id": "m", "name": "M"}})
    fc.topology_host_delete({"hostId": "m"})
    check("m" not in store["hosts"], "boundary: запись без единого отчёта (возраст неизвестен) — молчащая, её можно забыть")


def test_a_machine_node_is_a_host():
    """The node the board draws for a scout's machine: role "host", with the
    age of its last report — the banner on a silent machine reads it."""
    print("узел машины — хост, с возрастом отчёта:")
    import caravan.admin.topology as T
    saved = {k: getattr(T, k) for k in ("topo", "gpu_compute_apps", "cpu_snapshot", "memory_state",
                                         "_record_cpu_history", "_record_gpu_history", "_record_tps_history",
                                         "IS_CONTAINER")}
    try:
        T.topo = type("Topo", (), {"power_schedules": staticmethod(lambda: {})})()
        T.gpu_compute_apps = lambda: []
        T.cpu_snapshot = lambda: 1
        T.memory_state = lambda: {"ok": False}
        T._record_cpu_history = T._record_gpu_history = T._record_tps_history = lambda *a, **kw: []
        T.IS_CONTAINER = True
        hosts = [{"id": "m", "name": "M", "ip": "10.0.0.9", "state": "stale", "ageSeconds": 900, "gpus": []},
                 {"id": "n", "name": "N", "state": "online", "ageSeconds": 0, "scoutVersion": "2.0.0"}]
        nodes = {n["id"]: n for n in T.topology_nodes({}, {"id": "controller", "name": "Ctl"}, hosts)}
    finally:
        for k, v in saved.items():
            setattr(T, k, v)
    check([nodes["m"]["role"], nodes["n"]["role"], nodes["controller"]["role"]] == ["host", "host", "controller"],
          "машина со скаутом — узел роли host, а не client: клиент — запись оператора и узлом не бывает")
    check((nodes["m"].get("online"), nodes["m"].get("ageSeconds", "missing")) == (False, 900),
          "молчащая машина: online=false и возраст последнего отчёта")
    check((nodes["n"].get("online"), nodes["n"].get("ageSeconds", "missing")) == (True, 0),
          "boundary: возраст ноль — отчёт прямо сейчас, а не отсутствие")
    check("ageSeconds" not in nodes["controller"], "negative: у контроллера нет скаута — и возраста отчёта нет")
    check((nodes["n"].get("scoutVersion"), nodes["m"].get("scoutVersion")) == ("2.0.0", ""),
          "узел несёт версию скаута; скаут 1.x — пустая строка, по ней доска просит обновить")


for fn in (test_the_pull_keeps_the_scout_version, test_bind_refuses_an_agent_the_record_does_not_have, test_a_cell_of_an_unknown_machine_has_no_address, test_metrics_read_the_boards_liveness, test_forgetting_a_machine_touches_nothing_else, test_a_machine_node_is_a_host,
           test_a_scouts_address_lives_on_its_host, test_the_payload_keeps_machines_and_clients_apart, test_apply_stores_and_calls_no_scout, test_route_can_be_removed,
           test_agent_delete_takes_its_row_and_leaves_its_ports,
           test_agent_alias_survives_the_report,
           test_model_name_is_per_role,
           test_new_port_for_a_fallback_is_the_neighbour,
           test_agent_added_by_hand,
                      test_bind_refuses_a_port_someone_else_holds,
           test_the_board_is_told_who_holds_each_port,
                                 test_set_route_names_every_setting,
           test_saving_the_window_reaches_the_port_without_a_heartbeat,
           test_bridge_carries_the_window_to_the_route,
                      test_route_context_is_per_consumer, test_manual_client_is_an_ordinary_client,
           test_manual_client_id_rules, test_report_changes_only_the_machine, test_new_port_comes_from_the_agent_base,
           test_bind_writes_the_role_it_was_given, test_normalizer_rebuilds_the_row,            test_delete_is_explicit, test_staleness_is_a_display_state):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all client-record snapshots hold")
