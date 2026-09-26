// The folded line of a board card, the slot that holds the line and the card,
// and the window a cell's card opens in.
import { CardFold } from "./card-fold.js";
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";

/**
 * A cell folded into one line: what it serves, on which port, whether it runs.
 *
 * The card computes every fact once — the name the runner reports, the memory
 * chip, the start button's attributes — and hands them over; nothing here
 * re-derives them, so the line and the card cannot disagree about a cell.
 */
export class CellRow {
  /** The runner of a cell whose model runs inside an engine, fit to name a
   *  class (engine-ollama) — "" for any other word. */
  static launcher(id) {
    return /^[a-z][a-z0-9-]*$/.test(String(id || "")) ? String(id) : "";
  }

  constructor(f = {}) {
    this.key = String(f.key || "");
    this.port = String(f.port || "");
    this.name = String(f.name || "");
    this.title = String(f.title || f.name || "");
    // "running", "parked" (configured, stopped) or "reserved" (no model yet).
    this.state = f.state === "running" || f.state === "reserved" ? f.state : "parked";
    this.cpu = !!f.cpu;
    // The runner of a cell whose model runs inside an engine (ollama,
    // lmstudio): the line wears its launcher's colour. "" for the caravan's own.
    this.engine = CellRow.launcher(f.engine);
    this.chip = f.chip || "";          // the card's own memory/device chip, as built
    this.launch = f.launch || "";      // the card's ▶ attributes, empty when it cannot start
    this.stop = f.stop || "";          // the card's ⏹ attributes, empty when it cannot stop
    this.why = String(f.why || "");    // what flipping the switch does now, or why it cannot
    this.warn = !!f.warn;
    this.tps = String(f.tps || "");
    this.busy = !!f.busy;
    this.anchor = f.anchor || "";      // the cable's handle: the line owns it while folded
  }

  /** The line's switch: on while the cell runs, off while it is parked. It is
   *  the card's ▶ and ⏹ in one — flipping it carries their attributes, so the
   *  same confirm starts or stops the same cell. A cell that cannot be flipped
   *  now (no model yet, or nothing it may do) shows it disabled, saying why. */
  lead() {
    const on = this.state === "running";
    const act = on ? this.stop : this.launch;
    const hook = on ? "cell-row-stop" : "cell-row-start";
    const attrs = act ? `${act} data-t="${hook}" data-t-id="${escapeHtml(this.key)}"` : "disabled";
    const why = escapeHtml(this.why);
    return `<button type="button" class="fr-switch" role="switch" aria-checked="${on}" ${attrs}`
      + ` title="${why}" aria-label="${why}"><span class="fr-knob" aria-hidden="true"></span></button>`;
  }

  /** The name the line shows — and its window's title, from this one rule. */
  shownName() {
    return this.state === "reserved" ? t("topologyReservedCellLabel") : this.name;
  }

  html() {
    const name = this.shownName();
    const warn = this.warn
      ? `<span class="fr-warn" title="${escapeHtml(t("cellRowWarnTitle"))}">⚠</span>` : "";
    const cls = ["fold-row", "cell-row", this.state, this.cpu ? "cpu" : "", this.engine ? `engine-${this.engine}` : "",
      this.busy ? "busy" : ""]
      .filter(Boolean).join(" ");
    return `<div class="${cls}" role="button" tabindex="0" data-t="cell-row"`
      + ` data-t-id="${escapeHtml(this.key)}" data-llama-port="${escapeHtml(this.port)}"`
      + ` title="${escapeHtml(this.title)}">${this.anchor}${this.lead()}`
      + `<span class="fr-port">:${escapeHtml(this.port)}</span>`
      + `<span class="fr-name">${escapeHtml(name)}</span>${warn}`
      + `<span class="fr-tps" data-live-rowtps>${escapeHtml(this.tps)}</span>${this.chip}</div>`;
  }
}

/**
 * An agent folded into its header and one line per route it has. Only what is
 * set is shown: a route that does not exist, a model name nobody gave, a limit
 * nobody set are absent here rather than drawn as dashes. Every value is still
 * changed where it always was — on the full card, which floats open on hover.
 */
