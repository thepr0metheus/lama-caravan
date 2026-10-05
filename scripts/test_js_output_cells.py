#!/usr/bin/env python3
"""Snapshot of static/js/output-cells.js — the cell behind each local row of the kanban.

What a Servers row says of its cell (2026-10-04, after a look at the live kanban): its state,
in words and never guessed — 24 of 30 rows were stopped and drew the same grey "idle" dot as
the 6 that ran; its name as the cell itself is named — a moonshine cell read "en"; what sets
two cells of one model apart; and which stopped cells nothing leads to, so the panel can fold
them. The cables into a cell that is not serving read the same state (canvas.js).

The module is loaded FOR REAL with its real neighbours that carry the board's rules —
topology-nodes (machineAt, cellRunnerId, cellJobs), model-jobs, model-meta — so a pin here
breaks when the board's own rule moves. Only the DOM-heavy modules are stubbed, as in
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
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("topology-render,topology-modals,cables,routers,cloud,history,dialogs,favorites,config-locator,system-panels,"
         "onboarding,topology-dnd,canvas,usage-stats,dialog-llamas,models-page,system-page,onboarding-tours")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const m = await import(pathToFileURL(process.env.JS_ROOT + "/output-cells.js").href);
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const { OutputCells } = m;
// Two machines: the controller's (reached at loopback and at its LAN address) and another.
const CTL = (servers = [], extra = {}) => ({ id: "ctl", name: "ctl-box", ip: "10.0.0.5", controllerMachine: true, servers, ...extra });
const BOX = (servers = [], extra = {}) => ({ id: "b", name: "box-b", ip: "10.0.0.9", servers, ...extra });
const OUT = (port, host = "127.0.0.1", extra = {}) => ({ id: `srv:${port}`, upstreamHost: host, upstreamPort: port, upstreamType: "llama", ...extra });
// machineAt reads the board's topology (state.js): every pin sets the one it builds cells from.
const cells = (nodes, router = {}) => { st.setTopology({ server: { ip: "10.0.0.5" }, nodes, proxies: [], routers: [] });
  return new OutputCells(st.topology, router); };
const reset = () => { st.setState({ config: {}, runners: [] }); st.setTopology({ nodes: [], proxies: [], routers: [] }); };
const out = {};
"""

