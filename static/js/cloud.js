// The cloud under Pools: the pools' cards (pools.js), the window that adds a step or a
// pool (pool-step-dialog.js), and the accounts their steps stand on — the provider picker, the
// account window and the sign-in by a one-time code.
import { CreditLeft } from "./credit-left.js";
import { PoolCards } from "./pools.js";
import { PoolStepDialog } from "./pool-step-dialog.js";
import { SERVER_ORDER, ServerOrder } from "./server-order.js";
import { SubscriptionResetCards } from "./subscription-resets.js";
import { StepCarry } from "./step-carry.js";
import { t } from "./i18n.js";
import { formatPricePer1M, modelPricing } from "./model-meta.js";
import { setTopology, topology, ui } from "./state.js";
import { renderTopology } from "./topology-render.js";
import {
  apiCostsCache,
  apiCostsHtml,
  fetchApiCosts,
  fetchOpenRouterLimits,
  fetchProxySpend,
  fetchSubscriptionUsage,
  fetchUpstreamErrors,
  openrouterLimitsCache,
  openRouterLimitsHtml,
  previewSwitchLevel,
  proxySpendData,
  proxySpendFetchedAt,
  proxySpendHtml,
  proxySpendOf,
  refreshProxySpend,
  refreshUsageReading,
  saveSwitchLevel,
  subscriptionRefreshHtml,
  subscriptionUsageCache,
  subscriptionUsageHtml,
  switchDrag,
  upstreamErrFetchedAt,
  upstreamErrorsHtml,
} from "./usage-stats.js";
import { $, api, copyText, escapeHtml, toast } from "./utils.js";

export let topologyCloudBusy = false;

// Who waits for the account window to close: the step window that sent the operator to connect
// an account gets that account back (pool-step-dialog.js). One owner, emptied on the way out of
// every exit, the cancelled ones included — a hook left behind would hand the next window's
// account to a step window long closed.
export class AccountWindowReturn {
  constructor() { this.after = null; }
  wait(after) { this.after = typeof after === "function" ? after : null; }
  waiting() { return !!this.after; }
  done(accountId = null) {
    const after = this.after;
    this.after = null;
    if (after) after(accountId || null);
  }
}
export const ACCOUNT_RETURN = new AccountWindowReturn();

const drawLane = () => { ui._lastCloudProvidersKey = ""; renderTopologyCloudProviders(); };
const drawBoard = (top) => { if (top) setTopology(top); ui._lastCloudProvidersKey = ""; renderTopology(); };

// "+ Add step" and "+ New pool". Connecting a new account from it opens the provider picker; the
// account window brings the new account back to it.
export const POOL_STEPS = new PoolStepDialog({
  apply: drawBoard,
  render: () => renderTopology(),
  connect: (after) => openCloudPicker(after),
  icon: (account) => cloudAccountIconHtml(account),
  price: (model) => cloudPrice(model),
});

// The pools' cards. Their controls listen on the lane's permanent container (bindCloudCardDelegates):
// the lane's children are replaced by several independent paths (a full render, the usage and
// pricing fetch callbacks), and per-node listeners died with the old nodes.
export const POOL_CARDS = new PoolCards({
  apply: drawBoard,
  addStep: (poolId) => POOL_STEPS.open(poolId),
  editAccount: (accountId) => openCloudAccountModal(accountId),
});
const RESET_CARDS = new SubscriptionResetCards({ redraw: drawLane, refreshed: (id) => refreshUsageReading("subscription", id) });

// The ↻ buttons on a step. One table instead of three identical blocks: each was
// `cache.delete(id); fetch(id)` under a different attribute, and the tab-return refresher
// (usage-stats.js) would have made it a fourth copy of the same two lines.
const USAGE_REFRESH_BUTTONS = [
  ["data-usage-refresh", "usageRefresh", "subscription"],
  ["data-api-costs-refresh", "apiCostsRefresh", "apiCosts"],
  ["data-or-limits-refresh", "orLimitsRefresh", "openrouter"],
];

function bindCloudCardDelegates(cpEl) {
  if (cpEl.dataset.delegated) return;
  cpEl.dataset.delegated = "1";
  // The switch level on a subscription step's limit bar: dragging moves the hatched share at
  // once, letting go saves it, and the lane waits for the release before it redraws
  // (usage-stats.js, switchDrag).
  cpEl.addEventListener("pointerdown", (e) => {
    if (!e.target.closest("[data-pool-switch]")) return;
    switchDrag.begin(drawLane);
  });
  cpEl.addEventListener("input", (e) => {
    const slider = e.target.closest("[data-pool-switch]");
    if (slider) previewSwitchLevel(slider);
  });
  // A pool's step is carried by its grip (step-carry.js, the home start page's way); the pool card
  // saves the order it leaves behind. One carrier per lane, on its permanent container.
  POOL_CARDS.carry = new StepCarry(cpEl, { onSort: (poolId, ids) => POOL_CARDS.sort(poolId, ids) });
  cpEl.addEventListener("change", async (e) => {
    const slider = e.target.closest("[data-pool-switch]");
    if (slider) { saveSwitchLevel(slider, drawBoard); return; }
    await POOL_CARDS.handle(e, drawLane);
  });
  cpEl.addEventListener("click", async (e) => {
    if (await POOL_CARDS.handle(e, drawLane)) return;
    for (const [attr, dataKey, kind] of USAGE_REFRESH_BUTTONS) {
      const btn = e.target.closest(`[${attr}]`);
      if (!btn) continue;
      e.stopPropagation();
      refreshUsageReading(kind, btn.dataset[dataKey]);
      return;
    }
    const retryBtn = e.target.closest("[data-api-retry]");
    if (retryBtn) {
      e.stopPropagation();
      retryBtn.disabled = true;
      try {
        const res = await api("/api/cloud-api-health/retry", { method: "POST", body: JSON.stringify({ key: retryBtn.dataset.apiRetry }) });
        drawBoard(res.topology);
      } catch (err) { toast(err.message); retryBtn.disabled = false; }
    }
  });
}

// A model's price per 1M tokens as a step and the step window say it, or "".
export function cloudPrice(model) {
  if (String(model || "").endsWith(":free")) return "FREE";
  const p = modelPricing[model || ""];
  return p && (p.inputPer1M || p.outputPer1M) ? `${formatPricePer1M(p.inputPer1M)} · ${formatPricePer1M(p.outputPer1M)}` : "";
}

