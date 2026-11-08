#!/usr/bin/env python3
"""Value snapshot: the new-cell wizard — "+ Add model" (static/js/add-model.js, 1.3.638).

The owner chose variant А of the canvas with three changes (2026-10-25): first what the model is for and what it must be able to
do; every setting of llama.cpp within reach, the important ones in sight; the largest context a model takes, said on the model —
then "А2 with the stars of А3". The wizard drives the cell editor's own form; the snapshot gives it a fake one, a fake editor of
the settings and a machine, and pins by value, each claim with its negative:
  * the windows: the usual ones up to the trained one, and it; none is written by itself — an empty field asks for the window
    the model was trained for (the owner, 2026-10-26), and a smaller one the cards hold whole is only offered, as a button;
  * the opening: the form filled for a new cell of the machine — the form's key of a cell not made yet; no cellId, no port — without its
    dialog, adopted by the settings' editor — and not filled when the cell window keeps edits the operator does not let go;
  * the first step: a tile a job in the vocabulary's order with its count; what a chat model must be able to do narrows the list;
    a row says the trained window ("not known" for a model that takes one and states none, a dash for a job that takes none),
    what it weighs at the window its start asks for and where it would go — the bench's plan, with the machine's real cards;
  * a pick: the form's own pick, no window written, the next step;
  * the runner: the one made for the model, the others that can run it, a choice writes it; the projector and the draft;
  * the third step: the eight main fields of a llama.cpp cell and the starred ones, each writing the form; where it computes by
    the compute target's rule; a smaller window offered when the one set does not fit; the full list folded, then the editor's;
  * Create and Create and start: the form's Apply without its question — the save makes the cell — then the cell's start by the name
    the save gave it; a save that names none is said and nothing is started; a refused save keeps it open; the full form and closing let
    the form go; the launch builder's form filling carries no port, even one handed to it.

Run: python3 scripts/test_js_add_model.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


STUBS = "form,llama-edit,memory,remote-cells,favorites"

PROBE = r'''
import "./_js_globals.mjs";
globalThis.__stubReturns = {
  "memory.shortGpuName": (n) => String(n || "").replace(/NVIDIA\s+GeForce\s+/i, ""),
};
const { AddModel, WindowPick } = await import("../static/js/add-model.js");
const en = (await import("../static/js/i18n/en.js")).default;
const out = {};

// ── the windows ──
out.windows = {
  hermes: WindowPick.stops(131072), odd: WindowPick.stops(500000).slice(-3), unknown: WindowPick.stops(0).slice(-1),
  propose: typeof WindowPick.propose,
};

// ── a machine, its models, its runners, a fake form and a fake editor of the settings ──
const GIB = 2 ** 30;
const HERMES = "Hermes-4-70B-GGUF/lmstudio-community/Q4_K_M/Hermes-4-70B-Q4_K_M.gguf";
const CODER = "Qwen3-Coder-30B-A3B-Instruct-1M-GGUF/unsloth/Q4_K_M/Qwen3-Coder-30B-A3B-Instruct-1M-Q4_K_M.gguf";
const GEMMA = "gemma-4-31B-it-GGUF/unsloth/Q4_K_M/gemma-4-31B-it-Q4_K_M.gguf";
const EMB = "Qwen3-Embedding-0.6B-GGUF/Qwen/Q8_0/Qwen3-Embedding-0.6B-Q8_0.gguf";
const GIGA = "gigaam-v3-e2e-rnnt-gguf/salute/Q8_0/gigaam-v3-e2e-rnnt-Q8_0.gguf";
const WHISPER = "whisper/models--Systran--faster-whisper-large-v3-turbo";
const TTS = "Qwen3-TTS-12Hz-1.7B-Base/Qwen/BF16";
const COSMOS = "Cosmos-Reason2-2B/nvidia/BF16";
const CHOICES = [
  { value: HERMES, kind: "model", sizeGb: 39.6, window: 131072, detectedFamily: "hermes4", cached: true },
  { value: CODER, kind: "model", sizeGb: 17.3, window: 1048576, detectedFamily: "qwen3" },
  { value: GEMMA, kind: "model", sizeGb: 17.1, window: 262144, detectedFamily: "gemma4", capability: "vision_likely", suggestedMmproj: "x/mmproj.gguf" },
  { value: EMB, kind: "model", sizeGb: 0.6, window: 32768, detectedFamily: "embedding" },
  { value: GIGA, kind: "model", sizeGb: 0.25, window: null, sttVariant: "gigaam-v3" },
  { value: WHISPER, kind: "whisper", whSize: "large-v3-turbo", sizeLabel: "1.6 GB" },
  { value: TTS, kind: "st", stName: "Qwen3-TTS-12Hz-1.7B-Base", stArch: "qwen3_tts", sizeGb: 4.2, window: null },
];
const META = { blockCount: 80, headCount: 64, headCountKv: 8, keyLength: 128, embeddingLength: 8192, contextLength: 131072 };
const ROWS = new Map([
  [HERMES, { path: HERMES, kind: "model", sizeGb: 39.6, ggufMeta: META, compatibleMmprojs: [], compatibleDrafts: [] }],
  [CODER, { path: CODER, kind: "model", sizeGb: 17.3, ggufMeta: { blockCount: 48, headCount: 32, headCountKv: 4, keyLength: 128, embeddingLength: 2048, contextLength: 1048576 } }],
  [GEMMA, { path: GEMMA, kind: "model", sizeGb: 17.1, ggufMeta: { blockCount: 60, headCount: 32, headCountKv: 16, keyLength: 128, embeddingLength: 5376, contextLength: 262144 },
            compatibleMmprojs: ["gemma-4-31B-it-GGUF/unsloth/Q4_K_M/mmproj-F16.gguf"], compatibleDrafts: ["gemma-4-31B-it-GGUF/unsloth/Q4_K_M/mtp.gguf"] }],
  [EMB, { path: EMB, kind: "model", sizeGb: 0.6, ggufMeta: { blockCount: 28, headCount: 16, headCountKv: 8, keyLength: 128, embeddingLength: 1024, contextLength: 32768 } }],
]);
const RUNNERS = [
  { id: "llama-server", icon: "🦙", labelKey: "runnerLlama", benefitsKey: "runnerLlamaBenefits", llamaConfig: true, artifacts: ["llm-gguf"] },
  { id: "prism", icon: "🌱", labelKey: "runnerPrism", benefitsKey: "runnerPrismBenefits", minusKey: "runnerPrismMinus", llamaConfig: true, artifacts: ["llm-gguf"] },
  { id: "vllm", icon: "⚡", labelKey: "runnerVllm", artifacts: ["*"] },
  { id: "transcribe", icon: "📝", labelKey: "runnerTranscribe", artifacts: ["asr-gguf"] },
  { id: "whisper", icon: "🎙", labelKey: "runnerWhisper", artifacts: ["whisper-size"] },
  { id: "qwen3-tts", icon: "🗣", labelKey: "runnerQwen3Tts", artifacts: ["st-qwen3-tts"], vramPlan: { fixedMiB: 9216 } },
  { id: "ollama", icon: "🟠", labelKey: "runnerOllama", editorTab: false },
  { id: "translate", icon: "🔄", labelKey: "runnerTranslate", artifacts: ["nllb-repo"] },
  { id: "seamless", icon: "🌐", labelKey: "runnerSeamless", artifacts: ["seamless-st"] },
  { id: "gr00t", icon: "🦾", labelKey: "runnerGr00t", artifacts: ["gr00t-st"] },
  { id: "strata", icon: "🪨", labelKey: "runnerStrata", artifacts: ["strata-gguf"], workFolder: true },
  { id: "personaplex", labelKey: "runnerPersonaplex", artifacts: ["personaplex-st"] },
  { id: "step-audio2", labelKey: "runnerStepAudio2", artifacts: ["step-audio2-st"] },
  { id: "qwen3-omni", labelKey: "runnerQwen3Omni", artifacts: ["qwen3-omni-st"] },
  { id: "minicpm-omni", labelKey: "runnerMinicpmOmni", artifacts: ["gguf"] },
  // Two that take nothing from the model list: any model leaves them "available", and neither runs one.
  { id: "voice-clone", labelKey: "runnerVoiceClone", artifacts: ["*"], sharedPicker: "ignored" },
  { id: "custom", labelKey: "runnerCustom", artifacts: ["*"], sharedPicker: "ignored" },
];
const KIND = { [GIGA]: "asr-gguf", [WHISPER]: "whisper-size", [TTS]: "st-qwen3-tts" };
const NAMED = { [GIGA]: "transcribe", [WHISPER]: "whisper", [TTS]: "qwen3-tts" };
const NODE = { id: "hotel", name: "hotel", gpus: [
  { index: 0, name: "NVIDIA GeForce RTX 3090", memoryTotalMiB: "24576", memoryUsedMiB: "0" },
  { index: 1, name: "NVIDIA GeForce RTX 5090", memoryTotalMiB: "32607", memoryUsedMiB: "0" }],
  cpu: { ram: { totalGb: 60.5, usedGb: 9.2 } }, servers: [{ cellId: "c22020", port: null, slotConfig: { MODEL_FILE: HERMES } }] };
const BOXES = ["ENABLE_FLASH_ATTN", "ENABLE_THINKING", "KV_UNIFIED", "SPEC_ENABLED", "cacheModels", "MMAP"];
// The cell form as CellForm answers (remote-cells.js): a cell is held by its key — "new:<machine>" for one not made yet — and once a save
// made it, the form holds it by the name the controller gave it (`cellId`). Its config carries no port.
class Form {
  constructor() { this.fields = {}; this.boxes = {}; this.calls = []; this.mayFillAnswer = true; this.saveAnswer = true; this.madeAs = "c3f9a02b1"; this.held = ""; }
  async mayFill(key) { this.calls.push(["mayFill", key]); return this.mayFillAnswer; }
  fill(key, opts) {
    this.calls.push(["fill", key, opts]);
    this.held = "";
    this.fields = { CTX_SIZE: "", PARALLEL: "1", CACHE_TYPE_K: "q8_0", CACHE_TYPE_V: "q8_0", N_GPU_LAYERS: "999", BATCH_SIZE: "1024",
                    UBATCH_SIZE: "1024", MODEL_FILE: "", ALIAS: "", RUNNER: "" };
    this.boxes = { ENABLE_FLASH_ATTN: true, ENABLE_THINKING: true, KV_UNIFIED: false, SPEC_ENABLED: false, cacheModels: true };
    return true;
  }
  cellId() { return this.held; }
  // As the real form reads: a runner that names its model in a field of its own carries no MODEL_FILE.
  read() { return { ...this.fields, ...(["vllm", "whisper", "moonshine"].includes(this.fields.RUNNER) ? { MODEL_FILE: "" } : {}) }; }
  set(f, v) { this.calls.push(["set", f, String(v)]); if (BOXES.includes(f)) this.boxes[f] = String(v) === "1"; else this.fields[f] = String(v); return true; }
  checked(f) { return !!this.boxes[f]; }
  async save(opts) { this.calls.push(["save", opts]); if (this.saveAnswer) this.held = this.madeAs; return this.saveAnswer; }
  show() { this.calls.push(["show"]); }
}
class Settings {
  constructor() { this.calls = []; }
  adopt(k, o) { this.calls.push(["adopt", k, o]); return true; }
  release(k) { this.calls.push(["release", k]); return true; }
  placeHtml(k) { return `<div data-cell-window-place="${k}">the map</div>`; }
  html(k) { return `<section data-cell-settings-view="${k}">all fields</section>`; }
  mountMap() { this.calls.push(["mount"]); return true; }
  sync() { this.calls.push(["sync"]); return true; }
}
const el = () => ({ hidden: true, innerHTML: "", listeners: {}, addEventListener(k, fn) { (this.listeners[k] ||= []).push(fn); }, querySelector: () => null, contains: () => false });
const make = (over = {}) => {
  const form = new Form();
  const settings = new Settings();
  const root = el();
  let runner = "llama-server";
  const log = { picks: [], runners: [], compute: [], starts: [], later: [], notes: [] };
  const doc = { body: { appendChild: (x) => { doc.made = x; } }, getElementById: (id) => (id === "addModelOverlay" && doc.made ? doc.made : null),
                createElement: () => root, activeElement: null };
  const wiz = new AddModel({
    form, settings, doc: () => doc, newKey: (h) => `new:${h}`, node: (h) => (h === "hotel" ? NODE : null), choices: () => CHOICES, rows: () => ROWS,
    picked: () => form.fields.MODEL_FILE,
    pickModel: (v) => { log.picks.push(v); form.fields.MODEL_FILE = v; runner = NAMED[v] || (v === COSMOS ? "vllm" : "llama-server"); form.fields.RUNNER = runner; form.fields.ALIAS = v.split("/").pop().replace(".gguf", "").toLowerCase(); },
    runner: () => runner, chooseRunner: (id) => { log.runners.push(id); runner = id; }, runners: () => RUNNERS,
    llama: (id) => RUNNERS.find((r) => r.id === id)?.llamaConfig === true,
    // The form's own question: can this runner launch the model picked — by the kinds its row names (runnerAvailability).
    available: (r) => { const kind = KIND[form.fields.MODEL_FILE] || "llm-gguf"; return (r.artifacts || []).some((a) => a === "*" || a === kind); },
    naming: (v) => RUNNERS.find((r) => r.id === (NAMED[v] || "")) || null,
    compute: (sel) => log.compute.push(sel), kvGb: (row) => (row === ROWS.get(HERMES) ? 5.31 : 1.0),
    favorites: () => ["CTX_SIZE", "SPEC_TYPE", "MMAP", "CACHE_TYPE_V", "EXTRA_ARGS"], start: async (cellId) => log.starts.push(cellId),
    notify: (words) => log.notes.push(words), defaults: () => ({}), later: (fn) => log.later.push(fn), ...over,
  });
  return { wiz, form, settings, root, log, doc };
};
const hooks = (html, hook) => [...String(html).matchAll(new RegExp(`data-t="${hook}" data-t-id="([^"]*)"`, "g"))].map((m) => m[1]);
const pressed = (html, hook) => [...String(html).matchAll(new RegExp(`aria-pressed="true"[^>]*data-t="${hook}" data-t-id="([^"]*)"`, "g"))].map((m) => m[1]);
const text = (html) => String(html).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();

// ── a model whose runner names it in a field of its own: the form's reading has no MODEL_FILE for it ──
{
  const choice = { value: COSMOS, kind: "st", stName: "Cosmos-Reason2-2B", stArch: "qwen3_vl", sizeGb: 4.6, window: 262144 };
  const pickedStep = async (value, choices) => {
    const { wiz, form } = make({ choices: () => choices });
    await wiz.open("hotel");
    const row = text(wiz.rowHtml(choices.find((c) => c.value === value)));
    wiz.pick(value);
    const nextShut = /data-am-next[^>]*disabled|disabled[^>]*data-am-next/.test(wiz.footHtml());
    return { read: form.read().MODEL_FILE, picked: wiz.picked(), named: wiz.choice()?.value || null, step: wiz.step, nextShut, runners: hooks(wiz.stepHtml(), "add-model-runner").length > 0, row };
  };
  out.checkpointPick = await pickedStep(COSMOS, [...CHOICES, choice]);
  out.whisperPick = await pickedStep(WHISPER, CHOICES);
  const none = make();
  await none.wiz.open("hotel");
  out.nonePicked = [none.wiz.picked(), none.wiz.choice()];
}

// ── opening ──
{
  const { wiz, form, settings } = make();
  form.mayFillAnswer = false;
  out.refused = [await wiz.open("hotel"), form.calls.map((c) => c[0]), settings.calls.length, wiz.opened];
}
const A = make();
out.opened = [await A.wiz.open("hotel"), A.form.calls.filter((c) => c[0] === "fill"), [...A.settings.calls], A.root.hidden, A.wiz.key, A.wiz.step];
out.dialog = /data-t="add-model" data-t-id="new:hotel" data-t-state="pick"/.test(A.root.innerHTML) && /role="dialog"/.test(A.root.innerHTML);
out.sub = text(A.wiz.headHtml());
out.band = text(A.wiz.bandHtml());
out.rail = [...A.root.innerHTML.matchAll(/data-am-step="(\d)"[^>]*?( disabled)?>/g)].map((m) => [m[1], !!m[2]]);

// ── the first step ──
const tiles = A.wiz.tilesHtml();
out.tiles = [...tiles.matchAll(/data-am-job="([^"]*)"[^>]*aria-pressed="(true|false)">.*?<b>([^<]*)<\/b><span class="am-tile-count">([^<]*)<\/span><span class="am-tile-runners">([^<]*)<\/span>/g)]
  .map((m) => [m[1], m[2] === "true", m[3], m[4], m[5]]);
const rows = () => hooks(A.wiz.listHtml(), "add-model-row").map((v) => v.split("/").pop());
out.list = { llm: rows() };
A.wiz.toggleAbility("projector"); out.list.projector = rows();
A.wiz.toggleAbility("projector"); A.wiz.toggleAbility("long"); out.list.long = rows();
A.wiz.toggleAbility("cell"); out.list.longCell = rows();
A.wiz.toggleAbility("long"); out.list.cell = rows();
A.wiz.toggleAbility("cell");
out.abilitiesShown = [A.wiz.abilitiesHtml().includes('data-t="add-model-ability"'), (A.wiz.setJob("asr"), A.wiz.abilitiesHtml()), rows()];
A.wiz.setQuery("WHISPER"); out.list.query = rows(); A.wiz.setQuery("");
A.wiz.setJob("llm");
const ratedRow = (rating) => A.wiz.rowHtml({ ...CHOICES[0], rating }).split('<span class="am-row-name">')[1].split("</b>")[0];
out.ratedRow = [ratedRow("like").includes('data-t="model-rating" data-t-state="like"'), ratedRow("").includes("model-rating")];
const rowOf = (value) => { const h = A.wiz.rowHtml(CHOICES.find((c) => c.value === value)); return { window: text((h.match(/<span class="am-row-window[^"]*"[^>]*>([^<]*)<\/span>/) || [])[0] || ""),
  size: text((h.match(/<span class="am-row-size">([^<]*)<\/span>/) || [])[1] || ""), fit: (h.match(/<span class="am-row-fit ([a-z]+)">([^<]*)<\/span>/) || []).slice(1),
  facts: text((h.match(/<span class="am-row-name"><b>[^<]*<\/b><span>([^<]*)<\/span>/) || [])[1] || "") }; };
out.rows = { hermes: rowOf(HERMES), coder: rowOf(CODER), giga: rowOf(GIGA), whisper: rowOf(WHISPER), tts: rowOf(TTS) };
out.figures = { hermes: A.wiz.figures(CHOICES[0]).window, coder: A.wiz.figures(CHOICES[1]).window, emb: A.wiz.figures(CHOICES[3]).window,
                tts: [A.wiz.figures(CHOICES[6]).window, A.wiz.figures(CHOICES[6]).runner] };
// A speculative draft the form holds (2026-11-07): the list weighs each model alone — the form's draft is another model's, as its
// projector is — and the model picked is weighed with the draft the form holds, its own cache said not counted.
{
  const DRAFT = "Hermes-4-70B-GGUF/lmstudio-community/Q4_K_M/mtp-Hermes-4-70B.gguf";
  const withDraft = new Map([...ROWS, [DRAFT, { path: DRAFT, kind: "draft", sizeGb: 1.28, ggufMeta: { blockCount: 80 } }]]);
  const D = make({ rows: () => withDraft });
  await D.wiz.open("hotel");
  const alone = D.wiz.figures(CHOICES[0]).size;
  Object.assign(D.form.fields, { SPEC_TYPE: "draft-mtp", SPEC_DRAFT_MODEL_FILE: DRAFT });
  D.wiz.base = { ...D.form.read() };
  D.wiz.figured.clear();
  const listed = D.wiz.figures(CHOICES[0]).size;
  D.wiz.pick(HERMES);
  out.draftList = { alone, listed, picked: D.wiz.now().size };
}
out.empty = (A.wiz.query = "zzz", A.wiz.listHtml().includes('data-t="add-model-empty"'));
A.wiz.query = "";
out.noNext = [A.wiz.go(1), A.wiz.step, A.wiz.footHtml().includes('data-am-next data-t="add-model-next" disabled')];
{
  // Opened from a model of a machine's list: its work and words, or straight past the first question when it has one build.
  const Words = make();
  await Words.wiz.open("hotel", { query: "Hermes", job: "asr" });
  const One = make();
  await One.wiz.open("hotel", { value: HERMES, query: "x", job: "llm" });
  const Plain = make();
  await Plain.wiz.open("hotel");
  const Gone = make();
  await Gone.wiz.open("hotel", { value: "no/such/model/at.gguf", query: "no", job: "llm" });
  out.openOn = { words: [Words.wiz.query, Words.wiz.job, Words.wiz.step], one: [One.wiz.step, One.log.picks], plain: [Plain.wiz.query, Plain.wiz.job, Plain.wiz.step], gone: [Gone.wiz.step, Gone.log.picks.length] };
}

// ── a pick ──
out.pick = [A.wiz.pick(HERMES), A.log.picks, A.form.calls.filter((c) => c[0] === "set").map((c) => c.slice(1)), A.wiz.step];
out.pickCompute = A.log.compute.splice(0);
{
  // What is shown is written only where nothing was chosen: a card pinned, the processor, another runner keep their own.
  const P = make();
  await P.wiz.open("hotel");
  P.form.fields.DEVICE = "CUDA1"; P.wiz.pick(CODER); const pinned = P.log.compute.splice(0);
  P.form.fields.DEVICE = ""; P.form.fields.N_GPU_LAYERS = "0"; P.wiz.pick(CODER); const cpu = P.log.compute.splice(0);
  P.form.fields.N_GPU_LAYERS = "999"; P.wiz.pick(GIGA); const other = P.log.compute.splice(0);
  out.pickComputeNot = [pinned, cpu, other];
}
out.pickBand = text(A.wiz.bandHtml());
// No port anywhere in the wizard: a new cell has none, and its scout leases one at each start.
out.portless = [text(A.wiz.footHtml()), text(A.wiz.cellHtml()), [A.wiz.headHtml(), A.wiz.footHtml(), A.wiz.cellHtml(), A.root.innerHTML].some((h) => /:\d{4,5}\b|\b22\d{3}\b/.test(h))];
out.unknownPick = A.wiz.pick("nowhere.gguf");

// ── the runner ──
const runnerHtml = A.wiz.runnerStepHtml();
out.runner = { chosen: text((runnerHtml.match(/<div class="am-runner-chosen"><b>([^<]*)<\/b>/) || [])[1] || ""), others: hooks(runnerHtml, "add-model-runner"),
               full: runnerHtml.includes('data-t="add-model-full"'), comps: runnerHtml.includes("am-comps") };
out.useRunner = [A.wiz.useRunner("prism"), [...A.log.runners]];
A.wiz.useRunner("llama-server");
const G = make();
await G.wiz.open("hotel");
G.wiz.pick(GEMMA);
const gr = G.wiz.runnerStepHtml();
out.comps = { projector: [...gr.matchAll(/<option value="([^"]*)"/g)].map((m) => m[1]), draft: gr.includes('data-t="add-model-draft"') };
G.wiz.onChange({ target: { value: "gemma-4-31B-it-GGUF/unsloth/Q4_K_M/mmproj-F16.gguf", closest: (s) => (s === "[data-am-mmproj]" ? {} : null) } });
G.wiz.onClick({ target: { dataset: { amToggle: "SPEC_ENABLED" }, getAttribute: () => "false", closest: (s) => (s === "[data-am-toggle]" ? { dataset: { amToggle: "SPEC_ENABLED" }, getAttribute: () => "false" } : null) } });
out.compsSet = G.form.calls.filter((c) => c[0] === "set" && ["MMPROJ_FILE", "SPEC_ENABLED"].includes(c[1])).map((c) => c.slice(1));

// ── the third step ──
A.wiz.go(2);
const main = A.wiz.mainHtml();
out.main = {
  ctx: [...main.matchAll(/data-am-set="CTX_SIZE" data-am-value="(\d+)"/g)].map((m) => Number(m[1])), ctxOn: pressed(main, "add-model-ctx"),
  tags: [...main.matchAll(/data-t="add-model-ctx" data-t-id="(\d+)">[^<]*<span class="ui-count">([^<]*)<\/span>/g)].map((m) => [m[1], m[2]]),
  par: pressed(main, "add-model-parallel"), cache: pressed(main, "add-model-cache"), where: hooks(main, "add-model-where"), whereOn: pressed(main, "add-model-where"),
  flash: /aria-checked="true"[^>]*data-am-toggle="ENABLE_FLASH_ATTN"/.test(main), think: /aria-checked="true"[^>]*data-am-toggle="ENABLE_THINKING"/.test(main),
  name: (main.match(/data-am-field="MODEL_NAME"[^>]*placeholder="([^"]*)"/) || [])[1], starred: hooks(main, "add-model-starred"),
  hint: text(main).includes(en.amCtxTrained.replace("{n}", "131,072")), cost: text(main).includes(en.amCtxCost.replace("{gb}", "5.3")),
  per: text(main).includes(en.amPerRequest.split("{n}")[0].trim()),
};
A.form.calls.length = 0;
const click = (attrs) => A.wiz.onClick({ target: { closest: (s) => { const m = /^\[data-am-([a-z-]+)\]$/.exec(s); const key = m && m[1].replace(/-([a-z])/g, (x, c) => c.toUpperCase());
  const set = s === "[data-am-set]" ? attrs.set : null; if (s === "[data-am-set]" && attrs.set) return { dataset: { amSet: attrs.set, amValue: attrs.value } };
  if (s === "[data-am-toggle]" && attrs.toggle) return { dataset: { amToggle: attrs.toggle }, getAttribute: () => (attrs.on ? "true" : "false") };
  return key && attrs[key] !== undefined ? { dataset: { [`am${key[0].toUpperCase()}${key.slice(1)}`]: attrs[key] } } : null; } } });
click({ set: "CTX_SIZE", value: "131072" });
click({ set: "PARALLEL", value: "4" });
click({ set: "CACHE_TYPE", value: "f16" });
click({ toggle: "ENABLE_THINKING", on: true });
click({ set: "WHERE", value: "1" });
click({ set: "WHERE", value: "cpu" });
click({ set: "WHERE", value: "all" });
out.writes = A.form.calls.filter((c) => c[0] === "set").map((c) => c.slice(1));
out.per4 = text(A.wiz.mainHtml()).includes(en.amPerRequest.replace("{n}", "32,768"));
out.compute = A.log.compute;
A.wiz.onInput({ target: { value: "0.6", dataset: { amField: "TEMPERATURE" }, closest: (s) => (s === "[data-am-field]" ? { dataset: { amField: "TEMPERATURE" }, value: "0.6" } : null) } });
out.typed = A.form.fields.TEMPERATURE;
// The window the start asks for does not fit whole: a smaller one is offered — for an empty field too, against the trained one.
A.form.fields.CTX_SIZE = ""; A.form.fields.N_GPU_LAYERS = "auto"; A.form.fields.PARALLEL = "1"; A.form.fields.CACHE_TYPE_K = "q8_0"; A.form.fields.CACHE_TYPE_V = "q8_0";
out.tipEmpty = [A.wiz.tip(), text(A.wiz.placeHtml()).includes(en.amTip.replace("{n}", "65,536").replace("{was}", "131,072"))];
A.form.fields.CTX_SIZE = "131072"; A.form.fields.N_GPU_LAYERS = "auto"; A.form.fields.PARALLEL = "1"; A.form.fields.CACHE_TYPE_K = "q8_0"; A.form.fields.CACHE_TYPE_V = "q8_0";
const place = A.wiz.placeHtml();
out.tip = [A.wiz.tip(), (place.match(/data-am-value="(\d+)" data-t="add-model-tip"/) || [])[1] || null, place.includes("the map")];
A.form.fields.CTX_SIZE = "8192";
out.noTip = [A.wiz.tip(), A.wiz.placeHtml().includes("add-model-tip")];
out.all = [text(A.wiz.allHtml()).includes(en.amAllTitle.replace("{n}", "108")), A.wiz.allHtml().includes("all fields"), A.wiz.toggleAll(), A.wiz.allHtml().includes("all fields")];
// A star in the full list: drawn again once the editor wrote it.
A.log.later.length = 0;
out.star = [A.wiz.onClick({ target: { closest: (s) => (s === "[data-cell-settings-star]" ? {} : null) } }), A.log.later.length];
A.log.later.length = 0;
out.mapClick = [A.wiz.onClick({ target: { closest: (s) => (s === "[data-cell-window-place] button" ? {} : null) } }), A.log.later.length,
                A.wiz.onClick({ target: { closest: () => null } }), A.log.later.length];

// Another runner: no eight here, the full form.
const T = make();
await T.wiz.open("hotel");
T.wiz.setJob("tts"); T.wiz.pick(TTS); T.wiz.go(2);
const tm = T.wiz.mainHtml();
out.tts = { eight: tm.includes('data-t="add-model-ctx"'), full: tm.includes('data-t="add-model-full"'), note: text(tm).includes(en.amRunnerFields.replace("{runner}", "Qwen3-TTS")),
            all: T.wiz.allHtml(), map: T.wiz.placeHtml().includes("the map") };

// ── Create, Create and start, the full form, closing ──
A.form.calls.length = 0; A.settings.calls.length = 0;
out.create = [await A.wiz.create(true), A.form.calls.filter((c) => c[0] === "save"), A.settings.calls, A.log.starts, A.root.hidden, A.wiz.opened, A.log.notes];
{
  // A save that answered no name: the cell may not be one, and nothing is started by a guess — it is said.
  const U = make();
  await U.wiz.open("hotel"); U.wiz.pick(HERMES);
  U.form.madeAs = "";
  out.createUnnamed = [await U.wiz.create(true), U.log.starts, U.log.notes, U.wiz.opened];
  // Create alone starts nothing, named or not.
  const O = make();
  await O.wiz.open("hotel"); O.wiz.pick(HERMES);
  out.createOnly = [await O.wiz.create(false), O.log.starts, O.log.notes];
}
const R = make();
await R.wiz.open("hotel"); R.wiz.pick(HERMES);
R.form.saveAnswer = false;
out.refusedSave = [await R.wiz.create(true), R.wiz.opened, [...R.log.starts], R.settings.calls.filter((c) => c[0] === "release").length];
out.closeBeforePick = (() => { const N = make(); return N; })();
const N = make();
await N.wiz.open("hotel");
out.createNothing = [await N.wiz.create(false), N.form.calls.filter((c) => c[0] === "save").length];
out.full = [N.wiz.full(), N.form.calls.filter((c) => c[0] === "show").length, N.settings.calls.filter((c) => c[0] === "release").map((c) => c[1]), N.root.hidden];
const C = make();
await C.wiz.open("hotel");
out.close = [C.wiz.close(), C.wiz.close(), C.settings.calls.filter((c) => c[0] === "release").length, C.root.hidden];
{
  // A runner that keeps its models in a folder of its own (Strata) has no keep switch: the words say where the models stay.
  const K = make({ runner: () => "strata" });
  const L = make();
  out.keepByFolder = [K.wiz.cellHtml().includes('data-t="add-model-keep-folder"'), K.wiz.cellHtml().includes("add-model-keep\""), text(K.wiz.cellHtml()),
                      L.wiz.cellHtml().includes('data-t="add-model-keep"'), L.wiz.cellHtml().includes("add-model-keep-folder")];
}
{
  // The launch builder's Start (machine-build.js): the form filled for the new port as the wizard fills it, the model, the engine and the
  // set written, read back with its keep switch — no window opened, nothing saved here.
  const F = make();
  // A port given along is no part of a new cell: the form is filled under the machine's key, and nothing carries the number.
  out.formConfig = await F.wiz.formConfig({ hostId: "hotel", port: "22077", file: HERMES, runner: "llama-server", fields: { CTX_SIZE: "65536", TEMPERATURE: "0.6" } });
  out.formConfigCalls = F.form.calls.filter((c) => c[0] !== "set").map((c) => c.slice(0, 3)).concat([F.log.picks, F.log.runners, F.root.hidden, F.wiz.opened]);
  out.formConfigWrites = F.form.calls.filter((c) => c[0] === "set").map((c) => c.slice(1));
  const H = make();
  H.form.mayFillAnswer = false;
  out.formConfigHeld = [await H.wiz.formConfig({ hostId: "hotel", file: HERMES, runner: "llama-server" }), H.form.calls.map((c) => c[0])];
  const E = make();
  out.formConfigMissing = [await E.wiz.formConfig({ hostId: "hotel", file: "", runner: "llama-server" }),
                           await E.wiz.formConfig({ hostId: "", file: HERMES, runner: "llama-server" }), E.form.calls.length];
}
console.log(JSON.stringify(out));
'''


def main():
    node = find_node()
    if node is None:
        print("js add-model: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_add_model.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT,
                              env=env, timeout=120)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js add-model: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:3000])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    en = got.get("en", {})

    print("окна:")
    w = got["windows"]
    check(w["hermes"] == [4096, 8192, 16384, 32768, 65536, 131072], "обычные окна до обученного (131 072) включительно")
    check(w["odd"] == [131072, 262144, 500000] and w["unknown"] == [131072],
          "обученное окно не из обычных встаёт в ряд; negative: окно не названо — обычные до 131 072")
    check(w["propose"] == "undefined",
          "defect-history (2026-10-26): окна, которое никто не вводил, мастер больше не предлагает и не пишет — правило "
          "«наибольшее, что карты держат целиком» ушло; меньшее окно — только советом с кнопкой")

    print("открытие:")
    for name, pick in (("checkpointPick", got["checkpointPick"]), ("whisperPick", got["whisperPick"])):
        check(pick["read"] == "" and pick["picked"] and pick["named"] == pick["picked"] and pick["step"] == 1 and not pick["nextShut"] and pick["runners"],
              f"defect-history (2026-11-03): {name}: чтение формы пусто у раннера со своим полем модели, а мастер всё равно знает выбор: второй шаг с раннерами и Next открыт (got {pick})")
    check("4.6" in got["checkpointPick"]["row"] and "not known" not in got["checkpointPick"]["row"],
          f"папка, которую не называет ни один раннер, считается как у vLLM: её размер известен, а не «size not known» от llama.cpp (got {got['checkpointPick']['row']})")
    check(got["nonePicked"] == ["", None], f"negative: ничего не выбрано — пусто и нет модели, а не догадка (got {got['nonePicked']})")
    check(got["refused"] == [False, ["mayFill"], 0, False],
          "negative: окно ячейки держит правки, оператор не отпустил — форму не заполняют, мастер не открывается")
    op = got["opened"]
    check(op[0] is True and op[1] == [["fill", "new:hotel", {"pickModel": True, "hidden": True}]]
          and op[2] == [["adopt", "new:hotel", {"onlySet": False}]] and op[3] is False and op[4] == "new:hotel" and op[5] == 0,
          "форма заполнена для новой ячейки машины (её ключ — ключ формы для ещё не созданной) без своего диалога, её берёт редактор настроек; "
          "мастер — на первом шаге; negative: ни имени ячейки, ни порта — их нет, пока «Создать» её не сохранит")
    check(got["dialog"], "мастер — диалог с хуком add-model, data-t-id — ключ будущей ячейки, data-t-state — шаг")
    check(got["sub"].startswith("New cell") and "on hotel" in got["sub"] and not re.search(r"\b22\d{3}\b", got["sub"]),
          "в шапке — машина; negative (1.3.655): порта нет — его берёт караван, модель зовут по имени (шаг 3 плана)")
    check(got["band"].startswith("Choose what the model is for"), "модели ещё нет — полоса так и говорит")
    pl = got["portless"]
    check(pl[0].startswith("Will be: Hermes") and " on hotel · " in pl[0] and pl[1].startswith("Cell") and pl[2] is False,
          f"итог внизу — модель на машине, раздел ячейки — без номера; negative (1.3.655): порта нет нигде в мастере (got {pl[:2]})")
    check(got["rail"] == [["0", False], ["1", True], ["2", True]], "negative: до выбора модели второй и третий шаги закрыты")
    kb = got["keepByFolder"]
    check(kb[0] is True and kb[1] is False and "Strata keeps its models in its own folder" in kb[2] and kb[3] is True and kb[4] is False,
          f"Strata держит модели в своей папке: вместо переключателя «хранить модель» — слова, где они лежат; negative: у llama.cpp переключатель на месте (got {kb})")

    print("первый шаг:")
    tl = got["tiles"]
    check([x[0] for x in tl] == ["llm", "embed", "asr", "tts", "translate", "speech-translate", "voice-chat", "robot-policy"]
          and tl[0][1] is True, "плитки — работы словаря по его порядку; выбрана LLM")
    check(tl[0][3] == "models: 3" and tl[2][3] == "models: 2" and tl[1][3] == "models: 1" and tl[7][3] == "models: 0",
          "у плитки — сколько моделей этой работы в списке")
    check(tl[0][4] == "llama.cpp" and tl[2][4] == "transcribe.cpp · whisper" and tl[7][4] == "GR00T",
          "раннеры плитки — те, на которые ляжут её модели; работа без моделей — раннеры из таблицы работ")
    ls = got["list"]
    check(ls["llm"] == ["Hermes-4-70B-Q4_K_M.gguf", "Qwen3-Coder-30B-A3B-Instruct-1M-Q4_K_M.gguf", "gemma-4-31B-it-Q4_K_M.gguf"],
          "список — модели выбранной работы (векторы и речь не в LLM)")
    check(ls["projector"] == ["gemma-4-31B-it-Q4_K_M.gguf"] and ls["long"] == ["Qwen3-Coder-30B-A3B-Instruct-1M-Q4_K_M.gguf", "gemma-4-31B-it-Q4_K_M.gguf"]
          and ls["longCell"] == [] and ls["cell"] == ["Hermes-4-70B-Q4_K_M.gguf"],
          "умения сужают: проектор, контекст от 262 144, ячейка уже есть; два условия вместе")
    ab = got["abilitiesShown"]
    check(ab[0] is True and ab[1] == "" and ab[2] == ["gigaam-v3-e2e-rnnt-Q8_0.gguf", "models--Systran--faster-whisper-large-v3-turbo"],
          "умения — только у LLM; у речи их нет, а условия LLM речь не сужают")
    check(ls["query"] == ["models--Systran--faster-whisper-large-v3-turbo"], "поиск по имени, без учёта регистра")
    check(got["ratedRow"] == [True, False], "мастер новой ячейки: у строки модели — её оценка рядом с именем; negative: без оценки значка нет")
    rw = got["rows"]
    check(rw["hermes"]["window"] == "131,072" and rw["coder"]["window"] == "1,048,576", "у строки — окно, на котором обучены веса")
    check(rw["giga"]["window"] == "—" and rw["whisper"]["window"] == "—",
          "у работы без окна в токенах — прочерк, а не «не известен» и не 0")
    check("with the cache" in rw["hermes"]["size"] and "at a window of 131,072" in rw["hermes"]["size"] and rw["hermes"]["fit"][0] != "good",
          "Hermes взвешен планом при окне, с которым стартует пустое поле, — обученном 131 072: с кэшем, и строка честно говорит, "
          "что целиком он не ляжет")
    check("on this machine already: 1" in rw["hermes"]["facts"] and ":22020" not in rw["hermes"]["facts"],
          "строка говорит, сколько ячеек этой модели здесь уже есть; negative (1.3.655): без их портов")
    check(rw["tts"]["size"].startswith("≈9.0 GB") and rw["tts"]["window"] == "—", "голосовая — по цифре своего раннера (9 ГБ)")
    fg = got["figures"]
    check(fg["hermes"] == 131072 and fg["coder"] == 1048576 and fg["emb"] == 32768,
          "пустое поле — окно, на котором модель обучена: 131 072, 1 048 576, 32 768; меньшее, что влезает целиком, больше не "
          "подставляется (владелец, 2026-10-26)")
    check(fg["tts"] == [None, "qwen3-tts"], "negative: не llama.cpp — окна не предлагается, раннер тот, что назван для модели")
    dl = got["draftList"]
    check(dl["alone"] == "≈64.0 GB with the cache" and dl["listed"] == dl["alone"],
          f"черновик, что держит форма, — чужой модели списка: список весит модель одну, как и без проектора; "
          f"negative: черновик формы не прибавлен к Hermes (got {dl})")
    check(dl["picked"] == "≈65.3 GB with the cache · the draft's own cache is not counted",
          f"выбранная модель — с черновиком, что держит форма: +1.28 ГБ, и сказано, что его собственный кэш не посчитан (got {dl['picked']!r})")
    check(got["empty"] is True, "ничего не нашлось — так и сказано, со ссылкой на Hugging Face")
    check(got["noNext"] == [False, 0, True], "negative: без модели «Дальше» закрыто и на шаг вперёд не пускает")
    on = got["openOn"]
    check(on["words"] == ["Hermes", "asr", 0], "открыт со списка моделей машины: на работе и словах этой модели, модель ещё выбирать")
    check(on["one"] == [1, ["Hermes-4-70B-GGUF/lmstudio-community/Q4_K_M/Hermes-4-70B-Q4_K_M.gguf"]], "сборка одна: сразу дальше, первый вопрос уже отвечен")
    check(on["plain"] == ["", "llm", 0], "negative: без модели мастер открывается как всегда")
    check(on["gone"] == [0, 0], "negative: файла, которого нет в списке, мастер не выбирает и остаётся на первом вопросе")

    print("выбор модели:")
    pk = got["pick"]
    check(pk[0] is True and pk[1] == ["Hermes-4-70B-GGUF/lmstudio-community/Q4_K_M/Hermes-4-70B-Q4_K_M.gguf"] and pk[3] == 1,
          "модель выбирается выбором самой формы — и мастер на втором шаге")
    check(pk[2] == [], "negative: выбор модели окна в форму не пишет — поле пустое, старт попросит окно обучения")
    check(got["pickBand"].startswith("Hermes-4-70B-Q4_K_M.gguf · llama.cpp"), "полоса — модель, раннер, вес и место")
    check(got["unknownPick"] is False, "negative: модели нет в списке — ничего не выбрано")
    check(got["pickCompute"] == [{"mode": "gpu", "gpuIdx": [0, 1]}],
          "модель llama.cpp в форме без карты: «все карты», которые мастер показывает, записаны правилом цели счёта — "
          "не 999 слоёв, которые карта рисует как разбивку рукой с предупреждением")
    check(got["pickComputeNot"] == [[], [], []],
          "negative: карта уже выбрана, выбран процессор или раннер не llama.cpp — мастер ничего не пишет")

    print("как запускать:")
    rn = got["runner"]
    check(rn["chosen"] == "🦙 llama.cpp" and rn["others"] == ["prism", "vllm"] and rn["full"],
          "раннер для модели и другие, что умеют её запустить (у движков вкладки нет; клон голоса и команда моделей из списка "
          "не берут — их нет); полная форма — все раннеры")
    check(got["useRunner"] == ["prism", ["prism"]], "выбор раннера пишет его в форму")
    cp = got["comps"]
    check(cp["projector"] == ["", "gemma-4-31B-it-GGUF/unsloth/Q4_K_M/mmproj-F16.gguf"] and cp["draft"] is True,
          "проектор — из списка, что форма предлагает модели (или только текст); черновик — выключателем")
    check(got["compsSet"] == [["MMPROJ_FILE", "gemma-4-31B-it-GGUF/unsloth/Q4_K_M/mmproj-F16.gguf"], ["SPEC_ENABLED", "1"]],
          "проектор и черновик пишутся в форму")
    check(rn["comps"] is False, "negative: у модели без проектора и черновика этих строк нет")

    print("место и настройки:")
    mn = got["main"]
    check(mn["ctx"] == [4096, 8192, 16384, 32768, 65536, 131072, 262144] and mn["ctxOn"] == [str(fg["hermes"])],
          "окна — обычные до обученного и одно растянутое; нажато записанное")
    check(["131072", "max"] in mn["tags"] and ["262144", "YaRN"] in mn["tags"], "обученное помечено «max», большее — YaRN")
    check(mn["par"] == ["1"] and mn["cache"] == ["q8_0"] and mn["where"] == ["all", "0", "1", "cpu"] and mn["whereOn"] == ["all"],
          "запросы, тип кэша, где считать — нажато то, что в форме")
    check(mn["flash"] and mn["think"] and mn["name"] == "hermes-4-70b-q4_k_m", "выключатели — как в форме; у имени — подсказка алиасом")
    check(mn["starred"] == ["SPEC_TYPE", "MMAP"],
          "со звёздочкой — избранные, кроме восьми главных и того, что они уже задают (тип V-кэша, EXTRA_ARGS)")
    check(mn["hint"] and mn["cost"] and not mn["per"], "предел модели и вес кэша — словами; negative: один запрос — про деление окна ни слова")
    check(got["per4"], "четыре запроса без общего кэша — окно делится: на один запрос 131 072 / 4")
    check(got["writes"] == [["CTX_SIZE", "131072"], ["PARALLEL", "4"], ["CACHE_TYPE_K", "f16"], ["CACHE_TYPE_V", "f16"], ["ENABLE_THINKING", "0"]],
          "нажатия пишут поля формы; тип кэша — оба поля сразу")
    check(got["compute"] == [{"mode": "gpu", "gpuIdx": [1]}, {"mode": "cpu"}, {"mode": "gpu", "gpuIdx": [0, 1]}],
          "где считать — правилом выбора вычислителя формы: одна карта, процессор, все карты")
    check(got["typed"] == "0.6", "набранное пишется в форму сразу")
    tp = got["tip"]
    check(tp[0] is not None and tp[0] < 131072 and tp[1] == str(tp[0]) and tp[2],
          "окно не влезает целиком — предложено меньшее, кнопкой; рядом карта окна ячейки")
    check(got["tipEmpty"] == [tp[0], True],
          "пустое поле — то же окно обучения, и тот же совет: «65 536 вместо 131 072», кнопкой; само поле мастер не трогает")
    check(got["noTip"] == [None, False], "negative: влезает — совета нет")
    al = got["all"]
    check(al == [True, False, True, True], "все 108 настроек свёрнуты (ни порта, ни адреса: порт даёт скаут при старте, слушает ячейка петлю своей машины — 2026-11-08); «Открыть все» вставляет редактор окна ячейки")
    check(got["star"] == ["star", 1], "звёздочка в полном списке — мастер перерисуется, когда редактор её запишет")
    check(got["mapClick"] == ["map", 1, None, 1],
          "defect-history (2026-10-26): кнопка карты («по ручкам», потоки для RAM) пишет форму сама — мастер перерисует полосу, "
          "главные поля и низ после неё (полоса говорила «влезает на карты» рядом с картой, положившей 2 слоя в RAM); "
          "negative: клик мимо — ничего")
    ts = got["tts"]
    check(ts["eight"] is False and ts["full"] and ts["note"] and ts["all"] == "" and ts["map"] is False,
          "negative: другой раннер — восьми главных нет, настройки — в полной форме; плана памяти и полного списка llama.cpp тоже нет")

    print("создать, полная форма, закрыть:")
    cr = got["create"]
    check(cr[0] is True and cr[1] == [["save", {"confirmed": True}]] and ["release", "new:hotel"] in cr[2] and cr[3] == ["c3f9a02b1"]
          and cr[4] is True and cr[5] is False and cr[6] == [],
          "«Создать и запустить» — «Применить» формы без её вопроса (сохранение создаёт ячейку), мастер закрыт и форма отпущена, потом запуск ячейки "
          "по имени, которое ей дал контроллер")
    check(got["createUnnamed"] == [True, [], ["The controller named no new cell: nothing was started"], False],
          "negative: сохранение не назвало ячейку — запускать по догадке нечего: сказано словами, ничего не запущено")
    check(got["createOnly"] == [True, [], []], "negative: «Создать» без запуска ничего не запускает и ничего не говорит")
    check(got["refusedSave"] == [False, True, [], 0], "negative: форма не сохранила — мастер открыт, ничего не запущено")
    check(got["createNothing"] == [False, 0], "negative: без модели «Создать» ничего не шлёт")
    check(got["full"] == [True, 1, ["new:hotel"], True], "«Полная форма» — сам диалог со всем заданным; мастер уступает и отпускает форму")
    check(got["close"] == [True, False, 1, True], "закрыть — форма отпущена; второй раз закрывать нечего")
    fc = got["formConfig"]
    check("PORT" not in fc["config"] and "22077" not in json.dumps(fc) and fc["config"]["MODEL_FILE"].endswith("Hermes-4-70B-Q4_K_M.gguf") and fc["config"]["CTX_SIZE"] == "65536"
          and fc["config"]["TEMPERATURE"] == "0.6" and fc["config"]["CACHE_TYPE_K"] == "q8_0" and fc["cacheModels"] is True,
          f"сборка запуска: форма заполнена для новой ячейки машины, как мастер её заполняет, — модель, движок, набор поверх её значений по умолчанию; "
          f"переключатель «держать» прочитан; negative: порта нет, даже когда его передали (получено {fc})")
    calls = got["formConfigCalls"]
    check(calls[:2] == [["mayFill", "new:hotel"], ["fill", "new:hotel", {"pickModel": True, "hidden": True}]] and calls[2][0].endswith("Hermes-4-70B-Q4_K_M.gguf") and calls[3] == ["llama-server"],
          "сначала спрошено, можно ли занять форму, потом заполнена под ключом новой ячейки машины, выбраны модель и движок")
    check(calls[4] is True and calls[5] is False and "save" not in [c[0] for c in calls[:2]], "negative: окно мастера не открыто и ничего не сохранено — сохраняет старт")
    check(got["formConfigWrites"] == [["CTX_SIZE", "65536"], ["TEMPERATURE", "0.6"]], "записаны только поля набора")
    check(got["formConfigHeld"] == [None, ["mayFill"]], "negative: форму держат правки другой ячейки — ничего не тронуто")
    check(got["formConfigMissing"] == [None, None, 0], "negative: без файла или без машины — ничего")

    print()
    if _fail:
        print(f"js add-model FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js add-model OK: мастер новой ячейки — окна, шаги, выбор, раннер, главное и всё, создание — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
