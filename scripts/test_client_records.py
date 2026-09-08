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


def harness(assignments=None, routes=None, clients=None):
    """The module's collaborators pointed at in-memory state.

    Same shape as scripts/test_auto_provision.py — the provisioner is the only
    writer of these records today, and it is reached through module-level
    globals rather than an injected object.
    """
    store = {"assignments": dict(assignments or {}), "clients": dict(clients or {}),
             "deletedAgents": {}}
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


CLIENT = {"id": "client-a", "agentUrl": "http://10.0.0.2:8092",
          "agents": [{"id": "agent-a", "name": "Agent A"}]}


def test_provisioned_record_shape():
    print("что записывает провижининг:")
    store, routes = harness()
    fc.auto_provision_agent_proxies(CLIENT)
    host = store["assignments"]["client-a"]
    check(sorted(host.keys()) == ["agentUrl", "assignments"],
          f"запись хоста — две ключа: agentUrl и assignments (got {sorted(host.keys())})")
    ag = host["assignments"][0]
    check(ag["agentId"] == "agent-a", "агент назван своим id")
    check(sorted(ag.keys()) == ["agentId", "routes"],
          f"у агента только id и маршруты — ни флага manual, ни настроек (got {sorted(ag.keys())})")
    route = ag["routes"][0]
    check(sorted(route.keys()) == ["endpoint", "proxyId", "role"],
          f"маршрут — три ключа (got {sorted(route.keys())})")
    check(route["role"] == "primary", "роль primary")
    check(route["proxyId"].startswith("skynet:proxy:"), f"proxyId в неймспейсе (got {route['proxyId']})")
    check(route["endpoint"].endswith("/v1") and route["endpoint"].startswith("http://"),
          f"endpoint — http://<ip>:<port>/v1 (got {route['endpoint']})")
    port = int(route["proxyId"].rsplit(":", 1)[1])
    check(f":{port}/v1" in route["endpoint"], "порт в endpoint и в proxyId — один и тот же")


def test_absences_the_page_will_fill():
    print("чего в записи провижининга нет:")
    store, routes = harness()
    fc.auto_provision_agent_proxies(CLIENT)
    ag = store["assignments"]["client-a"]["assignments"][0]
    roles = [r["role"] for r in ag["routes"]]
    check(roles == ["primary"], f"fallback НЕ заводится автоматом никогда (got {roles})")
    check(all("contextLength" not in r and "contextAuto" not in r for r in ag["routes"]),
          "провижининг окна контекста НЕ задаёт: его ставит оператор, и молчание тут — не ноль")
    check(callable(getattr(fc, "topology_client_create", None)),
          "завести клиента без сердцебиения ТЕПЕРЬ есть чем — см. пины ниже")
    check("client-a" not in store["clients"],
          "провижининг НЕ создаёт саму запись клиента — только его прокси")


def test_silence_never_deletes():
    print("молчание не удаляет:")
    store, routes = harness()
    fc.auto_provision_agent_proxies(CLIENT)
    before = store["assignments"]["client-a"]["assignments"][0]["routes"][0]["proxyId"]
    # A heartbeat where the agent no longer exists at all.
    fc.auto_provision_agent_proxies({**CLIENT, "agents": []})
    ag = store["assignments"]["client-a"]["assignments"]
    check(len(ag) == 1 and ag[0]["agentId"] == "agent-a",
          "агент, которого скаут перестал называть, остаётся в записи")
    check(ag[0]["routes"][0]["proxyId"] == before, "и его порт не меняется")
    # A second pass over a live report — still no movement.
    fc.auto_provision_agent_proxies(CLIENT)
    check(store["assignments"]["client-a"]["assignments"][0]["routes"][0]["proxyId"] == before,
          "повторный проход по тому же отчёту ничего не переписывает")


