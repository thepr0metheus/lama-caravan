// Routing (the owner, 2026-10-12): clients, sets, pools and models in four columns, joined by
// cables — the mockup the owner approved ("I like such mockups. Build them.").
//
// "Only one cable goes on from a client": a client of the entry is cabled to one SET, and the set
// to pools — the models the client sees, chat, speech, embeddings (the owner, 2026-10-12, step 2
// of the visumap scheme caravan-model-sets; a set may serve several clients). Its `GET /v1/models`
// lists the set's pools, a request's `model` picks one (caravan/common/entry_models.py). "In a pool only the list of the
// models on the right is gathered, a row added by "+" in the pool; each row gives one more
// output, and that output is cabled to the model on the right": a pool is its rows in order,
// each a subscription's model or a machine's cell (caravan/common/cloud_pools.py), tried from the
// top (caravan/proxy/pool_steps.py). "The limit bars belong not on the pool but on the models
// themselves, on the right": a subscription model's two levels hold in every pool whose row
// names it (caravan/common/model_levels.py).
//
// The board draws the controller's reading and works out nothing of its own: which set a client
// calls and what models it sees (`set`, `models`), which pools a set holds (`topology.sets`),
// what each row is cabled to, which row served last and why the others did not (the proxy's
// word, `poolsRuntime`). A cable is drawn by carrying an output's dot onto a set, a pool or a
// model, and cut by a click on it; a new one — a set's model, a pool's row — by carrying a "＋"
// row from any point of it. A row is carried by its grip to another place (step-carry.js).
// A pool's settings — the window it states to its clients — open under its rows. A client's card
// links what the client gets for its own GET questions, asked with its key by the controller.
// "Show only the models I added" (the owner, 2026-10-12): an account's card holds the models added
// to it with "＋ model" — found in the account's list as they are typed — and leaving by their ✕,
// not every model the account offers (caravan/admin/added_models.py). The account itself is not set
// up here (the owner, 2026-10-12: "no settings of subscriptions in Routing"): its window ⚙, its
// saved resets and what it spent stand on the main board (provider-glances.js).
import { CableFlow } from "./cable-flow.js";
import { ConsumerCards } from "./consumers.js";
import { appConfirm } from "./dialogs.js";
import { cloudApiIssuesHtml } from "./cloud.js";
import { t } from "./i18n.js";
import { OutputCells } from "./output-cells.js";
import { PoolCards } from "./pools.js";
import { PoolDock } from "./pool-dock.js";
import { PoolFlow } from "./pool-flow.js";
import { ModelScheduleEditor } from "./model-schedule.js";
import { JOB_LABELS, JOB_MARKS } from "./model-jobs.js";
import { localOutputGroups } from "./routers.js";
import { setTopology, topology, ui } from "./state.js";
import { StepCarry } from "./step-carry.js";
import { ACTIVITY_SEEN } from "./topology-activity.js";
import { flushPendingTopologyRender, renderTopology } from "./topology-render.js";
import {
  READING_LANDED,
  fetchSubscriptionUsage,
  fetchUpstreamErrors,
  previewSwitchLevel,
  saveSwitchLevel,
  subscriptionMetersHtml,
  subscriptionUsageHtml,
  switchDrag,
  upstreamErrorsHtml,
} from "./usage-stats.js";
import { api, copyText, escapeHtml, toast } from "./utils.js";

export class PoolBoard {
  // A cell's state → its lamp: lit when it serves, a ring when it does not run, amber on the way
  // up or down, red when it failed — and a ring for a state nobody said (OutputCells: "unknown").
  static LEDS = { running: "", stopped: "off", starting: "wait", stopping: "wait", failed: "bad", unknown: "off" };

  constructor({ call = api, notify = toast, confirm = appConfirm, apply = null, copy = copyText, win = globalThis, doc = globalThis.document,
    agents = () => ui.latestSystemMonitor?.latest?.agentProxies?.agents, now = () => Date.now() } = {}) {
    this.call = call;
    this.agents = agents;          // the monitor's rows of requests, by port: what the cables' drops are read from (pool-flow.js)
    this.now = now;
    this.notify = notify;
    this.copy = copy;
    this.confirm = confirm;
    this._apply = apply;
    this.win = win;
    this.doc = doc;
    this.top = null;               // the topology the last drawing read
    this.root = null;              // the page's container the board is drawn into (mount)
    this.expanded = new Set();     // "m:<machine>": the machines whose every cell is shown
    this.picking = null;           // the account whose "＋ model" is open: {accountId, query}
    this.scroll = null;            // where the board stood scrolled when the page drew it last: {top, left}
    this.history = new Set();      // the pools whose switch history is open
    this.settings = new Set();     // the pools whose "Pool settings" are open
    this.tests = new Set();        // the clients (by port) whose "Test as the client" is open
    this.probe = null;             // a client's test request in its window: {port, label, path, model, busy | result | error}
    this.probeModel = new Map();   // client port → the model of its set its tests name (the first, until chosen)
    this.catalogues = new Map();   // usage account id → {models, fetchedAt} | {loading: true} | {error}
    this.drag = null;              // a cable being drawn: {kind, from, dot, pointerId}
    this.drops = [];               // the cables the last drawing could not place, and why
    this.flowDrawn = "";           // what the last drawing lit (PoolFlow signature): a reading that would light the same is skipped
    this.flowing = new Set();      // the dots the last drawing ringed, the ends of the cables that carry a request
    this.carry = null;             // who carries a row to another place (StepCarry, made on mount)
    this.cardCarry = null;         // who carries a client's, set's or pool's card to another place (made on mount)
    this.trace = null;             // the path lit on the board: {key, pinned} — a card's cables up to its clients and down to its models
    this.chooser = null;           // the targets a click on an output lists: {kind, from, query, x, y}
    this.pending = false;          // a drawing asked for while something was held
    this.dock = new PoolDock();    // the strip below the columns: what the trace points at (pool-dock.js)
    this.dockDrawn = "";           // the strip as the last drawing left it: a drawing that would read the same is skipped
    // The pool's own doors — its deletion with what holds it, its order, its name — are the
    // pool cards' (pools.js): one way to do each, for both pages.
    this.actions = new PoolCards({ call, notify, confirm, apply: (top) => this.applied(top) });
    // When each model is open: its ⏱ and the window that sets it (model-schedule.js).
    this.schedule = new ModelScheduleEditor({ call, notify, apply: (top) => this.applied(top), redraw: () => this.redraw() });
    this.onMove = (event) => this.follow(event);
    this.onUp = (event) => this.release(event);
    this.onKey = (event) => { if (event.key === "Escape" && this.drag) this.endDrag(); };
  }

  // While a cable is carried, a row is carried or its order saved, or a level's handle is held,
  // the page must not be drawn anew: the drawing would drop what the pointer holds
  // (topology-render.js, topologyInteractionActive).
  get busy() {
    return !!this.drag || !!this.carry?.busy || !!this.cardCarry?.busy || !!switchDrag.active || !!this.schedule.painting;
  }

  // The controller's answer → the page: the page draws itself anew from it.
  applied(top) {
    if (this._apply) { this._apply(top); return; }
    if (top) setTopology(top);
    renderTopology();
  }

  // ── what the drawing reads ──────────────────────────────────────────

  runtime() {
    return this.top?.poolsRuntime || { available: false, pools: {}, events: [] };
  }

  account(id) {
    return (this.top?.cloudAccounts || []).find((a) => a.id === id) || null;
  }

  // Routing's router: its outputs are the fleet's cells and the engines' models, one per
  // `srv:<port>` and `eng:<id>` (caravan/admin/proxies_config.py).
  router() {
    const routers = this.top?.routers || [];
    return routers.find((r) => r.id === "router:default") || routers[0] || { outputs: [] };
  }

  cells() {
    return new OutputCells(this.top, this.router());
  }

  // The machines with their local outputs, each named as Routing names a machine.
  machines() {
    return localOutputGroups(this.router().outputs || []);
  }

  output(id) {
    for (const group of this.machines()) {
      const out = group.outs.find((o) => String(o.id) === String(id));
      if (out) return { out, group };
    }
    return null;
  }

  // The key a target is known by: an account's model, or a local output. "" for a row with no
  // cable — no key, no cable.
  static key(target) {
    if (target?.output) return `out:${target.output}`;
    if (target?.accountId && target?.model) return `acc:${target.accountId}/${target.model}`;
    return "";
  }

  // Target key → the names of the pools whose rows name it, in the pools' order.
  static uses(pools) {
    const map = new Map();
    for (const pool of pools || []) {
      for (const row of pool.steps || []) {
        const key = PoolBoard.key(row);
        if (!key) continue;
        if (!map.has(key)) map.set(key, []);
        const name = String(pool.name || pool.id);
        if (!map.get(key).includes(name)) map.get(key).push(name);
      }
    }
    return map;
  }

  // The models an account's card shows (the owner, 2026-10-12: "only the ones I added"): the ones
  // added to it, in the order they were added, then any a pool's row names that the list lacks — a
  // row's cable needs a model to land on, and one left out would be dropped without a word.
  static shown(added = [], named = []) {
    const out = [];
    for (const model of [...added, ...named]) if (model && !out.includes(model)) out.push(model);
    return out;
  }

  // How many models "＋ model" lists at once: OpenRouter's list has hundreds, and the search finds the rest.
  static PICK_ROWS = 60;

  // What "＋ model" offers: the account's chat models not on its card yet — those whose id or name
  // holds what was typed, in any case — at most PICK_ROWS of them, and what the rest count. When the
  // search finds none, what was typed is offered as it is: a list lags behind its provider (offered
  // beside models found, a part of an id read as a model of its own). `chat` counts the
  // list's chat models and `free` the ones left to add before the search: a list with none and a
  // list all on the card are two facts, said apart.
  static candidates(catalogue, shown = [], query = "", limit = PoolBoard.PICK_ROWS) {
    const typed = String(query || "").trim();
    const want = typed.toLowerCase();
    const chat = (catalogue?.models || []).filter((m) => m && m.chat && m.id);
    const free = chat.filter((m) => !shown.includes(String(m.id)));
    const found = want ? free.filter((m) => `${m.id} ${m.name || ""}`.toLowerCase().includes(want)) : free;
    const known = shown.includes(typed) || free.some((m) => String(m.id) === typed);
    return { models: found.slice(0, limit), more: Math.max(0, found.length - limit), typed: typed && !known && !found.length ? typed : "",
      free: free.length, chat: chat.length };
  }

  // A model's window as the list says it: tokens in thousands; none said — nothing.
  static windowText(tokens) {
    const n = Number(tokens);
    return n > 0 ? `${Math.round(n / 1000)}K` : "";
  }

  // A machine's rows: the cells a row names and the ones not stopped, in port order; the stopped
  // cells no row names fold under one button while there are two or more of them — a button that
  // hides one row saves nothing (the rule OutputCells.split keeps for the old Routing).
  static foldCells(outs, stateOf, named, expanded = false) {
    const quiet = (outs || []).filter((o) => stateOf(o) === "stopped" && !named(o));
    if (expanded || quiet.length < 2) return { shown: [...(outs || [])], quiet: [], folded: quiet.length >= 2 };
    return { shown: outs.filter((o) => !quiet.includes(o)), quiet, folded: true };
  }

  // A cable between two points: it leaves its output going right and enters its input from the left.
  static curve(a, b) {
    const dx = Math.max(40, (b.x - a.x) / 2);
    const n = (v) => Math.round(v * 10) / 10;
    return `M ${n(a.x)} ${n(a.y)} C ${n(a.x + dx)} ${n(a.y)}, ${n(b.x - dx)} ${n(b.y)}, ${n(b.x)} ${n(b.y)}`;
  }

  // A local output as rows and lists name it: a cell — or an engine's model — by its name and its
  // port; a model of a machine's entry by its name alone: its port is the machine's entry, every
  // model's (1.3.506).
  static outLabel(out, cells) {
    const name = cells.name(out);
    return String(out?.upstreamType || "") === "machine" ? name : `${name} :${out.upstreamPort}`;
  }

  // Where a local output stands, as a row's target and the chooser say it: its machine, and the port
  // of a cell or an engine.
  static where(out, group) {
    const machine = `🖥 ${group?.name || ""}`;
    return String(out?.upstreamType || "") === "machine" ? machine : `${machine} :${out?.upstreamPort}`;
  }

  // A row as the windows name it: its model and where it stands, or that it has no cable.
  rowName(row) {
    if (row?.kind === "account") {
      const account = this.account(row.accountId);
      return `${row.model} · ${account?.name || row.accountId}`;
    }
    if (row?.kind === "output") {
      const found = this.output(row.output);
      return found ? PoolBoard.outLabel(found.out, this.cells()) : String(row.output);
    }
    return t("poolNotConnected");
  }

  // The levels of one subscription model: its own pair, or the pair of a model nobody set — the
  // controller's default, never one of the page's. No reading from the controller, no handles:
  // `max` 0 draws none (usage-stats.js, subscriptionLimitRowHtml).
  levelsOf(accountId, model) {
    const levels = this.top?.modelLevels || {};
    const own = levels.set?.[accountId]?.[model];
    return { ...(own || levels.default || { stopAt: {}, switchAt: {} }), max: Number(levels.max || 0) };
  }

  // ── reading what the drawing needs ──────────────────────────────────

  // An account's catalogue, read once a page: the step window's reading (GET
  // /api/cloud-accounts/catalogue). None yet — null, and the card says it is being read.
  catalogue(owner) {
    const entry = this.catalogues.get(owner);
    if (entry) return entry;
    this.catalogues.set(owner, { loading: true });
    Promise.resolve()
      .then(() => this.call(`/api/cloud-accounts/catalogue?id=${encodeURIComponent(owner)}`))
      .then((res) => this.catalogues.set(owner, { models: Array.isArray(res?.models) ? res.models : [], fetchedAt: res?.fetchedAt ?? null }))
      .catch((err) => this.catalogues.set(owner, { error: String(err?.message || err) }))
      .finally(() => this.redraw());
    return this.catalogues.get(owner);
  }

  // A subscription's limits, read the main board's way (usage-stats.js); the board is drawn anew
  // when a reading lands (READING_LANDED, registered on mount) — a read the cache skips lands nothing.
  readUsage(owner) {
    Promise.resolve(fetchSubscriptionUsage(owner)).catch(() => {});
  }

  // ── drawing ─────────────────────────────────────────────────────────

  // The page draws the board whole (renderTopology), the scrolled box with it: where it stood is read
  // here, from the box about to be replaced, and given to the new one on mount — a column scrolled to
  // an account's card jumped back to the top with every drawing (a model added, a cable drawn). Since
  // 1.3.548 the columns scroll, each on its own, and the box only across: each column's place is kept too.
  html(top = topology) {
    this.top = top || {};
    const box = this.root?.querySelector?.("[data-pb-root]");
    this.scroll = box ? { top: Number(box.scrollTop) || 0, left: Number(box.scrollLeft) || 0, columns: PoolBoard.columnScrolls(this.root) } : null;
    return `<div class="pb" data-pb-root data-t="pool-board">${this.inner()}</div>`;
  }

  // Where each column stands, by the mark it is known by (`data-pb-scroll`), and the same given back to
  // the columns of a board drawn anew: a drawing replaces them, and a column scrolled down to a card would
  // go back to its top with every reading that lands.
  static columnScrolls(root) {
    const tops = {};
    for (const col of root?.querySelectorAll?.("[data-pb-scroll]") || []) tops[col.dataset.pbScroll] = Number(col.scrollTop) || 0;
    return tops;
  }

  static scrollColumns(root, tops) {
    for (const col of root?.querySelectorAll?.("[data-pb-scroll]") || []) {
      const top = Number(tops?.[col.dataset.pbScroll]) || 0;
      if (!top) continue;
      col.scrollTop = top;
      // At once, not with the scroll event that follows: a column drawn anew would show its head without the strip for a frame.
      col.classList?.add("scrolled");
    }
  }

  inner() {
    this.schedule.set(this.top);
    return `<div class="pb-cols" data-pb-cols>
      <section class="pb-col" data-t="pb-clients">${this.clientsHtml()}</section>
      <section class="pb-col sets" data-t="pb-sets">${this.setsHtml()}</section>
      <section class="pb-col" data-pb-pools-drop data-pb-drop-hint="${escapeHtml(t("pbDropNewPool"))}" data-t="pb-pools">${this.poolsHtml()}</section>
      <section class="pb-col" data-t="pb-models">${this.modelsHtml()}</section>
      <svg class="pb-cables" data-pb-cables data-t="pb-cables" aria-hidden="true"></svg>
      <svg class="pb-cables pb-live-layer" data-pb-live-layer aria-hidden="true"></svg>
    </div>${this.dockHtml()}${this.probeHtml()}${this.schedule.html()}${this.chooserHtml()}`;
  }

  head(title, button) {
    return `<div class="pb-col-head"><span>${escapeHtml(title)}</span>${button}</div>`;
  }

  // A column is its head, which stays where it is, and under it its body: the list of its cards, which is what scrolls and
  // is the mark the scroll is kept by (`data-pb-scroll`) across drawings. The owner, 2026-10-18: "the headings outside the area
  // I scroll, shown always — it is not pretty when I scroll a column down": until 1.3.573 the head was the first child of the
  // scrolling column and stuck to its top, so the cards passed under it. The cards that can be put in another order name the list
  // they are carried in (`data-pb-list`); the models' column has no such list.
  static column(key, head, body, { list = true } = {}) {
    return `${head}<div class="pb-col-body"${list ? ` data-pb-list="${key}"` : ""} data-pb-scroll="${key}">${body}</div>`;
  }

  // A card in its column's list: the seat it is carried from (StepCarry, `cardCarry`) — it stays as
  // the empty place while the card travels — and the card's grip, in its head (the owner,
  // 2026-10-12: "the order of the blocks in Clients, Sets and Pools changed by dragging").
  static seat(id, html) {
    return `<div class="pb-seat" data-pb-seat="${escapeHtml(String(id))}">${html}</div>`;
  }

  static gripHtml() {
    return `<span class="pb-card-grip" data-pb-card-grip tabindex="0" role="button" title="${escapeHtml(t("pbCardGrip"))}" aria-label="${escapeHtml(t("pbCardGrip"))}">⠿</span>`;
  }

