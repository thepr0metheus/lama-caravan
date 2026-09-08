#!/usr/bin/env python3
"""Snapshot of static/js/polling.js — polling for state and monitors.

What's pinned by value. Formats (tok/s with thresholds, compact context
tokens), the live-poll delay (5s while running, else 1.5s), the monitor
interval (1..30s from the input/localStorage). refreshLiveState — ONLY the
live fields are taken from /api/state (service, runtime, cpu/gpu, memory,
diagnostics, logs, git, time), the form's config is left untouched; an
"in-flight" guard; a failure shows a toast. saveConfig and action — what goes
out on the wire and which toast appears. refreshMonitor — the URL by
nvidia-smi's source (a remote host through client-monitor), html or text
with a timestamp, on failure the previous snapshot is kept with a mark.
Merging a monitor series: a full response replaces it, a partial one
(`partial`) appends and trims by the server's retention, incidents use their
own, longer one; after the first response, polling continues with `?since=`;
an "in-flight" guard and a request timeout (without it, one stuck request
used to kill the cycle until the page reloaded). renderGpuUsers — proxy rows
from correlated activity (active ones, else up to 8 recent), clients, slots,
"by clients", recent ones, speed/context/timing/cache rows, the empty state.
Retention — clamped to 60..3600 and a POST. A client's caption — input, POST,
refresh.

The DOM is the `globalThis.__fields` dict; timers are recorders; stateful
neighbors (`activeView`, `topologyPointerDrag`, `_nvidiaSmiSource`) go through
__stubValues.

Run: python3 scripts/test_js_polling.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("charts,dialogs,form,llama-edit,remote-cells,system-panels,topology-activity,topology-dnd,topology-render,"
         "canvas,cables,cloud,history,favorites,config-locator,onboarding,onboarding-tours,usage-stats,dialog-llamas,"
         "models-page,system-page,memory,command-preview,topology-nodes,topology-modals,routers,topology-proxies,model-meta")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: { MODEL_FILE: "keep.gguf" } });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
globalThis.__stubValues = { "topology-render.activeView": "topology", "topology-dnd.topologyPointerDrag": null, "remote-cells._nvidiaSmiSource": "box-a" };
globalThis.__timers = []; globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push("timeout:" + ms); return 1; }; globalThis.setInterval = (fn, ms) => { globalThis.__timers.push("interval:" + ms); return 2; }; globalThis.clearTimeout = () => {}; globalThis.clearInterval = () => {};
// Модульный _monitorSince переживает пины (как в браузере — страницу): ответ на
// /api/system-monitor?since=N ищется по базовому пути, если точного ключа нет; записанный путь остаётся полным.
const realFetch = globalThis.fetch;
globalThis.fetch = (p, o) => { const full = String(p); const base = full.replace(/\?since=\d+$/, ""); if (!(full in globalThis.__fetchReply) && (base in globalThis.__fetchReply)) globalThis.__fetchReply[full] = globalThis.__fetchReply[base]; return realFetch(p, o); };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/polling.js").href);
const mkEl = () => ({ textContent: "", innerHTML: "", value: "", listeners: {}, dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, querySelector(sel) { return sel === ".system-monitor-status" ? (this.status ||= mkEl()) : null; } });
const F = () => globalThis.__fields;
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body === null ? null : JSON.parse(c.body) }));
const rec = (name) => (...a) => { globalThis.__calls.push([name, a[0] ?? null]); };
const reset = () => { st.setState({ config: { MODEL_FILE: "keep.gguf" }, runtime: { status: { phase: "ready" } } }); st.ui.latestSystemMonitor = null; st.ui.topologyProxyFormOpen = false;
  globalThis.__fields = { toast: mkEl(), monitorNvidia: mkEl(), monitorIntervalNvidia: mkEl(), systemMonitor: mkEl(), systemMonitorRetention: mkEl(), topologyLlamaClientsCount: mkEl() };
  globalThis.__timers.length = 0; globalThis.__calls = []; localStorage.clear(); m.stopSystemMonitor(); m.stopTopologyMonitor();
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {};
  globalThis.__stubReturns = { "charts.formatEventTime": (v) => (v ? "T" + v : ""), "charts.renderLlamaClientsInnerHtml": () => "<i>clients</i>", "form.readConfigForm": () => ({ MODEL_FILE: "form.gguf", THREADS: "8" }),
    "dialogs.appPrompt": async () => null, "llama-edit.closeConfirmModal": rec("closeConfirmModal"), "topology-activity.proxyTelemetrySummary": () => "tps 12", "topology-activity.refreshTopologyActivityState": rec("refreshTopologyActivityState"),
    "topology-render.refreshTopology": async () => { globalThis.__calls.push(["refreshTopology", null]); }, "topology-render.renderAll": rec("renderAll"),
    "system-panels.renderService": rec("renderService"), "system-panels.renderRuntime": rec("renderRuntime"), "system-panels.renderCpu": rec("renderCpu"), "system-panels.renderGpu": rec("renderGpu"), "system-panels.renderKnownProblems": rec("renderKnownProblems"), "system-panels.renderProjectGitBranch": rec("renderProjectGitBranch") }; };
reset();
globalThis.document.querySelector = (sel) => (sel === ".topology-llama-clients-dynamic" ? (globalThis.__clientsDyn ||= mkEl()) : null);
const named = () => globalThis.__calls.map((c) => c[0]);
const MON = (over = {}) => ({ time: 1000, retentionSeconds: 600, incidentRetentionSeconds: 86400, newestSample: 1000, samples: [{ time: 990 }, { time: 1000 }], tokenGenSamples: [{ time: 1000 }], incidents: [{ time: 500 }, { time: 1640 }], latest: { llamaClients: { clients: [{ ip: "a" }, { ip: "b" }] } }, ...over });
const out = {};
"""

