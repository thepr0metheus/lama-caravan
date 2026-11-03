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
from _node import find_node, node_search_paths, probe_args  # noqa: E402

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
    hookNames: [...html.matchAll(/data-t="([a-z-]+)"/g)].map((m) => m[1]),
    buttonIds: [...html.matchAll(/data-split="[a-z]+" data-t="[a-z-]+" data-t-id="([a-z]+)"/g)].map((m) => m[1]),
    titles: [...html.matchAll(/data-split="[a-z]+"[^>]* title="([^"]*)"/g)].map((m) => m[1]),
    warn: (html.match(/class="compute-split-warn">([^<]*)</) || [null, null])[1],
    about: (html.match(/class="compute-split-about" data-t="([a-z-]+)" data-t-id="([a-z]+)">/) || [null, null, null]).slice(1),
    aboutLines: (html.split('class="compute-split-compare"')[0].match(/class="compute-split-(what|plus|minus)"/g) || []).length,
    compared: [...html.matchAll(/class="compute-split-cmp"><b>([^<]*)<\/b>/g)].map((m) => m[1]),
    compareHook: (html.match(/<summary data-t="([a-z-]+)">/) || [null, null])[1],
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
  even: Object.fromEntries(["", "none", "layer", "row", "tensor", "raw", "TENSOR", " tensor "]
    .map((v) => [`[${v}]`, new SplitMode(v).evenByDefault])),
  suggested: (() => {
    const gb = (n) => ({ memoryTotalMiB: n * 1024 });
    const unlike = [{ memoryTotalMiB: 24576 }, { memoryTotalMiB: 32607 }];      // a 3090 and a 5090, as the machine reports them
    const s = (mode, cards) => new SplitMode(mode).suggestedSplit(cards);
    return {
      unlike: s("tensor", unlike), reordered: s("tensor", [...unlike].reverse()),
      equal: s("tensor", [gb(24), gb(24)]), withinTenth: s("tensor", [gb(24), gb(26)]), pastTenth: s("tensor", [gb(24), gb(27)]),
      three: s("tensor", [gb(24), gb(32), gb(48)]),
      rowMode: s("row", unlike), layerMode: s("layer", unlike), emptyMode: s("", unlike), unknownMode: s("raw", unlike),
      oneCard: s("tensor", [gb(24)]), noCards: s("tensor", []), nullCards: s("tensor", null), undefinedCards: s("tensor", undefined),
      unknownSize: s("tensor", [{ memoryTotalMiB: 24576 }, {}]), zeroSize: s("tensor", [gb(24), gb(0)]),
    };
  })(),
  // The label and the three lines must come from THOSE keys — pinning the English text here
  // would pin a copy of it, and the copy is what drifts.
  fromKeys: {
    labelLayer: new SplitMode("layer").label() === en.splitLayer,
    labelRow: new SplitMode("row").label() === en.splitRow,
    labelTensor: new SplitMode("tensor").label() === en.splitTensor,
    labelUnknown: new SplitMode("raw").label(),
    detailsLayer: JSON.stringify(new SplitMode("layer").details()) === JSON.stringify({ what: en.splitWhatLayer, plus: en.splitPlusLayer, minus: en.splitMinusLayer }),
    detailsTensor: JSON.stringify(new SplitMode("tensor").details()) === JSON.stringify({ what: en.splitWhatTensor, plus: en.splitPlusTensor, minus: en.splitMinusTensor }),
    detailsRow: (() => { const d = new SplitMode("row").details();
      return d.what === en.splitWhatRow && d.plus === en.splitPlusRow
        && d.minus === en.splitMinusRow.replace("{layer}", en.splitLayer).replace("{tensor}", en.splitTensor); })(),
    rowNamesTheOthers: (() => { const m = new SplitMode("row").details().minus; return m.includes(en.splitLayer) && m.includes(en.splitTensor) && !m.includes("{"); })(),
    detailsDiffer: new Set(["layer", "row", "tensor"].map((v) => new SplitMode(v).details().minus)).size,
    detailsNone: new SplitMode("none").details(),
    detailsEmpty: new SplitMode("").details(),
    detailsUnknown: new SplitMode("raw").details(),
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
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
           "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"}
    proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True,
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
check(tab["fallback"] == "layer",
      "умолчание — конвейер layer: собственный выбор llama.cpp, стартует на любой сборке. Было row (просьба 2026-09-21) — на машине "
      "с 3090 и 5090 (llama.cpp b1141) каждый старт с row умирал на «device CUDA0 does not support split buffers» (2026-10-17); "
      "и не EXPERIMENTAL tensor")

