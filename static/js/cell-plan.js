// What a llama.cpp cell takes, out of its fields and its model's header: the KV cache and the compute buffers as llama.cpp
// sizes them, and the model's weights. One rule for the cell's form, which reads the fields off the page (memory.js), and for
// the machine page's bench, which reads them off the cell's stored config (topology-nodes.js → machine-head.js, 1.3.635): the
// owner's "the exact size, and in colour where the model is and where the cache" (2026-10-25) needs the bench and the cell
// window to say one figure, and two copies of this accounting would drift as the form's and the server's once did.
import { AskedWindow } from "./asked-window.js";
import { defaultOnOptionalToggles, toggleFields } from "./constants.js";
import { DraftFile } from "./draft-file.js";
import { formatBool, formatSizeGb } from "./utils.js";

/**
 * A cell's fields as the estimate reads them. `text` is what a field holds (a box as "1" or "0"), `value` the same with the
 * controller's default behind an empty field — the form's `field || state.config[key]` — and `checked` whether a box is on.
 * The form builds one over its inputs (memory.js); a stored config is read by `ofConfig`, as the form shows it when it opens.
 */
export class CellFields {
  constructor({ text = () => "", value = null, checked = null } = {}) {
    this.text = text;
    this.value = value || text;
    this.checked = checked || ((key) => formatBool(text(key)));
  }

  /** A box of a stored config: what the config says, or — unsaid — on for the optional toggles that are on unless turned off,
   *  off for the rest (the form's toggleChecked). */
  static toggle(field, config) {
    const value = config?.[field];
    if (value === undefined || value === null || String(value).trim() === "") return defaultOnOptionalToggles.includes(field);
    return formatBool(value);
  }

  /** The fields of a stored config, with `defaults` (the controller's config) behind an empty one. */
  static ofConfig(config = {}, defaults = {}) {
    const text = (key) => (toggleFields.includes(key) ? (CellFields.toggle(key, config) ? "1" : "0")
      : String(config?.[key] ?? "").trim());
    return new CellFields({ text, value: (key) => text(key) || String(defaults?.[key] ?? "").trim(),
                            checked: (key) => CellFields.toggle(key, config) });
  }
}

/**
 * How a model keeps its KV cache, and how much of it a cell's fields ask for.
 *
 * `layout(meta)`: read from the model's header, in elements per token summed over the layers of each kind:
 * { full: {k, v}, swa: {k, v}, window } — `full` for the layers that keep the whole context, `swa` for the layers that
 * attend through a sliding window of `window` tokens and keep only that. null when the header does not say enough
 * (no layer count, no head width): the estimate then says nothing, rather than a number it made up.
 *
 * This is llama.cpp's own accounting (llama-hparams.cpp n_embd_k_gqa, llama-kv-cache-iswa.cpp): a layer caches n_head_kv
 * heads of key_length for K and of value_length for V; a windowed layer has its own head width (`key_length_swa`, the
 * full one where the file says none); the last `shared_kv_layers` layers cache nothing of their own.
 *
 * Gemma 4 12B: 48 layers, 8 keep the whole context with ONE head of 512 (16 KB a token in f16), the other 40 keep a
 * window of 1024 with 8 heads of 256 (320 KB a token). The form used to count all 48 layers with 16 heads of 512 over the
 * whole context: 264 GB of cache for the 180000 tokens of cell :22007 (2026-10-19, "277 GB" with the weights), where the
 * engine takes 5.6 GB (4.2 GB with its own physical batch of 512; the windows hold the batch too). A header that gives no flags
 * for the windowed layers (Gemma 2 and 3 keep theirs in the engine's code) leaves every layer with the whole context: more
 * than the engine takes, never less.
 *
 * A hybrid model's recurrent layers keep no cache at all (llama-memory-hybrid.cpp): only its attention layers do. Most
 * hybrids give such a layer no KV heads, which the heads of each layer already say; the Qwen3-Next family names its
 * attention layers instead — RECURRENT_BY_INTERVAL. Qwen3-Coder-Next attends in 12 of its 48 layers, and its 262144 tokens
 * came to 12.75 GB of q8_0 cache counted over all 48, 3.19 GB as llama.cpp keeps it. The recurrent state those layers
 * keep instead (some 2 MB a layer for each slot) is not counted.
 */