PINS = [
    ("metric_number_and_tps", '', '[m.metricNumber("12.5"), m.metricNumber("x"), m.metricNumber(Infinity), m.formatTps(123.456), m.formatTps(12.345), m.formatTps(1.5), m.formatTps(2), m.formatTps("junk")]', '[12.5,0,0,"123.5","12.35","1.5","2","0"]',
     "число из метрики (мусор и бесконечность — 0); tok/s: ≥100 одна десятичная, ≥10 две, ниже — до трёх без хвостовых нулей"),
    ("format_ctx_tokens", '', '[m.formatCtxTokens(32768), m.formatCtxTokens(12000), m.formatCtxTokens(1500), m.formatCtxTokens(999), m.formatCtxTokens(150000), m.formatCtxTokens(-1), m.formatCtxTokens("x")]', '["32.8k","12k","1.5k","999","150k","—","—"]',
     "компактные токены: k с одной десятичной до 100k, целые от 100k, меньше тысячи — как есть; отрицательное и мусор — прочерк"),
    ("live_refresh_delay", '', '(() => { const a = m.liveRefreshDelay(); st.state.runtime.status.phase = "running"; return [a, m.liveRefreshDelay()]; })()', '[1500,5000]', "задержка живого опроса: 1.5 с, при running — 5 с"),
    ("monitor_interval_clamps", '', '(() => { const inp = F().monitorIntervalNvidia; inp.value = "0"; const a = m.monitorIntervalMs("nvidia-smi"); inp.value = "99"; const b = m.monitorIntervalMs("nvidia-smi"); inp.value = "7"; const c = m.monitorIntervalMs("nvidia-smi"); return [a, b, c, m.monitorIntervalMs("other"), m.monitorStorageKey("nvidia-smi")]; })()',
     '[1000,30000,7000,1000,"llamacpp-monitor-interval-nvidia-smi"]', "интервал монитора: 1..30 с в миллисекундах; без инпута — 1 с"),
    ("monitor_interval_save_and_restore", '', '(() => { const inp = F().monitorIntervalNvidia; inp.value = "45"; m.saveMonitorInterval("nvidia-smi"); const a = [inp.value, localStorage.getItem("llamacpp-monitor-interval-nvidia-smi")]; inp.value = "1"; m.restoreMonitorInterval("nvidia-smi"); const b = inp.value; localStorage.setItem("llamacpp-monitor-interval-nvidia-smi", "0"); m.restoreMonitorInterval("nvidia-smi"); return [...a, b, inp.value]; })()',
     '["30","30","30","1"]', "сохранение нормализует и пишет в localStorage; восстановление зажимает снизу единицей"),
    ("refresh_live_state_merges_live_fields_only", 'globalThis.__fetchReply["/api/state"] = { config: { MODEL_FILE: "server.gguf" }, service: { MainPID: 7 }, runtime: { status: { phase: "running" } }, cpu: { ok: true }, gpu: { ok: true }, memory: { ok: true }, diagnostics: { checks: [] }, logs: "L", projectGit: { branch: "main" }, time: 42 };',
     'await (async () => { await m.refreshLiveState(); return [st.state.config.MODEL_FILE, st.state.service.MainPID, st.state.runtime.status.phase, st.state.time, st.state.logs, named(), m.liveRefreshInflight]; })()',
     '["keep.gguf",7,"running",42,"L",["renderProjectGitBranch","renderService","renderRuntime","renderCpu","renderGpu","renderKnownProblems","refreshTopology"],false]',
     "живое обновление: конфиг формы НЕ затирается, живые поля обновлены, карточки перерисованы, на доске — refreshTopology; сторож снят"),
    ("refresh_live_state_failure_toasts", 'globalThis.__fetchReply["/api/state"] = { __status: 500, error: "down" };', 'await (async () => { await m.refreshLiveState(); return [F().toast.textContent, m.liveRefreshInflight, named().length]; })()', '["down",false,0]', "negative: отказ — тост, сторож снят, ничего не перерисовано"),
    ("schedule_live_refresh", '', '(() => { m.scheduleLiveRefresh(); m.scheduleLiveRefresh(250); return [...globalThis.__timers]; })()', '["timeout:1500","timeout:250"]', "планирование: задержка по фазе или заданная"),
    ("load_state", 'globalThis.__fetchReply["/api/state"] = { config: { X: "1" }, appVersion: "9" };', 'await (async () => { await m.loadState(); return [st.state.appVersion, named(), [...globalThis.__timers]]; })()', '["9",["renderAll"],["timeout:1500"]]', "первая загрузка: состояние целиком, полная перерисовка, опрос запланирован"),
    ("save_config_posts_form", 'globalThis.__fetchReply["/api/config"] = { state: { config: { MODEL_FILE: "form.gguf" }, appVersion: "s" } };', 'await (async () => { await m.saveConfig(false); const a = [calls()[0].path, calls()[0].body, F().toast.textContent, st.state.appVersion]; await m.saveConfig(true); return [...a, calls()[1].body.restart, F().toast.textContent]; })()',
     '["/api/config",{"config":{"MODEL_FILE":"form.gguf","THREADS":"8"},"restart":false},"Saved.","s",true,"Saved and restarted."]', "сохранение: конфиг из формы и флаг рестарта; тост по флагу; состояние из ответа"),
    ("action_posts_and_schedules", 'globalThis.__fetchReply["/api/action"] = { state: { config: {}, appVersion: "a" } };', 'await (async () => { await m.action("restart"); return [calls()[0].body, st.state.appVersion, named(), F().toast.textContent, globalThis.__timers.filter((x) => x !== "timeout:3200")]; })()',
     '[{"action":"restart"},"a",["closeConfirmModal","renderAll"],"restart sent.",["timeout:500"]]', "действие: POST имени, состояние из ответа, модал закрыт, полная перерисовка, тост, быстрый опрос через 0.5 с"),
    ("action_failure", 'globalThis.__fetchReply["/api/action"] = { __status: 409, error: "busy" };', 'await (async () => { await m.action("stop"); return [F().toast.textContent, named().length]; })()', '["busy",0]', "negative: отказ действия — тост, без перерисовки"),
    ("monitor_remote_source_url_and_html", 'globalThis.__fetchReply["/api/topology/client-monitor?hostId=box-a&kind=nvidia-smi"] = { time: 1700000000, source: "box-a", html: "<b>smi</b>" };',
     'await (async () => { await m.refreshMonitor("nvidia-smi"); const h = F().monitorNvidia.innerHTML; return [calls()[0].path, h.includes("monitor-stamp"), h.includes("] box-a</span>"), h.endsWith("<b>smi</b>"), m.monitorInflight["nvidia-smi"]]; })()',
     '["/api/topology/client-monitor?hostId=box-a&kind=nvidia-smi",true,true,true,false]', "nvidia-smi с удалённым источником идёт через client-monitor хоста; html-ответ с меткой времени и источником"),
    ("monitor_text_output_and_no_output", '', 'await (async () => { globalThis.__fetchReply["/api/topology/client-monitor?hostId=box-a&kind=nvidia-smi"] = { output: "GPU 0" }; await m.refreshMonitor("nvidia-smi"); const a = F().monitorNvidia.textContent; globalThis.__fetchReply["/api/topology/client-monitor?hostId=box-a&kind=nvidia-smi"] = {}; await m.refreshMonitor("nvidia-smi"); return [a.endsWith("nvidia-smi\\n\\nGPU 0"), F().monitorNvidia.textContent.endsWith("no output")]; })()',
     '[true,true]', "текстовый ответ — с меткой и именем монитора; пустой — «no output»"),
    ("monitor_failure_keeps_snapshot", '', 'await (async () => { globalThis.__fetchReply["/api/topology/client-monitor?hostId=box-a&kind=nvidia-smi"] = { output: "GPU 0" }; await m.refreshMonitor("nvidia-smi"); F().monitorNvidia.textContent = "[t] box-a\\n\\nGPU 0"; F().monitorNvidia.innerHTML = "PREV"; globalThis.__fetchReply["/api/topology/client-monitor?hostId=box-a&kind=nvidia-smi"] = { __status: 502, error: "scout down" }; await m.refreshMonitor("nvidia-smi"); const h = F().monitorNvidia.innerHTML; return [h.includes("refresh failed: scout down; keeping previous snapshot"), h.endsWith("PREV")]; })()',
     '[true,true]', "отказ при живом снимке — пометка с причиной и прежний снимок ниже"),
    ("monitor_failure_without_snapshot", 'globalThis.__fetchReply["/api/topology/client-monitor?hostId=box-a&kind=nvidia-smi"] = { __status: 502, error: "scout down" };', 'await (async () => { F().monitorNvidia.textContent = "hover to start"; await m.refreshMonitor("nvidia-smi"); return F().monitorNvidia.textContent; })()', '"scout down"', "negative: отказ без снимка — просто причина"),
    ("monitor_unknown_kind_and_inflight", '', 'await (async () => { await m.refreshMonitor("other"); const a = calls().length; m.monitorInflight["nvidia-smi"] = true; await m.refreshMonitor("nvidia-smi"); m.monitorInflight["nvidia-smi"] = false; return [a, calls().length]; })()', '[0,0]', "negative: неизвестный монитор и запрос в полёте — ни одного запроса"),
    ("start_stop_monitor", '', '(() => { F().monitorIntervalNvidia.value = "3"; m.startMonitor("nvidia-smi"); const a = [...globalThis.__timers]; m.stopMonitor("nvidia-smi"); m.startMonitor(""); return [a, m.monitorState["nvidia-smi"], globalThis.__timers.length]; })()', '[["interval:3000"],null,1]', "старт монитора — интервал из настройки, стоп — обнуление; пустой вид — ничего"),
    ("start_monitor_system_routes_to_series", 'globalThis.__fetchReply["/api/system-monitor"] = MON();', 'await (async () => { m.startMonitor("system"); await new Promise((r) => setImmediate(r)); return [[...globalThis.__timers], calls()[0].path.startsWith("/api/system-monitor")]; })()', '[["interval:1000"],true]', "монитор «system» — это серия: опрос раз в секунду"),
    ("system_monitor_full_then_partial_merge", 'globalThis.__fetchReply["/api/system-monitor"] = MON();',
     'await (async () => { await m.refreshSystemMonitor(); const a = [calls()[0].path.startsWith("/api/system-monitor"), st.ui.latestSystemMonitor.samples.length]; globalThis.__fetchReply["/api/system-monitor?since=1000"] = MON({ partial: true, time: 1650, newestSample: 1650, samples: [{ time: 1650 }], tokenGenSamples: [], incidents: [] }); await m.refreshSystemMonitor(); const s = st.ui.latestSystemMonitor; return [...a, calls()[1].path, s.samples.map((x) => x.time), s.tokenGenSamples.length, s.incidents.map((x) => x.time), s.partial]; })()',
     '[true,2,"/api/system-monitor?since=1000",[1650],1,[500,1640],true]',
     "серия: первый ответ целиком; дальше ?since=; частичный ответ дописывается и режется по retention (600 с от 1650 → 990 и 1000 выпали), инциденты — старый и свежий — остаются: их режут по СВОЕМУ retention (сутки), не по окну сэмплов"),
    ("system_monitor_full_replaces", 'globalThis.__fetchReply["/api/system-monitor"] = MON();', 'await (async () => { await m.refreshSystemMonitor(); globalThis.__fetchReply["/api/system-monitor?since=1000"] = MON({ newestSample: 2000, samples: [{ time: 2000 }] }); await m.refreshSystemMonitor(); return [st.ui.latestSystemMonitor.samples.map((x) => x.time), calls().length]; })()', '[[2000],2]', "ответ без partial заменяет серию целиком"),
    ("system_monitor_render_side_effects", 'globalThis.__fetchReply["/api/system-monitor"] = MON();', 'await (async () => { await m.refreshSystemMonitor(); return [named(), globalThis.__clientsDyn?.innerHTML, F().topologyLlamaClientsCount.textContent]; })()', '[["refreshTopologyActivityState"],"<i>clients</i>",2]', "на доске после серии: активность пересчитана, блок клиентов и их счётчик перерисованы (число; настоящий DOM приведёт к строке)"),
    ("system_monitor_skips_while_form_open", 'globalThis.__fetchReply["/api/system-monitor"] = MON(); st.ui.topologyProxyFormOpen = true;', 'await (async () => { await m.refreshSystemMonitor(); return [named().length, st.ui.latestSystemMonitor.samples.length]; })()', '[0,2]', "открытая форма прокси: серия принята, но доска не трогается"),
    ("system_monitor_failure_status", 'globalThis.__fetchReply["/api/system-monitor"] = { __status: 504, error: "slow" };', 'await (async () => { await m.refreshSystemMonitor(); return [F().systemMonitor.status.textContent, m.systemMonitorInflight]; })()', '["refresh failed: slow",false]', "negative: отказ серии — статус в панели, сторож снят"),
    ("topology_monitor_guards", 'globalThis.__fetchReply["/api/system-monitor"] = MON();', 'await (async () => { await m.refreshTopologyMonitor(); const a = calls().length; m.startTopologyMonitor(); await new Promise((r) => setImmediate(r)); const b = calls().length; m.startSystemMonitor(); await new Promise((r) => setImmediate(r)); const c = calls().length; await m.refreshTopologyMonitor(); return [a, b, c, calls().length, [...globalThis.__timers], named().length]; })()', '[1,2,3,3,["interval:1000","interval:1000"],3]',
     "опрос доски: идёт, пока нет монитора системы; старт — раз в секунду; при запущенном мониторе системы опрос доски молчит (иначе два цикла тянули бы серию наперегонки)"),
    ("save_retention_clamps_and_posts", 'globalThis.__fetchReply["/api/system-monitor/settings"] = { monitor: MON({ samples: [] }) };', 'await (async () => { const inp = F().systemMonitorRetention; inp.value = "5"; await m.saveSystemMonitorRetention(); const a = [inp.value, calls()[0].body]; inp.value = "9999"; await m.saveSystemMonitorRetention(); return [...a, inp.value, calls()[1].body.retentionSeconds, st.ui.latestSystemMonitor.samples.length]; })()',
     '["60",{"retentionSeconds":60},"3600",3600,0]', "retention серии: зажим 60..3600, POST, монитор из ответа применён"),
    ("edit_client_label", 'st.ui.latestSystemMonitor = { clientLabels: { "10.0.0.7": "old" } }; globalThis.__fetchReply["/api/system-monitor"] = MON();', 'await (async () => { let opts = null; globalThis.__stubReturns["dialogs.appPrompt"] = async (_m, o) => { opts = o; return "hermes-box"; }; await m.editClientLabel("10.0.0.7"); return [opts.value, calls()[0].path, calls()[0].body, calls()[1].path.startsWith("/api/system-monitor"), F().toast.textContent]; })()',
     '["old","/api/system-monitor/client-label",{"ip":"10.0.0.7","label":"hermes-box"},true,"Saved."]', "подпись клиента: ввод с прежним значением, POST, перечитывание серии, тост"),
    ("edit_client_label_cancel", '', 'await (async () => { await m.editClientLabel("10.0.0.7"); return calls().length; })()', '0', "negative: отмена ввода — ни запроса"),
    ("gpu_users_proxy_rows_from_correlated", 'st.ui.latestSystemMonitor = { latest: { correlatedActivity: { activeRequests: [{ state: "active", label: "hermes", port: 23001, upstreamPort: 22001, path: "/v1/chat", client: "10.0.0.7", startedAt: 5, phase: "running", bytes: 10, correlation: "gpu" }], recentRequests: [{ label: "old" }] } } };',
     '(h => [h.includes("system-user-row active detailed proxy"), h.includes("<strong>hermes</strong>"), h.includes(":23001 -&gt; :22001"), h.includes("phase running · bytes 10 · tps 12 · via gpu"), h.includes("<strong>old</strong>"), h.includes("system-activity-title")])(m.renderGpuUsers({ clients: [], activeSlots: [], recentRequests: [], gpuUtil: 0, promptTps: 0, predictTps: 0, activity: {} }))',
     '[true,true,true,true,false,true]', "строки прокси: активные из коррелированной активности с телеметрией и корреляцией; недавние не показываются, пока есть активные"),
    ("gpu_users_recent_capped_at_8", 'st.ui.latestSystemMonitor = { latest: { correlatedActivity: { activeRequests: [], recentRequests: Array.from({ length: 12 }, (_, i) => ({ label: "r" + i, status: 200, durationMs: 5, finishedAt: 9 })) } } };',
     '(h => [(h.match(/system-user-row recent detailed proxy/g) || []).length, h.includes("<strong>r7</strong>"), h.includes("<strong>r8</strong>")])(m.renderGpuUsers({ clients: [], activeSlots: [], recentRequests: [], gpuUtil: 0, promptTps: 0, predictTps: 0, activity: {} }))',
     '[8,true,false]', "без активных — недавние, не больше восьми"),
    ("gpu_users_clients_slots_recent_byclient", '', '(h => [h.includes("<strong>box</strong>"), h.includes("10.0.0.7:5000"), h.includes("(port n/a)"), h.includes("<strong>slot 1</strong>"), h.includes("system-user-row active\\">\\n      <strong>slot 1"), h.includes("<strong>10.0.0.9</strong>"), h.includes("<strong>cli</strong>"), h.includes("2 req, last 200"), h.includes("GPU 50% · prompt 10.00 t/s · predict 20.00 t/s")])(m.renderGpuUsers({ clients: [{ clientName: "box", clientIp: "10.0.0.7", clientPort: 5000, localIp: "10.0.0.1", localPort: 22001 }, { clientIp: "10.0.0.8" }], activeSlots: [{ id: 1, isProcessing: true, taskId: 3 }], recentRequests: [{ clientIp: "10.0.0.9", path: "/v1/x", status: 200 }], gpuUtil: 50, promptTps: 10, predictTps: 20, activity: { recentByClient: [{ clientName: "cli", count: 2, lastStatus: 200 }] } }))',
     '[true,true,true,true,true,true,true,true,true]', "клиенты с адресом и без порта, слоты с обработкой, недавние, «по клиентам» без тайминга, строка скорости"),
    ("gpu_users_empty", '', 'm.renderGpuUsers({ clients: [], activeSlots: [], recentRequests: [], gpuUtil: 0, promptTps: 0, predictTps: 0, activity: {} }).includes("system-process-empty")', 'true', "negative: ничего — пустое состояние"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 28:
        print(f"js polling FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js polling: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_polling.tmp.mjs"
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
        print(f"js polling FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("опрос: живое состояние, мониторы, слияние серии, пользователи GPU:")
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
    print(f"js polling OK: настоящий модуль в node, {len(PINS)} пинов опроса значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
