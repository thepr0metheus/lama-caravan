#!/usr/bin/env python3
"""Value snapshot: the admin API described as OpenAPI (GET /openapi.json).

2026-09-29: an agent writing tests for the caravan asked for its Swagger. There
was none — only a hand-written list in docs/http-api.md that had fallen 16
paths behind the 164 it covered. The operator chose: generate it from the
code, level 1 (every route, what it does, what it reads, who may call it). The
home rule on visumap (apps-openapi.md) makes /openapi.json every app's.

Pinned by value, positive and negative for every claim:
- reading a handler's own code: the query parameters and body fields it reads
  in source order; a query or body handed on whole is "may read more", never
  "reads nothing"; the content types it answers with, two helpers deep;
- who may call a route: one rule (RouteAccess) for the guard that enforces it
  and for the document that states it — the guard itself is driven here;
- the document: every registered route and nothing else, the version, what is
  not described said out loud, /openapi.json open;
- the page for people (docs/http-api.md) rendered from the same document.

Run: python3 scripts/test_api_spec.py
"""
import os
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("CARAVAN_DATA_DIR", tempfile.mkdtemp(prefix="caravan-api-spec-"))
sys.path.insert(0, str(ROOT))

from caravan import __version__  # noqa: E402
from caravan.admin import routes  # noqa: E402
from caravan.admin.api_spec import ApiReference, ApiSpec, HandlerReading  # noqa: E402
from caravan.admin.route_access import ROUTE_ACCESS, RouteAccess  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# -- synthetic handlers: the reading rules, apart from any real route --------

def _flag(query, name, default=False):
    return bool(query.get(name))


def _redirect(handler, where):
    handler.send_response(302)
    handler.send_header("Location", where)


def _page(handler):
    handler.send_file(ROOT / "static" / "index.html", "text/html; charset=utf-8")


def s_reads_query(h, parsed):
    """Read four parameters

    Two ways into the same dict, and one inline."""
    q = urllib.parse.parse_qs(parsed.query or "")
    alpha = (q.get("alpha") or [""])[0]
    force = _flag(urllib.parse.parse_qs(parsed.query or ""), "force")
    beta = q["beta"][0]
    if "gamma" in q:
        alpha += beta
    h.send_json({"alpha": alpha, "force": force})


def s_reads_nested_first(h, parsed):
    """Read a nested parameter before a plain one"""
    q = urllib.parse.parse_qs(parsed.query or "")
    if parsed.path:
        first = q.get("first")
    second = q.get("second")
    h.send_json({"first": first, "second": second})


def s_hands_query_on(h, parsed):
    """Hand the raw query to a helper"""
    q = urllib.parse.parse_qs(parsed.query or "")
    _ = q.get("known")
    _serve(h, parsed.query)


def s_walks_query(h, parsed):
    """Iterate the query"""
    q = urllib.parse.parse_qs(parsed.query or "")
    h.send_json({key: q[key] for key in q})


def s_hands_request_on(h, parsed):
    """Hand the whole request on"""
    h.send_json(_describe(parsed))


def s_reads_body(h, parsed, body):
    """Read two fields"""
    if not isinstance(body, dict) or not body:
        return
    ident = body.get("id")
    value = body["value"]
    h.send_json({"id": ident, "value": value})


def s_passes_body(h, parsed, body):
    """Save the whole body"""
    name = body.get("name")
    _save(body)
    h.send_json({"name": name})


def s_ignores_body(h, parsed, body):
    """Answer without reading the body"""
    h.send_json({"ok": True})


def s_answers_many(h, parsed):
    """Answer a page, a redirect or a stream"""
    if parsed.path == "/a":
        _redirect(h, "/b")
    elif parsed.path == "/c":
        _page(h)
    else:
        h.send_response(200)
        h.send_header("Content-Type", "application/octet-stream")


def s_answer_elsewhere(h, parsed):
    """Let an unreadable helper answer"""
    print(h)


def _serve(h, query):
    h.send_json({})


def _describe(parsed):
    return {}


def _save(body):
    return body


