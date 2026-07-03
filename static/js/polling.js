// State loading and polling loops: loadState/saveConfig, monitors, live refresh.
import { formatEventTime, renderLlamaClientsInnerHtml } from "./charts.js";
import { dirtyOptionalToggles } from "./constants.js";
import { appPrompt } from "./dialogs.js";
import { readConfigForm } from "./form.js";
import { t } from "./i18n.js";
import { closeConfirmModal } from "./llama-edit.js";
import { addAgentProxyRoute } from "./proxy-routes.js";
import { _nvidiaSmiSource } from "./remote-cells.js";
import { setState, state, topology, ui } from "./state.js";
import {
  renderCpu,
  renderGpu,
  renderKnownProblems,
  renderProjectGitBranch,
  renderRuntime,
  renderService,
} from "./system-panels.js";
import { proxyTelemetrySummary, refreshTopologyActivityState } from "./topology-activity.js";
import { topologyPointerDrag } from "./topology-dnd.js";
import { activeView, refreshTopology, renderAll } from "./topology-render.js";
import { $, api, escapeHtml, toast } from "./utils.js";

export function renderLiveCards() {
  renderService();
  renderRuntime();
  renderCpu();
  renderGpu();
  renderKnownProblems();
}

export let liveRefreshTimer = null;
export let liveRefreshInflight = false;
export const tokenSpeedState = {
  lastTime: null,
  current: null,
  previous: null,
};

export function metricNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export function formatTps(value) {
  const number = metricNumber(value);
  if (number >= 100) return number.toFixed(1);
  if (number >= 10) return number.toFixed(2);
  return number.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

// Compact token count: 32768 -> "32k", 12000 -> "12k", 1500 -> "1.5k".
export function formatCtxTokens(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 1000) return String(Math.round(n));
  const k = n / 1000;
  return (k >= 100 ? Math.round(k) : Number(k.toFixed(1))) + "k";
}

export function liveRefreshDelay() {
  const phase = state.runtime?.status?.phase;
  return phase === "running" ? 5000 : 1500;
}

export async function refreshLiveState() {
  if (liveRefreshInflight) return;
  liveRefreshInflight = true;
  try {
    const fresh = await api("/api/state");
    state.service = fresh.service;
    state.runtime = fresh.runtime;
    state.cpu = fresh.cpu;
    state.gpu = fresh.gpu;
    state.memory = fresh.memory;
    state.diagnostics = fresh.diagnostics;
    state.logs = fresh.logs;
    state.projectGit = fresh.projectGit;
    state.time = fresh.time;
    renderProjectGitBranch();
    renderLiveCards();
    if (activeView === "topology") {
      await refreshTopology();
    }
  } catch (err) {
    toast(err.message);
  } finally {
    liveRefreshInflight = false;
  }
}

export function scheduleLiveRefresh(delay = liveRefreshDelay()) {
  clearTimeout(liveRefreshTimer);
  liveRefreshTimer = setTimeout(async () => {
    await refreshLiveState();
    scheduleLiveRefresh();
  }, delay);
}

export async function loadState() {
  setState(await api("/api/state"));
  dirtyOptionalToggles.clear();
  renderAll();
  scheduleLiveRefresh();
}

export async function saveConfig(restart) {
  const config = readConfigForm();
  const data = await api("/api/config", {
    method: "POST",
    body: JSON.stringify({ config, restart }),
  });
  setState(data.state);
  dirtyOptionalToggles.clear();
  renderAll();
  toast(restart ? t("savedRestarted") : t("saved"));
}

export async function action(name) {
  try {
    const data = await api("/api/action", {
      method: "POST",
      body: JSON.stringify({ action: name }),
    });
    setState(data.state);
    closeConfirmModal();
    renderAll();
    toast(t("actionSent", { action: name }));
    scheduleLiveRefresh(500);
  } catch (err) {
    toast(err.message);
  }
}


export const monitorState = {};
export const monitorInflight = {};
export let systemMonitorTimer = null;
export let systemMonitorInflight = false;
export let topologyMonitorTimer = null;

export function monitorTarget(kind) {
  return kind === "nvidia-smi" ? $("monitorNvidia") : null;
}

export function monitorIntervalInput(kind) {
  return kind === "nvidia-smi" ? $("monitorIntervalNvidia") : null;
}

