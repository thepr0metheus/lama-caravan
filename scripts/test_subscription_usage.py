#!/usr/bin/env python3
"""Snapshot of what the subscription card learns from OpenAI's usage answer.

Pins `_normalize_subscription_usage` by value on two real shapes: the one
captured in its docstring (a plan with credits) and the one seen live on
2026-09-06 (a plan blocked at its weekly limit, no credits, OpenAI's own
banner naming a banked reset). The card's banner reads these fields; a
field that goes missing here silently empties that banner.

Run: python3 scripts/test_subscription_usage.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.cloud_api import _normalize_subscription_usage  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


WITH_CREDITS = {
    "rate_limit": {
        "primary_window": {"used_percent": 3, "limit_window_seconds": 18000, "reset_after_seconds": 14217, "reset_at": 1779899331},
        "secondary_window": {"used_percent": 100, "limit_window_seconds": 604800, "reset_after_seconds": 336233, "reset_at": 1780221347},
    },
    "credits": {"has_credits": True, "balance": "394.7967250000"},
}

BLOCKED = {
    "plan_type": "plus",
    "rate_limit": {
        "allowed": False, "limit_reached": True,
        "primary_window": {"used_percent": 1, "limit_window_seconds": 18000, "reset_after_seconds": 15635, "reset_at": 1788708977},
        "secondary_window": {"used_percent": 100, "limit_window_seconds": 604800, "reset_after_seconds": 63848, "reset_at": 1788757189},
    },
    "additional_rate_limits": None,
    "credits": {"has_credits": False, "unlimited": False, "overage_limit_reached": False, "balance": "0",
                "approx_local_messages": [0, 0], "approx_cloud_messages": [0, 0]},
    "rate_limit_reached_type": {"type": "rate_limit_reached", "details": "default"},
    "rate_limit_upsell": {"banner_type": "plus_rate_limit_reached", "title": "You’re out of Codex and Work usage",
                          "description": "Use your banked reset, or save it for later and pay $8 to reset your usage limits now",
                          "ctas": [{"action": "reset", "label": "Reset usage"}, {"action": "buy", "label": "Buy a reset"}]},
}

RESERVE = {
    "rate_limit": {
        "allowed": True, "limit_reached": True,
        "primary_window": {"used_percent": 100, "limit_window_seconds": 604800, "reset_at": 1788757189},
        "additional_rate_limits": [{"limit_name": "gpt-reserve", "used_percent": 20, "limit_window_seconds": 604800, "reset_at": 1788757189}],
    },
    "credits": {"has_credits": False},
}


def refusals():
    """fetch_subscription_usage against a chatgpt.com that answers 401, 403 and 500."""
    import io
    import urllib.error
    import caravan.admin.cloud_api as ca
    saved = ca.load_cloud_data, ca._subscription_auth_headers, ca.model_catalog.guarded_call, ca.urllib.request.urlopen
    ca.load_cloud_data = lambda: {"accounts": [{"id": "sub"}], "blocks": []}
    ca._subscription_auth_headers = lambda account: ("token", "acct")
    ca.model_catalog.guarded_call = lambda key, fn: fn()
    out = {}
    try:
        for code in (401, 403, 500):
            def urlopen(req, timeout=0, code=code):
                raise urllib.error.HTTPError(req.full_url, code, "refused", {}, io.BytesIO(b""))
            ca.urllib.request.urlopen = urlopen
            try:
                ca.fetch_subscription_usage("sub")
                out[code] = None
            except ca.AppError as e:
                out[code] = (e.status, str(e))
    finally:
        ca.load_cloud_data, ca._subscription_auth_headers, ca.model_catalog.guarded_call, ca.urllib.request.urlopen = saved
    return out


def main():
    print("a plan with credits (the docstring's capture):")
    got = _normalize_subscription_usage(WITH_CREDITS)
    check(got["ok"] and [l["label"] for l in got["limits"]] == ["5h limit", "Weekly limit"], "two windows, labelled by duration")
    check([l["remainingPct"] for l in got["limits"]] == [97, 0], "remaining = 100 − used")
    check(got["credits"] == 395 and got["creditsInfo"]["hasCredits"] is True, "credits rounded, and the fact that there are some")
    check(got["limitReached"] is False and got["allowed"] is None, "no verdict fields → not reached, allowed unknown")
    check(got["upsell"] is None and got["reachedType"] == "", "no banner, no reached type")

    print("a plan blocked at its weekly limit (live, 2026-09-06):")
    got = _normalize_subscription_usage(BLOCKED)
    check(got["limitReached"] is True and got["allowed"] is False, "OpenAI's own verdict: reached, not allowed")
    check(got["planType"] == "plus" and got["reachedType"] == "rate_limit_reached" and got["reachedDetails"] == "default",
          "plan and the reached type are kept")
    check(got["credits"] is None and got["creditsInfo"]["hasCredits"] is False, "no credits — and said so, not merely absent")
    check(got["upsell"]["title"].startswith("You") and "banked reset" in got["upsell"]["description"]
          and got["upsell"]["ctas"] == ["Reset usage", "Buy a reset"],
          f"OpenAI's banner travels as it came, with its buttons (got {got['upsell']})")
    check(got["limits"][1]["remainingPct"] == 0 and got["limits"][1]["resetsAt"] == "2026-09-07T04:59:49Z",
          "the exhausted window and its reset moment")

    print("a reserve allowance:")
    got = _normalize_subscription_usage(RESERVE)
    check([l["label"] for l in got["limits"]] == ["Weekly limit", "gpt-reserve · Weekly limit"],
          f"a named window keeps its name in the label (got {[l['label'] for l in got['limits']]})")
    check(got["limits"][1]["name"] == "gpt-reserve" and got["limits"][1]["remainingPct"] == 80, "and its name and remainder as fields")

    check(_normalize_subscription_usage({})["ok"] is True and _normalize_subscription_usage({})["limits"] == [],
          "an empty answer is ok with no windows — nothing invented")

    print("when chatgpt.com refuses:")
    got = refusals()
    check(all(got[c][0] == 502 and "sign in again" in got[c][1] for c in (401, 403)),
          "defect-history: провайдер отказал токену — это 502 с подсказкой войти заново, а не 401 доски: "
          f"401 отправлял страницу на /login, и истёкший вход в ChatGPT выкидывал с доски (got {got[401]}, {got[403]})")
    check(got[500] == (502, "usage endpoint: HTTP 500"), f"negative: прочий отказ — как был (got {got[500]})")
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("all subscription-usage snapshots hold")


if __name__ == "__main__":
    main()
