#!/usr/bin/env python3
"""`grep -q` at the end of a pipe, in a shell script under `set -o pipefail`: it says "not there" of what is there.

`grep -q` leaves at its first match and closes the pipe. The command before it dies of that with SIGPIPE, and pipefail takes that for the
pipe's answer. So the longer the output, the likelier it is: `lspci | grep -qi nvidia` told a machine with two cards that it had none, and
it got no llama.cpp and no path to it in its config (2026-11-02, the first new install from the board). `grep ... >/dev/null` reads to the
end. `echo` has written all it has before grep can leave, and stays allowed.

Run: python3 scripts/check_shell_pipes.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ("rust/crates/scout/install.sh", "rust/crates/scout/scripts/*.sh", "scripts/*.sh", "cells/*.sh")
PIPE_TO_QUIET_GREP = re.compile(r"\|\s*grep\s+-[A-Za-z]*q")
ECHOED = re.compile(r"\becho\b[^|]*\|\s*grep\s+-[A-Za-z]*q")


def main():
    problems = []
    checked = 0
    for pattern in SCRIPTS:
        for path in sorted(ROOT.glob(pattern)):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "pipefail" not in text:
                continue
            checked += 1
            for number, line in enumerate(text.splitlines(), 1):
                if PIPE_TO_QUIET_GREP.search(line) and not ECHOED.search(line) and not line.lstrip().startswith("#"):
                    problems.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    if not checked:
        problems.append("no script under pipefail was found: the guard looks past them")
    if problems:
        print("shell pipes: FAILED — grep -q closes the pipe, and pipefail reads that as no match; write grep ... >/dev/null")
        for problem in problems:
            print("  - " + problem)
        return 1
    print(f"shell pipes OK: {checked} scripts under pipefail, no grep -q at the end of a pipe")
    return 0


if __name__ == "__main__":
    sys.exit(main())
