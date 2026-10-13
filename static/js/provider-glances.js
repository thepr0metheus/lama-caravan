// The cloud providers on the main board (the owner, 2026-10-12): under the machines, each provider a
// block of its accounts — ChatGPT subscriptions, OpenRouter, the OpenAI API… "＋ Add cloud provider"
// puts an empty provider here (the picker, cloud.js); the "＋" at the foot of its block adds an
// account to it — a subscription goes straight to its sign-in code, a key provider asks for the key —
// and the same sign-in may be added again. An empty provider is taken off by its ✕. Which account
// stands under which provider is the controller's word (`boardProviders`,
// caravan/admin/board_providers.py): the board works none of it out.
//
// An account is one row: its name, whether it can serve, a subscription's windows as last read with
// the small "↺ N" that opens the window of saved resets, an API key's spend through the caravan, a
// tripped endpoint; ⚙ opens its window, where the rest of it stands. Never its models: those are the
// kanban's (pool-board.js), where a pool's rows are cabled to them.
//
// The kanban's card on this board is cabled to the machines and the accounts its pools lead to
// (`PoolReach`, cables.js): a cable says requests can go there.
import {
  CLOUD_PICKER_META,
  cloudApiIssuesHtml,
  cloudPickerTileIcon,
  cloudProviderName,
  connectAccount,
  openCloudAccountModal,
  openCloudPicker,
  removeBoardProvider,
} from "./cloud.js";
import { t } from "./i18n.js";
import { PoolCards } from "./pools.js";
import { topology } from "./state.js";
import { SubscriptionResetCards } from "./subscription-resets.js";
import { machineAt } from "./topology-nodes.js";
import {
  READING_LANDED,
  fetchProxySpend,
  fetchSubscriptionUsage,
  proxySpendHtml,
  refreshUsageReading,
  subscriptionUsageHtml,
} from "./usage-stats.js";
import { escapeHtml } from "./utils.js";

// Where the kanban's pools lead: the accounts their rows call, and the machines whose cells they
// call. A row of a local model names its output ("srv:<port>", "eng:<id>"); the router's outputs say
// where that output answers, and machineAt(that address) names the machine — the rule the kanban's
// machine rows go by. A row switched off leads nowhere, and neither does a row whose output is gone:
// no request can go there, so no cable says one can.
export class PoolReach {
  static of(top = topology, machineOf = (address) => machineAt(address).key) {
    const outputs = new Map();
    for (const router of top?.routers || []) {
      for (const out of router?.outputs || []) if (out?.id && !outputs.has(out.id)) outputs.set(out.id, out);
    }
    const accounts = [];
    const machines = new Map();
    for (const pool of top?.pools || []) {
      for (const row of pool?.steps || []) {
        if (!row || row.enabled === false) continue;
        if (row.kind === "account" && row.accountId) {
          if (!accounts.includes(row.accountId)) accounts.push(row.accountId);
        } else if (row.kind === "output" && row.output) {
          const out = outputs.get(row.output);
          if (!out || String(out.upstreamType || "llama") === "cloud") continue;
          const key = String(machineOf(out.upstreamHost || "127.0.0.1"));
          if (!machines.has(key)) machines.set(key, []);
          if (!machines.get(key).includes(row.output)) machines.get(key).push(row.output);
        }
      }
    }
    return { accounts, machines: [...machines].map(([key, outs]) => ({ key, outputs: outs })) };
  }
}

export class ProviderGlances {
  // The provider a ChatGPT subscription stands under (BoardProviders.SUBSCRIPTION): its block says
  // "subscriptions", and its "＋" signs one in.
  static SUBSCRIPTION = "openai-subscription";

