#!/usr/bin/env python3
"""Снимок static/js/command-preview.js — команда запуска, которую оператор копирует.

Три чистые функции: разбиение команды на токены, раскладка по строкам
«--флаг значение», и LCS-подсветка того, что в предпросмотре НЕ изменилось.
Пинятся ЗНАЧЕНИЯ, включая некрасивое как есть: разбиение не знает кавычек, и
`--alias "my model"` разлетается на три токена — так это и копируется сегодня.

Модуль грузится в node НАСТОЯЩИЙ (scripts/_js_harness.mjs).

Запуск: python3 scripts/test_js_command_preview.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const m = await import(pathToFileURL(process.env.JS_ROOT + "/command-preview.js").href);
const out = {
  split: {
    empty: m.splitCommand(""), nul: m.splitCommand(null),
    ws: m.splitCommand("  llama-server   --port\n22001\t--ctx-size 4096 "),
    quoted: m.splitCommand('llama-server --alias "my model"'),
  },
  fmt: {
    pairs: m.formatCmdline("llama-server --model a.gguf --port 22001 --flash-attn --ctx-size 4096"),
    negative: m.formatCmdline("x --temp -1 --port 5"),
    positional: m.formatCmdline("python3 run.py --n 3"),
    empty: m.formatCmdline(""),
  },
  lcs: {
    same: [...m.lcsPreviewIndexes(["a","b","c"], ["a","b","c"])],
    replaced: [...m.lcsPreviewIndexes(["a","b","c"], ["a","x","c"])],
    inserted: [...m.lcsPreviewIndexes(["a","b","c"], ["a","b","c","d"])],
    removed: [...m.lcsPreviewIndexes(["a","b","c"], ["a","c"])],
    emptyCur: [...m.lcsPreviewIndexes([], ["a","b"])],
    emptyPrev: [...m.lcsPreviewIndexes(["a"], [])],
    moved: [...m.lcsPreviewIndexes(["--port","22001","--ctx","4096"], ["--ctx","4096","--port","22001"])],
  },
};
console.log(JSON.stringify(out));
"""

node = find_node()
if node is None:
    print("js command-preview: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
    sys.exit(0)
probe = ROOT / "scripts" / ".probe_cmd_preview.tmp.mjs"
probe.write_text(PROBE, encoding="utf-8")
try:
    hook = f"data:text/javascript,import {{ register }} from 'node:module'; register('file://{ROOT}/scripts/_js_harness.mjs');"
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
           "JS_STUBS": "form,llama-edit,cloud,topology-render,polling,favorites,remote-cells"}
    proc = subprocess.run([node, "--import", hook, str(probe)], capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
finally:
    probe.unlink(missing_ok=True)
if proc.returncode != 0:
    print("js command-preview: FAILED — харнесс не отработал"); print(proc.stderr.strip()[:800]); sys.exit(1)
got = json.loads(proc.stdout.strip().splitlines()[-1])

print("splitCommand:")
sp = got["split"]
check(sp["empty"] == [] and sp["nul"] == [], "пусто и null → пустой список, не ['']")
check(sp["ws"] == ["llama-server", "--port", "22001", "--ctx-size", "4096"], f"любые пробелы и переводы строк — разделители (получено {sp['ws']})")
# ЗАФИКСИРОВАНО КАК ЕСТЬ: кавычки не распознаются.
check(sp["quoted"] == ["llama-server", "--alias", '"my', 'model"'], f"кавычки НЕ распознаются — значение с пробелом рвётся (получено {sp['quoted']})")

print("formatCmdline:")
fm = got["fmt"]
check(fm["pairs"] == "llama-server\n--model a.gguf\n--port 22001\n--flash-attn\n--ctx-size 4096",
      f"«--флаг значение» на одной строке, флаг без значения — один (получено {fm['pairs']!r})")
# ЗАФИКСИРОВАНО КАК ЕСТЬ: отрицательное значение считается следующим флагом.
check(fm["negative"] == "x\n--temp\n-1\n--port 5", f"отрицательное значение отрывается от флага (получено {fm['negative']!r})")
check(fm["positional"] == "python3\nrun.py\n--n 3", f"позиционные — по одному на строку (получено {fm['positional']!r})")
check(fm["empty"] == "", "пустая команда → пустая строка")

print("lcsPreviewIndexes (индексы НЕИЗМЕНИВШИХСЯ токенов предпросмотра):")
lc = got["lcs"]
check(lc["same"] == [0, 1, 2], f"одинаковые — все на месте ({lc['same']})")
check(lc["replaced"] == [0, 2], f"замена середины — подсвечен только средний ({lc['replaced']})")
check(lc["inserted"] == [0, 1, 2], f"вставка в конец — новый токен подсвечен ({lc['inserted']})")
check(lc["removed"] == [0, 1], f"удаление — оставшиеся не подсвечены ({lc['removed']})")
check(lc["emptyCur"] == [] and lc["emptyPrev"] == [], "пустые стороны — пустое множество, не исключение")
check(sorted(lc["moved"]) in ([0, 1], [2, 3]), f"перестановка пар — одна пара считается неизменной, другая новой ({lc['moved']})")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail: print("  - " + m)
    sys.exit(1)
print("js command-preview OK: настоящий модуль в node, команда запуска значениями")
