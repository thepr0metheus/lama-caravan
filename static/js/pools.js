// Pools on the board (the operator, 2026-10-10). A pool is what an agent's cable goes to: an
// ordered chain of steps, each one account at a provider with ONE model and — on a ChatGPT
// subscription — its own switch levels on the 5H and WEEKLY windows. The proxy takes the first
// step that fits and goes on to the next one for limits only: the step's own level, 429, 402,
// 401 (caravan/proxy/pool_steps.py). A 500 or a timeout is the backup node's work, not the
// pool's. Another model is another pool.
//
// Each pool is its own card under Pools, always open (the operator, 2026-10-11: the folded
// view is not needed): its steps in order, each a card of its own with its number inside it, and
// between two of them a line that says what the order means. The pool's name is the title itself,
// edited where it stands. The pool serves by its order
// alone: nothing picks a step by hand (the operator, 2026-10-11), so the head carries no mode
// switch. A step's account is connected and chosen in "+ Add step" (pool-step-dialog.js);
// ⚙ on a step opens the account's window. The order changes by carrying a step by its grip — the
// way the home start page carries its cards (step-carry.js) — or by ↑ ↓ under its head.
import { CloudRefWords } from "./cloud-ref-words.js";
import { appConfirm, appConfirmChoice } from "./dialogs.js";
import { t } from "./i18n.js";
import { api, escapeHtml, toast } from "./utils.js";

export class PoolCards {
  // What the proxy says about a step → the words of its status pill and their look. A reason it
  // does not know is "unavailable", never a guess.
  static REASONS = {
    ready: ["poolReady", "ready"],
    // Below its switch level a step gives way — still fit; at its stop it does not serve.
    switch: ["poolSwitchReached", "reserve"],
    reserve: ["poolStopReached", "stop"],
    quota: ["poolQuota", "reserve"],
    payment: ["poolPayment", "reserve"],
    upstream_refused: ["poolRefused", "reserve"],
    model_unavailable: ["poolModelGone", "reserve"],
    auth_rejected: ["poolAuthRejected", "login"],
    credential_missing: ["poolLoginNeeded", "login"],
    usage_unknown: ["poolUsageUnknown", "unknown"],
    format_unsupported: ["poolChatOnly", "off"],
    disabled: ["poolDisabled", "off"],
    // A row of a local model (1.3.486): its cell gives way while busy and a later row is free,
    // is passed by while off or gone, and a row that failed a request before its first byte
    // is passed by for that request.
    busy: ["poolBusy", "ready"],
    unavailable: ["poolCellOff", "off-cell"],
    output_missing: ["poolOutputMissing", "missing"],
    not_connected: ["poolNotConnected", "open"],
    tried: ["poolTried", "reserve"],
    // A row of a model its schedule closes now (model-schedule.js): the kanban says until when
    // from the controller's word of the moment; this is the proxy's, for a page without it.
    closed: ["poolClosed", "closed"],
  };


  // Last in the list under Pools, whatever the stored order says: the strip of accounts
  // in no pool and the "no pool yet" card are not server cards, and CSS order 0 put them first.
  static LAST = 100000;

  // The answer "disconnect them" among the pools a deletion offers: no pool has this id.
  static CUT = "__cut__";