  constructor({ readUsage = (owner) => Promise.resolve(fetchSubscriptionUsage(owner)).catch(() => {}),
    readSpend = () => Promise.resolve(fetchProxySpend()).catch(() => {}),
    edit = openCloudAccountModal, add = () => openCloudPicker(), connect = connectAccount, remove = removeBoardProvider,
    resets = null, landed = READING_LANDED } = {}) {
    this.readUsage = readUsage;
    this.readSpend = readSpend;
    this.edit = edit;
    this.add = add;           // "＋ Add cloud provider": the picker
    this.connect = connect;   // "＋" in a block: an account of that provider
    this.remove = remove;     // ✕ of an empty provider
    this.landed = landed;
    // The saved resets of the subscriptions: the small "↺ N" on a row opens their window (the owner,
    // 2026-10-12: the button on the board's card, the rest in the account's window).
    this.resets = resets || new SubscriptionResetCards({ redraw: () => this.redraw(), refreshed: (id) => refreshUsageReading("subscription", id) });
    this.top = null;            // the topology the last drawing read
    this.container = null;      // the column's cards (index.html #boardProviderCards)
    this.after = () => {};      // what follows a drawing: the cables, whose ends may have moved
    this.listening = false;
  }

  // The cards drawn into `container`; the column around it keeps the listeners, bound once, and a
  // reading that lands draws the cards again (a subscription's windows, an API key's spend:
  // usage-stats.js READING_LANDED) — and then `after`, since a card that grew moved the cables' ends.
  mount(container, top = topology, { after = null } = {}) {
    if (!container) return;
    this.container = container;
    if (after) this.after = after;
    this.bind(container.parentElement);
    if (!this.listening) {
      this.listening = true;
      this.landed.add(() => { if (this.redraw()) this.after(); });
    }
    this.redraw(top);
  }

  // True when there was a column to draw into.
  redraw(top = topology) {
    if (!this.container || this.container.isConnected === false) return false;
    this.container.innerHTML = this.html(top);
    return true;
  }

  // Every provider on the board in the operator's order, each with its accounts; none — the line
  // that says so and what ＋ does, not an empty column.
  html(top = topology) {
    this.top = top || {};
    const providers = this.top.boardProviders || [];
    if (!providers.length) {
      return `<article class="topology-card provider-none" data-t="provider-none"><div class="topology-muted">${escapeHtml(t("boardProvidersNone"))}</div></article>`;
    }
    const accounts = new Map((this.top.cloudAccounts || []).map((a) => [a.id, a]));
    return providers.map((provider) => this.groupHtml(provider, accounts)).join("");
  }

  account(id) {
    return (this.top?.cloudAccounts || []).find((a) => a.id === id) || null;
  }

  // One provider: its sign and name, its accounts as rows, and the "＋" that adds one more. With no
  // account it says so, and its ✕ takes it off the board; a provider with accounts has no ✕ — they go
  // first, each by Delete in its window. The list and the accounts are read a moment apart: an id
  // the accounts lack (one deleted in between) draws no row, and the next drawing has neither.
  groupHtml(provider, accounts) {
    const kind = String(provider.kind || "");
    const id = escapeHtml(kind);
    const subscription = kind === ProviderGlances.SUBSCRIPTION;
    const rows = (provider.accounts || []).map((accountId) => accounts.get(accountId)).filter((a) => a);
    const name = escapeHtml(subscription ? t("providerGroupSubscriptions") : cloudProviderName(kind));
    const accent = escapeHtml((CLOUD_PICKER_META[kind] || {}).color || "#94a3b8");
    const add = t(subscription ? "providerAddSubscription" : kind === "custom" ? "providerAddEndpoint" : "providerAddKey");
    const remove = rows.length ? "" : `<button class="provider-group-remove" type="button" data-provider-remove="${id}" data-t="provider-group-remove" data-t-id="${id}"
        title="${escapeHtml(t("providerRemove"))}" aria-label="${escapeHtml(t("providerRemove"))}">✕</button>`;
    return `
      <section class="node-card provider-group" data-provider-group="${id}" data-t="provider-group" data-t-id="${id}" style="--provider-accent:${accent}"
               role="group" aria-label="${name}">
        <header class="provider-group-head">
          <span class="provider-group-icon" aria-hidden="true">${cloudPickerTileIcon(kind)}</span>
          <strong>${name}</strong>
          ${rows.length > 1 ? `<span class="provider-group-count">${rows.length}</span>` : ""}
          ${remove}
        </header>
        ${rows.map((account) => this.rowHtml(account)).join("")
          || `<p class="provider-group-empty" data-t="provider-group-empty">${escapeHtml(t("providerEmpty"))}</p>`}
        <button class="provider-group-add" type="button" data-provider-group-add="${id}" data-t="provider-group-add" data-t-id="${id}">＋ ${escapeHtml(add)}</button>
      </section>`;
  }

