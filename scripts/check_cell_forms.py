#!/usr/bin/env python3
"""Guard: a cell server reads a form with `Form` of cells/cell_base.py, and with nothing of its own.

Five cell servers had five copies of a reader of multipart/form-data, and the copies drifted. Two of them took
`rstrip(b"\\r\\n-")` for "the CRLF before the boundary" and cut every trailing LF, CR and hyphen off the data: a recording
whose last byte was one of them lost it, and sinapse's live ears were refused 400 "bad wav" in 1.7 % of their requests
(2026-10-19). The reader that was right was one of the five. Where a part of a form ends is ONE fact; its home is `Form`.

What is checked, by reading the code of every cells/*.py but the base:
  1. no function or method named `_extract_file`, `_boundary`, `_fields` or `_field` — the names the copies had;
  2. no bytes literal made of nothing but CR, LF and hyphens that holds a CRLF (`b"\\r\\n\\r\\n"`, `b"\\r\\n"`, `b"\\r\\n-"`): the
     line endings and the hyphens of a form are the form's reader's, and a cell that writes one is reading a form again.
     (A PNG's signature holds a CRLF too, among other bytes: it is not one.)

scripts/test_guards_fail.py plants each of the two in a copy of the tree and expects this guard red.

Run: python3 scripts/check_cell_forms.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELLS = ROOT / "cells"
BASE = "cell_base.py"
COPIES = {"_extract_file", "_boundary", "_fields", "_field"}
#: CR, LF and the hyphen: what a form's reader strips, splits and looks for.
FORM_BYTES = {13, 10, 45}


def problems_of(path):
    out = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in COPIES:
            out.append(f"{path.name}:{node.lineno}: `{node.name}` — a reader of a form of its own; use cell_base.Form")
        if (isinstance(node, ast.Constant) and isinstance(node.value, bytes)
                and b"\r\n" in node.value and set(node.value) <= FORM_BYTES):
            out.append(f"{path.name}:{node.lineno}: the bytes {node.value!r} — the line endings and hyphens of a form are Form's; "
                       f"a cell that writes them is reading a form again")
    return out


def main():
    files = sorted(p for p in CELLS.glob("*.py") if p.name != BASE)
    if not (CELLS / BASE).is_file() or not any(f.name.endswith("_server.py") for f in files):
        print("check_cell_forms: FAILED — no cells/cell_base.py or no cell server to read: nothing was checked")
        return 1
    problems = [line for path in files for line in problems_of(path)]
    if problems:
        print("check_cell_forms: FAILED —")
        for line in problems:
            print("  " + line)
        return 1
    print(f"check_cell_forms OK: {len(files)} cell files read, none holds a reader of a form of its own")
    return 0


if __name__ == "__main__":
    sys.exit(main())
