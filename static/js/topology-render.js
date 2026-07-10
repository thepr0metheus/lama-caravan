// Render orchestration: renderAll/renderTopology, structure fingerprint, live sync.
import { drawTopologyCables, topologyAccentStyle } from "./cables.js";
import { _cvDrag, bindCanvasInteractions, drawCanvasConnectors } from "./canvas.js";
import { drawTopologyGpuHistory } from "./charts.js";
import {
  prefetchAllSubscriptionModels,
  renderTopologyCloudAccountModal,
  renderTopologyCloudBlockModal,
  renderTopologyCloudPicker,
  renderTopologyCloudProviders,
} from "./cloud.js";
import { renderCommandPreview } from "./command-preview.js";
import {
  readConfigForm,
  renderFields,
  renderModelSelects,
  renderRaw,
  renderStaticConfigFields,
  syncAllToggleLabels,
} from "./form.js";
import { applyLanguage, applyTheme, t } from "./i18n.js";
import { fetchProxyDailyStats } from "./model-meta.js";
import {
  formatCtxTokens,
  formatTps,
  startTopologyMonitor,
  stopTopologyMonitor,
} from "./polling.js";
import {
  _pendingCellActions,
  _stoppingCells,
  bindServerSlotControls,
  clearPendingRemoteStart,
  deleteTopologyClient,
  deleteTopologyClientAgent,
  discoveryAddCandidate,
  remoteStartupInFlight,
  renderNvidiaSmiSourceButtons,
  startRemoteStartWatch,
  submitLlamaStop,
  topologyClientGpusHtml,
} from "./remote-cells.js";
import { renderTopologyRouterCard, renderTopologyRouterDetail } from "./routers.js";
import { setTopology, state, topology, ui } from "./state.js";
import {
  checkLlamaCpp,
  renderCpu,
  renderGpu,
  renderKnownProblems,
  openRestoreBuildModal,
  renderLlamaCpp,
  renderOpenClawLinks,
  renderProjectGitBranch,
  renderRuntime,
  renderSectionTips,
  renderService,
} from "./system-panels.js";
import {
  drawRouteTokenHistory,
  refreshTopologyActivityState,
  topologyGpuActivity,
  topologyRouteDetailHtml,
  topologyStateHealthClasses,
  topologyStatusPill,
} from "./topology-activity.js";
import {
  bindTopologyDragAndDrop,
  topologyPointerDrag,
  topologyRouteDetail,
} from "./topology-dnd.js";
import {
  fetchQueueThresholds,
  recalcQueueThresholds,
  renderTopologyAgentConfigModal,
  renderTopologyClientDetail,
  renderTopologyGpuModal,
  renderTopologyLlamaDetail,
  renderTopologyRawConfigModal,
  renderTopologyScheduleModal,
  topologyQueuePriorityModalOpen,
} from "./topology-modals.js";
import {
  _collapsedNodes,
  applyNodesViewMode,
  mountNodeTelemetry,
  nodesLaneHtml,
  nodeSparklineSvg,
  openIncidentsModal,
  parkLaneStats,
  renderModelsBar,
  toggleCtrlServerStats,
  toggleNodeCollapsed,
  topologyNodesViewOn,
} from "./topology-nodes.js";
import {
  renderTopologyProxyForm,
  topologyAssignmentsForHost,
  topologyBoardAssignmentsForHost,
  topologyGroupedAgents,
} from "./topology-proxies.js";
import { renderUsageStatsModal } from "./usage-stats.js";
import { $, api, escapeHtml, formatMemoryMiB, toast } from "./utils.js";

export let activeView = "topology";  // Classic retired — Topology is the only view
// Live-render bookkeeping: a full renderTopology() rebuilds the whole DOM (and
// resets animations / drops an in-progress drag), so background refreshes only
// do it when the *structure* changes. Otherwise syncTopologyLive() patches the
// volatile numbers in place. Renders are deferred while the user is interacting.
export let _topologyRenderPending = false;

