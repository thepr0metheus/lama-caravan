#!/usr/bin/env python3
"""Snapshot of static/js/charts.js — what the charts COMPUTE, not what they draw.

The module is 1154 lines of canvas rendering, and the drawing itself isn't
covered by the snapshot. What is covered is everything that produces a
value: classifying a route's activity from a sample (failed >
client_disconnected > preempting > degraded > active > slow > recent >
queued — a state priority order, where nothing lower overrides something
higher), filtering by node (a request counts toward the node that actually
SERVED it, the cloud never lights up a GPU), a node's route captions (direct
ones and ones through the router graph), the incident list (saved ones —
with a 24h cutoff and no fallback; otherwise derived from samples with
dedup), rendering the incident panel through a dict-based DOM, buckets by
canvas width, the sparkline, token speeds with their fallback paths, formats.

The module is real; so are `topology-activity` (incident classification) and
`topology-proxies`; `polling.formatTps` is stubbed via __stubReturns.

Run: python3 scripts/test_js_charts.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402
from cell_speed_cases import HELP, LAST  # noqa: E402

STUBS = ("polling,canvas,topology-dnd,topology-render,dialogs,cloud,cables,history,favorites,config-locator,"
         "system-panels,onboarding,onboarding-tours,usage-stats,dialog-llamas,models-page,system-page,memory,"
         "command-preview,llama-edit,remote-cells,topology-nodes,topology-modals,routers")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
Date.now = () => 1_700_000_100_000;
const m = await import(pathToFileURL(process.env.JS_ROOT + "/charts.js").href);
const el = () => ({ innerHTML: "", textContent: "" });
globalThis.CSS = { escape: (value) => String(value) };
document.body.appendChild = () => {};
const tokenCanvas = () => {
  const moves = [];
  const ctx = new Proxy({ measureText: (v) => ({ width: String(v).length * 6 }),
    moveTo(x, y) { moves.push([this.strokeStyle, x, y]); }, lineTo(x, y) { moves.push([this.strokeStyle, x, y]); } },
    { get(target, key) { return key in target ? target[key] : () => {}; } });
  return { width: 320, height: 120, offsetWidth: 320, moves, getContext: () => ctx,
    getBoundingClientRect: () => ({ width: 320, height: 120 }), addEventListener: () => {} };
};
const NODES = () => [
  { id: "box-c", role: "host", controllerMachine: true, ip: "10.0.0.1", servers: [{ port: 22001 }, { port: 22002, clientIp: "10.0.0.1" }] },
  { id: "box-a", role: "host", ip: "10.0.0.5", servers: [{ port: 22011 }] },
  { id: "box-b", role: "host", ip: "10.0.0.6", servers: [] },
];
const PROXIES = () => [
  { id: "p1", port: 23001, label: "hotel", upstreamHost: "127.0.0.1", upstreamPort: 22001 },
  { id: "p2", port: 23003, label: "scout", upstreamHost: "10.0.0.5", upstreamPort: 22011 },
  { id: "p3", port: 23005, label: "graphy", upstreamHost: "127.0.0.1", upstreamPort: 8080, routerId: "router:a" },
  { id: "p4", port: 23007, label: "cloudy", upstreamType: "cloud", providerId: "cb:terra", upstreamHost: "10.0.0.5", upstreamPort: 22011 },
  { id: "p5", port: 23009, label: "", upstreamHost: "10.0.0.5", upstreamPort: 22011 },
];
const ROUTERS = () => [{ id: "router:a", outputs: [{ id: "srv:22011", upstreamHost: "10.0.0.5", upstreamPort: 22011 }] }];
const TOPO = (extra = {}) => ({ proxies: PROXIES(), clients: [], routers: ROUTERS(), assignments: {}, nodes: NODES(), ...extra });
const S = (time, corr) => ({ time, correlatedActivity: corr });
const CV = () => { const texts = [], fills = [];
  const ctx = new Proxy({ fillText(v) { texts.push(String(v)); }, fillRect() { fills.push(String(this.fillStyle)); } },
    { get(target, key) { return key in target ? target[key] : () => {}; }, set(target, key, v) { target[key] = v; return true; } });
  return { width: 320, height: 74, offsetWidth: 320, style: {}, title: "", texts, fills, getContext: () => ctx,
    getBoundingClientRect() { return { width: 320, height: parseFloat(this.style.height) || 74 }; }, addEventListener: () => {} }; };
const reset = () => { st.setState({ config: {} }); st.setTopology(TOPO()); st.ui.latestSystemMonitor = null;
  globalThis.__fields = { topologyIncidents: el(), topologyIncidentsMeta: el() };
  globalThis.__stubReturns = { "polling.formatTps": (v) => `${v} t/s` }; };
reset();
const out = {};
"""

