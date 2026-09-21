#!/usr/bin/env python3
"""Снимок static/js/split-mode.js — как модель делится между картами.

Поле -sm жило свободной строкой в одиннадцатой вкладке: опечатка уезжала в
команду, ячейка не стартовала, причина оставалась в логе. Класс SplitMode
теперь решает три вещи, и все три пинятся ЗНАЧЕНИЯМИ: что получает свежий
выбор из двух карт, какие значения llama-server знает, и что рисуется, когда
значение ему не знакомо.

Модуль грузится в node по-настоящему (scripts/_js_harness.mjs), i18n тоже
настоящий: ожидания берутся из static/js/i18n/en.js программно, а не по памяти.

Запуск: python3 scripts/test_js_split_mode.py
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
const root = process.env.JS_ROOT;
const { SplitMode } = await import(pathToFileURL(root + "/split-mode.js").href);
const en = (await import(pathToFileURL(root + "/i18n/en.js").href)).default;

// Facts about a rendered control, so the pin is a value and not a wall of HTML.
const facts = (html) => {
  const on = [...html.matchAll(/data-split="([a-z]+)"(?![^>]*>)/g)];
  const active = [...html.matchAll(/class="compute-split-btn on" data-split="([a-z]+)"/g)].map((m) => m[1]);
  return {
    buttons: [...html.matchAll(/data-split="([a-z]+)"/g)].map((m) => m[1]),
    active,
    hooks: [...html.matchAll(/data-t="([a-z-]+)" data-t-id="([a-z]+)"/g)].map((m) => m.join("|").slice(m[0].length - m[0].length)),
    hookNames: [...html.matchAll(/data-t="([a-z-]+)"/g)].map((m) => m[1]),
    hookIds: [...html.matchAll(/data-t-id="([a-z]+)"/g)].map((m) => m[1]),
    warn: (html.match(/class="compute-split-warn">([^<]*)</) || [null, null])[1],
    hint: (html.match(/class="compute-split-hint">([^<]*)</) || [null, null])[1],
    exp: (html.match(/class="compute-split-exp">([^<]*)</) || [null, null])[1],
    raw: html,
  };
};

const out = {
  table: { values: SplitMode.VALUES, shown: SplitMode.SHOWN,
           parallel: SplitMode.PARALLEL, fallback: SplitMode.DEFAULT },
  forCards: Object.fromEntries(
    [["", 0], ["", 1], ["", 2], ["", 5], ["layer", 2], ["layer", 1], ["tensor", 3],
     ["raw", 2], ["none", 2], ["  ROW  ", 2], [null, 2], [undefined, 2]]
      .map(([v, n]) => [`${v}|${n}`, new SplitMode(v).forCards(n)])),
  known: Object.fromEntries(["", "none", "layer", "row", "tensor", "raw", "ROW", " row "]
    .map((v) => [`[${v}]`, new SplitMode(v).known])),
  isParallel: Object.fromEntries(["", "none", "layer", "row", "tensor", "raw"]
    .map((v) => [`[${v}]`, new SplitMode(v).parallel])),
  // The label/hint must come from THOSE keys — pinning the English text here
  // would pin a copy of it, and the copy is what drifts.
  fromKeys: {
    labelLayer: new SplitMode("layer").label() === en.splitLayer,
    labelRow: new SplitMode("row").label() === en.splitRow,
    labelTensor: new SplitMode("tensor").label() === en.splitTensor,
    labelUnknown: new SplitMode("raw").label(),
    hintLayer: new SplitMode("layer").hint() === en.splitHintLayer,
    hintRow: new SplitMode("row").hint() === en.splitHintParallel,
    hintTensor: new SplitMode("tensor").hint() === en.splitHintParallel,
    hintNone: new SplitMode("none").hint(),
    hintEmpty: new SplitMode("").hint(),
    warnNamesValue: new SplitMode("raw").html("h").includes("raw"),
  },
  html: {
    empty: facts(new SplitMode("").html("cell-edit-split")),
    layer: facts(new SplitMode("layer").html("cell-edit-split")),
    row: facts(new SplitMode("row").html("cell-edit-split")),
    tensor: facts(new SplitMode("tensor").html("cell-remote-split")),
    unknown: facts(new SplitMode("raw").html("cell-edit-split")),
    injected: facts(new SplitMode('"><b>x').html("cell-edit-split")),
  },
};
console.log(JSON.stringify(out));
"""

node = find_node()
if node is None:
    print("js split-mode: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: "
          + ", ".join(node_search_paths()))
    sys.exit(0)
probe = ROOT / "scripts" / ".probe_split_mode.tmp.mjs"
probe.write_text(PROBE, encoding="utf-8")
try:
    hook = (f"data:text/javascript,import {{ register }} from 'node:module'; "
            f"register('file://{ROOT}/scripts/_js_harness.mjs');")
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
           "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"}
    proc = subprocess.run([node, "--import", hook, str(probe)], capture_output=True,
                          text=True, cwd=ROOT, env=env, timeout=60)
finally:
    probe.unlink(missing_ok=True)
if proc.returncode != 0:
    print("js split-mode: FAILED — харнесс не отработал")
    print(proc.stderr.strip()[:900])
    sys.exit(1)
got = json.loads(proc.stdout.strip().splitlines()[-1])