def test_manual_flag_is_respected():
    print("ручная привязка (существует уже сегодня):")
    assignments = {"client-a": {"agentUrl": "", "assignments": [
        {"agentId": "agent-a", "manual": True, "routes": [
            {"role": "primary", "proxyId": "skynet:proxy:9999", "endpoint": "http://10.0.0.1:9999/v1"}]},
    ]}}
    store, routes = harness(assignments=assignments)
    for _ in range(3):
        fc.auto_provision_agent_proxies(CLIENT)
    ag = store["assignments"]["client-a"]["assignments"][0]
    check(routes == [], "ручной агент не порождает портов")
    check(ag["routes"][0]["proxyId"] == "skynet:proxy:9999", "порт оператора сохранён, даже мёртвый")
    check(ag.get("manual") is True, "флаг переживает проходы")
    # Exactly the same, without the flag — provisioning will rewrite it.
    store2, routes2 = harness(assignments={"client-a": {"agentUrl": "", "assignments": [
        {"agentId": "agent-a", "routes": [
            {"role": "primary", "proxyId": "skynet:proxy:9999", "endpoint": "http://10.0.0.1:9999/v1"}]},
    ]}})
    fc.auto_provision_agent_proxies(CLIENT)
    check(store2["assignments"]["client-a"]["assignments"][0]["routes"][0]["proxyId"] != "skynet:proxy:9999",
          "БЕЗ флага тот же мёртвый порт перевыдаётся — вот что флаг и отключает")


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
    print("живость — это состояние показа, а не существования:")
    now = int(time.time())
    store, _r = harness(clients={
        "fresh": {"id": "fresh", "name": "F", "lastSeen": now},
        "silent": {"id": "silent", "name": "S", "lastSeen": now - fc.TOPOLOGY_CLIENT_TTL - 60},
        "never": {"id": "never", "name": "N"},
    })
    fc.client_aliases = lambda: {}
    rows = {r["id"]: r for r in fc.topology_clients()}
    check(len(rows) == 3, f"молчащие клиенты остаются в списке (got {len(rows)})")
    check(rows["fresh"]["state"] == "online", "свежий — online")
    check(rows["silent"]["state"] == "stale", "замолчавший — stale, но не удалён")
    check(rows["never"]["state"] == "stale" and rows["never"]["ageSeconds"] is None,
          "никогда не отвечавший — stale и возраст неизвестен (не ноль)")



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
    kept = norm({"agentId": "a", "manual": True, "routes": [
        {"role": "primary", "endpoint": "http://h:1/v1"}]})
    check(kept.get("manual") is True,
          "а `manual` переживает — потому что нормализатор называет его явно")
    check(norm({"agentId": "a", "manual": False, "routes": []}).get("manual") is False,
          "включая явное False")
    check("manual" not in norm({"agentId": "a", "routes": []}),
          "отсутствующий флаг не выдумывается")
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
    check(row.get("manual") is True, "запись помечена как заведённая руками")
    agents = row.get("agents") or []
    check(len(agents) == 1 and agents[0].get("id") == "box-a" and agents[0].get("name") == "box-a"
          and agents[0].get("manual") is True,
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
    # And the same list, the way the board sees it: it exists, but is silent.
    fc.client_aliases = lambda: {}
    rows = {r["id"]: r for r in fc.topology_clients()}
    check(rows["box-a"]["state"] == "stale" and rows["box-a"]["ageSeconds"] is None,
          "в списке он молчащий с НЕИЗВЕСТНЫМ возрастом, а не свежий и не нулевой")


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


def test_heartbeat_keeps_the_manual_mark():
    print("отчёт скаута не переписывает пометку:")
    store, _routes = harness()
    fc.topology_client_create({"hostId": "box-a"})
    # Provisioning and the metadata reconcile have nothing to do with this —
    # they're stubbed out TEMPORARILY and then restored: a stub that outlives
    # its own test makes the next one dependent on run order, and one just
    # like it has already broken exactly that way.
    _prov, _rec = fc.auto_provision_agent_proxies, fc.reconcile_proxy_metadata
    fc.auto_provision_agent_proxies = lambda *a, **kw: None
    fc.reconcile_proxy_metadata = lambda *a, **kw: None
    try:
        after = fc.update_topology_client({"host": {"id": "box-a"}, "agents": [{"id": "ag"}]})
        plain = fc.update_topology_client({"host": {"id": "box-c"}, "agents": []})
    finally:
        fc.auto_provision_agent_proxies, fc.reconcile_proxy_metadata = _prov, _rec
    check(after.get("manual") is True,
          "клиент, заведённый руками и найденный потом, остаётся ручным")
    check(sorted(a["id"] for a in after.get("agents") or []) == ["ag", "box-a"],
          "и при этом принимает то, что скаут о нём рассказал — а первый агент, заведённый вместе с клиентом, "
          "остаётся как любой ручной (снимается ✕), отчёт его не стирает")
    fc.client_aliases = lambda: {}
    live = {r["id"]: r for r in fc.topology_clients()}
    check(live["box-a"]["state"] == "online",
          "отозвавшись, он становится живым — существование и живость разные вещи")
    # The reverse case: a client the scout found doesn't become manual.
    check("manual" not in plain, "клиент, которого никто не заводил, не помечается ручным")


def test_bind_writes_the_role_it_was_given():
    print("ручная привязка по ролям:")
    store = {"assignments": {}, "clients": {}}
    T = _topology_harness(store, [23001, 23002])
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23001, "role": "primary"})
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "a", "port": 23002, "role": "fallback"})
    row = store["assignments"]["h"]["assignments"][0]
    check([(r["role"], r["proxyId"]) for r in row["routes"]]
          == [("primary", "skynet:proxy:23001"), ("fallback", "skynet:proxy:23002")],
          f"обе роли записаны своими портами (got {row['routes']})")
    check(row.get("manual") is True, "привязка руками ставит manual")
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
    # With no port — reverts to automatic.
    T.bind_agent_to_proxy({"hostId": "h", "agentId": "a"})
    check("manual" not in store["assignments"]["h"]["assignments"][0],
          "привязка без порта снимает manual — агент возвращается к автомату")


