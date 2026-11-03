#!/usr/bin/env python3
"""Value snapshot: the head of a machine's page (static/js/machine-head.js) — variant В «Карта памяти» (1.3.632; its cells in the list of models, Н1, 2026-11-02).

The owner, 2026-10-25: the machine's page is variant В of the redesign. Its head is the passport with, in the same line, what the
machine does now, its "⋯" of the rare and the irreversible and Add model; under it the map of where its memory goes — a lane per
card and one for the RAM, every cell that holds memory a block of its measured share in a colour of its own, named inside — the
cells on their way under the lanes, and the list of models with its cells under the map (scripts/test_js_machine_models.py pins the list;
here, what a cell says in it). A click on a block, a chip or a cell's row chooses the cell: its row says what it does and holds, and gives
its window, its Start or Stop and the places it can go (the strip under the rack went into the row, the owner, 2026-11-02); a chosen stopped
cell is drawn dashed on the lanes where it would go. Part 2 (the
owner, the same day): where it would go is estimated by its size first — its files, or what its runner takes — and said so ("without the
cache"); the exact plan comes later.

Pinned by value, each claim with its negative:
  * a card's lane: the cells that hold it by their measured share, in their colours, named; what else holds it hatched, by name where
    the scout names it; the card, its size and temperature beside the label; how much is free; a stopped cell drawn nowhere, a cell
    warming up drawn; the chosen cell's block ringed;
  * a lane whose size the scout does not report draws no bar — an empty one would read as a free card — and says why;
  * the RAM's lane: the cells that hold no card, by their RSS, never past what the machine says it uses; a cell on a card not drawn
    there; a running cell nobody measured named under the lanes, choosable — not missing from the map;
  * where a stopped cell would go (CellFit), a way per runner: llama.cpp over its DEVICE cards by the room past its --fit-target
    margin and the rest to RAM, a split set by hand on the cards or not at all, a hand-set layer count not guessed; a one-card
    runner on the card its ENV pins, whole or not at all (to RAM when it picks its device itself); Strata on its card's free room
    by its floor and reserve; vLLM by its share of each card; a CPU cell in RAM; unknown — never a guess — when a size, a card or
    the RAM is not said;
  * the cells in the list of models: every cell of the machine (1.3.659: the bench that stood there held the standing ones, and a cell
    started from it left it) — the rule's order the working ones first, then the ones on their way, then the standing ones, the largest
    first by what each would take, the unweighed last; a working one says what it holds and that it runs, loads its weights or is broken;
    one on its way what it does, the copy's figures included; a standing one what it weighs and by what, and where it would go; a failed
    one says so with its reason, a port with no model says so; pills of the works with their counts narrow the list, and a work none of
    its cells does narrows nothing; a machine with no cells has no pills;
  * the pictures at the left of the lanes: a card at each card's, a stick at the RAM's, one box, no taller than a lane, also with six cards;
  * the dashed block of the chosen stopped cell on the lanes it would take; none for a running cell, none where it would not go;
  * the cells on their way named under the lanes with what they do — the copy's figures, stopping, starting;
  * a cell's row: what the strip under the rack used to say. Its last line is there for every cell and shown for the chosen one, with nothing
    chosen for none, and no strip says to choose; a cell's window only when the board drew it one; Stop for a cell that runs or is
    on its way, Start for one that stands, each with the attributes the board binds by, closed and saying why when it cannot act; the
    trouble of a working cell and the reason of a failed one in words;
  * the band in the head's line: bad for a silent machine, busy while a cell is on its way (with how many run), good while one runs,
    idle; Add model with the card's own attributes, shut while a cell is reserved;
  * the passport: the page's heading, the facts, the "⋯" items with the attributes the board's listeners bind by;
  * the choice (MachinePick): chosen again lets go; shown without a drawing — blocks ringed, one row's last line; the board drawn again when
    the choice puts a stopped cell's dashes on the lanes or takes them off, or when the chosen cell's window is not in the page,
    and the keyboard given back to the same block, chip or port; a click anywhere on a cell's row chooses, a click on its Window, Start or
    Stop does not; bound once;
  * the live patch: the lanes' figures moved in place while their blocks stay the same, written whole when they change; the sizes and
    verdicts of the rows as the page draws them and the band's words in place; the band drawn whole when its tone changes.

The module is loaded FOR REAL with ui-parts.js, cell-memory.js, placement.js, model-copy.js and utils.js; i18n (the English words)
is a stand-in.

Run: python3 scripts/test_js_machine_head.py
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


PROBE = r'''
import "./_js_globals.mjs";
const en = (await import("../static/js/i18n/en.js")).default;
globalThis.__stubReturns = { "i18n.t": (key, vars = {}) => String(en[key] ?? `?${key}`).replace(/\{(\w+)\}/g, (_, n) => (vars[n] === undefined ? `{${n}}` : vars[n])) };
const M = await import("../static/js/machine-head.js");
const MM = await import("../static/js/machine-models.js");
// What a chosen cell says and does is its row in the list: every cell's row of a map.
const rowsOf = (map) => map.bench().map((server) => new MM.MachineModels({ map }).launchHtml(server, "")).join("");
// The board has its state before it draws a page; the copy's figures read the model list from it (model-copy.js).
(await import("../static/js/state.js")).setState({ models: [] });
const out = { en: { silent: en.nodeScoutSilent, busy: en.shelfReserveBusy } };
const GIB = 2 ** 30;
const cell = (port, phase, extra = {}) => ({ port, phase, ...extra });
const NODE = {
  id: "box", name: "Box <A>", role: "host", online: true, platform: "linux", ip: "10.0.0.5", scoutVersion: "2.37.0",
  powerSchedule: { enabled: true, at: "23:30", daily: true },
  cpu: { loadPct: 1.2, ram: { totalGb: 60.5, usedGb: 8.8 } },
  gpus: [
    { index: 0, name: "NVIDIA GeForce RTX 3090", memoryTotalMiB: "24576", memoryUsedMiB: "12288", utilizationGpuPct: "7", temperatureC: "52", powerDrawW: "30.77" },
    { index: 1, name: "NVIDIA GeForce RTX 5090", memoryTotalMiB: "32607", memoryUsedMiB: "8200", utilizationGpuPct: "0", temperatureC: "48", powerDrawW: "23.6" },
  ],
  servers: [
    cell(22020, "running", { gpuMem: { 0: 8192, 1: 4096 }, ramBytes: 41 * GIB }),
    cell(22010, "warming", { gpuMem: { 0: 2048 }, ramBytes: 5 * GIB }),
    cell(22001, "running", { gpuMem: {}, ramBytes: 3 * GIB }),
    cell(22003, "running", { gpuMem: {}, ramBytes: null }),
    cell(22007, "stopped", { gpuMem: { 0: 9999 }, ramBytes: 9 * GIB }),
    cell(22014, "reserved"),
  ],
};
// What the board's builder says of each cell (topology-nodes.js, nodeServerCardHtml): its window's slot, its name, its stop.
const stop = (port) => `data-node-cell-stop="box" data-node-cell-port="${port}"`;
const CELLS = new Map([
  ["22020", { key: "box:22020", name: "Hermes-4-70B", stop: stop(22020), stopTitle: "Stop server", window: true }],
  ["22010", { key: "box:22010", name: "gemma-4-12B-it", stop: stop(22010), stopTitle: "Stop server", window: false }],
  ["22001", { key: "box:22001", name: "Qwen3-Embedding-0.6B", stop: stop(22001), stopTitle: "Stop server", window: true }],
  ["22003", { key: "box:22003", name: "gigaam <v3>", stop: "", stopTitle: "Not running", window: true }],
]);
// What holds a card that is no cell — topology-nodes.js's gpuOutsideOwners — as the board would say it for card 0.
const owners = (g) => (g.index === 0 ? [{ name: "Xorg", engine: "", mib: 1024 }] : []);
const map = new M.MachineMap(NODE, { owners, cells: CELLS, chosen: "22020" });
const lanes = map.lanes();
const strip = (lane) => ({ ...lane, blocks: lane.blocks.map(({ pick, ...rest }) => (pick ? { ...rest, pick: true } : rest)) });
out.holders = map.holders().map((h) => [h.server.port, h.series]);
out.card0 = strip(lanes[0]);
out.card0Pick = lanes[0].blocks.find((b) => b.port === "22020")?.pick;
out.card1 = strip(lanes[1]);
out.ram = strip(lanes[2]);
out.unplaced = map.unplaced().map((h) => h.server.port);
out.html = map.html();
out.words = ["22020", "22001", "22003", "22010"].map((p) => map.memoryWords(NODE.servers.find((s) => String(s.port) === p)));
out.zeroRss = map.memoryWords(cell(1, "running", { ramBytes: 0 }));
{ const broken = cell(1, "broken", { gpuMem: { 0: 1024 } }); out.brokenSub = [map.benchVerdict(broken).words, map.benchSize(broken)]; }
out.panels = rowsOf(map);
// A cell in trouble that holds its memory: the machine's page draws it as its window only, so its row says the trouble.
{
  const TROUBLE = new Map([
    ["22041", { key: "box:22041", name: "Swift", stop: stop(22041), stopTitle: "Stop server", window: true, crashed: 2 }],
    ["22042", { key: "box:22042", name: "Far", stop: stop(22042), stopTitle: "Stop server", window: true, unreachable: true, crashed: 1 }],
    ["22043", { key: "box:22043", name: "Calm", stop: stop(22043), stopTitle: "Stop server", window: true, crashed: 0, unreachable: false }],
  ]);
  const tnode = { ...NODE, servers: ["22041", "22042", "22043"].map((p) => cell(Number(p), "running", { gpuMem: { 0: 1024 } })) };
  const tmap = new M.MachineMap(tnode, { cells: TROUBLE, chosen: "22041" });
  out.trouble = tnode.servers.map((s) => { const said = tmap.benchVerdict(s);
    return [said.tone, said.state, said.words, tmap.benchSize(s), tmap.actionsHtml(s).includes('data-t="machine-model-window"')]; });
}
out.noChoice = rowsOf(new M.MachineMap(NODE, { cells: CELLS }));
out.staleChoice = rowsOf(new M.MachineMap(NODE, { cells: CELLS, chosen: "22999" }));
out.stoppedChoice = rowsOf(new M.MachineMap(NODE, { cells: CELLS, chosen: "22007" }));
out.unnamed = new M.MachineMap(NODE).lanes()[2].blocks.map((b) => b.name);
const seven = { servers: [1, 2, 3, 4, 5, 6, 7].map((i) => cell(22000 + i, "running")) };
out.seven = new M.MachineMap(seven).holders().map((h) => h.series);
const blind = new M.MachineMap({ gpus: [{ index: 2, name: "<b>", memoryUsedMiB: "", memoryTotalMiB: null }], cpu: {},
                                 servers: [cell(22002, "running", { gpuMem: { 2: 512 } })] });
out.blind = blind.lanes().map(strip);
out.blindHtml = blind.html();
out.blindUnplaced = blind.unplaced().map((h) => h.server.port);
const capped = new M.MachineMap({ cpu: { ram: { totalGb: 16, usedGb: 4 } }, servers: [cell(22001, "running", { ramBytes: 3 * GIB }), cell(22002, "running", { ramBytes: 3 * GIB })] });
out.capped = capped.lanes()[0].blocks.map((b) => [b.value, b.figure, b.kind || b.series]);

const band = (node) => new M.MachineBand(node, { age: () => "7 min" });
// The same machine once its warming cell has loaded: every cell that runs, runs.
const GOOD = { ...NODE, servers: NODE.servers.map((s) => (s.phase === "warming" ? { ...s, phase: "running" } : s)) };
const said = (b) => [b.tone(), b.title(), b.sub()];
out.band = {
  good: said(band(GOOD)),
  warming: said(band(NODE)),
  silent: said(band({ ...NODE, online: false })),
  coming: said(band({ ...NODE, servers: [cell(1, "downloading"), cell(2, "running")] })),
  // 1.3.657: one cell on its way is named, by the head's own name of a cell; two are counted.
  named: new M.MachineHead({ ...NODE, servers: [cell(22020, "downloading"), cell(22001, "running")] }, { cells: CELLS }).band.title(),
  two: said(band({ ...NODE, servers: [cell(1, "downloading"), cell(3, "loading"), cell(2, "running")] })),
  idle: said(band({ ...NODE, servers: [cell(1, "stopped"), cell(2, "reserved")] })),
  empty: [band({ ...NODE, servers: [cell(2, "reserved")] }).title(), band({ ...NODE, servers: [] }).title()],
  controller: band({ ...NODE, role: "controller", online: false }).tone(),
  html: band(GOOD).html(),
};

const head = new M.MachineHead(GOOD, { owners, age: () => "7 min", addTitle: "on :22030", oldScout: '<span class="node-scout-old">⚠ old</span>',
                                       cells: CELLS, chosen: "22020" });
out.head = { html: head.html(), facts: head.facts(), factsRelease: new M.MachineHead({ ...GOOD, scoutCommit: "33dbf22e" }).facts(),
             menu: head.menu(), add: head.addButton(),
             addBusy: new M.MachineHead(GOOD, { reserving: true }).addButton() };
out.noScoutMenu = new M.MachineHead({ ...NODE, role: "controller", powerSchedule: {} }).menu();

// The choice, on a page of stand-ins: blocks and rows' last lines that say what was written to them.
const pick = new M.MachinePick();
out.choose = [pick.choose("22020"), pick.chosen(22020), pick.choose(22020), pick.chosen("22020"), pick.choose(22001), pick.chosen(""),
              (pick.know("x"), pick.cells.size), (pick.know(CELLS), pick.cells.size)];
const el = (dataset) => {
  const e = { dataset, on: new Set(), attrs: {}, hidden: false, setAttribute(k, v) { this.attrs[k] = v; } };
  e.classList = { toggle: (c, on) => (on ? e.on.add(c) : e.on.delete(c)) };
  return e;
};
const blocks = ["22020", "22001", "22001"].map((p) => el({ machinePick: p }));
const panels = ["22020", "22001"].map((p) => el({ machinePanel: p }));
const page = { querySelectorAll: (sel) => (sel === "[data-machine-pick]" ? blocks : sel === "[data-machine-panel]" ? panels : []) };
const seen = () => ({ on: blocks.map((b) => [b.on.has("is-on"), b.attrs["aria-pressed"]]), shown: panels.filter((p) => !p.hidden).map((p) => p.dataset.machinePanel) });
pick.port = "";
pick.choose("22001"); pick.show(page); out.show = { one: seen() };
pick.choose("22001"); pick.show(page); out.show.letGo = seen();
pick.choose("22007"); pick.show(page); out.show.stale = seen();
// A cell's row is no button: it is ringed with its port, and only the port says it is pressed. The list of models hears of each choice shown.
{
  const rowLike = { ...el({ machinePick: "22001", t: "machine-model-launch" }), hasAttribute: () => false };
  rowLike.classList = { toggle: (c, on) => (on ? rowLike.on.add(c) : rowLike.on.delete(c)) };
  rowLike.setAttribute = (k, v) => { rowLike.attrs[k] = v; };
  const portLike = { ...el({ machinePick: "22001", t: "machine-model-cell" }), hasAttribute: () => true };
  portLike.classList = { toggle: (c, on) => (on ? portLike.on.add(c) : portLike.on.delete(c)) };
  portLike.setAttribute = (k, v) => { portLike.attrs[k] = v; };
  const heard = [];
  const rp = new M.MachinePick();
  rp.listed = (root) => heard.push(root.name);
  rp.port = "22001";
  rp.show({ name: "the page", querySelectorAll: (sel) => (sel === "[data-machine-pick]" ? [rowLike, portLike] : []) });
  out.show.row = { row: [rowLike.on.has("is-on"), rowLike.attrs["aria-pressed"] ?? null], port: [portLike.on.has("is-on"), portLike.attrs["aria-pressed"]], heard };
}
// Bound on a document: a click on a block chooses, and shows the choice — or draws the board when the cell's window is not in it.
const listeners = [];
let redraws = 0;
const slots = new Set(["box:22020"]);
const focused = [];
const doc = {
  addEventListener: (type, fn) => listeners.push([type, fn]),
  querySelector: (sel) => {
    if ([...slots].some((k) => sel === `.fold-slot[data-fold-key="${k}"]`)) return {};
    const m = sel.match(/^\[data-t="([^"]+)"\]\[data-machine-pick="(\d+)"\]$/);
    return m ? { focus: () => focused.push(`${m[1]}:${m[2]}`) } : null;
  },
  querySelectorAll: () => [],
};
const bound = new M.MachinePick();
bound.know(CELLS);
bound.bind(doc, { redraw: () => { redraws += 1; } });
bound.bind(doc, { redraw: () => { redraws += 100; } });
const click = (port, hook = "machine-map-block") => listeners.forEach(([, fn]) => fn({ target: { closest: (sel) => (sel === "[data-machine-pick]" && port
  ? { dataset: { machinePick: port, t: hook } } : null) }, preventDefault() {} }));
click("22020"); const afterShown = [bound.port, redraws];
click("22001"); const afterHidden = [bound.port, redraws, [...focused]];
click("22010"); const afterFull = [bound.port, redraws];
click(null); const afterMiss = [bound.port, redraws];
out.bind = { listeners: listeners.length, afterShown, afterHidden, afterFull, afterMiss };
{
  const charts = [], chartListeners = [];
  const cp = new M.MachinePick();
  cp.bind({ addEventListener: (type, fn) => { if (type === "click") chartListeners.push(fn); }, querySelector: () => null, querySelectorAll: () => [] }, { openChart: (key) => charts.push(key) });
  chartListeners[0]({ preventDefault() {}, target: { closest: (sel) => (sel === "[data-machine-chart]" || sel === "[data-machine-pick]" ? { dataset: { machineChart: "node:h:gpu", machinePick: "22020" } } : null) } });
  out.chartClick = [charts, cp.port];
}
// The pointer on a holder: its pieces lit on every lane, its line drawn, the rest stepped back.
{
  const lightEl = (owner) => { const e = { dataset: { laneOwner: owner }, on: new Set() }; e.classList = { toggle: (c, on) => (on ? e.on.add(c) : e.on.delete(c)) }; return e; };
  const owned = ["22020", "22001", "22020"].map(lightEl);
  const rack = { dataset: {}, on: new Set(), querySelectorAll: () => owned };
  rack.classList = { toggle: (c, on) => (on ? rack.on.add(c) : rack.on.delete(c)) };
  const lightRoot = { querySelector: (sel) => (sel === ".machine-rack" ? rack : null) };
  const lp = new M.MachinePick();
  const state = () => [rack.dataset.laneLit, rack.on.has("is-lighting"), owned.map((e) => e.on.has("is-lit"))];
  lp.light(lightRoot, "22020");
  const lit = state();
  let touched = 0;
  rack.querySelectorAll = () => { touched += 1; return owned; };
  lp.light(lightRoot, "22020");
  const again = touched;
  lp.light(lightRoot, "22001");
  const other = state();
  lp.light(lightRoot, "");
  const off = state();
  lp.light({ querySelector: () => null }, "22020");
  // The listeners: a pointer on a holder and off it, and none during a drag.
  const lightListeners = {};
  const bodyCls = new Set();
  const ldoc = { body: { classList: { contains: (c) => bodyCls.has(c) } }, addEventListener: (type, fn) => { lightListeners[type] = fn; }, querySelector: lightRoot.querySelector };
  const lb = new M.MachinePick();
  lb.bindLight(ldoc);
  const over = (owner) => lightListeners.mouseover({ target: { closest: () => (owner ? { dataset: { laneOwner: owner } } : null) } });
  over("22001");
  const onOwner = rack.dataset.laneLit;
  over("");
  const offOwner = rack.dataset.laneLit;
  over("22001");
  lightListeners.mouseout({ relatedTarget: {} });
  const stays = rack.dataset.laneLit;
  lightListeners.mouseout({ relatedTarget: null });
  const leftPage = rack.dataset.laneLit;
  bodyCls.add("machine-dragging");
  over("22020");
  out.light = { lit, again, other, off, onOwner, offOwner, stays, leftPage, dragging: rack.dataset.laneLit };
  // A chosen cell's line is drawn, without a drawing of the board.
  const lines = ["22020", "22001"].map(lightEl);
  const sp = new M.MachinePick();
  sp.port = "22001";
  sp.show({ querySelectorAll: (sel) => (sel === "i[data-lane-owner]" ? lines : []) });
  out.light.shown = lines.map((e) => e.on.has("is-shown"));
}
// The chosen cell's row is brought into sight, by as little as it takes; letting the cell go brings nothing.
{
  const asked = [];
  const rowDoc = { querySelector: (sel) => (sel === '.machine-model-launch[data-machine-pick="22020"]' ? { scrollIntoView: (how) => asked.push(how) } : null) };
  bound.bringRow(rowDoc, "22020");
  bound.bringRow(rowDoc, "");
  bound.bringRow({}, "22020");
  out.bind.brought = asked;
}

// The live patch, on elements that say what was written to them.
class El {
  constructor(attrs = {}) { this.dataset = attrs; this.writes = []; this.kids = {}; this._inner = ""; this._outer = null; this._text = ""; }
  get innerHTML() { return this._inner; }
  set innerHTML(v) { this._inner = v; this.writes.push("inner"); }
  get outerHTML() { return this._outer; }
  set outerHTML(v) { this._outer = v; this.writes.push("outer"); }
  get textContent() { return this._text; }
  set textContent(v) { this._text = v; this.writes.push("text"); }
  querySelector(sel) { return this.kids[sel] || null; }
}
const live = new M.MachineHeadLive();
const lanesEl = new El();
const bandEl = new El({ tState: "good" });
const titleEl = new El();
titleEl._text = "old title";
bandEl.kids[".ui-band-title"] = titleEl;
const rowSize = new El();
rowSize._text = "9.9 GB on the cards";
const factsEl = new El();
factsEl._text = "host · linux · 10.0.0.5 · scout an-old-release";
const root = { querySelector: (sel) => ({ "[data-machine-map]": lanesEl, "[data-machine-band]": bandEl, ".ui-win-facts": factsEl,
                                          '[data-machine-bench-size="22020"]': rowSize })[sel] || null };
live.patch(root, head);
live.patch(root, head);
// Copies, not the live arrays: the next patch writes to the same ones.
out.live = { mapWrites: lanesEl.writes.length, bandWrites: [...bandEl.writes], title: titleEl.textContent, rowSize: rowSize.textContent,
             rowSizeWrites: rowSize.writes.length, facts: factsEl.textContent, factsWrites: factsEl.writes.length };
bandEl.dataset.tState = "idle";
live.patch(root, head);
out.live.toneChange = [...bandEl.writes];
out.live.empty = (() => { try { live.patch({ querySelector: () => null }, head); return "quiet"; } catch (e) { return String(e); } })();

// The lanes drawn as the page has them — each block an element that says what was written to it — patched by a head whose figures
// moved (the RAM's use), and by heads whose blocks changed (a cell began to hold memory; a cell got measured).
const UP = await import("../static/js/ui-parts.js");
const drawn = (h) => {
  const writes = { map: 0, inner: 0 };
  const lanes = h.map.lanes().map((lane) => {
    const blocks = (UP.Meter.cut(lane.total, lane.blocks) || []).map(({ part, width }) => {
      const b = { dataset: part.port ? { machinePick: part.port } : {}, cls: new Set([`ui-lane-blk--${part.kind || "s"}`]), attrs: {},
                  style: { width: `${width}%` }, title: String(part.title || ""), _inner: UP.Lane.inner(part, width, lane.rack ? lane.rack.bar : null) };
      if (part.on) b.cls.add("is-on");
      b.classList = { contains: (c) => b.cls.has(c), toggle: (c, on) => (on ? b.cls.add(c) : b.cls.delete(c)) };
      b.setAttribute = (k, v) => { b.attrs[k] = v; };
      Object.defineProperty(b, "innerHTML", { get: () => b._inner, set: (v) => { b._inner = v; writes.inner += 1; } });
      return b;
    });
    const bar = lane.total ? { querySelectorAll: () => blocks } : null;
    const free = { textContent: lane.free }, side = { textContent: lane.side };
    const leads = (lane.links || []).filter((l) => l.here).map(() => { const props = {}; return { props, style: { setProperty: (k, v) => { props[k] = v; } } }; });
    return { blocks, leads, querySelector: (sel) => ({ ".ui-lane-bar": bar, ".ui-lane-free": free, ".ui-lane-side": side })[sel] || null,
             querySelectorAll: (sel) => (sel === ".ui-lane-blk" ? blocks : sel === ".ui-lane-lead" ? leads : []), free };
  });
  // The list beside the lanes, as drawn: a row per holder.
  const rows = M.MachineRack.legend(h.map.lanes()).map((r) => {
    const figure = { textContent: r.figure }, where = { textContent: r.where }, speed = { textContent: r.speed };
    const row = { dataset: r.owner ? { laneOwner: r.owner } : {}, title: r.title, attrs: {}, cls: new Set(r.on ? ["is-on"] : []), figure, where, speed,
                  querySelector: (sel) => (sel === ".ui-legend-figure" ? figure : sel === ".ui-legend-where" ? where : sel === ".ui-legend-speed" ? speed : null), setAttribute: (k, v) => { row.attrs[k] = v; } };
    row.classList = { toggle: (c, on) => (on ? row.cls.add(c) : row.cls.delete(c)) };
    return row;
  });
  const chip = (server, hook, words) => {
    const c = { dataset: { machinePick: String(server.port), t: hook }, writes: 0, _text: `${h.map.cellName(server)}${words ? ` · ${words}` : ""}` };
    Object.defineProperty(c, "textContent", { get: () => c._text, set: (v) => { c._text = v; c.writes += 1; } });
    return c;
  };
  const chips = [...h.map.unplaced().map(({ server }) => chip(server, "machine-map-unplaced-cell", "")),
                 ...h.map.coming().map((server) => chip(server, "machine-map-coming-cell", h.map.comingWords(server)))];
  const map = { writes, lanes, chips, rows, querySelectorAll: (sel) => (sel === ".ui-lane" ? lanes : sel === ".ui-legend-row" ? rows : sel === M.MachineHeadLive.CHIPS ? chips
    : sel === '[data-t="machine-map-coming-cell"]' ? chips.filter((c) => c.dataset.t === "machine-map-coming-cell") : []) };
  Object.defineProperty(map, "innerHTML", { get: () => "", set: () => { writes.map += 1; } });
  return map;
};
const headOf = (node) => new M.MachineHead(node, { owners, cells: CELLS, chosen: "22020" });
const page1 = drawn(head);
const live2 = new M.MachineHeadLive();
const at = { querySelector: (sel) => (sel === "[data-machine-map]" ? page1 : null) };
live2.patch(at, head);
const first = { ...page1.writes };
const moved = headOf({ ...GOOD, cpu: { ...GOOD.cpu, ram: { totalGb: 60.5, usedGb: 9.0 } } });
live2.patch(at, moved);
const ram = page1.lanes[2];
const ringed = () => page1.lanes[0].blocks.filter((b) => b.cls.has("is-on")).map((b) => [b.dataset.machinePick, b.attrs["aria-pressed"] ?? null]);
out.inPlace = { first, after: { ...page1.writes }, free: ram.free.textContent, system: ram.blocks[0].style.width, chosen: ringed(),
                rowOn: page1.rows.filter((n) => n.cls.has("is-on")).map((n) => [n.dataset.laneOwner, n.attrs["aria-pressed"] ?? null]) };
// A card's figures move: the list's figure and hover and where a sewn piece ends follow, and the lanes are not written whole.
const page4 = drawn(head);
const live4 = new M.MachineHeadLive();
const at4 = { querySelector: (sel) => (sel === "[data-machine-map]" ? page4 : null) };
live4.patch(at4, head);
live4.patch(at4, headOf({ ...GOOD, gpus: GOOD.gpus.map((g) => (g.index === 0 ? { ...g, memoryUsedMiB: "11264" } : g)),
                          servers: GOOD.servers.map((s) => (s.port === 22020 ? { ...s, gpuMem: { 0: 7168, 1: 4096 } } : s)) }));
live4.patch(at4, headOf({ ...GOOD, servers: GOOD.servers.map((s) => (s.port === 22020 ? { ...s, genTps: 41.2, requestsProcessing: 1 } : s)) }));
out.inPlace.speed = page4.rows.find((n) => n.dataset.laneOwner === "22020")?.speed.textContent;
live4.patch(at4, headOf({ ...GOOD, gpus: GOOD.gpus.map((g) => (g.index === 0 ? { ...g, memoryUsedMiB: "11264" } : g)),
                          servers: GOOD.servers.map((s) => (s.port === 22020 ? { ...s, gpuMem: { 0: 7168, 1: 4096 } } : s)) }));
out.inPlace.notes = { writes: page4.writes.map, figures: page4.rows.map((n) => n.figure.textContent), title: page4.rows.find((n) => n.dataset.laneOwner === "22020")?.title, lead: page4.lanes[0].leads[0]?.props["--lane-from"] };
live2.patch(at, new M.MachineHead({ ...GOOD, cpu: { ...GOOD.cpu, ram: { totalGb: 60.5, usedGb: 9.0 } } }, { owners, cells: CELLS, chosen: "" }));
out.inPlace.letGo = [ringed(), page1.lanes[0].blocks.find((b) => b.dataset.machinePick === "22020")?.attrs["aria-pressed"], page1.writes.map];
out.inPlace.rowLetGo = page1.rows.filter((n) => n.dataset.laneOwner === "22020").map((n) => [n.cls.has("is-on"), n.attrs["aria-pressed"]]);
const started = headOf({ ...GOOD, servers: GOOD.servers.map((s) => (s.port === 22007 ? { ...s, phase: "running" } : s)) });
const page2 = drawn(head);
live2.patch({ querySelector: (sel) => (sel === "[data-machine-map]" ? page2 : null) }, started);
const measured = headOf({ ...GOOD, servers: GOOD.servers.map((s) => (s.port === 22003 ? { ...s, ramBytes: GIB } : s)) });
const page3 = drawn(head);
live2.patch({ querySelector: (sel) => (sel === "[data-machine-map]" ? page3 : null) }, measured);
out.inPlace.reshaped = [page2.writes.map, page3.writes.map];

// The rack: one scale for the lanes, words beside each bar, one line sewing a cell's pieces together.
const scale = (cards, ram) => { const s = new M.RackScale(cards, ram); return [s.track, s.ramBar, s.shared, cards.map((c) => s.cardBar(c))]; };
out.scale = { machine: scale([24, 31.8], 60.5), hugeRam: scale([24], 256), smallRam: scale([24], 16), noCards: scale([], 60.5), noRam: scale([24, 32], 0),
              unknownCard: scale([0, 24], 60.5), equal: scale([32], 32), justOn: scale([24], 38.7) };
out.rack = { card0: { rack: lanes[0].rack, notes: lanes[0].notes, links: lanes[0].links },
             card1: { rack: lanes[1].rack, notes: lanes[1].notes, links: lanes[1].links },
             ram: { rack: lanes[2].rack, notes: lanes[2].notes, links: lanes[2].links },
             legend: M.MachineRack.legend(lanes),
             freeWords: [M.MachineMap.freeWords(24, 0), M.MachineMap.freeWords(24, 20), M.MachineMap.freeWords(2, 20)],
             where: [[["0"]], [["1"], ["2"], ["3"], ["4"]], [["0"], ["2"], ["3"], ["5"]], [["1"], ["ram"]], [["ram"]], []].map((ids) => M.MachineRack.whereWords(ids.map(([id]) => (id === "ram" ? { ram: true } : { cardIndex: id })))) };
{
  // A cell on the first and the last of three cards: its line passes the card it skips, with no piece and no note there.
  const three = { cpu: { ram: { totalGb: 60.5, usedGb: 8 } }, servers: [cell(22020, "running", { gpuMem: { 0: 4096, 2: 2048 } })],
                  gpus: [0, 1, 2].map((index) => ({ index, memoryTotalMiB: 8192, memoryUsedMiB: index === 1 ? 0 : 4096 })) };
  const tl = new M.MachineMap(three, { cells: CELLS }).lanes();
  out.rack.skip = tl.map((l) => [l.links, l.notes.map((n) => n.words)]);
  out.rack.skipHtml = new UP.Lane(tl[1]).html();
  // The list with a cell to come: on top of the others, its words its own; and when nothing holds anything, it says so.
  {
    const planned = { cpu: { ram: { totalGb: 60.5, usedGb: 8 } },
                      servers: [cell(22020, "running", { gpuMem: { 0: 4096 } }), cell(22001, "running", { gpuMem: { 0: 8192 } }), cell(22007, "stopped", { slotConfig: {}, modelSizeBytes: 12 * GIB })],
                      gpus: [{ index: 0, memoryTotalMiB: 24576, memoryUsedMiB: 12288 }, { index: 1, memoryTotalMiB: 24576, memoryUsedMiB: 0 }] };
    const fit = (facts) => new Map([...CELLS, ["22007", { ...(CELLS.get("22007") || {}), name: "gemma", fit: facts }]]);
    const chosen = new M.MachineMap(planned, { cells: fit({ how: "spread", bytes: 30 * GIB, source: "files", family: "llama", fields: {} }), chosen: "22007" });
    const pl = chosen.lanes();
    out.rack.planned = { rows: M.MachineRack.legend(pl).map((row) => [row.name, row.figure, row.where, row.kind || row.series, !!row.pick, row.on]), html: chosen.lanesHtml(pl),
                         lines: pl.map((l) => l.links.map((k) => [k.owner, k.slot, k.kind || "", k.shown])) };
    out.rack.emptyHtml = new M.MachineMap({ cpu: { ram: { totalGb: 8, usedGb: 1 } }, servers: [] }).lanesHtml();
    // A device's own figures on its row, as the monitor's tick will fill them; what nobody reported is a dash.
    const figures = new M.MachineMap({ id: "h1", cpu: { loadPct: 12.6, ram: { totalGb: 60.5, usedGb: 8 } }, servers: [], gpus: [{ index: 3, memoryTotalMiB: 24576, memoryUsedMiB: 6349, utilizationGpuPct: 33.6, powerDrawW: 117.72 }, { index: 4, memoryTotalMiB: 24576, memoryUsedMiB: null }] }).lanes();
    out.rack.metrics = figures.map((l) => l.metrics);
    out.rack.totals = new M.MachineMap({ id: "h1", gpus: [{ index: 0 }], servers: [] }).totalsHtml();
    out.rack.noTotals = new M.MachineMap({ id: "h1", gpus: [], servers: [] }).totalsHtml();
    // How fast a cell generates now: only while it answers a request; a held figure is no speed of now.
    out.rack.speed = [M.MachineRack.speedOf({ genTps: 38.4, requestsProcessing: 1 }), M.MachineRack.speedOf({ genTps: 38.4, requestsProcessing: 0 }), M.MachineRack.speedOf({ genTps: 0, requestsProcessing: 1 }), M.MachineRack.speedOf({})];
    const speedLanes = new M.MachineMap({ cpu: { ram: { totalGb: 60.5, usedGb: 8 } }, servers: [cell(22020, "running", { gpuMem: { 0: 4096 }, genTps: 51.6, requestsProcessing: 2 })], gpus: [{ index: 0, memoryTotalMiB: 24576, memoryUsedMiB: 4096 }] }, { cells: CELLS }).lanes();
    out.rack.speedRow = M.MachineRack.legend(speedLanes)[0].speed;
    // What is to come is the smallest here, and a running cell lies on two cards too: it still stands first, its line in the first place.
    const small = { ...planned, servers: [cell(22020, "running", { gpuMem: { 0: 4096, 1: 4096 } }), cell(22007, "stopped", { slotConfig: {}, modelSizeBytes: 2 * GIB })] };
    const smallLanes = new M.MachineMap(small, { cells: fit({ how: "spread", bytes: 2 * GIB, source: "files", family: "llama", fields: {} }), chosen: "22007" }).lanes();
    out.rack.smallPlan = { rows: M.MachineRack.legend(smallLanes).map((row) => [row.owner, row.figure]), slots: smallLanes[0].links.map((k) => [k.owner, k.slot]) };
    // A largest cell that changes: the rows change order, and the map is written whole.
    const swapA = { ...planned, servers: planned.servers.slice(0, 2) };
    const swapB = { ...swapA, servers: [cell(22020, "running", { gpuMem: { 0: 9216 } }), cell(22001, "running", { gpuMem: { 0: 4096 } })] };
    out.rack.order = [M.MachineRack.legend(new M.MachineMap(swapA, { cells: CELLS }).lanes()).map((row) => row.owner).slice(0, 2),
                      M.MachineRack.legend(new M.MachineMap(swapB, { cells: CELLS }).lanes()).map((row) => row.owner).slice(0, 2)];
    // The price of RAM, said by the cell's row now that the lane has no words: llama.cpp computes it on the processor.
    const said = (family, ramGb, cards) => { const m = new M.MachineMap(planned, { cells: new Map([["22007", { fit: { family } }]]) }); m.fit = () => ({ verdict: ramGb ? "spill" : "cards", cards, ramGb }); return m.fitSaid({ port: 22007 }); };
    out.rack.price = [said("llama", 9, [{ index: "0" }]), said("llama", 0, [{ index: "0" }]), said("vllm", 9, [{ index: "0" }]), said("llama", 9, [])];
    // And its row says it, with where the cell would go.
    { const m = new M.MachineMap(planned, { cells: new Map([["22007", { fit: { family: "llama" } }]]) }); m.fit = () => ({ verdict: "spill", cards: [{ index: "0" }], ramGb: 9 });
      out.rack.priceInRow = m.benchVerdict({ port: 22007, phase: "stopped" }).words; }
  }
  // Unmeasured lane: no bar, so no note and no line on it, and a cell does not count it among its pieces.
  const blindLanes = new M.MachineMap({ cpu: {}, servers: [cell(22020, "running", { gpuMem: { 0: 1024, 1: 1024 } })],
                                       gpus: [{ index: 0, memoryTotalMiB: 8192, memoryUsedMiB: 2048 }, { index: 1, memoryTotalMiB: null }] }, { cells: CELLS }).lanes();
  out.rack.blind = blindLanes.map((l) => [l.rack, l.notes.length, l.links.length]);
  out.rack.blindWords = blindLanes[0].notes.find((n) => n.name.startsWith(":22020"))?.words;
  out.rack.noCell = new M.MachineMap({ cpu: { ram: { totalGb: 8, usedGb: 1 } }, servers: [] }).lanes().map((l) => [l.rack, l.notes, l.links]);
  // Strata keeps its weights in RAM: its RSS is its own piece beside its card's, and neither is "a part" of the other.
  const keeps = (fit) => new M.MachineMap({ cpu: { ram: { totalGb: 60.5, usedGb: 50 } }, servers: [cell(22009, "running", { gpuMem: { 0: 30720 }, ramBytes: 39 * GIB })],
                                           gpus: [{ index: 0, memoryTotalMiB: 32768, memoryUsedMiB: 30720 }] },
                                         { cells: new Map([["22009", { name: "Strata", runner: "Strata", fit }]]) }).lanes();
  const strataLanes = keeps({ how: "free", keepsRam: true });
  out.rack.strata = strataLanes.map((l) => [l.notes.map((n) => n.words), l.blocks.filter((b) => b.port).map((b) => b.figure), l.links.length]);
  out.rack.mapped = keeps({ how: "plan", keepsRam: false }).map((l) => [l.notes.map((n) => n.words), l.blocks.filter((b) => b.port).length]);
}
// A plan in hand (machine-plan.js): the map draws the machine as the plan would leave it.
{
  const PL = await import("../static/js/machine-plan.js");
  const pnode = { id: "box", cpu: { availableCores: 8, physicalCores: 8, ram: { totalGb: 60, usedGb: 10 } },
                  gpus: [{ index: 0, name: "RTX 3090", memoryTotalMiB: 24576, memoryUsedMiB: 12288, memoryFreeMiB: 12288 }, { index: 1, name: "RTX 5090", memoryTotalMiB: 32768, memoryUsedMiB: 0, memoryFreeMiB: 32768 }],
                  servers: [cell(22007, "running", { gpuMem: { 0: 12288 }, slotConfig: { DEVICE: "CUDA0" } }), cell(22020, "stopped", { slotConfig: { DEVICE: "", THREADS: "1" } })] };
  const empty = { ENV: "", DEVICE: "", FIT_TARGET: "", TENSOR_SPLIT: "", FIT: "", N_GPU_LAYERS: "", N_CPU_MOE: "", CPU_MOE: "", KV_OFFLOAD: "" };
  const model = { weightsGb: 13, kvGb: 6, batchGb: 1, layers: 20, experts: 0, expertsGb: 0 };
  const fit = { how: "plan", family: "llama", bytes: 20 * GIB, source: "plan", model, mode: "layer", fields: empty, split: { weightsGb: 13, cacheGb: 7 } };
  const pcells = new Map([["22007", { name: "gemma", stop: "data-s", launch: "", group: "holds", runner: "llama.cpp", fit: { ...fit, bytes: 12 * GIB } }],
                          ["22020", { name: "Hermes", stop: "", launch: "data-y", group: "bench", runner: "llama.cpp", fit }]]);
  const plan = new PL.MachinePlan();
  const room = (leaving = []) => PL.MachineRoom.of(PL.MachineRoom.without(pnode, leaving));
  const lay = (port, target, opts = {}) => plan.set(port, PL.CellMove.of(pcells.get(String(port)).fit).to(target, room(opts.leaving || [])), opts);
  const drawn = () => {
    const m = new M.MachineMap(pnode, { cells: pcells, chosen: "", plan });
    const lanes = m.lanes();
    return { chosen: m.chosen, lanes: lanes.map((l) => ({ free: l.free, blocks: l.blocks.map((b) => [b.port || b.ghostOf || b.kind || "", b.kind || ""]), attrs: l.attrs,
                                                          grips: l.grips.map((g) => [g.on, g.at, g.title, g.attrs]), notes: l.notes.map((n) => n.words) })),
             panels: rowsOf(m), choice: m.bench().map((s) => m.choiceHtml(s)).join(""), bench: m.bench().map((s) => s.port), holders: m.holders().map((h) => h.server.port) };
  };
  out.planMap = { off: drawn() };
  lay(22020, "1");
  out.planMap.on = drawn();
  plan.busy = true;
  out.planMap.busy = drawn().choice;
  plan.busy = false;
  // While a start carries the plan out, it is drawn on the machine the operator was shown: the stop reaches the topology before the cards' next reading.
  plan.begin(pnode);
  const liveFit = new M.MachineMap({ ...pnode, gpus: pnode.gpus.map((g) => (String(g.index) === "1" ? { ...g, memoryUsedMiB: 32000, memoryFreeMiB: 768 } : g)) }, { cells: pcells, plan });
  out.planMap.frozen = liveFit.fit(pnode.servers[1]);
  out.planMap.othersLive = JSON.stringify(liveFit.fit(pnode.servers[0])) === JSON.stringify(new M.MachineMap(liveFit.node, { cells: pcells }).fit(pnode.servers[0]));
  plan.end();
  out.planMap.unfrozen = liveFit.fit(pnode.servers[1]);
  // vLLM with weights left in RAM: its piece there is said to ride, its handle is the only one, and its row names the price.
  {
    const vfit = { how: "asks", family: "vllm", bytes: 28 * GIB, asks: [], over: false, ridesGb: 0, fields: { ...empty, CPU_OFFLOAD_GB: "" }, asksFor: () => ({ asks: [], over: false, ridesGb: 0, offloadNeededGb: 0, weightsGb: 40 }) };
    const vcells = new Map([["22007", pcells.get("22007")], ["22020", { name: "V", stop: "", launch: "data-y", group: "bench", runner: "vLLM", fit: vfit }]]);
    plan.set(22020, { how: "asks", fields: { ENV: "CUDA_VISIBLE_DEVICES=1", CPU_OFFLOAD_GB: "12" }, asks: [{ index: "1", mib: 28 * 1024, weightsMib: 20 * 1024 }], over: false, ridesGb: 12 });
    const vm = new M.MachineMap(pnode, { cells: vcells, chosen: "", plan });
    const vl = vm.lanes();
    out.planMap.ridesSize = new M.MachineMap(pnode, { cells: new Map([["22020", { fit: { ...vfit, keepsRam: true, ridesGb: 5 } }]]) }).sizeWords(pnode.servers[1]);
    out.planMap.rides = { lanes: vl.map((l) => ({ blocks: l.blocks.filter((b) => b.ghostOf).map((b) => [b.ghostOf, b.kind, Math.round(b.value)]), notes: l.notes.filter((n) => n.name.includes("22020")).map((n) => n.words), grips: l.grips.map((g) => [g.on, g.title]), links: l.links.length })),
                          panel: rowsOf(vm) };
    plan.clear();
    // Running, with its weights left in RAM: the RSS is its own piece there, and it rides all the same.
    const running = { ...pnode, cpu: { ...pnode.cpu, ram: { totalGb: 60, usedGb: 25 } }, servers: [cell(22020, "running", { gpuMem: { 1: 28 * 1024 }, ramBytes: 14 * GIB, slotConfig: {} })] };
    const rm = new M.MachineMap(running, { cells: new Map([["22020", { name: "V", stop: "data-s", launch: "", group: "holds", runner: "vLLM", fit: { ...vfit, keepsRam: true } }]]), chosen: "", plan });
    out.planMap.ridesRunning = rm.lanes().map((l) => l.notes.filter((n) => (n.name || "").includes("22020")).map((n) => n.words));
  }
  lay(22020, "1");
  plan.dragging = true; plan.drop = "1"; plan.dropOk = true;
  out.planMap.dragging = drawn();
  plan.dropOk = false;
  out.planMap.draggingNo = drawn().lanes[1].attrs;
  plan.dragging = false; plan.drop = "";
  lay(22020, "0", { evict: ["22007"], leaving: ["22007"] });
  out.planMap.evict = drawn();
  lay(22007, "1", { moved: true, leaving: ["22007"] });
  out.planMap.moved = drawn();
  plan.set(22020, { how: "plan", fields: { ...empty, N_GPU_LAYERS: "99", FIT: "0", DEVICE: "CUDA0" } });
  const small = new M.MachineMap({ ...pnode, gpus: [{ index: 0, memoryTotalMiB: 2048, memoryUsedMiB: 2048, memoryFreeMiB: 0 }] }, { cells: pcells, plan });
  out.planMap.noFit = rowsOf(small);
  plan.clear();
  // The buttons of where a cell can be laid, on its row.
  const placesOf = (cells, port) => { const m = new M.MachineMap(pnode, { cells, chosen: port, plan }); return [...m.placesHtml(pnode.servers.find((s) => String(s.port) === port)).matchAll(/data-machine-place="([^"]+)"/g)].map((x) => x[1]); };
  out.planMap.places = {
    llama: placesOf(pcells, "22020"),
    html: new M.MachineMap(pnode, { cells: pcells, chosen: "22020", plan }).placesHtml(pnode.servers[1]).split("</button>")[0],
    running: placesOf(pcells, "22007"),
    cardOnly: placesOf(new Map([["22020", { launch: "data-y", group: "bench", fit: { family: "pinned", gpuOk: true, cpuOk: false, fields: empty } }]]), "22020"),
    engine: placesOf(new Map([["22020", { launch: "data-y", group: "bench", fit: { family: "", fields: empty } }]]), "22020"),
    noStart: placesOf(new Map([["22020", { launch: "", group: "bench", fit }]]), "22020"),
    noStop: placesOf(new Map([["22007", { stop: "", group: "holds", fit }]]), "22007"),
  };
  // A card with no room left offers no hollow handle.
  const fullCard = { ...pnode, gpus: [{ index: 0, name: "RTX 3090", memoryTotalMiB: 24576, memoryUsedMiB: 24300, memoryFreeMiB: 276 }, pnode.gpus[1]] };
  out.planMap.fullCard = new M.MachineMap(fullCard, { cells: pcells, chosen: "22020", plan }).lanes().map((l) => l.grips.length);
  // Grips for a chosen stopped llama.cpp cell with no plan yet; none for a one-card runner.
  out.planMap.chosenNoPlan = new M.MachineMap(pnode, { cells: pcells, chosen: "22020", plan }).lanes().map((l) => l.grips.length);
  const pinned = new Map([["22020", { name: "Step", launch: "data-y", group: "bench", fit: { how: "card", family: "pinned", bytes: 10 * GIB, fields: empty } }]]);
  out.planMap.chosenPinned = new M.MachineMap(pnode, { cells: pinned, chosen: "22020", plan }).lanes().map((l) => l.grips.length);
  // A row's last line written whole when the plan changes, and only then.
  const picks = { writes: 0, _html: "", set outerHTML(v) { this._html = v; this.writes += 1; }, get outerHTML() { return this._html; } };
  const models = { dataset: {} };
  const at = { querySelector: (sel) => ({ '[data-t="machine-models"]': models, '[data-machine-panel="22020"]': picks })[sel] || null };
  const planLive = new M.MachineHeadLive();
  const headNow = () => new M.MachineHead(pnode, { cells: pcells, plan });
  planLive.patch(at, headNow());
  const quiet = picks.writes;
  lay(22020, "1");
  planLive.patch(at, headNow());
  const laid = [picks.writes, picks._html.includes('data-t-state="planned"')];
  planLive.patch(at, headNow());
  const again = picks.writes;
  plan.clear();
  planLive.patch(at, headNow());
  out.planMap.live = { quiet, laid, again, cleared: [picks.writes, picks._html.includes("planned")] };
  // A click on another cell drops the plan with it.
  const docListeners = [];
  const pdoc = { addEventListener: (type, fn) => docListeners.push(fn), querySelector: () => null, querySelectorAll: () => [] };
  const pp = new M.MachinePick();
  pp.know(pcells);
  pp.bind(pdoc, { redraw: () => {} });
  const clickOn = (port) => docListeners.forEach((fn) => fn({ target: { closest: (sel) => (sel === "[data-machine-pick]" ? { dataset: { machinePick: port, t: "x" } } : null) }, preventDefault() {} }));
  PL.MACHINE_PLAN.set(22020, { how: "plan", fields: { A: "1" } });
  pp.port = "22020";
  clickOn("22007");
  out.planMap.otherCell = [PL.MACHINE_PLAN.on, pp.port];
  PL.MACHINE_PLAN.set(22020, { how: "plan", fields: { A: "1" } });
  pp.port = "";
  clickOn("22020");
  out.planMap.sameCell = [PL.MACHINE_PLAN.on, pp.port];
  PL.MACHINE_PLAN.clear();
}
// Where a stopped cell would go (CellFit), a way per runner, on a machine with two empty cards and 51.8 GB of RAM free.
const FN = { cpu: { ram: { totalGb: 60.5, usedGb: 8.7 } },
             gpus: [{ index: 0, memoryTotalMiB: 24576, memoryUsedMiB: 0 }, { index: 1, memoryTotalMiB: 32607, memoryUsedMiB: 0 }] };
const NOCARD = { cpu: FN.cpu, gpus: [] };
const r2 = (x) => (x === null || x === undefined ? null : Math.round(x * 100) / 100);
const placed = (facts, node = FN) => {
  const p = M.CellFit.of(facts).place(node);
  return [p.verdict, p.cards.map((c) => [c.index, r2(c.gb)]), r2(p.ramGb), r2(p.needGb)];
};
const F = (o) => M.CellFit.facts(o);
const spread = (gb, config = {}, extra = {}) => F({ how: "spread", bytes: gb === null ? null : gb * GIB, config, ...extra });
const one = (gb, env = "", row = {}) => F({ how: "card", bytes: gb === null ? null : gb * GIB, config: { ENV: env }, row });
// A server that runs on one card (whisper, seamless, the voice ones): the registry's oneCard.
const ONE = { oneCard: true };
const strata = (config, floorMiB = 6144) => F({ how: "free", config, row: { vramPlan: { takesFree: true, floorMiB, reserveField: "STRATA_VRAM_RESERVE_MIB" } } });
const ridesCell = (ridesGb, extra = {}) => ({ how: "asks", family: "vllm", asks: [{ index: "1", mib: 28 * 1024, weightsMib: 20 * 1024 }], over: false, ridesGb, needGb: 28, bytes: 28 * GIB, fields: {}, ...extra });
const asks = (cards, perCardGb, over = false) => F({ how: "asks", vllm: { cards: cards.map((index) => ({ index })), perCardGb,
                                                                       totalGb: perCardGb.reduce((a, b) => a + b, 0), weightsOver: over } });
out.fit = {
  spread: [placed(spread(39.6)), placed(spread(87.2)), placed(spread(140)), placed(spread(20, { DEVICE: "CUDA1" })),
           placed(spread(50, { FIT_TARGET: "4096" }))],
  tensor: [placed(spread(40, {}, { mode: "tensor" })), placed(spread(60, {}, { mode: "tensor" }))],
  held: [placed(spread(20, { N_GPU_LAYERS: "99" })), placed(spread(20, { CPU_MOE: "1" })), placed(spread(40, { N_GPU_LAYERS: "all" })),
         placed(spread(60, { N_GPU_LAYERS: "all" })), placed(spread(60, { FIT: "0" }))],
  spreadEdge: [placed(spread(2.8), NOCARD), placed(spread(60), NOCARD), placed(spread(null)), placed(spread(0)),
               placed(spread(20), { cpu: FN.cpu, gpus: [{ index: 0, memoryTotalMiB: null, memoryUsedMiB: 0 }] }),
               placed(spread(20, { DEVICE: "CUDA5" })), placed(spread(87.2), { gpus: FN.gpus, cpu: {} }),
               placed(one(2), { cpu: FN.cpu, gpus: [{ index: 0, memoryTotalMiB: 24576 }] }),
               placed(one(2), { cpu: FN.cpu, gpus: [{ index: 0, memoryFreeMiB: 3000 }] })],
  card: [placed(one(20)), placed(one(31, "CUDA_VISIBLE_DEVICES=1")), placed(one(32, "CUDA_VISIBLE_DEVICES=1")),
         placed(one(20, "CUDA_VISIBLE_DEVICES=0,1")), placed(one(20, "CUDA_VISIBLE_DEVICES=3")), placed(one(null)), placed(one(2), NOCARD),
         placed(one(null, "CUDA_VISIBLE_DEVICES=1", ONE)), placed(one(null, "CUDA_VISIBLE_DEVICES=3", ONE)), placed(one(null, "", ONE), NOCARD),
         placed(one(null, "", ONE))],
  auto: [placed(one(30, "", { autoDevice: true })), placed(one(2, "", { autoDevice: true }), NOCARD), placed(one(70, "", { autoDevice: true }))],
  free: [placed(strata({ ENV: "CUDA_VISIBLE_DEVICES=1" })), placed(strata({ ENV: "CUDA_VISIBLE_DEVICES=1", STRATA_VRAM_RESERVE_MIB: "4096" })),
         placed(strata({ ENV: "CUDA_VISIBLE_DEVICES=1" }, 40000)), placed(strata({ ENV: "CUDA_VISIBLE_DEVICES=1", STRATA_VRAM_RESERVE_MIB: "abc" })),
         placed(strata({ ENV: "CUDA_VISIBLE_DEVICES=3" })), placed(strata({})),
         placed(strata({ ENV: "CUDA_VISIBLE_DEVICES=1" }), { gpus: [{ index: 1 }] })],
  asks: [placed(asks([0], [21.6])), placed(asks([0, 1], [21.6, 21.6])), placed(asks([1], [32.23])), placed(asks([0], [21.6], true)),
         placed(asks([], [])), placed(asks([0], [21.6]), { gpus: [{ index: 0 }] })],
  ram: [placed(F({ how: "ram", bytes: 2.8 * GIB })), placed(F({ how: "ram", bytes: 60 * GIB })),
        placed(F({ how: "ram", bytes: 2.8 * GIB }), { gpus: [], cpu: { ram: { totalGb: 60.5 } } })],
  none: [placed(F({ how: "", bytes: 2 * GIB })), placed(F({ how: "zzz", bytes: 2 * GIB })), placed(undefined)],
};
out.facts = {
  free: F({ how: "free", bytes: 5, mode: "layer",
            config: { ENV: "A=1", DEVICE: "CUDA1", FIT_TARGET: "2048", TENSOR_SPLIT: "3,1", FIT: "1", N_GPU_LAYERS: "auto", N_CPU_MOE: "2",
                      CPU_MOE: "0", STRATA_VRAM_RESERVE_MIB: 4096 },
            row: { keepsRam: true, vramPlan: { takesFree: true, floorMiB: 6144, reserveField: "STRATA_VRAM_RESERVE_MIB" } } }),
  planned: [F({ how: "card", bytes: 5, planned: true }).source, F({ how: "card", bytes: 5 }).source, F({ row: { autoDevice: true } }).orRam],
  vllm: (({ bytes, source, asks: a, over }) => ({ gb: r2(bytes / GIB), source, asks: a.map((x) => [x.index, r2(x.mib)]), over }))(asks([0, 1], [22.1, 22.1], true)),
  bare: F(),
  asksWeights: F({ how: "asks", vllm: { cards: [{ index: 0 }, { index: 1 }], perCardGb: [22.1, 22.1], totalGb: 44.2, weightsOver: false, weightsGb: 30, tp: 2, weightsOnCardGb: 15, ridesGb: 0 } })
    .asks.map((a) => [a.index, r2(a.mib), r2(a.weightsMib)]),
};

// The exact plan (1.3.635): a llama.cpp cell whose model the library knows — its weights, its cache, its buffers — laid by the
// cell window's own plan (PlacementPlan.from) against the cards' free room now. A dense 70B of 80 layers, 8 KV heads of 128.
const DENSE = { blockCount: 80, headCount: 64, headCountKv: 8, keyLength: 128, embeddingLength: 8192 };
const MODELS = new Map([["70b.gguf", { path: "70b.gguf", sizeGb: 39.6, ggufMeta: DENSE }], ["bare.gguf", { path: "bare.gguf", sizeGb: 7 }],
                        ["mm.gguf", { path: "mm.gguf", sizeGb: 1.2 }]]);
const L70 = { MODEL_FILE: "70b.gguf", CTX_SIZE: "131072", CACHE_TYPE_K: "q8_0", CACHE_TYPE_V: "q8_0", PARALLEL: "1", BATCH_SIZE: "1024",
              UBATCH_SIZE: "512" };
const exact = (config, how = "spread", extra = {}) => F({ how, bytes: 39.6 * GIB, config: { ...L70, ...config }, models: MODELS, ...extra });
const full = (facts, node = FN) => {
  const p = M.CellFit.of(facts).place(node);
  return { verdict: p.verdict, cards: p.cards.map((c) => [c.index, r2(c.gb), r2(c.weightsGb), r2(c.cacheGb)]),
           ram: [r2(p.ramGb), r2(p.ramWeightsGb), r2(p.ramCacheGb)], need: r2(p.needGb) };
};
const big = exact({});
const told = ({ how, source, bytes, split }) => [how, source, r2(bytes / GIB), split ? [r2(split.weightsGb), r2(split.cacheGb)] : null];
out.exact = {
  facts: told(big), layers: big.model?.layers,
  spill: full(big), fits: full(exact({ CTX_SIZE: "4096" })),
  held999: full(exact({ N_GPU_LAYERS: "999" })), held999small: full(exact({ CTX_SIZE: "4096", N_GPU_LAYERS: "999" })),
  kvRam: full(exact({ KV_OFFLOAD: "0" })), ramShort: full(big, { ...FN, cpu: { ram: { totalGb: 16, usedGb: 11 } } }),
  noCard: full(big, NOCARD), noCardSmall: full(exact({ CTX_SIZE: "4096" }), NOCARD), device: full(exact({ CTX_SIZE: "4096", DEVICE: "CUDA1" })),
  silentCard: full(big, { cpu: FN.cpu, gpus: [{ index: 0, memoryTotalMiB: 24576 }, FN.gpus[1]] }), moe: full(exact({ CPU_MOE: "1" })),
  unknownModel: told(exact({ MODEL_FILE: "nope.gguf" })), headless: told(exact({ MODEL_FILE: "bare.gguf" }, "spread", { bytes: 7 * GIB })),
  cpu: told(exact({ CTX_SIZE: "4096" }, "ram")), cpuPlaced: full(exact({ CTX_SIZE: "4096" }, "ram")),
  noModels: told(F({ how: "spread", bytes: 39.6 * GIB, config: L70 })), projector: told(exact({ MMPROJ_FILE: "mm.gguf" })),
  asks: full(F({ how: "asks", vllm: { cards: [{ index: 0 }, { index: 1 }], perCardGb: [22.1, 22.1], totalGb: 44.2, weightsOver: false, weightsGb: 30, tp: 2, weightsOnCardGb: 15, ridesGb: 0 } })),
};
out.rides = {
  fits: full(ridesCell(12)), none: full(ridesCell(0)), short: full(ridesCell(200)), blind: full(ridesCell(200), { ...FN, cpu: { ram: { totalGb: 60, usedGb: null } } }),
  over: full(ridesCell(12, { over: true })),
  words: M.MachineMap.fitWords(M.CellFit.of(ridesCell(12)).place(FN)), tone: M.MachineMap.fitTone("rides"),
  keeps: [F({ how: "asks", row: { keepsRam: true }, vllm: { cards: [], perCardGb: [], totalGb: 0, ridesGb: 0 } }).keepsRam, F({ how: "asks", row: { keepsRam: true }, vllm: { cards: [], perCardGb: [], totalGb: 0, ridesGb: 5 } }).keepsRam,
          F({ how: "free", row: { keepsRam: true } }).keepsRam, F({ how: "asks", row: {}, vllm: { cards: [], perCardGb: [], totalGb: 0, ridesGb: 5 } }).keepsRam],
  said: F({ how: "asks", vllm: { cards: [], perCardGb: [], totalGb: 0, ridesGb: 7.5 } }).ridesGb,
  field: F({ how: "asks", config: { CPU_OFFLOAD_GB: "7.5" } }).fields.CPU_OFFLOAD_GB,
};
// The chosen stopped cell drawn on the lanes: its weights and, paler, its cache and buffers, where the plan lays each.
const XN = { ...FN, servers: [cell(22020, "stopped")] };
const xcell = (fit) => new Map([["22020", { key: "x:22020", name: "Hermes", group: "bench", fit, jobs: ["llm"], launch: "a" }]]);
const dashes = (fit) => new M.MachineMap(XN, { cells: xcell(fit), chosen: "22020" }).lanes()
  .map((lane) => lane.blocks.filter((b) => String(b.kind || "").startsWith("estimate")).map((b) => [b.kind, r2(b.value), b.name, b.figure, b.title]));
const xmap = new M.MachineMap(XN, { cells: xcell(big), chosen: "22020" });
out.exactGhost = { spill: dashes(big), kvRam: dashes(exact({ KV_OFFLOAD: "0" })), byFiles: dashes(F({ how: "spread", bytes: 39.6 * GIB, config: L70 })),
                   words: [xmap.sizeWords(XN.servers[0]), M.MachineMap.fitWords(xmap.fit(XN.servers[0])), xmap.benchVerdict(XN.servers[0]).words],
                   kvRamWords: M.MachineMap.fitWords(new M.MachineMap(XN, { cells: xcell(exact({ KV_OFFLOAD: "0" })) }).fit(XN.servers[0])),
                   html: xmap.lanesHtml() };

// The cells in the list of models, on a machine whose first card holds 2 GB of something else.
const BN = {
  id: "bench", name: "Bench", role: "host", online: true, cpu: { ram: { totalGb: 60.5, usedGb: 8.7 } },
  gpus: [{ index: 0, name: "NVIDIA GeForce RTX 3090", memoryTotalMiB: 24576, memoryUsedMiB: 2048 },
         { index: 1, name: "NVIDIA GeForce RTX 5090", memoryTotalMiB: 32607, memoryUsedMiB: 0 }],
  servers: [
    cell(22001, "running", { gpuMem: {}, ramBytes: 0.6 * GIB }),
    cell(22017, "downloading", { downloadingFile: "voice.safetensors", downloadedBytes: 4 * GIB, totalBytes: 8 * GIB }),
    cell(22011, "stopping"), cell(22012, "starting"),
    cell(22020, "stopped"), cell(22014, "stopped"), cell(22026, "stopped"), cell(22009, "stopped"), cell(22023, "stopped"),
    cell(22018, "error"), cell(22030, "reserved"), cell(22005, "stopped"),
  ],
};
const start = (port) => `data-node-cell-play="bench" data-node-cell-port="${port}"`;
const facts = (port, extra) => [String(port), { key: `bench:${port}`, name: "", window: true, group: "bench", stop: "", stopTitle: "Not running",
                                                launch: start(port), playTitle: "Start server", reason: "", jobs: [], runner: "llama.cpp", fit: {}, ...extra }];
const BCELLS = new Map([
  // A cell that runs has a size of its own too: it is drawn by what it holds, never dashed.
  facts(22001, { name: "Qwen3-Embedding-0.6B", group: "holds", stop: 'data-node-cell-stop="bench" data-node-cell-port="22001"', stopTitle: "Stop server",
                 launch: "", jobs: ["embed"], fit: spread(0.6) }),
  facts(22017, { name: "voice-clone", group: "coming", launch: "", jobs: ["tts"] }),
  facts(22011, { name: "gemma", group: "coming", launch: "", jobs: ["llm"] }),
  facts(22012, { name: "", group: "coming", launch: "", jobs: ["llm"] }),
  facts(22020, { name: "Hermes-4-70B", jobs: ["llm"], fit: spread(39.6), ctx: { set: 32768, max: 131072 }, repo: "lmstudio-community/Hermes-4-70B-GGUF",
                 model: "Hermes-4-70B-GGUF", listed: "Hermes-4-70B-GGUF", rating: "like" }),
  facts(22014, { name: "Strata <Kimi>", jobs: ["llm"], runner: "Strata", ctx: { set: 65536, max: 0 }, repo: "  a&b/<c>  ", listed: "Strata-Kimi",
                 fit: F({ how: "free", bytes: 120 * GIB, config: { ENV: "CUDA_VISIBLE_DEVICES=1" },
                          row: { keepsRam: true, vramPlan: { takesFree: true, floorMiB: 6144, reserveField: "STRATA_VRAM_RESERVE_MIB" } } }) }),
  facts(22026, { name: "Qwen3-TTS", jobs: ["tts"], runner: "Qwen3-TTS", fit: F({ how: "card", bytes: 31 * GIB, planned: true }) }),
  facts(22009, { name: "Llama-3.3-70B", jobs: ["llm"], fit: spread(70.7), ctx: { set: 196608, max: 131072 } }),
  facts(22023, { name: "bge-m3", jobs: ["embed"], fit: F({ how: "ram", bytes: 0.3 * GIB }) }),
  facts(22018, { name: "whisper", jobs: ["asr"], runner: "whisper", reason: "exit 1: CUDA out of <memory>", fit: one(3) }),
  facts(22030, { name: "Reserved port", jobs: [], launch: "", playTitle: "Choose a model first", fit: spread(null) }),
  facts(22005, { name: "ollama-qwen", jobs: ["llm", "nonsense"], runner: "Ollama", fit: F({ how: "" }) }),
]);
const bmap = (chosen = "") => new M.MachineMap(BN, { cells: BCELLS, chosen });
const bm = bmap();
const listOf = (map, job = "") => {
  const choice = new MM.MachineModelsChoice();
  choice.job = job;
  return new MM.MachineModels({ map, ratings: { "Hermes-4-70B-GGUF": "like" }, choice }).html();
};
out.bench = { order: bm.bench().map((s) => s.port), standing: bm.standing().map((s) => s.port), coming: bm.coming().map((s) => s.port),
              jobs: bm.benchJobs(), html: listOf(bm),
              every: bm.everyCell().map((s) => s.port),
              sizes: ["22020", "22014", "22026", "22005"].map((p) => bm.sizeWords(BN.servers.find((s) => String(s.port) === p))) };
out.bench.tts = listOf(bm, "tts");
out.bench.stale = listOf(bm, "voice-chat");
out.bench.shown = [bm.jobShown("tts"), bm.jobShown("voice-chat"), bm.jobShown("")];
out.bench.empty = listOf(new M.MachineMap({ ...BN, servers: [] }, { cells: BCELLS }));
// Every cell works or is on its way (1.3.659): the list shows them, with what they do — the bench said "nothing stands idle" and showed none.
out.bench.working = listOf(new M.MachineMap({ ...BN, servers: BN.servers.filter((s) => ["running", "downloading"].includes(s.phase)) }, { cells: BCELLS }));
// A cell that holds its memory and loads its weights, or whose engine does not answer: its row says that, not "running".
const WB = { ...BN, servers: [cell(22040, "warming", { gpuMem: { 0: 8192 } }), cell(22041, "broken", { gpuMem: { 1: 4096 } }), cell(22042, "running")] };
const wbm = new M.MachineMap(WB, { cells: new Map() });
out.bench.verdicts = WB.servers.map((s) => [wbm.benchVerdict(s), wbm.benchSize(s)]);
// A cell loading its weights, and one whose start reads its model, measured by their scout (2.43, 1.3.662): how far, how fast, how long.
const LB = { ...BN, servers: [cell(22050, "warming", { gpuMem: { 0: 8192 }, readBytes: 12 * GIB, modelBytes: 42 * GIB, readBytesPerSec: 480 * 2 ** 20 }),
                              cell(22051, "starting", { readBytes: 3 * GIB, readBytesPerSec: GIB }), cell(22052, "starting")] };
const lbm = new M.MachineMap(LB, { cells: new Map() });
out.bench.load = { warming: lbm.benchVerdict(LB.servers[0]).words, starting: lbm.comingWords(LB.servers[1]), still: lbm.comingWords(LB.servers[2]) };
out.bench.groups = ["running", "warming", "broken", "downloading", "starting", "loading", "resolving", "stopping", "stopped", "error", "reserved", ""]
  .map((phase) => M.MachineMap.groupOf(phase));
const ghostOf = (port) => bmap(port).lanes().map((lane) => lane.blocks.filter((b) => b.kind === "estimate")
  .map((b) => [r2(b.value), b.figure, b.name, b.title]));
out.ghost = { hermes: ghostOf("22020"), spill: ghostOf("22009"), strata: ghostOf("22014"), none: ghostOf("22026"), running: ghostOf("22001"),
              reserved: ghostOf("22030"), lanesHtml: bmap("22020").lanesHtml() };
out.comingHtml = bm.comingHtml();
out.bpanels = rowsOf(bmap("22020"));
out.bsubs = Object.fromEntries(["22017", "22011", "22012", "22014", "22009", "22023", "22018", "22030", "22005"]
  .map((p) => { const s = BN.servers.find((x) => String(x.port) === p); return [p, [bm.benchSize(s), bm.benchVerdict(s).words].filter(Boolean).join(" · ")]; }));

// The choice, bound on a document: a stopped cell's choice draws the board again; a press on a cell's own button chooses nothing.
const blisteners = [];
let bredraws = 0;
const bfocused = [];
const bdoc = {
  addEventListener: (type, fn) => blisteners.push([type, fn]),
  querySelector: (sel) => {
    if (sel.startsWith(".fold-slot")) return {};
    const m = sel.match(/^\[data-t="([^"]+)"\]\[data-machine-pick="(\d+)"\]$/);
    return m ? { focus: () => bfocused.push(`${m[1]}:${m[2]}`) } : null;
  },
  querySelectorAll: () => [],
};
const bpick = new M.MachinePick();
bpick.know(BCELLS);
const bsaved = [];
const bnotes = [];
let brefuse = false;
bpick.bind(bdoc, { redraw: () => { bredraws += 1; }, notify: (words) => bnotes.push(words),
                   save: async (model, rating) => { bsaved.push([model, rating]); if (brefuse) throw new Error("refused"); } });
const bclick = (target) => blisteners.forEach(([, fn]) => fn({ target: { closest: (sel) => target[sel] || null }, preventDefault() {} }));
const onPick = (port, hook) => ({ "[data-machine-pick]": { dataset: { machinePick: port, t: hook } } });
const onOwn = (port) => ({ "[data-machine-own]": {}, ...onPick(port, "machine-model-launch") });
bclick(onPick("22020", "machine-model-cell"));
const chosenStopped = { port: bpick.port, redraws: bredraws, focus: [...bfocused] };
bclick(onPick("22001", "machine-map-block"));
const leftStopped = { port: bpick.port, redraws: bredraws, focus: [...bfocused] };
bclick(onPick("22011", "machine-map-coming-cell"));
const runningToComing = { port: bpick.port, redraws: bredraws };
// A click anywhere on a cell's row chooses it, as the port does; on its Window, Start or Stop it only does that.
const beforeRow = bredraws;
bclick(onPick("22026", "machine-model-launch"));
const rowChosen = { port: bpick.port, redraws: bredraws - beforeRow };
bclick(onOwn("22009"));
const ownPressed = { port: bpick.port, redraws: bredraws - beforeRow };
bclick(onPick("22026", "machine-model-launch"));
const rowLetGo = { port: bpick.port, redraws: bredraws - beforeRow };
out.bbind = { chosenStopped, leftStopped, runningToComing, rowChosen, ownPressed, rowLetGo,
              standing: ["22020", "22001", "22011", "", "22999"].map((p) => bpick.standing(p)) };
out.oldJob = [typeof bpick.narrow, typeof bpick.showJob, "job" in bpick];
// A like or a dislike of a model: shown at once on every card of the model and kept by the controller; refused, it goes back and says why; it chooses nothing.
BCELLS.get("22014").model = "strata"; BCELLS.get("22001").model = "strata";
const rateEl = (kind, model) => { const e = { dataset: { modelRate: kind, modelRateFor: model }, attrs: {}, cls: new Set() };
  e.classList = { toggle: (c, on) => (on ? e.cls.add(c) : e.cls.delete(c)) }; e.setAttribute = (k, v) => { e.attrs[k] = v; }; return e; };
const rateLook = (e) => [e.attrs["aria-pressed"], e.cls.has("is-on")];
const settled = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };   // the harness holds the timers: microtasks only
const likeIt = rateEl("like", "strata"), dislikeIt = rateEl("dislike", "strata"), hermesOn = rateEl("like", "Hermes-4-70B-GGUF");
bdoc.querySelectorAll = ((was) => (sel) => (sel === "[data-model-rate-for]" ? [likeIt, dislikeIt, hermesOn] : was ? was(sel) : []))(bdoc.querySelectorAll?.bind(bdoc));
const rateFacts = () => [BCELLS.get("22014").rating, BCELLS.get("22001").rating, BCELLS.get("22020").rating];
const pickBefore = bpick.port;
const redrawsBefore = bredraws;
blisteners.forEach(([, fn]) => fn({ target: { closest: (sel) => (sel === "[data-model-rate]" ? likeIt : null) }, preventDefault() {} }));
await settled();
const pressed = { looks: [rateLook(likeIt), rateLook(dislikeIt)], other: hermesOn.attrs["aria-pressed"] ?? null, saved: [...bsaved], facts: rateFacts(), port: bpick.port === pickBefore, redraws: bredraws - redrawsBefore };
const saver = { save: async (model, rating) => { bsaved.push([model, rating]); }, root: bdoc };
await bpick.rate(rateEl("like", "strata"), saver);
const unpressed = { looks: [rateLook(likeIt), rateLook(dislikeIt)], saved: bsaved.slice(-1), facts: rateFacts() };
await bpick.rate(dislikeIt, saver);
const changed = { looks: [rateLook(likeIt), rateLook(dislikeIt)], saved: bsaved.slice(-1), facts: rateFacts() };
const refusedEl = rateEl("dislike", "Hermes-4-70B-GGUF");
const refusedAnswer = await bpick.rate(refusedEl, { save: async () => { throw new Error("no such model"); }, notify: (w) => bnotes.push(w), root: bdoc });
const refused = { answer: refusedAnswer, look: rateLook(refusedEl), other: rateLook(hermesOn), facts: rateFacts(), notes: [...bnotes] };
const sent = bsaved.length;
const unknown = [await bpick.rate(rateEl("like", ""), saver)];
out.rate = { pressed, unpressed, changed, refused, unknown, sent: bsaved.length - sent };

// The rows' sizes and verdicts and the chips of the cells on their way, kept current in place. What the patch finds is what the page drew: a
// span read off the head's own HTML, so that a row that stops writing the names the patch looks for has nothing to be found by.
const bhead = (node) => new M.MachineHead(node, { cells: BCELLS, chosen: "" });
const span = (cls, state, words) => {
  const e = { dataset: { tState: state }, className: cls, writes: 0, _text: words.replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&") };
  Object.defineProperty(e, "textContent", { get: () => e._text, set: (v) => { e._text = v; e.writes += 1; } });
  return e;
};
const drawnHtml = bhead(BN).html();
const spans = Object.fromEntries([...drawnHtml.matchAll(/<span class="(machine-bench-fit machine-bench-fit--\w+)" data-machine-bench-fit="(\d+)" data-t-state="(\w+)"[^>]*>([^<]*)<\/span>/g)]
  .map(([, cls, port, state, words]) => [port, span(cls, state, words)]));
const sizes = Object.fromEntries([...drawnHtml.matchAll(/<span class="machine-bench-size" data-machine-bench-size="(\d+)">([^<]*)<\/span>/g)]
  .map(([, port, words]) => [port, span("", "", words)]));
const bpage = drawn(bhead(BN));
const broot = { querySelector: (sel) => {
  if (sel === "[data-machine-map]") return bpage;
  const m = sel.match(/^\[data-machine-bench-fit="(\d+)"\]$/);
  if (m) return spans[m[1]] || null;
  const z = sel.match(/^\[data-machine-bench-size="(\d+)"\]$/);
  return z ? sizes[z[1]] || null : null;
} };
const blive = new M.MachineHeadLive();
const verdicts = () => Object.fromEntries(Object.entries(spans).map(([p, e]) => [p, [e.textContent, e.dataset.tState, e.className]]));
blive.patch(broot, bhead(BN));
out.blive = { drawn: verdicts(), drawnWrites: bpage.writes.map, sizes: Object.fromEntries(["22001", "22017", "22020"].map((p) => [p, sizes[p]?.textContent ?? null])),
              found: [Object.keys(spans).sort(), Object.keys(sizes).sort(), BN.servers.map((s) => String(s.port)).sort()] };
// The RAM fills up and the copy moves on: the blocks stay the same — the chips' words and the verdicts move in place.
const RAMFULL = { ...BN, cpu: { ram: { totalGb: 60.5, usedGb: 45 } },
                  servers: BN.servers.map((s) => (s.port === 22017 ? { ...s, downloadedBytes: 6 * GIB } : s)) };
blive.patch(broot, bhead(RAMFULL));
out.blive.ramFull = { verdicts: verdicts(), mapWrites: bpage.writes.map, chips: bpage.chips.map((c) => [c.textContent, c.writes]) };
// The running cell's memory moved: its row says the new figure in place.
blive.patch(broot, bhead({ ...RAMFULL, servers: RAMFULL.servers.map((s) => (s.port === 22001 ? { ...s, ramBytes: 0.9 * GIB } : s)) }));
out.blive.moved = { size: sizes["22001"]?.textContent ?? null, writes: sizes["22001"]?.writes ?? null, still: sizes["22020"]?.writes ?? null };
// The second card fills with something else: a block more on its lane — the lanes are written whole, the verdicts still move.
const CARDFULL = { ...BN, gpus: BN.gpus.map((g) => (g.index === 1 ? { ...g, memoryUsedMiB: 20000 } : g)) };
blive.patch(broot, bhead(CARDFULL));
out.blive.cardFull = { verdicts: verdicts(), mapWrites: bpage.writes.map };

// The column at the right of the map (1.3.636): the parts the board's builder drew, framed, and what is not there said.
const sideOf = (o) => new M.MachineSide(o).html();
out.side = {
  full: sideOf({ warnings: '<div class="w">!</div>', engines: "<i>engines</i>", disk: "<i>disk</i>", incidents: 2, activity: "<i>charts</i>", stats: "<i>stats</i>", machine: " gpu-box " }),
  empty: sideOf({}), zero: sideOf({ incidents: 0 }), junk: [sideOf({ incidents: -1 }), sideOf({ incidents: "x" }), sideOf({ incidents: 2.7 })],
};
const withSide = new M.MachineHead(GOOD, { owners, cells: CELLS, side: '<aside class="machine-side">S</aside>' }).html();
const withoutSide = new M.MachineHead(GOOD, { owners, cells: CELLS }).html();
out.headSide = [withSide.includes('<div class="machine-grid"><div class="machine-main"><section class="machine-models"') && withSide.indexOf('<section class="machine-map"') < withSide.indexOf('<div class="machine-grid">'),
                withSide.includes('</section></div><aside class="machine-side">S</aside></div>'), withoutSide.includes("machine-grid"),
                withoutSide.indexOf('<section class="machine-map"') >= 0 && withoutSide.includes('<div class="machine-main"><section class="machine-models"')];
// The pictures at the left of the lanes, on a machine of six cards: one per lane, its own, by value.
{
  const six = { id: "six", cpu: { ram: { totalGb: 60.5, usedGb: 8 } }, servers: [], gpus: [0, 1, 2, 3, 4, 5].map((index) => ({ index, memoryTotalMiB: 24576, memoryUsedMiB: 0 })) };
  const sixHtml = new M.MachineMap(six).lanesHtml();
  const refused = (() => { try { return M.LanePicture.html("toaster"); } catch { return "refused"; } })();
  out.pictures = { lanes: [...sixHtml.matchAll(/data-t="machine-map-lane" data-t-id="([^"]+)"><div class="ui-lane-head">(?:<span class="machine-lane-pic" data-machine-lane-pic="(\w+)" aria-hidden="true">)?/g)].map(([, lane, pic]) => [lane, pic ?? null]),
                   count: (sixHtml.match(/class="machine-lane-pic"/g) || []).length,
                   card: M.LanePicture.html("card"), ram: M.LanePicture.html("ram"), refused,
                   plain: new UP.Lane({ label: "GPU 0", total: 10, rack: { bar: 50, slots: 0 } }).html(),
                   laneOfCard: new M.MachineMap(six).lanes()[0].pic === M.LanePicture.html("card"), laneOfRam: new M.MachineMap(six).lanes()[6].pic === M.LanePicture.html("ram") };
}
// The incidents' way in, bound once on the document.
const si = new M.SideIncidents();
const sl = [];
let opened = 0;
const sdoc = { addEventListener: (type, fn) => sl.push([type, fn]) };
si.bind(sdoc, { open: () => { opened += 1; } });
si.bind(sdoc, { open: () => { opened += 100; } });
const sclick = (hit) => sl.forEach(([, fn]) => fn({ target: { closest: (sel) => (sel === "[data-machine-incidents]" && hit ? {} : null) }, preventDefault() {} }));
sclick(true);
sclick(false);
out.sideIncidents = [sl.length, opened, si.bound];
// A stopped cell whose runner runs on one card and whose size nobody knows (whisper, seamless): its card is named — the pin, else
// card 0 — and the lane of that card says it starts there; nothing is laid there as if its size were known (2026-10-27).
const UNSIZED = { ...NODE, servers: [...NODE.servers, cell(22005, "stopped", { gpuMem: {} }), cell(22008, "stopped", { gpuMem: {} })] };
const UCELLS = new Map([...CELLS,
  ["22005", { key: "box:22005", name: "large-v3-turbo", stop: "", window: true,
              fit: M.CellFit.facts({ how: "card", bytes: null, config: { ENV: "" }, row: { oneCard: true } }) }],
  ["22008", { key: "box:22008", name: "seamless", stop: "", window: true,
              fit: M.CellFit.facts({ how: "card", bytes: null, config: { ENV: "CUDA_VISIBLE_DEVICES=1" }, row: { oneCard: true } }) }]]);
const um = (chosen) => new M.MachineMap(UNSIZED, { owners, cells: UCELLS, chosen });
const us = (port) => UNSIZED.servers.find((x) => x.port === port);
const fill = (k, v) => String(en[k]).replace(/\{(\w+)\}/g, (_, n) => v[n]);
out.unsized = {
  panel: [um("").benchSize(us(22005)), um("").benchSize(us(22008))],
  panelWant: [en.machineSizeUnknown, en.machineSizeUnknown],
  bench: [um("").benchVerdict(us(22005)), um("").benchVerdict(us(22008))],
  benchWant: [0, 1].map((i) => fill("machineFitUnsized", { index: String(i) })),
  foot: um("22005").lanes().map((lane) => lane.foot), foot8: um("22008").lanes().map((lane) => lane.foot), footNone: um("").lanes().map((lane) => lane.foot),
  footWant: [fill("machineGhostUnsized", { cell: ":22005" }), fill("machineGhostUnsized", { cell: ":22008" })],
  dashed: um("22005").lanes().flatMap((lane) => lane.blocks).filter((b) => String(b.kind || "").startsWith("estimate")).length,
};
// The states a row's verdict says for a cell that works, is on its way, or failed: the row's tint and its dot read them (machine.css).
out.benchStates =Object.fromEntries(["running", "warming", "broken", "error", ...M.MachineMap.COMING]
  .map((phase) => [phase, um("").benchVerdict({ port: 22005, phase, gpuMem: {} }).state]));
// The panes of a machine's page stay where they were when the board draws it anew: the drawing makes new elements, which start at 0.
const paneRoot = () => {
  const made = { ".machine-main": { scrollTop: 640, written: 0 }, ".machine-side": { scrollTop: 0, written: 0 } };
  const root = { drawn: "", querySelector: (sel) => made[sel] || null,
                 set innerHTML(html) { this.drawn = html;
                   for (const sel of Object.keys(made)) {
                     const el = { top: 0, written: 0, get scrollTop() { return this.top; }, set scrollTop(v) { this.top = v; this.written += 1; } };
                     made[sel] = el;
                   } } };
  return { root, made };
};
{
  const { root, made } = paneRoot();
  const tops = M.MachinePanes.read(root);
  M.MachinePanes.replace(root, "<new>");
  out.panes = { tops, drawn: root.drawn, main: made[".machine-main"].scrollTop, side: made[".machine-side"].written,
                noPage: M.MachinePanes.read({ querySelector: () => null }),
                noRoot: M.MachinePanes.read(null) };
  const bare = { drawn: "", querySelector: () => null, set innerHTML(html) { this.drawn = html; } };
  M.MachinePanes.replace(bare, "<cards>");
  out.panes.boardDrawn = bare.drawn;
}
console.log(JSON.stringify(out));
'''


def launch_of(html, port):
    """One cell's row out of the list's HTML: from its opening tag to the next cell's row, or to the end."""
    mark = html.index(f'data-machine-pick="{port}"')
    start = html.rindex('<div class="machine-model-launch', 0, mark)
    following = html.find('<div class="machine-model-launch', mark)
    return html[start:following if following > 0 else len(html)]


