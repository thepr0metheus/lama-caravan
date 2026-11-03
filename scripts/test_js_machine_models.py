#!/usr/bin/env python3
"""Actual machine-models.js: the list of models on a machine's page, under its rack (the owner's choices М1 and Н1, 2026-11-02).

The owner: "at the bottom a list of all the models, row by row, with their likes and dislikes; a press on one shows the launches saved for
it"; then: "we still have that block of cells for some reason; move all that is useful into Models, and take nothing from them". Pinned, by
value:
  * what is a row: a model's folder, once, whatever its builds; a checkpoint folder too; a file straight in the library, with no mark to
    keep; a model only a cell here names, said not to be in the library. A later part and a projector are no rows. Its work, its sizes,
    its cells, its mark, its repository;
  * the order: those with a cell first, then by name. Neither a mark nor being open sorts: a row never moves under a press;
  * the count: a 📦 per cell; past four, three and +N; no cell is a quiet dash, not a zero; its words in its hover and its label;
  * the work: JOB_MARKS before each label, one source; the pills over the list narrow it in place, with no drawing, together with the filters
    and the words typed by one rule; a work no cell here does narrows nothing; a cell of other work inside an open row is hidden;
  * the filters and the words typed: what stays, what the counts say, the word when nothing stays — and an empty library is said apart;
  * which rows stand open: what was pressed; with no press, a row with a cell working or on its way, or with the chosen cell; several at
    once; a press closes it even then;
  * a cell's row: its port with a dot (a button that chooses the cell), runner, build, windows, what it sets, then size and verdict on a second
    line, a failed one's reason in its hover; its Window and Start or Stop apart, under names of their own; a Start with nothing to start with
    is shut; a click anywhere on it chooses, a click on its buttons does not;
  * the cells with no row of their own: named by their ports, each with a row of its own to choose, start or open; gone while the list is
    searched for a model or a mark;
  * what its makers recommend: said when kept, nothing when not, a word of its own when it could not be read — never as if it said nothing;
  * a new cell: with one build the wizard goes straight on from it, with several it opens on the model's words and work; shut while a cell
    is being reserved, and for a model with no file here;
  * a press on a mark: works for a model with no cell, turns by what stands on its buttons, comes back when refused, and the row and the 👍
    count follow at once;
  * a drawing of the page keeps the choice, the caret in the search box and the scroll;
  * the longest context a model was trained for, on its row (the owner, 2026-11-02: "there is no word here on the largest context the model can
    take"): 🎓 and the window; a range when its builds differ; what its cell's model says when the library lists none; "not known" for a model
    that takes a window nobody stated, never a 0; a dash for work with no window in tokens;
  * the chosen cell (the strip under the rack went into its row, the owner, 2026-11-02): its row stands whatever the list is narrowed to, its
    cell's row too, a cell with no model's row too; a new choice opens its model whatever was pressed on it before, and it can be pressed
    closed again; its row ends in the cell's last line, and a plan's Start stands in for its own;
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
        "machineModelsNotHere", "machineModelsTextsUnread", "machineModelsOutside", "machineModelsHint", "machineModelsJobs", "machinePickReserved",
        "mdlWindowTip", "mdlWindowUnknown", "mdlWindowUnknownTip", "mdlWindowNoneTip"]
GONE_KEYS = ["machineBenchTitle", "machineBenchHint", "machineBenchJobs", "machineBenchEmpty", "machinePickNone", "machinePickNoneSub", "machinePickStopped", "machineNoModel"]

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
  ["22030", cell({ model: "Zeta-GGUF", launch: 'data-start-a="22030"', stop: "", repo: "  unsloth/<Zeta>-GGUF  " })],
  ["22031", cell({ model: "Zeta-GGUF", quant: "Q5", launch: "", stop: 'data-stop-a="22031"', repo: "other/Zeta-GGUF" })],
  ["22040", cell({ model: "Gone-GGUF", runner: "vLLM", ctx: null, jobs: ["llm"], launch: 'data-start-a="22040"', reason: "out of <memory>" })],
  ["22050", cell({ model: "", name: "ollama-qwen", runner: "Ollama", jobs: ["llm", "nonsense"], ctx: null })],
  ["22060", cell({ model: "", listed: "", name: "Reserved port", jobs: [], ctx: null })],
]);
const NODE = { id: "hotel", servers: [{ port: 22030, phase: "stopped", slotConfig: { PARALLEL: "3", TEMPERATURE: "1.0", TOP_K: "" } },
                                      { port: 22031, phase: "running", slotConfig: {} },
                                      { port: 22040, phase: "error", slotConfig: {} },
                                      { port: 22050, phase: "stopped", slotConfig: {} },
                                      { port: 22060, phase: "reserved", slotConfig: {} }] };
const STATE = { 22040: "failed" };
const MAP = {
  node: NODE, cells: CELLS, chosen: "",
  cellName: (s) => `:${s.port} name`,
  benchSize: (s) => `≈${s.port} GB`,
  benchVerdict: (s) => ({ tone: "good", words: `fits ${s.port}`, state: STATE[s.port] || "card" }),
  actionsHtml: (s) => `<ACTS ${s.port}>`,
  choiceHtml: (s) => `<CHOICE ${s.port}>`,
  works: (s) => s.phase === "running",
  benchJobs: () => [{ job: "llm", count: 4 }, { job: "asr", count: 1 }],
  jobShown: (job) => (["llm", "asr"].includes(job) ? job : ""),
};
const choice = () => new MachineModelsChoice();
const list = (over = {}) => new MachineModels({ map: MAP, rows: ROWS, artifacts: ARTIFACTS, ratings: { "Alpha-GGUF": "dislike", "stt-GGUF": "like" }, choice: choice(), ...over });

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
eq(lines.map((l) => [l.works, l.chosen]), [[false, false], [true, false], [false, false], [false, false], [false, false], [false, false]], "a row says whether a cell of it works: the stopped and the failed one do not");
eq(list({ map: { ...MAP, chosen: "22040" } }).lines().map((l) => l.chosen), [true, false, false, false, false, false], "and whether it holds the chosen cell");

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
pin(!/is-on/.test(row(html, "Cosmos").split("machine-model-more")[0].replace("is-idle", "")), "a model with no mark has none pressed");
pin(row(html, "loose.gguf").includes("2.0 GB") && !row(html, "loose.gguf").includes("data-model-rate") && row(html, "loose.gguf").includes('<span class="machine-model-rate"></span>'), "a file straight in the library: its size, no mark buttons, their place kept for the columns");

// Its repository, under its name: the first cell's that names one; none with no cell.
pin(zeta.includes('<span class="machine-model-title"><b class="machine-model-name">Zeta-GGUF</b><small class="machine-model-repo" data-t="machine-model-repo" data-t-id="Zeta-GGUF" title="unsloth/&lt;Zeta&gt;-GGUF">unsloth/<wbr>&lt;Zeta&gt;-GGUF</small></span>'),
    "a row with a cell says the first cell's repository under its name, trimmed, escaped part by part, a break after the author's /");
pin(!zeta.includes("other/Zeta-GGUF"), "negative: the second cell's is not said");
pin(row(html, "Cosmos").includes('<span class="machine-model-title"><b class="machine-model-name">Cosmos</b></span>') && !row(html, "Gone-GGUF").includes("machine-model-repo"), "negative: a model with no cell, or whose cell's path names none, has one line: its author is not guessed");

// Which rows stand open: pressed; with no press, a cell working or on its way, or the chosen one; a press closes it even then.
const L0 = (over) => ({ name: "A", cells: 1, mark: "", shownJobs: [], works: false, chosen: false, ...over });
const op = choice();
eq([op.opens(L0()), op.opens(L0({ works: true })), op.opens(L0({ chosen: true }))], [false, true, true], "no press: closed, unless a cell of it works or is chosen");
eq([op.press("A", true), op.opens(L0({ works: true })), op.opens(L0({ chosen: true })), op.opens(L0())], [false, false, false, false], "a press closes it even then, and it stays closed");
eq([op.press("A", false), op.opens(L0())], [true, true], "pressed again it opens, and stays open with no cell working");
eq([op.opens(L0({ name: "B", works: true })), op.opens(L0({ name: "C" }))], [true, false], "negative: a press on one row says nothing of another");
const both = choice();
both.press("A", false); both.press("B", false);
eq([both.opens(L0()), both.opens(L0({ name: "B" }))], [true, true], "several stand open at once");
pin(zeta.includes('aria-expanded="true"') && !/data-t-id="Zeta-GGUF" hidden>/.test(zeta) && /class="machine-model is-open/.test(html), "a cell of it works: open by itself, at a drawing");
const alpha = row(html, "Alpha-GGUF");
pin(alpha.includes('aria-expanded="false"') && /data-t-id="Alpha-GGUF" hidden>/.test(alpha), "negative: no cell of it works: closed, its launches wait hidden");
pin(/data-machine-model="Gone-GGUF"[^>]*data-machine-model-works="0"/.test(html) && /data-machine-model="Zeta-GGUF"[^>]*data-machine-model-works="1"/.test(html), "a row says it for the page to read without a drawing");
pin(/data-machine-model="stt-GGUF"[^>]*data-machine-model-jobs="asr"/.test(html) && /data-machine-model="Zeta-GGUF"[^>]*data-machine-model-jobs="llm"/.test(html), "and its works, for the list to narrow without a drawing");
const hiddenAway = choice(); hiddenAway.press("Zeta-GGUF", false); hiddenAway.only = "like";
pin(row(list({ choice: hiddenAway }).html(), "Zeta-GGUF").includes('aria-expanded="false"') && !/class="machine-model is-open[^"]*" data-machine-model="Zeta-GGUF"/.test(list({ choice: hiddenAway }).html()), "negative: a row the filter hides is not open, pressed or not");
const failedOnly = row(html, "Gone-GGUF");
pin(failedOnly.includes('aria-expanded="false"'), "negative: a failed cell does not open its row");
const chosenRow = row(list({ map: { ...MAP, chosen: "22040" } }).html(), "Gone-GGUF");
pin(chosenRow.includes('aria-expanded="true"'), "the chosen cell's model opens, so that a click on the rack shows its row");
const pressedShut = choice();
list({ map: { ...MAP, chosen: "22040" }, choice: pressedShut }).html();
pressedShut.press("Gone-GGUF", true); pressedShut.press("Zeta-GGUF", true);
const shutHtml = list({ map: { ...MAP, chosen: "22040" }, choice: pressedShut }).html();
pin(row(shutHtml, "Gone-GGUF").includes('aria-expanded="false"') && row(shutHtml, "Zeta-GGUF").includes('aria-expanded="false"'), "a press closes the chosen cell's row and a working one's, at a drawing too");
// A new choice opens its model, whatever was pressed on it before: closed, the row would hide what the choice is for.
{
  const closedBefore = choice(); closedBefore.press("Gone-GGUF", true);
  const isOpen = (chosen) => row(list({ map: { ...MAP, chosen }, choice: closedBefore }).html(), "Gone-GGUF").includes('aria-expanded="true"');
  pin(!isOpen(""), "pressed closed with nothing chosen: closed");
  pin(isOpen("22040"), "a new choice of its cell opens it");
  closedBefore.press("Gone-GGUF", true);
  pin(!isOpen("22040"), "and it can be pressed closed again: the same choice does not open it twice");
  pin(!isOpen("22031"), "negative: the choice of another model's cell does not open it");
  const shutOther = choice(); shutOther.press("Zeta-GGUF", true);
  list({ map: { ...MAP, chosen: "22031" }, choice: shutOther }).html();
  pin(!shutOther.pressed.has("Zeta-GGUF"), "the press on the row of the new choice is let go");
  const shutThird = choice(); shutThird.press("Alpha-GGUF", true);
  list({ map: { ...MAP, chosen: "22031" }, choice: shutThird }).html();
  pin(shutThird.pressed.get("Alpha-GGUF") === false, "negative: a press on another row stays");
  shutThird.chose("", "");
  eq(shutThird.chosenPort, "", "a choice let go is remembered too, so the same cell chosen again opens its row again");
}
// The chosen cell's row stands whatever the list is narrowed to: it is where it says what it does and has its buttons.
{
  const narrowed = choice(); narrowed.narrowJob("asr"); narrowed.query = "nothing";
  const drawn = list({ map: { ...MAP, chosen: "22031" }, choice: narrowed }).html();
  pin(!/<div class="machine-model[^"]*" data-machine-model="Zeta-GGUF"[^>]* hidden>/.test(drawn), "the row of its model stands, whatever the work and the words");
  pin(!/data-machine-pick="22031" data-machine-jobs="llm"[^>]* hidden>/.test(drawn), "and its own row, of another work than the one shown");
  pin(/data-machine-pick="22030" data-machine-jobs="llm"[^>]* hidden>/.test(drawn), "negative: its neighbour of the same model stays hidden: the chosen one stands, not its model's cells");
  pin(/<div class="machine-model[^"]*" data-machine-model="Alpha-GGUF"[^>]* hidden>/.test(drawn), "negative: another model's row goes by the filter");
  eq([MachineModelsChoice.keepsCell(["llm"], "asr", false), MachineModelsChoice.keepsCell(["llm"], "asr", true), MachineModelsChoice.keepsCell(["asr"], "asr", false), MachineModelsChoice.keepsCell([], "", false)],
     [false, true, true, true], "a cell's own row: by its work, or chosen");
  const words = choice(); words.query = "nothing";
  pin(!/data-machine-models-rest hidden/.test(list({ map: { ...MAP, chosen: "22050" }, choice: words }).html()), "a cell with no model's row, chosen, stands while the list is searched");
  pin(/data-machine-models-rest hidden/.test(list({ map: { ...MAP, chosen: "22031" }, choice: words }).html()), "negative: with another one chosen they go with the search");
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
  const told = { ...MAP, cells: new Map([...CELLS, ["22040", cell({ model: "Gone-GGUF", runner: "vLLM", ctx: { set: 0, max: 4096 }, jobs: ["llm"] })]]) };
  pin(said(list({ map: told }).lines(), "Gone-GGUF").includes(">🎓 4.1k<"), "what its cell's model says is all there is of a model the library does not list");
  const wholeRow = row(list().html(), "Zeta-GGUF");
  pin(wholeRow.indexOf("machine-model-job") < wholeRow.indexOf("machine-model-context") && wholeRow.indexOf("machine-model-context") < wholeRow.indexOf("machine-model-sizes"), "its place on the row: between the work and the size");
  eq(MachineModels.contextHtml({ name: "Nothing", window: { lo: Infinity, hi: 0, unnamed: false, models: 0 } }),
     '<span class="machine-model-context is-dim" data-t="machine-model-context" data-t-id="Nothing" data-t-state="none"></span>', "a row with no model to speak of says nothing, and its column stays");
}
eq(list({ choice: pressedShut }).lines().map((l) => l.name), lines.map((l) => l.name), "a row never moves under a press");
const pressedOpen = choice(); pressedOpen.press("stt-GGUF", false); pressedOpen.press("Alpha-GGUF", false);
eq(list({ choice: pressedOpen }).lines().map((l) => l.name), lines.map((l) => l.name), "nor under a row opened");

// A cell's row, on two lines.
const openChoice = choice(); openChoice.press("Zeta-GGUF", false);
const opened = row(list({ choice: openChoice }).html(), "Zeta-GGUF");
pin(opened.includes('aria-expanded="true"') && !/data-t-id="Zeta-GGUF" hidden>/.test(opened), "open, they show");
const launch = (over = {}) => list(over).launchHtml(NODE.servers[0], "");
const r30 = launch();
pin(r30.startsWith('<div class="machine-model-launch" data-machine-pick="22030" data-machine-jobs="llm" data-t="machine-model-launch" data-t-id="22030" title="click a cell to plan it, or drag it up onto the rack">'),
    "the whole row chooses its cell, says its works, and says so in its hover");
pin(r30.includes('<button type="button" class="machine-model-port" aria-pressed="false" data-machine-pick="22030" data-t="machine-model-cell" data-t-id="22030" title=":22030 name — click to choose"><span class="machine-model-dot" aria-hidden="true"></span>:22030</button>'),
    "its port with a dot: a button for the keyboard, and the dot says nothing to a screen reader");
const parts = (html) => [...html.matchAll(/<div class="machine-model-line">/g)].length;
eq(parts(r30), 2, "two lines");
const [first, second] = r30.split('<div class="machine-model-line">').slice(1);
pin(first.includes('<span class="machine-model-runner">llama.cpp</span><span class="machine-model-quant">Q4</span><span class="machine-model-ctx" data-t="machine-model-ctx" data-t-id="22030" data-t-state="both"')
    && first.includes('<span class="machine-model-set" title="parallel 3 · temp 1.0">parallel 3 · temp 1.0</span></div>'), "the first line: its runner, its build, its windows, what else it sets");
pin(second.startsWith('<span class="machine-bench-size" data-machine-bench-size="22030">≈22030 GB</span><span class="machine-bench-fit machine-bench-fit--good" data-machine-bench-fit="22030" data-t-state="card">fits 22030</span></div>'),
    "the second line: its size and its verdict, with its tone and its state, under the names the live patch finds them by");
pin(r30.endsWith('<span class="machine-model-acts" data-machine-own><button type="button" class="ui-btn ui-btn--icon machine-model-note-add" data-cell-note="hotel:22030" data-machine-own'
                + ' data-t="machine-model-note-add" data-t-id="22030" title="Add a note to this cell" aria-label="Add a note to this cell">✎</button><ACTS 22030></span><CHOICE 22030></div>'),
    "its buttons at the end, under names of their own, marked as their own; a cell with no note has the ✎ that asks for one first");
// The cell's note in its row (the owner, 2026-11-03: "sign the cells, a comment of my own, visible here"): the one its card and window had.
st.setTopology({ nodes: [], cellNotes: { "hotel:22030": "for the coder <b>" } });
const noted = list().launchHtml(NODE.servers[0], "");
pin(noted.includes('</div><button type="button" class="machine-model-note" data-cell-note="hotel:22030" data-machine-own data-t="machine-model-note" data-t-id="22030"')
    && noted.includes('>💬 for the coder &lt;b&gt;</button><span class="machine-model-acts"'), "a noted cell says its note under its two lines, escaped, and a press on it asks for it again");
pin(!noted.includes("machine-model-note-add"), "negative: a noted cell has no ✎ besides its words");
st.setTopology({ nodes: [], cellNotes: {} });
pin(!list().launchHtml(NODE.servers[0], "").includes('class="machine-model-note"'), "negative: no note, no line");
pin(r30.indexOf("machine-model-port") < r30.indexOf('machine-model-line') && r30.lastIndexOf("machine-model-line") < r30.indexOf("machine-model-acts"), "port, lines, buttons, in that order");
pin(!r30.includes("machine-model-cell-name"), "negative: under a model's row it does not say the name again");
pin(!/data-machine-bench-fit="22030"[^>]* title=/.test(r30), "negative: a verdict that did not fail has no reason in its hover");
const failedRow = list().launchHtml(NODE.servers[2], "");
pin(failedRow.includes('data-machine-bench-fit="22040" data-t-state="failed" title="out of &lt;memory&gt;">'), "a failed cell's reason is in its verdict's hover, escaped");
const chosenLaunch = list({ map: { ...MAP, chosen: "22031" } }).launchHtml(NODE.servers[1], "");
pin(chosenLaunch.startsWith('<div class="machine-model-launch is-on" data-machine-pick="22031"') && chosenLaunch.includes('class="machine-model-port is-on" aria-pressed="true" data-machine-pick="22031"'), "the chosen row is highlighted, and its port says so");
pin(!chosenLaunch.startsWith('<div class="machine-model-launch is-on" data-machine-pick="22031" aria-pressed'), "negative: the row is no button and says no pressed");
const stoppedOther = list({ map: { ...MAP, chosen: "22031" } }).launchHtml(NODE.servers[0], "");
pin(!stoppedOther.includes("is-on"), "negative: another cell's row is not");
const lonely = choice(); lonely.press("Cosmos", false);
pin(row(list({ choice: lonely }).html(), "Cosmos").includes("No saved launch of this model"), "no launch: said");

// The cells with no row of their own: each has a row here, or it could not be chosen at all while it stands.
pin(html.includes('data-t="machine-models-outside">Their model lies outside the library: :22050<'), "a cell with no row is named by its port, and one with no model yet is not");
pin(!new MachineModels({ map: { ...MAP, node: { id: "h", servers: NODE.servers.slice(0, 3) } }, rows: ROWS, choice: choice() }).html().includes("machine-models-rest"), "every cell has its row: no such block");
const rest = html.slice(html.indexOf('data-machine-models-rest'), html.indexOf('data-machine-model="Alpha-GGUF"'));
pin(rest.includes('data-machine-pick="22050"') && rest.includes('data-machine-pick="22060"') && rest.includes("<ACTS 22050") && rest.includes("<ACTS 22060"), "the cell outside and the port with no model each have a row to choose and act on");
pin(rest.includes('<strong class="machine-model-cell-name">ollama-qwen · 💬 LLM</strong>') && rest.includes('<strong class="machine-model-cell-name">Reserved port</strong>'), "with no model's row over them they say their name and work; a work out of the vocabulary is not named");
const nameless = new MachineModels({ map: { ...MAP, cells: new Map([["22060", cell({ model: "", listed: "", jobs: ["llm"], ctx: null })]]) }, choice: choice() }).launchHtml(NODE.servers[4], "", { named: true });
pin(nameless.includes('<strong class="machine-model-cell-name">💬 LLM</strong>'), "negative: a cell nobody named says its work alone, with no dot before it");
pin(html.indexOf('data-machine-model="Zeta-GGUF"') < html.indexOf("data-machine-models-rest") &&html.indexOf("data-machine-models-rest") < html.indexOf('data-machine-model="Alpha-GGUF"'), "they stand among those with a cell, before the models with none");
pin(!rest.includes('data-machine-pick="22030"'), "negative: a cell with a model's row is not among them");
const keepsRest = (over, jobs, job) => { const c = choice(); Object.assign(c, over); return c.keepsRest(jobs, job); };
eq([keepsRest({}, [["llm"], []], ""), keepsRest({ only: "cells" }, [["llm"]], ""), keepsRest({ only: "like" }, [["llm"]], ""), keepsRest({ query: " x " }, [["llm"]], ""), keepsRest({}, [["llm"], []], "asr"), keepsRest({}, [["llm"], []], "llm")],
   [true, true, false, false, false, true], "they stand: not while the list is searched by words or a mark, which they cannot answer; not when none of them does the work");
const searched = choice(); searched.query = "zeta";
pin(/data-machine-models-rest hidden>/.test(list({ choice: searched }).html()), "words typed: the block goes, at a drawing");
pin(new MachineModels({ map: { ...MAP, node: { id: "h", servers: NODE.servers.slice(3) } }, rows: [], choice: choice() }).html().includes('data-machine-pick="22050"') && new MachineModels({ map: { ...MAP, node: { id: "h", servers: NODE.servers.slice(3) } }, rows: [], choice: choice() }).html().includes('data-t="machine-models" data-t-state="empty"'), "no model at all: the cells still stand, and the list says it is empty");

// What its makers recommend.
const said = (texts, unread = false) => { const c = choice(); c.texts = texts; c.unread = unread; return list({ choice: c }).saidHtml("Zeta-GGUF"); };
pin(said({ "Zeta-GGUF": "top_k 20 <b>" }).includes("Recommended by its makers.") && said({ "Zeta-GGUF": "top_k 20 <b>" }).includes("top_k 20 &lt;b&gt;"), "kept: said, escaped");
eq([said({}), said({ "Zeta-GGUF": "   " }), said({ constructor: "x" }), said(null)], ["", "", "", ""], "nothing kept, or not read yet: nothing drawn, and a word an object answers to is no text");
pin(said(null, true).includes('data-t-state="unread"') && said(null, true).includes("could not be read"), "could not be read: said so, not as if it said nothing");

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
pin(new MachineModels({ map: bare, choice: choice() }).html().includes('data-t-state="empty"') && new MachineModels({ map: bare, choice: choice() }).html().includes("The library holds no models"), "an empty library is said apart");
pin(!new MachineModels({ map: bare, choice: choice() }).html().includes("machine-models-jobs"), "negative: no cell says what it does: no row of pills");

// The pills of the work, under the head.
pin(html.includes('<strong class="machine-models-title">Models</strong>') && html.includes('<span class="machine-models-hint">click a cell to plan it, or drag it up onto the rack</span>'), "the head: its title and how to use it");
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
// A model that does two works, its cells one each: the row stays, the cell of the other is hidden inside.
const mixedCells = new Map([["1", cell({ model: "Twin-GGUF", jobs: ["llm"] })], ["2", cell({ model: "Twin-GGUF", jobs: ["asr"] })], ["3", cell({ model: "Twin-GGUF", jobs: [] })]]);
const mixedMap = { ...MAP, cells: mixedCells, node: { id: "h", servers: [{ port: 1, phase: "running", slotConfig: {} }, { port: 2, phase: "stopped", slotConfig: {} }, { port: 3, phase: "stopped", slotConfig: {} }] } };
const mixedChoice = choice(); mixedChoice.job = "asr";
const mixed = new MachineModels({ map: mixedMap, choice: mixedChoice }).html();
const launchHidden = (text, port) => new RegExp(`<div class="machine-model-launch" data-machine-pick="${port}"[^>]* hidden>`).test(text);
eq([launchHidden(mixed, 1), launchHidden(mixed, 2), launchHidden(mixed, 3), /data-machine-model="Twin-GGUF"[^>]* hidden>/.test(mixed)], [true, false, true, false], "inside an open model, a cell that does not do the work is hidden; one that says none as well; the row stays");
mixedChoice.job = "";
pin(![1, 2, 3].some((port) => launchHidden(new MachineModels({ map: mixedMap, choice: mixedChoice }).html(), port)), "negative: no work chosen: all of them show");

// Shown in place, on a page of stand-ins.
const el = (dataset, kids = {}) => {
  const e = { dataset, hidden: false, attrs: {}, on: new Set(), setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k] ?? null; }, querySelector: (sel) => kids[sel] || null, querySelectorAll: () => [] };
  e.classList = { toggle: (cls, on) => (on ? e.on.add(cls) : e.on.delete(cls)) };
  return e;
};
const rowEl = (name, cells, mark, jobs = "", works = "0") => {
  const opener = el({}), more = el({});
  return Object.assign(el({ machineModel: name, machineModelCells: String(cells), machineModelMark: mark, machineModelJobs: jobs, machineModelWorks: works }, { "[data-machine-model-open]": opener, "[data-machine-model-more]": more }), { opener, more });
};
const countEl = () => ({ textContent: "" });
const pillOf = (only) => { const count = countEl(); return Object.assign(el({ machineModelsOnly: only }, { ".ui-count": count }), { count }); };
const rows = [rowEl("Zeta", 2, "", "llm"), rowEl("Alpha", 0, "like", "llm asr"), rowEl("Cosmos", 0, "", "asr")];
const pills = ["", "cells", "like"].map(pillOf);
const jobPills = ["llm", "asr"].map((job) => el({ machineJob: job }));
const cellsOf = [["llm"], ["asr"], [""]].map(([jobs]) => el({ machineJobs: jobs }));
const none = el({});
const restEl = el({});
const page = {
  querySelectorAll: (sel) => (sel === "[data-machine-model]" ? rows : sel === "[data-machine-models-only]" ? pills : sel === "[data-machine-job]" ? jobPills : sel === "[data-machine-jobs]" ? cellsOf : []),
  querySelector: (sel) => (sel === "[data-machine-models-none]" ? none : sel === "[data-machine-models-rest]" ? restEl : null),
};
restEl.querySelectorAll = (sel) => (sel === "[data-machine-jobs]" ? cellsOf.slice(2) : []);
const shown = choice();
shown.only = "cells"; shown.press("Zeta", false); shown.show(page);
eq(rows.map((r) => r.hidden), [false, true, true], "the rows the filter leaves");
eq([rows[0].opener.attrs["aria-expanded"], rows[0].more.hidden, rows[0].on.has("is-open"), rows[1].more.hidden], ["true", false, true, true], "the row open, the others shut");
eq(pills.map((p) => [p.attrs["aria-pressed"], p.count.textContent]), [["false", "3"], ["true", "1"], ["false", "1"]], "the filters pressed and their counts");
eq(none.hidden, true, "something stays: no word");
shown.only = ""; shown.query = "nope"; shown.show(page);
eq([rows.every((r) => r.hidden), none.hidden], [true, false], "nothing stays: the word");
shown.query = ""; shown.press("Alpha", false); shown.only = "cells"; shown.show(page);
eq([rows[1].hidden, rows[1].more.hidden, rows[1].on.has("is-open")], [true, true, false], "a row the filter hides is not open");
shown.only = "like"; shown.show(page);
eq(rows.map((r) => r.hidden), [true, false, true], "the 👍 filter");
shown.marked(page, "Cosmos", "like");
eq([rows[2].dataset.machineModelMark, rows[2].hidden, pills[2].count.textContent], ["like", false, "2"], "a mark pressed: the row and the count follow at once");
shown.marked(page, "Cosmos", "");
eq([rows[2].hidden, pills[2].count.textContent], [true, "1"], "a mark taken off: it leaves the 👍 filter");
shown.only = "";
shown.narrowJob("asr"); shown.show(page);
eq([rows.map((r) => r.hidden), jobPills.map((p) => p.attrs["aria-pressed"]), cellsOf.map((cl) => cl.hidden), restEl.hidden], [[true, false, false], ["false", "true"], [true, false, true], true], "a work pressed, in place: the rows that do it, the pill, the cells inside, the cells with no row");
shown.query = "alp"; shown.show(page);
eq(rows.map((r) => r.hidden), [true, false, true], "with the words typed: one rule, neither overwrites the other");
shown.query = "cosmo"; shown.only = "like"; shown.show(page);
eq([rows.every((r) => r.hidden), none.hidden], [true, false], "with a filter too, and none left: said");
shown.query = ""; shown.only = ""; shown.narrowJob("asr"); shown.show(page);
eq([rows.map((r) => r.hidden), jobPills.map((p) => p.attrs["aria-pressed"]), cellsOf.map((cl) => cl.hidden), restEl.hidden, none.hidden], [[false, false, false], ["false", "false"], [false, false, false], false, true], "the same again lets it go");
shown.job = "voice-chat"; shown.show(page);
eq([rows.map((r) => r.hidden), jobPills.map((p) => p.attrs["aria-pressed"])], [[false, false, false], ["false", "false"]], "negative: a work with no pill narrows nothing here either");
shown.job = "";
// A row opens by itself by what it says of itself: a cell works, or its cell's row is chosen.
const auto = rowEl("Auto", 1, "", "llm", "1");
const quiet = rowEl("Quiet", 1, "", "llm", "0");
const chosenInside = el({});
const holding = rowEl("Holding", 1, "", "llm", "0");
holding.querySelector = ((was) => (sel) => (sel === ".machine-model-launch.is-on" ? chosenInside : was(sel)))(holding.querySelector);
const autoPage = { querySelectorAll: (sel) => (sel === "[data-machine-model]" ? [auto, quiet, holding] : []), querySelector: () => null };
const autoChoice = choice();
autoChoice.show(autoPage);
// Shown in place, a chosen row stands whatever the list is narrowed to, and so does its cell's row and the rest's.
{
  const narrowedRow = rowEl("Narrowed", 1, "", "llm", "0");
  narrowedRow.querySelector = ((was) => (sel) => (sel === ".machine-model-launch.is-on" ? {} : was(sel)))(narrowedRow.querySelector);
  const other = rowEl("Other", 1, "", "llm", "0");
  const chosenCell = el({ machineJobs: "llm" }); chosenCell.classList.contains = (cls) => cls === "is-on";
  const plainCell = el({ machineJobs: "llm" }); plainCell.classList.contains = () => false;
  const restBox = el({});
  restBox.querySelectorAll = () => [];
  restBox.querySelector = (sel) => (sel === ".machine-model-launch.is-on" ? {} : null);
  const asrPill = el({ machineJob: "asr" });
  const inPlace = { querySelectorAll: (sel) => (sel === "[data-machine-model]" ? [narrowedRow, other] : sel === "[data-machine-jobs]" ? [chosenCell, plainCell] : sel === "[data-machine-job]" ? [asrPill] : []),
                    querySelector: (sel) => (sel === "[data-machine-models-rest]" ? restBox : null) };
  const stays = choice(); stays.narrowJob("asr"); stays.show(inPlace);
  eq([narrowedRow.hidden, other.hidden, chosenCell.hidden, plainCell.hidden, restBox.hidden], [false, true, false, true, false], "in place: the chosen row, its cell's row and the rest stand; the others go by the work");
  // The choice is seen on the page: a new one lets go of a press on its row.
  const pressedRow = el({ machineModel: "Seen" });
  const onRow = { dataset: { machinePick: "22001" }, closest: (sel) => (sel === "[data-machine-model]" ? pressedRow : null) };
  const seen = choice(); seen.press("Seen", true);
  seen.show({ querySelectorAll: () => [], querySelector: (sel) => (sel === ".machine-model-launch.is-on" ? onRow : null) });
  eq([seen.chosenPort, seen.pressed.has("Seen")], ["22001", false], "a choice shown in place opens its model too: the press on it is let go");
}
eq([auto, quiet, holding].map((r) => r.more.hidden), [false, true, false], "in place: open while a cell works or the row holds the chosen one, closed otherwise");
autoChoice.press("Auto", true); autoChoice.press("Holding", true); autoChoice.show(autoPage);
eq([auto, quiet, holding].map((r) => r.more.hidden), [true, true, true], "a press closes them even then");

// A choice on the rack opens its model's row in place, through the pick's own listener.
{
  const lanePick = { dataset: { machinePick: "22030", t: "machine-map-block" }, closest: () => null };
  const launchEl ={ dataset: { machinePick: "22030", t: "machine-model-launch" }, on: new Set(), classList: { toggle(cls, on) { if (on) launchEl.on.add(cls); else launchEl.on.delete(cls); } } };
  const model = rowEl("Zeta", 1, "", "llm", "0");
  model.querySelector = ((was) => (sel) => (sel === ".machine-model-launch.is-on" ? (launchEl.on.has("is-on") ? launchEl : null) : was(sel)))(model.querySelector);
  const docListeners = [];
  const asked = [];
  const pageDoc = { addEventListener: (type, fn) => docListeners.push([type, fn]),
                    querySelector: (sel) => (sel.startsWith(".machine-model-launch[") ? { scrollIntoView: (how) => asked.push(["row", how]) } : sel.startsWith(".fold-slot") ? {} : null),
                    querySelectorAll: (sel) => (sel === "[data-machine-model]" ? [model] : sel === "[data-machine-pick]" ? [launchEl] : []) };
  const list2 = choice();
  const pick2 = new MachinePick();
  pick2.know(new Map([["22030", { group: "holds", key: "h:1", window: true }]]));
  let draws = 0;
  pick2.bind(pageDoc, { redraw: () => { draws += 1; }, listed: () => list2.show(pageDoc) });
  const clicked = (target) => docListeners.filter(([type]) => type === "click").forEach(([, fn]) => fn({ preventDefault() {}, target }));
  const onBlock = { closest: (sel) => (sel === "[data-machine-pick]" ? lanePick : null) };
  clicked(onBlock);
  eq([pick2.port, model.more.hidden, model.on.has("is-open"), draws], ["22030", false, true, 0], "a block on the rack chosen: its model's row opens at once, with no drawing");
  eq(asked.map(([what]) => what), ["row"], "and the row is brought into sight");
  asked.length = 0;
  clicked(onBlock);
  eq([pick2.port, model.more.hidden, model.on.has("is-open")], ["", true, false], "let go: it closes again: nothing holds it open");
  eq(asked, [], "negative: letting a cell go brings nothing into sight");
  const inList = { dataset: { machinePick: "22030", t: "machine-model-launch" }, closest: (sel) => (sel === '[data-t="machine-models"]' ? {} : null) };
  clicked({ closest: (sel) => (sel === "[data-machine-pick]" ? inList : null) });
  eq([pick2.port, asked.map(([what]) => what)], ["22030", ["row"]], "chosen in the list too: its new line may fall under the pane's edge, and the list moves by that much and no more");
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
const settled = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };   // the harness holds the timers: microtasks only
click("[data-machine-model-open]", { machineModelOpen: "Zeta" });
await settled();
eq([bound.pressed.get("Zeta"), boundReads], [true, 1], "a closed row pressed opens, and the texts are read again");
click("[data-machine-model-open]", { machineModelOpen: "Zeta" }, "true");
await settled();
eq([bound.pressed.get("Zeta"), boundReads], [false, 1], "an open row pressed closes: it turns from what it shows; negative: closing reads nothing");
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

// On the page: the head draws it under the rack, with its library, and the bench is no more.
const pageCells = new Map([["22030", cell({ model: "Zeta-GGUF", launch: 'data-start-a="22030"', playTitle: "go" })]]);
const headHtml = new MachineHead({ id: "hotel", name: "hotel", servers: [{ port: 22030, phase: "stopped", slotConfig: {} }] },
                                   { cells: pageCells, library: { rows: ROWS, artifacts: ARTIFACTS, ratings: { "Zeta-GGUF": "like" } } }).html();
pin(headHtml.indexOf('data-t="machine-map"') < headHtml.indexOf('data-t="machine-models"') && headHtml.indexOf('data-t="machine-models"') > 0, "under the rack");
pin(headHtml.includes('<div class="machine-main"><section class="machine-models"'), "it is the pane's first thing");
pin(!headHtml.includes("machine-bench\"") && !headHtml.includes("machine-bench-card") && !headHtml.includes("machine-bench-slot"), "negative: no block of cells is drawn any more");
pin(headHtml.includes('data-machine-model="Zeta-GGUF"') && headHtml.includes('data-model-rate-for="Zeta-GGUF"'), "the row of the library's model, with its mark");
pin(headHtml.includes('data-start-a="22030" data-t="machine-model-start" data-t-id="22030"') && headHtml.includes('data-cell-window-open="h:1" data-t="machine-model-window"'), "a launch acts with the buttons the board's builder gave its cell");
pin(!headHtml.includes("machine-pick-start") && !headHtml.includes("data-machine-picks") && !headHtml.includes("ui-band-sub\">stopped"), "negative: no strip under the rack: its words and buttons are the row's");
pin(headHtml.indexOf('data-t="machine-model-start"') < headHtml.indexOf('data-t="machine-pick"') && headHtml.indexOf('data-t="machine-pick"') > 0, "the cell's last line ends its row");
pin(typeof new MachineMap({}).benchHtml === "undefined" && typeof new MachineMap({}).benchCard === "undefined" && typeof MachineMap.ratingHtml === "undefined", "the bench's drawing is gone from the map; its rules stay");
eq(["benchVerdict", "benchSize", "bench", "benchJobs", "jobShown"].map((rule) => typeof new MachineMap({})[rule]), ["function", "function", "function", "function", "function"], "those it read by");
// The real map, its pills and what a stale work does there: the rule MachineModels.html asks.
const realMap = new MachineMap({ id: "h", servers: [{ port: 1, phase: "stopped" }, { port: 2, phase: "running" }] }, { cells: new Map([["1", cell({ model: "A", jobs: ["llm"] })], ["2", cell({ model: "B", jobs: ["asr"] })]]) });
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
    print(f"  ok  the list's words are in all {len(LANGS)} languages, the bench's in none")


def check_wiring():
    nodes = (ROOT / "static/js/topology-nodes.js").read_text(encoding="utf-8")
    render = (ROOT / "static/js/topology-render.js").read_text(encoding="utf-8")
    main = (ROOT / "static/js/main.js").read_text(encoding="utf-8")
    for text, needle, why in ((nodes, "library: { rows: state.models, artifacts: state.artifacts, ratings: topology?.modelRatings }", "the head is given the library and the marks"),
                              (nodes, 'quant: heldRef ? heldRef.quant() : ""', "the builder says which build a cell runs"),
                              (nodes, 'listed: heldRef ? heldRef.listed() : ""', "and what the list calls its model"),
                              (nodes, 'const heldRef = libraryRef || (vllmArt && _runner === "vllm" ? new LibraryPath(vllmArt.path) : null);', "a vLLM cell's model through the library's row"),
                              (render, "MACHINE_MODELS.readOnce();", "a machine's page reads the makers' texts"),
                              (main, 'MACHINE_MODELS.bind(document, { read: () => api("/api/model-notes"), redraw: renderTopology', "the listeners are bound"),
                              (main, "marked: (model, rating) => MACHINE_MODELS.marked(document, model, rating)", "the list hears of a mark"),
                              (main, "listed: () => MACHINE_MODELS.show(document)", "and of a choice, so that the chosen cell's model opens")):
        if needle not in text:
            print(f"  FAIL {why}: {needle}")
            raise SystemExit(1)
    print("  ok  the page draws the list, reads its texts and binds its listeners")


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
    """What the drawing cannot say of itself: the rows stay even, a row can be taken from anywhere, its head stays over it on a low window."""
    css = (ROOT / "static/css/machine.css").read_text(encoding="utf-8")
    columns = re.search(r"\.machine-model-open\s*\{[^}]*grid-template-columns:\s*([^;]+);", css)
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
                      (sticky and "position: sticky" in sticky.group(1), "the list's head stays while its rows scroll on a low window")):
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
