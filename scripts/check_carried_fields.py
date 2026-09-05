#!/usr/bin/env python3
"""Поле, которое едет через несколько пересборок, обязано быть НАЗВАНО в каждой.

Настройка клиентской прокси-ячейки проделывает путь от документа контроллера до
ответа прокси, и на этом пути её четырежды ПЕРЕСОБИРАЮТ: класс формы записи,
нормализатор на записи маршрута, нормализатор на чтении маршрута и мост, что
возит копию от назначения к маршруту. Каждая пересборка строит словарь с нуля,
поэтому поле, которого она не называет, исчезает — молча, без ошибки, и
замечается через слой или два, когда клиент получает не то, что задал оператор.

За одну работу это случилось ЧЕТЫРЕ раза подряд. Первые три нашлись красным
пином, четвёртый — только потому, что предыдущие три научили искать. Список
полей и список границ лежат здесь, и гвард требует, чтобы каждое поле было
названо на каждой границе.

Здесь стояло «пятого не будет». Пятый был — и этот гвард его не увидел: сверка
прокси собирала строку назначения ЗАНОВО по живому отчёту клиента, а рукописный
список границ про неё не знал и печатал зелёное. Рукописный список устаревает
молча — это уже было доказано на списке скриптов в CI. Поэтому ниже добавлено
правило, которое ловит не перечисленное место, а САМУ ФОРМУ дефекта: сборку
назначения с нуля там, где рядом лежит сохранённая запись.

Гвард падает ДВУМЯ способами. На дефекте: поле названо не везде. И когда
перестаёт что-либо находить: граница исчезла, переехала или переименована —
тогда он не молчит, а говорит, что проверять стало нечего.

Запуск: python3 scripts/check_carried_fields.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Поля, которые обязаны пережить весь путь. Добавляешь такое поле — впиши сюда,
#: и гвард сразу скажет, на какой границе ты его забыл назвать.
CARRIED_FIELDS = ("contextLength", "contextAuto", "modelName")

#: Границы пересборки: файл → функция, которая собирает запись заново.
#: Функция названа не для красоты — по ней проверяется, что граница на месте.
REBUILD_BOUNDARIES = {
    "caravan/domain/client_proxy.py": "to_dict",
    "caravan/admin/router_dsl.py": "normalize_agent_proxy_route",
    "caravan/proxy/config.py": "normalize_route",
    "caravan/admin/fleet_clients.py": "reconcile_proxy_metadata",
}

#: Ниже этого числа границ проверка бессмысленна: значит список отстал от кода.
MIN_BOUNDARIES = 4


def _emitted_keys(source, func_name):
    """Имена, которые функция КЛАДЁТ в собираемую запись, или None если её нет.

    Считаются два написания, и только они: ключ словарного литерала
    (``{"поле": ...}``) и цель присваивания по ключу (``out["поле"] = ...``).
    Всё остальное упоминание полем не является, и это не педантизм — обе
    предыдущие редакции этого гварда зеленели на сломанном дереве: первая
    удовлетворялась словом в КОММЕНТАРИИ, вторая — ЧТЕНИЕМ поля из входа
    (``route.get("поле")``), которое остаётся на месте, даже когда запись
    переименовали. Проверять надо то, что кладут, а не то, что рядом написано.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    target = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name), None)
    if target is None:
        return None
    keys = set()
    for node in ast.walk(target):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            for tgt in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                for sub in ast.walk(tgt):
                    if (isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant)
                            and isinstance(sub.slice.value, str)):
                        keys.add(sub.slice.value)
    return keys


#: Где живут классы формы записи: внутри них собирать запись с нуля — работа,
#: снаружи — дефект.
DOMAIN_DIR = "caravan/domain/"

#: Конструкторы, которые ПЕРЕНОСЯТ уже сохранённое. Всё остальное собирает
#: назначение с нуля и роняет то, чего не назвали.
CARRYING_CONSTRUCTORS = ("from_raw", "rewired")


def _bare_assignment_builds():
    """Места вне домена, где `AgentAssignment(...)` зовут напрямую.

    Пятая граница выглядела именно так: `AgentAssignment(aid, [route])` рядом с
    `existing[aid]`, из которого ничего не взяли. Классу передали только то, что
    знает живой отчёт, — и всё, что знал оператор, исчезло.
    """
    hits, call_sites = [], 0
    for path in sorted(ROOT.glob("caravan/**/*.py")):
        rel = path.relative_to(ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            # Непрочитанный файл — это НЕ «в нём ничего нет». Первая редакция
            # правила молча пропускала такой файл, и мутант, сломавший разбор,
            # оставил гвард зелёным: ровно то самое отсутствие, нарисованное
            # нормой, ради которого весь этот гвард и написан.
            hits.append(f"{rel}: не разбирается ({exc.msg}, строка {exc.lineno}) — "
                        f"проверить сборку назначения в нём нечем")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) \
                    and func.value.id == "AgentAssignment":
                call_sites += 1
                if rel.startswith(DOMAIN_DIR) or func.attr in CARRYING_CONSTRUCTORS:
                    continue
                hits.append(f"{rel}:{node.lineno}: AgentAssignment.{func.attr}(…) — "
                            f"не переносящий конструктор")
            elif isinstance(func, ast.Name) and func.id == "AgentAssignment":
                call_sites += 1
                if rel.startswith(DOMAIN_DIR):
                    continue
                hits.append(f"{rel}:{node.lineno}: назначение собирается с нуля — "
                            f"возьми {' или '.join(CARRYING_CONSTRUCTORS)}, иначе всё, "
                            f"что задал оператор, исчезнет")
    return hits, call_sites


def main():
    problems = []
    checked = 0
    for rel, marker in sorted(REBUILD_BOUNDARIES.items()):
        path = ROOT / rel
        if not path.exists():
            problems.append(f"{rel}: граница исчезла — файла нет")
            continue
        emitted = _emitted_keys(path.read_text(encoding="utf-8"), marker)
        if emitted is None:
            problems.append(f"{rel}: не найдена функция «{marker}» — граница переехала или "
                            f"переименована, и гвард больше не знает, что проверять")
            continue
        checked += 1
        for field in CARRIED_FIELDS:
            if field not in emitted:
                problems.append(f"{rel}: «{marker}» не называет поле «{field}» — эта пересборка его уронит")
    bare, call_sites = _bare_assignment_builds()
    problems.extend(bare)
    if call_sites < 3:
        problems.append(f"вызовов AgentAssignment найдено {call_sites} — класс переехал или "
                        f"переименован, и правило о сборке с нуля больше ничего не проверяет")
    if checked < MIN_BOUNDARIES:
        problems.append(f"границ осмотрено {checked}, ожидалось не меньше {MIN_BOUNDARIES}: "
                        f"список в этом гварде отстал от кода")
    if problems:
        print("carried fields FAILED:")
        for p in problems:
            print("  - " + p)
        print("\nПоле, едущее через пересборки, должно быть названо в каждой: "
              "иначе оно исчезает молча (docs/why.md).")
        return 1
    print(f"carried fields OK: {len(CARRIED_FIELDS)} полей названы на всех {checked} границах "
          f"пересборки; {call_sites} сборок назначения — все переносящие")
    return 0


if __name__ == "__main__":
    sys.exit(main())
