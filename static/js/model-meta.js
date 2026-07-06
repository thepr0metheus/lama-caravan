// Model name parsing, bench/AA-score caches, pricing and daily stats fetches.
import { renderTopologyCloudProviders } from "./cloud.js";
import { renderModelSelects } from "./form.js";
import { t } from "./i18n.js";
import { topology, ui } from "./state.js";
import { _topologyRenderPending, markTopologyRenderPending, renderTopology, topologyInteractionActive } from "./topology-render.js";
import { $, api } from "./utils.js";

export let proxyDailyStats = {};  // route label -> { total, failed }
export let modelPricing = {};    // model name -> { inputPer1M, outputPer1M, provider }
export let aaScores = {};        // model name -> Artificial Analysis Intelligence Index (best-effort)
export const serverBenchCache = new Map(); // modelLabel → bench data | null
export const _serverBenchPending = new Set();
export function topologyCrownSvg(className = "") {
  return `<svg class="${className}" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 17.5h16l1.1-9.2-5.1 3.4L12 4.5 8 11.7 2.9 8.3z"/><rect x="4" y="18.5" width="16" height="2" rx="0.7"/></svg>`;
}

export function topologyModelIcon() {
  return `<svg class="model-ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/></svg>`;
}

export function topologyProjectorIcon() {
  return `<svg class="model-ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>`;
}

export function parseModelName(path) {
  const file = String(path || "").split("/").pop().replace(/\.gguf$/i, "");
  if (!file) return null;
  const quant = file.match(/\b(NVFP4|MXFP4|IQ\d+(?:_[A-Z0-9]+)*|Q\d+(?:_[A-Z0-9]+)*|BF16|F16|F32)\b/i)?.[0] || "";
  const size = file.match(/\b\d+(?:\.\d+)?x?\d*B\b/i)?.[0] || "";
  // Detect instruction-tuned / chat variant from common suffixes
  const variantMatch = file.match(/[_-](it|instruct|chat|instruction)(?:[_-]|$)/i);
  const variant = variantMatch ? variantMatch[1].toLowerCase() : "";
  let label = file;
  if (quant) label = label.split(quant)[0];
  label = label.replace(/[-_\s]+$/, "").replace(/_/g, " ").trim() || file;
  return { file, label, quant, size, variant };
}

export function _modelBenchKey(modelPath) {
  const parsed = parseModelName(modelPath);
  if (!parsed?.file) return null;
  let key = parsed.file;
  if (parsed.quant) key = key.split(parsed.quant)[0];
  key = key.replace(/[-_\s]+$/, "").toLowerCase();
  // Drop quant-pack markers that sit between the base name and the quant
  // (unsloth "UD" dynamic quants, mradermacher "i1"/imatrix). Without this,
  // "Qwen3.6-35B-A3B-UD-Q4_K_S" keys as "…-a3b-ud" and fails to match the base
  // model's cached benchmarks, so different quants of the same model would
  // inconsistently show a rating.
  key = key.replace(/[-_](ud|i1|imat|imatrix)$/i, "").replace(/[-_\s]+$/, "");
  return key;
}

export function fetchServerBenchIfNeeded(modelPath) {
  const key = _modelBenchKey(modelPath);
  if (!key) return;
  if (serverBenchCache.has(key) || _serverBenchPending.has(key)) return;
  _serverBenchPending.add(key);
  fetch(`/api/hf/bench-search?q=${encodeURIComponent(key)}`)
    .then(r => r.json())
    .then(data => {
      serverBenchCache.set(key, data.ok ? data : null);
      _serverBenchPending.delete(key);
      if (data.ok) renderTopology();
    })
    .catch(() => { serverBenchCache.set(key, null); _serverBenchPending.delete(key); });
}

export function fetchPickerBenchBatch(items, pfx) {
  items.forEach(item => {
    if (!item.value || item.kind !== "model") return;
    const key = _modelBenchKey(item.value);
    if (!key || key.length < 3) return;
    if (serverBenchCache.has(key) || _serverBenchPending.has(key)) return;
    _serverBenchPending.add(key);
    fetch(`/api/hf/bench-search?q=${encodeURIComponent(key)}`)
      .then(r => r.json())
      .then(data => {
        serverBenchCache.set(key, data.ok ? data : null);
        _serverBenchPending.delete(key);
        if (data.ok) renderModelSelects(pfx);
      })
      .catch(() => { serverBenchCache.set(key, null); _serverBenchPending.delete(key); });
  });
}

export function topologyCtxInfo() {
  const ctx = ui.latestSystemMonitor?.latest?.llamaActivity?.context || {};
  const limit = Number(ctx.limit || 0);
  const tokens = Number(ctx.tokens || 0);
  const pct = ctx.pct ?? (limit ? Math.round((100 * tokens) / limit) : null);
  return { tokens, limit, pct };
}