export class KvCache {
  /** The slots of a llama-server whose PARALLEL field is empty: it takes 4, with ONE cache for all of them (server.cpp of
   *  b10357: "n_parallel is set to auto, using n_parallel = 4 and kv_unified = true"). */
  static AUTO_SLOTS = 4;
  /** llama.cpp rounds the cells of each cache up to this many (the padding of llama-kv-cache-iswa.cpp). */
  static PAD = 256;
  /** The architectures whose recurrent layers llama.cpp marks by `full_attention_interval` — every interval-th layer
   *  attends — and by 4 when the file names none (src/models/qwen3next.cpp, qwen35.cpp, qwen35moe.cpp of b1141). */
  static RECURRENT_BY_INTERVAL = { architectures: new Set(["qwen3next", "qwen35", "qwen35moe"]), interval: 4 };

  static bytesPerElement(cacheType) {
    const normalized = String(cacheType || "f16").toLowerCase();
    if (normalized.includes("q8_0")) return 34 / 32;
    if (normalized.includes("q6_k")) return 0.8125;
    if (normalized.includes("q5")) return 0.7;
    if (normalized.includes("q4")) return 0.5625;
    if (normalized.includes("iq4")) return 0.5625;
    if (normalized.includes("f32")) return 4;
    if (normalized.includes("bf16") || normalized.includes("f16")) return 2;
    return 2;
  }

  static layout(meta) {
    const m = meta || {};
    const layers = Number(m.blockCount || 0);
    if (!layers) return null;
    const headCount = Number(m.headCount || 0);
    const perLayer = Array.isArray(m.headCountKvLayers) && m.headCountKvLayers.length === layers ? m.headCountKvLayers : null;
    const heads = (il) => (perLayer ? Number(perLayer[il]) : Number(m.headCountKv || headCount || 0));
    const keyFull = Number(m.keyLength || 0) || (headCount ? Number(m.embeddingLength || 0) / headCount : 0);
    const valueFull = Number(m.valueLength || 0) || keyFull;
    const keySwa = Number(m.keyLengthSwa || 0) || keyFull;
    const valueSwa = Number(m.valueLengthSwa || 0) || valueFull;
    const window = Number(m.slidingWindow || 0);
    const flags = window > 0 && Array.isArray(m.slidingWindowLayers) && m.slidingWindowLayers.length === layers ? m.slidingWindowLayers : null;
    const own = layers - Math.max(0, Math.min(layers, Number(m.sharedKvLayers || 0)));
    const recurrent = KvCache.recurrent(m, layers);
    const out = { full: { k: 0, v: 0 }, swa: { k: 0, v: 0 }, window: 0 };
    for (let il = 0; il < own; il += 1) {
      if (recurrent(il)) continue;
      const windowed = !!(flags && flags[il]);
      const kind = windowed ? out.swa : out.full;
      kind.k += heads(il) * (windowed ? keySwa : keyFull);
      kind.v += heads(il) * (windowed ? valueSwa : valueFull);
    }
    if (out.swa.k || out.swa.v) out.window = window;
    // The value width defaults to the key width, so keys are the only thing that can be missing.
    if (!(out.full.k + out.swa.k)) return null;
    return out;
  }

  /** Whether layer `il` of a model is recurrent, keeping no KV cache: by the flags of `attention.recurrent_layers`, else by
   *  the interval of the architectures that use one. Any other model has no recurrent layer this can see. */
  static recurrent(meta, layers) {
    const m = meta || {};
    const flags = Array.isArray(m.recurrentLayers) && m.recurrentLayers.length === layers ? m.recurrentLayers : null;
    if (flags) return (il) => Number(flags[il]) !== 0;
    const by = KvCache.RECURRENT_BY_INTERVAL;
    const interval = Number(m.fullAttentionInterval || 0) || (by.architectures.has(String(m.architecture || "")) ? by.interval : 0);
    return interval > 1 ? (il) => (il + 1) % interval !== 0 : () => false;
  }

  static pad(cells) {
    return Math.ceil(cells / KvCache.PAD) * KvCache.PAD;
  }

  /** The cells of the two caches for a context of `ctx` tokens (llama-kv-cache-iswa.cpp). The whole-context cache has
   *  ctx cells, in slots of their own unless the cache is unified; the windowed cache has a window for each slot and the
   *  physical batch on top, or the whole context where that is less — or where --swa-full asks for it. */
  static cells(ctx, window, { slots, unified, ubatch, swaFull }) {
    const n = Math.max(1, slots);
    const each = unified ? KvCache.pad(ctx) : KvCache.pad(Math.ceil(ctx / n));
    const full = unified ? each : each * n;
    if (!window) return { full, swa: 0 };
    if (swaFull) return { full, swa: full };
    const swaEach = KvCache.pad(Math.min(each, window * (unified ? n : 1) + ubatch));
    return { full, swa: unified ? swaEach : swaEach * n };
  }

