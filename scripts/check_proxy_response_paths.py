#!/usr/bin/env python3
"""Гвард: полный ответ прокси собирает ОДИН помощник, а не каждое место заново.

Ответ с телом обязан нести три заголовка: тип, длину и `Connection: close`.
Последний — не украшение. Обработчик говорит по HTTP/1.1, поэтому клиент,
попросивший keep-alive (а так делает по умолчанию каждый современный SDK),
получит постоянное соединение, если не сказать иначе. Успешный путь закрывает
его явно, но исключение перепрыгивает через это место, и одна из рукописных
копий блока заголовок потеряла: поток слушателя парковался в readline() без
таймаута ровно на столько, сколько клиент держал сокет.

Копий было шесть по пять строк, и дефект — одна строка, отсутствующая в одной
из них. Шесть сведены к одному помощнику; два места остались своими законно —
ретрансляция заголовков апстрима и отдача переведённого тела, — поэтому правило
не «всё через помощника», а «объявил длину — объяви и закрытие».

Падает четырьмя способами: длина без закрытия; закрытие ГЛУБЖЕ длины, то есть
под условием, до которого можно не дойти; помощник перестал ставить один из трёх
заголовков; мест с длиной осталось меньше двух — значит гвард смотрит не туда.

Запуск: python3 scripts/check_proxy_response_paths.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "caravan" / "proxy" / "handler.py"
HELPER = "_send_bytes"

problems = []

if not TARGET.exists():
    print(f"proxy response paths: FAILED\n  - {TARGET} не найден — охранять нечего")
    sys.exit(1)

tree = ast.parse(TARGET.read_text(encoding="utf-8"))
functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]


def _depths(tree):
    """Глубина вложенности каждого вызова заголовка внутри своей функции.

    Наличия в тексте недостаточно. Первая версия гварда считала блок ответа
    закрытым, если между send_response и end_headers ГДЕ-ТО встретилось нужное
    имя, — и пропускала `if False: send_header("Connection", ...)`, то есть
    заголовок, до которого исполнение не доходит. Проверено руками: гвард
    говорил OK, а снимок в тот же момент краснел пятью проверками.
    """
    depth = {}

    def walk(node, level):
        for child in ast.iter_child_nodes(node):
            deeper = level + 1 if isinstance(child, (ast.If, ast.For, ast.While,
                                                     ast.Try, ast.With)) else level
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "send_header" and child.args
                    and isinstance(child.args[0], ast.Constant)):
                depth[(child.lineno, str(child.args[0].value).lower())] = level
            walk(child, deeper)

    walk(tree, 0)
    return depth


DEPTHS = {}


def _calls(tree):
    """Все вызовы send_response / send_header / end_headers по порядку строк."""
    DEPTHS.update(_depths(tree))
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if attr == "send_header" and node.args and isinstance(node.args[0], ast.Constant):
            found.append((node.lineno, "header", str(node.args[0].value).lower()))
        elif attr in ("send_response", "end_headers"):
            found.append((node.lineno, attr, ""))
    return sorted(found)


def _response_blocks(tree):
    """Один блок = от send_response до ближайшего end_headers.

    Группировка по СТРОКАМ, а не по функции: первая версия гварда спрашивала
    «ставит ли эта функция оба заголовка где-нибудь», и proxy() проходила
    проверку с одним потерянным Connection, потому что в другом своём ответе
    он был. Дефект был в детекции, не в правиле.
    """
    blocks, current = [], None
    for lineno, kind, name in _calls(tree):
        if kind == "send_response":
            if current is not None:
                blocks.append(current)
            current = {"line": lineno, "headers": [], "at": {}}
        elif kind == "header" and current is not None:
            current["headers"].append(name)
            current["at"].setdefault(name, []).append(DEPTHS.get((lineno, name), 0))
        elif kind == "end_headers" and current is not None:
            blocks.append(current)
            current = None
    if current is not None:
        blocks.append(current)
    return blocks


# Настоящий инвариант — не «всё через помощника». Два места объявляют длину
# законно и по-своему: одно ретранслирует заголовки самого апстрима (их нельзя
# подменять на свои), другое отдаёт переведённое тело в уже открытый поток.
# Первая версия этого гварда требовала помощника везде и краснела на обоих —
# это была ошибка ПРАВИЛА, а не кода. Правило звучит так: объявил длину —
# объяви и закрытие соединения.
blocks = _response_blocks(tree)
length_sites = 0
for block in blocks:
    if "content-length" not in block["headers"]:
        continue
    length_sites += 1
    if "connection" not in block["headers"]:
        problems.append(
            f"handler.py:{block['line']}: ответ объявляет Content-Length без Connection — "
            "клиент с keep-alive удержит поток слушателя в readline() без таймаута")
        continue
    # Наличие мало: закрытие должно быть НЕ ГЛУБЖЕ длины. Длина под условием
    # законна — ретрансляция ставит её только при наличии тела ошибки, а
    # Connection там безусловен. Обратное — заголовок, до которого не доходят.
    len_depth = min(block["at"].get("content-length") or [0])
    conn_depth = min(block["at"].get("connection") or [0])
    if conn_depth > len_depth:
        problems.append(
            f"handler.py:{block['line']}: Connection объявлен ГЛУБЖЕ Content-Length "
            f"(вложенность {conn_depth} против {len_depth}) — до него можно не дойти, "
            "а длина всё равно уйдёт")

helper = next((f for f in functions if f.name == HELPER), None)
if helper is None:
    problems.append(f"{HELPER} исчез — собирать полный ответ снова будет каждое место заново")
else:
    names = {name for _, kind, name in _calls(helper) if kind == "header"}
    for required in ("content-type", "content-length", "connection"):
        if required not in names:
            problems.append(f"{HELPER} больше не ставит {required}")

if length_sites < 2:
    problems.append(f"нашлось всего {length_sites} ответ(ов) с длиной — гвард смотрит не туда")

if problems:
    print("proxy response paths: FAILED")
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print(f"proxy response paths OK: {length_sites} мест(а) объявляют длину, все закрывают соединение; "
      f"{HELPER} ставит все три заголовка")
