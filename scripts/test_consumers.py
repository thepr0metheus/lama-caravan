#!/usr/bin/env python3
"""Value snapshot: a consumer of the entry as the board makes and keeps it.

caravan/admin/consumers.py — a consumer made with a name and a key answered
once, cabled to no set; its set given and taken away; its key replaced; a
consumer of the old form (`models`) given its first pool once, on the way to a
set (caravan/admin/model_sets.py, scripts/test_model_sets.py).
caravan/admin/router_dsl.py — a route of kind "consumer" keeps its set (or, of
an older form, its pool or its models) and feeds no router.
caravan/admin/proxies_config.py — a save from the page keeps a consumer's key
and set it does not carry; the old "Give a key" is not for a consumer, nor a
router. caravan/admin/topology.py — the board gets a consumer's last four
characters, its set and the models its key calls, never its key.

The config is a temp file; nothing listens and nothing is started.

Run: python3 scripts/test_consumers.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-consumers-admin-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
os.environ["AGENT_PROXY_CONFIG_FILE"] = str(TMP / "agent-proxies.json")
sys.path.insert(0, str(ROOT))

from caravan.admin import proxies_config as pc  # noqa: E402
from caravan.admin.consumers import ConsumerDesk  # noqa: E402
from caravan.admin.router_dsl import normalize_agent_proxy_route, recompute_cloud_fallback_eligibility  # noqa: E402
from caravan.admin.topology import _board_proxy, annotate_consumer_set  # noqa: E402
from caravan.common.entry_models import EntryModels  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refused(fn, *args):
    try:
        fn(*args)
    except AppError as exc:
        return exc.status
    return None


POOLS = [{"id": "std", "name": "Standart"}, {"id": "eco", "name": "Econom"}]
SETS = [{"id": "chat", "name": "Chat", "pools": ["std", "eco"]}, {"id": "cheap", "name": "Cheap", "pools": ["eco"]}]


class Keys:
    """Keys in order: k1, k2… — so a test can name them."""

    def __init__(self):
        self.n = 0

    def new(self):
        self.n += 1
        return f"lcv1_key{self.n}"


class Store:
    """agent-proxies.json in memory: what the desk loads, and what it saves."""

    def __init__(self, entry=True, routes=None):
        self.payload = {"routes": list(routes or []), "entry": {"port": 23999} if entry else {}, "routers": []}
        self.saves = 0
        self.keys = Keys()

    def load(self):
        import copy
        return copy.deepcopy(self.payload)

    read = load

    def save(self, payload):
        self.payload = payload
        self.saves += 1


def desk(store, keys=None, pools=POOLS, sets=SETS):
    return ConsumerDesk(load=store.load, save=store.save, read=store.read, pools=lambda: pools, sets=lambda: sets,
                        keys=keys or store.keys, free_port=lambda routes: 23001 + len(routes))


def test_create():
    print("клиента делают на доске:")
    store = Store(routes=[{"label": "old agent", "port": 23001, "apiKey": "lcv1_old"}])
    made = desk(store).create("  Hermes ")
    check(made == {"port": 23002, "name": "Hermes", "key": "lcv1_key1", "set": ""},
          f"имя без пробелов, ключ — один раз в ответе; набора нет, пока канат не проведён (got {made})")
    route = store.payload["routes"][-1]
    check({k: route[k] for k in ("kind", "portClosed", "routerId", "upstreamType", "apiKey", "set")}
          == {"kind": "consumer", "portClosed": True, "routerId": "", "upstreamType": "cloud", "apiKey": "lcv1_key1", "set": ""},
          "маршрут вида consumer: порт закрыт — вход единственный путь; канбана-роутера нет; набор пуст")
    check("models" not in route and "pool" not in route, "negative: ни списка пулов, ни пула старого вида у нового клиента нет")
    for name, status, why in (("", 400, "без имени"), ("  ", 400, "имя из пробелов"), ("hermes", 409, "имя другого клиента")):
        check(refused(desk(store).create, name) == status, f"negative: {why} — {status}")
    check(store.saves == 1, "negative: отказ ничего не пишет")
    check(refused(desk(Store(entry=False)).create, "Hermes") == 409,
          "negative: вход выключен — 409: у клиента не было бы пути")


def test_set_and_key():
    print("набор клиента (канат на канбане) и его ключ:")
    store = Store()
    made = desk(store).create("Hermes")
    check(desk(store).set_set(made["port"], " chat ") == {"port": made["port"], "set": "chat"}
          and store.payload["routes"][0]["set"] == "chat", "канат к набору пишется id набора")
    check(desk(store).set_set(made["port"], "cheap")["set"] == "cheap", "канат переносят на другой набор — один набор, не два")
    check(desk(store).set_set(made["port"], "")["set"] == "" and store.payload["routes"][0]["set"] == "",
          "пустое — канат снят")
    check(desk(store).set_set(made["port"], None)["set"] == "", "None — тоже снятый канат, а не ошибка")
    store.payload["routes"][0].update({"models": "all", "pool": "std"})
    desk(store).set_set(made["port"], "chat")
    check("models" not in store.payload["routes"][0] and "pool" not in store.payload["routes"][0],
          "канат на клиенте старого вида снимает его старый список и старый пул")
    keys = Keys()
    keys.n = 5
    again = desk(store, keys).new_key(made["port"])
    check(again == {"port": made["port"], "name": "Hermes", "key": "lcv1_key6"} and store.payload["routes"][0]["apiKey"] == "lcv1_key6",
          "новый ключ — один раз в ответе, старый больше не записан")
    store.payload["routes"].append({"label": "old agent", "port": 23050, "apiKey": "lcv1_x"})
    saves = store.saves
    for fn, args, status, why in ((desk(store).set_set, (23050, "chat"), 404, "порт старого агента — не клиент"),
                                  (desk(store).new_key, (99, ), 404, "номера нет"),
                                  (desk(store).set_set, ("x", "chat"), 400, "номер не число"),
                                  (desk(store).set_set, (made["port"], "gone"), 400, "набор, которого нет"),
                                  (desk(store).set_set, (made["port"], "std"), 400, "id пула вместо id набора"),
                                  (desk(store).set_set, (made["port"], ["chat"]), 400, "список вместо id"),
                                  (desk(store).set_set, (made["port"], True), 400, "True вместо id")):
        check(refused(fn, *args) == status, f"negative: {why} — {status}")
    check(store.saves == saves and store.payload["routes"][0]["set"] == "chat", "negative: отказ ничего не пишет")
    try:
        desk(store).set_set(made["port"], ["chat"])
        said = ""
    except AppError as exc:
        said = str(exc)
    check(said.startswith("set must be a set's id"),
          f"список вместо id назван как есть — не «набора с таким id нет» с пустым id (got {said!r})")


def test_migrate():
    print("клиент старого вида получает один пул (1.3.486), один раз:")
    routes = [{"label": "All", "port": 23001, "kind": "consumer", "models": "all", "routerId": ""},
              {"label": "List", "port": 23002, "kind": "consumer", "models": ["gone", "eco"]},
              {"label": "None", "port": 23003, "kind": "consumer", "models": []},
              {"label": "Taken", "port": 23004, "kind": "consumer", "models": ["std"], "routerId": "router:k"},
              {"label": "New", "port": 23005, "kind": "consumer", "pool": "eco", "routerId": ""},
              {"label": "agent", "port": 23006, "routerId": "router:default", "models": "all"},
              {"label": "Set", "port": 23007, "kind": "consumer", "set": "chat", "models": "all", "routerId": ""}]
    store = Store(routes=routes)
    done = desk(store).migrate()
    check(done == [{"name": "All", "pool": "Standart"}, {"name": "List", "pool": "Econom"},
                   {"name": "None", "pool": ""}, {"name": "Taken", "pool": "Standart"}],
          f"«все» — первый пул, список — первый живой id, пустой — без пула; ответ называет пул по имени (got {done})")
    by = {r["label"]: r for r in store.payload["routes"]}
    check([by[n].get("pool") for n in ("All", "List", "None", "Taken", "New")] == ["std", "eco", "", "std", "eco"],
          "пул записан id; уже переписанный клиент не тронут")
    check(all("models" not in by[n] for n in ("All", "List", "None", "Taken")) and by["Taken"]["routerId"] == "",
          "старый список ушёл; клиент, которого брал канбан, больше не на роутере — его канат ведёт к пулу")
    check(by["agent"] == routes[5], "negative: порт агента не тронут — ни пулом, ни роутером")
    check(by["Set"] == routes[6], "negative: клиент с набором (1.3.497) не тронут — пул ему не пишется")
    check(store.saves == 1, "запись одна на все")
    check(desk(store).migrate() is None and store.saves == 1, "negative: второй запуск — нечего переписывать, записи нет")
    check(desk(Store(routes=[{"label": "agent", "port": 23006}])).migrate() is None,
          "negative: клиентов нет — нечего переписывать")
    empty = Store(routes=[{"label": "All", "port": 23001, "kind": "consumer", "models": "all"}])
    check(desk(empty, pools=[]).migrate() == [{"name": "All", "pool": ""}] and empty.payload["routes"][0]["pool"] == "",
          "negative: «все пулы» без единого пула — без пула, а не догадка")


def test_route_rules():
    print("маршрут клиента в общих правилах:")
    base = {"label": "c", "port": 23005, "upstreamHost": "127.0.0.1", "upstreamPort": 1}
    row = normalize_agent_proxy_route({**base, "kind": "consumer", "set": " chat ", "pool": "std", "models": "all",
                                       "routerId": "router:default"})
    check((row["kind"], row["set"], row["routerId"]) == ("consumer", "chat", "") and "models" not in row and "pool" not in row,
          "вид consumer сохраняется, набор чистится, старые пул и список уходят; роутера у клиента нет, что бы ни было записано")
    one = normalize_agent_proxy_route({**base, "kind": "consumer", "pool": " std ", "models": "all"})
    check(one["pool"] == "std" and "models" not in one and "set" not in one,
          "negative: маршрут с одним пулом (1.3.486–1.3.496) хранит пул, пока контроллер не даст ему набор")
    old = normalize_agent_proxy_route({**base, "kind": "consumer", "models": ["std", "std"]})
    check(old["models"] == ["std"] and "pool" not in old and "set" not in old,
          "negative: маршрут старого вида хранит список, пока контроллер его не перепишет")
    check(normalize_agent_proxy_route({**base})["routerId"] == "router:default",
          "negative: порт без роутера по-прежнему встаёт на канбан по умолчанию")
    from caravan.admin.proxies_config import normalize_routers
    taken = [{"port": 23005, "kind": "consumer", "routerId": "router:gone"}, {"port": 23006, "routerId": "router:gone"},
             {"port": 23007, "kind": "consumer", "routerId": "router:b"}, {"port": 23008, "routerId": "router:b"}]
    routers = normalize_routers([{"id": "router:b", "name": "B"}], taken)
    check([r["routerId"] for r in taken] == ["", "router:default", "", "router:b"]
          and next(r for r in routers if r["id"] == "router:b")["inputs"] == ["skynet:proxy:23008"],
          "клиент не вход ни одного роутера, даже если сырой маршрут его называет; negative: порт агента, как раньше, "
          "уходит на канбан по умолчанию и остаётся входом своего канбана")
    check("models" not in normalize_agent_proxy_route({**base, "models": "all"})
          and "pool" not in normalize_agent_proxy_route({**base, "pool": "std"})
          and "set" not in normalize_agent_proxy_route({**base, "set": "chat"}),
          "negative: у порта агента нет ни списка, ни пула, ни набора")
    check(normalize_agent_proxy_route({**base, "kind": "bogus"})["kind"] == "",
          "negative: незнакомый вид — порт агента")
    routes = [{"label": "c", "kind": "consumer", "upstreamType": "cloud", "providerId": "std", "cloudFallbackProviderId": "x"},
              {"label": "c", "upstreamType": "llama"}]
    recompute_cloud_fallback_eligibility(routes)
    check(routes[0]["cloudFallbackProviderId"] == "x" and routes[1]["cloudFallbackEligible"] is False,
          "клиент не трогается правилом ↑☁ и не служит облачным братом порту с тем же именем")
    keep = pc.PolicyOwnedFields([{"port": 23005, "apiKey": "lcv1_secret", "set": "chat", "portClosed": True},
                                 {"port": 23006, "apiKey": "lcv1_older", "pool": "std"}])
    check(keep.kept({"port": 23005, "label": "c"}) == {"port": 23005, "label": "c", "apiKey": "lcv1_secret",
                                                       "set": "chat", "portClosed": True},
          "сохранение со страницы без ключа и набора клиента их не стирает (1.3.497: набор стирался бы — клиент терял модели)")
    check(keep.kept({"port": 23006})["pool"] == "std", "у клиента с одним пулом, ещё не переписанного, пул тоже не стирается")
    check(keep.kept({"port": 23005, "apiKey": "", "set": ""})["set"] == "",
          "negative: поле, названное явно, — слово отправителя, как и раньше")


def test_old_give_key():
    print("старая «Выдать ключ» — не для клиента:")
    pc.write_agent_proxy_payload({"routes": [{"label": "c", "port": 23007, "kind": "consumer", "apiKey": "lcv1_c",
                                              "portClosed": True, "set": "chat", "upstreamHost": "127.0.0.1",
                                              "upstreamPort": 1}],
                                  "entry": {"port": 23999}, "routers": []})
    try:
        pc.RouteKeys().issue(23007)
        said = None
    except AppError as exc:
        said = (exc.status, "on its card" in str(exc))
    check(said == (409, True), f"у клиента ключ уже есть: 409, и сказано, где его меняют — на карточке клиента (got {said})")
    check(pc.load_agent_proxy_config()["routes"][0]["set"] == "chat",
          "набор клиента проходит чтение и запись файла")
    try:
        pc.set_agent_proxy_route_policy(23007, {"routerId": "router:default"})
        said = None
    except AppError as exc:
        said = (exc.status, "cable it to a set" in str(exc))
    check(said == (400, True) and pc.load_agent_proxy_config()["routes"][0]["routerId"] == "",
          f"negative: клиента не ставят на роутер — 400, и сказано, что его канат ведёт к набору; ничего не записано (got {said})")
    key = pc.RouteKeys(token=lambda: "f" * 48).new()
    check(key == "lcv1_" + "f" * 48, "новый ключ — приставка и 48 знаков")


def test_board():
    print("доска получает четыре знака, набор клиента и его модели:")
    consumer = {"label": "Hermes", "port": 23009, "kind": "consumer", "apiKey": "lcv1_secretABCD", "set": "chat",
                "upstreamPort": 1}
    proxy = _board_proxy(consumer, holders={}, last_seen={}, routers_by_id={})
    check("apiKey" not in proxy and proxy["keyTail"] == "ABCD", "ключа клиента на доске нет — только четыре последних знака")
    agent = _board_proxy({"label": "old", "port": 23011, "apiKey": "lcv1_oldWXYZ", "upstreamPort": 1},
                         holders={}, last_seen={}, routers_by_id={})
    check(agent["apiKey"] == "lcv1_oldWXYZ", "negative: у порта агента форма ✎ правит ключ — его ключ остаётся как был")
    pools = POOLS + [{"id": "big", "name": "Big Brain"}]
    proxies = annotate_consumer_set([proxy, agent, {"kind": "consumer", "models": "all"}, {"kind": "consumer", "set": "gone"},
                                     {"kind": "consumer", "set": ""}, {"kind": "consumer", "pool": "eco"}, "junk"],
                                    EntryModels(pools, SETS))
    view = lambda p: (p["set"], p["setName"], p["models"])
    check(view(proxies[0]) == ("chat", "Chat", ["Standart", "Econom"]),
          "набор клиента — id для каната, имя для строки и модели его ключа по именам, в порядке набора")
    check(view(proxies[2]) == ("", "", ["Standart"]) and view(proxies[5]) == ("", "", ["Econom"]) and "pool" not in proxies[5],
          "клиент старого вида — без набора, но с моделью, которую зовёт прокси; старые поля доске не отданы")
    check([view(p) for p in proxies[3:5]] == [("", "", []), ("", "", [])],
          "negative: пропавший набор и снятый канат — набора и моделей нет, а не догадка")
    check(not {"set", "setName", "models", "pool"} & set(proxies[1]), "negative: у порта агента набора нет")


def test_rename():
    print("переименование клиента (2026-10-11: дверь маршрута брала любое имя):")
    consumer = lambda port, name: {"label": name, "port": port, "kind": "consumer", "apiKey": f"lcv1_c{port}", "portClosed": True,
                                   "set": "", "upstreamType": "cloud", "routerId": "", "upstreamHost": "127.0.0.1", "upstreamPort": 1}
    pc.write_agent_proxy_payload({"routes": [consumer(23101, "Hermes"), consumer(23102, "Bot"),
                                             {"label": "old agent", "port": 23103, "apiKey": "lcv1_old", "upstreamHost": "127.0.0.1",
                                              "upstreamPort": 1}], "entry": {"port": 23999}, "routers": []})
    names = lambda: [r.get("label") for r in pc.load_agent_proxy_config()["routes"]]
    check(refused(pc.set_agent_proxy_route_policy, 23102, {"label": " hermes "}) == 409 and names()[:2] == ["Hermes", "Bot"],
          "имя другого клиента, в любом регистре, — 409, как при создании, и ничего не записано")
    pc.set_agent_proxy_route_policy(23101, {"label": "HERMES"})
    pc.set_agent_proxy_route_policy(23102, {"label": " Sinapse "})
    check(names()[:2] == ["HERMES", "Sinapse"], "своё имя в другом регистре и новое имя — можно; пробелы срезаны")
    pc.set_agent_proxy_route_policy(23103, {"label": "Sinapse"})
    check(names()[2] == "Sinapse", "negative: порт агента старого вида — не клиент входа, правило имён клиентов его не касается")


for fn in (test_create, test_set_and_key, test_migrate, test_route_rules, test_old_give_key, test_board, test_rename):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("consumers admin snapshot holds")
