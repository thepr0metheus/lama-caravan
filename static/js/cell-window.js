// A cell's window over the board — variant Г of the canvas "Окно ячейки: переделка", the owner's choice of 2026-10-24
// ("делай Г в коде"): the model's passport on top, a band that says what the cell does now with its one main button, and
// the rest in tabs. It replaced the old full card inside the window: a row of seven buttons of one weight that put Delete
// beside Start, lifecycle steps that hid the settings behind "configured", and a dozen chips that read as one soup.
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";
import { CellRow } from "./card-rows.js";

/**
 * The window of one cell, drawn inside its slot with the lane and opened by a class (card-fold.js). The lane binds the
 * buttons the window carries — start, stop, autostart, delete, the port, the settings — where it binds the card's, by
 * the same data attributes (remote-cells.js bindServerSlotControls): the window only puts them where the operator looks.
 * What has to outlive a repaint of the lane — the tab chosen — is the fold state's (CardFold.windowTab), not the DOM's.
 *
 * Everything is drawn here from facts the board gathered; the window decides nothing about the cell. A part with nothing
 * to say says that, in words — a tab of a runner that cannot talk is not drawn at all.
 */
export class CellWindow {
  /** The tabs, in their order. */
  static TABS = ["overview", "memory", "settings", "log", "talk"];
  static TAB_WORDS = { overview: "cwTabOverview", memory: "cwTabMemory", settings: "cwTabSettings", log: "cwTabLog", talk: "cwTabTalk" };
  /** What each state of a cell is called on its band, and the tone the band wears: good — it works; busy — it is on its way;
   *  idle — it holds nothing; bad — it failed. */
  static STATES = {
    running: { word: "cwStateRunning", tone: "good" },
    starting: { word: "cwStateStarting", tone: "busy" },
    warming: { word: "cwStateWarming", tone: "busy" },
    downloading: { word: "cwStateDownloading", tone: "busy" },
    stopping: { word: "cwStateStopping", tone: "idle" },
    deleting: { word: "cwStateDeleting", tone: "idle" },
    stopped: { word: "cwStateStopped", tone: "idle" },
    reserved: { word: "cwStateReserved", tone: "idle" },
    failed: { word: "cwStateFailed", tone: "bad" },
    broken: { word: "cwStateBroken", tone: "bad" },
  };
  /** The hooks a test finds the window's parts by (docs/testability.md), spelled out for its guard. */
  static HOOKS = {
    window: "cell-window", close: "cell-window-close", via: "cell-window-via", band: "cell-window-band",
    action: "cell-window-action", tab: "cell-window-tab", panel: "cell-window-panel", more: "cell-window-more",
    menu: "cell-window-menu", item: "cell-window-item", copy: "cell-window-copy", tile: "cell-window-tile",
    button: "cell-window-button", link: "cell-window-link",
  };
  /** The states whose band offers Stop: a process is up, or on its way up. */
  static STOPPABLE = ["running", "starting", "warming", "downloading", "broken"];

