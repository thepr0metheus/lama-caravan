#!/usr/bin/env python3
"""Loading and unloading an engine's model from the board (step 3).

caravan/admin/engine_actions.py, EngineActions: the controller asks the
machine's scout (scout 2.14+) to load a model into Ollama or LM Studio, or
unload it, and puts the engines the scout answers with into the host record
at once — the board shows "loading…" on its next read. Pinned by value: what
reaches the scout (path, body, timeout), what is refused before it, what the
record keeps; and the route that reads the action from its path. The scout
is a stand-in; nothing reaches a network.

Run: python3 scripts/test_engine_actions.py
"""
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# The route test imports the admin's routes: its state goes to a scratch
# directory, never to the machine's own.
_TMP = Path(tempfile.mkdtemp(prefix="caravan-engine-actions-"))
os.environ["CARAVAN_DATA_DIR"] = str(_TMP / "data")
os.environ["LLAMA_ADMIN_STATE"] = str(_TMP / "data" / "admin.json")
from caravan.admin.engine_actions import EngineActions  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def same(actual, expected, msg):
    check(actual == expected, msg if actual == expected else f"{msg}\n        got:  {actual!r}\n        want: {expected!r}")


def refusal(fn):
    try:
        fn()
    except AppError as exc:
        return (exc.status, str(exc))
    return None


class FakeScout:
    """A machine's scout: records every call, answers with `answer` or raises."""

    def __init__(self, answer=None, raises=None):
        self.answer = answer
        self.raises = raises
        self.calls = []

    def post(self, path, payload=None, timeout=10):
        self.calls.append((path, payload, timeout))
        if self.raises:
            raise self.raises
        return self.answer


ENGINE = {"kind": "ollama", "label": "Ollama", "port": 11500, "listen": "network", "state": "ok",
          "models": [{"name": "qwen3:8b", "loaded": True}], "controls": ["unload", "delete"]}
AFTER = [{**ENGINE, "models": [{"name": "qwen3:8b", "loaded": True, "action": {"op": "unload", "since": 7}}]}]


def rig(answer=None, raises=None, hosts=None):
    scouts = {}
    saves = []
    store = {"hosts": {"box-a": {"id": "box-a", "engines": [dict(ENGINE)]}}}

    def scout_for(host_id):
        return scouts.setdefault(host_id, FakeScout(answer, raises))

    actions = EngineActions(scout_for, lambda: hosts if hosts is not None else [dict(store["hosts"]["box-a"])],
                            store=lambda: store, save=lambda: saves.append(1))
    return actions, scouts, store, saves


def test_act():
    print("выгрузить и удалить модель движка через скаут:")
    actions, scouts, store, saves = rig(answer={"ok": True, "engines": AFTER})
    got = actions.act("box-a", "unload", "ollama", "qwen3:8b")
    same(got, {"ok": True, "hostId": "box-a", "kind": "ollama", "model": "qwen3:8b", "op": "unload"}, "ответ — что сделано")
    same(scouts["box-a"].calls, [("/api/engines/unload", {"kind": "ollama", "port": 11500, "model": "qwen3:8b"}, 15)],
         "скауту — вид, порт движка из записи машины и модель; ждать — секунды (скаут отвечает сразу)")
    same((store["hosts"]["box-a"]["engines"][0]["models"][0]["action"], len(saves)), ({"op": "unload", "since": 7}, 1),
         "движки из ответа скаута — сразу в запись машины: доска покажет «выгружается» на следующем чтении")
    actions, scouts, store, saves = rig(answer={"ok": True, "engines": AFTER})
    got = actions.act("box-a", "delete", "ollama", "qwen3:8b")
    same((scouts["box-a"].calls[0][:2], got["op"]),
         (("/api/engines/delete", {"kind": "ollama", "port": 11500, "model": "qwen3:8b"}), "delete"),
         "удаление — и в ответе удаление")
    actions, scouts, store, saves = rig(answer={"ok": True, "engines": []})
    actions.act("box-a", "unload", "ollama", "qwen3:8b")
    same((store["hosts"]["box-a"]["engines"], len(saves)), ([], 1),
         "boundary: скаут сказал «движков нет» — это тоже ответ, и он записан")
    actions, scouts, store, saves = rig(answer={"ok": True})
    actions.act("box-a", "unload", "ollama", "qwen3:8b")
    same((store["hosts"]["box-a"]["engines"], len(saves)), ([ENGINE], 0),
         "negative: скаут не назвал движков — запись не тронута и не сохранена (не стёрта в «нет движков»)")
    actions, *_r = rig(raises=AppError("box-a: qwen3:8b is not loaded", 502))
    same(refusal(lambda: actions.act("box-a", "unload", "ollama", "qwen3:8b")),
         (502, "box-a: qwen3:8b is not loaded"), "отказ скаута — его словами, как есть")

    actions, scouts, *_r = rig(answer={"ok": True, "engines": AFTER})
    for args, want in ((("box-a", "stop", "ollama", "m"), (400, "unknown engine action 'stop'")),
                       (("box-a", "load", "ollama", "m"), (400, "unknown engine action 'load'")),
                       (("", "unload", "ollama", "m"), (400, "hostId, kind and model are required")),
                       (("box-a", "unload", "", "m"), (400, "hostId, kind and model are required")),
                       (("box-a", "unload", "ollama", " "), (400, "hostId, kind and model are required")),
                       (("box-z", "unload", "ollama", "m"), (404, "no scout has reported for host box-z")),
                       (("box-a", "unload", "lmstudio", "m"), (404, "box-a reports no lmstudio"))):
        same(refusal(lambda: actions.act(*args)), want, f"negative: {args[1]} {args[0] or '—'}/{args[2] or '—'} — {want[1]}")
    same(scouts, {}, "negative: ни один отказ до скаута не дошёл — и загрузка тоже: её с доски больше нет (2026-09-26)")


