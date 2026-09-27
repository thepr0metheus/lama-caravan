// A provider's models on its card: what each one is to the fleet right now,
// drawn from one place (2026-09-27, the operator's variant A).
//
// The list keeps itself (caravan/admin/cloud_sync.py): new models arrive
// hidden and marked new, a model the provider dropped is marked gone and —
// with nothing pointing at it — removed, and the removal can be undone for a
// day. So the card no longer has "Fetch models" or a bridge section: a row
// says what the model is (new, gone, on the kanban or hidden, the default),
// how many cables reach it, its price, and its own port for an app — opened
// by a button on the row, open in the LAN, no key (the operator's call).
import { appConfirm, appConfirmChoice } from "./dialogs.js";
import { t } from "./i18n.js";
import { formatPricePer1M, modelPricing } from "./model-meta.js";
import { topology } from "./state.js";
import { api, escapeHtml, toast } from "./utils.js";

// How long a model stays "new" after the list brought it.
export const NEW_FOR_MS = 7 * 24 * 3600 * 1000;

export class ProviderModels {
  constructor({ account, blocks = [], routers = [], proxies = [], removed = [], now = Date.now(), open = false,
    nextPort = null, hostname = "", spend = null } = {}) {
    this.account = account || {};
    this.blocks = blocks.filter((b) => b.accountId === this.account.id);
    this.routers = routers;
    this.proxies = proxies;
    this.removed = removed.filter((r) => r.accountId === this.account.id);
    this.now = now;
    this.open = open;
    this.nextPort = nextPort;
    this.hostname = hostname;
    // The account's 30 days through the caravan (usage-stats.js): each model's
    // share goes on its own row, what matches no row goes in one line below.
    this.spend = spend && Array.isArray(spend.byModel) ? spend : null;
  }

  // Dollars as the rows say them: whole from a dollar up, cents below, and a
  // share too small to show said so rather than as $0.
  static money(cost) {
    const c = Number(cost) || 0;
    if (c >= 1) return `$${Math.round(c).toLocaleString("en-US")}`;
    if (c >= 0.01) return `$${c.toFixed(2)}`;
    return "<$0.01";
  }

  // A model's line of the spend, matched by name whatever its case; null
  // when nothing went to it through the caravan.
  spentOn(model) {
    const key = String(model || "").toLowerCase();
    return (this.spend?.byModel || []).find((m) => String(m.model || "").toLowerCase() === key) || null;
  }

  // Its share on a row: the cost at API prices, or — no price known (the
  // spend says 0) — how many requests, never "$0".
  spendHtml(model) {
    const m = this.spentOn(model);
    if (!m || !(Number(m.requests) > 0 || Number(m.cost) > 0)) return "";
    const days = String(this.spend.windowDays || 30);
    const req = String(Number(m.requests) || 0);
    const text = Number(m.cost) > 0
      ? t("cloudModelSpend", { cost: ProviderModels.money(m.cost), days })
      : t("cloudModelSpendReq", { req, days });
    return `<span class="cloud-block-spend" title="${escapeHtml(t("cloudModelSpendTitle", { days, req }))}">${escapeHtml(text)}</span>`;
  }

  // What went through the caravan to a model this list does not have (gone
  // and removed, or named by the client): one line, so the total adds up.
  elsewhereHtml() {
    if (!this.spend) return "";
    const known = new Set(this.blocks.map((b) => String(b.model || "").toLowerCase()));
    const rest = this.spend.byModel.filter((m) => !known.has(String(m.model || "").toLowerCase())
      && (Number(m.cost) > 0 || Number(m.requests) > 0));
    if (!rest.length) return "";
    const items = rest.map((m) => `<span class="cloud-spend-item"><code>${escapeHtml(m.model || "?")}</code> `
      + `${escapeHtml(Number(m.cost) > 0 ? `≈ ${ProviderModels.money(m.cost)}` : t("spendReqOnly", { req: String(Number(m.requests) || 0) }))}</span>`).join("");
    return `<div class="cloud-spend-elsewhere"><span class="cloud-removed-title">${escapeHtml(t("cloudSpendElsewhere", { days: String(this.spend.windowDays || 30) }))}</span>${items}</div>`;
  }

  // Cables into a model: kanban edges that land on its output, in every router.
  cables(blockId) {
    const ref = `out:cb:${blockId}`;
    return this.routers.reduce((n, r) => n + ((r.graph?.edges || []).filter((e) => e && e.to === ref).length), 0);
  }