// Foreign modules defer a render during user interaction through this setter
// (rebinding an imported let throws).
export function markTopologyRenderPending() {
  _topologyRenderPending = true;
}
export let _lastStructureFingerprint = "";
// Perf: skip redundant per-tick DOM work when nothing has changed
export let _lastRuntimePanelHtml = {};       // group -> last-rendered panel HTML (per-server cache)
export function setActiveView(view) {
  // Classic is retired — the app is Topology-only now. The old #classicView DOM
  // is kept (hidden) because some bindings (#configForm, readConfigForm) still
  // reference it; the two unique panels (llama.cpp build, Known Problems) moved
  // into the System info modal.
  activeView = "topology";
  localStorage.setItem("llamacppAdminView", activeView);
  document.querySelectorAll("[data-view-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewTab === activeView);
  });
  document.querySelectorAll("[data-view]").forEach((panel) => {
    const active = panel.dataset.view === activeView;
    panel.classList.toggle("active", active);
    panel.hidden = !active;
  });
  if (activeView === "topology") {
    refreshTopology().catch((err) => toast(err.message));
    // Fetch stored thresholds + trigger recalc once on topology open
    fetchQueueThresholds();
    recalcQueueThresholds();
    startTopologyMonitor();
  } else {
    stopTopologyMonitor();
  }
}

