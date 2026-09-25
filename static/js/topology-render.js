// Render orchestration: renderAll/renderTopology, structure fingerprint, live sync.
import { CARD_FOLD } from "./card-fold.js";
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
import { appConfirm, appPrompt } from "./dialogs.js";
import { applyLanguage, applyTheme, t } from "./i18n.js";
import { fetchProxyDailyStats } from "./model-meta.js";
import {
  formatCtxTokens,
  formatTps,
  startTopologyMonitor,
  stopTopologyMonitor,
} from "./polling.js";
import {
  editRouteContext,
  addTopologyClient,
  _pendingCellActions,
  _stoppingCells,
  bindServerSlotControls,
  actOnEngineButton,
  pullEngineButton,
  serveEngineButton,
  clearPendingRemoteStart,
  deleteTopologyClientAgent,
  openHostPowerScheduleModal,
  remoteStartupInFlight,
  renderNvidiaSmiSourceButtons,
  startRemoteStartWatch,
  submitLlamaStop,
  disconnectScout,
  editRouteModel,
  editRouteWait,
  setRouteContextPrefer,
  setRouteModelLock,
} from "./remote-cells.js";
import { renderTopologyRouterCard, renderTopologyRouterDetail, setEngineModelExposed } from "./routers.js";
import { setTopology, state, topology, ui } from "./state.js";
import { SUSPECT_BANNER } from "./suspect-banner.js";
import {
  renderKnownProblems,
  renderLlamaCpp,
  renderProjectGitBranch,
  renderSectionTips,
} from "./system-panels.js";
import {
  drawRouteTokenHistory,
  refreshTopologyActivityState,
  topologyRouteDetailHtml,
  topologyStatusPill,
  sortedLaneCards,
  sortedTopologyClients,
} from "./topology-activity.js";
import {
  bindTopologyDragAndDrop,
  topologyPointerDrag,
  topologyRouteDetail,
} from "./topology-dnd.js";
import {
  recalcQueueThresholds,
  renderTopologyRawConfigModal,
  renderTopologyScheduleModal,
  topologyQueuePriorityModalOpen,
} from "./topology-modals.js";
import {
  _collapsedNodes,
  applyNodesViewMode,
  engineDownloadText,
  engineRamText,
  engineVramText,
  gpuOutsideBar,
  gpuWhoHtml,
  hostAgeText,
  hostPowerTextKey,
  isControllerMachine,
  mountNodeTelemetry,
  nodesLaneHtml,
  nodeSparklineSvg,
  parkLaneStats,
  renderModelsBar,
  toggleCtrlServerStats,
  toggleNodeCollapsed,
  topologyNodesViewOn,
} from "./topology-nodes.js";
import {
  renderTopologyProxyForm,
  topologyBoardAssignmentsForHost,
  clientLaneAgentCards,
  clientNeedsCaption,
  AGENT_IDLE_HOURS,
  clientIsLive,
} from "./topology-proxies.js";
import { renderUsageStatsModal } from "./usage-stats.js";
import { $, api, escapeHtml, formatMemoryMiB, markPageState, toast } from "./utils.js";

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
  // The board is the only view: the classic single-server view went with the
  // controller's own cells in step 6.9 (its two unique panels, llama.cpp
  // build and Known Problems, had already moved to the System page).
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
    // Recalc once on topology open. It POSTs and returns the fresh thresholds
    // itself, assigning the same `queueThresholds` the GET did — so the GET
    // that used to run first was fetching a value about to be overwritten by
    // the next line.
    recalcQueueThresholds();
    startTopologyMonitor();
  } else {
    stopTopologyMonitor();
  }
}

