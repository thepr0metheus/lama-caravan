// Detail/config modals: llama & client detail, GPU, logs, priorities, schedule.
import { SCHEDULE_DAY_LABELS, SCHEDULE_WEEKDAYS, scheduleOutputColor } from "./canvas.js";
import { appPrompt } from "./dialogs.js";
import { badge, option } from "./form.js";
import { t } from "./i18n.js";
import { messages } from "./i18n-data.js";
import {
  modalitiesText,
  parseModelName,
  topologyCrownSvg,
  topologyCtxInfo,
} from "./model-meta.js";
import { action, formatTps } from "./polling.js";
import { topologyRouterOutputLabel } from "./routers.js";
import { setTopology, state, topology, ui } from "./state.js";
import { _proxyUpstreamStr, proxyEffectiveWaitTimeout } from "./topology-activity.js";
import {
  topologyGpuModalOpen,
  topologyLlamaDetailOpen,
  topologyProxySummaryOpen,
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
export let topologyAgentConfigClientId = ""; // agent openclaw config viewer
export let topologyAgentConfigAgentId = "";
export let topologyAgentConfigLoading = false;
export let topologyAgentConfigResult = null; // null | {ok, path, data, error}
export let topologyPriorityEdits = {};       // pending edits: preemptGraceSec, preemptEnabled
export let queueThresholds = null;           // cached from /api/queue-thresholds
export let topologyClientDetailFor = "";
export let topologyClientDetailAgentName = "";  // agent name if opened from an agent card
export let topologyClientDetailLoading = false;
export let topologyLogsOpen = false;
export let topologyLogsData = null;
export let topologyLogsDate = "";
export function renderTopologyLlamaDetail() {
  if (!topologyLlamaDetailOpen) return "";
  const server = topology?.server || {};
  const llama = (server.llamaServers || [])[0] || {};
  const runtime = server.runtime || {};
  const props = runtime.props || {};
  const genSettings = props.default_generation_settings || {};
  const parsed = parseModelName(llama.model);
  const ctx = topologyCtxInfo();
  const timing = ui.latestSystemMonitor?.latest?.llamaActivity?.lastTiming || {};
  const totalSlots = Number(ui.latestSystemMonitor?.latest?.llamaActivity?.totalSlots || 0);
  const nCtx = genSettings.n_ctx || props.n_ctx || ctx.limit || "?";
  const cache = ui.latestSystemMonitor?.latest?.llamaActivity?.promptCache || {};
  const tx = (k, v) => escapeHtml(t(k, v));
  return `
    <div class="topology-policy-overlay" data-topology-llama-detail-overlay>
      <div class="topology-policy-modal client-detail-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(llama.name || "Current")}">
        <div class="topology-card-head">
          <strong>${escapeHtml(llama.name || "Current")} · ${escapeHtml(t("topologyLlamaDetailTitle"))}</strong>
          <button class="icon-action compact" type="button" data-topology-llama-detail-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
        </div>
        <div class="client-detail-body">
          <section class="client-detail-section">
            <h3>${tx("topologyLlamaModelSection")}</h3>
            <div class="client-detail-grid">
              <div><span class="topology-muted">${tx("topologyLlamaName")}</span><strong>${escapeHtml(parsed?.label || "—")}</strong></div>
              <div><span class="topology-muted">${tx("topologyLlamaQuant")}</span><strong>${escapeHtml(parsed?.quant || "—")}</strong></div>
              <div><span class="topology-muted">${tx("topologyLlamaSize")}</span><strong>${escapeHtml(parsed?.size || "—")}</strong></div>
              <div><span class="topology-muted">${tx("topologyLlamaModalities")}</span><strong>${modalitiesText(llama, tx)}</strong></div>
            </div>
            <div class="client-detail-models">
              <div><span class="topology-muted">model</span> <code>${escapeHtml(llama.model || "—")}</code></div>
              ${llama.mmproj ? `<div><span class="topology-muted">mmproj</span> <code>${escapeHtml(llama.mmproj)}</code></div>` : ""}
            </div>
          </section>
          <section class="client-detail-section">
            <h3>${tx("topologyLlamaRuntimeSection")}</h3>
            <div class="client-detail-grid">
              <div><span class="topology-muted">${tx("topologyLlamaContextWindow")}</span><strong>${escapeHtml(String(nCtx))}</strong></div>
              <div><span class="topology-muted">${t("tmCtxUsed")}</span><strong>${ctx.limit ? `${ctx.tokens}/${ctx.limit} (${ctx.pct ?? "?"}%)` : "—"}</strong></div>
              <div><span class="topology-muted">${tx("topologySlots")}</span><strong>${escapeHtml(String(totalSlots || "?"))}</strong></div>
              <div><span class="topology-muted">${t("tmPromptGenTps")}</span><strong>${timing.promptTps ? formatTps(timing.promptTps) : "—"} / ${timing.evalTps ? formatTps(timing.evalTps) : "—"}</strong></div>
              <div><span class="topology-muted">${t("tmPort")}</span><strong>${escapeHtml(String(llama.port || "?"))}</strong></div>
              <div><span class="topology-muted">${t("tmStatus")}</span><strong>${escapeHtml(llama.status?.phase || "?")}</strong></div>
              ${cache.prompts ? `<div><span class="topology-muted">${t("tmPromptCache")}</span><strong>${Math.round(cache.usedMiB || 0)}/${Math.round(cache.limitMiB || 0)} MiB</strong></div>` : ""}
            </div>
            <div class="client-detail-models">
              <div><span class="topology-muted">${t("tmService")}</span> <code>${escapeHtml(llama.service || "—")}</code></div>
            </div>
          </section>
        </div>
      </div>
    </div>
  `;
}

export function priorityHueForLevel(level) {
  const n = Math.max(1, Math.min(10, Number(level) || 1));
  return Math.round(220 - (n - 1) * 22);
}

export function renderTopologyClientDetail() {
  if (!topologyClientDetailFor) return "";
  const client = (topology?.clients || []).find((row) => row.id === topologyClientDetailFor);
  const hostName = client?.name || client?.id || topologyClientDetailFor;
  // If opened from a specific agent card, show "host · agent"; otherwise just the host name
  const displayName = topologyClientDetailAgentName && topologyClientDetailAgentName !== hostName
    ? `${hostName} · ${topologyClientDetailAgentName}`
    : hostName;
  const entry = (topology?.openclawConfigs || {})[topologyClientDetailFor];
  const loading = topologyClientDetailLoading ? `<span class="topology-muted">${escapeHtml(t("topologyDetailRefreshing"))}</span>` : "";
  let body = "";
  if (!entry) {
    body = `<div class="topology-muted">${t("topologyDetailNoManager", { client: `<code>${escapeHtml(topologyClientDetailFor)}</code>` })}</div>`;
  } else if (!entry.ok) {
    body = `<div class="topology-incident-line failed">${escapeHtml(t("tmCouldNotReach"))} <code>${escapeHtml(entry.url || "")}</code>: ${escapeHtml(entry.error || t("unknownError"))}</div>`;
  } else {
    body = renderOpenclawConfigBody(entry.data || {}, entry);
  }
  return `
    <div class="topology-policy-overlay" data-topology-client-detail-overlay>
      <div class="topology-policy-modal client-detail-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(t("topologyClientDetailTitle", { name: displayName }))}">
        <div class="topology-card-head">
          <strong>${escapeHtml(t("topologyClientDetailTitle", { name: displayName }))}</strong>
          <div class="client-detail-head-actions">
            ${loading}
            <button class="icon-action compact" type="button" data-topology-client-detail-refresh aria-label="${escapeHtml(t("topologyRefresh"))}" title="${escapeHtml(t("topologyRefresh"))}">↻</button>
            <button class="icon-action compact" type="button" data-topology-client-detail-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
          </div>
        </div>
        <div class="client-detail-body">${body}</div>
      </div>
    </div>
  `;
}

export function renderOpenclawConfigBody(data, entry) {
  const defaults = data?.agents?.defaults || {};
  const providers = data?.models?.providers || {};
  const gateway = data?.gateway || {};
  const session = data?.session || {};
  const fetchedAt = entry?.fetchedAt ? new Date(entry.fetchedAt * 1000).toLocaleString() : "";
  const tx = (key, vars) => escapeHtml(t(key, vars));
  const providersHtml = Object.entries(providers).map(([id, prov]) => {
    const models = Array.isArray(prov?.models) ? prov.models : [];
    const modelRows = models.map((model) => `
      <div class="client-detail-subrow">
        <span><b>${escapeHtml(model.id || "?")}</b>${model.name ? ` · ${escapeHtml(model.name)}` : ""}</span>
        <span class="topology-muted">ctx ${escapeHtml(String(model.contextWindow || model.contextTokens || "?"))} · max ${escapeHtml(String(model.maxTokens || "?"))}${Array.isArray(model.input) ? ` · ${escapeHtml(model.input.join("/"))}` : ""}</span>
      </div>
    `).join("");
    return `
      <div class="client-detail-row">
        <div class="client-detail-row-head"><strong>${escapeHtml(id)}</strong><span class="topology-muted">timeout ${escapeHtml(String(prov.timeoutSeconds ?? "?"))}s · ${escapeHtml(String(prov.api || "?"))}</span></div>
        <code>${escapeHtml(prov.baseUrl || "?")}</code>
        ${modelRows}
      </div>
    `;
  }).join("") || `<div class="topology-muted">${t("noProvidersConfigured")}</div>`;
  const fallbacks = Array.isArray(defaults?.model?.fallbacks) ? defaults.model.fallbacks : [];
  return `
    <section class="client-detail-section">
      <h3>${tx("topologyClientDetailAgentDefaults")}</h3>
      <div class="client-detail-grid">
        <div><span class="topology-muted">${tx("topologyResponseTimeout")}</span><strong>${escapeHtml(String(defaults.timeoutSeconds ?? "?"))} s</strong></div>
        <div><span class="topology-muted">${tx("topologyContextTokens")}</span><strong>${escapeHtml(String(defaults.contextTokens ?? "?"))}</strong></div>
        <div><span class="topology-muted">${tx("topologyThinking")}</span><strong>${escapeHtml(String(defaults.thinkingDefault ?? "?"))}</strong></div>
        <div><span class="topology-muted">${tx("topologyImageModel")}</span><strong title="${escapeHtml(String(defaults.imageModel ?? ""))}">${escapeHtml(String(defaults.imageModel ?? "—"))}</strong></div>
      </div>
      <div class="client-detail-models">
        <div><span class="topology-muted">${tx("topologyPrimaryModel")}</span> <code>${escapeHtml(String(defaults?.model?.primary ?? "—"))}</code></div>
        ${fallbacks.map((fb) => `<div><span class="topology-muted">${tx("topologyFallbackModel")}</span> <code>${escapeHtml(String(fb))}</code></div>`).join("")}
      </div>
    </section>
    <section class="client-detail-section">
      <h3>${tx("topologyClientDetailProviders")}</h3>
      ${providersHtml}
    </section>
    <section class="client-detail-section">
      <h3>${tx("topologyClientDetailGateway")}</h3>
      <div class="client-detail-grid">
        <div><span class="topology-muted">${tx("topologyGatewayPort")}</span><strong>${escapeHtml(String(gateway.port ?? "?"))}</strong></div>
        <div><span class="topology-muted">${tx("topologyBind")}</span><strong>${escapeHtml(String(gateway.bind ?? "?"))}</strong></div>
        <div><span class="topology-muted">${tx("topologyAuth")}</span><strong>${escapeHtml(String(gateway?.auth?.mode ?? "?"))}</strong></div>
        <div><span class="topology-muted">${tx("topologyIdleReset")}</span><strong>${escapeHtml(String(session?.reset?.idleMinutes ?? "?"))}</strong></div>
      </div>
    </section>
    ${fetchedAt ? `<div class="client-detail-footer topology-muted">${t("topologyDetailFetched", { time: escapeHtml(fetchedAt) })}</div>` : ""}
  `;
}

export function openClientDetail(clientId, agentName) {
  topologyClientDetailFor = clientId || "";
  topologyClientDetailAgentName = agentName || "";
  topologyClientDetailLoading = false;
  renderTopology();
}

export function closeClientDetail() {
  topologyClientDetailFor = "";
  topologyClientDetailAgentName = "";
  topologyClientDetailLoading = false;
  renderTopology();
}

export async function refreshClientDetail() {
  if (!topologyClientDetailFor) return;
  topologyClientDetailLoading = true;
  renderTopology();
  try {
    const data = await api(`/api/openclaw-config?client=${encodeURIComponent(topologyClientDetailFor)}&refresh=1`);
    setTopology(topology || {});
    topology.openclawConfigs = { ...(topology.openclawConfigs || {}), [topologyClientDetailFor]: data };
  } catch (err) {
    toast(err.message);
  }
  topologyClientDetailLoading = false;
  renderTopology();
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

export function renderTopologyGpuModal() {
  if (!topologyGpuModalOpen) return "";
  const logs = state?.logs || "";
  const summary = {
    service: state?.service,
    llamaCpp: state?.llamaCpp,
    runtime: {
      models: state?.runtime?.models,
      props: {
        n_ctx: state?.runtime?.props?.default_generation_settings?.n_ctx,
        modalities: state?.runtime?.props?.modalities,
        model_path: state?.runtime?.props?.model_path,
      },
      metrics: state?.runtime?.metrics,
    },
    cpu: state?.cpu,
    gpu: state?.gpu,
    memory: state?.memory,
  };
  return `
    <div class="topology-policy-overlay" data-topology-gpu-modal-overlay>
      <div class="topology-policy-modal topology-gpu-modal" role="dialog" aria-modal="true" aria-label="GPU Logs &amp; Raw API">
        <div class="topology-card-head">
          <strong>${escapeHtml(t("gpuLogsHeading"))}</strong>
          <button class="icon-action compact" type="button" data-topology-gpu-modal-close aria-label="Close" title="Close">×</button>
        </div>
        <div class="topology-gpu-modal-body">
          <div class="topology-gpu-modal-section">
            <div class="topology-gpu-modal-section-head">${escapeHtml(t("logsSection"))}</div>
            <pre class="topology-gpu-modal-pre">${escapeHtml(logs || "(no logs)")}</pre>
          </div>
          <div class="topology-gpu-modal-section">
            <div class="topology-gpu-modal-section-head">${escapeHtml(t("rawApiSection"))}</div>
            <pre class="topology-gpu-modal-pre">${escapeHtml(JSON.stringify(summary, null, 2))}</pre>
          </div>
        </div>
      </div>
    </div>
  `;
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

// Proxy Ports registry — the place to manage who owns which port, which router
// it feeds, and to delete ports of permanently-removed agents (manual, user-decided).
// Ports persist independently of whether the agent is currently online.
export function renderTopologyProxySummaryModal() {
  if (!topologyProxySummaryOpen) return "";
  const proxies = (topology?.proxies || []).slice().sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
  const routers = topology?.routers || [];
  const onlineClientIds = new Set((topology?.clients || []).map((c) => c.id));
  const rows = proxies.map((p) => {
    // Bridge ports are not agents: no owner, no router — a cloud pin instead.
    const isBridge = p.kind === "service";
    const owner = isBridge ? null : topologyProxyOwner(p.id);
    // Orphan = no LIVE agent uses this port: either no assignment at all, or the
    // assigned agent is no longer reported by the host (dead agent). Its settings
    // are kept; this is where you decide to delete it.
    const orphan = !isBridge && !(owner && owner.live);
    const role = p.role || (String(p.label || "").match(/(primary|fallback)$/i)?.[1]?.toLowerCase()) || "";
    const ownerName = owner?.title || p.label || "—";
    const routerOptions = routers.length
      ? routers.map((s) => `<option value="${escapeHtml(s.id)}"${s.id === (p.routerId || "router:default") ? " selected" : ""}>${escapeHtml(s.name || s.id)}</option>`).join("")
      : `<option value="router:default">Default</option>`;
    const bridgeModel = isBridge
      ? ((topology?.cloudProviders || []).find((b) => b.id === p.providerId)?.model || p.providerId || "cloud")
      : "";
    return `
      <div class="proxy-reg-row ${orphan ? "orphan" : ""}">
        <span class="proxy-reg-port">:${escapeHtml(p.port)}</span>
        <span class="proxy-reg-owner">${orphan ? `<span class="proxy-reg-orphan" title="${escapeHtml(t("orphanPortTitle"))}">orphan</span>` : ""}${isBridge ? `<span class="proxy-reg-bridge" title="${escapeHtml(t("cloudBridgeHint"))}">bridge</span>` : ""}<span class="proxy-reg-owner-name">${escapeHtml(ownerName)}</span></span>
        <span class="proxy-reg-role ${escapeHtml(role)}">${escapeHtml(role || "—")}</span>
        ${isBridge
          ? `<span class="proxy-reg-router proxy-reg-bridge-target" title="${escapeHtml(t("cloudBridgeHint"))}">☁ ${escapeHtml(bridgeModel)}</span>`
          : `<select class="proxy-reg-router" data-proxy-reg-router="${escapeHtml(p.id)}" title="${escapeHtml(t("tmTitleRouterFeeds"))}">${routerOptions}</select>`}
        <span class="proxy-reg-actions">
          <button class="icon-action compact" type="button" data-topology-proxy-edit="${escapeHtml(p.id)}" aria-label="${escapeHtml(t("rtTitleRenamePort"))}" title="${escapeHtml(t("rtTitleRenamePort"))}">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
          </button>
          <button class="icon-action compact danger" type="button" data-topology-proxy-delete="${escapeHtml(p.id)}" aria-label="${escapeHtml(t("rtTitleDeletePort"))}" title="${escapeHtml(t("rtTitleDeletePort"))}">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
          </button>
        </span>
      </div>`;
  }).join("") || `<div class="topology-muted">${t("cvNoProxyPorts")}</div>`;
  // Dead agents: assignment entries whose agent is no longer reported by the host
  // (left behind after a rename/removal). Listed separately so they can be deleted
  // — which removes the assignment and frees any proxy ports it still holds.
  const orphanedAgents = topology?.orphanedAgents || [];
  const orphanRows = orphanedAgents.map((o) => {
    const portsLabel = (o.ports && o.ports.length) ? o.ports.map((p) => `:${p}`).join(" ") : "—";
    return `
      <div class="proxy-reg-row orphan">
        <span class="proxy-reg-port">${escapeHtml(portsLabel)}</span>
        <span class="proxy-reg-owner"><span class="proxy-reg-orphan" title="${escapeHtml(t("deadAgentTitle"))}">dead</span><span class="proxy-reg-owner-name">${escapeHtml(o.agentId)} · ${escapeHtml(o.clientName)}</span></span>
        <span class="proxy-reg-role">—</span>
        <span></span>
        <span class="proxy-reg-actions">
          <button class="icon-action compact danger" type="button" data-orphan-agent-delete-client="${escapeHtml(o.clientId)}" data-orphan-agent-delete-id="${escapeHtml(o.agentId)}" aria-label="${escapeHtml(t("deleteDeadAgent"))}" title="${escapeHtml(t("deleteDeadAgent"))}">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>
          </button>
        </span>
      </div>`;
  }).join("");
  const orphanSection = orphanedAgents.length ? `
        <div class="topology-policy-hint proxy-reg-deadhead">${escapeHtml(t("deadAgentsHint"))}</div>
        <div class="proxy-reg-list">${orphanRows}</div>` : "";
  return `
    <div class="topology-policy-overlay" data-topology-proxy-summary-overlay>
      <div class="topology-policy-modal proxy-registry-modal" role="dialog" aria-modal="true" aria-label="Proxy ports">
        <div class="topology-card-head">
          <strong>Proxy ports</strong>
          <span class="topology-policy-head-actions">
            <button class="icon-action compact prominent" type="button" data-proxy-reg-add aria-label="Add port" title="Add a proxy port">＋</button>
            <button class="icon-action compact" type="button" data-topology-proxy-summary-close aria-label="Close" title="Close">×</button>
          </span>
        </div>
        <div class="topology-policy-hint">${escapeHtml(t("proxyPortsHint"))}</div>
        <div class="proxy-reg-head">
          <span>port</span><span>owner</span><span>role</span><span>router</span><span></span>
        </div>
        <div class="proxy-reg-list">${rows}</div>
        ${orphanSection}
      </div>
    </div>
  `;
}

export function renderTopologyAgentConfigModal() {
  if (!ui.topologyAgentConfigMode) return "";
  const client = (topology?.clients || []).find((c) => c.id === topologyAgentConfigClientId);
  const agent = (client?.agents || []).find((a) => a.id === topologyAgentConfigAgentId);
  const title = `${agent?.name || topologyAgentConfigAgentId} — .openclaw/openclaw.json`;
  const loading = topologyAgentConfigLoading ? `<span class="topology-muted">${t("loadingEllipsis")}</span>` : "";
  let body = "";
  if (topologyAgentConfigLoading) {
    body = `<div class="topology-muted">${t("loadingEllipsis")}</div>`;
  } else if (!topologyAgentConfigResult) {
    body = `<div class="topology-muted">${t("noData")}</div>`;
  } else if (!topologyAgentConfigResult.ok) {
    body = `<div class="topology-incident-line failed">${escapeHtml(topologyAgentConfigResult.error || "error")}</div>`;
  } else if (ui.topologyAgentConfigMode === "raw") {
    const json = JSON.stringify(topologyAgentConfigResult.data || {}, null, 2);
    body = `
      <div class="topology-policy-hint">${escapeHtml(topologyAgentConfigResult.path || "")}</div>
      <pre class="topology-raw-config">${escapeHtml(json)}</pre>`;
  } else {
    // "ports" mode — show providers with their baseUrls
    const providers = topologyAgentConfigResult.data?.models?.providers || {};
    const defaults = topologyAgentConfigResult.data?.agents?.defaults?.model || {};
    const primaryRef = String(defaults.primary || "");
    const fallbackRef = String((defaults.fallbacks || [])[0] || "");
    const primaryProvider = primaryRef.split("/")[0];
    const fallbackProvider = fallbackRef.split("/")[0];
    const roleOf = (id) => id === primaryProvider ? "primary" : id === fallbackProvider ? "fallback" : "";
    const rows = Object.entries(providers).map(([id, prov]) => {
      const role = roleOf(id);
      const url = String(prov?.baseUrl || "—");
      return `<div class="client-detail-row">
        <div class="client-detail-row-head">
          <strong>${escapeHtml(id)}</strong>
          ${role ? `<span class="proxy-role-label">${escapeHtml(role)}</span>` : ""}
        </div>
        <code>${escapeHtml(url)}</code>
      </div>`;
    }).join("") || `<div class="topology-muted">${t("noProviders")}</div>`;
    body = `
      <div class="topology-policy-hint">${escapeHtml(topologyAgentConfigResult.path || "")}</div>
      <div style="margin-top:8px">${rows}</div>`;
  }
  const modeBtn = (mode, label) => ui.topologyAgentConfigMode === mode
    ? `<span class="proxy-role-label">${label}</span>`
    : `<button class="mini-link" type="button" data-agent-config-mode="${escapeHtml(mode)}">${label}</button>`;
  return `
    <div class="topology-policy-overlay" data-agent-config-overlay>
      <div class="topology-policy-modal raw-config-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
        <div class="topology-card-head">
          <strong>${escapeHtml(title)}</strong>
          <div class="client-detail-head-actions">
            ${loading}
            ${modeBtn("ports", "ports")}
            ${modeBtn("raw", "{ }")}
            <button class="icon-action compact" type="button" data-agent-config-refresh title="Refresh">↻</button>
            <button class="icon-action compact" type="button" data-agent-config-close aria-label="Close" title="Close">×</button>
          </div>
        </div>
        <div class="client-detail-body">${body}</div>
      </div>
    </div>
  `;
}

export async function openAgentConfigModal(clientId, agentId, mode) {
  topologyAgentConfigClientId = clientId;
  topologyAgentConfigAgentId = agentId;
  ui.topologyAgentConfigMode = mode;
  topologyAgentConfigLoading = true;
  topologyAgentConfigResult = null;
  renderTopology();
  try {
    const res = await api(`/api/topology/agent-openclaw?client=${encodeURIComponent(clientId)}&agent=${encodeURIComponent(agentId)}`);
    topologyAgentConfigResult = res;
  } catch (err) {
    topologyAgentConfigResult = { ok: false, error: err.message };
  }
  topologyAgentConfigLoading = false;
  renderTopology();
}

export function closeAgentConfigModal() {
  ui.topologyAgentConfigMode = "";
  topologyAgentConfigResult = null;
  topologyAgentConfigLoading = false;
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
  const total = routeChanges.length + (Object.keys(policyChanges).length ? 1 : 0);
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

