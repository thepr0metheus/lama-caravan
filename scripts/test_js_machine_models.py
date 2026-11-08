#!/usr/bin/env python3
"""Actual machine-models.js: the two parts of the models on a machine's page (the owner's choices М1 and Н1, 2026-11-02, and the block he
asked for on 2026-11-05).

The owner: "at the bottom a list of all the models, row by row, with their likes and dislikes; a press on one shows the launches saved for
it"; then: "we still have that block of cells for some reason; move all that is useful into Models, and take nothing from them"; then the same
on 2026-11-05: "add a block under «What lies where» and above Models: it shows the row picked in Models and the Cell window and Start buttons
there — Models keeps only the picking". Pinned, by value:
  * what is a row: a model's folder, once, whatever its builds; a checkpoint folder too; a file straight in the library, with no mark to
    keep; a model only a cell here names, said not to be in the library. A later part and a projector are no rows. Its work, its sizes,
    its cells, its mark, its repository;
  * the picking: `pick` says whether it changed — the same row pressed again does nothing, and an empty name is not a model with no name but
    the state of nothing picked, which the block says in words; `chose` moves the block to the chosen cell's model, and a cell whose model has
    no row there moves nothing; the block is drawn for one model, so `show` says when the page has to be drawn again, and the list never does;
  * the order: those with a cell first, then by name. Neither a mark nor a pick sorts: a row never moves under a press. Within a model its
    cells keep the machine's order, read by the rows and by the repository line alike;
  * no row is a model's default cell any more (2026-11-07: the maker's numbers are the launch builder's own set, machine-build.js): a cell a
    controller marked so before is drawn as any other — no origin, no word of a missing file, no rule of its own in machine.css — and the
    words of the default cells are in no language;
  * the count: a 📦 per cell; past four, three and +N; no cell is a quiet dash, not a zero; its words in its hover and its label;
  * the work: JOB_MARKS before each label, one source; the pills over the list narrow it in place, with no drawing, together with the filters
    and the words typed by one rule; a work no cell here does narrows nothing; a cell of other work inside the block is hidden;
  * the filters and the words typed: what stays, what the counts say, the word when nothing stays — and an empty library is said apart;
  * what a row says of itself is only what a row can say of itself: its name, its cells, its mark, its works — not whether it is picked, which is
    the choice and has one place (`picked`). The picked row stands whatever the list is narrowed to;
  * the block: the picked model's parts, drawn by the same helper as the row, so the two cannot say two things about one model; then a row per
    cell of it — its own name, the cellId, with a dot (a button that chooses the cell; no port: a cell holds one only while it runs), runner, build, windows, what it sets, then size and verdict on a second
    line, a failed one's reason in its hover; its Window and Start or Stop apart, under names of their own; a Start with nothing to start with
    is shut; a click anywhere on it chooses, a click on its buttons does not; the mark is not in the block: it stays on the row, where a press
    keeps it;
  * the cells with no row to pick: named as the page names them, each with a row of its own to choose, start or open, inside the block; gone while the
    list is searched for a model or a mark;
  * what its makers recommend: said when kept, nothing when not, a word of its own when it could not be read — never as if it said nothing;
  * a new cell: with one build the wizard goes straight on from it, with several it opens on the model's words and work; shut while a cell
    is being reserved, and for a model with no file here;
  * a press on a mark: works for a model with no cell, turns by what stands on its buttons, comes back when refused, and the row and the 👍
    count follow at once;
  * a drawing of the page keeps the choice, the caret in the search box and the scroll;
  * the longest context a model was trained for, on the parts a model says of itself (the owner, 2026-11-02: "there is no word here on the
    largest context the model can take"): 🎓 and the window; a range when its builds differ; what its cell's model says when the library lists
    none; "not known" for a model that takes a window nobody stated, never a 0; a dash for work with no window in tokens;
  * the chosen cell (the strip under the rack went into its row, the owner, 2026-11-02): its row stands whatever the list is narrowed to, its
    cell's row too, a cell with no model's row too; a choice moves the block to its model, and the row is brought into sight; its row ends in
    the cell's last line, and a plan's Start stands in for its own;
  * the bench is gone: no such section, no such words in any language, no such rules in the stylesheet.

The modules are loaded FOR REAL (machine-models.js, machine-head.js and what they read); i18n (the English words) is a stand-in.

Run: python3 scripts/test_js_machine_models.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LANGS = sorted(p.stem for p in (ROOT / "static" / "js" / "i18n").glob("*.js"))
KEYS = ["machineModelsTitle", "machineModelsAll", "machineModelsWithCell", "machineModelsFind", "machineModelsNone", "machineModelsEmpty",
        "machineModelsCells", "machineModelsOneCell", "machineModelsNoCell", "machineModelsNoLaunch", "machineModelsMakers", "machineModelsNew",
        "machineModelsNotHere", "machineModelsTextsUnread", "machineModelsStatedOnce", "machineModelsOutside",
        "machineChosenTitle", "machineChosenHint", "machineChosenNone", "machineModelsHint", "machineCellRowHint", "machineModelsJobs", "machinePickReserved",
        "mdlWindowTip", "mdlWindowUnknown", "mdlWindowUnknownTip", "mdlWindowNoneTip"]
GONE_KEYS = ["machineBenchTitle", "machineBenchHint", "machineBenchJobs", "machineBenchEmpty", "machinePickNone", "machinePickNoneSub", "machinePickStopped", "machineNoModel",
             "machineModelsDefaultCell", "cellNoFileYet", "cellDefaultNotDeleted", "cellDefaultNoAutostart"]

PROBE = r'''
import "./_js_globals.mjs";
import assert from "node:assert/strict";
const en = (await import("../static/js/i18n/en.js")).default;
globalThis.__stubReturns = {
  "i18n.t": (key, vars = {}) => String(en[key] ?? `?${key}`).replace(/\{(\w+)\}/g, (_, name) => (vars[name] === undefined ? `{${name}}` : vars[name])),
};
const st = await import("../static/js/state.js");
const { MachineModels, MachineModelsChoice } = await import("../static/js/machine-models.js");
const { MachineHead, MachineMap, MachinePanes, MachinePick } = await import("../static/js/machine-head.js");
const { JOB_MARKS } = await import("../static/js/model-jobs.js");
const pass = [];
const pin = (cond, why) => { assert.ok(cond, why); pass.push(why); };
const eq = (got, want, why) => { assert.deepEqual(got, want, why + ` (got ${JSON.stringify(got)})`); pass.push(why); };

const ROWS = [
  { kind: "model", path: "Zeta-GGUF/unsloth/Q4/zeta-Q4.gguf", sizeGb: 17.6, ggufMeta: { contextLength: 65536 } },
  { kind: "model", path: "Zeta-GGUF/unsloth/Q5/zeta-Q5.gguf", sizeGb: 20.9, ggufMeta: { contextLength: 262144 } },
  { kind: "model", path: "Alpha-GGUF/a/Q4/alpha-00001-of-00002.gguf", sizeGb: 40.5, ggufMeta: {} },
  { kind: "model", path: "Alpha-GGUF/a/Q4/alpha-00002-of-00002.gguf", sizeGb: 40.5, ggufMeta: {} },
  { kind: "mmproj", path: "Alpha-GGUF/a/Q4/mmproj.gguf", sizeGb: 1 },
  { kind: "model", path: "stt-GGUF/b/Q8/stt.gguf", sizeGb: 0.3, ggufMeta: { sttVariant: "gigaam" } },
  { kind: "model", path: "loose.gguf", sizeGb: 2, ggufMeta: {} },
];
const ARTIFACTS = [{ kind: "safetensors", path: "Cosmos/nvidia/ST", sizeGb: 4.8, arch: "Qwen3ForCausalLM", contextLength: 8192 }];
const cell = (over) => ({ runner: "llama.cpp", jobs: ["llm"], ctx: { set: 8192, max: 131072 }, key: "h:1", window: true, quant: "Q4", ...over, listed: over.listed ?? over.model });
const CELLS = new Map([
  ["c22030", cell({ model: "Zeta-GGUF", launch: 'data-start-a="c22030"', stop: "", repo: "  unsloth/<Zeta>-GGUF  " })],
  ["c1a2b3c4d", cell({ model: "Zeta-GGUF", quant: "Q5", launch: "", stop: 'data-stop-a="c1a2b3c4d"', repo: "other/Zeta-GGUF" })],
  ["c5e1d7a90", cell({ model: "Gone-GGUF", runner: "vLLM", ctx: null, jobs: ["llm"], launch: 'data-start-a="c5e1d7a90"', reason: "out of <memory>" })],
  ["c22050", cell({ model: "", name: "ollama-qwen", runner: "Ollama", jobs: ["llm", "nonsense"], ctx: null })],
  ["c22060", cell({ model: "", listed: "", name: "Reserved cell", jobs: [], ctx: null })],
]);
const NODE = { id: "hotel", servers: [{ cellId: "c22030", port: null, phase: "stopped", slotConfig: { PARALLEL: "3", TEMPERATURE: "1.0", TOP_K: "" } },
                                      { cellId: "c1a2b3c4d", port: 22031, phase: "running", slotConfig: {} },
                                      { cellId: "c5e1d7a90", port: null, phase: "error", slotConfig: {} },
                                      { cellId: "c22050", port: null, phase: "stopped", slotConfig: {} },
                                      { cellId: "c22060", port: null, phase: "reserved", slotConfig: {} }] };
const STATE = { c5e1d7a90: "failed" };
const MAP = {
  node: NODE, cells: CELLS, chosen: "",
  // The machine's cells as the map reads them: the rows that name a cell, by the map's own rule.
  cellsMade() { return (this.node.servers || []).filter((s) => MachineMap.idOf(s)); },
  cellName: (s) => `${s.cellId} name`,
  benchSize: (s) => `≈${s.cellId} GB`,
  benchVerdict: (s) => ({ tone: "good", words: `fits ${s.cellId}`, state: STATE[s.cellId] || "card" }),
  actionsHtml: (s) => `<ACTS ${s.cellId}>`,
  choiceHtml: (s) => `<CHOICE ${s.cellId}>`,
  works: (s) => s.phase === "running",
  benchJobs: () => [{ job: "llm", count: 4 }, { job: "asr", count: 1 }],
  jobShown: (job) => (["llm", "asr"].includes(job) ? job : ""),
};
const choice = () => new MachineModelsChoice();
// The two parts as the page puts them: the block inside «What lies where», under its legend, and the list in the pane that scrolls. The place
// is MachineHead's (pinned below, on the head's own html); here the parts are read as they are drawn.
const pageOf = (m) => m.blockHtml() + m.listHtml();
const list = (over = {}) => { const m = new MachineModels({ map: MAP, rows: ROWS, artifacts: ARTIFACTS, ratings: { "Alpha-GGUF": "dislike", "stt-GGUF": "like" }, choice: choice(), ...over }); return Object.assign(m, { html: () => pageOf(m) }); };

// What is a row, and in what order.
const lines = list().lines();
eq(lines.map((l) => l.name), ["Gone-GGUF", "Zeta-GGUF", "Alpha-GGUF", "Cosmos", "loose.gguf", "stt-GGUF"], "with a cell first, then by name; a mark does not sort; a file straight in the library is a row");
eq(lines.find((l) => l.name === "Zeta-GGUF").sizes, [17.6, 20.9], "a model's builds are one row with both sizes");
eq(lines.find((l) => l.name === "Alpha-GGUF").sizes, [40.5], "a later part and a projector are no builds");
eq(lines.map((l) => l.cells), [1, 2, 0, 0, 0, 0], "the cells that run each model here");
eq(lines.map((l) => l.mark), ["", "", "dislike", "", "", "like"], "the marks kept by the folder");
eq(lines.map((l) => l.rated), [true, true, true, true, false, true], "a file with no folder has nothing to keep a mark by");
eq(lines.find((l) => l.name === "stt-GGUF").shownJobs, ["asr"], "a recognizer says its work");
eq(lines.find((l) => l.name === "Cosmos").shownJobs, ["llm"], "a checkpoint folder is a model with its work");
eq(lines.find((l) => l.name === "Gone-GGUF").files, [], "a model only a cell names has no file here");
eq(new MachineModels({ map: MAP, rows: null, artifacts: null, ratings: null, choice: choice() }).lines().map((l) => l.name), ["Gone-GGUF", "Zeta-GGUF"], "lists not come yet: the cells still have their models");
eq(lines.map((l) => l.chosen), [false, false, false, false, false, false], "a row says whether it holds the chosen cell: the stopped, the failed and the reserved one do not");
eq(list({ map: { ...MAP, chosen: "c5e1d7a90" } }).lines().map((l) => l.chosen), [true, false, false, false, false, false], "and does when it does, because the block above follows that cell");

// The order of one model's cells: as this machine gave them, read by the rows and by the repository line alike. Until 2026-11-07 a model's
// default cell stood first; a cell an older controller marked so moves nowhere now — the mark is no rule of the page.
const oldMark = new Map([["c22030", cell({ model: "Zeta-GGUF", repo: "unsloth/Zeta-GGUF" })],
                         ["c1a2b3c4d", cell({ model: "Zeta-GGUF", quant: "Q5", defaultFor: "Zeta-GGUF", repo: "first/Zeta-GGUF" })]]);
const ordered = new MachineModels({ map: { ...MAP, cells: oldMark }, choice: choice() }).lines().find((l) => l.name === "Zeta-GGUF");
eq(ordered.launches.map((s) => s.cellId), ["c22030", "c1a2b3c4d"], "a model's cells keep the machine's order, the order they were made, an old mark of a default cell moves nothing");
pin(ordered.repo === "unsloth/Zeta-GGUF", "and the repository under the name names that same first cell");
eq(new MachineModels({ map: MAP, choice: choice() }).lines().find((l) => l.name === "Zeta-GGUF").launches.map((s) => s.cellId),
   ["c22030", "c1a2b3c4d"], "negative: nothing is sorted by name, by port or by phase — c1a2b3c4d would stand first by its name");

// Figures.
eq([MachineModels.sizeWords([17.6, 20.9]), MachineModels.sizeWords([8.8, 8.8]), MachineModels.sizeWords([]), MachineModels.sizeWords([0])],
   ["17.6–20.9 GB", "8.8 GB", null, null], "one size, a range, and nothing known is null, not 0");
eq(MachineModels.moreOf({ PARALLEL: "3", TEMPERATURE: "1.0", TOP_K: "", TOP_P: 0.95 }), "parallel 3 · temp 1.0 · top_p 0.95", "what a launch sets, an empty field left out");
eq(MachineModels.moreOf(undefined), "", "a launch with no config says nothing");

// The count: marks by the count, past what fits three and how many more; no cell is not "0".
eq([0, 1, 4, 5, 7].map((n) => MachineModels.cellMarks(n)),
   [{ none: true, marks: "", more: "" }, { none: false, marks: "📦", more: "" }, { none: false, marks: "📦📦📦📦", more: "" },
    { none: false, marks: "📦📦📦", more: "+2" }, { none: false, marks: "📦📦📦", more: "+4" }], "a mark per cell; four fit; five are three and +2, seven three and +4; none is none");
eq(MachineModels.cellMarks(undefined), { none: true, marks: "", more: "" }, "negative: a count nobody said draws no mark");
eq(MachineModels.cellsHtml(0), '<span class="machine-model-cells is-none" role="img" title="no cell" aria-label="no cell">—</span>', "no cell: a quiet dash, the words in its hover and label; negative: no 0 and no mark");
eq(MachineModels.cellsHtml(1), '<span class="machine-model-cells" role="img" title="1 cell" aria-label="1 cell">📦</span>', "one cell: a mark, its own words");
eq(MachineModels.cellsHtml(7), '<span class="machine-model-cells" role="img" title="7 cells" aria-label="7 cells">📦📦📦<i>+4</i></span>', "seven cells: 📦📦📦+4, and the words say all seven");

// The work: its marks, from the vocabulary.
eq(["llm", "asr", "speech-translate", "voice-chat"].map((j) => MachineModels.jobWords(j)),
   [`${JOB_MARKS.llm} LLM`, `${JOB_MARKS.asr} speech → text`, `${JOB_MARKS["speech-translate"]} speech → translation`, `${JOB_MARKS["voice-chat"]} speech → speech`], "a work says its mark from JOB_MARKS, then its label");

// The row.
const html = list().html();
const row = (text, name) => text.slice(text.indexOf(`data-machine-model="${name}"`), text.indexOf("data-machine-model=", text.indexOf(`data-machine-model="${name}"`) + 10) + 1 || undefined);
pin(html.includes('data-t="machine-models" data-t-state="models"'), "the list says it holds models");
const zeta = row(html, "Zeta-GGUF");
pin(zeta.includes("17.6–20.9 GB") && zeta.includes('title="2 cells"') && zeta.includes("📦📦<") && zeta.includes('<span class="machine-model-job" title="💬 LLM">💬 LLM</span>'), "a row: its work with its mark, its sizes, its cells");
pin(!/\b2 cells</.test(zeta), "negative: the count is no text in the row");
pin(row(html, "stt-GGUF").includes('<span class="machine-model-job" title="🎧 speech → text">🎧 speech → text</span>'), "another work, its own mark");
pin(row(html, "Gone-GGUF").includes("not in the library") && row(html, "Gone-GGUF").includes('title="1 cell"'), "no file here: said, no size made up");
pin(row(html, "Cosmos").includes('title="no cell"') && row(html, "Cosmos").includes("is-idle"), "no cell here: said, and the row is quieter");
pin(row(html, "Alpha-GGUF").includes('data-model-rate="dislike" data-model-rate-for="Alpha-GGUF"') && /is-on" aria-pressed="true" data-model-rate="dislike"/.test(row(html, "Alpha-GGUF")), "a row has the model's mark pressed");
pin(!/is-on/.test(row(html, "Cosmos")) && row(html, "Cosmos").includes('aria-pressed="false" data-machine-model-choose="Cosmos"'), "a model with no mark has nothing pressed, and its row is not the picked one");
pin(row(html, "loose.gguf").includes("2.0 GB") && !row(html, "loose.gguf").includes("data-model-rate") && row(html, "loose.gguf").includes('<span class="machine-model-rate"></span>'), "a file straight in the library: its size, no mark buttons, their place kept for the columns");

// Its repository, under its name: the first cell's that names one; none with no cell.
pin(zeta.includes('<span class="machine-model-title"><b class="machine-model-name">Zeta-GGUF</b><small class="machine-model-repo" data-t="machine-model-repo" data-t-id="Zeta-GGUF" title="unsloth/&lt;Zeta&gt;-GGUF">unsloth/<wbr>&lt;Zeta&gt;-GGUF</small></span>'),
    "a row with a cell says the first cell's repository under its name, trimmed, escaped part by part, a break after the author's /");
pin(!zeta.includes("other/Zeta-GGUF"), "negative: the second cell's is not said");
pin(row(html, "Cosmos").includes('<span class="machine-model-title"><b class="machine-model-name">Cosmos</b></span>') && !row(html, "Gone-GGUF").includes("machine-model-repo"), "negative: a model with no cell, or whose cell's path names none, has one line: its author is not guessed");

// The picking: a row of the list picks which model the block above shows, and the block is drawn for that one model.
const blockOf = (text) => text.slice(0, text.indexOf("</section>"));
const pk = choice();
eq([pk.pick("Zeta-GGUF"), pk.pick("Zeta-GGUF"), pk.pick("Alpha-GGUF"), pk.pick(""), pk.picked], [true, false, true, false, "Alpha-GGUF"],
   "a pick says whether it changed: the same row pressed again does nothing; an empty name is not a model with no name, it is the state of nothing picked");
const moved = choice(); moved.pick("Alpha-GGUF"); moved.chose("Zeta-GGUF");
eq(moved.picked, "Zeta-GGUF", "and the block follows the chosen cell's model, named the same word a row's name is");
moved.chose("");
eq(moved.picked, "Zeta-GGUF", "negative: a cell whose model has no row here moves nothing: it stands among the cells with no model");

// The block at a drawing: with nothing picked it is still drawn, and says so in words.
pin(blockOf(html).includes('data-t="machine-chosen" data-t-id="" data-t-state="none"'), "nothing picked: its state names it, and the block is not hidden");
pin(blockOf(html).includes('<p class="machine-chosen-none" data-t="machine-chosen-none" data-t-state="none">Nothing is picked yet.</p>'),
    "the absence is said in words, not drawn as an empty block");
const picked = choice(); picked.pick("Zeta-GGUF");
const pickedHtml = list({ choice: picked }).html();
const shownBlock = blockOf(pickedHtml);
pin(shownBlock.includes('data-t="machine-chosen" data-t-id="Zeta-GGUF" data-t-state="chosen"'), "the model picked");
const parts = MachineModels.partsHtml(list({ choice: picked }).lines().find((l) => l.name === "Zeta-GGUF"));
pin(shownBlock.includes('<div class="machine-chosen-line" data-t="machine-chosen-line" data-t-id="Zeta-GGUF">') && shownBlock.includes(parts) && row(pickedHtml, "Zeta-GGUF").includes(parts),
    "the line in the block and the row of the list say the same parts, from one helper, so the two cannot say two things about one model");
pin(shownBlock.includes("<ACTS c22030>") && row(pickedHtml, "Zeta-GGUF").indexOf("<ACTS") < 0, "the cell rows with their buttons are in the block; a row of the list is a press and no place to act");
pin(!shownBlock.includes("data-model-rate"), "negative: the mark is not in the block: it stays on the row of the list, where a press keeps it");
pin(row(pickedHtml, "Zeta-GGUF").includes('<button type="button" class="machine-model-choose" aria-pressed="true" data-machine-model-choose="Zeta-GGUF" data-t="machine-model-choose" data-t-id="Zeta-GGUF" title="pick a model">'),
    "the row picked says it is pressed, and its hover says what a press on a row does");
pin(row(pickedHtml, "Alpha-GGUF").includes('aria-pressed="false" data-machine-model-choose="Alpha-GGUF"'), "negative: the rows not picked are not pressed");
pin(!shownBlock.includes("data-machine-model-new"), "negative: the block has no new-cell button: it stands at the end of the launch builder's rail (the owner's choice Б, 2026-11-08)");
{
  const built = list({ choice: picked, runners: { rows: [], takes: () => ({ ok: false }) } }).buildHtml();
  pin(/<span class="machine-build-end"[^>]*><strong class="machine-build-title">[^<]+<\/strong><button[^>]*data-machine-model-new="" data-machine-model-host="hotel" data-machine-model-name="Zeta-GGUF"/.test(built),
      "a new cell from the model picked is at the end of the builder's rail, with the button's own attributes: several builds, so the wizard opens on the model's words");
  pin(list({ choice: choice(), runners: { rows: [], takes: () => ({ ok: false }) } }).buildHtml().indexOf("data-machine-model-new") < 0,
      "negative: nothing picked — no rail, and no new cell of no model");
}
const idle = choice(); idle.pick("Cosmos");
pin(blockOf(list({ choice: idle }).html()).includes("No saved launch of this model"), "a model picked with no cell here says it has no saved launch");
pin(/data-machine-model="stt-GGUF"[^>]*data-machine-model-jobs="asr"/.test(html) && /data-machine-model="Zeta-GGUF"[^>]*data-machine-model-jobs="llm"/.test(html),
    "a row says its works, for the list to narrow without a drawing");
pin(!/data-machine-model-works/.test(html), "negative: it says nothing about a cell working: nothing reads that any more, since the buttons are not on the row");
const hiddenAway = choice(); hiddenAway.pick("Zeta-GGUF"); hiddenAway.only = "like";
pin(!/<div class="machine-model[^"]*" data-machine-model="Zeta-GGUF"[^>]* hidden>/.test(list({ choice: hiddenAway }).html()),
    "the picked row stands whatever the filter narrows the list to: it is the row the block is drawn for, and pressing it off would leave the block showing a model the list says is not picked");
pin(/<div class="machine-model[^"]*" data-machine-model="Alpha-GGUF"[^>]* hidden>/.test(list({ choice: hiddenAway }).html()),
    "negative: another model's row goes by the filter");
// What stands when the list is narrowed: the picked row, the chosen cell's row, and the cells with no row to pick. A drawing moves the pick to
// the chosen cell's model, so the block is where that cell says what it does and has its buttons.
{
  const narrowed = choice(); narrowed.narrowJob("asr"); narrowed.query = "nothing";
  const drawn = list({ map: { ...MAP, chosen: "c1a2b3c4d" }, choice: narrowed }).html();
  eq(narrowed.picked, "Zeta-GGUF", "a drawing moves the pick to the chosen cell's model, so a choice always has a place to act from");
  pin(blockOf(drawn).includes('data-t-id="Zeta-GGUF" data-t-state="chosen"'), "and the block shows it");
  pin(!/<div class="machine-model[^"]*" data-machine-model="Zeta-GGUF"[^>]* hidden>/.test(drawn), "its row in the list stands too, whatever the work and the words");
  pin(!/data-machine-pick="c1a2b3c4d" data-machine-jobs="llm"[^>]* hidden>/.test(drawn), "and the chosen cell's own row, of another work than the one shown");
  pin(/data-machine-pick="c22030" data-machine-jobs="llm"[^>]* hidden>/.test(drawn), "negative: its neighbour of the same model goes by the work: the chosen cell stands, not its model's cells");
  pin(/<div class="machine-model[^"]*" data-machine-model="Alpha-GGUF"[^>]* hidden>/.test(drawn), "negative: another model's row goes by the filter");
  eq([MachineModelsChoice.keepsCell(["llm"], "asr", false), MachineModelsChoice.keepsCell(["llm"], "asr", true), MachineModelsChoice.keepsCell(["asr"], "asr", false), MachineModelsChoice.keepsCell([], "", false)],
     [false, true, true, true], "a cell's own row: by its work, or chosen");
  const words = choice(); words.query = "nothing";
  pin(!/data-machine-models-rest hidden/.test(list({ map: { ...MAP, chosen: "c22050" }, choice: words }).html()), "a cell with no row to pick, chosen, stands while the list is searched");
  pin(/data-machine-models-rest hidden/.test(list({ map: { ...MAP, chosen: "c1a2b3c4d" }, choice: words }).html()), "negative: with another one chosen they go with the search");
}
// The longest context a model was trained for, on its row.
{
  const said = (chosenLines, name) => MachineModels.contextHtml(chosenLines.find((l) => l.name === name));
  const safe = (words) => String(words).replace(/'/g, "&#39;");
  const inRow = list().lines();
  eq(said(inRow, "Cosmos"), `<span class="machine-model-context" data-t="machine-model-context" data-t-id="Cosmos" data-t-state="known" title="${safe(en.mdlWindowTip)}">🎓 8.2k</span>`, "the window a folder's config states, under the 🎓 of its cells");
  pin(said(inRow, "Zeta-GGUF").includes(">🎓 65.5k – 262k<"), "a range when its builds differ, and its cells' models are counted in: 131k lies inside");
  eq(said(inRow, "Alpha-GGUF"), `<span class="machine-model-context is-dim" data-t="machine-model-context" data-t-id="Alpha-GGUF" data-t-state="unknown" title="${safe(en.mdlWindowUnknownTip)}">${en.mdlWindowUnknown}</span>`, "a model that takes a window nobody stated says so");
  eq(said(inRow, "stt-GGUF"), `<span class="machine-model-context is-dim" data-t="machine-model-context" data-t-id="stt-GGUF" data-t-state="none" title="${safe(en.mdlWindowNoneTip)}">—</span>`, "work with no window in tokens: a dash");
  pin(said(inRow, "Gone-GGUF").includes('data-t-state="unknown"'), "a model only a cell names, whose cell knows no window: not known");
  pin(!inRow.some((l) => MachineModels.contextHtml(l).includes("🎓 0")), "negative: never a zero");
  const told = { ...MAP, cells: new Map([...CELLS, ["c5e1d7a90", cell({ model: "Gone-GGUF", runner: "vLLM", ctx: { set: 0, max: 4096 }, jobs: ["llm"] })]]) };
  pin(said(list({ map: told }).lines(), "Gone-GGUF").includes(">🎓 4.1k<"), "what its cell's model says is all there is of a model the library does not list");
  const wholeRow = row(list().html(), "Zeta-GGUF");
  pin(wholeRow.indexOf("machine-model-job") < wholeRow.indexOf("machine-model-context") && wholeRow.indexOf("machine-model-context") < wholeRow.indexOf("machine-model-sizes"), "its place on the row: between the work and the size");
  eq(MachineModels.contextHtml({ name: "Nothing", window: { lo: Infinity, hi: 0, unnamed: false, models: 0 } }),
     '<span class="machine-model-context is-dim" data-t="machine-model-context" data-t-id="Nothing" data-t-state="none"></span>', "a row with no model to speak of says nothing, and its column stays");
}
eq(list({ choice: picked }).lines().map((l) => l.name), lines.map((l) => l.name), "a row never moves under a pick");
const otherPick = choice(); otherPick.pick("stt-GGUF"); otherPick.pick("Alpha-GGUF");
eq(list({ choice: otherPick }).lines().map((l) => l.name), lines.map((l) => l.name), "nor does the block move it: the order is the library's, not the pick's");

// A cell's row, on two lines, in the block of the model picked.
const pickedZeta = choice(); pickedZeta.pick("Zeta-GGUF");
const opened = blockOf(list({ choice: pickedZeta }).html());
pin(opened.includes("<ACTS c22030>") && opened.includes("<ACTS c1a2b3c4d>"), "the cells of the model picked stand in the block");
const launch = (over = {}) => list(over).launchHtml(NODE.servers[0], "");
const r30 = launch();
pin(r30.startsWith('<div class="machine-model-launch" data-machine-pick="c22030" data-machine-jobs="llm" data-t="machine-model-launch" data-t-id="c22030" title="click a cell to plan it, or drag it up onto the rack">'),
    "the whole row chooses its cell, says its works, and says so in its hover");
pin(r30.includes('<button type="button" class="machine-model-port" aria-pressed="false" data-machine-pick="c22030" data-t="machine-model-cell" data-t-id="c22030" title="c22030 name — click to choose"><span class="machine-model-dot" aria-hidden="true"></span>c22030</button>'),
    "its own name, the cellId, with a dot: a button for the keyboard, named in its hover as the page names the cell, and the dot says nothing to a screen reader");
pin(!/:\d{4,5}\b|\b220\d\d\b/.test(r30.replace(/data-start-a="[^"]*"/g, "")), "negative: no port number in a cell's row — a stopped cell holds none, and a running one's is its run's");
const lineParts = (text) => [...text.matchAll(/<div class="machine-model-line">/g)].length;
eq(lineParts(r30), 2, "two lines");
const [first, second] = r30.split('<div class="machine-model-line">').slice(1);
pin(first.includes('<span class="machine-model-runner">llama.cpp</span><span class="machine-model-quant">Q4</span><span class="machine-model-ctx" data-t="machine-model-ctx" data-t-id="c22030" data-t-state="both"')
    && first.includes('<span class="machine-model-set" title="parallel 3 · temp 1.0">parallel 3 · temp 1.0</span></div>'), "the first line: its runner, its build, its windows, what else it sets");
pin(second.startsWith('<span class="machine-bench-size" data-machine-bench-size="c22030">≈c22030 GB</span><span class="machine-bench-fit machine-bench-fit--good" data-machine-bench-fit="c22030" data-t-state="card">fits c22030</span></div>'),
    "the second line: its size and its verdict, with its tone and its state, under the names the live patch finds them by");
pin(r30.endsWith('<span class="machine-model-acts" data-machine-own><button type="button" class="ui-btn ui-btn--icon machine-model-note-add" data-cell-note="c22030" data-cell-note-name="c22030 name" data-machine-own'
                + ' data-t="machine-model-note-add" data-t-id="c22030" title="Add a note to this cell" aria-label="Add a note to this cell">✎</button><ACTS c22030></span><CHOICE c22030></div>'),
    "its buttons at the end, under names of their own, marked as their own; a cell with no note has the ✎ that asks for one first");
// The cell's note in its row (the owner, 2026-11-03: "sign the cells, a comment of my own, visible here"): the one its card and window had.
st.setTopology({ nodes: [], cellNotes: { c22030: "for the coder <b>" } });
const noted = list().launchHtml(NODE.servers[0], "");
pin(noted.includes('</div><button type="button" class="machine-model-note" data-cell-note="c22030" data-cell-note-name="c22030 name" data-machine-own data-t="machine-model-note" data-t-id="c22030"')
    && noted.includes('>💬 for the coder &lt;b&gt;</button><span class="machine-model-acts"'), "a noted cell says its note under its two lines, escaped, and a press on it asks for it again");
pin(!noted.includes("machine-model-note-add"), "negative: a noted cell has no ✎ besides its words");
st.setTopology({ nodes: [], cellNotes: {} });
pin(!list().launchHtml(NODE.servers[0], "").includes('class="machine-model-note"'), "negative: no note, no line");
pin(r30.indexOf("machine-model-port") < r30.indexOf('machine-model-line') && r30.lastIndexOf("machine-model-line") < r30.indexOf("machine-model-acts"), "port, lines, buttons, in that order");
pin(!r30.includes("machine-model-cell-name"), "negative: under a model's row it does not say the name again");
pin(!/data-machine-bench-fit="c22030"[^>]* title=/.test(r30), "negative: a verdict that did not fail has no reason in its hover");
const failedRow = list().launchHtml(NODE.servers[2], "");
pin(failedRow.includes('data-machine-bench-fit="c5e1d7a90" data-t-state="failed" title="out of &lt;memory&gt;">'), "a failed cell's reason is in its verdict's hover, escaped");
const chosenLaunch = list({ map: { ...MAP, chosen: "c1a2b3c4d" } }).launchHtml(NODE.servers[1], "");
pin(chosenLaunch.startsWith('<div class="machine-model-launch is-on" data-machine-pick="c1a2b3c4d"') && chosenLaunch.includes('class="machine-model-port is-on" aria-pressed="true" data-machine-pick="c1a2b3c4d"'), "the chosen row is highlighted, and its port says so");
pin(!chosenLaunch.startsWith('<div class="machine-model-launch is-on" data-machine-pick="c1a2b3c4d" aria-pressed'), "negative: the row is no button and says no pressed");
const stoppedOther = list({ map: { ...MAP, chosen: "c1a2b3c4d" } }).launchHtml(NODE.servers[0], "");
pin(!stoppedOther.includes("is-on"), "negative: another cell's row is not");
const lonely = choice(); lonely.pick("Cosmos");
pin(blockOf(list({ choice: lonely }).html()).includes("No saved launch of this model"), "a model picked with no cell here: said in the block, where its cells would be");

// The cells with no row to pick: they stand in the block, which is the only place to choose one, to start it or to open its window, and the
// words that say why they have no row name them there. Each has a row, or it could not be chosen at all while it stands.
pin(html.includes('data-t="machine-models-outside">Their model lies outside the library: c22050 name<'), "a cell with no row is named as the page names it (cellName), and one with no model yet is not");
pin(!/Their model lies outside the library: [^<]*:\d/.test(html), "negative: no port names it");
pin(!pageOf(new MachineModels({ map: { ...MAP, node: { id: "h", servers: NODE.servers.slice(0, 3) } }, rows: ROWS, choice: choice() })).includes("machine-models-rest"), "every cell has its row: no such words");
const rest = blockOf(html).slice(blockOf(html).indexOf('data-machine-models-rest'));
pin(rest.includes('data-machine-pick="c22050"') && rest.includes('data-machine-pick="c22060"') && rest.includes("<ACTS c22050") && rest.includes("<ACTS c22060"), "the cell outside and the cell with no model each have a row to choose and act on");
pin(rest.includes('<strong class="machine-model-cell-name">ollama-qwen · 💬 LLM</strong>') && rest.includes('<strong class="machine-model-cell-name">Reserved cell</strong>'), "with no model's row to pick them they say their name and work; a work out of the vocabulary is not named");
const nameless = new MachineModels({ map: { ...MAP, cells: new Map([["c22060", cell({ model: "", listed: "", jobs: ["llm"], ctx: null })]]) }, choice: choice() }).launchHtml(NODE.servers[4], "", { named: true });
pin(nameless.includes('<strong class="machine-model-cell-name">💬 LLM</strong>'), "negative: a cell nobody named says its work alone, with no dot before it");
pin(blockOf(html).includes("data-machine-models-rest") && blockOf(html).length < html.length && html.indexOf("data-machine-models-rest") < html.indexOf('data-machine-model="Zeta-GGUF"'),
    "the block is the page's first thing, the list of rows comes after it, and the cells with no row to pick are in the block, not among the rows");
pin(!rest.includes('data-machine-pick="c22030"'), "negative: a cell with a model's row to pick is not among them");
const keepsRest = (over, jobs, job) => { const c = choice(); Object.assign(c, over); return c.keepsRest(jobs, job); };
eq([keepsRest({}, [["llm"], []], ""), keepsRest({ only: "cells" }, [["llm"]], ""), keepsRest({ only: "like" }, [["llm"]], ""), keepsRest({ query: " x " }, [["llm"]], ""), keepsRest({}, [["llm"], []], "asr"), keepsRest({}, [["llm"], []], "llm")],
   [true, true, false, false, false, true], "they stand: not while the list is searched by words or a mark, which they cannot answer; not when none of them does the work");
const searched = choice(); searched.query = "zeta";
pin(/data-machine-models-rest hidden>/.test(list({ choice: searched }).html()), "words typed: they go, at a drawing");
pin(pageOf(new MachineModels({ map: { ...MAP, node: { id: "h", servers: NODE.servers.slice(3) } }, rows: [], choice: choice() })).includes('data-machine-pick="c22050"') && pageOf(new MachineModels({ map: { ...MAP, node: { id: "h", servers: NODE.servers.slice(3) } }, rows: [], choice: choice() })).includes('data-t="machine-models" data-t-state="empty"'), "no model at all: the cells still stand, and the list says it is empty");
pin(pageOf(new MachineModels({ map: { ...MAP, node: { id: "h", servers: NODE.servers.slice(3) } }, rows: [], choice: choice() })).includes('data-t="machine-chosen" data-t-id="" data-t-state="none"'), "negative: and the block still stands, saying nothing is picked");

// What its makers recommend.
const said = (texts, unread = false) => { const c = choice(); c.texts = texts; c.unread = unread; return list({ choice: c }).saidHtml("Zeta-GGUF"); };
pin(said({ "Zeta-GGUF": "top_k 20 <b>" }).includes("Recommended by its makers.") && said({ "Zeta-GGUF": "top_k 20 <b>" }).includes("top_k 20 &lt;b&gt;"), "kept: said, escaped");
eq([said({}), said({ "Zeta-GGUF": "   " }), said({ constructor: "x" }), said(null)], ["", "", "", ""], "nothing kept, or not read yet: nothing drawn, and a word an object answers to is no text");
pin(said(null, true).includes('data-t-state="unread"') && said(null, true).includes("could not be read"), "could not be read: said so, not as if it said nothing");

// What the maker stated once: the numbers the launch builder offers as the model's own set.
const stated = (values, name = "Zeta-GGUF") => { const c = choice(); c.stated = values; return list({ choice: c }).statedHtml(name); };
pin(stated({ "Zeta-GGUF": { TOP_K: "20", TEMPERATURE: "1.0" } }).includes("Stated once by its makers.")
  && stated({ "Zeta-GGUF": { TOP_K: "20", TEMPERATURE: "1.0" } }).includes("TOP_K 20, TEMPERATURE 1.0"), "kept: each value names itself, so the source is named per field");
eq([stated({}), stated({ "Zeta-GGUF": {} }), stated({ constructor: { TOP_K: "1" } }), stated(null), stated({ "Other-GGUF": { TOP_K: "20" } })],
  ["", "", "", "", ""], "negative: a model the table does not name has nothing stated once, and that is not a gap the row fills with the prose");
pin(stated({ "Zeta-GGUF": { TOP_K: "<b>" } }).includes("TOP_K &lt;b&gt;"), "escaped");

// Where the texts stand (the owner, 2026-11-06, variant А of the mockups): on the row that is picked, not in the block, so the block stays the
// short part of the map it is. A model whose texts are not read yet says that on its own word, on the same row.
const read = choice(); read.pick("Zeta-GGUF"); read.texts = { "Zeta-GGUF": "top_k 20" }; read.stated = { "Zeta-GGUF": { TOP_K: "20" } };
const readRow = list({ choice: read }).html();
pin(row(readRow, "Zeta-GGUF").includes("Recommended by its makers.") && row(readRow, "Zeta-GGUF").includes("Stated once by its makers."),
    "the row that is picked shows what its makers said, under its parts");
pin(!blockOf(readRow).includes("machine-model-said"), "negative: the block holds no texts: they live on the row that picked them");
pin(!row(readRow, "Alpha-GGUF").includes("machine-model-said"), "negative: a row that is not picked has nothing to say but its parts");
pin(!stated({ "Zeta-GGUF": { TOP_K: "20" } }).includes("unread"), "negative: nothing stated once is not the same as a text not read yet");
pin(stated({ "Zeta-GGUF": { TOP_K: "20" } }).includes('data-t-state="stated"'), "the row says which of the two lines it is");

// A cell an older controller marked as a model's default one is drawn as any other: no origin, no word of a missing file, the hint alone in its hover.
const plainCell = cell({ model: "Zeta-GGUF", quant: "Q4", ctx: null });
const rowOf = (c) => new MachineModels({ map: { ...MAP, cells: new Map([["c22060", c]]) }, choice: choice() }).launchHtml(NODE.servers[4], "", { named: true });
const plainRow = rowOf(plainCell);
eq(rowOf({ ...plainCell, defaultFor: "Zeta-GGUF" }), plainRow, "an old mark of a default cell changes nothing in the row");
pin(!plainRow.includes('data-t-state="default"') && plainRow.includes(`title="${String(en.machineCellRowHint).replace(/'/g, "&#39;")}"`),
    "negative: the row names no origin — the hover is the hint alone");

// A new cell.
const button = (name, over = {}) => { const c = choice(); return list({ choice: c, ...over }).newHtml(list().lines().find((l) => l.name === name)); };
pin(button("Alpha-GGUF").includes('data-machine-model-new="Alpha-GGUF/a/Q4/alpha-00001-of-00002.gguf"') && button("Alpha-GGUF").includes('data-machine-model-host="hotel"'), "one build: the wizard goes on from it");
pin(button("Zeta-GGUF").includes('data-machine-model-new=""') && button("Zeta-GGUF").includes('data-machine-model-name="Zeta-GGUF"') && button("Zeta-GGUF").includes('data-machine-model-job="llm"'), "several: it opens on the model's words and work");
pin(!/ disabled/.test(button("Zeta-GGUF")) && / disabled/.test(button("Zeta-GGUF", { reserving: true })) && / disabled/.test(button("Gone-GGUF")), "shut while a cell is being reserved, and with no file to start from");

// The filters, the work and the words typed: one rule.
const c = choice();
const L = (name, cells = 0, mark = "", jobs = []) => ({ name, cells, mark, shownJobs: jobs });
eq([c.keeps(L("A"), ""), (c.narrow("cells"), c.keeps(L("A"), "")), c.keeps(L("A", 1), ""), (c.narrow("cells"), c.only)], [true, false, true, ""], "with a cell here; pressed again it lets go");
eq([(c.narrow("like"), c.keeps(L("A", 1), "")), c.keeps(L("A", 0, "like"), ""), c.keeps(L("A", 0, "dislike"), "")], [false, true, false], "👍 keeps the liked ones only");
c.narrow("");
c.query = "  ZET ";
eq([c.keeps(L("Zeta-GGUF"), ""), c.keeps(L("Alpha"), "")], [true, false], "the words typed, any case, spaces trimmed");
const j = choice();
eq([j.keeps(L("A", 0, "", ["llm"]), "llm"), j.keeps(L("A", 0, "", ["llm", "asr"]), "asr"), j.keeps(L("A", 0, "", ["asr"]), "llm"), j.keeps(L("A", 0, "", []), "llm"), j.keeps(L("A", 0, "", ["asr"]), "")],
   [true, true, false, false, true], "a row stays when its model does the work; negative: one that does another, or says none, goes; no work chosen keeps it");
j.query = "zeta";
eq([j.keeps(L("Zeta", 0, "", ["llm"]), "llm"), j.keeps(L("Alpha", 0, "", ["llm"]), "llm"), j.keeps(L("Zeta", 0, "", ["asr"]), "llm")], [true, false, false], "the work and the words together: it has to answer both");
j.query = ""; j.only = "like";
eq([j.keeps(L("Zeta", 0, "like", ["llm"]), "llm"), j.keeps(L("Zeta", 0, "", ["llm"]), "llm"), j.keeps(L("Zeta", 0, "like", ["asr"]), "llm")], [true, false, false], "the work and a filter together too");
eq([j.narrowJob("llm"), j.job, j.narrowJob("asr"), j.narrowJob("asr"), j.job, j.narrowJob(undefined)], ["llm", "llm", "asr", "", "", ""], "a work pressed narrows, another takes its place, the same again lets it go");

const filtered = choice(); filtered.only = "like";
const narrowed = list({ choice: filtered }).html();
pin(/data-machine-model="stt-GGUF"[^>]*data-t-state="none">/.test(narrowed) && /data-machine-model="Zeta-GGUF"[^>]* hidden>/.test(narrowed), "a drawing keeps the filter");
pin(/data-machine-models-only="like"[^>]*>👍 <span class="ui-count">1<\/span>/.test(narrowed) && narrowed.includes('aria-pressed="true" data-machine-models-only="like"'), "the filter is pressed and counts");
pin(/data-machine-models-only=""[^>]*>All <span class="ui-count">6<\/span>/.test(narrowed) && /data-machine-models-only="cells"[^>]*>With a cell here <span class="ui-count">2<\/span>/.test(narrowed), "the other filters count too");
pin(/data-machine-models-none[^>]* hidden>/.test(narrowed), "something stays: no word");
const nothing = choice(); nothing.query = "nope";
pin(/data-machine-models-none data-t="machine-models-none">No model matches/.test(list({ choice: nothing }).html()), "nothing stays: said");
const typedAgain = choice(); typedAgain.query = 'a"b';
pin(list({ choice: typedAgain }).html().includes('value="a&quot;b"'), "the words typed stay in the box, escaped");
const bare = { ...MAP, node: { id: "h", servers: [] }, cells: new Map(), benchJobs: () => [] };
pin(pageOf(new MachineModels({ map: bare, choice: choice() })).includes('data-t-state="empty"') && pageOf(new MachineModels({ map: bare, choice: choice() })).includes("The library holds no models"), "an empty library is said apart");
pin(!pageOf(new MachineModels({ map: bare, choice: choice() })).includes("machine-models-jobs"), "negative: no cell says what it does: no row of pills");

// The pills of the work, under the head, and the words of each part.
pin(html.includes('<strong class="machine-models-title">Models</strong>') && html.includes('<span class="machine-models-hint">pick a model</span>'), "the head of the list: its title and what a press on its rows does");
pin(blockOf(html).includes('<strong class="machine-chosen-title">The model picked</strong>') && blockOf(html).includes('<span class="machine-chosen-hint">its cells, and their Cell window and Start, are here</span>'),
    "the block has its own title and its own words: the picking and the acting are not one block's words any more");
pin(blockOf(html).includes('title="click a cell to plan it, or drag it up onto the rack"'), "and the word a cell's row has is its own, not the head's");
pin(html.includes('<div class="machine-models-jobs" role="group" aria-label="Work"><button type="button" class="ui-pill" aria-pressed="false" data-machine-job="llm" data-t="machine-models-job" data-t-id="llm">💬 LLM <span class="ui-count">4</span></button><button type="button" class="ui-pill" aria-pressed="false" data-machine-job="asr" data-t="machine-models-job" data-t-id="asr">🎧 speech → text <span class="ui-count">1</span></button></div>'),
    "a second row: each work with its mark and how many cells do it, none pressed");
pin(html.indexOf("machine-models-head") < html.indexOf("machine-models-jobs") && html.indexOf("machine-models-jobs") < html.indexOf("machine-models-list"), "under the head, over the list");
const onJob = choice(); onJob.job = "asr";
const jobbed = list({ choice: onJob }).html();
pin(jobbed.includes('aria-pressed="true" data-machine-job="asr"') && jobbed.includes('aria-pressed="false" data-machine-job="llm"'), "a work chosen: its pill is pressed, at a drawing");
pin(!/data-machine-model="stt-GGUF"[^>]* hidden>/.test(jobbed) && /data-machine-model="Zeta-GGUF"[^>]* hidden>/.test(jobbed) && /data-machine-model="Cosmos"[^>]* hidden>/.test(jobbed), "the rows that do it stay, those that do not are hidden");
pin(/data-machine-models-rest hidden>/.test(jobbed), "and the cells with no row, none of which does it");
const wordy = choice(); wordy.job = "asr"; wordy.query = "zeta";
pin(/data-machine-models-none data-t="machine-models-none">No model matches/.test(list({ choice: wordy }).html()), "the work and the words leave none: said, as the list says it");
const staleJob = choice(); staleJob.job = "voice-chat";
const stale = list({ choice: staleJob }).html();
pin(!stale.includes('aria-pressed="true" data-machine-job=') && !/data-machine-model="Zeta-GGUF"[^>]* hidden>/.test(stale), "negative: a work no cell here does (chosen on another machine) narrows nothing: no pill would let it go");
// A model that does two works, its cells one each: picked, its row stays, and in the block the cell of the other work is hidden.
const mixedCells = new Map([["c1", cell({ model: "Twin-GGUF", jobs: ["llm"] })], ["c2", cell({ model: "Twin-GGUF", jobs: ["asr"] })], ["c3", cell({ model: "Twin-GGUF", jobs: [] })]]);
const mixedMap = { ...MAP, cells: mixedCells, node: { id: "h", servers: [{ cellId: "c1", port: 22101, phase: "running", slotConfig: {} }, { cellId: "c2", port: null, phase: "stopped", slotConfig: {} },
                                                                          { cellId: "c3", port: null, phase: "stopped", slotConfig: {} }] } };
const mixedChoice = choice(); mixedChoice.pick("Twin-GGUF"); mixedChoice.job = "asr";
const mixed = pageOf(new MachineModels({ map: mixedMap, choice: mixedChoice }));
const launchHidden = (text, cellId) => new RegExp(`<div class="machine-model-launch" data-machine-pick="${cellId}"[^>]* hidden>`).test(text);
eq([launchHidden(mixed, "c1"), launchHidden(mixed, "c2"), launchHidden(mixed, "c3"), /data-machine-model="Twin-GGUF"[^>]* hidden>/.test(mixed)], [true, false, true, false], "in the block of the picked model, a cell that does not do the work is hidden; one that says none as well; the row that picked it stays");
pin(blockOf(mixed).includes('data-t="machine-chosen" data-t-id="Twin-GGUF" data-t-state="chosen"'), "and the block is drawn for that model");
mixedChoice.job = "";
pin(!["c1", "c2", "c3"].some((cellId) => launchHidden(pageOf(new MachineModels({ map: mixedMap, choice: mixedChoice })), cellId)), "negative: no work chosen: all of them show");

// Shown in place, on a page of stand-ins. The list is shown by hiding and pressing; the block is drawn for one model, so `show` says when the
// page has to be drawn again — and the list never makes it draw.
const el = (dataset, kids = {}) => {
  const e = { dataset, hidden: false, attrs: {}, on: new Set(), setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; }, querySelector: (sel) => kids[sel] || null, querySelectorAll: () => [] };
  e.classList = { toggle: (cls, on) => (on ? e.on.add(cls) : e.on.delete(cls)) };
  return e;
};
const rowEl = (name, cells, mark, jobs = "") => {
  const choose = el({});
  return Object.assign(el({ machineModel: name, machineModelCells: String(cells), machineModelMark: mark, machineModelJobs: jobs }, { "[data-machine-model-choose]": choose }), { choose });
};
const countEl = () => ({ textContent: "" });
const pillOf = (only) => { const count = countEl(); return Object.assign(el({ machineModelsOnly: only }, { ".ui-count": count }), { count }); };
const rows = [rowEl("Zeta", 2, "", "llm"), rowEl("Alpha", 0, "like", "llm asr"), rowEl("Cosmos", 0, "", "asr")];
const pills = ["", "cells", "like"].map(pillOf);
const jobPills = ["llm", "asr"].map((job) => el({ machineJob: job }));
const cellsOf = [["llm"], ["asr"], [""]].map(([jobs]) => el({ machineJobs: jobs }));
const none = el({});
const restEl = el({});
const blockEl = el({ tId: "" });
const page = {
  querySelectorAll: (sel) => (sel === "[data-machine-model]" ? rows : sel === "[data-machine-models-only]" ? pills : sel === "[data-machine-job]" ? jobPills : sel === "[data-machine-jobs]" ? cellsOf : []),
  querySelector: (sel) => (sel === "[data-machine-models-none]" ? none : sel === "[data-machine-models-rest]" ? restEl : sel === '[data-t="machine-chosen"]' ? blockEl : null),
};
restEl.querySelectorAll = (sel) => (sel === "[data-machine-jobs]" ? cellsOf.slice(2) : []);
eq(MachineModelsChoice.lineOf(rows[0]), { name: "Zeta", cells: 2, mark: "", shownJobs: ["llm"] },
   "what a row says of itself: its name, its cells, its mark, its works — and nothing else, since a row here acts nowhere");
const shown = choice();
shown.only = "cells"; shown.show(page);
eq(rows.map((r) => r.hidden), [false, true, true], "the rows the filter leaves");
eq(rows.map((r) => r.choose.attrs["aria-pressed"]), ["false", "false", "false"], "nothing picked: no row says it is pressed");
eq(pills.map((p) => [p.attrs["aria-pressed"], p.count.textContent]), [["false", "3"], ["true", "1"], ["false", "1"]], "the filters pressed and their counts");
eq(none.hidden, true, "something stays: no word");
eq(shown.show(page), false, "shown again with nothing moved: the list is shown in place, so nothing is drawn");
eq([shown.pick("Alpha"), shown.show(page)], [true, true], "a pick moves the block to another model: the page has to be drawn again for it");
blockEl.dataset.tId = "Alpha";                       // what a drawing of the board writes on the block
eq(shown.show(page), false, "and the same model again says nothing to draw: the block is already drawn for it");
eq([rows[1].hidden, rows[1].choose.attrs["aria-pressed"]], [false, "true"], "the picked row stands under a filter it would not answer, and says it is pressed");
shown.only = ""; shown.query = "nope"; shown.show(page);
eq([rows.map((r) => r.hidden), none.hidden], [[true, false, true], true], "the picked row stands while the list is searched, and the word says nothing else stayed");
shown.query = ""; shown.only = "like"; shown.show(page);
eq(rows.map((r) => r.hidden), [true, false, true], "the 👍 filter, with the picked row kept by the pick");
shown.marked(page, "Cosmos", "like");
eq([rows[2].dataset.machineModelMark, rows[2].hidden, pills[2].count.textContent], ["like", false, "2"], "a mark pressed: the row and the count follow at once");
shown.marked(page, "Cosmos", "");
eq([rows[2].hidden, pills[2].count.textContent], [true, "1"], "a mark taken off: it leaves the 👍 filter");
shown.only = "";
shown.narrowJob("asr"); shown.show(page);
eq([rows.map((r) => r.hidden), jobPills.map((p) => p.attrs["aria-pressed"]), cellsOf.map((cl) => cl.hidden), restEl.hidden], [[true, false, false], ["false", "true"], [true, false, true], true], "a work pressed, in place: the rows that do it, the pill, the cell rows, the cells with no row to pick");
shown.query = "alp"; shown.show(page);
eq(rows.map((r) => r.hidden), [true, false, true], "with the words typed: one rule, neither overwrites the other");
shown.query = "cosmo"; shown.only = "like"; shown.show(page);
eq([rows.every((r) => r.hidden), none.hidden], [false, true], "negative: the picked row is not the word 'nothing matches': it stayed");
shown.query = ""; shown.only = ""; shown.narrowJob("asr"); shown.show(page);
eq([rows.map((r) => r.hidden), jobPills.map((p) => p.attrs["aria-pressed"]), cellsOf.map((cl) => cl.hidden), restEl.hidden, none.hidden], [[false, false, false], ["false", "false"], [false, false, false], false, true], "the same again lets it go");
shown.job = "voice-chat"; shown.show(page);
eq([rows.map((r) => r.hidden), jobPills.map((p) => p.attrs["aria-pressed"])], [[false, false, false], ["false", "false"]], "negative: a work with no pill narrows nothing here either");
shown.job = "";
// The block follows the chosen cell's model, and says when the page must be drawn again.
eq([shown.show(page, "Zeta"), shown.picked], [true, "Zeta"], "the chosen cell's model moves the block: the page has to be drawn again for it");
blockEl.dataset.tId = "Zeta";                        // what the drawing writes on the block
eq(shown.show(page), false, "and the same model again says nothing to draw");
eq(shown.show(page, "Ghost"), false, "negative: a model with no row here does not move the block: its cell stands among the cells with no model");
eq(shown.show(page, ""), false, "negative: a cell that names no model moves nothing either");

// A choice on the rack moves the block to its model, through the pick's own listener: what cannot be shown in place draws the page.
{
  const lanePick = { dataset: { machinePick: "c22030", t: "machine-map-block" }, closest: () => null };
  const launchEl = { dataset: { machinePick: "c22030", t: "machine-model-launch" }, on: new Set(), classList: { toggle(cls, on) { if (on) launchEl.on.add(cls); else launchEl.on.delete(cls); } } };
  const modelRow = rowEl("Zeta", 1, "", "llm");
  const blockStand = el({ tId: "" });
  const docListeners = [];
  const asked = [];
  const pageDoc = { addEventListener: (type, fn) => docListeners.push([type, fn]),
                     querySelector: (sel) => (sel.startsWith(".machine-model-launch[") ? { scrollIntoView: (how) => asked.push(["row", how]) } : sel.startsWith(".fold-slot") ? {} : sel === '[data-t="machine-chosen"]' ? blockStand : null),
                     querySelectorAll: (sel) => (sel === "[data-machine-model]" ? [modelRow] : sel === "[data-machine-pick]" ? [launchEl] : []) };
  const list2 = choice();
  const pick2 = new MachinePick();
  pick2.know(new Map([["c22030", { group: "holds", key: "h:1", window: true, listed: "Zeta" }], ["c22050", { group: "holds", key: "h:5", window: true, listed: "" }]]));
  let draws = 0;
  const asMainDoes = (root, model) => { if (list2.show(root, model)) draws += 1; };
  pick2.bind(pageDoc, { redraw: () => { draws += 1; }, listed: asMainDoes });
  const clicked = (target) => docListeners.filter(([type]) => type === "click").forEach(([, fn]) => fn({ preventDefault() {}, target }));
  const onBlock = { closest: (sel) => (sel === "[data-machine-pick]" ? lanePick : null) };
  clicked(onBlock);
  eq([pick2.cellId, list2.picked, blockStand.dataset.tId, draws], ["c22030", "Zeta", "", 1], "a block on the rack chosen: the block of models moves to its model, and the page is drawn again, because it is drawn for one model");
  eq(asked.map(([what]) => what), ["row"], "and the row is brought into sight");
  blockStand.dataset.tId = "Zeta";
  asked.length = 0;
  clicked(onBlock);
  eq([pick2.cellId, list2.picked, draws], ["", "Zeta", 1], "let go: the choice goes, the block stays on what was picked, and nothing is drawn again");
  eq(asked, [], "negative: letting a cell go brings nothing into sight");
  clicked({ closest: (sel) => (sel === "[data-machine-pick]" ? { dataset: { machinePick: "c22050", t: "machine-model-launch" } } : null) });
  eq([pick2.cellId, list2.picked, draws], ["c22050", "Zeta", 1], "negative: a cell with no model to name does not move the block, and nothing is drawn for it");
  eq(asked.map(([what]) => what), ["row"], "but its row, which stands in the block, is brought into sight");
  asked.length = 0;
  const inBlock = { dataset: { machinePick: "c22030", t: "machine-model-launch" }, closest: (sel) => (sel === '[data-t="machine-chosen"]' ? {} : null) };
  clicked({ closest: (sel) => (sel === "[data-machine-pick]" ? inBlock : null) });
  eq([pick2.cellId, asked.map(([what]) => what)], ["c22030", ["row"]], "chosen in the block too: its row may fall under the pane's edge, and the pane moves by that much and no more");
}

// The texts.
const reader = choice();
let answers = [], asked = 0, drawn = 0;
reader.read = async () => { asked += 1; const a = answers.shift(); if (a instanceof Error) throw a; return a; };
reader.redraw = () => { drawn += 1; };
answers = [{ params: { a: "x" } }];
eq([await reader.readTexts(), reader.texts, drawn], [true, { a: "x" }, 1], "read: drawn with the texts");
answers = [{ params: { a: "x" } }];
eq([await reader.readTexts(), drawn], [false, 1], "the same again: no drawing");
answers = [new Error("down")];
eq([await reader.readTexts(), reader.texts, reader.unread, drawn], [false, { a: "x" }, false, 1], "a failure after a reading keeps what was read");
const failing = choice();
failing.read = async () => { throw new Error("down"); };
failing.redraw = () => { drawn += 1; };
eq([await failing.readTexts(), failing.texts, failing.unread, drawn], [true, null, true, 2], "a failure with nothing read: said, drawn once");
eq([await failing.readTexts(), drawn], [false, 2], "and not drawn again");
answers = [{ params: { a: "x" }, defaults: { a: { TOP_K: "20" } } }];
eq([await reader.readTexts(), reader.stated, drawn], [true, { a: { TOP_K: "20" } }, 3], "the numbers stated once are read with the texts and drawn with them");
answers = [{ params: { a: "x" }, defaults: { a: { TOP_K: "20" } } }];
eq([await reader.readTexts(), drawn], [false, 3], "the same again: no drawing");
answers = [{ params: { a: "x" } }];
eq([await reader.readTexts(), reader.stated, drawn], [true, null, 4], "negative: a table that names nothing for a model is read as nothing, not as a text not read yet");
const once = choice();
let reads = 0;
once.read = async () => { reads += 1; return { params: {} }; };
await once.readOnce(); await once.readOnce();
eq(reads, 1, "a page's drawings read them once");

// The listeners.
const listeners = {};
const doc = { addEventListener: (type, fn) => { listeners[type] = fn; }, querySelectorAll: () => [], querySelector: () => null };
const bound = choice();
const opened2 = [];
let boundDraws = 0;
let boundReads = 0;
bound.bind(doc, { read: async () => { boundReads += 1; return { params: {} }; }, redraw: () => { boundDraws += 1; }, newCell: (host, model) => opened2.push([host, model]) });
bound.bind({ addEventListener: () => { throw new Error("bound twice"); } });
const click = (attr, data, expanded = "false") => listeners.click({ preventDefault() {}, target: { closest: (sel) => (sel === attr ? { dataset: data, getAttribute: () => expanded } : null) } });
click("[data-machine-models-only]", { machineModelsOnly: "like" });
eq(bound.only, "like", "a filter pressed");
click("[data-machine-job]", { machineJob: "llm" });
eq([bound.job, boundDraws], ["llm", 0], "a work pressed: narrowed in place, nothing drawn");
click("[data-machine-job]", { machineJob: "llm" });
eq([bound.job, boundDraws], ["", 0], "pressed again: let go");
const settled = async () => { for (let i = 0; i < 40; i += 1) await Promise.resolve(); };   // the harness holds the timers: microtasks only
click("[data-machine-model-choose]", { machineModelChoose: "Zeta" });
await settled();
eq([bound.picked, boundReads, boundDraws], ["Zeta", 1, 2], "a row pressed picks the model the block shows: the page is drawn again for it, and what its makers recommend is read for the model now picked and drawn with it");
click("[data-machine-model-choose]", { machineModelChoose: "Zeta" });
await settled();
eq([bound.picked, boundReads, boundDraws], ["Zeta", 1, 2], "the same row pressed again does nothing: no drawing, no reading; negative: pressing the picked row is not a way to have nothing picked");
click("[data-machine-model-choose]", { machineModelChoose: "" });
await settled();
eq([bound.picked, boundReads, boundDraws], ["Zeta", 1, 2], "negative: a button that names no model picks nothing");
click("[data-machine-model-choose]", { machineModelChoose: "Alpha" });
await settled();
eq([bound.picked, boundReads, boundDraws], ["Alpha", 2, 3], "another row: drawn again for it, and read again for it — the same table, so its texts draw nothing more");
click("[data-machine-model-new]", { machineModelNew: "m/a/q/f.gguf", machineModelHost: "hotel", machineModelName: "m", machineModelJob: "llm" });
eq(opened2, [["hotel", { value: "m/a/q/f.gguf", query: "m", job: "llm" }]], "a new cell: the wizard with the model");
listeners.input({ target: { closest: () => ({ value: "gem" }) } });
eq(bound.query, "gem", "words typed");
listeners.input({ target: { closest: () => null } });
eq(bound.query, "gem", "typing elsewhere changes nothing");
listeners.click({ preventDefault() { throw new Error("not ours"); }, target: { closest: () => null } });

// A mark on a model with no cell.
const pick = new MachinePick();
pick.know(new Map([["1", { model: "Has-Cell", rating: "like" }]]));
const rateButton = (model, kind, pressed = false) => {
  const b = { dataset: { modelRateFor: model, modelRate: kind }, attrs: { "aria-pressed": String(pressed) }, on: new Set(), setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; } };
  b.classList = { toggle: (cls, on) => (on ? b.on.add(cls) : b.on.delete(cls)) };
  return b;
};
const like = rateButton("Bare", "like"), dislike = rateButton("Bare", "dislike", true);
const rateRoot = { querySelectorAll: () => [like, dislike] };
const saves = [], marks = [];
eq(await pick.rate(like, { root: rateRoot, save: async (m, r) => { saves.push([m, r]); }, marked: (m, r) => marks.push([m, r]) }), true, "a model with no cell takes a mark");
eq(saves, [["Bare", "like"]], "the press kept: it turned from what stood on its buttons");
eq([like.attrs["aria-pressed"], dislike.attrs["aria-pressed"], marks], ["true", "false", [["Bare", "like"]]], "both buttons say so, and the list hears");
eq(await pick.rate(like, { root: rateRoot, save: async (m, r) => { saves.push([m, r]); } }), true, "pressed again");
eq(saves[1], ["Bare", ""], "the same mark again takes it off");
const refused = [];
like.attrs["aria-pressed"] = "true"; dislike.attrs["aria-pressed"] = "false";
const heard = [];
eq(await pick.rate(dislike, { root: rateRoot, save: async () => { throw new Error("no"); }, notify: (m) => refused.push(m), marked: (m, r) => heard.push(r) }), false, "refused");
eq([like.attrs["aria-pressed"], dislike.attrs["aria-pressed"], refused, heard], ["true", "false", ["no"], ["dislike", "like"]], "refused: back to what stood, said, and the list hears that too");
eq(await pick.rate({ dataset: {} }, { root: rateRoot }), false, "a button that names nothing does nothing");
pick.know(new Map([["1", { model: "Has-Cell", rating: "like" }]]));
const hasCell = rateButton("Has-Cell", "dislike");
const hasSaves = [];
await pick.rate(hasCell, { root: { querySelectorAll: () => [hasCell] }, save: async (m, r) => { hasSaves.push(r); } });
eq([hasSaves, pick.cells.get("1").rating], [["dislike"], "dislike"], "a model with a cell turns by the cell's word, as before");

// A drawing of the page.
const caret = [];
const box = { matches: (sel) => sel === "[data-machine-models-find]", selectionStart: 2, selectionEnd: 3 };
const newBox = { focused: false, focus() { this.focused = true; }, setSelectionRange: (a, b) => caret.push(a, b) };
const paneEl = { scrollTop: 40 };
const root = { ownerDocument: { activeElement: box }, innerHTML: "", querySelector: (sel) => (sel === "[data-machine-models-find]" ? newBox : sel === ".machine-main" ? paneEl : null) };
MachinePanes.replace(root, "<new>");
eq([root.innerHTML, newBox.focused, caret, paneEl.scrollTop], ["<new>", true, [2, 3], 40], "typing survives a drawing: the box has the keyboard, the caret where it was");
const elsewhere = { ownerDocument: { activeElement: { matches: () => false } }, innerHTML: "", querySelector: () => ({ focus() { throw new Error("took the keyboard"); }, scrollTop: 0 }) };
MachinePanes.replace(elsewhere, "<new>");
pass.push("the keyboard elsewhere stays there");
const noDoc = { innerHTML: "", querySelector: () => null };
MachinePanes.replace(noDoc, "<new>");
eq(noDoc.innerHTML, "<new>", "a root with no document still draws");

// On the page: the head draws inside «What lies where» — its lanes, its legend, then the block of the model picked — and under the map the list
// that picks it; the bench is no more.
const pageCells = new Map([["c22030", cell({ model: "Zeta-GGUF", launch: 'data-start-a="c22030"', playTitle: "go" })]]);
const pageNode = { id: "hotel", name: "hotel", servers: [{ cellId: "c22030", port: null, phase: "stopped", slotConfig: {} }] };
const headOf = (picked) => new MachineHead(pageNode, { cells: pageCells, choice: picked, library: { rows: ROWS, artifacts: ARTIFACTS, ratings: { "Zeta-GGUF": "like" } } }).html();
const headHtml = headOf(choice());
const mapEnd = headHtml.lastIndexOf("</section>", headHtml.indexOf('data-t="machine-models"'));   // the map's own end, not the block's
pin(headHtml.indexOf('data-machine-map') < headHtml.indexOf('data-t="machine-chosen"') && headHtml.indexOf('data-t="machine-chosen"') < mapEnd && mapEnd < headHtml.indexOf('data-t="machine-models"'),
    "inside the map, under the lanes it draws, before the map's own end; then the list");
pin(headHtml.includes('<div class="machine-main"><section class="machine-models"'),
    "negative: the pane that scrolls holds only the list, so a drawing of the board does not move the block away from the lanes");
eq(MachinePanes.PANES, [".machine-main", ".machine-side", ".machine-page > .ui-win--page > .ui-win-body"],
   "and what keeps its place when the page is drawn again is all that scrolls: the two panes and the page's own body");
pin(headHtml.includes('<p class="machine-chosen-none" data-t="machine-chosen-none" data-t-state="none">Nothing is picked yet.</p>'),
    "and with nothing picked it is still drawn, and says so in words");
pin(!headHtml.includes('data-t="machine-model-launch"'),
    "negative: with nothing picked the block holds no cell row: a cell whose model has a row in the list is named there, not drawn here");
pin(headHtml.includes('<span class="machine-models-hint">pick a model</span>'), "the list says what its rows are for: the picking");
pin(!headHtml.includes("machine-bench\"") && !headHtml.includes("machine-bench-card") && !headHtml.includes("machine-bench-slot"), "negative: no block of cells is drawn any more");
pin(headHtml.includes('data-machine-model="Zeta-GGUF"') && headHtml.includes('data-model-rate-for="Zeta-GGUF"'), "the row of the library's model, with its mark");
// A pick moves the block: the same head drawn for the model picked shows its cell with the buttons the builder gave that cell.
const pickedHead = headOf((() => { const c = choice(); c.pick("Zeta-GGUF"); return c; })());
pin(pickedHead.includes('data-t="machine-chosen" data-t-id="Zeta-GGUF" data-t-state="chosen"'), "the block names the model it shows, and it is the pick that says which");
pin(pickedHead.includes('data-start-a="c22030" data-t="machine-model-start" data-t-id="c22030"') && pickedHead.includes('data-cell-window-open="h:1" data-t="machine-model-window"'),
    "a launch acts with the buttons the board's builder gave its cell");
pin(!pickedHead.includes("machine-pick-start") && !pickedHead.includes("data-machine-picks") && !pickedHead.includes("ui-band-sub\">stopped"), "negative: no strip under the rack: its words and buttons are the row's");
pin(pickedHead.indexOf('data-t="machine-model-start"') < pickedHead.indexOf('data-t="machine-pick"') && pickedHead.indexOf('data-t="machine-pick"') > 0, "the cell's last line ends its row");
pin(typeof new MachineMap({}).benchHtml === "undefined" && typeof new MachineMap({}).benchCard === "undefined" && typeof MachineMap.ratingHtml === "undefined", "the bench's drawing is gone from the map; its rules stay");
eq(["benchVerdict", "benchSize", "bench", "benchJobs", "jobShown"].map((rule) => typeof new MachineMap({})[rule]), ["function", "function", "function", "function", "function"], "those it read by");
// The real map, its pills and what a stale work does there: the rule MachineModels.html asks.
const realMap = new MachineMap({ id: "h", servers: [{ cellId: "c1", port: null, phase: "stopped" }, { cellId: "c2", port: 22102, phase: "running" }] }, { cells: new Map([["c1", cell({ model: "A", jobs: ["llm"] })], ["c2", cell({ model: "B", jobs: ["asr"] })]]) });
eq([realMap.jobShown("asr"), realMap.jobShown("tts"), realMap.jobShown("")], ["asr", "", ""], "a work chosen stands while a cell does it");
eq([realMap.works({ phase: "stopped" }), realMap.works({ phase: "error" }), realMap.works({ phase: "reserved" }), realMap.works({ phase: "running" }), realMap.works({ phase: "warming" }), realMap.works({ phase: "broken" }), realMap.works({ phase: "starting" }), realMap.works({ phase: "downloading" }), realMap.works({ phase: "stopping" })],
   [false, false, false, true, true, true, true, true, true], "a cell works or is on its way: what opens a row; one that stands, failed or has no model does not");
console.log(JSON.stringify({ pass: pass.length }));
'''


def check_words():
    missing = []
    for lang in LANGS:
        text = (ROOT / "static" / "js" / "i18n" / f"{lang}.js").read_text(encoding="utf-8")
        missing.extend(f"{lang}.{key}" for key in KEYS if f"  {key}: " not in text)
        missing.extend(f"{lang}.{key} still here" for key in GONE_KEYS if f"  {key}: " in text)
    if missing:
        print("  FAIL words:", missing)
        raise SystemExit(1)
    print(f"  ok  the words of the block and of the list are in all {len(LANGS)} languages, the bench's in none")


def check_wiring():
    nodes = (ROOT / "static/js/topology-nodes.js").read_text(encoding="utf-8")
    render = (ROOT / "static/js/topology-render.js").read_text(encoding="utf-8")
    main = (ROOT / "static/js/main.js").read_text(encoding="utf-8")
    for text, needle, why in ((nodes, "library: { rows: state.models, artifacts: state.artifacts, ratings: topology?.modelRatings }", "the head is given the library and the marks"),
                              (nodes, 'quant: heldRef ? heldRef.quant() : ""', "the builder says which build a cell runs"),
                              (nodes, 'listed: heldRef ? heldRef.listed() : ""', "and what the list calls its model, from the library's row and nothing else"),
                              (nodes, 'const heldRef = libraryRef || (vllmArt && _runner === "vllm" ? new LibraryPath(vllmArt.path) : null);', "a vLLM cell's model through the library's row"),
                              (render, "MACHINE_MODELS.readOnce();", "a machine's page reads the makers' texts"),
                              (main, 'MACHINE_MODELS.bind(document, { read: () => api("/api/model-notes"), redraw: renderTopology', "the listeners are bound"),
                              (main, "marked: (model, rating) => MACHINE_MODELS.marked(document, model, rating)", "the list hears of a mark"),
                              (main, "listed: (root, model) => { if (MACHINE_MODELS.show(root, model)) renderTopology(); }",
                               "and of a choice, and the page is drawn again when the block has to be drawn for another model")):
        if needle not in text:
            print(f"  FAIL {why}: {needle}")
            raise SystemExit(1)
    print("  ok  the page draws the block and the list, reads its texts and binds its listeners")


def check_one_source():
    """The marks of the work have one home: a copy of one in the list, or a bench's rule left in the stylesheet, would read the same until it did not."""
    jobs = (ROOT / "static/js/model-jobs.js").read_text(encoding="utf-8")
    marks = [chr(int(code, 16)) for code in re.findall(r"\\u\{([0-9A-F]+)\}", jobs)]
    copies = [mark for mark in marks for name in ("machine-models.js", "machine-head.js") if mark in (ROOT / "static/js" / name).read_text(encoding="utf-8")]
    if not marks or copies:
        print(f"  FAIL a work's mark written outside model-jobs.js: {copies} (marks read: {len(marks)})")
        raise SystemExit(1)
    print("  ok  the marks of the work have one home")
    css = (ROOT / "static/css/machine.css").read_text(encoding="utf-8")
    left = sorted(set(re.findall(r"\.(machine-bench-(?!fit|size)[\w-]+)", css)))
    if left:
        print(f"  FAIL the bench's rules are still in machine.css: {left}")
        raise SystemExit(1)
    print("  ok  no rule of the bench's card is left; its size and verdict's stay")