def section_rack(got):
    print("стойка: одна шкала, подписи, линия:")
    s = got["scale"]
    check(s["machine"] == [52.56, 100, True, [39.67, 52.56]],
          "3090, 5090 и 60,5 ГБ ОЗУ: самая большая карта 52,56% строки, 3090 короче 5090 в той же шкале, ОЗУ на всю строку — шкала общая")
    check(s["hugeRam"] == [38, 100, False, [38]],
          "boundary: ОЗУ 256 ГБ при карте 24 — карта не уже 38%, а ОЗУ в свою шкалу (и говорит об этом shared=false), а не брусок в палец")
    check(s["smallRam"] == [62, 41.33, True, [62]],
          "boundary: карта больше ОЗУ — карта не шире 62%, ОЗУ короче в той же шкале")
    check(s["noCards"] == [100, 100, True, []], "negative: карт нет — ОЗУ на всю строку")
    check(s["noRam"] == [62, 100, True, [46.5, 62]], "negative: ОЗУ не сказана — карты не шире 62%, её бруска всё равно нет")
    check(s["unknownCard"] == [39.67, 100, True, [39.67, 39.67]], "negative: размер карты не сказан — в шкалу не идёт")
    check(s["equal"] == [62, 62, True, [62]], "boundary: карта и ОЗУ равны — и брусок ОЗУ той же длины: шкала общая")
    check(s["justOn"] == [62, 99.98, True, [62]], "boundary: ОЗУ на шкале ещё влезает в строку — шкала общая")
    r = got["rack"]
    check(r["card0"]["rack"] == {"bar": 39.67, "slots": 1} and r["card1"]["rack"] == {"bar": 52.63, "slots": 1},
          f"карта: своя длина на общей шкале и одна линия на всю стойку (получено {r['card0']['rack']})")
    check(r["ram"]["rack"] == {"bar": 100, "slots": 1}, "ОЗУ: брусок на всю строку той же шкалы")
    n0 = r["card0"]["notes"]
    check([n["name"] for n in n0] == ["Xorg", "other processes", ":22010 gemma-4-12B-it", ":22020 Hermes-4-70B"],
          f"подпись у каждой ячейки на карте в порядке блоков, и чужой процесс от 1 ГБ (получено {[n['name'] for n in n0]})")
    check(n0[0] == {"port": "", "name": "Xorg", "shown": "Xorg", "gb": 1, "words": "1.0 GB", "title": "Xorg · 1.0 GB", "kind": "other"},
          "чужой процесс — только имя и цифра")
    check(n0[3]["words"] == "8.0 GB · part 1 of 2" and n0[3]["on"] is True and n0[3]["series"] == 4 and n0[3]["port"] == "22020" and n0[3]["shown"] == "Hermes-4-70B" and n0[3]["gb"] == 8
          and [n["words"] for n in r["card1"]["notes"] if n["name"].startswith(":22020")] == ["4.0 GB · part 2 of 2"],
          "кусок ячейки на двух картах говорит, какая он часть, своим цветом; выбранная помечена")
    check(n0[2]["words"] == "2.0 GB · 8% of the card" and n0[2]["on"] is False and r["ram"]["notes"][0]["words"] == "3.0 GB · 5% of RAM",
          "ячейка целиком на одном устройстве — сколько его она занимает")
    print("  список рядом со стойкой:", [(row["name"], row["figure"], row["where"]) for row in r["legend"]])
    lg = r["legend"]
    check([(row["name"], row["figure"], row["where"]) for row in lg][:1] == [("Hermes-4-70B", "12.0", "GPU 0–1")],
          "список: ячейка один раз, сумма со всех карт и где она; самая большая первой")
    check(lg[0]["pick"] == 'data-machine-pick="22020" data-t="machine-map-legend" data-t-id="22020"' and lg[0]["owner"] == "22020" and lg[0]["on"] is True and lg[0]["series"] == 4,
          "строка списка выбирает ячейку, как её блок, и связана с её кусками")
    check(lg[0]["title"] == ":22020 Hermes-4-70B · 12.0 GB\nGPU 0: 8.0 GB · part 1 of 2\nGPU 1: 4.0 GB · part 2 of 2", "в подсказке строки: порт и что лежит на каждой карте")
    check([row["name"] for row in lg] == ["Hermes-4-70B", "Qwen3-Embedding-0.6B", "gemma-4-12B-it", "other processes", "Xorg"],
          "порядок: ячейки по размеру, чужие процессы после всех ячеек, даже если больше какой-то из них")
    others = [row for row in lg if row.get("kind") == "other"]
    check([row["name"] for row in others] == ["other processes", "Xorg"] and all("pick" not in row and row["attrs"] == 'data-t="machine-map-legend-other"' for row in others) and lg[-1] in others,
          "чужие процессы от 1 ГБ — в конце списка и не кнопки")
    check(r["freeWords"] == ["24.0 free", "≈4.0 free", "≈0.0 free"], "свободно: без плана замер как есть; с планом остаток и знак оценки; negative: план больше свободного — не меньше нуля")
    check(r["where"] == ["GPU 0", "GPU 1–4", "GPU 0, 2–3, 5", "GPU 1 + RAM", "RAM", ""], "где лежит: карты подряд одним отрезком, с пропуском через запятую, и RAM")
    pl = r["planned"]
    print("  план в списке:", pl["rows"], pl["lines"])
    check(pl["rows"][0][:4] == ["gemma", "≈30.0", "GPU 0–1", "estimate"] and pl["rows"][0][4:] == [True, True], "то, что будет запущено, — первым, с «≈», пунктирным цветом; выбирается как все")
    check([row[1] for row in pl["rows"][1:3]] == ["8.0", "4.0"], "дальше работающие, самая большая первой")
    check(all(k[2] == "estimate" and k[1] == 0 and k[3] is True for lane in pl["lines"] for k in lane if k[0] == "22007") and sum(1 for lane in pl["lines"] for k in lane if k[0] == "22007") == 2,
          "линия того, что будет запущено, занимает первое место и рисуется всегда")
    check(pl["html"].startswith('<div class="machine-rack"><div class="machine-rack-lanes"><div class="ui-lane-heads" style="--lane-slots: 1"><div class="ui-lane-metrics"><span class="ui-lane-metric">LOAD</span><span class="ui-lane-metric">MEMORY, GB</span><span class="ui-lane-metric">POWER</span></div></div><div class="ui-lane ui-lane--rack"')
          and '</div></div><div class="ui-legend"><div class="ui-legend-row ui-legend-heads"><span></span><span></span><span class="ui-legend-figure">GB</span><span></span><span class="ui-legend-speed">t/s</span></div><button type="button" class="ui-legend-row ui-lane-c ui-lane-c--estimate is-on"' in pl["html"],
          "стойка: заголовки столбцов, полосы, рядом список со своими единицами")
    m3, m4, mr = r["metrics"]
    check([x["word"] for x in m3] == ["34%", "6.2 / 24.0", "117.7 W"] and m3[0]["attrs"] == 'data-t="machine-map-metric" data-t-id="gpu-3:load" data-machine-chart="node:h1:gpu"'
          and m3[0]["valAttrs"] == 'data-node-metric-val="h1:gpu:3"' and m3[1]["sparkAttrs"] == 'data-node-metric-spark="h1:mem:3"' and m3[2]["valAttrs"] == 'data-node-metric-val="h1:power:3"',
          "у карты свои загрузка, память и мощность, с ключами монитора; нажатие открывает график машины")
    check([x["word"] for x in m4] == ["—", "— / 24.0", "—"], "negative: что карта не сказала, то прочерк, а не ноль")
    check([x.get("word") for x in mr] == ["13%", "8.0 / 60.5", None] and mr[0]["valAttrs"] == 'data-node-metric-val="h1:cpu"' and mr[1]["valAttrs"] == 'data-node-metric-val="h1:ram"' and mr[2] == {} and "data-machine-chart" not in mr[0]["attrs"],
          "у RAM загрузка процессора и занятая память; negative: мощности у неё нет, ячейка пустая")
    check('data-machine-chart="node:h1:vram" data-t="machine-map-total" data-t-id="vram"><span data-node-metric-val="h1:vram">—</span>' in r["totals"] and "All cards" in r["totals"], "итог по всем картам в шапке блока, с теми же ключами монитора, что и раньше")
    check(r["noTotals"] == "", "negative: карт нет — итога нет")
    check(r["speed"] == ["38", "", "", ""] and r["speedRow"] == "52", "скорость модели в её строке, только пока она отвечает; negative: удержанная скорость и не сказанная — пусто")
    check('<p class="ui-legend-empty">Nothing holds memory here</p>' in r["emptyHtml"], "negative: память никто не занимает — так и сказано, список не пуст молча")
    check(r["smallPlan"]["rows"][0][0] == "22007" and r["smallPlan"]["rows"][0][1].startswith("≈") and float(r["smallPlan"]["rows"][1][1].split()[0]) > float(r["smallPlan"]["rows"][0][1][1:].split()[0]),
          "то, что будет запущено, первым, даже когда оно меньше работающей")
    check(r["smallPlan"]["slots"] == [["22007", 0], ["22020", 1]], "линия того, что будет запущено, на первом месте и рядом с чужой линией")
    check(r["order"] == [["22001", "22020"], ["22020", "22001"]], "список по размеру: самая большая первой, и порядок идёт за цифрами")
    check(r["priceInRow"] == "9.0 GB goes to RAM · the processor computes it", "цену RAM говорит и строка ячейки: полосы под стойкой больше нет")
    check(r["price"] == ["9.0 GB goes to RAM · the processor computes it", "fits on the cards", "9.0 GB goes to RAM", "9.0 GB goes to RAM"],
          "цена RAM сказана на панели, раз на полосе слов нет: считает процессор — только у llama.cpp с частью на картах; negative: у vLLM и без карт этого не сказано")
    check(r["card0"]["links"] == [{"slot": 0, "up": False, "down": True, "here": True, "from": r["card0"]["links"][0]["from"], "owner": "22020", "shown": True, "series": 4}]
          and r["card1"]["links"] == [{"slot": 0, "up": True, "down": False, "here": True, "from": r["card1"]["links"][0]["from"], "owner": "22020", "shown": True, "series": 4}]
          and r["card0"]["links"][0]["from"] == 50 and r["card1"]["links"][0]["from"] == 25.15
          and r["ram"]["links"] == [], "линия идёт от первой карты до второй, с начала свободной части бруска, и не заходит в ОЗУ, где куска нет")
    skip = r["skip"]
    check(skip[0][0][0]["down"] is True and skip[1][0] == [{"slot": 0, "up": True, "down": True, "here": False, "from": 0, "owner": "22020", "shown": False, "series": 1}]
          and skip[1][1] == [] and skip[2][0][0]["up"] is True and skip[2][0][0]["down"] is False,
          "ячейка на 1-й и 3-й картах: линия проходит мимо 2-й, там ни куска, ни подписи")
    check('class="ui-lane-link ui-lane-c is-up is-down" data-lane-owner="22020"' in r["skipHtml"] and "ui-lane-lead" not in r["skipHtml"],
          "negative: на пропущенной карте линия без точки и без отвода к бруску")
    check(r["blind"][1][1:] == [0, 0] and r["blindWords"] == "1.0 GB · 13% of the card" and r["blind"][0][2] == 0,
          "negative: у карты без размера нет ни подписи, ни линии, и кусок на ней не считается частью")
    check(r["noCell"][0][1:] == [[], []], "negative: нет ячеек — нет подписей и линий")
    check(r["strata"] == [[["30.0 GB · the most used weights · the card computes"], ["30.0 GB"], 1],
                          [["39.0 GB · all its weights · the processor computes the rest"], ["39.0 GB"], 1]],
          f"Strata: кусок на карте и её RSS в ОЗУ — два куска, сшитых линией, и каждый говорит, что он такое, а не «часть 1 из 2» (получено {r['strata']})")
    check(r["mapped"] == [[["30.0 GB · 94% of the card · Strata"], 1], [[], 0]],
          "negative: у ячейки на карте, что просто отображает файл, RSS в ОЗУ не рисуется: те же страницы не её (как и было)")


