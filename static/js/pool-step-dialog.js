// "+ Add step" and "+ New pool": one window, two errands. Accounts are connected and chosen
// inside it (the operator, 2026-10-10): first the account — one already connected, or a new one
// connected right here through the account window, which brings the operator back with that
// account chosen — then ONE of its models, from the list the controller last fetched
// (GET /api/cloud-accounts/catalogue). A new pool also takes its name, the model's by default.
//
// A list the controller never fetched is said to be so, never drawn as "no models": an empty
// list and an unread one are two facts (absence drawn as normality is this board's oldest
// defect). A model the list does not have can still be typed: a list lags behind its provider.
import { t } from "./i18n.js";
import { api, escapeHtml, toast } from "./utils.js";

export class PoolStepDialog {
  // How many rows of a long list are drawn at once: OpenRouter lists hundreds, and the search
  // finds the rest.
  static ROWS = 120;

  constructor({ call = api, notify = toast, apply = () => {}, render = () => {}, connect = () => {},
    icon = () => "", price = () => "" } = {}) {
    this.call = call;
    this.notify = notify;
    this.apply = apply;       // the controller's answer → the board
    this.render = render;     // draws the board, this window with it
    this.connect = connect;   // (after) → opens the account window; after(accountId | null) on its close
    this.icon = icon;         // account → its provider's icon (HTML)
    this.price = price;       // model id → its price line, or ""
    this.form = null;
    // The lists read in this window, by account: {models, fetchedAt, loading, error}.
    this.catalogues = new Map();
    this.accounts = [];
    this.pools = [];
  }

  set({ accounts = [], pools = [] } = {}) {
    this.accounts = accounts;
    this.pools = pools;
  }

  isOpen() { return !!this.form; }

  // A step for the pool `poolId`; "" is a new pool.
  open(poolId = "") {
    this.form = { poolId: String(poolId || ""), accountId: "", model: "", custom: "", query: "", name: "", busy: false, away: false };
    this.render();
  }

  close() {
    this.form = null;
    this.render();
  }

  account(id) { return this.accounts.find((a) => a.id === id) || null; }

  pool() { return this.form?.poolId ? this.pools.find((p) => p.id === this.form.poolId) || null : null; }

  // The account chosen: its list is read — fetched from the provider first when the controller
  // never did, which a new account's first visit always is.
  pick(accountId) {
    const f = this.form;
    if (!f) return;
    f.accountId = accountId;
    f.model = "";
    f.custom = "";
    f.query = "";
    this.render();
    const account = this.account(accountId);
    if (account?.hasCredential) this.load(accountId, { check: !account.modelsCheckedAt });
  }

  async load(accountId, { check = false } = {}) {
    const before = this.catalogues.get(accountId) || { models: [], fetchedAt: null };
    this.catalogues.set(accountId, { ...before, loading: true, error: "" });
    this.render();
    try {
      if (check) await this.call("/api/cloud-accounts/check-models", { method: "POST", body: JSON.stringify({ id: accountId }) });
      const res = await this.call(`/api/cloud-accounts/catalogue?id=${encodeURIComponent(accountId)}`);
      this.catalogues.set(accountId, { models: Array.isArray(res?.models) ? res.models : [], fetchedAt: res?.fetchedAt ?? null, loading: false, error: "" });
    } catch (err) {
      this.catalogues.set(accountId, { ...before, loading: false, error: String(err?.message || err) });
    }
    this.render();
  }

  // "Connect a new account": the window steps aside while the account window is open, and comes
  // back when it closes — with the new account chosen, or as it was when none was made.
  connectNew() {
    const f = this.form;
    if (!f) return;
    f.away = true;
    this.render();
    this.connect((accountId) => this.back(accountId));
  }

  back(accountId) {
    const f = this.form;
    if (!f) return;
    f.away = false;
    if (accountId && this.account(accountId)) this.pick(accountId);
    else this.render();
  }

  // The model the step takes: one typed beats one picked — it is the operator's last word.
  chosenModel() {
    const f = this.form;
    return f ? (String(f.custom || "").trim() || f.model) : "";
  }

  async submit() {
    const f = this.form;
    if (!f || f.busy) return null;
    const model = this.chosenModel();
    if (!f.accountId) { this.notify(t("poolStepNeedsAccount")); return null; }
    if (!model) { this.notify(t("poolStepNeedsModel")); return null; }
    f.busy = true;
    this.render();
    try {
      const pool = this.pool();
      const res = f.poolId
        ? await this.call("/api/pools/add-step", { method: "POST", body: JSON.stringify({ poolId: f.poolId, accountId: f.accountId, model }) })
        : await this.call("/api/pools/create", { method: "POST", body: JSON.stringify({ name: String(f.name || "").trim(), accountId: f.accountId, model }) });
      const account = this.account(f.accountId);
      this.notify(f.poolId
        ? t("poolStepAdded", { step: `${account?.name || f.accountId} · ${model}`, pool: pool?.name || f.poolId })
        : t("poolCreated", { name: res?.pool?.name || model }));
      this.form = null;
      if (res?.topology) this.apply(res.topology);
      else this.render();
      return res;
    } catch (err) {
      this.notify(err.message);
      f.busy = false;
      this.render();
      return null;
    }
  }

