#!/usr/bin/env python3
"""Value snapshot: every page fits a phone's width (2026-11-07).

Measured on the stand with a 390×844 phone: the layout viewport of /board was 1196 px, of a machine's page 962 and 970, of
/models 893 and 882, of /hf 993 and 994, in English and in Arabic. A phone lays a page out as wide as its widest box and shows
it shrunk, and the end of the bar was cut off. What forced the width was the bar on every page: a grid of three groups whose
actions never wrap (base.css, cards.css). On the main board the board itself did too: it keeps three columns at any window
(`--board-min`, 1148 px) and gives the bar its width. A browser is not in CI, so what the stylesheets say is read from their
text (scripts/_css_rules.py), the rules at rest apart from the rules of each @media block. The claims, each with a positive
and a negative pin:

  the bar (static/css/base.css, cards.css, form.css; the pages' own styles in models.html and system.html)
  - at rest it is the desktop's bar: a grid of `1fr auto 1fr`, its actions on one line;
  - from 1180 px down it folds into a row that wraps, the actions pushed to the end by a logical margin; 1180 is above the
    widest bar measured below 1430 px (1107 px: Spanish, /hf and a machine's page);
  - on a phone (720 px and down) the actions wrap among themselves at the end of their lines, the brand may wrap, the long name
    under it goes, and the bar does not stick; no page's own style makes it stick again, and no rule of form.css (loaded after
    cards.css) names the bar: its old rule there was dead on the grid and turned the folded bar into a column;
  - the bar's three menus hang from logical sides: the language's and the account's from the end of their buttons, the
    machines' from the start of its own and, on a phone, from its end; in Arabic the language's opened 45 px off the screen;
  - no rule of the fold says left or right: a page written right to left folds the same way.

  the main board (static/css/topology-board.css)
  - at rest the board keeps its width (`--board-min: 1148px`) and is a window whose page does not scroll; its bar is a grid from
    721 px up, so it keeps one line, its title in the middle, where the bar of a narrower page folds;
  - on a phone the board has no width to keep, it is one column, the page scrolls and no column scrolls by itself, and the
    monitor's drawer goes;
  - one phone width for the bar and the board: the bar's phone block, the board's fold and the board bar's grid (720 + 1).

  a machine's page (static/css/machine.css, ui.css)
  - the 250 px its head keeps for the board's tools stand only where the page has two panes (`min-width: 1101px`): at rest
    they would make a phone's page 250 px wider;
  - on a narrow rack (its container 780 px and less: a phone) a device's words keep clear of its free room: the row's two
    columns stand apart, where "45 °C" ran into "31.8 free" on the live page; at rest the lanes have no gap, their columns
    stand under the heads' (live check of 2026-11-07).

Run: python3 scripts/test_pages_fit_phone_css.py
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


class Sheet:
    """One stylesheet by value: its rules at rest, and the rules of each of its @media blocks (or @container) apart from them."""

    #: The sides a rule names when it means the screen's left or right, not the start or the end of the line.
    PHYSICAL = ("left", "right", "margin-left", "margin-right", "padding-left", "padding-right", "border-left", "border-right")

    def __init__(self, text, at="media"):
        rest, blocks = CssRules.split(text, at)
        self.rest = CssRules.rules(rest)
        self.blocks = [(query, CssRules.rules(inner)) for query, inner in blocks]

    @classmethod
    def of(cls, path, at="media"):
        return cls(path.read_text(encoding="utf-8"), at)

    @classmethod
    def inline(cls, page):
        """The page's own <style>, the first one in its head."""
        found = re.search(r"<style>(.*?)</style>", page.read_text(encoding="utf-8"), re.S)
        return cls(found.group(1) if found else "")

    @staticmethod
    def merged(rules, selector):
        found = {}
        for sel, declarations in rules:
            if sel == selector:
                found.update(declarations)
        return found

    def at_rest(self, selector):
        return self.merged(self.rest, selector)

    def under(self, query, selector):
        return self.merged([rule for q, rules in self.blocks if q == query for rule in rules], selector)

    def query_where(self, selector, name, value):
        """The queries of the blocks in which `selector` sets `name` to `value`."""
        return [q for q, rules in self.blocks if self.merged(rules, selector).get(name) == value]

    def selectors(self):
        """Every selector of the sheet, at rest and in its blocks."""
        return [sel for sel, _ in self.rest] + [sel for _, rules in self.blocks for sel, _ in rules]

    def sides(self, query):
        """(selector, property) of every physical side the blocks of this query set."""
        return [(sel, name) for q, rules in self.blocks if q == query for sel, declarations in rules
                for name in declarations if name in self.PHYSICAL]

    @staticmethod
    def width(query):
        """The px of `(max-width: Npx)` or `(min-width: Npx)`; None for any other query."""
        found = re.fullmatch(r"\((?:max|min)-width: (\d+)px\)", query or "")
        return int(found.group(1)) if found else None


