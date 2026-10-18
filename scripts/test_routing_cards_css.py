#!/usr/bin/env python3
"""Value snapshot: Routing's cards are as the approved mockup draws them (1.3.541): the Models column, and where a head's text starts.

The owner, 2026-10-14, to the Models column of 1.3.540: "you made the right part so well — I do not see that carried over". The mockup:
a card is a head (the name, and at the right what the card says of itself), one line of meters, and a line of 24px for each model; what is
news stands on the line, and the tools — the "＋ model" in the head, a model's ✕ and its ⏱ while it has no schedule — are quiet until the card
or the line is pointed at (the calm board of 1.3.531). The browser is not in CI, so this snapshot reads static/css/pool-board.css and
names a stylesheet in which

  - a quiet tool is not quiet: no `opacity: 0` at rest, or no way to see it — by the pointer, by the keyboard, or where there is no pointer;
  - the ⏱ or the ✕ keeps room at rest (`width: 0` is what lets a long name keep the room the tool would have held), or does not take it
    when it shows;
  - the "＋ model" cannot be reached on a card with no model: that card shows it at rest (`.empty`);
  - the line is not 24px high, or it has hairlines between lines again (the old card's `border-top`);
  - the cable's socket is not on the card's edge: the line is inset from it, so the socket's offset must be the inset plus its own 8px;
  - a long name pushes the marks out of sight instead of being cut with an ellipsis, or the marks shrink and lose their words;
  - the head wraps (the status would drop under the name, as it did until 1.3.540), or the status is not pushed to the right;
  - the strip below hides the windows' reset times: the card does not say them any more, the strip is where they are;
  - a card's grip keeps room in the head (until 1.3.541 it kept 20px, empty, and every name of a client, a set and a pool stood that
    much to the right of the mockup's); or a client's key does not stand at the right of its first line;
  - a pool's row is not as the owner left it to be drawn (1.3.543, "choose the most beautiful variant yourself"): its ✕ or its grip keep
    room at rest (a row's model and place were cut for tools nobody saw); its rank is a circle again; its state is a pill with a
    frame and not a dot and a word; a pool of one row has a box and a rank-wide gap again, a line under its name in the mockup.

Run: python3 scripts/test_routing_cards_css.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "static" / "css" / "pool-board.css"

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class ModelsCss:
    """What a stylesheet says of the Models column's cards and lines."""

    MEDIA = re.compile(r"@media\s*([^{]*)\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}")
    #: The tools that are quiet at rest: (what it is, its selectors at rest, the selectors that show it, the one that shows it where
    #: there is no pointer, whether it takes room only when it is shown).
    TOOLS = (
        ("the ＋ in the card's head", (".pb-add-model",),
         (".pb-src:hover .pb-add-model", ".pb-src:focus-within .pb-add-model", ".pb-src.empty .pb-add-model", ".pb-add-model:focus-visible"),
         ".pb-add-model", False),
        ("a model's ⏱ without a schedule", (".pb .pb-sched.none", ".pb .pb-sched.off"),
         (".pb-model:hover .pb-sched", ".pb-model:focus-within .pb-sched", ".pb .pb-sched:focus-visible"), ".pb .pb-sched", True),
        ("a model's ✕", (".pb .pb-model-remove",),
         (".pb-model:hover .pb-model-remove", ".pb-model:focus-within .pb-model-remove", ".pb .pb-model-remove:focus-visible"), ".pb .pb-model-remove", True),
    )

    @classmethod
    def split(cls, css):
        """(the stylesheet without its @media blocks, the blocks as [(query, css)]): a rule read from a block must not
        pass for the rule at rest."""
        blocks = [(m.group(1).strip(), m.group(2)) for m in cls.MEDIA.finditer(css)]
        return cls.MEDIA.sub("", css), blocks

    @classmethod
    def declared(cls, rules, selector):
        """What the rules of exactly this selector give, the last one winning each property."""
        found = {}
        for sel, declarations in rules:
            if sel == selector:
                found.update(declarations)
        return found

    @classmethod
    def tool_problems(cls, css):
        base_css, blocks = cls.split(css)
        rules = CssRules.rules(base_css)
        touch = CssRules.rules("\n".join(inner for query, inner in blocks if "hover: none" in query.replace("  ", " ")))
        bad = []
        for name, rest, shown, touch_selector, takes_room in cls.TOOLS:
            for selector in rest:
                at_rest = cls.declared(rules, selector)
                if at_rest.get("opacity") != "0":
                    bad.append(f"{name} is not quiet at rest: {selector} has opacity {at_rest.get('opacity')!r}, not 0")
                if takes_room and at_rest.get("width") != "0":
                    bad.append(f"{name} keeps room at rest: {selector} has width {at_rest.get('width')!r}, not 0")
            for selector in shown:
                lit = cls.declared(rules, selector)
                if lit.get("opacity") != "1":
                    bad.append(f"{name} stays quiet at {selector}: opacity {lit.get('opacity')!r}, not 1")
                if takes_room and lit.get("width") != "auto":
                    bad.append(f"{name} takes no room at {selector}: width {lit.get('width')!r}, not auto")
            if cls.declared(touch, touch_selector).get("opacity") != "1":
                bad.append(f"{name} cannot be seen where there is no pointer: no @media (hover: none) rule shows it")
        return bad

    @classmethod
    def line_problems(cls, css):
        base_css, _ = cls.split(css)
        rules = CssRules.rules(base_css)
        line, card = cls.declared(rules, ".pb-model"), cls.declared(rules, ".pb-src")
        bad = []
        if line.get("height") != "24px":
            bad.append(f"a model's line is {line.get('height')!r} high, not 24px")
        if any(k in line for k in ("border-top", "border-bottom", "border")):
            bad.append("a model's line has a border again: the lines stand with no hairlines between them")
        inset = (CssRules.sides(card.get("padding", "")) or [0, 0, 0, 0])[3] + (CssRules.sides(line.get("margin", "")) or [0, 0, 0, 0])[3]
        socket = CssRules.px(cls.declared(rules, ".pb-model > .pb-dot.in").get("left"))
        if socket is None or socket != -(inset + 8):
            bad.append(f"the socket is not on the card's edge: the line is inset {inset:g}px, its socket stands at {socket!r}, not {-(inset + 8):g}px")
        name = cls.declared(rules, ".pb-model-name")
        for prop, value in (("min-width", "0"), ("overflow", "hidden"), ("text-overflow", "ellipsis"), ("white-space", "nowrap")):
            if name.get(prop) != value:
                bad.append(f"a long name is not cut with an ellipsis: .pb-model-name has {prop} {name.get(prop)!r}, not {value}")
        if name.get("flex", "").split()[1:2] != ["1"]:
            bad.append(f"a long name does not shrink first: .pb-model-name has flex {name.get('flex')!r}, not 0 1 auto")
        if cls.declared(rules, ".pb-chips").get("flex") != "none":
            bad.append("the marks shrink: .pb-chips has no `flex: none`, so a long name would take their room and cut their words")
        return bad

    @classmethod
    def head_problems(cls, css):
        base_css, _ = cls.split(css)
        rules = CssRules.rules(base_css)
        head, note = cls.declared(rules, ".pb-src-head"), cls.declared(rules, ".pb-src-head .pb-src-note")
        bad = []
        if head.get("display") != "flex" or head.get("flex-wrap", "nowrap") != "nowrap":
            bad.append(f"the head is not one line: display {head.get('display')!r}, flex-wrap {head.get('flex-wrap', 'nowrap')!r}")
        if note.get("margin-left") != "auto":
            bad.append(f"the status is not at the right of the head: its margin-left is {note.get('margin-left')!r}, not auto")
        return bad

    @classmethod
    def strip_problems(cls, css):
        base_css, _ = cls.split(css)
        hidden = [sel for sel, d in CssRules.rules(base_css) if "sub-usage-resets" in sel and sel.startswith(".pb-dock") and d.get("display") == "none"]
        return [f"{sel} hides when the windows reset: the card does not say it any more" for sel in hidden]

    @classmethod
    def card_problems(cls, css):
        base_css, _ = cls.split(css)
        rules = CssRules.rules(base_css)
        grip, key = cls.declared(rules, ".pb-card-grip"), cls.declared(rules, ".pb-client > .pb-key")
        bad = []
        if grip.get("position") != "absolute":
            bad.append(f"a card's grip keeps room in the head: .pb-card-grip has position {grip.get('position')!r}, not absolute")
        if key.get("margin-left") != "auto":
            bad.append(f"a client's key is not at the right of its first line: its margin-left is {key.get('margin-left')!r}, not auto")
        return bad

    @classmethod
    def row_problems(cls, css):
        """A pool's rows: their tools out of the way at rest, a number and not a circle, a dot and a word and not a pill, a line and not a box for a pool of one."""
        base_css, blocks = cls.split(css)
        rules = CssRules.rules(base_css)
        touch = CssRules.rules("\n".join(inner for query, inner in blocks if "hover: none" in query))
        tool, shown = cls.declared(rules, ".pb .pb-row .pb-tool"), cls.declared(rules, ".pb .pb-row:hover .pb-tool")
        grip, rank = cls.declared(rules, ".pb .pb-row [data-pool-grip]"), cls.declared(rules, ".pb-rank")
        status, dot = cls.declared(rules, ".pb-status"), cls.declared(rules, ".pb-row .pb-status:not(.quiet)::before")
        row = cls.declared(rules, ".pb .pb-row")
        one, one_open = cls.declared(rules, ".pb .pb-pool.single .pb-row"), cls.declared(rules, ".pb .pb-pool.single .pb-row.open")
        bad = []
        if tool.get("width") != "0":
            bad.append(f"a row's ✕ keeps room at rest: .pb .pb-row .pb-tool has width {tool.get('width')!r}, not 0 (the model's name is cut for a tool nobody sees)")
        if shown.get("width") != "auto":
            bad.append(f"a row's ✕ takes no room when the row is pointed at: width {shown.get('width')!r}, not auto")
        if cls.declared(touch, ".pb .pb-row .pb-tool").get("width") != "auto":
            bad.append("a row's ✕ cannot be seen where there is no pointer: no @media (hover: none) rule gives it room")
        if grip.get("position") != "absolute":
            bad.append(f"a row's grip keeps room in the row: position {grip.get('position')!r}, not absolute")
        if row.get("box-shadow") != "none":
            bad.append(f"a row has the old pool card's glow ring (modals.css, `.pool-step.serving`) again: box-shadow {row.get('box-shadow')!r}, not none")
        if "border-radius" in rank or "border" in rank or "width" in rank:
            bad.append("a row's rank is a circle again: a number is what the row has")
        if status.get("border") != "0" or status.get("padding") != "0":
            bad.append(f"a row's state is a pill with a frame again: .pb-status has border {status.get('border')!r}, padding {status.get('padding')!r}")
        if dot.get("content") != '""' or dot.get("border-radius") != "50%":
            bad.append("a row's state has no dot before its word")
        if one.get("background") != "none" or one.get("border-color") != "transparent":
            bad.append("a pool of one row has a box again: its row is the line under the name")
        if not one.get("grid-template-columns", "").startswith("minmax(0, 1fr)"):
            bad.append("a pool of one row has a column for a rank: its room goes to the model's name")
        if one_open.get("border-color") in (None, "transparent"):
            bad.append("a row with no cable, in a pool of one, has no place drawn: it is where the cable is to come")
        return bad

    @classmethod
    def problems(cls, css):
        return (cls.tool_problems(css) + cls.line_problems(css) + cls.head_problems(css) + cls.strip_problems(css) + cls.card_problems(css)
                + cls.row_problems(css))