  /**
   * @param key, name, port, address, via, viaTitle, engine — who the cell is and where its requests go (an engine's cell)
   * @param facts — the words under the name: what it does, what runs it, the file's own facts
   * @param place — where it computes: the split, the cards, the autostart
   * @param tab — the tab chosen in this visit (CardFold.windowTab), "" for the first
   * @param state — one of STATES; `sub` — the band's second line, HTML (it may carry a live progress line)
   * @param actions — {start, stop, configure}: the attributes of the card's ▶, ⏹ and ⚙ when they may be pressed, "" when not;
   *   {why}: why the line's switch is shut now — the tip of a main button that may not be pressed
   * @param menu — {boot: {attrs, on, supported, title}, port, detail, del, delTitle}: the "⋯" items, attributes or ""
   * @param overview — {notice, tiles: [{id, label, value, sub, live, liveSub}], alerts, notes, links, slots, extra, empty}: `live` and
   *   `liveSub` mark the figure and its line for the live patch; `links` — {models, hf}: the addresses of the model in the caravan's
   *   own pages (LibraryPath), "" for one it has not; `empty` is said when there is nothing else to show
   * @param memory — {badges, cards: [{name, figure, sub}], rows: [{k, v}], configure, place}: `place` is where the placement
   *   map is drawn from the form (cell-settings.js), HTML; with it the summary of the saved placement is not drawn
   * @param settings — {rows: [{k, v}], configure, port, detail, editor}: `editor` is the settings edited in the tab
   *   (cell-settings.js), HTML; with it the summary of the main fields gives way
   * @param foot — what is not applied of the settings edited in the window, with Discard and Apply (cell-settings.js), HTML;
   *   `footSlot` says the window has a foot at all (a cell whose settings are edited here), `running` whether it runs
   * @param log — [{tone, title, detail, hint, raw}], newest first: the hint is a line of its own, after the detail
   * @param logTail — the section of the server's own log under them (cell-log.js), HTML; "" for a cell that has none
   * @param talk — the talk, live and page buttons of a runner that has them, HTML; "" for none
   * @param chat — the text chat of a chat cell (cell-chat.js), HTML; "" for none
   */
  constructor({ key, name, port, address = "", via = "", viaTitle = "", engine = "", facts = [], place = [], tab = "",
                state = "stopped", sub = "", actions = {}, menu = {}, overview = {}, memory = {}, settings = {}, log = [],
                logTail = "", talk = "", chat = "", foot = "", footSlot = false, running = false } = {}) {
    this.key = String(key || "");
    this.name = String(name || "");
    this.port = String(port || "");
    this.address = String(address || "");
    this.via = String(via || "");
    this.viaTitle = String(viaTitle || "");
    this.engine = CellRow.launcher(engine);
    this.facts = (Array.isArray(facts) ? facts : []).map((f) => String(f || "").trim()).filter(Boolean);
    this.place = (Array.isArray(place) ? place : []).map((p) => String(p || "").trim()).filter(Boolean);
    this.state = CellWindow.STATES[state] ? state : "stopped";
    this.sub = String(sub || "");
    this.actions = { start: String(actions.start || ""), stop: String(actions.stop || ""), configure: String(actions.configure || ""),
                     why: String(actions.why || "") };
    this.menu = menu || {};
    this.overview = overview || {};
    this.memory = memory || {};
    this.settings = settings || {};
    this.log = Array.isArray(log) ? log : [];
    this.logTail = String(logTail || "");
    this.talk = String(talk || "");
    this.chat = String(chat || "");
    this.foot = String(foot || "");
    this.footSlot = !!footSlot;
    this.running = !!running;
    this.tab = this.tabs().includes(tab) ? tab : "overview";
  }

  /** What the band of a running cell says, by the line's rule (cell-speed.js): that it answers a request or waits for one —
   *  when its server says how many it has — and the speed. "" when it says neither. The live patch asks the same. */
  static speedWords(speed, format) {
    const words = speed.words(format);
    if (speed.requests === null) return words;
    const what = t(speed.working ? "cwAnswering" : "cwWaiting");
    return words ? `${what} · ${words}` : what;
  }

  /** The line under the speed figure: how fast the last prompt was read, when the server says it; that the speed is not
   *  measured, when the server keeps no metrics — and that a restart brings them, when it does; that no request was measured,
   *  only while there is no speed at all; nothing otherwise. A cell that does not run says so. The live patch asks the same,
   *  so the figure and its line never tell two stories. */
  static speedSub(speed, promptTps, format) {
    if (!speed.running) return t("cwNotRunning");
    if (Number(promptTps) > 0) return t("cwPromptSpeed", { tps: format(Number(promptTps)) });
    if (speed.unmeasured) return t(speed.measuredNext ? "cwSpeedNoMetricsNext" : "cwSpeedNoMetrics");
    return speed.speed > 0 ? "" : t("cwSpeedNone");
  }

  /** The machine and the port of a cell's key ("host:port", the window's data-t-id): by the last ":", "" for both without one.
   *  The log and the chat of the window ask the controller by them. */
  static place(key) {
    const k = String(key);
    const at = k.lastIndexOf(":");
    return at > 0 ? { hostId: k.slice(0, at), port: k.slice(at + 1) } : { hostId: "", port: "" };
  }

  /** The tabs this cell has: every one but the talk, which only a cell that can be talked to gets — a chat, or a runner
   *  that talks by voice, live or on a page of its own. */
  tabs() {
    return CellWindow.TABS.filter((id) => id !== "talk" || this.talk || this.chat);
  }

