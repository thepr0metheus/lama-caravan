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
import { BatchBuffers, CellFields, KvCache } from "./cell-plan.js";
import { CardPin, CardRoom, ComputeFields, FreeVramStart, PlacementPanel, PlacementPlan } from "./placement.js";
import { RamPlanAsk } from "./ram-plan.js";
import { _trClientCpu, _trClientGpus } from "./remote-cells.js";
import { SplitMode } from "./split-mode.js";
import { state, topology } from "./state.js";
import { $, escapeHtml, formatSizeGb, pill } from "./utils.js";

// The rules the machine page's bench shares with this form live with the placement (placement.js) and the formatter with the
// others (utils.js); their old names stay importable from here.
export { CardPin, FreeVramStart } from "./placement.js";
export { formatSizeGb } from "./utils.js";

// The KV cache, the compute buffers and the reading of a cell's fields live in cell-plan.js since 1.3.635 — the machine page's
// bench sizes a stopped cell by the same rule from its stored config. Their old names stay here, read off this form.
export const AUTO_SLOTS = KvCache.AUTO_SLOTS;
export const RECURRENT_BY_INTERVAL = KvCache.RECURRENT_BY_INTERVAL;
export function cacheBytesPerElement(cacheType) { return KvCache.bytesPerElement(cacheType); }
export function kvLayout(meta) { return KvCache.layout(meta); }
export function recurrentLayers(meta, layers) { return KvCache.recurrent(meta, layers); }
export function kvCells(ctx, window, opts) { return KvCache.cells(ctx, window, opts); }

/** The form's fields as the estimate reads them (cell-plan.js CellFields): a box as "1"/"0", an empty field with the
 *  controller's default behind it. */
export function formFields(pfx = "") {
  return new CellFields({
    text: (key) => {
      const el = $(pfx + key);
      if (!el) return "";
      return el.type === "checkbox" ? (el.checked ? "1" : "0") : String(el.value ?? "");
    },
    value: (key) => $(pfx + key)?.value || state.config?.[key] || "",
    checked: (key) => !!$(pfx + key)?.checked,
  });
}

export function estimateKvCacheGb(row, pfx = "") {
  return KvCache.gb(row?.ggufMeta, formFields(pfx));
}

