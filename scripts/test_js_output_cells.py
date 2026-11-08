#!/usr/bin/env python3
"""Snapshot of static/js/output-cells.js — the model behind each local row of Routing.

What a Servers row says of what stands behind it (2026-10-04, after a look at the live Routing): its
state, in words and never guessed — 24 of 30 rows were stopped and drew the same grey "idle" dot as
the 6 that ran; its name as the model is named; what it does; and which stopped models nothing leads
to, so the panel can fold them. The cables into a model that is not serving read the same state
(canvas.js).

Since 2026-11-07 (Papyrus caravan-scout-port-lease, step 3) a cell is no output of its own: it holds a
port only while it runs, and a request reaches it through its machine's model (`mm:`), of which it is a
copy. So a row is a model of a machine's entry or of an engine, found on the machine its output names
(`hostId`), and no row is found by a port.

The module is loaded FOR REAL with its real neighbour that carries the board's rule — model-jobs —
so a pin here breaks when the board's own rule moves. Only the DOM-heavy modules are stubbed, as in
test_js_topology_nodes.

Run: python3 scripts/test_js_output_cells.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

from _contract import Contract  # noqa: E402

STUBS = ("topology-render,topology-modals,cables,routers,cloud,history,dialogs,favorites,config-locator,system-panels,"
         "onboarding,topology-dnd,canvas,usage-stats,dialog-llamas,models-page,system-page,onboarding-tours")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const m = await import(pathToFileURL(process.env.JS_ROOT + "/output-cells.js").href);
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const { OutputCells } = m;
// Two machines: the controller's and another. A machine's cells are known by their names (cellId); a cell holds a port only
// while it runs.
const CTL = (servers = [], extra = {}) => ({ id: "ctl", name: "ctl-box", ip: "10.0.0.5", controllerMachine: true, servers, ...extra });
const BOX = (servers = [], extra = {}) => ({ id: "b", name: "box-b", ip: "10.0.0.9", servers, ...extra });
// A model of a machine's entry as the controller makes its output (rust/crates/admin/src/fleet/machine_models.rs): on its
// scout's address and port, named by the model, its machine's id beside it, and the ports its running copies leased.
const MM = (model, hostId = "b", extra = {}) => ({ id: `mm:${model}`, upstreamType: "machine", upstreamHost: hostId === "ctl" ? "10.0.0.5" : "10.0.0.9",
  upstreamPort: 8092, upstreamModel: model, label: model, hostId, copyPorts: [], ...extra });
// A model of an engine next to the cells (rust/crates/admin/src/fleet/engine_outputs.rs): on the engine's own port.
const ENG = (kind, hostId = "b", extra = {}) => ({ id: `eng:${kind}`, upstreamType: "engine", hostId, engine: kind, upstreamHost: "10.0.0.9", upstreamPort: 11434, ...extra });
// A copy of a model as its scout says it: its cell by name, the port it leased while it runs, none while it stands.
const COPY = (id, port = null, state = port ? "running" : "stopped") => ({ id, port, state, slots: null, busy: null });
const cells = (nodes, router = {}) => { st.setTopology({ server: { ip: "10.0.0.5" }, nodes, proxies: [], routers: [] });
  return new OutputCells(st.topology, router); };
const reset = () => { st.setState({ config: {}, runners: [] }); st.setTopology({ nodes: [], proxies: [], routers: [] }); };
const out = {};
"""