// Dollars as a step's head says them: whole from a dollar up, cents below, and a share too
// small to show said so rather than as $0.
export function cloudMoney(cost) {
  const c = Number(cost) || 0;
  if (c >= 1) return `$${Math.round(c).toLocaleString("en-US")}`;
  if (c >= 0.01) return `$${c.toFixed(2)}`;
  return "<$0.01";
}

// What one step's model cost through the caravan, from its account's 30 days: the cost at API
// prices, or — no price known — how many requests, never "$0". Empty when nothing went to it.
export function cloudStepSpend(accountId, model) {
  const spend = proxySpendOf(accountId);
  const key = String(model || "").toLowerCase();
  const row = (spend?.byModel || []).find((m) => String(m.model || "").toLowerCase() === key);
  if (!row || !(Number(row.requests) > 0 || Number(row.cost) > 0)) return { cost: "", costTitle: "" };
  const days = String(spend.windowDays || 30), req = String(Number(row.requests) || 0);
  return {
    cost: Number(row.cost) > 0 ? t("cloudModelSpend", { cost: cloudMoney(row.cost), days }) : t("cloudModelSpendReq", { req, days }),
    costTitle: t("cloudModelSpendTitle", { days, req }),
  };
}

export function renderTopologyCloudProviders() {
  const accounts = topology?.cloudAccounts || [];
  const pools = topology?.pools || [];
  // Skip re-render when the pools, their readings and the usage caches haven't changed.
  const usageKeys = accounts.map((a) => {
    const c = subscriptionUsageCache.get(a.id) || apiCostsCache.get(a.id) || openrouterLimitsCache.get(a.id);
    return c ? `${a.id}:${c.fetchedAt || 0}:${c.loading ? 1 : 0}` : `${a.id}:0`;
  }).join("|");
  const pricingKey = pools.flatMap((p) => p.steps || []).map((s) => {
    const price = modelPricing[s.model || ""];
    return price ? `${s.model}:${price.inputPer1M}:${price.outputPer1M}` : s.model || "";
  }).join("|");
  const key = poolsRuntimeKey(topology?.poolsRuntime) + JSON.stringify(accounts) + JSON.stringify(pools) + usageKeys + pricingKey
    + `:ps${proxySpendFetchedAt}:ah${JSON.stringify(topology?.cloudApiHealth || {})}:ue${upstreamErrFetchedAt}`
    + `:so${SERVER_ORDER.current().join(",")}`;
  if (key === ui._lastCloudProvidersKey) return;
  if (switchDrag.active) {
    switchDrag.deferred = true;   // redrawn when the pointer lets go
    return;
  }
  if (typeof document !== "undefined" && document.activeElement?.matches?.('[data-pool-field="name"], [data-pool-field="contextLength"]')) return;
  if (POOL_CARDS.inFlight()) return;   // a pool's rung is being dragged: the next tick draws what changed
  ui._lastCloudProvidersKey = key;
  const cpEl = $("topologyCloudProviders");
  if (!cpEl) return;
  bindCloudCardDelegates(cpEl);
  const accountOf = (id) => accounts.find((a) => a.id === id) || { id };
  POOL_CARDS.set({ pools, accounts, runtime: topology?.poolsRuntime || {} });
  // One card of the list under Pools: its place is the operator's
  // (server-order.js), and the controls that move it lead its head, before the icon.
  POOL_CARDS.lead = (pool) => `${SERVER_ORDER.controls(ServerOrder.key("cloud", pool.id), pool.name || pool.id)}<span class="cloud-account-icon pool-icon" aria-hidden="true">${POOL_ICON}</span>`;
  POOL_CARDS.attrs = (pool) => SERVER_ORDER.attrs(ServerOrder.key("cloud", pool.id));
  POOL_CARDS.icon = (account) => cloudAccountIconHtml(account);
  POOL_CARDS.price = (model) => cloudPrice(model);
  // A subscription step's limit bars, with the step's own switch levels on them.
  POOL_CARDS.limits = (pool, step, owner) => {
    fetchSubscriptionUsage(owner);
    return subscriptionUsageHtml(owner, { refresh: false, step: { poolId: pool.id, stepId: step.id, switchAt: step.switchAt || {},
      stopAt: step.stopAt || {}, switchMax: pool.switchMax, switchReached: step.switchReached || null,
      stopReached: step.stopReached || null } });
  };
  POOL_CARDS.refresh = (owner) => subscriptionRefreshHtml(owner);
  POOL_CARDS.chooseReset = (owner) => RESET_CARDS.choose(accountOf(owner));
  // Resets belong to the credential (a TEST step shows its original's); the spend to the step's
  // account and model.
  POOL_CARDS.summary = (owner, accountId, model) => {
    const subscription = PoolCards.subscription(accountOf(accountId));
    if (subscription) RESET_CARDS.read(accountOf(owner));   // the counter reads its own resets, at most once a minute
    return { ...(subscription ? { resets: RESET_CARDS.count(accountOf(owner)), pending: RESET_CARDS.pending(accountOf(owner)),
      resetsFailed: RESET_CARDS.failed(accountOf(owner)) } : {}), ...cloudStepSpend(accountId, model) };
  };
  // An account with a key: what the provider says about it — OpenRouter its key's limits, the
  // OpenAI API its spend (only api.openai.com has the Costs API; elsewhere it 404s).
  POOL_CARDS.usage = (account) => {
    if (!account.hasCredential) return "";
    if (account.type === "openrouter" || String(account.baseUrl || "").includes("openrouter.ai")) { fetchOpenRouterLimits(account.id); return openRouterLimitsHtml(account.id); }
    if (account.type === "openai" || String(account.baseUrl || "").includes("api.openai.com")) { fetchApiCosts(account.id); return apiCostsHtml(account.id); }
    return "";
  };
  // The account's 30 days through the caravan, all its models: the head of a step says its own model's share.
  POOL_CARDS.spend = (account) => proxySpendHtml(account.id, { subscription: PoolCards.subscription(account) });
  // Tripped upstream endpoints (breaker), then the routed traffic that came back 4xx/5xx over 24h.
  POOL_CARDS.issues = (account) => { fetchUpstreamErrors(); return cloudApiIssuesHtml(account, PoolCards.subscription(account)) + upstreamErrorsHtml(account.id); };
  fetchProxySpend();
  cpEl.innerHTML = POOL_CARDS.html();
  // The lane is drawn anew on its own (a usage read coming back): its cards' ↑ ↓ learn again
  // which of them stands first or last in the whole list.
  SERVER_ORDER.apply();
}

