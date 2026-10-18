#!/usr/bin/env python3
"""Actual money.js: dollars as the board says them — one rule for the provider's spend line and the credit left (1.3.585).

The owner, 2026-10-18, held the Routing card of the Anthropic account against the Console of the provider. The card's spend line said
"12 req · 7.2K tok ≈ $0": it rounded every spend to whole dollars, so $0.07 read as nothing spent, while the Console says cents. The credit left
beside it had a rule of its own (cents below a hundred dollars); the two places that said dollars had two rules.

Pinned, by value, each with its negative: whole from a hundred up and cents below; no ".00"; thousands with a comma; none for zero; an amount above
zero that cents cannot show is "<$0.01" and never "$0" (half a cent is the line: below it, the sliver; at it, a cent); junk is $0 and not NaN; a
negative amount is written as it comes (as-is: a spend is never negative, and the line was never asked to say one). And the wiring: the spend line
and the credit left ask this class, and neither keeps a copy of the rule.

The module is loaded for real; it imports nothing.

Run: python3 scripts/test_js_money.py
"""
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

PROBE = r'''
import assert from "node:assert/strict";
const { Money } = await import("../static/js/money.js");
const pass = [];
const eq = (got, want, why) => { assert.deepEqual(got, want, why + ` (got ${JSON.stringify(got)})`); pass.push(why); };
const say = (list) => list.map((v) => Money.dollars(v));

eq(say([0, 0.07, 0.4, 1, 1.22, 12.5, 12, 99.99]), ["$0", "$0.07", "$0.40", "$1", "$1.22", "$12.50", "$12", "$99.99"],
   "below a hundred dollars: cents, and none of \".00\" for a whole sum — $0.07 is $0.07, not $0");
eq(say([100, 100.4, 183.4, 1234.5, 1234567.4, 99.999]), ["$100", "$100", "$183", "$1,235", "$1,234,567", "$100"],
   "from a hundred up: whole dollars, thousands with a comma; 99.999 rounds up to a hundred and is said as one, not as \"$100.00\"");
eq(say([0.004, 0.0049, 0.0001]), ["<$0.01", "<$0.01", "<$0.01"],
   "negative: an amount above zero that cents cannot show is \"<$0.01\" — never \"$0\", which reads as nothing spent");
eq(say([0.005, 0.01]), ["$0.01", "$0.01"], "boundary: half a cent is a cent; the sliver is what is below it");
eq(say([null, undefined, "", "abc", NaN, "0"]), ["$0", "$0", "$0", "$0", "$0", "$0"], "junk is $0, not NaN and not a crash");
eq(say(["7", "12.5", "0.004"]), ["$7", "$12.50", "<$0.01"], "a figure that comes as text is read as a number");
eq(say([-3]), ["$-3"], "as-is: a negative amount is written as it comes — a spend is never negative, and the line was never asked to say one");
for (const why of pass) console.log("  ok  " + why);
console.log(`js money OK: ${pass.length} pins`);
'''


def wiring():
    """The spend line and the credit left ask the class; neither keeps a copy of the rule."""
    problems = []
    stats = (ROOT / "static" / "js" / "usage-stats.js").read_text(encoding="utf-8")
    credit = (ROOT / "static" / "js" / "credit-left.js").read_text(encoding="utf-8")
    if "export function spendCost(s) { return Money.dollars(s?.total); }" not in stats or 'import { Money } from "./money.js";' not in stats:
        problems.append("usage-stats.js: spendCost must be `Money.dollars(s?.total)` with Money imported from money.js")
    if re.search(r"function spendCost[^\n]*Math\.round", stats):
        problems.append("usage-stats.js: spendCost has its own rounding again — the rule is money.js's")
    if "return Money.dollars(amount);" not in credit or 'import { Money } from "./money.js";' not in credit:
        problems.append("credit-left.js: CreditLeft.money must be `Money.dollars(amount)` with Money imported from money.js")
    if 'toLocaleString("en-US")' in credit or "toFixed(2)" in credit:
        problems.append("credit-left.js keeps a copy of the dollar rule — it is money.js's")
    return problems


def main():
    problems = wiring()
    if problems:
        print("js money FAILED (wiring):")
        for line in problems:
            print("  - " + line)
        raise SystemExit(1)
    print("  ok  the spend line and the credit left ask Money; neither keeps a copy of the rule")
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_money.tmp.mjs"
    probe.write_text(PROBE)
    try:
        result = subprocess.run([node, str(probe)], cwd=ROOT, env={**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"},
                                capture_output=True, text=True, timeout=60)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
