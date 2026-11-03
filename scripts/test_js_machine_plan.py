#!/usr/bin/env python3
"""Value snapshot: static/js/machine-plan.js — what the operator lays out on a machine's rack before it happens (К1, 2026-10-31).

The owner: "drag a model onto a video card or elsewhere to start it and say where; divide it between the cards by dragging". A model
dropped on a lane, or a handle moved, is a plan: the fields of the cell's config it would change. Nothing on the machine changes until
Start, which stops what gives way, saves the config and starts the cell.

Pinned by value, each claim with its negative:
  * MachineRoom: what a leaving cell holds is free again, on its cards and, for a cell not on a card or one that keeps its weights in
    RAM, in RAM; a figure nobody said stays unsaid; nothing leaving, the machine itself;
  * RackShares: a drop fills its card, the other cards in order, then RAM; a share set by hand keeps the whole, takes from RAM first and
    the last card next, gives to the cards in use first, RAM next and a card not in use last, never past a room;
  * the moves, a kind per family: llama.cpp alone on a card it fits, over the others when it does not, on the processor by the form's
    own fields; a server of one card by its ENV's pin, its other rows kept; vLLM by its pin and what it would ask; refused by name where
    a cell cannot lie — an engine's, a card-only runner in RAM, a processor-only one on a card, a tensor-parallel vLLM;
  * MachinePlan: the facts as the plan would have them, what a start would change, whether it still means anything;
  * PaneLean: the pointer near a pane's top leans up, near its bottom down, in the middle not at all, and a pane too low has no edges;
  * MachineDrag: a press that does not move is a click; a press on a cell's own button takes nothing; a drag from a cell's row lays a plan,
    or says why not; a model that fits leaves what lies under it alone, one that does not takes its place; a running cell dropped on the list
    of models stops; Escape goes back; a handle sets a share, by pointer and by arrow keys;
  * MachinePlanStart: stops, waits, saves, starts, in that order; a cell that does not let go is said by name, and the plan stays.

The module is loaded FOR REAL with placement.js; i18n (the English words) is a stand-in, and the document is one.

Run: python3 scripts/test_js_machine_plan.py
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
const P = await import("../static/js/machine-plan.js");
const out = {};
const GIB = 2 ** 30;
const NODE = {
  id: "box", cpu: { availableCores: 16, physicalCores: 8, ram: { totalGb: 60.5, usedGb: 20 } },
  gpus: [{ index: 1, memoryTotalMiB: "32768", memoryUsedMiB: "2048", memoryFreeMiB: "30720" }, { index: 0, memoryTotalMiB: "24576", memoryUsedMiB: "18432", memoryFreeMiB: "6144" }],
  servers: [{ port: 22007, phase: "running", gpuMem: { 0: 12288 }, ramBytes: 5 * GIB }, { port: 22001, phase: "running", ramBytes: 3 * GIB },
            { port: 22009, phase: "running", gpuMem: { 1: 2048 }, ramBytes: 30 * GIB }, { port: 22020, phase: "stopped" }],
};
const keeps = (s) => s.port === 22009;
{
  const onCard = P.MachineRoom.without(NODE, ["22007"], keeps);
  const inRam = P.MachineRoom.without(NODE, [22001], keeps);
  const kept = P.MachineRoom.without(NODE, [22009], keeps);
  const blind = P.MachineRoom.without({ gpus: [{ index: 0 }], cpu: {}, servers: [{ port: 1, gpuMem: { 0: 100 }, ramBytes: GIB }] }, [1]);
  out.room = {
    onCard: { card0: [onCard.gpus[1].memoryUsedMiB, onCard.gpus[1].memoryFreeMiB], card1Same: onCard.gpus[0] === NODE.gpus[0], ram: onCard.cpu.ram.usedGb, leaving: onCard.servers.filter((s) => s.leaving).map((s) => s.port) },
    inRam: inRam.cpu.ram.usedGb, kept: [kept.cpu.ram.usedGb, kept.gpus[0].memoryUsedMiB],
    none: P.MachineRoom.without(NODE, []) === NODE, source: NODE.gpus[1].memoryUsedMiB,
    blind: [blind.gpus[0].memoryUsedMiB ?? null, blind.gpus[0].memoryFreeMiB ?? null, blind.cpu.ram ?? null],
    of: P.MachineRoom.of(NODE),
    ofBlind: P.MachineRoom.of({ gpus: [{ index: 0 }], cpu: {} }),
    rooms: P.MachineRoom.rooms(P.MachineRoom.of(NODE)),
    crumb: P.MachineRoom.rooms(P.MachineRoom.of({ gpus: [{ index: 0, memoryFreeMiB: 700, memoryTotalMiB: 1000, memoryUsedMiB: 300 }, { index: 1, memoryFreeMiB: 800, memoryTotalMiB: 1000, memoryUsedMiB: 200 }], cpu: {} })).of,
  };
}
{
  const rooms = { ids: ["0", "1", "2", "ram"], of: { 0: 10, 1: 20, 2: 5, ram: 30 } };
  const sum = (s) => Object.values(s).reduce((a, b) => a + b, 0);
  const set = (from, id, want) => { const s = P.RackShares.set(from, id, want, rooms); return { s, whole: sum(s) }; };
  out.shares = {
    drop: P.RackShares.dropped(12, "1", rooms), dropSpill: P.RackShares.dropped(40, "1", rooms), dropOver: P.RackShares.dropped(90, "ram", rooms),
    fromRam: set({ 0: 4, 1: 4, 2: 0, ram: 4 }, "0", 6),
    fromCards: set({ 0: 4, 1: 4, 2: 2, ram: 0 }, "0", 7),
    toUsed: set({ 0: 4, 1: 4, 2: 0, ram: 4 }, "0", 2),
    toRam: set({ 0: 10, 1: 20, 2: 0, ram: 0 }, "1", 15),
    toIdle: set({ 0: 10, 1: 20, 2: 0, ram: 30 }, "1", 15),
    pastRoom: set({ 0: 5, 1: 10, 2: 0, ram: 0 }, "0", 99),
    toZero: set({ 0: 4, 1: 4, 2: 2, ram: 0 }, "2", -3),
    cannotGo: set({ 0: 10, 1: 20, 2: 5, ram: 30 }, "1", 1),
    cards: P.RackShares.cards({ 2: 3, 0: 1, 1: 0, ram: 9 }),
  };
}
{
  const fields = (extra = {}) => ({ ENV: "", DEVICE: "", FIT_TARGET: "", TENSOR_SPLIT: "", FIT: "", N_GPU_LAYERS: "", N_CPU_MOE: "", CPU_MOE: "", KV_OFFLOAD: "", ...extra });
  const modelOf = (gb) => ({ weightsGb: gb * 0.65, kvGb: gb * 0.3, batchGb: gb * 0.05, layers: 60, experts: 0, expertsGb: 0 });
  const room = P.MachineRoom.of(NODE);
  const llama = (bytesGb, extra = {}) => P.CellMove.of({ family: "llama", bytes: bytesGb * GIB, model: modelOf(bytesGb), fields: fields(), mode: "layer", ...extra });
  // The board's builder (topology-nodes.js) over VllmPlacement: what a start with these fields asks.
  const vllmAt = (needed, weightsGb = 30) => (f) => { const rides = Number(f.CPU_OFFLOAD_GB) || 0; return { asks: [{ index: f.ENV, mib: 1 }], over: needed > rides, ridesGb: rides, offloadNeededGb: needed, weightsGb }; };
  out.moves = {
    sizable: [llama(10).sizable, P.CellMove.of({ family: "pinned" }).sizable, P.CellMove.of({}).sizable],
    alone: llama(10).to("1", room),
    over: llama(62).to("1", room),
    other: llama(62).to("0", room),
    ram: llama(62).to("ram", room),
    noCard: llama(10).to("7", room),
    unknownSize: P.CellMove.of({ family: "llama", bytes: null, fields: fields(), mode: "layer" }).to("1", room),
    noModel: P.CellMove.of({ family: "llama", bytes: 10 * GIB, model: null, fields: fields(), mode: "layer" }).to("1", room),
    tensor: llama(62, { mode: "tensor" }).to("1", room),
    tensorOne: llama(10, { mode: "tensor" }).to("1", room),
    kvOff: llama(10, { fields: fields({ KV_OFFLOAD: "0" }) }).to("1", room),
    shared: llama(62).share({ 0: 5, 1: 30, ram: 27 }, "1", 20, room),
    sharedAll: llama(30).share({ 0: 5, 1: 20, ram: 5 }, "ram", 0, room),
    sharedFloor: llama(40).share({ 0: 5, 1: 30, ram: 5 }, "ram", 0, room),
    sharedOff: llama(10).share({ 0: 5, 1: 5, ram: 0 }, "1", 0, room),
    sharedNone: llama(10).share({ 0: 0, 1: 10, ram: 0 }, "ram", 10, room),
    pinned: P.CellMove.of({ family: "pinned", onCard: "free", cpuOk: true, gpuOk: true, fields: fields({ ENV: "A=1\nCUDA_VISIBLE_DEVICES=0\nB=2" }) }).to("1", room),
    pinnedCard: P.CellMove.of({ family: "pinned", gpuOk: true, fields: fields() }).to("0", room),
    pinnedRam: P.CellMove.of({ family: "pinned", cpuOk: true, fields: fields({ ENV: "A=1\nCUDA_VISIBLE_DEVICES=0" }) }).to("ram", room),
    pinnedNoRam: P.CellMove.of({ family: "pinned", cpuOk: false, fields: fields() }).to("ram", room),
    pinnedBack: P.CellMove.of({ family: "pinned", gpuOk: true, fields: fields({ ENV: "TTS_DEVICE=cpu\nCUDA_VISIBLE_DEVICES=" }) }).to("1", room),
    cpuOnly: P.CellMove.of({ family: "pinned", cpuOk: true, gpuOk: false, fields: fields() }).to("0", room),
    vllm: P.CellMove.of({ family: "vllm", fields: fields({ ENV: "X=1" }), asksFor: vllmAt(0) }).to("1", room),
    vllmBig: P.CellMove.of({ family: "vllm", fields: fields(), asksFor: vllmAt(12) }).to("1", room),
    vllmOwn: P.CellMove.of({ family: "vllm", fields: fields({ CPU_OFFLOAD_GB: "20" }), asksFor: vllmAt(12) }).to("1", room),
    vllmSmall: P.CellMove.of({ family: "vllm", fields: fields({ CPU_OFFLOAD_GB: "5" }), asksFor: vllmAt(0) }).to("1", room),
    vllmSize: ["ram", "0", "1"].map((id) => P.CellMove.of({ family: "vllm", fields: fields(), asksFor: vllmAt(0) }).canSet(id)),
    vllmSizable: [P.CellMove.of({ family: "vllm", fields: fields(), asksFor: vllmAt(0) }).sizable, P.CellMove.of({ family: "vllm", parallel: true, fields: fields(), asksFor: vllmAt(0) }).sizable, P.CellMove.of({ family: "vllm", fields: fields() }).sizable],
    vllmShare: [10.2, 10.3, 0, -3, 500, "x"].map((want) => P.CellMove.of({ family: "vllm", fields: fields({ ENV: "A=1" }), asksFor: vllmAt(0) }).share({}, "ram", want, { ramFreeGb: 40 }).fields),
    vllmShareRoom: P.CellMove.of({ family: "vllm", fields: fields(), asksFor: vllmAt(0, 500) }).share({}, "ram", 100, { ramFreeGb: 40.3 }).fields.CPU_OFFLOAD_GB,
    vllmShareBlind: P.CellMove.of({ family: "vllm", fields: fields(), asksFor: vllmAt(0, 500) }).share({}, "ram", 100, { ramFreeGb: null }).fields.CPU_OFFLOAD_GB,
    vllmShareRidesOver: P.CellMove.of({ family: "vllm", fields: fields(), asksFor: vllmAt(0) }).share({}, "ram", 6, { ramFreeGb: 40 }),
    llamaSets: ["ram", "1"].map((id) => P.CellMove.of({ family: "llama", fields: fields() }).canSet(id)),
    vllmRam: P.CellMove.of({ family: "vllm", fields: fields() }).to("ram", room),
    vllmParallel: P.CellMove.of({ family: "vllm", parallel: true, fields: fields() }).to("1", room),
    engine: P.CellMove.of({ family: "", fields: fields() }).to("1", room),
    none: P.CellMove.of(null).to("1", room),
  };
}
{
  const plan = new P.MachinePlan();
  const facts = { how: "spread", bytes: 1, fields: { DEVICE: "", FIT_TARGET: "9", ENV: "" }, asks: ["was"] };
  out.plan = { offFacts: plan.on, key: plan.key(), leaving: plan.leaving() };
  plan.set(22020, { how: "plan", fields: { DEVICE: "CUDA1", FIT_TARGET: "1", THREADS: "1" }, shares: { 1: 5 } }, { evict: [22007], moved: true });
  out.plan.on = plan.on;
  out.plan.leavingOn = plan.leaving();
  out.plan.facts = plan.facts(facts);
  out.plan.changes = plan.changes({ DEVICE: "CUDA0", FIT_TARGET: "1", THREADS: "8" });
  out.plan.changesNone = plan.changes({ DEVICE: "CUDA1", FIT_TARGET: "1", THREADS: "1" });
  plan.set(22020, { how: "asks", fields: { ENV: "CUDA_VISIBLE_DEVICES=1\nA=2", DEVICE: "" }, asks: ["new"] });
  out.plan.factsAsks = plan.facts(facts);
  out.plan.changesEmpty = plan.changes({ DEVICE: "CUDA1", ENV: "" });
  const key = plan.key();
  const saved = plan.snapshot();
  plan.clear();
  out.plan.cleared = [plan.on, plan.port, plan.fields, plan.key()];
  plan.restore(saved);
  out.plan.restored = [plan.on, plan.key() === key];
  const phase = (s) => s.phase;
  const nodeWith = (me, other) => ({ servers: [{ port: 22020, phase: me }, ...(other ? [{ port: 22007, phase: other }] : [])] });
  const valid = (moved, evict, node) => { const p = new P.MachinePlan(); p.set(22020, { how: "plan", fields: { A: "1" } }, { moved, evict }); return p.validFor(node, phase); };
  out.plan.valid = {
    standing: valid(false, [], nodeWith("stopped")), startedSince: valid(false, [], nodeWith("running")), movedHolds: valid(true, [], nodeWith("running")),
    movedStopped: valid(true, [], nodeWith("stopped")), gone: valid(false, [], { servers: [] }), evictHolds: valid(false, ["22007"], nodeWith("stopped", "running")),
    evictLeft: valid(false, ["22007"], nodeWith("stopped", "stopped")), evictGone: valid(false, ["22007"], nodeWith("stopped")),
  };
  const busy = new P.MachinePlan();
  busy.set(22020, { how: "plan", fields: { A: "1" } }, { moved: true });
  busy.busy = true;
  out.plan.valid.busy = busy.validFor(nodeWith("stopped"), phase);
}
// The pointer, on a document of stand-ins: what is under the pointer is set by each step.
{
  const made = [];
  const listeners = {};
  let under = null;
  const lane = (id) => ({ dataset: { tId: id } });
  const pointAt = (spec) => {
    under = spec ? { closest: (sel) => {
      if (sel === '[data-t="machine-map-lane"]') return spec.lane ? lane(spec.lane) : null;
      if (sel === '[data-t="machine-map-block"]') return spec.block ? { dataset: { machinePick: spec.block } } : null;
      if (sel === '[data-t="machine-models"]') return spec.bench ? {} : null;
      return null;
    } } : null;
  };
  const docEl = { classes: new Set(), classList: { add: (c) => docEl.classes.add(c), remove: (c) => docEl.classes.delete(c) } };
  const barRect = { left: 100, width: 400 };
  const gripEl = (id) => ({ dataset: { machineGrip: id }, focusCount: 0, focus() { this.focusCount += 1; }, closest: () => ({ querySelector: () => ({ getBoundingClientRect: () => barRect }) }) });
  const grips = { 1: gripEl("1") };
  const doc = {
    documentElement: docEl, body: { appendChild: (el) => made.push(el) },
    createElement: () => { const el = { style: {}, removed: false, remove() { this.removed = true; } }; return el; },
    addEventListener: (type, fn) => { (listeners[type] ||= []).push(fn); },
    elementFromPoint: () => under,
    querySelector: (sel) => { if (sel === ".machine-main") return pane; const m = sel.match(/data-machine-grip="([^"]+)"/); return m ? grips[m[1]] : null; },
  };
  // The pane the list stands in, 800 px tall from y = 100, with 300 px still to scroll up and a browser that stops at 0.
  const frames = [];
  let paneTop = 300;
  let pane = { get scrollTop() { return paneTop; }, set scrollTop(v) { paneTop = Math.max(0, v); }, getBoundingClientRect: () => ({ top: 100, bottom: 900 }) };
  const fieldsOf = () => ({ ENV: "", DEVICE: "", FIT_TARGET: "", TENSOR_SPLIT: "", FIT: "", N_GPU_LAYERS: "", N_CPU_MOE: "", CPU_MOE: "", KV_OFFLOAD: "" });
  const llamaFit = (gb) => ({ how: "spread", family: "llama", bytes: gb * GIB, fields: fieldsOf(), mode: "layer", keepsRam: false });
  const cells = new Map([
    ["22020", { name: "Hermes", group: "bench", launch: "data-y", stop: "", fit: llamaFit(20) }],
    ["22021", { name: "Huge", group: "bench", launch: "data-y", stop: "", fit: llamaFit(50) }],
    ["22007", { name: "gemma", group: "holds", launch: "", stop: "data-s", fit: llamaFit(12) }],
    ["22005", { name: "whisper", group: "holds", launch: "", stop: "data-s", fit: { how: "card", family: "pinned", cpuOk: false, gpuOk: true, fields: fieldsOf(), bytes: 2 * GIB } }],
    ["22008", { name: "big", group: "holds", launch: "", stop: "data-s", fit: llamaFit(50) }],
    ["22030", { name: "reserved", group: "bench", launch: "", stop: "", fit: llamaFit(1) }],
    ["22031", { name: "coming", group: "coming", launch: "", stop: "data-s", fit: llamaFit(1) }],
  ]);
  const node = { id: "box", cpu: { availableCores: 8, physicalCores: 8, ram: { totalGb: 60, usedGb: 10 } },
                 gpus: [{ index: 0, memoryTotalMiB: 24576, memoryUsedMiB: 18432, memoryFreeMiB: 6144 }, { index: 1, memoryTotalMiB: 32768, memoryUsedMiB: 0, memoryFreeMiB: 32768 }],
                 servers: [{ port: 22007, phase: "running", gpuMem: { 0: 12288 } }, { port: 22005, phase: "running", gpuMem: { 0: 2048 } }, { port: 22008, phase: "running", gpuMem: { 0: 1024 } }] };
  const log = [];
  let chosen = "";
  let pageNode = node;
  const plan = new P.MachinePlan();
  const drag = new P.MachineDrag(plan);
  // Where the facts lay the cell: a rule of its own, as simple as the test needs (machine-head.js CellFit is pinned on its own).
  const place = (facts, at) => {
    const free = (at.gpus || []).reduce((sum, g) => sum + Number(g.memoryFreeMiB) / 1024, 0);
    const need = Number(facts.bytes) / GIB;
    return need <= free - 0.5 ? { verdict: "cards", cards: [{ index: "1", gb: need }], ramGb: 0 } : need <= free + 40 ? { verdict: "spill", cards: [{ index: "1", gb: free }], ramGb: need - free } : { verdict: "none", cards: [], ramGb: 0 };
  };
  drag.bind(doc, { cells: () => cells, node: () => pageNode, place, chosenPort: () => chosen, choose: (p) => { chosen = String(p); log.push(["choose", p]); }, bring: (p) => log.push(["bring", p]), patch: () => log.push(["patch"]),
                   // The page's stop is the cell's own button clicked: a click the guard of a drag's last click may eat.
                   stop: (p) => { let eaten = false; (listeners.click || []).forEach((fn) => fn({ target: { closest: () => null }, stopPropagation() { eaten = true; }, preventDefault() {} })); log.push(["stop", p, eaten ? "eaten" : "pressed"]); },
                   notify: (m) => log.push(["notify", m]), nextFrame: (fn) => { frames.push(fn); return frames.length; } });
  drag.bind(doc, { patch: () => log.push(["second bind"]) });
  const fire = (type, e) => (listeners[type] || []).forEach((fn) => fn(e));
  const pressOn = (port, extra = {}) => fire("pointerdown", { button: 0, clientX: 500, clientY: 500, target: { closest: (sel) => (sel === "[data-machine-pick]" ? { dataset: { machinePick: port } } : null) }, ...extra });
  const moveTo = (spec, x = 200, y = 100) => { pointAt(spec); fire("pointermove", { buttons: 1, clientX: x, clientY: y, preventDefault() {} }); };
  const release = () => fire("pointerup", {});
  const snap = () => ({ on: plan.on, port: plan.port, device: plan.fields?.DEVICE ?? null, evict: [...plan.evict], moved: plan.moved, dragging: plan.dragging, busy: drag.busy, chosen });
  const clicked = () => { const e = { stopped: false, stopPropagation() { this.stopped = true; }, preventDefault() {} }; fire("click", e); return e.stopped; };
  out.drag = { binds: (listeners.pointerdown || []).length };
  // The pane comes along: the pointer on its top edge, then still; what lies under it changes as it moves.
  const runFrame = () => frames.shift()?.();
  const point = (spec, y, x = 200) => moveTo(spec, x, y);
  pressOn("22020"); point({}, 500);
  out.drag.leanMiddle = { waiting: frames.length, top: paneTop };
  runFrame();
  out.drag.leanMiddleRan = { waiting: frames.length, top: paneTop };
  point({}, 500); point({}, 110); point({}, 104);
  out.drag.leanOneFrame = frames.length;
  pointAt({ lane: "gpu-1" });
  runFrame();
  out.drag.leanMoved = { top: paneTop, waiting: frames.length, on: plan.on, device: plan.fields?.DEVICE ?? null };
  paneTop = 0;
  runFrame();
  out.drag.leanAtEnd = { top: paneTop, waiting: frames.length };
  point({}, 104);
  release();
  plan.clear();
  log.length = 0;
  out.drag.leanAfterEnd = (() => { paneTop = 200; runFrame(); return { top: paneTop, waiting: frames.length }; })();
  frames.length = 0;
  pressOn("22020"); point({}, 895); runFrame();
  out.drag.leanDown = { top: paneTop, waiting: frames.length };
  const realPane = pane; pane = null; runFrame();
  out.drag.leanNoPane = { top: paneTop, waiting: frames.length };
  pane = realPane; frames.length = 0; release(); plan.clear(); log.length = 0; pointAt(null); made.length = 0;
  await (await import("node:timers/promises")).setTimeout(P.MachineDrag.CLICK_MS + 30);

  // A press that does not move: a click, as it was.
  pressOn("22020"); fire("pointermove", { buttons: 1, clientX: 502, clientY: 501, preventDefault() {} }); release();
  out.drag.still = { ...snap(), swallowed: clicked(), log: log.splice(0) };
  // A cell that cannot be taken.
  pressOn("22030"); moveTo({ lane: "gpu-1" }); out.drag.noLaunch = [drag.busy, plan.on]; release();
  pressOn("22031"); moveTo({ lane: "gpu-1" }); out.drag.onItsWay = [drag.busy, plan.on]; release();
  pressOn("22999"); moveTo({ lane: "gpu-1" }); out.drag.noFacts = [drag.busy, plan.on]; release();
  pressOn("22020", { button: 2 }); moveTo({ lane: "gpu-1" }); out.drag.rightButton = [drag.busy, plan.on]; release();
  pressOn("22020", { target: { closest: (sel) => (sel === "[data-model-rate]" ? {} : sel === "[data-machine-pick]" ? { dataset: { machinePick: "22020" } } : null) } }); moveTo({ lane: "gpu-1" }); out.drag.rating = [drag.busy, plan.on]; release();
  // A cell's row is taken by any place on it but its own buttons.
  const inRow = (...own) => ({ closest: (sel) => (own.includes(sel) ? {} : sel === "[data-machine-pick]" ? { dataset: { machinePick: "22020", t: "machine-model-launch" } } : null) });
  pressOn("22020", { target: inRow("[data-machine-own]") }); moveTo({ lane: "gpu-1" }); out.drag.ownButton = [drag.busy, plan.on]; release();
  plan.clear();
  pressOn("22020", { target: inRow() }); moveTo({ lane: "gpu-1" }); out.drag.fromRow = [drag.busy, plan.on, plan.port]; release();
  plan.clear();
  made.length = 0;
  out.drag.taken = [P.MachineDrag.taken(inRow())?.dataset?.machinePick ?? null, P.MachineDrag.taken(inRow("[data-machine-own]")), P.MachineDrag.taken(inRow("[data-model-rate]")), P.MachineDrag.taken({ closest: () => null }), P.MachineDrag.taken(null)];
  log.splice(0);
  // A drag onto a card.
  pressOn("22020"); moveTo({ lane: "gpu-1" }, 300, 200);
  out.drag.during = { ...snap(), tag: made[0]?.textContent, tagAt: made[0]?.style.transform, cls: [...docEl.classes], drop: [plan.drop, plan.dropOk], patches: log.filter((l) => l[0] === "patch").length };
  moveTo({ lane: "gpu-1" }, 310, 210);
  out.drag.samePlace = log.filter((l) => l[0] === "patch").length;
  moveTo({}, 310, 210);
  out.drag.left = snap();
  moveTo({ lane: "gpu-1" }, 300, 200);
  release();
  out.drag.dropped = { ...snap(), tagGone: made[0]?.removed, cls: [...docEl.classes], drop: plan.drop, swallowed: clicked(), next: clicked(), log: log.splice(0).filter((l) => l[0] !== "patch") };
  // Dropped nowhere: back to the plan there was.
  chosen = "";
  const was = plan.key();
  pressOn("22021"); moveTo({ lane: "gpu-0" }); moveTo({}); release();
  out.drag.nowhere = { same: plan.key() === was, chosen, log: log.splice(0).filter((l) => l[0] !== "patch") };
  // Escape, and the pointer gone.
  pressOn("22021"); moveTo({ lane: "gpu-0" }); fire("keydown", { key: "Escape" });
  out.drag.escape = { same: plan.key() === was, busy: drag.busy, dragging: plan.dragging, cls: [...docEl.classes] };
  pressOn("22021"); moveTo({ lane: "gpu-0" }); fire("pointercancel", {});
  out.drag.cancel = { same: plan.key() === was, busy: drag.busy };
  pressOn("22021"); moveTo({ lane: "gpu-0" }); fire("pointermove", { buttons: 0, clientX: 1, clientY: 1 });
  out.drag.noButtons = { same: plan.key() === was, busy: drag.busy };
  plan.clear(); log.splice(0);
  // Refused: said, and no plan.
  pressOn("22005"); moveTo({ lane: "ram" }); out.drag.refusedOver = [plan.on, plan.drop, plan.dropOk]; release();
  out.drag.refused = { ...snap(), log: log.splice(0).filter((l) => l[0] !== "patch") };
  // A running cell moved: its own memory is free where it goes.
  pressOn("22007"); moveTo({ lane: "gpu-1" }); release();
  out.drag.moved = { ...snap(), log: log.splice(0).filter((l) => l[0] !== "patch") };
  plan.clear();
  // A running cell dropped on the list of models: its own Stop.
  pressOn("22007"); moveTo({ bench: true }); release();
  out.drag.benchedAtOnce = log.filter((l) => l[0] === "stop").length;
  // The page's timers are unref'd here (_js_globals.mjs): only a timer of node's own keeps the process waiting for them.
  await (await import("node:timers/promises")).setTimeout(P.MachineDrag.CLICK_MS + 30);
  out.drag.benched = { ...snap(), log: log.splice(0).filter((l) => l[0] !== "patch") };
  // A stopped one dropped on the list: nothing.
  pressOn("22020"); moveTo({ bench: true }); release();
  out.drag.benchedStanding = { ...snap(), log: log.splice(0).filter((l) => l[0] !== "patch") };
  // On a block: one that fits leaves it alone; one that does not takes its place.
  pressOn("22020"); moveTo({ lane: "gpu-0", block: "22007" }); release();
  out.drag.fitsBlock = snap();
  plan.clear();
  pressOn("22021"); moveTo({ lane: "gpu-0", block: "22007" }); release();
  out.drag.takesBlock = snap();
  plan.clear();
  pressOn("22008"); moveTo({ lane: "gpu-0", block: "22008" }); release();
  out.drag.ownBlock = snap();
  plan.clear();
  log.splice(0);
  // A handle, a plan in hand: the share follows the pointer on its bar.
  chosen = "22021";
  pressOn("22021"); moveTo({ lane: "gpu-1" }); release();
  const gripPress = (id, extra = {}) => fire("pointerdown", { button: 0, preventDefault() {}, stopPropagation() {}, target: { closest: (sel) => (sel === "[data-machine-grip]" ? { dataset: { machineGrip: id, machineGripFrom: "0", machineGripWhole: "32" } } : null) }, ...extra });
  const before = { ...plan.shares };
  gripPress("1");
  out.drag.gripBusy = drag.busy;
  fire("pointermove", { buttons: 1, clientX: 300, clientY: 0, preventDefault() {} });
  out.drag.grip = { before, after: { ...plan.shares }, target: plan.fields.FIT_TARGET };
  release();
  out.drag.gripDone = drag.busy;
  // A handle whose piece starts further along the bar: the share is what lies past that start.
  gripPress("1", { target: { closest: (sel) => (sel === "[data-machine-grip]" ? { dataset: { machineGrip: "1", machineGripFrom: "8", machineGripWhole: "32" } } : null) } });
  fire("pointermove", { buttons: 1, clientX: 300, clientY: 0, preventDefault() {} });
  out.drag.gripFrom = plan.shares["1"];
  release();
  // Arrow keys on a focused handle.
  const arrow = (key) => { const e = { key, prevented: false, preventDefault() { this.prevented = true; }, target: { closest: (sel) => (sel === "[data-machine-grip]" ? { dataset: { machineGrip: "1", machineGripHolds: "9" } } : null) } }; fire("keydown", e); return e.prevented; };
  const keep = plan.shares["1"];
  out.drag.keys = { right: arrow("ArrowRight"), afterRight: plan.shares["1"] - keep, left: arrow("ArrowLeft"), afterLeft: plan.shares["1"] - keep, other: arrow("a"), focused: grips[1].focusCount };
  // A handle with no plan yet: one is made from where the cell would lie now.
  plan.clear();
  chosen = "22020";
  gripPress("1");
  fire("pointermove", { buttons: 1, clientX: 200, clientY: 0, preventDefault() {} });
  out.drag.gripFresh = { on: plan.on, port: plan.port, shares: { ...plan.shares } };
  release();
  // One that cannot be sized, and none at all.
  plan.clear();
  chosen = "22005";
  gripPress("1"); fire("pointermove", { buttons: 1, clientX: 200, clientY: 0, preventDefault() {} }); release();
  out.drag.gripPinned = plan.on;
  chosen = "";
  gripPress("1"); fire("pointermove", { buttons: 1, clientX: 200, clientY: 0, preventDefault() {} }); release();
  out.drag.gripNone = plan.on;
  // The panel's buttons: the same plan with no pointer, or the reason.
  plan.clear(); log.splice(0); chosen = "";
  const placeBtn = (port, target) => fire("click", { target: { closest: (sel) => (sel === "[data-machine-place]" ? { dataset: { machinePlaceFor: port, machinePlace: target } } : null) }, preventDefault() {}, stopPropagation() {} });
  placeBtn("22020", "1");
  out.drag.place = { ...snap(), log: log.splice(0).filter((l) => l[0] !== "patch") };
  plan.clear();
  placeBtn("22007", "1");
  out.drag.placeMoved = snap();
  plan.clear(); log.splice(0);
  placeBtn("22005", "ram");
  out.drag.placeRefused = { on: plan.on, log: log.splice(0).filter((l) => l[0] !== "patch") };
  placeBtn("22999", "1");
  out.drag.placeUnknown = { on: plan.on, log: log.splice(0) };
  // Not on a machine's page.
  pageNode = null;
  pressOn("22020"); moveTo({ lane: "gpu-1" }); out.drag.otherPage = [drag.busy, plan.on]; release();
}
// A start.
{
  const run = async ({ phases = {}, failSave = false, failAct = false, refuse = [], evict = [], moved = false, now = null, seen = "starting" }) => {
    const log = [];
    const plan = new P.MachinePlan();
    plan.set(22020, { how: "plan", fields: { DEVICE: "CUDA1", FIT_TARGET: "1" } }, { evict, moved });
    const ticks = { n: 0 };
    const start = new P.MachinePlanStart({
      save: async (body) => { if (failSave) throw new Error("refused"); log.push(["save", body]); },
      act: async (h, p, a) => {
        if (failAct) throw new Error("no");
        log.push([a, h, String(p)]);
        if (refuse.includes(`${a}:${p}`)) return false;
        if (a === "start") phases[p] = [seen];
        return true;
      },
      phase: async (p) => { const list = phases[p] || ["stopped"]; const v = list.length > 1 ? list.shift() : list[0]; log.push(["phase", String(p), v]); return v; },
      pause: async () => { ticks.n += 1; }, now: now || (() => ticks.n),
    });
    try {
      const done = await start.run({ plan, hostId: "box", config: { MODEL_FILE: "m.gguf", DEVICE: "", THREADS: "8" }, cacheModels: true });
      return { log, ticks: ticks.n, done, leaving: plan.leaving(), moved: plan.moved };
    } catch (err) {
      return { log, error: String(err.message) };
    }
  };
  out.start = {
    plain: await run({}),
    evict: await run({ evict: ["22007", "22008"], phases: { 22007: ["running", "stopping", "stopped"], 22008: ["stopped"] } }),
    moved: await run({ moved: true, phases: { 22020: ["stopping", "stopped"] } }),
    stuck: await run({ evict: ["22007"], phases: { 22007: ["running"] }, now: (() => { let t = 0; return () => { t += 60_000; return t; }; })() }),
    failSave: await run({ failSave: true }),
    refusedStart: await run({ refuse: ["start:22020"], moved: true, evict: ["22007"], phases: { 22007: ["stopped"], 22020: ["stopped"] } }),
    refusedStop: await run({ refuse: ["stop:22007"], evict: ["22007", "22008"] }),
    unseen: await run({ seen: "stopped", now: (() => { let t = 0; return () => { t += 4000; return t; }; })() }),
    seenError: await run({ seen: "error" }),
    fits: ["cards", "card", "free", "unsized", "ram", "rides", "none", "unknown", "spill"].map((v) => P.MachineDrag.fits(v)),
    letGo: ["stopped", "error", "reserved", "", null, "running", "warming", "stopping", "downloading"].map((p) => P.MachinePlanStart.letGo(p)),
    stands: ["stopped", "error", "reserved", "", null, "running", "warming", "stopping", "downloading"].map((p) => P.MachinePlanStart.stands(p)),
  };
  {
    const held = new P.MachinePlan();
    held.set(22020, { how: "plan", fields: { A: "1" } }, { evict: ["22007"], moved: true });
    const room = { mark: 1 };
    held.begin(room);
    const during = [held.busy, held.room === room, held.leaving()];
    held.letGone();
    const gone = [held.leaving(), held.moved, held.on];
    held.end();
    const after = [held.busy, held.room, held.on];
    held.begin(room);
    held.clear();
    out.planLife = { during, gone, after, cleared: [held.busy, held.room] };
  }
  // The panel's buttons.
  const listeners = [];
  const doc = { addEventListener: (type, fn) => listeners.push([type, fn]) };
  const log = [];
  const plan = new P.MachinePlan();
  let answer = true;
  let saveFails = false;
  let actRefused = false;
  const rooms = [];
  const start = new P.MachinePlanStart({ save: async () => { log.push("save"); rooms.push(plan.room); if (saveFails) throw new Error("refused"); }, act: async (h, p, a) => { log.push(a); return !actRefused; }, phase: async () => "starting" });
  start.bind(doc, { plan, target: (p) => ({ hostId: "box", config: {}, cacheModels: false, question: `go ${p.port}?`, room: { shown: p.port } }), confirm: async (q) => { log.push(q); return answer; }, notify: (m) => log.push(`said ${m}`), redraw: () => log.push("redraw") });
  start.bind(doc, { plan, redraw: () => log.push("second") });
  const press = (attr) => Promise.all(listeners.map(([, fn]) => fn({ target: { closest: (sel) => (sel === attr ? {} : null) }, preventDefault() {} })));
  const lay = () => plan.set(22020, { how: "plan", fields: { A: "1" } });
  lay();
  await press("[data-machine-plan-start]");
  out.buttons = { binds: listeners.length, ok: [...log], on: plan.on };
  log.length = 0;
  lay(); answer = false;
  await press("[data-machine-plan-start]");
  out.buttons.declined = [[...log], plan.on, plan.busy];
  log.length = 0;
  answer = true; saveFails = true;
  await press("[data-machine-plan-start]");
  out.buttons.failed = [[...log], plan.on, plan.busy];
  log.length = 0;
  saveFails = false; actRefused = true;
  await press("[data-machine-plan-start]");
  out.buttons.refused = [[...log], plan.on, plan.busy, plan.room];
  out.buttons.rooms = [...rooms];
  actRefused = false;
  log.length = 0;
  plan.busy = true;
  await press("[data-machine-plan-start]");
  out.buttons.whileBusy = [...log];
  plan.busy = false;
  await press("[data-machine-plan-cancel]");
  out.buttons.cancel = [[...log], plan.on];
  log.length = 0;
  await press("[data-machine-plan-start]");
  out.buttons.noPlan = [...log];
  await press("[data-other]");
  out.buttons.other = [...log];
}
const L = (y, top = 100, bottom = 900) => P.PaneLean.at(y, top, bottom);
out.lean = { middle: L(500), topEdge: L(100), halfTop: L(128), bottomEdge: L(900), halfBottom: L(872), past: [L(50), L(990)], low: L(150, 100, 200) };
console.log(JSON.stringify(out));
'''


def section_room(got):
    print("машина после ухода ячеек:")
    r = got["room"]
    check(r["onCard"]["card0"] == [6144, 18432] and r["onCard"]["card1Same"] is True,
          "что держала уходящая на карте, свободно; другая карта та же; negative: исходные числа топологии не тронуты")
    check(r["source"] == "18432", "negative: копия, а не правка: исходная машина как была")
    check(r["onCard"]["ram"] == 20 and r["onCard"]["leaving"] == [22007],
          "negative: RSS ячейки на карте — отображённый файл, RAM она не возвращает; уходящая помечена для рисунка")
    check(r["inRam"] == 17, "ячейка без карты возвращает свой RSS")
    check(r["kept"] == [0, 0], "ячейка, что держит веса в RAM (keepsRam), возвращает и карту, и свой RSS; boundary: не меньше нуля")
    check(r["none"] is True, "negative: никто не уходит — та же машина")
    check(r["blind"] == [None, None, None], "negative: число, которого не сказали, не появляется")
    o = r["of"]
    check([c["index"] for c in o["cards"]] == [0, 1] and o["cards"][1]["freeGb"] == 30 and o["ramFreeGb"] == 40.5 and o["all"] == [0, 1] and o["cores"] == 8,
          "карты по порядку, свободное каждой, RAM, ядра — не больше физических")
    check(o["cards"][0]["ceilingGb"] == 5.75, "потолок карты — свободное без запаса, который llama.cpp оставляет всегда")
    check(r["ofBlind"]["cards"][0]["freeGb"] == 0 and r["ofBlind"]["ramFreeGb"] is None, "negative: карта без чисел — места нет; RAM без чисел — не известно, а не ноль")
    check(r["rooms"]["ids"] == ["0", "1", "ram"] and r["rooms"]["of"]["ram"] == 40.5, "места: карты по порядку, RAM последней")
    check(r["crumb"]["0"] == 0 and r["crumb"]["1"] == 0.53125, "boundary: меньше полугигабайта на карте — места нет: крошка модели не держит ни слоя и только называет карту")


def section_shares(got):
    print("доли:")
    s = got["shares"]
    check(s["drop"] == {"0": 0, "1": 12, "2": 0, "ram": 0}, "сброс на карту, где модель влезает: вся на ней")
    check(s["dropSpill"] == {"0": 10, "1": 20, "2": 5, "ram": 5}, "не влезает: эта карта доверху, другие по порядку, остаток в RAM")
    check(s["dropOver"] == {"0": 10, "1": 20, "2": 5, "ram": 30}, "boundary: больше всего места — занято всё, не больше")
    w = s["fromRam"]
    check(w["s"] == {"0": 6, "1": 4, "2": 0, "ram": 2} and w["whole"] == 12, "больше здесь — сначала из RAM, модель целая")
    w = s["fromCards"]
    check(w["s"] == {"0": 7, "1": 3, "2": 0, "ram": 0} and w["whole"] == 10, "RAM нет — с последней занятой карты, затем с предыдущей")
    w = s["toUsed"]
    check(w["s"] == {"0": 2, "1": 6, "2": 0, "ram": 4} and w["whole"] == 12, "меньше здесь — сначала на занятые карты, RAM не растёт")
    w = s["toRam"]
    check(w["s"] == {"0": 10, "1": 15, "2": 0, "ram": 5} and w["whole"] == 30, "занятые карты полны — в RAM")
    w = s["toIdle"]
    check(w["s"] == {"0": 10, "1": 15, "2": 5, "ram": 30} and w["whole"] == 60, "RAM полна — на незанятую карту: доля не теряется")
    w = s["pastRoom"]
    check(w["s"] == {"0": 10, "1": 5, "2": 0, "ram": 0} and w["whole"] == 15, "boundary: не больше места карты и не больше всей модели")
    w = s["toZero"]
    check(w["s"]["2"] == 0 and w["s"]["0"] + w["s"]["1"] == 10 and w["whole"] == 10, "boundary: ручка в ноль и дальше — карта выходит из модели, а не уходит в минус")
    w = s["cannotGo"]
    check(w["s"]["1"] == 20 and w["whole"] == 65, "negative: другим некуда взять — столько, сколько им некуда деть, остаётся здесь")
    check(s["cards"] == [0, 2], "карты с долей — по возрастанию, без пустых и без RAM")


def section_moves(got):
    print("как ячейка ложится, по семьям раннеров:")
    m = got["moves"]
    check(m["sizable"] == [True, False, False], "доля задаётся рукой только у llama.cpp")
    a = m["alone"]
    check(a["how"] == "plan" and a["fields"]["DEVICE"] == "CUDA1" and a["fields"]["MAIN_GPU"] == "1" and a["fields"]["SPLIT_MODE"] == "" and a["fields"]["N_GPU_LAYERS"] == "auto"
          and a["fields"]["FIT"] == "1" and a["fields"]["THREADS"] == "1" and a["fields"]["FIT_TARGET"].isdigit() and a["shares"] == {"1": 10},
          f"влезает на карту: только она, llama.cpp сам подбирает слои, потоков один (получено {a['fields']})")
    o = m["over"]
    check(o["shares"] == {"0": 5.75, "1": 29.75, "ram": 26.5} and o["fields"]["DEVICE"] == "" and o["fields"]["MAIN_GPU"] == "" and o["fields"]["SPLIT_MODE"] == "layer"
          and o["fields"]["THREADS"] == "8" and len(o["fields"]["FIT_TARGET"].split(",")) == 2,
          f"не влезает: эта карта доверху, другая, остаток в RAM; DEVICE пуст — это все карты; часть в RAM считает процессор всеми ядрами (получено {o['shares']}, {o['fields']['THREADS']})")
    check(m["other"]["shares"]["0"] == 5.75 and m["other"]["shares"]["1"] == 29.75, "сброс на другую карту: она первая, но влезает столько же")
    r = m["ram"]
    check(r == {"how": "ram", "shares": None, "fields": {"N_GPU_LAYERS": "0", "DEVICE": "", "SPLIT_MODE": "", "TENSOR_SPLIT": "", "MAIN_GPU": "", "THREADS": "8", "THREADS_BATCH": "8", "FIT_TARGET": ""}},
          "в RAM: те же поля, что пишет плитка CPU формы, и запас карт снят")
    check(m["noCard"] == {"refused": "machineMoveFixed"}, "negative: карты такой нет — отказ, не догадка")
    u = m["unknownSize"]
    check(u["how"] == "spread" and u["fields"]["DEVICE"] == "CUDA1", "boundary: размер не известен — на эту карту, без расчёта долей")
    n = m["noModel"]
    check(n["how"] == "spread" and n["fields"]["N_GPU_LAYERS"] == "auto" and n["fields"]["FIT"] == "1" and n["fields"]["FIT_TARGET"].isdigit() and "THREADS" in n["fields"],
          "заголовок модели не известен — поля те же, путь spread, запас по долям")
    t = m["tensor"]
    check(t["fields"]["SPLIT_MODE"] == "tensor" and t["fields"]["TENSOR_SPLIT"] != "" and t["fields"]["FIT_TARGET"] == "",
          "ячейка в tensor на двух картах остаётся в tensor: доли пишутся в TENSOR_SPLIT")
    check(m["tensorOne"]["fields"]["SPLIT_MODE"] == "" and m["tensorOne"]["fields"]["TENSOR_SPLIT"] == "", "boundary: на одной карте делить нечего")
    check(m["kvOff"]["fields"]["KV_OFFLOAD"] == "0", "кэш, который просили держать в RAM, там и остаётся")
    s = m["shared"]
    check(s["shares"] == {"0": 5.75, "1": 20, "ram": 36.25} and s["fields"]["FIT_TARGET"] == "256,10240",
          f"ручка: доля карты меньше — сначала на другую занятую, пока та не полна, остальное в RAM; предел карты равен доле, раз часть в RAM (получено {s['shares']}, {s['fields']['FIT_TARGET']})")
    check(m["sharedAll"]["shares"] == {"0": 5.75, "1": 24.25, "ram": 0} and m["sharedAll"]["fields"]["THREADS"] == "1",
          f"ручка RAM в ноль: всё на картах, потоков снова один (получено {m['sharedAll']['shares']})")
    check(m["sharedFloor"]["shares"]["ram"] == 4.5, "boundary: на карты всё не влезет — в RAM остаётся то, что им некуда деть")
    check(m["sharedOff"]["fields"]["DEVICE"] == "CUDA0" and m["sharedOff"]["shares"]["1"] == 0, "карта в ноль выходит из DEVICE")
    check(m["sharedNone"]["how"] == "ram", "ничего на картах — это ячейка на процессоре")
    p = m["pinned"]
    check(p == {"how": "free", "fields": {"ENV": "A=1\nB=2\nCUDA_VISIBLE_DEVICES=1"}}, "сервер одной карты: закрепление в ENV, прежняя карта снята, чужие строки целы, способ свой (Strata: free)")
    check(m["pinnedCard"] == {"how": "card", "fields": {"ENV": "CUDA_VISIBLE_DEVICES=0"}}, "способ по умолчанию — card")
    check(m["pinnedRam"] == {"how": "ram", "fields": {"ENV": "A=1\nTTS_DEVICE=cpu\nCUDA_VISIBLE_DEVICES="}}, "умеет процессор — ENV говорит «без карты»")
    check(m["pinnedNoRam"] == {"refused": "machineMoveNeedsCard"}, "negative: не умеет — отказ")
    check(m["pinnedBack"]["fields"]["ENV"] == "CUDA_VISIBLE_DEVICES=1", "с процессора обратно на карту: «TTS_DEVICE=cpu» не остаётся, иначе ячейка так и считала бы на процессоре")
    check(m["cpuOnly"] == {"refused": "machineMoveCpuOnly"}, "negative: раннер только для процессора на карту — отказ")
    v = m["vllm"]
    check(v["how"] == "asks" and v["fields"] == {"ENV": "X=1\nCUDA_VISIBLE_DEVICES=1", "CPU_OFFLOAD_GB": ""} and v["asks"] == [{"index": "X=1\nCUDA_VISIBLE_DEVICES=1", "mib": 1}] and v["over"] is False and v["ridesGb"] == 0,
          f"vLLM: закрепление, и его доля считается заново для новой строки ENV; влезает — всё на карте (получено {v})")
    big = m["vllmBig"]
    check(big["fields"]["CPU_OFFLOAD_GB"] == "12" and big["over"] is False and big["ridesGb"] == 12, "vLLM, веса больше доли карты: сколько нужно остаётся в RAM: иначе он не запустится, а план это скажет")
    check(m["vllmOwn"]["fields"]["CPU_OFFLOAD_GB"] == "20" and m["vllmSmall"]["fields"]["CPU_OFFLOAD_GB"] == "5", "negative: то, что оставил оператор, не отбирается: ни меньше нужного, ни при большой карте")
    check(m["vllmSize"] == [True, False, False] and m["llamaSets"] == [True, True], "ручка у vLLM только на RAM: доля карты — его GPU_MEMORY_UTILIZATION; у llama.cpp — везде")
    check(m["vllmSizable"] == [True, False, False], "negative: tensor-parallel и ячейка, чью долю не посчитать, — без ручки")
    check([x["CPU_OFFLOAD_GB"] for x in m["vllmShare"]] == ["10", "10.5", "", "", "30", ""] and all(x["ENV"] == "A=1" for x in m["vllmShare"]),
          f"ручка: по полгигабайта; 0, минус и не число — пусто; не больше весов; закрепление на месте (получено {m['vllmShare']})")
    check(m["vllmShareRoom"] == "40", "не больше, чем свободно в RAM: шаг не выносит за предел")
    check(m["vllmShareBlind"] == "100", "negative: машина не сказала, сколько в RAM свободно: не ноль, а не ограничено")
    check(m["vllmShareRidesOver"]["ridesGb"] == 6 and m["vllmShareRidesOver"]["how"] == "asks", "ручка отдаёт тот же план, что и бросок")
    check(m["vllmRam"] == {"refused": "machineMoveNeedsCard"} and m["vllmParallel"] == {"refused": "machineMoveParallel"}, "negative: vLLM в RAM и tensor-parallel — отказ по имени")
    check(m["engine"] == {"refused": "machineMoveFixed"} and m["none"] == {"refused": "machineMoveFixed"}, "negative: ячейка движка и ячейка без сведений — отказ, а не догадка")


def section_plan(got):
    print("план:")
    p = got["plan"]
    check(p["offFacts"] is False and p["key"] == "" and p["leaving"] == [], "negative: плана нет — никто не уходит, ключ пуст")
    check(p["on"] is True and p["leavingOn"] == ["22007", "22020"], "уйдут те, кто уступает, и сама ячейка, если её переносят")
    check(p["facts"]["how"] == "plan" and p["facts"]["fields"] == {"DEVICE": "CUDA1", "FIT_TARGET": "1", "ENV": ""} and p["facts"]["asks"] == ["was"] and p["facts"]["bytes"] == 1,
          "сведения глазами плана: способ и поля подменены, чего нет в способе (THREADS) не добавлено, остальное как было")
    check(p["factsAsks"]["asks"] == ["new"], "доля vLLM — новая, когда план её назвал")
    check(p["changes"] == ["DEVICE=CUDA1", "THREADS=1"], "что поменяется: только то, что отличается от сохранённого")
    check(p["changesNone"] == [], "negative: совпало — менять нечего")
    check(p["changesEmpty"] == ["ENV=CUDA_VISIBLE_DEVICES=1 A=2", 'DEVICE=""'], "многострочное значение в одну строку, пустое — видно, что пустое")
    check(p["cleared"] == [False, "", None, ""] and p["restored"] == [True, True], "снять и вернуть — то же самое")
    v = p["valid"]
    check(v["standing"] is True and v["movedHolds"] is True and v["evictHolds"] is True, "план в силе: стоящая к запуску, работающая к переносу, уступающая ещё держит место")
    check(v["startedSince"] is False and v["movedStopped"] is False and v["gone"] is False and v["evictLeft"] is False and v["evictGone"] is False,
          "negative: ячейка запустилась, остановилась, исчезла; уступающая уже ушла — план больше ничего не значит")
    check(v["busy"] is True, "пока запуск его выполняет, план его и переносимая уже остановленная его не отменяет")


def section_lean(got):
    print("панель едет за указателем:")
    l = got["lean"]
    check(l["middle"] == 0 and l["topEdge"] == -1 and l["halfTop"] == -0.5 and l["bottomEdge"] == 1 and l["halfBottom"] == 0.5,
          "у верхнего края вверх, у нижнего вниз, чем ближе, тем быстрее, в середине стоит")
    check(l["past"] == [0, 1], "над панелью указатель на стойке: панель стоит; negative: за нижним краем не быстрее предела")
    check(l["low"] == 0, "negative: панель ниже двух зон краёв не едет: у неё нет середины, и она дёргалась бы от любого движения")
    d = got["drag"]
    check(d["leanMiddle"] == {"waiting": 1, "top": 300} and d["leanMiddleRan"] == {"waiting": 0, "top": 300},
          "указатель в середине панели: кадр проходит, панель стоит, новых кадров нет")
    check(d["leanOneFrame"] == 1, "negative: сколько бы указатель ни двигался, ждёт один кадр")
    check(d["leanMoved"]["top"] == 283 and d["leanMoved"]["waiting"] == 1, "указатель у верхнего края: панель поехала вверх, и следующий кадр ждёт без движения указателя")
    check(d["leanMoved"]["on"] is True and d["leanMoved"]["device"] == "CUDA1",
          "панель поехала — то, что под указателем, прочитано снова: стойка выехала под него, и план нарисован")
    check(d["leanAtEnd"] == {"top": 0, "waiting": 0}, "negative: панель дошла до конца — кадры кончились")
    check(d["leanAfterEnd"]["top"] == 200 and d["leanAfterEnd"]["waiting"] == 0, "negative: кадр после конца перетаскивания панель не двигает")
    check(d["leanDown"]["top"] == 216 and d["leanDown"]["waiting"] == 1, "указатель у нижнего края: панель едет вниз")
    check(d["leanNoPane"] == {"top": 216, "waiting": 0}, "negative: панели на странице нет — кадр молчит и не падает")


def section_drag(got):
    print("указатель:")
    d = got["drag"]
    check(d["binds"] == 1, "negative: второй bind ничего не добавляет")
    s = d["still"]
    check(s["on"] is False and s["busy"] is False and s["swallowed"] is False and s["log"] == [], "нажатие без движения — обычный клик: плана нет, клик проходит")
    for key, words in (("noLaunch", "ячейка без запуска"), ("onItsWay", "ячейка в пути"), ("noFacts", "ячейка без сведений"), ("rightButton", "правая кнопка"), ("rating", "кнопка оценки на карточке")):
        check(d[key] == [False, False], f"negative: {words} не тащится")
    du = d["during"]
    check(du["on"] and du["port"] == "22020" and du["device"] == "CUDA1" and du["dragging"] is True and du["busy"] is True, "над картой: план уже нарисован, доска его не перерисует")
    check(du["tag"] == "Hermes" and du["tagAt"] == "translate(314px, 188px)" and du["cls"] == ["machine-dragging"] and du["drop"] == ["1", True], "ярлык у указателя, полоса подсвечена")
    check(d["samePlace"] == du["patches"], "negative: то же место под указателем — без перерисовки")
    check(d["left"]["on"] is False, "ушёл с полосы — плана снова нет, как было")
    dr = d["dropped"]
    check(dr["on"] and dr["port"] == "22020" and dr["chosen"] == "22020" and dr["dragging"] is False and dr["busy"] is False, "отпустил на карте: план остался, ячейка выбрана")
    check(dr["tagGone"] is True and dr["cls"] == [] and dr["drop"] == "", "ярлык и подсветка убраны")
    check(dr["swallowed"] is True and dr["next"] is False, "клик в конце перетаскивания не выбор; следующий — обычный")
    check(dr["log"] == [["choose", "22020"], ["bring", "22020"]], "план лёг: ячейка выбрана, её строка приехала в вид: там его слова и кнопки; negative: ни остановки, ни сообщений")
    check(d["nowhere"]["same"] is True and d["nowhere"]["chosen"] == "" and d["nowhere"]["log"] == [], "отпустил мимо: прежний план на месте, выбор не менялся")
    check(d["escape"] == {"same": True, "busy": False, "dragging": False, "cls": []}, "Escape: как будто не брал")
    check(d["cancel"] == {"same": True, "busy": False} and d["noButtons"] == {"same": True, "busy": False}, "указатель потерян, кнопка отпущена вне окна: тоже")
    check(d["refusedOver"] == [False, "ram", False], "над местом, где нельзя: полоса красная, плана нет")
    r = d["refused"]
    check(r["on"] is False and r["log"] == [["notify", "this runner computes on a card only"]], "отпустил там: причина сказана, плана нет")
    m = d["moved"]
    check(m["on"] and m["moved"] is True and m["device"] == "CUDA1" and m["log"] == [["choose", "22007"], ["bring", "22007"]], "работающая на другую карту: план переноса")
    check(d["benched"]["on"] is False and d["benched"]["log"] == [["stop", "22007", "pressed"]],
          f"работающая на список моделей: её собственный Stop, и защита от клика конца перетаскивания его не съела (получено {d['benched']['log']})")
    check(d["benchedAtOnce"] == 0, "defect-history (1.3.695, стенд): Stop нажимается после защиты: нажатый сразу, он был съеден, и перетаскивание вниз ничего не делало")
    check(d["benchedStanding"]["on"] is False and d["benchedStanding"]["log"] == [], "negative: стоящая на список — ничего")
    check(d["ownButton"] == [False, False], "negative: нажатие на «Окно ячейки», «Запустить» или «Остановить» в строке — перетаскивание не начинается")
    check(d["fromRow"] == [True, True, "22020"], "строку ячейки тащат наверх, на полосу, как тащили карточку: план лёг")
    check(d["taken"] == ["22020", None, None, None, None], "что берёт нажатие: строка или блок; negative: своя кнопка внутри, оценка, ничего — не берут")
    check(d["fitsBlock"]["evict"] == [] and d["fitsBlock"]["on"], "модель влезает — блок под указателем не трогает")
    check(d["takesBlock"]["evict"] == ["22007"], "не влезает, отпущена на блоке — занимает его место")
    check(d["ownBlock"]["evict"] == [], "negative: на собственном блоке уступать некому")
    check(d["gripBusy"] is True and d["gripDone"] is False, "ручка в руке: доска не перерисует")
    g = d["grip"]
    check(g["before"]["1"] != g["after"]["1"] and g["after"]["1"] == 16, f"ручка на середине полосы в 32 ГБ: 16 ГБ (получено {g['after']})")
    check(d["gripFrom"] == 8, "доля — то, что от начала куска: 16-й гигабайт бруска при начале на 8-м — 8 ГБ")
    k = d["keys"]
    check(k["right"] is True and k["afterRight"] == 0.5 and k["left"] is True and k["afterLeft"] == 0 and k["other"] is False and k["focused"] == 2,
          "стрелки двигают на 0,5 ГБ, фокус остаётся на ручке; другие клавиши не её")
    check(d["gripFresh"]["on"] is True and d["gripFresh"]["port"] == "22020" and d["gripFresh"]["shares"]["1"] == 8,
          f"плана ещё нет: он делается из того, куда ячейка легла бы сейчас (получено {d['gripFresh']})")
    check(d["gripPinned"] is False and d["gripNone"] is False, "negative: у сервера одной карты и без выбранной ячейки ручка ничего не делает")
    check(d["otherPage"] == [False, False], "negative: не на странице машины — ничего")
    check(d["place"]["on"] and d["place"]["device"] == "CUDA1" and d["place"]["moved"] is False and d["place"]["log"] == [["choose", "22020"], ["bring", "22020"]], "кнопка панели: тот же план без указателя, ячейка выбрана")
    check(d["placeMoved"]["moved"] is True, "работающая — план переноса")
    check(d["placeRefused"] == {"on": False, "log": [["notify", "this runner computes on a card only"]]}, "negative: нельзя — сказано, плана нет")
    check(d["placeUnknown"] == {"on": False, "log": []}, "negative: ячейки нет в сведениях — ничего")


def section_start(got):
    print("запуск:")
    s = got["start"]
    plain = s["plain"]["log"]
    check([x[0] for x in plain] == ["save", "start", "phase"] and s["plain"]["done"] is True and plain[0][1] == {"hostId": "box", "port": 22020, "cacheModels": True,
                                                                         "config": {"MODEL_FILE": "m.gguf", "DEVICE": "CUDA1", "THREADS": "8", "FIT_TARGET": "1"}},
          "сохраняет весь конфиг с полями плана и запускает; negative: другие поля на месте, никого не останавливает")
    e = s["evict"]["log"]
    check([x[:3] for x in e if x[0] == "stop"] == [["stop", "box", "22007"], ["stop", "box", "22008"]] and [x[0] for x in e][-3:] == ["save", "start", "phase"]
          and [x[2] for x in e if x[0] == "phase"] == ["running", "stopping", "stopped", "stopped", "starting"] and s["evict"]["ticks"] == 2,
          "сначала останавливает уступающих, ждёт, пока отпустят память, и только потом сохраняет и запускает")
    check([x[0] for x in s["moved"]["log"]][0] == "stop" and s["moved"]["log"][0][2] == "22020" and [x[0] for x in s["moved"]["log"]][-3:] == ["save", "start", "phase"], "перенос: сама ячейка останавливается первой")
    check(s["stuck"].get("error") == ":22007 did not stop in two minutes" and "save" not in [x[0] for x in s["stuck"]["log"]], "negative: не отпустила за две минуты — сказано по имени, настройки не тронуты")
    check(s["failSave"].get("error") == "refused" and "start" not in [x[0] for x in s["failSave"]["log"]], "negative: контроллер отказал в сохранении — не запускается")
    check(s["fits"] == [True, True, True, True, True, True, False, False, False], "что значит «влезает, никого не трогая»: веса vLLM в RAM тоже; negative: перелив llama.cpp — повод занять чужое место")
    check(s["letGo"] == [True, True, True, True, True, False, False, False, False], "что значит «отпустила память»")
    check(s["stands"] == [True, False, True, True, True, False, False, False, False], "что значит «стоит, ничего не просили»: ошибка — уже не это")
    rs = s["refusedStart"]
    check(rs["done"] is False and [x[0] for x in rs["log"] if x[0] != "phase"] == ["stop", "stop", "save", "start"] and rs["log"][-1][0] == "start",
          "defect-history (1.3.695, стенд): старт отказан: run говорит «не вышло» и не ждёт старта, которого не будет")
    check(rs["leaving"] == [] and rs["moved"] is False, "отпустившие отпустили: план после отказа — на ячейку, которая стоит, а не на перенос работающей")
    rf = s["refusedStop"]
    check(rf["done"] is False and [x[0] for x in rf["log"]] == ["stop"], "negative: отказ в остановке: дальше никого не трогает, ничего не сохраняет")
    un = s["unseen"]
    check(un["done"] is True and [x[0] for x in un["log"]].count("phase") == 4 and un["ticks"] == 3,
          "старт так и не показан: подождали SEEN_MS (шагами) и отпустили; не вечно")
    check([x[2] for x in s["seenError"]["log"] if x[0] == "phase"] == ["error"] and s["seenError"]["ticks"] == 0, "старт упал и это видно: сразу, не ждём SEEN_MS")
    pl = got["planLife"]
    check(pl["during"] == [True, True, ["22007", "22020"]], "begin: запуск идёт, машина для рисунка у плана")
    check(pl["gone"] == [[], False, True], "letGone: уступавших больше нет, план жив")
    check(pl["after"] == [False, None, True], "end: план снова у оператора, рисуется по живой машине")
    check(pl["cleared"] == [False, None], "clear снимает и это")
    b = got["buttons"]
    check(b["binds"] == 1, "negative: второй bind ничего не добавляет")
    check(b["ok"] == ["go 22020?", "redraw", "save", "start", "redraw"] and b["on"] is False, "кнопка: вопрос, сохранить, запустить; план снят")
    check(b["declined"] == [["go 22020?"], True, False], "negative: ответил «нет» — ничего, план на месте")
    check(b["failed"] == [["go 22020?", "redraw", "save", "said refused", "redraw"], True, False], "negative: отказ сказан, план на месте, можно повторить")
    check(b["refused"] == [["go 22020?", "redraw", "save", "start", "redraw"], True, False, None],
          "defect-history (1.3.695, стенд): запуск отказан, причину сказал act: план на месте, кнопка снова жива; он исчезал молча с уже изменённым конфигом")
    check(b["rooms"][-1] == {"shown": "22020"}, "план держит машину, какой её показали, пока запуск идёт")
    check(b["whileBusy"] == [], "negative: идёт запуск — второго не начать")
    check(b["cancel"] == [["redraw"], False], "Отмена снимает план и рисует заново")
    check(b["noPlan"] == [] and b["other"] == [], "negative: без плана и по чужой кнопке — ничего")


def main():
    node = find_node()
    if node is None:
        print("js machine-plan: SKIPPED — node не найден")
        return 0
    probe = ROOT / "scripts" / ".probe_machine_plan.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "i18n", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js machine-plan: FAILED — харнесс не отработал")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    section_room(got)
    section_shares(got)
    section_moves(got)
    section_plan(got)
    section_drag(got)
    section_lean(got)
    section_start(got)
    if _fail:
        print(f"\njs machine-plan FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  -", msg)
        return 1
    print("\njs machine-plan OK: машина после ухода, доли, ходы по семьям раннеров, план, указатель, запуск — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