  // Clients and subscriptions are added on the main board (the owner, 2026-10-12): Routing's
  // columns of clients and of models have no "＋" of their own; it connects what is there.
  clientsHtml() {
    const head = this.head(t("topologyClientsSection"), ""), entry = this.entryHtml();
    const clients = ConsumerCards.of(this.top);
    if (!clients.length) return PoolBoard.column("clients", head, `${entry}<p class="pb-empty" data-t="pb-no-clients">${escapeHtml(t("pbNoClients"))}</p>`);
    return PoolBoard.column("clients", head, entry + clients.map((c) => PoolBoard.seat(c.port, this.clientHtml(c))).join(""));
  }

  // A client's card says who it is, how many models it sees and whether it was refused (the owner,
  // 2026-10-13: "the same address stood on all four cards, and sinapse had seven lines of links"): its
  // address, links, tests and errors are in the strip below, while the pointer is on the card or the card
  // is pinned.
  clientHtml(c) {
    const port = escapeHtml(String(c.port));
    const set = String(c.set || "");
    const paused = ["paused", "drain"].includes(String(c.mode || "open"));
    const missed = PoolBoard.missBadge(c);
    const badge = missed ? `<span class="pb-miss-badge" data-t="pb-client-misses-badge" title="${escapeHtml(t("pbClientMisses"))}">⚠ ${escapeHtml(missed)}</span>` : "";
    return `<article class="pb-card pb-client${paused ? " paused" : ""}" data-pb-client="${port}" data-pb-node="client:${port}" data-t="pb-client" data-t-id="${port}" data-t-state="${set ? "cabled" : "none"}">
      ${PoolBoard.gripHtml()}<span class="pb-client-name" title="${escapeHtml(String(c.label || ""))}">${escapeHtml(String(c.label || ""))}</span>
      <span class="pb-key" title="${escapeHtml(t("consumerKeyTitle"))}">🔑 …${escapeHtml(String(c.keyTail || ""))}</span>
      ${set ? "" : `<span class="pb-client-none">${escapeHtml(t("pbClientNoSet"))}</span>`}
      <span class="pb-dot out${set ? "" : " open"}" data-pb-out="client" data-port="${port}" title="${escapeHtml(t("pbDragClientSet"))}"></span>
      <span class="pb-client-sub"><span>${escapeHtml(t("pbClientModelsN", { n: String((c.models || []).length) }))}</span>${badge}</span>
    </article>`;
  }

  // How many times the client was answered with an error over the journal's days, as far as the lines
  // the card keeps say — "+" when lines were cut off, so at least that many. None — no badge.
  static missBadge(c) {
    const n = (c?.misses?.items || []).reduce((sum, m) => sum + (Number(m.count) || 0), 0);
    return n ? `${n}${Number(c.misses.more) > 0 ? "+" : ""}` : "";
  }

  // The address the entry gave its clients, said once under the column's head, with ⧉ (the owner,
  // 2026-10-13: the same address stood on all four cards): without its scheme — the column is narrow, the
  // hint names it whole and ⧉ copies it whole. Without the entry there is no address.
  entryHtml() {
    const base = String(this.top?.entry?.url || "");
    if (!base) return "";
    return `<div class="pb-entry" data-t="pb-entry"><span class="pb-client-url" title="${escapeHtml(`${t("consumerEntryTitle")}: ${base}`)}">${escapeHtml(base.replace(/^https?:\/\//i, ""))}</span>`
      + `<button class="pb-tool" type="button" data-pb-copy-url data-t="pb-client-copy" title="${escapeHtml(t("consumerCopyEntry"))}" aria-label="${escapeHtml(t("consumerCopyEntry"))}">⧉</button></div>`;
  }

  // What a client gets there (the owner, 2026-10-12: "links on each client's card, to get the same data the
  // client gets"): its two questions by GET — the model list and each model of its set — each opening what
  // the entry answers its key. The controller asks with the key (GET /api/consumers/ask): the page never
  // holds one, and a link to the entry itself would only be refused for want of it. Without the entry
  // there is nothing to ask; without a set, no model to name. They stand in the strip below.
  asksHtml(c) {
    if (!String(this.top?.entry?.url || "")) return "";
    const ask = (path, id) => `<a class="pb-ask" href="${escapeHtml(`/api/consumers/ask?port=${encodeURIComponent(String(c.port))}&path=${encodeURIComponent(path)}`)}"`
      + ` data-t="pb-client-ask" data-t-id="${id}" title="${escapeHtml(t("pbClientAskTitle"))}">${escapeHtml(path)}</a>`;
    const models = (c.models || []).map(String);
    return `<div class="pb-client-asks" data-t="pb-client-links">${ask("/v1/models", "list")}${models.map((m) => ask(`/v1/models/${m}`, "model")).join("")}</div>`;
  }

  // The work a client asks for by POST, each a test the controller sends as the client: the paths
  // are the controller's table (topology.clientProbes), the one that sends them. A set of more than
  // one model asks which of them the test names. Shut under "Test as the client" until opened —
  // six buttons are four lines of the narrow card — and kept open while the board is drawn again.
  probesHtml(c, models) {
    const table = this.top?.clientProbes || [];
    if (!table.length) return "";
    const open = this.tests.has(String(c.port));
    const head = `<button class="pb-tests-head${open ? " open" : ""}" type="button" data-pb-tests aria-expanded="${open}" data-t="pb-client-tests">`
      + `${escapeHtml(t("pbProbeRow"))}</button>`;
    if (!open) return head;
    const buttons = table.map((p) => `<button class="pb-probe-btn" type="button" data-pb-probe="${escapeHtml(String(p.path))}"`
      + ` data-t="pb-client-probe" data-t-id="${escapeHtml(String(p.path))}" title="${escapeHtml(t(p.paid ? "pbProbePaidTitle" : "pbProbeTitle"))}">`
      + `${escapeHtml(String(p.path).replace(/^\/v1\//, ""))} ▶</button>`).join("");
    return `${head}<span class="pb-client-probes">${this.probeModelHtml(c, models)}${buttons}</span>`;
  }

  // Which model of the client's set its tests name: a choice when the set holds more than one.
  probeModelHtml(c, models) {
    if (models.length < 2) return "";
    const chosen = this.probeModelOf(c);
    return `<select class="pb-probe-model" data-pb-probe-model data-t="pb-client-probe-model" aria-label="${escapeHtml(t("pbProbeModel"))}" title="${escapeHtml(t("pbProbeModel"))}">`
      + models.map((m) => `<option value="${escapeHtml(m)}"${m === chosen ? " selected" : ""}>${escapeHtml(m)}</option>`).join("") + "</select>";
  }

  // The model a client's test names: the one chosen while it is still in the set, else the first.
  probeModelOf(c) {
    const models = (c?.models || []).map(String);
    const chosen = this.probeModel.get(String(c?.port));
    return models.includes(chosen) ? chosen : (models[0] || "");
  }

  // What the client asked and was answered with an error over the last 30 days (the owner,
  // 2026-10-12: "to see, say, that it asked /api/show"): the controller's reading of the proxy's
  // journal (caravan/admin/client_misses.py), newest first, the rest counted. No errors, or no
  // reading — no list: the card stays as clean as Routing's other cards.
  missesHtml(c) {
    const items = c?.misses?.items || [];
    if (!items.length) return "";
    const lines = items.map((m) => `<li class="pb-miss" data-t="pb-client-miss" title="${escapeHtml(t("pbClientMissTitle", { reason: String(m.reason || "—") }))}">`
      + `<code>${escapeHtml([m.method, m.path].filter(Boolean).join(" "))}</code> <b>${escapeHtml(String(m.status))}</b>`
      + ` <span>×${escapeHtml(String(m.count))} · ${escapeHtml(PoolBoard.when(m.last))}</span></li>`).join("");
    const more = c.misses.more ? `<li class="pb-miss-more">${escapeHtml(t("pbClientMissesMore", { n: String(c.misses.more) }))}</li>` : "";
    return `<div class="pb-client-misses" data-t="pb-client-misses"><span class="pb-misses-head">⚠ ${escapeHtml(t("pbClientMisses"))}</span><ul>${lines}${more}</ul></div>`;
  }

  // A moment of the journal as a card says it: day, month and time, in the page's language.
  static when(seconds) {
    const n = Number(seconds);
    return n > 0 ? new Date(n * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
  }

  // An answer's size and time as the window says them.
  static size(bytes) {
    const n = Number(bytes) || 0;
    return n < 1024 ? `${n} B` : n < 1048576 ? `${Math.round(n / 102.4) / 10} KB` : `${Math.round(n / 104857.6) / 10} MB`;
  }

  static took(ms) {
    const n = Number(ms) || 0;
    return n < 1000 ? `${n} ms` : `${(n / 1000).toFixed(1)} s`;
  }

  // An answer's text as it is easiest to read: JSON laid out, anything else as it came.
  static pretty(text, contentType) {
    if (!/json/i.test(String(contentType || ""))) return String(text ?? "");
    try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return String(text ?? ""); }
  }

  // The test's window, over the board: what went out as the client, and what came back — the
  // status, type, time and size, then the body laid out, or a player for speech. Closed by ✕ or
  // Escape; a drawing of the board keeps it, it is the board's own state.
  probeHtml() {
    const p = this.probe;
    if (!p) return "";
    const base = String(this.top?.entry?.url || "").replace(/\/v1\/?$/, "");
    const close = `<button class="pb-tool" type="button" data-pb-probe-close data-t="pb-probe-close" title="${escapeHtml(t("topologyClose"))}" aria-label="${escapeHtml(t("topologyClose"))}">✕</button>`;
    const head = `<header class="pb-probe-head"><b>${escapeHtml(String(p.label || p.port))}</b><code>POST ${escapeHtml(base + p.path)}</code>${close}</header>`;
    const state = p.busy ? "busy" : p.error ? "failed" : "done";
    let body;
    if (p.busy) body = `<p class="pb-probe-note">${escapeHtml(t("pbProbeWaiting"))}</p>`;
    else if (p.error) body = `<p class="pb-probe-note bad">${escapeHtml(t("pbProbeFailed", { error: p.error }))}</p>`;
    else {
      const r = p.result || {};
      const ok = Number(r.status) >= 200 && Number(r.status) < 300;
      const said = `<p class="pb-probe-status ${ok ? "ok" : "bad"}" data-t="pb-probe-status"><b>${escapeHtml(String(r.status))}</b>`
        + ` · ${escapeHtml(String(r.contentType || "—"))} · ${escapeHtml(PoolBoard.took(r.ms))} · ${escapeHtml(PoolBoard.size(r.bytes))}</p>`;
      const shown = r.audio
        ? `<audio controls src="data:${escapeHtml(String(r.contentType || "audio/mpeg"))};base64,${escapeHtml(String(r.audio))}"></audio>`
        : `<pre class="pb-probe-text">${escapeHtml(PoolBoard.pretty(r.text, r.contentType))}</pre>`
          + (r.cut ? `<p class="pb-probe-note">${escapeHtml(t("pbProbeCut", { n: String(r.bytes) }))}</p>` : "");
      body = `<h4>${escapeHtml(t("pbProbeSent"))}</h4><pre class="pb-probe-text">${escapeHtml(String(r.request?.sent || ""))}</pre>`
        + `<h4>${escapeHtml(t("pbProbeAnswer"))}</h4>${said}${shown}`;
    }
    return `<div class="pb-probe" role="dialog" aria-modal="true" data-t="pb-probe" data-t-state="${state}"><div class="pb-probe-box">${head}${body}</div></div>`;
  }

  // A test of the card's client: the shortest standard request of that kind, sent by the
  // controller with the client's key (POST /api/consumers/probe) and naming the model the client
  // calls. A test that may cost money — a picture — is asked about first. The window waits, then
  // shows the answer, or why the controller could not ask; an answer for a test the window no
  // longer shows lands nowhere.
  async runProbe(port, path) {
    const client = ConsumerCards.of(this.top).find((c) => String(c.port) === String(port));
    const probe = (this.top?.clientProbes || []).find((p) => p.path === path);
    if (!client || !probe) return null;
    if (probe.paid) {
      const sure = await this.confirm(t("pbProbePaidAsk", { client: String(client.label || port) }),
        { title: t("pbProbePaidTitle"), danger: false, confirmLabel: t("pbProbeSend") });
      if (!sure) return null;
    }
    const asked = { port: Number(port), label: String(client.label || ""), path, model: this.probeModelOf(client) };
    this.probe = { ...asked, busy: true };
    this.redraw();
    let landed;
    try {
      landed = { ...asked, result: await this.call("/api/consumers/probe", { method: "POST", body: JSON.stringify({ port: asked.port, path, model: asked.model }) }) };
    } catch (err) {
      landed = { ...asked, error: String(err?.message || err) };
    }
    if (this.probe?.port !== asked.port || this.probe?.path !== path) return null;
    this.probe = landed;
    this.redraw();
    this.root?.querySelector?.("[data-pb-probe-close]")?.focus?.();
    return landed;
  }

  closeProbe() {
    if (!this.probe) return null;
    this.probe = null;
    this.redraw();
    return true;
  }

  // ⧉ beside a client's address: the address on the clipboard, or — when the page may not write
  // there — in the toast, to be copied by hand.
  async copyUrl() {
    const url = String(this.top?.entry?.url || "");
    if (!url) return null;
    const copied = await this.copy(url);
    this.notify(copied ? t("consumerEntryCopied") : url);
    return copied;
  }

  // The sets (the owner, 2026-10-12, «Набор»; named "ID sets" 2026-10-14, as the pools' column is "ID (Pools)": the
  // name of a pool is the id a client puts in `model`): what clients see as their models. A client's cable
  // comes into a set, and the set's rows go on to pools — one row per model the client sees, by
  // the pool's name. The "＋" row at a set's foot carries a new cable onto a pool, pressed on its
  // dot or anywhere else on it (newOutHtml); a click on a cable cuts it. One set may serve several
  // clients.
  setsHtml() {
    const head = this.head(t("pbSetsSection"),
      `<button class="pb-add" type="button" data-pb-add-set data-t="pb-add-set">＋ ${escapeHtml(t("pbSetNew"))}</button>`);
    const sets = this.top?.sets || [];
    if (!sets.length) return PoolBoard.column("sets", head, `<p class="pb-empty" data-t="pb-no-sets">${escapeHtml(t("pbNoSets"))}</p>`);
    return PoolBoard.column("sets", head, sets.map((set) => PoolBoard.seat(set.id, this.setHtml(set))).join(""));
  }

  setHtml(set) {
    const id = escapeHtml(String(set.id));
    const pools = new Map((this.top?.pools || []).map((p) => [p.id, p]));
    const rows = (set.pools || []).map((pid) => {
      const pool = pools.get(pid);
      const name = escapeHtml(String(pool?.name || pid));
      return `<li class="pb-set-model" data-pb-set-pool="${escapeHtml(String(pid))}" data-pb-node="setpool:${id}/${escapeHtml(String(pid))}" data-t="pb-set-model" data-t-id="${id}/${escapeHtml(String(pid))}">`
        + `<span class="pb-set-model-name" title="${name}">${name}</span>${PoolBoard.kindHtml(pool?.kind)}<span class="pb-dot out" data-pb-set-out></span></li>`;
    }).join("");
    return `<article class="pb-card pb-set" data-pb-set="${id}" data-pb-node="set:${id}" data-t="pb-set" data-t-id="${id}">
      ${PoolBoard.pullHtml("set")}
      <header class="pb-pool-head">
        ${PoolBoard.gripHtml()}<input class="pb-pool-name" data-pb-set-name value="${escapeHtml(String(set.name || ""))}" aria-label="${escapeHtml(t("pbSetName"))}" title="${escapeHtml(t("pbSetName"))}" data-t="pb-set-name">
        <button class="pb-tool del" type="button" data-pb-set-delete data-t="pb-set-delete" title="${escapeHtml(t("pbSetDelete"))}" aria-label="${escapeHtml(t("pbSetDelete"))}">✕</button>
      </header>
      ${rows ? `<ol class="pb-set-models">${rows}</ol>` : `<p class="pb-set-empty">${escapeHtml(t("pbSetEmpty"))}</p>`}
      ${rows ? "" : PoolBoard.newOutHtml("set", "pb-set-add", t("pbSetAddModel"), t("pbDragSet"))}
    </article>`;
  }

  // What a model does, as the controller says its pool's rows do together (`pool.kind`,
  // caravan/common/model_kinds.py; 1.3.502 — what GET /v1/models tells the clients): the jobs'
  // marks, a 🖼 for a chat that takes pictures, the languages in the hint; ⚠ when the rows do
  // different work, said because the list says nothing of such a pool. Unknown — nothing.
  static kindHtml(kind) {
    if (!kind) return "";
    if (kind.mixed) {
      return `<span class="pb-kind mixed" data-t="pb-kind" data-t-state="mixed" title="${escapeHtml(t("pbKindMixed"))}">⚠</span>`;
    }
    const jobs = (kind.jobs || []).filter((job) => JOB_MARKS[job]);
    if (!jobs.length) return "";
    const pictures = (kind.inputs || []).includes("image");
    const said = [jobs.map((job) => t(JOB_LABELS[job])).join(", "), pictures ? t("pbKindPictures") : "",
      (kind.languages || []).length ? kind.languages.join(", ") : ""].filter(Boolean).join(" · ");
    return `<span class="pb-kind" data-t="pb-kind" data-t-state="known" title="${escapeHtml(said)}">`
      + `${escapeHtml(jobs.map((job) => JOB_MARKS[job]).join("") + (pictures ? "🖼" : ""))}</span>`;
  }

  // A "＋" row that starts a new cable — a set's onto a pool, a pool's onto a model: a dashed row
  // with a dashed dot, carried by any point of it (the owner, 2026-10-12: "drag not only by the
  // circle but by the whole row"). It does nothing on a click: what it adds needs the place the
  // cable lands on.
  static newOutHtml(kind, testName, label, hint) {
    return `<div class="pb-new-out" data-pb-grab data-t="${escapeHtml(testName)}" title="${escapeHtml(hint)}"><span>＋ ${escapeHtml(label)}</span>`
      + `<span class="pb-dot out open" data-pb-out="${escapeHtml(kind)}" title="${escapeHtml(hint)}"></span></div>`;
  }