  constructor({ call = api, notify = toast, confirm = appConfirm, choose = appConfirmChoice,
    apply = () => {}, addStep = () => {}, editAccount = () => {} } = {}) {
    this.call = call;
    this.notify = notify;
    this.confirm = confirm;
    this.choose = choose;
    this.apply = apply;           // the controller's answer → the board
    this.addStep = addStep;       // pool id ("" for a new pool) → opens the step window
    this.editAccount = editAccount;
    // What the lane hands over before each render (set()).
    this.pools = [];
    this.accounts = [];
    this.runtime = {};
    // The lane's own pieces, as HTML: a card's lead (↑ ↓ and the icon) and its place in the list,
    // a provider's icon, the limit bars of a subscription step, the readings under a step.
    this.lead = () => "";
    this.attrs = () => "";
    this.icon = () => "";
    this.limits = () => "";
    this.refresh = () => "";
    this.chooseReset = () => {};
    this.summary = () => ({});
    this.usage = () => "";
    this.spend = () => "";
    this.issues = () => "";
    this.price = () => "";
    // Steps the operator opened, "<pool>/<step>": a render must not shut them again.
    this.open = new Set();
    // The parts under a pool the operator opened, "<pool>:settings" and "<pool>:history".
    this.shown = new Set();
    // Who carries a step to another place in its order (StepCarry, set by the lane that binds it).
    this.carry = null;
  }

  set({ pools = [], accounts = [], runtime = {} } = {}) {
    this.pools = pools;
    this.accounts = accounts;
    this.runtime = runtime || {};
  }

  account(id) { return this.accounts.find((a) => a.id === id) || null; }

  static subscription(account) {
    return !!account && (account.subscription === true || account.accountType === "openai-subscription"
      || String(account.baseUrl || "").includes("chatgpt.com"));
  }

  // A step as the windows name it: its account, then its model — "Pool · step · account" is the
  // operator's naming (2026-10-10), and a step without its model is not one.
  stepName(step) {
    const account = this.account(step.accountId);
    return `${account?.name || step.accountId} · ${step.model}`;
  }

  // The pool as the server takes it back (POST /api/pools/save): only what the pool keeps, never
  // what the board reads beside it (the levels reached, the reading's time).
  static payload(pool) {
    const out = {
      id: pool.id, name: pool.name, contextAuto: !!pool.contextAuto, contextLength: pool.contextLength ?? "",
      steps: (pool.steps || []).map((s) => ({ id: s.id, accountId: s.accountId, model: s.model,
        enabled: s.enabled !== false, switchAt: { ...(s.switchAt || {}) }, stopAt: { ...(s.stopAt || {}) } })),
    };
    return JSON.parse(JSON.stringify(out));
  }

  // The steps in the order `ids` names — the order a carried step left behind. Null when it changes
  // nothing, or does not name each of the pool's steps exactly once: a partial order is no order.
  static ordered(steps, ids) {
    if (!Array.isArray(ids) || ids.length !== steps.length || new Set(ids).size !== ids.length) return null;
    const byId = new Map(steps.map((s) => [s.id, s]));
    const next = ids.map((id) => byId.get(id));
    if (next.some((s) => !s)) return null;
    return next.every((s, i) => s === steps[i]) ? null : next;
  }

  // ── drawing ──────────────────────────────────────────────────────────

  html() {
    const cards = this.pools.length ? this.pools.map((pool) => this.card(pool)).join("")
      : `<article class="topology-card pool-none" data-t="pool-none" style="order:${PoolCards.LAST}">
          <p class="topology-muted">${escapeHtml(t("poolNone"))}</p>
          <button class="primary-mini-action" type="button" data-pool-new data-t="pool-new-first">＋ ${escapeHtml(t("poolNew"))}</button>
        </article>`;
    return cards + this.looseHtml();
  }

  card(pool) {
    const id = escapeHtml(pool.id);
    const state = this.runtime.available ? this.runtime.pools?.[pool.id] : null;
    const empty = !(pool.steps || []).length;
    const body = (empty ? this.empty(pool) : `<ol class="pool-ladder">${pool.steps.map((step, i) => this.rung(pool, step, i, state)).join("")}</ol>`)
      + this.foot(pool, empty);
    return `<article class="topology-card cloud-account-card pool-card" data-pool-card="${id}" data-t="pool-card" data-t-id="${id}"${this.attrs(pool)}>
      <span class="topology-handle server-input cloud-account-input" data-topology-cloud-input="1" data-pool-id="${id}" title="${escapeHtml(t("poolCableTitle"))}"></span>
      <section class="subscription-pool" data-pool-id="${id}">
        ${this.head(pool, state, empty)}
        ${body}
      </section>
    </article>`;
  }

