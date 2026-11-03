#!/usr/bin/env python3
"""Value snapshot: the caravan's pages are in the bar of every page, and nowhere else.

/models (the models on the disks and in the libraries) and /hf (Hugging Face, to download more) had four homes: two
wide buttons in the head of Machines on the main board (1.3.540), the same two on each machine's caravan strip, a
"🤗 HF" link in the bar of /models and a "📦 on disk" one in the bar of /hf. The owner, 2026-10-24: "move them into the
row where the language switches". They are now one part of the bar's template (scripts/gen_header.py, BAR_PAGES), so
a page cannot be left without them. Routing and the list of machines joined them on 2026-10-29. This snapshot names

  - a page whose bar lacks a link, or whose link opens a tab of its own (the caravan's screens open in THIS tab: the
    owner, 2026-10-17), carries no hook for the tests or no hover;
  - a link that says it is the page it stands on anywhere but on that page — or does not say it there;
  - a page that links /models or /hf a second time, from anywhere but the bar, and a script that still draws them;
  - /hf, which does not load the shared dictionary, calling the Models page by another word than every other page;
  - a bar without the list of machines, and a page whose script does not start it: a button that does nothing.

Run: python3 scripts/test_header_model_pages.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_header import AppHeader  # noqa: E402

STATIC = ROOT / "static"

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class ModelPagesInBar:
    """What a page's bar says of the two model pages, and what the rest of the page says of them."""

    LINKS = {"/models": "header-models", "/hf": "header-hf", "/routing": "header-routing"}
    #: Which page each link is: on it, the link says so.
    OWN = {"/models": "models", "/hf": "hf", "/routing": "routing"}
    BAR = re.compile(r'<header class="topbar"[^>]*>(?P<body>.*?)</header>', re.S)
    NAV = re.compile(r'<nav id="headerPages" class="topbar-pages" data-t="header-pages"[^>]*>(?P<body>.*?)</nav>', re.S)
    ACTIONS = re.compile(r'<div class="actions">\s*<nav id="headerPages"')
    ANCHOR = re.compile(r"<a [^>]*>", re.S)
    #: The list of machines: a button that says something in its hover, and its menu closed.
    MACHINES = re.compile(r'<button id="headerMachinesBtn"[^>]* data-t="header-machines-open" data-title-i18n="[^"]+"[^>]*>.*?</button>\s*'
                          r'<div id="headerMachinesMenu"[^>]* hidden ', re.S)
    #: The script a page starts from, the one that must start the list.
    ENTRY = re.compile(r'<script type="module" src="/js/([^"]+)"></script>')
    #: What drew the pair before: the board's row and the caravan strip's links.
    OLD = re.compile(r"board-pages|boardModelsLink|boardHfLink|board-models-open|board-hf-open|caravanLinksHtml|caravan-links"
                     r"|node-caravan-models|node-caravan-hf|hfOnDiskBtn|mdl-hf-link")

    @classmethod
    def problems(cls, html, page):
        """What is wrong with the pair on page `page` (a name of AppHeader.PAGES)."""
        bar = cls.BAR.search(html)
        nav = cls.NAV.search(bar.group("body")) if bar else None
        if not nav:
            return ["no pair of page links (nav.topbar-pages) in the bar"]
        bad = []
        if not cls.ACTIONS.search(bar.group("body")):
            bad.append("the pair is not the first thing of the bar's row (div.actions)")
        links = cls.ANCHOR.findall(nav.group("body"))
        for href, hook in cls.LINKS.items():
            link = next((a for a in links if f'href="{href}"' in a), None)
            if link is None:
                bad.append(f"no link to {href} in the bar")
                continue
            if "target=" in link:
                bad.append(f"the link to {href} opens in a tab of its own (it carries a target): the caravan's screens open in this tab")
            if f'data-t="{hook}"' not in link:
                bad.append(f"the link to {href} has no hook {hook}")
            if "data-title-i18n=" not in link:
                bad.append(f"the link to {href} says nothing in its hover")
            here = 'aria-current="page"' in link
            if here and cls.OWN[href] != page:
                bad.append(f"the link to {href} says it is the page it stands on, on {page}")
            if not here and cls.OWN[href] == page:
                bad.append(f"the link to {href} does not say it is this page, on {page}")
        if not cls.MACHINES.search(nav.group("body")):
            bad.append("no list of machines in the bar")
        for href in cls.LINKS:
            if html.count(f'href="{href}"') != 1:
                bad.append(f"{href} is linked {html.count(f'href={chr(34)}{href}{chr(34)}')} times on the page: the bar is its one home")
        return bad

    @classmethod
    def drawn_elsewhere(cls, files):
        """Files that still draw the pair, or a link to one of the pages, outside the bar."""
        return sorted(name for name, text in files.items() if cls.OLD.search(text))

    @classmethod
    def not_started(cls, html, scripts):
        """The script a page starts from when it does not start the list of machines; "" when it does."""
        entry = cls.ENTRY.search(html)
        name = entry.group(1) if entry else "no script"
        return "" if "new HeaderMachines(" in scripts.get(name, "") else name

    #: The keys /hf's own table holds with the words of the shared dictionary: the bar says them on every page.
    SAME_WORDS = ("headerPagesLabel", "topologyRouterTitle", "headerRoutingTitle", "topologyMachinesSection", "headerMachinesTitle",
                  "headerMachinesReading", "headerMachinesNone", "headerMachinesFailed", "headerMachineOff")

    @classmethod
    def differing(cls, shared_files, hf_text):
        """Each (language, key) whose word /hf's table lacks or says otherwise than the shared dictionary."""
        table = hf_text.split("const HFS = {", 1)[-1].split("\n};", 1)[0]
        marks = list(cls.HF_BLOCK.finditer(table))
        blocks = {m.group(1): table[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(table)] for i, m in enumerate(marks)}
        bad = []
        for lang, text in sorted(shared_files.items()):
            for key in cls.SAME_WORDS:
                shared = re.search(rf'^  {key}: ("(?:[^"\\]|\\.)*"),$', text, re.M)
                hf = re.search(rf'^    {key}: ("(?:[^"\\]|\\.)*"),$', blocks.get(lang, ""), re.M)
                if not shared or not hf or json.loads(shared.group(1)) != json.loads(hf.group(1)):
                    bad.append((lang, key))
        return bad

    #: The word the shared dictionary says for the Models page, and the one /hf's own table says.
    SHARED = re.compile(r'^  topologyModelsLabel: ("(?:[^"\\]|\\.)*"),$', re.M)
    HF_BLOCK = re.compile(r"^  ([a-z]{2}): \{$", re.M)
    HF_WORD = re.compile(r'^    modelsLink: ("(?:[^"\\]|\\.)*"),$', re.M)

    @classmethod
    def words(cls, shared_files, hf_text):
        """{lang: (the shared word, /hf's word)} — None for a word a table does not say."""
        shared = {lang: (json.loads(m.group(1)) if (m := cls.SHARED.search(text)) else None) for lang, text in shared_files.items()}
        table = hf_text.split("const HFS = {", 1)[-1].split("\n};", 1)[0]
        marks = list(cls.HF_BLOCK.finditer(table))
        hf = {}
        for i, mark in enumerate(marks):
            block = table[mark.end(): marks[i + 1].start() if i + 1 < len(marks) else len(table)]
            word = cls.HF_WORD.search(block)
            hf[mark.group(1)] = json.loads(word.group(1)) if word else None
        return {lang: (shared.get(lang), hf.get(lang)) for lang in sorted(set(shared) | set(hf))}