  isDefault(blockId) {
    return this.routers.some((r) => (r.rules || {}).default === `cb:${blockId}`);
  }

  // A model's own ports (route kind "service"), lowest first. Having one is
  // what puts a model on the kanban (caravan/admin/cloud_ports.py).
  static portsOf(proxies, blockId) {
    return (proxies || []).filter((p) => p.kind === "service" && p.providerId === blockId)
      .sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
  }

  ports(blockId) {
    return ProviderModels.portsOf(this.proxies, blockId);
  }

  price(model) {
    if (String(model || "").endsWith(":free")) return "FREE";
    const p = modelPricing[model || ""];
    return p && (p.inputPer1M || p.outputPer1M)
      ? `${formatPricePer1M(p.inputPer1M)} / ${formatPricePer1M(p.outputPer1M)} /1M` : "";
  }

  // What each model is, attention first: gone, then new, then on the
  // kanban, then hidden; within a group the dearer first, then by name.
  rows() {
    const rank = (m) => {
      const p = modelPricing[m || ""];
      return p ? (Number(p.inputPer1M) || 0) * 1000 + (Number(p.outputPer1M) || 0) : -1;
    };
    return this.blocks.map((b) => {
      const gone = !!b.unlisted;
      const fresh = !gone && Number(b.newSince) > 0 && this.now - Number(b.newSince) * 1000 < NEW_FOR_MS;
      return { block: b, gone, fresh, shown: !!b.exposed, cables: this.cables(b.id), isDefault: this.isDefault(b.id),
        ports: this.ports(b.id), price: this.price(b.model) };
    }).sort((a, b) => {
      const group = (r) => (r.gone ? 0 : r.fresh ? 1 : r.shown ? 2 : 3);
      return (group(a) - group(b)) || (rank(b.block.model) - rank(a.block.model))
        || String(a.block.model || a.block.id).localeCompare(String(b.block.model || b.block.id), undefined,
          { numeric: true, sensitivity: "base" });
    });
  }

  summary() {
    const rows = this.rows();
    return { total: rows.length, shown: rows.filter((r) => r.shown).length,
      fresh: rows.filter((r) => r.fresh).length, gone: rows.filter((r) => r.gone).length };
  }

  checkedAt() {
    const at = Number(this.account.modelsCheckedAt) || 0;
    if (!at) return t("cloudModelsNotChecked");
    const d = new Date(at * 1000);
    const hhmm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    return t("cloudModelsCheckedAt", { time: hhmm });
  }

  headHtml() {
    const s = this.summary();
    const acc = escapeHtml(this.account.id);
    const parts = [t("cloudModelsOnKanban", { n: String(s.shown) })];
    if (s.fresh) parts.push(`<span class="cloud-models-fresh">${escapeHtml(t("cloudModelsNewCount", { n: String(s.fresh) }))}</span>`);
    if (s.gone) parts.push(`<span class="cloud-models-gone">${escapeHtml(t("cloudModelsGoneCount", { n: String(s.gone) }))}</span>`);
    const said = parts.map((p) => (p.startsWith("<") ? p : escapeHtml(p))).join(" · ");
    return `<div class="cloud-models-head">
      <button class="cloud-models-toggle" type="button" data-cloud-models-toggle="${acc}" aria-expanded="${this.open}">
        <span class="cloud-models-title">${escapeHtml(t("cloudModelsTitle"))}</span><span class="cloud-models-n">${s.total}</span>
        <span class="cloud-models-sum">${said}</span><span class="cloud-models-caret" aria-hidden="true">${this.open ? "⌃" : "⌄"}</span>
      </button>
      <span class="cloud-models-checked">${escapeHtml(this.checkedAt())}</span>
      <button class="icon-action compact" type="button" data-cloud-fetch-models="${acc}" title="${escapeHtml(t("cloudModelsCheckNow"))}"
        aria-label="${escapeHtml(t("cloudModelsCheckNow"))}">↻</button>
    </div>`;
  }

  chip(text, kind) {
    return `<span class="cloud-chip ${kind}">${escapeHtml(text)}</span>`;
  }

