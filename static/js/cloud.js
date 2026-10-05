// Cloud provider accounts/blocks modals and OAuth login flow.
import { SubscriptionPoolCards } from "./cloud-pools.js";
import { SERVER_ORDER, ServerOrder } from "./server-order.js";
import { SubscriptionResetCards } from "./subscription-resets.js";
import { GoneModelCables, NewModelAnnouncer, PortCloser, ProviderModels } from "./cloud-models.js";
import { badge, option } from "./form.js";
import { t } from "./i18n.js";
import { modelPricing } from "./model-meta.js";
import { setTopology, state, topology, ui } from "./state.js";
import { refreshTopology, renderTopology } from "./topology-render.js";
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
  previewUsageReserve,
  proxySpendFetchedAt,
  proxySpendHtml,
  proxySpendOf,
  refreshUsageReading,
  reserveDrag,
  saveUsageReserve,
  spendCost,
  subscriptionRefreshHtml,
  subscriptionUsageCache,
  subscriptionUsageHtml,
  upstreamErrFetchedAt,
  upstreamErrorsHtml,
} from "./usage-stats.js";
import { appConfirm } from "./dialogs.js";
import { $, api, copyText, escapeHtml, pill, toast } from "./utils.js";

export let topologyCloudBlockModalOpen = false;
export let topologyCloudBlockForm = null;
export let topologyCloudBusy = false;
export const topologyCloudModelCache = new Map(); // accountId → models[], fetched once at page load

// When the page may ask a provider for its model list again after a refusal.
// A refusal is not an answer (the in-flight marker is forgotten), and it is not
// a reason to ask again at once either: the page asks on every poll, so an
// account that kept failing was asked every 1.5 s, forever. The operator's own
// act — opening the model editor — asks regardless.
export class ModelListAsks {
  constructor({ now = () => Date.now(), pauseMs = 60000 } = {}) {
    this.now = now;
    this.pauseMs = pauseMs;
    this.failedAt = new Map();   // accountId → when its last ask was refused
  }

  mayAsk(accountId, force = false) {
    const at = this.failedAt.get(accountId);
    return force || at === undefined || this.now() - at >= this.pauseMs;
  }

  refused(accountId) { this.failedAt.set(accountId, this.now()); }
}
export const MODEL_LIST_ASKS = new ModelListAsks();
// Provider-card controls via DELEGATION on the permanent container: the lane's
// children are replaced by several independent paths (full renderTopology, the
// usage/pricing fetch callbacks, the flyout toggle) — per-node listeners bound
// by bindTopologyDragAndDrop died with the old nodes whenever a callback-path
// re-render ran, leaving dead buttons. One listener on the container survives
// every innerHTML swap.
// The ↻ buttons on a cloud card. One table instead of three identical blocks:
// each was `cache.delete(id); fetch(id)` under a different attribute, and the
// tab-return refresher (usage-stats.js) would have made it a fourth copy of the
// same two lines. The button and the refresher call the same action. It lived
// in bindTopologyDragAndDrop, which runs on every full render and bound it to
// this permanent container again each time: after K renders one ↻ asked the
// provider K times.
const POOL_CARDS = new SubscriptionPoolCards({ apply: (top) => { setTopology(top); ui._lastCloudProvidersKey = ""; renderTopology(); }, connect: (id) => selectCloudProviderType("openai-subscription", id) });
const RESET_CARDS = new SubscriptionResetCards({ redraw: () => { ui._lastCloudProvidersKey = ""; renderTopologyCloudProviders(); }, refreshed: (id) => refreshUsageReading("subscription", id) });

const USAGE_REFRESH_BUTTONS = [
  ["data-usage-refresh", "usageRefresh", "subscription"],
  ["data-api-costs-refresh", "apiCostsRefresh", "apiCosts"],
  ["data-or-limits-refresh", "orLimitsRefresh", "openrouter"],
];

