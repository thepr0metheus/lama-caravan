// Routing (the owner, 2026-10-12): clients, pools and models in columns, joined by cables — the mockup the owner approved
// ("I like such mockups. Build them.").
//
// The owner, 2026-10-27: "every client we make has every model and every pool; the pools pass for models of their own; sets
// seem not to be needed; on a client we set which models or pools it may NOT have; the cables show only when we draw them, OR
// when a block is selected, OR when requests run". So three columns, and of the mockups the owner chose В2: Clients, «What is
// called» — on its top «Напрямую», pinned, a row for each model a client calls without a pool now (all of them, the owner: "let
// all be seen") — then the pools, and Models. A client's `GET /v1/models` lists every pool, then every model that runs, but what
// is blocked for it (rust/crates/rules/src/entry_models.rs); a client's card says how many it sees and what is blocked for it, and its
// "＋ Block" opens the window that blocks or unblocks a source whole, a model or a pool (option А). No cable crosses a column: a
// client's runs to a pool or to its «Напрямую» row, a pool's row and a «Напрямую» row run on to their model.
//
// "In a pool only the list of the models on the right is gathered, a row added by "+" in the pool; each row gives one more
// output, and that output is cabled to the model on the right": a pool is its rows in order, each a subscription's model or a
// machine's model (rust/crates/rules/src/cloud_pools.rs), tried from the top (rust/crates/proxy/src/pool_steps/mod.rs). "The limit bars belong not on
// the pool but on the models themselves, on the right": a subscription model's two levels hold in every pool whose row names it
// (rust/crates/rules/src/usage_limits.rs).
//
// The board draws the controller's reading and works out nothing of its own: what a client sees and is blocked from (`models`,
// `deny`, `entryModels`, `denyChoices`), what it called over three days (`calls`), what each row is cabled to, which row served
// last and why the others did not (the proxy's word, `poolsRuntime`). A pool's row is cabled by carrying an output's dot onto a
// model, and cut by a click on its cable; a new row by carrying a "＋" row from any point of it. A row is carried by its grip to
// another place (step-carry.js). A pool's settings — the window it states to its clients — open under its rows. A client's strip
// links what the client gets for its own GET questions, asked with its key by the controller. "Show only the models I added"
// (the owner, 2026-10-12): an account's card holds the models added to it with "＋ model", not every model the account offers
// (rust/crates/rules/src/cloud_models.rs). The account itself is set up on the main board (provider-glances.js).
//
// The reader block (static/js/reader-block.js) is the part of the Pools column that names a model for a picture none of any
// pool's rows can take: one row for the whole board, the name the operator gave it, and the word the rule answered for that
// name. The board draws the word it is given (`top.reader.answer`, from `Reader::word()`) and works out no state of its own;
// its row has an output dot and no input dot, and its cable — drawn at rest, because a wiring is what was named and not a
// path a request has run through — goes to the model card the name resolves to. A click on that cable writes the absence back.
import { CableFlow } from "./cable-flow.js";
import { ConsumerCards } from "./consumers.js";
import { EntryClients } from "./entry-clients.js";
import { appConfirm } from "./dialogs.js";
import { cloudApiIssuesHtml } from "./cloud.js";
import { t } from "./i18n.js";
import { OutputCells } from "./output-cells.js";
import { PoolCards } from "./pools.js";
import { PoolDock } from "./pool-dock.js";
import { PoolFlow } from "./pool-flow.js";
import { PoolReveal } from "./pool-reveal.js";
import { ReaderBlock } from "./reader-block.js";
import { ModelScheduleEditor } from "./model-schedule.js";
import { JOB_LABELS, JOB_MARKS } from "./model-jobs.js";
import { ModelQueue } from "./model-queue.js";
import { ClientNameSettings } from "./client-name-settings.js";
import { ModelQueueSettings } from "./model-queue-settings.js";
import { localOutputGroups } from "./routers.js";
import { ServerOrder } from "./server-order.js";
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
  // A local model's state → its lamp: lit when it serves, a ring when it does not run, amber on the way
  // up or down, red when it failed — and a ring for a state nobody said (OutputCells: "unknown").
  static LEDS = { running: "", stopped: "off", starting: "wait", stopping: "wait", failed: "bad", unknown: "off" };

  constructor({ call = api, notify = toast, confirm = appConfirm, apply = null, copy = copyText, win = globalThis, doc = globalThis.document,
    agents = () => ui.latestSystemMonitor?.latest?.agentProxies?.agents, now = () => Date.now(),
    slots = () => ui.latestSystemMonitor?.latest?.agentProxies?.slotTotals } = {}) {
    this.call = call;
    this.agents = agents;          // the monitor's rows of requests, by client id: what the cables' drops are read from (pool-flow.js)
    this.slots = slots;            // the slots the proxy counted for each upstream, by its group: how many a model's queue serves at once
    this.now = now;
    this.notify = notify;
    this.copy = copy;
    this.confirm = confirm;
    this._apply = apply;
    this.win = win;
    this.doc = doc;
    this.top = null;               // the topology the last drawing read
    this.sources = new ServerOrder();   // the order of the Models column's cards, as far as this page knows: a poll older than a save does not put it back
    this.root = null;              // the page's container the board is drawn into (mount)
    this.expanded = new Set();     // "m:<machine>": the machines whose every cell is shown
    this.picking = null;           // the account whose "＋ model" is open: {accountId, query}
    this.scroll = null;            // where the board stood scrolled when the page drew it last: {top, left}
    this.history = new Set();      // the pools whose switch history is open
    this.settings = new Set();     // the pools whose "Pool settings" are open
    this.tests = new Set();        // the clients (by id) whose "Test as the client" is open
    this.probe = null;             // a client's test request in its window: {id, label, path, model, busy | result | error}
    this.probeModel = new Map();   // client id → the model of its set its tests name (the first, until chosen)
    this.catalogues = new Map();   // usage account id → {models, fetchedAt} | {loading: true} | {error}
    this.drag = null;              // a cable being drawn: {kind, from, dot, pointerId}
    this.drops = [];               // the cables the last drawing could not place, and why
    this.flowDrawn = "";           // what the last drawing lit (PoolFlow signature): a reading that would light the same is skipped
    this.flowing = new Set();      // the dots the last drawing ringed, the ends of the cables that carry a request
    this.carry = null;             // who carries a row to another place (StepCarry, made on mount)
    this.cardCarry = null;         // who carries a client's, set's or pool's card to another place (made on mount)
    this.trace = null;             // the path lit on the board: {key, pinned} — a card's cables up to its clients and down to its models
    this.chooser = null;           // the targets a click on an output lists: {kind, from, query, x, y}
    this.denying = null;           // the window of what is blocked for a client: {port, query}
    this.moveKept = new Set();     // the twins the window of the move keeps, by id: unticked, they are not deleted
    this.pending = false;          // a drawing asked for while something was held
    this.dock = new PoolDock();    // the strip below the columns: what the trace points at (pool-dock.js)
    this.dockDrawn = "";           // the strip as the last drawing left it: a drawing that would read the same is skipped
    this.revealTimer = 0;          // the wait before the board follows the path of the card the pointer rests on (pool-reveal.js)
    this.userScrolled = -Infinity; // when the person last scrolled with a wheel or a finger: the board leaves the scrolling to them for a while
    this.pointer = { x: 0, y: 0 }; // where the pointer was last
    this.settling = null;          // the pointer's place while the board scrolled across under it: the cards that pass under a still pointer are not pointed at
    // The pool's own doors — its deletion with what holds it, its order, its name — are the
    // pool cards' (pools.js): one way to do each, for both pages.
    this.actions = new PoolCards({ call, notify, confirm, apply: (top) => this.applied(top) });
    // When each model is open: its ⏱ and the window that sets it (model-schedule.js).
    this.schedule = new ModelScheduleEditor({ call, notify, apply: (top) => this.applied(top), redraw: () => this.redraw() });
    // The models' queue — its two settings, one for every model (model-queue-settings.js) — and what it drew last.
    this.queue = new ModelQueueSettings({ call, notify });
    this.clientName = new ClientNameSettings({ call, notify });
    this.queueDrawn = new Map();   // [data-pb-queue-*] mark → the words or markup it holds: a reading that would draw the same touches nothing
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

  // Routing's router: its outputs are the machines' models and the engines', one per `mm:<hash>` and `eng:<id>`, and the
  // pools', `cb:<pool>` (rust/crates/admin/src/proxies/config/outputs.rs). A cell is no output of its own since 2026-11-07:
  // it is a copy of its machine's model.
  router() {
    const routers = this.top?.routers || [];
    return routers.find((r) => r.id === "router:default") || routers[0] || { outputs: [] };
  }

  cells() {
    return new OutputCells(this.top, this.router());
  }

  // The machines with their local outputs, each named as Routing names a machine: a machine stands in the column by the models
  // of its entry (1.3.506) and of its engines, by name. Until 2026-11-07 a cell was an output of its own (`srv:<port>`) and
  // stood here by its port where a pool's row still named it (1.3.655); now it is a copy of its machine's model, and a machine
  // whose scout lists no models stands here by its engines' models alone, if it has any.
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

  // A machine's rows: the models a row names and the ones not stopped, in the order given; the stopped
  // models no row names fold under one button while there are two or more of them — a button that
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

  // The port a local output's row says: an engine's own (Ollama's 11434, LM Studio's 1234), or null. A model of a machine's
  // entry has none of its own — its port is the machine's entry, every model's (1.3.506) — and a cell holds one only while it
  // runs, so no port names a cell (Papyrus caravan-scout-port-lease, 2026-11-07).
  static enginePort(out) {
    const port = Number(out?.upstreamPort);
    return String(out?.upstreamType || "") === "engine" && Number.isInteger(port) && port > 0 ? port : null;
  }

  // A local output as rows and lists name it: by its name, an engine's model with its engine's port after it.
  static outLabel(out, cells) {
    const port = PoolBoard.enginePort(out);
    return port ? `${cells.name(out)} :${port}` : cells.name(out);
  }

  // Where a local output stands, as a row's target and the chooser say it: its machine, and an engine's port.
  static where(out, group) {
    const port = PoolBoard.enginePort(out);
    const machine = `🖥 ${group?.name || ""}`;
    return port ? `${machine} :${port}` : machine;
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

  // What a key's model does, as the controller keeps the operator's word (`modelJobs`,
  // rust/crates/rules/src/cloud_models.rs, 1.3.631): `said` — its jobs, empty when nobody said; `offered` — the jobs it may
  // be said to do. null when there is nothing to say: the account's type fixes the work (a subscription, an Anthropic key),
  // or the controller says nothing of words at all — then no field and no mark, never a guess.
  workOf(accountId, model) {
    const jobs = this.top?.modelJobs;
    if (!jobs || jobs.fixed?.[accountId]) return null;
    return { said: [...(jobs.set?.[accountId]?.[model] || [])], offered: [...(jobs.offered || [])] };
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
    this.sources.read(this.top);
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
      <section class="pb-col" data-pb-pools-drop data-pb-drop-hint="${escapeHtml(t("pbDropNewPool"))}" data-t="pb-pools">${this.poolsHtml()}</section>
      <section class="pb-col" data-t="pb-models">${this.modelsHtml()}</section>
      <svg class="pb-cables" data-pb-cables data-t="pb-cables" aria-hidden="true"></svg>
      <svg class="pb-cables pb-live-layer" data-pb-live-layer aria-hidden="true"></svg>
    </div>${this.dockHtml()}${this.probeHtml()}${this.schedule.html()}${this.chooserHtml()}${this.denyHtml()}${this.moveHtml()}`;
  }

  head(title, button) {
    return `<div class="pb-col-head"><span>${escapeHtml(title)}</span>${button}</div>`;
  }

  // A column is its head, which stays where it is, and under it its body: the list of its cards, which is what scrolls and
  // is the mark the scroll is kept by (`data-pb-scroll`) across drawings. The owner, 2026-10-18: "the headings outside the area
  // I scroll, shown always — it is not pretty when I scroll a column down": until 1.3.573 the head was the first child of the
  // scrolling column and stuck to its top, so the cards passed under it. The cards that can be put in another order name the list
  // they are carried in (`data-pb-list`); a column with nothing to carry has no such list.
  static column(key, head, body, { list = true } = {}) {
    return `${head}<div class="pb-col-body"${list ? ` data-pb-list="${key}"` : ""} data-pb-scroll="${key}">${body}</div>`;
  }

  // A card in its column's list: the seat it is carried from (StepCarry, `cardCarry`) — it stays as
  // the empty place while the card travels — and the card's grip, in its head (the owner,
  // 2026-10-12: "the order of the blocks in Clients, Sets and Pools changed by dragging"; 2026-10-28, of Models: "them too").
  static seat(id, html) {
    return `<div class="pb-seat" data-pb-seat="${escapeHtml(String(id))}">${html}</div>`;
  }

  static gripHtml() {
    return `<span class="pb-card-grip" data-pb-card-grip tabindex="0" role="button" title="${escapeHtml(t("pbCardGrip"))}" aria-label="${escapeHtml(t("pbCardGrip"))}">⠿</span>`;
  }

  // Clients and subscriptions are added on the main board (the owner, 2026-10-12): Routing's columns of clients and of models
  // have no "＋" of their own; it connects what is there. The built-in clients stand first, in their kinds' order
  // (ConsumerCards.of), with no seat: they stand first whatever the order, and a grip would offer to carry one where it cannot
  // stay. Since 1.3.675 they are clients as any other — no line under them, the same card.
  clientsHtml() {
    // The head says the name the cloud providers see, and opens its field at the top of the column.
    const policy = this.top?.proxyPolicy;
    const head = this.head(t("topologyClientsSection"), this.clientName.buttonHtml(policy)), entry = this.clientName.panelHtml(policy) + this.entryHtml();
    const clients = ConsumerCards.of(this.top);
    if (!clients.length) return PoolBoard.column("clients", head, `${entry}<p class="pb-empty" data-t="pb-no-clients">${escapeHtml(t("pbNoClients"))}</p>`);
    return PoolBoard.column("clients", head, entry + clients.map((c) => (EntryClients.builtin(c)
      ? this.clientHtml(c) : PoolBoard.seat(c.id, this.clientHtml(c)))).join(""));
  }

  // A client's card says who it is, how many of the caravan's models it sees and whether it was refused, and what it is closed
  // to (the owner, 2026-10-27, option А: "chips on the card, and a window to choose"): a chip for each refusal and "＋ Block"
  // that opens the window (denyHtml). Its address, links, tests and errors are in the strip below while the card is pointed at
  // or pinned. The dot at its right edge is where its cables leave from: no cable is drawn from it by hand — a client calls what
  // it names, and every pool and model is open to it.
  clientHtml(c) {
    const id = escapeHtml(String(c.id || ""));
    const builtin = EntryClients.builtin(c);
    const paused = ["paused", "drain"].includes(String(c.mode || "open"));
    const missed = PoolBoard.missBadge(c);
    const badge = missed ? `<span class="pb-miss-badge" data-t="pb-client-misses-badge" title="${escapeHtml(t("pbClientMisses"))}">⚠ ${escapeHtml(missed)}</span>` : "";
    const deny = Array.isArray(c.deny) ? c.deny.map(String) : [];
    const sees = EntryClients.sees(c, this.top?.entryModels);
    const name = escapeHtml(String(c.label || ""));
    const chips = deny.map((key) => {
      const label = this.denyLabel(key);
      return `<span class="pb-chip pb-deny-chip${label.gone ? " gone" : ""}" data-t="pb-deny-chip" data-t-id="${escapeHtml(key)}" title="${escapeHtml(label.title)}">⊘ ${escapeHtml(label.name)}</span>`;
    }).join("");
    return `<article class="pb-card pb-client${builtin ? " builtin" : ""}${paused ? " paused" : ""}" data-pb-client="${id}" data-pb-node="client:${id}" data-t="pb-client" data-t-id="${id}" data-t-state="${builtin ? "builtin" : deny.length ? "closed" : "open"}"${builtin ? ` data-builtin="${escapeHtml(EntryClients.kind(c))}"` : ""}>
      ${builtin ? "" : PoolBoard.gripHtml()}<span class="pb-client-name" title="${name}">${name}</span>
      ${builtin ? `<span class="pb-chip pb-builtin" data-t="pb-client-builtin" title="${escapeHtml(ConsumerCards.words(c).title)}">${escapeHtml(t("consumerBuiltinChip"))}</span>` : ""}
      <span class="pb-key" title="${escapeHtml(t("consumerKeyTitle"))}">🔑 …${escapeHtml(String(c.keyTail || ""))}</span>
      <span class="pb-dot out anchor" data-pb-anchor aria-hidden="true"></span>
      <span class="pb-client-sub"><span class="pb-client-count" data-t="pb-client-count" data-t-state="${sees}">${escapeHtml(ConsumerCards.seesText(c, this.top?.entryModels))}</span>${badge}</span>
      <span class="pb-client-deny" data-t="pb-client-deny">${chips}<button class="pb-deny-add" type="button" data-pb-deny-open data-t="pb-deny-open" title="${escapeHtml(t("pbDenyAddTitle", { name: String(c.label || "") }))}">＋ ${escapeHtml(t("pbDenyAdd"))}</button></span>
    </article>`;
  }

  // A refusal's key as a chip says it (ClientDeny): a pool, a model or a source — an account or a machine — by the name the board
  // shows it by. A key whose pool, model or source the board no longer has is said as gone: it closes nothing, and the operator
  // takes it off in the window.
  denyLabel(key) {
    const [kind, ...rest] = String(key || "").split(":");
    const id = rest.join(":");
    const choices = this.top?.denyChoices;
    if (kind === "pool") {
      const pool = (this.top?.pools || []).find((x) => String(x.id) === id);
      return pool ? { name: String(pool.name || pool.id), title: t("pbDenyPool", { name: String(pool.name || pool.id) }) } : PoolBoard.gone(key);
    }
    if (kind === "model") {
      const model = (choices?.models || []).find((m) => m.key === key);
      return model ? { name: model.name, title: t("pbDenyModel", { name: model.name }) } : PoolBoard.gone(key);
    }
    if (kind === "account" || kind === "host") {
      const name = this.sourceName(key);
      return name ? { name, title: t("pbDenySource", { name }) } : PoolBoard.gone(key);
    }
    return PoolBoard.gone(key);
  }

  static gone(key) {
    return { name: t("pbDenyGone"), title: t("pbDenyGoneTitle", { key: String(key) }), gone: true };
  }

  // A source a refusal names, by the name the board shows it by: an account by its name, a machine by its card's — "" for one
  // the board does not have.
  sourceName(key) {
    const [kind, ...rest] = String(key || "").split(":");
    const id = rest.join(":");
    if (kind === "account") {
      const account = this.account(id);
      return account ? String(account.name || account.id) : "";
    }
    if (kind === "host") {
      const group = this.machines().find((g) => (g.outs || []).some((o) => String(o.hostId || "") === id));
      return group ? String(group.name ?? id) : (((this.top?.denyChoices?.sources) || []).includes(key) ? id : "");
    }
    return "";
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
  // client gets"): its two questions by GET — the model list, and one model — each opening what the entry answers
  // its key. The controller asks with the key (GET /api/consumers/ask): the page never holds one, and a link to the
  // entry itself would only be refused for want of it. The model is the one its tests name, chosen in the list
  // beside it: since 1.3.675 a client sees every model, and a link for each was a column of twenty. Without the entry
  // there is nothing to ask; with no model to see, no model to name. They stand in the strip below.
  asksHtml(c) {
    if (!String(this.top?.entry?.url || "")) return "";
    const ask = (path, id) => `<a class="pb-ask" href="${escapeHtml(`/api/consumers/ask?routeId=${encodeURIComponent(String(c.id))}&path=${encodeURIComponent(path)}`)}"`
      + ` data-t="pb-client-ask" data-t-id="${id}" title="${escapeHtml(t("pbClientAskTitle"))}">${escapeHtml(path)}</a>`;
    const model = this.probeModelOf(c);
    return `<div class="pb-client-asks" data-t="pb-client-links">${ask("/v1/models", "list")}${this.probeModelHtml(c, (c.models || []).map(String))}`
      + `${model ? ask(`/v1/models/${model}`, "model") : ""}</div>`;
  }

  // The work a client asks for by POST, each a test the controller sends as the client: the paths
  // are the controller's table (topology.clientProbes), the one that sends them, naming the model chosen
  // beside the GET links (asksHtml). Shut under "Test as the client" until opened —
  // six buttons are four lines of the narrow card — and kept open while the board is drawn again.
  probesHtml(c) {
    const table = this.top?.clientProbes || [];
    if (!table.length) return "";
    const open = this.tests.has(String(c.id));
    const head = `<button class="pb-tests-head${open ? " open" : ""}" type="button" data-pb-tests aria-expanded="${open}" data-t="pb-client-tests">`
      + `${escapeHtml(t("pbProbeRow"))}</button>`;
    if (!open) return head;
    const buttons = table.map((p) => `<button class="pb-probe-btn" type="button" data-pb-probe="${escapeHtml(String(p.path))}"`
      + ` data-t="pb-client-probe" data-t-id="${escapeHtml(String(p.path))}" title="${escapeHtml(t(p.paid ? "pbProbePaidTitle" : "pbProbeTitle"))}">`
      + `${escapeHtml(String(p.path).replace(/^\/v1\//, ""))} ▶</button>`).join("");
    return `${head}<span class="pb-client-probes">${buttons}</span>`;
  }

  // Which of the models the client sees its tests and its GET link name: a choice when it sees more than one.
  probeModelHtml(c, models) {
    if (models.length < 2) return "";
    const chosen = this.probeModelOf(c);
    return `<select class="pb-probe-model" data-pb-probe-model data-t="pb-client-probe-model" aria-label="${escapeHtml(t("pbProbeModel"))}" title="${escapeHtml(t("pbProbeModel"))}">`
      + models.map((m) => `<option value="${escapeHtml(m)}"${m === chosen ? " selected" : ""}>${escapeHtml(m)}</option>`).join("") + "</select>";
  }

  // The model a client's test names: the one chosen while the client still sees it, else the first.
  probeModelOf(c) {
    const models = (c?.models || []).map(String);
    const chosen = this.probeModel.get(String(c?.id));
    return models.includes(chosen) ? chosen : (models[0] || "");
  }

  // What the client asked and was answered with an error over the last 30 days (the owner,
  // 2026-10-12: "to see, say, that it asked /api/show"): the controller's reading of the proxy's
  // journal (rust/crates/admin/src/cloud/misses.rs), newest first, the rest counted. No errors, or no
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
    const head = `<header class="pb-probe-head"><b>${escapeHtml(String(p.label || ""))}</b><code>POST ${escapeHtml(base + p.path)}</code>${close}</header>`;
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
  async runProbe(id, path) {
    const client = ConsumerCards.of(this.top).find((c) => String(c.id) === String(id));
    const probe = (this.top?.clientProbes || []).find((p) => p.path === path);
    if (!client || !probe) return null;
    if (probe.paid) {
      const sure = await this.confirm(t("pbProbePaidAsk", { client: String(client.label || "") }),
        { title: t("pbProbePaidTitle"), danger: false, confirmLabel: t("pbProbeSend") });
      if (!sure) return null;
    }
    const asked = { id: String(client.id), label: String(client.label || ""), path, model: this.probeModelOf(client) };
    this.probe = { ...asked, busy: true };
    this.redraw();
    let landed;
    try {
      landed = { ...asked, result: await this.call("/api/consumers/probe", { method: "POST", body: JSON.stringify({ routeId: asked.id, path, model: asked.model }) }) };
    } catch (err) {
      landed = { ...asked, error: String(err?.message || err) };
    }
    if (this.probe?.id !== asked.id || this.probe?.path !== path) return null;
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

  // ── what a client is blocked from (the owner, 2026-10-27, option А) ────

  // "＋ Block" on a client's card opens what can be blocked for it (`denyChoices`, the controller's): each source — an account, a
  // machine — with a box that closes all of it and its models under it, then the pools, each ticked while it is closed. Listed at
  // once are the models that run and the ones closed already; the search finds the rest — a model can be closed before it runs.
  // A model a closed source closes is ticked and cannot be opened by itself. A model blocked for the client that one of its pools
  // still calls says so: the pool works whole (the owner's choice "а"). Each box is saved as it is ticked; "Done" closes the window.
  openDeny(id) {
    const client = ConsumerCards.of(this.top).find((c) => String(c.id) === String(id));
    if (!client) return null;
    this.denying = { id: String(client.id), query: "" };
    this.redraw();
    this.focusField("[data-pb-deny] [data-pb-deny-query]");
    return true;
  }

  closeDeny() {
    if (!this.denying) return null;
    this.denying = null;
    this.letGoField("[data-pb-deny-query]");
    this.redraw();
    return true;
  }

  denyHtml() {
    const d = this.denying;
    const client = d ? ConsumerCards.of(this.top).find((c) => String(c.id) === d.id) : null;
    if (!client) return "";
    const title = t("pbDenyTitle", { name: String(client.label || "") });
    const close = `<button class="pb-tool" type="button" data-pb-deny-close data-t="pb-deny-close" title="${escapeHtml(t("topologyClose"))}" aria-label="${escapeHtml(t("topologyClose"))}">✕</button>`;
    return `<div class="pb-modal" data-pb-deny role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}" data-t="pb-deny" data-t-id="${escapeHtml(String(client.id))}">`
      + `<div class="pb-modal-box"><header class="pb-modal-head"><b>${escapeHtml(title)}</b>${close}</header>`
      + `<p class="pb-modal-note">${escapeHtml(t("pbDenyNote"))}</p>`
      + `<input class="pb-picker-find" type="search" data-pb-deny-query data-t="pb-deny-query" value="${escapeHtml(String(d.query || ""))}"`
      + ` placeholder="${escapeHtml(t("pbDenyFind"))}" aria-label="${escapeHtml(t("pbDenyFind"))}" autocomplete="off" spellcheck="false">`
      + `<div class="pb-deny-body" data-pb-deny-body>${this.denyBodyHtml(client)}</div>`
      + `<footer class="pb-modal-foot"><button class="primary" type="button" data-pb-deny-close data-t="pb-deny-done">${escapeHtml(t("pbDenyDone"))}</button></footer>`
      + `</div></div>`;
  }

  // The window's lists, as the search leaves them. Not read — not known, said so: an empty window would say nothing can be closed.
  denyBodyHtml(client) {
    const choices = this.top?.denyChoices;
    if (!choices) return `<p class="pb-picker-note" data-t="pb-deny-unread">${escapeHtml(t("pbDenyUnread"))}</p>`;
    const closed = new Set((Array.isArray(client.deny) ? client.deny : []).map(String));
    const want = String(this.denying?.query || "").trim().toLowerCase();
    const hit = (...texts) => !want || texts.some((text) => String(text || "").toLowerCase().includes(want));
    const box = ({ key, name, hint = "", note = "", by = "", head = false }) => {
      const on = closed.has(key) || !!by;
      return `<label class="pb-deny-item${head ? " head" : ""}${on ? " closed" : ""}" data-t="pb-deny-item" data-t-id="${escapeHtml(key)}" data-t-state="${by ? "by-source" : on ? "closed" : "open"}">`
        + `<input type="checkbox" data-pb-deny-key="${escapeHtml(key)}"${on ? " checked" : ""}${by ? " disabled" : ""}>`
        + `<span class="pb-deny-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span>${hint ? `<small>${escapeHtml(hint)}</small>` : ""}`
        + (by ? `<small class="pb-deny-hint" data-t="pb-deny-by-source">${escapeHtml(t("pbDenyBySource", { name: by }))}</small>` : "")
        + (note ? `<small class="pb-deny-hint" data-t="pb-deny-still">${escapeHtml(note)}</small>` : "") + `</label>`;
    };
    const pools = this.top?.pools || [];
    // The pools that still call a model blocked for the client: the ones not blocked for it whose enabled rows name the model.
    const still = (key) => pools.filter((pool) => !closed.has(`pool:${pool.id}`)
      && (pool.steps || []).some((row) => row.enabled !== false && PoolBoard.denyKey(PoolBoard.key(row)) === key)).map((pool) => String(pool.name || pool.id));
    const groups = [];
    for (const source of [...choices.sources, ""]) {
      const models = choices.models.filter((m) => m.source === source);
      if (!models.length && source === "") continue;
      const name = source ? this.sourceName(source) || source.slice(source.indexOf(":") + 1) : t("pbDenyNoSource");
      const whole = source && closed.has(source) ? name : "";
      const shown = models.filter((m) => (want ? hit(m.name, name) : m.runs || closed.has(m.key)));
      if (want && !shown.length && !hit(name)) continue;
      const rows = shown.map((m) => {
        const left = closed.has(m.key) && !whole ? still(m.key) : [];
        return box({ key: m.key, name: m.name, hint: m.runs ? "" : t("pbDenyStopped"), by: whole,
          note: left.length ? t("pbDenyStillPools", { pools: left.join(", ") }) : "" });
      }).join("");
      const more = models.length - shown.length;
      groups.push(`<div class="pb-deny-group" data-t="pb-deny-group" data-t-id="${escapeHtml(source)}">`
        + (source ? box({ key: source, name, hint: t("pbDenyWhole", { n: String(models.length) }), head: true }) : `<div class="pb-deny-head">${escapeHtml(name)}</div>`)
        + rows + (more > 0 && !want ? `<p class="pb-picker-note" data-t="pb-deny-more">${escapeHtml(t("pbDenyMore", { n: String(more) }))}</p>` : "") + `</div>`);
    }
    const poolRows = choices.pools.filter((pool) => hit(pool.name)).map((pool) => box({ key: pool.key, name: pool.name })).join("");
    if (poolRows) groups.push(`<div class="pb-deny-group" data-t="pb-deny-group" data-t-id="pools"><div class="pb-deny-head">${escapeHtml(t("pbPoolsSection"))}</div>${poolRows}</div>`);
    // A refusal whose pool, model or source the board no longer has: it closes nothing, and it is taken off here.
    const known = new Set([...choices.sources, ...choices.models.map((m) => m.key), ...choices.pools.map((pool) => pool.key)]);
    const gone = [...closed].filter((key) => !known.has(key)).map((key) => box({ key, name: key, hint: t("pbDenyGone") })).join("");
    if (gone) groups.push(`<div class="pb-deny-group" data-t="pb-deny-group" data-t-id="gone">${gone}</div>`);
    return groups.length ? groups.join("") : `<p class="pb-picker-note" data-t="pb-deny-none">${escapeHtml(t("pbChooseNoMatch"))}</p>`;
  }

  // What is typed redraws the lists alone: the field keeps its place and its caret.
  denyFind(query) {
    if (!this.denying) return;
    this.denying.query = String(query || "");
    const client = ConsumerCards.of(this.top).find((c) => String(c.id) === this.denying.id);
    const body = this.root?.querySelector?.("[data-pb-deny] [data-pb-deny-body]");
    if (client && body) body.innerHTML = this.denyBodyHtml(client);
  }

  // A box ticked: the client's refusals with that key or without it, saved at once (POST /api/consumers/deny). The board is
  // drawn with the answer, and the box keeps the keyboard's focus. Refused — the toast says why, and the board is drawn from
  // what the controller keeps.
  async toggleDeny(key, on) {
    const client = this.denying ? ConsumerCards.of(this.top).find((c) => String(c.id) === this.denying.id) : null;
    if (!client || !key) return null;
    const was = (Array.isArray(client.deny) ? client.deny : []).map(String);
    const deny = on ? [...was.filter((k) => k !== key), key] : was.filter((k) => k !== key);
    const res = await this.send("/api/consumers/deny", { routeId: String(client.id), deny });
    if (!res) { this.redraw(); return null; }
    const esc = (v) => (globalThis.CSS?.escape ? globalThis.CSS.escape(String(v)) : String(v));
    this.root?.querySelector?.(`[data-pb-deny] [data-pb-deny-key="${esc(key)}"]`)?.focus?.();
    return res;
  }

  // ── the move to clients without sets (rust/crates/admin/src/cloud/entry_move.rs) ──

  // Once, after the move (the owner, 2026-10-27): what each client had and what it sees now, the sets that went, and the pools
  // that became twins — a pool of one row named as its model, which every client now calls straight by the same name — each
  // ticked to be deleted (the owner: "delete them"); this window is the one that asks. "Keep all" deletes nothing. Either answer
  // is the last time it shows.
  moveHtml() {
    const move = this.top?.entryMove;
    if (!move) return "";
    const twins = Array.isArray(move.twins) ? move.twins : [];
    const sees = t("pbClientSeesAll", { all: String(move.sees) });
    const rows = (move.clients || []).map((c) => `<tr data-t="pb-move-client" data-t-id="${escapeHtml(String(c.routeId || c.name || ""))}"><td>${escapeHtml(String(c.name || ""))}</td>`
      + `<td>${escapeHtml(String(c.had || t("pbMoveHadNone")))}</td><td>${escapeHtml(sees)}</td></tr>`).join("");
    const sets = (move.sets || []).map((x) => `${x.name}${(x.pools || []).length ? ` (${x.pools.join(", ")})` : ""}`).join("; ");
    const where = (twin) => (twin.where ? this.sourceName(`account:${twin.where}`) || this.sourceName(`host:${twin.where}`) || twin.where : "");
    const twinRows = twins.map((twin) => `<label class="pb-deny-item" data-t="pb-move-twin" data-t-id="${escapeHtml(twin.id)}">`
      + `<input type="checkbox" data-pb-move-twin="${escapeHtml(twin.id)}"${this.moveKept.has(twin.id) ? "" : " checked"}>`
      + `<span class="pb-deny-name">${escapeHtml(twin.name)}</span>${where(twin) ? `<small>${escapeHtml(where(twin))}</small>` : ""}</label>`).join("");
    return `<div class="pb-modal" data-pb-move role="dialog" aria-modal="true" aria-label="${escapeHtml(t("pbMoveTitle"))}" data-t="pb-move">`
      + `<div class="pb-modal-box wide"><header class="pb-modal-head"><b>${escapeHtml(t("pbMoveTitle"))}</b></header>`
      + `<p class="pb-modal-note">${escapeHtml(t("pbMoveLead", { n: String(move.sees) }))}</p>`
      + (rows ? `<div class="pb-move-table"><table><thead><tr><th>${escapeHtml(t("topologyClientsSection"))}</th><th>${escapeHtml(t("pbMoveHad"))}</th>`
        + `<th>${escapeHtml(t("pbMoveNow"))}</th></tr></thead><tbody>${rows}</tbody></table></div>` : "")
      + (sets ? `<p class="pb-modal-note" data-t="pb-move-sets">${escapeHtml(t("pbMoveSets", { sets }))}</p>` : "")
      + (twins.length ? `<h4>${escapeHtml(t("pbMoveTwins"))}</h4><p class="pb-modal-note">${escapeHtml(t("pbMoveTwinsNote"))}</p><div class="pb-deny-group">${twinRows}</div>` : "")
      + `<footer class="pb-modal-foot">${twins.length ? `<button type="button" data-pb-move-keep data-t="pb-move-keep">${escapeHtml(t("pbMoveKeep"))}</button>`
        + `<button class="danger" type="button" data-pb-move-delete data-t="pb-move-delete">${escapeHtml(this.moveDeleteLabel(twins))}</button>`
        : `<button class="primary" type="button" data-pb-move-keep data-t="pb-move-done">${escapeHtml(t("pbDenyDone"))}</button>`}</footer>`
      + `</div></div>`;
  }

  // The twins the window deletes: the ticked ones.
  moveDoomed(twins = this.top?.entryMove?.twins || []) {
    return twins.filter((twin) => !this.moveKept.has(twin.id));
  }

  moveDeleteLabel(twins) {
    return t("pbMoveDelete", { n: String(this.moveDoomed(twins).length) });
  }

  // A box of a twin ticked: the button says how many go, in place — the window is not drawn anew under the pointer.
  paintMoveButton() {
    const button = this.root?.querySelector?.("[data-pb-move-delete]");
    if (!button) return null;
    button.textContent = this.moveDeleteLabel(this.top?.entryMove?.twins || []);
    button.disabled = !this.moveDoomed().length;
    return true;
  }

  // The window answered: the ticked twins deleted one by one (a pool cables or rules hold is refused and stays, the toast says
  // why), then the move is marked seen and the window does not come back.
  async answerMove(remove) {
    const doomed = remove ? this.moveDoomed() : [];
    const deleted = [], kept = [];
    for (const twin of doomed) {
      try {
        await this.call("/api/pools/delete", { method: "POST", body: JSON.stringify({ id: twin.id }) });
        deleted.push(twin.name);
      } catch (err) {
        kept.push(`${twin.name}: ${err.message}`);
      }
    }
    const res = await this.send("/api/entry-move/seen", {});
    if (deleted.length) this.notify(t("pbMoveDeleted", { names: deleted.join(", ") }));
    if (kept.length) this.notify(t("pbMoveNotDeleted", { names: kept.join("; ") }));
    return res;
  }

  // What a model does, as the controller says its pool's rows do together (`pool.kind`,
  // rust/crates/admin/src/common/model_kinds.rs; 1.3.502 — what GET /v1/models tells the clients): the jobs'
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

  // A "＋" row that starts a new cable — a pool's onto a model: a dashed row with a dashed dot, carried by any point of it (the
  // owner, 2026-10-12: "drag not only by the circle but by the whole row"). It does nothing on a click: what it adds needs the
  // place the cable lands on.
  static newOutHtml(kind, testName, label, hint) {
    return `<div class="pb-new-out" data-pb-grab data-t="${escapeHtml(testName)}" title="${escapeHtml(hint)}"><span>＋ ${escapeHtml(label)}</span>`
      + `<span class="pb-dot out open" data-pb-out="${escapeHtml(kind)}" title="${escapeHtml(hint)}"></span></div>`;
  }

  // The order the column is read in, said once here and held by contract/media_reader_board.json (`column`): the direct
  // block, then the block that names a reader, then the pools' cards. The parts are named even when one of them is not
  // drawn — no pools, so no cards — because an absence has to be said, not left as a hole. The reader block is drawn whatever
  // the pools are: the reader is the board's, so its row does not depend on a pool being there, and the absence it shows is
  // the operator not having named anything.
  // Nothing here pins itself: Direct is simply the first block, not one held in view while the column scrolls
  // (the owner, 2026-11-06), so a part has no position of its own and the order is the only fact about where it sits.
  poolsHtml() {
    const head = this.head(t("pbPoolsSection"),
      `<span class="pb-head-tools"><button class="pb-add" type="button" data-pb-arrange data-t="pb-arrange" title="${escapeHtml(t("pbArrangeTitle"))}">⇅ ${escapeHtml(t("pbArrange"))}</button>`
      + `<button class="pb-add" type="button" data-pb-add-pool data-t="pb-add-pool">＋ ${escapeHtml(t("poolNew"))}</button></span>`);
    const pools = this.top?.pools || [];
    const direct = this.directHtml();
    const block = ReaderBlock.html(this.top?.reader);
    const empty = pools.length ? "" : `<p class="pb-empty" data-t="pb-no-pools">${escapeHtml(t("pbNoPools"))}</p>`;
    const cards = pools.map((pool) => PoolBoard.seat(pool.id, this.poolHtml(pool))).join("");
    return PoolBoard.column("pools", head, [direct, block, empty, cards].join(""));
  }

  // «Напрямую» (the owner, 2026-10-27, option В2: "the rows come and go by how many paths run straight now";
  // "let all be seen"): a row for each model a client calls now without a pool — one row a model, whatever number of
  // clients call it — and, while a client, a model or a row of it is pinned, the models called straight over three days. A
  // client's cable runs to the row, the row's on to its model: no cable crosses the column of pools. The rows are the monitor's
  // and the journal's (directRows); none — the head says nobody, and the block is one line. It is drawn anew in place as the
  // paths come and go (paintDirect).
  //
  // It is the first block of the column, and it is not pinned there (the owner, 2026-11-06): "не надо его прям закреплять
  // так чтобы его видно было и при свайпах. Просто пусть будет всегда самым верхним." The reader block stands directly
  // below it. The order is said once, in `poolsHtml`, and held by contract/media_reader_board.json.
  directHtml() {
    const rows = this.directRows();
    this.directDrawn = this.directBodyHtml(rows);
    return `<section class="pb-direct" data-pb-direct-block data-t="pb-direct" data-t-state="${rows.length ? "paths" : "quiet"}">${this.directDrawn}</section>`;
  }

  directBodyHtml(rows) {
    const paths = rows.filter((r) => r.state !== "recent").length;
    const count = rows.length ? (paths ? t("pbDirectPaths", { n: String(paths) }) : t("pbDirectPicked")) : t("pbDirectNone");
    return `<div class="pb-direct-head"><span class="pb-direct-title">${escapeHtml(t("pbDirect"))}</span>`
      + `<span class="pb-direct-sub">${escapeHtml(t("pbDirectSub"))}</span><span class="pb-direct-count" data-t="pb-direct-count">${escapeHtml(count)}</span></div>`
      + rows.map((row) => this.directRowHtml(row)).join("");
  }

  directRowHtml(row) {
    const pool = escapeHtml(row.pool);
    const target = row.key ? this.targetOf(row.key) : null;
    // A client the board no longer has is said as no client, never by a number.
    const who = row.clients.map((id) => String(ConsumerCards.of(this.top).find((c) => String(c.id) === id)?.label || "?")).join(", ");
    const note = row.state === "recent" ? t("pbDirectCalled", { who, n: String(row.count) }) : row.state === "ended" ? t("pbDirectEnded", { who }) : who;
    return `<div class="pb-direct-row ${escapeHtml(row.state)}" data-pb-direct="${pool}" data-pb-node="direct:${pool}" data-t="pb-direct-row" data-t-id="${pool}" data-t-state="${escapeHtml(row.state)}">`
      + `<span class="pb-dot in" data-pb-direct-in aria-hidden="true"></span><span class="pb-led${row.state === "live" ? "" : " off"}" aria-hidden="true"></span>`
      + `<b class="pb-direct-name" title="${escapeHtml(row.name)}">${escapeHtml(row.name)}</b>`
      + `<small class="pb-direct-where">${escapeHtml(target?.where || "")}</small>`
      + `<span class="pb-direct-who" title="${escapeHtml(note)}">${escapeHtml(note)}</span><span class="pb-dot out" data-pb-direct-out aria-hidden="true"></span></div>`;
  }

  // The block drawn anew where it stands — a path came or went, a card was pinned or let go — before the cables that run to its
  // rows are measured (drawCables). One that would read the same is not touched.
  paintDirect() {
    const el = this.root?.querySelector?.("[data-pb-direct-block]");
    if (!el) return false;
    const rows = this.directRows();
    const html = this.directBodyHtml(rows);
    if (html === this.directDrawn) return false;
    this.directDrawn = html;
    el.innerHTML = html;
    el.setAttribute?.("data-t-state", rows.length ? "paths" : "quiet");
    return true;
  }

  // The rows of «Напрямую»: the models called straight now or a moment ago (PoolFlow, the monitor's rows — a request on a pool of
  // one row, `live:…`), in the order the paths came; then, while a client is pinned, the ones it called straight over three days
  // (`calls`); while a model is pinned, its own row with the clients that called it straight; while a row of the block is pinned,
  // that row. Each {pool, name, key, clients, state: live | ended | recent, count}: its name and its model's key on the board come
  // from `liveCatalog`. A call of three days to a model the board no longer knows makes no row — there is no model to cable it to;
  // a request that runs now does, named by its pool's id while nobody names the model.
  directRows(now = this.now()) {
    const catalog = new Map((this.top?.liveCatalog || []).map((m) => [String(m.pool), m]));
    const rows = new Map();
    const add = (pool, id, state, count = 0) => {
      const entry = catalog.get(pool);
      if (!entry && state === "recent") return;
      if (!rows.has(pool)) rows.set(pool, { pool, name: String(entry?.id || pool), key: entry ? PoolBoard.key(entry) : "", clients: [], state, count: 0 });
      const row = rows.get(pool);
      if (id && !row.clients.includes(id)) row.clients.push(id);
      if (state === "live" || (state === "ended" && row.state === "recent")) row.state = state;
      row.count += count;
    };
    for (const [pool, ways] of this.flowNow(now).direct) for (const way of ways) add(pool, way.id, way.active ? "live" : "ended");
    const pinned = this.trace?.pinned ? String(this.trace.key) : "";
    const clients = ConsumerCards.of(this.top);
    const called = (pool) => {
      for (const c of clients) for (const call of c.calls || []) if (String(call.pool) === pool) add(pool, String(c.id), "recent", Number(call.count) || 0);
    };
    if (pinned.startsWith("client:")) {
      const client = clients.find((c) => `client:${c.id}` === pinned);
      for (const call of client?.calls || []) add(String(call.pool), String(client.id), "recent", Number(call.count) || 0);
    } else if (pinned.startsWith("model:")) {
      const key = pinned.slice("model:".length);
      for (const [pool, entry] of catalog) if (PoolBoard.key(entry) === key) called(pool);
    } else if (pinned.startsWith("direct:")) {
      const pool = pinned.slice("direct:".length);
      called(pool);
      add(pool, 0, "recent");
    }
    return [...rows.values()];
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
      <span class="pb-dot in" data-pb-in aria-hidden="true"></span>
      <header class="pb-pool-head">
        ${PoolBoard.gripHtml()}
        <span class="pb-pool-id" aria-hidden="true">id:</span>
        <input class="pb-pool-name" data-pb-pool-name value="${escapeHtml(String(pool.name || ""))}" aria-label="${escapeHtml(t("poolName"))}" title="${escapeHtml(t("poolName"))}" data-t="pb-pool-name">
        ${turns}${PoolBoard.kindHtml(pool.kind)}
        <button class="pb-tool" type="button" data-pb-pool-copy data-t="pb-pool-copy" title="${escapeHtml(t("poolCopy"))}" aria-label="${escapeHtml(t("poolCopy"))}">⧉</button>
        <button class="pb-tool del" type="button" data-pb-pool-delete data-t="pb-pool-delete" title="${escapeHtml(t("poolDelete"))}" aria-label="${escapeHtml(t("poolDelete"))}">✕</button>
      </header>
      <ol class="pool-ladder pb-rows">${rows}</ol>
      ${steps.length ? "" : PoolBoard.newOutHtml("new-row", "pb-add-row", t("pbAddRow"), t("pbDragRow"))}
    </article>`;
  }

  // When the pool goes on from `row` to the next one — said between the two (1.3.503): a subscription's
  // model once a window has no more left than its switch level (rust/crates/rules/src/usage_limits.rs; the
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
  // rust/crates/admin/src/topology/windows.rs annotate_pool_windows), never worked out here: a number, or that it
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

  // What a row's output is cabled to: a subscription's model with its account, a machine's model
  // with its machine (an engine's with its port too) — or what is gone, said in red rather than drawn as a cable.
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
      ${row.kind === "output" ? this.rowStateHtml(pool, row, status) : PoolBoard.statusHtml(status)}
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
    // The head says the models' queue — one for every model — and opens its two fields at the top of the column.
    const policy = this.top?.proxyPolicy;
    const head = this.head(t("topologyModelsLabel"), this.queue.buttonHtml(policy));
    const panel = this.queue.panelHtml(policy);
    const accounts = this.top?.cloudAccounts || [];
    const machines = this.machines();
    if (!accounts.length && !machines.length) return PoolBoard.column("models", head, `${panel}<p class="pb-empty" data-t="pb-no-models">${escapeHtml(t("pbNoModels"))}</p>`, { list: false });
    const uses = PoolBoard.uses(this.top?.pools || []);
    const closed = PoolBoard.closedBy(ConsumerCards.of(this.top));
    // Accounts and machines in one list, in the order the controller keeps for both (ServerOrder); while it names none of them,
    // the accounts first and the machines after, as this column has always stood.
    const cards = this.sources.sorted([
      ...accounts.map((a) => ({ key: ServerOrder.key("cloud", a.id), html: () => this.accountHtml(a, uses, closed) })),
      ...machines.map((g) => ({ key: ServerOrder.key("node", g.key), html: () => this.machineHtml(g, uses, closed) })),
    ], (card) => card.key);
    return PoolBoard.column("models", head, panel + cards.map((card) => PoolBoard.seat(card.key, card.html())).join(""));
  }

  // Who is blocked for what (ClientDeny): a refusal's key → the names of the clients whose refusal it is, in the clients' order. The
  // models and their sources say it on themselves (the owner, 2026-10-27, of the mockups: "blocked for: SpiderMonkey"), where the
  // marks of the built-in clients stood until 1.3.675: every client sees every model now, and a mark for each would say nothing.
  static closedBy(clients) {
    const map = new Map();
    for (const c of clients || []) {
      for (const key of Array.isArray(c.deny) ? c.deny : []) {
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(String(c.label || ""));
      }
    }
    return map;
  }

  // A model's board key (PoolBoard.key) → the key a refusal names it by: a machine's model by its output, an account's as it is.
  static denyKey(key) {
    const k = String(key || "");
    return k.startsWith("out:") ? `model:${k.slice(4)}` : k.startsWith("acc:") ? `model:${k}` : "";
  }

  // "⊘ SpiderMonkey, hermes" on a model or a source blocked for those clients; nothing when none is blocked for it.
  static closedHtml(names) {
    if (!names?.length) return "";
    const said = names.join(", ");
    return `<span class="pb-chip pb-closed" data-t="pb-model-closed" title="${escapeHtml(t("pbClosedTitle", { names: said }))}">⊘ ${escapeHtml(said)}</span>`;
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
  accountHtml(account, uses, closed = new Map()) {
    const id = escapeHtml(account.id);
    const subscription = PoolCards.subscription(account);
    // A test alias reads its original's limits and catalogue (CloudSources.quota_owner).
    const owner = String(account.testAliasOf || account.id);
    const shown = this.shownOf(account);
    const reads = subscription && !!account.hasCredential;
    if (reads) this.readUsage(owner);
    const rows = shown.map((model) => this.accountModelHtml(account, model, uses, closed)).join("");
    // None added: said, with the way to add one, rather than a card that reads as "no models".
    const none = shown.length ? "" : `<p class="pb-src-empty" data-t="pb-models-none">${escapeHtml(t("pbModelsNone"))}</p>`;
    const picking = this.picking?.accountId === account.id;
    const name = escapeHtml(String(account.name || account.id));
    const word = t(account.hasCredential ? "cloudConnected" : (subscription ? "poolLoginNeeded" : "cloudNoKeyYet"));
    return `<article class="pb-card pb-src${shown.length ? "" : " empty"}" data-pb-account="${id}" data-t="pb-account" data-t-id="${id}">
      <div class="pb-src-head">${PoolBoard.gripHtml()}<b title="${name}">${name}</b>${PoolBoard.closedHtml(closed.get(`account:${account.id}`))}${picking ? "" : this.addModelHtml(account)}
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

  // The name a client calls a model by, as the entry says it (`liveCatalog`, rust/crates/rules/src/entry_models.rs), by the model's key:
  // a model two accounts offer is called with its account after it — `gpt-6-luna (chatgpt-subscription)` — so the model's own id names
  // neither of them. The board's reader is saved and drawn by this name, because it is the name the rule reads (`EntryModels::wired`);
  // a reader cable that sent the bare id was refused as a name the caravan does not know on the live board (2026-11-07). "" for a model
  // no client can call: the entry offers it under no name.
  entryNameOf(key) {
    const entry = (this.top?.liveCatalog || []).find((m) => PoolBoard.key(m) === key);
    return entry ? String(entry.id) : "";
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
  accountModelHtml(account, model, uses, closed = new Map()) {
    const key = PoolBoard.key({ accountId: account.id, model });
    const step = this.stepOf(account.id, model);
    const unlisted = step.unlisted ? `<span class="pool-step-unlisted" title="${escapeHtml(t("cloudModelUnlisted"))}">⚠</span>` : "";
    // ✕ takes the model off the card while no row names it; a model in a pool keeps its place.
    const free = !uses.get(key)?.length;
    const remove = free ? `<button class="pb-tool del pb-model-remove" type="button" data-pb-model-remove data-t="pb-model-remove"`
      + ` title="${escapeHtml(t("pbModelRemove", { model }))}" aria-label="${escapeHtml(t("pbModelRemove", { model }))}">✕</button>` : "";
    const marks = PoolBoard.workChipHtml(this.workOf(account.id, model)) + PoolBoard.switchChipHtml(this.levelsOf(account.id, model))
      + PoolBoard.levelTagHtml(step) + this.schedule.chipHtml(key, model) + PoolBoard.closedHtml(closed.get(PoolBoard.denyKey(key)))
      + (free ? PoolBoard.unusedHtml() : "") + remove;
    return `<div class="pb-model" data-pb-model data-pb-key="${escapeHtml(key)}" data-pb-node="model:${escapeHtml(key)}" data-account="${escapeHtml(account.id)}" data-model="${escapeHtml(model)}" data-name="${escapeHtml(model)}" data-entry-name="${escapeHtml(this.entryNameOf(key))}" data-t="pb-model" data-t-id="${escapeHtml(key)}">
      ${PoolBoard.pullHtml("model")}
      <span class="pb-model-head">${PoolBoard.modelGrabHtml()}<span class="pb-model-name" title="${escapeHtml(model)}"><code>${escapeHtml(model)}</code>${unlisted}</span><span class="pb-chips">${marks}</span></span>
    </div>`;
  }

  // What a key's model does, on its card (`workOf`): its jobs' marks, the words in the hover — or "?" while nobody said it,
  // for then its pools promise their clients nothing of their work, and the card says so rather than look like one that
  // does. A model whose type fixes its work, or a controller that says nothing of it, — nothing.
  static workChipHtml(work) {
    if (!work) return "";
    const jobs = work.said.filter((job) => JOB_MARKS[job]);
    if (!jobs.length) {
      return `<span class="pb-chip pb-work unsaid" data-t="pb-model-work" data-t-state="unsaid" title="${escapeHtml(t("pbWorkUnsaidHint"))}">?</span>`;
    }
    return `<span class="pb-chip pb-work" data-t="pb-model-work" data-t-state="said" title="${escapeHtml(jobs.map((job) => t(JOB_LABELS[job])).join(", "))}">`
      + `${escapeHtml(jobs.map((job) => JOB_MARKS[job]).join(""))}</span>`;
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

  // A machine's card: a monitor, its name, and at the right how many of its models are in each state; a row for each one in
  // sight, the stopped ones no pool uses folded under one line. The machine's address stands in the name's hover.
  machineHtml(group, uses, closed = new Map()) {
    const cells = this.cells();
    const key = `m:${group.key}`;
    const expanded = this.expanded.has(key);
    const fold = PoolBoard.foldCells(group.outs, (o) => cells.state(o), (o) => uses.has(PoolBoard.key({ output: o.id })), expanded);
    const rows = fold.shown.map((out) => this.cellHtml(out, cells, uses, closed)).join("");
    const more = fold.quiet.length
      ? `<button class="pb-more" type="button" data-pb-more="${escapeHtml(key)}" aria-expanded="false">${escapeHtml(t("pbMoreModels", { n: String(fold.quiet.length) }))}</button>`
      : expanded && fold.folded ? `<button class="pb-more" type="button" data-pb-more="${escapeHtml(key)}" aria-expanded="true">${escapeHtml(t("pbFewer"))}</button>` : "";
    const name = escapeHtml(String(group.name ?? ""));
    const where = group.address && group.address !== group.name ? ` title="${escapeHtml(String(group.address))}"` : "";
    // A mark of two signs ("🎧🌐": hearing and translating) is wider than the slot before the names: the card gives every row the wider one.
    const wide = fold.shown.some((out) => cells.jobs(out).some((job) => Array.from(JOB_MARKS[job] || "").length > 1));
    return `<article class="pb-card pb-src${wide ? " wide-marks" : ""}" data-pb-machine="${escapeHtml(String(group.key))}" data-t="pb-machine" data-t-id="${escapeHtml(String(group.key))}">
      <div class="pb-src-head">${PoolBoard.gripHtml()}<span class="pb-src-icon" aria-hidden="true">${PoolBoard.MONITOR}</span><b${where}>${name}</b>${PoolBoard.closedHtml(PoolBoard.hostsOf(group).flatMap((host) => closed.get(`host:${host}`) || []))}<span class="pb-src-note" data-t="pb-machine-cells">${escapeHtml(PoolBoard.cellsSummary(group.outs.map((o) => cells.state(o))))}</span></div>
      ${rows}${more}
    </article>`;
  }

  // The machines a card's outputs say they stand on (`hostId`, the key a refusal of a machine names): one, as a rule.
  static hostsOf(group) {
    return [...new Set((group?.outs || []).map((o) => String(o.hostId || "")).filter(Boolean))];
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
  static PULL = { model: ["pb-pull-model", "pbPullModel"] };

  static pullHtml(of) {
    const [hook, hint] = PoolBoard.PULL[of];
    return `<span class="pb-dot in" data-pb-in data-t="${hook}" title="${escapeHtml(t(hint))}"></span>`;
  }

  static modelGrabHtml() {
    return `<span class="pb-model-grab" data-pb-out="model" data-t="pb-model-grab" title="${escapeHtml(t("pbModelGrab"))}" aria-label="${escapeHtml(t("pbModelGrab"))}">⠿</span>`;
  }

  // A local model's row: what it does (a mark, grey), its name, an engine's port, and at the right what is news — its schedule,
  // that no pool uses it, its state in a word when it is not running or stopped — and the lamp: lit while it serves, a ring while
  // it does not run, amber on the way up or down, red when it failed (`LEDS`). A stopped model says it by the ring alone; the
  // lamp's hover says it in words.
  cellHtml(out, cells, uses, closed = new Map()) {
    const key = PoolBoard.key({ output: out.id });
    const state = cells.state(out);
    const led = PoolBoard.LEDS[state] ?? "off";
    const said = escapeHtml(t(PoolBoard.cellStateWord(state)));
    const word = state !== "running" && state !== "stopped" ? `<span class="pb-cell-state">${said}</span>` : "";
    const name = escapeHtml(cells.name(out));
    // No port names a model of a machine's entry or a cell (enginePort); an engine's model keeps its engine's.
    const enginePort = PoolBoard.enginePort(out);
    const port = enginePort ? `<span class="pb-cell-port">:${enginePort}</span>` : "";
    // A model of a machine's entry says how many cells serve it, when more than one (its copies, 1.3.506).
    const copies = cells.copies(out) > 1
      ? `<span class="pb-copies" title="${escapeHtml(t("pbCopiesTitle", { n: String(cells.copies(out)) }))}">×${cells.copies(out)}</span>` : "";
    // What the model does: the first job's mark in the slot before the name, every job in its hover. A model whose job cannot be
    // named has an empty slot, so the names stand in one line.
    const jobs = cells.jobs(out).filter((job) => JOB_MARKS[job]);
    const mark = `<span class="pb-model-mark" aria-hidden="true"${jobs.length ? ` title="${escapeHtml(jobs.map((job) => t(JOB_LABELS[job])).join(", "))}"` : ""}>${jobs.length ? escapeHtml(JOB_MARKS[jobs[0]]) : ""}</span>`;
    const lamp = `<span class="pb-led${led ? ` ${led}` : ""}" role="img" title="${said}" aria-label="${said}"></span>`;
    return `<div class="pb-model machine" data-pb-model data-pb-key="${escapeHtml(key)}" data-pb-node="model:${escapeHtml(key)}" data-output="${escapeHtml(String(out.id))}" data-name="${name}" data-entry-name="${escapeHtml(this.entryNameOf(key))}" data-t="pb-model" data-t-id="${escapeHtml(key)}" data-t-state="${escapeHtml(state)}">
      ${PoolBoard.pullHtml("model")}
      <span class="pb-model-head">${PoolBoard.modelGrabHtml()}${mark}<span class="pb-model-name" title="${name}">${name}</span>${copies}${port}<span class="pb-chips">${this.schedule.chipHtml(key, PoolBoard.outLabel(out, cells))}${PoolBoard.closedHtml(closed.get(PoolBoard.denyKey(key)))}${uses.get(key)?.length ? "" : PoolBoard.unusedHtml()}${word}${this.queueChipHtml(key)}${lamp}</span></span>
    </div>`;
  }

  // ── the cables ──────────────────────────────────────────────────────

  // The cables a request runs through now, or ran through a moment ago, read from the monitor's rows (pool-flow.js).
  flowNow(now = this.now()) {
    return PoolFlow.of({ pools: this.top?.pools }, this.agents(), now);
  }

  // The drops on the cables follow the monitor, which is read a few times a second: a reading that would light the same
  // cables as the last drawing did costs nothing, and one that changes them draws the cables anew.
  paintFlow() {
    if (!this.root || !this.top || this.flowNow().signature === this.flowDrawn) return false;
    this.drawCables();
    return true;
  }

  // ── the models' queues (model-queue.js) ─────────────────────────────

  // Each model's queue now, from the monitor's rows of requests: who holds its slots, who waits and until when.
  queues(now = this.now()) {
    return ModelQueue.of(this.agents(), (item) => this.queueKey(item), (group) => (this.slots() || {})[group], now);
  }

  // The local model a request is on now, by its key on the board: a pool's row names it — the row it is on now, a request that went
  // on is the next row's — and a request routed straight to a model names the model's output. "" — no local model the board draws:
  // a subscription's row has no queue of the caravan's.
  queueKey(item) {
    const pool = (this.top?.pools || []).find((p) => String(p.id) === String(item?.cloudPoolId || ""));
    const row = (pool?.steps || []).find((s) => String(s.id) === String(item?.poolStepId ?? ""));
    if (row) return row.kind === "output" ? PoolBoard.key(row) || "" : "";
    return pool || !item?.routedOutputId ? "" : PoolBoard.key({ output: String(item.routedOutputId) });
  }

  // A local model's line: "1 of 1", "1 of 1 · 2 wait" — the mark is there while the model serves none and none waits, empty and hidden,
  // so the monitor's next reading fills it in place (paintQueue).
  queueChipHtml(key, queues = this.queues()) {
    const chip = queues.get(key)?.chip() || null;
    return `<span class="pb-queue-chip${chip?.waiting ? " waiting" : ""}" data-pb-queue-chip="${escapeHtml(key)}" data-t="pb-queue-chip"`
      + `${chip ? ` title="${escapeHtml(chip.title)}"` : " hidden"}>${chip ? escapeHtml(chip.text) : ""}</span>`;
  }

  // A pool's row of a local model: its state, and while a request of this pool waits on it, how long until it leaves — said over the state.
  rowStateHtml(pool, row, status, queues = this.queues()) {
    const words = queues.get(PoolBoard.key(row))?.rowWait(pool.id, row.id) || "";
    return `<span class="pb-state${words ? " waiting" : ""}" data-pb-row-wait="${escapeHtml(`${pool.id}/${row.id}`)}">${PoolBoard.statusHtml(status)}`
      + `<span class="pb-wait" data-t="pb-row-wait">${escapeHtml(words)}</span></span>`;
  }

  // The queue of a model in its strip; a model whose queue is empty says that too (ModelQueue with nobody in it). Its slots are the
  // proxy's count for the model's queue, found by the name the controller gives its output (`slotGroup`) while no request names it.
  queueLiveHtml(key, queues = this.queues()) {
    const queue = queues.get(key) || new ModelQueue(key, this.now());
    if (queue.slots === null) queue.slots = this.slotsOf(key);
    return queue.html((request) => this.rowOf(request), (id) => this.poolName(id));
  }

  // The name a pool is shown by — its id while it has none, as everywhere on the board. A model a client calls straight is a pool
  // of one row the cloud file does not keep (rust/crates/rules/src/entry_models.rs, LiveModels): it is named as the clients name the
  // model, from `liveCatalog` — its id (`live:mm:3a5…`) stood beside the client in a model's queue (2026-10-27).
  poolName(id) {
    const pool = (this.top?.pools || []).find((p) => String(p.id) === String(id));
    if (pool) return String(pool.name || id);
    const live = (this.top?.liveCatalog || []).find((m) => String(m.pool) === String(id));
    return String(live?.id || id);
  }

  // The slots of a model's queue as the proxy counted them (`slotTotals`, by the output's `slotGroup`), or null: nobody said.
  slotsOf(key) {
    const group = String(key).startsWith("out:") ? this.output(String(key).slice(4))?.out?.slotGroup : "";
    const said = group ? Number((this.slots() || {})[group]) : 0;
    return said > 0 ? said : null;
  }

  // The number of the row a request that goes on would go to: the next row of its pool the proxy said was ready — or null, and the
  // strip says "on" without a number.
  rowOf(request) {
    const pool = (this.top?.pools || []).find((p) => String(p.id) === request.pool);
    const steps = pool?.steps || [];
    const from = steps.findIndex((s) => String(s.id) === request.row);
    const words = this.runtime().pools?.[request.pool]?.steps || [];
    const next = steps.findIndex((s, i) => i > from && words.some((w) => w.stepId === s.id && w.reason === "ready"));
    return from >= 0 && next >= 0 ? next + 1 : null;
  }

  // The monitor read: each model's line, each waiting row and the strip's queue drawn anew in place — what would read the same is
  // not touched, so nothing flickers and a field typed in the strip keeps its focus.
  paintQueue() {
    if (!this.root?.querySelectorAll || !this.top) return 0;
    const queues = this.queues();
    let painted = 0;
    const put = (el, mark, html, apply) => {
      if (this.queueDrawn.get(mark) === html && el.dataset.pbQueueDrawn === "1") return;
      this.queueDrawn.set(mark, html);
      el.dataset.pbQueueDrawn = "1";
      apply();
      painted += 1;
    };
    for (const el of this.root.querySelectorAll("[data-pb-queue-chip]")) {
      const key = el.dataset.pbQueueChip;
      const chip = queues.get(key)?.chip() || null;
      put(el, `chip:${key}`, JSON.stringify(chip), () => {
        el.textContent = chip ? chip.text : "";
        el.hidden = !chip;
        el.classList.toggle("waiting", !!chip?.waiting);
        if (chip) el.setAttribute("title", chip.title); else el.removeAttribute("title");
      });
    }
    for (const el of this.root.querySelectorAll("[data-pb-row-wait]")) {
      const [poolId, rowId] = String(el.dataset.pbRowWait).split("/");
      const row = (this.top.pools || []).find((p) => String(p.id) === poolId)?.steps?.find((s) => String(s.id) === rowId);
      const words = row ? queues.get(PoolBoard.key(row))?.rowWait(poolId, rowId) || "" : "";
      put(el, `row:${poolId}/${rowId}`, words, () => {
        el.classList.toggle("waiting", !!words);
        const wait = el.querySelector?.("[data-t=\"pb-row-wait\"]");
        if (wait) wait.textContent = words;
      });
    }
    for (const el of this.root.querySelectorAll("[data-pb-queue-live]")) {
      const key = el.dataset.pbQueueLive;
      const html = this.queueLiveHtml(key, queues);
      put(el, `live:${key}`, html, () => { el.innerHTML = html; });
    }
    return painted;
  }

  // A field of the queue let go: saved as the proxy's policy; the board then reads the policy the controller keeps.
  async saveQueue(field) {
    const reply = await this.queue.save(field, this.top?.proxyPolicy);
    if (reply?.config?.policy) this.applied({ ...this.top, proxyPolicy: reply.config.policy });
    return reply;
  }

  // The one name for the cloud providers let go: saved as the proxy's policy, and the board reads what the controller keeps.
  async saveClientName(field) {
    const reply = await this.clientName.save(field, this.top?.proxyPolicy);
    if (reply?.config?.policy) this.applied({ ...this.top, proxyPolicy: reply.config.policy });
    return reply;
  }

  // The cables the board shows (the owner, 2026-10-27: "the cables only when we draw them, OR when a block is selected, OR when
  // requests run"): the pinned card's path (`path`) and every cable a request runs through now or ran through a moment ago
  // (pool-flow.js) — each from its output's dot to its input's dot, measured where both stand now. None at rest: what a client
  // may call is said on its card, and a cable for each would be every client to every pool. The reader block is the one cable
  // drawn at rest, because a wiring is what the operator named and not a path a request has run through: a reader with a name
  // has a cable even when nothing has been read yet. «Напрямую» is drawn first: its rows
  // are where some of them end. One that cannot be placed is named in `drops` with what is missing — never left out without a
  // word. One that carries a request now has its drops (cable-flow.js) and rings its two dots; one that did a moment ago is lit.
  drawCables() {
    const cols = this.root?.querySelector?.("[data-pb-cols]");
    const svg = cols?.querySelector("[data-pb-cables]");
    this.drops = [];
    // With no layer to draw on, the path is still lit and the strip still follows it.
    if (!cols || !svg || !this.top) { this.lightPath(); return 0; }
    this.paintDirect();
    const now = this.now();
    const flow = this.flowNow(now);
    const path = this.trace?.pinned ? PoolBoard.path(this.top, this.trace.key) : null;
    const ringed = new Set();
    CableFlow.round();    // the drops of a cable this drawing does not carry go down, not off (cable-flow.js)
    const origin = cols.getBoundingClientRect();
    const at = (el) => {
      const r = el.getBoundingClientRect();
      return { x: r.left + r.width / 2 - origin.left, y: r.top + r.height / 2 - origin.top };
    };
    const parts = [];
    for (const key of new Set([...(path?.cables || []), ...flow.active, ...flow.recent, ...ReaderBlock.wiredKeys(this.top?.reader)])) {
      const cable = this.cableOf(key);
      if (!cable) continue;
      const from = cols.querySelector(cable.from), to = cols.querySelector(cable.to);
      if (!from || !to) { if (!cable.quiet) this.drops.push({ what: key, from: !!from, to: !!to }); continue; }
      if (flow.active.has(key)) { ringed.add(from); ringed.add(to); }
      parts.push(PoolBoard.cableHtml(at(from), at(to), cable.attrs, cable.lit, cable.title, PoolBoard.flowOf(flow, key), now, key, cable.cuts));
    }
    svg.innerHTML = parts.join("") + CableFlow.ghosts(now);
    this.ring(ringed);
    this.flowDrawn = flow.signature;
    this.lightPath();
    return parts.length;
  }

  // Where a cable runs, by its key (the keys PoolFlow lights and `path` lists): the dot it leaves and the dot it enters, as the
  // columns find them, what the drawing marks it with, its hint, whether it is lit as the row that serves now, and whether a click
  // cuts it — only a pool's row is cabled by hand; a client calls what it names. Null for a key that names no cable of the
  // board. `quiet` — an end known to be missing and said in its own place: a row whose model is gone says so on itself
  // (targetHtml); a client the board no longer has has no card here.
  cableOf(key) {
    const esc = (v) => (globalThis.CSS?.escape ? globalThis.CSS.escape(String(v)) : String(v));
    const [kind, ...rest] = String(key || "").split(":");
    const id = rest.join(":");
    if (kind === "client") {
      const who = id.slice(0, id.indexOf("/")), pool = id.slice(id.indexOf("/") + 1);
      const client = ConsumerCards.of(this.top).find((c) => String(c.id) === who);
      const straight = !(this.top?.pools || []).some((p) => String(p.id) === pool);
      return { from: `[data-pb-node="client:${esc(who)}"] [data-pb-anchor]`,
        to: straight ? `[data-pb-direct="${esc(pool)}"] [data-pb-direct-in]` : `[data-pb-pool="${esc(pool)}"] > [data-pb-in]`,
        attrs: `data-pb-cable="call" data-pb-client-id="${escapeHtml(who)}" data-pb-cable-key="${escapeHtml(key)}"`,
        title: `${client ? String(client.label || "") : "?"} → ${this.poolName(pool)}`, lit: false, cuts: false, quiet: !client };
    }
    if (kind === "direct") {
      const entry = (this.top?.liveCatalog || []).find((m) => String(m.pool) === id);
      const target = PoolBoard.key(entry);
      return { from: `[data-pb-direct="${esc(id)}"] [data-pb-direct-out]`, to: `[data-pb-key="${esc(target)}"] [data-pb-in]`,
        attrs: `data-pb-cable="direct" data-pb-cable-key="${escapeHtml(key)}"`, title: `${t("pbDirect")} → ${this.poolName(id)}`,
        lit: false, cuts: false, quiet: !target };
    }
    if (kind === ReaderBlock.PREFIX) {
      // The board names one reader, so this cable has no pool in its key: it goes from the row to the model card the name
      // resolves to. Nothing named: no cable, and that is said as the absence it is — a line to nowhere would draw the
      // operator's absence as a path. `quiet` because the row names the reader on itself: a drop here would be the same fact
      // twice.
      const name = this.top?.reader?.name || "";
      if (!name) return null;
      // The name is the entry's (`entryNameOf`): two accounts' rows of one model share their id, never their entry name.
      return { from: `[data-t="${ReaderBlock.HOOKS.row}"] [data-pb-out]`, to: `[data-pb-model][data-entry-name="${esc(name)}"] [data-pb-in]`,
        attrs: `data-pb-cable="${ReaderBlock.PREFIX}" data-pb-cable-key="${escapeHtml(key)}"`,
        title: `${t("pbReaderHead")} → ${name}`, lit: false, cuts: true, quiet: true };
    }
    if (kind !== "row") return null;
    const [poolId, rowId] = id.split("/");
    const pool = (this.top?.pools || []).find((p) => String(p.id) === poolId);
    const row = (pool?.steps || []).find((r) => String(r.id) === rowId);
    const target = PoolBoard.key(row);
    if (!target) return null;
    const runtime = this.runtime();
    const serving = runtime.available ? runtime.pools?.[pool.id]?.selectedStepId : null;
    return { from: `[data-pb-pool="${esc(pool.id)}"] [data-pb-row="${esc(row.id)}"] [data-pb-out]`, to: `[data-pb-key="${esc(target)}"] [data-pb-in]`,
      attrs: `data-pb-cable="row" data-pool="${escapeHtml(pool.id)}" data-row="${escapeHtml(row.id)}" data-pb-cable-key="${escapeHtml(key)}"`,
      title: `${pool.name || pool.id} → ${this.rowName(row)}`, lit: serving === row.id, cuts: true, quiet: !this.targetKnown(row) };
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

  // The path through a card (the owner, 2026-10-12: "it is hard to see where the cables go"): from the card up to the clients that
  // reach it and down to the models it reaches — never sideways, so a model two pools share lights its own way up, not the other
  // pool's clients. Since 1.3.675 a client reaches what it called over three days (`calls`, the journal's): a pool, or a model
  // straight through its row of «Напрямую» — every pool and model is open to it, and a path to each would light the whole board.
  // Node keys are the cards' `data-pb-node`: client:<client id>, pool:<id>, row:<pool>/<row>, direct:<pool of one row>, model:<key>;
  // cable keys are the ones cableOf reads: client:<client id>/<pool>, row:<pool>/<row>, direct:<pool of one row>.
  static path(top, key) {
    const nodes = new Set(), cables = new Set();
    const clients = ConsumerCards.of(top);
    const pools = new Map((top?.pools || []).map((p) => [String(p.id), p]));
    const catalog = new Map((top?.liveCatalog || []).map((m) => [String(m.pool), m]));
    const callers = (pool) => clients.filter((c) => (c.calls || []).some((call) => String(call.pool) === pool));
    const [kind, ...rest] = String(key || "").split(":");
    const id = rest.join(":");
    const up = (node) => {
      if (nodes.has(node) && node !== key) return;
      nodes.add(node);
      const [k, ...r] = node.split(":");
      const v = r.join(":");
      if (k === "pool" || k === "direct") {
        for (const c of callers(v)) { nodes.add(`client:${c.id}`); cables.add(`client:${c.id}/${v}`); }
      } else if (k === "row") {
        up(`pool:${v.split("/")[0]}`);
      } else if (k === "model") {
        for (const [pid, pool] of pools) {
          for (const row of pool.steps || []) {
            if (PoolBoard.key(row) === v) { cables.add(`row:${pid}/${row.id}`); up(`row:${pid}/${row.id}`); }
          }
        }
        for (const [pool, entry] of catalog) {
          if (PoolBoard.key(entry) === v && callers(pool).length) { cables.add(`direct:${pool}`); up(`direct:${pool}`); }
        }
      }
    };
    const down = (node) => {
      nodes.add(node);
      const [k, ...r] = node.split(":");
      const v = r.join(":");
      if (k === "client") {
        const client = clients.find((c) => String(c.id) === v);
        for (const call of client?.calls || []) {
          const pool = String(call.pool);
          if (pools.has(pool)) { cables.add(`client:${v}/${pool}`); down(`pool:${pool}`); }
          else if (catalog.has(pool)) { cables.add(`client:${v}/${pool}`); down(`direct:${pool}`); }
        }
      } else if (k === "pool") {
        for (const row of pools.get(v)?.steps || []) down(`row:${v}/${row.id}`);
      } else if (k === "row") {
        const [pid, rid] = v.split("/");
        const row = (pools.get(pid)?.steps || []).find((x) => x.id === rid);
        const target = PoolBoard.key(row);
        if (target) { cables.add(`row:${v}`); nodes.add(`model:${target}`); }
      } else if (k === "direct") {
        const target = PoolBoard.key(catalog.get(v));
        if (target) { cables.add(`direct:${v}`); nodes.add(`model:${target}`); }
      }
    };
    if (!kind || !id) return { nodes, cables };
    up(key);
    down(key);
    return { nodes, cables };
  }

  // The lit path laid on the drawn board: its cards and cables marked (`tracing`, `on-path`). Pinned by a
  // click (`traced`), it stays until Esc or a click on it again, and only then does the rest step back —
  // the stylesheet's rule (pool-board.css; the owner, 2026-10-27: "do not make the other blocks transparent
  // when I only point at a block"); else it follows the pointer and lights, taking nothing away. A pinned path shows
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
      const c = ConsumerCards.of(this.top).find((x) => String(x.id) === id);
      return c ? { name: String(c.label || ""), subHtml: `<span class="pb-key">🔑 …${escapeHtml(String(c.keyTail || ""))}</span>` } : null;
    }
    if (kind === "direct") {
      const entry = this.liveEntry(id);
      const where = entry ? this.targetOf(PoolBoard.key(entry))?.where || "" : "";
      return entry ? { name: String(entry.id), subHtml: escapeHtml([t("pbDirect"), where].filter(Boolean).join(" · ")) } : null;
    }
    if (kind === "pool") {
      const pool = (this.top?.pools || []).find((x) => String(x.id) === id);
      return pool ? { name: String(pool.name || pool.id), subHtml: PoolBoard.kindHtml(pool.kind) } : null;
    }
    const target = this.targetOf(id);
    return target ? { name: target.name, subHtml: escapeHtml(target.where) } : null;
  }

  // A model called straight, by the id of its pool of one row (`live:…`): what `liveCatalog` says of it, or null.
  liveEntry(pool) {
    return (this.top?.liveCatalog || []).find((m) => String(m.pool) === String(pool)) || null;
  }

  // A model's key (PoolBoard.key) as the strip says it: its name, and where it stands — its account, or
  // its machine (PoolBoard.where). A key the board does not know is not a model of it.
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

  // The route of a card, by column: the clients that reach it, its pools, its models — the lit path (path) said in names, in the
  // order of the board. A model two accounts offer is told by its account.
  routeOf(key) {
    const { nodes } = PoolBoard.path(this.top, key);
    const ids = (prefix) => [...nodes].filter((n) => n.startsWith(prefix)).map((n) => n.slice(prefix.length));
    const clientIds = new Set(ids("client:")), pools = new Set(ids("pool:"));
    const targets = ids("model:").map((k) => this.targetOf(k)).filter(Boolean);
    const models = targets.map((x) => (targets.filter((y) => y.name === x.name).length > 1 ? `${x.name} · ${x.where}` : x.name)).sort();
    return [
      { label: t("topologyClientsSection"), names: ConsumerCards.of(this.top).filter((c) => clientIds.has(String(c.id))).map((c) => String(c.label || "")) },
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
      return `<div class="pb-dock-levels" data-t="pb-dock-levels">${bars || `<p class="pb-dock-note">${escapeHtml(note)}</p>`}</div>`
        + PoolBoard.workFieldHtml(account.id, rest.join("/"), this.workOf(accountId, rest.join("/")));
    }
    if (key.startsWith("out:")) {
      const found = this.output(key.slice(4));
      if (!found) return "";
      const state = PoolBoard.cellState(this.cells().state(found.out));
      const led = PoolBoard.LEDS[state] ?? "off";
      // The model's state stands over its queue, in the same column: the settings beside them begin at the strip's top, where
      // they have the room their words and legend need (1.3.665).
      return `<div class="pb-queue-wrap"><div class="pb-queue-main">`
        + `<div class="pb-dock-cell" data-t="pb-dock-cell" data-t-state="${escapeHtml(state)}"><span class="pb-led${led ? ` ${led}` : ""}" aria-hidden="true"></span>`
        + `${escapeHtml(t(PoolBoard.cellStateWord(state)))}</div>`
        + `<div class="pb-queue-live" data-pb-queue-live="${escapeHtml(key)}">${this.queueLiveHtml(key)}</div></div>`
        + `${this.queue.sideHtml(this.top?.proxyPolicy)}</div>`;
    }
    return "";
  }

  // "What it does" of a key's model in the strip (`workOf`): one of the jobs the controller offers, or "not said". Several
  // jobs kept (a file written by hand, the API) are said as they are, not as the first of them; choosing one replaces them.
  static workFieldHtml(accountId, model, work) {
    if (!work) return "";
    const word = (job) => `${JOB_MARKS[job] || ""} ${t(JOB_LABELS[job] || job)}`.trim();
    const several = work.said.length > 1;
    const chosen = several ? null : (work.said[0] || "");
    const kept = several ? `<option value="" selected disabled>${escapeHtml(work.said.map(word).join(", "))}</option>` : "";
    const options = [["", t("pbWorkUnsaid")], ...work.offered.map((job) => [job, word(job)])]
      .map(([value, text]) => `<option value="${escapeHtml(value)}"${value === chosen ? " selected" : ""}>${escapeHtml(text)}</option>`).join("");
    return `<label class="pb-dock-work" data-t="pb-dock-work" data-t-state="${work.said.length ? "said" : "unsaid"}"><span>${escapeHtml(t("pbWork"))}</span>`
      + `<select class="pb-work-field" data-pb-work data-pb-work-account="${escapeHtml(accountId)}" data-pb-work-model="${escapeHtml(model)}"`
      + ` title="${escapeHtml(t("pbWorkHint"))}">${kept}${options}</select></label>`;
  }

  // The details of the card in the strip. A client's links, tests and errors stand here, in one wrapper
  // that carries its id: the handlers find the client by it, as they did on its card (`display:
  // contents` — the wrapper has no box, the parts flow in the strip's columns).
  dockDetailsHtml({ kind, id }) {
    if (kind === "model") return this.modelDetailsHtml(id);
    if (kind === "pool") {
      const pool = (this.top?.pools || []).find((x) => String(x.id) === id);
      return pool ? this.poolDetailsHtml(pool) : "";
    }
    if (kind === "direct") {
      const entry = this.liveEntry(id);
      return entry ? this.modelDetailsHtml(PoolBoard.key(entry)) : "";
    }
    if (kind !== "client") return "";
    const c = ConsumerCards.of(this.top).find((x) => String(x.id) === id);
    if (!c) return "";
    return `<div class="pb-dock-client" data-pb-client="${escapeHtml(String(c.id))}" data-t="pb-dock-client">${this.asksHtml(c)}${this.probesHtml(c)}${this.missesHtml(c)}</div>`;
  }

  // The pointer over a card: its path, unless one is pinned or a cable, a row or a card is in the hand. The strip
  // under the pointer, when it is not pinned, is inert: the pointer is on whatever stands under it. The cards that pass under a
  // pointer that has not moved, because the board scrolled across beneath it (`bringIn`), are not pointed at: the path stays
  // on the card the person was on until the pointer moves again.
  hover(event) {
    if (this.settling) {
      if (!PoolReveal.moved(this.settling, event.clientX, event.clientY)) return;
      this.settling = null;
    }
    if (this.trace?.pinned || this.drag || this.carry?.busy || this.cardCarry?.busy) return;
    const key = event.target.closest?.("[data-pb-node]")?.dataset.pbNode || null;
    if ((this.trace?.key || null) === key) return;
    this.trace = key ? { key, pinned: false } : null;
    this.lightPath();
    this.scheduleReveal(key);
  }

  // The pointer rests on a card: after a moment the board brings what its path leads to, beyond the edge of a column or of the
  // window, into view (the owner, 2026-10-18, pool-reveal.js). Going on to another card, or off the cards, ends the wait.
  scheduleReveal(key) {
    const set = this.win?.setTimeout?.bind(this.win) || setTimeout, clear = this.win?.clearTimeout?.bind(this.win) || clearTimeout;
    clear(this.revealTimer);
    this.revealTimer = 0;
    if (!key) return;
    const mine = set(() => { if (this.revealTimer === mine) this.revealTimer = 0; this.reveal(key); }, PoolReveal.DELAY);
    this.revealTimer = mine;
  }

  // The path of `key` followed: the box across and the columns up or down move so that the cards of the path that stood out of view
  // come into it (PoolReveal.plan). Not while the pointer has gone on to another card, or something is in the hand, or the person
  // is scrolling themselves.
  reveal(key) {
    const box = this.root?.querySelector?.("[data-pb-root]");
    if (!box || !this.top || this.trace?.key !== key || this.busy) return false;
    if (this.now() - this.userScrolled < PoolReveal.QUIET) return false;
    const input = this.revealInput(box, key);
    return input ? this.bringIn(box, PoolReveal.plan(input)) : false;
  }

  // Where the cards of a path stand now, in the screen's numbers: the card under the pointer, the other cards of its path (only
  // what counts of each), the room of every column's body, the box, the window and the strip that covers the columns' foot.
  revealInput(box, key) {
    const path = PoolBoard.path(this.top, key);
    const rect = (el) => { const r = el.getBoundingClientRect(); return { left: r.left, right: r.right ?? r.left + r.width, top: r.top, bottom: r.bottom ?? r.top + r.height }; };
    const columns = {};
    for (const body of this.root?.querySelectorAll?.("[data-pb-scroll]") || []) { const r = rect(body); columns[body.dataset.pbScroll] = { top: r.top, bottom: r.bottom }; }
    let hovered = null;
    const anchors = [];
    for (const el of this.root?.querySelectorAll?.("[data-pb-node]") || []) {
      const id = el.dataset.pbNode, column = el.closest?.("[data-pb-scroll]")?.dataset.pbScroll;
      if (!column || (id !== key && !path.nodes.has(id))) continue;
      if (id === key) hovered = { column, rect: rect(el) };
      else anchors.push({ column, rect: PoolReveal.anchor(id, rect(el)) });
    }
    if (!hovered) return null;
    const dock = this.root?.querySelector?.("[data-pb-dock]"), b = rect(box);
    return { screen: { width: Number(this.win?.innerWidth) || Infinity, height: Number(this.win?.innerHeight) || Infinity },
      box: { left: b.left, right: b.right }, floor: dock ? rect(dock).top : null, hovered, columns, anchors, side: PoolReveal.side(key) };
  }

  // The plan done, smoothly (at once for a person who asked for less motion). A move that would change nothing — the box cannot
  // scroll that way, the column stands at its end — is not made. Across, the cards move under a pointer that stands still: it
  // is told to `hover` as the place to leave from.
  bringIn(box, plan) {
    const calm = !!this.win?.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches, behavior = calm ? "auto" : "smooth";
    const go = (el, side, delta) => {
      const wide = side === "left", now = wide ? el.scrollLeft : el.scrollTop, room = wide ? el.scrollWidth - el.clientWidth : el.scrollHeight - el.clientHeight;
      const to = Math.max(0, Math.min(room, now + delta));
      if (!(Math.abs(to - now) >= 1)) return false;
      if (el.scrollTo) el.scrollTo({ [side]: to, behavior });
      else if (wide) el.scrollLeft = to;
      else el.scrollTop = to;
      return true;
    };
    let moved = false;
    if (plan.dx && go(box, "left", plan.dx)) { moved = true; this.settling = { ...this.pointer }; }
    for (const body of this.root?.querySelectorAll?.("[data-pb-scroll]") || []) {
      const dy = plan.dy[body.dataset.pbScroll];
      if (dy && go(body, "top", dy)) moved = true;
    }
    return moved;
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
    this.drawCables();
    this.scheduleReveal(null);
    if (this.trace) this.reveal(key);       // a click is meant: the path is followed at once, as it was after the pointer rested
    return true;
  }

  letGo() {
    this.trace = null;
    this.drawCables();
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

  // A cable: its wide twin the pointer finds — on a cable a click cuts, a pool's row's —, and the line. `flow` is what the
  // monitor says of it: "active" — a request runs through it, its drops run over it (cable-flow.js) —, "recent" — one did a
  // moment ago —, or "". Either one lights the line, as the row that serves does.
  static cableHtml(a, b, attrs, lit, title, flow = "", now = 0, key = "", cuts = true) {
    const d = PoolBoard.curve(a, b);
    return `<g ${attrs}><title>${escapeHtml(String(title || ""))}</title>${cuts ? `<path class="pb-cable-hit" d="${d}"></path>` : ""}`
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
        if (event.target.closest?.("[data-pb-deny-query]")) this.denyFind(event.target.value);
      });
      container.addEventListener("keydown", (event) => this.key(event));
      this.win?.addEventListener?.("keydown", (event) => this.escape(event));
      // The path under the pointer lights as it moves; it goes dark when the pointer leaves the board.
      container.addEventListener("pointerleave", () => {
        this.scheduleReveal(null);
        if (!this.trace || this.trace.pinned) return;
        this.trace = null;
        this.lightPath();
      });
      // Where the pointer is, for the board to leave from when it scrolls across under it (`bringIn`); and the person's own
      // scrolling, which the board does not fight (`reveal`). A pointer that moves is no longer a still one.
      container.addEventListener("pointermove", (event) => {
        this.pointer = { x: Number(event.clientX) || 0, y: Number(event.clientY) || 0 };
        if (this.settling && PoolReveal.moved(this.settling, event.clientX, event.clientY)) this.settling = null;
      }, { passive: true });
      for (const kind of ["wheel", "touchmove"]) container.addEventListener(kind, () => { this.userScrolled = this.now(); }, { passive: true });
      // A pool's field let go: the drawing that waited for it lands (`typing`) once the focus has
      // moved on — to another of them, and it waits on.
      container.addEventListener("focusout", (event) => {
        if (!event.target.closest?.("[data-pb-pool-name],[data-pb-pool-window],[data-ms-from],[data-ms-to],[data-pb-work],[data-pb-queue-field],[data-pb-client-name]")) return;
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
      // ...and the models' queues: the lines, the rows that wait and the strip, each in its place (model-queue.js).
      ACTIVITY_SEEN.add(() => { this.paintFlow(); this.paintQueue(); });
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

  // The board's search fields — the account's list under "＋ model", the chooser's and the window of a client's refusals: the mark a
  // field is known by, and where it is found again in the board drawn anew.
  static FINDS = [["[data-pb-pick-query]", "[data-pb-picker] [data-pb-pick-query]"],
    ["[data-pb-choose-query]", "[data-pb-chooser] [data-pb-choose-query]"], ["[data-pb-deny-query]", "[data-pb-deny] [data-pb-deny-query]"]];

  // A pool's name or its window being typed: the board's own drawing waits until the field lets
  // go (`focusout`, bound on mount). A reading that landed mid-number drew the field anew with what
  // the controller keeps, and the digits typed so far went with it. A model's "What it does" holds
  // it too: drawn anew, its list would close under the pointer. The page's drawing waits for any
  // field already (topology-render.js).
  typing() {
    return !!this.doc?.activeElement?.matches?.("[data-pb-pool-name],[data-pb-pool-window],[data-ms-from],[data-ms-to],[data-pb-work],[data-pb-queue-field],[data-pb-client-name]");
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
      + "[data-pb-row-remove],[data-pb-pool-copy],[data-pb-pool-delete],[data-pb-history],[data-pb-settings],[data-pb-copy-url],[data-pb-tests],[data-pb-probe],[data-pb-probe-close],"
      + "[data-pb-queue-open],[data-pb-client-name-open],[data-pb-deny-open],[data-pb-deny-close],[data-pb-move-delete],[data-pb-move-keep],"
      + "[data-pb-more],[data-pb-cable],[data-api-retry],"
      + "[data-pb-add-model],[data-pb-pick-model],[data-pb-pick-close],[data-pb-model-remove],"
      + "[data-pb-choose],[data-pb-choose-close],"
      + "[data-ms-open],[data-ms-close],[data-ms-save],[data-ms-add],[data-ms-remove],[data-ms-day]");
    // The window of a client's refusals closes on a click beside its box, as on "Done".
    if (!el && this.denying && event.target.matches?.("[data-pb-deny]")) return this.closeDeny();
    if (!el) return closed || this.pin(event) || null;
    event.stopPropagation?.();
    if (el.hasAttribute("data-ms-open") || el.closest("[data-ms]")) return this.schedule.click(el);
    if (el.hasAttribute("data-pb-choose")) return this.choose(el.dataset.pbChoose);
    if (el.hasAttribute("data-pb-choose-close")) return this.closeChooser();
    if (el.hasAttribute("data-pb-arrange")) return this.arrange();
    if (el.hasAttribute("data-pb-queue-open")) { this.queue.open = !this.queue.open; return this.redraw(); }
    if (el.hasAttribute("data-pb-client-name-open")) { this.clientName.open = !this.clientName.open; return this.redraw(); }
    const poolId = el.closest("[data-pb-pool]")?.dataset.pbPool || "";
    const rowId = el.closest("[data-pb-row]")?.dataset.pbRow || "";
    if (el.hasAttribute("data-api-retry")) return this.send("/api/cloud-api-health/retry", { key: el.dataset.apiRetry });
    if (el.hasAttribute("data-pb-add-pool")) return this.addPool();
    if (el.hasAttribute("data-pb-deny-open")) return this.openDeny(el.closest("[data-pb-client]")?.dataset.pbClient || "");
    if (el.hasAttribute("data-pb-deny-close")) return this.closeDeny();
    if (el.hasAttribute("data-pb-move-delete")) return this.answerMove(true);
    if (el.hasAttribute("data-pb-move-keep")) return this.answerMove(false);
    if (el.hasAttribute("data-pb-row-remove")) return this.removeRow(poolId, rowId);
    if (el.hasAttribute("data-pb-pool-copy")) return this.copyPool(poolId);
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
    const queueField = event.target.closest?.("[data-pb-queue-field]");
    if (queueField) return this.saveQueue(queueField);
    const nameField = event.target.closest?.("[data-pb-client-name]");
    if (nameField) return this.saveClientName(nameField);
    const slider = event.target.closest?.("[data-level-account]");
    if (slider) return saveSwitchLevel(slider, (top) => this.applied(top), () => this.redraw());
    const windowField = event.target.closest?.("[data-pb-pool-window],[data-pb-pool-window-auto]");
    if (windowField) return this.saveWindow(windowField);
    const deny = event.target.closest?.("[data-pb-deny-key]");
    if (deny) return this.toggleDeny(deny.dataset.pbDenyKey, !!deny.checked);
    const twin = event.target.closest?.("[data-pb-move-twin]");
    if (twin) {
      if (twin.checked) this.moveKept.delete(twin.dataset.pbMoveTwin); else this.moveKept.add(twin.dataset.pbMoveTwin);
      return this.paintMoveButton();
    }
    const work = event.target.closest?.("[data-pb-work]");
    if (work) return this.saveWork(work);
    const probeModel = event.target.closest?.("[data-pb-probe-model]");
    if (probeModel) {
      this.probeModel.set(String(probeModel.closest("[data-pb-client]")?.dataset.pbClient || ""), String(probeModel.value || ""));
      this.paintDock();
      return true;
    }
    const name = event.target.closest?.("[data-pb-pool-name]");
    if (!name) return null;
    const pool = this.actions.stored(name.closest("[data-pb-pool]")?.dataset.pbPool || "");
    const typed = String(name.value || "").trim();
    if (!pool || !typed || typed === pool.name) { if (pool) name.value = pool.name; return null; }
    try { return await this.actions.save({ ...pool, name: typed }); } catch (err) { this.notify(err.message); name.value = pool.name; return null; }
  }

  // "What it does" chosen on a key model's strip: one job, or "not said" — an empty list takes the word back. The field lets
  // go first, so the drawing that waited for it (`typing`) lands with the answer. Refused, the board is drawn with what the
  // controller keeps, and the toast says why (`send`).
  async saveWork(field) {
    const value = String(field.value || "");
    field.blur?.();
    const res = await this.send("/api/pools/model-jobs", { accountId: field.dataset.pbWorkAccount || "", model: field.dataset.pbWorkModel || "",
      jobs: value ? [value] : [] });
    if (!res) this.redraw();
    return res;
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
    return this.nameIt(await this.send("/api/pools/create", {}));
  }

  // "⧉" on a pool's head (the owner, 2026-10-29: a button that copies a pool already made): the copy stands under it.
  async copyPool(poolId) {
    return this.nameIt(await this.send("/api/pools/copy", { id: poolId }));
  }

  // A pool the board has just made takes the keyboard in its name: the name is what its clients will call it by.
  nameIt(res) {
    const id = res?.pool?.id;
    const esc = (v) => (globalThis.CSS?.escape ? globalThis.CSS.escape(String(v)) : String(v));
    const field = id ? this.root?.querySelector?.(`[data-pb-pool="${esc(id)}"] [data-pb-pool-name]`) : null;
    field?.focus?.();
    field?.select?.();
    return res;
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

  // A click on a pool's row's cable cuts it, after one question that names both of its ends. A client's cable and a cable of
  // «Напрямую» are what was called: nothing to cut (cableHtml gives them no place for a click).
  //
  // A reader cable is cut the same way, and the answer is the absence written back: the name is set to nothing, not to an
  // empty name, so the wiring reads as the absence it is (`EntryModels::reader` in rust/crates/rules/src/entry_models.rs).
  async cut(el) {
    if (el.dataset.pbCable === "row") {
      const pool = this.actions.stored(el.dataset.pool);
      const index = (pool?.steps || []).findIndex((s) => s.id === el.dataset.row);
      if (index < 0) return null;
      const sure = await this.confirm(t("pbCutRowText", { n: String(index + 1), pool: pool.name || pool.id, target: this.rowName(pool.steps[index]) }),
        { title: t("pbCutTitle"), danger: true, confirmLabel: t("pbCutTitle") });
      return sure ? this.send("/api/pools/connect-row", { poolId: pool.id, rowId: el.dataset.row, target: null }) : null;
    }
    if (el.dataset.pbCable === ReaderBlock.PREFIX) {
      const named = this.top?.reader?.name || "";
      if (!named) return null;
      const sure = await this.confirm(t("pbReaderCutText", { reader: named }),
        { title: t("pbCutTitle"), danger: true, confirmLabel: t("pbCutTitle") });
      return sure ? this.send("/api/board/reader", ReaderBlock.body(null)) : null;
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

  // What each kind of cable lands on: a pool row's on a model — and a model's on a pool, or on the Pools column for a pool of
  // its own; a model's input (1.3.587) does what its handle does. A client draws no cable since 1.3.675: it calls what it
  // names. The reader block's row lands on a model too, because a reader is a model the operator names, not a place.
  static ONTO = {
    row: ["[data-pb-model]"],
    "new-row": ["[data-pb-model]"],
    model: ["[data-pb-pool]", "[data-pb-pools-drop]"],
  };

  // What a kind lands on. The reader block's kind is read from `ReaderBlock.PREFIX` here, at the call, and not as a key of
  // the table above: a class field that reads another module at the moment the class is defined is a load-order trap — when
  // the reader block is entered first (through pool-flow.js), `ReaderBlock` is still being initialised and the key becomes an
  // error, not a hole. Said here because `landing` below is the only place the table is read.
  static onto(kind) {
    return PoolBoard.ONTO[kind] || (kind === ReaderBlock.PREFIX ? ["[data-pb-model]"] : null);
  }
  // The kinds whose cable the pointer holds by its left end: it ends at the card's input, which stays where it is.
  static REVERSE = new Set(["model"]);

  // The output an element belongs to: a dot or a model's handle itself, or the dot of the "＋" row it
  // lies in (newOutHtml) — a press and a click find it alike.
  static opener(el) {
    return el?.closest?.("[data-pb-out]") || el?.closest?.("[data-pb-grab]")?.querySelector?.("[data-pb-out]") || null;
  }

  // What an output starts: its kind and where it comes from — a pool's row (the pool alone, for its "＋"), a model with the name
  // the board shows it by, or the reader block's row, which comes from the board and not from a pool. An output of any other
  // kind starts nothing: a cable of a kind nobody lands would hang in the hand.
  static source(dot) {
    if (dot?.hasAttribute?.("data-pb-in")) return PoolBoard.pulled(dot);
    const kind = dot?.dataset?.pbOut;
    if (kind === "model") return PoolBoard.modelSource(dot.closest("[data-pb-model]"));
    if (kind === ReaderBlock.PREFIX) return { kind, from: {} };
    if (kind !== "row" && kind !== "new-row") return null;
    return { kind, from: { poolId: dot.closest("[data-pb-pool]")?.dataset.pbPool || "", rowId: dot.closest("[data-pb-row]")?.dataset.pbRow || "" } };
  }

  // A model's cable: its target — an account's model, or a local model's output — with the name the board shows it by. A card that is none starts nothing.
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

  // What an input dot starts when it is pulled: its model's cable. A pool's input is where the clients' calls come in, and
  // nothing is pulled from it since 1.3.675; a dot on no model starts nothing.
  static pulled(dot) {
    const model = dot.closest?.("[data-pb-model]");
    return model ? PoolBoard.modelSource(model) : null;
  }

  // A place of the board as `ask` takes it: a pool, a model with its name — or the Pools column, a new pool.
  static placeOf(el) {
    if (el?.hasAttribute?.("data-pb-pool")) return { pool: el.dataset.pbPool };
    if (el?.hasAttribute?.("data-pb-model")) {
      return { target: el.dataset.output ? { output: el.dataset.output } : { accountId: el.dataset.account, model: el.dataset.model },
        name: el.dataset.name || "", entry: el.dataset.entryName || "" };
    }
    if (el?.hasAttribute?.("data-pb-pools-drop")) return { newPool: true };
    return {};
  }

  // What joining an output to a place asks of the controller — one door for a cable carried there and
  // for a place picked in the chooser. The model's name goes along: a pool still called "Pool", with no
  // cable yet, takes it as its own (rust/crates/admin/src/cloud/pools.rs; the owner, 2026-10-12: "a pool of one model
  // named after the model"). A place its kind does not land on asks nothing.
  //
  // A reader cable asks the board's door with the name the entry calls the model it landed on (`entryNameOf`), and with nothing
  // else: the page does not decide whether that name may be a reader. `EntryModels::can_write` does, before the write, and the answer
  // it gives is the same answer a request gets (rust/crates/admin/src/cloud/pool_edits.rs). A page that checked the promise here would
  // be the fact read a second way, and the board could accept what the entry refuses. A model the entry offers under no name is asked
  // by its key, which is no client's name: the door refuses it in the rule's words, where the bare id could name another account's
  // model of the same id — a guess.
  static ask(kind, from, to) {
    if (kind === ReaderBlock.PREFIX && to?.target && to.name) return ["/api/board/reader", ReaderBlock.body(to.entry || PoolBoard.key(to.target))];
    if (kind === "new-row" && to?.target) return ["/api/pools/add-row", { poolId: from.poolId, target: to.target, nameAfter: to.name || "" }];
    if (kind === "row" && to?.target) {
      return ["/api/pools/connect-row", { poolId: from.poolId, rowId: from.rowId, target: to.target, nameAfter: to.name || "" }];
    }
    if (kind === "model" && to?.pool) return ["/api/pools/add-row", { poolId: to.pool, target: from.target, nameAfter: from.name || "" }];
    if (kind === "model" && to?.newPool) return ["/api/pools/create", { target: from.target, nameAfter: from.name || "" }];
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
    for (const onto of PoolBoard.onto(this.drag.kind) || []) {
      const hit = el.closest?.(onto);
      if (hit) return hit;
    }
    return null;
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
    // The reader kind is not a key of `ONTO` (see `onto`), so the class a reader drag adds has to be named here too:
    // otherwise the dashed outline stays on the models after the cable is let go.
    root?.classList.remove(...[...Object.keys(PoolBoard.ONTO), ReaderBlock.PREFIX].map((kind) => `dragging-${kind}`));
    root?.querySelector("[data-pb-live]")?.remove();
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
  static CHOOSER_TITLES = { row: "pbChooseModel", "new-row": "pbChooseModel", model: "pbChooseModelPool" };
  // An empty list says what is missing, in the column's own words.
  static CHOOSER_EMPTY = { row: "pbNoModels", "new-row": "pbNoModels" };

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

  // Where an output's cable can go: each place with the key the list knows it by, its name and its line, the place `ask` takes,
  // and whether a cable goes there now — the pool's models, the model's pools. A model is offered a pool of its own first.
  choices(kind, from) {
    const top = this.top || {};
    const pools = top.pools || [];
    const cells = this.cells();
    const line = (pool) => (pool.steps || []).map((row) => this.modelName(row, cells)).filter(Boolean).join(", ");
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

  // A row's model by the name the board shows it by: an account's model id, a local model's name.
  modelName(row, cells = this.cells()) {
    if (row?.kind === "account") return String(row.model || "");
    if (row?.kind !== "output") return "";
    const found = this.output(row.output);
    return found ? cells.name(found.out) : String(row.output);
  }

  // Every model a row can be cabled to: the models on each account's card, then each machine's — its entry's models and its
  // engines', by name (machines).
  targets(cells = this.cells()) {
    const out = [];
    for (const account of this.top?.cloudAccounts || []) {
      for (const model of this.shownOf(account)) {
        out.push({ key: PoolBoard.key({ accountId: account.id, model }), label: model, hint: `☁ ${account.name || account.id}`,
          to: { target: { accountId: account.id, model }, name: model } });
      }
    }
    for (const group of this.machines()) {
      for (const model of group.outs || []) {
        const name = cells.name(model);
        out.push({ key: PoolBoard.key({ output: model.id }), label: name, hint: PoolBoard.where(model, group),
          to: { target: { output: model.id }, name } });
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

  // Esc anywhere on the page: the window of a client's refusals closes, else the chooser, else a pinned path lets go — one at a
  // time, and none while something is carried (its own Esc gives it back) or after a field has taken the Esc. The window of the
  // move waits for its answer.
  escape(event) {
    if (event.key !== "Escape" || event.defaultPrevented || this.drag || this.carry?.busy || this.cardCarry?.busy) return null;
    if (this.denying) {
      event.preventDefault?.();
      return this.closeDeny();
    }
    if (this.chooser) {
      event.preventDefault?.();
      return this.closeChooser();
    }
    if (!this.trace?.pinned) return null;
    event.preventDefault?.();
    return this.letGo();
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

  // Where each column's order is kept: the pools' in the cloud file, the clients' and the models' cards' in the board's layout
  // (rust/crates/admin/src/board_layout.rs, ClientOrder and ServerOrder). The list of the models' cards may name what the column does not
  // show — a machine gone for now, a card the main board has — and each of those keeps its place (`merged`).
  static ORDERS = {
    pools: (ids) => ["/api/pools/order", { ids }],
    clients: (ids) => ["/api/consumers/order", { order: ids.map(String) }],
    models: (ids, board) => ["/api/topology/server-order", { order: ServerOrder.merged(board.sources.current(), ids) }],
  };

  // The order a card's carry left behind, saved; the answer draws the board. Refused — the toast says
  // why, and the board is drawn from what the controller keeps.
  async saveOrder(kind, ids) {
    const door = PoolBoard.ORDERS[kind];
    const res = door ? await this.send(...door(ids, this)) : null;
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

  // "Arrange by the cables" (the owner, 2026-10-12): the models of each account in the order the pools' rows name them — the
  // controller's (/api/pools/arrange). The cables then run alongside one another more than across.
  async arrange() {
    const res = await this.send("/api/pools/arrange", {});
    if (res) this.notify(t("pbArranged"));
    return res;
  }
}

export const POOL_BOARD = new PoolBoard();
