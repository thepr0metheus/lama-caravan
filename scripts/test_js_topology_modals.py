#!/usr/bin/env python3
"""Snapshot of static/js/topology-modals.js — the board's modals and their write paths.

What's worth pinning by value here. The schedule grid: rules → [7][24] →
rules (the first rule wins, a window crossing midnight, merging adjacent
hours and days that share a window). Priorities: a level from its index, a
shade from its level, ordering in the modal (by priority, then by port),
writing only the CHANGED levels and zeroing out cleared ones. Queue:
percentages from edits layered over policy, per-proxy overrides (null =
reset), timelines with "(default)" for no timeout. Client and agent details:
no manager / unreachable / ok, provider roles from primary/fallback
references. Logs: a row summary and parsed details.

`savePriorityModal` once reached for `policyChanges` after saving, which
doesn't exist in that function — a ReferenceError after the save had already
gone through; the snapshot pinned this as-is first, and the next commit
fixed it and rewrote the pin.

The module is real (scripts/_js_harness.mjs). The open-modal flags live in
`topology-dnd` (a stub) — set via globalThis.__stubValues BEFORE import; the
weekday constants come from `canvas` the same way, so `indexOf` runs on an
array, not on a stub function.

Run: python3 scripts/test_js_topology_modals.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("canvas,polling,topology-dnd,topology-render,dialogs,charts,cables,cloud,history,favorites,config-locator,"
         "system-panels,onboarding,onboarding-tours,usage-stats,dialog-llamas,models-page,system-page,memory,"
         "command-preview,llama-edit,remote-cells,topology-nodes")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
// Флаги «модал открыт» — экспортные let соседа topology-dnd; заглушка получает их значением.
globalThis.__stubValues = {
  "canvas.SCHEDULE_WEEKDAYS": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
  "canvas.SCHEDULE_DAY_LABELS": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
  "topology-dnd.topologyLlamaDetailOpen": true, "topology-dnd.topologyGpuModalOpen": true,
  "topology-dnd.topologyScheduleRouterId": "router:sched", "topology-dnd.topologySchedulePaintOutput": "", "topology-dnd.topologyScheduleGrid": null,
};
const m = await import(pathToFileURL(process.env.JS_ROOT + "/topology-modals.js").href);
const toastEl = () => ({ textContent: "", classList: { add() {}, remove() {} } });
const toastText = () => globalThis.__fields.toast.textContent;
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body === null ? null : JSON.parse(c.body) }));
const PROXIES = () => [
  { id: "ctl:proxy:23001", port: 23001, label: "hermes", upstreamHost: "127.0.0.1", upstreamPort: 22001, priority: 3, clientTimeoutSeconds: 1800 },
  { id: "ctl:proxy:23003", port: 23003, label: "scout", upstreamHost: "127.0.0.1", upstreamPort: 22003, priority: 7 },
  { id: "ctl:proxy:23005", port: 23005, label: "plain", upstreamHost: "127.0.0.1", upstreamPort: 22005, cloudFallbackProviderId: "cb:terra" },
  { id: "ctl:proxy:23007", port: 23007, label: "cloudy", upstreamType: "cloud", providerId: "cb:terra" },
];
const ROUTER = () => ({ id: "router:sched", name: "sched", outputs: [{ id: "srv:22001", label: "a" }, { id: "cb:terra", label: "☁ terra" }],
  rules: { default: "srv:22001", schedule: [{ days: ["mon", "tue"], from: "09:00", to: "17:59", output: "cb:terra" }] } });
const TOPO = (extra = {}) => ({ proxies: PROXIES(), clients: [{ id: "box-a", name: "Box A", agents: [{ id: "hermes", name: "Hermes" }] }], routers: [ROUTER()], assignments: {}, proxyPolicy: { cloudFallbackPct: 20, priorityPreemptPct: 50, queueAbortPct: 85, preemptGraceSec: 20 }, ...extra });
const reset = () => {
  st.setState({ config: {} }); st.setTopology(TOPO()); st.ui.latestSystemMonitor = null; st.ui.topologyAgentConfigMode = "";
  m.closeQueuePriorityModal(); m.closePriorityModal(); m.closeClientDetail(); m.closeAgentConfigModal(); m.closeRawConfigViewer();
  globalThis.__fields = { toast: toastEl() };
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {};
  globalThis.__stubReturns = { "canvas.scheduleOutputColor": (r, id) => (id ? "#123456" : ""), "polling.formatTps": (v) => `${v} t/s`, "dialogs.appPrompt": async () => null };
};
reset();
const G = (spec) => { const g = Array.from({ length: 7 }, () => Array(24).fill("")); for (const [d, from, to, out] of spec) for (let h = from; h <= to; h++) g[d][h] = out; return g; };
const out = {};
"""

