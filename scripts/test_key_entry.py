#!/usr/bin/env python3
"""Value snapshot: the entry for keys as a rule and as the board keeps it.

caravan/common/key_entry.py — the one reading of a presented key and of the
route it names, shared by the proxy and the board; caravan/admin/proxies_config.py
— the entry carried through every write of agent-proxies.json, a key two
routes share refused, a closed port without a key refused, the entry's port
taken from the allocators; caravan/admin/proxy_entry.py — where the entry
listens, refused onto a port the fleet already uses.

The config is a temp file; nothing listens and nothing is started.

Run: python3 scripts/test_key_entry.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-key-entry-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
sys.path.insert(0, str(ROOT))

from caravan.admin import proxies_config as pc  # noqa: E402
from caravan.admin.proxy_entry import EntrySettings  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.common.key_entry import KeyEntry  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refused(fn, *args):
    try:
        fn(*args)
    except AppError as exc:
        return exc.status, str(exc)
    return None


KEY_A = "lcv1_" + "a" * 48
KEY_B = "lcv1_" + "b" * 48


def route(port, **extra):
    return {"label": f"agent {port}", "port": port, "upstreamHost": "127.0.0.1", "upstreamPort": 22001, **extra}


def test_rule():
    print("правило ключа:")
    check(KeyEntry.clean(None) == {} and KeyEntry.clean({"port": 0}) == {} and KeyEntry.clean({"port": 80}) == {}
          and KeyEntry.clean({"port": 70000}) == {} and KeyEntry.clean({"port": "x"}) == {},
          "вход выключен: нет записи, порт 0, служебный порт, порт за 65535, не число")
    check(KeyEntry.clean({"port": "18200", "publicUrl": "https://caravan-api.example.org/v1"})
          == {"port": 18200, "publicUrl": "https://caravan-api.example.org/v1"}, "порт и адрес для потребителей")
    check(KeyEntry.clean({"port": 18200, "publicUrl": "javascript:alert(1)"}) == {"port": 18200},
          "negative: не http(s) — адреса нет, порт остаётся")
    check(KeyEntry.presented_key({"Authorization": f"Bearer  {KEY_A} "}) == KEY_A, "Bearer — с обрезкой пробелов")
    check(KeyEntry.presented_key({"x-api-key": KEY_B}) == KEY_B, "x-api-key — как у клиентов Anthropic")
    check(KeyEntry.presented_key({"Authorization": "Basic abc"}) == "" and KeyEntry.presented_key({}) == ""
          and KeyEntry.presented_key(None) == "", "negative: не Bearer и нет заголовков — ключа нет")
    check(KeyEntry.same(KEY_A, KEY_A) and not KeyEntry.same(KEY_A, KEY_B) and not KeyEntry.same("ключ", KEY_A),
          "сравнение ключей — и с не-ASCII символами без исключения")
    routes = [route(23001, apiKey=KEY_A), route(23002, apiKey=KEY_B), route(23003),
              route(23004, apiKey="lcv1_off", enabled=False)]
    check(KeyEntry.route_for("", routes) == (None, "no-key"), "без ключа — «нет ключа»")
    check(KeyEntry.route_for("lcv1_nobody", routes) == (None, "unknown-key"), "чужой ключ — «неизвестный ключ»")
    check(KeyEntry.route_for(KEY_B, routes)[0]["port"] == 23002, "ключ находит свой маршрут")
    check(KeyEntry.route_for("lcv1_off", routes) == (None, "unknown-key"), "negative: ключ выключенного маршрута не входит")
    shared = routes + [route(23005, apiKey=KEY_A)]
    check(KeyEntry.route_for(KEY_A, shared) == (None, "ambiguous-key"), "один ключ у двух маршрутов — ни один не выбран")
    check(KeyEntry.shared_keys(shared) == {KEY_A: [23001, 23005]}, "общие ключи названы вместе с портами")


def fresh(payload):
    Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).write_text(json.dumps(payload), encoding="utf-8")


def stored():
    return json.loads(Path(os.environ["AGENT_PROXY_CONFIG_FILE"]).read_text(encoding="utf-8"))


def test_board_keeps_the_entry():
    print("доска не теряет вход и не пускает плохие ключи:")
    keep = pc.ensure_agent_proxy_running
    pc.ensure_agent_proxy_running = lambda timeout=30: {"ok": True, "stderr": ""}
    try:
        fresh({"routes": [route(23001, apiKey=KEY_A), route(23002, apiKey=KEY_B)],
               "entry": {"port": 23999, "publicUrl": "https://caravan-api.example.org/v1"}})
        check(pc.load_agent_proxy_config()["entry"] == {"port": 23999, "publicUrl": "https://caravan-api.example.org/v1"},
              "загрузчик доски несёт вход")
        pc.save_agent_proxy_config(pc.load_agent_proxy_config()["routes"])
        check(stored().get("entry", {}).get("port") == 23999, "сохранение маршрутов не стирает вход")
        pc.set_agent_proxy_route_policy(23001, {"priority": 5})
        check(stored().get("entry", {}).get("port") == 23999, "правка маршрута не стирает вход")
        pc.set_agent_proxy_route_policy(23002, {"portClosed": True})
        check(stored()["routes"][1].get("portClosed") is True, "порт закрыт по просьбе доски")
        pc.save_agent_proxy_config(pc.load_agent_proxy_config()["routes"])
        check(stored()["routes"][1].get("portClosed") is True, "закрытый порт переживает сохранение маршрутов")
        got = refused(pc.save_agent_proxy_config, [route(23001, apiKey=KEY_A), route(23002, apiKey=KEY_A)])
        check(got is not None and got[0] == 400 and "share one key" in got[1] and "23001, 23002" in got[1],
              f"один ключ на два порта — отказ с портами (got {got})")
        fresh({"routes": [route(23001), route(23002, apiKey=KEY_B)], "entry": {"port": 23999}})
        got = refused(pc.set_agent_proxy_route_policy, 23001, {"portClosed": True})
        check(got is not None and got[0] == 400 and "no key" in got[1], f"закрыть порт без ключа — отказ (got {got})")
        check("portClosed" not in stored()["routes"][0], "и ничего не записано")
        fresh({"routes": [route(23001), route(23002, apiKey=KEY_B)]})
        got = refused(pc.set_agent_proxy_route_policy, 23002, {"portClosed": True})
        check(got is not None and got[0] == 409 and "entry is off" in got[1] and "portClosed" not in stored()["routes"][1],
              f"вход выключен — закрыть порт нельзя: агенту некуда было бы идти (got {got})")
        check(pc.set_agent_proxy_route_policy(23002, {"portClosed": False}) and "portClosed" not in stored()["routes"][1],
              "negative: открыть порт можно и при выключенном входе")
        fresh({"routes": [route(23001, apiKey=KEY_A)], "entry": {"port": 23999}})
        check(23999 in pc._all_taken_ports([route(23001)]), "порт входа занят для раздачи портов агентам")
        fresh({"routes": [route(23001, apiKey=KEY_A, portClosed=True, cloudFallbackPct=30, queueAbortPct=90),
                          route(23002, apiKey=KEY_B)]})
        # The board's ✎ save: every route as the page holds it — the page never carried these fields.
        page = [route(23001, apiKey=KEY_A, label="renamed"), route(23002, apiKey=KEY_B)]
        pc.save_agent_proxy_config(page)
        r1 = stored()["routes"][0]
        check(r1.get("portClosed") is True and r1.get("cloudFallbackPct") == 30 and r1.get("queueAbortPct") == 90
              and r1["label"] == "renamed",
              "defect-history (2026-10-07): правка порта на доске не открывает закрытый порт и не сбрасывает его пороги")
        check("portClosed" not in stored()["routes"][1], "negative: у порта, который не закрывали, флаг не появился")
        pc.save_agent_proxy_config([route(23001, apiKey=KEY_A, portClosed=False, cloudFallbackPct=None), route(23002, apiKey=KEY_B)])
        r1 = stored()["routes"][0]
        check("portClosed" not in r1 and "cloudFallbackPct" not in r1 and r1.get("queueAbortPct") == 90,
              "сохранение, что называет поле (false, null), говорит своё: порт открыт, порог снят; неназванный — на месте")
    finally:
        pc.ensure_agent_proxy_running = keep


def test_route_keys():
    print("«Give a key»: ключ и сразу только вход:")
    fresh({"routes": [route(23001), route(23002, apiKey=KEY_B), route(23005, kind="consumer", label="notes app")],
           "entry": {"port": 23999}})
    keys = pc.RouteKeys(token=lambda: "c" * 48)
    got = keys.issue(23001)
    r1 = stored()["routes"][0]
    check(got == {"port": 23001, "key": "lcv1_" + "c" * 48} and r1["apiKey"] == got["key"], "ключ выдан маршруту без ключа и записан")
    check(r1.get("portClosed") is True,
          "порт закрыт в той же записи: без ключа старый порт не отвечает ни секунды (оператор, 2026-10-07)")
    keep = pc.ensure_agent_proxy_running
    pc.ensure_agent_proxy_running = lambda timeout=30: {"ok": True, "stderr": ""}
    try:
        pc.save_agent_proxy_config([route(23001, apiKey=got["key"]), route(23002, apiKey=KEY_B),
                                    route(23005, kind="consumer", label="notes app")])
    finally:
        pc.ensure_agent_proxy_running = keep
    check(stored()["routes"][0].get("portClosed") is True, "✎ сохранение доски порт не открывает")
    for port, status, why in ((23002, 409, "у маршрута уже есть ключ — заменить его — отдельное действие"),
                              (23005, 409, "клиент входа — его ключ меняют на его карточке"),
                              (23999, 404, "маршрута нет"), ("x", 400, "не число")):
        before = stored()
        got = refused(keys.issue, port)
        check(got is not None and got[0] == status and stored() == before, f"negative: {why} — {status}, ничего не записано (got {got})")
    fresh({"routes": [route(23001)]})
    got = refused(keys.issue, 23001)
    check(got is not None and got[0] == 409 and "entry is off" in got[1] and "apiKey" not in stored()["routes"][0],
          "negative: вход выключен — ключ не выдан: потребителю было бы некуда идти")
    fresh({"routes": [route(23001), route(23002, apiKey="lcv1_" + "c" * 48)], "entry": {"port": 23999}})
    got = refused(keys.issue, 23001)
    check(got is not None and got[0] == 400 and "apiKey" not in stored()["routes"][0],
          "negative: ключ совпал с чужим — отказ, ключ не записан и порт не закрыт")


def test_key_tail():
    print("что показывают от ключа:")
    check([KeyEntry.tail(KEY_A), KeyEntry.tail(""), KeyEntry.tail(None), KeyEntry.tail("abc")] == ["aaaa", "", "", "abc"],
          "последние 4 знака ключа; negative: нет ключа — пусто, а не «None»")
    route = {"label": "Hermes", "port": 23001, "kind": "consumer", "apiKey": KEY_B}
    public = KeyEntry.public_route(route)
    check(public == {"label": "Hermes", "port": 23001, "kind": "consumer", "keyTail": "bbbb"} and route["apiKey"] == KEY_B,
          "маршрут наружу — без ключа, с keyTail; negative: сам маршрут не тронут")


def test_entry_settings():
    print("настройка входа на доске:")
    listening = set()
    settings = EntrySettings(listening=lambda port: port in listening, taken=lambda routes: {23001, 22001})
    fresh({"routes": [route(23001, apiKey=KEY_A)]})
    check(settings.read() == {"ok": True, "port": None, "publicUrl": "", "listening": False, "keyedRoutes": 1,
                              "closedPorts": []}, "вход выключен — порта нет, а не 0")
    got = settings.write({"port": 23999, "publicUrl": "https://caravan-api.example.org/v1"})
    check(got["port"] == 23999 and got["publicUrl"] == "https://caravan-api.example.org/v1"
          and stored()["entry"] == {"port": 23999, "publicUrl": "https://caravan-api.example.org/v1"},
          "вход открыт: записан в конфиг, который читает прокси")
    check(settings.write({"port": 23999})["port"] == 23999, "тот же порт ещё раз — не «занят самим собой»")
    for body, status, why in (({"port": 23001}, 409, "порт маршрута"), ({"port": 22001}, 409, "порт ячейки"),
                              ({"port": 80}, 400, "служебный порт"), ({"port": "x"}, 400, "не число"),
                              ({"port": 23999, "publicUrl": "ftp://x"}, 400, "адрес не http(s)")):
        got = refused(settings.write, body)
        check(got is not None and got[0] == status, f"negative: {why} — {status} (got {got})")
    listening.add(23998)
    got = refused(settings.write, {"port": 23998})
    check(got is not None and got[0] == 409 and "listens" in got[1], "negative: порт уже кто-то слушает — 409")
    payload = stored()
    payload["routes"][0]["portClosed"] = True
    fresh(payload)
    got = refused(settings.write, {"port": 0})
    check(got is not None and got[0] == 409 and "23001" in got[1], f"закрыть вход при закрытом порте — отказ (got {got})")
    clients = {**payload, "routes": [*payload["routes"], route(23002, kind="consumer", label="notes app", portClosed=True)]}
    fresh(clients)
    got = refused(settings.write, {"port": 0})
    check(got == (409, "client notes app calls the caravan only through the entry: delete it before turning the entry off"),
          f"клиент входа есть — вход не выключить: назван клиент, а не номер его записи (got {got})")
    clients["routes"].append(route(23003, kind="consumer", label="mail bot", portClosed=True))
    fresh(clients)
    got = refused(settings.write, {"port": None})
    check(got == (409, "clients notes app, mail bot call the caravan only through the entry: delete them before turning the entry off"),
          f"два клиента — названы оба (got {got})")
    check(got is not None and "open" not in got[1] and stored()["entry"]["port"] == 23999,
          "negative: клиенту не предлагают «открыть порт», которого у него нет; после отказа вход на месте")
    fresh(payload)
    payload["routes"][0].pop("portClosed")
    fresh(payload)
    check(settings.write({"port": None})["port"] is None and stored()["entry"] == {}, "вход закрыт — запись пустая")


def test_route_key_endpoint():
    print("POST /api/agent-proxies/route-key:")
    from caravan.admin import routes
    handler = routes.POST_ROUTES.get("/api/agent-proxies/route-key")

    class Reply:
        def __init__(self):
            self.sent = []

        def send_json(self, data, status=200):
            self.sent.append((status, data))

    keep = routes.topology_state
    routes.topology_state = lambda **kw: {"marker": "board"}
    try:
        fresh({"routes": [route(23001)], "entry": {"port": 23999, "publicUrl": "https://caravan-api.example/v1"}})
        reply = Reply()
        handler(reply, None, {"port": 23001})
        status, doc = reply.sent[0] if reply.sent else (None, {})
        key = str(doc.get("key") or "")
        check(status == 200 and doc.get("ok") is True and doc.get("port") == 23001
              and key.startswith("lcv1_") and len(key) == 53 and stored()["routes"][0]["apiKey"] == key,
              "ключ отдан один раз в ответе — тот, что записан у маршрута")
        check(doc.get("entryUrl") == "https://caravan-api.example/v1" and doc.get("topology") == {"marker": "board"},
              "ответ называет адрес, куда теперь ходить, и несёт доску")
        check(stored()["routes"][0].get("portClosed") is True, "порт закрыт тем же запросом")
        fresh({"routes": [route(23001)]})
        reply = Reply()
        got = refused(handler, reply, None, {"port": 23001})
        check(got is not None and got[0] == 409 and reply.sent == [] and "apiKey" not in stored()["routes"][0],
              "negative: вход выключен — 409, ответа с ключом нет, ничего не записано")
    finally:
        routes.topology_state = keep
    check(routes.ROUTE_ACCESS.security("POST", "/api/agent-proxies/route-key").get("x-caravan-roles") == ["admin"],
          "ключ выдаёт только админ: зритель видит доску и не раздаёт ключи")


for fn in (test_rule, test_board_keeps_the_entry, test_route_keys, test_route_key_endpoint, test_key_tail, test_entry_settings):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("key entry snapshot holds")
