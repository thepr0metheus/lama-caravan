#!/usr/bin/env python3
"""Inside a nested class, `self` is not the cell — and nothing says so out loud.

The whisper cell counts download progress by subclassing huggingface's tqdm and
incrementing a counter from `update()`. When the six cell servers moved onto a
base class, the module-global `_state` that the hook closed over became
`self.state` — correct in the method body, and wrong two lines later inside the
nested `class _T(_hf_tqdm)`, where `self` is the progress bar.

Every chunk raised AttributeError. The hook's own `except Exception: pass`
swallowed it, so the cell downloaded three gigabytes while /health reported
`downloadedBytes: 0` and the board drew a progress bar that never moved. A
stalled download and a working one look identical that way.

Nothing could see it: the name exists, the attribute access is legal, the
exception is caught. So this reads the tree instead — a cell attribute reached
through `self` inside a class nested in a method is the bug, every time. The
fix is to bind the value before the class statement.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELLS = ROOT / "cells"

#: Attributes that belong to the CELL. Reaching one through `self` inside a
#: nested class means `self` is something else by then.
CELL_ATTRS = {"state", "log", "port", "args", "source", "model_name", "engine",
              "kinds", "extra_health", "handle", "load"}


def offenders(tree):
    for func in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        for nested in (n for n in ast.walk(func) if isinstance(n, ast.ClassDef)):
            for method in (n for n in ast.walk(nested) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
                for node in ast.walk(method):
                    if (isinstance(node, ast.Attribute)
                            and isinstance(node.value, ast.Name)
                            and node.value.id == "self"
                            and node.attr in CELL_ATTRS):
                        yield node.lineno, nested.name, node.attr


def main():
    errors = []
    files = sorted(CELLS.glob("*.py"))
    if not files:
        print("cell self capture: FAILED — в cells/ нет ни одного .py", file=sys.stderr)
        return 1
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for line, cls, attr in offenders(tree):
            errors.append(
                f"{path.relative_to(ROOT)}:{line}: `self.{attr}` внутри вложенного "
                f"класса {cls} — там `self` уже не ячейка. Свяжите значение до "
                f"`class`, иначе AttributeError уедет в ближайший except и "
                f"замолчит навсегда")
    if errors:
        print("cell self capture: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"cell self capture OK: {len(files)} серверов, ни одного захвата "
          f"чужого self")
    return 0


if __name__ == "__main__":
    sys.exit(main())