export function renderTopology() {
  if (!topology) return;
  // The lane switches live in the page's static header, outside the lanes this
  // repaints; their words still follow the language and the current setting.
  CARD_FOLD.syncSwitches();
  // Park live stat/chart elements back home before any innerHTML rebuild so we
  // never destroy them (they're re-mounted into the controller node below).
  parkLaneStats();
  const updated = topology.time ? new Date(topology.time * 1000).toLocaleTimeString() : "";
  const updatedEl = $("topologyUpdated");
  if (updatedEl) updatedEl.textContent = updated ? `${t("topologyUpdatedLabel")} ${updated}` : "";

  const clients = sortedTopologyClients(topology.clients || []);
  const clientsEl = $("topologyClients");
  // The lane is one flat list of cards — an agent or a client's caption —
  // ordered live-first and by name (sortedLaneCards), not client by client: a
  // client with ten agents would otherwise keep its quiet ones among the live
  // ones. A card still shows its client by the accent colour it carries.
  //
  // Only clients: the operator's records. The machine a scout reports is a
  // node in the model-servers lane (docs/scout-split.md); the host card that
  // stood here, with the machine's CPU, GPUs and silence, told about the
  // machine and was read as the client.
  const laneCards = [];
  clients.forEach((client) => {
    const assignments = topologyBoardAssignmentsForHost(client.id);
    const displayName = client.name || client.id;
    const caption = clientNeedsCaption((client.agents || []).length) ? `
      <div class="client-caption" data-t="board-client-caption" data-t-id="${escapeHtml(client.id || "")}">
        <strong>${escapeHtml(displayName)}</strong>
        <button class="client-rename-btn" type="button" title="${escapeHtml(t("trTitleSetName"))}"
          data-client-rename="${escapeHtml(client.id)}" data-client-name="${escapeHtml(displayName)}">✎</button>
      </div>` : "";
    if (caption) laneCards.push({ live: clientIsLive(client), name: displayName, html: caption });
    clientLaneAgentCards(client, assignments).forEach((card) => laneCards.push({ live: !card.idle, name: card.name, html: `
      <article class="topology-card agent-card${card.idle ? " idle" : ""}" data-t="board-agent-card"
               data-t-id="${escapeHtml(client.id || "")}"
               data-client-id="${escapeHtml(client.id || "")}"
               data-agent-id="${escapeHtml(card.agentId || "")}"${card.idle ? `
               title="${escapeHtml(t("agentIdleTip", { hours: String(AGENT_IDLE_HOURS) }))}"` : ""}
               style="${escapeHtml(topologyAccentStyle(client.id || displayName))}">${card.html}</article>` }));
  });
  if (clientsEl) clientsEl.innerHTML = clients.length ? sortedLaneCards(laneCards).map((card) => card.html).join("")
    : `<article class="topology-card"><div class="topology-muted">${escapeHtml(t("topologyClientsWaiting"))}</div></article>`;

  $("topologyProxies").innerHTML = [
    renderUsageStatsModal(),
    renderTopologyRawConfigModal(),
    renderTopologyCloudPicker(),
    renderTopologyCloudAccountModal(),
    renderTopologyCloudBlockModal(),
    topologyRouteDetailHtml(),
    renderTopologyProxyForm(),
    renderTopologyRouterDetail(),
    renderTopologyScheduleModal(),
    // Routing layer: a single router. The proxy is the client's
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
  // The limit and the switch on the route's context line, edited in place.
  document.querySelectorAll("[data-route-ctx]").forEach((chip) => {
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      editRouteContext(chip.dataset.ctxHost, chip.dataset.ctxAgent, chip.dataset.ctxRole,
                       chip.dataset.ctxValue, !!chip.dataset.ctxPrefer);
    });
  });
  // The row underneath opens the route detail on click; a click on the switch
  // or its caption must not — the label swallows both.
  document.querySelectorAll("[data-route-ctx-prefer-label]").forEach((label) => {
    label.addEventListener("click", (e) => e.stopPropagation());
    label.addEventListener("keydown", (e) => e.stopPropagation());
  });
  document.querySelectorAll("[data-route-ctx-prefer]").forEach((box) => {
    box.addEventListener("change", () => {
      setRouteContextPrefer(box.dataset.ctxHost, box.dataset.ctxAgent, box.dataset.ctxRole,
                            box.dataset.ctxValue, box.checked);
    });
  });
  document.querySelectorAll("[data-route-wait]").forEach((chip) => {
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      editRouteWait(chip.dataset.waitProxy, chip.dataset.waitValue);
    });
  });
  document.querySelectorAll("[data-route-model]").forEach((chip) => {
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      editRouteModel(chip.dataset.modelHost, chip.dataset.modelAgent, chip.dataset.modelRole,
                     chip.dataset.modelValue, !!chip.dataset.modelAuto);
    });
  });
  // The lock on the name: same record, a second decision. The name travels
  // along with it — the server accepts both fields at once, and a missing
  // one means "clear".
  document.querySelectorAll("[data-route-model-lock]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      setRouteModelLock(btn.dataset.modelHost, btn.dataset.modelAgent, btn.dataset.modelRole,
                        btn.dataset.modelValue, !btn.dataset.modelAuto);
    });
  });
  // Create a client by hand — a button in the lane's header.
  const addClientBtn = document.getElementById("topologyClientAddBtn");
  if (addClientBtn && !addClientBtn.dataset.bound) {
    addClientBtn.dataset.bound = "1";
    addClientBtn.addEventListener("click", () => addTopologyClient());
  }
  // Delete an agent: the record, its route settings; its ports stay free.
  document.querySelectorAll("[data-agent-delete-client]").forEach((btn) => {
    btn.addEventListener("click", (e) => { e.stopPropagation();
      deleteTopologyClientAgent(btn.dataset.agentDeleteClient, btn.dataset.agentDeleteId); });
  });
  // Keep polling if a remote server is mid-startup (e.g. page reloaded during
  // a download) even when no client-side placeholder initiated it.
  if (remoteStartupInFlight()) startRemoteStartWatch();

  // The GPUs of the machines whose scouts answer — the controller's own
  // machine among them (its own GPU cards, with the legacy logs modal, went
  // with its cells in step 6.9). They are the hosts' (topology.hosts), not the
  // clients': a client is the operator's record and has no hardware of its own.
  const remoteGpuCards = [];
  for (const host of (topology?.hosts || [])) {
    if (host.state !== "online") continue;
    for (const gpu of (host.gpus || [])) {
      if (!gpu.name) continue;
      const used  = formatMemoryMiB(gpu.memoryUsedMiB);
      const total = formatMemoryMiB(gpu.memoryTotalMiB);
      const util  = gpu.utilizationGpuPct ?? 0;
      const temp  = gpu.temperatureC ?? "n/a";
      const cname = escapeHtml(host.name || host.id || "");
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
  if (gpusEl) gpusEl.innerHTML = remoteGpuCards.join("") ||
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
  // A machine's eye: hide its cells that are not running, or show them again.
  $("topologyLlamaServers")?.querySelectorAll("[data-cell-eye]").forEach((btn) => {
    btn.addEventListener("click", () => {
      CARD_FOLD.toggleHideIdle(btn.dataset.cellEye);
      renderTopology();
    });
  });
  // A machine's chips: all its cells, or only the ones one launcher runs.
  $("topologyLlamaServers")?.querySelectorAll("[data-cell-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      CARD_FOLD.setLauncher(btn.dataset.cellFilter, btn.dataset.cellFilterId || "");
      renderTopology();
    });
  });
  // An engine's model next to the cells: load it or unload it (step 3).
  $("topologyLlamaServers")?.querySelectorAll("[data-engine-act]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      actOnEngineButton(btn);
    });
  });
  // A model downloaded into an engine (step 3д).
  $("topologyLlamaServers")?.querySelectorAll("[data-engine-pull]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      pullEngineButton(btn);
    });
  });
  // An engine's server itself: start it or stop it (step 3г).
  $("topologyLlamaServers")?.querySelectorAll("[data-engine-serve]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      serveEngineButton(btn);
    });
  });
  // An engine's model next to the cells: make it a router output, or stop.
  $("topologyLlamaServers")?.querySelectorAll("[data-engine-expose]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      btn.disabled = true;
      setEngineModelExposed(btn.dataset.engineExpose, btn.dataset.engineKind, btn.dataset.engineModel,
        btn.dataset.engineExposed !== "1");
    });
  });
  // A machine's one ✕: let go of its scout, or forget a silent one.
  $("topologyLlamaServers")?.querySelectorAll("[data-scout-disconnect]").forEach((btn) => {
    btn.addEventListener("click", () => disconnectScout(btn.dataset.scoutDisconnect));
  });
  // The controller machine's node: "Servers" header toggles the mounted
  // Server stats slot.
  $("topologyLlamaServers")?.querySelectorAll("[data-ctrl-stats-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => toggleCtrlServerStats(btn));
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
  // Power-cycle a host. Confirmed with the host's own name spelled out, because
  // the two headers look alike and rebooting the controller takes the board down
  // with it. Reboot only — nothing here can switch a headless box back on.
  $("topologyLlamaServers")?.querySelectorAll("[data-reboot-host]").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const hostId = btn.getAttribute("data-reboot-host") || "";
      const isCtrl = isControllerMachine(hostId);
      const ok = await appConfirm(
        t(hostPowerTextKey(hostId, "reboot")).replace("{host}", hostId),
        { confirmLabel: t("hostRebootOk"), scene: "stop" });
      if (!ok) return;
      try {
        const res = await api("/api/host/reboot", {
          method: "POST", body: JSON.stringify({ hostId }),
        });
        toast(res?.ok ? t("hostRebootIssued").replace("{host}", hostId)
                      : (res?.result?.error || t("hostRebootFailed")));
      } catch (err) {
        // The controller rebooting itself kills this very request — a transport
        // error here is the expected shape of success, not a failure to report.
        toast(isCtrl ? t("hostRebootIssued").replace("{host}", hostId) : err.message);
      }
    });
  });

  // Power off. Everything about this is one step heavier than reboot, because
  // the board cannot undo it: no button here switches a machine back on, so a
  // wrong click ends with someone walking to the rack.
  //
  // The gate is TYPING the host's name, not clicking through a warning. A
  // confirm dialog is one keystroke from a reflex; spelling out the name cannot
  // be done by muscle memory, and it forces the operator to read which host
  // they are on — the two node headers look alike, which is the mistake worth
  // preventing.
  $("topologyLlamaServers")?.querySelectorAll("[data-poweroff-host]").forEach((btn) => {
    btn.addEventListener("click", async (event) => {
      event.stopPropagation();
      const hostId = btn.getAttribute("data-poweroff-host") || "";
      const isCtrl = isControllerMachine(hostId);
      const typed = await appPrompt(
        t(hostPowerTextKey(hostId, "poweroff")).replace("{host}", hostId),
        { text: t("hostPowerOffWarning").replace("{host}", hostId),
          placeholder: hostId, confirmLabel: t("hostPowerOffOk"), scene: "stop" });
      // Cancel resolves null; an inexact answer is treated as cancel rather
      // than as an error, because the operator has already decided by then.
      if ((typed || "").trim() !== hostId) {
        if (typed != null) toast(t("hostPowerOffNameMismatch").replace("{host}", hostId));
        return;
      }
      try {
        const res = await api("/api/host/poweroff", {
          method: "POST", body: JSON.stringify({ hostId }),
        });
        toast(res?.ok ? t("hostPowerOffIssued").replace("{host}", hostId)
                      : (res?.result?.error || t("hostPowerOffFailed")));
      } catch (err) {
        // Powering off the controller kills this very request — a transport
        // error is the expected shape of success here, exactly as for reboot.
        toast(isCtrl ? t("hostPowerOffIssued").replace("{host}", hostId) : err.message);
      }
    });
  });

  // ⏰ Scheduled poweroff editor.
  $("topologyLlamaServers")?.querySelectorAll("[data-power-schedule-host]").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      const hostId = btn.getAttribute("data-power-schedule-host") || "";
      const node = (topology?.nodes || []).find((n) => String(n.id) === hostId);
      openHostPowerScheduleModal(hostId, node?.powerSchedule || {});
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

