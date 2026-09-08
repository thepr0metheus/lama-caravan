#!/usr/bin/env python3
"""Value snapshot: our copy of a file against the one on Hugging Face.

The rule lives twice — caravan/common/model_freshness.py and
static/js/model-freshness.js — because both the server and the browser
decide by it. Both copies are run here against ONE table of cases: diverging
twins would be exactly the defect this rule was split into its own file to
prevent.

What's pinned. Five states by value: no file; sizes differ (content is
definitely different); same size, but the HF commit is newer (possibly
re-uploaded); checked and matches; nothing to compare against. The last one
is a SEPARATE state: turning not-knowing into "matches" was exactly the
original defect that put a ✓ over a file we didn't have.

The numbers are from a production host on 2026-09-07: Qwen3.8-27B-UD-Q4_K_XL
is 17,923,394,624 B for us, dated 08-15, and 17,559,178,144 B on HF, dated 08-19.

Run: python3 scripts/test_model_freshness.py
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _node import find_node  # noqa: E402
from caravan.common.model_freshness import (  # noqa: E402
    DIFFERS, compare_file, repo_summary,
)

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def epoch(day):
    """Noon of the given day — the hour must not affect the output."""
    return int(datetime.strptime(day + " 12:00", "%Y-%m-%d %H:%M").timestamp())


# (name, local, remote, expected state, what the pin is for)
CASES = [
    ("qwen_q4_size",
     {"size": 17923394624, "mtime": epoch("2026-08-15")},
     {"size": 17559178144, "date": "2026-08-19T09:12:31.000Z"},
     "size",
     "боевой случай: 364 МБ разницы — перевыпущенное квантование, а не докачка"),
    ("qwen_q5_size",
     {"size": 20218178624, "mtime": epoch("2026-08-15")},
     {"size": 20876938144, "date": "2026-08-19T09:12:31.000Z"},
     "size",
     "…и в другую сторону: на HF файл БОЛЬШЕ нашего — тоже другая сборка"),
    ("gemma_metadata_size",
     {"size": 19598488192, "mtime": epoch("2026-07-22")},
     {"size": 19598489952, "date": "2026-07-27T00:00:00.000Z"},
     "size",
     "1 760 байт разницы — тоже size: правило не гадает, метаданные это или веса"),
    ("ornith_newer_commit",
     {"size": 21165000000, "mtime": epoch("2026-06-28")},
     {"size": 21165000000, "date": "2026-07-18T00:00:00.000Z"},
     "date",
     "размер тот же, коммит новее — «возможно перезалито», а не «другая сборка»"),
    ("same_day_commit",
     {"size": 100, "mtime": epoch("2026-08-15")},
     {"size": 100, "date": "2026-08-15T23:59:00.000Z"},
     "same",
     "коммит в тот же день не считается новее: час загрузки и час коммита в разных зонах"),
    ("older_commit",
     {"size": 100, "mtime": epoch("2026-08-15")},
     {"size": 100, "date": "2024-12-06T00:00:00.000Z"},
     "same",
     "negative: коммит старше нашего файла — сходится, и это утверждение"),
    ("missing_local",
     None,
     {"size": 100, "date": "2026-08-19T00:00:00.000Z"},
     "missing",
     "файла нет локально"),
    ("no_remote_size",
     {"size": 100, "mtime": epoch("2026-08-15")},
     {"size": 0, "date": "2026-08-19T00:00:00.000Z"},
     "unknown",
     "HF не назвал размер → «не знаем», а НЕ «совпадает»"),
    ("no_local_size",
     {"size": 0, "mtime": epoch("2026-08-15")},
     {"size": 100, "date": "2026-08-19T00:00:00.000Z"},
     "unknown",
     "нечитаемый локальный файл → тоже «не знаем»"),
    ("no_dates",
     {"size": 100, "mtime": 0},
     {"size": 100, "date": ""},
     "unknown",
     "размеры равны, но дат нет: равенство размера ещё не равенство файла"),
    ("no_remote_date",
     {"size": 100, "mtime": epoch("2026-08-15")},
     {"size": 100, "date": ""},
     "unknown",
     "дата только с одной стороны — сравнивать не с чем"),
]


def main():
    print("правило на сервере:")
    py_states = {}
    for name, local, remote, want, msg in CASES:
        state, detail = compare_file(local, remote)
        py_states[name] = state
        check(state == want, f"{msg} (got {state!r})")
        if state in ("size", "date", "same"):
            check(detail["localSize"] and detail["remoteSize"],
                  f"{name}: подробности несут ОБА размера — подсказка покажет обе пары")

    d = compare_file({"size": 17923394624, "mtime": epoch("2026-08-15")},
                     {"size": 17559178144, "date": "2026-08-19T09:12:31.000Z"})[1]
    check(d == {"localSize": 17923394624, "remoteSize": 17559178144,
                "localDate": "2026-08-15", "remoteDate": "2026-08-19"},
          f"подробности боевого случая — значениями (got {d})")
    check(compare_file(None, {"size": 1, "date": "2026-01-01"})[1] == {},
          "у отсутствующего файла подробностей нет — сравнивать было нечего")
    check(compare_file("не словарь", {"size": 1, "date": "x"})[0] == "missing",
          "не-словарь на месте локального — «нет файла», а не падение")

    print("свод по репозиторию:")
    summary = repo_summary(["size", "date", "same", "unknown", "missing", "size"])
    check(summary == {"differs": 3, "bySize": 2, "byDate": 1,
                      "unknown": 1, "same": 1, "missing": 1},
          f"считает каждое состояние отдельно (got {summary})")
    check(repo_summary([])["differs"] == 0 and repo_summary([])["unknown"] == 0,
          "пустой свод — нули, а не «всё сходится»")
    check(tuple(DIFFERS) == ("size", "date"),
          "разошедшимися считаются ровно два состояния")

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
            run = subprocess.run([node, str(probe)], capture_output=True, text=True,
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
            diverged = [n for n in py_states if js.get(n) != py_states[n]]
            check(not diverged,
                  f"обе копии правила отвечают ОДИНАКОВО на всей таблице (разошлись: {diverged})")
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
