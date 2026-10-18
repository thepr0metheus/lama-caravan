#!/usr/bin/env python3
"""The LiteLLM price table carries the cache prices, and an old table is not trusted for them (1.3.585).

A token read from the cache costs a fraction of a plain input token at Anthropic, a token written to it more, and the Console bills them so.
The table the meter prices by (`fetch_model_pricing`, cached on disk for 24 h) had only the plain input and the output. Two things follow, and both
are pinned here, by value, each with its negative:

- the cache prices are read from the table — `cache_read_input_token_cost` and `cache_creation_input_token_cost` — as dollars per million; a row that
  names none has none, a price that is text, negative or a boolean is no price, and one bad row does not take the table down with it;
- the table on disk has a shape. A file written before the cache prices (no `shape`) is refetched even though its day is not up — it would price every
  cached token as a plain one for up to a day — and when the fetch fails the old table is returned rather than nothing: an old price is better than none,
  and no price reads as a spend of nothing. A table of the current shape inside its day is read without asking the network.

And the route `/api/model-pricing`, which lays the operator's own prices over the table for the price tags: a price the operator typed replaces the
table's INCLUDING its cache prices (they belong to the table's input price), as `ModelPrices` prices the cache at the operator's.

The network is a stand-in and the cache file is a temp file.

Run: python3 scripts/test_model_pricing.py
"""
import io
import json
import os
import sys
import tempfile
import time
import urllib.error
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="caravan-pricing-"))
os.environ["CARAVAN_DATA_DIR"] = str(TMP)
for sub in ("state", "config", "secrets"):
    (TMP / sub).mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

from caravan.admin import pricing, routes  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


RAW = {
    "claude-x": {"input_cost_per_token": 3e-06, "output_cost_per_token": 1.5e-05, "cache_read_input_token_cost": 3e-07,
                 "cache_creation_input_token_cost": 3.75e-06, "litellm_provider": "anthropic"},
    "gpt-y": {"input_cost_per_token": 1.25e-06, "output_cost_per_token": 1e-05, "cache_read_input_token_cost": 1.25e-07, "litellm_provider": "openai"},
    "plain-z": {"input_cost_per_token": 2e-06, "output_cost_per_token": 4e-06, "litellm_provider": "other"},
    "odd-1": {"input_cost_per_token": 1e-06, "output_cost_per_token": 2e-06, "cache_read_input_token_cost": "abc", "cache_creation_input_token_cost": -1e-06},
    "odd-2": {"input_cost_per_token": 1e-06, "output_cost_per_token": 2e-06, "cache_read_input_token_cost": True, "cache_creation_input_token_cost": [1]},
    "odd-3": {"input_cost_per_token": 1e-06, "output_cost_per_token": 2e-06, "cache_read_input_token_cost": None},
    "no-price": {"max_tokens": 100, "litellm_provider": "other"},
    "not-a-row": "text",
}
WANT = {
    "claude-x": {"inputPer1M": 3.0, "outputPer1M": 15.0, "provider": "anthropic", "cacheReadPer1M": 0.3, "cacheWritePer1M": 3.75},
    "gpt-y": {"inputPer1M": 1.25, "outputPer1M": 10.0, "provider": "openai", "cacheReadPer1M": 0.125},
    "plain-z": {"inputPer1M": 2.0, "outputPer1M": 4.0, "provider": "other"},
    "odd-1": {"inputPer1M": 1.0, "outputPer1M": 2.0, "provider": ""},
    "odd-2": {"inputPer1M": 1.0, "outputPer1M": 2.0, "provider": ""},
    "odd-3": {"inputPer1M": 1.0, "outputPer1M": 2.0, "provider": ""},
}


class Network:
    """A stand-in for urlopen: answers with a table, or with a refusal, and counts how often it was asked."""

    def __init__(self):
        self.calls = 0
        self.answer = RAW

    def __call__(self, request, timeout=None):
        self.calls += 1
        if self.answer is None:
            raise urllib.error.URLError(OSError(101, "Network is unreachable"))
        return io.BytesIO(json.dumps(self.answer).encode("utf-8"))


NET = Network()
pricing.urllib.request.urlopen = NET


def fresh(file_body=None):
    """A cache file of its own (`file_body` is its text, or None for no file) and a network that answers."""
    pricing.MODEL_PRICING_CACHE_PATH = Path(tempfile.mkdtemp(prefix="pricing-")) / "model-pricing-cache.json"
    if file_body is not None:
        pricing.MODEL_PRICING_CACHE_PATH.write_text(file_body, encoding="utf-8")
    NET.calls = 0
    NET.answer = RAW


def written():
    return json.loads(pricing.MODEL_PRICING_CACHE_PATH.read_text(encoding="utf-8"))


def test_the_table_is_read():
    print("the table is read:")
    fresh()
    got = pricing.fetch_model_pricing()
    check(got == WANT, f"each row: the plain prices as before, and the cache prices as dollars per million where the table names them (got {got})")
    check(got["claude-x"]["cacheReadPer1M"] == 0.3 and got["claude-x"]["cacheWritePer1M"] == 3.75, "the table's own prices, as the fixture names them: a read at a tenth of the input, a write a quarter more")
    check("cacheWritePer1M" not in got["gpt-y"] and "cacheReadPer1M" not in got["plain-z"],
          "negative: a row names what it names — an OpenAI row without a write price has none, a plain row has neither")
    check(all("cacheReadPer1M" not in got[k] and "cacheWritePer1M" not in got[k] for k in ("odd-1", "odd-2", "odd-3")),
          "negative: a price that is text, negative, a boolean, a list or null is no price — and its row is still in the table")
    check("no-price" not in got and "not-a-row" not in got, "a row with no input or output price, and a value that is no row, are not in the table (as before)")
    body = written()
    check(body["shape"] == pricing.PRICING_SHAPE == 2 and body["pricing"] == WANT and abs(body["fetchedAt"] - time.time()) < 10,
          "the file written says its shape (2), when it was fetched, and the table")
    check(pricing.per_million("2.5e-06") == 2.5 and pricing.per_million(0) == 0.0 and pricing.per_million(1e-07) == 0.1,
          "a price as a number or as text is dollars per million, rounded to six places")
    check(all(pricing.per_million(v) is None for v in (None, True, "abc", -1, [], {}, float("nan"))),
          "negative: nothing, a boolean, a word, a negative, a list, an object and nan are no price")


