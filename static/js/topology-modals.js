// Detail/config modals: client detail, logs, priorities, schedule.
import { SCHEDULE_DAY_LABELS, SCHEDULE_WEEKDAYS, scheduleOutputColor } from "./canvas.js";
import { appPrompt } from "./dialogs.js";
import { badge, option } from "./form.js";
import { t } from "./i18n.js";
import {
  modalitiesText,
  parseModelName,
  topologyCrownSvg,
} from "./model-meta.js";
import { formatTps } from "./polling.js";
import { topologyRouterOutputLabel } from "./routers.js";
import { setTopology, state, topology, ui } from "./state.js";
import { _proxyUpstreamStr, proxyEffectiveWaitTimeout } from "./topology-activity.js";
import {
  topologyScheduleGrid,
  topologySchedulePaintOutput,
  topologyScheduleRouterId,
} from "./topology-dnd.js";
import { topologyProxyOwner } from "./topology-proxies.js";
import { refreshTopology, renderTopology } from "./topology-render.js";
import { $, api, escapeHtml, pill, toast } from "./utils.js";

export let topologyQueuePriorityModalOpen = false;
export let topologyPriorityModalOpen = false;
export let topologyPriorityOrder = [];
export let topologyQueuePriorityEdits = {};  // pending edits: cloudFallbackPct, priorityPreemptPct, queueAbortPct, stickySlotSec; routes: {port: {cloudFallbackPct,priorityPreemptPct,queueAbortPct}}
export let topologyQueuePriorityProxyExpanded = {};  // {port: true} — which proxy rows are expanded in the modal
export let topologyRawConfigOpen = false;    // raw agent-proxies.json viewer modal
export let topologyRawConfigText = "";
export let topologyRawConfigPath = "";
export let topologyPriorityEdits = {};       // pending edits: preemptGraceSec, preemptEnabled
export let queueThresholds = null;           // cached from /api/queue-thresholds
export let topologyLogsOpen = false;
export let topologyLogsData = null;
export let topologyLogsDate = "";

export function priorityHueForLevel(level) {
  const n = Math.max(1, Math.min(10, Number(level) || 1));
  return Math.round(220 - (n - 1) * 22);
}

export function priorityLevelForIndex(index) {
  return Math.max(1, Math.min(10, 10 - index));
}

export function _fmtSec(sec) {
  if (!sec) return "0s";
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60), s = sec % 60;
  return s ? `${m}m ${s}s` : `${m}m`;
}

