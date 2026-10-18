#!/usr/bin/env python3
"""Value snapshot: the main board keeps a way into the caravan's two model pages, in the head of Machines.

/models (the models in the caravan's folder) and /hf (Hugging Face, to download more) had their links on each
machine's caravan strip. The strip left the main board for the machine's window (1.3.472), and the links went with
it: from the main board neither page could be reached, and nothing said so (the owner, 2026-10-12: "the way into
them is lost"). They stood in the head of Machines then, among the board's tools; under Routing's card from
1.3.537 (2026-10-14: "move these two buttons somewhere more fitting"); and since 1.3.540 they stand in the head of
Machines again, as two wide buttons of the Add scout kind, a row of their own over the scouts' buttons (the owner,
2026-10-14). This snapshot names

  - a page whose link is gone, or that opens in a tab of its own again (it opens in THIS tab: the owner, 2026-10-17,
    "new screens open in a new tab, remove that");
  - a pair that does not stand in the head of Machines, in a row between the title and the scouts' buttons;
  - a pair drawn a second time, by the script (Routing's card drew it from 1.3.537 to 1.3.539);
  - a pair that is not a row of its own, or whose buttons do not share the Add scout look, in one rule;
  - a style that hides a link on the main board as well as in a machine's own window — and a machine's window that
    does not hide the row (its caravan strip has the same two links).

Run: python3 scripts/test_board_model_pages.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "static" / "index.html"
STYLES = ROOT / "static" / "css"
SCRIPTS = ROOT / "static" / "js"

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class BoardEntries:
    """What the main board's page and styles say of the way into the two model pages."""

    LINKS = {"/models": "board-models-open", "/hf": "board-hf-open"}
    HEAD = re.compile(r'<div class="topology-lane-head machines-head">')
    PAIR = re.compile(r'<div class="board-pages"[^>]*data-t="board-pages"[^>]*>(?P<body>.*?)</div>', re.S)
    ACTIONS = re.compile(r'<div class="topology-head-actions">')
    # The title is a block of its own over the head: since 1.3.578 it stands over the body that scrolls (`.board-col-body`, which holds the head
    # and the rest of the column's tools and cards), so the body's opening tag may stand between the title and the head.
    TITLE = re.compile(r'<div class="board-col-title"><h2[^>]*>(?:(?!</h2>).)*</h2></div>\s*(?:<div class="board-col-body[^"]*">\s*)?$', re.S)
    ANCHOR = re.compile(r"<a [^>]*>", re.S)
    MACHINE_ONLY = 'html[data-board-view="machine"]'
    # One look for the head's wide buttons: the Add scout button and the two page buttons are in one rule.
    LOOK_SCOUT = ".topology-head-actions > .icon-action.prominent.topology-head-add"
    LOOK_PAGES = ".board-pages > .icon-action.prominent.board-page-link"

    @classmethod
    def page_problems(cls, html):
        """What is wrong with the pair in the page: its place, its links."""
        head = cls.HEAD.search(html)
        pair = cls.PAIR.search(html)
        if not head or not pair:
            return ["no pair of page links (div.board-pages) in the head of Machines"]
        bad = []
        actions = cls.ACTIONS.search(html, head.end())
        title = cls.TITLE.search(html[:head.start()])
        if not (title and actions and head.end() < pair.start() < actions.start()):
            bad.append("the pair does not stand in the head of Machines between its title and the scouts' buttons")
        links = cls.ANCHOR.findall(pair.group("body"))
        for href, hook in cls.LINKS.items():
            link = next((a for a in links if f'href="{href}"' in a), None)
            if link is None:
                bad.append(f"no link to {href} in the pair")
                continue
            if "↗" in pair.group("body") or "board-page-arrow" in pair.group("body"):
                bad.append("the pair carries an arrow ↗, which promises a tab of its own: the pages open in this tab")
                break
            if "target=" in link:
                bad.append(f"the link to {href} opens in a tab of its own (it carries a target): the caravan's screens open in this tab")
            if f'data-t="{hook}"' not in link:
                bad.append(f"the link to {href} has no hook {hook}")
            if "data-title-i18n=" not in link:
                bad.append(f"the link to {href} says nothing in its hover")
            if "icon-action prominent" not in link:
                bad.append(f"the link to {href} is not a button of the head's kind (icon-action prominent)")
        if html.count('href="/models"') != 1 or html.count('href="/hf"') != 1:
            bad.append("a page is linked from the page more than once, or not at all: the pair has one home")
        return bad

    @staticmethod
    def drawn_by_script(js_files):
        """Files of the page's script that still draw the pair, which the page now holds in its head."""
        return sorted(name for name, text in js_files.items()
                      if re.search(r"renderBoardPageLinks|board-pages|boardModelsLink|boardHfLink", text))

    @classmethod
    def css_problems(cls, css):
        """What keeps the pair from being two wide buttons of the Add scout look, a row of their own."""
        rules = CssRules.rules(css)
        row = {}
        for selector, declarations in rules:
            if selector == ".board-pages":
                row.update(declarations)
        bad = []
        if row.get("display") != "flex":
            bad.append("the pair is not a flex row (.board-pages display: flex)")
        if not row.get("flex", "").endswith("100%"):
            bad.append("the pair is not a row of its own: .board-pages has no flex: 1 1 100%")
        # The rule with both selectors is ONE rule: its declarations are one dict, shared by its selectors.
        shared = [d for s, d in rules if s == cls.LOOK_PAGES and any(s2 == cls.LOOK_SCOUT and d2 is d for s2, d2 in rules)]
        if not shared:
            bad.append("the page buttons do not share the Add scout rule (the look is in two places)")
        # The shared rule says `flex: 1 1 auto`; the buttons are halves of the row by the last word on their own flex.
        effective = ""
        for selector, declarations in rules:
            if selector == cls.LOOK_PAGES and "flex" in declarations:
                effective = declarations["flex"]
        if not effective.startswith("1 1 0"):
            bad.append("the two buttons are not halves of the row (flex: 1 1 0)")
        return bad

    @classmethod
    def hidden_on_main(cls, css):
        """Selectors that hide the pair or a link on the main board too, one per selector of the rule."""
        bad = []
        for selector, declarations in CssRules.rules(css):
            if re.search(r"\.board-page(?:s|-link)\b", selector) and declarations.get("display") == "none" \
                    and not selector.startswith(cls.MACHINE_ONLY):
                bad.append(selector)
        return bad

    @classmethod
    def machine_window_hides(cls, css):
        """Whether a machine's own window hides the row (its caravan strip has the same two links)."""
        return any(selector.startswith(cls.MACHINE_ONLY) and ".board-pages" in selector and declarations.get("display") == "none"
                   for selector, declarations in CssRules.rules(css))


