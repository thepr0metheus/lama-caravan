#!/usr/bin/env python3
"""The bar at the top of every page is the template's, and the way back to the main board is in it.

scripts/gen_header.py holds the one template and the one table of how pages differ. A page's bar is a
COPY of what it renders (the pages are static files the tests and the E2E suite read as they are), and
copies drift: this is what stops it. Fails when

  * a page under static/ has no row in AppHeader.PAGES (a new page that was given a bar of its own);
  * a page does not hold exactly one `<header class="topbar">`, or its bar is not between the two marker
    comments, or what stands between them is not what the template renders — the message names the first
    line that differs, so "someone edited one page" reads as that and not as "CI is red";
  * the way back is hidden anywhere but on the main board: the one rule that hides `.topbar-back` is
    `html:not([data-board-view="machine"]) .topbar-back[data-view-only="machine"]`, only the board's row (index.html)
    may say its link is for the machine's view, and board-view.js must still say "main" and "machine" for the two
    views of index.html. The machine's window is index.html with `?host=`, and it lost its way back once because the
    bar was a copy that nobody remembered to give it; Routing lost its own while this was being written, because
    a first version keyed the rule on `data-board-view="main"` — a word Routing's script puts on /routing too.

How the page behaves in a browser is test_header.py's.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_header import AppHeader, ROOT  # noqa: E402

#: The one rule that takes the way back away: on the board's own page outside a machine's window, where back goes.
MAIN_RULE = re.compile(r'html:not\(\[data-board-view="machine"\]\)\s+\.topbar-back\[data-view-only="machine"\]\s*\{([^}]*)\}')
HIDES = re.compile(r'display:\s*none|visibility:\s*hidden|opacity:\s*0\b|clip-path|height:\s*0\b|width:\s*0\b')
#: What names the link in a selector: its own class, the class it shares with the page's other links, its hook.
NAMES = ("topbar-back", "sys-back", "header-back")
VIEWS = re.compile(r'isMachine\s*\?\s*"machine"\s*:\s*"main"')


def first_difference(want, got):
    """'line N: it has ..., the template has ...' for the first line two texts do not share."""
    a, b = want.split("\n"), got.split("\n")
    for number in range(max(len(a), len(b))):
        x = a[number] if number < len(a) else "<end of block>"
        y = b[number] if number < len(b) else "<end of block>"
        if x != y:
            return f"line {number + 1} of the bar: the page has {y.strip()[:110]!r}, the template has {x.strip()[:110]!r}"
    return "the texts differ in their line endings"


def page_problems():
    bad = []
    rows = {row.file: name for name, row in AppHeader.PAGES.items()}
    for path in sorted((ROOT / "static").glob("*.html")):
        if path.name not in rows:
            bad.append(f"static/{path.name} has no row in AppHeader.PAGES (scripts/gen_header.py): "
                       f"a page with no row has a bar of its own, and the way back is the first thing it lacks")
    for name, row in AppHeader.PAGES.items():
        path = AppHeader.path(name)
        rel = f"static/{row.file}"
        if not path.is_file():
            bad.append(f"{rel}: the page is gone — drop its row from AppHeader.PAGES or restore it")
            continue
        html = path.read_text(encoding="utf-8")
        bars = len(re.findall(r'<header class="topbar', html))
        if bars != 1:
            bad.append(f"{rel}: {bars} <header class=\"topbar\"> elements, not 1")
            continue
        if html.count(AppHeader.BEGIN) != 1 or html.count(AppHeader.END) != 1:
            bad.append(f"{rel}: the bar is not between the marker comments (python3 scripts/gen_header.py puts it there)")
            continue
        start = html.index(AppHeader.BEGIN)
        start = html.rfind("\n", 0, start) + 1
        stop = html.index(AppHeader.END) + len(AppHeader.END)
        stop = html.index("\n", stop) + 1
        held, want = html[start:stop], AppHeader.render(name)
        if held != want:
            bad.append(f"{rel}: its bar is not the template's — {first_difference(want, held)}; "
                       f"run python3 scripts/gen_header.py (and change the TEMPLATE, not the page, to change a bar)")
    return bad


def code_of(css):
    """The stylesheet without its comments: a comment that names the link is not a rule that hides it."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def way_back_problems():
    bad = []
    css = {p: code_of(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "static" / "css").glob("*.css"))}
    homes = [p.name for p, text in css.items() if MAIN_RULE.search(text)]
    if homes != ["base.css"]:
        bad.append(f"the main board's rule (html:not([data-board-view=\"machine\"]) .topbar-back[data-view-only=\"machine\"] "
                   f"{{ display: none }}) is in {homes or 'no stylesheet'}, not in base.css alone")
    for path, text in css.items():
        for rule in MAIN_RULE.finditer(text):
            if not re.search(r"display:\s*none", rule.group(1)):
                bad.append(f"static/css/{path.name}: the main board's rule no longer says display: none")
        rest = MAIN_RULE.sub("", text)
        for block in re.finditer(r"([^{}]+)\{([^}]*)\}", rest):
            selector, body = block.group(1).strip(), block.group(2)
            if any(name in selector for name in NAMES) and HIDES.search(body):
                bad.append(f"static/css/{path.name}: a rule other than the main board's takes the way back away "
                           f"({selector[:80]!r}: {HIDES.search(body).group(0)})")
    only = {name: row.back_only_in for name, row in AppHeader.PAGES.items() if row.back_only_in}
    if only != {"board": "machine"}:
        bad.append(f"the pages whose way back is for one view only are {only}; they must be the board's page alone, "
                   f"for the machine's window ({{'board': 'machine'}}): any other page hides the way back from itself")
    js = (ROOT / "static" / "js" / "board-view.js").read_text(encoding="utf-8")
    if not VIEWS.search(js):
        bad.append("static/js/board-view.js no longer says `isMachine ? \"machine\" : \"main\"` — the CSS rule that "
                   "hides the way back on the main board keys on those two words")
    return bad


def main():
    problems = page_problems() + way_back_problems()
    if problems:
        print("header: FAILED")
        for line in problems:
            print(f"  - {line}")
        return 1
    print(f"header OK: {len(AppHeader.PAGES)} pages, one template, the way back on each "
          f"(hidden on the main board alone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