def test_reading():
    print("что обработчик читает — по его коду:")
    names, complete = HandlerReading(s_reads_query).query()
    check((names, complete) == (["alpha", "force", "beta", "gamma"], True),
          f"параметры в порядке кода: .get, _flag(parse_qs(...)), [..], in — и это все (got {names}, {complete})")
    check(HandlerReading(s_reads_nested_first).query() == (["first", "second"], True),
          "порядок — как в коде, а не как обходит дерево (вложенное чтение раньше — первым)")
    names, complete = HandlerReading(s_hands_query_on).query()
    check((names, complete) == (["known"], False),
          f"negative: сырой query ушёл помощнику — «может читать больше», а не «читает одно» (got {names}, {complete})")
    check(HandlerReading(s_walks_query).query() == ([], False),
          "negative: обход словаря — не «параметров нет», а «не знаю каких»")
    check(HandlerReading(s_hands_request_on).query() == ([], False),
          "negative: запрос целиком ушёл дальше — «может читать больше»")
    reading = HandlerReading(s_reads_body)
    check(reading.body_fields() == (["id", "value"], True, True),
          f"поля тела в порядке кода; isinstance и «не пусто» — не чтение поля (got {reading.body_fields()})")
    check(HandlerReading(s_passes_body).body_fields() == (["name"], False, True),
          "negative: тело целиком ушло дальше — «может читать больше»")
    check(HandlerReading(s_ignores_body).body_fields() == ([], True, False),
          "negative: тело не читается вовсе — тела у операции нет")
    types, redirects, handed = HandlerReading(s_answers_many).answers()
    check((types, redirects, handed) == (["text/html", "application/octet-stream"], ["302"], False),
          f"ответы: заголовок, страница помощника и переадресация помощника — два вызова вглубь (got {types}, {redirects}, {handed})")
    check(HandlerReading(s_answer_elsewhere).answers() == ([], [], True),
          "negative: h ушёл в код, который не прочитать, — ответ «не весь», а не «пустой»")
    reading = HandlerReading(s_reads_query)
    check((reading.summary, reading.description) == ("Read four parameters", "Two ways into the same dict, and one inline."),
          "первая строка докстроки — summary, остальное — description")


class FakeHandler:
    def __init__(self, headers=None, session=None):
        self.headers = headers or {}
        self.session = session
        self.sent = []
        self.close_connection = False

    def send_json(self, payload, status=200):
        self.sent.append((status, payload.get("error")))

    def send_response(self, code):
        self.sent.append((code, None))

    def send_header(self, *args):
        pass

    def end_headers(self):
        pass


