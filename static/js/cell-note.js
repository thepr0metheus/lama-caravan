// A cell's note in its row on the machine's page (the owner, 2026-11-03: "I want to be able to sign the cells, to give them a comment of my own, visible here").
// The note is the one the cell always had: the controller keeps it in the cell's slot (fleet/server_cells.rs set_note, `POST /api/topology/server-slot/note`
// with the cell's id) and the topology carries all of them as `cellNotes`, cellId → words; the card on the main board and the cell's window said it, the row
// on the machine's page did not. Here it is drawn in the row, and asked for from there. One note, read and written by every place that shows it.
//
// A cell is known by its id alone: it holds a port only while it runs, so the note is neither kept nor asked for by one, and the question names no port.
import { appPrompt } from "./dialogs.js";
import { t } from "./i18n.js";
import { topology } from "./state.js";
import { api, escapeHtml, toast } from "./utils.js";

export class CellNote {
  /** The longest note the controller keeps (set_note), as the question says it; the cell's details take as many (their box's maxlength). */
  static MOST = 280;

  /** The note of cell `cellId`, as the page holds it now; "" for none. */
  static of(cellId) {
    const said = (topology?.cellNotes || {})[String(cellId)];
    return typeof said === "string" ? said.trim() : "";
  }

  /** What a press of the line or of the ✎ is read back from (bind): the cell's id, and the name the row gives it — the question names the cell by it. */
  static attrs(cellId, name) {
    const shown = String(name || "").trim();
    return `data-cell-note="${escapeHtml(String(cellId))}"${shown ? ` data-cell-note-name="${escapeHtml(shown)}"` : ""} data-machine-own`;
  }

  /** The note as a line of the cell's row: its words after the 💬 the card has, one line however long, the whole of it in the tip; a press asks for
   *  it again. Nothing for a cell with none. `name` is what the row calls the cell. */
  static lineHtml(cellId, name = "") {
    const note = CellNote.of(cellId);
    if (!note) return "";
    const id = escapeHtml(String(cellId));
    return `<button type="button" class="machine-model-note" ${CellNote.attrs(cellId, name)}`
      + ` data-t="machine-model-note" data-t-id="${id}" title="${escapeHtml(`${note}\n\n${t("cellNoteChange")}`)}">💬 ${escapeHtml(note)}</button>`;
  }

  /** The row's ✎ for a cell with no note yet: one click from the row, as the owner looks at it. */
  static addHtml(cellId, name = "") {
    if (CellNote.of(cellId)) return "";
    const id = escapeHtml(String(cellId));
    const words = escapeHtml(t("cellNoteAdd"));
    return `<button type="button" class="ui-btn ui-btn--icon machine-model-note-add" ${CellNote.attrs(cellId, name)}`
      + ` data-t="machine-model-note-add" data-t-id="${id}" title="${words}" aria-label="${words}">✎</button>`;
  }

  /** Asks for the note of cell `cellId` — its present words in the box, the cell named as the row names it (`name`), by its id when the row gives
   *  none — and keeps what was typed; empty words take it off. Words that did not change send nothing. */
  static async edit(cellId, refresh, { name = "" } = {}) {
    const id = String(cellId);
    const current = CellNote.of(id);
    const typed = await appPrompt(t("cellNotePrompt", { cell: String(name || "").trim() || id, most: String(CellNote.MOST) }),
      { value: current, placeholder: t("cellNotePlaceholder"), confirmLabel: t("cellNoteSave") });
    if (typed === null || typed === undefined) return;
    const note = String(typed).trim();
    if (note === current) return;
    try {
      await api("/api/topology/server-slot/note", { method: "POST", body: JSON.stringify({ cellId: id, note }) });
      toast(t(note ? "cellNoteSaved" : "cellNoteRemoved"));
    } catch (err) {
      toast(err.message);
    }
    await refresh();
  }

  /** Wires every note and ✎ under `root` (the page binds again after each redraw): a click asks for the note — the asking's promise is the handler's answer,
   *  for whoever waits on it. A button that names no cell asks nothing. */
  static bind(root, refresh) {
    root?.querySelectorAll("[data-cell-note]").forEach((btn) => {
      btn.addEventListener("click", (event) => {
        event.stopPropagation();
        const cellId = String(btn.dataset.cellNote || "");
        return cellId ? CellNote.edit(cellId, refresh, { name: btn.dataset.cellNoteName || "" }) : null;
      });
    });
  }
}
