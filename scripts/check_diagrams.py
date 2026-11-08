#!/usr/bin/env python3
"""CI guard: a diagram in `diagrams/` says what a guard holds, and points at the guard that still holds it.

The diagrams of `scripts/check_media_reader.py` were written so a rule can be read as a shape: who decides, where a fact
is named once, what a file may not say. Three ways a diagram lies, and each has happened in a document somewhere: a
diagram the README does not name is a diagram nobody reads; a number in a title that is not the number the guard checks
the rule at is the defect the guard's own rule numbering was written for; and a diagram pointing at a list the guard no
longer has points at nothing, while still looking like a rule.

The rule, held here:
1. Every diagram in `diagrams/` is named in `diagrams/README.md` with what it holds, and the README names no file the
   folder does not have. A row that promises a diagram is a promise the tree must keep, both ways, and the number a row names is the number of the diagram it lists.
2. Every rule the guard checks has exactly one diagram, and the number of that diagram is the number the guard holds the
   rule at — read from the `# N.` comments in its `main()`, in the order it checks them. The number is in the file name
   and in the title, and the two must agree.
3. Each diagram ends with the line `Проверяет:`, naming the guard and what in that guard holds its rule (a list or a
   check). The name it names must exist in the guard's source: a diagram pointing at a list the guard does not have
   points at nothing.
4. The diagram with no number holds all the rules of its guard: every number the guard checks must appear in it, so the
   general view cannot quietly drop one.
5. Every diagram is a diagram: it has a mermaid block. Prose with no block is not a diagram, and the README cannot
   promise one.
6. The legend in `diagrams/README.md` names each shape the diagrams draw, and no shape it names is left unused: an arrow,
   a dashed link, a dashed frame. A legend that describes a shape nobody draws describes a rule nobody has. And the diagram
   that draws the dashed frame must name in its words what that frame is — an absence named as an absence, not a value.

Run: python3 scripts/check_diagrams.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIAGRAMS = ROOT / "diagrams"
README = DIAGRAMS / "README.md"

#: A row of diagrams/README.md: the diagram, what it holds, what checks it.
ROW = re.compile(r"^\|\s+`([^`]+\.md)`\s+\|\s*([^|]*)\|\s*([^|]*)\|", re.MULTILINE)
NUMBER = re.compile(r"\b(\d+)\b")
#: A per-rule diagram: `# Правило N: ...`, and its file name carries the same number.
TITLE = re.compile(r"^# Правило (\d+):", re.MULTILINE)
FILE_NUMBER = re.compile(r"-(\d+)-")
#: The line each diagram ends with: the guard it points at, and what in that guard holds its rule.
CHECK_LINE = re.compile(r"^Проверяет:.*", re.MULTILINE)
GUARD = re.compile(r"`scripts/(check_[a-z_]+\.py)`")
HOLDS = re.compile(r"(?:список|проверка)\s+([A-Z_]{3,}|built)")
#: A rule number inside the general diagram's labels: `правило 7`.
RULE_IN_LABEL = re.compile(r"правило (\d+)", re.IGNORECASE)
#: The shapes the legend of diagrams/README.md describes, and what draws each of them.
LEGEND = {"стрелка": "-->", "пунктир": "-.->", "штриховая рамка": "classDef"}


def rules_of(guard: Path) -> list:
    """The numbers the guard holds its rules at, in the order it checks them: the `# N.` comments in main()."""
    body = guard.read_text(encoding="utf-8").split("def main", 1)[-1]
    return sorted(set(int(n) for n in re.findall(r"^\s*#\s*(\d+)\.", body, re.MULTILINE)))


def main() -> int:
    if not DIAGRAMS.is_dir():
        print("diagrams: FAILED — diagrams/ отсутствует", file=sys.stderr)
        return 1
    diagrams = sorted(p for p in DIAGRAMS.glob("*.md") if p.name != "README.md")
    if not diagrams:
        print("diagrams: FAILED — в diagrams/ нет ни одной диаграммы", file=sys.stderr)
        return 1
    if not README.is_file():
        print("diagrams: FAILED — diagrams/README.md отсутствует", file=sys.stderr)
        return 1
    readme = README.read_text(encoding="utf-8")

    problems = []
    #: 1. the README and the folder say the same list, both ways, and the number in a row is the diagram's number.
    rows = ROW.findall(readme)
    listed = {name for name, _, _ in rows}
    for diagram in diagrams:
        if diagram.name not in listed:
            problems.append(f"diagrams/{diagram.name}: диаграммы нет в diagrams/README.md — её никто не читает")
    for name in sorted(listed):
        if not (DIAGRAMS / name).is_file():
            problems.append(f"diagrams/README.md: строка обещает {name}, которого в папке нет")
    for name, holds, checks in rows:
        if not holds.strip() or not checks.strip():
            problems.append(f"diagrams/README.md: строка о {name} не говорит, что диаграмма держит или что проверяет")
        number = int(NUMBER.search(holds).group(1)) if NUMBER.search(holds) else None
        title = TITLE.search((DIAGRAMS / name).read_text(encoding="utf-8")) if (DIAGRAMS / name).is_file() else None
        if number is not None and title and number != int(title.group(1)):
            problems.append(f"diagrams/README.md: строка о {name} называет правило {number}, диаграмма — "
                            f"{title.group(1)}; номер сказан дважды, и дважды по-разному")

    #: 2, 3, 5. each diagram's number is the number its guard holds the rule at, and the guard still has the list.
    by_guard = {}
    general = []
    for diagram in diagrams:
        text = diagram.read_text(encoding="utf-8")
        line = CHECK_LINE.search(text)
        if not line:
            problems.append(f"diagrams/{diagram.name}: строки Проверяет: нет — диаграмма ничего не проверяет")
            continue
        guard_name = GUARD.search(line.group(0))
        if not guard_name:
            problems.append(f"diagrams/{diagram.name}: в строке Проверяет: нет гварда — диаграмма указывает в никуда")
            continue
        guard = ROOT / "scripts" / guard_name.group(1)
        if not guard.is_file():
            problems.append(f"diagrams/{diagram.name}: гварда {guard_name.group(1)} нет — диаграмма указывает в никуда")
            continue
        if not re.search("```mermaid", text):
            problems.append(f"diagrams/{diagram.name}: нет блока mermaid — это текст, а не диаграмма")
        number = TITLE.search(text)
        if not number:
            general.append((diagram, guard_name.group(1)))
            continue
        held = HOLDS.search(line.group(0))
        if not held:
            problems.append(f"diagrams/{diagram.name}: строка Проверяет: не называет, что в гварде держит правило")
        elif held.group(1) not in guard.read_text(encoding="utf-8"):
            problems.append(f"diagrams/{diagram.name}: {guard_name.group(1)} не держит {held.group(1)!r} — диаграмма "
                            f"указывает на список, которого гвард уже не имеет")
        in_name = FILE_NUMBER.search(diagram.name)
        if not in_name:
            problems.append(f"diagrams/{diagram.name}: номера правила нет в имени файла")
            continue
        if int(in_name.group(1)) != int(number.group(1)):
            problems.append(f"diagrams/{diagram.name}: файл назван правилом {in_name.group(1)}, заголовок говорит "
                            f"{number.group(1)} — номер сказан дважды, и дважды по-разному")
        order = rules_of(guard)
        if int(number.group(1)) not in order:
            problems.append(f"diagrams/{diagram.name}: гвард {guard_name.group(1)} проверяет правила {order}, а "
                            f"диаграмма называет {number.group(1)} — номера, которого у гварда нет")
        by_guard.setdefault(guard_name.group(1), set()).add(int(number.group(1)))

    #: 2. every rule the guard checks has exactly one diagram.
    for guard_name, drawn in by_guard.items():
        order = rules_of(ROOT / "scripts" / guard_name)
        missing = sorted(set(order) - drawn)
        if missing:
            problems.append(f"diagrams/: гвард {guard_name} проверяет правила {order}, а диаграммы есть только для "
                            f"{sorted(drawn)} — правил {missing} нет")

    #: 4. the general diagram holds every rule of its guard, as it draws them — the numbers it says in its labels, not
    #: in its prose, because the prose of a general view is allowed to name a rule without drawing it.
    for diagram, guard_name in general:
        text = diagram.read_text(encoding="utf-8")
        order = rules_of(ROOT / "scripts" / guard_name)
        said = {int(n) for n in RULE_IN_LABEL.findall(text.split("```")[1])}
        missing = sorted(set(order) - said)
        if missing:
            problems.append(f"diagrams/{diagram.name}: общая диаграмма рисует правила {sorted(said)}, а гвард "
                            f"{guard_name} проверяет {order} — вид, который пропускает правило, не является видом "
                            f"всех правил")

    #: 6. the legend names the shapes the diagrams use, both ways, and a dashed frame names what it draws.
    for word, shape in LEGEND.items():
        used = any(shape in p.read_text(encoding="utf-8") for p in diagrams)
        named = word in readme.lower()
        if used and not named:
            problems.append(f"diagrams/README.md: легенда не называет форму «{word}», которую диаграммы рисуют")
        if named and not used:
            problems.append(f"diagrams/README.md: легенда описывает «{word}», которой ни в одной диаграмме нет")
    for diagram in diagrams:
        text = diagram.read_text(encoding="utf-8")
        if "classDef" in text and "отсутствие" not in text.split("```")[-1].lower():
            problems.append(f"diagrams/{diagram.name}: штриховая рамка названа отсутствием, а в словах этой диаграммы "
                            f"отсутствия нет")

    if problems:
        print("diagrams: FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("  diagrams/README.md lists what each diagram holds, the number of a diagram is the number the guard "
              "checks the rule at, a diagram names the guard and the list that holds it, the general diagram holds "
              "every rule, and a dashed frame is drawn where the legend says an absence is named as an absence",
              file=sys.stderr)
        return 1
    print(f"diagrams OK: {len(diagrams)} диаграмм, {sum(len(v) for v in by_guard.values())} по правилам, "
          f"{len(rows)} строк в README, блок mermaid в каждой")
    return 0


if __name__ == "__main__":
    sys.exit(main())