  html() {
    const k = escapeHtml(this.key);
    const label = escapeHtml(`${t("a11yCell")} :${this.port} ${this.name}`.trim());
    return `<div class="cell-window-backdrop" data-cell-window-close="1" aria-hidden="true"></div>`
      + `<div class="cell-window cw${this.engine ? ` engine-${this.engine}` : ""}" role="dialog" aria-modal="true" aria-label="${label}"`
      + ` data-t="${CellWindow.HOOKS.window}" data-t-id="${k}">${this.head()}`
      // The live patch finds the numbers of the band and the panels here (topology-render.js syncTopologyLive). Its own mark:
      // `data-cell-live` is the 📞 button's, and the lane binds a live call to every element that wears it (remote-cells.js).
      + `<div class="cw-live" data-cell-window-live="1" data-llama-port="${escapeHtml(this.port)}">${this.band()}${this.tabsHtml()}`
      + `<div class="cw-panels">${this.tabs().map((id) => this.panel(id)).join("")}</div>${this.footHtml()}</div></div>`;
  }

  // ── the passport ────────────────────────────────────────────────────────────────────────────────────

  head() {
    const k = escapeHtml(this.key);
    const close = escapeHtml(t("close"));
    const more = escapeHtml(t("cwMore"));
    const facts = this.facts.length ? `<span class="cwh-facts">${escapeHtml(this.facts.join(" · "))}</span>` : "";
    const address = this.address
      ? `<button type="button" class="cwh-addr" data-cell-window-copy="${escapeHtml(this.address)}" data-t="${CellWindow.HOOKS.copy}"`
        + ` data-t-id="${k}" title="${escapeHtml(t("cwCopyAddress"))}"><span data-cell-window-copied>${escapeHtml(this.address)}</span>`
        + `<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">`
        + `<rect x="5" y="5" width="8" height="8" rx="1.5"></rect><path d="M3 10.5V4a1 1 0 0 1 1-1h6.5"></path></svg></button>` : "";
    const via = this.via
      ? `<span class="cwh-via" data-t="${CellWindow.HOOKS.via}" title="${escapeHtml(this.viaTitle)}">→ ${escapeHtml(this.via)}</span>` : "";
    const place = this.place.length ? `<span class="cwh-place">${escapeHtml(this.place.join(" · "))}</span>` : "";
    const where = address || via || place ? `<div class="cwh-where">${address}${via}${place}</div>` : "";
    return `<div class="cell-window-head"><div class="cwh-id"><div class="cwh-title"><strong class="cwh-name">${escapeHtml(this.name)}</strong>`
      + `<span class="cwh-port">:${escapeHtml(this.port)}</span>${facts}</div>${where}</div>`
      + `<button type="button" class="cwh-icon cwh-more" data-cell-window-more="${k}" aria-haspopup="menu" aria-expanded="false"`
      + ` data-t="${CellWindow.HOOKS.more}" data-t-id="${k}" title="${more}" aria-label="${more}">`
      + `<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true">`
      + `<path d="M3 8h.01M8 8h.01M13 8h.01"></path></svg></button>`
      + `<button type="button" class="cwh-icon cwh-close" data-cell-window-close="1" data-t="${CellWindow.HOOKS.close}"`
      + ` data-t-id="${k}" title="${close}" aria-label="${close}">✕</button>${this.menuHtml()}</div>`;
  }