def check_look():
    """What the drawing cannot say of itself: the rows stay even, a row can be taken from anywhere, its head stays over it on a low window, no rule of a default cell's row is left, and the block has its own place in the stylesheet."""
    css = (ROOT / "static/css/machine.css").read_text(encoding="utf-8")
    columns = re.search(r"\.machine-model-choose\s*\{[^}]*grid-template-columns:\s*([^;]+);", css)
    block = re.search(r"\.machine-chosen-cells\s*\{([^}]*)\}", css)
    chosen = re.search(r"\.machine-chosen\s*\{([^}]*)\}", css)
    said = re.search(r"\.machine-model-said\s*\{([^}]*)\}", css)
    if "machine-picks" in css or not re.search(r'\.machine-model-launch:has\(\.machine-pick\[data-t-state="planned"\]:not\(\[hidden\]\)\) \[data-t="machine-model-start"\] \{ display: none; \}', css):
        print("  FAIL a plan's Start stands in for the row's own, and the strip's rules are gone")
        raise SystemExit(1)
    launch = " ".join(re.findall(r"\.machine-model-launch\s*\{([^}]*)\}", css))
    sticky = re.search(r"\.machine-models-top\s*\{([^}]*)\}", css)
    for cond, why in ((columns and re.fullmatch(r"minmax\(0, 1fr\) minmax\(0, \d+px\) \d+px \d+px \d+px", columns.group(1)), "the columns of a row are of fixed widths, the name takes the rest: rows of one, two or seven cells stay even"),
                      (re.search(r"\.machine-model-cells\s*\{[^}]*white-space:\s*nowrap", css), "the count stays on one line"),
                      (re.search(r"\.machine-model-rate\s*\{[^}]*width:\s*\d+px", css), "and the place of the marks has its own width, with buttons or without"),
                      ("user-select: none" in launch and "cursor: pointer" in launch, "a cell's row is pressed and dragged: its words are no text to select"),
                      ("touch-action: pan-y" in launch, "a finger on a row scrolls the list or drags the row"),
                      (re.search(r"\.machine-model-launch\.is-on\s*\{[^}]*var\(--ui-act\)", css), "the chosen row is ringed"),
                      ('data-t-state="default"' not in css and "--ui-stated" not in (ROOT / "static/css/ui.css").read_text(encoding="utf-8") + css,
                       "negative: no rule of a default cell's row is left, and no token of its background"),
                      (sticky and "position: sticky" in sticky.group(1), "the list's head stays while its rows scroll on a low window"),
                      (block and "var(--ui-well)" in block.group(1), "the block's rows sit on their own background, from a token"),
                      (chosen and "padding-top" in chosen.group(1) and "border-top" in chosen.group(1), "the block inside the map keeps only what the map cannot say of it: the space under the legend and the line over it"),
                      (chosen and "padding:" not in chosen.group(1), "negative: a part standing inside the map draws no padding of its own — the map's is one place, and a second would read as a second part"),
                      (said and re.search(r"margin:\s*0 var\(--ui-s2\)", said.group(1)), "the prose stands under the row that picked it, inside the list's own padding"),
                      (not re.search(r"machine-chosen[^{]*machine-model-said", css), "negative: no rule puts the prose in the block: it is read on the row that picked"),
                      (not re.search(r"\.machine-model-more|\.machine-model\.is-open", css), "negative: no rule of an opened row is left: a row of the list is a press and nothing else, and what it shows stands in the block")):
        if not cond:
            print(f"  FAIL {why}")
            raise SystemExit(1)
        print(f"  ok  {why}")


def main():
    check_words()
    check_wiring()
    check_one_source()
    check_look()
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_machine_models.tmp.mjs"
    probe.write_text(PROBE)
    try:
        harness = ROOT / "scripts" / "_js_harness.mjs"
        result = subprocess.run(probe_args(node, harness, probe), cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "JS_STUBS": "i18n", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"},
                                capture_output=True, text=True, timeout=90)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    if result.returncode:
        raise SystemExit(result.returncode)
    print("machine models: ok, " + json.loads(result.stdout.strip().splitlines()[-1])["pass"].__str__() + " pins")


if __name__ == "__main__":
    main()
