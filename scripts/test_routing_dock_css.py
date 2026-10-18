#!/usr/bin/env python3
"""Value snapshot: Routing's strip is not shown when nothing is pointed at or pinned.

The strip under Routing (pool-dock.js) read "point at a card or click it" when nothing was
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

It also names a stylesheet in which the strip does not stand flush with the foot of the board (1.3.539, made again in 1.3.548).
Since the columns scroll on their own the board's box does not scroll down and keeps no padding at its foot: the strip is its last
child, pulled up over the columns' foot by its own height (a top margin of minus its height), with no margin under it. A padding at
the board's foot floats the strip above the edge, with the board's foot showing under it (1.3.539, the first time); a pull that is not
its height leaves a gap under the columns or pushes the board out past its box.

It names, too, a stylesheet in which a label of the strip's path can wrap (2026-10-14): the labels stood in a column of a fixed 58px, and
"ID (POOLS)", the new name of the pools' column, broke into two lines over the next row. The column is as wide as its longest label
(`fit-content`, up to a limit), a label never wraps (`nowrap`), and one that is too long for the limit is cut with an ellipsis.

Run: python3 scripts/test_routing_dock_css.py
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


class DockCss:
    """What a stylesheet says of the strip (`.pb-dock`) when it is empty."""

    STRIP = re.compile(r"\.pb-dock(?![\w-])")
    EMPTY = re.compile(r'\[data-t-state=["\']?empty["\']?\]')

    @classmethod
    def flush_problems(cls, css):
        """What keeps the strip from standing flush with the board's foot, over the columns' foot."""
        rules = CssRules.rules(css)
        board, strip = {}, {}
        for selector, declarations in rules:
            if selector == ".pb":
                board.update(declarations)
            elif selector == ".pb-dock":
                strip.update(declarations)
        padding = CssRules.sides(board.get("padding", ""))
        margin = CssRules.sides(strip.get("margin", ""))
        height = CssRules.px(strip.get("height", ""))
        if padding is None:
            return ["the board's padding (.pb) is not in px: its foot cannot be measured"]
        if height is None:
            return ["the strip's height (.pb-dock) is not in px: its pull over the columns cannot be measured"]
        bad = []
        if padding[2] != 0:
            bad.append(f"the strip floats off the board's foot: the board keeps {padding[2]:g}px of padding under it")
        if margin is None or margin[0] != -height:
            bad.append(f"the strip does not lie over the columns' foot: its top margin is not minus its height ({-height:g}px)")
        if margin is None or margin[2] != 0:
            bad.append("the strip does not end where the board does: its bottom margin is not 0")
        return bad

    @classmethod
    def route_problems(cls, css):
        """What lets a label of the strip's path wrap or run over: no width of its own, no nowrap, no ellipsis."""
        grid, label = {}, {}
        for selector, declarations in CssRules.rules(css):
            if selector == ".pb-route":
                grid.update(declarations)
            elif selector == ".pb-route dt":
                label.update(declarations)
        bad = []
        if not grid.get("grid-template-columns", "").startswith("fit-content("):
            bad.append("the labels' column does not follow its longest label: grid-template-columns is not fit-content(...)")
        if label.get("white-space") != "nowrap":
            bad.append("a label may wrap into two lines: no white-space: nowrap on .pb-route dt")
        if label.get("overflow") != "hidden" or label.get("text-overflow") != "ellipsis":
            bad.append("a label too long for its column is not cut with an ellipsis")
        return bad

    @classmethod
    def problems(cls, css):
        rules = CssRules.rules(css)
        strip = [(s, d) for s, d in rules if cls.STRIP.search(CssRules.subject(s))]
        empty = [(s, d) for s, d in strip if cls.EMPTY.search(CssRules.subject(s))]
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
.pb { position: relative; padding: 14px 20px 0; }
/* the strip */
.pb-dock { position: sticky; left: 0; height: 156px; margin: -156px -20px 0; transition: visibility 0s linear 0s; }
/* nothing pointed at: no strip, a comma, in a comment */
.pb-dock[data-t-state="empty"] { visibility: hidden; transition-delay: .25s; }
.pb-dock-id { display: flex; }
.pb:has(.pool-ladder.sorting) .pb-dock .pb-turn { display: none; }
.pb-dock-body { column-width: 230px; }"""


ROUTE = """.pb-route { display: grid; grid-template-columns: fit-content(96px) minmax(0, 1fr); column-gap: 8px; }
.pb-route > div { display: contents; }
.pb-route dt, .pb-route dd { height: 16px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pb-route dt { color: gray; text-transform: uppercase; }
.pb-route dd { margin: 0; }"""


def test_route():
    print("колонка подписей пути в полосе — на своих образцах:")
    check(DockCss.route_problems(ROUTE) == [], "колонка по самой длинной подписи, подпись не переносится и режется многоточием — без замечаний")
    fixed = ROUTE.replace("grid-template-columns: fit-content(96px) minmax(0, 1fr);", "grid-template-columns: 58px minmax(0, 1fr);")
    check(DockCss.route_problems(fixed) == ["the labels' column does not follow its longest label: grid-template-columns is not fit-content(...)"],
          "negative: колонка в 58px — «ID (POOLS)» не поместится, названо")
    wraps = ROUTE.replace("white-space: nowrap;", "")
    check(DockCss.route_problems(wraps) == ["a label may wrap into two lines: no white-space: nowrap on .pb-route dt"],
          "negative: без nowrap подпись переносится на вторую строку, названо")
    cut = ROUTE.replace("text-overflow: ellipsis;", "")
    check(DockCss.route_problems(cut) == ["a label too long for its column is not cut with an ellipsis"],
          "negative: без многоточия длинная подпись режется молча, названо")
    other = ROUTE.replace(".pb-route dt, .pb-route dd {", ".pb-route dd {")
    check(len(DockCss.route_problems(other)) == 2, "negative: правило про подпись есть только у dd — nowrap и многоточие у dt не заданы, названы оба")


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
    base = GOOD.replace("position: sticky; left: 0;", "display: none;")
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
    print("the strip flush with the foot of the board — on samples of its own:")
    check(DockCss.flush_problems(GOOD) == [], "the board keeps no padding at its foot and the strip is pulled up by its own height — no remarks")
    floating = GOOD.replace("padding: 14px 20px 0;", "padding: 14px 20px 28px;")
    check(DockCss.flush_problems(floating) == ["the strip floats off the board's foot: the board keeps 28px of padding under it"],
          "negative: 28px of padding at the board's foot — the strip floats above the edge, named")
    short = GOOD.replace("margin: -156px -20px 0;", "margin: -100px -20px 0;")
    check(DockCss.flush_problems(short) == ["the strip does not lie over the columns' foot: its top margin is not minus its height (-156px)"],
          "negative: a pull shorter than the strip — a gap under the columns, named")
    pushed = GOOD.replace("margin: -156px -20px 0;", "margin: 12px -20px 0;")
    check(DockCss.flush_problems(pushed) == ["the strip does not lie over the columns' foot: its top margin is not minus its height (-156px)"],
          "negative: the old top margin — the strip would sit under the columns and push the board out, named")
    lifted = GOOD.replace("margin: -156px -20px 0;", "margin: -156px -20px 12px;")
    check(DockCss.flush_problems(lifted) == ["the strip does not end where the board does: its bottom margin is not 0"],
          "negative: a margin under the strip — it ends above the board's edge, named")
    taller = GOOD.replace("height: 156px;", "height: 180px;")
    check(DockCss.flush_problems(taller) == ["the strip does not lie over the columns' foot: its top margin is not minus its height (-180px)"],
          "negative: the strip grew and its pull did not — named")
    emsize = GOOD.replace("padding: 14px 20px 0;", "padding: 14px 20px 2em;")
    check(DockCss.flush_problems(emsize) == ["the board's padding (.pb) is not in px: its foot cannot be measured"],
          "a padding not in px is said so, not guessed")
    noheight = GOOD.replace("height: 156px; ", "")
    check(DockCss.flush_problems(noheight) == ["the strip's height (.pb-dock) is not in px: its pull over the columns cannot be measured"],
          "a strip with no height in px is said so, not guessed")
    check(CssRules.sides("12px -20px -28px") == [12.0, -20.0, -28.0, -20.0] and CssRules.sides("4px 8px") == [4.0, 8.0, 4.0, 8.0],
          "сокращённая запись: три значения и два раскладываются на четыре стороны")


def test_the_board():
    print("доска (static/css/pool-board.css):")
    bad = DockCss.problems(CSS.read_text(encoding="utf-8"))
    check(bad == [], "пустая полоса спрятана, остаётся в потоке и уходит с задержкой" + (f" — {'; '.join(bad)}" if bad else ""))
    flush = DockCss.flush_problems(CSS.read_text(encoding="utf-8"))
    check(flush == [], "полоса вровень с низом доски" + (f" — {'; '.join(flush)}" if flush else ""))
    route = DockCss.route_problems(CSS.read_text(encoding="utf-8"))
    check(route == [], "подписи пути в полосе в одну строку, колонка по самой длинной" + (f" — {'; '.join(route)}" if route else ""))


for fn in (test_the_rule, test_flush, test_route, test_the_board):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("routing strip css snapshot holds")
