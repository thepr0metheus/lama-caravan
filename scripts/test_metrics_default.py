#!/usr/bin/env python3
"""Value snapshot: a llama.cpp cell starts with its metrics unless it says off, as the form shows it (static/js/cell-plan.js, constants.js; 1.3.658).

The owner, 2026-10-26: Hermes answered, and its window said no request was measured — "start it with metrics by default, always". llama.cpp keeps no metrics without
--metrics, and the caravan reads a cell's speed, queue and context use there. The program starts the cell by one table of cases, contract/metrics_default.json
(rust/crates/admin/tests/contract.rs), and the form reads the same table the same way (CellFields.toggle): the box shows what the cell will start with.

Run: python3 scripts/test_metrics_default.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _contract import Contract  # noqa: E402
from _node import find_node, node_search_paths, probe_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


#: What a box says → whether the cell starts with its metrics. None: the key is not in the config at all.
CASES = [(row["said"], row["on"]) for row in Contract.table("metrics_default")["cases"]]

PROBE = r'''
import "./_js_globals.mjs";
const P = await import("../static/js/cell-plan.js");
const cases = JSON.parse(process.env.CASES);
console.log(JSON.stringify(cases.map((v) => P.CellFields.toggle("ENABLE_METRICS", v === null ? {} : { ENABLE_METRICS: v }))));
'''


def form_reads():
    node = find_node()
    if node is None:
        print("  ..  форма: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return None
    probe = ROOT / "scripts" / ".probe_metrics_default.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
               "TZ": "UTC", "CASES": json.dumps([v for v, _ in CASES])}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT,
                              env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print(proc.stderr.strip()[:2000])
        return "failed"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def main():
    print("форма читает флажок тем же правилом, что сборщик команды:")
    want = [on for _, on in CASES]
    form = form_reads()
    if form is not None:
        check(form == want, f"не сказанный — включён, сказанный «выкл» — нет: флажок показывает то, с чем ячейка запустится (got {form})")
    print()
    if _fail:
        print(f"metrics default FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("metrics default OK: the form shows what a llama.cpp cell starts with")
    return 0


if __name__ == "__main__":
    sys.exit(main())
