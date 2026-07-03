// Usage & spend statistics modal, pricing edits, provider cost fetches.
import { renderTopologyCloudProviders } from "./cloud.js";
import { t } from "./i18n.js";
import { action } from "./polling.js";
import { topology, ui } from "./state.js";
import { renderTopology } from "./topology-render.js";
import { $, api, escapeHtml } from "./utils.js";

// (proxy squares + proxy detail popover removed — the proxy now lives on the client
// route row and is managed via the Proxy Ports registry modal.)

// Cache: accountId → { data, fetchedAt, loading }
// No TTL — data is fetched once on first render, then only on manual refresh via button.
export const subscriptionUsageCache = new Map();
// API providers: official spend via /v1/organization/costs (needs api.usage.read scope).
export const apiCostsCache = new Map();
// OpenRouter: key info + daily token limit + request rate limit.
export const openrouterLimitsCache = new Map();
export async function fetchApiCosts(accountId) {
  if (apiCostsCache.get(accountId)) return;   // fetched/in-flight — manual refresh busts it
  apiCostsCache.set(accountId, { loading: true });
  try {
    const res = await api(`/api/cloud-accounts/api-costs?id=${encodeURIComponent(accountId)}`);
    apiCostsCache.set(accountId, { data: res, fetchedAt: Date.now(), loading: false });
  } catch (e) {
    apiCostsCache.set(accountId, { data: null, error: String(e), fetchedAt: Date.now(), loading: false });
  }
  renderTopologyCloudProviders();
}
export async function fetchOpenRouterLimits(accountId) {
  const cached = openrouterLimitsCache.get(accountId);
  if (cached && !cached.error) return;  // fetched/in-flight — manual refresh busts it
  openrouterLimitsCache.set(accountId, { ...(cached || {}), loading: true });
  try {
    const res = await api(`/api/cloud-accounts/openrouter-limits?id=${encodeURIComponent(accountId)}`);
    openrouterLimitsCache.set(accountId, { data: res, fetchedAt: Date.now(), loading: false });
  } catch (e) {
    openrouterLimitsCache.set(accountId, { data: null, error: String(e), fetchedAt: Date.now(), loading: false });
  }
  renderTopologyCloudProviders();
}
// Local spend-meter: $ spent through the proxy (our token counts × pricing). One fetch
// returns every account; cached briefly.
export let proxySpendData = null, proxySpendFetchedAt = 0, proxySpendLoading = false;
export async function fetchProxySpend() {
  if (proxySpendLoading) return;
  if (proxySpendData && Date.now() - proxySpendFetchedAt < 30000) return;  // 30s TTL
  proxySpendLoading = true;
  try {
    const res = await api("/api/cloud-accounts/proxy-spend");
    proxySpendData = res.spend || {};
  } catch { proxySpendData = proxySpendData || {}; }
  proxySpendFetchedAt = Date.now();
  proxySpendLoading = false;
  renderTopologyCloudProviders();
}
export function proxySpendHtml(accountId) {
  const s = (proxySpendData || {})[accountId];
  if (!s || (!s.total && !s.requests)) return "";
  const models = (s.byModel || []).slice(0, 3)
    .map((m) => `<div class="sub-usage-row"><span class="sub-usage-label">${escapeHtml(m.model)}</span><span class="sub-usage-pct">$${Number(m.cost || 0).toFixed(3)}</span></div>`).join("");
  return `<div class="sub-usage-panel"><div class="sub-usage-credits"><span>⇄ via proxy · ${s.windowDays}d</span><strong>$${Number(s.total || 0).toFixed(2)}</strong></div>${models}<div class="sub-usage-row"><span class="muted">${s.requests} req · ${(s.promptTokens + s.completionTokens).toLocaleString()} tok</span></div></div>`;
}
// ── Usage & spend statistics modal (cloud $ spent + local tokens × manual rate) ──
export let usageStatsData = null, usageStatsLoading = false;
export let usageStatsApiPriceEdit = {};   // model -> {inputPer1M, outputPer1M} while editing
export async function fetchUsageStats() {
  usageStatsLoading = true;
  renderTopology();
  try {
    usageStatsData = await api(`/api/usage-stats?days=${ui.usageStatsDays}`);
  } catch { usageStatsData = usageStatsData || { ok: false }; }
  usageStatsLoading = false;
  ui.usageStatsRateEdit = null;  // adopt freshly returned rate
  usageStatsApiPriceEdit = {};
  renderTopology();
}
export function openUsageStatsModal() {
  ui.usageStatsModalOpen = true;
  usageStatsData = null;
  ui.usageStatsScope = "overview";
  ui.usageStatsExpanded = "";
  usageStatsApiPriceEdit = {};
  renderTopology();
  fetchUsageStats();
}
export async function saveApiPrice(model) {
  const e = usageStatsApiPriceEdit[model] || {};
  try {
    await api("/api/api-pricing", {
      method: "POST",
      body: JSON.stringify({
        model,
        inputPer1M: Number(e.inputPer1M) || 0,
        outputPer1M: Number(e.outputPer1M) || 0,
      }),
    });
  } catch {}
  delete usageStatsApiPriceEdit[model];
  await fetchUsageStats();
}
export async function saveLocalPricing() {
  const r = ui.usageStatsRateEdit || (usageStatsData && usageStatsData.rate) || {};
  try {
    await api("/api/local-pricing", {
      method: "POST",
      body: JSON.stringify({
        inputPer1M: Number(r.inputPer1M) || 0,
        outputPer1M: Number(r.outputPer1M) || 0,
      }),
    });
  } catch {}
  await fetchUsageStats();
}
// Compact money formatter: more precision for sub-dollar amounts.
export function usMoney(v) {
  const n = Number(v) || 0;
  return n > 0 && n < 1 ? n.toFixed(3) : n.toFixed(2);
}
export function usTok(n) { return (Number(n) || 0).toLocaleString(); }
// Expandable per-model table. kind: "cloud" → $ cost; "local" → would-cost.
export function usageStatsModelTable(rows, kind) {
  if (!rows || !rows.length) return `<div class="us-empty muted">${t("usageStatsNoData")}</div>`;
  return `<div class="us-table">` + rows.map((m) => {
    const key = `${kind}:${m.model}`;
    const open = ui.usageStatsExpanded === key;
    const tok = (m.promptTokens || 0) + (m.completionTokens || 0);
    const right = kind === "cloud" ? `$${usMoney(m.cost)}` : `$${usMoney(m.wouldCost)}`;
    const perReq = m.requests ? Math.round(tok / m.requests) : 0;
    // For cloud models, the expanded row lets you set the API $/1M price (override or
    // fill in a missing one — e.g. subscription-only slugs) so the estimate is meaningful.
    let priceEditor = "";
    if (open && kind === "cloud") {
      const e = usageStatsApiPriceEdit[m.model] || {};
      const pin = e.inputPer1M ?? (Number(m.priceIn) || 0);
      const pout = e.outputPer1M ?? (Number(m.priceOut) || 0);
      const hint = m.hasPrice ? "" : `<span class="us-price-hint">${t("usageStatsNoPublicPrice")}</span>`;
      priceEditor = `<div class="us-row-price" data-us-price-row>
          <span class="muted">${t("usageStatsApiPrice")}</span>
          <label>$<input type="number" min="0" step="0.01" value="${pin}" data-us-apiprice="inputPer1M" data-us-apiprice-model="${escapeHtml(m.model)}"> /1M ${t("usageStatsIn")}</label>
          <label>$<input type="number" min="0" step="0.01" value="${pout}" data-us-apiprice="outputPer1M" data-us-apiprice-model="${escapeHtml(m.model)}"> /1M ${t("usageStatsOut")}</label>
          <button class="icon-action compact" type="button" data-us-apiprice-save="${escapeHtml(m.model)}">${t("usageStatsRateSave")}</button>
          ${hint}
        </div>`;
    }
    const detail = open ? `<div class="us-row-detail">
        <span><b>${usTok(m.promptTokens)}</b> ${t("usageStatsIn")}</span>
        <span><b>${usTok(m.completionTokens)}</b> ${t("usageStatsOut")}</span>
        <span><b>${usTok(m.requests)}</b> req</span>
        <span><b>${usTok(perReq)}</b> tok/req</span>
      </div>${priceEditor}` : "";
    return `<div class="us-row${open ? " open" : ""}" data-usage-stats-model="${escapeHtml(key)}" role="button" tabindex="0">
        <span class="us-row-caret">${open ? "▾" : "▸"}</span>
        <span class="us-row-name" title="${escapeHtml(m.model)}">${escapeHtml(m.model)}</span>
        <span class="us-row-tok muted">${usTok(tok)} tok</span>
        <span class="us-row-val">${right}</span>
      </div>${detail}`;
  }).join("") + `</div>`;
}
export function usageStatsScopeChips(s) {
  const accts = Object.values((s.cloud && s.cloud.byAccount) || {});
  const chips = [["overview", `📊 ${t("usageStatsScopeOverview")}`]];
  accts.forEach((a) => chips.push([a.id, `☁ ${a.name || a.id}`]));
  chips.push(["local", `💻 ${t("usageStatsScopeLocal")}`]);
  return `<div class="usage-stats-scopes">` + chips.map(([k, label]) =>
    `<button class="usage-stats-scope${ui.usageStatsScope === k ? " active" : ""}" type="button" data-usage-stats-scope="${escapeHtml(k)}">${escapeHtml(label)}</button>`
  ).join("") + `</div>`;
}
export function usageStatsOverview(s) {
  const c = s.cloud || {}, l = s.local || {};
  const cloudTok = (c.promptTokens || 0) + (c.completionTokens || 0);
  const localTok = (l.promptTokens || 0) + (l.completionTokens || 0);
  const cloudMini = (c.byModel || []).slice(0, 3).map((m) =>
    `<div class="us-mini-row"><span>${escapeHtml(m.model)}</span><span>$${usMoney(m.cost)}</span></div>`).join("")
    || `<div class="us-mini-row muted"><span>${t("usageStatsNoData")}</span></div>`;
  const localMini = (l.byModel || []).slice(0, 3).map((m) =>
    `<div class="us-mini-row"><span>${escapeHtml(m.model)}</span><span>${usTok((m.promptTokens || 0) + (m.completionTokens || 0))} tok</span></div>`).join("")
    || `<div class="us-mini-row muted"><span>${t("usageStatsNoData")}</span></div>`;
  return `<div class="us-overview">
    <div class="us-card us-card-cloud">
      <div class="us-card-label">${t("usageStatsCloudHead")}</div>
      <div class="us-bignum">$${usMoney(c.total)}</div>
      <div class="us-card-sub muted">${usTok(c.requests)} req · ${usTok(cloudTok)} tok</div>
      <div class="us-mini">${cloudMini}</div>
    </div>
    <div class="us-card us-card-local">
      <div class="us-card-label">${t("usageStatsLocalHead")}</div>
      <div class="us-bignum">${usTok(localTok)} <span class="us-bignum-unit">tok</span></div>
      <div class="us-card-sub muted">≈ $${usMoney(l.wouldCost)} ${t("usageStatsInCloud")} · ${usTok(l.requests)} req</div>
      <div class="us-mini">${localMini}</div>
    </div>
  </div>`;
}
export function usageStatsAccountDetail(s, acctId) {
  const a = ((s.cloud && s.cloud.byAccount) || {})[acctId];
  if (!a) return usageStatsOverview(s);
  const tok = (a.promptTokens || 0) + (a.completionTokens || 0);
  // Subscriptions (ChatGPT Plus) are flat-rate — the $ figure is a hypothetical
  // "what it would cost at API prices", not actual billing. Label it as such.
  const bignum = a.subscription ? `≈ $${usMoney(a.total)}` : `$${usMoney(a.total)}`;
  const tag = a.subscription
    ? `<div class="us-detail-tag">${t("usageStatsSubscriptionNote")}</div>` : "";
  return `<div class="us-detail">
    <div class="us-detail-head">
      <div class="us-detail-title">☁ ${escapeHtml(a.name || a.id)}</div>
      <div class="us-bignum">${bignum}</div>
    </div>
    ${tag}
    <div class="us-detail-sub muted">${usTok(a.requests)} req · ${usTok(tok)} tok (${usTok(a.promptTokens)} ${t("usageStatsIn")} / ${usTok(a.completionTokens)} ${t("usageStatsOut")})</div>
    ${usageStatsModelTable(a.byModel, "cloud")}
  </div>`;
}
export function usageStatsLocalDetail(s) {
  const l = s.local || {};
  const tok = (l.promptTokens || 0) + (l.completionTokens || 0);
  const rate = ui.usageStatsRateEdit || s.rate || {};
  return `<div class="us-detail">
    <div class="us-detail-head">
      <div class="us-detail-title">💻 ${t("usageStatsLocalHead")}</div>
      <div class="us-bignum">${usTok(tok)} <span class="us-bignum-unit">tok</span></div>
    </div>
    <div class="us-detail-sub muted">${usTok(l.requests)} req · ${t("usageStatsWouldCost")}: <b>$${usMoney(l.wouldCost)}</b></div>
    <div class="usage-stats-rate">
      <span class="muted">${t("usageStatsRateLabel")}</span>
      <label>$<input type="number" min="0" step="0.01" value="${Number(rate.inputPer1M) || 0}" data-usage-stats-rate="inputPer1M"> /1M in</label>
      <label>$<input type="number" min="0" step="0.01" value="${Number(rate.outputPer1M) || 0}" data-usage-stats-rate="outputPer1M"> /1M out</label>
      <button class="icon-action compact" type="button" data-usage-stats-rate-save>${t("usageStatsRateSave")}</button>
    </div>
    ${usageStatsModelTable(l.byModel, "local")}
  </div>`;
}
export function renderUsageStatsModal() {
  if (!ui.usageStatsModalOpen) return "";
  const periods = [[1, "day"], [7, "week"], [30, "month"]];
  const periodBtns = periods.map(([d, key]) =>
    `<button class="usage-stats-period${ui.usageStatsDays === d ? " active" : ""}" type="button" data-usage-stats-days="${d}">${t("usageStatsPeriod_" + key)}</button>`
  ).join("");
  const s = usageStatsData;
  let chipsHtml = "", bodyHtml;
  if (usageStatsLoading && !s) {
    bodyHtml = `<div class="us-empty muted">${t("usageStatsLoading")}</div>`;
  } else if (!s || !s.ok) {
    bodyHtml = `<div class="us-empty muted">${escapeHtml((s && s.error) || t("usageStatsUnavailable"))}</div>`;
  } else {
    chipsHtml = usageStatsScopeChips(s);
    const accounts = (s.cloud && s.cloud.byAccount) || {};
    if (ui.usageStatsScope === "overview") bodyHtml = usageStatsOverview(s);
    else if (ui.usageStatsScope === "local") bodyHtml = usageStatsLocalDetail(s);
    else if (accounts[ui.usageStatsScope]) bodyHtml = usageStatsAccountDetail(s, ui.usageStatsScope);
    else bodyHtml = usageStatsOverview(s);  // stale scope → fall back
  }
  return `
    <div class="topology-policy-overlay" data-usage-stats-overlay>
      <div class="topology-policy-modal usage-stats-modal" role="dialog" aria-modal="true" aria-label="${t("usageStatsTitle")}">
        <div class="topology-card-head">
          <strong>📊 ${t("usageStatsTitle")}</strong>
          <button class="icon-action compact" type="button" data-usage-stats-close aria-label="Close" title="Close">×</button>
        </div>
        <div class="usage-stats-periods">${periodBtns}</div>
        ${chipsHtml}
        <div class="usage-stats-body">${bodyHtml}</div>
      </div>
    </div>
  `;
}
export function apiCostsHtml(accountId) {
  const c = apiCostsCache.get(accountId);
  const refresh = `<button class="sub-usage-refresh icon-action compact${c?.loading ? " spinning" : ""}" type="button" data-api-costs-refresh="${escapeHtml(accountId)}" title="Refresh spend" ${c?.loading ? "disabled" : ""}>↻</button>`;
  if (!c || c.loading) return `<div class="sub-usage-panel"><div class="sub-usage-head">${refresh}</div><div class="sub-usage-row"><span class="muted">loading spend…</span></div></div>`;
  const d = c.data;
  if (!d || !d.ok) return `<div class="sub-usage-panel"><div class="sub-usage-head">${refresh}</div><div class="sub-usage-row"><span class="muted">spend: ${escapeHtml(d?.error || c.error || "unavailable")}</span></div></div>`;
  return `<div class="sub-usage-panel"><div class="sub-usage-head">${refresh}</div><div class="sub-usage-credits"><span>Spent · last ${d.windowDays}d</span><strong>$${Number(d.total || 0).toFixed(2)}</strong></div></div>`;
}

