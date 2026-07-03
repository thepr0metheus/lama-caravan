// The delegated pointer/click router for the whole board + drag state.
import { appConfirm } from "./dialogs.js";
import {
  highlightTopologyCable,
  scheduleClearTopologyCableHighlight,
  topologyProxyClass,
  topologyRouteClass,
} from "./cables.js";
import { _cvPos, _cvQueueHistData, _cvQueueHistOpen, _cvSchedHistData, _cvSchedHistOpen, _cvView, _fetchQueueHist, _fetchSchedHist, bindCanvasInteractions, canvasLoadPositions, cvSetViewport, drawCanvasConnectors, scheduleOutputColor } from "./canvas.js";
import {
  closeChartModal,
  closeRouteActivityModal,
  openChartModal,
  openRouteActivityModal,
} from "./charts.js";
import {
  closeCloudBlockModal,
  closeCloudProviderModal,
  deleteCloudAccount,
  deleteCloudBlock,
  openCloudAccountModal,
  openCloudBlockModal,
  saveCloudAccount,
  saveCloudBlock,
  selectCloudProviderType,
  startCloudOauthLogin,
  topologyCloudBlockForm,
} from "./cloud.js";
import { openRequestHistory } from "./history.js";
import { t } from "./i18n.js";
import { closeConfirmModal } from "./llama-edit.js";
import { deleteOrphanAgent } from "./remote-cells.js";
import {
  routerById,
  saveRouters,
  setCloudModelExposed,
  topologyOutputsCloudExpanded,
} from "./routers.js";
import { setTopology, topology, ui } from "./state.js";
import { loadRouteTokenHistory, proxyEffectiveWaitTimeout } from "./topology-activity.js";
import {
  _fmtSec,
  _queuePctExampleText,
  closeAgentConfigModal,
  closeClientDetail,
  closePriorityModal,
  closeQueuePriorityModal,
  closeRawConfigViewer,
  editTopologyClientAlias,
  openAgentConfigModal,
  openClientDetail,
  openQueuePriorityModal,
  openRawConfigViewer,
  refreshClientDetail,
  savePriorityModal,
  saveQueuePriorityModal,
  scheduleGridToRules,
  scheduleRulesToGrid,
  setTopologyProxyRoutePolicy,
  topologyAgentConfigAgentId,
  topologyAgentConfigClientId,
  topologyPriorityOrder,
  topologyQueuePriorityEdits,
} from "./topology-modals.js";
import { closeIncidentsModal } from "./topology-nodes.js";
import {
  deleteTopologyProxy,
  editTopologyProxy,
  saveTopologyProxyForm,
} from "./topology-proxies.js";
import { flushPendingTopologyRender, renderTopology } from "./topology-render.js";
import {
  apiCostsCache,
  fetchApiCosts,
  fetchOpenRouterLimits,
  fetchSubscriptionUsage,
  fetchUsageStats,
  openrouterLimitsCache,
  saveApiPrice,
  saveLocalPricing,
  subscriptionUsageCache,
  usageStatsApiPriceEdit,
  usageStatsData,
} from "./usage-stats.js";
import { $, api, pill, toast } from "./utils.js";