  rowHtml(r, movable = false) {
    const b = r.block;
    const chips = [
      r.gone ? this.chip(t("cloudChipGone"), "gone") : "",
      r.fresh ? this.chip(t("cloudChipNew"), "fresh") : "",
      r.shown ? this.chip(t("cloudChipKanban"), "shown") : "",
      r.isDefault ? this.chip(t("cloudChipDefault"), "default") : "",
    ].join("");
    const cables = r.cables ? `<span class="cloud-block-cables">${escapeHtml(t("cloudModelCables", { n: String(r.cables) }))}</span>` : "";
    const price = (r.price ? `<span class="cloud-block-pricing${r.price === "FREE" ? " free" : ""}">${escapeHtml(r.price)}</span>` : "")
      + this.spendHtml(b.model);
    const ports = r.ports.length
      ? r.ports.map((p) => {
        const url = `http://${this.hostname}:${p.port}`;
        return `<span class="cloud-model-port"><code class="cloud-bridge-port">:${escapeHtml(String(p.port))}</code>`
          + `<button class="icon-action compact" type="button" data-bridge-copy="${escapeHtml(url)}" title="${escapeHtml(t("cloudBridgeCopy"))}">⧉</button>`
          + `<button class="icon-action compact" type="button" data-bridge-delete="${escapeHtml(String(p.port))}" title="${escapeHtml(t("cloudBridgeDelete"))}">✕</button></span>`;
      }).join("")
      : (this.account.hasCredential
        ? `<button class="cloud-port-add" type="button" data-bridge-mint="${escapeHtml(b.id)}" title="${escapeHtml(
          t("cloudPortAddTitle", { port: this.nextPort ? String(this.nextPort) : "…" }))}">${escapeHtml(t("cloudPortAdd"))}</button>`
        : "");
    // A gone model something still leads to, while the provider has another
    // model to lead there instead: its cables move in one step.
    const move = r.gone && (r.cables > 0 || r.isDefault) && movable
      ? `<button class="cloud-move-cables" type="button" data-cloud-move-cables="${escapeHtml(b.id)}"`
        + ` title="${escapeHtml(t("cloudMoveCablesTitle"))}">${escapeHtml(t("cloudMoveCables"))}</button>`
      : "";
    const title = r.gone ? t("cloudModelGoneTitle") : (b.model || b.id);
    return `<div class="cloud-block-row${r.gone ? " stale" : ""}${r.fresh ? " fresh" : ""}" data-cloud-block="${escapeHtml(b.id)}"`
      + ` role="button" tabindex="0" title="${escapeHtml(title)}">`
      + `<span class="cloud-block-model">${escapeHtml(b.model || "—")}</span>${chips}${cables}${move}${price}${ports}</div>`;
  }

  removedHtml() {
    if (!this.removed.length) return "";
    const acc = escapeHtml(this.account.id);
    const items = this.removed.map((r) => `<span class="cloud-removed-item"><code>${escapeHtml(r.model || r.id)}</code>`
      + `<button class="icon-action compact" type="button" data-cloud-restore="${acc}|${escapeHtml(r.id)}"`
      + ` title="${escapeHtml(t("cloudRestore"))}" aria-label="${escapeHtml(t("cloudRestore"))}">↶</button></span>`).join("");
    return `<div class="cloud-removed"><span class="cloud-removed-title">${escapeHtml(t("cloudRemovedTitle"))}</span>${items}</div>`;
  }

  html() {
    const rows = this.rows();
    const movable = rows.some((r) => !r.gone);
    const list = rows.length
      ? `<div class="cloud-account-blocks">${rows.map((r) => this.rowHtml(r, movable)).join("")}</div>`
      : `<div class="topology-muted cloud-models-empty">${escapeHtml(t("clNoModelsYet"))}</div>`;
    return `${this.headHtml()}${this.removedHtml()}
      <div class="cloud-models-flyout">${list}${this.elsewhereHtml()}
        <button class="cloud-add-model-btn" type="button" data-cloud-add-block="${escapeHtml(this.account.id)}">${escapeHtml(t("cloudAddById"))}</button>
      </div>`;
  }
}

// How alike two model names are: the words of the name without the vendor
// and the versions ("openai/gpt-6.1-sol" → gpt, sol), counted in common.
// Both offers to move cables rank by it — onto a newcomer, off a gone model.
export class ModelNames {
  static words(id) {
    const name = String(id || "").toLowerCase().split("/").pop();
    return [...new Set(name.split(/[-_.:]+/).filter((w) => w && !/^v?\d+[a-z]?$/.test(w)))];
  }

