// The banner over the board when a fresh llama.cpp build crashes cells.
import { t } from "./i18n.js";
import { topology } from "./state.js";
import { openRestoreBuildModal } from "./system-panels.js";
import { $, api, escapeHtml } from "./utils.js";

/**
 * One row per machine whose fresh llama.cpp build crashes its cells. The
 * verdict is the machine's own: this controller keeps its own
 * (topology.llamaSuspect), a scout keeps its machine's and reports it
 * (topology.hostSuspects, scout 2.6+). A row offers the newest archived
 * build of another commit — restored only after the same confirmation the
 * System builds list uses, never by itself — and a dismissal the machine
 * remembers for that build.
 *
 * A row the operator acted on in this page goes at once, before the
 * server's next word, and stays gone while its incident is the same one
 * (its key: machine, build, candidate, minute of the last crash).
 */
export class LlamaSuspectBanner {
  constructor() {
    this.shown = "";        // the keys of the rows on screen
    this.done = new Set();  // the keys the operator acted on in this page
  }

  rows(topo) {
    const all = [];
    const own = topo?.llamaSuspect || {};
    if (own.suspect) all.push({ ...own, hostId: "", name: "" });
    for (const row of topo?.hostSuspects || []) {
      if (row?.suspect) all.push(row);
    }
    return all
      .map((row) => ({ ...row, key: `${row.hostId}|${row.currentCommit}:${row.builtAt}:`
        + `${row.restoreCandidate?.id || ""}:${Math.floor((row.lastSeenAt || 0) / 60)}` }))
      .filter((row) => !this.done.has(row.key));
  }

  message(row) {
    const n = String(row.crashes15m || 0);
    return row.hostId
      ? t("llamaSuspectMsgHost").replace("{host}", row.name || row.hostId).replace("{n}", n)
      : t("llamaSuspectMsg").replace("{n}", n);
  }

  rowHtml(row) {
    const cand = row.restoreCandidate || null;
    const candLabel = cand ? String(cand.version || cand.id).replace("version: ", "b") : "";
    const lastSeen = row.lastSeenAt ? ` · ${new Date(row.lastSeenAt * 1000).toLocaleTimeString()}` : "";
    return `<div class="llama-suspect-row" data-t="board-llama-suspect-row" data-t-id="${escapeHtml(row.hostId || "controller")}">`
      + `<span class="llama-suspect-msg">⚠ ${escapeHtml(this.message(row))}${escapeHtml(lastSeen)}</span>`
      + (cand ? `<button type="button" class="llama-suspect-restore" data-suspect-restore="${escapeHtml(row.key)}">`
        + `${escapeHtml(t("llamaSuspectRestore"))} ${escapeHtml(candLabel)}</button>` : "")
      + `<button type="button" class="llama-suspect-dismiss" data-suspect-dismiss="${escapeHtml(row.key)}">`
      + `${escapeHtml(t("llamaSuspectDismiss"))}</button></div>`;
  }

  render(el = $("llamaSuspectBanner"), topo = topology) {
    if (!el) return;
    const rows = this.rows(topo);
    if (!rows.length) {
      // Emptied, not only hidden: a check that looks a row up by its data-t
      // must not find one nobody can see.
      el.innerHTML = "";
      el.hidden = true;
      this.shown = "";
      return;
    }
    const shown = rows.map((row) => row.key).join("\n");
    if (shown === this.shown && !el.hidden) return;   // already on screen
    this.shown = shown;
    el.innerHTML = rows.map((row) => this.rowHtml(row)).join("");
    el.hidden = false;
    const byKey = new Map(rows.map((row) => [row.key, row]));
    el.querySelectorAll("[data-suspect-restore]").forEach((btn) => {
      btn.addEventListener("click", () => this.restore(byKey.get(btn.getAttribute("data-suspect-restore")), el, topo));
    });
    el.querySelectorAll("[data-suspect-dismiss]").forEach((btn) => {
      btn.addEventListener("click", () => this.dismiss(byKey.get(btn.getAttribute("data-suspect-dismiss")), el, topo));
    });
  }

  // The banner did its job; the confirmation takes over.
  restore(row, el, topo) {
    if (!row) return;
    this.forget(row, el, topo);
    const cand = row.restoreCandidate || null;
    openRestoreBuildModal(String(cand?.id || ""), cand,
      row.hostId ? { hostId: row.hostId, name: row.name, version: row.llamaBinaryVersion || "" } : null);
  }

  // The machine remembers it for this build; its next build starts clean.
  dismiss(row, el, topo) {
    if (!row) return;
    this.forget(row, el, topo);
    const [path, body] = row.hostId
      ? ["/api/fleet/llama-suspect-dismiss", { hostId: row.hostId }]
      : ["/api/llamacpp/suspect-dismiss", {}];
    api(path, { method: "POST", body: JSON.stringify(body) }).catch(() => {});
  }

  forget(row, el, topo) {
    this.done.add(row.key);
    this.shown = "";
    this.render(el, topo);
  }
}

export const SUSPECT_BANNER = new LlamaSuspectBanner();