export function renderTopology() {
  if (!topology) return;
  // Park live stat/chart elements back home before any innerHTML rebuild so we
  // never destroy them (they're re-mounted into the controller node below).
  parkLaneStats();
  const server = topology.server || {};
  const service = server.service || {};
  const runtimeStatus = server.runtime?.status || {};
  const updated = topology.time ? new Date(topology.time * 1000).toLocaleTimeString() : "";
  const updatedEl = $("topologyUpdated");
  if (updatedEl) updatedEl.textContent = updated ? `${t("topologyUpdatedLabel")} ${updated}` : "";

  const clients = topology.clients || [];
  const clientsEl = $("topologyClients");
  if (clientsEl) clientsEl.innerHTML = clients.length ? clients.map((client) => {
    const assignments = topologyBoardAssignmentsForHost(client.id);
    const displayName = client.name || client.id;
    const ccpu = client.cpu || {}, cram = ccpu.ram || {};
    const clientMeta = [
      ccpu.loadPct != null ? `CPU ${ccpu.loadPct}%` : "",
      cram.usedGb != null ? `RAM ${cram.usedGb}/${cram.totalGb} GB`
        : (cram.totalGb != null ? `RAM ${cram.totalGb} GB` : ""),
      client.platform || "",
    ].filter(Boolean).join(" · ");
    const isStale = client.state === "stale";
    const staleBanner = isStale ? `
      <div class="client-stale-banner">
        <span>${escapeHtml(t("topologyAgentNoContact"))}</span>
        <button class="client-delete-btn" type="button"
          data-client-delete="${escapeHtml(client.id)}">${escapeHtml(t("deleteAction"))}</button>
      </div>` : "";
    // Discovery hints: running agent-* machines on this host that aren't in the fleet registry.
    const candidates = Array.isArray(client.candidates) ? client.candidates : [];
    const discoveryBanner = candidates.length ? `
      <div class="client-discovery-banner">
        ${candidates.map((c) => `
          <div class="discovery-row">
            <span>🔍 ${escapeHtml(c.machine || "")} (${escapeHtml(c.runtime || "")}${c.ip ? ", " + escapeHtml(c.ip) : ""}) — not in registry</span>
            <button class="client-discovery-btn" type="button"
              data-discover-add="${escapeHtml(c.suggestedId || "")}"
              data-discover-host="${escapeHtml(c.ip || "")}">Add to fleet</button>
          </div>`).join("")}
      </div>` : "";
    return `
      <article class="topology-card client-card${isStale ? " client-stale" : ""}" data-client-id="${escapeHtml(client.id || "")}" style="${escapeHtml(topologyAccentStyle(client.id || displayName))}">
        <div class="topology-card-head client-head">
          <div class="client-title-line">
            <strong>${escapeHtml(displayName)}</strong>
            <button class="client-rename-btn" type="button" title="Set display name"
              data-client-rename="${escapeHtml(client.id)}" data-client-name="${escapeHtml(displayName)}">✎</button>
            <span>${escapeHtml(client.ip || "ip n/a")}</span>
          </div>
          <div class="client-state-line">
            ${topologyStatusPill(client.state)}
            <span data-live-age>${client.ageSeconds ?? "?"}s ago</span>
          </div>
        </div>
        <div class="client-meta-line" data-live-meta${clientMeta ? "" : ' style="display:none"'}>${escapeHtml(clientMeta)}</div>
        ${topologyClientGpusHtml(client)}
        <div class="topology-agents">${topologyGroupedAgents(client, assignments)}</div>
        ${discoveryBanner}
        ${staleBanner}
      </article>
    `;
  }).join("") : `<article class="topology-card"><div class="topology-muted">${escapeHtml(t("topologyClientsWaiting"))}</div></article>`;

  $("topologyProxies").innerHTML = [
    renderUsageStatsModal(),
    renderTopologyGpuModal(),
    renderTopologyRawConfigModal(),
    renderTopologyAgentConfigModal(),
    renderTopologyClientDetail(),
    renderTopologyLlamaDetail(),
    renderTopologyCloudPicker(),
    renderTopologyCloudAccountModal(),
    renderTopologyCloudBlockModal(),
    topologyRouteDetailHtml(),
    renderTopologyProxyForm(),
    renderTopologyRouterDetail(),
    renderTopologyScheduleModal(),
    // Routing layer: a single router (Роутер). The proxy is the client's
    // primary/fallback row (left); its handle drags to the router input.
    `<div class="router-stack">${(topology.routers || []).filter((s) => s.id === "router:default").map(renderTopologyRouterCard).join("")}</div>`,
  ].join("");

  applyNodesViewMode();
  renderModelsBar();
  const llamaServersEl = $("topologyLlamaServers");
  if (llamaServersEl) llamaServersEl.innerHTML = nodesLaneHtml();
  mountNodeTelemetry();  // relocate live controller charts into the controller node
  // Dismiss buttons on terminal (timeout/error) pending-start cards
  document.querySelectorAll("[data-pending-remote-dismiss]").forEach((btn) => {
    btn.addEventListener("click", () => {
      clearPendingRemoteStart(btn.dataset.pendingRemoteDismiss);
      renderTopology();
    });
  });
  // Delete stale client buttons (whole-client cards)
  document.querySelectorAll("[data-client-delete]").forEach((btn) => {
    btn.addEventListener("click", () => deleteTopologyClient(btn.dataset.clientDelete));
  });
  // Discovery: register a detected-but-unregistered agent into the fleet registry.
  document.querySelectorAll("[data-discover-add]").forEach((btn) => {
    btn.addEventListener("click", () => discoveryAddCandidate(btn.dataset.discoverAdd, btn.dataset.discoverHost));
  });
  // Delete individual agent sub-client buttons (within a host card, legacy path)
  document.querySelectorAll("[data-agent-client-delete]").forEach((btn) => {
    btn.addEventListener("click", (e) => { e.stopPropagation(); deleteTopologyClient(btn.dataset.agentClientDelete); });
  });
  // Delete agent from client agent list (runtimeDetected path)
  document.querySelectorAll("[data-agent-delete-client]").forEach((btn) => {
    btn.addEventListener("click", (e) => { e.stopPropagation();
      deleteTopologyClientAgent(btn.dataset.agentDeleteClient, btn.dataset.agentDeleteId); });
  });
  // Keep polling if a remote server is mid-startup (e.g. page reloaded during
  // a download) even when no client-side placeholder initiated it.
  if (remoteStartupInFlight()) startRemoteStartWatch();

  const gpuActivity = topologyGpuActivity();
  // controller GPUs
  const skynetGpuCards = (server.gpus || []).map((gpu) => {
    const used = formatMemoryMiB(gpu.memoryUsedMiB);
    const total = formatMemoryMiB(gpu.memoryTotalMiB);
    const util = gpu.utilPct ?? gpu.utilizationGpuPct ?? 0;
    const power = gpu.powerW ?? gpu.powerDrawW ?? "n/a";
    return `
      <article class="topology-card gpu-card ${escapeHtml(topologyStateHealthClasses(gpuActivity))}" data-topology-gpu-modal="${escapeHtml(String(gpu.index ?? 0))}" role="button" tabindex="0" title="Show Logs &amp; Raw API">
        <div class="topology-card-head">
          <strong>GPU ${escapeHtml(gpu.index ?? "?")}</strong>
          ${topologyStatusPill(`${util}%`)}
        </div>
        <div class="topology-model">${escapeHtml(gpu.name || "GPU")}</div>
        <div class="topology-meta">
          <span>VRAM ${used} / ${total}</span>
          <span>${escapeHtml(gpu.temperatureC ?? "n/a")}C</span>
          <span>${escapeHtml(power)}W</span>
          ${gpuActivity.label ? `<span class="topology-activity-chip ${escapeHtml(gpuActivity.state)}">${escapeHtml(gpuActivity.label)}</span>` : ""}
        </div>
        ${gpuActivity.summary ? `<div class="topology-telemetry-line server">${escapeHtml(gpuActivity.summary)}</div>` : ""}
      </article>`;
  });

  // Remote client GPUs — shown alongside controller GPUs
  const remoteGpuCards = [];
  for (const client of (topology?.clients || [])) {
    if (client.state !== "online") continue;
    for (const gpu of (client.gpus || [])) {
      if (!gpu.name) continue;
      const used  = formatMemoryMiB(gpu.memoryUsedMiB);
      const total = formatMemoryMiB(gpu.memoryTotalMiB);
      const util  = gpu.utilizationGpuPct ?? 0;
      const temp  = gpu.temperatureC ?? "n/a";
      const cname = escapeHtml(client.name || client.id || "");
      remoteGpuCards.push(`
        <article class="topology-card gpu-card" style="opacity:.9">
          <div class="topology-card-head">
            <strong>${cname}</strong>
            ${topologyStatusPill(`${util}%`)}
          </div>
          <div class="topology-model">${escapeHtml(gpu.name || "GPU")}</div>
          <div class="topology-meta">
            <span>VRAM ${used} / ${total}</span>
            <span>${escapeHtml(String(temp))}C</span>
            <span class="topology-muted" style="font-size:11px">remote</span>
          </div>
        </article>`);
    }
  }

  const gpusEl = $("topologyGpus");
  if (gpusEl) gpusEl.innerHTML = [...skynetGpuCards, ...remoteGpuCards].join("") ||
    `<article class="topology-card"><div class="topology-muted">${escapeHtml(t("topologyNoGpusDetected"))}</div></article>`;
  renderTopologyCloudProviders();
  bindTopologyDragAndDrop();

  // Bind stop buttons on remote llama-server cards (re-bind each render)
  document.querySelectorAll("[data-llama-stop]").forEach((btn) => {
    btn.addEventListener("click", () => submitLlamaStop(btn.dataset.llamaStop));
  });
  // Node-view server stop buttons (node mode uses data-node-stop)
  $("topologyLlamaServers")?.querySelectorAll("[data-node-stop]").forEach((btn) => {
    btn.addEventListener("click", () => submitLlamaStop(btn.dataset.nodeStop));
  });
  // Node collapse/expand
  $("topologyLlamaServers")?.querySelectorAll("[data-node-collapse]").forEach((btn) => {
    btn.addEventListener("click", () => toggleNodeCollapsed(btn.dataset.nodeCollapse));
  });
  // Controller node: "Servers" header toggles the mounted Server telemetry slot.
  $("topologyLlamaServers")?.querySelectorAll("[data-ctrl-stats-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => toggleCtrlServerStats(btn));
  });
  // Controller node: Incidents button opens the incidents modal.
  $("topologyLlamaServers")?.querySelectorAll("[data-ctrl-incidents]").forEach((btn) => {
    btn.addEventListener("click", openIncidentsModal);
  });
  // Controller node: llama.cpp version refresh button
  $("topologyLlamaServers")?.querySelectorAll("[data-check-llama-ver]").forEach((btn) => {
    btn.addEventListener("click", () => checkLlamaCpp().catch((err) => toast(err.message)));
  });
  // Client nodes: update llama.cpp on the client to the controller's commit.
  // The scout runs it as a background job; its heartbeat flips the chip to a
  // "building…" indicator on the next topology poll.
  $("topologyLlamaServers")?.querySelectorAll("[data-update-client-llama]").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const hostId = btn.getAttribute("data-update-client-llama") || "";
      const tag = state.llamaCpp?.git?.head || "";
      if (!window.confirm(t("updateClientLlamaConfirm"))) return;
      try {
        await api("/api/fleet/llama-update", { method: "POST", body: JSON.stringify({ hostId, tag }) });
        toast(t("clientLlamaBuilding"));
      } catch (err) {
        toast(err.message);
      }
    });
  });
  // Stopped-slot Start / remove controls (both classic + node lane)
  bindServerSlotControls($("topologyLlamaServers"));

  // Refresh source buttons whenever topology re-renders
  renderNvidiaSmiSourceButtons();

  // Invalidate per-tick caches — full DOM was just rebuilt, next tick must re-sync
  _lastRuntimePanelHtml = {};
  ui._lastActivityFingerprint = "";
  ui._lastCloudProvidersKey = "";
  // Record the structure we just rendered so background ticks can tell whether
  // they need another full rebuild or just a live patch.
  _lastStructureFingerprint = topologyStructureFingerprint();
  _topologyRenderPending = false;  // a full render satisfies any deferred refresh
  if (topologyRouteDetail?.port || topologyRouteDetail?.clientIp) drawRouteTokenHistory();
  requestAnimationFrame(drawTopologyCables);
  if (ui.topologyCanvasRouterId) requestAnimationFrame(() => { drawCanvasConnectors(); bindCanvasInteractions(); });
  // Charts are driven by the 1s monitor timer; draw once here for initial render
  drawTopologyGpuHistory();
}