export function openRouterLimitsHtml(accountId) {
  const c = openrouterLimitsCache.get(accountId);
  const isLoading = c?.loading;
  const refreshBtn = `<button class="sub-usage-refresh icon-action compact${isLoading ? " spinning" : ""}" type="button" data-or-limits-refresh="${escapeHtml(accountId)}" title="Refresh limits" ${isLoading ? "disabled" : ""}>↻</button>`;
  if (!c || (c.loading && !c.data)) return `<div class="sub-usage-panel"><div class="sub-usage-head">${refreshBtn}</div><div class="sub-usage-row"><span class="muted">loading limits…</span></div></div>`;
  const d = c.data;
  if (!d?.ok) {
    const isAuth = d?.authError;
    const errHtml = isAuth
      ? `<span class="or-key-invalid">⚠ key invalid</span>`
      : `<span class="muted">${escapeHtml(d?.error || c.error || "unavailable")}</span>`;
    return `<div class="sub-usage-panel"><div class="sub-usage-head">${refreshBtn}</div><div class="sub-usage-row">${errHtml}</div></div>`;
  }
  let rows = "";
  if (d.limit != null) {
    const used = d.usage || 0;
    const remainPct = Math.max(0, Math.min(100, Math.round((1 - used / d.limit) * 100)));
    const color = remainPct > 50 ? "#22c55e" : remainPct > 15 ? "#f59e0b" : "#ef4444";
    rows += `<div class="sub-usage-row">
      <div class="sub-usage-meta"><span class="sub-usage-label">Daily tokens</span><span class="sub-usage-pct" style="color:${color}">${remainPct}% left</span></div>
      <div class="sub-usage-bar"><i style="width:${remainPct}%;background:${color}"></i></div>
      <span class="sub-usage-resets">${(used || 0).toLocaleString()} / ${d.limit.toLocaleString()} used</span>
    </div>`;
  } else if (d.usage != null) {
    rows += `<div class="sub-usage-row"><div class="sub-usage-meta"><span class="sub-usage-label">Used today</span><span class="sub-usage-pct">${d.usage.toLocaleString()} tok</span></div></div>`;
  }
  if (d.rateLimit?.requests && d.rateLimit?.interval) {
    rows += `<div class="sub-usage-row"><span class="muted">${d.rateLimit.requests} req / ${d.rateLimit.interval}</span></div>`;
  }
  const tierBadge = d.isFreeTier ? `<span class="sub-usage-label" style="color:#4ade80;margin-left:4px">free tier</span>` : "";
  return `<div class="sub-usage-panel"><div class="sub-usage-head">${refreshBtn}${tierBadge}</div>${rows}</div>`;
}

