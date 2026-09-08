#!/usr/bin/env python3
"""Snapshot of static/js/canvas.js — the baseline for Phase 8 (turning the kanban into classes).

The behaviour is pinned BEFORE the rewrite, by value: helpers (an agent's
group, a pair's primary port, a client's key and name qualified by host,
history formats, gguf's short name, walking edges to a schedule node),
building `canvasNodes` (inputs, rule nodes of every kind with their ports,
the server block, the embeddings slot), graph operations through
`saveRouters` (a schedule node is born with two outputs, one output on an
in:-port is a replacement, inc: expands into a client's ports, queue/onError
roles hold edge pointers and get cleaned up, a rewire inherits schedPortId,
healing accepts the first free edge as main and converges), the grid-save
queue (one request in flight, the latest grid catches up), the node config
panel, geometry (a world point via the offsetParent chain, anchors, the
curve, connectors with `data-t-id="from->to"` and role classes, the cable
while dragging), dragging (a node → position, and a save through saveRouters
for rule:, otherwise localStorage; panning; connect/rewire → an edge onto the
target), spreading out overlaps, the binder (one binding per world
generation, the palette built once, zoom to cursor 0.35–2.2, queue field
clamps).

The DOM is a selector dict and element models with an offsetParent chain;
neighbors are stubs recording their calls; saveRouters applies the mutator to
a copy.

Run: python3 scripts/test_js_canvas.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("dialogs,form,llama-edit,polling,remote-cells,routers,topology-activity,topology-proxies,topology-render,"
         "charts,cables,cloud,history,favorites,config-locator,system-panels,onboarding,onboarding-tours,usage-stats,"
         "dialog-llamas,models-page,system-page,memory,command-preview,topology-nodes,topology-modals,topology-dnd,model-meta")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const i18n = await import(pathToFileURL(process.env.JS_ROOT + "/i18n.js").href);
st.setState({ config: {} }); st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
globalThis.CSS = { escape: (s) => String(s) }; globalThis.MutationObserver = class { observe() {} };
globalThis.__timers = []; globalThis.setInterval = (fn, ms) => { globalThis.__timers.push("interval:" + ms); return 0; }; globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push("timeout:" + ms); globalThis.__deferred.push(fn); return 0; }; globalThis.__deferred = [];
globalThis.requestAnimationFrame = (fn) => { globalThis.__raf.push(fn); return 0; }; globalThis.__raf = [];
const docListeners = {}; document.addEventListener = (t, fn, opts) => { (docListeners[t] ||= []).push({ fn, capture: opts === true }); };
const winListeners = {}; globalThis.addEventListener = (t, fn) => { (winListeners[t] ||= []).push(fn); };
Date.now = () => 1_700_000_100_000; globalThis.Math.random = () => 0.5;
globalThis.__stubValues = { "topology-activity.stickySlotAnims": {} };
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on === undefined ? (s.has(c) ? s.delete(c) : s.add(c)) : (on ? s.add(c) : s.delete(c))), contains: (c) => s.has(c), has: (c) => s.has(c), list: () => [...s].sort() } };
// Элемент мира: offsetParent-цепочка для геометрии, dataset, стиль, слушатели, querySelector по словарю q/qa.
const mkEl = (props = {}) => { const e = { dataset: {}, classList: cls(), style: {}, listeners: {}, offsetLeft: 0, offsetTop: 0, offsetWidth: 100, offsetHeight: 40, offsetParent: null, parentElement: null, innerHTML: "", value: "", textContent: "",
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, closest(sel) { return this.q?.[sel] ?? (this.parentElement ? this.parentElement.closest(sel) : null); }, querySelector(sel) { return this.q?.[sel] ?? null; }, querySelectorAll(sel) { return this.qa?.[sel] ?? []; }, getBoundingClientRect() { return this.rect || { left: 0, top: 0, width: 100, height: 40 }; }, contains: () => false, remove() { this.removed = true; }, ...props }; return e; };
globalThis.__q = {}; globalThis.__qa = {};
document.querySelector = (sel) => (Object.prototype.hasOwnProperty.call(globalThis.__q, sel) ? globalThis.__q[sel] : null);
document.querySelectorAll = (sel) => globalThis.__qa[sel] || [];
document.getElementById = (id) => (Object.prototype.hasOwnProperty.call(globalThis.__fields, id) ? globalThis.__fields[id] : null);
globalThis.__atPoint = null; document.elementFromPoint = () => globalThis.__atPoint;
document.body = { appendChild() {} }; document.createElement = () => mkEl();
globalThis.__calls = [];
const isEventLike = (x) => x && typeof x === "object" && (x.listeners || "target" in x || typeof x.preventDefault === "function");
const arg = (x) => (typeof x === "function" ? "fn" : isEventLike(x) ? null : x);
const rec = (name, ret) => (...a) => { globalThis.__calls.push([name, ...a.map(arg)]); return ret; };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/canvas.js").href);
const names = () => globalThis.__calls.map((c) => c[0]);
const saved = () => globalThis.__calls.filter((c) => c[0] === "saveRouters").map((c) => c[1]);
const lastSaved = () => saved().at(-1);
const PROXIES = () => [
  { id: "skynet:proxy:23001", port: 23001, label: "hermes primary", clientId: "box-a", upstreamHost: "127.0.0.1", upstreamPort: 22001 },
  { id: "skynet:proxy:23002", port: 23002, label: "hermes fallback", clientId: "box-a" },
  { id: "skynet:proxy:23101", port: 23101, label: "crane", clientId: "box-b" },
  { id: "skynet:proxy:8022", port: 8022, label: "promie", clientId: "" },
];
const ROUTER = (extra = {}) => ({ id: "router:a", inputs: ["skynet:proxy:23001", "skynet:proxy:23002", "skynet:proxy:23101"], outputs: [
  { id: "srv:22001", label: "qwen", upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22001 },
  { id: "cb:terra", label: "☁ terra", upstreamType: "cloud", providerId: "cb:terra", accountId: "acct" },
  { id: "srv:22003", label: "embed", upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22003 } ],
  rules: { default: "srv:22001", embeddingsOutput: "", bySource: [] },
  graph: { nodes: [
    { id: "q1", type: "queue", x: 300, y: 100, config: { spillPct: 25, admitEdge: "e1", spillEdge: "e2" } },
    { id: "s1", type: "schedule", x: 300, y: 400, config: { outputs: [{ id: "o1", name: "day" }, { id: "o2", name: "night" }], grid: [[null, "o1"]] } },
    { id: "w1", type: "weighted", x: 300, y: 700, config: { weights: [{ edge: "e5", pct: 70 }] } },
    { id: "f1", type: "failover", x: 300, y: 800, config: { order: [] } },
    { id: "oe1", type: "onError", x: 300, y: 900, config: { mainEdge: "e7", rescueEdge: "e8" } },
    { id: "rt1", type: "requestType", x: 300, y: 1000, config: {} },
    { id: "rs1", type: "requestSize", x: 300, y: 1100, config: { maxTokensAt: 500 } } ],
  edges: [
    { id: "e0", from: "in:skynet:proxy:23001", to: "rule:q1" }, { id: "e1", from: "rule:q1", to: "out:srv:22001" }, { id: "e2", from: "rule:q1", to: "out:cb:terra" },
    { id: "e3", from: "rule:s1", to: "out:srv:22001", schedPortId: "o1" }, { id: "e4", from: "rule:s1", to: "out:cb:terra", schedPortId: "__default__" },
    { id: "e5", from: "rule:w1", to: "out:srv:22001" }, { id: "e6", from: "rule:w1", to: "out:cb:terra" },
    { id: "e7", from: "rule:oe1", to: "out:srv:22001" }, { id: "e8", from: "rule:oe1", to: "out:cb:terra" },
    { id: "e9", from: "rule:rt1", to: "out:srv:22003", schedPortId: "embed" }, { id: "e10", from: "rule:rs1", to: "out:srv:22001", schedPortId: "small" } ] }, ...extra });
const TOPO = (extra = {}) => ({ proxies: PROXIES(), clients: [{ id: "box-a", name: "Box A", agents: [{ id: "hermes" }] }, { id: "box-b", name: "Box B", agents: [{ id: "crane" }] }], routers: [ROUTER()], assignments: {
  "box-a": { assignments: [{ agentId: "hermes", routes: [{ role: "primary", proxyId: "skynet:proxy:23001" }, { role: "fallback", proxyId: "skynet:proxy:23002" }] }] },
  "box-b": { assignments: [{ agentId: "crane", routes: [{ role: "primary", proxyId: "skynet:proxy:23101" }] }] } }, cloudProviders: [{ id: "cb:terra", model: "gpt-5.6-terra", unlisted: false }], proxyPolicy: { loadingModelWaitSec: 90 }, ...extra });
const boardClients = (proxies) => { const rows = []; const claimed = new Set(); for (const c of (st.topology.clients || [])) for (const a of ((st.topology.assignments[c.id] || {}).assignments || [])) { const own = []; for (const r of (a.routes || [])) { const p = proxies.find((x) => x.id === r.proxyId); if (p && !claimed.has(p.id)) { own.push(p); claimed.add(p.id); } } if (own.length) rows.push({ key: `${c.id}::${a.agentId}`, clientId: c.id, agentId: a.agentId, proxies: own }); } return { rows, unclaimed: proxies.filter((p) => !claimed.has(p.id)) }; };
const reset = () => { st.setTopology(TOPO()); st.ui.topologyCanvasRouterId = "router:a"; st.ui.topologyRouterNodeCfgId = ""; st.ui.pendingConfirm = null; st.ui.latestSystemMonitor = null; localStorage.clear();
  globalThis.__q = {}; globalThis.__qa = {}; globalThis.__fields = { confirmTitle: mkEl(), confirmText: mkEl(), confirmMeta: mkEl(), confirmPath: mkEl(), confirmDelete: mkEl(), confirmOverlay: mkEl({ hidden: true }), toast: mkEl() }; globalThis.__calls = []; globalThis.__timers.length = 0; globalThis.__deferred.length = 0; globalThis.__raf.length = 0; globalThis.__atPoint = null;
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {};
  for (const k of Object.keys(m._cvQueueHistData)) delete m._cvQueueHistData[k]; for (const k of Object.keys(m._cvQueueHistOpen)) delete m._cvQueueHistOpen[k]; for (const k of Object.keys(m._cvSchedHistData)) delete m._cvSchedHistData[k]; for (const k of Object.keys(m._cvSchedHistOpen)) delete m._cvSchedHistOpen[k]; for (const k of Object.keys(m._cvSchedPaintIds)) delete m._cvSchedPaintIds[k]; for (const k of Object.keys(m._cvSchedWorkingGrids)) delete m._cvSchedWorkingGrids[k]; for (const k of Object.keys(m._cvSchedSaveQueue)) delete m._cvSchedSaveQueue[k]; m._cvSchedCollapsed.clear();
  m.cvSetViewport({}, { tx: 24, ty: 24, scale: 1 });
  globalThis.__stubReturns = { "routers.routerById": (rs, id) => rs.find((r) => r.id === id), "routers.saveRouters": async (mut) => { const copy = JSON.parse(JSON.stringify(st.topology.routers)); mut(copy); globalThis.__calls.push(["saveRouters", copy[0]]); }, "routers.topologyRouterOutputLabel": (o) => o.label || o.id, "routers.renderServersBlockHtml": () => "<div class=\"srv\">SERVERS</div>",
    "topology-proxies.canvasBoardClients": boardClients, "topology-proxies._cvProxyIsStale": () => false, "topology-proxies._cvProxyIsTombstoned": () => false, "topology-proxies.topologyMutedProxyIds": () => new Set(), "topology-proxies.topologyProxyOwner": (id) => (id === "skynet:proxy:23001" ? { title: "Hermes" } : null), "topology-proxies.editTopologyProxy": rec("editTopologyProxy"),
    "topology-activity._proxyUpstreamStr": (p) => `${p.upstreamHost || "127.0.0.1"}:${p.upstreamPort || 8080}`, "topology-activity.proxyEffectiveWaitTimeout": () => 1800, "topology-activity.topologyRuntimeOverview": () => globalThis.__overview || { running: [], queued: [] }, "topology-activity.topologyItemGroup": (it) => it.group, "topology-activity.topologyFormatDuration": (ms) => `${Math.round(ms / 1000)}s`, "topology-activity.topologyDurationMs": () => 5000, "topology-activity.topologyQueueRuntime": (it) => ({ timeoutSec: 100, queuedMs: 20000, leftMs: 80000, cloudAt: 40 }), "topology-activity.ensureStickyBarTicker": rec("ensureStickyBarTicker"),
    "topology-render.renderTopology": rec("renderTopology"), "topology-render.refreshTopology": async () => {}, "dialogs.appConfirm": async () => true, "llama-edit.closeConfirmModal": rec("closeConfirmModal"), "form.option": (v, l) => `<option value="${v}">${l}</option>`, "remote-cells.deleteOrphanAgent": rec("deleteOrphanAgent") };
  globalThis.__overview = null; };
reset();
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); };
const nodesOf = () => m.canvasNodes(st.topology.routers[0]);
const node = (id) => nodesOf().find((n) => n.id === id);
const out = {};
"""

