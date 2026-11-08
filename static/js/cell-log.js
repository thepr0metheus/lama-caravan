// A cell's log in its window (1.3.623): the last lines its server wrote and the runs there are to read, as the machine's scout
// reads them (2.36, GET /api/llama-node/log) and the controller passes them on (GET /api/cell-log?cell=<cellId>) — the board is
// https, the scout plain http. A cell's logs follow its id, whatever ports its runs leased. Before, the window said only what the
// scout reported of a failure: a reason and eight lines.
//
// What was read is kept here, by cell id, and not in the window: the board repaints the lane wholesale, and a log read into the
// window would go with the next repaint. The window draws it from here (html). It is read when the Log tab opens, and again on
// the poll's tick while it is shown, the cell runs and its present run is chosen (tick) — an earlier run does not change.
import { t } from "./i18n.js";
import { api, escapeHtml } from "./utils.js";

export class CellLog {
  /** The view's data-t names (docs/testability.md): the section, the button that reads the log, the one that reads it again,
   *  the choice of a run and the lines. data-t-id = the cell's id; the section's data-t-state says idle, loading, ok, error. */
  static HOOKS = { view: "cell-log", show: "cell-log-show", refresh: "cell-log-refresh", run: "cell-log-run", lines: "cell-log-lines" };
  /** How often the present run of a running cell is read again while its log is shown. */
  static EVERY_MS = 5000;
  /** The name of a run rotate put aside: the log's stem, the moment, maybe a number (the scout's CellLog.RUN_STAMP). */
  static EARLIER = /\.\d{8}-\d{6}(?:-\d+)?\.log$/;

  constructor({ call = api, now = () => Date.now(), when = (epoch) => new Date(epoch * 1000).toLocaleString() } = {}) {
    this.call = call;
    this.now = now;
    this.when = when;
    // cellId → {state, run, runs, lines, error, at, busy}
    this.cells = new Map();
    this.bound = false;
  }

  /** What is known of the log of cell `cellId`: the state of one never read when nothing is. */
  of(cellId) {
    return { state: "idle", run: "", runs: [], lines: [], error: "", at: 0, busy: false, ...(this.cells.get(String(cellId)) || {}) };
  }

  /** True for the present run's log: not one rotate put aside. */
  static present(name) {
    return !!name && !CellLog.EARLIER.test(String(name));
  }

  /** The words of a run in the choice: this run or an earlier one, and when its last line was written. */
  runWords(row) {
    const time = Number(row.modifiedAt) > 0 ? this.when(Number(row.modifiedAt)) : "?";
    return t(CellLog.present(row.name) ? "cwLogTailNow" : "cwLogTailBefore", { time });
  }

  /** The Log tab's section of cell `cellId`. `live`: the cell runs, so its present run grows and is read again while shown. */
  html(cellId, { live = false } = {}) {
    const s = this.of(cellId);
    const k = escapeHtml(String(cellId));
    const H = CellLog.HOOKS;
    const open = `<section class="cw-sec cw-tail" data-cell-log-view="${k}" data-cell-log-live="${live ? "1" : ""}"`
      + ` data-t="${H.view}" data-t-id="${k}" data-t-state="${s.state}"><h4 class="cw-sec-title">${escapeHtml(t("cwLogTailTitle"))}</h4>`;
    const read = (hook, attr, words) => `<button type="button" class="cw-btn" ${attr}="${k}" data-t="${hook}" data-t-id="${k}"`
      + `${s.busy ? " disabled" : ""}>${escapeHtml(words)}</button>`;
    if (s.state === "idle") {
      return `${open}<p class="cw-empty">${escapeHtml(t("cwLogTailLead"))}</p>`
        + `<div class="cw-buttons">${read(H.show, "data-cell-log-show", t("cwLogTailShow"))}</div></section>`;
    }
    if (s.state === "loading") {
      return `${open}<p class="cw-empty"><span class="topology-spinner" aria-hidden="true"></span> ${escapeHtml(t("cwLogTailLoading"))}</p></section>`;
    }
    if (s.state === "error") {
      return `${open}<p class="cw-tail-error" role="alert">${escapeHtml(s.error)}</p>`
        + `<div class="cw-buttons">${read(H.show, "data-cell-log-show", t("cwLogTailRetry"))}</div></section>`;
    }
    const options = s.runs.map((row) => `<option value="${escapeHtml(row.name)}"${row.name === s.run ? " selected" : ""}>`
      + `${escapeHtml(this.runWords(row))}</option>`).join("");
    const choose = s.runs.length > 1
      ? `<select class="cw-tail-run" data-cell-log-run="${k}" data-t="${H.run}" data-t-id="${k}" aria-label="${escapeHtml(t("cwLogTailRunLabel"))}"`
        + `${s.busy ? " disabled" : ""}>${options}</select>`
      : `<span class="cw-tail-run-one">${escapeHtml(s.runs[0] ? this.runWords(s.runs[0]) : "")}</span>`;
    const lines = s.lines.length
      ? `<pre class="cw-tail-lines" data-t="${H.lines}" data-t-id="${k}">${escapeHtml(s.lines.join("\n"))}</pre>`
      : `<p class="cw-empty">${escapeHtml(t("cwLogTailEmpty"))}</p>`;
    const growing = live && CellLog.present(s.run);
    return `${open}<div class="cw-tail-head">${choose}<span class="cw-tail-count">${escapeHtml(t("cwLogTailCount", { n: String(s.lines.length) }))}</span>`
      + `${read(H.refresh, "data-cell-log-refresh", t("cwLogTailRefresh"))}</div>${lines}`
      + `${growing ? `<p class="cw-tail-note">${escapeHtml(t("cwLogTailLive"))}</p>` : ""}</section>`;
  }

