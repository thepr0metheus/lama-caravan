#!/usr/bin/env python3
"""Snapshot of static/js/pool-board.js — Routing as three columns (the owner, 2026-10-12).

Pinned by value, with the module loaded for real (scripts/_js_harness.mjs): the
client cards and their one cable to a pool, or none; a pool's rows of three
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
from _node import find_node, node_search_paths  # noqa: E402

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
const fill = (s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => v[k]);
const TOPO = () => ({
  proxies: [
    { id: "ctl:proxy:23001", port: 23001, kind: "consumer", label: "Hermes", keyTail: "a1b2", set: "std-set", setName: "Standart set", models: ["Standart"] },
    { id: "ctl:proxy:23002", port: 23002, kind: "consumer", label: "Bot", keyTail: "c3d4", set: "", setName: "", models: [], mode: "paused" },
    { id: "ctl:proxy:23050", port: 23050, label: "old agent" }],
  cloudAccounts: [
    { id: "sub", name: "ChatGPT", accountType: "openai-subscription", hasCredential: true },
    { id: "or", name: "OpenRouter", type: "openrouter", hasCredential: true }],
  sets: [{ id: "std-set", name: "Standart set", pools: ["std"] }, { id: "empty", name: "Empty", pools: [] }],
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
    { id: "srv:22008", upstreamType: "llama", upstreamHost: "10.0.0.5", upstreamPort: 22008, label: "Coder :22008" },
    { id: "srv:22009", upstreamType: "llama", upstreamHost: "10.0.0.5", upstreamPort: 22009, label: "Gemma :22009" },
    { id: "srv:22010", upstreamType: "llama", upstreamHost: "10.0.0.5", upstreamPort: 22010, label: "Big :22010" },
    { id: "srv:22011", upstreamType: "llama", upstreamHost: "10.0.0.5", upstreamPort: 22011, label: "Small :22011" },
    { id: "cb:std", upstreamType: "cloud", providerId: "std" }] }],
  nodes: [{ id: "box", servers: [
    { port: 22008, phase: "running", cellLabel: "Coder" }, { port: 22009, phase: "stopped", cellLabel: "Gemma" },
    { port: 22010, phase: "stopped", cellLabel: "Big" }, { port: 22011, phase: "error", cellLabel: "Small" }] }],
});
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
const SPOTS = { '[data-pb-client="23001"] [data-pb-out]': [100, 50], '[data-pb-set="std-set"] > [data-pb-in]': [200, 40],
  '[data-pb-set="std-set"] [data-pb-set-pool="std"] [data-pb-set-out]': [250, 60], '[data-pb-pool="std"] > [data-pb-in]': [300, 20],
  '[data-pb-pool="std"] [data-pb-row="sub"] [data-pb-out]': [500, 60], '[data-pb-pool="std"] [data-pb-row="r1"] [data-pb-out]': [500, 90],
  '[data-pb-key="acc:sub/gpt-sol"] [data-pb-in]': [700, 30], '[data-pb-key="out:srv:22008"] [data-pb-in]': [700, 200] };
const rigged = (b) => {
  const svg = { innerHTML: "" }; const dots = {};
  for (const [sel, [left, top]] of Object.entries(SPOTS)) dots[sel] = node({}, null, R(left, top));
  const cols = { ...R(0, 0), querySelector: (s) => (s === "[data-pb-cables]" ? svg : dots[s] || null) };
  b.root = { querySelector: (s) => (s === "[data-pb-cols]" ? cols : null) };
  return { svg, dots };
};
// One request of the monitor, by the port it came in by (Hermes, 23001, is the client of the set that has the pool Standart).
const RUN = (item, port = 23001) => ({ [String(port)]: { port, active: [{ phase: "running", port, ...item }], recent: [] } });
const SAW = (item, port = 23001) => ({ [String(port)]: { port, active: [], recent: [{ port, ...item }] } });
// The part of the drawing between two markers: one card, one row.
const part = (h, from, to = "</article>") => { const i = h.indexOf(from); return i < 0 ? "" : h.slice(i, h.indexOf(to, i) + to.length); };
// One whole item of a list drawn as HTML — a pool's row, a model's row — found by what it contains.
const item = (h, start, has) => h.split(start).slice(1).map((x) => start + x).find((x) => x.includes(has)) || "";
const keys = (h, prefix) => (h.match(new RegExp(`data-pb-key="${prefix}([^"]+)"`, "g")) || []).map((x) => x.slice(`data-pb-key="${prefix}`.length, -1));
const reset = () => { st.setTopology(TOPO()); globalThis.__usage.clear(); globalThis.__seen.clear(); globalThis.__drag.active = false; globalThis.__drag.deferred = false; };
reset();
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
     '(() => { const [b] = board(); const h = b.clientsHtml(); const her = part(h, \'data-pb-client="23001"\'), bot = part(h, \'data-pb-client="23002"\');'
     ' return [her.includes(\'data-t-state="cabled"\'), her.includes("🔑 …a1b2"), her.includes(\'class="pb-dot out" data-pb-out="client" data-port="23001"\'),'
     ' bot.includes(\'data-t-state="none"\'), bot.includes(en.pbClientNoSet), bot.includes(\'class="pb-dot out open"\'), h.includes("pb-client paused"),'
     ' h.includes("old agent"), h.indexOf(">Bot<") < h.indexOf(">Hermes<")]; })()',
     '[true,true,true,true,true,true,true,false,true]',
     "клиент с набором — гнездо каната; без набора — сказано «нет набора», гнездо пунктиром; на паузе — блеклый; по имени; "
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
       const order = ["pb-card-grip", 'class="pb-pool-id"', "data-pb-pool-name", 'data-t="pb-pool-turns"', 'data-t="pb-kind"', "data-pb-pool-delete"].map(at);
       return [order.every((x, i) => x > 0 && (i === 0 || x > order[i - 1]))]; })()""",
     r'''[true]''',
     "голова пула, как в макете: ручка, «id:», имя, справа «⇣ N по очереди», после неё знаки работы, ✕ последним"),
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
    ("the_four_columns_carry_the_marks_their_scroll_is_kept_by",
     '',
     r"""(() => { const [b] = board(); const h = b.inner();
       return [...h.matchAll(/<div class="pb-col-body"([^>]*)>/g)].map((m) => (m[1].match(/data-pb-scroll="([^"]+)"/) || [])[1] || null); })()""",
     '["clients","sets","pools","models"]',
     "the body of each of the four columns carries the mark its scroll is kept by across drawings (data-pb-scroll), in the order they stand: a body with no mark "
     "would go back to its top with every reading that lands; negative: no fifth mark — nothing else in the board is a body that scrolls"),
    ("a_column_is_its_head_and_its_body",
     '',
     r"""(() => { const [b] = board(); return [b.clientsHtml(), b.setsHtml(), b.poolsHtml(), b.modelsHtml()].map((h) => {
       const body = h.indexOf('<div class="pb-col-body"');
       return [h.indexOf('<div class="pb-col-head">') === 0, body > 0, (h.match(/class="pb-col-head"/g) || []).length, (h.match(/class="pb-col-body"/g) || []).length, h.slice(body).includes("pb-col-head")]; }); })()""",
     '[[true,true,1,1,false],[true,true,1,1,false],[true,true,1,1,false],[true,true,1,1,false]]',
     "each column is its head, first, and its body, after it: one of each, and the head is not in the body — what scrolls is the body, and the head stands over it, always shown "
     "(the owner, 2026-10-18: \"the headings outside the area I scroll\"); negative: no head inside the body, no second body"),
    ("the_heads_tools_stand_with_the_head",
     '',
     r"""(() => { const [b] = board(); const head = (h) => h.slice(0, h.indexOf('<div class="pb-col-body"')), body = (h) => h.slice(h.indexOf('<div class="pb-col-body"'));
       const sets = b.setsHtml(), pools = b.poolsHtml();
       return [head(sets).includes("data-pb-add-set"), head(pools).includes("data-pb-add-pool"), head(pools).includes("data-pb-arrange"),
         body(sets).includes("data-pb-add-set"), body(pools).includes("data-pb-add-pool") || body(pools).includes("data-pb-arrange")]; })()""",
     '[true,true,true,false,false]',
     "the buttons that make a set or a pool and the one that arranges the pools are in their column's head, outside what scrolls: they are at hand however far the column is "
     "scrolled; negative: none of them is in a body"),
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
     '[["clients","sets","pools",null],false,1]',
     "the list a card is carried along (data-pb-list) is the body, where the cards are and its offsets are measured from (step-carry.js): clients, sets, pools; the models' "
     "column is no list; negative: no section carries a list or a scroll mark of its own; the pools' drop mark stays on the whole column, so a cable let go over its head makes a pool too"),
    ("an_empty_column_keeps_its_head_and_says_so_in_its_body",
     'st.setTopology({ proxies: [], cloudAccounts: [], sets: [], pools: [], routers: [{ id: "router:default", outputs: [] }], nodes: [] });',
     r"""(() => { const [b] = board(); return [b.clientsHtml(), b.setsHtml(), b.poolsHtml(), b.modelsHtml()].map((h) => {
       const cut = h.indexOf('<div class="pb-col-body"'), said = /data-t="pb-no-(?:clients|sets|pools|models)"/;
       return [h.indexOf('<div class="pb-col-head">') === 0, said.test(h.slice(cut)), said.test(h.slice(0, cut))]; }); })()""",
     '[[true,true,false],[true,true,false],[true,true,false],[true,true,false]]',
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
     '(() => { const [b] = board(); const svg = { innerHTML: "" }; const at = {'
     ' "[data-pb-cables]": svg, \'[data-pb-client="23001"] [data-pb-out]\': R(100, 50), \'[data-pb-set="std-set"] > [data-pb-in]\': R(200, 40),'
     ' \'[data-pb-set="std-set"] [data-pb-set-pool="std"] [data-pb-set-out]\': R(250, 60), \'[data-pb-pool="std"] > [data-pb-in]\': R(300, 20),'
     ' \'[data-pb-pool="std"] [data-pb-row="sub"] [data-pb-out]\': R(500, 60), \'[data-pb-pool="std"] [data-pb-row="r1"] [data-pb-out]\': R(500, 90),'
     ' \'[data-pb-key="acc:sub/gpt-sol"] [data-pb-in]\': R(700, 30), \'[data-pb-key="out:srv:22008"] [data-pb-in]\': R(700, 200),'
     ' \'[data-pb-pool="eco"] [data-pb-row="sub"] [data-pb-out]\': R(500, 300) };'
     ' const cols = { ...R(0, 0), querySelector: (s) => at[s] || null }; b.root = { querySelector: (s) => (s === "[data-pb-cols]" ? cols : null) };'
     ' const n = b.drawCables(); return [n, (svg.innerHTML.match(/<g [^>]*>/g) || []), (svg.innerHTML.match(/class="pb-cable[^"]*"/g) || []), b.drops]; })()',
     '[4,["<g data-pb-cable=\\"client\\" data-port=\\"23001\\" data-pb-cable-key=\\"client:23001\\">",'
     '"<g data-pb-cable=\\"set\\" data-set=\\"std-set\\" data-pool=\\"std\\" data-pb-cable-key=\\"set:std-set/std\\">",'
     '"<g data-pb-cable=\\"row\\" data-pool=\\"std\\" data-row=\\"sub\\" data-pb-cable-key=\\"row:std/sub\\">",'
     '"<g data-pb-cable=\\"row\\" data-pool=\\"std\\" data-row=\\"r1\\" data-pb-cable-key=\\"row:std/r1\\">"],'
     '["class=\\"pb-cable-hit\\"","class=\\"pb-cable\\"","class=\\"pb-cable-hit\\"","class=\\"pb-cable\\"","class=\\"pb-cable-hit\\"","class=\\"pb-cable\\"","class=\\"pb-cable-hit\\"","class=\\"pb-cable lit\\""],'
     '[{"what":"pool eco row sub -> acc:sub/gpt-luna","from":true,"to":false}]]',
     "канат клиента к набору, канаты набора к пулам и канаты строк к моделям, у каждого невидимый широкий двойник для щелчка; канат служащей строки горит; "
     "у каждого — ключ для подсветки пути и больше ничего: цвета у каната нет, он один на всю доску (1.3.531); "
     "defect-class: канат к модели, которой нет на экране, назван в drops, а не пропал молча; negative: у строки без каната и у строки к пропавшей "
     "ячейке канатов нет — и в drops их нет"),
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
         look(RUN({ cloudPoolId: "std", poolStepId: "sub" }, 23999)), look(undefined)]; })()""",
     json.dumps([
         [['class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"', 'class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"',
           'class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"', 'class="pb-cable lit"'], 6],
         [['class="pb-cable lit"', 'class="pb-cable lit"', 'class="pb-cable lit"', 'class="pb-cable lit"'], 0],
         [['class="pb-cable"', 'class="pb-cable"', 'class="pb-cable"', 'class="pb-cable lit"'], 0],
         [['class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"', 'class="pb-cable"', 'class="pb-cable"', 'class="pb-cable lit"'], 2],
         [['class="pb-cable"', 'class="pb-cable"', 'class="pb-cable lit"', 'class="cable-flow fwd rising"', 'class="cable-flow back rising"', 'class="pb-cable lit"'], 2],
         [['class="pb-cable"', 'class="pb-cable"', 'class="pb-cable"', 'class="pb-cable lit"'], 0]]),
     "запрос Hermes идёт через пул Standart строкой sub — горят и несут капли три его каната: клиента, набора к пулу и строки к модели; два конца каждого — шесть точек — в кольце; "
     "канат служащей строки r1 горит и без запроса, без капель; "
     "запрос закончился 2 с назад — горят те же три, без капель и без колец; "
     "negative: запрос в очереди не идёт — ничего не горит, кроме служащей строки; пул, которого на доске нет, зажигает канат клиента и только его (две точки); "
     "запрос порта, который не клиент набора, зажигает строку и больше ничего (две точки); монитор молчит — как до 1.3.549"),
    ("the_cables_are_named_for_their_story",
     '',
     r"""(() => { const keys = (agents) => { CableFlow.reset(); const [b] = board({ agents: () => agents }); rigged(b); b.drawCables(); return [...CableFlow.seen.keys()].sort(); };
       return [keys(RUN({ cloudPoolId: "std", poolStepId: "sub" })), keys(undefined)]; })()""",
     '[["pb:client:23001","pb:row:std/sub","pb:set:std-set/std"],[]]',
     "у каждого каната, что несёт запрос, свой ключ — по нему капли помнят, что кабель нёс: клиента, набора к пулу и строки к модели, у каждого с приставкой доски (pb:), "
     "чтобы их не спутать с канатами главной доски (main:); negative: монитор молчит — ключей нет"),
    ("draw_cables_lets_the_drops_of_a_request_that_ended_go_down",
     '',
     r"""(() => { let t = 1000000, rows = RUN({ cloudPoolId: "std", poolStepId: "sub" }); const [b] = board({ agents: () => rows, now: () => t }); const { svg } = rigged(b);
       const way = () => (svg.innerHTML.match(/class="cable-flow(?= )[^"]*"/g) || []).map((c) => c.split(" ").slice(2).join(" ").replace('"', ""));
       const count = (list, word) => list.filter((c) => c === word).length;
       b.drawCables(); const first = way(); t += 100; rows = SAW({ cloudPoolId: "std", poolStepId: "sub", finishedAt: 998 }); b.drawCables(); const second = way();
       const lastLine = svg.innerHTML.lastIndexOf('class="pb-cable lit"') < svg.innerHTML.indexOf("fading");
       t += 400; b.drawCables(); const third = way(); t += 600; b.drawCables(); const fourth = way(); t += 5000; rows = SAW({ cloudPoolId: "std", poolStepId: "sub", finishedAt: 990 }); b.drawCables();
       return [[count(first, "rising"), first.length], [count(second, "fading"), second.length, lastLine], [count(third, "fading"), third.length], fourth.length, way().length]; })()""",
     '[[6,6],[6,6,true],[6,6],0,0]',
     "канаты, по которым только что шёл запрос, не гасят капли разом: в перерисовке, где запрос уже закончился, каждый из трёх каналов несёт пару капель-призраков (fading), "
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
     '[6,0,6,false,true]',
     "пока идёт запрос, шесть точек трёх канатов в кольце; запрос кончился — кольца сняты у всех (у одной и той же доски, что нарисовала их): канаты горят, а кольцо — у тех, по кому идёт сейчас; "
     "negative: пошёл другой запрос того же клиента — точки его строки (r1) в кольце, а точка строки sub, что служила прежнему, — уже нет"),
    ("flow_now_reads_the_boards_clients_and_pools",
     '',
     r"""(() => { const [b] = board({ agents: () => RUN({ cloudPoolId: "std", poolStepId: "r1" }) }); const f = b.flowNow(); const none = board()[0].flowNow();
       return [[...f.active].sort(), [...f.recent], f.signature, [...none.active], none.signature]; })()""",
     json.dumps([["client:23001", "row:std/r1", "set:std-set/std"], [], "client:23001|row:std/r1|set:std-set/std~", [], "~"]),
     "доска читает монитор по своим клиентам (порт — набор) и пулам; negative: без монитора — ничего и подпись «~»"),
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
       const cols = ["clients", "sets", "pools", "models"].map(mk); const root = { querySelectorAll: (s) => (s === "[data-pb-scroll]" ? cols : []) };
       m.PoolBoard.scrollColumns(root, { clients: 0, pools: 120, models: 15 }); return cols.map((c) => [c.scrollTop, [...c.names]]); })()""",
     '[[0,[]],[0,[]],[120,["scrolled"]],[15,["scrolled"]]]',
     "колонка, нарисованная заново, встаёт на своё место и сразу несёт метку scrolled — не со следующим событием прокрутки, иначе голова на кадр оставалась бы без полосы; "
     "negative: колонка, что стояла наверху, и колонка, о которой ничего не сказано, остаются как есть"),
    ("the_board_listens_for_the_monitor",
     '',
     r"""(() => { globalThis.__seen.clear(); const [b] = board(); let painted = 0; b.paintFlow = () => { painted += 1; }; const c = { dataset: {}, addEventListener() {}, querySelector: () => null };
       b.mount(c); const told = globalThis.__seen.size; [...globalThis.__seen].forEach((f) => f()); b.mount(c); return [told, painted, globalThis.__seen.size]; })()""",
     '[1,1,1]',
     "доска один раз просит, чтобы ей говорили, что монитор прочитан, — и тогда рисует капли; negative: страница рисует доску заново много раз, а слушатель всё один"),
    # ── what the operator does ──
    ("drop_client_on_a_set",
     '',
     'await (async () => { const set = node({ "data-pb-set": "std-set" }); const inside = node({}, set); const [b, log] = board({ at: () => inside });'
     ' const dot = node({ "data-pb-out": "client", "data-port": "23002" }, null, { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });'
     ' b.press({ target: dot, button: 0, pointerId: 1, preventDefault() {} }); const held = b.busy; b.follow({ pointerId: 1, clientX: 40, clientY: 5 });'
     ' await b.release({ type: "pointerup", pointerId: 1, clientX: 40, clientY: 5 });'
     ' return [held, b.busy, log.calls, log.applied]; })()',
     '[true,false,[["/api/consumers/set",{"port":23002,"set":"std-set"}]],[{"marker":1}]]',
     "канат клиента, отпущенный над набором, — один запрос: набор клиента; пока канат в руке, доска держит перерисовку"),
    ("drop_set_on_a_pool",
     '',
     'await (async () => { let under = node({}, node({ "data-pb-pool": "eco" })); const [b, log] = board({ at: () => under });'
     ' const dot = node({ "data-pb-out": "set" }, node({ "data-pb-set": "empty" }), { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });'
     ' b.press({ target: dot, button: 0, pointerId: 7, preventDefault() {} }); b.follow({ pointerId: 7, clientX: 40, clientY: 5 }); await b.release({ type: "pointerup", pointerId: 7, clientX: 40, clientY: 5 });'
     ' under = node({ "data-pb-set": "std-set" });'
     ' b.press({ target: dot, button: 0, pointerId: 8, preventDefault() {} }); b.follow({ pointerId: 8, clientX: 40, clientY: 5 }); await b.release({ type: "pointerup", pointerId: 8, clientX: 40, clientY: 5 });'
     ' return log.calls; })()',
     '[["/api/sets/add-pool",{"id":"empty","pool":"eco"}]]',
     "канат от точки внизу набора, отпущенный над пулом, — пул становится моделью набора; negative: над набором — ничего"),
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
     'await (async () => { let target = null; const [b, log] = board({ at: () => target }); const box = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) };'
     ' const grab = (attrs, kind, parent) => { const g = node({ "data-pb-grab": "", ...attrs }, parent); const dot = node({ "data-pb-out": kind }, g, box);'
     ' g.querySelector = (sel) => (sel === "[data-pb-out]" ? dot : null); return [g, node({}, g)]; };'
     ' const [poolGrab, poolLabel] = grab({ "data-t": "pb-add-row" }, "new-row", node({ "data-pb-pool": "std" }));'
     ' const [, setLabel] = grab({ "data-t": "pb-set-add" }, "set", node({ "data-pb-set": "empty" }));'
     ' const carry = async (from, over, id) => { target = over; b.press({ target: from, button: 0, pointerId: id, preventDefault() {} }); const held = b.busy;'
     ' b.follow({ pointerId: id, clientX: 30, clientY: 1 }); await b.release({ type: "pointerup", pointerId: id, clientX: 30, clientY: 1 }); return held; };'
     ' const held = await carry(poolLabel, node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-astra", "data-name": "gpt-astra" }), 1);'
     ' await carry(poolGrab, node({ "data-pb-model": "", "data-output": "srv:22009", "data-name": "Gemma" }), 2);'
     ' await carry(setLabel, node({}, node({ "data-pb-pool": "eco" })), 3);'
     ' await carry(poolLabel, node({}), 4); await carry(poolLabel, null, 5);'
     ' await b.click({ target: poolLabel, stopPropagation() {} }); await b.click({ target: setLabel, stopPropagation() {} });'
     ' return [held, log.calls, b.busy]; })()',
     '[true,[["/api/pools/add-row",{"poolId":"std","target":{"accountId":"sub","model":"gpt-astra"},"nameAfter":"gpt-astra"}],'
     '["/api/pools/add-row",{"poolId":"std","target":{"output":"srv:22009"},"nameAfter":"Gemma"}],["/api/sets/add-pool",{"id":"empty","pool":"eco"}]],false]',
     "«＋ строка» пула и «＋ модель» набора тянут новый канат с любой точки строки, не только с точки (владелец, 2026-10-12): "
     "строка пула над моделью — одна запись, новая строка сразу с канатом (/api/pools/add-row с целью): к модели подписки — аккаунт "
     "и модель, к ячейке — её выход; набор над пулом — пул в наборе; negative: отпущено мимо модели или ни над чем — ничего не "
     "послано, открытой строки не осталось; щелчок по «＋» строке ничего не шлёт (он открывает список мест — пин chooser_*)"),
    ("drop_nowhere_or_cancelled",
     '',
     'await (async () => { let under = node({}); const [b, log] = board({ at: () => under }); const dot = node({ "data-pb-out": "client", "data-port": "23001" }, null, { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });'
     ' b.press({ target: dot, button: 0, pointerId: 3, preventDefault() {} }); b.follow({ pointerId: 3, clientX: 30, clientY: 1 }); await b.release({ type: "pointerup", pointerId: 3, clientX: 30, clientY: 1 });'
     ' under = node({ "data-pb-set": "std-set" });'
     ' b.press({ target: dot, button: 0, pointerId: 4, preventDefault() {} }); b.follow({ pointerId: 4, clientX: 30, clientY: 1 }); await b.release({ type: "pointercancel", pointerId: 4, clientX: 30, clientY: 1 });'
     ' b.press({ target: dot, button: 0, pointerId: 5, preventDefault() {} }); b.follow({ pointerId: 5, clientX: 30, clientY: 1 }); b.onKey({ key: "Escape" }); const afterEsc = b.busy;'
     ' b.press({ target: dot, button: 2, pointerId: 6, preventDefault() {} }); return [log.calls.length, afterEsc, b.busy]; })()',
     '[0,false,false]',
     "negative: канат, отпущенный мимо набора, отменённый (даже над набором) или брошенный по Esc, ничего не шлёт; правая кнопка каната не начинает"),
    ("cut_cables_after_a_question",
     '',
     'await (async () => { const [b, log] = board({ answers: [false, true, false, true, true] }); const click = (el) => b.click({ target: el, stopPropagation() {} });'
     ' await click(node({ "data-pb-cable": "client", "data-port": "23001" }));'
     ' await click(node({ "data-pb-cable": "client", "data-port": "23001" })); await click(node({ "data-pb-cable": "row", "data-pool": "std", "data-row": "sub" }));'
     ' await click(node({ "data-pb-cable": "row", "data-pool": "std", "data-row": "r1" })); await click(node({ "data-pb-cable": "client", "data-port": "23002" }));'
     ' await click(node({ "data-pb-cable": "set", "data-set": "std-set", "data-pool": "std" })); await click(node({ "data-pb-cable": "set", "data-set": "empty", "data-pool": "std" }));'
     ' return [log.asks.map((a) => [a[0], a[1] === en.pbCutTitle, a[2]]), log.calls]; })()',
     '[[["Take the cable of Hermes away from Standart set? Its requests are refused until it has a set again.",true,true],'
     '["Take the cable of Hermes away from Standart set? Its requests are refused until it has a set again.",true,true],'
     '["Take the cable of row 1 of Standart away from gpt-sol · ChatGPT? The row stays, not connected.",true,true],'
     '["Take the cable of row 2 of Standart away from Coder :22008? The row stays, not connected.",true,true],'
     '["Take Standart out of Standart set? The clients of this set no longer see this model.",true,true]],'
     '[["/api/consumers/set",{"port":23001,"set":""}],["/api/pools/connect-row",{"poolId":"std","rowId":"r1","target":null}],'
     '["/api/sets/remove-pool",{"id":"std-set","pool":"std"}]]]',
     "щелчок по канату — вопрос с обоими концами, потом снятие: клиента — с набора, набора — с пула, строки — с модели; "
     "negative: отказ в вопросе — ничего; у клиента без набора и у набора без этого пула резать нечего"),
    ("sets_column",
     '',
     '(() => { const [b] = board(); const h = b.setsHtml(); const std = part(h, \'data-pb-set="std-set"\'), empty = part(h, \'data-pb-set="empty"\');'
     ' st.setTopology({ ...TOPO(), sets: [] }); const [b2] = board(); const none = b2.setsHtml();'
     ' return [h.includes(`data-pb-add-set data-t="pb-add-set">＋ ${esc(en.pbSetNew)}</button>`), std.includes(\'data-pb-set-name value="Standart set"\'),'
     ' (std.match(/<li class="pb-set-model"[^>]*>.*?<\\/li>/g) || []).map((x) => x.replace(/<[^>]+>/g, "")), std.includes(\'<span class="pb-dot out" data-pb-set-out></span>\'),'
     ' std.includes(\'data-pb-out="set"\'), std.includes(\'data-t="pb-set-add"\'),'
     ' empty.includes(`<div class="pb-new-out" data-pb-grab data-t="pb-set-add" title="${esc(en.pbDragSet)}"><span>＋ ${esc(en.pbSetAddModel)}</span>`'
     ' + `<span class="pb-dot out open" data-pb-out="set" title="${esc(en.pbDragSet)}"></span></div>`),'
     ' empty.includes(esc(en.pbSetEmpty)), none.includes(esc(en.pbNoSets)), none.includes("data-pb-set=")]; })()',
     '[true,true,["Standart"],true,false,false,true,true,true,false]',
     "колонка наборов: ＋ новый набор; у набора имя в поле, его модели — имена пулов, у каждой гнездо каната к пулу; пустой набор так и сказан, "
     "и у него одного на карточке строка «＋ модель» с пунктирной точкой нового каната — её тянут за любую точку; у набора с моделями она в полосе (1.3.533); "
     "negative: наборов нет — сказано, что это и как его сделать"),
    ("pool_kinds",
     'st.topology.pools[0].kind = { jobs: ["llm"], inputs: ["text", "image"] }; st.topology.pools[1].kind = { mixed: true };'
     ' st.topology.pools.push({ id: "ears", name: "Ears", steps: [], kind: { jobs: ["asr"], languages: ["ru"] } },'
     ' { id: "quiet", name: "Quiet", steps: [], kind: null }); st.topology.sets[0].pools.push("ears");',
     '(() => { const [b] = board(); const pools = b.poolsHtml(); const head = (id) => part(pools, `data-pb-pool="${id}"`, "</header>");'
     ' const sets = b.setsHtml(); const row = (pid) => part(sets, `data-pb-set-pool="${pid}"`, "</li>");'
     ' return [head("std").includes(`<span class="pb-kind" data-t="pb-kind" data-t-state="known" title="${esc(en.jobLlm + " · " + en.pbKindPictures)}">💬🖼</span>`),'
     ' head("eco").includes(`<span class="pb-kind mixed" data-t="pb-kind" data-t-state="mixed" title="${esc(en.pbKindMixed)}">⚠</span>`),'
     ' head("ears").includes(`title="${esc(en.jobAsr + " · ru")}">🎧</span>`), head("quiet").includes("pb-kind"),'
     ' row("std").includes(">💬🖼</span>"), row("ears").includes(">🎧</span>"), m.PoolBoard.kindHtml(undefined), m.PoolBoard.kindHtml({ jobs: ["nonsense"] })]; })()',
     '[true,true,true,false,true,true,"",""]',
     "у пула и у строки набора — что делает модель (1.3.502): значки работ и 🖼 у чата с картинками, работа, картинки и "
     "языки — в подсказке; ⚠ — строки пула делают разную работу; negative: вид неизвестен или работы нет в словаре — ничего"),
    ("set_actions",
     '',
     'await (async () => { const [b, log] = board({ answers: [false, true, true], res: { ok: true, set: { id: "Set" }, topology: { marker: 3 } } });'
     ' const field = { did: [], focus() { this.did.push("focus"); }, select() { this.did.push("select"); } };'
     ' b.root = { querySelector: (s) => (s === \'[data-pb-set="Set"] [data-pb-set-name]\' ? field : null) };'
     ' const card = node({ "data-pb-set": "std-set" }); const click = (el) => b.click({ target: el, stopPropagation() {} });'
     ' await click(node({ "data-pb-add-set": "" })); const name = (v) => node({ "data-pb-set-name": "" }, card, { value: v });'
     ' await b.change({ target: name(" Chat ") }); const same = name("Standart set"); await b.change({ target: same }); const blank = name(" "); await b.change({ target: blank });'
     ' await click(node({ "data-pb-set-delete": "" }, card)); await click(node({ "data-pb-set-delete": "" }, card)); await click(node({ "data-pb-set-delete": "" }, node({ "data-pb-set": "empty" })));'
     ' return [log.calls, log.asks.map((a) => a[0]), field.did, blank.value]; })()',
     '[[["/api/sets/create",{}],["/api/sets/rename",{"id":"std-set","name":"Chat"}],["/api/sets/delete",{"id":"std-set"}],["/api/sets/delete",{"id":"empty"}]],'
     '["Delete set Standart set? Hermes lose their models: their requests are refused until they have a set again.",'
     '"Delete set Standart set? Hermes lose their models: their requests are refused until they have a set again.","Delete set Empty?"],["focus","select"],"Standart set"]',
     "＋ новый набор — его имя выбрано в поле, печатать поверх; имя набора сохраняется на месте; ✕ — после вопроса, который называет "
     "клиентов без моделей; negative: то же имя или пустое — ничего, поле возвращает прежнее; отказ в вопросе — ничего"),
    ("probe_model_choice",
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 }; st.topology.clientProbes = [{ path: "/v1/chat/completions", paid: false }];'
     ' Object.assign(st.topology.proxies[0], { models: ["Standart", "Voice"] });',
     'await (async () => { const [b, log] = board(); b.trace = { key: "client:23001", pinned: true }; const hermes = () => part(b.dockHtml(), \'data-pb-client="23001"\', "</aside>");'
     ' const card = node({ "data-pb-client": "23001" }); const shut = hermes(); await b.click({ target: node({ "data-pb-tests": "" }, card), stopPropagation() {} });'
     ' const first = hermes();'
     ' await b.change({ target: node({ "data-pb-probe-model": "" }, card, { value: "Voice" }) }); const chosen = hermes();'
     ' await b.click({ target: node({ "data-pb-probe": "/v1/chat/completions" }, card), stopPropagation() {} });'
     ' return [(first.match(/<option[^>]*>[^<]*<\\/option>/g) || []), chosen.includes(\'<option value="Voice" selected>\'), log.calls[0][1].model,'
     ' part(b.clientsHtml(), \'data-pb-client="23002"\').includes("pb-probe-model"), (first.match(/data-t-id="model"/g) || []).length,'
     ' shut.includes("pb-probe-model"), (shut.match(/data-t-id="model"/g) || []).length]; })()',
     '[["<option value=\\"Standart\\" selected>Standart</option>","<option value=\\"Voice\\">Voice</option>"],true,"Voice",false,2,false,2]',
     "набор из двух моделей — у проверок выбор модели, проверка шлёт выбранную, ссылок GET — по одной на модель; выбор стоит "
     "в свёрнутых проверках и виден, когда они открыты; negative: у клиента без моделей выбора нет"),
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
     'st.topology.entry = { url: "https://caravan-api.example.org/v1", port: 23999 };',
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
     "открывает ответ входа его ключу через контроллер (2026-10-12); у клиента без пула — только список; negative: на карточке клиента ссылок нет; входа нет — нет и адреса, и ссылок"),
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
     r'''["⠿ Hermes 🔑 …a1b2 Models: 1 ⚠ 5","⠿ Bot 🔑 …c3d4 no set Models: 0",[]]''',
     "карточка клиента — имя, хвост ключа, сколько моделей он видит и значок ошибок с числом раз: ни адреса, ни ссылок, ни проверок, ни списка ошибок "
     "(1.3.532); у клиента без набора — «no set» и ноль моделей; negative: у клиента без ошибок значка нет"),
    ("dock_empty_and_aims",
     '',
     r'''(() => { const [b] = board(); const empty = b.dockHtml(); b.trace = { key: "client:99999", pinned: true }; const gone = b.dockHtml(); const aim = (k) => b.dock.constructor.aim(k);
       return [empty.includes('data-t-state="empty"'), / inert[ >]/.test(empty), empty.replace(/<aside[^>]*>/, "").replace("</aside>", "") === "", gone === empty,
         ["client:23001", "set:std-set", "setpool:std-set/std", "pool:std", "row:std/sub", "model:acc:sub/gpt-sol", "nonsense", "", "client:"].map(aim)]; })()''',
     r'''[true,true,true,true,[{"kind":"client","id":"23001"},{"kind":"set","id":"std-set"},{"kind":"set","id":"std-set"},{"kind":"pool","id":"std"},{"kind":"pool","id":"std"},{"kind":"model","id":"acc:sub/gpt-sol"},null,null,null]]''',
     "полоса под доской, когда ничего не выбрано и ни на что не наведено, пуста: ни подсказки, ни слов (владелец, 2026-10-14: «не отображай нижнюю полосу, когда ни на что не наведено или не выбрано»), "
     "и она inert; на карточке, которой уже нет на доске (клиент 99999), — то же самое, не догадка; "
     "ключ пути → о чём полоса: клиент — клиент, строка набора — набор, строка пула — пул, модель — модель; negative: непонятный или пустой ключ — ничего"),
    ("dock_client_strip",
     '',
     r'''(() => { const [b] = board(); const text = (x) => x.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
       const words = (x) => x.replace(en.topologyClientsSection, "{clients}").replace(en.pbSetsSection, "{sets}").replace(en.pbPoolsSection, "{pools}").replace(en.topologyModelsLabel, "{models}");
       b.trace = { key: "client:23001", pinned: false }; const pointed = b.dockHtml(); b.trace = { key: "client:23001", pinned: true }; const pinned = b.dockHtml();
       const route = (h) => (h.match(/<div><dt[^>]*>[^<]*<\/dt><dd[^>]*>[^<]*<\/dd><\/div>/g) || []).map((x) => words(text(x)));
       return [text(part(pinned, '<b class="pb-dock-name"', "</b>")), text(part(pinned, '<span class="pb-dock-sub"', "</span></span>")), route(pinned),
         pointed.includes(esc(en.pbDockPin)), pointed.includes(esc(en.pbDockPinned)), pinned.includes(esc(en.pbDockPinned)), pinned.includes('data-t-state="client"')]; })()''',
     r'''["Hermes","🔑 …a1b2",["{clients} Hermes","{sets} Standart set","{pools} Standart","{models} Coder, gpt-sol"],true,false,true,true]''',
     "полоса клиента: его имя, хвост ключа и путь по колонкам — клиенты, набор, пулы, модели: те, кого зажигает путь под курсором; под курсором внизу «щёлкните, чтобы закрепить», "
     "закреплённая — «закреплено, ещё раз или Esc отпускают»"),
    ("dock_route_says_none",
     '',
     r'''(() => { const [b] = board(); const text = (x) => x.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim(); b.trace = { key: "client:23002", pinned: true };
       const words = (x) => x.replace(en.topologyClientsSection, "{clients}").replace(en.pbSetsSection, "{sets}").replace(en.pbPoolsSection, "{pools}").replace(en.topologyModelsLabel, "{models}");
       return (b.dockHtml().match(/<div><dt[^>]*>[^<]*<\/dt><dd[^>]*>[^<]*<\/dd><\/div>/g) || []).map((x) => words(text(x))); })()''',
     '["{clients} Bot","{sets} —","{pools} —","{models} —"]',
     "уровень пути без имён в полосе говорит «—»: клиент без набора — только он сам, а у набора, пулов и моделей прочерк, не пустое место "
     "(отсутствие названо вслух)"),
    ("dock_route_names_the_account_of_a_twin",
     'st.topology.pools.push({ id: "twin", name: "Twin", steps: [{ id: "a", kind: "account", accountId: "sub", model: "x", enabled: true },'
     ' { id: "b", kind: "account", accountId: "or", model: "x", enabled: true }, { id: "c", kind: "account", accountId: "sub", model: "y", enabled: true }] });',
     r'''(() => { const [b] = board(); const names = (key) => b.routeOf(key).map((l) => l.names); return [names("pool:twin"), names("pool:eco"), names("client:23002")]; })()''',
     r'''[[[],[],["Twin"],["x · ☁ ChatGPT","x · ☁ OpenRouter","y"]],[[],[],["Econom"],["gpt-luna","srv:22999"]],[["Bot"],[],[],[]]]''',
     "путь в именах по колонкам: модель, которую дают два аккаунта, названа с аккаунтом (иначе «x, x»), прочие — просто именем; пул, который никто не зовёт, — "
     "пустой уровень клиентов; клиент без набора — только он сам, остальные уровни пусты (не выдумка); модель, которой нет на доске (srv:22999), названа тем, что в строке"),
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
     r'''(() => { const [b] = board(); const pool = b.poolHtml(st.topology.pools[0]); const set = b.setHtml(st.topology.sets[0]);
       const head = (h) => h.slice(h.indexOf("<header"), h.indexOf("</header>"));
       return [/<span class="pb-pool-id" aria-hidden="true">id:<\/span>\s*<input class="pb-pool-name"/.test(pool), head(pool).indexOf("pb-card-grip") < head(pool).indexOf("pb-pool-id"),
         set.includes("pb-pool-id"), /<input class="pb-pool-name" data-pb-set-name/.test(set)]; })()''',
     '[true,true,false,true]',
     "на карточке пула слева от названия подпись «id:» (владелец, 2026-10-14: «на самом блоке пиши слева от названия id:»): имя пула есть идентификатор модели, который клиент "
     "пишет в поле model; подпись после ручки и прямо перед полем имени, для читалок экрана скрыта (поле имени говорит само); negative: у набора подписи нет — имя набора не идентификатор"),
    ("column_heads_say_id",
     '',
     r'''(() => { const [b] = board(); const head = (h) => (h.match(/<div class="pb-col-head"><span>([^<]*)<\/span>/) || [])[1];
       return [head(b.clientsHtml()) === esc(en.topologyClientsSection), head(b.setsHtml()) === esc(en.pbSetsSection), head(b.poolsHtml()) === esc(en.pbPoolsSection),
         en.pbSetsSection, en.pbPoolsSection, en.topologyLlamaServersSection, head(b.modelsHtml()) === esc(en.topologyModelsLabel)]; })()''',
     r'''[true,true,true,"ID sets","ID (Pools)","Pools",true]''',
     "головы колонок Маршрутизации: клиенты, «ID sets», «ID (Pools)», модели — имя пула есть идентификатор модели, который клиент пишет в поле model (владелец, 2026-10-14); "
     "negative: общее слово «Pools» (карточка Маршрутизации на главной доске, счётчики) прежнее — заголовок колонки взял свой ключ, а не его"),
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
     'await (async () => { const set = node({ "data-pb-set": "std-set" }); const [b, log] = board({ at: () => set });'
     ' const dot = node({ "data-pb-out": "client", "data-port": "23002" }, null, { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });'
     ' const go = async (id, dx) => { b.press({ target: dot, button: 0, pointerId: id, clientX: 10, clientY: 10, preventDefault() {} });'
     ' if (dx) b.follow({ pointerId: id, clientX: 10 + dx, clientY: 10 }); const moved = b.drag.moved;'
     ' await b.release({ type: "pointerup", pointerId: id, clientX: 10 + dx, clientY: 10 }); return moved; };'
     ' const moves = [await go(1, 0), await go(2, 3)]; const quiet = log.calls.length; moves.push(await go(3, 30)); return [moves, quiet, log.calls, b.busy]; })()',
     '[[false,false,true],0,[["/api/consumers/set",{"port":23002,"set":"std-set"}]],false]',
     "нажатие, которое не уехало дальше 5 px, — щелчок, а не канат: над набором отпущено — ничего не послано (щелчок открывает список); "
     "уехало — канат, и он ложится на набор"),
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
     '''await (async () => { const set = node({ "data-pb-set": "std-set" }); const [b] = board({ at: () => set }); const added = [];
       b.win.addEventListener = (type, fn, opts) => { if (type === "click") added.push([fn, opts]); }; b.win.setTimeout = () => 0;
       const dot = node({ "data-pb-out": "client", "data-port": "23002" }, null, { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) });
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
       const src = [S(node({ "data-pb-out": "client", "data-port": "23001" })), S(node({ "data-pb-out": "set" }, node({ "data-pb-set": "std-set" }))),
         S(node({ "data-pb-out": "row" }, row)), S(node({ "data-pb-out": "new-row" }, pool)), S(node({ "data-pb-out": "model" }, acc)),
         S(node({ "data-pb-out": "model" }, cell)), S(node({ "data-pb-out": "model" })), S(node({})), S(null)];
       const places = [P(node({ "data-pb-set": "s" })), P(node({ "data-pb-pool": "p" })), P(acc), P(cell), P(node({ "data-pb-pools-drop": "" })), P(node({})), P(null)];
       const asks = [A("client", { port: 1 }, { set: "s" }), A("set", { setId: "s" }, { pool: "p" }), A("row", { poolId: "p", rowId: "r" }, P(cell)),
         A("new-row", { poolId: "p", rowId: "" }, P(acc)), A("model", src[4].from, { pool: "p" }), A("model", src[5].from, { newPool: true })];
       const none = [A("client", { port: 1 }, { pool: "p" }), A("set", { setId: "s" }, P(acc)), A("model", src[4].from, { set: "s" }),
         A("row", { poolId: "p", rowId: "r" }, { newPool: true }), A("new-row", { poolId: "p" }, { pool: "p" }), A("nope", {}, { set: "s" }), A("client", { port: 1 }, {})];
       return [src, places, asks, none]; })()''',
     '[[{"kind":"client","from":{"port":23001}},{"kind":"set","from":{"setId":"std-set"}},{"kind":"row","from":{"poolId":"std","rowId":"r2"}},'
     '{"kind":"new-row","from":{"poolId":"std","rowId":""}},{"kind":"model","from":{"target":{"accountId":"sub","model":"gpt-sol"},"name":"gpt-sol"}},'
     '{"kind":"model","from":{"target":{"output":"srv:22008"},"name":"Coder"}},null,null,null],'
     '[{"set":"s"},{"pool":"p"},{"target":{"accountId":"sub","model":"gpt-sol"},"name":"gpt-sol"},{"target":{"output":"srv:22008"},"name":"Coder"},{"newPool":true},{},{}],'
     '[["/api/consumers/set",{"port":1,"set":"s"}],["/api/sets/add-pool",{"id":"s","pool":"p"}],'
     '["/api/pools/connect-row",{"poolId":"p","rowId":"r","target":{"output":"srv:22008"},"nameAfter":"Coder"}],'
     '["/api/pools/add-row",{"poolId":"p","target":{"accountId":"sub","model":"gpt-sol"},"nameAfter":"gpt-sol"}],'
     '["/api/pools/add-row",{"poolId":"p","target":{"accountId":"sub","model":"gpt-sol"},"nameAfter":"gpt-sol"}],'
     '["/api/pools/create",{"target":{"output":"srv:22008"},"nameAfter":"Coder"}]],'
     '[null,null,null,null,null,null,null]]',
     "выход говорит, что он начинает: клиент — порт, набор — свой id, строка — пул и строку, «＋» пула — пул без строки, модель — цель и имя, "
     "как его пишет доска; место — набор, пул, модель с именем, колонка пулов — новый пул; одна дверь на канат и на выбор из списка: "
     "клиент → набор, набор → пул, строка → модель (с именем модели), модель → пул или новый пул; negative: выход без карточки модели и "
     "не выход — ничего; место не того рода — ничего не спрашивается"),
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
       const overPool = ["model", "set", "row", "new-row", "client"].map(land); under = inCol; const overColumn = ["model", "set"].map(land); return [overPool, overColumn]; })()''',
     '[["pool","pool",null,null,null],["column",null]]',
     "модель ложится на пул — строкой, а мимо пулов на колонку «Pools» — своим пулом; канат набора — только на пул; "
     "negative: строка и клиент на пул не ложатся, канат набора — на пустое место колонки"),
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
    ("pull_source_place_ask",
     '',
     r"""(() => { const S = m.PoolBoard.source, A = m.PoolBoard.ask, P = m.PoolBoard.placeOf;
       const pool = node({ "data-pb-pool": "std" }); const poolIn = node({ "data-pb-in": "" }, pool);
       const set = node({ "data-pb-set": "std-set" }); const setIn = node({ "data-pb-in": "" }, set);
       const acc = node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-sol", "data-name": "gpt-sol" }); const accIn = node({ "data-pb-in": "" }, acc);
       const cell = node({ "data-pb-model": "", "data-output": "srv:22008", "data-name": "Coder" }); const cellIn = node({ "data-pb-in": "" }, cell);
       const src = [S(poolIn), S(setIn), S(accIn), S(cellIn), S(node({ "data-pb-in": "" })), S(node({}))];
       const places = [P(node({ "data-pb-client": "23001" })), P(node({ "data-pb-set": "s" })), P(node({}))];
       const asks = [A("pull-pool", { poolId: "std" }, { set: "std-set" }), A("pull-set", { setId: "std-set" }, { client: "23001" }), A("pull-set", { setId: "empty" }, { client: "23002" })];
       const none = [A("pull-pool", { poolId: "std" }, { pool: "p" }), A("pull-pool", { poolId: "std" }, { client: "23001" }), A("pull-set", { setId: "s" }, { set: "s" }),
         A("pull-set", { setId: "s" }, {}), A("pull-pool", { poolId: "std" }, {})];
       return [src, places, asks, none]; })()""",
     '[[{"kind":"pull-pool","from":{"poolId":"std"}},{"kind":"pull-set","from":{"setId":"std-set"}},'
     '{"kind":"model","from":{"target":{"accountId":"sub","model":"gpt-sol"},"name":"gpt-sol"}},{"kind":"model","from":{"target":{"output":"srv:22008"},"name":"Coder"}},null,null],'
     '[{"client":"23001"},{"set":"s"},{}],'
     '[["/api/sets/add-pool",{"id":"std-set","pool":"std"}],["/api/consumers/set",{"port":23001,"set":"std-set"}],["/api/consumers/set",{"port":23002,"set":"empty"}]],'
     '[null,null,null,null,null]]',
     "вход карточки — тоже начало каната, который тянут влево: у пула — на набор, у набора — на клиента, у модели — то же, что её ручка "
     "(строка или новый пул); место — теперь ещё клиент; одна дверь: пул → набор — пул в наборе (/api/sets/add-pool), набор → клиент — набор клиента "
     "(/api/consumers/set); negative: вход, которого нет ни на одной карточке, и не вход — ничего; пул на пул, пул на клиента, набор на набор — ничего не спрашивается"),
    ("pull_landing_and_holds",
     '',
     r"""(() => { const setStd = node({ "data-pb-set": "std-set" }), setEmpty = node({ "data-pb-set": "empty" }), hermes = node({ "data-pb-client": "23001" }), bot = node({ "data-pb-client": "23002" });
       const inStd = node({}, setStd), inEmpty = node({}, setEmpty), inHermes = node({}, hermes), inBot = node({}, bot), inPool = node({}, node({ "data-pb-pool": "eco" }));
       let under = inStd; const [b] = board({ at: () => under });
       const land = (kind, from, el) => { under = el; b.drag = { kind, from }; const hit = b.landing(1, 1); b.drag = null;
         return hit === setStd ? "std-set" : hit === setEmpty ? "empty" : hit === hermes ? "hermes" : hit === bot ? "bot" : hit ? "other" : null; };
       return [land("pull-pool", { poolId: "eco" }, inStd), land("pull-pool", { poolId: "eco" }, inEmpty), land("pull-pool", { poolId: "std" }, inStd),
         land("pull-pool", { poolId: "std" }, inEmpty), land("pull-pool", { poolId: "eco" }, inHermes), land("pull-pool", { poolId: "eco" }, inPool),
         land("pull-set", { setId: "empty" }, inHermes), land("pull-set", { setId: "std-set" }, inHermes), land("pull-set", { setId: "std-set" }, inBot),
         land("pull-set", { setId: "std-set" }, inStd)]; })()""",
     '["std-set","empty",null,"empty",null,null,"hermes",null,"bot",null]',
     "пул, потянутый влево, ложится на набор — и на тот, где уже есть модель (на часть, откуда уже идёт связь, ложится ещё одна), и на пустой; "
     "набор — на клиента, и на того, у кого уже есть другой набор (связь заменится: клиент смотрит в один набор); negative: набор, где этот "
     "пул уже есть, и клиент, который уже смотрит в этот набор, — не место: не светятся, и канат над ними ничего не делает; пул на клиента или на пул, "
     "набор на набор — не ложатся"),
    ("pull_a_cable_from_an_input",
     '',
     r"""await (async () => { let under = null; const [b, log] = board({ at: () => under }); const box = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) };
       const poolIn = node({ "data-pb-in": "" }, node({ "data-pb-pool": "eco" }), box);
       const setInEmpty = node({ "data-pb-in": "" }, node({ "data-pb-set": "empty" }), box), setInStd = node({ "data-pb-in": "" }, node({ "data-pb-set": "std-set" }), box);
       const acc = node({ "data-pb-model": "", "data-account": "sub", "data-model": "gpt-astra", "data-name": "gpt-astra" }); const accIn = node({ "data-pb-in": "" }, acc, box);
       acc.querySelector = (s) => (s === "[data-pb-in]" ? accIn : null);
       const setStd = node({ "data-pb-set": "std-set" }), setEmpty = node({ "data-pb-set": "empty" }), hermes = node({ "data-pb-client": "23001" }), bot = node({ "data-pb-client": "23002" });
       const col = node({ "data-pb-pools-drop": "" }); const poolStd = node({ "data-pb-pool": "std" }, col);
       const pull = async (from, over, id) => { under = over; b.press({ target: from, button: 0, pointerId: id, clientX: 0, clientY: 0, preventDefault() {} }); const held = b.busy;
         const anchor = b.drag.dot; b.follow({ pointerId: id, clientX: 50, clientY: 0 }); const kind = b.drag.kind;
         await b.release({ type: "pointerup", pointerId: id, clientX: 50, clientY: 0 }); return [held, kind, anchor === from]; };
       const r = [await pull(poolIn, node({}, setEmpty), 1), await pull(poolIn, node({}, setStd), 2), await pull(setInEmpty, node({}, bot), 3), await pull(setInEmpty, node({}, hermes), 4),
         await pull(setInStd, node({}, hermes), 5), await pull(accIn, node({}, poolStd), 6), await pull(accIn, node({}, col), 7), await pull(poolIn, node({}, poolStd), 8),
         await pull(poolIn, null, 9)];
       return [r, log.calls, b.busy]; })()""",
     '[[[true,"pull-pool",true],[true,"pull-pool",true],[true,"pull-set",true],[true,"pull-set",true],[true,"pull-set",true],[true,"model",true],[true,"model",true],'
     '[true,"pull-pool",true],[true,"pull-pool",true]],'
     '[["/api/sets/add-pool",{"id":"empty","pool":"eco"}],["/api/sets/add-pool",{"id":"std-set","pool":"eco"}],["/api/consumers/set",{"port":23002,"set":"empty"}],'
     '["/api/consumers/set",{"port":23001,"set":"empty"}],'
     '["/api/pools/add-row",{"poolId":"std","target":{"accountId":"sub","model":"gpt-astra"},"nameAfter":"gpt-astra"}],'
     '["/api/pools/create",{"target":{"accountId":"sub","model":"gpt-astra"},"nameAfter":"gpt-astra"}]],false]',
     "канат, потянутый за левую точку: пула на пустой набор и на набор, где уже есть модель, — ещё одна модель набора; набора на клиента без набора и "
     "на клиента с другим — клиент берёт этот набор сразу, прежний уходит; модели на пул — её строка, на колонку «Pools» — свой пул (то же, что за "
     "ручку); канат тянется от самой точки; пока он в руке, доска держит перерисовку; negative: набор на клиента, который уже смотрит в него, пул на "
     "пул и канат, отпущенный мимо, ничего не шлют"),
    ("pull_dot_click_does_nothing",
     '',
     r"""await (async () => { const [b, log] = board(); const box = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) };
       const pool = node({ "data-pb-pool": "eco", "data-pb-node": "pool:eco" }); const dot = node({ "data-pb-in": "" }, pool, box); const body = node({}, pool);
       const pinOnDot = b.pin({ target: dot }); const afterDot = b.trace; const pinOnBody = b.pin({ target: body }); const afterBody = b.trace?.key || null; b.trace = null;
       b.press({ target: dot, button: 0, pointerId: 1, clientX: 0, clientY: 0, preventDefault() {} }); const held = b.busy;
       await b.release({ type: "pointerup", pointerId: 1, clientX: 0, clientY: 0 }); const noCable = b.drag;
       await b.click({ target: dot, stopPropagation() {} });
       b.press({ target: dot, button: 2, pointerId: 2, clientX: 0, clientY: 0, preventDefault() {} });
       return [pinOnDot, afterDot, pinOnBody, afterBody, held, noCable, !!b.chooser, b.busy, log.calls.length]; })()""",
     '[false,null,true,"pool:eco",true,null,false,false,0]',
     "щелчок по левой точке — ничего: ни списка мест, ни закрепления пути карточки (щелчок по самой карточке закрепляет), ни запроса; нажатие без движения "
     "канатом не становится; negative: правая кнопка каната не начинает"),
    ("pull_marks_the_places_that_already_have_it",
     '',
     r"""(() => { const setStd = node({ "data-pb-set": "std-set" }), setEmpty = node({ "data-pb-set": "empty" }), hermes = node({ "data-pb-client": "23001" }), bot = node({ "data-pb-client": "23002" });
       const all = [setStd, setEmpty, hermes, bot]; const [b] = board();
       b.root = { querySelector: () => null, querySelectorAll: (sel) => (sel === "[data-pb-set]" ? [setStd, setEmpty] : sel === "[data-pb-client]" ? [hermes, bot]
         : sel === ".pb-holds" ? all.filter((n) => n.classes.has("pb-holds")) : []) };
       const marked = () => all.filter((n) => n.classes.has("pb-holds")).map((n) => n.dataset.pbSet || n.dataset.pbClient);
       const run = (kind, from) => { b.drag = { kind, from, moved: true }; b.markHolds(); const m = marked(); b.clearHolds(); b.drag = null; return [m, marked()]; };
       return [run("pull-pool", { poolId: "std" }), run("pull-pool", { poolId: "eco" }), run("pull-set", { setId: "std-set" }), run("pull-set", { setId: "empty" }), run("client", { port: 23001 }), run("model", {})]; })()""",
     '[[["std-set"],[]],[[],[]],[["23001"],[]],[[],[]],[[],[]],[[],[]]]',
     "пока канат в руке, место, где уже есть то, что канат дал бы (набор с этим пулом, клиент с этим набором), помечено — на нём нет рамки места посадки; "
     "рука отпущена — метки сняты; negative: набор без этого пула и клиент с другим набором не помечены, а канаты клиента и модели не помечают никого"),
    ("pull_marks_come_with_the_cable_and_go_with_it",
     '',
     r"""await (async () => { const [b] = board(); const box = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }) };
       const setStd = node({ "data-pb-set": "std-set" }), setEmpty = node({ "data-pb-set": "empty" }); const all = [setStd, setEmpty];
       b.root = { querySelector: () => null, querySelectorAll: (sel) => (sel === "[data-pb-set]" ? all : sel === ".pb-holds" ? all.filter((n) => n.classes.has("pb-holds")) : []) };
       const marked = () => all.filter((n) => n.classes.has("pb-holds")).map((n) => n.dataset.pbSet);
       const poolIn = node({ "data-pb-in": "" }, node({ "data-pb-pool": "std" }), box);
       b.press({ target: poolIn, button: 0, pointerId: 1, clientX: 0, clientY: 0, preventDefault() {} }); const pressed = marked();
       b.follow({ pointerId: 1, clientX: 50, clientY: 0 }); const carried = marked();
       await b.release({ type: "pointerup", pointerId: 1, clientX: 50, clientY: 0 }); const letGo = marked();
       b.press({ target: poolIn, button: 0, pointerId: 2, clientX: 0, clientY: 0, preventDefault() {} }); b.follow({ pointerId: 2, clientX: 50, clientY: 0 }); const again = marked();
       b.onKey({ key: "Escape" }); const cancelled = marked();
       return [pressed, carried, letGo, again, cancelled]; })()""",
     '[[],["std-set"],[],["std-set"],[]]',
     "метки «уже есть» ставятся, как только канат пошёл (до этого, пока нажатие не сдвинулось, — нет), и снимаются, когда его отпустили и когда отменили по Esc; "
     "negative: пока нажатие стоит на месте, ни один набор не помечен"),
    ("pull_cable_is_held_by_its_left_end",
     '',
     r"""(() => { const [b] = board(); const svg = { d: "", live: null, querySelector() { return this.live; }, insertAdjacentHTML() { this.live = { setAttribute: (k, v) => { svg.d = v; } }; } };
       const cols = { getBoundingClientRect: () => ({ left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600 }), querySelector: (s) => (s === "[data-pb-live-layer]" ? svg : null) };
       b.root = { querySelector: (s) => (s === "[data-pb-cols]" ? cols : null) };
       const dot = node({ "data-pb-in": "" }, null, { getBoundingClientRect: () => ({ left: 95, top: 500, width: 10, height: 10 }) });
       const go = (kind) => { b.drag = { kind, moved: true, dot, pointer: { x: 400, y: 100 }, over: null }; b.track(); return svg.d.split(" C")[0]; };
       return ["pull-pool", "pull-set", "model", "client", "set", "row", "new-row"].map(go); })()""",
     '["M 400 100","M 400 100","M 400 100","M 100 505","M 100 505","M 100 505","M 100 505"]',
     "канат, потянутый влево, пишется от руки к точке карточки (точка остаётся на месте, рука — слева, как у модели); negative: канат, что тянут от выхода, "
     "идёт от самой точки, как раньше"),
    ("input_dots_are_handles_in_the_markup",
     '',
     r"""(() => { const [b] = board(); const h = b.html(st.topology); const dots = (h.match(/<span class="pb-dot in" data-pb-in[^>]*><\/span>/g) || []);
       const kind = (k) => dots.filter((d) => d.includes(`data-t="pb-pull-${k}"`)).length;
       return [kind("set"), kind("pool"), kind("model") > 0, dots.length === kind("set") + kind("pool") + kind("model"), (h.match(/data-pb-in/g) || []).length === dots.length,
         h.includes(`data-t="pb-pull-pool" title="${esc(en.pbPullPool)}"`), h.includes(`data-t="pb-pull-set" title="${esc(en.pbPullSet)}"`), h.includes(`data-t="pb-pull-model" title="${esc(en.pbPullModel)}"`)]; })()""",
     '[2,2,true,true,true,true,true,true]',
     "у каждого набора (2), каждого пула (2) и каждой строки модели есть левая точка с hover-подсказкой на языке страницы и меткой для тестов "
     "(pb-pull-set, pb-pull-pool, pb-pull-model); negative: голой точки без подсказки не осталось — каждая точка входа ручка"),
    ("chooser_choices",
     '',
     '''(() => { const [b] = board(); const c = (kind, from) => b.choices(kind, from).map((x) => [x.key, x.label, x.hint, x.now, x.to]);
       return [c("client", { port: 23001 }), c("client", { port: 23002 }).map((x) => x[3]), c("set", { setId: "std-set" }),
         c("row", { poolId: "std", rowId: "sub" }).filter((x) => x[3] || /^out:srv:2200[89]$/.test(x[0])), c("row", { poolId: "std", rowId: "sub" }).map((x) => x[0]),
         c("new-row", { poolId: "std", rowId: "" }).filter((x) => x[3]).length, c("model", { target: { accountId: "sub", model: "gpt-sol" }, name: "gpt-sol" }), c("nope", {})]; })()''',
     '[[["set:std-set","Standart set","Standart",true,{"set":"std-set"}],["set:empty","Empty","",false,{"set":"empty"}]],[false,false],'
     '[["pool:std","Standart","gpt-sol, Coder",true,{"pool":"std"}],["pool:eco","Econom","gpt-luna, srv:22999",false,{"pool":"eco"}]],'
     '[["acc:sub/gpt-sol","gpt-sol","☁ ChatGPT",true,{"target":{"accountId":"sub","model":"gpt-sol"},"name":"gpt-sol"}],'
     '["out:srv:22008","Coder","🖥 Box :22008",true,{"target":{"output":"srv:22008"},"name":"Coder"}],'
     '["out:srv:22009","Gemma","🖥 Box :22009",false,{"target":{"output":"srv:22009"},"name":"Gemma"}]],'
     '["acc:sub/gpt-sol","acc:sub/gpt-astra","acc:sub/gpt-luna","out:srv:22008","out:srv:22009","out:srv:22010","out:srv:22011"],2,'
     '[["pool:new","＋ New pool “gpt-sol”","",false,{"newPool":true}],["pool:std","Standart","gpt-sol, Coder",true,{"pool":"std"}],'
     '["pool:eco","Econom","gpt-luna, srv:22999",false,{"pool":"eco"}]],[]]',
     "список мест по щелчку: клиенту — наборы (его набор отмечен), набору — пулы (уже его — отмечены), строке и новой строке — модели "
     "карточек аккаунтов и ячейки всех машин (модели этого пула отмечены: дважды в одном пуле модель пробовалась бы дважды), модели — "
     "сначала свой новый пул, потом пулы (где она уже есть — отмечены); в строке — что внутри: модели пула, пулы набора, аккаунт или "
     "машина с портом; negative: у клиента без набора отметок нет"),
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
       const dot = (left, top) => node({ "data-pb-out": "client", "data-port": "23002" }, null, { getBoundingClientRect: () => ({ left, top, right: left + 12, bottom: top + 12, width: 12, height: 12 }) });
       await b.click({ target: dot(140, 200), stopPropagation() {} }); const opened = [b.chooser, html.includes('style="left: 60px; top: 468px"'), html.includes(esc(en.pbChooseSet)),
         html.includes('data-pb-choose="set:std-set"') && html.includes('data-pb-choose="set:empty"'), field.focused];
       await b.click({ target: dot(1080, 800), stopPropagation() {} }); const up = b.chooser.at;
       const inChooser = (attrs) => node(attrs, node({ "data-pb-chooser": "" }));
       await b.click({ target: inChooser({ "data-pb-choose": "set:empty" }), stopPropagation() {} }); const chosen = [b.chooser, html, log.calls];
       await b.click({ target: dot(140, 200), stopPropagation() {} }); const outside = await b.click({ target: node({}, node({ "data-pb-node": "pool:std" })), stopPropagation() {} });
       return [opened, up, chosen, [outside, b.chooser, b.trace]]; })()''',
     '[[{"kind":"client","from":{"port":23002},"query":"","at":{"x":60,"y":468,"up":false}},true,true,true,true],{"x":692,"y":1044,"up":true},'
     '[null,"",[["/api/consumers/set",{"port":23002,"set":"empty"}]]],[true,null,null]]',
     "щелчок по выходу открывает список мест под ним, в рамке доски с её прокруткой, и ставит фокус в поиск; у нижнего края — вверх, у правого — "
     "прижат внутрь; выбор места — тот же запрос, что канат; щелчок мимо списка закрывает его и ничего больше — путь не закрепляется"),
    ("chooser_refusals",
     '',
     '''await (async () => { const [b, log] = board({ fail: true }); let html = ""; const box = { scrollLeft: 0, scrollTop: 0, clientWidth: 1000,
         getBoundingClientRect: () => ({ left: 0, top: 0, right: 1000, bottom: 800 }), insertAdjacentHTML(_p, h) { html = h; } };
       b.root = { querySelector: (s) => (s === "[data-pb-root]" ? box : s === "[data-pb-chooser]" ? (html ? { remove() { html = ""; } } : null) : null) };
       const dot = node({ "data-pb-out": "client", "data-port": "23001" }, null, { getBoundingClientRect: () => ({ left: 0, top: 0, right: 12, bottom: 12 }) });
       await b.click({ target: dot, stopPropagation() {} }); const now = await b.choose("set:std-set"); const nowCalls = log.calls.length;
       const failed = await b.choose("set:empty"); return [now, nowCalls, failed, log.notes, b.chooser?.kind, html.includes("data-pb-chooser")]; })()''',
     '[null,0,null,["controller is down"],"client",true]',
     "negative: место, куда канат уже идёт, не выбирается — запроса нет; отказ контроллера — тост с его словами, и список возвращается"),
    ("escape_order",
     '',
     '''(() => { const [b] = board(); const esc1 = () => b.escape({ key: "Escape", defaultPrevented: false, preventDefault() {} });
       b.chooser = { kind: "client", from: { port: 1 }, query: "" }; b.trace = { key: "pool:std", pinned: true };
       const r = [esc1(), b.chooser, b.trace?.key, esc1(), b.trace, esc1()];
       b.trace = { key: "pool:std", pinned: true }; const taken = b.escape({ key: "Escape", defaultPrevented: true, preventDefault() {} });
       b.drag = { kind: "client" }; const held = esc1(); b.drag = null; const other = b.escape({ key: "Enter", defaultPrevented: false });
       return [r, taken, held, other, b.trace.pinned]; })()''',
     '[[true,null,"pool:std",true,null,null],null,null,null,true]',
     "Esc закрывает сначала список мест, потом закреплённый путь — по одному на нажатие; negative: Esc, который взяло поле, Esc с канатом "
     "в руке и другая клавиша путь не трогают"),
    ("path_through_cards",
     '',
     '''(() => { const p = (key) => { const r = m.PoolBoard.path(st.topology, key); return [[...r.nodes].sort(), [...r.cables].sort()]; };
       return [p("model:acc:sub/gpt-sol"), p("pool:eco"), p("client:23001"), p("client:23002"), p("row:std/r1"), p("setpool:std-set/std")[1], p(""), p("nonsense")]; })()''',
     '[[["client:23001","model:acc:sub/gpt-sol","pool:std","row:std/sub","set:std-set","setpool:std-set/std"],["client:23001","row:std/sub","set:std-set/std"]],'
     '[["model:acc:sub/gpt-luna","model:out:srv:22999","pool:eco","row:eco/r1","row:eco/sub"],["row:eco/r1","row:eco/sub"]],'
     '[["client:23001","model:acc:sub/gpt-sol","model:out:srv:22008","pool:std","row:std/r1","row:std/r2","row:std/sub","set:std-set","setpool:std-set/std"],'
     '["client:23001","row:std/r1","row:std/sub","set:std-set/std"]],[["client:23002"],[]],'
     '[["client:23001","model:out:srv:22008","pool:std","row:std/r1","set:std-set","setpool:std-set/std"],["client:23001","row:std/r1","set:std-set/std"]],'
     '["client:23001","row:std/r1","row:std/sub","set:std-set/std"],[[],[]],[[],[]]]',
     "путь через карточку — вверх до клиентов и вниз до моделей: модель — её строки, пулы, наборы и клиенты; клиент — всё, что он видит; "
     "строка — её модель и путь её пула вверх; у строки без каната каната нет и в пути; negative: в сторону путь не идёт — соседняя строка, пул без набора и клиент без набора "
     "чужого не зажигают; пустой и непонятный ключ — пусто"),
    ("light_hover_pin",
     '',
     '''(() => { const [b] = board(); const el = (key, attr = "pbNode") => { const e = { dataset: { [attr]: key }, cls: new Set() };
         e.classList = { toggle: (c, on) => (on ? e.cls.add(c) : e.cls.delete(c)) }; return e; };
       const nodes = ["client:23001", "client:23002", "set:std-set", "pool:std", "pool:eco", "row:std/sub", "model:acc:sub/gpt-sol"].map((k) => el(k));
       const cables = ["client:23001", "set:std-set/std", "row:std/sub", "row:eco/sub"].map((k) => el(k, "pbCableKey"));
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
     '[[["tracing"],["client:23001","set:std-set","pool:std","row:std/sub","model:acc:sub/gpt-sol"],["client:23001","set:std-set/std","row:std/sub"]],'
     '[["path-alone","traced","tracing"],["pool:eco"],["row:eco/sub"]],[["path-alone","traced","tracing"],["pool:eco"],["row:eco/sub"]],false,[[],[],[]],[null,[[],[],[]]]]',
     "наведение зажигает путь карточки, остальное отступает (на наведении — только «tracing», других канатов не прячет); щелчок закрепляет путь и оставляет доске только его "
     "канаты (path-alone) — наведение его не сбивает; щелчок по той же карточке отпускает; negative: щелчок по точке выхода путь не закрепляет; с канатом в руке наведение ничего не зажигает"),
    ("a_pinned_path_shows_only_its_own_cables",
     '',
     '''(() => { const [b] = board(); const el = (key, attr = "pbNode") => { const e = { dataset: { [attr]: key }, cls: new Set() };
         e.classList = { toggle: (c, on) => (on ? e.cls.add(c) : e.cls.delete(c)) }; return e; };
       const nodes = ["client:23001", "client:23002", "set:std-set", "pool:std", "pool:eco", "row:std/sub", "model:acc:sub/gpt-sol"].map((k) => el(k));
       const cables = ["client:23001", "set:std-set/std", "row:std/sub", "row:eco/sub"].map((k) => el(k, "pbCableKey"));
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
     "владелец, 2026-10-18; пока карточка в руке (канат тянут), доска показывает все канаты, как всегда, и возвращает путь, когда её опустили; "
     "карточка без канатов (клиент без набора) — путь из неё одной, и рисуются только её канаты, то есть ни одного; negative: закреплённая карточка, которой на доске уже нет, ничего "
     "не прячет — доска только отступает, как отступала (иначе канаты пропали бы без объяснения); наведение без закрепления только отступает, а не прячет; отпущенный путь — классов нет"),
    ("pool_has_no_colour_of_its_own",
     '',
     '''(() => { const [b] = board(); const html = [b.clientsHtml(), b.setsHtml(), b.poolsHtml(), b.modelsHtml()].join("");
       return [typeof b.hueOf, typeof b.hueStyle, /pool-hue|pb-hue/.test(html)]; })()''',
     '["undefined","undefined",false]',
     "negative (1.3.531, владелец: «пёстро»): у пула нет своего цвета — ни метки в голове, ни полосы у строки набора, ни переменной на карточке; "
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
    ("dock_set_strip",
     '',
     r"""(() => { const [b] = board(); const text = (x) => x.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
       b.trace = { key: "set:std-set", pinned: true }; const h = b.dockHtml(); b.trace = { key: "setpool:std-set/std", pinned: false }; const viaPool = b.dockHtml();
       b.trace = { key: "set:empty", pinned: true }; const empty = b.dockHtml(); b.trace = { key: "set:gone", pinned: true }; const gone = b.dockHtml();
       return [text(part(h, '<b class="pb-dock-name"', "</b>")), (h.match(/<li class="pb-dock-model"[^>]*>.*?<\/li>/g) || []).map((x) => [(x.match(/data-t-id="([^"]*)"/) || [])[1], text(x)]),
         h.includes('<div class="pb-dock-set" data-pb-set="std-set" data-t="pb-dock-set">'), h.includes('data-pb-out="set"'), h.includes('data-t="pb-set-add"'),
         viaPool.includes('data-pb-set="std-set"'), empty.includes('data-pb-set="empty"'), empty.includes("pb-new-out"), empty.includes("pb-dock-model"), gone.includes('data-t-state="empty"'), b.dockDetailsHtml({ kind: "set", id: "nope" })]; })()""",
     r'''["Standart set",[["std-set/std","Standart"]],true,true,true,true,true,false,false,true,""]''',
     "полоса набора: его имя, по строке на каждую его модель (имя пула и что он делает) и «＋ модель» с точкой каната; набор, на чьём пуле стоит курсор, показан тем же; "
     "negative: у пустого набора в полосе ни списка, ни «＋ модели» — она на его карточке; набора, которого нет, полоса не показывает — она пуста («empty»)"),
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
         ["client:23001", "set:std-set", "setpool:std-set/std", "pool:eco", "row:std/r2", "model:out:srv:22008", "model:acc:sub/gpt-astra"].filter((k) => !h.includes(`data-pb-node="${k}"`))];
       st.setTopology({ ...st.topology, layout: { clientOrder: [23001, 4242] } }); const ordered = seats(b.html(st.topology)).slice(0, 2);
       return [first, ordered]; })()''',
     '[[["23002","23001","std-set","empty","std","eco"],["data-pb-list=\\"clients\\"","data-pb-list=\\"sets\\"","data-pb-list=\\"pools\\""],6,true,true,[]],["23001","23002"]]',
     "каждая карточка клиентов, наборов и пулов — в своём гнезде с ручкой, колонки — списки для переноса; на колонке пулов — подсказка для "
     "модели; у каждой карточки и строки — ключ пути; клиенты — в порядке оператора, остальные — по имени; negative: порт без клиента "
     "в порядке ничего не рисует"),
    ("card_parts_and_orders",
     '',
     '''await (async () => { const P = m.PoolBoard.CARDS; const card = { id: "c" }; const seat = { dataset: { pbSeat: "eco" }, firstElementChild: card };
       const parts = [P.item, P.list, P.grip, P.idOf(seat), P.ownerOf({ dataset: { pbList: "pools" } }), P.card(seat) === card];
       const timers = []; const [b, log] = board(); b.win.setTimeout = (fn) => timers.push(fn);
       const saved = [await b.saveOrder("pools", ["eco", "std"]), await b.saveOrder("sets", ["empty", "std-set"]), await b.saveOrder("clients", ["23002", "23001"])].map((r) => !!r);
       const quiet = [b.pending, timers.length]; const unknown = await b.saveOrder("nope", ["x"]);
       return [parts, saved, log.calls, quiet, [unknown, log.calls.length, b.pending, timers.length]]; })()''',
     '[[".pb-seat","[data-pb-list]","[data-pb-card-grip]","eco","pools",true],[true,true,true],'
     '[["/api/pools/order",{"ids":["eco","std"]}],["/api/sets/order",{"ids":["empty","std-set"]}],["/api/consumers/order",{"order":[23002,23001]}]],'
     '[false,0],[null,3,true,1]]',
     "перенос карточки: гнездо, колонка, ручка, id карточки и род колонки; новый порядок — дверью своей колонки: пулы и наборы — их id, "
     "клиенты — порты числами; negative: колонка без двери ничего не шлёт, а доска будет нарисована заново"),
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
            [node, "--import",
             f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
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
