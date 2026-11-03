// The window a cell is started with — the browser's copy of AskedWindow in rust/crates/rules/src/cell_config.rs, held to it by
// one table of cases (contract/asked_window.json; rust/crates/admin/tests/contract.rs and test_js_asked_window.py run it).
// The form's estimate, the cell window's plan and the add-model wizard count the KV cache of the window the start will ask
// for; an empty field asks for the window the model was trained for (the owner, 2026-10-26), and drawn as 0 it read as a
// cell that keeps no cache at all.
export class AskedWindow {
  /** The number the field says; an empty field — or "0", llama.cpp's "from the model" — the window the model was trained
   *  for; null when neither is known or the field is not a number. */
  static of(field, trained) {
    if (AskedWindow.empty(field)) return AskedWindow.positive(trained);
    const text = String(field).trim();
    if (!/^\d+$/.test(text)) return null;
    return AskedWindow.positive(text);
  }

  /** Whether the field asks for the trained window: left empty, or "0". */
  static empty(field) {
    return ["", "0"].includes(field === null || field === undefined ? "" : String(field).trim());
  }

  /** A size, or null: zero, rubbish and booleans are absences. */
  static positive(value) {
    if (typeof value === "boolean" || value === null || value === undefined) return null;
    const n = Number(value);
    return Number.isInteger(n) && n > 0 ? n : null;
  }
}