def test_route():
    print("маршрут POST /api/engines/unload|delete:")
    from caravan.admin import routes
    same([p in routes.POST_ROUTES for p in ("/api/engines/load", "/api/engines/unload", "/api/engines/delete",
                                            "/api/engines/start", "/api/engines/stop", "/api/engines/pause")],
         [False, True, True, True, True, False],
         "выгрузка, удаление и пуск/остановка сервера — маршруты; загрузки нет: модель грузит ячейка в движке")

    class _H:
        def __init__(self):
            self.sent = []

        def send_json(self, doc, *a, **kw):
            self.sent.append(doc)

    seen = []
    real_act, real_state = EngineActions.act, routes.topology_state
    try:
        EngineActions.act = lambda self, *a, **kw: (seen.append((*a, kw)), {"ok": True, "op": a[1]})[1]
        routes.topology_state = lambda **kw: {"board": True, **kw}
        sent = []
        for path in ("/api/engines/unload", "/api/engines/delete"):
            h = _H()
            routes._post_api_engines_act(h, types.SimpleNamespace(path=path),
                                         {"hostId": "box-a", "kind": "ollama", "model": "qwen3:8b", "contextLength": 8192,
                                          "force": True, "hold": 900})
            sent += h.sent
    finally:
        EngineActions.act, routes.topology_state = real_act, real_state
    same(seen, [("box-a", "unload", "ollama", "qwen3:8b", {}), ("box-a", "delete", "ollama", "qwen3:8b", {})],
         "действие — из пути, машина, движок и модель — из тела; окно, force и срок загрузки больше никуда не идут")
    same(sent, [{"ok": True, "op": op, "topology": {"board": True, "refresh_hosts": False}} for op in ("unload", "delete")],
         "ответ — что сделано и доска, без нового опроса машин")


def test_serve():
    print("пуск и остановка сервера движка через скаут (скаут 2.16):")
    stopping = [{**ENGINE, "serverAction": {"op": "stop", "since": 7}}]
    actions, scouts, store, saves = rig(answer={"ok": True, "engines": stopping})
    same(actions.serve("box-a", "stop", "ollama"), {"ok": True, "hostId": "box-a", "kind": "ollama", "op": "stop"},
         "ответ — что сделано")
    same(scouts["box-a"].calls, [("/api/engines/stop", {"kind": "ollama", "port": 11500}, 15)],
         "скауту — вид и порт движка из записи машины; ждать секунды (скаут отвечает сразу)")
    same((store["hosts"]["box-a"]["engines"][0]["serverAction"], len(saves)), ({"op": "stop", "since": 7}, 1),
         "движки из ответа — сразу в запись машины: «останавливается» видно на следующем чтении")
    actions, scouts, store, saves = rig(answer={"ok": True})
    actions.serve("box-a", "start", "ollama")
    same((scouts["box-a"].calls[0][0], store["hosts"]["box-a"]["engines"], len(saves)),
         ("/api/engines/start", [ENGINE], 0), "negative: скаут не назвал движков — запись не тронута")
    actions, scouts, *_r = rig(answer={"ok": True})
    for args, want in ((("box-a", "reboot", "ollama"), (400, "unknown engine action 'reboot'")),
                       (("box-a", "load", "ollama"), (400, "unknown engine action 'load'")),
                       (("", "start", "ollama"), (400, "hostId and kind are required")),
                       (("box-a", "start", " "), (400, "hostId and kind are required")),
                       (("box-z", "start", "ollama"), (404, "no scout has reported for host box-z")),
                       (("box-a", "start", "lmstudio"), (404, "box-a reports no lmstudio"))):
        same(refusal(lambda: actions.serve(*args)), want, f"negative: {args[1]} {args[0] or '—'}/{args[2].strip() or '—'} — {want[1]}")
    same(scouts, {}, "negative: ни один отказ до скаута не дошёл")

    from caravan.admin import routes

    class _H:
        def __init__(self):
            self.sent = []

        def send_json(self, doc, *a, **kw):
            self.sent.append(doc)

    seen = []
    real_serve, real_state = EngineActions.serve, routes.topology_state
    try:
        EngineActions.serve = lambda self, *a: (seen.append(a), {"ok": True, "op": a[1]})[1]
        routes.topology_state = lambda **kw: {"board": True, **kw}
        sent = []
        for path in ("/api/engines/start", "/api/engines/stop"):
            h = _H()
            routes._post_api_engines_serve(h, types.SimpleNamespace(path=path), {"hostId": "box-a", "kind": "ollama"})
            sent += h.sent
    finally:
        EngineActions.serve, routes.topology_state = real_serve, real_state
    same(seen, [("box-a", "start", "ollama"), ("box-a", "stop", "ollama")], "маршрут: действие — из пути")
    same(sent, [{"ok": True, "op": op, "topology": {"board": True, "refresh_hosts": False}} for op in ("start", "stop")],
         "ответ — что сделано и доска, без нового опроса машин")


