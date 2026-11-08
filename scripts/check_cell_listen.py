#!/usr/bin/env python3
"""Guard: every cell listens on its machine's loopback, and the programs and the cells' own files say the same address.

Step 7 of the owner's plan (Papyrus caravan-scout-port-lease, 2026-11-08): a machine shows the network one port of the caravan, its
scout's. A client reaches a model through the scout's entry, the controller reaches a cell through the scout's door, and the scout
dials the cell on 127.0.0.1. Until that day every cell bound every address and answered anyone the firewall let in: the owner's ufw
rule was all that kept the network out of servers with no password, and the rule was to go once no cell needed it. A cell that
binds a wildcard again is open to the whole network the day the rule is gone, and nobody would see it.

What is checked:
  1. rust/crates/rules/src/cell_door.rs says LISTEN = "127.0.0.1", and LISTEN of cells/cell_base.py is the same address;
  2. no file of cells/ names a wildcard address (0.0.0.0, ::), every `--host` there is followed by 127.0.0.1, and InferSSD's
     LLAMA_SERVER_HOST is set to it, not defaulted to something the environment may say otherwise;
  3. a Python cell server is bound to `(LISTEN, ...)`, never to an address of its own;
  4. the command builders — the controller's (config/args.rs, domain/runner/*.rs) and the scout's starts — write no wildcard.

scripts/test_guards_fail.py plants a wildcard in each place and expects this guard red.

Run: python3 scripts/check_cell_listen.py
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CELLS = ROOT / "cells"
RULE = ROOT / "rust/crates/rules/src/cell_door.rs"
LOOPBACK = "127.0.0.1"
#: The builders of a cell's command: none of them may write a wildcard address.
BUILDERS = ("rust/crates/admin/src/config/args.rs", "rust/crates/admin/src/config/args", "rust/crates/admin/src/domain/runner",
            "rust/crates/scout/src/starts")
WILDCARD = re.compile(r"0\.0\.0\.0|--host[ =]+\[?::\]?(\s|$)")
HOST_WORD = re.compile(r"""--host["']?(?:,\s*|\s+|=)["']?([^\s"',)]+)""")


def rule_problems():
    said = re.search(r'pub const LISTEN: &\'static str = "([^"]+)";', RULE.read_text(encoding="utf-8")) if RULE.is_file() else None
    if not said:
        return [f"{RULE.relative_to(ROOT)}: no `pub const LISTEN` — nothing says where a cell listens"]
    out = [] if said.group(1) == LOOPBACK else [f"{RULE.relative_to(ROOT)}: LISTEN is {said.group(1)!r}, not the loopback {LOOPBACK}"]
    base = CELLS / "cell_base.py"
    kept = re.search(r'^LISTEN = "([^"]+)"', base.read_text(encoding="utf-8"), re.M) if base.is_file() else None
    if not kept:
        out.append("cells/cell_base.py: no `LISTEN = \"...\"` — the Python cells have no address to bind")
    elif kept.group(1) != said.group(1):
        out.append(f"cells/cell_base.py: LISTEN is {kept.group(1)!r}, the programs say {said.group(1)!r}: one address, said twice apart")
    return out


def text_problems(path, shown, words_too):
    """A wildcard in any file; in a cell's own file, `--host` and LLAMA_SERVER_HOST followed by anything but the loopback. A
    builder says the address by its name (`CellDoor::LISTEN`), so only a wildcard is read there."""
    out = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for number, line in enumerate(text.splitlines(), 1):
        if WILDCARD.search(line):
            out.append(f"{shown}:{number}: a wildcard address — a cell listens on its machine's loopback ({LOOPBACK}): {line.strip()[:120]}")
        if not words_too:
            continue
        for host in HOST_WORD.findall(line):
            if host != LOOPBACK and not host.startswith(("$", "{")):
                out.append(f"{shown}:{number}: --host {host} — a cell listens on {LOOPBACK}: {line.strip()[:120]}")
        if "LLAMA_SERVER_HOST=" in line and not re.search(rf"LLAMA_SERVER_HOST={re.escape(LOOPBACK)}(\s|$)", line):
            out.append(f"{shown}:{number}: LLAMA_SERVER_HOST is not set to {LOOPBACK} outright: {line.strip()[:120]}")
    return out


def bind_problems(path, shown):
    """A server's address in a Python cell: the tuple handed to a `...Server(` is `(LISTEN, ...)`."""
    out = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args or not isinstance(node.args[0], ast.Tuple):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
        if not name.endswith("Server") or not node.args[0].elts:
            continue
        first = node.args[0].elts[0]
        if not (isinstance(first, ast.Name) and first.id == "LISTEN"):
            out.append(f"{shown}:{node.lineno}: `{name}(({ast.unparse(first)}, ...))` — a cell server binds LISTEN of cell_base.py")
    return out


def builder_files():
    for place in BUILDERS:
        path = ROOT / place
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from sorted(path.rglob("*.rs"))


def main():
    cell_files = sorted(path for path in CELLS.iterdir() if path.is_file() and path.suffix in (".py", ".sh"))
    builders = list(builder_files())
    if not cell_files or not builders:
        print("check_cell_listen: FAILED — no cells/ or no command builder to read: nothing was checked")
        return 1
    problems = rule_problems()
    for path in cell_files + builders:
        shown = str(path.relative_to(ROOT))
        problems += text_problems(path, shown, words_too=path in cell_files)
        if path.suffix == ".py":
            problems += bind_problems(path, shown)
    if problems:
        print("check_cell_listen: FAILED —")
        for line in problems:
            print("  " + line)
        return 1
    print(f"check_cell_listen OK: {len(cell_files)} cell files and {len(builders)} builders read, every cell listens on {LOOPBACK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