PINS = [
    # ── state ──
    ("state_by_phase",
     '',
     '(() => { const c = cells([CTL([{ port: 22001, phase: "running" }, { port: 22002, phase: "stopped" }, { port: 22003, phase: "reserved" },'
     ' { port: 22004, phase: "loading" }, { port: 22005, phase: "broken" }, { port: 22006, phase: "error" }, { port: 22007, phase: "stopping" },'
     ' { port: 22008, status: { phase: "warming" } }, { port: 22009, phase: "sleeping" }])]);'
     ' return [22001, 22002, 22003, 22004, 22005, 22006, 22007, 22008, 22009, 22010].map((p) => c.state(OUT(p))); })()',
     '["running","stopped","stopped","starting","failed","failed","stopping","starting","unknown","unknown"]',
     "состояние строки — слово записи ячейки: работает / остановлена (и reserved) / стартует (loading, warming — в том числе "
     "из status) / отказ (broken, error) / останавливается; negative: незнакомое слово и ячейка, которой доска не знает, — "
     "«unknown», а не stopped и не idle"),
    ("state_of_cloud_and_engine_outputs",
     '',
     '(() => { const c = cells([BOX([], { engines: [{ kind: "ollama", state: "ok" }, { kind: "lmstudio", state: "stopped" }, { kind: "x", state: "auth" }] })]);'
     ' const eng = (kind, hostId = "b") => ({ id: `eng:${kind}`, upstreamType: "engine", hostId, engine: kind, upstreamHost: "10.0.0.9", upstreamPort: 11434 });'
     ' return [c.state({ id: "cb:a", upstreamType: "cloud" }), c.state(eng("ollama")), c.state(eng("lmstudio")), c.state(eng("x")),'
     ' c.state(eng("y")), c.state(eng("ollama", "zz"))]; })()',
     '["","running","stopped","failed","unknown","unknown"]',
     "облако — без слова (его машины нет во флоте); модель движка — по состоянию движка её машины: ok — работает (модель "
     "грузится первым запросом), stopped — остановлен, auth/unreachable — отказ; negative: движка или машины нет — unknown"),
    ("cell_is_found_by_machine_then_port",
     '',
     '(() => { const c = cells([CTL([{ port: 22001, phase: "running" }]), BOX([{ port: 22001, phase: "stopped" }])]);'
     ' return [c.state(OUT(22001, "10.0.0.9")), c.state(OUT(22001, "127.0.0.1")), c.state(OUT(22001, "10.0.0.5"))]; })()',
     '["stopped","running","running"]',
     "ячейка ищется так же, как панель называет машину: машина по адресу (machineAt), затем порт; петля и LAN-адрес "
     "контроллера — одна машина; negative: тот же порт на другой машине — другая ячейка"),
    # ── name ──
    ("name_is_what_the_cell_runs",
     '',
     '(() => { const c = cells([CTL([{ port: 22014, model: "en", cellLabel: "moonshine en" }, { port: 22002, model: "/m/gemma-4-12B-it-Q8_0.gguf" }])]);'
     ' return [c.name(OUT(22014)), c.name(OUT(22002)), c.name(OUT(22009, "127.0.0.1", { label: "raw.gguf :22009" })), c.name(OUT(22011))]; })()',
     '["moonshine en","gemma-4-12B-it","raw.gguf",""]',
     "имя — собственная фраза ячейки (cell_artifact_label: «moonshine en», не «en»), иначе короткое имя модели, как на "
     "карточке ячейки; negative: ячейки нет — label выхода без порта; нет ничего — пусто, не выдумка"),
    # ── marks ──
    ("marks_are_the_card_jobs",
     '',
     '(() => { const c = cells([CTL([{ port: 22001, slotConfig: { RUNNER: "llama-server" } }, { port: 22002, slotConfig: { RUNNER: "llama-server", ENABLE_EMBEDDINGS: "1" } },'
     ' { port: 22003, slotConfig: { RUNNER: "moonshine" } }, { port: 22004, slotConfig: { RUNNER: "custom" } },'
     ' { port: 22005, slotConfig: { RUNNER: "custom" }, cellMeta: { kinds: ["tts"] } }, { port: 22006, slotConfig: { RUNNER: "seamless" } }])]);'
     ' return [22001, 22002, 22003, 22004, 22005, 22006, 22007].map((p) => c.marks(OUT(p))); })()',
     '["💬","🧬","🎧🔊","","🔊","🎧🌐",""]',
     "значки — работы ячейки, тот же список, что фишки на карточке (cellJobs): LLM, эмбеддинги по ENABLE_EMBEDDINGS, "
     "moonshine — распознавание и речь, команда — по живому kinds; negative: работу не назвать (команда без kinds) или "
     "ячейки нет — без значка"),
    # ── what is reached ──
    ("reached_outputs",
     '',
     '(() => { const c = cells([], { rules: { default: "cb:x", audioOutput: "srv:22030", embeddingsOutput: "srv:22001", failover: ["srv:22011"],'
     ' schedule: [{ output: "srv:22012" }], bySource: [{ output: "srv:22013" }] },'
     ' graph: { edges: [{ to: "out:srv:22020" }, { to: "rule:q" }, { to: "out:cb:y" }] } });'
     ' return [[...c.reached()].sort(), [...cells([], {}).reached()]]; })()',
     '[["cb:x","cb:y","srv:22001","srv:22011","srv:22012","srv:22013","srv:22020","srv:22030"],[]]',
     "к выходу ведёт: канат (ребро out:), выход по умолчанию, выходы аудио и эмбеддингов, старые списки правил; ребро к "
     "узлу правила — не выход; negative: пустой канбан — ничего"),
    # ── the quiet fold ──
    ("split_folds_stopped_cells_nothing_leads_to",
     '',
     '(() => { const srv = [{ port: 22001, phase: "running" }, { port: 22002, phase: "stopped" }, { port: 22003, phase: "stopped" },'
     ' { port: 22004, phase: "stopped" }, { port: 22005, phase: "broken" }]; const router = { graph: { edges: [{ to: "out:srv:22002" }] } };'
     ' const ids = (r) => [r.shown.map((o) => o.id), r.quiet.map((o) => o.id)];'
     ' const outs = [22001, 22002, 22003, 22004, 22005, 22006].map((p) => OUT(p));'
     ' const both = ids(cells([CTL(srv)], router).split(outs));'
     ' const one = ids(cells([CTL(srv.filter((s) => s.port !== 22004))], router).split(outs.filter((o) => o.upstreamPort !== 22004)));'
     ' return [both, one]; })()',
     '[[["srv:22001","srv:22002","srv:22005","srv:22006"],["srv:22003","srv:22004"]],[["srv:22001","srv:22002","srv:22003","srv:22005","srv:22006"],[]]]',
     "сворачиваются остановленные ячейки, к которым ничего не ведёт, — когда их две и больше; остановленная с канатом, "
     "отказавшая и неизвестная остаются на виду; negative: одна такая — не сворачивается (строка вместо строки ничего не экономит)"),
    # ── twins ──
    ("twins_say_what_sets_them_apart",
     '',
     '(() => { const c = cells([CTL(['
     ' { port: 22006, model: "seamless-m4t-v2-large", slotConfig: { RUNNER: "seamless", PORT: "22006", SEAMLESS_TGT_LANG: "eng" } },'
     ' { port: 22007, model: "seamless-m4t-v2-large", slotConfig: { RUNNER: "seamless", PORT: "22007", SEAMLESS_TGT_LANG: "rus" } },'
     ' { port: 22003, model: "g.gguf", slotConfig: { PORT: "22003", X: "1" } }, { port: 22004, model: "g.gguf", slotConfig: { PORT: "22004", X: "1" } },'
     ' { port: 22010, model: "s.gguf", slotConfig: { PORT: "22010", API_KEY: "aaa" } }, { port: 22011, model: "s.gguf", slotConfig: { PORT: "22011", API_KEY: "bbb" } },'
     ' { port: 22020, model: "u.gguf", slotConfig: { PORT: "22020" } }, { port: 22021, model: "u.gguf" },'
     ' { port: 22030, model: "solo.gguf", slotConfig: {} }])]);'
     ' const notes = Object.fromEntries(c.twins([22006, 22007, 22003, 22004, 22010, 22011, 22020, 22021, 22030].map((p) => OUT(p))));'
     ' return [notes, /aaa|bbb/.test(JSON.stringify(notes))]; })()',
     '[{"srv:22006":{"keys":["SEAMLESS_TGT_LANG"],"differ":[["SEAMLESS_TGT_LANG","eng"]]},'
     '"srv:22007":{"keys":["SEAMLESS_TGT_LANG"],"differ":[["SEAMLESS_TGT_LANG","rus"]]},'
     '"srv:22003":{"same":22004},"srv:22004":{"same":22003},'
     '"srv:22010":{"keys":["API_KEY"],"differ":[["API_KEY",null]]},"srv:22011":{"keys":["API_KEY"],"differ":[["API_KEY",null]]}},false]',
     "две ячейки одной модели на машине говорят, чем отличаются: каждая — своё значение («eng» рядом с «rus»); одинаковые "
     "во всём, кроме порта, — чья это копия; настройка, где может быть секрет, — только именем, значения нет нигде; "
     "negative: у близнеца нет настроек — молчат оба (сравнить не с чем — не «одинаковы»); без близнеца — ничего"),
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
            [node, "--import",
             f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print(f"js output-cells FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("ячейки за строками канбана:")
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