PINS = [
    # ── helpers ──
    ("agent_group_and_primary_port", '', '[m._cvAgentGroup({ label: "hermes primary" }), m._cvAgentGroup({ label: "hermes  Fallback" }), m._cvAgentGroup({}), m._cvPrimaryPort({ port: 23002 }), m._cvPrimaryPort({ port: 23001 }), m._cvPrimaryPort({ port: "0" }), m._cvPrimaryPort({})]', '["hermes","hermes","",23001,23001,0,0]',
     "имя группы — подпись без суффикса роли; primary пары — нечётный порт (чётный → порт−1)"),
    ("client_key_and_name", '', '[m.canvasClientKey(PROXIES()[1]), m.canvasClientKey(PROXIES()[3]), m.canvasClientName(PROXIES()[0]), m.canvasClientName(PROXIES()[1]), m.canvasClientName(PROXIES()[2]), m.canvasClientName(PROXIES()[3])]', '["box-a::23001","::8021","hermes","hermes","crane","promie"]',
     "ключ клиента — хост::primary-порт (as-is: без хоста, но с портом — «::порт», id только когда нет обоих); имя — агент из назначений, иначе подпись"),
    ("client_name_qualified_by_host_when_duplicated", 'st.topology.assignments["box-b"].assignments[0].agentId = "hermes";', '[m.canvasClientName(PROXIES()[0]), m.canvasClientName(PROXIES()[2])]', '["hermes · box-a","hermes · box-b"]', "одноимённые агенты на двух хостах квалифицируются хостом"),
    ("client_name_fallbacks_without_assignment", 'st.setTopology(TOPO({ assignments: {} }));', '[m.canvasClientName({ id: "x", label: "box-a", clientId: "box-a", port: 23005 }), m.canvasClientName({ id: "x", label: "box-a", clientId: "box-a" }), m.canvasClientName({ id: "raw", label: "" })]', '["box-a:23005","box-a","raw"]',
     "без назначения: подпись; подпись = хост → хост:primary; ни того ни другого — id"),
    ("hist_formats", '', '[m._cvQHistFmt(null), m._cvQHistFmt(999), m._cvQHistFmt(1500), m._cvQHistFmt(60000), m._cvQHistFmt(125000), m._cvQHistModel({ queue: { cloudFallback: true }, model: "gpt" }), m._cvQHistModel({ stream: { model: "/m/Qwen_Qwen3.6-27B-Q5_K_L.gguf" } }), m._cvQHistModel({ model: "plain" }), m._cvQHistModel({})]',
     '["—","999ms","1.5s","1m","2m 5s",{"text":"gpt","overflow":true},{"text":"Qwen3.6-27B","overflow":false},{"text":"plain","overflow":false},{"text":"?","overflow":false}]', "формат длительности; имя модели: облако — как есть с пометкой, gguf — семейство-размер"),
    ("port_display_name_and_hist_route", '', '[m._portDisplayName(23001), m._portDisplayName(23001, { short: true }), m._portDisplayName(23001, { nameOnly: true }), m._portDisplayName(23101), m._portDisplayName(0), m._cvQHistRoute({ item: { port: 23001 } }), m._cvQHistRoute({ route: "box · hermes fallback" }), m._cvQHistRoute({})]',
     '["Hermes :23001","Hermes:01","Hermes",":23101",":????","Hermes:01","hermes",":?"]', "имя порта: владелец с портом (коротко — две цифры), без владельца — порт; маршрут истории — порт, иначе подпись без роли и хоста"),
    ("sched_input_ports_walk_backwards", '', '(() => { const r = ROUTER(); r.graph.edges.push({ id: "x", from: "in:skynet:proxy:23101", to: "rule:w1" }, { id: "y", from: "rule:w1", to: "rule:s1" }); return [[...m._cvSchedInputPorts(r, "s1")].sort(), [...m._cvSchedInputPorts(r, "q1")], [...m._cvSchedInputPorts(r, "nope")]]; })()', '[[23101],[23001],[]]',
     "порты, доходящие до узла расписания, — обход рёбер назад через промежуточные узлы"),
    ("sched_grid_color_now", '', '(() => { const g = m._cvSchedMakeGrid({ grid: [[null, "o1"]] }); const now = m._cvSchedNow(); return [g.length, g[0].length, g[0][1], g[0][0], g[6][23], m._cvSchedColor([{ id: "a" }, { id: "b" }], "b"), m._cvSchedColor([], "a"), now.d >= 0 && now.d <= 6, /^\\d\\d:\\d\\d$/.test(now.timeStr)]; })()', '[7,24,"o1",null,null,"#f59e0b","",true,true]',
     "сетка 7×24 из частичного конфига, пустое — null; цвет по индексу выхода; «сейчас» — день Пн=0 и часы:минуты"),
    ("labels_summary_edges", '', '(() => { const r = ROUTER(); return [m.cvNodeTypeLabel("queue"), m.cvNodeTypeLabel("zzz"), m._ruleNodeSummary({ type: "weighted", config: { weights: [{ pct: 70 }, { pct: 30 }] } }), m._ruleNodeSummary({ type: "queue", config: { maxSlots: 4, spillPct: 10 } }).includes("spill 10%"), m._ruleNodeSummary({ type: "roundRobin" }).length > 0, m.edgeTargetLabel(r, { to: "out:cb:terra" }), m.edgeTargetLabel(r, { to: "rule:q1" }), m.edgeTargetLabel(r, { to: "out:gone" }), m.graphOutEdges(r, "q1").map((e) => e.id), m.clientProxyInputRefs(r, "box-a::23001"), m._isSingleOut("in:x"), m._isSingleOut("rule:x")]; })()',
     '["queue","zzz","70% / 30%",true,true,"☁ terra","⏳ queue","gone",["e1","e2"],["in:skynet:proxy:23001","in:skynet:proxy:23002"],true,false]', "подписи типов, сводки, подпись цели ребра (выход — подпись, узел — глиф+тип, пропавший — id), исходящие рёбра, входы клиента, одиночный выход у in:"),
    ("paths_positions_viewport", '', '(() => { m.cvSetViewport({ "rule:q1": { x: 1, y: 2 } }, { tx: 10, ty: 20, scale: 2 }); m.canvasSavePositions("router:a"); const stored = localStorage.getItem("cvpos:router:a"); m.cvSetViewport({}, { tx: 0, ty: 0, scale: 1 }); return [m._cvPathD({ x: 0, y: 0 }, { x: 200, y: 100 }), stored, m.canvasLoadPositions("router:a"), m.canvasLoadPositions("router:zzz"), m.canvasPosKey("r")]; })()',
     '["M 0 0 C 96 0, 104 100, 200 100","{\\"rule:q1\\":{\\"x\\":1,\\"y\\":2}}",{"rule:q1":{"x":1,"y":2}},{},"cvpos:r"]', "кривая с плечом 48%; позиции узлов роутера — в localStorage по ключу роутера"),
    ("client_to_world", '', '(() => { globalThis.__q["[data-cv-viewport]"] = mkEl({ rect: { left: 100, top: 50 } }); m.cvSetViewport({}, { tx: 24, ty: 24, scale: 2 }); const p = m._cvClientToWorld(324, 274); m.cvSetViewport({}, { tx: 24, ty: 24, scale: 1 }); return p; })()', '{"x":100,"y":100}', "экранная точка → мир: минус вьюпорт, минус пан, делить на масштаб"),
    ("queue_live_stats", 'globalThis.__overview = { running: [{ group: "127.0.0.1:22001" }, { group: "127.0.0.1:22001" }, { group: "other" }], queued: [{ group: "127.0.0.1:22001", queue: { queuedMs: 40000, timeoutSec: 85 } }] }; st.ui.latestSystemMonitor = { latest: { agentProxies: { slotTotals: { "127.0.0.1:22001": 4 } } } };',
     '(() => { const r = ROUTER(); const q = r.graph.nodes[0]; return [m.queueNodeLiveStats(r, q), m.queueNodeLiveStats(r, { id: "q1", config: { admitEdge: "e2" } }), m.queueNodeLiveStats(r, { id: "zzz", config: {} })]; })()',
     '[{"group":"127.0.0.1:22001","running":2,"queued":1,"slots":4,"waitPct":40},null,null]', "живая статистика очереди: по группе admit-выхода — бегущие, ждущие, слоты из монитора, прогресс ожидания к полному таймауту (85 с при abort 85% = 100 с → 40%); облачный admit или без рёбер — null"),
    # ── canvasNodes ──
    ("nodes_ids_and_positions", '', '(() => nodesOf().map((n) => [n.id, n.type, n.fixed?.x, n.fixed?.y]))()', '[["inputs:block","inputs",20,20],["rule:q1","rule",300,100],["rule:s1","rule",300,400],["rule:w1","rule",300,700],["rule:f1","rule",300,800],["rule:oe1","rule",300,900],["rule:rt1","rule",300,1000],["rule:rs1","rule",300,1100],["outputs:block","outputs",700,20]]',
     "узлы: блок входов (20,20), узлы правил по своим x/y в порядке графа, блок серверов (700,20)"),
    ("inputs_block_rows", '', '(() => { const h = node("inputs:block").html; return [(h.match(/cv-inputs-client /g) || []).length, h.includes(\'data-cv-in-row="in:skynet:proxy:23001"\'), h.includes(\'data-cv-in-row="in:skynet:proxy:23002"\'), h.includes("cv-in-row primary"), h.includes("cv-in-row fallback unwired"), h.includes("↳"), h.includes("wait 1800s") || h.includes("1800"), h.includes("kanban-unclaimed"), h.includes("data-cv-reconcile"), h.includes("cv-orphan-agents")]; })()',
     '[2,true,true,true,true,true,true,false,true,false]', "блок входов: строка на агента с P и F (фолбэк без ребра — «↳ follows»), бюджет ожидания, непринадлежащих нет, кнопка сверки, без мёртвых агентов"),
    ("inputs_block_empty_says_so", 'st.topology.routers[0].inputs = [];', '(() => { const h = node("inputs:block").html; return [h.includes("cv-inputs-client"), h.includes("${"), h.includes(i18n.t("cvNoProxyPorts"))]; })()', '[false,false,true]',
     "роутер без портов: блок клиентов пуст и говорит это словами из en.js, а не буквальным `${…}`"),
    ("inputs_block_unclaimed_and_orphans", 'st.setTopology(TOPO({ orphanedAgents: [{ agentId: "ghost", clientId: "box-z", ports: [23901] }] })); st.topology.routers[0].inputs.push("skynet:proxy:8022");', '(() => { const h = node("inputs:block").html; return [h.includes("kanban-unclaimed"), h.includes(":8022"), h.includes("cv-orphan-agents"), h.includes("ghost · box-z"), h.includes(":23901"), h.includes(\'data-cv-orphan-agent="ghost"\')]; })()',
     '[true,true,true,true,true,true]', "порт без владельца назван непринадлежащим; мёртвые агенты — полоса с портами и кнопкой удаления"),
    ("queue_node_html", '', '(() => { const h = node("rule:q1").html; return [h.includes("cv-q-dest admit") && h.includes("cv-q-dest spill"), h.includes(\'data-cv-qrole="admit"\'), h.includes(\'data-cv-qrole="spill"\'), h.includes(">qwen<") || h.includes("qwen"), h.includes("☁ terra"), h.includes(\'data-cv-q="spillPct" value="25"\'), h.includes(\'data-cv-q="loadingModelWaitSec" value="90"\'), h.includes("cv-q-warn"), h.includes(\'data-cv-q-live="q1"\'), h.includes("cv-port in"), h.includes(\'data-cv-delnode="q1"\'), h.includes("cv-q-hist-toggle")]; })()',
     '[true,true,true,true,true,true,true,false,true,true,true,true]', "узел очереди: main/overflow с ролевыми портами и подписями целей, поля с наследованным loadWait из политики, без предупреждений, живая область, вход, удаление, история"),
    ("queue_node_warns_on_dead_or_unlisted_target", 'st.topology.routers[0].outputs.splice(0, 1); st.topology.cloudProviders[0].unlisted = true;', '(() => { const h = node("rule:q1").html; return [(h.match(/cv-q-warn/g) || []).length, h.includes("main:"), h.includes("overflow:")]; })()', '[2,true,true]',
     "предупреждения: у admit пропал выход, у spill блок не в списке провайдера"),
    ("queue_live_html_empty_and_busy", '', '(() => { const r = ROUTER(); const empty = m.queueNodeLiveHtml(r, r.graph.nodes[0]); globalThis.__overview = { running: [{ group: "127.0.0.1:22001", port: 23001, startedAt: 1 }], queued: [{ group: "127.0.0.1:22001", port: 23101, queue: { position: 1, queuedMs: 20000, timeoutSec: 100 } }] }; const busy = m.queueNodeLiveHtml(r, r.graph.nodes[0]); return [empty.includes("cv-q-empty"), empty.includes("cv-q-qd idle"), busy.includes("cv-q-now-row running"), busy.includes("Hermes :23001"), busy.includes("→ main"), busy.includes("⏳ 1"), busy.includes("cv-q-wait-row"), busy.includes("cv-q-bar-mk spill"), busy.includes("width:20%")]; })()',
     '[true,true,true,true,true,true,true,true,true]', "живая область: пусто — «нет активных», idle; занято — бегущий с именем порта и «→ main», счётчик ждущих, строка ожидания с заливкой 20% и меткой spill"),
    ("schedule_node_html_expanded_and_collapsed", '', '(() => { const h = node("rule:s1").html; m._cvSchedCollapsed.add("s1"); const c = node("rule:s1").html; return [(h.match(/data-cv-sched-cell="s1"/g) || []).length, (h.match(/data-cv-sched-chip="s1:/g) || []).length, h.includes(\'data-cv-sched-port="o1"\'), h.includes(\'data-cv-sched-port="__default__"\'), h.includes("cv-sched-row--active") && h.includes(\'data-cv-sched-chip="s1:o1"\'), h.includes("+ output"), h.includes("cv-port in"), c.includes("cv-sched-chip-stub"), (c.match(/data-cv-sched-port=/g) || []).length, c.includes("cv-sched-gcal")]; })()',
     '[168,3,true,true,true,true,true,true,3,false]', "расписание раскрыто: 168 клеток, строки двух выходов + default (первый выход — кисть), порт на каждом; свёрнуто — только заглушки портов, без сетки"),
    ("other_rule_nodes_html", '', '(() => { const w = node("rule:w1").html, f = node("rule:f1").html, oe = node("rule:oe1").html, rt = node("rule:rt1").html, rs = node("rule:rs1").html; return [w.includes(\'data-cv-cfgnode="w1"\') && w.includes(\'data-cv-port="out"\'), w.includes("70%"), f.includes("data-cv-cfgnode"), oe.includes(\'data-cv-qrole="main"\') && oe.includes(\'data-cv-qrole="rescue"\'), oe.includes("data-cv-cfgnode"), rt.includes(\'data-cv-sched-port="embed"\') && rt.includes(\'data-cv-sched-port="__default__"\'), rt.includes(\'cv-q-dest spill"\') && rt.includes("cv-q-dest admit unset"), rs.includes(\'data-cv-q="maxTokensAt" value="500"\'), rs.includes(\'data-cv-sched-port="small"\')]; })()',
     '[true,true,true,true,false,true,true,true,true]', "weighted/failover — шестерёнка и общий выход; onError — main/rescue без шестерёнки; requestType — embed привязан, default без ребра — unset; requestSize — порог и порт small"),
    ("request_type_global_note", 'st.topology.routers[0].rules.embeddingsOutput = "srv:22003";', '(() => { const rt = node("rule:rt1").html; const inp = node("inputs:block").html; return [rt.includes("cv-q-note"), inp.includes("cv-embed-slot assigned"), inp.includes(\'<option value="srv:22003" selected>\'), inp.includes("cb:terra")]; })()', '[true,true,true,false]',
     "глобальный слот embeddings назначен: узел by-type предупреждает, слот показывает выбор; облачные выходы в слот не попадают"),
    ("outputs_block_uses_servers_renderer", '', '(() => { const o = node("outputs:block"); return [o.cls, o.html.includes("SERVERS"), o.html.includes("cv-servers-body")]; })()', '["cv-servers-block",true,true]', "блок серверов рисует renderServersBlockHtml внутри своей обёртки"),
    ("render_canvas_modal", '', '(() => { m.cvSetViewport({ "rule:q1": { x: 5, y: 6 } }, { tx: 1, ty: 2, scale: 1.5 }); const h = m.renderTopologyCanvasModal(); m.cvSetViewport({}, { tx: 24, ty: 24, scale: 1 }); st.ui.topologyCanvasRouterId = ""; const none = m.renderTopologyCanvasModal(); return [h.includes("translate(1px, 2px) scale(1.5)"), h.includes(\'data-cv-node="rule:q1" style="left:5px;top:6px"\'), h.includes(\'data-cv-node="inputs:block" style="left:20px;top:20px"\'), (h.match(/class="cv-node /g) || []).length, none]; })()',
     '[true,true,true,9,""]', "модал канбана: трансформ мира из вьюпорта, сохранённая позиция побеждает fixed, все узлы; без открытого роутера — пусто"),
    # ── graph operations ──
    ("add_rule_node_schedule_gets_two_outputs", 'globalThis.__q["[data-cv-viewport]"] = mkEl({ clientWidth: 800, clientHeight: 600 });', 'await (async () => { m.addRuleNode("schedule"); m.addRuleNode("queue"); await settle(); const s = saved(); const sn = s[0].graph.nodes.at(-1), qn = s[1].graph.nodes.at(-1); return [sn.type, sn.config.outputs.length, sn.config.grid.length, sn.x, sn.y, qn.type, qn.config, qn.id.startsWith("n")]; })()',
     '["schedule",2,7,376,276,"queue",{},true]', "новый узел в центре вьюпорта (с учётом пана 24); расписание рождается с двумя выходами и пустой сеткой, очередь — с пустым конфигом"),
    ("delete_rule_node_confirms_and_drops_edges", '', 'await (async () => { globalThis.__stubReturns["dialogs.appConfirm"] = async () => false; await m.deleteRuleNode("q1"); const refused = saved().length; globalThis.__stubReturns["dialogs.appConfirm"] = async () => true; await m.deleteRuleNode("q1"); await settle(); const g = lastSaved().graph; return [refused, g.nodes.some((n) => n.id === "q1"), g.edges.filter((e) => e.from === "rule:q1" || e.to === "rule:q1").length, g.edges.length]; })()',
     '[0,false,0,8]', "удаление узла: без подтверждения ничего; с ним — узел и все его рёбра (входящие и исходящие) сняты"),
    ("add_edge_single_out_replaces_for_ports", '', 'await (async () => { m.addGraphEdge("in:skynet:proxy:23001", "rule:w1"); await settle(); const g = lastSaved().graph; return [g.edges.filter((e) => e.from === "in:skynet:proxy:23001").map((e) => e.to), g.edges.length]; })()', '[["rule:w1"],11]',
     "порт клиента имеет один выход: новое ребро заменяет прежнее"),
    ("add_edge_inc_expands_and_dedupes", '', 'await (async () => { m.addGraphEdge("inc:box-a::23001", "rule:w1"); await settle(); const g = lastSaved().graph; m.addGraphEdge("rule:w1", "out:srv:22001"); await settle(); return [g.edges.filter((e) => e.to === "rule:w1").map((e) => e.from).sort(), lastSaved().graph.edges.filter((e) => e.from === "rule:w1" && e.to === "out:srv:22001").length, saved().length]; })()',
     '[["in:skynet:proxy:23001","in:skynet:proxy:23002"],1,2]', "inc:клиент раскрывается в ребро на каждый порт клиента; дубль ребра узла не добавляется"),
    ("add_edge_noops", '', 'await (async () => { m.addGraphEdge("", "rule:w1"); m.addGraphEdge("rule:w1", "rule:w1"); m.addGraphEdge("rule:w1", "out:x", "admit"); await settle(); return [saved().length, lastSaved().graph.edges.length]; })()', '[1,11]', "negative: пустой источник и петля — без записи; роль у узла не-очереди — as-is: saveRouters вызван, но граф не тронут (11 рёбер)"),
    ("add_edge_queue_role_replaces_and_points", '', 'await (async () => { m.addGraphEdge("rule:q1", "out:srv:22003", "spill"); await settle(); const g = lastSaved().graph; const q = g.nodes.find((n) => n.id === "q1"); const spill = g.edges.find((e) => e.id === q.config.spillEdge); return [g.edges.some((e) => e.id === "e2"), spill.to, q.config.admitEdge, g.edges.filter((e) => e.from === "rule:q1").length]; })()',
     '[false,"out:srv:22003","e1",2]', "роль очереди: прежнее ребро роли снято, новое записано в указатель роли, другая роль нетронута"),
    ("add_edge_sched_port_replaces_per_port", '', 'await (async () => { m.addGraphEdge("rule:s1", "out:srv:22003", null, "o1"); await settle(); const g = lastSaved().graph; return [g.edges.filter((e) => e.from === "rule:s1" && e.schedPortId === "o1").map((e) => e.to), g.edges.some((e) => e.id === "e4")]; })()', '[["out:srv:22003"],true]',
     "порт расписания: ровно одно ребро на порт, чужие порты нетронуты"),
    ("rewire_keeps_sched_port_and_role_pointer", '', 'await (async () => { m.rewireGraphEdge("rule:s1", "out:srv:22001", "out:srv:22003"); await settle(); const a = lastSaved().graph.edges.find((e) => e.from === "rule:s1" && e.to === "out:srv:22003"); m.rewireGraphEdge("rule:q1", "out:srv:22001", "out:srv:22003"); await settle(); const g = lastSaved().graph; const q = g.nodes.find((n) => n.id === "q1"); const admit = g.edges.find((e) => e.id === q.config.admitEdge); return [a.schedPortId, g.edges.some((e) => e.id === "e1"), admit.to, q.config.spillEdge]; })()',
     '["o1",false,"out:srv:22003","e2"]', "перецепка: тег порта расписания наследуется; указатель роли очереди переезжает на новое ребро"),
    ("rewire_noops_and_delete_between", '', 'await (async () => { m.rewireGraphEdge("rule:q1", "out:srv:22001", "out:srv:22001"); m.rewireGraphEdge("", "a", "b"); await settle(); const none = saved().length; m.deleteGraphEdgesBetween("inc:box-a::23001", "rule:q1"); await settle(); const g = lastSaved().graph; m.deleteGraphEdgesBetween("rule:q1", "out:srv:22001"); await settle(); const q = lastSaved().graph.nodes.find((n) => n.id === "q1"); return [none, g.edges.some((e) => e.id === "e0"), q.config.admitEdge, q.config.spillEdge]; })()',
     '[0,false,"","e2"]', "перецепка в ту же цель или без источника — ничего; удаление между inc: и узлом снимает рёбра всех портов клиента; удалённое ребро роли чистит её указатель"),
    ("heal_adopts_free_edge_and_converges", '', 'await (async () => { m.healQueueNodeEdges(); await settle(); const healthy = saved().length; st.topology.routers[0].graph.nodes[0].config = { spillEdge: "e2" }; m.healQueueNodeEdges(); await settle(); const q = lastSaved().graph.nodes.find((n) => n.id === "q1"); return [healthy, q.config.admitEdge]; })()', '[0,"e1"]',
     "лечение: здоровый граф не пишется; узел без admit принимает первое свободное ребро (не spill)"),
    ("sched_save_grid_queue", '', 'await (async () => { let resolve; globalThis.__stubReturns["routers.saveRouters"] = (mut) => new Promise((r) => { resolve = () => { const copy = JSON.parse(JSON.stringify(st.topology.routers)); mut(copy); globalThis.__calls.push(["saveRouters", copy[0]]); r(); }; }); m._cvSchedSaveGrid("s1", [["A"]]); m._cvSchedSaveGrid("s1", [["B"]]); m._cvSchedSaveGrid("s1", [["C"]]); const inflight = [saved().length, m._cvSchedSaveQueue.s1.pending[0][0]]; resolve(); await settle(); const after = [saved().length]; resolve(); await settle(); return [...inflight, ...after, saved().map((s) => s.graph.nodes.find((n) => n.id === "s1").config.grid[0][0])]; })()',
     '[0,"C",1,["A","C"]]', "очередь сохранений сетки: пока запрос в полёте, копится ТОЛЬКО последняя сетка и уходит следом — промежуточная B не пишется"),
    ("save_node_config_and_panel", '', 'await (async () => { m.saveNodeConfig("w1", (c) => { c.weights = [{ edge: "e5", pct: 60 }]; }); await settle(); st.ui.topologyRouterNodeCfgId = "w1"; const w = m.renderRouterNodeConfig(st.topology.routers[0]); st.ui.topologyRouterNodeCfgId = "f1"; const f = m.renderRouterNodeConfig(st.topology.routers[0]); st.ui.topologyRouterNodeCfgId = "q1"; const q = m.renderRouterNodeConfig(st.topology.routers[0]); st.ui.topologyRouterNodeCfgId = "zzz"; const none = m.renderRouterNodeConfig(st.topology.routers[0]); return [lastSaved().graph.nodes.find((n) => n.id === "w1").config.weights[0].pct, w.includes("data-cfg-weight") && w.includes(\'value="70"\'), (f.match(/data-cfg-ord-id=/g) || []).length, q.includes(\'data-cfg-q="spillPct"\'), none]; })()',
     '[60,true,0,true,""]', "конфиг узла сохраняется патчем; панель: веса по рёбрам, порядок failover (без рёбер — пусто), поля очереди; неизвестный узел — пусто"),
    # ── geometry and connectors ──
    ("world_point_sums_offsets", '', '(() => { const world = mkEl({ classList: (() => { const c = cls(); c.add("cv-world"); return c; })() }); const nodeEl = mkEl({ offsetLeft: 100, offsetTop: 50, offsetWidth: 200, offsetHeight: 80, offsetParent: world }); const port = mkEl({ offsetLeft: 190, offsetTop: 30, offsetWidth: 16, offsetHeight: 16, offsetParent: nodeEl }); return [m._cvWorldPoint(port, "right"), m._cvWorldPoint(port, "center"), m._cvWorldPoint(nodeEl, "left")]; })()',
     '[{"x":306,"y":88},{"x":298,"y":88},{"x":100,"y":90}]', "точка мира суммирует смещения до cv-world: правый край, центр, левый край"),
    # ── the backup node: output health and the ▶ for the next request come from proxy state, not a recomputation ──
    ("onerror_rows_default", '', '(() => { const h = node("rule:oe1").html; const rows = h.split(/class="cv-q-dest/).slice(1); const cls = (r) => (r.match(/cv-oe-state (\\w+)/) || [])[1]; const tip = (r) => (r.match(/cv-oe-state \\w+" title="([^"]*)"/) || [])[1]; return [rows.length, /cv-oe-next" title="the next request goes here">▶/.test(rows[0]), /cv-oe-next off/.test(rows[1]), cls(rows[0]), tip(rows[0]), cls(rows[1]), /data-cv-oe-live="oe1"/.test(h)]; })()',
     '[2,true,true,"unknown","not checked yet","unknown",true]',
     "без отчёта прокси: ▶ у main (это и есть правило прокси, когда он ничего не знает), оба выхода «ещё не проверялись», живая область помечена id узла"),
    ("onerror_rows_from_monitor", 'st.ui.latestSystemMonitor = { latest: { agentProxies: { outputHealth: { "srv:22001": { state: "error", status: 429, kind: "http 429", message: "quota gone", ageSec: 120, fresh: true, retryInSec: 180 }, "cb:terra": { state: "ok", ageSec: 5, fresh: true, retryInSec: 295 } }, onErrorNext: { oe1: { next: "backup", reason: "main is down: http 429" } } } } };', '(() => { const h = node("rule:oe1").html; const rows = h.split(/class="cv-q-dest/).slice(1); const cls = (r) => (r.match(/cv-oe-state (\\w+)/) || [])[1]; const tip = (r) => (r.match(/cv-oe-state \\w+" title="([^"]*)"/) || [])[1]; return [/cv-oe-next off/.test(rows[0]), /cv-oe-next" title="the next request goes here">▶/.test(rows[1]), cls(rows[0]), tip(rows[0]), cls(rows[1]), tip(rows[1])]; })()',
     '[true,true,"error","down (http 429: quota gone) — 2m ago; re-checked in 3m","ok","alive — checked 5s ago"]',
     "из отчёта: main мёртв (429, квота) — ▶ уходит на backup, точка красная с причиной, возрастом и сроком перепроверки; backup жив — зелёная с возрастом"),
    ("onerror_rows_stale", 'st.ui.latestSystemMonitor = { latest: { agentProxies: { outputHealth: { "srv:22001": { state: "error", status: 429, kind: "http 429", message: "quota gone", ageSec: 420, fresh: false, retryInSec: 0 } }, onErrorNext: { oe1: { next: "main", reason: "" } } } } };', '(() => { const h = node("rule:oe1").html; const rows = h.split(/class="cv-q-dest/).slice(1); const cls = (r) => (r.match(/cv-oe-state (\\w+)/) || [])[1]; const tip = (r) => (r.match(/cv-oe-state \\w+" title="([^"]*)"/) || [])[1]; return [/cv-oe-next" title/.test(rows[0]), cls(rows[0]), tip(rows[0])]; })()',
     '[true,"stale","last verdict: http 429: quota gone, 7m ago — re-checked on the next request"]',
     "истёкший вердикт: ▶ снова у main, точка янтарная — «последний вердикт … перепроверится на следующем запросе», а не мёртвый"),
    ("onerror_sync_live", 'const oeEl = mkEl({ getAttribute: () => "oe1", innerHTML: "" }); globalThis.__qa["[data-cv-oe-live]"] = [oeEl]; st.ui.latestSystemMonitor = { latest: { agentProxies: { outputHealth: { "srv:22001": { state: "error", status: 429, kind: "http 429", message: "quota gone", ageSec: 120, fresh: true, retryInSec: 180 }, "cb:terra": { state: "ok", ageSec: 5, fresh: true, retryInSec: 295 } }, onErrorNext: { oe1: { next: "backup", reason: "main is down: http 429" } } } } }; m.syncQueueNodesLive();', '(() => { const rows = oeEl.innerHTML.split(/class="cv-q-dest/).slice(1); return [rows.length, /cv-oe-next off/.test(rows[0]), /▶/.test(rows[1])]; })()',
     '[2,true,true]',
     "тик монитора перепатчивает только живую область узла: ▶ переехал на backup без полной перерисовки"),
    ("onerror_chained_exit", 'st.ui.latestSystemMonitor = { latest: { agentProxies: { outputHealth: { "srv:22010": { state: "ok", checkedAt: 1699999993, ageSec: 7, fresh: true, retryInSec: 293 }, "srv:22001": { state: "error", status: 429, kind: "http 429", message: "quota", ageSec: 10, fresh: true, retryInSec: 290 } }, onErrorNext: { oe1: { next: "main", reason: "", main: "srv:22010", mainChain: ["q1"], mainName: "Muse :22010" } } } } };',
     '(() => { const h = node("rule:oe1").html; const rows = h.split(/class="cv-q-dest/).slice(1); const cls = (r) => (r.match(/cv-oe-state (\\w+)/) || [])[1]; const label = (r) => (r.match(/cv-q-dt" title="([^"]*)"/) || [])[1]; return [cls(rows[0]), label(rows[0]), /cv-oe-cd/.test(rows[0])]; })()',
     '["ok","qwen → Muse :22010",true]',
     "выход в узел: здоровье и отсчёт берутся у КОНЕЧНОГО выхода, названного прокси (srv:22010 — жив), а подпись говорит через что: «… → Muse :22010»; вердикт выхода, куда ведёт само ребро (429), к этой строке отношения не имеет"),
    ("onerror_chain_named_by_the_board", 'st.ui.latestSystemMonitor = { latest: { agentProxies: { outputHealth: { "srv:22003": { state: "ok", checkedAt: 1699999993, ageSec: 7, fresh: true, retryInSec: 293 } }, onErrorNext: { oe1: { next: "main", reason: "", main: "srv:22003", mainChain: ["q1"], mainName: "srv:22003" } } } } };',
     '(() => { const rows = node("rule:oe1").html.split(/class="cv-q-dest/).slice(1); return (rows[0].match(/cv-q-dt" title="([^"]*)"/) || [])[1]; })()',
     '"qwen → embed"',
     "выход, который доска знает, называется её же словами («embed», как на канате), а не голым id из отчёта: одна модель — одно имя на экране"),
    ("onerror_chain_unnamed", 'st.ui.latestSystemMonitor = { latest: { agentProxies: { outputHealth: { "srv:22001": { state: "ok", ageSec: 7, fresh: true, retryInSec: 293 } }, onErrorNext: { oe1: { next: "main", reason: "", main: null, mainChain: ["rr1"], mainName: null } } } } };',
     '(() => { const h = node("rule:oe1").html; const rows = h.split(/class="cv-q-dest/).slice(1); const cls = (r) => (r.match(/cv-oe-state (\\w+)/) || [])[1]; const label = (r) => (r.match(/cv-q-dt" title="([^"]*)"/) || [])[1]; return [cls(rows[0]), label(rows[0])]; })()',
     '["ok","qwen"]',
     "negative: конец цепочки не назван (её решает round-robin) — стрелки в подписи нет, догадка тут хуже молчания; здоровье берётся у того, куда ведёт само ребро — для прямого выхода это он и есть"),
    ("onerror_ago", '', '[m.OnErrorNode.ago(5), m.OnErrorNode.ago(59), m.OnErrorNode.ago(60), m.OnErrorNode.ago(150), m.OnErrorNode.ago(3600), m.OnErrorNode.ago(-3), m.OnErrorNode.ago("x")]',
     '["5s","59s","1m","3m","1h","0s","0s"]',
     "возраст: секунды до минуты, минуты до часа, часы; мусор и минус — 0s"),
    ("onerror_countdown", 'st.ui.latestSystemMonitor = { latest: { agentProxies: { outputHealth: { "srv:22001": { state: "error", status: 429, kind: "http 429", message: "quota", checkedAt: 1700000000, ageSec: 100, fresh: true, retryInSec: 200 }, "cb:terra": { state: "ok", checkedAt: 1699999600, ageSec: 500, fresh: false, retryInSec: 0 } }, onErrorNext: { oe1: { next: "main", reason: "" } } } } }; globalThis.__timers.length = 0;', '(() => { const h = node("rule:oe1").html; const rows = h.split(/class="cv-q-dest/).slice(1); const cd = (r) => (r.match(/cv-oe-cd" data-cv-oe-deadline="(\\d+)"[^>]*>([^<]*)</) || []).slice(1, 3); return [cd(rows[0]), cd(rows[1]), globalThis.__timers.includes("interval:1000")]; })()',
     '[["1700000300","3:20"],["1700000100","0:00"],true]',
     "отсчёт: дедлайн = checkedAt + возраст + срок перепроверки; свежий вердикт — «3:20», истёкший — «0:00»; тикер раз в секунду зарегистрирован при отрисовке"),
    ("onerror_countdown_unknown", '', '(() => { const h = node("rule:oe1").html; return [h.includes("cv-oe-cd"), m.OnErrorNode.countdownText(0), m.OnErrorNode.countdownText(1700000100 - 5), m.OnErrorNode.countdownText(1700000100 + 61), m.OnErrorNode.countdownText(1700000100 + 3600)]; })()',
     '[false,"","0:00","1:01","60:00"]',
     "без вердикта отсчёта нет; текст: пусто без дедлайна, «0:00» в прошлом, минуты без ограничения часом"),
    ("onerror_countdown_tick", 'const cdEl = mkEl({ textContent: "", dataset: { cvOeDeadline: "1700000300" } }); globalThis.__qa["[data-cv-oe-deadline]"] = [cdEl]; m.OnErrorNode.tick();', 'cdEl.textContent',
     '"3:20"',
     "тик патчит только текст отсчёта — строки узла не перестраиваются"),
    ("draw_connectors_groups_and_roles", '', '(() => { const world = mkEl({ classList: (() => { const c = cls(); c.add("cv-world"); return c; })() }); const el = (x, y, w = 100, h = 40) => mkEl({ offsetLeft: x, offsetTop: y, offsetWidth: w, offsetHeight: h, offsetParent: world }); const q = el(300, 100), s = el(300, 400), w1 = el(300, 700), oe = el(300, 900), rt = el(300, 1000), rs = el(300, 1100), f1 = el(300, 800); const admitPort = mkEl({ offsetLeft: 90, offsetTop: 10, offsetWidth: 10, offsetHeight: 10, offsetParent: q }); q.q = { \'.cv-port.out[data-cv-qrole="admit"]\': admitPort }; const outA = el(700, 20, 10, 10), outB = el(700, 60, 10, 10), outC = el(700, 100, 10, 10); const inDot = el(200, 30, 10, 10); world.q = { \'[data-cv-node="rule:q1"]\': q, \'[data-cv-node="rule:s1"]\': s, \'[data-cv-node="rule:w1"]\': w1, \'[data-cv-node="rule:oe1"]\': oe, \'[data-cv-node="rule:rt1"]\': rt, \'[data-cv-node="rule:rs1"]\': rs, \'[data-cv-node="rule:f1"]\': f1, \'[data-cv-out-port="out:srv:22001"]\': outA, \'[data-cv-out-port="out:cb:terra"]\': outB, \'[data-cv-out-port="out:srv:22003"]\': outC, \'.cv-port.out[data-cv-ref="in:skynet:proxy:23001"]\': inDot }; const svg = mkEl({ classList: cls() }); globalThis.__q["[data-cv-world]"] = world; globalThis.__q["[data-cv-svg]"] = svg; m.drawCanvasConnectors(); const h = svg.innerHTML; return [(h.match(/class="cv-edge-grp"/g) || []).length, h.includes(\'data-t-id="in:skynet:proxy:23001-&gt;rule:q1"\'), h.includes("cv-cable cv-cable-admit"), h.includes("cv-cable cv-cable-spill"), h.includes("cv-cable cv-cable-main") && h.includes("cv-cable cv-cable-rescue"), h.includes("M 400 120 C"), (h.match(/data-cv-edge-del=/g) || []).length]; })()',
     '[11,true,true,true,true,true,11]', "коннекторы: группа на ребро с data-t-id from->to, классы ролей очереди и onError, admit выходит из ролевого порта, ✕ на каждом"),
    ("draw_connectors_without_router_clears", 'st.ui.topologyCanvasRouterId = "router:zzz";', '(() => { const svg = mkEl({ innerHTML: "OLD" }); globalThis.__q["[data-cv-world]"] = mkEl(); globalThis.__q["[data-cv-svg]"] = svg; m.drawCanvasConnectors(); return svg.innerHTML; })()', '""', "negative: роутер не найден — холст очищен"),
    ("bind_node_drag_moves_and_persists_rule_position", '', 'await (async () => { const world = mkEl({ dataset: {}, classList: (() => { const c = cls(); c.add("cv-world"); return c; })() }); const viewport = mkEl({ rect: { left: 0, top: 0 } }); const nodeEl = mkEl({ dataset: { cvNode: "rule:q1" }, offsetLeft: 300, offsetTop: 100, style: {}, parentElement: world, q: {} }); nodeEl.closest = (sel) => (sel === "[data-cv-node]" ? nodeEl : null); world.qa = { "[data-cv-node]": [nodeEl], ".cv-node": [nodeEl] }; globalThis.__q["[data-cv-viewport]"] = viewport; globalThis.__q["[data-cv-world]"] = world; m.bindCanvasInteractions(); const bound = world.dataset.cvBound; m.bindCanvasInteractions(); nodeEl.listeners.pointerdown[0]({ button: 0, clientX: 10, clientY: 10, target: { closest: () => null }, stopPropagation() {}, preventDefault() {} }); const dragging = nodeEl.classList.has("dragging"); winListeners.pointermove.at(-1)({ clientX: 60, clientY: 30 }); const moved = [nodeEl.style.left, nodeEl.style.top, m._cvPos["rule:q1"]]; winListeners.pointerup.at(-1)({}); await settle(); const persisted = lastSaved().graph.nodes.find((n) => n.id === "q1"); return [bound, nodeEl.listeners.pointerdown.length, dragging, moved, nodeEl.classList.has("dragging"), [persisted.x, persisted.y]]; })()',
     '["1",1,true,["350px","120px",{"x":350,"y":120}],false,[350,120]]', "перетаскивание узла: биндер одной привязкой на поколение мира, движение в мировых единицах, позиция rule-узла пишется в граф при отпускании"),
    ("bind_pan_and_wheel_zoom", '', '(() => { const world = mkEl({ dataset: {}, classList: cls() }); const viewport = mkEl({ rect: { left: 0, top: 0 }, classList: cls() }); globalThis.__q["[data-cv-viewport]"] = viewport; globalThis.__q["[data-cv-world]"] = world; m.cvSetViewport({}, { tx: 24, ty: 24, scale: 1 }); m.bindCanvasInteractions(); viewport.listeners.pointerdown[0]({ button: 0, clientX: 100, clientY: 100, target: { closest: () => null } }); const panning = viewport.classList.has("panning"); winListeners.pointermove.at(-1)({ clientX: 130, clientY: 90 }); const panned = [m._cvView.tx, m._cvView.ty, world.style.transform]; winListeners.pointerup.at(-1)({}); let p = 0; viewport.listeners.wheel[0]({ deltaY: -100, clientX: 54, clientY: 14, target: { closest: () => null }, preventDefault: () => p++ }); const zoomed = [Math.round(m._cvView.scale * 1000) / 1000, Math.round(m._cvView.tx * 10) / 10, Math.round(m._cvView.ty * 10) / 10]; for (let i = 0; i < 20; i++) viewport.listeners.wheel[0]({ deltaY: -100, clientX: 0, clientY: 0, target: { closest: () => null }, preventDefault() {} }); const max = m._cvView.scale; for (let i = 0; i < 40; i++) viewport.listeners.wheel[0]({ deltaY: 100, clientX: 0, clientY: 0, target: { closest: () => null }, preventDefault() {} }); return [panning, panned, viewport.classList.has("panning"), p, zoomed, max, m._cvView.scale]; })()',
     '[true,[54,14,"translate(54px, 14px) scale(1)"],false,1,[1.1,54,14],2.2,0.35]', "пан фоном двигает мир; колесо — зум к курсору (точка под курсором на месте), зажат в 0.35…2.2"),
    ("bind_port_drag_connects_on_drop", '', 'await (async () => { const world = mkEl({ dataset: {}, classList: (() => { const c = cls(); c.add("cv-world"); return c; })() }); const viewport = mkEl({ rect: { left: 0, top: 0 } }); const nodeEl = mkEl({ dataset: { cvNode: "rule:w1" }, offsetParent: world, offsetLeft: 300, offsetTop: 700 }); const port = mkEl({ dataset: { cvRef: "" }, offsetParent: nodeEl, offsetLeft: 90, offsetTop: 10, offsetWidth: 10, offsetHeight: 10 }); port.closest = (sel) => (sel === ".cv-port.out" ? port : sel === "[data-cv-node]" ? nodeEl : null); globalThis.__q["[data-cv-viewport]"] = viewport; globalThis.__q["[data-cv-world]"] = world; m.bindCanvasInteractions(); world.listeners.pointerdown[0]({ button: 0, target: port, stopPropagation() {}, preventDefault() {} }); const target = mkEl({ dataset: { cvNode: "out:srv:22003" }, classList: cls() }); target.closest = (sel) => (sel === "[data-cv-node]" ? target : null); globalThis.__atPoint = target; globalThis.__qa[".cv-node.cv-drop-ok"] = [target]; winListeners.pointermove.at(-1)({ clientX: 500, clientY: 500 }); const dropOk = target.classList.has("cv-drop-ok"); winListeners.pointerup.at(-1)({ clientX: 500, clientY: 500 }); await settle(); const g = lastSaved().graph; return [dropOk, g.edges.some((e) => e.from === "rule:w1" && e.to === "out:srv:22003"), target.classList.has("cv-drop-ok")]; })()',
     '[true,true,false]', "протяжка из порта: цель под курсором подсвечивается, отпускание над выходом создаёт ребро, подсветка снята"),
    ("bind_queue_cfg_input_clamps", '', 'await (async () => { const world = mkEl({ dataset: {}, classList: cls() }); const viewport = mkEl(); const nodeEl = mkEl({ dataset: { cvNode: "rule:q1" } }); const slots = mkEl({ dataset: { cvQ: "maxSlots" }, value: "99", min: "1", max: "64" }); slots.closest = () => nodeEl; const pct = mkEl({ dataset: { cvQ: "spillPct" }, value: "150", min: "0", max: "100" }); pct.closest = () => nodeEl; world.qa = { ".cv-q-cfg-in[data-cv-q]": [slots, pct] }; globalThis.__q["[data-cv-viewport]"] = viewport; globalThis.__q["[data-cv-world]"] = world; m.bindCanvasInteractions(); slots.listeners.change[0](); pct.listeners.change[0](); slots.value = ""; slots.listeners.change[0](); await settle(); const cfgs = saved().map((s) => s.graph.nodes.find((n) => n.id === "q1").config); return [cfgs[0].maxSlots, cfgs[1].spillPct, cfgs[2].maxSlots]; })()',
     '[64,100,null]', "поля очереди на карточке: слоты зажаты 1…64 (пусто — null = авто), проценты 0…100"),
    ("bind_sched_paint_saves_grid", '', 'await (async () => { const world = mkEl({ dataset: {}, classList: cls() }); const cell = mkEl({ dataset: { cvSchedCell: "s1", schedD: "2", schedH: "5" }, style: {}, classList: cls() }); const cell2 = mkEl({ dataset: { cvSchedCell: "s1", schedD: "2", schedH: "6" }, style: {}, classList: cls() }); world.qa = { "[data-cv-sched-cell]": [cell, cell2] }; globalThis.__q["[data-cv-viewport]"] = mkEl(); globalThis.__q["[data-cv-world]"] = world; globalThis.__q[\'[data-cv-sched-cell="s1"][data-sched-d="2"][data-sched-h="5"]\'] = cell; globalThis.__q[\'[data-cv-sched-cell="s1"][data-sched-d="2"][data-sched-h="6"]\'] = cell2; m.bindCanvasInteractions(); cell.listeners.pointerdown[0]({ button: 0, stopPropagation() {}, preventDefault() {} }); const painting = [m._cvSchedPainting, cell.style.background, cell.classList.has("painted")]; cell2.listeners.pointerover[0]({}); winListeners.pointerup.find((fn) => fn.length === 0 || true); for (const fn of winListeners.pointerup) fn({}); await settle(); const grid = lastSaved().graph.nodes.find((n) => n.id === "s1").config.grid; return [painting, cell2.classList.has("painted"), grid[2][5], grid[2][6], grid[0][1], m._cvSchedPainting]; })()',
     '[[true,"#60a5fa",true],true,"o1","o1","o1",false]', "рисование сетки: pointerdown красит кистью (первый выход), pointerover продолжает, pointerup сохраняет сетку целиком (старые клетки на месте)"),
    ("resolve_overlap_pushes_dragged_node_only", '', '(() => { const world = mkEl({ classList: cls() }); const a = mkEl({ dataset: { cvNode: "rule:q1" }, offsetLeft: 100, offsetTop: 100, offsetWidth: 100, offsetHeight: 40, style: {}, parentElement: world }); const b = mkEl({ dataset: { cvNode: "rule:w1" }, offsetLeft: 150, offsetTop: 100, offsetWidth: 100, offsetHeight: 40, style: {} }); world.qa = { ".cv-node": [a, b] }; m._cvResolveOverlap(a); return [a.style.left, a.style.top, b.style.left, m._cvPos["rule:q1"]]; })()',
     '["100px","188px",null,{"x":100,"y":188}]', "раздвижка: сдвигается только перетащенный узел, по оси меньшего сдвига (dy 88 < dx 98), с зазором 48 и без зажима к нулю"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 40:
        print(f"js canvas FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js canvas: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    # Pins don't depend on each other: the same set run in reverse order
    # must give the same values.
    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_canvas.tmp.mjs"
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
        print(f"js canvas FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("канбан: узлы, рёбра графа, геометрия, перетаскивание:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:200]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:200]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print(f"порядок: {len(PINS)} пинов дают те же значения в обратном порядке" if not _fail else "")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js canvas OK: настоящий модуль в node, {len(PINS)} пинов канбана значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