def section_rides(got):
    print("веса vLLM в RAM, едут на карту:")
    r = got["rides"]
    check(r["fits"] == {"verdict": "rides", "cards": [["1", 28, 20, 8]], "ram": [12, None, None], "need": 28},
          f"карта и её доля как всегда, на ней меньше весов и больше кэша; в RAM сказанное; вердикт свой (получено {r['fits']})")
    check(r["none"]["verdict"] == "card" and r["none"]["ram"][0] == 0, "negative: ничего не оставили: обычная ячейка на карте")
    check(r["short"]["verdict"] == "none", "negative: в RAM столько нет: не влезет, как и при нехватке карты")
    check(r["blind"]["verdict"] == "rides", "negative: машина не сказала, что занято в RAM: не отказ, а сказанное как есть")
    check(r["over"]["verdict"] == "none", "negative: и так не влезает на карту: не влезет")
    check(r["words"] == "12.0 GB stays in RAM and comes to the card for every pass" and r["tone"] == "idle", "панель называет цену словами, и план не зелёный: будет медленнее")
    check(r["keeps"] == [False, True, True, False],
          "vLLM держит RAM только с весами в ней: реестр говорит за весь раннер, а ячейка без них рисуется как прежде; Strata как была; negative: реестр не сказал — нет")
    check(r["said"] == 7.5 and r["field"] == "7.5", "строитель читает поле и переносит то, что посчитало правило")
    p = got["planMap"]["rides"]
    print_lanes = p["lanes"]
    check(print_lanes[1]["blocks"] == [["22020", "estimate", 20480], ["22020", "estimate-cache", 8192]] and print_lanes[2]["blocks"] == [["22020", "estimate", 12]],
          "на карте пунктиром веса и кэш, в RAM пунктиром то, что едет")
    check(print_lanes[1]["notes"] == ["≈28.0 GB · part 1 of 2 · vLLM"] and print_lanes[2]["notes"] == ["≈12.0 GB · part 2 of 2 · vLLM · comes to the card for every pass"],
          f"подпись в RAM говорит, что считает всё равно карта: это не «считает процессор» llama.cpp (получено {print_lanes[2]['notes']})")
    check(print_lanes[0]["grips"] == [] and print_lanes[1]["grips"] == [] and print_lanes[2]["grips"] == [[True, "Drag: how much of it lies on RAM"]],
          "ручка одна, на RAM: доля карты — GPU_MEMORY_UTILIZATION, её ручка не трогает")
    check(print_lanes[1]["links"] == 1 and print_lanes[2]["links"] == 1, "куски сшиты линией, как у других")
    check("12.0 GB stays in RAM and comes to the card for every pass" in p["panel"] and "CPU_OFFLOAD_GB=12" in p["panel"] and "<b>→ GPU 1 · RAM</b>" in p["panel"],
          "строка плана: куда, какая цена и что изменится")
    check("not counted" not in got["planMap"]["ridesSize"], f"negative: доля RAM посчитана: «не считается» здесь неправда (получено {got['planMap']['ridesSize']})")
    run = got["planMap"]["ridesRunning"]
    check(run == [[], ["28.0 GB · part 1 of 2 · vLLM"], ["14.0 GB · part 2 of 2 · vLLM · comes to the card for every pass"]],
          f"работающая: кусок в RAM — её RSS, и подпись та же (получено {run})")


