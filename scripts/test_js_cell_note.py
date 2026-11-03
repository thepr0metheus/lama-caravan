#!/usr/bin/env python3
"""Actual cell-note.js: a cell's note in its row on the machine's page (the owner, 2026-11-03: "I want to be able to sign the cells, to give them a comment of my own,
visible here").

The note is the one the cell always had (`cellNotes` of the topology, `POST /api/topology/server-slot/note`): shown on its card and in its window, it
was not in its row. Pinned, by value: what the page holds as a cell's note (none, spaces, words); the line of a noted cell and the ✎ of one with none,
escaped, with the hooks the binding finds; the question — the present words in the box, the limit named — and what is sent: the trimmed words, empty to
take the note off, nothing when nothing changed or the operator stepped back; what is said after, and a refusal in the controller's words; the binding of
every hook under the page's root; the words in all six languages.

The module is loaded FOR REAL with utils.js and state.js; i18n (English words, filled as the board fills them) and the dialogs are stand-ins; the network
and the toast are the harness's.

Run: python3 scripts/test_js_cell_note.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LANGS = sorted(p.stem for p in (ROOT / "static" / "js" / "i18n").glob("*.js"))
KEYS = ["cellNoteAdd", "cellNoteChange", "cellNotePrompt", "cellNotePlaceholder", "cellNoteSave", "cellNoteSaved", "cellNoteRemoved"]

PROBE = r'''
import "./_js_globals.mjs";
import assert from "node:assert/strict";
const en = (await import("../static/js/i18n/en.js")).default;
const prompted = [], refreshes = [];
let typed = null;
globalThis.__stubReturns = {
  "i18n.t": (key, vars = {}) => String(en[key] ?? `?${key}`).replace(/\{(\w+)\}/g, (_, name) => (vars[name] === undefined ? `{${name}}` : vars[name])),
  "dialogs.appPrompt": async (message, opts) => { prompted.push({ message, opts }); return typed; },
};
const toastEl = { textContent: "", classList: { add() {}, remove() {} } };
globalThis.__fields = { toast: toastEl };
const spoken = [];
Object.defineProperty(toastEl, "textContent", { get() { return spoken.at(-1) ?? ""; }, set(v) { spoken.push(v); } });
const st = await import("../static/js/state.js");
const { CellNote } = await import("../static/js/cell-note.js");
const pass = [];
const pin = (cond, why) => { assert.ok(cond, why); pass.push(why); };
const eq = (got, want, why) => { assert.deepEqual(got, want, why + ` (got ${JSON.stringify(got)})`); pass.push(why); };
const ROUTE = "/api/topology/server-slot/note";
const reset = () => { prompted.length = 0; refreshes.length = 0; spoken.length = 0; typed = null; globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; };
const refresh = async () => { refreshes.push(1); };
const sent = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, body: JSON.parse(c.body) }));
const world = (notes) => st.setTopology({ nodes: [{ id: "hotel", servers: [{ port: 22007 }, { port: 22025 }] }], cellNotes: notes });

// ── what the page holds ──
{
  world({ "hotel:22007": " for the coder ", "hotel:22025": "   ", "box:1": 5 });
  eq([CellNote.of("hotel", 22007), CellNote.of("hotel", "22025"), CellNote.of("hotel", 9), CellNote.of("box", 1)], ["for the coder", "", "", ""],
     "a note is the words the topology holds for that machine and port, trimmed; spaces, none and a number are no note");
  world(undefined);
  pin(CellNote.of("hotel", 22007) === "", "negative: a topology that says no notes says none for every cell");
}

// ── the row's line and its ✎ ──
{
  world({ "hotel:22007": "for <the> coder" });
  eq(CellNote.lineHtml("hotel", 22007), '<button type="button" class="machine-model-note" data-cell-note="hotel:22007" data-machine-own data-t="machine-model-note" data-t-id="22007"'
     + ' title="for &lt;the&gt; coder\n\nClick to change the note">💬 for &lt;the&gt; coder</button>', "a noted cell's line: the card's 💬 and its words, escaped, the whole of them in the tip");
  pin(CellNote.lineHtml("hotel", 22025) === "", "negative: no note, no line");
  const add = CellNote.addHtml("hotel", 22025);
  pin(add.includes('data-cell-note="hotel:22025"') && add.includes('data-t="machine-model-note-add"') && add.includes('aria-label="Add a note to this cell"') && add.includes(">✎</button>"),
      "a cell with none has the ✎, named for the screen reader");
  pin(CellNote.addHtml("hotel", 22007) === "", "negative: a noted cell has no ✎ besides its words");
}

// ── the question and what is sent ──
{
  world({ "hotel:22007": "for the coder" });
  reset();
  typed = "  long context, do not stop  ";
  globalThis.__fetchReply[ROUTE] = { key: "hotel:22007", note: "long context, do not stop" };
  await CellNote.edit("hotel", "22007", refresh);
  eq([prompted[0].message, prompted[0].opts.value, prompted[0].opts.confirmLabel],
     ["A note on the cell :22007 — your own words, shown in its row and on its card (at most 280 characters; empty removes it):", "for the coder", "Save note"],
     "the question names the cell and the limit, with the present words in the box");
  eq(sent(), [{ path: ROUTE, body: { hostId: "hotel", port: 22007, note: "long context, do not stop" } }], "the words go to the note's own route, trimmed, the port as a number");
  eq([spoken, refreshes.length], [["Note saved"], 1], "the operator is told, and the page drawn again");
  reset();
  typed = "   ";
  await CellNote.edit("hotel", "22007", refresh);
  eq([sent()[0].body.note, spoken], ["", ["Note removed"]], "empty words take the note off");
  reset();
  typed = "for the coder";
  await CellNote.edit("hotel", "22007", refresh);
  pin(sent().length === 0 && refreshes.length === 0, "negative: the same words send nothing");
  reset();
  typed = null;
  await CellNote.edit("hotel", "22007", refresh);
  pin(sent().length === 0 && spoken.length === 0, "negative: stepped back, nothing is sent or said");
  world({});
  reset();
  typed = "first words";
  await CellNote.edit("hotel", "22007", refresh);
  eq([prompted[0].opts.value, sent()[0].body.note], ["", "first words"], "a cell with none asks with an empty box");
  reset();
  typed = "x";
  globalThis.__fetchReply[ROUTE] = { __status: 404, error: "no server slot hotel:22007" };
  await CellNote.edit("hotel", "22007", refresh);
  pin(spoken.length === 1 && spoken[0].includes("no server slot") && refreshes.length === 1, "negative: the controller refuses — its words are said");
}

// ── the binding ──
{
  const made = (dataset) => ({ dataset, handlers: {}, addEventListener(type, fn) { this.handlers[type] = fn; } });
  const btns = [made({ cellNote: "hotel:22007" }), made({ cellNote: "box:with:colons:22025" })];
  const asked = [];
  const root = { querySelectorAll(selector) { asked.push(selector); return selector === "[data-cell-note]" ? btns : []; } };
  CellNote.bind(root, refresh);
  pin(asked.join() === "[data-cell-note]" && btns.every((b) => typeof b.handlers.click === "function"), "every note and ✎ under the root gets its click");
  world({ "hotel:22007": "x" });
  reset();
  typed = "y";
  // Waited on as the asking itself: the harness keeps timers, and a wait on one never ends under it.
  await btns[0].handlers.click({ stopPropagation() {} });
  eq(sent()[0]?.body, { hostId: "hotel", port: 22007, note: "y" }, "a click asks for that cell's note");
  pin(btns[1].handlers.click({ stopPropagation() {} }) instanceof Promise, "a host name with colons still splits at the port's colon");
  CellNote.bind(null, refresh);
  pass.push("negative: no root, no binding, no throw");
}

// ── the words ──
{
  const langs = JSON.parse(process.env.LANGS), keys = JSON.parse(process.env.KEYS);
  const holes = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");
  const want = { cellNotePrompt: "most,port", cellNoteSaved: "", cellNoteRemoved: "" };
  const lacking = [], wrong = [], same = [];
  for (const lang of langs) {
    const m = (await import(`../static/js/i18n/${lang}.js`)).default;
    for (const key of keys) {
      if (!m[key]) { lacking.push(`${lang}.${key}`); continue; }
      if (lang !== "en" && m[key] === en[key]) same.push(`${lang}.${key}`);
      if (key in want && holes(m[key]) !== want[key]) wrong.push(`${lang}.${key}: ${holes(m[key])}`);
    }
  }
  eq(lacking, [], `all ${keys.length} words exist in all ${langs.length} languages`);
  eq(wrong, [], "every language fills the holes the code fills, and no other");
  eq(same, [], "no language is left with the English text");
}

for (const why of pass) console.log("  ok  " + why);
console.log(`js cell-note OK: ${pass.length} pins`);
'''


def main() -> int:
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_cell_note.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        harness = ROOT / "scripts" / "_js_harness.mjs"
        result = subprocess.run(probe_args(node, harness, probe), cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "JS_STUBS": "i18n,dialogs", "LANGS": json.dumps(LANGS), "KEYS": json.dumps(KEYS),
                                     "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"},
                                capture_output=True, text=True, timeout=90)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