export function monitorStorageKey(kind) {
  return `llamacpp-monitor-interval-${kind}`;
}

export function monitorIntervalMs(kind) {
  const input = monitorIntervalInput(kind);
  const value = Math.max(Number(input?.value || 1), 1);
  return Math.min(value, 30) * 1000;
}

export function restoreMonitorInterval(kind) {
  const input = monitorIntervalInput(kind);
  if (!input) return;
  const saved = localStorage.getItem(monitorStorageKey(kind));
  if (!saved) return;
  const value = Math.max(Number(saved), 1);
  if (Number.isFinite(value)) input.value = String(Math.min(value, 30));
}

export function saveMonitorInterval(kind) {
  const input = monitorIntervalInput(kind);
  if (!input) return;
  const value = Math.max(Number(input.value || 1), 1);
  const normalized = Math.min(value, 30);
  input.value = String(normalized);
  localStorage.setItem(monitorStorageKey(kind), String(normalized));
}

export async function refreshMonitor(kind) {
  if (kind === "system") {
    await refreshSystemMonitor();
    return;
  }
  const target = monitorTarget(kind);
  if (!target || monitorInflight[kind]) return;
  monitorInflight[kind] = true;
  try {
    // nvidia-smi: route to selected source (local controller or remote client)
    const url = (kind === "nvidia-smi" && _nvidiaSmiSource !== "local")
      ? `/api/topology/client-monitor?hostId=${encodeURIComponent(_nvidiaSmiSource)}&kind=nvidia-smi`
      : `/api/monitor/${kind}`;
    const data = await api(url);
    const stamp = new Date((data.time || Date.now() / 1000) * 1000).toLocaleTimeString();
    if (data.html) {
      target.innerHTML = `<span class="monitor-stamp">[${stamp}] ${data.source || kind}</span>\n\n${data.html}`;
    } else {
      target.textContent = `[${stamp}] ${data.source || kind}\n\n${data.output || "no output"}`;
    }
  } catch (err) {
    const previous = target.innerHTML;
    const hasSnapshot = target.textContent.trim() && target.textContent.trim() !== "hover to start";
    if (hasSnapshot) {
      const stamp = new Date().toLocaleTimeString();
      target.innerHTML = `<span class="monitor-stamp">[${stamp}] refresh failed: ${escapeHtml(err.message)}; keeping previous snapshot</span>\n\n${previous}`;
    } else {
      target.textContent = err.message;
    }
  } finally {
    monitorInflight[kind] = false;
  }
}

export function startMonitor(kind) {
  if (!kind) return;
  if (kind === "system") {
    startSystemMonitor();
    return;
  }
  clearInterval(monitorState[kind]);
  refreshMonitor(kind);
  monitorState[kind] = setInterval(() => refreshMonitor(kind), monitorIntervalMs(kind));
}

export function stopMonitor(kind) {
  if (kind === "system") {
    stopSystemMonitor();
    return;
  }
  clearInterval(monitorState[kind]);
  monitorState[kind] = null;
}

export function bindMonitorDrawer() {
  ["nvidia-smi"].forEach(restoreMonitorInterval);
  document.querySelectorAll("[data-monitor-kind]").forEach((tab) => {
    const kind = tab.dataset.monitorKind;
    tab.addEventListener("mouseenter", () => startMonitor(kind));
    tab.addEventListener("focusin", () => startMonitor(kind));
    tab.addEventListener("mouseleave", () => stopMonitor(kind));
    tab.addEventListener("focusout", () => stopMonitor(kind));
  });
  ["monitorIntervalNvidia"].forEach((id) => {
    $(id)?.addEventListener("change", () => {
      const kind = "nvidia-smi";
      saveMonitorInterval(kind);
      if (monitorState[kind]) startMonitor(kind);
    });
  });
  $("systemMonitorRetention")?.addEventListener("change", saveSystemMonitorRetention);
  $("addAgentProxyRoute")?.addEventListener("click", addAgentProxyRoute);
}

