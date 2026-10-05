// Usage & spend statistics modal, pricing edits, provider cost fetches.
import { renderTopologyCloudProviders } from "./cloud.js";
import { t } from "./i18n.js";
import { topology, ui } from "./state.js";
import { renderTopology } from "./topology-render.js";
import { $, api, escapeHtml, toast } from "./utils.js";

// (proxy squares + proxy detail popover removed — the proxy now lives on the client
// route row and is managed via the Proxy Ports registry modal.)

// Cache: accountId → { data, fetchedAt, loading, error }
// Good data has no TTL — it is fetched once on first render, then only on manual
// refresh via the button. A FAILURE is different: it must expire, or the panel it
// feeds is gone for the life of the tab.
export const subscriptionUsageCache = new Map();
// How long a failed fetch is remembered before another attempt is allowed. These
// fetchers run from the RENDER path, so retrying with no cooldown would turn a
// down endpoint into a request per repaint.
const FETCH_RETRY_MS = 60000;

/** Should we (re)fetch for this account? Skip while one is in flight and while we
 *  hold good data; retry a failure once the cooldown has passed.
 *
 *  The bug this replaces: `if (cached) return` treated a stored FAILURE as a
 *  completed fetch. One transient error — a controller restart, a dropped
 *  connection — poisoned the cache permanently, and since the renderer draws
 *  nothing when data is missing, a whole panel vanished from the card with no
 *  message and no way back short of reloading the page. */
