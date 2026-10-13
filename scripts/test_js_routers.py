#!/usr/bin/env python3
"""Snapshot of static/js/routers.js — the WRITE path for the routing graph and output cards.

`saveRouters` is the only door through which the board changes routers: a
cable on the kanban, a client's wait budget, a rule node — all of it goes
through this one function. Before this snapshot it had not had a single
test, and its promise is non-trivial: the mutator gets a COPY, state only
changes from the server's response, and a server failure doesn't leave the
board stuck in "saving" forever. Pinned across three trails — what went out
on the wire, what happened to the state, what's left after a failure.

Alongside that: what reads the graph for drawing — an output's caption
(a pool's by the pool's name, local ones by the model's nice name from the
server), an output's liveness (matched by upstream host:port, for a pool
by providerId, because a pool has no host:port of its own), the router's
compact card, and the output panel with its single "default" radio button
and a row per pool that says its steps and what keeps it from serving.

The module is loaded FOR REAL (scripts/_js_harness.mjs), as are its
neighbors state/i18n/form/utils/model-meta/topology-activity/topology-proxies;
only the DOM-heavy ones are stubbed: canvas, topology-dnd, topology-render,
charts, dialogs.

Run: python3 scripts/test_js_routers.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("canvas,polling,topology-dnd,topology-render,topology-modals,topology-nodes,charts,cables,cloud,history,"
         "dialogs,favorites,config-locator,system-panels,onboarding,usage-stats,dialog-llamas,"
         "models-page,system-page,onboarding-tours,memory,command-preview,llama-edit,remote-cells")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
Date.now = () => 1_700_000_100_000;
// saveRouters держит «муравьиную дорожку» ещё 350 мс, если запись была быстрой:
// пусть часы говорят, что прошла секунда, — снимок не ждёт анимацию.
let _perf = 0; globalThis.performance = { now: () => (_perf += 1000) };
globalThis.__stubValues = { ...(globalThis.__stubValues || {}),
  "canvas._cvView": { tx: 0, ty: 0, scale: 1 }, "canvas._cvPos": {} };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/routers.js").href);
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const fill = (s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => v[k]);
// Тост — то, что видит оператор: третий след действия рядом с проводом и
// состоянием. Без элемента настоящий toast() падает на null, и харнесс выдавал
// бы свой артефакт за поведение модуля.
const toastEl = () => ({ textContent: "", classList: { add() {}, remove() {} } });
const toastText = () => globalThis.__fields.toast.textContent;
const reset = () => { st.setState({ config: {} });
  st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
  st.ui.latestSystemMonitor = null; globalThis.__fields = { toast: toastEl() };
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; };
reset();
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body }));
const ROUTER = (extra = {}) => ({ id: "router:default", name: "default", inputs: [], outputs: [
  { id: "srv:22001", label: "Qwen3-Embedding-0.6B-f16.gguf ", upstreamHost: "127.0.0.1", upstreamPort: 22001, upstreamType: "llama", providerId: "" },
  { id: "cb:terra", label: "☁ gpt-5.6-terra", upstreamHost: "", upstreamPort: 0, upstreamType: "cloud", providerId: "gpt-5-6-terra" },
], rules: { default: "cb:terra", schedule: [], bySource: [] }, graph: { nodes: [], edges: [], inputs: {} }, ...extra });
// A pool is one output, cb:<pool id> (caravan/admin/proxies_config.py, pool_output).
const STEP = (id, accountId, model, extra = {}) => ({ id, accountId, model, enabled: true, switchAt: {}, ...extra });
const CLOUD = (pool = {}) => ({ cloudAccounts: [{ id: "openai-subscription", type: "openai", name: "OpenAI (ChatGPT Plus)" }, { id: "or", type: "openrouter", name: "OpenRouter" }],
  pools: [{ id: "gpt-5-6-terra", name: "Terra", ports: [], steps: [STEP("s1", "openai-subscription", "gpt-5.6-terra"), STEP("s2", "or", "vendor/terra")], ...pool }] });
const MON = (items, port = 23001) => ({ latest: { agentProxies: { agents: { [String(port)]: { port, active: items.active || [], recent: items.recent || [] } } } } });
// machineAt is topology-nodes' (stubbed here; the real one is pinned in
// test_js_topology_nodes): two addresses of one machine, one other, the rest unknown.
const MACHINES = { "127.0.0.1": { key: "m-ctl", name: "ctl-box", address: "10.0.0.5" },
                   "10.0.0.5": { key: "m-ctl", name: "ctl-box", address: "10.0.0.5" },
                   "10.0.0.9": { key: "m-b", name: "box-b", address: "10.0.0.9" } };
globalThis.__stubReturns = { ...(globalThis.__stubReturns || {}),
  "topology-nodes.machineAt": (a) => MACHINES[a] || { key: String(a), name: String(a), address: String(a) },
  // output-cells.js reads a cell's runner and jobs through topology-nodes (stubbed here; the real
  // rules are pinned in test_js_output_cells and test_js_topology_nodes): every cell is a chat model.
  "topology-nodes.cellRunnerId": (cfg) => String((cfg || {}).RUNNER || "llama-server"), "topology-nodes.cellJobs": () => ["llm"],
  "canvas.canvasNodes": () => [], "canvas.renderRouterNodeConfig": () => "",
  "canvas.canvasPanels": () => ({ left: "<aside>CLIENTS</aside>", right: "<aside>SERVERS</aside>" }) };
const rowIds = (h) => [...h.matchAll(/data-router-out-row="([^"]+)"/g)].map((x) => x[1]);
// The groups of the Servers panel in their order, each by the outputs it holds: a machine's, a pool's.
const groupOrder = (h) => [...h.matchAll(/class="router-(?:out-host-group|prov router-pool)[^"]*" data-cv-group-outs="([^"]*)"/g)].map((x) => x[1]);
const heads = (h) => [...h.matchAll(/router-out-host-label">([^<]*?)\s*(?:<span class="router-out-host-addr">([^<]*)<\/span>)?</g)].map((x) => [x[1], x[2] || ""]);
const out = {};
"""