PINS = [
    # ── pure helpers ──
    ("hue_by_level", '', '[m.priorityHueForLevel(1), m.priorityHueForLevel(10), m.priorityHueForLevel(0), m.priorityHueForLevel("x"), m.priorityHueForLevel(11)]', '[220,22,220,220,22]',
     "оттенок: 1 → 220, 10 → 22; мусор и выход за края — зажаты"),
    ("level_by_index", '', '[m.priorityLevelForIndex(0), m.priorityLevelForIndex(9), m.priorityLevelForIndex(12)]', '[10,1,1]', "уровень: первый в списке — 10, десятый — 1, дальше — 1"),
    ("fmt_sec", '', '[m._fmtSec(0), m._fmtSec(59), m._fmtSec(60), m._fmtSec(90), m._fmtSec(undefined)]', '["0s","59s","1m","1m 30s","0s"]', "секунды: 0s / 59s / 1m / 1m 30s; пусто — 0s"),
    # ── schedule: rules → grid ──
    ("rules_to_grid_window", '',
     '(g => [g[0][8], g[0][9], g[0][17], g[0][18], g[1][9], g[2][9]])(m.scheduleRulesToGrid(ROUTER()))',
     '["","cb:terra","cb:terra","","cb:terra",""]', "окно 09:00–17:59 по пн/вт: часы 9..17 закрашены, 8 и 18 — нет, среда пуста"),
    ("rules_to_grid_no_days_means_all", '',
     '(g => g.map((d) => d[12]))(m.scheduleRulesToGrid({ rules: { schedule: [{ from: "12:00", to: "12:59", output: "x" }] } }))',
     '["x","x","x","x","x","x","x"]', "правило без дней — все семь"),
    ("rules_to_grid_wraps_midnight", '',
     '(g => [g[4][21], g[4][22], g[4][23], g[4][0], g[4][5], g[4][6]])(m.scheduleRulesToGrid({ rules: { schedule: [{ days: ["fri"], from: "22:00", to: "05:59", output: "n" }] } }))',
     '["","n","n","n","n",""]', "окно через полночь: 22..23 и 0..5 того же дня"),
    ("rules_to_grid_first_rule_wins", '',
     '(g => [g[0][10], g[0][14]])(m.scheduleRulesToGrid({ rules: { schedule: [{ days: ["mon"], from: "09:00", to: "11:59", output: "first" }, { days: ["mon"], from: "10:00", to: "15:59", output: "second" }] } }))',
     '["first","second"]', "пересечение: первое правило побеждает (семантика движка), второе берёт остаток"),
    ("rules_to_grid_skips_garbage", '',
     '(g => g.flat().filter(Boolean).length)(m.scheduleRulesToGrid({ rules: { schedule: [{ days: ["mon"], from: "xx", to: "12:59", output: "a" }, { days: ["someday"], from: "09:00", to: "12:59", output: "b" }] } }))',
     '0', "negative: нечисловой час и неизвестный день — правило пропущено без исключения"),
    ("rules_to_grid_null_router", '', 'm.scheduleRulesToGrid(null).flat().filter(Boolean).length', '0', "negative: без роутера — пустая сетка"),
    # ── schedule: grid → rules ──
    ("grid_to_rules_merges_hours_and_days", '',
     'm.scheduleGridToRules(G([[0, 9, 17, "a"], [1, 9, 17, "a"], [2, 0, 23, "b"]]))',
     '[{"days":["mon","tue"],"from":"09:00","to":"17:59","output":"a"},{"days":["wed"],"from":"00:00","to":"23:59","output":"b"}]',
     "соседние часы склеены в окно, дни с одинаковым окном — в одно правило"),
    ("grid_to_rules_two_runs_same_day", '',
     'm.scheduleGridToRules(G([[0, 9, 10, "a"], [0, 14, 15, "a"]]))',
     '[{"days":["mon"],"from":"09:00","to":"10:59","output":"a"},{"days":["mon"],"from":"14:00","to":"15:59","output":"a"}]',
     "два отрезка в один день — два правила, не одно склеенное"),
    ("grid_to_rules_empty", '', 'm.scheduleGridToRules(G([]))', '[]', "negative: пустая сетка — ни одного правила"),
    ("schedule_round_trip", '',
     '(r => m.scheduleGridToRules(m.scheduleRulesToGrid({ rules: { schedule: r } })))([{ days: ["mon", "tue"], from: "09:00", to: "17:59", output: "cb:terra" }])',
     '[{"days":["mon","tue"],"from":"09:00","to":"17:59","output":"cb:terra"}]', "правила → сетка → правила: каноническое правило возвращается тем же"),
    # ── schedule: the modal ──
    ("schedule_modal_cells_and_palette", '',
     '(h => [(h.match(/data-sched-cell="1"/g) || []).length, (h.match(/sched-cell painted/g) || []).length, (h.match(/data-sched-paint="/g) || []).length, (h.match(/sched-cell painted"[^>]*background:#123456/g) || []).length])(m.renderTopologyScheduleModal())',
     '[168,18,3,18]', "7×24 клеток; закрашены 2 дня × 9 часов; палитра = выходы + ластик; цвет из canvas на каждой закрашенной"),
    ("schedule_modal_router_missing", 'st.setTopology(TOPO({ routers: [] }));', 'm.renderTopologyScheduleModal()', '""', "negative: роутер модала не найден — пустая строка"),
    # ── client details ──
    ("client_detail_closed", '', 'm.renderTopologyClientDetail()', '""', "negative: детали не открыты — пусто"),
    ("client_detail_no_manager", 'm.openClientDetail("box-a", "Hermes");',
     '(h => [h.includes("OpenClaw config — Box A · Hermes"), h.includes("No OpenClaw config manager registered for <code>box-a</code>")])(m.renderTopologyClientDetail())',
     '[true,true]', "без менеджера конфига — так и сказано, заголовок «хост · агент»"),
    ("client_detail_unreachable", 'st.setTopology(TOPO({ openclawConfigs: { "box-a": { ok: false, url: "http://box-a:18789", error: "timeout" } } })); m.openClientDetail("box-a", "Box A");',
     '(h => [h.includes("Could not reach <code>http://box-a:18789</code>: timeout"), h.includes("OpenClaw config — Box A<")])(m.renderTopologyClientDetail())',
     '[true,true]', "не достучались — URL и причина; имя агента = имя хоста → без « · »"),
    ("client_detail_ok_body", 'st.setTopology(TOPO({ openclawConfigs: { "box-a": { ok: true, fetchedAt: 1700000000, data: { agents: { defaults: { timeoutSeconds: 600, contextTokens: 158000, model: { primary: "p/gpt", fallbacks: ["f/mini"] } } }, models: { providers: { p: { baseUrl: "http://ctl:23001/v1", timeoutSeconds: 600, models: [{ id: "gpt", contextWindow: 158000, maxTokens: 4096 }] } } }, gateway: { port: 18789, bind: "lan", auth: { mode: "token" } } } } } })); m.openClientDetail("box-a");',
     '(h => [h.includes("<code>p/gpt</code>"), h.includes("<code>f/mini</code>"), h.includes("http://ctl:23001/v1"), h.includes("ctx 158000 · max 4096"), h.includes("<strong>18789</strong>"), h.includes("Fetched ")])(m.renderTopologyClientDetail())',
     '[true,true,true,true,true,true]', "ok: primary/fallback, провайдер с URL и моделью, шлюз, время выборки"),
    ("openclaw_body_without_providers", '', 'm.renderOpenclawConfigBody({}, null).includes("no providers configured")', 'true', "negative: пустой конфиг — «no providers configured», без исключения"),
    ("refresh_client_detail_stores_reply", 'm.openClientDetail("box-a"); globalThis.__fetchReply["/api/openclaw-config?client=box-a&refresh=1"] = { ok: true, data: { gateway: { port: 1 } } };',
     'await (async () => { await m.refreshClientDetail(); return [calls()[0].path, st.topology.openclawConfigs["box-a"].data.gateway.port, m.topologyClientDetailLoading]; })()',
     '["/api/openclaw-config?client=box-a&refresh=1",1,false]', "обновление: GET с refresh=1, ответ ложится в topology, флаг загрузки снят"),
    ("refresh_client_detail_closed_is_noop", '', 'await (async () => { await m.refreshClientDetail(); return calls().length; })()', '0', "negative: детали закрыты — запроса нет"),
    # ── agent config ──
    ("agent_config_closed", '', 'm.renderTopologyAgentConfigModal()', '""', "negative: режим пуст — пусто"),
    ("agent_config_ports_mode_roles", 'globalThis.__fetchReply["/api/topology/agent-openclaw?client=box-a&agent=hermes"] = { ok: true, path: "/home/x/.openclaw/openclaw.json", data: { agents: { defaults: { model: { primary: "hemi/gpt", fallbacks: ["spare/mini"] } } }, models: { providers: { hemi: { baseUrl: "http://ctl:23001/v1" }, spare: { baseUrl: "http://ctl:23002/v1" }, other: { baseUrl: "http://x" } } } } };',
     'await (async () => { await m.openAgentConfigModal("box-a", "hermes", "ports"); const h = m.renderTopologyAgentConfigModal(); return [h.includes("Hermes — .openclaw/openclaw.json"), h.includes("<strong>hemi</strong>\\n          <span class=\\"proxy-role-label\\">primary</span>"), h.includes("<strong>spare</strong>\\n          <span class=\\"proxy-role-label\\">fallback</span>"), h.includes("<strong>other</strong>\\n          \\n"), m.topologyAgentConfigLoading]; })()',
     '[true,true,true,true,false]', "режим ports: роли primary/fallback из ссылок defaults, прочие без роли"),
    ("agent_config_raw_mode_and_error", 'globalThis.__fetchReply["/api/topology/agent-openclaw?client=box-a&agent=hermes"] = { __status: 502, error: "scout down" };',
     'await (async () => { await m.openAgentConfigModal("box-a", "hermes", "raw"); return [m.renderTopologyAgentConfigModal().includes("topology-incident-line failed\\">scout down"), m.topologyAgentConfigResult.ok]; })()',
     '[true,false]', "negative: отказ скаута — строка ошибки, результат ok:false"),
    # ── queue and priorities: rendering ──
    ("queue_modal_closed", '', 'm.renderTopologyQueuePriorityModal()', '""', "negative: модал очереди закрыт — пусто"),
    ("queue_modal_policy_and_edits", 'm.openQueuePriorityModal(); m.topologyQueuePriorityEdits.cloudFallbackPct = 30;',
     '(h => [h.includes("qp-handle-pct\\">30%"), h.includes("qp-handle-pct\\">50%"), h.includes("qp-handle-pct\\">85%"), h.includes("hermes · wait_timeout=1800s → ↑☁ 540s · 👑 900s · ✕ 1530s")])(m.renderTopologyQueuePriorityModal())',
     '[true,true,true,true]', "проценты: правка поверх политики; пример в секундах по первому локальному прокси с таймаутом"),
    ("queue_timelines_rows", 'm.openQueuePriorityModal();',
     '(h => [(h.match(/data-qp-proxy-row="/g) || []).length, h.includes(\'data-qp-proxy-row="23007"\'), h.includes("wait_timeout=1800s</span>"), h.includes("wait_timeout=3600s (default)"), (h.match(/qp-handle-inactive/g) || []).length])(m._renderQueueThresholdTimelines(20, 50, 85))',
     '[3,false,true,true,3]', "таймлайны: только локальные прокси; без таймаута — 3600 (default); неактивные ручки: облако у двух без облака, корона у одного без приоритета"),
    ("queue_timelines_override_dot", 'globalThis.__fetchReply["/api/queue-thresholds"] = { thresholds: { proxies: [{ port: 23005, hasAbortOverride: true, effectiveAbortPct: 70 }] } };',
     'await (async () => { await m.fetchQueueThresholds(); const h = m._renderQueueThresholdTimelines(20, 50, 85); return [h.includes(\'data-qp-proxy-row="23005" class\') || /qp-proxy-tl-row has-override" data-qp-proxy-row="23005"/.test(h), (h.match(/has-override/g) || []).length, h.includes(\'data-qp-proxy-reset="23005"\')]; })()',
     '[true,1,true]', "сохранённое переопределение: точка и кнопка сброса ровно у своего прокси"),
    ("queue_example_without_timeout_proxy", 'st.setTopology(TOPO({ proxies: [{ id: "x", port: 1, label: "x" }] }));', 'm._queuePctExampleText(20, 50, 85)', '""', "negative: ни у одного локального прокси нет таймаута — примера нет"),
    ("priority_modal_closed", '', 'm.renderTopologyPriorityModal()', '""', "negative: модал приоритетов закрыт — пусто"),
    ("priority_open_orders_by_priority_then_port", '', '(() => { m.openPriorityModal(""); return m.topologyPriorityOrder; })()', '["ctl:proxy:23003","ctl:proxy:23001"]',
     "порядок: по приоритету вниз, прокси без приоритета не в списке"),
    ("priority_open_unshifts_the_clicked_proxy", '', '(() => { m.openPriorityModal("ctl:proxy:23005"); return m.topologyPriorityOrder; })()', '["ctl:proxy:23005","ctl:proxy:23003","ctl:proxy:23001"]',
     "клик по 👑 на прокси без приоритета ставит его первым"),
    ("priority_open_unknown_proxy_ignored", '', '(() => { m.openPriorityModal("ctl:proxy:29999"); return m.topologyPriorityOrder; })()', '["ctl:proxy:23003","ctl:proxy:23001"]', "negative: неизвестный прокси в список не попадает"),
    ("priority_modal_rows", 'm.openPriorityModal("");',
     '(h => [(h.match(/data-priority-row="/g) || []).length, h.includes("topology-priority-badge\\" style=\\"background:hsl(22,66%,42%)\\">10</span>"), h.includes(":23003 → 127.0.0.1:22003"), h.includes("hsl(44,66%,42%)\\">9</span>")])(m.renderTopologyPriorityModal())',
     '[2,true,true,true]', "строки: уровень 10 первому (тёплый оттенок 22), 9 второму (44), endpoint :port → upstream"),
    ("priority_modal_empty", 'st.setTopology(TOPO({ proxies: [{ id: "x", port: 1, label: "x" }] })); m.openPriorityModal("");',
     'm.renderTopologyPriorityModal().includes("No priority routes. Close and click 👑 on a proxy to add one.")', 'true', "negative: без приоритетных прокси — подсказка"),
    # ── queue: writing ──
    ("save_queue_nothing_changed_closes", 'm.openQueuePriorityModal();',
     'await (async () => { await m.saveQueuePriorityModal(); return [calls().length, m.topologyQueuePriorityModalOpen, toastText()]; })()', '[0,false,""]', "negative: без правок — закрыть, ни запроса, ни тоста"),
    ("save_queue_global_policy_merged", 'm.openQueuePriorityModal(); m.topologyQueuePriorityEdits.cloudFallbackPct = 30; m.topologyQueuePriorityEdits.preemptEnabled = false;',
     'await (async () => { await m.saveQueuePriorityModal(); const c = calls(); return [c.map((x) => x.path), c[0].body, toastText(), m.topologyQueuePriorityModalOpen]; })()',
     '[["/api/agent-proxies/policy","/api/queue-thresholds/recalc"],{"policy":{"cloudFallbackPct":30,"priorityPreemptPct":50,"queueAbortPct":85,"preemptGraceSec":20,"preemptEnabled":false}},"saved · queue policy",false]',
     "глобальная политика: правки слиты поверх сохранённой, потом пересчёт порогов"),
    ("save_queue_route_overrides_null_clears", 'm.openQueuePriorityModal(); m.topologyQueuePriorityEdits.routes = { "23005": { queueAbortPct: 70, cloudFallbackPct: null, junk: 1 }, "23001": {} };',
     'await (async () => { await m.saveQueuePriorityModal(); const c = calls(); return [c.map((x) => x.path), c[0].body]; })()',
     '[["/api/agent-proxies/route-policy","/api/queue-thresholds/recalc"],{"port":23005,"queueAbortPct":70,"cloudFallbackPct":null}]',
     "per-proxy: только известные ключи, null уходит как сброс, пустая правка не шлётся; порт — числом"),
    # ── priorities: writing ──
    ("save_priority_no_change_closes", 'st.setTopology(TOPO({ proxies: [{ id: "ctl:proxy:23003", port: 23003, priority: 10 }, { id: "ctl:proxy:23001", port: 23001, priority: 9 }] })); m.openPriorityModal("");',
     'await (async () => { await m.savePriorityModal(); return [calls().length, m.topologyPriorityModalOpen]; })()', '[0,false]', "negative: порядок не менялся — ни запроса"),
    ("save_priority_writes_changed_levels_and_toasts", 'm.openPriorityModal(""); m.topologyPriorityOrder.reverse();',
     'await (async () => { let err = ""; try { await m.savePriorityModal(); } catch (e) { err = String(e.message); } return [calls().map((x) => x.body), err, m.topologyPriorityModalOpen, toastText()]; })()',
     '[[{"port":23001,"priority":10},{"port":23003,"priority":9}],"",false,"saved · 2 changes"]',
     "изменившиеся уровни записаны, модал закрыт, тост считает изменения — без исключения после записи"),
    ("save_priority_removed_gets_zero", 'm.openPriorityModal(""); m.topologyPriorityOrder.pop();',
     'await (async () => { try { await m.savePriorityModal(); } catch (e) {} return calls().map((x) => x.body); })()',
     '[{"port":23001,"priority":0},{"port":23003,"priority":10}]', "снятый с приоритета получает 0, оставшийся — новый уровень"),
    # ── other write paths ──
    ("route_policy_patch_known_proxy", '', 'await (async () => { await m.setTopologyProxyRoutePolicy("ctl:proxy:23005", { priority: 4 }); return [calls()[0].path, calls()[0].body, toastText()]; })()',
     '["/api/agent-proxies/route-policy",{"port":23005,"priority":4},"proxy policy updated"]', "патч политики маршрута: порт из прокси плюс патч"),
    ("route_policy_unknown_proxy_noop", '', 'await (async () => { await m.setTopologyProxyRoutePolicy("ctl:proxy:29999", { priority: 4 }); await m.stopTopologyProxy("ctl:proxy:29999"); return calls().length; })()', '0', "negative: неизвестный прокси — ни запроса"),
    ("stop_proxy", '', 'await (async () => { await m.stopTopologyProxy("ctl:proxy:23001"); return [calls()[0].path, calls()[0].body, toastText()]; })()', '["/api/agent-proxies/stop",{"port":23001},"stop requested"]', "остановка прокси: порт на провод, тост"),
    ("alias_saved_trimmed", 'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "  Box Alpha "; globalThis.__fetchReply["/api/topology/client-alias"] = { ok: true, topology: TOPO({ clients: [] }) };',
     'await (async () => { await m.editTopologyClientAlias("box-a", "Box A"); return [calls()[0].path, calls()[0].body, toastText(), st.topology.clients.length]; })()',
     '["/api/topology/client-alias",{"hostId":"box-a","name":"Box Alpha"},"client name saved",0]', "псевдоним: обрезан, topology из ответа применена"),
    ("alias_empty_resets_cancel_sends_nothing", 'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "   ";',
     'await (async () => { await m.editTopologyClientAlias("box-a", "Box A"); const a = [calls()[0].body.name, toastText()]; globalThis.__stubReturns["dialogs.appPrompt"] = async () => null; await m.editTopologyClientAlias("box-a", "Box A"); return [...a, calls().length]; })()',
     '["","client name reset",1]', "пустое имя — сброс; отмена — ни запроса"),
    # ── logs ──
    ("log_summary", '', 'm.topologyLogSummary({ timeIso: "10:00", event: "proxy", item: { route: "hermes", port: 23001, status: 502, error: "upstream down" } })', '"10:00 · proxy · hermes · :23001 · status 502 · upstream down"', "сводка строки лога — поля через «·», пустые пропущены"),
    ("log_summary_empty", '', 'm.topologyLogSummary({})', '""', "negative: пустая строка лога — пусто"),
    ("log_detail_sections", '', '(h => [h.includes("Upstream error body"), h.includes("&quot;code&quot;: 400"), h.includes("model: gpt-5.6"), h.includes("<td>1234 ms</td>"), h.includes("waited: 800 m"), h.includes("Raw JSON"), h.includes("log-detail-value")])(m.renderTopologyLogDetail({ upstreamErrorBody: "{\\"code\\":400}", cloudMeta: { model: "gpt-5.6", toolCount: 2 }, item: { status: 400, error: "bad", durationMs: 1234, queue: { queuedMs: 800 } } }))',
     '[true,true,true,true,true,true,false]', "детали: тело ошибки красиво, пилюли облака, таблица полей, очередь, raw; отдельная строка ошибки не дублируется при теле"),
    ("load_logs_query", 'globalThis.__fetchReply["/api/agent-proxy-logs?date=2026-09-01&limit=300"] = { date: "2026-09-01", rows: [] };',
     'await (async () => { await m.loadTopologyLogs("2026-09-01"); const a = [calls()[0].path, m.topologyLogsDate]; await m.loadTopologyLogs(""); return [...a, calls()[1].path]; })()',
     '["/api/agent-proxy-logs?date=2026-09-01&limit=300","2026-09-01","/api/agent-proxy-logs?limit=300"]', "логи: дата и лимит в запросе; без даты — только лимит"),
    # ── raw config / gpu / llama ──
    ("raw_config_open_and_close", 'globalThis.__fetchReply["/api/agent-proxies/raw"] = { content: "{\\"routes\\":[]}", path: "/srv/agent-proxies.json" };',
     'await (async () => { await m.openRawConfigViewer(); const h = m.renderTopologyRawConfigModal(); const a = [h.includes("<strong>/srv/agent-proxies.json</strong>"), h.includes("{&quot;routes&quot;:[]}")]; m.closeRawConfigViewer(); return [...a, m.renderTopologyRawConfigModal()]; })()',
     '[true,true,""]', "сырой конфиг: путь и содержимое; после закрытия — пусто"),
    ("raw_config_error", 'globalThis.__fetchReply["/api/agent-proxies/raw"] = { __status: 500, error: "nope" };',
     'await (async () => { await m.openRawConfigViewer(); return m.renderTopologyRawConfigModal().includes("error: nope"); })()', 'true', "negative: отказ — текст ошибки в модале"),
    ("gpu_modal_summary", 'st.setState({ config: {}, logs: "", runtime: { props: { default_generation_settings: { n_ctx: 8192 } } } });',
     '(h => [h.includes("(no logs)"), h.includes("&quot;n_ctx&quot;: 8192"), h.includes("GPU 0 — Logs &amp; Raw API")])(m.renderTopologyGpuModal())', '[true,true,true]', "GPU-модал: заглушка без логов, сводка с n_ctx"),
    ("llama_detail_fields", 'st.setTopology(TOPO({ server: { llamaServers: [{ name: "Current", model: "/models/Qwen3-Embedding-0.6B-f16.gguf", port: 22001, status: { phase: "ready" }, service: "llama@1" }], runtime: { props: { n_ctx: 4096 } } } }));',
     '(h => [h.includes("<strong>Qwen3-Embedding-0.6B</strong>"), h.includes("<strong>4096</strong>"), h.includes("<strong>22001</strong>"), h.includes("<strong>ready</strong>"), h.includes("<code>llama@1</code>")])(m.renderTopologyLlamaDetail())',
     '[true,true,true,true,true]', "детали модели: красивое имя, окно, порт, фаза, сервис"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 40:
        print(f"js topology-modals FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js topology-modals: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_topology_modals.tmp.mjs"
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
        print(f"js topology-modals FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("модалы доски: расписание, приоритеты, очередь, детали, пути записи:")
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
    print(f"js topology-modals OK: настоящий модуль в node, {len(PINS)} пинов модалов значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
