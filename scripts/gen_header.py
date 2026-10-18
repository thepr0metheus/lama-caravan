#!/usr/bin/env python3
"""The header of every page, from ONE template.

The owner, 2026-10-15: "on pages like /machine?host=… there is no button to the main page. The app's
header must always follow one template." It did not: the bar was written by hand into five pages
(index, Routing, models, system, hf), and five copies drift — the machine window (index.html in its
other view) had no way back, /hf carried a class nothing styled, the version chip stood inside the
brand on two pages and beside it on three, the account menu named its entries on two pages and not on
three. A rule written on the page where it was noticed is a rule the other four never got.

So the bar is written HERE, once. This script puts it into each page between two marker comments;
`check_header.py` (CI) fails when a page's bar is not what this template renders. What may differ
from page to page is the table PAGES, and nothing else: its title, whether it has a tour to start,
whether its script wires the account menu's «Security» entry, what it adds beside the account, and
whether it carries the product's long name. Everything the bar must have everywhere — above all the
way back to the main board — is in the template and so cannot be left off one page.

    python3 scripts/gen_header.py        # rewrite the bar of every page
    python3 scripts/check_header.py      # the guard: fails on a page whose bar is not the template's

The way back is on EVERY page, the board's own among them: index.html is two pages (/board, and
/machine?host=… — static/js/board-view.js tells them apart). On the board's row the link says it is for
the machine's view only (`data-view-only="machine"`), and one rule of static/css/base.css hides it
anywhere else: the main board is where back goes, and a machine's window is not the board. The rule keys
on the LINK's own word and not on `data-board-view="main"`: Routing loads the board's script too, which
marks it "main" — it is not the main board, and the first version of this rule took its way back away.
"""
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ACRONYM = "Local And Multi-backend Adaptive Computation And Routing Across Various AI Nodes"


@dataclass(frozen=True)
class Page:
    """How one page's bar differs from the template's default. Anything not here does not differ."""

    #: the page's file under static/
    file: str
    #: the page's own name: the bar's <h1>
    title: str
    #: its key in the shared dictionary; "" for /hf, which keeps a table of its own and does not load it
    title_key: str = ""
    #: the product's long name under the brand (the board's, the product's front page)
    tagline: bool = False
    #: the page has a tour: /models and /system have none, and a button that starts nothing is worse than none
    tour: bool = True
    #: the page's script wires the account menu's «Security» entry (main.js: the board and Routing)
    security: bool = False
    #: markup the page adds in front of the account chip, indented as it is to stand in the bar
    actions: str = ""
    #: the way back is shown in this view of the page only ("" = in every view). The board's page is two pages: its
    #: main view is where back goes, and a machine's window is not
    back_only_in: str = ""