def _ops_harness(store, routes):
    """Тот же приём для caravan.admin.proxy_ops — пересборка по живому отчёту."""
    import caravan.admin.proxy_ops as po
    po.refresh_topology_clients_from_agents = lambda *a, **k: None
    po.topology_store = lambda: store
    po.TOPOLOGY_SERVER_IP = "10.0.0.1"
    po.load_agent_proxy_config = lambda: {"routes": list(routes)}
    po.save_agent_proxy_config = lambda *a, **k: None
    po.save_admin_state = lambda *a, **k: None
    po.restart_agent_proxy = lambda *a, **k: None
    po.stop_agent_proxy = lambda *a, **k: None
    return po


def _reconcile_fixture(*, live_port, saved_port=23001, context=8192, auto=False, manual=True):
    saved_route = {"role": "primary", "proxyId": f"skynet:proxy:{saved_port}",
                   "endpoint": f"http://10.0.0.1:{saved_port}/v1"}
    if context is not None:
        saved_route["contextLength"] = context
    if auto is not None:
        saved_route["contextAuto"] = auto
    saved_row = {"agentId": "agent-a", "routes": [saved_route]}
    if manual is not None:
        saved_row["manual"] = manual
    return {
        "clients": {"client-a": {"agentUrl": "http://10.0.0.1:8092", "assignments": [
            {"agentId": "agent-a", "routes": [{"role": "primary",
                                               "proxyId": f"skynet:proxy:{live_port}",
                                               "endpoint": f"http://10.0.0.1:{live_port}/v1"}]}]}},
        "assignments": {"client-a": {"agentUrl": "http://10.0.0.1:8092",
                                     "assignments": [saved_row]}},
        "deletedAgents": {},
    }