  head(pool, state, empty) {
    const name = String(pool.name ?? "");
    return `<header class="pool-top">
        ${this.lead(pool)}
        <div class="pool-ident">
          <label class="pool-name" title="${escapeHtml(t("poolName"))}"><input class="pool-name-input" data-pool-field="name" data-t="pool-name" value="${escapeHtml(name)}" size="${Math.max(8, [...name].length + 1)}" aria-label="${escapeHtml(t("poolName"))}"><span class="pool-name-pen" aria-hidden="true">✎</span></label>
          ${empty ? "" : `<div class="pool-last">${this.lastHtml(pool, state)}</div>`}
        </div>
      </header>`;
  }

  // Which step the pool's last request went to, and when, in one short line — or that the pool
  // refused it, no step fitting — or why that is not known: no request since the proxy started, or
  // the proxy silent. A refusal is a decision with its time: drawn as "no request yet", a pool
  // refusing every request read as a pool nobody called.
  lastHtml(pool, state) {
    const label = escapeHtml(t("poolLast"));
    if (!this.runtime.available) return `${label}: <strong>${escapeHtml(t("poolProxySilent"))}</strong>`;
    const at = Number(state?.decidedAt) || 0;
    const when = at ? ` · ${escapeHtml(new Date(at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))}` : "";
    const step = (pool.steps || []).find((s) => s.id === state?.selectedStepId);
    if (step) return `${label}: <strong>${escapeHtml(this.stepName(step))}</strong>${when}`;
    if (state && at) return `${label}: <strong class="pool-last-refused">${escapeHtml(t("poolLastRefused"))}</strong>${when}`;
    return `${label}: <strong>${escapeHtml(t("poolNoRequest"))}</strong>`;
  }

  // A pool with no step: the cable to it stays, and a request is refused with "add one". The
  // two ways on are a step, or the pool's deletion.
  empty(pool) {
    return `<div class="pool-empty" data-t="pool-empty">
      <p class="pool-empty-note">${escapeHtml(t("poolEmpty"))}</p>
      <div class="pool-empty-actions">
        <button class="primary-mini-action" type="button" data-pool-add-step="${escapeHtml(pool.id)}" data-t="pool-add-step">＋ ${escapeHtml(t("poolAddFirstStep"))}</button>
        <button class="ghost-action danger" type="button" data-pool-delete="${escapeHtml(pool.id)}" data-t="pool-delete">${escapeHtml(t("poolDelete"))}</button>
      </div>
    </div>`;
  }

  // The status pill: why the proxy would, or would not, use this step now. Serving beats every
  // reason, but only on the proxy's own word. An account with no sign-in says so before the
  // proxy does.
  status(pool, step, state) {
    const account = this.account(step.accountId);
    const row = (state?.steps || []).find((r) => r.stepId === step.id);
    // A step giving way still serves when no step above its own switch level is fit.
    if (state?.selectedStepId === step.id && (!row || row.reason === "ready" || row.reason === "switch")) {
      return { look: "serving", text: t("poolServing"), title: row?.reason === "switch" ? t("poolSwitchReached") : "" };
    }
    if (account && !account.hasCredential) {
      return { look: "login", text: t(PoolCards.subscription(account) ? "poolLoginNeeded" : "cloudNoKeyYet"), title: "" };
    }
    if (!row) return { look: "unknown", text: t(this.runtime.available ? "poolNoRequest" : "poolProxySilent"), title: "" };
    const [key, look] = PoolCards.REASONS[row.reason] || ["poolUnavailable", "unknown"];
    return { look, text: t(key), title: row.reason || "" };
  }

