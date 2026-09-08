#!/usr/bin/env python3
"""Value snapshot: what the controller counts as an INCIDENT on a route.

The incident panel is a promise: a red row means the route failed. On one
production day, one port carried 31 red rows out of 46, and every one of
them was a client's PROBE: `GET /v1/props`, `/api/tags`, `/api/v1/models` —
paths llama.cpp doesn't have, answered with an honest 404 in the very
seconds every real request through that port got a 200. A panel where a
normal conversation between a client and a server is drawn as a failure
teaches people to stop trusting the panel at all — the same defect as
"absence drawn as normal" (docs/why.md), just mirrored.

A VALUE is pinned for every claim — positive and negative: a probe never
produces an incident; a model request with the same 404 does; an unrelated
status on a probe (401, 5xx) does; a slow first byte and a long request are
still counted the way they always were.

Run: python3 scripts/test_incidents.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.monitoring import proxy_incident_for_item  # noqa: E402
from caravan.common.request_kind import is_discovery_probe, is_inference_request  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def kind_of(item):
    inc = proxy_incident_for_item(item)
    return inc.get("kind") if inc else None


def test_discovery_is_not_an_incident():
    print("разведка клиента:")
    # The exact four paths and statuses that showed up in the panel on 2026-09-06.
    for path, status, err in (("/v1/props", 404, "File Not Found"),
                              ("/api/tags", 404, "File Not Found"),
                              ("/api/v1/models", 404, "File Not Found"),
                              ("/api/v1/models", 405, "Method Not Allowed"),
                              ("/v1/internal/model/info", 404, ""),
                              ("/", 415, ""),
                              ("/", 405, "")):
        item = {"status": status, "method": "GET", "path": path, "label": "route", "error": err}
        check(kind_of(item) is None,
              f"GET {path} → {status}: у сервера нет такого пути — это не отказ маршрута")

    # NEGATIVE for every condition of the rule.
    check(kind_of({"status": 404, "method": "POST", "path": "/v1/chat/completions",
                   "label": "route", "error": "model not found"}) == "failed",
          "POST к модели с тем же 404 — инцидент: это модель сказала «меня нет»")
    check(kind_of({"status": 401, "method": "GET", "path": "/v1/props", "label": "route"}) == "failed",
          "401 на разведке — инцидент: ключ маршрута не тот, и это надо видеть")
    check(kind_of({"status": 500, "method": "GET", "path": "/v1/props", "label": "route"}) == "failed",
          "5xx на разведке — инцидент: упал сам выход, а не путь")
    check(kind_of({"status": 502, "method": "GET", "path": "/props", "label": "route",
                   "error": "[Errno 111] Connection refused"}) == "failed",
          "отказ соединения на разведке — инцидент: сокет закрыт, это факт выхода")
    check(kind_of({"status": 404, "method": "GET", "path": "/v1/props", "label": "route",
                   "errorKind": "upstream_timeout"}) is None,
          "as-is: разведка молчит даже с чужим errorKind — правило смотрит на путь и статус")

    print("что осталось инцидентом:")
    check(kind_of({"status": 200, "method": "POST", "path": "/v1/chat/completions",
                   "label": "route", "firstByteMs": 31000}) == "slow_first_byte",
          "медленный первый байт (31 с) — прежний инцидент")
    check(kind_of({"status": 200, "method": "GET", "path": "/v1/props",
                   "label": "route", "firstByteMs": 31000}) == "slow_first_byte",
          "as-is: и на разведке тоже — правило снимает только «нет такого пути», не медленность")
    check(kind_of({"status": 200, "method": "POST", "path": "/v1/chat/completions",
                   "label": "route", "durationMs": 130000}) == "slow_request",
          "долгий запрос (130 с) — прежний инцидент")
    check(kind_of({"status": 200, "method": "POST", "path": "/v1/chat/completions",
                   "label": "route", "error": "client disconnected (upstream generation aborted)"})
          == "client_disconnected",
          "обрыв клиента — прежний инцидент со своим видом")
    check(kind_of({"status": 200, "method": "POST", "path": "/v1/chat/completions",
                   "label": "route", "firstByteMs": 100, "durationMs": 1000}) is None,
          "negative: обычный успешный запрос инцидентом не был и не стал")
    check(kind_of({"status": 429, "method": "POST", "path": "/v1/chat/completions",
                   "label": "route", "error": "usage limit reached"}) == "failed",
          "429 от облака — инцидент: лимиты кончились, и это надо видеть")
    check(kind_of({"status": 404, "label": "route"}) == "failed",
          "as-is: запись без method/path судится по-старому — 404 остаётся отказом")


def test_the_chain_is_part_of_the_reason():
    """Кто отказал ПЕРВЫМ — часть причины, а не сноска.

    Локальный выход ответил 502, спасение ушло в облако, облако — 429. В
    журнале оставалось «The usage limit has been reached», и панель называла
    виноватым облако (боевой случай 2026-09-06, 21:28). Цепочка теперь едет
    с записью и попадает в строку инцидента.
    """
    print("цепочка в причине:")
    inc = proxy_incident_for_item({"status": 429, "method": "POST", "path": "/v1/chat/completions",
                                   "label": "route", "error": "The usage limit has been reached",
                                   "chain": "srv:22011: 502"})
    check(inc["summary"] == "The usage limit has been reached — after srv:22011: 502",
          f"positive: сводка называет и последний ответ, и того, кто отказал до него (got {inc['summary']!r})")
    inc = proxy_incident_for_item({"status": 500, "method": "POST", "path": "/v1/chat/completions",
                                   "label": "route"})
    check(inc["summary"] == "status 500",
          f"negative: без цепочки сводка прежняя — приписки из ниоткуда не появляется (got {inc['summary']!r})")
    inc = proxy_incident_for_item({"status": 500, "method": "POST", "path": "/v1/chat/completions",
                                   "label": "route", "chain": "   "})
    check(inc["summary"] == "status 500", "пустая цепочка — тоже не приписка")


def test_the_rule_itself():
    print("правило одно на двоих (proxy и контроллер):")
    check(is_discovery_probe("GET", "/v1/props", 404) is True,
          "positive: GET по несуществующему пути — разведка")
    check(is_discovery_probe("GET", "/v1/props", "404") is True,
          "статус строкой считается так же — журнал пишет и так, и так")
    check(is_discovery_probe("POST", "/v1/chat/completions", 404) is False,
          "negative: запрос к модели разведкой не считается никогда")
    check(is_discovery_probe("GET", "/v1/props", 500) is False,
          "negative: 5xx — не «нет такого пути»")
    check(is_discovery_probe("GET", "/v1/props", None) is False,
          "negative: статуса нет — судить не о чем")
    check(is_discovery_probe("GET", "", 404) is False,
          "negative: пути нет — «не знаю, о чём спросили» не равно «спросили ни о чём»")
    check(is_inference_request("POST", "/v1/chat/completions?x=1") is True,
          "positive: строка запроса не мешает узнать путь")
    check(is_inference_request("GET", "/v1/chat/completions") is False,
          "negative: GET по тому же пути запросом к модели не считается")


def test_the_log_forgets_old_discovery():
    """Журнал живёт 30 дней, поэтому правило применяется и на чтении."""
    print("журнал инцидентов:")
    import json, os, tempfile, time as _time
    from pathlib import Path as _Path
    import caravan.admin.monitoring as mon
    tmp = _Path(tempfile.mkdtemp(prefix="caravan-inc-")) / "incident-log.jsonl"
    now = int(_time.time())
    rows = [
        {"time": now, "kind": "failed", "title": "r failed", "method": "GET",
         "path": "/v1/props", "status": 404, "summary": "File Not Found"},
        {"time": now, "kind": "failed", "title": "r failed", "method": "POST",
         "path": "/v1/chat/completions", "status": 429, "summary": "usage limit reached"},
        {"time": now, "kind": "slow_first_byte", "title": "r slow first byte", "method": "POST",
         "path": "/v1/chat/completions", "status": 200, "summary": "fb 31s"},
        {"time": now, "kind": "fallback_active", "title": "not an incident at all"},
    ]
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    old_file = mon.INCIDENT_LOG_FILE
    mon.INCIDENT_LOG_FILE = tmp
    try:
        got = mon.load_incident_log()
    finally:
        mon.INCIDENT_LOG_FILE = old_file
    kinds = sorted(str(r.get("summary")) for r in got)
    check(len(got) == 2 and "File Not Found" not in kinds,
          f"записанная раньше разведка на чтении отбрасывается (got {kinds})")
    check("usage limit reached" in kinds and "fb 31s" in kinds,
          f"настоящие инциденты из журнала остаются (got {kinds})")
    check(all(r.get("kind") != "fallback_active" for r in got),
          "as-is: fallback_active по-прежнему не инцидент")


for fn in (test_discovery_is_not_an_incident, test_the_chain_is_part_of_the_reason,
           test_the_rule_itself, test_the_log_forgets_old_discovery):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("all incident snapshots hold")
