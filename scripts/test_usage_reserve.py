#!/usr/bin/env python3
"""Value snapshot: a step's switch levels on a subscription's limit windows.

2026-09-28: the five-hour window of the ChatGPT subscription ran out under the
caravan's traffic, and with it the operator's own chats. Since then a share of
each window is left untouched; since pools of steps (2026-10-10) it is each
step's own "switch at N%": the pool goes on to the next step there, and with no
step left, the proxy answers 429 itself.

Pinned by value, positive and negative for every claim:
- the rule (caravan/common/usage_reserve.py) — what closes a step, what does
  not, and what stored levels look like;
- the reading the proxy takes off the Codex backend's headers and off the
  account's usage page (caravan/proxy/subscription_usage.py), and the answer
  the proxy gives itself (caravan/proxy/pool_steps.py, OwnAnswer);
- the usage page's windows carry their length, and the board's error panel
  counts the caravan's own refusal apart from the provider's 429;
- an account keeps no levels of its own any more: they are its steps'.

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

from caravan.common.usage_reserve import UsageReserve  # noqa: E402
from caravan.proxy.pool_steps import PoolRefusal  # noqa: E402
from caravan.proxy.subscription_usage import SubscriptionUsage  # noqa: E402

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
    check(UsageReserve.NEW_STEP == {"18000": 10, "604800": 10},
          "новый шаг подписки — 10% пятичасового окна и 10% недельного (оператор, 2026-10-08)")


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

    print("собственный ответ прокси (пул без подходящего шага):")
    pool = {"id": "p", "name": "Main"}
    steps = [{"stepId": "a", "reason": "reserve", "resetAt": NOW + 3600}, {"stepId": "b", "reason": "quota", "resetAt": NOW + 600}]
    refusal = PoolRefusal(pool, steps, NOW)
    body = json.loads(refusal.read())
    check(refusal.status == 429 and body["error"]["type"] == "pool_unavailable" and refusal.KIND == "pool_unavailable",
          "все шаги держит лимит — 429 и тип отказа пула")
    check(body["error"]["resets_at"] == NOW + 600 and refusal.getheader("retry-after") == "600",
          "Retry-After — до ближайшего сброса")
    check(body["error"]["message"] == "Pool Main has no step that fits now: a (reserve); b (quota)",
          "слова называют пул и причину каждого шага")
    check(refusal.read() == b"" and int(refusal.getheader("Content-Length")) == len(refusal.body),
          "тело читается один раз, длина в заголовке — длина тела")
    gone = PoolRefusal(pool, [{"stepId": "a", "reason": "reserve", "resetAt": NOW - 10}], NOW)
    check(gone.retry_after == 30, "сброс уже прошёл — Retry-After 30 с, не ноль и не прошлое")
    check(PoolRefusal(pool, [{"stepId": "a", "reason": "credential_missing"}], NOW).status == 503,
          "negative: шаг без входа — не лимит: 503")
    line = PoolRefusal(pool, [], NOW)
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
                     "pools": [{"id": "sol", "name": "gpt-6-sol", "steps": [{"id": "sub", "accountId": "sub", "model": "gpt-6-sol"}]}]})
    now = int(time.time())
    rows = [{"event": "finished", "item": {"upstreamType": "cloud", "providerId": "sol", "status": 429,
                                           "errorKind": "usage_reserve", "error": "The caravan keeps your reserve", "finishedAt": now}},
            {"event": "finished", "item": {"upstreamType": "cloud", "providerId": "sol", "status": 429, "cloudAccountId": "sub",
                                           "errorKind": "pool_unavailable", "error": "Pool gpt-6-sol has no step", "finishedAt": now}},
            {"event": "finished", "item": {"upstreamType": "cloud", "providerId": "sol", "status": 429,
                                           "errorKind": "", "error": "", "finishedAt": now}},
            # The pool refused before asking any step: the record names no account.
            {"event": "finished", "item": {"upstreamType": "cloud", "providerId": "sol", "status": 503,
                                           "errorKind": "pool_unavailable", "error": "Pool gpt-6-sol has no step that fits now",
                                           "finishedAt": now}}]
    (log_dir / f"{time.strftime('%Y-%m-%d')}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    old = cloud_api.AGENT_PROXY_LOG_DIR
    cloud_api.AGENT_PROXY_LOG_DIR = log_dir
    try:
        got = cloud_api.cloud_upstream_errors()["byAccount"].get("sub") or []
        spend = cloud_api.cloud_spend_summary(days=1).get("sub", {})
    finally:
        cloud_api.AGENT_PROXY_LOG_DIR = old
    codes = sorted(r["code"] for r in got)
    check(codes == ["HTTP 429", "pool_unavailable", "usage_reserve"],
          f"отказ каравана — своя строка (и под старым именем из журнала до 1.3.462), 429 провайдера — своя (got {codes})")
    check(next(r["count"] for r in got if r["code"] == "pool_unavailable") == 1,
          "negative: отказ пула, который не спросил ни одного шага, не приписан первому шагу (до 2026-10-11 приписывался)")
    check(spend.get("requests") == 3,
          f"расход: три записи, назвавшие учётку или старого вида, — запросы; отказ пула без учётки — ничей (got {spend.get('requests')})")
    check({r["model"] for r in got} == {"gpt-6-sol"}, "модель строки — модель шага пула, а не то, что назвал клиент")


def test_an_account_keeps_no_levels():
    print("у аккаунта своих порогов нет — они у шагов:")
    from caravan.admin.cloud import load_cloud_data, save_cloud_data, upsert_cloud_account
    save_cloud_data({"accounts": [], "pools": []})
    upsert_cloud_account({"id": "sub", "type": "openai-subscription", "name": "Plus", "usageReserve": {"18000": 30}})
    stored = next(a for a in load_cloud_data()["accounts"] if a["id"] == "sub")
    check("usageReserve" not in stored, "запрос назвал запас аккаунту — он не хранится: уровни живут у шагов пулов")
    check(load_cloud_data()["pools"] == [], "negative: новая подписка сама ни в какой пул не встаёт — шаг ставит оператор")


for fn in (test_the_rule, test_the_reading_and_the_refusal, test_the_usage_page, test_the_board_sides,
           test_an_account_keeps_no_levels):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("usage reserve OK: правило порогов, показания, ответ прокси и панель — значениями")