class AppHeader:
    """The bar at the top of every page. `render(name)` is the whole of it."""

    BEGIN = ("<!-- header:begin — made by scripts/gen_header.py from its template; "
             "change the template, never one page -->")
    END = "<!-- header:end -->"

    #: The one table of how pages differ. A new page is a new row, and the guard names the page that has none.
    PAGES = {
        "board": Page(file="index.html", title="Main board", title_key="boardPageName",
                      tagline=True, security=True, back_only_in="machine"),
        "routing": Page(file="routing.html", title="Routing", title_key="topologyRouterTitle",
                       security=True),
        "models": Page(file="models.html", title="Models on disk", title_key="modelsPage", tour=False,
                       actions='<a class="sys-back mdl-hf-link" href="/hf">🤗 HF</a>'),
        "system": Page(file="system.html", title="System &amp; settings", title_key="systemSubtitleBrand",
                       tour=False),
        "hf": Page(file="hf.html", title="HuggingFace Browser",
                   actions='<span id="hfDiskBadge" class="hf-disk-badge" hidden></span>\n'
                           '<a id="hfOnDiskBtn" data-t="hf-on-disk" class="hf-ondisk-btn" href="/models" '
                           'title="Manage downloaded models">📦 <span data-label>on disk</span></a>'),
    }

    #: <header class="topbar" …> … </header>, as a page has it before and after the markers go in
    _BAR = re.compile(r'(?:[ \t]*<!-- header:begin[^>]*-->\n)?[ \t]*<header class="topbar[^"]*"[^>]*>.*?</header>\n'
                      r'(?:[ \t]*<!-- header:end -->\n)?', re.S)

    # ---- the template, part by part -------------------------------------------------------------

    @staticmethod
    def _back(page):
        # The way back to the main board, on every page. `data-view-only` is what base.css's one rule reads.
        only = f' data-view-only="{page.back_only_in}"' if page.back_only_in else ""
        return (f'<a class="sys-back topbar-back" data-t="header-back"{only} href="/board">'
                '<span aria-hidden="true">←</span> <span data-i18n="boardPageName">Main board</span></a>')

    @classmethod
    def _brand(cls, page):
        tagline = (f'\n          <span class="brand-acronym" data-i18n="appAcronym" '
                   f'data-t="header-page-subtitle">{ACRONYM}</span>') if page.tagline else ""
        return (
            '<div class="topbar-brand">\n'
            f'      {cls._back(page)}\n'
            '      <div class="brand-title">\n'
            '        <img src="/favicon.svg?v=4" alt="" aria-hidden="true">\n'
            '        <span class="brand-name-wrap">\n'
            f'          <span data-i18n="appTitle" data-t="header-app-title">LAMA CARAVAN</span>{tagline}\n'
            '        </span>\n'
            '        <span id="projectGitBranch" class="project-git-branch" data-title-i18n="projectGitBranchTitle" '
            'title="Project git branch" data-t="header-version-branch">branch n/a</span>\n'
            '      </div>\n'
            '    </div>')

    @staticmethod
    def _title(page):
        key = f' data-i18n="{page.title_key}"' if page.title_key else ""
        return f'<h1 class="page-title" data-t="header-page-title"{key}>{page.title}</h1>'

    @staticmethod
    def _account(page):
        security = ('          <button id="userMenuSecurity" type="button" data-i18n="securitySection" '
                    'data-t="header-user-security">Security</button>\n') if page.security else ""
        return (
            '<div class="user-chip" id="userChip" hidden data-t="header-user-chip">\n'
            '        <button id="userChipBtn" type="button" aria-haspopup="menu" aria-expanded="false" '
            'data-t="header-user-menu-open">\n'
            '          <span class="user-chip-ico">👤</span><span id="userChipName" data-t="header-user-name">'
            '</span><span class="lang-caret" aria-hidden="true">▾</span>\n'
            '        </button>\n'
            '        <div id="userMenu" class="user-menu" hidden data-t="header-user-menu">\n'
            f'{security}'
            '          <button id="userMenuLogout" type="button" data-i18n="authLogout" '
            'data-t="header-user-logout">Log out</button>\n'
            '        </div>\n'
            '      </div>')

    @staticmethod
    def _tour():
        return ('<button type="button" class="ob-btn-head" data-ob-tour>\n'
                '        <span class="ob-q">?</span><span id="obBtnLabel" data-i18n="tourBtnLabel">Tour</span>\n'
                '      </button>')

    @staticmethod
    def _language():
        return (
            '<div class="lang-select" id="langSelect">\n'
            '        <button id="langTrigger" class="lang-trigger" type="button" aria-haspopup="listbox" '
            'aria-expanded="false" data-i18n-aria="a11yInterfaceLanguage" aria-label="Interface language" '
            'data-t="header-lang-open">\n'
            '          <span class="lang-emoji" id="langTriggerEmoji">☕</span>'
            '<span class="lang-code" id="langTriggerCode" data-t="header-lang-current">EN</span>'
            '<span class="lang-caret" aria-hidden="true">▾</span>\n'
            '        </button>\n'
            '        <ul class="lang-menu" id="langMenu" role="listbox" tabindex="-1" hidden '
            'data-t="header-lang-menu" data-i18n-aria="a11yInterfaceLanguage" aria-label="Interface language"></ul>\n'
            '      </div>')

    # ---- the whole bar ----------------------------------------------------------------------------

    @classmethod
    def render(cls, name):
        """The marked block of page `name`: both comments and the <header> between them, as the page holds it."""
        page = cls.PAGES[name]
        added = "".join(f"      {line}\n" for line in page.actions.split("\n")) if page.actions else ""
        tour = f"      {cls._tour()}\n" if page.tour else ""
        return (
            f'  {cls.BEGIN}\n'
            '  <header class="topbar" data-t="header">\n'
            f'    {cls._brand(page)}\n'
            f'    {cls._title(page)}\n'
            '    <div class="actions">\n'
            f'{added}'
            f'      {cls._account(page)}\n'
            f'{tour}'
            f'      {cls._language()}\n'
            '    </div>\n'
            '  </header>\n'
            f'  {cls.END}\n')

    @classmethod
    def put_into(cls, html, name):
        """`html` with the page's bar replaced by the template's, or None when the page has no bar to replace."""
        if len(cls._BAR.findall(html)) != 1:
            return None
        return cls._BAR.sub(lambda _: cls.render(name), html, count=1)

    @classmethod
    def path(cls, name):
        return ROOT / "static" / cls.PAGES[name].file

    @classmethod
    def write_all(cls, out=sys.stdout):
        status = 0
        for name in cls.PAGES:
            path = cls.path(name)
            html = path.read_text(encoding="utf-8")
            made = cls.put_into(html, name)
            if made is None:
                out.write(f"{path.relative_to(ROOT)}: not exactly one <header class=\"topbar\"> — left alone\n")
                status = 1
            elif made == html:
                out.write(f"{path.relative_to(ROOT)}: bar already the template's\n")
            else:
                path.write_text(made, encoding="utf-8")
                out.write(f"{path.relative_to(ROOT)}: bar rewritten from the template\n")
        return status


if __name__ == "__main__":
    sys.exit(AppHeader.write_all())
