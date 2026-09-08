#!/usr/bin/env python3
"""Guard: a full proxy response is assembled by ONE helper, not rebuilt at
every call site.

A response with a body must carry three headers: type, length, and
`Connection: close`. The last one isn't decoration. The handler speaks
HTTP/1.1, so a client that asked for keep-alive (which every modern SDK does
by default) will get a persistent connection unless told otherwise. The
success path closes it explicitly, but an exception jumps right over that
spot, and one of the hand-written copies of the header block was missing it:
the listener thread parked in readline() with no timeout for exactly as long
as the client held the socket open.

There were six copies of five lines each, and the defect was one line missing
from one of them. The six were reduced to a single helper; two places
legitimately stayed their own — relaying the upstream's own headers, and
handing off a translated body — so the rule isn't "everything through the
helper" but "declared a length, then declare the close too".

Fails four ways: a length with no close; a close NESTED DEEPER than the
length, meaning behind a condition that might never be reached; the helper
stopped setting one of the three headers; fewer than two places declare a
length — meaning the guard is looking in the wrong place.

Run: python3 scripts/check_proxy_response_paths.py
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
    """Nesting depth of every header call, within its own function.

    Being present in the text isn't enough. The first version of the guard
    considered a response block closed if the right name showed up SOMEWHERE
    between send_response and end_headers — and let through `if False:
    send_header("Connection", ...)`, meaning a header execution never
    reaches. Verified by hand: the guard said OK while the snapshot turned
    red on five checks at that exact moment.
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
    """Every call to send_response / send_header / end_headers, in line order."""
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
    """One block = from send_response to the nearest end_headers.

    Grouped by LINES, not by function: the first version of the guard asked
    "does this function set both headers somewhere", and proxy() passed the
    check with one Connection header missing, because it had one in its
    OTHER response. The defect was in the detection, not the rule.
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


# The real invariant isn't "everything through the helper". Two places
# legitimately declare a length their own way: one relays the upstream's own
# headers (which must not be swapped for ours), the other hands off a
# translated body into a stream that's already open. The first version of
# this guard required the helper everywhere and turned red on both — that
# was a bug in the RULE, not the code. The rule reads: declared a length,
# then declare the connection close too.
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
    # Presence alone isn't enough: the close must be NO DEEPER than the
    # length. A conditional length is legitimate — the relay only sets it
    # when there's an error body, while Connection there is unconditional.
    # The reverse is a header that execution never reaches.
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
