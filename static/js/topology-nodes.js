// Host-centric nodes view: server cards, telemetry mounts, incidents, models bar.
import { drawTopologyCables } from "./cables.js";
import { nodeTelemetryRowsHtml, renderTopologyIncidents } from "./charts.js";
import { effectiveModelsDir } from "./command-preview.js";
import { badge, mbadge, renderModelSelects } from "./form.js";
import { t } from "./i18n.js";
import {
  _modelBenchKey,
  fetchServerBenchIfNeeded,
  parseModelName,
  serverBenchCache,
  topologyModelIcon,
} from "./model-meta.js";
import { action, formatCtxTokens, formatTps } from "./polling.js";
import {
  _deletingSlots,
  _newReservedCells,
  _pendingRemoteStarts,
  _reservingCells,
  _pendingCellActions,
  _stoppingCells,
  _stoppingHosts,
  nextTopologyCellPort,
  nodeStartingCardHtml,
} from "./remote-cells.js";
import { setState, state, topology } from "./state.js";
import {
  topologyLlamaActivity,
  topologyRuntimePanelHtml,
  topologyServerGroup,
  topologyStatusPill,
} from "./topology-activity.js";
import { topologyLlamaDetailOpen } from "./topology-dnd.js";
import { topologyServerUpstreamHost } from "./topology-proxies.js";
import { refreshTopology, renderTopology } from "./topology-render.js";
import { $, api, copyText, escapeHtml, toast } from "./utils.js";

// ── Host-centric node view (Stage 3a) ────────────────────────────────────────
// Known safetensors format folder names (mirror of _ST_FORMAT_HINTS in
// caravan/admin/models.py) — used to read <Model>/<author>/<FORMAT> paths.
const _ST_FMT = new Set(["NVFP4", "MXFP4", "AWQ", "GPTQ", "AUTOROUND", "FP8",
                         "INT4", "W4A16", "BNB", "BF16", "FP16", "FP32", "ST"]);

// Runner identity chip shown IN the model-name row of every cell card —
// replaces the generic "chip" svg so the engine is readable at a glance.
function runnerChipHtml(runnerId) {
  const meta = { "llama-server": ["🦙", "llama.cpp"], "vllm": ["⚡", "vLLM"],
                 "whisper": ["🎙", "whisper"], "custom": ["🛠", "command"] }[runnerId];
  if (!meta) return "";
  return `<span class="mbadge mbadge-cmd node-runner-chip">${meta[0]} ${meta[1]}</span>`;
}

// Compact age for status lines: 45s / 12m / 5h / 3d.
function _agoShort(epoch) {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - Number(epoch)));
  if (s < 90) return s + "s";
  const m = Math.floor(s / 60);
  if (m < 90) return m + "m";
  const h = Math.floor(m / 60);
  if (h < 36) return h + "h";
  return Math.floor(h / 24) + "d";
}
export const topologyNodesViewOn = true;  // node view is the only mode (flat list retired)
export const _collapsedNodes = new Set(
  (() => { try { return JSON.parse(localStorage.getItem("topologyCollapsedNodes") || "[]"); } catch { return []; } })()
);
export function persistCollapsedNodes() {
  localStorage.setItem("topologyCollapsedNodes", JSON.stringify([..._collapsedNodes]));
}
export function toggleNodeCollapsed(nodeId) {
  if (_collapsedNodes.has(nodeId)) _collapsedNodes.delete(nodeId);
  else _collapsedNodes.add(nodeId);
  persistCollapsedNodes();
  renderTopology();
  requestAnimationFrame(drawTopologyCables); // anchors moved (card ↔ rail)
}

export function applyNodesViewMode() {
  // Node view renders INTO the Llama Servers lane (so the Proxy column + SVG
  // cables stay intact). Here we only reflect the toggle's pressed state.
  const lane = $("topologyLlamaServers");
  if (lane) lane.classList.toggle("nodes-mode", topologyNodesViewOn);
  // Widen the servers lane over the stats column (col3+col4) in node mode.
  const lanes = document.querySelector(".topology-lanes");
  if (lanes) lanes.classList.toggle("nodes-on", topologyNodesViewOn);
}

