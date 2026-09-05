#!/usr/bin/env python3
"""The launch line of every real cell, unchanged.

This is the safety net for the rewrite. Twenty-five cells, eight runners, every
flag an operator actually arrived at — regenerated from their saved configs and
compared with the picture taken before the first line was moved.

It is deliberately the dumbest possible test: same input, same bytes out. That
is the only property worth having here. A rewrite is allowed to restructure
anything it likes as long as this stays green; when it goes red, either
something was lost, or a change was intended and the snapshot is updated in a
commit of its own that says which cells changed and why.

Run `scripts/capture_golden.py` to take a fresh picture.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests/golden"
FIXTURES = GOLDEN / "cells"
COMMANDS = GOLDEN / "commands"

# The same pinning the capture used. Without it every path differs and the test
# says everything changed, which is the same as saying nothing.
HOME = "/home/caravan"
for _k, _v in (("LLAMA_HOME", f"{HOME}/llama.cpp"),
               ("LLAMA_MODELS_DIR", f"{HOME}/llama.cpp/models"),
               ("HOME", HOME)):
    os.environ[_k] = _v

sys.path.insert(0, str(ROOT))

from caravan.admin.launch import render_server_cell_script   # noqa: E402
from caravan.common.errors import AppError                   # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(detail)


def first_difference(want, got):
    """The line where they part, with a little either side."""
    w, g = want.splitlines(), got.splitlines()
    for i in range(max(len(w), len(g))):
        a = w[i] if i < len(w) else "<нет строки>"
        b = g[i] if i < len(g) else "<нет строки>"
        if a != b:
            out = [f"       строка {i + 1}:", f"       было:  {a[:160]}", f"       стало: {b[:160]}"]
            return "\n".join(out)
    return "       (различий по строкам нет — расходятся пробелы или конец файла)"


def main():
    if not FIXTURES.is_dir() or not any(FIXTURES.glob("*.json")):
        print("golden: FAILED — снимков нет. Снимите: python3 scripts/capture_golden.py",
              file=sys.stderr)
        return 1

    fixtures = sorted(FIXTURES.glob("*.json"))
    missing = [f.stem for f in fixtures if not (COMMANDS / f"{f.stem}.sh").is_file()]
    if missing:
        print(f"golden: FAILED — есть конфиг, нет эталона команды: {missing}", file=sys.stderr)
        return 1

    for fixture in fixtures:
        port = fixture.stem
        config = json.loads(fixture.read_text(encoding="utf-8"))
        want = (COMMANDS / f"{port}.sh").read_text(encoding="utf-8")
        try:
            got = render_server_cell_script(config)
        except AppError as exc:
            got = f"__REFUSED__ {exc}"
        except Exception as exc:  # noqa: BLE001
            # A crash is not a refusal: the old code answered, so answering with
            # a traceback is itself a lost behaviour.
            check(f"cell {port} ({config.get('RUNNER') or 'llama-server'})", False,
                  f"       упало: {type(exc).__name__}: {exc}")
            continue
        check(f"cell {port} ({config.get('RUNNER') or 'llama-server'})",
              got == want, first_difference(want, got))

    shapes_file = GOLDEN / "api-shapes.json"
    if shapes_file.is_file():
        shapes = json.loads(shapes_file.read_text(encoding="utf-8"))
        # Not re-fetched here: the live service is not available in CI. The file
        # is the contract the rewrite must keep, and scripts/capture_golden.py
        # is what compares it against a running controller.
        check("api shapes recorded", all("__unavailable__" not in v for v in shapes.values()),
              "       часть форм не снялась — переснимите с работающего контроллера")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("\nЕсли изменение НАМЕРЕННОЕ: python3 scripts/capture_golden.py --local\n"
              "и отдельный коммит, объясняющий, какие ячейки изменились и почему.",
              file=sys.stderr)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
