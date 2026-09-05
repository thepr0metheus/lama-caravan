#!/usr/bin/env python3
"""Живой патчер доски не пересказывает то, что уже говорит строитель карточки.

Доска рисуется дважды: строитель собирает карточку клиента, а патчер на каждом
тике опроса переписывает в ней живые куски, не трогая остального. Пока один и
тот же факт собирают оба, они расходятся — и расходятся молча.

Так и вышло с возрастом ответа. Строитель научили говорить «не отвечал» тому,
кто НИКОГДА не отвечал (раньше он печатал «?s ago», то есть утверждал, что
ответ был, просто время неизвестно). Патчер остался со своим шаблоном — и
починка держалась ровно один кадр: первый же тик возвращал «?s ago». Снимки
этого не видели, потому что пины стоят на строителе, а патчер в них не
загружается.

Гвард падает ДВУМЯ способами: когда факт снова собирают где-то ещё, и когда
единственный источник перестаёт его собирать — тогда охранять нечего.

Запуск: python3 scripts/check_board_live_patch.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Факт → (как он выглядит в коде, единственный файл-источник, имя функции).
#: Ищется ШАБЛОН СБОРКИ, а не слова: чтение того же факта никому не запрещено.
SHARED_FACTS = {
    "возраст ответа клиента": (
        re.compile(r"`\$\{[^`]*\}s ago`"),
        "static/js/topology-activity.js",
        "clientAgeText",
    ),
}

#: Файлы, которые рисуют доску: и строитель, и патчер, и всё между ними.
BOARD_FILES = ("static/js/topology-render.js", "static/js/topology-activity.js",
               "static/js/topology-proxies.js", "static/js/remote-cells.js")


def main():
    problems = []
    for fact, (pattern, source_rel, func) in SHARED_FACTS.items():
        source = ROOT / source_rel
        if not source.exists():
            problems.append(f"{fact}: источник {source_rel} исчез — охранять нечего")
            continue
        text = source.read_text(encoding="utf-8")
        if f"function {func}" not in text:
            problems.append(f"{fact}: в {source_rel} нет функции «{func}» — источник переехал "
                            f"или переименован, и правило больше ничего не проверяет")
            continue
        if not pattern.search(text):
            problems.append(f"{fact}: «{func}» больше не собирает этот факт — либо он собирается "
                            f"теперь где-то ещё, либо проверять нечего")
            continue
        for rel in BOARD_FILES:
            if rel == source_rel:
                continue
            path = ROOT / rel
            if not path.exists():
                continue
            for num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    problems.append(f"{rel}:{num}: {fact} собирается второй раз — зови «{func}» "
                                    f"из {source_rel}, иначе починка одного места держится один кадр")
    if problems:
        print("board live patch FAILED:")
        for p in problems:
            print("  - " + p)
        print("\nПатчер и строитель, говорящие один факт порознь, расходятся молча (docs/why.md).")
        return 1
    print(f"board live patch OK: {len(SHARED_FACTS)} общих фактов — каждый собирается в одном месте")
    return 0


if __name__ == "__main__":
    sys.exit(main())