  /** The "⋯": what is done to a cell now and then — its autostart, its address, its port, its command, its removal. An item
   *  that may not be pressed now stays, shut, with the reason as its tip: a menu whose items come and go is learnt twice. */
  menuHtml() {
    const k = escapeHtml(this.key);
    const item = (id, attrs, words, { cls = "", tip = "", extra = "", role = 'role="menuitem"' } = {}) =>
      `<button type="button" ${role} class="cwm-item${cls}" ${attrs || "disabled"} data-t="${CellWindow.HOOKS.item}" data-t-id="${k}:${id}"`
        + `${tip ? ` title="${escapeHtml(tip)}"` : ""}>${escapeHtml(words)}${extra}</button>`;
    const boot = this.menu.boot || {};
    const on = !!(boot.supported && boot.on);
    const knob = `<span class="cwm-switch${on ? " on" : ""}" aria-hidden="true"><span></span></span>`;
    const items = [
      item("boot", String(boot.attrs || ""), t("cwAutostart"),
        { cls: " cwm-check", tip: boot.title || "", extra: knob, role: `role="menuitemcheckbox" aria-checked="${on}"` }),
      this.address ? item("copy", `data-cell-window-copy="${escapeHtml(this.address)}"`, t("cwCopyAddress")) : "",
      item("port", String(this.menu.port || ""), t("cwChangePort"), { tip: this.menu.port ? "" : t("cwPortOnlyParked") }),
      item("detail", String(this.menu.detail || ""), t("cwDetails")),
      `<div class="cwm-sep" role="separator"></div>`,
      item("delete", String(this.menu.del || ""), t("cwDelete"), { cls: " cwm-danger", tip: this.menu.delTitle || "" }),
    ];
    return `<div class="cwh-menu" role="menu" aria-label="${escapeHtml(t("cwMore"))}" hidden data-t="${CellWindow.HOOKS.menu}"`
      + ` data-t-id="${k}">${items.join("")}</div>`;
  }

  // ── the band ────────────────────────────────────────────────────────────────────────────────────────

  band() {
    const k = escapeHtml(this.key);
    const st = CellWindow.STATES[this.state];
    const log = st.tone === "bad"
      ? `<button type="button" class="cw-band-more" data-cell-window-tab="log">${escapeHtml(t("cwTabLog"))}</button>` : "";
    return `<div class="cw-band ${st.tone}" role="status" data-t="${CellWindow.HOOKS.band}" data-t-id="${k}" data-t-state="${this.state}">`
      + `<span class="cw-dot" aria-hidden="true"></span><div class="cw-band-text"><strong class="cw-band-title">${escapeHtml(t(st.word))}</strong>`
      + `${this.sub ? `<div class="cw-band-sub">${this.sub}</div>` : ""}</div>${log}${this.action()}</div>`;
  }

  /** The one main button: Stop for a cell whose process is up or on its way, Start for one that is parked or failed, the
   *  settings for a port with no model yet. A cell being stopped or deleted gets it shut and spinning, as the card's own
   *  does. A button that may not be pressed now — Start of a cell that may not start, Stop of one whose start was only just
   *  asked for — stays, shut, with the line's reason as its tip (`actions.why`): its words say what it would do, not what
   *  the cell is doing. */
  action() {
    const k = escapeHtml(this.key);
    const button = (kind, attrs, words, cls) => `<button type="button" class="cw-act ${cls}" ${attrs}`
      + ` data-t="${CellWindow.HOOKS.action}" data-t-id="${k}" data-t-state="${kind}">${escapeHtml(words)}</button>`;
    const busy = (words) => `<button type="button" class="cw-act busy" disabled data-t="${CellWindow.HOOKS.action}" data-t-id="${k}"`
      + ` data-t-state="busy"><span class="topology-spinner stopping-spinner" aria-hidden="true"></span>${escapeHtml(words)}</button>`;
    const shut = (words, cls) => `<button type="button" class="cw-act ${cls}" disabled`
      + `${this.actions.why ? ` title="${escapeHtml(this.actions.why)}"` : ""}`
      + ` data-t="${CellWindow.HOOKS.action}" data-t-id="${k}" data-t-state="shut">${escapeHtml(words)}</button>`;
    const s = this.state;
    if (s === "stopping" || s === "deleting") return busy(t(s === "deleting" ? "removingSlotLabel" : "stoppingLabel"));
    if (s === "reserved") return this.actions.configure ? button("configure", this.actions.configure, t("cwChooseModel"), "go") : "";
    if (CellWindow.STOPPABLE.includes(s)) return this.actions.stop ? button("stop", this.actions.stop, t("stop"), "halt") : shut(t("stop"), "halt");
    const words = t(s === "failed" ? "cwStartAgain" : "start");
    return this.actions.start ? button("start", this.actions.start, words, "go") : shut(words, "go");
  }

  // ── the tabs ────────────────────────────────────────────────────────────────────────────────────────