export class AgentRow {
  constructor(f = {}) {
    this.key = String(f.key || "");
    this.name = String(f.name || "");
    this.kind = String(f.kind || "");
    this.routes = (f.routes || []).filter((r) => r && r.port);
  }

  route(r) {
    const face = r.face || { cls: "route-confirmed-tag", glyph: "✓", tip: "" };
    const facts = [
      r.model ? `<span class="ar-model">${escapeHtml(r.model)}${r.locked ? " 🔒" : ""}</span>` : "",
      r.waitSec ? `<span class="ar-meta">${escapeHtml(t("routeWaitLabel", { sec: String(r.waitSec) }))}</span>` : "",
      r.limit ? `<span class="ar-meta">${escapeHtml(t("routeCtxLimit", { value: String(r.limit) }))}</span>` : "",
    ].join("");
    return `<div class="ar-route ${escapeHtml(r.role)}">${r.anchor || ""}`
      + `<span class="${face.cls}" title="${escapeHtml(face.tip ? t(face.tip) : "")}">${face.glyph}</span>`
      + `<span class="ar-port" title="${escapeHtml(r.address || "")}">${r.role === "fallback" ? "↪ " : ""}:${escapeHtml(String(r.port))}</span>`
      + `${facts}${r.errBadge || ""}</div>`;
  }

  html() {
    return `<div class="fold-row agent-row" role="button" tabindex="0" data-t="agent-row"`
      + ` data-t-id="${escapeHtml(this.key)}"><div class="ar-head"><span class="ar-dot" aria-hidden="true"></span>`
      + `<strong>${escapeHtml(this.name)}</strong><span class="ar-kind">${escapeHtml(this.kind)}</span></div>`
      + `${this.routes.map((r) => this.route(r)).join("")}</div>`;
  }
}

/**
 * A cell's card as a window over the board: the card itself with a title bar
 * and a ✕ above it, over a dimmed board. Drawn inside the cell's slot and shown
 * only while the slot is open (fold.css), so the card's buttons are bound where
 * the lane binds them and a repaint redraws the window with the lane. The
 * cable's handle stays on the line, which never moves.
 */
export class CellWindow {
  // `via`: where a cell in an engine sends its requests — the engine's
  // loopback address, which only the cell's port leads to; `viaTitle` says so.
  constructor({ key, name, port, address = "", via = "", viaTitle = "", engine = "", card = "" } = {}) {
    this.key = String(key || "");
    this.name = String(name || "");
    this.port = String(port || "");
    this.address = String(address || "");
    this.via = String(via || "");
    this.viaTitle = String(viaTitle || "");
    this.engine = CellRow.launcher(engine);
    this.card = card || "";
  }

  html() {
    const k = escapeHtml(this.key);
    const close = escapeHtml(t("close"));
    const label = escapeHtml(`${t("a11yCell")} :${this.port} ${this.name}`.trim());
    const address = this.address ? `<span class="cwh-addr">${escapeHtml(this.address)}</span>` : "";
    const via = this.via
      ? `<span class="cwh-via" data-t="cell-window-via" title="${escapeHtml(this.viaTitle)}">→ ${escapeHtml(this.via)}</span>` : "";
    return `<div class="cell-window-backdrop" data-cell-window-close="1" aria-hidden="true"></div>`
      + `<div class="cell-window${this.engine ? ` engine-${this.engine}` : ""}" role="dialog" aria-modal="true" aria-label="${label}"`
      + ` data-t="cell-window" data-t-id="${k}"><div class="cell-window-head">`
      + `<strong class="cwh-name">${escapeHtml(this.name)}</strong>`
      + `<span class="cwh-port">:${escapeHtml(this.port)}</span>${address}${via}`
      + `<button type="button" class="cwh-close" data-cell-window-close="1" data-t="cell-window-close"`
      + ` data-t-id="${k}" title="${close}" aria-label="${close}">✕</button></div>${this.card}</div>`;
  }
}

/**
 * A machine's eye over its list of cells: pressed, the cells that are not
 * running are hidden, and it says how many — hidden is named, not silent.
 */
export class CellEye {
  static OPEN = '<path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z"></path><circle cx="8" cy="8" r="2"></circle>';
  static SHUT = `${CellEye.OPEN}<path d="M2.5 13.5l11-11"></path>`;