// Human-readable input modalities for a llama-server. Prefers the authoritative
// /props.modalities reported by the backend; falls back to the mmproj-presence
// heuristic ("vision likely") when the server hasn't reported modalities yet.
export function modalitiesText(llama, tx) {
  const m = llama?.modalities;
  if (m && typeof m === "object") {
    const on = [];
    if (m.vision) on.push("👁 vision");
    if (m.audio) on.push("🎙 audio");
    if (m.video) on.push("🎬 video");
    return on.length ? on.join(" · ") : (tx ? tx("topologyTextOnly") : "text only");
  }
  return llama?.mmproj
    ? (tx ? tx("topologyOn") : "on")
    : (tx ? tx("topologyOff") : "off");
}

export async function fetchProxyDailyStats() {
  try {
    const data = await api("/api/proxy-daily-stats");
    if (data?.routes) {
      proxyDailyStats = data.routes;
      // Slow-moving "today: N" counts — full render is fine, but never while the
      // user is dragging a cable (defer until they finish).
      if (topologyInteractionActive()) markTopologyRenderPending();
      else renderTopology();
    }
  } catch (_) { /* non-critical */ }
}

export function formatPricePer1M(v) {
  if (v === null || v === undefined || isNaN(v)) return "";
  if (v === 0) return "$0";
  const s = v >= 100 ? v.toFixed(0)
          : v >= 10  ? v.toFixed(1)
          : v >= 1   ? v.toFixed(2)
          : v >= 0.1 ? v.toFixed(3)
          :             v.toFixed(4);
  return "$" + s.replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
}

export async function fetchModelPricing() {
  try {
    const data = await api("/api/model-pricing");
    if (data?.pricing && typeof data.pricing === "object") {
      modelPricing = data.pricing;
      ui._lastCloudProvidersKey = "";  // force cloud panel re-render
      if (topology) renderTopologyCloudProviders();
    }
  } catch (_) { /* non-critical */ }
}

// Artificial Analysis Intelligence Index for cloud models shown in the Servers
// panel. Models are resolved in waves: the backend looks them up in its cache and
// scrapes a capped number of misses per call, so we keep pumping the queue until
// every visible model is either scored or confirmed to have no AA page. Each model
// shows a pulsing ★ placeholder until it resolves. Callers list exposed models
// first so they get the limited live-scrape budget before the rest.
export const _aaBad = new Set();      // model ids confirmed to have no AA rating
export let _aaQueue = [];             // model ids awaiting resolution (priority order)
export let _aaPumpActive = false;     // a pump wave is scheduled or in flight
export const _AA_BATCH = 40;          // ids per backend call

export function requestAaScores(modelIds) {
  let added = false;
  for (const id of modelIds) {
    if (!id || id in aaScores || _aaBad.has(id) || _aaQueue.includes(id)) continue;
    _aaQueue.push(id);
    added = true;
  }
  if (added) _scheduleAaPump();
}
export function _scheduleAaPump(delay = 150) {
  if (_aaPumpActive) return;   // a wave is already running; it picks up new queue items
  _aaPumpActive = true;
  setTimeout(_aaPump, delay);
}
export function _aaDrainResolved() {
  _aaQueue = _aaQueue.filter((id) => !(id in aaScores) && !_aaBad.has(id));
}
export async function _aaPump() {
  _aaDrainResolved();
  if (!_aaQueue.length) { _aaPumpActive = false; return; }
  const batch = _aaQueue.slice(0, _AA_BATCH);
  try {
    const res = await api("/api/aa-scores", { method: "POST", body: JSON.stringify({ models: batch }) });
    let changed = false;
    for (const [id, v] of Object.entries(res?.scores || {})) {
      if (aaScores[id] !== v) { aaScores[id] = v; changed = true; }
    }
    for (const id of (res?.misses || [])) {
      if (!_aaBad.has(id)) { _aaBad.add(id); changed = true; }
    }
    if (changed && topology) renderTopology();
  } catch (_) { /* non-critical — leave items queued for a later attempt */ }
  _aaDrainResolved();
  if (_aaQueue.length) { setTimeout(_aaPump, 150); }  // next wave until all resolve
  else { _aaPumpActive = false; }
}
// Badge next to a cloud model: gold score once known, pulsing grey ★ while we're
// still resolving it, nothing once we've confirmed it has no AA page.
export function aaBadgeHtml(model) {
  if (!model) return "";
  const v = aaScores[model];
  if (v != null) return `<span class="router-prov-model-aa" title="Artificial Analysis Intelligence Index — higher = smarter">★ ${v}</span>`;
  if (_aaBad.has(model)) return "";
  return `<span class="router-prov-model-aa is-pending" title="Loading rating…">★</span>`;
}