function bindCloudCardDelegates(cpEl) {
  if (cpEl.dataset.delegated) return;
  cpEl.dataset.delegated = "1";
  // The reserve slider on a subscription's limit bar: dragging moves the
  // hatched share at once, letting go saves it, and the lane waits for the
  // release before it redraws (usage-stats.js, reserveDrag).
  cpEl.addEventListener("pointerdown", (e) => {
    if (!e.target.closest("[data-usage-reserve]")) return;
    reserveDrag.begin(() => {
      ui._lastCloudProvidersKey = "";
      renderTopologyCloudProviders();
    });
  });
  cpEl.addEventListener("input", (e) => {
    const slider = e.target.closest("[data-usage-reserve]");
    if (slider) previewUsageReserve(slider);
  });
  // A pool's rung is dragged by its grip: the pool card reads the drag, the lane only passes it on.
  for (const type of ["dragstart", "dragover", "drop", "dragend"]) cpEl.addEventListener(type, (e) => { POOL_CARDS.gesture(e); });
  cpEl.addEventListener("change", async (e) => {
    if (await POOL_CARDS.handle(e)) return;
    const slider = e.target.closest("[data-usage-reserve]");
    if (slider) saveUsageReserve(slider);
  });
  cpEl.addEventListener("click", async (e) => {
    if (await RESET_CARDS.handle(e, topology?.cloudAccounts || [])) return;
    if (await POOL_CARDS.handle(e)) return;
    for (const [attr, dataKey, kind] of USAGE_REFRESH_BUTTONS) {
      const btn = e.target.closest(`[${attr}]`);
      if (!btn) continue;
      e.stopPropagation();
      refreshUsageReading(kind, btn.dataset[dataKey]);
      return;
    }
    const toggle = e.target.closest("[data-cloud-models-toggle]");
    if (toggle) {
      e.stopPropagation();
      const id = toggle.dataset.cloudModelsToggle;
      (ui.cloudModelsOpen ||= {})[id] = !ui.cloudModelsOpen[id];
      ui._lastCloudProvidersKey = "";   // the class lives outside the render key
      renderTopologyCloudProviders();
      return;
    }
    const edit = e.target.closest("[data-cloud-edit-account]");
    if (edit) { e.stopPropagation(); openCloudAccountModal(edit.dataset.cloudEditAccount); return; }
    const addBlock = e.target.closest("[data-cloud-add-block]");
    if (addBlock) { e.stopPropagation(); openCloudBlockModal(null, addBlock.dataset.cloudAddBlock); return; }
    const retryBtn = e.target.closest("[data-api-retry]");
    if (retryBtn) {
      e.stopPropagation();
      retryBtn.disabled = true;
      try {
        const res = await api("/api/cloud-api-health/retry", { method: "POST", body: JSON.stringify({ key: retryBtn.dataset.apiRetry }) });
        if (res.topology) setTopology(res.topology);
        renderTopology();
      } catch (err) { toast(err.message); retryBtn.disabled = false; }
      return;
    }
    const fetchBtn = e.target.closest("[data-cloud-fetch-models]");
    if (fetchBtn) {
      // "↻ check now": the list is checked by itself every ten minutes while
      // the board is open; this asks at once and says what it found.
      e.stopPropagation();
      const id = fetchBtn.dataset.cloudFetchModels;
      fetchBtn.disabled = true;
      fetchBtn.classList.add("spinning");
      try {
        const res = await api("/api/cloud-accounts/auto-create-blocks", { method: "POST", body: JSON.stringify({ id }) });
        await refreshTopology();
        toast(t("cloudChecked", { total: String(res.total || 0), created: String(res.created || 0),
          gone: String(res.gone || 0), removed: String(res.removed || 0) }));
        ui._lastCloudProvidersKey = "";
        renderTopology();
      } catch (err) { toast(`${t("cloudCheckFailed")}: ${err.message}`); fetchBtn.disabled = false; fetchBtn.classList.remove("spinning"); }
      return;
    }
    const mint = e.target.closest("[data-bridge-mint]");
    if (mint) {
      e.stopPropagation();
      // The "+ port" on a model's row: that model on its own open port.
      const blockId = mint.dataset.bridgeMint;
      if (!blockId) return;
      mint.disabled = true;
      try {
        const res = await api("/api/cloud-accounts/bridge-port", { method: "POST", body: JSON.stringify({ blockId }) });
        await refreshTopology();
        const url = `http://${location.hostname}:${res.route.port}`;
        toast((await copyText(url)) ? t("cloudBridgeMinted", { url }) : url);
        renderTopology();
      } catch (err) { toast(err.message); mint.disabled = false; }
      return;
    }
    const copyBtn = e.target.closest("[data-bridge-copy]");
    if (copyBtn) {
      e.stopPropagation();
      toast((await copyText(copyBtn.dataset.bridgeCopy)) ? t("cloudBridgeCopied") : copyBtn.dataset.bridgeCopy);
      return;
    }
    const del = e.target.closest("[data-bridge-delete]");
    if (del) {
      // The model's port: the last one takes it off the kanban, and the
      // closer asks what happens to what still leads to it.
      e.stopPropagation();
      const port = Number(del.dataset.bridgeDelete);
      const route = (topology?.proxies || []).find((p) => Number(p.port) === port);
      await PORT_CLOSER.close(route?.providerId || "", port);
      return;
    }
    const restore = e.target.closest("[data-cloud-restore]");
    if (restore) {
      e.stopPropagation();
      const [accountId, id] = String(restore.dataset.cloudRestore).split("|");
      restore.disabled = true;
      try {
        const res = await api("/api/cloud-blocks/restore", { method: "POST", body: JSON.stringify({ accountId, id }) });
        if (res.topology) setTopology(res.topology);
        toast(t("cloudRestored", { model: res.block?.model || id }));
        renderTopology();
      } catch (err) { toast(err.message); restore.disabled = false; }
      return;
    }
    const move = e.target.closest("[data-cloud-move-cables]");
    if (move) {
      e.stopPropagation();
      move.disabled = true;
      await GONE_CABLES.offer(move.dataset.cloudMoveCables);
      move.disabled = false;
      return;
    }
    const row = e.target.closest("[data-cloud-block]");
    if (row) openCloudBlockModal(row.dataset.cloudBlock, null);
  });
  cpEl.addEventListener("keydown", (e) => {
    // The row itself, not a button in it: Enter on "＋ port" opened the
    // model's window, and the port was never minted from the keyboard.
    const row = e.target.matches?.("[data-cloud-block]") ? e.target : null;
    if (row && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openCloudBlockModal(row.dataset.cloudBlock, null); }
  });
}