export function _renderQueueThresholdTimelines(globalCloudPct, globalPriorPct, globalAbortPct) {
  // Show every local (non-cloud) proxy. Use its synced wait_timeout when known,
  // otherwise fall back to the effective timeout (route config) or 3600s default.
  const proxies = topology?.proxies || [];
  const localProxies = proxies.filter((p) => String(p.upstreamType || "llama") !== "cloud" && p.enabled !== false);
  if (!localProxies.length) return "<em>No local proxies configured.</em>";
  const routeEdits = topologyQueuePriorityEdits.routes || {};

  return localProxies.map((proxy) => {
    const port = Number(proxy.port || 0);
    const effective = proxyEffectiveWaitTimeout(proxy);
    const wt = effective > 0 ? effective : 3600;
    const isDefault = !(effective > 0);
    const expanded = !!topologyQueuePriorityProxyExpanded[port];

    // Resolve effective pct: pending edit > saved route override > global slider
    const thresh = (queueThresholds?.proxies || []).find((p) => Number(p.port || 0) === port) || {};
    const pendingRoute = routeEdits[port] || {};
    function _effPct(key, globalVal) {
      if (Object.prototype.hasOwnProperty.call(pendingRoute, key)) {
        const v = pendingRoute[key];
        return v === null ? globalVal : Math.max(0, Math.min(100, Number(v)));
      }
      // Use saved effective value from computed thresholds when available
      const effKey = { cloudFallbackPct: "effectiveCloudPct", priorityPreemptPct: "effectivePriorityPct", queueAbortPct: "effectiveAbortPct" }[key];
      if (effKey && thresh[effKey] !== undefined) return thresh[effKey];
      return globalVal;
    }
    function _hasOverride(key) {
      if (Object.prototype.hasOwnProperty.call(pendingRoute, key)) return pendingRoute[key] !== null;
      const flagKey = { cloudFallbackPct: "hasCloudOverride", priorityPreemptPct: "hasPriorityOverride", queueAbortPct: "hasAbortOverride" }[key];
      return !!(flagKey && thresh[flagKey]);
    }

    const cloudPct = _effPct("cloudFallbackPct", globalCloudPct);
    const priorPct = _effPct("priorityPreemptPct", globalPriorPct);
    const abortPct = _effPct("queueAbortPct", globalAbortPct);
    const hasPriority = Number(proxy.priority || 0) > 0;
    const cloudSec = proxy.cloudFallbackProviderId ? Math.round(wt * cloudPct / 100) : null;
    const priorSec = hasPriority ? Math.round(wt * priorPct / 100) : null;
    const abortSec = Math.round(wt * abortPct / 100);

    const events = [];
    if (cloudSec !== null) events.push({ pct: cloudSec / wt * 100, cls: "cloud", icon: "↑☁", time: _fmtSec(cloudSec) });
    if (priorSec !== null) events.push({ pct: priorSec / wt * 100, cls: "crown", icon: topologyCrownSvg("crown-icon"), time: _fmtSec(priorSec) });
    events.push({ pct: abortSec / wt * 100, cls: "abort", icon: "✕", time: _fmtSec(abortSec) });

    const notches = events.map((e) =>
      `<span class="topology-tl-notch ${e.cls}" style="left:${e.pct.toFixed(1)}%" title="${escapeHtml(e.time)}">${e.icon}</span>`
    ).join("");
    const marks = events.map((e) =>
      `<span class="topology-tl-mark ${e.cls}" style="left:${e.pct.toFixed(1)}%"><span class="topology-tl-ic">${e.icon}</span><span>${escapeHtml(e.time)}</span></span>`
    ).join("");

    const anyOverride = _hasOverride("cloudFallbackPct") || _hasOverride("priorityPreemptPct") || _hasOverride("queueAbortPct");
    const hasCloud = !!proxy.cloudFallbackProviderId;

    // Always-visible per-proxy slider. All 3 handles always rendered;
    // inapplicable ones are grayed out (qp-handle-inactive) and non-draggable.
    const sliderSection = `
      <div class="qp-proxy-overrides">
        <div class="topology-pct-track qp-proxy-track" data-qp-proxy-track="${port}">
          <div class="topology-pct-fill" data-qp-proxy-fill="${port}" style="width:${abortPct}%"></div>
          <div class="topology-pct-handle cloud${!hasCloud ? " qp-handle-inactive" : ""}" style="left:${cloudPct}%"
              data-qp-proxy-handle="${port}" data-qp-pct-key="cloudFallbackPct" tabindex="0"
              title="${escapeHtml(hasCloud ? t("qpCloudFallbackTitle") : t("qpNoCloudTitle"))}">
            <span class="qp-handle-icon">↑☁</span>
            <span class="qp-handle-time">${_fmtSec(Math.round(wt * cloudPct / 100))}</span>
          </div>
          <div class="topology-pct-handle crown${!hasPriority ? " qp-handle-inactive" : ""}" style="left:${priorPct}%"
              data-qp-proxy-handle="${port}" data-qp-pct-key="priorityPreemptPct" tabindex="0"
              title="${escapeHtml(hasPriority ? t("qpPriorityTitle") : t("qpNoPriorityTitle"))}">
            <span class="qp-handle-icon">👑</span>
            <span class="qp-handle-time">${_fmtSec(Math.round(wt * priorPct / 100))}</span>
          </div>
          <div class="topology-pct-handle abort" style="left:${abortPct}%"
              data-qp-proxy-handle="${port}" data-qp-pct-key="queueAbortPct"
              tabindex="0" title="${escapeHtml(t("qpQueueAbortTitle"))}">
            <span class="qp-handle-icon">✕</span>
            <span class="qp-handle-time">${_fmtSec(Math.round(wt * abortPct / 100))}</span>
          </div>
        </div>
        <div class="qp-proxy-override-footer">
          <span class="qp-override-hint">${escapeHtml(t("qpOverrideHint", { wt }))}</span>
          ${anyOverride ? `<button class="mini-link qp-override-reset" type="button" data-qp-proxy-reset="${port}" title="${escapeHtml(t("qpResetGlobalTitle"))}">${escapeHtml(t("qpResetGlobalBtn"))}</button>` : ""}
        </div>
      </div>`;

    return `
      <div class="qp-proxy-tl-row${anyOverride ? " has-override" : ""}" data-qp-proxy-row="${port}">
        <div class="qp-proxy-tl-head">
          <span class="qp-proxy-tl-label">${escapeHtml(proxy.label || `:${proxy.port}`)}${anyOverride ? `<span class="qp-override-dot" title="${escapeHtml(t("tmTitleCustomThresholds"))}">•</span>` : ""}</span>
          <span class="qp-proxy-tl-wt">wait_timeout=${wt}s${isDefault ? " (default)" : ""}</span>
        </div>
        ${sliderSection}
      </div>
    `;
  }).join("");
}