  tabsHtml() {
    const k = escapeHtml(this.key);
    return `<div class="cw-tabs" role="tablist" aria-label="${escapeHtml(t("cwTabsLabel"))}">${this.tabs().map((id) => {
      const on = id === this.tab;
      return `<button type="button" role="tab" class="cw-tab${on ? " on" : ""}" aria-selected="${on}" data-cell-window-tab="${id}"`
        + ` data-t="${CellWindow.HOOKS.tab}" data-t-id="${k}:${id}">${escapeHtml(t(CellWindow.TAB_WORDS[id]))}</button>`;
    }).join("")}</div>`;
  }

  panel(id) {
    const k = escapeHtml(this.key);
    const body = { overview: () => this.overviewHtml(), memory: () => this.memoryHtml(), settings: () => this.settingsHtml(),
                   log: () => this.logHtml(), talk: () => this.talkHtml() }[id]();
    return `<div class="cw-panel cw-panel-${id}" role="tabpanel" data-cell-window-panel="${id}" data-t="${CellWindow.HOOKS.panel}"`
      + ` data-t-id="${k}:${id}"${id === this.tab ? "" : " hidden"}>${body}</div>`;
  }

  static section(title, body) {
    return body ? `<section class="cw-sec">${title ? `<h4 class="cw-sec-title">${escapeHtml(title)}</h4>` : ""}${body}</section>` : "";
  }

  static rows(rows) {
    const list = (Array.isArray(rows) ? rows : []).filter((r) => r && String(r.v ?? "").trim() !== "");
    return list.length
      ? `<dl class="cw-rows">${list.map((r) => `<div class="cw-row"><dt>${escapeHtml(r.k)}</dt><dd>${escapeHtml(String(r.v))}</dd></div>`).join("")}</dl>`
      : "";
  }

  /** A button of a panel that carries one of the card's actions; none when the action may not be pressed now. */
  button(id, attrs, words, cls = "") {
    return attrs ? `<button type="button" class="cw-btn${cls}" ${attrs} data-t="${CellWindow.HOOKS.button}"`
      + ` data-t-id="${escapeHtml(this.key)}:${id}">${escapeHtml(words)}</button>` : "";
  }

  overviewHtml() {
    const o = this.overview;
    const k = escapeHtml(this.key);
    const tiles = (Array.isArray(o.tiles) ? o.tiles : []).map((tile) => `<div class="cw-tile" data-t="${CellWindow.HOOKS.tile}"`
      + ` data-t-id="${k}:${escapeHtml(tile.id)}"><span class="cw-tile-label">${escapeHtml(tile.label)}</span>`
      + `<span class="cw-tile-value"${tile.live ? ` ${tile.live}` : ""}>${escapeHtml(tile.value || "—")}</span>`
      + `<span class="cw-tile-sub"${tile.liveSub ? ` ${tile.liveSub}` : ""}>${escapeHtml(tile.sub || "")}</span></div>`).join("");
    const body = `${o.notice || ""}${tiles ? `<div class="cw-tiles">${tiles}</div>` : ""}`
      + `${o.alerts ? CellWindow.section(t("cwAlerts"), `<div class="cw-chips">${o.alerts}</div>`) : ""}`
      + `${CellWindow.section(t("cwAboutModel"), `${o.notes || ""}${this.modelLinksHtml()}`)}${o.slots || ""}${o.extra || ""}`;
    return body || (o.empty ? `<p class="cw-empty">${escapeHtml(o.empty)}</p>` : "");
  }

  /** Where the cell's model is in the caravan's own pages, under what is said of it (the owner, 2026-10-26: "a link to the model
   *  in our storage, and to our page on HF"): the models page on its folder and /hf on its repository, in this tab as everything
   *  of the caravan (check_same_tab_links.py — the owner's word of 2026-10-17); the way back is the browser's Back. A link the
   *  model's path does not give is not drawn. */
  modelLinksHtml() {
    const links = this.overview.links || {};
    const k = escapeHtml(this.key);
    const one = (id, href, words) => (href
      ? `<a class="cw-btn cw-link" href="${escapeHtml(href)}" data-t="${CellWindow.HOOKS.link}"`
        + ` data-t-id="${k}:${id}">${escapeHtml(words)}</a>` : "");
    const html = one("models", String(links.models || ""), t("cwModelInLibrary")) + one("hf", String(links.hf || ""), t("cwModelOnHf"));
    return html ? `<div class="cw-buttons cw-links">${html}</div>` : "";
  }

