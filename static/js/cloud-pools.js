// Pool policy and member controls. Credentials stay in each account's editor;
// the pool's saved policy and the proxy's last decisions are separate facts.
//
// A pool is drawn as a LADDER: its members in priority order, one numbered rung each, joined
// by a spine that says what the order means — the proxy takes the first eligible member, and
// goes down a rung when that one reaches its reserve or its limit. The rung shows the two
// limit bars, one under the other; everything that is acted on rarely (the toggles, the order
// buttons, the saved resets, the spend) opens under its head. The priority changes by dragging
// a rung by its grip. The card owns its whole top: the pool's name is the title itself, edited
// where it stands, and the mode is a switch beside it — there is no form above the ladder.
import { t } from "./i18n.js";
import { api, escapeHtml, toast } from "./utils.js";

export class SubscriptionPoolCards {
  // What the proxy says about a member → the words of its status pill. A reason it does not
  // know is "unavailable", never a guess.
  static REASONS = { ready: "poolReady", reserve: "poolReserve", quota: "poolReserve", disabled: "poolDisabled", manual_only: "poolManualOnly", not_selected: "poolManualOnly" };
  static REASON_LOOK = { ready: "ready", reserve: "reserve", quota: "reserve", disabled: "off", manual_only: "off", not_selected: "off" };

  constructor({ accounts = [], runtime = {}, limits = () => "", refresh = () => "", resets = () => "", chooseReset = () => {}, summary = () => ({}), spend = () => "", apply = () => {}, connect = () => {} } = {}) {
    this.accounts = accounts;
    this.runtime = runtime;
    this.limits = limits;     // account id → the limit bars (HTML)
    this.refresh = refresh;   // account id → the button that re-reads them (HTML): it sits in the rung's head, not among the bars
    this.resets = resets;     // account id → the saved resets (HTML)
    this.chooseReset = chooseReset;   // account id → opens the window that asks which saved reset to spend
    this.summary = summary;   // (credential owner id, account id) → {resets, pending, cost}: what a rung's head says
    this.spend = spend;
    this.apply = apply;
    this.connect = connect;
    // Rungs the operator opened: a render must not shut them again.
    this.open = new Set();
    // The rung being dragged by its grip: {pool, id}.
    this.dragging = null;
  }

  static subscription(a) { return !a.isPool && (a.accountType === "openai-subscription" || String(a.baseUrl || "").includes("chatgpt.com")); }
  static owner(a) { return a.testAliasOf || a.id; }
  // The card the account `id` is drawn on under Model servers: the pool it is a member of,
  // or its own. The lane draws a member inside its pool's ladder, and the kanban's Servers
  // panel keeps a member's group beside its pool's (server-order.js places both by the card).
  static cardOf(accounts, id) {
    return accounts.find((a) => a.isPool && (a.pool?.members || []).some((m) => m.accountId === id))?.id || id;
  }

  // The accounts the kanban's Servers panel draws as groups of their own: every account with a
  // card of its own, and a pool's member only while it still holds models of its own. A member's
  // models are reached through its pool, so an empty member group said "0/0" and sent the
  // operator to "↻ on its card" — a card the member does not have. A member that holds models
  // keeps its group: hiding it would hide outputs that cables may lead to.
  static kanbanGroups(accounts, blocks) {
    return accounts.filter((a) => this.cardOf(accounts, a.id) === a.id
      || (blocks || []).some((b) => b.accountId === a.id));
  }

  // The members with `id` moved next to `targetId` — after it, or before it. Null when the move
  // changes nothing or names a member the pool does not have.
  static reordered(members, id, targetId, after) {
    const from = members.findIndex((m) => m.accountId === id);
    if (from < 0 || id === targetId || !members.some((m) => m.accountId === targetId)) return null;
    const rest = members.filter((m) => m.accountId !== id);
    const at = rest.findIndex((m) => m.accountId === targetId) + (after ? 1 : 0);
    const next = [...rest.slice(0, at), members[from], ...rest.slice(at)];
    return next.every((m, i) => m === members[i]) ? null : next;
  }

  // `lead` is what the lane leads a pool's title with: the card's grip and the account's icon.
  controls(account, lead = "") {
    if (account.isPool) return this.pool(account, lead);
    if (!SubscriptionPoolCards.subscription(account)) return "";
    return `<div class="pool-actions"><button class="ghost-action" data-pool-create="${escapeHtml(account.id)}">${escapeHtml(t("poolCreate"))}</button>`
      + (account.testAliasOf ? `<span class="muted">${escapeHtml(t("poolAliasHint"))}</span>` : "") + `</div>`;
  }