export function _queuePctExampleText(cloudPct, priorPct, abortPct) {
  // Find first llama proxy with clientTimeoutSeconds > 0 for a concrete seconds example
  const proxies = topology?.proxies || [];
  const exProxy = proxies.find((p) => Number(p.clientTimeoutSeconds || 0) > 0 && String(p.upstreamType || "llama") !== "cloud");
  if (!exProxy) return "";
  const wt = Number(exProxy.clientTimeoutSeconds);
  const cloudSec = Math.round(wt * cloudPct / 100);
  const priorSec = Math.round(wt * priorPct / 100);
  const abortSec = Math.round(wt * abortPct / 100);
  return `${exProxy.label} · wait_timeout=${wt}s → ↑☁ ${cloudSec}s · 👑 ${priorSec}s · ✕ ${abortSec}s`;
}

export function renderTopologyQueuePriorityModal() {
  if (!topologyQueuePriorityModalOpen) return "";
  const policy = topology?.proxyPolicy || {};
  const edits = topologyQueuePriorityEdits;

  // Percentage threshold values — prefer live edits, fall back to saved policy
  const cloudPct = edits.cloudFallbackPct ?? (policy.cloudFallbackPct ?? 20);
  const priorPct = edits.priorityPreemptPct ?? (policy.priorityPreemptPct ?? 50);
  const abortPct = edits.queueAbortPct ?? (policy.queueAbortPct ?? 85);
  const ss = edits.stickySlotSec ?? (policy.stickySlotSec ?? 0);
  // Preemption settings (moved here from the crown's Priority modal so all
  // preemption knobs live in one place next to the 👑 threshold slider).
  const pg = edits.preemptGraceSec ?? (policy.preemptGraceSec ?? 20);
  const pe = Object.prototype.hasOwnProperty.call(edits, "preemptEnabled")
    ? edits.preemptEnabled : (policy.preemptEnabled !== false);

  // Example seconds text
  const exampleText = _queuePctExampleText(cloudPct, priorPct, abortPct);

  // Handle positions (clamped 0–100)
  const cl = Math.max(0, Math.min(100, cloudPct)).toFixed(1);
  const pl = Math.max(0, Math.min(100, priorPct)).toFixed(1);
  const al = Math.max(0, Math.min(100, abortPct)).toFixed(1);

  return `
    <div class="topology-policy-overlay" data-topology-queue-priority-overlay>
      <div class="topology-policy-modal queue-priority-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(t("topologyQueuePriorityTitle"))}">
        <div class="topology-card-head">
          <strong>${escapeHtml(t("topologyQueuePriorityTitle"))}</strong>
          <button class="icon-action compact" type="button" data-topology-queue-priority-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
        </div>

        <div class="topology-modal-section-label">${escapeHtml(t("topologyQueueSection"))}</div>
        <div class="topology-policy-hint">${escapeHtml(t("topologyQueuePctHintShort"))}</div>

        <div class="topology-pct-section">
          <div class="topology-pct-track" data-qp-track>
            <div class="topology-pct-fill" data-qp-fill style="width:${al}%"></div>
            <div class="topology-pct-handle cloud" data-qp-handle="cloudFallbackPct" style="left:${cl}%" title="↑☁ Cloud fallback — transparently redirect to cloud at this % of wait_timeout" role="slider" aria-label="Cloud fallback %" aria-valuenow="${cloudPct}" aria-valuemin="0" aria-valuemax="100" tabindex="0">
              <span class="qp-handle-icon">↑☁</span><span class="qp-handle-pct">${cloudPct}%</span>
            </div>
            <div class="topology-pct-handle priority" data-qp-handle="priorityPreemptPct" style="left:${pl}%" title="👑 Priority preempt — trigger preemption at this % of wait_timeout" role="slider" aria-label="Priority preempt %" aria-valuenow="${priorPct}" aria-valuemin="0" aria-valuemax="100" tabindex="0">
              <span class="qp-handle-icon">👑</span><span class="qp-handle-pct">${priorPct}%</span>
            </div>
            <div class="topology-pct-handle abort" data-qp-handle="queueAbortPct" style="left:${al}%" title="✕ Queue abort — return 503 at this % of wait_timeout" role="slider" aria-label="Queue abort %" aria-valuenow="${abortPct}" aria-valuemin="1" aria-valuemax="100" tabindex="0">
              <span class="qp-handle-icon">✕</span><span class="qp-handle-pct">${abortPct}%</span>
            </div>
          </div>
          <div class="topology-pct-axis"><span>0%</span><span>50%</span><span>100%</span></div>
          <div class="topology-pct-example" data-qp-example>${escapeHtml(exampleText)}</div>
        </div>

        <div class="topology-policy-grid" style="margin-top:10px">
          <label title="Reserve the local slot for the same proxy N seconds after its request finishes. 0 = disabled.">${escapeHtml(t("topologyStickySlot"))}<input name="stickySlotSec" type="number" min="0" max="120" value="${escapeHtml(String(ss))}" data-topology-qp-policy="stickySlotSec"></label>
          <label title="After 👑 preemption fires, how long to wait for the active request to release the slot after the stop signal before giving up.">${escapeHtml(t("topologyPreemptGrace"))}<input name="preemptGraceSec" type="number" min="1" max="300" value="${escapeHtml(String(pg))}" data-topology-qp-policy="preemptGraceSec"></label>
          <label class="topology-checkbox" style="grid-column:1/-1"><input name="preemptEnabled" type="checkbox"${pe ? " checked" : ""} data-topology-qp-policy="preemptEnabled"> ${escapeHtml(t("topologyPreemptCheckbox"))}</label>
        </div>

        <div class="topology-threshold-section" style="margin-top:14px;border-top:1px solid var(--line);padding-top:10px">
          <div style="font-size:11px;font-weight:700;text-transform:uppercase;color:var(--muted);padding:2px 0 8px">${escapeHtml(t("agentTimelines"))}</div>
          <div style="font-size:11px;max-height:480px;overflow-y:auto;padding-right:4px">
            ${_renderQueueThresholdTimelines(cloudPct, priorPct, abortPct)}
          </div>
        </div>

        <div class="topology-priority-actions">
          <button class="ghost-action" type="button" data-topology-raw-config title="Show the raw agent-proxies.json (policy + per-agent computed seconds) stored on the backend" style="margin-right:auto">{ } config file</button>
          <button class="ghost-action" type="button" data-topology-queue-priority-cancel>${escapeHtml(t("topologyCancel"))}</button>
          <button class="primary-mini-action" type="button" data-topology-queue-priority-save>${escapeHtml(t("topologySave"))}</button>
        </div>
      </div>
    </div>
  `;
}