export function estimateBatchBuffersGb(row, pfx = "") {
  return BatchBuffers.gb(row?.ggufMeta, formFields(pfx));
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

// How the weights divide between the cards and RAM — the figures the line above the tabs says and the placement map draws.
//
// The estimate above sums the WHOLE model and compares it to VRAM, which is only true when every layer is on a card.
// With a part in RAM — the thing that makes a 70B start on two cards — it reads "over" for a configuration that fits, and
// never says how much lands in RAM. llama.cpp decides that at load time from its own accounting; PlacementPlan
// (placement.js) predicts the same shape, and this reads it in the form's words. One plan for both: the map and the line
// above the tabs once kept two estimates of the same split, and they drifted.
export function offloadSplit(pfx = "") {
  const { selected } = selectedModelRows(pfx);
  const est = estimateRuntimeMemoryGb(pfx);
  // blockCount lives in ggufMeta, not on the row — reading it off the row gave 0, which this function treats as "layer count
  // unknown", so the split simply never appeared. A quiet nothing rather than a visible wrong number, which is the harder kind
  // to notice.
  const layers = Number(selected?.ggufMeta?.blockCount || 0);
  const raw = String(($(pfx + "N_GPU_LAYERS")?.value ?? state.config?.N_GPU_LAYERS ?? "").trim() || "auto").toLowerCase();
  const out = { layers, layersGpu: layers, vramGb: est.runtimeSize, ramGb: 0,
                mode: raw, partial: false, known: layers > 0, perGpu: [], autoLayers: layers };
  if (!selected || !layers) return out;            // no layer count → no claim
  // The plan the placement map draws, read from the same fields by the same panel: one estimate of one split. The room of
  // each card is what it has FOR THIS CELL — what the cell already holds, if it runs, counts as free.
  const panel = new PlacementPanel({ form: placementForm(pfx), facts: placementFacts(pfx) });
  const plan = panel.plan();
  // No card to place it on: every layer is the CPU's.
  if (!plan.cards.length) {
    return { ...out, layersGpu: 0, vramGb: 0, ramGb: est.fileTotalSize + est.kvSize, partial: true, autoLayers: 0 };
  }
  // An expert override the plan cannot count: no claim, rather than "0 layers on the cards".
  if (!plan.counted) return { ...out, known: false };
  // Where "auto" lands: llama.cpp's fitting, by the margins the cell names — and in a tensor split every layer, since llama.cpp
  // does not fit there ("llama_params_fit is not implemented for SPLIT_MODE_TENSOR"; measured, 42.5 GB of the 70B on two cards).
  out.autoLayers = panel.with(plan, { held: null, fixedLayers: null, parts: [] }).placed().layersOnCards;
  // "0" is the CPU: every layer in RAM. A number or "all" fixes the layers; "auto" is the fitting, unless something holds it.
  const placed = plan.placed();
  out.layersGpu = placed.layersOnCards;
  // Anything short of "every layer on the card" is worth saying, INCLUDING the case where nothing fits and the whole model
  // runs from RAM — which is the difference between fast and very slow.
  out.partial = out.layersGpu < layers;
  out.vramGb = placed.cards.reduce((sum, c) => sum + c.totalGb, 0);
  out.ramGb = placed.ram.totalGb;
  // Which card holds what: a card's GB is its weights PLUS its share of the cache and its part of the buffers.
  out.perGpu = placed.cards.map((c) => ({ index: c.index, name: c.name, layers: c.layers, gb: c.totalGb }));
  return out;
}

/** What the placement map knows of the model and the machine — the facts the map and offloadSplit both read: the files, the
 *  KV cache and the buffers as this module estimates them, the layer and expert counts of the model's header and what its
 *  experts weigh (the bytes of its expert tensors, summed over a split model's parts by models.py), the picked
 *  cards with the room each has for this cell, the machine's RAM and cores, and the split mode. */
export function placementFacts(pfx = "") {
  const { selected } = selectedModelRows(pfx);
  const est = estimateRuntimeMemoryGb(pfx);
  const cpu = computeTargetCpu(pfx);
  const ramTotalGb = pfx === "tr-" ? Number(cpu?.ram?.totalGb || 0) : Number(state.memory?.totalMiB || 0) / 1024;
  const ramFreeGb = computeTargetRamGb(pfx);
  return {
    model: { weightsGb: est.fileTotalSize, kvGb: est.kvSize, batchGb: est.batchSize,
             layers: Number(selected?.ggufMeta?.blockCount || 0), experts: Number(selected?.ggufMeta?.expertCount || 0),
             expertsGb: Number(selected?.ggufMeta?.expertBytes || 0) / (1024 ** 3) },
    cards: computeSelectedGpus(pfx).map((g) => ({ index: Number(g.index), name: shortGpuName(g.name),
                                                  freeGb: cellFreeMiB(pfx, g) / 1024, totalGb: Number(g.memoryTotalMiB || 0) / 1024 })),
    // 0 is a machine that has not reported its RAM: not known, and no shortage is claimed of it.
    ramFreeGb: ramFreeGb > 0 ? ramFreeGb : null, ramTotalGb, cores: computeTargetCores(pfx),
    mode: new SplitMode($(pfx + "SPLIT_MODE")?.value).value === "tensor" ? "tensor" : "layer",
  };
}

/** The cell's fields as the placement map reads and writes them: a box as "1"/"0", an input as its text; a write is announced
 *  as typing would be, and the parts of the form that read the fields are drawn again. */
function placementForm(pfx) {
  return {
    get: (key) => {
      const el = $(pfx + key);
      if (!el) return "";
      return el.type === "checkbox" ? (el.checked ? "1" : "0") : String(el.value ?? "");
    },
    set: (key, value) => {
      const el = $(pfx + key);
      if (!el) return;
      if (el.type === "checkbox") el.checked = value === "1";
      else el.value = value;
      el.dispatchEvent?.(new Event("input", { bubbles: true }));
      el.dispatchEvent?.(new Event("change", { bubbles: true }));
    },
    changed: () => {
      syncFavoriteMirrors(pfx);
      renderModelInsight(pfx);
      renderCommandPreview(pfx);
    },
  };
}

// FREE VRAM on a GPU (accounts for memory already in use by other processes): CardRoom's rule, which the machine page's
// bench reads too; a card that says nothing has nothing to give here.
export function gpuFreeMiB(row) {
  return CardRoom.freeMiB(row) ?? 0;
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
  return ComputeFields.cores(computeTargetCpu(pfx));
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
  return PlacementPlan.devices($(pfx + "DEVICE")?.value, computeTargetGpus(pfx).map((g) => Number(g.index)));
}
export function applyComputeTarget(pfx, sel) {
  const set = (k, v) => { const el = $(pfx + k); if (!el) return; if (el.type === "checkbox") el.checked = (v === "1"); else el.value = v; };
  if (sel.mode === "cpu") {
    for (const [key, value] of Object.entries(ComputeFields.cpu(computeTargetCores(pfx)))) set(key, value);
  } else {
    const all = computeTargetGpus(pfx).map((g) => Number(g.index));
    const idx = (sel.gpuIdx && sel.gpuIdx.length ? sel.gpuIdx : all).slice().sort((a, b) => a - b);
    // Writing 999 here meant "all layers on the GPU": every cell this tile touched had the engine's own spill-to-RAM turned off,
    // and an oversized model failed instead of running slowly. An exact number still works for pinning the split by hand.
    for (const [key, value] of Object.entries(ComputeFields.cards(idx, all))) set(key, value);
    // Pipeline by default on two cards or more (SplitMode.DEFAULT); a mode the
    // operator already chose survives re-picking a card, and brings its split
    // by the cards' sizes along when it cuts equal parts without one.
    const mode = new SplitMode(new SplitMode($(pfx + "SPLIT_MODE")?.value).forCards(idx.length));
    set("SPLIT_MODE", mode.value);
    set("TENSOR_SPLIT", mode.suggestedSplit(computeTargetGpus(pfx).filter((g) => idx.includes(Number(g.index)))
      .sort((a, b) => Number(a.index) - Number(b.index))));
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
//   autoDevice   : CPU + GPU + auto  (the registry says so — runner.py auto_device: a custom command, the voice-clone
//                  TTS cell, which picks the card when it has the room and else the CPU)
function _runnerOf(pfx) {
  const explicit = ($(pfx + "RUNNER")?.value || "").trim();
  if (explicit) return explicit;
  return ($(pfx + "CELL_KIND")?.value || "") === "command" ? "custom" : "llama-server";
}
export function runnerDeviceCaps(runner) {
  const row = runnerRegistry().find((r) => r.id === runner);
  if (row?.gpuOnly) return { cpu: false, gpu: true, auto: false };
  if (row?.autoDevice) return { cpu: true, gpu: true, auto: true };
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
/** Where form `pfx` computes — the compute target's tiles and the new-cell wizard (add-model.js): {mode: "cpu" | "gpu",
 *  gpuIdx}. A llama.cpp form writes its layers, devices and split; any other runner its ENV pin. */
export function applyComputeMode(pfx, sel) {
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
// The placement map of a llama.cpp cell on the cards (placement.js): where the model lives, a handle per card for how much of
// it the model may take, what that leaves in RAM. It replaced the "auto / all on GPU / manual" tiles (2026-10-24): those moved
// one layer count, and the owner asked for the cards and RAM by name — "fill the 5090, all or part of the 3090, something in
// RAM". Nothing for a CPU cell, another runner, or the row split, which this llama.cpp's NVIDIA build cannot start (the split
// tile says so).
export function refreshPlacementMap(pfx) {
  mountPlacementMap(pfx, $(pfx + "placementMap"));
}

/** The placement map of form `pfx` drawn in `box`: the dialog's own, or the cell window's Memory tab (cell-settings.js), each
 *  reading and writing the same fields. False, and the box emptied, for a cell that has none. */
export function mountPlacementMap(pfx, box) {
  if (!box) return false;
  const runner = _runnerOf(pfx);
  if (!usesLlamaConfig(runner) || computeIsCpu(pfx) || new SplitMode($(pfx + "SPLIT_MODE")?.value).value === "row") {
    box.innerHTML = "";
    return false;
  }
  new PlacementPanel({ form: placementForm(pfx), facts: placementFacts(pfx) }).mount(box);
  return true;
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
  refreshPlacementMap(pfx);
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
// Strata's takes the free VRAM (FreeVramStart, placement.js), GR00T's is a fixed figure
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
    const field = (key) => $(pfx + key)?.value;
    const row = VllmPlacement.rowOf(pfx);
    return VllmPlacement.from({ TENSOR_PARALLEL: field("TENSOR_PARALLEL"), GPU_MEMORY_UTILIZATION: field("GPU_MEMORY_UTILIZATION"),
                                ENV: field("ENV"), CPU_OFFLOAD_GB: field("CPU_OFFLOAD_GB"), MAX_MODEL_LEN: field("MAX_MODEL_LEN"), KV_CACHE_DTYPE: field("KV_CACHE_DTYPE") },
                              computeTargetGpus(pfx), Number(row?.sizeGb || 0), row || {});
  }

  /** The library's row of the model this cell serves. `VLLM_MODEL` says which, and on another machine than the controller's `MODEL_FILE` may name anything: a check on the
   *  owner's machine said 36.6 GB of a 2 GB checkpoint, the weight of the first file in the list. Not in the library: none, no figures rather than another model's. */
  static rowOf(pfx) {
    const said = String($(pfx + "VLLM_MODEL")?.value || "").trim().replace(/\/+$/, "");
    if (!said) return selectedModelRows(pfx).selected || null;
    const rows = [...(state.artifacts || []), ...modelsByPath().values()];
    return rows.find((one) => said === one.path || said.endsWith(`/${one.path}`)) || null;
  }

  /** The same out of a cell's config as it is stored, the machine's cards and what its checkpoint weighs, GB: the machine
   *  page's bench reads a stopped vLLM cell so (topology-nodes.js), by one rule with the form. */
  static from(config, gpus, weightsGb = 0, model = {}) {
    const raw = String(config?.TENSOR_PARALLEL ?? "").trim();
    const tp = /^\d+$/.test(raw) && Number(raw) > 1 ? Number(raw) : 1;
    const util = Number(config?.GPU_MEMORY_UTILIZATION) || 0.9;
    const sorted = (gpus || []).slice().sort((a, b) => Number(a.index) - Number(b.index));
    const pin = CardPin.card(config?.ENV || "");
    const cards = tp > 1 ? sorted.slice(0, tp) : sorted.filter((g) => String(g.index) === pin);
    const offload = Number(config?.CPU_OFFLOAD_GB);
    const place = new VllmPlacement(tp, util, cards, sorted.length, Number(weightsGb) || 0, offload > 0 ? offload : 0);
    place.kvGb = VllmPlacement.kvGbOf(config, model, tp);
    return place;
  }

  /** What one request of the longest length takes of KV cache on each card, GB: the length asked, else the one the model was trained with, which is what vLLM takes then. 0 when
   *  the checkpoint does not say what a token weighs. An 8-bit cache takes half of what the model's own 16-bit numbers would. */
  static kvGbOf(config, model, tp) {
    const perToken = Number(model?.kvPerToken) || 0;
    const length = Number(config?.MAX_MODEL_LEN) || Number(model?.contextLength) || 0;
    const shrink = String(config?.KV_CACHE_DTYPE || "").trim().toLowerCase().startsWith("fp8") ? 2 : 1;
    return perToken > 0 && length > 0 ? (perToken * length) / shrink / tp / 2 ** 30 : 0;
  }

  constructor(tp, util, cards, machineCards, weightsGb, offloadGb = 0) {
    this.kvGb = 0;   // what the start's longest request takes on each card (VllmPlacement.kvGbOf)
    this.tp = tp;
    this.util = util;
    this.cards = cards;
    this.machineCards = machineCards;
    this.weightsGb = weightsGb;
    this.offloadGb = offloadGb;   // CPU_OFFLOAD_GB: the weights of each card that stay in RAM and come to it for every pass
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

  /** The weights one card holds at a time, GB: its cut of them less what stays in RAM. */
  get weightsOnCardGb() {
    return Math.max(0, this.weightsGb / this.tp - this.offloadGb);
  }

  /** What of the weights stays in RAM on all the cards it takes, GB. vLLM offloads what there is: no more than the card's cut of the
   *  weights, when their size is known. */
  get ridesGb() {
    const each = this.weightsGb > 0 ? Math.min(this.offloadGb, this.weightsGb / this.tp) : this.offloadGb;
    return each * (this.tp > 1 ? this.tp : 1);
  }

  /** How much of the weights of a card must stay in RAM for the rest to fit its share, GB, in half gigabytes: 0 when they fit, or when
   *  their size or the card is not known. */
  get offloadNeededGb() {
    if (!(this.weightsGb > 0) || !this.cards.length) return 0;
    const over = this.weightsGb / this.tp - (Math.min(...this.perCardGb) - VllmPlacement.MARGIN_GB);
    return over > 0 ? Math.ceil(over * 2) / 2 : 0;
  }

  /** Whether the weights, cut evenly over TENSOR_PARALLEL cards, leave less than the margin on any card the start takes. Not
   *  known — false — while no checkpoint is named (a hand-typed repo id has no size here) or no card is. */
  get weightsOver() {
    if (!(this.weightsGb > 0) || !this.cards.length) return false;
    return this.perCardGb.some((budget) => this.weightsOnCardGb > budget - VllmPlacement.MARGIN_GB);
  }

  /** Whether one request of the longest length does not fit what the weights leave: vLLM refuses to start then, in its own words, after minutes of loading. Not known — false —
   *  while the checkpoint does not say what a token weighs or no card is named. */
  get kvOver() {
    if (!(this.kvGb > 0) || !this.cards.length) return false;
    return this.perCardGb.some((budget) => this.weightsOnCardGb + VllmPlacement.MARGIN_GB + this.kvGb > budget);
  }

  /** The line under the estimate bar, when there is something to say. */
  note() {
    if (this.weightsOver) return t("vllmWeightsOver", { weights: formatSizeGb(this.weightsOnCardGb * this.tp), budget: formatSizeGb(Math.min(...this.perCardGb)) });
    if (this.kvOver) {
      const left = Math.max(0, Math.min(...this.perCardGb) - this.weightsOnCardGb - VllmPlacement.MARGIN_GB);
      return t("vllmKvOver", { kv: formatSizeGb(this.kvGb), left: formatSizeGb(left) });
    }
    return this.ridesGb > 0 ? t("vllmRides", { gb: formatSizeGb(this.ridesGb) }) : "";
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
    // Weights left in RAM are a promise there too, the controller's word as for any runner that keeps weights in RAM.
    const promised = place.ridesGb > 0 ? RamPlanAsk.of(pfx).planFor(readConfigForm(pfx), () => refreshAsidePanels(pfx)) : null;
    renderAsideVramBar(pfx, place.totalGb, true, { hard: true, cards: place.indexes, vramNote: place.note(), ...(promised ? { ramPlan: promised } : {}) });
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