export function renderGpuUsers({ clients, activeSlots, recentRequests, gpuUtil, promptTps, predictTps, activity }) {
  const timing = activity.lastTiming || {};
  const context = activity.context || {};
  const promptCache = activity.promptCache || {};
  const recentByClient = activity.recentByClient || [];
  const correlated = ui.latestSystemMonitor?.latest?.correlatedActivity || {};
  const proxyAgents = ui.latestSystemMonitor?.latest?.agentProxies?.agents || {};
  const correlatedProxyRows = [
    ...(correlated.activeRequests || []),
    ...(correlated.activeRequests?.length ? [] : (correlated.recentRequests || []).slice(0, 8)),
  ].map((item) => `
      <div class="system-user-row ${item.state === "active" ? "active" : "recent"} detailed proxy">
        <div class="system-user-main">
          <strong>${escapeHtml(item.label || `:${item.port}`)}</strong>
          <code>${escapeHtml(`:${item.port || "?"} -> :${item.upstreamPort || 8080}`)}</code>
          <span>${escapeHtml(`${item.method || "POST"} ${item.path || ""}`)}</span>
        </div>
        <div class="system-user-detail">
          <span>${escapeHtml(item.state === "active" ? t("gpuUsersNow") : String(item.status || "?"))}</span>
          <small>${escapeHtml(item.state === "active"
            ? t("gpuUsersProxyActive", { client: item.client || "?", time: formatEventTime(item.startedAt) })
            : t("gpuUsersProxyRecent", { status: item.status || "?", duration: String(item.durationMs || 0), time: formatEventTime(item.finishedAt) }))}</small>
          <small>${escapeHtml([
            `phase ${item.phase || "active"}`,
            `bytes ${item.bytes || 0}`,
            proxyTelemetrySummary(item),
            item.correlation ? `via ${item.correlation}` : "",
          ].filter(Boolean).join(" · "))}</small>
        </div>
      </div>
  `).join("");
  const proxyRows = correlatedProxyRows || Object.entries(proxyAgents).flatMap(([agent, row]) => {
    const port = row.port || "?";
    const active = (row.active || []).map((item) => `
      <div class="system-user-row active detailed proxy">
        <div class="system-user-main">
          <strong>${escapeHtml(agent)}</strong>
          <code>${escapeHtml(`:${port} -> :8080`)}</code>
          <span>${escapeHtml(`${item.method || "POST"} ${item.path || ""}`)}</span>
        </div>
        <div class="system-user-detail">
          <span>${escapeHtml(t("gpuUsersNow"))}</span>
          <small>${escapeHtml(t("gpuUsersProxyActive", { client: item.client || "?", time: formatEventTime(item.startedAt) }))}</small>
          <small>${escapeHtml([
            `phase ${item.phase || "active"}`,
            `bytes ${item.bytes || 0}`,
            proxyTelemetrySummary(item),
          ].filter(Boolean).join(" · "))}</small>
        </div>
      </div>
    `);
    const recent = (row.recent || []).slice(-3).reverse().map((item) => `
      <div class="system-user-row recent detailed proxy">
        <div class="system-user-main">
          <strong>${escapeHtml(agent)}</strong>
          <code>${escapeHtml(`:${port} -> :8080`)}</code>
          <span>${escapeHtml(`${item.method || "POST"} ${item.path || ""}`)}</span>
        </div>
        <div class="system-user-detail">
          <span>${escapeHtml(String(item.status || "?"))}</span>
          <small>${escapeHtml(t("gpuUsersProxyRecent", { status: item.status || "?", duration: String(item.durationMs || 0), time: formatEventTime(item.finishedAt) }))}</small>
          <small>${escapeHtml([
            item.client || "?",
            proxyTelemetrySummary(item),
            item.error || "",
          ].filter(Boolean).join(" · "))}</small>
        </div>
      </div>
    `);
    return active.length ? active : recent;
  }).join("");
  const activeRows = clients.map((row) => {
    const name = row.clientName || row.clientIp || "unknown";
    const endpoint = `${row.clientIp || "?"}${row.clientPort ? `:${row.clientPort}` : ` (${t("gpuUsersPortUnknown")})`}`;
    const local = `${row.localIp || "?"}:${row.localPort || "?"}`;
    return `
      <div class="system-user-row active">
        <strong>${escapeHtml(name)}</strong>
        <code>${escapeHtml(endpoint)}</code>
        <span>${escapeHtml(t("gpuUsersNow"))}</span>
        <small>${escapeHtml(row.state || "ESTAB")} -> ${escapeHtml(local)} <button class="mini-link" type="button" data-client-label="${escapeHtml(row.clientIp || "")}">${escapeHtml(t("editClientLabel"))}</button></small>
      </div>
    `;
  }).join("");
  const slotRows = activeSlots.map((slot) => `
    <div class="system-user-row ${slot.isProcessing ? "active" : ""}">
      <strong>slot ${escapeHtml(String(slot.id ?? "?"))}</strong>
      <code>${escapeHtml(t("llamaActivityTask"))} ${escapeHtml(String(slot.taskId ?? "-"))}</code>
      <span>${escapeHtml(t(slot.isProcessing ? "llamaActivityProcessing" : "llamaActivityIdle"))}</span>
      <small>${escapeHtml(t("llamaActivityDecodedRemain", { decoded: String(slot.decoded ?? 0), remain: String(slot.remain ?? 0) }))}</small>
    </div>
  `).join("");
  const recentRows = recentRequests.slice().reverse().slice(0, 5).map((row) => `
    <div class="system-user-row recent">
      <strong>${escapeHtml(row.clientName || row.clientIp || "unknown")}</strong>
      <code>${escapeHtml(row.method || "POST")} ${escapeHtml(row.path || "")}</code>
      <span>${escapeHtml(row.status || "")}</span>
      <small>${escapeHtml(row.time || "")}</small>
    </div>
  `).join("");
  const byClientRows = recentByClient.map((row) => {
    const timing = row.lastTiming || {};
    const context = row.lastContext || {};
    const timingText = (timing.promptTokens || timing.evalTokens)
      ? t("gpuUsersClientTiming", {
        count: String(row.count || 0),
        status: String(row.lastStatus || "?"),
        promptTokens: String(timing.promptTokens ?? 0),
        promptTps: String(timing.promptTps ?? 0),
        evalTokens: String(timing.evalTokens ?? 0),
        evalTps: String(timing.evalTps ?? 0),
      })
      : `${row.count || 0} req, last ${row.lastStatus || "?"}`;
    const contextText = context.tokens
      ? ` · ${t("gpuUsersClientContext", {
        tokens: String(context.tokens),
        limit: String(context.limit || "?"),
        pct: String(context.pct ?? "?"),
      })}`
      : "";
    return `
      <div class="system-user-row recent detailed">
        <div class="system-user-main">
          <strong>${escapeHtml(row.clientName || row.clientIp || "unknown")}</strong>
          <code>${escapeHtml(row.lastPath || "/v1/chat/completions")}</code>
          <span>${escapeHtml(row.lastTime || "")}</span>
        </div>
        <small>${escapeHtml(timingText + contextText)}</small>
      </div>
    `;
  }).join("");
  const speedLine = (gpuUtil > 0 || promptTps > 0 || predictTps > 0)
    ? `<div class="system-activity-help">${escapeHtml(`GPU ${gpuUtil}% · prompt ${formatTps(promptTps)} t/s · predict ${formatTps(predictTps)} t/s`)}</div>`
    : "";
  const contextLine = context.tokens ? `
    <div class="system-activity-help">${escapeHtml(t("gpuUsersContext", {
      tokens: String(context.tokens),
      limit: String(context.limit || "?"),
      pct: String(context.pct ?? "?"),
      remaining: String(context.remaining ?? "?"),
    }))}</div>
  ` : "";
  const timingLine = (timing.promptTokens || timing.evalTokens) ? `
    <div class="system-activity-help">${escapeHtml(t("gpuUsersTiming", {
      promptTokens: String(timing.promptTokens ?? 0),
      promptTps: String(timing.promptTps ?? 0),
      evalTokens: String(timing.evalTokens ?? 0),
      evalTps: String(timing.evalTps ?? 0),
    }))}</div>
  ` : "";
  const cacheLine = promptCache.prompts ? `
    <div class="system-activity-help">${escapeHtml(t("gpuUsersCache", {
      prompts: String(promptCache.prompts),
      used: String(Math.round(promptCache.usedMiB || 0)),
      limit: String(Math.round(promptCache.limitMiB || 0)),
      pct: String(promptCache.pct ?? "?"),
    }))}</div>
  ` : "";
  return `
    ${speedLine}
    ${contextLine}
    ${timingLine}
    ${cacheLine}
    ${proxyRows ? `<div class="system-activity-title">${escapeHtml(t("gpuUsersProxyPorts"))}</div>${proxyRows}` : ""}
    ${activeRows}
    ${slotRows}
    ${byClientRows ? `<div class="system-activity-title">${escapeHtml(t("gpuUsersByClient"))}</div>${byClientRows}` : ""}
    ${recentRows ? `<div class="system-activity-title">${escapeHtml(t("gpuUsersRecent"))}</div>${recentRows}` : ""}
    ${proxyRows || activeRows || slotRows || byClientRows || recentRows ? "" : `<div class="system-process-empty">${escapeHtml(t("gpuUsersNoData"))}</div>`}
  `;
}