export function renderTopologyRawConfigModal() {
  if (!topologyRawConfigOpen) return "";
  return `
    <div class="topology-policy-overlay" data-topology-raw-overlay>
      <div class="topology-policy-modal raw-config-modal" role="dialog" aria-modal="true" aria-label="agent-proxies.json">
        <div class="topology-card-head">
          <strong>${escapeHtml(topologyRawConfigPath || "agent-proxies.json")}</strong>
          <button class="icon-action compact" type="button" data-topology-raw-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
        </div>
        <div class="topology-policy-hint">${t("policyStoredHint")}</div>
        <pre class="topology-raw-config">${escapeHtml(topologyRawConfigText || "(empty)")}</pre>
      </div>
    </div>
  `;
}

export async function openRawConfigViewer() {
  topologyRawConfigText = "loading…";
  topologyRawConfigPath = "";
  topologyRawConfigOpen = true;
  renderTopology();
  try {
    const res = await api("/api/agent-proxies/raw");
    topologyRawConfigText = res.content || "(empty)";
    topologyRawConfigPath = res.path || "agent-proxies.json";
  } catch (err) {
    topologyRawConfigText = t("rawConfigError", { msg: err.message });
  }
  renderTopology();
}

export function closeRawConfigViewer() {
  topologyRawConfigOpen = false;
  topologyRawConfigText = "";
  renderTopology();
}

export function renderTopologyPriorityModal() {
  if (!topologyPriorityModalOpen) return "";
  const proxies = topology?.proxies || [];

  const priorityRows = topologyPriorityOrder.map((id, index) => {
    const proxy = proxies.find((row) => row.id === id);
    if (!proxy) return "";
    const level = priorityLevelForIndex(index);
    const hue = priorityHueForLevel(level);
    const endpoint = `:${proxy.port || "?"} → ${_proxyUpstreamStr(proxy)}`;
    return `
      <div class="topology-priority-row" data-priority-row="${escapeHtml(proxy.id)}" draggable="true">
        <span class="topology-priority-handle" aria-hidden="true" title="Drag to reorder">⠿</span>
        <span class="topology-priority-badge" style="background:hsl(${hue},66%,42%)">${level}</span>
        <div class="topology-priority-meta">
          <strong>${escapeHtml(proxy.label || `:${proxy.port}`)}</strong>
          <small>${escapeHtml(proxy.topologyRole || "route")} · ${escapeHtml(endpoint)}</small>
        </div>
        <button class="icon-action compact" type="button" data-priority-remove="${escapeHtml(proxy.id)}" aria-label="Remove priority" title="Remove priority">×</button>
      </div>
    `;
  }).filter(Boolean).join("") || `<div class="topology-priority-empty">${escapeHtml(t("topologyPriorityEmpty"))}</div>`;

  return `
    <div class="topology-policy-overlay" data-topology-priority-overlay>
      <div class="topology-policy-modal queue-priority-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(t("topologyPrioritySection"))}">
        <div class="topology-card-head">
          <strong>${escapeHtml(t("topologyPrioritySection"))}</strong>
          <button class="icon-action compact" type="button" data-topology-priority-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
        </div>

        <div class="topology-priority-hint">${escapeHtml(t("topologyPriorityHint"))}</div>
        <div class="topology-priority-list">${priorityRows}</div>

        <div class="topology-priority-actions">
          <button class="ghost-action" type="button" data-topology-priority-cancel>${escapeHtml(t("topologyCancel"))}</button>
          <button class="primary-mini-action" type="button" data-topology-priority-save>${escapeHtml(t("topologySave"))}</button>
        </div>
      </div>
    </div>
  `;
}

