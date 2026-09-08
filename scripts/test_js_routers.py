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
const m = await import(pathToFileURL(process.env.JS_ROOT + "/routers.js").href);
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
     'st.setTopology({ ...st.topology, server: { llamaServers: [{ port: 22001, model: "/models/Qwen3-Embedding-0.6B-f16.gguf" }] } });',
     'm.topologyRouterOutputLabel({ upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22001, label: "Qwen3-Embedding-0.6B-f16.gguf " })',
     '"Qwen3-Embedding-0.6B :22001"',
     "локальный выход — КРАСИВОЕ имя модели с сервера плюс порт, а не сырое имя .gguf из label"),
    ("output_label_local_without_server_uses_label",
     '',
     'm.topologyRouterOutputLabel({ upstreamType: "llama", upstreamHost: "127.0.0.1", upstreamPort: 22001, label: "raw.gguf" })',
     '"raw.gguf"',
     "negative: сервера на этом порту нет — остаётся label выхода"),
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
    # ── the output panel ──
    ("panel_one_radio_per_output_default_checked",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()] });',
     '(h => [(h.match(/class="router-out-radio"/g) || []).length, (h.match(/data-router-set-default="router:default"[^>]*>/g) || []).length, /data-router-set-default="router:default" data-router-out="cb:terra"[^>]*checked|checked data-router-set-default="router:default" data-router-out="cb:terra"/.test(h) || /is-default[^>]*data-router-out-row="cb:terra"/.test(h)])(m.renderRouterOutputsPanel(st.topology.routers[0]))',
     '[2,2,true]',
     "по радиокнопке на выход, и отмечен ровно default"),
    ("panel_provider_header_counts_exposed",
     'st.setTopology({ ...st.topology, ...CLOUD(), routers: [ROUTER()] });',
     '(h => [h.includes("☁ OpenAI (ChatGPT Plus)"), h.includes(">1/1</span>")])(m.renderRouterOutputsPanel(st.topology.routers[0]))',
     '[true,true]',
     "заголовок провайдера считает открытые модели из всех"),
    ("panel_without_cloud_says_so",
     'st.setTopology({ ...st.topology, routers: [ROUTER({ outputs: [] })] });',
     '(h => [h.includes("router-cfg-muted"), (h.match(/router-out-radio/g) || []).length])(m.renderRouterOutputsPanel(st.topology.routers[0]))',
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