// The board is "ready" for automation the moment its content has rendered ONCE
// — every later refresh is an update, not an arrival. See docs/testability.md.
let _boardRenderedOnce = false;

export async function refreshTopology() {
  setTopology(await api("/api/topology"));
  // Structure-aware: full rebuild only when the graph changed, else a cheap
  // in-place patch — and never rebuild mid-interaction (deferred).
  applyTopologyUpdate();
  if (!_boardRenderedOnce) {
    _boardRenderedOnce = true;
    markPageState("ready");
  }
  prefetchAllSubscriptionModels();
  // Daily spend is a DAILY aggregate and it rode this tick — which fires every
  // 1.5-5s, so the board asked for yesterday's totals up to forty times a
  // minute. main.js owns it on a 60s timer; that is the right cadence for a
  // number that changes once a day.
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
  // A field in a block the render never replaces (data-survives-render: the
  // "+ Add scout" address) does not defer it — nothing is rebuilt under it.
  // It did: while the address had the focus the board stood still, and a
  // scout added with Enter did not appear until the focus moved on.
  const ae = document.activeElement;
  return !!(ae && ae.matches
            && ae.matches("select, textarea, input:not([type=checkbox]):not([type=radio])")
            && !(ae.closest && ae.closest("[data-survives-render]")));
}