  poolsHtml() {
    const head = this.head(t("pbPoolsSection"),
      `<span class="pb-head-tools"><button class="pb-add" type="button" data-pb-arrange data-t="pb-arrange" title="${escapeHtml(t("pbArrangeTitle"))}">⇅ ${escapeHtml(t("pbArrange"))}</button>`
      + `<button class="pb-add" type="button" data-pb-add-pool data-t="pb-add-pool">＋ ${escapeHtml(t("poolNew"))}</button></span>`);
    const pools = this.top?.pools || [];
    if (!pools.length) return PoolBoard.column("pools", head, `<p class="pb-empty" data-t="pb-no-pools">${escapeHtml(t("pbNoPools"))}</p>`);
    return PoolBoard.column("pools", head, pools.map((pool) => PoolBoard.seat(pool.id, this.poolHtml(pool))).join(""));
  }

  // A pool is its name, what it does and its rows (the owner, 2026-10-12: "pools of one model and of several
  // look the same"; 2026-10-13: "crowded and motley", and of three mockups "details in a strip below"): one
  // row is drawn as one line under the pool's name — "= the model" —, two rows and more are a ladder with
  // "N in turn" in the head, and a row says its state by a pill only when the state is news. What the pool
  // does between its rows, its settings, its switch history and the "＋ row" that adds a row stand in the strip
  // below (poolDetailsHtml) while the card is pointed at or pinned. A pool with no row keeps the "＋ row" on its
  // card: it is all it needs.
  poolHtml(pool) {
    const id = escapeHtml(pool.id);
    const runtime = this.runtime();
    const state = runtime.available ? runtime.pools?.[pool.id] : null;
    const steps = pool.steps || [];
    const look = steps.length === 1 ? " single" : steps.length > 1 ? " turns" : "";
    const rows = steps.map((row, index) => this.rowHtml(pool, row, index, state)).join("");
    const turns = steps.length > 1
      ? `<span class="pb-turns" data-t="pb-pool-turns" title="${escapeHtml(t("pbTurnTitle"))}">⇣ ${escapeHtml(t("pbPoolTurns", { n: String(steps.length) }))}</span>` : "";
    return `<article class="pb-card pb-pool${look}" data-pb-pool="${id}" data-pool-id="${id}" data-pb-node="pool:${id}" data-t="pb-pool" data-t-id="${id}">
      ${PoolBoard.pullHtml("pool")}
      <header class="pb-pool-head">
        ${PoolBoard.gripHtml()}
        <span class="pb-pool-id" aria-hidden="true">id:</span>
        <input class="pb-pool-name" data-pb-pool-name value="${escapeHtml(String(pool.name || ""))}" aria-label="${escapeHtml(t("poolName"))}" title="${escapeHtml(t("poolName"))}" data-t="pb-pool-name">
        ${turns}${PoolBoard.kindHtml(pool.kind)}
        <button class="pb-tool del" type="button" data-pb-pool-delete data-t="pb-pool-delete" title="${escapeHtml(t("poolDelete"))}" aria-label="${escapeHtml(t("poolDelete"))}">✕</button>
      </header>
      <ol class="pool-ladder pb-rows">${rows}</ol>
      ${steps.length ? "" : PoolBoard.newOutHtml("new-row", "pb-add-row", t("pbAddRow"), t("pbDragRow"))}
    </article>`;
  }

  // When the pool goes on from `row` to the next one — said between the two (1.3.503): a subscription's
  // model once a window has no more left than its switch level (caravan/common/usage_reserve.py; the
  // switch is never below the stop, so it says both), a cell when it is busy or silent, anything else
  // when it refuses. The levels are the model's own (`levelsOf`).
  turnText(row) {
    if (row?.kind === "output") return t("pbTurnCell");
    if (row?.kind !== "account") return "";
    const account = this.account(row.accountId);
    if (!account || !PoolCards.subscription(account)) return t("pbTurnRefused");
    const said = PoolBoard.levelsText(this.levelsOf(row.accountId, row.model).switchAt);
    return said ? t("pbTurnLeft", { levels: said }) : t("pbTurnRefused");
  }

  // Switch levels as the note says them: each window's share left, the shortest window first —
  // "30% (5h) · 20% (7d)". No level — nothing: the row goes on only when it refuses.
  static levelsText(levels) {
    const span = (seconds) => (seconds < 172800 ? `${Math.round(seconds / 3600)}h` : `${Math.round(seconds / 86400)}d`);
    return Object.entries(levels || {}).map(([seconds, pct]) => [Number(seconds), Number(pct)])
      .filter(([seconds, pct]) => seconds > 0 && pct > 0).sort((a, b) => a[0] - b[0])
      .map(([seconds, pct]) => `${pct}% (${span(seconds)})`).join(" · ");
  }

  // "Pool settings" under the rows, shut until opened (the owner, 2026-10-12: back on the pool's
  // card — they left with the main board's pool cards in 1.3.486): the window the pool states to its
  // clients, blank for "not stated", and the switch that takes the smallest window its rows' models
  // report instead. Under them, what the pool states now (`statedHtml`).
  settingsHtml(pool) {
    const open = this.settings.has(pool.id);
    const head = `<button class="pb-settings-head${open ? " open" : ""}" type="button" data-pb-settings aria-expanded="${open}" data-t="pb-settings">`
      + `${escapeHtml(t("poolSettings"))}</button>`;
    if (!open) return head;
    const stated = pool.contextLength ? String(pool.contextLength) : "";
    return `${head}<div class="pb-settings" data-t="pb-settings-panel">
        <label class="pb-window" title="${escapeHtml(t("poolWindowHint"))}"><span>${escapeHtml(t("topologyCloudContextLength"))}</span>
          <input type="number" min="1" step="1" inputmode="numeric" data-pb-pool-window data-t="pb-pool-window" value="${escapeHtml(stated)}" placeholder="${escapeHtml(t("topologyCloudContextEmpty"))}"></label>
        <label class="pb-check" title="${escapeHtml(t("poolWindowAutoHint"))}"><input type="checkbox" data-pb-pool-window-auto data-t="pb-pool-window-auto"${pool.contextAuto ? " checked" : ""}>`
      + `<span>${escapeHtml(t("poolWindowAuto"))}</span></label>
        ${this.statedHtml(pool)}
      </div>`;
  }

  // What the pool states to its clients in GET /v1/models — the controller's word (`window`,
  // caravan/admin/topology.py annotate_pool_windows), never worked out here: a number, or that it
  // states none. A reading without the word says nothing rather than "none".
  statedHtml(pool) {
    if (!pool || !Object.prototype.hasOwnProperty.call(pool, "window")) return "";
    const told = PoolBoard.windowText(pool.window);
    return told
      ? `<p class="pb-stated" data-t="pb-pool-window-stated" data-t-state="stated" title="${escapeHtml(String(pool.window))}">${escapeHtml(t("pbPoolWindowStated", { window: told }))}</p>`
      : `<p class="pb-stated none" data-t="pb-pool-window-stated" data-t-state="none">${escapeHtml(t("pbPoolWindowNone"))}</p>`;
  }

  // Why the proxy would, or would not, use this row now. Serving beats every reason, but only
  // on the proxy's own word; a row with no cable says so before the proxy does (its target's
  // place says it, so no pill repeats it), and so does an account no one signed in to. `quiet` marks the two
  // states that are no news — the row is fit and waits its turn, the proxy has not asked it yet — and only
  // those: a silent proxy, an unknown usage, a reason nobody knows are not quiet, they are what the owner
  // has to see.
  status(pool, row, state) {
    const word = (state?.steps || []).find((r) => r.stepId === row.id);
    // A model closed by its schedule now: the controller's word of this moment beats the proxy's
    // last one, which may be from before the window closed.
    const closed = this.schedule.closedWord(PoolBoard.key(row));
    if (closed) return { look: "closed", text: closed, title: "" };
    const cell = this.cellWord(row);
    if (cell) return cell;
    if (state?.selectedStepId === row.id && (!word || ["ready", "switch", "busy"].includes(word.reason))) {
      return { look: "serving", text: t("poolServing"), title: word?.reason === "switch" ? t("poolSwitchReached") : "" };
    }
    if (row.kind === "open") return { look: "open", text: t("poolNotConnected"), title: "" };
    if (row.kind === "account") {
      const account = this.account(row.accountId);
      if (account && !account.hasCredential) {
        return { look: "login", text: t(PoolCards.subscription(account) ? "poolLoginNeeded" : "cloudNoKeyYet"), title: "" };
      }
    }
    if (!this.runtime().available) return { look: "unknown", text: t("poolProxySilent"), title: "" };
    if (!word) return { look: "unknown", text: t("poolNoRequest"), title: "", quiet: true };
    const [key, look] = PoolCards.REASONS[word.reason] || ["poolUnavailable", "unknown"];
    return { look, text: t(key), title: String(word.reason || ""), quiet: word.reason === "ready" };
  }

  // A row of a cell that does not run now says so (1.3.504; the owner, 2026-10-12: "it is not shown that
  // the cable leads to a switched-off cell"): the controller's word of this moment, as a closed
  // schedule's — the proxy's last word may be from before the cell stopped, and "no request yet" read
  // as a cell ready to serve. A running cell, or one whose state nobody said, has the proxy's word.
  static CELL_LOOKS = { stopped: ["poolCellOff", "off-cell"], starting: ["starting", "off-cell"],
    stopping: ["rtCellStopping", "off-cell"], failed: ["failed", "missing"] };

  cellWord(row) {
    if (row?.kind !== "output") return null;
    const found = this.output(row.output);
    const said = found ? PoolBoard.CELL_LOOKS[this.cells().state(found.out)] : null;
    return said ? { look: said[1], text: t(said[0]), title: "" } : null;
  }

  // What a row's output is cabled to: a subscription's model with its account, a machine's cell
  // with its machine and port — or what is gone, said in red rather than drawn as a cable.
  targetHtml(row) {
    if (row.kind === "account") {
      const account = this.account(row.accountId);
      const model = escapeHtml(String(row.model || ""));
      if (!account) return `<span class="pb-target gone" title="${model}"><b>${model}</b><small>${escapeHtml(t("poolAccountGone"))}</small></span>`;
      return `<span class="pb-target" title="${model}"><b>${model}</b><small>☁ ${escapeHtml(String(account.name || account.id))}</small></span>`;
    }
    if (row.kind === "output") {
      const found = this.output(row.output);
      if (!found) return `<span class="pb-target gone"><b>${escapeHtml(String(row.output))}</b><small>${escapeHtml(t("poolOutputMissing"))}</small></span>`;
      const name = escapeHtml(this.cells().name(found.out));
      return `<span class="pb-target" title="${name}"><b>${name}</b><small>${escapeHtml(PoolBoard.where(found.out, found.group))}</small></span>`;
    }
    return `<span class="pb-target open">${escapeHtml(t("pbRowOpen"))}</span>`;
  }

  rowHtml(pool, row, index, state) {
    const rid = escapeHtml(row.id);
    const status = this.status(pool, row, state);
    const cabled = !!PoolBoard.key(row);
    const look = [status.look === "serving" ? " serving" : "", cabled ? "" : " open", row.enabled === false ? " off" : ""].join("");
    const single = (pool.steps || []).length === 1;
    return `<li class="pool-rung"><div class="pool-step pb-row${look}" data-pool-step="${rid}" data-pb-row="${rid}" data-pb-node="row:${escapeHtml(pool.id)}/${rid}" data-t="pb-row" data-t-id="${escapeHtml(pool.id)}/${rid}" data-t-state="${escapeHtml(status.look)}">
      ${single ? "" : `<span data-pool-grip tabindex="0" role="button" title="${escapeHtml(t("poolOrder"))}" aria-label="${escapeHtml(t("poolOrder"))}">⠿</span>
      <span class="pb-rank">${index + 1}</span>`}
      ${this.targetHtml(row)}
      ${PoolBoard.statusHtml(status)}
      <button class="pb-tool del" type="button" data-pb-row-remove data-t="pb-row-remove" title="${escapeHtml(t("poolStepRemove"))}" aria-label="${escapeHtml(t("poolStepRemove"))}">✕</button>
      <span class="pb-dot out${cabled ? "" : " open"}" data-pb-out="row" title="${escapeHtml(t("pbDragRow"))}"></span>
    </div></li>`;
  }

  // A row's state as its card says it: a pill with the words when the state is news — serving, closed, off,
  // missing, a sign-in asked for, a proxy that is silent — and a bare dot when it is no news (`quiet`, status()):
  // the dot is filled when the row is fit and hollow when the proxy has not asked it yet, and says its words in its
  // title and, in full, in the strip below. A row with no cable says nothing here: its target says it.
  static statusHtml(status) {
    if (status.look === "open") return "<span></span>";
    const look = escapeHtml(status.look);
    if (status.quiet) {
      return `<span class="pb-status ${look} quiet" role="img" title="${escapeHtml(status.text)}" aria-label="${escapeHtml(status.text)}"></span>`;
    }
    return `<span class="pb-status ${look}" title="${escapeHtml(status.title)}">${escapeHtml(status.text)}</span>`;
  }

  // The proxy's last switches between the pool's rows, newest first.
  events(pool) {
    return (this.runtime().events || []).filter((e) => e.poolId === pool.id).slice(-5).reverse();
  }

  historyHtml(pool, events) {
    const name = (id) => {
      const row = (pool.steps || []).find((s) => s.id === id);
      return row ? this.rowName(row) : String(id || "—");
    };
    return `<div class="pb-history" data-t="pb-history">${events.map((e) => `<div><time>${escapeHtml(new Date(Number(e.at) * 1000).toLocaleTimeString())}</time>`
      + `${escapeHtml(name(e.from))} → ${escapeHtml(name(e.to))}</div>`).join("")}</div>`;
  }

  modelsHtml() {
    const head = this.head(t("topologyModelsLabel"), "");
    const accounts = this.top?.cloudAccounts || [];
    const machines = this.machines();
    if (!accounts.length && !machines.length) return PoolBoard.column("models", head, `<p class="pb-empty" data-t="pb-no-models">${escapeHtml(t("pbNoModels"))}</p>`, { list: false });
    const uses = PoolBoard.uses(this.top?.pools || []);
    return PoolBoard.column("models", head, accounts.map((a) => this.accountHtml(a, uses)).join("") + machines.map((g) => this.machineHtml(g, uses)).join(""), { list: false });
  }

  // The one thing a model's card says of its pools: that none uses it. Which pools do stands in the strip, in the
  // route of the model; a model in a pool says nothing here (the owner, 2026-10-13: "crowded and motley").
  static unusedHtml() {
    return `<span class="pb-use none" data-t="pb-model-unused">${escapeHtml(t("pbInNoPool"))}</span>`;
  }

  // An account's card, as the mockup draws it (the owner, 2026-10-14): its name, and at the right what it says of itself — a lamp
  // lit while it is connected, amber while it waits for a sign-in or a key —; a subscription's limits as one line of meters;
  // a row for each model. The "＋ model" stands in the head, quiet until the card is pointed at; opened, its list takes
  // the card's foot.
  accountHtml(account, uses) {
    const id = escapeHtml(account.id);
    const subscription = PoolCards.subscription(account);
    // A test alias reads its original's limits and catalogue (CloudSources.quota_owner).
    const owner = String(account.testAliasOf || account.id);
    const shown = this.shownOf(account);
    const reads = subscription && !!account.hasCredential;
    if (reads) this.readUsage(owner);
    const rows = shown.map((model) => this.accountModelHtml(account, model, uses)).join("");
    // None added: said, with the way to add one, rather than a card that reads as "no models".
    const none = shown.length ? "" : `<p class="pb-src-empty" data-t="pb-models-none">${escapeHtml(t("pbModelsNone"))}</p>`;
    const picking = this.picking?.accountId === account.id;
    const name = escapeHtml(String(account.name || account.id));
    const word = t(account.hasCredential ? "cloudConnected" : (subscription ? "poolLoginNeeded" : "cloudNoKeyYet"));
    return `<article class="pb-card pb-src${shown.length ? "" : " empty"}" data-pb-account="${id}" data-t="pb-account" data-t-id="${id}">
      <div class="pb-src-head"><b title="${name}">${name}</b>${picking ? "" : this.addModelHtml(account)}
        <span class="pb-src-note" data-t="pb-account-state" data-t-state="${account.hasCredential ? "connected" : "waiting"}"><i class="pb-led${account.hasCredential ? "" : " wait"}" aria-hidden="true"></i>${escapeHtml(word)}</span>
      </div>
      ${this.issuesHtml(account, subscription)}
      ${reads ? this.limitsHtml(owner, account, shown) : ""}
      ${rows}${none}${picking ? this.pickerHtml(account, owner, shown) : ""}
    </article>`;
  }

  // The models on an account's card: the ones the controller says were added to it
  // (`addedModels`), then any a pool's row names.
  shownOf(account) {
    const named = [];
    for (const pool of this.top?.pools || []) {
      for (const row of pool.steps || []) {
        if (row.kind === "account" && row.accountId === account.id && !named.includes(row.model)) named.push(row.model);
      }
    }
    return PoolBoard.shown(this.top?.addedModels?.[account.id] || [], named);
  }

  // "＋ model" in an account's head: it opens the account's list in place (pickerHtml).
  addModelHtml(account) {
    const id = escapeHtml(account.id);
    return `<button class="pb-add-model" type="button" data-pb-add-model="${id}" data-t="pb-add-model" data-t-id="${id}">＋ ${escapeHtml(t("pbAddModel"))}</button>`;
  }

  // "＋ model" open: a search over the account's list and the models it finds, each a button that
  // puts it on the card. The field keeps its place while the board is drawn again (redraw); what
  // is typed redraws the list under it alone (find).
  pickerHtml(account, owner, shown) {
    const id = escapeHtml(account.id);
    const query = String(this.picking?.query || "");
    return `<div class="pb-picker" data-pb-picker="${id}" data-t="pb-picker" data-t-id="${id}">
      <div class="pb-picker-head">
        <input class="pb-picker-find" type="search" data-pb-pick-query data-t="pb-pick-query" value="${escapeHtml(query)}"
          placeholder="${escapeHtml(t("poolStepFind"))}" aria-label="${escapeHtml(t("poolStepFind"))}" autocomplete="off" spellcheck="false">
        <button class="pb-tool" type="button" data-pb-pick-close data-t="pb-pick-close" title="${escapeHtml(t("topologyClose"))}" aria-label="${escapeHtml(t("topologyClose"))}">✕</button>
      </div>
      <div class="pb-picker-body" data-pb-pick-body>${this.pickBodyHtml(account, owner, shown, query)}</div>
    </div>`;
  }