PINS = [
    # ── routerById ──
    ("router_by_id_found",
     'st.setTopology({ ...st.topology, routers: [ROUTER()] });',
     'm.routerById(st.topology.routers, "router:default")?.name',
     '"default"',
     "positive: роутер находится по id"),
    ("router_by_id_missing_is_undefined",
     '',
     'm.routerById([ROUTER()], "router:nope") === undefined',
     'true',
     "negative: неизвестный id — undefined, а не пустой объект, который выглядел бы как роутер"),
    # ── an output's caption ──
    ("output_label_cloud_by_pool_name",
     'st.setTopology({ ...st.topology, ...CLOUD() });',
     'm.topologyRouterOutputLabel({ upstreamType: "cloud", providerId: "gpt-5-6-terra" })',
     '"☁ Terra"',
     "выход пула подписывается ИМЕНЕМ пула, не id"),
    ("output_label_cloud_keeps_own_label",
     'st.setTopology({ ...st.topology, ...CLOUD() });',
     'm.topologyRouterOutputLabel({ upstreamType: "cloud", providerId: "gpt-5-6-terra", label: "☁ gpt-5.6-terra" })',
     '"☁ gpt-5.6-terra"',
     "boundary: у выхода есть своя подпись (контроллер ставит имя пула) — она побеждает"),
    ("output_label_cloud_unknown_pool",
     '',
     'm.topologyRouterOutputLabel({ upstreamType: "cloud", providerId: "gone" })',
     '"☁ gone"',
     "negative: пул удалён — показывается его id, а не «cloud» и не пустота"),
    ("output_label_local_pretty_model",
     'st.setTopology({ ...st.topology, nodes: [{ id: "m-ctl", servers: [{ port: 22001, model: "/models/Qwen3-Embedding-0.6B-f16.gguf" }] }] });',
     'm.topologyRouterOutputLabel({ upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22001, label: "Qwen3-Embedding-0.6B-f16.gguf :22001" })',
     '"Qwen3-Embedding-0.6B :22001"',
     "локальный выход — КРАСИВОЕ имя модели ячейки (машина по адресу, ячейка по порту) плюс порт, а не сырое имя .gguf из label"),
    ("output_label_local_says_what_the_cell_runs",
     'st.setTopology({ ...st.topology, nodes: [{ id: "m-b", servers: [{ port: 22014, model: "en", cellLabel: "moonshine en" },'
     ' { port: 22019, model: "", cellLabel: "run_tts.sh xtts" }] }] });',
     '[22014, 22019].map((port) => m.topologyRouterOutputLabel({ upstreamType: "llama", upstreamHost: "10.0.0.9", upstreamPort: port, label: `x :${port}` }))',
     '["moonshine en :22014","run_tts.sh xtts :22019"]',
     "defect-history (2026-10-04): ячейка moonshine читалась «en :22014» — label выхода сервер печёт из файла модели; "
     "теперь — собственная фраза ячейки (cell_artifact_label), что она запускает"),
    ("output_label_local_without_server_uses_label",
     '',
     'm.topologyRouterOutputLabel({ upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22001, label: "raw.gguf" })',
     '"raw.gguf :22001"',
     "negative: ячейки на этом порту доска не знает — остаётся label выхода, за ним порт"),
    ("output_label_local_without_anything_is_host_port",
     '',
     'm.topologyRouterOutputLabel({ upstreamHost: "10.0.0.5", upstreamPort: 22009 })',
     '"10.0.0.5:22009"',
     "negative: ни сервера, ни label — host:port, чтобы выход всё равно можно было опознать"),
    # ── an output's liveness ──
    ("output_activity_local_active_by_upstream",
     'st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", upstream: "127.0.0.1:22001", upstreamType: "llama" }] });',
     'm.topologyOutputActivity({ upstreamHost: "127.0.0.1", upstreamPort: 22001 }).state',
     '"active"',
     "локальный выход жив, когда активный запрос идёт ИМЕННО на его host:port"),
    ("output_activity_other_port_is_idle",
     'st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", upstream: "127.0.0.1:22002", upstreamType: "llama" }] });',
     'm.topologyOutputActivity({ upstreamHost: "127.0.0.1", upstreamPort: 22001 }).state',
     '"idle"',
     "negative: запрос на соседний порт этот выход не оживляет — иначе анимировались бы все кабели"),
    ("output_activity_queued_does_not_count",
     'st.ui.latestSystemMonitor = MON({ active: [{ phase: "queued", upstream: "127.0.0.1:22001", upstreamType: "llama" }] });',
     'm.topologyOutputActivity({ upstreamHost: "127.0.0.1", upstreamPort: 22001 }).state',
     '"idle"',
     "boundary: запрос в ОЧЕРЕДИ ещё не обслуживается этим выходом"),
    ("output_activity_cloud_by_provider_id",
     'st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", upstream: "127.0.0.1:8080", upstreamType: "cloud", providerId: "gpt-5-6-terra" }] });',
     '[m.topologyOutputActivity({ upstreamType: "cloud", providerId: "gpt-5-6-terra" }).state, m.topologyOutputActivity({ upstreamType: "cloud", providerId: "gpt-5-6-luna" }).state]',
     '["active","idle"]',
     "облачные выходы делят один host:port — совпадение по providerId, и соседний блок не оживает"),
    ("output_activity_engine_by_routed_output",
     'st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", upstream: "10.0.0.5:11434", upstreamType: "engine", routedOutputId: "eng:a" }] });',
     '[m.topologyOutputActivity({ id: "eng:a", upstreamType: "engine", upstreamHost: "10.0.0.5", upstreamPort: 11434 }).state, m.topologyOutputActivity({ id: "eng:b", upstreamType: "engine", upstreamHost: "10.0.0.5", upstreamPort: 11434 }).state]',
     '["active","idle"]',
     "модели одного движка делят его host:port — совпадение по выходу, куда запрос направлен, и соседняя модель не оживает"),
    # 2026-10-11: a pool also serves the entry's free clients directly, their requests carrying the
    # pool's id — a kanban's output to that pool lights only for the requests its own ports brought.
    ("output_activity_counts_its_kanbans_ports_only",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001 }, { id: "skynet:proxy:23050", port: 23050, kind: "consumer" }] });'
     ' st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", upstreamType: "cloud", providerId: "terra" }] }, 23050);',
     '(() => { const out = { upstreamType: "cloud", providerId: "terra" };'
     ' return [m.topologyOutputActivity(out, ROUTER({ inputs: ["skynet:proxy:23001"] })).state,'
     ' m.topologyOutputActivity(out, ROUTER({ inputs: ["skynet:proxy:23050"] })).state, m.topologyOutputActivity(out).state]; })()',
     '["idle","active","active"]',
     "выход канбана к пулу горит только от запросов его портов: запрос свободного клиента шёл мимо канбана — кабель тих; "
     "positive: тот же запрос от порта этого канбана — горит (порт записи — из строки монитора); без канбана — по-старому, любой запрос"),
    # 1.3.506: the models of a machine's entry share its scout's host:port, as an engine's do.
    ("output_activity_machine_model_by_routed_output",
     'st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", upstream: "10.0.0.5:8092/gemma", upstreamType: "machine", routedOutputId: "mm:a" }] });',
     '(() => { const mm = (id, model) => ({ id, upstreamType: "machine", upstreamHost: "10.0.0.5", upstreamPort: 8092, upstreamModel: model });'
     ' return [m.topologyOutputActivity(mm("mm:a", "gemma")).state, m.topologyOutputActivity(mm("mm:b", "ear")).state,'
     ' m.topologyRouterOutputLabel({ ...mm("mm:a", "gemma"), label: "gemma" }), m.topologyRouterOutputLabel({ upstreamType: "machine", label: "x" })]; })()',
     '["active","idle","gemma","x"]',
     "модели входа машины делят адрес скаута — совпадение по имени очереди модели («адрес:порт/модель»), соседняя "
     "модель не оживает; подпись — имя модели, без порта входа: он у всех моделей машины один"),
    ("output_label_engine",
     '',
     '[m.topologyRouterOutputLabel({ upstreamType: "engine", label: "qwen3:8b · Ollama", upstreamPort: 11434 }), m.topologyRouterOutputLabel({ upstreamType: "engine", upstreamModel: "qwen3:8b", engine: "ollama", upstreamPort: 11434 })]',
     '["qwen3:8b · Ollama","qwen3:8b · ollama"]',
     "выход модели движка подписан моделью и движком — ячейки на порту движка нет, host:port ничего не сказал бы"),
    ("output_activity_recent_within_8s",
     'st.ui.latestSystemMonitor = MON({ recent: [{ upstream: "127.0.0.1:22001", upstreamType: "llama", finishedAt: 1700000098 }] });',
     'm.topologyOutputActivity({ upstreamHost: "127.0.0.1", upstreamPort: 22001 }).state',
     '"recent"',
     "positive: завершился 2 секунды назад — «recent» (Date.now заморожен)"),
    ("output_activity_old_recent_is_idle",
     'st.ui.latestSystemMonitor = MON({ recent: [{ upstream: "127.0.0.1:22001", upstreamType: "llama", finishedAt: 1700000080 }] });',
     'm.topologyOutputActivity({ upstreamHost: "127.0.0.1", upstreamPort: 22001 }).state',
     '"idle"',
     "boundary: завершился 20 секунд назад — уже idle, окно «recent» 8 секунд"),
    ("output_activity_no_monitor_is_idle",
     'st.ui.latestSystemMonitor = null;',
     'm.topologyOutputActivity({ upstreamHost: "127.0.0.1", upstreamPort: 22001 })',
     '{"state":"idle","title":""}',
     "negative: монитора нет — idle без исключения"),
    # ── saveRouters: three trails ──
    ("save_posts_the_mutated_copy",
     'st.setTopology({ ...st.topology, routers: [ROUTER()] });'
     ' globalThis.__fetchReply["/api/agent-proxies/routers"] = { ok: true };',
     'await (async () => { await m.saveRouters((rs) => { rs[0].rules.default = "srv:22001"; }); const c = calls(); return [c.length, c[0].path, c[0].method, JSON.parse(c[0].body).routers[0].rules.default]; })()',
     '[1,"/api/agent-proxies/routers","POST","srv:22001"]',
     "на провод уходит ОДИН POST с изменённым списком роутеров"),
    ("save_mutates_a_copy_not_the_state",
     'st.setTopology({ ...st.topology, routers: [ROUTER()] });'
     ' globalThis.__fetchReply["/api/agent-proxies/routers"] = { ok: true };',
     'await (async () => { await m.saveRouters((rs) => { rs[0].rules.default = "srv:22001"; }); return st.topology.routers[0].rules.default; })()',
     '"cb:terra"',
     "defect-class: мутатор получает КОПИЮ — состояние доски меняет только ответ сервера, иначе отказ записи оставлял бы на экране то, чего нет в файле"),
    ("save_applies_the_servers_topology",
     'st.setTopology({ ...st.topology, routers: [ROUTER()] });'
     ' globalThis.__fetchReply["/api/agent-proxies/routers"] = { ok: true, topology: { proxies: [], clients: [], assignments: {}, routers: [ROUTER({ name: "from-server" })] } };',
     'await (async () => { await m.saveRouters(() => {}); return st.topology.routers[0].name; })()',
     '"from-server"',
     "positive: ответ сервера с topology становится состоянием доски"),
    ("save_without_topology_keeps_state",
     'st.setTopology({ ...st.topology, routers: [ROUTER()] });'
     ' globalThis.__fetchReply["/api/agent-proxies/routers"] = { ok: true };',
     'await (async () => { await m.saveRouters(() => {}); return st.topology.routers[0].name; })()',
     '"default"',
     "negative: ответ без topology состояние не трогает"),
    ("save_failure_releases_the_saving_flag",
     'st.setTopology({ ...st.topology, routers: [ROUTER()] });'
     ' globalThis.__fetchReply["/api/agent-proxies/routers"] = { __status: 500, error: "disk full" };',
     'await (async () => { let err = ""; try { await m.saveRouters(() => {}); } catch (e) { err = String(e.message || e); } return [err, m._routersSaving]; })()',
     '["disk full",0]',
     "отказ сервера ДОХОДИТ до вызывающего, а флаг «сохраняется» снимается — иначе муравьиная дорожка бежала бы вечно"),
    # ── saveRouters and an old copy (ProxyRevisions on the controller, 2026-10-08) ──
    ("save_sends_the_version_it_was_built_from",
     'st.setTopology({ ...st.topology, routers: [ROUTER()], proxyRevisions: { routes: "p1", routers: "r1" } });'
     ' globalThis.__fetchReply["/api/agent-proxies/routers"] = { ok: true };',
     'await (async () => { await m.saveRouters(() => {}); return JSON.parse(calls()[0].body).revision; })()',
     '"r1"',
     "запись несёт версию роутеров, из которой собрана: по ней контроллер узнаёт старую копию"),
    ("save_without_a_version_sends_none",
     'st.setTopology({ ...st.topology, routers: [ROUTER()] });'
     ' globalThis.__fetchReply["/api/agent-proxies/routers"] = { ok: true };',
     'await (async () => { await m.saveRouters(() => {}); return JSON.parse(calls()[0].body).revision; })()',
     '""',
     "negative: топология без версий (старый контроллер) — пустая версия, контроллер её не проверяет"),
    ("save_from_an_old_copy_is_made_again_on_the_current",
     'st.setTopology({ ...st.topology, routers: [ROUTER()], proxyRevisions: { routes: "p1", routers: "r1" } });'
     ' let n = 0; globalThis.__fetchReply["/api/agent-proxies/routers"] = () => (++n === 1 ? { __status: 409, stale: true, error: "the routers changed since this page read them", topology: { proxies: [], clients: [], assignments: {}, routers: [ROUTER({ name: "fresh" })], proxyRevisions: { routes: "p2", routers: "r2" } } } : { ok: true });',
     'await (async () => { await m.saveRouters((rs) => { rs[0].rules.default = "srv:22001"; }); const c = calls().map((x) => JSON.parse(x.body));'
     ' return [c.length, c[1].revision, c[1].routers[0].name, c[1].routers[0].rules.default, toastText() === en.staleCopyRetried, m._routersSaving]; })()',
     '[2,"r2","fresh","srv:22001",true,0]',
     "отказ «старая копия»: то же изменение сделано ещё раз на текущей топологии из ответа, с её версией, и тост это говорит"),
    ("save_refused_twice_reaches_the_caller",
     'st.setTopology({ ...st.topology, routers: [ROUTER()], proxyRevisions: { routes: "p1", routers: "r1" } });'
     ' globalThis.__fetchReply["/api/agent-proxies/routers"] = { __status: 409, stale: true, error: "the routers changed since this page read them", topology: { proxies: [], clients: [], assignments: {}, routers: [ROUTER({ name: "fresh" })], proxyRevisions: { routes: "p2", routers: "r2" } } };',
     'await (async () => { let err = ""; try { await m.saveRouters(() => {}); } catch (e) { err = e.message; } return [calls().length, err, m._routersSaving]; })()',
     '[2,"the routers changed since this page read them",0]',
     "negative: второй отказ — ошибка вызывающему, третьей попытки нет, флаг «сохраняется» снят"),
    ("save_other_409_is_not_retried",
     'st.setTopology({ ...st.topology, routers: [ROUTER()], proxyRevisions: { routes: "p1", routers: "r1" } });'
     ' globalThis.__fetchReply["/api/agent-proxies/routers"] = { __status: 409, error: "Local model srv:22001 has multiple queue policies" };',
     'await (async () => { let err = ""; try { await m.saveRouters(() => {}); } catch (e) { err = e.message; } return [calls().length, err]; })()',
     '[1,"Local model srv:22001 has multiple queue policies"]',
     "negative: другой отказ 409 (две политики очереди) не повторяется — повторять имеет смысл только запись со старой копии"),
    ("save_nested_flag_counts",
     '',
     '(() => { m._setRoutersSaving(true); m._setRoutersSaving(true); const two = m._routersSaving; m._setRoutersSaving(false); const one = m._routersSaving; m._setRoutersSaving(false); m._setRoutersSaving(false); return [two, one, m._routersSaving]; })()',
     '[2,1,0]',
     "boundary: две записи подряд считаются, а лишнее снятие не уводит счётчик в минус"),
    # ── the kanban's card on the main board (2026-10-12: the pools stand on the kanban) ──
    ("card_counts_the_clients_and_the_pools",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER({ inputs: ["a", "b", "c"] })], proxies: ['
     ' { id: "ctl:proxy:23001", port: 23001, kind: "consumer", label: "Hermes", set: "main" }, { id: "ctl:proxy:23002", port: 23002, kind: "consumer", label: "Bot", set: "", pool: "terra" },'
     ' { id: "ctl:proxy:23003", port: 23003, kind: "consumer", label: "Zed", set: "cheap" },'
     ' { id: "ctl:proxy:23050", port: 23050, label: "old agent" }] });',
     '(h => [h.includes(`${en.topologyClientsSection} 2/3 · ${en.topologyLlamaServersSection} ${st.topology.pools.length}`),'
     ' st.topology.pools.some((p) => h.includes(`data-t-id="${p.id}"`) || h.includes(String(p.name || p.id))), ["router-pool-name", "board-kanban-pool", "router-outputs"].some((x) => h.includes(x)),'
     ' h.includes(\'data-t="board-kanban-card"\'), h.includes(`title="${en.rtTitleOpenKanban}"`), h.includes("data-topology-router-input"), h.includes("data-topology-router-output"), h.includes(" out ")])'
     '(m.renderTopologyRouterCard(st.topology.routers[0]))',
     '[true,false,false,true,true,true,true,false]',
     "карточка канбана маленькая (владелец, 2026-10-13: «без перечисления всего внутри»): имя и две цифры — клиенты с набором из всех клиентов и число пулов; "
     "щелчок открывает канбан; вход для канатов клиентов и выход к машинам и провайдерам, которых ведут пулы (владелец, 2026-10-12); "
     "negative: имён пулов на ней нет, ни чипов, ни списка; счётчиков графа (in · out) нет; старое поле pool клиента не считается (1.3.497)"),
    ("card_without_pools_says_zero",
     'st.setTopology({ ...st.topology, pools: [], routers: [ROUTER()] });',
     '(h => [h.includes(`${en.topologyLlamaServersSection} 0`), h.includes("router-output-row"), h.includes(en.rtNoPools), h.includes("router-pool-name")])(m.renderTopologyRouterCard(st.topology.routers[0]))',
     '[true,false,false,false]',
     "пулов нет — карточка так и говорит цифрой «0»; negative: ни строки «пулов нет», ни имён, ни пустого списка"),
    ("board_page_links",
     '',
     '(h => [(h.match(/<a [^>]*>/g) || []).map((a) => [(a.match(/href="([^"]*)"/) || [])[1], (a.match(/data-t="([^"]*)"/) || [])[1], a.includes(\'target="_blank"\') && a.includes(\'rel="noopener"\')]),'
     ' h.includes(`title="${en.modelsPageSub}"`), h.includes(`title="${en.hfBrowserTitle}"`), h.includes(`${en.topologyModelsLabel}</span>`), h.includes("Hugging Face</span>"),'
     ' h.includes(\'data-t="board-pages"\')])(m.renderBoardPageLinks())',
     '[[["/models","board-models-open",true],["/hf","board-hf-open",true]],true,true,true,true,true]',
     "под карточкой канбана — две страницы каравана: «Models» (модели в его папке) и «Hugging Face» (скачать ещё); каждая открывается в новой вкладке, "
     "с подсказкой и словом на языке страницы (владелец, 2026-10-14: «переместить эти две кнопки в более подходящее место»)"),
    ("card_lights_with_a_client",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()], proxies: [{ id: "ctl:proxy:23001", port: 23001, kind: "consumer", label: "Hermes", set: "main" },'
     ' { id: "ctl:proxy:23002", port: 23002, kind: "consumer", label: "Bot", set: "" }] });'
     ' st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", port: 23001 }] });',
     '(() => { const lit = m.renderTopologyRouterCard(st.topology.routers[0]).includes("activity-active");'
     ' st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", port: 23002 }] }, 23002);'
     ' return [lit, m.renderTopologyRouterCard(st.topology.routers[0]).includes("activity-active")]; })()',
     '[true,false]',
     "карточка горит, пока идёт запрос клиента с набором; negative: запрос клиента без набора её не зажигает — к ней его канат не ведёт"),
    ("card_is_red_while_a_clients_failure_is_in_the_window",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()], proxies: [{ id: "ctl:proxy:23001", port: 23001, kind: "consumer", label: "Hermes", set: "main" }] }); st.ui.latestSystemMonitor = MON({ recent: [{ status: "500", startedAt: 1699999000, finishedAt: 1699999501, durationMs: 1000 }] });',
     '(h => [h.includes("activity-error"), h.includes("health-failed")])(m.renderTopologyRouterCard(st.topology.routers[0]))',
     '[true,true]',
     "карточка канбана красная, пока отказ клиента с набором (599 с назад) в окне монитора"),
    ("card_is_calm_after_the_alarm_is_over",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()], proxies: [{ id: "ctl:proxy:23001", port: 23001, kind: "consumer", label: "Hermes", set: "main" }] }); st.ui.latestSystemMonitor = MON({ recent: [{ status: "500", startedAt: 1699999000, finishedAt: 1699999499, durationMs: 1000 }] });',
     '(h => [h.includes("activity-error"), h.includes("health-failed"), h.includes("activity-recent health-ok")])(m.renderTopologyRouterCard(st.topology.routers[0]))',
     '[false,false,true]',
     "тот же отказ 601 с назад — карточка канбана не красная: activity-recent health-ok, как после любого старого запроса"),
    # ── the router's outputs: the Servers block on the kanban ──
    ("panel_one_radio_per_output_default_checked",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()] });',
     '(h => [(h.match(/class="router-out-radio"/g) || []).length, (h.match(/data-router-set-default="router:default"[^>]*>/g) || []).length, /data-router-set-default="router:default" data-router-out="cb:terra"[^>]*checked|checked data-router-set-default="router:default" data-router-out="cb:terra"/.test(h) || /is-default[^>]*data-router-out-row="cb:terra"/.test(h)])(m.renderServersBlockHtml(st.topology.routers[0]))',
     '[2,2,true]',
     "по радиокнопке на выход, и отмечен ровно default"),
    ("panel_pool_row_says_its_steps",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()] });',
     '(h => [(h.match(/data-router-out-row="cb:terra"/g) || []).length, (h.match(/class="router-out-steps" title="([^"]*)">([^<]*)</) || []).slice(1), h.includes("router-out-unlisted-warn"), groupOrder(h)])(m.renderServersBlockHtml(st.topology.routers[0]))',
     '[1,["1. OpenAI (ChatGPT Plus) · gpt-5.6-terra\\n2. OpenRouter · vendor/terra","steps: 2"],false,["srv:22001","cb:terra"]]',
     "пул — одна строка-выход в своей группе: сколько шагов, а в подсказке — шаги по порядку «аккаунт · модель»; здоровый пул — без ⚠"),
    ("pool_row_marks_what_cannot_serve",
     '',
     '(() => { const warn = (pool) => { st.setTopology({ ...st.topology, ...CLOUD(pool), routers: [ROUTER()] }); return (m.renderServersBlockHtml(st.topology.routers[0]).match(/router-out-unlisted-warn" title="([^"]*)"/) || [null, null])[1]; };'
     ' return [warn({ steps: [STEP("s1", "or", "m", { enabled: false })] }) === en.rtPoolNoStep, warn({ steps: [] }) === en.rtPoolNoStep,'
     ' warn({ steps: [STEP("s1", "or", "m", { unlisted: true }), STEP("s2", "or", "n")] }) === en.cloudModelUnlisted, warn({ steps: [STEP("s1", "or", "m", { unlisted: true, enabled: false }), STEP("s2", "or", "n")] })]; })()',
     '[true,true,true,null]',
     "⚠ на строке пула: ни одного включённого шага (или шагов нет) — запросы получат отказ; модель включённого шага провайдер больше не отдаёт; negative: такая модель только у выключенного шага — тихо"),
    ("pool_row_shows_no_port_of_its_own",
     '',
     '(() => { const ports = (list) => { st.setTopology({ ...st.topology, ...CLOUD({ ports: list }), routers: [ROUTER()] }); return [...m.renderServersBlockHtml(st.topology.routers[0]).matchAll(/router-out-port">([^<]*)</g)].map((x) => x[1]); };'
     ' return [ports([23004, 23011]), ports([])]; })()',
     '[[],[]]',
     "у пула нет своего порта (владелец, 2026-10-12): номер на строке пула не рисуется, даже если старые данные его несут"),
    ("kanban_output_without_a_known_pool_keeps_its_row",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER({ outputs: [...ROUTER().outputs, { id: "cb:ghost", label: "☁ ghost", upstreamType: "cloud", providerId: "ghost" }] })] });',
     '(h => [groupOrder(h), h.includes(\'data-router-out-row="cb:ghost"\'), (h.match(/router-out-steps/g) || []).length])(m.renderServersBlockHtml(st.topology.routers[0]))',
     '[["srv:22001","cb:terra","cb:ghost"],true,1]',
     "выход, чей пул страница не знает, остаётся строкой после известных — канат к нему не теряет конца; шагов у него не придумано"),
    ("panel_without_cloud_says_so",
     'st.setTopology({ ...st.topology, routers: [ROUTER({ outputs: [] })] });',
     '(h => [h.includes("router-cfg-muted"), (h.match(/router-out-radio/g) || []).length])(m.renderServersBlockHtml(st.topology.routers[0]))',
     '[true,0]',
     "negative: ни серверов, ни облака — приглушённые подписи и ни одной радиокнопки"),
    # ── rewiring a proxy ──
    ("rebind_posts_route_policy",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, routerId: "router:default" }] });'
     ' globalThis.__fetchReply["/api/agent-proxies/route-policy"] = { ok: true };',
     'await (async () => { await m.rebindProxyRouter("skynet:proxy:23001", "router:b"); const c = calls(); return [c.length, c[0]?.path, c[0] && JSON.parse(c[0].body), toastText()]; })()',
     '[1,"/api/agent-proxies/route-policy",{"port":23001,"routerId":"router:b"},"proxy re-bound"]',
     "перецепка шлёт порт и новый роутер, и оператору сказано об этом"),
    ("rebind_same_router_or_unknown_proxy_sends_nothing",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, routerId: "router:default" }] });',
     'await (async () => { await m.rebindProxyRouter("skynet:proxy:23001", "router:default"); await m.rebindProxyRouter("skynet:proxy:29999", "router:b"); await m.rebindProxyRouter("skynet:proxy:23001", ""); return calls().length; })()',
     '0',
     "negative: тот же роутер, неизвестный прокси, пустой роутер — ни одного запроса"),
    # ── the machines behind the local outputs (one grouping, one name source) ──
    ('local_groups_by_machine',
     '',
     'm.localOutputGroups([{ id: "srv:22003", upstreamHost: "10.0.0.9", upstreamPort: 22003 }, { id: "srv:22001", upstreamHost: "127.0.0.1", upstreamPort: 22001 }, { id: "srv:22002", upstreamHost: "10.0.0.5", upstreamPort: 22002 }, { id: "cb:x", upstreamHost: "127.0.0.1", upstreamPort: 8080, upstreamType: "cloud" }, { id: "srv:22009", upstreamHost: "10.9.9.9", upstreamPort: 22009 }]).map((g) => [g.key, g.name, g.outs.map((o) => o.id)])',
     '[["m-ctl","ctl-box",["srv:22001","srv:22002"]],["m-b","box-b",["srv:22003"]],["10.9.9.9","10.9.9.9",["srv:22009"]]]',
     'positive: выходы — по машине (machineAt): петля и адрес сети одной машины — одна группа с её именем; облако не входит; незнакомый адрес — сам адрес; группы по наименьшему порту, выходы по порту'),
    ('servers_block_names_machines_not_the_controller',
     'st.setTopology({ ...st.topology, server: { name: "Ctl-Display", ip: "10.0.0.5" }, routers: [ROUTER({ outputs: [{ id: "srv:22001", label: "a", upstreamHost: "127.0.0.1", upstreamPort: 22001, upstreamType: "llama" }, { id: "srv:22003", label: "b", upstreamHost: "10.0.0.9", upstreamPort: 22003, upstreamType: "llama" }] })] });',
     '(h => [heads(h), h.includes("Ctl-Display"), /data-router-group-fold="host:m-ctl"/.test(h)])(m.renderServersBlockHtml(st.topology.routers[0]))',
     '[[["ctl-box","10.0.0.5"],["box-b","10.0.0.9"]],false,true]',
     'positive: блок серверов канбана подписывает группы именем машины и её адресом рядом; negative: старое имя контроллера (topology.server.name) не пишется нигде; свёртка группы — по машине'),
    ('machine_label_once_when_the_address_is_the_name',
     '',
     '[m.machineLabelHtml({ name: "box-b", address: "10.0.0.9" }), m.machineLabelHtml({ name: "10.9.9.9", address: "10.9.9.9" }), m.machineLabelHtml({ name: "box-x", address: "" })]',
     '["box-b <span class=\\"router-out-host-addr\\">10.0.0.9</span>","10.9.9.9","box-x"]',
     'positive: имя и адрес рядом; negative: незнакомая машина — адрес один раз, без повтора; адреса нет — только имя'),

]


