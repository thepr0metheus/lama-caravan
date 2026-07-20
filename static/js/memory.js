// VRAM/RAM estimation for the launch form (KV cache, buffers, compute target).
import { renderCommandPreview } from "./command-preview.js";
import { moonshineModelGb, whisperModelGb } from "./constants.js";
import { syncFavoriteMirrors } from "./favorites.js";
// Device-in-ENV helpers for command-path runners. Imported for use inside
// functions only (llama-edit.js also imports this module) — the runtime cycle
// is safe because nothing here runs at module load.
import { _applyDeviceToEnv, _envDeviceState } from "./llama-edit.js";
import { modelsByPath, renderAsideVramBar, renderModelInsight } from "./form.js";
import { t } from "./i18n.js";
import { _trClientCpu, _trClientGpus } from "./remote-cells.js";
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
  const keyWidth = keyLength || fallbackKvWidth;
  const valueWidth = valueLength || keyWidth;
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
  const selected = byPath.get($(pfx + "MODEL_FILE")?.value || state.config.MODEL_FILE);
  const selectedMmproj = $(pfx + "MMPROJ_FILE")?.value || state.config.MMPROJ_FILE;
  return { selected, selectedMmprojRow: byPath.get(selectedMmproj) };
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

// FREE VRAM on a GPU (accounts for memory already in use by other processes).
// Prefer nvidia-smi's memory.free; fall back to total-used, then total.
export function gpuFreeMiB(row) {
  const free = Number(row.memoryFreeMiB || 0);
  if (free > 0) return free;
  const total = Number(row.memoryTotalMiB || 0);
  const used = Number(row.memoryUsedMiB || 0);
  return Math.max(0, total - used);
}

