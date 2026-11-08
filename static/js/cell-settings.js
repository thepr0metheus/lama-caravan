// A cell's settings edited in its window (1.3.625): the Settings tab lists the fields of a llama.cpp cell by the dialog's own
// tabs, with a search and "only those set", and the Memory tab draws the placement map of the cards and RAM. Both edit the cell
// editor's form itself (remote-cells.js CellForm) — filled for the cell without its dialog — so the checks, the map's arithmetic
// and the command the cell will run stay the dialog's, in one place; what is not applied yet is said at the window's foot, with
// Discard and Apply (the dialog's Apply).
//
// One form holds one cell at a time. Edits not applied are let go only when the operator says so: before the form is filled for
// another cell, from its window or from a dialog; the dialog of the cell itself shows them as they stand. The board repaints the
// lane wholesale, so what is chosen here — the cell, the search, the group — is kept here, and the map is drawn again into the
// Memory tab after every repaint (remount).
//
// A cell is held by its key: its id (cellId) — the window's data-t-id — or, for a cell the new-cell wizard has not made yet, the
// key the wizard and the form hold it under. The form is asked by that key alone (CellForm.holds, fill): a cell has a port only
// while it runs, so none is read out of a key here.
import { CellWindow } from "./cell-window.js";
import { advancedGroups, advancedTabDefs, fieldChoices, toggleFields } from "./constants.js";
import { fieldHelp, t } from "./i18n.js";
import { escapeHtml } from "./utils.js";

export class CellSettings {
  /** The data-t names of the editor (docs/testability.md); data-t-id = the cell's key (its id), a group, a field or the Memory
   *  tab's open button adds ":<its id>". The editor's and the map's data-t-state say idle (the form holds another cell, or none) or open —
   *  the map's says none for a cell with no map; a field's says set, unset or changed; the foot's says dirty or busy. */
  static HOOKS = {
    view: "cell-settings", open: "cell-settings-open", query: "cell-settings-query", only: "cell-settings-only",
    group: "cell-settings-group", field: "cell-settings-field", dirty: "cell-window-dirty", apply: "cell-window-apply",
    discard: "cell-window-discard", place: "cell-window-place", star: "cell-settings-star",
  };
  /** How many names of the fields not applied the foot says before "and N more". */
  static NAMED = 4;

  /** The dialog's tabs (constants.js advancedTabDefs), each with the fields of its groups, in their order; EXTRA_ARGS — the
   *  dialog's escape hatch for any flag of llama-server — closes the first. */
  static groups() {
    const byTitle = new Map(advancedGroups.map((g) => [g.titleKey, g.fields]));
    return advancedTabDefs.map((tab, i) => ({
      key: tab.key, fields: [...tab.groups.flatMap((g) => byTitle.get(g) || []), ...(i === 0 ? ["EXTRA_ARGS"] : [])],
    }));
  }

  /** The first sentence of a field's help: what the row says under its name (the whole help is its tip). A latin stop ends
   *  it before a space ("v1.5" does not); the stops of Chinese, Japanese, Hindi and Urdu stand with no space after them. */
  static note(help) {
    const text = String(help || "").trim();
    const m = text.match(/^(.+?(?:[.!?](?=\s|$)|[。！？।۔]))/);
    return m ? m[1] : text;
  }

  /** The fields whose values differ between two readings of the form. */
  static changed(a, b) {
    const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
    return [...keys].filter((k) => String(a?.[k] ?? "") !== String(b?.[k] ?? "")).sort();
  }

