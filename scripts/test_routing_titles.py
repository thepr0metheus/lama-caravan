#!/usr/bin/env python3
"""Value snapshot: Routing's columns are titled for what they hold — "ID (Pools)" for the pools — in every language.

The owner, 2026-10-14: "name the pools column «ID (POOLS)»" and, on a pool's card, "id:" before its name. The name of a pool is
the id of a model, the thing a client puts in `model`. The pools' title is a key of its own (`pbPoolsSection`): the plain word
"Pools" stays on the main board's Routing card and in its counters. In each of the languages the pools' title is "ID (" and
that language's word for a pool and ")"; Routing's head and the strip's path say the same words (one word, one meaning); and a
pool's card says "id:" in front of its name — a label, not a word to translate. The sets' column, which had a title of its own
(`pbSetsSection`, without the "ID": the owner, 2026-10-18), went with the sets in 1.3.675: no language keeps its word.

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
            pools, word = (cls.value(text, k) for k in ("pbPoolsSection", "topologyLlamaServersSection"))
            if pools is None or word is None:
                bad.append(f"{lang}: a title is missing (pbPoolsSection or topologyLlamaServersSection)")
                continue
            if cls.value(text, "pbSetsSection") is not None:
                bad.append(f"{lang}: the sets' title is still there — the sets went in 1.3.675")
            if not re.fullmatch(r"ID ?[(（]" + re.escape(word) + r"[)）]", pools):
                bad.append(f"{lang}: the pools' title \"{pools}\" is not ID and the word for a pool, \"{word}\", in brackets")
        return bad

    @classmethod
    def script_problems(cls, js):
        """Routing's heads and the strip's path must speak the titles' own keys, not the plain word the main board's card uses."""
        bad = []
        if 'this.head(t("pbPoolsSection")' not in js:
            bad.append("the pools' column head does not use pbPoolsSection")
        if 'label: t("pbPoolsSection")' not in js:
            bad.append("the strip's path names its columns with other words than the heads")
        if "pbSetsSection" in js:
            bad.append("the board's script still names a column of sets")
        if re.search(r't\("topologyLlamaServersSection"\)', js):
            bad.append("the board's script still reads the plain word for a pool (topologyLlamaServersSection)")
        if not re.search(r'<span class="pb-pool-id" aria-hidden="true">id:</span>\s*<input class="pb-pool-name" data-pb-pool-name', js):
            bad.append("a pool's card does not say id: before its name")
        return bad


def test_the_rule():
    print("названия колонок Маршрутизации — на своих образцах:")
    en = 'x\n  pbPoolsSection: "ID (Pools)",\n  topologyLlamaServersSection: "Pools",\n'
    ja = 'x\n  pbPoolsSection: "ID（プール）",\n  topologyLlamaServersSection: "プール",\n'
    zh = 'x\n  pbPoolsSection: "ID(池)",\n  topologyLlamaServersSection: "池",\n'
    check(ColumnTitles.language_problems({"en": en, "ja": ja, "zh": zh}) == [], "английский, японский и китайский образцы без замечаний (скобки и пробелы по языку)")
    with_sets = en + '  pbSetsSection: "Sets",\n'
    check(ColumnTitles.language_problems({"en": with_sets}) == ["en: the sets' title is still there — the sets went in 1.3.675"],
          "negative: у языка осталось название колонки наборов — названо (наборов нет с 1.3.675)")
    old = en.replace('pbPoolsSection: "ID (Pools)"', 'pbPoolsSection: "Pools"')
    check(ColumnTitles.language_problems({"en": old}) == ['en: the pools\' title "Pools" is not ID and the word for a pool, "Pools", in brackets'],
          "negative: название пулов осталось прежним словом — названо")
    wrong = en.replace('pbPoolsSection: "ID (Pools)"', 'pbPoolsSection: "ID (Groups)"')
    check(len(ColumnTitles.language_problems({"en": wrong})) == 1, "negative: в скобках не то слово, которым язык называет пул, — названо")
    missing = en.replace('  pbPoolsSection: "ID (Pools)",\n', "")
    check(ColumnTitles.language_problems({"de": missing}) == ["de: a title is missing (pbPoolsSection or topologyLlamaServersSection)"],
          "negative: названия нет в языке совсем — названо")
    js = ('this.head(t("pbPoolsSection"),\nlabel: t("pbPoolsSection")\n'
          '<span class="pb-pool-id" aria-hidden="true">id:</span>\n  <input class="pb-pool-name" data-pb-pool-name\'')
    check(ColumnTitles.script_problems(js) == [], "скрипт: голова и путь в полосе говорят названием колонки — без замечаний")
    check(ColumnTitles.script_problems(js.replace('this.head(t("pbPoolsSection")', 'this.head(t("topologyLlamaServersSection")'))
          == ["the pools' column head does not use pbPoolsSection", "the board's script still reads the plain word for a pool (topologyLlamaServersSection)"],
          "negative: голова колонки пулов читает прежнее слово — названо")
    check(ColumnTitles.script_problems(js.replace('label: t("pbPoolsSection")', 'label: t("topologyLlamaServersSection")'))
          == ["the strip's path names its columns with other words than the heads", "the board's script still reads the plain word for a pool (topologyLlamaServersSection)"],
          "negative: полоса называет колонки другими словами, чем головы, — названо (одно слово — один смысл)")
    check(ColumnTitles.script_problems(js + 'this.head(t("pbSetsSection"),\n') == ["the board's script still names a column of sets"],
          "negative: колонка наборов вернулась в скрипт — названо")
    check(ColumnTitles.script_problems(js.replace('<span class="pb-pool-id" aria-hidden="true">id:</span>', "")) == ["a pool's card does not say id: before its name"],
          "negative: у карточки пула нет подписи «id:» перед названием — названо (владелец, 2026-10-14)")
    check(ColumnTitles.script_problems(js.replace('<span class="pb-pool-id" aria-hidden="true">id:</span>', '<span class="pb-pool-id">id:</span>'))
          == ["a pool's card does not say id: before its name"],
          "negative: подпись не скрыта от читалок экрана (поле имени говорит само) — названо")
    check(ColumnTitles.script_problems(js.replace('data-pb-pool-name', 'data-pb-set-name')) == ["a pool's card does not say id: before its name"],
          "negative: подпись стоит перед другим полем, не перед именем пула — названо")


def test_the_board():
    print("доска (static/js):")
    files = {path.stem: path.read_text(encoding="utf-8") for path in sorted(LANGS.glob("*.js"))}
    check(len(files) == 6, f"языков 6 ({len(files)})")
    bad = ColumnTitles.language_problems(files)
    check(bad == [], "название колонки пулов «ID (слово языка)» во всех языках, а колонки наборов нет ни в одном" + (f" — {'; '.join(bad[:3])}" if bad else ""))
    bad = ColumnTitles.script_problems(BOARD.read_text(encoding="utf-8"))
    check(bad == [], "Маршрутизация: голова и путь в полосе называют колонку одними словами, карточка пула говорит «id:»" + (f" — {'; '.join(bad)}" if bad else ""))


for fn in (test_the_rule, test_the_board):
    fn()

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("routing titles snapshot holds")