print("forCards — что записать при N выбранных картах:")
fc = got["forCards"]
check(fc["|0"] == "" and fc["|1"] == "", "одна карта и ноль карт — пусто: делить нечего, флаг не печатается")
check(fc["|2"] == "layer" and fc["|5"] == "layer", "пустое поле на двух и пяти картах — конвейер по умолчанию")
check(fc["layer|2"] == "layer", "уже выбранный конвейер переживает перещёлкивание карты")
check(fc["layer|1"] == "", "две карты свели к одной — флаг снимается, а не остаётся врать")
check(fc["tensor|3"] == "tensor", "выбранный экспериментальный режим не подменяется на умолчание")
check(fc["raw|2"] == "layer", "опечатка не уезжает в команду — заменяется умолчанием")
check(fc["none|2"] == "layer",
      "as-is: «none» при двух выбранных картах ТОЖЕ заменяется — значение противоречит самому выбору")
check(fc["  ROW  |2"] == "row",
      "negative: выбранный нарочно Tensor (row) умолчанием не подменяется — регистр и пробелы вокруг значения не считаются другим режимом")
check(fc["null|2"] == "layer" and fc["undefined|2"] == "layer", "нет поля вовсе — то же умолчание, без падения")

print("evenByDefault / suggestedSplit — как режим делит модель без --tensor-split:")
ev, sg = got["even"], got["suggested"]
check(ev["[tensor]"] and ev["[TENSOR]"] and ev["[ tensor ]"],
      "tensor режет веса на ровные части, какая бы память ни была у карт (замер: 21,1 + 21,4 ГБ на 24 и 32 ГБ); регистр и пробелы — как у остальных")
check(not any(ev[f"[{v}]"] for v in ("", "none", "layer", "row", "raw")),
      "negative: layer и row делят по свободной памяти карт сами, пустое и незнакомое — ничего не утверждают")
check(sg["unlike"] == "24,32",
      f"3090 и 5090 — доли по размерам карт, в ГБ: 24,32 (получено {sg['unlike']!r}); с ними 70B пошла с 32,0 на 36,0 ток/с")
check(sg["reordered"] == "32,24", "порядок — как карты пришли: так их видит llama.cpp, вызывающий сортирует по номеру")
check(sg["equal"] == "" and sg["withinTenth"] == "",
      "negative: две одинаковые карты и разница в пределах десятой доли — доли не нужны, «1,1» — шум в команде")
check(sg["pastTenth"] == "24,27", "boundary: разница больше десятой доли (3 из 27) — доли пишутся")
check(sg["three"] == "24,32,48", "три карты — три доли")
check(all(sg[k] == "" for k in ("rowMode", "layerMode", "emptyMode", "unknownMode")),
      "negative: режим, который делит по свободной памяти сам, и пустой/незнакомый — доли не пишутся")
check(all(sg[k] == "" for k in ("oneCard", "noCards", "nullCards", "undefinedCards")),
      "negative: одна карта, ни одной, нет списка — делить нечего, доли нет, падения нет")
check(sg["unknownSize"] == "" and sg["zeroSize"] == "",
      "negative: размер карты неизвестен или 0 — доли не выдумываются (выдуманные доли хуже ровного деления)")

print("known / parallel:")
kn, par = got["known"], got["isParallel"]
check(all(kn[f"[{v}]"] for v in ("none", "layer", "row", "tensor")), "четыре значения llama-server — знакомые")
check(kn["[raw]"] is False, "«raw» — незнакомое")
check(kn["[]"] is False, "пустое — НЕ знакомое: это не режим, а «пусть выберет llama.cpp»")
check(kn["[ROW]"] and kn["[ row ]"],
      "регистр и пробелы снимает конструктор, поэтому «ROW» знакомо так же, как «row»")