  static css(value) {
    return globalThis.CSS?.escape ? globalThis.CSS.escape(value) : String(value).replace(/["\\]/g, "\\$&");
  }

  /** Draws with `paint` and gives the typing back: a field of the editor that had the focus gets it again, caret and all, when
   *  the drawing replaced it. */
  static keepFocus(doc, paint) {
    const el = doc?.activeElement;
    const id = el?.id && el.closest?.("[data-cell-settings-view]") ? el.id : "";
    const at = id && typeof el.selectionStart === "number" ? [el.selectionStart, el.selectionEnd] : null;
    paint();
    if (!id) return;
    const again = doc.getElementById?.(id);
    if (!again || again === el) return;
    again.focus?.({ preventScroll: true });
    if (at && typeof again.setSelectionRange === "function") again.setSelectionRange(at[0], at[1]);
  }

  constructor({ help = fieldHelp } = {}) {
    this.help = help;
    // Given at bind: the form (remote-cells.js CellForm), the page's confirm (dialogs.js appConfirm) and the starred fields
    // (favorites.js: one list for the dialog's Favorites tab, these rows and the wizard's main fields).
    this.form = null;
    this.confirm = async () => false;
    this.favorites = { list: () => [], toggle: async () => {} };
    // The cell the form is filled with for its window, the config it was filled with, and what the form says now.
    this.key = "";
    this.base = {};
    this.values = {};
    this.query = "";
    this.onlySet = true;
    this.group = "";
    this.busy = false;
    this.writing = false;
    this.bound = false;
  }

  /** True while the form holds cell `key` for its window. */
  holds(key) {
    if (!this.key || this.key !== String(key) || !this.form) return false;
    return this.form.holds(this.key);
  }

  value(field) {
    return String(this.values[field] ?? "");
  }

  /** The fields whose value differs from what the form was filled with: what Apply would save. */
  dirty() {
    return CellSettings.changed(this.base, this.values);
  }

  /** A field the search finds: by its name or its help, whatever is set. */
  matches(field, query) {
    return field.toLowerCase().includes(query) || this.help(field).toLowerCase().includes(query);
  }

  /** The fields one group shows now: those the search finds in it, else those set ("only those set") or all. */
  shown(group) {
    const q = this.query.trim().toLowerCase();
    if (q) return group.fields.filter((f) => this.matches(f, q));
    return group.fields.filter((f) => !this.onlySet || this.value(f) !== "");
  }

  /** The first group with a field set: where the editor opens. */
  firstGroup() {
    const groups = CellSettings.groups();
    return (groups.find((g) => g.fields.some((f) => this.value(f) !== "")) || groups[0]).key;
  }

  // ── what the form says, and what it is told ─────────────────────────────────────────────────────────────

  /** Fills the form with cell `key`'s saved config, unless it holds it already: edits of another cell not applied are let go
   *  only when the operator says so. True when the form holds `key` after it. The form fills nothing for a key of no cell the
   *  board shows (CellForm.fill says false) and stays as it was: so does what is kept here. */
  async open(key, doc = globalThis.document) {
    const k = String(key);
    if (!this.form) return false;
    if (this.holds(k)) {
      this.mountMap(doc);
      return true;
    }
    if (!(await this.leave(k, doc))) return false;
    const was = { key: this.key, query: this.query, onlySet: this.onlySet, group: this.group };
    // The key first: the filling is heard back at once as "filled" (refill), which reads the form for the cell held.
    this.key = k;
    this.query = "";
    this.onlySet = true;
    this.group = "";
    if (!this.form.fill(k, { hidden: true })) {
      Object.assign(this, was);
      return false;
    }
    // The window of the cell left keeps no editor of the form it no longer holds: drawn idle, its fields cannot write here.
    if (was.key && was.key !== k) this.paintAll(doc, was.key);
    return this.holds(k);
  }

  /** The form filled for cell `key` by another hand — the new-cell wizard (add-model.js) — edited here as it stands: what it
   *  holds now is the start, and what is typed after it is what the wizard will save. `onlySet`: whether the list opens on the
   *  fields that hold a value only. False when the form holds another cell. */
  adopt(key, { onlySet = false } = {}, doc = globalThis.document) {
    const k = String(key);
    if (!k || !this.form?.holds(k)) return false;
    const was = this.key;
    this.key = k;
    this.query = "";
    this.onlySet = !!onlySet;
    this.base = { ...this.form.read() };
    this.values = { ...this.base };
    this.group = this.firstGroup();
    if (was && was !== k) this.paintAll(doc, was);
    return true;
  }

  /** The wizard closed: cell `key` is no one's to keep here, and what was typed for it is let go. */
  release(key) {
    if (!this.key || this.key !== String(key)) return false;
    this.key = "";
    this.base = {};
    this.values = {};
    return true;
  }

  /** The form was filled — by this window or by a dialog: for the cell held, what it says is the new start; for another, the
   *  edits here are gone (the operator let them go, or there were none) and the window offers to open its cell again. */
  refill(doc = globalThis.document) {
    if (!this.key) return;
    if (this.holds(this.key)) {
      this.base = { ...this.form.read() };
      this.values = { ...this.base };
      if (!this.group) this.group = this.firstGroup();
    } else {
      this.base = {};
      this.values = {};
    }
    this.paintAll(doc);
  }

  /** The form was saved — by the window's Apply or the dialog's: the config sent is what the cell has now. A field typed in
   *  while the save was on its way stays not applied. */
  settle(doc = globalThis.document, saved = null) {
    if (!this.holds(this.key)) return;
    this.values = { ...this.form.read() };
    this.base = { ...(saved || this.values) };
    this.paint(doc);
    this.paintFoot(doc);
  }

  /** The keeper's question (CellForm.keeps): the dialog of cell `key` shows the edits kept here as they stand. */
  keeps(key) {
    return !!this.key && this.key === String(key) && this.holds(this.key) && this.dirty().length > 0;
  }

  /** The keeper's other question (CellForm.mayFill): may the form be filled for cell `key` now? Whichever cell that is — another,
   *  or this one afresh — the edits here not applied would go: not without the operator's word. The question names the cell
   *  whose edits they are as its window is titled (CellWindow.titleIn), by its key when no window of it is drawn. */
  async leave(key, doc = globalThis.document) {
    if (!this.holds(this.key) || !this.dirty().length) return true;
    const cell = CellWindow.titleIn(doc, this.key) || this.key;
    return !!(await this.confirm(t("cwDirtyLeave", { cell }), { danger: false }));
  }

  /** Writes one field into the form, as the editor's input says it, and says at the foot what is not applied. */
  set(field, value, doc = globalThis.document) {
    if (!this.holds(this.key)) return false;
    this.writing = true;
    try {
      this.form.set(field, value);
    } finally {
      this.writing = false;
    }
    const before = this.values;
    this.values = { ...this.form.read() };
    const row = doc?.querySelector?.(`[data-t="${CellSettings.HOOKS.field}"][data-t-id="${CellSettings.css(`${this.key}:${field}`)}"]`);
    if (row?.dataset) row.dataset.tState = this.rowState(field);
    // A field the form's own listeners wrote as well (a hint, a companion) is drawn again; the one typed in keeps its caret.
    if (CellSettings.changed(before, this.values).some((f) => f !== field)) this.paintFields(doc);
    this.paintFoot(doc);
    this.mountMap(doc);
    return true;
  }

  /** The form changed by another hand — the map, the dialog — : what it says now, drawn. */
  sync(doc = globalThis.document) {
    if (this.writing || !this.holds(this.key)) return false;
    const before = this.values;
    this.values = { ...this.form.read() };
    if (!CellSettings.changed(before, this.values).length) return false;
    this.paintFields(doc);
    this.paintFoot(doc);
    this.mountMap(doc);
    return true;
  }

  /** The dialog's Apply: its checks, its question, its save (heard back as "saved"). True when saved. */
  async apply(doc = globalThis.document) {
    if (this.busy || !this.holds(this.key)) return false;
    this.busy = true;
    this.paintFoot(doc);
    let ok = false;
    try {
      ok = !!(await this.form.save());
    } finally {
      this.busy = false;
    }
    this.paintFoot(doc);
    return ok;
  }

  /** Back to the saved config: the form filled again from it (heard back as "filled"). False when the form fills nothing — a
   *  cell the board no longer shows: what is not applied stays so, and is said so at the foot. */
  discard() {
    if (this.busy || !this.holds(this.key)) return false;
    return !!this.form.fill(this.key, { hidden: true });
  }

  // ── the editor ──────────────────────────────────────────────────────────────────────────────────────

  rowState(field) {
    if (String(this.base[field] ?? "") !== this.value(field)) return "changed";
    return this.value(field) !== "" ? "set" : "unset";
  }

  fieldHtml(field) {
    const k = escapeHtml(this.key);
    const help = this.help(field);
    const id = `cws-${field}`;
    const choices = fieldChoices[field];
    let input;
    if (toggleFields.includes(field)) {
      // Drawn as the form draws the box: an optional toggle the config does not state shows the server's default, and says so.
      input = `<input type="checkbox" id="${id}" class="cws-toggle" data-cell-settings-field="${field}"`
        + `${this.form?.checked?.(field) ? " checked" : ""}>`
        + `${this.value(field) === "" ? `<span class="cws-default">${escapeHtml(t("cwDefault"))}</span>` : ""}`;
    } else {
      // The window field says the most the model takes, as the dialog's does (form.js modelWindowFor): the owner's word of 2026-10-26.
      const most = field === this.form?.windowField?.() ? Number(this.form?.modelWindow?.() || 0) : 0;
      input = `<input type="text" id="${id}" class="cws-input" data-cell-settings-field="${field}" value="${escapeHtml(this.value(field))}"`
        + ` placeholder="${escapeHtml(most ? String(most) : t("cwSetUnset"))}" autocomplete="off" spellcheck="false"`
        + `${this.form?.locked?.(field) ? " readonly" : ""}${choices ? ` list="${id}-choices"` : ""}>`
        + (choices ? `<datalist id="${id}-choices">${choices.map((c) => `<option value="${escapeHtml(c)}"></option>`).join("")}</datalist>` : "");
    }
    // The star brings the field to the dialog's Favorites and the wizard's main fields; EXTRA_ARGS is always there.
    const starred = field === "EXTRA_ARGS" || this.favorites.list().includes(field);
    const star = field === "EXTRA_ARGS" ? ""
      : `<button type="button" class="cws-star${starred ? " on" : ""}" data-cell-settings-star="${field}" aria-pressed="${starred}"`
        + ` title="${escapeHtml(t("favStarTip"))}" aria-label="${escapeHtml(t("favStarTip"))}"`
        + ` data-t="${CellSettings.HOOKS.star}" data-t-id="${k}:${field}">★</button>`;
    return `<div class="cws-row" data-t="${CellSettings.HOOKS.field}" data-t-id="${k}:${field}" data-t-state="${this.rowState(field)}">`
      + `<div class="cws-name">${star}<label for="${id}"${help ? ` title="${escapeHtml(help)}"` : ""}>${field}</label>`
      + `${help ? `<span class="cws-note">${escapeHtml(CellSettings.note(help))}</span>` : ""}</div>`
      + `<div class="cws-value">${input}</div></div>`;
  }

  /** The groups and the fields — what a search, "only those set" or a group chosen draws again. */
  bodyHtml() {
    const k = escapeHtml(this.key);
    const groups = CellSettings.groups();
    const chosen = groups.find((g) => g.key === this.group) || groups[0];
    const searching = this.query.trim() !== "";
    const nav = groups.map((g) => {
      const on = !searching && g.key === chosen.key;
      return `<button type="button" class="cws-group${on ? " on" : ""}" data-cell-settings-group="${g.key}"`
        + ` data-t="${CellSettings.HOOKS.group}" data-t-id="${k}:${g.key}"${on ? ' aria-current="true"' : ""}>`
        + `<span>${escapeHtml(t(g.key))}</span><span class="cws-count">${this.shown(g).length}</span></button>`;
    }).join("");
    const fields = searching ? groups.flatMap((g) => this.shown(g)) : this.shown(chosen);
    const title = searching ? t("cwSetFound", { n: String(fields.length) }) : t(chosen.key);
    const rows = fields.length ? fields.map((f) => this.fieldHtml(f)).join("")
      : `<p class="cw-empty">${escapeHtml(t(searching ? "cwSetNoMatch" : "cwSetNone"))}</p>`;
    return `<nav class="cws-groups" aria-label="${escapeHtml(t("cwSetGroups"))}">${nav}</nav>`
      + `<div class="cws-fields"><h4 class="cw-sec-title">${escapeHtml(title)}</h4>${rows}</div>`;
  }

  /** The Settings tab's editor of cell `key`: its fields when the form holds it, else a way to open them here. "" for a cell
   *  whose settings are not the llama.cpp fields, or that may not be configured now — the window keeps its summary then. */
  html(key, { llama = false, editable = false } = {}) {
    if (!llama || !editable) return "";
    const k = escapeHtml(String(key));
    const H = CellSettings.HOOKS;
    if (!this.holds(key)) {
      return `<section class="cw-sec cws" data-cell-settings-view="${k}" data-t="${H.view}" data-t-id="${k}" data-t-state="idle">`
        + `<p class="cw-lead">${escapeHtml(t("cwSetLead"))}</p><div class="cw-buttons"><button type="button" class="cw-btn primary"`
        + ` data-cell-settings-open="${k}" data-t="${H.open}" data-t-id="${k}">${escapeHtml(t("cwSetOpen"))}</button></div></section>`;
    }
    const set = CellSettings.groups().flatMap((g) => g.fields).filter((f) => this.value(f) !== "").length;
    return `<section class="cw-sec cws" data-cell-settings-view="${k}" data-t="${H.view}" data-t-id="${k}" data-t-state="open">`
      + `<div class="cws-top"><input type="search" id="cws-query" class="cws-query" data-cell-settings-query="${k}" data-t="${H.query}"`
      + ` data-t-id="${k}" value="${escapeHtml(this.query)}" placeholder="${escapeHtml(t("cwSetSearch"))}"`
      + ` aria-label="${escapeHtml(t("cwSetSearch"))}" autocomplete="off" spellcheck="false">`
      + `<label class="cws-only"><input type="checkbox" id="cws-only" data-cell-settings-only="${k}" data-t="${H.only}" data-t-id="${k}"`
      + `${this.onlySet ? " checked" : ""}> ${escapeHtml(t("cwSetOnly", { n: String(set) }))}</label></div>`
      + `<div class="cws-body">${this.bodyHtml()}</div></section>`;
  }

  /** The window's foot of cell `key`: what is not applied, Discard and Apply; empty while nothing is. `running`: the cell keeps
   *  the settings it started with until it restarts, and the foot says so. */
  footHtml(key, { running = false } = {}) {
    if (!this.holds(key)) return "";
    const changed = this.dirty();
    if (!changed.length) return "";
    const k = escapeHtml(String(key));
    const H = CellSettings.HOOKS;
    const named = changed.slice(0, CellSettings.NAMED).join(", ");
    const more = changed.length > CellSettings.NAMED ? ` ${t("cwDirtyMore", { n: String(changed.length - CellSettings.NAMED) })}` : "";
    const busy = this.busy ? " disabled" : "";
    return `<div class="cw-dirty" role="status" data-t="${H.dirty}" data-t-id="${k}" data-t-state="${this.busy ? "busy" : "dirty"}">`
      + `<span class="cw-dirty-text">${escapeHtml(t("cwDirtyText", { fields: named + more }))}`
      + `${running ? ` ${escapeHtml(t("cwDirtyRunning"))}` : ""}</span>`
      + `<button type="button" class="cw-btn" data-cell-window-discard="${k}" data-t="${H.discard}" data-t-id="${k}"${busy}>${escapeHtml(t("cwDirtyDiscard"))}</button>`
      + `<button type="button" class="cw-btn primary" data-cell-window-apply="${k}" data-t="${H.apply}" data-t-id="${k}"${busy}>${escapeHtml(t("cwDirtyApply"))}</button></div>`;
  }

  /** Where the Memory tab of cell `key` draws the placement map: its box while the form holds the cell (mountMap draws it
   *  there), else a way to open it here. "" for a cell whose settings are not the llama.cpp fields, or may not be changed now. */
  placeHtml(key, { llama = false, editable = false } = {}) {
    if (!llama || !editable) return "";
    const k = escapeHtml(String(key));
    const H = CellSettings.HOOKS;
    if (this.holds(key)) {
      return `<div class="cw-place" data-cell-window-place="${k}" data-t="${H.place}" data-t-id="${k}" data-t-state="open">`
        + `<div class="cw-place-map placement-box"></div></div>`;
    }
    return `<div class="cw-place" data-cell-window-place="${k}" data-t="${H.place}" data-t-id="${k}" data-t-state="idle">`
      + `<p class="cw-lead">${escapeHtml(t("cwPlaceLead"))}</p><div class="cw-buttons"><button type="button" class="cw-btn primary"`
      + ` data-cell-settings-open="${k}" data-t="${H.open}" data-t-id="${k}:memory">${escapeHtml(t("cwPlaceOpen"))}</button></div></div>`;
  }

  /** The editor, the foot and the map's place of cell `key`, drawn again as the form now says. */
  paintAll(doc, key = this.key) {
    this.paint(doc, key);
    this.paintFoot(doc, key);
    this.paintPlace(doc, key);
  }

  paint(doc, key = this.key) {
    if (!key) return;
    const view = doc?.querySelector?.(`[data-cell-settings-view="${CellSettings.css(key)}"]`);
    if (view) CellSettings.keepFocus(doc, () => { view.outerHTML = this.html(key, { llama: true, editable: true }); });
  }

  paintFields(doc) {
    const body = doc?.querySelector?.(`[data-cell-settings-view="${CellSettings.css(this.key)}"] .cws-body`);
    if (body) CellSettings.keepFocus(doc, () => { body.innerHTML = this.bodyHtml(); });
  }

  paintFoot(doc, key = this.key) {
    if (!key) return;
    const slot = doc?.querySelector?.(`[data-cell-window-foot="${CellSettings.css(key)}"]`);
    if (slot) slot.innerHTML = this.footHtml(key, { running: slot.dataset?.running === "1" });
  }

  paintPlace(doc, key = this.key) {
    if (!key) return;
    const mount = doc?.querySelector?.(`[data-cell-window-place="${CellSettings.css(key)}"]`);
    if (!mount) return;
    mount.outerHTML = this.placeHtml(key, { llama: true, editable: true });
    if (key === this.key) this.mountMap(doc);
  }

  /** The map drawn from the form into the Memory tab of the cell held, where the board drew its box; a cell with no map —
   *  one on the CPU, or split by rows — says so instead. False when there is no box to draw in. */
  mountMap(doc = globalThis.document) {
    if (!this.holds(this.key)) return false;
    const mount = doc?.querySelector?.(`[data-cell-window-place="${CellSettings.css(this.key)}"]`);
    const box = mount?.querySelector?.(".cw-place-map");
    if (!box) return false;
    const drawn = !!this.form.placeMap(box);
    if (!drawn) box.innerHTML = `<p class="cw-empty">${escapeHtml(t("cwPlaceNoMap"))}</p>`;
    if (mount.dataset) mount.dataset.tState = drawn ? "open" : "none";
    return true;
  }

  /** After the board's repaint (topology-render.js): the map drawn again into the new box. */
  remount(doc = globalThis.document) {
    return this.mountMap(doc);
  }

  /** A field starred or unstarred: the list of the starred is the favorites' (favorites.js), and the rows say it again. */
  async star(field, doc = globalThis.document) {
    await this.favorites.toggle(field);
    this.paintFields(doc);
    return this.favorites.list().includes(field);
  }

  // ── the page ────────────────────────────────────────────────────────────────────────────────────────

  /** Once (the lanes are repainted wholesale): the tabs and buttons that open the settings here, the groups, the search, "only
   *  those set", the fields, Discard and Apply; the form's own edits (the map, the dialog), its filling, saving and closing; and
   *  the keeper's questions the form asks before it is filled or shown. */
  bind(doc = globalThis.document, { form = null, confirm = null, favorites = null } = {}) {
    if (this.bound || !doc) return;
    this.bound = true;
    this.form = form;
    if (confirm) this.confirm = confirm;
    if (favorites) this.favorites = favorites;
    doc.addEventListener("click", (e) => this.onClick(e, doc));
    doc.addEventListener("input", (e) => this.onInput(e, doc));
    doc.addEventListener("change", (e) => this.onChange(e, doc));
    doc.addEventListener("focusout", (e) => this.onLeave(e, doc));
    if (!form) return;
    form.keepBy?.(this);
    form.on?.("filled", () => this.refill(doc));
    form.on?.("saved", (config) => this.settle(doc, config));
    form.on?.("hidden", () => this.sync(doc));
    for (const kind of ["input", "change"]) form.element?.()?.addEventListener?.(kind, () => this.sync(doc));
  }

  onClick(e, doc = globalThis.document) {
    const target = e.target;
    const star = target?.closest?.("[data-cell-settings-star]");
    if (star) return this.mine(star) ? this.star(star.dataset.cellSettingsStar, doc) : null;
    const apply = target?.closest?.("[data-cell-window-apply]");
    if (apply) return apply.dataset.cellWindowApply === this.key ? this.apply(doc) : null;
    const discard = target?.closest?.("[data-cell-window-discard]");
    if (discard) return discard.dataset.cellWindowDiscard === this.key ? this.discard() : null;
    const open = target?.closest?.("[data-cell-settings-open]");
    if (open) return this.open(open.dataset.cellSettingsOpen, doc);
    const group = target?.closest?.("[data-cell-settings-group]");
    if (group && this.mine(group)) {
      this.group = group.dataset.cellSettingsGroup;
      this.query = "";
      const box = doc?.querySelector?.(`[data-cell-settings-query="${CellSettings.css(this.key)}"]`);
      if (box) box.value = "";
      this.paintFields(doc);
      return this.group;
    }
    // The Settings or the Memory tab of a cell whose settings are edited here: the form is filled for it now, not at a second
    // click — unless that would let edits of another cell go; its Open button asks then.
    const tab = target?.closest?.('[data-cell-window-tab="settings"], [data-cell-window-tab="memory"]');
    const win = tab?.closest?.(".cell-window");
    if (!win?.querySelector?.("[data-cell-settings-view]")) return null;
    if (win.dataset.tId !== this.key && this.holds(this.key) && this.dirty().length) return null;
    return this.open(win.dataset.tId, doc);
  }

  /** True for a part of the editor of the cell the form holds: an editor left from another cell writes nothing. */
  mine(el) {
    return !!this.key && el?.closest?.("[data-cell-settings-view]")?.dataset?.cellSettingsView === this.key && this.holds(this.key);
  }

  onInput(e, doc = globalThis.document) {
    const query = e.target?.closest?.("[data-cell-settings-query]");
    if (query && this.mine(query)) {
      this.query = query.value;
      this.paintFields(doc);
      return this.query;
    }
    const field = e.target?.closest?.("[data-cell-settings-field]");
    if (field && this.mine(field) && field.type !== "checkbox" && !field.readOnly) return this.set(field.dataset.cellSettingsField, field.value, doc);
    return null;
  }

  onChange(e, doc = globalThis.document) {
    const only = e.target?.closest?.("[data-cell-settings-only]");
    if (only && this.mine(only)) {
      this.onlySet = !!only.checked;
      this.paintFields(doc);
      return this.onlySet;
    }
    const field = e.target?.closest?.("[data-cell-settings-field]");
    if (field && this.mine(field) && field.type === "checkbox") return this.set(field.dataset.cellSettingsField, field.checked ? "1" : "0", doc);
    return null;
  }

  /** Leaving a field does what leaving it does in the dialog (CellForm.settle), and the window draws what that wrote. */
  onLeave(e, doc = globalThis.document) {
    const field = e.target?.closest?.("[data-cell-settings-field]");
    if (!field || !this.mine(field)) return null;
    return Promise.resolve(this.form.settle?.(field.dataset.cellSettingsField)).then(() => this.sync(doc));
  }
}

export const CELL_SETTINGS = new CellSettings();
