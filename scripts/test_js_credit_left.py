#!/usr/bin/env python3
"""Actual credit-left.js: what is left of a key account's credit, as the board says it (1.3.568).

The owner added an Anthropic key and a model and asked why the board did not say how much money was left on it (2026-10-17). The
provider does not tell, so the account holds the figure the operator typed and the moment it was typed, and the controller counts what
went through the caravan since. CreditLeft turns the two into the line the board and the account window draw — by value, with the
negatives that matter most: a credit with no spend reading says the spend is not read (never "all of it left"), a reading made for
another figure counts nothing, and a figure that is too high says so.

The module is loaded FOR REAL; i18n, utils and usage-stats are stubbed: a key stands for its words with its arguments, and the
tone of a bar for the share it was asked for.

Run: python3 scripts/test_js_credit_left.py
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
import assert from "node:assert/strict";
globalThis.__stubReturns = {
  "i18n.t": (k, v) => (v ? `${k}${JSON.stringify(v)}` : k),
  "utils.escapeHtml": (x) => String(x ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
  "usage-stats.limitTone": (pct) => `tone${pct}`,
};
const { CreditLeft } = await import("../static/js/credit-left.js");
const pass = [];
const pin = (cond, why) => { assert.ok(cond, why); pass.push(why); };

const ACCOUNT = { id: "anth", creditUsd: 200, creditAsOf: 1800000000 };
const spend = (since, id = "anth") => ({ [id]: { total: 99, requests: 9, sinceCredit: since } });
const SINCE = { asOf: 1800000000, total: 16.6, requests: 4, unpriced: 0, partial: false };

// ── the credit as typed ──
{
  const typed = [200, "150.5", 0, "0", null, undefined, "", "abc", Infinity, NaN, true].map((v) => CreditLeft.typed({ creditUsd: v }));
  assert.deepEqual(typed, [200, 150.5, 0, 0, null, null, null, null, null, null, null]);
  pin(true, "the credit as the controller says it: a number, or a numeric string; 0 is a credit used up; junk, infinity and a bool are none");
  pin(CreditLeft.typed({ creditUsd: null }) === null && CreditLeft.typed({}) === null && CreditLeft.typed(null) === null && CreditLeft.typed(undefined) === null,
    "negative: no credit (null, none, no account) is null — never 0, which would draw 'nothing left'");
}

// ── the figures ──
{
  const f = CreditLeft.of(ACCOUNT, spend(SINCE));
  assert.deepEqual(f, { credit: 200, spent: 16.6, left: 183.4, pct: 92, unpriced: 0, partial: false, asOf: 1800000000 });
  pin(true, "the credit less what went through the caravan since it was typed: 200 − 16.60 = 183.40, 92% of it left");
  const over = CreditLeft.of(ACCOUNT, spend({ ...SINCE, total: 250 }));
  pin(over.left === 0 && over.pct === 0 && over.spent === 250, "spent over the credit: nothing left, never a negative figure — the spend is still said as it is");
  const zero = CreditLeft.of({ ...ACCOUNT, creditUsd: 0 }, spend({ ...SINCE, total: 0 }));
  pin(zero.credit === 0 && zero.left === 0 && zero.pct === 0, "boundary: a credit of 0 — nothing left, a share of 0, no division by it");
  pin(CreditLeft.of(ACCOUNT, spend({ ...SINCE, total: 0.4 })).pct === 100 && CreditLeft.of(ACCOUNT, spend({ ...SINCE, total: 0 })).pct === 100
      && CreditLeft.of(ACCOUNT, spend({ ...SINCE, total: -30 })).pct === 100,
    "the share rounds, and never above a hundred — not for a reading that says less than nothing was spent either");
  pin(CreditLeft.of(ACCOUNT, spend({ ...SINCE, unpriced: 3, partial: true })).unpriced === 3 && CreditLeft.of(ACCOUNT, spend({ ...SINCE, partial: true })).partial === true,
    "the requests with no price and the logs that do not reach back are carried");
  pin(CreditLeft.of(ACCOUNT, spend({ ...SINCE, partial: "yes" })).partial === false && CreditLeft.of(ACCOUNT, spend({ ...SINCE, unpriced: "x" })).unpriced === 0,
    "negative: only a true `partial` is partial; a junk count of unpriced is none, not NaN");
  pin(CreditLeft.of({ id: "anth" }, spend(SINCE)) === null && CreditLeft.of({ ...ACCOUNT, creditUsd: null }, spend(SINCE)) === null,
    "negative: an account with no credit has no figures");
  pin(CreditLeft.of(ACCOUNT, null) === null && CreditLeft.of(ACCOUNT, undefined) === null,
    "negative: no spend reading yet — no figures: 'all of it left' is not what an unread meter means");
  pin(CreditLeft.of(ACCOUNT, {}) === null && CreditLeft.of(ACCOUNT, spend(SINCE, "other")) === null,
    "negative: a reading with no entry for the account (a failed read gives {}) — no figures; another account's entry is not this one's");
  pin(CreditLeft.of(ACCOUNT, spend(undefined)) === null && CreditLeft.of(ACCOUNT, spend({ ...SINCE, asOf: 1799999000 })) === null,
    "negative: a reading with no sinceCredit, or counted from another figure (made before this one was typed), counts nothing");
  pin(CreditLeft.of({ ...ACCOUNT, creditAsOf: null }, spend(SINCE)) === null && CreditLeft.of({ id: "anth", creditUsd: 5 }, spend(SINCE)) === null,
    "negative: a credit with no moment cannot be matched to a reading");
}

// ── the words ──
{
  const money = [200, 183.4, 1234.5, 42.5, 42, 0, 0.5, "7", NaN, undefined, 99.999, 100, 99.99, 100.4, 0.004, 0.005].map((v) => CreditLeft.money(v));
  assert.deepEqual(money, ["$200", "$183", "$1,235", "$42.50", "$42", "$0", "$0.50", "$7", "$0", "$0", "$100", "$100", "$99.99", "$100", "<$0.01", "$0.01"]);
  pin(true, "dollars: whole from a hundred up, cents below, none for zero; a junk figure is $0, not NaN; what is left but too small for cents is \"<$0.01\", not $0 (1.3.585)");
  pin(CreditLeft.day(1800000000) === "Jan 15", "the day the figure was typed, short, in the page's language");
}

// ── the line ──
{
  pin(CreditLeft.html({ id: "x" }, spend(SINCE)) === "" && CreditLeft.html({ id: "x", creditUsd: null }, null) === "",
    "no credit typed: no line at all — an account nobody counted must not draw 'nothing left'");
  const unread = CreditLeft.html(ACCOUNT, null);
  pin(unread.includes('data-t-state="unread"') && unread.includes('creditUnread{&quot;credit&quot;:&quot;$200&quot;}') && unread.includes('title="creditHint"')
      && !unread.includes("sub-meter") && !unread.includes("creditLeft"),
    "a credit with no spend reading: the figure alone and 'the spend is not read yet'; negative: no bar, no 'left'");
  pin(CreditLeft.html(ACCOUNT, spend(SINCE, "other")).includes('data-t-state="unread"'),
    "a reading with no entry for the account is unread too");
  const known = CreditLeft.html(ACCOUNT, spend(SINCE));
  pin(known.includes('data-t-state="known"') && known.includes('data-t-id="anth"') && known.includes("sub-meter credit-meter") && known.includes('title="creditHint"'),
    "the meter: the subscription limits' bar, said as an estimate in its hover");
  pin(known.includes('<span class="sub-meter-label">creditLeft{&quot;left&quot;:&quot;$183&quot;}</span>')
      && known.includes('<span class="sub-meter-pct">creditOf{&quot;credit&quot;:&quot;$200&quot;}</span>'),
    "what is left stands before the bar, of how much after it");
  pin(known.includes('style="width:92%;background:tone92"'), "the bar is the share left, in the colour of that share (the limits' own thresholds)");
  pin(known.includes('data-t="credit-since">creditSince{&quot;date&quot;:&quot;Jan 15&quot;}</div>'),
    "one muted line says it is an estimate and from when it counts");
  pin(known.includes('role="meter"') && known.includes('aria-valuemin="0"') && known.includes('aria-valuemax="200"') && known.includes('aria-valuenow="183.4"'),
    "a reader that does not see the bar hears the meter: its range and what is left");
  pin(!known.includes("credit-warn"), "negative: a figure with nothing to warn of draws no warning");
  const warned = CreditLeft.html(ACCOUNT, spend({ ...SINCE, unpriced: 3, partial: true }));
  const notes = [...warned.matchAll(/data-t="credit-warn">([^<]*)</g)].map((m) => m[1]);
  assert.deepEqual(notes, ["creditUnpriced{&quot;n&quot;:&quot;3&quot;}", "creditPartial"]);
  pin(true, "a figure that is too high says why, one line each: requests with no price, logs that do not reach back");
  pin(CreditLeft.html(ACCOUNT, spend({ ...SINCE, unpriced: 2 })).includes("creditUnpriced") && !CreditLeft.html(ACCOUNT, spend({ ...SINCE, unpriced: 2 })).includes("creditPartial"),
    "negative: the two warnings are told apart");
  const empty = CreditLeft.html(ACCOUNT, spend({ ...SINCE, total: 250 }));
  pin(empty.includes("creditLeft{&quot;left&quot;:&quot;$0&quot;}") && empty.includes("width:0%;background:tone0"),
    "spent through: $0 left, an empty bar in the lowest tone");
  const quoted = CreditLeft.html({ ...ACCOUNT, id: 'a"b' }, spend(SINCE, 'a"b'));
  pin(quoted.includes('data-t-id="a&quot;b"') && !quoted.includes('data-t-id="a"b"'), "the account's id is escaped where it stands in an attribute");
}
for (const why of pass) console.log("  ok  " + why);
console.log(`js credit-left OK: ${pass.length} pins — the credit as typed, the figures against the reading, the line and its warnings`);
'''


def main():
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_credit_left.tmp.mjs"
    probe.write_text(PROBE)
    try:
        harness = ROOT / "scripts" / "_js_harness.mjs"
        result = subprocess.run([node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');", str(probe)], cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "JS_STUBS": "i18n,utils,usage-stats",
                                     "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"},
                                capture_output=True, text=True, timeout=30)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
