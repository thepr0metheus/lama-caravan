// A cell's note in its row on the machine's page (the owner, 2026-11-03: "I want to be able to sign the cells, to give them a comment of my own, visible here").
// The note is the one the cell always had: the controller keeps it in the cell's slot (fleet/server_cells.rs set_note, `POST /api/topology/server-slot/note`)
// and the topology carries all of them as `cellNotes`, "host:port" → words; the card on the main board and the cell's window said it, the row on the
// machine's page did not. Here it is drawn in the row, and asked for from there. One note, read and written by every place that shows it.
import { appPrompt } from "./dialogs.js";
import { t } from "./i18n.js";
import { topology } from "./state.js";
import { api, escapeHtml, toast } from "./utils.js";

export class CellNote {
  /** The longest note the controller keeps (set_note), as the question says it; the cell's details take as many (their box's maxlength). */
  static MOST = 280;

  /** The note of the cell on `port` of machine `hostId`, as the page holds it now; "" for none. */
  static of(hostId, port) {
    const said = (topology?.cellNotes || {})[`${hostId}:${port}`];
    return typeof said === "string" ? said.trim() : "";
  }

  /** The note as a line of the cell's row: its words after the 💬 the card has, one line however long, the whole of it in the tip; a press asks for
   *  it again. Nothing for a cell with none. */
  static lineHtml(hostId, port) {
    const note = CellNote.of(hostId, port);
    if (!note) return "";
    const id = escapeHtml(String(port));
    return `<button type="button" class="machine-model-note" data-cell-note="${escapeHtml(String(hostId))}:${id}" data-machine-own`
      + ` data-t="machine-model-note" data-t-id="${id}" title="${escapeHtml(`${note}\n\n${t("cellNoteChange")}`)}">💬 ${escapeHtml(note)}</button>`;
  }

  /** The row's ✎ for a cell with no note yet: one click from the row, as the owner looks at it. */
  static addHtml(hostId, port) {
    if (CellNote.of(hostId, port)) return "";
    const id = escapeHtml(String(port));
    const words = escapeHtml(t("cellNoteAdd"));
    return `<button type="button" class="ui-btn ui-btn--icon machine-model-note-add" data-cell-note="${escapeHtml(String(hostId))}:${id}" data-machine-own`
      + ` data-t="machine-model-note-add" data-t-id="${id}" title="${words}" aria-label="${words}">✎</button>`;
  }

  /** Asks for the cell's note — its present words in the box — and keeps what was typed; empty words take it off. Words that did not change send nothing. */
  static async edit(hostId, port, refresh) {
    const current = CellNote.of(hostId, port);
    const typed = await appPrompt(t("cellNotePrompt", { port: String(port), most: String(CellNote.MOST) }),
      { value: current, placeholder: t("cellNotePlaceholder"), confirmLabel: t("cellNoteSave") });
    if (typed === null || typed === undefined) return;
    const note = String(typed).trim();
    if (note === current) return;
    try {
      await api("/api/topology/server-slot/note", { method: "POST", body: JSON.stringify({ hostId, port: Number(port), note }) });
      toast(t(note ? "cellNoteSaved" : "cellNoteRemoved"));
    } catch (err) {
      toast(err.message);
    }
    await refresh();
  }

  /** Wires every note and ✎ under `root` (the page binds again after each redraw): a click asks for the note — the asking's promise is the handler's answer,
   *  for whoever waits on it. */
  static bind(root, refresh) {
    root?.querySelectorAll("[data-cell-note]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        const [hostId, port] = String(btn.dataset.cellNote || "").split(/:(?=[^:]*$)/);
        return hostId && port ? CellNote.edit(hostId, port, refresh) : null;
      });
    });
  }
}
