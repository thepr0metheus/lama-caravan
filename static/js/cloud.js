// Cloud provider accounts/blocks modals and OAuth login flow.
import { badge, option } from "./form.js";
import { t } from "./i18n.js";
import { formatPricePer1M, modelPricing } from "./model-meta.js";
import { action } from "./polling.js";
import { nextTopologyCellPort } from "./remote-cells.js";
import { setTopology, state, topology, ui } from "./state.js";
import { refreshTopology, renderTopology } from "./topology-render.js";
import {
  apiCostsCache,
  apiCostsHtml,
  fetchApiCosts,
  fetchOpenRouterLimits,
  fetchProxySpend,
  fetchSubscriptionUsage,
  openrouterLimitsCache,
  openRouterLimitsHtml,
  proxySpendFetchedAt,
  proxySpendHtml,
  subscriptionUsageCache,
  subscriptionUsageHtml,
} from "./usage-stats.js";
import { appConfirm } from "./dialogs.js";
import { $, api, copyText, escapeHtml, pill, toast } from "./utils.js";

export let topologyCloudBlockModalOpen = false;
export let topologyCloudBlockForm = null;
export let topologyCloudBusy = false;
export const topologyCloudModelCache = new Map(); // accountId → models[], fetched once at page load
// Provider-card controls via DELEGATION on the permanent container: the lane's
// children are replaced by several independent paths (full renderTopology, the
// usage/pricing fetch callbacks, the flyout toggle) — per-node listeners bound
// by bindTopologyDragAndDrop died with the old nodes whenever a callback-path
// re-render ran, leaving dead buttons. One listener on the container survives
// every innerHTML swap.
function bindCloudCardDelegates(cpEl) {
  if (cpEl.dataset.delegated) return;
  cpEl.dataset.delegated = "1";
  cpEl.addEventListener("click", async (e) => {
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
    const fetchBtn = e.target.closest("[data-cloud-fetch-models]");
    if (fetchBtn) {
      e.stopPropagation();
      const id = fetchBtn.dataset.cloudFetchModels;
      fetchBtn.textContent = t("fetchingModels"); fetchBtn.disabled = true;
      try {
        const res = await api("/api/cloud-accounts/auto-create-blocks", { method: "POST", body: JSON.stringify({ id }) });
        if (res.topology) setTopology(res.topology);
        toast(res.created > 0 ? `${res.created} model${res.created !== 1 ? "s" : ""} added (${res.total} available)` : `models up to date (${res.total} available)`);
        renderTopology();
      } catch (err) { toast(`fetch failed: ${err.message}`); fetchBtn.textContent = t("fetchModelsBtn"); fetchBtn.disabled = false; }
      return;
    }
    const mint = e.target.closest("[data-bridge-mint]");
    if (mint) {
      e.stopPropagation();
      const sel = cpEl.querySelector(`select[data-bridge-block="${mint.dataset.bridgeMint}"]`);
      const blockId = sel?.value;
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
      e.stopPropagation();
      if (!(await appConfirm(t("cloudBridgeDeleteConfirm", { port: del.dataset.bridgeDelete })))) return;
      try {
        await api("/api/cloud-accounts/bridge-port-delete", { method: "POST", body: JSON.stringify({ port: Number(del.dataset.bridgeDelete) }) });
        await refreshTopology();
        renderTopology();
      } catch (err) { toast(err.message); }
      return;
    }
    const row = e.target.closest("[data-cloud-block]");
    if (row) openCloudBlockModal(row.dataset.cloudBlock, null);
  });
  cpEl.addEventListener("change", (e) => {
    const sel = e.target.closest("select[data-bridge-block]");
    // Unsaved choice — survives the poll-tick rebuilds (the render below puts
    // the selected attribute back from ui state).
    if (sel) (ui.bridgeBlockChoice ||= {})[sel.dataset.bridgeBlock] = sel.value;
  });
  cpEl.addEventListener("keydown", (e) => {
    const row = e.target.closest("[data-cloud-block]");
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
  // The mint button shows the next fleet-wide port — any cell/port change must re-render.
  const key = JSON.stringify(accounts) + JSON.stringify(blocks) + usageKeys + pricingKey
    + `:ps${proxySpendFetchedAt}:br${bridgesKey}:np${nextTopologyCellPort()}`;
  if (key === ui._lastCloudProvidersKey) return;
  ui._lastCloudProvidersKey = key;
  const addCloudBtn = `<button class="topology-add-wide-btn" type="button" data-topo-add-cloud>${escapeHtml(t("clAddProvider"))}</button>`;
  const cpEl = $("topologyCloudProviders");
  if (!cpEl) return;
  bindCloudCardDelegates(cpEl);
  if (!accounts.length) {
    cpEl.innerHTML = `<article class="topology-card"><div class="topology-muted">${escapeHtml(t("topologyCloudNoProviders"))}</div></article>${addCloudBtn}`;
    return;
  }
  cpEl.innerHTML = accounts.map((acct) => {
    const acctBlocks = blocks
      .filter((b) => b.accountId === acct.id)
      .sort((a, b) => String(b.model || b.name || b.id)
        .localeCompare(String(a.model || a.name || a.id), undefined, { numeric: true, sensitivity: "base" }));
    const isSubscription = acct.accountType === "openai-subscription" || String(acct.baseUrl || "").includes("chatgpt.com");
    const credLine = acct.hasCredential
      ? (acct.credentialKind === "noKey"
          ? "no auth"
          : acct.credentialKind === "oauth"
              ? (isSubscription ? "ChatGPT Plus" : `OAuth${acct.oauthEmail ? ` · ${escapeHtml(acct.oauthEmail)}` : ""}`)
              : t("topologyCloudKeySet", { last4: acct.keyLast4 || "" }))
      : t("topologyCloudNeedsKey");
    const iconType = isSubscription ? "openai-subscription" : (acct.type || "");
    const meta = CLOUD_PICKER_META[iconType] || CLOUD_PICKER_META[acct.type || ""] || {};
    const blockRows = acctBlocks.map((b) => {
      const p = modelPricing[b.model || ""] || null;
      const pricingHtml = p
        ? `<span class="cloud-block-pricing">${formatPricePer1M(p.inputPer1M)} / ${formatPricePer1M(p.outputPer1M)} /1M</span>`
        : "";
      return `
      <div class="cloud-block-row" data-cloud-block="${escapeHtml(b.id)}" role="button" tabindex="0" title="${escapeHtml(b.model || b.id)}">
        <span class="cloud-block-model">${escapeHtml(b.model || "—")}</span>
        ${pricingHtml}
      </div>
      `;
    }).join("");
    // Usage/spend panel (fetched async). Subscription → ChatGPT Plus limits/credits;
    // OpenRouter → key limits via /auth/key; API accounts → official spend via Costs API.
    const isOpenRouter = acct.type === "openrouter" || String(acct.baseUrl || "").includes("openrouter.ai");
    // The Costs API (/organization/costs) exists only on api.openai.com — for
    // other providers (Ollama, Anthropic, generic) the probe just 404s, so
    // don't fire it; the local proxy spend-meter below covers them.
    const hasCostsApi = acct.type === "openai" || String(acct.baseUrl || "").includes("api.openai.com");
    let usagePanel = "";
    if (acct.hasCredential) {
      if (isSubscription) { fetchSubscriptionUsage(acct.id); usagePanel = subscriptionUsageHtml(acct.id); }
      else if (isOpenRouter) { fetchOpenRouterLimits(acct.id); usagePanel = openRouterLimitsHtml(acct.id); }
      else if (hasCostsApi) { fetchApiCosts(acct.id); usagePanel = apiCostsHtml(acct.id); }
    }
    // Local proxy spend-meter (our token counts × pricing) — for every cloud account.
    fetchProxySpend();
    usagePanel += proxySpendHtml(acct.id);
    // Bridge ports: OpenAI-compatible entry points for EXTERNAL consumers
    // (a voice app, an IDE plugin, …) pinned to one of this account's model blocks. Not agents:
    // kind="service" routes never join the kanban graph.
    const blockById = new Map(acctBlocks.map((b) => [b.id, b]));
    const bridges = (topology?.proxies || [])
      .filter((p) => p.kind === "service" && blockById.has(p.providerId))
      .sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
    const bridgeRows = bridges.map((p) => {
      const model = blockById.get(p.providerId)?.model || p.providerId;
      const url = `http://${location.hostname}:${p.port}`;
      const mp = modelPricing[model];
      const priceHtml = String(model).endsWith(":free")
        ? `<span class="cloud-bridge-price free">FREE</span>`
        : (mp && (mp.inputPer1M || mp.outputPer1M))
          ? `<span class="cloud-bridge-price">${formatPricePer1M(mp.inputPer1M)}/${formatPricePer1M(mp.outputPer1M)}</span>`
          : "";
      return `<div class="cloud-bridge-row">
        <code class="cloud-bridge-port">:${escapeHtml(String(p.port))}</code>
        <span class="cloud-bridge-model" title="${escapeHtml(`${p.label || ""} → ${model}`)}">→ ${escapeHtml(model)}</span>
        ${priceHtml}
        <button class="icon-action compact" type="button" data-bridge-copy="${escapeHtml(url)}" title="${escapeHtml(t("cloudBridgeCopy"))}">⧉</button>
        <button class="icon-action compact" type="button" data-bridge-delete="${escapeHtml(String(p.port))}" title="${escapeHtml(t("cloudBridgeDelete"))}">✕</button>
      </div>`;
    }).join("");
    // The board fully re-renders on poll ticks — an unsaved dropdown choice
    // must live in ui state or every rebuild would reset it to the first row.
    const chosenBlock = ui.bridgeBlockChoice?.[acct.id] || "";
    // Native <option> can't carry styled tags, but plain text works — append
    // the $in/$out price (or FREE) so the price is visible right in the picker.
    const bridgeOptions = acctBlocks
      .map((b) => {
        const model = b.model || b.name || b.id;
        const mp = modelPricing[b.model || ""];
        const suffix = String(b.model || "").endsWith(":free") ? " · FREE"
          : (mp && (mp.inputPer1M || mp.outputPer1M))
            ? ` · ${formatPricePer1M(mp.inputPer1M)}/${formatPricePer1M(mp.outputPer1M)}`
            : "";
        return `<option value="${escapeHtml(b.id)}"${b.id === chosenBlock ? " selected" : ""}>${escapeHtml(model + suffix)}</option>`;
      }).join("");
    // Same ghost styling and "next free port" promise as the Reserve-cell
    // card — bridges and cells share the fleet-wide numbering.
    const nextBridgePort = nextTopologyCellPort();
    const bridgePanel = acct.hasCredential && acctBlocks.length ? `
      <div class="cloud-bridges">
        <div class="cloud-bridges-head" title="${escapeHtml(t("cloudBridgeHint"))}">${escapeHtml(t("cloudBridgePorts"))}</div>
        ${bridgeRows}
        <div class="cloud-bridge-add">
          <select class="cloud-bridge-block" data-bridge-block="${escapeHtml(acct.id)}" title="${escapeHtml(t("cloudBridgeHint"))}">${bridgeOptions}</select>
          <button class="ghost-start-btn cloud-bridge-ghost-btn" type="button" data-bridge-mint="${escapeHtml(acct.id)}" title="${escapeHtml(t("cloudBridgeOpen"))}">＋ ${escapeHtml(t("cloudBridgeReserveLabel"))} :${escapeHtml(String(nextBridgePort))}</button>
        </div>
      </div>` : "";
    usagePanel += bridgePanel;
    // One cable handle per PROVIDER (account). The router output attaches here;
    // the actual model is chosen inside the router. The model list is hidden until
    // hover (slide-out flyout with prices).
    const modelsOpen = !!ui.cloudModelsOpen?.[acct.id];
    return `
      <article class="topology-card cloud-account-card ${acct.hasCredential ? "configured" : "needs-key"}${modelsOpen ? " models-open" : ""}">
        <span class="topology-handle server-input cloud-account-input" data-topology-cloud-input="1" data-account-id="${escapeHtml(acct.id)}" title="${escapeHtml(t("clTitleRouterOutput"))}"></span>
        <div class="cloud-account-head">
          <span class="cloud-account-icon" style="color:${escapeHtml(meta.color || "#94a3b8")}">${cloudPickerTileIcon(iconType)}</span>
          <strong class="cloud-account-name">${escapeHtml(acct.name || acct.id)}</strong>
          ${acct.hasCredential ? pill(isSubscription ? "Plus" : acct.credentialKind === "noKey" ? t("clReady") : acct.credentialKind === "apiKey" ? t("topologyCloudConfigured") : "OAuth", "good") : pill(t("topologyCloudNeedsKey"), "warn")}
          <button class="icon-action compact" type="button" data-cloud-edit-account="${escapeHtml(acct.id)}" title="${escapeHtml(t("clTitleEditAccount"))}">⚙</button>
        </div>
        <div class="cloud-key-line ${acct.hasCredential ? "set" : "unset"}">${escapeHtml(credLine)}</div>
        ${usagePanel}
        <button class="cloud-models-toggle-row" type="button" data-cloud-models-toggle="${escapeHtml(acct.id)}">
          ${modelsOpen ? `${escapeHtml(t("cloudModelsHide"))} ⌃` : `${escapeHtml(t("cloudModelsShowAll", { n: String(acctBlocks.length) }))} ⌄`}
        </button>
        <div class="cloud-models-flyout">
          ${blockRows ? `<div class="cloud-account-blocks">${blockRows}</div>` : `<div class="topology-muted" style="font-size:11px">${t("clNoModelsYet")}</div>`}
          <button class="cloud-add-model-btn" type="button" data-cloud-fetch-models="${escapeHtml(acct.id)}" title="${escapeHtml(t("clTitleFetchModels"))}">${escapeHtml(t("fetchModelsBtn"))}</button>
          <button class="cloud-add-model-btn" type="button" data-cloud-add-block="${escapeHtml(acct.id)}">＋ ${escapeHtml(t("topologyCloudBlockModalTitleNew"))}</button>
        </div>
      </article>
    `;
  }).join("") + addCloudBtn;
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

export function selectCloudProviderType(type) {
  const preset = topologyCloudPresetByType(type) || {};
  ui.topologyCloudPickerOpen = false;
  ui.topologyCloudForm = {
    isNew: true,
    accountId: "",
    type,
    name: preset.name || "",
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
    modelMode: block?.modelMode || "rewrite",
  };
  topologyCloudBlockModalOpen = true;
  renderTopology();
  const resolvedAccountId = topologyCloudBlockForm.accountId;
  const acct = (topology?.cloudAccounts || []).find((a) => a.id === resolvedAccountId);
  if (acct && acct.hasCredential) {
    if ((acct.accountType || "") === "openai-subscription" || String(acct.baseUrl || "").includes("chatgpt.com")) {
      fetchCloudSubscriptionModels(resolvedAccountId);
    } else {
      fetchCloudAccountModels(resolvedAccountId);
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

export async function fetchCloudSubscriptionModels(accountId) {
  if (!accountId || topologyCloudModelCache.has(accountId)) return;
  topologyCloudModelCache.set(accountId, []); // mark as in-flight to avoid duplicate requests
  try {
    const res = await api(`/api/cloud-accounts/subscription-models?id=${encodeURIComponent(accountId)}`);
    if (res.ok && Array.isArray(res.models)) {
      topologyCloudModelCache.set(accountId, res.models);
      renderTopology();
    }
  } catch (_) { /* silent */ }
}

export async function fetchCloudAccountModels(accountId) {
  if (!accountId || topologyCloudModelCache.has(accountId)) return;
  topologyCloudModelCache.set(accountId, []); // mark as in-flight
  try {
    const res = await api(`/api/cloud-accounts/models?id=${encodeURIComponent(accountId)}`);
    if (res.ok && Array.isArray(res.models)) {
      topologyCloudModelCache.set(accountId, res.models);
      renderTopology();
    }
  } catch (_) { /* silent */ }
}

export function prefetchAllSubscriptionModels() {
  const accounts = topology?.cloudAccounts || [];
  accounts.forEach((acct) => {
    if ((acct.accountType || "") === "openai-subscription" || String(acct.baseUrl || "").includes("chatgpt.com")) {
      fetchCloudSubscriptionModels(acct.id);
    } else if (acct.hasCredential) {
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
            ${f.isNew ? `<button class="ghost-action compact" type="button" data-cloud-picker-change>${escapeHtml(t("topologyCloudPickerChange"))}</button>` : ""}
          </div>
          <label class="cloud-span">${escapeHtml(t("topologyCloudName"))}<input type="text" data-cloud-field="name" value="${escapeHtml(f.name)}"></label>
          ${showBaseUrl ? `<label class="cloud-span">${escapeHtml(t("topologyCloudBaseUrl"))}<input type="text" data-cloud-field="baseUrl" value="${escapeHtml(f.baseUrl)}" placeholder="https://api.openai.com/v1"></label>` : ""}
          ${showAuthModeSelector ? `<label>${escapeHtml(t("topologyCloudAuthMode"))}<select data-cloud-field="authMode">${authModeOptions}</select></label>` : ""}
          ${f.isNew
            ? (showKey
                ? `<label class="cloud-span">${escapeHtml(t("topologyCloudApiKey"))}<input type="password" data-cloud-field="apiKey" value="" placeholder="${escapeHtml(t("topologyCloudKeyPlaceholder"))}" autocomplete="off"></label>`
                : f.authMode === "noKey" ? ""
                : oauthFields)
            : credSection}
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
  // plus the block's current value, so anything known is always pickable.
  const modelById = new Map();
  (topologyCloudModelCache.get(f.accountId) || []).forEach((m) => { if (m.id) modelById.set(m.id, m); });
  (topology?.cloudProviders || []).filter((b) => b.accountId === f.accountId && b.model)
    .forEach((b) => { if (!modelById.has(b.model)) modelById.set(b.model, { id: b.model, name: b.model }); });
  if (f.model && !modelById.has(f.model)) modelById.set(f.model, { id: f.model, name: f.model });
  const models = [...modelById.values()];
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
          <label>${escapeHtml(t("topologyCloudModelMode"))}<select data-block-field="modelMode">
            <option value="rewrite"${(f.modelMode || "rewrite") !== "passthrough" ? " selected" : ""}>${escapeHtml(t("topologyCloudModelRewrite"))}</option>
            <option value="passthrough"${(f.modelMode || "rewrite") === "passthrough" ? " selected" : ""}>${escapeHtml(t("topologyCloudModelPassthrough"))}</option>
          </select></label>
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
    if (f.isNew) {
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
    const autoCreate = wasNew;
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
      if (wasNew) openCloudBlockModal(null, accountId);
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
  if (!f.model) { toast("Pick a model first"); return; }
  topologyCloudBusy = true;
  renderTopology();
  try {
    const blockId = f.isNew
      ? topologyCloudUniqueId(topologyCloudSlug(f.model || f.accountId), (topology?.cloudProviders || []).map((b) => b.id))
      : f.blockId;
    const blockRes = await api("/api/cloud-blocks/save", {
      method: "POST",
      body: JSON.stringify({ block: { id: blockId, accountId: f.accountId, name: f.model || blockId, model: f.model, modelMode: f.modelMode || "rewrite" } }),
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
    const res = await api("/api/cloud-accounts/save", {
      method: "POST",
      body: JSON.stringify({ account: { id: accountId, type: f.type, name: f.name, baseUrl: resolvedUrl, authMode: "oauth", accountType: preset.accountType || "", oauthConfig: f.oauthConfig || {} } }),
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
  window.open(started.authorizeUrl, "_blank", "noopener");
  pollCloudOauth(started.state);
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