  // What the head of a rung says without opening it: how many saved resets, what the step's model
  // cost at API prices — and, loudest, that a reset's outcome is uncertain. The number of resets is
  // a button when there is one to use: it opens the window that asks which — the one place resets
  // are spent. A count that could not be read says "?" rather than vanish.
  meta(s, owner = "") {
    const parts = [];
    if (s.pending) parts.push(`<span class="pool-warn" title="${escapeHtml(t("resetPending"))}">⚠</span>`);
    if (s.resets != null) {
      const title = escapeHtml(t(s.resets > 0 ? "resetChoose" : "resetAvailable", { count: String(s.resets) }));
      const count = escapeHtml(t("resetCount", { count: String(s.resets) }));
      parts.push(s.resets > 0
        ? `<button class="pool-resets" type="button" data-pool-resets="${escapeHtml(owner)}" title="${title}" aria-label="${title}">↺ ${count}</button>`
        : `<span class="pool-resets none" title="${title}">↺ ${count}</span>`);
    } else if (s.resetsFailed) {
      parts.push(`<span class="pool-resets none" title="${escapeHtml(t("resetUnavailable"))}">↺ ?</span>`);
    }
    if (s.cost) parts.push(`<span title="${escapeHtml(s.costTitle || "")}">≈ ${escapeHtml(s.cost)}</span>`);
    return parts.join("");
  }

  rung(pool, step, index, state) {
    const account = this.account(step.accountId);
    const last = index === pool.steps.length - 1;
    const link = last ? "" : `<div class="pool-link"><span aria-hidden="true">↓</span>${escapeHtml(t("poolFallsThrough"))}</div>`;
    const rank = `<span class="pool-rank" aria-hidden="true">${index + 1}</span>`;
    const sid = escapeHtml(step.id);
    const remove = `<button class="icon-action compact" type="button" data-pool-step-remove data-t="pool-step-remove" title="${escapeHtml(t("poolStepRemove"))}" aria-label="${escapeHtml(t("poolStepRemove"))}">✕</button>`;
    if (!account) {
      return `<li class="pool-rung"><div class="pool-step missing" data-pool-step="${sid}" data-t="pool-step" data-t-id="${sid}">${rank}<span class="pool-step-gone">${escapeHtml(this.stepName(step))} · ${escapeHtml(t("poolAccountGone"))}</span>${remove}</div>${link}</li>`;
    }
    const subscription = PoolCards.subscription(account);
    // A subscription nobody signed into has no limits to read: asking would only draw a refusal.
    const reads = subscription && !!account.hasCredential;
    const owner = step.usageAccountId || account.testAliasOf || account.id;
    const status = this.status(pool, step, state);
    const sum = this.summary(owner, account.id, step.model) || {};
    const key = `${pool.id}/${step.id}`;
    const open = this.open.has(key);
    const price = this.price(step.model);
    const unlisted = step.unlisted ? `<span class="pool-step-unlisted" title="${escapeHtml(t("cloudModelUnlisted"))}">⚠</span>` : "";
    return `<li class="pool-rung"><div class="pool-step${status.look === "serving" ? " serving" : ""}${step.enabled === false ? " off" : ""}${open ? " open" : ""}" data-pool-step="${sid}" data-t="pool-step" data-t-id="${sid}" data-t-state="${escapeHtml(status.look)}">
      <div class="pool-step-head">
        ${rank}
        <span class="pool-grip" data-pool-grip tabindex="0" role="button" title="${escapeHtml(t("poolOrder"))}" aria-label="${escapeHtml(t("poolOrder"))}">⠿</span>
        <div class="pool-step-id">
          <div class="pool-step-title">
            ${this.icon(account)}
            <strong class="pool-step-name" title="${escapeHtml(account.name || account.id)}">${escapeHtml(account.name || account.id)}</strong>${account.testAliasOf ? `<span class="pool-test">TEST</span>` : ""}
            <span class="pool-status ${status.look}" title="${escapeHtml(status.title)}">${escapeHtml(status.text)}</span>
          </div>
          <div class="pool-step-model"><code title="${escapeHtml(step.model)}">${escapeHtml(step.model)}</code>${unlisted}${price ? `<span class="pool-step-price" title="${escapeHtml(t("cloudPriceLegend"))}">${escapeHtml(price)}</span>` : ""}${account.oauthEmail ? `<span class="pool-step-mail" title="${escapeHtml(account.oauthEmail)}">${escapeHtml(account.oauthEmail)}</span>` : ""}</div>
        </div>
        <div class="pool-step-tools">
          <span class="pool-step-meta">${this.meta(sum, owner)}</span>
          ${reads ? this.refresh(owner) : ""}
          <button class="icon-action compact pool-fold" type="button" data-pool-fold aria-expanded="${open}" title="${escapeHtml(t(open ? "collapse" : "expand"))}" aria-label="${escapeHtml(t(open ? "collapse" : "expand"))}"></button>
        </div>
      </div>
      ${reads ? this.limits(pool, step, owner) : ""}
      <div class="pool-step-more">
        <div class="pool-actions">
          <label class="pool-check"><input type="checkbox" data-step-field="enabled"${step.enabled !== false ? " checked" : ""}>${escapeHtml(t("poolEnabled"))}</label>
          <button class="icon-action compact" type="button" data-pool-move="-1" title="${escapeHtml(t("poolOrder"))}"${index === 0 ? " disabled" : ""}>↑</button>
          <button class="icon-action compact" type="button" data-pool-move="1" title="${escapeHtml(t("poolOrder"))}"${last ? " disabled" : ""}>↓</button>
          <button class="icon-action compact" type="button" data-pool-edit-account="${escapeHtml(account.testAliasOf || account.id)}" title="${escapeHtml(t("clTitleEditAccount"))}">⚙</button>
          ${remove}
        </div>
        ${account.testAliasOf ? `<div class="muted">${escapeHtml(t("poolAliasHint"))}</div>` : ""}
        ${subscription ? "" : this.usage(account)}${this.spend(account)}${this.issues(account)}
      </div>
    </div>${link}</li>`;
  }

