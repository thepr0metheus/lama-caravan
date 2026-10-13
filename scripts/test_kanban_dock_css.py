#!/usr/bin/env python3
"""Value snapshot: the kanban's strip is not shown when nothing is pointed at or pinned.

The strip under the kanban (pool-dock.js) read "point at a card or click it" when nothing was
pointed at, and stood over the foot of the board all the time. The owner, 2026-10-14: "do not show
the bottom strip when nothing is pointed at or selected". The board marks the idle strip
`data-t-state="empty"` (test_js_pool_board.py pins that, and that the strip is `inert` unless it is
pinned); what turns the mark into a hidden strip is one rule of static/css/pool-board.css, and it is
easy to lose or to bend: this snapshot names a stylesheet in which

  - no rule hides the empty strip (`visibility: hidden`);
  - the empty strip is taken out of the layout (`display: none`): the board would be shorter by its
    height, and one scrolled to its end would jump when the strip goes;
  - the empty strip goes at once: the pointer crossing the gap between two cards would flash it, so
    it goes a moment late (`transition-delay`, a delay and not an animation: the owner took the
    animation of a card's reveal out in 1.3.350).

It also names a stylesheet in which the strip does not stand flush with the foot of the board (1.3.539): a sticky box keeps
to the scrollport less its padding, the board (`.pb`) has some at its foot, and the strip gives it back — its `bottom` and its
bottom margin are minus that padding. With `bottom: 0` the strip floated 28px above the edge, with the board's foot showing
under it.

Run: python3 scripts/test_kanban_dock_css.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "static" / "css" / "pool-board.css"

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class DockCss:
    """What a stylesheet says of the strip (`.pb-dock`) when it is empty."""

    STRIP = re.compile(r"\.pb-dock(?![\w-])")
    EMPTY = re.compile(r'\[data-t-state=["\']?empty["\']?\]')
    RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")

    @classmethod
    def rules(cls, css):
        """(selector, {property: value}) for each selector of each rule, comments left out."""
        found = []
        for head, body in cls.RULE.findall(re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
            declarations = {}
            for part in body.split(";"):
                if ":" in part:
                    name, _, value = part.partition(":")
                    declarations[name.strip().lower()] = value.strip().lower()
            for selector in head.split(","):
                found.append((selector.strip(), declarations))
        return found

    @classmethod
    def subject(cls, selector):
        """The last compound of a selector — the element the rule is about: `.pb .pb-dock .pb-turn` is about `.pb-turn`."""
        masked = re.sub(r"\([^()]*\)|\[[^\]]*\]", lambda m: "_" * len(m.group(0)), selector)
        ends = [m.end() for m in re.finditer(r"[\s>+~]+", masked)]
        return selector[ends[-1]:] if ends else selector

    @staticmethod
    def sides(value):
        """top, right, bottom, left of a shorthand like `12px -20px -28px`, in px; None for a value that is not in px."""
        parts = value.split()
        if not parts or len(parts) > 4:
            return None
        parts = {1: parts * 4, 2: parts * 2, 3: parts + [parts[1]], 4: parts}[len(parts)]
        try:
            return [float(re.fullmatch(r"(-?[\d.]+)(?:px)?", p).group(1)) for p in parts]
        except (AttributeError, ValueError):
            return None

    @classmethod
    def flush_problems(cls, css):
        """What keeps the strip from standing flush with the board's foot."""
        rules = cls.rules(css)
        board, strip = {}, {}
        for selector, declarations in rules:
            if selector == ".pb":
                board.update(declarations)
            elif selector == ".pb-dock":
                strip.update(declarations)
        padding = cls.sides(board.get("padding", ""))
        margin = cls.sides(strip.get("margin", ""))
        if padding is None:
            return ["the board's padding (.pb) is not in px: its foot cannot be given back"]
        owed = -padding[2]
        bad = []
        try:
            bottom = float(re.fullmatch(r"(-?[\d.]+)(?:px)?", strip.get("bottom", "")).group(1))
        except (AttributeError, ValueError):
            bottom = None
        if bottom != owed:
            bad.append(f"the strip floats off the board's foot: its bottom is {strip.get('bottom', 'not set')}, not {owed:g}px")
        if margin is None or margin[2] != owed:
            bad.append(f"the strip does not end where the board's content does: its bottom margin is not {owed:g}px")
        return bad

    @classmethod
    def problems(cls, css):
        rules = cls.rules(css)
        strip = [(s, d) for s, d in rules if cls.STRIP.search(cls.subject(s))]
        empty = [(s, d) for s, d in strip if cls.EMPTY.search(cls.subject(s))]
        said = {}
        for _, declarations in empty:
            said.update(declarations)
        bad = []
        if said.get("visibility") != "hidden":
            bad.append("no rule hides the empty strip: visibility: hidden")
        if any(d.get("display") == "none" for _, d in strip):
            bad.append("the strip is taken out of the layout with display: none, so the board changes its height when the strip comes and goes")
        delay = said.get("transition-delay", "")
        match = re.match(r"([\d.]+)(m?s)$", delay)
        if not match or float(match.group(1)) <= 0:
            bad.append("the empty strip goes at once: no transition-delay on its rule")
        return bad


