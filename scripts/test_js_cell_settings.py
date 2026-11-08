#!/usr/bin/env python3
"""Value snapshot: a cell's settings edited in its window (static/js/cell-settings.js, 1.3.625).

The Settings tab of a llama.cpp cell lists its fields by the dialog's own tabs, with a search and "only those set"; the Memory
tab draws the placement map. Both edit the cell editor's form itself (remote-cells.js CellForm): the window fills it for the
cell without the dialog, writes into it as typing would, and saves it by the dialog's Apply. What is not applied is said at the
window's foot, and is let go only when the operator says so. A cell is held by its key alone — its id (cellId): the form is
asked holds(key) and fill(key, options), and no config here keeps a port (a cell holds one only while it runs).

Pinned by value with a fake form and a fake page: the groups (every field of the dialog's tabs once), a help's first sentence
in every script's stops, the editor idle and open, a field drawn as the form draws it (a box the config does not state shows
the server's default and says so, a field the form locks, the closed choices), the search by name and help, "only those set", a
field written (its row, the foot, the map; a field the form's own listeners wrote as well is drawn again), the foot (the fields
named, "and N more", the cell keeping its old settings, busy while saving), Apply (the config sent is the new start — a field
typed while the save was on its way stays not applied; a refusal keeps everything), Discard, the keeper's questions (the dialog
of the same cell shows the edits; another cell is filled only with the operator's word, the question naming the cell with the
edits as its window is titled, by its id with no window), an editor left from another cell writing nothing, the form filled by
a dialog for another cell, the map (drawn, a cell with none, no box), the focus given back after a repaint, the handlers, and that
the form is never asked by a machine and a port. The words come from static/js/i18n/en.js.

Run: python3 scripts/test_js_cell_settings.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _node import find_node, node_search_paths, probe_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def esc(text):
    """A word as the page writes it: escapeHtml of static/js/utils.js."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const root = process.env.JS_ROOT;
const { CellSettings } = await import(pathToFileURL(root + "/cell-settings.js").href);
const C = await import(pathToFileURL(root + "/constants.js").href);
const en = (await import(pathToFileURL(root + "/i18n/en.js").href)).default;
const out = { en: Object.fromEntries(Object.entries(en).filter(([k]) => /^(cwSet|cwDirty|cwPlace|cwDefault|tab)/.test(k))) };
const HELP = { CTX_SIZE: "Context window in tokens. More text costs memory.", PARALLEL: "How many requests at once.",
               MMAP: "Map the model file into memory. Faster starts.", EXTRA_ARGS: "Any other flag of llama-server." };
const help = (f) => HELP[f] || "";

// ── the groups and the words ──
const groups = CellSettings.groups();
const all = groups.flatMap((g) => g.fields);
const want = [...C.advancedGroups.flatMap((g) => g.fields), "EXTRA_ARGS"];
out.groups = { keys: groups.map((g) => g.key), tabs: C.advancedTabDefs.map((t) => t.key), firstLast: groups[0].fields.slice(-1)[0],
               once: all.length === new Set(all).size, none: want.filter((f) => !all.includes(f)), extra: all.filter((f) => !want.includes(f)) };
out.note = [CellSettings.note("Context window in tokens. More text costs memory."), CellSettings.note("No stop here"),
            CellSettings.note(""), CellSettings.note("v1.5 is read first. Then the rest."), CellSettings.note("上下文窗口。越大越占内存。"),
            CellSettings.note("कॉन्टेक्स्ट विंडो। ज़्यादा मेमोरी।"), CellSettings.note("Why? Because.")];
out.changed = [CellSettings.changed({ A: "1", B: "" }, { A: "1", B: "x", C: "" }), CellSettings.changed({}, {}), CellSettings.changed({ A: "0" }, {})];

// ── a fake form: the cell editor's, as remote-cells.js CellForm answers ──
// A cell is held by its key alone — its id (cellId); a cell holds a port only while it runs, so the form is asked by none. How
// many arguments every holds and fill of every fake form was given is kept (ARITY): holds the key, fill the key and its options.
const ARITY = [];
class Form {
  constructor(saved) {
    this.saved = saved; this.key = ""; this.fields = {}; this.boxes = {}; this.calls = [];
    this.listeners = { filled: [], saved: [], hidden: [] }; this.keeper = null; this.saveAnswer = true; this.duringSave = null;
    this.mapAnswer = true; this.onWrite = null;
  }
  holds(...a) { ARITY.push(["holds", a.length]); return !!this.key && this.key === String(a[0]); }
  // As CellForm.fill: true when filled; false for a key of no cell the board shows (here: one with no saved config, and not a new
  // cell's) — the form is left as it was then, and nothing is heard.
  fill(...a) {
    ARITY.push(["fill", a.length]);
    const [k, opts] = a;
    this.calls.push(["fill", String(k), opts]);
    if (!(String(k) in this.saved) && !String(k).startsWith("new:")) return false;
    this.key = String(k);
    this.fields = { ...(this.saved[this.key] || {}) };
    this.boxes = { MMAP: true, ENABLE_JINJA: this.fields.ENABLE_JINJA === "1" };
    this.emit("filled");
    return true;
  }
  read() { return { ...this.fields }; }
  set(f, v) {
    this.calls.push(["set", f, v]);
    this.fields[f] = String(v);
    if (f in this.boxes) this.boxes[f] = String(v) === "1";
    // The form's own listeners write a companion of SPEC_TYPE, as the dialog's do.
    if (f === "SPEC_TYPE") this.fields.SPEC_DRAFT_N_MAX = v ? "16" : "";
    // The form's input listener hears the write at once — the window's own write must not be drawn twice.
    this.onWrite?.();
    return true;
  }
  checked(f) { return !!this.boxes[f]; }
  // A field the form does not let be typed in (CellForm.locked): the window draws it so and writes nothing into it.
  locked(f) { return f === "ALIAS"; }
  // The runner's window field and the most its model takes (remote-cells.js CellForm); unset until a pin says them.
  windowField() { return this.window?.field; }
  modelWindow() { return this.window?.most || 0; }
  settle(f) {
    this.calls.push(["settle", f]);
    if (f === "EXTRA_ARGS" && /--ctx-size (\d+)/.test(this.fields.EXTRA_ARGS || "")) {
      this.fields.CTX_SIZE = this.fields.EXTRA_ARGS.match(/--ctx-size (\d+)/)[1];
      this.fields.EXTRA_ARGS = "";
    }
    return Promise.resolve();
  }
  async save() {
    this.calls.push(["save"]);
    const sent = this.read();
    if (this.duringSave) await this.duringSave();
    if (!this.saveAnswer) return false;
    this.saved[this.key] = sent;
    this.emit("saved", sent);
    return true;
  }
  placeMap(box) { this.calls.push(["map"]); box.innerHTML = this.mapAnswer ? "<the map>" : ""; return this.mapAnswer; }
  element() { return null; }
  keepBy(k) { this.keeper = k; }
  on(kind, fn) { this.listeners[kind].push(fn); }
  emit(kind, ...a) { for (const fn of this.listeners[kind]) fn(...a); }
}