def test_the_rule():
    print("правило — на своих образцах:")
    board = AppHeader.render("board")
    models = AppHeader.render("models")
    check(ModelPagesInBar.problems(board, "board") == [], "на доске: обе ссылки в строке шапки, первыми, ни одна не «эта страница»")
    check(ModelPagesInBar.problems(models, "models") == [], "на /models: ссылка на /models говорит «эта страница» (aria-current)")
    check(ModelPagesInBar.problems(models, "board") == ["the link to /models says it is the page it stands on, on board"],
          "negative: «эта страница» не на своей странице — названо")
    check(ModelPagesInBar.problems(board, "models") == ["the link to /models does not say it is this page, on models"],
          "negative: на своей странице ссылка не говорит, что это она — названо")
    check(ModelPagesInBar.problems(board.replace('href="/hf"', 'href="/x"'), "board")
          == ["no link to /hf in the bar", "/hf is linked 0 times on the page: the bar is its one home"],
          "negative: ссылки на /hf в шапке нет — названо")
    check(ModelPagesInBar.problems(board.replace('href="/models"', 'href="/models" target="_blank"'), "board")
          == ["the link to /models opens in a tab of its own (it carries a target): the caravan's screens open in this tab"],
          "negative: /models в новой вкладке — названо (экраны каравана открываются в этой же)")
    check(ModelPagesInBar.problems(board.replace('data-t="header-hf"', 'data-t="x"'), "board") == ["the link to /hf has no hook header-hf"],
          "negative: без хука для тестов — названо")
    check(ModelPagesInBar.problems(board.replace(' data-title-i18n="hfBrowserTitle"', ""), "board") == ["the link to /hf says nothing in its hover"],
          "negative: без подсказки — названо")
    check(ModelPagesInBar.problems(board + '\n<a href="/models">again</a>', "board")
          == ["/models is linked 2 times on the page: the bar is its one home"],
          "negative: вторая ссылка на /models где-то на странице — названо (у пары один дом)")
    moved = board.replace('<div class="actions">\n', '<div class="actions">\n      <span>first</span>\n', 1)
    check(ModelPagesInBar.problems(moved, "board") == ["the pair is not the first thing of the bar's row (div.actions)"],
          "negative: пара не первой в строке шапки — названо")
    check(ModelPagesInBar.problems("<header class=\"topbar\"></header>", "board") == ["no pair of page links (nav.topbar-pages) in the bar"],
          "negative: в шапке пары нет совсем — сказано, а не принято за «всё хорошо»")
    check(ModelPagesInBar.problems(board.replace('href="/routing"', 'href="/x"'), "board")
          == ["no link to /routing in the bar", "/routing is linked 0 times on the page: the bar is its one home"],
          "negative: ссылки на /routing в шапке нет — названо")
    routing = AppHeader.render("routing")
    check(ModelPagesInBar.problems(routing, "routing") == [] and ModelPagesInBar.problems(routing, "board") == ["the link to /routing says it is the page it stands on, on board"],
          "на /routing её ссылка горит; negative: «эта страница» не на своей странице — названо")
    check(ModelPagesInBar.problems(board.replace(' data-title-i18n="headerMachinesTitle"', ""), "board") == ["no list of machines in the bar"],
          "negative: кнопка машин без подсказки — списка как нет")
    check(ModelPagesInBar.problems(board.replace('role="menu" hidden ', 'role="menu" '), "board") == ["no list of machines in the bar"],
          "negative: меню машин открыто само — списка как нет")
    check(ModelPagesInBar.not_started('<script type="module" src="/js/a.js"></script>', {"a.js": "new HeaderMachines({}).bind();"}) == "",
          "страница, чей скрипт запускает список, чиста")
    check(ModelPagesInBar.not_started('<script type="module" src="/js/a.js"></script>', {"a.js": "x", "b.js": "new HeaderMachines({})"}) == "a.js",
          "negative: скрипт страницы его не запускает — назван")
    words = {key: "w" for key in ModelPagesInBar.SAME_WORDS}
    hf_table = "const HFS = {\n  en: {\n" + "".join(f'    {k}: "{v}",\n' for k, v in words.items()) + "  },\n};"
    shared_one = {"en": "".join(f'  {k}: "{v}",\n' for k, v in words.items())}
    check(ModelPagesInBar.differing(shared_one, hf_table) == [], "одинаковые слова /hf и общего словаря — чисто")
    check(ModelPagesInBar.differing(shared_one, hf_table.replace('headerMachineOff: "w"', 'headerMachineOff: "x"')) == [("en", "headerMachineOff")],
          "negative: другое слово у /hf — названо")
    check(ModelPagesInBar.differing(shared_one, hf_table.replace('    headerMachineOff: "w",\n', "")) == [("en", "headerMachineOff")],
          "negative: слова у /hf нет — названо")

    check(ModelPagesInBar.drawn_elsewhere({"a.js": "export const x = 1;"}) == [], "скрипт без старых мест пары — чист")
    check(ModelPagesInBar.drawn_elsewhere({"a.js": 'data-t="node-caravan-models"', "b.css": ".board-pages {}"}) == ["a.js", "b.css"],
          "negative: ссылка на полосе каравана или ряд «Machines» — названы")

    good = ModelPagesInBar.words({"en": '  topologyModelsLabel: "Models",\n', "ru": '  topologyModelsLabel: "Модели",\n'},
                                 'const HFS = {\n  en: {\n    modelsLink: "Models",\n  },\n  ru: {\n    modelsLink: "Модели",\n  },\n};')
    check(good == {"en": ("Models", "Models"), "ru": ("Модели", "Модели")}, "слово /hf и общего словаря читаются по языкам")
    bad = ModelPagesInBar.words({"en": '  topologyModelsLabel: "Models",\n', "ru": '  topologyModelsLabel: "Модели",\n'},
                                'const HFS = {\n  en: {\n    modelsLink: "Models",\n  },\n  ru: {\n    onDisk: "на диске",\n  },\n};')
    check(bad["ru"] == ("Модели", None), "negative: у языка /hf слова нет — None, а не чужое слово")


