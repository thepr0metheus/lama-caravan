"""Value snapshot: the heads of the main board's columns stand level.

The main board (the owner, 2026-10-14, a screenshot: "the heads of Clients and Machines are two different columns, but they
are not level, as if they were of different classes"): the Machines head started 18px lower than the Clients head. It had a
margin over it, from the days the machines stood under the pools in one column; the column is the board's third now, beside
the clients. And the distance from a title to the first row of buttons under it was 12px in the clients' column and 8px in the
machines'. Since 1.3.578 a column is a head and a body (the owner, 2026-10-18: "the headings outside the area I scroll, shown
always"): the title (`.board-col-title`, the first child of its column) stands over the body that scrolls (`.board-scroll`), and the
distance from the title to the first row is the title's own margin under it and the body's padding over it. Both columns have one
rule for each, so the two heads are the same block by construction; what is left to hold is that no column has a rule of its own
for them. This snapshot reads the stylesheets and names a board in which

  - the two titles do not start on one line: a margin or a padding over one of them that the other does not have;
  - the title is not as far from its first row of buttons in one column as it is in the other: a margin under one title, or a padding
    over one body, that the other column does not have.

Run: python3 scripts/test_board_heads.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STYLES = ROOT / "static" / "css"

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class HeadCss:
    """What a stylesheet says of the titles that open the main board's first and third columns, and of the bodies under them."""

    BOARD = 'html:not([data-board-view="machine"])'
    TITLE = ".board-col-title"
    BODY = f"{BOARD} .topology-board .board-scroll"
    # the rules a column could have of its own, over the shared ones
    CLIENTS_TITLE = (".topology-column > .board-col-title", f"{BOARD} .topology-column > .board-col-title", f"{BOARD} .topology-board .topology-column > .board-col-title")
    CLIENTS_BODY = (".topology-column > .board-scroll", f"{BOARD} .topology-column > .board-scroll", f"{BOARD} .topology-board .topology-column > .board-scroll")
    LANE_TITLE = (".lane-servers > .board-col-title", f"{BOARD} .lane-servers > .board-col-title", f"{BOARD} .topology-board .lane-servers > .board-col-title")
    LANE_BODY = (".lane-servers > .board-scroll", f"{BOARD} .lane-servers > .board-scroll", f"{BOARD} .topology-board .lane-servers > .board-scroll")

    @classmethod
    def side(cls, rules, selector, name, index):
        """One side of a box (`margin` or `padding`; index 0 top, 2 bottom) as the last rule of the selector leaves it, in px (0 if none)."""
        value = 0.0
        for sel, declarations in rules:
            if sel != selector:
                continue
            if f"{name}-{('top', 'right', 'bottom', 'left')[index]}" in declarations:
                value = CssRules.px(declarations[f"{name}-{('top', 'right', 'bottom', 'left')[index]}"]) or 0.0
            elif name in declarations:
                value = (CssRules.sides(declarations[name]) or [0.0] * 4)[index]
        return value

    @classmethod
    def declares(cls, rules, selector, name, index):
        """Whether a rule of this selector says one side of a box, longhand or shorthand."""
        longhand = f"{name}-{('top', 'right', 'bottom', 'left')[index]}"
        return any(sel == selector and (longhand in declarations or name in declarations) for sel, declarations in rules)

    @classmethod
    def cascade(cls, rules, selectors, name, index):
        """One side of a box as the last of these selectors (from the general to the narrow) that says it leaves it, in px (0 if none does):
        a column's own rule replaces the shared one, as it does in the page."""
        value = 0.0
        for selector in selectors:
            if cls.declares(rules, selector, name, index):
                value = cls.side(rules, selector, name, index)
        return value

    @classmethod
    def column(cls, css, titles, bodies):
        """(over the title, title to the first row) of a column: the shared title's and body's rules, and the column's own over them."""
        rules = CssRules.rules(css)
        title_rules, body_rules = (cls.TITLE, *titles), (cls.BODY, *bodies)
        top = sum(cls.cascade(rules, title_rules, n, 0) for n in ("margin", "padding"))
        gap = cls.cascade(rules, title_rules, "margin", 2) + cls.cascade(rules, body_rules, "padding", 0)
        return top, gap

    @classmethod
    def clients(cls, css):
        return cls.column(css, cls.CLIENTS_TITLE, cls.CLIENTS_BODY)

    @classmethod
    def machines(cls, css):
        return cls.column(css, cls.LANE_TITLE, cls.LANE_BODY)

    @classmethod
    def problems(cls, css):
        (c_top, c_gap), (m_top, m_gap) = cls.clients(css), cls.machines(css)
        bad = []
        if c_top != m_top:
            bad.append(f"the titles do not start on one line: {c_top:g}px over the clients' title, {m_top:g}px over the machines'")
        if c_gap != m_gap:
            bad.append(f"the titles are not as far from their first row of buttons: {c_gap:g}px under the clients' title, {m_gap:g}px under the machines'")
        return bad