export async function refreshTopology() {
  setTopology(await api("/api/topology"));
  // Structure-aware: full rebuild only when the graph changed, else a cheap
  // in-place patch — and never rebuild mid-interaction (deferred).
  applyTopologyUpdate();
  prefetchAllSubscriptionModels();
  fetchProxyDailyStats().catch(() => {});
}

// True while the user is mid-interaction — rebuilding the DOM now would drop an
// in-progress cable drag or close a proxy form, so we defer the render.
export function topologyInteractionActive() {
  if (topologyPointerDrag || ui.topologyProxyFormOpen || _cvDrag) return true;
  // A focused select/text field anywhere on the poll-rebuilt page defers the
  // rebuild too: a full render replaces the DOM under the user's cursor —
  // closing an open dropdown mid-choice (bridge model select, port-registry
  // router select) or stealing the caret from a text field (cell note).
  // The deferred render lands via flushPendingTopologyRender on focusout.
  const ae = document.activeElement;
  return !!(ae && ae.matches
            && ae.matches("select, textarea, input:not([type=checkbox]):not([type=radio])"));
}

// Exact phase string — used as a structural key. The fast-moving bits inside a
// phase (download %, t/s, ctx) are NOT in the phase, so they stay live-patched;
// any phase transition (downloading→loading→running) is structural → full render.
export function topologyServerPhase(s) {
  return (s.phase) || (s.status && s.status.phase) || (s.isController ? "running" : "stopped");
}