function _shouldFetch(cache, accountId) {
  const c = cache.get(accountId);
  if (!c) return true;
  if (c.loading) return false;
  if (c.data) return false;                       // have it; manual refresh busts
  return Date.now() - (c.fetchedAt || 0) >= FETCH_RETRY_MS;
}
// API providers: official spend via /v1/organization/costs (needs api.usage.read scope).
export const apiCostsCache = new Map();
// OpenRouter: key info + daily token limit + request rate limit.
export const openrouterLimitsCache = new Map();
export async function fetchApiCosts(accountId) {
  if (!_shouldFetch(apiCostsCache, accountId)) return;
  apiCostsCache.set(accountId, { ...(apiCostsCache.get(accountId) || {}), loading: true });
  try {
    const res = await api(`/api/cloud-accounts/api-costs?id=${encodeURIComponent(accountId)}`);
    apiCostsCache.set(accountId, { data: res, fetchedAt: Date.now(), loading: false });
  } catch (e) {
    apiCostsCache.set(accountId, { data: null, error: String(e), fetchedAt: Date.now(), loading: false });
  }
  renderTopologyCloudProviders();
}
export async function fetchOpenRouterLimits(accountId) {
  // Already retried on error — but with no cooldown, so a persistently dead
  // endpoint got a request per repaint. Same guard as its siblings now.
  if (!_shouldFetch(openrouterLimitsCache, accountId)) return;
  openrouterLimitsCache.set(accountId, { ...(openrouterLimitsCache.get(accountId) || {}), loading: true });
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
// Data-plane cloud failures (routed traffic that came back 4xx/5xx or died),
// aggregated per account over 24h — the runtime twin of the API-issues panel.
export let upstreamErrData = null, upstreamErrFetchedAt = 0, upstreamErrLoading = false;
export async function fetchUpstreamErrors() {
  if (upstreamErrLoading) return;
  if (upstreamErrData && Date.now() - upstreamErrFetchedAt < 60000) return;  // 60s TTL
  upstreamErrLoading = true;
  try {
    const res = await api("/api/cloud-upstream-errors");
    upstreamErrData = res.byAccount || {};
  } catch { upstreamErrData = upstreamErrData || {}; }
  upstreamErrFetchedAt = Date.now();
  upstreamErrLoading = false;
  renderTopologyCloudProviders();
}
export function upstreamErrorsHtml(accountId) {
  const rows = (upstreamErrData || {})[accountId] || [];
  if (!rows.length) return "";
  const hhmm = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  // Every row on this card is over as often as not, so it has to say WHEN and
  // WHETHER, not just how many. A single stamp next to a 24h count read as
  // "25 failures at 15:34" when it was 25 spread across two and a half hours.
  const recovered = rows.every((r) => (r.okSince || 0) > 0);
  const items = rows.map((r) => {
    const when = r.lastAt
      ? (r.firstAt && r.lastAt - r.firstAt > 90 ? `${hhmm(r.firstAt)}–${hhmm(r.lastAt)}` : hhmm(r.lastAt))
      : "";
    const reason = (r.error || r.kind || "").slice(0, 60);
    return `<div class="cloud-api-issue${(r.okSince || 0) > 0 ? " is-resolved" : ""}">
      <span class="cloud-api-issue-name">${escapeHtml(r.model)}</span>
      <span class="cloud-api-issue-state">${escapeHtml(r.code)} ×${escapeHtml(String(r.count))}</span>
      <span class="cloud-api-issue-err" title="${escapeHtml(r.error || r.kind || "")}">${escapeHtml(reason)}${when ? ` · ${escapeHtml(when)}` : ""}</span>
    </div>`;
  }).join("");
  const okRow = recovered && rows[0]?.okSince
    ? `<div class="cloud-api-issue is-resolved-note">✓ ${escapeHtml(t("cloudUpstreamRecovered", { n: rows[0].okSince }))}</div>`
    : "";
  return `<div class="cloud-api-issues${recovered ? " all-resolved" : ""}"><div class="cloud-api-issues-title">⚠ ${escapeHtml(t("cloudUpstreamErrorsTitle"))}</div>${items}${okRow}</div>`;
}

// A count said short and the same in every language: 359627986 → "360M".
export function compactCount(n) {
  const v = Number(n) || 0;
  const [div, unit] = v >= 1e9 ? [1e9, "B"] : v >= 1e6 ? [1e6, "M"] : v >= 1e3 ? [1e3, "K"] : [1, ""];
  if (!unit) return String(Math.round(v));
  const short = v / div;
  return `${short >= 100 ? Math.round(short) : Number(short.toFixed(1))}${unit}`;
}

// What the proxy's traffic to this account would cost at API prices over the
// window — one line, the models behind it on a click. It stood as a block of
// rows under a bare "$698.73" (2026-09-27, the operator: "it confuses"); for a
// subscription the figure is not a bill, and the line says whose price it is.
// "30 days via the caravan": one line, the total. Each model's share stands
// on its own row in the models list (cloud-models.js, the operator's ask of
// 2026-09-27 — the breakdown here repeated the rows below it). On a
// subscription the line says whose price it is: the subscription covers it.
export function spendCost(s) { return `$${Math.round(Number(s?.total) || 0).toLocaleString("en-US")}`; }

export function proxySpendHtml(accountId, { subscription = false } = {}) {
  const s = (proxySpendData || {})[accountId];
  if (!s || (!s.total && !s.requests)) return "";
  const tokens = (Number(s.promptTokens) || 0) + (Number(s.completionTokens) || 0);
  const title = [t("spendEstimateTitle"), subscription ? t("spendSubscriptionNote") : ""].filter(Boolean).join(" ");
  return `<div class="sub-usage-panel spend-panel"><div class="spend-line" title="${escapeHtml(title)}">`
    + `<span class="spend-line-what">⇄ ${escapeHtml(t("spendWindow", { days: String(s.windowDays || 30) }))}</span>`
    + `<span class="spend-line-count">${escapeHtml(t("spendReqTok", { req: compactCount(s.requests), tok: compactCount(tokens) }))}</span>`
    + `<strong class="spend-line-cost">${escapeHtml(t("spendAtApiPrices", { cost: spendCost(s) }))}</strong>`
    + `</div></div>`;
}

// The account's 30-day spend record, or null — what the models' rows read.
export function proxySpendOf(accountId) {
  return (proxySpendData || {})[accountId] || null;
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
  const refresh = `<button class="sub-usage-refresh icon-action compact${c?.loading ? " spinning" : ""}" type="button" data-api-costs-refresh="${escapeHtml(accountId)}" title="${escapeHtml(t("usTitleRefreshSpend"))}" ${c?.loading ? "disabled" : ""}>↻</button>`;
  if (!c || c.loading) return `<div class="sub-usage-panel"><div class="sub-usage-head">${refresh}</div><div class="sub-usage-row"><span class="muted">${t("usLoadingSpend")}</span></div></div>`;
  const d = c.data;
  if (!d || !d.ok) return `<div class="sub-usage-panel"><div class="sub-usage-head">${refresh}</div><div class="sub-usage-row"><span class="muted">spend: ${escapeHtml(d?.error || c.error || "unavailable")}</span></div></div>`;
  return `<div class="sub-usage-panel"><div class="sub-usage-head">${refresh}</div><div class="sub-usage-credits"><span>Spent · last ${d.windowDays}d</span><strong>$${Number(d.total || 0).toFixed(2)}</strong></div></div>`;
}

export function openRouterLimitsHtml(accountId) {
  const c = openrouterLimitsCache.get(accountId);
  const isLoading = c?.loading;
  const refreshBtn = `<button class="sub-usage-refresh icon-action compact${isLoading ? " spinning" : ""}" type="button" data-or-limits-refresh="${escapeHtml(accountId)}" title="${escapeHtml(t("usTitleRefreshLimits"))}" ${isLoading ? "disabled" : ""}>↻</button>`;
  if (!c || (c.loading && !c.data)) return `<div class="sub-usage-panel"><div class="sub-usage-head">${refreshBtn}</div><div class="sub-usage-row"><span class="muted">${t("usLoadingLimits")}</span></div></div>`;
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
  const tierBadge = d.isFreeTier ? `<span class="sub-usage-label" style="color:#4ade80;margin-left:4px">${t("usFreeTier")}</span>` : "";
  return `<div class="sub-usage-panel"><div class="sub-usage-head">${refreshBtn}${tierBadge}</div>${rows}</div>`;
}

export async function fetchSubscriptionUsage(accountId) {
  if (!_shouldFetch(subscriptionUsageCache, accountId)) return;
  const cached = subscriptionUsageCache.get(accountId);
  subscriptionUsageCache.set(accountId, { data: cached?.data || null, fetchedAt: cached?.fetchedAt || 0, loading: true });
  try {
    const res = await api(`/api/cloud-accounts/subscription-usage?id=${encodeURIComponent(accountId)}`);
    subscriptionUsageCache.set(accountId, { data: res, fetchedAt: Date.now(), loading: false });
  } catch (e) {
    subscriptionUsageCache.set(accountId, { data: null, fetchedAt: Date.now(), loading: false, error: String(e) });
  }
  renderTopologyCloudProviders();
}

export function subscriptionUsageHtml(accountId, { refresh = true } = {}) {
  const cached = subscriptionUsageCache.get(accountId);
  // Keep showing old data while a background refresh is in progress — avoids card collapsing
  if (!cached) return "";
  // A failed read is not "no subscription". Silently rendering nothing is how a
  // whole limit bar disappeared off the card and stayed gone with no clue why —
  // say the read failed and that a retry is coming.
  if (!cached.data?.ok) {
    if (!cached.error) return "";
    return `<div class="sub-usage-panel sub-usage-failed" title="${escapeHtml(cached.error)}">`
      + `<div class="sub-usage-row"><span class="muted">⚠ ${escapeHtml(t("subUsageUnavailable"))}</span></div></div>`;
  }
  const { limits = [], credits } = cached.data;
  if (!limits.length && credits == null) return "";
  const rows = limits.map((lim) => subscriptionLimitRowHtml(accountId, lim, cached.data)).join("");
  const creditsHtml = credits != null
    ? `<div class="sub-usage-credits"><span>${t("usCredits")}</span><strong>${credits}</strong></div>` : "";
  // A card that keeps the refresh button elsewhere (a pool rung puts it in its head) asks for none here.
  const head = refresh ? `<div class="sub-usage-head">${subscriptionRefreshHtml(accountId)}</div>` : "";
  return `<div class="sub-usage-panel">${subscriptionBannerHtml(cached.data)}${head}${rows}${creditsHtml}</div>`;
}

/** The button that re-reads an account's limits, spinning while the read is under way. It has
 *  its own function so that a card can put it where it wants: in the head of the limit panel
 *  by default, in the head of a pool rung. Nothing has been read — nothing to read again. */
export function subscriptionRefreshHtml(accountId) {
  const cached = subscriptionUsageCache.get(accountId);
  if (!cached || (!cached.data?.ok && !cached.error)) return "";
  const isLoading = cached.loading;
  return `<button class="sub-usage-refresh icon-action compact${isLoading ? " spinning" : ""}" type="button" data-usage-refresh="${escapeHtml(accountId)}" title="${escapeHtml(t("usTitleRereadLimits"))}" aria-label="${escapeHtml(t("usTitleRereadLimits"))}" ${isLoading ? "disabled" : ""}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 4v6h6"/><path d="M23 20v-6h-6"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg></button>`;
}

/** One limit bar of a subscription, with the operator's reserve on it.
 *
 *  The reserve is the share of the window the operator keeps for themselves:
 *  once the window is down to it, the proxy answers requests to the account
 *  itself (caravan/common/usage_reserve.py). The slider lies over the bar at the
 *  reserve's mark, the kept share is hatched, and the mark is named beside the
 *  label. A window the reading does not name by length gets no slider: the
 *  proxy knows windows by length, and a reserve on an unnamed one would be a
 *  setting that does nothing. Neither without the server's ceiling — the
 *  slider's range is the server's rule, not a copy of it. The slider spans
 *  that ceiling's share of the bar, so its handle stands where the hatching
 *  ends: stretched over the whole bar, a 20% reserve sat at 22%. */
export function subscriptionLimitRowHtml(accountId, lim, data) {
  const pct = Math.max(0, Math.min(100, lim.remainingPct ?? 0));
  const color = pct > 50 ? "#22c55e" : pct > 15 ? "#f59e0b" : "#ef4444";
  const resetsLine = lim.resetsAt
    ? `<span class="sub-usage-resets">${escapeHtml(formatSubUsageReset(lim.resetsAt))}</span>` : "";
  const seconds = Number(lim.windowSeconds || 0);
  const max = Number(data?.reserveMax || 0);
  const settable = seconds > 0 && max > 0;
  const reserve = settable ? Math.max(0, Math.min(max, Number((data?.reserve || {})[String(seconds)] || 0))) : 0;
  const mark = settable
    ? `<span class="sub-usage-reserve-mark"${reserve ? "" : " hidden"}>${escapeHtml(t("usReserveMark", { pct: String(reserve) }))}</span>` : "";
  const zone = settable ? `<b class="sub-usage-reserve-zone" style="width:${reserve}%"></b>` : "";
  const slider = settable
    ? `<input class="sub-usage-reserve${reserve ? "" : " is-off"}" type="range" min="0" max="${max}" step="1" value="${reserve}"`
      + ` style="width:${max}%" data-usage-reserve="${escapeHtml(accountId)}" data-window-seconds="${seconds}" data-t="usage-reserve"`
      + ` aria-label="${escapeHtml(t("usReserveHandle"))}" title="${escapeHtml(t("usReserveHandle"))}">` : "";
  return `
      <div class="sub-usage-row">
        <div class="sub-usage-meta">
          <span class="sub-usage-label">${escapeHtml(lim.label)}</span>
          ${mark}
          <span class="sub-usage-pct" style="color:${color}">${pct}%</span>
        </div>
        <div class="sub-usage-track"><div class="sub-usage-bar"><i style="width:${pct}%;background:${color}"></i>${zone}</div>${slider}</div>
        ${resetsLine}
      </div>`;
}

/** Whether a reserve slider is being dragged: the cloud lane must not be rebuilt
 *  under the pointer, or the slider jumps back mid-gesture. Cleared on ANY
 *  release — a click that moves nothing fires no `change`, and a flag left up
 *  would keep the lane from ever rendering again. */
export const reserveDrag = {
  active: false,
  deferred: false,
  begin(onEnd) {
    this.active = true;
    const end = () => {
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      this.active = false;
      if (this.deferred) {
        this.deferred = false;
        onEnd();
      }
    };
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  },
};

/** While dragging: the hatched share and its mark follow the slider, nothing is saved. */
export function previewUsageReserve(slider) {
  const pct = Number(slider.value || 0);
  const row = slider.closest(".sub-usage-row");
  const zone = row?.querySelector(".sub-usage-reserve-zone");
  const mark = row?.querySelector(".sub-usage-reserve-mark");
  if (zone) zone.style.width = `${pct}%`;
  if (mark) {
    mark.textContent = t("usReserveMark", { pct: String(pct) });
    mark.hidden = !pct;
  }
  slider.classList.toggle("is-off", !pct);
}

/** On release: save the window's reserve, then draw what the server kept.
 *  A failed save is said, and the redraw puts the slider back where the saved
 *  value is — a slider left at an unsaved mark would read as a kept reserve. */
export async function saveUsageReserve(slider) {
  const accountId = slider.dataset.usageReserve;
  try {
    const res = await api("/api/cloud-accounts/usage-reserve", { method: "POST", body: JSON.stringify({
      id: accountId, windowSeconds: Number(slider.dataset.windowSeconds), pct: Number(slider.value || 0) }) });
    const cached = subscriptionUsageCache.get(accountId);
    if (cached?.data) {
      cached.data = { ...cached.data, reserve: res.reserve, reserveKept: res.reserveKept,
                      reserveReadAt: res.reserveReadAt, reserveMax: res.reserveMax };
    }
  } catch (err) {
    toast(t("usReserveSaveFailed", { error: String(err?.message || err) }));
  }
  ui._lastCloudProvidersKey = "";   // the reserve is not part of the lane's render key
  renderTopologyCloudProviders();
}

// The moment itself, without the "resets" word: the banner says "until {moment}".
// `now` is a parameter: "today" read off the wall clock made the snapshot's
// "time only" pin fail whenever it ran a minute before midnight.
export function formatSubUsageMoment(resetsAt, now = new Date()) {
  try {
    const d = new Date(resetsAt);
    if (isNaN(d)) return resetsAt;
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  } catch { return resetsAt; }
}

export function formatSubUsageReset(resetsAt, now = new Date()) {
  const moment = formatSubUsageMoment(resetsAt, now);
  return moment === resetsAt && isNaN(new Date(resetsAt)) ? resetsAt : `resets ${moment}`;
}

// What keeps requests going — or nothing — said ABOVE the bars. A weekly bar
// at 0% beside a day of successful requests explained nothing: OpenAI's
// counter and its enforcement are two facts. `limitReached` is the provider's
// own verdict; credits and a reserve allowance (its "gpt-reserve" window) are
// the two things that carry requests past it; OpenAI's banner is quoted as it
// came, because it names the way out (a banked reset, a paid reset).
export function subscriptionBannerHtml(data) {
  if (!data || !data.ok) return "";
  const limits = data.limits || [];
  const exhausted = limits.filter((l) => Number(l.remainingPct ?? 100) <= 0 && !/reserve|base-model/i.test(String(l.name || "")));
  const reserve = limits.find((l) => /reserve|base-model/i.test(String(l.name || "")) && Number(l.remainingPct ?? 0) > 0);
  const ci = data.creditsInfo || {};
  const reset = exhausted[0]?.resetsAt ? formatSubUsageMoment(exhausted[0].resetsAt) : "";
  if (data.limitReached) {
    let keeps;
    if (ci.hasCredits) keeps = t("usBannerOnCredits", { balance: `$${data.credits ?? "?"}` });
    else if (reserve) keeps = t("usBannerOnReserve", { label: reserve.label, pct: String(reserve.remainingPct) });
    else keeps = t("usBannerNothingLeft");
    const own = data.upsell?.title || data.upsell?.description
      ? `<div class="sub-usage-banner-own">${escapeHtml([data.upsell.title, data.upsell.description].filter(Boolean).join(" — "))}</div>`
      : "";
    return `<div class="sub-usage-banner blocked" data-t="sub-usage-banner">⛔ ${escapeHtml(t("usBannerLimitReached", { reset }))}`
      + `<div class="sub-usage-banner-keeps">${escapeHtml(keeps)}</div>${own}</div>`;
  }
  // The caravan's own refusal, said as its own: the proxy keeps the operator's
  // reserve and answers the account's requests with 429 itself. After the
  // provider's verdict above — once OpenAI refuses, it is OpenAI's word.
  const kept = data.reserveKept;
  if (kept && kept.resetAt) {
    const lim = limits.find((l) => Number(l.windowSeconds || 0) === Number(kept.windowSeconds));
    const until = formatSubUsageMoment(new Date(Number(kept.resetAt) * 1000).toISOString());
    return `<div class="sub-usage-banner reserve" data-t="sub-usage-banner">🛡 ${escapeHtml(t("usBannerReserveKept", {
      label: lim ? lim.label : "", remaining: String(kept.remainingPct), reserve: String(kept.reservePct), reset: until }))}</div>`;
  }
  if (exhausted.length) {
    return `<div class="sub-usage-banner warn" data-t="sub-usage-banner">⚠ ${escapeHtml(t("usBannerCounterFull", { label: exhausted[0].label }))}</div>`;
  }
  return "";
}


// ── Re-reading a usage panel: on the ↻ button, and on coming back to the tab ──

//: The three readings a cloud card can show, each with the cache that holds it
//: and the call that fills it. A table rather than three `if`s: the button
//: handler already carried the same two lines three times, and the tab-return
//: refresher below would have made it a fourth copy.
export const USAGE_READINGS = {
  subscription: { cache: subscriptionUsageCache, fetch: fetchSubscriptionUsage },
  apiCosts: { cache: apiCostsCache, fetch: fetchApiCosts },
  openrouter: { cache: openrouterLimitsCache, fetch: fetchOpenRouterLimits },
};

//: How old a reading must be before RETURNING to the page re-reads it.
//: Not zero, and that is the whole point: a subscription reading costs a call
//: against the very budget the panel is showing, and switching tabs happens
//: dozens of times an hour. Refreshing on every return would spend the thing it
//: measures. A minute is short enough that coming back after real work always
//: re-reads, and long enough that flipping between two tabs does not.
export const RETURN_REFRESH_MIN_AGE_MS = 60000;

/** Which accounts in one cache are worth re-reading now. Pure on purpose: this
 *  is the DECISION, and it is checked by values in scripts/test_js_usage_stats.py
 *  — the same rule inside the event listener could only be checked by eye.
 *
 *  A reading already in flight is left alone; an account never read yet counts
 *  as stale, so a card that failed its first read recovers on the next return. */
export function staleReadings(cache, now, minAgeMs = RETURN_REFRESH_MIN_AGE_MS) {
  const out = [];
  for (const [accountId, entry] of cache) {
    if (entry?.loading) continue;
    if (now - (entry?.fetchedAt || 0) < minAgeMs) continue;
    out.push(accountId);
  }
  return out;
}

/** Forget one reading and ask again — exactly what the ↻ button does, because
 *  it is the same call. `_shouldFetch` refuses while good data is held, so the
 *  cache entry has to go first; that is what makes this a REFRESH and not a
 *  no-op. */
export function refreshUsageReading(kind, accountId) {
  const reading = USAGE_READINGS[kind];
  if (!reading || !accountId) return false;
  reading.cache.delete(accountId);
  reading.fetch(accountId);
  return true;
}

/** Re-read every panel that has gone stale, for the page the operator just came
 *  back to. Returns what it refreshed, as `kind → [accountId]`, so the snapshot
 *  can check the decision rather than the listener.
 *
 *  Why this exists: the numbers move while the tab is in the background — that
 *  is when the tokens are being spent — and the panel had no way to notice.
 *  Coming back to a card showing a five-minute-old percentage, with no sign it
 *  was old, is absence drawn as a fact. */
export function refreshUsageOnReturn(now = Date.now()) {
  const refreshed = {};
  for (const [kind, reading] of Object.entries(USAGE_READINGS)) {
    const ids = staleReadings(reading.cache, now);
    if (ids.length) refreshed[kind] = ids;
    ids.forEach((id) => refreshUsageReading(kind, id));
  }
  return refreshed;
}