export function renderTopologyCloudProviders() {
  const accounts = topology?.cloudAccounts || [];
  const blocks = topology?.cloudProviders || [];
  // Skip re-render when cloud data + usage cache haven't changed
  const usageKeys = accounts.map((a) => {
    const c = subscriptionUsageCache.get(a.id) || apiCostsCache.get(a.id) || openrouterLimitsCache.get(a.id);
    return c ? `${a.id}:${c.fetchedAt || 0}:${c.loading ? 1 : 0}` : `${a.id}:0`;
  }).join("|");
  // Include pricing fingerprint for relevant models so pricing load triggers re-render
  const pricingKey = blocks.map((b) => {
    const p = modelPricing[b.model || ""];
    return p ? `${b.model}:${p.inputPer1M}:${p.outputPer1M}` : b.model || "";
  }).join("|");
  // Bridge ports live on the provider cards — their set must trigger a re-render.
  const bridgesKey = (topology?.proxies || [])
    .filter((p) => p.kind === "service")
    .map((p) => `${p.port}:${p.providerId}`).join(",");
  // Fetched model lists drive the "not listed by provider" marks — arrival must re-render.
  const modelsKey = accounts.map((a) => `${a.id}:${(topologyCloudModelCache.get(a.id) || []).length}`).join("|")
    // …and so do the sync's removals ("↶"), and the cables that reach a model.
    + JSON.stringify(topology?.cloudRemoved || [])
    + (topology?.routers || []).map((r) => (r.graph?.edges || []).filter((e) => String(e?.to || "").startsWith("out:cb:")).map((e) => e.to).join(",")).join("|");
  // Endpoint-health panel (breaker trips / retries / codex version) re-renders too.
  const healthKey = JSON.stringify(topology?.cloudApiHealth || {});
  // The mint button shows the port the next bridge will get — its change must re-render.
  const key = JSON.stringify(topology?.cloudPoolsRuntime || {}) + JSON.stringify(accounts) + JSON.stringify(blocks) + usageKeys + pricingKey
    + `:ps${proxySpendFetchedAt}:br${bridgesKey}:np${topology?.nextAppPort ?? ""}:ml${modelsKey}:ah${healthKey}:ue${upstreamErrFetchedAt}`;
  if (key === ui._lastCloudProvidersKey) return;
  if (reserveDrag.active) {
    reserveDrag.deferred = true;   // redrawn when the pointer lets go
    return;
  }
  if (typeof document !== "undefined" && document.activeElement?.matches?.('[data-pool-field="name"]')) return;
  if (POOL_CARDS.inFlight()) return;   // a pool's rung is being dragged: the next tick draws what changed
  ui._lastCloudProvidersKey = key;
  const cpEl = $("topologyCloudProviders");
  if (!cpEl) return;
  bindCloudCardDelegates(cpEl);
  if (!accounts.length) {
    // "click + to add one": the + is in the head of Model servers (index.html), the lane's main action.
    cpEl.innerHTML = `<article class="topology-card"><div class="topology-muted">${escapeHtml(t("topologyCloudNoProviders"))}</div></article>`;
    SERVER_ORDER.apply();   // the last card of the list may be a machine now
    return;
  }
  POOL_CARDS.accounts = accounts;
  POOL_CARDS.runtime = topology?.cloudPoolsRuntime || {};
  // What each rung of a pool shows: the limit bars always; the saved resets and the spend under its
  // head; and, in the head, only the numbers — how many resets (null while unread), what it cost.
  const accountOf = (id) => accounts.find((a) => a.id === id) || { id };
  POOL_CARDS.limits = (id) => { fetchSubscriptionUsage(id); return subscriptionUsageHtml(id, { refresh: false }); };
  POOL_CARDS.refresh = (id) => subscriptionRefreshHtml(id);
  POOL_CARDS.resets = (id) => RESET_CARDS.html(accountOf(id));
  POOL_CARDS.chooseReset = (id) => RESET_CARDS.choose(accountOf(id));
  // Resets belong to the credential (a TEST member shows its original's); the spend to the account itself.
  POOL_CARDS.summary = (owner, id) => {
    const spend = proxySpendOf(id);
    return { resets: RESET_CARDS.count(accountOf(owner)), pending: RESET_CARDS.pending(accountOf(owner)), cost: spend?.total ? spendCost(spend) : "" };
  };
  POOL_CARDS.spend = (id) => proxySpendHtml(id, { subscription: true });
  cpEl.innerHTML = accounts.filter((a) => SubscriptionPoolCards.cardOf(accounts, a.id) === a.id).map((acct) => {
    const isSubscription = isSubscriptionAccount(acct);
    const credLine = acct.hasCredential
      ? (acct.credentialKind === "noKey"
          ? "no auth"
          : acct.credentialKind === "oauth"
              ? (isSubscription ? `ChatGPT${acct.oauthEmail ? ` · ${acct.oauthEmail}` : ""}` : `OAuth${acct.oauthEmail ? ` · ${acct.oauthEmail}` : ""}`)
              : t("topologyCloudKeySet", { last4: acct.keyLast4 || "" }))
      : t("topologyCloudNeedsKey");
    const iconType = isSubscription ? "openai-subscription" : (acct.type || "");
    const meta = CLOUD_PICKER_META[iconType] || CLOUD_PICKER_META[acct.type || ""] || {};
    const iconHtml = `<span class="cloud-account-icon" style="color:${escapeHtml(meta.color || "#94a3b8")}">${cloudPickerTileIcon(iconType)}</span>`;
    // One card of the list under Model servers, among the machines: its place is the
    // operator's (server-order.js), and the controls that move it lead its head, before the icon.
    const orderKey = ServerOrder.key("cloud", acct.id);
    const orderHtml = SERVER_ORDER.controls(orderKey, acct.name || acct.id);
    // Usage/spend panel (fetched async). Subscription → ChatGPT Plus limits/credits;
    // OpenRouter → key limits via /auth/key; API accounts → official spend via Costs API.
    const isOpenRouter = acct.type === "openrouter" || String(acct.baseUrl || "").includes("openrouter.ai");
    // The Costs API (/organization/costs) exists only on api.openai.com — for
    // other providers (Ollama, Anthropic, generic) the probe just 404s, so
    // don't fire it; the local proxy spend-meter below covers them.
    const hasCostsApi = acct.type === "openai" || String(acct.baseUrl || "").includes("api.openai.com");
    let usagePanel = "";
    if (acct.hasCredential && !acct.isPool) {
      if (isSubscription) { fetchSubscriptionUsage(acct.id); usagePanel = subscriptionUsageHtml(acct.id); }
      else if (isOpenRouter) { fetchOpenRouterLimits(acct.id); usagePanel = openRouterLimitsHtml(acct.id); }
      else if (hasCostsApi) { fetchApiCosts(acct.id); usagePanel = apiCostsHtml(acct.id); }
    }
    // Local proxy spend-meter (our token counts × pricing) — for every cloud account.
    fetchProxySpend();
    if (!acct.isPool) usagePanel += proxySpendHtml(acct.id, { subscription: isSubscription });
    usagePanel += POOL_CARDS.controls(acct, `${orderHtml}${iconHtml}`);
    if (SubscriptionPoolCards.subscription(acct)) usagePanel += RESET_CARDS.html(acct);
    // Tripped upstream endpoints (breaker).
    usagePanel += cloudApiIssuesHtml(acct, isSubscription);
    // Data-plane cloud failures over 24h (routed traffic that came back 4xx/5xx).
    fetchUpstreamErrors();
    usagePanel += upstreamErrorsHtml(acct.id);
    // One cable handle per PROVIDER (account). The router output attaches here;
    // the actual model is chosen inside the router. The model list is hidden until
    // hover (slide-out flyout with prices).
    const modelsOpen = !!ui.cloudModelsOpen?.[acct.id];
    return `
      <article class="topology-card cloud-account-card ${acct.hasCredential ? "configured" : "needs-key"}${modelsOpen ? " models-open" : ""}"${SERVER_ORDER.attrs(orderKey)}>
        <span class="topology-handle server-input cloud-account-input" data-topology-cloud-input="1" data-account-id="${escapeHtml(acct.id)}" title="${escapeHtml(t("clTitleRouterOutput"))}"></span>
        ${acct.isPool ? "" : `<div class="cloud-account-head">
          ${orderHtml}${iconHtml}
          <strong class="cloud-account-name">${escapeHtml(acct.name || acct.id)}</strong>
          ${acct.hasCredential ? pill(isSubscription ? "ChatGPT" : acct.credentialKind === "noKey" ? t("clReady") : acct.credentialKind === "apiKey" ? t("topologyCloudConfigured") : "OAuth", "good") : pill(t("topologyCloudNeedsKey"), "warn")}
          <button class="icon-action compact" type="button" data-cloud-edit-account="${escapeHtml(acct.testAliasOf || acct.id)}" title="${escapeHtml(t("clTitleEditAccount"))}">⚙</button>
        </div>`}
        ${acct.isPool ? "" : `<div class="cloud-key-line ${acct.hasCredential ? "set" : "unset"}">${escapeHtml(credLine)}</div>`}
        ${usagePanel}
        ${new ProviderModels({ account: acct, blocks, routers: topology?.routers || [], proxies: topology?.proxies || [],
          removed: topology?.cloudRemoved || [], open: modelsOpen, nextPort: topology?.nextAppPort,
          hostname: location.hostname, spend: proxySpendOf(acct.id) }).html()}
      </article>
    `;
  }).join("") + (() => {
    // Bridges whose model block is GONE vanish from the per-account panels (the
    // block filter can't attribute them) — without this strip they'd keep
    // listening on their port, invisible and undeletable from the UI.
    const allBlockIds = new Set(blocks.map((b) => b.id));
    const orphans = (topology?.proxies || [])
      .filter((p) => p.kind === "service" && !allBlockIds.has(p.providerId))
      .sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
    if (!orphans.length) return "";
    return `<div class="cloud-orphan-bridges">
      <div class="cloud-api-issues-title">⚠ ${escapeHtml(t("cloudOrphanBridges"))}</div>
      ${orphans.map((p) => `<div class="cloud-bridge-row unlisted">
        <code class="cloud-bridge-port">:${escapeHtml(String(p.port))}</code>
        <span class="cloud-bridge-model" title="${escapeHtml(p.label || "")}">→ ${escapeHtml(p.providerId || "?")}</span>
        <button class="icon-action compact" type="button" data-bridge-delete="${escapeHtml(String(p.port))}" title="${escapeHtml(t("cloudBridgeDelete"))}">✕</button>
      </div>`).join("")}
    </div>`;
  })();
  // The lane is drawn anew on its own (a usage read coming back): its cards' ↑ ↓ learn again
  // which of them stands first or last in the whole list.
  SERVER_ORDER.apply();
}

