#!/usr/bin/env python3
"""Снимок static/js/charts.js — то, что графики СЧИТАЮТ, а не рисуют.

Модуль на 1154 строки — canvas-рендеры, и рисование в снимок не берётся. Берётся
всё, что даёт значение: классификация активности маршрута по сэмплу
(failed > client_disconnected > preempting > degraded > active > slow > recent >
queued — приоритет состояний, и никакое нижнее не затирает верхнее), фильтр по
узлу (запрос засчитывается узлу, который его ОБСЛУЖИЛ, облако не зажигает GPU),
подписи маршрутов узла (прямые и через граф роутера), список инцидентов
(сохранённые — с отсечкой 24 ч и без fallback; иначе — из сэмплов с дедупом),
рендер панели инцидентов через словарный DOM, бакеты по ширине холста,
спарклайн, скорости токенов с их запасными путями, форматы.

Модуль настоящий; `topology-activity` (классификация инцидентов) и
`topology-proxies` тоже; `polling.formatTps` — заглушка через __stubReturns.

Запуск: python3 scripts/test_js_charts.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

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
const NODES = () => [
  { id: "controller", role: "controller", ip: "10.0.0.1", servers: [{ port: 22001 }, { port: 22002, clientIp: "10.0.0.1" }] },
  { id: "box-a", role: "client", ip: "10.0.0.5", servers: [{ port: 22011 }] },
  { id: "box-b", role: "client", ip: "10.0.0.6", servers: [] },
];
const PROXIES = () => [
  { id: "p1", port: 23001, label: "hermes", upstreamHost: "127.0.0.1", upstreamPort: 22001 },
  { id: "p2", port: 23003, label: "scout", upstreamHost: "10.0.0.5", upstreamPort: 22011 },
  { id: "p3", port: 23005, label: "graphy", upstreamHost: "127.0.0.1", upstreamPort: 8080, routerId: "router:a" },
  { id: "p4", port: 23007, label: "cloudy", upstreamType: "cloud", providerId: "cb:terra", upstreamHost: "10.0.0.5", upstreamPort: 22011 },
  { id: "p5", port: 23009, label: "", upstreamHost: "10.0.0.5", upstreamPort: 22011 },
];
const ROUTERS = () => [{ id: "router:a", outputs: [{ id: "srv:22011", upstreamHost: "10.0.0.5", upstreamPort: 22011 }] }];
const TOPO = (extra = {}) => ({ proxies: PROXIES(), clients: [], routers: ROUTERS(), assignments: {}, nodes: NODES(), ...extra });
const S = (time, corr) => ({ time, correlatedActivity: corr });
const reset = () => { st.setState({ config: {} }); st.setTopology(TOPO()); st.ui.latestSystemMonitor = null;
  globalThis.__fields = { topologyIncidents: el(), topologyIncidentsMeta: el() };
  globalThis.__stubReturns = { "polling.formatTps": (v) => `${v} t/s` }; };
reset();
const out = {};
"""