export function openQueuePriorityModal() {
  topologyQueuePriorityEdits = {};
  topologyQueuePriorityProxyExpanded = {};
  topologyQueuePriorityModalOpen = true;
  renderTopology();
}

export function closeQueuePriorityModal() {
  topologyQueuePriorityModalOpen = false;
  topologyQueuePriorityEdits = {};
  topologyQueuePriorityProxyExpanded = {};
  renderTopology();
}

export async function saveQueuePriorityModal() {
  const policyChanges = {};
  ["cloudFallbackPct", "priorityPreemptPct", "queueAbortPct", "stickySlotSec", "preemptGraceSec", "preemptEnabled"].forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(topologyQueuePriorityEdits, key)) {
      policyChanges[key] = topologyQueuePriorityEdits[key];
    }
  });

  // Save global policy if changed
  if (Object.keys(policyChanges).length) {
    const merged = { ...(topology?.proxyPolicy || {}), ...policyChanges };
    await api("/api/agent-proxies/policy", {
      method: "POST",
      body: JSON.stringify({ policy: merged }),
    });
  }

  // Save per-proxy overrides
  const routeEdits = topologyQueuePriorityEdits.routes || {};
  const routeSavePromises = Object.entries(routeEdits).map(([port, overrides]) => {
    const patch = {};
    for (const key of ["cloudFallbackPct", "priorityPreemptPct", "queueAbortPct"]) {
      if (Object.prototype.hasOwnProperty.call(overrides, key)) {
        patch[key] = overrides[key]; // null = clear override
      }
    }
    if (!Object.keys(patch).length) return Promise.resolve();
    return api("/api/agent-proxies/route-policy", {
      method: "POST",
      body: JSON.stringify({ port: Number(port), ...patch }),
    });
  });
  await Promise.all(routeSavePromises);

  if (!Object.keys(policyChanges).length && !Object.keys(routeEdits).length) {
    closeQueuePriorityModal();
    return;
  }

  topologyQueuePriorityModalOpen = false;
  topologyQueuePriorityEdits = {};
  topologyQueuePriorityProxyExpanded = {};
  await refreshTopology();
  recalcQueueThresholds();
  toast("saved · queue policy");
}

export function openPriorityModal(proxyId) {
  const proxies = topology?.proxies || [];
  topologyPriorityOrder = proxies
    .filter((proxy) => Math.max(0, Number(proxy.priority || 0)) > 0)
    .sort((a, b) => Number(b.priority || 0) - Number(a.priority || 0) || Number(a.port || 0) - Number(b.port || 0))
    .map((proxy) => proxy.id);
  topologyPriorityEdits = {};
  if (proxyId && !topologyPriorityOrder.includes(proxyId)) {
    const proxy = proxies.find((row) => row.id === proxyId);
    if (proxy) topologyPriorityOrder.unshift(proxyId);
  }
  topologyPriorityModalOpen = true;
  renderTopology();
}

export function closePriorityModal() {
  topologyPriorityModalOpen = false;
  topologyPriorityOrder = [];
  topologyPriorityEdits = {};
  renderTopology();
}