  memoryHtml() {
    const m = this.memory;
    const cards = (Array.isArray(m.cards) ? m.cards : []).map((c) => `<div class="cw-mem-card"><span class="cw-mem-name">${escapeHtml(c.name)}</span>`
      + `<span class="cw-mem-figure">${escapeHtml(c.figure || "—")}</span><span class="cw-mem-sub">${escapeHtml(c.sub || "")}</span></div>`).join("");
    const held = `${m.badges ? `<div class="cw-chips">${m.badges}</div>` : ""}${cards ? `<div class="cw-mem-cards">${cards}</div>` : ""}`;
    const heldSec = CellWindow.section(t("cwHeld"), held || `<p class="cw-empty">${escapeHtml(t("cwHeldNothing"))}</p>`);
    // The placement map, drawn from the form, stands here when the window edits the cell's settings: a summary of the saved
    // placement beside it would tell another story while edits are not applied. The map titles itself ("Where the model
    // lives"); where the cell computes stays in the dialog.
    if (m.place) {
      return `${heldSec}${CellWindow.section("", String(m.place))}`
        + `<div class="cw-buttons">${this.button("placement", m.configure, t("cwSettingsOpen"))}</div>`;
    }
    const place = CellWindow.rows(m.rows);
    return heldSec
      + CellWindow.section(t("cwPlacement"), place || `<p class="cw-empty">${escapeHtml(t("cwPlacementDefault"))}</p>`)
      + `<div class="cw-buttons">${this.button("placement", m.configure, t("cwPlacementEdit"))}</div>`;
  }

  settingsHtml() {
    const s = this.settings;
    // The settings edited here: the editor, and the dialog with every runner's field and the command for what it has not.
    if (s.editor) {
      return `${s.editor}<div class="cw-buttons cw-set-more">${this.button("configure", s.configure, t("cwSettingsOpen"))}`
        + `${this.button("port", s.port, t("cwChangePort"))}${this.button("detail", s.detail, t("cwDetails"))}</div>`;
    }
    const rows = CellWindow.rows(s.rows);
    return CellWindow.section(t("cwSettingsMain"), rows || `<p class="cw-empty">${escapeHtml(t("cwSettingsNone"))}</p>`)
      + `<p class="cw-lead">${escapeHtml(t(s.configure ? "cwSettingsLead" : "cwSettingsShut"))}</p>`
      + `<div class="cw-buttons">${this.button("configure", s.configure, t("cwSettingsOpen"), " primary")}${this.button("port", s.port, t("cwChangePort"))}`
      + `${this.button("detail", s.detail, t("cwDetails"))}</div>`;
  }

  /** The window's foot: what is not applied of the settings edited here. Its slot stands while the window edits the cell's
   *  settings (the board patches it as the fields change), empty while nothing is pending. */
  footHtml() {
    if (!this.footSlot) return "";
    return `<div class="cw-foot" data-cell-window-foot="${escapeHtml(this.key)}" data-running="${this.running ? "1" : ""}">${this.foot}</div>`;
  }

  /** What the cell reported going wrong, then the server's own log under it (the builder's, from cell-log.js). */
  logHtml() {
    const events = !this.log.length ? `<p class="cw-empty">${escapeHtml(t("cwLogEmpty"))}</p>`
      : `<div class="cw-log">${this.log.map((e) => `<div class="cw-ev ${e.tone === "bad" ? "bad" : "info"}">`
        + `<strong class="cw-ev-title">${escapeHtml(e.title)}</strong>${e.detail ? `<span class="cw-ev-detail">${escapeHtml(e.detail)}</span>` : ""}`
        + `${e.hint ? `<span class="cw-ev-detail">${escapeHtml(e.hint)}</span>` : ""}`
        + `${e.raw ? `<pre class="cw-ev-raw">${escapeHtml(e.raw)}</pre>` : ""}</div>`).join("")}</div>`;
    return `${events}${this.logTail}`;
  }

  /** The text chat first, when the cell has one; then the ways to talk by voice, live or on its own page, when the runner has them. */
  talkHtml() {
    const ways = this.talk ? `<p class="cw-lead">${escapeHtml(t("cwTalkLead"))}</p><div class="cw-buttons cw-talk">${this.talk}</div>` : "";
    return `${this.chat}${this.chat && ways ? `<div class="cw-talk-ways">${ways}</div>` : ways}`;
  }
}