print("таблица значений:")
tab = got["table"]
check(tab["values"] == ["none", "layer", "row", "tensor"],
      f"четыре значения llama-server, из constants.js (получено {tab['values']})")
check(tab["shown"] == ["layer", "row", "tensor"],
      "на плитке три: «none» = «только одна карта» противоречит выбранным двум и живёт в поле")
check(tab["parallel"] == ["row", "tensor"], "одновременно считают row и tensor")
check(tab["fallback"] == "row",
      "умолчание — тензорный row, а НЕ помеченный llama.cpp как EXPERIMENTAL tensor")

print("forCards — что записать при N выбранных картах:")
fc = got["forCards"]
check(fc["|0"] == "" and fc["|1"] == "", "одна карта и ноль карт — пусто: делить нечего, флаг не печатается")
check(fc["|2"] == "row" and fc["|5"] == "row", "пустое поле на двух и пяти картах — тензорный по умолчанию")
check(fc["layer|2"] == "layer", "уже выбранный конвейер переживает перещёлкивание карты")
check(fc["layer|1"] == "", "две карты свели к одной — флаг снимается, а не остаётся врать")
check(fc["tensor|3"] == "tensor", "выбранный экспериментальный режим не подменяется на умолчание")
check(fc["raw|2"] == "row", "опечатка не уезжает в команду — заменяется умолчанием")
check(fc["none|2"] == "row",
      "as-is: «none» при двух выбранных картах ТОЖЕ заменяется — значение противоречит самому выбору")
check(fc["  ROW  |2"] == "row", "регистр и пробелы вокруг значения не считаются другим режимом")
check(fc["null|2"] == "row" and fc["undefined|2"] == "row", "нет поля вовсе — то же умолчание, без падения")

print("known / parallel:")
kn, par = got["known"], got["isParallel"]
check(all(kn[f"[{v}]"] for v in ("none", "layer", "row", "tensor")), "четыре значения llama-server — знакомые")
check(kn["[raw]"] is False, "«raw» — незнакомое")
check(kn["[]"] is False, "пустое — НЕ знакомое: это не режим, а «пусть выберет llama.cpp»")
check(kn["[ROW]"] and kn["[ row ]"],
      "регистр и пробелы снимает конструктор, поэтому «ROW» знакомо так же, как «row»")
check(par["[row]"] and par["[tensor]"], "row и tensor — одновременная работа карт")
check(not par["[layer]"] and not par["[none]"] and not par["[]"], "конвейер, none и пустое — не одновременная")

print("подписи и подсказки берутся из ключей en.js:")
fk = got["fromKeys"]
check(fk["labelLayer"] and fk["labelRow"] and fk["labelTensor"], "три подписи — из splitLayer/splitRow/splitTensor")
check(fk["labelUnknown"] == "raw", "незнакомое значение показывается как есть, а не переводится в пустоту")
check(fk["hintLayer"], "у конвейера своя подсказка — splitHintLayer")
check(fk["hintRow"] and fk["hintTensor"], "у row и tensor одна подсказка на двоих — splitHintParallel")
check(fk["hintNone"] == "" and fk["hintEmpty"] == "",
      "у «none» и пустого подсказки нет — пустая строка, а не пустой абзац на экране")
check(fk["warnNamesValue"], "предупреждение называет само значение, а не «неверное значение»")

print("разметка:")
h = got["html"]
check(h["layer"]["buttons"] == ["layer", "row", "tensor"], "три кнопки в порядке SHOWN")
check(h["layer"]["active"] == ["layer"] and h["row"]["active"] == ["row"],
      "подсвечена ровно одна кнопка — та, что в поле")
check(h["empty"]["active"] == [],
      "пустое поле — НИ ОДНА кнопка не горит: llama.cpp выбирает сам, и выдавать это за режим нельзя")
check(h["unknown"]["active"] == [], "незнакомое значение — тоже ни одной горящей кнопки")
check(h["unknown"]["warn"] and "raw" in h["unknown"]["warn"], "незнакомое названо вслух, с самим значением")
check(h["empty"]["warn"] is None and h["layer"]["warn"] is None,
      "у пустого и у нормального режима предупреждения нет")
check(h["layer"]["hint"] and h["row"]["hint"] and h["layer"]["hint"] != h["row"]["hint"],
      "у конвейера и у тензорного подсказки разные")
check(h["empty"]["hint"] is None and h["unknown"]["hint"] is None,
      "без режима подсказки нет — пустой абзац читался бы как пропавший перевод")
check(h["layer"]["exp"] and h["layer"]["raw"].count("compute-split-exp") == 1,
      "пометка «эксперимент» ровно одна — на кнопке tensor")
check(h["layer"]["hookNames"] == ["cell-edit-split"] * 3
      and h["tensor"]["hookNames"] == ["cell-remote-split"] * 3,
      "хук data-t зависит от формы: cell-edit-split в редакторе, cell-remote-split в модале клиента")
check(h["layer"]["hookIds"] == ["layer", "row", "tensor"], "каждая кнопка различима по data-t-id")
check("<b>" not in h["injected"]["raw"] and "&lt;b&gt;" in h["injected"]["raw"],
      "значение из поля экранируется — разметкой из него не подменишь плитку")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print(f"js split-mode OK: {len(got['forCards'])} значений forCards, разметка шести состояний")
