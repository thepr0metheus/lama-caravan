#!/usr/bin/env python3
"""Value snapshot: the operator's reserve on a subscription's limits.

2026-09-28: the five-hour window of the ChatGPT subscription ran out under the
caravan's traffic, and with it the operator's own chats. The operator keeps a
share of each window for themselves; once a window is down to it, the proxy
answers the account's requests itself with the provider's own 429.

Pinned by value, positive and negative for every claim:
- the rule (caravan/common/usage_reserve.py) — what closes the account, what
  does not, and what a stored reserve looks like;
- the reading the proxy takes off the Codex backend's headers and off the
  account's usage page, the gate that refreshes a shut door's reading (an
  early reset), and the refusal it gives (caravan/proxy/subscription_usage.py);
- the controller's desk: setting a window's reserve, and the verdict the card
  shows, computed from the proxy's state file with the same rule;
- the usage page's windows carry their length, and the board's error panel
  counts the caravan's own refusal apart from the provider's 429.

Run: python3 scripts/test_usage_reserve.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-reserve-"))
os.environ["CLOUD_PROVIDERS_FILE"] = str(TMP / "cloud-providers.json")
os.environ["AGENT_PROXY_STATE_FILE"] = str(TMP / "agent-proxy-state.json")
os.environ["AGENT_PROXY_LOG_DIR"] = str(TMP / "logs")
os.environ["MODEL_CATALOG_FILE"] = str(TMP / "model-catalog.json")
os.environ["PROVIDER_SECRETS_FILE"] = str(TMP / "provider-secrets.json")
sys.path.insert(0, str(ROOT))

from caravan.common.errors import AppError  # noqa: E402
from caravan.common.usage_reserve import UsageReserve  # noqa: E402
from caravan.proxy.subscription_usage import ReserveGate, ReserveRefusal, SubscriptionUsage  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


NOW = 1_800_000_000
FIVE_H, WEEK = 18000, 604800


def win(seconds, used, reset_in):
    return {"seconds": seconds, "usedPct": used, "resetAt": NOW + reset_in if reset_in is not None else None}


def test_the_rule():
    print("правило запаса:")
    r = UsageReserve({"18000": 20, "604800": 10})
    check(r.verdict([win(FIVE_H, 85, 3600)], NOW) == {"windowSeconds": FIVE_H, "remainingPct": 15, "reservePct": 20,
                                                       "resetAt": NOW + 3600},
          "positive: осталось 15% при запасе 20% — окно закрывает аккаунт до своего сброса")
    check((r.verdict([win(FIVE_H, 80, 3600)], NOW) or {}).get("remainingPct") == 20,
          "граница: осталось ровно столько, сколько запас, — уже закрыто")
    check(r.verdict([win(FIVE_H, 79, 3600)], NOW) is None, "negative: осталось 21% при запасе 20% — открыто")
    check((r.verdict([win(FIVE_H, 100, 3600)], NOW) or {}).get("remainingPct") == 0
          and (r.verdict([win(FIVE_H, 130, 3600)], NOW) or {}).get("remainingPct") == 0,
          "исчерпанное окно и счётчик больше 100% — остаток 0, не отрицательный")
    check(r.verdict([win(FIVE_H, 95, 0)], NOW) is None and r.verdict([win(FIVE_H, 95, -60)], NOW) is None,
          "negative: окно уже сбросилось — показание старое и ничего не закрывает")
    check(r.verdict([win(FIVE_H, 95, None)], NOW) is None,
          "negative: без времени сброса нельзя сказать, сколько держать, — не закрывает (не знать — не повод отказывать)")
    check(UsageReserve({"18000": 20}).verdict([win(WEEK, 99, 9000)], NOW) is None,
          "negative: у окна без запаса нет двери, даже почти пустого")
    both = r.verdict([win(FIVE_H, 90, 3600), win(WEEK, 95, 90000)], NOW)
    check(both["windowSeconds"] == WEEK and both["resetAt"] == NOW + 90000,
          f"закрывают оба окна — названо то, что откроется позже (got {both})")
    check(r.verdict([], NOW) is None and r.verdict(None, NOW) is None and r.verdict(["x", {"seconds": "a"}], NOW) is None,
          "negative: нет показаний или мусор — ничего не закрыто")
    check(UsageReserve().verdict([win(FIVE_H, 99, 3600)], NOW) is None, "negative: запаса нет — не закрывает ничего")

    print("вид запаса в хранилище:")
    check(UsageReserve.normalize({"18000": 20, 604800: "10"}) == {"18000": 20, "604800": 10},
          "ключ — длина окна строкой, значение — целые проценты")
    check(UsageReserve.normalize({"18000": 0, "604800": -5}) == {},
          "negative: ноль и минус не хранятся — «запаса нет» не записывается как выбор")
    check(UsageReserve.normalize({"18000": 100}) == {"18000": UsageReserve.MAX_PCT},
          f"запас всего окна закрыл бы аккаунт навсегда — не больше {UsageReserve.MAX_PCT}%")
    check(UsageReserve.normalize({"x": 20, "0": 20, "18000": "a", "604800": True}) == {} and UsageReserve.normalize("x") == {},
          "negative: мусор выпадает, а не становится числом")
    check(UsageReserve.of({"usageReserve": {"18000": 20}}).by_seconds == {FIVE_H: 20} and UsageReserve.of(None).by_seconds == {},
          "запас читается с аккаунта или провайдера; без аккаунта — пусто")


def test_the_reading_and_the_refusal():
    print("показания из заголовков Codex:")
    headers = {"X-Codex-Primary-Used-Percent": "85", "x-codex-primary-window-minutes": "300",
               "x-codex-primary-reset-at": str(NOW + 3600), "x-codex-secondary-used-percent": "16.4",
               "x-codex-secondary-window-minutes": "10080", "x-codex-secondary-reset-at": str(NOW + 86400)}
    got = SubscriptionUsage.windows_from_headers(headers)
    check(got == [{"seconds": FIVE_H, "usedPct": 85, "resetAt": NOW + 3600}, {"seconds": WEEK, "usedPct": 16, "resetAt": NOW + 86400}],
          f"оба окна, длина в секундах, регистр заголовков не важен (got {got})")
    check(SubscriptionUsage.windows_from_headers(list(headers.items())) == got, "список пар читается так же, как словарь")
    check(SubscriptionUsage.windows_from_headers({"x-codex-primary-used-percent": "85"}) == [],
          "negative: без длины окна нет и показания")
    only = SubscriptionUsage.windows_from_headers({"x-codex-primary-used-percent": "85", "x-codex-primary-window-minutes": "300"})
    check(only == [{"seconds": FIVE_H, "usedPct": 85, "resetAt": None}], "без времени сброса — показание с None, а не с нулём")
    usage = SubscriptionUsage()
    check(usage.note("acc", headers, now=NOW) is True and usage.windows("acc") == got, "показание запомнено по аккаунту")
    check(usage.note("acc", {"content-type": "text/event-stream"}, now=NOW + 5) is False and usage.windows("acc") == got,
          "negative: ответ без показаний не стирает прежние")
    check(usage.note("", headers) is False and usage.windows("other") == [], "negative: без аккаунта не пишется; чужой аккаунт пуст")
    snap = usage.snapshot()
    check(snap == {"acc": {"windows": got, "readAt": float(NOW)}}, "снимок для state-файла: окна и время показания")
    usage.windows("acc")[0]["usedPct"] = 1
    check(usage.windows("acc")[0]["usedPct"] == 85, "снаружи отдаётся копия — чужая правка показание не портит")

    print("отказ каравана:")
    refusal = ReserveRefusal({"windowSeconds": FIVE_H, "remainingPct": 15, "reservePct": 20, "resetAt": NOW + 3600}, now=NOW)
    body = json.loads(refusal.read())
    check(refusal.status == 429 and body["error"]["type"] == "usage_limit_reached",
          "форма провайдера: 429 и usage_limit_reached")
    check(body["error"]["resets_at"] == NOW + 3600 and body["error"]["resets_in_seconds"] == 3600
          and refusal.getheader("retry-after") == "3600", "когда окно сбросится — в теле и в Retry-After")
    check(body["error"]["caravan_reserve"] == {"window_seconds": FIVE_H, "remaining_pct": 15, "reserve_pct": 20},
          "числа запаса в ответе")
    check(body["error"]["message"].startswith("The caravan keeps your reserve: the 5-hour window has 15% left"),
          "слова называют караван и окно")
    check(refusal.read() == b"" and int(refusal.getheader("Content-Length")) == len(refusal.body),
          "тело читается один раз, длина в заголовке — длина тела")
    again = ReserveRefusal({"windowSeconds": WEEK, "remainingPct": 5, "reservePct": 10, "resetAt": NOW - 10}, now=NOW)
    check(again.retry_after == 1 and "weekly" in again.message, "сброс уже прошёл — Retry-After не меньше 1; недельное окно названо")
    check(ReserveRefusal.window_name(7200) == "2-hour" and ReserveRefusal.window_name(90) == "90-second",
          "имя окна по длине")
    line = ReserveRefusal({"windowSeconds": FIVE_H, "remainingPct": 1, "reservePct": 2, "resetAt": NOW + 9}, now=NOW)
    check(line.readline(10) == line.body[:10] and line.read() == line.body[10:], "readline и read читают подряд")


# The usage page in the shape cloud_api._normalize_subscription_usage documents as
# confirmed, plus OpenAI's extra window that shares the weekly length.
PAGE = {"rate_limit": {
    "primary_window": {"used_percent": 3, "limit_window_seconds": 18000, "reset_after_seconds": 14217, "reset_at": NOW + 14217},
    "secondary_window": {"used_percent": 100, "limit_window_seconds": 604800, "reset_after_seconds": 336233,
                         "reset_at": NOW + 336233},
    "additional_rate_limits": [{"used_percent": 5, "limit_name": "gpt-reserve", "limit_window_seconds": 604800,
                                "reset_at": NOW + 1000}]}}


def test_the_usage_page():
    print("показания со страницы использования:")
    got = SubscriptionUsage.windows_from_usage_page(PAGE)
    check(got == [{"seconds": FIVE_H, "usedPct": 3, "resetAt": NOW + 14217}, {"seconds": WEEK, "usedPct": 100, "resetAt": NOW + 336233}],
          f"оба окна, как в заголовках ответа; окно gpt-reserve не читается — у него длина недели (got {got})")
    from caravan.admin import cloud_api
    limits = cloud_api._normalize_subscription_usage(PAGE)["limits"][:2]
    check([(w["seconds"], 100 - w["usedPct"]) for w in got] == [(lim["windowSeconds"], lim["remainingPct"]) for lim in limits],
          "прокси и карточка читают одну страницу одинаково: длина и остаток совпадают")
    check(SubscriptionUsage.windows_from_usage_page({"rate_limit": {"primary_window": {"limit_window_seconds": 18000,
                                                                                       "reset_at": NOW}}}) == [],
          "negative: без доли использованного окно пропущено, а не прочитано как «0%»")
    check(SubscriptionUsage.windows_from_usage_page({"rate_limit": {"primary_window": {"used_percent": 5,
                                                                                       "limit_window_seconds": 0}}}) == [],
          "negative: без длины окна нет и показания")
    check(SubscriptionUsage.windows_from_usage_page(None) == [] and SubscriptionUsage.windows_from_usage_page({"detail": "x"}) == [],
          "negative: страница не ответила или ответила не тем — показаний нет")
    only = SubscriptionUsage.windows_from_usage_page({"rate_limit": {"primary_window": {"used_percent": 7, "limit_window_seconds": 18000}}})
    check(only == [{"seconds": FIVE_H, "usedPct": 7, "resetAt": None}], "без времени сброса — None, а не ноль")


def test_the_gate():
    """While the door is shut nothing is sent, so no answer brings a reading: an
    early reset (a banked or bought one) stayed unseen until the old reset time."""
    print("закрытая дверь и досрочный сброс:")
    clock = [float(NOW)]
    asked = []
    page = {"value": None}

    def fetch(provider):
        asked.append(provider["accountId"])
        if isinstance(page["value"], Exception):
            raise page["value"]
        return page["value"]

    provider = {"accountId": "acc", "usageReserve": {"18000": 20}}
    shut = [{"seconds": FIVE_H, "usedPct": 85, "resetAt": NOW + 3600}]
    usage = SubscriptionUsage()
    gate = ReserveGate(usage, fetch=fetch, clock=lambda: clock[0])
    usage.keep("acc", shut, now=NOW)
    check((gate.verdict(provider) or {}).get("remainingPct") == 15 and asked == [],
          "свежие показания — дверь закрыта, страницу не спрашиваем")
    clock[0] = NOW + 299
    check(gate.verdict(provider) is not None and asked == [], "negative: через 299 секунд показания ещё свежие")
    clock[0] = NOW + 300
    page["value"] = {"rate_limit": {"primary_window": {"used_percent": 0, "limit_window_seconds": 18000, "reset_at": NOW + 18300}}}
    check(gate.verdict(provider) is None and asked == ["acc"],
          "positive: через пять минут спрашиваем страницу; сброс пришёл раньше срока — дверь открыта")
    check(usage.windows("acc") == [{"seconds": FIVE_H, "usedPct": 0, "resetAt": NOW + 18300}] and usage.read_at("acc") == NOW + 300,
          "показание со страницы заменило старое, со своим временем")

    usage = SubscriptionUsage()
    gate = ReserveGate(usage, fetch=fetch, clock=lambda: clock[0])
    asked.clear()
    clock[0] = NOW + 1000
    usage.keep("acc", shut, now=NOW)
    page["value"] = RuntimeError("page down")
    check((gate.verdict(provider) or {}).get("remainingPct") == 15 and asked == ["acc"],
          "страница не ответила — дверь закрыта по последним показаниям")
    clock[0] = NOW + 1200
    check(gate.verdict(provider) is not None and asked == ["acc"],
          "negative: после неудачи страницу не спрашивают снова раньше пяти минут")
    clock[0] = NOW + 1300
    page["value"] = {"detail": "Unauthorized"}
    check(gate.verdict(provider) is not None and asked == ["acc", "acc"] and usage.windows("acc") == shut,
          "через пять минут спрашивают снова; ответ без окон показаний не стирает")
    clock[0] = NOW + 1600
    page["value"] = {"rate_limit": {"primary_window": {"used_percent": 90, "limit_window_seconds": 18000, "reset_at": NOW + 3600}}}
    check((gate.verdict(provider) or {}).get("remainingPct") == 10 and asked == ["acc"] * 3,
          "страница подтвердила — дверь закрыта со свежими числами")

    usage = SubscriptionUsage()
    gate = ReserveGate(usage, fetch=fetch, clock=lambda: clock[0])
    asked.clear()
    usage.keep("acc", [{"seconds": FIVE_H, "usedPct": 50, "resetAt": NOW + 3600}], now=NOW - 100000)
    check(gate.verdict(provider) is None and asked == [],
          "negative: дверь открыта — страницу не спрашиваем даже по старым показаниям (показания едут на ответах)")
    usage.keep("acc", shut, now=NOW - 100000)
    check(gate.verdict({"accountId": "acc"}) is None and asked == [], "negative: запаса нет — не спрашиваем")


def test_the_desk():
    print("стол запаса у контроллера:")
    from caravan.admin.cloud import load_cloud_data, save_cloud_data
    from caravan.admin.usage_reserve_desk import UsageReserveDesk
    save_cloud_data({"accounts": [{"id": "sub", "type": "openai", "accountType": "openai-subscription",
                                   "name": "Plus", "baseUrl": "https://chatgpt.com", "authMode": "oauth"},
                                  {"id": "api", "type": "openai", "name": "API", "baseUrl": "https://api.openai.com/v1"}],
                     "blocks": []})
    state = TMP / "agent-proxy-state.json"
    desk = UsageReserveDesk(state_file=state, clock=lambda: NOW)
    check(desk.set("sub", FIVE_H, 20) == {"18000": 20} and desk.set("sub", WEEK, "10") == {"18000": 20, "604800": 10},
          "запас окна ставится на аккаунт, окна независимы")
    stored = next(a for a in load_cloud_data()["accounts"] if a["id"] == "sub")
    check(stored.get("usageReserve") == {"18000": 20, "604800": 10}, "и лежит в файле аккаунтов")
    check(desk.set("sub", WEEK, 0) == {"18000": 20}, "0 снимает запас окна")
    desk.set("sub", FIVE_H, 0)
    stored = next(a for a in load_cloud_data()["accounts"] if a["id"] == "sub")
    check("usageReserve" not in stored, "снят последний — поля нет вовсе, а не пустой словарь")
    for args, code, why in ((("nope", FIVE_H, 20), 404, "нет аккаунта"),
                            (("api", FIVE_H, 20), 400, "не подписка: окон нет, запас ничего бы не делал"),
                            (("sub", FIVE_H, UsageReserve.MAX_PCT + 1), 400, "больше потолка"),
                            (("sub", FIVE_H, -1), 400, "отрицательный"),
                            (("sub", 0, 20), 400, "окно без длины"),
                            (("sub", "x", 20), 400, "не число")):
        try:
            desk.set(*args)
            check(False, f"negative: {why} — отказ {code}")
        except AppError as err:
            check(err.status == code, f"negative: {why} — отказ {code} (got {err.status})")

    desk.set("sub", FIVE_H, 20)
    from caravan.admin.cloud import upsert_cloud_account
    upsert_cloud_account({"id": "sub", "name": "Plus, renamed"})
    stored = next(a for a in load_cloud_data()["accounts"] if a["id"] == "sub")
    check(stored.get("usageReserve") == {"18000": 20} and stored.get("name") == "Plus, renamed",
          "правка аккаунта (переименование) запас не стирает: нормализатор пересобирает запись и знает это поле")
    check(desk.view("sub") == {"reserve": {"18000": 20}, "reserveKept": None, "reserveMax": UsageReserve.MAX_PCT,
                               "reserveReadAt": None},
          "state-файла нет — показаний нет, вердикта нет, а не выдуманный")
    state.write_text(json.dumps({"subscriptionUsage": {"sub": {"windows": [win(FIVE_H, 85, 3600), win(WEEK, 10, 90000)],
                                                               "readAt": NOW - 30}}}), encoding="utf-8")
    view = desk.view("sub")
    check(view["reserveKept"] == {"windowSeconds": FIVE_H, "remainingPct": 15, "reservePct": 20, "resetAt": NOW + 3600}
          and view["reserveReadAt"] == NOW - 30,
          "positive: карточка видит то же, что прокси: тем же правилом по его показаниям")
    desk.set("sub", FIVE_H, 10)
    check(desk.view("sub")["reserveKept"] is None, "negative: запас ниже остатка — дверь открыта")
    state.write_text("not json", encoding="utf-8")
    check(desk.view("sub")["reserveKept"] is None and desk.reading("sub") is None, "negative: битый state-файл — показаний нет")


def test_the_board_sides():
    print("окна страницы использования и панель ошибок:")
    from caravan.admin import cloud_api
    usage = cloud_api._normalize_subscription_usage({"rate_limit": {
        "primary_window": {"used_percent": 100, "limit_window_seconds": 18000, "reset_at": NOW + 60},
        "secondary_window": {"used_percent": 16, "limit_window_seconds": 604800, "reset_at": NOW + 600},
        "additional_rate_limits": [{"used_percent": 5, "limit_name": "gpt-reserve"}]}})
    check([lim.get("windowSeconds", "absent") for lim in usage["limits"]] == [18000, 604800, None],
          "у окон страницы использования есть длина — по ней ставится запас; без длины — None")

    log_dir = TMP / "logs"
    log_dir.mkdir(exist_ok=True)
    from caravan.admin.cloud import save_cloud_data
    save_cloud_data({"accounts": [{"id": "sub", "type": "openai", "accountType": "openai-subscription", "name": "Plus",
                                   "baseUrl": "https://chatgpt.com", "authMode": "oauth"}],
                     "blocks": [{"id": "sol", "accountId": "sub", "model": "gpt-6-sol"}]})
    now = int(time.time())
    rows = [{"event": "finished", "item": {"upstreamType": "cloud", "providerId": "sol", "status": 429,
                                           "errorKind": "usage_reserve", "error": "The caravan keeps your reserve", "finishedAt": now}},
            {"event": "finished", "item": {"upstreamType": "cloud", "providerId": "sol", "status": 429,
                                           "errorKind": "", "error": "", "finishedAt": now}}]
    (log_dir / f"{time.strftime('%Y-%m-%d')}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    old = cloud_api.AGENT_PROXY_LOG_DIR
    cloud_api.AGENT_PROXY_LOG_DIR = log_dir
    try:
        got = cloud_api.cloud_upstream_errors()["byAccount"].get("sub") or []
    finally:
        cloud_api.AGENT_PROXY_LOG_DIR = old
    codes = sorted(r["code"] for r in got)
    check(codes == ["HTTP 429", "usage_reserve"],
          f"отказ каравана — своя строка, 429 провайдера — своя (got {codes})")


for fn in (test_the_rule, test_the_reading_and_the_refusal, test_the_usage_page, test_the_gate, test_the_desk,
           test_the_board_sides):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("usage reserve OK: правило, показания, отказ, стол контроллера и панель — значениями")