// Identity of the graph: anything that changes which cards/handles/cables exist
// or how they connect. Deliberately EXCLUDES fast-moving numbers (t/s, VRAM,
// ageSeconds, ctxUsed, download %), which syncTopologyLive() patches in place.
export function topologyStructureFingerprint() {
  if (!topology) return "";
  const server = topology.server || {};
  const clients = (topology.clients || [])
    .map((c) => `${c.id}:${c.name || ""}:${c.state}:${(c.gpus || []).length}:${topologyAssignmentsForHost(c.id).length}`)
    .sort().join(",");
  const classicSrv = (server.llamaServers || [])
    .map((s) => `${s.id}:${s.port}:${s.model || ""}:${topologyServerPhase(s)}:${s.reachable === false ? 0 : 1}`)
    .sort().join(",");
  const nodeSrv = (topology.nodes || [])
    .flatMap((n) => (n.servers || []).map((s) =>
      `${n.id}/${s.port}:${s.model || ""}:${topologyServerPhase(s)}:${s.isController ? 1 : 0}:${s.reachable === false ? 0 : 1}`))
    .sort().join(",");
  const gpus = (topology.nodes || [])
    .flatMap((n) => (n.gpus || []).map((g) => `${n.id}/${g.index}`))
    .sort().join(",");
  const prox = (topology.proxies || [])
    .map((p) => `${p.port}:${p.label || ""}>${p.upstreamHost}:${p.upstreamPort}:${p.upstreamType}:${p.providerId || ""}:${p.enabled !== false ? 1 : 0}:${p.mode || ""}:${p.priority || 0}`)
    .sort().join(",");
  const cloud = (topology.cloudProviders || [])
    .map((p) => `${p.id}:${(p.models || []).length}:${p.enabled !== false ? 1 : 0}`)
    .sort().join(",");
  // llama.cpp build state per node: the client-update job flipping running
  // on/off and a finished build changing the binary version/mtime must
  // re-render the version chip (building indicator, stale badge, ⇪ button).
  const llamaVer = (topology.nodes || [])
    .map((n) => `${n.id}:${(n.llamaBinaryVersion || "").slice(0, 40)}:${(n.llamaBinaryMtime || "").slice(0, 19)}:${n.llamaUpdate?.running ? 1 : 0}`)
    .sort().join(",");
  const view = `${topologyNodesViewOn ? 1 : 0}:${[..._collapsedNodes].sort().join("+")}`;
  // In-flight cell actions are structural: adding/clearing one must re-render
  // the card even when the server-side topology has not moved yet.
  const pendingCells = `${[..._pendingCellActions.keys()].sort().join("+")}:${[..._stoppingCells].sort().join("+")}`;
  const modals = `${ui.topologyProxyFormOpen ? 1 : 0}:${topologyQueuePriorityModalOpen ? 1 : 0}:${topologyRouteDetail?.proxyId || ""}`;
  return [clients, classicSrv, nodeSrv, gpus, prox, cloud, llamaVer, view, pendingCells, modals].join("||");
}

