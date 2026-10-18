// VRAM/RAM estimation for the launch form (KV cache, buffers, compute target).
import { renderCommandPreview } from "./command-preview.js";
import { moonshineModelGb, whisperModelGb } from "./constants.js";
import { syncFavoriteMirrors } from "./favorites.js";
// Device-in-ENV helpers for command-path runners. Imported for use inside
// functions only (llama-edit.js also imports this module) — the runtime cycle
// is safe because nothing here runs at module load.
import { _applyDeviceToEnv, _commandCellSlot, _envDeviceState, runnerFixedVramGb, runnerRegistry, usesLlamaConfig } from "./llama-edit.js";
import { modelChoiceOf, modelsByPath, readConfigForm, renderAsideVramBar, renderModelInsight } from "./form.js";
import { t } from "./i18n.js";
import { RamPlanAsk } from "./ram-plan.js";
import { _trClientCpu, _trClientGpus } from "./remote-cells.js";
import { SplitMode } from "./split-mode.js";
import { state, topology } from "./state.js";
import { $, escapeHtml, pill } from "./utils.js";

export function formatSizeGb(value) {
  const n = Number(value || 0);
  if (!Number.isFinite(n) || n <= 0) return "n/a";
  return `${n.toFixed(n >= 10 ? 1 : 2)} GB`;
}