export async function savePriorityModal() {
  const proxies = topology?.proxies || [];
  const originalPriority = new Map();
  proxies.forEach((proxy) => {
    const value = Math.max(0, Math.min(10, Number(proxy.priority || 0)));
    if (value > 0) originalPriority.set(proxy.id, value);
  });
  const targets = new Map();
  topologyPriorityOrder.forEach((id, index) => {
    if (proxies.find((proxy) => proxy.id === id)) {
      targets.set(id, priorityLevelForIndex(index));
    }
  });
  const routeChanges = [];
  originalPriority.forEach((_value, id) => {
    if (!targets.has(id)) {
      const proxy = proxies.find((row) => row.id === id);
      if (proxy) routeChanges.push({ port: proxy.port, priority: 0 });
    }
  });
  targets.forEach((target, id) => {
    const current = originalPriority.get(id) || 0;
    if (current !== target) {
      const proxy = proxies.find((row) => row.id === id);
      if (proxy) routeChanges.push({ port: proxy.port, priority: target });
    }
  });
  if (!routeChanges.length) {
    closePriorityModal();
    return;
  }
  for (const change of routeChanges) {
    await api("/api/agent-proxies/route-policy", {
      method: "POST",
      body: JSON.stringify(change),
    });
  }
  topologyPriorityModalOpen = false;
  topologyPriorityOrder = [];
  topologyPriorityEdits = {};
  await refreshTopology();
  const total = routeChanges.length;
  toast(`saved · ${total} change${total === 1 ? "" : "s"}`);
}

export function topologyLogSummary(row) {
  const item = row.item || {};
  const parts = [
    row.timeIso || (row.time ? new Date(row.time * 1000).toLocaleString() : ""),
    row.event || "",
    row.route || item.route || "",
    item.port || row.port ? `:${item.port || row.port}` : "",
    item.status || row.status ? `status ${item.status || row.status}` : "",
    item.error || row.error || "",
  ].filter(Boolean);
  return parts.join(" · ");
}

export function renderTopologyLogDetail(row) {
  const item = row.item || {};
  const status = item.status || row.status || 0;
  const isError = status >= 400 || item.error || row.error;
  const sections = [];

  // Error body from upstream (e.g. chatgpt.com 400 response)
  const errBody = row.upstreamErrorBody;
  if (errBody) {
    let parsed = null;
    try { parsed = JSON.parse(errBody); } catch (_) {}
    sections.push(`<div class="log-detail-section log-detail-error">
      <div class="log-detail-label">Upstream error body</div>
      <pre class="log-detail-pre">${escapeHtml(parsed ? JSON.stringify(parsed, null, 2) : errBody)}</pre>
    </div>`);
  }

  // Cloud request metadata
  const cm = row.cloudMeta;
  if (cm) {
    const pills = [
      cm.model ? `<span class="log-detail-pill">model: ${escapeHtml(cm.model)}</span>` : "",
      cm.toolCount != null ? `<span class="log-detail-pill">tools: ${cm.toolCount}</span>` : "",
      cm.inputCount != null ? `<span class="log-detail-pill">messages: ${cm.inputCount}</span>` : "",
    ].filter(Boolean).join("");
    if (pills) sections.push(`<div class="log-detail-section"><div class="log-detail-label">Cloud request</div><div class="log-detail-pills">${pills}</div></div>`);
  }

  // Error message
  const errMsg = item.error || row.error;
  if (errMsg && !errBody) {
    sections.push(`<div class="log-detail-section log-detail-error"><div class="log-detail-label">Error</div><div class="log-detail-value">${escapeHtml(errMsg)}</div></div>`);
  }

  // Core fields
  const fields = [
    item.durationMs != null && ["Duration", `${item.durationMs} ms`],
    item.bytes != null && ["Bytes out", item.bytes],
    item.firstByteMs != null && ["First byte", `${item.firstByteMs} ms`],
    item.method && ["Method", item.method],
    item.path && ["Path", item.path],
    item.client && ["Client", item.client],
    item.upstream && ["Upstream", item.upstream],
  ].filter(Boolean);
  if (fields.length) {
    const rows2 = fields.map(([k, v]) => `<tr><td class="log-detail-key">${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`).join("");
    sections.push(`<div class="log-detail-section"><table class="log-detail-table">${rows2}</table></div>`);
  }

  // Stream summary
  const st = item.stream;
  if (st && st.events) {
    const sr = [
      st.events && ["Events", st.events],
      st.deltaTextChars && ["Text chars", st.deltaTextChars],
      st.finishReasons?.length && ["Finish", st.finishReasons.join(", ")],
      st.usage?.total_tokens && ["Tokens", st.usage.total_tokens],
    ].filter(Boolean);
    if (sr.length) {
      const rows2 = sr.map(([k, v]) => `<tr><td class="log-detail-key">${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`).join("");
      sections.push(`<div class="log-detail-section"><div class="log-detail-label">Stream</div><table class="log-detail-table">${rows2}</table></div>`);
    }
  }

  // Queue info
  const q = item.queue || row.queue;
  if (q && q.queuedMs) {
    sections.push(`<div class="log-detail-section"><div class="log-detail-label">Queue</div><div class="log-detail-pills"><span class="log-detail-pill">waited: ${q.queuedMs} ms</span>${q.preempted ? `<span class="log-detail-pill">preempted: ${escapeHtml(q.preempted)}</span>` : ""}</div></div>`);
  }

  // Raw JSON fallback toggle
  sections.push(`<details class="log-detail-raw"><summary>Raw JSON</summary><pre>${escapeHtml(JSON.stringify(row, null, 2))}</pre></details>`);

  return sections.join("");
}