  // The models the search finds, and what the board knows of the list instead of an empty one: no
  // sign-in, being read, unreadable, never read, no chat model in it, all of it on the card
  // already, nothing found.
  pickBodyHtml(account, owner, shown, query) {
    const catalogue = account.hasCredential ? this.catalogue(owner) : null;
    const pick = PoolBoard.candidates(catalogue, shown, query);
    const rows = pick.models.map((m) => {
      const model = escapeHtml(String(m.id));
      const window = PoolBoard.windowText(m.contextLength);
      return `<button class="pb-pick-model" type="button" data-pb-pick-model="${model}" data-t="pb-pick-model" data-t-id="${model}">`
        + `<code>${model}</code>${window ? `<small>${escapeHtml(window)}</small>` : ""}</button>`;
    }).join("");
    const typed = pick.typed ? `<button class="pb-pick-model typed" type="button" data-pb-pick-model="${escapeHtml(pick.typed)}" data-t="pb-pick-typed">`
      + `${escapeHtml(t("pbModelTyped", { model: pick.typed }))}</button>` : "";
    const word = !account.hasCredential ? t(PoolCards.subscription(account) ? "poolLoginNeeded" : "cloudNoKeyYet")
      : catalogue?.loading ? t("pbCatalogueReading")
      : catalogue?.error ? `⚠ ${t("pbCatalogueFailed")}`
      : !pick.chat && catalogue?.fetchedAt == null ? t("pbCatalogueNotYet")
      : !pick.chat ? t("pbCatalogueEmpty")
      : !pick.free ? t("pbModelsAllAdded")
      : query.trim() && !pick.models.length ? t("pbModelsNoMatch")
      : pick.more ? t("pbModelsMore", { n: String(pick.more) }) : "";
    const note = word ? `<div class="pb-picker-note" data-t="pb-pick-note"${catalogue?.error ? ` title="${escapeHtml(catalogue.error)}"` : ""}>${escapeHtml(word)}</div>` : "";
    return `${rows ? `<div class="pb-picker-list">${rows}</div>` : ""}${note}${typed}`;
  }

  // What the breaker tripped for the account and the routed errors of the last day: said on the card
  // itself, where the rows that call the account stand — a fault hidden behind a fold reads as none.
  issuesHtml(account, subscription) {
    fetchUpstreamErrors();
    const said = cloudApiIssuesHtml(account, subscription) + upstreamErrorsHtml(account.id);
    return said ? `<div class="pb-account-issues" data-t="pb-account-issues">${said}</div>` : "";
  }

  // A subscription's limits, once on its card (the owner, 2026-10-13: "crowded and motley" — each of its models
  // drew the same two bars): the provider's word when the limit is reached, and the windows as one line of meters, each with
  // what is left (2026-10-14: the mockup's line, in place of two tall bars). Where a model's pool steps aside, and where it stops, is the
  // model's own and stands in the strip, on the tall bars (`levelsHtml`); the red tick on a meter is where the card's models stop.
  limitsHtml(owner, account, models) {
    const bars = subscriptionMetersHtml(owner, { stops: this.stopsOf(account, models) });
    return bars ? `<div class="pb-limits" data-t="pb-limits">${bars}</div>` : "";
  }

  // The levels at which the models of a card stop, by the window's length in seconds, each level once and the smallest first:
  // the ticks on its meters. A model nobody set stops at the controller's default (`levelsOf`), so the ticks are the levels
  // the card's models hold, never a guess.
  stopsOf(account, models) {
    const found = {};
    for (const model of models) {
      for (const [seconds, pct] of Object.entries(this.levelsOf(account.id, model).stopAt || {})) {
        if (Number(pct) > 0) (found[seconds] ||= new Set()).add(Number(pct));
      }
    }
    return Object.fromEntries(Object.entries(found).map(([seconds, levels]) => [seconds, [...levels].sort((a, b) => a - b)]));
  }

  // The same bars with a model's two levels and their handles (usage-stats.js): its own pair, or the controller's
  // default; the proxy's last judgement of the model carries the banner "stopped" or "steps aside". No reading, no bars.
  levelsHtml(account, owner, model) {
    const levels = this.levelsOf(account.id, model);
    const step = this.stepOf(account.id, model);
    return subscriptionUsageHtml(owner, { refresh: false, step: { accountId: account.id, model,
      switchAt: levels.switchAt || {}, stopAt: levels.stopAt || {}, switchMax: levels.max,
      switchReached: step.switchReached || null, stopReached: step.stopReached || null } });
  }

  // A row of a pool that names the model: it carries the proxy's last judgement of the model's levels.
  stepOf(accountId, model) {
    return (this.top?.pools || []).flatMap((p) => p.steps || [])
      .find((s) => s.kind === "account" && s.accountId === accountId && s.model === model) || {};
  }

  // A model on an account's card: a line — its name, and at the right the marks that are news: where its pool goes on to the
  // next row (its switch level), that the pool has stepped aside or stopped it, its schedule, that no pool uses it. What
  // it is for (the pools that use it), and its two levels on the bars, stand in the strip. The ✕ takes it off the card while no
  // pool uses it; its handle stands in the row's left edge, and both show when the row is pointed at.
  accountModelHtml(account, model, uses) {
    const key = PoolBoard.key({ accountId: account.id, model });
    const step = this.stepOf(account.id, model);
    const unlisted = step.unlisted ? `<span class="pool-step-unlisted" title="${escapeHtml(t("cloudModelUnlisted"))}">⚠</span>` : "";
    // ✕ takes the model off the card while no row names it; a model in a pool keeps its place.
    const free = !uses.get(key)?.length;
    const remove = free ? `<button class="pb-tool del pb-model-remove" type="button" data-pb-model-remove data-t="pb-model-remove"`
      + ` title="${escapeHtml(t("pbModelRemove", { model }))}" aria-label="${escapeHtml(t("pbModelRemove", { model }))}">✕</button>` : "";
    const marks = PoolBoard.switchChipHtml(this.levelsOf(account.id, model)) + PoolBoard.levelTagHtml(step)
      + this.schedule.chipHtml(key, model) + (free ? PoolBoard.unusedHtml() : "") + remove;
    return `<div class="pb-model" data-pb-model data-pb-key="${escapeHtml(key)}" data-pb-node="model:${escapeHtml(key)}" data-account="${escapeHtml(account.id)}" data-model="${escapeHtml(model)}" data-name="${escapeHtml(model)}" data-t="pb-model" data-t-id="${escapeHtml(key)}">
      ${PoolBoard.pullHtml("model")}
      <span class="pb-model-head">${PoolBoard.modelGrabHtml()}<span class="pb-model-name" title="${escapeHtml(model)}"><code>${escapeHtml(model)}</code>${unlisted}</span><span class="pb-chips">${marks}</span></span>
    </div>`;
  }

  // Where a model's pool goes on to the next row, on the model's card: "switch 20% (7d)", each window with a switch level above
  // its stop (at the stop the switch changes nothing, `subscriptionLimitRowHtml`) — and nothing for a model with none. The hover
  // says it as the pool's rows do (`turnText`).
  static switchChipHtml(levels) {
    const above = Object.fromEntries(Object.entries(levels?.switchAt || {}).filter(([seconds, pct]) => Number(pct) > Number(levels?.stopAt?.[seconds] || 0)));
    const said = PoolBoard.levelsText(above);
    return said ? `<span class="pb-chip" data-t="pb-model-switch" title="${escapeHtml(t("pbTurnLeft", { levels: said }))}">${escapeHtml(t("pbChipSwitch", { levels: said }))}</span>` : "";
  }

  // A model whose pool has stepped aside or stopped it says so on its card, in a word: the stop first — at both levels the
  // model is stopped. The long word, as a row's pill says it, stands in the hover; the strip says why, with the time it resets.
  // A level that was not reached says nothing.
  static levelTagHtml(step) {
    const [look, chip, word] = step?.stopReached?.resetAt ? ["stop", "pbChipStopped", "poolStopReached"]
      : step?.switchReached?.resetAt ? ["reserve", "pbChipYielding", "poolSwitchReached"] : [];
    return look ? `<span class="pb-status ${look}" data-t="pb-model-level" data-t-state="${look}" title="${escapeHtml(t(word))}">${escapeHtml(t(chip))}</span>` : "";
  }

  // A machine's card: a monitor, its name, and at the right how many of its cells are in each state; a row for each cell in sight,
  // the stopped ones no pool uses folded under one line. The machine's address stands in the name's hover.
  machineHtml(group, uses) {
    const cells = this.cells();
    const key = `m:${group.key}`;
    const expanded = this.expanded.has(key);
    const fold = PoolBoard.foldCells(group.outs, (o) => cells.state(o), (o) => uses.has(PoolBoard.key({ output: o.id })), expanded);
    const rows = fold.shown.map((out) => this.cellHtml(out, cells, uses)).join("");
    const more = fold.quiet.length
      ? `<button class="pb-more" type="button" data-pb-more="${escapeHtml(key)}" aria-expanded="false">${escapeHtml(t("pbMoreCells", { n: String(fold.quiet.length) }))}</button>`
      : expanded && fold.folded ? `<button class="pb-more" type="button" data-pb-more="${escapeHtml(key)}" aria-expanded="true">${escapeHtml(t("pbFewer"))}</button>` : "";
    const name = escapeHtml(String(group.name ?? ""));
    const where = group.address && group.address !== group.name ? ` title="${escapeHtml(String(group.address))}"` : "";
    // A mark of two signs ("🎧🌐": hearing and translating) is wider than the slot before the names: the card gives every row the wider one.
    const wide = fold.shown.some((out) => cells.jobs(out).some((job) => Array.from(JOB_MARKS[job] || "").length > 1));
    return `<article class="pb-card pb-src${wide ? " wide-marks" : ""}" data-pb-machine="${escapeHtml(String(group.key))}" data-t="pb-machine" data-t-id="${escapeHtml(String(group.key))}">
      <div class="pb-src-head"><span class="pb-src-icon" aria-hidden="true">${PoolBoard.MONITOR}</span><b${where}>${name}</b><span class="pb-src-note" data-t="pb-machine-cells">${escapeHtml(PoolBoard.cellsSummary(group.outs.map((o) => cells.state(o))))}</span></div>
      ${rows}${more}
    </article>`;
  }

  // A machine's mark in its card's head: a line drawing as grey as the text beside it — an emoji is the loudest colour on a card.
  static MONITOR = `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3.5h12v8H2z M6 13.5h4 M8 11.5v2"/></svg>`;

  // What a machine's cells are doing, in the cell states' own words, each state with how many are in it: "3 running · 5 stopped".
  // The states in a fixed order; a cell that failed is not counted as stopped, and a state nobody expected is counted as
  // "unknown", so the numbers always add up to the cells there are. A state with none says nothing.
  static CELL_STATES = ["running", "stopped", "starting", "stopping", "failed", "unknown"];
  static cellsSummary(states) {
    const seen = (states || []).map((x) => PoolBoard.cellState(x));
    return PoolBoard.CELL_STATES.map((state) => [seen.filter((x) => x === state).length, state]).filter(([n]) => n > 0)
      .map(([n, state]) => `${n} ${t(PoolBoard.cellStateWord(state))}`).join(" · ");
  }

  // A cell's state as the board knows it: one of CELL_STATES, anything else "unknown". Its word is the output cells' own
  // (OutputCells.WORDS) — and "running", which a card says by its lamp alone and the strip and the summary in words.
  static cellState(state) {
    return PoolBoard.CELL_STATES.includes(state) ? state : "unknown";
  }
  static cellStateWord(state) {
    return state === "running" ? "running" : OutputCells.WORDS[state] || "unknown";
  }

  // A model's handle (1.3.503, the owner, 2026-10-12: "a model carried onto Pools makes a pool of it"):
  // carried onto the Pools column it makes a pool of the model, named after it; onto a pool, a row of
  // that pool. A click lists the same places.
  // The input dot of a card is a handle too (1.3.587; the owner, 2026-10-18: "from the right block pull a link to the left block, even onto
  // the part a link already leaves from — a new link, a new row"): a model's cable pulled onto a pool, a pool's onto a set, a set's onto a
  // client. A set that has a model has no "＋" on its card to carry from, and a cable could only be carried from the left; now every card
  // has the end that is always there. A click on it does nothing.
  static PULL = { model: ["pb-pull-model", "pbPullModel"], pool: ["pb-pull-pool", "pbPullPool"], set: ["pb-pull-set", "pbPullSet"] };

  static pullHtml(of) {
    const [hook, hint] = PoolBoard.PULL[of];
    return `<span class="pb-dot in" data-pb-in data-t="${hook}" title="${escapeHtml(t(hint))}"></span>`;
  }

  static modelGrabHtml() {
    return `<span class="pb-model-grab" data-pb-out="model" data-t="pb-model-grab" title="${escapeHtml(t("pbModelGrab"))}" aria-label="${escapeHtml(t("pbModelGrab"))}">⠿</span>`;
  }

  // A cell's row: what it does (a mark, grey), its name, its port, and at the right what is news — its schedule, that no pool uses
  // it, its state in a word when it is not running or stopped — and the lamp: lit while it serves, a ring while it does not run, amber
  // on the way up or down, red when it failed (`LEDS`). A stopped cell says it by the ring alone; the lamp's hover says it in words.
  cellHtml(out, cells, uses) {
    const key = PoolBoard.key({ output: out.id });
    const state = cells.state(out);
    const led = PoolBoard.LEDS[state] ?? "off";
    const said = escapeHtml(t(PoolBoard.cellStateWord(state)));
    const word = state !== "running" && state !== "stopped" ? `<span class="pb-cell-state">${said}</span>` : "";
    const name = escapeHtml(cells.name(out));
    // A model of a machine's entry has no port of its own; it says how many cells serve it, when
    // more than one (its copies, 1.3.506).
    const ofMachine = String(out.upstreamType || "") === "machine";
    const port = ofMachine ? "" : `<span class="pb-cell-port">:${escapeHtml(String(out.upstreamPort))}</span>`;
    const copies = ofMachine && cells.copies(out) > 1
      ? `<span class="pb-copies" title="${escapeHtml(t("pbCopiesTitle", { n: String(cells.copies(out)) }))}">×${cells.copies(out)}</span>` : "";
    // What the cell does: the first job's mark in the slot before the name, every job in its hover. A cell whose job cannot be
    // named has an empty slot, so the names stand in one line.
    const jobs = cells.jobs(out).filter((job) => JOB_MARKS[job]);
    const mark = `<span class="pb-model-mark" aria-hidden="true"${jobs.length ? ` title="${escapeHtml(jobs.map((job) => t(JOB_LABELS[job])).join(", "))}"` : ""}>${jobs.length ? escapeHtml(JOB_MARKS[jobs[0]]) : ""}</span>`;
    const lamp = `<span class="pb-led${led ? ` ${led}` : ""}" role="img" title="${said}" aria-label="${said}"></span>`;
    return `<div class="pb-model machine" data-pb-model data-pb-key="${escapeHtml(key)}" data-pb-node="model:${escapeHtml(key)}" data-output="${escapeHtml(String(out.id))}" data-name="${name}" data-t="pb-model" data-t-id="${escapeHtml(key)}" data-t-state="${escapeHtml(state)}">
      ${PoolBoard.pullHtml("model")}
      <span class="pb-model-head">${PoolBoard.modelGrabHtml()}${mark}<span class="pb-model-name" title="${name}">${name}</span>${copies}${port}<span class="pb-chips">${this.schedule.chipHtml(key, PoolBoard.outLabel(out, cells))}${uses.get(key)?.length ? "" : PoolBoard.unusedHtml()}${word}${lamp}</span></span>
    </div>`;
  }

  // ── the cables ──────────────────────────────────────────────────────

  // The cables a request runs through now, or ran through a moment ago, read from the monitor's rows (pool-flow.js).
  flowNow(now = this.now()) {
    return PoolFlow.of({ clients: ConsumerCards.of(this.top), pools: this.top?.pools }, this.agents(), now);
  }

  // The drops on the cables follow the monitor, which is read a few times a second: a reading that would light the same
  // cables as the last drawing did costs nothing, and one that changes them draws the cables anew.
  paintFlow() {
    if (!this.root || !this.top || this.flowNow().signature === this.flowDrawn) return false;
    this.drawCables();
    return true;
  }