  static likeness(a, b) {
    const mine = new Set(ModelNames.words(a));
    return ModelNames.words(b).filter((w) => mine.has(w)).length;
  }
}

// The "new model" window (2026-09-27, the operator's ask): a provider brought
// new models, and some model of that provider carries cables or is a
// router's default — offer to move them onto a newcomer. One window per
// provider's batch: it names the newcomer closest by name to a model in use
// (gpt-6.1-sol beside gpt-6-sol: the words without the vendor and the
// version), and "Not now" answers for the whole batch — OpenRouter brought
// 184 models in one list, and a window per model would have been 184
// windows. "Move" and "Just add" answer for that one model; the next of the
// batch asks after it.
export class NewModelAnnouncer {
  static JUST_ADD = "__add__";

  constructor({ dialog = appConfirmChoice, call = api, notify = toast, apply = () => {}, now = () => Date.now(),
    quiet = () => NewModelAnnouncer.nothingOpen() } = {}) {
    this.dialog = dialog;
    this.call = call;
    this.notify = notify;
    this.apply = apply;
    this.now = now;
    this.quiet = quiet;
    this.asking = false;
    // Models whose answer failed to reach the controller: not asked again on
    // this page, or a failing controller would reopen the window every poll.
    this.failed = new Set();
  }

  // Nothing is open over the board: every dialog and modal is aria-modal,
  // and one counts when it is drawn (has boxes). Not by the hidden attribute:
  // a cell's window waits in its row with display:none, and on the live
  // board seven of them read as open — the window would never have asked.
  static nothingOpen(doc = globalThis.document) {
    if (!doc?.querySelectorAll) return false;
    return ![...doc.querySelectorAll('[aria-modal="true"]')].some((d) => (d.getClientRects?.() || []).length > 0);
  }

  // What to ask now, or null: the first provider with new models nobody
  // answered for and a model in use. Closest newcomer first (ties keep the
  // card's order), and for it the closest model in use, then the busiest.
  pending(top) {
    for (const account of top?.cloudAccounts || []) {
      const rows = new ProviderModels({ account, blocks: top.cloudProviders || [], routers: top.routers || [],
        now: this.now() }).rows();
      const batch = rows.filter((r) => r.fresh && !r.block.announced && !this.failed.has(r.block.id));
      const inUse = rows.filter((r) => !r.fresh && (r.cables > 0 || r.isDefault));
      if (!batch.length || !inUse.length) continue;
      const close = (r) => Math.max(...inUse.map((u) => ModelNames.likeness(r.block.model, u.block.model)));
      const block = batch.map((r) => ({ r, k: close(r) })).sort((a, b) => b.k - a.k)[0].r.block;
      const sources = inUse.map((u) => ({ u, k: ModelNames.likeness(block.model, u.block.model) }))
        .sort((a, b) => (b.k - a.k) || (b.u.cables - a.u.cables)).map((x) => x.u);
      return { account, block, sources, batch: batch.map((r) => r.block.id) };
    }
    return null;
  }

  sourceLabel(row) {
    const parts = [row.block.model || row.block.id];
    if (row.cables) parts.push(t("cloudModelCables", { n: String(row.cables) }));
    if (row.isDefault) parts.push(t("cloudChipDefault"));
    if (row.gone) parts.push(t("cloudChipGone"));
    return parts.join(" · ");
  }

