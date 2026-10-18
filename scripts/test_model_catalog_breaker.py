#!/usr/bin/env python3
"""The breaker around a provider's endpoint counts the provider's failures, not the road's (1.3.584).

On 2026-10-18 the Routing page showed `API issues: models — off after 3 fails — failed to fetch models: <urlopen error [Errno 101] Network is
unreachable>` on the Anthropic account. The NAS had had no route to the provider for about twenty minutes; the model list is refreshed every
ten minutes while the board is open, so three refreshes failed in a row, and the breaker — meant for an endpoint that keeps refusing — turned
the list off for six hours. The network was back long before; the list stayed off until someone pressed "retry".

Pinned, by value, each with its negative: what a failure of the road is (no answer came: unreachable, refused, reset, timed out, no name) and what is not
(an HTTP status, which is the provider's answer; a plain error); that the provider's three strikes still trip the endpoint, with the same six hours doubling
to forty-eight; that the road's failures are SHOWN (the count and the error, so the card says what is the matter) and never block, however many; that the two
counts are kept apart (a road failure between two of the provider's neither erases nor adds one); that a record written before the split still means what it
meant; that the next success clears it; the guarded call end to end; and the wiring: every place that wraps a failure into an AppError keeps what it was made of.

The state file is a temp file and the clock is a stand-in.

Run: python3 scripts/test_model_catalog_breaker.py
"""
import json
import re
import socket
import sys
import tempfile
import types
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin import model_catalog as mc  # noqa: E402
from caravan.common.errors import AppError  # noqa: E402

_fail = []
NOW = [1_790_000_000]
mc.time = types.SimpleNamespace(time=lambda: float(NOW[0]))
H = 3600


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def fresh(record=None):
    """A catalogue file of its own; `record` is an endpoint record as an older version wrote it."""
    mc.MODEL_CATALOG_FILE = Path(tempfile.mkdtemp(prefix="catalog-")) / "model-catalog.json"
    NOW[0] = 1_790_000_000
    if record is not None:
        mc.MODEL_CATALOG_FILE.write_text(json.dumps({"endpoints": {"k": record}}), encoding="utf-8")


def report(key="k"):
    return mc.endpoints_report().get(key)


def http(code=500):
    return urllib.error.HTTPError("https://api.example/v1/models", code, "x", {}, None)


def made_from(cause, text="failed to fetch models"):
    try:
        try:
            raise cause
        except Exception as exc:
            raise AppError(f"{text}: {exc}", 502) from exc
    except AppError as err:
        return err


def test_what_is_the_road():
    print("what a failure of the road is:")
    unreachable = urllib.error.URLError(OSError(101, "Network is unreachable"))
    roads = [unreachable, socket.timeout("timed out"), ConnectionResetError(104, "reset"), ConnectionRefusedError(111, "refused"),
             socket.gaierror(-2, "Name or service not known"), OSError(101, "Network is unreachable"), made_from(unreachable), made_from(TimeoutError("t"))]
    check([mc.is_network_failure(e) for e in roads] == [True] * len(roads),
          "no answer came — unreachable, a timeout, a reset, a refused connection, no name, a bare OS error, and an AppError made from one of them (`raise ... from`): the road's")
    provider = [http(500), http(429), http(401), made_from(http(503), "HTTP 503"), AppError("HTTP 502: bad gateway", 502), ValueError("not json"), KeyError("data"),
                AppError("chatgpt.com returned 500", 502)]
    check([mc.is_network_failure(e) for e in provider] == [False] * len(provider),
          "negative: a status is the provider's answer (an HTTPError, or an AppError made from one, or one with no cause at all), and a plain error is a bug, not the road: counted")


def test_the_provider_still_trips_it():
    print("the provider's own failures still trip it:")
    fresh()
    for _ in range(2):
        mc.record_fail("k", "HTTP 500")
    check(not mc.endpoint_blocked("k") and report()["failCount"] == 2, "two failures are not three: the endpoint still answers calls")
    mc.record_fail("k", "HTTP 500")
    check(mc.endpoint_blocked("k") and report()["disabledUntil"] == NOW[0] + 6 * H and report()["network"] is False,
          "the third trips it for six hours — the provider's refusal, not the road's")
    NOW[0] += 6 * H + 1
    check(not mc.endpoint_blocked("k"), "six hours later it is armed again")
    mc.record_fail("k", "HTTP 500")
    check(report()["disabledUntil"] == NOW[0] + 12 * H, "a fourth in a row doubles it: twelve hours")
    for _ in range(8):
        NOW[0] += 100 * H
        mc.record_fail("k", "HTTP 500")
    check(report()["disabledUntil"] - NOW[0] == 48 * H, "and the doubling stops at forty-eight hours")


def test_the_road_never_trips_it():
    print("the road's failures are shown and never block:")
    fresh()
    for _ in range(10):
        mc.record_fail("k", "failed to fetch models: <urlopen error [Errno 101] Network is unreachable>", network=True)
    got = report()
    check((got["failCount"], got["disabled"], got["disabledUntil"], got["network"]) == (10, False, 0, True) and not mc.endpoint_blocked("k"),
          "ten failures of the road in a row: counted for the card (10), the error kept, marked as the road's — and the endpoint is never off")
    check("Network is unreachable" in got["lastError"] and got["lastErrorAt"] == NOW[0], "negative: what is the matter is still said, and when")
    mc.record_ok("k")
    check(report() is None, "the next success clears the record: the card says nothing again")