export async function fetchSubscriptionUsage(accountId) {
  const cached = subscriptionUsageCache.get(accountId);
  if (cached) return;  // already fetched (or in flight) — only manual refresh busts this
  if (cached?.loading) return;
  subscriptionUsageCache.set(accountId, { data: cached?.data || null, fetchedAt: cached?.fetchedAt || 0, loading: true });
  try {
    const res = await api(`/api/cloud-accounts/subscription-usage?id=${encodeURIComponent(accountId)}`);
    subscriptionUsageCache.set(accountId, { data: res, fetchedAt: Date.now(), loading: false });
  } catch (e) {
    subscriptionUsageCache.set(accountId, { data: null, fetchedAt: Date.now(), loading: false, error: String(e) });
  }
  renderTopologyCloudProviders();
}

export function subscriptionUsageHtml(accountId) {
  const cached = subscriptionUsageCache.get(accountId);
  // Keep showing old data while a background refresh is in progress — avoids card collapsing
  if (!cached || !cached.data?.ok) return "";
  const { limits = [], credits } = cached.data;
  if (!limits.length && credits == null) return "";
  const rows = limits.map((lim) => {
    const pct = Math.max(0, Math.min(100, lim.remainingPct ?? 0));
    const color = pct > 50 ? "#22c55e" : pct > 15 ? "#f59e0b" : "#ef4444";
    const resetsLine = lim.resetsAt
      ? `<span class="sub-usage-resets">${escapeHtml(formatSubUsageReset(lim.resetsAt))}</span>` : "";
    return `
      <div class="sub-usage-row">
        <div class="sub-usage-meta">
          <span class="sub-usage-label">${escapeHtml(lim.label)}</span>
          <span class="sub-usage-pct" style="color:${color}">${pct}%</span>
        </div>
        <div class="sub-usage-bar"><i style="width:${pct}%;background:${color}"></i></div>
        ${resetsLine}
      </div>`;
  }).join("");
  const creditsHtml = credits != null
    ? `<div class="sub-usage-credits"><span>Credits</span><strong>${credits}</strong></div>` : "";
  const isLoading = cached?.loading;
  const refreshBtn = `<button class="sub-usage-refresh icon-action compact${isLoading ? " spinning" : ""}" type="button" data-usage-refresh="${escapeHtml(accountId)}" title="Refresh limits" aria-label="Refresh limits" ${isLoading ? "disabled" : ""}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 4v6h6"/><path d="M23 20v-6h-6"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg></button>`;
  return `<div class="sub-usage-panel"><div class="sub-usage-head">${refreshBtn}</div>${rows}${creditsHtml}</div>`;
}

export function formatSubUsageReset(resetsAt) {
  try {
    const d = new Date(resetsAt);
    if (isNaN(d)) return resetsAt;
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return `resets ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    return `resets ${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  } catch { return resetsAt; }
}

