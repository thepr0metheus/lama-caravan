#!/usr/bin/env python3
"""Adding a scout from the board, and letting it go (caravan/admin/scout_pairing.py).

The machine only installs its scout; the controller pairs it. Pinned by value
against a scout that is a pair of functions: what the operator may type, which
address of the controller the scout is handed, what reaches the scout and in
which order, how each way of failing is worded — and that letting go asks the
scout first, forgets the machine either way when the scout is silent, and
keeps it when the scout refuses.

Run: python3 scripts/test_scout_pairing.py
"""
import io
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.scout_pairing import ScoutPairing  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


TOKEN = {"X-Caravan-Token": "fleet-t0k3n"}
INFO = {"service": "caravan-scout", "version": "2.1.0", "hostId": "box-a", "port": 8092,
        "controllerUrl": "", "tokenRequired": False}


def http_error(url, code, body=b'{"error": "nope"}'):
    return urllib.error.HTTPError(url, code, "status", {}, io.BytesIO(body))


class FakeScout:
    """A scout as the controller's two calls see it: GET answers and POST
    answers by path, each an object or an exception; every call written down."""

    def __init__(self, get=None, post=None):
        self.get_answer = INFO if get is None else get
        self.post_answers = post or {}
        self.calls = []

    def http_get(self, url, timeout=None):
        self.calls.append(("GET", url, None, None))
        if isinstance(self.get_answer, BaseException):
            raise self.get_answer
        return self.get_answer

    def http_post(self, url, payload, timeout=None, headers=None):
        self.calls.append(("POST", url, payload, headers))
        for path, answer in self.post_answers.items():
            if url.endswith(path):
                if isinstance(answer, BaseException):
                    raise answer
                return answer
        return {"ok": True}


def paired(host=None):
    return {"ok": True, "controllerUrl": "http://10.0.0.1:7990",
            "heartbeat": {"state": "ok", "lastAt": 1, "result": {"ok": True, "host": host or {
                "id": "box-a", "name": "Box A", "scoutVersion": "2.1.0"}}}}


def pairing(scout, headers=TOKEN, store=None, advertised="10.0.0.1"):
    store = {"hosts": {}} if store is None else store
    saved = []
    p = ScoutPairing(lambda: store, lambda: saved.append(1), lambda: dict(headers), 7990, advertised,
                     http_get=scout.http_get, http_post=scout.http_post, facing_ip=lambda host: "10.9.9.9")
    return p, store, saved


def refusal(fn):
    try:
        fn()
    except AppError as exc:
        return exc.status, str(exc)
    return None


def test_what_can_be_typed():
    print("что можно ввести:")
    url = ScoutPairing.scout_url
    check(url("10.0.0.5") == "http://10.0.0.5:8092", "адрес без порта — порт скаута по умолчанию, 8092")
    check(url("10.0.0.5", "9000") == "http://10.0.0.5:9000", "порт из своего поля")
    check(url(" http://gpu-box.lan:8093/ ") == "http://gpu-box.lan:8093",
          "схема, хвост и порт в самом адресе понимаются; имя машины годится")
    check(url("10.0.0.5:8093", "9000") == "http://10.0.0.5:9000",
          "boundary: порт в поле сильнее порта в адресе")
    for bad, want in (("", "enter the machine's address — an IP or a host name"),
                      ("bad host!", "enter the machine's address — an IP or a host name"),
                      ("-lead", "enter the machine's address — an IP or a host name")):
        check(refusal(lambda b=bad: url(b)) == (400, want), f"negative: {bad!r} — отказ 400 с подсказкой")
    for port in ("0", "65536", "80a"):
        check(refusal(lambda p=port: url("10.0.0.5", p)) == (400, "the port must be a number from 1 to 65535"),
              f"negative: порт {port!r} — отказ 400")


def test_which_controller_address():
    print("какой адрес контроллера получает скаут:")
    p, _s, _v = pairing(FakeScout())
    check(p.controller_url_for("http://127.0.0.1:8092") == "http://127.0.0.1:7990"
          and p.controller_url_for("http://localhost:8092") == "http://127.0.0.1:7990",
          "скаут на машине контроллера получает 127.0.0.1")
    check(p.controller_url_for("http://10.0.0.5:8092") == "http://10.0.0.1:7990",
          "любой другой — заданный адрес контроллера в сети")
    p, _s, _v = pairing(FakeScout(), advertised="127.0.0.1")
    check(p.controller_url_for("http://10.0.0.5:8092") == "http://10.9.9.9:7990",
          "negative: заданный адрес — петля: скаут получает адрес интерфейса, что смотрит на него, а не 127.0.0.1")