// The step window among the board's windows: it reads the accounts and pools of this render.
export function renderPoolStepDialog() {
  POOL_STEPS.set({ accounts: topology?.cloudAccounts || [], pools: topology?.pools || [] });
  return POOL_STEPS.html();
}

// The proxy's word on the pools, as much of it as the cards draw: which step serves, why each
// other one waits, and the minute of the last choice. The second it was made at moves with every
// request, and a lane redrawn on each would take the tooltip from under the pointer.
export function poolsRuntimeKey(runtime) {
  if (!runtime?.available) return "silent";
  const pools = Object.entries(runtime.pools || {}).sort(([a], [b]) => a.localeCompare(b)).map(([id, st]) =>
    `${id}:${st.selectedStepId || ""}:${Math.floor(Number(st.decidedAt || 0) / 60)}:${(st.steps || []).map((r) => `${r.stepId}=${r.reason}`).join("+")}`);
  const events = runtime.events || [];
  return `${pools.join("|")}#${events.length}:${events.length ? events[events.length - 1].at : 0}`;
}

// A pool's mark in its head: stacked layers, unlike any provider's — a pool is not one provider.
const POOL_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17.5l9 5 9-5"/></svg>`;

// A ChatGPT subscription account: its models answer through chatgpt.com, which gates them by
// the codex client_version the caravan sends.
export function isSubscriptionAccount(acct) {
  return acct?.accountType === "openai-subscription" || String(acct?.baseUrl || "").includes("chatgpt.com");
}

// An account's provider icon, in its colour: a subscription has its own mark whatever its type.
export function cloudAccountIconHtml(account) {
  const type = isSubscriptionAccount(account) ? "openai-subscription" : (account?.type || "");
  const meta = CLOUD_PICKER_META[type] || {};
  return `<span class="cloud-account-icon" style="color:${escapeHtml(meta.color || "#94a3b8")}" aria-hidden="true">${cloudPickerTileIcon(type)}</span>`;
}

// The codex client_version the caravan sends to chatgpt.com and where it came from (env
// override / npm latest / built-in floor). It lives under ⚙, in the account's window (the
// operator's variant A): a fact to look up, not to watch on the card. Nothing known — no line.
export function codexVersionHtml() {
  const v = topology?.cloudApiHealth?.codexClientVersion;
  if (!v?.value) return "";
  return `<div class="cloud-span cloud-api-version" title="${escapeHtml(t("cloudApiVersionHint"))}">codex client_version: ${escapeHtml(v.value)}${v.source ? ` · ${escapeHtml(v.source)}` : ""}</div>`;
}

// "API issues" panel: endpoints the breaker tripped (we stopped calling them — the list is the
// user's cue to fix or retry). Routing's account card shows it too (pool-board.js).
export function cloudApiIssuesHtml(acct, isSubscription) {
  const eps = topology?.cloudApiHealth?.endpoints || {};
  const mine = Object.entries(eps)
    .filter(([key]) => key.startsWith(`${acct.id}:`) || (isSubscription && key === "global:codex-npm"));
  if (!mine.length) return "";
  const rows = mine.map(([key, st]) => {
    const what = key.split(":").pop();
    const state = st.disabled
      ? t("cloudApiIssueOff", { n: String(st.failCount || 0) })
      : t("cloudApiIssueFails", { n: String(st.failCount || 0) });
    const when = st.lastErrorAt ? new Date(st.lastErrorAt * 1000).toLocaleString() : "";
    return `<div class="cloud-api-issue${st.disabled ? " off" : ""}">
        <span class="cloud-api-issue-name">${escapeHtml(what)}</span>
        <span class="cloud-api-issue-state">${escapeHtml(state)}</span>
        <span class="cloud-api-issue-err" title="${escapeHtml(st.lastError || "")}">${escapeHtml((st.lastError || "").slice(0, 70))}${when ? ` · ${escapeHtml(when)}` : ""}</span>
        <button class="ghost-action cloud-api-retry" type="button" data-api-retry="${escapeHtml(key)}">${escapeHtml(t("cloudApiIssueRetry"))}</button>
      </div>`;
  }).join("");
  return `<div class="cloud-api-issues"><div class="cloud-api-issues-title">⚠ ${escapeHtml(t("cloudApiIssuesTitle"))}</div>${rows}</div>`;
}

export function topologyCloudPresetByType(type) {
  return (topology?.cloudProviderPresets || []).find((p) => p.type === type) || null;
}

