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
  * the model's weight: its file and its projector, its header's layers and experts; nothing known without its row;
  * the speculative draft (CellDraft, 2026-11-07): whether a start loads one is the builder's rule, run here on the table the
    program's builder is held to (contract/draft_load.json, rust/crates/admin/tests/contract.rs); what it weighs and where its
    weights live by SPEC_DRAFT_N_GPU_LAYERS and CPU_MOE_DRAFT, a place not known said and counted on the cards, a file not in the
    library said as not known — never 0; and the model's whole (CellModel.totalGb) with the draft in it, and without it when the
    start loads none;
  * the rest of the builder's speculation on the same table (2026-11-07): the --spec-type a start says, the depth of its draft,
    the word a switched-off speculation writes (none: the file named, nothing loaded) and whether a start drafts (the board's chip).

Run: python3 scripts/test_js_cell_plan.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _contract import Contract  # noqa: E402
from _node import find_node, node_search_paths, probe_args  # noqa: E402

# What a start loads of a draft: ONE table for the program's builder and the browser's copy (CellDraft.start).
DRAFT_LOAD = Contract.table("draft_load")["cases"]

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
const cut = (m) => m && Object.fromEntries(Object.entries(m).map(([k, v]) => [k, typeof v === "number" ? r6(v) : v]));
out.model = { dense: cut(P.CellModel.of({ row, mmprojRow: { sizeGb: 1.2 }, fields })), moe: cut(P.CellModel.of({ row: moe, fields })),
              none: P.CellModel.of({ row: null, fields }), headless: cut(P.CellModel.of({ row: { sizeGb: 7 }, fields })) };

// The draft: what a start loads of one, by the table the program's builder is held to.
const LOAD = JSON.parse(process.env.DRAFT_LOAD);
out.draftLoad = LOAD.map((row) => P.CellDraft.start(P.CellFields.ofConfig(row.config, {})));
// What it weighs and where it lives. The owner's case of 2026-10-27: Qwen3.8-27B's MTP head, 1.28 GB; its header counts the 65
// layers of the whole model. An MoE drafter of 1.5 GB, 1 GiB of it experts, and one whose experts nobody weighed.
const MTP = "Qwen3.8-27B-GGUF/unsloth/default/mtp-Qwen3.8-27B-Q4_0.gguf";
const mtpRow = { path: MTP, kind: "draft", sizeGb: 1.28, ggufMeta: { blockCount: 65 } };
const moeDraft = { path: "m/mtp-moe.gguf", kind: "draft", sizeGb: 1.5, ggufMeta: { blockCount: 1, expertCount: 8, expertBytes: 2 ** 30 } };
const draftOf = (config, row = mtpRow) => {
  const d = P.CellDraft.of({ fields: P.CellFields.ofConfig({ SPEC_TYPE: "draft-mtp", SPEC_DRAFT_MODEL_FILE: row?.path || MTP, ...config }, {}), row });
  return d && { gb: d.gb, place: Object.fromEntries(Object.entries(d.place).map(([k, v]) => [k, typeof v === "number" ? r6(v) : v])),
                state: d.state, said: d.said };
};
out.draft = {
  cards: draftOf({}), all: draftOf({ SPEC_DRAFT_N_GPU_LAYERS: "all" }), whole: draftOf({ SPEC_DRAFT_N_GPU_LAYERS: "65" }),
  ram: draftOf({ SPEC_DRAFT_N_GPU_LAYERS: "0" }), part: draftOf({ SPEC_DRAFT_N_GPU_LAYERS: "20" }), auto: draftOf({ SPEC_DRAFT_N_GPU_LAYERS: "auto" }),
  noLayers: [draftOf({}, { ...mtpRow, ggufMeta: {} }), draftOf({ SPEC_DRAFT_N_GPU_LAYERS: "500" }, { ...mtpRow, ggufMeta: {} })],
  experts: draftOf({ CPU_MOE_DRAFT: "1" }, moeDraft), expertsInRam: draftOf({ CPU_MOE_DRAFT: "1", SPEC_DRAFT_N_GPU_LAYERS: "0" }, moeDraft),
  expertsUnweighed: draftOf({ CPU_MOE_DRAFT: "1" }, { ...moeDraft, ggufMeta: { blockCount: 1, expertCount: 8 } }),
  expertsOff: draftOf({}, moeDraft), dense: draftOf({ CPU_MOE_DRAFT: "1" }),
  unsized: draftOf({ SPEC_DRAFT_N_GPU_LAYERS: "0" }, null),
  off: [draftOf({ SPEC_TYPE: "none" }), draftOf({ SPEC_TYPE: "ngram-mod" }), draftOf({ ENABLE_EMBEDDINGS: "1" }),
        P.CellDraft.of({ fields: P.CellFields.ofConfig({ SPEC_TYPE: "draft-mtp" }, {}), row: mtpRow }), P.CellDraft.of({})],
  // The form reads its draft file itself (memory.js, the form's word on what is chosen): the file it names counts, not the field.
  named: draftOf({ SPEC_DRAFT_MODEL_FILE: "" }) === null
    && P.CellDraft.of({ fields: P.CellFields.ofConfig({ SPEC_TYPE: "draft-mtp" }, {}), file: MTP, row: mtpRow })?.gb === 1.28,
  // No controller default behind the draft: the start sends the cell's own config.
  noDefault: P.CellDraft.of({ fields: P.CellFields.ofConfig({ SPEC_TYPE: "draft-mtp" }, { SPEC_DRAFT_MODEL_FILE: MTP }), row: mtpRow }),
};
// The rest of the builder's speculation (2026-11-07): the word a switched-off speculation writes, and whether a start drafts — the
// board's ⚡ mtp chip.
out.off = { word: P.CellDraft.OFF, start: P.CellDraft.start(P.CellFields.ofConfig({ SPEC_TYPE: P.CellDraft.OFF, SPEC_DRAFT_MODEL_FILE: MTP }, {})) };
out.drafts = [["draft-mtp", MTP], ["", MTP], ["draft-mtp", ""], ["ngram-mod", MTP], ["none", MTP], ["draft-eagle3", ""], ["", ""]]
  .map(([type, file]) => P.CellDraft.drafts(P.CellFields.ofConfig({ SPEC_TYPE: type }, {}), file));
out.draftsEmbeddings = P.CellDraft.drafts(P.CellFields.ofConfig({ SPEC_TYPE: "draft-mtp", ENABLE_EMBEDDINGS: "1" }, {}), MTP);
// The model with its draft: one whole the estimate, the map and the machine page read.
const withDraft = (config, draftRow = mtpRow) => cut(P.CellModel.of({ row, fields: P.CellFields.ofConfig({ CTX_SIZE: "4096", CACHE_TYPE_K: "q8_0",
  CACHE_TYPE_V: "q8_0", BATCH_SIZE: "1024", UBATCH_SIZE: "512", SPEC_TYPE: "draft-mtp", SPEC_DRAFT_MODEL_FILE: MTP, ...config }, {}), draftRow }));
const brief = (m) => m && { draft: m.draft ? m.draft.state : null, cards: m.draftCardsGb, ram: m.draftRamGb, files: m.filesGb, total: m.totalGb,
                            weights: m.weightsGb };
out.modelDraft = { mtp: brief(withDraft({})), ram: brief(withDraft({ SPEC_DRAFT_N_GPU_LAYERS: "0" })), none: brief(withDraft({ SPEC_TYPE: "none" })),
                   ngram: brief(withDraft({ SPEC_TYPE: "ngram-simple" })), noFile: brief(withDraft({ SPEC_DRAFT_MODEL_FILE: "" })),
                   unsized: brief(withDraft({}, null)) };
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
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC",
               "DRAFT_LOAD": json.dumps(DRAFT_LOAD)}
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
    dense = md["dense"]
    check({k: dense[k] for k in ("weightsGb", "kvGb", "batchGb", "layers", "experts", "expertsGb")}
          == {"weightsGb": 40.8, "kvGb": 0.664063, "batchGb": bf["both"], "layers": 80, "experts": 0, "expertsGb": 0},
          "вес — файл модели и её проектор; кэш и буферы — по полям ячейки; слои — из заголовка")
    check(dense["draft"] is None and dense["draftCardsGb"] == 0 and dense["draftRamGb"] == 0 and dense["filesGb"] == 40.8
          and abs(dense["totalGb"] - (40.8 + 0.6640625 + 1.625)) < 1e-5,
          "целое — файлы, кэш и буферы (40.8 + 0.66 + 1.63); черновика нет — null и нули его частей, файлы — модель с проектором")
    check(md["moe"]["experts"] == 512 and md["moe"]["expertsGb"] == 40 and md["moe"]["layers"] == 48,
          "у MoE — число экспертов и их вес из заголовка (байты тензоров экспертов)")
    check(md["none"] is None, "negative: строки модели в библиотеке нет — модель не известна (null), а не нули")
    check(md["headless"] == {"weightsGb": 7, "kvGb": 0, "batchGb": 0, "layers": 0, "experts": 0, "expertsGb": 0, "draft": None,
                             "draftCardsGb": 0, "draftRamGb": 0, "filesGb": 7, "totalGb": 7},
          "строка есть, заголовка нет — вес по файлу, слоёв 0: план такой модели не строится (PlacementPlan.known)")

    print("черновик спекуляции — что грузит старт (contract/draft_load.json, та же таблица у сборщика команды):")
    for row, js in zip(DRAFT_LOAD, got["draftLoad"]):
        check(js == row["start"], f"{row['why']} (got {js})")
    check(len(got["draftLoad"]) == len(DRAFT_LOAD), "двойник ответил на каждый случай таблицы")

    print("выключенная спекуляция и чип ⚡ mtp (2026-11-07):")
    check(got["off"] == {"word": "none", "start": {"loads": False, "spec": None, "layers": None, "nMax": None, "nMin": None, "cpuMoe": False}},
          "выключенная спекуляция пишет none — слово сборщика: файл назван, а старт его не грузит и не говорит ни --spec-type, ни "
          "глубины; negative: пустой тип при названном файле сборщик грузит (таблица выше)")
    check(got["drafts"] == [True, True, True, False, False, False, False] and got["draftsEmbeddings"] is False,
          "черновик рисуется, когда старт черновиком пишет: файл с типом и без, своя голова MTP; negative: ngram-*, none при файле, тип "
          "черновика без файла, ничего, ячейка эмбеддингов")

    print("черновик — сколько весит и где живут его веса:")
    dr = got["draft"]
    check(dr["cards"] == {"gb": 1.28, "place": {"cardsGb": 1.28, "ramGb": 0, "known": True, "why": ""}, "state": "cards",
                          "said": {"key": "draftKvNotCounted", "args": {}}},
          "positive (дефект 2026-10-27): голова MTP 1.28 ГБ, SPEC_DRAFT_N_GPU_LAYERS пуст (999) — вся на картах; "
          "её собственный KV-кэш не посчитан, и это сказано")
    check(dr["all"]["state"] == "cards" and dr["whole"]["state"] == "cards",
          "«all» и число не меньше слоёв черновика (65 из 65) — тоже все на картах")
    check(dr["ram"]["place"] == {"cardsGb": 0, "ramGb": 1.28, "known": True, "why": ""} and dr["ram"]["state"] == "ram"
          and dr["ram"]["said"]["key"] == "draftInRam",
          "SPEC_DRAFT_N_GPU_LAYERS 0 — черновик весь в RAM, на картах 0; negative: не на картах")
    check(dr["part"]["place"] == {"cardsGb": 1.28, "ramGb": 0, "known": False, "why": "SPEC_DRAFT_N_GPU_LAYERS 20"}
          and dr["part"]["state"] == "unknown" and dr["part"]["said"] == {"key": "draftWhereUnknown", "args": {"why": "SPEC_DRAFT_N_GPU_LAYERS 20"}},
          "20 слоёв из 65 — какие останутся на картах, здесь не сказать: место не известно, посчитан на картах, и сказано почему")
    check(dr["auto"]["state"] == "unknown" and dr["auto"]["place"]["why"] == "SPEC_DRAFT_N_GPU_LAYERS auto",
          "«auto» — тоже не известно, а не «все на картах»")
    check([d["state"] for d in dr["noLayers"]] == ["cards", "unknown"],
          "заголовок слоёв не говорит: 999 — все (это и есть «все» сборщика); negative: 500 — не известно")
    check(dr["experts"]["place"] == {"cardsGb": 0.5, "ramGb": 1, "known": True, "why": ""} and dr["experts"]["state"] == "split"
          and dr["experts"]["said"] == {"key": "draftExpertsInRam", "args": {"cards": "0.50 GB", "ram": "1.00 GB"}},
          "CPU_MOE_DRAFT у MoE-черновика — его эксперты (1 ГиБ) в RAM, остальное (0.5) на картах")
    check(dr["expertsInRam"]["state"] == "ram" and dr["expertsInRam"]["place"]["ramGb"] == 1.5,
          "эксперты в RAM при 0 слоях на картах — весь черновик в RAM")
    check(dr["expertsUnweighed"]["state"] == "unknown" and dr["expertsUnweighed"]["place"]["why"] == "CPU_MOE_DRAFT"
          and dr["expertsUnweighed"]["place"]["cardsGb"] == 1.5,
          "вес экспертов не известен — место не известно (из-за CPU_MOE_DRAFT), посчитан на картах")
    check(dr["expertsOff"]["state"] == "cards" and dr["dense"]["state"] == "cards",
          "negative: без CPU_MOE_DRAFT эксперты на картах; у плотного черновика флаг ничего не двигает")
    check(dr["unsized"] == {"gb": None, "place": {"cardsGb": 0, "ramGb": 0, "known": True, "why": ""}, "state": "unsized",
                            "said": {"key": "draftNotInLibrary", "args": {"file": "Qwen3.8-27B-GGUF/unsloth/default/mtp-Qwen3.8-27B-Q4_0.gguf"}}},
          "файла черновика нет в библиотеке — размер не известен (null, не 0), и сказано, какого файла нет")
    check(dr["off"] == [None, None, None, None, None],
          "negative: SPEC_TYPE none, ngram-*, ячейка эмбеддингов, draft-mtp без файла, без полей — черновика нет")
    check(dr["named"] is True, "файл черновика может назвать читатель (форма — своим словом о выборе); negative: пустой — нет черновика")
    check(dr["noDefault"] is None, "negative: умолчание контроллера за пустым полем черновика не стоит — старт шлёт конфиг ячейки")

    print("модель с черновиком — одно целое для формы, карты и страницы машины:")
    mdr = got["modelDraft"]
    base_total = mdr["none"]["total"]
    check(mdr["mtp"]["draft"] == "cards" and mdr["mtp"]["cards"] == 1.28 and mdr["mtp"]["ram"] == 0 and mdr["mtp"]["files"] == 40.88
          and abs(mdr["mtp"]["total"] - (base_total + 1.28)) < 1e-5 and mdr["mtp"]["weights"] == 39.6,
          "positive: draft-mtp с файлом — файлы 39.6 + 1.28, целое больше на 1.28; веса модели (план делит их по слоям) — без черновика")
    check(mdr["ram"]["cards"] == 0 and mdr["ram"]["ram"] == 1.28 and abs(mdr["ram"]["total"] - (base_total + 1.28)) < 1e-5,
          "черновик в RAM — в целом он есть, на картах его 0")
    check(mdr["none"]["draft"] is None and mdr["none"]["files"] == 39.6 and mdr["ngram"] == mdr["none"] and mdr["noFile"] == mdr["none"],
          "negative: SPEC_TYPE none, ngram-* и нет файла — черновик ничего не добавляет")
    check(mdr["unsized"]["draft"] == "unsized" and mdr["unsized"]["files"] == 39.6 and mdr["unsized"]["total"] == base_total,
          "черновика нет в библиотеке — он назван (unsized), а в сумме его нет: неизвестное не нарисовано нулём и не выдумано")

    print()
    if _fail:
        print(f"js cell-plan FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js cell-plan OK: поля ячейки из конфига, KV-кэш и буферы, вес модели, черновик спекуляции — значениями")
    return 0


def r6(x):
    return round(x * 1e6) / 1e6


if __name__ == "__main__":
    sys.exit(main())
