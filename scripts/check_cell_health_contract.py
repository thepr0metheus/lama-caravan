#!/usr/bin/env python3
"""The three lists of /health field names must be one list.

They were three, kept by hand, and nothing compared them: what a cell server
emits, what telemetry copies out of the reply, and what the board reads back.
Drift cost nothing at the time and surfaced later as a panel that quietly knew
less than the cell had told it —

  - `targetLang` was emitted and never copied, so the language chip's live value
    never arrived. It looked right because a config fallback gave the same
    answer, which is what made the failure invisible.
  - Cells report `langs`; the copier looked for `languages`.

Now caravan/admin/cell_health.py holds the names and both sides read them from
there. This checks the third side — the cell servers — and the one thing a
static check can be sure of: that each server MENTIONS every required key in
the payload it builds. It cannot prove the value is right; it can prove nobody
forgot the field, which is how all three of these started.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caravan.admin.cell_health import CARRIED, OPTIONAL, REQUIRED  # noqa: E402

CELLS = ROOT / "cells"
TELEMETRY = ROOT / "caravan/admin/telemetry.py"
TOPOLOGY = ROOT / "caravan/admin/topology.py"


def dict_literal_keys(path):
    """Every string key appearing in a dict literal in this module."""
    import ast
    found = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    found.add(k.value)
        # `self._send(200, {...})` covered by the above; some servers build the
        # payload with keyword arguments to json.dumps(dict(...)).
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "dict":
            for kw in node.keywords:
                if kw.arg:
                    found.add(kw.arg)
    return found


def inherits_cell_server(path):
    """True when the module defines a class deriving from CellServer."""
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if getattr(base, "id", "") == "CellServer" or getattr(base, "attr", "") == "CellServer":
                    return True
    return False


def defines(path, member):
    """True when the module assigns or defines `member` at class level."""
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == member:
                    return True
                if isinstance(item, ast.Assign):
                    for t in item.targets:
                        if getattr(t, "id", "") == member:
                            return True
                if isinstance(item, ast.AnnAssign) and getattr(item.target, "id", "") == member:
                    return True
    return False


def main():
    errors = []

    servers = sorted(CELLS.glob("*_server.py"))
    if not servers:
        print("cell health contract: FAILED — no cell servers found", file=sys.stderr)
        return 1

    # The base builds the required fields for every cell that inherits it, so a
    # subclass is checked for what the base ASKS OF IT instead. This is not a
    # weaker rule: a server writing the payload by hand can still forget a key,
    # and a subclass that declared no engine would produce a payload with an
    # empty one — which the board reads as a cell that did not say.
    base_keys = dict_literal_keys(CELLS / "cell_base.py") if (CELLS / "cell_base.py").is_file() else set()
    for key in REQUIRED:
        if base_keys and key not in base_keys:
            errors.append(f'cell_base.py never builds "{key}" — every cell that inherits it '
                          f'would be missing the field')

    for path in servers:
        if path.name == "cell_base.py":
            continue
        # Keys of dict LITERALS, via the syntax tree — not a text search. The
        # first version of this grepped the file and passed while the field was
        # deleted, because every one of these servers documents its own payload
        # in its docstring: the check was reading the promise instead of the
        # code. A guard that cannot fail is worse than no guard.
        keys = dict_literal_keys(path)
        if inherits_cell_server(path):
            for member in ("engine", "model_name", "kinds"):
                if not defines(path, member):
                    errors.append(
                        f"{path.name} subclasses CellServer but never defines {member}. "
                        f"The base builds /health from these:\n"
                        f"        a cell that does not say its engine cannot be found by what it does.")
            continue
        for key in REQUIRED:
            if key not in keys:
                errors.append(
                    f'{path.name} never builds "{key}". Every cell must report it:\n'
                    f'        status/engine/model/source are how the board tells one running\n'
                    f'        cell from another and whether it runs the code we ship.')

    # The copier must not keep a list of its own again.
    tele = TELEMETRY.read_text(encoding="utf-8")
    if "carry(" not in tele:
        errors.append("telemetry.py no longer routes the reply through cell_health.carry() — "
                      "a second list of names has come back")
    if re.search(r'for k in \("model", "engine"', tele):
        errors.append("telemetry.py has a hand-written key list again")

    # Anything the board reads out of a cell's live reply has to be carried, or
    # it silently arrives empty and renders as though the cell said nothing.
    topo = TOPOLOGY.read_text(encoding="utf-8")
    for key in re.findall(r'\(health or \{\}\)\.get\("([a-zA-Z_]+)"\)', topo):
        if key not in CARRIED and key != "meta":
            errors.append(
                f'topology.py reads "{key}" from a cell\'s reply, but the contract does not\n'
                f'        carry it — it will always be empty. Add it to OPTIONAL in\n'
                f'        caravan/admin/cell_health.py, or stop reading it.')

    if errors:
        print("cell health contract: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"cell health contract OK: {len(servers)} servers report "
          f"{len(REQUIRED)} required fields; {len(OPTIONAL)} optional fields carried")
    return 0


if __name__ == "__main__":
    sys.exit(main())
