#!/usr/bin/env python3
"""Value snapshot: `untranslated()` of scripts/check_messages_i18n.py — the rule
that tells a translation from English left standing, shared by the board's
tables and the /hf table (scripts/check_i18n_calls.py).

The english-phrase half was dead until 2026-10-07: the identifier pattern was
compiled under one re.IGNORECASE, so its ALLCAPS alternative matched every latin
word, every word was stripped first, and a whole English sentence in the Chinese
table passed. Each case below is a value and the verdict it must get.

DroppedLetters (the same file) is the rule that tells a word written WITHOUT its diacritics ("modele",
"uebersetzt") from one written right: the file itself is the witness, so a case is a small table of strings
and the findings it must give. The strings of six commits stood plain in seven tables for two months
(2026-08-15 to 10-13) while the key was there and the text was no copy of the English.

Run: python3 scripts/test_i18n_untranslated.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_messages_i18n import DroppedLetters, untranslated  # noqa: E402

CASES = [
    # (lang, key, value, en value, verdict, what it shows)
    ("zh", "k", "Open the settings page and turn on the switch", "x", "english-phrase",
     "английское предложение в китайской таблице — найдено"),
    ("ja", "k", "モデルを読み込む Open the settings page", "x", "english-phrase",
     "английская фраза внутри японского текста — найдена"),
    ("ru", "k", "Модель грузится, wait for the model please", "x", "english-phrase",
     "английская фраза внутри русского текста — найдена"),
    ("zh", "k", "请 Open the settings", "x", "english-phrase",
     "три латинских слова подряд — уже фраза"),
    ("zh", "k", "请 Open settings", "x", None,
     "negative: два латинских слова — ещё не фраза"),
    ("zh", "k", "打开设置页面", "x", None,
     "negative: перевод без латиницы — чисто"),
    ("zh", "k", "使用 llama.cpp 和 GGUF 模型", "x", None,
     "negative: имена продуктов и ALLCAPS — не фраза"),
    ("zh", "k", "--ctx-size 和 /v1/models 的 EXTRA_ARGS", "x", None,
     "negative: флаг, путь и snake_case — не фраза"),
    ("zh", "k", "开启“Device code authorization”，然后重新开始", "x", None,
     "negative: подпись настройки ChatGPT, как её пишет ChatGPT, — имя, не фраза"),
    ("ja", "k", "無料の Moonshine Community License", "x", None,
     "negative: название лицензии — имя, не фраза"),
    ("zh", "k", "OPENING THE CONNECTION TO THE MODEL", "x", None,
     "as-is: предложение заглавными читается как идентификаторы — не находится"),
    ("de", "k", "Open the settings page and turn on the switch",
     "Open the settings page and turn on the switch", "en-copy",
     "латинский язык: дословная копия английской прозы — найдена"),
    ("de", "k", "Token speed", "Token speed", None,
     "negative: короткая одинаковая подпись в латинском языке — чисто"),
    ("fr", "k", "авто", "auto", "russian-leak",
     "русское значение в чужой таблице — найдено"),
    ("zh", "appAcronym", "Lightweight Agent Model Access", "x", None,
     "negative: ключ из списка исключений — не проверяется"),
]

#: (lang, {key: value}, findings, what it shows). A finding is (key, why), in key order.
DROPPED = [
    ("de", {"a": "Nur für Gruppen", "b": "Das ist für jeden Client", "c": "Gilt für alle Modelle",
            "d": "Gilt fuer alle Modelle"},
     [("d", "dropped-letters «fuer» for «für»")],
     "a plain spelling beside three right ones is dropped letters: «fuer» for «für»"),
    ("de", {"a": "Nur für Gruppen", "b": "Das ist für jeden Client", "c": "Gilt fuer alle Modelle"}, [],
     "negative: two right spellings beside one plain are no proof — a language has real pairs (Alter / älter)"),
    ("de", {"a": "Sprache, in die uebersetzt wird"}, [],
     "as-is: a word the file never writes right has no witness — nothing to hold it against"),
    ("fr", {"a": "Ce modèle charge", "b": "Un modèle de chat", "c": "Le modèle est prêt", "d": "Ce modele charge"},
     [("d", "dropped-letters «modele» for «modèle»")],
     "French: «modele» beside three «modèle»"),
    ("fr", {"a": "Il est fermé", "b": "Un port fermé", "c": "Tout est fermé", "d": "Elle ferme la porte"}, [],
     "negative: «ferme» is a verb, listed in PLAIN_WORDS_ALLOWED with its reason — not dropped letters"),
    *[("fr", {"a": "Ce modèle charge", "b": "Un modèle de chat", "c": "Le modèle est prêt", "d": text}, [],
       f"negative: {what} is not the language's word")
      for what, text in (("a flag", "Voir --modele-x"), ("a placeholder", "Voir {modele}"),
                         ("code in backticks", "Voir `modele`"), ("a snake_case name", "Voir modele_x"),
                         ("a path", "Voir /etc/modele"), ("an ALLCAPS name", "Voir MODELE"))],
    ("pt", {"a": "Não pode", "b": "Não existe", "c": "Não há", "d": "nao pode"},
     [("d", "dropped-letters «nao» for «não»")],
     "Portuguese: «nao» beside three «não»"),
    ("tr", {"a": "yalnızca bu", "b": "yalnızca şu", "c": "yalnızca o", "d": "yalnizca bu"},
     [("d", "dropped-letters «yalnizca» for «yalnızca»")],
     "Turkish: «yalnizca» beside three «yalnızca»"),
    ("tr", {"a": "İstek başına", "b": "İstek sayısı", "c": "İstek gelir", "d": "istek geldi"}, [],
     "negative: a capital İ is an «i», not an accented twin — «İstek» and «istek» are one word"),
    ("vi", {"a": "Giay phep phi thuong mai va chi tao ngon ngu dich"},
     [("a", "dropped-letters: no tone mark in a sentence of 11 words")],
     "Vietnamese: a sentence of 11 words with no tone mark is written plain"),
    ("vi", {"a": "Giấy phép phi thương mại và chỉ tạo ngôn ngữ đích", "b": "Xong", "c": "trong {names}",
            "d": "Mot hai ba bon"}, [],
     "negative: a marked sentence, and a short plain label (4 words and fewer) are real Vietnamese"),
    ("vi", {"appAcronym": "Local And Multi-backend Adaptive Computation And Routing Across Various AI Nodes"}, [],
     "negative: a key of TRANSLATION_ALLOWLIST is not looked at"),
    ("es", {"a": "en cuanto llegue", "b": "¿cuánto?", "c": "cuánto tarda", "d": "cuánto cuesta"}, [],
     "negative: «cuanto» is listed in PLAIN_WORDS_ALLOWED (the conjunction has no accent)"),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    print("untranslated(): перевод или английский текст:")
    for lang, key, value, en_value, want, msg in CASES:
        got = untranslated(lang, key, value, en_value)
        check(got == want, msg if got == want else f"{msg}\n        ожидалось {want!r}, получено {got!r}")
    print()
    print("DroppedLetters: слова без диакритики:")
    for lang, strings, want, msg in DROPPED:
        got = DroppedLetters(lang, strings).findings()
        check(got == want, msg if got == want else f"{msg}\n        ожидалось {want!r}, получено {got!r}")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"i18n untranslated snapshot holds: {len(CASES)} values, {len(DROPPED)} tables of strings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
