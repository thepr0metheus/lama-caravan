// The strip under the kanban (the owner, 2026-10-13: "hide part of it, show it on hover", and of the
// three mockups he chose "details in a strip below"): what the board's trace points at — a card under the
// pointer, or one pinned by a click — said in one place: its name, the route that lights across the four
// columns, and its details. The cards keep a name and what is news (⚠, off, serving); the rest stands here,
// where it covers no neighbour and moves no cable.
//
// The board gives the readings (`reader`, PoolBoard.dockReader) and this draws them; it decides nothing.
// A trace key is the board's own (PoolBoard.path): client:<port>, set:<id>, setpool:<set>/<pool>,
// pool:<id>, row:<pool>/<row>, model:<key>.
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";

export class PoolDock {
  // A trace key → what the strip is about: the kind of card, and its id. A row says its pool, a set's
  // row its set. A key the board does not know says nothing: the strip stays empty rather than guess.
  static aim(key) {
    const [prefix, ...rest] = String(key || "").split(":");
    const id = rest.join(":");
    if (!id) return null;
    if (prefix === "client") return { kind: "client", id };
    if (prefix === "set") return { kind: "set", id };
    if (prefix === "setpool") return { kind: "set", id: id.split("/")[0] };
    if (prefix === "pool") return { kind: "pool", id };
    if (prefix === "row") return { kind: "pool", id: id.split("/")[0] };
    if (prefix === "model") return { kind: "model", id };
    return null;
  }

  // The strip drawn from a reader — {aim, pinned, name, subHtml, route, detailsHtml}. With no reader there is no
  // strip: the board does not ask (PoolBoard.paintDock), and hides the one it has (the owner, 2026-10-14: "do not
  // show the bottom strip when nothing is pointed at or selected"; it was a line that said what to do). A level
  // of the route with no names says so (—): a set no client calls is not a blank.
  html(reader) {
    const route = reader.route.map(({ label, names }) => {
      const said = names.join(", ");
      return `<div><dt>${escapeHtml(label)}</dt><dd title="${escapeHtml(said)}">${said ? escapeHtml(said) : "—"}</dd></div>`;
    }).join("");
    return `<div class="pb-dock-id" data-t="pb-dock-id">`
      + `<b class="pb-dock-name" title="${escapeHtml(reader.name)}">${escapeHtml(reader.name)}</b>`
      + `<span class="pb-dock-sub">${reader.subHtml}</span>`
      + `<dl class="pb-route" data-t="pb-route">${route}</dl>`
      + `<span class="pb-dock-foot" data-t="pb-dock-foot">${escapeHtml(t(reader.pinned ? "pbDockPinned" : "pbDockPin"))}</span>`
      + `</div><div class="pb-dock-body" data-t="pb-dock-body">${reader.detailsHtml}</div>`;
  }

  // What the strip is about, for its `data-t-state`.
  static state(reader) {
    return reader ? reader.aim.kind : "empty";
  }
}