export function renderSystemMonitor(data) {
  ui.latestSystemMonitor = data;
  if (activeView === "topology" && topology && !ui.topologyProxyFormOpen && !topologyPointerDrag) {
    refreshTopologyActivityState();
    const clientsDynamic = document.querySelector(".topology-llama-clients-dynamic");
    if (clientsDynamic) clientsDynamic.innerHTML = renderLlamaClientsInnerHtml();
    const clientsCount = $("topologyLlamaClientsCount");
    if (clientsCount) {
      const clients = data.latest?.llamaClients?.clients || [];
      clientsCount.textContent = clients.length || 0;
    }
  }
}

// ── end Request History ────────────────────────────────────────────────────

export async function refreshSystemMonitor() {
  if (systemMonitorInflight) return;
  systemMonitorInflight = true;
  try {
    renderSystemMonitor(await api("/api/system-monitor", { signal: AbortSignal.timeout(4000) }));
  } catch (err) {
    const status = $("systemMonitor")?.querySelector(".system-monitor-status");
    if (status) status.textContent = `refresh failed: ${err.message}`;
  } finally {
    systemMonitorInflight = false;
  }
}

export function startSystemMonitor() {
  clearInterval(systemMonitorTimer);
  refreshSystemMonitor();
  systemMonitorTimer = setInterval(refreshSystemMonitor, 1000);
}