def test_access():
    print("кто может звать — одно правило для охраны и для описания:")
    kinds = {(m, p): ROUTE_ACCESS.kind(m, p) for m, p in (
        ("GET", "/openapi.json"), ("GET", "/health"), ("POST", "/api/auth/login"), ("GET", "/api/cell-assets"),
        ("POST", "/api/topology/client-heartbeat"), ("GET", "/api/topology/client-heartbeat"),
        ("GET", "/metrics"), ("GET", "/api/topology"), ("POST", "/api/cloud-blocks/save"))}
    check(kinds == {("GET", "/openapi.json"): "public", ("GET", "/health"): "public",
                    ("POST", "/api/auth/login"): "public", ("GET", "/api/cell-assets"): "machine",
                    ("POST", "/api/topology/client-heartbeat"): "machine",
                    ("GET", "/api/topology/client-heartbeat"): "session",
                    ("GET", "/metrics"): "metrics", ("GET", "/api/topology"): "session",
                    ("POST", "/api/cloud-blocks/save"): "session"},
          f"виды доступа; negative: GET по пути машинного POST — уже сессия (got {kinds})")
    check(ROUTE_ACCESS.viewer_may("GET", "/api/topology") and ROUTE_ACCESS.viewer_may("POST", "/api/auth/logout")
          and not ROUTE_ACCESS.viewer_may("POST", "/api/cloud-blocks/save"),
          "viewer: любой GET и выход; negative: любая правка — нет")
    check(ROUTE_ACCESS.security("POST", "/api/cloud-blocks/save") == {"security": [{"session": []}], "x-caravan-roles": ["admin"]}
          and ROUTE_ACCESS.security("GET", "/api/topology")["x-caravan-roles"] == ["admin", "viewer"]
          and ROUTE_ACCESS.security("GET", "/health") == {"security": []}
          and ROUTE_ACCESS.security("GET", "/metrics")["security"] == [{"fleetToken": []}, {"fleetBearer": []}, {"session": []}],
          "то же правило в словах OpenAPI: security и роли")

    saved = (routes.auth_mod.auth_enabled, routes.auth_mod.fleet_token_verify, routes.auth_mod.session_from_handler)
    routes.auth_mod.auth_enabled = lambda: True
    routes.auth_mod.fleet_token_verify = lambda candidate: candidate == "T"
    routes.auth_mod.session_from_handler = lambda h: h.session
    try:
        def guard(method, path, **kw):
            h = FakeHandler(**kw)
            return routes._auth_guard(h, path, method), h.sent

        check(guard("GET", "/openapi.json") == (True, []), "/openapi.json открыт без входа")
        check(guard("GET", "/api/topology") == (False, [(401, "authentication required")]),
              "negative: API без сессии — 401")
        check(guard("GET", "/board") == (False, [(302, None)]), "страница без сессии — на форму входа")
        check(guard("GET", "/api/cell-assets") == (False, [(401, "fleet token required (X-Caravan-Token)")])
              and guard("GET", "/api/cell-assets", headers={"X-Caravan-Token": "T"}) == (True, []),
              "машинный путь: без токена флота — 401, с токеном — пускает")
        check(guard("GET", "/metrics", headers={"Authorization": "Bearer T"}) == (True, []),
              "/metrics берёт токен флота и как Bearer")
        check(guard("GET", "/metrics") == (False, [(302, None)]),
              "as-is: /metrics без токена и сессии уходит на форму входа (302), а не 401")
        viewer = {"user": "v", "role": "viewer"}
        check(guard("POST", "/api/cloud-blocks/save", session=viewer) == (False, [(403, "read-only account")]),
              "negative: viewer не правит — 403")
        check(guard("POST", "/api/auth/logout", session=viewer) == (True, [])
              and guard("GET", "/api/topology", session=viewer) == (True, []),
              "viewer читает и выходит")
        check(guard("POST", "/api/cloud-blocks/save", session={"user": "a", "role": "admin"}) == (True, []),
              "admin правит")
        routes.auth_mod.auth_enabled = lambda: False
        check(guard("POST", "/api/cloud-blocks/save") == (True, []), "учёток ещё нет — открыто всё")
    finally:
        routes.auth_mod.auth_enabled, routes.auth_mod.fleet_token_verify, routes.auth_mod.session_from_handler = saved