check(par["[row]"] and par["[tensor]"], "row и tensor — одновременная работа карт")
check(not par["[layer]"] and not par["[none]"] and not par["[]"], "конвейер, none и пустое — не одновременная")

print("подписи и три строки режима (что делает, чем хорош, чем плох) — из ключей en.js:")
fk = got["fromKeys"]
check(fk["labelLayer"] and fk["labelRow"] and fk["labelTensor"], "три подписи — из splitLayer/splitRow/splitTensor")
check(fk["labelUnknown"] == "raw", "незнакомое значение показывается как есть, а не переводится в пустоту")
check(fk["detailsLayer"] and fk["detailsTensor"],
      "у конвейера и у tensor — свои три строки (владелец, 2026-10-24: «подписать подробно, чем каждый режим отличается, чем выгоден и его минусы»)")
check(fk["detailsRow"] and fk["rowNamesTheOthers"],
      "минус row — с июля 2026 (llama.cpp #24216) в CUDA-сборках его нет — называет две плитки, что работают, по их подписям на экране, без нерасставленных {…}")
check(fk["detailsDiffer"] == 3, "negative: у трёх режимов три разных минуса, а не одна строка на всех")
check(fk["detailsNone"] is None and fk["detailsEmpty"] is None and fk["detailsUnknown"] is None,
      "у «none», пустого и незнакомого строк нет — null, а не пустые абзацы, читающиеся как пропавший перевод")
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
check(h["layer"]["about"] == ["cell-remote-split-about", "layer"] and h["row"]["about"] == ["cell-remote-split-about", "row"]
      and h["tensor"]["about"][1] == "tensor" and h["layer"]["aboutLines"] == 3,
      "под плиткой — три строки выбранного режима, с его именем в data-t-id")
check(h["empty"]["about"] == [None, None] and h["unknown"]["about"] == [None, None] and h["empty"]["aboutLines"] == 0,
      "negative: без режима строк нет — пустые абзацы читались бы как пропавший перевод")
check(all(h[k]["compared"] == ["Pipeline", "Tensor", "Tensor + KV"] for k in ("empty", "layer", "unknown"))
      and h["layer"]["compareHook"] == "cell-remote-split-compare",
      "свёрнутое сравнение — все три режима рядом, при любом выбранном (и при пустом: выбор ещё впереди)")
check(h["layer"]["titles"][0].startswith("Pipeline · ") and len(set(h["layer"]["titles"])) == 3,
      "подсказка кнопки — подпись и что режим делает: у каждой своя")
check(h["layer"]["exp"] and h["layer"]["raw"].count("compute-split-exp") == 1,
      "пометка «эксперимент» ровно одна — на кнопке tensor")
check(h["layer"]["hookNames"][:3] == ["cell-edit-split"] * 3
      and h["tensor"]["hookNames"][:3] == ["cell-remote-split"] * 3,
      "хук кнопок data-t зависит от формы: cell-edit-split в редакторе, cell-remote-split в модале клиента")
check(h["layer"]["hookNames"][3:] == ["cell-remote-split-about", "cell-remote-split-compare"]
      and h["empty"]["hookNames"][3:] == ["cell-remote-split-compare"],
      "строки режима и сравнение — свои хуки, написанные целиком (их видит гвард testability_names.py); без режима — только сравнение")
check(h["layer"]["buttonIds"] == ["layer", "row", "tensor"], "каждая кнопка различима по data-t-id")
check('"><b>x' not in h["injected"]["raw"] and "&quot;&gt;&lt;b&gt;x" in h["injected"]["raw"],
      "значение из поля экранируется — разметкой из него не подменишь плитку (свои <b> у плитки есть: подписи в сравнении)")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print(f"js split-mode OK: {len(got['forCards'])} значений forCards, разметка шести состояний")