export function topologyCloudSlug(text) {
  return String(text || "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "acct";
}

export function topologyCloudUniqueId(base, taken) {
  let id = base; let n = 2;
  while (taken.includes(id)) { id = `${base}-${n}`; n += 1; }
  return id;
}

// The provider picker, the first page of connecting an account. `after` gets the new account's
// id when the account window closes with one, or null.
export function openCloudPicker(after = null) {
  ACCOUNT_RETURN.wait(after);
  ui.topologyCloudPickerOpen = true;
  ui.topologyCloudModalOpen = false;
  ui.topologyCloudForm = null;
  renderTopology();
}

export function selectCloudProviderType(type) {
  const preset = topologyCloudPresetByType(type) || {};
  const subscriptions = (topology?.cloudAccounts || []).filter((a) => isSubscriptionAccount(a) && !a.testAliasOf).length;
  ui.topologyCloudPickerOpen = false;
  ui.topologyCloudForm = {
    isNew: true,
    accountId: "",
    type,
    // A second subscription is told from the first by its number: two windows named alike
    // made "which one is out of limits" a guess. Named as its block and its tile name it
    // ("ChatGPT subscription"): until 1.3.494 a new one came as "OpenAI subscription N".
    name: type === "openai-subscription" ? `${t("cloudNameSubscription")} ${subscriptions + 1}` : cloudProviderName(type),
    baseUrl: preset.baseUrl || "",
    authMode: (preset.authModes || ["apiKey"])[0],
    oauthConfig: { ...(preset.oauth || {}) },
    apiKey: "",
  };
  ui.topologyCloudModalOpen = true;
  renderTopology();
}

// The main board's providers (caravan/admin/board_providers.py, the owner, 2026-10-12): the picker puts
// one on the board as an empty block, and the "＋" in a block adds an account to it. The controller's
// answer is the board drawn anew; a refusal is said in a toast and changes nothing.
export async function addBoardProvider(kind) {
  try {
    const res = await api("/api/board-providers/add", { method: "POST", body: JSON.stringify({ kind }) });
    ui.topologyCloudPickerOpen = false;
    drawBoard(res.topology);
    return true;
  } catch (err) {
    toast(err.message);
    return false;
  }
}

// An empty provider's ✕. One with accounts is refused by the controller (409) and stays.
export async function removeBoardProvider(kind) {
  try {
    const res = await api("/api/board-providers/remove", { method: "POST", body: JSON.stringify({ kind }) });
    drawBoard(res.topology);
    return true;
  } catch (err) {
    toast(err.message);
    return false;
  }
}

// A tile of the picker: from the main board it puts the provider on the board; from a window waiting
// for an account (pool-step-dialog.js) it opens the new account's window, as it did before providers.
export function pickCloudProvider(type) {
  if (ACCOUNT_RETURN.waiting()) return selectCloudProviderType(type);
  return addBoardProvider(type);
}

// "＋" in a provider's block: a subscription goes straight to its sign-in code — the window opens on
// the code, the account named "ChatGPT subscription N" until it is renamed in ⚙ — and a provider with a
// key opens the window that asks for it. The same sign-in may be added again: nothing refuses it.
export async function connectAccount(kind) {
  selectCloudProviderType(kind);
  if (cloudSignsInByCode(ui.topologyCloudForm)) await startCloudOauthLogin();
}

export function openCloudAccountModal(accountId) {
  const acct = (topology?.cloudAccounts || []).find((a) => a.id === accountId);
  if (!acct) return;
  ui.topologyCloudForm = {
    isNew: false,
    accountId: acct.id,
    type: acct.type || "openai",
    name: acct.name || "",
    baseUrl: acct.baseUrl || "",
    authMode: acct.authMode || "apiKey",
    oauthConfig: {},
    apiKey: "",
    // What the operator typed as the credit left, as typed (credit-left.js): blank for none.
    creditUsd: acct.creditUsd === null || acct.creditUsd === undefined ? "" : String(acct.creditUsd),
  };
  ui.topologyCloudModalOpen = true;
  renderTopology();
}

// Every way out of the picker and the account window but one: nothing new comes back from them.
export function closeCloudProviderModal() {
  ui.topologyCloudModalOpen = false;
  ui.topologyCloudPickerOpen = false;
  ui.topologyCloudForm = null;
  topologyCloudBusy = false;
  renderTopology();
  ACCOUNT_RETURN.done(null);
}

// The one way out that brings an account back: "Done" after a sign-in, Save of a new account.
export function finishCloudAccountWindow(accountId = ui.topologyCloudForm?.accountId) {
  ui.topologyCloudModalOpen = false;
  ui.topologyCloudPickerOpen = false;
  ui.topologyCloudForm = null;
  topologyCloudBusy = false;
  renderTopology();
  ACCOUNT_RETURN.done(accountId || null);
}

// What the window says about each provider: its name and one line, both from the language
// tables, and which group it stands in — a subscription signs in, the rest take a key.
export const CLOUD_PICKER_META = {
  "openai-subscription": { color: "#22c55e", name: "cloudNameSubscription", desc: "cloudDescSubscription", group: "subscription" },
  "openai":              { color: "#60a5fa", name: "cloudNameOpenai",       desc: "cloudDescOpenai",       group: "key" },
  "anthropic":           { color: "#fb923c", name: "cloudNameAnthropic",    desc: "cloudDescAnthropic",    group: "key" },
  "openrouter":          { color: "#a78bfa", name: "cloudNameOpenrouter",   desc: "cloudDescOpenrouter",   group: "key" },
  "ollama":              { color: "#34d399", name: "cloudNameOllama",       desc: "cloudDescOllama",       group: "key" },
  "custom":              { color: "#94a3b8", name: "cloudNameCustom",       desc: "cloudDescCustom",       group: "key" },
};

// A provider's name as the windows say it: from the language table, else the preset's own
// name, else its type — never nothing.
export function cloudProviderName(type) {
  const meta = CLOUD_PICKER_META[type];
  return meta ? t(meta.name) : ((topologyCloudPresetByType(type) || {}).name || String(type || ""));
}

export function cloudPickerTileIcon(type) {
  switch (type) {
    case "openai-subscription":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/></svg>`;
    case "openai":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="15" r="5"/><path d="M8 10V4M22 8l-3 3-9 9"/></svg>`;
    case "anthropic":
      // A spark of eight rays, in the provider's orange. It was a triangle with a bar — a warning sign — and on the board it
      // read as a provider in trouble before it had a key (the owner asked for the Anthropic block to look good, 2026-10-17).
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2.5v19M2.5 12h19M5.3 5.3l13.4 13.4M18.7 5.3L5.3 18.7"/></svg>`;
    case "openrouter":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3l4 4-4 4M3 7h18"/><path d="M7 21l-4-4 4-4M21 17H3"/></svg>`;
    case "ollama":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="2.5" ry="3"/><path d="M9.5 7.5C8 9 8 11 9 12l-2 8h10l-2-8c1-1 1-3-.5-4.5"/><path d="M10 12h4"/><path d="M9 17h6"/></svg>`;
    default:
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>`;
  }
}

export function renderTopologyCloudPicker() {
  if (!ui.topologyCloudPickerOpen) return "";
  const presets = topology?.cloudProviderPresets || [];
  // From the main board a provider already there is no tile to press: the "＋" in its block adds to
  // it. A window waiting for an account (pool-step-dialog.js) picks the account's provider, on the
  // board or not.
  const choosing = ACCOUNT_RETURN.waiting();
  const onBoard = choosing ? new Set() : new Set((topology?.boardProviders || []).map((p) => String(p.kind)));
  const tile = (p) => {
    const meta = CLOUD_PICKER_META[p.type] || { color: "#94a3b8" };
    const there = onBoard.has(p.type);
    const desc = there ? t("cloudPickerOnBoard") : (meta.desc ? t(meta.desc) : "");
    return `
      <button class="cloud-picker-tile${there ? " on-board" : ""}" type="button" data-pick-type="${escapeHtml(p.type)}" data-t="cloud-pick" data-t-state="${escapeHtml(p.type)}"${there ? " disabled" : ""} style="--picker-accent:${escapeHtml(meta.color)}">
        <span class="cloud-picker-icon">${cloudPickerTileIcon(p.type)}</span>
        <span class="cloud-picker-text">
          <span class="cloud-picker-name">${escapeHtml(cloudProviderName(p.type))}</span>
          ${desc ? `<span class="cloud-picker-desc" title="${escapeHtml(desc)}">${escapeHtml(desc)}</span>` : ""}
        </span>
      </button>`;
  };
  const subscriptions = presets.filter((p) => (CLOUD_PICKER_META[p.type] || {}).group === "subscription");
  const keys = presets.filter((p) => (CLOUD_PICKER_META[p.type] || {}).group !== "subscription");
  const group = (label, list, wide) => list.length ? `
        <p class="cloud-picker-group">${escapeHtml(t(label))}</p>
        <div class="cloud-picker-grid${wide ? " wide" : ""}">${list.map(tile).join("")}</div>` : "";
  const title = t(choosing ? "topologyCloudAccountModalTitleNew" : "cloudPickerTitle");
  return `
    <div class="topology-policy-overlay" data-cloud-picker-overlay>
      <div class="topology-policy-modal cloud-window cloud-picker-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}" data-t="cloud-picker">
        <div class="topology-card-head">
          <strong>${escapeHtml(title)}</strong>
          <button class="icon-action compact" type="button" data-cloud-picker-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
        </div>
        <div class="cloud-window-body">${group("cloudPickerSubscription", subscriptions, true)}${group("cloudPickerApiKey", keys, false)}</div>
      </div>
    </div>`;
}

// Sign-in by a one-time code (caravan/admin/oauth.py, DeviceLogin). The server says who has it:
// `deviceLogin` on the preset of a new account and on every existing one — an old subscription
// account is type "openai", so the rule is not the form's type.
export function cloudSignsInByCode(f) {
  if (!f) return false;
  const acct = f.isNew ? null : (topology?.cloudAccounts || []).find((a) => a.id === f.accountId);
  return !!(acct ? acct.deviceLogin : (topologyCloudPresetByType(f.type) || {}).deviceLogin);
}

// ── The account window ───────────────────────────────────────────────────────
// One window, in plain states rather than fields shown and hidden (2026-10-07, the operator's
// mockup): connecting a subscription — before its sign-in, while the code waits, when it ended
// without a login, connected — and an account that exists: a subscription signed in or not, a
// key set or not. The state is a pure function of the form and the account, so the snapshot
// pins it by value.
export function cloudAccountWindowState(f, acct) {
  if (!f) return "";
  if (f.connected) return "connected";
  if (f.deviceLogin) return "waiting";
  if (f.loginEnded) return "ended";
  if (f.isNew) {
    if (cloudSignsInByCode(f)) return "connect";
    return f.authMode === "noKey" ? "newNoKey" : "newKey";
  }
  if (cloudSignsInByCode(f) || acct?.authMode === "oauth") return "subscription";
  return acct?.authMode === "noKey" ? "noKey" : "keyAccount";
}

// Where a provider's address is the operator's to give: their own endpoint, or an Ollama they
// run. The big providers have one address, and showing it invited edits that only break the
// account.
const CLOUD_ADDRESS_TYPES = new Set(["custom", "ollama"]);

const SIGN_IN_STATES = new Set(["connect", "waiting", "ended", "connected"]);

function cloudFieldHtml(label, field, value, { type = "text", placeholder = "", hint = "", inputmode = "" } = {}) {
  return `<label class="cloud-field">${escapeHtml(label)}<input type="${type}" data-cloud-field="${field}" value="${escapeHtml(value || "")}"${placeholder ? ` placeholder="${escapeHtml(placeholder)}"` : ""}${inputmode ? ` inputmode="${inputmode}"` : ""}${type === "password" ? ' autocomplete="off"' : ""}>${hint ? `<span class="cloud-hint">${escapeHtml(hint)}</span>` : ""}</label>`;
}

// The credit the operator says a key account has left: the field, its words (what to type, and that no provider tells it), and the meter
// as the board draws it — the saved figure counted down by what went through the caravan since (credit-left.js).
function cloudCreditHtml(f, acct) {
  return `${cloudFieldHtml(t("creditField"), "creditUsd", f.creditUsd, { placeholder: "200", hint: t("creditHint"), inputmode: "decimal" })}`
    + `${CreditLeft.html(acct, proxySpendData)}`;
}

function cloudWaitingHtml(f) {
  const dl = f.deviceLogin;
  const until = new Date(Number(dl.expiresAt || 0) * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  // The page is a link the operator clicks, and it takes THIS tab (the owner, 2026-10-17: nothing of the
  // caravan opens in a new one). The controller finishes the login by itself — the login has a thread of
  // its own on the controller (DeviceLogin) — so leaving the board costs nothing: the account is there when
  // the operator comes back. The click copies the code first, then goes (topology-dnd.js). The code copies
  // on its own click as well (the operator, 2026-10-08): a click on it used to only select it, and the
  // operator took the selection for a copy.
  return `
    <div class="cloud-code-row" data-t="cloud-device-login">
      <code class="cloud-device-code" role="button" tabindex="0" title="${escapeHtml(t("cloudCodeCopyTip"))}" data-cloud-device-code data-t="cloud-device-code">${escapeHtml(dl.userCode || "")}</code>
      <a class="primary-mini-action cloud-open" href="${escapeHtml(dl.verifyUrl || "")}" data-cloud-device-open data-t="cloud-device-open">${escapeHtml(t("cloudCopyAndOpen"))}</a>
    </div>
    <ol class="cloud-steps">
      <li>${escapeHtml(t("cloudStepSignIn"))}</li>
      <li>${escapeHtml(t("cloudStepPaste"))}</li>
      <li>${escapeHtml(t("cloudStepBack"))}</li>
    </ol>
    <div class="cloud-wait" role="status" data-t="cloud-sign-in-wait"><span class="cloud-spinner" aria-hidden="true"></span>${escapeHtml(t("cloudWaitingUntil", { time: until }))}
      <button class="cloud-link" type="button" data-cloud-oauth-login data-t="cloud-new-code">${escapeHtml(t("cloudNewCode"))}</button></div>
    <p class="cloud-hint">${escapeHtml(t("deviceLoginSetting"))}</p>`;
}

// How a sign-in ended without a login, in words, and the one way on: a new code where the old
// one is merely gone, another try after a refusal, and nothing for an account that is no longer
// there.
const CLOUD_ENDINGS = {
  replaced: { words: "cloudCodeReplaced", again: "cloudNewCode" },
  expired: { words: "cloudCodeExpired", again: "cloudNewCode" },
  unknown: { words: "cloudCodeForgotten", again: "cloudNewCode" },
  removed: { words: "cloudCodeRemoved", again: "" },
};

function cloudEndedHtml(f) {
  const ended = f.loginEnded || {};
  const known = CLOUD_ENDINGS[ended.reason];
  const words = known ? t(known.words) : t("cloudSignInFailed", { error: ended.error || ended.reason || "" });
  const again = known ? known.again : "cloudTryAgain";
  return `
    <div class="cloud-note warn" role="status" data-t="cloud-sign-in-ended" data-t-state="${escapeHtml(ended.reason || "failed")}">${escapeHtml(words)}</div>
    ${again ? `<div class="cloud-btn-row"><button class="primary-mini-action" type="button" data-cloud-oauth-login>${escapeHtml(t(again))}</button></div>` : ""}`;
}

// Connected: what comes next is said by where the operator came from — the step window waits to
// take the account's model; from anywhere else the account stands in no pool until a step names it.
function cloudConnectedHtml(f) {
  const who = f.connected.email ? t("cloudConnectedAs", { email: f.connected.email }) : t("cloudConnected");
  const next = ACCOUNT_RETURN.waiting() ? t("cloudConnectedNext") : t("cloudConnectedAddStep");
  return `<div class="cloud-note good" role="status" data-t="cloud-connected"><strong>✓ ${escapeHtml(who)}</strong><span>${escapeHtml(next)}</span></div>`;
}

function cloudStatusHtml(state, acct) {
  if (state === "subscription") {
    // The plan the last reading of its limits named (Plus, Pro); none read — no word, not a guess.
    const plan = acct?.hasCredential ? String(subscriptionUsageCache.get(acct.testAliasOf || acct.id)?.data?.planType || "") : "";
    const planWord = plan ? ` <span class="cloud-plan" data-t="cloud-account-plan">${escapeHtml(plan.charAt(0).toUpperCase() + plan.slice(1))}</span>` : "";
    return acct?.hasCredential
      ? `<p class="cloud-status good" data-t="cloud-account-status" data-t-state="signed-in">✓ ${escapeHtml(acct.oauthEmail ? t("cloudSignedInAs", { email: acct.oauthEmail }) : t("cloudSignedIn"))}${planWord}</p>`
      : `<p class="cloud-status warn" data-t="cloud-account-status" data-t-state="signed-out">${escapeHtml(t("cloudNotSignedIn"))}</p>`;
  }
  if (state === "noKey") return `<p class="cloud-status" data-t="cloud-account-status" data-t-state="no-auth">${escapeHtml(t("cloudNoAuthNeeded"))}</p>`;
  return acct?.hasCredential
    ? `<p class="cloud-status good" data-t="cloud-account-status" data-t-state="key">✓ ${escapeHtml(t("cloudKeyShort", { last4: acct.keyLast4 || "" }))}</p>`
    : `<p class="cloud-status warn" data-t="cloud-account-status" data-t-state="no-key">${escapeHtml(t("cloudNoKeyYet"))}</p>`;
}

// What a key's provider says about it, in its window: OpenRouter its key's limits, the OpenAI API its
// costs (only api.openai.com has the Costs API; elsewhere it 404s). Until 2026-10-12 it stood under
// Routing's ⋯; the account's window holds what is not on its row (the owner).
function cloudProviderWordHtml(acct) {
  if (!acct?.hasCredential) return "";
  if (acct.type === "openrouter" || String(acct.baseUrl || "").includes("openrouter.ai")) {
    fetchOpenRouterLimits(acct.id);
    return `<div class="cloud-provider-word" data-t="cloud-provider-word">${openRouterLimitsHtml(acct.id)}</div>`;
  }
  if (acct.type === "openai" || String(acct.baseUrl || "").includes("api.openai.com")) {
    fetchApiCosts(acct.id);
    return `<div class="cloud-provider-word" data-t="cloud-provider-word">${apiCostsHtml(acct.id)}</div>`;
  }
  return "";
}

// The pools whose rows stand on the account, as its window lists them: what its deletion takes.
function cloudUsedInHtml(acct) {
  const pools = [...new Set((acct?.usedIn || []).map((u) => u.poolName || u.poolId))];
  if (!pools.length) return `<p class="cloud-hint" data-t="cloud-account-pools">${escapeHtml(t("cloudInNoPool"))}</p>`;
  return `<p class="cloud-hint" data-t="cloud-account-pools">${escapeHtml(t("cloudInPools", { pools: pools.join(", ") }))}</p>`;
}

export function renderTopologyCloudAccountModal() {
  if (!ui.topologyCloudModalOpen || !ui.topologyCloudForm) return "";
  const f = ui.topologyCloudForm;
  const acct = f.isNew ? null : (topology?.cloudAccounts || []).find((a) => a.id === f.accountId);
  const state = cloudAccountWindowState(f, acct);
  const preset = topologyCloudPresetByType(f.type) || {};
  const provider = cloudProviderName(f.type);
  const connecting = f.isNew || f.connecting;
  const title = SIGN_IN_STATES.has(state) && connecting ? t("cloudConnectTitle", { name: provider })
    : (state === "newKey" || state === "newNoKey") ? t("cloudAddTitle", { name: provider })
    : (acct?.name || provider);
  const nameField = cloudFieldHtml(t("cloudNameOnBoard"), "name", f.name);
  const addressField = CLOUD_ADDRESS_TYPES.has(f.type) ? cloudFieldHtml(t("topologyCloudBaseUrl"), "baseUrl", f.baseUrl, { placeholder: "https://…/v1" }) : "";
  const authModes = preset.authModes || ["apiKey"];
  const authField = authModes.length > 1 && (state === "newKey" || state === "newNoKey")
    ? `<label class="cloud-field">${escapeHtml(t("topologyCloudAuthMode"))}<select data-cloud-field="authMode">${authModes.map((m) =>
        `<option value="${escapeHtml(m)}"${m === f.authMode ? " selected" : ""}>${escapeHtml(m === "noKey" ? t("clNoAuth") : t("topologyCloudAuthApiKey"))}</option>`).join("")}</select></label>` : "";
  const change = f.isNew ? `<button class="cloud-link" type="button" data-cloud-picker-change>${escapeHtml(t("topologyCloudPickerChange"))}</button>` : "";
  let body = "";
  let footer = "";
  const cancel = `<button class="ghost-action" type="button" data-cloud-cancel>${escapeHtml(t("topologyCancel"))}</button>`;
  const save = `<button class="primary-mini-action" type="button" data-cloud-save${topologyCloudBusy ? " disabled" : ""}>${escapeHtml(t("topologySave"))}</button>`;
  const remove = `<button class="ghost-action danger" type="button" data-cloud-delete-account>${escapeHtml(t("topologyCloudDeleteAccount"))}</button>`;
  if (state === "connect") {
    body = `${nameField}
      <div class="cloud-btn-row"><button class="primary-mini-action" type="button" data-cloud-oauth-login data-t="cloud-sign-in">${escapeHtml(t("cloudSignInChatgpt"))}</button></div>`;
    footer = cancel;
  } else if (state === "waiting") {
    body = cloudWaitingHtml(f);
    footer = cancel;
  } else if (state === "ended") {
    body = cloudEndedHtml(f);
    footer = cancel;
  } else if (state === "connected") {
    body = cloudConnectedHtml(f);
    footer = `<button class="primary-mini-action" type="button" data-cloud-done data-t="cloud-done">${escapeHtml(t("cloudDone"))}</button>`;
  } else if (state === "subscription") {
    const version = codexVersionHtml();
    if (acct?.hasCredential) fetchSubscriptionUsage(acct.testAliasOf || acct.id);   // the plan's word; read once a page
    body = `${cloudStatusHtml(state, acct)}${nameField}${cloudUsedInHtml(acct)}
      <div class="cloud-btn-row">${acct?.hasCredential
        ? `<button class="ghost-action" type="button" data-cloud-oauth-login data-t="cloud-sign-in">${escapeHtml(t("cloudSignInAgain"))}</button>`
        : `<button class="primary-mini-action" type="button" data-cloud-oauth-login data-t="cloud-sign-in">${escapeHtml(t("cloudSignInChatgpt"))}</button>`}</div>
      ${version ? `<details class="cloud-details"><summary>${escapeHtml(t("cloudDetails"))}</summary>${version}</details>` : ""}`;
    footer = `${remove}${cancel}${save}`;
  } else if (state === "newKey" || state === "newNoKey") {
    body = `${nameField}${addressField}${authField}${state === "newKey"
      ? cloudFieldHtml(t("topologyCloudApiKey"), "apiKey", "", { type: "password", placeholder: t("cloudKeyPlaceholder") }) : ""}`;
    footer = `${cancel}${save}`;
  } else {
    // The credit is a key's to count, so it is asked of an account that has one; its meter counts from the spend reading.
    const credit = state === "keyAccount" && acct?.hasCredential;
    if (credit) fetchProxySpend();
    body = `${cloudStatusHtml(state, acct)}${cloudProviderWordHtml(acct)}${nameField}${addressField}${state === "keyAccount"
      ? cloudFieldHtml(t("cloudNewKey"), "apiKey", "", { type: "password", placeholder: t("cloudNewKeyPlaceholder") }) : ""}${credit ? cloudCreditHtml(f, acct) : ""}${cloudUsedInHtml(acct)}`;
    footer = `${remove}${cancel}${save}`;
  }
  return `
    <div class="topology-policy-overlay" data-topology-cloud-overlay>
      <div class="topology-policy-modal cloud-window cloud-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}" data-t="cloud-account-window" data-t-state="${escapeHtml(state)}">
        <div class="topology-card-head">
          <span class="cloud-window-title" style="--picker-accent:${escapeHtml((CLOUD_PICKER_META[f.type] || {}).color || "#94a3b8")}"><span class="cloud-type-badge-icon">${cloudPickerTileIcon(f.type)}</span><strong>${escapeHtml(title)}</strong>${change}</span>
          <button class="icon-action compact" type="button" data-cloud-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
        </div>
        <div class="cloud-window-body">${body}</div>
        <div class="cloud-window-foot">${footer}</div>
      </div>
    </div>
  `;
}

export async function saveCloudAccount() {
  if (!ui.topologyCloudForm) return;
  const f = ui.topologyCloudForm;
  topologyCloudBusy = true;
  renderTopology();
  try {
    let accountId = f.accountId;
    if (!f.isNew) {
      // An edit sends what changed: the name, the address, how it signs in. It used to send
      // nothing and still say "saved".
      const stored = (topology?.cloudAccounts || []).find((a) => a.id === accountId) || {};
      // The credit: as typed against as stored (blank is none; the controller reads a decimal comma and keeps the moment of a figure
      // that did not change). A window that has no such field — a subscription's — sends nothing.
      const typedCredit = String(f.creditUsd ?? "").trim();
      const storedCredit = stored.creditUsd === null || stored.creditUsd === undefined ? "" : String(stored.creditUsd);
      const creditChanged = f.creditUsd !== undefined && typedCredit !== storedCredit;
      const changed = creditChanged || ["name", "baseUrl", "authMode"].some((k) => String(f[k] ?? "") !== String(stored[k] ?? ""));
      if (changed) {
        if (!/^https?:\/\//.test(f.baseUrl || "")) { toast("base URL must be http(s)"); topologyCloudBusy = false; renderTopology(); return; }
        const account = { id: accountId, type: f.type, name: f.name, baseUrl: f.baseUrl, authMode: f.authMode };
        if (creditChanged) account.creditUsd = typedCredit;
        const editRes = await api("/api/cloud-accounts/save", { method: "POST", body: JSON.stringify({ account }) });
        if (editRes.topology) setTopology(editRes.topology);
        // The meter is read again now: a reading made before the figure was typed counts nothing from it.
        if (creditChanged) refreshProxySpend().catch(() => {});
      }
    } else {
      const preset = topologyCloudPresetByType(f.type) || {};
      const resolvedUrl = f.baseUrl || preset.baseUrl || "";
      if (!/^https?:\/\//.test(resolvedUrl)) { toast("base URL must be http(s)"); topologyCloudBusy = false; renderTopology(); return; }
      const taken = (topology?.cloudAccounts || []).map((a) => a.id);
      accountId = topologyCloudUniqueId(topologyCloudSlug(f.name || f.type), taken);
      const acctRes = await api("/api/cloud-accounts/save", {
        method: "POST",
        body: JSON.stringify({ account: { id: accountId, type: f.type, name: f.name, baseUrl: resolvedUrl, authMode: f.authMode, accountType: preset.accountType || "" } }),
      });
      if (acctRes.topology) setTopology(acctRes.topology);
      // Saved: the window edits this account from here on — a failed key below must not make a
      // second account on the next Save.
      f.isNew = false;
      f.accountId = accountId;
    }
    if ((f.apiKey || "").trim()) {
      const keyRes = await api("/api/cloud-accounts/key", {
        method: "POST",
        body: JSON.stringify({ id: accountId, apiKey: f.apiKey.trim() }),
      });
      if (keyRes.topology) setTopology(keyRes.topology);
      // Bust limits cache so the new key is validated immediately after save.
      openrouterLimitsCache.delete(accountId);
      if (!keyRes.ok) {
        toast(`${t("topologyCloudKeyFail")}: ${keyRes.test?.error || ""}`);
        topologyCloudBusy = false;
        renderTopology();
        return;
      }
    }
    toast(t("cloudAccountSaved"));
    finishCloudAccountWindow(accountId);
  } catch (err) {
    toast(err.message);
    topologyCloudBusy = false;
    renderTopology();
  }
}

// The one way to sign a subscription in: by a one-time code. A new account is saved first — the
// code belongs to an account — and remembered as made for this sign-in, so Cancel can take it
// back while it has no login.
export async function startCloudOauthLogin() {
  const f = ui.topologyCloudForm;
  if (!f) return;
  f.loginEnded = null;
  f.connected = null;
  let accountId = f.accountId;
  if (f.isNew) {
    const preset = topologyCloudPresetByType(f.type) || {};
    const resolvedUrl = f.baseUrl || preset.baseUrl || "";
    const taken = (topology?.cloudAccounts || []).map((a) => a.id);
    accountId = topologyCloudUniqueId(topologyCloudSlug(f.name || f.type), taken);
    const res = await api("/api/cloud-accounts/save", {
      method: "POST",
      body: JSON.stringify({ account: { id: accountId, type: f.type, name: f.name, baseUrl: resolvedUrl, authMode: "oauth", accountType: preset.accountType || "", oauthConfig: f.oauthConfig || {} } }),
    });
    if (res.topology) setTopology(res.topology);
    f.isNew = false;
    f.connecting = true;
    f.createdForSignIn = true;
    f.accountId = accountId;
  }
  if (!accountId) { toast("pick or create an account"); return; }
  await startCloudDeviceLogin(f, accountId);
}

// The board's half of the sign-in by code: show the code, then poll its status for the code's
// whole life (15 minutes; the server ends the login first).
export const DEVICE_LOGIN_POLLS = 460;

async function startCloudDeviceLogin(f, accountId) {
  const started = await api("/api/cloud-accounts/oauth/device-start", {
    method: "POST",
    body: JSON.stringify({ id: accountId }),
  });
  if (!started.userCode || !started.state) { toast("device sign-in failed"); return; }
  f.deviceLogin = { state: started.state, userCode: started.userCode, verifyUrl: started.verifyUrl, expiresAt: started.expiresAt };
  f.loginEnded = null;
  renderTopology();
  pollCloudOauth(started.state, 0, DEVICE_LOGIN_POLLS);
}

export async function copyCloudDeviceCode() {
  const code = ui.topologyCloudForm?.deviceLogin?.userCode;
  if (!code) return false;
  const copied = await copyText(code);
  // A failed copy says so: the operator would paste whatever the clipboard held before,
  // believing it is the code.
  toast(t(copied ? "deviceLoginCopied" : "cloudCodeNotCopied"));
  return copied;
}

export function pollCloudOauth(state, attempt = 0, limit = DEVICE_LOGIN_POLLS) {
  if (!ui.topologyCloudModalOpen || !ui.topologyCloudForm) return;
  // A newer code took this one's place in this window: its answers are not ours.
  if (ui.topologyCloudForm.deviceLogin?.state !== state) return;
  if (attempt > limit) {
    ui.topologyCloudForm.deviceLogin = null;
    ui.topologyCloudForm.loginEnded = { reason: "expired" };
    renderTopology();
    return;
  }
  api(`/api/cloud-accounts/oauth/status?state=${encodeURIComponent(state)}`).then((res) => {
    const f = ui.topologyCloudForm;
    if (!ui.topologyCloudModalOpen || !f || f.deviceLogin?.state !== state) return;
    if (res.state === "done") {
      if (res.topology) setTopology(res.topology);
      f.deviceLogin = null;
      f.connected = { email: res.email || "" };
      renderTopology();
      return;
    }
    // "unknown": the controller restarted and forgot the code — asking for fifteen minutes would
    // change nothing. A replaced or removed login says so.
    if (res.state === "error" || res.state === "unknown") {
      f.deviceLogin = null;
      f.loginEnded = { reason: res.reason || (res.state === "unknown" ? "unknown" : ""), error: res.error || "" };
      renderTopology();
      return;
    }
    setTimeout(() => pollCloudOauth(state, attempt + 1, limit), 2000);
  }).catch(() => setTimeout(() => pollCloudOauth(state, attempt + 1, limit), 2000));
}

// Cancel and × in the account window. An account this window made for its own sign-in goes
// back while it has no login: it used to stay on the board as a subscription that "needs key",
// with nothing to say how it got there.
export async function cancelCloudAccountWindow() {
  const f = ui.topologyCloudForm;
  const acct = f ? (topology?.cloudAccounts || []).find((a) => a.id === f.accountId) : null;
  closeCloudProviderModal();
  if (!f?.createdForSignIn || !acct || acct.hasCredential) return;
  try {
    const res = await api("/api/cloud-accounts/delete", { method: "POST", body: JSON.stringify({ id: acct.id }) });
    if (res.topology) { setTopology(res.topology); renderTopology(); }
  } catch (err) {
    toast(err.message);
  }
}

// What deleting an account does, in the words its confirmation says: every step that names it
// leaves its pool, and the pools stay with their other steps. The sign-out at the provider is
// said only where the server says the delete does it (signOutOnDelete).
export function cloudDeleteWords(acct) {
  const name = acct?.name || acct?.id || "";
  const pools = [...new Set((acct?.usedIn || []).map((u) => u.poolName || u.poolId))];
  const words = pools.length
    ? t("accountDeleteSteps", { name, pools: pools.join(", "), count: String((acct.usedIn || []).length) })
    : t("accountDeleteText", { name });
  return acct?.signOutOnDelete ? `${words} ${t("cloudDeleteSignsOut")}` : words;
}

export async function deleteCloudAccount() {
  const accountId = ui.topologyCloudForm?.accountId;
  if (!accountId) return;
  try {
    const res = await api("/api/cloud-accounts/delete", {
      method: "POST",
      body: JSON.stringify({ id: accountId }),
    });
    if (res.topology) setTopology(res.topology);
    // The controller asked OpenAI to end the sign-in (oauth.SignOut): what OpenAI answered is
    // said, a refusal or silence included.
    if (res.signOut) toast(res.signOut.ok ? t("cloudSignedOut") : t("cloudSignOutFailed", { error: res.signOut.error || "" }));
  } catch (err) {
    toast(err.message);
  }
  closeCloudProviderModal();
}