  // Under the steps: "+ Add step" across the card, then one bar with the switches of the two
  // parts that open (settings, history) — and under it the part opened (the operator,
  // 2026-10-11: the foot was three loose rows).
  foot(pool, empty) {
    const id = escapeHtml(pool.id);
    const parts = this.partHead(pool, "settings", "poolSettings") + (this.events(pool).length ? this.partHead(pool, "history", "poolHistory") : "");
    return `<div class="pool-foot">
      ${empty ? "" : `<button class="ghost-action pool-add-step" type="button" data-pool-add-step="${id}" data-t="pool-add-step">＋ ${escapeHtml(t("poolAddStep"))}</button>`}
      <div class="pool-bar">
        <div class="pool-parts">${parts}</div>
      </div>
      ${this.settingsHtml(pool, empty)}
      ${this.historyHtml(pool)}
    </div>`;
  }

  // The switch of one part under the foot: "<pool>:<part>" opens and shuts it (`shown`).
  partHead(pool, part, key) {
    const name = `${pool.id}:${part}`;
    const open = this.shown.has(name);
    return `<button class="pool-part-head${open ? " open" : ""}" type="button" data-pool-part="${escapeHtml(name)}" aria-expanded="${open}">${escapeHtml(t(key))}</button>`;
  }

  // What is set once and rarely: the window the pool states to its clients, and the pool's
  // deletion. Shut until the operator opens it.
  settingsHtml(pool, empty) {
    if (!this.shown.has(`${pool.id}:settings`)) return "";
    const window = pool.contextLength ? String(pool.contextLength) : "";
    return `<div class="pool-panel pool-settings" data-t="pool-settings">
        <label class="pool-window" title="${escapeHtml(t("poolWindowHint"))}">${escapeHtml(t("topologyCloudContextLength"))}<input type="number" min="1" step="1" data-pool-field="contextLength" value="${escapeHtml(window)}" placeholder="${escapeHtml(t("topologyCloudContextEmpty"))}"></label>
        <label class="pool-check" title="${escapeHtml(t("poolWindowAutoHint"))}"><input type="checkbox" data-pool-field="contextAuto"${pool.contextAuto ? " checked" : ""}>${escapeHtml(t("poolWindowAuto"))}</label>
        ${empty ? "" : `<button class="ghost-action danger" type="button" data-pool-delete="${escapeHtml(pool.id)}" data-t="pool-delete">${escapeHtml(t("poolDelete"))}</button>`}
      </div>`;
  }

