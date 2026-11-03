// What a llama.cpp cell takes, out of its fields and its model's header: the KV cache and the compute buffers as llama.cpp
// sizes them, and the model's weights. One rule for the cell's form, which reads the fields off the page (memory.js), and for
// the machine page's bench, which reads them off the cell's stored config (topology-nodes.js → machine-head.js, 1.3.635): the
// owner's "the exact size, and in colour where the model is and where the cache" (2026-10-25) needs the bench and the cell
// window to say one figure, and two copies of this accounting would drift as the form's and the server's once did.
import { AskedWindow } from "./asked-window.js";
import { defaultOnOptionalToggles, toggleFields } from "./constants.js";
import { formatBool } from "./utils.js";

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
 * What a llama.cpp cell's model weighs and keeps, as the placement plan reads it (placement.js PlacementPlan's `model`):
 * {weightsGb, kvGb, batchGb, layers, experts, expertsGb} — its files (the model and its projector), its cache and buffers
 * under its fields, the layer and expert counts of its header and what its experts weigh. null when the library has no row
 * for the model: the files' size alone is then all anyone knows.
 */
export class CellModel {
  static of({ row = null, mmprojRow = null, fields } = {}) {
    if (!row) return null;
    const meta = row.ggufMeta || {};
    return {
      weightsGb: Number(row.sizeGb || 0) + Number(mmprojRow?.sizeGb || 0),
      kvGb: KvCache.gb(meta, fields),
      batchGb: BatchBuffers.gb(meta, fields),
      layers: Number(meta.blockCount || 0),
      experts: Number(meta.expertCount || 0),
      expertsGb: Number(meta.expertBytes || 0) / (1024 ** 3),
    };
  }
}