// Exact phase string — used as a structural key. The fast-moving bits inside a
// phase (download %, t/s, ctx) are NOT in the phase, so they stay live-patched;
// any phase transition (downloading→loading→running) is structural → full render.
export function topologyServerPhase(s) {
  return (s.phase) || (s.status && s.status.phase) || "stopped";
}

// Identity of the graph: anything that changes which cards/handles/cables exist
// or how they connect. Deliberately EXCLUDES fast-moving numbers (t/s, VRAM,
// ageSeconds, ctxUsed, download %), which syncTopologyLive() patches in place.
export function topologyStructureFingerprint() {
  if (!topology) return "";
  const server = topology.server || {};
  // Agents and the SETTINGS on their routes go into the fingerprint on equal
  // footing with the assignments themselves: anything missing here doesn't
  // appear on the board until the page reloads — and reads as "didn't save".
  // That's exactly what happened: an agent created by hand sat invisible in
  // the record, and the context-window chip kept showing the old number. The
  // model name and its lock are the same kind of setting: while they weren't
  // included here, the operator would press the lock, the server would
  // record it, and the board would keep showing the old state until a
  // reload — which is exactly "didn't save".
  const clients = (topology.clients || [])
    .map((c) => {
      // Takes what the board actually DRAWS. While a reader that preferred
      // the scout's live report stood here, an edit to the stored record (the
      // context window) never reached the fingerprint: the board stayed
      // silent until a reload. The live report is gone (2026-09-24); the
      // stored rows are what is drawn.
      const routes = topologyBoardAssignmentsForHost(c.id)
        .map((row) => `${row.agentId}=` + (row.routes || [])
          .map((r) => `${r.role}@${r.proxyId || ""}#${r.contextLength || ""}${r.contextAuto ? "A" : ""}`
                       + `~${r.modelName || ""}${r.modelNameAuto ? "O" : ""}`)
          .sort().join("+"))
        .sort().join(";");
      return `${c.id}:${c.name || ""}:`
        + `${(c.agents || []).map((a) => a.id).sort().join("|")}:${routes}`;
    })
    .sort().join(",");
  // Which machines are on the board and whether their scouts answer: a host
  // appearing, or going silent, adds or removes a node's banner — structure.
  // Its age is not; the live patcher moves that.
  const hosts = (topology.nodes || [])
    .map((n) => `${n.id}:${n.online ? 1 : 0}:${n.scoutVersion ? 1 : 0}`)
    .sort().join(",");
  // Autostart is a setting of the card like the model: while ↟ was not here,
  // pressing it left the button spinning until something else changed — the
  // server had done it, the board still said "working" (2026-09-24).
  const classicSrv = (server.llamaServers || [])
    .map((s) => `${s.id}:${s.port}:${s.model || ""}:${topologyServerPhase(s)}:${s.reachable === false ? 0 : 1}`
                + `:${s.bootEnabled ? 1 : 0}${s.bootSupported ? 1 : 0}`)
    .sort().join(",");
  const nodeSrv = (topology.nodes || [])
    .flatMap((n) => (n.servers || []).map((s) =>
      `${n.id}/${s.port}:${s.model || ""}:${topologyServerPhase(s)}:${s.reachable === false ? 0 : 1}`
      + `:${s.bootEnabled ? 1 : 0}${s.bootSupported ? 1 : 0}`))
    .sort().join(",");
  const gpus = (topology.nodes || [])
    .flatMap((n) => (n.gpus || []).map((g) => `${n.id}/${g.index}`))
    .sort().join(",");
  // The engines next to the cells (scout 2.12+): one coming or going, a
  // model loading or unloading, its window or its keep_alive moving — the
  // card says each, so each rebuilds it. Its memory is live (the patcher).
  const engines = (topology.nodes || [])
    .flatMap((n) => (Array.isArray(n.engines) ? n.engines : []).map((e) =>
      `${n.id}/${e.kind}:${e.port}:${e.state}:${e.listen}:${e.version}:${e.installedKnown === false ? 0 : 1}:`
      + `${e.reachable === false ? 0 : 1}${e.blockedBy || ""}:${e.firewall?.state || ""}:${(e.controls || []).join("+")}`
      + `${e.holds === true ? "~" : ""}:${e.runBy || ""}${e.autostart === true ? "^" : ""}`
      + `${e.serverAction?.op || ""}${e.serverError?.at || ""}${e.downloading?.model || ""}${e.downloadError?.at || ""}:`
      + (Array.isArray(e.models) ? e.models : [])
        .map((m) => `${m.name}${m.loaded === true ? "+" : m.loaded === false ? "-" : "?"}${m.contextLength ?? ""}@${m.expiresAt || ""}${m.exposed === true ? "#" : ""}`
          + `${m.action?.op || ""}${m.actionError?.at || ""}${m.staysLoaded === true ? "∞" : ""}`)
        .join("|")))
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
    .map((n) => `${n.id}:${(n.llamaBinaryVersion || "").slice(0, 40)}:${(n.llamaBinaryMtime || "").slice(0, 19)}:${n.llamaUpdate?.running ? 1 : 0}:${(n.powerSchedule || {}).enabled ? (n.powerSchedule.at || "") : ""}`)
    .sort().join(",");
  const view = `${topologyNodesViewOn ? 1 : 0}:${[..._collapsedNodes].sort().join("+")}`;
  // In-flight cell actions are structural: adding/clearing one must re-render
  // the card even when the server-side topology has not moved yet.
  const pendingCells = `${[..._pendingCellActions.keys()].sort().join("+")}:${[..._stoppingCells].sort().join("+")}`;
  const modals = `${ui.topologyProxyFormOpen ? 1 : 0}:${topologyQueuePriorityModalOpen ? 1 : 0}:${topologyRouteDetail?.proxyId || ""}`;
  return [clients, hosts, classicSrv, nodeSrv, gpus, engines, prox, cloud, llamaVer, view, pendingCells, modals].join("||");
}