  /** The cache a model's header keeps under a cell's fields (CellFields), GB; 0 when the header or the context says nothing.
   *  The window is the one the start asks for (AskedWindow): an empty CTX_SIZE is the window the model was trained for —
   *  counted as 0, a cell that starts with 262144 tokens was drawn keeping no cache at all. */
  static gb(meta, fields) {
    const layout = KvCache.layout(meta);
    const ctx = AskedWindow.of(fields.value("CTX_SIZE"), meta?.contextLength) || 0;
    if (!layout || !ctx) return 0;
    const kBytes = KvCache.bytesPerElement(fields.value("CACHE_TYPE_K"));
    const vBytes = KvCache.bytesPerElement(fields.value("CACHE_TYPE_V"));
    // The slots, the cache's kind and the batch decide the windowed cache only; a model with no window ignores them.
    const asked = Number(fields.value("PARALLEL") || 0);
    const slots = asked >= 1 ? asked : KvCache.AUTO_SLOTS;
    const unified = asked >= 1 ? !!fields.checked("KV_UNIFIED") : true;
    const batch = Number(fields.value("BATCH_SIZE") || 0);
    const ubatch = Number(fields.value("UBATCH_SIZE") || 0) || 512;
    const cells = KvCache.cells(ctx, layout.window, { slots, unified, ubatch: batch ? Math.min(ubatch, batch) : ubatch,
                                                      swaFull: !!fields.checked("SWA_FULL") });
    const bytes = cells.full * (layout.full.k * kBytes + layout.full.v * vBytes)
                + cells.swa * (layout.swa.k * kBytes + layout.swa.v * vBytes);
    return bytes / (1024 ** 3);
  }
}

/** The compute buffers of a llama.cpp start, GB, by its batches and its model's width — the graph of a physical batch over
 *  every layer and the scheduler's of a logical one; 0 when the header or the fields do not say them. */
export class BatchBuffers {
  static gb(meta, fields) {
    const m = meta || {};
    const layers = Number(m.blockCount || 0);
    const embedding = Number(m.embeddingLength || 0);
    const batch = Number(fields.value("BATCH_SIZE") || 0);
    const ubatch = Number(fields.value("UBATCH_SIZE") || batch || 0);
    if (!layers || !embedding || (!batch && !ubatch)) return 0;
    const computeBytes = KvCache.bytesPerElement("f16");
    const physicalBatch = Math.max(0, Math.min(ubatch || batch, batch || ubatch));
    const logicalBatch = Math.max(0, batch);
    const graphBytes = physicalBatch * layers * embedding * computeBytes * 2.5;
    const schedulerBytes = logicalBatch * embedding * computeBytes * 4;
    return (graphBytes + schedulerBytes) / (1024 ** 3);
  }
}

/**
 * The draft model a llama.cpp cell loads beside its model for speculative decoding: whether it loads one, what that weighs and
 * where its weights live. 2026-10-27: a 27B with its 1.28 GB MTP draft on a 31.8 GB card read "Runtime ≈ 27.3 GB", and every
 * verdict built on that figure — the form's, the placement map's, the machine page's — was short by the draft.
 *
 * Whether a start loads a draft FILE is the builder's (rust/crates/admin/src/config/args/switches.rs, `speculation`), and `start`
 * is that rule, held to one table with it (contract/draft_load.json, run through the builder by rust/crates/admin/tests/contract.rs
 * and through this class by scripts/test_js_cell_plan.py): a cell that computes no embeddings, whose SPEC_TYPE is no ngram-*
 * (those draft from the prompt and load nothing), that names a file, of a type that is not "none" — SPEC_TYPE ("mtp" is
 * draft-mtp), or the file's own when it says none (DraftFile.launchType). draft-mtp with no file is the model's own MTP head,
 * inside the model's file: nothing more is loaded. The cell's own fields, with no controller default behind them: a start sends
 * its cell's config, and an empty draft field is no draft.
 *
 * Where its weights live is --gpu-layers-draft (SPEC_DRAFT_N_GPU_LAYERS, 999 when empty) and --spec-draft-cpu-moe
 * (CPU_MOE_DRAFT): every layer on the cards for "all", "max" or a number of at least its layers (EVERY where its header gives
 * none), every layer in RAM for 0, and an MoE draft's experts in RAM with CPU_MOE_DRAFT. What a number between does (which layers
 * llama.cpp keeps on the cards is its own, and a sidecar's header may count the layers of the whole model), "auto", and the
 * experts of a draft whose header does not weigh them are not known here: the draft is then counted on the cards — where a card
 * short of it fails the start — and the estimate says so.
 *
 * Its own KV cache is not counted: how llama.cpp sizes the draft's context (one per slot or not, --ctx-size-draft) is its
 * server's, and nothing here reads it. The estimate says so beside the figure, rather than leaving it out in silence.
 *
 * The same rule says the rest of the builder's speculation (2026-11-07), and every place that tells it reads it here: the switch
 * of the cell form and of the new-cell wizard (on while the start speculates; off writes OFF), the board's ⚡ mtp chip (while it
 * drafts) and the board's command preview (topology-nodes.js). The switch wrote an empty SPEC_TYPE for off and kept the draft
 * file, and the builder launches a file named with no type by the file's own type: "off" still loaded the draft. The preview drew
 * --model-draft for "none", and the chip lit for any draft file named and for a model whose name says -mtp.
 */