def section_plan_map(got):
    print("план на стойке:")
    p = got["planMap"]
    off = p["off"]
    check(off["chosen"] == "" and all(not l["grips"] for l in off["lanes"]), "negative: плана нет и никто не выбран — ни пунктира, ни ручек")
    on = p["on"]
    check(on["chosen"] == "22020" and [b for b in on["lanes"][1]["blocks"]] == [["22020", "estimate"], ["22020", "estimate-cache"]],
          "план: его ячейка выбрана, на карте её пунктир — веса и кэш")
    check(on["lanes"][1]["notes"] == ["≈20.0 GB · 63% of the card · layers 0–19"], f"подпись: сколько, сколько карты, какие слои (получено {on['lanes'][1]['notes']})")
    g1 = on["lanes"][1]["grips"][0]
    check(g1[0] is True and g1[2] == "Drag: how much of it lies on GPU 1" and 'data-machine-grip="1"' in g1[3] and 'data-machine-grip-from="0"' in g1[3] and 'data-machine-grip-whole="32"' in g1[3]
          and 'data-machine-grip-holds="20"' in g1[3] and 'data-t="machine-map-grip" data-t-id="1"' in g1[3] and g1[1] == 62.51,
          f"заполненная ручка на конце куска: откуда начинается доля, сколько всего, сколько держит (получено {g1})")
    g0 = on["lanes"][0]["grips"][0]
    check(g0[0] is False and g0[2] == "Drag: put a part of it on GPU 0" and 'data-machine-grip-from="12"' in g0[3] and 'data-machine-grip-holds="0"' in g0[3],
          "на карте с местом, где куска нет, — полая ручка: добавить её")
    check(on["lanes"][2]["grips"][0][0] is False, "и на RAM — полая")
    planned = launch_of(on["panels"], 22020)
    check('data-t-state="planned"' in planned and "<b>→ GPU 1</b>" in planned and "data-machine-plan-start" in planned and "Start here" in planned
          and "data-machine-plan-cancel" in planned and "changes " in planned and 'data-machine-panel="22007"' in on["panels"],
          "строка плана: куда, что поменяется, своя кнопка запуска и отмена; у других последняя строка на месте")
    check('data-t="machine-model-window"' in planned or "data-cell-window-open" not in planned, "negative: кнопки самой строки на месте")
    check("DEVICE=CUDA1" in on["panels"] and "THREADS=" not in on["panels"].split("changes ")[1].split("<")[0],
          "в словах только то, что отличается от сохранённого: потоков было столько же")
    check(p["busy"].count("disabled") == 2, "пока запуск идёт, обе кнопки плана закрыты")
    fz, uf = p["frozen"], p["unfrozen"]
    check(fz["verdict"] == "card" and [c["gb"] for c in fz["cards"]] == [20] and fz["ramGb"] == 0,
          f"defect-history (1.3.695, стенд): пока идёт запуск, план рисуется на показанной машине, а не на чтении карт, отставшем от стопа (получено {fz})")
    check(uf["verdict"] != "card" and uf["ramGb"] > 0, f"negative: без запуска — по живой машине, где карта занята (получено {uf})")
    check(p["othersLive"] is True, "negative: замороженная машина только у ячейки плана: другие ячейки считаются по живой")
    dr = p["dragging"]
    check(all(not l["grips"] for l in dr["lanes"]), "negative: пока тащат, ручек нет: план не утверждён")
    check('data-machine-drop="ok"' in dr["lanes"][1]["attrs"] and "data-machine-drop" not in dr["lanes"][0]["attrs"] and 'data-machine-drop="no"' in p["draggingNo"],
          "полоса под указателем говорит, ляжет ли; другие молчат")
    ev = p["evict"]
    check(ev["holders"] == [] and [b[0] for b in ev["lanes"][0]["blocks"]] == ["22020", "22020"] and ev["lanes"][0]["free"] == "≈4.0 free",
          "вытесняемая не рисуется, её место считается свободным, а «свободно» — то, что останется после плана, и со знаком оценки")
    check(ev["bench"] == [22007, 22020] and "gives way: :22007" in ev["panels"], "но в списке она есть, и строка плана говорит, кто уступит")
    mv = p["moved"]
    moved_line = re.search(r'<span class="machine-pick-words">(.*?)</span>', mv["choice"]).group(1)
    standing_line = re.search(r'<span class="machine-pick-words">(.*?)</span>', on["choice"]).group(1)
    check("<b>→ GPU 1 · RAM</b> 7.6 GB goes to RAM · the processor computes it · changes " in moved_line,
          f"работающая: куда ляжет — словами, в её второй строке этого нет (получено {moved_line})")
    check(re.search(r"</b> changes ", standing_line) is not None,
          f"negative: стоящая: сразу что изменится, куда ляжет уже сказала её вторая строка (получено {standing_line})")
    check([b[0] for b in mv["lanes"][0]["blocks"]] == [] and [b for b in mv["lanes"][1]["blocks"]][0] == ["22007", "estimate"] and "Restart here" in mv["panels"],
          "перенос работающей: со старой карты убрана, на новой пунктиром, кнопка «Перезапустить здесь»")
    check("disabled" in p["noFit"].split('data-t-state="planned"')[1] and "machine-pick--bad" in p["noFit"] and "won&#39;t fit now" in p["noFit"].replace("won't", "won&#39;t"),
          "не влезает: запуск закрыт, строка плана красная и говорит почему")
    check(p["chosenNoPlan"] == [1, 1, 1], "у выбранной стоящей llama.cpp ручки есть и без плана: первый сдвиг его создаст")
    check(p["chosenPinned"] == [0, 0, 0], "negative: у сервера одной карты долей нет")
    check(p["fullCard"] == [0, 1, 1], "negative: на полной карте полой ручки нет: положить туда нечего")
    pl = p["places"]
    check(pl["llama"] == ["0", "1", "ram"] and pl["running"] == ["0", "1", "ram"], "кнопки куда положить: каждая карта и RAM, у стоящей и работающей")
    check('title="Lay it on GPU 0" data-machine-place="0" data-machine-place-for="22020" data-t="machine-place" data-t-id="0"' in pl["html"] and pl["html"].endswith(">GPU 0"), "кнопка говорит, что делает, и чью ячейку кладёт")
    check(pl["cardOnly"] == ["0", "1"], "раннер только для карты: без RAM")
    check(pl["engine"] == [] and pl["noStart"] == [] and pl["noStop"] == [], "negative: ячейка движка, ячейка без запуска и без остановки: кнопок нет")
    lv = p["live"]
    check(lv["quiet"] == 0 and lv["laid"] == [1, True] and lv["again"] == 1 and lv["cleared"] == [2, False], "последняя строка пишется целиком только когда план поменялся")
    check(p["otherCell"] == [False, "22007"], "выбрал другую ячейку: план снят")
    check(p["sameCell"] == [True, "22020"], "negative: выбрал свою: план на месте")