  // The proxy's last switches between the pool's steps, newest first.
  events(pool) {
    return (this.runtime.events || []).filter((e) => e.poolId === pool.id).slice(-5).reverse();
  }

  historyHtml(pool) {
    const events = this.events(pool);
    if (!events.length || !this.shown.has(`${pool.id}:history`)) return "";
    const name = (id) => {
      const step = (pool.steps || []).find((s) => s.id === id);
      return step ? this.stepName(step) : (id || "—");
    };
    const rows = events.map((e) => `<div class="pool-event"><time>${escapeHtml(new Date(e.at * 1000).toLocaleTimeString())}</time> ${escapeHtml(name(e.from))} → ${escapeHtml(name(e.to))}`
      + `<small>${escapeHtml((e.reasons || []).map((r) => `${name(r.stepId)}: ${r.reason}`).join("; "))}</small></div>`).join("");
    return `<div class="pool-panel pool-history">${rows}</div>`;
  }

  // Accounts that stand in no pool: connected, and reached by no cable. Without this strip they
  // would be nowhere on the board — absence drawn as nothing at all.
  looseHtml() {
    const used = new Set(this.pools.flatMap((p) => (p.steps || []).map((s) => s.accountId)));
    const loose = this.accounts.filter((a) => !used.has(a.id) && !a.testAliasOf);
    if (!loose.length) return "";
    return `<article class="topology-card pool-loose" data-t="pool-loose" style="order:${PoolCards.LAST + 1}">
      <div class="pool-loose-title">${escapeHtml(t("poolLooseTitle"))}</div>
      <p class="pool-loose-hint">${escapeHtml(t("poolLooseHint"))}</p>
      ${loose.map((a) => `<div class="pool-loose-row" data-t="pool-loose-account" data-t-id="${escapeHtml(a.id)}">${this.icon(a)}<span class="pool-loose-name">${escapeHtml(a.name || a.id)}</span>`
        + `<span class="pool-status ${a.hasCredential ? "ready" : "login"}">${escapeHtml(a.hasCredential ? t("cloudConnected") : t(PoolCards.subscription(a) ? "poolLoginNeeded" : "cloudNoKeyYet"))}</span>`
        + `<button class="icon-action compact" type="button" data-pool-edit-account="${escapeHtml(a.id)}" title="${escapeHtml(t("clTitleEditAccount"))}">⚙</button></div>`).join("")}
    </article>`;
  }

  // ── acting ───────────────────────────────────────────────────────────

  stored(poolId) { return this.pools.find((p) => p.id === poolId) || null; }

  async save(pool) {
    const res = await this.call("/api/pools/save", { method: "POST", body: JSON.stringify({ pool: PoolCards.payload(pool) }) });
    this.apply(res.topology);
    return res;
  }

  // A step is carried, landing, or its new order is being saved: the lane is not rebuilt under it —
  // a drawing would put back the order the controller still holds. The carry clears its own state
  // on every way out, the save's refusal included (step-carry.js).
  inFlight() {
    return !!this.carry?.busy;
  }