export function _vramFitFrom(gpus, runtimeSizeGb) {
  const totalMiB = gpus.reduce((sum, g) => sum + Number(g.memoryTotalMiB || 0), 0);
  if (!runtimeSizeGb || !totalMiB) return { kind: "", html: `<b>n/a</b>` };
  // Compare against FREE VRAM, not total — a card may already host another model.
  const freeGb = gpus.reduce((sum, g) => sum + gpuFreeMiB(g), 0) / 1024;
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
  const all = computeTargetGpus(pfx);
  const sel = computeSelectedGpuIdx(pfx);
  const gpus = (sel && sel.length) ? all.filter((g) => sel.includes(Number(g.index))) : all;
  return _vramFitFrom(gpus, runtimeSizeGb);
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
    set("N_GPU_LAYERS", "999");
    set("DEVICE", isAll ? "" : idx.map((i) => `CUDA${i}`).join(","));
    set("MAIN_GPU", isAll ? "" : String(idx[0]));
    set("SPLIT_MODE", idx.length > 1 ? "layer" : "");
    set("TENSOR_SPLIT", "");
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

// ── Unified compute target: one CPU/GPU/auto control for EVERY runner ─────────
// The launch device used to have two separate widgets — llama's rich CPU/GPU
// cards (writing N_GPU_LAYERS) and the command tab's auto/GPU/CPU tiles (writing
// ENV). They are one control now, sitting above MODEL_FILE. What each runner can
// target differs, so the unavailable tiles are disabled rather than hidden:
//   llama-server : CPU + GPU  (no start-probe → no auto)
//   vLLM         : GPU only   (it reserves VRAM by utilization)
//   whisper      : GPU only   (whisper_server.py hardcodes device=cuda)
//   moonshine    : CPU only   (its ONNX models have no GPU build)
//   custom       : CPU + GPU + auto  (generic managed process / TTS engines)
function _runnerOf(pfx) {
  const explicit = ($(pfx + "RUNNER")?.value || "").trim();
  if (explicit) return explicit;
  return ($(pfx + "CELL_KIND")?.value || "") === "command" ? "custom" : "llama-server";
}
export function runnerDeviceCaps(runner) {
  switch (runner) {
    case "vllm":      return { cpu: false, gpu: true,  auto: false };
    case "whisper":   return { cpu: false, gpu: true,  auto: false };
    case "moonshine": return { cpu: true,  gpu: false, auto: false };
    case "custom":    return { cpu: true,  gpu: true,  auto: true  };
    default:          return { cpu: true,  gpu: true,  auto: false };  // llama-server
  }
}
// llama edits N_GPU_LAYERS; the command-path runners pin the device in ENV. A
// forced runner (vllm/whisper=gpu, moonshine=cpu) reports that regardless.
export function currentComputeMode(pfx) {
  const runner = _runnerOf(pfx);
  const caps = runnerDeviceCaps(runner);
  if (runner === "moonshine") return "cpu";
  if (runner === "vllm" || runner === "whisper") return "gpu";
  if (runner === "llama-server") return computeIsCpu(pfx) ? "cpu" : "gpu";
  // custom (and any other command runner): read the ENV pin
  const st = _envDeviceState($(pfx + "ENV")?.value || "", $(pfx + "COMMAND")?.value || "");
  return caps[st] ? st : (caps.auto ? "auto" : caps.gpu ? "gpu" : "cpu");
}
function applyComputeMode(pfx, sel) {
  if (_runnerOf(pfx) === "llama-server") { applyComputeTarget(pfx, sel); return; }
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
export function refreshComputeTarget(pfx) {
  const box = $(pfx + "computeTarget");
  if (!box) return;
  const runner = _runnerOf(pfx);
  const caps = runnerDeviceCaps(runner);
  const mode = currentComputeMode(pfx);
  const gpus = computeTargetGpus(pfx);
  const isLlama = runner === "llama-server";
  const sel = new Set(isLlama && !computeIsCpu(pfx) ? computeSelectedGpuIdx(pfx) : []);
  const cores = computeTargetCores(pfx);
  const ramGb = computeTargetRamGb(pfx);
  const na = t("computeUnavailable");
  // One row: icon + NAME + the primary detail (cores/GB, card name, "probe at
  // start") + the secondary note, all inline; the check floats to the far right.
  // The full label goes on the button's title= so hovering reveals whatever the
  // one-line tile had to ellipsise (long specs, long translations).
  const card = (active, disabled, attrs, icon, title, main, sub) =>
    `<button type="button" class="compute-card${active ? " active" : ""}${disabled ? " disabled" : ""}" ${disabled ? "disabled" : ""} title="${escapeHtml([title, main, sub].filter(Boolean).join(" · "))}" ${attrs}>
      <span class="compute-card-head"><span class="compute-card-icon" aria-hidden="true">${icon}</span><span class="compute-card-name">${escapeHtml(title)}</span>${main ? `<span class="compute-card-main">${escapeHtml(main)}</span>` : ""}${sub ? `<span class="compute-card-sub">${escapeHtml(sub)}</span>` : ""}${active ? '<span class="compute-card-check" aria-hidden="true">✓</span>' : ""}</span>
    </button>`;
  const cpuCard = card(mode === "cpu" && caps.cpu, !caps.cpu, `data-compute="cpu"`,
    "🧠", "CPU", `${cores} ${t("computeCores")}${ramGb ? ` · ${ramGb.toFixed(0)} GB` : ""}`,
    caps.cpu ? t("computeCpuSub") : na);
  // GPU: ONE summary tile. A multi-GPU host picks its cards in the sub-picker
  // below (chips, or a checklist dropdown for many), keeping CPU/GPU/auto a clean
  // three-tile row. Off GPU-mode the tile previews "all cards" as the default.
  const multi = isLlama && gpus.length > 1;
  const allIdx = gpus.map((g) => Number(g.index));
  const shownSel = mode === "gpu" ? [...sel].sort((a, b) => a - b) : allIdx;
  let gpuCards;
  if (multi) {
    const vramSel = gpus.filter((g) => shownSel.includes(Number(g.index)))
      .reduce((s, g) => s + Number(g.memoryTotalMiB || 0) / 1024, 0);
    const allOn = shownSel.length === gpus.length;
    gpuCards = card(mode === "gpu" && caps.gpu, !caps.gpu, `data-compute="gpu"`,
      "🎮", "GPU", `${shownSel.length}/${gpus.length} · ${vramSel.toFixed(1)} GB`,
      allOn ? t("computeGpuAll") : shownSel.map((i) => `GPU${i}`).join(" + "));
  } else {
    const g0 = gpus[0];
    const vram = Number(g0?.memoryTotalMiB || 0) / 1024;
    gpuCards = card(mode === "gpu" && caps.gpu, !caps.gpu, `data-compute="gpu"`,
      "🎮", "GPU", g0 ? shortGpuName(g0.name) : "GPU",
      caps.gpu ? (vram ? `${formatSizeGb(vram)} VRAM` : t("computeGpuSub")) : na);
  }
  const autoCard = card(mode === "auto" && caps.auto, !caps.auto, `data-compute="auto"`,
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
  box.innerHTML = `<div class="compute-label">${t("computeTarget")}</div><div class="compute-cards">${cpuCard}${gpuCards}${autoCard}</div>${subPicker}`;
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
//   moonshine fixed ~250 MB, and CPU-only, so it lands on the RAM pool.
//   custom    an opaque process — nothing to estimate, the bar shows use only.
export function computeFitRuntimeGb(pfx = "") {
  const runner = _runnerOf(pfx);
  if (runner === "llama-server") return estimateRuntimeMemoryGb(pfx).runtimeSize;
  if (runner === "vllm") {
    const util = Number($(pfx + "GPU_MEMORY_UTILIZATION")?.value) || 0.9;
    return computeTargetGpus(pfx).reduce((s, g) => s + Number(g.memoryTotalMiB || 0) / 1024, 0) * util;
  }
  if (runner === "whisper") return whisperModelGb[($(pfx + "WHISPER_MODEL")?.value || "large-v3").trim()] || 0;
  if (runner === "moonshine") return moonshineModelGb;
  return 0;
}
// llama keeps driving the estimate bar from renderModelInsight (it has the
// richer per-file breakdown); every other runner gets it from here, so the bar
// looks and reads the same for all of them.
export function refreshAsidePanels(pfx = "") {
  if (_runnerOf(pfx) !== "llama-server") renderAsideVramBar(pfx, computeFitRuntimeGb(pfx), true);
}

