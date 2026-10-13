#!/usr/bin/env python3
"""Value snapshot: the main board keeps a way into the caravan's two model pages.

/models (the models in the caravan's folder) and /hf (Hugging Face, to download more) had
their links on each machine's caravan strip. The strip left the main board for the machine's
window (1.3.472), and the links went with it: from the main board neither page could be
reached, and nothing said so (the owner, 2026-10-12: "the way into them is lost"). They stood
in the head of Machines then, among the board's tools; since 1.3.537 they stand under the
kanban's card (routers.js `renderBoardPageLinks`, drawn by topology-render.js in the card's
stack; the owner, 2026-10-14: "move these two buttons somewhere more fitting"). This snapshot
names the page whose link is gone, a main board that does not draw the pair, and a style that
hides a link on the main board as well.

Run: python3 scripts/test_board_model_pages.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTERS = ROOT / "static" / "js" / "routers.js"
RENDER = ROOT / "static" / "js" / "topology-render.js"
STYLES = ROOT / "static" / "css"

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class BoardEntries:
    """Which model pages the main board has no way into."""

    PAGES = ("/models", "/hf")
    # What draws the pair, and the card's stack that carries it (a machine's own window has no such lane: its
    # caravan strip carries the same two links).
    DRAWER = re.compile(r"export function renderBoardPageLinks\(\)\s*\{(?P<body>.*?)\n\}", re.S)
    ON_MAIN = re.compile(r'class="router-stack">[^`]*renderBoardPageLinks\(\)')
    # A rule that hides the links or their pair, and the one place it may do so: a machine's
    # own window.
    HIDDEN = re.compile(r"\.board-page(?:s|-link)\b")
    HIDE = re.compile(r"([^{}]*\.board-page(?:s|-link)\b[^{}]*)\{[^}]*display\s*:\s*none", re.S)
    MACHINE_ONLY = 'html[data-board-view="machine"]'

    @classmethod
    def missing(cls, js):
        """The pages the drawing function has no link to; both, when there is no such function."""
        drawer = cls.DRAWER.search(js)
        body = drawer.group("body") if drawer else ""
        return [page for page in cls.PAGES if f'"{page}"' not in body]

    @classmethod
    def on_main(cls, js):
        """Whether the kanban card's stack draws the pair."""
        return bool(cls.ON_MAIN.search(js))

    @classmethod
    def hidden_on_main(cls, css):
        """Selectors that hide a link on the main board too, one per line of the rule."""
        bad = []
        # Comments first: a comma in one would split a selector in two.
        for rule in cls.HIDE.findall(re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
            for selector in rule.split(","):
                selector = selector.strip()
                if cls.HIDDEN.search(selector) and not selector.startswith(cls.MACHINE_ONLY):
                    bad.append(selector)
        return bad


DRAWER_SAMPLE = """// something above
export function renderBoardPageLinks() {
  const link = (id, href, hook) => `<a id="${id}" href="${href}" data-t="${hook}"></a>`;
  return link("boardModelsLink", "/models", "board-models-open") + link("boardHfLink", "/hf", "board-hf-open");
}
export function elsewhere() { return link("x", "/kanban", "y"); }
"""

STACK_SAMPLE = """const html = window.ROUTER_STANDALONE ? "" : `<div class="router-stack">${cards}${BOARD_VIEW.isMachine ? "" : renderBoardPageLinks()}</div>`;"""

CSS = """/* the window, the board: a comma in a comment */
html[data-board-view="machine"] .machines-head [data-scout-add-open],
html[data-board-view="machine"] .board-pages { display: none; }
.board-pages > .board-page-link { display: inline-flex; }"""


def test_the_rule():
    print("правило — на своих образцах:")
    check(BoardEntries.missing(DRAWER_SAMPLE) == [], "обе страницы — ссылки в функции, что рисует пару")
    check(BoardEntries.missing(DRAWER_SAMPLE.replace('"/hf"', '"/kanban"')) == ["/hf"],
          "negative: без ссылки на /hf — названа /hf")
    check(BoardEntries.missing(DRAWER_SAMPLE.replace('"/models"', '"/kanban"')) == ["/models"],
          "negative: без ссылки на /models — названа /models")
    check(BoardEntries.missing(DRAWER_SAMPLE.replace("export function renderBoardPageLinks", "export function other")) == ["/models", "/hf"],
          "negative: функции, что рисует пару, нет — названы обе страницы; ссылка в чужой функции не в счёт")
    check(BoardEntries.on_main(STACK_SAMPLE), "стопка карточки канбана рисует пару")
    check(not BoardEntries.on_main(STACK_SAMPLE.replace("renderBoardPageLinks()", '""')),
          "negative: стопка пару не рисует — названо")
    check(BoardEntries.hidden_on_main(CSS) == [], "ссылки скрыты только в окне машины")
    loose = CSS.replace('html[data-board-view="machine"] .board-pages', ".machines-head .board-pages")
    check(BoardEntries.hidden_on_main(loose) == [".machines-head .board-pages"],
          "negative: правило скрывает пару ссылок и на главной доске — названо")
    one = CSS + "\n.board-pages > .board-page-link + .board-page-link { display:none }"
    check(BoardEntries.hidden_on_main(one) == [".board-pages > .board-page-link + .board-page-link"],
          "negative: правило скрывает одну ссылку на главной доске — названо")


def test_the_board():
    print("главная доска (static/js, static/css):")
    missing = BoardEntries.missing(ROUTERS.read_text(encoding="utf-8"))
    check(missing == [], "функция рисует ссылки на /models и /hf" + (f" — нет: {', '.join(missing)}" if missing else ""))
    check(BoardEntries.on_main(RENDER.read_text(encoding="utf-8")),
          "стопка карточки канбана на главной доске рисует пару (окно машины его не показывает: там своя полоса)")
    bad = [f"{path.name}: {sel}" for path in sorted(STYLES.glob("*.css"))
           for sel in BoardEntries.hidden_on_main(path.read_text(encoding="utf-8"))]
    check(bad == [], f"ни одно правило не прячет их на главной доске {bad if bad else ''}".rstrip())


for fn in (test_the_rule, test_the_board):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("board model pages snapshot holds")
