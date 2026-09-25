#!/usr/bin/env python3
"""The two builders of a cell card must describe the same thing.

topology_server() assembles a cell card in two places: one for cells that are
LIVE (a process is answering) and one for slots that are not. Same object, two
dicts, ~180 lines apart, 36 of 40 keys in common — and each written by hand.

They drifted, and the drift was invisible. `savedCommand` was written in the
slot branch only, so every RUNNING cell and every client cell reached the board
without it; the cell modal reads the command from that key and told the operator
"not saved yet" about a cell that had been serving traffic for hours. Nothing was
red: the key was simply absent, and absent renders as "nothing saved".

So the two key sets are compared here, and a difference has to be declared with a
reason. The point is not that they must be identical — three fields genuinely
only exist for a live process, one only for a stored slot — but that every one
of those is a decision somebody made, rather than a line somebody forgot. (Since
step 6.9 the controller runs no cell of its own, and its single-server card and
the fields only its cells had are gone: two builders, not three.)

This is a KEY check, deliberately. Values differ per cell and per moment; what
must not differ is what a card is made of.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "caravan/admin/topology.py"

#: Keys one branch has and the other does not, each with the reason it is not an
#: oversight. Anything outside this list is a drift.
DECLARED = {
    # Only a live process has these — they are measured from something running.
    "ctxUsed": "live: the context in use is measured from the running process",
    "modelReady": "live: whether the engine is answering right now",
    "uptimeSec": "live: how long the process has been running",
    "launchDiskNewer": "live: a file the process holds changed on disk after it started — a stopped cell holds none",
    # Only a stored slot has this — read from the record's model on disk, and a
    # live cell's card has the real figure from GPU process memory instead.
    "modelSizeBytes": "slot: the model file's size, from disk",
}


def card_keys(tree):
    """Key sets of every llama_servers.append({...}) in the module."""
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "append"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "llama_servers"
                and node.args and isinstance(node.args[0], ast.Dict)):
            keys = {k.value for k in node.args[0].keys if isinstance(k, ast.Constant)}
            out.append((node.lineno, keys))
    return out


def main():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    cards = card_keys(tree)
    if len(cards) != 2:
        print(f"cell card keys: FAILED — ожидалось два сборщика карточки, найдено {len(cards)}",
              file=sys.stderr)
        print("  Проверка перестала находить то, что проверяла.", file=sys.stderr)
        return 1

    # The live cell a scout reports, then a stored slot that is not live.
    (line_live, live), (line_slot, slot) = cards
    errors = []
    for key in sorted(live - slot):
        if key not in DECLARED:
            errors.append(f"{SOURCE.name}:{line_live}: `{key}` есть у живой ячейки и нет у "
                          f"слота — либо объявите причину, либо это потеря")
    for key in sorted(slot - live):
        if key not in DECLARED:
            errors.append(f"{SOURCE.name}:{line_slot}: `{key}` есть у слота и нет у живой "
                          f"ячейки — либо объявите причину, либо это потеря")
    # A declared exception that no longer exists is a stale claim.
    for key in sorted(DECLARED):
        if key in (live & slot) or key not in (live | slot):
            errors.append(f"объявлено исключение `{key}`, но оно больше не различает ветки "
                          f"— уберите его из DECLARED")

    if errors:
        print("cell card keys: FAILED", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"cell card keys OK: обе ветки дают {len(live & slot)} общих ключей, "
          f"{len(DECLARED)} различий объявлены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