// ── llama.cpp crash-watchdog banner ──────────────────────────────────────────
// The backend flags "fresh build + crashing cells"; the banner offers a
// rollback to the previous archived build. Restore fires only after a second,
// explicit confirmation click — never automatically.
let _suspectKey = "";
let _suspectDismissed = "";
function renderLlamaSuspectBanner() {
  const el = $("llamaSuspectBanner");
  if (!el) return;
  const s = topology?.llamaSuspect || {};
  const cand = s.restoreCandidate || null;
  const key = s.suspect ? `${s.currentCommit}:${s.builtAt}:${cand?.id || ""}` : "";
  if (!s.suspect || _suspectDismissed === key) {
    el.hidden = true;
    _suspectKey = "";
    return;
  }
  if (key === _suspectKey && !el.hidden) return;   // already rendered
  _suspectKey = key;
  const candLabel = cand ? String(cand.version || cand.id).replace("version: ", "b") : "";
  el.innerHTML = `
    <span class="llama-suspect-msg">⚠ ${escapeHtml(t("llamaSuspectMsg").replace("{n}", String(s.crashes15m || 0)))}</span>
    ${cand ? `<button type="button" class="llama-suspect-restore" data-suspect-restore="${escapeHtml(cand.id)}">${escapeHtml(t("llamaSuspectRestore"))} ${escapeHtml(candLabel)}</button>` : ""}
    <button type="button" class="llama-suspect-dismiss" data-suspect-dismiss>${escapeHtml(t("llamaSuspectDismiss"))}</button>`;
  el.hidden = false;
  const restoreBtn = el.querySelector("[data-suspect-restore]");
  if (restoreBtn) {
    // The click opens the SAME informative confirmation the System builds
    // list uses: what will happen (from → to, cells keep running) and the
    // escape hatches if the restored build misbehaves too.
    restoreBtn.addEventListener("click", () => {
      _suspectDismissed = key;   // the banner did its job; the modal takes over
      el.hidden = true;
      openRestoreBuildModal(String(cand?.id || ""), cand);
    });
  }
  el.querySelector("[data-suspect-dismiss]")?.addEventListener("click", () => {
    _suspectDismissed = key;
    el.hidden = true;
  });
}

