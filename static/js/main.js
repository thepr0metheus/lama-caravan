// Entry point: DOMContentLoaded wiring and the standalone kanban page init.
import { appConfirm } from "./dialogs.js";
import { initDialogLlamas } from "./dialog-llamas.js";
import { drawLiveTopologyCable, drawTopologyCables } from "./cables.js";
import { canvasLoadPositions, cvSetViewport, drawCanvasConnectors } from "./canvas.js";
import { drawTopologyServerStats, systemSamples } from "./charts.js";
import { openCloudProviderModal } from "./cloud.js";
import { renderCommandPreview } from "./command-preview.js";
import { memoryEstimateFields } from "./constants.js";
import {
  maybeAutofillModelHelpers,
  maybeAutofillModelHelpersPfx,
  modelsByPath,
  renderChatTemplateHint,
  renderChatTemplateOptions,
  renderModelInsight,
  renderStaticConfigFields,
  setGemma4Mode,
  syncCompanionMuting,
  syncToggleLabel,
} from "./form.js";
import { applyLanguage, applyTheme, setupLangSelect, t } from "./i18n.js";
import {
  _teCellPort,
  closeConfirmModal,
  closeTopologyLlamaEdit,
  openActionModal,
  saveTopologyLlamaConfig,
} from "./llama-edit.js";
import { refreshComputeTarget } from "./memory.js";
import { fetchModelPricing, fetchProxyDailyStats } from "./model-meta.js";
import { initOnboarding } from "./onboarding-tours.js";
import { action, bindMonitorDrawer, loadState, startTopologyMonitor } from "./polling.js";
import { refreshRouteErrBadges } from "./topology-activity.js";
import { purgeRemoteModelCache, submitRemoteLlamaStart } from "./remote-cells.js";
import { rebindProxyRouter } from "./routers.js";
import { topology, ui } from "./state.js";
import { renderRuntime, revertLatest } from "./system-panels.js";
import {
  clearTopologyPointerDrag,
  topologyPointerDrag,
  topologyRouterInputAtPoint,
} from "./topology-dnd.js";
import { activeView, flushPendingTopologyRender, refreshTopology, renderTopology, setActiveView } from "./topology-render.js";
import { openUsageStatsModal } from "./usage-stats.js";
import { $, api, bindTooltips, escapeHtml, toast } from "./utils.js";

// The pixel-llama page loader is inline in index.html/kanban.html so it shows
// before the modules download; window.__plHide is defined there.
function hideAppLoader() { try { window.__plHide?.(); } catch { /* already gone */ } }

function initRouterStandalonePage() {
  bindTooltips();
  $("confirmCancel").addEventListener("click", closeConfirmModal);
  $("confirmDelete").addEventListener("click", () => { if (ui.pendingConfirm) ui.pendingConfirm(); });
  $("confirmOverlay").addEventListener("click", (event) => {
    if (event.target.id === "confirmOverlay") closeConfirmModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("confirmOverlay").hidden) closeConfirmModal();
  });
  const routerId = new URLSearchParams(location.search).get("id") || "router:default";
  refreshTopology().then(() => {
    const router = (topology?.routers || []).find((r) => r.id === routerId);
    if (!router) {
      const el = $("topologyProxies");
      if (el) el.innerHTML = `<div style="padding:20px;color:var(--muted)">${escapeHtml(t("routerNotFound", { id: routerId }))}</div>`;
      hideAppLoader();
      return;
    }
    ui.topologyRouterDetailId = routerId;
    ui.topologyCanvasRouterId = routerId;
    ui.topologyRouterNodeCfgId = "";
    ui.topologyRouterInputsExpanded = true;
    cvSetViewport(canvasLoadPositions(routerId), { tx: 24, ty: 24, scale: 1 });
    renderTopology();
    startTopologyMonitor();
    hideAppLoader();
  }).catch((err) => { hideAppLoader(); toast(err.message); });
}

