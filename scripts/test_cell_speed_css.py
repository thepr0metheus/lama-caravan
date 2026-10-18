#!/usr/bin/env python3
"""Value snapshot: the breathing of a cell's switch and the quiet of a held speed (1.3.588).

The owner, 2026-10-18, shown a Strata cell on the machine page: the ring around the switch of the line pulsed, both video cards stood at 0 %,
and the line said "211.3 t/s". cell-speed.js now decides what is work (a request running) and what is only the last speed held (`.held`).
What the stylesheet (static/css/fold.css) must say for that to be seen, read from its text (scripts/_css_rules.py — a browser is not in CI):

  - the switch breathes: `.cell-row.busy .fr-switch` runs the animation `fold-breathe`, forever, and the keyframes exist;
  - ONLY the busy line breathes: no other rule (not `.cell-row`, not `.held`, not `.fr-tps`) runs `fold-breathe` — a ring on a line that holds
    a speed would say "working" again;
  - a user who asked for less motion gets none: the reduced-motion rule turns the animation off for the busy switch;
  - a held speed is quiet: `.fr-tps.held` takes the muted text colour (not the accent of a live figure) and a lighter weight than `.fr-tps`;
  - the span is there and hidden when empty (`.fr-tps:empty`): the live patch writes into it, and an empty span shows nothing.

Each claim has a positive and a negative pin.

Run: python3 scripts/test_cell_speed_css.py
"""
import re
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
    """Every declaration of every rule that has exactly this selector, the later one over the earlier."""
    merged = {}
    for sel, decl in CssRules.rules(css):
        if sel == selector:
            merged.update(decl)
    return merged


def each(css, selector, name):
    """The values `name` takes in each rule of this selector, in the order of the stylesheet."""
    return [decl[name] for sel, decl in CssRules.rules(css) if sel == selector and name in decl]


class CellSpeedLook:
    SWITCH = ".cell-row.busy .fr-switch"

    @classmethod
    def problems(cls, css):
        bad = []
        runs = each(css, cls.SWITCH, "animation")
        if not runs or "fold-breathe" not in runs[0] or "infinite" not in runs[0]:
            bad.append("the busy switch does not breathe forever: `.cell-row.busy .fr-switch` has no `animation: fold-breathe … infinite`")
        if "@keyframes fold-breathe" not in css:
            bad.append("the keyframes `fold-breathe` are gone, and the animation names nothing")
        if len(runs) < 2 or runs[-1] != "none" or "prefers-reduced-motion" not in css:
            bad.append("a user who asked for less motion still gets the breathing: no reduced-motion rule turns it off")
        elsewhere = sorted({sel for sel, decl in CssRules.rules(css) if "fold-breathe" in decl.get("animation", "") and ".busy" not in sel})
        if elsewhere:
            bad.append(f"a line that is not busy breathes: {', '.join(elsewhere)} runs `fold-breathe` — only `.busy` is work")
        held, live = declared(css, ".fr-tps.held"), declared(css, ".fr-tps")
        if held.get("color") != "var(--muted)" or "accent" not in live.get("color", ""):
            bad.append("a held speed is not quiet: `.fr-tps.held` should take `var(--muted)` while a live figure keeps the accent mix")
        weight = re.fullmatch(r"(\d+)", held.get("font-weight", ""))
        live_weight = re.match(r"(\d+)\s", live.get("font", ""))
        if not weight or not live_weight or int(weight.group(1)) >= int(live_weight.group(1)):
            bad.append("a held speed is not lighter than a live figure: `.fr-tps.held` needs a font-weight below the 600 of `.fr-tps`")
        if declared(css, ".fr-tps:empty").get("display") != "none":
            bad.append("an empty speed shows: `.fr-tps:empty` is not `display: none`")
        return bad


def named(css, old, new):
    """The problems of the stylesheet with one thing changed (the old text must be there to change)."""
    assert old in css, f"the stylesheet has no {old!r} to change"
    return CellSpeedLook.problems(css.replace(old, new, 1))


def main():
    css = (ROOT / "static" / "css" / "fold.css").read_text(encoding="utf-8")
    print("the breathing and the held speed:")
    check(CellSpeedLook.problems(css) == [], f"only the busy switch breathes (and not with reduced motion); a held speed is quiet — {CellSpeedLook.problems(css)}")
    check("does not breathe" in "; ".join(named(css, ".cell-row.busy .fr-switch { animation: fold-breathe 1.4s ease-in-out infinite; }",
                                                 ".cell-row.busy .fr-switch { animation: none; }")),
          "negative: a busy switch with no animation — named")
    check("does not breathe" in "; ".join(named(css, "fold-breathe 1.4s ease-in-out infinite;", "fold-breathe 1.4s ease-in-out 3;")),
          "negative: a breathing that stops after three — named")
    check("keyframes" in "; ".join(named(css, "@keyframes fold-breathe", "@keyframes fold-breath")), "negative: the keyframes renamed — named")
    check("less motion" in "; ".join(named(css, "  .cell-row.busy .fr-switch { animation: none; }", "")),
          "negative: no reduced-motion rule — named")
    check("not busy breathes" in "; ".join(named(css, ".cell-row.busy .fr-switch { animation: fold-breathe 1.4s ease-in-out infinite; }",
                                                 ".cell-row .fr-switch { animation: fold-breathe 1.4s ease-in-out infinite; }")),
          "negative: every line breathes, not only the busy one — named")
    check("not busy breathes" in "; ".join(CellSpeedLook.problems(css + "\n.fr-tps.held { animation: fold-breathe 1s infinite; }")),
          "negative: a held speed that breathes too — named")
    check("not quiet" in "; ".join(named(css, ".fr-tps.held { font-weight: 500; color: var(--muted); }", ".fr-tps.held { font-weight: 500; }")),
          "negative: a held speed that keeps the accent of a live figure — named")
    check("not quiet" in "; ".join(named(css, ".fr-tps.held { font-weight: 500; color: var(--muted); }", ".fr-tps.held { font-weight: 500; color: var(--text); }")),
          "negative: a held speed in the plain text colour — named")
    check("not lighter" in "; ".join(named(css, ".fr-tps.held { font-weight: 500;", ".fr-tps.held { font-weight: 600;")),
          "negative: a held speed as heavy as a live figure — named")
    check("empty speed shows" in "; ".join(named(css, ".fr-tps:empty { display: none; }", "")), "negative: an empty speed that shows — named")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("cell speed css snapshot holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
