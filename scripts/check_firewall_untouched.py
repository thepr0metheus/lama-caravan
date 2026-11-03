#!/usr/bin/env python3
"""Guard: the caravan never runs ufw — the firewall is the operator's.

The controller used to open and close each proxy port itself with `sudo -n ufw allow|delete allow <port>`. That needed a sudoers rule, did nothing at all in a container,
and swallowed a refusal, so a port could stay closed with nothing saying why. Since 1.3.436 the operator opens the proxy range once (`ufw allow 23001:23999/tcp`) and the
caravan only keeps its ports inside it. A ufw call slipping back in would bring all three problems back, quietly — hence this guard.

Walks the code of the controller and its proxy, comments and tests aside, and fails two ways: a string that is the word "ufw" alone (an argument for a program); a string
that reads as a ufw command (`ufw allow …`, `sudo ufw status`). What a scout reads of its own machine's ufw is the scout's. It also fails when it found nothing to walk.

Run: python3 scripts/check_firewall_untouched.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _rust_source import RustSource  # noqa: E402

TREES = ("admin/src", "proxy/src", "plumbing/src", "os/src")
MUST_SEE = ("rust/crates/admin/src/proxies/config.rs", "rust/crates/proxy/src/connection.rs")
COMMAND = re.compile(r"\bufw\s+(allow|deny|reject|limit|delete|insert|prepend|route|status|enable|disable|reload|reset)\b")
ARGUMENT = re.compile(r'"ufw"')


def main():
    seen, problems = set(), []
    for rel, lines in RustSource.files(*TREES):
        seen.add(rel)
        for number, line in enumerate(lines, 1):
            if ARGUMENT.search(line) or COMMAND.search(line):
                problems.append(f"{rel}:{number}: {line.strip()[:100]}")
    problems += [f"{must}: не найден — гвард смотрит не туда" for must in MUST_SEE if must not in seen]
    if problems:
        print("firewall untouched: FAILED — файрвол ведёт оператор (одно правило на диапазон прокси):")
        for problem in problems:
            print("  - " + problem)
        return 1
    print(f"firewall untouched OK: {len(seen)} файлов, ни одного вызова ufw")
    return 0


if __name__ == "__main__":
    sys.exit(main())