  // The order a carried step left behind, saved as the pool's order; the answer draws the board, and
  // is what this answers. Refused, or nothing to save — null: the board then draws the order the
  // controller keeps (pool-board.js, sortRows), not the carried one.
  async sort(poolId, ids) {
    const stored = this.stored(poolId);
    const steps = stored && PoolCards.ordered(stored.steps, ids);
    if (!steps) return null;
    try { return await this.save({ ...stored, steps }); } catch (err) { this.notify(err.message); return null; }
  }

  // A rung opens and shuts in place — nothing is asked of the server, and the rung is remembered,
  // so the next render keeps it as it is.
  foldStep(element) {
    const step = element.closest("[data-pool-step]");
    const pool = element.closest("[data-pool-id]");
    if (!step || !pool) return;
    const key = `${pool.dataset.poolId}/${step.dataset.poolStep}`;
    const open = !this.open.has(key);
    this.open[open ? "add" : "delete"](key);
    step.classList.toggle("open", open);
    const button = step.querySelector("[data-pool-fold]");
    button?.setAttribute("aria-expanded", String(open));
    button?.setAttribute("title", t(open ? "collapse" : "expand"));
    button?.setAttribute("aria-label", t(open ? "collapse" : "expand"));
  }

  // "Delete pool": what leads to it on the kanban is the controller's reading, not a list kept
  // here; when the controller cannot say, the pool stays. With nothing leading to it the question
  // is plain; with cables or rules it asks where they go — onto another pool, or disconnected.
  async remove(poolId) {
    const pool = this.stored(poolId);
    if (!pool) return null;
    let answer;
    try {
      answer = await this.call(`/api/pools/refs?id=${encodeURIComponent(poolId)}`);
    } catch (err) {
      this.notify(err.message);
      return null;
    }
    const held = answer?.held;
    if (!held) {
      this.notify(t("poolDeleteUnknown"));
      return null;
    }
    const name = pool.name || pool.id;
    // The clients of the entry that call it by name lose it with it (2026-10-11): the controller names
    // them — the same reading its entry routes by — and the window says so before it is too late.
    const clients = (answer.clients || []).map(String);
    const clientsLine = clients.length ? t("poolDeleteClients", { names: clients.join(", ") }) : "";
    const opts = { title: t("poolDelete"), danger: true, confirmLabel: t("poolDelete"), detail: CloudRefWords.detail(CloudRefWords.lines(answer.refs || {})) };
    const rules = held.rules || [];
    let resolution = null;
    if (!held.cables && !rules.length) {
      if (!(await this.confirm([t("poolDeleteText", { name }), clientsLine].filter(Boolean).join(" "), opts))) return null;
    } else {
      const others = this.pools.filter((p) => p.id !== poolId);
      const text = [t("poolDeleteHeld", { name, cables: String(held.cables), rules: String(rules.length) }),
        rules.includes("default") ? t("portCloseDefault") : "", clientsLine].filter(Boolean).join(" ");
      const choice = await this.choose(text, { ...opts, list: others.length > 3, choiceLabel: t("portCloseChoiceLabel"),
        choices: [...others.map((p) => ({ value: p.id, label: p.name || p.id })), { value: PoolCards.CUT, label: t("portCloseCut") }] });
      if (!choice) return null;
      resolution = choice === PoolCards.CUT ? { cut: true } : { moveTo: choice };
    }
    try {
      const res = await this.call("/api/pools/delete", { method: "POST", body: JSON.stringify({ id: poolId, ...(resolution ? { resolution } : {}) }) });
      const onto = this.pools.find((p) => p.id === res?.onto);
      this.notify(res?.onto ? t("poolDeletedMoved", { name, onto: onto?.name || res.onto, n: String(res.moved ?? 0) })
        : res?.cut ? t("poolDeletedCut", { name, n: String(res.cut) }) : t("poolDeleted", { name }));
      if (res?.topology) this.apply(res.topology);
      return res;
    } catch (err) {
      this.notify(err.message);
      return null;
    }
  }

