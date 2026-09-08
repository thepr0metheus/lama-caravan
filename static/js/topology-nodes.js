// Host-centric nodes view: server cards, telemetry mounts, incidents, models bar.
import { drawTopologyCables } from "./cables.js";
import { CONTROLLER_HOST_ID } from "./constants.js";
import { nodeTelemetryRowsHtml, renderTopologyIncidents } from "./charts.js";
import { effectiveModelsDir } from "./command-preview.js";
import { badge, mbadge, modelsByPath, renderModelSelects } from "./form.js";
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
  _reservingCells,
  _pendingCellActions,
  _stoppingCells,
  _stoppingHosts,
  nextTopologyCellPort,
  nodeStartingCardHtml,
  remoteStartPending,
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
import { runnerRegistry } from "./llama-edit.js";
import { jobsForCell } from "./model-jobs.js";
import { $, api, copyText, escapeHtml, inferSpecType, toast } from "./utils.js";

// ── Host-centric node view (Stage 3a) ────────────────────────────────────────
// Known safetensors format folder names (mirror of _ST_FORMAT_HINTS in
// caravan/admin/models.py) — used to read <Model>/<author>/<FORMAT> paths.
// NOT "ST": that is the badge the backend shows when it recognises none of
// these, never a directory anyone writes. Listing it here made the mirror
// strip a segment the backend would have kept, so the two would have disagreed
// about the model's own name. check_command_mirrors keeps the lists equal.
const _ST_FMT = new Set(["NVFP4", "MXFP4", "AWQ", "GPTQ", "AUTOROUND", "FP8",
                         "INT4", "W4A16", "BNB", "BF16", "FP16", "FP32"]);

// Runner identity chip shown IN the model-name row of every cell card —
// replaces the generic "chip" svg so the engine is readable at a glance.
function runnerChipHtml(runnerId) {
  const meta = { "llama-server": ["🦙", "llama.cpp"], "vllm": ["⚡", "vLLM"],
                 "whisper": ["🎙", "whisper"], "moonshine": ["🌙", "moonshine"],
                 "transcribe": ["📝", "transcribe.cpp"],
                 "seamless": ["🌐", "seamless"],
                 "translate": ["🔄", "nllb"],
                 "custom": ["🛠", "command"] }[runnerId];
  if (!meta) return "";
  return `<span class="mbadge mbadge-cmd node-runner-chip">${meta[0]} ${meta[1]}</span>`;
}

//: Same marks and the same words as the picker's chips — one vocabulary, so a
//: model chosen as "🎧 speech → text" is still that after it starts.
const JOB_MARKS = { llm: "\u{1F4AC}", embed: "\u{1F9EC}", asr: "\u{1F3A7}", tts: "\u{1F50A}",
                    translate: "\u{1F310}", "speech-translate": "\u{1F3A7}\u{1F310}" };
const JOB_LABELS = { llm: "jobLlm", embed: "jobEmbed", asr: "jobAsr", tts: "jobTts",
                     translate: "jobTranslate", "speech-translate": "jobSpeechTranslate" };
//: Spelled out, not composed — see the same table in form.js.
const JOB_HOOKS = { llm: "cell-job-llm", embed: "cell-job-embed", asr: "cell-job-asr", tts: "cell-job-tts",
                    translate: "cell-job-translate",
                    "speech-translate": "cell-job-speech-translate" };

// What the cell DOES, beside the chip that says what RUNS it.
//
// The live `kinds` outrank the runner table, which is the only way a TTS cell
// can be named as one: voice cloning runs as a typed command, so its runner is
// "custom" and the table knows nothing about it. A cell whose job cannot be
// named draws no chip rather than a guessed one.
function jobChipsHtml(runnerId, cellMeta, cfg) {
  // An embedding server answers /v1/embeddings and returns vectors; llama.cpp
  // cannot serve chat from the same instance. The runner is still llama-server,
  // so the runner table alone called it a chat model — and a live
  // Qwen3-Embedding cell wore "💬 LLM" on the board until this branch existed.
  const embeds = String((cfg || {}).ENABLE_EMBEDDINGS || "").trim().toLowerCase();
  if (embeds && !["", "0", "no", "false", "off"].includes(embeds)) {
    return `<span class="mbadge mbadge-job node-job-chip" data-t="cell-job-embed">${
      JOB_MARKS.embed} ${escapeHtml(t(JOB_LABELS.embed))}</span>`;
  }
  return jobsForCell(runnerId, (cellMeta || {}).kinds || []).map((job) => {
    const key = JOB_LABELS[job];
    if (!key) return "";
    return `<span class="mbadge mbadge-job node-job-chip" data-t="${JOB_HOOKS[job]}">${
      JOB_MARKS[job] || ""} ${escapeHtml(t(key))}</span>`;
  }).join("");
}