export function renderTopologyLogsModal() {
  if (!topologyLogsOpen) return "";
  const rows = topologyLogsData?.rows || [];
  const dates = topologyLogsData?.dates || [];
  const activeDate = topologyLogsData?.date || topologyLogsDate || "";
  return `
    <div class="topology-policy-overlay" data-topology-logs-overlay>
      <div class="topology-policy-modal topology-logs-modal" role="dialog" aria-modal="true" aria-label="Proxy logs">
        <div class="topology-card-head">
          <strong>Proxy Logs</strong>
          <button class="icon-action compact" type="button" data-topology-logs-close aria-label="Close proxy logs" title="Close">×</button>
        </div>
        <div class="topology-logs-toolbar">
          <select data-topology-logs-date>
            ${dates.length
              ? dates.map((date) => `<option value="${escapeHtml(date)}"${date === activeDate ? " selected" : ""}>${escapeHtml(date)}</option>`).join("")
              : `<option value="${escapeHtml(activeDate)}">${escapeHtml(activeDate || t("todayWord"))}</option>`}
          </select>
          <button class="icon-action compact" type="button" data-topology-logs-refresh aria-label="Refresh logs" title="Refresh">↻</button>
        </div>
        <div class="topology-log-list">
          ${rows.length ? rows.map((row) => {
            const s = row.item?.status || row.status || 0;
            const cls = s >= 400 ? "failed" : (row.error || row.item?.error ? "failed" : "");
            return `<details class="topology-log-row ${cls}">
              <summary>${escapeHtml(topologyLogSummary(row))}</summary>
              <div class="log-detail-body">${renderTopologyLogDetail(row)}</div>
            </details>`;
          }).join("") : `<div class="topology-muted">${escapeHtml(t("noProxyLogRows"))}</div>`}
        </div>
      </div>
    </div>
  `;
}

export async function loadTopologyLogs(date = topologyLogsDate) {
  const query = new URLSearchParams();
  if (date) query.set("date", date);
  query.set("limit", "300");
  topologyLogsData = await api(`/api/agent-proxy-logs?${query.toString()}`);
  topologyLogsDate = topologyLogsData.date || date || "";
}

export async function openTopologyLogs() {
  topologyLogsOpen = true;
  await loadTopologyLogs();
  renderTopology();
}

export async function setTopologyProxyRoutePolicy(proxyId, patch) {
  const proxy = (topology?.proxies || []).find((row) => row.id === proxyId);
  if (!proxy) return;
  await api("/api/agent-proxies/route-policy", {
    method: "POST",
    body: JSON.stringify({ port: proxy.port, ...patch }),
  });
  await refreshTopology();
  toast("proxy policy updated");
}

export async function stopTopologyProxy(proxyId) {
  const proxy = (topology?.proxies || []).find((row) => row.id === proxyId);
  if (!proxy) return;
  await api("/api/agent-proxies/stop", {
    method: "POST",
    body: JSON.stringify({ port: proxy.port }),
  });
  await refreshTopology();
  toast("stop requested");
}


export async function editTopologyClientAlias(hostId, currentName) {
  const name = await appPrompt(t("dlgClientName"), { value: currentName || hostId, confirmLabel: t("save") });
  if (name === null) return;
  const data = await api("/api/topology/client-alias", {
    method: "POST",
    body: JSON.stringify({ hostId, name: name.trim() }),
  });
  setTopology(data.topology);
  renderTopology();
  toast(name.trim() ? "client name saved" : "client name reset");
}

// rules.schedule → [7][24] grid of outputId. First matching rule wins (engine
// semantics), so earlier rules are not overwritten by later ones.
export function scheduleRulesToGrid(router) {
  const grid = Array.from({ length: 7 }, () => Array(24).fill(""));
  for (const r of (router?.rules?.schedule || [])) {
    const days = (r.days && r.days.length) ? r.days : SCHEDULE_WEEKDAYS;
    const fromH = parseInt(String(r.from || "00:00"), 10);
    const toH = parseInt(String(r.to || "23:59"), 10);
    if (isNaN(fromH) || isNaN(toH)) continue;
    for (const day of days) {
      const d = SCHEDULE_WEEKDAYS.indexOf(String(day).toLowerCase());
      if (d < 0) continue;
      for (let h = 0; h < 24; h++) {
        const inWindow = fromH <= toH ? (h >= fromH && h <= toH) : (h >= fromH || h <= toH);
        if (inWindow && !grid[d][h]) grid[d][h] = r.output;
      }
    }
  }
  return grid;
}