  async removeStep(poolId, stepId) {
    const pool = this.stored(poolId);
    const step = pool?.steps.find((s) => s.id === stepId);
    if (!step) return null;
    const ok = await this.confirm(t("poolStepRemoveText", { step: this.stepName(step), pool: pool.name || pool.id }),
      { title: t("poolStepRemove"), danger: true, confirmLabel: t("poolStepRemove") });
    if (!ok) return null;
    try {
      const res = await this.call("/api/pools/remove-step", { method: "POST", body: JSON.stringify({ poolId, stepId }) });
      this.open.delete(`${poolId}/${stepId}`);
      if (res?.topology) this.apply(res.topology);
      return res;
    } catch (err) {
      this.notify(err.message);
      return null;
    }
  }

  // Clicks and changes on the lane, delegated from its container. True when the event was a
  // pool's; the lane then stops looking.
  async handle(event, redraw = () => {}) {
    const element = event.target.closest?.("[data-pool-move], [data-pool-field], [data-step-field], [data-pool-add-step], [data-pool-new], [data-pool-delete], [data-pool-fold], [data-pool-resets], [data-pool-part], [data-pool-step-remove], [data-pool-edit-account]");
    if (!element || (event.type === "click" && element.matches("input, select")) || (event.type === "change" && element.matches("button"))) return false;
    event.stopPropagation();
    const poolId = element.closest("[data-pool-id]")?.dataset.poolId || "";
    const stepId = element.closest("[data-pool-step]")?.dataset.poolStep || "";
    if (element.hasAttribute("data-pool-add-step")) { this.addStep(element.dataset.poolAddStep); return true; }
    if (element.hasAttribute("data-pool-new")) { this.addStep(""); return true; }
    if (element.hasAttribute("data-pool-delete")) { await this.remove(element.dataset.poolDelete); return true; }
    if (element.hasAttribute("data-pool-fold")) { this.foldStep(element); return true; }
    if (element.hasAttribute("data-pool-part")) {
      const key = element.dataset.poolPart;
      if (this.shown.has(key)) this.shown.delete(key); else this.shown.add(key);
      redraw();
      return true;
    }
    if (element.hasAttribute("data-pool-resets")) { this.chooseReset(element.dataset.poolResets); return true; }
    if (element.hasAttribute("data-pool-edit-account")) { this.editAccount(element.dataset.poolEditAccount); return true; }
    if (element.hasAttribute("data-pool-step-remove")) { await this.removeStep(poolId, stepId); return true; }
    const stored = this.stored(poolId);
    if (!stored) return true;
    const pool = PoolCards.payload(stored);
    const step = pool.steps.find((s) => s.id === stepId);
    if (element.dataset.poolField === "contextAuto") {
      pool.contextAuto = !!element.checked;
    } else if (element.dataset.poolField === "contextLength") {
      // Left blank is "I state nothing", not zero: the server drops the window.
      pool.contextLength = String(element.value || "").trim();
    } else if (element.dataset.poolField === "name") {
      const name = String(element.value || "").trim();
      if (!name || name === stored.name) return true;
      pool.name = name;
    } else if (element.dataset.stepField === "enabled" && step) {
      // A step's one switch: off takes it out of the order. Named, so no other field a stray
      // element names (the "Automatic selection" of the hand pick, before 1.3.463) gets written.
      step.enabled = !!element.checked;
    } else if (element.hasAttribute("data-pool-move")) {
      const from = pool.steps.findIndex((s) => s.id === stepId), to = from + Number(element.dataset.poolMove);
      if (from < 0 || to < 0 || to >= pool.steps.length) return true;
      [pool.steps[from], pool.steps[to]] = [pool.steps[to], pool.steps[from]];
    } else {
      return true;
    }
    element.disabled = true;
    try { await this.save(pool); } catch (err) { this.notify(err.message); element.disabled = false; }
    return true;
  }
}
