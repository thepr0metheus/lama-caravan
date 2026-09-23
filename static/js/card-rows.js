// The folded line of a board card, and the slot that holds the line and the card.
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
  constructor(f = {}) {
    this.key = String(f.key || "");
    this.port = String(f.port || "");
    this.name = String(f.name || "");
    this.title = String(f.title || f.name || "");
    // "running", "parked" (configured, stopped) or "reserved" (no model yet).
    this.state = f.state === "running" || f.state === "reserved" ? f.state : "parked";
    this.cpu = !!f.cpu;
    this.chip = f.chip || "";          // the card's own memory/device chip, as built
    this.launch = f.launch || "";      // the card's ▶ attributes, empty when it cannot start
    this.warn = !!f.warn;
    this.tps = String(f.tps || "");
    this.busy = !!f.busy;
    this.anchor = f.anchor || "";      // the cable's handle: the line owns it while folded
  }

  lead() {
    if (this.state === "parked" && this.launch) {
      return `<button type="button" class="fr-play" ${this.launch} data-t="cell-row-start"`
        + ` data-t-id="${escapeHtml(this.key)}" title="${escapeHtml(t("nodeStartServer"))}">▶</button>`;
    }
    return '<span class="fr-dot" aria-hidden="true"></span>';
  }

  html() {
    const name = this.state === "reserved" ? t("topologyReservedCellLabel") : this.name;
    const warn = this.warn
      ? `<span class="fr-warn" title="${escapeHtml(t("cellRowWarnTitle"))}">⚠</span>` : "";
    const cls = ["fold-row", "cell-row", this.state, this.cpu ? "cpu" : "", this.busy ? "busy" : ""]
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
    this.stale = !!f.stale;
    this.routes = (f.routes || []).filter((r) => r && r.port);
  }

  route(r) {
    const face = r.face || { cls: "route-confirmed-tag", glyph: "✓", tip: "" };
    const facts = [
      r.model ? `<span class="ar-model">${escapeHtml(r.model)}${r.locked ? " 🔒" : ""}</span>` : "",
      r.waitSec ? `<span class="ar-meta">${escapeHtml(t("routeWaitLabel", { sec: String(r.waitSec) }))}</span>` : "",
      r.limit ? `<span class="ar-meta">${escapeHtml(t("routeCtxLimit", { value: String(r.limit) }))}</span>` : "",
    ].join("");
    return `<div class="ar-route ${escapeHtml(r.role)}${r.muted ? " muted" : ""}">${r.anchor || ""}`
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
 * The place a folding card stands in its lane. While folded it holds the line,
 * which never moves, and the full card, which floats over the lane on hover —
 * so the lane never reflows under the pointer and no cable has to move. Pinned,
 * it holds the full card in place and the control that folds it back.
 */
export class FoldSlot {
  constructor({ key, lane, mode, line = "", card = "", peek = false } = {}) {
    this.key = String(key || "");
    this.lane = lane === "clients" ? "clients" : "cells";
    this.mode = mode === "pinned" ? "pinned" : "line";
    this.line = line;
    this.card = card;
    this.peek = !!peek && this.mode === "line";
  }

  control() {
    const pinned = this.mode === "pinned";
    return `<button type="button" class="fold-pin" data-fold-pin="1" data-t="${pinned ? "fold-unpin" : "fold-pin"}"`
      + ` data-t-id="${escapeHtml(this.key)}" title="${escapeHtml(t(pinned ? "foldUnpinTitle" : "foldPinTitle"))}">`
      + `${pinned ? "▴" : "📌"}</button>`;
  }

  html() {
    return `<div class="fold-slot ${this.lane}-fold${this.peek ? " peek" : ""}"`
      + ` data-fold-key="${escapeHtml(this.key)}" data-fold-mode="${this.mode}">`
      + `${this.mode === "line" ? this.line : ""}${this.card}${this.control()}</div>`;
  }
}
