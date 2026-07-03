// VRAM/RAM estimation for the launch form (KV cache, buffers, compute target).
import { renderCommandPreview } from "./command-preview.js";
import { syncFavoriteMirrors } from "./favorites.js";
import { modelsByPath, renderModelInsight } from "./form.js";
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
export function refreshComputeTarget(pfx) {
  const box = $(pfx + "computeTarget");
  if (!box) return;
  const gpus = computeTargetGpus(pfx);
  const cpuMode = computeIsCpu(pfx);
  const sel = new Set(computeSelectedGpuIdx(pfx));
  const cores = computeTargetCores(pfx);
  const ramGb = computeTargetRamGb(pfx);
  const card = (active, attrs, icon, title, main, sub) =>
    `<button type="button" class="compute-card${active ? " active" : ""}" ${attrs}>
      <span class="compute-card-head"><span class="compute-card-icon" aria-hidden="true">${icon}</span><span>${escapeHtml(title)}</span>${active ? '<span class="compute-card-check" aria-hidden="true">✓</span>' : ""}</span>
      <span class="compute-card-main">${escapeHtml(main)}</span>
      <span class="compute-card-sub">${escapeHtml(sub)}</span>
    </button>`;
  const cpuCard = card(cpuMode, `data-compute="cpu"`, "🧠", "CPU",
    `${cores} ${t("computeCores")}${ramGb ? ` · ${ramGb.toFixed(0)} GB` : ""}`, t("computeCpuSub"));
  const gpuCards = gpus.map((g) => {
    const i = Number(g.index);
    const on = !cpuMode && sel.has(i);
    const vram = Number(g.memoryTotalMiB || 0) / 1024;
    return card(on, `data-compute="gpu" data-gpu="${i}"`, "🎮",
      gpus.length > 1 ? `GPU${i}` : "GPU", shortGpuName(g.name), vram ? `${formatSizeGb(vram)} VRAM` : t("computeGpuSub"));
  }).join("");
  box.innerHTML = `<div class="compute-label">${t("computeTarget")}</div><div class="compute-cards">${cpuCard}${gpuCards}</div>`;
  box.querySelectorAll(".compute-card").forEach((btn) => btn.addEventListener("click", () => {
    if (btn.dataset.compute === "cpu") { applyComputeTarget(pfx, { mode: "cpu" }); return; }
    const gi = Number(btn.dataset.gpu);
    const cur = new Set(computeIsCpu(pfx) ? [] : computeSelectedGpuIdx(pfx));
    if (cur.has(gi)) cur.delete(gi); else cur.add(gi);
    if (!cur.size) cur.add(gi);
    applyComputeTarget(pfx, { mode: "gpu", gpuIdx: [...cur] });
  }));
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