// [7][24] grid → rules.schedule. Merges consecutive hours per day, then merges
// days that share an identical from/to/output window into one rule.
export function scheduleGridToRules(grid) {
  const perDay = [];
  for (let d = 0; d < 7; d++) {
    let h = 0;
    while (h < 24) {
      const out = grid[d][h];
      if (!out) { h++; continue; }
      let e = h;
      while (e + 1 < 24 && grid[d][e + 1] === out) e++;
      perDay.push({ day: SCHEDULE_WEEKDAYS[d], from: `${String(h).padStart(2, "0")}:00`, to: `${String(e).padStart(2, "0")}:59`, output: out });
      h = e + 1;
    }
  }
  const merged = new Map();
  for (const r of perDay) {
    const k = `${r.from}|${r.to}|${r.output}`;
    if (!merged.has(k)) merged.set(k, { days: [], from: r.from, to: r.to, output: r.output });
    merged.get(k).days.push(r.day);
  }
  return [...merged.values()];
}

export function renderTopologyScheduleModal() {
  if (!topologyScheduleRouterId) return "";
  const router = (topology?.routers || []).find((s) => s.id === topologyScheduleRouterId);
  if (!router) return "";
  const grid = topologyScheduleGrid || scheduleRulesToGrid(router);
  const outputs = router.outputs || [];

  const palette = [
    `<button class="sched-swatch ${topologySchedulePaintOutput === "" ? "active" : ""}" type="button" data-sched-paint="" title="${escapeHtml(t("schedEraseTitle"))}"><i class="sched-clear"></i>${escapeHtml(t("schedClearBtn"))}</button>`,
    ...outputs.map((o) => `<button class="sched-swatch ${topologySchedulePaintOutput === o.id ? "active" : ""}" type="button" data-sched-paint="${escapeHtml(o.id)}"><i style="background:${scheduleOutputColor(router, o.id)}"></i>${escapeHtml(topologyRouterOutputLabel(o))}</button>`),
  ].join("");

  const header = `<div class="sched-corner"></div>` + Array.from({ length: 24 }, (_, h) =>
    `<div class="sched-hour">${h % 3 === 0 ? h : ""}</div>`).join("");

  const rows = SCHEDULE_DAY_LABELS.map((dl, d) => {
    const cells = Array.from({ length: 24 }, (_, h) => {
      const out = grid[d][h];
      const bg = out ? scheduleOutputColor(router, out) : "";
      return `<div class="sched-cell ${out ? "painted" : ""}" data-sched-cell="1" data-day="${d}" data-hour="${h}" style="${bg ? `background:${bg}` : ""}"></div>`;
    }).join("");
    return `<div class="sched-day">${dl}</div>${cells}`;
  }).join("");

  return `
    <div class="topology-policy-overlay" data-topology-schedule-overlay>
      <div class="topology-policy-modal schedule-modal">
        <div class="topology-policy-head">
          <strong>⏱ Schedule — ${escapeHtml(t("topologyRouterTitle"))}</strong>
          <button class="icon-action compact" type="button" data-schedule-close aria-label="Close" title="Close">×</button>
        </div>
        <div class="sched-hint">${escapeHtml(t("schedPaintHint"))}</div>
        <div class="schedule-palette">${palette}</div>
        <div class="schedule-grid" data-schedule-grid>
          ${header}
          ${rows}
        </div>
        <div class="schedule-actions">
          <button class="mini-link" type="button" data-schedule-clear>Clear all</button>
          <span class="spacer"></span>
          <button class="mini-link" type="button" data-schedule-cancel>Cancel</button>
          <button class="primary-mini-action" type="button" data-schedule-save>Save</button>
        </div>
      </div>
    </div>`;
}

export async function fetchQueueThresholds() {
  try {
    const data = await api("/api/queue-thresholds");
    if (data?.thresholds) {
      queueThresholds = data.thresholds;
      // Re-render modal if open (threshold data may have changed)
      if (topologyQueuePriorityModalOpen) renderTopology();
    }
  } catch (_) { /* non-critical */ }
}

export async function recalcQueueThresholds() {
  try {
    const data = await api("/api/queue-thresholds/recalc", { method: "POST", body: "{}" });
    if (data?.thresholds) {
      queueThresholds = data.thresholds;
      if (topologyQueuePriorityModalOpen) renderTopology();
    }
  } catch (_) { /* non-critical */ }
}

