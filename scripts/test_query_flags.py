#!/usr/bin/env python3
"""What counts as "yes" in a query parameter — the same answer on every endpoint.

Seven boolean query flags, written four different ways. Five of them accept
`1`, `true` and `yes`; the two spelled `force` accept only the literal `"1"`.
So `?force=true` on the benchmark endpoints is read as false: the caller asks for
a fresh fetch, gets a 200 and a cached answer, and nothing anywhere says the flag
was ignored. The browser always sends `=1`, so this only bites a person driving
the API by hand — which is a documented way to use it.

Elsewhere in the caravan a truthy config value is `1/true/yes/on`, case
insensitive. Two vocabularies for one idea, and the narrower one is silent about
what it drops.

This pins what each flag accepts so the answer is one answer.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


#: Every spelling a caller might reasonably send, and whether it means yes.
YES = ("1", "true", "TRUE", "True", "yes", "YES", "on", " 1 ", "true ")
NO = ("0", "false", "no", "off", "", "  ", "banana", "2", "-1")


def main():
    from caravan.admin.routes import _flag

    for value in YES:
        got = _flag({"f": [value]}, "f")
        check(f"«{value}» значит да", got is True, f"получено {got!r}")
    for value in NO:
        got = _flag({"f": [value]}, "f")
        check(f"«{value}» значит нет", got is False, f"получено {got!r}")

    check("отсутствующий параметр — нет", _flag({}, "f") is False)
    check("отсутствующий с умолчанием да — да", _flag({}, "f", default=True) is True)
    check("присутствующий бьёт умолчание",
          _flag({"f": ["0"]}, "f", default=True) is False)
    # A query string parses to lists; an empty list is not the same as absent.
    check("пустой список — как отсутствие", _flag({"f": []}, "f") is False)
    check("несколько значений — берётся первое", _flag({"f": ["1", "0"]}, "f") is True)

    # The vocabulary must be the SAME one the rest of the caravan uses for a
    # truthy config value, or "on" works in a config file and not in a URL.
    from caravan.common.flags import truthy
    mismatched = [v for v in YES + NO
                  if _flag({"f": [v]}, "f") is not truthy(v)]
    check("словарь тот же, что у конфигов", not mismatched, f"расходятся: {mismatched}")
    # And the config side really does read through it, so "on" cannot mean yes
    # in a cell config and no in a URL.
    from caravan.admin import config_builder
    check("конфиг разбирает «да» ТЕМ ЖЕ объектом, а не своей копией",
          config_builder._flag_truthy is truthy,
          "config_builder завёл собственный список заново")

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
