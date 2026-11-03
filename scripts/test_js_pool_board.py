#!/usr/bin/env python3
"""Snapshot of static/js/pool-board.js — Routing as three columns (the owner, 2026-10-12; without sets since 1.3.675).

Pinned by value, with the module loaded for real (scripts/_js_harness.mjs): the
client cards — what each sees and what is closed to it, the window that closes a
source, a model or a pool, and the window of the move — «Напрямую» and its rows; the
cables shown only for a pinned card and while requests run; a pool's rows of three
kinds — a subscription's model, a machine's cell, a row with no cable — with the
proxy's word on each and the serving one lit; the models on the right with the
pools that use them — on an account's card only the models added to it (the
owner, 2026-10-12: "only the ones I added"), "＋ model" finding more in the
account's list as it is typed, and ✕ taking one no row names off — a
subscription's models with their levels (their own pair, the controller's
default, or no handles when the controller says nothing), the stopped cells no
row names folded under one button; the cables measured from
dot to dot, and the ones that cannot be placed named; a cable drawn by carrying
an output's dot onto a pool or a model, and cut by a click after one question;
"+ row", "+ New pool", a row's removal, a pool's new name; the drawing held while
the pointer holds something. Strings come from en.js.

The renderer, the routers' grouping of outputs, the usage readings and the
dialogs are stubs (`machineAt` and `localOutputGroups` given the simplest real
shape); the controller is a stand-in passed to the class.

Run: python3 scripts/test_js_pool_board.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

STUBS = ("dialogs,topology-render,consumer-access,polling,remote-cells,topology-dnd,canvas,charts,cables,history,"
         "favorites,config-locator,system-panels,onboarding,onboarding-tours,dialog-llamas,models-page,system-page,"
         "memory,command-preview,llama-edit,topology-nodes,topology-modals,topology-activity,topology-proxies,routers,"
         "cloud,usage-stats")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
globalThis.CSS = { escape: (s) => String(s) };
globalThis.__usage = new Map();
globalThis.__drag = { active: false, deferred: false, begin(onEnd) { this.active = true; this.onEnd = onEnd; } };
globalThis.__landed = new Set();
globalThis.__seen = new Set();   // who is told that the monitor was read (topology-activity.ACTIVITY_SEEN): the board's drops on its cables
globalThis.__stubValues = { "usage-stats.subscriptionUsageCache": globalThis.__usage, "usage-stats.switchDrag": globalThis.__drag,
  "usage-stats.READING_LANDED": globalThis.__landed, "topology-activity.ACTIVITY_SEEN": globalThis.__seen };
globalThis.__stubReturns = {
  "topology-nodes.machineAt": (address) => ({ key: address === "10.0.0.5" ? "box" : address, name: address === "10.0.0.5" ? "Box" : address, address }),
  "topology-nodes.cellJobs": () => [],
  "topology-nodes.cellRunnerId": () => "",
  "routers.localOutputGroups": (outs) => {
    const groups = new Map();
    for (const o of outs || []) {
      if (String(o.upstreamType || "llama") === "cloud") continue;
      const key = o.upstreamHost === "10.0.0.5" ? "box" : o.upstreamHost;
      if (!groups.has(key)) groups.set(key, { key, name: key === "box" ? "Box" : key, address: o.upstreamHost, outs: [] });
      groups.get(key).outs.push(o);
    }
    return [...groups.values()].map((g) => ({ ...g, outs: [...g.outs].sort((a, b) => a.upstreamPort - b.upstreamPort) }));
  },
  "routers.machineLabelHtml": (g) => String(g.name),
  "cloud.cloudAccountIconHtml": (a) => `<i>${a.id}</i>`,
  // With a model's step it draws the model's levels on the bars, without one the account's limits alone.
  "usage-stats.subscriptionUsageHtml": (owner, { step } = {}) => (step
    ? `[bars ${owner} ${step.accountId}/${step.model} stop=${JSON.stringify(step.stopAt)} switch=${JSON.stringify(step.switchAt)} max=${step.switchMax}]`
    : `[usage ${owner}]`),
  // The account's small meters (the card's limits, 1.3.541) with the stop levels the card gives them — the red ticks on its bars.
  "usage-stats.subscriptionMetersHtml": (owner, { stops } = {}) => `[meters ${owner} stops=${JSON.stringify(stops)}]`,
  // The ⟳ the account's head had until 2026-10-12, drawn as itself: a card that draws it again shows it.
  "usage-stats.subscriptionRefreshHtml": (owner) => `<button data-usage-refresh="${owner}">⟳</button>`,
  "usage-stats.upstreamErrorsHtml": (id) => (globalThis.__errs && globalThis.__errs[id]) || "",
  "usage-stats.proxySpendHtml": (id) => `[spend ${id}]`,
  "usage-stats.openRouterLimitsHtml": (id) => `[limits ${id}]`,
  "usage-stats.apiCostsHtml": (id) => `[costs ${id}]`,
  "cloud.cloudApiIssuesHtml": (a) => (globalThis.__issues && globalThis.__issues[a.id]) || "",
};
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const m = await import(pathToFileURL(process.env.JS_ROOT + "/pool-board.js").href);
const { CableFlow } = await import(pathToFileURL(process.env.JS_ROOT + "/cable-flow.js").href);
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const { escapeHtml: esc } = await import(pathToFileURL(process.env.JS_ROOT + "/utils.js").href);
// Routing's tour stands on this board's parts (static/js/onboarding-tours.js): each anchor must be one the board draws.
const tours = await import(pathToFileURL(process.env.JS_ROOT + "/onboarding-tours.js").href);
const { drawn } = await import("./_tour_anchors.mjs");
const fill = (s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => v[k]);
const TOPO = () => ({
  proxies: [
    // Hermes is closed to nothing and called Standart and Coder straight over three days; Bot is closed to Econom (1.3.675: no sets).
    { id: "ctl:proxy:23001", port: 23001, kind: "consumer", label: "Hermes", keyTail: "a1b2", deny: [], models: ["Standart", "Econom", "gpt-sol", "gpt-astra", "Coder"],
      calls: [{ pool: "std", count: 12, last: 999 }, { pool: "live:srv:22008", count: 3, last: 990 }] },
    { id: "ctl:proxy:23002", port: 23002, kind: "consumer", label: "Bot", keyTail: "c3d4", deny: ["pool:eco"], models: ["Standart", "gpt-sol", "gpt-astra", "Coder"], calls: [], mode: "paused" },
    { id: "ctl:proxy:23050", port: 23050, label: "old agent" }],
  // What a client closed to nothing sees, what a client can be closed to, and the models a client calls straight (topology.entry_reading).
  entryModels: ["Standart", "Econom", "gpt-sol", "gpt-astra", "Coder"],
  denyChoices: { pools: [{ key: "pool:std", name: "Standart" }, { key: "pool:eco", name: "Econom" }],
    models: [{ key: "model:srv:22008", name: "Coder", source: "host:box", runs: true }, { key: "model:srv:22009", name: "Gemma", source: "host:box", runs: false },
      { key: "model:acc:sub/gpt-sol", name: "gpt-sol", source: "account:sub", runs: true }, { key: "model:acc:sub/gpt-astra", name: "gpt-astra", source: "account:sub", runs: true }],
    sources: ["host:box", "account:sub"] },
  liveCatalog: [{ id: "Coder", pool: "live:srv:22008", runs: true, output: "srv:22008" }, { id: "Gemma", pool: "live:srv:22009", runs: false, output: "srv:22009" },
    { id: "gpt-sol", pool: "live:acc:sub/gpt-sol", runs: true, accountId: "sub", model: "gpt-sol" },
    { id: "gpt-astra", pool: "live:acc:sub/gpt-astra", runs: true, accountId: "sub", model: "gpt-astra" }],
  cloudAccounts: [
    { id: "sub", name: "ChatGPT", accountType: "openai-subscription", hasCredential: true },
    { id: "or", name: "OpenRouter", type: "openrouter", hasCredential: true }],
  pools: [
    { id: "std", name: "Standart", steps: [
      { id: "sub", kind: "account", accountId: "sub", model: "gpt-sol", enabled: true, switchReached: { "18000": true } },
      { id: "r1", kind: "output", output: "srv:22008", enabled: true },
      { id: "r2", kind: "open", enabled: true }] },
    { id: "eco", name: "Econom", steps: [
      { id: "sub", kind: "account", accountId: "sub", model: "gpt-luna", enabled: true },
      { id: "r1", kind: "output", output: "srv:22999", enabled: true }] }],
  poolsRuntime: { available: true, pools: { std: { selectedStepId: "r1", steps: [
    { stepId: "sub", reason: "reserve" }, { stepId: "r1", reason: "ready" }, { stepId: "r2", reason: "not_connected" }] } },
    events: [{ poolId: "std", at: 1700000000, from: "sub", to: "r1" }] },
  modelLevels: { max: 90, default: { stopAt: { "18000": 10 }, switchAt: { "18000": 10 } },
    set: { sub: { "gpt-sol": { stopAt: { "18000": 20 }, switchAt: { "18000": 30 } } } } },
  // gpt-luna is named by a row of Econom and not added: it stands on the card all the same.
  addedModels: { sub: ["gpt-sol", "gpt-astra"] },
  routers: [{ id: "router:default", outputs: [
    { id: "srv:22008", upstreamType: "llama", upstreamHost: "10.0.0.5", upstreamPort: 22008, label: "Coder :22008", hostId: "box" },
    { id: "srv:22009", upstreamType: "llama", upstreamHost: "10.0.0.5", upstreamPort: 22009, label: "Gemma :22009", hostId: "box" },
    { id: "srv:22010", upstreamType: "llama", upstreamHost: "10.0.0.5", upstreamPort: 22010, label: "Big :22010", hostId: "box" },
    { id: "srv:22011", upstreamType: "llama", upstreamHost: "10.0.0.5", upstreamPort: 22011, label: "Small :22011", hostId: "box" },
    { id: "cb:std", upstreamType: "cloud", providerId: "std" }] }],
  nodes: [{ id: "box", servers: [
    { port: 22008, phase: "running", cellLabel: "Coder" }, { port: 22009, phase: "stopped", cellLabel: "Gemma" },
    { port: 22010, phase: "stopped", cellLabel: "Big" }, { port: 22011, phase: "error", cellLabel: "Small" }] }],
});
// The built-in clients (2026-10-27) are clients as any other since 1.3.675: Open WebUI sees everything and called gpt-sol straight;
// opencode is closed to the whole account "sub".
const OWUI = (over = {}) => ({ id: "ctl:proxy:23009", port: 23009, kind: "consumer", builtin: "open-webui", label: "Open WebUI", keyTail: "b0b0", deny: [],
  models: ["Standart", "Econom", "gpt-sol", "gpt-astra", "Coder"], calls: [{ pool: "live:acc:sub/gpt-sol", count: 4, last: 995 }], ...over });
const WITH_OWUI = (over) => st.setTopology({ ...TOPO(), proxies: [...TOPO().proxies, OWUI(over)] });
const OCODE = (over = {}) => ({ id: "ctl:proxy:23010", port: 23010, kind: "consumer", builtin: "opencode", label: "opencode", keyTail: "c0c0", deny: ["account:sub"],
  models: ["Standart", "Econom", "Coder"], calls: [], ...over });
const WITH_BOTH = () => st.setTopology({ ...TOPO(), proxies: [...TOPO().proxies, OCODE(), OWUI()] });
const CATALOGUE = { models: [{ id: "gpt-sol", chat: true }, { id: "gpt-luna", chat: true }, { id: "gpt-astra", chat: true }, { id: "embed-1", chat: false }] };
const OR_CATALOGUE = { models: [{ id: "a/one", chat: true }, { id: "b/two", chat: true }, { id: "c/three", chat: true }] };
// A stand-in for an element: attributes, dataset, a parent — enough for closest() and matches(); a selector is an
// attribute (`[data-x]`, `[data-x="v"]`) or a bare tag name, which is told by `extra.tagName`.
const camel = (s) => s.replace(/-(\w)/g, (_, c) => c.toUpperCase());
const node = (attrs = {}, parent = null, extra = {}) => {
  const n = { attrs, parent, dataset: {}, classes: new Set(), ...extra };
  for (const [k, v] of Object.entries(attrs)) if (k.startsWith("data-")) n.dataset[camel(k.slice(5))] = v;
  n.classList = { add: (c) => n.classes.add(c), remove: (...cs) => cs.forEach((c) => n.classes.delete(c)) };
  n.hasAttribute = (a) => Object.prototype.hasOwnProperty.call(n.attrs, a);
  n.matches = (sel) => sel.split(",").some((s) => { const x = s.trim().match(/^\[([\w-]+)(?:="([^"]*)")?\]$/);
    if (!x) return /^[a-z]+$/.test(s.trim()) && String(n.tagName || "").toLowerCase() === s.trim();
    return n.hasAttribute(x[1]) && (x[2] === undefined || n.attrs[x[1]] === x[2]); });
  n.closest = (sel) => { let c = n; while (c) { if (c.matches(sel)) return c; c = c.parent; } return null; };
  return n;
};
const R = (left, top, width = 10, height = 10) => ({ getBoundingClientRect: () => ({ left, top, width, height, right: left + width, bottom: top + height }) });
const board = (over = {}) => {
  CableFlow.reset();   // a board is new: the cables that carried a request before it are not its story
  const log = { calls: [], notes: [], asks: [], applied: [], saved: [], removed: [] };
  const answers = [...(over.answers || [true])];
  const b = new m.PoolBoard({
    call: async (path, o) => { log.calls.push(o ? [path, JSON.parse(o.body)] : [path]); if (over.fail) throw new Error("controller is down"); return over.res || { ok: true, topology: { marker: 1 } }; },
    notify: (x) => log.notes.push(x),
    confirm: async (text, opts) => { log.asks.push([text, opts.title, opts.danger]); return answers.length ? answers.shift() : true; },
    apply: (top) => log.applied.push(top),
    win: { addEventListener() {}, removeEventListener() {}, requestAnimationFrame: () => 0 },
    doc: { elementFromPoint: (x, y) => (over.at ? over.at(x, y) : null) },
    agents: over.agents || (() => undefined),   // the monitor's rows of requests, by port
    slots: over.slots || (() => undefined),     // the slots the proxy counted, by upstream group
    now: over.now || (() => 1000000),           // 1000 s: a request that finished at 998 finished 2 s ago
  });
  b.catalogues.set("sub", CATALOGUE);
  b.catalogues.set("or", OR_CATALOGUE);
  b.actions.save = async (pool) => { log.saved.push({ id: pool.id, name: pool.name }); return { ok: true }; };
  b.actions.remove = async (id) => { log.removed.push(id); return { ok: true }; };
  b.html(st.topology);
  b.actions.set({ pools: st.topology.pools, accounts: st.topology.cloudAccounts });
  return [b, log];
};
// A board that can draw its cables: each dot is an element with a class list, standing where the `draw_cables` pin puts it.
const SPOTS = { '[data-pb-node="client:23001"] [data-pb-anchor]': [100, 50], '[data-pb-pool="std"] > [data-pb-in]': [300, 20],
  '[data-pb-direct="live:srv:22008"] [data-pb-direct-in]': [300, 5], '[data-pb-direct="live:srv:22008"] [data-pb-direct-out]': [550, 5],
  '[data-pb-pool="std"] [data-pb-row="sub"] [data-pb-out]': [500, 60], '[data-pb-pool="std"] [data-pb-row="r1"] [data-pb-out]': [500, 90],
  '[data-pb-pool="eco"] [data-pb-row="sub"] [data-pb-out]': [500, 300],
  '[data-pb-key="acc:sub/gpt-sol"] [data-pb-in]': [700, 30], '[data-pb-key="out:srv:22008"] [data-pb-in]': [700, 200] };
const rigged = (b) => {
  const svg = { innerHTML: "" }; const dots = {};
  for (const [sel, [left, top]] of Object.entries(SPOTS)) dots[sel] = node({}, null, R(left, top));
  const cols = { ...R(0, 0), querySelector: (s) => (s === "[data-pb-cables]" ? svg : dots[s] || null) };
  b.root = { querySelector: (s) => (s === "[data-pb-cols]" ? cols : null) };
  return { svg, dots };
};
// One request of the monitor, by the port it came in by (Hermes, 23001, a client of the entry).
const RUN = (item, port = 23001) => ({ [String(port)]: { port, active: [{ phase: "running", port, ...item }], recent: [] } });
const SAW = (item, port = 23001) => ({ [String(port)]: { port, active: [], recent: [{ port, ...item }] } });
// The part of the drawing between two markers: one card, one row.
const part = (h, from, to = "</article>") => { const i = h.indexOf(from); return i < 0 ? "" : h.slice(i, h.indexOf(to, i) + to.length); };
// One whole item of a list drawn as HTML — a pool's row, a model's row — found by what it contains.
const item = (h, start, has) => h.split(start).slice(1).map((x) => start + x).find((x) => x.includes(has)) || "";
// The monitor at `now` ms with a model's queue (model-queue.js): Hermes's request waits on Standart's cell row r1 (Coder :22008) for
// 90 s, 65 s of them gone, with nowhere to go; a request that came straight to the cell holds its one slot for 2:10.
const QA = (now = 1000000) => { const s = now / 1000; return {
  "23001": { port: 23001, active: [{ id: "w1", route: "Hermes", phase: "queued", cloudPoolId: "std", poolStepId: "r1", routedOutputId: "srv:22008",
    upstream: "10.0.0.5:22008", queue: { since: s - 65, leaveAt: s + 25, leaveTo: "refuse", position: 0 } }] },
  "23005": { port: 23005, active: [{ id: "x1", route: "Bot", phase: "streaming", routedOutputId: "srv:22008", upstream: "10.0.0.5:22008", slotAt: s - 130 }] } }; };
const keys = (h, prefix) => (h.match(new RegExp(`data-pb-key="${prefix}([^"]+)"`, "g")) || []).map((x) => x.slice(`data-pb-key="${prefix}`.length, -1));
const reset = () => { st.setTopology(TOPO()); globalThis.__usage.clear(); globalThis.__seen.clear(); globalThis.__drag.active = false; globalThis.__drag.deferred = false; };
reset();

// A board drawn on the screen, for following a path: the box, the three column bodies, the strip over their foot and the cards, each
// with the place it stands in ({key: [column, left, top, width, height]}). `scrollTo` of the box and of the bodies is logged, the
// timers of the board's window are held (an id each), and the window is a screen of 1440 x 800 whose strip begins at 604.
const CARDS = { "row:std/sub": ["pools", 740, 300, 200, 28], "pool:std": ["pools", 730, 260, 280, 200],
  "client:23001": ["clients", 50, 250, 280, 70], "model:acc:sub/gpt-sol": ["models", 1080, 900, 260, 90] };
const stage = (b, cards, over = {}) => {
  const calls = [], timers = [], cleared = [];
  const at = (l, t, w, h) => ({ getBoundingClientRect: () => ({ left: l, top: t, width: w, height: h, right: l + w, bottom: t + h }) });
  const bodies = {};
  [["clients", 40], ["pools", 720], ["models", 1060]].forEach(([name, left]) => {
    const spec = (over.bodies || {})[name] || {};
    bodies[name] = node({ "data-pb-scroll": name }, null, { ...at(left, 120, 300, 640), scrollTop: spec.scrollTop ?? 100, scrollLeft: 0,
      scrollHeight: 3000, clientHeight: 640, scrollWidth: 300, clientWidth: 300, scrollTo(o) { calls.push([name, o]); } });
  });
  const wide = over.boxWidth ?? 1440;
  const box = node({ "data-pb-root": "" }, null, { ...at(0, 0, wide, 760), scrollLeft: 0, scrollWidth: 1535, clientWidth: wide, scrollTo(o) { calls.push(["box", o]); } });
  const dock = node({ "data-pb-dock": "" }, null, at(0, 604, wide, 156));
  const els = Object.entries(cards).map(([key, [col, l, t, w, h]]) => node({ "data-pb-node": key }, bodies[col], at(l, t, w, h)));
  // what the lighting of the path (lightPath, paintDock) does to them
  for (const e of els) e.classList.toggle = () => {};
  box.classList.toggle = () => {}; box.querySelectorAll = (sel) => (sel === "[data-pb-node]" ? els : []);
  Object.assign(dock, { setAttribute() {}, removeAttribute() {}, innerHTML: "" });
  b.root = { querySelector: (sel) => (sel === "[data-pb-root]" ? box : sel === "[data-pb-dock]" ? dock : null),
    querySelectorAll: (sel) => (sel === "[data-pb-scroll]" ? Object.values(bodies) : sel === "[data-pb-node]" ? els : []) };
  Object.assign(b.win, { innerWidth: wide, innerHeight: 800, matchMedia: () => ({ matches: !!over.calm }),
    setTimeout: (fn, ms) => { timers.push([fn, ms]); return timers.length; }, clearTimeout: (id) => cleared.push(id) });
  return { calls, timers, cleared, box, bodies };
};
const said = (s) => s.calls.map(([where, o]) => [where, o.top ?? o.left, o.behavior]);
const over = (key, x = 0, y = 0) => ({ target: node({}, node({ "data-pb-node": key })), clientX: x, clientY: y });
const out = {};
"""

