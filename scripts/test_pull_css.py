#!/usr/bin/env python3
"""Value snapshot: the cables pulled from the right (1.3.587) — what static/css/pool-board.css says of the handle and of the places a cable lands on.

The owner, 2026-10-18, looking at Routing: "I want to pull a link from the right block to the left block, even onto the part a link already leaves
from — a new link, a new row". A model's input dot is the handle of such a cable: it goes onto a pool, as the model's ⠿ does. Since 1.3.675 there
are no sets and a client draws no cable (the owner, 2026-10-27: every client sees every pool and every model), so a pool's input, a client's dot and
a row of «Напрямую»'s dots only mark where a client's cables run. The browser is not in CI, so this reads the stylesheet's text and names a
stylesheet in which

  - a model's input dot does not look like a handle: the crosshair of an output's dot (`cursor: crosshair`), and the same ring when the pointer
    is on it (`box-shadow`) — a dot that does not answer the pointer would not be found;
  - a dot that is no handle looks like one: the crosshair on every input dot, or none of the quiet look on a client's mark, a pool's input and a
    row of «Напрojmую»'s dots;
  - the places a row's cable can land on are not outlined while it is in the hand by one dashed outline, the same for a row's and a "＋ row"'s;
  - a rule of the set-era cables is left (`.pb-holds`, `dragging-pull-*`, `dragging-client`, `dragging-set`): it would style what nothing draws.

Run: python3 scripts/test_pull_css.py
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
    """Every declaration of every rule that has this selector, the later one over the earlier."""
    merged = {}
    for sel, decl in CssRules.rules(css):
        if sel == selector:
            merged.update(decl)
    return merged


class PullCss:
    LANDINGS = (".pb.dragging-row .pb-model[data-pb-model]", ".pb.dragging-new-row .pb-model[data-pb-model]")
    #: The dots that only mark where a client's cables run (1.3.675): a client's, a pool's input, a row of «Напрямую»'s.
    PASSIVE = (".pb-dot.anchor", ".pb-pool > .pb-dot.in", ".pb-direct-row > .pb-dot")
    OLD = ("pb-holds", "dragging-pull", "dragging-client", "dragging-set")

    @classmethod
    def problems(cls, css):
        bad = []
        if declared(css, ".pb-model .pb-dot.in").get("cursor") != "crosshair":
            bad.append("a model's input dot is not a crosshair, as an output's is")
        ring = declared(css, ".pb-model .pb-dot.in:hover").get("box-shadow", "")
        if "0 0 0 4px" not in ring or ring != declared(css, ".pb-dot.out:hover").get("box-shadow"):
            bad.append("a model's input dot has no ring under the pointer, or not the ring of an output's")
        if declared(css, ".pb-dot.in").get("cursor") == "crosshair":
            bad.append("every input dot is a crosshair: a pool's input is no handle since 1.3.675")
        for sel in cls.PASSIVE:
            if declared(css, sel).get("cursor") != "default":
                bad.append(f"{sel} is no handle and still looks like one")
        outlines = {declared(css, sel).get("outline") for sel in cls.LANDINGS}
        if len(outlines) != 1 or "dashed" not in str(next(iter(outlines))):
            bad.append("the landing places of a row's cable are not outlined by one dashed outline")
        left = sorted({sel for sel, _ in CssRules.rules(css) if any(word in sel for word in cls.OLD)})
        if left:
            bad.append(f"a rule of the set-era cables is left: {left}")
        return bad


def named(css, old, new):
    """The problems of the stylesheet with one thing changed (the old text must be there to change)."""
    assert old in css, f"the stylesheet has no {old!r} to change"
    return PullCss.problems(css.replace(old, new, 1))


def main():
    css = (ROOT / "static" / "css" / "pool-board.css").read_text(encoding="utf-8")
    print("the handle and the landing places:")
    check(PullCss.problems(css) == [], f"a model's input dot is a handle; the dots that only mark a client's cables are quiet; a row's landing places are "
          f"outlined; no set-era rule is left — {PullCss.problems(css)}")
    check("not a crosshair" in "; ".join(named(css, ".pb-model .pb-dot.in { cursor: crosshair; }", ".pb-model .pb-dot.in { cursor: default; }")),
          "negative: a model's input dot with the default pointer — named")
    check("no ring" in "; ".join(named(css, ".pb-model .pb-dot.in:hover { box-shadow: 0 0 0 4px", ".pb-model .pb-dot.in:hover { box-shadow: 0 0 0 9px")),
          "negative: a ring that is not an output's — named")
    check("every input dot" in "; ".join(PullCss.problems(css + "\n.pb-dot.in { cursor: crosshair; }")), "negative: every input dot a crosshair again — named")
    check(".pb-pool > .pb-dot.in is no handle" in "; ".join(named(css, ".pb-pool > .pb-dot.in, ", "")),
          "negative: a pool's input that lost the quiet look — named")
    check("not outlined" in "; ".join(named(css, ".pb.dragging-new-row .pb-model[data-pb-model] { outline", ".pb.dragging-new-row .pb-models { outline")),
          "negative: a \"＋ row\"'s cable whose landing places are not outlined — named")
    check("set-era" in "; ".join(PullCss.problems(css + "\n.pb.dragging-pull-pool .pb-set { outline: none; }")), "negative: a set-era rule put back — named")
    check("set-era" in "; ".join(PullCss.problems(css + "\n.pb .pb-holds { opacity: .3; }")), "negative: `.pb-holds` put back — named")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m)
        return 1
    print("pull css snapshot holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