def test_document():
    print("документ /openapi.json:")
    doc = routes.API_SPEC.build()
    ops = {(m.upper(), p) for p, methods in doc["paths"].items() for m in methods}
    expected = {("GET", p) for p in routes.GET_ROUTES} | {("POST", p) for p in routes.POST_ROUTES} \
        | {("DELETE", p) for p in routes.DELETE_ROUTES} | {("GET", r.template) for r in routes.GET_PREFIX_ROUTES}
    check(ops == expected, f"каждый маршрут таблиц и ничего сверх (лишних {sorted(ops - expected)[:3]}, "
                           f"недостающих {sorted(expected - ops)[:3]})")
    check(("GET", "/api/nope") not in ops, "negative: незарегистрированного пути в описании нет")
    ids = [op["operationId"] for methods in doc["paths"].values() for op in methods.values()]
    check(len(ids) == len(set(ids)), "operationId не повторяются")
    refusal = '`{"ok": false, "error": "…"}`'
    check(refusal in doc["info"]["description"] and refusal in doc["components"]["responses"]["Error"]["description"],
          "сказано, что часть отказов приходит 200 с ok: false — описание не обещает только статусы ошибок")
    check(doc["openapi"] == "3.1.0" and doc["info"]["version"] == __version__ and isinstance(doc["info"]["x-commit"], str),
          f"OpenAPI 3.1, версия каравана, коммит строкой (got {doc['openapi']}, {doc['info']['version']})")
    empty = [f"{m} {p}" for p, methods in doc["paths"].items() for m, op in methods.items() if not op["summary"]]
    check(empty == [], f"у каждой операции есть summary — из докстроки обработчика (без: {empty[:5]})")
    own = doc["paths"]["/openapi.json"]["get"]
    check(own["security"] == [] and "application/json" in own["responses"]["200"]["content"],
          "сам /openapi.json открыт и отдаёт JSON")
    usage = doc["paths"]["/api/cloud-accounts/usage-reserve"]["post"]
    schema = usage["requestBody"]["content"]["application/json"]["schema"]
    check(list(schema["properties"]) == ["id", "windowSeconds", "pct"] and "x-caravan-fields-complete" not in schema
          and usage["x-caravan-roles"] == ["admin"],
          f"тело запаса: id, windowSeconds, pct — и это все; только admin (got {list(schema['properties'])})")
    check("requestBody" not in doc["paths"]["/api/auth/logout"]["post"],
          "negative: выход тела не читает — тела у операции нет")
    download = doc["paths"]["/api/models/download"]["get"]
    check(download.get("x-caravan-query-complete") is False and download["security"] == [{"fleetToken": []}]
          and "application/octet-stream" in download["responses"]["200"]["content"],
          "скачивание модели: query уходит помощнику — «может больше»; токен флота; поток байт из помощника")
    monitor = doc["paths"].get("/api/monitor/{kind}", {}).get("get", {})
    check((monitor.get("parameters") or [None])[0] == {"name": "kind", "in": "path", "required": True,
                                                       "schema": {"type": "string"}},
          "префиксный маршрут — параметр пути с именем")
    check("302" in doc["paths"]["/"]["get"]["responses"], "корень переадресует — 302 прочитан у помощника")
    typed = [f"{m} {p}" for p, methods in doc["paths"].items() for m, op in methods.items()
             for c in op["responses"]["200"].get("content", {}).values() if "type" in c.get("schema", {})]
    check(typed == [] and ApiSpec.NOT_DESCRIBED in usage["responses"]["200"]["description"],
          "negative: формы ответов не выдуманы — вместо них сказано «не описано»")
    h = FakeHandler()
    sent = []
    h.send_json = lambda payload, status=200: sent.append((status, payload))
    routes._get_openapi(h, urllib.parse.urlparse("/openapi.json"))
    check(sent and sent[0][0] == 200 and sent[0][1]["openapi"] == "3.1.0" and len(sent[0][1]["paths"]) == len(doc["paths"]),
          "обработчик /openapi.json отдаёт этот документ")


def test_reference():
    print("страница для людей — из того же документа:")
    doc = routes.API_SPEC.build()
    ref = ApiReference(doc)
    labels = {path: ref.access_label(doc["paths"][path][m]) for path, m in (
        ("/openapi.json", "get"), ("/api/cell-assets", "get"), ("/metrics", "get"),
        ("/api/topology", "get"), ("/api/cloud-blocks/save", "post"))}
    check(labels == {"/openapi.json": "open", "/api/cell-assets": "fleet token", "/metrics": "fleet token or session",
                     "/api/topology": "any account", "/api/cloud-blocks/save": "admin"},
          f"столбец доступа (got {labels})")
    check(ref.inputs(doc["paths"]["/api/models/download"]["get"]).endswith("…")
          and ref.inputs(doc["paths"]["/api/cloud-accounts/usage-reserve"]["post"]) == "body: `id`, `windowSeconds`, `pct`",
          "столбец входов: «…» там, где обработчик может читать больше")
    check(ApiReference.cell("a | b\n c") == "a \\| b c", "ячейка: одна строка, черта экранирована")
    page = "top\n" + ApiReference.START + "\nSTALE-ROW-7f3\n" + ApiReference.END + "\nbottom\n"
    spliced = ref.splice(page)
    check(spliced.startswith("top\n" + ApiReference.START) and spliced.endswith(ApiReference.END + "\nbottom\n")
          and "STALE-ROW-7f3" not in spliced and "`GET /openapi.json`" in spliced,
          "между маркерами — таблица из документа; вокруг — не тронуто")
    try:
        ref.splice("a page without markers")
        check(False, "negative: страницу без маркеров не переписываем")
    except ValueError:
        check(True, "negative: страницу без маркеров не переписываем")


for fn in (test_reading, test_access, test_document, test_reference):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("api spec OK: чтение кода, правило доступа, документ и страница — значениями")