export class CellDraft {
  /** What --gpu-layers-draft says when SPEC_DRAFT_N_GPU_LAYERS is empty: every layer, the builder's own default. */
  static EVERY = 999;
  /** What a switched-off speculation writes into SPEC_TYPE: the builder's word for none. The draft file stays in its field, so the
   *  switch turned on again gives the cell the same draft; with this type the builder loads it not, and asks for no MTP head. */
  static OFF = "none";
  /** --spec-draft-n-max of the model's own MTP head when SPEC_DRAFT_N_MAX is empty: the builder's default (a draft file has none). */
  static HEAD_MAX = "2";

  /** What a start with these fields (CellFields) and this draft file says of speculation, in the builder's words: {loads, spec,
   *  layers, nMax, nMin, cpuMoe} — whether --model-draft is in its command; its --spec-type, null with none (a draft file loaded,
   *  the model's own MTP head — draft-mtp with no file — or ngram-*, which drafts from the prompt and loads nothing); the
   *  --gpu-layers-draft that comes with --model-draft; --spec-draft-n-max and --spec-draft-n-min, said with a draft or a head;
   *  and whether --spec-draft-cpu-moe is said (the builder says it with or without a draft). */
  static start(fields, file = fields.text("SPEC_DRAFT_MODEL_FILE")) {
    const embeddings = !!fields.checked("ENABLE_EMBEDDINGS");
    const said = String(fields.text("SPEC_TYPE") ?? "").trim().toLowerCase();
    const type = embeddings ? "" : said === "mtp" ? "draft-mtp" : said;
    const path = String(file ?? "").trim();
    const kind = type || (path ? new DraftFile(path).launchType : "");
    const ngram = type.startsWith("ngram-");
    const loads = !embeddings && !ngram && !!path && kind !== CellDraft.OFF;
    // The head inside the model: draft-mtp with no file. A file named of type "none" is no head either.
    const head = !ngram && !path && type === "draft-mtp";
    const word = (key) => String(fields.text(key) ?? "").trim();
    return {
      loads,
      spec: ngram ? type : loads ? kind : head ? type : null,
      layers: loads ? word("SPEC_DRAFT_N_GPU_LAYERS") || String(CellDraft.EVERY) : null,
      nMax: loads ? word("SPEC_DRAFT_N_MAX") || null : head ? word("SPEC_DRAFT_N_MAX") || CellDraft.HEAD_MAX : null,
      nMin: loads || head ? word("SPEC_DRAFT_N_MIN") || null : null,
      cpuMoe: !embeddings && !!fields.checked("CPU_MOE_DRAFT"),
    };
  }

  /** Whether a start drafts with a model or the model's own head — what the board's ⚡ mtp chip says of a cell; ngram-* drafts with
   *  neither. */
  static drafts(fields, file) {
    return String(CellDraft.start(fields, file).spec || "").startsWith("draft-");
  }

  /** The draft a start with these fields loads, `row` the library's row of its file (none when the library has not the file); null
   *  when it loads none. `file` is the cell's own field unless the caller reads it otherwise (the form: memory.js). */
  static of({ fields, file = fields?.text("SPEC_DRAFT_MODEL_FILE"), row = null } = {}) {
    if (!fields) return null;
    const start = CellDraft.start(fields, file);
    return start.loads ? new CellDraft(String(file).trim(), start, row) : null;
  }

  constructor(file, start, row = null) {
    this.file = file;
    this.type = start.spec;
    this.layers = start.layers;
    this.cpuMoe = start.cpuMoe;
    this.row = row || null;
  }

