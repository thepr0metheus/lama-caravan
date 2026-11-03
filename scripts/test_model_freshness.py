#!/usr/bin/env python3
"""Value snapshot: our copy of a file against the one on Hugging Face, as the browser decides it (static/js/model-freshness.js).

The program decides the same (rust/crates/admin/tests/contract.rs), and both are held to ONE table, contract/model_freshness.json: diverging twins would be exactly the
defect this rule was split into its own file to prevent.

What's pinned. Five states by value: no file; sizes differ (content is definitely different); same size, but the HF commit is newer (possibly re-uploaded); checked and
matches; nothing to compare against. The last one is a SEPARATE state: turning not-knowing into "matches" was exactly the original defect that put a ✓ over a file we
didn't have. The numbers are from a production host on 2026-09-07. A file's date is noon by UTC: its day stands in any zone a test runs in.

Run: python3 scripts/test_model_freshness.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _contract import Contract  # noqa: E402
from _node import find_node, node_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


# (name, local, remote, expected state, what the pin is for)
CASES = [(row["name"], row["local"], row["remote"], row["state"], row["why"]) for row in Contract.table("model_freshness")["cases"]]


def main():
    print("двойник в браузере:")
    node = find_node()
    if not node:
        check(False, "node не найден — двойник не проверен")
    else:
        probe = ROOT / "scripts" / ".probe_freshness.tmp.mjs"
        cases = [[n, l, r] for n, l, r, _w, _m in CASES]
        probe.write_text(
            'import { pathToFileURL } from "node:url";\n'
            'const m = await import(pathToFileURL(process.env.JS_FILE).href);\n'
            f"const cases = {json.dumps(cases)};\n"
            'const out = {};\n'
            'for (const [n, l, r] of cases) out[n] = m.compareLocalFile(l, r).state;\n'
            'out.__marks = ["size", "date", "unknown", "same", "missing"].map(s => m.freshMark({ state: s }));\n'
            'out.__summary = m.repoSummary(["size", "date", "same", "unknown", "missing", "size"]);\n'
            'out.__detail = m.compareLocalFile(cases[0][1], cases[0][2]).detail;\n'
            'console.log(JSON.stringify(out));\n'
        )
        try:
            env = {**os.environ, "JS_FILE": str(ROOT / "static" / "js" / "model-freshness.js"),
                   "TZ": os.environ.get("TZ", "")}
            run = subprocess.run(node_args(node, probe), capture_output=True, text=True,
                                 env=env, cwd=ROOT, timeout=60)
        finally:
            probe.unlink(missing_ok=True)
        if run.returncode != 0:
            print(run.stdout, run.stderr)
            check(False, f"node вышел с кодом {run.returncode}")
        else:
            js = json.loads(run.stdout.strip().splitlines()[-1])
            for name, _l, _r, want, msg in CASES:
                check(js.get(name) == want, f"js: {msg} (got {js.get(name)!r})")
            check(js["__marks"] == ["⇪", "⇪", "?", "✓", "✓"],
                  f"значки: разошлось — ⇪, не знаем — «?», сходится — ✓ (got {js['__marks']})")
            check(js["__summary"] == {"differs": 3, "bySize": 2, "byDate": 1,
                                      "unknown": 1, "same": 1, "missing": 1},
                  f"js: свод считает так же (got {js['__summary']})")
            check(js["__detail"] == {"localSize": 17923394624, "remoteSize": 17559178144,
                                     "localDate": "2026-08-15", "remoteDate": "2026-08-19"},
                  f"js: подробности те же значениями (got {js['__detail']})")

    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        sys.exit(1)
    print("model-freshness snapshots hold")


if __name__ == "__main__":
    main()