def test_pull_delete():
    print("скачать в движок и удалить модель через скаут (скаут 2.17):")
    downloading = [{**ENGINE, "downloading": {"model": "qwen3:4b", "since": 7, "doneBytes": None, "totalBytes": None}}]
    actions, scouts, store, saves = rig(answer={"ok": True, "engines": downloading})
    same(actions.pull("box-a", "ollama", " qwen3:4b "),
         {"ok": True, "hostId": "box-a", "kind": "ollama", "model": "qwen3:4b", "op": "pull"}, "ответ — что сделано")
    same((scouts["box-a"].calls, store["hosts"]["box-a"]["engines"][0]["downloading"]["model"], len(saves)),
         ([("/api/engines/pull", {"kind": "ollama", "port": 11500, "model": "qwen3:4b"}, 15)], "qwen3:4b", 1),
         "скауту — вид, порт движка и имя; движки из ответа — сразу в запись машины")
    actions, scouts, *_r = rig(answer={"ok": True})
    for args, want in ((("box-a", "ollama", ""), (400, "hostId, kind and model are required")),
                       (("", "ollama", "m"), (400, "hostId, kind and model are required")),
                       (("box-z", "ollama", "m"), (404, "no scout has reported for host box-z")),
                       (("box-a", "lmstudio", "m"), (404, "box-a reports no lmstudio"))):
        same(refusal(lambda: actions.pull(*args)), want, f"negative: скачать {args[2] or '—'} на {args[0] or '—'}/{args[1]} — {want[1]}")
    same(scouts, {}, "negative: ни один отказ до скаута не дошёл")
    actions, scouts, store, saves = rig(answer={"ok": True, "engines": AFTER})
    actions.act("box-a", "delete", "ollama", "qwen3:8b")
    same(scouts["box-a"].calls[0][:2], ("/api/engines/delete", {"kind": "ollama", "port": 11500, "model": "qwen3:8b"}),
         "удаление модели — то же действие над моделью, что загрузка")

    from caravan.admin import routes
    same(["/api/engines/delete" in routes.POST_ROUTES, "/api/engines/pull" in routes.POST_ROUTES], [True, True],
         "маршруты удаления и скачивания есть")

    class _H:
        def __init__(self):
            self.sent = []

        def send_json(self, doc, *a, **kw):
            self.sent.append(doc)

    seen = []
    real_pull, real_state = EngineActions.pull, routes.topology_state
    try:
        EngineActions.pull = lambda self, *a: (seen.append(a), {"ok": True, "op": "pull"})[1]
        routes.topology_state = lambda **kw: {"board": True, **kw}
        h = _H()
        routes._post_api_engines_pull(h, types.SimpleNamespace(path="/api/engines/pull"),
                                      {"hostId": "box-a", "kind": "lmstudio", "model": "qwen/qwen3-4b"})
    finally:
        EngineActions.pull, routes.topology_state = real_pull, real_state
    same((seen, h.sent), ([("box-a", "lmstudio", "qwen/qwen3-4b")],
                          [{"ok": True, "op": "pull", "topology": {"board": True, "refresh_hosts": False}}]),
         "маршрут скачивания: машина, движок, имя — как есть; ответ с доской")


for test in (test_act, test_route, test_serve, test_pull_delete):
    try:
        test()
    except Exception as exc:  # noqa: BLE001 — a crash is a red pin
        check(False, f"{test.__name__} упал: {exc!r}")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for f in _fail:
        print("  - " + f.splitlines()[0])
    sys.exit(1)
print("engine actions OK")