// Decide between a full structural rebuild and a cheap in-place live patch —
// and never rebuild while the user is interacting (defer until they finish).
export function applyTopologyUpdate() {
  if (!topology) return;
  renderLlamaSuspectBanner();
  if (topologyInteractionActive()) {
    _topologyRenderPending = true;
    return;
  }
  const fp = topologyStructureFingerprint();
  if (fp !== _lastStructureFingerprint) {
    // Set window.__fpDebug = 1 in the console to see WHICH fingerprint part
    // forces full rebuilds — the #1 suspect when the board redraws too often.
    if (window.__fpDebug && _lastStructureFingerprint) {
      const a = _lastStructureFingerprint.split("||"), b = fp.split("||");
      const parts = ["clients", "classicSrv", "nodeSrv", "gpus", "prox", "cloud", "llamaVer", "view", "pendingCells", "modals"];
      b.forEach((v, i) => { if (v !== a[i]) console.debug(`[fp] ${parts[i]} changed:\n  was: ${a[i]}\n  now: ${v}`); });
    }
    renderTopology();          // structure changed → full rebuild
  } else if (topologyNodesViewOn) {
    syncTopologyLive();        // node view → patch volatile numbers, keep DOM + animations
  } else {
    renderTopology();          // classic view (legacy) keeps its per-tick full render
  }
}

// Flush a render that was deferred because the user was dragging / had a form
// open. Called when the interaction ends.
export function flushPendingTopologyRender() {
  if (!_topologyRenderPending) return;
  _topologyRenderPending = false;
  applyTopologyUpdate();
}

// ── Live in-place patch (no DOM rebuild) ─────────────────────────────────────
// Runs on background ticks when the graph STRUCTURE is unchanged. Updates only
// the fast-moving numbers by writing text/width into pre-existing hooks, so
// animations keep running and an in-progress drag is never disturbed. Covers the
// node view + the clients column (classic view falls back to a full render).
export function _liveSet(root, sel, text) {
  const el = root ? root.querySelector(sel) : document.querySelector(sel);
  if (el && el.textContent !== text) el.textContent = text;
  return el;
}
export function _liveShow(el, show) {
  if (el) el.style.display = show ? "" : "none";
}