  constructor({ hostId, on = false, hidden = 0 } = {}) {
    this.hostId = String(hostId || "");
    this.on = !!on;
    this.hidden = Math.max(0, Number(hidden) || 0);
  }

  html() {
    const words = escapeHtml(this.on ? t("cellsHideIdleOn", { count: String(this.hidden) }) : t("cellsHideIdleOff"));
    const id = escapeHtml(this.hostId);
    const count = this.on ? `<span class="node-eye-count">${this.hidden}</span>` : "";
    return `<button type="button" class="node-eye" data-cell-eye="${id}" data-t="node-hide-idle" data-t-id="${id}"`
      + ` aria-pressed="${this.on}" title="${words}" aria-label="${words}">`
      + `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"`
      + ` stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${this.on ? CellEye.SHUT : CellEye.OPEN}</svg>`
      + `${count}</button>`;
  }
}

/**
 * A machine's chips over its list of cells (2026-09-25): all of them, or only
 * the ones one launcher runs — the caravan itself, or an engine next to it.
 * Each chip says how many cells it holds; an engine's carries a dot while its
 * server answers, and none when the machine did not report it. The pressed
 * chip is the list shown. `anchors` are the handles of the engine models made
 * router outputs directly: their cables land at the chips' edge, as a cell's
 * land at its line.
 */
export class CellFilter {
  constructor({ hostId, chosen = "", options = [], anchors = "" } = {}) {
    this.hostId = String(hostId || "");
    this.chosen = String(chosen || "");
    this.anchors = String(anchors || "");
    this.options = (Array.isArray(options) ? options : []).map((o) => ({
      id: String(o?.id || ""),
      label: String(o?.label || ""),
      count: Math.max(0, Math.floor(Number(o?.count) || 0)),
      up: typeof o?.up === "boolean" ? o.up : null,
      title: String(o?.title || ""),
    }));
  }

  html() {
    if (!this.options.length) return "";
    const host = escapeHtml(this.hostId);
    const chips = this.options.map((o) => {
      // An engine's chip wears its colour; "" (all) and the caravan keep the board's.
      const engine = o.id && o.id !== "caravan" ? CellRow.launcher(o.id) : "";
      const dot = o.up === null ? "" : `<span class="ncf-dot${o.up ? " up" : ""}" aria-hidden="true"></span>`;
      return `<button type="button" class="ncf-chip${engine ? ` engine-${engine}` : ""}" data-cell-filter="${host}"`
        + ` data-cell-filter-id="${escapeHtml(o.id)}" data-t="node-cell-filter" data-t-id="${host}:${escapeHtml(o.id || "all")}"`
        + ` aria-pressed="${o.id === this.chosen}" title="${escapeHtml(o.title)}">${dot}${escapeHtml(o.label)}`
        + `<span class="ncf-count">${o.count}</span></button>`;
    }).join("");
    return `<div class="node-cell-filter" role="group" aria-label="${escapeHtml(t("cellsFilterLabel"))}">`
      + `${this.anchors}${chips}</div>`;
  }
}

/**
 * An engine's server, in one strip over its machine's chips (2026-09-26, the
 * operator's choice B, always shown): the switch starts or stops it, then
 * its name, what it holds and a download; under them where it listens and
 * what it has to say. The builder computes each piece — the switch with its
 * attributes and reason, the memory with its live hooks — and nothing here
 * re-derives them. The strip keeps the engine's test hook (node-engine) and
 * the live patch's handle on its memory.
 */
export class EngineStrip {
  constructor({ key, engine = "", state = "", label = "", version = "", lever = "", boot = "", memory = "",
                pull = "", where = "", notes = "", title = "" } = {}) {
    this.key = String(key || "");
    this.engine = CellRow.launcher(engine);
    this.state = String(state || "");
    this.label = String(label || "");
    this.version = String(version || "");
    this.lever = lever || "";
    this.boot = boot || "";
    this.memory = memory || "";
    this.pull = pull || "";
    this.where = where || "";
    this.notes = notes || "";
    this.title = String(title || "");
  }

