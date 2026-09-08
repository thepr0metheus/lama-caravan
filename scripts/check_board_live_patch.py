#!/usr/bin/env python3
"""The board's live patcher must not retell what the card builder already says.

The board is drawn twice: the builder assembles a client's card, and the
patcher rewrites its live pieces on every poll tick, without touching the
rest. As long as both of them compute the same fact, they drift apart — and
they drift silently.

That's exactly what happened with response age. The builder was taught to
say "never answered" to a client that NEVER answered (it used to print "?s
ago", claiming an answer had happened, just at an unknown time). The patcher
kept its own template — and the fix held for exactly one frame: the very
next tick brought back "?s ago". Snapshots never saw it, because the pins sit
on the builder, and the patcher isn't loaded by them.

The guard fails TWO ways: when a fact gets computed somewhere else again, and
when the sole source stops computing it — then there's nothing left to guard.

Run: python3 scripts/check_board_live_patch.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Fact → (what it looks like in code, its sole source file, the function's name).
#: The COMPUTATION PATTERN is searched for, not words: reading the same fact
#: elsewhere is not forbidden.
SHARED_FACTS = {
    "возраст ответа клиента": (
        re.compile(r"`\$\{[^`]*\}s ago`"),
        "static/js/topology-activity.js",
        "clientAgeText",
    ),
}

#: Files that draw the board: the builder, the patcher, and everything in between.
BOARD_FILES = ("static/js/topology-render.js", "static/js/topology-activity.js",
               "static/js/topology-proxies.js", "static/js/remote-cells.js")


def main():
    problems = []
    for fact, (pattern, source_rel, func) in SHARED_FACTS.items():
        source = ROOT / source_rel
        if not source.exists():
            problems.append(f"{fact}: источник {source_rel} исчез — охранять нечего")
            continue
        text = source.read_text(encoding="utf-8")
        if f"function {func}" not in text:
            problems.append(f"{fact}: в {source_rel} нет функции «{func}» — источник переехал "
                            f"или переименован, и правило больше ничего не проверяет")
            continue
        if not pattern.search(text):
            problems.append(f"{fact}: «{func}» больше не собирает этот факт — либо он собирается "
                            f"теперь где-то ещё, либо проверять нечего")
            continue
        for rel in BOARD_FILES:
            if rel == source_rel:
                continue
            path = ROOT / rel
            if not path.exists():
                continue
            for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    problems.append(f"{rel}:{num}: {fact} собирается второй раз — зови «{func}» "
                                    f"из {source_rel}, иначе починка одного места держится один кадр")
    if problems:
        print("board live patch FAILED:")
        for p in problems:
            print("  - " + p)
        print("\nПатчер и строитель, говорящие один факт порознь, расходятся молча (docs/why.md).")
        return 1
    print(f"board live patch OK: {len(SHARED_FACTS)} общих фактов — каждый собирается в одном месте")
    return 0


if __name__ == "__main__":
    sys.exit(main())
