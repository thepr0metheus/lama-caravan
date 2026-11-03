#!/usr/bin/env python3
"""Every flag the controller can write to llama-server is one the server knows.

llama.cpp took `--mmap`, `--no-mmap` and `--mlock` away for `--load-mode`. A new build was put on the machine and everything went on looking well: a cell with one of them says
"invalid argument" and does not start, and two of thirty did, only nobody had started those two yet (2026-11-03). The flags are read out of the code that writes them and held to contract/llama-server-help.txt, the
`--help` of the build last checked. A new build: write that file again; what it no longer knows goes red here.

`config/extra.rs` is left out: it reads what an operator pasted, the old flags too, and writes fields.

Run: python3 scripts/check_llama_flags.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRITERS = ("rust/crates/admin/src/config/args.rs", "rust/crates/admin/src/config/args/*.rs")
HELP = ROOT / "contract" / "llama-server-help.txt"
FLAG = re.compile(r'"(--[a-z0-9][a-z0-9-]*)"')
KNOWN = re.compile(r"(?<![\w-])(--[a-z0-9][a-z0-9-]*)")


def main():
    if not HELP.is_file():
        print(f"llama flags: FAILED — {HELP.relative_to(ROOT)} is not there")
        return 1
    known = set(KNOWN.findall(HELP.read_text(encoding="utf-8", errors="replace")))
    problems = []
    written = 0
    for pattern in WRITERS:
        for path in sorted(ROOT.glob(pattern)):
            code = path.read_text(encoding="utf-8").split("#[cfg(test)]")[0]
            for number, line in enumerate(code.splitlines(), 1):
                for flag in FLAG.findall(line):
                    written += 1
                    if flag not in known:
                        problems.append(f"{path.relative_to(ROOT)}:{number}: {flag}")
    if not written:
        problems.append("no flag was found in the code that writes them: the guard looks past it")
    if problems:
        print("llama flags: FAILED — the controller writes what the checked llama-server does not know: a cell with it does not start")
        for problem in problems:
            print("  - " + problem)
        return 1
    print(f"llama flags OK: {written} written, all known to the build of {HELP.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