  html() {
    const version = this.version ? `<span class="es-ver">${escapeHtml(this.version)}</span>` : "";
    return `<div class="engine-strip${this.engine ? ` engine-${this.engine}` : ""}" data-t="node-engine"`
      + ` data-t-id="${escapeHtml(this.key)}" data-t-state="${escapeHtml(this.state)}" title="${escapeHtml(this.title)}">`
      + `<div class="es-main">${this.lever}<strong class="es-name">${escapeHtml(this.label)}</strong>${version}`
      + `<span class="es-fill"></span>${this.boot}${this.memory}${this.pull}</div>`
      + `<div class="es-sub">${this.where}${this.notes}</div></div>`;
  }
}

/**
 * A model its engine holds and no cell serves yet: a line of the cells' shape,
 * dashed, with "+" where a cell's switch stands — "+" makes the cell, with
 * this model, on the next free port. It has no port, so no cable lands on it.
 * The builder hands over what the model is and what may be done to it; the
 * delete waits under the pointer, the unload of a model held outside any cell
 * does not. "+" keeps its test hook while it waits — disabled, saying why —
 * so a test finds it in the one state worth checking.
 */
export class ShelfLine {
  constructor({ key, engine = "", name = "", remote = "", job = "", params = "", memory = "", reserve = "", why = "",
                acts = "", error = "", loaded = false } = {}) {
    this.key = String(key || "");
    this.engine = CellRow.launcher(engine);
    this.name = String(name || "");
    this.remote = remote || "";
    this.job = job || "";
    this.params = String(params || "");
    this.memory = memory || "";
    this.reserve = reserve || "";    // what "+" reserves with, "" when no cell can be made now
    this.why = String(why || "");
    this.acts = acts || "";
    this.error = error || "";
    this.loaded = !!loaded;
  }

  html() {
    const why = escapeHtml(this.why);
    const plus = `<button type="button" class="sl-plus" data-t="engine-model-reserve" data-t-id="${escapeHtml(this.key)}"`
      + ` ${this.reserve || "disabled"} title="${why}" aria-label="${why}">+</button>`;
    const params = this.params ? `<span class="sl-params">${escapeHtml(this.params)}</span>` : "";
    return `<div class="shelf-line${this.engine ? ` engine-${this.engine}` : ""}${this.loaded ? " loaded" : ""}"`
      + ` data-t="engine-model" data-t-id="${escapeHtml(this.key)}">${plus}`
      + `<span class="sl-name" title="${escapeHtml(this.name)}">${escapeHtml(this.name)}</span>${this.remote}${this.job}`
      + `${params}${this.acts}${this.memory}${this.error}</div>`;
  }
}

/**
 * The place a folding card stands in its lane. While folded it holds the line,
 * which never moves, and the full card: an agent's floats over the lane on
 * hover, a cell's opens as a window on a click — so the lane never reflows
 * under the pointer and no cable has to move. Pinned (agents only), it holds
 * the full card in place and the control that folds it back.
 */
export class FoldSlot {
  constructor({ key, lane, mode, line = "", card = "", peek = false, open = false } = {}) {
    this.key = String(key || "");
    this.lane = lane === "clients" ? "clients" : "cells";
    this.mode = mode === "pinned" ? "pinned" : "line";
    this.line = line;
    this.card = card;
    this.peek = !!peek && this.mode === "line";
    this.open = !!open && this.mode === "line";
  }

  /** Whether this lane pins cards in place — not one whose cards open in a window. */
  pins() { return CardFold.OPENS[this.lane] !== "window"; }

  control() {
    const pinned = this.mode === "pinned";
    return `<button type="button" class="fold-pin" data-fold-pin="1" data-t="${pinned ? "fold-unpin" : "fold-pin"}"`
      + ` data-t-id="${escapeHtml(this.key)}" title="${escapeHtml(t(pinned ? "foldUnpinTitle" : "foldPinTitle"))}">`
      + `${pinned ? "▴" : "📌"}</button>`;
  }

  html() {
    const marks = `${this.peek ? " peek" : ""}${this.open ? " open" : ""}`;
    return `<div class="fold-slot ${this.lane}-fold${marks}"`
      + ` data-fold-key="${escapeHtml(this.key)}" data-fold-lane="${this.lane}" data-fold-mode="${this.mode}">`
      + `${this.mode === "line" ? this.line : ""}${this.card}${this.pins() ? this.control() : ""}</div>`;
  }
}