PINS = [
    # ── the rules, as values ──
    ("key_and_uses",
     '',
     '[m.PoolBoard.key({ accountId: "sub", model: "gpt-sol" }), m.PoolBoard.key({ output: "srv:1" }), m.PoolBoard.key({ id: "r2" }), m.PoolBoard.key(null),'
     ' [...m.PoolBoard.uses(st.topology.pools).entries()]]',
     '["acc:sub/gpt-sol","out:srv:1","","",[["acc:sub/gpt-sol",["Standart"]],["out:srv:22008",["Standart"]],["acc:sub/gpt-luna",["Econom"]],["out:srv:22999",["Econom"]]]]',
     "цель строки — модель аккаунта или выход; строка без каната ключа не имеет; пулы, где стоит цель, — по порядку пулов"),
    ("uses_names_a_pool_once",
     '',
     '[...m.PoolBoard.uses([{ id: "a", name: "A", steps: [{ output: "srv:1" }, { output: "srv:1" }] }, { id: "b", steps: [{ output: "srv:1" }] }]).entries()]',
     '[["out:srv:1",["A","b"]]]',
     "пул, где цель стоит дважды, назван у неё один раз; пул без имени — своим id"),
    ("shown_models",
     '',
     '[m.PoolBoard.shown(["a", "b"], ["b", "c"]), m.PoolBoard.shown([], []), m.PoolBoard.shown(["a", ""], [null, "a"]), m.PoolBoard.shown(undefined, ["x"])]',
     '[["a","b","c"],[],["a"],["x"]]',
     "на карточке аккаунта — модели, добавленные к ней, в их порядке, потом те, что называют строки пулов, но в списке их нет: "
     "канату строки нужно, куда прийти; negative: пустая не показана, каждая — один раз"),
    ("candidates",
     '',
     '''(() => { const c = (...a) => { const r = m.PoolBoard.candidates(...a); return { ...r, models: r.models.map((x) => x.id) }; };
       return [c(CATALOGUE, ["gpt-sol"]), c(CATALOGUE, ["gpt-sol"], " LUN "), c(OR_CATALOGUE, [], "", 2), c(CATALOGUE, ["gpt-sol"], "embed"),
         c(CATALOGUE, ["gpt-sol"], "gpt-sol"), c(null, [], "my/model"), c({ models: [{ id: "x/y", name: "Fancy One", chat: true }] }, [], "fancy").models,
         c({ models: [{ id: "e", chat: false }], fetchedAt: 1 }, [], "")]; })()''',
     '[{"models":["gpt-luna","gpt-astra"],"more":0,"typed":"","free":2,"chat":3},{"models":["gpt-luna"],"more":0,"typed":"","free":2,"chat":3},'
     '{"models":["a/one","b/two"],"more":1,"typed":"","free":3,"chat":3},{"models":[],"more":0,"typed":"embed","free":2,"chat":3},'
     '{"models":[],"more":0,"typed":"","free":2,"chat":3},{"models":[],"more":0,"typed":"my/model","free":0,"chat":0},["x/y"],'
     '{"models":[],"more":0,"typed":"","free":0,"chat":0}]',
     "«＋ модель» предлагает чат-модели списка, которых на карточке нет, — те, где id или имя содержит набранное, в любом регистре; "
     "сверх предела — счётом; ничего не нашлось — набранное предлагается как есть; negative: рядом с найденными набранное "
     "не предлагается (часть id читалась бы моделью), эмбеддинг не предлагается, показанная — ни в списке, ни как набранная; "
     "без списка — только набранное; список без чат-моделей и список, весь на карточке, — два разных факта (chat 0 и free 0)"),
    ("window_text",
     '',
     '[m.PoolBoard.windowText(272000), m.PoolBoard.windowText(128500), m.PoolBoard.windowText(0), m.PoolBoard.windowText(undefined), m.PoolBoard.windowText("x")]',
     '["272K","129K","","",""]',
     "окно модели в списке — тысячами токенов; negative: не сказано — ничего, а не «0K»"),
    ("fold_cells",
     '',
     '(() => { const outs = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }]; const st8 = { a: "running", b: "stopped", c: "stopped", d: "failed" };'
     ' const f = (named, exp) => { const r = m.PoolBoard.foldCells(outs, (o) => st8[o.id], (o) => named.includes(o.id), exp); return [r.shown.map((o) => o.id), r.quiet.map((o) => o.id), r.folded]; };'
     ' return [f([], false), f(["b"], false), f([], true)]; })()',
     '[[["a","d"],["b","c"],true],[["a","b","c","d"],[],false],[["a","b","c","d"],[],true]]',
     "две и больше остановленных ячеек, которых не называет ни одна строка, сложены под кнопку; упавшая — на виду; "
     "negative: названная строкой — на виду, а одна оставшаяся не складывается; раскрыто — все"),
    ("curve",
     '',
     '[m.PoolBoard.curve({ x: 0, y: 0 }, { x: 200, y: 100 }), m.PoolBoard.curve({ x: 0, y: 0 }, { x: 20, y: 50 })]',
     '["M 0 0 C 100 0, 100 100, 200 100","M 0 0 C 40 0, -20 50, 20 50"]',
     "канат выходит вправо и входит слева; boundary: близкие точки — плечо не короче 40"),
    # ── the columns ──
    ("clients_column",
     '',
     r"""(() => { const [b] = board(); const h = b.clientsHtml(); const her = part(h, 'data-pb-client="23001"'), bot = part(h, 'data-pb-client="23002"');
       const chips = (x) => [...x.matchAll(/data-t="pb-deny-chip" data-t-id="([^"]+)"/g)].map((c) => c[1]);
       return [her.includes('data-t-state="open"'), her.includes("🔑 …a1b2"), her.includes('<span class="pb-dot out anchor" data-pb-anchor aria-hidden="true"></span>'),
         her.includes("data-pb-out"), her.includes(">" + fill(en.pbClientSeesAll, { all: "5" }) + "<"), chips(her), her.includes("data-pb-deny-open"),
         bot.includes('data-t-state="closed"'), bot.includes(">" + fill(en.pbClientSeesSome, { n: "4", all: "5" }) + "<"), chips(bot), bot.includes(">⊘ Econom<"),
         h.includes("pb-client paused"), h.includes("old agent"), h.indexOf(">Bot<") < h.indexOf(">Hermes<")]; })()""",
     '[true,true,true,false,true,[],true,true,true,["pool:eco"],true,true,false,true]',
     "клиент, которому ничего не запрещено (1.3.675: наборов нет), — «видит все 5», точка у края — только метка, откуда идут его канаты (тянуть из клиента нечего: "
     "он зовёт то, что называет), чипов запретов нет, «＋ Запретить» есть; клиенту запрещён пул — «видит 4 из 5» и чип «⊘ Econom»; на паузе — блеклый; по имени; "
     "negative: порт агента старого вида — не клиент"),
    ("clients_none",
     'st.setTopology({ ...TOPO(), proxies: [] });',
     '(() => { const [b] = board(); const h = b.clientsHtml(); return [h.includes(en.pbNoClients), h.includes("data-pb-add-client"),'
     ' b.modelsHtml().includes("data-pb-add-account"), b.poolsHtml().includes("data-pb-add-pool")]; })()',
     '[true,false,false,true]',
     "negative: клиентов нет — сказано словами и где их создают; ＋ клиента и ＋ подписки в Маршрутизации нет — их добавляют на "
     "главной доске (владелец, 2026-10-12); ＋ пула остаётся: пулы собирают здесь"),
    ("pool_rows_three_kinds",
     '',
     '(() => { const [b] = board(); const h = b.poolsHtml(); const std = part(h, \'data-pb-pool="std"\'); const row = (id) => item(std, \'<li class="pool-rung">\', `data-pb-row="${id}"`);'
     ' const [a, c, o] = ["sub", "r1", "r2"].map(row);'
     ' return [a.includes("<b>gpt-sol</b><small>☁ ChatGPT</small>"), a.includes(\'data-t-state="stop"\') && a.includes(">" + en.poolStopReached + "<"),'
     ' c.includes("<b>Coder</b><small>🖥 Box :22008</small>"), c.includes("pool-step pb-row serving") && c.includes(">" + en.poolServing + "<"),'
     ' o.includes(en.pbRowOpen) && o.includes("pb-row open") && o.includes(\'class="pb-dot out open"\') && !o.includes("pb-status"),'
     ' [a, c, o].map((r) => (r.match(/class="pb-rank">(\\d)</) || [])[1]),'
     ' !std.includes("pb-new-out") && !std.includes("data-pb-add-row"),'
     ' std.includes(\'class="pool-ladder pb-rows"\')]; })()',
     '[true,true,true,true,true,["1","2","3"],true,true]',
     "три вида строк: модель подписки с аккаунтом, ячейка с машиной и портом, строка без каната; слово прокси на каждой, "
     "служащая строка подсвечена; номера по порядку; «＋ строка» с пунктирной точкой стоит в полосе, а не под строками (1.3.533; "
     "её тянут к модели с 1.3.500, кнопки щелчком нет); negative: у строки без каната плашка не повторяет то, что уже сказано на месте её цели"),
    ("pool_row_gone_said_red",
     '',
     '(() => { const [b] = board(); const eco = part(b.poolsHtml(), \'data-pb-pool="eco"\'); const r = part(eco, \'data-pb-row="r1"\', "</li>");'
     ' return [r.includes(\'class="pb-target gone"\') && r.includes("<b>srv:22999</b>") && r.includes(en.poolOutputMissing), eco.includes("data-pb-history"),'
     ' r.includes(\'data-t-state="unknown"\') && r.includes(en.poolNoRequest)]; })()',
     '[true,false,true]',
     "ячейки, к которой ведёт строка, нет — сказано красным, без каната; у пула без истории нет кнопки 🕘; "
     "negative: прокси ещё не решал о пуле — «запросов не было», а не «готов»"),
    ("selected_but_passed_by_is_not_serving",
     'st.topology.poolsRuntime.pools.std = { selectedStepId: "r1", steps: [{ stepId: "r1", reason: "unavailable" }] };',
     '(() => { const [b] = board(); const c = item(part(b.poolsHtml(), \'data-pb-pool="std"\'), \'<li class="pool-rung">\', \'data-pb-row="r1"\');'
     ' return [c.includes("pb-row serving"), c.includes(\'data-t-state="off-cell"\') && c.includes(en.poolCellOff)]; })()',
     '[false,true]',
     "negative: строка, которую прокси выбрал последней, но о которой сказал «ячейка выключена», — не «служит»: слово прокси главнее"),
    ("pool_status_login_and_silent",
     'st.topology.cloudAccounts[0].hasCredential = false;',
     '(() => { const [b] = board(); const a = part(b.poolsHtml(), \'data-pb-row="sub"\', "</li>"); st.topology.poolsRuntime = { available: false, pools: {}, events: [] };'
     ' const [b2] = board(); const c = part(b2.poolsHtml(), \'data-pb-row="r1"\', "</li>"); return [a.includes(\'data-t-state="login"\') && a.includes(en.poolLoginNeeded), c.includes(en.poolProxySilent)]; })()',
     '[true,true]',
     "подписка без входа говорит об этом раньше прокси; прокси молчит — так и сказано"),
    ("history_toggle",
     '',
     'await (async () => { const [b] = board(); const pool = st.topology.pools.find((p) => p.id === "std"); const card = () => part(b.poolsHtml(), \'data-pb-pool="std"\');'
     ' const shut = b.poolDetailsHtml(pool); b.history.add("std"); const open = b.poolDetailsHtml(pool);'
     ' return [shut.includes(\'data-pb-history aria-expanded="false" data-t="pb-history-toggle">\' + esc(en.poolHistory)), shut.includes("pb-history\\""), open.includes(\'data-t="pb-history"\'),'
     ' open.includes("gpt-sol · ChatGPT → Coder :22008"), card().includes("data-pb-history"), card().includes("pb-history"), card().includes("🕘"),'
     ' b.poolDetailsHtml(st.topology.pools.find((p) => p.id === "eco")).includes("data-pb-history")]; })()',
     '[true,false,true,true,false,false,false,false]',
     "история переключений — в полосе пула, строкой «Switch history», и называет строки их моделями; negative: на карточке пула ни кнопки, ни списка, ни 🕘 (1.3.533); "
     "у пула без переключений в полосе нет и кнопки"),
    ("models_subscription",
     '',
     r"""(() => { const [b] = board(); const card = part(b.modelsHtml(), 'data-pb-account="sub"'); const row = (model) => item(card, '<div class="pb-model', `data-pb-key="acc:sub/${model}"`);
       const strip = (model) => b.modelDetailsHtml(`acc:sub/${model}`); const key = part(b.modelsHtml(), 'data-pb-account="or"');
       return [keys(card, "acc:sub/"), strip("gpt-sol").includes('[bars sub sub/gpt-sol stop={"18000":20} switch={"18000":30} max=90]'),
         strip("gpt-luna").includes('stop={"18000":10} switch={"18000":10}'), row("gpt-astra").includes(en.pbInNoPool), row("gpt-sol").includes("pb-use none"), card.includes(en.cloudConnected),
         ["data-pb-more", "data-usage-refresh", "embed-1", "pb-models-none", "[bars", "[usage"].filter((x) => card.includes(x)),
         (card.match(/\[meters sub /g) || []).length, card.includes('data-t="pb-limits"'), key.includes("[meters") || key.includes("pb-limits"),
         ["gpt-sol", "gpt-astra", "gpt-luna"].map((x) => row(x).includes("data-pb-model-remove")),
         row("gpt-astra").includes(`title="${esc(fill(en.pbModelRemove, { model: "gpt-astra" }))}"`), card.includes('data-pb-add-model="sub"'),
         card.includes('stops={"18000":[10,20]}')]; })()""",
     r'''[["gpt-sol","gpt-astra","gpt-luna"],true,true,true,false,true,[],1,true,false,[false,true,false],true,true,true]''',
     "подписка (2026-10-12: «только те, что я добавил»): добавленные модели в их порядке, потом названная строкой пула, которой в списке нет; "
     "на карточке модель — только имя, ⏱ и «не в пуле» (1.3.534: в каких пулах — в полосе); лимиты подписки нарисованы ОДИН раз, а не у каждой модели; "
     "свои уровни модели (у незаданной — по умолчанию у контроллера) — в её полосе; ✕ — только у модели вне пулов, и он говорит, что сделает; внизу «＋ модель»; "
     "негативы: каталог не высыпан (ни эмбеддинга, ни не добавленных), «ещё» нет, ⟳ в шапке нет, высоких шкал на карточке нет, у аккаунта по ключу лимитов нет; "
     "красные риски на шкалах карточки — пороги остановки её моделей (1.3.541): у gpt-sol 20, у остальных — 10 контроллера, каждый уровень один раз"),
    # ── the Models column as the mockup draws it (1.3.541; the owner, 2026-10-14) ──
    ("account_card_layout",
     '',
     r"""(() => { const [b] = board(); const card = part(b.modelsHtml(), 'data-pb-account="sub"'); const head = part(card, '<div class="pb-src-head">', "</div>");
       const at = (x) => card.indexOf(x);
       return [head.includes('<b title="ChatGPT">ChatGPT</b>'), head.includes('data-pb-add-model="sub"'), head.includes('data-t="pb-account-state" data-t-state="connected"'),
         head.includes('<i class="pb-led" aria-hidden="true"></i>' + en.cloudConnected), at("data-pb-add-model") < at('data-t="pb-account-state"'),
         at("[meters sub") > at("pb-src-head"), at("[meters sub") < at('class="pb-model"'), at('data-pb-key="acc:sub/gpt-sol"') < at('data-pb-key="acc:sub/gpt-luna"'),
         card.includes("<i>sub</i>"), card.includes("cloud-account-icon"), /resets|⟳|data-usage-refresh/.test(card),
         b.modelsHtml().includes('<article class="pb-card pb-src" data-pb-account="sub"'), b.modelsHtml().includes('<article class="pb-card pb-src empty" data-pb-account="or"'),
         (card.match(/data-pb-add-model/g) || []).length]; })()""",
     r'''[true,true,true,true,true,true,true,true,false,false,false,true,true,1]''',
     "карточка подписки: имя слева, справа — лампа и «Connected»; «＋ модель» — в шапке, после имени; шкалы — одной строкой между шапкой и моделями, "
     "модели — по порядку; у карточки без моделей свой признак «empty» (по нему «＋ модель» видна без наведения); "
     "negative: значка провайдера нет, «resets» и ⟳ на карточке нет (когда сбрасывается окно — в подсказке шкалы и в полосе)"),
    ("account_card_waiting",
     'st.topology.cloudAccounts[0].hasCredential = false; st.topology.cloudAccounts[1].hasCredential = false;',
     r"""(() => { const [b] = board(); const note = (id) => (part(b.modelsHtml(), `data-pb-account="${id}"`).match(/<span class="pb-src-note"[^>]*>.*?<\/span>/s) || [""])[0];
       const sub = note("sub"), or = note("or");
       return [sub.includes('data-t-state="waiting"') && sub.includes('class="pb-led wait"') && sub.includes(en.poolLoginNeeded),
         or.includes('data-t-state="waiting"') && or.includes(en.cloudNoKeyYet), part(b.modelsHtml(), 'data-pb-account="sub"').includes("[meters"), sub.includes(en.cloudConnected)]; })()""",
     r'''[true,true,false,false]''',
     "аккаунт без входа или без ключа говорит своё слово и горит янтарным, а не зелёным «Connected»; negative: шкал у него нет — читать нечего"),
    ("model_switch_chip",
     '',
     r"""(() => { const chip = (b, model) => (item(part(b.modelsHtml(), 'data-pb-account="sub"'), '<div class="pb-model', `data-pb-key="acc:sub/${model}"`)
         .match(/<span class="pb-chip" data-t="pb-model-switch" title="([^"]*)">([^<]*)<\/span>/) || []).slice(1);
       const [b0] = board(); const first = [chip(b0, "gpt-sol"), chip(b0, "gpt-luna"), chip(b0, "gpt-astra")];
       st.topology.modelLevels.set.sub["gpt-sol"] = { stopAt: { "18000": 20, "604800": 10 }, switchAt: { "18000": 30, "604800": 20 } };
       st.topology.modelLevels.set.sub["gpt-luna"] = { stopAt: { "18000": 20, "604800": 10 }, switchAt: { "18000": 30, "604800": 10 } };
       const [b1] = board(); const second = [chip(b1, "gpt-sol"), chip(b1, "gpt-luna")];
       const cell = item(part(b1.modelsHtml(), 'data-pb-machine="box"'), '<div class="pb-model', 'data-pb-key="out:srv:22008"');
       return [first, second, cell.includes("pb-model-switch")]; })()""",
     r'''[[["next when 30% (5h) is left","switch 30% (5h)"],[],[]],[["next when 30% (5h) · 20% (7d) is left","switch 30% (5h) · 20% (7d)"],["next when 30% (5h) is left","switch 30% (5h)"]],false]''',
     "метка «switch…» на строке модели — уровень, с которого пул идёт дальше, по каждому окну (короткое первым), с подсказкой «next when … is left»; "
     "negative: нет уровня выше остановки — нет метки (на остановке переключение ничего не меняет), окно с уровнем у самой остановки в метку не входит; у ячейки машины метки нет"),
    ("model_row_marks_order",
     'st.topology.pools[0].steps[0].switchReached = { resetAt: 1700000000, windowSeconds: 18000, remainingPct: 25, reservePct: 30 };',
     r"""(() => { const [b] = board(); const card = part(b.modelsHtml(), 'data-pb-account="sub"'); const row = (m) => item(card, '<div class="pb-model', `data-pb-key="acc:sub/${m}"`);
       const inc = (h, marks) => marks.map((x) => h.indexOf(x)).every((x, i, all) => x > 0 && (i === 0 || x > all[i - 1]));
       return [inc(row("gpt-sol"), ["pb-model-name", 'data-t="pb-model-switch"', 'data-t="pb-model-level"', "pb-sched"]),
         inc(row("gpt-astra"), ["pb-model-name", "pb-sched", "pb-use none", "pb-model-remove"]), row("gpt-sol").includes('<span class="pb-chips">'),
         row("gpt-sol").includes("pb-use none") || row("gpt-sol").includes("pb-model-remove")]; })()""",
     r'''[true,true,true,false]''',
     "метки модели — справа от имени, по порядку: «switch…», «↓ yielding», ⏱, «in no pool», ✕; negative: у модели, которую называет пул, нет ни «in no pool», ни ✕"),
    ("pool_head_order",
     'st.topology.pools[0].kind = { jobs: ["llm"], inputs: [], languages: [] };',
     r"""(() => { const [b] = board(); const head = part(b.poolsHtml(), 'data-pb-pool="std"', "</header>"); const at = (x) => head.indexOf(x);
       const order = ["pb-card-grip", 'class="pb-pool-id"', "data-pb-pool-name", 'data-t="pb-pool-turns"', 'data-t="pb-kind"', "data-pb-pool-copy", "data-pb-pool-delete"].map(at);
       return [order.every((x, i) => x > 0 && (i === 0 || x > order[i - 1]))]; })()""",
     r'''[true]''',
     "голова пула, как в макете: ручка, «id:», имя, справа «⇣ N по очереди», после неё знаки работы, ⧉, ✕ последним"),
    ("account_meters_stops",
     'st.topology.modelLevels.set.sub["gpt-astra"] = { stopAt: { "18000": 0, "604800": 10 }, switchAt: {} }; st.topology.modelLevels.set.sub["gpt-luna"] = { stopAt: { "18000": 10 }, switchAt: {} };',
     r"""(() => { const [b] = board(); const sub = st.topology.cloudAccounts[0];
       const seen = (models) => b.stopsOf(sub, models);
       const meters = (id) => (part(b.modelsHtml(), `data-pb-account="${id}"`).match(/\[meters \w+ stops=(\{.*?\})\]/) || [])[1];
       return [seen(["gpt-sol", "gpt-astra", "gpt-luna"]), seen([]), seen(["gone-model"]), meters("sub"), meters("or") ?? null]; })()""",
     r'''[{"18000":[10,20],"604800":[10]},{},{"18000":[10]},"{\"18000\":[10,20],\"604800\":[10]}",null]''',
     "красные риски на шкалах — уровни остановки моделей карточки по длине окна: каждый один раз, меньший первым; negative: «0» — не уровень (остановки нет); "
     "карточка без моделей рисок не даёт; модель, которой контроллер уровней не задал, останавливается на его уровне по умолчанию, а не без остановки"),
    ("machine_card_marks_slot_and_address",
     'const T = TOPO(); T.routers[0].outputs.unshift({ id: "mm:a1", upstreamType: "machine", upstreamHost: "10.0.0.5", upstreamPort: 8092, upstreamModel: "gemma", hostId: "box", label: "gemma", jobs: ["speech-translate"] },'
     ' { id: "srv:30001", upstreamType: "llama", upstreamHost: "10.0.0.9", upstreamPort: 30001, label: "Lone :30001" }); T.nodes[0].entryModels = [{ id: "gemma", state: "running", copies: [{ port: 22008 }] }]; st.setTopology(T);',
     r"""(() => { const [b] = board(); const html = b.modelsHtml(); const box = part(html, 'data-pb-machine="box"'), lone = part(html, 'data-pb-machine="10.0.0.9"');
       const wide = (h) => h.includes('class="pb-card pb-src wide-marks"'); const open = () => { b.expanded.add("m:box"); return part(b.modelsHtml(), 'data-pb-machine="box"'); };
       return [html.includes('class="pb-card pb-src wide-marks" data-pb-machine="box"'), html.includes('class="pb-card pb-src" data-pb-machine="10.0.0.9"'),
         box.includes('<b title="10.0.0.5">Box</b>'), lone.includes("<b>10.0.0.9</b>") && !lone.includes("<b title="), box.includes("🎧🌐")]; })()""",
     r'''[true,true,true,true,true]''',
     "карточка машины со знаком из двух («🎧🌐» — слышит и переводит) даёт всем своим строкам место пошире, чтобы имена стояли в одну линию; negative: без такого знака место обычное; "
     "адрес в подсказке имени — только когда он не то же, что имя (имя машины неизвестно — адрес и есть имя, подсказка не повторяет его)"),
    ("machine_card_layout",
     '',
     r"""(() => { const [b] = board(); const card = part(b.modelsHtml(), 'data-pb-machine="box"'); const head = part(card, '<div class="pb-src-head">', "</div>");
       const row = (h, id) => item(h, '<div class="pb-model', `data-pb-key="out:${id}"`);
       b.expanded.add("m:box"); const open = part(b.modelsHtml(), 'data-pb-machine="box"'); const stopped = row(open, "srv:22009");
       return [head.includes('<span class="pb-src-icon" aria-hidden="true"><svg') && !head.includes("🖥"), head.includes('<b title="10.0.0.5">Box</b>'),
         head.indexOf("<b") < head.indexOf("pb-src-note"), row(card, "srv:22008").includes('class="pb-led"') && row(card, "srv:22008").includes('title="running"'),
         stopped.includes('class="pb-led off"') && stopped.includes('title="stopped"') && !stopped.includes("pb-cell-state"),
         row(card, "srv:22011").includes('<span class="pb-cell-state">failed</span>') && row(card, "srv:22011").includes('class="pb-led bad"')
           && row(card, "srv:22011").indexOf("pb-cell-state") < row(card, "srv:22011").indexOf('class="pb-led bad"') && !row(card, "srv:22011").includes("pb-model-remove"),
         ["srv:22008", "srv:22011"].map((id) => row(card, id).includes('<span class="pb-model-mark" aria-hidden="true"></span>')), /router-out-host-addr/.test(card)]; })()""",
     r'''[true,true,true,true,true,true,[true,true],false]''',
     "карточка машины: линия монитора, имя (адрес — в подсказке), справа сводка ячеек; в строке ячейки лампа справа — зелёная, кольцо, красная; остановленная говорит только кольцом "
     "(слово — в подсказке лампы), упавшая — ещё и словом; место перед именем занято всегда, чтобы имена стояли в одну линию; negative: смайлика 🖥 и адреса рядом с именем нет"),
    ("models_levels_unknown_draws_no_handles",
     'delete st.topology.modelLevels;',
     '(() => { const [b] = board(); return [b.levelsOf("sub", "gpt-sol"), b.modelDetailsHtml("acc:sub/gpt-sol").includes("max=0")]; })()',
     '[{"stopAt":{},"switchAt":{},"max":0},true]',
     "negative: контроллер не сказал об уровнях — ручек нет (max 0) в полосе модели, а не догадка «10%»"),
    ("models_key_account_added_only",
     '',
     '''(() => { const [b, log] = board(); b.catalogues.delete("or"); const card = () => part(b.modelsHtml(), 'data-pb-account="or"'); const none = card();
       st.topology.addedModels.or = ["b/two"]; const one = card();
       return [(none.match(/data-pb-key=/g) || []).length, none.includes('data-t="pb-models-none"') && none.includes(esc(en.pbModelsNone)),
         none.includes('data-pb-add-model="or"'), keys(one, "acc:or/"), ["pb-models-none", "[bars", "data-pb-more"].filter((x) => one.includes(x)),
         b.catalogues.has("or"), log.calls.length]; })()''',
     '[0,true,true,["b/two"],[],false,0]',
     "аккаунт с ключом — тоже только добавленные: ни одной — так и сказано, с «＋ модель», а не пустая карточка; negative: каталог "
     "не высыпан и не прячется под «ещё», шкал подписки нет; карточка список не читает — его читает только открытый «＋ модель»"),
    ("picker_opens_finds_and_adds",
     '',
     '''await (async () => { const [b, log] = board(); const el = { innerHTML: "" }; const body = { innerHTML: "" }; let focused = 0;
       const field = { value: "", focus() { focused += 1; }, setSelectionRange(a, z) { this.sel = [a, z]; } };
       b.root = { querySelector: (s) => ({ "[data-pb-root]": el, "[data-pb-picker] [data-pb-pick-query]": field, "[data-pb-picker] [data-pb-pick-body]": body,
         "[data-pb-picker] [data-pb-pick-model]": node({ "data-pb-pick-model": "b/two" }) })[s] ?? null };
       const click = (attrs) => b.click({ target: node(attrs), stopPropagation() {} });
       const enter = (key) => b.key({ key, target: node({ "data-pb-pick-query": "" }), preventDefault() {} });
       await click({ "data-pb-add-model": "or" });
       const card = part(el.innerHTML, 'data-pb-account="or"');
       const opened = [{ ...b.picking }, focused, field.sel, card.includes('data-t="pb-picker" data-t-id="or"'), card.includes('data-pb-add-model="or"'),
         el.innerHTML.includes('data-pb-add-model="sub"'), (card.match(/data-t="pb-pick-model"/g) || []).length, card.includes("<code>a/one</code>")];
       const before = el.innerHTML; b.find("TW");
       const found = [b.picking.query, (body.innerHTML.match(/data-t="pb-pick-model"/g) || []).length, body.innerHTML.includes('data-pb-pick-model="b/two"'),
         body.innerHTML.includes('data-t="pb-pick-typed"'), el.innerHTML === before];
       await enter("Enter");
       const added = [log.calls.slice(-1)[0], log.applied.length, b.picking];
       await click({ "data-pb-add-model": "or" }); await click({ "data-pb-pick-model": "c/three" }); const picked = log.calls.slice(-1)[0];
       await click({ "data-pb-add-model": "or" }); await enter("Escape"); const escaped = b.picking;
       await click({ "data-pb-add-model": "or" }); await click({ "data-pb-pick-close": "" }); const closed = b.picking;
       return [opened, found, added, picked, escaped, closed, await enter("Enter"), log.calls.length]; })()''',
     '[[{"accountId":"or","query":""},1,[0,0],true,false,true,3,true],["TW",1,true,false,true],'
     '[["/api/pools/add-model",{"accountId":"or","model":"b/two"}],1,null],["/api/pools/add-model",{"accountId":"or","model":"c/three"}],null,null,null,2]',
     "«＋ модель» открывает список аккаунта на его карточке, поле поиска в фокусе, один список за раз; набранное перерисовывает "
     "только найденное — карточка не перерисована, поле не теряет слово; Enter ставит первую найденную, щелчок — выбранную, ответ "
     "контроллера закрывает список; Escape и ✕ закрывают; negative: рядом с найденной набранное как модель не предложено; "
     "Enter без открытого списка — ничего"),
    ("picker_refused_stays_open",
     '',
     '''await (async () => { const [b, log] = board({ fail: true }); const el = { innerHTML: "" };
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) };
       await b.click({ target: node({ "data-pb-add-model": "or" }), stopPropagation() {} });
       await b.click({ target: node({ "data-pb-pick-model": "a/one" }), stopPropagation() {} });
       return [log.notes, b.picking, el.innerHTML.includes('data-t="pb-picker" data-t-id="or"'), log.applied.length]; })()''',
     '[["controller is down"],{"accountId":"or","query":""},true,0]',
     "отказ контроллера — список остаётся открытым, тост говорит почему; negative: на карточку ничего не встало"),
    ("picker_says_what_it_knows",
     '',
     '''(() => { const [b] = board();
       st.topology.cloudAccounts.push({ id: "bare", name: "Bare", type: "custom", hasCredential: false }, { id: "sub2", name: "Sub 2", accountType: "openai-subscription", hasCredential: false });
       const said = (id, cat, query = "") => { if (cat === undefined) b.catalogues.delete(id); else b.catalogues.set(id, cat); b.picking = { accountId: id, query };
         const card = part(b.modelsHtml(), `data-pb-account="${id}"`); return card.slice(card.indexOf("data-pb-picker")); };
       const note = (h) => { const i = h.indexOf('data-t="pb-pick-note"'); return i < 0 ? "" : h.slice(h.indexOf(">", i) + 1, h.indexOf("</div>", i)); };
       const many = { models: Array.from({ length: 63 }, (_, i) => ({ id: `m/${i}`, chat: true })), fetchedAt: 1 };
       const failed = said("or", { error: "boom" }); const nothing = said("or", OR_CATALOGUE, "zzz");
       return [note(said("or", { loading: true })) === esc(en.pbCatalogueReading), note(failed) === esc("⚠ " + en.pbCatalogueFailed) && failed.includes('title="boom"'),
         note(said("or", { models: [], fetchedAt: null })) === esc(en.pbCatalogueNotYet),
         note(said("or", { models: [{ id: "e", chat: false }], fetchedAt: 1 })) === esc(en.pbCatalogueEmpty),
         note(said("sub", CATALOGUE)) === esc(en.pbModelsAllAdded), (said("or", many).match(/data-t="pb-pick-model"/g) || []).length,
         note(said("or", many)) === esc(fill(en.pbModelsMore, { n: "3" })), note(nothing) === esc(en.pbModelsNoMatch) && nothing.includes('data-t="pb-pick-typed"'),
         note(said("or", OR_CATALOGUE)), note(said("bare", undefined)) === esc(en.cloudNoKeyYet), note(said("sub2", undefined)) === esc(en.poolLoginNeeded),
         [b.catalogues.has("bare"), b.catalogues.has("sub2")]]; })()''',
     '[true,true,true,true,true,60,true,true,"",true,true,[false,false]]',
     "что список знает, сказано вместо пустоты: читается; не прочитан (с причиной в подсказке); контроллер его ещё не читал; в нём нет "
     "чат-моделей; все его модели уже на карточке; сверх 60 — счётом; ничего не нашлось — и предложен набранный id; negative: "
     "список без входа не читается — сказано, что нужен ключ или вход; найдено в пределах — без лишней строки"),
    ("picker_reads_a_list_again",
     '',
     '''await (async () => { const [b, log] = board(); const el = { innerHTML: "" }; b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) };
       const open = (cat) => { b.catalogues.set("or", cat); b.openPicker("or"); const got = b.catalogues.get("or"); b.closePicker(); return got; };
       const kept = [open(OR_CATALOGUE) === OR_CATALOGUE, open({ loading: true }).loading];
       const again = [open({ error: "boom" }), open({ models: [], fetchedAt: null })];
       for (let i = 0; i < 6; i += 1) await null;   // the reads start a tick later; this harness's timers are recorded, not run
       return [kept, again, log.calls.filter((c) => c[0].startsWith("/api/cloud-accounts/catalogue")).length, b.openPicker("nobody")]; })()''',
     '[[true,true],[{"loading":true},{"loading":true}],2,null]',
     "открытый «＋ модель» читает список заново, если тот не прочитался или контроллер его ещё не читал; negative: прочитанный и "
     "читающийся не трогает; аккаунта нет — ничего"),
    ("model_remove_and_listeners",
     '',
     '''await (async () => { const [b, log] = board(); const c = { dataset: {}, listeners: {}, addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); } };
       b.mount(c); const fire = (type, ev) => (c.listeners[type] || []).forEach((fn) => fn(ev));
       let prevented = 0; fire("mousedown", { target: node({ "data-pb-pick-model": "a/one" }), preventDefault() { prevented += 1; } });
       fire("mousedown", { target: node({ "data-pb-add-model": "or" }), preventDefault() { prevented += 10; } });
       b.picking = { accountId: "or", query: "" }; fire("input", { target: node({ "data-pb-pick-query": "" }, null, { value: "thr" }) });
       const typed = b.picking.query;
       await b.click({ target: node({ "data-pb-model-remove": "" }, node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-astra" })), stopPropagation() {} });
       return [prevented, typed, log.calls, b.removeModel("", "x"), ["mousedown", "input"].map((t) => (c.listeners[t] || []).length)]; })()''',
     '[1,"thr",[["/api/pools/remove-model",{"accountId":"sub","model":"gpt-astra"}]],null,[1,1]]',
     "✕ у модели — один запрос: снять её с карточки; нажатие на модель списка не уводит фокус из поиска — иначе отложенная "
     "перерисовка страницы подменит кнопку между нажатием и щелчком; набранное в поиске — в списке; negative: нажатие мимо списка "
     "фокус не держит; ✕ без аккаунта или модели — ничего; слушатели — по одному"),
    ("page_drawing_keeps_the_scroll",
     '',
     '''(() => { const [b] = board(); const first = b.scroll; const old = { scrollTop: 640, scrollLeft: 30 }; const fresh = { scrollTop: 0, scrollLeft: 0 };
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? old : null) }; b.html(st.topology);
       const c = { dataset: { pbBound: "1" }, querySelector: (s) => (s === "[data-pb-root]" ? fresh : null) }; b.mount(c);
       const none = { scrollTop: 0, scrollLeft: 0 }; b.root = { querySelector: () => null }; b.html(st.topology);
       b.mount({ dataset: { pbBound: "1" }, querySelector: (s) => (s === "[data-pb-root]" ? none : null) });
       return [first, [fresh.scrollTop, fresh.scrollLeft], b.scroll, [none.scrollTop, none.scrollLeft]]; })()''',
     '[null,[640,30],null,[0,0]]',
     "страница рисует доску целиком (добавили модель, провели канат) — доска встаёт туда, куда была прокручена, а не к началу "
     "колонки (2026-10-12); negative: первая отрисовка — прокручивать нечего, ничего не задано"),
    ("columns_keep_their_places_across_drawings",
     '',
     r"""(() => { const [b] = board();
       const col = (key, top) => ({ dataset: { pbScroll: key }, scrollTop: top });
       const set = (tops) => Object.entries(tops).map(([k, v]) => col(k, v));
       const root = (cols, box) => ({ querySelectorAll: (s) => (s === "[data-pb-scroll]" ? cols : []), querySelector: (s) => (s === "[data-pb-root]" ? box : null) });
       b.root = root(set({ clients: 40, sets: 0, pools: 640, models: 15 }), { scrollTop: 0, scrollLeft: 30 }); b.html(st.topology); const read = b.scroll;
       const fresh = set({ clients: 0, sets: 0, pools: 0, models: 0 }), box = { scrollTop: 0, scrollLeft: 0 };
       b.mount({ ...root(fresh, box), dataset: { pbBound: "1" } }); const mounted = [fresh.map((c) => c.scrollTop), box.scrollLeft];
       let live = set({ clients: 10, sets: 20, pools: 700, models: 0 });
       const el = { set innerHTML(_html) { live = set({ clients: 0, sets: 0, pools: 0, models: 0 }); }, querySelectorAll: (s) => (s === "[data-pb-scroll]" ? live : []) };
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) }; b.redraw();
       return [read, mounted, live.map((c) => [c.dataset.pbScroll, c.scrollTop])]; })()""",
     '[{"top":0,"left":30,"columns":{"clients":40,"sets":0,"pools":640,"models":15}},[[40,0,640,15],30],'
     '[["clients",10],["sets",20],["pools",700],["models",0]]]',
     "the columns scroll, each on its own, and a drawing replaces them: the page's drawing of the board whole (html, then mount) and the board's own "
     "drawing anew (redraw) both give each column the place it stood at — by the column's mark, not by its order — so a column scrolled down to a card "
     "does not jump to its top when a reading lands (1.3.548); negative: a column that stood at the top is left alone"),
    ("the_three_columns_carry_the_marks_their_scroll_is_kept_by",
     '',
     r"""(() => { const [b] = board(); const h = b.inner();
       return [...h.matchAll(/<div class="pb-col-body"([^>]*)>/g)].map((m) => (m[1].match(/data-pb-scroll="([^"]+)"/) || [])[1] || null); })()""",
     '["clients","pools","models"]',
     "the body of each of the three columns (1.3.675: no sets) carries the mark its scroll is kept by across drawings (data-pb-scroll), in the order they stand: a body "
     "with no mark would go back to its top with every reading that lands; negative: no fourth mark — nothing else in the board is a body that scrolls"),
    ("a_column_is_its_head_and_its_body",
     '',
     r"""(() => { const [b] = board(); return [b.clientsHtml(), b.poolsHtml(), b.modelsHtml()].map((h) => {
       const body = h.indexOf('<div class="pb-col-body"');
       return [h.indexOf('<div class="pb-col-head">') === 0, body > 0, (h.match(/class="pb-col-head"/g) || []).length, (h.match(/class="pb-col-body"/g) || []).length, h.slice(body).includes("pb-col-head")]; }); })()""",
     '[[true,true,1,1,false],[true,true,1,1,false],[true,true,1,1,false]]',
     "each column is its head, first, and its body, after it: one of each, and the head is not in the body — what scrolls is the body, and the head stands over it, always shown "
     "(the owner, 2026-10-18: \"the headings outside the area I scroll\"); negative: no head inside the body, no second body"),
    ("the_heads_tools_stand_with_the_head",
     '',
     r"""(() => { const [b] = board(); const head = (h) => h.slice(0, h.indexOf('<div class="pb-col-body"')), body = (h) => h.slice(h.indexOf('<div class="pb-col-body"'));
       const pools = b.poolsHtml();
       return [head(pools).includes("data-pb-add-pool"), head(pools).includes("data-pb-arrange"),
         body(pools).includes("data-pb-add-pool") || body(pools).includes("data-pb-arrange"), b.inner().includes("data-pb-add-set")]; })()""",
     '[true,true,false,false]',
     "the buttons that make a pool and arrange the pools are in their column's head, outside what scrolls: they are at hand however far the column is "
     "scrolled; negative: none of them is in a body, and none makes a set (1.3.675)"),
    ("the_clients_address_scrolls_with_the_clients",
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 };',
     r"""(() => { const [b] = board(); const h = b.clientsHtml(), cut = h.indexOf('<div class="pb-col-body"');
       return [h.slice(0, cut).includes("pb-entry"), h.slice(cut).includes("pb-entry"), h.slice(cut).indexOf("pb-entry") < h.slice(cut).indexOf("pb-client ")]; })()""",
     '[false,true,true]',
     "the address the clients are given is not a heading: it is the first line of the clients' body, above their cards, and it scrolls away with them — only the title stays; "
     "negative: it is not in the head"),
    ("the_lists_that_can_be_ordered_are_the_bodies",
     '',
     r"""(() => { const [b] = board(); const h = b.inner();
       return [[...h.matchAll(/<div class="pb-col-body"([^>]*)>/g)].map((m) => (m[1].match(/data-pb-list="([^"]+)"/) || [])[1] || null),
         /<section[^>]*data-pb-(?:list|scroll)=/.test(h), (h.match(/<section class="pb-col[^"]*"[^>]*data-pb-pools-drop/g) || []).length]; })()""",
     '[["clients","pools","models"],false,1]',
     "the list a card is carried along (data-pb-list) is the body, where the cards are and its offsets are measured from (step-carry.js): clients, pools, models; "
     "negative: no section carries a list or a scroll mark of its own; the pools' drop mark stays on the whole column, so a cable let go over its head makes a pool too"),
    ("models_cards_stand_in_the_order_kept",
     '',
     r"""(() => { const seats = (h) => [...h.slice(h.indexOf('data-pb-list="models"')).matchAll(/data-pb-seat="([^"]*)"/g)].map((x) => x[1]);
       const [b] = board(); const grips = (h) => (h.slice(h.indexOf('data-pb-list="models"')).match(/data-pb-card-grip/g) || []).length;
       const drew = (layout) => { b.html({ ...st.topology, layout }); return seats(b.inner()); };
       const own = seats(b.inner()), gripped = grips(b.inner());
       const kept = drew({ serverOrder: ["node:box", "cloud:or", "cloud:sub"], serverOrderRev: 5 });
       const stale = drew({ serverOrder: [], serverOrderRev: 4 });
       const named = drew({ serverOrder: ["node:gone", "cloud:or"], serverOrderRev: 6 });
       const [none] = board(); none.html({ cloudAccounts: [], pools: [], routers: [{ id: "router:default", outputs: [] }], proxies: [], nodes: [] });
       const empty = none.inner();
       return [own, gripped === own.length, kept, stale, named, empty.includes('data-pb-list="models"'), seats(empty)]; })()""",
     '[["cloud:sub","cloud:or","node:box"],true,["node:box","cloud:or","cloud:sub"],["node:box","cloud:or","cloud:sub"],["cloud:or","cloud:sub","node:box"],false,[]]',
     "карточки Models — одним списком в порядке, который хранит контроллер, у каждой ручка (владелец, 2026-10-28: «блоки Models тоже менять местами»), пока порядка нет — "
     "сначала аккаунты, потом машины; negative: чтение старше сохранения старый порядок не возвращает; ключ пропавшей машины ничего не рисует, не названные — за названными; "
     "пустая колонка — не список"),
    ("models_cards_saved_through_their_door",
     '',
     r"""await (async () => { const timers = []; const [b, log] = board({ res: { ok: true, order: [], rev: 2, topology: { marker: 7 } } });
       b.sources.read({ layout: { serverOrder: ["cloud:gone", "node:box", "cloud:sub"], serverOrderRev: 1 } });
       const said = await b.saveOrder("models", ["cloud:sub", "node:box", "cloud:or"]);
       const [off, refused] = board({ fail: true }); off.win.setTimeout = (fn) => timers.push(fn);
       const none = await off.saveOrder("models", ["cloud:or", "cloud:sub", "node:box"]);
       return [log.calls, log.applied, said.rev, none, refused.notes, off.pending, timers.length]; })()""",
     '[[["/api/topology/server-order",{"order":["cloud:gone","cloud:sub","node:box","cloud:or"]}]],[{"marker":7}],2,null,["controller is down"],true,1]',
     "новый порядок карточек Models — дверью порядка карточек, ответ рисует доску; карточка, которой нет в колонке, держит своё место, не названная — в конце; "
     "negative: отказ сказан вслух, а доска будет нарисована заново, из того, что хранит контроллер"),
    ("an_empty_column_keeps_its_head_and_says_so_in_its_body",
     'st.setTopology({ proxies: [], cloudAccounts: [], pools: [], routers: [{ id: "router:default", outputs: [] }], nodes: [] });',
     r"""(() => { const [b] = board(); return [b.clientsHtml(), b.poolsHtml(), b.modelsHtml()].map((h) => {
       const cut = h.indexOf('<div class="pb-col-body"'), said = /data-t="pb-no-(?:clients|pools|models)"/;
       return [h.indexOf('<div class="pb-col-head">') === 0, said.test(h.slice(cut)), said.test(h.slice(0, cut))]; }); })()""",
     '[[true,true,false],[true,true,false],[true,true,false]]',
     "a column with nothing in it keeps its head and says it is empty inside its body: the note scrolls with the rest and the head is the same as with cards; negative: no note in a head"),
    ("a_carried_card_is_carried_along_its_column",
     '',
     r"""(() => { const [b] = board(); const root = "BOX";
       b.mount({ dataset: {}, addEventListener() {}, querySelector: (s) => (s === "[data-pb-root]" ? root : null) });
       const column = { closest: (s) => (s === "[data-pb-scroll]" ? "COLUMN" : null) }, loose = { closest: () => null };
       return [b.carry.sway, b.cardCarry.sway, b.carry.scroller(column), b.cardCarry.scroller(column), b.carry.scroller(loose), b.carry.scroller(undefined), m.PoolBoard.SWAY]; })()""",
     '[10,10,"COLUMN","COLUMN","BOX","BOX",10]',
     "the board's carriers (a pool's steps, the cards of a column) are told to sway ten pixels to the sides and no more — a column cuts what stands out of it — and "
     "their scroller is the column the list stands in; negative: a list that is in no column (or none given) falls back to the board's box, as before 1.3.548"),
    ("a_column_scrolling_draws_the_cables_once_a_frame",
     '',
     r"""await (async () => { const [b] = board(); const frames = []; let drawn = 0; b.win.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
       b.drawCables = () => { drawn += 1; }; const listeners = [];
       b.mount({ dataset: {}, addEventListener: (type, fn, opts) => listeners.push([type, fn, opts]), querySelector: () => null });
       const run = () => { while (frames.length) frames.shift()(); }; run(); const mounted = drawn;
       const scroll = listeners.find(([type]) => type === "scroll"); const column = { matches: (s) => s === "[data-pb-scroll]" };
       scroll[1]({ target: column }); scroll[1]({ target: column }); scroll[1]({ target: column }); const queued = frames.length; run(); const after = drawn - mounted;
       scroll[1]({ target: { matches: () => false } }); return [scroll[2], mounted, queued, after, frames.length]; })()""",
     '[{"capture":true,"passive":true},1,1,1,0]',
     "a column's scroll does not bubble, so the board listens for it on the way down (capture); the dots moved with it, so the cables are drawn again — "
     "once a frame, however many scroll events come; negative: a scroll of anything that is not a column (a list inside a card) draws nothing"),
    ("the_cable_leans_on_the_column_under_it",
     '',
     r"""(() => { const [b] = board(); const frames = []; b.win.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
       b.win.innerWidth = 1400; b.win.innerHeight = 800; b.win.scrollBy = (x, y) => { b.win.page = [x, y]; };
       const rect = (left, top, right, bottom) => ({ left, top, right, bottom });
       const mk = (key, r) => ({ dataset: { pbScroll: key }, scrollTop: 100, getBoundingClientRect: () => r });
       const cols = [mk("clients", rect(20, 70, 270, 800)), mk("sets", rect(330, 70, 610, 800)), mk("pools", rect(670, 70, 1030, 800)), mk("models", rect(1090, 70, 1450, 800))];
       const box = { scrollLeft: 0, scrollTop: 0, getBoundingClientRect: () => rect(0, 60, 1400, 800) };
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? box : null), querySelectorAll: (s) => (s === "[data-pb-scroll]" ? cols : []) };
       const over = (x, y) => { const d = { moved: true, pointer: { x, y } }; b.drag = d; b.lean(); return { column: d.column ? d.column.dataset.pbScroll : null, lean: d.lean }; };
       const low = over(800, 790), gutter = over(300, 790), top = over(800, 75);
       const d = { moved: true, pointer: { x: 800, y: 790 } }; b.drag = d; b.lean(); b.scrollStep(d);
       return [low, gutter, top, [cols.map((c) => c.scrollTop), box.scrollTop, box.scrollLeft, b.win.page || null]]; })()""",
     '[{"column":"pools","lean":{"x":0,"y":0.8214285714285714}},{"column":null,"lean":{"x":0,"y":0}},'
     '{"column":"pools","lean":{"x":0,"y":-0.9107142857142857}},[[100,100,115,100],0,0,null]]',
     "a cable in the hand that leans on the top or the bottom of the board scrolls the column the pointer is over — at its foot the pools column goes down by a "
     "step, the clients' and the board's box stay; negative: in the gutter between two columns nothing leans up or down, and the window is not asked to scroll while "
     "the column can"),
    ("redraw_keeps_the_search_field",
     '',
     '''(() => { const [b] = board(); b.picking = { accountId: "or", query: "tw" }; const el = { innerHTML: "" };
       const field = { value: "tw", focus() { this.focused = (this.focused || 0) + 1; }, setSelectionRange(a, z) { this.sel = [a, z]; } };
       b.doc.activeElement = { matches: (s) => s === "[data-pb-pick-query]", selectionStart: 1, selectionEnd: 2 };
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : s === "[data-pb-picker] [data-pb-pick-query]" ? field : null) };
       b.redraw(); const kept = [field.focused, field.sel, el.innerHTML.includes('value="tw"')];
       b.doc.activeElement = null; field.focused = 0; b.redraw(); return [kept, field.focused]; })()''',
     '[[1,[1,2],true],0]',
     "показание, пришедшее при наборе в поиске, перерисовывает доску, а поле остаётся в фокусе и с кареткой на месте; negative: "
     "поле не в фокусе — фокус ему не навязан"),
    ("models_machine",
     '',
     '(() => { const [b] = board(); const card = () => part(b.modelsHtml(), \'data-pb-machine="box"\'); const shut = card(); b.expanded.add("m:box"); const open = card();'
     ' const cell = (h, id) => item(h, \'<div class="pb-model\', `data-pb-key="out:${id}"`);'
     ' return [keys(shut, "out:"), shut.includes(fill(en.pbMoreCells, { n: "2" })), keys(open, "out:"), cell(shut, "srv:22008").includes("pb-use none"),'
     ' shut.includes(\'data-t-state="failed"\') && shut.includes(\'class="pb-led bad"\'),'
     ' (() => { const c = cell(shut, "srv:22008"); const at = (x) => c.indexOf(x); return at(\'<span class="pb-model-name" title="Coder">Coder</span>\') > 0 && at(\'<span class="pb-cell-port">:22008</span>\') > at("Coder</span>") && at(\'<span class="pb-led" role="img"\') > at("pb-cell-port"); })(),'
     ' cell(shut, "srv:22011").includes(en.pbInNoPool), shut.includes(\'data-t="pb-machine-cells">1 running · 2 stopped · 1 failed</span>\'), open.includes("1 running · 2 stopped · 1 failed")]; })()',
     '[["srv:22008","srv:22011"],true,["srv:22008","srv:22009","srv:22010","srv:22011"],false,true,true,true,true,true]',
     "машина: работающая и упавшая ячейки на виду, две остановленные без строк сложены; открыта — все; в шапке — сколько ячеек в каком состоянии, "
     "ВСЕ четыре (в том числе сложенные); ячейка из пула про пулы молчит (1.3.534: они в полосе), а ячейка вне пулов говорит «ни в одном»"),
    # ── a model of a machine's entry (1.3.506): called by its name, no port of its own ──
    ("machine_models_on_the_card",
     'const T = TOPO(); T.routers[0].outputs.unshift({ id: "mm:a1", upstreamType: "machine", upstreamHost: "10.0.0.5", upstreamPort: 8092,'
     ' upstreamModel: "gemma", hostId: "box", label: "gemma", jobs: ["llm", "asr"] });'
     ' T.nodes[0].entryModels = [{ id: "gemma", state: "starting", copies: [{ port: 22008 }, { port: 22009 }] }];'
     ' T.pools[1].steps.push({ id: "r2", kind: "output", output: "mm:a1", enabled: true }); st.setTopology(T);',
     '(() => { const [b] = board(); const card = part(b.modelsHtml(), \'data-pb-machine="box"\'); const mm = item(card, \'<div class="pb-model\', \'data-pb-key="out:mm:a1"\');'
     ' const row = st.topology.pools[1].steps[2]; const target = b.targetHtml(row);'
     ' const hint = b.targets().find((x) => x.key === "out:mm:a1");'
     ' return [keys(card, "out:")[0], mm.includes(\'<span class="pb-model-name" title="gemma">gemma</span><span class="pb-copies"\'), mm.includes("×2"), mm.includes(":8092"),'
     ' mm.includes(\'data-t-state="starting"\'), b.rowName(row), target.includes("<small>🖥 Box</small>"), [hint.label, hint.hint],'
     ' mm.includes(\'<span class="pb-model-mark" aria-hidden="true" title="\' + en.jobLlm + ", " + en.jobAsr + \'">💬</span>\')]; })()',
     '["mm:a1",true,true,false,true,"gemma",true,["gemma","🖥 Box"],true]',
     "модель входа машины на карточке машины — первой, по имени, без порта (порт входа у всех моделей машины один), с числом "
     "копий, со знаком работы (из того, что она сама говорит на выходе) и словом скаута о ней; в строке пула, в её цели и в списке мест — имя модели и машина, без порта"),
    # ── step 3 (1.3.655): a machine with an entry stands by its models; its cells by port only where a row names one ──
    ("machine_stands_by_its_models",
     'const T = TOPO(); const mm = (id, name) => ({ id, upstreamType: "machine", upstreamHost: "10.0.0.5", upstreamPort: 8092, upstreamModel: name, hostId: "box", label: name });'
     ' T.routers[0].outputs.unshift(mm("mm:a1", "gemma"), mm("mm:b2", "big"), mm("mm:c3", "small"));'
     ' T.routers[0].outputs.push({ id: "srv:22030", upstreamType: "llama", upstreamHost: "10.0.0.9", upstreamPort: 22030, label: "Lone :22030" });'
     ' T.nodes[0].entryModels = [{ id: "gemma", state: "running", copies: [{ port: 22008, state: "running" }, { port: 22009, state: "stopped" }] },'
     ' { id: "big", state: "stopped", copies: [{ port: 22010, state: "stopped" }] }, { id: "small", state: "stopped", copies: [{ port: 22011, state: "stopped" }] }];'
     ' st.setTopology(T);',
     '''(() => { const [b] = board(); const html = b.modelsHtml(); const box = part(html, 'data-pb-machine="box"'), lone = part(html, 'data-pb-machine="10.0.0.9"');
       b.expanded.add("m:box"); const open = part(b.modelsHtml(), 'data-pb-machine="box"');
       return [keys(box, "out:"), box.includes(fill(en.pbMoreModels, { n: "2" })), box.includes(fill(en.pbMoreCells, { n: "2" })), keys(open, "out:"),
         keys(lone, "out:"), b.targets().filter((x) => x.key.startsWith("out:")).map((x) => x.key), b.output("srv:22010")?.out?.id || null,
         box.includes('data-t="pb-machine-cells">2 running · 2 stopped</span>')]; })()''',
     '[["mm:a1","srv:22008"],true,false,["mm:a1","mm:b2","mm:c3","srv:22008"],["srv:22030"],'
     '["out:mm:a1","out:mm:b2","out:mm:c3","out:srv:22008","out:srv:22030"],"srv:22010",true]',
     "шаг 3 (1.3.655): машина, чей вход называет модели, стоит в колонке моделями, по именам; её ячейка по порту — только та, на "
     "которую ещё ведёт строка пула (:22008), остальные :22009–:22011 — копии моделей и в колонке не стоят; две остановленные "
     "модели сложены под «+ 2 остановленные модели»; в выборе для строки — то же; negative: машина без входа стоит ячейками, как "
     "раньше; ячейку, ушедшую из колонки, строка и история находят по-прежнему"),
    # ── the account itself is set up on the main board (the owner, 2026-10-12) ──
    ("account_card_sets_nothing_up",
     'globalThis.__issues = { or: "<div class=\\"cloud-api-issues\\">tripped</div>" };',
     '''(() => { const [b, log] = board(); const card = (id) => part(b.modelsHtml(), `data-pb-account="${id}"`);
       const sub = card("sub"), or = card("or");
       return [["data-pb-details", "data-pb-account-edit", "data-pool-resets", "pb-src-tools", "[spend", "[limits", "[costs", "⚙", "⋯"].filter((x) => sub.includes(x) || or.includes(x)),
         or.includes("tripped") && !sub.includes("tripped"), sub.includes(en.cloudConnected), log.calls.length]; })()''',
     '[[],true,true,0]',
     "карточка аккаунта в Маршрутизации его не настраивает (2026-10-12): ни ⚙, ни «↺ сбросы», ни ⋯ с расходом — это на главной доске; "
     "сбой эндпоинта сказан на карточке; negative: для этого Маршрутизация ничего не просит у контроллера"),
    ("account_buttons",
     'globalThis.__refreshed = []; globalThis.__stubReturns["usage-stats.refreshUsageReading"] = (kind, id) => { globalThis.__refreshed.push([kind, id]); return true; };',
     '''await (async () => { const [b, log] = board(); const click = (attrs) => b.click({ target: node(attrs), stopPropagation() {} });
       const quiet = [await click({ "data-pool-resets": "sub" }), await click({ "data-usage-refresh": "sub" }), await click({ "data-or-limits-refresh": "or" }),
         await click({ "data-api-costs-refresh": "api" }), await click({ "data-pb-account-edit": "sub" }), await click({ "data-pb-details": "sub" })];
       await click({ "data-api-retry": "or:chat" });
       return [quiet, globalThis.__refreshed, log.calls]; })()''',
     '[[null,null,null,null,null,null],[],[["/api/cloud-api-health/retry",{"key":"or:chat"}]]]',
     "«Retry» сбоя снимает его у контроллера; negative: ни ↺, ни ⟳, ни ⚙, ни ⋯ в Маршрутизации ничего не делают — подписку "
     "настраивают на главной доске (2026-10-12)"),
    # ── the cables ──
    ("draw_cables",
     '',
     r"""(() => { const [b] = board(); const { svg } = rigged(b);
       const rest = b.drawCables(); const atRest = [rest, svg.innerHTML.includes("<g "), b.drops];
       b.trace = { key: "client:23001", pinned: true }; const n = b.drawCables();
       const gs = svg.innerHTML.match(/<g [^>]*>/g) || [], cls = svg.innerHTML.match(/class="pb-cable[^"]*"/g) || [];
       b.trace = { key: "pool:eco", pinned: true }; b.drawCables(); const eco = b.drops;
       b.trace = { key: "client:23001", pinned: false }; const hovered = b.drawCables();
       return [atRest, n, gs, cls, eco, hovered]; })()""",
     json.dumps([[0, False, []], 5,
                 ['<g data-pb-cable="call" data-port="23001" data-pb-cable-key="client:23001/std">',
                  '<g data-pb-cable="row" data-pool="std" data-row="sub" data-pb-cable-key="row:std/sub">',
                  '<g data-pb-cable="row" data-pool="std" data-row="r1" data-pb-cable-key="row:std/r1">',
                  '<g data-pb-cable="call" data-port="23001" data-pb-cable-key="client:23001/live:srv:22008">',
                  '<g data-pb-cable="direct" data-pb-cable-key="direct:live:srv:22008">'],
                 ['class="pb-cable"', 'class="pb-cable-hit"', 'class="pb-cable"', 'class="pb-cable-hit"', 'class="pb-cable lit"', 'class="pb-cable"', 'class="pb-cable"'],
                 [{"what": "row:eco/sub", "from": True, "to": False}], 0]),
     "в покое канатов нет (владелец, 2026-10-27: канаты — только когда тянем, когда выбран блок или когда бегут запросы); закреплён клиент — его канаты: к пулу, "
     "который он звал за три дня, и строки этого пула к моделям, к строке «Напрямую» модели, которую он звал без пула, и от неё к модели; у канатов строк — широкий "
     "двойник для щелчка (их режут), у каната клиента и «Напрямую» — нет: резать нечего; канат служащей строки горит; defect-class: канат к модели, которой нет на "
     "экране, назван в drops, а не пропал молча; negative: строка к пропавшей ячейке — ни каната, ни drops; наведение без щелчка канатов не рисует"),
    # ── the drops on the cables that carry a request now (1.3.549; the owner, 2026-10-14: "keep how an active connection is shown — in Routing too") ──
    ("cable_html_by_what_the_monitor_says",
     '',
     r"""(() => { const d = (flow, lit = false) => m.PoolBoard.cableHtml({ x: 0, y: 0 }, { x: 100, y: 50 }, 'data-pb-cable="row"', lit, "t", flow, 1000000);
       const cls = (h) => h.match(/class="[^"]*"/g); const lit = d("active");
       return [cls(d("")), cls(d("", true)), cls(d("recent")), cls(lit), lit.endsWith("</path></g>"),
         lit.includes('animation-duration:380ms;animation-delay:-220ms"'), d("active").includes(' d="M 0 0 C 50 0, 50 50, 100 50"'), cls(d("", false))]; })()""",
     json.dumps([['class="pb-cable-hit"', 'class="pb-cable"'], ['class="pb-cable-hit"', 'class="pb-cable lit"'], ['class="pb-cable-hit"', 'class="pb-cable lit"'],
                 ['class="pb-cable-hit"', 'class="pb-cable lit"', 'class="cable-flow-stop"', 'class="cable-flow-stop"', 'class="cable-flow-stop"', 'class="cable-flow-stop"',
                  'class="cable-flow fwd"', 'class="cable-flow back"'], True, True, True, ['class="pb-cable-hit"', 'class="pb-cable"']]),
     "канат по тому, что говорит монитор: «active» — горит и несёт капли: пара (вперёд и назад) последней в своей группе, на той же линии, с градиентом между концами каната "
     "(четыре его остановки), круг в 380 мс, задержка из общих часов: 1000000 по модулю 380 = 220; «recent» — горит, без капель; ни то ни другое — как раньше; "
     "служащая строка горит и без монитора; negative: ни у одного нет ничего лишнего — широкий двойник для щелчка один, линия одна"),
    ("draw_cables_runs_drops_along_the_way_of_a_request",
     '',
     r"""(() => { const look = (agents) => { const [b] = board({ agents: () => agents }); const { svg, dots } = rigged(b); b.drawCables();
         return [(svg.innerHTML.match(/class="(?:pb-cable|cable-flow(?= ))[^"]*"/g) || []).filter((c) => c !== 'class="pb-cable-hit"'),
           Object.keys(dots).filter((k) => dots[k].classes.has("flowing")).length]; };
       return [look(RUN({ cloudPoolId: "std", poolStepId: "sub" })), look(SAW({ cloudPoolId: "std", poolStepId: "sub", finishedAt: 998 })),
         look(RUN({ cloudPoolId: "std", poolStepId: "sub", phase: "queued" })), look(RUN({ cloudPoolId: "ghost", poolStepId: "sub" })),
         look(RUN({ cloudPoolId: "std", poolStepId: "sub" }, 23999)), look(RUN({ cloudPoolId: "live:srv:22008", poolStepId: "r1" })), look(undefined)]; })()""",
     json.dumps([
         [['class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"', 'class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"'], 4],
         [['class="pb-cable lit"', 'class="pb-cable lit"'], 0],
         [[], 0],
         [[], 0],
         [['class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"'], 2],
         [['class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"', 'class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"'], 4],
         [[], 0]]),
     "запрос Hermes идёт через пул Standart строкой sub — появляются, горят и несут капли два его каната: клиента к пулу и строки к модели; два конца каждого — четыре "
     "точки — в кольце; запрос закончился 2 с назад — горят те же два, без капель и без колец; запрос к модели напрямую — канат клиента к строке «Напрямую» и её к модели; "
     "negative: запрос в очереди не идёт — канатов нет вовсе (служащая строка без запроса каната не рисует: в покое канатов нет); пул, которого на доске нет, — "
     "ничего; запрос порта, который не клиент входа, — только строка (две точки); монитор молчит — ничего"),
    ("the_cables_are_named_for_their_story",
     '',
     r"""(() => { const keys = (agents) => { CableFlow.reset(); const [b] = board({ agents: () => agents }); rigged(b); b.drawCables(); return [...CableFlow.seen.keys()].sort(); };
       return [keys(RUN({ cloudPoolId: "std", poolStepId: "sub" })), keys(RUN({ cloudPoolId: "live:srv:22008", poolStepId: "r1" })), keys(undefined)]; })()""",
     '[["pb:client:23001/std","pb:row:std/sub"],["pb:client:23001/live:srv:22008","pb:direct:live:srv:22008"],[]]',
     "у каждого каната, что несёт запрос, свой ключ — по нему капли помнят, что кабель нёс: клиента к пулу или к строке «Напрямую», строки к модели, у каждого с "
     "приставкой доски (pb:), чтобы их не спутать с канатами главной доски (main:); negative: монитор молчит — ключей нет"),
    ("draw_cables_lets_the_drops_of_a_request_that_ended_go_down",
     '',
     r"""(() => { let t = 1000000, rows = RUN({ cloudPoolId: "std", poolStepId: "sub" }); const [b] = board({ agents: () => rows, now: () => t }); const { svg } = rigged(b);
       const way = () => (svg.innerHTML.match(/class="cable-flow(?= )[^"]*"/g) || []).map((c) => c.split(" ").slice(2).join(" ").replace('"', ""));
       const count = (list, word) => list.filter((c) => c === word).length;
       b.drawCables(); const first = way(); t += 100; rows = SAW({ cloudPoolId: "std", poolStepId: "sub", finishedAt: 998 }); b.drawCables(); const second = way();
       const lastLine = svg.innerHTML.lastIndexOf('class="pb-cable lit"') < svg.innerHTML.indexOf("fading");
       t += 400; b.drawCables(); const third = way(); t += 600; b.drawCables(); const fourth = way(); t += 5000; rows = SAW({ cloudPoolId: "std", poolStepId: "sub", finishedAt: 990 }); b.drawCables();
       return [[count(first, "rising"), first.length], [count(second, "fading"), second.length, lastLine], [count(third, "fading"), third.length], fourth.length, way().length]; })()""",
     '[[4,4],[4,4,true],[4,4],0,0]',
     "канаты, по которым только что шёл запрос, не гасят капли разом: в перерисовке, где запрос уже закончился, каждый из двух каналов несёт пару капель-призраков (fading), "
     "после линий каналов, а не между ними; через 500 мс они всё ещё идут вниз; negative: через 900 мс с первой такой перерисовки их нет, и когда запрос закончился давно, — тоже"),
    ("paint_flow_draws_when_the_picture_changes",
     '',
     r"""(() => { let rows; const [b] = board({ agents: () => rows }); const first = b.paintFlow(); rigged(b); let drawn = 0; const draw = b.drawCables.bind(b); b.drawCables = () => { drawn += 1; return draw(); };
       const a = b.paintFlow(), same = b.paintFlow(); rows = RUN({ cloudPoolId: "std", poolStepId: "sub" }); const changed = b.paintFlow(), again = b.paintFlow();
       rows = SAW({ cloudPoolId: "std", poolStepId: "sub", finishedAt: 998 }); const settled = b.paintFlow(); rows = undefined; const gone = b.paintFlow(); b.root = null; const none = b.paintFlow();
       return [first, a, same, changed, again, settled, gone, none, drawn]; })()""",
     '[false,true,false,true,false,true,true,false,4]',
     "кабели рисуются заново, только когда монитор говорит другое, чем при прошлой отрисовке: первый раз (доска ещё не рисовала), запрос пошёл, запрос закончился (канаты лишь горят), "
     "монитор успокоился; negative: то же самое показание — ничего не рисуется; доска не нарисована (нет корня) — ничего"),
    ("a_dot_loses_its_ring_when_the_request_ends",
     '',
     r"""(() => { let rows = RUN({ cloudPoolId: "std", poolStepId: "sub" }); const [b] = board({ agents: () => rows }); const { dots } = rigged(b); const ringed = () => Object.keys(dots).filter((k) => dots[k].classes.has("flowing")).length;
       b.drawCables(); const during = ringed(); rows = SAW({ cloudPoolId: "std", poolStepId: "sub", finishedAt: 998 }); b.drawCables(); const after = ringed();
       rows = RUN({ cloudPoolId: "std", poolStepId: "r1" }); b.drawCables(); const sub = '[data-pb-pool="std"] [data-pb-row="sub"] [data-pb-out]', r1 = '[data-pb-pool="std"] [data-pb-row="r1"] [data-pb-out]';
       return [during, after, ringed(), dots[sub].classes.has("flowing"), dots[r1].classes.has("flowing")]; })()""",
     '[4,0,4,false,true]',
     "пока идёт запрос, четыре точки двух канатов в кольце; запрос кончился — кольца сняты у всех (у одной и той же доски, что нарисовала их): канаты горят, а кольцо — у тех, по кому идёт сейчас; "
     "negative: пошёл другой запрос того же клиента — точки его строки (r1) в кольце, а точка строки sub, что служила прежнему, — уже нет"),
    ("flow_now_reads_the_boards_pools",
     '',
     r"""(() => { const [b] = board({ agents: () => RUN({ cloudPoolId: "std", poolStepId: "r1" }) }); const f = b.flowNow(); const none = board()[0].flowNow();
       const straight = board({ agents: () => RUN({ cloudPoolId: "live:srv:22008", poolStepId: "r1" }) })[0].flowNow();
       return [[...f.active].sort(), [...f.recent], f.signature, [...f.direct], [...none.active], none.signature, [...straight.active].sort(), [...straight.direct]]; })()""",
     json.dumps([["client:23001/std", "row:std/r1"], [], "client:23001/std|row:std/r1~", [], [], "~",
                 ["client:23001/live:srv:22008", "direct:live:srv:22008"], [["live:srv:22008", [{"port": 23001, "active": True}]]]]),
     "доска читает монитор по своим пулам: запрос клиента через пул — канат клиента к пулу и строка; запрос к модели напрямую — канат клиента к строке «Напрямую», её канат "
     "к модели и сама строка «Напрямую» (пул из одной строки, live:…) с клиентом, чей запрос идёт; negative: без монитора — ничего и подпись «~»"),
    ("a_column_that_is_not_at_its_top_is_scrolled",
     '',
     r"""(() => { const [b] = board(); const mk = (top) => { const names = new Set(); return { scrollTop: top, names, classList: { toggle: (n, f) => { if (f) names.add(n); else names.delete(n); } } }; };
       const col = mk(40); b.scrolled(col); const down = [...col.names]; col.scrollTop = 0; b.scrolled(col); const top = [...col.names]; b.scrolled(); return [down, top]; })()""",
     '[["scrolled"],[]]',
     "колонка, прокрученная вниз, получает метку scrolled — её голова, что стоит наверху, тогда показывает полосу (columns.css); "
     "negative: вернулась к началу — метка снята; вызов без колонки (его делали до 1.3.549) ничего не трогает и не падает"),
    ("the_board_marks_the_column_it_hears",
     '',
     r"""await (async () => { const [b] = board(); const listeners = []; b.mount({ dataset: {}, addEventListener: (type, fn) => listeners.push([type, fn]), querySelector: () => null });
       const hear = listeners.find(([type]) => type === "scroll")[1]; const names = new Set();
       const column = { scrollTop: 60, matches: (s) => s === "[data-pb-scroll]", classList: { toggle: (n, f) => { if (f) names.add(n); else names.delete(n); } } };
       hear({ target: column }); const down = [...names]; column.scrollTop = 0; hear({ target: column }); const top = [...names];
       const card = { scrollTop: 60, matches: () => false, classList: { toggle: () => names.add("WRONG") } }; hear({ target: card }); return [down, top, [...names]]; })()""",
     '[["scrolled"],[],[]]',
     "доска слышит прокрутку колонки и ставит ей метку scrolled, пока она не у начала; negative: у начала метка снята; список внутри карточки — не колонка и метки не получает"),
    ("the_columns_drawn_anew_are_scrolled_at_once",
     '',
     r"""(() => { const mk = (key) => { const names = new Set(); return { dataset: { pbScroll: key }, scrollTop: 0, names, classList: { add: (n) => names.add(n) } }; };
       const cols = ["clients", "pools", "models"].map(mk); const root = { querySelectorAll: (s) => (s === "[data-pb-scroll]" ? cols : []) };
       m.PoolBoard.scrollColumns(root, { pools: 120, models: 15 }); return cols.map((c) => [c.scrollTop, [...c.names]]); })()""",
     '[[0,[]],[120,["scrolled"]],[15,["scrolled"]]]',
     "колонка, нарисованная заново, встаёт на своё место и сразу несёт метку scrolled — не со следующим событием прокрутки, иначе голова на кадр оставалась бы без полосы; "
     "negative: колонка, о которой ничего не сказано, остаётся как есть"),
    ("the_board_listens_for_the_monitor",
     '',
     r"""(() => { globalThis.__seen.clear(); const [b] = board(); let painted = 0; b.paintFlow = () => { painted += 1; }; const c = { dataset: {}, addEventListener() {}, querySelector: () => null };
       b.mount(c); const told = globalThis.__seen.size; [...globalThis.__seen].forEach((f) => f()); b.mount(c); return [told, painted, globalThis.__seen.size]; })()""",
     '[1,1,1]',
     "доска один раз просит, чтобы ей говорили, что монитор прочитан, — и тогда рисует капли; negative: страница рисует доску заново много раз, а слушатель всё один"),
    # ── what the operator does ──
    ("drop_row_on_models",
     '',
     'await (async () => { let target = null; const [b, log] = board({ at: () => target });'
     ' const pool = node({ "data-pb-pool": "std" }); const row = node({ "data-pb-row": "r2" }, pool); const dot = node({ "data-pb-out": "row" }, row, { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });'
     ' const drop = async (el) => { target = el; b.press({ target: dot, button: 0, pointerId: 2, preventDefault() {} }); b.follow({ pointerId: 2, clientX: 30, clientY: 1 });'
     ' await b.release({ type: "pointerup", pointerId: 2, clientX: 30, clientY: 1 }); };'
     ' await drop(node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-astra", "data-name": "gpt-astra" }));'
     ' await drop(node({ "data-pb-model": "", "data-output": "srv:22009", "data-name": "Gemma" }));'
     ' return log.calls; })()',
     '[["/api/pools/connect-row",{"poolId":"std","rowId":"r2","target":{"accountId":"sub","model":"gpt-astra"},"nameAfter":"gpt-astra"}],'
     '["/api/pools/connect-row",{"poolId":"std","rowId":"r2","target":{"output":"srv:22009"},"nameAfter":"Gemma"}]]',
     "канат строки к модели подписки — аккаунт и модель; к ячейке — её выход; имя модели — с ним (пул с именем доски возьмёт его, 1.3.503)"),
    ("grab_rows_carry_new_cables",
     '',
     r"""await (async () => { let target = null; const [b, log] = board({ at: () => target }); const box = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) };
       const grab = (attrs, kind, parent) => { const g = node({ "data-pb-grab": "", ...attrs }, parent); const dot = node({ "data-pb-out": kind }, g, box);
         g.querySelector = (sel) => (sel === "[data-pb-out]" ? dot : null); return [g, node({}, g)]; };
       const [poolGrab, poolLabel] = grab({ "data-t": "pb-add-row" }, "new-row", node({ "data-pb-pool": "std" }));
       const carry = async (from, over, id) => { target = over; b.press({ target: from, button: 0, pointerId: id, preventDefault() {} }); const held = b.busy;
         b.follow({ pointerId: id, clientX: 30, clientY: 1 }); await b.release({ type: "pointerup", pointerId: id, clientX: 30, clientY: 1 }); return held; };
       const held = await carry(poolLabel, node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-astra", "data-name": "gpt-astra" }), 1);
       await carry(poolGrab, node({ "data-pb-model": "", "data-output": "srv:22009", "data-name": "Gemma" }), 2);
       await carry(poolLabel, node({}, node({ "data-pb-pool": "eco" })), 3); await carry(poolLabel, node({}), 4); await carry(poolLabel, null, 5);
       await b.click({ target: poolLabel, stopPropagation() {} });
       return [held, log.calls, b.busy]; })()""",
     '[true,[["/api/pools/add-row",{"poolId":"std","target":{"accountId":"sub","model":"gpt-astra"},"nameAfter":"gpt-astra"}],'
     '["/api/pools/add-row",{"poolId":"std","target":{"output":"srv:22009"},"nameAfter":"Gemma"}]],false]',
     "«＋ строка» пула тянет новый канат с любой точки строки, не только с точки (владелец, 2026-10-12): строка пула над моделью — одна запись, новая строка "
     "сразу с канатом (/api/pools/add-row с целью): к модели подписки — аккаунт и модель, к ячейке — её выход; negative: отпущено над пулом, мимо модели или ни над "
     "чем — ничего не послано, открытой строки не осталось; щелчок по «＋» строке ничего не шлёт (он открывает список мест — пин chooser_*)"),
    ("drop_nowhere_or_cancelled",
     '',
     r"""await (async () => { let under = node({}); const [b, log] = board({ at: () => under });
       const dot = node({ "data-pb-out": "row" }, node({ "data-pb-row": "r2" }, node({ "data-pb-pool": "std" })), { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });
       b.press({ target: dot, button: 0, pointerId: 3, preventDefault() {} }); b.follow({ pointerId: 3, clientX: 30, clientY: 1 }); await b.release({ type: "pointerup", pointerId: 3, clientX: 30, clientY: 1 });
       under = node({ "data-pb-model": "", "data-output": "srv:22009", "data-name": "Gemma" });
       b.press({ target: dot, button: 0, pointerId: 4, preventDefault() {} }); b.follow({ pointerId: 4, clientX: 30, clientY: 1 }); await b.release({ type: "pointercancel", pointerId: 4, clientX: 30, clientY: 1 });
       b.press({ target: dot, button: 0, pointerId: 5, preventDefault() {} }); b.follow({ pointerId: 5, clientX: 30, clientY: 1 }); b.onKey({ key: "Escape" }); const afterEsc = b.busy;
       b.press({ target: dot, button: 2, pointerId: 6, preventDefault() {} }); return [log.calls.length, afterEsc, b.busy]; })()""",
     '[0,false,false]',
     "negative: канат строки, отпущенный мимо модели, отменённый (даже над моделью) или брошенный по Esc, ничего не шлёт; правая кнопка каната не начинает"),
    ("cut_cables_after_a_question",
     '',
     r"""await (async () => { const [b, log] = board({ answers: [false, true] }); const click = (el) => b.click({ target: el, stopPropagation() {} });
       await click(node({ "data-pb-cable": "row", "data-pool": "std", "data-row": "sub" })); await click(node({ "data-pb-cable": "row", "data-pool": "std", "data-row": "r1" }));
       await click(node({ "data-pb-cable": "call", "data-port": "23001" })); await click(node({ "data-pb-cable": "direct" }));
       await click(node({ "data-pb-cable": "row", "data-pool": "std", "data-row": "nope" }));
       return [log.asks.map((a) => [a[0], a[1] === en.pbCutTitle, a[2]]), log.calls]; })()""",
     '[[["Take the cable of row 1 of Standart away from gpt-sol · ChatGPT? The row stays, not connected.",true,true],'
     '["Take the cable of row 2 of Standart away from Coder :22008? The row stays, not connected.",true,true]],'
     '[["/api/pools/connect-row",{"poolId":"std","rowId":"r1","target":null}]]]',
     "щелчок по канату строки — вопрос с обоими концами, потом строка снята с модели; negative: отказ в вопросе — ничего; канат клиента и канат «Напрямую» — то, "
     "что звали, а не связь, которую провели: резать нечего, вопроса нет (1.3.675); строки, которой нет, — ничего"),
    ("pool_kinds",
     'st.topology.pools[0].kind = { jobs: ["llm"], inputs: ["text", "image"] }; st.topology.pools[1].kind = { mixed: true };'
     ' st.topology.pools.push({ id: "ears", name: "Ears", steps: [], kind: { jobs: ["asr"], languages: ["ru"] } },'
     ' { id: "quiet", name: "Quiet", steps: [], kind: null });',
     '(() => { const [b] = board(); const pools = b.poolsHtml(); const head = (id) => part(pools, `data-pb-pool="${id}"`, "</header>");'
     ' return [head("std").includes(`<span class="pb-kind" data-t="pb-kind" data-t-state="known" title="${esc(en.jobLlm + " · " + en.pbKindPictures)}">💬🖼</span>`),'
     ' head("eco").includes(`<span class="pb-kind mixed" data-t="pb-kind" data-t-state="mixed" title="${esc(en.pbKindMixed)}">⚠</span>`),'
     ' head("ears").includes(`title="${esc(en.jobAsr + " · ru")}">🎧</span>`), head("quiet").includes("pb-kind"),'
     ' m.PoolBoard.kindHtml(undefined), m.PoolBoard.kindHtml({ jobs: ["nonsense"] })]; })()',
     '[true,true,true,false,"",""]',
     "у пула — что делает модель (1.3.502): значки работ и 🖼 у чата с картинками, работа, картинки и "
     "языки — в подсказке; ⚠ — строки пула делают разную работу; negative: вид неизвестен или работы нет в словаре — ничего"),
    ("probe_model_choice",
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 }; st.topology.clientProbes = [{ path: "/v1/chat/completions", paid: false }];'
     ' Object.assign(st.topology.proxies[0], { models: ["Standart", "Voice"] }); Object.assign(st.topology.proxies[1], { models: ["Standart"] });',
     r"""await (async () => { const [b, log] = board(); b.trace = { key: "client:23001", pinned: true }; const hermes = () => part(b.dockHtml(), 'data-pb-client="23001"', "</aside>");
       const card = node({ "data-pb-client": "23001" }); const asked = (h) => (h.match(/path=([^"]*)" data-t="pb-client-ask" data-t-id="model"/) || [])[1];
       const first = hermes(); await b.change({ target: node({ "data-pb-probe-model": "" }, card, { value: "Voice" }) }); const chosen = hermes();
       await b.click({ target: node({ "data-pb-tests": "" }, card), stopPropagation() {} }); const opened = hermes();
       await b.click({ target: node({ "data-pb-probe": "/v1/chat/completions" }, card), stopPropagation() {} });
       b.trace = { key: "client:23002", pinned: true }; const bot = part(b.dockHtml(), 'data-pb-client="23002"', "</aside>");
       return [(first.match(/<option[^>]*>[^<]*<\/option>/g) || []), (first.match(/data-t-id="model"/g) || []).length, asked(first),
         chosen.includes('<option value="Voice" selected>'), asked(chosen), log.calls[0][1].model, (opened.match(/data-pb-probe-model/g) || []).length,
         bot.includes("pb-probe-model"), asked(bot)]; })()""",
     '[["<option value=\\"Standart\\" selected>Standart</option>","<option value=\\"Voice\\">Voice</option>"],1,"%2Fv1%2Fmodels%2FStandart",true,'
     '"%2Fv1%2Fmodels%2FVoice","Voice",1,false,"%2Fv1%2Fmodels%2FStandart"]',
     "клиент видит две модели — выбор модели стоит в полосе рядом со ссылками GET (1.3.675: клиент видит все модели, ссылка на каждую была бы столбцом в двадцать): "
     "ссылка на одну модель — на выбранную, проверки шлют её же; выбор виден и при свёрнутых проверках, внутри проверок второго нет; "
     "negative: у клиента с одной моделью выбора нет — ссылка на неё одну"),
    ("pool_copy",
     '',
     'await (async () => { const seen = async (over) => { const [b, log] = board(over);'
     ' const field = { did: [], focus() { this.did.push("focus"); }, select() { this.did.push("select"); } };'
     ' b.root = { querySelector: (s) => (s === \'[data-pb-pool="std-copy"] [data-pb-pool-name]\' ? field : null) };'
     ' const pool = node({ "data-pb-pool": "std" }); await b.click({ target: node({ "data-pb-pool-copy": "" }, pool), stopPropagation() {} });'
     ' return [log.calls, log.asks.length, log.removed, field.did, log.notes]; };'
     ' const [b] = board(); const head = part(b.poolsHtml(), \'data-pb-pool="std"\', "</header>");'
     ' return [await seen({ res: { ok: true, pool: { id: "std-copy" }, topology: { marker: 2 } } }), await seen({ fail: true }), head.includes(\'data-t="pb-pool-copy"\')]; })()',
     '[[[["/api/pools/copy",{"id":"std"}]],0,[],["focus","select"],[]],[[["/api/pools/copy",{"id":"std"}]],0,[],[],["controller is down"]],true]',
     "⧉ на голове пула копирует его сразу, без вопроса: копия ничего не ломает и снимается ✕; её имя выбрано в поле — печатать поверх; "
     "negative: отказ контроллера — сказано вслух, поле не трогаем"),
    ("buttons",
     '',
     'await (async () => { const [b, log] = board({ answers: [true, false], res: { ok: true, pool: { id: "pool" }, topology: { marker: 2 } } });'
     ' const field = { did: [], focus() { this.did.push("focus"); }, select() { this.did.push("select"); } };'
     ' b.root = { querySelector: (s) => (s === \'[data-pb-pool="pool"] [data-pb-pool-name]\' ? field : null) };'
     ' const pool = node({ "data-pb-pool": "std" }); const row = node({ "data-pb-row": "r2" }, pool); const click = (el) => b.click({ target: el, stopPropagation() {} });'
     ' await click(node({ "data-pb-add-pool": "" })); await click(node({ "data-pb-row-remove": "" }, row));'
     ' await click(node({ "data-pb-row-remove": "" }, row)); await click(node({ "data-pb-pool-delete": "" }, pool)); await click(node({}));'
     ' return [log.calls, log.asks.map((a) => a[0]), log.removed, field.did]; })()',
     '[[["/api/pools/create",{}],["/api/pools/remove-step",{"poolId":"std","stepId":"r2"}]],'
     '["Remove row 3 “not connected” from Standart?","Remove row 3 “not connected” from Standart?"],["std"],["focus","select"]]',
     "＋ пул (имя нового пула выбрано в его поле — печатать поверх), удаление строки после вопроса, удаление пула — дверью "
     "карточек пулов; negative: отказ — строка остаётся, щелчок мимо — ничего"),
    ("rename_pool",
     '',
     'await (async () => { const [b, log] = board(); const pool = node({ "data-pb-pool": "std" }); const field = (value) => node({ "data-pb-pool-name": "" }, pool, { value });'
     ' const named = field(" Standart Plus "); await b.change({ target: named }); const same = field("Standart"); await b.change({ target: same });'
     ' const empty = field("  "); await b.change({ target: empty }); return [log.saved, empty.value]; })()',
     '[[{"id":"std","name":"Standart Plus"}],"Standart"]',
     "новое имя пула сохраняется дверью карточек; negative: то же имя — ничего; пустое — поле возвращает прежнее"),
    ("toggles_redraw_the_board_only",
     '',
     'await (async () => { const [b, log] = board(); const el = { innerHTML: "" }; b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) };'
     ' b.trace = { key: "pool:std", pinned: true };'
     ' await b.click({ target: node({ "data-pb-more": "m:box" }), stopPropagation() {} }); const more = b.expanded.has("m:box") && el.innerHTML.includes(en.pbFewer);'
     ' await b.click({ target: node({ "data-pb-history": "" }, node({ "data-pb-pool": "std" })), stopPropagation() {} });'
     ' return [more, b.history.has("std"), el.innerHTML.includes(\'data-t="pb-history"\'), log.calls.length, log.applied.length]; })()',
     '[true,true,true,0,0]',
     "«ещё» и «Switch history» открываются на месте: доска перерисована своя (история — в полосе пула, пока путь на нём), контроллеру ничего не послано"),
    ("redraw_waits_while_held",
     '',
     '(() => { const [b] = board(); const el = { innerHTML: "old" }; b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) };'
     ' globalThis.__drag.active = true; b.redraw(); const held = [el.innerHTML, b.pending, globalThis.__drag.deferred];'
     ' globalThis.__drag.active = false; b.settled(); return [held, el.innerHTML.startsWith("<div class=\\"pb-cols\\""), b.pending]; })()',
     '[["old",true,true],true,false]',
     "пока держат ручку уровня, доска не перерисовывается — перерисовка ждёт отпускания и случается после него"),
    ("client_links",
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 }; st.topology.proxies[1].models = [];',
     r'''(() => { const [b] = board(); const head = b.clientsHtml(); const dock = (board, key) => { board.trace = { key, pinned: true }; return board.dockHtml(); };
       const links = (h) => (h.match(/<a class="pb-ask"[^>]*>[^<]*<\/a>/g) || []);
       const hermes = dock(b, "client:23001"), bot = dock(b, "client:23002");
       st.topology.entry = { url: "", port: null }; const [b2] = board(); const off = b2.clientsHtml() + dock(b2, "client:23001");
       return [head.includes(`<span class="pb-client-url" title="${esc(en.consumerEntryTitle + ": https://caravan-api.example.org/v1")}">caravan-api.example.org/v1</span>`),
         head.includes(`data-pb-copy-url data-t="pb-client-copy" title="${esc(en.consumerCopyEntry)}"`), (head.match(/pb-client-url/g) || []).length, links(hermes),
         links(bot).length, links(hermes).every((a) => a.includes(`title="${esc(en.pbClientAskTitle)}"`)), part(head, '<article class="pb-card pb-client').includes("pb-ask"),
         off.includes("pb-entry"), off.includes("pb-ask")]; })()''',
     r'''[true,true,1,["<a class=\"pb-ask\" href=\"/api/consumers/ask?port=23001&amp;path=%2Fv1%2Fmodels\" data-t=\"pb-client-ask\" data-t-id=\"list\" title=\"Opens the answer this client gets here, asked with its own key\">/v1/models</a>",
       "<a class=\"pb-ask\" href=\"/api/consumers/ask?port=23001&amp;path=%2Fv1%2Fmodels%2FStandart\" data-t=\"pb-client-ask\" data-t-id=\"model\" title=\"Opens the answer this client gets here, asked with its own key\">/v1/models/Standart</a>"],1,true,false,false,false]''',
     "адрес, который дан клиентам, стоит ОДИН раз под заголовком колонки, без схемы (колонка узкая, 1.3.500; подсказка и ⧉ — адрес целиком) и с ⧉ (1.3.532: "
     "раньше он стоял на всех карточках); два вопроса GET клиента (список моделей и его модель) стоят в полосе под доской, пока клиент выбран, и каждый "
     "открывает ответ входа его ключу через контроллер (2026-10-12); у клиента, которому нечего звать, — только список; negative: на карточке клиента ссылок нет; входа нет — нет и адреса, и ссылок"),
    ("client_copy",
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 };',
     'await (async () => { const [b, log] = board(); const copied = []; let ok = true; b.copy = async (x) => { copied.push(x); return ok; };'
     ' const click = () => b.click({ target: node({ "data-pb-copy-url": "" }, node({ "data-pb-client": "23001" })), stopPropagation() {} });'
     ' const first = await click(); ok = false; const second = await click(); st.topology.entry = {}; b.html(st.topology); const third = await click();'
     ' return [first, second, third, copied, log.notes, log.calls.length]; })()',
     '[true,false,null,["https://caravan-api.example.org/v1","https://caravan-api.example.org/v1"],["Address copied","https://caravan-api.example.org/v1"],0]',
     "⧉ кладёт адрес клиента в буфер и говорит об этом; буфер недоступен — адрес в тосте, скопировать руками; "
     "negative: входа нет — нечего копировать; контроллеру ничего не послано"),
    ("client_probes",
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 }; st.topology.clientProbes = [{ path: "/v1/chat/completions", paid: false },'
     ' { path: "/v1/images/generations", paid: true }];',
     r'''await (async () => { const [b, log] = board(); const el = { innerHTML: "" }; b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) };
       const strip = (h, port) => part(h, `class="pb-dock-client" data-pb-client="${port}"`, "</aside>");
       b.trace = { key: "client:23001", pinned: true }; const shut = strip(b.dockHtml(), "23001"); const card = node({ "data-pb-client": "23001" });
       await b.click({ target: node({ "data-pb-tests": "" }, card), stopPropagation() {} }); const hermes = strip(el.innerHTML, "23001");
       const buttons = hermes.match(/<button class="pb-probe-btn"[^>]*>[^<]*<\/button>/g) || [];
       b.trace = { key: "client:23002", pinned: true }; const bot = strip(b.dockHtml(), "23002");
       b.trace = { key: "client:23001", pinned: true }; await b.click({ target: node({ "data-pb-tests": "" }, card), stopPropagation() {} });
       const again = strip(el.innerHTML, "23001"); delete st.topology.clientProbes; const [b2] = board(); b2.tests.add("23001"); b2.trace = { key: "client:23001", pinned: true };
       const none = strip(b2.dockHtml(), "23001"); const cardOnly = part(b.clientsHtml(), '<article class="pb-card pb-client');
       return [shut.includes(`<button class="pb-tests-head" type="button" data-pb-tests aria-expanded="false" data-t="pb-client-tests">${esc(en.pbProbeRow)}</button>`),
         shut.includes("pb-probe-btn"), hermes.includes(`<button class="pb-tests-head open" type="button" data-pb-tests aria-expanded="true" data-t="pb-client-tests">`),
         buttons.map((x) => x.replace(/ title="[^"]*"/, "")), buttons[0].includes(`title="${esc(en.pbProbeTitle)}"`), buttons[1].includes(`title="${esc(en.pbProbePaidTitle)}"`),
         bot.includes("pb-probe-btn"), again.includes("pb-probe-btn"), none.includes("pb-tests-head") || none.includes("pb-client-probes"),
         cardOnly.includes("pb-tests-head"), log.calls.length]; })()''',
     r'''[true,false,true,["<button class=\"pb-probe-btn\" type=\"button\" data-pb-probe=\"/v1/chat/completions\" data-t=\"pb-client-probe\" data-t-id=\"/v1/chat/completions\">chat/completions ▶</button>",
       "<button class=\"pb-probe-btn\" type=\"button\" data-pb-probe=\"/v1/images/generations\" data-t=\"pb-client-probe\" data-t-id=\"/v1/images/generations\">images/generations ▶</button>"],true,true,false,false,false,false,0]''',
     "в полосе под доской — проверки POST «как клиент» из таблицы контроллера (topology.clientProbes), свёрнутые под одной строкой «Test as the client», "
     "пока её не откроют: щелчок открывает их у этого клиента, второй — сворачивает, доска перерисована своя, контроллеру ничего не послано; "
     "подсказка говорит, что тратится лимит, а у картинки — что она может стоить денег; negative: у другого клиента они свёрнуты; контроллер не дал таблицу — "
     "ни строки, ни кнопок; на карточке клиента проверок нет (1.3.532)"),
    ("client_probe_runs",
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 }; st.topology.clientProbes = [{ path: "/v1/chat/completions", paid: false },'
     ' { path: "/v1/images/generations", paid: true }, { path: "/v1/audio/speech", paid: false }];',
     'await (async () => { const answer = { ok: true, request: { method: "POST", path: "/v1/chat/completions", model: "Standart", sent: "{\\"model\\": \\"Standart\\"}" },'
     ' status: 200, contentType: "application/json", ms: 1234, bytes: 512, text: "{\\"model\\":\\"gpt-6.1-sol\\",\\"choices\\":[]}", cut: false };'
     ' const [b, log] = board({ res: answer, answers: [false, true] }); const card = node({ "data-pb-client": "23001" });'
     ' const click = (attrs) => b.click({ target: node(attrs, card), stopPropagation() {} });'
     ' const pending = click({ "data-pb-probe": "/v1/chat/completions" }); const busy = b.probeHtml(); await pending; const done = b.probeHtml();'
     ' await click({ "data-pb-probe": "/v1/images/generations" }); const refusedPaid = [log.asks.length, log.calls.length];'
     ' await click({ "data-pb-probe": "/v1/images/generations" }); const sentPaid = log.calls.length;'
     ' b.key({ key: "Escape", preventDefault() {}, target: node({}) }); const closed = b.probe;'
     ' return [log.calls[0], busy.includes(\'data-t-state="busy"\') && busy.includes(esc(en.pbProbeWaiting)),'
     ' done.includes(\'<code>POST https://caravan-api.example.org/v1/chat/completions</code>\'), done.includes(\'data-t-state="done"\'),'
     ' done.includes(\'<p class="pb-probe-status ok" data-t="pb-probe-status"><b>200</b> · application/json · 1.2 s · 512 B</p>\'),'
     ' done.includes(esc(JSON.stringify({ model: "gpt-6.1-sol", choices: [] }, null, 2))), done.includes(`<h4>${esc(en.pbProbeSent)}</h4>`),'
     ' refusedPaid, log.asks[0][0] === fill(en.pbProbePaidAsk, { client: "Hermes" }), sentPaid, closed]; })()',
     '[["/api/consumers/probe",{"port":23001,"path":"/v1/chat/completions","model":"Standart"}],true,true,true,true,true,true,[1,1],true,2,null]',
     "проверка «как клиент» — один запрос контроллеру с портом, путём и именем модели клиента; окно ждёт, потом показывает адрес, что ушло, "
     "код, тип, время, размер и тело ответа, разложенное по строкам; картинка — только после «да»; negative: «нет» — ничего не послано; Esc закрывает окно"),
    ("client_probe_failed_and_audio",
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 }; st.topology.clientProbes = [{ path: "/v1/audio/speech", paid: false }];',
     'await (async () => { const [b] = board({ fail: true }); const card = node({ "data-pb-client": "23001" });'
     ' await b.click({ target: node({ "data-pb-probe": "/v1/audio/speech" }, card), stopPropagation() {} }); const failed = b.probeHtml();'
     ' b.probe = { port: 23001, label: "Hermes", path: "/v1/audio/speech", model: "Standart", result: { request: { sent: "{}" }, status: 200,'
     ' contentType: "audio/mpeg", ms: 80, bytes: 2048, audio: "SUQz" } }; const audio = b.probeHtml();'
     ' b.probe = { port: 23001, path: "/v1/audio/speech", busy: true }; const late = b.runProbe("23002", "/v1/audio/speech");'
     ' b.probe = null; const landed = await late;'
     ' return [failed.includes(\'data-t-state="failed"\') && failed.includes(esc(fill(en.pbProbeFailed, { error: "controller is down" }))),'
     ' audio.includes(\'<audio controls src="data:audio/mpeg;base64,SUQz"></audio>\') && audio.includes("80 ms · 2 KB"), landed, b.probe]; })()',
     '[true,true,null,null]',
     "контроллер не смог спросить — окно говорит почему; речь — плеер прямо в окне; negative: ответ на проверку, окно которой закрыли, "
     "никуда не ложится"),
    ("client_misses",
     'Object.assign(st.topology.proxies[0], { misses: { items: [{ method: "POST", path: "/api/show", status: 404, count: 5, last: 1791800000, reason: "entry:invalid-url" },'
     ' { method: "", path: "/v1/models", status: 401, count: 1, last: 1791700000, reason: "" }], more: 2 } });'
     ' Object.assign(st.topology.proxies[1], { misses: { items: [], more: 0 } });',
     r'''(() => { const [b] = board(); const dock = (key) => { b.trace = { key, pinned: true }; return b.dockHtml(); }; const h = b.clientsHtml();
       const hermes = dock("client:23001"), bot = dock("client:23002");
       const badge = (port) => (part(h, `data-pb-client="${port}"`).match(/<span class="pb-miss-badge"[^>]*>([^<]*)<\/span>/) || [])[1] || null;
       return [hermes.includes(`<span class="pb-misses-head">⚠ ${esc(en.pbClientMisses)}</span>`),
         (hermes.match(/<li class="pb-miss"[^>]*>.*?<\/li>/g) || []).map((x) => x.replace(/<[^>]+>/g, "")),
         hermes.includes(`title="${esc(fill(en.pbClientMissTitle, { reason: "entry:invalid-url" }))}"`),
         hermes.includes(`<li class="pb-miss-more">${esc(fill(en.pbClientMissesMore, { n: "2" }))}</li>`), bot.includes("pb-client-misses"),
         [m.PoolBoard.size(900), m.PoolBoard.size(5000), m.PoolBoard.took(830), m.PoolBoard.took(2340), m.PoolBoard.when(0), m.PoolBoard.pretty("[1]", "text/plain")],
         part(h, 'data-pb-client="23001"').includes('class="pb-client-misses"'), [badge(23001), badge(23002)]]; })()''',
     r'''[true,["POST /api/show 404 ×5 · Oct 12, 10:13 AM","/v1/models 401 ×1 · Oct 11, 06:26 AM"],true,true,false,["900 B","4.9 KB","830 ms","2.3 s","—","[1]"],false,["⚠ 6+",null]]''',
     "в полосе под доской — ошибки клиента за 30 дней: метод и путь, код, сколько раз и когда последний, причина — в подсказке, остальные — числом; "
     "запись без метода — только путь; на карточке клиента остаётся значок «⚠ N» с числом раз (6+ — не меньше: часть строк обрезана); "
     "negative: ошибок нет — списка нет и значка нет; списка на самой карточке нет (1.3.532)"),
    ("client_card_is_compact",
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 }; st.topology.clientProbes = [{ path: "/v1/chat/completions", paid: false }];'
     ' Object.assign(st.topology.proxies[0], { misses: { items: [{ method: "POST", path: "/api/show", status: 404, count: 5, last: 1791800000, reason: "" }], more: 0 } });',
     r'''(() => { const [b] = board(); const h = b.clientsHtml(); const card = (port) => item(h, '<article class="pb-card pb-client', `data-pb-client="${port}"`);
       const text = (x) => x.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(); const cards = h.slice(h.indexOf("<article"));
       return [text(card(23001)), text(card(23002)), ["pb-client-links", "pb-ask", "pb-tests-head", 'class="pb-client-misses"', "pb-probe-btn", "pb-client-url"].filter((c) => cards.includes(c))]; })()''',
     r'''["⠿ Hermes 🔑 …a1b2 Sees all 5 ⚠ 5 ＋ Block","⠿ Bot 🔑 …c3d4 Sees 4 of 5 ⊘ Econom ＋ Block",[]]''',
     "карточка клиента — имя, хвост ключа, сколько моделей он видит, значок ошибок с числом раз и что ему запрещено, с «＋ Запретить»: ни адреса, ни ссылок, ни проверок, "
     "ни списка ошибок (1.3.532); negative: у клиента без ошибок значка нет, у клиента, которому ничего не запрещено, чипов нет"),
    ("dock_empty_and_aims",
     '',
     r'''(() => { const [b] = board(); const empty = b.dockHtml(); b.trace = { key: "client:99999", pinned: true }; const gone = b.dockHtml(); const aim = (k) => b.dock.constructor.aim(k);
       return [empty.includes('data-t-state="empty"'), / inert[ >]/.test(empty), empty.replace(/<aside[^>]*>/, "").replace("</aside>", "") === "", gone === empty,
         ["client:23001", "direct:live:srv:22008", "pool:std", "row:std/sub", "model:acc:sub/gpt-sol", "set:std-set", "setpool:std-set/std", "nonsense", "", "client:"].map(aim)]; })()''',
     r'''[true,true,true,true,[{"kind":"client","id":"23001"},{"kind":"direct","id":"live:srv:22008"},{"kind":"pool","id":"std"},{"kind":"pool","id":"std"},{"kind":"model","id":"acc:sub/gpt-sol"},null,null,null,null,null]]''',
     "полоса под доской, когда ничего не выбрано и ни на что не наведено, пуста: ни подсказки, ни слов (владелец, 2026-10-14: «не отображай нижнюю полосу, когда ни на что не наведено или не выбрано»), "
     "и она inert; на карточке, которой уже нет на доске (клиент 99999), — то же самое, не догадка; "
     "ключ пути → о чём полоса: клиент — клиент, строка «Напрямую» — её модель по пулу из одной строки, строка пула — пул, модель — модель; "
     "negative: ключи набора (наборов нет с 1.3.675), непонятный или пустой ключ — ничего"),
    ("dock_client_strip",
     '',
     r'''(() => { const [b] = board(); const text = (x) => x.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
       const words = (x) => x.replace(en.topologyClientsSection, "{clients}").replace(en.pbPoolsSection, "{pools}").replace(en.topologyModelsLabel, "{models}");
       b.trace = { key: "client:23001", pinned: false }; const pointed = b.dockHtml(); b.trace = { key: "client:23001", pinned: true }; const pinned = b.dockHtml();
       const route = (h) => (h.match(/<div><dt[^>]*>[^<]*<\/dt><dd[^>]*>[^<]*<\/dd><\/div>/g) || []).map((x) => words(text(x)));
       return [text(part(pinned, '<b class="pb-dock-name"', "</b>")), text(part(pinned, '<span class="pb-dock-sub"', "</span></span>")), route(pinned),
         pointed.includes(esc(en.pbDockPin)), pointed.includes(esc(en.pbDockPinned)), pinned.includes(esc(en.pbDockPinned)), pinned.includes('data-t-state="client"')]; })()''',
     r'''["Hermes","🔑 …a1b2",["{clients} Hermes","{pools} Standart","{models} Coder, gpt-sol"],true,false,true,true]''',
     "полоса клиента: его имя, хвост ключа и путь по колонкам — клиенты, пулы, модели: то, что он звал за три дня (пул Standart и его модели, Coder и напрямую), "
     "а не всё, что ему открыто; под курсором внизу «щёлкните, чтобы закрепить», закреплённая — «закреплено, ещё раз или Esc отпускают»"),
    ("dock_route_says_none",
     '',
     r'''(() => { const [b] = board(); const text = (x) => x.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(); b.trace = { key: "client:23002", pinned: true };
       const words = (x) => x.replace(en.topologyClientsSection, "{clients}").replace(en.pbPoolsSection, "{pools}").replace(en.topologyModelsLabel, "{models}");
       return (b.dockHtml().match(/<div><dt[^>]*>[^<]*<\/dt><dd[^>]*>[^<]*<\/dd><\/div>/g) || []).map((x) => words(text(x))); })()''',
     '["{clients} Bot","{pools} —","{models} —"]',
     "уровень пути без имён в полосе говорит «—»: клиент, который ничего не звал за три дня, — только он сам, а у пулов и моделей прочерк, не пустое место "
     "(отсутствие названо вслух)"),
    ("dock_route_names_the_account_of_a_twin",
     'st.topology.pools.push({ id: "twin", name: "Twin", steps: [{ id: "a", kind: "account", accountId: "sub", model: "x", enabled: true },'
     ' { id: "b", kind: "account", accountId: "or", model: "x", enabled: true }, { id: "c", kind: "account", accountId: "sub", model: "y", enabled: true }] });',
     r'''(() => { const [b] = board(); const names = (key) => b.routeOf(key).map((l) => l.names); return [names("pool:twin"), names("pool:eco"), names("client:23002")]; })()''',
     r'''[[[],["Twin"],["x · ☁ ChatGPT","x · ☁ OpenRouter","y"]],[[],["Econom"],["gpt-luna","srv:22999"]],[["Bot"],[],[]]]''',
     "путь в именах по колонкам: модель, которую дают два аккаунта, названа с аккаунтом (иначе «x, x»), прочие — просто именем; пул, который никто не звал, — "
     "пустой уровень клиентов; клиент, который ничего не звал, — только он сам, остальные уровни пусты (не выдумка); модель, которой нет на доске (srv:22999), названа тем, что в строке"),
    ("dock_painting",
     '',
     r'''(() => { const [b] = board(); const writes = []; const el = { set innerHTML(v) { writes.push(v); }, get innerHTML() { return writes[writes.length - 1] || ""; }, attrs: {},
         setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; } };
       const seen = () => [writes.length, el.attrs["data-t-state"], "inert" in el.attrs];
       b.root = { querySelector: (s) => (s === "[data-pb-dock]" ? el : null) }; b.dockDrawn = "";
       b.paintDock(); const idle = seen(); b.trace = { key: "pool:std", pinned: false }; b.paintDock(); const lit = seen();
       b.paintDock(); const same = writes.length; b.trace = { key: "pool:std", pinned: true }; b.paintDock(); const pinned = seen();
       b.trace = null; b.paintDock(); return [idle, lit, same, pinned, seen()]; })()''',
     r'''[[0,"empty",true],[1,"pool",true],1,[2,"pool",false],[2,"empty",true]]''',
     "полоса рисуется заново на месте, когда путь сменился, и её состояние идёт за путём: пустая и inert, наведённая — inert, закреплённая — нет; "
     "когда путь погас, она только прячется и хранит, что говорила (пока указатель переходит с карточки на карточку, она не мигает пустой); "
     "negative: та же полоса второй раз не переписывается (поле в ней не теряет фокус, карточка не мигает), а полоса, нарисованная доской, на которую не навели, — тоже"),
    ("dock_follows_the_pointer",
     '',
     r'''(() => { const [b] = board(); const writes = []; const el = { set innerHTML(v) { writes.push(v); }, get innerHTML() { return writes[writes.length - 1] || ""; }, attrs: {},
         setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; } };
       const rootEl = { classList: { toggle() {} }, querySelectorAll: () => [] };
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? rootEl : s === "[data-pb-dock]" ? el : null) }; b.dockDrawn = "";
       b.hover({ target: node({}, node({ "data-pb-node": "client:23001" })) }); const onClient = [writes.length, el.attrs["data-t-state"], el.innerHTML.includes("Hermes")];
       b.hover({ target: node({}, node({ "data-pb-node": "pool:std" })) }); const onPool = [writes.length, el.attrs["data-t-state"], el.innerHTML.includes("Standart")];
       b.pin({ target: node({}, node({ "data-pb-node": "pool:eco" })) }); const pinned = [writes.length, el.innerHTML.includes("Econom"), el.innerHTML.includes(esc(en.pbDockPinned))];
       b.hover({ target: node({}, node({ "data-pb-node": "client:23001" })) }); const stillPinned = writes.length;
       b.trace = null; b.lightPath(); return [onClient, onPool, pinned, stillPinned, el.attrs["data-t-state"], el.innerHTML.includes("Econom")]; })()''',
     '[[1,"client",true],[2,"pool",true],[3,true,true],3,"empty",true]',
     "полоса идёт за указателем: навели на клиента — его полоса, на пул — полоса пула, щелчок закрепил — полоса пула «закреплено»; negative: пока закреплено, "
     "наведение на другого клиента полосу не меняет; путь погас — полоса спрятана («empty») и ничего нового не рисовала"),
    ("dock_takes_the_pointer_only_when_pinned",
     '',
     r'''(() => { const [b] = board(); const aside = (h) => h.match(/<aside[^>]*>/)[0]; const inert = (h) => / inert[ >]/.test(aside(h));
       const idle = b.dockHtml(); b.trace = { key: "pool:std", pinned: false }; const pointed = b.dockHtml(); b.trace = { key: "pool:std", pinned: true }; const pinned = b.dockHtml();
       b.trace = null; const after = b.dockHtml(); b.trace = { key: "pool:std", pinned: false }; b.hover({ target: node({}, node({ "data-pb-dock": "" })) }); const onStrip = b.trace;
       b.trace = { key: "pool:std", pinned: false }; b.hover({ target: node({}) });
       return [inert(idle), inert(pointed), inert(pinned), inert(after), after.includes("Standart"), aside(after).includes('data-t-state="empty"'), onStrip, b.trace]; })()''',
     '[true,true,false,true,true,true,null,null]',
     "полоса принимает указатель, только когда карточка закреплена: пока на неё лишь навели или ничего нет — она inert, указатель идёт сквозь неё, "
     "и карточка под ней по-прежнему наводится и закрепляется; пустая полоса хранит то, что говорила (чтобы не мигать), но спрятана и inert; "
     "negative: наведение на пустое место путь гасит, как раньше, и у полосы в этом голоса нет — событие, пришедшее с неё, пути не держит"),
    ("pin_lets_go_on_an_empty_place",
     '',
     r'''(() => { const [b] = board(); const cols = node({ "data-pb-cols": "" }), root = node({ "data-pb-root": "" });
       const outcome = (target) => { b.trace = { key: "pool:std", pinned: true }; const done = b.pin({ target }); return [done, b.trace && b.trace.key]; };
       const gap = outcome(node({}, cols)), ground = outcome(root), strip = outcome(node({}, node({ "data-pb-dock": "" }, root))),
         chooser = outcome(node({}, node({ "data-pb-chooser": "" }, root))), elsewhere = outcome(node({}));
       b.trace = null; const idle = [b.pin({ target: node({}, cols) }), b.trace];
       b.trace = { key: "pool:std", pinned: false }; const pointed = [b.pin({ target: node({}, cols) }), b.trace && b.trace.pinned];
       return [gap, ground, strip, chooser, elsewhere, idle, pointed]; })()''',
     r'''[[true,null],[true,null],[false,"pool:std"],[false,"pool:std"],[false,"pool:std"],[false,null],[false,false]]''',
     "щелчок в пустое место доски (щель между карточками, голова колонки, поле, что держит колонки) отпускает закреплённый путь (владелец, 2026-10-14: «кликну между блоками — "
     "а фокус не уходит»); negative: щелчок в полосе, в окне выбора и вообще не на доске путь держит; когда ничего не закреплено — щелчок в пустое ничего не делает, "
     "а наведённый (не закреплённый) путь он не закрепляет"),
    ("pin_follows_a_field_of_another_card",
     '',
     r'''(() => { const [b] = board(); const card = (k) => node({ "data-pb-node": k });
       const after = (target) => { b.trace = { key: "pool:std", pinned: true }; const done = b.pin({ target }); return [done, b.trace && b.trace.key]; };
       const other = after(node({}, card("pool:eco"), { tagName: "INPUT" })), select = after(node({}, card("pool:eco"), { tagName: "SELECT" })),
         own = after(node({}, card("pool:std"), { tagName: "INPUT" })), button = after(node({}, card("pool:eco"), { tagName: "BUTTON" })),
         inStrip = after(node({}, node({ "data-pb-dock": "" }), { tagName: "INPUT" })), body = after(node({}, card("pool:eco")));
       b.trace = null; const idle = [b.pin({ target: node({}, card("pool:eco"), { tagName: "INPUT" }) }), b.trace];
       return [other, select, own, button, inStrip, body, idle]; })()''',
     r'''[[true,null],[true,null],[false,"pool:std"],[false,"pool:std"],[false,"pool:std"],[true,"pool:eco"],[false,null]]''',
     "щелчок в текстовом поле или списке другой карточки отпускает закреплённый путь (поле берёт фокус клавиатуры, путь не должен остаться на старой карточке); щелчок по телу "
     "другой карточки закрепляет уже её; negative: поле самой закреплённой карточки, кнопка другой карточки и поле в полосе путь держат; ничего не закреплено — поле его не закрепляет"),
    ("pool_name_is_an_id",
     '',
     r'''(() => { const [b] = board(); const pool = b.poolHtml(st.topology.pools[0]);
       const head = (h) => h.slice(h.indexOf("<header"), h.indexOf("</header>"));
       return [/<span class="pb-pool-id" aria-hidden="true">id:<\/span>\s*<input class="pb-pool-name"/.test(pool), head(pool).indexOf("pb-card-grip") < head(pool).indexOf("pb-pool-id"),
         b.inner().includes("data-pb-set-name")]; })()''',
     '[true,true,false]',
     "на карточке пула слева от названия подпись «id:» (владелец, 2026-10-14: «на самом блоке пиши слева от названия id:»): имя пула есть идентификатор модели, который клиент "
     "пишет в поле model; подпись после ручки и прямо перед полем имени, для читалок экрана скрыта (поле имени говорит само); negative: поля имени набора больше нет нигде"),
    ("column_heads_say_id",
     '',
     r'''(() => { const [b] = board(); const head = (h) => (h.match(/<div class="pb-col-head"><span>([^<]*)<\/span>/) || [])[1];
       return [head(b.clientsHtml()) === esc(en.topologyClientsSection), head(b.poolsHtml()) === esc(en.pbPoolsSection),
         en.pbPoolsSection, en.topologyLlamaServersSection, head(b.modelsHtml()) === esc(en.topologyModelsLabel), "pbSetsSection" in en]; })()''',
     r'''[true,true,"ID (Pools)","Pools",true,false]''',
     "головы колонок Маршрутизации: клиенты, «ID (Pools)», модели — имя пула есть идентификатор модели, который клиент пишет в поле model (владелец, 2026-10-14); "
     "negative: общее слово «Pools» (карточка Маршрутизации на главной доске, счётчики) прежнее — заголовок колонки взял свой ключ, а не его; слова «Sets» больше нет (1.3.675)"),
    ("miss_badge_values",
     '',
     r'''[m.PoolBoard.missBadge({ misses: { items: [{ count: 5 }, { count: "2" }], more: 0 } }), m.PoolBoard.missBadge({ misses: { items: [{ count: 3 }], more: 4 } }),
       m.PoolBoard.missBadge({ misses: { items: [], more: 0 } }), m.PoolBoard.missBadge({}), m.PoolBoard.missBadge(null), m.PoolBoard.missBadge({ misses: { items: [{}] } })]''',
     '["7","3+","","","",""]',
     "значок ошибок на карточке клиента — сколько раз его отшили по строкам, что видит карточка; «+» — не меньше (часть строк обрезана); "
     "negative: нет строк, нет журнала, строка без числа — значка нет"),
    ("pool_settings_shut_then_open",
     '',
     '(() => { const [b] = board(); const dock = (id) => b.poolDetailsHtml(st.topology.pools.find((p) => p.id === id)); const shut = dock("std"); b.settings.add("std");'
     ' const open = dock("std"), other = dock("eco"), card = part(b.poolsHtml(), \'data-pb-pool="std"\');'
     ' return [shut.includes(`data-pb-settings aria-expanded="false" data-t="pb-settings">${esc(en.poolSettings)}</button>`), shut.includes("pb-settings-panel"),'
     ' open.includes(\'data-pb-settings aria-expanded="true"\'), open.includes(\'data-t="pb-settings-panel"\'),'
     ' open.includes(`data-pb-pool-window data-t="pb-pool-window" value="" placeholder="${esc(en.topologyCloudContextEmpty)}"`),'
     ' open.includes(`<span>${esc(en.topologyCloudContextLength)}</span>`), open.includes(`data-t="pb-pool-window-auto"><span>${esc(en.poolWindowAuto)}</span>`),'
     ' open.includes(`title="${esc(en.poolWindowHint)}"`) && open.includes(`title="${esc(en.poolWindowAutoHint)}"`), open.includes("pb-pool-window-stated"),'
     ' other.includes("pb-settings-panel"), card.includes("data-pb-settings"), card.includes("pb-settings-panel")]; })()',
     '[true,false,true,true,true,true,true,true,false,false,false,false]',
     "«Pool settings» пула — в его полосе, закрыты, пока их не откроют: поле окна (пустое — «не задано»), переключатель «наименьшее окно "
     "моделей», подсказки; negative: без слова контроллера о том, что пул называет, строки нет; другой пул не открывается; на карточке пула ни кнопки, ни настроек, даже открытых (1.3.533)"),
    ("pool_settings_show_what_is_kept",
     'Object.assign(st.topology.pools[0], { contextLength: 300000, contextAuto: true, window: 272000 });'
     ' Object.assign(st.topology.pools[1], { contextLength: "", window: null });',
     '(() => { const [b] = board(); b.settings.add("std"); b.settings.add("eco"); const dock = (id) => b.poolDetailsHtml(st.topology.pools.find((p) => p.id === id));'
     ' const std = dock("std"), eco = dock("eco");'
     ' return [std.includes(\'data-t="pb-pool-window" value="300000"\'), std.includes(\'data-t="pb-pool-window-auto" checked>\'),'
     ' std.includes(`data-t="pb-pool-window-stated" data-t-state="stated" title="272000">${esc(fill(en.pbPoolWindowStated, { window: "272K" }))}</p>`),'
     ' eco.includes(\'data-t="pb-pool-window" value=""\'), eco.includes(\'data-t="pb-pool-window-auto">\'),'
     ' eco.includes(`class="pb-stated none" data-t="pb-pool-window-stated" data-t-state="none">${esc(en.pbPoolWindowNone)}</p>`)]; })()',
     '[true,true,true,true,true,true]',
     "в настройках — то, что хранит контроллер: число, переключатель и что пул называет клиентам (272K, точное число в подсказке); "
     "negative: пул не называет окна — так и сказано, а не пустое место"),
    ("pool_settings_open_in_place",
     '',
     'await (async () => { const [b, log] = board(); const el = { innerHTML: "" }; b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) }; b.trace = { key: "pool:std", pinned: true };'
     ' const click = () => b.click({ target: node({ "data-pb-settings": "" }, node({ "data-pb-pool": "std" })), stopPropagation() {} });'
     ' await click(); const open = [b.settings.has("std"), el.innerHTML.includes(\'data-t="pb-settings-panel"\')];'
     ' await click(); return [open, b.settings.has("std"), el.innerHTML.includes("pb-settings-panel"), log.calls.length, log.applied.length]; })()',
     '[[true,true],false,false,0,0]',
     "«Pool settings» открываются и закрываются на месте (в полосе пула): доска перерисована своя, контроллеру ничего не послано"),
    ("pool_window_saved",
     'Object.assign(st.topology.pools[0], { contextLength: 300000, contextAuto: false });',
     'await (async () => { const [b, log] = board(); const saves = []; b.actions.save = async (p) => { saves.push([p.id, p.name, p.contextLength, p.contextAuto, p.steps.length]); return { ok: true }; };'
     ' const card = node({ "data-pb-pool": "std" }); const number = node({ "data-pb-pool-window": "" }, card, { value: "300000" });'
     ' const box = node({ "data-pb-pool-window-auto": "" }, card, { checked: false });'
     ' card.querySelector = (s) => (s === "[data-pb-pool-window]" ? number : s === "[data-pb-pool-window-auto]" ? box : null);'
     ' await b.change({ target: number }); number.value = " 128000 "; await b.change({ target: number }); number.value = "";'
     ' await b.change({ target: number }); box.checked = true; await b.change({ target: box });'
     ' const lone = node({ "data-pb-pool-window-auto": "" }, node({ "data-pb-pool": "eco" }), { checked: true }); await b.change({ target: lone });'
     ' await b.change({ target: node({ "data-pb-pool-window": "" }, node({ "data-pb-pool": "gone" }), { value: "5" }) });'
     ' return [saves, log.saved, log.notes]; })()',
     '[[["std","Standart","128000",false,3],["std","Standart","",false,3],["std","Standart","",true,3],["eco","Econom","",true,2]],[],[]]',
     "окно пула и переключатель сохраняются дверью карточек пулов вместе, как стоят в настройках; пусто — «не задано», не ноль; "
     "negative: то же число — ничего; пул, которого нет, — ничего; без второго поля берётся то, что хранит контроллер"),
    ("pool_window_refused",
     'Object.assign(st.topology.pools[0], { contextLength: 300000, contextAuto: false });',
     'await (async () => { const [b, log] = board(); b.actions.save = async () => { throw new Error("contextLength must be a positive number or empty"); };'
     ' const card = node({ "data-pb-pool": "std" }); const number = node({ "data-pb-pool-window": "" }, card, { value: "-5" });'
     ' const box = node({ "data-pb-pool-window-auto": "" }, card, { checked: true });'
     ' card.querySelector = (s) => (s === "[data-pb-pool-window]" ? number : s === "[data-pb-pool-window-auto]" ? box : null);'
     ' const got = await b.change({ target: number }); return [got, log.notes, number.value, box.checked]; })()',
     '[null,["contextLength must be a positive number or empty"],"300000",false]',
     "отказ контроллера: тост говорит почему, поля показывают то, что он хранит"),
    ("redraw_waits_while_typed",
     '',
     '(() => { const [b] = board(); const el = { innerHTML: "old" }; b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) };'
     ' const card = node({ "data-pb-pool": "std" }); const typed = [];'
     ' for (const attr of ["data-pb-pool-window", "data-pb-pool-name", "data-pb-pick-query"]) {'
     '  el.innerHTML = "old"; b.pending = false; b.doc.activeElement = node({ [attr]: "" }, card); b.redraw(); typed.push([attr, el.innerHTML === "old", b.pending]); }'
     ' b.doc.activeElement = node({ "data-pb-pool-window": "" }, card); el.innerHTML = "old"; b.pending = false; b.redraw(); b.settled(); const still = [el.innerHTML, b.pending];'
     ' b.doc.activeElement = null; b.settled(); return [typed, still, el.innerHTML.startsWith("<div class=\\"pb-cols\\""), b.pending]; })()',
     '[[["data-pb-pool-window",true,true],["data-pb-pool-name",true,true],["data-pb-pick-query",false,false]],["old",true],true,false]',
     "пока печатают окно или имя пула, доска не перерисовывается: перерисовка ждёт, пока поле отпустят, и случается после; "
     "negative: поле поиска модели перерисовке не мешает — его доска сохраняет сама"),
    ("row_names",
     '',
     '(() => { const [b] = board(); const [a, c, o] = st.topology.pools[0].steps; return [b.rowName(a), b.rowName(c), b.rowName(o), b.rowName(st.topology.pools[1].steps[1])]; })()',
     '["gpt-sol · ChatGPT","Coder :22008","not connected","srv:22999"]',
     "строка в вопросах и в истории — модель с аккаунтом, ячейка с портом, «без каната»; пропавший выход — его id"),
    # ── when a model is open (1.3.498): its ⏱ beside its name, a pool's row of a model closed now ──
    ("schedule_chip_on_each_model",
     'const NOW = Date.UTC(2026, 9, 12, 8, 0) / 1000; st.setTopology({ ...st.topology, modelSchedules: { zone: { name: "UTC", known: true, offsetMinutes: 0 }, now: NOW, models: { "acc:sub/gpt-sol": { enabled: true, windows: [], open: true, until: NOW + 3600, opensAt: null }, "out:srv:22008": { enabled: true, windows: [], open: false, until: null, opensAt: NOW + 11 * 3600 } } } });',
     '(() => { const [b] = board(); const h = b.html(st.topology);'
     ' const row = (key) => item(h, \'<div class="pb-model\', `data-pb-key="${key}"`);'
     ' const state = (key) => (row(key).match(/data-t="pb-model-schedule" data-t-id="[^"]*" data-t-state="([^"]*)"/) || [])[1];'
     ' return [state("acc:sub/gpt-sol"), state("out:srv:22008"), state("acc:sub/gpt-astra"),'
     ' /<span class="pb-model-head"><span class="pb-model-grab"[^>]*>⠿<\\/span><span class="pb-model-name"[^>]*><code>gpt-sol<\\/code><\\/span><span class="pb-chips"><span class="pb-chip"[^>]*>[^<]*<\\/span><button class="pb-sched open"/.test(row("acc:sub/gpt-sol"))]; })()',
     '["open","closed","none",true]',
     "⏱ у каждой модели правой колонки, среди меток справа от имени, после метки «switch…»: у модели аккаунта и у ячейки машины; без расписания — тихий ⏱; "
     "перед именем — ручка модели (1.3.503)"),
    ("row_of_a_closed_model_says_so",
     'const NOW = Date.UTC(2026, 9, 12, 8, 0) / 1000; st.setTopology({ ...st.topology, modelSchedules: { zone: { name: "UTC", known: true, offsetMinutes: 0 }, now: NOW, models: { "acc:sub/gpt-sol": { enabled: true, windows: [], open: true, until: NOW + 3600, opensAt: null }, "out:srv:22008": { enabled: true, windows: [], open: false, until: null, opensAt: NOW + 11 * 3600 } } } });',
     '(() => { const [b] = board(); const h = b.html(st.topology);'
     ' const r1 = item(h, \'<li class="pool-rung">\', \'data-t-id="std/r1"\'); const sub = item(h, \'<li class="pool-rung">\', \'data-t-id="std/sub"\');'
     ' return [r1.includes(\'data-t-state="closed"\'), r1.includes(">" + fill(en.pbSchedClosedUntil, { time: "19:00" }) + "<"),'
     ' r1.includes("pb-row serving"), sub.includes(\'data-t-state="stop"\')]; })()',
     '[true,true,false,true]',
     "строка ячейки, закрытой расписанием, говорит «закрыта до 19:00» — слово контроллера сейчас важнее последнего слова прокси «отвечает»; "
     "negative: строка модели, которая открыта, говорит своё, как раньше"),
    ("chip_opens_the_window_escape_closes",
     'const NOW = Date.UTC(2026, 9, 12, 8, 0) / 1000; st.setTopology({ ...st.topology, modelSchedules: { zone: { name: "UTC", known: true, offsetMinutes: 0 }, now: NOW, models: { "acc:sub/gpt-sol": { enabled: true, windows: [], open: true, until: NOW + 3600, opensAt: null }, "out:srv:22008": { enabled: true, windows: [], open: false, until: null, opensAt: NOW + 11 * 3600 } } } });',
     'await (async () => { const [b] = board(); await b.click({ target: node({ "data-ms-open": "acc:sub/gpt-sol", "data-ms-title": "gpt-sol" }), stopPropagation() {} });'
     ' const h = b.inner(); await b.click({ target: node({ "data-ms-add": "" }, node({ "data-ms": "" })), stopPropagation() {} });'
     ' const windows = b.schedule.form.windows.length; b.key({ key: "Escape", preventDefault() {}, target: node({}) });'
     ' return [h.includes(\'data-t="pb-schedule" data-t-id="acc:sub/gpt-sol"\'), windows, b.schedule.form]; })()',
     '[true,1,null]',
     "щелчок по ⏱ открывает окно этой модели поверх Маршрутизации, кнопки окна ведёт само окно, Escape закрывает его"),
    ("painting_holds_the_board",
     'const NOW = Date.UTC(2026, 9, 12, 8, 0) / 1000; st.setTopology({ ...st.topology, modelSchedules: { zone: { name: "UTC", known: true, offsetMinutes: 0 }, now: NOW, models: { "acc:sub/gpt-sol": { enabled: true, windows: [], open: true, until: NOW + 3600, opensAt: null }, "out:srv:22008": { enabled: true, windows: [], open: false, until: null, opensAt: NOW + 11 * 3600 } } } });',
     '(() => { const [b] = board(); const el = { innerHTML: "old" }; b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) };'
     ' b.schedule.open("acc:sub/gpt-sol", "gpt-sol"); el.innerHTML = "old"; b.pending = false;'
     ' b.schedule.painting = { open: true, mask: new Uint8Array(10080) }; b.redraw(); const held = [el.innerHTML, b.busy, b.pending];'
     ' b.schedule.release(); b.settled(); return [held, el.innerHTML.includes(\'data-t="pb-schedule"\'), b.pending]; })()',
     '[["old",true,true],true,false]',
     "пока указатель рисует часы, доска не перерисовывается; отпустил — окно нарисовано заново, отложенная перерисовка случилась"),
    # ── 1.3.503: where the cables go (the owner, 2026-10-12) ──
    ("click_is_not_a_cable",
     '',
     r"""await (async () => { const model = node({ "data-pb-model": "", "data-output": "srv:22009", "data-name": "Gemma" }); const [b, log] = board({ at: () => model });
       const dot = node({ "data-pb-out": "row" }, node({ "data-pb-row": "r2" }, node({ "data-pb-pool": "std" })), { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });
       const go = async (id, dx) => { b.press({ target: dot, button: 0, pointerId: id, clientX: 10, clientY: 10, preventDefault() {} });
         if (dx) b.follow({ pointerId: id, clientX: 10 + dx, clientY: 10 }); const moved = b.drag.moved;
         await b.release({ type: "pointerup", pointerId: id, clientX: 10 + dx, clientY: 10 }); return moved; };
       const moves = [await go(1, 0), await go(2, 3)]; const quiet = log.calls.length; moves.push(await go(3, 30)); return [moves, quiet, log.calls, b.busy]; })()""",
     '[[false,false,true],0,[["/api/pools/connect-row",{"poolId":"std","rowId":"r2","target":{"output":"srv:22009"},"nameAfter":"Gemma"}]],false]',
     "нажатие, которое не уехало дальше 5 px, — щелчок, а не канат: над моделью отпущено — ничего не послано (щелчок открывает список); "
     "уехало — канат, и он ложится на модель"),
    ("row_says_its_cell_is_off",
     '',
     '''(() => { const [b] = board(); const S = (output, serving) => { const pool = { id: "p", steps: [{ id: "r", kind: "output", output, enabled: true }] };
       const state = { selectedStepId: serving ? "r" : null, steps: serving ? [{ stepId: "r", reason: "ready" }] : [] };
       const said = b.status(pool, pool.steps[0], state); return [said.look, said.text]; };
       return [S("srv:22009"), S("srv:22009", true), S("srv:22011"), S("srv:22008", true), S("srv:22008"), S("srv:22999")]; })()''',
     '[["off-cell","cell off"],["off-cell","cell off"],["missing","failed"],["serving","Serving now"],["unknown","No request yet"],["unknown","No request yet"]]',
     "строка пула, чья ячейка не работает, говорит это словом контроллера сейчас (1.3.504; владелец: «не видно, что канат ведёт к "
     "выключенной ячейке»): остановлена — «cell off», даже если прокси последним словом сказал «отвечает»; упала — красным; "
     "negative: у работающей ячейки и у ячейки, которой нет, — слово прокси, как раньше"),
    ("carry_swallows_its_click",
     '',
     '''await (async () => { const model = node({ "data-pb-model": "", "data-output": "srv:22009", "data-name": "Gemma" }); const [b] = board({ at: () => model }); const added = [];
       b.win.addEventListener = (type, fn, opts) => { if (type === "click") added.push([fn, opts]); }; b.win.setTimeout = () => 0;
       const dot = node({ "data-pb-out": "row" }, node({ "data-pb-row": "r2" }, node({ "data-pb-pool": "std" })), { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });
       b.press({ target: dot, button: 0, pointerId: 1, clientX: 10, clientY: 10, preventDefault() {} }); await b.release({ type: "pointerup", pointerId: 1, clientX: 10, clientY: 10 });
       const afterClick = added.length;
       b.press({ target: dot, button: 0, pointerId: 2, clientX: 10, clientY: 10, preventDefault() {} }); b.follow({ pointerId: 2, clientX: 40, clientY: 10 });
       await b.release({ type: "pointerup", pointerId: 2, clientX: 40, clientY: 10 });
       const ev = { stopped: 0, prevented: 0, preventDefault() { this.prevented += 1; }, stopPropagation() { this.stopped += 1; } }; added[0]?.[0](ev);
       return [afterClick, added.length, added[0]?.[1], ev.prevented, ev.stopped]; })()''',
     '[0,1,{"capture":true,"once":true},1,1]',
     "щелчок, которым кончился перенесённый канат, — его собственный: он перехвачен один раз, до всех, и список мест над только что "
     "проведённым канатом не открывается; negative: простой щелчок ничего не перехватывает — он и открывает список"),
    ("source_place_ask",
     '',
     '''(() => { const S = m.PoolBoard.source, A = m.PoolBoard.ask, P = m.PoolBoard.placeOf;
       const pool = node({ "data-pb-pool": "std" }); const row = node({ "data-pb-row": "r2" }, pool);
       const acc = node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-sol", "data-name": "gpt-sol" });
       const cell = node({ "data-pb-model": "", "data-output": "srv:22008", "data-name": "Coder" });
       const src = [S(node({ "data-pb-out": "row" }, row)), S(node({ "data-pb-out": "new-row" }, pool)), S(node({ "data-pb-out": "model" }, acc)),
         S(node({ "data-pb-out": "model" }, cell)), S(node({ "data-pb-out": "model" })), S(node({})), S(null), S(node({ "data-pb-out": "client", "data-port": "23001" }))];
       const places = [P(node({ "data-pb-pool": "p" })), P(acc), P(cell), P(node({ "data-pb-pools-drop": "" })), P(node({})), P(null),
         P(node({ "data-pb-set": "s" })), P(node({ "data-pb-client": "23001" }))];
       const asks = [A("row", { poolId: "p", rowId: "r" }, P(cell)), A("new-row", { poolId: "p", rowId: "" }, P(acc)), A("model", src[2].from, { pool: "p" }),
         A("model", src[3].from, { newPool: true })];
       const none = [A("row", { poolId: "p", rowId: "r" }, { newPool: true }), A("new-row", { poolId: "p" }, { pool: "p" }), A("model", src[2].from, { set: "s" }),
         A("client", { port: 1 }, { set: "s" }), A("set", { setId: "s" }, { pool: "p" }), A("nope", {}, { pool: "p" })];
       return [src, places, asks, none]; })()''',
     '[[{"kind":"row","from":{"poolId":"std","rowId":"r2"}},{"kind":"new-row","from":{"poolId":"std","rowId":""}},'
     '{"kind":"model","from":{"target":{"accountId":"sub","model":"gpt-sol"},"name":"gpt-sol"}},{"kind":"model","from":{"target":{"output":"srv:22008"},"name":"Coder"}},null,null,null,null],'
     '[{"pool":"p"},{"target":{"accountId":"sub","model":"gpt-sol"},"name":"gpt-sol"},{"target":{"output":"srv:22008"},"name":"Coder"},{"newPool":true},{},{},{},{}],'
     '[["/api/pools/connect-row",{"poolId":"p","rowId":"r","target":{"output":"srv:22008"},"nameAfter":"Coder"}],'
     '["/api/pools/add-row",{"poolId":"p","target":{"accountId":"sub","model":"gpt-sol"},"nameAfter":"gpt-sol"}],'
     '["/api/pools/add-row",{"poolId":"p","target":{"accountId":"sub","model":"gpt-sol"},"nameAfter":"gpt-sol"}],'
     '["/api/pools/create",{"target":{"output":"srv:22008"},"nameAfter":"Coder"}]],'
     '[null,null,null,null,null,null]]',
     "выход говорит, что он начинает: строка — пул и строку, «＋» пула — пул без строки, модель — цель и имя, как его пишет доска; место — пул, модель с именем, "
     "колонка пулов — новый пул; одна дверь на канат и на выбор из списка: строка → модель (с именем модели), модель → пул или новый пул; "
     "negative: выход без карточки модели, не выход и выход клиента (1.3.675: клиент каната не тянет) — ничего; набор и клиент — не места; место не того рода "
     "и канаты наборов — ничего не спрашивается"),
    ("edge_lean",
     '',
     '[300, 56, 28, 0, -50, 572, 650].map((y) => m.PoolBoard.edgeLean(y, 0, 600)).concat([m.PoolBoard.edgeLean(150, 100, 700), m.PoolBoard.edgeLean(10, 0, 100)])',
     '[0,0,-0.5,-1,-1,0.5,1,-0.10714285714285714,0]',
     "у края доски канат «давит» на него: внутри — 0, ближе к краю — сильнее, у края и за ним — 1, к началу — со знаком минус; "
     "край считается от рамки доски, а не от окна; negative: в рамке меньше двух полос края давить некуда"),
    ("landing_by_kind",
     '',
     '''(() => { const col = node({ "data-pb-pools-drop": "", "data-pb-list": "pools" }); const pool = node({ "data-pb-pool": "eco" }, col);
       const inPool = node({}, pool), inCol = node({}, col); let under = inPool; const [b] = board({ at: () => under });
       const land = (kind) => { b.drag = { kind }; const el = b.landing(1, 1); b.drag = null; return el === pool ? "pool" : el === col ? "column" : el ? "other" : null; };
       const overPool = ["model", "row", "new-row", "client", "set"].map(land); under = inCol; const overColumn = ["model", "set"].map(land); return [overPool, overColumn]; })()''',
     '[["pool",null,null,null,null],["column",null]]',
     "модель ложится на пул — строкой, а мимо пулов на колонку «Pools» — своим пулом; "
     "negative: строка на пул не ложится; каната клиента и набора больше нет (1.3.675) — им места нет"),
    ("carry_a_model",
     '',
     '''await (async () => { let under = null; const [b, log] = board({ at: () => under }); const box = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) };
       const acc = node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-astra", "data-name": "gpt-astra" }); const accIn = node({ "data-pb-in": "" }, acc, box);
       acc.querySelector = (s) => (s === "[data-pb-in]" ? accIn : null); const grab = node({ "data-pb-out": "model" }, acc, box);
       const cell = node({ "data-pb-model": "", "data-output": "srv:22009", "data-name": "Gemma" }); cell.querySelector = () => null; const cellGrab = node({ "data-pb-out": "model" }, cell, box);
       const col = node({ "data-pb-pools-drop": "" }); const pool = node({ "data-pb-pool": "eco" }, col);
       const carry = async (from, over, id) => { under = over; b.press({ target: from, button: 0, pointerId: id, clientX: 0, clientY: 0, preventDefault() {} });
         const anchor = b.drag.dot; b.follow({ pointerId: id, clientX: 50, clientY: 0 }); await b.release({ type: "pointerup", pointerId: id, clientX: 50, clientY: 0 }); return anchor; };
       const a1 = await carry(grab, node({}, pool), 1); await carry(grab, node({}, col), 2); const a3 = await carry(cellGrab, node({}, col), 3);
       await carry(grab, node({ "data-pb-set": "std-set" }), 4); return [a1 === accIn, a3 === cellGrab, log.calls, b.busy]; })()''',
     '[true,true,[["/api/pools/add-row",{"poolId":"eco","target":{"accountId":"sub","model":"gpt-astra"},"nameAfter":"gpt-astra"}],'
     '["/api/pools/create",{"target":{"accountId":"sub","model":"gpt-astra"},"nameAfter":"gpt-astra"}],'
     '["/api/pools/create",{"target":{"output":"srv:22009"},"nameAfter":"Gemma"}]],false]',
     "модель, перенесённая за ручку на пул, — его новая строка; на колонку «Pools» — новый пул из неё, с её именем (ячейка — своим выходом "
     "и своим именем); канат модели тянется от её входа, а без входа — от ручки; negative: на набор модель не ложится"),
    # ── cables pulled from the right (1.3.587; the owner, 2026-10-18) ──
    ("pull_source",
     '',
     r"""(() => { const S = m.PoolBoard.source;
       const poolIn = node({ "data-pb-in": "" }, node({ "data-pb-pool": "std" }));
       const acc = node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-sol", "data-name": "gpt-sol" }); const accIn = node({ "data-pb-in": "" }, acc);
       const cell = node({ "data-pb-model": "", "data-output": "srv:22008", "data-name": "Coder" }); const cellIn = node({ "data-pb-in": "" }, cell);
       return [S(poolIn), S(accIn), S(cellIn), S(node({ "data-pb-in": "" })), S(node({}))]; })()""",
     '[null,{"kind":"model","from":{"target":{"accountId":"sub","model":"gpt-sol"},"name":"gpt-sol"}},{"kind":"model","from":{"target":{"output":"srv:22008"},"name":"Coder"}},null,null]',
     "вход модели — тоже начало каната, который тянут влево: то же, что её ручка (строка или новый пул); negative: вход пула — куда приходят вызовы клиентов — "
     "ничего не тянет (1.3.675: клиент зовёт то, что называет, и наборов нет); вход вне карточки и не вход — ничего"),
    ("pull_a_cable_from_an_input",
     '',
     r"""await (async () => { let under = null; const [b, log] = board({ at: () => under }); const box = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) };
       const poolIn = node({ "data-pb-in": "" }, node({ "data-pb-pool": "eco" }), box);
       const acc = node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-astra", "data-name": "gpt-astra" }); const accIn = node({ "data-pb-in": "" }, acc, box);
       acc.querySelector = (s) => (s === "[data-pb-in]" ? accIn : null);
       const col = node({ "data-pb-pools-drop": "" }); const poolStd = node({ "data-pb-pool": "std" }, col);
       const pull = async (from, over, id) => { under = over; b.press({ target: from, button: 0, pointerId: id, clientX: 0, clientY: 0, preventDefault() {} }); const held = b.busy;
         const anchor = b.drag.dot; b.follow({ pointerId: id, clientX: 50, clientY: 0 }); const kind = b.drag.kind;
         await b.release({ type: "pointerup", pointerId: id, clientX: 50, clientY: 0 }); return [held, kind, anchor === from]; };
       const r = [await pull(accIn, node({}, poolStd), 6), await pull(accIn, node({}, col), 7)];
       under = node({}, poolStd); b.press({ target: poolIn, button: 0, pointerId: 8, clientX: 0, clientY: 0, preventDefault() {} }); const pool = [b.drag, b.busy];
       return [r, pool, log.calls, b.busy]; })()""",
     '[[[true,"model",true],[true,"model",true]],[null,false],'
     '[["/api/pools/add-row",{"poolId":"std","target":{"accountId":"sub","model":"gpt-astra"},"nameAfter":"gpt-astra"}],'
     '["/api/pools/create",{"target":{"accountId":"sub","model":"gpt-astra"},"nameAfter":"gpt-astra"}]],false]',
     "канат, потянутый за левую точку модели: на пул — её строка, на колонку «Pools» — свой пул (то же, что за ручку); канат тянется от самой точки; пока он "
     "в руке, доска держит перерисовку; negative: точка входа пула каната не начинает — ни перерисовка не задержана, ни запроса"),
    ("pull_dot_click_does_nothing",
     '',
     r"""await (async () => { const [b, log] = board(); const box = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) };
       const model = node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-astra", "data-name": "gpt-astra", "data-pb-node": "model:acc:sub/gpt-astra" });
       const dot = node({ "data-pb-in": "" }, model, box); const body = node({}, model); model.querySelector = (s) => (s === "[data-pb-in]" ? dot : null);
       const pinOnDot = b.pin({ target: dot }); const afterDot = b.trace; const pinOnBody = b.pin({ target: body }); const afterBody = b.trace?.key || null; b.trace = null;
       b.press({ target: dot, button: 0, pointerId: 1, clientX: 0, clientY: 0, preventDefault() {} }); const held = b.busy;
       await b.release({ type: "pointerup", pointerId: 1, clientX: 0, clientY: 0 }); const noCable = b.drag;
       await b.click({ target: dot, stopPropagation() {} });
       b.press({ target: dot, button: 2, pointerId: 2, clientX: 0, clientY: 0, preventDefault() {} });
       return [pinOnDot, afterDot, pinOnBody, afterBody, held, noCable, !!b.chooser, b.busy, log.calls.length]; })()""",
     '[false,null,true,"model:acc:sub/gpt-astra",true,null,false,false,0]',
     "щелчок по левой точке модели — ничего: ни списка мест, ни закрепления пути карточки (щелчок по самой карточке закрепляет), ни запроса; нажатие без движения "
     "канатом не становится; negative: правая кнопка каната не начинает"),
    ("pull_cable_is_held_by_its_left_end",
     '',
     r"""(() => { const [b] = board(); const svg = { d: "", live: null, querySelector() { return this.live; }, insertAdjacentHTML() { this.live = { setAttribute: (k, v) => { svg.d = v; } }; } };
       const cols = { getBoundingClientRect: () => ({ left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600 }), querySelector: (s) => (s === "[data-pb-live-layer]" ? svg : null) };
       b.root = { querySelector: (s) => (s === "[data-pb-cols]" ? cols : null) };
       const dot = node({ "data-pb-in": "" }, null, { getBoundingClientRect: () => ({ left: 95, top: 500, width: 10, height: 10 }) });
       const go = (kind) => { b.drag = { kind, moved: true, dot, pointer: { x: 400, y: 100 }, over: null }; b.track(); return svg.d.split(" C")[0]; };
       return ["model", "row", "new-row"].map(go); })()""",
     '["M 400 100","M 100 505","M 100 505"]',
     "канат модели, потянутый влево, пишется от руки к точке карточки (точка остаётся на месте, рука — слева); negative: канат строки, что тянут от выхода, "
     "идёт от самой точки, как раньше"),
    ("input_dots_are_handles_in_the_markup",
     '',
     r"""(() => { const [b] = board(); const h = b.html(st.topology); const dots = (h.match(/<span class="pb-dot in" data-pb-in[^>]*><\/span>/g) || []);
       const pulls = dots.filter((d) => d.includes('data-t="pb-pull-model"')), passive = dots.filter((d) => d === '<span class="pb-dot in" data-pb-in aria-hidden="true"></span>');
       return [pulls.length > 0, passive.length, dots.length === pulls.length + passive.length, (h.match(/data-pb-in\b/g) || []).length === dots.length,
         h.includes(`data-t="pb-pull-model" title="${esc(en.pbPullModel)}"`), h.includes("pb-pull-pool"), h.includes("pb-pull-set")]; })()""",
     '[true,2,true,true,true,false,false]',
     "у каждой строки модели левая точка — ручка с hover-подсказкой на языке страницы и меткой для тестов (pb-pull-model); у каждого пула (2) точка входа — только "
     "место, куда приходят канаты клиентов, без подсказки и скрытая от читалок (1.3.675); negative: ручек пула и набора больше нет"),
    ("chooser_choices",
     '',
     '''(() => { const [b] = board(); const c = (kind, from) => b.choices(kind, from).map((x) => [x.key, x.label, x.hint, x.now, x.to]);
       return [c("client", { port: 23001 }), c("set", { setId: "std-set" }),
         c("row", { poolId: "std", rowId: "sub" }).filter((x) => x[3] || /^out:srv:2200[89]$/.test(x[0])), c("row", { poolId: "std", rowId: "sub" }).map((x) => x[0]),
         c("new-row", { poolId: "std", rowId: "" }).filter((x) => x[3]).length, c("model", { target: { accountId: "sub", model: "gpt-sol" }, name: "gpt-sol" }), c("nope", {})]; })()''',
     '[[],[],'
     '[["acc:sub/gpt-sol","gpt-sol","☁ ChatGPT",true,{"target":{"accountId":"sub","model":"gpt-sol"},"name":"gpt-sol"}],'
     '["out:srv:22008","Coder","🖥 Box :22008",true,{"target":{"output":"srv:22008"},"name":"Coder"}],'
     '["out:srv:22009","Gemma","🖥 Box :22009",false,{"target":{"output":"srv:22009"},"name":"Gemma"}]],'
     '["acc:sub/gpt-sol","acc:sub/gpt-astra","acc:sub/gpt-luna","out:srv:22008","out:srv:22009","out:srv:22010","out:srv:22011"],2,'
     '[["pool:new","＋ New pool “gpt-sol”","",false,{"newPool":true}],["pool:std","Standart","gpt-sol, Coder",true,{"pool":"std"}],'
     '["pool:eco","Econom","gpt-luna, srv:22999",false,{"pool":"eco"}]],[]]',
     "список мест по щелчку: строке и новой строке — модели карточек аккаунтов и ячейки всех машин (модели этого пула отмечены: дважды в одном пуле модель "
     "пробовалась бы дважды), модели — сначала свой новый пул, потом пулы (где она уже есть — отмечены); в строке — что внутри: модели пула, аккаунт или "
     "машина с портом; negative: клиенту и набору мест нет (1.3.675: клиент каната не тянет, наборов нет)"),
    ("chooser_found",
     '',
     '''(() => { const list = [{ key: "a", label: "Alpha", hint: "one" }, { key: "b", label: "Beta", hint: "two" }, { key: "c", label: "Gamma", hint: "ONE more" }];
       const f = (q, n) => { const r = m.PoolBoard.found(list, q, n); return [r.list.map((x) => x.key), r.more, r.total]; };
       return [f(""), f(" one "), f("zzz"), f("", 2), f("a", 1), m.PoolBoard.found([], "x").total]; })()''',
     '[[["a","b","c"],0,3],[["a","c"],0,3],[[],0,3],[["a","b"],1,3],[["a"],2,3],0]',
     "поиск списка — по имени и по строке, без регистра и пробелов по краям; сверх предела — счётом; пустой список и «ничего не нашлось» — "
     "два разных факта (total)"),
    ("chooser_opens_chooses_closes",
     '',
     '''await (async () => { const [b, log] = board(); let html = ""; const field = { value: "", focus() { this.focused = true; }, setSelectionRange() {} };
       const box = { scrollLeft: 20, scrollTop: 300, clientWidth: 1000, getBoundingClientRect: () => ({ left: 100, top: 50, right: 1100, bottom: 850, width: 1000, height: 800 }),
         insertAdjacentHTML(_p, h) { html = h; } };
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? box : s === "[data-pb-chooser]" ? (html ? { remove() { html = ""; } } : null)
         : s === "[data-pb-chooser] [data-pb-choose-query]" ? field : null) };
       const dot = (left, top) => node({ "data-pb-out": "row" }, node({ "data-pb-row": "r2" }, node({ "data-pb-pool": "std" })),
         { getBoundingClientRect: () => ({ left, top, right: left + 12, bottom: top + 12, width: 12, height: 12 }) });
       await b.click({ target: dot(140, 200), stopPropagation() {} }); const opened = [b.chooser, html.includes('style="left: 60px; top: 468px"'), html.includes(esc(en.pbChooseModel)),
         html.includes('data-pb-choose="acc:sub/gpt-sol"') && html.includes('data-pb-choose="out:srv:22009"'), field.focused];
       await b.click({ target: dot(1080, 800), stopPropagation() {} }); const up = b.chooser.at;
       const inChooser = (attrs) => node(attrs, node({ "data-pb-chooser": "" }));
       await b.click({ target: inChooser({ "data-pb-choose": "out:srv:22009" }), stopPropagation() {} }); const chosen = [b.chooser, html, log.calls];
       await b.click({ target: dot(140, 200), stopPropagation() {} }); const outside = await b.click({ target: node({}, node({ "data-pb-node": "pool:std" })), stopPropagation() {} });
       return [opened, up, chosen, [outside, b.chooser, b.trace]]; })()''',
     '[[{"kind":"row","from":{"poolId":"std","rowId":"r2"},"query":"","at":{"x":60,"y":468,"up":false}},true,true,true,true],{"x":692,"y":1044,"up":true},'
     '[null,"",[["/api/pools/connect-row",{"poolId":"std","rowId":"r2","target":{"output":"srv:22009"},"nameAfter":"Gemma"}]]],[true,null,null]]',
     "щелчок по выходу строки открывает список мест под ним, в рамке доски с её прокруткой, и ставит фокус в поиск; у нижнего края — вверх, у правого — "
     "прижат внутрь; выбор места — тот же запрос, что канат; щелчок мимо списка закрывает его и ничего больше — путь не закрепляется"),
    ("chooser_refusals",
     '',
     '''await (async () => { const [b, log] = board({ fail: true }); let html = ""; const box = { scrollLeft: 0, scrollTop: 0, clientWidth: 1000,
         getBoundingClientRect: () => ({ left: 0, top: 0, right: 1000, bottom: 800 }), insertAdjacentHTML(_p, h) { html = h; } };
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? box : s === "[data-pb-chooser]" ? (html ? { remove() { html = ""; } } : null) : null) };
       const dot = node({ "data-pb-out": "row" }, node({ "data-pb-row": "r1" }, node({ "data-pb-pool": "std" })), { getBoundingClientRect: () => ({ left: 0, top: 0, right: 12, bottom: 12 }) });
       await b.click({ target: dot, stopPropagation() {} }); const now = await b.choose("out:srv:22008"); const nowCalls = log.calls.length;
       const failed = await b.choose("out:srv:22009"); return [now, nowCalls, failed, log.notes, b.chooser?.kind, html.includes("data-pb-chooser")]; })()''',
     '[null,0,null,["controller is down"],"row",true]',
     "negative: место, куда канат уже идёт (модель, которая уже есть в этом пуле), не выбирается — запроса нет; отказ контроллера — тост с его словами, и список возвращается"),
    ("escape_order",
     '',
     '''(() => { const [b] = board(); const esc1 = () => b.escape({ key: "Escape", defaultPrevented: false, preventDefault() {} });
       b.denying = { port: 23002, query: "" }; b.chooser = { kind: "row", from: { poolId: "std", rowId: "r2" }, query: "" }; b.trace = { key: "pool:std", pinned: true };
       const r = [esc1(), b.denying, b.chooser?.kind, esc1(), b.chooser, b.trace?.key, esc1(), b.trace, esc1()];
       b.trace = { key: "pool:std", pinned: true }; const taken = b.escape({ key: "Escape", defaultPrevented: true, preventDefault() {} });
       b.drag = { kind: "row" }; const held = esc1(); b.drag = null; const other = b.escape({ key: "Enter", defaultPrevented: false });
       return [r, taken, held, other, b.trace.pinned]; })()''',
     '[[true,null,"row",true,null,"pool:std",true,null,null],null,null,null,true]',
     "Esc закрывает сначала окно запретов клиента, потом список мест, потом закреплённый путь — по одному на нажатие; negative: Esc, который взяло поле, Esc с канатом "
     "в руке и другая клавиша путь не трогают"),
    ("path_through_cards",
     '',
     '''(() => { const p = (key) => { const r = m.PoolBoard.path(st.topology, key); return [[...r.nodes].sort(), [...r.cables].sort()]; };
       return [p("model:acc:sub/gpt-sol"), p("pool:eco"), p("client:23001"), p("client:23002"), p("row:std/r1"), p("direct:live:srv:22008"), p("model:out:srv:22008"),
         p("setpool:std-set/std")[1], p(""), p("nonsense")]; })()''',
     json.dumps([[["client:23001", "model:acc:sub/gpt-sol", "pool:std", "row:std/sub"], ["client:23001/std", "row:std/sub"]],
                 [["model:acc:sub/gpt-luna", "model:out:srv:22999", "pool:eco", "row:eco/r1", "row:eco/sub"], ["row:eco/r1", "row:eco/sub"]],
                 [["client:23001", "direct:live:srv:22008", "model:acc:sub/gpt-sol", "model:out:srv:22008", "pool:std", "row:std/r1", "row:std/r2", "row:std/sub"],
                  ["client:23001/live:srv:22008", "client:23001/std", "direct:live:srv:22008", "row:std/r1", "row:std/sub"]],
                 [["client:23002"], []],
                 [["client:23001", "model:out:srv:22008", "pool:std", "row:std/r1"], ["client:23001/std", "row:std/r1"]],
                 [["client:23001", "direct:live:srv:22008", "model:out:srv:22008"], ["client:23001/live:srv:22008", "direct:live:srv:22008"]],
                 [["client:23001", "direct:live:srv:22008", "model:out:srv:22008", "pool:std", "row:std/r1"],
                  ["client:23001/live:srv:22008", "client:23001/std", "direct:live:srv:22008", "row:std/r1"]],
                 [], [[], []], [[], []]]),
     "путь через карточку — вверх до клиентов и вниз до моделей, по тому, что звали за три дня (1.3.675): модель — её строки, пулы и клиенты, что их звали, и её "
     "строка «Напрямую» с клиентами, что звали её без пула; клиент — пулы и модели, что он звал, с их строками и моделями; строка — её модель и путь её пула вверх; "
     "строка «Напрямую» — её клиенты и модель; у строки без каната каната нет и в пути; negative: в сторону путь не идёт — модель, которую никто не звал напрямую, "
     "строки «Напрямую» не зажигает, пул, который никто не звал, — клиентов, клиент, который ничего не звал, — ничего; ключ набора, пустой и непонятный — пусто"),
    ("light_hover_pin",
     '',
     '''(() => { const [b] = board(); const el = (key, attr = "pbNode") => { const e = { dataset: { [attr]: key }, cls: new Set() };
         e.classList = { toggle: (c, on) => (on ? e.cls.add(c) : e.cls.delete(c)) }; return e; };
       const nodes = ["client:23001", "client:23002", "pool:std", "pool:eco", "row:std/sub", "model:acc:sub/gpt-sol"].map((k) => el(k));
       const cables = ["client:23001/std", "row:std/sub", "row:eco/sub"].map((k) => el(k, "pbCableKey"));
       const rootEl = el("root"); rootEl.querySelectorAll = (s) => (s === "[data-pb-node]" ? nodes : s === "[data-pb-cable-key]" ? cables : []);
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? rootEl : null) };
       const lit = () => [[...rootEl.cls].sort(), nodes.filter((n) => n.cls.has("on-path")).map((n) => n.dataset.pbNode), cables.filter((c) => c.cls.has("on-path")).map((c) => c.dataset.pbCableKey)];
       b.hover({ target: node({}, node({ "data-pb-node": "model:acc:sub/gpt-sol" })) }); const hovered = lit();
       b.pin({ target: node({}, node({ "data-pb-node": "pool:eco" })) }); const pinned = lit();
       b.hover({ target: node({}, node({ "data-pb-node": "client:23002" })) }); const stillPinned = lit();
       const onControl = b.pin({ target: node({ "data-pb-out": "row" }, node({ "data-pb-node": "row:std/sub" })) });
       b.pin({ target: node({}, node({ "data-pb-node": "pool:eco" })) }); const unpinned = lit();
       b.drag = { kind: "row", moved: true }; b.hover({ target: node({}, node({ "data-pb-node": "pool:std" })) }); const carrying = [b.trace, lit()]; b.drag = null;
       return [hovered, pinned, stillPinned, onControl, unpinned, carrying]; })()''',
     '[[["tracing"],["client:23001","pool:std","row:std/sub","model:acc:sub/gpt-sol"],["client:23001/std","row:std/sub"]],'
     '[["path-alone","traced","tracing"],["pool:eco"],["row:eco/sub"]],[["path-alone","traced","tracing"],["pool:eco"],["row:eco/sub"]],false,[[],[],[]],[null,[[],[],[]]]]',
     "наведение зажигает путь карточки — только «tracing», без «traced»: остальное не отступает (правило стилей, test_path_dim_css.py; владелец, 2026-10-27) "
     "и других канатов не прячет; щелчок закрепляет путь («traced» — тогда остальное отступает) и оставляет доске только его "
     "канаты (path-alone) — наведение его не сбивает; щелчок по той же карточке отпускает; negative: щелчок по точке выхода путь не закрепляет; с канатом в руке наведение ничего не зажигает"),
    ("a_pinned_path_shows_only_its_own_cables",
     '',
     '''(() => { const [b] = board(); const el = (key, attr = "pbNode") => { const e = { dataset: { [attr]: key }, cls: new Set() };
         e.classList = { toggle: (c, on) => (on ? e.cls.add(c) : e.cls.delete(c)) }; return e; };
       const nodes = ["client:23001", "client:23002", "pool:std", "pool:eco", "row:std/sub", "model:acc:sub/gpt-sol"].map((k) => el(k));
       const cables = ["client:23001/std", "row:std/sub", "row:eco/sub"].map((k) => el(k, "pbCableKey"));
       const rootEl = el("root"); rootEl.querySelectorAll = (s) => (s === "[data-pb-node]" ? nodes : s === "[data-pb-cable-key]" ? cables : []);
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? rootEl : null) };
       const look = () => [[...rootEl.cls].sort(), nodes.filter((n) => n.cls.has("on-path")).length, cables.filter((c) => c.cls.has("on-path")).map((c) => c.dataset.pbCableKey)];
       b.trace = { key: "pool:eco", pinned: true }; b.lightPath(); const pinned = look();
       b.drag = { kind: "row", moved: true }; b.lightPath(); const carrying = look(); b.drag = null; b.lightPath(); const dropped = look();
       b.trace = { key: "client:23002", pinned: true }; b.lightPath(); const bare = look();
       b.trace = { key: "pool:gone", pinned: true }; b.lightPath(); const gone = look();
       b.trace = { key: "pool:eco", pinned: false }; b.lightPath(); const pointed = look();
       b.trace = null; b.lightPath(); const let_go = look();
       return [pinned, carrying, dropped, bare, gone, pointed, let_go]; })()''',
     '[[["path-alone","traced","tracing"],1,["row:eco/sub"]],[["traced"],0,[]],[["path-alone","traced","tracing"],1,["row:eco/sub"]],'
     '[["path-alone","traced","tracing"],1,[]],[["traced","tracing"],0,[]],[["tracing"],1,["row:eco/sub"]],[[],0,[]]]',
     "закреплённый путь оставляет доске только свои канаты (path-alone: остальные не рисуются, и на них нельзя ни смотреть, ни попасть щелчком — щелчок по канату режет его), "
     "владелец, 2026-10-18; пока карточка в руке (канат тянут), путь не горит, и возвращается, когда её опустили; "
     "клиент, который ничего не звал, — путь из него одного, и канатов у пути нет; negative: закреплённая карточка, которой на доске уже нет, ничего "
     "не прячет — доска только отступает, как отступала (иначе канаты пропали бы без объяснения); наведение без закрепления — только «tracing»: ничего не прячет и (по стилям, с 1.3.676) не уводит назад; отпущенный путь — классов нет"),
    ("pool_has_no_colour_of_its_own",
     '',
     '''(() => { const [b] = board(); const html = [b.clientsHtml(), b.poolsHtml(), b.modelsHtml()].join("");
       return [typeof b.hueOf, typeof b.hueStyle, /pool-hue|pb-hue/.test(html)]; })()''',
     '["undefined","undefined",false]',
     "negative (1.3.531, владелец: «пёстро»): у пула нет своего цвета — ни метки в голове, ни переменной на карточке; "
     "помощников hueOf и hueStyle больше нет: канаты и рамки одного цвета, цвет у пути под курсором"),
    ("single_and_turns",
     '',
     r"""(() => { const [b] = board(); const one = { id: "solo", name: "Solo", steps: [{ id: "a", kind: "account", accountId: "sub", model: "gpt-sol", enabled: true }] };
       const none = { id: "void", name: "Void", steps: [] };
       const h1 = b.poolHtml(one), h3 = b.poolHtml(st.topology.pools[0]), h0 = b.poolHtml(none);
       const notes = (h) => (h.match(/<div class="pb-turn"[^>]*>[^<]*<\/div>/g) || []).map((x) => x.replace(/<[^>]+>/g, ""));
       b.settings.add("solo"); const opened = b.poolHtml(one);
       const d1 = b.poolDetailsHtml(one), d3 = b.poolDetailsHtml(st.topology.pools[0]), d0 = b.poolDetailsHtml(none);
       const steps = (h) => (h.match(/data-t="pb-dock-step"/g) || []).length;
       return [[/class="pb-card pb-pool single"/.test(h1), h1.includes("pb-eq") || h1.includes(">=<"), h1.includes('class="pb-rank"'), h1.includes('data-pb-out="new-row"'),
           h1.includes("pb-new-out"), h1.includes('data-t="pb-pool-turns"'), h1.includes('data-t="pb-settings-panel"'), opened.includes('data-t="pb-settings-panel"'), opened.includes("data-pb-settings"), notes(h1)],
         [/class="pb-card pb-pool turns"/.test(h3), h3.includes(fill(en.pbPoolTurns, { n: "3" })), (h3.match(/class="pb-rank"/g) || []).length, h3.includes("pb-new-out"), notes(h3)],
         [/class="pb-card pb-pool"/.test(h0), h0.includes("pb-new-out"), h0.includes('class="pb-eq"'), h0.includes('data-t="pb-pool-turns"')],
         [d1.includes('data-pb-out="new-row"'), d1.includes("data-pb-settings"), notes(d1), steps(d1)],
         [d3.includes('data-pb-out="new-row"'), notes(d3), steps(d3)],
         [d0.includes("pb-new-out"), d0.includes("data-pb-settings"), d0.includes("pb-dock-steps")]]; })()""",
     r'''[[true,false,false,false,false,false,false,false,false,[]],[true,true,3,false,[]],[true,true,false,false],[true,true,[],1],[true,["↓ next when 30% (5h) is left","↓ next when the cell is busy or silent"],3],[false,true,false]]''',
     "пул из одной строки — одна строка под именем, без «=», без номера и ручки (1.3.543; до неё стоял знак «=»), а пул из нескольких — лесенка, «3 по очереди» в шапке; ни ＋, ни ⚙, ни 🕘, "
     "ни настроек, ни слов «когда пул идёт дальше» на карточке нет — они в полосе пула (1.3.533), и там: у пула из одной строки «＋ строка» и настройки, без слов между строками; "
     "у пула из трёх — по строке на каждую и два слова между ними, после последней слова нет; negative: пустой пул — обычная карточка с «＋ строка», а полоса его — "
     "только настройки: ни «＋ строки», ни списка (она на карточке)"),
    ("dock_pool_strip",
     '',
     r"""(() => { const [b] = board(); const text = (x) => x.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
       b.trace = { key: "pool:std", pinned: true }; const h = b.dockHtml(); const steps = h.match(/<li class="pb-dock-step"[^>]*>.*?<\/li>/g) || [];
       b.trace = { key: "row:std/r1", pinned: false }; const viaRow = b.dockHtml(); b.trace = { key: "pool:gone", pinned: true }; const gone = b.dockHtml();
       return [text(part(h, '<b class="pb-dock-name"', "</b>")), steps.map((x) => [(x.match(/data-t-id="([^"]*)"/) || [])[1], (x.match(/data-t-state="([^"]*)"/) || [])[1], text(x)]),
         h.includes('<div class="pb-dock-pool" data-pb-pool="std" data-pool-id="std" data-t="pb-dock-pool">'), h.includes('data-pb-out="new-row"'), h.includes('data-t="pb-settings"'),
         viaRow.includes('data-pb-pool="std"'), gone.includes('data-t-state="empty"'), b.dockDetailsHtml({ kind: "pool", id: "nope" })]; })()""",
     r'''["Standart",[["std/sub","stop","1 gpt-sol ☁ ChatGPT Stop level reached ↓ next when 30% (5h) is left"],["std/r1","serving","2 Coder 🖥 Box :22008 Serving now ↓ next when the cell is busy or silent"],["std/r2","open","3 not connected — drag from the dot to a model"]],true,true,true,true,true,""]''',
     "полоса пула: его имя, по строке на каждую — номер, модель с местом, слово прокси целиком (у строки без каната слова нет), под строкой — когда пул идёт дальше; "
     "«＋ строка» с точкой каната и «Pool settings»; пул, на котором стоит строка под курсором, показан тем же; negative: пула, которого нет, полоса не показывает — она пуста («empty»)"),
    ("row_state_dot_when_no_news",
     '',
     r"""(() => { const row = (h, id) => part(h, `data-pb-row="${id}"`, "</li>"); const pill = (h) => (h.match(/<span class="pb-status[^>]*>[^<]*<\/span>/) || [""])[0];
       const draw = () => part(board()[0].poolsHtml(), 'data-pb-pool="eco"'); const first = draw();
       st.topology.poolsRuntime.pools.eco = { selectedStepId: "", steps: [{ stepId: "sub", reason: "ready" }, { stepId: "r1", reason: "weird" }] }; const second = draw();
       st.topology.poolsRuntime = { available: false, pools: {}, events: [] }; const third = draw();
       const [b] = board(); const strip = b.poolDetailsHtml(st.topology.pools.find((p) => p.id === "eco"));
       st.topology.poolsRuntime = { available: true, pools: { eco: { selectedStepId: "", steps: [{ stepId: "sub", reason: "ready" }, { stepId: "r1", reason: "weird" }] } }, events: [] };
       const strip2 = board()[0].poolDetailsHtml(st.topology.pools.find((p) => p.id === "eco"));
       return [pill(row(first, "sub")), pill(row(second, "sub")), pill(row(second, "r1")), pill(row(third, "sub")), pill(row(part(board()[0].poolsHtml(), 'data-pb-pool="std"'), "r2")),
         strip.includes('<span class="pb-status unknown" title="">' + en.poolProxySilent + "</span>"),
         strip2.includes('<span class="pb-status ready" title="ready">' + en.poolReady + "</span>"), strip2.includes('<span class="pb-status unknown" title="weird">' + en.poolUnavailable + "</span>")]; })()""",
     r'''["<span class=\"pb-status unknown quiet\" role=\"img\" title=\"No request yet\" aria-label=\"No request yet\"></span>","<span class=\"pb-status ready quiet\" role=\"img\" title=\"Ready\" aria-label=\"Ready\"></span>","<span class=\"pb-status unknown\" title=\"weird\">Unavailable</span>","<span class=\"pb-status unknown\" title=\"\">The proxy is silent</span>","",true,true,true]''',
     "строка пула говорит своё состояние плашкой только когда оно — новость; когда нет — точкой: готова и ждёт очереди — закрашенной, прокси её ещё не спрашивал — пустой, "
     "слова в её подсказке; negative: прокси молчит и причина неизвестна — это плашка со словами, не точка (отсутствие не рисуем нормой); у строки без каната ни плашки, ни точки; "
     "в полосе слова целиком"),
    ("dock_cable_leaves_the_strip",
     '',
     r"""(() => { const make = (inStrip, colsBottom = 600) => { const [b] = board(); const svg = { d: "", live: null, querySelector() { return this.live; }, insertAdjacentHTML() { this.live = { setAttribute: (k, v) => { svg.d = v; } }; } };
       const cols = { getBoundingClientRect: () => ({ left: 0, top: 0, right: 800, bottom: colsBottom, width: 800, height: colsBottom }), querySelector: (s) => (s === "[data-pb-live-layer]" ? svg : null) };
       b.root = { querySelector: (s) => (s === "[data-pb-cols]" ? cols : null) };
       const dock = node({ "data-pb-dock": "" }, null, { getBoundingClientRect: () => ({ top: 450, bottom: 600, left: 0, right: 800 }) });
       const dot = node({ "data-pb-out": "new-row" }, inStrip ? dock : null, { getBoundingClientRect: () => ({ left: 95, top: 500, width: 10, height: 10 }) });
       b.drag = { kind: "new-row", moved: true, dot, pointer: { x: 400, y: 100 }, over: null }; b.track(); return svg.d.split(" C")[0]; };
       return [make(true), make(false), make(true, 300)]; })()""",
     r'''["M 100 450","M 100 505","M 100 300"]''',
     "канат, выходящий из полосы («＋ строка» пула, «＋ модель» набора), выходит из её верхнего края, а не из-под неё (под полосой колонки не рисуются); если колонки кончаются "
     "выше полосы — из их нижнего края; negative: канат из точки на доске идёт от самой точки, как раньше"),
    ("model_level_tag_on_the_card",
     '',
     r"""(() => { const tag = (b, model) => (item(part(b.modelsHtml(), 'data-pb-account="sub"'), '<div class="pb-model', `data-pb-key="acc:sub/${model}"`).match(/<span class="pb-status[^>]*>[^<]*<\/span>/) || [""])[0];
       const [b0] = board(); const before = [tag(b0, "gpt-sol"), tag(b0, "gpt-luna"), tag(b0, "gpt-astra")]; const level = { resetAt: 1700000000, windowSeconds: 18000, remainingPct: 5, reservePct: 10 };
       st.topology.pools[0].steps[0].switchReached = level; st.topology.pools[1].steps[0].switchReached = level; st.topology.pools[1].steps[0].stopReached = { ...level, reservePct: 2 };
       const [b1] = board(); return [before, [tag(b1, "gpt-sol"), tag(b1, "gpt-luna"), tag(b1, "gpt-astra")]]; })()""",
     r'''[["","",""],["<span class=\"pb-status reserve\" data-t=\"pb-model-level\" data-t-state=\"reserve\" title=\"Switch level reached\">↓ yielding</span>","<span class=\"pb-status stop\" data-t=\"pb-model-level\" data-t-state=\"stop\" title=\"Stop level reached\">■ stopped</span>",""]]''',
     "модель, которую пул отодвинул (порог переключения) или остановил (порог остановки), говорит это на карточке одним словом метки — «↓ yielding», «■ stopped»; "
     "полные слова плашки строки — в её подсказке; остановка важнее переключения; "
     "negative: признак без времени сброса (как в старом снимке) и модель вне пулов не говорят ничего"),
    ("dock_model_strip",
     '',
     r"""(() => { const [b] = board(); const text = (x) => x.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
       const strip = (key) => { b.trace = { key, pinned: true }; return b.dockHtml(); }; const body = (h) => text(part(h, '<div class="pb-dock-body"', "</div></aside>"));
       const sol = strip("model:acc:sub/gpt-sol"), key = strip("model:acc:or/b/two"), run = strip("model:out:srv:22008"), dead = strip("model:out:srv:22011"), gone = strip("model:acc:gone/x"), ghost = strip("model:out:srv:99999");
       const cell = (h) => [(h.match(/data-t="pb-dock-cell" data-t-state="([^"]*)"/) || [])[1], text(part(h, '<div class="pb-dock-cell"', "</div>"))];
       return [text(part(sol, '<b class="pb-dock-name"', "</b>")), sol.includes('data-t="pb-dock-levels"'), sol.includes('[bars sub sub/gpt-sol'),
         key.includes(en.cloudConnected) && key.includes("pb-dock-note"), key.includes("[bars"), cell(run), cell(dead), body(gone), body(ghost)]; })()""",
     r'''["gpt-sol",true,true,true,false,["running","running"],["failed","failed"],"",""]''',
     "полоса модели: у модели подписки — две шкалы аккаунта с её порогами и ручками (одни и те же, что были на карточке), у аккаунта по ключу — его состояние словами, а не пустое место; "
     "у ячейки — её состояние словами, в том числе «running», которого на карточке нет (там только лампа); negative: модель, которой нет на доске, названа тем, что в строке, а подробностей не выдумываем"),
    # ── what a key's model does, as the operator says it (1.3.631) ──
    ("model_work_marks",
     'st.topology.modelJobs = { offered: ["llm", "embed", "asr", "speech-translate", "tts"], set: { or: { "b/two": ["asr"], "c/three": ["asr", "tts"] } }, fixed: { sub: ["llm"] } }; st.topology.addedModels.or = ["b/two", "a/one", "c/three"];',
     r"""await (async () => { const { JOB_MARKS, JOB_LABELS } = await import(pathToFileURL(process.env.JS_ROOT + "/model-jobs.js").href);
       const [b] = board(); const models = b.modelsHtml(); const card = (key) => item(models, '<div class="pb-model', `data-pb-key="${key}"`);
       const chip = (key) => (card(key).match(/data-t="pb-model-work" data-t-state="([^"]*)" title="([^"]*)">([^<]*)<\/span>/) || []).slice(1);
       const word = (job) => en[JOB_LABELS[job]];
       return [chip("acc:or/b/two")[0], chip("acc:or/b/two").join("|") === ["said", esc(word("asr")), JOB_MARKS.asr].join("|"),
         chip("acc:or/a/one")[0], chip("acc:or/a/one").join("|") === ["unsaid", esc(en.pbWorkUnsaidHint), "?"].join("|"),
         chip("acc:or/c/three").join("|") === ["said", esc(`${word("asr")}, ${word("tts")}`), JOB_MARKS.asr + JOB_MARKS.tts].join("|"),
         card("acc:sub/gpt-sol") !== "" && !card("acc:sub/gpt-sol").includes("pb-model-work")]; })()""",
     '["said",true,"unsaid",true,true,true]',
     "модель ключа на карточке: сказанная — значками своих работ, слова — в подсказке, несколько — в том порядке, в каком их держит контроллер (словаря); "
     "несказанная — тихим «?» с подсказкой, что пулы ничего не обещают, а не видом «как у всех»; negative: у модели подписки — ничего, её работу задаёт тип"),
    ("model_work_field",
     'st.topology.modelJobs = { offered: ["llm", "embed", "asr", "speech-translate", "tts"], set: { or: { "b/two": ["asr"], "c/three": ["asr", "tts"] } }, fixed: { sub: ["llm"] } }; st.topology.addedModels.or = ["b/two", "a/one", "c/three"];',
     r"""await (async () => { const { JOB_MARKS, JOB_LABELS } = await import(pathToFileURL(process.env.JS_ROOT + "/model-jobs.js").href);
       const [b] = board(); const strip = (key) => b.modelDetailsHtml(key); const field = (key) => part(strip(key), '<label class="pb-dock-work"', "</label>");
       const opts = (key) => field(key).match(/<option[^>]*>[^<]*<\/option>/g) || [];
       const chosen = (key) => opts(key).filter((o) => o.includes(" selected")).map((o) => o.replace(/<[^>]+>/g, ""));
       const said = (job) => `${JOB_MARKS[job]} ${en[JOB_LABELS[job]]}`;
       return [opts("acc:or/b/two").map((o) => (o.match(/value="([^"]*)"/) || [])[1]), chosen("acc:or/b/two").join() === said("asr"),
         chosen("acc:or/a/one").join() === en.pbWorkUnsaid, (field("acc:or/a/one").match(/data-t-state="([^"]*)"/) || [])[1],
         chosen("acc:or/c/three").join() === esc(`${said("asr")}, ${said("tts")}`), opts("acc:or/c/three").filter((o) => o.includes(" disabled")).length,
         field("acc:or/b/two").includes('data-pb-work-account="or" data-pb-work-model="b/two"'), field("acc:or/b/two").includes(`title="${esc(en.pbWorkHint)}"`),
         strip("acc:or/b/two").includes(en.cloudConnected), field("acc:sub/gpt-sol"), strip("acc:sub/gpt-sol").includes("[bars sub sub/gpt-sol")]; })()""",
     '[["","llm","embed","asr","speech-translate","tts"],true,true,"unsaid",true,1,true,true,true,"",true]',
     "«Что делает» в полосе модели ключа: «не сказано» и пять работ, у которых есть путь входа; выбрана сказанная, у несказанной — «не сказано»; "
     "несколько работ (файл правили руками) названы как есть одной отключённой строкой, а не первой из них; поле знает аккаунт и модель; "
     "состояние ключа — по-прежнему словами; negative: у модели подписки поля нет, её шкалы — на месте"),
    ("model_work_unknown",
     'st.topology.addedModels.or = ["b/two"];',
     r"""(() => { const [b] = board(); const models = b.modelsHtml(); return [models.includes("pb-model-work"), b.modelDetailsHtml("acc:or/b/two").includes("pb-dock-work"),
       b.workOf("or", "b/two")]; })()""",
     '[false,false,null]',
     "negative: контроллер о работах моделей ничего не сказал (старый) — ни значка, ни поля, а не «?» и не выбор по догадке"),
    ("model_work_save",
     '',
     r"""await (async () => { const [b, log] = board(); let blurred = 0;
       const field = (value) => node({ "data-pb-work": "", "data-pb-work-account": "or", "data-pb-work-model": "b/two" }, null, { value, blur() { blurred += 1; } });
       await b.change({ target: field("tts") }); await b.change({ target: field("") });
       const [bad, badLog] = board({ fail: true }); let redrawn = 0; bad.redraw = () => { redrawn += 1; }; await bad.change({ target: field("asr") });
       return [log.calls, log.applied.length, blurred, badLog.notes, redrawn]; })()""",
     '[[["/api/pools/model-jobs",{"accountId":"or","model":"b/two","jobs":["tts"]}],["/api/pools/model-jobs",{"accountId":"or","model":"b/two","jobs":[]}]],2,3,["controller is down"],1]',
     "выбор в поле — одна работа уходит контроллеру списком, «не сказано» — пустым списком (слово взято назад); ответ ложится на доску; "
     "поле сначала отпускает фокус, чтобы рисунок, который его ждал, лёг с ответом; отказ — тост и доска рисуется с тем, что у контроллера"),
    ("model_work_holds_drawing",
     '',
     r"""(() => { const [b] = board(); b.doc.activeElement = node({ "data-pb-work": "" }); const held = b.typing();
       b.doc.activeElement = node({ "data-pb-probe-model": "" }); return [held, b.typing()]; })()""",
     '[true,false]',
     "открытое поле «Что делает» держит рисунок доски, как имя пула: перерисованное, оно закрыло бы список под указателем; negative: другое поле — нет"),
    ("cells_summary",
     '',
     r"""[m.PoolBoard.cellsSummary(["running", "stopped", "stopped", "failed", "stopping", "starting"]), m.PoolBoard.cellsSummary(["stopped", "weird", undefined]), m.PoolBoard.cellsSummary([]), m.PoolBoard.cellsSummary(null)]""",
     r'''["1 running · 2 stopped · 1 starting · 1 stopping · 1 failed","1 stopped · 2 unknown","",""]''',
     "сводка машины: сколько ячеек в каком состоянии, состояния в одном порядке, слова — самих состояний ячейки; negative: упавшая ячейка не числится остановленной; "
     "неожиданное состояние — «unknown», чтобы числа сходились с ячейками; ни одной ячейки — пусто"),
    ("turn_text",
     '',
     '''(() => { const [b] = board(); const T = (row) => b.turnText(row); const L = m.PoolBoard.levelsText;
       return [T({ kind: "account", accountId: "sub", model: "gpt-sol" }), T({ kind: "account", accountId: "sub", model: "gpt-luna" }),
         T({ kind: "account", accountId: "or", model: "a/one" }), T({ kind: "account", accountId: "gone", model: "x" }), T({ kind: "output", output: "srv:1" }),
         T({ kind: "open" }), T(null), L({ "604800": 20, "18000": 30 }), L({}), L({ "18000": 0, x: 5 }), L(null), L({ "86400": 15 })]; })()''',
     '["next when 30% (5h) is left","next when 10% (5h) is left","next when it refuses","next when it refuses","next when the cell is busy or silent","","",'
     '"30% (5h) · 20% (7d)","","","","15% (24h)"]',
     "когда пул идёт дальше: модель подписки — когда в окне останется её порог переключения (свой или общий по умолчанию), по каждому окну, "
     "короткое первым; ячейка — когда занята или молчит; другое — когда откажет; negative: без порога и у пропавшего аккаунта — «когда "
     "откажет»; у строки без каната — ничего"),
    ("seats_grips_nodes",
     '',
     '''(() => { const [b] = board(); const seats = (h) => (h.match(/data-pb-seat="[^"]*"/g) || []).map((x) => x.slice(14, -1)); const h = b.html(st.topology);
       const first = [seats(h), (h.match(/data-pb-list="[^"]*"/g) || []), (h.match(/data-pb-card-grip/g) || []).length,
         h.includes(`data-pb-pools-drop data-pb-drop-hint="${esc(en.pbDropNewPool)}"`), h.includes(`data-t="pb-arrange" title="${esc(en.pbArrangeTitle)}"`),
         ["client:23001", "pool:eco", "row:std/r2", "model:out:srv:22008", "model:acc:sub/gpt-astra"].filter((k) => !h.includes(`data-pb-node="${k}"`))];
       st.setTopology({ ...st.topology, layout: { clientOrder: [23001, 4242] } }); const ordered = seats(b.html(st.topology)).slice(0, 2);
       return [first, ordered]; })()''',
     '[[["23002","23001","std","eco","cloud:sub","cloud:or","node:box"],["data-pb-list=\\"clients\\"","data-pb-list=\\"pools\\"","data-pb-list=\\"models\\""],7,true,true,[]],["23001","23002"]]',
     "каждая карточка клиентов, пулов и моделей — в своём гнезде с ручкой, колонки — списки для переноса; на колонке пулов — подсказка для "
     "модели; у каждой карточки и строки — ключ пути; клиенты — в порядке оператора, пулы — по порядку файла; negative: порт без клиента "
     "в порядке ничего не рисует"),
    ("card_parts_and_orders",
     '',
     '''await (async () => { const P = m.PoolBoard.CARDS; const card = { id: "c" }; const seat = { dataset: { pbSeat: "eco" }, firstElementChild: card };
       const parts = [P.item, P.list, P.grip, P.idOf(seat), P.ownerOf({ dataset: { pbList: "pools" } }), P.card(seat) === card];
       const timers = []; const [b, log] = board(); b.win.setTimeout = (fn) => timers.push(fn);
       const saved = [await b.saveOrder("pools", ["eco", "std"]), await b.saveOrder("clients", ["23002", "23001"])].map((r) => !!r);
       const quiet = [b.pending, timers.length]; const unknown = await b.saveOrder("sets", ["empty", "std-set"]);
       return [parts, saved, log.calls, quiet, [unknown, log.calls.length, b.pending, timers.length]]; })()''',
     '[[".pb-seat","[data-pb-list]","[data-pb-card-grip]","eco","pools",true],[true,true],'
     '[["/api/pools/order",{"ids":["eco","std"]}],["/api/consumers/order",{"order":[23002,23001]}]],'
     '[false,0],[null,2,true,1]]',
     "перенос карточки: гнездо, колонка, ручка, id карточки и род колонки; новый порядок — дверью своей колонки: пулы — их id, "
     "клиенты — порты числами; negative: колонка без двери (наборов больше нет) ничего не шлёт, а доска будет нарисована заново"),
    ("refused_order_draws_again",
     '',
     '''await (async () => { const timers = []; const [b, log] = board({ fail: true }); b.win.setTimeout = (fn) => timers.push(fn); let drawn = 0;
       const el = { set innerHTML(v) { drawn += 1; } }; b.root = { querySelector: (s) => (s === "[data-pb-root]" ? el : null) };
       const r = await b.saveOrder("pools", ["eco", "std"]); const before = [r, log.notes, b.pending, timers.length, drawn];
       timers.shift()(); const after = [b.pending, drawn];
       const [g, glog] = board(); g.win.setTimeout = (fn) => timers.push(fn); const rows = [!!(await g.sortRows("std", ["r1", "sub", "r2"])), timers.length,
         await g.sortRows("std", ["sub"]), timers.length, glog.calls.length];
       return [before, after, rows]; })()''',
     '[[null,["controller is down"],true,1,0],[false,1],[true,0,null,1,0]]',
     "отказ контроллера в новом порядке — тост с его словами, и доска перерисована, когда перенос отпустил её: перенесённый порядок не "
     "остаётся на экране сохранённым на вид; строки пула — так же; negative: сохранённый порядок перерисовки не просит"),
    ("arrange_button",
     '',
     '''await (async () => { const [b, log] = board(); await b.click({ target: node({ "data-pb-arrange": "" }), stopPropagation() {} });
       const [f, flog] = board({ fail: true }); await f.click({ target: node({ "data-pb-arrange": "" }), stopPropagation() {} });
       return [log.calls, log.notes, flog.notes]; })()''',
     '[[["/api/pools/arrange",{}]],["Pools and models arranged by the cables"],["controller is down"]]',
     "«Выстроить»: контроллер ставит пулы в порядке наборов, модели — в порядке строк; тост говорит, что сделано; negative: отказ — только его слова"),
    # ── the path followed to what lies off the screen (the owner, 2026-10-18) ──
    ("reveal_follows_the_path_after_a_rest",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, CARDS);
       b.hover(over("row:std/sub")); const waiting = [s.timers.map((t) => t[1]), s.calls.length];
       s.timers[0][0](); return [waiting, said(s), b.revealTimer]; })()""",
     '[[[220],0],[["models",464,"smooth"]],0]',
     "наведение на строку пула: путь зажигается сразу, а доска идёт за ним, лишь когда указатель постоял 220 мс; тогда колонка моделей, где стоит её модель под полосой "
     "(900 > дна 592), прокручивается плавно так, чтобы модель встала над полосой (100 + 364), а колонки наборов и клиентов, где всё на виду, стоят"),
    ("reveal_goes_with_the_pointer",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, CARDS);
       b.hover(over("row:std/sub")); b.hover(over("client:23001")); const stale = (s.timers[0][0](), s.calls.length); s.timers[1][0]();
       b.hover(over("row:std/sub")); b.hover({ target: node({}) });
       const leftBoard = s.calls.length; s.timers[2][0](); return [s.timers.length, s.cleared, stale, said(s), leftBoard, s.calls.length]; })()""",
     '[3,[0,1,0,3],0,[["models",464,"smooth"]],1,1]',
     "ожидание кончается, когда указатель ушёл на другую карточку (старый таймер снят, а если он всё же сработал, ничего не двигает: путь уже другой) или с карточек вовсе "
     "(щель между ними); negative: идёт за карточкой, на которой указатель постоял"),
    ("reveal_leaves_the_persons_own_scrolling_alone",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, CARDS); b.hover(over("row:std/sub"));
       b.userScrolled = b.now() - 100; const rolling = b.reveal("row:std/sub"); const during = s.calls.length;
       b.userScrolled = b.now() - 800; const later = b.reveal("row:std/sub"); return [rolling, during, later, said(s)]; })()""",
     '[false,0,true,[["models",464,"smooth"]]]',
     "пока человек сам крутит колесо или палец (меньше 700 мс назад), доска не вмешивается; negative: когда он перестал, она идёт за путём"),
    ("reveal_calm_motion",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, CARDS, { calm: true }); b.hover(over("row:std/sub")); s.timers[0][0](); return said(s); })()""",
     '[["models",464,"auto"]]',
     "у человека, который просил меньше движения (prefers-reduced-motion), колонка встаёт на место сразу, без плавной прокрутки"),
    ("reveal_keeps_the_pointers_own_column_still",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, { ...CARDS, "pool:std": ["pools", 730, 1500, 280, 200], "client:23001": ["clients", 50, 1300, 280, 70] });
       b.hover(over("row:std/sub")); s.timers[0][0](); return said(s); })()""",
     '[["clients",864,"smooth"],["models",464,"smooth"]]',
     "колонка, где стоит указатель, не двигается, как бы далеко ни стояла в ней карточка пути (пул под строкой — в 1500); остальные колонки идут: клиент, что был "
     "в 1300, выходит на виду (100 + 764), и модель под полосой тоже"),
    ("reveal_nothing_when_all_is_in_view",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, { ...CARDS, "model:acc:sub/gpt-sol": ["models", 1080, 300, 260, 90] }); b.hover(over("row:std/sub"));
       const went = (s.timers[0][0](), s.calls.length); const at = b.reveal("row:std/sub"); return [went, at]; })()""",
     '[0,false]',
     "всё, что путь трогает, на виду (колонка, окно, не под полосой): ничего не крутится — то, что видно, не трогают"),
    ("reveal_stops_at_the_end_of_a_column",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, CARDS, { bodies: { models: { scrollTop: 2360 } } }); b.hover(over("row:std/sub")); const moved = b.reveal("row:std/sub");
       return [moved, s.calls.length]; })()""",
     '[false,0]',
     "колонка, что стоит у своего конца (2360 из 2360), дальше не идёт: ход, который ничего не изменит, не делается"),
    ("reveal_across_holds_the_pointer",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, { ...CARDS, "model:acc:sub/gpt-sol": ["models", 1080, 300, 260, 90] }, { boxWidth: 1000 });
       b.pointer = { x: 800, y: 310 }; b.hover(over("row:std/sub", 800, 310)); s.timers[0][0]();
       const call = said(s), held = b.settling;
       b.hover(over("pool:eco", 800, 311)); const still = [b.trace.key, b.settling !== null];
       b.hover(over("pool:eco", 808, 311)); return [call, held, still, [b.trace.key, b.settling]]; })()""",
     '[[["box",352,"smooth"]],{"x":800,"y":310},["row:std/sub",true],["pool:eco",null]]',
     "окно уже колонок: доска идёт вбок на 352 (набор рядом и модель справа умещаются вместе с карточкой под указателем, клиенты, что не умещаются, остаются); "
     "карточки, что идут под указателем, пока он стоит, не наводятся — путь остаётся на той, где человек был; negative: чуть сдвинул указатель (меньше 4 px) — всё ещё стоит, "
     "сдвинул на 8 — наведение работает как всегда"),
    ("reveal_across_goes_to_the_model_of_the_row",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, { "row:std/sub": ["pools", 667, 144, 327, 26], "pool:std": ["pools", 650, 110, 360, 200], "setpool:std-set/std": ["sets", 220, 260, 260, 24],
         "set:std-set": ["sets", 200, 220, 300, 120], "client:23001": ["clients", 50, 200, 280, 70], "model:acc:sub/gpt-sol": ["models", 1071, 180, 335, 24] }, { boxWidth: 1100 });
       b.pointer = { x: 800, y: 150 }; b.hover(over("row:std/sub", 800, 150)); s.timers[0][0](); const row = said(s);
       b.hover(over("model:acc:sub/gpt-sol", 900, 150)); s.timers[1][0](); return [row, said(s).slice(row.length)]; })()""",
     '[[["box",318,"smooth"]],[["pools",78,"smooth"]]]',
     "окно в 1100, а набор слева и модель справа вместе со строкой не умещаются: у строки её канат идёт вправо, поэтому доска идёт к модели (318), а набор остаётся за краем; "
     "negative: с модели канат идёт влево, строка и пул уже в окне — вбок доска стоит (карточку под указателем не гонят, даже если она наполовину за краем), а пул, чья голова выше колонки (110 < 132), подтянут вниз на 22"),
    ("pin_follows_the_path_at_once",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, CARDS); b.hover(over("row:std/sub")); const waiting = s.timers.length; const pinned = b.pin(over("row:std/sub"));
       const rest = [s.cleared.slice(), said(s)]; const again = b.pin(over("row:std/sub")); return [waiting, pinned, rest, again, b.trace, said(s).length]; })()""",
     '[1,true,[[0,1],[["models",464,"smooth"]]],true,null,1]',
     "щелчок по строке закрепляет путь, и доска идёт за ним сразу, не дожидаясь отдыха указателя (человек сделал это сам): ожидание, что шло после наведения, снято; negative: второй щелчок по той же карточке отпускает путь и ничего не крутит"),
    ("reveal_not_while_something_is_carried",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, CARDS); b.trace = { key: "row:std/sub", pinned: false }; b.drag = { kind: "row", moved: true };
       const carried = b.reveal("row:std/sub"); b.drag = null; b.trace = { key: "client:23002", pinned: false }; const other = b.reveal("row:std/sub");
       return [carried, other, s.calls.length]; })()""",
     '[false,false,0]',
     "пока в руке канат или карточка, доска сама не прокручивается (под рукой ничего не уезжает); negative: путь, что давно не тот, под указателем уже другая карточка, — тоже ничего"),
    ("the_board_leaving_the_cards_ends_the_wait",
     '',
     r"""await (async () => { const [b] = board(); const s = stage(b, CARDS); const listeners = [];
       b.mount({ dataset: {}, addEventListener: (type, fn, opts) => listeners.push([type, fn, opts]), querySelector: () => null });
       const leave = () => listeners.find(([t]) => t === "pointerleave")[1]();
       b.hover(over("row:std/sub")); const waiting = b.revealTimer; leave(); const left = [s.cleared.slice(), b.revealTimer, b.trace];
       b.pin(over("pool:std")); leave(); return [waiting, left, b.trace && b.trace.pinned]; })()""",
     '[1,[[0,1],0,null],true]',
     "указатель ушёл с доски (pointerleave): ожидание снято и путь, что шёл за указателем, погас; negative: закреплённый путь уходом не снимается"),
    ("reveal_without_smooth_scroll_sets_the_position",
     '',
     r"""(() => { const [b] = board(); const s = stage(b, CARDS); delete s.bodies.models.scrollTo; b.hover(over("row:std/sub")); const moved = b.reveal("row:std/sub");
       return [moved, s.bodies.models.scrollTop, s.calls.length]; })()""",
     '[true,464,0]',
     "элемент без scrollTo (старый браузер): положение ставится прямо — колонка встаёт на 464 без плавности; negative: плавных вызовов нет"),
    ("the_board_hears_the_persons_scrolling_and_the_pointer",
     '',
     r"""await (async () => { const [b] = board(); const listeners = []; b.mount({ dataset: {}, addEventListener: (type, fn, opts) => listeners.push([type, fn, opts]), querySelector: () => null });
       const of = (type) => listeners.filter(([t]) => t === type); const before = b.userScrolled;
       of("wheel")[0][1](); const wheel = b.userScrolled === b.now(); b.userScrolled = -Infinity; of("touchmove")[0][1](); const touch = b.userScrolled === b.now();
       b.settling = { x: 10, y: 10 }; of("pointermove")[0][1]({ clientX: 11, clientY: 10 }); const still = b.settling !== null; of("pointermove")[0][1]({ clientX: 30, clientY: 10 });
       return [before, wheel, touch, still, b.settling, b.pointer, of("pointermove")[0][2], of("wheel")[0][2]]; })()""",
     '[null,true,true,true,null,{"x":30,"y":10},{"passive":true},{"passive":true}]',
     "доска слышит колесо и палец (их она не перебивает), и указатель: сдвиг меньше 4 px — он всё ещё стоит, больше — снимает «стоит»; слушатели пассивные (прокрутку не тормозят)"),
    # ── the models' queue (model-queue.js; the owner, 2026-10-26: "the queue is to be made on the model, not in the pool") ──
    ("queue_key_is_the_row_a_request_is_on",
     '',
     r"""(() => { const [b] = board(); const k = (item) => b.queueKey(item);
       return [k({ cloudPoolId: "std", poolStepId: "r1", routedOutputId: "srv:22999" }), k({ cloudPoolId: "std", poolStepId: "sub", routedOutputId: "srv:22008" }),
         k({ routedOutputId: "srv:22009" }), k({ cloudPoolId: "gone", poolStepId: "r1", routedOutputId: "srv:22010" }), k({ cloudPoolId: "std", poolStepId: "r9" }), k({})]; })()""",
     '["out:srv:22008","","out:srv:22009","out:srv:22010","",""]',
     "модель запроса — по строке пула, на которой он сейчас (а не по выходу, которым он шёл раньше); на строке подписки — ни одной очереди; "
     "пришедший к ячейке напрямую — по её выходу; negative: строки, которой у пула нет, и запроса без адреса — ни одной"),
    ("queue_on_the_cells_line",
     '',
     r"""(() => { const [b] = board({ agents: () => QA(), slots: () => ({ "10.0.0.5:22008": 1 }) }); const models = b.modelsHtml();
       const line = item(models, '<div class="pb-model', 'data-pb-key="out:srv:22008"'); const idle = item(models, '<div class="pb-model', 'data-pb-key="out:srv:22011"');
       const [b2] = board({ agents: () => QA() }); const unknown = item(b2.modelsHtml(), '<div class="pb-model', 'data-pb-key="out:srv:22008"');
       return [line.includes('<span class="pb-queue-chip waiting" data-pb-queue-chip="out:srv:22008" data-t="pb-queue-chip" title="'
         + esc(fill(en.pbQueueChipTitle, { busy: "1", slots: "1", n: "1" })) + '">' + esc(fill(en.pbQueueChipWaiting, { busy: "1", slots: "1", n: "1" })) + "</span>"),
         idle.includes('data-pb-queue-chip="out:srv:22011" data-t="pb-queue-chip" hidden></span>'), unknown.includes(">1 of ? · 1 waiting<")]; })()""",
     '[true,true,true]',
     "строка ячейки: «1 из 1 · ждут 1», янтарная, с подсказкой; negative: у ячейки без запросов метка пустая и скрыта; слотов никто не сказал — «?»"),
    ("queue_on_the_row_that_waits",
     '',
     r"""(() => { const [b] = board({ agents: () => QA() }); const std = part(b.poolsHtml(), 'data-pb-pool="std"');
       const r1 = item(std, '<li class="pool-rung">', 'data-pb-row="r1"'); const sub = item(std, '<li class="pool-rung">', 'data-pb-row="sub"');
       const eco = item(part(b.poolsHtml(), 'data-pb-pool="eco"'), '<li class="pool-rung">', 'data-pb-row="r1"');
       return [r1.includes('<span class="pb-state waiting" data-pb-row-wait="std/r1">'), r1.includes('<span class="pb-wait" data-t="pb-row-wait">' + esc(fill(en.pbQueueRowWait, { time: "25 s" })) + "</span>"),
         r1.includes("pb-row serving"), sub.includes("pb-state"), eco.includes('<span class="pb-state" data-pb-row-wait="eco/r1">'), eco.includes('data-t="pb-row-wait"></span>')]; })()""",
     '[true,true,true,false,true,true]',
     "строка пула, чей запрос ждёт: «ждёт в очереди · ещё 25 с» поверх её состояния (состояние остаётся в разметке); "
     "negative: у строки подписки обёртки нет, у строки ячейки без ждущих — пустые слова"),
    ("queue_in_the_strip_of_a_cell",
     'st.topology.proxyPolicy = { queueYieldSec: 90, queueLimitSec: 1500 };',
     r"""(() => { const [b] = board({ agents: () => QA(), slots: () => ({ "10.0.0.5:22008": 1 }) }); const strip = b.modelDetailsHtml("out:srv:22008");
       const idle = b.modelDetailsHtml("out:srv:22009");
       return [strip.includes('<div class="pb-queue-live" data-pb-queue-live="out:srv:22008"><div class="pb-queue" data-t="pb-queue" data-t-state="waiting">'),
         strip.includes(esc(fill(en.pbQueueRunning, { time: "2:10" }))), strip.includes(esc(en.pbQueueTo503)), strip.includes(esc(en.pbQueueNext)),
         strip.includes(esc(fill(en.pbQueueYieldSaid, { time: "1.5 min" }))) && strip.includes(esc(fill(en.pbQueueLimitSaid, { time: "25 min" }))),
         strip.includes('data-pb-queue-open data-t="pb-queue-edit"'), idle.includes('data-t-state="idle"') && idle.includes(esc(en.pbQueueNobody)),
         b.modelDetailsHtml("acc:sub/gpt-sol").includes("pb-queue"), strip.includes("<b>Hermes</b> · Standart"), strip.includes("· std<"),
         b.poolName("std"), b.poolName("gone")]; })()""",
     '[true,true,true,true,true,true,true,false,true,false,"Standart","gone"]',
     "полоса ячейки: её очередь (слот «идёт 2:10», ждущий с «→ 503» и «следующий в слот»), рядом — настройки словами и «Изменить»; "
     "ждущий назван клиентом и именем пула (Standart), а не его id; "
     "negative: у пустой — «никто не ждёт», у модели подписки очереди нет, id пула (std) в полосе не стоит; пул, которого доска не знает, — его id"),
    ("queue_names_the_builtin_clients_model",
     'WITH_OWUI();',
     r"""(() => { const agents = () => ({ "23009": { port: 23009, active: [{ id: "o1", route: "Open WebUI", phase: "queued", cloudPoolId: "live:srv:22008",
         poolStepId: "r1", routedOutputId: "srv:22008", upstream: "10.0.0.5:22008", queue: { since: 975, leaveAt: 4275, leaveTo: "refuse", position: 0 } }] } });
       const [b] = board({ agents }); const strip = b.modelDetailsHtml("out:srv:22008");
       return [strip.includes("<b>Open WebUI</b> · Coder<"), strip.includes("live:srv:22008"), b.poolName("live:acc:sub/gpt-sol"), b.poolName("live:srv:22009"), b.poolName("live:nope")]; })()""",
     '[true,false,"gpt-sol","Gemma","live:nope"]',
     "запрос к модели напрямую в очереди модели назван её именем, каким её зовут клиенты (каталог доски, liveCatalog), а не id её пула "
     "(владелец, 2026-10-27: в полосе стояло «Open WebUI · live:mm:3a5…») — и остановленной модели тоже; negative: пул, которого нет ни в файле, ни в каталоге, — его id"),
    ("routing_tour_anchors_are_drawn",
     '',
     r"""(() => { const [b] = board(); const html = b.html(st.topology);
       return [tours.TOURS.routing().filter((x) => x.anchor && !drawn(html, x.anchor)).map((x) => x.anchor), tours.TOURS.routing().length, drawn(html, "[data-t='pb-nope']")]; })()""",
     '[[],6,false]',
     "каждый якорь тура «Маршрутизации» доска и рисует — четыре колонки и кнопка очереди в шапке моделей (2026-10-27: шаг очереди); "
     "negative: якорь, которого доска не рисует, не находится"),
    ("queue_button_in_the_models_head",
     '',
     r"""await (async () => { const [b] = board(); const shut = b.modelsHtml(); st.topology.proxyPolicy = { queueYieldSec: 90, queueLimitSec: 1500 };
       const [b2] = board(); await b2.click({ target: node({ "data-pb-queue-open": "" }) }); const open = b2.modelsHtml();
       return [shut.includes('data-pb-queue-open aria-expanded="false" data-t="pb-queue-settings"') && shut.includes(">" + esc(fill(en.pbQueuePill, { wait: en.pbQueueAtOnce, limit: en.pbQueueNoLimit })) + "</button>"),
         shut.includes("pb-queue-panel"), open.includes(">" + esc(fill(en.pbQueuePill, { wait: "1.5 min", limit: "25 min" })) + "</button>"),
         open.includes('data-t="pb-queue-panel"') && open.indexOf("pb-queue-panel") < open.indexOf('class="pb-card'), b2.queue.open]; })()""",
     '[true,false,true,true,true]',
     "шапка «Модели»: кнопка говорит обе настройки («сразу · без предела» без них, «1,5 мин · 25 мин» с ними); щелчок открывает поля над карточками; "
     "negative: закрытая — полей нет"),
    ("client_name_button_in_the_clients_head",
     '',
     r"""await (async () => { const [b] = board(); const shut = b.clientsHtml(); st.topology.proxyPolicy = { clientName: "pi (linux; x64)" };
       const [b2] = board(); await b2.click({ target: node({ "data-pb-client-name-open": "" }) }); const open = b2.clientsHtml();
       return [shut.includes('data-pb-client-name-open aria-expanded="false"') && shut.includes(">" + esc(en.pbClientNamePillOwn) + "</button>"), shut.includes("pb-client-name-panel"),
         open.includes(">" + esc(fill(en.pbClientNamePill, { name: "pi (linux; x64)" })) + "</button>"), open.includes('data-t="pb-client-name-panel"'), b2.clientName.open]; })()""",
     '[true,false,true,true,true]',
     "шапка «Клиенты»: кнопка говорит, под каким именем клиенты идут к провайдерам, щелчок открывает поле (владелец, 2026-10-31: «давай представляться как один»); "
     "negative: закрытая — поля нет"),
    ("client_name_field_saves_the_policy",
     'st.topology.proxyPolicy = { clientName: "" };',
     r"""await (async () => { const [b, log] = board({ res: { ok: true, config: { policy: { clientName: "pi" } } } });
       await b.change({ target: node({ "data-pb-client-name": "" }, null, { value: "pi" }) });
       b.doc.activeElement = node({ "data-pb-client-name": "" }); const held = b.typing();
       return [log.calls, log.applied.map((x) => x.proxyPolicy), held]; })()""",
     '[[["/api/agent-proxies/policy",{"policy":{"clientName":"pi"}}]],[{"clientName":"pi"}],true]',
     "поле имени, отпущенное, сохраняется в политику прокси, и доска рисуется с тем, что хранит контроллер; пока в нём печатают, рисунок доски ждёт"),
    ("queue_field_saves_the_policy",
     'st.topology.proxyPolicy = { queueYieldSec: 90, queueLimitSec: 1500 };',
     r"""await (async () => { const [b, log] = board({ res: { ok: true, config: { policy: { queueYieldSec: 30, queueLimitSec: 1500 } } } });
       await b.change({ target: node({ "data-pb-queue-field": "queueYieldSec" }, null, { value: "0.5" }) });
       const [b2, log2] = board(); const wrong = node({ "data-pb-queue-field": "queueLimitSec" }, null, { value: "61" }); await b2.change({ target: wrong });
       return [log.calls, log.applied.map((x) => x.proxyPolicy), log2.calls, wrong.value, log2.notes]; })()""",
     '[[["/api/agent-proxies/policy",{"policy":{"queueYieldSec":30}}]],[{"queueYieldSec":30,"queueLimitSec":1500}],[],"25",["A whole number from 0 to 60"]]',
     "поле очереди, отпущенное, сохраняется в политику прокси, и доска рисуется с политикой, которую хранит контроллер; "
     "negative: 61 мин не отправлены — поле вернулось к 25, сказано, в каких границах"),
    ("queue_painted_in_place",
     '',
     r"""(() => { let now = 1000000; const seen1 = QA(now); const [b] = board({ agents: () => seen1, slots: () => ({ "10.0.0.5:22008": 1 }), now: () => now });
       const el = (attrs, extra = {}) => { const n = node(attrs, null, { textContent: "", innerHTML: "", hidden: true, title: null, ...extra });
         n.classList.toggle = (c, on) => { if (on) n.classes.add(c); else n.classes.delete(c); };
         n.setAttribute = (k, v) => { n.title = v; }; n.removeAttribute = () => { n.title = null; }; return n; };
       const wait = el({ "data-t": "pb-row-wait" });
       const els = { "[data-pb-queue-chip]": [el({ "data-pb-queue-chip": "out:srv:22008" }), el({ "data-pb-queue-chip": "out:srv:22011" })],
         "[data-pb-row-wait]": [el({ "data-pb-row-wait": "std/r1" }, { querySelector: () => wait })], "[data-pb-queue-live]": [el({ "data-pb-queue-live": "out:srv:22008" })] };
       b.root = { querySelectorAll: (s) => els[s] || [] }; b.top = st.topology;
       const first = b.paintQueue(); const chip = els["[data-pb-queue-chip]"][0]; const seen = [chip.textContent, chip.hidden, chip.classes.has("waiting"), wait.textContent,
         els["[data-pb-row-wait]"][0].classes.has("waiting"), els["[data-pb-queue-live]"][0].innerHTML.includes("pb-queue-wait"), els["[data-pb-queue-chip]"][1].hidden];
       const again = b.paintQueue(); now += 5000; const later = b.paintQueue();
       return [first, seen, again, later, wait.textContent]; })()""",
     '[4,["1 of 1 · 1 waiting",false,true,"waiting in the queue · 25 s left",true,true,true],0,2,"waiting in the queue · 20 s left"]',
     "монитор прочитан: метка, строка пула и полоса рисуются на месте; negative: то же чтение не трогает ничего (0), "
     "через 5 с меняется только то, где время (строка пула и полоса)"),
    ("queue_idle_strip_says_its_slots",
     'st.topology.routers[0].outputs[1].slotGroup = "10.0.0.5:22009";',
     r"""(() => { const busy = (n) => ">" + esc(fill(en.pbQueueBusy, { busy: "0", slots: n })) + "<";
       const [b] = board({ slots: () => ({ "10.0.0.5:22009": 1, "10.0.0.5:22010": 4 }) });
       const [b2] = board(); const [b3] = board({ slots: () => ({ "10.0.0.5:22009": 0 }) });
       return [b.modelDetailsHtml("out:srv:22009").includes(busy("1")), b2.modelDetailsHtml("out:srv:22009").includes(busy("?")),
         b3.modelDetailsHtml("out:srv:22009").includes(busy("?")), b.modelDetailsHtml("out:srv:22010").includes(busy("?"))]; })()""",
     '[true,true,true,true]',
     "полоса модели, которой никто не занят, говорит её слоты по имени её очереди (slotGroup выхода): «0 из 1» (владелец, 2026-10-26: «вижу баги внизу»); "
     "negative: прокси слотов не сказал или сказал 0 — «?»; у выхода без имени очереди — тоже «?», чужие слоты (22010) ему не достаются"),
    ("queue_side_door_beside_its_title",
     'st.topology.proxyPolicy = { queueYieldSec: 90, queueLimitSec: 1500 };',
     r"""(() => { const [b] = board(); const strip = b.modelDetailsHtml("out:srv:22009"); const side = strip.slice(strip.indexOf('data-t="pb-queue-side"'));
       const head = side.slice(0, side.indexOf("</div>")); const wait = (time) => "<p>" + esc(fill(en.pbQueueClientWaitSaid, { time })) + "</p>";
       st.topology.proxyPolicy = { queueYieldSec: 90, clientTimeoutSec: 1800 }; const [b2] = board(); const half = b2.modelDetailsHtml("out:srv:22009");
       return [head.includes("<b>" + esc(en.pbQueueSettingsTitle) + "</b>"), head.includes('data-t="pb-queue-edit"'),
         side.split('data-t="pb-queue-edit"').length - 1, side.indexOf('data-t="pb-queue-edit"') < side.indexOf("pb-queue-legend"),
         strip.startsWith('<div class="pb-queue-wrap"><div class="pb-queue-main"><div class="pb-dock-cell"'), side.includes(wait("60 min")),
         half.includes(wait("30 min")), half.includes(wait("60 min"))]; })()""",
     '[true,true,1,true,true,true,true,false]',
     "в полосе «Изменить» стоит в строке заголовка настроек, над словами и легендой — подножие полосы его больше не срезает; "
     "состояние модели стоит над её очередью, в той же колонке, и настройки начинаются от верха полосы; сказано, сколько ждут клиенты, — "
     "такой тайм-аут ставить агентам (несказанное — 60 мин); negative: второй кнопки после легенды нет, при 30 мин — 30, а не 60"),
    ("queue_slot_says_its_clients_deadline",
     '',
     r"""(() => { const at = 1000; const item = (deadline) => ({ "23005": { port: 23005, active: [{ id: "x1", route: "Bot", phase: "streaming",
         routedOutputId: "srv:22008", upstream: "10.0.0.5:22008", startedAt: at - 140, slotAt: at - 130, ...(deadline ? { clientDeadline: deadline } : {}) }] } });
       const words = (deadline) => { const [b] = board({ agents: () => item(deadline), slots: () => ({ "10.0.0.5:22008": 1 }) });
         return (b.modelDetailsHtml("out:srv:22008").match(/<span class="pb-queue-time run">([^<]*)<\/span>/) || [])[1]; };
       return [words(at - 140 + 3600) === fill(en.pbQueueRunningLeft, { time: "2:10", left: "57:40" }), words(null) === fill(en.pbQueueRunning, { time: "2:10" })]; })()""",
     '[true,true]',
     "в слоте полосы — сколько идёт запрос и сколько ещё ждёт его клиент, по сроку, который сказал прокси (владелец, 2026-10-26: "
     "«почему не известен?»); negative: без срока — «конец неизвестен», как прежде"),
    # The built-in clients (2026-10-27) stand first; since 1.3.675 they are clients as any other: what they see, what is closed to them,
    # what they called.
    ("clients_column_with_builtin",
     'WITH_OWUI();',
     r"""(() => { const [b] = board(); const h = b.clientsHtml(); const own = part(h, 'data-pb-client="23009"'); const at = (x) => h.indexOf(x);
       return [at('data-pb-client="23009"') < at('data-pb-client="23002"'), h.includes("pb-clients-divider"), own.includes('data-t-state="builtin"'),
         own.includes(">" + en.consumerBuiltinChip + "<"), own.includes(">" + fill(en.pbClientSeesAll, { all: "5" }) + "<"), own.includes("data-pb-anchor"),
         own.includes("pb-card-grip"), own.includes("data-pb-deny-open"), h.includes('data-pb-seat="23009"'), h.includes('data-pb-seat="23001"')]; })()""",
     '[true,false,true,true,true,true,false,true,false,true]',
     "встроенный — первым, без черты под ним (1.3.675: он клиент, как любой другой): «свой», «видит все 5», точка, откуда идут его канаты, «＋ Запретить»; "
     "negative: ни ручки переноса, ни места в порядке — он всегда первый; у обычных место осталось"),
    ("clients_column_without_builtin",
     '',
     '(() => { const [b] = board(); const h = b.clientsHtml(); return [h.includes("pb-clients-divider"), h.includes("pb-builtin")]; })()',
     '[false,false]',
     "negative: встроенного нет — нет и черты"),
    ("client_count_not_known",
     'WITH_OWUI({ models: undefined });',
     r"""(() => { const [b] = board(); const h = b.clientsHtml(); const own = part(h, 'data-pb-client="23009"'), her = part(h, 'data-pb-client="23001"');
       st.topology.entryModels = null; const [c] = board(); const now = part(c.clientsHtml(), 'data-pb-client="23001"');
       return [own.includes(">" + en.pbClientModelsUnknown + "<"), own.includes('data-t="pb-client-count" data-t-state="unknown"'),
         her.includes('data-t="pb-client-count" data-t-state="all"'), now.includes(">" + en.pbClientModelsUnknown + "<"), now.includes("Sees")]; })()""",
     '[true,true,true,true,false]',
     "что видит клиент, не прочитано — «моделей: не известно»; не прочитано, что видит клиент, которому ничего не запрещено, — то же у каждого: "
     "сравнить не с чем; negative: «не известно» — не «ни одной модели» и не «видит все»"),
    ("closed_marks_on_models",
     'st.topology.proxies[1].deny = ["model:srv:22008", "account:sub", "host:box"];',
     r"""(() => { const [b] = board(); const html = b.modelsHtml(); const sub = part(html, 'data-pb-account="sub"'), box = part(html, 'data-pb-machine="box"');
       const row = (h, key) => item(h, '<div class="pb-model', `data-pb-key="${key}"`);
       const closed = (x) => (x.match(/data-t="pb-model-closed"[^>]*>⊘ ([^<]*)</) || [])[1] || null;
       const head = (x) => part(x, '<div class="pb-src-head"', "</div>");
       st.setTopology(TOPO()); const [c] = board(); const plain = c.modelsHtml();
       return [closed(row(box, "out:srv:22008")), closed(row(box, "out:srv:22009")), closed(head(sub)), closed(head(box)), closed(row(sub, "acc:sub/gpt-sol")),
         row(box, "out:srv:22008").includes(`title="${esc(fill(en.pbClosedTitle, { names: "Bot" }))}"`), plain.includes("pb-model-closed"),
         m.PoolBoard.denyKey("out:srv:1"), m.PoolBoard.denyKey("acc:a/m"), m.PoolBoard.denyKey("x"), m.PoolBoard.closedHtml([])]; })()""",
     '["Bot",null,"Bot","Bot",null,true,false,"model:srv:1","model:acc:a/m","",""]',
     "что запрещено клиенту, видно и на моделях (владелец, 2026-10-27, макет: «запрещена для: SpiderMonkey»): модель машины — на своей строке, аккаунт и машина целиком — "
     "в голове своей карточки, с именами клиентов в подсказке; ключ модели на доске → ключ её запрета: выход машины — model:<выход>, модель аккаунта — model:acc:…; "
     "negative: модель, запрещённая только через источник, своей метки не несёт (метка у источника); никому ничего не запрещено — меток нет; ключ не модели — пусто"),
    ("two_builtins_on_routing",
     'WITH_BOTH();',
     r"""(() => { const [b] = board(); const h = b.clientsHtml(); const ow = part(h, 'data-pb-client="23009"'), oc = part(h, 'data-pb-client="23010"'); const at = (x) => h.indexOf(x);
       const subHead = part(part(b.modelsHtml(), 'data-pb-account="sub"'), '<div class="pb-src-head"', "</div>");
       return [at('data-pb-client="23009"') < at('data-pb-client="23010"') && at('data-pb-client="23010"') < at('data-pb-client="23002"'),
         oc.includes(">⊘ ChatGPT<"), oc.includes(`title="${esc(fill(en.pbDenySource, { name: "ChatGPT" }))}"`), oc.includes(">" + fill(en.pbClientSeesSome, { n: "3", all: "5" }) + "<"),
         ow.includes("data-pb-anchor") && oc.includes("data-pb-anchor"), [...m.PoolBoard.path(st.topology, "client:23010").nodes], subHead.includes(">⊘ opencode<")]; })()""",
     '[true,true,true,true,true,["client:23010"],true]',
     "два встроенных — первыми, в порядке видов, потом остальные; opencode запрещён аккаунт целиком — на его карточке чип с именем аккаунта, «видит 3 из 5», а голова "
     "аккаунта говорит, кому он запрещён; оба — с точкой своих канатов; путь opencode, который ничего не звал, — он один"),
    ("builtin_path",
     'WITH_OWUI();',
     r"""(() => { const top = st.topology; const own = m.PoolBoard.path(top, "client:23009"); const sol = m.PoolBoard.path(top, "model:acc:sub/gpt-sol");
       const astra = m.PoolBoard.path(top, "model:acc:sub/gpt-astra"); const [b] = board();
       return [[...own.nodes].sort(), [...own.cables].sort(), sol.nodes.has("client:23009"), sol.nodes.has("client:23001"),
         astra.nodes.has("client:23009"), b.routeOf("model:acc:sub/gpt-sol")[0].names]; })()""",
     '[["client:23009","direct:live:acc:sub/gpt-sol","model:acc:sub/gpt-sol"],["client:23009/live:acc:sub/gpt-sol","direct:live:acc:sub/gpt-sol"],true,true,false,["Open WebUI","Hermes"]]',
     "путь встроенного — как любого клиента, по тому, что он звал: Open WebUI звал gpt-sol напрямую — его путь идёт через строку «Напрямую» к модели; путь модели "
     "называет его среди клиентов рядом с Hermes, что звал её пулом; negative: модель, которую он не звал, его не зажигает"),
    # «Напрямую» (the owner, 2026-10-27, option В2): pinned on the top of the pools' column, a row for each model called straight now — all of them.
    ("direct_rows",
     '',
     r"""(() => { const look = (agents, trace = null) => { const [b] = board({ agents: () => agents }); b.trace = trace; return [b.directRows(), b.directHtml()]; };
       const [rest, restHtml] = look(undefined);
       const [live, liveHtml] = look(RUN({ cloudPoolId: "live:srv:22008", poolStepId: "r1" }));
       const [ended, endedHtml] = look(SAW({ cloudPoolId: "live:srv:22008", poolStepId: "r1", finishedAt: 998 }));
       const [pinned, pinnedHtml] = look(undefined, { key: "client:23001", pinned: true });
       const [model] = look(undefined, { key: "model:out:srv:22008", pinned: true });
       const [row] = look(undefined, { key: "direct:live:srv:22009", pinned: true });
       const [hovered] = look(undefined, { key: "client:23001", pinned: false });
       const [unknown] = look(RUN({ cloudPoolId: "live:mm:zzz", poolStepId: "r1" }));
       st.topology.proxies[0].calls = [{ pool: "live:gone", count: 1, last: 1 }]; const [gone] = look(undefined, { key: "client:23001", pinned: true });
       const who = (h) => (h.match(/class="pb-direct-who" title="[^"]*">([^<]*)</) || [])[1];
       return [rest, restHtml.includes('data-t="pb-direct" data-t-state="quiet"') && restHtml.includes(">" + en.pbDirectNone + "<"), live,
         liveHtml.includes('data-pb-node="direct:live:srv:22008"') && liveHtml.includes('<span class="pb-led" aria-hidden="true">'),
         liveHtml.includes('<small class="pb-direct-where">🖥 Box :22008</small>'), liveHtml.includes(">" + fill(en.pbDirectPaths, { n: "1" }) + "<"), who(liveHtml),
         ended[0].state, who(endedHtml), pinned, pinnedHtml.includes(">" + en.pbDirectPicked + "<"), who(pinnedHtml), model, row, hovered, unknown, gone]; })()""",
     json.dumps([[], True,
                 [{"pool": "live:srv:22008", "name": "Coder", "key": "out:srv:22008", "ports": [23001], "state": "live", "count": 0}],
                 True, True, True, "Hermes", "ended", "Hermes · just now",
                 [{"pool": "live:srv:22008", "name": "Coder", "key": "out:srv:22008", "ports": [23001], "state": "recent", "count": 3}], True, "Hermes · 3 in 3 days",
                 [{"pool": "live:srv:22008", "name": "Coder", "key": "out:srv:22008", "ports": [23001], "state": "recent", "count": 3}],
                 [{"pool": "live:srv:22009", "name": "Gemma", "key": "out:srv:22009", "ports": [], "state": "recent", "count": 0}],
                 [],
                 [{"pool": "live:mm:zzz", "name": "live:mm:zzz", "key": "", "ports": [23001], "state": "live", "count": 0}],
                 []]),
     "«Напрямую»: в покое — ни строки, «сейчас никто»; запрос к модели напрямую — её строка по имени модели, с лампой, где она стоит и кто её зовёт, в голове — "
     "сколько путей сейчас; запрос только что кончился — строка ещё стоит: «только что»; закреплён клиент — модели, что он звал напрямую за три дня, со счётом, "
     "в голове «звали раньше»; закреплена модель — её строка с теми, кто звал её напрямую; закреплена строка — она сама, даже без вызовов (остановленная Gemma); "
     "запрос к модели, которой доска не знает, — строка с id её пула (не догадка); negative: наведение без закрепления строк не добавляет; вызов за три дня к "
     "модели, которой доска больше не знает, строки не даёт — канату некуда идти"),
    ("direct_painted_in_place",
     '',
     r"""(() => { let agents; const [b] = board({ agents: () => agents });
       const el = { innerHTML: "", attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } }; b.root = { querySelector: (s) => (s === "[data-pb-direct-block]" ? el : null) };
       const same = b.paintDirect(); agents = RUN({ cloudPoolId: "live:srv:22008", poolStepId: "r1" }); const changed = b.paintDirect(); const after = [el.attrs["data-t-state"], el.innerHTML.includes(">Coder<")];
       const again = b.paintDirect(); agents = undefined; const gone = b.paintDirect(); const quiet = el.attrs["data-t-state"]; b.root = null; const none = b.paintDirect();
       return [same, changed, after, again, gone, quiet, none]; })()""",
     '[false,true,["paths",true],false,true,"quiet",false]',
     "«Напрямую» рисуется заново на месте, когда пути пришли или ушли (перед канатами, что к его строкам идут); negative: то же самое — не трогается; доски нет — ничего"),
    ("cable_of",
     '',
     r"""(() => { const [b] = board(); const c = (k) => { const x = b.cableOf(k); return x && [x.from, x.to, x.cuts, x.quiet, x.lit]; };
       return [c("client:23001/std"), c("client:23001/live:srv:22008"), c("client:4242/std"), c("direct:live:srv:22008"), c("direct:live:nope"),
         c("row:std/r1"), c("row:std/r2"), c("row:eco/r1"), c("set:std-set/std"), c("nonsense")]; })()""",
     json.dumps([['[data-pb-node="client:23001"] [data-pb-anchor]', '[data-pb-pool="std"] > [data-pb-in]', False, False, False],
                 ['[data-pb-node="client:23001"] [data-pb-anchor]', '[data-pb-direct="live:srv:22008"] [data-pb-direct-in]', False, False, False],
                 ['[data-pb-node="client:4242"] [data-pb-anchor]', '[data-pb-pool="std"] > [data-pb-in]', False, True, False],
                 ['[data-pb-direct="live:srv:22008"] [data-pb-direct-out]', '[data-pb-key="out:srv:22008"] [data-pb-in]', False, False, False],
                 ['[data-pb-direct="live:nope"] [data-pb-direct-out]', '[data-pb-key=""] [data-pb-in]', False, True, False],
                 ['[data-pb-pool="std"] [data-pb-row="r1"] [data-pb-out]', '[data-pb-key="out:srv:22008"] [data-pb-in]', True, False, True],
                 None,
                 ['[data-pb-pool="eco"] [data-pb-row="r1"] [data-pb-out]', '[data-pb-key="out:srv:22999"] [data-pb-in]', True, True, False],
                 None, None]),
     "где идёт канат по его ключу: клиента — от его точки к входу пула или к строке «Напрямую» (не режется), строки «Напрямую» — к модели (не режется), строки пула — "
     "к модели (режется щелчком, служащая горит); `quiet` — конец, которого нет по известной причине: порт не клиент входа, модель «Напрямую» неизвестна, ячейка "
     "строки пропала; negative: строка без каната, ключи набора и непонятные — канатов нет"),
    # What a client is closed to (1.3.675, option А): chips on its card and the window "＋ Close" opens.
    ("deny_labels",
     '',
     r"""(() => { const [b] = board(); return ["pool:eco", "model:srv:22008", "account:sub", "host:box", "pool:old", "model:mm:gone", "account:nope", "host:far", "junk"]
       .map((k) => { const l = b.denyLabel(k); return [l.name, l.title, !!l.gone]; }); })()""",
     json.dumps([["Econom", "Blocked: the pool Econom", False], ["Coder", "Blocked: the model Coder", False], ["ChatGPT", "Blocked: every model of ChatGPT", False],
                 ["Box", "Blocked: every model of Box", False],
                 *[["gone", f"{k} is no longer on the board: this block stops nothing. Open the window to take it off.", True]
                   for k in ("pool:old", "model:mm:gone", "account:nope", "host:far", "junk")]]),
     "чип запрета называет запрещённое так, как его зовёт доска: пул и модель — по имени, аккаунт и машина — по имени карточки; negative: ключ, чьего пула, модели "
     "или источника на доске больше нет, — «нет на доске»: он ничего не закрывает, и его снимают в окне (не догадка о том, что это было)"),
    ("deny_window",
     'st.topology.proxies[1].deny = ["pool:eco", "model:srv:22008", "pool:old"];',
     r"""(() => { const [b] = board(); b.denying = { port: 23002, query: "" }; const h = b.denyHtml();
       const items = [...h.matchAll(/<label class="pb-deny-item([^"]*)" data-t="pb-deny-item" data-t-id="([^"]+)" data-t-state="([^"]+)">/g)].map((x) => [x[2], x[3], x[1].trim()]);
       const still = (h.match(/data-t="pb-deny-still">([^<]*)</) || [])[1], more = (h.match(/data-t="pb-deny-more">([^<]*)</) || [])[1];
       b.denying.query = "gem"; const found = b.denyBodyHtml(st.topology.proxies[1]); const foundItems = [...found.matchAll(/data-t-id="([^"]+)" data-t-state/g)].map((x) => x[1]);
       b.denying.query = ""; st.topology.proxies[1].deny = ["pool:std", "model:srv:22008"];
       const alone = (b.denyBodyHtml(st.topology.proxies[1]).match(/data-t="pb-deny-still">([^<]*)</) || [])[1] || null;
       st.topology.proxies[1].deny = ["host:box"]; const whole = b.denyBodyHtml(st.topology.proxies[1]);
       const coder = (whole.match(/<label[^>]*data-t-id="model:srv:22008"[^>]*>.*?<\/label>/) || [""])[0];
       st.topology.denyChoices = null; const unread = b.denyBodyHtml(st.topology.proxies[1]); b.denying = { port: 4242, query: "" };
       return [h.includes(">" + esc(fill(en.pbDenyTitle, { name: "Bot" })) + "<"), h.includes("data-pb-deny-query"), items, still, alone, more, found.includes(esc(en.pbDenyStopped)), foundItems,
         coder.includes(" checked") && coder.includes(" disabled") && coder.includes(esc(fill(en.pbDenyBySource, { name: "Box" }))), unread.includes('data-t="pb-deny-unread"'), b.denyHtml()]; })()""",
     json.dumps([True, True,
                 [["host:box", "open", "head"], ["model:srv:22008", "closed", "closed"], ["account:sub", "open", "head"], ["model:acc:sub/gpt-sol", "open", ""],
                  ["model:acc:sub/gpt-astra", "open", ""], ["pool:std", "open", ""], ["pool:eco", "closed", "closed"], ["pool:old", "closed", "closed"]],
                 "Its pools still call it: Standart", None, "1 more — find them by name", True, ["host:box", "model:srv:22009", "pool:old"], True, True, ""]),
     "окно «Что запретить для Bot»: источники — машина и аккаунт, каждый с галкой «целиком» и своими моделями под ним: сразу видны работающие и уже запрещённые, остальные "
     "сказаны счётом и находятся поиском; потом пулы; запрещённое отмечено; запрещённая модель, которую ещё зовёт разрешённый клиенту пул, говорит это (владелец: пул работает "
     "целиком), а когда запрещён и сам пул — молчит; запрет, чьего на доске нет, — отдельно, его снимают; поиск находит и остановленную модель — её можно запретить заранее; машина запрещена целиком — её модели "
     "отмечены и не разрешаются по одной, «запрещена вместе с Box»; negative: не прочитано — так и сказано, а не пустое окно; окна для клиента, которого нет, нет"),
    ("deny_toggle_saves",
     '',
     r"""await (async () => { const [b, log] = board(); b.denying = { port: 23002, query: "" };
       await b.change({ target: node({ "data-pb-deny-key": "model:srv:22008" }, null, { checked: true }) });
       await b.change({ target: node({ "data-pb-deny-key": "pool:eco" }, null, { checked: false }) });
       b.denying = null; const idle = await b.toggleDeny("pool:std", true);
       const [c, log2] = board({ fail: true }); c.denying = { port: 23002, query: "" }; const refused = await c.toggleDeny("pool:std", true);
       return [log.calls, log.applied.length, idle, log.calls.length, refused, log2.notes]; })()""",
     '[[["/api/consumers/deny",{"port":23002,"deny":["pool:eco","model:srv:22008"]}],["/api/consumers/deny",{"port":23002,"deny":[]}]],2,null,2,null,["controller is down"]]',
     "галка в окне сохраняется сразу: запреты клиента с этим ключом или без него (/api/consumers/deny), доска рисуется с ответом; negative: окно закрыто — ничего; "
     "отказ контроллера — тост с его словами"),
    ("deny_window_opens_and_closes",
     '',
     r"""await (async () => { const [b] = board(); const card = node({ "data-pb-client": "23002" });
       await b.click({ target: node({ "data-pb-deny-open": "" }, card), stopPropagation() {} }); const opened = b.denying;
       const e = { key: "Escape", defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } }; const byEsc = [b.escape(e), b.denying, e.defaultPrevented];
       b.denying = { port: 23002, query: "" }; await b.click({ target: node({ "data-pb-deny": "" }), stopPropagation() {} }); const byBackdrop = b.denying;
       b.denying = { port: 23002, query: "" }; await b.click({ target: node({}, node({ "data-pb-deny-close": "" })), stopPropagation() {} }); const byDone = b.denying;
       b.denying = { port: 23002, query: "" }; await b.click({ target: node({}, node({ "data-pb-deny": "" })), stopPropagation() {} }); const inside = b.denying;
       b.denying = null; const nobody = b.openDeny("4242");
       return [opened, byEsc, byBackdrop, byDone, inside, nobody, b.denying]; })()""",
     '[{"port":23002,"query":""},[true,null,true],null,null,{"port":23002,"query":""},null,null]',
     "«＋ Запретить» на карточке открывает окно этого клиента; закрывают его Esc, щелчок мимо окна и «Готово»; negative: щелчок внутри окна его не закрывает; "
     "клиента, которого нет, окно не открывает"),
    # The move to clients without sets (rust/crates/admin/src/cloud/entry_move.rs): the window shown once, and the twins it deletes.
    ("move_window",
     'st.topology.entryMove = { clients: [{ name: "Hermes", port: 23001, had: "Standart set" }, { name: "Bot", port: 23002, had: "" }],'
     ' sets: [{ name: "Standart set", pools: ["Standart"] }, { name: "Empty", pools: [] }], sees: 5,'
     ' twins: [{ id: "gpt-sol", name: "gpt-sol", where: "sub" }, { id: "coder", name: "Coder", where: "box" }] };',
     r"""await (async () => { const [b, log] = board(); const h = b.moveHtml(); const text = (x) => x.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
       const rows = (h.match(/<tr data-t="pb-move-client"[^>]*>.*?<\/tr>/g) || []).map(text);
       const twins = [...h.matchAll(/data-t="pb-move-twin" data-t-id="([^"]+)"><input type="checkbox" data-pb-move-twin="[^"]+"( checked)?>/g)].map((x) => [x[1], !!x[2]]);
       const where = text((h.match(/<label class="pb-deny-item" data-t="pb-move-twin" data-t-id="coder">.*?<\/label>/) || [""])[0]);
       const button = { textContent: "", disabled: false }; b.root = { querySelector: (s) => (s === "[data-pb-move-delete]" ? button : null) };
       await b.change({ target: node({ "data-pb-move-twin": "coder" }, null, { checked: false }) }); const one = [button.textContent, button.disabled, [...b.moveKept]];
       await b.answerMove(true);
       return [h.includes(">" + esc(en.pbMoveTitle) + "<"), h.includes(esc(fill(en.pbMoveLead, { n: "5" }))), rows, h.includes(esc(fill(en.pbMoveSets, { sets: "Standart set (Standart); Empty" }))),
         twins, where, h.includes(">" + esc(fill(en.pbMoveDelete, { n: "2" })) + "<"), one, log.calls, log.notes]; })()""",
     json.dumps([True, True, ["Hermes Standart set Sees all 5", "Bot nothing Sees all 5"], True, [["gpt-sol", True], ["coder", True]], "Coder Box", True,
                 ["Delete ticked (1)", False, ["coder"]], [["/api/pools/delete", {"id": "gpt-sol"}], ["/api/entry-move/seen", {}]], ["Deleted: gpt-sol"]]),
     "окно переезда, один раз: каждый клиент — что у него было и что он видит теперь, какие наборы ушли (с их пулами), и пулы-двойники — по одной строке, названные как "
     "их модель, с тем, где модель стоит, — отмечены к удалению (владелец: «удали»); снятая галка оставляет пул, и кнопка говорит, сколько уйдёт; ответ удаляет "
     "отмеченные по одному и помечает переезд увиденным"),
    ("move_window_keep_and_failures",
     'st.topology.entryMove = { clients: [], sets: [], sees: 5, twins: [{ id: "gpt-sol", name: "gpt-sol", where: "sub" }] };',
     r"""await (async () => { const [b, log] = board(); await b.answerMove(false); const kept = log.calls.slice();
       const [c, log2] = board(); c.call = async (path, o) => { log2.calls.push([path, JSON.parse(o.body)]); if (path === "/api/pools/delete") throw new Error("1 cable leads to it");
         return { ok: true, topology: { marker: 1 } }; };
       await c.answerMove(true);
       st.topology.entryMove = { clients: [], sets: [], sees: 5, twins: [] }; const [d] = board(); const none = d.moveHtml();
       st.topology.entryMove = null; const [e] = board();
       return [kept, log2.calls, log2.notes, none.includes('data-t="pb-move-done"'), none.includes("data-pb-move-delete"), e.moveHtml()]; })()""",
     '[[["/api/entry-move/seen",{}]],[["/api/pools/delete",{"id":"gpt-sol"}],["/api/entry-move/seen",{}]],["Not deleted: gpt-sol: 1 cable leads to it"],true,false,""]',
     "«Оставить всё» ничего не удаляет и только помечает переезд увиденным; пул, который контроллер не удалил (его держат канаты), остаётся, и тост говорит почему; "
     "двойников нет — одна кнопка «Готово»; negative: переезд уже увиден — окна нет"),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    node = find_node()
    if node is None:
        print("js pool board: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.stack || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_pool_board.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            probe_args(node, harness, path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print(f"js pool board FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("Маршрутизация: клиенты, пулы, модели и канаты между ними:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:400]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:400]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js pool board OK: настоящий модуль в node, {len(PINS)} пинов значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