  // One account: its name, whether it can serve, a subscription's "↺ N" and ⚙ in its head; then a
  // subscription's windows as last read (the account's: its models share them) or an API key's spend
  // through the caravan; a faulted endpoint is said on it, as on the kanban.
  rowHtml(account) {
    const id = escapeHtml(String(account.id));
    const name = escapeHtml(String(account.name || account.id));
    const subscription = PoolCards.subscription(account);
    // A test alias reads its original's limits and resets (CloudSources.quota_owner).
    const owner = String(account.testAliasOf || account.id);
    const ready = !!account.hasCredential;
    const state = ready ? "cloudConnected" : (subscription ? "poolLoginNeeded" : "cloudNoKeyYet");
    let body = "";
    let resets = "";
    if (subscription && ready) {
      this.readUsage(owner);
      this.resets.read(account);
      resets = this.resets.chipHtml(account);
      body = subscriptionUsageHtml(owner, { refresh: false });
    } else if (ready) {
      this.readSpend();
      body = proxySpendHtml(account.id, { zero: true });
    }
    const issues = cloudApiIssuesHtml(account, subscription);
    return `
        <div class="provider-glance provider-account${ready ? " online" : " offline"}" data-board-provider="${id}" data-t="provider-glance" data-t-id="${id}">
          <div class="node-head provider-head">
            <strong title="${name}">${name}</strong>
            <span class="provider-state${ready ? "" : " warn"}" data-t="provider-state" data-t-state="${ready ? "ready" : "waiting"}">${escapeHtml(t(state))}</span>
            <span class="provider-tools">${resets}<button class="icon-action compact provider-edit" type="button" data-provider-edit="${escapeHtml(owner)}" data-t="provider-edit"
              title="${escapeHtml(t("clTitleEditAccount"))}" aria-label="${escapeHtml(t("clTitleEditAccount"))}">⚙</button></span>
          </div>
          ${issues ? `<div class="provider-issues">${issues}</div>` : ""}
          ${body ? `<div class="provider-body">${body}</div>` : ""}
        </div>`;
  }

  // ⚙, the "＋"s, ✕ and "↺ N", delegated from the column, which outlives every drawing.
  bind(column) {
    if (!column || column.dataset.providersBound) return;
    column.dataset.providersBound = "1";
    column.addEventListener("click", (event) => {
      const el = event.target.closest?.("[data-provider-edit],[data-provider-add],[data-provider-group-add],[data-provider-remove],[data-pool-resets]");
      if (!el) return;
      event.stopPropagation();
      if (el.hasAttribute("data-provider-add")) this.add();
      else if (el.hasAttribute("data-provider-group-add")) this.connect(el.dataset.providerGroupAdd);
      else if (el.hasAttribute("data-provider-remove")) this.remove(el.dataset.providerRemove);
      else if (el.hasAttribute("data-pool-resets")) this.resets.choose(this.account(el.dataset.poolResets) || { id: el.dataset.poolResets });
      else this.edit(el.dataset.providerEdit);
    });
  }
}

export const PROVIDER_GLANCES = new ProviderGlances();
