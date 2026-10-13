#!/usr/bin/env python3
"""Snapshot of static/js/cables.js — the board's cables: geometry, classes, and a report of the missing.

The centerpiece here is `drawTopologyCables` and its `cableDrops`: a cable
with no anchor or binding used to vanish silently into filter(Boolean), and
the board looked "normal minus one curve" — that's how a missing agent cable
stayed hidden for a month (v1.3.92, the "absence rendered as normality"
defect class). Now every drop names the cable and the reason, with warnings
deduplicated. What's pinned by value: which cables get drawn, with which
classes (primary/fallback, priority, unverified with a tooltip, idle/active),
and WHAT gets recorded about the ones that can't be drawn.

Alongside that: pure geometry (a Bezier curve with a 48 minimum arm), anchor
points relative to the board, state/proxy/route classes, a deterministic
accent by key, apply status with the priority "assignment > client > stored".

The DOM is the `globalThis.__q` selector dict (querySelector by exact string)
and `globalThis.__fields` for svg; CSS.escape is the identity function. The
module is real, as are routers/topology-activity/topology-proxies;
`topology-dnd.topologyPointerDrag` is set via __stubValues before import.

Run: python3 scripts/test_js_cables.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("topology-dnd,canvas,polling,topology-render,dialogs,charts,cloud,history,favorites,config-locator,"
         "system-panels,onboarding,onboarding-tours,usage-stats,dialog-llamas,models-page,system-page,memory,"
         "command-preview,llama-edit,remote-cells,topology-nodes,topology-modals")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
const R = (left, top, width = 40, height = 20) => ({ getBoundingClientRect: () => ({ left, top, width, height, right: left + width, bottom: top + height }) });
const LIVE_SRC = R(100, 100);
globalThis.__stubValues = { "topology-dnd.topologyPointerDrag": { source: LIVE_SRC } };
globalThis.CSS = { escape: (s) => String(s) };
globalThis.__q = {};
document.querySelector = (s) => (Object.prototype.hasOwnProperty.call(globalThis.__q, s) ? globalThis.__q[s] : null);
globalThis.__warns = []; console.warn = (...a) => { globalThis.__warns.push(String(a[1] ?? "")); };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/cables.js").href);
const svgEl = () => ({ attrs: {}, innerHTML: "", live: null, setAttribute(k, v) { this.attrs[k] = v; }, querySelector(sel) { return sel === ".topology-cable.live" ? this.live : null; }, insertAdjacentHTML(_p, h) { this.innerHTML += h; } });
const svg = () => globalThis.__fields.topologyCables;
const SEL = {
  board: ".topology-board",
  handle: (h, a, r) => `[data-topology-route-handle][data-host-id="${h}"][data-agent-id="${a}"][data-route-role="${r}"]`,
  rin: (id) => `[data-topology-router-input][data-router-id="${id}"]`,
  rout: (id) => `[data-topology-router-output][data-router-id="${id}"]`,
  llama: (port) => `[data-topology-llama-input][data-llama-port="${port}"]`,
  cloud: (pool) => `[data-topology-cloud-input][data-pool-id="${pool}"]`,
};
const TOPO = (extra = {}) => ({
  clients: [{ id: "box-a", name: "Box A", agents: [{ id: "hotel" }] }],
  assignments: { "box-a": { assignments: [{ agentId: "hotel", routes: [
    { role: "primary", proxyId: "ctl:proxy:23001" }, { role: "fallback", proxyId: "ctl:proxy:23002" }, { role: "embeddings", proxyId: "ctl:proxy:23009" }] }] } },
  proxies: [
    { id: "ctl:proxy:23001", port: 23001, routerId: "router:default", lastRequestAt: 1, priority: 2 },
    { id: "ctl:proxy:23002", port: 23002, routerId: "router:default" },
    { id: "ctl:proxy:23009", port: 23009 },
  ],
  routers: [{ id: "router:default", outputs: [
    { id: "srv:22001", upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22001 },
    { id: "cb:terra", upstreamType: "cloud", providerId: "terra" },
    { id: "srv:22077", upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22077 },
  ] }],
  ...extra,
});
const DOM = () => { globalThis.__q = {
  [SEL.board]: R(0, 0, 1000, 600),
  [SEL.handle("box-a", "hotel", "primary")]: R(100, 100), [SEL.handle("box-a", "hotel", "fallback")]: R(100, 140), [SEL.handle("box-a", "hotel", "embeddings")]: R(100, 180),
  [SEL.rin("router:default")]: R(400, 120), [SEL.rout("router:default")]: R(440, 120),
  [SEL.llama(22001)]: R(700, 100), [SEL.cloud("terra")]: R(700, 200),
}; };
const MON = (port) => ({ latest: { agentProxies: { agents: { [String(port)]: { port, active: [{ phase: "running", port }], recent: [] } } } } });
const reset = () => { st.setState({ config: {} }); st.setTopology(TOPO()); st.ui.latestSystemMonitor = null; DOM();
  globalThis.__fields = { topologyCables: svgEl() }; globalThis.__warns.length = 0; m.cableDrops.length = 0; };
reset();
const paths = () => (svg().innerHTML.match(/<path class="([^"]*)"/g) || []).map((x) => x.slice(13, -1).replace(/\s+/g, " ").trim());
const out = {};
"""