  // ── drawing ──────────────────────────────────────────────────────────

  html() {
    const f = this.form;
    if (!f || f.away) return "";
    const pool = this.pool();
    const title = f.poolId ? t("poolStepTitle", { pool: pool?.name || f.poolId }) : t("poolNewTitle");
    const account = this.account(f.accountId);
    const model = this.chosenModel();
    return `
    <div class="topology-policy-overlay" data-pool-step-overlay>
      <div class="topology-policy-modal cloud-window pool-step-window" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}" data-t="pool-step-window" data-t-state="${account ? "model" : "account"}">
        <div class="topology-card-head">
          <strong>${escapeHtml(title)}</strong>
          <button class="icon-action compact" type="button" data-pool-step-close aria-label="${escapeHtml(t("topologyClose"))}" title="${escapeHtml(t("topologyClose"))}">×</button>
        </div>
        <div class="cloud-window-body">
          <p class="pool-step-label">${escapeHtml(t("poolStepAccount"))}</p>
          ${this.accountsHtml()}
          ${account ? `<p class="pool-step-label">${escapeHtml(t("poolStepModel"))}</p>${this.modelsHtml(account)}` : ""}
          ${account && !f.poolId ? `<label class="cloud-field">${escapeHtml(t("poolName"))}<input type="text" data-pool-step-name data-t="pool-step-name" value="${escapeHtml(f.name)}" placeholder="${escapeHtml(model || t("poolNamePlaceholder"))}"></label>` : ""}
        </div>
        <div class="cloud-window-foot">
          <button class="ghost-action" type="button" data-pool-step-cancel data-t="pool-step-cancel">${escapeHtml(t("topologyCancel"))}</button>
          <button class="primary-mini-action" type="button" data-pool-step-submit data-t="pool-step-submit"${f.busy || !account || !model ? " disabled" : ""}>${escapeHtml(t(f.poolId ? "poolAddStep" : "poolCreate"))}</button>
        </div>
      </div>
    </div>`;
  }

  accountsHtml() {
    const f = this.form;
    const rows = this.accounts.filter((a) => !a.testAliasOf).map((a) => {
      const on = a.id === f.accountId;
      const sign = a.hasCredential
        ? (a.oauthEmail || (a.keyLast4 ? t("cloudKeyShort", { last4: a.keyLast4 }) : t("cloudConnected")))
        : t(a.subscription ? "poolLoginNeeded" : "cloudNoKeyYet");
      return `<button type="button" role="radio" aria-checked="${on}" class="pool-step-account${on ? " on" : ""}${a.hasCredential ? "" : " unsigned"}" data-pool-step-account="${escapeHtml(a.id)}" data-t="pool-step-account" data-t-id="${escapeHtml(a.id)}">
          ${this.icon(a)}<span class="pool-step-account-name">${escapeHtml(a.name || a.id)}</span><span class="pool-step-account-sign">${escapeHtml(sign)}</span>
        </button>`;
    }).join("");
    return `<div class="pool-step-accounts" role="radiogroup" aria-label="${escapeHtml(t("poolStepAccount"))}">
        ${rows || `<p class="pool-step-note">${escapeHtml(t("poolStepNoAccounts"))}</p>`}
        <button type="button" class="pool-step-account new" data-pool-step-connect data-t="pool-step-connect">＋ ${escapeHtml(t("poolStepConnect"))}</button>
      </div>`;
  }

  // The account's models: chat models first (the controller sorts them so), the rest under their
  // own line. What the window knows about the list is said above it: never read, read when, or the
  // provider's refusal.
  modelsHtml(account) {
    const f = this.form;
    const list = this.catalogues.get(account.id);
    const checked = account.modelsCheckedAt || list?.fetchedAt;
    const state = !account.hasCredential ? t("poolStepUnsigned")
      : list?.loading ? t("poolStepLoading")
      : list?.error ? t("poolStepListFailed", { error: list.error })
      : checked ? t("poolStepChecked", { when: new Date(Number(checked) * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) })
      : t("poolStepNeverChecked");
    // An account with no sign-in has no list to search or check: only its words and the typed id.
    const head = account.hasCredential ? `<div class="pool-step-models-head">
        <input type="search" data-pool-step-query data-t="pool-step-query" value="${escapeHtml(f.query)}" placeholder="${escapeHtml(t("poolStepFind"))}" aria-label="${escapeHtml(t("poolStepFind"))}" autocomplete="off" spellcheck="false">
        <button class="ghost-action" type="button" data-pool-step-check data-t="pool-step-check"${list?.loading ? " disabled" : ""}>↻ ${escapeHtml(t("poolStepCheck"))}</button>
      </div>` : "";
    return `${head}
      <p class="pool-step-note" data-t="pool-step-list-state">${escapeHtml(state)}</p>
      <div class="pool-step-models" role="radiogroup" aria-label="${escapeHtml(t("poolStepModel"))}" data-pool-step-models>${this.rowsHtml(account)}</div>
      <label class="cloud-field">${escapeHtml(t("poolStepOther"))}<input type="text" data-pool-step-custom data-t="pool-step-custom" value="${escapeHtml(f.custom)}" placeholder="${escapeHtml(t("poolStepOtherHint"))}" autocomplete="off" spellcheck="false"></label>`;
  }