GOOD_CSS = """
.pb-src { padding: 12px 12px 8px; }
.pb-src-head { display: flex; align-items: center; gap: 8px; }
.pb-src-head .pb-src-note { display: inline-flex; flex: none; margin-left: auto; }
.pb-add-model { flex: none; opacity: 0; transition: opacity .12s ease; }
.pb-src:hover .pb-add-model, .pb-src:focus-within .pb-add-model, .pb-src.empty .pb-add-model, .pb-add-model:focus-visible { opacity: 1; }
@media (hover: none) { .pb-add-model { opacity: 1; } }
.pb-model { position: relative; height: 24px; margin: 0 -4px 2px; padding: 0 8px 0 12px; border-radius: 7px; }
.pb-model > .pb-dot.in { left: -16px; }
.pb-model-name { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pb-chips { display: flex; flex: none; gap: 6px; margin-left: auto; }
.pb .pb-model-remove { flex: none; width: 0; margin-left: -6px; padding: 0; overflow: hidden; opacity: 0; }
.pb-model:hover .pb-model-remove, .pb-model:focus-within .pb-model-remove, .pb .pb-model-remove:focus-visible { width: auto; margin-left: 0; padding: 0 4px; opacity: 1; }
@media (hover: none) { .pb .pb-model-remove { width: auto; margin-left: 0; padding: 0 4px; opacity: 1; } }
.pb .pb-sched { flex: none; height: 18px; padding: 0 7px; }
.pb .pb-sched.none, .pb .pb-sched.off { width: 0; margin-left: -6px; padding: 0; overflow: hidden; opacity: 0; }
.pb-model:hover .pb-sched, .pb-model:focus-within .pb-sched, .pb .pb-sched:focus-visible { width: auto; margin-left: 0; padding: 0 4px; opacity: 1; }
@media (hover: none) { .pb .pb-sched { width: auto; margin-left: 0; padding: 0 4px; opacity: 1; } }
.pb-dock-levels .sub-usage-panel { margin: 0; }
.pb-card-grip { position: absolute; left: 0; top: 10px; width: 12px; height: 26px; }
.pb-client > .pb-key { margin-left: auto; }
.pb .pb-row .pb-tool { flex: none; width: 0; margin-left: -8px; padding: 0; overflow: hidden; }
.pb .pb-row:hover .pb-tool, .pb .pb-row:focus-within .pb-tool { width: auto; margin-left: 0; padding: 0 4px; }
@media (hover: none) { .pb .pb-row .pb-tool { width: auto; margin-left: 0; padding: 0 4px; } }
.pb .pb-row { position: relative; display: grid; box-shadow: none; }
.pb .pb-row [data-pool-grip] { position: absolute; left: 1px; top: 0; bottom: 0; width: 9px; }
.pb-rank { color: var(--muted); font-size: 11px; text-align: center; }
.pb-status { display: inline-flex; align-items: center; gap: 6px; padding: 0; border: 0; border-radius: 0; font-size: 11px; }
.pb-row .pb-status:not(.quiet)::before, .pb-dock-step .pb-status:not(.quiet)::before { content: ""; flex: none; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.pb .pb-pool.single .pb-row { grid-template-columns: minmax(0, 1fr) auto auto; height: 22px; padding: 0 12px 0 0; border-color: transparent; background: none; }
.pb .pb-pool.single .pb-row.open { border-color: var(--line); padding: 0 12px 0 10px; }
"""