PINS = [
    # ── geometry ──
    ("cable_path_bezier", '', 'm.topologyCablePath({ x: 0, y: 0 }, { x: 200, y: 100 })', '"M 0 0 C 96 0, 104 100, 200 100"', "кривая: плечо 48% расстояния по x"),
    ("cable_path_min_arm", '', 'm.topologyCablePath({ x: 0, y: 0 }, { x: 20, y: 50 })', '"M 0 0 C 48 0, -28 50, 20 50"', "boundary: близкие точки — плечо не короче 48"),
    ("svg_path_and_title", '', '[m.topologySvgPath({ x: 1, y: 2 }, { x: 3, y: 4 }, "c x", "a<b"), m.topologySvgPath(null, { x: 1, y: 1 }, "c"), m.topologySvgPath({ x: 1, y: 1 }, undefined, "c")]',
     '["<path class=\\"c x\\" d=\\"M 1 2 C 49 2, -45 4, 3 4\\"><title>a&lt;b</title></path>","",""]', "путь с экранированной подсказкой; без любой из точек — пусто"),
    ("svg_text", '', '[m.topologySvgText({ x: 5, y: 6 }, "<hi>"), m.topologySvgText({ x: 5, y: 6 }, ""), m.topologySvgText(null, "x")]',
     '["<text class=\\"topology-cable-label\\" x=\\"5\\" y=\\"6\\">&lt;hi&gt;</text>","",""]', "подпись экранирована; без текста или точки — пусто"),
    ("point_for_sides", '', '[m.topologyPointFor(R(100, 100, 40, 20), "left"), m.topologyPointFor(R(100, 100, 40, 20), "right"), m.topologyPointFor(R(100, 100, 40, 20))]',
     '[{"x":100,"y":110},{"x":140,"y":110},{"x":120,"y":110}]', "точка якоря относительно доски: левый край, правый край, центр; y — середина"),
    ("point_for_board_offset_and_missing", '', '(() => { globalThis.__q[SEL.board] = R(10, 20, 500, 500); const a = m.topologyPointFor(R(100, 100, 40, 20), "left"); delete globalThis.__q[SEL.board]; return [a, m.topologyPointFor(R(1, 1), "left"), m.topologyPointFor(null)]; })()',
     '[{"x":90,"y":90},null,null]', "смещение доски вычитается; без доски или элемента — null"),
    # ── classes ──
    ("proxy_and_route_class", '', '[m.topologyProxyClass("ctl:proxy:23001"), m.topologyProxyClass(""), m.topologyRouteClass("box a", "hotel", undefined)]', '["proxy-ctl-proxy-23001","proxy-","route-box-a-hotel-"]',
     "классы: всё, кроме [A-Za-z0-9_-], — в дефис"),
    ("accent_deterministic", '', '[m.topologyAccentStyle("hotel") === m.topologyAccentStyle("hotel"), m.topologyAccentStyle("hotel") !== m.topologyAccentStyle("scout"), m.topologyAccentColor("hotel", 0.5).endsWith("/ 0.5)"), m.topologyAccentStyle("") === m.topologyAccentStyle("item"), /^--topology-accent: hsl\\(\\d+ 70% 62%\\); --topology-accent-soft: hsl\\(\\d+ 70% 62% \\/ 0\\.13\\);$/.test(m.topologyAccentStyle("x"))]',
     '[true,true,true,true,true]', "акцент по ключу: детерминирован, разный для разных ключей, пустой ключ = item, формат стиля"),
    # ── drawTopologyCables ──
    ("draw_paths_and_viewbox", '', '(() => { m.drawTopologyCables(); return [svg().attrs.viewBox, paths().length]; })()',
     '["0 0 1000 600",2]', "viewBox из доски; нарисованы 2 кабеля клиента; negative: пулов нет — от карточки канбана канатов нет: "
     "канат к машине или провайдеру значит, что туда ведёт строка пула"),
    ("draw_segment1_classes", '', '(() => { m.drawTopologyCables(); return paths().slice(0, 2); })()',
     '["topology-cable primary idle priority proxy-ctl-proxy-23001 route-box-a-hotel-primary","topology-cable fallback unverified idle proxy-ctl-proxy-23002 route-box-a-hotel-fallback"]',
     "primary с приоритетом и трафиком — priority, idle без активности; fallback без единого запроса — unverified; классы прокси и маршрута для подсветки"),
    ("draw_unverified_has_title", '', '(() => { m.drawTopologyCables(); return (svg().innerHTML.match(/<title>/g) || []).length; })()', '1', "подсказка «не подтверждён» стоит ровно на непроверенном кабеле"),
    ("draw_no_cable_leaves_the_kanban", '', '(() => { m.drawTopologyCables(); return [paths().filter((c) => c.includes(" router")), m.cableDrops.filter((d) => d.what.startsWith("router")).length]; })()',
     '[[],0]', "negative: выходы роутера — ячейка и пул — сами канатов на главной доске не получают и потерянными не записаны: "
     "строки пулов на канбане, а от карточки канбана канат идёт к машине или провайдеру целиком"),
    ("draw_active_cable_lights", 'st.ui.latestSystemMonitor = MON(23001);', '(() => { m.drawTopologyCables(); return paths()[0]; })()',
     '"topology-cable primary priority activity-active health-ok proxy-ctl-proxy-23001 route-box-a-hotel-primary"', "активный запрос на порту — кабель без idle, с классами активности и здоровья (анимируется)"),
    ("draw_drops_named_with_reasons", '', '(() => { m.drawTopologyCables(); return m.cableDrops.map((d) => ({ ...d })); })()',
     '[{"what":"box-a/hotel embeddings -> router","routeHandleFound":true,"proxyId":"ctl:proxy:23009","proxyResolved":true,"routerId":"(unresolved)","routerInputFound":false}]',
     "defect-class: невырисованный кабель НАЗВАН — и почему: прокси без роутера. Выход к ячейке без её карточки не назван: "
     "главная доска показывает машины без ячеек, ячейки — в окне машины (2026-10-11)"),
    ("draw_hidden_cell_put_away", "globalThis.__q['[data-cell-hidden-port=\"22077\"]'] = {};",
     '(() => { m.drawTopologyCables(); return [m.cableDrops.map((d) => d.what), paths().length]; })()',
     '[["box-a/hotel embeddings -> router"],2]',
     "ячейку спрятал глаз её машины — ничего не меняется: канатов к ячейкам на главной доске нет, и потерянными они не записаны"),
    ("draw_cell_cable_put_away_on_the_main_board", "delete globalThis.__q[SEL.cloud(\"terra\")];",
     '(() => { m.drawTopologyCables(); return [m.cableDrops.map((d) => d.what), paths().length]; })()',
     '[["box-a/hotel embeddings -> router"],2]',
     "главная доска не рисует ни ячеек (окно машины, 2026-10-11), ни пулов (канбан, 2026-10-12): выход к пулу без его карточки "
     "не рисуется и потерянным не записан"),
    ("draw_nothing_in_a_machine_window", "",
     'await (async () => { const v = (await import(pathToFileURL(process.env.JS_ROOT + "/board-view.js").href)).BOARD_VIEW; v.machine = "box-a";'
     ' try { m.drawTopologyCables(); return [svg().innerHTML, m.cableDrops.length, svg().attrs.viewBox]; } finally { v.machine = null; } })()',
     '["",0,"0 0 1000 600"]',
     "окно машины показывает одну её карточку: кабелей нет — клиенты и узел канбана в странице скрыты, кабель к ним шёл бы из угла доски; "
     "и потерянными они не записаны"),
    # ── a client of the entry (2026-10-11, the owner: its activity on the cables, as the agents' was;
    #    2026-10-12: one cable goes on from a client — to its set of models, which stands on the kanban) ──
    ("draw_client_to_the_kanban",
     'st.topology.proxies.push({ id: "ctl:proxy:23050", port: 23050, kind: "consumer", label: "Hermes", routerId: "router:default", set: "main" });'
     ' globalThis.__q[\'[data-topology-proxy-output][data-proxy-id="ctl:proxy:23050"]\'] = R(100, 260); globalThis.__q[SEL.cloud("luna")] = R(700, 300);',
     '(() => { m.drawTopologyCables(); const mine = (svg().innerHTML.match(/<path class="[^"]*consumer[^"]*" d="[^"]*"/g) || []);'
     ' return [paths().filter((c) => c.includes("consumer")), mine.map((x) => x.split(\' d="\')[1].slice(0, -1)), m.cableDrops.map((d) => d.what)]; })()',
     '[["topology-cable consumer idle proxy-ctl-proxy-23050"],["M 140 270 C 264.8 270, 275.2 130, 400 130"],["box-a/hotel embeddings -> router"]]',
     "клиент с набором — один кабель от гнезда его карточки ко входу карточки канбана: наборы и пулы стоят на канбане (2026-10-12); "
     "negative: к карточкам пулов кабеля нет — их на главной доске нет"),
    ("draw_client_cable_lit_by_any_of_its_requests",
     'st.topology.proxies.push({ id: "ctl:proxy:23050", port: 23050, kind: "consumer", label: "Hermes", routerId: "", set: "main" });'
     ' st.topology.routers[0].inputs = ["ctl:proxy:23001"];'
     ' globalThis.__q[\'[data-topology-proxy-output][data-proxy-id="ctl:proxy:23050"]\'] = R(100, 260); globalThis.__q[SEL.cloud("luna")] = R(700, 300);'
     ' st.ui.latestSystemMonitor = { latest: { agentProxies: { agents: { "23050": { port: 23050, recent: [],'
     ' active: [{ phase: "running", upstreamType: "llama", providerId: "" }] },'
     ' "23001": { port: 23001, recent: [], active: [{ phase: "running", port: 23001, upstreamType: "cloud", providerId: "terra" }] } } } } };',
     '(() => { const lit = () => { m.drawTopologyCables(); return paths().filter((c) => c.includes("consumer")); };'
     ' const busy = lit(); globalThis.__fields = { topologyCables: svgEl() }; st.ui.latestSystemMonitor.latest.agentProxies.agents["23050"].active = [];'
     ' return [busy, lit()]; })()',
     '[["topology-cable consumer activity-active proxy-ctl-proxy-23050"],["topology-cable consumer idle proxy-ctl-proxy-23050"]]',
     "кабель клиента горит от любого его запроса — и от того, что служит ячейка пула (запись без облака); "
     "negative: запрос чужого порта к тому же пулу его не зажигает"),
    ("draw_client_without_a_set_has_no_cable",
     'st.topology.proxies.push({ id: "ctl:proxy:23050", port: 23050, kind: "consumer", label: "Hermes", routerId: "", set: "", pool: "terra" });'
     ' globalThis.__q[\'[data-topology-proxy-output][data-proxy-id="ctl:proxy:23050"]\'] = R(100, 260);',
     '(() => { m.drawTopologyCables(); return [paths().filter((c) => c.includes("consumer")), m.cableDrops.filter((d) => d.what.startsWith("client")).length]; })()',
     '[[],0]',
     "negative: канат от клиента к набору не проведён — кабеля нет, и потерянным он не записан: его нет и в данных; "
     "старое поле pool доска не читает (1.3.497: контроллер отдаёт set)"),
    ("draw_no_kanban_cable_to_a_busy_pool",
     'st.topology.routers[0].inputs = ["ctl:proxy:23001"];'
     ' st.ui.latestSystemMonitor = { latest: { agentProxies: { agents: { "23001": { port: 23001, recent: [],'
     ' active: [{ phase: "running", port: 23001, upstreamType: "cloud", providerId: "terra" }] } } } } };',
     '(() => { m.drawTopologyCables(); return paths().filter((c) => c.startsWith("topology-cable router")); })()',
     '[]',
     "negative: запрос порта канбана к пулу — каната канбана к пулу на главной доске нет, горящего тоже: пул на канбане"),
    # ── segment 3: the kanban's card → the machines and the providers its pools lead to (the owner, 2026-10-12) ──
    ("draw_kanban_to_its_sources",
     'st.topology.pools = [{ id: "std", steps: [{ kind: "account", accountId: "sub" }, { kind: "output", output: "srv:22001" },'
     ' { kind: "account", accountId: "off", enabled: false }] }];'
     ' globalThis.__stubReturns = { "topology-nodes.machineAt": (a) => ({ key: a === "127.0.0.1" ? "box-c" : a }) };'
     ' globalThis.__q[\'.machine-glance[data-node-id="box-c"] > .node-head\'] = R(700, 300);'
     ' globalThis.__q[\'[data-board-provider="sub"] > .node-head\'] = R(700, 400); globalThis.__q[\'[data-board-provider="off"] > .node-head\'] = R(700, 500);',
     '(() => { m.drawTopologyCables(); const mine = (svg().innerHTML.match(/<path class="topology-cable router[^"]*" d="[^"]*"/g) || []);'
     ' return [paths().filter((c) => c.startsWith("topology-cable router")), mine.map((x) => x.split(\' d="\')[1].slice(0, -1)),'
     ' m.cableDrops.filter((d) => d.what.startsWith("kanban")).length]; })()',
     '[["topology-cable router idle","topology-cable router idle"],["M 480 130 C 585.6 130, 594.4 310, 700 310","M 480 130 C 585.6 130, 594.4 410, 700 410"],0]',
     "от выхода карточки канбана — канат к шапке машины, чья ячейка стоит строкой пула, и к шапке провайдера, которого зовёт строка; "
     "negative: к провайдеру выключенной строки каната нет"),
    ("draw_kanban_cable_lights_where_a_request_runs",
     'st.topology.pools = [{ id: "std", steps: [{ kind: "account", accountId: "sub" }, { kind: "output", output: "srv:22001" }] }];'
     ' globalThis.__stubReturns = { "topology-nodes.machineAt": () => ({ key: "box-c" }) };'
     ' globalThis.__q[\'.machine-glance[data-node-id="box-c"] > .node-head\'] = R(700, 300); globalThis.__q[\'[data-board-provider="sub"] > .node-head\'] = R(700, 400);'
     ' const run = (it) => ({ latest: { agentProxies: { agents: { "23050": { port: 23050, recent: [], active: [{ phase: "running", port: 23050, ...it }] } } } } });',
     '(() => { const draw = (mon) => { st.ui.latestSystemMonitor = mon; m.drawTopologyCables(); return paths().filter((c) => c.startsWith("topology-cable router")); };'
     ' return [draw(run({ upstreamType: "cloud", cloudAccountId: "sub" })), draw(run({ upstreamType: "llama", routedOutputId: "srv:22001" })),'
     ' draw(run({ upstreamType: "llama", routedOutputId: "srv:22077" })), draw(run({ upstreamType: "cloud", cloudAccountId: "other" }))]; })()',
     '[["topology-cable router idle","topology-cable router activity-active"],'
     '["topology-cable router activity-active","topology-cable router idle"],'
     '["topology-cable router idle","topology-cable router idle"],["topology-cable router idle","topology-cable router idle"]]',
     "канат горит, пока туда идёт запрос: к провайдеру — по его аккаунту на запросе, к машине — по выходу её ячейки; "
     "negative: запрос к ячейке, которой нет в пулах, и запрос к другому аккаунту каната не зажигают"),
    ("draw_kanban_cable_drop_named",
     'st.topology.pools = [{ id: "std", steps: [{ kind: "account", accountId: "sub" }] }];',
     '(() => { m.drawTopologyCables(); return m.cableDrops.filter((d) => d.what.startsWith("kanban")).map((d) => ({ ...d })); })()',
     '[{"what":"kanban -> provider sub","kanbanOutputFound":true,"targetFound":false}]',
     "defect-class: канат канбана к провайдеру, чьей карточки нет на доске, не пропал молча — назван, и сказано, чего нет"),
    ("draw_client_cable_drop_named",
     'st.topology.proxies.push({ id: "ctl:proxy:23050", port: 23050, kind: "consumer", label: "Hermes", routerId: "", set: "main" });'
     ' globalThis.__q[\'[data-topology-proxy-output][data-proxy-id="ctl:proxy:23050"]\'] = R(100, 260); globalThis.__q[SEL.rin("router:default")] = null;',
     '(() => { m.drawTopologyCables(); return m.cableDrops.filter((d) => d.what.startsWith("client")).map((d) => ({ ...d })); })()',
     '[{"what":"client Hermes -> kanban","handleFound":true,"kanbanFound":false}]',
     "defect-class: кабель клиента без карточки канбана не пропал молча — назван, и сказано, чего нет"),
    ("draw_drop_warned_once", 'st.topology.assignments["box-a"].assignments[0].routes[2].proxyId = "ctl:proxy:" + Math.random().toString(36).slice(2);',
     '(() => { m.drawTopologyCables(); m.drawTopologyCables(); return [globalThis.__warns.filter((w) => w === "box-a/hotel embeddings -> router").length, m.cableDrops[0].proxyResolved]; })()',
     '[1,false]', "предупреждение в консоль — один раз на новую сигнатуру пропуска (дедуп переживает перерисовки), повторная отрисовка не дублирует"),
    ("draw_drops_rebuilt_each_draw", '', '(() => { m.drawTopologyCables(); globalThis.__q[SEL.rin("router:default")] = null; st.topology.proxies[2].routerId = "router:default"; m.drawTopologyCables(); return [m.cableDrops.length, m.cableDrops.map((d) => d.what)]; })()',
     '[3,["box-a/hotel primary -> router","box-a/hotel fallback -> router","box-a/hotel embeddings -> router"]]',
     "список пропусков пересобирается на каждой отрисовке: пропал вход роутера — пропали все три кабеля клиента"),
    ("draw_ignores_an_old_live_report", 'st.setTopology(TOPO({ clients: [{ id: "box-a", agents: [{ id: "hotel" }], assignments: [{ agentId: "hotel", routes: [{ role: "primary", proxyId: "ctl:proxy:23001" }] }] }] }));',
     '(() => { m.drawTopologyCables(); return paths().slice(0, 2); })()',
     '["topology-cable primary idle priority proxy-ctl-proxy-23001 route-box-a-hotel-primary","topology-cable fallback unverified idle proxy-ctl-proxy-23002 route-box-a-hotel-fallback"]', "negative: живой отчёт, оставшийся в записи от старого скаута, ничего не решает — фолбэк без трафика нарисован как любой другой (unverified), а не «приглушён»"),
    ("draw_without_svg_or_board", '', '(() => { delete globalThis.__fields.topologyCables; m.drawTopologyCables(); globalThis.__fields = { topologyCables: svgEl() }; delete globalThis.__q[SEL.board]; m.drawTopologyCables(); return [svg().innerHTML, m.cableDrops.length]; })()',
     '["",0]', "negative: без svg или без доски — ничего не рисуется и не отмечается"),
    # ── an engine's model as an output (step 2, docs/foreign-engines.md) ──
    ("draw_engine_output_to_its_model",
     'st.topology.routers[0].outputs = [{ id: "eng:abc", upstreamType: "engine", upstreamHost: "10.0.0.5", upstreamPort: 11434, upstreamModel: "qwen3:8b" }]; globalThis.__q[\'[data-topology-engine-input][data-output-id="eng:abc"]\'] = R(700, 300);',
     '(() => { m.drawTopologyCables(); return [paths().slice(2), m.cableDrops.length]; })()',
     '[[],1]',
     "negative: выход модели движка на главной доске каната не получает — даже при строке этой модели: он на канбане; пропуск один — "
     "кабель эмбеддингов без роутера"),
    ("draw_engine_output_not_on_a_cell_port",
     'st.topology.routers[0].outputs = [{ id: "eng:abc", upstreamType: "engine", upstreamHost: "10.0.0.5", upstreamPort: 11434, upstreamModel: "qwen3:8b" }]; globalThis.__q[SEL.llama(11434)] = R(700, 300);',
     '(() => { m.drawTopologyCables(); return [paths().slice(2), m.cableDrops.filter((d) => d.what.includes("eng:")).length]; })()',
     '[[],0]',
     "negative: у движка нет строки модели на доске — кабель не цепляется к ячейке на том же порту; строка модели живёт на карточке "
     "машины, а её главная доска не рисует целиком (2026-10-11) — кабель убран, не записан потерянным"),
    ("live_cable_replaces_previous", '', '(() => { const prev = { removed: 0, remove() { this.removed += 1; } }; svg().live = prev; m.drawLiveTopologyCable(300, 250); return [prev.removed, paths(), svg().innerHTML.includes("M 140 110 C")]; })()',
     '[1,["topology-cable live"],true]', "живой кабель при перетаскивании: прежний удалён, новый от правого края источника к курсору"),
    ("live_cable_without_board", 'delete globalThis.__q[SEL.board];', '(() => { m.drawLiveTopologyCable(300, 250); return svg().innerHTML; })()', '""', "negative: без доски живой кабель не рисуется"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    # The floor catches a list cut short by accident, so it follows the list: 20
    # since the apply-state and cable-status helpers went (2026-09-24).
    if len(PINS) < 20:
        print(f"js cables FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js cables: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_cables.tmp.mjs"
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
        print(f"js cables FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("кабели доски: геометрия, классы, отчёт о невырисованных:")
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
    print(f"js cables OK: настоящий модуль в node, {len(PINS)} пинов кабелей значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