  rowsHtml(account) {
    const f = this.form;
    const models = this.catalogues.get(account.id)?.models || [];
    const query = String(f.query || "").trim().toLowerCase();
    const matched = query ? models.filter((m) => String(m.id).toLowerCase().includes(query) || String(m.name || "").toLowerCase().includes(query)) : models;
    if (!models.length) return "";
    if (!matched.length) return `<p class="pool-step-note">${escapeHtml(t("poolStepNoMatch"))}</p>`;
    const shown = matched.slice(0, PoolStepDialog.ROWS);
    let other = false;
    const rows = shown.map((m) => {
      const line = !m.chat && !other ? `<p class="pool-step-other">${escapeHtml(t("poolStepNotChat"))}</p>` : "";
      if (!m.chat) other = true;
      const on = m.id === f.model && !String(f.custom || "").trim();
      const window = Number(m.contextLength) > 0 ? `<span class="pool-step-ctx">🪟 ${escapeHtml(String(Math.round(Number(m.contextLength) / 1000)))}K</span>` : "";
      const price = this.price(m.id);
      return `${line}<button type="button" role="radio" aria-checked="${on}" class="pool-step-model-row${on ? " on" : ""}" data-pool-step-model="${escapeHtml(m.id)}" data-t="pool-step-model" data-t-id="${escapeHtml(m.id)}">
          <code>${escapeHtml(m.id)}</code>${window}${price ? `<span class="pool-step-price">${escapeHtml(price)}</span>` : ""}
        </button>`;
    }).join("");
    const more = matched.length > shown.length ? `<p class="pool-step-note">${escapeHtml(t("poolStepMore", { n: String(matched.length - shown.length) }))}</p>` : "";
    return rows + more;
  }

  // Typing in the search draws the rows again in place: a whole board drawn under the caret
  // would take the field away mid-word.
  redrawRows(root) {
    const account = this.account(this.form?.accountId);
    const box = root?.querySelector?.("[data-pool-step-models]");
    if (account && box) box.innerHTML = this.rowsHtml(account);
  }

  // ── acting ───────────────────────────────────────────────────────────

  // Listens on the container once: the window inside it is drawn over and over, the container is not.
  bind(root) {
    if (!root || root.dataset.poolStepBound) return;
    root.dataset.poolStepBound = "1";
    root.addEventListener("click", (event) => { this.click(event); });
    root.addEventListener("input", (event) => { this.typed(event, root); });
  }

  click(event) {
    if (!this.form) return false;
    const target = event.target;
    if (target.closest?.("[data-pool-step-close], [data-pool-step-cancel]")
        || (target.dataset?.poolStepOverlay !== undefined && target.closest?.("[data-pool-step-overlay]") === target)) {
      this.close();
      return true;
    }
    const account = target.closest?.("[data-pool-step-account]");
    if (account) { this.pick(account.dataset.poolStepAccount); return true; }
    if (target.closest?.("[data-pool-step-connect]")) { this.connectNew(); return true; }
    if (target.closest?.("[data-pool-step-check]")) { this.load(this.form.accountId, { check: true }); return true; }
    const model = target.closest?.("[data-pool-step-model]");
    if (model) {
      this.form.model = model.dataset.poolStepModel;
      this.form.custom = "";
      this.render();
      return true;
    }
    if (target.closest?.("[data-pool-step-submit]")) { this.submit(); return true; }
    return false;
  }

  typed(event, root) {
    const f = this.form;
    if (!f) return false;
    const target = event.target;
    if (target.matches?.("[data-pool-step-query]")) { f.query = target.value; this.redrawRows(root); return true; }
    if (target.matches?.("[data-pool-step-custom]")) {
      // A typed id is the operator's last word: the picked row lets go of its mark.
      f.custom = target.value;
      this.redrawRows(root);
      const submit = root?.querySelector?.("[data-pool-step-submit]");
      if (submit) submit.disabled = f.busy || !this.chosenModel();
      return true;
    }
    if (target.matches?.("[data-pool-step-name]")) { f.name = target.value; return true; }
    return false;
  }
}