// A ChatGPT subscription account: its models answer through chatgpt.com, which
// gates them by the codex client_version the caravan sends.
export function isSubscriptionAccount(acct) {
  return acct?.accountType === "openai-subscription" || String(acct?.baseUrl || "").includes("chatgpt.com");
}

// The codex client_version the caravan sends to chatgpt.com and where it came
// from (env override / npm latest / built-in floor). It lives under ⚙, in the
// account's window (the operator's variant A): a fact to look up, not to watch
// on the card. Nothing known — no line.
export function codexVersionHtml() {
  const v = topology?.cloudApiHealth?.codexClientVersion;
  if (!v?.value) return "";
  return `<div class="cloud-span cloud-api-version" title="${escapeHtml(t("cloudApiVersionHint"))}">codex client_version: ${escapeHtml(v.value)}${v.source ? ` · ${escapeHtml(v.source)}` : ""}</div>`;
}

// "API issues" panel: endpoints the breaker tripped (we stopped calling them —
// the list is the user's cue to fix or retry).
function cloudApiIssuesHtml(acct, isSubscription) {
  const health = topology?.cloudApiHealth || {};
  const eps = health.endpoints || {};
  const mine = Object.entries(eps)
    .filter(([key]) => key.startsWith(`${acct.id}:`) || (isSubscription && key === "global:codex-npm"));
  let html = "";
  if (mine.length) {
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
    html += `<div class="cloud-api-issues"><div class="cloud-api-issues-title">⚠ ${escapeHtml(t("cloudApiIssuesTitle"))}</div>${rows}</div>`;
  }
  return html;
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

export function openCloudProviderModal(blockId) {
  if (!blockId) {
    ui.topologyCloudPickerOpen = true;
    ui.topologyCloudModalOpen = false;
    ui.topologyCloudForm = null;
    renderTopology();
    return;
  }
  openCloudBlockModal(blockId, null);
}

export function selectCloudProviderType(type, poolId = "") {
  const preset = topologyCloudPresetByType(type) || {};
  ui.topologyCloudPickerOpen = false;
  ui.topologyCloudForm = {
    isNew: true,
    ...(poolId ? { poolId } : {}),
    accountId: "",
    type,
    name: poolId ? `${t("poolSubscriptionName")} ${(topology?.cloudAccounts || []).filter((a) => isSubscriptionAccount(a) && !a.isPool && !a.testAliasOf).length + 1}` : preset.name || "",
    baseUrl: preset.baseUrl || "",
    authMode: (preset.authModes || ["apiKey"])[0],
    oauthConfig: { ...(preset.oauth || {}) },
    apiKey: "",
    oauthStatus: "",
  };
  ui.topologyCloudModalOpen = true;
  renderTopology();
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
    oauthStatus: "",
  };
  ui.topologyCloudModalOpen = true;
  renderTopology();
}

export function openCloudBlockModal(blockId, accountId) {
  const block = blockId ? (topology?.cloudProviders || []).find((b) => b.id === blockId) : null;
  topologyCloudBlockForm = {
    isNew: !block,
    blockId: block?.id || "",
    accountId: block?.accountId || accountId || "",
    blockName: block?.name || "",
    model: block?.model || "",
    origModel: block?.model || "",   // to warn when an EDIT rewires the block to another model
    modelMode: block?.modelMode || "rewrite",
    contextLength: block?.contextLength ? String(block.contextLength) : "",
    contextAuto: !!block?.contextAuto,
  };
  topologyCloudBlockModalOpen = true;
  renderTopology();
  const resolvedAccountId = topologyCloudBlockForm.accountId;
  const acct = (topology?.cloudAccounts || []).find((a) => a.id === resolvedAccountId);
  if (acct && acct.hasCredential) {
    // The operator opened the editor: ask now, even inside a pause.
    if ((acct.accountType || "") === "openai-subscription" || String(acct.baseUrl || "").includes("chatgpt.com")) {
      fetchCloudSubscriptionModels(resolvedAccountId, { force: true });
    } else {
      fetchCloudAccountModels(resolvedAccountId, { force: true });
    }
  }
}

export function closeCloudBlockModal() {
  topologyCloudBlockModalOpen = false;
  topologyCloudBlockForm = null;
  renderTopology();
}

export function closeCloudProviderModal() {
  ui.topologyCloudModalOpen = false;
  ui.topologyCloudPickerOpen = false;
  ui.topologyCloudForm = null;
  topologyCloudBusy = false;
  renderTopology();
}

export const CLOUD_PICKER_META = {
  "openai-subscription": { desc: "ChatGPT Plus · OAuth · GPT-5.4+", color: "#22c55e" },
  "openai":              { desc: "API Credits · API key",            color: "#60a5fa" },
  "anthropic":           { desc: "Claude models · API key",          color: "#fb923c" },
  "openrouter":          { desc: "100+ models · API key",            color: "#a78bfa" },
  "ollama":              { desc: "ollama.com cloud · API key",           color: "#34d399" },
  "custom":              { desc: "OpenAI-compatible endpoint",        color: "#94a3b8" },
};