export function syncTopologyLive() {
  if (!topology) return;

  const updatedEl = $("topologyUpdated");
  if (updatedEl && topology.time) {
    updatedEl.textContent = `updated ${new Date(topology.time * 1000).toLocaleTimeString()}`;
  }

  // Clients column (present in both views): heartbeat age + CPU/RAM line.
  (topology.clients || []).forEach((client) => {
    const card = document.querySelector(`.client-card[data-client-id="${CSS.escape(client.id || "")}"]`);
    if (!card) return;
    _liveSet(card, "[data-live-age]", `${client.ageSeconds ?? "?"}s ago`);
    const ccpu = client.cpu || {}, cram = ccpu.ram || {};
    const meta = [
      ccpu.loadPct != null ? `CPU ${ccpu.loadPct}%` : "",
      cram.usedGb != null ? `RAM ${cram.usedGb}/${cram.totalGb} GB`
        : (cram.totalGb != null ? `RAM ${cram.totalGb} GB` : ""),
      client.platform || "",
    ].filter(Boolean).join(" · ");
    const metaEl = _liveSet(card, "[data-live-meta]", meta);
    _liveShow(metaEl, !!meta);
    // The client GPU summary (VRAM/util/temp/uptime) is pure display — no bound
    // listeners or animation inside — so we can safely rebuild just that block
    // from its own builder (keeps it live without drift, leaves cables intact).
    const gpuBlock = card.querySelector(".client-gpus");
    if (gpuBlock) {
      const tmpl = document.createElement("template");
      tmpl.innerHTML = topologyClientGpusHtml(client);
      const fresh = tmpl.content.firstElementChild;
      if (fresh) gpuBlock.replaceWith(fresh);
    }
  });

  // Node view is the only place we live-patch servers/GPUs (classic re-renders).
  if (!topologyNodesViewOn) return;

  (topology.nodes || []).forEach((n) => {
    const nodeEl = document.querySelector(`.node-card[data-node-id="${CSS.escape(n.id)}"]`);
    if (!nodeEl) return;

    // Node header: CPU/RAM sparklines + the "CPU x% · RAM y/z GB · platform" line.
    const cpu = n.cpu || {}, ram = cpu.ram || {};
    const cpuTxt = cpu.loadPct != null ? `CPU ${cpu.loadPct}%` : "";
    const ramTxt = ram.usedGb != null ? `RAM ${ram.usedGb}/${ram.totalGb} GB` : (ram.totalGb != null ? `RAM ${ram.totalGb} GB` : "");
    _liveSet(nodeEl, "[data-live-nodemeta]", [cpuTxt, ramTxt, n.platform].filter(Boolean).join(" · "));

    // Server cards: token speed, context usage, download progress.
    (n.servers || []).forEach((s) => {
      const card = nodeEl.querySelector(`.node-server[data-llama-port="${CSS.escape(String(s.port))}"]`);
      if (!card) return;
      const running = topologyServerPhase(s) === "running";
      if (running) {
        const tpsEl = card.querySelector("[data-live-tps]");
        if (tpsEl) {
          tpsEl.textContent = `${formatTps(s.promptTps || 0)} / ${formatTps(s.genTps || 0)} t/s`;
          _liveShow(tpsEl, !!(s.promptTps || s.genTps));
        }
        const ctxEl = card.querySelector("[data-live-ctx]");
        if (ctxEl) {
          ctxEl.textContent = `ctx ${s.ctxUsed != null ? formatCtxTokens(s.ctxUsed) : "—"} / ${formatCtxTokens(s.ctxMax || 0)}`;
          _liveShow(ctxEl, !!s.ctxMax);
        }
      } else if (topologyServerPhase(s) === "downloading") {
        const done = Number(s.downloadedBytes || 0), tot = Number(s.totalBytes || 0);
        const p = tot > 0 ? Math.round((done / tot) * 100) : null;
        const bar = card.querySelector(".remote-dl-bar > span");
        if (bar) bar.style.width = `${p ?? 0}%`;
        const dlLabel = s.downloadingFile || t("topologyRemoteDownloading");
        _liveSet(card, "[data-live-dl]", `${dlLabel} · ${(done / 1e9).toFixed(1)}/${(tot / 1e9).toFixed(1)} GB${p != null ? ` · ${p}%` : ""}`);
      }
    });

    // GPU rows: utilisation/temp/power, VRAM bar + text, sparkline.
    (n.gpus || []).forEach((g) => {
      const row = nodeEl.querySelector(`[data-gpu-row="${CSS.escape(`${n.id}:${g.index}`)}"]`);
      if (!row) return;
      const used = Number(g.memoryUsedMiB || 0), total = Number(g.memoryTotalMiB || 0);
      const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
      const usedGb = (used / 1024).toFixed(1), totalGb = (total / 1024).toFixed(1);
      const util = g.utilizationGpuPct ?? "?", temp = g.temperatureC ?? "?", power = g.powerDrawW ?? "?";
      _liveSet(row, "[data-live-gpuutil]", `${util}% · ${temp}°C · ${power}W`);
      _liveSet(row, "[data-live-gpuvram]", `VRAM ${usedGb} / ${totalGb} GB`);
      const barWrap = row.querySelector("[data-live-gpuvrambar]");
      if (barWrap) {
        barWrap.title = `${usedGb} / ${totalGb} GB`;
        const bar = barWrap.querySelector("span");
        if (bar) bar.style.width = `${pct}%`;
      }
      const sparkEl = row.querySelector("[data-live-gpuspark]");
      if (sparkEl) {
        const svg = nodeSparklineSvg(g.history, 1, "var(--accent,#6ea8fe)", total);
        if (sparkEl.innerHTML !== svg) sparkEl.innerHTML = svg;
      }
    });
  });

  // Cheap cable redraw (anchors may have shifted as text widths changed) + keep
  // activity classes/chips in sync via the existing fingerprinted helper.
  refreshTopologyActivityState();
  requestAnimationFrame(drawTopologyCables);
}

export function renderAll() {
  applyLanguage();
  applyTheme();
  renderProjectGitBranch();
  renderSectionTips();
  renderService();
  renderRuntime();
  renderOpenClawLinks();
  renderCpu();
  renderGpu();
  renderLlamaCpp();
  renderKnownProblems();
  renderFields();
  renderStaticConfigFields();
  renderModelSelects();
  syncAllToggleLabels();
  renderCommandPreview();
  renderRaw();
  renderTopology();
}