def test_connect():
    print("подключение:")
    scout = FakeScout(post={"/api/controller-url": paired()})
    p, store, _saved = pairing(scout)
    got = p.connect("10.0.0.5", "")
    check(got == {"ok": True, "hostId": "box-a", "name": "Box A", "scoutVersion": "2.1.0",
                  "scoutUrl": "http://10.0.0.5:8092", "controllerUrl": "http://10.0.0.1:7990"},
          "ответ: машина, версия скаута, где скаут и какой адрес контроллера он получил")
    check([c[:2] for c in scout.calls] == [("GET", "http://10.0.0.5:8092/api/pairing"),
                                          ("POST", "http://10.0.0.5:8092/api/controller-url")],
          "сначала открытый /api/pairing — что там скаут, потом сопряжение")
    check(scout.calls[1][2] == {"url": "http://10.0.0.1:7990", "token": "fleet-t0k3n"} and scout.calls[1][3] == TOKEN,
          "скауту уходят адрес контроллера и токен флота — в теле и в заголовке")
    check(store == {"hosts": {}}, "negative: запись машины делает сам пульс скаута, не подключение")
    scout = FakeScout(post={"/api/controller-url": paired()})
    p, _store, _saved = pairing(scout, headers={})
    p.connect("10.0.0.5")
    check(scout.calls[1][2] == {"url": "http://10.0.0.1:7990", "token": ""} and scout.calls[1][3] == {},
          "вход выключен — токена нет ни в теле, ни в заголовке")


def test_connect_refusals():
    print("подключение не удалось — и почему:")
    cases = (
        (FakeScout(get=urllib.error.URLError("Connection refused")),
         (502, "no scout answers at http://10.0.0.5:8092: Connection refused — is ./install.sh done there, "
               "and is the port open?"), "никто не отвечает"),
        (FakeScout(get=http_error("u", 404)),
         (409, "a scout older than 2.0 answers at http://10.0.0.5:8092 — update it: git pull and "
               "./install.sh on that machine"), "скаут старше 2.0 (нет /api/pairing)"),
        (FakeScout(get={"service": "something-else"}),
         (502, "something other than a caravan-scout answers at http://10.0.0.5:8092"), "там не скаут"),
        (FakeScout(get=ValueError("Expecting value")),
         (502, "something other than a caravan-scout answers at http://10.0.0.5:8092"), "ответ не JSON"),
        (FakeScout(post={"/api/controller-url": http_error("u", 401)}),
         (409, "the scout at http://10.0.0.5:8092 is paired with another controller (it holds a different "
               "fleet token) — take it off there first, or on that machine run ./uninstall.sh and ./install.sh"),
         "скаут держит чужой токен"),
        (FakeScout(post={"/api/controller-url": {"ok": True, "heartbeat": {"state": "error",
                                                                           "error": "timed out"}}}),
         (502, "the scout at http://10.0.0.5:8092 took the controller's address (http://10.0.0.1:7990) but "
               "cannot reach it: timed out — open port 7990 on the controller to that machine"),
         "скаут взял адрес, но не достучался обратно"),
        (FakeScout(post={"/api/controller-url": {"ok": True}}),
         (502, "the scout at http://10.0.0.5:8092 took the controller's address (http://10.0.0.1:7990) but "
               "cannot reach it: no answer — open port 7990 on the controller to that machine"),
         "as-is: в ответе нет пульса вовсе (между ними что-то другое) — считается, что не достучался"),
        (FakeScout(post={"/api/controller-url": http_error("u", 400, b'{"error": "bad url"}')}),
         (502, "the scout at http://10.0.0.5:8092 refused: bad url"), "скаут отказал своими словами"),
    )
    for scout, want, why in cases:
        p, _store, _saved = pairing(scout)
        check(refusal(lambda: p.connect("10.0.0.5")) == want, f"negative: {why} — {want[0]}, и сказано, что делать")