// Decide between a full structural rebuild and a cheap in-place live patch —
// and never rebuild while the user is interacting (defer until they finish).
export function applyTopologyUpdate() {
  if (!topology) return;
  SUSPECT_BANNER.render();
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
  } else {
    syncTopologyLive();        // patch volatile numbers, keep DOM + animations
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
    updatedEl.textContent = `${t("topologyUpdatedLabel")} ${new Date(topology.time * 1000).toLocaleTimeString()}`;
  }

  (topology.nodes || []).forEach((n) => {
    const nodeEl = document.querySelector(`.node-card[data-node-id="${CSS.escape(n.id)}"]`);
    if (!nodeEl) return;

    // A silent scout's age grows every tick; the banner itself comes and goes
    // with a full render (the host's state is in the fingerprint).
    _liveSet(nodeEl, "[data-live-hostage]", hostAgeText(n));

    // Header now carries only the platform. Live CPU load% and RAM moved into
    // the CPU block below the GPUs, mirroring a GPU row's util/VRAM.
    const cpu = n.cpu || {}, ram = cpu.ram || {};
    _liveSet(nodeEl, "[data-live-nodemeta]", n.platform || "");
    _liveSet(nodeEl, "[data-live-cpuload]", cpu.loadPct != null ? `${cpu.loadPct}%` : "");
    _liveSet(nodeEl, "[data-live-cpuram]", ram.usedGb != null ? `RAM ${ram.usedGb}/${ram.totalGb} GB`
      : (ram.totalGb != null ? `RAM ${ram.totalGb} GB` : ""));
    const ramBar = nodeEl.querySelector("[data-live-cpurambar]");
    if (ramBar) {
      const rt = Number(ram.totalGb || 0), ru = Number(ram.usedGb || 0);
      const rp = rt > 0 ? Math.min(100, Math.round((ru / rt) * 100)) : 0;
      ramBar.title = `${ru.toFixed(1)} / ${rt.toFixed(1)} GB`;
      const sp = ramBar.querySelector("span");
      if (sp) sp.style.width = `${rp}%`;
    }
    // An engine's memory moves between reports; what it has loaded and how
    // it answers are structure (the fingerprint) and rebuild its card.
    (Array.isArray(n.engines) ? n.engines : []).forEach((e) => {
      const card = nodeEl.querySelector(`[data-t="node-engine"][data-t-id="${CSS.escape(`${n.id}:${e.kind}:${e.port}`)}"]`);
      if (card) {
        _liveSet(card, "[data-live-engine-ram]", engineRamText(e));
        _liveSet(card, "[data-live-engine-vram]", engineVramText(n, e));
        _liveSet(card, "[data-live-engine-download]", engineDownloadText(e));
      }
    });

    // Server cards: token speed, context usage, download progress.
    (n.servers || []).forEach((s) => {
      const card = nodeEl.querySelector(`.node-server[data-llama-port="${CSS.escape(String(s.port))}"]`);
      if (!card) return;
      const running = topologyServerPhase(s) === "running";
      // A folded cell's line carries the one live number it shows — generation
      // speed — and breathes while it generates; the card behind it is patched
      // below as always, for the moment it floats open.
      const line = nodeEl.querySelector(`.cell-row[data-llama-port="${CSS.escape(String(s.port))}"]`);
      if (line) {
        const gen = running ? Number(s.genTps || 0) : 0;
        _liveSet(line, "[data-live-rowtps]", gen > 0 ? `${formatTps(gen)} t/s` : "");
        line.classList.toggle("busy", gen > 0);
      }
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
        // The outside owners' bands — the same function as the first render.
        const outsides = barWrap.querySelector("[data-live-gpuoutside]");
        const [outsideHtml, outsideKey] = gpuOutsideBar(g);
        if (outsides && outsides.dataset.key !== outsideKey) {
          outsides.innerHTML = outsideHtml;
          outsides.dataset.key = outsideKey;
        }
      }
      // Who holds the card: fleet ports and everyone else by name, or idle.
      const whoEl = row.querySelector("[data-live-gpuwho]");
      if (whoEl) {
        const html = gpuWhoHtml(g);
        if (whoEl.innerHTML !== html) whoEl.innerHTML = html;
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
  renderLlamaCpp();
  renderKnownProblems();
  renderTopology();
}