PINS = [
    # ── formats ──
    ("format_rate", '', '[m.formatRate(0), m.formatRate(999), m.formatRate(1536), m.formatRate(3 * 1024 ** 2), m.formatRate(2 * 1024 ** 3), m.formatRate(NaN), m.formatRate("x")]',
     '["0 B/s","999 B/s","1.5 KB/s","3.00 MB/s","2.00 GB/s","0 B/s","0 B/s"]', "байты в секунду с порогами; мусор — 0 B/s"),
    ("fmt_ms", '', '[m._fmtMs(0), m._fmtMs(999), m._fmtMs(1000), m._fmtMs(1550), m._fmtMs(undefined)]', '["0ms","999ms","1.0s","1.6s","0ms"]', "миллисекунды до секунды, потом секунды с десятой"),
    ("format_event_time", '', '[m.formatEventTime(""), m.formatEventTime(0), m.formatEventTime("2026-09-05T10:00"), typeof m.formatEventTime(1700000000)]', '["","","2026-09-05T10:00","string"]',
     "пусто — пусто; строка — как есть; число — локальное время (строка, локаль не пинится)"),
    ("system_samples_and_latest", '', '[m.systemSamples({ samples: [1, 2] }), m.systemSamples({ samples: "no" }), m.systemSamples(null), m.latestSample([{ a: 1 }, { a: 2 }]), m.latestSample([])]',
     '[[1,2],[],[],{"a":2},{}]', "сэмплы только массивом; последний — последний; пусто — {}"),
    ("tps_from_tokens_only", '',
     '[m.topologyPromptTps({ llamaActivity: { lastTiming: { promptTps: 10 } }, tokens: { promptTokensPerSecond: 99 } }), m.topologyPromptTps({ correlatedActivity: { llamaServer: { lastTiming: { promptTps: 20 } } } }), m.topologyPromptTps({ tokens: { promptTokensPerSecond: 30 } }), m.topologyPromptTps({}), m.topologyEvalTps({ tokens: { predictedTokensPerSecond: 40 } }), m.topologyEvalTps({ llamaActivity: { lastTiming: { evalTps: 7 } } }), m.topologyEvalTps(null)]',
     '[99,null,30,null,40,null,null]', "скорость точки — только tokens.*PerSecond; отсутствие — null, не ноль; negative: lastTiming одиночного сервера контроллера больше не читается и не побеждает tokens"),
    ("main_token_info", '', 'm._mainTokenInfo({ time: 5, tokens: { predictedTokensPerSecond: 1, genTokens: 2, genMs: 3, promptTokensPerSecond: 4, promptTokens: 5, promptMs: 6, cacheTokens: 7 } })',
     '{"genTps":1,"genTokens":2,"genMs":3,"promptTps":4,"promptTokens":5,"promptMs":6,"cacheTokens":7,"time":5}', "адаптер сэмпла контроллера к полям подсказки"),
    ("chart_size_dpr_and_floors", '',
     '(() => { const c = { width: 0, height: 0, getBoundingClientRect: () => ({ width: 400.4, height: 50 }) }; globalThis.devicePixelRatio = 2; const r = m.chartSize(c); delete globalThis.devicePixelRatio; return [r, c.width, c.height]; })()',
     '[{"width":801,"height":120,"dpr":2},801,120]', "размер холста: ширина × dpr с округлением, высота не ниже 120; атрибуты холста переписаны"),
    ("route_buckets", '',
     '(() => { const r = m._routeBuckets(Array.from({ length: 10 }, (_, i) => i), { offsetWidth: 4 }); return [r.buckets.length, r.buckets[0], r.barW]; })()',
     '[4,[0,1,2],1]', "10 сэмплов на 4 колонки — бакеты по 3; на узком холсте ширина бара зажата снизу единицей"),
    ("route_buckets_wide", '', '(() => { const r = m._routeBuckets([1, 2, 3], { offsetWidth: 320 }); return [r.buckets.length, r.barW > 100]; })()', '[3,true]', "широкий холст: бакет на сэмпл"),
    ("mini_sparkline", '', '[m.miniSparklineSvg([0, 5, 10], "red", 10).includes(\'points="0.0,14.0 36.0,7.0 72.0,0.0"\'), m.miniSparklineSvg([5], "red"), m.miniSparklineSvg(["x", "y"], "red")]', '[true,"",""]',
     "спарклайн: точки по ширине 72 и высоте 14; меньше двух чисел — пусто"),
    # ── nodes ──
    ("endpoint_set_controller_adds_loopback", '', '[[...m.nodeEndpointSet(NODES()[0])].sort(), [...m.nodeEndpointSet({ id: "controller", role: "controller", ip: "10.0.0.1", servers: [{ port: 22001 }] })]]', '[["10.0.0.1:22001","10.0.0.1:22002","127.0.0.1:22001","127.0.0.1:22002"],["10.0.0.1:22001"]]',
     "машина контроллера (controllerMachine узла): каждый порт и по IP, и по 127.0.0.1 — прокси на ней ходит к её ячейкам по loopback; negative: узел с ролью «controller» (такого нет с шага 6.9) loopback больше не получает"),
    ("endpoint_set_machine_models",
     'st.setTopology({ ...TOPO(), routers: [{ id: "router:default", outputs: ['
     ' { id: "mm:a", upstreamType: "machine", hostId: NODES()[1].id, upstreamHost: "10.0.0.5", upstreamPort: 8092, upstreamModel: "gemma" },'
     ' { id: "mm:b", upstreamType: "machine", hostId: "elsewhere", upstreamHost: "10.0.0.7", upstreamPort: 8092, upstreamModel: "ear" }] }] });',
     '[...m.nodeEndpointSet(NODES()[1])].sort()',
     '["10.0.0.5:22011","10.0.0.5:8092/gemma"]',
     "машина со входом (1.3.506): её модели — свои очереди «адрес:порт/модель», запрос к модели — её; negative: модель другой "
     "машины — не её"),
    ("endpoint_set_client_and_empty", '', '[[...m.nodeEndpointSet(NODES()[1])], [...m.nodeEndpointSet(NODES()[2])], [...m.nodeEndpointSet(null)]]', '[["10.0.0.5:22011"],[],[]]', "клиент: только свой IP; без серверов — пусто; null — пусто"),
    ("activity_filter", '', '[Object.keys(m.nodeActivityFilter("box-a")), [...m.nodeActivityFilter("box-a").endpoints], [...m.nodeActivityFilter("box-c").endpoints].length, m.nodeActivityFilter("ghost")]',
     '[["endpoints"],["10.0.0.5:22011"],4,null]', "фильтр узла — только концы его ячеек (у машины контроллера и loopback); неизвестный узел — null"),
    ("node_route_labels_direct_and_via_graph", '', '[m.nodeRouteLabels("box-a"), m.nodeRouteLabels("box-c"), m.nodeRouteLabels("box-b"), m.nodeRouteLabels("ghost")]',
     '[["graphy","scout"],["hotel"],[],[]]', "подписи: прямой upstream и через выход роутера; облако и пустая подпись не считаются; узел без ячеек — пусто; без трафика все тихие — по имени (порядок лейна), а не по порядку конфига"),
    ("ordered_route_labels_live_first_then_name", 'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:1", port: 1, label: "zeta", lastRequestAt: Date.now() / 1000 - 60 }, { id: "skynet:proxy:2", port: 2, label: "alpha", lastRequestAt: Date.now() / 1000 - 3600 * 13 }, { id: "skynet:proxy:3", port: 3, label: "Mid", lastRequestAt: Date.now() / 1000 - 3600 }, { id: "skynet:proxy:4", port: 4, label: "" }, { id: "skynet:proxy:5", port: 5, label: "alpha" }, { id: "skynet:proxy:6", port: 6, label: "beta" }] });',
     'm.orderedRouteLabels(st.topology.proxies)', '["Mid","zeta","alpha","beta"]',
     "строки трафика — как карточки клиентов: живые (запрос за 12 ч: Mid, zeta) первыми по имени без учёта регистра, тихие (alpha 13 ч, beta никогда) после; пустая подпись без строки, одноимённые — одна строка"),
    ("ordered_route_labels_follow_the_client_cards", 'st.setTopology({ ...TOPO(), proxies: [{ id: "skynet:proxy:23001", port: 23001, label: "sierra Hemi proxy", lastRequestAt: Date.now() / 1000 - 60 },{ id: "skynet:proxy:23002", port: 23002, label: "fallback hemi" },{ id: "skynet:proxy:23117", port: 23117, label: "Charlie primary" },{ id: "skynet:proxy:8083", port: 8083, label: "proton-ui" }], clients: [{ id: "hotel", name: "hotel", manual: true, agents: [{ id: "hotel" }] },{ id: "Charlie", name: "Charlie", agents: [{ id: "Charlie" }] }], assignments: { hotel: { assignments: [{ agentId: "hotel", routes: [{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e" },{ role: "fallback", proxyId: "skynet:proxy:23002", endpoint: "e" }] }] }, Charlie: { assignments: [{ agentId: "Charlie", routes: [{ role: "primary", proxyId: "skynet:proxy:23117", endpoint: "e" }] }] } } });',
     'm.orderedRouteLabels(st.topology.proxies)',
     '["sierra Hemi proxy","fallback hemi","Charlie primary","proton-ui"]',
     "порядок строк трафика — порядок КАРТОЧЕК клиентов, а не подписей маршрутов: живой агент (hotel) первым со своими портами в порядке ролей (primary, потом fallback), затем тихий Charlie, а порт, которого не называет ни одна карточка, — последним"),
    ("ordered_route_labels_quiet_go_by_agent_name", 'st.setTopology({ ...TOPO(), proxies: [{ id: "skynet:proxy:23001", port: 23001, label: "sierra Hemi proxy" },{ id: "skynet:proxy:23002", port: 23002, label: "fallback hemi" },{ id: "skynet:proxy:23117", port: 23117, label: "Charlie primary" },{ id: "skynet:proxy:8083", port: 8083, label: "proton-ui" }], clients: [{ id: "hotel", name: "hotel", manual: true, agents: [{ id: "hotel" }] },{ id: "Charlie", name: "Charlie", agents: [{ id: "Charlie" }] }], assignments: { hotel: { assignments: [{ agentId: "hotel", routes: [{ role: "primary", proxyId: "skynet:proxy:23001", endpoint: "e" },{ role: "fallback", proxyId: "skynet:proxy:23002", endpoint: "e" }] }] }, Charlie: { assignments: [{ agentId: "Charlie", routes: [{ role: "primary", proxyId: "skynet:proxy:23117", endpoint: "e" }] }] } } });',
     'm.orderedRouteLabels(st.topology.proxies)',
     '["Charlie primary","sierra Hemi proxy","fallback hemi","proton-ui"]',
     "boundary: без трафика обе карточки тихие и идут по имени АГЕНТА (Charlie раньше hotel) — если бы сортировали по подписи маршрута, «sierra Hemi proxy» ушла бы под букву s, и лейн с полосой разошлись бы"),
    ("ordered_route_labels_use_the_shown_agent_name", 'st.setTopology({ ...TOPO(), proxies: ['
     '{ id: "skynet:proxy:23101", port: 23101, label: "port of aaa" },'
     '{ id: "skynet:proxy:23102", port: 23102, label: "port of zzz" }], '
     'clients: [{ id: "h1", name: "h1", agents: [{ id: "aaa", name: "zeta" }, { id: "zzz", name: "beta" }] }], '
     'assignments: { h1: { assignments: ['
     '{ agentId: "aaa", routes: [{ role: "primary", proxyId: "skynet:proxy:23101", endpoint: "e" }] },'
     '{ agentId: "zzz", routes: [{ role: "primary", proxyId: "skynet:proxy:23102", endpoint: "e" }] }] } } });',
     'm.orderedRouteLabels(st.topology.proxies)',
     '["port of zzz","port of aaa"]',
     "порядок берёт ПОКАЗАННОЕ имя агента, а не его id: агент zzz подписан «beta» и идёт раньше агента aaa, подписанного «zeta» — по id вышло бы наоборот, и лейн с полосой снова разошлись бы, теперь на псевдонимах"),
    # ── the clients' activity strip (2026-10-11, the owner: "the chart where the clients' recent activity was seen") ──
    ("client_activity_rows",
     'st.setTopology({ ...TOPO(), proxies: [{ id: "skynet:proxy:23010", port: 23010, kind: "consumer", label: "Zed" },'
     ' { id: "skynet:proxy:23011", port: 23011, kind: "consumer", label: "hermes" },'
     ' { id: "skynet:proxy:23003", port: 23003, label: "alpha" }] });',
     'm.clientActivityLabels()',
     '["hermes","Zed","alpha"]',
     "строки графика клиентов: клиенты входа по имени, как стоят их карточки, затем порты старых клиентов"),
    # ── each client's row on its own card (2026-10-12, the owner: the strip under the clients moved onto them) ──
    ("client_activity_needs_a_card_and_names_no_data",
     '',
     '(() => { const c = CV(); c.dataset = { consumerActivity: "Zed" };'
     ' const none = m.drawClientActivity({ querySelectorAll: () => [] }); const one = m.drawClientActivity({ querySelectorAll: () => [c] });'
     ' return [none, one, c.style.height, c.texts, c.fills.includes("#050607")]; })()',
     '[0,1,"16px",["no data"],true]',
     "строка на карточке клиента: карточек нет — рисовать нечего; одна — одна строка ровно в свою высоту, на тёмном фоне, "
     "как была полоса (владелец, 2026-10-12: серая полоса на фоне карточки ничего не говорила); negative: монитор ещё не "
     "ответил — сказано «no data», а не пустая строка, которая читалась бы как тихий клиент"),
    ("client_activity_row_lights_a_cloud_request",
     'st.setTopology({ ...TOPO(), proxies: [{ id: "skynet:proxy:23010", port: 23010, kind: "consumer", label: "Zed" },'
     ' { id: "skynet:proxy:23011", port: 23011, kind: "consumer", label: "hermes" }] });'
     ' st.ui.latestSystemMonitor = { samples: [S(1, { activeRequests: [{ label: "Zed", isCloud: true, phase: "streaming" }] })] };',
     '(() => { const zed = CV(), her = CV(); zed.dataset = { consumerActivity: "Zed" }; her.dataset = { consumerActivity: "hermes" };'
     ' const n = m.drawClientActivity({ querySelectorAll: () => [zed, her] }); const lit = m.topologyRouteActivityColor("Zed", "cloud_active");'
     ' return [n, zed.texts, her.texts, zed.fills.filter((f) => f === lit).length, her.fills.filter((f) => f === lit).length,'
     ' zed.title === her.title && zed.title.length > 0]; })()',
     '[2,[],["no requests in 1 min"],1,0,true]',
     "запрос клиента входа к пулу (облако) виден на строке его карточки палочкой — машины его не показывали: их график "
     "только о своих ячейках; имени на строке нет — оно в шапке карточки, а подсказка говорит, что откроет щелчок; "
     "negative: у тихого клиента заливки нет, и строка говорит словами, что запросов не было и за какое окно"),
    ("client_activity_idle_names_its_window",
     'st.ui.latestSystemMonitor = { samples: [S(1000, {}), S(1300, {}), S(1600, {})] };',
     '(() => { const c = CV(); c.dataset = { consumerActivity: "Zed" }; m.drawClientActivity({ querySelectorAll: () => [c] }); return c.texts; })()',
     '["no requests in 10 min"]',
     "тихий клиент: строка говорит, за какое окно запросов не было — длина окна из отсчётов монитора (600 с — 10 мин)"),
    ("quiet_strip_without_idle_words_says_nothing_more",
     '',
     '(() => { const c = CV(); m.drawTopologyRouteHistory([S(1, {})], [[S(1, {})]], 4, c, { routes: ["a"] }); return c.texts; })()',
     '["a"]',
     "negative: полоса без своих слов для тишины (машины, окно активности) пишет только имена строк — слова «нет "
     "запросов» есть лишь у строки на карточке клиента"),
    ("client_activity_drawn_on_every_sample",
     'st.setTopology({ ...TOPO(), nodes: [], proxies: [{ id: "skynet:proxy:23010", port: 23010, kind: "consumer", label: "Zed" }] });'
     ' st.ui.latestSystemMonitor = { samples: [S(1, {})] };',
     '(() => { const c = CV(); c.dataset = { consumerActivity: "Zed" }; const keep = document.querySelectorAll;'
     ' document.querySelectorAll = (sel) => (sel === "canvas[data-consumer-activity]" ? [c] : (keep ? keep.call(document, sel) : []));'
     ' try { m.drawTopologyGpuHistory(); } finally { document.querySelectorAll = keep; } return [c.style.height, c.fills.length > 0]; })()',
     '["16px",true]',
     "строки клиентов на карточках перерисовываются с каждым отсчётом монитора, вместе с остальными графиками доски"),
    ("route_strip_drawn_at_its_own_height",
     '',
     '(() => { globalThis.devicePixelRatio = 2; try { const c = CV(); m.drawTopologyRouteHistory([S(1, {})], [[S(1, {})]], 4, c, { routes: ["a", "b"] });'
     ' const other = { width: 0, height: 0, getBoundingClientRect: () => ({ width: 160, height: 43 }) };'
     ' return [c.style.height, c.height, m.chartSize(other).height]; } finally { delete globalThis.devicePixelRatio; } })()',
     '["43px",86,120]',
     "полоса строк рисуется ровно в свою высоту на странице (43 px × dpr 2 = 86): раньше рисунок был не ниже 120 и сжимался "
     "в 43 — строки и имена сплющены; negative: остальные графики сохраняют пол 120"),
    ("route_window_hover_reads_its_own_rows",
     'st.ui.latestSystemMonitor = { samples: [S(1, {})] };',
     '(() => { const samples = m.systemSamples(st.ui.latestSystemMonitor); const before = m._routeActivityDrawState;'
     ' m.drawTopologyRouteHistory(samples, [samples], 4, CV(), { routes: ["a"] }); const afterStrip = m._routeActivityDrawState;'
     ' m.drawTopologyRouteHistory(samples, [samples], 4, CV(), { routes: ["a", "b"], hover: true });'
     ' return [afterStrip === before, m._routeActivityDrawState.routes]; })()',
     '[true,["a","b"]]',
     "подсказка окна читает геометрию только своего рисунка: полоса (машины, клиентов), нарисованная после окна, её больше "
     "не перехватывает — раньше подсказка окна называла строки чужого графика"),
    ("client_window_whole_lists_the_strips_rows",
     'st.setTopology({ ...TOPO(), proxies: [{ id: "skynet:proxy:23010", port: 23010, kind: "consumer", label: "Zed" },'
     ' { id: "skynet:proxy:23003", port: 23003, label: "alpha" }] }); st.ui.latestSystemMonitor = { samples: [S(1, {})] };',
     '(() => { const title = { textContent: "" }; globalThis.__fields.routeActivityOverlay = { hidden: true, querySelector: () => title };'
     ' globalThis.__fields.routeActivityModalCanvas = CV(); globalThis.__fields.routeActivityLegend = { innerHTML: "" };'
     ' m.openRouteActivityModal(null); return [title.textContent, m._routeActivityDrawState.routes, m.clientActivityLabels()]; })()',
     '["Client activity",["Zed","alpha"],["Zed","alpha"]]',
     "окно целиком (⤢ у полосы клиентов) — «Client activity» с теми же строками, что у полосы: один список на оба"),
    # ── route activity from a sample ──
    ("activity_priority", '', '["failed","client_disconnected","preempting","degraded","active","cloud_active","slow","recent","cloud_recent","queued","",null].map(m.topologyRouteActivityPriority)',
     '[8,7,6,5,4,4,3,2,2,1,0,0]', "приоритет состояний сверху вниз; неизвестное — 0"),
    ("activity_set_keeps_higher", '', '(() => { const mp = new Map(); m.topologyRouteActivitySet(mp, "r", "queued"); m.topologyRouteActivitySet(mp, "r", "failed"); m.topologyRouteActivitySet(mp, "r", "active"); m.topologyRouteActivitySet(mp, "", "active"); return [mp.get("r"), mp.size]; })()',
     '["failed",1]', "нижнее состояние не затирает верхнее; пустой маршрут не пишется"),
    ("activity_for_sample_states", '',
     '(() => { const a = m.topologyRouteActivityForSample(S(100, { activeRequests: [{ label: "q", phase: "queued" }, { label: "a" }, { label: "c", isCloud: true }, { label: "p", phase: "preempting" }, { label: "f", status: "502" }, { label: "d", error: "client disconnected" }], recentRequests: [{ label: "r", finishedAt: 99 }, { label: "s", finishedAt: 100, firstByteMs: 40000 }, { label: "old", finishedAt: 90 }, { label: "cr", finishedAt: 100, isCloud: true }] })); return Object.fromEntries([...a.entries()].sort()); })()',
     '{"a":"active","c":"cloud_active","cr":"cloud_recent","d":"client_disconnected","f":"failed","p":"preempting","q":"queued","r":"recent","s":"slow"}',
     "состояния: очередь, локальный/облачный активный, вытеснение, статус 5xx — failed, «client disconnected» — свой цвет, завершённые в окне 3 с, медленный первый байт; старое завершение не считается"),
    ("activity_for_sample_gpu_routes_and_filter", '',
     '(() => { const corr = { gpu: { activeRoutes: ["g"], cloudActiveRoutes: ["gc"] }, llamaServer: { activeRoutes: ["l"] }, activeRequests: [{ label: "srv", upstream: "10.0.0.5:22011" }, { label: "other", upstream: "10.0.0.9:1" }, { label: "cl", isCloud: true }, { label: "queued", phase: "queued" }] }; const all = m.topologyRouteActivityForSample(S(1, corr)); const box = m.topologyRouteActivityForSample(S(1, corr), m.nodeActivityFilter("box-a")); const ctl = m.topologyRouteActivityForSample(S(1, corr), m.nodeActivityFilter("box-c")); return [[...all.keys()].sort(), [...box.keys()].sort(), [...ctl.keys()].sort()]; })()',
     '[["cl","g","gc","l","other","queued","srv"],["queued","srv"],["queued"]]',
     "фильтр узла: только обслуженное его ячейками и очередь; negative: корреляции монитора (все локальные маршруты с запросом в полёте, чья бы машина их ни обслуживала) — только общей картине, не узлу, и машине контроллера тоже: узел контроллера брал их себе и подсвечивал маршруты, которые обслуживала другая машина; облако никому из узлов"),
    ("activity_controller_machine_over_loopback", '',
     '(() => { const corr = { activeRequests: [{ label: "own", upstream: "127.0.0.1:22001" }, { label: "far", upstream: "10.0.0.5:22011" }] }; return [[...m.topologyRouteActivityForSample(S(1, corr), m.nodeActivityFilter("box-c")).keys()].sort(), [...m.topologyRouteActivityForSample(S(1, corr), m.nodeActivityFilter("box-a")).keys()].sort()]; })()',
     '[["own"],["far"]]',
     "запрос, который прокси отдал ячейке машины контроллера по 127.0.0.1, — на её узле, а не на чужом; запрос другой машины — на ней"),
    ("activity_for_bucket_takes_max", '', 'm.topologyRouteActivityForBucket([S(1, { activeRequests: [{ label: "r", phase: "queued" }] }), S(2, { activeRequests: [{ label: "r", status: "500" }] }), S(3, { activeRequests: [{ label: "r" }] })], "r")',
     '"failed"', "бакет: самое тяжёлое состояние маршрута из всех сэмплов"),
    ("activity_for_bucket_missing_route", '', 'm.topologyRouteActivityForBucket([S(1, { activeRequests: [{ label: "r" }] })], "zzz")', '""', "negative: маршрута нет в бакете — пустая строка"),
    ("activity_color_table", '', '["failed","client_disconnected","active","cloud_active","recent","queued","nope"].map((s) => m.topologyRouteActivityColor("r", s))',
     '["rgba(255, 120, 120, 0.90)","rgba(250, 204,  21, 0.82)","rgba( 37,  99, 235, 0.92)","rgba(186, 230, 253, 0.92)","rgba( 52, 211, 153, 0.75)","rgba( 96, 165, 250, 0.60)","rgba(150, 162, 168, 0.48)"]',
     "цвета состояний; неизвестное — серый"),
    ("state_labels_and_legend", '', '(() => { const it = (await_ => 0); const h = m.buildRouteActivityLegendHtml(); return [m.ROUTE_ACTIVITY_STATE_LABELS.active, (h.match(/ral-item/g) || []).length, h.includes("error / timeout"), Object.keys(m.CHART_EXPAND_CONFIGS)]; })()',
     '["ratActive",10,true,["gpu","tokens","vram","power"]]', "подписи состояний — ключи i18n; легенда из десяти; четыре расширяемых графика"),
    # ── incidents ──
    ("incidents_persisted_filtered_and_capped", 'st.ui.latestSystemMonitor = { incidents: [{ kind: "fallback_active", time: 1700000090 }, { kind: "failed", time: 1700000090, title: "hotel failed" }, { kind: "slow", time: 1700000000 - 90000 }, ...Array.from({ length: 9 }, (_, i) => ({ kind: "failed", time: 1700000080 - i, error: "boom" }))] };',
     '(() => { const it = m.topologyIncidentItems([]); return [it.length, it[0].incident.title, it[0].incident.cause, it.some((x) => x.kind === "fallback_active"), it.some((x) => x.kind === "slow")]; })()',
     '[8,"hotel failed","proxy/upstream error",false,false]', "сохранённые инциденты: fallback и старше 24 ч отброшены, не больше восьми, причина по виду подставляется"),
    ("incidents_from_samples_dedup_sort", '',
     '(() => { const bad = { id: "x1", label: "hotel", status: "502", finishedAt: 50 }; const it = m.topologyIncidentItems([S(1, { activeRequests: [bad], recentRequests: [bad, { id: "x2", label: "scout", error: "timed out", finishedAt: 70 }, { id: "ok", label: "fine", status: "200", finishedAt: 80 }] })]); return [it.map((x) => x.id), it[0].incident.kind, it[1].incident.kind]; })()',
     '[["x2","x1"],"upstream_timeout","failed"]', "из сэмплов: дедуп одного запроса, успешный не инцидент, порядок — свежие первыми, вид по тексту ошибки"),
    ("incidents_render_rows", 'st.ui.latestSystemMonitor = { incidents: [{ kind: "failed", time: 1700000090, title: "hotel failed", summary: "status 502", client: "10.0.0.7", status: 502, port: 23001 }] };',
     '(() => { m.renderTopologyIncidents([]); const f = globalThis.__fields; return [f.topologyIncidentsMeta.textContent, f.topologyIncidents.innerHTML.includes("topology-incident-row failed"), f.topologyIncidents.innerHTML.includes("10.0.0.7 · status 502 · :23001"), f.topologyIncidents.innerHTML.includes("likely: proxy/upstream error")]; })()',
     '["1 recent",true,true,true]', "панель: счётчик в мете, класс failed, детали через «·», причина по виду в строке likely"),
    # 2026-09-28: the row named only the way IN (:23001); the cell that
    # refused (:22011) and what was asked (/props) stayed out of sight.
    ("incidents_render_exit_and_question", 'st.ui.latestSystemMonitor = { incidents: [{ kind: "failed", time: 1700000090, title: "hotel failed", summary: "[Errno 111] Connection refused", client: "10.0.0.7", method: "GET", path: "/props?key=s3cret", status: 502, port: 23001, exit: "10.0.0.5:22011", correlation: "proxy-only" }] };',
     '(() => { m.renderTopologyIncidents([]); const h = globalThis.__fields.topologyIncidents.innerHTML; return [h.includes("10.0.0.7 · GET /props · status 502 · :23001 → 10.0.0.5:22011 · proxy-only"), h.includes("s3cret")]; })()',
     '[true,false]', "positive: строка называет вопрос и выход, куда он ушёл; negative: строка запроса клиента (может нести ключ) не показывается"),
    ("incidents_render_cloud_exit_without_port", 'st.ui.latestSystemMonitor = { incidents: [{ kind: "failed", time: 1700000090, title: "hotel failed", summary: "status 429", status: 429, method: "POST", path: "/v1/chat/completions", exit: "☁ gpt-6-sol" }] };',
     '(() => { m.renderTopologyIncidents([]); const h = globalThis.__fields.topologyIncidents.innerHTML; return [h.includes("POST /v1/chat/completions · status 429 · → ☁ gpt-6-sol"), h.includes(" :")]; })()',
     '[true,false]', "облачный выход называется блоком модели; без порта входа — только стрелка к выходу"),
    ("incidents_render_old_record_no_exit", 'st.ui.latestSystemMonitor = { incidents: [{ kind: "failed", time: 1700000090, title: "hotel failed", summary: "status 502", client: "10.0.0.7", status: 502, port: 23001, method: "GET" }] };',
     '(() => { m.renderTopologyIncidents([]); const h = globalThis.__fields.topologyIncidents.innerHTML; return [h.includes("10.0.0.7 · status 502 · :23001"), h.includes("→"), h.includes("GET")]; })()',
     '[true,false,false]', "negative: запись без выхода и без пути (старая) — ни стрелки, ни «GET» без пути: не знаем — не пишем"),
    ("incidents_count_on_the_board_button",
     'st.ui.latestSystemMonitor = { incidents: [{ kind: "failed", time: 1700000090, title: "hotel failed" }, { kind: "slow", time: 1700000080, title: "slow" }] };',
     '(() => { const keep = document.querySelectorAll; const cnt = { textContent: "" }; const btn = { on: null, classList: { toggle(c, v) { btn.on = [c, v]; } } }; const old = { textContent: "" }; document.querySelectorAll = (sel) => ({ "[data-board-incidents-count]": [cnt], "[data-board-incidents]": [btn], "[data-ctrl-incidents-count]": [old] })[sel] || []; try { m.renderTopologyIncidents([]); } finally { document.querySelectorAll = keep; } return [cnt.textContent, btn.on, old.textContent]; })()',
     '["2",["has-incidents",true],""]',
     "счётчик и янтарь — у кнопки доски (data-board-incidents в строке Model servers); negative: старый атрибут узла контроллера больше никто не пишет"),
    ("incidents_render_empty", '', '(() => { m.renderTopologyIncidents([]); const f = globalThis.__fields; return [f.topologyIncidentsMeta.textContent, f.topologyIncidents.innerHTML.includes("No slow or failed proxy incidents")]; })()',
     '["clear",true]', "negative: без инцидентов — «clear» и подсказка"),
    ("incidents_render_no_panel", 'delete globalThis.__fields.topologyIncidents;', '(() => { m.renderTopologyIncidents([]); return globalThis.__fields.topologyIncidentsMeta.textContent; })()', '""', "negative: панели нет — ничего не трогается, без исключения"),
    # ── node telemetry ──
    ("node_telemetry_nothing", '', 'm.nodeTelemetryRowsHtml({ id: "box-b" })', '""', "negative: ни GPU, ни сервера, ни маршрутов — пусто"),
    ("node_telemetry_blocks", '', '(h => [(h.match(/class="gpu-metric"/g) || []).length, h.includes(\'data-open-chart="node:box-a:tokens"\'), h.includes(\'data-node-route-canvas="box-a"\'), h.includes("GPU history")])(m.nodeTelemetryRowsHtml({ id: "box-a", gpus: [{}], servers: [{ port: 22011 }] }))',
     '[4,true,true,true]', "GPU + сервер + маршруты: четыре метрики и блок активности маршрутов"),
    ("node_telemetry_row_says_its_descriptor_on_hover", '',
     '(h => [...h.matchAll(/<div class="gpu-metric" title="([^"]*)">/g)].map((x) => x[1]))(m.nodeTelemetryRowsHtml({ id: "box-a", gpus: [{}], servers: [{ port: 22011 }] }))',
     '["GPU history · Util","Token speed · prompt / gen","VRAM · used / total","Power · GPU power draw"]',
     "каждая строка графика говорит при наведении, что она меряет: на главной доске строка — имя, значение и мини-график, "
     "а подпись («Util», «used / total») ушла в подсказку (владелец, 2026-10-12: компактно и красиво, всё на месте)"),
    ("node_telemetry_routes_only", '', '(h => [(h.match(/class="gpu-metric"/g) || []).length, h.includes("data-open-route-activity")])(m.nodeTelemetryRowsHtml({ id: "box-a" }))', '[0,true]', "узел без GPU, но с маршрутами через граф — только блок маршрутов"),
    ("node_pseudo_samples", '', '[m._nodeGpuSamples({ gpus: [{ memoryTotalMiB: 1000, history: [[0, 250, 50, 120]] }] }), m._nodeTokenSamples({ servers: [{ tpsHistory: [] }, { tpsHistory: [[0, 30, 70]] }] }), m._nodeGpuSamples({})]',
     '[[{"gpu":{"utilPct":50,"memoryUsedMiB":250,"memoryTotalMiB":1000,"memoryPct":25,"powerW":120}}],[{"time":0,"tokens":{"promptTokensPerSecond":30,"predictedTokensPerSecond":70}}],[]]',
     "псевдосэмплы узла в форме сэмплов монитора; токены сохраняют время измерения"),
    ("node_tokens_cpu_first_bonsai_later", '',
     '(() => { const servers = [{port:22001,phase:"running",promptTps:0,genTps:0,tpsHistory:[[1,0,0],[2,0,0]]},{port:22013,phase:"running",promptTps:467.95,genTps:137.75,tpsHistory:[[1,467.95,137.75],[2,467.95,137.75]]}]; return [new m.NodeTokenTelemetry({servers}).current(),m._nodeTokenSamples({servers}),new m.NodeTokenTelemetry({servers:[...servers].reverse()}).current()]; })()',
     '[{"promptTps":467.95,"genTps":137.75},[{"time":1,"tokens":{"promptTokensPerSecond":467.95,"predictedTokensPerSecond":137.75}},{"time":2,"tokens":{"promptTokensPerSecond":467.95,"predictedTokensPerSecond":137.75}}],{"promptTps":467.95,"genTps":137.75}]',
     "регрессия машины контроллера: первая ячейка CPU-эмбеддингов с нулями не заслоняет Bonsai :22013; подпись и история считают весь узел, независимо от порядка портов"),
    ("node_tokens_running_measured_sum", '',
     'new m.NodeTokenTelemetry({servers:[{phase:"running",promptTps:10,genTps:20},{status:{phase:"running"},promptTps:30,genTps:40},{phase:"stopped",promptTps:1000,genTps:2000},{phase:"starting",promptTps:1000,genTps:2000},{phase:"running",promptTps:null,genTps:null}]}).current()',
     '{"promptTps":40,"genTps":60}', "известные скорости работающих ячеек суммируются; остановленные и стартующие не прибавляют старую скорость"),
    ("node_tokens_missing_is_unknown", '',
     '[new m.NodeTokenTelemetry({servers:[{phase:"running",promptTps:null,genTps:NaN},{phase:"stopped",genTps:99}]}).current(),new m.NodeTokenTelemetry({}).current(),new m.NodeTokenTelemetry({servers:[{phase:"running",promptTps:0,genTps:0}]}).current(),m.NodeTokenTelemetry.label(null,null)]',
     '[{"promptTps":null,"genTps":null},{"promptTps":null,"genTps":null},{"promptTps":0,"genTps":0},"prompt — / gen — t/s"]',
     "нет замеров — прочерки; измеренный ноль остаётся нулём"),
    ("node_token_histories_align_by_time", '',
     'm._nodeTokenSamples({servers:[{phase:"stopped",tpsHistory:[[2,20,2],[1,10,1],[3,null,null]]},{tpsHistory:[[2,30,3],[4,40,4],[4,50,5],[3,null,null]]}]})',
     '[{"time":1,"tokens":{"promptTokensPerSecond":10,"predictedTokensPerSecond":1}},{"time":2,"tokens":{"promptTokensPerSecond":50,"predictedTokensPerSecond":5}},{"time":3,"tokens":{"promptTokensPerSecond":null,"predictedTokensPerSecond":null}},{"time":4,"tokens":{"promptTokensPerSecond":50,"predictedTokensPerSecond":5}}]',
     "истории объединены по времени: старые ответы остановленных сохраняются, дубль одной ячейки заменяет себя, пропуск не заполняется чужой старой скоростью"),
    ("node_token_panel_renders_bonsai", '',
     '(() => { const old=document.querySelector; const label=el(); const canvas=tokenCanvas(); globalThis.__stubReturns["polling.formatTps"]=(v)=>String(v); st.setTopology({nodes:[{id:"sierra-pc",servers:[{port:22001,phase:"running",promptTps:0,genTps:0,tpsHistory:[[1,0,0],[2,0,0]]},{port:22013,phase:"running",promptTps:467.95,genTps:137.75,requestsProcessing:1,tpsHistory:[[1,467.95,137.75],[2,467.95,137.75]]}]}]}); document.querySelector=(s)=>s.includes("data-node-metric-val")?label:s.includes("data-node-canvas")?canvas:null; try {m.drawNodeTelemetry();return [label.textContent,canvas._tokenSamples.map((s)=>s.tokens.predictedTokensPerSecond),canvas.moves.some(([color,x,y])=>color==="rgba(105, 208, 144, 0.95)"&&y<80)];}finally{document.querySelector=old;} })()',
     '["prompt 467.95 / gen 137.75 t/s",[137.75,137.75],true]',
     "настоящий рендер панели: CPU первым, Bonsai позже — подпись ненулевая, график получает Bonsai, зелёная линия выше нуля"),
    ("token_chart_preserves_gap", '',
     '(() => {const canvas=tokenCanvas();m.drawTopologyTokenSpeedHistory([0,null,10].map((v,i)=>({time:i,tokens:{promptTokensPerSecond:v,predictedTokensPerSecond:v}})),canvas);return canvas.moves.filter(([color])=>color==="rgba(105, 208, 144, 0.95)").length;})()',
     '2', "график токенов не рисует третью точку на нуле вместо отсутствующего измерения"),
    ("node_samples_from_its_scout",
     'st.ui.latestSystemMonitor = { hosts: { "box-a": [{ t: 1001, gpus: [{ index: 0, memUsedMiB: 100, memTotalMiB: 1000, utilPct: 10, powerW: 50 }, { index: 1, memUsedMiB: 900, memTotalMiB: 2000, utilPct: 99, powerW: 300 }] }, { t: 1002, gpus: [{ index: 1, memUsedMiB: 1000, utilPct: 90, powerW: 280 }] }] } };',
     '[m._nodeGpuSamples({ id: "box-a", gpus: [{ index: 1, memoryTotalMiB: 2000, history: [[0, 1, 2, 3]] }] }), m._nodeGpuSamples({ id: "box-b", gpus: [{ memoryTotalMiB: 1000, history: [[0, 250, 50, 120]] }] }).length]',
     '[[{"time":1001,"gpu":{"utilPct":99,"memoryUsedMiB":900,"memoryTotalMiB":2000,"memoryPct":45,"powerW":300}},{"time":1002,"gpu":{"utilPct":90,"memoryUsedMiB":1000,"memoryTotalMiB":2000,"memoryPct":50,"powerW":280}}],1]',
     "машину, чей скаут снимает посекундно (2.8), рисуют его строки — секунда в секунду, та же карта, что на карточке; размер карты — из строки, иначе из отчёта; negative: у машины без строк — прежняя история отчётов"),
    ("node_samples_missing_card_in_a_row",
     'st.ui.latestSystemMonitor = { hosts: { "box-a": [{ t: 5, gpus: [] }] } };',
     'm._nodeGpuSamples({ id: "box-a", gpus: [{ index: 0, memoryTotalMiB: 1000 }] })',
     '[{"time":5,"gpu":{"memoryTotalMiB":1000,"memoryPct":0}}]',
     "boundary: в строке карты нет (nvidia-smi не ответил) — значения не выдумываются (нет, а не 0); как рисовать пропуск, "
     "решают графики — так же, как для замеров самого контроллера"),
    # ── a machine of two cards: one pool of memory, one power draw, the busiest card's utilisation ──
    ("node_gpu_two_cards_are_one_machine", '',
     '[new m.NodeGpuTelemetry({ gpus: [{ index: 0, memoryTotalMiB: 24576, memoryUsedMiB: 0, utilizationGpuPct: 3, powerDrawW: 18 }, { index: 1, memoryTotalMiB: 32607, memoryUsedMiB: 4907, utilizationGpuPct: 7, powerDrawW: 24 }] }).current(),'
     ' new m.NodeGpuTelemetry({ gpus: [{ index: 0, memoryTotalMiB: 32607, memoryUsedMiB: 4907, utilizationGpuPct: 7, powerDrawW: 24 }] }).current()]',
     '[{"utilPct":7,"usedMiB":4907,"totalMiB":57183,"powerW":42},{"utilPct":7,"usedMiB":4907,"totalMiB":32607,"powerW":24}]',
     "defect-history (2026-10-17): карточка машины с 3090 и 5090 показывала «0.0 / 24.0 GB» и 18 Вт — цифры нулевой карты, а 4,8 ГБ держала другая. "
     "Теперь память и мощность складываются, загрузка — у самой занятой карты (3 % и 7 % — это 7 %, а не 10 %); negative: машина с одной картой — её цифры, как были"),
    ("node_gpu_unknown_is_not_zero", '',
     '[new m.NodeGpuTelemetry({ gpus: [{ index: 0, memoryTotalMiB: 1000 }, { index: 1, memoryTotalMiB: 2000 }] }).current(),'
     ' new m.NodeGpuTelemetry({ gpus: [{ index: 0, memoryTotalMiB: 1000, memoryUsedMiB: 100, utilizationGpuPct: 5 }, { index: 1, memoryTotalMiB: 2000 }] }).current(),'
     ' new m.NodeGpuTelemetry({}).current()]',
     '[{"utilPct":null,"usedMiB":null,"totalMiB":3000,"powerW":null},{"utilPct":5,"usedMiB":100,"totalMiB":3000,"powerW":null},{"utilPct":null,"usedMiB":null,"totalMiB":0,"powerW":null}]',
     "negative: ни одна карта цифры не назвала — это null («—» на карточке), а не ноль; назвала одна — суммируется известное; машина без карт — нули размера и null"),
    ("node_gpu_samples_two_cards_from_scout_rows",
     'st.ui.latestSystemMonitor = { hosts: { "box-a": [{ t: 1001, gpus: [{ index: 0, memUsedMiB: 100, memTotalMiB: 1000, utilPct: 10, powerW: 50 }, { index: 1, memUsedMiB: 900, memTotalMiB: 3000, utilPct: 99, powerW: 300 }] },'
     ' { t: 1002, gpus: [{ index: 1, memUsedMiB: 1000, utilPct: 90, powerW: 280 }] }, { t: 1003, gpus: [] }] } };',
     'm._nodeGpuSamples({ id: "box-a", gpus: [{ index: 0, memoryTotalMiB: 1000 }, { index: 1, memoryTotalMiB: 3000 }] })',
     '[{"time":1001,"gpu":{"utilPct":99,"memoryUsedMiB":1000,"memoryTotalMiB":4000,"memoryPct":25,"powerW":350}},'
     '{"time":1002,"gpu":{"utilPct":90,"memoryUsedMiB":1000,"memoryTotalMiB":4000,"memoryPct":25,"powerW":280}},'
     '{"time":1003,"gpu":{"memoryTotalMiB":4000,"memoryPct":0}}]',
     "строки скаута двух карт: секунда в секунду, память и мощность складываются, загрузка — максимум, объём — обе карты; boundary: в секунде одной карты нет — "
     "считается то, что есть, объём прежний; negative: ни одной карты в строке — ничего не выдумано (нет, а не 0)"),
    ("node_gpu_samples_two_cards_from_reports", '',
     'm._nodeGpuSamples({ gpus: [{ index: 0, memoryTotalMiB: 1000, history: [[1, 100, 10, 50], [2, 200, 20, 60]] }, { index: 1, memoryTotalMiB: 3000, history: [[1, 900, 99, 300], [2, 800, 5, 250], [3, 700, 1, 200]] }] })',
     '[{"gpu":{"utilPct":99,"memoryUsedMiB":1000,"memoryTotalMiB":4000,"memoryPct":25,"powerW":350}},'
     '{"gpu":{"utilPct":20,"memoryUsedMiB":1000,"memoryTotalMiB":4000,"memoryPct":25,"powerW":310}},'
     '{"gpu":{"utilPct":1,"memoryUsedMiB":700,"memoryTotalMiB":4000,"memoryPct":17.5,"powerW":200}}]',
     "история отчётов старого скаута: карты наложены друг на друга по времени строки; у позднего времени только вторая карта — считается она; "
     "negative: история одной карты и пустая — как были (см. node_pseudo_samples)"),
    ("node_gpu_breakdown_names_each_card", '',
     '(() => { const two = new m.NodeGpuTelemetry({ gpus: [{ index: 0, memoryTotalMiB: 24576, memoryUsedMiB: 0, utilizationGpuPct: 0, powerDrawW: 18.04 }, { index: 1, memoryTotalMiB: 32607, memoryUsedMiB: 4907, powerDrawW: 24.3 }] });'
     ' return [two.breakdown("gpu"), two.breakdown("vram"), two.breakdown("power"), two.breakdown("tokens"), new m.NodeGpuTelemetry({ gpus: [{ index: 0 }] }).breakdown("vram"),'
     ' new m.NodeGpuTelemetry({ gpus: [{ index: 1, memoryTotalMiB: 1000, memoryUsedMiB: 500 }, { index: 0, memoryTotalMiB: 2000, memoryUsedMiB: 100 }] }).breakdown("vram")]; })()',
     '["GPU0 0% · GPU1 —","GPU0 0.0 / 24.0 GB · GPU1 4.8 / 31.8 GB","GPU0 18.0 W · GPU1 24.3 W","","","GPU1 0.5 / 1.0 GB · GPU0 0.1 / 2.0 GB"]',
     "подсказка к цифре: свои цифры каждой карты (нет замера — «—»); negative: у машины с одной картой подсказки нет — различать нечего; неизвестная метрика — пусто; карта названа своим номером, а не местом в списке (карты 1 и 0 — «GPU1 … · GPU0 …»)"),
    ("node_gpu_panel_renders_both_cards", '',
     '(() => { const old = document.querySelector; const labels = {}; document.querySelector = (q) => { const k = (q.match(/data-node-metric-val="([^"]*)"/) || [])[1]; return k ? (labels[k] ||= { textContent: "", title: "" }) : null; };'
     ' try { st.setTopology({ nodes: [{ id: "a", gpus: [{ index: 0, memoryTotalMiB: 24576, memoryUsedMiB: 0, utilizationGpuPct: 0, powerDrawW: 18 }, { index: 1, memoryTotalMiB: 32607, memoryUsedMiB: 4907, utilizationGpuPct: 7, powerDrawW: 24 }] },'
     ' { id: "b", gpus: [{ index: 0, memoryTotalMiB: 32607, memoryUsedMiB: 4907, utilizationGpuPct: 7, powerDrawW: 24 }] }, { id: "c", gpus: [{ index: 0, memoryTotalMiB: 8192 }] }] });'
     ' m.drawNodeTelemetry(); const read = (id) => ["gpu", "vram", "power"].map((k) => [labels[id + ":" + k].textContent, labels[id + ":" + k].title]); return { a: read("a"), b: read("b"), c: read("c") }; } finally { document.querySelector = old; } })()',
     '{"a":[["7%","GPU0 0% · GPU1 7%"],["4.8 / 55.8 GB","GPU0 0.0 / 24.0 GB · GPU1 4.8 / 31.8 GB"],["42.0 W","GPU0 18.0 W · GPU1 24.0 W"]],'
     '"b":[["7%",""],["4.8 / 31.8 GB",""],["24.0 W",""]],"c":[["—",""],["— / 8.0 GB",""],["—",""]]}',
     "настоящий рендер панели: у машины с двумя картами 4.8 / 55.8 GB, 42 Вт и 7% (карты по отдельности — в подсказке); negative: у машины с одной картой цифры её и без подсказки; "
     "у карты без замеров — «—», а не «0%», «0.0 / 8.0 GB» и «0.0 W»"),
    # 2026-10-17, the owner: "the combined chart (like you did now) and a chart for each of the cards".
    ("node_telemetry_a_line_per_card", '',
     '(() => { const two = { id: "box-a", gpus: [{ index: 0, name: "NVIDIA GeForce RTX 3090" }, { index: 1, name: "NVIDIA GeForce RTX 5090" }], servers: [{ port: 22011 }] };'
     ' const rows = (h) => (h.match(/class="gpu-metric-card"/g) || []).length; const two_ = m.nodeTelemetryRowsHtml(two);'
     ' const block = (key) => (two_.match(new RegExp(`data-open-chart="node:box-a:${key}"[\\\\s\\\\S]*?(?=<div class="gpu-metric"|$)`)) || [""])[0];'
     ' return [rows(two_), [...two_.matchAll(/data-t="node-gpu-card" data-t-id="([^"]*)" title="([^"]*)"/g)].map((x) => [x[1], x[2]]),'
     ' [...two_.matchAll(/data-t="node-gpu-cards" data-t-id="([^"]*)"/g)].map((x) => x[1]), rows(block("tokens")), rows(block("gpu")),'
     ' rows(m.nodeTelemetryRowsHtml({ id: "box-a", gpus: [{ index: 0 }], servers: [{ port: 22011 }] })), rows(m.nodeTelemetryRowsHtml({ id: "box-a", servers: [{ port: 22011 }] })),'
     ' [...m.nodeTelemetryRowsHtml({ id: "box-a", gpus: [{ index: 2 }, { index: 0 }] }).matchAll(/data-t="node-gpu-card" data-t-id="box-a:gpu:(\\d+)" title="([^"]*)"/g)].map((x) => [x[1], x[2]]),'
     ' two_.includes(\'data-node-metric-val="box-a:power:1"\') && two_.includes(\'data-node-metric-spark="box-a:power:1"\')]; })()',
     '[6,[["box-a:gpu:0","GPU 0 · NVIDIA GeForce RTX 3090"],["box-a:gpu:1","GPU 1 · NVIDIA GeForce RTX 5090"],["box-a:vram:0","GPU 0 · NVIDIA GeForce RTX 3090"],'
     '["box-a:vram:1","GPU 1 · NVIDIA GeForce RTX 5090"],["box-a:power:0","GPU 0 · NVIDIA GeForce RTX 3090"],["box-a:power:1","GPU 1 · NVIDIA GeForce RTX 5090"]],'
     '["box-a:gpu","box-a:vram","box-a:power"],0,2,0,0,[["2","GPU 2"],["0","GPU 0"]],true]',
     "машина с двумя картами: под общей строкой загрузки, памяти и мощности — по строке на карту (6 строк), каждая со своим номером платы, именем в подсказке, значением и мини-графиком; "
     "negative: под скоростью токенов строк по картам нет (токены считает ячейка, не карта); у машины с одной картой и без карт их нет; карта называется своим номером, а не местом в списке (карты 2 и 0)"),
    ("node_gpu_card_samples", '',
     '(() => { const hist = new m.NodeGpuTelemetry({ gpus: [{ index: 0, memoryTotalMiB: 1000, history: [[1, 100, 10, 50], [2, 200, 20, 60]] }, { index: 1, memoryTotalMiB: 2000, history: [[1, 900, 90, 300]] }] }, []);'
     ' const rows = new m.NodeGpuTelemetry({ gpus: [{ index: 0, memoryTotalMiB: 1000 }, { index: 1, memoryTotalMiB: 2000 }] }, [{ t: 5, gpus: [{ index: 1, utilPct: 40, memUsedMiB: 500, memTotalMiB: 2048, powerW: 123 }, { index: 0, utilPct: 3, memUsedMiB: 10, powerW: 20 }] }, { t: 6, gpus: [{ index: 1 }] }]);'
     ' return [hist.cardSamples(0), hist.cardSamples(1), rows.cardSamples(1), rows.cardSamples(0), hist.cardSamples(7), rows.cardCurrent(5)]; })()',
     '[[{"gpu":{"utilPct":10,"memoryUsedMiB":100,"memoryTotalMiB":1000,"memoryPct":10,"powerW":50}},{"gpu":{"utilPct":20,"memoryUsedMiB":200,"memoryTotalMiB":1000,"memoryPct":20,"powerW":60}}],'
     '[{"gpu":{"utilPct":90,"memoryUsedMiB":900,"memoryTotalMiB":2000,"memoryPct":45,"powerW":300}}],'
     '[{"time":5,"gpu":{"utilPct":40,"memoryUsedMiB":500,"memoryTotalMiB":2048,"memoryPct":24.4140625,"powerW":123}},{"time":6,"gpu":{"memoryTotalMiB":2000,"memoryPct":0}}],'
     '[{"time":5,"gpu":{"utilPct":3,"memoryUsedMiB":10,"memoryTotalMiB":1000,"memoryPct":1,"powerW":20}},{"time":6,"gpu":{"memoryTotalMiB":1000,"memoryPct":0}}],[],'
     '{"utilPct":null,"usedMiB":null,"totalMiB":0,"powerW":null}]',
     "один график карты: из истории её отчётов (старый скаут) и из секундных строк монитора (по номеру карты, а не по месту в списке); "
     "negative: карта без замера в строке — «нет замера» (поле пусто), не 0; карты нет — пусто, а не падение"),
    ("node_gpu_panel_draws_each_card", '',
     '(() => { const old = document.querySelector; const seen = {}; document.querySelector = (q) => { const v = (q.match(/data-node-metric-val="([^"]*)"/) || [])[1]; const sp = (q.match(/data-node-metric-spark="([^"]*)"/) || [])[1];'
     ' if (v) return (seen["v:" + v] ||= { textContent: "", title: "" }); if (sp) return (seen["s:" + sp] ||= { innerHTML: "" }); return null; };'
     ' try { st.setTopology({ nodes: [{ id: "a", gpus: [{ index: 0, memoryTotalMiB: 24576, memoryUsedMiB: 0, utilizationGpuPct: 0, powerDrawW: 18, history: [[1, 0, 0, 18], [2, 0, 1, 19]] },'
     ' { index: 1, memoryTotalMiB: 32607, memoryUsedMiB: 4907, utilizationGpuPct: 7, powerDrawW: 24, history: [[1, 4900, 5, 23], [2, 4907, 9, 24]] }] },'
     ' { id: "b", gpus: [{ index: 0, memoryTotalMiB: 32607, memoryUsedMiB: 4907, utilizationGpuPct: 7, powerDrawW: 24 }] }] });'
     ' m.drawNodeTelemetry(); const read = (id, key) => [(seen["v:" + id + ":" + key] || {}).textContent ?? null, (((seen["s:" + id + ":" + key] || {}).innerHTML || "").match(/points="([^"]*)"/) || [null, null])[1]];'
     ' return { a0: [read("a", "gpu:0"), read("a", "vram:0"), read("a", "power:0")], a1: [read("a", "gpu:1"), read("a", "vram:1"), read("a", "power:1")], b: [read("b", "gpu:0"), read("b", "vram:0")] }; } finally { document.querySelector = old; } })()',
     '{"a0":[["0%","0.0,14.0 72.0,13.9"],["0.0 / 24.0 GB","0.0,14.0 72.0,14.0"],["18.0 W","0.0,9.0 72.0,8.7"]],'
     '"a1":[["7%","0.0,13.3 72.0,12.7"],["4.8 / 31.8 GB","0.0,11.9 72.0,11.9"],["24.0 W","0.0,7.6 72.0,7.3"]],"b":[[null,null],[null,null]]}',
     "настоящий рендер: каждая из двух карт получает своё значение и свой график (загрузка, память, мощность), а не общие цифры машины; "
     "negative: у машины с одной картой строк по картам нет и ничего в них не пишется"),
    ("controller_widget_gone", '', '["controllerTokenGenSamples", "drawGpuMetricSparklines", "renderLlamaClientsInnerHtml"].filter((k) => k in m)', '[]',
     "negative: собственного виджета контроллера (серия генерации, спарклайны GPU/токенов/VRAM/мощности, клиенты llama) больше нет — его машина теперь узел со своей телеметрией (шаг 6.9)"),
]