def main():
    node = find_node()
    if node is None:
        print("js machine-head: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_machine_head.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "i18n", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True, text=True, cwd=ROOT,
                              env=env, timeout=90)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js machine-head: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:2000])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    choose = " — click to choose"

    print("полосы карт:")
    check(got["holders"] == [[22001, 1], [22003, 2], [22010, 3], [22020, 4]],
          "держат память работающие и прогревающиеся ячейки, по порту, у каждой свой цвет; negative: остановленная (:22007) и "
          "порт без модели — не держат")
    c0 = got["card0"]
    check(c0["label"] == "GPU 0" and c0["side"] == "RTX 3090 · 24.0 GB · 52 °C" and c0["free"] == "12.0 free" and c0["total"] == 24576,
          "карта: номер, имя без «NVIDIA GeForce», объём и температура рядом; справа — сколько свободно; числа скаута, хотя он пишет их строкой")
    check(c0["blocks"] == [
        {"value": 1024, "kind": "other", "name": "Xorg", "short": "Xorg", "figure": "1.0 GB", "title": "Xorg · 1.0 GB", "owner": ""},
        {"value": 1024, "kind": "other", "name": "other processes", "short": "other processes", "figure": "1.0 GB", "title": "other processes · 1.0 GB", "owner": ""},
        {"value": 2048, "series": 3, "name": ":22010 gemma-4-12B-it", "figure": "2.0 GB", "short": "2.0", "on": False, "port": "22010",
         "title": ":22010 gemma-4-12B-it · 2.0 GB" + choose, "owner": "22010", "pick": True},
        {"value": 8192, "series": 4, "name": ":22020 Hermes-4-70B", "figure": "8.0 GB", "short": "8.0", "on": True, "port": "22020",
         "title": ":22020 Hermes-4-70B · 8.0 GB" + choose, "owner": "22020", "pick": True}],
          "блоки: чужой процесс штриховкой по имени, остаток занятого — «другие процессы», ячейки — своим цветом по замеру gpuMem, "
          "с портом и именем; выбранная — on; negative: остановленная :22007 с её 9999 MiB не нарисована, чужие — не кнопки")
    check(got["card0Pick"] == 'data-machine-pick="22020" data-t="machine-map-block" data-t-id="22020"',
          "блок ячейки — кнопка выбора с меткой для теста")
    check(c0["attrs"] == 'data-t="machine-map-lane" data-t-id="gpu-0"' and c0["foot"] == "", "метка полосы для теста; negative: подписи под полосой нет")
    c1 = got["card1"]
    check(c1["side"] == "RTX 5090 · 31.8 GB · 48 °C" and c1["free"] == "23.8 free"
          and [b.get("series") for b in c1["blocks"] if "series" in b] == [4]
          and c1["blocks"][0] == {"value": 4104, "kind": "other", "name": "other processes", "short": "other processes", "figure": "4.0 GB", "title": "other processes · 4.0 GB", "owner": ""},
          "та же ячейка на второй карте — тем же цветом (4): одна ячейка — один цвет на всех полосах")
    check(got["seven"] == [1, 2, 3, 4, 5, 6, 1], "boundary: седьмая работающая ячейка — снова первый цвет: цветов шесть, они идут по кругу")
    b = got["blind"]
    check(b[0]["total"] is None and b[0]["free"] == "" and b[0]["foot"] == "the scout does not report this card's memory"
          and "ui-lane-bar" not in got["blindHtml"] and "&lt;b&gt;" in got["blindHtml"] and "<b>" not in got["blindHtml"],
          "negative: объём карты не сказан — полосы нет вовсе (пустая читалась бы как свободная карта), «свободно» нет, причина сказана; "
          "имя карты экранировано")
    check(b[1]["total"] is None and b[1]["foot"] == "the scout does not report the RAM" and b[1]["side"] == "",
          "negative: RAM не сказана — тоже без полосы и со словами почему; загрузки CPU нет — нет и подписи")
    check(got["blindUnplaced"] == [22002] and 'data-t="machine-map-unplaced-cell"' in got["blindHtml"],
          "ячейка на карте, чья полоса не нарисована, — не пропала: названа под полосами")

    print("полоса RAM:")
    r = got["ram"]
    check(r["label"] == "RAM" and r["side"] == "60.5 GB · CPU 1.2%" and r["free"] == "51.7 free" and r["total"] == 60.5,
          "RAM: объём и загрузка процессора рядом, свободно справа")
    check(r["blocks"] == [
        {"value": 5.800000000000001, "kind": "other", "name": "the system and other processes", "short": "system", "figure": "5.8 GB",
         "title": "the system and other processes · 5.8 GB", "owner": ""},
        {"value": 3, "series": 1, "name": ":22001 Qwen3-Embedding-0.6B", "figure": "3.0 GB", "short": "3.0", "on": False, "port": "22001",
         "title": ":22001 Qwen3-Embedding-0.6B · 3.0 GB · RSS of its processes" + choose, "owner": "22001", "pick": True}],
          "в RAM — ячейка без карты по её RSS; остальное занятое — система и другие процессы; negative: ячейки на картах (:22020 с RSS "
          "41 ГБ, :22010) не нарисованы — их RSS считает отображённый файл модели, а «занято» машины его не считает")
    check(got["unplaced"] == [22003] and 'data-machine-pick="22003" data-t="machine-map-unplaced-cell" data-t-id="22003"' in got["html"]
          and "Running, memory not measured:" in got["html"] and ":22003 gigaam &lt;v3&gt;" in got["html"],
          "работающая ячейка, чью память никто не замерил, — не пропала с карты: названа под полосами, её можно выбрать; имя экранировано")
    check(got["capped"] == [[3, "3.0 GB", 1], [1, "3.0 GB", 2]],
          "boundary: ячейки не рисуются дальше занятого машиной (4 ГБ): вторая обрезана до остатка, подпись — её настоящий RSS")
    check(got["unnamed"][1] == ":22001", "negative: строитель не назвал ячейку — блок назван портом, а не пустым местом")
    check('aria-label="What lies where"' in got["html"] and '<strong class="machine-map-title">What lies where</strong>' in got["html"]
          and "drag a model from below" in got["html"] and '<i class="is-weights" aria-hidden="true"></i>weights<i class="is-cache" aria-hidden="true"></i>cache and buffers' in got["html"]
          and got["html"].count('data-t="machine-map-lane"') == 3
          and '<button type="button" class="ui-lane-blk ui-lane-blk--s4 is-on"' in got["html"] and "data-machine-map>" in got["html"]
          and "data-machine-picks" not in got["html"] and "machine-pick\"" not in got["html"],
          "карта: заголовок и как её читать, три полосы (ui-parts Lane), блок ячейки — кнопка (её достаёт клавиатура), выбранная "
          "обведена; negative: полосы выбранной ячейки под стойкой нет (владелец, 2026-11-02)")

    print("строка выбранной ячейки:")
    p = got["panels"]
    check('data-machine-panel="22020" data-machine-own data-t="machine-pick" data-t-id="22020">' in p
          and 'data-machine-panel="22001" data-machine-own data-t="machine-pick" data-t-id="22001" hidden' in p,
          "последняя строка есть у каждой ячейки: у выбранной (:22020) открыта, у остальных спрятана")
    hermes = launch_of(p, 22020)
    check('data-machine-bench-size="22020">12.0 GB on the cards</span>' in hermes and 'data-t-state="running">running</span>' in hermes
          and 'data-cell-window-open="box:22020" data-t="machine-model-window" data-t-id="22020">Cell window</button>' in hermes
          and 'class="ui-btn ui-btn--main ui-btn--danger" title="Stop server" data-node-cell-stop="box" data-node-cell-port="22020" data-t="machine-model-stop" data-t-id="22020">Stop</button>' in hermes,
          "строка :22020: что делает и сколько держит на картах; «Окно ячейки» — ключом её окна, «Остановить» — атрибутами доски (тот же вопрос, то же действие)")
    gemma = launch_of(p, 22010)
    check("machine-bench-fit--busy" in gemma and "loading its weights" in gemma and 'data-machine-bench-size="22010">2.0 GB on the cards<' in gemma
          and "data-cell-window-open" not in gemma and 'data-node-cell-port="22010"' in gemma,
          "грузит веса — жёлтые слова; negative: окна у неё строитель не рисовал (полная карточка) — кнопки окна нет")
    giga = launch_of(p, 22003)
    check("memory not measured" in giga and 'title="Not running" data-t="machine-model-stop" data-t-id="22003" disabled' in giga
          and "data-node-cell-stop" not in giga,
          "negative: остановить нельзя — кнопка закрыта и говорит почему, без атрибутов доски; память не замерена — так и сказано")
    last_lines = lambda html: re.findall(r'<div class="machine-pick[^"]*" data-machine-panel="\d+"[^>]*>', html)
    check(len(last_lines(got["noChoice"])) == 6 and all(line.endswith(" hidden>") for line in last_lines(got["noChoice"]))
          and "Choose a cell" not in got["noChoice"] and 'data-machine-panel="22007"' in got["noChoice"] and 'data-machine-panel="22014"' in got["noChoice"],
          "ничего не выбрано — последние строки всех шести ячеек спрятаны: и тех, что держат память, и стоящих; negative: никакой «Выберите ячейку»")
    check(all(line.endswith(" hidden>") for line in last_lines(got["staleChoice"])) and len(last_lines(got["staleChoice"])) == 6,
          "negative: выбран порт, которого у машины нет, — все спрятаны")
    stopped = launch_of(got["stoppedChoice"], 22007)
    check('data-t="machine-pick" data-t-id="22007">' in stopped
          and 'data-machine-bench-size="22007">size not known</span>' in stopped and '>place not known</span>' in stopped
          and 'data-t="machine-model-start" data-t-id="22007" disabled>Start</button>' in stopped and "data-node-cell-stop" not in stopped,
          "остановленную ячейку можно выбрать: её кнопка — «Запустить», а не «Остановить»; строитель не сказал ни размера, ни "
          "запуска — так и сказано, кнопка закрыта")
    check(got["words"] == ["12.0 GB on the cards", "3.0 GB in RAM", "memory not measured", "2.0 GB on the cards"]
          and got["zeroRss"] == "memory not measured",
          "что держит: на картах — сумма по картам; без карт — RSS; не сказано — «не замерена»; negative: RSS 0 у живого процесса — не «0 ГБ»")
    check(got["brokenSub"] == ["its process runs, its engine does not answer", "1.0 GB on the cards"], "сломанная: процесс жив, движок молчит — словами")
    tr = got["trouble"]
    check(tr[0] == ["busy", "crashed", "running · 💥 crashed 2× since it was last started by hand", "1.0 GB on the cards", True]
          and tr[1] == ["bad", "unreachable", "running · ⚠ port unreachable from server — open the host firewall for this port · "
                        "💥 crashed 1× since it was last started by hand", "1.0 GB on the cards", True],
          "defect-history (2026-10-26): ячейка в беде на странице машины — только окно, и беду говорит её строка, у каждой ячейки, а не только у выбранной: падала (сторож "
          "поднял) — янтарная и «💥 crashed 2×…», контроллер не достаёт — красная и словами; кнопка окна у обеих")
    check(tr[2] == ["good", "running", "running", "1.0 GB on the cards", True],
          "negative: без беды (0 падений, порт доступен) — зелёная, без лишних слов")

    print("полоса статуса в строке шапки:")
    bd = got["band"]
    check(bd["good"] == ["good", "Cells running: 4 of 5", ""], "работает — зелёная: сколько из скольких (порт без модели не в счёте); второй строки нет — её говорят полосы")
    check(bd["warming"] == ["busy", "Starting :22010 · running 3 of 5", ""],
          "ячейка грузит веса — жёлтая: какая в пути (одна — названа, 1.3.657) и сколько уже работает, одной строкой")
    check(bd["silent"] == ["bad", got["en"]["silent"], "<span data-live-hostage>7 min</span>"],
          "машина молчит — красная, и сколько молчит, в живом месте для патча")
    check(bd["coming"] == ["busy", "Starting :1 · running 1 of 2", ""] and bd["idle"] == ["idle", "No cell is running", ""]
          and bd["empty"] == ["No cells yet", "No cells yet"],
          "в пути — жёлтая; ни одна не работает — тихая; нет ни одной ячейки — так и сказано")
    check(bd["named"] == "Starting :22020 Hermes-4-70B · running 1 of 2" and bd["two"] == ["busy", "Starting 2 · running 1 of 3", ""],
          "1.3.657 (владелец 2026-10-26: «где видно, какая ячейка запускается?»): одна в пути — шапка её называет, порт и имя, как "
          "плашка под картой; negative: две — только сколько, имена — в строке под картой")
    check(bd["controller"] != "bad", "negative: молчание — только у машины со скаутом")
    check(bd["html"] == '<div class="ui-band ui-band--good ui-band--inline" role="status" data-machine-band data-t="machine-band" data-t-state="good">'
          '<span class="ui-band-dot" aria-hidden="true"></span><div class="ui-band-text"><strong class="ui-band-title">Cells running: 4 of 5</strong></div></div>',
          "полоса — часть Band в строке (inline), с меткой и тоном для теста и для живого патча")

    print("паспорт:")
    h = got["head"]
    check(h["facts"] == "host · linux · 10.0.0.5 · scout 2.37.0", "кто это: роль, платформа, адрес, версия скаута")
    check(h["factsRelease"] == "host · linux · 10.0.0.5 · scout 33dbf22e", "скаут, назвавший свой выпуск: номер выпуска, версия стоит на месте")
    tools = h["html"][h["html"].index('<div class="machine-tools">'):h["html"].index('<div class="ui-win-body">')]
    check('<h1 class="ui-win-title">Box &lt;A&gt;</h1>' in h["html"] and 'class="ui-win ui-win--page"' in h["html"]
          and '<span class="node-scout-old">⚠ old</span>' in h["html"] and 'data-machine-head' in h["html"]
          and 'class="ui-win-band"' not in h["html"]
          and tools.index("data-machine-band") < tools.index('data-t="machine-menu"') < tools.index('data-t="machine-add"')
          and '<div class="ui-win-body"><section class="machine-map"' in h["html"],
          "шапка — одна строка: имя (h1, экранировано), метка старого скаута, справа — что делает, «⋯» и «Добавить модель»; под ней — карта; "
          "negative: отдельной полосы-карточки больше нет")
    check(h["add"] == '<button type="button" class="ui-btn ui-btn--main" title="on :22030" data-t="machine-add" data-t-id="box" data-caravan-add="box">'
          + h["add"][h["add"].index("<svg"):h["add"].index("</svg>") + 6] + "Add model</button>",
          "главная кнопка — «Добавить модель» с атрибутом, по которому её слушает доска (data-caravan-add)")
    check("disabled" in h["addBusy"] and "data-caravan-add" not in h["addBusy"] and f'title="{got["en"]["busy"]}"' in h["addBusy"],
          "negative: пока резервируется ячейка — кнопка закрыта и не слушается, причина в подсказке")
    for attr, hook in (('data-reboot-host="box"', "node-reboot"), ('data-power-schedule-host="box"', "node-power-schedule"),
                       ('data-poweroff-host="box"', "node-poweroff"), ('data-scout-update="box"', "node-scout-update"), ('data-scout-disconnect="box"', "node-disconnect")):
        check(attr in h["menu"] and f'data-t="{hook}" data-t-id="box"' in h["menu"],
              f"в «⋯» — {hook}: атрибут, по которому кнопку слушает доска, и прежняя метка теста")
    check("23:30" in h["menu"], "заданное расписание выключения — в подсказке пункта")
    check(h["menu"].count("ui-menu-item--danger") == 2 and 'role="separator"' in h["menu"],
          "выключить и отпустить скаута — красные; отпускание — после черты")
    check("data-scout-disconnect" not in got["noScoutMenu"] and 'role="separator"' not in got["noScoutMenu"],
          "negative: у машины без скаута отпускать некого — пункта нет")

    print("выбор ячейки:")
    check(got["choose"] == ["22020", True, "", False, "22001", False, 0, 4],
          "выбор — порт строкой; выбранная снова — отпущена; negative: пустой порт — не выбор; знания строителя — только карта, иначе пусто")
    sh = got["show"]
    check(sh["one"] == {"on": [[False, "false"], [True, "true"], [True, "true"]], "shown": ["22001"]},
          "показ без перерисовки: блоки выбранной обведены и aria-pressed (на всех полосах), открыта последняя строка её ряда")
    check(sh["letGo"] == {"on": [[False, "false"], [False, "false"], [False, "false"]], "shown": []},
          "отпущена — ни один блок не обведён, последних строк нет")
    check(sh["stale"]["shown"] == [], "negative: выбрана ячейка, которой тут нет, — ничего не открыто")
    check(sh["row"] == {"row": [True, None], "port": [True, "true"], "heard": ["the page"]},
          "строка ячейки обведена, но она не кнопка: «нажата» говорит её порт; negative: у строки aria-pressed нет; список моделей слышит о выборе")
    bn = got["bind"]
    check(bn["listeners"] == 3, "привязан дважды — слушает один раз: нажатие и два указателя")
    check(got["chartClick"] == [["node:h:gpu"], ""], "нажатие на показатель открывает график, ячейку не выбирает: слушатель общий, полосы пишутся заново между перерисовками")
    lt = got["light"]
    check(lt["lit"] == ["22020", True, [True, False, True]], "указатель на ячейке: её куски подсвечены на всех полосах, стойка знает, что идёт подсветка")
    check(lt["again"] == 0, "negative: та же ячейка под указателем — страницу не трогаем на каждое движение")
    check(lt["other"] == ["22001", True, [False, True, False]], "другая ячейка: подсветка переходит")
    check(lt["off"] == ["", False, [False, False, False]], "указатель ушёл: всё как было")
    check([lt["onOwner"], lt["offOwner"], lt["stays"], lt["leftPage"]] == ["22001", "", "22001", ""], "слушатели: на ячейке, мимо, уход на другой элемент ничего не значит, уход со страницы снимает")
    check(lt["dragging"] == "", "negative: во время перетаскивания подсветка молчит: на полосах план")
    check(lt["shown"] == [False, True], "линия выбранной ячейки рисуется без перерисовки доски")
    check(bn["afterShown"] == ["22020", 0], "щелчок по блоку — выбор и показ на месте: окно ячейки в странице есть, доска не перерисована")
    check(bn["afterHidden"] == ["22001", 1, ["machine-map-block:22001"]],
          "окна выбранной в странице нет (список прячет её фильтром) — доска рисуется заново: выбранная ячейка тогда остаётся в списке; "
          "клавиатура возвращается на её блок")
    check(bn["afterFull"] == ["22010", 1],
          "negative: ячейка, нарисованная полной карточкой, окна не имеет — выбор показан на месте, доска не перерисована зря")
    check(bn["afterMiss"] == ["22010", 1], "negative: щелчок мимо блока выбора не трогает")
    check(bn["brought"] == [{"block": "nearest"}],
          "выбранная ячейка: её строка приезжает в вид настолько, насколько нужно; negative: снятие выбора и документ без строки ничего не двигают")

    print("живой патч:")
    lv = got["live"]
    check((lv["facts"], lv["factsWrites"]) == ("host · linux · 10.0.0.5 · scout 2.37.0", 1), "шапка догоняет скаута под открытой страницей (Update the scout): новые слова пишутся один раз, а не на каждый такт")
    check(lv["mapWrites"] == 1, "полосы карты переписаны один раз: второй тик с теми же числами не трогает их")
    check(lv["rowSize"] == "12.0 GB on the cards" and lv["rowSizeWrites"] == 1,
          "слова строки ячейки — на месте, один раз: её кнопки «Окно» и «Остановить» не перерисованы и держат фокус")
    check(lv["bandWrites"] == [] and lv["title"] == "Cells running: 4 of 5",
          "тот же тон — у полосы меняются только слова на месте")
    check(lv["toneChange"] == ["outer"], "тон сменился — полоса нарисована заново целиком")
    check(lv["empty"] == "quiet", "negative: на странице без головы машины патч молчит, не падает")
    print("панели страницы машины:")
    pn = got["panes"]
    check(pn["tops"] == [640, 0] and pn["drawn"] == "<new>" and pn["main"] == 640,
          "доска нарисовала страницу заново: панель с ячейками осталась на своём месте, а не прыгнула наверх")
    check(pn["side"] == 0, "negative: панель, стоявшая наверху, не трогается")
    check(pn["noPage"] == [0, 0] and pn["noRoot"] == [0, 0] and pn["boardDrawn"] == "<cards>",
          "negative: на главной доске панелей нет: она рисуется как рисовалась")
    section_rack(got)
    section_plan_map(got)
    section_rides(got)
    ip = got["inPlace"]
    check(ip["rowOn"] == [["22020", "true"]], "строка выбранной ячейки в списке после правки на месте тоже помечена")
    check(ip["notes"]["writes"] == 0 and "11.0" in ip["notes"]["figures"] and "GPU 0: 7.0 GB · part 1 of 2" in ip["notes"]["title"] and ip["notes"].get("lead") == "45.84",
          f"цифры на карте сдвинулись — слова подписи и отвод куска правятся на месте, полосы не переписаны (получено {ip['notes']})")
    check(ip["first"] == {"map": 0, "inner": 0},
          "полосы, нарисованные доской, тем же набором блоков — патч не переписывает их целиком и не трогает слова внутри блоков")
    check(ip["after"]["map"] == 0 and ip["free"] == "51.5 free" and ip["system"] == "9.92%",
          "занятая RAM сдвинулась — на месте поменялись «свободно» и ширина блока системы: кнопки ячеек не перерисованы, фокус и наведение "
          "остаются (щелчок не попадает между двумя переписями)")
    check(ip["chosen"] == [["22020", "true"]], "выбранная ячейка после правки на месте — по-прежнему обведена и aria-pressed")
    check(ip["letGo"] == [[], "false", 0], "выбор снят — на месте снята и обводка, и aria-pressed; полосы целиком не переписаны")
    check(ip["rowLetGo"] == [[False, "false"]], "и строка списка снята тоже")
    check(ip["speed"] == "41", "скорость модели в её строке правится на месте")
    check(ip["reshaped"] == [1, 1],
          "negative: ячейка начала держать память или её наконец замерили (из фишек — в блок RAM) — набор блоков другой, полосы "
          "переписаны целиком")

    print("куда ляжет стоящая ячейка (CellFit):")
    f = got["fit"]
    check(f["spread"][0] == ["cards", [["0", 16.92], ["1", 22.68]], 0, 39.6],
          "llama.cpp, 39.6 ГБ файлов на двух пустых картах: влезает — по картам пропорционально месту за полем --fit-target "
          "(23.0 и 30.84 ГБ за его 1024 MiB), как окно ячейки считает это место")
    check(f["spread"][1] == ["spill", [["0", 23], ["1", 30.84]], 33.36, 87.2] and f["spread"][2] == ["none", [], 0, 140],
          "не влезает на карты — карты до поля, остальное в RAM (33.36 из 51.8 свободных); negative: и в RAM не влезает — «сейчас не влезет»")
    check(f["spread"][3] == ["card", [["1", 20]], 0, 20],
          "DEVICE=CUDA1 — только вторая карта, и сказано «на GPU 1», а не «на карты»; negative: первая не нарисована")
    check(f["spread"][4] == ["spill", [["0", 20], ["1", 27.84]], 2.16, 50],
          "своё поле --fit-target (4096 MiB) — места на картах меньше: 20 и 27.84 ГБ, 2.16 уходит в RAM")
    check(f["tensor"] == [["cards", [["0", 20], ["1", 20]], 0, 40], ["none", [], 0, 60]],
          "тензорный сплит без частей — поровну, по месту меньшей карты; negative: не влезает — не влезет совсем, в RAM тензорный ничего не кладёт")
    check(f["held"][0][0] == "unknown" and f["held"][1][0] == "unknown",
          "negative: число слоёв задано руками (99) или эксперты отправлены на CPU — по размеру файлов не сказать, сколько останется на "
          "картах: «место не известно», а не догадка")
    check(f["held"][2] == ["cards", [["0", 17.09], ["1", 22.91]], 0, 40] and f["held"][3] == ["none", [], 0, 60] and f["held"][4] == ["none", [], 0, 60],
          "все слои руками (all) или подгонка выключена (FIT=0) — на карты или никуда: llama.cpp не подгоняет и в RAM не отдаёт")
    e = f["spreadEdge"]
    check(e[0] == ["ram", [], 2.8, 2.8] and e[1] == ["none", [], 0, 60],
          "машина без карт — llama.cpp считает на CPU: в RAM, пока она есть")
    check(e[2] == ["unknown", [], 0, None] and e[3] == ["unknown", [], 0, None],
          "negative: размер не известен, или он ноль (файл никто не мерил) — места нет и веса нет: в конце скамейки, а не «0 ГБ»")
    check(e[4][0] == "unknown" and e[5][0] == "unknown" and e[6][0] == "unknown",
          "negative: карта не сказала объём, DEVICE называет карту, которой нет, RAM не сказана там, где нужна, — «не известно», "
          "а не «влезет»")
    check(e[7][0] == "unknown" and e[8] == ["card", [["0", 2]], 0, 2],
          "negative: карта сказала объём, но не занятость, — свободного не известно, а не «вся свободна» (CardRoom); сказала "
          "свободное (memory.free) — его и хватает")
    c = f["card"]
    check(c[0] == ["card", [["0", 20]], 0, 20] and c[1] == ["card", [["1", 31]], 0, 31] and c[2] == ["none", [], 0, 32],
          "раннер на одной карте: без закрепления — карта 0, закреплённая в ENV — своя; целиком, до MiB: 31 ГБ на 31.8 влезает, 32 — нет")
    check(c[3] == ["card", [["0", 20]], 0, 20],
          "список «0,1» в ENV читается как закрепление за картой 0 — так ENV читает сервер (строки по переводу строки и запятой), одно правило")
    check(c[4][0] == "unknown" and c[5][0] == "unknown" and c[6][0] == "unknown",
          "negative: закреплён за картой, которой нет; размер не известен у раннера НЕ одной карты (команда, сервер, что сам выбирает "
          "устройство — карта была бы догадкой); машина без карт — «не известно», не «самая свободная карта»")
    check(c[10] == ["unsized", [["0", 0]], 0, None] and c[7] == ["unsized", [["1", 0]], 0, None],
          "раннер одной карты, размер не известен — карта всё равно названа: пин, иначе карта 0, где окажется старт; веса ей не "
          "выдумано (2026-10-27)")
    check(c[8][0] == "unknown" and c[9][0] == "unknown",
          "negative: раннер одной карты, размер не известен и карты нет — пин на чужую карту, машина без карт — «не известно»")
    u = got["unsized"]
    check(u["panel"] == u["panelWant"] and [b["state"] for b in u["bench"]] == ["unsized", "unsized"]
          and [b["words"] for b in u["bench"]] == u["benchWant"] and {b["tone"] for b in u["bench"]} == {"idle"},
          "стоящая ячейка с неизвестным размером: «размер не известен · пойдёт на GPU 0» — без пина карта 0, с пином своя; "
          "тон спокойный: «влезет» не обещано")
    check(u["foot"] == [u["footWant"][0], "", ""] and u["foot8"] == ["", u["footWant"][1], ""] and u["footNone"] == ["", "", ""]
          and u["dashed"] == 0,
          "выбрали её — под полосой её карты сказано, что она запустится здесь и сколько займёт не известно; блока не нарисовано; "
          "negative: ничего не выбрано — на полосах тихо")
    # 1.3.671 — the whole row of a cell that works is tinted (the owner, 2026-10-27: "let the running cells be pleasantly greenish,
    # or clear not only by the label"), and its dot says the same: machine.css reads the verdict's data-t-state, so its names must be the verdict's.
    css = (ROOT / "static" / "css" / "machine.css").read_text(encoding="utf-8")
    tints = {}
    dots = {}
    for selector, body in re.findall(r"(\.machine-model-launch:where\(:has\([^{]*?)\{([^}]*)\}", css):
        if ":hover" in selector:
            continue
        token = (re.search(r"var\(--ui-(good|busy|bad)\)", body) or [None, None])[1]
        tints.setdefault(token, set()).update(re.findall(r'data-t-state="(\w+)"', selector))
        dots[token] = (re.search(r"--launch-state:\s*var\(--ui-(\w+)\)", body) or [None, None])[1]
    bs = got["benchStates"]
    coming = [ph for ph in bs if ph not in ("running", "warming", "broken", "error")]
    check(tints.get("good") == {bs["running"]},
          "работающая ячейка — зелёная строка: правило стиля читает то самое состояние, что говорит её вердикт (running)")
    check(tints.get("busy") == {bs["warming"], got["trouble"][0][1], *(bs[ph] for ph in coming)},
          "грузит веса, в пути (скачивание, старт, остановка…) или падала и поднята сторожем — янтарная рамка; набор состояний стиля — ровно тот, что говорит вердикт")
    check(tints.get("bad") == {bs["broken"], bs["error"], got["trouble"][1][1]} and None not in tints,
          "сломана, не запустилась или контроллер до неё не достаёт — красная рамка; negative: стоящая (влезет / не влезет / не известно) — без цвета строки")
    dot = re.search(r"\.machine-model-dot\s*\{([^}]*)\}", css)
    check(dots == {"good": "good", "busy": "busy", "bad": "bad"} and dot is not None and "var(--launch-state, var(--ui-muted))" in dot.group(1),
          "точка у порта говорит то же из того же вердикта: работает, в пути, сломана; negative: стоящая — серая, своего цвета нет; второй копии состояния нет")
    check(f["auto"] == [["ram", [], 30, 30], ["ram", [], 2, 2], ["none", [], 0, 70]],
          "раннер, что сам выбирает устройство: карта мала — в RAM; карт нет — в RAM; negative: и RAM мала — не влезет")
    fr = f["free"]
    check(fr[0] == ["free", [["1", 31.84]], 0, 31.84] and fr[1] == ["free", [["1", 27.84]], 0, 27.84],
          "Strata берёт свободное на своей карте за вычетом резерва (FreeVramStart): 31.84 ГБ, с резервом 4096 MiB — 27.84")
    check(fr[2] == ["none", [], 0, 39.06], "negative: свободного меньше её порога — не влезет, и сколько ей нужно (39.06 ГБ)")
    check(fr[3][0] == "unknown" and fr[4][0] == "unknown" and fr[6][0] == "unknown",
          "negative: резерв не число, карта закрепления не существует, карта не сказала свободное — «не известно»")
    check(fr[5] == ["free", [["0", 24]], 0, 24], "без закрепления — карта 0, как её прочтёт сервер")
    a = f["asks"]
    check(a[0] == ["card", [["0", 21.6]], 0, 21.6] and a[1] == ["cards", [["0", 21.6], ["1", 21.6]], 0, 43.2],
          "vLLM — свою долю каждой карты, что он берёт (её считает VllmPlacement): одна карта — «на GPU 0», две — «на карты»")
    check(a[2][0] == "none" and a[3][0] == "none",
          "negative: доля больше свободного на карте, или веса не влезают в долю (weightsOver), — не запустится")
    check(a[4] == ["unknown", [], 0, None] and a[5][0] == "unknown",
          "negative: карт для доли нет (закрепление на несуществующей), карта не сказала свободное — «не известно»")
    check(f["ram"] == [["ram", [], 2.8, 2.8], ["none", [], 0, 60], ["unknown", [], 0, 2.8]],
          "ячейка на CPU — в RAM, пока хватает свободной; negative: не хватает — не влезет; RAM не сказала, сколько занято, — не известно")
    check([x[0] for x in f["none"]] == ["unknown"] * 3,
          "negative: раннер без способа (ячейка движка, команда) и неизвестный способ — «место не известно»")
    fc = got["facts"]
    check(fc["free"] == {"how": "free", "bytes": 5, "source": "files", "keepsRam": True,
                         "fields": {"ENV": "A=1", "DEVICE": "CUDA1", "FIT_TARGET": "2048", "TENSOR_SPLIT": "3,1", "FIT": "1",
                                    "N_GPU_LAYERS": "auto", "N_CPU_MOE": "2", "CPU_MOE": "0", "KV_OFFLOAD": "1", "CPU_OFFLOAD_GB": ""},
                         "mode": "layer", "model": None, "split": None, "floorMiB": 6144, "reserve": "4096", "asks": [], "over": False, "ridesGb": 0,
                         "orRam": False, "oneCard": False, "family": "", "cpuOk": False, "gpuOk": True, "onCard": "card", "parallel": False, "asksFor": None},
          "что строитель берёт из конфига ячейки и строки реестра: поля способа так, как их покажет форма (флажок KV_OFFLOAD не сказан — "
          "включён), порог и резерв Strata по имени поля из реестра; модели не дали — не известна")
    check(fc["planned"] == ["runner", "files", True] and fc["vllm"] == {"gb": 44.2, "source": "runner", "asks": [["0", 22630.4], ["1", 22630.4]], "over": True},
          "размер — «столько берёт раннер», когда это его замер или доля карт vLLM; иначе — файлы")
    check(fc["bare"]["how"] == "" and fc["bare"]["bytes"] is None and fc["bare"]["asks"] == [] and fc["bare"]["model"] is None,
          "negative: строитель ничего не сказал — ни способа, ни размера, ни модели, а не нули")
    check(fc["asksWeights"] == [["0", 22630.4, 15360], ["1", 22630.4, 15360]],
          "vLLM: веса чекпойнта (30 ГБ) поровну на две карты тензорного параллелизма, остаток доли — его кэш")

    print("точный расчёт (1.3.635):")
    ex = got["exact"]
    check(ex["facts"] == ["plan", "plan", 62.48, [39.6, 22.88]] and ex["layers"] == 80,
          "llama.cpp с моделью из библиотеки — способ «план»: весит целиком — 39.6 ГБ весов и 22.88 кэша и буферов (131072 токена q8_0 "
          "на 80 слоях — 21.25, буферы 1.63) = 62.48 ГБ, «с кэшем»")
    check(ex["spill"] == {"verdict": "spill", "cards": [["0", 22.87, 14.36, 8.52], ["1", 30.48, 19.31, 11.17]], "ram": [9.13, 5.94, 3.19],
                          "need": 62.47},
          "план окна ячейки по свободному сейчас: карты от последней до поля --fit-target — 29 и 39 слоёв, каждая с весами, кэшем своих "
          "слоёв и половиной буферов; 12 первых слоёв в RAM — 5.94 весов и 3.19 кэша")
    check(ex["fits"] == {"verdict": "cards", "cards": [["0", 17.92, 16.83, 1.09], ["1", 23.96, 22.77, 1.19]], "ram": [0, 0, 0], "need": 41.89},
          "с контекстом 4096 — влезает: слои по свободному месту 34 и 46, в RAM ничего")
    check(ex["held999"]["verdict"] == "none" and ex["held999"]["cards"] == [] and ex["held999small"] == ex["fits"],
          "N_GPU_LAYERS=999 — все 80 слоёв на картах, без подгонки: со 131072 токенами первой карте не хватит — «не влезет», пунктира нет; "
          "с 4096 — влезает (у оценки по размеру это было «место не известно»)")
    check(ex["kvRam"] == {"verdict": "kvRam", "cards": [["0", 17.64, 16.83, 0.81], ["1", 23.58, 22.77, 0.81]], "ram": [21.25, 0, 21.25],
                          "need": 62.47},
          "KV_OFFLOAD выключен — слои на картах с буферами, весь кэш в RAM: «кэш уйдёт в RAM»")
    check(ex["ramShort"]["verdict"] == "none" and ex["noCard"]["verdict"] == "none",
          "negative: RAM меньше, чем уйдёт в неё, или машина без карт не вмещает 62 ГБ в RAM — «не влезет»")
    check(ex["noCardSmall"] == {"verdict": "ram", "cards": [], "ram": [41.89, 39.6, 2.29], "need": 41.89},
          "машина без карт — llama.cpp на CPU: в RAM веса и кэш порознь")
    check(ex["device"] == {"verdict": "spill", "cards": [["1", 30.82, 28.71, 2.11]], "ram": [11.07, 10.89, 0.18], "need": 41.89},
          "DEVICE=CUDA1 — план по одной второй карте: 58 слоёв с буферами целиком, 22 в RAM")
    check(ex["silentCard"]["verdict"] == "unknown" and ex["moe"]["verdict"] == "unknown",
          "negative: карта не сказала занятость, эксперты отправлены на CPU руками — «место не известно», не план наугад")
    check(ex["unknownModel"] == ["spread", "files", 39.6, None] and ex["headless"] == ["spread", "files", 7, None]
          and ex["noModels"] == ["spread", "files", 39.6, None],
          "negative: модели нет в библиотеке, у строки нет заголовка или строитель не дал библиотеку — оценка по размеру файлов, «без "
          "кэша», а не «с кэшем» с нулём кэша")
    check(ex["projector"] == ["plan", "plan", 63.68, [40.8, 22.88]],
          "проектор ячейки — тоже её веса: 39.6 + 1.2 ГБ, как считает форма")
    check(ex["cpu"] == ["ram", "plan", 41.89, [39.6, 2.29]] and ex["cpuPlaced"] == ex["noCardSmall"],
          "ячейка на CPU с известной моделью — в RAM целиком, веса и кэш порознь")
    check(ex["asks"]["cards"] == [["0", 22.1, 15, 7.1], ["1", 22.1, 15, 7.1]], "vLLM — на каждой карте его доля: 15 ГБ весов и 7.1 кэша")
    eg = got["exactGhost"]
    title = ":22020 Hermes · ≈22.9 GB · part 1 of 3 · layers 12–40 · weights ≈14.4 GB · cache and buffers ≈8.5 GB"
    check(eg["spill"][0] == [["estimate", 14699.52, "would go here :22020", "≈14.4 GB", title],
                             ["estimate-cache", 8720, "cache :22020", "≈8.5 GB", title]]
          and [b[0] for b in eg["spill"][2]] == ["estimate", "estimate-cache"] and eg["spill"][2][0][3] == "≈5.9 GB",
          "пунктир на карте — два блока: веса и бледнее «кэш :22020», в подсказке какая он часть, какие слои и сколько чего на этой карте; в RAM — так же")
    check('class="ui-lane-blk ui-lane-blk--estimate-cache"' in eg["html"], "бледный пунктир — вид estimate-cache части Lane")
    check([[b[0] for b in lane] for lane in eg["kvRam"]] == [["estimate", "estimate-cache"], ["estimate", "estimate-cache"], ["estimate-cache"]],
          "кэш в RAM — на полосе RAM только бледный блок кэша; negative: блока весов нулевой ширины нет")
    check([[b[0] for b in lane] for lane in eg["byFiles"]] == [["estimate"], ["estimate"], []] and "without the cache" in eg["byFiles"][0][0][4],
          "negative: оценка по размеру файлов — один блок на карту, без бледного: кэш никто не считал, и подсказка это говорит")
    check(eg["words"] == ["≈62.5 GB with the cache", "9.1 GB goes to RAM", "9.1 GB goes to RAM"]
          and eg["kvRamWords"] == "its cache goes to RAM",
          "слова: «≈62.5 ГБ с кэшем», «9.1 ГБ уйдёт в RAM»; кэш в RAM — «кэш уйдёт в RAM»")

    print("ячейки в списке моделей (скамейки нет с Н1, 2026-11-02; её правила и слова здесь):")
    bn = got["bench"]
    check(bn["standing"] == [22009, 22020, 22014, 22026, 22018, 22023, 22005, 22030],
          "стоящие — крупные первыми по тому, что взяли бы сейчас (70.7, 39.6, 31.84 свободных у Strata, 31, 3, 0.3); без размера — в "
          "конце, по порту; negative: работающие и те, что в пути, — не среди стоящих")
    check(bn["order"] == [22001, 22011, 22012, 22017, 22009, 22020, 22014, 22026, 22018, 22023, 22005, 22030],
          "1.3.659 (владелец, 2026-10-26: «запущенные ячейки — что убираются отсюда? не надо их убирать, надо показывать, и что они "
          "грузятся или запущены»): правило говорит о каждой ячейке машины — сначала работающие, потом те, что в пути, потом стоящие; "
          "negative: запущенная из него не уходит")
    check(bn["groups"] == ["holds", "holds", "holds", "coming", "coming", "coming", "coming", "coming", "bench", "bench", "bench", "bench"],
          "где ячейка на странице: держит память (работает, прогревается, сломана) — на полосах; в пути (копия, старт, загрузка, "
          "остановка) — под ними; остальное — только в списке")
    check(bn["every"] == [22001, 22011, 22012, 22017, 22009, 22020, 22014, 22026, 22018, 22023, 22005, 22030],
          "каждая ячейка машины — один раз: на полосах, в пути, стоящие")
    html = bn["html"]
    check(html.startswith('<section class="machine-models" aria-label="Models" data-t="machine-models" data-t-state="models">')
          and '<strong class="machine-models-title">Models</strong>' in html
          and '<span class="machine-models-hint">click a cell to plan it, or drag it up onto the rack</span>' in html,
          "список: заголовок и как с ним обращаться: щелчок ставит ячейку в планер, можно перетащить на стойку")
    running = launch_of(html, 22001)
    check('<span class="machine-bench-size" data-machine-bench-size="22001">0.6 GB in RAM</span>' in running
          and '<span class="machine-bench-fit machine-bench-fit--good" data-machine-bench-fit="22001" data-t-state="running">running</span>' in running,
          "работающая — что держит сейчас и «работает» зелёным; negative: не «влезет на карты» — она уже там")
    check('data-machine-bench-size="22017">size not known</span>'
          '<span class="machine-bench-fit machine-bench-fit--busy" data-machine-bench-fit="22017" data-t-state="downloading">'
          'voice.safetensors · 4.0/8.0 GB · 50%</span>' in html
          and 'data-machine-bench-fit="22012" data-t-state="starting">starting</span>' in html
          and 'data-machine-bench-fit="22011" data-t-state="stopping">stopping…</span>' in html
          and html.count("machine-bench-fit--busy") == 4,
          "в пути — жёлтым, что делает: копирует модель (файл и цифры копии), запускается, останавливается; те же слова, что у фишки «в пути»")
    ld = bn["load"]
    check(ld == {"warming": "loading its weights · 12.0/42.0 GB · 29% · 480 MB/s · ~2 min left",
                 "starting": "starting · 3.0 GB · 1.0 GB/s", "still": "starting"},
          "1.3.662: грузит веса — сколько из всей модели, доля, скорость, остаток (как копия); старт, чей процесс уже читает, — "
          "сколько и как быстро; negative: старт без замера — только слово")
    wv = bn["verdicts"]
    check(wv == [[{"tone": "busy", "words": "loading its weights", "state": "warming"}, "8.0 GB on the cards"],
                 [{"tone": "bad", "words": "its process runs, its engine does not answer", "state": "broken"}, "4.0 GB on the cards"],
                 [{"tone": "good", "words": "running", "state": "running"}, "memory not measured"]],
          "держит память: грузит веса — жёлтым, сломана — красным, работает — зелёным; что держит — по картам; не измерено — так и сказано")
    hermes = launch_of(html, 22020)
    check(hermes.startswith('<div class="machine-model-launch" data-machine-pick="22020" data-machine-jobs="llm" data-t="machine-model-launch" data-t-id="22020" title="click a cell to plan it, or drag it up onto the rack">'
                            '<button type="button" class="machine-model-port" aria-pressed="false" data-machine-pick="22020" data-t="machine-model-cell" data-t-id="22020" title=":22020 Hermes-4-70B' + choose + '">')
          and '<span class="machine-bench-size" data-machine-bench-size="22020">≈39.6 GB by file size, without the cache</span>' in hermes
          and '<span class="machine-bench-fit machine-bench-fit--good" data-machine-bench-fit="22020" data-t-state="cards">fits on the cards</span>' in hermes,
          "строка ячейки выбирает её вся, порт — кнопка выбора для клавиатуры; размер по файлам с оговоркой «без кэша»; куда ляжет — зелёным")
    check('<b class="machine-model-name">Hermes-4-70B-GGUF</b><small class="machine-model-repo" data-t="machine-model-repo" data-t-id="Hermes-4-70B-GGUF" '
          'title="lmstudio-community/Hermes-4-70B-GGUF">lmstudio-community/<wbr>Hermes-4-70B-GGUF</small>' in html,
          "под именем модели мелко — репозиторий на HF (владелец, 2026-10-27), как был под именем на карточке")
    check('data-t="machine-model-repo" data-t-id="Strata-Kimi" title="a&amp;b/&lt;c&gt;">a&amp;b/<wbr>&lt;c&gt;</small>' in html
          and html.count('class="machine-model-repo"') == 2,
          "репозиторий экранирован по частям, перенос — после «/» автора (<wbr>), без пробелов по краям; negative: у ячейки, чей путь "
          "репозитория не называет, строки нет — "
          "автор не угадан, и пустой строки тоже нет")
    check('<span class="machine-model-runner">llama.cpp</span><span class="machine-model-quant"></span><span class="machine-model-ctx" data-t="machine-model-ctx" '
          'data-t-id="22020" data-t-state="both" title="Context set: 32,768 tokens · the model is trained for 131,072">🪟 32.8k / 🎓 131k</span>' in hermes,
          "1.3.648 (владелец, 2026-10-26): рядом с раннером — заданный контекст и самый большой, на каком модель обучена, "
          "словами строки ячейки (CellContext): 🪟 задан / 🎓 обучена, числа целиком в подсказке")
    check('class="machine-model-ctx over" data-t="machine-model-ctx" data-t-id="22009" data-t-state="over" '
          'title="Context set: 196,608 tokens · the model is trained for 131,072 · past its training: the window is stretched (YaRN)">'
          '🪟 197k / 🎓 131k</span>' in html
          and 'data-t="machine-model-ctx" data-t-id="22014" data-t-state="set" title="Context set: 65,536 tokens">🪟 65.5k</span>' in html,
          "окно больше обучения — предупреждением, как в строке; обучение не известно (Strata) — только заданное")
    check(not any(f'data-t="machine-model-ctx" data-t-id="{p}"' in html for p in ("22018", "22005", "22030", "22026", "22023")),
          "negative: у речи, у ячейки движка без чисел, у порта без модели и где контекст не сказан — строки контекста нет, "
          "а не «0» и не прочерк")
    check('data-t-state="spill">18.9 GB goes to RAM</span>' in html and 'machine-bench-fit--idle" data-machine-bench-fit="22009"' in html,
          "не влезает на карты — сколько уйдёт в RAM, спокойным тоном: это не отказ")
    check('machine-bench-fit--busy" data-machine-bench-fit="22026" data-t-state="none">won&#39;t fit now</span>' in html
          and "≈31.0 GB, what its runner takes" in html,
          "раннер со своим замером — «столько берёт раннер»; на свою карту не влезает — «сейчас не влезет» жёлтым")
    check("takes its card&#39;s free memory · its share of RAM is not counted here" in html and 'data-t-state="free">fits on GPU 1</span>' in html,
          "Strata: берёт свободное своей карты, и сказано, что её доля RAM здесь не учтена")
    check('machine-bench-fit--bad" data-machine-bench-fit="22018" data-t-state="failed" title="exit 1: CUDA out of &lt;memory&gt;">failed to start</span>' in html,
          "не запустилась — красным, причина в подсказке (экранирована); negative: не «влезет», хоть по размеру и влезла бы")
    check('<span class="machine-bench-size" data-machine-bench-size="22030"></span><span class="machine-bench-fit machine-bench-fit--idle" data-machine-bench-fit="22030" data-t-state="reserved">no model yet — choose it in the cell window</span>' in html
          and 'data-machine-pick="22030" data-machine-jobs=""' in html,
          "порт без модели — «без модели», без размера; negative: не «место не известно»")
    check('<span class="machine-bench-size" data-machine-bench-size="22005">size not known</span><span class="machine-bench-fit machine-bench-fit--idle" data-machine-bench-fit="22005" data-t-state="unknown">place not known</span>' in html
          and 'data-machine-pick="22005" data-machine-jobs="llm"' in html and '<strong class="machine-model-cell-name">ollama-qwen · 💬 LLM</strong><span class="machine-model-runner">Ollama</span>' in html,
          "ячейка движка — размер и место не известны, так и сказано; negative: работа не из словаря («nonsense») не названа")
    check(bn["sizes"] == ["≈39.6 GB by file size, without the cache", "takes its card's free memory · its share of RAM is not counted here",
                          "≈31.0 GB, what its runner takes", "size not known"],
          "что весит — словами: по файлам, своё правило Strata, замер раннера, не известно")
    check(bn["jobs"] == [{"job": "llm", "count": 6}, {"job": "embed", "count": 2}, {"job": "asr", "count": 1}, {"job": "tts", "count": 2}]
          and '<div class="machine-models-jobs" role="group" aria-label="Work">' in html
          and '<button type="button" class="ui-pill" aria-pressed="false" data-machine-job="llm" data-t="machine-models-job" data-t-id="llm">💬 LLM <span class="ui-count">6</span></button>' in html,
          "фильтр по работе над списком: работы всех ячеек машины в порядке словаря, со счётом — работающие и те, что в пути, тоже (эмбеддинг :22001, "
          "голос :22017)")
    tts = bn["tts"]
    slot_marks = re.findall(r'<div class="machine-model-launch" data-machine-pick="(\d+)" data-machine-jobs="[^"]*" data-t="machine-model-launch" data-t-id="\d+" title="[^"]*"( hidden)?>', tts)
    shown = [port for port, gone in slot_marks if not gone]
    check(shown == ["22017", "22026"] and 'aria-pressed="true" data-machine-job="tts"' in tts and sum(1 for _, gone in slot_marks if gone) == 10,
          "выбрана работа «текст → речь» — видны только её ячейки (и та, что копирует модель), её пилюля нажата, остальные спрятаны")
    check(not re.search(r'<div class="machine-model-launch" data-machine-pick="\d+"[^>]* hidden>', bn["stale"])
          and 'aria-pressed="true" data-machine-job=' not in bn["stale"] and bn["stale"].count('class="machine-model-launch"') == 12,
          "negative: выбрана работа, которой на машине нет (выбрали на другой машине), — список не сужен: снять выбор было бы нечем")
    check(bn["shown"] == ["tts", "", ""], "правило: работа стоит, пока её делает ячейка машины; negative: чужая и пустая — нет")
    check(bn["empty"].endswith('<p class="machine-models-empty">The library holds no models</p></section>')
          and 'data-t-state="empty"' in bn["empty"] and "machine-model-launch" not in bn["empty"] and "machine-models-jobs" not in bn["empty"],
          "negative: ячеек на машине нет — ни строк ячеек, ни фильтров по работе")
    wk = bn["working"]
    check(wk.count('class="machine-model-launch"') == 2 and 'data-t-state="models"' not in wk and 'data-t-state="running">running</span>' in wk
          and 'data-t-state="downloading">voice.safetensors · 4.0/8.0 GB · 50%</span>' in wk,
          "defect-history (1.3.634–1.3.658): все ячейки работают или в пути — скамейка показывала «стоящих нет» и ни одной; теперь — их, "
          "с тем, что каждая делает")

    print("куда ляжет — пунктир на полосах:")
    g = got["ghost"]
    check(g["hermes"] == [[[16425.79, "≈16.0 GB", "would go here :22020",
                            ":22020 Hermes-4-70B · ≈16.0 GB · part 1 of 2 · llama.cpp · ≈39.6 GB by file size, without the cache"]],
                          [[24124.61, "≈23.6 GB", "would go here :22020",
                            ":22020 Hermes-4-70B · ≈23.6 GB · part 2 of 2 · llama.cpp · ≈39.6 GB by file size, without the cache"]], []],
          "выбрана стоящая — пунктир на картах, куда ляжет: доля каждой (первая карта занята на 2 ГБ — ей меньше); в подсказке — что весит "
          "и по чему; negative: в RAM — ничего")
    check(g["spill"][2] == [[18.86, "≈18.9 GB", "would go here :22009", ":22009 Llama-3.3-70B · ≈18.9 GB · part 3 of 3 · llama.cpp · ≈70.7 GB by file size, without the cache"]]
          and g["spill"][0][0][1] == "≈21.0 GB" and g["spill"][1][0][1] == "≈30.8 GB",
          "не влезает на карты — пунктир заполняет их, остаток — пунктиром в RAM")
    check(g["strata"][0] == [] and g["strata"][1][0][:2] == [32607, "≈31.8 GB"], "Strata — на своей карте, всё её свободное")
    check(g["none"] == [[], [], []] and g["running"] == [[], [], []] and g["reserved"] == [[], [], []],
          "negative: не влезет — пунктира нет нигде; выбрана работающая или порт без модели — тоже")
    check('class="ui-lane-blk ui-lane-blk--estimate"' in g["lanesHtml"], "пунктир — часть Lane вида estimate")

    print("в пути:")
    ch = got["comingHtml"]
    check(ch == '<div class="machine-map-coming" data-t="machine-map-coming"><span>Starting:</span>'
          '<button type="button" class="ui-pill" aria-pressed="false" data-machine-pick="22012" data-t="machine-map-coming-cell" data-t-id="22012">:22012 · starting</button>'
          '<button type="button" class="ui-pill" aria-pressed="false" data-machine-pick="22017" data-t="machine-map-coming-cell" data-t-id="22017">:22017 voice-clone · voice.safetensors · 4.0/8.0 GB · 50%</button></div>'
          '<div class="machine-map-coming" data-t="machine-map-coming"><span>Stopping:</span>'
          '<button type="button" class="ui-pill" aria-pressed="false" data-machine-pick="22011" data-t="machine-map-coming-cell" data-t-id="22011">:22011 gemma · stopping…</button></div>',
          "ячейки в пути — под полосами, по порту, с тем, что делают, и каждая строка говорит, что это (1.3.657: было «В пути:»): "
          "«Запускается:» — стартует, копирует модель (файл и цифры копии); «Останавливается:» — отдельной строкой; их можно выбрать")
    check("machine-map-coming" not in got["html"], "negative: никого в пути — строки нет")

    print("строка — у каждой ячейки:")
    bp = got["bpanels"]
    stood = launch_of(bp, 22020)
    check('data-machine-bench-size="22020">≈39.6 GB by file size, without the cache</span>' in stood and '>fits on the cards</span>' in stood
          and 'data-cell-window-open="bench:22020" data-t="machine-model-window" data-t-id="22020">Cell window</button>' in stood
          and '<button type="button" class="ui-btn ui-btn--main" title="Start server" data-node-cell-play="bench" data-node-cell-port="22020" data-t="machine-model-start" data-t-id="22020">Start</button>' in stood
          and "machine-model-stop" not in stood,
          "выбрана стоящая: что весит и куда ляжет; «Окно ячейки» и «Запустить» атрибутами кнопки доски; negative: «Остановить» нет")
    reserved = launch_of(bp, 22030)
    check('title="Choose a model first" data-t="machine-model-start" data-t-id="22030" disabled>Start</button>' in reserved
          and "data-node-cell-play" not in reserved and "no model yet — choose it in the cell window" in reserved,
          "negative: запустить нельзя (порт без модели) — кнопка закрыта и говорит почему, без атрибутов доски; строка говорит, где выбрать модель")
    failed = launch_of(bp, 22018)
    check("machine-bench-fit--bad" in failed and '<span class="machine-pick-words">exit 1: CUDA out of &lt;memory&gt;</span>' in failed
          and 'data-t="machine-model-start" data-t-id="22018"' in failed,
          "не запустилась — красные слова, причина целиком в последней строке; «Запустить» — ещё раз")
    coming = launch_of(bp, 22017)
    check("machine-bench-fit--busy" in coming and "voice.safetensors · 4.0/8.0 GB · 50%" in coming
          and 'title="Not running" data-t="machine-model-stop" data-t-id="22017" disabled>Stop</button>' in coming,
          "в пути — жёлтые слова с тем, что делает; «Остановить» — закрыта, раз строитель её не дал")
    sb = got["bsubs"]
    check(sb["22011"].endswith("stopping…") and sb["22012"].endswith("starting") and sb["22023"] == "≈0.3 GB by file size, without the cache · in RAM"
          and sb["22014"] == "takes its card's free memory · its share of RAM is not counted here · fits on GPU 1"
          and sb["22030"] == "no model yet — choose it in the cell window" and sb["22005"] == "size not known · place not known",
          "вторая строка ряда — теми же словами, что фишка «в пути»")

    print("выбор на странице:")
    bb = got["bbind"]
    check(bb["chosenStopped"] == {"port": "22020", "redraws": 1, "focus": ["machine-model-cell:22020"]},
          "выбрана стоящая — доска рисуется заново (пунктир на полосах рисует только она), клавиатура — на тот же порт в строке")
    check(bb["leftStopped"] == {"port": "22001", "redraws": 2, "focus": ["machine-model-cell:22020", "machine-map-block:22001"]},
          "со стоящей на работающую — снова заново: пунктир надо убрать; клавиатура — на блок работающей")
    check(bb["runningToComing"] == {"port": "22011", "redraws": 2},
          "negative: с работающей на ту, что в пути, — пунктира нет ни до, ни после: показ на месте, без перерисовки")
    check(bb["rowChosen"] == {"port": "22026", "redraws": 1},
          "щелчок где угодно по строке ячейки выбирает её для планера, как щелчок по карточке выбирал")
    check(bb["ownPressed"] == {"port": "22026", "redraws": 1},
          "negative: щелчок по «Окно ячейки», «Запустить» или «Остановить» в строке — только это: ячейка не выбрана, ничего не нарисовано")
    check(bb["rowLetGo"] == {"port": "", "redraws": 2}, "снова по той же строке — выбор снят, как у блока")
    check(got["oldJob"] == ["undefined", "undefined", False],
          "работу выбирает список, и держит её он (MachineModelsChoice): у выбора ячейки своей копии нет")
    check(bb["standing"] == [True, False, False, False, False], "стоящая — та, что строитель отнёс к стоящим; negative: работающая, в пути, пусто, чужой порт")

    print("оценка модели в её строке (владелец, 2026-10-31):")
    en_js = (ROOT / "static" / "js" / "i18n" / "en.js").read_text(encoding="utf-8")
    like_words, dislike_words = (json.loads(re.search(rf'^  {key}: (".*"),$', en_js, re.M).group(1)).replace("'", "&#39;") for key in ("ratingLike", "ratingDislike"))
    html = got["bench"]["html"]
    rates = re.findall(r'<button type="button" class="model-rate-btn( is-on)?" aria-pressed="(true|false)" data-model-rate="(like|dislike)" data-model-rate-for="([^"]*)"'
                       r' data-t="machine-model-rate" data-t-id="\4:\3" title="([^"]*)" aria-label="\5">(👍|👎)</button>', html)
    check([(cls, pressed, kind, model, mark) for cls, pressed, kind, model, _, mark in rates]
          == [(" is-on", "true", "like", "Hermes-4-70B-GGUF", "👍"), ("", "false", "dislike", "Hermes-4-70B-GGUF", "👎")]
          and {words for _, _, _, _, words, _ in rates} == {like_words, dislike_words},
          f"у строки модели — две кнопки, нажата та, что стоит; negative: у модели, чей путь папки не называет, кнопок нет (got {rates})")
    opener = html[html.index('data-machine-model-open="Hermes-4-70B-GGUF"'):html.index('<span class="machine-model-rate">', html.index('data-machine-model-open="Hermes-4-70B-GGUF"'))]
    check(opener.endswith("</button>") and "model-rate-btn" not in opener,
          "кнопки — рядом с кнопкой строки, не внутри неё: кнопка не держит другую кнопку")
    st = got["rate"]
    check(st["pressed"] == {"looks": [["true", True], ["false", False]], "other": None, "saved": [["strata", "like"]], "facts": ["like", "like", "like"], "port": True, "redraws": 0},
          "щелчок: сразу нажата на всех карточках модели, контроллеру ушло «модель, оценка»; факты обеих ячеек помнят; negative: кнопка чужой модели не тронута, ячейка не выбрана, доска не перерисована")
    check(st["unpressed"] == {"looks": [["false", False], ["false", False]], "saved": [["strata", ""]], "facts": ["", "", "like"]},
          "тот же щелчок снимает оценку тем же путём")
    check(st["changed"] == {"looks": [["false", False], ["true", True]], "saved": [["strata", "dislike"]], "facts": ["dislike", "dislike", "like"]},
          "дизлайк на модели без оценки ставит её; у модели одна оценка")
    check(st["refused"] == {"answer": False, "look": ["false", False], "other": ["true", True], "facts": ["dislike", "dislike", "like"], "notes": ["no such model"]},
          "negative: контроллер отказал — оценка возвращается какой была (у Hermes 👍), факт тоже, причина сказана вслух")
    check(st["unknown"] == [False] and st["sent"] == 0, "negative: кнопка без модели ничего не шлёт (модель без ячейки оценивается: scripts/test_js_machine_models.py)")

    print("живой патч строк ячеек:")
    lb = got["blive"]
    check(lb["found"][0] == lb["found"][2] and lb["found"][1] == lb["found"][2] and len(lb["found"][2]) == 12,
          "патч находит размер и вердикт каждой ячейки там, где их нарисовала страница: в её строке, под именами data-machine-bench-size и -fit")
    check(lb["drawnWrites"] == 0 and lb["drawn"]["22020"][:2] == ["fits on the cards", "cards"],
          "доска нарисовала — патч с теми же числами не переписывает полосы; слова вердиктов — на месте")
    check(lb["ramFull"]["mapWrites"] == 0 and lb["ramFull"]["verdicts"]["22009"] == ["won't fit now", "none", "machine-bench-fit machine-bench-fit--busy"]
          and lb["ramFull"]["chips"] == [[":22011 gemma · stopping…", 0], [":22012 · starting", 0],
                                         [":22017 voice-clone · voice.safetensors · 6.0/8.0 GB · 75%", 1]],
          "RAM заполнилась, копия пошла дальше — блоки те же: вердикт «уйдёт в RAM» стал «не влезет» (с тоном) и слова фишки копии — на "
          "месте; negative: фишки без перемен не тронуты")
    check(lb["cardFull"]["mapWrites"] == 1 and lb["cardFull"]["verdicts"]["22020"] == ["7.3 GB goes to RAM", "spill", "machine-bench-fit machine-bench-fit--idle"]
          and lb["cardFull"]["verdicts"]["22014"][:2] == ["fits on GPU 1", "free"],
          "вторую карту занял чужой процесс — на её полосе блок прибавился, полосы переписаны целиком; вердикты пересчитаны: Hermes теперь "
          "отдаст 7.3 ГБ в RAM, Strata возьмёт оставшееся свободное")
    check(lb["drawn"].get("22001") == ["running", "running", "machine-bench-fit machine-bench-fit--good"]
          and lb["drawn"].get("22017") == ["voice.safetensors · 4.0/8.0 GB · 50%", "downloading", "machine-bench-fit machine-bench-fit--busy"]
          and (lb["ramFull"]["verdicts"].get("22017") or [""])[0] == "voice.safetensors · 6.0/8.0 GB · 75%",
          "живой патч строк работающей и той, что в пути: «работает» зелёным; копия — её цифры, и они идут дальше на месте")
    check(lb["sizes"] == {"22001": "0.6 GB in RAM", "22017": "size not known", "22020": "≈39.6 GB by file size, without the cache"}
          and lb["moved"] == {"size": "0.9 GB in RAM", "writes": 1, "still": 0},
          "размер в строке — на месте: работающая держит 0.6 ГБ, потом 0.9 — переписано; negative: размер стоящей не менялся и не переписан")
    check(lb["cardFull"]["verdicts"]["22018"] == ["failed to start", "failed", "machine-bench-fit machine-bench-fit--bad"]
          and lb["cardFull"]["verdicts"]["22030"][:2] == ["no model yet — choose it in the cell window", "reserved"],
          "negative: «не запустилась» и «без модели» патч не переписывает вердиктом места")

    print("картинки у полос стойки:")
    pc = got["pictures"]
    check(pc["lanes"] == [[f"gpu-{i}", "card"] for i in range(6)] + [["ram", "ram"]] and pc["count"] == 7,
          "шесть карт: у каждой полосы карты — картинка карты, у полосы RAM — планка памяти, по одной, перед подписью (владелец, 2026-11-02: «слева картинки у видеокарт и RAM»)")
    check(pc["laneOfCard"] is True and pc["laneOfRam"] is True, "картинку полосе даёт один класс (LanePicture)")
    check(pc["card"] == '<span class="machine-lane-pic" data-machine-lane-pic="card" aria-hidden="true"><svg width="34" height="20" viewBox="0 0 34 20">'
                        '<rect class="is-body" x="1.5" y="3" width="27" height="13" rx="2"/><circle class="is-hollow" cx="9" cy="9.5" r="4.2"/><circle class="is-hollow" cx="21" cy="9.5" r="4.2"/>'
                        '<circle class="is-hub" cx="9" cy="9.5" r="1.6"/><circle class="is-hub" cx="21" cy="9.5" r="1.6"/>'
                        '<rect class="is-bracket" x="29" y="2" width="2.5" height="16"/><rect class="is-contact" x="5" y="16" width="14" height="2"/></svg></span>',
          "видеокарта — фигуры макета «заливка» один в один, скрыта от чтения с экрана: подпись рядом говорит то же")
    check(pc["ram"] == '<span class="machine-lane-pic" data-machine-lane-pic="ram" aria-hidden="true"><svg width="34" height="18" viewBox="0 0 34 18">'
                       '<path class="is-body" d="M1.5 3h31v9h-14v2h-3v-2h-14z"/><rect class="is-hollow" x="5" y="5.5" width="4" height="4"/><rect class="is-hollow" x="12" y="5.5" width="4" height="4"/>'
                       '<rect class="is-hollow" x="19" y="5.5" width="4" height="4"/><rect class="is-hollow" x="26" y="5.5" width="4" height="4"/>'
                       '<rect class="is-contact" x="3" y="12" width="12" height="2"/><rect class="is-contact" x="19" y="12" width="12" height="2"/></svg></span>',
          "планка памяти — тоже; negative: ни одного своего цвета в разметке")
    check(pc["refused"] == "refused" and "machine-lane-pic" not in pc["plain"],
          "negative: картинки неизвестного устройства нет — отказ, а не догадка; полоса, которой картинку не дали, без неё")
    box = re.search(r"\.machine-lane-pic\s*\{([^}]*)\}", css).group(1)
    lane_height = int(re.search(r"--lane-height:\s*(\d+)px", (ROOT / "static" / "css" / "ui.css").read_text(encoding="utf-8")).group(1))
    box_height = int(re.search(r"(?<![-\w])height:\s*(\d+)px", box).group(1))
    check("width: 34px" in box and "flex: none" in box and box_height == 20 and box_height <= lane_height,
          f"рамка одна и не сжимается: подписи полос начинаются в одном месте; {box_height} px — не выше полосы в {lane_height} px, и шесть карт не прибавляют высоты")
    narrow = re.search(r"@container rack \(max-width: 620px\)\s*\{\s*\.machine-lane-pic\s*\{([^}]*)\}", css)
    check(narrow is not None and "height: 15px" in narrow.group(1),
          "узкая стойка, где подпись стоит своей строкой, — картинка не выше её слов (15 px при подписи 15.6): строка не растёт")
    who = re.search(r"\.machine-rack-lanes\s*\{[^}]*--lane-who:\s*(\d+)px", css)
    short = re.search(r"@container rack \(max-width: 1300px\)\s*\{\s*\.machine-rack-lanes\s*\{\s*--lane-who:\s*(\d+)px", css)
    check(who is not None and short is not None and int(who.group(1)) - int(short.group(1)) == 42,
          "широкая стойка отдаёт картинке и отступу свои 42 px, и слова рядом целы; короткая строка держит брусок, слова режутся (целиком в подсказке)")
    for token in ("is-body", "is-hollow", "is-hub", "is-bracket", "is-contact"):
        check(re.search(rf"\.machine-lane-pic \.{token}\s*\{{\s*fill:[^;}}]*var\(--ui-", css) is not None, f"цвет фигуры {token} — из токенов страницы")

    print("колонка справа от карты (1.3.636):")
    sd = got["side"]
    full = sd["full"]
    at = lambda k: full.index(f'data-t="machine-side-{k}"')
    check(full.startswith('<aside class="machine-side" aria-label="What the machine runs its cells with" data-t="machine-side"><div class="w">!</div>')
          and at("engines") < at("disk") < at("incidents") < at("activity")
          and '<div class="machine-side-title">Engines<span class="machine-side-whose">gpu-box</span></div><i>engines</i>' in full
          and '<div class="machine-side-title">Model disk<span class="machine-side-whose">gpu-box</span></div><i>disk</i>' in full
          and '<div class="machine-side-title">Activity<span class="machine-side-whose">gpu-box</span></div>' in full
          and '<div class="machine-side-title">Incidents<span class="machine-side-whose">whole caravan</span></div>' in full
          and 'aria-label="Model disk · gpu-box"' in full
          and full.index("<i>charts</i>") < full.index("<i>stats</i>"),
          "колонка: предупреждения о драйвере сверху, потом движки, диск моделей, инциденты и активность — каждая часть со своим заголовком; "
          "статистика сервера машины контроллера — под графиками")
    check('<span class="machine-incidents-count" data-board-incidents-count data-t="machine-incidents-count" data-t-state="some">2</span>' in full
          and "slow or failed requests through the caravan&#39;s ports in the last 24 hours" in full
          and 'data-machine-incidents data-t="machine-incidents-open">Open</button>' in full,
          "инциденты: число в общем счётчике доски (его пишет charts.js), что это за число, и «Открыть»")
    em = sd["empty"]
    check('<div class="machine-side-title">Model disk</div>' in em and 'aria-label="Model disk"' in em
          and '<span class="machine-side-whose">whole caravan</span>' in em,
          "negative: машина не названа — у её частей нет подписи, имя не выдумано; инциденты всё равно говорят, что они всего каравана")
    check("No engine reported" in em and "The scout does not report its model cache" in em and "Nothing measured yet" in em
          and 'data-t-state="unknown">—</span>' in em,
          "negative: части нет — колонка так и говорит (нет движков, скаут не сообщает о кэше, ничего не замерено), а не рисует пустое "
          "место; число инцидентов не известно — «—», а не 0")
    check('data-t-state="none">0</span>' in sd["zero"] and [('data-t-state="unknown">—' in x) for x in sd["junk"][:2]] == [True, True]
          and 'data-t-state="some">2</span>' in sd["junk"][2],
          "известный ноль — «0»; negative: отрицательное или не число — «не известно», дробь — целое")
    check(got["headSide"] == [True, True, False, True],
          "стойка на всю ширину, под ней сетка: список моделей слева, колонка справа; negative: без колонки — без сетки, а стойка на месте")
    check(got["sideIncidents"] == [1, 1, True], "«Открыть» привязан к документу один раз и открывает инциденты; negative: щелчок мимо не открывает")

    print()
    if _fail:
        print(f"js machine-head FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg)
        return 1
    print("js machine-head OK: полосы карт и RAM с ячейками и картинками, куда ляжет стоящая, ячейки в списке, в пути, панели, полоса в строке шапки, "
          "паспорт с «⋯», выбор, живой патч — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
