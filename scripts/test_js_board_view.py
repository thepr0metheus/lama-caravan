#!/usr/bin/env python3
"""Snapshot of static/js/board-view.js — which board a page is (the owner, 2026-10-11).

The main board shows each machine at a glance; ↗ opens the machine's own window, the same
index.html at /machine?host=<id>, which shows that machine's whole card. Pinned by value,
with the module loaded for real: the page's address and window.open are parameters, so no
browser is needed — the path decides, the id is read and trimmed, a window that names no
machine is not the main board, the address and the window's name survive an odd id, the
mark lands on <html>, and a refused window is said, not assumed.

Run: python3 scripts/test_js_board_view.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

PROBE = r"""
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.argv[2]).href);
const V = m.BoardView;
const at = (pathname, search = "") => new V({ pathname, search });
const out = {};
out.paths = [at("/board").machine, at("/board", "?host=x").machine, at("/machine", "?host=box").machine,
  at("/machine", "?host=%20box%20").machine, at("/machine").machine, at("/machine", "?host=").machine, at("/machine/", "?host=box").machine];
out.names = [at("/board").name, at("/machine", "?host=box").name, at("/machine").name, at("/board").isMachine, at("/machine").isMachine];
out.urls = [V.url("box"), V.url("a&b <c>"), V.url(7)];
out.windows = [V.windowName("box"), V.windowName("a&b <c>"), V.windowName("sierra-pc")];
const root = { dataset: {} };
at("/machine", "?host=box").mark(root);
const main = { dataset: {} };
at("/board").mark(main);
at("/board").mark(null);
out.marks = [root.dataset.boardView, main.dataset.boardView];
const calls = [];
const win = { focused: 0, focus() { this.focused += 1; } };
out.open = [V.open("box", (...a) => { calls.push(a); return win; }), calls, win.focused,
  V.open("box", () => null), V.open("box", undefined), V.open("box", "not a function")];
console.log(JSON.stringify(out));
"""

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    node = find_node()
    if node is None:
        print("js board-view: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_js_board_view.tmp.mjs"
    probe.write_text(PROBE)
    try:
        run = subprocess.run([node, str(probe), str(ROOT / "static" / "js" / "board-view.js")],
                             capture_output=True, text=True, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr)
        print(f"js board-view FAILED: node вышел с кодом {run.returncode}")
        return 1
    got = json.loads(run.stdout.strip().splitlines()[-1])
    print("какая это доска — главная или окно машины:")
    check(got["paths"] == [None, None, "box", "box", "", "", None],
          "путь решает: /board — главная (и с ?host= тоже); /machine?host=box — окно машины box, пробелы срезаны; "
          "negative: /machine без машины — окно, которое её не называет (\"\"), а не главная доска; /machine/ — не окно машины "
          f"(получено {got['paths']})")
    check(got["names"] == ["main", "machine", "machine", False, True],
          f"метка вида: main / machine; окно без машины — всё равно окно машины (получено {got['names']})")
    check(got["urls"] == ["/machine?host=box", "/machine?host=a%26b%20%3Cc%3E", "/machine?host=7"],
          f"адрес окна машины; странный id закодирован, а не ломает адрес (получено {got['urls']})")
    check(got["windows"] == ["caravan-machine-box", "caravan-machine-a_b__c_", "caravan-machine-sierra-pc"],
          f"имя окна — одно на машину (второй щелчок поднимает его, а не плодит окна); всё, кроме букв, цифр, _ и -, — в _ "
          f"(получено {got['windows']})")
    check(got["marks"] == ["machine", "main"],
          "метка ложится на <html> как data-board-view (у main#topologyView свой data-view); negative: без корня — молча ничего")
    opened = got["open"]
    check(opened[0] is True and opened[1] == [["/machine?host=box", "caravan-machine-box", "popup=yes,width=1180,height=920"]]
          and opened[2] == 1,
          "↗ открывает отдельное окно машины по её адресу и имени и поднимает его")
    check(opened[3:] == [False, False, False],
          "negative: браузер окно не дал (или открывать нечем) — сказано false, и ссылка откроет адрес обычным путём")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("js board-view OK: настоящий модуль в node, вид страницы значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