// ── a fake page: the parts the editor finds, by the selectors it asks ──
const page = () => {
  const els = new Map();
  const paints = {};
  const el = (sel, extra = {}) => {
    const e = { sel, dataset: {}, _outer: "", _inner: "", ...extra };
    Object.defineProperty(e, "outerHTML", { get() { return this._outer; }, set(v) { this._outer = v; paints[sel] = (paints[sel] || 0) + 1; } });
    Object.defineProperty(e, "innerHTML", { get() { return this._inner; }, set(v) { this._inner = v; paints[sel + " |inner"] = (paints[sel + " |inner"] || 0) + 1; } });
    els.set(sel, e);
    return e;
  };
  const doc = { els, paints, activeElement: null, ids: new Map(), listeners: [],
    querySelector: (s) => els.get(s) || null, getElementById: (id) => doc.ids.get(id) || null,
    addEventListener(kind) { this.listeners.push(kind); } };
  const cell = (k) => {
    const view = el(`[data-cell-settings-view="${k}"]`);
    const body = el(`[data-cell-settings-view="${k}"] .cws-body`);
    const foot = el(`[data-cell-window-foot="${k}"]`, { dataset: { running: "" } });
    const box = el(`box ${k}`);
    const place = el(`[data-cell-window-place="${k}"]`);
    place.querySelector = (s) => (s === ".cw-place-map" && place.outerHTML.includes("cw-place-map") ? box : null);
    const query = el(`[data-cell-settings-query="${k}"]`, { value: "typed" });
    const row = (f) => els.get(`[data-t="cell-settings-field"][data-t-id="${k}:${f}"]`) || el(`[data-t="cell-settings-field"][data-t-id="${k}:${f}"]`);
    return { view, body, foot, box, place, query, row };
  };
  return { doc, cell, paints };
};
const state = (html) => (String(html).match(/data-t-state="([a-z]+)"/) || [])[1] ?? null;
const rows = (html) => [...String(html).matchAll(/data-t="cell-settings-field" data-t-id="[^"]*:([A-Z_0-9]+)" data-t-state="([a-z]+)"/g)].map((m) => [m[1], m[2]]);
const nav = (html) => Object.fromEntries([...String(html).matchAll(/data-cell-settings-group="([a-zA-Z]+)"[^>]*><span>[^<]*<\/span><span class="cws-count">(\d+)<\/span>/g)].map((m) => [m[1], Number(m[2])]));
const title = (html) => (String(html).match(/<h4 class="cw-sec-title">([^<]*)<\/h4>/) || [])[1] ?? null;
const empty = (html) => (String(html).match(/<p class="cw-empty">([^<]*)<\/p>/) || [])[1] ?? null;

// The cells by their ids — a new one's and an old one's (c<port>, made before 2026-11-07) — and their configs, which keep no port.
const SAVED = {
  "c3f9a02b1": { ALIAS: "local", CTX_SIZE: "32768", PARALLEL: "2", ENABLE_JINJA: "1", MMAP: "", SPEC_TYPE: "",
                 SPEC_DRAFT_N_MAX: "", EXTRA_ARGS: "", THREADS: "", BATCH_SIZE: "", UBATCH_SIZE: "", TENSOR_SPLIT: "", SPLIT_MODE: "" },
  "c22021": { THREADS: "8" },
  "c5e01d7aa": {},
};

// ── before the form is given ──
let cs = new CellSettings({ help });
out.unbound = [cs.html("c3f9a02b1", { llama: true, editable: true }), cs.html("c3f9a02b1", { llama: false, editable: true }),
               cs.html("c3f9a02b1", { llama: true, editable: false }), cs.placeHtml("c3f9a02b1", { llama: true, editable: true }),
               cs.placeHtml("c3f9a02b1", { llama: false, editable: true }), cs.footHtml("c3f9a02b1", { running: true })];
out.unboundOpen = await cs.open("c3f9a02b1");

// ── bound ──
const asked = [];
let answer = true;
const confirm = async (text, opts) => { asked.push([text, opts]); return answer; };
let form = new Form(JSON.parse(JSON.stringify(SAVED)));
let P = page();
let A = P.cell("c3f9a02b1");
for (const f of ["CTX_SIZE", "PARALLEL", "THREADS", "SPEC_TYPE"]) A.row(f);
cs = new CellSettings({ help });
cs.bind(P.doc, { form, confirm });
cs.bind(P.doc, { form, confirm });
out.bound = { keeper: form.keeper === cs, listeners: Object.fromEntries(Object.entries(form.listeners).map(([k, v]) => [k, v.length])), doc: P.doc.listeners };

out.open = await cs.open("c3f9a02b1", P.doc);
out.openFill = form.calls.filter((c) => c[0] === "fill");
out.openState = { holds: cs.holds("c3f9a02b1"), group: cs.group, dirty: cs.dirty(), view: state(A.view.outerHTML), foot: A.foot.innerHTML,
                  place: state(A.place.outerHTML), map: A.place.dataset.tState, mapCalls: form.calls.filter((c) => c[0] === "map").length };
const openHtml = A.view.outerHTML;
out.openHtml = { query: /data-cell-settings-query="c3f9a02b1"[^>]*value=""/.test(openHtml), only: /data-cell-settings-only="c3f9a02b1"[^>]* checked>/.test(openHtml),
                 onlyWords: (openHtml.match(/checked> ([^<]*)<\/label>/) || [])[1], rows: rows(openHtml), nav: nav(openHtml), title: title(openHtml) };
// A field as the form draws it; its name without the star (pinned on its own below).
const noStar = (html) => String(html || "").replace(/^<button type="button" class="cws-star[^>]*>★<\/button>/, "");
const fieldOf = (f) => (cs.fieldHtml(f).match(/<div class="cws-value">(.*)<\/div><\/div>$/) || [])[1];
out.fields = { CTX_SIZE: fieldOf("CTX_SIZE"), ALIAS: fieldOf("ALIAS"), ENABLE_JINJA: fieldOf("ENABLE_JINJA"), MMAP: fieldOf("MMAP"),
               SPLIT_MODE: fieldOf("SPLIT_MODE"), nameCtx: noStar((cs.fieldHtml("CTX_SIZE").match(/<div class="cws-name">(.*?)<\/div>/) || [])[1]),
               nameNoHelp: noStar((cs.fieldHtml("THREADS").match(/<div class="cws-name">(.*?)<\/div>/) || [])[1]) };
// The window field says the most the model takes; another field and an unknown model keep "unset".
form.window = { field: "CTX_SIZE", most: 131072 };
const placeholderOf = (f) => (fieldOf(f).match(/placeholder="([^"]*)"/) || [])[1];
out.windowPlaceholder = [placeholderOf("CTX_SIZE"), placeholderOf("THREADS")];
form.window = { field: "CTX_SIZE", most: 0 };
out.windowPlaceholder.push(placeholderOf("CTX_SIZE"));
form.window = null;
// Already held: no second filling.
form.calls.length = 0;
out.reopen = [await cs.open("c3f9a02b1", P.doc), form.calls.filter((c) => c[0] === "fill").length];
// A cell the board no longer shows: the form fills nothing and stays as it was — so does what the window holds.
cs.group = "tabMemory";
out.openGone = [await cs.open("c0ffee000", P.doc), cs.key, cs.group, cs.holds("c3f9a02b1"), form.key];
cs.group = "tabBasics";

// ── the search and "only those set" ──
cs.query = "mmap";
out.searchName = { rows: rows(cs.bodyHtml()), title: title(cs.bodyHtml()), nav: nav(cs.bodyHtml()), on: /cws-group on/.test(cs.bodyHtml()) };
cs.query = "COSTS memory";
out.searchHelp = rows(cs.bodyHtml());
cs.query = "zzz";
out.searchNone = [rows(cs.bodyHtml()), empty(cs.bodyHtml()), title(cs.bodyHtml())];
cs.query = "";
cs.group = "tabSpeculation";
out.groupEmpty = [rows(cs.bodyHtml()), empty(cs.bodyHtml())];
cs.onlySet = false;
out.groupAll = rows(cs.bodyHtml()).map((r) => r[0]);
cs.onlySet = true;
cs.group = "tabBasics";

// ── a field written ──
const count = (sel) => P.paints[sel] || 0;
let writes = 0;
form.onWrite = () => { writes += 1; cs.sync(P.doc); };
const bodySel = `[data-cell-settings-view="c3f9a02b1"] .cws-body`;
const bodyBefore = count(bodySel + " |inner");
const mapBefore = form.calls.filter((c) => c[0] === "map").length;
out.set = cs.set("CTX_SIZE", "65536", P.doc);
out.afterSet = { values: cs.values.CTX_SIZE, row: A.row("CTX_SIZE").dataset.tState, dirty: cs.dirty(), foot: A.foot.innerHTML,
                 body: count(bodySel + " |inner") - bodyBefore, map: form.calls.filter((c) => c[0] === "map").length - mapBefore, writes };
cs.set("CTX_SIZE", "32768", P.doc);
out.back = { row: A.row("CTX_SIZE").dataset.tState, foot: A.foot.innerHTML, dirty: cs.dirty() };
const bodyMid = count(bodySel + " |inner");
cs.set("SPEC_TYPE", "draft-mtp", P.doc);
out.companion = { body: count(bodySel + " |inner") - bodyMid, dirty: cs.dirty() };
cs.set("SPEC_TYPE", "", P.doc);
form.onWrite = null;

// ── the foot ──
for (const [f, v] of [["CTX_SIZE", "1"], ["PARALLEL", "4"], ["THREADS", "6"], ["BATCH_SIZE", "512"], ["UBATCH_SIZE", "256"], ["TENSOR_SPLIT", "1,1"]]) cs.set(f, v, P.doc);
out.footMany = A.foot.innerHTML;
A.foot.dataset.running = "1";
cs.paintFoot(P.doc);
out.footRunning = A.foot.innerHTML;
A.foot.dataset.running = "";
out.footOther = cs.footHtml("c22021", { running: false });

// ── another hand ──
cs.discard();
form.fields.TENSOR_SPLIT = "3,1";      // the map wrote it, or the dialog
out.sync = [cs.sync(P.doc), cs.dirty(), cs.sync(P.doc)];
cs.discard();

// ── Apply ──
cs.set("CTX_SIZE", "65536", P.doc);
let busyFoot = null;
form.duringSave = async () => { busyFoot = A.foot.innerHTML; form.fields.PARALLEL = "8"; };
const twice = [cs.apply(P.doc), cs.apply(P.doc)];
out.apply = { results: await Promise.all(twice), saves: form.calls.filter((c) => c[0] === "save").length, busyState: state(busyFoot),
              busyDisabled: (busyFoot.match(/ disabled>/g) || []).length, dirty: cs.dirty(), saved: form.saved["c3f9a02b1"].CTX_SIZE,
              savedParallel: form.saved["c3f9a02b1"].PARALLEL, base: cs.base.CTX_SIZE };
form.duringSave = null;
form.saveAnswer = false;
cs.set("THREADS", "12", P.doc);
out.applyRefused = [await cs.apply(P.doc), cs.dirty(), state(A.foot.innerHTML)];
form.saveAnswer = true;

// ── Discard ──
// The cell gone from the board meanwhile: nothing is filled, and what is not applied stays so.
const keptConfig = form.saved["c3f9a02b1"];
delete form.saved["c3f9a02b1"];
out.discardGone = [cs.discard(), cs.dirty()];
form.saved["c3f9a02b1"] = keptConfig;
form.calls.length = 0;
out.discard = [cs.discard(), form.calls.filter((c) => c[0] === "fill"), cs.dirty(), A.foot.innerHTML, cs.values.THREADS];
// Nothing to lose: the dialog of the cell is filled afresh, and another cell's form is filled without a question.
out.clean = [cs.keeps("c3f9a02b1"), await cs.leave("c22021", P.doc), asked.length];

// ── the keeper's questions ──
cs.set("CTX_SIZE", "4096", P.doc);
out.keeps = [cs.keeps("c3f9a02b1"), cs.keeps("c22021"), cs.keeps("c5e01d7aa"), cs.keeps("")];
answer = false;
out.leaveNo = await cs.leave("c22021", P.doc);
answer = true;
// The question names the cell whose edits would go as its window is titled; with no window of it drawn, by its id.
P.doc.els.set('[data-t="cell-window"][data-t-id="c3f9a02b1"] .cwh-name', { textContent: " Hermes-4-70B " });
out.leaveYes = await cs.leave("c22021", P.doc);
P.doc.els.delete('[data-t="cell-window"][data-t-id="c3f9a02b1"] .cwh-name');
out.asked = asked.splice(0);
// Another cell's window, while edits here are not applied: declined, nothing changes.
const B = P.cell("c22021");
answer = false;
form.calls.length = 0;
out.openOtherNo = [await cs.open("c22021", P.doc), cs.key, form.calls.filter((c) => c[0] === "fill").length, asked.splice(0).length];
// Accepted: the other cell is filled, and the cell left is drawn idle.
answer = true;
A.view._outer = openHtml;
out.openOtherYes = [await cs.open("c22021", P.doc), cs.key, form.calls.filter((c) => c[0] === "fill").map((c) => [c[1], c[2]]),
                    state(A.view.outerHTML), A.foot.innerHTML, state(A.place.outerHTML), state(B.view.outerHTML), cs.group, asked.splice(0).length];
const keepValues = cs.values;
cs.values = { THREADS: "8" };
const g1 = cs.firstGroup();
cs.values = {};
out.firstGroup = [g1, cs.firstGroup()];
cs.values = keepValues;
// An editor left from the cell before writes nothing into the form that holds another.
form.calls.length = 0;
const staleView = { dataset: { cellSettingsView: "c3f9a02b1" } };
const staleField = { type: "text", value: "999", readOnly: false, dataset: { cellSettingsField: "CTX_SIZE" },
                     closest: (s) => (s === "[data-cell-settings-field]" ? staleField : s === "[data-cell-settings-view]" ? staleView : null) };
out.stale = [cs.onInput({ target: staleField }, P.doc), form.calls.length,
             cs.onClick({ target: { closest: (s) => (s === "[data-cell-window-apply]" ? { dataset: { cellWindowApply: "c3f9a02b1" } } : null) } }, P.doc),
             cs.onClick({ target: { closest: (s) => (s === "[data-cell-window-discard]" ? { dataset: { cellWindowDiscard: "c3f9a02b1" } } : null) } }, P.doc),
             form.calls.length];
// The form filled by a dialog for another cell: the edits here are gone, and nothing is asked when there is nothing to lose.
cs.set("THREADS", "9", P.doc);
form.fill("c5e01d7aa", { pickModel: false });
out.dialogOther = [cs.key, cs.holds("c22021"), cs.dirty(), state(B.view.outerHTML), B.foot.innerHTML, cs.keeps("c22021"),
                   await cs.leave("c5e01d7aa", P.doc), asked.length];

// ── the map ──
form = new Form(JSON.parse(JSON.stringify(SAVED)));
P = page();
A = P.cell("c3f9a02b1");
cs = new CellSettings({ help });
cs.bind(P.doc, { form, confirm });
await cs.open("c3f9a02b1", P.doc);
out.map = [A.place.dataset.tState, A.box.innerHTML];
form.mapAnswer = false;
out.noMap = [cs.mountMap(P.doc), A.place.dataset.tState, A.box.innerHTML];
form.mapAnswer = true;
// After the board's repaint the box is new and drawn again; a board that drew no window has no box.
A.place._outer = cs.placeHtml("c3f9a02b1", { llama: true, editable: true });
A.box._inner = "";
out.remount = [cs.remount(P.doc), A.box.innerHTML];
P.doc.els.delete(`[data-cell-window-place="c3f9a02b1"]`);
out.noBox = cs.remount(P.doc);
const idle = new CellSettings({ help }).placeHtml("c3f9a02b1", { llama: true, editable: true });
out.placeIdle = [state(idle), (idle.match(/data-t="cell-settings-open" data-t-id="([^"]*)"/) || [])[1], (idle.match(/<p class="cw-lead">([^<]*)<\/p>/) || [])[1]];
const viewIdle = new CellSettings({ help }).html("c3f9a02b1", { llama: true, editable: true });
out.viewIdle = [state(viewIdle), (viewIdle.match(/data-t="cell-settings-open" data-t-id="([^"]*)"/) || [])[1], (viewIdle.match(/<p class="cw-lead">([^<]*)<\/p>/) || [])[1]];

// ── the focus given back ──
const focused = { id: "cws-CTX_SIZE", selectionStart: 2, selectionEnd: 4, closest: (s) => (s === "[data-cell-settings-view]" ? {} : null) };
const again = { id: "cws-CTX_SIZE", focused: 0, range: null, focus() { this.focused += 1; }, setSelectionRange(a, b) { this.range = [a, b]; } };
P.doc.activeElement = focused;
P.doc.ids.set("cws-CTX_SIZE", again);
cs.paintFields(P.doc);
out.focus = [again.focused, again.range];
const outside = { id: "elsewhere", selectionStart: 1, selectionEnd: 1, closest: () => null };
const other = { focused: 0, focus() { this.focused += 1; } };
P.doc.activeElement = outside;
P.doc.ids.set("elsewhere", other);
cs.paintFields(P.doc);
out.focusOutside = other.focused;
P.doc.activeElement = null;

// ── the handlers ──
const view = { dataset: { cellSettingsView: "c3f9a02b1" } };
const inView = (extra) => { const e = { ...extra }; e.closest = (s) => (extra.match === s ? e : s === "[data-cell-settings-view]" ? view : null); return e; };
form.calls.length = 0;
const q = inView({ match: "[data-cell-settings-query]", value: "ctx" });
out.onQuery = [cs.onInput({ target: q }, P.doc), rows(A.body.innerHTML).map((r) => r[0])];
const text = inView({ match: "[data-cell-settings-field]", type: "text", value: "8192", readOnly: false, dataset: { cellSettingsField: "CTX_SIZE" } });
cs.onInput({ target: text }, P.doc);
const locked = inView({ match: "[data-cell-settings-field]", type: "text", value: "1", readOnly: true, dataset: { cellSettingsField: "ALIAS" } });
out.onField = [form.calls.filter((c) => c[0] === "set"), cs.onInput({ target: locked }, P.doc)];
const box = inView({ match: "[data-cell-settings-field]", type: "checkbox", checked: false, dataset: { cellSettingsField: "ENABLE_JINJA" } });
cs.onChange({ target: box }, P.doc);
out.onBox = form.calls.filter((c) => c[0] === "set").slice(-1)[0];
const only = inView({ match: "[data-cell-settings-only]", checked: false });
out.onOnly = [cs.onChange({ target: only }, P.doc), cs.onlySet];
cs.onlySet = true;
A.query.value = "typed";
const grp = inView({ match: "[data-cell-settings-group]", dataset: { cellSettingsGroup: "tabMemory" } });
out.onGroup = [cs.onClick({ target: grp }, P.doc), cs.query, A.query.value];
// Leaving EXTRA_ARGS does what leaving it does in the dialog: the flag with a field of its own goes to it.
form.fields.EXTRA_ARGS = "--ctx-size 8192 --foo";
cs.sync(P.doc);
form.fields.EXTRA_ARGS = "--ctx-size 4096";
cs.sync(P.doc);
const extra = inView({ match: "[data-cell-settings-field]", type: "text", dataset: { cellSettingsField: "EXTRA_ARGS" } });
await cs.onLeave({ target: extra }, P.doc);
out.onLeave = [form.calls.filter((c) => c[0] === "settle"), cs.values.CTX_SIZE, cs.values.EXTRA_ARGS];
out.onLeaveOther = cs.onLeave({ target: { closest: () => null } }, P.doc);
// A tab of the window: the form is filled for its cell — unless edits of another cell would be lost.
const win = (key) => ({ dataset: { tId: key }, querySelector: (s) => (s === "[data-cell-settings-view]" ? {} : null) });
const tab = (key) => ({ closest: (s) => (s.startsWith('[data-cell-window-tab="settings"]') ? { closest: (x) => (x === ".cell-window" ? win(key) : null) } : null) });
form.calls.length = 0;
out.tabOther = [cs.onClick({ target: tab("c22021") }, P.doc), form.calls.filter((c) => c[0] === "fill").length];
cs.discard();
form.calls.length = 0;
out.tabFree = [await cs.onClick({ target: tab("c22021") }, P.doc), form.calls.filter((c) => c[0] === "fill").map((c) => [c[1], c[2]]), cs.key];
const winNone = { closest: (s) => (s.startsWith('[data-cell-window-tab="settings"]') ? { closest: () => ({ dataset: { tId: "c3f9a02b1" }, querySelector: () => null }) } : null) };
out.tabNoEditor = cs.onClick({ target: winNone }, P.doc);
out.clickElse = cs.onClick({ target: { closest: () => null } }, P.doc);
const openBtn = { closest: (s) => (s === "[data-cell-settings-open]" ? { dataset: { cellSettingsOpen: "c3f9a02b1" } } : null) };
out.clickOpen = [await cs.onClick({ target: openBtn }, P.doc), cs.key];
// ── the stars: the favorites' list, said on each row and changed by a click (1.3.638) ──
{
  let favs = ["CTX_SIZE"];
  const toggled = [];
  const favorites = { list: () => favs, toggle: async (f) => { toggled.push(f); favs = favs.includes(f) ? favs.filter((x) => x !== f) : [...favs, f]; } };
  const fs = new Form(JSON.parse(JSON.stringify(SAVED)));
  const SP = page();
  const SC = SP.cell("c3f9a02b1");
  const sc = new CellSettings({ help });
  sc.bind(SP.doc, { form: fs, confirm, favorites });
  await sc.open("c3f9a02b1", SP.doc);
  const starOf = (f) => (sc.fieldHtml(f).match(/<button type="button" class="cws-star[^"]*"[^>]*>★<\/button>/) || [""])[0];
  const pressed = (html) => (html.match(/aria-pressed="(true|false)"/) || [])[1] ?? null;
  out.stars = { on: [starOf("CTX_SIZE").includes('class="cws-star on"'), pressed(starOf("CTX_SIZE"))],
                off: [starOf("PARALLEL").includes('class="cws-star"'), pressed(starOf("PARALLEL"))],
                extra: starOf("EXTRA_ARGS"), hook: starOf("PARALLEL").includes('data-t="cell-settings-star" data-t-id="c3f9a02b1:PARALLEL"') };
  const starEl = (key, f) => ({ dataset: { cellSettingsStar: f },
    closest: (sel) => (sel === "[data-cell-settings-star]" ? starEl(key, f) : sel === "[data-cell-settings-view]" ? { dataset: { cellSettingsView: key } } : null) });
  const before = SP.paints[`[data-cell-settings-view="c3f9a02b1"] .cws-body |inner`] || 0;
  const now = await sc.onClick({ target: starEl("c3f9a02b1", "PARALLEL") }, SP.doc);
  out.starClick = { now, toggled: [...toggled], favs: [...favs], painted: (SP.paints[`[data-cell-settings-view="c3f9a02b1"] .cws-body |inner`] || 0) - before };
  const off = await sc.onClick({ target: starEl("c3f9a02b1", "CTX_SIZE") }, SP.doc);
  const foreign = sc.onClick({ target: starEl("c5e01d7aa", "THREADS") }, SP.doc);
  out.starOff = { off, favs: [...favs], foreign, toggled: [...toggled] };

  // ── adopt and release: the new-cell wizard's filling, edited here as it stands ──
  fs.fill("c22021", { hidden: true });
  fs.set("CTX_SIZE", "65536");
  const adopted = sc.adopt("c22021", { onlySet: false }, SP.doc);
  out.adopt = { adopted, key: sc.key, holds: sc.holds("c22021"), base: sc.base.CTX_SIZE, onlySet: sc.onlySet, dirty: sc.dirty(),
                group: sc.group, notHeld: sc.adopt("c5e01d7aa", {}, SP.doc), noKey: sc.adopt("", {}, SP.doc), keyAfter: sc.key };
  sc.set("PARALLEL", "4", SP.doc);
  out.adoptDirty = sc.dirty();
  out.release = { other: sc.release("c3f9a02b1"), mine: sc.release("c22021"), key: sc.key, holds: sc.holds("c22021"),
                  again: sc.release("c22021"), leave: await sc.leave("c22021") };
  out.arity = ARITY;
}

console.log(JSON.stringify(out));
"""


def main():
    node = find_node()
    if node is None:
        print("js cell-settings: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_cell_settings.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
               "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True,
                              text=True, cwd=ROOT, env=env, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js cell-settings: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:1500])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    en = got["en"]

    print("группы и слова:")
    g = got["groups"]
    check(g["keys"] == g["tabs"] and g["firstLast"] == "EXTRA_ARGS",
          "группы — вкладки диалога в их порядке; EXTRA_ARGS (любой флаг llama-server) закрывает первую")
    check(g["once"] and g["none"] == [] and g["extra"] == [],
          "negative: каждое поле групп диалога — ровно один раз, ни одно не потеряно и чужих нет")
    check(got["note"] == ["Context window in tokens.", "No stop here", "", "v1.5 is read first.", "上下文窗口。",
                          "कॉन्टेक्स्ट विंडो।", "Why?"],
          "под именем — первая фраза подсказки; negative: «v1.5» фразу не кончает, а точки китайского и хинди без пробела — кончают; "
          "без точки — вся подсказка, пустая — пусто")
    check(got["changed"] == [["B"], [], ["A"]], "разница двух чтений формы — по полям; пустое и отсутствующее — одно и то же")

    print("до формы:")
    check(got["unbound"][1:3] == ["", ""] and got["unbound"][4:] == ["", ""],
          "negative: не llama.cpp или настраивать нельзя — ни редактора, ни места карты; без формы подвала нет")
    check('data-t-state="idle"' in got["unbound"][0] and 'data-t-state="idle"' in got["unbound"][3] and got["unboundOpen"] is False,
          "negative: формы ещё нет — редактор и карта ждут (idle), открыть нечем")

    print("открытие:")
    check(got["bound"] == {"keeper": True, "listeners": {"filled": 1, "saved": 1, "hidden": 1}, "doc": ["click", "input", "change", "focusout"]},
          "bind: окно — хранитель правок формы, слышит «заполнена», «сохранена», «диалог закрыт»; слушатели страницы — один раз "
          "(negative: второй bind не добавляет)")
    check(got["open"] is True and got["openFill"] == [["fill", "c3f9a02b1", {"hidden": True}]],
          "открыть — заполнить форму сохранёнными настройками ячейки без диалога, по её ключу (cellId)")
    o = got["openState"]
    check(o == {"holds": True, "group": "tabBasics", "dirty": [], "view": "open", "foot": "", "place": "open", "map": "open", "mapCalls": 1},
          "после — редактор открыт на первой группе с заданным полем, правок нет, подвал пуст, карта нарисована в своём месте")
    h = got["openHtml"]
    check(h["query"] and h["only"] and h["onlyWords"] == en["cwSetOnly"].replace("{n}", "4"),
          "поиск пуст, «только заданные» включено, рядом — сколько полей задано (ALIAS, CTX_SIZE, PARALLEL, ENABLE_JINJA)")
    check(h["rows"] == [["ALIAS", "set"], ["CTX_SIZE", "set"], ["PARALLEL", "set"], ["ENABLE_JINJA", "set"]]
          and h["title"] == en["tabBasics"],
          "в группе — только заданные поля, по порядку диалога; negative: пустые API_PREFIX, N_GPU_LAYERS, EXTRA_ARGS не рисуются, "
          "и порта среди заданных нет — настройки ячейки порта не хранят")
    check(h["nav"].get("tabBasics") == 4 and h["nav"].get("tabSpeculation") == 0 and len(h["nav"]) == len(g["keys"]),
          "у каждой группы — число её заданных полей")
    f = got["fields"]
    check(f["CTX_SIZE"] == f'<input type="text" id="cws-CTX_SIZE" class="cws-input" data-cell-settings-field="CTX_SIZE" value="32768" '
                           f'placeholder="{esc(en["cwSetUnset"])}" autocomplete="off" spellcheck="false">',
          "текстовое поле — значение формы, «не задано» подсказкой")
    check("readonly" in f["ALIAS"] and "readonly" not in f["CTX_SIZE"],
          "negative: поле, которое форма не даёт печатать (CellForm.locked), и здесь readonly")
    check(got["windowPlaceholder"] == ["131072", esc(en["cwSetUnset"]), esc(en["cwSetUnset"])],
          "поле окна раннера подсказывает максимум модели — 131072, как поле диалога (владелец, 2026-10-26); negative: другое поле "
          "и модель, чьё окно не известно, — «не задано»")
    check(f["ENABLE_JINJA"].endswith(" checked>") and "cws-default" not in f["ENABLE_JINJA"],
          "переключатель, заданный конфигом, — как его рисует форма, без «по умолчанию»")
    check(f["MMAP"] == f'<input type="checkbox" id="cws-MMAP" class="cws-toggle" data-cell-settings-field="MMAP" checked>'
                       f'<span class="cws-default">{esc(en["cwDefault"])}</span>',
          "negative: необязательный переключатель, которого конфиг не задаёт, — включён, как его рисует форма (умолчание сервера), "
          "и сказано «по умолчанию»: отсутствие не выдано за решение")
    check('list="cws-SPLIT_MODE-choices"' in f["SPLIT_MODE"] and '<option value="tensor"></option>' in f["SPLIT_MODE"],
          "закрытый набор значений — подсказками, текст остаётся свободным")
    check(f["nameCtx"] == '<label for="cws-CTX_SIZE" title="Context window in tokens. More text costs memory.">CTX_SIZE</label>'
                          '<span class="cws-note">Context window in tokens.</span>'
          and f["nameNoHelp"] == '<label for="cws-THREADS">THREADS</label>',
          "имя — с подсказкой целиком на наведении и первой фразой под ним; negative: без подсказки — без пустых title и строки")

    print("звёздочки и мастер новой ячейки (1.3.638):")
    st = got["stars"]
    check(st["on"] == [True, "true"] and st["off"] == [True, "false"],
          "у поля — звёздочка избранного: нажата у поля из списка, отжата у остальных")
    check(st["extra"] == "" and st["hook"], "negative: у EXTRA_ARGS звёздочки нет — он в избранном всегда; хук cell-settings-star с полем")
    sc = got["starClick"]
    check(sc["now"] is True and sc["toggled"] == ["PARALLEL"] and sc["favs"] == ["CTX_SIZE", "PARALLEL"] and sc["painted"] == 1,
          "щелчок по звёздочке — список избранного меняет favorites.js, строки перерисованы")
    so = got["starOff"]
    check(so["off"] is False and so["favs"] == ["PARALLEL"] and so["foreign"] is None and so["toggled"] == ["PARALLEL", "CTX_SIZE"],
          "повторный щелчок снимает; negative: звёздочка редактора чужой ячейки не пишет ничего")
    ad = got["adopt"]
    check(ad["adopted"] is True and ad["key"] == "c22021" and ad["holds"] is True and ad["base"] == "65536" and ad["onlySet"] is False
          and ad["dirty"] == [] and ad["group"] == "tabBasics",
          "мастер: форма, заполненная другой рукой, правится здесь как есть — её слова и есть начало, правок нет, список полный")
    check(ad["notHeld"] is False and ad["noKey"] is False and ad["keyAfter"] == "c22021",
          "negative: ячейку, которой форма не держит, и пустой ключ взять нельзя — ключ остаётся прежним")
    check(got["adoptDirty"] == ["PARALLEL"], "что набрано после — то и правки")
    rl = got["release"]
    check(rl["other"] is False and rl["mine"] is True and rl["key"] == "" and rl["holds"] is False and rl["again"] is False and rl["leave"] is True,
          "мастер закрыт — ячейку отпустили: правки ничьи, следующее заполнение формы ни о чём не спрашивает; "
          "negative: чужую или уже отпущенную не отпускают")
    check(got["reopen"] == [True, 0], "negative: форма уже держит ячейку — второй раз не заполняется (правки не теряются)")
    check(got["openGone"] == [False, "c3f9a02b1", "tabMemory", True, "c3f9a02b1"],
          "negative: ячейки, которой доска больше не показывает, форма не заполняет (CellForm.fill — false) — и окно держит "
          "прежнюю ячейку, её группу и правки, а не выдаёт себя за новую")

    print("поиск и «только заданные»:")
    s = got["searchName"]
    check(s["rows"] == [["MMAP", "unset"]] and s["title"] == en["cwSetFound"].replace("{n}", "1") and not s["on"]
          and s["nav"]["tabMemory"] == 1 and s["nav"]["tabBasics"] == 0,
          "поиск по имени — поверх «только заданных» и по всем группам; у групп — сколько найдено в каждой, ни одна не выбрана")
    check(got["searchHelp"] == [["CTX_SIZE", "set"]], "поиск по подсказке, без учёта регистра")
    check(got["searchNone"] == [[], en["cwSetNoMatch"], en["cwSetFound"].replace("{n}", "0")],
          "negative: ничего не нашлось — так и сказано, а не пустая группа")
    check(got["groupEmpty"] == [[], esc(en["cwSetNone"])],
          "negative: в группе ничего не задано — сказано, как увидеть все её поля")
    check(got["groupAll"][:3] == ["SPEC_TYPE", "SPEC_DRAFT_N_GPU_LAYERS", "SPEC_DRAFT_N_MAX"] and len(got["groupAll"]) == 9,
          "без «только заданных» — все поля группы")

    print("поле записано:")
    a = got["afterSet"]
    check(got["set"] is True and a.get("values") == "65536" and a.get("row") == "changed" and a.get("dirty") == ["CTX_SIZE"],
          "запись — в саму форму; строка поля — changed; не применено — это поле")
    check(f'{esc(en["cwDirtyText"].replace("{fields}", "CTX_SIZE"))}</span>' in a["foot"]
          and 'data-cell-window-discard="c3f9a02b1"' in a["foot"] and 'data-cell-window-apply="c3f9a02b1"' in a["foot"]
          and 'data-t-state="dirty"' in a["foot"],
          "подвал называет поле и даёт «Отменить» и «Применить»")
    check(a["body"] == 0 and a["map"] == 1 and a["writes"] == 1,
          "negative: набранное поле не перерисовывается (каретка остаётся), а слушатель формы, услышав запись окна, не рисует второй раз; "
          "карта — заново")
    check(got["back"] == {"row": "set", "foot": "", "dirty": []}, "вернул как было — правок нет, подвал пуст")
    check(got["companion"] == {"body": 1, "dirty": ["SPEC_DRAFT_N_MAX", "SPEC_TYPE"]},
          "поле, которое дописали слушатели формы (спутник SPEC_TYPE), рисуется заново вместе с группой")

    print("подвал:")
    named = "BATCH_SIZE, CTX_SIZE, PARALLEL, TENSOR_SPLIT " + en["cwDirtyMore"].replace("{n}", "2")
    check(f'{esc(en["cwDirtyText"].replace("{fields}", named))}</span>' in got["footMany"],
          "больше четырёх — четыре по имени и «и ещё N»")
    check(f'{esc(en["cwDirtyText"].replace("{fields}", named))} {esc(en["cwDirtyRunning"])}</span>' in got["footRunning"],
          "работающая ячейка — сказано, что она работает со старыми настройками до перезапуска")
    check(got["footOther"] == "", "negative: подвал другой ячейки пуст — её форма не держит")

    print("другая рука:")
    check(got["sync"] == [True, ["TENSOR_SPLIT"], False],
          "форма изменилась не окном (карта, диалог) — окно перечитывает и называет поле; negative: перемен нет — ничего не рисуется")

    print("«Применить»:")
    ap = got["apply"]
    check(ap["results"] == [True, False] and ap["saves"] == 1, "сохраняет «Применить» диалога; negative: второе нажатие, пока идёт первое, — не сохраняет")
    check(ap["busyState"] == "busy" and ap["busyDisabled"] == 2, "пока сохраняется — подвал busy, кнопки закрыты")
    check(ap["saved"] == "65536" and ap["base"] == "65536" and ap["savedParallel"] == "2" and ap["dirty"] == ["PARALLEL"],
          "после — отправленное стало началом; negative: поле, набранное, пока сохранение шло, остаётся не применённым")
    check(got["applyRefused"] == [False, ["PARALLEL", "THREADS"], "dirty"],
          "negative: отказ (проверка, вопрос) — не применено остаётся не применённым")

    print("«Отменить»:")
    check(got["discardGone"] == [False, ["PARALLEL", "THREADS"]],
          "negative: ячейки уже нет на доске — «Отменить» ничего не заполняет, не применённое так и остаётся не применённым")
    d = got["discard"]
    check(d[0] is True and d[1] == [["fill", "c3f9a02b1", {"hidden": True}]] and d[2] == [] and d[3] == "" and d[4] == "",
          "форма снова заполнена сохранёнными настройками; правок нет, подвал пуст")

    print("хранитель правок:")
    check(got["clean"] == [False, True, 0],
          "negative: правок нет — диалог ячейки заполняется заново (окно ничего не держит), а другую ячейку открывают без вопроса")
    check(got["keeps"] == [True, False, False, False],
          "диалог этой ячейки показывает правки окна как есть; negative: другая ячейка (любая другая — по её имени) и пустой ключ — нет")
    check(got["leaveNo"] is False and got["leaveYes"] is True and len(got["asked"]) == 2
          and got["asked"][0][0] == en["cwDirtyLeave"].replace("{cell}", "c3f9a02b1") and got["asked"][0][1] == {"danger": False},
          "заполнить форму для другой ячейки — только со слова оператора; названа ячейка с правками — её cellId, когда окна её нет")
    check(got["asked"][1][0] == en["cwDirtyLeave"].replace("{cell}", "Hermes-4-70B") and "{" not in got["asked"][1][0],
          "окно ячейки нарисовано — вопрос называет её так, как названо окно (CellWindow.titleIn); negative: ни порта, ни пустой дыры")
    check(got["openOtherNo"] == [False, "c3f9a02b1", 0, 1], "negative: отказался — ни заполнения, ни смены ячейки")
    oy = got["openOtherYes"]
    check(oy[0] is True and oy[1] == "c22021" and oy[2] == [["c22021", {"hidden": True}]] and oy[7] == "tabPerformance" and oy[8] == 1,
          "согласился — форма заполнена для другой по её ключу, редактор на её первой группе с заданным полем (THREADS)")
    check(got["firstGroup"] == ["tabPerformance", "tabBasics"],
          "первая группа с заданным полем; negative: ничего не задано — первая вкладка диалога")
    check(oy[3:7] == ["idle", "", "idle", "open"],
          "negative: окно оставленной ячейки нарисовано в покое (idle) — его поля больше не пишут в форму другой")
    st = got["stale"]
    check(st == [None, 0, None, None, 0],
          "negative: поле, «Применить» и «Отменить», оставшиеся от другой ячейки, ничего не пишут и не сохраняют")
    do = got["dialogOther"]
    check(do == ["c22021", False, [], "idle", "", False, True, 0],
          "диалог заполнил форму для третьей ячейки — правок окна больше нет, оно в покое; negative: терять нечего — и не спрашивают")

    print("карта:")
    check(got["map"] == ["open", "<the map>"], "карта рисуется формой в свою коробку во вкладке «Память»")
    check(got["noMap"] == [True, "none", f'<p class="cw-empty">{esc(en["cwPlaceNoMap"])}</p>'],
          "negative: у ячейки нет карты (CPU, деление по строкам) — так и сказано, состояние none, а не пустая коробка")
    check(got["remount"] == [True, "<the map>"] and got["noBox"] is False,
          "после перерисовки доски — карта в новой коробке; negative: окна нет — рисовать негде")
    check(got["placeIdle"] == ["idle", "c3f9a02b1:memory", esc(en["cwPlaceLead"])]
          and got["viewIdle"] == ["idle", "c3f9a02b1", esc(en["cwSetLead"])],
          "форма держит другую — вкладки предлагают открыть свои поля и карту здесь")

    print("фокус:")
    check(got["focus"] == [1, [2, 4]], "перерисовка группы возвращает фокус и каретку полю, которое их держало")
    check(got["focusOutside"] == 0, "negative: фокус был вне редактора — его не трогают")

    print("обработчики:")
    check(got["onQuery"][0] == "ctx" and got["onQuery"][1] == ["CTX_SIZE", "CTX_CHECKPOINTS", "FIT_CTX", "YARN_ORIG_CTX"],
          "поиск рисует найденное сразу")
    check(got["onField"] == [[["set", "CTX_SIZE", "8192"]], None], "набор в поле пишет в форму; negative: readonly-поле — нет")
    check(got["onBox"] == ["set", "ENABLE_JINJA", "0"], "переключатель пишет «1»/«0»")
    check(got["onOnly"] == [False, False], "«только заданные» снимается")
    check(got["onGroup"] == ["tabMemory", "", ""], "группа выбрана — поиск сброшен, и в его поле тоже")
    check(got["onLeave"] == [[["settle", "EXTRA_ARGS"]], "4096", ""],
          "уход из EXTRA_ARGS делает то же, что в диалоге: флаг со своим полем уходит в него, окно рисует написанное")
    check(got["onLeaveOther"] is None, "negative: уход не из поля редактора — ничего")
    check(got["tabOther"] == [None, 0],
          "negative: вкладка окна другой ячейки, пока здесь не применено, — форма не заполняется (её кнопка спросит)")
    check(got["tabFree"] == [True, [["c22021", {"hidden": True}]], "c22021"],
          "вкладка «Настройки» или «Память» — форма заполняется для ячейки окна сразу")
    check(got["tabNoEditor"] is None and got["clickElse"] is None, "negative: окно без редактора, клик мимо — ничего")
    check(got["clickOpen"] == [True, "c3f9a02b1"], "кнопка «Править здесь» — открыть")
    ar = got["arity"]
    check(len(ar) > 20 and all(n == 1 for k, n in ar if k == "holds") and all(n == 2 for k, n in ar if k == "fill"),
          "negative: форму спрашивают по одному ключу ячейки — holds(ключ), fill(ключ, опции): ни машины, ни порта отдельно "
          f"(got {sorted(set(map(tuple, ar)))})")

    print()
    if _fail:
        print(f"js cell-settings FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print("js cell-settings OK: группы, редактор, поиск, запись, подвал, «Применить», «Отменить», хранитель, карта, фокус — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