PINS += [
    # 2026-10-04: Model servers is one list of machines and cloud providers in the operator's
    # order (server-order.js), and the kanban's Servers panel follows it: a group stands where its
    # card stands on the board, a pool's member beside its pool. The order is module state —
    # the pin sets it and leaves it empty.
    ("kanban_groups_follow_the_board_order",
     'globalThis.__so = (await import(pathToFileURL(process.env.JS_ROOT + "/server-order.js").href)).SERVER_ORDER;'
     ' st.setTopology({ ...st.topology, cloudAccounts: [{ id: "or", type: "openrouter", name: "OpenRouter" }],'
     ' pools: [{ id: "solo", name: "Router", steps: [STEP("s", "or", "m")] }, { id: "pp", name: "Pool", steps: [STEP("s", "or", "n")] }],'
     ' routers: [ROUTER({ outputs: [{ id: "srv:22003", label: "b", upstreamHost: "10.0.0.9", upstreamPort: 22003, upstreamType: "llama" },'
     ' { id: "srv:22001", label: "a", upstreamHost: "127.0.0.1", upstreamPort: 22001, upstreamType: "llama" },'
     ' { id: "cb:pp", label: "☁ Pool", upstreamType: "cloud", providerId: "pp" }, { id: "cb:solo", label: "☁ Router", upstreamType: "cloud", providerId: "solo" }] })] });',
     '(() => { const so = globalThis.__so;'
     ' try { const h0 = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' so.held = { order: ["cloud:pp", "node:m-b", "cloud:solo", "node:m-ctl"], rev: 1 }; const h1 = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' so.held = { order: ["node:m-b"], rev: 2 }; const h2 = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' return [groupOrder(h0), groupOrder(h1), groupOrder(h2), [h0, h1].some((h) => h.includes("router-out-sec-h")), (h1.match(/class="router-out-sec"/g) || []).length]; }'
     ' finally { so.held = { order: [], rev: -1 }; } })()',
     '[["srv:22001","srv:22003","cb:solo","cb:pp"],["cb:pp","srv:22003","cb:solo","srv:22001"],["srv:22003","srv:22001","cb:solo","cb:pp"],false,1]',
     "группы панели «Серверы» идут в порядке доски: ничего не сохранено — машины (по наименьшему порту), затем пулы в порядке "
     "контроллера; сохранено — вперемешку, как карточки; не названные — после названных, в прежнем порядке; заголовков «Local» и «Cloud» нет — один список"),
    ("kanban_says_which_kind_it_has_none_of",
     '',
     '(() => { const run = (outputs, pools) => { st.setTopology({ ...st.topology, cloudAccounts: [], pools, routers: [ROUTER({ outputs })] });'
     ' const h = m.renderServersBlockHtml(st.topology.routers[0]); return [h.includes(en.rtNoLocalServers), h.includes(en.rtNoPools)]; };'
     ' const local = [{ id: "srv:22001", label: "a", upstreamHost: "127.0.0.1", upstreamPort: 22001, upstreamType: "llama" }];'
     ' const pool = [{ id: "solo", label: "☁ Router", upstreamType: "cloud", providerId: "solo" }];'
     ' return [run([], []), run(local, []), run(pool, [{ id: "solo", name: "Router", steps: [] }]), run([...local, ...pool], [{ id: "solo", name: "Router", steps: [] }])]; })()',
     '[[true,true],[false,true],[true,false],[false,false]]',
     "пусто по своему виду — своя строка после списка: нет машин — «no local servers», нет пулов — «no pools»; negative: есть и то и другое — ни одной"),
    ("model_queue_below_its_local_row_only", 'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()] });', '(() => { const h = m.renderServersBlockHtml(st.topology.routers[0], { "srv:22001": "LOCAL-QUEUE", "cb:terra": "CLOUD-QUEUE" }); return [h.indexOf("LOCAL-QUEUE") > h.indexOf(\'data-router-out-row="srv:22001"\'), h.indexOf("LOCAL-QUEUE") < h.indexOf(\'data-router-out-row="cb:terra"\'), h.includes("CLOUD-QUEUE")]; })()',
     '[true,true,false]', "очередь стоит после строки своей локальной модели и до следующей модели; облако без автоматической очереди"),
    ("model_queue_folds_with_host", 'st.setTopology({ ...st.topology, routers: [ROUTER()] }); m.topologyOutputsFolded["host:m-ctl"] = true;', '(() => { try { return m.renderServersBlockHtml(st.topology.routers[0], { "srv:22001": "LOCAL-QUEUE" }).includes("LOCAL-QUEUE"); } finally { delete m.topologyOutputsFolded["host:m-ctl"]; } })()',
     'false', "свёрнутая группа скрывает модели и их очереди вместе"),
    ("router_detail_toolbar_has_no_queue_settings", 'st.setTopology({ ...st.topology, routers: [ROUTER()] }); st.ui.topologyRouterDetailId = "router:default";',
     '(() => { const h = m.renderTopologyRouterDetail(); const at = (k) => h.indexOf(k); return [typeof h, h.includes("rw-palette"), h.includes("kanban-palette-add"), h.includes("data-cv-queue-settings"), h.includes("cv-queue-settings"), h.includes("data-cv-cols"), h.includes("<aside>CLIENTS</aside>") && h.includes("<aside>SERVERS</aside>") && at("<aside>CLIENTS</aside>") < at("rw-center") && at("rw-center") < at("<aside>SERVERS</aside>"), at("<aside>SERVERS</aside>") > at("data-cv-viewport")]; })()',
     '["string",true,true,false,false,true,true,true]', "рабочее поле: панель клиентов слева, холст с палитрой посередине, панель серверов справа, внутри одной сетки; в панели инструментов нет строки политики очередей — она живёт в панели серверов, одна на доску"),
    # 2026-10-04: "4 unassigned" on the live kanban counted four cloud models' own ports — outputs
    # that never fed a router (those ports are gone since 1.3.487). The badge counts only ports
    # that can feed one, and opens their list by name, both heads alike.
    ("kanban_unassigned_counts_only_ports_that_feed_routers",
     'st.setTopology({ ...st.topology, routers: [ROUTER(), { ...ROUTER(), id: "router:b", name: "second" }], proxies: ['
     ' { id: "ctl:proxy:23010", port: 23010, routerId: "", label: "alpha" },'
     ' { id: "ctl:proxy:23011", port: 23011, routerId: "router:b", label: "beta" },'
     ' { id: "ctl:proxy:23001", port: 23001, routerId: "router:default", label: "mine" }] });'
     ' st.ui.topologyRouterDetailId = "router:default";',
     '(() => { const read = (h) => [(h.match(/class="rw-unassigned-badge"[^>]*>([^<]*)</) || [])[1] || "",'
     ' [...h.matchAll(/data-router-attach="([^"]*)"/g)].map((x) => x[1]), [...h.matchAll(/router-pill-name">([^<]*)</g)].map((x) => x[1])];'
     ' const overlay = read(m.renderTopologyRouterDetail()); window.ROUTER_STANDALONE = true;'
     ' try { return [overlay, read(m.renderTopologyRouterDetail()), fill(en.rtUnassigned, { n: 2 })]; } finally { delete window.ROUTER_STANDALONE; } })()',
     '[["2 unassigned",["ctl:proxy:23010","ctl:proxy:23011"],["alpha","beta"]],["2 unassigned",["ctl:proxy:23010","ctl:proxy:23011"],["alpha","beta"]],"2 unassigned"]',
     "значок считает только порты, которые могут кормить канбан: свободный и на другом канбане; список называет "
     "порты по имени; обе шапки одинаковы"),
    # 2026-10-04: a row says its cell's state — on the live kanban 24 of 30 rows were stopped and
    # drew the same grey "idle" dot as the running six; a stopped cell's dot is a ring now, and
    # the word stands at the row's end.
    ("kanban_row_says_the_cells_state",
     'st.setTopology({ ...st.topology, nodes: [{ id: "m-ctl", servers: [{ port: 22001, phase: "running", model: "a.gguf" },'
     ' { port: 22002, phase: "stopped", model: "b.gguf" }, { port: 22003, phase: "broken", model: "c.gguf" }] }],'
     ' routers: [ROUTER({ outputs: [22001, 22002, 22003, 22005].map((p) => ({ id: `srv:${p}`, label: `x :${p}`, upstreamHost: "127.0.0.1", upstreamPort: p, upstreamType: "llama" })) })] });',
     '(() => { const h = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' const row = (id) => { const i = h.indexOf(`data-router-out-row="${id}"`); return h.slice(h.lastIndexOf("<label", i), h.indexOf("</label>", i)); };'
     ' const read = (r) => [(r.match(/class="router-out-row[^"]*? cell-(\\w+)/) || [])[1] || "", (r.match(/router-out-live (live-\\w+)/) || [])[1] || "",'
     ' (r.match(/data-t="kanban-out-state"[^>]*>([^<]*)</) || [])[1] || "", r.includes("router-out-marks")];'
     ' return [["srv:22001", "srv:22002", "srv:22003", "srv:22005"].map((id) => read(row(id))), [en.stopped, en.failed, en.unknown]]; })()',
     '[[["","live-idle","",true],["stopped","live-off","stopped",true],["failed","live-off","failed",true],["unknown","live-off","unknown",false]],["stopped","failed","unknown"]]',
     "строка говорит состояние ячейки: работающая — точка трафика, без слова; остановленная, отказавшая и неизвестная — "
     "кольцо и слово в конце строки; значки работ — у тех, чью ячейку доска знает; negative: ячейки нет — «unknown», не idle"),
    # 2026-10-11: an output's dot on the kanban counts only the requests this kanban's ports brought —
    # another kanban's port reaching the same cell is that kanban's traffic.
    ("kanban_row_lights_only_for_its_own_ports",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, routerId: "router:default" },'
     ' { id: "skynet:proxy:23050", port: 23050, routerId: "router:b" }], nodes: [{ id: "m-ctl", servers: [{ port: 22001, phase: "running", model: "a.gguf" }] }],'
     ' routers: [ROUTER({ inputs: ["skynet:proxy:23001"], outputs: [{ id: "srv:22001", label: "x :22001", upstreamHost: "127.0.0.1", upstreamPort: 22001, upstreamType: "llama" }] })] });',
     '(() => { const dot = (port) => { st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", upstream: "127.0.0.1:22001", upstreamType: "llama" }] }, port);'
     ' return (m.renderServersBlockHtml(st.topology.routers[0]).match(/router-out-live (live-\\w+)/) || [])[1] || ""; }; return [dot(23050), dot(23001)]; })()',
     '["live-idle","live-active"]',
     "точка выхода на канбане горит только от запросов портов этого канбана; negative: порт другого канбана идёт в ту же "
     "ячейку — здесь точка тиха"),
    ("kanban_quiet_cells_fold_under_one_row",
     'st.setTopology({ ...st.topology, nodes: [{ id: "m-ctl", servers: [{ port: 22001, phase: "running", model: "a.gguf" },'
     ' { port: 22002, phase: "stopped", model: "b.gguf" }, { port: 22003, phase: "stopped", model: "c.gguf" }, { port: 22004, phase: "stopped", model: "d.gguf" }] }],'
     ' routers: [ROUTER({ outputs: [22001, 22002, 22003, 22004].map((p) => ({ id: `srv:${p}`, label: `x :${p}`, upstreamHost: "127.0.0.1", upstreamPort: p, upstreamType: "llama" })),'
     ' graph: { nodes: [], edges: [{ id: "e1", from: "in:a", to: "out:srv:22002" }], inputs: {} } })] });',
     '(() => { const rows = (h) => [...h.matchAll(/data-router-out-row="([^"]*)"/g)].map((x) => x[1]);'
     ' const quiet = (h) => [(h.match(/class="router-out-quiet( folded)?"[^>]*data-cv-group-outs="([^"]*)"/) || []).slice(1).map((x) => x || ""),'
     ' (h.match(/router-out-quiet-label">([^<]*)</) || [])[1] || ""];'
     ' const closed = m.renderServersBlockHtml(st.topology.routers[0]); m.topologyQuietShown["m-ctl"] = true;'
     ' try { const opened = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' return [rows(closed), quiet(closed), rows(opened), quiet(opened)[0], fill(en.rtQuietCells, { n: 2 })]; }'
     ' finally { delete m.topologyQuietShown["m-ctl"]; } })()',
     '[["srv:22001","srv:22002"],[[" folded","srv:22003,srv:22004"],"2 stopped, no cables"],["srv:22001","srv:22002","srv:22003","srv:22004"],["","srv:22003,srv:22004"],"2 stopped, no cables"]',
     "остановленные ячейки, к которым ничего не ведёт, — под одной строкой «2 stopped, no cables», свёрнуты по умолчанию; "
     "их выходы названы на строке (data-cv-group-outs); открыто — строки идут под ней; остановленная с канатом — на виду"),
    ("kanban_twin_rows_say_what_differs",
     'st.setTopology({ ...st.topology, nodes: [{ id: "m-ctl", servers: ['
     ' { port: 22006, phase: "running", model: "seamless-m4t-v2-large", slotConfig: { PORT: "22006", SEAMLESS_TGT_LANG: "eng" } },'
     ' { port: 22007, phase: "running", model: "seamless-m4t-v2-large", slotConfig: { PORT: "22007", SEAMLESS_TGT_LANG: "rus" } },'
     ' { port: 22003, phase: "running", model: "g.gguf", slotConfig: { PORT: "22003" } }, { port: 22004, phase: "running", model: "g.gguf", slotConfig: { PORT: "22004" } },'
     ' { port: 22010, phase: "running", model: "s.gguf", slotConfig: { PORT: "22010", API_KEY: "aaa" } }, { port: 22011, phase: "running", model: "s.gguf", slotConfig: { PORT: "22011", API_KEY: "bbb" } }] }],'
     ' routers: [ROUTER({ outputs: [22006, 22007, 22003, 22004, 22010, 22011].map((p) => ({ id: `srv:${p}`, label: `x :${p}`, upstreamHost: "127.0.0.1", upstreamPort: p, upstreamType: "llama" })) })] });',
     '(() => { const h = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' const notes = [...h.matchAll(/data-router-out-row="([^"]*)"[\\s\\S]*?router-out-twin" title="([^"]*)">([^<]*)</g)].map((x) => [x[1], x[3]]);'
     ' return [notes, /aaa|bbb/.test(h), h.includes(fill(en.rtTwinSame, { port: "22004" }))]; })()',
     '[[["srv:22003","= :22004"],["srv:22004","= :22003"],["srv:22006","SEAMLESS_TGT_LANG=eng"],["srv:22007","SEAMLESS_TGT_LANG=rus"],["srv:22010","API_KEY ≠"],["srv:22011","API_KEY ≠"]],false,true]',
     "две ячейки одной модели на машине: у каждой своё отличие («SEAMLESS_TGT_LANG=eng» и «=rus»), одинаковые — «= :порт "
     "копии» с подсказкой; секретная настройка — только именем: значений нет в разметке"),
    ("kanban_canvas_has_show_all",
     'st.setTopology({ ...st.topology, routers: [ROUTER()] }); st.ui.topologyRouterDetailId = "router:default";',
     '(h => { const at = (k) => h.indexOf(k); return [h.includes(\'data-cv-fit\'), at("data-cv-fit") > at("data-cv-viewport"), at("data-cv-fit") < at("<aside>SERVERS</aside>"), h.includes(en.cvFitAll)]; })(m.renderTopologyRouterDetail())',
     '[true,true,true,true]',
     "кнопка «⤢ Show all» стоит на самом холсте (в окне просмотра), а не в панелях"),
    ("kanban_cell_port_stands_apart_from_the_name",
     'st.setTopology({ ...st.topology, nodes: [{ id: "m-ctl", servers: [{ port: 22008, phase: "stopped", model: "/m/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf" }] }],'
     ' routers: [ROUTER({ outputs: [{ id: "srv:22008", label: "x :22008", upstreamHost: "127.0.0.1", upstreamPort: 22008, upstreamType: "llama" }, { id: "srv:22099", label: "", upstreamHost: "10.0.0.7", upstreamPort: 22099, upstreamType: "llama" }] })] });',
     '(() => { const h = m.renderServersBlockHtml(st.topology.routers[0]); const row = (id) => { const i = h.indexOf(`data-router-out-row="${id}"`); return h.slice(h.lastIndexOf("<label", i), h.indexOf("</label>", i)); };'
     ' const read = (r) => [(r.match(/router-out-name">(?:<span class="router-out-marks">[^<]*<\\/span> )?([^<]*)</) || [])[1], (r.match(/router-out-port cell-port">([^<]*)</) || [])[1]];'
     ' return [read(row("srv:22008")), read(row("srv:22099"))]; })()',
     '[["Qwen3-Coder-30B-A3B-Instruct",":22008"],["10.0.0.7",":22099"]]',
     "у строки ячейки порт — отдельно от имени: длинное имя уступает место слову состояния, порт — нет "
     "(«Qwen3-Coder-30B-A3B-Instruct :220…» не называл ячейку); negative: имени нет — адрес, порт всё равно отдельно"),
    # 2026-10-04: a rule node's place lived in two stores — the server's graph (every drag saves
    # there) and the browser's old `cvpos:` copy, which won on every open: the operator's drags
    # were saved and then undone by his own Chrome on reload. He chose the server; the copy is
    # dropped on open (canvas.js, openPositions), and the board's memory holds only a drop whose
    # save has not landed yet.
    ("kanban_rule_node_stands_where_the_server_has_it",
     'st.setTopology({ ...st.topology, routers: [ROUTER()] }); st.ui.topologyRouterDetailId = "router:default";'
     ' globalThis.__stubReturns["canvas.canvasNodes"] = () => [{ id: "rule:n1", type: "rule", fixed: { x: 368, y: 372 }, html: "N1" }];',
     '(() => { const place = () => (m.renderTopologyRouterDetail().match(/data-cv-node="rule:n1" style="([^"]*)"/) || [])[1];'
     ' try { const rest = place(); globalThis.__stubValues["canvas._cvPos"]["rule:n1"] = { x: 509, y: 359 }; return [rest, place()]; }'
     ' finally { delete globalThis.__stubValues["canvas._cvPos"]["rule:n1"]; globalThis.__stubReturns["canvas.canvasNodes"] = () => []; } })()',
     '["left:368px;top:372px","left:509px;top:359px"]',
     "узел правила стоит на месте с сервера; только бросок, чьё сохранение ещё не пришло, показан на месте броска, "
     "чтобы перерисовка в пути не дёрнула узел назад; третьего места нет"),
    # 2026-10-12: a client of the entry feeds no kanban — its one cable leads to a set of models — so the
    # kanban's list of ports that could feed it never names one.
    ("kanban_lists_no_client_of_the_entry",
     'st.setTopology({ ...st.topology, routers: [ROUTER()], proxies: ['
     ' { id: "skynet:proxy:23020", port: 23020, kind: "consumer", routerId: "", label: "Hermes", keyTail: "e676", set: "" },'
     ' { id: "ctl:proxy:23010", port: 23010, routerId: "", label: "alpha" }] });'
     ' st.ui.topologyRouterDetailId = "router:default";',
     '(() => { const h = m.renderTopologyRouterDetail(); const port = (h.split(\'data-router-attach="ctl:proxy:23010"\')[1] || "").split("</span></span>")[0];'
     ' return [(h.match(/class="rw-unassigned-badge"[^>]*>([^<]*)</) || [])[1] === fill(en.rtUnassigned, { n: 1 }), h.includes("skynet:proxy:23020"), h.includes("…e676"),'
     ' port.includes("503"), h.includes("router-pill free client")]; })()',
     '[true,false,false,true,false]',
     "клиент входа без пула — не в списке «не на канбане»: он не кормит канбан, его канат ведёт к пулу; "
     "negative: свободный порт по-прежнему в списке и помечен 503"),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 26:
        print(f"js routers FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js routers: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_routers.tmp.mjs"
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
        print(f"js routers FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("роутеры: запись графа и карточки выходов:")
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
    print(f"js routers OK: настоящий модуль в node, {len(PINS)} пинов маршрутизации значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
