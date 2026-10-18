#!/usr/bin/env python3
"""Value snapshot: the cables pulled from the right (1.3.587) — what static/css/pool-board.css says of the handle and of the places a cable lands on.

The owner, 2026-10-18, looking at Routing: "I want to pull a link from the right block to the left block, even onto the part a link already leaves
from — a new link, a new row". An input dot (the one on a card's left edge) is the handle of such a cable: a pool's goes onto a set, a set's onto a
client, a model's onto a pool. The browser is not in CI, so this reads the stylesheet's text and names a stylesheet in which

  - an input dot looks like a handle: the crosshair of an output's dot (`cursor: crosshair`), and the same ring when the pointer is on it
    (`box-shadow`) — a dot that does not answer the pointer would not be found;
  - the places a cable pulled from the right can land on are outlined while it is in the hand, as every other kind's are: the sets for a
    pool's cable (`.pb.dragging-pull-pool .pb-set`), the clients for a set's (`.pb.dragging-pull-set .pb-client`) — dashed, in the one rule of
    the other kinds, so the five outlines cannot drift apart;
  - a place that already has what the cable would give it (`.pb-holds`: a set that holds the pool, a client that sees the set) loses the
    outline and is quieter, for the cable of its own kind only — it is no landing, and an outline would say it is.

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
    LANDINGS = (".pb.dragging-client .pb-set", ".pb.dragging-set .pb-pool", ".pb.dragging-row .pb-model[data-pb-model]",
                ".pb.dragging-new-row .pb-model[data-pb-model]", ".pb.dragging-pull-pool .pb-set", ".pb.dragging-pull-set .pb-client")

    @classmethod
    def problems(cls, css):
        bad = []
        if declared(css, ".pb-dot.in").get("cursor") != "crosshair":
            bad.append("an input dot is not a crosshair, as an output's is")
        ring = declared(css, ".pb-dot.in:hover").get("box-shadow", "")
        if "0 0 0 4px" not in ring or ring != declared(css, ".pb-dot.out:hover").get("box-shadow"):
            bad.append("an input dot has no ring under the pointer, or not the ring of an output's")
        outlines = {declared(css, sel).get("outline") for sel in cls.LANDINGS}
        if len(outlines) != 1 or "dashed" not in str(next(iter(outlines))):
            bad.append("the landing places of the five kinds of cable are not outlined by one dashed outline")
        for sel in (".pb.dragging-pull-pool .pb-set.pb-holds", ".pb.dragging-pull-set .pb-client.pb-holds"):
            rule = declared(css, sel)
            if rule.get("outline") != "none" or rule.get("opacity") is None or float(rule["opacity"]) >= 1:
                bad.append(f"{sel} keeps the outline of a landing, or is not quieter")
        if declared(css, ".pb .pb-holds") or declared(css, ".pb-holds"):
            bad.append("`.pb-holds` quiets a place whatever cable is in the hand — it belongs to the pulled kinds only")
        return bad


def named(css, old, new):
    """The problems of the stylesheet with one thing changed (the old text must be there to change)."""
    assert old in css, f"the stylesheet has no {old!r} to change"
    return PullCss.problems(css.replace(old, new, 1))


def main():
    css = (ROOT / "static" / "css" / "pool-board.css").read_text(encoding="utf-8")
    print("the handle and the landing places:")
    check(PullCss.problems(css) == [], f"an input dot is a handle; the places of a pulled cable are outlined as the others are; what already has it is quiet — {PullCss.problems(css)}")
    check("not a crosshair" in "; ".join(named(css, ".pb-dot.in { cursor: crosshair; }", ".pb-dot.in { cursor: default; }")),
          "negative: an input dot with the default pointer — named")
    check("not a crosshair" in "; ".join(named(css, ".pb-dot.in { cursor: crosshair; }", "")), "negative: an input dot with no pointer of its own — named")
    check("no ring" in "; ".join(named(css, ".pb-dot.in:hover { box-shadow: 0 0 0 4px", ".pb-dot.in:hover { box-shadow: 0 0 0 9px")), "negative: a ring that is not an output's — named")
    check("no ring" in "; ".join(named(css, ".pb-dot.in:hover {", ".pb-dot.in:focus {")), "negative: the ring only when focused, not under the pointer — named")
    check("not outlined" in "; ".join(named(css, ".pb.dragging-pull-pool .pb-set, .pb.dragging-pull-set .pb-client { outline: 1px dashed", ".pb.dragging-pull-pool .pb-set { outline: 1px dotted")),
          "negative: a pulled cable whose landing places have an outline of their own — named")
    check("not outlined" in "; ".join(named(css, ".pb.dragging-pull-set .pb-client { outline:", ".pb.dragging-pull-set .pb-clients { outline:")),
          "negative: the clients are not outlined for a set's cable — named")
    check("keeps the outline" in "; ".join(named(css, ".pb.dragging-pull-pool .pb-set.pb-holds, .pb.dragging-pull-set .pb-client.pb-holds { outline: none; opacity: .6; }",
                                                 ".pb.dragging-pull-pool .pb-set.pb-holds, .pb.dragging-pull-set .pb-client.pb-holds { opacity: .6; }")),
          "negative: a set that holds the pool keeps its outline — named")
    check("keeps the outline" in "; ".join(named(css, "outline: none; opacity: .6; }", "outline: none; opacity: 1; }")), "negative: a place that is not quieter — named")
    check("whatever cable" in "; ".join(PullCss.problems(css + "\n.pb .pb-holds { opacity: .3; }")), "negative: `.pb-holds` that quiets a place for any cable — named")
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