# 1.3.589 — the machine's token speed panel says `last` when its figures are only held (the owner, 2026-10-18, after the cells' lines did):
# a running cell has a speed above 0 and no running cell answers a request now. The rule of who works is cell-speed.js's.
_RUN = 'phase:"running"'
PINS += [
    ("node_tokens_held_idle_holds", '',
     'new m.NodeTokenTelemetry({servers:[{%s,promptTps:2671.4,genTps:211.3,requestsProcessing:0}]}).held()' % _RUN,
     'true', "the cell answered once and holds its rates, no request runs: the machine's figures are held"),
    ("node_tokens_not_held_while_a_request_runs", '',
     'new m.NodeTokenTelemetry({servers:[{%s,promptTps:2671.4,genTps:211.3,requestsProcessing:1}]}).held()' % _RUN,
     'false', "a request runs: the figures are plain"),
    ("node_tokens_mixed_is_not_held", '',
     'new m.NodeTokenTelemetry({servers:[{%s,genTps:211.3,requestsProcessing:0},{%s,genTps:40,requestsProcessing:1}]}).held()' % (_RUN, _RUN),
     'false', "one cell holds and another answers: the machine works, the figures are plain"),
    ("node_tokens_a_working_cell_without_a_figure_blocks_held", '',
     'new m.NodeTokenTelemetry({servers:[{%s,genTps:211.3,requestsProcessing:0},{%s,genTps:null,requestsProcessing:2}]}).held()' % (_RUN, _RUN),
     'false', "a request that reads its prompt has no speed yet, and it is still work: nothing is called `last` while it runs"),
    ("node_tokens_not_told_is_held", '',
     '[new m.NodeTokenTelemetry({servers:[{%s,genTps:5}]}).held(), new m.NodeTokenTelemetry({servers:[{%s,genTps:5,requestsProcessing:"2"}]}).held()]' % (_RUN, _RUN),
     '[true,true]', "a scout that does not say how many requests run (or says it as text): not told claims no work — the figures are the last ones"),
    ("node_tokens_a_prompt_rate_alone_is_held", '',
     'new m.NodeTokenTelemetry({servers:[{%s,promptTps:300,genTps:0,requestsProcessing:0}]}).held()' % _RUN,
     'true', "the prompt rate is a figure too: a cell that only read prompts holds it while idle, and the panel says `last`"),
    ("node_tokens_no_figure_is_not_held", '',
     '[new m.NodeTokenTelemetry({servers:[{%s,promptTps:null,genTps:null,requestsProcessing:0}]}).held(), new m.NodeTokenTelemetry({servers:[{%s,promptTps:0,genTps:0,requestsProcessing:0}]}).held()]' % (_RUN, _RUN),
     '[false,false]', "negative: nothing measured, or a measured zero, is no figure to call `last`"),
    ("node_tokens_a_stopped_cell_is_not_counted", '',
     '[new m.NodeTokenTelemetry({servers:[{phase:"stopped",genTps:99,requestsProcessing:0}]}).held(), new m.NodeTokenTelemetry({servers:[{%s,genTps:20,requestsProcessing:0},{phase:"stopped",genTps:99,requestsProcessing:3}]}).held()]' % _RUN,
     '[false,true]', "a stopped cell has no figures and no work whatever it last said: alone it holds nothing; beside a running idle cell it does not make the machine work"),
    ("node_tokens_nothing_to_hold", '',
     '[new m.NodeTokenTelemetry({}).held(), new m.NodeTokenTelemetry({servers:[]}).held()]',
     '[false,false]', "negative: a machine with no cells holds nothing"),
    ("node_tokens_label_says_last_when_held",
     'globalThis.__stubReturns["polling.formatTps"] = (v) => String(v);',
     '[m.NodeTokenTelemetry.label(1,2), m.NodeTokenTelemetry.label(1,2,false), m.NodeTokenTelemetry.label(1,2,true), m.NodeTokenTelemetry.label(null,null,true)]',
     json.dumps(["prompt 1 / gen 2 t/s", "prompt 1 / gen 2 t/s", f"{LAST} prompt 1 / gen 2 t/s", f"{LAST} prompt — / gen — t/s"]),
     "`last` stands before the figures only when they are held; the word is the cells' (tpsLastLabel); as-is: handed no figures and told they are held, the label says so"),
    ("node_token_panel_says_last_and_its_hint",
     'const old = document.querySelector; const label = { textContent: "", title: "" }; const canvas = tokenCanvas(); globalThis.__stubReturns["polling.formatTps"] = (v) => String(v);'
     ' const draw = (servers) => { st.setTopology({ nodes: [{ id: "sierra-pc", servers }] }); document.querySelector = (s) => (s.includes("data-node-metric-val") ? label : s.includes("data-node-canvas") ? canvas : null);'
     ' try { m.drawNodeTelemetry(); return [label.textContent, label.title]; } finally { document.querySelector = old; } };',
     '[draw([{port:22001,phase:"running",promptTps:467.95,genTps:137.75,requestsProcessing:0,tpsHistory:[[1,467.95,137.75]]}]),'
     ' draw([{port:22001,phase:"running",promptTps:467.95,genTps:137.75,requestsProcessing:1,tpsHistory:[[1,467.95,137.75]]}]),'
     ' draw([{port:22001,phase:"running",promptTps:467.95,genTps:137.75,requestsProcessing:0,tpsHistory:[[1,467.95,137.75]]}])]',
     json.dumps([[f"{LAST} prompt 467.95 / gen 137.75 t/s", HELP], ["prompt 467.95 / gen 137.75 t/s", ""], [f"{LAST} prompt 467.95 / gen 137.75 t/s", HELP]]),
     "the real panel draw, one label over three ticks: idle holds (`last`, with the hint on hover), a request runs (plain, the hint gone), idle again — "
     "a hint left behind would explain live figures as held ones"),
]