def without(css, old):
    assert old in css, old
    return css.replace(old, "")


def swapped(css, old, new):
    assert old in css, old
    return css.replace(old, new)


def test_the_rule():
    print("the rule, on its own samples:")
    check(ModelsCss.problems(GOOD_CSS) == [], "sample: a quiet add button, ✕ and ⏱ that take room only when shown, a 24px line, a socket on the edge, no wrap: no remarks")
    loud = swapped(GOOD_CSS, ".pb-add-model { flex: none; opacity: 0;", ".pb-add-model { flex: none; opacity: 1;")
    check(ModelsCss.problems(loud) == ["the ＋ in the card's head is not quiet at rest: .pb-add-model has opacity '1', not 0"],
          "negative: the ＋ model is always lit — named")
    unreachable = swapped(GOOD_CSS, ".pb-src:hover .pb-add-model, ", "")
    check(ModelsCss.problems(unreachable) == ["the ＋ in the card's head stays quiet at .pb-src:hover .pb-add-model: opacity None, not 1"],
          "negative: the pointer on the card does not show the ＋ model — named")
    empty_hidden = swapped(GOOD_CSS, ".pb-src.empty .pb-add-model, ", "")
    check(ModelsCss.problems(empty_hidden) == ["the ＋ in the card's head stays quiet at .pb-src.empty .pb-add-model: opacity None, not 1"],
          "negative: a card with no model shows no ＋ model at rest, and there is no other way to add one — named")
    no_touch = without(GOOD_CSS, "@media (hover: none) { .pb-add-model { opacity: 1; } }\n")
    check(ModelsCss.problems(no_touch) == ["the ＋ in the card's head cannot be seen where there is no pointer: no @media (hover: none) rule shows it"],
          "negative: on a touch screen the ＋ model never shows — named (a rule inside the @media is not read as the rule at rest)")
    roomy = swapped(GOOD_CSS, ".pb .pb-model-remove { flex: none; width: 0;", ".pb .pb-model-remove { flex: none; width: 18px;")
    check(ModelsCss.problems(roomy) == ["a model's ✕ keeps room at rest: .pb .pb-model-remove has width '18px', not 0"],
          "negative: the ✕ holds its room at rest, and a long name loses it — named")
    stuck = swapped(GOOD_CSS, "{ width: auto; margin-left: 0; padding: 0 4px; opacity: 1; }\n@media (hover: none) { .pb .pb-model-remove", "{ opacity: 1; }\n@media (hover: none) { .pb .pb-model-remove")
    check(any(p.startswith("a model's ✕ takes no room at") for p in ModelsCss.problems(stuck)),
          "negative: the ✕ shown but at width 0 — invisible — named")
    sched_loud = swapped(GOOD_CSS, ".pb .pb-sched.none, .pb .pb-sched.off { width: 0; margin-left: -6px; padding: 0; overflow: hidden; opacity: 0; }",
                         ".pb .pb-sched.none, .pb .pb-sched.off { width: 0; margin-left: -6px; padding: 0; overflow: hidden; opacity: .45; }")
    check(len(ModelsCss.problems(sched_loud)) == 2 and all("a model's ⏱ without a schedule is not quiet at rest" in p for p in ModelsCss.problems(sched_loud)),
          "negative: the ⏱ of a model with no schedule is dim, not quiet — named for both of its states, none and off")
    tall = swapped(GOOD_CSS, "height: 24px; margin: 0 -4px 2px;", "height: 34px; margin: 0 -4px 2px;")
    check(ModelsCss.problems(tall) == ["a model's line is '34px' high, not 24px"], "negative: a line of 34px — named")
    hairline = swapped(GOOD_CSS, "border-radius: 7px; }", "border-radius: 7px; border-top: 1px solid #333; }")
    check(ModelsCss.problems(hairline) == ["a model's line has a border again: the lines stand with no hairlines between them"], "negative: a hairline between the lines — named")
    off_edge = swapped(GOOD_CSS, ".pb-model > .pb-dot.in { left: -16px; }", ".pb-model > .pb-dot.in { left: -8px; }")
    check(ModelsCss.problems(off_edge) == ["the socket is not on the card's edge: the line is inset 8px, its socket stands at -8.0, not -16px"],
          "negative: the line is inset 8px and the socket is where it was for a full-width line — named")
    wider = swapped(GOOD_CSS, "margin: 0 -4px 2px;", "margin: 0 -6px 2px;")
    check(ModelsCss.problems(wider) == ["the socket is not on the card's edge: the line is inset 6px, its socket stands at -16.0, not -14px"],
          "negative: the inset changed and the socket was left — named")
    pushed = swapped(GOOD_CSS, "text-overflow: ellipsis; white-space: nowrap; }\n.pb-chips", "white-space: nowrap; }\n.pb-chips")
    check(ModelsCss.problems(pushed) == ["a long name is not cut with an ellipsis: .pb-model-name has text-overflow None, not ellipsis"], "negative: a long name with no ellipsis — named")
    stiff = swapped(GOOD_CSS, ".pb-model-name { flex: 0 1 auto;", ".pb-model-name { flex: 0 0 auto;")
    check(ModelsCss.problems(stiff) == ["a long name does not shrink first: .pb-model-name has flex '0 0 auto', not 0 1 auto"], "negative: the name does not shrink — named")
    squeezed = swapped(GOOD_CSS, ".pb-chips { display: flex; flex: none;", ".pb-chips { display: flex; flex: 0 1 auto;")
    check(ModelsCss.problems(squeezed) == ["the marks shrink: .pb-chips has no `flex: none`, so a long name would take their room and cut their words"],
          "negative: the marks may shrink — named")
    wrap = swapped(GOOD_CSS, ".pb-src-head { display: flex;", ".pb-src-head { display: flex; flex-wrap: wrap;")
    check(ModelsCss.problems(wrap) == ["the head is not one line: display 'flex', flex-wrap 'wrap'"], "negative: a head that wraps — named")
    left = swapped(GOOD_CSS, "flex: none; margin-left: auto; }\n.pb-add-model", "flex: none; }\n.pb-add-model")
    check(ModelsCss.problems(left) == ["the status is not at the right of the head: its margin-left is None, not auto"], "negative: the status beside the name, not at the right — named")
    hidden = GOOD_CSS + ".pb-dock-levels .sub-usage-resets { display: none; }\n"
    check(ModelsCss.problems(hidden) == [".pb-dock-levels .sub-usage-resets hides when the windows reset: the card does not say it any more"],
          "negative: the strip hides the reset times, the card does not say them — nobody does — named")


