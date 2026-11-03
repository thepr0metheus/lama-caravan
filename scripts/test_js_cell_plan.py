#!/usr/bin/env python3
"""Value snapshot: what a llama.cpp cell takes, out of its fields and its model's header (static/js/cell-plan.js, 1.3.635).

The owner, 2026-10-25: the machine page's bench says "the exact size, and in colour where the model is and where the cache".
The cell window already sized a cell so — its KV cache and its buffers under its fields — but read the fields off the form.
cell-plan.js is that accounting with the fields read by a reader: the form builds one over its inputs (memory.js formFields), the
bench one over the cell's stored config (CellFields.ofConfig), and both give one figure. scripts/test_js_memory.py pins the
agreement of the two readers on one cell; this file pins the rules themselves, each claim with its negative:
  * a stored config read as the form shows it: a box by what it says, unsaid — on for the optional toggles that are on unless
    turned off, off for the rest; a field trimmed; an empty one with the controller's default behind it;
  * the KV cache of a dense model under the fields — the slots and their cache's kind, the cache types — and nothing for a
    header or a context that does not say;
  * the compute buffers by the batches and the model's width, nothing without them;
  * the model's weight: its file and its projector, its header's layers and experts; nothing known without its row.

Run: python3 scripts/test_js_cell_plan.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r'''
import "./_js_globals.mjs";
const P = await import("../static/js/cell-plan.js");
const C = await import("../static/js/constants.js");
const out = {};
const r6 = (x) => Math.round(x * 1e6) / 1e6;

// A stored config read as the form shows it.
const cfg = { KV_OFFLOAD: "0", CPU_MOE: "true", N_GPU_LAYERS: " 999 ", CTX_SIZE: "", CACHE_TYPE_K: "q8_0", KV_UNIFIED: "1", MMAP: "off" };
const f = P.CellFields.ofConfig(cfg, { CTX_SIZE: "4096", CACHE_TYPE_V: "q4_0", N_GPU_LAYERS: "1" });
out.fields = {
  text: ["KV_OFFLOAD", "FIT", "CPU_MOE", "KV_UNIFIED", "SWA_FULL", "MMAP", "N_GPU_LAYERS", "CTX_SIZE", "TENSOR_SPLIT"].map((k) => f.text(k)),
  value: ["CTX_SIZE", "CACHE_TYPE_K", "CACHE_TYPE_V", "N_GPU_LAYERS", "BATCH_SIZE"].map((k) => f.value(k)),
  checked: ["KV_UNIFIED", "SWA_FULL", "KV_OFFLOAD", "FIT", "CPU_MOE"].map((k) => f.checked(k)),
};
out.toggle = { onUnlessOff: C.defaultOnOptionalToggles.map((k) => P.CellFields.toggle(k, {})),
               otherUnset: ["KV_UNIFIED", "SWA_FULL", "CPU_MOE", "ENABLE_JINJA"].map((k) => P.CellFields.toggle(k, {})),
               blank: P.CellFields.toggle("KV_OFFLOAD", { KV_OFFLOAD: "  " }), said: ["yes", "on", "1", "TRUE", "no", "2"].map((v) => P.CellFields.toggle("SWA_FULL", { SWA_FULL: v })) };
const bare = new P.CellFields({ text: (k) => ({ A: "x", B: "1" })[k] || "" });
out.bare = [bare.value("A"), bare.checked("B"), bare.checked("A")];

// A dense 70B: 80 layers of 8 KV heads of 128.
const DENSE = { blockCount: 80, headCount: 64, headCountKv: 8, keyLength: 128, embeddingLength: 8192 };
const kv = (config, meta = DENSE, defaults = {}) => r6(P.KvCache.gb(meta, P.CellFields.ofConfig(config, defaults)));
out.kv = {
  auto: kv({ CTX_SIZE: "4096", CACHE_TYPE_K: "q8_0", CACHE_TYPE_V: "q8_0" }),
  f16: kv({ CTX_SIZE: "4096", CACHE_TYPE_K: "f16", CACHE_TYPE_V: "f16" }),
  mixed: kv({ CTX_SIZE: "4096", CACHE_TYPE_K: "f16", CACHE_TYPE_V: "q4_0" }),
  slots: kv({ CTX_SIZE: "4096", CACHE_TYPE_K: "f16", CACHE_TYPE_V: "f16", PARALLEL: "3" }),
  padded: kv({ CTX_SIZE: "4000", CACHE_TYPE_K: "f16", CACHE_TYPE_V: "f16" }),
  byDefault: kv({ CACHE_TYPE_K: "f16", CACHE_TYPE_V: "f16" }, DENSE, { CTX_SIZE: "4096" }),
  noContext: kv({ CTX_SIZE: "0" }), noLayers: kv({ CTX_SIZE: "4096" }, { headCount: 64, keyLength: 128 }), noMeta: kv({ CTX_SIZE: "4096" }, null),
  // An empty window asks for the trained one (AskedWindow, 2026-10-26): its cache, not none.
  trained: [kv({ CTX_SIZE: "", CACHE_TYPE_K: "f16", CACHE_TYPE_V: "f16" }, { ...DENSE, contextLength: 8192 }),
            kv({ CTX_SIZE: "0", CACHE_TYPE_K: "f16", CACHE_TYPE_V: "f16" }, { ...DENSE, contextLength: 8192 }),
            kv({ CTX_SIZE: "4096", CACHE_TYPE_K: "f16", CACHE_TYPE_V: "f16" }, { ...DENSE, contextLength: 8192 })],
};
out.cells = [P.KvCache.cells(4096, 0, { slots: 3, unified: false, ubatch: 512 }), P.KvCache.cells(4096, 1024, { slots: 3, unified: true, ubatch: 512 }),
             P.KvCache.cells(4096, 1024, { slots: 3, unified: true, ubatch: 512, swaFull: true })];
out.bytes = ["q8_0", "Q8_0", "q4_0", "iq4_nl", "f32", "bf16", "f16", "", null, "weird"].map((t) => P.KvCache.bytesPerElement(t));

const buf = (config, meta = DENSE) => r6(P.BatchBuffers.gb(meta, P.CellFields.ofConfig(config, {})));
out.buffers = { both: buf({ BATCH_SIZE: "1024", UBATCH_SIZE: "512" }), batchOnly: buf({ BATCH_SIZE: "1024" }), none: buf({}),
                noWidth: buf({ BATCH_SIZE: "1024" }, { blockCount: 80 }) };

// The model of a cell: its files, its cache and buffers, its header.
const row = { sizeGb: 39.6, ggufMeta: { ...DENSE, expertCount: 0, expertBytes: 0 } };
const fields = P.CellFields.ofConfig({ CTX_SIZE: "4096", CACHE_TYPE_K: "q8_0", CACHE_TYPE_V: "q8_0", BATCH_SIZE: "1024", UBATCH_SIZE: "512" }, {});
const moe = { sizeGb: 46.2, ggufMeta: { blockCount: 48, headCount: 16, headCountKv: 2, keyLength: 256, embeddingLength: 2048, expertCount: 512, expertBytes: 40 * 2 ** 30 } };
const cut = (m) => m && Object.fromEntries(Object.entries(m).map(([k, v]) => [k, r6(v)]));
out.model = { dense: cut(P.CellModel.of({ row, mmprojRow: { sizeGb: 1.2 }, fields })), moe: cut(P.CellModel.of({ row: moe, fields })),
              none: P.CellModel.of({ row: null, fields }), headless: cut(P.CellModel.of({ row: { sizeGb: 7 }, fields })) };
console.log(JSON.stringify(out));
'''


def main():
    node = find_node()
    if node is None:
        print("js cell-plan: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_cell_plan.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT,
                              env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js cell-plan: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:2000])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])

    print("поля ячейки из сохранённого конфига:")
    fl = got["fields"]
    check(fl["text"] == ["0", "1", "1", "1", "0", "0", "999", "", ""],
          "флажок — как его покажет форма: сказано «0» — выключен; не сказано FIT — включён (он из включённых по умолчанию); «true» — "
          "«1»; не сказано SWA_FULL — выключен; «off» — «0»; поле обрезано; пустое — пустое")
    check(fl["value"] == ["4096", "q8_0", "q4_0", "999", ""],
          "значение — пустое поле с умолчанием контроллера за ним (как `поле || state.config`): контекст 4096 и тип V из умолчаний; "
          "negative: сказанное ячейкой не подменяется умолчанием (999, а не 1); ни там, ни там — пусто")
    check(fl["checked"] == [True, False, False, True, True], "включён ли флажок — тем же правилом")
    tg = got["toggle"]
    check(all(tg["onUnlessOff"]) and len(tg["onUnlessOff"]) >= 5 and tg["otherUnset"] == [False, False, False, False] and tg["blank"] is True,
          "не сказано — включены ровно те, что включены, пока их не выключат (defaultOnOptionalToggles); пробелы — тоже «не сказано»; "
          "negative: остальные не сказанные выключены")
    check(tg["said"] == [True, True, True, True, False, False], "сказанное читается как у сервера: 1, true, yes, on — да; прочее — нет")
    check(got["bare"] == ["x", True, False], "читатель без значений и флажков берёт их из текста: значение — текст, флажок — «1»")

    print("KV-кэш и буферы:")
    kv = got["kv"]
    check(kv["auto"] == 0.664063,
          "плотная 70B (80 слоёв, 8 голов KV по 128), контекст 4096, q8_0: 4096 ячеек × 80·8·128 × 2 × 34/32 байта = 0.66 ГБ; PARALLEL "
          "пуст — 4 слота и ОДИН общий кэш (llama-server сам), ячеек столько же")
    check(kv["f16"] == 1.25 and kv["mixed"] == r6(0.625 + 0.625 * 0.5625 / 2), "тип кэша — по своему K и V: f16 — 2 байта, q4_0 — 0.5625")
    check(kv["slots"] == 1.40625 and kv["padded"] == 1.25,
          "три слота без общего кэша — по 1366 → 1536 ячеек на слот, 4608 всего (1.41 ГБ в f16 против 1.25 общего): счёт по слотам; "
          "negative: 4000 токенов дополнены до 4096 (кратно 256), не меньше")
    check(kv["byDefault"] == 1.25, "контекст не сказан ячейкой — берётся у контроллера")
    check(kv["trained"] == [2.5, 2.5, 1.25],
          "defect-history (2026-10-26): пустое окно (и «0») — окно обучения из заголовка, 8192: кэш вдвое больше, чем у 4096; "
          "было 0 — ячейку, что стартует с окном модели, оценка рисовала без кэша; negative: 4096 руками — 4096")
    check(kv["noContext"] == 0 and kv["noLayers"] == 0 and kv["noMeta"] == 0,
          "negative: контекст 0, заголовок без слоёв или без заголовка — кэша 0, а не выдуманное число")
    check(got["cells"] == [{"full": 4608, "swa": 0}, {"full": 4096, "swa": 3584}, {"full": 4096, "swa": 4096}],
          "ячейки кэшей: по слотам 3 × 1536; общий с окном 1024 — окно на слот и физический батч сверху (3 × 1024 + 512); --swa-full — "
          "всё окно во весь контекст")
    check(got["bytes"] == [1.0625, 1.0625, 0.5625, 0.5625, 4, 2, 2, 2, 2, 2], "байт на элемент по типу кэша; незнакомый — как f16")
    bf = got["buffers"]
    check(bf["both"] == r6((512 * 80 * 8192 * 2 * 2.5 + 1024 * 8192 * 2 * 4) / 2 ** 30) and bf["batchOnly"] == r6((1024 * 80 * 8192 * 2 * 2.5 + 1024 * 8192 * 2 * 4) / 2 ** 30),
          "буферы: граф физического батча по всем слоям и планировщик логического; физический не сказан — равен логическому")
    check(bf["none"] == 0 and bf["noWidth"] == 0, "negative: без батчей или без ширины модели буферов 0")

    print("модель ячейки:")
    md = got["model"]
    check(md["dense"] == {"weightsGb": 40.8, "kvGb": 0.664063, "batchGb": bf["both"], "layers": 80, "experts": 0, "expertsGb": 0},
          "вес — файл модели и её проектор; кэш и буферы — по полям ячейки; слои — из заголовка")
    check(md["moe"]["experts"] == 512 and md["moe"]["expertsGb"] == 40 and md["moe"]["layers"] == 48,
          "у MoE — число экспертов и их вес из заголовка (байты тензоров экспертов)")
    check(md["none"] is None, "negative: строки модели в библиотеке нет — модель не известна (null), а не нули")
    check(md["headless"] == {"weightsGb": 7, "kvGb": 0, "batchGb": 0, "layers": 0, "experts": 0, "expertsGb": 0},
          "строка есть, заголовка нет — вес по файлу, слоёв 0: план такой модели не строится (PlacementPlan.known)")

    print()
    if _fail:
        print(f"js cell-plan FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js cell-plan OK: поля ячейки из конфига, KV-кэш и буферы, вес модели — значениями")
    return 0


def r6(x):
    return round(x * 1e6) / 1e6


if __name__ == "__main__":
    sys.exit(main())
