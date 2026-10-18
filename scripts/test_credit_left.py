#!/usr/bin/env python3
"""Value snapshot: the credit a key account has left (1.3.568) — the figure the operator types, the spend counted from it, and the one
price rule both the board's meter and the statistics panel go by.

The owner added an Anthropic key and asked why the board did not say how much money was left on it (2026-10-17). The provider does
not tell: the Console shows "Organization credits", and the API has no call for it (the Admin API reports spend and spend limits).
So the account holds what the operator types — what the console shows NOW — and the moment it was typed; the proxy's logs say what
went through the caravan since, priced. An estimate, and every place that shows it says so.

Each claim has a positive and a negative pin. Time is a parameter, not a call: the stamps and the log days are those of a `now` the
test passes.

Run: python3 scripts/test_credit_left.py
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-credit-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
for sub in ("state", "config", "secrets"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from caravan.admin import cloud, cloud_api  # noqa: E402
from caravan.common.account_credit import AccountCredit  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402
from caravan.common.model_prices import ModelPrices  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def refusal(fn):
    try:
        fn()
    except AppError as exc:
        return exc.status, str(exc)
    return None


#: Local noon of a day: a row an hour before it is on the same log day whatever the machine's time zone.
NOON = int(time.mktime((2027, 1, 15, 12, 0, 0, 0, 0, -1)))
DAY = 86400


def section_the_figure():
    print("what the operator types:")
    got = {raw: AccountCredit.amount(raw) for raw in ("200", " 12.349 ", "200,5", 7, 0, "0", 12.5)}
    check(got == {"200": 200.0, " 12.349 ": 12.35, "200,5": 200.5, 7: 7.0, 0: 0.0, "0": 0.0, 12.5: 12.5},
          f"a number of dollars, to the cent; a decimal comma is read as a point (typed by hand, in the operator's language) (got {got})")
    check(AccountCredit.amount("") is None and AccountCredit.amount("   ") is None and AccountCredit.amount(None) is None,
          "blank is none — and 0 is not blank: a credit used up is a credit")
    for raw, what in (("abc", "text"), ("-1", "negative"), ("nan", "nan"), ("inf", "infinity"), (True, "a bool"), ("1,000.50", "two separators"),
                      (str(AccountCredit.LIMIT + 1), "above the limit"), ("1e400", "overflow")):
        check(refusal(lambda: AccountCredit.amount(raw)) is not None and refusal(lambda: AccountCredit.amount(raw))[0] == 400,
              f"negative: {what} ({raw!r}) is refused with 400, not read as something else")
    check(AccountCredit.amount(str(AccountCredit.LIMIT)) == float(AccountCredit.LIMIT), "boundary: the limit itself is a credit")

    print("what is stored and what an edit does to it:")
    held = {"credit": {"amountUsd": 200.0, "asOf": 1000}}
    check(AccountCredit.resolve({}, 5) is None, "an account with no credit and an edit that names none: none")
    check(AccountCredit.resolve(dict(held), 9) == {"amountUsd": 200.0, "asOf": 1000},
          "an edit that does not name the credit (a rename) leaves it — and its moment — as it was")
    check(AccountCredit.resolve({**held, "creditUsd": "200"}, 9) == {"amountUsd": 200.0, "asOf": 1000},
          "the same figure again keeps its moment: it was already counting from there")
    check(AccountCredit.resolve({**held, "creditUsd": "150"}, 9) == {"amountUsd": 150.0, "asOf": 9},
          "another figure starts counting now: what is left changed when the operator looked")
    check(AccountCredit.resolve({**held, "creditUsd": ""}, 9) is None and AccountCredit.resolve({**held, "creditUsd": None}, 9) is None,
          "blank takes the credit away")
    check(AccountCredit.resolve({"creditUsd": "0"}, 9) == {"amountUsd": 0.0, "asOf": 9},
          "boundary: 0 is stored — a credit used up, not 'no credit'")
    for junk in ({"amountUsd": "x", "asOf": 1}, {"amountUsd": 5, "asOf": "y"}, {"amountUsd": True, "asOf": 1}, {"amountUsd": -3, "asOf": 1},
                 {"amountUsd": float("nan"), "asOf": 1}, {"amountUsd": 5}, "200", 200, ["x"]):
        check(AccountCredit.resolve({"credit": junk}, 9) is None,
              f"negative: a file edited by hand ({junk!r}) is no credit — dropped, not guessed")


def section_the_account():
    print("the account:")
    cloud.save_cloud_data({"accounts": [], "pools": []})
    new = cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "name": "Anthropic", "creditUsd": "200"}, now=1000)
    check(new.get("credit") == {"amountUsd": 200.0, "asOf": 1000} and "creditUsd" not in new,
          "a key account saved with a figure stores its credit and the moment — and never the typed field itself")
    renamed = cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "name": "Claude"}, now=2000)
    check(renamed["credit"] == {"amountUsd": 200.0, "asOf": 1000} and renamed["name"] == "Claude",
          "a rename (an edit that sends no credit) does not move it")
    same = cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "creditUsd": "200"}, now=3000)
    check(same["credit"]["asOf"] == 1000, "the same figure typed again keeps its moment")
    changed = cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "creditUsd": "150,25"}, now=4000)
    check(changed["credit"] == {"amountUsd": 150.25, "asOf": 4000}, "another figure — counted from the moment it was typed")
    stored = next(a for a in cloud.load_cloud_data()["accounts"] if a["id"] == "anth")
    check(stored["credit"] == {"amountUsd": 150.25, "asOf": 4000}, "it is in the file, not only in the answer")
    gone = cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "creditUsd": ""}, now=5000)
    check("credit" not in gone, "blank — the credit is gone from the account")
    check(refusal(lambda: cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "creditUsd": "lots"}, now=6000)) is not None
          and "credit" not in next(a for a in cloud.load_cloud_data()["accounts"] if a["id"] == "anth"),
          "negative: a figure that is no number is refused, and the account is as it was")
    sub = refusal(lambda: cloud.upsert_cloud_account({"id": "plus", "type": "openai-subscription", "creditUsd": "10"}, now=7000))
    check(sub == (400, "a subscription has limits, not a dollar credit"),
          "negative: a subscription has limits, not a dollar credit — a figure sent for one is refused, not dropped without a word")
    ok = cloud.upsert_cloud_account({"id": "plus", "type": "openai-subscription", "creditUsd": ""}, now=7000)
    check("credit" not in ok, "boundary: a blank figure for a subscription is no figure — nothing to refuse")

    print("what the board is told:")
    cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "creditUsd": "200"}, now=8000)
    cloud.upsert_cloud_account({"id": "zero", "type": "openai", "creditUsd": "0"}, now=8000)
    cloud.upsert_cloud_account({"id": "bare", "type": "ollama"}, now=8000)
    by = {a["id"]: a for a in cloud.cloud_accounts_state()}
    check((by["anth"]["creditUsd"], by["anth"]["creditAsOf"]) == (200.0, 8000), "the account's state carries the figure and its moment")
    check((by["zero"]["creditUsd"], by["zero"]["creditAsOf"]) == (0.0, 8000), "a credit of 0 is told as 0 — a credit used up")
    check((by["bare"]["creditUsd"], by["bare"]["creditAsOf"], by["plus"]["creditUsd"]) == (None, None, None),
          "negative: no credit is told as none (null), never as 0 — the board must not draw 'nothing left' for an account nobody counted")


#: Four prices: the LiteLLM table's, and an operator's own over one of them. `claude-cached` names its cache prices (the fixture's: a tenth of the
#: input for a read, a quarter more for a write); the others, like a table of the older shape, do not.
TABLE = {"claude-sonnet-5-5": {"inputPer1M": 2.0, "outputPer1M": 10.0}, "claude-opus-5-5": {"inputPer1M": 4.0, "outputPer1M": 20.0},
         "free-row": {"inputPer1M": 0, "outputPer1M": 0},
         "claude-cached": {"inputPer1M": 2.0, "outputPer1M": 10.0, "cacheReadPer1M": 0.2, "cacheWritePer1M": 2.5}}


def section_the_price_rule():
    print("one price rule:")
    prices = ModelPrices(TABLE, {"claude-opus-5-5": {"inputPer1M": 1.0, "outputPer1M": 2.0}, "mine": {"inputPer1M": 0.5, "outputPer1M": 0}})
    check(prices.of("claude-sonnet-5-5") == (2.0, 10.0, True), "the table's price when the operator named none")
    check(prices.of("claude-opus-5-5") == (1.0, 2.0, True), "the operator's own price beats the table's")
    check(prices.of("mine") == (0.5, 0.0, True), "a model only the operator priced is priced")
    check(prices.of("free-row") == (0.0, 0.0, False) and prices.of("nobody") == (0.0, 0.0, False),
          "negative: a row that names neither number, and a model in no table, are KNOWN not to be priced — not priced at 0")
    check(ModelPrices({"m": {"inputPer1M": 3.0, "outputPer1M": 1.0}}, {"m": {"inputPer1M": 0, "outputPer1M": 0}}).of("m") == (3.0, 1.0, True),
          "negative: an operator's row of zeros is no price: the table's stands (as the statistics panel always read it)")
    check(ModelPrices(None, None).of("m") == (0.0, 0.0, False) and ModelPrices("x", ["y"]).of("m") == (0.0, 0.0, False),
          "boundary: no tables, or tables of the wrong shape — nothing priced, no crash")
    cost, known = prices.cost("claude-sonnet-5-5", 1_000_000, 100_000)
    check((round(cost, 6), known) == (3.0, True), f"a million tokens in and a hundred thousand out at 2/10 dollars: 3.00 (got {cost})")
    cost, known = prices.cost("nobody", 5_000_000, 5_000_000)
    check((cost, known) == (0.0, False), "negative: an unpriced model adds 0 and says it is unpriced")

    print("the cache has its own two prices (1.3.585):")
    check(prices.cache_of("claude-cached") == (0.2, 2.5), "the table's own cache prices, as the fixture names them: a read at a tenth of the input, a write at a quarter more")
    check(prices.cache_of("claude-sonnet-5-5") == (2.0, 2.0),
          "negative: a row that names none — a table of the older shape — prices the cache as plain input: the cache is not free, and that is the nearest price there is")
    check(prices.cache_of("nobody") == (0.0, 0.0) and prices.cache_of("free-row") == (0.0, 0.0), "a model nobody priced has no cache price either")
    mine = ModelPrices(TABLE, {"claude-cached": {"inputPer1M": 1.0, "outputPer1M": 2.0}})
    check(mine.cache_of("claude-cached") == (1.0, 1.0),
          "the operator's price beats the table's, cache and all: it names none, so the cache goes at HIS input price — not at the table's cheaper read")
    odd = ModelPrices({"m": {"inputPer1M": 3.0, "outputPer1M": 1.0, "cacheReadPer1M": "x", "cacheWritePer1M": -1},
                       "b": {"inputPer1M": 3.0, "outputPer1M": 1.0, "cacheReadPer1M": True, "cacheWritePer1M": False}})
    check(odd.cache_of("m") == (3.0, 3.0) and odd.cache_of("b") == (3.0, 3.0),
          "negative: a cache price that is text, negative or a boolean is no price: the input's")
    plain = prices.cost("claude-cached", 2112, 2)[0]
    check(round(plain, 9) == round((2112 * 2.0 + 2 * 10.0) / 1e6, 9), "no cache counts: all the prompt is plain input, as before")
    cost, known = prices.cost("claude-cached", 2112, 2, cache_read=2000, cache_write=100)
    check((round(cost * 1e6, 6), known) == (12 * 2.0 + 2000 * 0.2 + 100 * 2.5 + 2 * 10.0, True),
          f"2112 tokens in — 12 plain, 2000 read from the cache, 100 written to it — and 2 out: 24 + 400 + 250 + 20 = 694 millionths of a dollar (got {cost * 1e6})")
    cost, _ = prices.cost("claude-sonnet-5-5", 1_000_000, 0, cache_read=900_000)
    check(round(cost, 6) == 2.0, "negative: a model whose table names no cache price is charged the plain price for what it read from the cache")
    cost, _ = prices.cost("claude-cached", 100, 0, cache_read=500)
    check(round(cost * 1e6, 6) == 100 * 0.2, "boundary: a cache count above its prompt is cut to the prompt — never priced for more input than the request had")
    cost, _ = prices.cost("claude-cached", 100, 0, cache_read=60, cache_write=60)
    check(round(cost * 1e6, 6) == 60 * 0.2 + 40 * 2.5, "boundary: a read and a write that together pass the prompt — the read keeps its share, the write gets what is left")
    cost, _ = prices.cost("claude-cached", 100, 10, cache_read=-5, cache_write=-5)
    check(round(cost * 1e6, 6) == 100 * 2.0 + 10 * 10.0, "negative: a negative cache count is none")
    check(prices.cost("nobody", 10, 10, 5, 5) == (0.0, False), "negative: an unpriced model adds 0 with any cache")
    cost, _ = prices.cost("claude-cached", 100, -10)
    check(round(cost * 1e6, 6) == 100 * 2.0, "negative: a negative output is none")
    cost, _ = prices.cost("claude-cached", -5, 10, cache_read=3)
    check(round(cost * 1e6, 6) == 10 * 10.0, "negative: a negative prompt is none, and the cache of it with it")


def write_logs(log_dir, rows):
    """Each row on the log day of its own `time`, as the proxy writes them (events.py)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    for path in log_dir.glob("*.jsonl"):
        path.unlink()
    for row in rows:
        day = datetime.fromtimestamp(row["time"]).strftime("%Y-%m-%d")
        with (log_dir / f"{day}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")


