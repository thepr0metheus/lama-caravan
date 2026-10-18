#!/usr/bin/env python3
"""Value snapshot: Routing's columns are titled for what they hold — "ID sets" and "ID (Pools)" — in every language.

The owner, 2026-10-14: "name the pools column «ID (POOLS)», and the sets «sets of ID»" and, on a pool's card, "id:" before its name.
The name of a pool is the id of a model, the thing a client puts in `model`; a set holds such ids. The two column titles are keys of
their own (`pbSetsSection`, `pbPoolsSection`): the plain word "Pools" stays on the main board's Routing card and in its counters.
In each of the 20 languages the pools' title is "ID (" and that language's word for a pool and ")", the sets' title carries "ID" as a
word of its own; Routing's head and the strip's path say the same words (one word, one meaning); and a pool's card says "id:" in
front of its name — a label, not a word to translate, and a thing the sets' cards do not have.

Run: python3 scripts/test_routing_titles.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ROOT / "static" / "js" / "i18n"
BOARD = ROOT / "static" / "js" / "pool-board.js"

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


class ColumnTitles:
    """Routing's column titles, in every language and in the board's script."""

    @staticmethod
    def value(text, key):
        found = re.search(rf'^  {key}: "([^"]*)",$', text, re.M)
        return found.group(1) if found else None

    @classmethod
    def language_problems(cls, files):
        bad = []
        for lang, text in sorted(files.items()):
            sets, pools, word = (cls.value(text, k) for k in ("pbSetsSection", "pbPoolsSection", "topologyLlamaServersSection"))
            if sets is None or pools is None or word is None:
                bad.append(f"{lang}: a title is missing (pbSetsSection, pbPoolsSection or topologyLlamaServersSection)")
                continue
            if not re.search(r"(?<![A-Za-z])ID(?![A-Za-z])", sets):
                bad.append(f"{lang}: the sets' title \"{sets}\" does not carry ID")
            if not re.fullmatch(r"ID ?[(（]" + re.escape(word) + r"[)）]", pools):
                bad.append(f"{lang}: the pools' title \"{pools}\" is not ID and the word for a pool, \"{word}\", in brackets")
        return bad

    @classmethod
    def script_problems(cls, js):
        """Routing's heads and the strip's path must speak the titles' own keys, not the plain word the main board's card uses."""
        bad = []
        if 'this.head(t("pbPoolsSection")' not in js:
            bad.append("the pools' column head does not use pbPoolsSection")
        if 'this.head(t("pbSetsSection")' not in js:
            bad.append("the sets' column head does not use pbSetsSection")
        if 'label: t("pbPoolsSection")' not in js or 'label: t("pbSetsSection")' not in js:
            bad.append("the strip's path names its columns with other words than the heads")
        if re.search(r't\("topologyLlamaServersSection"\)', js):
            bad.append("the board's script still reads the plain word for a pool (topologyLlamaServersSection)")
        if not re.search(r'<span class="pb-pool-id" aria-hidden="true">id:</span>\s*<input class="pb-pool-name" data-pb-pool-name', js):
            bad.append("a pool's card does not say id: before its name")
        return bad



def test_the_rule():
    print("названия колонок Маршрутизации — на своих образцах:")
    en = 'x\n  pbSetsSection: "ID sets",\n  pbPoolsSection: "ID (Pools)",\n  topologyLlamaServersSection: "Pools",\n'
    ja = 'x\n  pbSetsSection: "IDセット",\n  pbPoolsSection: "ID（プール）",\n  topologyLlamaServersSection: "プール",\n'
    zh = 'x\n  pbSetsSection: "ID模型集",\n  pbPoolsSection: "ID(池)",\n  topologyLlamaServersSection: "池",\n'
    check(ColumnTitles.language_problems({"en": en, "ja": ja, "zh": zh}) == [], "английский, японский и китайский образцы без замечаний (скобки и пробелы по языку)")
    no_id = en.replace('"ID sets"', '"Sets"')
    check(ColumnTitles.language_problems({"en": no_id}) == ['en: the sets\' title "Sets" does not carry ID'], "negative: у названия наборов нет ID — названо")
    old = en.replace('pbPoolsSection: "ID (Pools)"', 'pbPoolsSection: "Pools"')
    check(ColumnTitles.language_problems({"en": old}) == ['en: the pools\' title "Pools" is not ID and the word for a pool, "Pools", in brackets'],
          "negative: название пулов осталось прежним словом — названо")
    wrong = en.replace('pbPoolsSection: "ID (Pools)"', 'pbPoolsSection: "ID (Groups)"')
    check(len(ColumnTitles.language_problems({"en": wrong})) == 1, "negative: в скобках не то слово, которым язык называет пул, — названо")
    missing = en.replace('  pbPoolsSection: "ID (Pools)",\n', "")
    check(ColumnTitles.language_problems({"de": missing}) == ["de: a title is missing (pbSetsSection, pbPoolsSection or topologyLlamaServersSection)"],
          "negative: названия нет в языке совсем — названо")
    check(ColumnTitles.language_problems({"id": 'x\n  pbSetsSection: "Set ID",\n  pbPoolsSection: "ID (Kelompok)",\n  topologyLlamaServersSection: "Kelompok",\n'}) == [],
          "ID как слово: «Set ID» — идентификатор отдельным словом, не часть чужого слова")
    check(ColumnTitles.language_problems({"x": 'x\n  pbSetsSection: "Valid sets",\n  pbPoolsSection: "ID (Pools)",\n  topologyLlamaServersSection: "Pools",\n'})
          == ['x: the sets\' title "Valid sets" does not carry ID'], "negative: «ID» внутри чужого слова («Valid») за ID не считается")
    js = ('this.head(t("pbSetsSection"),\nthis.head(t("pbPoolsSection"),\nlabel: t("pbSetsSection")\nlabel: t("pbPoolsSection")\n'
          '<span class="pb-pool-id" aria-hidden="true">id:</span>\n  <input class="pb-pool-name" data-pb-pool-name\'')
    check(ColumnTitles.script_problems(js) == [], "скрипт: головы и путь в полосе говорят названиями колонок — без замечаний")
    check(ColumnTitles.script_problems(js.replace('this.head(t("pbPoolsSection")', 'this.head(t("topologyLlamaServersSection")'))
          == ["the pools' column head does not use pbPoolsSection", "the board's script still reads the plain word for a pool (topologyLlamaServersSection)"],
          "negative: голова колонки пулов читает прежнее слово — названо")
    check(ColumnTitles.script_problems(js.replace('label: t("pbPoolsSection")', 'label: t("topologyLlamaServersSection")'))
          == ["the strip's path names its columns with other words than the heads", "the board's script still reads the plain word for a pool (topologyLlamaServersSection)"],
          "negative: полоса называет колонки другими словами, чем головы, — названо (одно слово — один смысл)")



    check(ColumnTitles.script_problems(js.replace('<span class="pb-pool-id" aria-hidden="true">id:</span>', "")) == ["a pool's card does not say id: before its name"],
          "negative: у карточки пула нет подписи «id:» перед названием — названо (владелец, 2026-10-14)")
    check(ColumnTitles.script_problems(js.replace('<span class="pb-pool-id" aria-hidden="true">id:</span>', '<span class="pb-pool-id">id:</span>'))
          == ["a pool's card does not say id: before its name"],
          "negative: подпись не скрыта от читалок экрана (поле имени говорит само) — названо")
    check(ColumnTitles.script_problems(js.replace('data-pb-pool-name', 'data-pb-set-name')) == ["a pool's card does not say id: before its name"],
          "negative: подпись стоит перед полем имени набора, не пула — названо")


def test_the_board():
    print("доска (static/js):")
    files = {path.stem: path.read_text(encoding="utf-8") for path in sorted(LANGS.glob("*.js"))}
    check(len(files) == 20, f"языков 20 ({len(files)})")
    bad = ColumnTitles.language_problems(files)
    check(bad == [], "названия колонок Маршрутизации — ID и слово языка — во всех языках" + (f" — {'; '.join(bad[:3])}" if bad else ""))
    bad = ColumnTitles.script_problems(BOARD.read_text(encoding="utf-8"))
    check(bad == [], "Маршрутизация: головы и путь в полосе называют колонки одними словами, карточка пула говорит «id:»" + (f" — {'; '.join(bad)}" if bad else ""))


for fn in (test_the_rule, test_the_board):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("routing titles snapshot holds")
