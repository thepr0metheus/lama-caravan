#!/usr/bin/env python3
"""CI guard: the maker's numbers are held to the sentence the maker said them in.

`modelParams` is prose for a person. 28 of the 59 cards name a value twice — once for the mode with reasoning,
once without, or once as the model's trained context and once as an example in a command — so a number read out of
prose is a choice, not a fact: whoever reads it picks which of the two to believe. Only a value a card states ONCE
can become a cell's default, and a sentence that names a mode states its value for that mode.

So `contract/model_defaults.json` holds the sentence, `rust/crates/admin/src/models/defaults.rs` holds the numbers,
and this guard holds them to each other:

  1. every number in the program's table must be readable back out of its own sentence;
  2. the sentence must name the field the way the program names it — the flag from `config/args.rs`, so a field the
     program cannot write (a penalty: the caravan writes no flag for one) cannot be a row;
  3. a sentence may name a mode only when it also says the value holds for all of them; a use word counts as a mode
     word ("для текста" states its value for text), and it is read at the start of a word, so that "Контекст" is not
     a sentence about a use;
  4. every field is held to the list the program keeps (`ConfigFields::ALL`), the same home
     `scripts/check_field_homes.py` holds every other field to.

Output is Russian on purpose: it is read by the operator running the guards.

Run: python3 scripts/check_model_defaults.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from _contract import Contract  # noqa: E402
from _rust_source import RustSource  # noqa: E402

TABLE = "model_defaults"
ROW = re.compile(r'\(\s*"([^"]+)",\s*&\[([^\]]*)\]')
PAIR = re.compile(r'\("([^"]+)", "([^"]+)"\)')
FLAG = re.compile(r'\("(--[a-z0-9][a-z0-9-]*)", "([A-Z_]+)"\)')
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def flag_of_field():
    """field → flag, as the program writes them (`config/args.rs`). Nothing for a field it has no flag for."""
    code = RustSource.code_lines((ROOT / "rust/crates/admin/src/config/args.rs").read_text(encoding="utf-8"))
    return {field: flag for line in code for flag, field in FLAG.findall(line)}


def main():
    table = Contract.table(TABLE)
    fields, mode_words, for_all = table["fields"], table["modeWords"], table["forAll"]
    flags = flag_of_field()
    if not flags:
        print(f"{TABLE}: FAILED — config/args.rs не даёт ни одного флага: охрана смотрит мимо программы")
        return 1
    program_fields = RustSource.words("admin/src/config/fields.rs", "ALL")

    rows = {}
    # The rows are read as the program writes them, not as a copy: rustfmt may wrap a long row over two lines,
    # so the table is read as one text, not line by line.
    code = " ".join(RustSource.code_lines((ROOT / "rust/crates/admin/src/models/defaults.rs").read_text(encoding="utf-8")))
    for model, body in ROW.findall(code):
        rows.setdefault(model, []).append(dict(PAIR.findall(body)))
    if not rows:
        print(f"{TABLE}: FAILED — rust/crates/admin/src/models/defaults.rs не даёт ни строки: охрана смотрит мимо таблицы")
        return 1

    problems = []
    if not fields:
        problems.append("`fields` не называет ни поля: охранке не на что смотреть")
    for field in fields:
        # A field the table has the right to hold must be one the program can say. This is why a penalty is not
        # here: the cards name presence_penalty and repetition_penalty, but the caravan writes no flag for one.
        if field not in program_fields:
            problems.append(f"`fields`: {field} — поля у программы нет (`ConfigFields::ALL`)")
        elif field not in flags:
            problems.append(f"`fields`: {field} — караван пишет для него флаг? нет, и ячейка не может это сказать")

    for row in table["rows"]:
        model, said = row["model"], row["said"]
        where = f"{model}: {said[:60]}"
        held = rows.get(model)
        if not held:
            problems.append(f"{where} — программы с этим папкой нет")
            continue
        if len(held) > 1:
            problems.append(f"{where} — программа называет эту папку дважды")
            continue
        held = held[0]
        for field, value in row["values"].items():
            if field not in fields:
                problems.append(f"{where} — {field} не входит в `fields`")
                continue
            if field not in program_fields:
                problems.append(f"{where} — {field}: поля у программы нет (`ConfigFields::ALL`)")
                continue
            flag = flags.get(field)
            if not flag:
                problems.append(f"{where} — {field}: караван пишет для него флаг? нет, и ячейка не может это сказать")
                continue
            if value != held.get(field):
                problems.append(f"{where} — {field}: программа говорит {held.get(field)}, таблица говорит {value}")
                continue
            if not NUMBER.fullmatch(value):
                problems.append(f"{where} — {field}: {value} — не число")
                continue
            if flag.strip("-").replace("-", "_") not in said.replace("-", "_"):
                problems.append(f"{where} — {field}: предложение не называет его так, как программа ({flag})")
            if value not in said:
                problems.append(f"{where} — {field}: {value} нет в предложении, откуда оно взято")
            named = [word for word in mode_words
                     if re.search(rf"(?<![a-zа-ё]){re.escape(word.lower())}", said.lower())]
            if named and not any(phrase in said.lower() for phrase in for_all):
                problems.append(f"{where} — предложение называет режим ({', '.join(named)}), значит значение — выбор")

    if problems:
        print(f"{TABLE}: FAILED — число не держится предложением, которое его сказало")
        for problem in problems:
            print("  - " + problem)
        return 1

    values = sum(len(row["values"]) for row in table["rows"])
    print(f"{TABLE} OK: {len(table['rows'])} строк, {values} значений, каждое читается обратно из своего предложения")
    return 0


if __name__ == "__main__":
    sys.exit(main())