GOOD_CSS = """.board-col-title { padding: 0 2px; height: 28px; }
.board-col-title h2 { margin: 0; }
html:not([data-board-view="machine"]) .topology-board .board-scroll { padding-top: 6px; padding-inline: var(--board-col-room); }
html:not([data-board-view="machine"]) .lane-servers .providers-title { margin-top: 18px; margin-bottom: 8px; }
html[data-board-view="machine"] .machines-head { margin-top: 0; justify-content: flex-end; }"""

LANE = 'html:not([data-board-view="machine"]) .lane-servers > .board-col-title'
LANE_BODY = 'html:not([data-board-view="machine"]) .lane-servers > .board-scroll'
CLIENTS_BODY = 'html:not([data-board-view="machine"]) .topology-column > .board-scroll'


def test_the_rule():
    print("правило — на своих образцах:")
    check(HeadCss.clients(GOOD_CSS) == (0.0, 6.0) and HeadCss.machines(GOOD_CSS) == (0.0, 6.0),
          "образец: над обоими названиями нет отступа, от названия до первого ряда одно и то же (6px паддинга тела — у обеих колонок одно правило)")
    check(HeadCss.problems(GOOD_CSS) == [], "образец без замечаний")
    over = GOOD_CSS + f"\n{LANE} {{ margin-top: 18px; }}"
    check(HeadCss.problems(over) == ["the titles do not start on one line: 0px over the clients' title, 18px over the machines'"],
          "negative: отступ 18px над названием «Machines» — названо (так было до 1.3.540)")
    pad = GOOD_CSS + "\n.board-col-title { padding-top: 6px; }"
    check(HeadCss.problems(pad) == [], "названия — один и тот же блок: padding над ним у обоих, поровну — замечаний нет")
    lane_pad = GOOD_CSS + f"\n{LANE} {{ padding-top: 6px; }}"
    check(HeadCss.problems(lane_pad) == ["the titles do not start on one line: 0px over the clients' title, 6px over the machines'"],
          "negative: padding над названием «Machines» одним — тоже названо")
    shorthand = GOOD_CSS + f"\n{LANE} {{ margin: 10px 0 0; }}"
    check(HeadCss.problems(shorthand) == ["the titles do not start on one line: 0px over the clients' title, 10px over the machines'"],
          "negative: отступ сверху в сокращённой записи margin — читается и называется")
    clients_over = GOOD_CSS.replace(".board-col-title { padding: 0 2px;", ".board-col-title { margin: 5px 0 0; padding: 0 2px;")
    check(HeadCss.clients(clients_over)[0] == 5.0 and HeadCss.machines(clients_over)[0] == 5.0 and HeadCss.problems(clients_over) == [],
          "названия — один блок: отступ, общий для обоих, считается у обоих поровну — замечаний нет")
    tight = GOOD_CSS + f"\n{LANE} {{ margin-bottom: 8px; }}"
    check(HeadCss.problems(tight) == ["the titles are not as far from their first row of buttons: 6px under the clients' title, 14px under the machines'"],
          "negative: у названия «Machines» свой отступ снизу 8px — расстояние до кнопок 14px против 6px у «Clients» — названо")
    body_own = GOOD_CSS + f"\n{LANE_BODY} {{ padding-top: 14px; }}"
    check(HeadCss.problems(body_own) == ["the titles are not as far from their first row of buttons: 6px under the clients' title, 14px under the machines'"],
          "negative: у тела колонки машин свой паддинг сверху — первый ряд ниже, чем у клиентов — названо")
    clients_body = GOOD_CSS + f"\n{CLIENTS_BODY} {{ padding-top: 0; }}"
    check(HeadCss.problems(clients_body) == ["the titles are not as far from their first row of buttons: 0px under the clients' title, 6px under the machines'"],
          "negative: у тела колонки клиентов свой паддинг (0) — расстояние до кнопок другое — названо")
    check(HeadCss.problems(GOOD_CSS.replace("padding-top: 6px;", "padding-top: 10px;")) == [],
          "общее правило тела меняет расстояние у обеих колонок поровну — замечаний нет")
    check(HeadCss.problems(GOOD_CSS + '\nhtml[data-board-view="machine"] .machines-head { margin-top: 18px; }') == [],
          "окно одной машины — своя шапка (margin-top: 0 там и нужен): правило с префиксом окна машины в счёт не идёт")
    check(HeadCss.problems(GOOD_CSS + "\n.providers-title { margin-top: 30px; }") == [],
          "название «Cloud providers» стоит внутри тела, под машинами, и названием колонки не считается: его отступ с «Machines» не сравнивают")


def test_the_board():
    print("доска (static/css):")
    css = "\n".join(path.read_text(encoding="utf-8") for path in sorted(STYLES.glob("*.css")))
    bad = HeadCss.problems(css)
    check(bad == [], "головы «Clients» и «Machines» на одной линии, от названия до кнопок поровну" + (f" — {'; '.join(bad)}" if bad else ""))


for fn in (test_the_rule, test_the_board):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("board heads snapshot holds")
