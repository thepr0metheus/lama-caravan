#!/usr/bin/env python3
"""Value snapshot: a card on the main board never stands wider than its column, and an issue row says its reason whole (1.3.571).

The owner, 2026-10-18, with a screenshot of the main board's cloud providers: "on an error the labels run off to the right, past the
screen". The "API issues" box of two ChatGPT subscriptions held a row — the endpoint, "off after 3 fails", the reason, "retry" — whose
reason was one line that could not break (`white-space: nowrap`, an ellipsis that only works in a box of a given width), and the grid of
provider cards had one implicit column, `auto`. An `auto` column takes the width of the widest thing in it: 722px in a column of 340px.
The card stood out of its column, cut at the right, and "retry" with it — the one button that brings the endpoint back.

A browser is not in CI, so what the stylesheets say about the boxes is read from their text (scripts/_css_rules.py). What the layout
stands on:

  - the grids that hold the main board's cards (`.machine-cards`, `.provider-cards`, static/css/topology-board.css) have ONE column that
    may shrink, `minmax(0, 1fr)`: not `auto`, and not `1fr` either (that is `minmax(auto, 1fr)`: the same blow-out);
  - the issue row (`.cloud-api-issue`, static/css/modals.css) wraps and may shrink: a row that cannot wrap asks for the width of its
    whole text from every box around it;
  - its reason (`.cloud-api-issue-err`) is said whole, not cut to a line: it has a basis of about 30 characters (beside the name while
    there is room, else on a line of its own), may shrink to nothing, and breaks anywhere in a word that has no break in it
    ("<urlopen", a path); `nowrap`, an ellipsis and `overflow: hidden` are what made it one line;
  - what is short stays whole: the state ("off after 3 fails") does not wrap, and "retry" does not shrink and stands at the end;
  - no other stylesheet talks over these rules (a later file that said `white-space: nowrap` again would undo them).

Each claim has a positive and a negative pin.

Run: python3 scripts/test_board_cards_fit_css.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "static" / "css"
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def declared(css, selector):
    """Every declaration of every rule whose selector is exactly this one, the later one over the earlier."""
    merged = {}
    for sel, decl in CssRules.rules(css):
        if sel == selector:
            merged.update(decl)
    return merged


class CardsFit:
    GRIDS = (".machine-cards", ".provider-cards")
    #: the stylesheet that owns each box; another one that sets one of these properties on it can undo the rule
    OWNERS = {".machine-cards": "topology-board.css", ".provider-cards": "topology-board.css", ".cloud-api-issue": "modals.css",
              ".cloud-api-issue-err": "modals.css", ".cloud-api-issue-state": "modals.css", ".cloud-api-retry": "modals.css"}
    GUARDED = ("grid-template-columns", "display", "flex", "flex-wrap", "flex-shrink", "min-width", "white-space", "text-overflow",
               "overflow", "overflow-x", "overflow-wrap", "word-break", "margin-left")

    @classmethod
    def problems(cls, board_css, modals_css, others=None):
        bad = []
        for selector in cls.GRIDS:
            grid = declared(board_css, selector)
            if grid.get("display") != "grid":
                bad.append(f"{selector} is not a grid any more: this snapshot reads the cards' column")
            elif grid.get("grid-template-columns") != "minmax(0, 1fr)":
                bad.append(f"{selector}'s column grows with the widest text in a card: grid-template-columns is not minmax(0, 1fr) "
                           f"(`auto` and a bare `1fr` both take the width of an unbreakable line, and the card stands out of its column)")
            if grid.get("min-width") != "0":
                bad.append(f"{selector} may not shrink to its column: min-width is not 0")
        row, err = declared(modals_css, ".cloud-api-issue"), declared(modals_css, ".cloud-api-issue-err")
        state, retry = declared(modals_css, ".cloud-api-issue-state"), declared(modals_css, ".cloud-api-retry")
        if row.get("display") != "flex" or row.get("flex-wrap") != "wrap":
            bad.append("an issue row cannot wrap: .cloud-api-issue is not display: flex with flex-wrap: wrap, so it asks for the width of its whole text")
        if row.get("min-width") != "0":
            bad.append("an issue row may not shrink to its card: .cloud-api-issue has no min-width: 0")
        if err.get("flex") != "1 1 20em":
            bad.append("the reason has no room of its own: .cloud-api-issue-err is not flex: 1 1 20em (beside the name while there is room, else on its own line)")
        if err.get("min-width") != "0":
            bad.append("the reason may not shrink: .cloud-api-issue-err has no min-width: 0")
        if err.get("overflow-wrap") != "anywhere":
            bad.append("a word of the reason with no break in it widens the card: .cloud-api-issue-err has no overflow-wrap: anywhere")
        for prop, value in (("white-space", "nowrap"), ("text-overflow", "ellipsis"), ("overflow", "hidden")):
            if err.get(prop) == value:
                bad.append(f"the reason is cut to a line again: .cloud-api-issue-err says {prop}: {value}")
        if state.get("white-space") != "nowrap":
            bad.append("the state wraps: .cloud-api-issue-state is not white-space: nowrap")
        if retry.get("flex-shrink") != "0" or retry.get("margin-left") != "auto":
            bad.append("\"retry\" shrinks or does not stand at the end: .cloud-api-retry needs flex-shrink: 0 and margin-left: auto")
        for name, css in (others or {}).items():
            for sel, decl in CssRules.rules(css):
                subject = CssRules.subject(sel)
                for box, owner in cls.OWNERS.items():
                    if name != owner and re.search(re.escape(box) + r"(?![\w-])", subject) and any(p in decl for p in cls.GUARDED):
                        bad.append(f"{name} talks over {box} ({sel}): its rule belongs in {owner}")
        return bad


def real_files():
    css = {path.name: path.read_text(encoding="utf-8") for path in sorted(CSS.glob("*.css"))}
    owners = {"topology-board.css", "modals.css"}
    return css["topology-board.css"], css["modals.css"], {n: t for n, t in css.items() if n not in owners}


def main():
    board, modals, others = real_files()
    real = CardsFit.problems(board, modals, others)
    check(real == [], "the board's card grids and the issue rows are as the layout needs" + (f" — {'; '.join(real)}" if real else ""))

    def named(find, replace, phrase, in_modals=False, others_extra=None):
        css = modals if in_modals else board
        if find not in css:
            check(False, f"the anchor {find!r} is still in the stylesheet — update the snapshot")
            return False
        css = css.replace(find, replace, 1)
        found = CardsFit.problems(board if in_modals else css, css if in_modals else modals, {**others, **(others_extra or {})})
        return any(phrase in line for line in found)

    check(named(".provider-cards { display: grid; grid-template-columns: minmax(0, 1fr);", ".provider-cards { display: grid;", "provider-cards's column grows"),
          "negative: the provider cards' grid with no column of its own (the `auto` one) — named")
    check(named(".machine-cards { display: grid; grid-template-columns: minmax(0, 1fr);", ".machine-cards { display: grid;", "machine-cards's column grows"),
          "negative: the machine cards' grid with no column of its own — named")
    check(named(".provider-cards { display: grid; grid-template-columns: minmax(0, 1fr);", ".provider-cards { display: grid; grid-template-columns: 1fr;",
                "provider-cards's column grows"),
          "negative: a bare `1fr` (its minimum is `auto`: the same blow-out) — named")
    check(named(".provider-cards { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; min-width: 0; }",
                ".provider-cards { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; }", "provider-cards may not shrink"),
          "negative: a grid that may not shrink to its column — named")
    check(named("  flex-wrap: wrap;\n  align-items: baseline;", "  align-items: baseline;", "cannot wrap", in_modals=True),
          "negative: an issue row that cannot wrap — named")
    check(named("  gap: 2px 6px;\n  min-width: 0;\n", "  gap: 2px 6px;\n", "may not shrink to its card", in_modals=True),
          "negative: an issue row that may not shrink — named")
    check(named("flex: 1 1 20em;", "flex: 1;", "has no room of its own", in_modals=True), "negative: a reason with no basis of its own (always beside the name, however narrow) — named")
    check(named("  flex: 1 1 20em;\n  min-width: 0;\n  overflow-wrap: anywhere;", "  flex: 1 1 20em;\n  overflow-wrap: anywhere;", "the reason may not shrink", in_modals=True),
          "negative: a reason that may not shrink — named")
    check(named("  flex: 1 1 20em;\n  min-width: 0;\n  overflow-wrap: anywhere;", "  flex: 1 1 20em;\n  min-width: 0;\n  overflow-wrap: normal;", "no break in it widens", in_modals=True),
          "negative: a reason whose unbreakable word widens the card — named")
    check(named("  flex: 1 1 20em;\n", "  flex: 1 1 20em;\n  white-space: nowrap;\n", "cut to a line again", in_modals=True),
          "negative: a reason that is `nowrap` again — named")
    check(named("  flex: 1 1 20em;\n", "  flex: 1 1 20em;\n  text-overflow: ellipsis;\n", "cut to a line again", in_modals=True),
          "negative: a reason with an ellipsis again — named")
    check(named("  flex: 1 1 20em;\n", "  flex: 1 1 20em;\n  overflow: hidden;\n", "cut to a line again", in_modals=True),
          "negative: a reason with `overflow: hidden` again — named")
    check(named(".cloud-api-issue-state { color: var(--muted); white-space: nowrap; }", ".cloud-api-issue-state { color: var(--muted); }", "the state wraps", in_modals=True),
          "negative: a state that wraps — named")
    check(named(".cloud-api-retry { margin-left: auto; flex-shrink: 0;", ".cloud-api-retry { margin-left: auto;", "shrinks or does not stand at the end", in_modals=True),
          "negative: a \"retry\" that shrinks — named")
    check(named(".cloud-api-retry { margin-left: auto; flex-shrink: 0;", ".cloud-api-retry { flex-shrink: 0;", "shrinks or does not stand at the end", in_modals=True),
          "negative: a \"retry\" that does not stand at the end — named")
    check(named("", "", "talks over .cloud-api-issue-err", in_modals=True, others_extra={"later.css": ".pb-card .cloud-api-issue-err { white-space: nowrap; }"}),
          "negative: a later stylesheet says `nowrap` on the reason again — named")
    check(named("", "", "talks over .provider-cards", others_extra={"later.css": ".lane-servers .provider-cards { grid-template-columns: auto; }"}),
          "negative: a later stylesheet gives the provider cards' grid its `auto` column back — named")
    check(not named("", "", "talks over", others_extra={"later.css": ".pb-card .cloud-api-issue-err { color: red; }"}),
          "a later stylesheet that only paints the reason is no stray")

    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("board cards fit css snapshot holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