export function cacheBytesPerElement(cacheType) {
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

export function estimateKvCacheGb(row, pfx = "") {
  const meta = row?.ggufMeta || {};
  const layers = Number(meta.blockCount || 0);
  const headCount = Number(meta.headCount || 0);
  const headCountKv = Number(meta.headCountKv || headCount || 0);
  const embedding = Number(meta.embeddingLength || 0);
  const keyLength = Number(meta.keyLength || 0);
  const valueLength = Number(meta.valueLength || 0);
  const fallbackKvWidth = headCount ? (embedding / headCount) * headCountKv : 0;
  // key_length and value_length are the width of ONE head (attention.key_length), and a layer caches headCountKv of them for
  // every token. Used as they stood they made the cache headCountKv times too small — 8 times for a Llama 3: "KV≈0.08 GB" for
  // a 70B at 4k with q8_0, 0.66 GB held (2026-10-17). The fallback just above, which does multiply, was the only honest path;
  // both now give one number for one model (the width of one head times the heads, or the embedding cut by the query heads).
  const keyWidth = keyLength ? keyLength * headCountKv : fallbackKvWidth;
  const valueWidth = valueLength ? valueLength * headCountKv : keyWidth;
  const ctx = Number($(pfx + "CTX_SIZE")?.value || state.config.CTX_SIZE || 0);
  if (!layers || !keyWidth || !valueWidth || !ctx) return 0;
  const kBytes = cacheBytesPerElement($(pfx + "CACHE_TYPE_K")?.value || state.config.CACHE_TYPE_K);
  const vBytes = cacheBytesPerElement($(pfx + "CACHE_TYPE_V")?.value || state.config.CACHE_TYPE_V);
  const bytes = ctx * layers * ((keyWidth * kBytes) + (valueWidth * vBytes));
  return bytes / (1024 ** 3);
}

export function estimateBatchBuffersGb(row, pfx = "") {
  const meta = row?.ggufMeta || {};
  const layers = Number(meta.blockCount || 0);
  const embedding = Number(meta.embeddingLength || 0);
  const batch = Number($(pfx + "BATCH_SIZE")?.value || state.config.BATCH_SIZE || 0);
  const ubatch = Number($(pfx + "UBATCH_SIZE")?.value || state.config.UBATCH_SIZE || batch || 0);
  if (!layers || !embedding || (!batch && !ubatch)) return 0;
  const computeBytes = cacheBytesPerElement("f16");
  const physicalBatch = Math.max(0, Math.min(ubatch || batch, batch || ubatch));
  const logicalBatch = Math.max(0, batch);
  const graphBytes = physicalBatch * layers * embedding * computeBytes * 2.5;
  const schedulerBytes = logicalBatch * embedding * computeBytes * 4;
  return (graphBytes + schedulerBytes) / (1024 ** 3);
}

export function selectedModelRows(pfx = "") {
  const byPath = modelsByPath();
  // The form's own word on what is chosen: a pick awaited by "+ Add model" is
  // no model. Reading the field with the config behind it estimated the
  // config's model instead — the editor opened on the default model's 29.8 GB
  // "won't fit" and its projector hint with nothing chosen (live check,
  // 2026-09-27).
  const choice = modelChoiceOf(pfx);
  return { selected: byPath.get(choice.model), selectedMmprojRow: byPath.get(choice.mmproj) };
}

export function estimateRuntimeMemoryGb(pfx = "") {
  const { selected, selectedMmprojRow } = selectedModelRows(pfx);
  if (!selected) return { modelSize: 0, mmprojSize: 0, fileTotalSize: 0, kvSize: 0, batchSize: 0, runtimeSize: 0 };
  const modelSize = Number(selected.sizeGb || 0);
  const mmprojSize = Number(selectedMmprojRow?.sizeGb || 0);
  const fileTotalSize = modelSize + mmprojSize;
  const kvSize = estimateKvCacheGb(selected, pfx);
  const batchSize = estimateBatchBuffersGb(selected, pfx);
  return {
    modelSize,
    mmprojSize,
    fileTotalSize,
    kvSize,
    batchSize,
    runtimeSize: fileTotalSize + kvSize + batchSize,
  };
}

// How the weights divide between the card and RAM.
//
// The estimate above sums the WHOLE model and compares it to VRAM, which is
// only true when every layer is on the GPU. With a partial offload — the thing
// that makes a 70B start on a 32 GB card — it reads "over" for a configuration
// that fits perfectly well, and never says how much lands in RAM.
//
// llama.cpp's own fitting ('auto') decides this at load time from its real
// accounting; this predicts the same shape so the operator can see the split
// before starting, and is labelled an estimate because that is what it is.
export function offloadSplit(pfx = "") {
  const { selected } = selectedModelRows(pfx);
  const est = estimateRuntimeMemoryGb(pfx);
  // blockCount lives in ggufMeta, not on the row — reading it off the row gave
  // 0, which this function treats as "layer count unknown", so the split simply
  // never appeared. A quiet nothing rather than a visible wrong number, which
  // is the harder kind to notice.
  const layers = Number(selected?.ggufMeta?.blockCount || 0);
  const raw = String(($(pfx + "N_GPU_LAYERS")?.value ?? state.config?.N_GPU_LAYERS ?? "").trim() || "auto").toLowerCase();
  const kvOnGpu = !!($(pfx + "KV_OFFLOAD")?.checked ?? true);
  const out = { layers, layersGpu: layers, vramGb: est.runtimeSize, ramGb: 0,
                mode: raw, partial: false, known: layers > 0, perGpu: [], autoLayers: layers };
  if (!selected || !layers) return out;            // no layer count → no claim
  const perLayer = est.fileTotalSize / layers;
  const use = computeSelectedGpus(pfx);
  const splitMode = new SplitMode($(pfx + "SPLIT_MODE")?.value);

  // Where "auto" lands: as many layers as the room of the picked cards holds, after the caches. The room is what each card has
  // FOR THIS CELL, so what the cell already holds, if it runs, counts as free (it is given back before the restart that applies
  // the change). The one place this is worked out: the plan panel's "auto" tile reads it from here — it kept a copy of its own.
  // A tensor split has no fitting (llama.cpp: "llama_params_fit is not implemented for SPLIT_MODE_TENSOR") and "auto" put every
  // layer on the cards — measured, 42.5 GB of the 70B on two cards — so it says "all" and not a partial split it never makes.
  const freeGb = use.reduce((sum, g) => sum + cellFreeMiB(pfx, g), 0) / 1024;
  const forWeights = freeGb - (kvOnGpu ? est.kvSize : 0) - est.batchSize - 0.6;
  out.autoLayers = splitMode.value === "tensor" ? layers
    : (perLayer > 0 ? Math.max(0, Math.min(layers, Math.floor(forWeights / perLayer))) : 0);

  let onGpu;
  if (raw === "0") onGpu = 0;
  else if (raw === "all" || raw === "max") onGpu = layers;
  else if (/^\d+$/.test(raw)) onGpu = Math.min(layers, parseInt(raw, 10));
  else onGpu = out.autoLayers;
  out.layersGpu = onGpu;
  // Anything short of "every layer on the card" is worth saying, INCLUDING the
  // case where nothing fits and the whole model runs from RAM. Requiring at
  // least one layer on the GPU hid exactly that: the card shows a comfortable
  // "0 GB / 0.4 GB free" and the operator is never told the model went to RAM
  // entirely — which is the difference between fast and very slow.
  out.partial = onGpu < layers;
  out.vramGb = onGpu * perLayer + (onGpu > 0 ? (kvOnGpu ? est.kvSize : 0) + est.batchSize : 0);
  out.ramGb = (layers - onGpu) * perLayer + (onGpu > 0 && kvOnGpu ? 0 : est.kvSize);
  // Which card holds what. With two cards llama.cpp splits the GPU-resident
  // layers between them (--split-mode layer) by --tensor-split, defaulting to
  // proportions that follow device memory. One summed VRAM figure hides the
  // question the operator actually has with two cards in the box: does it fit
  // THIS card, and how much still lands in RAM. Proportional to FREE memory,
  // so a card already hosting another cell is not promised room it lacks.
  //
  // Said out loud: under a TENSOR split (-sm row/tensor) whole layers are not
  // handed to a card at all — every weight is cut between them by the same
  // proportions, so the per-card GB here still reads about right, but "layers
  // on this card" would not, and with -sm row the KV lives on --main-gpu
  // alone rather than spread. The bar prints only the GB, never the per-card
  // layer count, which is why this stays honest for all three modes.
  {
    // An explicit TENSOR_SPLIT is the operator's own decision; follow it. Without one, the mode decides: a tensor split cuts
    // equal parts (SplitMode.evenByDefault), the others follow the room each card has.
    const manualSplit = String($(pfx + "TENSOR_SPLIT")?.value || "").trim()
      .split(",").map((x) => Number(x)).filter((x) => Number.isFinite(x) && x > 0);
    const weights = use.map((g, i) => (manualSplit.length === use.length
      ? manualSplit[i]
      : (splitMode.evenByDefault ? 1 : cellFreeMiB(pfx, g) / 1024)));
    const sum = weights.reduce((a, b) => a + b, 0) || 1;
    let left = onGpu;
    const shares = use.map((g, i) => {
      const share = i === use.length - 1 ? left : Math.min(left, Math.round(onGpu * weights[i] / sum));
      left -= share;
      return share;
    });
    // A card's GB is its weights PLUS its share of the caches — the KV of a
    // layer lives on the card that holds the layer. Counting only weights made
    // the per-card segments add up to less than the VRAM total, so the bar
    // stopped short of full and the two views disagreed with each other.
    const extra = Math.max(0, out.vramGb - onGpu * perLayer);
    out.perGpu = use.map((g, i) => ({
      index: Number(g.index),
      name: shortGpuName(g.name),
      layers: shares[i],
      gb: shares[i] * perLayer + (onGpu > 0 ? extra * shares[i] / onGpu : 0),
    }));
  }
  return out;
}

// FREE VRAM on a GPU (accounts for memory already in use by other processes).
// Prefer nvidia-smi's memory.free; fall back to total-used, then total.
export function gpuFreeMiB(row) {
  const free = Number(row.memoryFreeMiB || 0);
  if (free > 0) return free;
  const total = Number(row.memoryTotalMiB || 0);
  const used = Number(row.memoryUsedMiB || 0);
  return Math.max(0, total - used);
}

// What the cell this form edits holds on each card right now, MiB by card index (its slot's per-process GPU memory), and
// nothing while it does not run — a stopped cell's memory is already free. A change is applied by a restart, which gives
// that memory back before the cell asks again; so a cell that holds 41.7 GB of 55.8 is not "over VRAM" with 13.3 GB free
// (2026-10-17: the form of the running 70B said "won't fit" and planned 19 of its 80 layers for the very weights it held).
export function cellHolds(pfx) {
  const slot = _commandCellSlot(pfx);
  const live = !!slot && ["running", "warming"].includes(String(slot.phase || ""));
  const byCard = live
    ? Object.fromEntries(Object.entries(slot.gpuMem || {}).map(([index, mib]) => [String(index), Number(mib) || 0])) : {};
  return { live, byCard, totalGb: Object.values(byCard).reduce((a, mib) => a + mib, 0) / 1024 };
}

// The room a card has for THIS cell at its next start: what the card reports free, plus what the cell holds on it.
export function cellFreeMiB(pfx, gpu) {
  return gpuFreeMiB(gpu) + (cellHolds(pfx).byCard[String(gpu.index)] || 0);
}

// The cards the form's compute target picks (all of them while none is picked), as rows of the machine's report.
export function computeSelectedGpus(pfx) {
  const gpus = computeTargetGpus(pfx);
  const sel = computeSelectedGpuIdx(pfx);
  return (sel && sel.length) ? gpus.filter((g) => sel.includes(Number(g.index))) : gpus;
}

// `back(card)`: MiB to count as free on top of what the card reports — what the edited cell itself holds.
export function _vramFitFrom(gpus, runtimeSizeGb, back = () => 0) {
  const totalMiB = gpus.reduce((sum, g) => sum + Number(g.memoryTotalMiB || 0), 0);
  if (!runtimeSizeGb || !totalMiB) return { kind: "", html: `<b>n/a</b>` };
  // Compare against FREE VRAM, not total — a card may already host another model.
  const freeGb = gpus.reduce((sum, g) => sum + gpuFreeMiB(g) + back(g), 0) / 1024;
  const headroom = freeGb - runtimeSizeGb;
  const kind = headroom < -1 ? "bad" : headroom < 1 ? "warn" : "good";
  const label = headroom < -1 ? t("vramOver") : headroom < 1 ? t("vramNear") : t("vramOk");
  return {
    kind,
    html: `${pill(label, kind)} <b>${formatSizeGb(runtimeSizeGb)}</b> / ${formatSizeGb(freeGb)} free`,
  };
}

export function vramFit(runtimeSizeGb) {
  return _vramFitFrom(state.gpu?.gpus || [], runtimeSizeGb);
}

export function vramFitForPfx(runtimeSizeGb, pfx) {
  const held = cellHolds(pfx).byCard;
  return _vramFitFrom(computeSelectedGpus(pfx), runtimeSizeGb, (g) => held[String(g.index)] || 0);
}

export function ramFit(runtimeSizeGb) {
  const availableGb = Number(state.memory?.availableMiB || 0) / 1024;
  if (!runtimeSizeGb || !availableGb) return { kind: "", html: `<b>n/a</b>` };
  const headroom = availableGb - runtimeSizeGb;
  const kind = headroom < -1 ? "bad" : headroom < 1 ? "warn" : "good";
  const label = headroom < -1 ? t("ramOver") : headroom < 1 ? t("ramNear") : t("ramOk");
  return {
    kind,
    html: `${pill(label, kind)} <b>${formatSizeGb(runtimeSizeGb)}</b> / ${formatSizeGb(availableGb)}`,
  };
}

// ── Compute target (CPU vs GPU) ──────────────────────────────────────────────
// Friendly card view over the raw N_GPU_LAYERS / DEVICE / SPLIT_MODE / THREADS
// fields. Multi-GPU ready: selected GPUs map to a CUDA device list (+ split-mode
// "layer"); CPU sets n-gpu-layers 0 and threads to the host's available cores.
// No new persisted field — the cards just edit existing fields, so the command
// builder, persistence and the remote payload keep working unchanged.
export function computeTargetGpus(pfx) {
  if (pfx === "tr-") return _trClientGpus || [];
  return (topology?.server?.gpus && topology.server.gpus.length) ? topology.server.gpus : (state.gpu?.gpus || []);
}
export function computeTargetCpu(pfx) {
  return pfx === "tr-" ? (_trClientCpu || {}) : (state.cpu || {});
}
export function computeTargetCores(pfx) {
  const c = computeTargetCpu(pfx);
  const avail = Number(c.availableCores || 0);   // affinity-aware: a pinned VM reports its slice
  const phys = Number(c.physicalCores || 0);
  // Respect cpuset/VM pinning, but cap at physical cores — hyperthreads rarely
  // help compute-bound inference. Fall back gracefully on older reports.
  if (avail && phys) return Math.min(avail, phys);
  return avail || phys || Number(c.logicalCores || 0) || Number(c.ncpu || 0) || 1;
}
export function computeTargetRamGb(pfx) {
  if (pfx === "tr-") {
    const ram = (_trClientCpu && _trClientCpu.ram) || {};
    const avail = Number(ram.totalGb || 0) - Number(ram.usedGb || 0);
    return avail > 0 ? avail : Number(ram.totalGb || 0);
  }
  return Number(state.memory?.availableMiB || 0) / 1024;
}
export function computeIsCpu(pfx) {
  const el = $(pfx + "N_GPU_LAYERS");
  const v = el ? el.value : (state.config?.N_GPU_LAYERS ?? "");
  return String(v).trim() === "0";
}
// Selected GPU indexes parsed from the DEVICE field ("CUDA0,CUDA1"). Empty
// DEVICE in GPU mode = all GPUs; CPU mode = none.
export function computeSelectedGpuIdx(pfx) {
  if (computeIsCpu(pfx)) return [];
  const all = computeTargetGpus(pfx).map((g) => Number(g.index));
  const dev = ($(pfx + "DEVICE")?.value || "").trim();
  if (!dev) return all;
  const picked = dev.split(",").map((d) => Number(String(d).replace(/[^0-9]/g, ""))).filter((n) => !Number.isNaN(n));
  return picked.length ? picked : all;
}
export function applyComputeTarget(pfx, sel) {
  const set = (k, v) => { const el = $(pfx + k); if (!el) return; if (el.type === "checkbox") el.checked = (v === "1"); else el.value = v; };
  if (sel.mode === "cpu") {
    set("N_GPU_LAYERS", "0"); set("DEVICE", ""); set("SPLIT_MODE", ""); set("TENSOR_SPLIT", ""); set("MAIN_GPU", "");
    const cores = String(computeTargetCores(pfx));
    set("THREADS", cores); set("THREADS_BATCH", cores);
  } else {
    const all = computeTargetGpus(pfx).map((g) => Number(g.index));
    const idx = (sel.gpuIdx && sel.gpuIdx.length ? sel.gpuIdx : all).slice().sort((a, b) => a - b);
    const isAll = idx.length === all.length;
    // "auto", not 999. llama.cpp's -ngl defaults to auto: it puts as many
    // layers on the card as fit and leaves the rest in RAM, which is exactly
    // what makes a model larger than VRAM start at all. Writing 999 here meant
    // "all layers on the GPU" — every cell this tile touched had the engine's
    // own spill-to-RAM turned off, and an oversized model failed instead of
    // running slowly. An exact number still works for pinning the split by hand.
    set("N_GPU_LAYERS", "auto");
    set("DEVICE", isAll ? "" : idx.map((i) => `CUDA${i}`).join(","));
    set("MAIN_GPU", isAll ? "" : String(idx[0]));
    // Pipeline by default on two cards or more (SplitMode.DEFAULT); a mode the
    // operator already chose survives re-picking a card, and brings its split
    // by the cards' sizes along when it cuts equal parts without one.
    const mode = new SplitMode(new SplitMode($(pfx + "SPLIT_MODE")?.value).forCards(idx.length));
    set("SPLIT_MODE", mode.value);
    set("TENSOR_SPLIT", mode.suggestedSplit(computeTargetGpus(pfx).filter((g) => idx.includes(Number(g.index)))
      .sort((a, b) => Number(a.index) - Number(b.index))));
    set("THREADS", "1"); set("THREADS_BATCH", "1");
  }
  refreshComputeTarget(pfx);
  syncFavoriteMirrors(pfx);
  renderModelInsight(pfx);
  renderCommandPreview(pfx);
}
export function shortGpuName(name) {
  return String(name || "GPU").replace(/NVIDIA\s+GeForce\s+/i, "").replace(/NVIDIA\s+/i, "").trim() || "GPU";
}

// The machine's cards for a title: the card's name on a one-card machine (as it always was), "2 × RTX 3090" for
// twins and "RTX 3090 + RTX 5090" for two kinds — never the first card alone, which named a two-card machine
// after one of them (2026-10-17: the form of a machine with a 3090 and a 5090 said "NVIDIA GeForce RTX 3090").
export function machineGpuLabel(gpus) {
  const named = (gpus || []).filter((g) => g && g.name);
  if (named.length <= 1) return String(named[0]?.name || "");
  const counts = new Map();
  named.forEach((g) => counts.set(shortGpuName(g.name), (counts.get(shortGpuName(g.name)) || 0) + 1));
  return [...counts].map(([name, n]) => (n > 1 ? `${n} × ${name}` : name)).join(" + ");
}

// ── Unified compute target: one CPU/GPU/auto control for EVERY runner ─────────
// The launch device used to have two separate widgets — llama's rich CPU/GPU
// cards (writing N_GPU_LAYERS) and the command tab's auto/GPU/CPU tiles (writing
// ENV). They are one control now, sitting above MODEL_FILE. What each runner can
// target differs, so the unavailable tiles are disabled rather than hidden:
//   llama-server : CPU + GPU  (no start-probe → no auto)
//   vLLM         : GPU only   (it reserves VRAM by utilization)
//   whisper      : GPU only   (whisper_server.py hardcodes device=cuda)
//   moonshine    : CPU only   (its ONNX models have no GPU build)
//   gpuOnly      : GPU only   (the registry says so — runner.py gpu_only: Strata's one CUDA card, GR00T's
//                  CUDA policy, the voice servers; a list of ids here was one more thing to forget)
//   transcribe   : CPU + GPU  (ggml: CUDA/Metal if the build has it, else CPU)
//   custom       : CPU + GPU + auto  (generic managed process / TTS engines)
function _runnerOf(pfx) {
  const explicit = ($(pfx + "RUNNER")?.value || "").trim();
  if (explicit) return explicit;
  return ($(pfx + "CELL_KIND")?.value || "") === "command" ? "custom" : "llama-server";
}
export function runnerDeviceCaps(runner) {
  if (runnerRegistry().find((r) => r.id === runner)?.gpuOnly) return { cpu: false, gpu: true, auto: false };
  switch (runner) {
    case "vllm":      return { cpu: false, gpu: true,  auto: false };
    case "whisper":   return { cpu: false, gpu: true,  auto: false };
    case "moonshine": return { cpu: true,  gpu: false, auto: false };
    // ggml runs on whatever the build carries; CUDA_VISIBLE_DEVICES= (what the
    // CPU tile writes) makes a CUDA build fall back, so the pin is real here.
    case "transcribe": return { cpu: true, gpu: true,  auto: false };
    // Runs on either; the server picks CUDA when it sees a GPU. Stated
    // explicitly rather than left to the default branch, which belongs to
    // llama-server and would take this runner with it if it ever changed.
    case "seamless":  return { cpu: true,  gpu: true,  auto: false };
    case "translate": return { cpu: true,  gpu: true,  auto: false };
    case "custom":    return { cpu: true,  gpu: true,  auto: true  };
    default:          return { cpu: true,  gpu: true,  auto: false };  // llama-server
  }
}
// llama edits N_GPU_LAYERS; the command-path runners pin the device in ENV,
// read through the caps above — so a runner with one device (vLLM, whisper and
// Strata on GPU, moonshine on CPU) reports it whatever its ENV says. The caps
// are the one list of them: this function kept a second, and Strata was in neither.
export function currentComputeMode(pfx) {
  const runner = _runnerOf(pfx);
  const caps = runnerDeviceCaps(runner);
  if (usesLlamaConfig(runner)) return computeIsCpu(pfx) ? "cpu" : "gpu";
  // custom (and any other command runner): read the ENV pin
  const st = _envDeviceState($(pfx + "ENV")?.value || "", $(pfx + "COMMAND")?.value || "");
  return caps[st] ? st : (caps.auto ? "auto" : caps.gpu ? "gpu" : "cpu");
}
function applyComputeMode(pfx, sel) {
  if (usesLlamaConfig(_runnerOf(pfx))) { applyComputeTarget(pfx, sel); return; }
  // command-path: device lives in ENV (TTS_DEVICE / CUDA_VISIBLE_DEVICES)
  const env = $(pfx + "ENV");
  if (env) env.value = _applyDeviceToEnv(env.value, sel.mode);
  const devSel = $(pfx + "CELL_DEVICE");
  if (devSel) devSel.value = sel.mode;
  refreshComputeTarget(pfx);
  renderCommandPreview(pfx);
}
// Keeps the multi-GPU dropdown open across the re-render each toggle triggers.
let _computeGpuDdOpen = false;

// ── Where the weights go when the model is bigger than the card ──────────────
// The layer split was a text field holding "auto", "all" or a number, in a tab,
// which is a fine place to keep a value and a poor place to make a decision:
// the operator had to know the model's layer count, do the division, and get no
// feedback until the cell either started or did not. This is the same three-tile
// shape as the compute target, plus a slider for the one case where a number is
// genuinely the answer — with both totals live, because the question people
// actually ask is "how much lands in RAM", not "how many layers".
//
// It appears only when the model does NOT fit the card: with room to spare the
// split is not a decision worth putting on screen.
// formatSizeGb renders 0 as "n/a" — right for a size nobody measured, wrong
// here, where zero layers on the card is a measured fact and the whole point of
// the line. "n/a VRAM + 28.3 GB RAM" reads as a gap in the estimate rather than
// as "none of it is on the GPU".
// The sentence under the bar. Two cards get named individually — "19.4 GB
// VRAM" across a 5090 and a 3090 is not an answer to "will it fit", since the
// halves are not interchangeable.
function planReadout(split) {
  const args = { n: split.layersGpu, total: split.layers,
                 vram: planGb(split.vramGb), ram: planGb(split.ramGb) };
  if ((split.perGpu || []).length > 1) {
    const cards = split.perGpu.map((g) => `GPU${g.index} ${planGb(g.gb)}`).join(" + ");
    return t("offloadSplitMulti", { n: split.layersGpu, total: split.layers,
                                    cards, ram: planGb(split.ramGb) });
  }
  return t("offloadSplitValue", args);
}

function planGb(value) {
  return value > 0.05 ? formatSizeGb(value) : "0 GB";
}

export function refreshOffloadPlan(pfx) {
  const box = $(pfx + "offloadPlan");
  if (!box) return;
  const runner = _runnerOf(pfx);
  const split = offloadSplit(pfx);
  const est = estimateRuntimeMemoryGb(pfx);
  const fits = split.known ? split.layersGpu >= split.layers : true;
  const raw = String(($(pfx + "N_GPU_LAYERS")?.value ?? "").trim() || "auto").toLowerCase();
  // "all" is a deliberate choice the operator can make even when it will not
  // fit, so the panel has to stay on screen while it is selected — otherwise
  // choosing it makes the control that chose it disappear.
  const forced = raw === "all" || /^\d+$/.test(raw);
  if (!usesLlamaConfig(runner) || computeIsCpu(pfx) || !split.known || (fits && !forced)) {
    box.innerHTML = "";
    return;
  }
  const autoLayers = split.autoLayers;           // where "auto" would land: worked out once, in offloadSplit
  // A number that reaches every layer IS "all on the card", whatever it is spelled: a new cell opens with 999, and the panel
  // lit "manual — choose the split yourself" with the slider at its end for a split nobody had chosen.
  const mode = (raw === "all" || (/^\d+$/.test(raw) && parseInt(raw, 10) >= split.layers)) ? "all"
    : (/^\d+$/.test(raw) ? "manual" : "auto");
  // One cell editor, one set of hooks (the controller's own editor and its
  // cell-edit-* names went with its cells in step 6.9).
  const tHook = "cell-remote-offload";
  // Spelled out rather than `${tHook}-slider`: the testability guard derives
  // only the "-picker" suffix, and a hook it cannot see is a hook the doc does
  // not publish — a suite would then look for a name the page never announces.
  const tSlider = "cell-remote-offload-slider";
  // The RAM of the machine the cell runs on, as its scout reported it. It read
  // the controller's own free RAM for every machine, so a cell that would
  // spill past a small machine's RAM looked fine whenever the controller had
  // room to spare.
  const ramFree = computeTargetRamGb(pfx);
  const ramShort = split.ramGb - ramFree;

  const card = (id, active, icon, title, main, sub, warn) =>
    `<button type="button" class="compute-card${active ? " active" : ""}${warn ? " warn" : ""}"` +
    ` data-plan="${id}" data-t="${tHook}" data-t-id="${id}"` +
    ` title="${escapeHtml([title, main, sub].filter(Boolean).join(" · "))}">` +
    `<span class="compute-card-head"><span class="compute-card-icon" aria-hidden="true">${icon}</span>` +
    `<span class="compute-card-name">${escapeHtml(title)}</span>` +
    `<span class="compute-card-main">${escapeHtml(main)}</span>` +
    `<span class="compute-card-sub">${escapeHtml(sub)}</span>` +
    `${active ? '<span class="compute-card-check" aria-hidden="true">✓</span>' : ""}</span></button>`;

  const cards =
    card("auto", mode === "auto", "🎲", t("planAuto"),
         t("offloadSplitShort", { n: autoLayers, total: split.layers }), t("planAutoSub"), false) +
    card("all", mode === "all", "🎮", t("planAll"),
         `${split.layers}/${split.layers}`, t("planAllSub"), true) +
    card("manual", mode === "manual", "✋", t("planManual"),
         mode === "manual" ? `${split.layersGpu}/${split.layers}` : "—", t("planManualSub"), false);

  // The bar is the answer at a glance: how much of the model sits on the card
  // and how much in RAM, in proportion.
  const total = Math.max(0.001, split.vramGb + split.ramGb);
  const multi = (split.perGpu || []).length > 1;
  // One segment per card, then RAM. With a single card this is the same two-part
  // bar as before; with two it shows which card carries what.
  const bar = `<div class="plan-bar" aria-hidden="true">` +
    (multi
      ? split.perGpu.map((g, i) =>
          `<span class="plan-bar-vram plan-bar-gpu${i % 2}" style="width:${(100 * g.gb / total).toFixed(1)}%"` +
          ` title="GPU${g.index}"></span>`).join("")
      : `<span class="plan-bar-vram" style="width:${(100 * split.vramGb / total).toFixed(1)}%"></span>`) +
    `<span class="plan-bar-ram" style="width:${(100 * split.ramGb / total).toFixed(1)}%"></span></div>`;

  const slider = mode === "manual"
    // min 1, not 0: "0" is this codebase's CPU sentinel (computeIsCpu reads it),
    // so a slider that could reach zero would silently flip the cell to CPU and
    // take its own panel off the screen — which is what it did. No layers on the
    // card is a real choice, and it already has a control: the CPU tile above.
    ? `<input type="range" class="plan-slider" min="1" max="${split.layers}" value="${Math.max(1, split.layersGpu)}"` +
      ` data-t="${tSlider}" aria-label="${escapeHtml(t("planManual"))}">`
    : "";

  box.innerHTML =
    `<div class="compute-label">${t("planLabel")}</div>` +
    `<div class="compute-cards">${cards}</div>${slider}${bar}` +
    `<div class="plan-readout${ramShort > 0 ? " bad" : ""}">${escapeHtml(planReadout(split))
    }${ramShort > 0 ? ` — ${escapeHtml(t("planRamShort", { n: formatSizeGb(ramShort) }))}` : ""}</div>`;

  const write = (value) => {
    const el = $(pfx + "N_GPU_LAYERS");
    if (!el) return;
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    syncFavoriteMirrors(pfx);
    renderModelInsight(pfx);
    renderCommandPreview(pfx);
    refreshOffloadPlan(pfx);
  };
  box.querySelectorAll("[data-plan]").forEach((btn) => btn.addEventListener("click", () => {
    const kind = btn.dataset.plan;
    // Manual starts from where auto would have landed — the useful starting
    // point to nudge from, rather than 0 or the whole model.
    write(kind === "auto" ? "auto" : kind === "all" ? "all" : String(Math.max(1, autoLayers)));
  }));
  const range = box.querySelector(".plan-slider");
  if (range) {
    range.addEventListener("input", () => {
      // Repaint the numbers on every drag step, but do not re-render the whole
      // panel — that would replace the element under the operator's finger.
      const el = $(pfx + "N_GPU_LAYERS");
      if (el) { el.value = range.value; el.dispatchEvent(new Event("input", { bubbles: true })); }
      const s2 = offloadSplit(pfx);
      const tot = Math.max(0.001, s2.vramGb + s2.ramGb);
      const segs = box.querySelectorAll(".plan-bar-vram");
      if (segs.length > 1 && (s2.perGpu || []).length === segs.length) {
        segs.forEach((el, i) => { el.style.width = `${(100 * s2.perGpu[i].gb / tot).toFixed(1)}%`; });
      } else if (segs[0]) {
        segs[0].style.width = `${(100 * s2.vramGb / tot).toFixed(1)}%`;
      }
      box.querySelector(".plan-bar-ram").style.width = `${(100 * s2.ramGb / tot).toFixed(1)}%`;
      const short = s2.ramGb - ramFree;
      const out = box.querySelector(".plan-readout");
      out.classList.toggle("bad", short > 0);
      out.textContent = planReadout(s2)
        + (short > 0 ? ` — ${t("planRamShort", { n: formatSizeGb(short) })}` : "");
    });
    range.addEventListener("change", () => write(range.value));
  }
}

export function refreshComputeTarget(pfx) {
  const box = $(pfx + "computeTarget");
  if (!box) return;
  const runner = _runnerOf(pfx);
  const caps = runnerDeviceCaps(runner);
  const mode = currentComputeMode(pfx);
  const gpus = computeTargetGpus(pfx);
  const isLlama = usesLlamaConfig(runner);
  const sel = new Set(isLlama && !computeIsCpu(pfx) ? computeSelectedGpuIdx(pfx) : []);
  const cores = computeTargetCores(pfx);
  const ramGb = computeTargetRamGb(pfx);
  const na = t("computeUnavailable");
  // One row: icon + NAME + the primary detail (cores/GB, card name, "probe at
  // start") + the secondary note, all inline; the check floats to the far right.
  // The full label goes on the button's title= so hovering reveals whatever the
  // one-line tile had to ellipsise (long specs, long translations).
  // Same repeated-element shape as the runner tabs: one hook, told apart by
  // data-t-id, and the `disabled` attribute left on the tiles this runner
  // cannot use — which is the state worth asserting, since it changes with
  // the runner.
  const tHook = "cell-remote-compute";
  const card = (active, disabled, attrs, icon, title, main, sub) =>
    `<button type="button" class="compute-card${active ? " active" : ""}${disabled ? " disabled" : ""}" ${disabled ? "disabled" : ""} title="${escapeHtml([title, main, sub].filter(Boolean).join(" · "))}" ${attrs}>
      <span class="compute-card-head"><span class="compute-card-icon" aria-hidden="true">${icon}</span><span class="compute-card-name">${escapeHtml(title)}</span>${main ? `<span class="compute-card-main">${escapeHtml(main)}</span>` : ""}${sub ? `<span class="compute-card-sub">${escapeHtml(sub)}</span>` : ""}${active ? '<span class="compute-card-check" aria-hidden="true">✓</span>' : ""}</span>
    </button>`;
  const cpuCard = card(mode === "cpu" && caps.cpu, !caps.cpu, `data-compute="cpu" data-t="${tHook}" data-t-id="cpu"`,
    "🧠", "CPU", `${cores} ${t("computeCores")}${ramGb ? ` · ${ramGb.toFixed(0)} GB` : ""}`,
    caps.cpu ? t("computeCpuSub") : na);
  // GPU: ONE summary tile. A multi-GPU host picks its cards in the sub-picker
  // below (chips, or a checklist dropdown for many), keeping CPU/GPU/auto a clean
  // three-tile row. Off GPU-mode the tile previews "all cards" as the default.
  const multi = isLlama && gpus.length > 1;
  // A runner that runs on ONE card (the registry's oneCard) on a machine with several asks which one: the chips
  // below write the pin into its ENV, and the tile says the card the pin names. Without them the cell took card 0
  // whatever it needed, and a 31 GB server was refused by a 24 GB card with no way to choose the other (2026-10-17).
  const oneCardPick = !isLlama && gpus.length > 1 && !!runnerRegistry().find((r) => r.id === runner)?.oneCard;
  const pinnedCard = oneCardPick ? CardPin.card($(pfx + "ENV")?.value || "") : "";
  const allIdx = gpus.map((g) => Number(g.index));
  const shownSel = mode === "gpu" ? [...sel].sort((a, b) => a - b) : allIdx;
  let gpuCards;
  if (multi) {
    const vramSel = gpus.filter((g) => shownSel.includes(Number(g.index)))
      .reduce((s, g) => s + Number(g.memoryTotalMiB || 0) / 1024, 0);
    const allOn = shownSel.length === gpus.length;
    gpuCards = card(mode === "gpu" && caps.gpu, !caps.gpu, `data-compute="gpu" data-t="${tHook}" data-t-id="gpu"`,
      "🎮", "GPU", `${shownSel.length}/${gpus.length} · ${vramSel.toFixed(1)} GB`,
      allOn ? t("computeGpuAll") : shownSel.map((i) => `GPU${i}`).join(" + "));
  } else if (runner === "vllm" && gpus.length > 1 && VllmPlacement.of(pfx).cards.length) {
    // vLLM has no chips: TENSOR_PARALLEL says how many cards, so the tile says which ones that is — it named card 0 alone.
    const taken = VllmPlacement.of(pfx).cards;
    const gb = taken.reduce((s, g) => s + Number(g.memoryTotalMiB || 0) / 1024, 0);
    gpuCards = card(mode === "gpu" && caps.gpu, !caps.gpu, `data-compute="gpu" data-t="${tHook}" data-t-id="gpu"`,
      "🎮", "GPU", `${taken.length}/${gpus.length} · ${gb.toFixed(1)} GB`,
      caps.gpu ? (taken.length === gpus.length ? t("computeGpuAll") : taken.map((g) => `GPU${g.index}`).join(" + ")) : na);
  } else {
    // A one-card runner's tile shows the card its pin names (card 0 while nothing is pinned, as the server reads it).
    const g0 = (oneCardPick && gpus.find((g) => String(g.index) === pinnedCard)) || gpus[0];
    const vram = Number(g0?.memoryTotalMiB || 0) / 1024;
    gpuCards = card(mode === "gpu" && caps.gpu, !caps.gpu, `data-compute="gpu" data-t="${tHook}" data-t-id="gpu"`,
      "🎮", "GPU", g0 ? shortGpuName(g0.name) : "GPU",
      caps.gpu ? (vram ? `${formatSizeGb(vram)} VRAM` : t("computeGpuSub")) : na);
  }
  const autoCard = card(mode === "auto" && caps.auto, !caps.auto, `data-compute="auto" data-t="${tHook}" data-t-id="auto"`,
    "🎲", t("computeAuto"), t("computeAutoMain"), caps.auto ? t("computeAutoSub") : na);
  // Sub-picker for which cards: chips up to 4, a custom checklist dropdown for 5+.
  // Only while GPU is the active mode. Each toggle edits the CUDA device set.
  let subPicker = "";
  if (multi && mode === "gpu") {
    const allOn = shownSel.length === gpus.length;
    const rows = gpus.map((g) => {
      const i = Number(g.index);
      const vram = Number(g.memoryTotalMiB || 0) / 1024;
      return { i, on: sel.has(i), spec: `${shortGpuName(g.name)}${vram ? ` · ${vram.toFixed(1)} GB` : ""}` };
    });
    if (gpus.length >= 5) {
      const summary = allOn ? t("computeGpuAll") : shownSel.map((i) => `GPU${i}`).join(" + ");
      subPicker = `<details class="compute-gpu-dd"${_computeGpuDdOpen ? " open" : ""}>`
        + `<summary class="compute-gpu-dd-sum">${escapeHtml(summary)}<span class="compute-gpu-dd-caret" aria-hidden="true">▾</span></summary>`
        + `<div class="compute-gpu-dd-panel">`
        + rows.map((r) => `<button type="button" class="compute-gpu-dd-row${r.on ? " on" : ""}" data-gpu="${r.i}"><span class="compute-gpu-box" aria-hidden="true">${r.on ? "✓" : ""}</span><span class="compute-gpu-dd-name">GPU${r.i}</span><span class="compute-gpu-dd-vram">${escapeHtml(r.spec)}</span></button>`).join("")
        + `<div class="compute-gpu-dd-div"></div>`
        + `<button type="button" class="compute-gpu-dd-row${allOn ? " on" : ""}" data-gpu-all="1"><span class="compute-gpu-box" aria-hidden="true">${allOn ? "✓" : ""}</span><span class="compute-gpu-dd-name">${escapeHtml(t("computeGpuAll"))}</span></button>`
        + `</div></details>`;
    } else {
      subPicker = `<div class="compute-gpu-chips">`
        + rows.map((r) => `<button type="button" class="compute-gpu-chip${r.on ? " on" : ""}" data-gpu="${r.i}">${r.on ? "✓ " : ""}GPU${r.i}<span class="compute-gpu-chip-m">${escapeHtml(r.spec)}</span></button>`).join("")
        + `<button type="button" class="compute-gpu-chip${allOn ? " on" : ""}" data-gpu-all="1">${escapeHtml(t("computeGpuAll"))}</button>`
        + `</div>`;
    }
  }
  // One card to pick, not a set: the chips of a one-card runner, each writing its card as the pin.
  if (oneCardPick && mode === "gpu") {
    subPicker = `<div class="compute-gpu-chips">`
      + gpus.map((g) => {
        const i = Number(g.index);
        const vram = Number(g.memoryTotalMiB || 0) / 1024;
        const on = String(i) === pinnedCard;
        return `<button type="button" class="compute-gpu-chip${on ? " on" : ""}" data-pin-card="${i}" data-t="cell-remote-card" data-t-id="${i}">`
          + `${on ? "✓ " : ""}GPU${i}<span class="compute-gpu-chip-m">${escapeHtml(`${shortGpuName(g.name)}${vram ? ` · ${vram.toFixed(1)} GB` : ""}`)}</span></button>`;
      }).join("")
      + `</div>`;
  }
  // How the picked cards divide the model — shown only once TWO or more are
  // actually selected. With one card there is nothing to divide and the flag
  // changes nothing, and a control that changes nothing is worse than none:
  // the operator reads it as a setting that did not take effect.
  const splitRow = (multi && mode === "gpu" && shownSel.length > 1)
    ? new SplitMode($(pfx + "SPLIT_MODE")?.value).html("cell-remote-split")
    : "";
  box.innerHTML = `<div class="compute-label">${t("computeTarget")}</div><div class="compute-cards">${cpuCard}${gpuCards}${autoCard}</div>${subPicker}${splitRow}`;
  refreshOffloadPlan(pfx);
  box.querySelectorAll(".compute-card:not(.disabled)").forEach((btn) => btn.addEventListener("click", () => {
    const kind = btn.dataset.compute;
    if (kind === "gpu" && mode === "gpu") return;   // already GPU — the sub-picker owns the card choice
    applyComputeMode(pfx, { mode: kind });          // GPU (from cpu/auto) defaults to all cards
  }));
  // Sub-picker toggles: flip one card in/out of the CUDA device set (never empty).
  box.querySelectorAll("[data-gpu]").forEach((btn) => btn.addEventListener("click", (e) => {
    e.preventDefault();
    const gi = Number(btn.dataset.gpu);
    const cur = new Set(computeIsCpu(pfx) ? [] : computeSelectedGpuIdx(pfx));
    if (cur.has(gi)) cur.delete(gi); else cur.add(gi);
    if (!cur.size) cur.add(gi);
    _computeGpuDdOpen = true;
    applyComputeMode(pfx, { mode: "gpu", gpuIdx: [...cur] });
  }));
  box.querySelectorAll("[data-gpu-all]").forEach((btn) => btn.addEventListener("click", (e) => {
    e.preventDefault();
    _computeGpuDdOpen = true;
    applyComputeMode(pfx, { mode: "gpu" });          // empty DEVICE = every card
  }));
  box.querySelectorAll("[data-pin-card]").forEach((btn) => btn.addEventListener("click", (e) => {
    e.preventDefault();
    const env = $(pfx + "ENV");
    if (env) env.value = CardPin.write(env.value, btn.dataset.pinCard);
    refreshComputeTarget(pfx);                       // the tile, the chips and the aside follow the pin
    renderCommandPreview(pfx);
  }));
  box.querySelectorAll("[data-split]").forEach((btn) => btn.addEventListener("click", (e) => {
    e.preventDefault();
    const el = $(pfx + "SPLIT_MODE");
    const before = new SplitMode(el?.value);
    const next = new SplitMode(btn.dataset.split);
    if (el) el.value = next.value;
    // The split by the cards' sizes follows the mode as long as it is the one written for it: an equal-parts mode gets it, the
    // mode after it takes it back. A TENSOR_SPLIT the operator typed is theirs and stays whatever the tile says.
    const cards = computeSelectedGpus(pfx).slice().sort((a, b) => Number(a.index) - Number(b.index));
    const split = $(pfx + "TENSOR_SPLIT");
    if (split && ["", before.suggestedSplit(cards)].includes(String(split.value || "").trim())) {
      split.value = next.suggestedSplit(cards);
    }
    refreshComputeTarget(pfx);
    syncFavoriteMirrors(pfx);
    renderCommandPreview(pfx);
  }));
  const dd = box.querySelector(".compute-gpu-dd");
  if (dd) dd.addEventListener("toggle", () => { _computeGpuDdOpen = dd.open; });
  // The aside's host picture depends on the same inputs (host, device, runner).
  refreshAsidePanels(pfx);
}
// VRAM/RAM headroom for the form's memory estimate, honoring the compute target.
export function ramFitForPfx(runtimeSizeGb, pfx) {
  const availableGb = computeTargetRamGb(pfx);
  if (!runtimeSizeGb || !availableGb) return { kind: "", html: `<b>n/a</b>` };
  const headroom = availableGb - runtimeSizeGb;
  const kind = headroom < -1 ? "bad" : headroom < 1 ? "warn" : "good";
  const label = headroom < -1 ? t("ramOver") : headroom < 1 ? t("ramNear") : t("ramOk");
  return { kind, html: `${pill(label, kind)} <b>${formatSizeGb(runtimeSizeGb)}</b> / ${formatSizeGb(availableGb)}` };
}

// What each runner puts on the shared estimate bar. llama sums its own files +
// KV + batch; the others cannot use that math, so each contributes the number
// that actually predicts ITS failure:
//   vLLM      reserves GPU_MEMORY_UTILIZATION × the WHOLE card at startup no
//             matter what the model weighs — that reservation is what starves
//             neighbouring cells, so the reservation is what we plot.
//   whisper   a fixed model size straight off the picker.
//   moonshine  fixed ~250 MB, and CPU-only, so it lands on the RAM pool.
//   transcribe the picked GGUF's own size — no KV growth to add, an ASR pass is
//              one bounded utterance, so the file IS the footprint.
//   custom    an opaque process — nothing to estimate, the bar shows use only.
// A runner with a VRAM plan in the registry is drawn from the plan instead:
// Strata's takes the free VRAM (FreeVramStart, below), GR00T's is a fixed figure
// the server measured (runner.py vram_plan).
export function computeFitRuntimeGb(pfx = "") {
  const runner = _runnerOf(pfx);
  const fixedGb = runnerFixedVramGb(runner);
  if (fixedGb > 0) return fixedGb;
  if (usesLlamaConfig(runner)) return estimateRuntimeMemoryGb(pfx).runtimeSize;
  if (runner === "vllm") return VllmPlacement.of(pfx).totalGb;
  if (runner === "whisper") return whisperModelGb[($(pfx + "WHISPER_MODEL")?.value || "large-v3").trim()] || 0;
  if (runner === "moonshine") return moonshineModelGb;
  if (runner === "transcribe") return Number(selectedModelRows(pfx).selected?.sizeGb || 0);
  return 0;
}
// The card a one-card cell (Strata, GR00T, the voice servers: the registry's `oneCard`) is pinned to, in the cell's
// ENV: its last CUDA_VISIBLE_DEVICES, numbered as the board and nvidia-smi number the cards (the controller starts
// every engine with CUDA_DEVICE_ORDER=PCI_BUS_ID). The server reads the pin the same way (runner.py
// Runner.pinned_card), and one table of cases holds the two copies together (scripts/test_js_memory.py). The ENV box
// is hidden for these runners, so the pin is written by the card chips of the compute target.
export class CardPin {
  /** The card's index as text: the ENV's last CUDA_VISIBLE_DEVICES, else "0" (where an unpinned start lands);
   *  "" when the pin names no single card (a list, nothing, a UUID) — the server reserves nothing then. */
  static card(env) {
    const pins = [];
    for (const raw of String(env || "").split(/[\n,]/)) {
      const at = raw.indexOf("=");
      if (at > 0 && raw.slice(0, at).trim() === "CUDA_VISIBLE_DEVICES") pins.push(raw.slice(at + 1).trim());
    }
    const device = pins.length ? pins[pins.length - 1].replace(/^"+|"+$/g, "") : "0";
    return /^\d+$/.test(device) ? device : "";
  }

  /** The ENV with the pin set to card `index`: every earlier CUDA_VISIBLE_DEVICES row goes (the pin is one card, and
   *  the last row wins on the server), the cell's other rows stay as they were. */
  static write(env, index) {
    // The ENV is read by newline or comma (Runner.env_pairs): a pin written as a list ("0,1") is the pin "0" and a row
    // "1" with no "=", which the server skips — and so does this: a row that sets nothing is not kept.
    const rows = String(env || "").split(/[\n,]/).map((row) => row.trim()).filter(Boolean)
      .filter((row) => row.includes("=") || row.startsWith("#"))
      .filter((row) => !/^CUDA_VISIBLE_DEVICES\s*=/.test(row));
    rows.push(`CUDA_VISIBLE_DEVICES=${Number(index)}`);
    return rows.join("\n");
  }
}

// vLLM on a machine with several cards: which cards it takes and what it asks of each. The server's rule (runner.py
// vram_reservation) is util × the card's memory on the ONE card a single-card start lands on (the ENV's pin, else card 0)
// and nothing for a tensor-parallel start ("vLLM places itself"); the form drew util × EVERY card of the machine for both. So
// a 25.7 GB checkpoint on the default TENSOR_PARALLEL of 1 showed a comfortable "50.3 GB of 55.8" for a start whose weights
// do not fit one 24 GB card at all (2026-10-17: the Qwen3-Omni AWQ the owner asked to see on two cards). Here the cards are
// the first TENSOR_PARALLEL of them (vLLM numbers the visible cards from 0), each asked util × its memory, and the weights —
// when the picker names a checkpoint — are cut evenly over them and held against what a card may give.
export class VllmPlacement {
  /** What a card keeps for the activations and the CUDA graphs, GB: the weights must leave this much of the reservation. */
  static MARGIN_GB = 1;

  static of(pfx) {
    const raw = String($(pfx + "TENSOR_PARALLEL")?.value || "").trim();
    const tp = /^\d+$/.test(raw) && Number(raw) > 1 ? Number(raw) : 1;
    const util = Number($(pfx + "GPU_MEMORY_UTILIZATION")?.value) || 0.9;
    const gpus = computeTargetGpus(pfx).slice().sort((a, b) => Number(a.index) - Number(b.index));
    const pin = CardPin.card($(pfx + "ENV")?.value || "");
    const cards = tp > 1 ? gpus.slice(0, tp) : gpus.filter((g) => String(g.index) === pin);
    return new VllmPlacement(tp, util, cards, gpus.length, Number(selectedModelRows(pfx).selected?.sizeGb || 0));
  }

  constructor(tp, util, cards, machineCards, weightsGb) {
    this.tp = tp;
    this.util = util;
    this.cards = cards;
    this.machineCards = machineCards;
    this.weightsGb = weightsGb;
  }

  /** What vLLM asks of each card it takes, GB. A single card is asked util × its memory. Tensor-parallel workers size ONE KV
   *  cache, the smallest any of them can hold, so every card takes what the smallest asks of it (measured on a 24.6 and a
   *  32.6 GB card at 0.9: 22.8 and 23.2 GB held — not 22.1 and 29.3). */
  get perCardGb() {
    const totals = this.cards.map((g) => Number(g.memoryTotalMiB || 0) / 1024);
    const basis = this.tp > 1 && totals.length ? Math.min(...totals) : null;
    return totals.map((gb) => this.util * (basis ?? gb));
  }
  get totalGb() { return this.perCardGb.reduce((sum, gb) => sum + gb, 0); }
  get indexes() { return this.cards.map((g) => Number(g.index)); }

  /** Whether the weights, cut evenly over TENSOR_PARALLEL cards, leave less than the margin on any card the start takes. Not
   *  known — false — while no checkpoint is named (a hand-typed repo id has no size here) or no card is. */
  get weightsOver() {
    if (!(this.weightsGb > 0) || !this.cards.length) return false;
    const each = this.weightsGb / this.tp;
    return this.perCardGb.some((budget) => each > budget - VllmPlacement.MARGIN_GB);
  }

  /** The line under the estimate bar, when there is something to say. */
  note() {
    if (!this.weightsOver) return "";
    return t("vllmWeightsOver", { weights: formatSizeGb(this.weightsGb), budget: formatSizeGb(Math.min(...this.perCardGb)) });
  }
}

// A start that takes its card's free VRAM (runner.py vram_plan: Strata sizes
// its expert cache to what is free). Its card is the one runner.py
// vram_reservation names, read off the cell's ENV the same way; its cost is
// what is free there less the reserve it leaves to others, and it needs its
// floor plus that reserve free. The scout refuses it below that, exactly
// (starts.py: free >= reserved), so the bar's 1 GB grace for estimates is not
// given. A class, not a function: the card, the reserve and the floor are read
// once and answer four questions.
export class FreeVramStart {
  /** The card's index as text — CardPin's rule, which is the server's. */
  static device(env) { return CardPin.card(env); }

  /** The start, or null where the server reserves nothing: no such card, or a
   *  reserve that is not a number of MiB (its Apply is refused, by name). */
  static of(plan, { env = "", reserve = "", gpus = [] } = {}) {
    const device = FreeVramStart.device(env);
    const card = device ? (gpus || []).find((g) => String(g.index) === device) : null;
    const raw = String(reserve ?? "").trim();
    if (!card || (raw && !/^\d+$/.test(raw))) return null;
    return new FreeVramStart(plan, card, raw ? Number(raw) : 0);
  }

  constructor(plan, card, reserveMiB) {
    this.card = card;
    this.floorMiB = Math.max(0, Number(plan?.floorMiB) || 0);
    this.reserveMiB = reserveMiB;
    this.freeMiB = gpuFreeMiB(card);
  }

  get needMiB() { return this.floorMiB + this.reserveMiB; }
  get fits() { return this.freeMiB >= this.needMiB; }
  /** What the bar plans for it: what it will take, or — when it will not
   *  start — what it needs free. */
  get addGb() { return (this.fits ? this.freeMiB - this.reserveMiB : this.needMiB) / 1024; }
  /** How the bar draws it: on its card alone, overflowing exactly, saying how. */
  bar() {
    return { hard: true, cards: [Number(this.card.index)],
             vramNote: t("vramTakesFree", { gb: formatSizeGb(this.needMiB / 1024) }) };
  }
}

// Who draws the estimate bar, decided here once. llama's figure is
// renderModelInsight's (it has the per-file breakdown) and comes in as
// llamaGb; every other runner's comes from its VRAM plan or from
// computeFitRuntimeGb. renderModelInsight drew its llama sum for every runner
// with a model chosen, and a Strata cell read "37.2 GB, won't fit" on the card
// it runs on (live check, 2026-10-13). A llama cell with no model chosen has
// nothing to estimate, and the bar says so — left alone, it kept the last
// model's numbers.
export function refreshAsidePanels(pfx = "", llamaGb = null) {
  const runner = _runnerOf(pfx);
  if (usesLlamaConfig(runner)) {
    if (!selectedModelRows(pfx).selected) renderAsideVramBar(pfx, 0);
    else if (llamaGb !== null) renderAsideVramBar(pfx, llamaGb);
    return;
  }
  if (runner === "vllm") {
    // The cards it takes and what it asks of each; its start refuses at the first GB short, like the scout's exact rule.
    const place = VllmPlacement.of(pfx);
    renderAsideVramBar(pfx, place.totalGb, true, { hard: true, cards: place.indexes, vramNote: place.note() });
    return;
  }
  const row = runnerRegistry().find((r) => r.id === runner);
  const plan = row?.vramPlan;
  // A runner that keeps its weights in the machine's memory (the registry's `keepsRam`) has a plan of RAM too: the controller's
  // answer for this config, asked once and drawn when it is in (ram-plan.js).
  const ramPlan = row?.keepsRam ? RamPlanAsk.of(pfx).planFor(readConfigForm(pfx), () => refreshAsidePanels(pfx)) : null;
  // The bar's options, with the plan only where there is one: a runner that promises nothing is drawn exactly as before.
  const withPlan = (opts) => (ramPlan ? { ...opts, ramPlan } : opts);
  const start = plan?.takesFree
    ? FreeVramStart.of(plan, { env: $(pfx + "ENV")?.value, reserve: $(pfx + plan.reserveField)?.value,
                               gpus: computeTargetGpus(pfx) })
    : null;
  if (start) { renderAsideVramBar(pfx, start.addGb, true, withPlan(start.bar())); return; }
  // A fixed figure on a one-card runner (GR00T, the voice servers) lands on the card its pin names and the scout
  // refuses it at the first MiB short (starts.py: free >= reserved) — so the bar draws it on that card alone, exactly.
  const card = row?.oneCard ? computeTargetGpus(pfx).find((g) => String(g.index) === CardPin.card($(pfx + "ENV")?.value || "")) : null;
  if (card) renderAsideVramBar(pfx, computeFitRuntimeGb(pfx), true, withPlan({ hard: true, cards: [Number(card.index)] }));
  else if (ramPlan) renderAsideVramBar(pfx, computeFitRuntimeGb(pfx), true, { ramPlan });
  else renderAsideVramBar(pfx, computeFitRuntimeGb(pfx), true);
}