// A cell explicitly pinned to the GPU — TTS_DEVICE/DEVICE=cuda|gpu or
// --device cuda in its ENV/COMMAND. The pin is authoritative even when the cell
// currently holds no VRAM: with an explicit pin the launcher either lands on the
// GPU or fails outright, it never quietly falls back. Measured VRAM alone is not
// enough to call a cell "CPU" — a model reads its weights off disk for the first
// 13-18s and allocates nothing on the card in that window, and the host's
// GPU→process mapping refreshes on its own beat after that.
function cellPinnedToGpu(srv) {
  const cfg = (srv && srv.slotConfig) || {};
  const envCmd = `${String(cfg.ENV || "")}\n${String(cfg.COMMAND || "")}`;
  return /(?:^|[\s;,])(?:TTS_DEVICE|DEVICE)=(?:cuda|gpu)\b|--device[=\s]+(?:cuda|gpu)\b/i.test(envCmd);
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
  // VRAM the card holds for something that is NOT a fleet cell — a training run,
  // another app. Below a small floor it is driver/graphics overhead, not a job,
  // so the card still reads "idle". Above it, "idle" was a lie: the card is busy,
  // just not with us. The backend split `used` using the compute-app pids.
  const nonFleet = Number(g.nonFleetUsedMiB || 0);
  const nonFleetPct = total > 0 ? Math.min(100, Math.round((nonFleet / total) * 100)) : 0;
  const nonFleetGb = (nonFleet / 1024).toFixed(1);
  const hasOutside = nonFleet >= 64;   // MiB floor
  const outsideLabel = `▶ ${t("topologyGpuOutside")} · ${nonFleetGb} GB`;
  return `
    <div class="node-gpu-row" data-gpu-row="${escapeHtml(`${node.id}:${g.index}`)}">
      <div class="node-gpu-head">
        <strong>GPU ${escapeHtml(String(g.index ?? "?"))}</strong>
        <span class="node-gpu-name">${escapeHtml(g.name || "GPU")}</span>
        <span class="node-gpu-util" data-live-gpuutil>${escapeHtml(String(util))}% · ${escapeHtml(String(temp))}°C · ${escapeHtml(String(power))}W</span>
      </div>
      <div class="node-vram-bar" data-live-gpuvrambar data-vram-total="${escapeHtml(String(total))}"
           title="${usedGb} / ${totalGb} GB"><span style="width:${pct}%"></span><i class="node-vram-outside" data-live-gpuoutsidebar style="width:${nonFleetPct}%"${hasOutside ? "" : " hidden"}></i><i class="node-vram-slice" hidden></i></div>
      <div class="node-gpu-meta">
        <span data-live-gpuvram>VRAM ${usedGb} / ${totalGb} GB</span>
        <span data-live-gpuwho>${ports.length
          ? `<span class="node-gpu-ports">▶ ${ports.map((p) => escapeHtml(String(p))).join(", ")}</span>`
          : hasOutside
            ? `<span class="node-gpu-outside" title="${escapeHtml(t("topologyGpuOutsideHint"))}">${escapeHtml(outsideLabel)}</span>`
            : `<span class="topology-muted">${escapeHtml(t("topologyGpuIdle"))}</span>`}</span>
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
  // No reason at all is itself a fact worth stating. The log reader now returns
  // "" rather than blaming a harmless warning line, so a crash whose cause is
  // not in the log reaches here empty — and the card used to render red with no
  // panel, which reads as "we know something and won't say". Say "unknown" and
  // point at the log instead.
  if (!raw) return { friendly: t("llamaErrUnknown"), hint: t("llamaErrUnknownHint"), raw: "" };
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

// Launch file roles — in the operator's words, not the config's field names.
function roleName(role) {
  if (role === "mmproj") return t("cellLaunchFileMmproj");
  if (role === "draft") return t("cellLaunchFileDraft");
  return t("cellLaunchFileModel");
}

function launchRoleNames(roles) {
  return roles.map(roleName).join(", ");
}

// A suffix on the chip — only when it's NOT the weights: "⇪ model re-issued"
// on a card with no further detail reads as "the model has been updated",
// and the operator goes looking for one.
function launchFilesSuffix(roles) {
  const others = roles.filter((r) => r !== "model");
  if (!others.length) return "";
  return ` · ${escapeHtml(launchRoleNames(others))}`;
}

export function nodeServerCardHtml(node, s) {
  const isStopping = !s.isController && _stoppingHosts.has(node.id);
  const port = s.port;
  const slotHostId = s.isController ? CONTROLLER_HOST_ID : node.id;
  const slotKey = `${slotHostId}:${port}`;
  const cellKey = slotKey;  // alias used in controls + config block
  const isDeleting = _deletingSlots.has(slotKey);
  const pendingCellAction = _pendingCellActions.get(cellKey) || "";
  const isCellStopping = (s.isSlot && _stoppingCells.has(cellKey)) || pendingCellAction === "stop";
  const isNewReserved = _newReservedCells.has(slotKey);
  // If a start was just submitted for this host and the slot still shows "stopped",
  // treat it as "starting" so the user can't accidentally click Start again.
  // `remoteStartPending`, not `.has()`: a record that timed out is still in the
  // map, waiting to be dismissed, and asking only whether it EXISTS kept every
  // stopped cell of that host reading "starting" forever.
  const hasPendingStart = (!s.isController && remoteStartPending(node.id)) || pendingCellAction === "start";
  const rawPhase = isStopping ? "stopping" : (s.phase || (s.status && s.status.phase) || (s.isController ? "running" : "stopped"));
  const phase = (rawPhase === "stopped" && hasPendingStart) ? "starting" : rawPhase;
  const running = phase === "running";
  const isReserved = phase === "reserved";
  const isError = phase === "error";
  // Broken = the wrapper process is up and its health path answers WITH AN
  // ERROR (engine never initialised). Deliberately not lumped into isError:
  // error behaves like stopped (Start available), while a broken cell is a
  // running process — Stop must work and Start must not.
  const isBroken = phase === "broken";
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
    // "into VRAM" is a lie on a CPU cell — it loads into RAM. The full isCpuCell
    // is derived further down (it needs the live GPU list), so the two cases
    // that matter while WARMING are read straight off the cell config here.
    const _wcfg = s.slotConfig || {};
    const _warmCpu = String(_wcfg.N_GPU_LAYERS ?? "").trim() === "0"
      || String(_wcfg.RUNNER || "").toLowerCase() === "moonshine";
    const _warmKey = _warmCpu ? "topologyRemoteWarmingRam" : "topologyRemoteWarming";
    statusRow = _msl("", `${_mslSpin(false)}<span class="msl-bar indeterminate"><span></span></span><span class="msl-text">${escapeHtml(t(_warmKey))}</span>${_prevErrChip(s)}`);
  } else if (isBroken) {
    // The diagnosis is the cell's own health body — a string, not the
    // journal-classified object the isError branch below reads.
    const bErr = String(s.status?.error || "");
    statusRow = _msl("msl-err", `<span class="msl-err-icon" aria-hidden="true">💔</span>`
      + `<span class="msl-text" data-t="cell-broken-error" data-t-id="${escapeHtml(`${slotHostId}:${port}`)}"`
      + ` title="${escapeHtml(bErr)}">${escapeHtml(t("failed"))}: ${escapeHtml(bErr.slice(0, 140))}${bErr.length > 140 ? "…" : ""}</span>`);
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
  const healthCls = running ? "running" : (isBroken ? "error" : (isStopped ? "" : "loading"));
  // Compact model block (name + quant/size/vision chips) — click to drill in.
  const parsed = parseModelName(s.model) || {};
  const hasVision = !!s.mmproj;
  // Authoritative input modalities from the running server's /props, when known.
  const mods = s.modalities || null;
  // Detect built-in MTP: path component ends with "-mtp" (e.g. "qwen3.6-27b-mtp/...")
  const _mtpRe = /-mtp(?:[^a-z0-9]|$)/i;
  const hasMtpBuiltin = _mtpRe.test(s.model || "") || _mtpRe.test(s.modelPath || "");
  const hasMtp = !!s.specDraft || hasMtpBuiltin || (s.specType || "").toLowerCase() === "draft-mtp";
  // For configured (stopped) slot cells pull key params from slotConfig as fallback chips
  const _scfg = s.slotConfig || {};
  // A speech cell's window is an AUDIO length, not a token count. Its config
  // still carries a llama CTX_SIZE it will never use, and rendering that as
  // "🪟 100k" put a confident, precise, entirely fictional number on the card.
  // The cell reports the real one on its health path, so prefer that and show
  // nothing rather than the fiction when it is unavailable.
  const _audioMs = Number((s.cellMeta || {}).maxAudioMs || 0);
  // Only llama and vLLM measure their work in tokens. Every other runner keeps
  // an inherited CTX_SIZE in its saved config that it will never read, so an
  // allow-list of token cells is the safe direction: a runner added later gets
  // no window chip until someone decides it has one, instead of silently
  // inheriting a precise, fictional "🪟 100k".
  const _runner = String(_scfg.RUNNER || (String(_scfg.CELL_KIND || "").toLowerCase() === "command" ? "custom" : "llama-server")).toLowerCase();
  // The allow-list moved to the runner classes on the controller and arrives
  // in state.runners; keeping a copy here is how the two came to disagree.
  const _isTokenCell = !_runner
    || !!runnerRegistry().find((r) => r.id === _runner)?.tokenContext;
  const _isSpeechCell = _audioMs > 0
    || ["transcribe", "whisper", "moonshine", "seamless"].includes(_runner);
  const ctxChip = _isSpeechCell
    ? (_audioMs > 0 ? mbadge("ctx", `🪟 ${Math.round(_audioMs / 1000)} s`, t("audioWindowChipTitle")) : "")
    : (s.ctxMax
        ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(s.ctxMax || 0))}`, t("topologyCtxUsageTip") || "Context window")
        : "");
  // What the weights were trained with, right after the model's name: a fact
  // about the model, not about this cell — the cell's own window is the 🪟
  // chip below, and the two differ on this fleet (131k trained, 60k served).
  // Never a substitute for 🪟: a card with no served window shows none.
  const trainedChip = (_isTokenCell && !_isSpeechCell && Number(s.ctxTrained) > 0)
    ? mbadge("trained", `🎓 ${escapeHtml(formatCtxTokens(Number(s.ctxTrained)))}`, t("trainedCtxChipTitle"))
    : "";
  const slotCtxChip = (_isTokenCell && !_isSpeechCell && !s.ctxMax && _scfg.CTX_SIZE)
    ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(Number(_scfg.CTX_SIZE)))}`) : "";
  const _benchKey = s.model ? (_modelBenchKey(s.model) || "") : "";
  const _bdata = _benchKey ? serverBenchCache.get(_benchKey) : null;
  const _aaScore = _bdata?.scores?.aa_intelligence;
  const benchChip = _aaScore != null ? mbadge("bench", `🧠 ${_aaScore}`) : "";
  if (s.model) fetchServerBenchIfNeeded(s.model);
  // What language a translating cell WRITES. The card carried no language at
  // all, so two cells serving different languages off the same checkpoint were
  // indistinguishable — and the one fact that tells them apart is the one the
  // cell already reports. Taken from the live report first, falling back to the
  // saved config so a stopped cell still says what it is configured for.
  const _tgtLang = String((s.cellMeta || {}).targetLang || "").trim();
  const langChip = _tgtLang
    ? mbadge("it", `🌐 ${escapeHtml(_tgtLang)}`, t("targetLangChipTitle"))
    : "";
  const chips = [
    langChip,
    parsed.quant && _isTokenCell ? mbadge("quant", `🎛 ${escapeHtml(parsed.quant)}`) : "",
    parsed.size ? mbadge("size", `⚖ ${escapeHtml(parsed.size)}`) : "",
    parsed.variant && _isTokenCell ? mbadge("it", `🤖 ${escapeHtml(parsed.variant)}`) : "",
    // Prefer real /props modalities; fall back to the mmproj-presence heuristic.
    mods ? [
      mods.vision ? mbadge("vision", "👁 vision") : "",
      mods.audio ? mbadge("audio", "🎙 audio") : "",
      mods.video ? mbadge("video", "🎬 video") : "",
    ].join("") : (hasVision && _isTokenCell ? mbadge("mmproj", "📷 mmproj") : ""),
    hasMtp && _isTokenCell ? mbadge("mtp", "⚡ mtp") : "",
    ctxChip || slotCtxChip,
    benchChip,
  ].filter(Boolean).join("");
  // Schedule chip: the cell is started/stopped by a time window.
  const schedChip = (s.schedule && s.schedule.enabled)
    ? mbadge("sched", `⏱ ${escapeHtml(s.schedule.start)}–${escapeHtml(s.schedule.stop)}`,
             t("schedChipTitle"))
    : "";
  // The running process is older than the cell server the controller ships. The
  // file next to it is already current — a restart is what picks it up — so no
  // other chip on this card can show the gap. Command cells only: a llama or
  // vLLM cell runs a binary, whose staleness has its own banner.
  // The cell HAS CRASHED. systemd brings it back up, and a minute later the
  // card is "running" again — an evening with three crashes looked like
  // smooth operation (2026-09-06: Xid 8, "CUDA error: the launch timed
  // out"). The count is kept since the last MANUAL start: restart it
  // yourself and the counter resets, which is honest.
  const crash = s.crash && Number(s.crash.count) > 0 ? s.crash : null;
  const crashChip = crash
    ? mbadge("crashed", `💥 ${escapeHtml(t("cellCrashedChip", { count: String(crash.count) }))}`,
             t("cellCrashedTip", { count: String(crash.count),
                                   at: String(crash.at || "?"),
                                   reason: String(crash.reason || "?") }), "cell-crashed")
    : "";
  const staleSrcChip = (s.cellMeta || {}).sourceState === "stale"
    ? mbadge("stale-src", `⇪ ${escapeHtml(t("cellSourceStaleChip"))}`,
             t("cellSourceStaleTip"), "cell-source-stale")
    : "";
  // The same ⇪ as the stale-binary chip, but about the WEIGHTS: a different
  // file sits under this name on HF now. An empty field means "not
  // checked", and it stays silent: a "matches" icon over an unchecked file
  // would be exactly the defect the watcher exists to fix.
  // The file on disk has already been swapped, but the process is still
  // running the old weights — it holds the INODE, not the name. This isn't
  // "broken", it's "restart whenever convenient", and that has to be said
  // plainly: silence here reads as "already updated".
  // A launch involves not one file but up to three: the weights, mmproj, and
  // the draft. All of them come from HF and all get re-issued, so the chip
  // speaks about ANY of them and names which one — otherwise the operator
  // goes looking for an update that isn't there.
  const launchNewer = Array.isArray(s.launchDiskNewer) ? s.launchDiskNewer : [];
  const diskNewerFiles = launchNewer.length ? launchNewer : (s.modelDiskNewer ? ["model"] : []);
  const diskNewerChip = diskNewerFiles.length
    ? mbadge("disk-newer",
             `⟳ ${escapeHtml(t("cellModelDiskNewerChip"))}${launchFilesSuffix(diskNewerFiles)}`,
             `${t("cellModelDiskNewerTip")}\n${t("cellLaunchFilesLine", { files: launchRoleNames(diskNewerFiles) })}`,
             "cell-model-disk-newer")
    : "";
  const staleRows = (Array.isArray(s.launchFresh) ? s.launchFresh : [])
    .filter((r) => r && (r.state === "size" || r.state === "date"));
  // A fallback for a source that doesn't yet report a list: the card must
  // not go blind just because that field hasn't arrived.
  const staleRoles = staleRows.length
    ? staleRows.map((r) => r.role)
    : ((s.modelFresh === "size" || s.modelFresh === "date") ? ["model"] : []);
  const staleModelChip = staleRoles.length
    ? mbadge("stale-model",
             `⇪ ${escapeHtml(t("cellModelStaleChip"))}${launchFilesSuffix(staleRoles)}`,
             `${t("cellModelStaleTip")}\n${t("cellLaunchFilesLine", {
               files: staleRows.length
                 ? staleRows.map((r) => `${roleName(r.role)} — ${r.file}`).join(", ")
                 : launchRoleNames(staleRoles),
             })}`,
             "cell-model-stale")
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
  const cfgSaysGpu = cellPinnedToGpu(s);
  // Device chip carries WHERE (⚡ GPU0); the memory badge carries HOW MUCH and
  // sits next to the model name — live VRAM held by the cell's processes
  // (multi-GPU sums up, the per-GPU split lives in the tooltip).
  const _gpuList = (s.gpuIndexes || []).map((i) => ({ i, mib: Number((s.gpuMem || {})[String(i)] || 0) }));
  const devGpuTxt = _gpuList.map((g) => `GPU${g.i}`).join(" · ");
  const _vramMib = _gpuList.reduce((a, g) => a + g.mib, 0);
  const _vramSplit = _gpuList.filter((g) => g.mib).map((g) => `GPU${g.i}: ${(g.mib / 1024).toFixed(1)} GiB`).join(" · ");
  // Hovering the card lights up this cell's slice of the node's VRAM bar. The
  // bar knows only the node-wide total in use, so the card has to carry its own
  // per-GPU claim ("<gpuIndex>:<MiB>") for the hover handler to size the band.
  const _vramClaim = running
    ? _gpuList.filter((g) => g.mib > 0).map((g) => `${g.i}:${g.mib}`).join(",")
    : "";
  const memBadge = (running && _vramMib)
    ? mbadge("vram", `${escapeHtml((_vramMib / 1024).toFixed(1))}G`, `${t("vramChipTitle")}${_vramSplit ? ` — ${_vramSplit}` : ""}`)
    : ((!running && Number(s.modelSizeBytes) > 0)
        ? mbadge("vram-est", `≈${escapeHtml((Number(s.modelSizeBytes) / 2 ** 30).toFixed(1))}G`, t("vramEstChipTitle"))
        : "");
  // One truth for the chip AND the card accent (.cpu-cell → blue instead of
  // green/amber): running with no GPU memory AND no GPU pin, or stopped with
  // CPU pinned in the config. The pin has to count — measuring VRAM alone
  // labeled a GPU-pinned cell "CPU" for the whole window before it allocates,
  // which reads as the Device setting having been ignored.
  // Stopped without a pin: llama (with offload) and vLLM are GPU by nature,
  // whisper's launcher is CUDA-first; moonshine is CPU-only by design (its ONNX
  // models have no GPU build), so it deliberately stays OUT of
  // runnerDefaultsGpu AND counts as a CPU cell even without a TTS_DEVICE=cpu
  // pin; a bare custom command resolves its device at start (VRAM probe) → "auto".
  const runnerDefaultsGpu = _runner === "llama-server" || _runner === "vllm" || _runner === "whisper"
    || _runner === "transcribe";
  const runnerCpuOnly = _runner === "moonshine";
  const isCpuCell = (running && !devGpuTxt && !cfgSaysGpu)
    || (!running && (cfgSaysCpu || runnerCpuOnly) && !isReserved)
    || (running && runnerCpuOnly);
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
      ${/* The NAME owns this line. It used to share row 1 with three chips and
             was left 38-72px wide: on a 31-card board 20 names wrapped to two
             ragged lines. The name is what the operator is scanning for; the
             chips describe it and belong beneath it. The trained-context number
             stays pinned right as a fixed anchor — one thing that can run, one
             thing that never moves. */""}
      <div class="node-model-ident">
        <strong class="node-model-name" title="${escapeHtml(s.modelPath || s.model)}"><span>${escapeHtml(parsed.label || s.model)}</span></strong>${trainedChip}
      </div>
      ${/* One ordered row, always the same sequence: what it DOES, what RUNS it,
             WHERE it computes, how MUCH it takes, then the file's own facts, and
             warnings last. Two cards of the same kind now read in the same
             order, which is what makes a board scannable at all. */""}
      ${statusRow || (jobChipsHtml(_runner, s.cellMeta, _scfg) || deviceChip || chips || schedChip || diskNewerChip || staleModelChip || crashChip ? `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml(_runner, s.cellMeta, _scfg)}${runnerChipHtml(_runner)}${deviceChip}${memBadge}${chips}${schedChip}${diskNewerChip}${staleModelChip}${crashChip}</span></div>` : "")}
    </div>` : "";
  const emptyCellBlock = isReserved ? `
    <div class="node-model-block node-model-block-empty">
      <div class="node-model-ident">
        ${topologyModelIcon()}
        <strong class="node-model-name"><span>:${escapeHtml(String(port))}</span></strong>
        <span class="node-reserved-tag">${escapeHtml(t("topologyReservedCellLabel"))}</span>${schedChip}
      </div>
      ${statusRow}
    </div>` : "";
  const isCmdCell = String(_scfg.CELL_KIND || "").toLowerCase() === "command";
  const cmdText = String(_scfg.COMMAND || "").replace(/^\s*exec\s+/, "").trim();
  const commandBlock = isCmdCell ? `
    <div class="node-model-block" role="button" tabindex="0"
         data-node-detail="${escapeHtml(node.id)}:${escapeHtml(String(port))}" title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      ${/* A typed command is the longest text on the board and was the most
             squeezed of all; here it gets the whole line, and the rest of it
             runs past on hover. */""}
      <div class="node-model-ident">
        <strong class="node-model-name" title="${escapeHtml(cmdText)}"><span>${escapeHtml(cmdText || t("commandCellFallback"))}</span></strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml("custom", s.cellMeta, _scfg)}${runnerChipHtml("custom")}${deviceChip}${memBadge}${_scfg.HEALTH_PATH ? mbadge("cmd", `❤ ${escapeHtml(_scfg.HEALTH_PATH)}`) : ""}${mbadge("ctx", `:${escapeHtml(String(port))}`)}${schedChip}${staleSrcChip}${crashChip}</span></div>`}
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
      <div class="node-model-ident">
        <strong class="node-model-name" title="${escapeHtml(vllmModel || vllmName)}${vllmAlias ? escapeHtml(` · served as ${vllmAlias}`) : ""}"><span>${escapeHtml(vllmName)}</span></strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml("vllm", s.cellMeta, _scfg)}${runnerChipHtml("vllm")}${deviceChip}${memBadge}${vllmFmt ? mbadge("quant", `🎛 ${escapeHtml(vllmFmt)}`) : ""}${s.vllmStats ? mbadge("cmd", `▶ ${s.vllmStats.requestsRunning}${s.vllmStats.requestsWaiting ? " ⏳" + s.vllmStats.requestsWaiting : ""}`, "running / queued requests") : ""}${s.vllmStats && s.vllmStats.genTps != null ? mbadge("bench", `${formatTps(s.vllmStats.genTps)} t/s`) : ""}${mbadge("cmd", "❤ /v1/models")}${_scfg.MAX_MODEL_LEN ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(Number(_scfg.MAX_MODEL_LEN)))}`) : ""}${mbadge("ctx", `:${escapeHtml(String(port))}`)}${schedChip}${staleSrcChip}${crashChip}</span></div>`}
    </div>` : "";
  // whisper runner cell: the "model" is a faster-whisper size name.
  const isWhisperCell = String(_scfg.RUNNER || "").toLowerCase() === "whisper";
  const whisperSize = String(_scfg.WHISPER_MODEL || "").trim() || "large-v3";
  const whisperBlock = (isWhisperCell && !s.model) ? `
    <div class="node-model-block" role="button" tabindex="0"
         data-node-detail="${escapeHtml(node.id)}:${escapeHtml(String(port))}" title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-ident">
        <strong class="node-model-name" title="faster-whisper ${escapeHtml(whisperSize)}"><span>${escapeHtml(whisperSize)}</span></strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml("whisper", s.cellMeta, _scfg)}${runnerChipHtml("whisper")}${deviceChip}${memBadge}${mbadge("cmd", "❤ /health")}${mbadge("ctx", `:${escapeHtml(String(port))}`)}${schedChip}${staleSrcChip}${crashChip}</span></div>`}
    </div>` : "";
  // moonshine runner cell: the "model" is a language code, CPU-only.
  const isMoonshineCell = String(_scfg.RUNNER || "").toLowerCase() === "moonshine";
  const moonshineLang = String(_scfg.MOONSHINE_MODEL || "").trim().toLowerCase() || "en";
  const moonshineBlock = (isMoonshineCell && !s.model) ? `
    <div class="node-model-block" role="button" tabindex="0"
         data-node-detail="${escapeHtml(node.id)}:${escapeHtml(String(port))}" title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-ident">
        <strong class="node-model-name" title="moonshine ${escapeHtml(moonshineLang)}"><span>${escapeHtml(moonshineLang)}</span></strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml("moonshine", s.cellMeta, _scfg)}${runnerChipHtml("moonshine")}${deviceChip}${memBadge}${mbadge("cmd", "❤ /health")}${mbadge("ctx", `:${escapeHtml(String(port))}`)}${schedChip}${staleSrcChip}${crashChip}</span></div>`}
    </div>` : "";
  const bodyBlock = modelBlock || vllmBlock || whisperBlock || moonshineBlock || commandBlock || emptyCellBlock;
  // No model/command block to host the status (e.g. a bare stopped server) —
  // fall back to the old below-the-body progress panel.
  const progressPanel = (!bodyBlock && statusRow)
    ? `<div class="topology-runtime-panel node-progress-panel">${statusRow}</div>`
    : "";
  const isConfiguredCell = phase === "stopped" && !isReserved && !isError;
  const cardCls = [
    isStopping ? "stopping" : (isDeleting ? "deleting" : (running ? "running" : ((isError || isBroken) ? "error" : (isStopped ? (isConfiguredCell ? "configured-cell" : "stopped") : "loading")))),
    isReserved ? "reserved-cell" : "",
    isNewReserved ? "reserved-new" : "",
    isCpuCell ? "cpu-cell" : "",
  ].filter(Boolean).join(" ");
  const pillPhase = isStopping ? "stopping" : (running ? "running" : ((isError || isBroken) ? "failed" : (phase === "stopped" ? "stopped" : (isWarming ? "warming" : "loading"))));
  // Lifecycle breadcrumb — reserved(0) → configured(1) → starting(2) → running(3)
  const lcIdx = (running || isStopping || isBroken) ? 3 : (isReserved ? 0 : (isStopped || isError ? 1 : 2));
  const lcActiveStep = isStopping ? "stopping" : ((isError || isBroken) ? "error" : (running ? "running" : (isReserved ? "reserved" : (phase === "stopped" ? "configured" : "loading"))));
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
    const cfgAttrs = `data-t="cell-configure" data-t-id="${escapeHtml(cellHostId)}:${escapeHtml(String(port))}" aria-label="${escapeHtml(t("nodeConfigure"))}: ${escapeHtml(cellHostId)}:${escapeHtml(String(port))}" data-node-cell-start="${escapeHtml(s.isController ? CONTROLLER_HOST_ID : node.id)}" data-node-cell-port="${escapeHtml(String(port))}" data-node-role="${escapeHtml(node.role)}"`;

    // ✕ delete — active only when reserved / stopped / error
    const canDelete = (isReserved || phase === "stopped" || isError) && !isDeleting && !isCellBusy;
    const delBtn = isDeleting
      ? `<button class="node-action-btn muted" type="button" disabled title="${escapeHtml(t("removingSlotLabel"))}"><span class="topology-spinner stopping-spinner" aria-hidden="true"></span><span class="nab-lbl">${escapeHtml(t("deleteAction"))}</span></button>`
      : `<button class="node-action-btn ${canDelete ? "del" : "muted"}" type="button"
           ${canDelete ? `data-t="cell-delete" data-t-id="${escapeHtml(cellHostId)}:${escapeHtml(String(port))}" data-node-slot-del="${escapeHtml(cellHostId)}:${escapeHtml(String(port))}"` : "disabled"}
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
    // The confirm has to know what it is starting: a command-path cell runs a
    // command, and its "model name" row holds that command line — only the
    // render knows the runner, so hand it to the click handler.
    const cellRunner = isCmdCell ? "custom"
      : (String(_scfg.RUNNER || "").toLowerCase() || "llama-server");
    const playBtn = `<button class="node-action-btn ${canPlay ? "ok" : "muted"}" type="button"
        ${canPlay ? `data-t="cell-start" data-t-id="${escapeHtml(cellHostId)}:${escapeHtml(String(port))}" data-node-cell-launch="${escapeHtml(cellHostId)}" data-node-cell-port="${escapeHtml(String(port))}" data-node-cell-runner="${escapeHtml(cellRunner)}"` : "disabled"}
        title="${escapeHtml(canPlay ? t("nodeStartServer") : (isReserved ? t("nodeConfigureFirst") : t("nodeNotStopped")))}">▶<span class="nab-lbl">${escapeHtml(t("start"))}</span></button>`;

    // ⏹ stop — active when starting or running; spinner while stopping
    const canStop = !isStopped && !isDeleting && !isCellBusy;
    const stopBtn = isCellStopping
      ? `<button class="node-action-btn muted" type="button" disabled title="${escapeHtml(t("nodeStoppingTitle"))}"><span class="topology-spinner stopping-spinner" aria-hidden="true"></span><span class="nab-lbl">${escapeHtml(t("stop"))}</span></button>`
      : `<button class="node-action-btn ${canStop ? "warn" : "muted"}" type="button"
           ${canStop ? `data-t="cell-stop" data-t-id="${escapeHtml(cellHostId)}:${escapeHtml(String(port))}" data-node-cell-stop="${escapeHtml(cellHostId)}" data-node-cell-port="${escapeHtml(String(port))}"` : "disabled"}
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
               data-t="cell-card" data-t-id="${escapeHtml(slotKey)}" aria-label="${escapeHtml(t("a11yCell"))} ${escapeHtml(slotKey)}" data-topology-llama="1" data-llama-port="${escapeHtml(String(port))}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, node))}"
               ${_vramClaim ? `data-cell-node="${escapeHtml(String(node.id))}" data-cell-vram="${escapeHtml(_vramClaim)}"` : ""}>
        ${running ? '<span class="cell-beam" aria-hidden="true"></span>' : ""}
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
        ${isError ? (() => {
          const err = classifyLlamaError(s.lastError);
          return `<div class="topology-remote-unreachable llama-err-block" title="${escapeHtml(s.lastError)}">
            <span class="llama-err-icon">⚠</span>
            <span class="llama-err-body">
              <span class="llama-err-friendly">${escapeHtml(err.friendly)}</span>
              ${err.hint ? `<span class="llama-err-hint">${escapeHtml(err.hint)}</span>` : ""}
              ${s.lastError ? `<span class="llama-err-raw">${escapeHtml(s.lastError)}</span>` : ""}
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
             data-t="cell-card" data-t-id="${escapeHtml(slotKey)}" aria-label="${escapeHtml(t("a11yCell"))} ${escapeHtml(slotKey)}" data-topology-llama="1" data-llama-port="${escapeHtml(String(port))}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, node))}">
      ${running ? '<span class="cell-beam" aria-hidden="true"></span>' : ""}
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
      ${isError ? (() => {
        const err = classifyLlamaError(s.lastError);
        return `<div class="topology-remote-unreachable llama-err-block" title="${escapeHtml(s.lastError)}">
          <span class="llama-err-icon">⚠</span>
          <span class="llama-err-body">
            <span class="llama-err-friendly">${escapeHtml(err.friendly)}</span>
            ${err.hint ? `<span class="llama-err-hint">${escapeHtml(err.hint)}</span>` : ""}
            ${s.lastError ? `<span class="llama-err-raw">${escapeHtml(s.lastError)}</span>` : ""}
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
  // ONE lookup, from the registry the backend derives from the runner classes.
  // This modal used to enumerate five runners by hand and draw everything else
  // as llama-server: a translate cell showed `llama-server --model … --ctx-size
  // 100000 --spec-type draft-mtp`, a command it has never run, plus a 🪟 100k
  // window for a translator that has no context window. Confidently wrong, and
  // nothing about it looked broken.
  const _runnerId = String(_scfg.RUNNER || "").trim().toLowerCase()
    || (String(_scfg.CELL_KIND || "").toLowerCase() === "command" ? "custom" : "llama-server");
  const _runnerRow = runnerRegistry().find((r) => r.id === _runnerId) || null;
  const isCmd = _runnerId === "custom";
  const isLlama = _runnerId === "llama-server";
  // CTX_SIZE is inherited by every cell config, including the ones that will
  // never read it. Only a runner that says its work is measured in tokens gets
  // the chip; an unknown runner says nothing, so it gets none.
  const _hasCtx = !!(_runnerRow ? _runnerRow.tokenContext : isLlama);
  const nsdCtxChip = !_hasCtx ? ""
    : s.ctxMax
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

  const cmdSection = (lines) => {
    const cmdText = lines.join("\n");
    const pre = lines.map((l) => `<span class="cmd-token">${escapeHtml(l)}</span>`).join("\n");
    return `<div class="nsd-cfg-section"><div class="nsd-cfg-head">COMMAND <button class="nsd-copy-btn" type="button" data-copy="${escapeHtml(cmdText)}" title="${escapeHtml(t("copyCommand"))}">⎘</button></div><pre class="command-preview nsd-cmd-pre">${pre}</pre></div>`;
  };

  // The command block. For everything except llama-server this is the line
  // start.sh actually holds, read off the file — not a mirror of the builder
  // rewritten in JS. There were four such mirrors here, one per runner someone
  // had remembered to add, and the two nobody added fell through to the llama
  // branch and were drawn as llama cells.
  const cmdBlockHtml = (() => {
    const cfg = s.slotConfig || {};
    if (!isLlama) {
      // The backend answers this for BOTH kinds of host: a controller cell from
      // its start.sh, a client cell from the same builder that hands the scout
      // its line. A custom cell's COMMAND is the last fallback — it IS the
      // config, so it is a fact and not a re-render.
      const saved = String(s.savedCommand || (isCmd ? cfg.COMMAND : "") || "")
        .trim().replace(/^\s*exec\s+/, "");
      if (!saved) {
        // Never applied, and nothing to read. Said plainly rather than guessed —
        // but only when it is TRUE: this line once appeared on client cells that
        // had been serving for hours, because it was asked for a start.sh that
        // only a controller host ever has.
        return `<div class="nsd-cfg-section"><div class="nsd-cfg-head">COMMAND</div>`
             + `<pre class="command-preview nsd-cmd-pre muted">${escapeHtml(t("cmdNotSavedYet"))}</pre></div>`;
      }
      const lines = [`export PORT=${cfg.PORT || s.port || ""}`];
      if (isCmd) {
        String(cfg.ENV || "").split(/[\n,]/).forEach((raw) => {
          const it = raw.trim(); if (!it || it.startsWith("#") || !it.includes("=")) return;
          const i = it.indexOf("="); const k = it.slice(0, i).trim();
          if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k)) return;
          lines.push(`export ${k}="${it.slice(i + 1).trim()}"`);
        });
        if (cfg.WORKDIR) lines.push(`cd ${cfg.WORKDIR}`);
      }
      lines.push(`exec ${saved}`);
      return cmdSection(lines);
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
    // Mirror config_builder.build_llama_args exactly. This preview used to print
    // --spec-type whenever the field was non-empty, while the builder emitted it
    // only alongside a draft file — so the board showed a command that was not
    // the one being run, for the single field that carries the whole speculative
    // story. Any change to the builder's spec branch belongs here too.
    const specTypeRaw = (cfg.SPEC_TYPE || "").trim().toLowerCase();
    const specType = specTypeRaw === "mtp" ? "draft-mtp" : specTypeRaw;
    const draftFile = cfg.SPEC_DRAFT_MODEL_FILE;
    if (specType.startsWith("ngram-")) {
      add("--spec-type", specType);            // drafts from the prompt; takes no draft model
    } else if (draftFile) {
      add("--spec-type", specType || inferSpecType(draftFile));
      add("--model-draft", [cfg.LLAMA_MODELS_DIR, draftFile].filter(Boolean).join("/"));
      add("--gpu-layers-draft", cfg.SPEC_DRAFT_N_GPU_LAYERS);
      add("--spec-draft-n-max", cfg.SPEC_DRAFT_N_MAX);
    } else if (specType === "draft-mtp") {
      add("--spec-type", specType);            // built-in MTP head, no draft file
      add("--spec-draft-n-max", cfg.SPEC_DRAFT_N_MAX);
    }
    // Auto-YaRN mirror: CTX_SIZE above the model's native window makes the
    // builder emit the whole recipe — the preview must say so too.
    const yarnCtx = Number(cfg.CTX_SIZE || 0);
    const yarnMeta = modelsByPath().get(cfg.MODEL_FILE || "")?.ggufMeta || {};
    const yarnNative = Number(yarnMeta.contextLength || 0);
    if (yarnCtx > yarnNative && yarnNative > 0 && yarnMeta.architecture) {
      const extra = String(cfg.EXTRA_ARGS || "");
      if (!cfg.ROPE_SCALING) add("--rope-scaling", "yarn");
      if (!cfg.ROPE_SCALE) add("--rope-scale", String(Math.ceil((yarnCtx / yarnNative) * 100) / 100));
      if (!extra.includes("--yarn-orig-ctx")) add("--yarn-orig-ctx", String(yarnNative));
      if (!extra.includes("--override-kv"))
        add("--override-kv", `${yarnMeta.architecture}.context_length=int:${yarnCtx}`);
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
            : _runnerRow && _runnerRow.modelField && !isLlama
            // Each runner keeps its model in its OWN field; reading MODEL_FILE
            // for all of them is what once labelled an NLLB cell "gemma".
            ? row("Model", `<code class="nsd-cmd-inline">${escapeHtml(String(_scfg[_runnerRow.modelField] || "") || "—")}</code>`)
            : row("Model", escapeHtml(parsed.label || s.model || ""))}
          ${(!isLlama && !isCmd && _runnerRow)
            ? row("Runner", `${mbadge("cmd", `${_runnerRow.icon || ""} ${t(_runnerRow.labelKey) || _runnerRow.id}`)}${_runnerRow.health ? mbadge("cmd", `❤ ${_runnerRow.health}`) : ""}`)
            : ""}
          ${isCmd
            ? (row("Health", _scfg.HEALTH_PATH ? `<code>${escapeHtml(_scfg.HEALTH_PATH)}</code>` : "") + row("Workdir", _scfg.WORKDIR ? `<code>${escapeHtml(_scfg.WORKDIR)}</code>` : ""))
            : (() => { const chips = [parsed.quant ? mbadge("quant", `🎛 ${escapeHtml(parsed.quant)}`) : "", parsed.size ? mbadge("size", `⚖ ${escapeHtml(parsed.size)}`) : "", parsed.variant ? mbadge("it", `🤖 ${escapeHtml(parsed.variant)}`) : "", s.mmproj ? mbadge("mmproj", "📷 mmproj") : "", (hasMtp && _hasCtx) ? mbadge("mtp", "⚡ mtp") : "", nsdCtxChip].filter(Boolean).join(""); return chips ? `<div class="nsd-row"><span class="nsd-k"></span><span class="nsd-v"><span class="model-chips">${chips}</span></span></div>` : ""; })()}
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
              placeholder="${escapeHtml(t("cellNotePlaceholder"))}">${escapeHtml((topology?.cellNotes || {})[`${s.isController ? CONTROLLER_HOST_ID : node.id}:${s.port}`] || "")}</textarea>
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
        body: JSON.stringify({ hostId: s.isController ? CONTROLLER_HOST_ID : node.id, port: s.port, note }),
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
    // llama.cpp version chip
    const nodeVerStr = n.role === "controller" ? ctrlVersionStr : (n.llamaBinaryVersion || "");
    const nodeMtime = n.role === "controller" ? ctrlMtime : (n.llamaBinaryMtime || "");
    const nodeBuild = parseLlamaBuildVersion(nodeVerStr);
    const verLabel = nodeBuild ? `b${nodeBuild.build}` : "";
    // Build date: keep only the date part (first 10 ISO characters, no time)
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
    // Power-cycle this host. Some faults are not fixable in software — a host
    // drops a RAM stick on some boots and comes back with half its memory, which
    // starves cells until the machine is rebooted. Reboot only, never shutdown:
    // nothing on this board can switch a headless box back on.
    const rebootBtn = `<button class="llama-ver-refresh node-reboot" type="button" data-t="node-reboot" data-t-id="${escapeHtml(String(n.id))}" data-reboot-host="${escapeHtml(String(n.id))}" title="${escapeHtml(t("hostRebootTitle"))}" aria-label="${escapeHtml(t("hostRebootTitle"))}">⟳︎</button>`;
    // Power off. Deliberately NOT the same glyph as reboot and deliberately
    // last: the two sit side by side, and the one that cannot be undone should
    // not be the one under the thumb. Its confirmation asks for the host's name
    // to be typed — see topology-render.js.
    const powerOffBtn = `<button class="llama-ver-refresh node-poweroff" type="button" data-t="node-poweroff" data-t-id="${escapeHtml(String(n.id))}" data-poweroff-host="${escapeHtml(String(n.id))}" title="${escapeHtml(t("hostPowerOffTitle"))}" aria-label="${escapeHtml(t("hostPowerOffTitle"))}">⏻︎</button>`;
    // A schedule for that poweroff. The ⏰ lights up when one is armed and its
    // title shows the time, so an armed daily shutdown is visible at rest —
    // never a surprise. Opens the little editor in topology-render.js.
    const ps = n.powerSchedule || {};
    const psArmed = !!ps.enabled;
    const powerSchedBtn = `<button class="llama-ver-refresh node-power-sched${psArmed ? " armed" : ""}" type="button" data-t="node-power-schedule" data-t-id="${escapeHtml(String(n.id))}" data-power-schedule-host="${escapeHtml(String(n.id))}" title="${escapeHtml(psArmed ? t("hostPowerSchedArmedTitle", { at: ps.at || "", daily: ps.daily ? t("hostPowerSchedDaily") : t("hostPowerSchedOnce") }) : t("hostPowerSchedTitle"))}" aria-label="${escapeHtml(t("hostPowerSchedTitle"))}">⏰︎</button>`;
    const verChip = verLabel
      ? `<span class="llama-ver-chip${verOutdated ? " outdated" : ""}" title="${escapeHtml(verChipTitle)}">${escapeHtml(verLabel)}${verDate ? `<span class="llama-ver-date"> ${escapeHtml(verDate)}</span>` : ""}${upstreamArrow}${verOutdated ? " ⬆" : ""}</span>${refreshBtn}${updateBtn}${staleBadge}<span class="node-power-ctl">${rebootBtn}${powerSchedBtn}${powerOffBtn}</span>`
      : `${refreshBtn}<span class="node-power-ctl">${rebootBtn}${powerSchedBtn}${powerOffBtn}</span>`;
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
          data-t="board-cell-add" data-t-id="${escapeHtml(n.id)}"
          aria-label="${escapeHtml(t("topologyReserveCellLabel"))} :${escapeHtml(String(reservePort))}"
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
        // Same rule as the card's chip: a GPU-pinned cell is never a CPU cell,
        // even in the window where it holds no VRAM yet.
        return ph === "running" && !(srv.gpuIndexes || []).length && !cellPinnedToGpu(srv);
      }).map((srv) => srv.port).filter(Boolean);
      // The CPU block mirrors a GPU row now: live load% in the head, RAM
      // used/total where a GPU shows VRAM — those two moved out of the node
      // header (which kept only the platform). The "cells on CPU" ports are a
      // sub-line when any exist. Always rendered, so a host's CPU/RAM is visible
      // even with no CPU cell running.
      const cpuLoadTxt = cpu.loadPct != null ? `${cpu.loadPct}%` : "";
      const ramUsedGb = Number(ram.usedGb || 0), ramTotalGb = Number(ram.totalGb || 0);
      const ramPct = ramTotalGb > 0 ? Math.min(100, Math.round((ramUsedGb / ramTotalGb) * 100)) : 0;
      const cpuRamTxt = ram.usedGb != null ? `RAM ${ram.usedGb}/${ram.totalGb} GB`
        : (ram.totalGb != null ? `RAM ${ram.totalGb} GB` : "");
      // Mirrors a GPU row: a used/total RAM bar where the GPU has its VRAM bar
      // (no per-cell slices — just the whole-host RAM), and the CPU-cell blue
      // accent so the block matches the cells that run on it.
      const cpuRowHtml = `
        <div class="node-gpu-row node-cpu-row" title="${escapeHtml(t("topologyCpuCellsHint"))}">
          <div class="node-gpu-head">
            <strong>CPU</strong>
            <span class="node-gpu-util" data-live-cpuload>${escapeHtml(cpuLoadTxt)}</span>
          </div>
          <div class="node-ram-bar" data-live-cpurambar title="${ramUsedGb.toFixed(1)} / ${ramTotalGb.toFixed(1)} GB"><span style="width:${ramPct}%"></span></div>
          <div class="node-gpu-meta">
            <span data-live-cpuram>${escapeHtml(cpuRamTxt)}</span>
            ${cpuPorts.length ? `<span class="node-gpu-ports">▶ ${cpuPorts.map((pp) => escapeHtml(String(pp))).join(", ")}</span>` : ""}
          </div>
        </div>`;
      // CPU first, then the GPUs (swapped on request — the CPU/RAM summary now
      // lives here, so it leads).
      const gpusHtml = cpuRowHtml + ((n.gpus || []).length
        ? n.gpus.map((g) => nodeGpuRowHtml(n, g)).join("")
        // The reason outranks a dash: "no cards" and "can't ask a card" are
        // different messages, and the second one names what to fix (after a
        // driver update, that's "needs a reboot", while the card is right
        // there).
        : `<div class="topology-muted" style="font-size:12px"${n.gpuError ? ` title="${escapeHtml(n.gpuError)}"` : ""}>${escapeHtml(n.gpuError || t("topologyNoGpu"))}</div>`);
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
      // Cells running OUTSIDE the registry (live unit, no slot record): without
      // this strip they are invisible by construction — the board renders the
      // store — while holding their port and VRAM with nothing left to stop
      // them BY. Red, dashed, with the one action that makes sense.
      const _orphans = Array.isArray(n.orphanCells) ? n.orphanCells : [];
      const orphanHtml = _orphans.length ? `
        <div class="node-orphan-strip" title="${escapeHtml(t("topologyOrphanHint"))}">
          <div class="node-orphan-head">☠ ${escapeHtml(t("topologyOrphanCells"))}</div>
          ${_orphans.map((o) => `
            <div class="node-orphan-row">
              <span class="node-orphan-what">:${escapeHtml(String(o.port))}${o.model ? ` · ${escapeHtml(o.model)}` : ""}${o.vramMiB ? ` · ${escapeHtml((o.vramMiB / 1024).toFixed(1))}G VRAM` : ""}${o.pid ? ` · pid ${escapeHtml(String(o.pid))}` : ""}</span>
              <button class="node-orphan-stop" type="button" data-orphan-stop="${escapeHtml(String(o.port))}">${escapeHtml(t("stop"))}</button>
            </div>`).join("")}
        </div>` : "";
      bodyHtml = `<div class="node-body">
          <div class="node-servers">${serversSubtitle}${orphanHtml}${serversHtml}${startingCard}${addBtn}${serverStatsSlot}</div>
          <div class="node-gpus"><div class="node-subtitle">${escapeHtml(t("topologyGpusSection"))}</div>${gpusHtml}${gpuTelemetrySlot}</div>
        </div>`;
    }
    // A machine card is a real grouping of controls that belong together, and
    // nothing said so: a screen reader user walked into two dozen buttons with
    // no announcement of which machine any of them acts on. role="group" and
    // not the <section>'s implicit region — a landmark per machine would bury
    // the five that describe the page itself, and these are repeated items
    // inside one of those, not sections of the page.
    //
    // The name is assembled from what the header already shows: the role word
    // (translated), the machine's own name, and its address. Capitalised
    // because it opens a phrase; harmless where a script has no case.
    const _roleWord = n.role === "controller" ? t("nodeRoleController")
      : n.role === "client" ? t("nodeRoleClient") : String(n.role || "");
    const _groupName = `${_roleWord.charAt(0).toUpperCase()}${_roleWord.slice(1)} ${n.name || n.id}`
      + (n.ip ? ` · ${n.ip}` : "");
    return `
      <section class="node-card ${n.online ? "online" : "offline"} ${collapsed ? "collapsed" : ""}" data-node-id="${escapeHtml(n.id)}"
               role="group" aria-label="${escapeHtml(_groupName)}">
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
          <span class="node-meta" data-live-nodemeta>${escapeHtml(n.platform || "")}</span>
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