  /** Reads the log of cell `cellId` — the run `run`, or the newest — and draws the section again where it stands in `doc`. A
   *  read already under way is not doubled. The words of a refusal are the scout's or the controller's, shown as they came. */
  async load(cellId, { run = "", doc = globalThis.document } = {}) {
    const k = String(cellId);
    const before = this.of(k);
    if (before.busy) return before;
    this.cells.set(k, { ...before, busy: true, state: before.state === "ok" ? "ok" : "loading" });
    this.paint(doc, k);
    const query = new URLSearchParams({ cell: k, ...(run ? { run } : {}) });
    let next;
    try {
      const got = await this.call(`/api/cell-log?${query}`);
      next = got?.ok
        ? { state: "ok", run: String(got.run || ""), runs: Array.isArray(got.runs) ? got.runs : [],
            lines: Array.isArray(got.lines) ? got.lines.map(String) : [], error: "" }
        : { ...before, state: "error", error: String(got?.error || t("cwLogTailNone")) };
    } catch (e) {
      next = { ...before, state: "error", error: String(e?.message || e) };
    }
    this.cells.set(k, { ...next, at: this.now(), busy: false });
    this.paint(doc, k);
    return this.of(k);
  }

  /** Draws the section of `cellId` again in `doc`, keeping the reader where they were: at the end when they were there (a tail
   *  is read at its end), at their line when they had scrolled up. */
  paint(doc, cellId) {
    const esc = globalThis.CSS?.escape ? globalThis.CSS.escape(cellId) : String(cellId).replace(/["\\]/g, "\\$&");
    const view = doc?.querySelector?.(`[data-cell-log-view="${esc}"]`);
    if (!view) return;
    const old = view.querySelector?.(".cw-tail-lines");
    const atEnd = !old || old.scrollTop + old.clientHeight >= old.scrollHeight - 4;
    const top = old ? old.scrollTop : 0;
    view.outerHTML = this.html(cellId, { live: view.dataset?.cellLogLive === "1" });
    const lines = doc.querySelector?.(`[data-cell-log-view="${esc}"] .cw-tail-lines`);
    if (lines) lines.scrollTop = atEnd ? lines.scrollHeight : top;
  }

  /** On the poll's tick: the log shown in the open window is read again — once, when its tab opened and it was never read; every
   *  EVERY_MS while the cell runs and its present run is chosen. Nothing when no window shows a log. */
  tick(doc = globalThis.document) {
    const view = doc?.querySelector?.('.fold-slot.open > .cell-window [data-cell-window-panel="log"]:not([hidden]) [data-cell-log-view]');
    if (!view) return null;
    const cellId = view.dataset.cellLogView;
    const s = this.of(cellId);
    if (s.busy) return null;
    if (s.state === "idle") return this.load(cellId, { doc });
    const growing = view.dataset.cellLogLive === "1" && s.state === "ok" && CellLog.present(s.run);
    if (!growing || this.now() - s.at < CellLog.EVERY_MS) return null;
    return this.load(cellId, { run: s.run, doc });
  }

  /** Once, on the document (the lanes are repainted wholesale): the buttons that read, the choice of a run, and the Log tab —
   *  the log is read when the tab opens, not at the next tick. */
  bind(doc = globalThis.document) {
    if (this.bound || !doc) return;
    this.bound = true;
    doc.addEventListener("click", (e) => this.onClick(e, doc));
    doc.addEventListener("change", (e) => this.onChange(e, doc));
  }

  onClick(e, doc = globalThis.document) {
    const target = e.target;
    const read = target?.closest?.("[data-cell-log-show], [data-cell-log-refresh]");
    if (read) {
      const cellId = read.dataset.cellLogShow || read.dataset.cellLogRefresh;
      return this.load(cellId, { run: read.dataset.cellLogRefresh ? this.of(cellId).run : "", doc });
    }
    // The Log tab, or the band's way to it (a failed cell's "Log"): the window's data-t-id is its cell's id.
    const tab = target?.closest?.('[data-cell-window-tab="log"]');
    const win = tab?.closest?.(".cell-window");
    if (win && this.of(win.dataset.tId).state === "idle" && win.querySelector?.("[data-cell-log-view]")) {
      return this.load(win.dataset.tId, { doc });
    }
    return null;
  }

  onChange(e, doc = globalThis.document) {
    const pick = e.target?.closest?.("[data-cell-log-run]");
    if (!pick) return null;
    return this.load(pick.dataset.cellLogRun, { run: pick.value, doc });
  }
}

export const CELL_LOG = new CellLog();