  // Ask about one newcomer, if there is one and nothing else is open.
  // Resolves the answer ("move from" id, JUST_ADD, null for "Not now"), or
  // undefined when it did not ask.
  async maybeAsk(top = topology) {
    if (this.asking || !this.quiet()) return undefined;
    const p = this.pending(top);
    if (!p) return undefined;
    this.asking = true;
    const { account, block, sources, batch } = p;
    const model = block.model || block.id;
    try {
      const more = batch.length - 1;
      const choice = await this.dialog(
        t("newModelText", { model }) + (more > 0 ? ` ${t("newModelMore", { n: String(more) })}` : ""), {
          title: t("newModelTitle", { provider: account.name || account.id }),
          danger: false, list: sources.length > 3, choiceLabel: t("newModelChoiceLabel"),
          confirmLabel: t("newModelApply"), cancelLabel: t("newModelNotNow"),
          choices: [...sources.map((s) => ({ value: s.block.id, label: this.sourceLabel(s) })),
            { value: NewModelAnnouncer.JUST_ADD, label: t("newModelJustAdd") }],
        });
      const post = (path, body) => this.call(path, { method: "POST", body: JSON.stringify(body) });
      let res;
      if (choice === null || choice === undefined) {
        res = await post("/api/cloud-blocks/announced", { ids: batch });
      } else if (choice === NewModelAnnouncer.JUST_ADD) {
        res = await post("/api/cloud-blocks/announced", { ids: [block.id], expose: true });
      } else {
        res = await post("/api/cloud-blocks/move-cables", { from: choice, to: block.id });
        if (Number.isFinite(res?.moved)) this.notify(t("newModelMoved", { n: String(res.moved), model }));
      }
      if (res?.topology) this.apply(res.topology);
      return choice ?? null;
    } catch (err) {
      this.failed.add(block.id);
      this.notify(err.message);
      return undefined;
    } finally {
      this.asking = false;
    }
  }
}

// Where a model's cables may go: the provider's other models it still lists
// — the closest by name first, then the ones on the kanban, then the card's
// order. One ranking for both offers that move them: off a gone model, and
// off a model whose last port closes.
export class CableTargets {
  // The model's row, its provider and the targets; null when the model or
  // its provider is not on the board.
  static of(blockId, top, now = Date.now()) {
    const block = (top?.cloudProviders || []).find((b) => b.id === blockId);
    const account = block && (top.cloudAccounts || []).find((a) => a.id === block.accountId);
    if (!account) return null;
    const rows = new ProviderModels({ account, blocks: top.cloudProviders, routers: top.routers || [], now }).rows();
    const onto = rows.filter((r) => !r.gone && r.block.id !== blockId)
      .map((r) => ({ r, k: ModelNames.likeness(block.model, r.block.model) }))
      .sort((a, b) => (b.k - a.k) || (Number(b.r.shown) - Number(a.r.shown))).map((x) => x.r);
    return { account, from: rows.find((r) => r.block.id === blockId), onto };
  }

  static label(row) {
    const parts = [row.block.model || row.block.id];
    if (row.shown) parts.push(t("cloudChipKanban"));
    if (row.cables) parts.push(t("cloudModelCables", { n: String(row.cables) }));
    return parts.join(" · ");
  }
}

// "⇄ Move cables…" on a model the provider dropped while something still
// leads to it (variant A): its cables and rules move onto another model of
// the same provider in one step — the closest by name first, then the ones
// on the kanban, then the card's order. Nothing points at the gone model
// afterwards, so the sync removes it by itself and keeps it a day for "↶".
export class GoneModelCables {
  constructor({ dialog = appConfirmChoice, call = api, notify = toast, apply = () => {}, now = () => Date.now() } = {}) {
    this.dialog = dialog;
    this.call = call;
    this.notify = notify;
    this.apply = apply;
    this.now = now;
  }

  targets(blockId, top) {
    return CableTargets.of(blockId, top, this.now());
  }

  label(row) {
    return CableTargets.label(row);
  }

  // Resolves the model the cables went to, or null: cancelled, nowhere to
  // go, or the controller refused (said in a toast).
  async offer(blockId, top = topology) {
    const p = this.targets(blockId, top);
    if (!p?.onto.length) return null;
    const model = p.from.block.model || blockId;
    const to = await this.dialog(t("goneMoveText", { model, provider: p.account.name || p.account.id }), {
      title: t("goneMoveTitle", { model }), danger: false, list: p.onto.length > 3,
      choiceLabel: t("goneMoveChoiceLabel"), confirmLabel: t("goneMoveApply"),
      choices: p.onto.map((r) => ({ value: r.block.id, label: this.label(r) })),
    });
    if (!to) return null;
    try {
      const res = await this.call("/api/cloud-blocks/move-cables", { method: "POST", body: JSON.stringify({ from: blockId, to }) });
      const onto = p.onto.find((r) => r.block.id === to);
      if (Number.isFinite(res?.moved)) this.notify(t("newModelMoved", { n: String(res.moved), model: onto?.block.model || to }));
      if (res?.topology) this.apply(res.topology);
      return to;
    } catch (err) {
      this.notify(err.message);
      return null;
    }
  }
}