// Tiny inline SVG sparkline from history rows [t, mem, util, power].
export function nodeSparklineSvg(history, idx, color, max) {
  const pts = (history || []).map((r) => r[idx]).filter((v) => v !== null && v !== undefined);
  if (pts.length < 2) return "";
  const w = 120, h = 28;
  const hi = max || Math.max(...pts, 1);
  const step = w / (pts.length - 1);
  const d = pts.map((v, i) => `${(i * step).toFixed(1)},${(h - (v / hi) * h).toFixed(1)}`).join(" ");
  return `<svg class="node-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${d}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
}

export function nodeGpuRowHtml(node, g) {
  const used = Number(g.memoryUsedMiB || 0), total = Number(g.memoryTotalMiB || 0);
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const usedGb = (used / 1024).toFixed(1), totalGb = (total / 1024).toFixed(1);
  const util = g.utilizationGpuPct ?? "?", temp = g.temperatureC ?? "?", power = g.powerDrawW ?? "?";
  const ports = (g.serverPorts || []).filter((p) => p != null);
  return `
    <div class="node-gpu-row" data-gpu-row="${escapeHtml(`${node.id}:${g.index}`)}">
      <div class="node-gpu-head">
        <strong>GPU ${escapeHtml(String(g.index ?? "?"))}</strong>
        <span class="node-gpu-name">${escapeHtml(g.name || "GPU")}</span>
        <span class="node-gpu-util" data-live-gpuutil>${escapeHtml(String(util))}% · ${escapeHtml(String(temp))}°C · ${escapeHtml(String(power))}W</span>
      </div>
      <div class="node-vram-bar" data-live-gpuvrambar title="${usedGb} / ${totalGb} GB"><span style="width:${pct}%"></span></div>
      <div class="node-gpu-meta">
        <span data-live-gpuvram>VRAM ${usedGb} / ${totalGb} GB</span>
        ${ports.length ? `<span class="node-gpu-ports">▶ ${ports.map((p) => escapeHtml(String(p))).join(", ")}</span>` : `<span class="topology-muted">idle</span>`}
        <span data-live-gpuspark>${nodeSparklineSvg(g.history, 1, "var(--accent,#6ea8fe)", total)}</span>
      </div>
    </div>`;
}

// Small firewall-access badge (icon + tooltip) for a server's port.
export function firewallBadge(fw) {
  if (!fw || !fw.state || fw.state === "unknown") return "";
  const from = (fw.allowedFrom || []).join(", ");
  const map = {
    all:        ["🌐", "Port open to all (Anywhere)"],
    open:       ["🔓", "ufw inactive — port open to all"],
    restricted: ["🔒", `Restricted: ${from} + localhost`],
    blocked:    ["⛔", "Blocked — no firewall rule allows this port"],
  };
  const [icon, tip] = map[fw.state] || ["", ""];
  if (!icon) return "";
  return `<span class="node-fw-badge fw-${escapeHtml(fw.state)}" title="${escapeHtml(tip)}">${icon}</span>`;
}

export function formatUptime(sec) {
  const s = Math.floor(sec || 0);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

// Parse lastError string from llama-server log into a friendly human-readable message.
// Returns { friendly, hint, raw } where friendly is the short translated reason.
export function classifyLlamaError(raw) {
  if (!raw) return null;
  const r = raw.toLowerCase();
  // Corrupted / incomplete file
  if (r.includes("not within the file bounds") || r.includes("corrupted or incomplete") || r.includes("unexpected end of file")) {
    return { friendly: t("llamaErrCorrupted"), hint: t("llamaErrCorruptedHint"), raw };
  }
  // VRAM / memory OOM
  if (r.includes("out of memory") || r.includes("cudaerroromemoryallocation") || r.includes("failed to allocate") || r.includes("not enough memory")) {
    return { friendly: t("llamaErrOOM"), hint: t("llamaErrOOMHint"), raw };
  }
  // Wrong mmproj
  if (r.includes("mismatch between text model") || r.includes("wrong mmproj") || r.includes("mtmd_init_from_file")) {
    return { friendly: t("llamaErrMmproj"), hint: t("llamaErrMmprojHint"), raw };
  }
  // Model file not found
  if (r.includes("no such file") || r.includes("failed to open") || r.includes("failed to load model")) {
    return { friendly: t("llamaErrNotFound"), hint: "", raw };
  }
  // Generic
  return { friendly: t("llamaErrGeneric"), hint: "", raw };
}

// Shared lifecycle breadcrumb bar used by real server cards and the ghost "no server" card.
// lcIdx: 0=reserved, 1=stopped, 2=starting, 3=running; -1 = all future (ghost card)
// lcActiveStep: key for CSS colour class on the active dot (stopped/error/loading/running)
export function serverLifecycleBar(lcIdx, lcActiveStep, uptimeTxt = "", cfgAttrs = "", reservedPort = "", portAttrs = "") {
  const steps = ["reserved", "configured", "starting", "running"];
  const stepLabels = { reserved: t("lcReserved"), configured: t("lcConfigured"), starting: t("lcStarting"), running: t("lcRunning") };
  return `<div class="node-server-lc">${
    steps.map((lbl, i) => {
      const nodeState = i < lcIdx ? "done" : i === lcIdx ? "active" : "future";
      const railCls   = i > 0 ? (i <= lcIdx ? "done" : "future") : "";
      const colorKey  = i === lcIdx ? lcActiveStep : (i < lcIdx ? "done" : "future");
      // Once the "configured" step is behind us, tint it green like the AUTOSTART
      // button: pulsing while the server is still coming up (lcIdx 2 = starting),
      // solid green once running (lcIdx ≥ 3).
      const cfgLive = (i === 1 && nodeState === "done")
        ? (lcIdx < 3 ? " lc-cfg-live lc-cfg-starting" : " lc-cfg-live")
        : "";
      const label = escapeHtml(stepLabels[lbl] || lbl)
        + (i === 2 && uptimeTxt ? `<span class="lc-uptime">${escapeHtml(uptimeTxt)}</span>` : "")
        + (i === 0 && reservedPort ? `<span class="lc-port">:${escapeHtml(String(reservedPort))}</span>` : "");
      // Reserved step carries the :port now — drop its redundant dot (the ghost
      // card, which has no port, keeps the dot for symmetry).
      const inner = `${(i === 0 && reservedPort) ? "" : `<span class="lc-dot"></span>`}<span class="lc-lbl">${label}</span>`;
      const node = (i === 1 && cfgAttrs)
        ? `<button class="lc-node lc-cfg-btn ${nodeState} lc-${colorKey}${cfgLive}" type="button" ${cfgAttrs} title="${escapeHtml(t("nodeConfigure"))}">${inner}</button>`
        // Reserved step becomes the port-reassign button while the cell is
        // stopped: click → free-port picker (occupied ports highlighted).
        : ((i === 0 && portAttrs)
            ? `<button class="lc-node lc-port-btn ${nodeState} lc-${colorKey}" type="button" ${portAttrs} title="${escapeHtml(t("lcPortReassignTitle"))}">${inner}</button>`
            : `<span class="lc-node ${nodeState} lc-${colorKey}${cfgLive}">${inner}</span>`);
      return `${i > 0 ? `<span class="lc-rail ${railCls}"></span>` : ""}${node}`;
    }).join("")
  }</div>`;
}

export function nodeServerCardHtml(node, s) {
  const isStopping = !s.isController && _stoppingHosts.has(node.id);
  const port = s.port;
  const slotHostId = s.isController ? "skynet" : node.id;
  const slotKey = `${slotHostId}:${port}`;
  const cellKey = slotKey;  // alias used in controls + config block
  const isDeleting = _deletingSlots.has(slotKey);
  const pendingCellAction = _pendingCellActions.get(cellKey) || "";
  const isCellStopping = (s.isSlot && _stoppingCells.has(cellKey)) || pendingCellAction === "stop";
  const isNewReserved = _newReservedCells.has(slotKey);
  // If a start was just submitted for this host and the slot still shows "stopped",
  // treat it as "starting" so the user can't accidentally click Start again.
  const hasPendingStart = (!s.isController && _pendingRemoteStarts.has(String(node.id))) || pendingCellAction === "start";
  const rawPhase = isStopping ? "stopping" : (s.phase || (s.status && s.status.phase) || (s.isController ? "running" : "stopped"));
  const phase = (rawPhase === "stopped" && hasPendingStart) ? "starting" : rawPhase;
  const running = phase === "running";
  const isReserved = phase === "reserved";
  const isError = phase === "error";
  const isStopped = phase === "stopped" || isReserved || isError;  // error behaves like stopped for controls
  const isDownloading = phase === "downloading";
  const isWarming = phase === "warming";  // process up, model still loading into VRAM
  const addr = `${s.clientIp || node.ip || ""}:${port}`;
  const nodeGpus = node.gpus || [];
  const gpuBadges = (s.gpuIndexes || []).map((i) => {
    const usedMib = (s.gpuMem || {})[String(i)];
    const usedGb = usedMib ? (usedMib / 1024).toFixed(1) : null;
    const gpuMeta = nodeGpus.find((g) => g.index === i);
    const totalMib = gpuMeta ? Number(gpuMeta.memoryTotalMiB || 0) : 0;
    const totalGb = totalMib > 0 ? Math.round(totalMib / 1024) : null;
    const memLabel = usedGb ? (totalGb ? `${usedGb}/${totalGb}G` : `${usedGb}G`) : "";
    return `<span class="node-gpu-badge">GPU${escapeHtml(String(i))}${memLabel ? " " + escapeHtml(memLabel) : ""}</span>`;
  }).join("");
  // Transient status (stopping / downloading / warming / starting) renders as a
  // compact line INSIDE the model block, replacing the chips row — the card
  // keeps its height instead of growing extra rows at the bottom.
  const _msl = (cls, inner) => `<div class="node-model-row2 model-status-line${cls ? " " + cls : ""}">${inner}</div>`;
  const _mslSpin = (stop) => `<span class="topology-spinner${stop ? " stopping-spinner" : ""}" aria-hidden="true"></span>`;
  // While systemd retries a crashing cell the card mostly shows "loading …" —
  // this ⚠ carries what the PREVIOUS attempt died of (hover for the journal).
  const _prevErrChip = (srv) => {
    const err = srv.status?.lastError;
    if (!err) return "";
    const kindKey = { oom: "cellErrOom", exec: "cellErrExec", model: "cellErrModel", port: "cellErrPort" }[err.kind] || "cellErrCrash";
    const tip = `${t("cellPrevAttempt")} ${t(kindKey)}\n\n${err.tail || err.detail || ""}`.trim();
    return `<span class="msl-prev-err" title="${escapeHtml(tip)}">⚠</span>`;
  };
  let statusRow = "";
  if (isDeleting) {
    statusRow = _msl("msl-stop", `${_mslSpin(true)}<span class="msl-bar indeterminate msl-bar-stop"><span></span></span><span class="msl-text">${escapeHtml(t("removingSlotLabel"))}</span>`);
  } else if (isStopping || isCellStopping) {
    statusRow = _msl("msl-stop", `${_mslSpin(true)}<span class="msl-bar indeterminate msl-bar-stop"><span></span></span><span class="msl-text">${escapeHtml(t("stoppingLabel"))}</span>`);
  } else if (isDownloading) {
    const done = Number(s.downloadedBytes || 0), tot = Number(s.totalBytes || 0);
    const p = tot > 0 ? Math.round((done / tot) * 100) : null;
    const dlFile = s.downloadingFile ? escapeHtml(s.downloadingFile) : escapeHtml(t("topologyRemoteDownloading"));
    statusRow = _msl("", `<span class="msl-bar"><span style="width:${p ?? 0}%"></span></span><span class="msl-text" data-live-dl>${dlFile} · ${(done/1e9).toFixed(1)}/${(tot/1e9).toFixed(1)} GB${p!=null?` · ${p}%`:""}</span>`);
  } else if (isWarming) {
    statusRow = _msl("", `${_mslSpin(false)}<span class="msl-bar indeterminate"><span></span></span><span class="msl-text">${escapeHtml(t("topologyRemoteWarming"))}</span>${_prevErrChip(s)}`);
  } else if (isError && (s.status?.error)) {
    // The unit is failed or flapping — say WHY (classified from its journal)
    // instead of leaving a silent stopped-looking card. WHEN it died matters
    // just as much: an hours-old crash must not read as "it just fell again".
    const err = s.status.error;
    const kindKey = { oom: "cellErrOom", exec: "cellErrExec", model: "cellErrModel", port: "cellErrPort" }[err.kind] || "cellErrCrash";
    const ago = s.status.errorAt ? ` · ${_agoShort(s.status.errorAt)}` : "";
    const tip = [err.detail || "", "", err.tail || ""].join("\n").trim();
    statusRow = _msl("msl-err", `<span class="msl-err-icon" aria-hidden="true">⚠</span><span class="msl-text" title="${escapeHtml(tip)}">${escapeHtml(t(kindKey) + ago)}</span>`);
  } else if (!running && !isStopped) {
    // progressNote (from the cell journal) says WHERE a long start currently
    // is — vLLM downloads/compiles for minutes and a bare spinner reads as a
    // hang. Log-derived, so shown as-is (same policy as error details).
    const note = s.status?.progressNote ? ` · ${s.status.progressNote}` : "";
    statusRow = _msl("", `${_mslSpin(false)}<span class="msl-text">${escapeHtml((phase === "loading" ? t("topologyRemoteLoading") : t("topologyRemoteStarting")) + note)}</span>${_prevErrChip(s)}`);
  }
  const healthCls = running ? "running" : (isStopped ? "" : "loading");
  // Compact model block (name + quant/size/vision chips) — click to drill in.
  const parsed = parseModelName(s.model) || {};
  const hasVision = !!s.mmproj;
  // Authoritative input modalities from the running server's /props, when known.
  const mods = s.modalities || null;
  // Detect built-in MTP: path component ends with "-mtp" (e.g. "qwen3.6-27b-mtp/...")
  const _mtpRe = /-mtp(?:[^a-z0-9]|$)/i;
  const hasMtpBuiltin = _mtpRe.test(s.model || "") || _mtpRe.test(s.modelPath || "");
  const hasMtp = !!s.specDraft || hasMtpBuiltin || (s.specType || "").toLowerCase() === "draft-mtp";
  const ctxChip = s.ctxMax
    ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(s.ctxMax || 0))}`, t("topologyCtxUsageTip") || "Context window")
    : "";
  // For configured (stopped) slot cells pull key params from slotConfig as fallback chips
  const _scfg = s.slotConfig || {};
  const slotCtxChip = (!s.ctxMax && _scfg.CTX_SIZE)
    ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(Number(_scfg.CTX_SIZE)))}`) : "";
  const _benchKey = s.model ? (_modelBenchKey(s.model) || "") : "";
  const _bdata = _benchKey ? serverBenchCache.get(_benchKey) : null;
  const _aaScore = _bdata?.scores?.aa_intelligence;
  const benchChip = _aaScore != null ? mbadge("bench", `🧠 ${_aaScore}`) : "";
  if (s.model) fetchServerBenchIfNeeded(s.model);
  const chips = [
    parsed.quant ? mbadge("quant", `🎛 ${escapeHtml(parsed.quant)}`) : "",
    parsed.size ? mbadge("size", `⚖ ${escapeHtml(parsed.size)}`) : "",
    parsed.variant ? mbadge("it", `🤖 ${escapeHtml(parsed.variant)}`) : "",
    // Prefer real /props modalities; fall back to the mmproj-presence heuristic.
    mods ? [
      mods.vision ? mbadge("vision", "👁 vision") : "",
      mods.audio ? mbadge("audio", "🎙 audio") : "",
      mods.video ? mbadge("video", "🎬 video") : "",
    ].join("") : (hasVision ? mbadge("mmproj", "📷 mmproj") : ""),
    hasMtp ? mbadge("mtp", "⚡ mtp") : "",
    ctxChip || slotCtxChip,
    benchChip,
  ].filter(Boolean).join("");
  // Schedule chip: the cell is started/stopped by a time window.
  const schedChip = (s.schedule && s.schedule.enabled)
    ? mbadge("sched", `⏱ ${escapeHtml(s.schedule.start)}–${escapeHtml(s.schedule.stop)}`,
             t("schedChipTitle"))
    : "";
  // Device chip — every non-reserved cell wears one. Runtime truth first: a
  // RUNNING cell shows its actual device (unit pids vs nvidia compute-apps;
  // command cells included). A STOPPED cell shows the CONFIGURED target —
  // pins are scanned in COMMAND *and* ENV (the Device selector writes
  // TTS_DEVICE=cpu|cuda there; empty CUDA_VISIBLE_DEVICES = hard CPU).
  const _envStr = String(_scfg.ENV || "");
  const _envCmd = `${_envStr}\n${String(_scfg.COMMAND || "")}`;
  const cfgSaysCpu = String(_scfg.N_GPU_LAYERS ?? "").trim() === "0"
    || /(?:^|[\s;,])(?:TTS_DEVICE|DEVICE)=cpu\b|--device[=\s]+cpu\b/i.test(_envCmd)
    || /(?:^|[\n,;\s])CUDA_VISIBLE_DEVICES=(?:""|'')?(?:[\n,;\s]|$)/.test(_envStr);
  const cfgSaysGpu = /(?:^|[\s;,])(?:TTS_DEVICE|DEVICE)=(?:cuda|gpu)\b|--device[=\s]+(?:cuda|gpu)\b/i.test(_envCmd);
  // Device chip carries WHERE (⚡ GPU0); the memory badge carries HOW MUCH and
  // sits next to the model name — live VRAM held by the cell's processes
  // (multi-GPU sums up, the per-GPU split lives in the tooltip).
  const _gpuList = (s.gpuIndexes || []).map((i) => ({ i, mib: Number((s.gpuMem || {})[String(i)] || 0) }));
  const devGpuTxt = _gpuList.map((g) => `GPU${g.i}`).join(" · ");
  const _vramMib = _gpuList.reduce((a, g) => a + g.mib, 0);
  const _vramSplit = _gpuList.filter((g) => g.mib).map((g) => `GPU${g.i}: ${(g.mib / 1024).toFixed(1)} GiB`).join(" · ");
  const memBadge = (running && _vramMib)
    ? mbadge("vram", `${escapeHtml((_vramMib / 1024).toFixed(1))}G`, `${t("vramChipTitle")}${_vramSplit ? ` — ${_vramSplit}` : ""}`)
    : ((!running && Number(s.modelSizeBytes) > 0)
        ? mbadge("vram-est", `≈${escapeHtml((Number(s.modelSizeBytes) / 2 ** 30).toFixed(1))}G`, t("vramEstChipTitle"))
        : "");
  // One truth for the chip AND the card accent (.cpu-cell → blue instead of
  // green/amber): running with no GPU memory, or stopped with CPU pinned in
  // the config.
  const isCpuCell = (running && !devGpuTxt) || (!running && cfgSaysCpu && !isReserved);
  // Stopped without a pin: llama (with offload) and vLLM are GPU by nature,
  // whisper's launcher is CUDA-first; a bare custom command resolves its
  // device at start (VRAM probe) → "auto".
  const _runner = String(_scfg.RUNNER || (String(_scfg.CELL_KIND || "").toLowerCase() === "command" ? "custom" : "llama-server")).toLowerCase();
  const runnerDefaultsGpu = _runner === "llama-server" || _runner === "vllm" || _runner === "whisper";
  const deviceChip = (running && devGpuTxt)
    ? mbadge("gpu", `⚡ ${escapeHtml(devGpuTxt)}`)
    : (isCpuCell
        ? mbadge("cpu", "🧮 CPU", t("topologyCpuCellsHint"))
        : ((!running && !isReserved)
            ? ((cfgSaysGpu || runnerDefaultsGpu)
                ? mbadge("gpu", "⚡ GPU", t("topologyDeviceCfgGpuHint"))
                : mbadge("dev", "⚙ auto", t("topologyDeviceAutoHint")))
            : ""));
  const modelBlock = s.model ? `
    <div class="node-model-block" role="button" tabindex="0"
         data-node-detail="${escapeHtml(node.id)}:${escapeHtml(String(port))}" title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-row1">
        ${runnerChipHtml("llama-server")}
        ${memBadge}
        <strong class="node-model-name" title="${escapeHtml(s.modelPath || s.model)}">${escapeHtml(parsed.label || s.model)}</strong>
      </div>
      ${statusRow || (deviceChip || chips || schedChip ? `<div class="node-model-row2"><span class="model-chips">${deviceChip}${chips}${schedChip}</span></div>` : "")}
    </div>` : "";
  const emptyCellBlock = isReserved ? `
    <div class="node-model-block node-model-block-empty">
      <div class="node-model-row1">
        ${topologyModelIcon()}
        <strong class="node-model-name">:${escapeHtml(String(port))}</strong>
        <span class="node-reserved-tag">${escapeHtml(t("topologyReservedCellLabel"))}</span>${schedChip}
      </div>
      ${statusRow}
    </div>` : "";
  const isCmdCell = String(_scfg.CELL_KIND || "").toLowerCase() === "command";
  const cmdText = String(_scfg.COMMAND || "").replace(/^\s*exec\s+/, "").trim();
  const commandBlock = isCmdCell ? `
    <div class="node-model-block" role="button" tabindex="0"
         data-node-detail="${escapeHtml(node.id)}:${escapeHtml(String(port))}" title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-row1">
        ${runnerChipHtml("custom")}
        ${memBadge}
        <strong class="node-model-name" title="${escapeHtml(cmdText)}">${escapeHtml(cmdText || t("commandCellFallback"))}</strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${deviceChip}${_scfg.HEALTH_PATH ? mbadge("cmd", `❤ ${escapeHtml(_scfg.HEALTH_PATH)}`) : ""}${mbadge("ctx", `:${escapeHtml(String(port))}`)}${schedChip}</span></div>`}
    </div>` : "";
  // vLLM runner cell: no MODEL_FILE — the artifact lives in VLLM_MODEL. Same
  // body layout as a llama cell: model icon + model NAME, then runner chips.
  const isVllmCell = String(_scfg.RUNNER || "").toLowerCase() === "vllm";
  const vllmModel = String(_scfg.VLLM_MODEL || "").trim().replace(/\/+$/, "");
  const vllmArt = vllmModel
    ? (state.artifacts || []).find((a) => vllmModel === a.path || vllmModel.endsWith("/" + a.path))
    : null;
  let vllmName = vllmArt?.name || "";
  let vllmFmt = vllmArt?.format || "";
  if (!vllmName && vllmModel) {
    // <…>/<Model>/<author>/<FORMAT> → Model; a bare HF repo id → its last part.
    const segs = vllmModel.split("/").filter(Boolean);
    const last = segs[segs.length - 1] || "";
    if (_ST_FMT.has(last.toUpperCase()) && segs.length >= 3) {
      vllmFmt = last.toUpperCase();
      vllmName = segs[segs.length - 3];
    } else {
      vllmName = last;
    }
  }
  if (!vllmName) vllmName = String(_scfg.ALIAS || "").trim() || "vLLM";
  const vllmAlias = String(_scfg.ALIAS || "").trim();
  const vllmBlock = (isVllmCell && !s.model) ? `
    <div class="node-model-block" role="button" tabindex="0"
         data-node-detail="${escapeHtml(node.id)}:${escapeHtml(String(port))}" title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-row1">
        ${runnerChipHtml("vllm")}
        ${memBadge}
        <strong class="node-model-name" title="${escapeHtml(vllmModel || vllmName)}${vllmAlias ? escapeHtml(` · served as ${vllmAlias}`) : ""}">${escapeHtml(vllmName)}</strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${deviceChip}${vllmFmt ? mbadge("quant", `🎛 ${escapeHtml(vllmFmt)}`) : ""}${s.vllmStats ? mbadge("cmd", `▶ ${s.vllmStats.requestsRunning}${s.vllmStats.requestsWaiting ? " ⏳" + s.vllmStats.requestsWaiting : ""}`, "running / queued requests") : ""}${s.vllmStats && s.vllmStats.genTps != null ? mbadge("bench", `${formatTps(s.vllmStats.genTps)} t/s`) : ""}${mbadge("cmd", "❤ /v1/models")}${_scfg.MAX_MODEL_LEN ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(Number(_scfg.MAX_MODEL_LEN)))}`) : ""}${mbadge("ctx", `:${escapeHtml(String(port))}`)}${schedChip}</span></div>`}
    </div>` : "";
  // whisper runner cell: the "model" is a faster-whisper size name.
  const isWhisperCell = String(_scfg.RUNNER || "").toLowerCase() === "whisper";
  const whisperSize = String(_scfg.WHISPER_MODEL || "").trim() || "large-v3";
  const whisperBlock = (isWhisperCell && !s.model) ? `
    <div class="node-model-block" role="button" tabindex="0"
         data-node-detail="${escapeHtml(node.id)}:${escapeHtml(String(port))}" title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-row1">
        ${runnerChipHtml("whisper")}
        ${memBadge}
        <strong class="node-model-name" title="faster-whisper ${escapeHtml(whisperSize)}">${escapeHtml(whisperSize)}</strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${deviceChip}${mbadge("cmd", "❤ /health")}${mbadge("ctx", `:${escapeHtml(String(port))}`)}${schedChip}</span></div>`}
    </div>` : "";
  const bodyBlock = modelBlock || vllmBlock || whisperBlock || commandBlock || emptyCellBlock;
  // No model/command block to host the status (e.g. a bare stopped server) —
  // fall back to the old below-the-body progress panel.
  const progressPanel = (!bodyBlock && statusRow)
    ? `<div class="topology-runtime-panel node-progress-panel">${statusRow}</div>`
    : "";
  const isConfiguredCell = phase === "stopped" && !isReserved && !isError;
  const cardCls = [
    isStopping ? "stopping" : (isDeleting ? "deleting" : (running ? "running" : (isError ? "error" : (isStopped ? (isConfiguredCell ? "configured-cell" : "stopped") : "loading")))),
    isReserved ? "reserved-cell" : "",
    isNewReserved ? "reserved-new" : "",
    isCpuCell ? "cpu-cell" : "",
  ].filter(Boolean).join(" ");
  const pillPhase = isStopping ? "stopping" : (running ? "running" : (isError ? "failed" : (phase === "stopped" ? "stopped" : (isWarming ? "warming" : "loading"))));
  // Lifecycle breadcrumb — reserved(0) → configured(1) → starting(2) → running(3)
  const lcIdx = (running || isStopping) ? 3 : (isReserved ? 0 : (isStopped || isError ? 1 : 2));
  const lcActiveStep = isStopping ? "stopping" : (isError ? "error" : (running ? "running" : (isReserved ? "reserved" : (phase === "stopped" ? "configured" : "loading"))));
  let lifecycleBar = serverLifecycleBar(lcIdx, lcActiveStep, "", "", port);
  // Controls differ by role/phase. Controller (controller) is read-only here.
  let controls = "";
  // Client cells (isRemote) render with the same unified card as controller
  // slots so the two look identical. Their config lives on the route-agent,
  // so the ▶ button opens the remote form instead of launching a
  // controller-side slot directly (which they don't have).
  if (s.isSlot || !s.isController) {
    const cellHostId = slotHostId;
    const isCellStopping = _stoppingCells.has(cellKey) || pendingCellAction === "stop";
    const isCellBusy = isCellStopping || !!pendingCellAction;
    const cfgAttrs = `data-node-cell-start="${escapeHtml(s.isController ? "skynet" : node.id)}" data-node-cell-port="${escapeHtml(String(port))}" data-node-role="${escapeHtml(node.role)}"`;

    // ✕ delete — active only when reserved / stopped / error
    const canDelete = (isReserved || phase === "stopped" || isError) && !isDeleting && !isCellBusy;
    const delBtn = isDeleting
      ? `<button class="node-action-btn muted" type="button" disabled title="${escapeHtml(t("removingSlotLabel"))}"><span class="topology-spinner stopping-spinner" aria-hidden="true"></span><span class="nab-lbl">${escapeHtml(t("deleteAction"))}</span></button>`
      : `<button class="node-action-btn ${canDelete ? "del" : "muted"}" type="button"
           ${canDelete ? `data-node-slot-del="${escapeHtml(cellHostId)}:${escapeHtml(String(port))}"` : "disabled"}
           title="${escapeHtml(canDelete ? t("nodeRemoveCell") : t("nodeCannotRemoveActive"))}">✕<span class="nab-lbl">${escapeHtml(t("deleteAction"))}</span></button>`;

    // ⚙ Configure — disabled only during starting / stopping / deleting
    const canConfigure = !isDeleting && !isCellBusy && phase !== "starting";
    // ⇄ Reassign port — same window as delete: only a parked cell may move.
    const canReassign = (isReserved || phase === "stopped" || isError) && !isDeleting && !isCellBusy;
    const portAttrs = canReassign
      ? `data-cell-port-reassign="${escapeHtml(cellHostId)}:${escapeHtml(String(port))}"`
      : "";
    lifecycleBar = serverLifecycleBar(lcIdx, lcActiveStep, "", canConfigure ? cfgAttrs : "", port, portAttrs);

    // ▶ start — active when stopped or error (model already configured).
    // Launches the saved slot directly; server-cell/action handles both
    // controller and client hosts (for a client it forwards to the route-agent
    // via client_llama_start). Reserved cells (no model yet) are configured via
    // the lifecycle-bar ⚙ (cfgAttrs → remote form for clients), not this button.
    const canPlay = (phase === "stopped" || isError) && !isCellBusy && !isDeleting;
    const playBtn = `<button class="node-action-btn ${canPlay ? "ok" : "muted"}" type="button"
        ${canPlay ? `data-node-cell-launch="${escapeHtml(cellHostId)}" data-node-cell-port="${escapeHtml(String(port))}"` : "disabled"}
        title="${escapeHtml(canPlay ? t("nodeStartServer") : (isReserved ? t("nodeConfigureFirst") : t("nodeNotStopped")))}">▶<span class="nab-lbl">${escapeHtml(t("start"))}</span></button>`;

    // ⏹ stop — active when starting or running; spinner while stopping
    const canStop = !isStopped && !isDeleting && !isCellBusy;
    const stopBtn = isCellStopping
      ? `<button class="node-action-btn muted" type="button" disabled title="${escapeHtml(t("nodeStoppingTitle"))}"><span class="topology-spinner stopping-spinner" aria-hidden="true"></span><span class="nab-lbl">${escapeHtml(t("stop"))}</span></button>`
      : `<button class="node-action-btn ${canStop ? "warn" : "muted"}" type="button"
           ${canStop ? `data-node-cell-stop="${escapeHtml(cellHostId)}" data-node-cell-port="${escapeHtml(String(port))}"` : "disabled"}
           title="${escapeHtml(canStop ? t("nodeStopServer") : t("nodeNotRunning"))}">⏹<span class="nab-lbl">${escapeHtml(t("stop"))}</span></button>`;

    // ↑ autostart — controller only for now; shown on both but disabled on client.
    // Three looks: ok = enabled, off = disabled but CLICKABLE (it's a toggle —
    // muted here read as dead chrome), muted = genuinely unavailable (client/busy).
    const bootSupported = s.isController;
    const canBoot = bootSupported && (phase === "stopped" || running) && !isDeleting && !isCellBusy;
    const bootBtn = `<button class="node-action-btn${bootSupported && s.bootEnabled ? " ok" : (canBoot ? " off" : " muted")}" type="button"
        ${canBoot ? `data-node-cell-boot="${escapeHtml(cellHostId)}" data-node-cell-port="${escapeHtml(String(port))}" data-node-cell-boot-action="${s.bootEnabled ? "disable" : "enable"}"` : "disabled"}
        title="${escapeHtml(bootSupported ? (s.bootEnabled ? t("tnBootDisable") : t("tnBootEnable")) : t("tnBootUnsupported"))}">${bootSupported && s.bootEnabled ? "↟" : "↥"}<span class="nab-lbl">${escapeHtml(t("topologyAutostart"))}</span></button>`;

    return `
      <article class="node-server ${cardCls}"
               data-topology-llama="1" data-llama-port="${escapeHtml(String(port))}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, node))}">
        <span class="topology-handle server-input ${healthCls}" data-topology-llama-input="1"
              data-llama-port="${escapeHtml(String(port))}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, node))}" title="${escapeHtml(t("tnTitleProxyUpstream"))}"></span>
        <div class="node-ctrl-row">
          ${playBtn}${stopBtn}${bootBtn}${delBtn}
        </div>
        ${lifecycleBar}
        ${bodyBlock
          ? (isReserved
              ? `<div class="node-server-body">${bodyBlock}${(() => `<div class="topology-runtime-panel llama ghost-slots"><div class="topology-runtime-slots-head"><strong>${escapeHtml(t("topologySlots"))} <span class="topology-muted">1</span></strong></div><div class="topology-runtime-slots slot-chips-row"><span class="slot-chip idle"></span></div></div>`)()}</div>${progressPanel}`
              : `<div class="node-server-body">${bodyBlock}${topologyRuntimePanelHtml(topologyServerGroup(s))}</div>${progressPanel}`)
          : progressPanel}
        ${(() => {
          const note = (topology?.cellNotes || {})[slotKey];
          return note ? `<div class="node-server-note" title="${escapeHtml(note)}">💬 ${escapeHtml(note)}</div>` : "";
        })()}
        ${isError && s.lastError ? (() => {
          const err = classifyLlamaError(s.lastError);
          return `<div class="topology-remote-unreachable llama-err-block" title="${escapeHtml(s.lastError)}">
            <span class="llama-err-icon">⚠</span>
            <span class="llama-err-body">
              <span class="llama-err-friendly">${escapeHtml(err.friendly)}</span>
              ${err.hint ? `<span class="llama-err-hint">${escapeHtml(err.hint)}</span>` : ""}
              <span class="llama-err-raw">${escapeHtml(s.lastError)}</span>
            </span>
          </div>`;
        })() : ""}
        ${running && s.reachable === false ? (() => {
          const fw = s.firewall || {};
          const isBlocked = fw.state === "blocked";
          const ufwCmd = isBlocked ? `sudo ufw allow ${port}` : "";
          return `<div class="topology-remote-unreachable">
            <span>${escapeHtml(t("topologyRemoteUnreachable"))}</span>
            ${ufwCmd ? `<code class="firewall-cmd" title="Run on ${escapeHtml(node.name || node.id)}">${escapeHtml(ufwCmd)}</code>` : ""}
          </div>`;
        })() : ""}
      </article>`;
  } else if (s.isController) {
    // Controller's legacy single "current" llama server (not a reserved slot).
    const editBtn = `<button class="node-icon-btn" type="button" data-node-ctrl-edit title="${escapeHtml(t("nodeEditConfig"))}">✎</button>`;
    if (!isStopped) {
      controls = editBtn + `<button class="node-icon-btn warn" type="button" data-node-ctrl-stop title="${escapeHtml(t("nodeStopLlama"))}">⏹</button>`;
    } else {
      controls = editBtn + `<button class="node-icon-btn ok" type="button" data-node-ctrl-start title="${escapeHtml(t("nodeStartLlama"))}">▶</button>`;
    }
  }
  if (controls) controls = `<span class="node-server-ctl">${controls}</span>`;
  return `
    <article class="node-server ${cardCls}"
             data-topology-llama="1" data-llama-port="${escapeHtml(String(port))}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, node))}">
      <span class="topology-handle server-input ${healthCls}" data-topology-llama-input="1"
            data-llama-port="${escapeHtml(String(port))}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, node))}" title="${escapeHtml(t("tnTitleProxyUpstream"))}"></span>
      ${lifecycleBar}
      <div class="node-server-head">
        <a href="http://${escapeHtml(addr)}" target="_blank" rel="noopener" class="topology-addr-link" onclick="event.stopPropagation()">${escapeHtml(addr)}</a>
        ${firewallBadge(s.firewall)}
        ${gpuBadges || (running ? `<span class="node-gpu-badge node-cpu-badge" title="${escapeHtml(t("topologyCpuCellsHint"))}">CPU</span>` : "")}
        <span style="flex:1"></span>
        ${controls}
      </div>
      ${bodyBlock
        ? (isReserved
            ? `<div class="node-server-body">${bodyBlock}${(() => `<div class="topology-runtime-panel llama ghost-slots"><div class="topology-runtime-slots-head"><strong>${escapeHtml(t("topologySlots"))} <span class="topology-muted">1</span></strong></div><div class="topology-runtime-slots slot-chips-row"><span class="slot-chip idle"></span></div></div>`)()}</div>${progressPanel}`
            : `<div class="node-server-body">${bodyBlock}${topologyRuntimePanelHtml(topologyServerGroup(s))}</div>${progressPanel}`)
        : progressPanel}
      ${isError && s.lastError ? (() => {
        const err = classifyLlamaError(s.lastError);
        return `<div class="topology-remote-unreachable llama-err-block" title="${escapeHtml(s.lastError)}">
          <span class="llama-err-icon">⚠</span>
          <span class="llama-err-body">
            <span class="llama-err-friendly">${escapeHtml(err.friendly)}</span>
            ${err.hint ? `<span class="llama-err-hint">${escapeHtml(err.hint)}</span>` : ""}
            <span class="llama-err-raw">${escapeHtml(s.lastError)}</span>
          </span>
        </div>`;
      })() : ""}
      ${running && s.reachable === false ? (() => {
        const fw = s.firewall || {};
        const isBlocked = fw.state === "blocked";
        const ufwCmd = isBlocked ? `sudo ufw allow ${port}` : "";
        return `<div class="topology-remote-unreachable">
          <span>${escapeHtml(t("topologyRemoteUnreachable"))}</span>
          ${ufwCmd ? `<code class="firewall-cmd" title="Run on ${escapeHtml(node.name || node.id)}">${escapeHtml(ufwCmd)}</code>` : ""}
        </div>`;
      })() : ""}
    </article>`;
}

// Drill-in detail modal for a node server (full info that the compact card omits).
export function openNodeServerDetail(nodeId, port) {
  const node = (topology?.nodes || []).find((n) => String(n.id) === String(nodeId));
  const s = node && (node.servers || []).find((x) => String(x.port) === String(port));
  if (!s) return;
  document.getElementById("nodeServerDetailOverlay")?.remove();
  const phase = s.phase || (s.status && s.status.phase) || (s.isController ? "running" : "stopped");
  const running = phase === "running";
  const parsed = parseModelName(s.model) || {};
  const fw = s.firewall || {};
  const activity = running ? (topologyLlamaActivity(s.port) || {}) : {};
  const _mtpRe = /-mtp(?:[^a-z0-9]|$)/i;
  const hasMtpBuiltin = _mtpRe.test(s.model || "") || _mtpRe.test(s.modelPath || "");
  const hasMtp = !!s.specDraft || hasMtpBuiltin || (s.specType || "").toLowerCase() === "draft-mtp";
  const _scfg = s.slotConfig || {};
  const isCmd = String(_scfg.CELL_KIND || "").toLowerCase() === "command";
  const isVllm = String(_scfg.RUNNER || "").toLowerCase() === "vllm";
  const isWhisper = String(_scfg.RUNNER || "").toLowerCase() === "whisper";
  const nsdCtxChip = s.ctxMax
    ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(s.ctxMax))}`, t("topologyCtxUsageTip") || "Context window")
    : (_scfg.CTX_SIZE ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(Number(_scfg.CTX_SIZE)))}`) : "");
  const addr = `${s.clientIp || node.ip || ""}:${s.port}`;
  const gpuLines = (s.gpuIndexes || []).map((i) => {
    const mib = (s.gpuMem || {})[String(i)];
    return `GPU${i}${mib ? ` · ${(mib / 1024).toFixed(1)} GB` : ""}`;
  }).join(", ");

  // GPU badges for the status row
  const nodeGpusList = node.gpus || [];
  const statusGpuBadges = (s.gpuIndexes || []).map((i) => {
    const mib = (s.gpuMem || {})[String(i)];
    const usedGb = mib ? (mib / 1024).toFixed(1) : null;
    const gpuMeta = nodeGpusList.find((g) => g.index === i);
    const totalMib = gpuMeta ? Number(gpuMeta.memoryTotalMiB || 0) : 0;
    const totalGb = totalMib > 0 ? Math.round(totalMib / 1024) : null;
    const memLabel = usedGb ? (totalGb ? `${usedGb}/${totalGb}G` : `${usedGb}G`) : "";
    return `<span class="node-gpu-badge">GPU${escapeHtml(String(i))}${memLabel ? " " + escapeHtml(memLabel) : ""}</span>`;
  }).join(" ");

  const row = (k, v) => v ? `<div class="nsd-row"><span class="nsd-k">${escapeHtml(k)}</span><span class="nsd-v">${v}</span></div>` : "";

  // Build formatted command block from slotConfig
  const cmdBlockHtml = (() => {
    const cfg = s.slotConfig || {};
    if (isWhisper) {
      const size = String(cfg.WHISPER_MODEL || "").trim() || "large-v3";
      const lines = [`export PORT=${cfg.PORT || s.port || ""}`,
                     `exec env HUGGINGFACE_HUB_CACHE="\${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper" bash $HOME/run_whisper.sh "$PORT" ${size}`];
      const cmdText = lines.join("\n");
      const pre = lines.map((l) => `<span class="cmd-token">${escapeHtml(l)}</span>`).join("\n");
      return `<div class="nsd-cfg-section"><div class="nsd-cfg-head">COMMAND <button class="nsd-copy-btn" type="button" data-copy="${escapeHtml(cmdText)}" title="Copy">⎘</button></div><pre class="command-preview nsd-cmd-pre">${pre}</pre></div>`;
    }
    if (isVllm) {
      // Simplified mirror of build_vllm_command() — the authoritative script
      // lives in the cell's start.sh; this is the human-readable summary.
      const m = String(cfg.VLLM_MODEL || "").trim() || "…";
      const served = String(cfg.ALIAS || "").trim() || (m.split("/").filter(Boolean).pop() || "").toLowerCase();
      const p = ["$HOME/vllm-venv/bin/vllm serve", m, '--host 0.0.0.0 --port "$PORT"'];
      if (served) p.push(`--served-model-name ${served}`);
      if (cfg.MAX_MODEL_LEN) p.push(`--max-model-len ${cfg.MAX_MODEL_LEN}`);
      if (cfg.GPU_MEMORY_UTILIZATION) p.push(`--gpu-memory-utilization ${cfg.GPU_MEMORY_UTILIZATION}`);
      const q = String(cfg.QUANTIZATION || "").toLowerCase();
      if (q && q !== "auto") p.push(`--quantization ${q}`);
      const dt = String(cfg.DTYPE || "").toLowerCase();
      if (dt && dt !== "auto") p.push(`--dtype ${dt}`);
      const tp = String(cfg.TENSOR_PARALLEL || "").trim();
      if (tp && tp !== "0" && tp !== "1") p.push(`--tensor-parallel-size ${tp}`);
      const lines = [`export PORT=${cfg.PORT || s.port || ""}`, `exec ${p.join(" ")}`];
      const cmdText = lines.join("\n");
      const pre = lines.map((l) => `<span class="cmd-token">${escapeHtml(l)}</span>`).join("\n");
      return `<div class="nsd-cfg-section"><div class="nsd-cfg-head">COMMAND <button class="nsd-copy-btn" type="button" data-copy="${escapeHtml(cmdText)}" title="Copy">⎘</button></div><pre class="command-preview nsd-cmd-pre">${pre}</pre></div>`;
    }
    if (isCmd) {
      const port = cfg.PORT || s.port || "";
      const lines = [`export PORT=${port}`];
      String(cfg.ENV || "").split(/[\n,]/).forEach((raw) => {
        const it = raw.trim(); if (!it || it.startsWith("#") || !it.includes("=")) return;
        const i = it.indexOf("="); const k = it.slice(0, i).trim();
        if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k)) return;
        lines.push(`export ${k}="${it.slice(i + 1).trim()}"`);
      });
      if (cfg.WORKDIR) lines.push(`cd ${cfg.WORKDIR}`);
      const c = String(cfg.COMMAND || "").trim().replace(/^\s*exec\s+/, "");
      lines.push(`exec ${c || "…"}`);
      const cmdText = lines.join("\n");
      const pre = lines.map((l) => `<span class="cmd-token">${escapeHtml(l)}</span>`).join("\n");
      return `<div class="nsd-cfg-section"><div class="nsd-cfg-head">COMMAND <button class="nsd-copy-btn" type="button" data-copy="${escapeHtml(cmdText)}" title="Copy">⎘</button></div><pre class="command-preview nsd-cmd-pre">${pre}</pre></div>`;
    }
    if (!Object.keys(cfg).length) return "";
    const tokens = [];
    const add = (flag, val) => { if (val != null && String(val).trim() !== "") tokens.push(flag, String(val).trim()); };
    const llamaBin = state?.paths?.llamaHome ? `${state.paths.llamaHome}/build/bin/llama-server` : null;
    if (llamaBin) tokens.push(llamaBin);
    add("--host", cfg.HOST);
    add("--port", cfg.PORT);
    const modelPath = s.modelPath || [cfg.LLAMA_MODELS_DIR, cfg.MODEL_FILE].filter(Boolean).join("/");
    if (modelPath) add("--model", modelPath);
    add("--ctx-size", cfg.CTX_SIZE);
    add("--threads", cfg.THREADS);
    add("--threads-batch", cfg.THREADS_BATCH);
    add("--batch-size", cfg.BATCH_SIZE);
    add("--ubatch-size", cfg.UBATCH_SIZE);
    add("--parallel", cfg.PARALLEL);
    add("--n-gpu-layers", cfg.N_GPU_LAYERS);
    add("--cache-type-k", cfg.CACHE_TYPE_K);
    add("--cache-type-v", cfg.CACHE_TYPE_V);
    const mmproj = s.mmproj || [cfg.LLAMA_MODELS_DIR, cfg.MMPROJ_FILE].filter(Boolean).join("/");
    if (mmproj) {
      add("--mmproj", mmproj);
      if (String(cfg.OFFLOAD_MMPROJ || "").toLowerCase() === "true") tokens.push("--mmproj-offload");
    }
    const specTypeRaw = (cfg.SPEC_TYPE || "").trim().toLowerCase();
    const specType = specTypeRaw === "mtp" ? "draft-mtp" : specTypeRaw;
    if (specType && specType !== "none") {
      add("--spec-type", specType);
      if (cfg.SPEC_DRAFT_MODEL_FILE) {
        add("--model-draft", [cfg.LLAMA_MODELS_DIR, cfg.SPEC_DRAFT_MODEL_FILE].filter(Boolean).join("/"));
        add("--gpu-layers-draft", cfg.SPEC_DRAFT_N_GPU_LAYERS);
      }
      add("--spec-draft-n-max", cfg.SPEC_DRAFT_N_MAX);
    }
    if (!tokens.length) return "";
    const parts = [];
    let ti = 0;
    while (ti < tokens.length) {
      const tok = tokens[ti];
      if (tok.startsWith("--") && ti + 1 < tokens.length && !tokens[ti + 1].startsWith("-")) {
        parts.push(`<span class="cmd-token">${escapeHtml(tok)} <span class="cmd-value">${escapeHtml(tokens[ti + 1])}</span></span>`);
        ti += 2;
      } else {
        parts.push(`<span class="cmd-token">${escapeHtml(tok)}</span>`);
        ti += 1;
      }
    }
    const cmdText = tokens.join(" ");
    return `<div class="nsd-cfg-section">
      <div class="nsd-cfg-head">COMMAND <button class="nsd-copy-btn" type="button" data-copy="${escapeHtml(cmdText)}" title="${escapeHtml(t("copyCommand"))}">⎘</button></div>
      <pre class="command-preview nsd-cmd-pre">${parts.join("\n")}</pre>
    </div>`;
  })();

  const html = `
    <div class="modal-overlay" id="nodeServerDetailOverlay">
      <div class="modal node-detail-modal" role="dialog" aria-modal="true">
        <div class="modal-head-row">
          <strong>${escapeHtml(node.name || node.id)}</strong>
          <button class="icon-action compact" id="nodeServerDetailClose" aria-label="Close">✕</button>
        </div>
        <div class="nsd-body">
          ${row("Status", `${topologyStatusPill(running ? "running" : (phase === "error" ? "failed" : phase))} ${firewallBadge(fw)} ${statusGpuBadges || (running ? `<span class="node-gpu-badge node-cpu-badge" title="${escapeHtml(t("topologyCpuCellsHint"))}">CPU</span>` : "")}`)}
          ${row("Address", `<a href="http://${escapeHtml(addr)}" target="_blank" rel="noopener" class="topology-addr-link nsd-addr-link" onclick="event.stopPropagation()">${escapeHtml(addr)} ↗</a>`)}
          ${isCmd
            ? row("Command", `<code class="nsd-cmd-inline">${escapeHtml(String(_scfg.COMMAND || "").replace(/^\s*exec\s+/, "") || "—")}</code>`)
            : isVllm
            ? row("Model", `<code class="nsd-cmd-inline">${escapeHtml(String(_scfg.VLLM_MODEL || "") || "—")}</code>`)
            : isWhisper
            ? row("Model", `<code class="nsd-cmd-inline">faster-whisper ${escapeHtml(String(_scfg.WHISPER_MODEL || "large-v3"))}</code>`)
            : row("Model", escapeHtml(parsed.label || s.model || ""))}
          ${isVllm ? row("Runner", `${mbadge("cmd", "⚡ vllm")}${mbadge("cmd", "❤ /v1/models")}`) : ""}
          ${isWhisper ? row("Runner", `${mbadge("cmd", "🎙 whisper")}${mbadge("cmd", "❤ /health")}`) : ""}
          ${isCmd
            ? (row("Health", _scfg.HEALTH_PATH ? `<code>${escapeHtml(_scfg.HEALTH_PATH)}</code>` : "") + row("Workdir", _scfg.WORKDIR ? `<code>${escapeHtml(_scfg.WORKDIR)}</code>` : ""))
            : (() => { const chips = [parsed.quant ? mbadge("quant", `🎛 ${escapeHtml(parsed.quant)}`) : "", parsed.size ? mbadge("size", `⚖ ${escapeHtml(parsed.size)}`) : "", parsed.variant ? mbadge("it", `🤖 ${escapeHtml(parsed.variant)}`) : "", s.mmproj ? mbadge("mmproj", "📷 mmproj") : "", hasMtp ? mbadge("mtp", "⚡ mtp") : "", nsdCtxChip].filter(Boolean).join(""); return chips ? `<div class="nsd-row"><span class="nsd-k"></span><span class="nsd-v"><span class="model-chips">${chips}</span></span></div>` : ""; })()}
          ${row("GPU", gpuLines ? escapeHtml(gpuLines) : (running ? "CPU" : ""))}
          ${row(t("topologyTokenSpeedHead"), (s.promptTps != null || s.genTps != null) ? `${formatTps(s.promptTps || 0)} / ${formatTps(s.genTps || 0)} t/s (${t("topologyPromptGen")})` : "")}
          ${row("Context", s.ctxMax ? `${s.ctxUsed != null ? escapeHtml(formatCtxTokens(s.ctxUsed)) : "—"} / ${escapeHtml(formatCtxTokens(s.ctxMax))} ${escapeHtml(t("topologyLlamaContextWindow").toLowerCase())}` : "")}
          ${row("Activity", [activity.label, activity.summary].filter(Boolean).map(escapeHtml).join(" · "))}
          ${(s.isController || s.isSlot) ? row("Service", escapeHtml([s.service, s.pid ? `PID ${s.pid}` : ""].filter(Boolean).join(" · "))) : ""}
          ${s.reachable === false ? row("Reachable", "<span style='color:var(--warn,#f59e0b)'>no — port blocked?</span>") : ""}
          ${phase === "error" && s.lastError ? row("Error", `<code>${escapeHtml(s.lastError)}</code>`) : ""}
          ${cmdBlockHtml}
          <div class="nsd-cfg-section nsd-note-section">
            <div class="nsd-cfg-head">${escapeHtml(t("cellNoteHead"))}</div>
            <textarea class="nsd-note-input" maxlength="280" rows="2"
              placeholder="${escapeHtml(t("cellNotePlaceholder"))}">${escapeHtml((topology?.cellNotes || {})[`${s.isController ? "skynet" : node.id}:${s.port}`] || "")}</textarea>
            <button class="nsd-note-save" type="button">${escapeHtml(t("cellNoteSave"))}</button>
          </div>
        </div>
      </div>
    </div>`;
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  const overlay = tmp.firstElementChild;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  overlay.querySelector("#nodeServerDetailClose")?.addEventListener("click", close);
  overlay.querySelectorAll("[data-copy]").forEach((b) => {
    b.addEventListener("click", async () => {
      // copyText falls back to execCommand — the LAN UI runs on plain http
      // where navigator.clipboard does not exist.
      if (await copyText(b.dataset.copy)) {
        const orig = b.textContent;
        b.textContent = "✓";
        setTimeout(() => { b.textContent = orig; }, 1200);
      }
    });
  });
  overlay.querySelector(".nsd-note-save")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const note = overlay.querySelector(".nsd-note-input")?.value ?? "";
    btn.disabled = true;
    try {
      await api("/api/topology/server-slot/note", {
        method: "POST",
        body: JSON.stringify({ hostId: s.isController ? "skynet" : node.id, port: s.port, note }),
      });
      toast(t("cellNoteSaved"));
      await refreshTopology();
      renderTopology();
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false;
    }
  });
}

// Parse "version: 362 (3ac3c20)" → { build: 362, commit: "3ac3c20" }
export function parseLlamaBuildVersion(vstr) {
  if (!vstr) return null;
  const m = String(vstr).match(/version:\s*(\d+)\s*\(([0-9a-f]+)\)/i);
  if (!m) return null;
  return { build: parseInt(m[1], 10), commit: m[2] };
}

// Returns the node-grouped HTML for the Llama Servers lane.
export function nodesLaneHtml() {
  if (!topology) return "";
  // Only show the controller and client nodes that actually have a GPU (or a
  // declared server). GPU-less clients live in the Clients column instead.
  const nodes = (topology.nodes || []).filter((n) =>
    n.role === "controller" || (n.gpus || []).length > 0 || (n.servers || []).length > 0);
  // Determine controller build number for "outdated" comparison
  const ctrlVersionStr = state.llamaCpp?.version || "";
  const ctrlBuild = parseLlamaBuildVersion(ctrlVersionStr);
  const ctrlMtime = state.llamaCpp?.binaryMtime || "";
  const ctrlUpstreamBuild = state.llamaCpp?.git?.upstreamBuild || 0;
  const ctrlUpstreamChecked = state.llamaCpp?.git?.upstreamChecked || false;
  const ctrlUpstreamCommit = state.llamaCpp?.git?.upstreamBuildCommit || "";
  const ctrlHeadCommit = state.llamaCpp?.git?.head || "";

  const sections = nodes.map((n) => {
    const cpu = n.cpu || {}, ram = cpu.ram || {};
    const cpuTxt = cpu.loadPct != null ? `CPU ${cpu.loadPct}%` : "";
    const ramTxt = ram.usedGb != null ? `RAM ${ram.usedGb}/${ram.totalGb} GB` : (ram.totalGb != null ? `RAM ${ram.totalGb} GB` : "");
    // llama.cpp version chip
    const nodeVerStr = n.role === "controller" ? ctrlVersionStr : (n.llamaBinaryVersion || "");
    const nodeMtime = n.role === "controller" ? ctrlMtime : (n.llamaBinaryMtime || "");
    const nodeBuild = parseLlamaBuildVersion(nodeVerStr);
    const verLabel = nodeBuild ? `b${nodeBuild.build}` : "";
    // Дата сборки: берём только дату (первые 10 символов ISO, без времени)
    const verDate = nodeMtime ? nodeMtime.slice(0, 10) : "";
    // Outdated = different commit hash (most reliable) OR lower build number when
    // commits are unavailable. Same commit hash → in sync regardless of build number
    // (happens when one clone is shallow and the other is full). Hashes are short
    // git abbrevs whose LENGTH varies per clone (7 vs 9 chars for the same commit),
    // so equality is prefix-based — strict !== flagged in-sync fleets as outdated.
    const sameCommit = (a, b) => !!a && !!b && (a.startsWith(b) || b.startsWith(a));
    const verOutdated = nodeBuild && ctrlBuild && n.role !== "controller" && (
      (nodeBuild.commit && ctrlBuild.commit)
        ? !sameCommit(nodeBuild.commit, ctrlBuild.commit)
        : nodeBuild.build < ctrlBuild.build       // fallback: numeric comparison
    );
    const verChipTitle = [nodeVerStr, nodeMtime].filter(Boolean).join(" · ");
    // For the controller: show the upstream arrow only when the release tag's
    // COMMIT differs from the local head — the numeric build is a clone-local
    // counter (a shallow clone reports e.g. 731 while sitting exactly on
    // b9947), so number-vs-number would show a false "outdated" arrow forever.
    const isCtrlNode = n.role === "controller";
    const upstreamIsNewer = ctrlUpstreamChecked && ctrlUpstreamBuild > 0 && (
      (ctrlUpstreamCommit && (ctrlHeadCommit || nodeBuild?.commit))
        ? !sameCommit(ctrlUpstreamCommit, ctrlHeadCommit || nodeBuild.commit)
        : (nodeBuild && ctrlUpstreamBuild > nodeBuild.build)
    );
    const upstreamArrow = isCtrlNode && upstreamIsNewer
      ? `<span class="llama-ver-upstream"> → b${ctrlUpstreamBuild} ⬆</span>`
      : "";
    const refreshBtn = isCtrlNode
      ? `<button class="llama-ver-refresh" type="button" data-check-llama-ver title="${escapeHtml(t("checkUpstreamVersion"))}" aria-label="${escapeHtml(t("checkUpstreamVersion"))}">↻</button>`
      : "";
    // Client nodes: one-click llama.cpp update (converges the client onto the
    // controller's commit via the scout's background job); while the scout
    // reports a running job the button gives way to a building indicator.
    const upd = n.llamaUpdate || {};
    const updateBtn = !isCtrlNode && nodeVerStr
      ? (upd.running
        ? `<span class="llama-ver-building" title="${escapeHtml(String(upd.lastLine || ""))}">⏳ ${escapeHtml(t("clientLlamaBuilding"))}</span>`
        : `<button class="llama-ver-refresh" type="button" data-update-client-llama="${escapeHtml(String(n.id))}" title="${escapeHtml(t("updateClientLlama"))}" aria-label="${escapeHtml(t("updateClientLlama"))}">⇪</button>`)
      : "";
    // Stale binary: a server that started BEFORE the binary on disk was last
    // rebuilt still runs the old build — restart it to apply.
    const nodeMtimeEpoch = nodeMtime ? Date.parse(nodeMtime) / 1000 : 0;
    const staleBinary = !isCtrlNode && nodeMtimeEpoch > 0 && (n.servers || []).some((s) => {
      const upSec = Number(s.uptimeSec || 0);
      return upSec > 0 && (Date.now() / 1000 - upSec) < nodeMtimeEpoch;
    });
    const staleBadge = staleBinary
      ? `<span class="llama-ver-stale" title="${escapeHtml(t("staleBinaryTitle"))}">⟳ ${escapeHtml(t("staleBinaryBadge"))}</span>`
      : "";
    const verChip = verLabel
      ? `<span class="llama-ver-chip${verOutdated ? " outdated" : ""}" title="${escapeHtml(verChipTitle)}">${escapeHtml(verLabel)}${verDate ? `<span class="llama-ver-date"> ${escapeHtml(verDate)}</span>` : ""}${upstreamArrow}${verOutdated ? " ⬆" : ""}</span>${refreshBtn}${updateBtn}${staleBadge}`
      : refreshBtn || "";
    const servers = (n.servers || []);
    const collapsed = _collapsedNodes.has(n.id);
    const nextCellPort = nextTopologyCellPort();
    const reservePending = _reservingCells.get(String(n.id));
    const reservePort = reservePending?.port || nextCellPort;
    const reserveBusy = !!reservePending;
    // A containerized controller has no systemd to host cells — swap the
    // reserve card for a hint that models are served by caravan-scout hosts.
    const addBtn = n.containerized
      ? `<article class="node-server ghost-server container-hint">
      <div class="ghost-server-body"><span class="container-cells-hint">🐳 ${escapeHtml(t("topologyContainerCellsHint"))}</span></div>
    </article>`
      : `<article class="node-server ghost-server${reserveBusy ? " reserving" : ""}">
      ${serverLifecycleBar(-1, "none")}
      <div class="ghost-server-body">
        <button class="ghost-start-btn" type="button"
          data-node-reserve="${escapeHtml(n.id)}"
          data-node-reserve-port="${escapeHtml(String(reservePort))}"
          data-node-role="${escapeHtml(n.role)}"
          ${reserveBusy ? "disabled" : ""}>${reserveBusy ? `<span class="topology-spinner" aria-hidden="true"></span> ${escapeHtml(t("topologyReservingCellLabel"))} :${escapeHtml(String(reservePort))}` : `＋ ${escapeHtml(t("topologyReserveCellLabel"))} :${escapeHtml(String(reservePort))}`}</button>
      </div>
    </article>`;
    // When collapsed, keep a left-edge rail of cable anchors (one per server)
    // so proxy cables stay attached.
    let bodyHtml;
    if (collapsed) {
      const rail = servers.map((s) => {
        const phase = s.phase || (s.status && s.status.phase) || "running";
        const cls = phase === "running" ? "running" : (phase === "stopped" || phase === "reserved" ? "" : "loading");
        return `<span class="node-rail-input" title="${escapeHtml(`${s.clientIp || n.ip || ""}:${s.port}`)}">
            <span class="topology-handle server-input ${cls}" data-topology-llama-input="1" data-llama-port="${escapeHtml(String(s.port))}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, n))}"></span>
            <code>${escapeHtml(String(s.port))}</code></span>`;
      }).join("");
      bodyHtml = `<div class="node-rail">${rail || `<span class="topology-muted" style="font-size:11px">${escapeHtml(t("topologyNoServers"))}</span>`}</div>`;
    } else {
      const startingCard = nodeStartingCardHtml(n);
      const serversHtml = servers.length
        ? servers.map((s) => nodeServerCardHtml(n, s)).join("")
        : "";
      // Cells that run on this host WITHOUT touching a GPU (n-gpu-layers 0,
      // command cells): they never appear in a GPU row's ▶ ports, so give
      // them their own CPU line — otherwise a running CPU cell looks missing.
      const cpuPorts = servers.filter((srv) => {
        const ph = srv.phase || (srv.status && srv.status.phase) || "";
        return ph === "running" && !(srv.gpuIndexes || []).length;
      }).map((srv) => srv.port).filter(Boolean);
      const cpuRowHtml = cpuPorts.length ? `
        <div class="node-gpu-row node-cpu-row" title="${escapeHtml(t("topologyCpuCellsHint"))}">
          <div class="node-gpu-head">
            <strong>CPU</strong>
            <span class="node-gpu-name">${escapeHtml(t("topologyCpuCellsLabel"))}</span>
          </div>
          <div class="node-gpu-meta">
            <span class="node-gpu-ports">▶ ${cpuPorts.map((pp) => escapeHtml(String(pp))).join(", ")}</span>
          </div>
        </div>` : "";
      const gpusHtml = ((n.gpus || []).length
        ? n.gpus.map((g) => nodeGpuRowHtml(n, g)).join("")
        : `<div class="topology-muted" style="font-size:12px">${escapeHtml(t("topologyNoGpu"))}</div>`) + cpuRowHtml;
      // Controller node hosts the deep controller telemetry (mounted, not rebuilt):
      // Server charts toggle under the "Servers" header; GPU charts live in the
      // GPUs column; Incidents open in a modal from the header button.
      const isCtrl = n.role === "controller";
      const statsOpen = localStorage.getItem("topologyCtrlServerStatsOpen") === "1";
      const serversSubtitle = isCtrl
        ? `<button class="node-subtitle node-subtitle-toggle" type="button" data-ctrl-stats-toggle aria-expanded="${statsOpen ? "true" : "false"}">${escapeHtml(t("topologyServersHead"))} <span class="node-subtitle-caret">${statsOpen ? "▾" : "▸"}</span><span class="node-subtitle-hint">${escapeHtml(t("topologyNodeServerCharts"))}</span></button>`
        : `<div class="node-subtitle">${escapeHtml(t("topologyServersHead"))}</div>`;
      const serverStatsSlot = isCtrl ? `<div class="node-ctrl-server-stats" data-ctrl-server-stats${statsOpen ? "" : " hidden"}></div>` : "";
      // Controller mounts the rich controller canvas widget; client nodes get the
      // same-looking telemetry rows built from per-node history.
      const gpuTelemetrySlot = isCtrl ? `<div class="node-ctrl-gpu-telemetry" data-ctrl-gpu-telemetry></div>` : nodeTelemetryRowsHtml(n);
      bodyHtml = `<div class="node-body">
          <div class="node-servers">${serversSubtitle}${serversHtml}${startingCard}${addBtn}${serverStatsSlot}</div>
          <div class="node-gpus"><div class="node-subtitle">${escapeHtml(t("topologyGpusSection"))}</div>${gpusHtml}${gpuTelemetrySlot}</div>
        </div>`;
    }
    return `
      <section class="node-card ${n.online ? "online" : "offline"} ${collapsed ? "collapsed" : ""}" data-node-id="${escapeHtml(n.id)}">
        <header class="node-head">
          <button class="node-collapse" type="button" data-node-collapse="${escapeHtml(n.id)}" title="${escapeHtml(collapsed ? t("expand") : t("collapse"))}" aria-expanded="${collapsed ? "false" : "true"}">${collapsed ? "▸" : "▾"}</button>
          <span class="node-dot ${n.online ? "on" : "off"}"></span>
          <strong>${escapeHtml(n.name || n.id)}</strong>
          <span class="node-role">${escapeHtml(n.role === "controller" ? t("nodeRoleController") : n.role === "client" ? t("nodeRoleClient") : n.role)}</span>
          ${n.ip ? `<span class="topology-muted">${escapeHtml(n.ip)}</span>` : ""}
          ${verChip}
          ${collapsed ? `<span class="node-meta">${servers.length} srv · ${(n.gpus||[]).length} GPU</span>` : ""}
          <span style="flex:1"></span>
          ${(n.role === "controller")
            ? `<button class="node-incidents-btn" type="button" data-ctrl-incidents title="${escapeHtml(t("topologyIncidentsOpen"))}">⚠ <span data-ctrl-incidents-count>0</span></button>` : ""}
          <span class="node-meta" data-live-nodemeta>${escapeHtml([cpuTxt, ramTxt, n.platform].filter(Boolean).join(" · "))}</span>
        </header>
        ${bodyHtml}
      </section>`;
  }).join("");

  return sections || `<div class="topology-muted">${escapeHtml(t("topologyNoNodes"))}</div>`;
}

// Move the live controller stats/charts elements back to their home .lane-stats
// section (called before every lane rebuild so innerHTML doesn't destroy them).
export const _LANE_STATS_CARDS = ["topology-server-stats-card", "topology-gpu-history-card", "topology-incidents-card"];
export let _incidentsModalOpen = false;
export function parkLaneStats() {
  const home = document.querySelector(".lane-stats");
  if (!home) return;
  _LANE_STATS_CARDS.forEach((cls) => {
    // Keep the incidents card in its modal while it's open — don't yank it home.
    if (cls === "topology-incidents-card" && _incidentsModalOpen) return;
    const el = document.querySelector("." + cls);
    if (el && el.parentElement !== home) home.appendChild(el);
  });
}
// After a node-mode render, relocate the live telemetry cards (canvases, so we
// move the DOM rather than rebuild it) into their slots in the controller node:
// Server charts under the Servers toggle, GPU charts in the GPUs column. The
// incidents card stays parked until its modal is opened.
export function mountNodeTelemetry() {
  const root = $("topologyLlamaServers");
  if (!root) return;
  const statsSlot = root.querySelector("[data-ctrl-server-stats]");
  const serverCard = document.querySelector(".topology-server-stats-card");
  if (statsSlot && serverCard) {
    if (serverCard.tagName === "DETAILS") serverCard.open = true;  // show charts, not just the summary
    statsSlot.appendChild(serverCard);
  }
  const gpuSlot = root.querySelector("[data-ctrl-gpu-telemetry]");
  const gpuCard = document.querySelector(".topology-gpu-history-card");
  if (gpuSlot && gpuCard) gpuSlot.appendChild(gpuCard);
}

// Show/hide the mounted Server-telemetry charts under the controller's
// "Servers" header (state persisted so it survives re-renders).
export function toggleCtrlServerStats(btn) {
  const slot = $("topologyLlamaServers")?.querySelector("[data-ctrl-server-stats]");
  if (!slot) return;
  const willOpen = slot.hasAttribute("hidden");
  if (willOpen) slot.removeAttribute("hidden"); else slot.setAttribute("hidden", "");
  btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
  const caret = btn.querySelector(".node-subtitle-caret");
  if (caret) caret.textContent = willOpen ? "▾" : "▸";
  localStorage.setItem("topologyCtrlServerStatsOpen", willOpen ? "1" : "0");
  requestAnimationFrame(drawTopologyCables);  // node height changed → reattach cables
}

// Incidents open in a modal: relocate the live incidents card into the modal
// body (it keeps updating — renderTopologyIncidents targets it by id), park it
// back home on close.
export function openIncidentsModal() {
  const overlay = $("incidentsModalOverlay");
  const body = $("incidentsModalBody");
  const card = document.querySelector(".topology-incidents-card");
  if (!overlay || !body || !card) return;
  _incidentsModalOpen = true;
  body.appendChild(card);
  overlay.hidden = false;
  renderTopologyIncidents();
}
export function closeIncidentsModal() {
  _incidentsModalOpen = false;
  const overlay = $("incidentsModalOverlay");
  if (overlay) overlay.hidden = true;
  const home = document.querySelector(".lane-stats");
  const card = document.querySelector(".topology-incidents-card");
  if (home && card) home.appendChild(card);
}

// ── Models directory bar ──────────────────────────────────────────────────────
export let _modelsDirEditing = false;

export function renderModelsBar() {
  const el = $("topologyModelsBar");
  if (!el) return;
  const dir = effectiveModelsDir(state?.config || {});
  if (_modelsDirEditing) {
    el.innerHTML = `
      <span class="models-bar-icon" aria-hidden="true">📁</span>
      <input id="modelsDirEditInput" class="models-bar-input" value="${escapeHtml(dir)}" placeholder="/path/to/models" autocomplete="off" spellcheck="false">
      <button class="models-bar-btn models-bar-save" type="button" title="${escapeHtml(t("savePath"))}">${escapeHtml(t("save"))}</button>
      <button class="models-bar-btn models-bar-cancel" type="button" title="${escapeHtml(t("cancel"))}">✕</button>`;
    const input = el.querySelector("#modelsDirEditInput");
    input?.focus();
    input?.select();
    el.querySelector(".models-bar-save")?.addEventListener("click", async () => {
      const newVal = input?.value?.trim() || "";
      _modelsDirEditing = false;
      await saveModelsDir(newVal);
    });
    el.querySelector(".models-bar-cancel")?.addEventListener("click", () => {
      _modelsDirEditing = false;
      renderModelsBar();
    });
    input?.addEventListener("keydown", async (e) => {
      if (e.key === "Enter") { e.preventDefault(); el.querySelector(".models-bar-save")?.click(); }
      if (e.key === "Escape") { e.preventDefault(); el.querySelector(".models-bar-cancel")?.click(); }
    });
  } else {
    const dirDisplay = dir || "(not set)";
    el.innerHTML = `
      <span class="models-bar-icon" aria-hidden="true">📁</span>
      <span class="models-bar-label">${escapeHtml(t("topologyModelsLabel"))}</span>
      <code class="models-bar-path${dir ? "" : " models-bar-empty"}" title="${escapeHtml(dir)}">${escapeHtml(dirDisplay)}</code>
      <button class="models-bar-btn models-bar-edit" type="button" title="${escapeHtml(t("editModelsDir"))}">✎</button>
      <span class="inline-tip help-tip models-bar-tip" tabindex="0" aria-label="${escapeHtml(t("modelsLayoutHint"))}">?<span class="tooltip" role="tooltip">${escapeHtml(t("modelsLayoutHint"))}</span></span>
      <a class="models-bar-btn models-bar-hf" href="/hf" target="_blank" rel="noopener" title="${escapeHtml(t("hfBrowserTitle"))}">HF ↗</a>`;
    el.querySelector(".models-bar-edit")?.addEventListener("click", () => {
      _modelsDirEditing = true;
      renderModelsBar();
    });
  }
}

export async function saveModelsDir(newPath) {
  try {
    const config = Object.assign({}, state?.config || {}, { LLAMA_MODELS_DIR: newPath });
    const data = await api("/api/config", {
      method: "POST",
      body: JSON.stringify({ config, restart: false }),
    });
    setState(data.state);
    renderModelsBar();
    // Refresh model dropdowns everywhere since dir changed
    renderModelSelects("");
  } catch (e) {
    toast(String(e));
    renderModelsBar();
  }
}