def finished(at, account, model, prompt, completion, kind="cloud", cache_read=0, cache_write=0):
    usage = {"prompt": prompt, "completion": completion}
    if cache_read:
        usage["cacheRead"] = cache_read
    if cache_write:
        usage["cacheWrite"] = cache_write
    return {"time": at, "event": "finished", "item": {"upstreamType": kind, "cloudAccountId": account, "cloudModel": model, "usage": usage}}


class Rig:
    """The spend meter pointed at a log folder, a price table and the operator's own prices of the test's."""

    def __init__(self, rows, overrides=None, retention=30):
        self.log_dir = TMP / "logs"
        write_logs(self.log_dir, rows)
        self.overrides = overrides or {}
        self.retention = retention

    def __enter__(self):
        self.saved = (cloud_api.AGENT_PROXY_LOG_DIR, cloud_api.fetch_model_pricing, cloud_api.LOG_RETENTION_DAYS,
                      dict(cloud_api.admin_state.get("apiPricing") or {}))
        cloud_api.AGENT_PROXY_LOG_DIR = self.log_dir
        cloud_api.fetch_model_pricing = lambda: TABLE
        cloud_api.LOG_RETENTION_DAYS = self.retention
        cloud_api.admin_state["apiPricing"] = self.overrides
        return self

    def __exit__(self, *exc):
        (cloud_api.AGENT_PROXY_LOG_DIR, cloud_api.fetch_model_pricing, cloud_api.LOG_RETENTION_DAYS) = self.saved[:3]
        cloud_api.admin_state["apiPricing"] = self.saved[3]