PINS = [
    # ── форматы ──
    ("format_rate", '', '[m.formatRate(0), m.formatRate(999), m.formatRate(1536), m.formatRate(3 * 1024 ** 2), m.formatRate(2 * 1024 ** 3), m.formatRate(NaN), m.formatRate("x")]',
     '["0 B/s","999 B/s","1.5 KB/s","3.00 MB/s","2.00 GB/s","0 B/s","0 B/s"]', "байты в секунду с порогами; мусор — 0 B/s"),
    ("fmt_ms", '', '[m._fmtMs(0), m._fmtMs(999), m._fmtMs(1000), m._fmtMs(1550), m._fmtMs(undefined)]', '["0ms","999ms","1.0s","1.6s","0ms"]', "миллисекунды до секунды, потом секунды с десятой"),
    ("format_event_time", '', '[m.formatEventTime(""), m.formatEventTime(0), m.formatEventTime("2026-09-05T10:00"), typeof m.formatEventTime(1700000000)]', '["","","2026-09-05T10:00","string"]',
     "пусто — пусто; строка — как есть; число — локальное время (строка, локаль не пинится)"),
    ("system_samples_and_latest", '', '[m.systemSamples({ samples: [1, 2] }), m.systemSamples({ samples: "no" }), m.systemSamples(null), m.latestSample([{ a: 1 }, { a: 2 }]), m.latestSample([])]',
     '[[1,2],[],[],{"a":2},{}]', "сэмплы только массивом; последний — последний; пусто — {}"),
    ("tps_fallback_chain", '',
     '[m.topologyPromptTps({ llamaActivity: { lastTiming: { promptTps: 10 } }, tokens: { promptTokensPerSecond: 99 } }), m.topologyPromptTps({ correlatedActivity: { llamaServer: { lastTiming: { promptTps: 20 } } } }), m.topologyPromptTps({ tokens: { promptTokensPerSecond: 30 } }), m.topologyPromptTps({}), m.topologyEvalTps({ tokens: { predictedTokensPerSecond: 40 } }), m.topologyEvalTps(null)]',
     '[10,20,30,0,40,0]', "скорость: llamaActivity → correlatedActivity → tokens → 0"),
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
    # ── узлы ──
    ("endpoint_set_controller_adds_loopback", '', '[...m.nodeEndpointSet(NODES()[0])].sort()', '["10.0.0.1:22001","10.0.0.1:22002","127.0.0.1:22001","127.0.0.1:22002"]',
     "контроллер: каждый порт и по IP, и по 127.0.0.1"),
    ("endpoint_set_client_and_empty", '', '[[...m.nodeEndpointSet(NODES()[1])], [...m.nodeEndpointSet(NODES()[2])], [...m.nodeEndpointSet(null)]]', '[["10.0.0.5:22011"],[],[]]', "клиент: только свой IP; без серверов — пусто; null — пусто"),
    ("activity_filter", '', '[m.nodeActivityFilter("box-a").isController, [...m.nodeActivityFilter("box-a").endpoints], m.nodeActivityFilter("controller").isController, m.nodeActivityFilter("ghost")]',
     '[false,["10.0.0.5:22011"],true,null]', "фильтр узла: концы и флаг контроллера; неизвестный узел — null"),
    ("node_route_labels_direct_and_via_graph", '', '[m.nodeRouteLabels("box-a"), m.nodeRouteLabels("controller"), m.nodeRouteLabels("box-b"), m.nodeRouteLabels("ghost")]',
     '[["scout","graphy"],["hermes"],[],[]]', "подписи: прямой upstream и через выход роутера; облако и пустая подпись не считаются; узел без ячеек — пусто"),
    # ── активность маршрута по сэмплу ──
    ("activity_priority", '', '["failed","client_disconnected","preempting","degraded","active","cloud_active","slow","recent","cloud_recent","queued","",null].map(m.topologyRouteActivityPriority)',
     '[8,7,6,5,4,4,3,2,2,1,0,0]', "приоритет состояний сверху вниз; неизвестное — 0"),
    ("activity_set_keeps_higher", '', '(() => { const mp = new Map(); m.topologyRouteActivitySet(mp, "r", "queued"); m.topologyRouteActivitySet(mp, "r", "failed"); m.topologyRouteActivitySet(mp, "r", "active"); m.topologyRouteActivitySet(mp, "", "active"); return [mp.get("r"), mp.size]; })()',
     '["failed",1]', "нижнее состояние не затирает верхнее; пустой маршрут не пишется"),
    ("activity_for_sample_states", '',
     '(() => { const a = m.topologyRouteActivityForSample(S(100, { activeRequests: [{ label: "q", phase: "queued" }, { label: "a" }, { label: "c", isCloud: true }, { label: "p", phase: "preempting" }, { label: "f", status: "502" }, { label: "d", error: "client disconnected" }], recentRequests: [{ label: "r", finishedAt: 99 }, { label: "s", finishedAt: 100, firstByteMs: 40000 }, { label: "old", finishedAt: 90 }, { label: "cr", finishedAt: 100, isCloud: true }] })); return Object.fromEntries([...a.entries()].sort()); })()',
     '{"a":"active","c":"cloud_active","cr":"cloud_recent","d":"client_disconnected","f":"failed","p":"preempting","q":"queued","r":"recent","s":"slow"}',
     "состояния: очередь, локальный/облачный активный, вытеснение, статус 5xx — failed, «client disconnected» — свой цвет, завершённые в окне 3 с, медленный первый байт; старое завершение не считается"),
    ("activity_for_sample_gpu_routes_and_filter", '',
     '(() => { const corr = { gpu: { activeRoutes: ["g"], cloudActiveRoutes: ["gc"] }, llamaServer: { activeRoutes: ["l"] }, activeRequests: [{ label: "srv", upstream: "10.0.0.5:22011" }, { label: "other", upstream: "10.0.0.9:1" }, { label: "cl", isCloud: true }, { label: "queued", phase: "queued" }] }; const all = m.topologyRouteActivityForSample(S(1, corr)); const box = m.topologyRouteActivityForSample(S(1, corr), m.nodeActivityFilter("box-a")); const ctl = m.topologyRouteActivityForSample(S(1, corr), m.nodeActivityFilter("controller")); return [[...all.keys()].sort(), [...box.keys()].sort(), [...ctl.keys()].sort()]; })()',
     '[["cl","g","gc","l","other","queued","srv"],["queued","srv"],["g","l","queued"]]',
     "фильтр узла: клиенту — только обслуженное им и очередь; контроллеру — GPU/llama-корреляции без облачных, а чужой upstream — не его; облако никому из узлов"),
    ("activity_for_bucket_takes_max", '', 'm.topologyRouteActivityForBucket([S(1, { activeRequests: [{ label: "r", phase: "queued" }] }), S(2, { activeRequests: [{ label: "r", status: "500" }] }), S(3, { activeRequests: [{ label: "r" }] })], "r")',
     '"failed"', "бакет: самое тяжёлое состояние маршрута из всех сэмплов"),
    ("activity_for_bucket_missing_route", '', 'm.topologyRouteActivityForBucket([S(1, { activeRequests: [{ label: "r" }] })], "zzz")', '""', "negative: маршрута нет в бакете — пустая строка"),
    ("activity_color_table", '', '["failed","client_disconnected","active","cloud_active","recent","queued","nope"].map((s) => m.topologyRouteActivityColor("r", s))',
     '["rgba(255, 120, 120, 0.90)","rgba(250, 204,  21, 0.82)","rgba( 37,  99, 235, 0.92)","rgba(186, 230, 253, 0.92)","rgba( 52, 211, 153, 0.75)","rgba( 96, 165, 250, 0.60)","rgba(150, 162, 168, 0.48)"]',
     "цвета состояний; неизвестное — серый"),
    ("state_labels_and_legend", '', '(() => { const it = (await_ => 0); const h = m.buildRouteActivityLegendHtml(); return [m.ROUTE_ACTIVITY_STATE_LABELS.active, (h.match(/ral-item/g) || []).length, h.includes("error / timeout"), Object.keys(m.CHART_EXPAND_CONFIGS)]; })()',
     '["ratActive",10,true,["gpu","tokens","vram","power"]]', "подписи состояний — ключи i18n; легенда из десяти; четыре расширяемых графика"),
    # ── инциденты ──
    ("incidents_persisted_filtered_and_capped", 'st.ui.latestSystemMonitor = { incidents: [{ kind: "fallback_active", time: 1700000090 }, { kind: "failed", time: 1700000090, title: "hermes failed" }, { kind: "slow", time: 1700000000 - 90000 }, ...Array.from({ length: 9 }, (_, i) => ({ kind: "failed", time: 1700000080 - i, error: "boom" }))] };',
     '(() => { const it = m.topologyIncidentItems([]); return [it.length, it[0].incident.title, it[0].incident.cause, it.some((x) => x.kind === "fallback_active"), it.some((x) => x.kind === "slow")]; })()',
     '[8,"hermes failed","proxy/upstream error",false,false]', "сохранённые инциденты: fallback и старше 24 ч отброшены, не больше восьми, причина по виду подставляется"),
    ("incidents_from_samples_dedup_sort", '',
     '(() => { const bad = { id: "x1", label: "hermes", status: "502", finishedAt: 50 }; const it = m.topologyIncidentItems([S(1, { activeRequests: [bad], recentRequests: [bad, { id: "x2", label: "scout", error: "timed out", finishedAt: 70 }, { id: "ok", label: "fine", status: "200", finishedAt: 80 }] })]); return [it.map((x) => x.id), it[0].incident.kind, it[1].incident.kind]; })()',
     '[["x2","x1"],"upstream_timeout","failed"]', "из сэмплов: дедуп одного запроса, успешный не инцидент, порядок — свежие первыми, вид по тексту ошибки"),
    ("incidents_render_rows", 'st.ui.latestSystemMonitor = { incidents: [{ kind: "failed", time: 1700000090, title: "hermes failed", summary: "status 502", client: "10.0.0.7", status: 502, port: 23001 }] };',
     '(() => { m.renderTopologyIncidents([]); const f = globalThis.__fields; return [f.topologyIncidentsMeta.textContent, f.topologyIncidents.innerHTML.includes("topology-incident-row failed"), f.topologyIncidents.innerHTML.includes("10.0.0.7 · status 502 · :23001"), f.topologyIncidents.innerHTML.includes("likely: proxy/upstream error")]; })()',
     '["1 recent",true,true,true]', "панель: счётчик в мете, класс failed, детали через «·», причина по виду в строке likely"),
    ("incidents_render_empty", '', '(() => { m.renderTopologyIncidents([]); const f = globalThis.__fields; return [f.topologyIncidentsMeta.textContent, f.topologyIncidents.innerHTML.includes("No slow or failed proxy incidents")]; })()',
     '["clear",true]', "negative: без инцидентов — «clear» и подсказка"),
    ("incidents_render_no_panel", 'delete globalThis.__fields.topologyIncidents;', '(() => { m.renderTopologyIncidents([]); return globalThis.__fields.topologyIncidentsMeta.textContent; })()', '""', "negative: панели нет — ничего не трогается, без исключения"),
    # ── телеметрия узла ──
    ("node_telemetry_nothing", '', 'm.nodeTelemetryRowsHtml({ id: "box-b" })', '""', "negative: ни GPU, ни сервера, ни маршрутов — пусто"),
    ("node_telemetry_blocks", '', '(h => [(h.match(/class="gpu-metric"/g) || []).length, h.includes(\'data-open-chart="node:box-a:tokens"\'), h.includes(\'data-node-route-canvas="box-a"\'), h.includes("GPU history")])(m.nodeTelemetryRowsHtml({ id: "box-a", gpus: [{}], servers: [{ port: 22011 }] }))',
     '[4,true,true,true]', "GPU + сервер + маршруты: четыре метрики и блок активности маршрутов"),
    ("node_telemetry_routes_only", '', '(h => [(h.match(/class="gpu-metric"/g) || []).length, h.includes("data-open-route-activity")])(m.nodeTelemetryRowsHtml({ id: "box-a" }))', '[0,true]', "узел без GPU, но с маршрутами через граф — только блок маршрутов"),
    ("node_pseudo_samples", '', '[m._nodeGpuSamples({ gpus: [{ memoryTotalMiB: 1000, history: [[0, 250, 50, 120]] }] }), m._nodeTokenSamples({ servers: [{ tpsHistory: [] }, { tpsHistory: [[0, 30, 70]] }] }), m._nodeGpuSamples({})]',
     '[[{"gpu":{"utilPct":50,"memoryUsedMiB":250,"memoryTotalMiB":1000,"memoryPct":25,"powerW":120}}],[{"tokens":{"promptTokensPerSecond":30,"predictedTokensPerSecond":70}}],[]]',
     "псевдосэмплы узла в форме сэмплов монитора; сервер с историей выбирается первый непустой"),
    ("controller_token_samples", 'st.ui.latestSystemMonitor = { tokenGenSamples: [{ time: 1 }] };', '[m.controllerTokenGenSamples(), (st.ui.latestSystemMonitor = null, m.controllerTokenGenSamples())]', '[[{"time":1}],[]]', "серия генерации контроллера из монитора; без монитора — пусто"),
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

    # Пины не опираются друг на друга: тот же набор в обратном порядке обязан
    # дать те же значения.
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
