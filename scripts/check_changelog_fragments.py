#!/usr/bin/env python3
"""Guard: the changelog's entries before a release live in changelog.d/, one file per merge request, not at the top of CHANGELOG.md.

Every merge request used to write at the top of `## Unreleased`, so each merge made every other open merge request conflict on the same
lines (eleven of them on 2026-11-07). The rule and the release that folds the files in: scripts/changelog.py, changelog.d/README.md.

Fails when: `## Unreleased` in CHANGELOG.md says anything but the pointer to changelog.d/, or is not there once; changelog.d/README.md is
missing; a file of changelog.d/ is not named by its day and words, is empty, does not start as a list entry, or carries a heading.
Negative self-test: scripts/test_guards_fail.py. The rules on made-up trees: scripts/test_changelog.py.

Run: python3 scripts/check_changelog_fragments.py
"""
import sys

from changelog import Changelog


def main():
    changelog = Changelog()
    problems = changelog.problems()
    if problems:
        print("changelog fragments: FAILED")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"changelog fragments: ok — {len(changelog.entries())} entries wait in {Changelog.FOLDER}/ for a release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