def section_the_spend():
    print("what went through the caravan:")
    typed = NOON - 2 * 3600       # the figure was typed two hours before `now`
    cloud.save_cloud_data({"accounts": [], "pools": []})
    cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "creditUsd": "200"}, now=typed)
    cloud.upsert_cloud_account({"id": "plain", "type": "openai"}, now=typed)
    S = "claude-sonnet-5-5"
    rows = [finished(typed - 3600, "anth", S, 1_000_000, 100_000),        # an hour BEFORE the figure: in the window, not in the credit
            finished(typed, "anth", S, 1_000_000, 0),                     # at the very second it was typed: counted from it (>=)
            finished(typed + 60, "anth", S, 1_000_000, 100_000),          # after it: both
            finished(typed + 120, "anth", "claude-unknown", 5_000, 5_000),  # no price: adds 0, counted
            finished(typed + 180, "plain", S, 2_000_000, 0),
            finished(typed + 240, "anth", S, 9_000_000, 9_000_000, kind="llama"),   # a local request is no cloud spend
            finished(NOON - 40 * DAY, "anth", S, 1_000_000, 0)]           # 40 days ago: far outside the window, before the figure
    with Rig(rows):
        got = cloud_api.cloud_spend_summary(days=30, now=NOON)
    a = got["anth"]
    check((a["requests"], round(a["total"], 4), a["unpriced"]) == (4, 8.0, 1),
          f"the window: four cloud requests of the account, 3.00 + 2.00 + 3.00 + 0 — the local one and the 40-day-old one are not in it (got {a['requests']}, {a['total']}, {a['unpriced']})")
    check(a["sinceCredit"]["requests"] == 3 and round(a["sinceCredit"]["total"], 4) == 5.0 and a["sinceCredit"]["unpriced"] == 1,
          f"since the figure was typed: the request of that very second (2.00), the one after it (3.00) and the unpriced one counted — not the one before (got {a['sinceCredit']})")
    check(a["sinceCredit"]["asOf"] == typed and a["sinceCredit"]["partial"] is False, "it says from when it counts, and that the logs cover it")
    check("sinceCredit" not in got["plain"] and got["plain"]["requests"] == 1 and round(got["plain"]["total"], 4) == 4.0,
          "negative: an account with no credit has no sinceCredit — and its own spend is its own (4.00), not the other account's")
    check(sorted(m["model"] for m in a["byModel"]) == ["claude-sonnet-5-5", "claude-unknown"] and a["windowDays"] == 30,
          "the window's models, as before")

    print("a price the operator typed counts:")
    with Rig(rows, overrides={S: {"inputPer1M": 1.0, "outputPer1M": 1.0}}):
        got = cloud_api.cloud_spend_summary(days=30, now=NOON)
        stats = cloud_api.usage_stats(days=30, now=NOON)
    check((round(got["anth"]["total"], 4), round(got["anth"]["sinceCredit"]["total"], 4)) == (3.2, 2.1),
          f"the operator's price (1/1 dollar) over the table's: 1.1 + 1.0 + 1.1 in the window, 1.0 + 1.1 since the figure (got {got['anth']['total']})")
    check(round(stats["cloud"]["byAccount"]["anth"]["total"], 4) == round(got["anth"]["total"], 4),
          "the statistics panel and the board's meter say the same figure for the same logs: one price rule, not two")
    with Rig(rows):
        plain = cloud_api.cloud_spend_summary(days=30, now=NOON)
        stats = cloud_api.usage_stats(days=30, now=NOON)
    check(round(stats["cloud"]["byAccount"]["anth"]["total"], 4) == round(plain["anth"]["total"], 4) == 8.0,
          "and with no price of the operator's own: the table's, in both")

    print("how far back the figure counts:")
    old = NOON - 40 * DAY
    cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "creditUsd": "200"}, now=old)
    cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "creditUsd": "199"}, now=old)
    rows40 = [finished(old + 60, "anth", S, 1_000_000, 0), finished(NOON - 5 * DAY, "anth", S, 1_000_000, 0)]
    with Rig(rows40, retention=60):
        got = cloud_api.cloud_spend_summary(days=30, now=NOON)
    check(round(got["anth"]["sinceCredit"]["total"], 4) == 4.0 and got["anth"]["sinceCredit"]["partial"] is False
          and round(got["anth"]["total"], 4) == 2.0 and got["anth"]["requests"] == 1,
          f"a figure typed 40 days ago counts back that far (2.00 + 2.00) while the window shows only its own 30 days (2.00) (got {got['anth']})")
    with Rig(rows40, retention=30):
        got = cloud_api.cloud_spend_summary(days=30, now=NOON)
    check(got["anth"]["sinceCredit"]["partial"] is True,
          "the proxy keeps its logs 30 days: a figure older than that is a floor — said (partial), not drawn as the whole")
    with Rig(rows40, retention=0):
        got = cloud_api.cloud_spend_summary(days=30, now=NOON)
    check(got["anth"]["sinceCredit"]["partial"] is False,
          "boundary: logs kept without end (retention 0) — never partial")
    with Rig([], retention=60):
        got = cloud_api.cloud_spend_summary(days=30, now=NOON)
    check(list(got) == ["anth"] and got["anth"]["sinceCredit"] == {"asOf": old, "total": 0.0, "requests": 0, "unpriced": 0, "partial": False}
          and got["anth"]["requests"] == 0,
          f"no traffic at all: the credited account still has its row, with a zero spend since its figure — 'nothing spent' is an answer of the reading, "
          f"named for the figure it counts from, not the absence of one (got {got})")
    check("plain" not in got, "negative: an account with no credit and no traffic has no row")


