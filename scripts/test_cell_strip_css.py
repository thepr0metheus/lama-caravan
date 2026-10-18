#!/usr/bin/env python3
"""Value snapshot: the strip of a start under a cell's folded line stays a thin line of the line's own width (1.3.572).

The owner, 2026-10-18, after starting a cell whose model had to be copied: "when I start a cell, do not widen it by itself — only in the
same thin line say the same as the card says, without the name of the model". The full card opened by itself for a copy, a load and a
warm-up; the folded line keeps the cell now and carries, under its own row, a strip (start-strip.js): the bar and the words of the
card's status line. What the layout stands on, read from the stylesheets' text (scripts/_css_rules.py — a browser is not in CI):

  - the line (`.cell-row`, static/css/fold.css) is a flex line that WRAPS: the strip is a second row of the same line, not a card and
    not a box beside it. Without `flex-wrap: wrap` the strip would be squeezed into the first row, beside the name;
  - the strip (`.cell-row > .fr-strip`) takes a whole row (`flex: 1 0 100%`), may shrink (`min-width: 0`), is itself a flex row, and
    starts under the port, past the switch (`padding-left: 37px` = the switch's 30px and the gap);
  - what stays a thin line inside it is the card's status line's own rule (static/css/nodes.css): the words are cut with an ellipsis
    instead of wrapping (`.model-status-line .msl-text`), the bar is a fixed 64px (`.msl-bar`) and follows the share with a
    transition (`.msl-bar > span`). The strip leans on all three, so they are read here too.

Each claim has a positive and a negative pin.

Run: python3 scripts/test_cell_strip_css.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
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


class StartStripLayout:
    @classmethod
    def problems(cls, fold_css, nodes_css):
        bad = []
        row = declared(fold_css, ".cell-row")
        strip = declared(fold_css, ".cell-row > .fr-strip")
        words = declared(nodes_css, ".model-status-line .msl-text")
        bar, fill = declared(nodes_css, ".msl-bar"), declared(nodes_css, ".msl-bar > span")
        if row.get("display") != "flex" or row.get("flex-wrap") != "wrap":
            bad.append("the strip has no row of its own: .cell-row is not display: flex with flex-wrap: wrap, so it is squeezed beside the name")
        if row.get("min-width") != "0":
            bad.append("the line may not shrink to its lane: .cell-row has no min-width: 0")
        if strip.get("flex") != "1 0 100%":
            bad.append("the strip is not a row of the line's whole width: .cell-row > .fr-strip needs flex: 1 0 100%")
        if strip.get("min-width") != "0":
            bad.append("the strip may not shrink to the line: .cell-row > .fr-strip has no min-width: 0")
        if strip.get("display") != "flex" or strip.get("align-items") != "center":
            bad.append("the bar and the words do not stand on one line: .cell-row > .fr-strip is not display: flex with align-items: center")
        if CssRules.px(strip.get("padding-left", "")) != 37:
            bad.append("the strip does not start under the port: .cell-row > .fr-strip needs padding-left: 37px (the switch's 30px and its gap)")
        if words.get("white-space") != "nowrap" or words.get("text-overflow") != "ellipsis" or words.get("overflow") != "hidden":
            bad.append("the words of the strip wrap and make the line taller: .model-status-line .msl-text needs nowrap, an ellipsis and overflow: hidden")
        if CssRules.px(bar.get("flex", "").split()[-1]) != 64 if bar.get("flex") else True:
            bad.append("the bar is not a fixed 64px: .msl-bar needs flex: 0 0 64px")
        if "width" not in fill.get("transition", ""):
            bad.append("the bar jumps instead of following the share: .msl-bar > span has no width transition")
        return bad


def main():
    fold = (ROOT / "static" / "css" / "fold.css").read_text(encoding="utf-8")
    nodes = (ROOT / "static" / "css" / "nodes.css").read_text(encoding="utf-8")
    real = StartStripLayout.problems(fold, nodes)
    check(real == [], "the strip is a thin second row of the folded line" + (f" — {'; '.join(real)}" if real else ""))

    def named(css_name, find, replace, phrase):
        css = {"fold": fold, "nodes": nodes}
        if find not in css[css_name]:
            check(False, f"the anchor {find!r} is still in the stylesheet — update the snapshot")
            return False
        css[css_name] = css[css_name].replace(find, replace, 1)
        return any(phrase in line for line in StartStripLayout.problems(css["fold"], css["nodes"]))

    check(named("fold", "  flex-wrap: wrap;\n  align-items: center;\n  gap: 3px 7px;", "  align-items: center;\n  gap: 3px 7px;", "has no row of its own"),
          "negative: a line that does not wrap — the strip would be squeezed beside the name — named")
    check(named("fold", "  flex: 1 0 100%;\n  min-width: 0;\n  display: flex;", "  flex: 1;\n  min-width: 0;\n  display: flex;", "not a row of the line's whole width"),
          "negative: a strip with no row of its own — named")
    check(named("fold", "  flex: 1 0 100%;\n  min-width: 0;\n  display: flex;", "  flex: 1 0 100%;\n  display: flex;", "may not shrink to the line"),
          "negative: a strip that may not shrink — named")
    check(named("fold", "  min-width: 0;\n  display: flex;\n  align-items: center;\n  /* Under the port", "  min-width: 0;\n  display: block;\n  align-items: center;\n  /* Under the port",
                "do not stand on one line"),
          "negative: a strip that is not a flex row — named")
    check(named("fold", "  padding-left: 37px;", "  padding-left: 0;", "does not start under the port"),
          "negative: a strip that starts under the switch instead of the port — named")
    check(named("nodes", "  text-overflow: ellipsis;\n  white-space: nowrap;\n}\n.msl-bar {", "  white-space: normal;\n}\n.msl-bar {", "wrap and make the line taller"),
          "negative: words that wrap — the strip would be taller than a thin line — named")
    check(named("nodes", "  flex: 0 0 64px;", "  flex: 1;", "not a fixed 64px"), "negative: a bar that stretches — named")
    check(named("nodes", "  transition: width 0.4s ease;", "  transition: none;", "jumps instead of following"), "negative: a bar that jumps — named")

    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("cell strip css snapshot holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
