#!/usr/bin/env python3
"""Value snapshot: static/js/machine-build.js — the launch builder under the map of a machine's page (the owner, 2026-11-06; its look,
variant А «Ступени и рельс» of the shelf's mockups, 2026-11-07, in two rows by the owner's variant Б of 2026-11-08).

The owner: a launch is built of three parts — the engine (a turbine), the carrier · quant (a cartridge), the setting (sliders). The launch is
one rail of three places on top, and its places are the steps; under it one shelf shows one step's cards at a time, swiped sideways; a card
is carried up into the launch, or pressed, and the shelf moves on to the next step. Once an engine and a quant stand there the rail is the
strip, carried up onto the lanes as a cell is; until then the rail's end names the builder and gives the new-cell wizard. The builder decides nothing a cell decides: which engine takes which file is the rule it is told (the
board's builder tells it, with the registry), which engines are offered at all is the wizard's (runner-offer.js), and the strip is a cell
that is not made yet: no cellId and no port, laid on the map under the builder's own key (2026-11-08: a cell is named when it is made and
holds a port only while it runs).

Pinned by value, each claim with its negative:
  * nothing is drawn when no engines were told; with no model picked, the words say so;
  * two rows, the rail over the shelf: the rail's three places are the steps, numbered in order, the first shown; each is a tab and a
    button of its own; the shelf holds the cards of the step shown and no other; no steps row, no hint, no line of what is missing — the
    rail's end says the builder's name with what a start needs in its hover and holds the new-cell wizard the page hands it;
  * the engines offered: those the wizard offers that take a file of the model — an engine of its own, a voice clone, a runner that takes no
    file of it are not there; the quants by their folder and weight; the settings only after an engine;
  * a place pressed shows its step's cards, in the strip too; its frame outside its button does nothing; the cards of a step come in once;
  * a card put in its place moves the shelf on to the next step not done; a card that does not go with what is picked is dim, says why, and
    is refused; the owner's mark only warns;
  * engine + quant make the launch whole: chosen on the map under the builder's key, the rail made the strip with its handle, the button
    that chooses it named "new cell", and the map's last line under it; no port number anywhere; the places inside the strip stay the steps,
    buttons of their own as their ✕ is, so a press there neither chooses nor carries the strip;
  * ✕ empties its place, a press on the card in its place too; while the launch's start is being made, nothing changes — a card carried
    onto the rail neither;
  * a cell's settings carry no name, no files, no place, no engine, no port; its card names the cell by its cellId, and a row that names
    no cell is offered nothing; a saved set's numbers and switches become the config's words;
  * what the model's maker stated once is the first set (the preset a default cell became, 2026-11-07): its numbers as the config's words,
    named per field; none for an engine that writes no sampling flag of its own (no `llamaConfig`), none for a model the table does not name;
  * the sets are read once; reading, failed, rows left out — each said, never drawn as "none saved";
  * a change of what is picked drops a plan laid for the launch, and a plan for another cell stays; the cell its Start made empties the
    places and the shelf starts again, and the builder's key names nothing more;
  * a press that moves: up or down it carries the card — up, the rail stands over the shelf; its copy under the pointer, the rail lit — and
    let go over the rail it is put;
    sideways a mouse drags the shelf and a finger is the browser's own scroll; the click that ends a carry or a drag is no press; a carry the
    browser takes over leaves nothing behind;
  * the shelf's ends: an end with cards out of sight is said; where it was swiped to survives a drawing of the same step.

The module is loaded FOR REAL; i18n (the English words) is a stand-in, and the document is one.

Run: python3 scripts/test_js_machine_build.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, probe_args  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r'''
import "./_js_globals.mjs";
const en = (await import("../static/js/i18n/en.js")).default;
globalThis.__stubReturns = { "i18n.t": (key, vars = {}) => String(en[key] ?? `?${key}`).replace(/\{(\w+)\}/g, (_, n) => (vars[n] === undefined ? `{${n}}` : vars[n])) };
const B = await import("../static/js/machine-build.js");
const P = await import("../static/js/machine-plan.js");
const { RunnerOffer } = await import("../static/js/runner-offer.js");
const out = {};
// The page's timers are the harness's and do not keep node alive: a wait is node's own.
const pause = (await import("node:timers/promises")).setTimeout;

// The registry as the board's builder tells it, and a stand-in for the rule a runner takes a file by (llama-edit.js runnerAvailability is
// pinned on its own): a GGUF to the GGUF runners, llama.cpp refusing PQ2_0, a folder to vLLM.
const ROWS = [
  { id: "llama-server", icon: "🦙", labelKey: "runnerLlama", artifacts: ["gguf"] },
  { id: "vllm", icon: "⚡", labelKey: "runnerVllm", artifacts: ["safetensors"] },
  { id: "strata", labelKey: "runnerStrata", artifacts: ["gguf"] },
  { id: "voice-clone", labelKey: "runnerWhisper", artifacts: ["*"], sharedPicker: "ignored" },
  { id: "ollama", labelKey: "runnerWhisper", artifacts: ["*"], editorTab: false },
  { id: "whisper", labelKey: "runnerWhisper", artifacts: ["whisper-size"] },
];
const takes = (row, file) => {
  const kind = String(file).endsWith(".gguf") ? "gguf" : "safetensors";
  if (row.id === "llama-server" && /PQ2_0/.test(file)) return { ok: false, reasonKey: "llamaErrUnsupportedQuantHint" };
  return (row.artifacts || []).some((a) => a === "*" || a === kind) ? { ok: true } : { ok: false, reasonKey: "runnerNeedsGguf" };
};
const runners = { rows: ROWS, takes };
const Q4 = "Zeta-GGUF/unsloth/Q4_K_M/zeta-Q4_K_M.gguf";
const Q8 = "Zeta-GGUF/unsloth/Q8_0/zeta-Q8_0.gguf";
const PQ = "Zeta-GGUF/unsloth/PQ2_0/zeta-PQ2_0.gguf";
// The model's cells by their names (cellId): stopped, so none holds a port. The first one's config still names a PORT, as a config saved
// before 2026-11-07 may: a port is no setting another launch takes. A row that names no cell is none of them.
const LINE = {
  name: "Zeta-GGUF", files: [Q4, Q8, PQ], sizes: [17.6, 30.24, 0],
  launches: [
    { cellId: "c22011", port: null, slotConfig: { RUNNER: "llama-server", MODEL_FILE: Q8, LLAMA_MODELS_DIR: "/m", MMPROJ_FILE: "mm.gguf", MODEL_NAME: "zeta", ALIAS: "z", PORT: "22011",
                                 CTX_SIZE: "65536", PARALLEL: "2", TEMPERATURE: "0.6", DEVICE: "CUDA0", N_GPU_LAYERS: "99", MAIN_GPU: "0", SPLIT_MODE: "row", ENV: "X=1" } },
    { cellId: "c22012", port: null, slotConfig: { RUNNER: "vllm", CTX_SIZE: "8192" } },
    { cellId: "c3f9a02b1", port: null, slotConfig: { CTX_SIZE: "4096" } },
    { port: 22014, slotConfig: { RUNNER: "llama-server", CTX_SIZE: "2048" } },
  ],
};
const CELLS = new Map([["c22011", { quant: "Q8_0" }]]);

// An element of the page as far as the builder touches it: its classes, its data, what it sits in.
const element = (dataset = {}, inside = {}) => {
  const el = { classes: new Set(), dataset, attrs: {}, style: {}, removed: false };
  el.classList = { add: (c) => el.classes.add(c), remove: (c) => el.classes.delete(c), toggle: (c, on) => (on ? el.classes.add(c) : el.classes.delete(c)), contains: (c) => el.classes.has(c) };
  el.closest = (sel) => (inside[sel] === "self" ? el : inside[sel] || null);
  el.remove = () => { el.removed = true; };
  el.getAttribute = (a) => el.attrs[a] ?? null;
  el.setAttribute = (a, v) => { el.attrs[a] = String(v); };
  el.removeAttribute = (a) => { delete el.attrs[a]; };
  return el;
};

// The page around a builder: a document that keeps its listeners, an element under the pointer, the panel, the rail and the shelf, a plan,
// a log. Every scenario below has a page of its own, so that what one does cannot make another pass or fail.
let answer = { presets: { "llama-server": { cool: { TEMPERATURE: 0.2, CACHE_PROMPT: true, TOP_K: 40 } } }, warnings: { "Zeta-GGUF": { strata: true } }, unread: 2 };
const page = ({ ask = null } = {}) => {
  const listeners = {};
  const log = [];
  const plan = new P.MachinePlan();
  const at = { under: null, asked: 0 };
  const panel = element();
  const rail = element({}, { "[data-build-rail]": "self" });
  const shelf = element();
  const scrolled = [];
  const track = element({}, { "[data-build-shelf]": shelf, "[data-build-track]": "self" });
  Object.assign(track, { scrollLeft: 0, clientWidth: 400, scrollWidth: 900, matches: (sel) => sel === "[data-build-track]", scrollBy: (o) => scrolled.push(o) });
  shelf.querySelector = (sel) => (sel === "[data-build-track]" ? track : null);
  const ghosts = [];
  const doc = {
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    querySelector: (sel) => (sel === '[data-t="machine-build"]' ? panel : sel === "[data-build-rail]" ? rail : sel === "[data-build-track]" ? track : null),
    elementFromPoint: () => at.under,
    body: { appendChild: (el) => ghosts.push(el) },
  };
  const b = new B.MachineBuild();
  b.bind(doc, { ask: ask || (async () => { at.asked += 1; if (answer instanceof Error) throw answer; return answer; }),
                choose: (key) => log.push(["choose", key]), redraw: () => log.push(["redraw"]), plan });
  const fire = (type, e) => (listeners[type] || []).forEach((fn) => fn(e));
  const draw = (line = LINE, extra = {}) => b.html(line, "box", { cells: CELLS, runners, ...extra });
  // A card of the shelf: a press on it, or a press that moves.
  const card = (kind, key, { dim = false } = {}) => {
    const el = element({ buildCard: kind, buildKey: key }, { "[data-build-card]": "self", "[data-build-track]": track });
    if (dim) el.attrs["aria-disabled"] = "true";
    el.getBoundingClientRect = () => ({ left: 90, top: 80, width: 150, height: 44 });
    el.cloneNode = () => { const copy = element({ buildCard: kind, buildKey: key }); copy.attrs["data-t"] = "machine-build-card"; return copy; };
    return el;
  };
  const step = (kind) => element({ buildStep: kind }, { "[data-build-step]": "self" });
  // A place of the launch: inside the strip once the launch is whole; its ✕.
  const slot = (kind, { strip = false } = {}) => element({ buildSlot: kind }, { "[data-build-slot]": "self", "[data-machine-pick]": strip ? rail : null });
  const x = (kind) => element({ buildEmpty: kind }, { "[data-build-empty]": "self" });
  const click = (target) => fire("click", { target });
  // A launch made whole by presses, as the operator would: the sets read, the engine, the quant.
  const whole = async () => { await b.readOnce(); draw(); click(card("engine", "llama-server")); draw(); click(card("quant", Q4)); draw(); log.length = 0; };
  return { b, log, plan, at, panel, rail, shelf, track, scrolled, ghosts, listeners, doc, fire, draw, whole, card, step, slot, x, click };
};
const cardsOf = (html, kind) => [...html.matchAll(new RegExp(`data-build-card="${kind}" data-build-key="([^"]*)"[^>]*data-t-state="([a-z]+)"(?: title="([^"]*)")?`, "g"))].map((m) => [m[1], m[2], m[3] || ""]);
const words = (html, id) => [...html.matchAll(new RegExp(`data-t="machine-build-none" data-t-id="${id}(?:-\\d+)?">([^<]*)<`, "g"))].map((m) => m[1]);
// A place's step: its kind, its number, whether its cards are shown, whether it is a button of its own, its hover.
const steps = (html) => [...html.matchAll(/<button type="button" class="machine-build-step" role="tab" aria-selected="(true|false)" data-build-step="([a-z]+)"( data-machine-own)? data-t="machine-build-step" data-t-id="[a-z]+" title="([^"]*)"><i class="machine-build-step-mark" aria-hidden="true">([^<]*)<\/i>/g)]
  .map((m) => [m[2], m[5], m[1] === "true", !!m[3], m[4]]);
const shown = (html) => [...html.matchAll(/aria-selected="true" data-build-step="([a-z]+)"/g)].map((m) => m[1]);
const unescape = (s) => String(s).replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
// A place: its kind, full or empty, what stands there, whether it is the step shown, the kind its ✕ empties.
const slots = (html) => [...html.matchAll(/<span class="machine-build-slot is-[a-z]+( is-full)?( is-shown)?" data-build-slot="([a-z]+)"[^>]*data-t-state="([a-z]+)">[\s\S]*?<strong>([^<]*)<\/strong><\/span><\/button>(<button[^>]*data-build-empty="([a-z]+)"[^>]*>)?/g)]
  .map((m) => [m[3], m[4], unescape(m[5]), !!m[2], m[7] || ""]);
// The rail's end while the launch is not whole: its name, its hover, what it holds after the name.
const end = (html) => (html.match(/<span class="machine-build-end" title="([^"]*)"><strong class="machine-build-title">([^<]*)<\/strong>([\s\S]*?)<\/span><\/div>/) || []).slice(1);
const entering = (html) => /class="machine-build-track is-entering"/.test(html);

// Nothing told, nothing drawn; nothing picked, said; the first drawing of a model: the steps, the engines' shelf, the rail; the sets read once.
{
  const A = page();
  out.untold = A.b.html(LINE, "box", { cells: CELLS });
  const none = A.b.html(null, "box", { runners });
  out.noModel = { state: /data-t="machine-build" data-t-state="none"/.test(none), words: words(none, "model"), steps: /machine-build-step/.test(none),
                  title: (none.match(/<strong class="machine-build-title">([^<]*)<\/strong>/) || [])[1] || null };
  A.b.bind(A.doc, { redraw: () => A.log.push(["second bind"]) });
  out.binds = (A.listeners.click || []).length;
  const html = A.draw();
  out.fresh = { steps: steps(html), shown: shown(html), engines: cardsOf(html, "engine"), quantCards: cardsOf(html, "quant").length, paramCards: cardsOf(html, "params").length,
                state: (html.match(/data-t="machine-build" data-t-id="[^"]*" data-t-state="([a-z]+)"/) || [])[1], slots: slots(html), rail: (html.match(/<div class="machine-build-rail" data-build-rail data-t="([a-z-]+)">/) || [])[1] || null,
                needs: /data-t="machine-build-needs"/.test(html), strip: /data-t="machine-build-strip"/.test(html), port: /machine-build-port/.test(html), entering: entering(html),
                order: [...html.matchAll(/data-t="machine-build-(steps|shelf|slots|needs)"|class="machine-build-(steps|hint|head)"/g)].map((m) => m[1] || m[2]),
                end: end(html), endFresh: end(A.draw(LINE, { fresh: '<button type="button" class="ui-btn" data-machine-model-new="">New cell from this model</button>' })),
                tablist: /<div class="machine-build-places" role="tablist" aria-label="Steps of the launch">/.test(html), hint: /Drag a tile/.test(html) };
  out.again = { entering: entering(A.draw()) };
  await A.b.readOnce();
  await A.b.readOnce();
  out.readOnce = { asked: A.at.asked, read: A.b.read, redraws: A.log.filter((l) => l[0] === "redraw").length };
}
// The steps pressed: the quants before an engine, the settings before an engine, a place of the launch being built shows its step.
{
  const S = page();
  S.draw();
  S.log.length = 0;
  S.click(S.step("quant"));
  let html = S.draw();
  out.quantStep = { shown: shown(html), quants: cardsOf(html, "quant"), engines: cardsOf(html, "engine").length, entering: entering(html), log: S.log.splice(0),
                    quantWords: [...html.matchAll(/data-build-card="quant"[\s\S]*?<strong>([^<]*)<\/strong>(?:<small>([^<]*)<\/small>)?/g)].map((m) => [m[1], m[2] || ""]) };
  out.sameStep = { pressed: S.b.show("quant"), log: S.log.splice(0) };
  S.click(S.step("params"));
  html = S.draw();
  out.paramsStep = { shown: shown(html), words: words(html, "params"), cards: cardsOf(html, "params").length };
  S.log.length = 0;
  S.click(S.slot("engine"));
  out.slotFrame = { step: S.b.step, log: S.log.splice(0) };
  S.click(S.step("engine"));
  out.slotShows = { step: S.b.step, picked: { ...S.b.picked }, log: S.log.splice(0) };
  out.unknownStep = S.b.show("nope");
}
// The main way: an engine, the shelf on to the quants, a dim card refused, the quant — whole, the shelf on to the settings; a set; another engine.
{
  const C = page();
  await C.b.readOnce();
  C.draw();
  C.log.length = 0;
  C.click(C.card("engine", "llama-server"));
  let html = C.draw();
  out.engine = { picked: { ...C.b.picked }, launch: C.b.launch(), server: C.b.server(), step: C.b.step, log: C.log.splice(0), shown: shown(html), quants: cardsOf(html, "quant"), steps: steps(html),
                 slots: slots(html), entering: entering(html) };
  out.dimPress = [C.b.press("quant", PQ), C.b.picked.quant];
  C.click(C.step("engine"));
  html = C.draw();
  out.engineAgain = { unwanted: cardsOf(html, "engine").find(([key]) => key === "strata"), llama: cardsOf(html, "engine").find(([key]) => key === "llama-server")?.[1],
                      tick: /data-build-key="llama-server"[^>]*>[\s\S]*?machine-build-tick/.test(html.split("data-build-key=\"strata\"")[0]) };
  C.log.length = 0;
  C.click(C.card("quant", Q4));
  const choice = '<div class="machine-pick" data-machine-panel="new" data-machine-own data-t="machine-pick" data-t-id="new"></div>';
  html = C.draw(LINE, { choice, on: true });
  out.whole = { step: C.b.step, log: C.log.splice(0), launch: C.b.launch(), server: C.b.server(), key: B.MachineBuild.KEY,
                owns: [C.b.owns("new"), C.b.owns("c22011"), C.b.owns(""), C.b.owns("22077")],
                strip: (html.match(/<div class="machine-build-rail is-whole( is-on)?" data-build-rail data-machine-pick="([^"]*)" data-t="machine-build-strip" data-t-id="([^"]*)"/) || []).slice(1),
                portButton: (html.match(/<button type="button" class="machine-build-port is-on" aria-pressed="true" data-machine-pick="new"[^>]*>([^<]*)</) || [])[1] || null,
                // No number of a port anywhere on the builder: the launch has none, and the cells on its shelf none either.
                ports: html.match(/:\d{4,5}\b|\b22\d{3}\b/g) || [],
                cellSetName: (html.match(/data-build-key="cell:c22011"[\s\S]*?<strong>([^<]*)<\/strong>/) || [])[1] || null,
                take: (html.match(/<span class="machine-build-take">[\s\S]*?<strong><span aria-hidden="true">↑ <\/span>([^<]*)<\/strong><small>([^<]*)<\/small>/) || []).slice(1),
                slots: slots(html), ownX: (html.match(/data-build-empty="[a-z]+" data-machine-own/g) || []).length, slotButtons: (html.match(/<button type="button" class="machine-build-slot/g) || []).length,
                choiceAfter: html.indexOf(choice) > html.indexOf("machine-build-strip"), needs: /data-t="machine-build-needs"/.test(html), state: /data-t-state="whole"/.test(html),
                shown: shown(html), steps: steps(html) };
  out.sets = { cards: cardsOf(html, "params"), words: words(html, "params") };
  C.click(C.card("params", "cell:c22011"));
  out.cellSet = { fields: C.b.launch().fields, step: C.b.step, log: C.log.splice(0) };
  C.click(C.card("params", "set:cool"));
  out.savedSet = C.b.launch().fields;
  C.log.length = 0;
  C.click(C.slot("engine", { strip: true }));
  out.stripFrame = { picked: { ...C.b.picked }, step: C.b.step, log: C.log.splice(0) };
  C.click(C.step("engine"));
  out.stripSlot = { picked: { ...C.b.picked }, step: C.b.step, log: C.log.splice(0) };
  C.click(C.step("params"));
  C.log.length = 0;
  C.click(C.x("params"));
  out.stripX = { picked: { ...C.b.picked }, server: C.b.server(), step: C.b.step, log: C.log.splice(0) };
  C.click(C.step("engine"));
  C.click(C.card("engine", "strata"));
  html = C.draw();
  out.otherEngine = { picked: { ...C.b.picked }, server: C.b.server(), step: C.b.step, log: C.log.splice(0) };
}
// The maker's set: offered first for an engine that writes sampling flags, its numbers the config's words; none for another engine, none
// for a model the table does not name. The settings' shelf is shown by its step, as the operator would press it.
{
  const M = page({ ask: async () => ({ ...answer, makers: { "Zeta-GGUF": { TEMPERATURE: "1.0", TOP_K: "64" }, "Other-GGUF": { TOP_P: "0.9" } } }) });
  const llama = { rows: ROWS.map((r) => (r.id === "llama-server" ? { ...r, llamaConfig: true } : r)), takes };
  const drawn = (line = LINE) => M.draw(line, { runners: llama });
  const paramsShelf = (line = LINE) => { drawn(line); M.click(M.step("params")); return drawn(line); };
  await M.b.readOnce();
  drawn();
  M.click(M.card("engine", "llama-server"));
  let html = paramsShelf();
  const offered = cardsOf(html, "params").map(([key]) => key);
  const words = (html.match(/data-build-key="maker"[\s\S]*?<strong>([^<]*)<\/strong><small>([^<]*)<\/small>/) || []).slice(1);
  M.click(M.card("quant", Q4));
  drawn();
  M.click(M.card("params", "maker"));
  drawn();
  out.maker = { offered, words, picked: M.b.picked.params, fields: M.b.launch()?.fields };
  // Another model picked empties the places (follow): its engine is picked again, and its shelf of settings read.
  const other = { ...LINE, name: "Nameless-GGUF" };
  drawn(other);
  M.click(M.card("engine", "llama-server"));
  out.makerOtherModel = cardsOf(paramsShelf(other), "params").map(([key]) => key);
  const plain = page({ ask: async () => ({ ...answer, makers: { "Zeta-GGUF": { TEMPERATURE: "1.0" } } }) });
  await plain.b.readOnce();
  plain.draw();
  plain.click(plain.card("engine", "llama-server"));
  plain.draw();
  plain.click(plain.step("params"));
  out.makerNoFlags = cardsOf(plain.draw(), "params").map(([key]) => key);
}
// A plan laid for the launch goes when the launch changes; one for another cell stays.
{
  const D = page();
  await D.whole();
  D.plan.set("new", { how: "plan", fields: { DEVICE: "CUDA1" } });
  D.click(D.card("params", "set:cool"));
  out.planGoes = { on: D.plan.on, params: D.b.picked.params };
  D.plan.set("c22011", { how: "plan", fields: { DEVICE: "CUDA1" } });
  D.click(D.card("params", "cell:c22011"));
  out.otherPlanStays = { on: D.plan.on, cellId: D.plan.cellId, params: D.b.picked.params };
}
// While the launch's start is being made, nothing changes: neither another card, pressed or carried onto the rail, nor a ✕.
{
  const E = page();
  await E.whole();
  E.plan.set("new", { how: "plan", fields: { DEVICE: "CUDA1" } });
  E.plan.begin(null);
  E.click(E.card("quant", Q8));
  E.click(E.card("quant", Q4));
  E.click(E.x("engine"));
  E.at.under = E.rail;
  E.fire("pointerdown", { button: 0, pointerType: "mouse", clientX: 100, clientY: 100, target: E.card("quant", Q8) });
  E.fire("pointermove", { buttons: 1, clientX: 100, clientY: 180, preventDefault() {} });
  E.fire("pointerup", { clientX: 100, clientY: 180 });
  out.busy = { quant: E.b.picked.quant, engine: E.b.picked.engine, whole: !!E.b.server(), on: E.plan.on, busy: E.plan.busy, log: E.log.splice(0) };
}
// A card pressed again empties its place, and so does its ✕; a place pressed while the launch is being built shows its step and empties nothing.
{
  const F = page();
  await F.whole();
  F.click(F.card("quant", Q4));
  const html = F.draw();
  out.emptied = { picked: { ...F.b.picked }, owns: F.b.owns("new"), step: F.b.step, launch: F.b.launch(), server: F.b.server(), strip: /machine-build-strip/.test(html),
                  needs: /data-t="machine-build-needs"/.test(html), log: F.log.splice(0) };
  F.click(F.step("engine"));
  out.slotKeeps = { picked: { ...F.b.picked }, step: F.b.step, log: F.log.splice(0) };
  F.click(F.x("engine"));
  out.xEmpties = { picked: { ...F.b.picked }, step: F.b.step, log: F.log.splice(0) };
}
// Carried: past the slop a move down takes the card — its copy under the pointer, the rail lit — and over the rail it is put; the click that
// ends it is no press. Let go off the rail, nothing. A dim card is not taken. Sideways a mouse drags the shelf; a finger is the browser's.
{
  const G = page();
  await G.b.readOnce();
  G.draw();
  G.log.length = 0;
  const llama = G.card("engine", "llama-server");
  G.fire("pointerdown", { button: 0, pointerType: "mouse", clientX: 100, clientY: 100, target: llama });
  G.fire("pointermove", { buttons: 1, clientX: 102, clientY: 101 });
  out.carrySlop = { carrying: G.panel.classes.has("is-carrying"), ghosts: G.ghosts.length, busy: G.b.busy };
  G.at.under = G.rail;
  // Up: the rail stands over the shelf (the owner's choice Б, 2026-11-08).
  G.fire("pointermove", { buttons: 1, clientX: 108, clientY: 30, preventDefault() {} });
  const ghost = G.ghosts[0] || null;
  out.carryOver = { carrying: G.panel.classes.has("is-carrying"), kind: G.panel.dataset.carrying, rail: [...G.rail.classes], lifted: [...llama.classes], busy: G.b.busy,
                    ghost: ghost && { cls: [...ghost.classes], t: ghost.attrs["data-t"] ?? null, hidden: ghost.attrs["aria-hidden"], at: ghost.style.transform, width: ghost.style.width } };
  G.fire("pointerup", { clientX: 108, clientY: 30 });
  G.click(llama);
  out.carried = { picked: G.b.picked.engine, step: G.b.step, carrying: G.panel.classes.has("is-carrying"), kind: G.panel.dataset.carrying ?? null, rail: [...G.rail.classes],
                  lifted: [...llama.classes], ghostGone: !!ghost?.removed, busy: G.b.busy, log: G.log.splice(0) };
  await pause(5);
  // The card that stands in its place, carried onto the rail again: nothing changes, and the plan of the launch is not dropped for it.
  G.at.under = G.rail;
  G.fire("pointerdown", { button: 0, pointerType: "mouse", clientX: 100, clientY: 100, target: llama });
  G.fire("pointermove", { buttons: 1, clientX: 100, clientY: 180, preventDefault() {} });
  G.fire("pointerup", { clientX: 100, clientY: 180 });
  out.sameAgain = { picked: G.b.picked.engine, log: G.log.splice(0) };
  await pause(5);
  G.draw();
  G.at.under = null;
  G.fire("pointerdown", { button: 0, pointerType: "mouse", clientX: 100, clientY: 100, target: G.card("quant", Q8) });
  G.fire("pointermove", { buttons: 1, clientX: 110, clientY: 300, preventDefault() {} });
  G.fire("pointerup", { clientX: 110, clientY: 300 });
  out.offRail = { quant: G.b.picked.quant, log: G.log.splice(0) };
  await pause(5);
  G.fire("pointerdown", { button: 0, pointerType: "mouse", clientX: 100, clientY: 100, target: G.card("quant", PQ, { dim: true }) });
  G.at.under = G.rail;
  G.fire("pointermove", { buttons: 1, clientX: 100, clientY: 200, preventDefault() {} });
  G.fire("pointerup", { clientX: 100, clientY: 200 });
  out.dimCarry = { quant: G.b.picked.quant, carrying: G.panel.classes.has("is-carrying"), ghosts: G.ghosts.length, log: G.log.splice(0) };
  // A mouse drags the shelf sideways: the track follows, no card is taken, and the click at its end is no press.
  G.track.scrollLeft = 120;
  const q4 = G.card("quant", Q4);
  G.fire("pointerdown", { button: 0, pointerType: "mouse", clientX: 300, clientY: 100, target: q4 });
  G.fire("pointermove", { buttons: 1, clientX: 240, clientY: 104, preventDefault() {} });
  out.dragShelf = { left: G.track.scrollLeft, busy: G.b.busy, carrying: G.panel.classes.has("is-carrying"), ghosts: G.ghosts.length };
  G.fire("pointerup", { clientX: 240, clientY: 104 });
  G.click(q4);
  out.dragShelfEnd = { quant: G.b.picked.quant, busy: G.b.busy, log: G.log.splice(0) };
  await pause(5);
  // A finger that swipes sideways is the browser's scroll: the builder lets go, and the press after it is a press.
  G.fire("pointerdown", { button: 0, pointerType: "touch", clientX: 300, clientY: 100, target: q4 });
  G.fire("pointermove", { buttons: 1, clientX: 240, clientY: 104, preventDefault() {} });
  out.fingerSwipe = { left: G.track.scrollLeft, carry: G.b.carry, busy: G.b.busy, ghosts: G.ghosts.length };
  G.click(q4);
  out.fingerPress = { quant: G.b.picked.quant, step: G.b.step };
}
// A carry the browser takes over (pointercancel) leaves nothing behind, and the next press is a press.
{
  const K = page();
  K.draw();
  const llama = K.card("engine", "llama-server");
  K.at.under = K.rail;
  K.fire("pointerdown", { button: 0, pointerType: "touch", clientX: 100, clientY: 100, target: llama });
  K.fire("pointermove", { buttons: 1, clientX: 101, clientY: 160, preventDefault() {} });
  const during = { carrying: K.panel.classes.has("is-carrying"), ghosts: K.ghosts.length };
  K.fire("pointercancel", {});
  K.click(K.step("quant"));
  out.cancelled = { during, carrying: K.panel.classes.has("is-carrying"), rail: [...K.rail.classes], lifted: [...llama.classes], ghostGone: !!K.ghosts[0]?.removed,
                    carry: K.b.carry, step: K.b.step, picked: K.b.picked.engine };
}
// The shelf: an arrow moves it most of its width; where it was swiped to survives a drawing of the same step, not another step's.
{
  const W = page();
  W.draw();
  W.click(element({ buildScroll: "1" }, { "[data-build-scroll]": "self", "[data-build-shelf]": W.shelf }));
  W.click(element({ buildScroll: "-1" }, { "[data-build-scroll]": "self", "[data-build-shelf]": W.shelf }));
  out.arrows = W.scrolled.splice(0);
  out.arrowNoShelf = W.b.slide(element({ buildScroll: "1" }, {}));
  W.track.scrollLeft = 260;
  W.fire("scroll", { target: W.track });
  out.scrolledEnds = { kept: { ...W.b.shelf }, cls: [...W.shelf.classes] };
  W.draw();
  W.track.scrollLeft = 0;
  out.mounted = { ends: W.b.mounted(W.doc), left: W.track.scrollLeft, cls: [...W.shelf.classes] };
  W.click(W.step("quant"));
  W.draw();
  W.track.scrollLeft = 0;
  out.otherStep = { ends: W.b.mounted(W.doc), left: W.track.scrollLeft };
  W.click(W.step("engine"));
  W.track.scrollLeft = 150;
  W.fire("scroll", { target: W.track });
  W.b.html({ name: "Alpha", files: [], sizes: [], launches: [] }, "box", { cells: CELLS, runners });
  W.track.scrollLeft = 0;
  W.b.mounted(W.doc);
  out.otherModelShelf = { left: W.track.scrollLeft, kept: { ...W.b.shelf } };
  out.notTrack = (() => { const was = { ...W.b.shelf }; W.fire("scroll", { target: { matches: () => false, scrollLeft: 999 } }); return JSON.stringify(W.b.shelf) === JSON.stringify(was); })();
  out.noTrack = new B.MachineBuild().mounted({ querySelector: () => null });
}
// The cell the launch's Start made empties the places and the shelf starts again; another model empties what was picked.
{
  const H = page();
  await H.whole();
  H.b.made();
  out.made = { picked: { ...H.b.picked }, launch: H.b.launch(), server: H.b.server(), owns: H.b.owns("new"), model: H.b.model, host: H.b.host, step: H.b.step };
  H.click(H.card("engine", "llama-server"));
  const alpha = { name: "Alpha", files: [], sizes: [], launches: [] };
  H.b.html(alpha, "box", { cells: CELLS, runners });
  out.otherModel = { picked: { ...H.b.picked }, model: H.b.model, step: H.b.step };
  const engineWords = words(H.b.html(alpha, "box", { cells: CELLS, runners }), "engine");
  H.b.show("quant");
  const quantWords = words(H.b.html(alpha, "box", { cells: CELLS, runners }), "quant");
  out.noFiles = { engines: engineWords, quants: quantWords };
}
// A file straight in the library: its card is named by the file, which is the model's name — the launch is not called "x · x".
{
  const flat = "stand-small-8B-Q4_K_M.gguf";
  const L = page();
  await L.b.readOnce();
  const line = { name: flat, files: [flat], sizes: [5], launches: [] };
  L.draw(line);
  L.click(L.card("engine", "llama-server"));
  L.draw(line);
  L.click(L.card("quant", flat));
  out.flatName = L.b.launch()?.name ?? null;
}
// The saved sets: being read, not read, read with nothing for the engine — each said, and the cells' settings still offered.
{
  const strataWords = async (read) => {
    const R = page({ ask: read === "failed" ? async () => { throw new Error("down"); } : async () => answer });
    if (read !== "") await R.b.readOnce();
    R.draw();
    R.click(R.card("engine", "strata"));
    R.click(R.step("params"));
    return words(R.draw(), "params");
  };
  out.strataReading = await strataWords("");
  out.strataFailed = await strataWords("failed");
  out.noSets = await strataWords("read");
  const f = page({ ask: async () => { throw new Error("down"); } });
  await f.b.readOnce();
  f.draw();
  f.click(f.card("engine", "llama-server"));
  f.click(f.step("params"));
  const h = f.draw();
  out.failed = { read: f.b.read, words: words(h, "params"), cards: cardsOf(h, "params").map(([k]) => k) };
}
const nb = new B.MachineBuild();
out.nextStep = [[{}, ""], [{ engine: "x" }, ""], [{ quant: "q" }, ""], [{ engine: "x", quant: "q" }, ""], [{ engine: "x", quant: "q", params: "s" }, ""]].map(([picked]) => {
  nb.picked = { engine: "", quant: "", params: "", ...picked };
  return nb.nextStep();
});
out.gesture = [[0, 10, true], [10, 10, true], [-10, -10, false], [20, -5, true], [20, 5, false], [-30, 40, false], [0, -20, false], [-40, 3, true]].map(([dx, dy, mouse]) => B.MachineBuild.gesture(dx, dy, mouse));
out.ends = [{ scrollLeft: 0, clientWidth: 300, scrollWidth: 300 }, { scrollLeft: 0, clientWidth: 300, scrollWidth: 500 }, { scrollLeft: 200, clientWidth: 300, scrollWidth: 500 },
            { scrollLeft: 100, clientWidth: 300, scrollWidth: 500 }, { scrollLeft: 1, clientWidth: 300, scrollWidth: 301 }, {}].map((t) => B.MachineBuild.ends(t));
out.offered = [RunnerOffer.offered(ROWS[0]), RunnerOffer.offered(ROWS[3]), RunnerOffer.offered(ROWS[4]), RunnerOffer.offered(null), RunnerOffer.offered({ id: "x" })];
out.fieldsOfSet = B.MachineBuild.fieldsOfSet({ TEMPERATURE: 0.2, CACHE_PROMPT: true, CONTEXT_SHIFT: false, TOP_K: 40 });
out.setting = ["CTX_SIZE", "TEMPERATURE", "RUNNER", "MODEL_FILE", "MMPROJ_FILE", "DEVICE", "ENV", "FIT", "MODEL_NAME", "MAIN_GPU", "SPLIT_MODE"].map((k) => [k, B.MachineBuild.setting(k)]);
console.log(JSON.stringify(out));
'''

Q4 = "Zeta-GGUF/unsloth/Q4_K_M/zeta-Q4_K_M.gguf"


def section_drawing(got):
    print("что нарисовано:")
    check(got["untold"] == "", "negative: движки не сказаны — сборки нет: иначе она сказала бы, что модель не запускает ни один движок")
    check(got["noModel"] == {"state": True, "words": ["Pick a model in the list to build a launch of it."], "steps": False, "title": "Build a launch"},
          "модель не выбрана — имя сборки и что сделать, одной строкой; negative: ни шагов, ни полки")
    check(got["binds"] == 1, "negative: второй bind ничего не добавляет")
    f = got["fresh"]
    tip = "Show its tiles in the row below"
    check(f["steps"] == [["engine", "1", True, True, tip], ["quant", "2", False, True, tip], ["params", "3", False, True, tip]] and f["shown"] == ["engine"] and f["tablist"],
          f"вариант Б (владелец, 2026-11-08): места рельса — шаги по порядку, с номерами, показан первый; каждое — вкладка и своя кнопка, "
          f"подсказка зовёт к полке ниже (получено {f['steps']}, {f['shown']})")
    check([k for k, _, _ in f["engines"]] == ["llama-server", "strata"],
          f"движки — те, что мастер предлагает и что берут файл модели; negative: свой движок, клон голоса, vLLM и whisper без своего файла не предложены (получено {f['engines']})")
    check(f["quantCards"] == 0 and f["paramCards"] == 0, "negative: на полке карточки одного шага — квантов и настроек там нет")
    check(f["order"] == ["slots", "shelf"] and f["rail"] == "machine-build-slots" and f["state"] == "building" and not f["needs"] and not f["strip"] and not f["port"]
          and not f["hint"],
          f"два ряда: рельс, под ним полка; запуска ещё нет — нет полосы и её кнопки выбора; negative: ни ряда шагов, ни подсказки, ни строки "
          f"«чего не хватает» (получено {f['order']})")
    check(f["end"] == ["A launch needs an engine and a quant.", "Build a launch", ""]
          and f["endFresh"] == ["A launch needs an engine and a quant.", "Build a launch", '<button type="button" class="ui-btn" data-machine-model-new="">New cell from this model</button>'],
          f"конец рельса: имя сборки, что нужно для старта — в подсказке, и кнопка мастера новой ячейки, какую даёт страница (получено {f['end']}, {f['endFresh']})")
    check(f["slots"] == [["engine", "empty", "No engine yet", True, ""], ["quant", "empty", "No quant yet", False, ""], ["params", "empty", "The engine's own defaults", False, ""]],
          f"три места пусты и названы словами, место показанного шага обведено; negative: ✕ на пустом месте нет (получено {f['slots']})")
    check(f["entering"] and got["again"]["entering"] is False, "карточки шага въезжают один раз; negative: перерисовка того же шага их не двигает")
    r = got["readOnce"]
    check(r == {"asked": 1, "read": "read", "redraws": 1}, f"наборы читаются один раз на страницу, после — перерисовка; negative: второй раз не спрашивает (получено {r})")


def section_steps(got):
    print("шаги:")
    q = got["quantStep"]
    check(q["shown"] == ["quant"] and q["engines"] == 0 and q["entering"] and q["log"] == [["redraw"]],
          "шаг нажат — полка на его карточках, они въезжают; negative: движков на полке больше нет")
    check(q["quants"] == [[Q4, "ok", ""], ["Zeta-GGUF/unsloth/Q8_0/zeta-Q8_0.gguf", "ok", ""], ["Zeta-GGUF/unsloth/PQ2_0/zeta-PQ2_0.gguf", "ok", ""]],
          "кванты все годны, пока движка нет")
    check(q["quantWords"] == [["Q4_K_M", "17.6 GB"], ["Q8_0", "30.2 GB"], ["PQ2_0", ""]],
          f"квант назван папкой, вес — с десятыми; negative: невзвешенный — без цифры, не «0 GB» (получено {q['quantWords']})")
    check(got["sameStep"] == {"pressed": False, "log": []}, "negative: шаг, который уже показан, — без перерисовки")
    p = got["paramsStep"]
    check(p["shown"] == ["params"] and p["cards"] == 0 and p["words"] == ["Pick an engine first: a set belongs to its engine.", "Reading the saved sets…"],
          f"настройки — после движка; наборы ещё читаются — так и сказано, а не «нет наборов» (получено {p['words']})")
    check(got["slotShows"] == {"step": "engine", "picked": {"engine": "", "quant": "", "params": ""}, "log": [["redraw"]]},
          f"место собираемого запуска нажато — полка на его шаге; negative: ничего не выбрано и не освобождено (получено {got['slotShows']})")
    check(got["slotFrame"] == {"step": "params", "log": []}, f"negative: рамка места мимо его кнопки — ничего (получено {got['slotFrame']})")
    check(got["unknownStep"] is False, "negative: шага, которого нет, не показать")


def section_picking(got):
    print("выбор:")
    e = got["engine"]
    check(e["picked"] == {"engine": "llama-server", "quant": "", "params": ""} and e["launch"] is None and e["server"] is None and e["log"] == [["redraw"]],
          "движок встал на место; negative: без кванта запуск не целый — карте нечего класть, на ней ничего не выбрано")
    check(e["step"] == "quant" and e["shown"] == ["quant"] and e["entering"], "полка сама перешла к следующему шагу — квантам, они въехали")
    check([st[1] for st in e["steps"]] == ["1", "2", "3"] and [st[2] for st in e["steps"]] == [False, True, False],
          f"номера шагов на местах остаются, показан шаг кванта (место занятой части красит её номер — правило CSS) (получено {e['steps']})")
    check(e["quants"][2] == ["Zeta-GGUF/unsloth/PQ2_0/zeta-PQ2_0.gguf", "dim", "Use a runtime that supports this GGUF. For PQ2_0/PTQ1_0, select PrismML."] and e["quants"][0][1] == "ok",
          "квант, который движок не запускает, тусклый и говорит почему — словами правила; negative: остальные годны")
    check(e["slots"][0] == ["engine", "full", "🦙 llama.cpp", False, "engine"] and e["slots"][1] == ["quant", "empty", "No quant yet", True, ""],
          f"место движка занято, у него ✕; место кванта — показанный шаг; negative: у пустого места кванта ✕ нет (получено {e['slots']})")
    ea = got["engineAgain"]
    check(ea["unwanted"] == ["strata", "ok", "Marked as not for this model"] and ea["llama"] == "on" and ea["tick"],
          "пометка владельца «не для этой модели» только предупреждает: карточка годна, слова на ней; карточка на месте — нажата и с галкой")
    check(got["dimPress"] == [False, ""], "negative: тусклый квант не ставится")
    w = got["whole"]
    check(w["key"] == "new" and w["log"] == [["choose", "new"], ["redraw"]],
          "движок и квант — запуск целый и выбран на карте под ключом сборки: ни имени ячейки, ни порта у него нет, пока Start её не создаст")
    check(w["step"] == "params" and w["shown"] == ["params"] and [s[1] for s in w["slots"]] == ["full", "full", "empty"],
          "полка перешла к настройкам: без них запуск целый, но набор взять можно; negative: место настроек пусто")
    check(w["launch"] == {"host": "box", "runner": "llama-server", "file": Q4, "name": "Zeta-GGUF · Q4_K_M", "sizeGb": 17.6, "fields": {}},
          f"запуск: машина, движок, файл, вес; настроек нет — настройки движка по умолчанию; negative: ни порта, ни имени ячейки (получено {w['launch']})")
    check(got["flatName"] == "stand-small-8B-Q4_K_M.gguf",
          f"defect-history (стенд, 2026-11-07): файл прямо в библиотеке — запуск зовётся именем модели, не «x · x» (получено {got['flatName']})")
    check(w["server"] == {"cellId": "new", "phase": "stopped", "virtual": True} and w["owns"] == [True, False, False, False],
          "для карты — ячейка, которая стоит, под ключом сборки, не ячейка машины; negative: имя другой ячейки, пустота и номер порта — не её")
    check(w["strip"] == [" is-on", "new", "new"] and w["portButton"] == "new cell" and w["state"] and w["take"] == ["Onto GPU or RAM", "drag it up, or press a place"],
          f"рельс стал полосой: берётся как ячейка (data-machine-pick — ключ сборки), выбран, у него ручка и кнопка выбора с клавиатуры, названная тем, что это: новая ячейка (получено {w['strip']}, {w['portButton']!r}, {w['take']})")
    check(w["ports"] == [], f"negative: ни одного номера порта на сборке — ни у запуска, ни у ячеек на полке настроек (получено {w['ports']})")
    check([s[3] for s in w["slots"]] == [False, False, True] and all(st[3] for st in w["steps"]) and w["slotButtons"] == 0 and w["ownX"] == 2
          and w["choiceAfter"] and not w["needs"],
          "в полосе места остаются шагами: их кнопки — свои (data-machine-own), как ✕, так что полосу они не выбирают и не тащат — её берут за ручку; "
          "под полосой — последняя строка карты")
    s = got["sets"]
    check([k for k, _, _ in s["cards"]] == ["set:cool", "cell:c22011", "cell:c3f9a02b1"],
          f"настройки движка: сохранённый набор и ячейки этой модели на нём, по их именам, ячейка без RUNNER — llama.cpp; negative: ячейка vLLM не предложена, "
          f"строка без имени ячейки — не ячейка (получено {s['cards']})")
    check(w["cellSetName"] == "Settings of c22011", f"карточка ячейки названа её именем (id), как его говорит её строка; negative: не портом (получено {w['cellSetName']!r})")
    check(s["words"] == ["Saved sets that could not be read, left out: 2."], "непрочитанные строки наборов названы числом, не пропущены молча")
    check(got["cellSet"]["fields"] == {"CTX_SIZE": "65536", "PARALLEL": "2", "TEMPERATURE": "0.6"} and got["cellSet"]["step"] == "params",
          f"настройки ячейки — без имени, файлов, места и движка; полка остаётся на настройках (получено {got['cellSet']['fields']})")
    check(got["savedSet"] == {"TEMPERATURE": "0.2", "CACHE_PROMPT": "1", "TOP_K": "40"}, "сохранённый набор — словами конфига: число строкой, переключатель — 1/0")
    check(got["stripSlot"] == {"picked": {"engine": "llama-server", "quant": Q4, "params": "set:cool"}, "step": "engine", "log": [["redraw"]]},
          "место внутри полосы нажато — полка на его шаге; negative: ничего не освобождено и полоса не выбрана заново")
    check(got["stripFrame"] == {"picked": {"engine": "llama-server", "quant": Q4, "params": "set:cool"}, "step": "params", "log": []},
          "negative: рамка места в полосе мимо его кнопки — ничего не освобождает и шаг не меняет")
    x = got["stripX"]
    check(x["picked"]["params"] == "" and x["picked"]["quant"] == Q4 and x["server"] == {"cellId": "new", "phase": "stopped", "virtual": True} and x["step"] == "params"
          and x["log"] == [["choose", "new"], ["redraw"]],
          "✕ в полосе освобождает своё место; запуск остаётся целым и выбранным под ключом сборки")
    o = got["otherEngine"]
    check(o["picked"]["params"] == "" and o["picked"]["engine"] == "strata" and o["server"] is not None and o["step"] == "params",
          "другой движок уносит набор прежнего; запуск остаётся целым")
    mk = got["maker"]
    check(mk["offered"] == ["maker", "set:cool", "cell:c22011", "cell:c3f9a02b1"], f"числа создателей модели — первый набор, перед сохранёнными и настройками ячеек (получено {mk['offered']})")
    check(mk["words"] == ["The makers&#39; numbers", "TEMPERATURE 1.0, TOP_K 64"], f"карточка называет каждое число своим полем (получено {mk['words']})")
    check(mk["picked"] == "maker" and mk["fields"] == {"TEMPERATURE": "1.0", "TOP_K": "64"}, "выбранная — её числа идут в запуск словами конфига, и только они")
    check(got["makerOtherModel"] == ["set:cool", "cell:c22011", "cell:c3f9a02b1"], "negative: модели, о которой таблица молчит, своего набора нет — его не придумывают")
    check(got["makerNoFlags"] == ["set:cool", "cell:c22011", "cell:c3f9a02b1"], "negative: движку без своих флагов выборки (нет llamaConfig) числа не предлагаются: они ничего бы не поменяли")
    check(got["planGoes"] == {"on": False, "params": "set:cool"}, "план, положенный для запуска, уходит, когда запуск меняется: он был для другой ячейки")
    check(got["otherPlanStays"] == {"on": True, "cellId": "c22011", "params": "cell:c22011"}, "negative: план другой ячейки остаётся")
    check(got["busy"] == {"quant": Q4, "engine": "llama-server", "whole": True, "on": True, "busy": True, "log": []},
          "пока запуск запускается, сборка не меняется — ни другим квантом, нажатым или перенесённым на рельс, ни снятием этого, ни ✕; "
          "defect-history: перенесённая карточка меняла запуск и снимала план, который старт ещё выполнял")
    m = got["emptied"]
    check(m["picked"]["quant"] == "" and m["owns"] is False and m["launch"] is None and m["server"] is None and not m["strip"] and not m["needs"] and m["step"] == "quant",
          "квант нажат ещё раз — место пусто, полосы нет, ключ сборки больше ничего не называет, полка на квантах")
    check(got["slotKeeps"] == {"picked": {"engine": "llama-server", "quant": "", "params": ""}, "step": "engine", "log": [["redraw"]]},
          "занятое место нажато, пока запуск собирается, — полка на его шаге; negative: место не освобождено (это делает ✕)")
    check(got["xEmpties"]["picked"] == {"engine": "", "quant": "", "params": ""} and got["xEmpties"]["step"] == "engine" and got["xEmpties"]["log"] == [["redraw"]],
          "✕ движка освобождает место; без движка нет и набора; полка на движках")


def section_carry(got):
    print("перенос карточки и полка:")
    check(got["carrySlop"] == {"carrying": False, "ghosts": 0, "busy": False}, "negative: сдвиг меньше порога — ещё нажатие")
    co = got["carryOver"]
    check(co["carrying"] and co["kind"] == "engine" and co["rail"] == ["is-over"] and co["lifted"] == ["is-lifted"] and co["busy"],
          "сдвиг по вертикали — карточка в руке: рельс подсвечен под указателем, карточка на полке отступила, доска не перерисует под рукой")
    check(co["ghost"] == {"cls": ["machine-build-ghost"], "t": None, "hidden": "true", "at": "translate(98px, 10px)", "width": "150px"},
          f"под указателем — копия карточки, там, где её взяли, без своего data-t и скрыта от чтения экрана (получено {co['ghost']})")
    c = got["carried"]
    check(c["picked"] == "llama-server" and c["step"] == "quant" and not c["carrying"] and c["kind"] is None and c["rail"] == [] and c["lifted"] == [] and c["ghostGone"] and not c["busy"]
          and c["log"] == [["redraw"]],
          "отпущена над рельсом — поставлена, полка на следующем шаге; копия и подсветка сняты; negative: клик в конце переноса не второе нажатие (иначе снял бы её)")
    check(got["sameAgain"] == {"picked": "llama-server", "log": []}, "negative: карточка, что уже стоит на месте, перенесена снова — ничего не меняется и не перерисовано")
    check(got["offRail"] == {"quant": "", "log": []}, "negative: отпущена не над рельсом — ничего")
    check(got["dimCarry"] == {"quant": "", "carrying": False, "ghosts": 3, "log": []}, "negative: тусклую не берут в руку — и новой копии нет (три — от трёх прежних переносов)")
    d = got["dragShelf"]
    check(d == {"left": 180, "busy": True, "carrying": False, "ghosts": 3}, f"мышью вбок — полка едет за указателем, карточка не взята, копии нет (получено {d})")
    check(got["dragShelfEnd"] == {"quant": "", "busy": False, "log": []}, "negative: клик в конце протяжки полки — не нажатие на карточку")
    fs = got["fingerSwipe"]
    check(fs == {"left": 180, "carry": None, "busy": False, "ghosts": 3}, f"пальцем вбок — прокрутка браузера: сборка отпускает нажатие и полку не двигает (получено {fs})")
    check(got["fingerPress"]["quant"] == Q4, "negative: после свайпа пальцем следующее нажатие — нажатие")
    k = got["cancelled"]
    check(k["during"] == {"carrying": True, "ghosts": 1} and not k["carrying"] and k["rail"] == [] and k["lifted"] == [] and k["ghostGone"] and k["carry"] is None
          and k["step"] == "quant" and k["picked"] == "",
          "перенос, который забрал браузер, ничего не оставляет; defect-history: прежде такой перенос глушил все клики сборки до следующего нажатия на карточку")
    check(got["arrows"] == [{"left": 320, "behavior": "smooth"}, {"left": -320, "behavior": "smooth"}] and got["arrowNoShelf"] is False,
          "стрелка двигает полку на большую часть её ширины туда, куда смотрит; negative: без полки — ничего")
    se = got["scrolledEnds"]
    check(se == {"kept": {"step": "engine", "left": 260}, "cls": ["has-back", "has-more"]}, f"полку прокрутили — место запомнено для шага, концы сказаны (получено {se})")
    mo = got["mounted"]
    check(mo["left"] == 260 and mo["ends"] == {"back": True, "more": True} and mo["cls"] == ["has-back", "has-more"],
          "доска перерисовала страницу — полка того же шага там, куда её пролистали")
    check(got["otherStep"] == {"ends": {"back": False, "more": True}, "left": 0}, "negative: на другом шаге полка с начала")
    check(got["otherModelShelf"] == {"left": 0, "kept": {"step": "", "left": 0}}, "negative: у другой модели полка с начала, место прежней забыто")
    check(got["notTrack"] is True and got["noTrack"] is None, "negative: прокрутка не полки не трогает её место; страницы без полки — ничего")


def section_life(got):
    print("созданная ячейка, другая модель, наборы, правила:")
    st = got["made"]
    check(st == {"picked": {"engine": "", "quant": "", "params": ""}, "launch": None, "server": None, "owns": False, "model": "Zeta-GGUF", "host": "box", "step": "engine"},
          "старт создал ячейку — у неё своя строка и своё имя, места пусты для следующего, полка снова на движках, модель та же; "
          "negative: ключ сборки больше ничего не называет — второй Start создал бы вторую ячейку")
    check(got["otherModel"] == {"picked": {"engine": "", "quant": "", "params": ""}, "model": "Alpha", "step": "engine"},
          "другая модель — выбранное для прежней не переносится, полка с начала")
    check(got["noFiles"] == {"engines": ["No engine here runs a file of this model."], "quants": ["The library holds no file of this model."]},
          "у модели нет файлов в библиотеке — так и сказано на полке и движков, и квантов")
    fl = got["failed"]
    check(fl["read"] == "failed" and fl["words"] == ["The saved sets could not be read."] and fl["cards"] == ["cell:c22011", "cell:c3f9a02b1"],
          "наборы не прочитались — сказано рядом с настройками ячеек; negative: полка с одними ячейками не читается как «наборов нет»")
    check(got["noSets"] == ["No saved set, and no cell of this model on this engine.", "Saved sets that could not be read, left out: 2."],
          f"наборы прочитаны, у движка ничего нет — тогда и только тогда «нет»; непрочитанные строки названы и здесь (получено {got['noSets']})")
    check(got["strataReading"] == ["Reading the saved sets…"] and got["strataFailed"] == ["The saved sets could not be read."],
          f"negative: наборы читаются или не прочитались — «нет» не сказано, сказано, что с ними (получено {got['strataReading']}, {got['strataFailed']})")
    check(got["nextStep"] == ["engine", "quant", "engine", "params", "params"],
          f"следующий шаг — первая недостающая часть, движок или квант, а когда обе на местах — настройки (получено {got['nextStep']})")
    check(got["gesture"] == ["carry", "carry", "carry", "scroll", "", "carry", "carry", "scroll"],
          f"жест по первому сдвигу: вверх или вниз (и поровну) — перенос; вбок мышью — протяжка полки, пальцем — прокрутка браузера (получено {got['gesture']})")
    check(got["ends"] == [{"back": False, "more": False}, {"back": False, "more": True}, {"back": True, "more": False}, {"back": True, "more": True},
                          {"back": False, "more": False}, {"back": False, "more": False}],
          f"концы полки: что за краем — сказано; negative: сдвиг в пиксель — не край, пустое — нет краёв (получено {got['ends']})")
    check(got["offered"] == [True, False, False, False, True], "мастер предлагает раннер; negative: клон голоса, свой движок, пустота")
    check(got["fieldsOfSet"] == {"TEMPERATURE": "0.2", "CACHE_PROMPT": "1", "CONTEXT_SHIFT": "0", "TOP_K": "40"}, "false — это «0», а не пропуск")
    check(got["setting"] == [["CTX_SIZE", True], ["TEMPERATURE", True], ["RUNNER", False], ["MODEL_FILE", False], ["MMPROJ_FILE", False], ["DEVICE", False], ["ENV", False],
                             ["FIT", False], ["MODEL_NAME", False], ["MAIN_GPU", False], ["SPLIT_MODE", False]],
          "что берётся из настроек ячейки; negative: движок, файлы, место, имя, ведущая карта и разрез слоёв — нет")


def main():
    node = find_node()
    if node is None:
        print("js machine-build: SKIPPED — node не найден")
        return 0
    probe = ROOT / "scripts" / ".probe_machine_build.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "i18n", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js machine-build: FAILED — харнесс не отработал")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    section_drawing(got)
    section_steps(got)
    section_picking(got)
    section_carry(got)
    section_life(got)
    if _fail:
        print(f"\njs machine-build FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  -", msg)
        return 1
    print("\njs machine-build OK: рельс-шаги над полкой, конец рельса, полоса, наборы, перенос вверх, протяжка и место полки, созданная ячейка — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