GOOD = """/* the board */
.pb { position: relative; padding: 14px 20px 28px; }
/* the strip */
.pb-dock { position: sticky; bottom: -28px; margin: 12px -20px -28px; transition: visibility 0s linear 0s; }
/* nothing pointed at: no strip, a comma, in a comment */
.pb-dock[data-t-state="empty"] { visibility: hidden; transition-delay: .25s; }
.pb-dock-id { display: flex; }
.pb:has(.pool-ladder.sorting) .pb-dock .pb-turn { display: none; }
.pb-dock-body { column-width: 230px; }"""


def test_the_rule():
    print("правило — на своих образцах:")
    check(DockCss.problems(GOOD) == [], "таблица, где пустая полоса спрятана с задержкой и остаётся в потоке, — без замечаний")
    bare = GOOD.replace('.pb-dock[data-t-state="empty"] { visibility: hidden; transition-delay: .25s; }', "")
    check(DockCss.problems(bare) == ["no rule hides the empty strip: visibility: hidden",
                                     "the empty strip goes at once: no transition-delay on its rule"],
          "negative: правила для пустой полосы нет — названо, что её никто не прячет")
    shown = GOOD.replace("visibility: hidden", "visibility: visible")
    check("no rule hides the empty strip: visibility: hidden" in DockCss.problems(shown),
          "negative: пустая полоса видима — названо")
    gone = GOOD.replace("visibility: hidden;", "display: none;")
    check(any("display: none" in p for p in DockCss.problems(gone)), "negative: display: none на пустой полосе — названо (доска меняет высоту)")
    base = GOOD.replace("position: sticky; bottom: -28px;", "display: none;")
    check(any("display: none" in p for p in DockCss.problems(base)), "negative: display: none на самой полосе — названо")
    quick = GOOD.replace("transition-delay: .25s;", "transition-delay: 0s;")
    check(DockCss.problems(quick) == ["the empty strip goes at once: no transition-delay on its rule"],
          "negative: без задержки (0s) — названо: указатель, переходящий через щель между карточками, мигал бы полосой")
    ms = GOOD.replace("transition-delay: .25s;", "transition-delay: 250ms;")
    check(DockCss.problems(ms) == [], "задержка в миллисекундах — тоже задержка")
    inside = GOOD + "\n.pb-dock .pb-dock-foot { display: none; }"
    check(DockCss.problems(inside) == [], "правило про то, что стоит внутри полосы (.pb-dock .pb-dock-foot), — не про полосу: display: none там не в счёт")
    other = GOOD.replace('.pb-dock[data-t-state="empty"]', '.pb-dock-id[data-t-state="empty"]')
    check("no rule hides the empty strip: visibility: hidden" in DockCss.problems(other),
          "negative: правило про другой элемент (.pb-dock-id) полосу не прячет")


def test_flush():
    print("полоса вровень с низом доски — на своих образцах:")
    check(DockCss.flush_problems(GOOD) == [], "bottom и нижнее поле полосы возвращают нижний отступ доски — без замечаний")
    floating = GOOD.replace("bottom: -28px;", "bottom: 0;")
    check(DockCss.flush_problems(floating) == ["the strip floats off the board's foot: its bottom is 0, not -28px"],
          "negative: bottom: 0 — полоса висит над краем, названо")
    short = GOOD.replace("margin: 12px -20px -28px;", "margin: 12px -20px 0;")
    check(DockCss.flush_problems(short) == ["the strip does not end where the board's content does: its bottom margin is not -28px"],
          "negative: нижнее поле не возвращает отступ — названо")
    wider = GOOD.replace("padding: 14px 20px 28px;", "padding: 14px 20px 40px;")
    check(len(DockCss.flush_problems(wider)) == 2, "negative: отступ доски вырос, а полоса осталась — названы оба расхождения")
    emsize = GOOD.replace("padding: 14px 20px 28px;", "padding: 14px 20px 2em;")
    check(DockCss.flush_problems(emsize) == ["the board's padding (.pb) is not in px: its foot cannot be given back"],
          "отступ не в px — так и сказано, а не догадка")
    check(DockCss.sides("12px -20px -28px") == [12.0, -20.0, -28.0, -20.0] and DockCss.sides("4px 8px") == [4.0, 8.0, 4.0, 8.0],
          "сокращённая запись: три значения и два раскладываются на четыре стороны")


def test_the_board():
    print("доска (static/css/pool-board.css):")
    bad = DockCss.problems(CSS.read_text(encoding="utf-8"))
    check(bad == [], "пустая полоса спрятана, остаётся в потоке и уходит с задержкой" + (f" — {'; '.join(bad)}" if bad else ""))
    flush = DockCss.flush_problems(CSS.read_text(encoding="utf-8"))
    check(flush == [], "полоса вровень с низом доски" + (f" — {'; '.join(flush)}" if flush else ""))


for fn in (test_the_rule, test_flush, test_the_board):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("kanban strip css snapshot holds")