  pool(account, lead = "") {
    const pool = account.pool;
    const state = this.runtime.available ? this.runtime.pools?.[pool.id] : null;
    const chosen = this.accounts.find((a) => a.id === state?.selectedAccountId);
    const unused = this.accounts.filter((a) => SubscriptionPoolCards.subscription(a) && !pool.members.some((m) => m.accountId === a.id));
    const options = `<option value="">${escapeHtml(t("poolAdd"))}</option>` + unused.map((a) => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name || a.id)}</option>`).join("");
    const events = (this.runtime.events || []).filter((e) => e.poolId === pool.id).slice(-5).reverse();
    const history = events.map((e) => {
      const name = (id) => this.accounts.find((a) => a.id === id)?.name || id || "—";
      return `<div class="pool-event"><time>${escapeHtml(new Date(e.at * 1000).toLocaleTimeString())}</time> ${escapeHtml(name(e.from))} → ${escapeHtml(name(e.to))}`
        + `<small>${escapeHtml(e.mode)} ${escapeHtml((e.reasons || []).map((r) => `${name(r.accountId)}: ${r.reason}`).join("; "))}</small></div>`;
    }).join("");
    const mode = (value, key) => `<button type="button" role="radio" class="pool-mode${pool.mode === value ? " on" : ""}" aria-checked="${pool.mode === value}" data-pool-mode="${value}">${escapeHtml(t(key))}</button>`;
    const name = String(pool.name ?? "");
    return `<section class="subscription-pool" data-pool-id="${escapeHtml(pool.id)}">
      <header class="pool-top">
        ${lead}
        <div class="pool-ident">
          <label class="pool-name" title="${escapeHtml(t("poolName"))}"><input class="pool-name-input" data-pool-field="name" value="${escapeHtml(name)}" size="${Math.max(8, [...name].length + 1)}" aria-label="${escapeHtml(t("poolName"))}"><span class="pool-name-pen" aria-hidden="true">✎</span></label>
          <div class="pool-last">${escapeHtml(t("poolLast"))}: <strong>${escapeHtml(chosen?.name || t("poolUnknown"))}</strong>${state?.decidedAt ? ` · ${escapeHtml(new Date(state.decidedAt * 1000).toLocaleTimeString())}` : ""}</div>
        </div>
        <div class="pool-controls">
          ${pool.mode === "manual" ? `<label class="pool-until">${escapeHtml(t("poolUntil"))}<select data-pool-field="manualDuration">${pool.manualUntil ? `<option value="current" selected disabled>${escapeHtml(new Date(pool.manualUntil * 1000).toLocaleString())}</option>` : ""}<option value="0">${escapeHtml(t("poolUntilCancel"))}</option><option value="3600">1 h</option><option value="18000">5 h</option></select></label>` : ""}
          <div class="pool-modes" role="radiogroup" aria-label="${escapeHtml(t("poolMode"))}">${mode("auto", "poolAuto")}${mode("manual", "poolManual")}</div>
        </div>
      </header>
      <ol class="pool-ladder">${pool.members.map((member, index) => this.rung(pool, member, index, state)).join("")}</ol>
      <div class="pool-foot">
        <label class="pool-check pool-loop"><input type="checkbox" data-pool-field="returnToPrimary"${pool.returnToPrimary ? " checked" : ""}><span aria-hidden="true">↻</span>${escapeHtml(t("poolReturn"))}</label>
        <div class="pool-add">
          ${unused.length ? `<select data-pool-add aria-label="${escapeHtml(t("poolAdd"))}">${options}</select>` : ""}
          <button class="ghost-action" type="button" data-pool-connect="${escapeHtml(pool.id)}">＋ ${escapeHtml(t("poolConnect"))}</button>
        </div>
        ${history ? `<details class="pool-history"><summary>${escapeHtml(t("poolHistory"))}</summary>${history}</details>` : ""}
      </div>
    </section>`;
  }

  // The status pill: why the proxy would, or would not, use this member now. Serving beats
  // every reason, but only on the proxy's own word; a member picked by hand says so, since the
  // proxy may not have answered for it yet.
  status(pool, member, account, state) {
    if (member.pendingLogin) return { look: "login", text: t("poolLoginNeeded"), title: "" };
    const row = state?.members?.find((r) => r.accountId === account.id);
    if (state?.selectedAccountId === account.id && (!row || row.reason === "ready")) return { look: "serving", text: t("poolServing"), title: row?.reason || "" };
    if (pool.mode === "manual" && pool.manualAccountId === account.id) return { look: "serving", text: t("poolManual"), title: row?.reason || "" };
    if (!row) return { look: "unknown", text: t("poolUnknown"), title: "" };
    return { look: SubscriptionPoolCards.REASON_LOOK[row.reason] || "unknown", text: t(SubscriptionPoolCards.REASONS[row.reason] || "poolUnavailable"), title: row.reason || "" };
  }

  // What the head of a rung says without opening it: how many saved resets, what the
  // account cost at API prices — and, loudest, that a reset's outcome is uncertain. The number of
  // resets is a button when there is one to use: it opens the window that asks which (the refresh
  // button beside it only reads, and the two must not be mistaken for each other).
  meta(s, owner = "") {
    const parts = [];
    if (s.pending) parts.push(`<span class="pool-warn" title="${escapeHtml(t("resetPending"))}">⚠</span>`);
    if (s.resets != null) {
      const title = escapeHtml(t(s.resets > 0 ? "resetChoose" : "resetAvailable", { count: String(s.resets) }));
      parts.push(s.resets > 0
        ? `<button class="pool-resets" type="button" data-pool-resets="${escapeHtml(owner)}" title="${title}" aria-label="${title}">↺ ${escapeHtml(String(s.resets))}</button>`
        : `<span class="pool-resets none" title="${title}">↺ 0</span>`);
    }
    if (s.cost) parts.push(`<span title="${escapeHtml(t("spendAtApiPrices", { cost: s.cost }))}">≈ ${escapeHtml(s.cost)}</span>`);
    return parts.join("");
  }

  rung(pool, member, index, state) {
    const account = this.accounts.find((a) => a.id === member.accountId);
    const last = index === pool.members.length - 1;
    const link = last ? "" : `<div class="pool-link"><span aria-hidden="true">↓</span>${escapeHtml(t("poolFallsThrough"))}</div>`;
    const rank = `<span class="pool-rank" aria-hidden="true">${index + 1}</span>`;
    if (!account) return `<li class="pool-rung"><div class="pool-step missing" data-pool-member="${escapeHtml(member.accountId)}">${rank}${escapeHtml(member.accountId)} · ${escapeHtml(t("poolUnavailable"))}</div>${link}</li>`;
    const owner = SubscriptionPoolCards.owner(account);
    const status = this.status(pool, member, account, state);
    const sum = this.summary(owner, account.id) || {};
    const open = this.open.has(account.id) || !!sum.pending;
    const picked = pool.mode === "manual" && pool.manualAccountId === account.id;
    return `<li class="pool-rung"><div class="pool-step${status.look === "serving" ? " serving" : ""}${member.enabled ? "" : " off"}${open ? " open" : ""}" data-pool-member="${escapeHtml(account.id)}">
      ${rank}
      <div class="pool-step-head">
        <span class="pool-grip" draggable="true" data-pool-grip title="${escapeHtml(t("poolOrder"))}" aria-label="${escapeHtml(t("poolOrder"))}">⠿</span>
        <div class="pool-step-id">
          <div class="pool-step-title">
            <strong class="pool-step-name" title="${escapeHtml(account.name || account.id)}">${escapeHtml(account.name || account.id)}</strong>${account.testAliasOf ? `<span class="pool-test">TEST</span>` : ""}
            <span class="pool-status ${status.look}" title="${escapeHtml(status.title)}">${escapeHtml(status.text)}</span>
            ${pool.mode === "manual" && !picked ? `<button class="ghost-action" type="button" data-pool-use="${escapeHtml(account.id)}">${escapeHtml(t("poolUse"))}</button>` : ""}
          </div>
          ${account.oauthEmail ? `<span class="pool-step-mail" title="${escapeHtml(account.oauthEmail)}">${escapeHtml(account.oauthEmail)}</span>` : ""}
        </div>
        <div class="pool-step-tools">
          <span class="pool-step-meta">${this.meta(sum, owner)}</span>
          ${this.refresh(owner)}
          <button class="icon-action compact pool-fold" type="button" data-pool-fold aria-expanded="${open}" title="${escapeHtml(t(open ? "collapse" : "expand"))}" aria-label="${escapeHtml(t(open ? "collapse" : "expand"))}"></button>
        </div>
      </div>
      ${this.limits(owner)}
      <div class="pool-step-more">
        <div class="pool-actions">
          <button class="ghost-action${picked ? " selected" : ""}" type="button" data-pool-use="${escapeHtml(account.id)}">${escapeHtml(t("poolUse"))}</button>
          <label class="pool-check"><input type="checkbox" data-member-field="enabled"${member.enabled ? " checked" : ""}>${escapeHtml(t("poolEnabled"))}</label>
          <label class="pool-check"><input type="checkbox" data-member-field="automatic"${member.automatic ? " checked" : ""}>${escapeHtml(t("poolAutomatic"))}</label>
          <button class="icon-action compact" type="button" data-pool-move="-1" title="${escapeHtml(t("poolOrder"))}"${index === 0 ? " disabled" : ""}>↑</button>
          <button class="icon-action compact" type="button" data-pool-move="1" title="${escapeHtml(t("poolOrder"))}"${last ? " disabled" : ""}>↓</button>
          <button class="icon-action compact" type="button" data-pool-remove title="${escapeHtml(t("poolRemove"))}"${pool.members.length === 1 ? " disabled" : ""}>×</button>
          <button class="icon-action compact" type="button" data-cloud-edit-account="${escapeHtml(owner)}" title="${escapeHtml(t("clTitleEditAccount"))}">⚙</button>
        </div>
        ${account.testAliasOf ? `<div class="muted">${escapeHtml(t("poolAliasHint"))}</div>` : ""}
        ${this.resets(owner)}${this.spend(account.id)}
      </div>
    </div>${link}</li>`;
  }

  async save(pool, extra = {}) {
    const res = await api("/api/cloud-pools/save", { method: "POST", body: JSON.stringify({ pool, ...extra }) });
    this.apply(res.topology);
  }

  // A rung is in the air. The lane is not rebuilt under it. When the rung is gone — the page was
  // drawn over it, or the browser never said dragend — the flag goes with it: it must not keep the
  // lane from ever drawing again.
  inFlight() {
    if (!this.dragging) return false;
    if (typeof document !== "undefined" && document.querySelector?.(".pool-step.dragging")) return true;
    this.dragging = null;
    return false;
  }

  // A rung opens and shuts in place — nothing is asked of the server, and the rung is
  // remembered, so the next render keeps it as it is.
  fold(step) {
    const id = step.dataset.poolMember;
    const open = !this.open.has(id);
    this.open[open ? "add" : "delete"](id);
    step.classList.toggle("open", open);
    const button = step.querySelector("[data-pool-fold]");
    button?.setAttribute("aria-expanded", String(open));
    button?.setAttribute("title", t(open ? "collapse" : "expand"));
    button?.setAttribute("aria-label", t(open ? "collapse" : "expand"));
  }

  // Dragging a rung by its grip: where the pointer is over another rung says whether the
  // dragged one goes before it or after it; dropping saves the new order.
  async gesture(event) {
    const step = event.target.closest?.("[data-pool-member]");
    const section = event.target.closest?.("[data-pool-id]");
    const clear = () => event.target.closest?.("[data-pool-id]")?.querySelectorAll?.(".pool-step.dragging, .pool-step.drop-before, .pool-step.drop-after")
      .forEach((el) => el.classList.remove("dragging", "drop-before", "drop-after"));
    if (event.type === "dragstart") {
      if (!event.target.closest("[data-pool-grip]") || !step || !section) return false;
      this.dragging = { pool: section.dataset.poolId, id: step.dataset.poolMember };
      event.dataTransfer?.setData("text/plain", this.dragging.id);
      if (event.dataTransfer) event.dataTransfer.effectAllowed = "move";
      event.dataTransfer?.setDragImage?.(step, 16, 16);   // the whole rung follows the pointer, not the grip's one glyph
      step.classList.add("dragging");
      return true;
    }
    if (event.type === "dragend") { clear(); this.dragging = null; return true; }
    const mine = this.dragging && section && section.dataset.poolId === this.dragging.pool && step;
    if (!mine) return false;
    const rect = step.getBoundingClientRect();
    const after = event.clientY > rect.top + rect.height / 2;
    if (event.type === "dragover") {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
      section.querySelectorAll(".pool-step.drop-before, .pool-step.drop-after").forEach((el) => el.classList.remove("drop-before", "drop-after"));
      if (step.dataset.poolMember !== this.dragging.id) step.classList.add(after ? "drop-after" : "drop-before");
      return true;
    }
    if (event.type !== "drop") return false;
    event.preventDefault();
    const { pool: poolId, id } = this.dragging;
    clear();
    this.dragging = null;
    const stored = this.accounts.find((a) => a.id === poolId)?.pool;
    const members = stored && SubscriptionPoolCards.reordered(stored.members, id, step.dataset.poolMember, after);
    if (!members) return true;
    try { await this.save({ ...JSON.parse(JSON.stringify(stored)), members: JSON.parse(JSON.stringify(members)) }); } catch (err) { toast(err.message); }
    return true;
  }

  async handle(event) {
    const element = event.target.closest("[data-pool-create], [data-pool-use], [data-pool-move], [data-pool-remove], [data-pool-field], [data-member-field], [data-pool-add], [data-pool-connect], [data-pool-mode], [data-pool-fold], [data-pool-resets]");
    if (!element || (event.type === "click" && element.matches("input, select")) || (event.type === "change" && element.matches("button"))) return false;
    event.stopPropagation();
    if (element.hasAttribute("data-pool-connect")) { this.connect(element.dataset.poolConnect); return true; }
    if (element.hasAttribute("data-pool-fold")) { this.fold(element.closest("[data-pool-member]")); return true; }
    if (element.hasAttribute("data-pool-resets")) { this.chooseReset(element.dataset.poolResets); return true; }
    element.disabled = true;
    try {
      const section = element.closest("[data-pool-id]");
      const stored = this.accounts.find((a) => a.id === section?.dataset.poolId)?.pool;
      const pool = stored ? JSON.parse(JSON.stringify(stored)) : null;
      const memberId = element.closest("[data-pool-member]")?.dataset.poolMember;
      if (element.hasAttribute("data-pool-create")) {
        const aid = element.dataset.poolCreate;
        let id = "openai-pool", n = 2;
        while (this.accounts.some((a) => a.id === id)) id = `openai-pool-${n++}`;
        await this.save({ id, name: t("poolTitle"), mode: "auto", members: [{ accountId: aid, enabled: true, automatic: true }] }, { adoptAccountId: aid });
      } else if (pool) {
        const member = pool.members.find((m) => m.accountId === memberId);
        if (element.hasAttribute("data-pool-mode")) {
          // The mode already on is not a change: nothing is saved for it.
          if (pool.mode === element.dataset.poolMode) { element.disabled = false; return true; }
          pool.mode = element.dataset.poolMode;
          if (pool.mode === "manual" && !pool.manualAccountId) pool.manualAccountId = pool.members.find((m) => m.enabled)?.accountId || pool.members[0].accountId;
        } else if (element.dataset.poolField === "mode") {
          pool.mode = element.value;
          if (pool.mode === "manual" && !pool.manualAccountId) pool.manualAccountId = pool.members.find((m) => m.enabled)?.accountId || pool.members[0].accountId;
        } else if (element.dataset.poolField === "manualDuration") pool.manualUntil = Number(element.value) ? Math.floor(Date.now() / 1000) + Number(element.value) : 0;
        else if (element.dataset.poolField) pool[element.dataset.poolField] = element.type === "checkbox" ? element.checked : element.value;
        else if (element.dataset.memberField && member) member[element.dataset.memberField] = element.checked;
        else if (element.hasAttribute("data-pool-use")) { pool.mode = "manual"; pool.manualAccountId = element.dataset.poolUse; pool.manualUntil = 0; }
        else if (element.hasAttribute("data-pool-move")) {
          const from = pool.members.findIndex((m) => m.accountId === memberId), to = from + Number(element.dataset.poolMove);
          if (to >= 0 && to < pool.members.length) [pool.members[from], pool.members[to]] = [pool.members[to], pool.members[from]];
        } else if (element.hasAttribute("data-pool-remove")) {
          pool.members = pool.members.filter((m) => m.accountId !== memberId);
          if (pool.manualAccountId === memberId) { pool.manualAccountId = ""; pool.mode = "auto"; }
        } else if (element.hasAttribute("data-pool-add") && element.value) pool.members.push({ accountId: element.value, enabled: true, automatic: true });
        await this.save(pool);
      }
    } catch (err) { toast(err.message); element.disabled = false; }
    return true;
  }
}