document.addEventListener("DOMContentLoaded", async () => {
  initDialogLlamas();
  applyLanguage();
  applyTheme();
  initOnboarding();

  if (window.ROUTER_STANDALONE) {
    initRouterStandalonePage();
    // The standalone boot exits before the shared boot tail below — fetch the
    // pricing map here too, or the kanban's $/1M tags stay empty forever.
    fetchModelPricing().catch(() => {});
    return;
  }

  const doLogout = async () => {
    try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } catch { /* ignore */ }
    window.location = "/login";
  };
  $("authLogoutBtn")?.addEventListener("click", doLogout);
  // Header account chip: shown when sign-in is enabled; menu = Security / Log out.
  api("/api/auth/me").then((me) => {
    if (!me.enabled || !me.authenticated) return;
    $("userChipName").textContent = me.user + (me.role === "viewer" ? t("userViewerSuffix") : "");
    $("userChip").hidden = false;
    const menu = $("userMenu");
    const closeMenu = () => { menu.hidden = true; $("userChipBtn").setAttribute("aria-expanded", "false"); };
    $("userChipBtn").addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      $("userChipBtn").setAttribute("aria-expanded", String(!menu.hidden));
    });
    // Capture phase: the board's delegated click router stopPropagation()s
    // most clicks, so a bubble-phase listener never saw them and the menu
    // stayed open forever. Capture runs before any of that.
    document.addEventListener("click", (e) => { if (!$("userChip").contains(e.target)) closeMenu(); }, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) closeMenu(); });
    $("userMenuLogout").addEventListener("click", doLogout);
    $("userMenuSecurity").addEventListener("click", () => {
      closeMenu();
      window.location.href = "/system#security";
    });
  }).catch(() => {});

  // Remote llama-server modal buttons
  $("llamaRemoteEditStart")?.addEventListener("click", submitRemoteLlamaStart);
  $("tr-purgeCache")?.addEventListener("click", purgeRemoteModelCache);
  const closeRemote = () => { $("llamaRemoteEditOverlay").hidden = true; };
  $("llamaRemoteEditClose")?.addEventListener("click", closeRemote);
  $("llamaRemoteEditOverlay")?.addEventListener("click", (e) => {
    if (e.target === $("llamaRemoteEditOverlay")) closeRemote();
  });
  // Redraw Server Stats charts when card is opened (canvas has zero size while closed)
  document.querySelector(".topology-server-stats-card")?.addEventListener("toggle", () => {
    const samples = systemSamples(ui.latestSystemMonitor).slice(-600);
    if (samples.length) drawTopologyServerStats(samples);
  });
  setupLangSelect();
  // System lives on its own page now (/system: Controller, llama.cpp,
  // Security, Diagnostics tabs) — the header button just navigates.
  $("systemInfoBtn")?.addEventListener("click", () => { window.location.href = "/system"; });
  $("usageStatsBtn")?.addEventListener("click", openUsageStatsModal);
  $("gemmaTextBoostBtn").addEventListener("click", () => setGemma4Mode("text").catch((err) => toast(err.message)));
  $("gemmaVisionBtn").addEventListener("click", () => setGemma4Mode("vision").catch((err) => toast(err.message)));
  $("textOnlyBtn").addEventListener("click", () => {
    $("MMPROJ_FILE").value = "";
    renderModelInsight();
    renderRuntime();
    renderCommandPreview();
    toast(t("mmprojCleared"));
  });
  $("revertBtn").addEventListener("click", () => revertLatest().catch((err) => toast(err.message)));
  $("confirmCancel").addEventListener("click", closeConfirmModal);
  $("confirmDelete").addEventListener("click", () => {
    if (ui.pendingConfirm) ui.pendingConfirm();
  });
  $("confirmOverlay").addEventListener("click", (event) => {
    if (event.target.id === "confirmOverlay") closeConfirmModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("confirmOverlay").hidden) { closeConfirmModal(); return; }
    if (event.key === "Escape" && !$("llamaRemoteEditOverlay")?.hidden) { $("llamaRemoteEditOverlay").hidden = true; return; }
    if (event.key === "Escape" && !$("topologyLlamaEditOverlay")?.hidden) { closeTopologyLlamaEdit(); return; }
    // п.6: Ctrl+Enter → Save & Restart (local) or Start (remote)
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      if (!$("topologyLlamaEditOverlay")?.hidden) {
        event.preventDefault();
        saveTopologyLlamaConfig(true).catch((err) => toast(err.message));
        return;
      }
      if (!$("llamaRemoteEditOverlay")?.hidden) {
        event.preventDefault();
        submitRemoteLlamaStart().catch((err) => toast(err.message));
        return;
      }
    }
    if (event.key === "Escape" && topologyPointerDrag) clearTopologyPointerDrag();
  });
  document.addEventListener("pointermove", (event) => {
    if (!topologyPointerDrag) return;
    document.querySelectorAll("[data-topology-proxy-input]").forEach((target) => target.classList.remove("drag-over"));
    document.querySelectorAll("[data-topology-llama-input]").forEach((target) => target.classList.remove("drag-over"));
    document.querySelectorAll("[data-topology-cloud-input]").forEach((target) => target.classList.remove("drag-over"));
    document.querySelectorAll("[data-topology-router-input]").forEach((target) => target.classList.remove("drag-over"));
    // route-router / proxy-router → target a router input.
    topologyRouterInputAtPoint(event.clientX, event.clientY)?.classList.add("drag-over");
    drawLiveTopologyCable(event.clientX, event.clientY);
  });
  document.addEventListener("pointerup", (event) => {
    if (!topologyPointerDrag) return;
    const payload = { ...topologyPointerDrag };
    // route-router / proxy-router: re-bind the proxy to the dropped router
    const routerEl = topologyRouterInputAtPoint(event.clientX, event.clientY);
    clearTopologyPointerDrag();
    if (!routerEl || !payload.proxyId) return;
    rebindProxyRouter(payload.proxyId, routerEl.dataset.routerId).catch((err) => toast(err.message));
  });
  window.addEventListener("resize", () => {
    if (activeView === "topology") requestAnimationFrame(() => { drawTopologyCables(); if (ui.topologyCanvasRouterId) drawCanvasConnectors(); });
  });
  // The router card is sticky (stays centred on scroll) → redraw cables so they
  // keep tracking it. rAF-throttled; only on the topology view.
  let _scrollCablePending = false;
  window.addEventListener("scroll", () => {
    if (activeView !== "topology" || _scrollCablePending) return;
    _scrollCablePending = true;
    requestAnimationFrame(() => { _scrollCablePending = false; drawTopologyCables(); });
  }, { passive: true });
  if (typeof ResizeObserver !== "undefined") {
    const board = document.querySelector(".topology-board");
    if (board) {
      let pending = false;
      const observer = new ResizeObserver(() => {
        if (activeView !== "topology" || pending) return;
        pending = true;
        requestAnimationFrame(() => {
          pending = false;
          drawTopologyCables();
        });
      });
      observer.observe(board);
    }
  }
  $("MODEL_FILE").addEventListener("change", maybeAutofillModelHelpers);
  $("MMPROJ_FILE").addEventListener("change", () => {
    renderModelInsight();
    renderRuntime();
    renderCommandPreview();
  });
  $("OFFLOAD_MMPROJ")?.addEventListener("change", (e) => {
    syncToggleLabel(e.target);
    syncCompanionMuting();
    renderCommandPreview();
  });
  $("SPEC_DRAFT_MODEL_FILE")?.addEventListener("change", () => {
    renderModelInsight();
    renderCommandPreview();
  });
  $("SPEC_ENABLED")?.addEventListener("change", (e) => {
    const selected = modelsByPath().get($("MODEL_FILE")?.value || "");
    const specTypeEl = $("SPEC_TYPE");
    if (specTypeEl) specTypeEl.value = e.target.checked ? (selected?.familyDefaults?.SPEC_TYPE || "draft-mtp") : "";
    syncToggleLabel(e.target);
    syncCompanionMuting();
    renderCommandPreview();
  });
  $("CHAT_TEMPLATE_FILE").addEventListener("input", () => {
    renderChatTemplateOptions();
    renderChatTemplateHint();
    renderModelInsight();
    renderCommandPreview();
  });
  $("LLAMA_MODELS_DIR").addEventListener("input", () => {
    renderStaticConfigFields();
    renderCommandPreview();
  });
  $("configForm").addEventListener("input", (event) => {
    if (memoryEstimateFields.includes(event.target?.id)) {
      renderModelInsight();
      renderRuntime();
    }
    renderCommandPreview();
  });
  $("configForm").addEventListener("change", (event) => {
    if (memoryEstimateFields.includes(event.target?.id)) {
      renderModelInsight();
      renderRuntime();
    }
    renderCommandPreview();
  });

  // Topology Llama Edit Modal + wide-button bindings
  document.addEventListener("click", (event) => {
    // Close port dropdown on outside click
    if (!event.target.closest(".port-combo")) {
      document.querySelectorAll(".port-dropdown:not([hidden])").forEach((dd) => { dd.hidden = true; });
    }
    if (event.target.closest("[data-topo-add-cloud]")) {
      openCloudProviderModal(null);
      return;
    }
    if (event.target.closest("[data-topo-edit-close]")) {
      closeTopologyLlamaEdit();
      return;
    }
    if (event.target.id === "topologyLlamaEditSaveRestart") {
      if (_teCellPort) {
        // Cell config — confirm before applying
        appConfirm(t("dlgApplyCellConfig"), { danger: false, confirmLabel: "OK", scene: "start" })
          .then((ok) => { if (ok) saveTopologyLlamaConfig(false).catch((err) => toast(err.message)); });
        return;
      } else {
        saveTopologyLlamaConfig(true).catch((err) => toast(err.message));
      }
      return;
    }
    // Close on backdrop click
    if (event.target.id === "topologyLlamaEditOverlay") {
      closeTopologyLlamaEdit();
    }
  });

  // Topology edit form live preview
  $("topologyLlamaEditForm")?.addEventListener("input", (event) => {
    const bareId = (event.target?.id || "").replace(/^te-/, "");
    if (memoryEstimateFields.includes(bareId)) renderModelInsight("te-");
    renderCommandPreview("te-");
  });
  $("topologyLlamaEditForm")?.addEventListener("change", (event) => {
    const bareId = (event.target?.id || "").replace(/^te-/, "");
    if (memoryEstimateFields.includes(bareId)) renderModelInsight("te-");
    if (["N_GPU_LAYERS", "DEVICE", "THREADS"].includes(bareId)) refreshComputeTarget("te-");
    renderCommandPreview("te-");
  });
  $("te-MODEL_FILE")?.addEventListener("change", () => {
    maybeAutofillModelHelpersPfx("te-", { aliasFollow: true });
    renderModelInsight("te-");
    renderChatTemplateHint("te-");
    renderCommandPreview("te-");
  });
  $("te-MMPROJ_FILE")?.addEventListener("change", () => {
    renderModelInsight("te-");
    renderCommandPreview("te-");
  });
  $("te-OFFLOAD_MMPROJ")?.addEventListener("change", (e) => {
    syncToggleLabel(e.target);
    syncCompanionMuting("te-");
    renderCommandPreview("te-");
  });
  $("te-SPEC_DRAFT_MODEL_FILE")?.addEventListener("change", () => {
    renderModelInsight("te-");
    renderCommandPreview("te-");
  });
  $("te-SPEC_ENABLED")?.addEventListener("change", (e) => {
    const selected = modelsByPath().get($("te-MODEL_FILE")?.value || "");
    const specTypeEl = $("te-SPEC_TYPE");
    if (specTypeEl) specTypeEl.value = e.target.checked ? (selected?.familyDefaults?.SPEC_TYPE || "draft-mtp") : "";
    syncToggleLabel(e.target);
    syncCompanionMuting("te-");
    renderCommandPreview("te-");
  });
  $("te-CHAT_TEMPLATE_FILE")?.addEventListener("input", () => {
    renderChatTemplateOptions("te-");
    renderChatTemplateHint("te-");
    renderCommandPreview("te-");
  });

  document.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => openActionModal(button.dataset.action));
  });
  bindMonitorDrawer();
  bindTooltips();
  document.querySelectorAll("[data-view-tab]").forEach((button) => {
    button.addEventListener("click", () => setActiveView(button.dataset.viewTab));
  });
  // Board renders deferred while a select/text field held focus (see
  // topologyInteractionActive) land here once the focus moves on. The timeout
  // lets document.activeElement settle on the newly-focused element first.
  document.addEventListener("focusout", () => setTimeout(flushPendingTopologyRender, 60));
  // The loader hides the moment the board is actually populated — polling the
  // DOM beats awaiting the init chain, whose slowest call (/api/state tail)
  // can finish many seconds after the topology already rendered.
  const boardReady = new Promise((resolve) => {
    const t0 = Date.now();
    (function tick() {
      const filled = ($("topologyClients")?.children.length || 0) > 0
        && !!document.querySelector("[data-node-cell-port]");
      if (filled || Date.now() - t0 > 15000) resolve();
      else setTimeout(tick, 120);
    })();
  });
  boardReady.then(hideAppLoader);
  try {
    await loadState();
    setActiveView(activeView);
  } catch (err) {
    hideAppLoader();
    toast(err.message);
  }
  fetchProxyDailyStats().catch(() => {});
  setInterval(() => fetchProxyDailyStats().catch(() => {}), 60_000);
  fetchModelPricing().catch(() => {});
  setInterval(() => fetchModelPricing().catch(() => {}), 24 * 3600 * 1000);
  refreshRouteErrBadges().catch(() => {});
  setInterval(() => refreshRouteErrBadges().catch(() => {}), 60_000);
});
