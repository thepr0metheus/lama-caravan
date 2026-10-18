#!/usr/bin/env python3
"""Value snapshot: the bar of every page — one template, and the way back to the main board on each.

The owner, 2026-10-15: "on pages like /machine?host=… there is no button to the main page. The app's header must always follow
one template — with this button, so as not to lose it". The machine's window is index.html in its second view, and the bar was a
copy written by hand into five pages; this one was not given the link. Now scripts/gen_header.py renders the bar for every page
from one template, and what a page may do differently is the one table AppHeader.PAGES (check_header.py holds the pages to it).

Pinned by value: the way back is the first thing in the bar of every page, to /board, with the same words and hook; the pages
differ in exactly the table's six things (the title, the tagline, the tour, the «Security» entry, what stands before the account,
the view the way back is for) and in nothing else; every id a script finds the bar's parts by is on every page; the words the bar carries before a language
is loaded are the English ones of the shared dictionary (a page must not flash other words); the generator puts a bar in once and
leaves a second run alone; and the rule that hides the way back keys on the link's own word (`data-view-only="machine"`, on the
board's page alone), not on `data-board-view="main"`: Routing loads the board's script and is marked "main" too, and its
way back was taken away by the first version of the rule (found in a browser, 2026-10-15).

Run: python3 scripts/test_header.py
"""
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_header import ACRONYM, AppHeader, ROOT  # noqa: E402
import check_header  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class Bar:
    """One rendered bar, read by the hooks a test (or a script) finds its parts by."""

    def __init__(self, name):
        self.name = name
        self.text = AppHeader.render(name)

    def hooks(self, hook):
        return re.findall(r'data-t="' + re.escape(hook) + r'"', self.text)

    def ids(self):
        return sorted(re.findall(r'\bid="([^"]+)"', self.text))

    def has(self, snippet):
        return snippet in self.text

    def tag(self, hook):
        """The opening tag that carries `hook`."""
        found = re.search(r'<[a-z0-9]+ [^>]*data-t="' + re.escape(hook) + r'"[^>]*>', self.text)
        return found.group(0) if found else ""

    def first_in_brand(self):
        """The first element inside .topbar-brand: where the way back stands."""
        found = re.search(r'<div class="topbar-brand">\s*(<[a-z0-9]+ [^>]*>)', self.text)
        return found.group(1) if found else ""


BARS = {name: Bar(name) for name in AppHeader.PAGES}
#: What the table says, by page — typed out here so that a change of the table is a change of this test too.
EXPECT = {
    #            title                    its key                tagline tour  security
    "board":  ("Main board",            "boardPageName",        True,  True,  True),
    "routing": ("Routing",               "topologyRouterTitle",  False, True,  True),
    "models": ("Models on disk",        "modelsPage",           False, False, False),
    "system": ("System &amp; settings", "systemSubtitleBrand",  False, False, False),
    "hf":     ("HuggingFace Browser",   "",                     False, True,  False),
}
#: What every bar has: the ids the pages' scripts find the account, the language picker and the version chip by.
COMMON_IDS = sorted(["projectGitBranch", "userChip", "userChipBtn", "userChipName", "userMenu", "userMenuLogout",
                     "langSelect", "langTrigger", "langTriggerEmoji", "langTriggerCode", "langMenu"])


def english(key):
    """The English words of a key: the shared dictionary's, or the tour's (onboarding-strings.js) for the tour's own."""
    for path in (ROOT / "static" / "js" / "i18n" / "en.js", ROOT / "static" / "js" / "onboarding-strings.js"):
        found = re.search(rf'^  {key}: "([^"]*)",$', path.read_text(encoding="utf-8"), re.M)
        if found:
            return found.group(1)
    return None


def test_the_table():
    print("the table of pages:")
    check(sorted(AppHeader.PAGES) == sorted(EXPECT), f"five pages in the table: {sorted(AppHeader.PAGES)}")
    for name, (title, key, tagline, tour, security) in EXPECT.items():
        row = AppHeader.PAGES[name]
        got = (row.title, row.title_key, row.tagline, row.tour, row.security)
        check(got == (title, key, tagline, tour, security), f"{name}: the row says {got}")
    check(sorted(row.file for row in AppHeader.PAGES.values()) ==
          sorted(p.name for p in (ROOT / "static").glob("*.html")),
          "every page under static/ is in the table, and every row has its file")