  /** What its file weighs, GB; null when the library has no row for it — not known, and not 0. */
  get gb() {
    const size = Number(this.row?.sizeGb);
    return this.row && Number.isFinite(size) && size > 0 ? size : null;
  }

  /** Where its weights live: {cardsGb, ramGb, known, why} — `why` the field that leaves it not known ("" when it is known), and
   *  both figures 0 while its size is not known. */
  get place() {
    const gb = this.gb ?? 0;
    const meta = this.row?.ggufMeta || {};
    const word = String(this.layers || "").toLowerCase();
    const n = /^\d+$/.test(word) ? Number(word) : null;
    if (n === 0) return { cardsGb: 0, ramGb: gb, known: true, why: "" };
    const layers = Number(meta.blockCount) || 0;
    const every = word === "all" || word === "max" || (n !== null && n >= (layers > 0 ? layers : CellDraft.EVERY));
    if (!every) return { cardsGb: gb, ramGb: 0, known: false, why: `SPEC_DRAFT_N_GPU_LAYERS ${this.layers}` };
    if (!this.cpuMoe || !(Number(meta.expertCount) > 0)) return { cardsGb: gb, ramGb: 0, known: true, why: "" };
    const expertsGb = (Number(meta.expertBytes) || 0) / (1024 ** 3);
    if (!(expertsGb > 0 && expertsGb < gb)) return { cardsGb: gb, ramGb: 0, known: false, why: "CPU_MOE_DRAFT" };
    return { cardsGb: gb - expertsGb, ramGb: expertsGb, known: true, why: "" };
  }

  /** Where it is, in a word — the estimate's data-t-state: "unsized" (not in the library), "unknown" (its place is not known and
   *  it is counted on the cards), "ram", "split" (its experts in RAM, the rest on the cards) or "cards". */
  get state() {
    if (this.gb === null) return "unsized";
    const place = this.place;
    if (!place.known) return "unknown";
    if (!(place.cardsGb > 0)) return "ram";
    return place.ramGb > 0 ? "split" : "cards";
  }

  /** What the estimate says of it beside the figure, as the key of a message and its words: where its weights go when that is not
   *  the cards, and what is not counted. The words are the form's to translate (form.js): this module reads no language. */
  get said() {
    const place = this.place;
    return {
      unsized: { key: "draftNotInLibrary", args: { file: this.file } },
      unknown: { key: "draftWhereUnknown", args: { why: place.why } },
      ram: { key: "draftInRam", args: {} },
      split: { key: "draftExpertsInRam", args: { cards: formatSizeGb(place.cardsGb), ram: formatSizeGb(place.ramGb) } },
      cards: { key: "draftKvNotCounted", args: {} },
    }[this.state];
  }
}

/**
 * What a llama.cpp cell's model weighs and keeps, as the placement plan reads it (placement.js PlacementPlan's `model`):
 * {weightsGb, kvGb, batchGb, layers, experts, expertsGb} — its files (the model and its projector), its cache and buffers
 * under its fields, the layer and expert counts of its header and what its experts weigh — and its draft (CellDraft, null when
 * it loads none) with the part of it on the cards and in RAM (`draftCardsGb`, `draftRamGb`), what its files weigh with the draft
 * (`filesGb`) and the whole of it (`totalGb`): the one sum the form's estimate, its placement map and the machine page's verdicts
 * all read. null when the library has no row for the model: the files' size alone is then all anyone knows.
 */
export class CellModel {
  static of({ row = null, mmprojRow = null, draftFile, draftRow = null, fields } = {}) {
    if (!row) return null;
    const meta = row.ggufMeta || {};
    const weightsGb = Number(row.sizeGb || 0) + Number(mmprojRow?.sizeGb || 0);
    const kvGb = KvCache.gb(meta, fields);
    const batchGb = BatchBuffers.gb(meta, fields);
    const draft = CellDraft.of({ fields, file: draftFile, row: draftRow });
    const place = draft ? draft.place : { cardsGb: 0, ramGb: 0 };
    // A draft not in the library weighs what nobody knows: it is said (CellDraft.state), not added as 0 nor guessed.
    const filesGb = weightsGb + (draft?.gb ?? 0);
    return {
      weightsGb,
      kvGb,
      batchGb,
      layers: Number(meta.blockCount || 0),
      experts: Number(meta.expertCount || 0),
      expertsGb: Number(meta.expertBytes || 0) / (1024 ** 3),
      draft,
      draftCardsGb: place.cardsGb,
      draftRamGb: place.ramGb,
      filesGb,
      totalGb: filesGb + kvGb + batchGb,
    };
  }
}