def test_cards():
    print("the heads' text starts at the card's edge:")
    in_flow = swapped(GOOD_CSS, ".pb-card-grip { position: absolute;", ".pb-card-grip { position: static;")
    check(ModelsCss.problems(in_flow) == ["a card's grip keeps room in the head: .pb-card-grip has position 'static', not absolute"],
          "negative: the grip in the head's flow (20px of empty room before every name) — named")
    key_left = without(GOOD_CSS, ".pb-client > .pb-key { margin-left: auto; }\n")
    check(ModelsCss.problems(key_left) == ["a client's key is not at the right of its first line: its margin-left is None, not auto"],
          "negative: the key beside the client's name, not at the right — named")


def test_rows():
    print("a pool's rows:")
    roomy = swapped(GOOD_CSS, ".pb .pb-row .pb-tool { flex: none; width: 0;", ".pb .pb-row .pb-tool { flex: none; width: 22px;")
    check(ModelsCss.row_problems(roomy) == ["a row's ✕ keeps room at rest: .pb .pb-row .pb-tool has width '22px', not 0 (the model's name is cut for a tool nobody sees)"],
          "negative: the row's ✕ holds 22px at rest — named")
    stuck = swapped(GOOD_CSS, ".pb .pb-row:hover .pb-tool, .pb .pb-row:focus-within .pb-tool { width: auto;", ".pb .pb-row:hover .pb-tool, .pb .pb-row:focus-within .pb-tool { width: 0;")
    check(ModelsCss.row_problems(stuck) == ["a row's ✕ takes no room when the row is pointed at: width '0', not auto"], "negative: the ✕ never shows — named")
    no_touch = without(GOOD_CSS, "@media (hover: none) { .pb .pb-row .pb-tool { width: auto; margin-left: 0; padding: 0 4px; } }\n")
    check(ModelsCss.row_problems(no_touch) == ["a row's ✕ cannot be seen where there is no pointer: no @media (hover: none) rule gives it room"],
          "negative: on a touch screen the ✕ never shows — named")
    grip = swapped(GOOD_CSS, ".pb .pb-row [data-pool-grip] { position: absolute;", ".pb .pb-row [data-pool-grip] { position: static;")
    check(ModelsCss.row_problems(grip) == ["a row's grip keeps room in the row: position 'static', not absolute"], "negative: the grip in the row's flow — named")
    ring = swapped(GOOD_CSS, ".pb .pb-row { position: relative; display: grid; box-shadow: none; }", ".pb .pb-row { position: relative; display: grid; }")
    check(ModelsCss.row_problems(ring) == ["a row has the old pool card's glow ring (modals.css, `.pool-step.serving`) again: box-shadow None, not none"],
          "negative: the glow ring of the main board's old pool card shows on the serving row — named")
    circle = swapped(GOOD_CSS, ".pb-rank { color: var(--muted); font-size: 11px; text-align: center; }", ".pb-rank { color: var(--muted); font-size: 11px; text-align: center; border-radius: 50%; }")
    check(ModelsCss.row_problems(circle) == ["a row's rank is a circle again: a number is what the row has"], "negative: the rank in a circle — named")
    pill = swapped(GOOD_CSS, "gap: 6px; padding: 0; border: 0; border-radius: 0; font-size: 11px; }", "gap: 6px; padding: 1px 7px; border: 1px solid #333; border-radius: 999px; font-size: 11px; }")
    check(ModelsCss.row_problems(pill) == ["a row's state is a pill with a frame again: .pb-status has border '1px solid #333', padding '1px 7px'"], "negative: a pill with a frame — named")
    no_dot = swapped(GOOD_CSS, '.pb-row .pb-status:not(.quiet)::before, .pb-dock-step .pb-status:not(.quiet)::before { content: ""; flex: none;', '.pb-row .pb-status:not(.quiet)::before, .pb-dock-step .pb-status:not(.quiet)::before { content: none; flex: none;')
    check(ModelsCss.row_problems(no_dot) == ["a row's state has no dot before its word"], "negative: a word with no dot — named")
    boxed = swapped(GOOD_CSS, "padding: 0 12px 0 0; border-color: transparent; background: none; }", "padding: 0 12px 0 0; border-color: #333; background: none; }")
    check(ModelsCss.row_problems(boxed) == ["a pool of one row has a box again: its row is the line under the name"], "negative: a pool of one with a framed row — named")
    columns = swapped(GOOD_CSS, ".pb .pb-pool.single .pb-row { grid-template-columns: minmax(0, 1fr) auto auto;", ".pb .pb-pool.single .pb-row { grid-template-columns: 14px minmax(0, 1fr) auto auto;")
    check(ModelsCss.row_problems(columns) == ["a pool of one row has a column for a rank: its room goes to the model's name"], "negative: a pool of one with a rank's column — named")
    lost_place = swapped(GOOD_CSS, ".pb .pb-pool.single .pb-row.open { border-color: var(--line);", ".pb .pb-pool.single .pb-row.open { border-color: transparent;")
    check(ModelsCss.row_problems(lost_place) == ["a row with no cable, in a pool of one, has no place drawn: it is where the cable is to come"],
          "negative: a row with no cable that is drawn as nothing — named")


def test_the_board():
    print("the board (static/css/pool-board.css):")
    css = CSS.read_text(encoding="utf-8")
    bad = ModelsCss.problems(css)
    check(bad == [], "the cards: quiet tools, lines of 24px, the socket on the edge, heads of one line starting at the card's edge" + (f" — {'; '.join(bad)}" if bad else ""))


for fn in (test_the_rule, test_cards, test_rows, test_the_board):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("routing cards css snapshot holds")