  // Each cable from its output's dot to its input's dot, measured where both stand now. One that
  // cannot be placed is named in `drops` with what is missing — never left out without a word. One that carries
  // a request now has its drops (cable-flow.js) and rings its two dots; one that did a moment ago is lit.
  drawCables() {
    const cols = this.root?.querySelector?.("[data-pb-cols]");
    const svg = cols?.querySelector("[data-pb-cables]");
    this.drops = [];
    if (!cols || !svg || !this.top) return 0;
    const now = this.now();
    const flow = this.flowNow(now);
    const ringed = new Set();
    CableFlow.round();    // the drops of a cable this drawing does not carry go down, not off (cable-flow.js)
    const origin = cols.getBoundingClientRect();
    const at = (el) => {
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2 - origin.left, y: r.top + r.height / 2 - origin.top };
    };
    const esc = (v) => (globalThis.CSS?.escape ? globalThis.CSS.escape(String(v)) : String(v));
    const parts = [];
    for (const c of ConsumerCards.of(this.top)) {
      const set = String(c.set || "");
      if (!set) continue;
      const from = cols.querySelector(`[data-pb-client="${esc(c.port)}"] [data-pb-out]`);
      const to = cols.querySelector(`[data-pb-set="${esc(set)}"] > [data-pb-in]`);
      if (!from || !to) { this.drops.push({ what: `client ${c.label} -> set ${set}`, from: !!from, to: !!to }); continue; }
      const key = `client:${c.port}`;
      if (flow.active.has(key)) { ringed.add(from); ringed.add(to); }
      parts.push(PoolBoard.cableHtml(at(from), at(to), `data-pb-cable="client" data-port="${escapeHtml(String(c.port))}" data-pb-cable-key="client:${escapeHtml(String(c.port))}"`, false,
        `${c.label} → ${c.setName || set}`, PoolBoard.flowOf(flow, key), now, key));
    }
    for (const set of this.top.sets || []) {
      for (const pid of set.pools || []) {
        const from = cols.querySelector(`[data-pb-set="${esc(set.id)}"] [data-pb-set-pool="${esc(pid)}"] [data-pb-set-out]`);
        const to = cols.querySelector(`[data-pb-pool="${esc(pid)}"] > [data-pb-in]`);
        if (!from || !to) { this.drops.push({ what: `set ${set.id} -> pool ${pid}`, from: !!from, to: !!to }); continue; }
        const key = `set:${set.id}/${pid}`;
        if (flow.active.has(key)) { ringed.add(from); ringed.add(to); }
        parts.push(PoolBoard.cableHtml(at(from), at(to), `data-pb-cable="set" data-set="${escapeHtml(String(set.id))}" data-pool="${escapeHtml(String(pid))}"`
          + ` data-pb-cable-key="set:${escapeHtml(String(set.id))}/${escapeHtml(String(pid))}"`,
          false, `${set.name || set.id} → ${(this.top.pools || []).find((x) => x.id === pid)?.name || pid}`, PoolBoard.flowOf(flow, key), now, key));
      }
    }
    const runtime = this.runtime();
    for (const pool of this.top.pools || []) {
      const serving = runtime.available ? runtime.pools?.[pool.id]?.selectedStepId : null;
      for (const row of pool.steps || []) {
        const key = PoolBoard.key(row);
        if (!key) continue;
        const from = cols.querySelector(`[data-pb-pool="${esc(pool.id)}"] [data-pb-row="${esc(row.id)}"] [data-pb-out]`);
        const to = cols.querySelector(`[data-pb-key="${esc(key)}"] [data-pb-in]`);
        // A row whose target is gone says so on itself (targetHtml): no cable, and no drop.
        if (!to && !this.targetKnown(row)) continue;
        if (!from || !to) { this.drops.push({ what: `pool ${pool.id} row ${row.id} -> ${key}`, from: !!from, to: !!to }); continue; }
        const flowKey = `row:${pool.id}/${row.id}`;
        if (flow.active.has(flowKey)) { ringed.add(from); ringed.add(to); }
        parts.push(PoolBoard.cableHtml(at(from), at(to),
          `data-pb-cable="row" data-pool="${escapeHtml(pool.id)}" data-row="${escapeHtml(row.id)}" data-pb-cable-key="row:${escapeHtml(pool.id)}/${escapeHtml(row.id)}"`,
          serving === row.id, `${pool.name || pool.id} → ${this.rowName(row)}`, PoolBoard.flowOf(flow, flowKey), now, flowKey));
      }
    }
    svg.innerHTML = parts.join("") + CableFlow.ghosts(now);
    this.ring(ringed);
    this.flowDrawn = flow.signature;
    this.lightPath();
    return parts.length;
  }

  // The dots at the two ends of the cables that carry a request now have the ring (cables.css, .flowing); the ones a
  // cable carried through a moment ago lose it.
  ring(dots) {
    for (const dot of this.flowing) if (!dots.has(dot)) dot.classList?.remove("flowing");
    for (const dot of dots) dot.classList?.add("flowing");
    this.flowing = dots;
  }

  // What a cable's key says in the reading: "active" while a request runs through it, "recent" for a moment after.
  static flowOf(flow, key) {
    return flow.active.has(key) ? "active" : flow.recent.has(key) ? "recent" : "";
  }

  // The path through a card (the owner, 2026-10-12: "it is hard to see where the cables go"): from the
  // card up to the clients that reach it and down to the models it reaches — never sideways, so a model
  // two pools share lights its own way up, not the other pool's clients. Node keys are the cards'
  // `data-pb-node`: client:<port>, set:<id>, setpool:<set>/<pool>, pool:<id>, row:<pool>/<row>,
  // model:<key>; cable keys are `data-pb-cable-key`: client:<port>, set:<set>/<pool>, row:<pool>/<row>.
  static path(top, key) {
    const nodes = new Set(), cables = new Set();
    const clients = ConsumerCards.of(top);
    const sets = top?.sets || [];
    const pools = new Map((top?.pools || []).map((p) => [p.id, p]));
    const [kind, ...rest] = String(key || "").split(":");
    const id = rest.join(":");
    const up = (node) => {
      if (nodes.has(node) && node !== key) return;
      nodes.add(node);
      const [k, ...r] = node.split(":");
      const v = r.join(":");
      if (k === "set") {
        for (const c of clients) if (String(c.set || "") === v) { nodes.add(`client:${c.port}`); cables.add(`client:${c.port}`); }
      } else if (k === "setpool") {
        const [setId] = v.split("/");
        up(`set:${setId}`);
        cables.add(`set:${v}`);
      } else if (k === "pool") {
        for (const s of sets) if ((s.pools || []).includes(v)) up(`setpool:${s.id}/${v}`);
      } else if (k === "row") {
        up(`pool:${v.split("/")[0]}`);
      } else if (k === "model") {
        for (const [pid, pool] of pools) {
          for (const row of pool.steps || []) {
            if (PoolBoard.key(row) === v) { cables.add(`row:${pid}/${row.id}`); up(`row:${pid}/${row.id}`); }
          }
        }
      }
    };
    const down = (node) => {
      nodes.add(node);
      const [k, ...r] = node.split(":");
      const v = r.join(":");
      if (k === "client") {
        const client = clients.find((c) => String(c.port) === v);
        if (client?.set) { cables.add(`client:${v}`); down(`set:${client.set}`); }
      } else if (k === "set") {
        const s = sets.find((x) => x.id === v);
        for (const pid of s?.pools || []) down(`setpool:${v}/${pid}`);
      } else if (k === "setpool") {
        cables.add(`set:${v}`);
        down(`pool:${v.split("/")[1]}`);
      } else if (k === "pool") {
        for (const row of pools.get(v)?.steps || []) down(`row:${v}/${row.id}`);
      } else if (k === "row") {
        const [pid, rid] = v.split("/");
        const row = (pools.get(pid)?.steps || []).find((x) => x.id === rid);
        const target = PoolBoard.key(row);
        if (target) { cables.add(`row:${v}`); nodes.add(`model:${target}`); }
      }
    };
    if (!kind || !id) return { nodes, cables };
    up(key);
    down(key);
    return { nodes, cables };
  }

  // The lit path laid on the drawn board: its cards and cables marked, the rest dimmed. Pinned by a
  // click, it stays until Esc or a click on it again; else it follows the pointer. A pinned path shows
  // only its own cables (`path-alone`, the owner, 2026-10-18: "hide the other cables while blocks are
  // selected, so they cannot be seen or clicked — they are hard to see anyway, and when I want to let the
  // selection go I sometimes hit them": a click on a cable cuts it). Only while a card of the path is on the
  // board: a pin on a card that is gone dims everything, as it did, and does not take the cables away as well.
  lightPath() {
    const root = this.root?.querySelector?.("[data-pb-root]");
    if (!root) return;
    const path = this.trace && !this.drag?.moved ? PoolBoard.path(this.top, this.trace.key) : null;
    root.classList.toggle("tracing", !!path);
    root.classList.toggle("traced", !!this.trace?.pinned);
    let lit = 0;
    for (const el of root.querySelectorAll("[data-pb-node]")) {
      const on = !!path?.nodes.has(el.dataset.pbNode);
      el.classList.toggle("on-path", on);
      if (on) lit += 1;
    }
    for (const el of root.querySelectorAll("[data-pb-cable-key]")) el.classList.toggle("on-path", !!path?.cables.has(el.dataset.pbCableKey));
    root.classList.toggle("path-alone", !!this.trace?.pinned && lit > 0);
    this.paintDock();
  }

  // ── the strip below (pool-dock.js) ──────────────────────────────────

  // What the strip reads now: the card the trace points at, its name, the route lit across the columns
  // and its details. Nothing pointed at, or what is pointed at gone from the board — null: the strip
  // says what to do.
  dockReader() {
    const key = this.trace?.key;
    const aim = PoolDock.aim(key);
    const about = aim ? this.dockAbout(aim) : null;
    if (!about) return null;
    return { aim, pinned: !!this.trace.pinned, ...about, route: this.routeOf(key), detailsHtml: this.dockDetailsHtml(aim) };
  }

  // The strip shows while a card is pointed at or pinned, and only then (the owner, 2026-10-14): `data-t-state="empty"`
  // hides it, a moment late (pool-board.css), and it keeps what it said last — the pointer crossing the gap between two
  // cards would blank it for a frame, and the same card again need not be drawn twice. It keeps its place when hidden, so
  // nothing moves when it shows. Only a pinned strip takes the pointer: pointed at, it is for reading and is `inert`, the
  // pointer passes through it, and a card under it can still be pointed at and pinned.
  dockHtml() {
    const reader = this.dockReader();
    if (reader) this.dockDrawn = this.dock.html(reader);
    return `<aside class="pb-dock" data-pb-dock data-t="pb-dock" data-t-state="${PoolDock.state(reader)}"${reader?.pinned ? "" : " inert"}>${this.dockDrawn}</aside>`;
  }

  // The trace changed: the strip's state follows, and what it says is drawn anew in place. A strip that would read the
  // same is left alone — a field typed in it keeps its focus, and a card pointed at twice does not flicker.
  paintDock() {
    const el = this.root?.querySelector?.("[data-pb-dock]");
    if (!el) return;
    const reader = this.dockReader();
    el.setAttribute("data-t-state", PoolDock.state(reader));
    if (reader?.pinned) el.removeAttribute("inert"); else el.setAttribute("inert", "");
    if (!reader) return;
    const html = this.dock.html(reader);
    if (html === this.dockDrawn) return;
    this.dockDrawn = html;
    el.innerHTML = html;
  }

  // A card by what the strip says first: its name, and what stands under it.
  dockAbout({ kind, id }) {
    if (kind === "client") {
      const c = ConsumerCards.of(this.top).find((x) => String(x.port) === id);
      return c ? { name: String(c.label || ""), subHtml: `<span class="pb-key">🔑 …${escapeHtml(String(c.keyTail || ""))}</span>` } : null;
    }
    if (kind === "set") {
      const set = (this.top?.sets || []).find((x) => String(x.id) === id);
      return set ? { name: String(set.name || set.id), subHtml: escapeHtml(t("pbClientModelsN", { n: String((set.pools || []).length) })) } : null;
    }
    if (kind === "pool") {
      const pool = (this.top?.pools || []).find((x) => String(x.id) === id);
      return pool ? { name: String(pool.name || pool.id), subHtml: PoolBoard.kindHtml(pool.kind) } : null;
    }
    const target = this.targetOf(id);
    return target ? { name: target.name, subHtml: escapeHtml(target.where) } : null;
  }

  // A model's key (PoolBoard.key) as the strip says it: its name, and where it stands — its account, or
  // its machine and port. A key the board does not know is not a model of it.
  targetOf(key) {
    if (key.startsWith("acc:")) {
      const [accountId, ...rest] = key.slice(4).split("/");
      const account = this.account(accountId);
      return { name: rest.join("/"), where: `☁ ${account ? String(account.name || account.id) : accountId}` };
    }
    if (key.startsWith("out:")) {
      const found = this.output(key.slice(4));
      return found ? { name: this.cells().name(found.out), where: PoolBoard.where(found.out, found.group) } : { name: key.slice(4), where: "" };
    }
    return null;
  }

  // The route of a card, by column: the clients that reach it, its set, its pools, its models — the lit
  // path (path) said in names, in the order of the board. A model two accounts offer is told by its account.
  routeOf(key) {
    const { nodes } = PoolBoard.path(this.top, key);
    const ids = (prefix) => [...nodes].filter((n) => n.startsWith(prefix)).map((n) => n.slice(prefix.length));
    const ports = new Set(ids("client:")), sets = new Set(ids("set:")), pools = new Set(ids("pool:"));
    const targets = ids("model:").map((k) => this.targetOf(k)).filter(Boolean);
    const models = targets.map((x) => (targets.filter((y) => y.name === x.name).length > 1 ? `${x.name} · ${x.where}` : x.name)).sort();
    return [
      { label: t("topologyClientsSection"), names: ConsumerCards.of(this.top).filter((c) => ports.has(String(c.port))).map((c) => String(c.label || "")) },
      { label: t("pbSetsSection"), names: (this.top?.sets || []).filter((x) => sets.has(String(x.id))).map((x) => String(x.name || x.id)) },
      { label: t("pbPoolsSection"), names: (this.top?.pools || []).filter((x) => pools.has(String(x.id))).map((x) => String(x.name || x.id)) },
      { label: t("topologyModelsLabel"), names: models },
    ];
  }

  // A pool in the strip: its rows as the proxy says them — the model, the state in words and, under a row,
  // when the pool goes on to the next one (turnText) — then what can be done with it: a "＋ row" to carry onto a
  // model, its settings, its switch history. One wrapper that carries the pool (`display: contents`), so the
  // handlers find it by `closest("[data-pb-pool]")` as they did on its card.
  poolDetailsHtml(pool) {
    const id = escapeHtml(pool.id);
    const runtime = this.runtime();
    const state = runtime.available ? runtime.pools?.[pool.id] : null;
    const steps = pool.steps || [];
    const lines = steps.map((row, index) => {
      const status = this.status(pool, row, state);
      const next = index < steps.length - 1 ? this.turnText(row) : "";
      const hint = next ? `<div class="pb-turn" data-t="pb-turn" title="${escapeHtml(t("pbTurnTitle"))}">↓ ${escapeHtml(next)}</div>` : "";
      const word = status.look === "open" ? "" : `<span class="pb-status ${escapeHtml(status.look)}" title="${escapeHtml(status.title)}">${escapeHtml(status.text)}</span>`;
      return `<li class="pb-dock-step" data-t="pb-dock-step" data-t-id="${id}/${escapeHtml(row.id)}" data-t-state="${escapeHtml(status.look)}">`
        + `<span class="pb-rank">${index + 1}</span>${this.targetHtml(row)}${word}${hint}</li>`;
    }).join("");
    const events = this.events(pool);
    const open = this.history.has(pool.id) && events.length > 0;
    const history = events.length
      ? `<button class="pb-history-toggle${open ? " open" : ""}" type="button" data-pb-history aria-expanded="${open}" data-t="pb-history-toggle">${escapeHtml(t("poolHistory"))}</button>` : "";
    return `<div class="pb-dock-pool" data-pb-pool="${id}" data-pool-id="${id}" data-t="pb-dock-pool">`
      + (steps.length ? `<ol class="pb-dock-steps">${lines}</ol>${PoolBoard.newOutHtml("new-row", "pb-add-row", t("pbAddRow"), t("pbDragRow"))}` : "")
      + `${this.settingsHtml(pool)}${history}${open ? this.historyHtml(pool, events) : ""}</div>`;
  }

  // A set in the strip: the models it gives its clients, one line each with what the model does, and the
  // "＋ model" row to carry onto a pool. An empty set keeps that row on its card.
  setDetailsHtml(set) {
    const id = escapeHtml(String(set.id));
    const pools = new Map((this.top?.pools || []).map((p) => [p.id, p]));
    const lines = (set.pools || []).map((pid) => {
      const pool = pools.get(pid);
      return `<li class="pb-dock-model" data-t="pb-dock-model" data-t-id="${id}/${escapeHtml(String(pid))}">`
        + `<span class="pb-set-model-name">${escapeHtml(String(pool?.name || pid))}</span>${PoolBoard.kindHtml(pool?.kind)}</li>`;
    }).join("");
    return `<div class="pb-dock-set" data-pb-set="${id}" data-t="pb-dock-set">`
      + ((set.pools || []).length ? `<ol class="pb-dock-steps">${lines}</ol>${PoolBoard.newOutHtml("set", "pb-set-add", t("pbSetAddModel"), t("pbDragSet"))}` : "") + `</div>`;
  }

  // A model in the strip. A subscription's: the account's two limit bars with the model's own levels and their handles
  // (levelsHtml) — the model's name for the proxy's word on them, "stopped" or "steps aside", above the bars —; an account
  // with no limits to read says its state instead. A machine's: what the cell is doing, in words. The handles are found by
  // their own attributes, so the handlers need no wrapper here.
  modelDetailsHtml(key) {
    if (key.startsWith("acc:")) {
      const [accountId, ...rest] = key.slice(4).split("/");
      const account = this.account(accountId);
      if (!account) return "";
      const owner = String(account.testAliasOf || account.id);
      const reads = PoolCards.subscription(account) && !!account.hasCredential;
      const bars = reads ? this.levelsHtml(account, owner, rest.join("/")) : "";
      const note = t(account.hasCredential ? "cloudConnected" : (PoolCards.subscription(account) ? "poolLoginNeeded" : "cloudNoKeyYet"));
      return `<div class="pb-dock-levels" data-t="pb-dock-levels">${bars || `<p class="pb-dock-note">${escapeHtml(note)}</p>`}</div>`;
    }
    if (key.startsWith("out:")) {
      const found = this.output(key.slice(4));
      if (!found) return "";
      const state = PoolBoard.cellState(this.cells().state(found.out));
      const led = PoolBoard.LEDS[state] ?? "off";
      return `<div class="pb-dock-cell" data-t="pb-dock-cell" data-t-state="${escapeHtml(state)}"><span class="pb-led${led ? ` ${led}` : ""}" aria-hidden="true"></span>`
        + `${escapeHtml(t(PoolBoard.cellStateWord(state)))}</div>`;
    }
    return "";
  }

  // The details of the card in the strip. A client's links, tests and errors stand here, in one wrapper
  // that carries its port: the handlers find the client by it, as they did on its card (`display:
  // contents` — the wrapper has no box, the parts flow in the strip's columns).
  dockDetailsHtml({ kind, id }) {
    if (kind === "model") return this.modelDetailsHtml(id);
    if (kind === "pool") {
      const pool = (this.top?.pools || []).find((x) => String(x.id) === id);
      return pool ? this.poolDetailsHtml(pool) : "";
    }
    if (kind === "set") {
      const set = (this.top?.sets || []).find((x) => String(x.id) === id);
      return set ? this.setDetailsHtml(set) : "";
    }
    if (kind !== "client") return "";
    const c = ConsumerCards.of(this.top).find((x) => String(x.port) === id);
    if (!c) return "";
    return `<div class="pb-dock-client" data-pb-client="${escapeHtml(String(c.port))}" data-t="pb-dock-client">${this.asksHtml(c)}${this.probesHtml(c, (c.models || []).map(String))}${this.missesHtml(c)}</div>`;
  }

  // The pointer over a card: its path, unless one is pinned or a cable, a row or a card is in the hand. The strip
  // under the pointer, when it is not pinned, is inert: the pointer is on whatever stands under it.
  hover(event) {
    if (this.trace?.pinned || this.drag || this.carry?.busy || this.cardCarry?.busy) return;
    const key = event.target.closest?.("[data-pb-node]")?.dataset.pbNode || null;
    if ((this.trace?.key || null) === key) return;
    this.trace = key ? { key, pinned: false } : null;
    this.lightPath();
  }

  // A click on a card — not on one of its controls — pins its path; on the pinned card, lets it go. A click that is on
  // neither the pinned card nor its strip lets the pin go too (the owner, 2026-10-14: "I click another pool, or an empty
  // place between the blocks, and the focus does not leave"): on an empty place of the board, or in a text field of
  // another card — the field takes the keyboard's focus, and the path must not stay lit on the old card. A click on
  // another card's own place pins that card instead; a button of any card does its own work and leaves the pin.
  pin(event) {
    const target = event.target;
    const key = target.closest?.("[data-pb-node]")?.dataset.pbNode || null;
    const held = this.trace?.pinned ? this.trace.key : null;
    if (target.closest?.("button, input, select, textarea, a, label, [data-pb-out], [data-pb-in], [data-pb-grab], [data-pool-grip], [data-pb-card-grip], [data-level-account]")) {
      return held && key && key !== held && PoolBoard.isField(target) ? this.letGo() : false;
    }
    if (!key) return held && PoolBoard.emptyPlace(target) ? this.letGo() : false;
    this.trace = held === key ? null : { key, pinned: true };
    this.lightPath();
    return true;
  }

  letGo() {
    this.trace = null;
    this.lightPath();
    return true;
  }

  static isField(target) {
    return ["INPUT", "SELECT", "TEXTAREA"].includes(String(target?.tagName || "").toUpperCase());
  }

  // The board's own ground: its columns, with the gaps between the cards and the heads over them, and the box that
  // holds them. Not the strip, the chooser or a window — they stand beside the columns, in the box.
  static emptyPlace(target) {
    return !!target.closest?.("[data-pb-cols]") || !!target.matches?.("[data-pb-root]");
  }

  // Whether the board has what a row's cable would go to: its account, or its output.
  targetKnown(row) {
    if (row.kind === "account") return !!this.account(row.accountId);
    if (row.kind === "output") return !!this.output(row.output);
    return false;
  }

  // A cable: its wide twin the pointer finds, and the line. `flow` is what the monitor says of it: "active" — a request
  // runs through it, its drops run over it (cable-flow.js) —, "recent" — one did a moment ago —, or "". Either one lights
  // the line, as the row that serves does.
  static cableHtml(a, b, attrs, lit, title, flow = "", now = 0, key = "") {
    const d = PoolBoard.curve(a, b);
    return `<g ${attrs}><title>${escapeHtml(String(title || ""))}</title><path class="pb-cable-hit" d="${d}"></path>`
      + `<path class="pb-cable${lit || flow ? " lit" : ""}" d="${d}"></path>${flow === "active" ? CableFlow.twin(d, "", now, { key: key ? `pb:${key}` : "", from: a, to: b }) : ""}</g>`;
  }

  drawSoon() {
    const later = this.win?.requestAnimationFrame?.bind(this.win) || ((fn) => setTimeout(fn, 0));
    later(() => this.drawCables());
  }

  // ── the page ────────────────────────────────────────────────────────

  // The board stands in `container`, which the page keeps: its listeners are bound once, and every
  // drawing after that only replaces what is inside.
  mount(container) {
    if (!container) return;
    this.root = container;
    if (!container.dataset.pbBound) {
      container.dataset.pbBound = "1";
      // The columns scroll, each on its own (1.3.548): a carry that leans on the edge of its column scrolls that
      // column, and every step of a carry moves the cables of what it carries. The card sways a little to the sides
      // and no more: a column cuts what stands out of it, and a card is only ever carried along its column.
      const scroller = (list) => list?.closest?.("[data-pb-scroll]") || container.querySelector?.("[data-pb-root]");
      this.carry = new StepCarry(container, { onSort: (poolId, ids) => this.sortRows(poolId, ids), win: this.win, doc: this.doc,
        scroller, sway: PoolBoard.SWAY, onMove: () => this.drawCables() });
      this.cardCarry = new StepCarry(container, { onSort: (kind, ids) => this.saveOrder(kind, ids), win: this.win, doc: this.doc,
        parts: PoolBoard.CARDS, scroller, sway: PoolBoard.SWAY, onMove: () => this.drawCables() });
      container.addEventListener("pointerdown", (event) => this.press(event));
      container.addEventListener("click", (event) => { this.click(event); });
      container.addEventListener("change", (event) => { this.change(event); });
      container.addEventListener("input", (event) => {
        const slider = event.target.closest?.("[data-level-account]");
        if (slider) previewSwitchLevel(slider);
        if (event.target.closest?.("[data-pb-pick-query]")) this.find(event.target.value);
        if (event.target.closest?.("[data-pb-choose-query]")) this.chooseFind(event.target.value);
      });
      container.addEventListener("keydown", (event) => this.key(event));
      this.win?.addEventListener?.("keydown", (event) => this.escape(event));
      // The path under the pointer lights as it moves; it goes dark when the pointer leaves the board.
      container.addEventListener("pointerleave", () => {
        if (!this.trace || this.trace.pinned) return;
        this.trace = null;
        this.lightPath();
      });
      // A pool's field let go: the drawing that waited for it lands (`typing`) once the focus has
      // moved on — to another of them, and it waits on.
      container.addEventListener("focusout", (event) => {
        if (!event.target.closest?.("[data-pb-pool-name],[data-pb-pool-window],[data-pb-set-name],[data-ms-from],[data-ms-to]")) return;
        (this.win?.setTimeout?.bind(this.win) || setTimeout)(() => this.settled(), 0);
      });
      // A model of the list is pressed with the search field keeping the focus: the page's drawing
      // waits for that field (topology-render.js) and, let go between press and click, would put a
      // new button under the pointer before the click lands on the old one.
      container.addEventListener("mousedown", (event) => {
        if (event.target.closest?.("[data-pb-pick-model]")) event.preventDefault?.();
      });
      this.win?.addEventListener?.("resize", () => this.drawCables());
      // A column scrolls on its own, and a cable runs from dot to dot: the dots moved, so the cables are drawn again,
      // once a frame however many scroll events come.
      container.addEventListener("scroll", (event) => { if (event.target?.matches?.("[data-pb-scroll]")) this.scrolled(event.target); }, { capture: true, passive: true });
      // A stroke over the schedule's hours: each hour the pointer passes, until it lets go anywhere.
      container.addEventListener("pointerover", (event) => {
        this.schedule.over(event);
        this.hover(event);
      });
      this.win?.addEventListener?.("pointerup", () => { if (this.schedule.release()) this.settled(); });
      READING_LANDED.add(() => this.redraw());
      // The monitor read: the cables that carry a request now run their drops (pool-flow.js).
      ACTIVITY_SEEN.add(() => this.paintFlow());
    }
    this.actions.set({ pools: this.top?.pools || [], accounts: this.top?.cloudAccounts || [],
      runtime: this.top?.poolsRuntime || {} });
    this.actions.stepName = (row) => this.rowName(row);
    const box = container.querySelector?.("[data-pb-root]");
    if (box && this.scroll) {
      box.scrollTop = this.scroll.top;
      box.scrollLeft = this.scroll.left;
      PoolBoard.scrollColumns(container, this.scroll.columns);
    }
    this.drawSoon();
  }

  // One drawing of the cables per frame, however many scroll events a column sends. A column that is not at its top is
  // `scrolled`: its head, which stands over the body that scrolls, then has a line under it (pool-board.css).
  scrolled(column = null) {
    column?.classList?.toggle("scrolled", Number(column.scrollTop) > 0);
    if (this.scrollQueued) return;
    this.scrollQueued = true;
    this.nextFrame(() => { this.scrollQueued = false; this.drawCables(); });
  }

  // The board alone drawn anew — a reading landed, a card opened. While something is held the
  // drawing waits for its release (settled), and a level's handle is told to wait for it too.
  redraw() {
    if (this.busy || this.typing()) {
      this.pending = true;
      if (switchDrag.active) switchDrag.deferred = true;
      return;
    }
    const el = this.root?.querySelector?.("[data-pb-root]");
    if (!el) return;
    // A reading that lands while a search field is typed in keeps the field and its caret.
    const field = this.doc?.activeElement;
    const kept = PoolBoard.FINDS.find(([mark]) => field?.matches?.(mark))?.[1] || null;
    const caret = kept ? [field.selectionStart, field.selectionEnd] : null;
    const tops = PoolBoard.columnScrolls(el);
    el.innerHTML = this.inner();
    PoolBoard.scrollColumns(el, tops);
    if (kept) this.focusField(kept, caret);
    this.drawSoon();
  }

  // The board's search fields — the account's list under "＋ model", and the chooser's: the mark a
  // field is known by, and where it is found again in the board drawn anew.
  static FINDS = [["[data-pb-pick-query]", "[data-pb-picker] [data-pb-pick-query]"],
    ["[data-pb-choose-query]", "[data-pb-chooser] [data-pb-choose-query]"]];

  // A pool's name or its window being typed: the board's own drawing waits until the field lets
  // go (`focusout`, bound on mount). A reading that landed mid-number drew the field anew with what
  // the controller keeps, and the digits typed so far went with it. The page's drawing waits for
  // any field already (topology-render.js).
  typing() {
    return !!this.doc?.activeElement?.matches?.("[data-pb-pool-name],[data-pb-pool-window],[data-pb-set-name],[data-ms-from],[data-ms-to]");
  }

  // What the pointer held is let go: the drawings that waited for it land now — the board's own,
  // and the page's (topology-render.js deferred it while the board was busy).
  settled() {
    if (this.busy) return;
    if (this.pending) {
      this.pending = false;
      this.redraw();
    }
    flushPendingTopologyRender();
  }

  // ── what the operator does ──────────────────────────────────────────

  async send(path, body) {
    try {
      const res = await this.call(path, { method: "POST", body: JSON.stringify(body) });
      this.applied(res?.topology);
      return res;
    } catch (err) {
      this.notify(err.message);
      return null;
    }
  }

  async click(event) {
    // A click on an output lists where its cable can go. The click that ends a carried cable never
    // comes here (swallowClick).
    const opener = PoolBoard.opener(event.target);
    if (opener) {
      event.stopPropagation?.();
      return this.openChooser(opener);
    }
    // A click anywhere but in the chooser closes it; a button still does its own work, a card's free
    // place only closes the list — it does not pin a path as well.
    const closed = this.chooser && !event.target.closest?.("[data-pb-chooser]") ? this.closeChooser() : null;
    const el = event.target.closest?.("[data-pb-add-pool],[data-pb-arrange],"
      + "[data-pb-row-remove],[data-pb-pool-delete],[data-pb-history],[data-pb-settings],[data-pb-copy-url],[data-pb-tests],[data-pb-probe],[data-pb-probe-close],"
      + "[data-pb-add-set],[data-pb-set-delete],"
      + "[data-pb-more],[data-pb-cable],[data-api-retry],"
      + "[data-pb-add-model],[data-pb-pick-model],[data-pb-pick-close],[data-pb-model-remove],"
      + "[data-pb-choose],[data-pb-choose-close],"
      + "[data-ms-open],[data-ms-close],[data-ms-save],[data-ms-add],[data-ms-remove],[data-ms-day]");
    if (!el) return closed || this.pin(event) || null;
    event.stopPropagation?.();
    if (el.hasAttribute("data-ms-open") || el.closest("[data-ms]")) return this.schedule.click(el);
    if (el.hasAttribute("data-pb-choose")) return this.choose(el.dataset.pbChoose);
    if (el.hasAttribute("data-pb-choose-close")) return this.closeChooser();
    if (el.hasAttribute("data-pb-arrange")) return this.arrange();
    const poolId = el.closest("[data-pb-pool]")?.dataset.pbPool || "";
    const rowId = el.closest("[data-pb-row]")?.dataset.pbRow || "";
    if (el.hasAttribute("data-api-retry")) return this.send("/api/cloud-api-health/retry", { key: el.dataset.apiRetry });
    if (el.hasAttribute("data-pb-add-pool")) return this.addPool();
    if (el.hasAttribute("data-pb-add-set")) return this.addSet();
    if (el.hasAttribute("data-pb-set-delete")) return this.removeSet(el.closest("[data-pb-set]")?.dataset.pbSet || "");
    if (el.hasAttribute("data-pb-row-remove")) return this.removeRow(poolId, rowId);
    if (el.hasAttribute("data-pb-pool-delete")) return this.actions.remove(poolId);
    if (el.hasAttribute("data-pb-history")) { this.toggle(this.history, poolId); return this.redraw(); }
    if (el.hasAttribute("data-pb-settings")) { this.toggle(this.settings, poolId); return this.redraw(); }
    if (el.hasAttribute("data-pb-copy-url")) return this.copyUrl();
    if (el.hasAttribute("data-pb-tests")) { this.toggle(this.tests, el.closest("[data-pb-client]")?.dataset.pbClient || ""); return this.redraw(); }
    if (el.hasAttribute("data-pb-probe")) return this.runProbe(el.closest("[data-pb-client]")?.dataset.pbClient || "", el.dataset.pbProbe);
    if (el.hasAttribute("data-pb-probe-close")) return this.closeProbe();
    if (el.hasAttribute("data-pb-more")) { this.toggle(this.expanded, el.dataset.pbMore); return this.redraw(); }
    if (el.hasAttribute("data-pb-add-model")) return this.openPicker(el.dataset.pbAddModel);
    if (el.hasAttribute("data-pb-pick-close")) return this.closePicker();
    if (el.hasAttribute("data-pb-pick-model")) return this.addModel(el.dataset.pbPickModel);
    if (el.hasAttribute("data-pb-model-remove")) {
      const model = el.closest("[data-pb-model]");
      return this.removeModel(model?.dataset.account || "", model?.dataset.model || "");
    }
    return this.cut(el);
  }

  // ── the models on the right ─────────────────────────────────────────

  // "＋ model" opens the account's list in its card, the search field ready to type in; one list is
  // open at a time. A list the controller had not read, or could not, is asked for again.
  openPicker(accountId) {
    const account = this.account(accountId);
    if (!account) return null;
    const owner = String(account.testAliasOf || account.id);
    const known = this.catalogues.get(owner);
    if (known && (known.error || (!known.loading && known.fetchedAt == null && !(known.models || []).length))) this.catalogues.delete(owner);
    this.picking = { accountId: account.id, query: "" };
    this.redraw();
    this.focusFind();
    return true;
  }

  closePicker() {
    if (!this.picking) return null;
    this.picking = null;
    this.letGoFind();
    this.redraw();
    return true;
  }

  // What is typed redraws the found models alone: the whole card drawn again would take the field
  // away mid-word.
  find(query) {
    if (!this.picking) return;
    this.picking.query = String(query || "");
    const account = this.account(this.picking.accountId);
    const body = this.root?.querySelector?.("[data-pb-picker] [data-pb-pick-body]");
    if (account && body) body.innerHTML = this.pickBodyHtml(account, String(account.testAliasOf || account.id), this.shownOf(account), this.picking.query);
  }

  // In the search field Enter puts the first model found on the card (or the typed id, when nothing
  // is found), and Escape closes the list.
  key(event) {
    if (this.probe && event.key === "Escape") {
      event.preventDefault?.();
      return this.closeProbe();
    }
    if (this.schedule.form && event.key === "Escape") {
      event.preventDefault?.();
      return this.schedule.close();
    }
    // In the chooser's search Enter picks the first place it finds that can be picked, and Escape
    // closes it.
    if (this.chooser && event.target.closest?.("[data-pb-choose-query]")) {
      if (event.key === "Escape") {
        event.preventDefault?.();
        return this.closeChooser();
      }
      if (event.key !== "Enter") return null;
      event.preventDefault?.();
      const first = this.root?.querySelector?.("[data-pb-chooser] [data-pb-choose]:not([disabled])");
      return first ? this.choose(first.dataset.pbChoose) : null;
    }
    if (!this.picking || !event.target.closest?.("[data-pb-pick-query]")) return null;
    if (event.key === "Escape") {
      event.preventDefault?.();
      return this.closePicker();
    }
    if (event.key !== "Enter") return null;
    event.preventDefault?.();
    const first = this.root?.querySelector?.("[data-pb-picker] [data-pb-pick-model]");
    return first ? this.addModel(first.dataset.pbPickModel) : null;
  }

  // The model goes on the card; the list closes with the answer. Refused — the list stays open, and
  // the toast says why.
  async addModel(model) {
    const was = this.picking;
    if (!was || !model) return null;
    this.picking = null;
    const res = await this.send("/api/pools/add-model", { accountId: was.accountId, model });
    if (!res) {
      this.picking = was;
      this.redraw();
      return null;
    }
    this.letGoFind();
    return res;
  }

  removeModel(accountId, model) {
    if (!accountId || !model) return null;
    return this.send("/api/pools/remove-model", { accountId, model });
  }

  focusFind(caret = null) {
    this.focusField("[data-pb-picker] [data-pb-pick-query]", caret);
  }

  // A search field of the board takes the focus, its caret where it was — at the end, when new.
  focusField(selector, caret = null) {
    const field = this.root?.querySelector?.(selector);
    if (!field) return;
    field.focus?.();
    const end = String(field.value || "").length;
    field.setSelectionRange?.(caret?.[0] ?? end, caret?.[1] ?? end);
  }

  // The search field lets go of the focus: the page's drawing waited for it (topology-render.js,
  // topologyInteractionActive) and lands when it does.
  letGoFind() {
    this.letGoField("[data-pb-pick-query]");
  }

  letGoField(selector) {
    const field = this.doc?.activeElement;
    if (field?.matches?.(selector)) field.blur?.();
  }

  toggle(set, key) {
    if (set.has(key)) set.delete(key); else set.add(key);
  }

  async change(event) {
    if (event.target.closest?.("[data-ms]")) return this.schedule.change(event.target);
    const slider = event.target.closest?.("[data-level-account]");
    if (slider) return saveSwitchLevel(slider, (top) => this.applied(top), () => this.redraw());
    const windowField = event.target.closest?.("[data-pb-pool-window],[data-pb-pool-window-auto]");
    if (windowField) return this.saveWindow(windowField);
    const setName = event.target.closest?.("[data-pb-set-name]");
    if (setName) return this.renameSet(setName);
    const probeModel = event.target.closest?.("[data-pb-probe-model]");
    if (probeModel) {
      this.probeModel.set(String(probeModel.closest("[data-pb-client]")?.dataset.pbClient || ""), String(probeModel.value || ""));
      return true;
    }
    const name = event.target.closest?.("[data-pb-pool-name]");
    if (!name) return null;
    const pool = this.actions.stored(name.closest("[data-pb-pool]")?.dataset.pbPool || "");
    const typed = String(name.value || "").trim();
    if (!pool || !typed || typed === pool.name) { if (pool) name.value = pool.name; return null; }
    try { return await this.actions.save({ ...pool, name: typed }); } catch (err) { this.notify(err.message); name.value = pool.name; return null; }
  }

  // The window a pool states and its switch, saved by the pool cards' door (`save`) as the main
  // board's pool cards saved them until 1.3.486: blank is "I state nothing", not zero — the
  // controller keeps no window then. Both fields go as they stand: a number typed and the switch
  // ticked before the number's answer came back would otherwise undo each other with what the
  // controller kept before. Refused (a number below 1), the fields show what the controller keeps
  // and the toast says why.
  async saveWindow(field) {
    const card = field.closest("[data-pb-pool]");
    const pool = this.actions.stored(card?.dataset.pbPool || "");
    if (!pool) return null;
    const number = card.querySelector?.("[data-pb-pool-window]") || (field.hasAttribute("data-pb-pool-window") ? field : null);
    const box = card.querySelector?.("[data-pb-pool-window-auto]") || (field.hasAttribute("data-pb-pool-window-auto") ? field : null);
    const typed = number ? String(number.value ?? "").trim() : String(pool.contextLength ?? "");
    const auto = box ? !!box.checked : !!pool.contextAuto;
    if (typed === String(pool.contextLength ?? "") && auto === !!pool.contextAuto) return null;
    try {
      return await this.actions.save({ ...pool, contextLength: typed, contextAuto: auto });
    } catch (err) {
      this.notify(err.message);
      if (number) number.value = pool.contextLength ? String(pool.contextLength) : "";
      if (box) box.checked = !!pool.contextAuto;
      return null;
    }
  }

  // "+ New pool": an empty pool named by the controller ("Pool", "Pool 2"…); its name waits in
  // the field, chosen, for the operator to type over it.
  async addPool() {
    const res = await this.send("/api/pools/create", {});
    const id = res?.pool?.id;
    const esc = (v) => (globalThis.CSS?.escape ? globalThis.CSS.escape(String(v)) : String(v));
    const field = id ? this.root?.querySelector?.(`[data-pb-pool="${esc(id)}"] [data-pb-pool-name]`) : null;
    field?.focus?.();
    field?.select?.();
    return res;
  }

  // "＋ New set": an empty set named by the controller ("Set", "Set 2"…); its name waits in its
  // field, chosen, for the operator to type over it — as a new pool's does.
  async addSet() {
    const res = await this.send("/api/sets/create", {});
    const id = res?.set?.id;
    const esc = (v) => (globalThis.CSS?.escape ? globalThis.CSS.escape(String(v)) : String(v));
    const field = id ? this.root?.querySelector?.(`[data-pb-set="${esc(id)}"] [data-pb-set-name]`) : null;
    field?.focus?.();
    field?.select?.();
    return res;
  }

  async renameSet(field) {
    const set = (this.top?.sets || []).find((x) => x.id === field.closest("[data-pb-set]")?.dataset.pbSet);
    const typed = String(field.value || "").trim();
    if (!set || !typed || typed === set.name) { if (set) field.value = set.name; return null; }
    const res = await this.send("/api/sets/rename", { id: set.id, name: typed });
    if (!res) field.value = set.name;
    return res;
  }

  // ✕ on a set, after one question that names the clients it leaves without models.
  async removeSet(setId) {
    const set = (this.top?.sets || []).find((x) => x.id === setId);
    if (!set) return null;
    const clients = ConsumerCards.of(this.top).filter((c) => c.set === set.id).map((c) => c.label);
    const text = clients.length ? t("pbSetDeleteClients", { set: set.name, clients: clients.join(", ") }) : t("pbSetDeleteText", { set: set.name });
    const sure = await this.confirm(text, { title: t("pbSetDelete"), danger: true, confirmLabel: t("pbSetDelete") });
    return sure ? this.send("/api/sets/delete", { id: set.id }) : null;
  }

  async removeRow(poolId, rowId) {
    const pool = this.actions.stored(poolId);
    const index = (pool?.steps || []).findIndex((s) => s.id === rowId);
    if (index < 0) return null;
    const sure = await this.confirm(t("pbRowRemoveText", { n: String(index + 1), row: this.rowName(pool.steps[index]), pool: pool.name || pool.id }),
      { title: t("poolStepRemove"), danger: true, confirmLabel: t("poolStepRemove") });
    if (!sure) return null;
    return this.send("/api/pools/remove-step", { poolId, stepId: rowId });
  }

  // A click on a cable cuts it, after one question that names both of its ends.
  async cut(el) {
    const kind = el.dataset.pbCable;
    if (kind === "client") {
      const client = ConsumerCards.of(this.top).find((c) => String(c.port) === String(el.dataset.port));
      if (!client?.set) return null;
      const sure = await this.confirm(t("pbCutClientSetText", { client: client.label, set: client.setName || client.set }),
        { title: t("pbCutTitle"), danger: true, confirmLabel: t("pbCutTitle") });
      return sure ? this.send("/api/consumers/set", { port: Number(client.port), set: "" }) : null;
    }
    if (kind === "set") {
      const set = (this.top?.sets || []).find((x) => x.id === el.dataset.set);
      const pool = (this.top?.pools || []).find((x) => x.id === el.dataset.pool);
      if (!set || !(set.pools || []).includes(el.dataset.pool)) return null;
      const sure = await this.confirm(t("pbCutSetPoolText", { set: set.name || set.id, pool: pool?.name || el.dataset.pool }),
        { title: t("pbCutTitle"), danger: true, confirmLabel: t("pbCutTitle") });
      return sure ? this.send("/api/sets/remove-pool", { id: set.id, pool: el.dataset.pool }) : null;
    }
    if (kind === "row") {
      const pool = this.actions.stored(el.dataset.pool);
      const index = (pool?.steps || []).findIndex((s) => s.id === el.dataset.row);
      if (index < 0) return null;
      const sure = await this.confirm(t("pbCutRowText", { n: String(index + 1), pool: pool.name || pool.id, target: this.rowName(pool.steps[index]) }),
        { title: t("pbCutTitle"), danger: true, confirmLabel: t("pbCutTitle") });
      return sure ? this.send("/api/pools/connect-row", { poolId: pool.id, rowId: el.dataset.row, target: null }) : null;
    }
    return null;
  }

  // ── carrying a cable ────────────────────────────────────────────────

  // How far a press travels before it is a cable: one that stays is a click, and a click on an
  // output lists where its cable can go (the chooser).
  static SLOP = 5;
  // Where a cable in the hand leans on an edge of the board, and how fast the board scrolls then
  // (the owner, 2026-10-12: "a cable cannot be drawn to a cell off the screen, above or below").
  static EDGE = 56;
  static SCROLL = 18;
  // How far a carried card may go to either side of its column, in px: it is carried along the column, and a column cuts
  // what stands out of it.
  static SWAY = 10;

  // What each kind of cable lands on: a client's on a set, a set's on a pool, a pool row's on a
  // model — and a model's on a pool, or on the Pools column for a pool of its own. The cables pulled from the
  // right (1.3.587): a pool's input onto a set, a set's input onto a client; a model's input does what its handle does.
  static ONTO = {
    client: ["[data-pb-set]"],
    set: ["[data-pb-pool]"],
    row: ["[data-pb-model]"],
    "new-row": ["[data-pb-model]"],
    model: ["[data-pb-pool]", "[data-pb-pools-drop]"],
    "pull-pool": ["[data-pb-set]"],
    "pull-set": ["[data-pb-client]"],
  };
  // The kinds whose cable the pointer holds by its left end: it ends at the card's input, which stays where it is.
  static REVERSE = new Set(["model", "pull-pool", "pull-set"]);

  // The output an element belongs to: a dot or a model's handle itself, or the dot of the "＋" row it
  // lies in (newOutHtml) — a press and a click find it alike.
  static opener(el) {
    return el?.closest?.("[data-pb-out]") || el?.closest?.("[data-pb-grab]")?.querySelector?.("[data-pb-out]") || null;
  }

  // What an output starts: its kind and where it comes from — a client's port, a set, a pool's row
  // (the pool alone, for its "＋"), a model with the name the board shows it by.
  static source(dot) {
    if (dot?.hasAttribute?.("data-pb-in")) return PoolBoard.pulled(dot);
    const kind = dot?.dataset?.pbOut;
    if (!kind) return null;
    if (kind === "client") return { kind, from: { port: Number(dot.dataset.port) } };
    if (kind === "set") return { kind, from: { setId: dot.closest("[data-pb-set]")?.dataset.pbSet || "" } };
    if (kind === "model") return PoolBoard.modelSource(dot.closest("[data-pb-model]"));
    return { kind, from: { poolId: dot.closest("[data-pb-pool]")?.dataset.pbPool || "", rowId: dot.closest("[data-pb-row]")?.dataset.pbRow || "" } };
  }

  // A model's cable: its target — an account's model, or a cell's output — with the name the board shows it by. A card that is none starts nothing.
  static modelSource(card) {
    if (!card) return null;
    const target = card.dataset.output ? { output: card.dataset.output } : { accountId: card.dataset.account || "", model: card.dataset.model || "" };
    return { kind: "model", from: { target, name: card.dataset.name || "" } };
  }

  // The input dot an element belongs to: where a cable is pulled from (1.3.587). A press on it and a press on an output are told apart by
  // `press`, which asks for an output first.
  static puller(el) {
    return el?.closest?.("[data-pb-in]") || null;
  }

  // What an input dot starts when it is pulled: its model's cable, a pool's onto a set, a set's onto a client. A dot on no card starts nothing.
  static pulled(dot) {
    const model = dot.closest?.("[data-pb-model]");
    if (model) return PoolBoard.modelSource(model);
    const pool = dot.closest?.("[data-pb-pool]");
    if (pool) return { kind: "pull-pool", from: { poolId: pool.dataset.pbPool || "" } };
    const set = dot.closest?.("[data-pb-set]");
    return set ? { kind: "pull-set", from: { setId: set.dataset.pbSet || "" } } : null;
  }

  // A place of the board as `ask` takes it: a set, a pool, a model with its name — or the Pools column,
  // a new pool.
  static placeOf(el) {
    if (el?.hasAttribute?.("data-pb-set")) return { set: el.dataset.pbSet };
    if (el?.hasAttribute?.("data-pb-client")) return { client: el.dataset.pbClient };
    if (el?.hasAttribute?.("data-pb-pool")) return { pool: el.dataset.pbPool };
    if (el?.hasAttribute?.("data-pb-model")) {
      return { target: el.dataset.output ? { output: el.dataset.output } : { accountId: el.dataset.account, model: el.dataset.model },
        name: el.dataset.name || "" };
    }
    if (el?.hasAttribute?.("data-pb-pools-drop")) return { newPool: true };
    return {};
  }

  // What joining an output to a place asks of the controller — one door for a cable carried there and
  // for a place picked in the chooser. The model's name goes along: a pool still called "Pool", with no
  // cable yet, takes it as its own (caravan/admin/pools.py; the owner, 2026-10-12: "a pool of one model
  // named after the model"). A place its kind does not land on asks nothing.
  static ask(kind, from, to) {
    if (kind === "client" && to?.set) return ["/api/consumers/set", { port: from.port, set: to.set }];
    if (kind === "set" && to?.pool) return ["/api/sets/add-pool", { id: from.setId, pool: to.pool }];
    if (kind === "new-row" && to?.target) return ["/api/pools/add-row", { poolId: from.poolId, target: to.target, nameAfter: to.name || "" }];
    if (kind === "row" && to?.target) {
      return ["/api/pools/connect-row", { poolId: from.poolId, rowId: from.rowId, target: to.target, nameAfter: to.name || "" }];
    }
    if (kind === "model" && to?.pool) return ["/api/pools/add-row", { poolId: to.pool, target: from.target, nameAfter: from.name || "" }];
    if (kind === "model" && to?.newPool) return ["/api/pools/create", { target: from.target, nameAfter: from.name || "" }];
    // Pulled from the right: a pool onto a set is one more model of the set; a set onto a client is the set the client sees, in place of its own.
    if (kind === "pull-pool" && to?.set) return ["/api/sets/add-pool", { id: to.set, pool: from.poolId }];
    if (kind === "pull-set" && to?.client) return ["/api/consumers/set", { port: Number(to.client), set: from.setId }];
    return null;
  }

  // How hard the pointer leans on an edge of a box along one axis: 0 inside, harder the nearer the
  // edge, 1 at it and past it, negative toward the start. A box too small to lean in leans nowhere.
  static edgeLean(at, low, high, edge = PoolBoard.EDGE) {
    if (!(high - low > 2 * edge)) return 0;
    if (at < low + edge) return -Math.min(1, (low + edge - at) / edge);
    if (at > high - edge) return Math.min(1, (at - (high - edge)) / edge);
    return 0;
  }

  // A press on an output — its dot, a "＋" row anywhere on it, a model's handle — becomes a cable
  // once it travels; one that stays is a click, and `click` opens the chooser. A press on a level's
  // handle holds the board still until it is let go (usage-stats.js, switchDrag).
  press(event) {
    if (this.schedule.press(event)) return;
    if (event.target.closest?.("[data-level-account]")) {
      switchDrag.begin(() => this.settled());
      switchDrag.deferred = true;
      return;
    }
    const dot = PoolBoard.opener(event.target) || PoolBoard.puller(event.target);
    if (!dot || event.button !== 0 || this.drag) return;
    const source = PoolBoard.source(dot);
    if (!source) return;
    event.preventDefault?.();
    // A model's cable is drawn from its other end: it ends at the model's input, and the pointer holds
    // the end that goes to a pool.
    const anchor = source.kind === "model" ? dot.closest("[data-pb-model]")?.querySelector?.("[data-pb-in]") || dot : dot;
    const at = { x: event.clientX, y: event.clientY };
    this.drag = { ...source, dot: anchor, pointerId: event.pointerId, start: at, pointer: at, moved: false, over: null,
      lean: { x: 0, y: 0 }, scrollFrame: 0 };
    this.win.addEventListener("pointermove", this.onMove);
    this.win.addEventListener("pointerup", this.onUp);
    this.win.addEventListener("pointercancel", this.onUp);
    this.win.addEventListener("keydown", this.onKey);
  }

  // The cable follows the pointer once the press has travelled; the place it would land on lights,
  // and near an edge the board scrolls under it.
  follow(event) {
    const drag = this.drag;
    if (!drag || (drag.pointerId !== undefined && event.pointerId !== drag.pointerId)) return;
    drag.pointer = { x: event.clientX, y: event.clientY };
    if (!drag.moved) {
      if (Math.hypot(drag.pointer.x - drag.start.x, drag.pointer.y - drag.start.y) <= PoolBoard.SLOP) return;
      drag.moved = true;
      this.closeChooser();
      this.root?.querySelector?.("[data-pb-root]")?.classList.add(`dragging-${drag.kind}`);
      this.markHolds();
      this.lightPath();
    }
    this.track();
    this.lean();
  }

  // The loose cable drawn to the pointer, and the place under the pointer lit. It has a layer of its own, above
  // the columns: the drawn cables run under the cards and show in the gutters, a cable in the hand shows all the
  // way to the pointer. One that leaves the strip (a pool's "＋ row", a set's "＋ model") comes out of the strip's
  // top edge, where the columns end.
  track() {
    const drag = this.drag;
    const cols = this.root?.querySelector?.("[data-pb-cols]");
    const svg = cols?.querySelector("[data-pb-live-layer]");
    if (!drag?.moved || !cols || !svg) return;
    const origin = cols.getBoundingClientRect();
    const r = drag.dot.getBoundingClientRect();
    const floor = drag.dot.closest?.("[data-pb-dock]") ? Math.min(origin.bottom, drag.dot.closest("[data-pb-dock]").getBoundingClientRect().top) : Infinity;
    const dot = { x: r.left + r.width / 2 - origin.left, y: Math.min(r.top + r.height / 2, floor) - origin.top };
    const hand = { x: drag.pointer.x - origin.left, y: drag.pointer.y - origin.top };
    const d = PoolBoard.REVERSE.has(drag.kind) ? PoolBoard.curve(hand, dot) : PoolBoard.curve(dot, hand);
    let live = svg.querySelector("[data-pb-live]");
    if (!live) {
      svg.insertAdjacentHTML("beforeend", `<path class="pb-cable live" data-pb-live d="${d}"></path>`);
      live = svg.querySelector("[data-pb-live]");
    }
    live?.setAttribute("d", d);
    const target = this.landing(drag.pointer.x, drag.pointer.y);
    if (target !== drag.over) {
      drag.over?.classList.remove("pb-drop");
      target?.classList.add("pb-drop");
      drag.over = target;
    }
  }

  // Near an edge of the board's box — the part of it on the screen — the cable leans on it, and the
  // board scrolls that way frame by frame while it does.
  lean() {
    const drag = this.drag;
    const box = this.root?.querySelector?.("[data-pb-root]");
    if (!drag?.moved || !box) return;
    const r = box.getBoundingClientRect();
    const wide = Number(this.win.innerWidth) || r.right, high = Number(this.win.innerHeight) || r.bottom;
    // Across, the board scrolls; up and down, the column the pointer is over: in the gutter between two, nothing leans.
    drag.column = this.columnAt(drag.pointer.x);
    const c = drag.column?.getBoundingClientRect?.();
    drag.lean = {
      x: PoolBoard.edgeLean(drag.pointer.x, Math.max(r.left, 0), Math.min(r.right, wide)),
      y: c ? PoolBoard.edgeLean(drag.pointer.y, Math.max(c.top, 0), Math.min(c.bottom, high)) : 0,
    };
    if ((drag.lean.x || drag.lean.y) && !drag.scrollFrame) drag.scrollFrame = this.nextFrame(() => this.scrollStep(drag));
  }

  // The column whose width the pointer is in, whatever lies over its foot (the strip): the one a cable that leans on the
  // top or the bottom scrolls.
  columnAt(x) {
    for (const col of this.root?.querySelectorAll?.("[data-pb-scroll]") || []) {
      const r = col.getBoundingClientRect();
      if (x >= r.left && x <= r.right) return col;
    }
    return null;
  }

  // One frame of it: the board scrolls across, the column up or down, the page when neither can; at the
  // end every way it leans, it stops until the pointer moves again.
  scrollStep(drag) {
    drag.scrollFrame = 0;
    const box = this.root?.querySelector?.("[data-pb-root]");
    if (this.drag !== drag || !box) return;
    const col = drag.column;
    const dx = Math.round(drag.lean.x * PoolBoard.SCROLL), dy = Math.round(drag.lean.y * PoolBoard.SCROLL);
    const was = [box.scrollLeft, col ? col.scrollTop : 0, this.win.scrollX, this.win.scrollY];
    box.scrollLeft += dx;
    if (col) col.scrollTop += dy;
    if (box.scrollLeft === was[0] && (col ? col.scrollTop : 0) === was[1]) this.win.scrollBy?.(dx, dy);
    const now = [box.scrollLeft, col ? col.scrollTop : 0, this.win.scrollX, this.win.scrollY];
    if (now.every((v, i) => v === was[i])) return;
    this.track();
    this.lean();
  }

  nextFrame(fn) {
    return (this.win?.requestAnimationFrame?.bind(this.win) || ((f) => setTimeout(f, 16)))(fn);
  }

  // The element a cable would land on at (x, y): the nearest of its kind's places under the pointer.
  landing(x, y) {
    const el = this.doc?.elementFromPoint?.(x, y);
    if (!el || !this.drag) return null;
    for (const onto of PoolBoard.ONTO[this.drag.kind] || []) {
      const hit = el.closest?.(onto);
      if (hit) return this.holds(this.drag, hit) ? null : hit;
    }
    return null;
  }

  // The places of the cable's kind that already have what it would give them stand as they are, with no outline of a landing: a set that
  // holds the pool, the client that sees the set. (`holds` says which; it is clear of them once the cable is let go.)
  markHolds() {
    const drag = this.drag;
    for (const onto of PoolBoard.ONTO[drag?.kind] || []) {
      for (const place of this.root?.querySelectorAll?.(onto) || []) {
        if (this.holds(drag, place)) place.classList.add("pb-holds");
      }
    }
  }

  clearHolds() {
    for (const place of this.root?.querySelectorAll?.(".pb-holds") || []) place.classList.remove("pb-holds");
  }

  // Whether a place already has what a cable pulled from the right would give it: a set that holds the pool, a client that sees the set. It is
  // no landing: it does not light, and a cable let go over it is let go of nothing. (A set with other models, a client with another set — that
  // is where they land: onto the part a link already leaves from, a new one is made.)
  holds(drag, place) {
    if (drag.kind === "pull-pool") {
      const set = (this.top?.sets || []).find((s) => String(s.id) === String(place.dataset?.pbSet));
      return (set?.pools || []).includes(drag.from?.poolId);
    }
    if (drag.kind === "pull-set") {
      const client = ConsumerCards.of(this.top).find((c) => String(c.port) === String(place.dataset?.pbClient));
      return !!client?.set && String(client.set) === String(drag.from?.setId);
    }
    return false;
  }

  // Letting go: a press that never travelled was a click, and leaves the chooser to it. A cable lands
  // on the place under the pointer; let go anywhere else, it is gone.
  async release(event) {
    const drag = this.drag;
    if (!drag || (drag.pointerId !== undefined && event.pointerId !== undefined && event.pointerId !== drag.pointerId)) return null;
    if (!drag.moved) {
      this.endDrag();
      return null;
    }
    this.swallowClick();
    // What the cable lands on is read before the board is let go: letting go may draw it anew.
    // A pool's new row comes cabled in one write (/api/pools/add-row with its target): there is
    // no open row left behind when the cable is not drawn.
    const target = event.type === "pointercancel" ? null : this.landing(event.clientX, event.clientY);
    const ask = target ? PoolBoard.ask(drag.kind, drag.from, PoolBoard.placeOf(target)) : null;
    this.endDrag();
    return ask ? this.send(...ask) : null;
  }

  // The click that ends a carried cable is the cable's: on the output it left, it would open the
  // chooser over the cable just drawn.
  swallowClick() {
    const swallow = (event) => { event.preventDefault?.(); event.stopPropagation?.(); };
    this.win.addEventListener?.("click", swallow, { capture: true, once: true });
    (this.win?.setTimeout?.bind(this.win) || setTimeout)(() => this.win.removeEventListener?.("click", swallow, { capture: true }), 400);
  }

  endDrag() {
    const drag = this.drag;
    this.drag = null;
    this.win.removeEventListener("pointermove", this.onMove);
    this.win.removeEventListener("pointerup", this.onUp);
    this.win.removeEventListener("pointercancel", this.onUp);
    this.win.removeEventListener("keydown", this.onKey);
    if (drag?.scrollFrame) this.win.cancelAnimationFrame?.(drag.scrollFrame);
    drag?.over?.classList.remove("pb-drop");
    const root = this.root?.querySelector?.("[data-pb-root]");
    root?.classList.remove(...Object.keys(PoolBoard.ONTO).map((kind) => `dragging-${kind}`));
    root?.querySelector("[data-pb-live]")?.remove();
    this.clearHolds();
    if (drag?.moved) this.lightPath();
    this.settled();
  }

  // ── the chooser ─────────────────────────────────────────────────────

  // A click on an output lists where its cable can go (1.3.503; the owner, 2026-10-12: "a cable
  // cannot be drawn to a cell off the screen"): every place its kind lands on, wherever it stands on
  // the board, with a search over them. The place the cable goes to now is marked and cannot be
  // picked again. The list stands by the output it was opened from, in the board's scrolled box, and
  // scrolls with it; it opens upward when there is more room above.
  static CHOOSER_WIDTH = 320;
  static CHOOSER_TITLES = { client: "pbChooseSet", set: "pbChoosePool", row: "pbChooseModel", "new-row": "pbChooseModel", model: "pbChooseModelPool" };
  // An empty list says what is missing, in the column's own words.
  static CHOOSER_EMPTY = { client: "pbNoSets", set: "pbNoPools", row: "pbNoModels", "new-row": "pbNoModels" };

  openChooser(dot) {
    const source = PoolBoard.source(dot);
    const box = this.root?.querySelector?.("[data-pb-root]");
    if (!source || !box) return null;
    // A name being typed is saved first, as a click anywhere else would save it.
    if (this.typing()) this.doc.activeElement.blur?.();
    const r = dot.getBoundingClientRect(), b = box.getBoundingClientRect();
    const below = b.bottom - r.bottom, above = r.top - b.top;
    const up = below < 300 && above > below;
    const left = r.left - b.left + box.scrollLeft;
    const x = Math.max(box.scrollLeft + 8, Math.min(left, box.scrollLeft + box.clientWidth - PoolBoard.CHOOSER_WIDTH - 8));
    const y = (up ? r.top - 6 : r.bottom + 6) - b.top + box.scrollTop;
    this.chooser = { ...source, query: "", at: { x: Math.round(x), y: Math.round(y), up } };
    this.showChooser();
    this.focusField("[data-pb-chooser] [data-pb-choose-query]");
    return true;
  }

  // The chooser put on the board as it stands: the board is not drawn anew for it.
  showChooser() {
    const box = this.root?.querySelector?.("[data-pb-root]");
    this.root?.querySelector?.("[data-pb-chooser]")?.remove();
    if (box && this.chooser) box.insertAdjacentHTML("beforeend", this.chooserHtml());
  }

  closeChooser() {
    if (!this.chooser) return null;
    this.chooser = null;
    this.letGoField("[data-pb-choose-query]");
    this.root?.querySelector?.("[data-pb-chooser]")?.remove();
    return true;
  }

  chooserHtml() {
    const c = this.chooser;
    if (!c) return "";
    const title = t(PoolBoard.CHOOSER_TITLES[c.kind] || "pbChooseModel");
    return `<div class="pb-chooser${c.at?.up ? " up" : ""}" data-pb-chooser role="dialog" aria-label="${escapeHtml(title)}" data-t="pb-chooser"`
      + ` data-t-state="${escapeHtml(c.kind)}" style="left: ${Number(c.at?.x) || 0}px; top: ${Number(c.at?.y) || 0}px">
      <div class="pb-chooser-head"><b>${escapeHtml(title)}</b>
        <button class="pb-tool" type="button" data-pb-choose-close data-t="pb-choose-close" title="${escapeHtml(t("topologyClose"))}" aria-label="${escapeHtml(t("topologyClose"))}">✕</button></div>
      <input class="pb-picker-find" type="search" data-pb-choose-query data-t="pb-choose-query" value="${escapeHtml(String(c.query || ""))}"
        placeholder="${escapeHtml(t("pbChooseFind"))}" aria-label="${escapeHtml(t("pbChooseFind"))}" autocomplete="off" spellcheck="false">
      <div class="pb-chooser-list" data-pb-choose-body>${this.chooseBodyHtml()}</div>
    </div>`;
  }

  chooseBodyHtml() {
    const c = this.chooser;
    if (!c) return "";
    const found = PoolBoard.found(this.choices(c.kind, c.from), c.query);
    const rows = found.list.map((x) => `<button class="pb-choice${x.now ? " now" : ""}" type="button" data-pb-choose="${escapeHtml(x.key)}"`
      + ` data-t="pb-choice" data-t-id="${escapeHtml(x.key)}"${x.now ? ` disabled title="${escapeHtml(t("pbChooseNow"))}"` : ""}>`
      + `<span class="pb-choice-name">${x.now ? "✓ " : ""}${escapeHtml(x.label)}</span>${x.hint ? `<small>${escapeHtml(x.hint)}</small>` : ""}</button>`).join("");
    const word = !found.total ? t(PoolBoard.CHOOSER_EMPTY[c.kind] || "pbChooseNoMatch")
      : !found.list.length ? t("pbChooseNoMatch")
        : found.more ? t("pbModelsMore", { n: String(found.more) }) : "";
    return `${rows}${word ? `<div class="pb-picker-note" data-t="pb-choose-note">${escapeHtml(word)}</div>` : ""}`;
  }

  // The choices a search finds — by name or by line, in any case — at most PICK_ROWS of them, with
  // what the rest count and what the whole list counts: an empty list and nothing found are two facts.
  static found(choices, query = "", limit = PoolBoard.PICK_ROWS) {
    const want = String(query || "").trim().toLowerCase();
    const hit = want ? choices.filter((c) => `${c.label} ${c.hint || ""}`.toLowerCase().includes(want)) : choices;
    return { list: hit.slice(0, limit), more: Math.max(0, hit.length - limit), total: choices.length };
  }

  // Where an output's cable can go: each place with the key the list knows it by, its name and its
  // line, the place `ask` takes, and whether a cable goes there now — the client's set, the set's pools,
  // the pool's models, the model's pools. A model is offered a pool of its own first.
  choices(kind, from) {
    const top = this.top || {};
    const pools = top.pools || [];
    const cells = this.cells();
    const line = (pool) => (pool.steps || []).map((row) => this.modelName(row, cells)).filter(Boolean).join(", ");
    if (kind === "client") {
      const now = String(ConsumerCards.of(top).find((c) => Number(c.port) === Number(from.port))?.set || "");
      return (top.sets || []).map((s) => ({ key: `set:${s.id}`, label: String(s.name || s.id), to: { set: s.id }, now: s.id === now,
        hint: (s.pools || []).map((pid) => String(pools.find((p) => p.id === pid)?.name || pid)).join(", ") }));
    }
    if (kind === "set") {
      const held = (top.sets || []).find((s) => s.id === from.setId)?.pools || [];
      return pools.map((p) => ({ key: `pool:${p.id}`, label: String(p.name || p.id), hint: line(p), to: { pool: p.id }, now: held.includes(p.id) }));
    }
    if (kind === "row" || kind === "new-row") {
      // A model the pool has in a row already is marked too: twice in one pool, it would be tried twice.
      const held = new Set((pools.find((p) => p.id === from.poolId)?.steps || []).map((s) => PoolBoard.key(s)).filter(Boolean));
      return this.targets(cells).map((x) => ({ ...x, now: held.has(x.key) }));
    }
    if (kind === "model") {
      const key = PoolBoard.key(from.target);
      return [{ key: "pool:new", label: t("pbChooseNewPool", { name: String(from.name || "") }), hint: "", to: { newPool: true }, now: false },
        ...pools.map((p) => ({ key: `pool:${p.id}`, label: String(p.name || p.id), hint: line(p), to: { pool: p.id },
          now: (p.steps || []).some((s) => PoolBoard.key(s) === key) }))];
    }
    return [];
  }

  // A row's model by the name the board shows it by: an account's model id, a cell's name.
  modelName(row, cells = this.cells()) {
    if (row?.kind === "account") return String(row.model || "");
    if (row?.kind !== "output") return "";
    const found = this.output(row.output);
    return found ? cells.name(found.out) : String(row.output);
  }

  // Every model a row can be cabled to: the models on each account's card, then each machine's cells.
  targets(cells = this.cells()) {
    const out = [];
    for (const account of this.top?.cloudAccounts || []) {
      for (const model of this.shownOf(account)) {
        out.push({ key: PoolBoard.key({ accountId: account.id, model }), label: model, hint: `☁ ${account.name || account.id}`,
          to: { target: { accountId: account.id, model }, name: model } });
      }
    }
    for (const group of this.machines()) {
      for (const cell of group.outs || []) {
        const name = cells.name(cell);
        out.push({ key: PoolBoard.key({ output: cell.id }), label: name, hint: PoolBoard.where(cell, group),
          to: { target: { output: cell.id }, name } });
      }
    }
    return out;
  }

  // What is typed redraws the list alone: the field keeps its place and its caret.
  chooseFind(query) {
    if (!this.chooser) return;
    this.chooser.query = String(query || "");
    const body = this.root?.querySelector?.("[data-pb-chooser] [data-pb-choose-body]");
    if (body) body.innerHTML = this.chooseBodyHtml();
  }

  // A place picked: the cable is drawn there, as if carried. Refused — the list comes back, and the
  // toast says why.
  async choose(key) {
    const was = this.chooser;
    const choice = was ? this.choices(was.kind, was.from).find((x) => x.key === key && !x.now) : null;
    const ask = choice ? PoolBoard.ask(was.kind, was.from, choice.to) : null;
    if (!ask) return null;
    this.closeChooser();
    const res = await this.send(...ask);
    if (!res) {
      this.chooser = was;
      this.showChooser();
    }
    return res;
  }

  // Esc anywhere on the page: the chooser closes, else a pinned path lets go — one at a time, and none
  // while something is carried (its own Esc gives it back) or after a field has taken the Esc.
  escape(event) {
    if (event.key !== "Escape" || event.defaultPrevented || this.drag || this.carry?.busy || this.cardCarry?.busy) return null;
    if (this.chooser) {
      event.preventDefault?.();
      return this.closeChooser();
    }
    if (!this.trace?.pinned) return null;
    event.preventDefault?.();
    this.trace = null;
    this.lightPath();
    return true;
  }

  // ── carrying a card ─────────────────────────────────────────────────

  // Routing's cards as StepCarry carries them (1.3.503): a card's seat in its column, the column,
  // the grip in the card's head, the card's id, the column's kind, the card that travels.
  static CARDS = {
    item: ".pb-seat",
    list: "[data-pb-list]",
    grip: "[data-pb-card-grip]",
    idOf: (seat) => seat.dataset.pbSeat,
    ownerOf: (list) => list.dataset.pbList,
    card: (seat) => seat.firstElementChild,
  };

  // Where each column's order is kept: the pools' and the sets' in the cloud file, the clients' in the
  // board's layout (caravan/admin/board_layout.py, ClientOrder).
  static ORDERS = {
    pools: (ids) => ["/api/pools/order", { ids }],
    sets: (ids) => ["/api/sets/order", { ids }],
    clients: (ids) => ["/api/consumers/order", { order: ids.map(Number) }],
  };

  // The order a card's carry left behind, saved; the answer draws the board. Refused — the toast says
  // why, and the board is drawn from what the controller keeps.
  async saveOrder(kind, ids) {
    const door = PoolBoard.ORDERS[kind];
    const res = door ? await this.send(...door(ids)) : null;
    if (!res) this.redrawAfterCarry();
    return res;
  }

  // A row's new place in its pool, saved by the pool cards' door (pools.js) — refused, drawn back the same way.
  async sortRows(poolId, ids) {
    const res = await this.actions.sort(poolId, ids);
    if (!res) this.redrawAfterCarry();
    return res;
  }

  // A carried order the controller did not keep stayed on the screen and read as saved: the board is
  // drawn again once the carry has let go — it holds the board until its save is answered.
  redrawAfterCarry() {
    this.pending = true;
    (this.win?.setTimeout?.bind(this.win) || setTimeout)(() => this.settled(), 0);
  }

  // "Arrange by the cables" (the owner, 2026-10-12): the pools in the order the sets name them, the
  // models of each account in the order the pools' rows name them — the controller's
  // (/api/pools/arrange). The cables then run alongside one another more than across.
  async arrange() {
    const res = await this.send("/api/pools/arrange", {});
    if (res) this.notify(t("pbArranged"));
    return res;
  }
}

export const POOL_BOARD = new PoolBoard();