export function stopSystemMonitor() {
  clearInterval(systemMonitorTimer);
  systemMonitorTimer = null;
}

export async function refreshTopologyMonitor() {
  if (activeView !== "topology" || systemMonitorTimer || systemMonitorInflight) return;
  systemMonitorInflight = true;
  try {
    // Timeout matters: without it one hung request (e.g. during a service
    // restart) leaves systemMonitorInflight stuck true and silently kills
    // this poll loop until the page is reloaded.
    ui.latestSystemMonitor = await api("/api/system-monitor", { signal: AbortSignal.timeout(4000) });
    if (topology && !ui.topologyProxyFormOpen && !topologyPointerDrag) {
      refreshTopologyActivityState();
    }
  } catch (err) {
    // Topology can keep the last telemetry snapshot; the drawer shows monitor errors.
  } finally {
    systemMonitorInflight = false;
  }
}

export function startTopologyMonitor() {
  clearInterval(topologyMonitorTimer);
  refreshTopologyMonitor();
  topologyMonitorTimer = setInterval(refreshTopologyMonitor, 1000);
}

export function stopTopologyMonitor() {
  clearInterval(topologyMonitorTimer);
  topologyMonitorTimer = null;
}

export async function saveSystemMonitorRetention() {
  const input = $("systemMonitorRetention");
  if (!input) return;
  const value = Math.max(60, Math.min(Number(input.value || 600), 3600));
  input.value = String(value);
  try {
    const data = await api("/api/system-monitor/settings", {
      method: "POST",
      body: JSON.stringify({ retentionSeconds: value }),
    });
    renderSystemMonitor(data.monitor);
  } catch (err) {
    toast(err.message);
  }
}

export async function editClientLabel(ip) {
  const current = (ui.latestSystemMonitor?.clientLabels || {})[ip] || "";
  const label = await appPrompt(t("dlgClientLabel", { ip }), { value: current, confirmLabel: t("save") });
  if (label === null) return;
  try {
    await api("/api/system-monitor/client-label", {
      method: "POST",
      body: JSON.stringify({ ip, label }),
    });
    await refreshSystemMonitor();
    toast(t("saved"));
  } catch (err) {
    toast(err.message);
  }
}

