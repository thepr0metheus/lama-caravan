#!/usr/bin/env python3
"""Nothing the public mirror would refuse: the home network's names stay private.

scripts/sync-public.sh copies the tree to the public repository and stops on the
first forbidden string — a machine's name or address, the home network's domain,
a private project. It runs only when the mirror is synced, so a leak waited for
it: on 2026-10-11 the scan would have stopped on 70 lines of docs, code, tests
and 20 translations written since the last sync, fleet names in fixtures among
them — which the project's rules forbid. This guard runs the same scan on every
build.

The patterns are read from the sync script, the one place they live: a second
copy here would drift from it, and the guard would pass what the sync refuses.
The files are the ones the sync would carry: tracked and untracked-not-ignored
files minus the sync's exclusions, or — in a copy of the tree without git — every
file there. Binary files are skipped, as `grep -I` skips them.

Run: python3 scripts/check_public_leaks.py
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNC = ROOT / "scripts" / "sync-public.sh"
SKIP_DIRS = {".git", "__pycache__", "node_modules", "var", "logs"}


class MirrorRules:
    """The sync script's patterns: what stays out of the mirror, and what may not appear in it."""

    NAMES = ("EXCLUDE_RE", "LEAK_RE", "FLEET_RE", "FLEET_ALLOW")

    def __init__(self, text):
        found = {}
        for line in text.splitlines():
            m = re.match(r"^([A-Z_]+)='(.*)'\s*$", line)
            if m and m.group(1) in self.NAMES:
                found[m.group(1)] = m.group(2)
        missing = [name for name in self.NAMES if name not in found]
        if missing:
            raise SystemExit(f"check_public_leaks: {SYNC.relative_to(ROOT)} no longer sets {', '.join(missing)}")
        self.exclude = re.compile(found["EXCLUDE_RE"])
        self.leak = re.compile(found["LEAK_RE"])
        self.fleet = re.compile(found["FLEET_RE"])
        self.allow = re.compile(found["FLEET_ALLOW"])

    def hits(self, line):
        return bool(self.leak.search(line)) or (bool(self.fleet.search(line)) and not self.allow.search(line))


def public_files(rules):
    """The files the sync would carry, relative to the root, the sync script itself left out."""
    if (ROOT / ".git").exists():
        out = subprocess.run(["git", "ls-files", "-c", "-o", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.splitlines()
    else:
        out = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
               if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)]
    return sorted(f for f in out if f.strip() and not rules.exclude.search(f) and f != "scripts/sync-public.sh")


def main():
    rules = MirrorRules(SYNC.read_text(encoding="utf-8"))
    files = public_files(rules)
    found = []
    for rel in files:
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found += [f"{rel}:{n}: {line.strip()[:110]}" for n, line in enumerate(text.splitlines(), 1) if rules.hits(line)]
    if found:
        print(f"check_public_leaks: FAILED — {len(found)} line(s) the public mirror would refuse "
              "(scripts/sync-public.sh LEAK_RE / FLEET_RE):")
        for hit in found[:40]:
            print("  - " + hit)
        print("  a machine's name or address, the home domain or a private project: write a neutral one "
              "(10.0.x.y, example.org; in a fixture, a name with the same first letter: sierra, foxtrot, alpha)")
        return 1
    print(f"check_public_leaks OK: {len(files)} files the mirror would carry, none with a private name")
    return 0


if __name__ == "__main__":
    sys.exit(main())