def test_the_two_counts_are_apart():
    print("the provider's count and the road's are kept apart:")
    fresh()
    mc.record_fail("k", "HTTP 500")
    mc.record_fail("k", "HTTP 500")
    for _ in range(5):
        mc.record_fail("k", "Network is unreachable", network=True)
    check(not mc.endpoint_blocked("k") and report()["failCount"] == 7, "two of the provider's and five of the road's: nothing tripped — the road added none")
    mc.record_fail("k", "HTTP 500")
    check(mc.endpoint_blocked("k") and report()["failCount"] == 8 and report()["network"] is False,
          "the third of the provider's trips it, however many failures of the road came between: they neither erased a strike nor added one")
    fresh()
    for _ in range(3):
        mc.record_fail("k", "Network is unreachable", network=True)
    mc.record_fail("k", "HTTP 500")
    mc.record_fail("k", "HTTP 500")
    check(not mc.endpoint_blocked("k"), "negative: three of the road's before two of the provider's are not three strikes")


def test_a_record_of_an_older_version():
    print("a record written before the split (1.3.583 and earlier):")
    fresh({"failCount": 2, "lastError": "HTTP 500", "lastErrorAt": NOW[0]})
    mc.record_fail("k", "HTTP 500")
    check(mc.endpoint_blocked("k"), "it had counted every failure as the provider's: two, and one more trips it, as it did")
    fresh({"failCount": 2, "lastError": "HTTP 500", "lastErrorAt": NOW[0]})
    mc.record_fail("k", "Network is unreachable", network=True)
    check(not mc.endpoint_blocked("k") and report()["failCount"] == 3, "a failure of the road on top of it does not trip it")
    mc.record_fail("k", "HTTP 500")
    check(mc.endpoint_blocked("k"), "and the two it had counted stand: the next of the provider's is the third")
    fresh({"failCount": 3, "disabledUntil": NOW[0] + 5 * H, "lastError": "x", "lastErrorAt": NOW[0]})
    check(mc.endpoint_blocked("k") and report()["network"] is False, "a trip written by the old version stands until its time, or until \"retry\"")
    mc.retry_endpoint("k")
    check(report() is None and not mc.endpoint_blocked("k"), "\"retry\" forgets it, as it did")


def test_the_guarded_call():
    print("the guarded call:")
    fresh()
    calls = []

    def road():
        calls.append(1)
        try:
            raise urllib.error.URLError(OSError(101, "Network is unreachable"))
        except Exception as exc:
            raise AppError(f"failed to fetch models: {exc}", 502) from exc
    for _ in range(6):
        try:
            mc.guarded_call("k", road)
        except AppError:
            pass
    check(len(calls) == 6 and not mc.endpoint_blocked("k") and report()["failCount"] == 6 and report()["network"] is True,
          "six calls that find no road: each asked the network again (6) and none was refused — the card shows 6 fails, the endpoint is on")
    check(mc.guarded_call("k", lambda: "back") == "back" and report() is None,
          "and the first call that finds the road again clears the record by itself — no \"retry\" to press, the card goes quiet")

    def provider():
        calls.append(1)
        try:
            raise http(500)
        except Exception as exc:
            raise AppError(f"HTTP 500: {exc}", 502) from exc
    fresh()
    calls.clear()
    for _ in range(5):
        try:
            mc.guarded_call("k", provider)
        except AppError as err:
            last = str(err)
    check(len(calls) == 3 and mc.endpoint_blocked("k") and last.startswith("endpoint disabled after 3 failures"),
          "negative: the provider's 500, three times, trips it: the fourth and fifth call are refused without asking the provider (3 asked)")
    fresh()
    check(mc.guarded_call("k", lambda: 7) == 7 and report() is None, "a call that works leaves no record")


def test_the_wiring():
    print("what wraps a failure keeps what it was made of:")
    text = (ROOT / "caravan" / "admin" / "cloud_api.py").read_text(encoding="utf-8")
    wrapped = re.findall(r'raise AppError\(f"(failed to fetch models|usage endpoint): \{e\}", 502\)( from e)?', text)
    check(len(wrapped) == 3 and all(w[1] for w in wrapped),
          f"the three places that turn an error of the road into an AppError (the two model lists, the usage) say `from e`, or the breaker cannot tell the road from the provider (got {wrapped})")
    direct = re.findall(r"model_catalog\.record_fail\(ep_key, str\(e\)(?:, network=model_catalog\.is_network_failure\(e\))?\)", text)
    check(len(direct) == 2 and all("is_network_failure" in d for d in direct),
          f"the two endpoints that record a failure by hand (the costs, the limits) classify it too (got {len(direct)})")


if __name__ == "__main__":
    for fn in (test_what_is_the_road, test_the_provider_still_trips_it, test_the_road_never_trips_it, test_the_two_counts_are_apart,
               test_a_record_of_an_older_version, test_the_guarded_call, test_the_wiring):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            check(False, f"{fn.__name__} crashed: {exc!r}")
    if _fail:
        print(f"\nFAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        sys.exit(1)
    print("\nmodel catalog breaker OK: the provider's failures trip it, the road's are shown and never block")
