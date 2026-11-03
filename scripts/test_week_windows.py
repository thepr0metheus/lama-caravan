#!/usr/bin/env python3
"""Value snapshot: when a model is open — the windows of a schedule, as the board paints and edits them (static/js/week-windows.js).

The program reads the same windows (rust/crates/admin/tests/contract.rs), and both are held to ONE table, contract/week_windows.json, each read as the same open
minutes of the week. Pinned: Monday is 0 and no days is every day; a window is open from `from` and closed at `to`; a window whose `to` is not after its `from` runs
past midnight and belongs to its start day; `from` equal to `to` is a whole day; a window past Sunday midnight goes on at the week's start; windows that touch are one
stretch; a window that does not read opens nothing. The board's own reading back of a painted week (`fromMask`): one way for one week, and the same minutes again.

Run: python3 scripts/test_week_windows.py
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


def w(days, start, end):
    return {"days": days, "from": start, "to": end}


# (windows, open runs of the week, what the pin is for)
CASES = [(row["windows"], row["runs"], row["why"]) for row in Contract.table("week_windows")["cases"]]


def section_js():
    print("двойник в браузере — та же таблица, и как доска пишет окна из закрашенной недели:")
    node = find_node()
    if not node:
        check(False, "node не найден — двойник не проверен")
        return
    canon = [
        ("будни", [w([0, 1, 2, 3, 4], "09:00", "19:00")], [w([0, 1, 2, 3, 4], "09:00", "19:00")]),
        ("ночи", [w([], "19:00", "09:00")], [w([], "19:00", "09:00")]),
        ("сутки субботы", [w([5], "06:00", "06:00")], [w([5], "06:00", "06:00")]),
        ("неделя", [w([], "00:00", "00:00")], [w([], "00:00", "00:00")]),
        ("36 часов", [w([0], "20:00", "00:00"), w([1], "00:00", "00:00"), w([2], "00:00", "08:00")],
         [w([0], "20:00", "00:00"), w([1], "00:00", "00:00"), w([2], "00:00", "08:00")]),
        ("пусто", [], []),
    ]
    probe = (
        'import { pathToFileURL } from "node:url";\n'
        'const { WeekWindows } = await import(pathToFileURL(process.env.JS_FILE).href);\n'
        f"const cases = {json.dumps([c[0] for c in CASES])};\n"
        f"const canon = {json.dumps([c[1] for c in canon])};\n"
        "const runsOf = (mask) => WeekWindows.runs(WeekWindows.fromMask(mask));\n"
        "const week = WeekWindows.mask([{ days: [0, 1, 2, 3, 4], from: '09:00', to: '19:00' }]);\n"
        "WeekWindows.paint(week, 2, 12, false);\n"
        "const half = WeekWindows.mask([{ days: [0], from: '09:30', to: '10:00' }]);\n"
        "const out = {\n"
        "  runs: cases.map((c) => WeekWindows.runs(c)),\n"
        "  canon: canon.map((c) => WeekWindows.fromMask(WeekWindows.mask(c))),\n"
        "  round: cases.map((c) => JSON.stringify(runsOf(WeekWindows.mask(c))) === JSON.stringify(WeekWindows.runs(c))),\n"
        "  painted: WeekWindows.fromMask(week),\n"
        "  shares: [WeekWindows.share(half, 0, 9), WeekWindows.share(half, 0, 10), WeekWindows.share(week, 1, 12), WeekWindows.share(week, 2, 12)],\n"
        "  words: [WeekWindows.minutes('9:05'), WeekWindows.minutes('24:00'), WeekWindows.minutes(''), WeekWindows.hhmm(1439), WeekWindows.hhmm(1440)],\n"
        "};\n"
        "console.log(JSON.stringify(out));\n"
    )
    env = {**os.environ, "JS_FILE": str(ROOT / "static" / "js" / "week-windows.js")}
    run = subprocess.run(node_args(node, "--input-type=module", "-e", probe), capture_output=True, text=True, env=env, timeout=60)
    if run.returncode != 0:
        check(False, f"node вышел с кодом {run.returncode}: {run.stderr.strip()[-300:]}")
        return
    js = json.loads(run.stdout.strip().splitlines()[-1])
    for (windows, runs, why), got in zip(CASES, js["runs"]):
        check(got == runs, f"js: {why}")
    check(len(js["runs"]) == len(CASES), "двойник ответил на каждый случай таблицы")
    for (name, _windows, want), got in zip(canon, js["canon"]):
        check(got == want, f"js fromMask: {name} — неделя пишется одним видом (got {got})")
    check(all(js["round"]), f"js: окна из закрашенной недели открывают те же минуты — для каждого случая таблицы (got {js['round']})")
    check(js["painted"] == [w([0, 1, 3, 4], "09:00", "19:00"), w([2], "09:00", "12:00"), w([2], "13:00", "19:00")],
          f"js: закрыт полдень среды — среда двумя окнами, остальные будни одним (got {js['painted']})")
    check(js["shares"] == [30, 0, 60, 0], f"js: час закрашен целиком, наполовину или пуст — по минутам (got {js['shares']})")
    check(js["words"] == [545, None, None, "23:59", "00:00"], f"js: ЧЧ:ММ читается так же, как на сервере (got {js['words']})")


def main():
    section_js()
    if _fail:
        print(f"\nweek windows FAILED: {len(_fail)}")
        for m in _fail:
            print("  - " + m)
        return 1
    print(f"\nweek windows OK: {len(CASES)} cases, one table with the program")
    return 0


if __name__ == "__main__":
    sys.exit(main())