PINS = [
    # ── state ──
    ("state_by_the_scouts_word",
     '',
     '(() => { const c = cells([BOX([], { entryModels: [{ id: "gemma", state: "running", copies: [COPY("c22001", 22001)] },'
     ' { id: "ear", state: "stopped", copies: [COPY("c3f9a02b1")] }, { id: "big", state: "starting", copies: [] },'
     ' { id: "bad", state: "failed", copies: [] }, { id: "odd", state: "melting", copies: [] }] })]);'
     ' return ["gemma", "ear", "big", "bad", "odd", "nope"].map((x) => c.state(MM(x))); })()',
     '["running","stopped","starting","failed","unknown","unknown"]',
     "состояние строки — слово скаута о модели (entryModels её машины): работает / остановлена / стартует / отказ; "
     "negative: незнакомое слово и модель, которой скаут не называет, — «unknown», а не stopped и не idle"),
    ("no_row_is_found_by_a_port",
     '',
     '(() => { const c = cells([CTL([{ cellId: "c22001", port: 22001, phase: "running", cellLabel: "moonshine en", model: "en",'
     ' slotConfig: { RUNNER: "moonshine" } }])]);'
     ' const old = { id: "srv:22001", upstreamType: "llama", upstreamHost: "10.0.0.5", upstreamPort: 22001, label: "en" };'
     ' return [c.state(old), c.name(old), c.jobs(old), c.marks(old), c.copies(old), c.state({ ...old, upstreamType: undefined })]; })()',
     '["unknown","en",[],"",0,"unknown"]',
     "с 2026-11-07 ячейка — не выход: выход старого вида (srv:<порт>) не находит ячейку по порту — состояние «unknown», имя — его "
     "подпись, ни работ, ни копий; negative: работающая ячейка на том же порту строке ничего не одалживает — ни «running», ни "
     "фразы «moonshine en», ни значков"),
    ("state_of_cloud_and_engine_outputs",
     '',
     '(() => { const c = cells([BOX([], { engines: [{ kind: "ollama", state: "ok" }, { kind: "lmstudio", state: "stopped" }, { kind: "x", state: "auth" }] })]);'
     ' return [c.state({ id: "cb:a", upstreamType: "cloud" }), c.state(ENG("ollama")), c.state(ENG("lmstudio")), c.state(ENG("x")),'
     ' c.state(ENG("y")), c.state(ENG("ollama", "zz"))]; })()',
     '["","running","stopped","failed","unknown","unknown"]',
     "облако — без слова (его машины нет во флоте); модель движка — по состоянию движка её машины: ok — работает (модель "
     "грузится первым запросом), stopped — остановлен, auth/unreachable — отказ; negative: движка или машины нет — unknown"),
    ("model_is_found_on_the_machine_its_output_names",
     '',
     '(() => { const c = cells([CTL([], { entryModels: [{ id: "gemma", state: "running", copies: [COPY("c22001", 22001)] }] }),'
     ' BOX([], { entryModels: [{ id: "gemma", state: "stopped", copies: [COPY("c22002")] }] })]);'
     ' return [c.state(MM("gemma", "b")), c.state(MM("gemma", "ctl")), c.state(MM("gemma", "b", { upstreamHost: "10.0.0.5" })),'
     ' c.state(MM("gemma", "zz", { upstreamHost: "10.0.0.5" })), c.state(MM("gemma", ""))]; })()',
     '["stopped","running","stopped","unknown","unknown"]',
     "модель ищется на машине, которую называет её выход (hostId): одна модель на двух машинах — две строки, каждая со словом "
     "своего скаута; адрес выхода машину не выбирает; negative: машины с таким id нет или id пуст — unknown, даже когда адрес — "
     "известной машины"),
    # ── name ──
    ("name_of_a_model",
     '',
     '(() => { const c = cells([]); const names = [c.name(MM("gemma-4-12B")), c.name(MM("", "b", { label: "fallback" })), c.name(MM("", "b", { label: "" })),'
     ' c.name(ENG("ollama", "b", { label: "qwen3:8b · Ollama", upstreamModel: "qwen3:8b" })), c.name(ENG("ollama", "b", { upstreamModel: "qwen3:8b" })),'
     ' c.name(ENG("ollama", "b", { engine: "" })), c.name({ id: "o1", label: "plain" }), c.name({ id: "o1" })];'
     ' return [names, names.some((n) => /:(8092|11434)/.test(n))]; })()',
     '[["gemma-4-12B","fallback","","qwen3:8b · Ollama","qwen3:8b · ollama","","plain",""],false]',
     "имя строки — имя модели (модель входа машины), подпись, что контроллер дал модели движка («qwen3:8b · Ollama»), иначе "
     "модель и движок; у выхода иного вида — его подпись; negative: назвать нечем — пусто, не выдумка; порта в имени нет — ни "
     "входа машины, ни движка"),
    # ── what it does ──
    ("jobs_and_marks_are_what_the_output_says",
     '',
     '(() => { const c = cells([]); const outs = [MM("a", "b", { jobs: ["llm"] }), MM("e", "b", { jobs: ["embed"] }), MM("m", "b", { jobs: ["asr", "tts"] }),'
     ' MM("s", "b", { jobs: ["speech-translate"] }), MM("n", "b", { jobs: [] }), MM("x"), ENG("ollama"), MM("w", "b", { jobs: "llm" })];'
     ' return [outs.map((o) => c.jobs(o)), outs.map((o) => c.marks(o))]; })()',
     '[[["llm"],["embed"],["asr","tts"],["speech-translate"],[],[],[],[]],["💬","🧬","🎧🔊","🎧🌐","","","",""]]',
     "работы модели — то, что контроллер говорит на её выходе (jobs, из её копий), значки — те же работы (marks): строка модели "
     "в Маршрутизации берёт из имён и значок, и подсказку; negative: работы не сказано (пустой список, ничего, не список) или это "
     "модель движка — пустой список и без значка, а не «💬» по умолчанию"),
    ("a_cell_lends_its_model_nothing",
     '',
     '(() => { const c = cells([BOX([{ cellId: "c22003", port: 22003, phase: "running", cellLabel: "moonshine en", model: "en", slotConfig: { RUNNER: "moonshine" } }],'
     ' { entryModels: [{ id: "en", state: "stopped", copies: [COPY("c22003", 22003, "running")] }] })]);'
     ' return [c.state(MM("en")), c.name(MM("en")), c.jobs(MM("en")), c.copies(MM("en"))]; })()',
     '["stopped","en",[],1]',
     "строка говорит слово скаута о модели, а не о ячейке за ней: копия работает, скаут сказал о модели «stopped» — строка stopped; "
     "имя — модели; работы — со слов выхода; negative: ячейка-копия (moonshine) не одалживает строке ни своей фразы, ни значков"),
    # ── what is reached ──
    ("reached_outputs",
     '',
     '(() => { const c = cells([], { rules: { default: "cb:x", audioOutput: "mm:ear", embeddingsOutput: "mm:emb", failover: ["mm:f"],'
     ' schedule: [{ output: "mm:s" }], bySource: [{ output: "eng:o" }] },'
     ' graph: { edges: [{ to: "out:mm:g" }, { to: "rule:q" }, { to: "out:cb:y" }] } });'
     ' return [[...c.reached()].sort(), [...cells([], {}).reached()]]; })()',
     '[["cb:x","cb:y","eng:o","mm:ear","mm:emb","mm:f","mm:g","mm:s"],[]]',
     "к выходу ведёт: канат (ребро out:), выход по умолчанию, выходы аудио и эмбеддингов, старые списки правил; ребро к "
     "узлу правила — не выход; negative: пустая Маршрутизация — ничего"),
    # ── the quiet fold ──
    ("split_folds_stopped_models_nothing_leads_to",
     '',
     '(() => { const models = [{ id: "a", state: "running" }, { id: "b", state: "stopped" }, { id: "c", state: "stopped" },'
     ' { id: "d", state: "stopped" }, { id: "e", state: "failed" }]; const router = { graph: { edges: [{ to: "out:mm:b" }] } };'
     ' const ids = (r) => [r.shown.map((o) => o.id), r.quiet.map((o) => o.id)];'
     ' const outs = ["a", "b", "c", "d", "e", "f"].map((x) => MM(x));'
     ' const both = ids(cells([BOX([], { entryModels: models })], router).split(outs));'
     ' const one = ids(cells([BOX([], { entryModels: models.filter((x) => x.id !== "d") })], router).split(outs.filter((o) => o.upstreamModel !== "d")));'
     ' return [both, one]; })()',
     '[[["mm:a","mm:b","mm:e","mm:f"],["mm:c","mm:d"]],[["mm:a","mm:b","mm:c","mm:e","mm:f"],[]]]',
     "сворачиваются остановленные модели, к которым ничего не ведёт, — когда их две и больше; остановленная с канатом, "
     "отказавшая и неизвестная остаются на виду; negative: одна такая — не сворачивается (строка вместо строки ничего не экономит)"),
    # ── a model of a machine's entry (1.3.506) ──
    ("machine_model_from_its_machine",
     '',
     '(() => { const models = [{ id: "gemma", state: "running", copies: [COPY("c22001", 22001), COPY("c3f9a02b1")] },'
     ' { id: "ear", state: "stopped", copies: [COPY("c22005")] }, { id: "odd", state: "melting", copies: [] }];'
     ' const c = cells([BOX([{ cellId: "c22001", port: 22001, phase: "stopped" }], { entryModels: models }), CTL([])]);'
     ' const g = MM("gemma", "b", { jobs: ["llm", "embed"] });'
     ' return [[c.state(g), c.name(g), c.marks(g), c.copies(g)],'
     ' [c.state(MM("ear")), c.copies(MM("ear"))], c.state(MM("odd")), c.state(MM("nope")), c.state(MM("gemma", "zz")),'
     ' cells([BOX([])]).state(MM("gemma")), c.copies(ENG("ollama")), c.modelOf(ENG("ollama"))]; })()',
     '[["running","gemma","💬🧬",2],["stopped",1],"unknown","unknown","unknown","unknown",0,null]',
     "модель входа машины — по слову скаута о ней (entryModels её машины, по hostId): состояние, имя модели, значки — из "
     "сведений выхода, копий — и работающих, и стоящих (у стоящей порта нет); фаза ячейки на карточке машины слова скаута не "
     "меняет; negative: незнакомое слово, модели нет в списке, чужая машина, старый скаут без списка — unknown, а не stopped; "
     "у модели движка копий нет"),
    ("queue_name_is_the_proxys",
     '',
     f'{json.dumps([row["upstream"] for row in Contract.table("controller")["routeGroups"]])}.map((o) => OutputCells.upstream(o))',
     json.dumps([row["group"] for row in Contract.table("controller")["routeGroups"]]),
     "имя очереди выхода на доске — то же, что прокси ставит на запрос (route_group_key): движок и выход иного вида — "
     "«адрес:порт», модель машины — «адрес:порт/модель»; одна таблица для обоих двойников"),
    ("every_state_word_is_a_string",
     '',
     'Object.values(OutputCells.WORDS).map((k) => typeof en[k] === "string" && en[k].length > 0)',
     '[true,true,true,true,true]',
     "у каждого слова состояния есть строка интерфейса — иначе строка показала бы ключ"),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    node = find_node()
    if node is None:
        print("js output-cells: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    # Pins don't depend on each other: the same set run in reverse order must give the same values.
    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_output_cells.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            probe_args(node, harness, path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print(f"js output-cells FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("ячейки за строками Маршрутизации:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:300]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:300]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print(f"порядок: {len(PINS)} пинов дают те же значения в обратном порядке" if not _fail else "")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg.splitlines()[0])
        return 1
    print(f"js output-cells OK: настоящий модуль в node, {len(PINS)} пинов значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
