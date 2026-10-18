#!/usr/bin/env python3
"""Value snapshot of the reading in scripts/check_same_tab_links.py: what counts as a place that asks for another tab.

The guard is red on a place it should not read and on a place it misses alike: a comment that talks of
`window.open(` must not fail the page, and an attribute with a window's NAME (not only `_blank`) must. Each
sample below is a text and the lines that count, with the negative beside it. The list of reasons is checked
on a small tree of its own: a place with its reason passes, one without is named, and a reason whose place is
gone or has grown is named.

Run: python3 scripts/test_same_tab_links.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_same_tab_links import NewTabSites  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def lines(text, suffix=".js"):
    return [number for number, _ in NewTabSites.asks(text, suffix)]


def test_what_asks():
    print("что просит другую вкладку или окно:")
    check(lines('const html = `<a href="/x" target="_blank" rel="noopener">x</a>`;') == [1], "атрибут target=\"_blank\" в шаблоне — просит")
    check(lines('<a href="/x" target="caravan-hf">x</a>', ".html") == [1], "окно с ИМЕНЕМ — тоже просит, не только _blank")
    check(lines('`<a href="/m" target="${windowName}">`') == [1], "имя окна из шаблона — просит")
    check(lines("<a href='/x' target='_blank'>", ".html") == [1], "одинарные кавычки — просит")
    check(lines('window.open("/routing", "_blank");') == [1] and lines("globalThis.open(url, '_blank')") == [1]
          and lines("self.open(url)") == [1] and lines("top.open(url)") == [1], "window.open, globalThis.open, self.open, top.open — просят")
    check(lines('hfBtn.target = "_blank";') == [1] and lines("link.target='_blank'") == [1], "свойство .target = \"…\" — просит")
    check(lines('a.setAttribute("target", "_blank")') == [1], "setAttribute(\"target\", …) — просит")
    check(lines("ok\n\nwindow.open(x)\n") == [3], "номер строки — настоящий")

    print("что не просит:")
    check(lines("if (e.target === node) return;\nconst t = event.target?.closest?.('a');\nobj = { target: x };\nevt.target.closest(\"a\")") == [],
          "negative: e.target, event.target?.closest, поле { target: x } — не окна")
    check(lines("this.open = open || ((u) => u);\nconst win = this.open(url);\nopen(\"model\");") == [],
          "negative: свой метод open и локальная функция open(\"model\") — не окно (window.open пишется с window)")
    check(lines('// window.open("/x", "_blank")\n   * target="_blank"\n/* window.open( */\n# target="_blank"') == [],
          "negative: строки комментариев // * /* # о window.open и target не считаются")
    check(lines('<!-- <a target="_blank">\n   and window.open( -->\n<a href="/x">', ".html") == [],
          "negative: HTML-комментарий о target и window.open не считается, в том числе в несколько строк")
    check(lines('<!-- c\n -->\n<a target="_blank">x</a>', ".html") == [3], "номера строк после HTML-комментария не съехали")
    check(lines("threading.Thread(target=run, daemon=True).start()", ".py") == [] and lines("x = 'window.open(1)'", ".py") == [],
          "negative: в Python — Thread(target=run) и строка о window.open( не окно")
    check(lines("html = '<a href=\"/x\" target=\"_blank\">x</a>'", ".py") == [1], "атрибут в HTML, который отдаёт Python, — просит")


def test_reasons():
    print("список причин — на дереве из двух файлов:")

    class Two(NewTabSites):
        ALLOWED = (("static/js/a.js", "mark", 1, "another site"), ("static/js/b.js", "twice", 2, "two other sites"))
        SKIP = ()

    def tree(files):
        tmp = tempfile.TemporaryDirectory()
        for rel, text in files.items():
            path = Path(tmp.name) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return tmp

    good = {"static/js/a.js": 'x = `<a target="_blank" data-mark>`;\n', "static/js/b.js": 'twice(`<a target="_blank">`);\ntwice(`<a target="_blank">`);\n'}
    with tree(good) as d:
        bad, found = Two(Path(d)).problems()
        check(bad == [] and len(found) == 3, f"каждое место с причиной, число совпало — без замечаний (получено {bad})")
    with tree({**good, "static/js/c.js": 'window.open("/models");\n'}) as d:
        bad, _ = Two(Path(d)).problems()
        check(len(bad) == 1 and bad[0].startswith("static/js/c.js:1:") and "причины на это нет" in bad[0],
              f"negative: место вне списка названо — файлом и строкой (получено {bad})")
    with tree({**good, "static/js/b.js": 'twice(`<a target="_blank">`);\n'}) as d:
        bad, _ = Two(Path(d)).problems()
        check(len(bad) == 1 and "static/js/b.js" in bad[0] and "×2" in bad[0] and "×1" in bad[0],
              f"negative: причина на два места, а в коде одно — список назван устаревшим (получено {bad})")
    with tree({**good, "static/js/b.js": 'twice(`<a target="_blank">`);\ntwice(`<a target="_blank">`);\ntwice(window.open(1));\n'}) as d:
        bad, _ = Two(Path(d)).problems()
        check(len(bad) == 1 and "×2" in bad[0] and "×3" in bad[0], f"negative: мест стало больше, чем в списке, — назван список (получено {bad})")
    with tree({"static/js/a.js": 'x = `<a data-mark>`;\n', "static/js/b.js": good["static/js/b.js"]}) as d:
        bad, _ = Two(Path(d)).problems()
        check(len(bad) == 1 and "static/js/a.js" in bad[0] and "×1" in bad[0] and "×0" in bad[0],
              f"negative: место больше не просит вкладку, а причина осталась — назван список (получено {bad})")
    with tree({**good, "static/js/other.js": 'x = `<a target="_blank" data-mark>`;\n'}) as d:
        bad, _ = Two(Path(d)).problems()
        check(len(bad) == 1 and "static/js/other.js" in bad[0], f"negative: причина другого файла не покрывает этот — назван он (получено {bad})")
    with tree({**good, "static/js/i18n/en.js": '  tip: "opens with window.open( in a new target=\\"_blank\\" tab",\n'}) as d:
        class WithSkip(Two):
            SKIP = ("static/js/i18n/",)
        bad, _ = WithSkip(Path(d)).problems()
        check(bad == [], "словари (static/js/i18n) — слова, а не поведение: в них целиком не ищется")


test_what_asks()
test_reasons()
print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("same tab links snapshot holds")
