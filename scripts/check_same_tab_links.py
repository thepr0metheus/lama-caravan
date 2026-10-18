#!/usr/bin/env python3
"""Everything of the caravan opens in the tab the operator is in.

The owner, 2026-10-17: "when I click some buttons of the caravan, new screens open in a new tab, not in
this one - remove that". Until then the board's Models and Hugging Face buttons, the machine strip's two
links, Routing card and a machine's page each asked for a tab or a window of their own (the machine's
page was a popup, one a machine), and the tabs piled up. Asked whether the places that had a reason to stay
(another site, a raw answer, the cell's form) should stay, the owner said: "remove them too, it must be in
the same tab". So none stays: a page of the caravan, another site, a raw answer, all go in this tab, and the
way back is the header's "<- Main board" or the browser's Back.

Every `target=`, `.target = ` and `window.open(` in the page is a failure. A place that must ask for another tab
anyway is a line of `ALLOWED` with its reason, and only the owner's word puts one there; a line whose place no
longer asks for a tab, or that asks more often than it says, is a failure too (a list that does not match the
code is a list nobody reads).

Run: python3 scripts/check_same_tab_links.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class NewTabSites:
    """Every place of the page that asks for a tab or a window of its own, and which of them may."""

    #: Where the page's behaviour lives. The dictionaries (static/js/i18n) and the tour texts are words, not behaviour.
    TREES = ("static", "caravan")
    SKIP = ("static/js/i18n/", "static/js/onboarding-strings.js")
    #: An attribute target="…" (a named window too), a property .target = "…", setAttribute("target", …), window.open(.
    ASK = re.compile(
        r"""(?:\starget=["'`]|\.target\s*=\s*["'`]|setAttribute\(\s*["']target["']|\b(?:window|globalThis|self|top)\.open\()""")
    SUFFIXES = (".html", ".js", ".py")
    HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)

    #: (file, a text of the line, how many such lines, why this place may ask for another tab) — none, since the
    #: owner's word of 2026-10-17: everything goes in this tab.
    ALLOWED = ()

    def __init__(self, root: Path = ROOT):
        self.root = root

    def files(self):
        for tree in self.TREES:
            for path in sorted((self.root / tree).rglob("*")):
                rel = path.relative_to(self.root).as_posix()
                if (path.suffix in self.SUFFIXES and path.is_file() and "__pycache__" not in path.parts
                        and not rel.startswith(self.SKIP) and not (tree == "caravan" and path.suffix != ".py")):
                    yield rel, path

    @classmethod
    def code_lines(cls, text: str):
        """(number, line) of the lines that are code: the HTML comments blanked, the lines of a // or /* comment left out."""
        text = cls.HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
        for number, line in enumerate(text.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith(("//", "/*", "*", "#")):
                continue
            yield number, line

    @classmethod
    def asks(cls, text: str, suffix: str):
        """(number, line) of every line of `text` that asks for a tab or a window of its own. A Python file is read for the
        HTML it serves (an attribute), not for open( calls: `threading.Thread(target=…)` is no window."""
        found = []
        for number, line in cls.code_lines(text):
            if not cls.ASK.search(line):
                continue
            if suffix == ".py" and not re.search(r"""\starget=["']""", line):
                continue
            found.append((number, line.strip()))
        return found

    def hits(self):
        """(file, number, line) of every place of the tree that asks for a tab or a window of its own."""
        return [(rel, number, line) for rel, path in self.files()
                for number, line in self.asks(path.read_text(encoding="utf-8"), path.suffix)]

    def problems(self):
        found = self.hits()
        bad = []
        used = {}
        for rel, number, line in found:
            entry = next((e for e in self.ALLOWED if e[0] == rel and e[1] in line), None)
            if entry is None:
                bad.append(f"{rel}:{number}: открывает вкладку или окно, и причины на это нет в списке — "
                           f"всё в караване открывается в этой же вкладке: {line[:110]}")
                continue
            used[entry] = used.get(entry, 0) + 1
        for entry in self.ALLOWED:
            file, text, count, _ = entry
            if used.get(entry, 0) != count:
                bad.append(f"{file}: в списке причин «{text}» ×{count}, а в коде ×{used.get(entry, 0)} — "
                           f"список не совпал с кодом; поправить список или код")
        return bad, found


def main():
    bad, found = NewTabSites().problems()
    if bad:
        print("same tab links: FAILED", file=sys.stderr)
        for line in bad:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print(f"same tab links OK: {len(found)} мест просят другую вкладку"
          f"{' — у каждого есть причина' if found else '; всё в караване открывается в этой же'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