def test_disconnect():
    print("отключение:")
    host = {"id": "box-a", "agentUrl": "http://10.0.0.5:8092"}
    scout = FakeScout()
    client = {"id": "box-a", "name": "Client A", "agents": [{"id": "a"}]}
    p, store, saved = pairing(scout, store={"hosts": {"box-a": dict(host), "box-b": {"id": "box-b"}},
                                            "clients": {"box-a": dict(client)},
                                            "assignments": {"box-a": {"assignments": [{"agentId": "a"}]}}})
    got = p.disconnect(" box-a ")
    check(got == {"ok": True, "hostId": "box-a", "unpaired": True} and set(store["hosts"]) == {"box-b"} and saved == [1],
          "скаут отпущен, машина забыта, соседняя цела, состояние сохранено")
    check(store["clients"] == {"box-a": client} and store["assignments"] == {"box-a": {"assignments": [{"agentId": "a"}]}},
          "negative: клиент с тем же id и его назначения не тронуты — это запись оператора, а не машины")
    check(scout.calls == [("POST", "http://10.0.0.5:8092/api/unpair", {}, TOKEN)],
          "скауту — /api/unpair с токеном флота")
    for answer, why in ((urllib.error.URLError("No route to host"), "скаут молчит"),
                        (http_error("u", 404), "скаут старше 2.1 — отпустить его нечем")):
        p, store, _saved = pairing(FakeScout(post={"/api/unpair": answer}), store={"hosts": {"box-a": dict(host)}})
        got = p.disconnect("box-a")
        check(got == {"ok": True, "hostId": "box-a", "unpaired": False} and store["hosts"] == {},
              f"{why} — машина всё равно забыта, и ответ говорит, что скаут не отпущен")
    p, store, saved = pairing(FakeScout(post={"/api/unpair": http_error("u", 401, b'{"error": "fleet token required"}')}),
                              store={"hosts": {"box-a": dict(host)}})
    check(refusal(lambda: p.disconnect("box-a")) == (502, "the scout of box-a refused to let go: fleet token required")
          and store["hosts"] == {"box-a": host} and saved == [],
          "negative: скаут отказал — машина остаётся: забыть её значило бы потерять ту, что всё ещё отчитывается")
    p, store, _saved = pairing(FakeScout(), store={"hosts": {"box-c": {"id": "box-c"}}})
    check(p.disconnect("box-c") == {"ok": True, "hostId": "box-c", "unpaired": False} and store["hosts"] == {},
          "boundary: у записи нет адреса скаута — только забыть")
    p, _store, _saved = pairing(FakeScout())
    check(refusal(lambda: p.disconnect("nope")) == (404, "host not found: nope")
          and refusal(lambda: p.disconnect("  ")) == (400, "hostId is required"),
          "negative: неизвестная машина — 404, пустой id — 400")


def test_move_host_cells():
    print("ячейки машины переезжают под её новое имя:")
    import caravan.admin.server_cells as sc
    slot = lambda host, port, **kw: {"id": f"{host}:{port}", "hostId": host, "port": port, "createdAt": 1, **kw}
    store = {"serverSlots": {
        "box-a:22021": slot("box-a", 22021, model="gemma-4-12B-it-Q5_K_M.gguf", config={"CTX_SIZE": "8192"},
                              note="translator", label="gemma"),
        "box-a:22015": slot("box-a", 22015),
        "box-b:22030": slot("box-b", 22030),
        "controller:22001": slot("controller", 22001),
    }}
    saved = []
    orig = (sc.topology_store, sc.save_admin_state)
    sc.topology_store, sc.save_admin_state = (lambda: store), (lambda: saved.append(1))
    try:
        got = sc.move_host_cells({"from": "box-a", "to": " box-a-pc "})
        check(got == {"ok": True, "from": "box-a", "to": "box-a-pc", "ports": [22015, 22021]} and saved == [1],
              "ответ называет, что куда переехало, по возрастанию порта; состояние сохранено")
        moved = store["serverSlots"].get("box-a-pc:22021") or {}
        check(sorted(store["serverSlots"]) == ["box-a-pc:22015", "box-a-pc:22021", "box-b:22030", "controller:22001"],
              "под старым именем не осталось ни одной ячейки; чужие и ячейки контроллера не тронуты")
        check((moved.get("id"), moved.get("hostId"), moved.get("model"), moved.get("config"), moved.get("note"),
               moved.get("label"), moved.get("createdAt")) ==
              ("box-a-pc:22021", "box-a-pc", "gemma-4-12B-it-Q5_K_M.gguf", {"CTX_SIZE": "8192"}, "translator", "gemma", 1),
              "ячейка переехала целиком: модель, конфиг, заметка, подпись, время создания — меняются только имя машины и ключ")

        def refused(body):
            try:
                sc.move_host_cells(body)
            except AppError as exc:
                return exc.status, str(exc)
            return None
        store["serverSlots"]["box-a:22030"] = slot("box-a", 22030)
        check(refused({"from": "box-a", "to": "box-b"}) == (409, "box-b already has cells on :22030")
              and "box-a:22030" in store["serverSlots"],
              "negative: у новой машины уже есть ячейка на том же порту — отказ 409, ничего не сдвинуто")
        check(refused({"from": "nobody", "to": "x"}) == (404, "no cells are configured on nobody"),
              "negative: у машины нет ячеек — 404, а не тихий успех")
        check(refused({"from": "box-a", "to": "controller"}) == (400, "the controller's own cells stay with the controller")
              and refused({"from": "controller", "to": "x"}) == (400, "the controller's own cells stay with the controller"),
              "negative: ячейки контроллера не переезжают, и на контроллер тоже")
        check(refused({"from": "a", "to": "a"}) == (400, "from and to are the same machine")
              and refused({"from": "", "to": "x"}) == (400, "both machines are required: from and to"),
              "negative: одна и та же машина или пустое имя — 400")
    finally:
        sc.topology_store, sc.save_admin_state = orig


for fn in (test_what_can_be_typed, test_which_controller_address, test_connect, test_connect_refusals,
           test_disconnect, test_move_host_cells):
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — a crash is a red pin; the rest still runs
        check(False, f"{fn.__name__} упал: {exc!r}")

if _fail:
    print(f"\nFAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("\nscout pairing OK")