class PhoneFit:
    """The claims, read from the stylesheets of this tree."""

    #: The widest bar measured on the stand below 1430 px (the pages' words gone), 2026-11-07: Spanish, /hf and a machine's page,
    #: an account of five letters. The bar folds above it.
    WIDEST_BAR = 1107
    PHONE = "(max-width: 720px)"
    #: Where a lane of the machine page's rack is too short for one row (ui.css): its words over its bar.
    NARROW_RACK = "rack (max-width: 780px)"
    BOARD = 'html:not([data-board-view="machine"])'

    def __init__(self, root):
        css = root / "static" / "css"
        self.base, self.cards, self.form = Sheet.of(css / "base.css"), Sheet.of(css / "cards.css"), Sheet.of(css / "form.css")
        self.board, self.machine = Sheet.of(css / "topology-board.css"), Sheet.of(css / "machine.css")
        self.ui = Sheet.of(css / "ui.css", at="container")
        self.pages = {name: Sheet.inline(root / "static" / name) for name in ("models.html", "system.html")}
        #: The block in which the bar folds, read from cards.css: the one where it is a row of flex. None for none, or for two.
        folds = self.cards.query_where(".topbar", "display", "flex")
        self.folds = folds
        self.fold = folds[0] if len(folds) == 1 and folds[0].startswith("(max-width") else None

    def bar(self):
        print("полоса:")
        rest = self.base.at_rest(".topbar")
        check(rest.get("display") == "grid" and rest.get("grid-template-columns") == "1fr auto 1fr",
              f"negative: в покое полоса — сетка 1fr auto 1fr, как на компьютере (получено {rest.get('display')!r}, {rest.get('grid-template-columns')!r})")
        check(self.cards.at_rest(".topbar .actions").get("flex-wrap") == "nowrap",
              "negative: в покое действия стоят одной строкой — на компьютере полоса не переносится")
        fold = self.fold
        check(fold is not None and Sheet.width(fold) >= self.WIDEST_BAR,
              f"полоса складывается в одном блоке, шире самой широкой замеренной ({self.WIDEST_BAR} px, испанский, /hf и страница машины; получено {self.folds})")
        folded = self.cards.under(fold, ".topbar")
        check(folded.get("flex-wrap") == "wrap" and folded.get("gap") == "8px 24px",
              f"сложенная полоса — строка, которая переносится (получено {folded})")
        check(self.cards.under(fold, ".topbar .actions").get("margin-inline-start") == "auto",
              "действия прижаты к концу строки логическим полем: справа, а на странице справа налево — слева")
        phone = self.cards.under(self.PHONE, ".topbar")
        check(phone.get("position") == "static" and phone.get("padding") == "14px",
              f"на телефоне полоса не липнет: в три-четыре строки она закрыла бы пятую часть экрана (получено {phone})")
        actions = self.cards.under(self.PHONE, ".topbar .actions")
        check(actions.get("flex-wrap") == "wrap" and actions.get("justify-content") == "flex-end",
              f"на телефоне действия переносятся между собой и стоят у конца строк (получено {actions})")
        check(all(self.cards.under(self.PHONE, sel).get("flex-wrap") == "wrap" for sel in (".topbar-brand", ".brand-title"))
              and self.cards.under(self.PHONE, ".topbar .brand-acronym").get("display") == "none",
              "на телефоне бренд переносится, а длинное имя под ним уходит, как в окне машины")
        print("полосу не трогают те, кто грузится после:")
        check(".topbar" not in self.form.selectors(),
              "negative: form.css (после cards.css) не называет полосу — его старое правило ставило сложенную полосу столбцом")
        for name, page in self.pages.items():
            own = page.at_rest(".topbar")
            check(own.get("z-index") == "30" and "position" not in own and "top" not in own,
                  f"negative: {name} не держит полосу липкой своим стилем: на телефоне она ушла бы вверх со страницей только там (получено {own})")

    def menus(self):
        print("меню полосы:")
        for sheet, selector, side in ((self.cards, ".lang-menu", "inset-inline-end"), (self.form, ".user-menu", "inset-inline-end"),
                                      (self.cards, ".topbar-machines-menu", "inset-inline-start")):
            rule = sheet.at_rest(selector)
            check(rule.get(side) == "0", f"{selector} висит от {'конца' if side.endswith('end') else 'начала'} своей кнопки ({side}: 0)")
            physical = {name: value for name, value in rule.items() if name in ("left", "right")}
            check(physical == {}, f"negative: {selector} не говорит left/right: на странице справа налево такое меню "
                                  f"открывается за край экрана, как меню языка на 45 px (получено {physical})")
        phone = self.cards.under(self.PHONE, ".topbar-machines-menu")
        check(phone.get("inset-inline-start") == "auto" and phone.get("inset-inline-end") == "0",
              f"на телефоне меню машин висит от конца кнопки: от начала оно уходило за край на 9 px (получено {phone})")
        sides = self.cards.sides(self.fold) + self.cards.sides(self.PHONE) + self.board.sides(self.PHONE)
        check(sides == [], f"negative: ни одно правило складывания не говорит left/right (получено {sides})")

    def main_board(self):
        print("главная доска:")
        check(self.board.at_rest(":root").get("--board-min") == "1148px"
              and all(self.board.at_rest(sel).get("min-width") == "var(--board-min)" for sel in (".topology-board", ".topology-view")),
              "negative: в покое доска держит свою ширину: окно уже доски листается вбок, а доска цела (решение владельца)")
        window = self.board.at_rest(f"{self.BOARD}:has(.topology-view)").get("overflow-y")
        check(window == "hidden", f"negative: в покое доска — окно: страница не листается, колонки листаются сами (получено {window!r})")
        grid = self.board.under("(min-width: 721px)", f"{self.BOARD} body:has(.topology-view) .topbar")
        check(grid.get("display") == "grid",
              "полоса главной доски — сетка от 721 px: шириной с доску, она в одну строку с названием посередине")
        check(self.board.under(self.PHONE, ":root").get("--board-min") == "0px", "на телефоне доске нечего держать: --board-min 0px")
        folded = self.board.under(self.PHONE, f"{self.BOARD} .topology-view > .topology-board")
        check(folded.get("grid-template-columns") == "minmax(0, 1fr)" and folded.get("grid-template-rows") == "none",
              f"на телефоне доска — одна колонка: клиенты, Routing, машины (получено {folded})")
        page = self.board.under(self.PHONE, f"{self.BOARD}:has(.topology-view)").get("overflow-y")
        body = self.board.under(self.PHONE, f"{self.BOARD} body:has(.topology-view)")
        check(page == "visible" and body.get("display") == "block" and body.get("height") == "auto",
              f"на телефоне доска — страница: листается вся (получено {page!r}, {body})")
        scroll = self.board.under(self.PHONE, f"{self.BOARD} .topology-board .board-scroll").get("overflow")
        check(scroll == "visible", f"на телефоне ни одна колонка не листается сама: два листателя пальцем не различить (получено {scroll!r})")
        drawer = self.board.under(self.PHONE, f"{self.BOARD} .monitor-drawer").get("display")
        check(drawer == "none", f"на телефоне выдвижной монитор уходит: у края экрана он лёг поверх кнопок полосы (получено {drawer!r})")

    def one_phone(self):
        print("одна ширина телефона:")
        bar = self.cards.query_where(".topbar .actions", "flex-wrap", "wrap")
        board = self.board.query_where(":root", "--board-min", "0px")
        grid = self.board.query_where(f"{self.BOARD} body:has(.topology-view) .topbar", "display", "grid")
        phone = Sheet.width(bar[0]) if len(bar) == 1 and bar[0].startswith("(max-width") else None
        check(phone is not None and board == bar,
              f"полоса и доска складываются на одной ширине телефона (получено {bar}, {board})")
        check(phone is not None and len(grid) == 1 and grid[0] == f"(min-width: {phone + 1}px)",
              f"полоса доски — сетка ровно до ширины телефона: шириной с доску, она не складывается (получено {grid})")
        check(phone is not None and self.fold is not None and Sheet.width(self.fold) > phone, "полоса складывается раньше, чем начинается телефон")

    def machine_page(self):
        print("страница машины:")
        head = ".machine-page .ui-win-head"
        check(self.machine.under("(min-width: 1101px)", head).get("padding-right") == "250px",
              "250 px шапки под инструменты доски — там, где у страницы две панели (от 1101 px)")
        rest = self.machine.at_rest(head)
        check(rest.get("padding") == "8px 24px" and "padding-right" not in rest and "padding-inline-end" not in rest,
              f"negative: в покое шапка не держит 250 px: страница телефона стала бы на 250 px шире (получено {rest})")
        narrow = self.ui.under(self.NARROW_RACK, ".ui-lane--rack")
        free = self.ui.under(self.NARROW_RACK, ".ui-lane--rack > .ui-lane-free")
        check(narrow.get("grid-template-columns") == "minmax(0, 1fr) auto" and narrow.get("column-gap") == "var(--ui-s2)"
              and free.get("padding-right") == "0",
              f"на узкой стойке слова устройства не упираются в его свободное место: колонка свободного — по цифре, между колонками "
              f"зазор («45 °C31.8 free» на телефоне; получено {narrow}, {free})")
        lane, heads = self.ui.at_rest(".ui-lane--rack"), self.ui.at_rest(".ui-lane-heads")
        check(lane.get("gap") == "0" and "column-gap" not in lane and not {"gap", "column-gap"} & set(heads),
              f"negative: в покое у дорожек нет зазора: их колонки стоят под колонками заголовков, у которых его тоже нет (получено {lane.get('gap')!r})")

    def run(self):
        for claim in (self.bar, self.menus, self.main_board, self.one_phone, self.machine_page):
            claim()


def main():
    PhoneFit(ROOT).run()
    if _fail:
        print(f"\npages fit a phone FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  -", msg)
        return 1
    print("\npages fit a phone OK: полоса складывается, доска на телефоне — одна колонка, всё логическими сторонами")
    return 0


if __name__ == "__main__":
    sys.exit(main())
