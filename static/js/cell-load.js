// A starting cell's load as the controller measured it (load_progress.py):
// how much is read, how fast, how long is left, and which file comes next.
//
// Two rows in place of the chips row, and only while a load is measured: the
// bar with the numbers, then the files in the order llama-server reads them.
// A start that cannot be measured sends no loadProgress and keeps the old line
// — a looping bar says "working" without inventing a number.
import { t } from "./i18n.js";
import { Pace } from "./pace.js";
import { escapeHtml, fmtGb } from "./utils.js";

// Role → its word on the card. A role the controller adds later is shown as it
// is sent, never dropped: a step without a word for it is still a step.
const ROLES = { model: "cellLoadModel", draft: "cellLoadDraft", mmproj: "cellLoadMmproj" };
// A state the card has no mark for gets "?" — drawn as waiting it would say
// something the controller did not.
const MARKS = { done: "✓", reading: "▸", waiting: "○" };

export class CellLoad {
  constructor(progress) {
    this.p = progress || {};
  }

  get files() {
    return Array.isArray(this.p.files) ? this.p.files : [];
  }

  get pct() {
    const total = Number(this.p.total) || 0;
    return total > 0 ? Math.min(100, Math.round(((Number(this.p.read) || 0) * 100) / total)) : 0;
  }

  static role(file) {
    const key = ROLES[file.role];
    return key ? t(key) : String(file.role || "");
  }

  static mark(file) {
    return MARKS[file.state] || "?";
  }

  // The line beside the bar: what is read of what, how fast, how long is left.
  // The context is made between files and after the last one, with nothing
  // read — then the line says so instead of a speed that is not happening.
  summary() {
    const p = this.p;
    if (p.stage === "setup") return t("cellLoadSetup");
    if (p.stage === "starting") return t("topologyRemoteStarting");
    const amount = `${fmtGb(Number(p.read) || 0)} / ${fmtGb(Number(p.total) || 0)}`;
    if (p.stage === "stalled") return `${amount} · ${t("cellLoadStalled", { n: String(p.idle) })}`;
    return [amount, Pace.speed(p.speed), Pace.eta(p.left)].filter((part) => part).join(" · ");
  }

  step(file) {
    const size = Number(file.size) || 0;
    const amount = file.state === "reading" ? `${fmtGb(Number(file.read) || 0)} / ${fmtGb(size)}` : fmtGb(size);
    const state = escapeHtml(String(file.state || ""));
    return `<span class="msl-step is-${state}" data-t="cell-load-file" data-t-id="${escapeHtml(String(file.role || ""))}" data-t-state="${state}">`
      + `${CellLoad.mark(file)} ${file.library ? "📚 " : ""}${escapeHtml(CellLoad.role(file))} ${escapeHtml(amount)}</span>`;
  }

  // One line per file for the hover: its name, its size, where it is read from.
  title() {
    return this.files.map((f) => `${CellLoad.mark(f)} ${CellLoad.role(f)}: ${f.name} · ${fmtGb(Number(f.size) || 0)} · `
      + (f.library ? t("cellLoadFrom", { name: f.library }) : t("cellLoadDisk"))).join("\n");
  }

  // Both rows. `id` names the cell for tests; `tail` goes at the end of the
  // first row — the card's ⚠ for a previous attempt that failed. A stall
  // trades the spinner for its own ⚠: a spinner over bytes that stopped would
  // say the load is moving.
  html(id, tail = "") {
    const stage = String(this.p.stage || "");
    const stalled = stage === "stalled";
    const title = escapeHtml(this.title());
    const lead = stalled ? `<span class="msl-stall-icon" aria-hidden="true">⚠</span>`
      : `<span class="topology-spinner" aria-hidden="true"></span>`;
    return `<div class="node-model-row2 model-status-line msl-load${stalled ? " msl-load-stalled" : ""}" data-t="cell-load"`
      + ` data-t-id="${escapeHtml(String(id))}" data-t-state="${escapeHtml(stage)}" title="${title}">`
      + `${lead}<span class="msl-bar"><span style="width:${this.pct}%"></span></span>`
      + `<span class="msl-text">${escapeHtml(this.summary())}</span>${tail}</div>`
      + `<div class="node-model-row2 msl-steps" title="${title}">${this.files.map((f) => this.step(f)).join("")}</div>`;
  }
}