def test_agent_added_by_hand():
    """Агента клиенту можно добавить руками — и он это переживает.

    Клиента завести было можно, а агента ему — нечем: в карточке ручного
    клиента жили только «переименовать» и «удалить», поэтому назначить прокси
    было некому. Запись существовала и настраиваться не могла.

    Отчёт скаута заменяет список агентов целиком, поэтому добавленный руками
    обязан быть помечен и пережить отчёт: иначе он исчезал бы у клиента,
    который однажды отозвался, — молча и без следа.
    """
    print("агент, добавленный руками:")
    from caravan.domain.client import FleetClient
    store, _routes = harness(clients={"box-a": FleetClient.manual("box-a", name="A")})
    fc.topology_store = lambda: store

    row = fc.topology_client_add_agent({"hostId": "box-a", "agentId": "  ag-1  ", "name": " Один "})
    agents = store["clients"]["box-a"]["agents"]
    check([a["id"] for a in agents] == ["ag-1"], f"агент добавлен, id обрезан (got {agents!r})")
    check(agents[0].get("manual") is True, "и помечен ручным — иначе отчёт его сотрёт")
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
    fc.update_topology_client({"host": {"id": "box-a", "name": "A"},
                               "agents": [{"id": "reported", "name": "R"}]})
    ids = sorted(a["id"] for a in store["clients"]["box-a"]["agents"])
    check(ids == ["ag-1", "reported"],
          f"ручной агент пережил отчёт, а не был заменён им (got {ids})")
    check(next(a for a in store["clients"]["box-a"]["agents"] if a["id"] == "ag-1")["manual"] is True,
          "и остался помеченным")
    # NEGATIVE: an agent the report stays silent about, and which is NOT
    # manual, still disappears as before — liveness still belongs to the scout.
    fc.update_topology_client({"host": {"id": "box-a", "name": "A"}, "agents": []})
    ids = sorted(a["id"] for a in store["clients"]["box-a"]["agents"])
    check(ids == ["ag-1"], f"неручной агент по-прежнему уходит вместе с отчётом (got {ids})")