// Closing a model's port: the ✕ beside it on the card, or unticking the
// model on the kanban (which closes all of its ports). The last port takes
// the model off the kanban (the operator's rule, 2026-09-27), and whatever
// still leads to it has to go somewhere first: the window asks — onto
// another model of the provider (CableTargets; one without a port gets one)
// or disconnect. What "leads to it" is the controller's reading (`held` from
// the refs route), not a second list kept here. A port that is not the last
// one closes with a plain question; so does a last one nothing holds. Each
// says when a request last came through, since an app may be behind it.
export class PortCloser {
  static CUT = "__cut__";

  constructor({ dialog = appConfirmChoice, confirm = appConfirm, call = api, notify = toast, apply = () => {},
    now = () => Date.now() } = {}) {
    this.dialog = dialog;
    this.confirm = confirm;
    this.call = call;
    this.notify = notify;
    this.apply = apply;
    this.now = now;
  }

  static lastRequestLine(top, ports) {
    const at = Math.max(0, ...(top?.proxies || []).filter((p) => ports.includes(Number(p.port)))
      .map((p) => Number(p.lastRequestAt) || 0));
    if (!at) return t("portNoRequest");
    const when = new Date(at * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    return t("portLastRequest", { when });
  }

  // Close one port (`port`) or all of the model's ports (null). Resolves the
  // controller's answer, or null when nothing was closed.
  async close(blockId, port = null, top = topology) {
    const mine = ProviderModels.portsOf(top?.proxies, blockId).map((p) => Number(p.port));
    const closing = port === null ? mine : mine.filter((p) => p === Number(port));
    if (!closing.length) return null;
    const block = (top?.cloudProviders || []).find((b) => b.id === blockId);
    const model = block?.model || blockId;
    const named = closing.map((p) => `:${p}`).join(", ");
    const last = PortCloser.lastRequestLine(top, closing);
    const title = t("portCloseTitle", { port: named });
    const opts = { title, danger: true, confirmLabel: t("portCloseApply") };
    let resolution = null;
    if (closing.length < mine.length) {
      const stays = mine.filter((p) => !closing.includes(p)).map((p) => `:${p}`).join(", ");
      if (!(await this.confirm(`${t("portCloseKeep", { model, ports: stays })} ${last}`, opts))) return null;
    } else {
      let held;
      try {
        held = (await this.call(`/api/cloud-blocks/refs?id=${encodeURIComponent(blockId)}`))?.held;
      } catch (err) {
        this.notify(err.message);
        return null;
      }
      if (!held) {
        this.notify(t("portCloseUnknown"));
        return null;
      }
      const rules = held.rules || [];
      if (!held.cables && !rules.length) {
        if (!(await this.confirm(`${t("portCloseConfirm", { model })} ${last}`, opts))) return null;
      } else {
        const onto = CableTargets.of(blockId, top, this.now())?.onto || [];
        const text = [t("portCloseHeld", { model, cables: String(held.cables), rules: String(rules.length) }),
          rules.includes("default") ? t("portCloseDefault") : "", last].filter(Boolean).join(" ");
        const choice = await this.dialog(text, { ...opts, list: onto.length > 3, choiceLabel: t("portCloseChoiceLabel"),
          choices: [...onto.map((r) => ({ value: r.block.id, label: CableTargets.label(r) })),
            { value: PortCloser.CUT, label: t("portCloseCut") }] });
        if (!choice) return null;
        resolution = choice === PortCloser.CUT ? { cut: true } : { moveTo: choice };
      }
    }
    const post = (path, body) => this.call(path, { method: "POST", body: JSON.stringify(body) });
    const extra = resolution ? { resolution } : {};
    try {
      const res = port === null
        ? await post("/api/cloud-blocks/expose", { id: blockId, exposed: false, ...extra })
        : await post("/api/cloud-accounts/bridge-port-delete", { port: closing[0], ...extra });
      const onto = (top?.cloudProviders || []).find((b) => b.id === res?.onto);
      this.notify(res?.onto
        ? t("portClosedMoved", { port: named, model: onto?.model || res.onto, n: String(res.moved ?? 0) })
        : res?.cut ? t("portClosedCut", { port: named, n: String(res.cut) }) : t("portClosed", { port: named }));
      if (res?.topology) this.apply(res.topology);
      return res;
    } catch (err) {
      this.notify(err.message);
      return null;
    }
  }
}