PAGE = """<div class="board-col-title"><h2 class="title-with-tip"><span id="boardMachinesHead">Machines</span></h2></div>
<div class="board-col-body board-scroll">
<div class="topology-lane-head machines-head">
  <!-- the pair -->
  <div class="board-pages" data-t="board-pages">
    <a id="boardModelsLink" class="icon-action prominent board-page-link" href="/models"
       data-t="board-models-open" data-title-i18n="modelsPageSub"><span>Models</span></a>
    <a id="boardHfLink" class="icon-action prominent board-page-link" href="/hf"
       data-t="board-hf-open" data-title-i18n="hfBrowserTitle"><span>Hugging Face</span></a>
  </div>
  <div class="topology-head-actions"><button>Add scout</button></div>
</div>
</div>"""

SHARED = """.topology-head-actions > .icon-action.prominent.topology-head-add,
.board-pages > .icon-action.prominent.board-page-link { flex: 1 1 auto; padding: 0 14px; font-size: 13px; }"""
HALVES = ".board-pages > .icon-action.prominent.board-page-link { flex: 1 1 0; display: inline-flex; }"
ROW = ".board-pages { display: flex; gap: 8px; flex: 1 1 100%; min-width: 0; }"
MACHINE = """html[data-board-view="machine"] .machines-head [data-scout-add-open],
html[data-board-view="machine"] .machines-head .board-pages { display: none; }"""
CSS = "/* the pair, a comma, in a comment */\n" + "\n".join((SHARED, ROW, HALVES, MACHINE))

JS = {"routers.js": "export function renderTopologyRouterCard() {}", "topology-render.js": "const x = `<div class=\"router-stack\">${cards}</div>`;"}


