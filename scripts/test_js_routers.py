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
(cloud ones by account, local ones by the model's nice name from the
server), an output's liveness (matched by upstream host:port, for the cloud
by providerId, because every cloud output shares one host:port), the
router's compact card, and the output panel with its single "default" radio
button.

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
// The closer of models' ports lives in cloud.js (stubbed): an object, so its
// stand-in is a value — it writes down what it was asked and answers `answer`.
globalThis.__stubValues = { ...(globalThis.__stubValues || {}),
  "cloud.PORT_CLOSER": { calls: [], answer: null, close(id, port) { this.calls.push([id, port ?? null]); return Promise.resolve(this.answer); } },
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
  { id: "cb:terra", label: "☁ gpt-5.6-terra", upstreamHost: "127.0.0.1", upstreamPort: 8080, upstreamType: "cloud", providerId: "gpt-5-6-terra", accountId: "openai-subscription" },
], rules: { default: "cb:terra", schedule: [], bySource: [] }, graph: { nodes: [], edges: [], inputs: {} }, ...extra });
const CLOUD = () => ({ cloudAccounts: [{ id: "openai-subscription", type: "openai", name: "OpenAI (ChatGPT Plus)" }],
  cloudProviders: [{ id: "gpt-5-6-terra", accountId: "openai-subscription", model: "gpt-5.6-terra", exposed: true }] });
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
    ("output_label_cloud_by_account_name",
     'st.setTopology({ ...st.topology, ...CLOUD() });',
     'm.topologyRouterOutputLabel({ upstreamType: "cloud", accountId: "openai-subscription" })',
     '"☁ OpenAI (ChatGPT Plus)"',
     "облачный выход подписывается ИМЕНЕМ аккаунта, не id"),
    ("output_label_cloud_keeps_own_label",
     'st.setTopology({ ...st.topology, ...CLOUD() });',
     'm.topologyRouterOutputLabel({ upstreamType: "cloud", accountId: "openai-subscription", label: "☁ gpt-5.6-terra" })',
     '"☁ gpt-5.6-terra"',
     "boundary: у выхода есть своя подпись — она побеждает имя аккаунта"),
    ("output_label_cloud_unknown_account",
     '',
     'm.topologyRouterOutputLabel({ upstreamType: "cloud", accountId: "gone" })',
     '"☁ gone"',
     "negative: аккаунт удалён — показывается его id, а не «cloud» и не пустота"),
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
    # ── a router's liveness ──
    ("router_activity_from_its_inputs",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, label: "p" }] });'
     ' st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", port: 23001 }] });',
     'm.topologyRouterActivity({ inputs: ["skynet:proxy:23001"] }).state',
     '"active"',
     "роутер жив живостью своих входов"),
    ("router_activity_idle_without_inputs",
     'st.setTopology({ ...st.topology, proxies: [{ id: "skynet:proxy:23001", port: 23001, label: "p" }] });'
     ' st.ui.latestSystemMonitor = MON({ active: [{ phase: "running", port: 23001 }] });',
     '[m.topologyRouterActivity({ inputs: [] }).state, m.topologyRouterActivity({ inputs: ["skynet:proxy:29999"] }).state, m.topologyRouterActivity(null).state]',
     '["idle","idle","idle"]',
     "negative: без входов, с неизвестным входом, без роутера — idle, без исключения"),
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
    ("save_nested_flag_counts",
     '',
     '(() => { m._setRoutersSaving(true); m._setRoutersSaving(true); const two = m._routersSaving; m._setRoutersSaving(false); const one = m._routersSaving; m._setRoutersSaving(false); m._setRoutersSaving(false); return [two, one, m._routersSaving]; })()',
     '[2,1,0]',
     "boundary: две записи подряд считаются, а лишнее снятие не уводит счётчик в минус"),
    # ── the router's card ──
    ("card_counts_inputs_and_outputs",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER({ inputs: ["a", "b", "c"] })] });',
     '(h => [h.includes("in 3 · out 2"), h.includes("router-output-row is-default"), h.includes("☁ gpt-5.6-terra"), h.includes(">default</span>")])(m.renderTopologyRouterCard(st.topology.routers[0]))',
     '[true,true,true,true]',
     "карточка: счётчики входов/выходов, строка default с подписью выхода и чипом"),
    ("card_without_outputs_says_so",
     'st.setTopology({ ...st.topology, routers: [ROUTER({ outputs: [], rules: { default: "" } })] });',
     '(h => [h.includes("router-output-row empty"), h.includes("is-default")])(m.renderTopologyRouterCard(st.topology.routers[0]))',
     '[true,false]',
     "negative: выходов нет — об этом сказано, и строки default нет"),
    ("card_default_pointing_nowhere",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER({ rules: { default: "cb:gone" } })] });',
     '(h => [h.includes("is-default"), h.includes("in 0 · out 2")])(m.renderTopologyRouterCard(st.topology.routers[0]))',
     '[false,true]',
     "boundary: default указывает на удалённый выход — строки default нет, но карточка не падает и счётчики верны"),
    ("card_mentions_rules_when_any",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER({ rules: { default: "cb:terra", schedule: [{}, {}], bySource: [{}] } })] });',
     'm.renderTopologyRouterCard(st.topology.routers[0]).includes("3 rule(s)")',
     'true',
     "positive: правила посчитаны по обоим спискам"),
    # ── the router's outputs: the Servers block on the kanban ──
    ("panel_one_radio_per_output_default_checked",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()] });',
     '(h => [(h.match(/class="router-out-radio"/g) || []).length, (h.match(/data-router-set-default="router:default"[^>]*>/g) || []).length, /data-router-set-default="router:default" data-router-out="cb:terra"[^>]*checked|checked data-router-set-default="router:default" data-router-out="cb:terra"/.test(h) || /is-default[^>]*data-router-out-row="cb:terra"/.test(h)])(m.renderServersBlockHtml(st.topology.routers[0]))',
     '[2,2,true]',
     "по радиокнопке на выход, и отмечен ровно default"),
    ("panel_provider_header_counts_exposed",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()] });',
     '(h => [h.includes("☁ OpenAI (ChatGPT Plus)"), h.includes(">1/1</span>")])(m.renderServersBlockHtml(st.topology.routers[0]))',
     '[true,true]',
     "заголовок провайдера считает открытые модели из всех"),
    ("servers_block_marks_new_and_gone_models",
     'st.setTopology({ ...st.topology, cloudAccounts: [{ id: "acc", name: "Prov" }], cloudProviders: ['
     ' { id: "a", accountId: "acc", model: "shown-1", exposed: true }, { id: "b", accountId: "acc", model: "zz-new", newSince: 1_700_000_000 },'
     ' { id: "c", accountId: "acc", model: "aa-hidden" }, { id: "d", accountId: "acc", model: "old-gone", unlisted: true },'
     ' { id: "e", accountId: "acc", model: "stale-new", newSince: 1_000 }], routers: [ROUTER({ outputs: [] })] });',
     '(() => { m.topologyOutputsCloudExpanded.acc = true; try { const h = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' const all = (re) => [...h.matchAll(re)].map((x) => x[1]);'
     ' return [h.match(/router-prov-count" title="([^"]*)">([^<]*)</).slice(1), all(/class="cloud-chip fresh">([^<]*)</g),'
     ' all(/class="cloud-chip gone">([^<]*)</g), all(/router-prov-model-name">([^<]*)</g)]; }'
     ' finally { delete m.topologyOutputsCloudExpanded.acc; } })()',
     '[["1 on kanban · Models 5","1/5"],["1 new","new"],["1 gone"],["shown-1","zz-new","aa-hidden","old-gone","stale-new"]]',
     "панель канбана говорит то же, что карточка провайдера: «1/5» с подсказкой «1 на канбане · Модели 5», метки «новых» и «ушли»; "
     "в списке — метка «новая», показанные первыми, новые следом (иначе в длинном списке их не найти), дальше по цене, при равной — по имени; "
     "boundary: модель старше недели — уже не новая"),
    ("kanban_untick_goes_through_the_closer",
     '',
     'await (async () => { const pc = globalThis.__stubValues["cloud.PORT_CLOSER"]; pc.calls = []; pc.answer = null; let renders = 0;'
     ' globalThis.__stubReturns["topology-render.renderTopology"] = () => { renders++; };'
     ' try { st.setTopology({ ...st.topology, cloudProviders: [{ id: "b", accountId: "acc", model: "m" }] });'
     ' m.setCloudModelExposed("b", false); await m._cloudExposeChain; const cancelled = [pc.calls.slice(), renders];'
     ' pc.answer = { closed: [23004] }; renders = 0; m.setCloudModelExposed("b", false); await m._cloudExposeChain;'
     ' return [cancelled, pc.calls.length, renders, calls().length]; }'
     ' finally { delete globalThis.__stubReturns["topology-render.renderTopology"]; } })()',
     '[[[["b",null]],1],2,0,0]',
     "снять галочку = закрыть порты модели через окно закрытия (оно спросит про канаты); отмена — доска перерисована, галочка вернулась; "
     "закрыто — рисует ответ окна; negative: сам канбан ничего не шлёт"),
    ("kanban_tick_opens_a_port",
     '',
     'await (async () => { globalThis.__fetchReply["/api/cloud-blocks/expose"] = { ok: true, port: 23012, topology: { ...st.topology, marker: 1 } };'
     ' try { st.setTopology({ ...st.topology, cloudProviders: [{ id: "b", accountId: "acc", model: "gpt-x" }] });'
     ' m.setCloudModelExposed("b", true); await m._cloudExposeChain;'
     ' return [calls().map((c) => [c.path, JSON.parse(c.body)]), toastText() === fill(en.portOpened, { model: "gpt-x", port: "23012" }), st.topology.marker]; }'
     ' finally { delete globalThis.__fetchReply["/api/cloud-blocks/expose"]; } })()',
     '[[["/api/cloud-blocks/expose",{"id":"b","exposed":true}]],true,1]',
     "поставить галочку = открыть модели свой порт; тост называет порт; доска — из ответа"),
    ("servers_block_shows_each_cloud_models_port",
     'st.setTopology({ ...st.topology, ...CLOUD(), proxies: [{ port: 23004, kind: "service", providerId: "gpt-5-6-terra" }], routers: [ROUTER()] });',
     '(() => { m.topologyOutputsCloudExpanded["openai-subscription"] = true; try { const all = (h) => [...h.matchAll(/router-out-port">([^<]*)</g)].map((x) => x[1]);'
     ' const withPort = all(m.renderServersBlockHtml(st.topology.routers[0])); st.setTopology({ ...st.topology, proxies: [] });'
     ' return [withPort, all(m.renderServersBlockHtml(st.topology.routers[0]))]; } finally { delete m.topologyOutputsCloudExpanded["openai-subscription"]; } })()',
     '[[":23004",":23004"],[]]',
     "облачная модель на канбане — со своим портом, и он виден: у выхода и в списке моделей провайдера; negative: порта нет — номера нет"),
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
     ' st.setTopology({ ...st.topology, cloudAccounts: [{ id: "solo", type: "openai", name: "Router" },'
     ' { id: "pp", type: "openai", name: "Pool", isPool: true, pool: { id: "pp", members: [{ accountId: "plus", enabled: true }] } },'
     ' { id: "plus", type: "openai", name: "Plus" }], cloudProviders: [{ id: "own", accountId: "plus", model: "m-own" }],'
     ' routers: [ROUTER({ outputs: [{ id: "srv:22003", label: "b", upstreamHost: "10.0.0.9", upstreamPort: 22003, upstreamType: "llama" },'
     ' { id: "srv:22001", label: "a", upstreamHost: "127.0.0.1", upstreamPort: 22001, upstreamType: "llama" }] })] });',
     '(() => { const so = globalThis.__so; const heads = (h) => [...h.matchAll(/class="router-(?:out-host-label|prov-name)">(?:☁ )?([^<]*)/g)].map((x) => x[1].trim());'
     ' try { const h0 = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' so.held = { order: ["cloud:pp", "node:m-b", "cloud:solo", "node:m-ctl"], rev: 1 }; const h1 = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' so.held = { order: ["node:m-b"], rev: 2 }; const h2 = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' return [heads(h0), heads(h1), heads(h2), [h0, h1].some((h) => h.includes("router-out-sec-h")), (h1.match(/class="router-out-sec"/g) || []).length]; }'
     ' finally { so.held = { order: [], rev: -1 }; } })()',
     '[["ctl-box","box-b","Router","Pool","Plus"],["Pool","Plus","box-b","Router","ctl-box"],["box-b","ctl-box","Router","Pool","Plus"],false,1]',
     "группы панели «Серверы» идут в порядке доски: ничего не сохранено — как раньше, машины (по наименьшему порту), "
     "затем облако по записям; сохранено — вперемешку, как карточки, участник пула рядом со своим пулом; не названные — "
     "после названных, в прежнем порядке; заголовков «Local» и «Cloud» больше нет — один список"),
    # 2026-10-04: a pool's member without models of its own has no group — its models are
    # reached through the pool, and the empty group said "0/0" and "↻ on its card" (no card).
    ("kanban_hides_an_empty_pool_member",
     '',
     '(() => { const run = (blocks) => { st.setTopology({ ...st.topology, cloudAccounts: [{ id: "pp", type: "openai", name: "Pool", isPool: true,'
     ' pool: { id: "pp", members: [{ accountId: "plus", enabled: true }] } }, { id: "plus", type: "openai", name: "Plus" }],'
     ' cloudProviders: blocks, routers: [ROUTER({ outputs: [] })] }); const h = m.renderServersBlockHtml(st.topology.routers[0]);'
     ' return [...h.matchAll(/class="router-prov-name">☁ ([^<]*)/g)].map((x) => x[1]); };'
     ' return [run([{ id: "b1", accountId: "pp", model: "m1" }]), run([{ id: "b1", accountId: "pp", model: "m1" }, { id: "b2", accountId: "plus", model: "m2" }])]; })()',
     '[["Pool"],["Pool","Plus"]]',
     "участник пула без своих моделей — без группы на канбане (его модели идут через пул); "
     "negative: у участника есть своя модель — группа остаётся, рядом с пулом"),
    ("kanban_says_which_kind_it_has_none_of",
     '',
     '(() => { const run = (outputs, accounts) => { st.setTopology({ ...st.topology, cloudAccounts: accounts, cloudProviders: [], routers: [ROUTER({ outputs })] });'
     ' const h = m.renderServersBlockHtml(st.topology.routers[0]); return [h.includes(en.rtNoLocalServers), h.includes(en.rtNoCloudProviders)]; };'
     ' const local = [{ id: "srv:22001", label: "a", upstreamHost: "127.0.0.1", upstreamPort: 22001, upstreamType: "llama" }];'
     ' return [run([], []), run(local, []), run([], [{ id: "solo", type: "openai", name: "Router" }]), run(local, [{ id: "solo", type: "openai", name: "Router" }])]; })()',
     '[[true,true],[false,true],[true,false],[false,false]]',
     "пусто по своему виду — своя строка после списка: нет машин — «no local servers», нет облака — «no cloud providers»; "
     "negative: есть и то и другое — ни одной"),
    ("model_queue_below_its_local_row_only", 'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()] });', '(() => { const h = m.renderServersBlockHtml(st.topology.routers[0], { "srv:22001": "LOCAL-QUEUE", "cb:terra": "CLOUD-QUEUE" }); return [h.indexOf("LOCAL-QUEUE") > h.indexOf(\'data-router-out-row="srv:22001"\'), h.indexOf("LOCAL-QUEUE") < h.indexOf(\'data-router-out-row="cb:terra"\'), h.includes("CLOUD-QUEUE")]; })()',
     '[true,true,false]', "очередь стоит после строки своей локальной модели и до следующей модели; облако без автоматической очереди"),
    ("model_queue_folds_with_host", 'st.setTopology({ ...st.topology, routers: [ROUTER()] }); m.topologyOutputsFolded["host:m-ctl"] = true;', '(() => { try { return m.renderServersBlockHtml(st.topology.routers[0], { "srv:22001": "LOCAL-QUEUE" }).includes("LOCAL-QUEUE"); } finally { delete m.topologyOutputsFolded["host:m-ctl"]; } })()',
     'false', "свёрнутая группа скрывает модели и их очереди вместе"),
    ("router_detail_toolbar_has_no_queue_settings", 'st.setTopology({ ...st.topology, routers: [ROUTER()] }); st.ui.topologyRouterDetailId = "router:default";',
     '(() => { const h = m.renderTopologyRouterDetail(); const at = (k) => h.indexOf(k); return [typeof h, h.includes("rw-palette"), h.includes("kanban-palette-add"), h.includes("data-cv-queue-settings"), h.includes("cv-queue-settings"), h.includes("data-cv-cols"), h.includes("<aside>CLIENTS</aside>") && h.includes("<aside>SERVERS</aside>") && at("<aside>CLIENTS</aside>") < at("rw-center") && at("rw-center") < at("<aside>SERVERS</aside>"), at("<aside>SERVERS</aside>") > at("data-cv-viewport")]; })()',
     '["string",true,true,false,false,true,true,true]', "рабочее поле: панель клиентов слева, холст с палитрой посередине, панель серверов справа, внутри одной сетки; в панели инструментов нет строки политики очередей — она живёт в панели серверов, одна на доску"),
    # 2026-10-04: "4 unassigned" on the live kanban counted four cloud models' own ports
    # (kind "service") — outputs of the Servers panel that never feed a router. The badge
    # counts only ports that can, and opens their list by name, both heads alike.
    ("kanban_unassigned_counts_only_ports_that_feed_routers",
     'st.setTopology({ ...st.topology, routers: [ROUTER(), { ...ROUTER(), id: "router:b", name: "second" }], proxies: ['
     ' { id: "ctl:proxy:23004", port: 23004, kind: "service", routerId: "", label: "model port" },'
     ' { id: "ctl:proxy:23010", port: 23010, routerId: "", label: "alpha" },'
     ' { id: "ctl:proxy:23011", port: 23011, routerId: "router:b", label: "beta" },'
     ' { id: "ctl:proxy:23001", port: 23001, routerId: "router:default", label: "mine" }] });'
     ' st.ui.topologyRouterDetailId = "router:default";',
     '(() => { const read = (h) => [(h.match(/class="rw-unassigned-badge"[^>]*>([^<]*)</) || [])[1] || "",'
     ' [...h.matchAll(/data-router-attach="([^"]*)"/g)].map((x) => x[1]), [...h.matchAll(/router-pill-name">([^<]*)</g)].map((x) => x[1])];'
     ' const overlay = read(m.renderTopologyRouterDetail()); window.ROUTER_STANDALONE = true;'
     ' try { return [overlay, read(m.renderTopologyRouterDetail()), fill(en.rtUnassigned, { n: 2 })]; } finally { delete window.ROUTER_STANDALONE; } })()',
     '[["2 unassigned",["ctl:proxy:23010","ctl:proxy:23011"],["alpha","beta"]],["2 unassigned",["ctl:proxy:23010","ctl:proxy:23011"],["alpha","beta"]],"2 unassigned"]',
     "значок считает только порты, которые могут кормить канбан: свободный и на другом канбане; порт модели облака "
     "(kind service) — выход, не клиент, его нет ни в счёте, ни в списке; список называет порты по имени; обе шапки одинаковы"),
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
    ("kanban_unassigned_absent_when_only_model_ports",
     'st.setTopology({ ...st.topology, routers: [ROUTER()], proxies: ['
     ' { id: "ctl:proxy:23004", port: 23004, kind: "service", routerId: "", label: "model port" },'
     ' { id: "ctl:proxy:23001", port: 23001, routerId: "router:default", label: "mine" }] });'
     ' st.ui.topologyRouterDetailId = "router:default";',
     '(h => [h.includes("rw-unassigned"), h.includes("ctl:proxy:23004")])(m.renderTopologyRouterDetail())',
     '[false,false]',
     "negative: свободны только порты моделей облака — значка нет совсем (на проде было «4 unassigned» — ложная тревога)"),
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