def test_the_file_on_disk():
    print("the file on disk:")
    old_table = {"claude-x": {"inputPer1M": 3.0, "outputPer1M": 15.0, "provider": "anthropic"}}
    fresh(json.dumps({"fetchedAt": int(time.time()), "shape": 2, "pricing": old_table}))
    got = pricing.fetch_model_pricing()
    check(got == old_table and NET.calls == 0, f"a table of the current shape inside its day is read as it is — the network is not asked (asked {NET.calls})")
    fresh(json.dumps({"fetchedAt": int(time.time()), "pricing": old_table}))
    got = pricing.fetch_model_pricing()
    check(NET.calls == 1 and got == WANT and written()["shape"] == 2,
          f"negative: a table written before the cache prices (no shape) is refetched though its day is not up, and the file is rewritten (asked {NET.calls})")
    fresh(json.dumps({"fetchedAt": int(time.time()), "shape": 1, "pricing": old_table}))
    pricing.fetch_model_pricing()
    check(NET.calls == 1, "negative: any other shape is refetched too")
    fresh(json.dumps({"fetchedAt": int(time.time()) - pricing.MODEL_PRICING_TTL - 5, "shape": 2, "pricing": old_table}))
    got = pricing.fetch_model_pricing()
    check(NET.calls == 1 and got == WANT, "negative: a table of the current shape whose day is up is refetched")


def test_when_the_fetch_fails():
    print("when the fetch fails:")
    old_table = {"claude-x": {"inputPer1M": 3.0, "outputPer1M": 15.0, "provider": "anthropic"}}
    fresh(json.dumps({"fetchedAt": int(time.time()), "pricing": old_table}))
    NET.answer = None
    got = pricing.fetch_model_pricing()
    check(NET.calls == 1 and got == old_table, f"the old table is returned, not nothing — a price a day old, or of the older shape, is better than none (got {got})")
    check("shape" not in written(), "and the file is not rewritten with it: the next call asks again")
    fresh(json.dumps({"fetchedAt": int(time.time()) - 10 * pricing.MODEL_PRICING_TTL, "shape": 2, "pricing": old_table}))
    NET.answer = None
    check(pricing.fetch_model_pricing() == old_table, "a table ten days old is returned too")
    fresh()
    NET.answer = None
    check(pricing.fetch_model_pricing() == {}, "negative: no file and no network: nothing — {}, as it always was")
    fresh("{ not json")
    NET.answer = None
    check(pricing.fetch_model_pricing() == {}, "negative: a file that is no JSON is no table")
    fresh(json.dumps({"fetchedAt": int(time.time()), "shape": 2, "pricing": "oops"}))
    NET.answer = None
    check(pricing.fetch_model_pricing() == {}, "negative: a file whose table is no object is no table")
    fresh(json.dumps(["list"]))
    NET.answer = None
    check(pricing.fetch_model_pricing() == {}, "negative: a file that is no object is no file")


class Handler:
    def __init__(self):
        self.sent = []

    def send_json(self, body, status=200):
        self.sent.append((status, body))


def test_the_route():
    print("the route:")
    keep = (routes.fetch_model_pricing, dict(routes.admin_state.get("apiPricing") or {}))
    routes.fetch_model_pricing = lambda: {k: dict(v) for k, v in WANT.items()}
    routes.admin_state["apiPricing"] = {"claude-x": {"inputPer1M": 1.0, "outputPer1M": 2.0}, "mine": {"inputPer1M": 0.5, "outputPer1M": 0}}
    try:
        h = Handler()
        routes.GET_ROUTES["/api/model-pricing"](h, urlparse("/api/model-pricing"))
    finally:
        routes.fetch_model_pricing, routes.admin_state["apiPricing"] = keep
    status, body = h.sent[0]
    table = body["pricing"]
    check(status == 200 and body["ok"] is True and table["gpt-y"] == WANT["gpt-y"],
          "a model the operator did not price is the table's row, cache price and all — the price tags can say it")
    check(table["claude-x"] == {"inputPer1M": 1.0, "outputPer1M": 2.0, "provider": "anthropic"},
          f"negative: the operator's price replaces the table's whole — the table's cache prices are gone, they belonged to the table's input price (got {table['claude-x']})")
    check(table["mine"] == {"inputPer1M": 0.5, "outputPer1M": 0, "provider": "manual"}, "a model only the operator priced is there, as manual, with no cache price")


def main():
    for fn in (test_the_table_is_read, test_the_file_on_disk, test_when_the_fetch_fails, test_the_route):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(False, f"{fn.__name__} crashed: {exc!r}")
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        sys.exit(1)
    print("\nmodel pricing OK: the cache prices are read, an old table is refetched, and kept when the fetch fails")


if __name__ == "__main__":
    main()