def test_the_rule():
    print("правило — на своих образцах:")
    check(BoardEntries.page_problems(PAGE) == [], "пара в шапке «Machines», между названием и кнопками скаутов, обе ссылки на месте — без замечаний")
    check(BoardEntries.page_problems(PAGE.replace('href="/hf"', 'href="/routing"')) == ["no link to /hf in the pair",
                                                                                      "a page is linked from the page more than once, or not at all: the pair has one home"],
          "negative: ссылки на /hf нет — названа /hf (и дома у страницы больше нет)")
    check(BoardEntries.page_problems(PAGE.replace('href="/models"', 'href="/routing"'))[0] == "no link to /models in the pair",
          "negative: ссылки на /models нет — названа /models")
    check(BoardEntries.page_problems(PAGE.replace('href="/models"\n       data-t', 'href="/models" target="_blank" rel="noopener"\n       data-t'))
          == ["the link to /models opens in a tab of its own (it carries a target): the caravan's screens open in this tab"],
          "negative: страница /models открывается в новой вкладке — названо (она открывается в этой же)")
    check(BoardEntries.page_problems(PAGE.replace('href="/hf"\n       data-t', 'href="/hf" target="caravan-hf"\n       data-t'))
          == ["the link to /hf opens in a tab of its own (it carries a target): the caravan's screens open in this tab"],
          "negative: страница /hf уходит в окно с именем — тоже названо: любой target, не только _blank")
    check(BoardEntries.page_problems(PAGE.replace("<span>Models</span>", '<span>Models</span> <span class="board-page-arrow" aria-hidden="true">↗</span>'))
          == ["the pair carries an arrow ↗, which promises a tab of its own: the pages open in this tab"],
          "negative: у кнопки вернулась стрелка ↗ — она обещает новую вкладку, названо")
    check(BoardEntries.page_problems(PAGE.replace('data-t="board-hf-open"', 'data-t="x"')) == ["the link to /hf has no hook board-hf-open"],
          "negative: у ссылки на /hf нет хука для тестов — названо")
    check(BoardEntries.page_problems(PAGE.replace(' data-title-i18n="hfBrowserTitle"', "")) == ["the link to /hf says nothing in its hover"],
          "negative: у ссылки на /hf нет подсказки — названо")
    check(BoardEntries.page_problems(PAGE.replace("icon-action prominent board-page-link", "board-page-link", 1))
          == ["the link to /models is not a button of the head's kind (icon-action prominent)"],
          "negative: ссылка на /models не кнопка того же вида, что «Add scout» — названо")
    check(BoardEntries.page_problems(PAGE.replace('<div class="board-pages" data-t="board-pages">', '<div class="board-pages" data-t="board-pages">', 1)
                                     .replace("  <!-- the pair -->\n", "")) == [],
          "комментарий перед парой ничего не меняет")
    check(BoardEntries.page_problems(PAGE.replace('<div class="board-col-title"><h2 class="title-with-tip"><span id="boardMachinesHead">Machines</span></h2></div>\n', "")
                                     + "\n<h2>Machines</h2>") != [],
          "negative: пара стоит раньше названия шапки — названо")
    check(BoardEntries.page_problems(PAGE.replace('</h2></div>\n<div class="board-col-body board-scroll">\n<div class="topology-lane-head',
                                                  '</h2></div>\n<div class="board-col-body board-scroll">\n<div class="x"></div>\n<div class="topology-lane-head')) != [],
          "negative: между названием и шапкой встало что-то третье — название уже не над самой шапкой — названо")
    swapped = PAGE.replace('<div class="topology-head-actions"><button>Add scout</button></div>', "").replace(
        '<div class="board-pages"', '<div class="topology-head-actions"><button>Add scout</button></div>\n  <div class="board-pages"', 1)
    check(any("does not stand in the head of Machines" in p for p in BoardEntries.page_problems(swapped)),
          "negative: пара под кнопками скаутов, не над ними — названо")
    check(BoardEntries.page_problems("<div>no head</div>") == ["no pair of page links (div.board-pages) in the head of Machines"],
          "negative: шапки нет совсем — сказано, а не принято за «всё хорошо»")
    twice = PAGE + '\n<a href="/models">again</a>'
    check("a page is linked from the page more than once, or not at all: the pair has one home" in BoardEntries.page_problems(twice),
          "negative: вторая ссылка на /models где-то ещё на странице — названо (у пары один дом)")

    check(BoardEntries.drawn_by_script(JS) == [], "скрипт пару не рисует")
    check(BoardEntries.drawn_by_script({**JS, "topology-render.js": JS["topology-render.js"] + " renderBoardPageLinks()"}) == ["topology-render.js"],
          "negative: карточка Маршрутизации рисует пару и скриптом — названа (она рисовала её с 1.3.537)")
    check(BoardEntries.drawn_by_script({**JS, "x.js": '`<div class="board-pages">`'}) == ["x.js"], "negative: скрипт рисует свой div.board-pages — назван")

    check(BoardEntries.css_problems(CSS) == [], "ряд из двух кнопок на всю ширину, общий вид с «Add scout» в одном правиле — без замечаний")
    check("the pair is not a row of its own: .board-pages has no flex: 1 1 100%" in BoardEntries.css_problems(CSS.replace("flex: 1 1 100%;", "")),
          "negative: пара не занимает ряд целиком — названо")
    check(BoardEntries.css_problems(CSS.replace("display: flex; gap", "gap")) == ["the pair is not a flex row (.board-pages display: flex)"],
          "negative: пара не flex-ряд — названо")
    split = CSS.replace(".topology-head-actions > .icon-action.prominent.topology-head-add,\n", "")
    check("the page buttons do not share the Add scout rule (the look is in two places)" in BoardEntries.css_problems(split),
          "negative: вид кнопок страниц описан отдельно от «Add scout» — названо (один факт в двух местах)")
    check(BoardEntries.css_problems(CSS.replace(HALVES, "")) == ["the two buttons are not halves of the row (flex: 1 1 0)"],
          "negative: у кнопок нет своего «flex: 1 1 0», остаётся «1 1 auto» общего правила — ширина по тексту, не половины ряда, названо")
    first = CSS.replace(HALVES, "").replace(SHARED, HALVES + "\n" + SHARED, 1)
    check(BoardEntries.css_problems(first) == ["the two buttons are not halves of the row (flex: 1 1 0)"],
          "negative: «flex: 1 1 0» стоит раньше общего правила и проигрывает ему по порядку — названо")

    check(BoardEntries.hidden_on_main(CSS) == [], "пара скрыта только в окне машины")
    loose = CSS.replace('html[data-board-view="machine"] .machines-head .board-pages', ".machines-head .board-pages")
    check(BoardEntries.hidden_on_main(loose) == [".machines-head .board-pages"], "negative: правило прячет пару и на главной доске — названо")
    one = CSS + "\n.board-pages > .board-page-link + .board-page-link { display:none }"
    check(BoardEntries.hidden_on_main(one) == [".board-pages > .board-page-link + .board-page-link"],
          "negative: правило прячет одну ссылку на главной доске — названо")
    check(BoardEntries.machine_window_hides(CSS), "окно машины ряд прячет: у его полосы каравана те же две ссылки")
    check(not BoardEntries.machine_window_hides(loose), "negative: окно машины ряд не прячет — ссылки стояли бы дважды, названо")