def test_adopting_the_scouts_clients():
    """Adoption in place: the board becomes the owner of a scout's record.

    Nothing is created or deleted — otherwise a live registry gets a window
    where working routes exist twice or not at all. Exactly one fact
    changes: who owns it. Everything else in the record must stay
    byte-for-byte, and route settings especially so: adoption is no reason
    to rebuild them.
    """
    print("усыновление клиентов скаута:")
    store = {
        "clients": {
            "box-a": {"id": "box-a", "name": "A", "lastSeen": 111, "agents": [{"id": "a1"}]},
            "box-b": {"id": "box-b", "name": "B", "manual": True, "agents": []},
        },
        "assignments": {
            "box-a": {"agentUrl": "http://x", "assignments": [
                {"agentId": "a1", "routes": [{"role": "primary", "proxyId": "skynet:proxy:23001",
                                              "endpoint": "http://x:23001/v1",
                                              "contextLength": 8192, "contextAuto": False}]}]},
            "box-b": {"agentUrl": "", "assignments": [
                {"agentId": "b1", "manual": True, "routes": [
                    {"role": "primary", "proxyId": "skynet:proxy:23002",
                     "endpoint": "http://x:23002/v1"}]}]},
        },
    }
    harness(assignments=store["assignments"], clients=store["clients"])
    fc.topology_store = lambda: store
    before_a = json.dumps(store["clients"]["box-a"], sort_keys=True)

    report = fc.adopt_scout_clients()
    check(report == {"clients": 1, "agents": 1},
          f"отчёт называет числа: один клиент, один агент (got {report!r})")
    check(store["clients"]["box-a"].get("manual") is True,
          "запись скаута помечена ручной")
    check(store["assignments"]["box-a"]["assignments"][0].get("manual") is True,
          "и строка его агента тоже")
    route = store["assignments"]["box-a"]["assignments"][0]["routes"][0]
    check(route.get("contextLength") == 8192 and route.get("contextAuto") is False,
          f"настройки маршрута усыновление не трогает (got {route!r})")
    check(route.get("proxyId") == "skynet:proxy:23001"
          and route.get("endpoint") == "http://x:23001/v1",
          f"и привязку не трогает (got {route!r})")
    check(json.loads(before_a)["lastSeen"] == store["clients"]["box-a"]["lastSeen"],
          "живость не переписана — усыновление про хозяина, а не про то, отвечает ли он")
    check(list(store["clients"]) == ["box-a", "box-b"]
          and len(store["assignments"]["box-a"]["assignments"]) == 1,
          "ничего не создано и не удалено")

    # NEGATIVE: what's already manual isn't counted or touched; a repeat call is harmless.
    check(fc.adopt_scout_clients() == {"clients": 0, "agents": 0},
          "повторное усыновление не находит ничего — операция идемпотентна")
    check(store["clients"]["box-b"].get("manual") is True
          and store["assignments"]["box-b"]["assignments"][0].get("manual") is True,
          "уже ручные остались как были")

    # The controller is not a scout client: there's nothing to adopt and no reason to.
    store2 = {"clients": {"controller": {"id": "controller", "name": "C", "agents": []}},
              "assignments": {}}
    fc.topology_store = lambda: store2
    check(fc.adopt_scout_clients() == {"clients": 0, "agents": 0},
          "сентинел контроллера в усыновление не попадает")
    check("manual" not in store2["clients"]["controller"],
          "и не помечается ручным")


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
    store = {"assignments": {}, "clients": {}}
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
        "clients": {}}
    T = _topology_harness(store, [23001, 23002])
    fc.topology_store = lambda: store
    row = lambda: store["assignments"]["h"]["assignments"][0]

    T.remove_agent_route({"hostId": "h", "agentId": "a", "role": "fallback"})
    check([r["role"] for r in row()["routes"]] == ["primary"],
          f"фолбэк убран, праймари цел (got {row()['routes']})")
    check(row()["routes"][0].get("contextLength") == 8192,
          "и настройки уцелевшей роли не тронуты")
    check(row().get("manual") is True, "флаг «руками» на месте")
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
    store, _routes = harness(clients={"box-a": dict(FleetClient.manual("box-a", name="A"),
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
    fc.update_topology_client({"host": {"id": "box-a", "name": "A"},
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
    store = {"assignments": {}, "clients": {}}
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
    # as-is: "unbind" means returning the agent to automatic, NOT freeing the
    # port. The route stays in place, so the port stays taken, and trying to
    # give it to a neighbor is still a refusal. The pin fixes this as-is: if
    # freeing it up is ever added, the pin must turn red and force a
    # decision, rather than silently drift away from what the word means.
    T.bind_agent_to_proxy({"hostId": "h1", "agentId": "a1"})
    check("manual" not in store["assignments"]["h1"]["assignments"][0],
          "снятие привязки убирает manual — агент вернулся автомату")
    try:
        T.bind_agent_to_proxy({"hostId": "h1", "agentId": "a2", "port": 23001, "role": "fallback"})
        check(False, "порт после «отвязки» всё ещё за прежним агентом — ожидался отказ")
    except Exception as exc:
        check(getattr(exc, "status", None) == 409,
              f"«отвязать» = вернуть автомату, а не освободить порт; освобождает его "
              f"remove_agent_route (got {exc!r})")


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


def test_reconcile_carries_what_the_operator_set():
    """The fifth rebuild boundary: reconciling proxies with a live report.

    The scout's live report knows WHERE an agent is reached. It doesn't know
    what the operator decided about that route, and has no right to erase
    it. Before these pins, the reconcile built the record from scratch out of
    the report — and the context window, along with the "manual" flag,
    silently vanished for EVERY online agent, even when the port hadn't changed.
    """
    print("сверка прокси с живым отчётом:")
    # (a) Same port — nothing to rewrite, yet the record still got rebuilt.
    store = _reconcile_fixture(live_port=23001, saved_port=23001)
    po = _ops_harness(store, [{"port": 23001, "clientId": "client-a", "role": "primary"}])
    po.reconcile_agent_proxies(dry_run=False)
    row = store["assignments"]["client-a"]["assignments"][0]
    route = row["routes"][0]
    check(route.get("contextLength") == 8192,
          f"тот же порт: окно оператора уцелело (got {route.get('contextLength')!r})")
    check(route.get("contextAuto") is False,
          f"тот же порт: выключенная галка уцелела (got {route.get('contextAuto')!r})")
    check(row.get("manual") is True,
          f"тот же порт: флаг «руками» уцелел (got {row.get('manual')!r})")

    # (b) The port MOVED — liveness moves, settings follow along.
    store = _reconcile_fixture(live_port=23002, saved_port=23001)
    po = _ops_harness(store, [{"port": 23001, "clientId": "client-a", "role": "primary"},
                              {"port": 23002, "clientId": "client-a", "role": "primary"}])
    po.reconcile_agent_proxies(dry_run=False)
    row = store["assignments"]["client-a"]["assignments"][0]
    route = row["routes"][0]
    check(route.get("proxyId") == "skynet:proxy:23002",
          f"переезд: маршрут встал на порт из отчёта (got {route.get('proxyId')!r})")
    check(route.get("endpoint") == "http://10.0.0.1:23002/v1",
          f"переезд: endpoint собран по тому же порту (got {route.get('endpoint')!r})")
    check(route.get("contextLength") == 8192,
          f"переезд: окно оператора переехало вместе с ним (got {route.get('contextLength')!r})")
    check(row.get("manual") is True,
          f"переезд: флаг «руками» переехал (got {row.get('manual')!r})")

    # (c) NEGATIVE: what the operator never set doesn't appear either.
    store = _reconcile_fixture(live_port=23002, saved_port=23001,
                               context=None, auto=None, manual=None)
    po = _ops_harness(store, [{"port": 23001}, {"port": 23002}])
    po.reconcile_agent_proxies(dry_run=False)
    row = store["assignments"]["client-a"]["assignments"][0]
    route = row["routes"][0]
    check("contextLength" not in route,
          f"незаданное окно не выдумывается (got {route!r})")
    check("contextAuto" not in route,
          f"незаданная галка не выдумывается (got {route!r})")
    check("manual" not in row,
          f"незаданный флаг «руками» не выдумывается (got {row!r})")
    check([r["role"] for r in row["routes"]] == ["primary"],
          f"строка остаётся primary-only, пары fallback не воскресают (got {row['routes']})")


def test_route_context_is_per_consumer():
    print("окно контекста на клиентской прокси-ячейке:")
    from caravan.domain.client_proxy import ProxyRoute
    store = {"assignments": {"h": {"agentUrl": "", "assignments": [
        {"agentId": "a", "routes": [
            {"role": "primary", "proxyId": "skynet:proxy:23001", "endpoint": "http://x:23001/v1"},
            {"role": "fallback", "proxyId": "skynet:proxy:23002", "endpoint": "http://x:23002/v1"}]}]}},
        "clients": {}}
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

for fn in (test_provisioned_record_shape, test_route_can_be_removed,
           test_agent_alias_survives_the_report,
           test_model_name_is_per_role,
           test_new_port_for_a_fallback_is_the_neighbour,
           test_agent_added_by_hand,
           test_adopting_the_scouts_clients,
           test_bind_refuses_a_port_someone_else_holds,
           test_set_route_names_every_setting,
           test_saving_the_window_reaches_the_port_without_a_heartbeat,
           test_bridge_carries_the_window_to_the_route,
           test_reconcile_carries_what_the_operator_set,
           test_route_context_is_per_consumer, test_manual_client_is_an_ordinary_client,
           test_manual_client_id_rules, test_heartbeat_keeps_the_manual_mark,
           test_bind_writes_the_role_it_was_given, test_normalizer_rebuilds_the_row, test_absences_the_page_will_fill, test_silence_never_deletes,
           test_manual_flag_is_respected, test_delete_is_explicit, test_staleness_is_a_display_state):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all client-record snapshots hold")