export function cloudPickerTileIcon(type) {
  switch (type) {
    case "openai-subscription":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/></svg>`;
    case "openai":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="15" r="5"/><path d="M8 10V4M22 8l-3 3-9 9"/></svg>`;
    case "anthropic":
      return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 19.5h20L12 2z"/><path d="M12 9v5"/></svg>`;
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
  const tiles = presets.map((p) => {
    const meta = CLOUD_PICKER_META[p.type] || { desc: "", color: "#94a3b8" };
    return `
      <button class="cloud-picker-tile" data-pick-type="${escapeHtml(p.type)}" style="--picker-accent:${escapeHtml(meta.color)}">
        <span class="cloud-picker-icon">${cloudPickerTileIcon(p.type)}</span>
        <span class="cloud-picker-name">${escapeHtml(p.name || p.type)}</span>
        <span class="cloud-picker-desc">${escapeHtml(meta.desc)}</span>
      </button>`;
  }).join("");
  return `
    <div class="topology-policy-overlay" data-cloud-picker-overlay>
      <div class="topology-policy-modal cloud-picker-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(t("topologyCloudPickerTitle"))}">
        <div class="topology-card-head">
          <strong>${escapeHtml(t("topologyCloudPickerTitle"))}</strong>
          <button class="icon-action compact" type="button" data-cloud-picker-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
        </div>
        <div class="cloud-picker-grid">${tiles}</div>
      </div>
    </div>`;
}

export function cloudModalIsSubscription() {
  if (!ui.topologyCloudForm) return false;
  const f = ui.topologyCloudForm;
  if (f.accountMode === "new") {
    const p = topologyCloudPresetByType(f.newType);
    return (p?.accountType || "") === "openai-subscription";
  }
  const acct = (topology?.cloudAccounts || []).find((a) => a.id === f.accountId);
  return (acct?.accountType || "") === "openai-subscription" || String(acct?.baseUrl || "").includes("chatgpt.com");
}

async function _fetchModelsInto(accountId, path, { force = false } = {}) {
  // One body for both lists: they were two copies of the same eight lines, and
  // the same defect sat in both.
  if (!accountId || topologyCloudModelCache.has(accountId) || !MODEL_LIST_ASKS.mayAsk(accountId, force)) return;
  // The empty array is the in-flight marker — it is what makes concurrent
  // callers ask only once.
  topologyCloudModelCache.set(accountId, []);
  try {
    const res = await api(`${path}?id=${encodeURIComponent(accountId)}`);
    if (res.ok && Array.isArray(res.models)) {
      topologyCloudModelCache.set(accountId, res.models);
      renderTopology();
      return;
    }
  } catch (_) { /* the reason belongs to whoever showed the request; here we
                   only decide whether this counts as an answer */ }
  // A refusal is not an answer and must not be remembered as one. The marker
  // used to stay behind, `has()` then refused every retry until the page was
  // reloaded, and an empty list reads on the board exactly like "this account
  // has no models" — absence drawn as a fact. Forgetting it lets the next
  // caller ask again — after a pause (MODEL_LIST_ASKS).
  topologyCloudModelCache.delete(accountId);
  MODEL_LIST_ASKS.refused(accountId);
}

export async function fetchCloudSubscriptionModels(accountId, opts) {
  return _fetchModelsInto(accountId, "/api/cloud-accounts/subscription-models", opts);
}

export async function fetchCloudAccountModels(accountId, opts) {
  return _fetchModelsInto(accountId, "/api/cloud-accounts/models", opts);
}

// The two offers to move a provider's cables (cloud-models.js): the "new
// model" window, asked after a refresh of the board, and "⇄ Move cables…" on
// a gone model's row. Their answers come back with the board, drawn at once.
const drawBoard = (top) => { setTopology(top); renderTopology(); };
export const NEW_MODELS = new NewModelAnnouncer({ apply: drawBoard });
export const GONE_CABLES = new GoneModelCables({ apply: drawBoard });
// Closing a model's port — the ✕ on the card, unticking it on the kanban.
export const PORT_CLOSER = new PortCloser({ apply: drawBoard });

export function prefetchAllSubscriptionModels() {
  const accounts = topology?.cloudAccounts || [];
  accounts.forEach((acct) => {
    // Nobody signed in, nothing to list: a subscription with no sign-in used
    // to be asked on every poll and refused every time.
    if (!acct.hasCredential) return;
    if ((acct.accountType || "") === "openai-subscription" || String(acct.baseUrl || "").includes("chatgpt.com")) {
      fetchCloudSubscriptionModels(acct.id);
    } else {
      fetchCloudAccountModels(acct.id);
    }
  });
}

export function renderTopologyCloudAccountModal() {
  if (!ui.topologyCloudModalOpen || !ui.topologyCloudForm) return "";
  const f = ui.topologyCloudForm;
  const preset = topologyCloudPresetByType(f.type) || {};
  const authModes = preset.authModes || ["apiKey"];
  const authModeOptions = authModes.map((m) =>
    `<option value="${escapeHtml(m)}"${m === f.authMode ? " selected" : ""}>${escapeHtml(m === "oauth" ? t("topologyCloudAuthOauth") : m === "noKey" ? t("clNoAuth") : t("topologyCloudAuthApiKey"))}</option>`
  ).join("");
  const oc = f.oauthConfig || {};
  const oauthFields = `
    <div class="cloud-span cloud-oauth-note">${escapeHtml(t("topologyCloudOauthHint"))}</div>
    <label class="cloud-span">Client ID<input type="text" data-cloud-field="oauthClientId" value="${escapeHtml(oc.clientId || "")}"></label>
    <label>Authorize URL<input type="text" data-cloud-field="oauthAuthorizeUrl" value="${escapeHtml(oc.authorizeUrl || "")}"></label>
    <label>Token URL<input type="text" data-cloud-field="oauthTokenUrl" value="${escapeHtml(oc.tokenUrl || "")}"></label>
    <label>Scope<input type="text" data-cloud-field="oauthScope" value="${escapeHtml(oc.scope || "")}"></label>
    <label>${escapeHtml(t("clRedirectPort"))}<input type="number" data-cloud-field="oauthRedirectPort" value="${escapeHtml(String(oc.redirectPort || 1455))}"></label>
    <div class="cloud-span cloud-oauth-actions"><button class="ghost-action" type="button" data-cloud-oauth-login>${escapeHtml(t("topologyCloudOauthLogin"))}</button>${f.oauthStatus ? `<span class="cloud-oauth-note">${escapeHtml(f.oauthStatus)}</span>` : ""}</div>
  `;
  const simpleOauthFields = `<div class="cloud-span cloud-oauth-note">${escapeHtml(t("poolConnectHint"))}</div>
    <div class="cloud-span cloud-oauth-actions"><button class="ghost-action" type="button" data-cloud-oauth-login>${escapeHtml(t("topologyCloudOauthLogin"))}</button>${f.oauthStatus ? `<span class="cloud-oauth-note">${escapeHtml(f.oauthStatus)}</span>` : ""}</div>`;
  const callbackFields = f.oauthLoginState ? `<div class="cloud-span cloud-oauth-note">${escapeHtml(t("oauthRemoteHint"))}</div>
    <label class="cloud-span">${escapeHtml(t("oauthCallbackUrl"))}<input type="password" autocomplete="off" data-cloud-field="oauthCallbackUrl" value="${escapeHtml(f.oauthCallbackUrl || "")}" placeholder="http://localhost:1455/auth/callback?…"></label>
    <div class="cloud-span cloud-oauth-actions"><a href="${escapeHtml(f.oauthAuthorizeUrl || "")}" target="_blank" rel="noopener noreferrer">${escapeHtml(t("topologyCloudOauthLogin"))}</a><button class="ghost-action" type="button" data-cloud-oauth-complete>${escapeHtml(t("oauthComplete"))}</button></div>` : "";
  const pickerMeta = CLOUD_PICKER_META[f.type] || {};
  const showAuthModeSelector = authModes.length > 1;
  const showBaseUrl = f.type !== "openai-subscription";
  const showKey = f.authMode === "apiKey";
  const title = f.isNew ? t("topologyCloudAccountModalTitleNew") : t("topologyCloudAccountModalTitleEdit");
  // For existing account editing: show current credential status + re-login / new key option
  const existingAcct = f.isNew ? null : (topology?.cloudAccounts || []).find((a) => a.id === f.accountId);
  const credSection = existingAcct ? `
    <div class="cloud-span cloud-acct-status">${escapeHtml(t("topologyCloudCredential"))}: <span class="cloud-key-line ${existingAcct.hasCredential ? "set" : "unset"}">${
      existingAcct.hasCredential
        ? (existingAcct.credentialKind === "noKey" ? "no auth" : existingAcct.credentialKind === "oauth" ? `OAuth${existingAcct.oauthEmail ? ` · ${escapeHtml(existingAcct.oauthEmail)}` : ""}` : t("topologyCloudKeySet", { last4: escapeHtml(existingAcct.keyLast4 || "") }))
        : escapeHtml(t("topologyCloudNeedsKey"))
    }</span></div>
    ${existingAcct.authMode === "oauth"
      ? `<div class="cloud-span cloud-oauth-actions"><button class="ghost-action" type="button" data-cloud-oauth-login>${escapeHtml(existingAcct.hasCredential ? t("topologyCloudOauthRelogin") : t("topologyCloudOauthLogin"))}</button>${f.oauthStatus ? `<span class="cloud-oauth-note">${escapeHtml(f.oauthStatus)}</span>` : ""}</div>`
      : existingAcct.authMode === "noKey" ? ""
      : `<label class="cloud-span">${escapeHtml(t("topologyCloudApiKey"))}<input type="password" data-cloud-field="apiKey" value="" placeholder="${escapeHtml(t("topologyCloudKeyPlaceholder"))}" autocomplete="off"></label>`}
  ` : "";
  return `
    <div class="topology-policy-overlay" data-topology-cloud-overlay>
      <div class="topology-policy-modal cloud-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
        <div class="topology-card-head">
          <strong>${escapeHtml(title)}</strong>
          <button class="icon-action compact" type="button" data-cloud-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
        </div>
        <div class="topology-policy-grid cloud-grid">
          <div class="cloud-span cloud-type-badge" style="--picker-accent:${escapeHtml(pickerMeta.color || "#94a3b8")}">
            <span class="cloud-type-badge-icon">${cloudPickerTileIcon(f.type)}</span>
            <span class="cloud-type-badge-name">${escapeHtml(preset.name || f.type)}</span>
            ${f.isNew && !f.poolId ? `<button class="ghost-action compact" type="button" data-cloud-picker-change>${escapeHtml(t("topologyCloudPickerChange"))}</button>` : ""}
          </div>
          <label class="cloud-span">${escapeHtml(t("topologyCloudName"))}<input type="text" data-cloud-field="name" value="${escapeHtml(f.name)}"></label>
          ${showBaseUrl ? `<label class="cloud-span">${escapeHtml(t("topologyCloudBaseUrl"))}<input type="text" data-cloud-field="baseUrl" value="${escapeHtml(f.baseUrl)}" placeholder="https://api.openai.com/v1"></label>` : ""}
          ${showAuthModeSelector ? `<label>${escapeHtml(t("topologyCloudAuthMode"))}<select data-cloud-field="authMode">${authModeOptions}</select></label>` : ""}
          ${f.isNew
            ? (showKey
                ? `<label class="cloud-span">${escapeHtml(t("topologyCloudApiKey"))}<input type="password" data-cloud-field="apiKey" value="" placeholder="${escapeHtml(t("topologyCloudKeyPlaceholder"))}" autocomplete="off"></label>`
                : f.authMode === "noKey" ? ""
                : f.poolId ? simpleOauthFields : oauthFields)
            : credSection}
          ${callbackFields}
          ${isSubscriptionAccount(existingAcct) ? codexVersionHtml() : ""}
        </div>
        <div class="topology-priority-actions cloud-actions">
          ${!f.isNew ? `<button class="ghost-action danger" type="button" data-cloud-delete-account>${escapeHtml(t("topologyCloudDeleteAccount"))}</button>` : ""}
          <button class="ghost-action" type="button" data-cloud-cancel>${escapeHtml(t("topologyCancel"))}</button>
          <button class="primary-mini-action" type="button" data-cloud-save${topologyCloudBusy ? " disabled" : ""}>${escapeHtml(t("topologySave"))}</button>
        </div>
      </div>
    </div>
  `;
}

export function renderTopologyCloudBlockModal() {
  if (!topologyCloudBlockModalOpen || !topologyCloudBlockForm) return "";
  const f = topologyCloudBlockForm;
  const account = (topology?.cloudAccounts || []).find((a) => a.id === f.accountId);
  const acctMeta = CLOUD_PICKER_META[account?.type || ""] || {};
  const title = f.isNew ? t("topologyCloudBlockModalTitleNew") : t("topologyCloudBlockModalTitleEdit");
  // The live endpoint list can lag (chatgpt.com gates models by the pinned
  // client_version) — union it with the models the account's blocks already use,
  // plus the block's current value, so anything known is always pickable. Models
  // that are NOT in the fetched list get a ⚠ suffix (provider no longer serves).
  const fetched = topologyCloudModelCache.get(f.accountId) || [];
  const fetchedIds = new Set(fetched.map((m) => m.id));
  const modelById = new Map();
  fetched.forEach((m) => { if (m.id) modelById.set(m.id, m); });
  (topology?.cloudProviders || []).filter((b) => b.accountId === f.accountId && b.model)
    .forEach((b) => { if (!modelById.has(b.model)) modelById.set(b.model, { id: b.model, name: b.model }); });
  if (f.model && !modelById.has(f.model)) modelById.set(f.model, { id: f.model, name: f.model });
  const models = [...modelById.values()].map((m) => (fetchedIds.size && !fetchedIds.has(m.id)
    ? { ...m, name: `${m.name || m.id} ⚠` }
    : m));
  // What the provider itself last reported for the picked model, shown as the
  // input's placeholder: the operator sees the number that will be advertised
  // if they type nothing, instead of guessing whether anything is known.
  const providerWindow = modelById.get(f.model)?.contextLength || 0;
  return `
    <div class="topology-policy-overlay" data-topology-cloud-block-overlay>
      <div class="topology-policy-modal cloud-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}">
        <div class="topology-card-head">
          <strong>${escapeHtml(title)}</strong>
          <button class="icon-action compact" type="button" data-cloud-block-close aria-label="${escapeHtml(t("topologyClose"))}">×</button>
        </div>
        <div class="topology-policy-grid cloud-grid">
          ${account ? `<div class="cloud-span cloud-type-badge" style="--picker-accent:${escapeHtml(acctMeta.color || "#94a3b8")}">
            <span class="cloud-type-badge-icon">${cloudPickerTileIcon(account.type || "")}</span>
            <span class="cloud-type-badge-name">${escapeHtml(account.name || account.id)}</span>
          </div>` : ""}
          <label>${escapeHtml(t("topologyCloudModel"))}${models.length
            ? `<select data-block-field="model">${models.map((m) => `<option value="${escapeHtml(m.id)}"${m.id === f.model ? " selected" : ""}>${escapeHtml(m.name || m.id)}</option>`).join("")}</select>`
            : `<input type="text" data-block-field="model" value="${escapeHtml(f.model)}" placeholder="gpt-4o-mini">`}</label>
          ${models.length ? `<label>${escapeHtml(t("topologyCloudModelCustom"))}<input type="text" data-block-field-custom placeholder="gpt-5.2"></label>` : ""}
          <label title="${escapeHtml(t("topologyCloudContextHint"))}">${escapeHtml(t("topologyCloudContextLength"))}<input type="number" min="1" step="1" data-block-field="contextLength" value="${escapeHtml(f.contextLength)}" placeholder="${escapeHtml(t("topologyCloudContextEmpty"))}"></label>
          <div class="cloud-span cloud-ctx-reported" data-t="cloud-context-reported">
            <span class="topology-muted">${escapeHtml(t("topologyCloudContextReported"))}</span>
            <b>${escapeHtml(providerWindow ? String(providerWindow) : t("topologyCloudContextAuto"))}</b>
          </div>
          <label class="cloud-span cloud-expose-line" title="${escapeHtml(t("topologyCloudContextAutoHint"))}"><input type="checkbox" data-block-field-context-auto${f.contextAuto ? " checked" : ""}> ${escapeHtml(t("topologyCloudContextAutoUse"))}</label>
          <label>${escapeHtml(t("topologyCloudModelMode"))}<select data-block-field="modelMode">
            <option value="rewrite"${(f.modelMode || "rewrite") !== "passthrough" ? " selected" : ""}>${escapeHtml(t("topologyCloudModelRewrite"))}</option>
            <option value="passthrough"${(f.modelMode || "rewrite") === "passthrough" ? " selected" : ""}>${escapeHtml(t("topologyCloudModelPassthrough"))}</option>
          </select></label>
          ${f.isNew
            ? `<label class="cloud-expose-line"><input type="checkbox" data-block-field-expose checked> ${escapeHtml(t("topologyCloudExposeNew"))}</label>`
            : `<label>${escapeHtml(t("topologyCloudBlockId"))}<input type="text" value="${escapeHtml(f.blockId)}" disabled title="${escapeHtml(t("topologyCloudBlockIdHint"))}"></label>`}
        </div>
        <div class="topology-priority-actions cloud-actions">
          ${!f.isNew ? `<button class="ghost-action danger" type="button" data-cloud-delete-block>${escapeHtml(t("topologyCloudDeleteBlock"))}</button>` : ""}
          <button class="ghost-action" type="button" data-cloud-block-cancel>${escapeHtml(t("topologyCancel"))}</button>
          <button class="primary-mini-action" type="button" data-cloud-block-save${topologyCloudBusy ? " disabled" : ""}>${escapeHtml(t("topologySave"))}</button>
        </div>
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
      // An edit sends what changed: the name, the address, how it signs in.
      // It used to send nothing and still say "saved".
      const stored = (topology?.cloudAccounts || []).find((a) => a.id === accountId) || {};
      const changed = ["name", "baseUrl", "authMode"].some((k) => String(f[k] ?? "") !== String(stored[k] ?? ""));
      if (changed) {
        if (!/^https?:\/\//.test(f.baseUrl || "")) { toast("base URL must be http(s)"); topologyCloudBusy = false; renderTopology(); return; }
        const editRes = await api("/api/cloud-accounts/save", {
          method: "POST",
          body: JSON.stringify({ account: { id: accountId, type: f.type, name: f.name, baseUrl: f.baseUrl, authMode: f.authMode } }),
        });
        if (editRes.topology) setTopology(editRes.topology);
      }
    }
    if (f.isNew) {
      const preset = topologyCloudPresetByType(f.type) || {};
      const resolvedUrl = f.baseUrl || preset.baseUrl || "";
      if (!/^https?:\/\//.test(resolvedUrl)) { toast("base URL must be http(s)"); topologyCloudBusy = false; renderTopology(); return; }
      const taken = (topology?.cloudAccounts || []).map((a) => a.id);
      accountId = topologyCloudUniqueId(topologyCloudSlug(f.name || f.type), taken);
      const acctRes = await api(f.poolId ? "/api/cloud-pools/connect-account" : "/api/cloud-accounts/save", {
        method: "POST",
        body: JSON.stringify({ ...(f.poolId ? { poolId: f.poolId } : {}), account: { id: accountId, type: f.type, name: f.name, baseUrl: resolvedUrl, authMode: f.authMode, accountType: preset.accountType || "" } }),
      });
      if (acctRes.topology) setTopology(acctRes.topology);
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
    const wasNew = f.isNew;
    const acctType = f.type || "";
    const isSubscription = acctType === "openai-subscription";
    // Any new account with credentials: try to auto-fetch its model list from the
    // provider (subscription via codex/models; others via GET /models). Errors are
    // caught below, so providers that don't support listing just stay empty.
    const autoCreate = wasNew && !f.poolId;
    if (autoCreate) {
      try {
        const acRes = await api("/api/cloud-accounts/auto-create-blocks", {
          method: "POST",
          body: JSON.stringify({ id: accountId }),
        });
        if (acRes.topology) setTopology(acRes.topology);
        toast(acRes.created > 0
          ? `${t("topologyCloudSaved")} · ${acRes.created} model${acRes.created !== 1 ? "s" : ""} added`
          : t("topologyCloudSaved"));
      } catch (e) {
        toast(`${t("topologyCloudSaved")} · models: ${e.message || "fetch failed"}`);
      }
      closeCloudProviderModal();
    } else {
      toast(t("topologyCloudSaved"));
      closeCloudProviderModal();
      if (wasNew && !f.poolId) openCloudBlockModal(null, accountId);
    }
  } catch (err) {
    toast(err.message);
    topologyCloudBusy = false;
    renderTopology();
  }
}

export async function saveCloudBlock() {
  if (!topologyCloudBlockForm) return;
  const f = topologyCloudBlockForm;
  // Read the model/mode straight from the DOM: an untouched <select> shows its first
  // option but never fires a change event, so f.model would otherwise stay empty and
  // the block would render as "—".
  const modelEl = document.querySelector('[data-block-field="model"]');
  if (modelEl && modelEl.value) f.model = modelEl.value;
  // Free-text escape hatch: a model the upstream list no longer serves (e.g.
  // retired from the pinned client_version) is otherwise unpickable.
  const customModel = (document.querySelector("[data-block-field-custom]")?.value || "").trim();
  if (customModel) f.model = customModel;
  const modeEl = document.querySelector('[data-block-field="modelMode"]');
  if (modeEl && modeEl.value) f.modelMode = modeEl.value;
  // Left blank = "I state nothing", which is not the same as zero: the server
  // drops the key entirely. Nothing takes its place unless the switch below is
  // ticked — a window nobody chose is the trap this codebase keeps returning to.
  f.contextLength = (document.querySelector('[data-block-field="contextLength"]')?.value || "").trim();
  f.contextAuto = !!document.querySelector("[data-block-field-context-auto]")?.checked;
  const exposeNew = !!document.querySelector("[data-block-field-expose]")?.checked;
  if (!f.model) { toast("Pick a model first"); return; }
  // Editing an existing block to another model keeps its id (and every cb:<id>
  // reference) but silently rewires them — exactly how terra once became a
  // second sol. Make that an explicit decision.
  if (!f.isNew && f.origModel && f.model !== f.origModel) {
    if (!(await appConfirm(t("topologyCloudModelChangeWarn", { id: f.blockId, from: f.origModel, to: f.model })))) return;
  }
  // A second block for the same model is almost always a mis-click, not intent.
  if (f.isNew && (topology?.cloudProviders || []).some((b) => b.accountId === f.accountId && b.model === f.model)) {
    if (!(await appConfirm(t("topologyCloudDupBlockWarn", { model: f.model })))) return;
  }
  topologyCloudBusy = true;
  renderTopology();
  try {
    const blockId = f.isNew
      ? topologyCloudUniqueId(topologyCloudSlug(f.model || f.accountId), (topology?.cloudProviders || []).map((b) => b.id))
      : f.blockId;
    const blockRes = await api("/api/cloud-blocks/save", {
      method: "POST",
      body: JSON.stringify({ block: { id: blockId, accountId: f.accountId, name: f.model || blockId, model: f.model, modelMode: f.modelMode || "rewrite",
        // Both always sent, blank included: clearing the field must REMOVE a
        // stated window, and unticking the switch must turn it off, rather than
        // leaving what was there standing.
        contextLength: f.contextLength || "",
        contextAuto: !!f.contextAuto,
        ...(f.isNew ? { exposed: exposeNew } : {}) } }),
    });
    if (blockRes.topology) setTopology(blockRes.topology);
    toast(t("topologyCloudSaved"));
  } catch (err) {
    toast(err.message);
  }
  topologyCloudBusy = false;
  closeCloudBlockModal();
}

export async function deleteCloudBlock() {
  if (!topologyCloudBlockForm?.blockId) return;
  try {
    const res = await api("/api/cloud-blocks/delete", {
      method: "POST",
      body: JSON.stringify({ id: topologyCloudBlockForm.blockId }),
    });
    if (res.topology) setTopology(res.topology);
  } catch (err) {
    toast(err.message);
  }
  closeCloudBlockModal();
}

export async function startCloudOauthLogin() {
  const f = ui.topologyCloudForm;
  if (!f) return;
  let accountId = f.accountId;
  if (f.isNew) {
    const preset = topologyCloudPresetByType(f.type) || {};
    const resolvedUrl = f.baseUrl || preset.baseUrl || "";
    if (!/^https?:\/\//.test(resolvedUrl)) { toast("base URL must be http(s)"); return; }
    const taken = (topology?.cloudAccounts || []).map((a) => a.id);
    accountId = topologyCloudUniqueId(topologyCloudSlug(f.name || f.type), taken);
    const res = await api(f.poolId ? "/api/cloud-pools/connect-account" : "/api/cloud-accounts/save", {
      method: "POST",
      body: JSON.stringify({ ...(f.poolId ? { poolId: f.poolId } : {}), account: { id: accountId, type: f.type, name: f.name, baseUrl: resolvedUrl, authMode: "oauth", accountType: preset.accountType || "", oauthConfig: f.oauthConfig || {} } }),
    });
    if (res.topology) setTopology(res.topology);
    f.isNew = false;
    f.accountId = accountId;
  }
  if (!accountId) { toast("pick or create an account"); return; }
  f.oauthStatus = t("topologyCloudOauthOpening");
  renderTopology();
  const started = await api("/api/cloud-accounts/oauth/start", {
    method: "POST",
    body: JSON.stringify({ id: accountId }),
  });
  if (!started.authorizeUrl) { toast("oauth start failed"); return; }
  f.oauthLoginState = started.state;
  f.oauthAuthorizeUrl = started.authorizeUrl;
  renderTopology();
  window.open(started.authorizeUrl, "_blank", "noopener");
  pollCloudOauth(started.state);
}

export async function completeCloudOauthLogin() {
  const f = ui.topologyCloudForm;
  if (!f?.oauthLoginState || !f.oauthCallbackUrl) return;
  try {
    const res = await api("/api/cloud-accounts/oauth/complete", { method: "POST", body: JSON.stringify({ state: f.oauthLoginState, callbackUrl: f.oauthCallbackUrl }) });
    f.oauthCallbackUrl = "";
    if (res.topology) setTopology(res.topology);
    if (res.state === "done") { f.oauthLoginState = ""; f.oauthStatus = t("topologyCloudOauthDone"); }
    else f.oauthStatus = `${t("topologyCloudOauthFail")}: ${res.error || ""}`;
    renderTopology();
  } catch (err) { toast(err.message); }
}

export function pollCloudOauth(state, attempt = 0) {
  if (!ui.topologyCloudModalOpen) return;
  if (attempt > 150) {
    if (ui.topologyCloudForm) { ui.topologyCloudForm.oauthStatus = t("topologyCloudOauthTimeout"); renderTopology(); }
    return;
  }
  api(`/api/cloud-accounts/oauth/status?state=${encodeURIComponent(state)}`).then((res) => {
    if (!ui.topologyCloudModalOpen || !ui.topologyCloudForm) return;
    if (res.state === "done") {
      if (res.topology) setTopology(res.topology);
      ui.topologyCloudForm.oauthLoginState = "";
      ui.topologyCloudForm.oauthCallbackUrl = "";
      ui.topologyCloudForm.oauthStatus = t("topologyCloudOauthDone") + (res.email ? ` · ${res.email}` : "");
      renderTopology();
      toast(t("topologyCloudOauthDone"));
      return;
    }
    if (res.state === "error") {
      ui.topologyCloudForm.oauthStatus = `${t("topologyCloudOauthFail")}: ${res.error || ""}`;
      renderTopology();
      return;
    }
    setTimeout(() => pollCloudOauth(state, attempt + 1), 2000);
  }).catch(() => setTimeout(() => pollCloudOauth(state, attempt + 1), 2000));
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
  } catch (err) {
    toast(err.message);
  }
  closeCloudProviderModal();
}