def test_the_way_back():
    print("the way back to the main board:")
    for name, bar in BARS.items():
        check(len(bar.hooks("header-back")) == 1, f"{name}: one way back (data-t=\"header-back\")")
        tag = bar.tag("header-back")
        check('href="/board"' in tag and tag.startswith("<a "), f"{name}: a link to /board — {tag[:80]}")
        check('class="sys-back topbar-back"' in tag, f"{name}: it has the class the board's own view hides")
        check(bar.first_in_brand() == tag, f"{name}: it is the first thing in the brand group, as before the brand")
        check(bar.has('<span data-i18n="boardPageName">Main board</span></a>'), f"{name}: it says «Main board», in the dictionary's words")
        # Only the board's page may call its link «for the machine's view»: any other page that did would hide it from itself.
        check(('data-view-only="machine"' in tag) == (name == "board"), f"{name}: its link is {'for the machine' + chr(39) + 's view only' if name == 'board' else 'shown in every view'}")
    # The machine's window is the board's page: its bar has the link in the markup (the CSS hides it on the main board only).
    check(BARS["board"].has('data-t="header-back"'), "the machine's window (index.html) carries the way back in its markup")
    check(AppHeader.PAGES["board"].file == "index.html", "the board's row is index.html: the page of both /board and /machine")
    for name in ("routing-back-link",):
        check(all(not bar.has(name) for bar in BARS.values()), f"the old per-page hook {name} is gone from every bar")


def test_what_differs():
    print("what the pages differ in — the table's six things and nothing else:")
    for name, (title, key, tagline, tour, security) in EXPECT.items():
        bar = BARS[name]
        h1 = re.search(r'<h1 class="page-title" data-t="header-page-title"( data-i18n="([^"]+)")?>([^<]*)</h1>', bar.text)
        check(bool(h1) and h1.group(3) == title and (h1.group(2) or "") == key, f"{name}: its one <h1> is {title!r} ({key or 'no key: /hf has its own table'})")
        check(len(re.findall(r"<h1[ >]", bar.text)) == 1, f"{name}: one <h1>")
        check(len(bar.hooks("header-page-subtitle")) == int(tagline), f"{name}: the product's long name is {'there' if tagline else 'not there'}")
        check(len(re.findall(r"data-ob-tour", bar.text)) == int(tour), f"{name}: the tour button is {'there' if tour else 'not there'}")
        check(len(bar.hooks("header-user-security")) == int(security), f"{name}: the account menu's «Security» is {'there' if security else 'not there'}")
    # The skeleton: take each bar's own five things out and what is left must be the same text on every page.
    def skeleton(name):
        text = BARS[name].text
        row = AppHeader.PAGES[name]
        for piece in (row.actions, ):
            if piece:
                text = text.replace("".join(f"      {line}\n" for line in piece.split("\n")), "")
        text = re.sub(r'\n\s*<span class="brand-acronym"[^\n]*</span>', "", text)
        text = re.sub(r'\n\s*<button id="userMenuSecurity"[^\n]*</button>', "", text)
        text = re.sub(r'\n\s*<button type="button" class="ob-btn-head".*?</button>', "", text, flags=re.S)
        text = re.sub(r'(<h1 class="page-title" data-t="header-page-title")[^>]*>[^<]*</h1>', r"\1></h1>", text)
        text = text.replace(' data-view-only="machine"', "")
        return text
    base = skeleton("board")
    for name in AppHeader.PAGES:
        check(skeleton(name) == base, f"{name}: with its six things taken out, its bar is the board's, character for character")
    check(AppHeader.PAGES["models"].actions.count("\n") == 0 and "/hf" in AppHeader.PAGES["models"].actions, "/models adds its link to /hf before the account")
    check(all(h in AppHeader.PAGES["hf"].actions for h in ('id="hfDiskBadge"', 'id="hfOnDiskBtn"', 'data-t="hf-on-disk"')),
          "/hf adds its disk badge and its link to what is on disk before the account")


def test_the_parts_scripts_find():
    print("the ids the pages' scripts find the bar's parts by:")
    for name, bar in BARS.items():
        extra = []
        if EXPECT[name][4]:
            extra.append("userMenuSecurity")
        if name == "hf":
            extra += ["hfDiskBadge", "hfOnDiskBtn"]
        if EXPECT[name][3]:
            extra.append("obBtnLabel")
        check(bar.ids() == sorted(COMMON_IDS + extra), f"{name}: ids {sorted(set(bar.ids()) - set(COMMON_IDS))} besides the common {len(COMMON_IDS)}")
    check(all(len(set(bar.ids())) == len(bar.ids()) for bar in BARS.values()), "no id twice in a bar")
    for name, bar in BARS.items():
        check(bar.has('<div class="topbar-brand">') and bar.has('<div class="actions">'), f"{name}: .topbar-brand and .actions, where the brook's switch and the account find them")
        check(len(re.findall(r'<header class="topbar"', bar.text)) == 1 and bar.text.count("</header>") == 1, f"{name}: one <header class=\"topbar\">")
    check(not any("hf-header" in bar.text for bar in BARS.values()), "the class nothing styled (hf-header) is gone")