export let topologyPointerDrag = null;
export let topologyScheduleRouterId = "";         // which router's weekly schedule editor is open
export let topologySchedulePaintOutput = "";  // output id currently selected for painting ("" = clear)
export let topologyScheduleGrid = null;       // working [7][24] grid of outputId|"" while editing
export let _schedulePainting = false;
export let _schedulePointerUpBound = false;
export let topologyProxySummaryOpen = false; // proxy port summary JSON viewer
export let topologyLlamaDetailOpen = false;
export let topologyGpuModalOpen = false;
export let topologyRouteDetail = null;
export function bindTopologyDragAndDrop() {
  const summaryButton = $("topologyProxySummaryBtn");
  if (summaryButton) summaryButton.onclick = () => {
    topologyProxySummaryOpen = true;
    renderTopology();
  };
  document.querySelector("[data-topology-proxy-summary-close]")?.addEventListener("click", () => {
    topologyProxySummaryOpen = false;
    renderTopology();
  });
  document.querySelector("[data-topology-proxy-summary-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyProxySummaryOverlay !== undefined) {
      topologyProxySummaryOpen = false;
      renderTopology();
    }
  });
  // Proxy Ports registry: router reassign + add port
  document.querySelectorAll("[data-proxy-reg-router]").forEach((sel) => {
    sel.addEventListener("change", () => {
      setTopologyProxyRoutePolicy(sel.dataset.proxyRegRouter, { routerId: sel.value }).catch((e) => toast(e.message));
    });
  });
  document.querySelector("[data-proxy-reg-add]")?.addEventListener("click", () => {
    ui.topologyProxyEditingId = "";
    ui.topologyProxyFormOpen = true;
    renderTopology();
  });
  // Dead-agent rows: delete the orphaned assignment + free its ports.
  document.querySelectorAll("[data-orphan-agent-delete-client]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteOrphanAgent(btn.dataset.orphanAgentDeleteClient, btn.dataset.orphanAgentDeleteId);
    });
  });
  // ── Agent openclaw config viewer ─────────────────────────────────────────
  document.querySelectorAll("[data-agent-config-open]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const mode = btn.dataset.agentConfigOpen;
      const clientId = btn.dataset.clientId;
      const agentId = btn.dataset.agentId;
      openAgentConfigModal(clientId, agentId, mode).catch((err) => toast(err.message));
    });
  });
  document.querySelector("[data-agent-config-close]")?.addEventListener("click", closeAgentConfigModal);
  document.querySelector("[data-agent-config-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.agentConfigOverlay !== undefined) closeAgentConfigModal();
  });
  document.querySelector("[data-agent-config-refresh]")?.addEventListener("click", () => {
    if (ui.topologyAgentConfigMode) {
      openAgentConfigModal(topologyAgentConfigClientId, topologyAgentConfigAgentId, ui.topologyAgentConfigMode)
        .catch((err) => toast(err.message));
    }
  });
  document.querySelectorAll("[data-agent-config-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      ui.topologyAgentConfigMode = btn.dataset.agentConfigMode;
      renderTopology();
    });
  });
  const logsButton = $("topologyLogsBtn");
  // topologyLogsBtn removed — no longer used
  document.querySelector("[data-topology-proxy-save]")?.addEventListener("click", () => {
    saveTopologyProxyForm().catch((err) => toast(err.message));
  });
  // Roll a fresh data-plane API key into the form field (saved on Save).
  document.querySelector("[data-proxy-genkey]")?.addEventListener("click", () => {
    const input = document.querySelector('[data-topology-proxy-form] [name="apiKey"]');
    if (!input) return;
    const bytes = crypto.getRandomValues(new Uint8Array(24));
    input.value = "lcv1_" + [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  });
  document.querySelector("[data-topology-proxy-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyProxyOverlay !== undefined) {
      ui.topologyProxyFormOpen = false;
      ui.topologyProxyEditingId = "";
      renderTopology();
    }
  });
  // "Add Cloud Provider" button is now rendered dynamically — handled via delegation below
  const historyBtn = $("topologyRequestHistoryBtn");
  if (historyBtn) historyBtn.addEventListener("click", () => openRequestHistory());
  // Route Activity expand modal
  document.querySelectorAll("[data-open-route-activity]").forEach((el) => {
    el.addEventListener("click", () => openRouteActivityModal(el.dataset.routeNode || null));
  });
  $("routeActivityClose")?.addEventListener("click", closeRouteActivityModal);
  $("routeActivityOverlay")?.addEventListener("click", (e) => {
    if (e.target === $("routeActivityOverlay")) closeRouteActivityModal();
  });
  // Chart expand modals (GPU History, Token Speed, VRAM, Power)
  document.querySelectorAll("[data-open-chart]").forEach((el) => {
    el.addEventListener("click", () => openChartModal(el.dataset.openChart));
  });
  $("chartExpandClose")?.addEventListener("click", closeChartModal);
  $("chartExpandOverlay")?.addEventListener("click", (e) => {
    if (e.target === $("chartExpandOverlay")) closeChartModal();
  });
  // Incidents modal
  $("incidentsModalClose")?.addEventListener("click", closeIncidentsModal);
  $("incidentsModalOverlay")?.addEventListener("click", (e) => {
    if (e.target === $("incidentsModalOverlay")) closeIncidentsModal();
  });
  // block row clicks → open block modal
  document.querySelectorAll("[data-cloud-block]").forEach((row) => {
    const open = () => openCloudBlockModal(row.dataset.cloudBlock, null);
    row.addEventListener("click", open);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });
  // account edit / add-block buttons
  document.querySelectorAll("[data-cloud-edit-account]").forEach((btn) => {
    btn.addEventListener("click", (e) => { e.stopPropagation(); openCloudAccountModal(btn.dataset.cloudEditAccount); });
  });
  document.querySelectorAll("[data-cloud-add-block]").forEach((btn) => {
    btn.addEventListener("click", (e) => { e.stopPropagation(); openCloudBlockModal(null, btn.dataset.cloudAddBlock); });
  });
  document.querySelectorAll("[data-cloud-fetch-models]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = btn.dataset.cloudFetchModels;
      btn.textContent = "↻ fetching…"; btn.disabled = true;
      try {
        const res = await api("/api/cloud-accounts/auto-create-blocks", { method: "POST", body: JSON.stringify({ id }) });
        if (res.topology) setTopology(res.topology);
        toast(res.created > 0 ? `${res.created} model${res.created !== 1 ? "s" : ""} added (${res.total} available)` : `models up to date (${res.total} available)`);
        renderTopology();
      } catch (err) { toast(`fetch failed: ${err.message}`); btn.textContent = "↻ Fetch models from provider"; btn.disabled = false; }
    });
  });
  // account modal
  document.querySelector("[data-cloud-close]")?.addEventListener("click", closeCloudProviderModal);
  document.querySelector("[data-cloud-cancel]")?.addEventListener("click", closeCloudProviderModal);
  document.querySelector("[data-topology-cloud-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyCloudOverlay !== undefined) closeCloudProviderModal();
  });
  document.querySelector("[data-cloud-save]")?.addEventListener("click", () => {
    saveCloudAccount().catch((err) => toast(err.message));
  });
  document.querySelector("[data-cloud-delete-account]")?.addEventListener("click", () => {
    const name = ui.topologyCloudForm
      ? ((topology?.cloudAccounts || []).find((a) => a.id === ui.topologyCloudForm.accountId)?.name || "this account")
      : "this account";
    $("confirmTitle").textContent = t("topologyCloudDeleteAccount");
    $("confirmText").textContent = `Delete "${name}"? All model blocks will be removed.`;
    $("confirmMeta").hidden = true;
    $("confirmPath").textContent = "";
    $("confirmDelete").textContent = t("topologyCloudDeleteAccount");
    $("confirmDelete").classList.add("danger");
    ui.pendingConfirm = () => { closeConfirmModal(); deleteCloudAccount().catch((err) => toast(err.message)); };
    $("confirmOverlay").hidden = false;
  });
  // Subscription usage refresh buttons (event delegation on topology container)
  document.getElementById("topologyCloudProviders")?.addEventListener("click", (e) => {
    const subBtn = e.target.closest("[data-usage-refresh]");
    if (subBtn) {
      e.stopPropagation();
      const id = subBtn.dataset.usageRefresh;
      if (id) { subscriptionUsageCache.delete(id); fetchSubscriptionUsage(id); }
      return;
    }
    const costBtn = e.target.closest("[data-api-costs-refresh]");
    if (costBtn) {
      e.stopPropagation();
      const id = costBtn.dataset.apiCostsRefresh;
      if (id) { apiCostsCache.delete(id); fetchApiCosts(id); }
      return;
    }
    const orBtn = e.target.closest("[data-or-limits-refresh]");
    if (orBtn) {
      e.stopPropagation();
      const id = orBtn.dataset.orLimitsRefresh;
      if (id) { openrouterLimitsCache.delete(id); fetchOpenRouterLimits(id); }
    }
  });
  document.querySelectorAll("[data-cloud-field]").forEach((input) => {
    const evt = input.tagName === "SELECT" ? "change" : "input";
    input.addEventListener(evt, () => {
      if (!ui.topologyCloudForm) return;
      const field = input.dataset.cloudField;
      const value = input.value;
      if (field === "authMode") { ui.topologyCloudForm.authMode = value; renderTopology(); return; }
      const oauthMap = { oauthClientId: "clientId", oauthAuthorizeUrl: "authorizeUrl", oauthTokenUrl: "tokenUrl", oauthScope: "scope", oauthRedirectPort: "redirectPort" };
      if (oauthMap[field]) {
        ui.topologyCloudForm.oauthConfig = ui.topologyCloudForm.oauthConfig || {};
        ui.topologyCloudForm.oauthConfig[oauthMap[field]] = field === "oauthRedirectPort" ? Number(value) : value;
        return;
      }
      ui.topologyCloudForm[field] = value;
    });
  });
  document.querySelector("[data-cloud-oauth-login]")?.addEventListener("click", () => {
    startCloudOauthLogin().catch((err) => toast(err.message));
  });
  // block modal
  document.querySelector("[data-cloud-block-close]")?.addEventListener("click", closeCloudBlockModal);
  document.querySelector("[data-cloud-block-cancel]")?.addEventListener("click", closeCloudBlockModal);
  document.querySelector("[data-topology-cloud-block-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyCloudBlockOverlay !== undefined) closeCloudBlockModal();
  });
  document.querySelector("[data-cloud-block-save]")?.addEventListener("click", () => {
    saveCloudBlock().catch((err) => toast(err.message));
  });
  document.querySelector("[data-cloud-delete-block]")?.addEventListener("click", () => {
    const model = topologyCloudBlockForm?.model || topologyCloudBlockForm?.blockName || topologyCloudBlockForm?.blockId || "this model block";
    $("confirmTitle").textContent = t("topologyCloudDeleteBlock");
    $("confirmText").textContent = `Remove model block "${model}"?`;
    $("confirmMeta").hidden = true;
    $("confirmPath").textContent = "";
    $("confirmDelete").textContent = t("topologyCloudDeleteBlock");
    $("confirmDelete").classList.add("danger");
    ui.pendingConfirm = () => { closeConfirmModal(); deleteCloudBlock().catch((err) => toast(err.message)); };
    $("confirmOverlay").hidden = false;
  });
  document.querySelectorAll("[data-block-field]").forEach((input) => {
    const evt = input.tagName === "SELECT" ? "change" : "input";
    input.addEventListener(evt, () => {
      if (!topologyCloudBlockForm) return;
      topologyCloudBlockForm[input.dataset.blockField] = input.value;
    });
  });
  // picker
  document.querySelector("[data-cloud-picker-close]")?.addEventListener("click", closeCloudProviderModal);
  document.querySelector("[data-cloud-picker-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.cloudPickerOverlay !== undefined) closeCloudProviderModal();
  });
  document.querySelectorAll("[data-pick-type]").forEach((tile) => {
    tile.addEventListener("click", () => selectCloudProviderType(tile.dataset.pickType));
  });
  document.querySelector("[data-cloud-picker-change]")?.addEventListener("click", () => {
    ui.topologyCloudPickerOpen = true;
    ui.topologyCloudModalOpen = false;
    ui.topologyCloudForm = null;
    renderTopology();
  });
  document.querySelectorAll("[data-topology-client-detail]").forEach((trigger) => {
    const open = () => {
      const clientId = trigger.dataset.topologyClientDetail;
      const agentId = trigger.dataset.agentId || "";
      const agentName = agentId
        ? ((topology?.clients || []).find((c) => c.id === clientId)?.agents || []).find((a) => a.id === agentId)?.name || agentId
        : "";
      openClientDetail(clientId, agentName);
    };
    trigger.addEventListener("click", open);
    if (trigger.tagName !== "BUTTON") {
      trigger.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    }
  });
  document.querySelectorAll("[data-topology-gpu-modal]").forEach((el) => {
    const open = () => { topologyGpuModalOpen = true; renderTopology(); };
    el.addEventListener("click", open);
    el.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });
  document.querySelector("[data-topology-gpu-modal-close]")?.addEventListener("click", () => {
    topologyGpuModalOpen = false; renderTopology();
  });
  document.querySelector("[data-topology-gpu-modal-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyGpuModalOverlay !== undefined) { topologyGpuModalOpen = false; renderTopology(); }
  });
  // ── Usage & spend statistics modal (open button is static in the header) ──
  document.querySelector("[data-usage-stats-close]")?.addEventListener("click", () => {
    ui.usageStatsModalOpen = false; renderTopology();
  });
  document.querySelector("[data-usage-stats-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.usageStatsOverlay !== undefined) { ui.usageStatsModalOpen = false; renderTopology(); }
  });
  document.querySelectorAll("[data-usage-stats-days]").forEach((el) => {
    el.addEventListener("click", () => {
      ui.usageStatsDays = Number(el.dataset.usageStatsDays) || 30;
      ui.usageStatsExpanded = "";
      fetchUsageStats();
    });
  });
  document.querySelectorAll("[data-usage-stats-scope]").forEach((el) => {
    el.addEventListener("click", () => {
      ui.usageStatsScope = el.dataset.usageStatsScope;
      ui.usageStatsExpanded = "";
      renderTopology();
    });
  });
  document.querySelectorAll("[data-usage-stats-model]").forEach((el) => {
    const toggle = () => {
      const k = el.dataset.usageStatsModel;
      ui.usageStatsExpanded = ui.usageStatsExpanded === k ? "" : k;
      renderTopology();
    };
    el.addEventListener("click", toggle);
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
  });
  document.querySelectorAll("[data-usage-stats-rate]").forEach((el) => {
    el.addEventListener("input", () => {
      ui.usageStatsRateEdit = ui.usageStatsRateEdit
        || { ...((usageStatsData && usageStatsData.rate) || { inputPer1M: 0, outputPer1M: 0 }) };
      ui.usageStatsRateEdit[el.dataset.usageStatsRate] = Number(el.value) || 0;
    });
  });
  document.querySelector("[data-usage-stats-rate-save]")?.addEventListener("click", saveLocalPricing);
  // Per-model API price editor (cloud / subscription drill-down)
  document.querySelectorAll("[data-us-apiprice]").forEach((el) => {
    el.addEventListener("input", () => {
      const model = el.dataset.usApipriceModel;
      const cur = usageStatsApiPriceEdit[model] || {};
      cur[el.dataset.usApiprice] = Number(el.value) || 0;
      usageStatsApiPriceEdit[model] = cur;
    });
    // Don't let clicks inside the editor toggle the row collapse.
    el.addEventListener("click", (e) => e.stopPropagation());
  });
  document.querySelectorAll("[data-us-price-row]").forEach((el) => {
    el.addEventListener("click", (e) => e.stopPropagation());
  });
  document.querySelectorAll("[data-us-apiprice-save]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      saveApiPrice(el.dataset.usApipriceSave);
    });
  });
  document.querySelectorAll("[data-topology-llama-detail]").forEach((el) => {
    const open = () => { topologyLlamaDetailOpen = true; renderTopology(); };
    el.addEventListener("click", open);
    el.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });
  document.querySelector("[data-topology-llama-detail-close]")?.addEventListener("click", () => {
    topologyLlamaDetailOpen = false; renderTopology();
  });
  document.querySelector("[data-topology-llama-detail-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyLlamaDetailOverlay !== undefined) { topologyLlamaDetailOpen = false; renderTopology(); }
  });
  document.querySelector("[data-topology-client-detail-close]")?.addEventListener("click", closeClientDetail);
  document.querySelector("[data-topology-client-detail-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyClientDetailOverlay !== undefined) closeClientDetail();
  });
  document.querySelector("[data-topology-client-detail-refresh]")?.addEventListener("click", () => {
    refreshClientDetail().catch((err) => toast(err.message));
  });
  // Queue & Priority unified modal
  document.querySelectorAll("[data-topology-queue-priority-open]").forEach((element) => {
    const open = () => openQueuePriorityModal(null);
    element.addEventListener("click", open);
    element.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    });
  });
  document.querySelector("[data-topology-queue-priority-close]")?.addEventListener("click", closeQueuePriorityModal);
  document.querySelector("[data-topology-queue-priority-cancel]")?.addEventListener("click", closeQueuePriorityModal);
  document.querySelector("[data-topology-queue-priority-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyQueuePriorityOverlay !== undefined) closeQueuePriorityModal();
  });
  document.querySelector("[data-topology-queue-priority-save]")?.addEventListener("click", () => {
    saveQueuePriorityModal().catch((err) => toast(err.message));
  });
  // ── Raw config viewer ─────────────────────────────────────────────────────
  document.querySelector("[data-topology-raw-config]")?.addEventListener("click", () => {
    openRawConfigViewer().catch((err) => toast(err.message));
  });
  document.querySelector("[data-topology-raw-close]")?.addEventListener("click", closeRawConfigViewer);
  document.querySelector("[data-topology-raw-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyRawOverlay !== undefined) closeRawConfigViewer();
  });
  // ── Priority modal handlers ──────────────────────────────────────────────
  document.querySelector("[data-topology-priority-close]")?.addEventListener("click", closePriorityModal);
  document.querySelector("[data-topology-priority-cancel]")?.addEventListener("click", closePriorityModal);
  document.querySelector("[data-topology-priority-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyPriorityOverlay !== undefined) closePriorityModal();
  });
  document.querySelector("[data-topology-priority-save]")?.addEventListener("click", () => {
    savePriorityModal().catch((err) => toast(err.message));
  });
  document.querySelectorAll("[data-priority-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      const id = button.dataset.priorityRemove;
      const idx = topologyPriorityOrder.indexOf(id);
      if (idx !== -1) {
        topologyPriorityOrder.splice(idx, 1);
        renderTopology();
      }
    });
  });
  // (expand/collapse removed — per-proxy sliders are always visible)
  // ── Per-proxy drag handles ───────────────────────────────────────────────
  (function attachQpProxyHandles() {
    document.querySelectorAll("[data-qp-proxy-handle]").forEach((handle) => {
      const port = Number(handle.dataset.qpProxyHandle);
      const pctKey = handle.dataset.qpPctKey;
      const MIN = pctKey === "queueAbortPct" ? 1 : 0;
      const proxy = (topology?.proxies || []).find((p) => Number(p.port) === port);
      const eff = proxy ? proxyEffectiveWaitTimeout(proxy) : 0;
      const wt = eff > 0 ? eff : 3600;
      const track = handle.closest("[data-qp-proxy-track]");

      function updateHandleLive(pct) {
        handle.style.left = pct + "%";
        const timeEl = handle.querySelector(".qp-handle-time");
        if (timeEl) timeEl.textContent = _fmtSec(Math.round(wt * pct / 100));
        const fill = track?.querySelector("[data-qp-proxy-fill]");
        if (fill && pctKey === "queueAbortPct") fill.style.width = pct + "%";
      }
      function applyPct(pct) {
        if (!topologyQueuePriorityEdits.routes) topologyQueuePriorityEdits.routes = {};
        if (!topologyQueuePriorityEdits.routes[port]) topologyQueuePriorityEdits.routes[port] = {};
        topologyQueuePriorityEdits.routes[port][pctKey] = pct;
        updateHandleLive(pct);
      }
      const onMove = (clientX) => {
        if (!track) return;
        const rect = track.getBoundingClientRect();
        applyPct(Math.max(MIN, Math.min(100, Math.round((clientX - rect.left) / rect.width * 100))));
      };
      handle.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const onMM = (e2) => onMove(e2.clientX);
        const onMU = () => { document.removeEventListener("mousemove", onMM); document.removeEventListener("mouseup", onMU); };
        document.addEventListener("mousemove", onMM);
        document.addEventListener("mouseup", onMU);
      });
      handle.addEventListener("touchstart", (e) => {
        e.preventDefault();
        const onTM = (e2) => onMove(e2.touches[0].clientX);
        const onTE = () => { document.removeEventListener("touchmove", onTM); document.removeEventListener("touchend", onTE); };
        document.addEventListener("touchmove", onTM, { passive: false });
        document.addEventListener("touchend", onTE);
      }, { passive: false });
      handle.addEventListener("keydown", (e) => {
        const cur = topologyQueuePriorityEdits.routes?.[port]?.[pctKey]
          ?? Math.round(parseFloat(handle.style.left || "0"));
        if (e.key === "ArrowRight" || e.key === "ArrowUp") {
          e.preventDefault(); applyPct(Math.min(100, cur + 1));
        } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
          e.preventDefault(); applyPct(Math.max(MIN, cur - 1));
        }
      });
    });
  })();
  // ── Per-proxy reset ──────────────────────────────────────────────────────
  document.querySelectorAll("[data-qp-proxy-reset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const port = Number(btn.dataset.qpProxyReset);
      if (topologyQueuePriorityEdits.routes) {
        topologyQueuePriorityEdits.routes[port] = {
          cloudFallbackPct: null, priorityPreemptPct: null, queueAbortPct: null,
        };
      }
      renderTopology();
    });
  });
  // ── Queue policy modal: stickySlotSec number input ───────────────────────
  document.querySelectorAll("[data-topology-qp-policy]").forEach((input) => {
    const event = input.type === "checkbox" ? "change" : "input";
    input.addEventListener(event, () => {
      const key = input.dataset.topologyQpPolicy;
      if (input.type === "checkbox") {
        topologyQueuePriorityEdits[key] = input.checked;
      } else {
        const value = Number(input.value);
        if (Number.isFinite(value)) topologyQueuePriorityEdits[key] = value;
      }
    });
  });
  // ── Drag handles for pct threshold sliders ───────────────────────────────
  (function attachQpHandles() {
    const track = document.querySelector("[data-qp-track]");
    if (!track) return;
    const fill = track.querySelector("[data-qp-fill]");
    const exEl = document.querySelector("[data-qp-example]");
    const policy = topology?.proxyPolicy || {};

    function getPct(key) {
      return topologyQueuePriorityEdits[key] ?? (policy[key] ?? { cloudFallbackPct: 20, priorityPreemptPct: 50, queueAbortPct: 85 }[key]);
    }
    function updateLive() {
      const cPct = getPct("cloudFallbackPct");
      const pPct = getPct("priorityPreemptPct");
      const aPct = getPct("queueAbortPct");
      if (fill) fill.style.width = Math.max(0, Math.min(100, aPct)) + "%";
      const handles = track.querySelectorAll("[data-qp-handle]");
      handles.forEach((h) => {
        const key = h.dataset.qpHandle;
        const val = getPct(key);
        const clamped = Math.max(0, Math.min(100, val));
        h.style.left = clamped + "%";
        const pctEl = h.querySelector(".qp-handle-pct");
        if (pctEl) pctEl.textContent = clamped + "%";
      });
      if (exEl) exEl.textContent = _queuePctExampleText(cPct, pPct, aPct);
    }
    track.querySelectorAll("[data-qp-handle]").forEach((handle) => {
      const MIN = handle.dataset.qpHandle === "queueAbortPct" ? 1 : 0;
      const onMove = (clientX) => {
        const rect = track.getBoundingClientRect();
        const pct = Math.max(MIN, Math.min(100, Math.round((clientX - rect.left) / rect.width * 100)));
        topologyQueuePriorityEdits[handle.dataset.qpHandle] = pct;
        updateLive();
      };
      handle.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const onMM = (e2) => onMove(e2.clientX);
        const onMU = () => { document.removeEventListener("mousemove", onMM); document.removeEventListener("mouseup", onMU); };
        document.addEventListener("mousemove", onMM);
        document.addEventListener("mouseup", onMU);
      });
      handle.addEventListener("touchstart", (e) => {
        e.preventDefault();
        const onTM = (e2) => onMove(e2.touches[0].clientX);
        const onTE = () => { document.removeEventListener("touchmove", onTM); document.removeEventListener("touchend", onTE); };
        document.addEventListener("touchmove", onTM, { passive: false });
        document.addEventListener("touchend", onTE);
      }, { passive: false });
      handle.addEventListener("keydown", (e) => {
        const key = handle.dataset.qpHandle;
        const cur = getPct(key);
        if (e.key === "ArrowRight" || e.key === "ArrowUp") {
          e.preventDefault();
          topologyQueuePriorityEdits[key] = Math.min(100, cur + 1);
          updateLive();
        } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
          e.preventDefault();
          topologyQueuePriorityEdits[key] = Math.max(MIN, cur - 1);
          updateLive();
        }
      });
    });
  })();
  document.querySelectorAll("[data-priority-row]").forEach((row) => {
    row.addEventListener("dragstart", (event) => {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", row.dataset.priorityRow);
      row.classList.add("dragging");
    });
    row.addEventListener("dragend", () => {
      row.classList.remove("dragging");
      document.querySelectorAll(".topology-priority-row").forEach((other) => {
        other.classList.remove("drop-above", "drop-below");
      });
    });
    row.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      const rect = row.getBoundingClientRect();
      const dropBelow = (event.clientY - rect.top) > rect.height / 2;
      row.classList.toggle("drop-above", !dropBelow);
      row.classList.toggle("drop-below", dropBelow);
    });
    row.addEventListener("dragleave", () => {
      row.classList.remove("drop-above", "drop-below");
    });
    row.addEventListener("drop", (event) => {
      event.preventDefault();
      const sourceId = event.dataTransfer.getData("text/plain");
      const targetId = row.dataset.priorityRow;
      if (!sourceId || sourceId === targetId) return;
      const sourceIdx = topologyPriorityOrder.indexOf(sourceId);
      if (sourceIdx === -1) return;
      topologyPriorityOrder.splice(sourceIdx, 1);
      const rect = row.getBoundingClientRect();
      const dropBelow = (event.clientY - rect.top) > rect.height / 2;
      const targetIdx = topologyPriorityOrder.indexOf(targetId);
      const insertAt = targetIdx === -1
        ? topologyPriorityOrder.length
        : targetIdx + (dropBelow ? 1 : 0);
      topologyPriorityOrder.splice(insertAt, 0, sourceId);
      renderTopology();
    });
  });
  document.querySelector("[data-topology-route-detail-close]")?.addEventListener("click", () => {
    topologyRouteDetail = null;
    renderTopology();
  });
  document.querySelectorAll("[data-token-range]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!topologyRouteDetail) return;
      topologyRouteDetail.range = button.dataset.tokenRange;
      renderTopology();
      loadRouteTokenHistory();
    });
  });
  document.querySelector("[data-topology-route-detail-overlay]")?.addEventListener("click", (event) => {
    if (event.target?.dataset?.topologyRouteDetailOverlay !== undefined) {
      topologyRouteDetail = null;
      renderTopology();
    }
  });
  document.querySelector("[data-topology-proxy-cancel]")?.addEventListener("click", () => {
    ui.topologyProxyFormOpen = false;
    ui.topologyProxyEditingId = "";
    renderTopology();
  });
  // ── Router (Роутер) card → open in new tab ────────────────────────
  document.querySelectorAll("[data-topology-router]").forEach((card) => {
    const open = (event) => {
      if (event.target?.closest?.(".topology-handle, .inline-tip, .tip-trigger")) return;
      const routerId = card.dataset.topologyRouter;
      window.open(`/kanban`, "_blank");
    };
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(event); }
    });
  });
  document.querySelector("[data-topology-router-close]")?.addEventListener("click", () => {
    ui.topologyRouterDetailId = ""; ui.topologyCanvasRouterId = ""; ui.topologyRouterNodeCfgId = "";
    renderTopology();
  });
  document.querySelector("[data-topology-router-overlay]")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) { ui.topologyRouterDetailId = ""; ui.topologyCanvasRouterId = ""; ui.topologyRouterNodeCfgId = ""; renderTopology(); }
  });
  document.querySelectorAll("[data-router-set-default]").forEach((btn) => {
    btn.addEventListener("change", () => {
      const routerId = btn.dataset.routerSetDefault, outId = btn.dataset.outputId;
      const label = btn.closest("[data-router-out-row]")?.querySelector(".router-out-name")?.textContent?.trim() || outId;

      // Revert the radio immediately — wait for explicit confirmation.
      const prevDefaultId = (topology?.routers || []).find((s) => s.id === routerId)?.rules?.default || "";
      btn.checked = false;
      if (prevDefaultId) {
        const prevBtn = document.querySelector(`[data-router-set-default="${CSS.escape(routerId)}"][data-output-id="${CSS.escape(prevDefaultId)}"]`);
        if (prevBtn) prevBtn.checked = true;
      }

      // Show confirm modal (reuse global #confirmOverlay pattern).
      $("confirmTitle").textContent = "Сменить дефолт?";
      $("confirmText").textContent = `Установить «${label}» как дефолтный выход?`;
      $("confirmMeta").hidden = true;
      $("confirmPath").textContent = "";
      $("confirmDelete").textContent = "Установить";
      $("confirmDelete").classList.remove("danger");
      ui.pendingConfirm = () => {
        closeConfirmModal();
        saveRouters((routers) => {
          const s = routerById(routers, routerId);
          if (s) { s.rules = s.rules || {}; s.rules.default = outId; }
        }).catch((e) => toast(e.message));
      };
      $("confirmOverlay").hidden = false;
    });
  });
  // Queue history toggle.
  document.querySelectorAll("[data-cv-q-hist-toggle]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const nodeId = btn.dataset.cvQHistToggle;
      _cvQueueHistOpen[nodeId] = !_cvQueueHistOpen[nodeId];
      if (_cvQueueHistOpen[nodeId] && !_cvQueueHistData[nodeId]) {
        _fetchQueueHist(nodeId);   // async; will call renderTopology() when done
      } else {
        renderTopology();
      }
    });
  });
  document.querySelectorAll("[data-cv-q-hist-refresh]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      _cvQueueHistData[btn.dataset.cvQHistRefresh] = null;
      _fetchQueueHist(btn.dataset.cvQHistRefresh);
    });
  });

  // Schedule history toggle.
  document.querySelectorAll("[data-cv-sched-hist-toggle]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const nodeId = btn.dataset.cvSchedHistToggle;
      _cvSchedHistOpen[nodeId] = !_cvSchedHistOpen[nodeId];
      if (_cvSchedHistOpen[nodeId] && !_cvSchedHistData[nodeId]) {
        _fetchSchedHist(nodeId);
      } else {
        renderTopology();
      }
    });
  });
  document.querySelectorAll("[data-cv-sched-hist-refresh]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      _cvSchedHistData[btn.dataset.cvSchedHistRefresh] = null;
      _fetchSchedHist(btn.dataset.cvSchedHistRefresh);
    });
  });

  // Cloud provider header → expand/collapse its model checklist.
  document.querySelectorAll("[data-router-prov-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const acc = btn.dataset.routerProvToggle;
      const accBlocks = (topology?.cloudProviders || []).filter((b) => b.accountId === acc);
      const cur = (acc in topologyOutputsCloudExpanded) ? topologyOutputsCloudExpanded[acc] : accBlocks.filter((b) => b.exposed).length === 0;
      topologyOutputsCloudExpanded[acc] = !cur;
      renderTopology();
    });
  });
  // Cloud model checkbox → expose/hide as a routable output.
  document.querySelectorAll("[data-router-expose]").forEach((cb) => {
    cb.addEventListener("change", () => setCloudModelExposed(cb.dataset.routerExpose, cb.checked));
  });
  document.querySelectorAll("[data-router-add-rule]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.routerAddRule;
      const src = document.querySelector(`[data-router-rule-source="${CSS.escape(id)}"]`)?.value;
      const out = document.querySelector(`[data-router-rule-output="${CSS.escape(id)}"]`)?.value;
      if (!src || !out) return;
      saveRouters((routers) => {
        const s = routerById(routers, id);
        if (!s) return;
        s.rules = s.rules || {};
        s.rules.bySource = (s.rules.bySource || []).filter((r) => r.proxyId !== src);
        s.rules.bySource.push({ proxyId: src, clientId: "", output: out });
      }).catch((e) => toast(e.message));
    });
  });
  document.querySelectorAll("[data-router-del-rule]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.routerDelRule, idx = Number(btn.dataset.ruleIndex);
      saveRouters((routers) => {
        const s = routerById(routers, id);
        if (s && s.rules) s.rules.bySource = (s.rules.bySource || []).filter((_, i) => i !== idx);
      }).catch((e) => toast(e.message));
    });
  });
  // Left column: attach a port to this router (confirm if it's on another), or
  // detach (→ unassigned/503). Both via route-policy routerId — no restart.
  document.querySelectorAll("[data-router-attach]").forEach((el) => {
    const attach = async () => {
      const pid = el.dataset.routerAttach;
      if (el.dataset.confirm) {
        const p = (topology?.proxies || []).find((x) => x.id === pid);
        if (!(await appConfirm(t("dlgMoveToRouter", { name: p?.label || pid }), { danger: false, confirmLabel: "OK" }))) return;
      }
      setTopologyProxyRoutePolicy(pid, { routerId: ui.topologyRouterDetailId }).catch((e) => toast(e.message));
    };
    el.addEventListener("click", attach);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); attach(); } });
  });
  document.querySelectorAll("[data-router-detach]").forEach((el) => {
    el.addEventListener("click", async (e) => {
      e.stopPropagation();
      const pid = el.dataset.routerDetach;
      const p = (topology?.proxies || []).find((x) => x.id === pid);
      const name = p ? (p.label || `proxy ${p.port}`) : pid;
      const ok = await appConfirm(t("dlgUnassignRouter", { name }), { confirmLabel: t("dlgUnassign") });
      if (!ok) return;
      setTopologyProxyRoutePolicy(pid, { routerId: "" }).catch((err) => toast(err.message));
    });
  });
  document.querySelector("[data-router-open-canvas]")?.addEventListener("click", (event) => {
    ui.topologyCanvasRouterId = event.currentTarget.dataset.routerOpenCanvas;
    cvSetViewport(canvasLoadPositions(ui.topologyCanvasRouterId), { tx: 24, ty: 24, scale: 1 });
    renderTopology();
    requestAnimationFrame(() => { drawCanvasConnectors(); bindCanvasInteractions(); });
  });
  document.querySelector("[data-topology-canvas-close]")?.addEventListener("click", () => {
    ui.topologyCanvasRouterId = "";
    renderTopology();
  });
  document.querySelector("[data-topology-canvas-overlay]")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) { ui.topologyCanvasRouterId = ""; renderTopology(); }
  });
  document.querySelector("[data-router-failover-toggle]")?.addEventListener("click", (event) => {
    const id = event.currentTarget.dataset.routerFailoverToggle;
    saveRouters((routers) => {
      const s = routerById(routers, id);
      if (!s) return;
      s.rules = s.rules || {};
      const on = (s.rules.failover || []).length > 0;
      if (on) { s.rules.failover = []; return; }
      // Build the chain: default output first, then the rest in display order.
      const ids = (s.outputs || []).map((o) => o.id);
      const def = s.rules.default;
      s.rules.failover = def && ids.includes(def) ? [def, ...ids.filter((x) => x !== def)] : ids;
    }).catch((e) => toast(e.message));
  });
  document.querySelector("[data-router-inputs-toggle]")?.addEventListener("click", () => {
    ui.topologyRouterInputsExpanded = !ui.topologyRouterInputsExpanded;
    renderTopology();
  });
  // Hover-link: highlight the rule(s)/default and the output row they connect.
  const routerLinkHi = (outId, on) => {
    if (!outId) return;
    document.querySelector(`[data-router-out-row="${CSS.escape(outId)}"]`)?.classList.toggle("link-hi", on);
    document.querySelectorAll(`[data-router-link-out="${CSS.escape(outId)}"]`).forEach((el) => el.classList.toggle("link-hi", on));
  };
  document.querySelectorAll("[data-router-link-out]").forEach((el) => {
    const out = el.dataset.routerLinkOut;
    el.addEventListener("mouseenter", () => routerLinkHi(out, true));
    el.addEventListener("mouseleave", () => routerLinkHi(out, false));
  });
  document.querySelectorAll("[data-router-out-row]").forEach((el) => {
    const out = el.dataset.routerOutRow;
    el.addEventListener("mouseenter", () => routerLinkHi(out, true));
    el.addEventListener("mouseleave", () => routerLinkHi(out, false));
  });
  const routerSearch = document.querySelector("[data-router-input-search]");
  if (routerSearch) {
    routerSearch.addEventListener("input", () => {
      ui.topologyRouterInputSearch = routerSearch.value;
      const q = routerSearch.value.trim().toLowerCase();
      document.querySelectorAll("[data-router-pill-wrap] [data-pill-name]").forEach((el) => {
        const hit = !q || (el.dataset.pillName || "").includes(q) || (el.dataset.pillPort || "").includes(q);
        el.style.display = hit ? "" : "none";
      });
    });
  }
  // ── Weekly schedule editor ─────────────────────────────────────────────────
  document.querySelector("[data-router-open-schedule]")?.addEventListener("click", (event) => {
    const id = event.currentTarget.dataset.routerOpenSchedule;
    const router = (topology?.routers || []).find((s) => s.id === id);
    topologyScheduleRouterId = id;
    topologyScheduleGrid = scheduleRulesToGrid(router);
    topologySchedulePaintOutput = (router?.outputs || [])[0]?.id || "";
    renderTopology();
  });
  const closeSchedule = () => { topologyScheduleRouterId = ""; topologyScheduleGrid = null; renderTopology(); };
  document.querySelector("[data-schedule-close]")?.addEventListener("click", closeSchedule);
  document.querySelector("[data-schedule-cancel]")?.addEventListener("click", closeSchedule);
  document.querySelector("[data-topology-schedule-overlay]")?.addEventListener("click", (event) => {
    if (event.target === event.currentTarget) closeSchedule();
  });
  document.querySelectorAll("[data-sched-paint]").forEach((btn) => {
    btn.addEventListener("click", () => {
      topologySchedulePaintOutput = btn.dataset.schedPaint;
      document.querySelectorAll("[data-sched-paint]").forEach((b) => b.classList.toggle("active", b === btn));
    });
  });
  document.querySelector("[data-schedule-clear]")?.addEventListener("click", () => {
    if (!topologyScheduleGrid) return;
    topologyScheduleGrid = topologyScheduleGrid.map((row) => row.map(() => ""));
    document.querySelectorAll("[data-sched-cell]").forEach((c) => { c.style.background = ""; c.classList.remove("painted"); });
  });
  document.querySelector("[data-schedule-save]")?.addEventListener("click", () => {
    const id = topologyScheduleRouterId;
    const rules = scheduleGridToRules(topologyScheduleGrid || []);
    topologyScheduleRouterId = ""; topologyScheduleGrid = null;
    saveRouters((routers) => {
      const s = routerById(routers, id);
      if (s) { s.rules = s.rules || {}; s.rules.schedule = rules; }
    }).catch((e) => toast(e.message));
  });
  const scheduleGrid = document.querySelector("[data-schedule-grid]");
  if (scheduleGrid) {
    const routerForPaint = (topology?.routers || []).find((s) => s.id === topologyScheduleRouterId);
    const paintCell = (cell) => {
      if (!cell || !topologyScheduleGrid) return;
      const d = Number(cell.dataset.day), h = Number(cell.dataset.hour);
      const out = topologySchedulePaintOutput;
      topologyScheduleGrid[d][h] = out;
      const bg = out ? scheduleOutputColor(routerForPaint, out) : "";
      cell.style.background = bg;
      cell.classList.toggle("painted", !!out);
    };
    scheduleGrid.addEventListener("pointerdown", (event) => {
      const cell = event.target.closest("[data-sched-cell]");
      if (!cell) return;
      _schedulePainting = true;
      paintCell(cell);
      event.preventDefault();
    });
    scheduleGrid.addEventListener("pointerover", (event) => {
      if (!_schedulePainting) return;
      paintCell(event.target.closest("[data-sched-cell]"));
    });
    if (!_schedulePointerUpBound) {
      _schedulePointerUpBound = true;
      document.addEventListener("pointerup", () => { _schedulePainting = false; });
    }
  }
  document.querySelectorAll("[data-client-rename]").forEach((btn) => {
    btn.addEventListener("click", () => {
      editTopologyClientAlias(btn.dataset.clientRename, btn.dataset.clientName);
    });
  });
  document.querySelectorAll("[data-topology-proxy-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      editTopologyProxy(button.dataset.topologyProxyEdit);
    });
  });
  document.querySelectorAll("[data-topology-proxy-delete]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteTopologyProxy(button.dataset.topologyProxyDelete).catch((err) => toast(err.message));
    });
  });
  document.querySelectorAll("[data-topology-route-handle]").forEach((handle) => {
    handle.addEventListener("mouseenter", () => {
      highlightTopologyCable(topologyRouteClass(handle.dataset.hostId, handle.dataset.agentId, handle.dataset.routeRole));
    });
    handle.addEventListener("mouseleave", scheduleClearTopologyCableHighlight);
    // Cables auto-connect from assignments — handles are visual anchors only,
    // no manual drag-to-connect.
  });
  document.querySelectorAll("[data-topology-route-detail]").forEach((row) => {
    const open = () => {
      const proxyId = row.dataset.topologyRouteDetail || "";
      const clientIp = row.dataset.clientIp || "";
      // The proxy port is the consumer key: prefer the resolved proxy object,
      // else parse it from the proxyId ("skynet:proxy:<port>").
      const proxy = (topology?.proxies || []).find((p) => p.id === proxyId);
      const port = Number(proxy?.port || String(proxyId).split(":").pop()) || null;
      const changedRoute = !topologyRouteDetail || topologyRouteDetail.proxyId !== proxyId;
      topologyRouteDetail = {
        proxyId,
        port,
        routeLabel: proxy?.label || "",
        clientIp,
        clientName: row.dataset.clientName || "",
        range: (topologyRouteDetail && !changedRoute) ? topologyRouteDetail.range : "all",
      };
      renderTopology();
      loadRouteTokenHistory();
    };
    row.addEventListener("click", (event) => {
      if (event.target?.closest?.("[data-topology-route-handle]")) return;
      open();
    });
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
  });
  // (Output handles are cable anchors only — outputs are auto-derived from providers,
  // so there's no manual retarget drag anymore.)
  document.querySelectorAll("[data-topology-client-edit]").forEach((button) => {
    button.addEventListener("click", () => {
      editTopologyClientAlias(button.dataset.hostId, button.dataset.currentName).catch((err) => toast(err.message));
    });
  });
  document.querySelectorAll("[data-topology-proxy-input]").forEach((proxyEl) => {
    proxyEl.addEventListener("dragover", (event) => {
      event.preventDefault();
      proxyEl.classList.add("drag-over");
      event.dataTransfer.dropEffect = "copy";
    });
    proxyEl.addEventListener("dragleave", () => proxyEl.classList.remove("drag-over"));
    proxyEl.addEventListener("drop", (event) => {
      event.preventDefault();
      proxyEl.classList.remove("drag-over");
      proxyEl.classList.remove("drag-over");
    });
  });
  document.querySelectorAll("[data-topology-proxy]").forEach((proxyCard) => {
    proxyCard.addEventListener("mouseenter", () => {
      highlightTopologyCable(topologyProxyClass(proxyCard.dataset.proxyId));
    });
    proxyCard.addEventListener("mouseleave", scheduleClearTopologyCableHighlight);
  });
}

export function topologyLlamaAtPoint(x, y) {
  return document.elementFromPoint(x, y)?.closest?.("[data-topology-llama-input]");
}

export function topologyRouterInputAtPoint(x, y) {
  return document.elementFromPoint(x, y)?.closest?.("[data-topology-router-input]");
}

export function topologyCloudAtPoint(x, y) {
  return document.elementFromPoint(x, y)?.closest?.("[data-topology-cloud-input]");
}

export function clearTopologyPointerDrag() {
  topologyPointerDrag?.source?.classList.remove("dragging");
  topologyPointerDrag = null;
  document.querySelectorAll("[data-topology-proxy-input]").forEach((target) => target.classList.remove("drag-over"));
  document.querySelectorAll("[data-topology-llama-input]").forEach((target) => target.classList.remove("drag-over"));
  document.querySelectorAll("[data-topology-cloud-input]").forEach((target) => target.classList.remove("drag-over"));
  document.querySelectorAll("[data-topology-router-input]").forEach((target) => target.classList.remove("drag-over"));
  $("topologyCables")?.querySelector(".topology-cable.live")?.remove();
  // The drag is over — apply any refresh that was deferred while dragging.
  flushPendingTopologyRender();
}