# 1.3.590 — the machine's sum counts what the machine does now: while any cell works, only the cells that work; the held figures only when none does.
PINS += [
    ("node_tokens_sum_counts_only_the_cells_that_work", '',
     'new m.NodeTokenTelemetry({servers:[{%s,promptTps:2671.4,genTps:211.3,requestsProcessing:0},{%s,promptTps:300,genTps:40,requestsProcessing:1}]}).current()' % (_RUN, _RUN),
     '{"promptTps":300,"genTps":40}', "defect-history (the owner, 2026-10-18): one cell answers at 40 t/s and another holds its last 211.3 — the machine generates 40, not 251"),
    ("node_tokens_two_working_cells_add_up", '',
     'new m.NodeTokenTelemetry({servers:[{%s,promptTps:100,genTps:10,requestsProcessing:1},{%s,promptTps:200,genTps:20,requestsProcessing:2},{%s,promptTps:999,genTps:99,requestsProcessing:0}]}).current()' % (_RUN, _RUN, _RUN),
     '{"promptTps":300,"genTps":30}', "two cells answer and one holds: the two add up, the one that holds adds nothing"),
    ("node_tokens_sum_of_held_when_none_works", '',
     '(t => [t.current(), t.held()])(new m.NodeTokenTelemetry({servers:[{%s,promptTps:100,genTps:10,requestsProcessing:0},{%s,promptTps:200,genTps:20,requestsProcessing:0}]}))' % (_RUN, _RUN),
     '[{"promptTps":300,"genTps":30},true]', "none answers: the figures are the held ones of the running cells, summed as before, and they are called held"),
    ("node_tokens_a_request_without_a_figure_hides_the_held_ones",
     'globalThis.__stubReturns["polling.formatTps"] = (v) => String(v);',
     '(t => [t.current(), t.held(), m.NodeTokenTelemetry.label(t.current().promptTps, t.current().genTps, t.held())])(new m.NodeTokenTelemetry({servers:[{%s,promptTps:2671.4,genTps:211.3,requestsProcessing:0},{%s,promptTps:null,genTps:null,requestsProcessing:2}]}))' % (_RUN, _RUN),
     json.dumps([{"promptTps": None, "genTps": None}, False, "prompt — / gen — t/s"]),
     "a request that has no speed yet is the machine's work: dashes (not measured yet), not a held figure of another cell drawn as if it were live"),
    ("node_tokens_a_cell_that_says_no_count_is_not_live_beside_a_working_one", '',
     'new m.NodeTokenTelemetry({servers:[{%s,promptTps:50,genTps:211.3},{%s,promptTps:300,genTps:40,requestsProcessing:1}]}).current()' % (_RUN, _RUN),
     '{"promptTps":300,"genTps":40}', "negative: nothing tells whether a cell that says no count works — beside one that does, its figure is not counted as live"),
    ("node_tokens_a_stopped_cell_never_adds", '',
     'new m.NodeTokenTelemetry({servers:[{phase:"stopped",promptTps:900,genTps:99,requestsProcessing:3},{%s,promptTps:50,genTps:20,requestsProcessing:0}]}).current()' % _RUN,
     '{"promptTps":50,"genTps":20}', "negative: a stopped cell is no part of the machine's figures, whatever its last report said of requests"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 30:
        print(f"js charts FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js charts: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_charts.tmp.mjs"
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
        print(f"js charts FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("графики: активность маршрутов, инциденты, телеметрия узлов:")
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
    print(f"js charts OK: настоящий модуль в node, {len(PINS)} пинов графиков значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