def test_the_words():
    print("the words a page shows before its language is loaded are the English ones:")
    wanted = [("boardPageName", '<span data-i18n="boardPageName">{}</span>'),
              ("appTitle", '<span data-i18n="appTitle" data-t="header-app-title">{}</span>'),
              ("appAcronym", '<span class="brand-acronym" data-i18n="appAcronym" data-t="header-page-subtitle">{}</span>'),
              ("projectGitBranchTitle", 'data-title-i18n="projectGitBranchTitle" title="{}"'),
              ("authLogout", 'data-i18n="authLogout" data-t="header-user-logout">{}</button>'),
              ("securitySection", 'data-i18n="securitySection" data-t="header-user-security">{}</button>'),
              ("tourBtnLabel", 'id="obBtnLabel" data-i18n="tourBtnLabel">{}</span>'),
              ("a11yInterfaceLanguage", 'data-i18n-aria="a11yInterfaceLanguage" aria-label="{}"')]
    for key, shape in wanted:
        words = english(key)
        check(words is not None, f"{key}: English words found in the dictionary")
        if words is None:
            continue
        used = [name for name, bar in BARS.items() if shape.format(words) in bar.text]
        carries = [name for name, bar in BARS.items() if f'"{key}"' in bar.text or f'-i18n="{key}"' in bar.text]
        check(used == carries and used, f"{key}: «{words[:40]}» on every bar that carries it ({len(used)} of {len(carries)})")
    for name, (title, key, *_) in EXPECT.items():
        if key:
            check(html.unescape(title) == english(key), f"{name}: the title «{html.unescape(title)}» is the dictionary's English for {key}")
    check(ACRONYM == english("appAcronym"), "the tagline is the dictionary's appAcronym")


def test_the_generator():
    print("the generator:")
    page = '<body>\n  <header class="topbar hf-header" data-t="header">\n    <h1>x</h1>\n  </header>\n  <main>m</main>\n</body>\n'
    made = AppHeader.put_into(page, "models")
    check(made is not None and made.count(AppHeader.BEGIN) == 1 and made.count(AppHeader.END) == 1, "a page with a bar of its own gets the template's, between the two comments")
    check(made is not None and made.startswith("<body>\n") and made.endswith("  <main>m</main>\n</body>\n"), "what stands around the bar is untouched")
    check(AppHeader.put_into(made, "models") == made, "a second run changes nothing")
    check(AppHeader.put_into(made, "hf") != made, "the same page put through another page's row changes (the row is what decides)")
    check(AppHeader.put_into("<body></body>\n", "models") is None, "a page with no bar is not given one in silence")
    check(AppHeader.put_into(page + page, "models") is None, "a page with two bars is not guessed at")
    check(AppHeader.render("board") == AppHeader.render("board"), "the render is the same text every time")


def test_the_rule():
    print("the rule that hides the way back:")
    base = (ROOT / "static" / "css" / "base.css").read_text(encoding="utf-8")
    code = check_header.code_of(base)
    rule = check_header.MAIN_RULE.search(code)
    check(bool(rule) and rule.group(1).strip() == "display: none;",
          "base.css hides html:not([data-board-view=\"machine\"]) .topbar-back[data-view-only=\"machine\"] — one declaration, display: none")
    check(len(check_header.MAIN_RULE.findall(code)) == 1, "once")
    others = [m.group(0) for m in re.finditer(r"[^{}]*topbar-back[^{}]*\{[^}]*\}", code) if not check_header.MAIN_RULE.search(m.group(0))]
    check(others == [], f"no other rule of base.css names it: {others}")
    every = {p.name: check_header.code_of(p.read_text(encoding="utf-8")) for p in (ROOT / "static" / "css").glob("*.css")}
    check(all('data-board-view="main"' not in text for text in every.values()),
          "no stylesheet selects data-board-view=\"main\" at all: the word Routing shares with the board decides nothing")
    check(all("topbar-back" not in text for name, text in every.items() if name != "base.css"), "no stylesheet but base.css names the way back")
    machine = [line for text in every.values() for line in text.split("\n")
               if line.lstrip().startswith('html[data-board-view="machine"]') and "display" in line]
    check(machine != [] and all("topbar-back" not in line for line in machine), f"no rule of the machine's window ({len(machine)} of them) takes it away")
    board = every["topology-board.css"]
    check(board.count('html[data-board-view="machine"] .topbar .brand-acronym { display: none; }') == 1,
          "a machine's window drops the long name under the brand, once (with it the bar was 28 px wider than the window's 1180)")
    view = (ROOT / "static" / "js" / "board-view.js").read_text(encoding="utf-8")
    check('this.isMachine ? "machine" : "main"' in view, "board-view.js names the views «machine» and «main»")
    check('BoardView.PATH = "/machine"' in view.replace("static PATH", "BoardView.PATH").replace(' = "/machine";', ' = "/machine";'),
          "a machine's window is /machine — the path the board's script reads")
    check(check_header.page_problems() == [] and check_header.way_back_problems() == [], "the pages on disk hold the template's bars (check_header.py is green)")


def main():
    test_the_table()
    test_the_way_back()
    test_what_differs()
    test_the_parts_scripts_find()
    test_the_words()
    test_the_generator()
    test_the_rule()
    print()
    if _fail:
        print(f"header: {len(_fail)} FAILED")
        return 1
    print("header OK: the bar is one template; the way back is on every page, hidden on the main board alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
