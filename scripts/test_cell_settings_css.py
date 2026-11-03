#!/usr/bin/env python3
"""Value snapshot: the editor of a cell's settings is styled wherever it is drawn, and its star is a quiet mark (1.3.640).

The editor (cell-settings.js) is drawn in two places: the cell window's Settings tab and, since 1.3.638, the new-cell wizard's "all the
settings of llama.cpp". Its rules hung on the cell window (`.cw .cws-*`): in the wizard the search, the groups, the boxes and the fields
fell back to the board's own inputs and buttons — 42px boxes, outlined group buttons with the count glued to the name. And the star
that 1.3.638 put at every field had no rule at all: a white browser button the width of the name stood over every field, in the window
too (seen on the live board, 2026-10-26). What the stylesheet (static/css/fold.css) must say for that not to come back, read from its
text (scripts/_css_rules.py — a browser is not in CI):

  - the editor's controls hang on its own root (`.cws`), never on the cell window (`.cw .cws-…`);
  - the star (`.cws .cws-star`) is a small mark, not a button: no background, no border, no padding, and `min-height: 0` (the board
    gives every button 34px); pressed (`.on`), it is the board's yellow;
  - a name with a star is two columns (`.cws-name:has(> .cws-star)` — a grid): the star beside the name, not a row over it.

Each claim has a positive and a negative pin.

Run: python3 scripts/test_cell_settings_css.py
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
    merged = {}
    for sel, decl in CssRules.rules(css):
        if sel == selector:
            merged.update(decl)
    return merged


class EditorLook:
    #: The controls the board styles for itself, which the editor must restyle wherever it is drawn.
    CONTROLS = (".cws-query", ".cws-toggle", ".cws-group", ".cws-input", ".cws-star")

    @classmethod
    def problems(cls, fold_css):
        bad = []
        selectors = [sel for sel, _decl in CssRules.rules(fold_css)]
        bound = sorted({sel for sel in selectors if sel.startswith(".cw .cws-")})
        if bound:
            bad.append("the editor is styled in the cell window only — the wizard draws it bare: " + ", ".join(bound))
        for control in cls.CONTROLS:
            if ".cws " + control not in selectors:
                bad.append(f"no rule styles {control} under the editor's root (.cws {control})")
        star = declared(fold_css, ".cws .cws-star")
        if star.get("background") != "transparent" or star.get("border") != "0" or CssRules.px(star.get("padding", "")) != 0:
            bad.append("the star is drawn as a button: .cws .cws-star needs background: transparent, border: 0 and padding: 0")
        if star.get("min-height") != "0":
            bad.append("the star takes the board's button height: .cws .cws-star needs min-height: 0")
        if declared(fold_css, ".cws .cws-star.on").get("color") != "var(--yellow)":
            bad.append("a pressed star does not look pressed: .cws .cws-star.on needs color: var(--yellow)")
        if declared(fold_css, ".cws-name:has(> .cws-star)").get("display") != "grid":
            bad.append("the star stands over the name instead of beside it: .cws-name:has(> .cws-star) needs display: grid")
        return bad


def main():
    fold = (ROOT / "static" / "css" / "fold.css").read_text(encoding="utf-8")
    real = EditorLook.problems(fold)
    check(real == [], "the editor is styled under its own root, and its star is a quiet mark" + (f" — {'; '.join(real)}" if real else ""))

    def named(find, replace, phrase):
        if find not in fold:
            check(False, f"the anchor {find!r} is still in the stylesheet — update the snapshot")
            return False
        return any(phrase in line for line in EditorLook.problems(fold.replace(find, replace, 1)))

    check(named(".cws .cws-group {", ".cw .cws-group {", "styled in the cell window only"),
          "negative: a group rule hung on the cell window again — the wizard draws its groups bare — named")
    check(named(".cws .cws-star {", ".cws .cws-mark {", "no rule styles .cws-star"),
          "negative: no rule for the star at all (as 1.3.638 shipped it) — named")
    check(named("border: 0; border-radius: 6px; background: transparent; color: var(--muted);",
                "border: 1px solid var(--line); border-radius: 6px; background: var(--panel); color: var(--muted);", "drawn as a button"),
          "negative: a star with a background and a border — a button — named")
    check(named("  flex: none; width: 22px; height: 22px; min-height: 0; margin: 0; padding: 0;",
                "  flex: none; width: 22px; height: 22px; margin: 0; padding: 0;", "board's button height"),
          "negative: a star without min-height: 0 takes the board's 34px — named")
    check(named(".cws .cws-star.on { opacity: 1; color: var(--yellow); }", ".cws .cws-star.on { opacity: 1; }", "does not look pressed"),
          "negative: a pressed star the colour of an unpressed one — named")
    check(named(".cws-name:has(> .cws-star) { display: grid;", ".cws-name:has(> .cws-star) { display: flex;", "over the name instead of beside it"),
          "negative: the star in a column over the name — named")

    print()
    if _fail:
        print(f"cell settings css: {len(_fail)} FAILED")
        return 1
    print("cell settings css OK: the editor is styled wherever it is drawn, its star is a quiet mark")
    return 0


if __name__ == "__main__":
    sys.exit(main())