def test_the_board():
    print("главная доска (static/index.html, static/js, static/css):")
    html = INDEX.read_text(encoding="utf-8")
    bad = BoardEntries.page_problems(html)
    check(bad == [], "две ссылки — в шапке «Machines», рядом с «Add scout», как кнопки" + (f" — {'; '.join(bad)}" if bad else ""))
    scripts = {path.name: path.read_text(encoding="utf-8") for path in sorted(SCRIPTS.glob("*.js"))}
    drawn = BoardEntries.drawn_by_script(scripts)
    check(drawn == [], f"скрипт страницы пару не рисует {drawn if drawn else ''}".rstrip())
    css = "\n".join(path.read_text(encoding="utf-8") for path in sorted(STYLES.glob("*.css")))
    bad = BoardEntries.css_problems(css)
    check(bad == [], "два широких ряда: «Models» и «Hugging Face» — свой ряд, общий вид с «Add scout»" + (f" — {'; '.join(bad)}" if bad else ""))
    hidden = [f"{path.name}: {sel}" for path in sorted(STYLES.glob("*.css")) for sel in BoardEntries.hidden_on_main(path.read_text(encoding="utf-8"))]
    check(hidden == [], f"ни одно правило не прячет их на главной доске {hidden if hidden else ''}".rstrip())
    check(BoardEntries.machine_window_hides(css), "окно машины пару прячет")


for fn in (test_the_rule, test_the_board):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("board model pages snapshot holds")