def test_the_pages():
    print("страницы (static/*.html, static/js, static/css):")
    for name, page in AppHeader.PAGES.items():
        html = (STATIC / page.file).read_text(encoding="utf-8")
        bad = ModelPagesInBar.problems(html, name)
        check(bad == [], f"{page.file}: «📦 Models», «🤗 Hugging Face», «🔀 Routing» и список машин — в строке шапки и только там" + (f" — {'; '.join(bad)}" if bad else ""))
    files = {path.name: path.read_text(encoding="utf-8")
             for pattern in ("js/*.js", "css/*.css", "*.html") for path in sorted(STATIC.glob(pattern))}
    drawn = ModelPagesInBar.drawn_elsewhere(files)
    check(drawn == [], f"ни ряд «Machines», ни полоса каравана, ни свои ссылки /models и /hf их больше не рисуют {drawn if drawn else ''}".rstrip())
    scripts = {path.name: path.read_text(encoding="utf-8") for path in sorted((STATIC / "js").glob("*.js"))}
    for name, page in AppHeader.PAGES.items():
        missing = ModelPagesInBar.not_started((STATIC / page.file).read_text(encoding="utf-8"), scripts)
        check(missing == "", f"{page.file}: его скрипт запускает список машин" + (f" — {missing} нет" if missing else ""))
    shared = {path.stem: path.read_text(encoding="utf-8") for path in sorted((STATIC / "js" / "i18n").glob("*.js"))}
    differ = ModelPagesInBar.differing(shared, (STATIC / "js" / "hf-text.js").read_text(encoding="utf-8"))
    check(differ == [], f"слова шапки у /hf и в общем словаре одни на всех языках {differ[:6]}")
    words = ModelPagesInBar.words(shared, (STATIC / "js" / "hf-text.js").read_text(encoding="utf-8"))
    check(len(words) == 6 and all(s is not None and s == h for s, h in words.values()),
          "/hf зовёт страницу моделей тем же словом, что и общий словарь, на всех языках (свой словарь /hf — копия, и она сверяется здесь)"
          + "".join(f" — {lang}: {s!r} ≠ {h!r}" for lang, (s, h) in words.items() if s != h))


def test_the_row_fits():
    print("строка шапки влезает (замерено на 6 видах страниц в 20 языках: 1430 px вмещает слова, ниже остаются значки):")
    cards = (STATIC / "css" / "cards.css").read_text(encoding="utf-8")
    base = (STATIC / "css" / "base.css").read_text(encoding="utf-8")
    check("@media (max-width: 1429px) { .topbar-page-label { display: none; } }" in cards, "подписи кнопок уходят ниже 1430 px, значки и подсказки остаются")
    acronym = re.search(r"\.brand-acronym \{(.*?)\}", base, re.S)
    check(acronym is not None and "nowrap" not in acronym.group(1),
          "negative: расшифровка под названием может переноситься: строкой в 81 букву она выталкивала выбор языка за окно на главной доске")


for fn in (test_the_rule, test_the_pages, test_the_row_fits):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("header model pages snapshot holds")