def section_the_cache_in_the_spend():
    print("what the cache costs in the spend (1.3.585):")
    typed = NOON - 2 * 3600
    cloud.save_cloud_data({"accounts": [], "pools": []})
    cloud.upsert_cloud_account({"id": "anth", "type": "anthropic", "creditUsd": "200"}, now=typed)
    C = "claude-cached"
    rows = [
        # a million tokens in — 50 thousand plain, 900 thousand read from the cache, 50 thousand written to it — and a hundred thousand out:
        # 50k * 2.0 + 900k * 0.2 + 50k * 2.5 + 100k * 10.0 = 100000 + 180000 + 125000 + 1000000 = 1.405 dollars
        finished(typed + 60, "anth", C, 1_000_000, 100_000, cache_read=900_000, cache_write=50_000),
        # a row of the journal before the cache was told: a million tokens in, all priced as input, as it was: 2.0 + 1.0 = 3.0 dollars
        finished(typed + 120, "anth", C, 1_000_000, 100_000),
    ]
    with Rig(rows):
        got = cloud_api.cloud_spend_summary(days=30, now=NOON)
        stats = cloud_api.usage_stats(days=30, now=NOON)
    a = got["anth"]
    check(round(a["total"], 4) == 4.405 and a["requests"] == 2 and a["unpriced"] == 0,
          f"the meter prices the cache: 1.405 for the row that names it and 3.00 for the older row that does not (got {a['total']}, {a['requests']}, {a['unpriced']})")
    check(round(a["sinceCredit"]["total"], 4) == 4.405, f"and the credit counts down by the same (got {a['sinceCredit']['total']})")
    check((a["promptTokens"], a["completionTokens"]) == (2_000_000, 200_000),
          f"the tokens of the window are ALL the input, the cached too — the figure the card says as '2M tok' (got {a['promptTokens']}, {a['completionTokens']})")
    check(round(stats["cloud"]["byAccount"]["anth"]["total"], 4) == round(a["total"], 4),
          "the statistics panel says the same: one price rule, the cache in it")
    with Rig([finished(typed + 60, "anth", C, 1_000_000, 100_000, cache_read=900_000, cache_write=50_000)], overrides={C: {"inputPer1M": 1.0, "outputPer1M": 1.0}}):
        mine = cloud_api.cloud_spend_summary(days=30, now=NOON)
    check(round(mine["anth"]["total"], 4) == 1.1, f"a price the operator typed counts, the whole prompt at it: 1.0 + 0.1 (got {mine['anth']['total']})")
    with Rig([finished(typed + 60, "anth", C, 0, 600)]):
        old = cloud_api.cloud_spend_summary(days=30, now=NOON)
    check(round(old["anth"]["total"], 6) == 0.006,
          f"negative: a journal row written before the input was counted (prompt 0, 600 out) keeps its figure — nothing to price twice (got {old['anth']['total']})")


def main():
    section_the_figure()
    section_the_account()
    section_the_price_rule()
    section_the_spend()
    section_the_cache_in_the_spend()
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for msg in _fail:
            print("  -", msg)
        return 1
    print("\ncredit left OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
