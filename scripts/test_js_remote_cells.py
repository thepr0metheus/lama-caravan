#!/usr/bin/env python3
"""Snapshot of static/js/remote-cells.js — the actions behind client cells' buttons.

What's pinned for an action: WHAT goes out on the wire (calls(): path,
method, body), WHAT the operator sees (toastText()), and WHAT stays in state
(the sets _stoppingCells/_pendingCellActions/_deletingSlots/_reservingCells/
_newReservedCells/_pendingRemoteStarts). A history of fixes: instant busy and
pending state (87f5ea7), port selection skipping proxy ports (4bfeeab), a
"starting" card shown before the real one appears.

fetch is a recorder (_js_globals.mjs): calls land in __fetchCalls, the reply
comes from __fetchReply[path] or defaults to {ok:true}; __status makes api()
throw. appConfirm's confirmation is a stub with a set answer (__stubReturns).
A toast is an element from the __fields dict, and its textContent is exactly
the text the operator sees. Time is frozen.

Run: python3 scripts/test_js_remote_cells.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

def _english():
    """Every one-string line of en.js — a pin quotes the page's own words, not a
    copy of them that can drift."""
    import re
    out = {}
    for key, raw in re.findall(r'^  (\w+): (".*"),$', (ROOT / "static/js/i18n/en.js").read_text(encoding="utf-8"), re.M):
        try:
            out[key] = json.loads(raw)
        except ValueError:
            continue
    return out


EN = _english()


def en(key, **kw):
    text = EN[key]
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


STUBS = ("topology-render,topology-modals,cables,routers,cloud,history,dialogs,favorites,config-locator,system-panels,"
         "onboarding,topology-dnd,canvas,usage-stats,dialog-llamas,models-page,system-page,onboarding-tours")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {}, runners: [], artifacts: [], models: [], paths: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {}, nodes: [] });
Date.now = () => 1_700_000_100_000;
globalThis.__stubReturns = { "dialogs.appConfirm": async () => true };
const le = await import(pathToFileURL(process.env.JS_ROOT + "/llama-edit.js").href);
const rc = await import(pathToFileURL(process.env.JS_ROOT + "/remote-cells.js").href);
const cst = await import(pathToFileURL(process.env.JS_ROOT + "/constants.js").href);
const ui = st.ui;
const norm = (s) => String(s).replace(/\s+/g, " ").trim();
const toastEl = () => ({ textContent: "", classList: { add() {}, remove() {} } });
const F = (fields) => { globalThis.__fields = { toast: toastEl(), ...fields }; };
const reset = () => { st.setState({ config: {}, runners: [], artifacts: [], models: [], paths: {} });
  st.setTopology({ proxies: [], clients: [], routers: [], assignments: {}, nodes: [] });
  F({}); globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__stubReturns = { "dialogs.appConfirm": async () => true };
  for (const c of [rc._stoppingHosts, rc._stoppingCells, rc._deletingSlots, rc._newReservedCells, rc._pendingRemoteStarts, rc._pendingCellActions, rc._reservingCells]) c.clear(); };
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body }));
const toastText = () => globalThis.__fields.toast.textContent;
const out = {};
"""

# (id, setup, expression, expected JSON string, message). Filled from the pin
# workflow; see the OOP-rewrite journal (private), phase 7, snapshot 6.
# A machine whose scout reports three engines: Ollama running with two models,
# LM Studio stopped (a model still listed: not ready is not ready), and "foo" —
# an engine no runner of engine cells serves.
# The dialogs record what they were asked and answer from __answers in turn.
RSC_ENGINES = (
    'globalThis.__snap = null; globalThis.__msg = null; globalThis.__asks = [];'
    ' globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; };'
    ' globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; };'
    ' globalThis.__stubReturns["dialogs.appConfirmChoice"] = async (msg, opts) => { globalThis.__asks.push({ msg, opts }); return globalThis.__answers.shift(); };'
    ' st.setState({ config: {}, runners: [{ id: "llama-server" }, { id: "ollama", engineCell: true }, { id: "lmstudio", engineCell: true }], artifacts: [], models: [], paths: {} });'
    ' st.topology.nodes = [{ id: "h1", engines: ['
    '{ kind: "ollama", label: "Ollama", port: 11434, state: "ok", models: [{ name: "qwen2.5:0.5b", params: "494M", quant: "Q4_K_M" }, { name: "gpt-oss:120b-cloud", remote: true }] },'
    ' { kind: "lmstudio", label: "LM Studio", port: 1234, state: "stopped", models: [{ name: "google/gemma-4-e4b" }] },'
    ' { kind: "foo", label: "Foo", port: 9, state: "ok", models: [{ name: "f" }] }] }];'
)
RSC_RUN = ('await (async () => { await rc.reserveServerCell("h1"); return { calls: calls(), toast: toastText(), '
           'asks: globalThis.__asks, confirm: globalThis.__msg, reserving: [...rc._reservingCells.entries()], '
           'fresh: [...rc._newReservedCells], snap: globalThis.__snap }; })()')
RSC_ASK = {"danger": False, "confirmLabel": en("topologyReserveCellLabel"), "scene": "create"}
RSC_WHERE = {"msg": en("dlgReserveCell", port=22001), "opts": {**RSC_ASK, "choiceLabel": en("reserveRunsIn"), "choices": [
    {"value": "", "label": en("launcherCaravan")}, {"value": "ollama", "label": "Ollama"},
    {"value": "lmstudio", "label": en("reserveEngineNotReady", engine="LM Studio")}]}}
RSC_MODEL = {"msg": en("dlgReserveModelText", engine="Ollama"), "opts": {
    **RSC_ASK, "title": en("dlgReserveModelTitle", port=22001), "choiceLabel": en("reserveModelLabel"), "list": True,
    "choices": [{"value": "qwen2.5:0.5b", "label": "qwen2.5:0.5b · 494M · Q4_K_M"},
                {"value": "gpt-oss:120b-cloud", "label": "gpt-oss:120b-cloud · ☁"}]}}


def rsc_add(body):
    return [{"path": "/api/topology/server-slot/add", "method": "POST", "body": json.dumps(body, separators=(",", ":"))}]


# The "+" on an engine model's line reserves with no dialog at all: every dialog
# records that it was asked, and the spinner is caught at its first render.
ERC_SETUP = (
    'globalThis.__snap = null; globalThis.__asked = [];'
    ' globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; };'
    ' for (const d of ["appConfirm", "appConfirmChoice", "appPrompt"]) globalThis.__stubReturns["dialogs." + d] = async () => { globalThis.__asked.push(d); return null; };'
)
ERC_RESULT = ('{ calls: calls(), toast: toastText(), asked: globalThis.__asked, reserving: [...rc._reservingCells.entries()], '
              'fresh: [...rc._newReservedCells], snap: globalThis.__snap }')


PINS = [
    # ── remote_actions ──
    # ── create a client by hand ──
    ('add_client_wire',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "  box-a  ";',
     'await (async () => { await rc.addTopologyClient(); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [{"path": "/api/topology/client/create", "method": "POST", "body": "{\\"hostId\\":\\"box-a\\"}"}], "toast": ""}',
     'positive: на провод уходит обрезанный hostId, без выдуманных полей'),
    ('add_client_cancelled',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => null;',
     'await (async () => { await rc.addTopologyClient(); return calls(); })()',
     '[]',
     'negative: отменённый диалог не шлёт ничего'),
    ('add_client_blank',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "   ";',
     'await (async () => { await rc.addTopologyClient(); return calls(); })()',
     '[]',
     'negative: имя из одних пробелов — тоже отмена, а не клиент без имени'),
    ('add_client_refusal_shown',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "dup";'
     ' globalThis.__fetchReply["/api/topology/client/create"] = { __status: 409, error: "client already exists: dup" };',
     'await (async () => { await rc.addTopologyClient(); return toastText(); })()',
     '"Error: client already exists: dup"',
     'as-is: отказ сервера доходит до оператора с приставкой «Error:» — так его печатает toast(String(e))'),
    # ── moving scout clients under the board's ownership ──
    # ── a route's context window ──
    ('route_ctx_number',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => " 8192 ";',
     'await (async () => { await rc.editRouteContext("h","a","primary",0,false); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [{"path": "/api/topology/agent-route/context", "method": "POST", "body": "{\\"hostId\\":\\"h\\",\\"agentId\\":\\"a\\",\\"role\\":\\"primary\\",\\"contextLength\\":\\"8192\\"}"}], "toast": ""}',
     'positive: число уходит обрезанным, оба поля — одно состояние'),
    ('route_ctx_word_refused',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "AUTO";',
     'await (async () => { await rc.editRouteContext("h","a","primary",0,false); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [], "toast": "Enter a number of tokens, or nothing to clear"}',
     'defect-history: слово «auto» больше не режим — галка «модель, если больше» живёт отдельно; слово отклоняется как опечатка'),
    ('route_ctx_number_keeps_switch',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "8192";',
     'await (async () => { await rc.editRouteContext("h","a","primary",0,true); return calls(); })()',
     '[{"path": "/api/topology/agent-route/context", "method": "POST", "body": "{\\"hostId\\":\\"h\\",\\"agentId\\":\\"a\\",\\"role\\":\\"primary\\",\\"contextLength\\":\\"8192\\",\\"contextAuto\\":true}"}]',
     'positive: правка числа при включённой галке шлёт и галку — пропущенное поле сервер читает как «снять»'),
    ('route_ctx_clear_keeps_switch',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "";',
     'await (async () => { await rc.editRouteContext("h","a","primary",8192,true); return calls(); })()',
     '[{"path": "/api/topology/agent-route/context", "method": "POST", "body": "{\\"hostId\\":\\"h\\",\\"agentId\\":\\"a\\",\\"role\\":\\"primary\\",\\"contextAuto\\":true}"}]',
     'positive: снятие числа не снимает галку'),
    ('route_ctx_empty_clears',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "  ";',
     'await (async () => { await rc.editRouteContext("h","a","primary",8192,false); return calls(); })()',
     '[{"path": "/api/topology/agent-route/context", "method": "POST", "body": "{\\"hostId\\":\\"h\\",\\"agentId\\":\\"a\\",\\"role\\":\\"primary\\"}"}]',
     'positive: пусто — это ЯВНОЕ «снять», и на провод уходит именно снятие'),
    ('route_ctx_typo_refused',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "8k";',
     'await (async () => { await rc.editRouteContext("h","a","primary",8192,false); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [], "toast": "Enter a number of tokens, or nothing to clear"}',
     'defect-history: опечатка молча СНИМАЛА настройку и рапортовала успехом — теперь отказ, и ничего не уходит'),
    ('route_ctx_zero_refused',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "0";',
     'await (async () => { await rc.editRouteContext("h","a","primary",8192,false); return calls(); })()',
     '[]',
     'boundary: ноль — не окно в ноль токенов и не «снять»; просят сказать яснее'),
    ('route_ctx_cancelled',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => null;',
     'await (async () => { await rc.editRouteContext("h","a","primary",8192,false); return calls(); })()',
     '[]',
     'negative: отменённый диалог не шлёт ничего'),
    # ── the "model, if larger" checkbox ──
    ('route_ctx_prefer_on',
     '',
     'await (async () => { await rc.setRouteContextPrefer("h","a","primary","8192",true); return calls(); })()',
     '[{"path": "/api/topology/agent-route/context", "method": "POST", "body": "{\\"hostId\\":\\"h\\",\\"agentId\\":\\"a\\",\\"role\\":\\"primary\\",\\"contextLength\\":\\"8192\\",\\"contextAuto\\":true}"}]',
     'positive: включение галки везёт с собой число — на сервере оба поля одно состояние'),
    ('route_ctx_prefer_off_keeps_number',
     '',
     'await (async () => { await rc.setRouteContextPrefer("h","a","primary","8192",false); return calls(); })()',
     '[{"path": "/api/topology/agent-route/context", "method": "POST", "body": "{\\"hostId\\":\\"h\\",\\"agentId\\":\\"a\\",\\"role\\":\\"primary\\",\\"contextLength\\":\\"8192\\"}"}]',
     'positive: выключение галки оставляет число, а галку не шлёт вовсе — отсутствие и есть «выключено»'),
    ('route_ctx_prefer_without_number',
     '',
     'await (async () => { await rc.setRouteContextPrefer("h","a","fallback","",true); return calls(); })()',
     '[{"path": "/api/topology/agent-route/context", "method": "POST", "body": "{\\"hostId\\":\\"h\\",\\"agentId\\":\\"a\\",\\"role\\":\\"fallback\\",\\"contextAuto\\":true}"}]',
     'boundary: числа нет — уходит одна галка, без contextLength'),
    ('route_ctx_prefer_server_refuses',
     'globalThis.__fetchReply["/api/topology/agent-route/context"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.setRouteContextPrefer("h","a","primary","8192",true); return toastText(); })()',
     '"Error: nope"',
     'negative: отказ сервера доходит до оператора тостом'),
    ('ntp_default_empty',
     '',
     'rc.nextTopologyCellPort()',
     '22001',
     'positive: nextTopologyCellPort: пустая топология → 22001 (from по умолчанию из cellPortRange)'),
    ('ntp_gap_fill',
     'st.topology.nodes = [{ servers: [{ port: 22001 }, { port: 22003 }] }];',
     'rc.nextTopologyCellPort()',
     '22002',
     'positive: nextTopologyCellPort: заняты 22001 и 22003 → дыра 22002 заполняется'),
    ('ntp_proxy_blocks_gap',
     'st.topology.nodes = [{ servers: [{ port: 22001 }, { port: 22003 }] }]; st.topology.proxies = [{ port: 22002 }];',
     'rc.nextTopologyCellPort()',
     '22004',
     'defect-history: nextTopologyCellPort (4bfeeab): прокси держит 22002 → объединение портов ячеек и прокси → 22004'),
    ('ntp_string_ports_count',
     'st.topology.nodes = [{ servers: [{ port: "22001" }] }]; st.topology.proxies = [{ port: "22002" }];',
     'rc.nextTopologyCellPort()',
     '22003',
     'boundary: nextTopologyCellPort: строковые порты ячейки и прокси тоже считаются занятыми → 22003'),
    ('ntp_bad_ports_ignored',
     'st.topology.nodes = [{ servers: [{ port: 0 }, { port: "abc" }, {}] }]; st.topology.proxies = [{}];',
     'rc.nextTopologyCellPort()',
     '22001',
     'negative: nextTopologyCellPort: порт 0 / "abc" / отсутствующий не занимают ничего → 22001'),
    ('ntp_proxy_only_at_from',
     'st.topology.proxies = [{ port: 22001 }];',
     'rc.nextTopologyCellPort()',
     '22002',
     'positive: nextTopologyCellPort: прокси на самом from → 22002 (без единой ячейки)'),
    ('ntp_range_override',
     'st.topology.cellPortRange = { from: 30001, to: 30999 };',
     'rc.nextTopologyCellPort()',
     '30001',
     'positive: cellPortRange: диапазон берётся из topology.cellPortRange (не из state) → from=30001'),
    ('ntp_range_zero_falls_back',
     'st.topology.cellPortRange = { from: 0 };',
     'rc.nextTopologyCellPort()',
     '22001',
     'boundary: cellPortRange: from=0 ложный → дефолт 22001'),
    ('ntp_range_to_not_enforced',
     'st.topology.cellPortRange = { from: 22001, to: 22002 }; st.topology.nodes = [{ servers: [{ port: 22001 }, { port: 22002 }] }];',
     'rc.nextTopologyCellPort()',
     '22003',
     'as-is: КАК ЕСТЬ: верхняя граница `to` не проверяется — при полном диапазоне 22001–22002 выдаётся 22003'),
    ('fse_client_match_string_port',
     'st.topology.server = { llamaServers: [{ port: 22001, clientId: "h1", tag: "a" }] };',
     'rc.findSlotEntry("h1", "22001") ?? null',
     '{"port": 22001, "clientId": "h1", "tag": "a"}',
     'positive: findSlotEntry: числовой port записи и строковый запрос совпадают по String() → запись (undefined приводится к null через ??)'),
    ('fse_wrong_host',
     'st.topology.server = { llamaServers: [{ port: 22001, clientId: "h1" }] };',
     'rc.findSlotEntry("h2", 22001) ?? null',
     'null',
     'negative: findSlotEntry: другой хост → undefined (null через ??)'),
    ('fse_wrong_port',
     'st.topology.server = { llamaServers: [{ port: 22001, clientId: "h1" }] };',
     'rc.findSlotEntry("h1", 22002) ?? null',
     'null',
     'negative: findSlotEntry: другой порт → undefined (null через ??)'),
    ('fse_controller_id_is_no_host',
     'st.topology.server = { llamaServers: [{ port: 22002, tag: "local" }, { port: 22001, clientId: "h1" }] };',
     '[rc.findSlotEntry("controller", 22002) ?? null, rc.findSlotEntry("controller", 22001) ?? null]',
     '[null, null]',
     'negative: findSlotEntry: id контроллера — не машина: запись без clientId (ячейка контроллера до шага 6.9) им больше не находится, и чужая запись того же порта — тоже'),
    ('fse_client_skips_controller_entry',
     'st.topology.server = { llamaServers: [{ port: 22001, clientId: "" }] };',
     'rc.findSlotEntry("h1", 22001) ?? null',
     'null',
     'negative: findSlotEntry: клиент не видит контроллерную запись (clientId "") того же порта'),
    ('fse_no_server_block',
     '',
     'rc.findSlotEntry("h1", 22001) ?? null',
     'null',
     'negative: findSlotEntry: topology.server отсутствует → undefined без броска'),
    ('fse_first_duplicate_wins',
     'st.topology.server = { llamaServers: [{ port: 22001, clientId: "h1", tag: "first" }, { port: 22001, clientId: "h1", tag: "second" }] };',
     'rc.findSlotEntry("h1", 22001) ?? null',
     '{"port": 22001, "clientId": "h1", "tag": "first"}',
     'boundary: findSlotEntry: при дубликатах возвращается первая запись'),
    ('csa_stop_wire_and_state',
     '',
     'await (async () => { await rc.cellServiceAction("h1", "22001", "stop"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("h1:22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001,\\"action\\":\\"stop\\"}"}], "toast": "", "pending": "stop", "stopping": ["h1:22001"]}',
     'defect-history: cellServiceAction (87f5ea7): stop — на провод {hostId, port:22001 (Number из строки), action}; сразу после await pending="stop" и _stoppingCells держат ключ (их снимет таймер 1200 мс); тоста нет'),
    ('csa_start_clears_pending',
     '',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "start"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("h1:22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001,\\"action\\":\\"start\\"}"}], "toast": "", "pending": null, "stopping": []}',
     'defect-history: cellServiceAction: start — pending снят сразу после ответа, _stoppingCells пуст, тоста нет'),
    ('csa_boot_clears_pending',
     '',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "boot"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("h1:22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001,\\"action\\":\\"boot\\"}"}], "toast": "", "pending": null, "stopping": []}',
     'positive: cellServiceAction: boot идёт по ветке start — pending снят сразу'),
    ('csa_library_model_starts_like_any',
     'globalThis.__asked = []; globalThis.__stubReturns["dialogs.appConfirm"] = async (text) => { globalThis.__asked.push(text); return true; };'
     ' globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: true, bringing: { id: "mv-1" } };',
     r'''await (async () => {
       const handlers = [];
       const btn = { dataset: { nodeCellLaunch: "h1", nodeCellPort: "22001", nodeCellRunner: "llama-server",
                                nodeCellLibrary: "NAS", nodeCellLibraryFiles: "model, mmproj" },
                     closest: () => null, addEventListener: (ev, fn) => handlers.push(fn) };
       const root = { querySelectorAll: (sel) => (sel === "[data-node-cell-launch]" ? [btn] : []) };
       // The vram hover binds once per page, on the body's dataset.
       document.body ||= {}; document.body.dataset ||= { vramHoverBound: "1" };
       rc.bindServerSlotControls(root);
       await handlers[0]();
       for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
       return ({ asked: globalThis.__asked, body: calls().map((c) => c.body), toast: toastText(), choose: typeof rc.askWhereFrom }); })()''',
     json.dumps({"asked": [en("dlgStartPort", port="22001")],
                 "body": [json.dumps({"hostId": "h1", "port": 22001, "action": "start"}, separators=(",", ":"))],
                 "toast": "", "choose": "undefined"}, ensure_ascii=False),
     'negative: ▶ у ячейки с моделью в библиотеке — обычное подтверждение старта, без вопроса «с диска или из '
     'библиотеки» и без поля modelFrom на проводе: ответ читали только ячейки контроллера, скаут читает модель на '
     'месте; и ответ сервера «везу модель» больше ничего не говорит'),
    ('csa_engine_cell_start_speaks_of_the_model',
     'globalThis.__asked = []; globalThis.__stubReturns["dialogs.appConfirm"] = async (text) => { globalThis.__asked.push(text); return false; };'
     ' st.setState({ config: {}, runners: [{ id: "llama-server" }, { id: "custom" }, { id: "ollama", engineCell: true }], artifacts: [], models: [], paths: {} });',
     r'''await (async () => {
       const ask = async (runner, model) => {
         const handlers = [];
         const article = { querySelector: () => (model ? { textContent: ` ${model} ` } : null) };
         const btn = { dataset: { nodeCellLaunch: "h1", nodeCellPort: "22031", nodeCellRunner: runner },
                       closest: () => article, addEventListener: (ev, fn) => handlers.push(fn) };
         const root = { querySelectorAll: (sel) => (sel === "[data-node-cell-launch]" ? [btn] : []) };
         document.body ||= {}; document.body.dataset ||= { vramHoverBound: "1" };
         rc.bindServerSlotControls(root);
         await handlers[0]();
       };
       await ask("ollama", "qwen3:8b"); await ask("custom", "bash run.sh"); await ask("lmstudio", "m");
       return { asked: globalThis.__asked, calls: calls() }; })()''',
     json.dumps({"asked": [en("dlgStartModel", model="qwen3:8b", port="22031"), en("dlgStartCommand", port="22031"),
                           en("dlgStartCommand", port="22031")], "calls": []}, ensure_ascii=False),
     'positive: ▶ у ячейки в Ollama спрашивает о её модели — модель загрузится в память (движка); negative: у командной '
     'ячейки — о команде, как прежде; раннер, которого реестр не называет ячейкой движка (lmstudio здесь), — тоже о команде; '
     'отказ в диалоге — ни одного запроса'),
    ('csa_port_nan_body',
     '',
     'await (async () => { await rc.cellServiceAction("h1", "abc", "start"); return { calls: calls(), pending: rc._pendingCellActions.get("h1:abc") ?? null }; })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":null,\\"action\\":\\"start\\"}"}], "pending": null}',
     'as-is: КАК ЕСТЬ: нечисловой порт → Number("abc")=NaN → на провод уходит port:null, запрос не блокируется'),
    ('csa_reply_busy_hint',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, error: "slot already in progress" };',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "start"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("h1:22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001,\\"action\\":\\"start\\"}"}], "toast": "⚠️ slot already in progress — this host runs one server slot at a time — wait for the current start to finish", "pending": null, "stopping": []}',
     'defect-history: cellServiceAction: ответ ok:false с «already/in progress» → тост с ошибкой И подсказкой cellSlotBusyHint'),
    ('csa_reply_busy_case_insensitive',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, error: "Already Running here" };',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "start"); return toastText(); })()',
     '"⚠️ Already Running here — this host runs one server slot at a time — wait for the current start to finish"',
     'boundary: cellServiceAction: регэксп busy нечувствителен к регистру («Already Running») → подсказка добавлена'),
    ('csa_reply_plain_error',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, error: "boom" };',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "start"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("h1:22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001,\\"action\\":\\"start\\"}"}], "toast": "⚠️ boom", "pending": null, "stopping": []}',
     'negative: cellServiceAction: ответ ok:false «boom» → тост «⚠️ boom» без подсказки busy'),
    ('csa_reply_result_error_precedence',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, result: { error: "nested" }, error: "outer" };',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "start"); return toastText(); })()',
     '"⚠️ nested"',
     'positive: cellServiceAction: result.error имеет приоритет над error верхнего уровня'),
    ('csa_reply_false_no_text',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false };',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "start"); return toastText(); })()',
     '"⚠️ the action failed"',
     'boundary: cellServiceAction: ok:false без текста → t("cellActionFailed")'),
    ('csa_reply_ok_missing_no_toast',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { result: "whatever" };',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "start"); return toastText(); })()',
     '""',
     'negative: cellServiceAction: ответ без поля ok (не === false) → тоста нет'),
    ('csa_stop_reply_error_keeps_pending',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, error: "boom" };',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "stop"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("h1:22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001,\\"action\\":\\"stop\\"}"}], "toast": "⚠️ boom", "pending": "stop", "stopping": ["h1:22001"]}',
     'as-is: КАК ЕСТЬ: агент отверг stop (ok:false), но pending/_stoppingCells всё равно висят до таймера 1200 мс — тост «⚠️ boom» при занятых кнопках'),
    ('csa_throw_500_start',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "start"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("h1:22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001,\\"action\\":\\"start\\"}"}], "toast": "Error: nope", "pending": null, "stopping": []}',
     'negative: cellServiceAction: api бросил (500 «nope») → catch: тост «Error: nope», pending и stopping очищены'),
    ('csa_throw_500_stop',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.cellServiceAction("h1", 22001, "stop"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("h1:22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001,\\"action\\":\\"stop\\"}"}], "toast": "Error: nope", "pending": null, "stopping": []}',
     'negative: cellServiceAction: stop при 500 → catch снимает _stoppingCells и pending немедленно (без таймера), тост «Error: nope»'),
    ('dss_success',
     '',
     'await (async () => { await rc.deleteServerSlot("h1", "22001"); return { calls: calls(), toast: toastText(), deleting: [...rc._deletingSlots] }; })()',
     '{"calls": [{"path": "/api/topology/server-slot/delete", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001}"}], "toast": "", "deleting": []}',
     'positive: deleteServerSlot: на провод {hostId, port:22001 (Number)}; после успеха _deletingSlots пуст, тоста нет'),
    ('dss_deleting_set_before_wire',
     'globalThis.__snap = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._deletingSlots]; };',
     'await (async () => { await rc.deleteServerSlot("h1", 22001); return globalThis.__snap; })()',
     '["h1:22001"]',
     'positive: deleteServerSlot: ключ h1:22001 лежит в _deletingSlots уже на первом renderTopology — до запроса'),
    ('dss_error_500',
     'globalThis.__fetchReply["/api/topology/server-slot/delete"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.deleteServerSlot("h1", 22001); return { calls: calls(), toast: toastText(), deleting: [...rc._deletingSlots] }; })()',
     '{"calls": [{"path": "/api/topology/server-slot/delete", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"port\\":22001}"}], "toast": "Error: nope", "deleting": []}',
     'as-is: КАК ЕСТЬ: при 500 ключ снят, а тост показывает сырой String(Error) — «Error: nope»'),
    ('rsc_yes_reply_cell',
     'globalThis.__snap = null; globalThis.__msg = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; }; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; globalThis.__fetchReply["/api/topology/server-slot/add"] = { cell: { hostId: "h1", port: 22007 } };',
     'await (async () => { await rc.reserveServerCell("h1"); return ({ calls: calls(), toast: toastText(), reserving: [...rc._reservingCells.entries()], fresh: [...rc._newReservedCells], snap: globalThis.__snap, confirm: globalThis.__msg }); })()',
     '{"calls": [{"path": "/api/topology/server-slot/add", "method": "POST", "body": "{\\"hostId\\":\\"h1\\"}"}], "toast": "", "reserving": [], "fresh": ["h1:22007"], "snap": [["h1", {"port": 22001, "startedAt": 1700000100000}]], "confirm": {"msg": "Reserve cell :22001? The port is claimed fleet-wide; the cell can be configured and started later.", "opts": {"danger": false, "confirmLabel": "Reserve cell", "scene": "create"}}}',
     'positive: reserveServerCell: до запроса _reservingCells h1→{port:22001, startedAt: замороженный Date.now 1700000100 с}; на провод {hostId}; ответ cell → _newReservedCells «h1:22007»; после await _reservingCells пуст; текст диалога'),
    ('rsc_yes_reply_slot_alias',
     'globalThis.__snap = null; globalThis.__msg = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; }; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; globalThis.__fetchReply["/api/topology/server-slot/add"] = { slot: { hostId: "h1", port: 22008 } };',
     'await (async () => { await rc.reserveServerCell("h1"); return [...rc._newReservedCells]; })()',
     '["h1:22008"]',
     'positive: reserveServerCell: ответ с полем slot (вместо cell) тоже принимается → «h1:22008»'),
    ('rsc_yes_reply_empty_falls_back',
     'globalThis.__snap = null; globalThis.__msg = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; }; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; };',
     'await (async () => { await rc.reserveServerCell("h1"); return { fresh: [...rc._newReservedCells], reserving: [...rc._reservingCells.entries()] }; })()',
     '{"fresh": ["h1:22001"], "reserving": []}',
     'boundary: reserveServerCell: ответ {ok:true} без cell/slot → ключ из hostId и pendingPort «h1:22001»'),
    ('rsc_porthint_wins',
     'globalThis.__snap = null; globalThis.__msg = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; }; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; st.topology.nodes = [{ servers: [{ port: 22001 }] }];',
     'await (async () => { await rc.reserveServerCell("h1", "22010"); return { snap: globalThis.__snap, confirm: globalThis.__msg.msg, fresh: [...rc._newReservedCells] }; })()',
     '{"snap": [["h1", {"port": 22010, "startedAt": 1700000100000}]], "confirm": "Reserve cell :22010? The port is claimed fleet-wide; the cell can be configured and started later.", "fresh": ["h1:22010"]}',
     'positive: reserveServerCell: portHint "22010" побеждает nextTopologyCellPort в диалоге, в _reservingCells (startedAt = замороженный Date.now) и в fallback-ключе'),
    ('rsc_no_hint_uses_next',
     'globalThis.__snap = null; globalThis.__msg = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; }; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; st.topology.nodes = [{ servers: [{ port: 22001 }] }];',
     'await (async () => { await rc.reserveServerCell("h1"); return { snap: globalThis.__snap, confirm: globalThis.__msg.msg, fresh: [...rc._newReservedCells] }; })()',
     '{"snap": [["h1", {"port": 22002, "startedAt": 1700000100000}]], "confirm": "Reserve cell :22002? The port is claimed fleet-wide; the cell can be configured and started later.", "fresh": ["h1:22002"]}',
     'negative: reserveServerCell: без portHint порт = nextTopologyCellPort (22001 занят → 22002); startedAt = замороженный Date.now'),
    ('rsc_no',
     'globalThis.__snap = null; globalThis.__msg = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; }; globalThis.__stubReturns["dialogs.appConfirm"] = async () => false;',
     'await (async () => { await rc.reserveServerCell("h1"); return ({ calls: calls(), toast: toastText(), reserving: [...rc._reservingCells.entries()], fresh: [...rc._newReservedCells], snap: globalThis.__snap, confirm: globalThis.__msg }); })()',
     '{"calls": [], "toast": "", "reserving": [], "fresh": [], "snap": null, "confirm": null}',
     'negative: reserveServerCell: отказ в диалоге → ни запроса, ни рендера, ни состояния'),
    ('rsc_500',
     'globalThis.__snap = null; globalThis.__msg = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; }; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; globalThis.__fetchReply["/api/topology/server-slot/add"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.reserveServerCell("h1"); return ({ calls: calls(), toast: toastText(), reserving: [...rc._reservingCells.entries()], fresh: [...rc._newReservedCells], snap: globalThis.__snap, confirm: globalThis.__msg }); })()',
     '{"calls": [{"path": "/api/topology/server-slot/add", "method": "POST", "body": "{\\"hostId\\":\\"h1\\"}"}], "toast": "Error: nope", "reserving": [], "fresh": [], "snap": [["h1", {"port": 22001, "startedAt": 1700000100000}]], "confirm": {"msg": "Reserve cell :22001? The port is claimed fleet-wide; the cell can be configured and started later.", "opts": {"danger": false, "confirmLabel": "Reserve cell", "scene": "create"}}}',
     'negative: reserveServerCell: 500 → _reservingCells снят, _newReservedCells пуст, тост «Error: nope» (startedAt в снимке = замороженный Date.now)'),
    ('rsc_empty_host',
     'globalThis.__snap = null; globalThis.__msg = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._reservingCells.entries()]; }; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; };',
     'await (async () => { await rc.reserveServerCell(""); return ({ calls: calls(), toast: toastText(), reserving: [...rc._reservingCells.entries()], fresh: [...rc._newReservedCells], snap: globalThis.__snap, confirm: globalThis.__msg }); })()',
     '{"calls": [{"path": "/api/topology/server-slot/add", "method": "POST", "body": "{\\"hostId\\":\\"\\"}"}], "toast": "", "reserving": [], "fresh": [], "snap": [], "confirm": {"msg": "Reserve cell :22001? The port is claimed fleet-wide; the cell can be configured and started later.", "opts": {"danger": false, "confirmLabel": "Reserve cell", "scene": "create"}}}',
     'as-is: КАК ЕСТЬ: пустой hostId не блокируется — диалог показан, на провод {hostId:""}, ни спиннера, ни вспышки новой ячейки'),
    # ── reserve: where the new cell runs, and an engine cell's model (2026-09-25) ──
    ('rsc_engines_where_caravan',
     RSC_ENGINES + ' globalThis.__answers = [""];',
     RSC_RUN,
     json.dumps({"calls": rsc_add({"hostId": "h1"}), "toast": "", "asks": [RSC_WHERE], "confirm": None, "reserving": [],
                 "fresh": ["h1:22001"], "snap": [["h1", {"port": 22001, "startedAt": 1700000100000}]]}),
     'positive: машина сообщает движки — первый шаг спрашивает, где работает ячейка: Caravan (он нажат первым), Ollama, '
     'LM Studio с пометкой «не готов»; foo не предложен — он не раннер ячеек движка; выбран Caravan — на провод прежний '
     '{hostId}, старый диалог не звали'),
    ('rsc_engine_model_chosen',
     RSC_ENGINES + ' globalThis.__answers = ["ollama", "qwen2.5:0.5b"]; globalThis.__fetchReply["/api/topology/server-slot/add"] = { cell: { hostId: "h1", port: 22001 } };',
     RSC_RUN,
     json.dumps({"calls": rsc_add({"hostId": "h1", "engine": "ollama", "model": "qwen2.5:0.5b"}), "toast": "",
                 "asks": [RSC_WHERE, RSC_MODEL], "confirm": None, "reserving": [], "fresh": ["h1:22001"],
                 "snap": [["h1", {"port": 22001, "startedAt": 1700000100000}]]}),
     'positive: выбран Ollama — второй шаг: модели движка списком (имя · параметры · квант, облачная — ☁), заголовок с '
     'портом, текст с именем движка; на провод {hostId, engine, model}'),
    ('rsc_engine_not_ready_sent_bare',
     RSC_ENGINES + ' globalThis.__answers = ["lmstudio"]; globalThis.__fetchReply["/api/topology/server-slot/add"] = { __status: 409, error: "LM Studio is not running on this machine — start its server first" };',
     RSC_RUN,
     json.dumps({"calls": rsc_add({"hostId": "h1", "engine": "lmstudio"}),
                 "toast": "Error: LM Studio is not running on this machine — start its server first",
                 "asks": [RSC_WHERE], "confirm": None, "reserving": [], "fresh": [],
                 "snap": [["h1", {"port": 22001, "startedAt": 1700000100000}]]}),
     'negative: движок не готов — выбирать модель не из чего, запрос уходит без неё, и причину говорит контроллер (тост его '
     'словами), а не вторая копия правила на доске'),
    ('rsc_engine_ok_no_models',
     RSC_ENGINES + ' globalThis.__answers = ["ollama"]; st.topology.nodes[0].engines[0].models = [];',
     RSC_RUN,
     json.dumps({"calls": rsc_add({"hostId": "h1", "engine": "ollama"}), "toast": "", "asks": [RSC_WHERE],
                 "confirm": None, "reserving": [], "fresh": ["h1:22001"],
                 "snap": [["h1", {"port": 22001, "startedAt": 1700000100000}]]}),
     'boundary: движок работает, но моделей нет — второго шага нет, запрос без модели (контроллер скажет «скачайте»)'),
    ('rsc_engine_model_cancel',
     RSC_ENGINES + ' globalThis.__answers = ["ollama", null];',
     RSC_RUN,
     json.dumps({"calls": [], "toast": "", "asks": [RSC_WHERE, RSC_MODEL], "confirm": None, "reserving": [], "fresh": [],
                 "snap": None}),
     'negative: отмена на шаге модели — ни запроса, ни спиннера, ни рендера'),
    ('rsc_engine_where_cancel',
     RSC_ENGINES + ' globalThis.__answers = [null];',
     RSC_RUN,
     json.dumps({"calls": [], "toast": "", "asks": [RSC_WHERE], "confirm": None, "reserving": [], "fresh": [], "snap": None}),
     'negative: отмена на шаге «где» — второго шага нет, ни запроса, ни состояния'),
    ('rsc_no_engine_cells_old_dialog',
     RSC_ENGINES + ' globalThis.__answers = []; st.topology.nodes[0].engines = st.topology.nodes[0].engines.slice(2);',
     'await (async () => { await rc.reserveServerCell("h1"); return { calls: calls(), asks: globalThis.__asks, confirm: globalThis.__msg }; })()',
     json.dumps({"calls": rsc_add({"hostId": "h1"}), "asks": [], "confirm": {"msg": en("dlgReserveCell", port=22001), "opts": RSC_ASK}}),
     'negative: у машины только движок, в котором ячейка не живёт (foo) — прежний диалог без выбора'),
    ('rsc_registry_without_engine_cells',
     RSC_ENGINES + ' globalThis.__answers = []; st.setState({ config: {}, runners: [{ id: "llama-server" }, { id: "ollama" }], artifacts: [], models: [], paths: {} });',
     'await (async () => { await rc.reserveServerCell("h1"); return { asks: globalThis.__asks.length, confirm: !!globalThis.__msg, engines: rc.reserveEngines("h1") }; })()',
     '{"asks": 0, "confirm": true, "engines": []}',
     'negative: реестр контроллера не называет раннеров ячеек движка — движки не предлагаются, хотя скаут их видит'),
    ('rsc_other_machine_engines',
     RSC_ENGINES + ' globalThis.__answers = [];',
     'await (async () => { await rc.reserveServerCell("h2"); return { asks: globalThis.__asks.length, confirm: !!globalThis.__msg, engines: rc.reserveEngines("h2").length, mine: rc.reserveEngines("h1").map((e) => e.kind) }; })()',
     '{"asks": 0, "confirm": true, "engines": 0, "mine": ["ollama", "lmstudio"]}',
     'negative: движки чужой машины не предлагаются — у h2 своих нет, прежний диалог'),
    ('dtca_yes_named',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; st.topology.clients = [{ id: "c1", agents: [{ id: "a1", name: "Scout" }] }];',
     'await (async () => { await rc.deleteTopologyClientAgent("c1", "a1"); return { calls: calls(), toast: toastText(), confirm: globalThis.__msg }; })()',
     '{"calls": [{"path": "/api/topology/client/agent/delete", "method": "POST", "body": "{\\"clientId\\":\\"c1\\",\\"agentId\\":\\"a1\\"}"}], "toast": "Removed Scout", "confirm": {"msg": "Delete agent “Scout” from the list?", "opts": {"confirmLabel": "Delete"}}}',
     'positive: deleteTopologyClientAgent: диалог с именем агента «Scout», на провод {clientId, agentId}; обещания «вернётся с heartbeat» больше нет — вернуть его некому'),
    ('dtca_ports_named',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; st.topology.clients = [{ id: "c1", agents: [{ id: "a1", name: "Scout" }, { id: "a2", name: "Other" }] }]; st.topology.assignments = { c1: { assignments: [{ agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23001" }, { role: "fallback", proxyId: "skynet:proxy:23002" }] }, { agentId: "a2", routes: [{ role: "primary", proxyId: "skynet:proxy:23009" }] }] } }; globalThis.__fetchReply["/api/topology/client/agent/delete"] = { ok: true, freedPorts: [23001] };',
     'await (async () => { await rc.deleteTopologyClientAgent("c1", "a1"); return { toast: toastText(), confirm: globalThis.__msg.msg }; })()',
     '{"toast": "Removed Scout; freed ports: :23001", "confirm": "Delete agent “Scout” from the list?\\n\\nIts ports :23001 :23002 stay free: bind them to another agent, or delete them in the port\'s window."}',
     'positive: у агента есть порты — диалог называет его порты (оба, по порядку ролей, без чужого :23009) и говорит, что они останутся; тост — какие порты больше никто не держит'),
    ('dtca_ports_other_agent_only',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return false; }; st.topology.clients = [{ id: "c1", agents: [{ id: "a1", name: "Scout" }] }]; st.topology.assignments = { c1: { assignments: [{ agentId: "a2", routes: [{ role: "primary", proxyId: "skynet:proxy:23009" }] }] }, c2: { assignments: [{ agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23011" }] }] } };',
     'await (async () => { await rc.deleteTopologyClientAgent("c1", "a1"); return { calls: calls(), confirm: globalThis.__msg.msg, ports: rc.savedAgentPorts("c1", "a1"), missing: rc.savedAgentPorts("nope", "a1") }; })()',
     '{"calls": [], "confirm": "Delete agent “Scout” from the list?", "ports": [], "missing": []}',
     'negative: порты чужого агента и агента с тем же id у другого клиента — не его; нет записи — нет портов, диалог короткий'),
    ('dtca_yes_unknown_uses_id',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; st.topology.clients = [{ id: "c1" }];',
     'await (async () => { await rc.deleteTopologyClientAgent("c1", "a7"); return { calls: calls(), confirm: globalThis.__msg.msg }; })()',
     '{"calls": [{"path": "/api/topology/client/agent/delete", "method": "POST", "body": "{\\"clientId\\":\\"c1\\",\\"agentId\\":\\"a7\\"}"}], "confirm": "Delete agent “a7” from the list?"}',
     'boundary: deleteTopologyClientAgent: агент не найден → в диалоге его id'),
    ('dtca_no',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return false; };',
     'await (async () => { await rc.deleteTopologyClientAgent("c1", "a1"); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [], "toast": ""}',
     'negative: deleteTopologyClientAgent: отказ → ничего'),
    ('dtca_500',
     'globalThis.__fetchReply["/api/topology/client/agent/delete"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.deleteTopologyClientAgent("c1", "a1"); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [{"path": "/api/topology/client/agent/delete", "method": "POST", "body": "{\\"clientId\\":\\"c1\\",\\"agentId\\":\\"a1\\"}"}], "toast": "Error: nope"}',
     'negative: deleteTopologyClientAgent: 500 → тост «Error: nope»'),
    ('sls_yes_named',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; st.topology.hosts = [{ id: "h1", name: "Box A" }]; rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 });',
     'await (async () => { await rc.submitLlamaStop("h1"); return ({ calls: calls(), toast: toastText(), stoppingHosts: [...rc._stoppingHosts], pending: [...rc._pendingRemoteStarts.keys()], confirm: globalThis.__msg }); })()',
     '{"calls": [{"path": "/api/topology/client-llama/stop", "method": "POST", "body": "{\\"hostId\\":\\"h1\\"}"}], "toast": "", "stoppingHosts": ["h1"], "pending": [], "confirm": {"msg": "Stop llama-server on Box A?\\n\\nThe model will be unloaded from VRAM. The admin panel stays up.", "opts": {"confirmLabel": "Stop", "scene": "stop"}}}',
     'positive: submitLlamaStop: диалог с именем машины «Box A» из её записи хоста; pending-старт h1 снят; на провод {hostId}; после await _stoppingHosts ещё держит h1 (таймер 1500 мс); тоста нет'),
    ('sls_no',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return false; }; rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 });',
     'await (async () => { await rc.submitLlamaStop("h1"); return ({ calls: calls(), toast: toastText(), stoppingHosts: [...rc._stoppingHosts], pending: [...rc._pendingRemoteStarts.keys()], confirm: globalThis.__msg }); })()',
     '{"calls": [], "toast": "", "stoppingHosts": [], "pending": ["h1"], "confirm": {"msg": "Stop llama-server on h1?\\n\\nThe model will be unloaded from VRAM. The admin panel stays up.", "opts": {"confirmLabel": "Stop", "scene": "stop"}}}',
     'negative: submitLlamaStop: отказ → нет запроса, pending-старт остаётся, имя в диалоге = hostId (хоста нет)'),
    ('sls_names_the_host_not_the_client',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return false; }; st.topology.clients = [{ id: "h1", name: "Client name" }];',
     'await (async () => { await rc.submitLlamaStop("h1"); return globalThis.__msg.msg.split("?")[0]; })()',
     '"Stop llama-server on h1"',
     'negative: клиент с тем же id — запись оператора, не машина: ячейки стоят на хосте, и имя берётся из записи хоста'),
    ('sls_500_silent',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; globalThis.__fetchReply["/api/topology/client-llama/stop"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.submitLlamaStop("h1"); return ({ calls: calls(), toast: toastText(), stoppingHosts: [...rc._stoppingHosts], pending: [...rc._pendingRemoteStarts.keys()], confirm: globalThis.__msg }); })()',
     '{"calls": [{"path": "/api/topology/client-llama/stop", "method": "POST", "body": "{\\"hostId\\":\\"h1\\"}"}], "toast": "", "stoppingHosts": [], "pending": [], "confirm": {"msg": "Stop llama-server on h1?\\n\\nThe model will be unloaded from VRAM. The admin panel stays up.", "opts": {"confirmLabel": "Stop", "scene": "stop"}}}',
     'as-is: КАК ЕСТЬ: 500 при остановке проглатывается — _stoppingHosts снят, но тоста НЕТ (catch(_) без toast)'),
    ('rprs_entry_frozen',
     '',
     '(rc.registerPendingRemoteStart({ hostId: "h1", port: 22001, modelName: "m" }), rc._pendingRemoteStarts.get("h1"))',
     '{"phase": "starting", "startedAt": 1700000100000, "hostId": "h1", "port": 22001, "modelName": "m"}',
     'positive: registerPendingRemoteStart: запись phase=starting, startedAt = замороженный Date.now (1700000100 с), поля info'),
    ('rprs_info_phase_overrides_default',
     '',
     '(rc.registerPendingRemoteStart({ hostId: "h1", phase: "downloading", startedAt: 5 }), rc._pendingRemoteStarts.get("h1"))',
     '{"phase": "downloading", "startedAt": 5, "hostId": "h1"}',
     'as-is: КАК ЕСТЬ: ...info идёт после дефолтов — phase/startedAt из info перекрывают «starting»/Date.now'),
    ('rsif_empty_false',
     '',
     'rc.remoteStartupInFlight()',
     'false',
     'negative: remoteStartupInFlight: ничего не стартует → false'),
    ('rsif_pending_true',
     'rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 });',
     'rc.remoteStartupInFlight()',
     'true',
     'positive: remoteStartupInFlight: есть pending phase=starting → true'),
    ('rsif_false_after_clear',
     'rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 }); rc.clearPendingRemoteStart("h1");',
     '({ inFlight: rc.remoteStartupInFlight(), size: rc._pendingRemoteStarts.size })',
     '{"inFlight": false, "size": 0}',
     'negative: clearPendingRemoteStart: после очистки → false, карта пуста'),
    ('rsif_pending_timeout_phase_false',
     'rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 }); rc._pendingRemoteStarts.get("h1").phase = "timeout";',
     'rc.remoteStartupInFlight()',
     'false',
     'boundary: remoteStartupInFlight: pending с phase=timeout не считается стартующим → false'),
    ('rsif_server_startup_phases',
     '',
     '["resolving", "downloading", "loading", "running", "stopped", "error"].map((ph) => { st.topology.server = { llamaServers: [{ isRemote: true, phase: ph }] }; return ph + "=" + rc.remoteStartupInFlight(); })',
     '["resolving=true", "downloading=true", "loading=true", "running=false", "stopped=false", "error=false"]',
     'boundary: remoteStartupInFlight: удалённый сервер в resolving/downloading/loading → true; running/stopped/error → false'),
    ('rsif_server_not_remote_false',
     'st.topology.server = { llamaServers: [{ isRemote: false, phase: "downloading" }] };',
     'rc.remoteStartupInFlight()',
     'false',
     'negative: remoteStartupInFlight: локальный (isRemote:false) сервер в downloading не считается → false'),
    ('nsch_no_pending_empty',
     '',
     'rc.nodeStartingCardHtml({ id: "h1", ip: "10.0.0.9" })',
     '""',
     'negative: nodeStartingCardHtml: без pending-старта → ""'),
    ('nsch_other_host_pending_empty',
     'rc.registerPendingRemoteStart({ hostId: "h2", port: 22001 });',
     'rc.nodeStartingCardHtml({ id: "h1", ip: "10.0.0.9" })',
     '""',
     'negative: nodeStartingCardHtml: pending на другом хосте → ""'),
    ('nsch_card_full',
     'rc.registerPendingRemoteStart({ hostId: "h1", port: 22001, modelName: "m", clientIp: "10.0.0.5" });',
     'norm(rc.nodeStartingCardHtml({ id: "h1", ip: "10.0.0.9", servers: [] }))',
     '"<article class=\\"node-server loading\\" data-pending-remote-start=\\"h1\\"> <div class=\\"node-server-head\\"> <span class=\\"topology-spinner\\" aria-hidden=\\"true\\"></span> <span class=\\"topology-addr-link\\" style=\\"pointer-events:none\\">10.0.0.5:22001</span> <span class=\\"pill warn\\">loading</span> <span style=\\"flex:1\\"></span> <button class=\\"mini-link\\" type=\\"button\\" data-pending-remote-dismiss=\\"h1\\" style=\\"color:var(--muted,#888)\\" title=\\"Dismiss\\">✕</button> </div> <div class=\\"topology-muted\\" style=\\"font-size:12px;padding:2px 0\\">m</div> <div class=\\"topology-muted\\" style=\\"font-size:11px\\">starting…</div> </article>"',
     'positive: nodeStartingCardHtml: полная карточка — clientIp:port, pill loading, кнопка ✕, строка модели, «starting…»'),
    ('nsch_card_minimal_node_ip',
     'rc.registerPendingRemoteStart({ hostId: "h1" });',
     'norm(rc.nodeStartingCardHtml({ id: "h1", ip: "10.0.0.9" }))',
     '"<article class=\\"node-server loading\\" data-pending-remote-start=\\"h1\\"> <div class=\\"node-server-head\\"> <span class=\\"topology-spinner\\" aria-hidden=\\"true\\"></span> <span class=\\"topology-addr-link\\" style=\\"pointer-events:none\\">10.0.0.9</span> <span class=\\"pill warn\\">loading</span> <span style=\\"flex:1\\"></span> <button class=\\"mini-link\\" type=\\"button\\" data-pending-remote-dismiss=\\"h1\\" style=\\"color:var(--muted,#888)\\" title=\\"Dismiss\\">✕</button> </div> <div class=\\"topology-muted\\" style=\\"font-size:11px\\">starting…</div> </article>"',
     'boundary: nodeStartingCardHtml: без clientIp/port/modelName → адрес = node.ip без порта, строки модели нет'),
    # ── second-pair-of-eyes tranche: exports the snapshot had never named ──
    ('rename_agent_wire',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "  Hotel  ";',
     'await (async () => { await rc.renameTopologyAgent("box-a", "ag1", "old"); return calls(); })()',
     '[{"path": "/api/topology/client/agent-alias", "method": "POST", "body": "{\\"hostId\\":\\"box-a\\",\\"agentId\\":\\"ag1\\",\\"name\\":\\"Hotel\\"}"}]',
     'positive: переименование агента — псевдоним обрезается и уходит с hostId и agentId'),
    ('rename_agent_cancelled',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => null;',
     'await (async () => { await rc.renameTopologyAgent("box-a", "ag1", "old"); return calls(); })()',
     '[]',
     'negative: отменённый диалог не шлёт ничего'),
    ('rename_agent_blank_clears',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "   ";',
     'await (async () => { await rc.renameTopologyAgent("box-a", "ag1", "old"); return JSON.parse(calls()[0].body).name; })()',
     '""',
     'as-is: пробелы — это СНЯТИЕ псевдонима, а не отмена (в отличие от add_client_blank, где пробелы = отмена); расхождение зафиксировано'),
    ('route_wait_clamped_silently',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "999999";'
     ' st.setTopology({ proxies: [], clients: [], routers: [{ id: "r1", graph: { nodes: [], edges: [], inputs: {} } }], assignments: {}, nodes: [] });',
     'await (async () => { await rc.editRouteWait("p1", 30); return { saved: (globalThis.__stubCalls || []).length, toast: toastText() }; })()',
     '{"saved": 0, "toast": ""}',
     'as-is: 999999 обрезается до 86400 БЕЗ единого слова оператору — он видит не то число, которое ввёл (saveRouters под заглушкой, сюда пинится молчание)'),
    ('route_wait_not_a_number_refused',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "30s";',
     'await (async () => { await rc.editRouteWait("p1", 30); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [], "toast": "Enter a number of seconds, or nothing to use the client\'s own"}',
     'negative: не-число отвергается с объяснением и без записи'),
    ('route_model_lock_carries_the_name',
     '',
     'await (async () => { await rc.setRouteModelLock("h1", "ag1", "primary", "  gpt-5.4-mini  ", false); return calls(); })()',
     '[{"path": "/api/topology/agent-route/model", "method": "POST", "body": "{\\"hostId\\":\\"h1\\",\\"agentId\\":\\"ag1\\",\\"role\\":\\"primary\\",\\"modelName\\":\\"gpt-5.4-mini\\"}"}]',
     'positive: замок несёт имя с собой — иначе закрытие замка стёрло бы имя оператора; auto=false НЕ шлёт modelNameAuto'),
    ('route_model_lock_auto_adds_flag',
     '',
     'await (async () => { await rc.setRouteModelLock("h1", "ag1", "primary", "x", true); return JSON.parse(calls()[0].body).modelNameAuto; })()',
     'true',
     'negative: auto=true — поле появляется; пара к предыдущему пину'),
    ('route_model_empty_clears',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "   ";',
     'await (async () => { await rc.editRouteModel("h1", "ag1", "primary", "old", false); return JSON.parse(calls()[0].body).modelName; })()',
     '""',
     'positive: пустое имя — это ОЧИСТКА (порт снова зовётся именем апстрима), а не отмена'),
    ('nvidia_source_kept_when_still_listed',
     '',
     'rc.surviving_nvidiaSmiSource([{ id: "local" }, { id: "c1" }, { id: "c2" }], "c2")',
     '"c2"',
     'positive: выбранный источник на месте — остаётся выбранным'),
    ('nvidia_source_resets_when_its_client_vanishes',
     '',
     'rc.surviving_nvidiaSmiSource([{ id: "local" }, { id: "c1" }], "c2")',
     '"local"',
     'negative: выбранный клиент исчез — источник возвращается на контроллер, иначе опрос уходит на ушедший хост'),
    ('nvidia_source_resets_with_one_source_left',
     '',
     'rc.surviving_nvidiaSmiSource([{ id: "local" }], "c1")',
     '"local"',
     'boundary: остался ОДИН источник — правило всё равно срабатывает; раньше починка стояла ПОСЛЕ раннего возврата, и ровно этот случай её миновал: опрос навсегда уходил на исчезнувший хост, а кнопки, чтобы вернуться, уже не рисовались'),
    ('nvidia_source_empty_list_is_local',
     '',
     '[rc.surviving_nvidiaSmiSource([], "c1"), rc.surviving_nvidiaSmiSource(null, "c1")]',
     '["local","local"]',
     'boundary: пустой и отсутствующий список — контроллер, а не падение'),
    ('nsch_phase_timeout_keeps_a_dismissable_card',
     'rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 }); rc._pendingRemoteStarts.get("h1").phase = "timeout";',
     '(h => ({ shown: h !== "", dismiss: h.includes("data-pending-remote-dismiss=\\"h1\\""),'
     ' says: h.includes("Timed out"), spinner: h.includes("topology-spinner"),'
     ' pending: [...rc._pendingRemoteStarts.keys()] }))(rc.nodeStartingCardHtml({ id: "h1" }))',
     '{"shown": true, "dismiss": true, "says": true, "spinner": false, "pending": ["h1"]}',
     'positive: истёкший старт ОСТАЁТСЯ карточкой с ✕ и говорит про таймаут — раньше карточка исчезала вместе с единственной кнопкой снятия, а запись жила дальше'),
    ('nsch_phase_error_says_failed',
     'rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 }); rc._pendingRemoteStarts.get("h1").phase = "error";',
     '(h => ({ failed: h.includes("Start failed"), timeout: h.includes("Timed out") }))(rc.nodeStartingCardHtml({ id: "h1" }))',
     '{"failed": true, "timeout": false}',
     'negative: отказ и таймаут — разные надписи, а не одна на оба случая'),
    ('nsch_no_record_still_empty',
     '',
     'rc.nodeStartingCardHtml({ id: "nobody" })',
     '""',
     'negative: записи нет вообще — по-прежнему пусто, карточка ниоткуда не берётся'),
    ('rsp_pending_only_while_starting',
     'rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 });',
     '(() => { const a = rc.remoteStartPending("h1");'
     ' rc._pendingRemoteStarts.get("h1").phase = "timeout"; const b = rc.remoteStartPending("h1");'
     ' rc._pendingRemoteStarts.get("h1").phase = "error"; const c = rc.remoteStartPending("h1");'
     ' return [a, b, c, rc.remoteStartPending("nobody")]; })()',
     '[true,false,false,false]',
     'positive+negative: «старт в полёте» — только фаза starting; истёкший и отказавший НЕ считаются, иначе остановленные ячейки хоста навсегда читаются как стартующие'),
    ('nsch_server_running_clears_pending',
     'rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 }); globalThis.__stubReturns["topology-render.topologyServerPhase"] = () => "running";',
     '({ html: rc.nodeStartingCardHtml({ id: "h1", servers: [{ port: 22001 }] }), pending: [...rc._pendingRemoteStarts.keys()] })',
     '{"html": "", "pending": []}',
     'positive: nodeStartingCardHtml: у узла есть сервер с фазой ≠ stopped (заглушка topologyServerPhase → running) → "" и pending снят'),
    ('nsch_server_stopped_keeps_card',
     'rc.registerPendingRemoteStart({ hostId: "h1", port: 22001 }); globalThis.__stubReturns["topology-render.topologyServerPhase"] = () => "stopped";',
     '({ html: norm(rc.nodeStartingCardHtml({ id: "h1", ip: "10.0.0.9", servers: [{ port: 22001 }] })), pending: [...rc._pendingRemoteStarts.keys()] })',
     '{"html": "<article class=\\"node-server loading\\" data-pending-remote-start=\\"h1\\"> <div class=\\"node-server-head\\"> <span class=\\"topology-spinner\\" aria-hidden=\\"true\\"></span> <span class=\\"topology-addr-link\\" style=\\"pointer-events:none\\">10.0.0.9:22001</span> <span class=\\"pill warn\\">loading</span> <span style=\\"flex:1\\"></span> <button class=\\"mini-link\\" type=\\"button\\" data-pending-remote-dismiss=\\"h1\\" style=\\"color:var(--muted,#888)\\" title=\\"Dismiss\\">✕</button> </div> <div class=\\"topology-muted\\" style=\\"font-size:11px\\">starting…</div> </article>", "pending": ["h1"]}',
     'negative: nodeStartingCardHtml: все серверы узла stopped (заглушка → stopped) → карточка остаётся, pending жив'),
    # ── the machine a scout reports: its own record ──
    ('host_record_by_id',
     'st.topology.hosts = [{ id: "h1", name: "Box A" }]; st.topology.clients = [{ id: "h1", name: "Client name" }, { id: "c9", name: "C9" }];',
     '[rc.topologyHost("h1").name, rc.topologyHost("c9"), rc.topologyHost("")]',
     '["Box A", null, null]',
     'positive: машину ищут в topology.hosts; клиент с тем же или своим id — не машина, и его нет — null, а не пустой объект'),
    ('host_record_without_hosts',
     'st.setTopology({ proxies: [], clients: [{ id: "h1", name: "C" }], routers: [], assignments: {}, nodes: [] });',
     'rc.topologyHost("h1")',
     'null',
     'negative: в ответе нет раздела hosts — ни одной машины, а не падение и не подстановка клиента'),
    ('disconnect_live_scout',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; };'
     ' st.topology.hosts = [{ id: "h2", name: "Box B", state: "online", ageSeconds: 20 }];'
     ' globalThis.__fetchReply["/api/topology/scout/disconnect"] = { ok: true, hostId: "h2", unpaired: true };',
     'await (async () => { await rc.disconnectScout("h2"); return { calls: calls(), toast: toastText(), confirm: globalThis.__msg }; })()',
     json.dumps({"calls": [{"path": "/api/topology/scout/disconnect", "method": "POST", "body": "{\"hostId\":\"h2\"}"}],
                 "toast": en("scoutDisconnected", name="Box B"),
                 "confirm": {"msg": en("dlgDisconnectScout", name="Box B"),
                             "opts": {"confirmLabel": en("nodeDisconnectScout")}}}, ensure_ascii=False),
     'positive: скаут отвечает — диалог «отключить», на провод только {hostId}; тост — скаут отключён'),
    ('disconnect_silent_scout_forgets',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg) => { globalThis.__msg = msg; return true; };'
     ' st.topology.hosts = [{ id: "h2", name: "Box B", state: "stale", ageSeconds: 600 }];'
     ' globalThis.__fetchReply["/api/topology/scout/disconnect"] = { ok: true, hostId: "h2", unpaired: false };',
     'await (async () => { await rc.disconnectScout("h2"); return { toast: toastText(), msg: globalThis.__msg }; })()',
     json.dumps({"toast": en("scoutForgottenSilent", name="Box B"),
                 "msg": en("dlgForgetSilentScout", name="Box B", ago=en("nodeScoutLastReport", ago="10m"))},
                ensure_ascii=False),
     'positive: скаут молчит — диалог говорит «забыть» и сколько он молчит, а тост — что забыта, скаут не ответил'),
    ('disconnect_declined',
     'globalThis.__stubReturns["dialogs.appConfirm"] = async () => false; st.topology.hosts = [{ id: "h2", name: "Box B", state: "online" }];',
     'await (async () => { await rc.disconnectScout("h2"); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [], "toast": ""}',
     'negative: отказ в подтверждении — ничего не уходит'),
    ('disconnect_refused_by_the_scout',
     'st.topology.hosts = [{ id: "h2", name: "Box B", state: "online" }];'
     ' globalThis.__fetchReply["/api/topology/scout/disconnect"] = { __status: 502, error: "the scout of h2 refused to let go: fleet token required" };',
     'await (async () => { await rc.disconnectScout("h2"); return toastText(); })()',
     '"Error: the scout of h2 refused to let go: fleet token required"',
     'negative: скаут отказал — отказ доходит до оператора, тоста «отключён» нет'),
    ('disconnect_unknown_host_names_its_id',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg) => { globalThis.__msg = msg; return false; };',
     'await (async () => { await rc.disconnectScout("h9"); return globalThis.__msg; })()',
     json.dumps(en("dlgDisconnectScout", name="h9"), ensure_ascii=False),
     'boundary: записи нет — диалог называет id; «молчит» он сказать не может, и не говорит'),
    ('smi_sources_name_the_controller_machine_once',
     'F({ nvidiaSmiSources: { innerHTML: "", querySelectorAll: () => [] } });'
     ' st.topology.server = { name: "Ctl-Display", ip: "10.0.0.5", hostname: "ctl-host" };'
     ' st.topology.nodes = [{ id: "h0", name: "box-ctl", ip: "10.0.0.5", controllerMachine: true }, { id: "h1", name: "Box A", ip: "10.0.0.9" }];'
     ' st.topology.hosts = [{ id: "h0", name: "box-ctl", state: "online", gpus: [{ name: "NVIDIA GeForce RTX 5090" }] },'
     ' { id: "h1", name: "Box A", state: "online", gpus: [{ name: "NVIDIA GeForce RTX 3090" }] }];',
     '(rc.renderNvidiaSmiSourceButtons(), [...globalThis.__fields.nvidiaSmiSources.innerHTML.matchAll(/data-smi-source="([^"]*)"[^>]*>\\s*([^<]*?)\\s*</g)].map((x) => [x[1], x[2]]))',
     '[["local", "box-ctl"], ["h1", "Box A · RTX 3090"]]',
     'positive: машина контроллера названа, как на доске (её узел); negative: не старым отображаемым именем «Ctl-Display», и её скаут не второй кнопкой — та же машина'),
    ('smi_sources_are_answering_hosts_with_a_gpu',
     'F({ nvidiaSmiSources: { innerHTML: "", querySelectorAll: () => [] } });'
     ' st.topology.server = { name: "Ctl" };'
     ' st.topology.hosts = [{ id: "h1", name: "Box A", state: "online", gpus: [{ name: "NVIDIA GeForce RTX 3090" }] },'
     ' { id: "h2", name: "Box B", state: "stale", gpus: [{ name: "RTX" }] }, { id: "h3", name: "Box C", state: "online", gpus: [] }];'
     ' st.topology.clients = [{ id: "c1", name: "Client", state: "online", gpus: [{ name: "RTX" }] }];',
     '(rc.renderNvidiaSmiSourceButtons(), [...globalThis.__fields.nvidiaSmiSources.innerHTML.matchAll(/data-smi-source="([^"]*)"/g)].map((x) => x[1]))',
     '["local", "h1"]',
     'positive: источники nvidia-smi — контроллер и машины, чей скаут отвечает и видит карту; молчащая, безкарточная и строка клиента — нет'),
    # ── an engine's model next to the cells: unload and delete (step 3) ──
    # Loading left the board on 2026-09-26 (the operator's choice B): a model
    # is reached through a cell in its engine, which loads it when it starts.
    ('engine_unload_confirmed_like_a_stop',
     'globalThis.__msg = null; globalThis.__asked = 0;'
     ' globalThis.__stubReturns["dialogs.appPrompt"] = async () => { globalThis.__asked += 1; return "4096"; };'
     ' globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; };',
     'await (async () => { await rc.actOnEngineModel("box-a", "lmstudio", "LM Studio", "qwen/qwen3-0.6b", "unload"); return { calls: calls(), confirm: globalThis.__msg, asked: globalThis.__asked }; })()',
     json.dumps({"calls": [{"path": "/api/engines/unload", "method": "POST",
                            "body": "{\"hostId\":\"box-a\",\"kind\":\"lmstudio\",\"model\":\"qwen/qwen3-0.6b\"}"}],
                 "confirm": {"msg": en("nodeEngineUnloadConfirm", model="qwen/qwen3-0.6b", engine="LM Studio"),
                             "opts": {"confirmLabel": en("nodeEngineUnload"), "scene": "stop"}},
                 "asked": 0}, ensure_ascii=False),
     'positive: выгрузка подтверждается, как остановка ячейки, и называет движок; окно не спрашивается'),
    ('engine_unload_declined',
     'globalThis.__stubReturns["dialogs.appConfirm"] = async () => false;',
     'await (async () => { await rc.actOnEngineModel("box-a", "ollama", "Ollama", "qwen3:8b", "unload"); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [], "toast": ""}',
     'negative: отказ в подтверждении — ничего не уходит'),
    ('engine_load_is_not_the_boards',
     'globalThis.__asked = [];'
     ' for (const d of ["appConfirm", "appConfirmChoice", "appPrompt"]) globalThis.__stubReturns["dialogs." + d] = async () => { globalThis.__asked.push(d); return true; };',
     'await (async () => { for (const op of ["load", "pull", "", undefined]) await rc.actOnEngineModel("box-a", "ollama", "Ollama", "qwen3:8b", op); return { calls: calls(), toast: toastText(), asked: globalThis.__asked }; })()',
     '{"calls": [], "toast": "", "asked": []}',
     'negative: загрузки с доски нет — модель доходит до дела через ячейку в своём движке; «load» и любое другое '
     'действие не спрашивают и не шлют ничего'),
    ('engine_act_takes_the_board_it_answers_with',
     'globalThis.__fetchReply["/api/engines/unload"] = { ok: true, topology: { proxies: [], clients: [], routers: [], assignments: {},'
     ' nodes: [{ id: "box-a", engines: [{ kind: "ollama", models: [{ name: "qwen3:8b", action: { op: "unload", since: 7 } }] }] }] } };',
     'await (async () => { await rc.actOnEngineModel("box-a", "ollama", "Ollama", "qwen3:8b", "unload"); return st.topology.nodes[0].engines[0].models[0].action; })()',
     '{"op": "unload", "since": 7}',
     'positive: доска из ответа — сразу в состояние: модель «выгружается» до следующего опроса'),
    ('engine_button_carries_its_line',
     'globalThis.__msgs = []; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg) => { globalThis.__msgs.push(msg); return true; };',
     'await (async () => { const b = (act, machine) => ({ dataset: { engineHost: "box-a", engineKind: "lmstudio", engineLabel: "LM Studio", engineModel: "qwen/qwen3-0.6b", engineAct: act, ...(machine === undefined ? {} : { engineMachine: machine }) } });'
     ' await rc.actOnEngineButton(b("unload")); await rc.actOnEngineButton(b("delete", "Box A")); await rc.actOnEngineButton(b("delete")); await rc.actOnEngineButton(b("load"));'
     ' return { msgs: globalThis.__msgs, sent: calls().map((c) => [c.path, c.body]) }; })()',
     json.dumps({"msgs": [en("nodeEngineUnloadConfirm", model="qwen/qwen3-0.6b", engine="LM Studio"),
                          en("nodeEngineDeleteConfirm", model="qwen/qwen3-0.6b", engine="LM Studio", machine="Box A"),
                          en("nodeEngineDeleteConfirm", model="qwen/qwen3-0.6b", engine="LM Studio", machine="box-a")],
                 "sent": [["/api/engines/unload", "{\"hostId\":\"box-a\",\"kind\":\"lmstudio\",\"model\":\"qwen/qwen3-0.6b\"}"],
                          ["/api/engines/delete", "{\"hostId\":\"box-a\",\"kind\":\"lmstudio\",\"model\":\"qwen/qwen3-0.6b\"}"],
                          ["/api/engines/delete", "{\"hostId\":\"box-a\",\"kind\":\"lmstudio\",\"model\":\"qwen/qwen3-0.6b\"}"]]},
                ensure_ascii=False),
     'кнопка строки несёт машину, движок, модель и действие; окно удаления называет машину её именем, а без имени — её '
     'id; «load» с кнопки не шлёт ничего'),
    ('engine_server_stop_confirmed',
     'globalThis.__msg = null;'
     ' globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; };'
     ' globalThis.__fetchReply["/api/engines/stop"] = { ok: true, topology: { proxies: [], clients: [], routers: [], assignments: {}, nodes: [{ id: "box-a", engines: [{ kind: "ollama", serverAction: { op: "stop", since: 3 } }] }] } };',
     'await (async () => { await rc.serveEngine("box-a", "ollama", "Ollama", "Box A", "stop"); return { calls: calls(), confirm: globalThis.__msg, mark: st.topology.nodes[0].engines[0].serverAction }; })()',
     json.dumps({"calls": [{"path": "/api/engines/stop", "method": "POST", "body": "{\"hostId\":\"box-a\",\"kind\":\"ollama\"}"}],
                 "confirm": {"msg": en("nodeEngineStopConfirm", engine="Ollama", machine="Box A"),
                             "opts": {"confirmLabel": en("nodeEngineStop"), "scene": "stop"}},
                 "mark": {"op": "stop", "since": 3}}, ensure_ascii=False),
     'positive: остановка сервера — с вопросом, как остановка ячейки (называет движок и машину); доска из ответа — сразу'),
    ('engine_server_stop_declined',
     'globalThis.__stubReturns["dialogs.appConfirm"] = async () => false;',
     'await (async () => { await rc.serveEngine("box-a", "ollama", "Ollama", "Box A", "stop"); return calls(); })()',
     '[]',
     'negative: «нет» — ничего не уходит'),
    ('engine_server_start_asks_nothing',
     'globalThis.__asked = 0; globalThis.__stubReturns["dialogs.appConfirm"] = async () => { globalThis.__asked += 1; return false; };',
     'await (async () => { await rc.serveEngineButton({ dataset: { engineHost: "box-a", engineKind: "lmstudio", engineLabel: "LM Studio", engineMachine: "Box A", engineServe: "start" } }); return { calls: calls(), asked: globalThis.__asked }; })()',
     json.dumps({"calls": [{"path": "/api/engines/start", "method": "POST", "body": "{\"hostId\":\"box-a\",\"kind\":\"lmstudio\"}"}],
                 "asked": 0}),
     'пуск — без вопроса (память берёт только загрузка модели); кнопка несёт машину, движок и действие'),
    ('engine_server_refusal_in_its_words',
     'globalThis.__fetchReply["/api/engines/start"] = { __status: 502, error: "box-a: LM Studio on port 1234 cannot start from here" };',
     'await (async () => { await rc.serveEngine("box-a", "lmstudio", "LM Studio", "Box A", "start"); return toastText(); })()',
     json.dumps("box-a: LM Studio on port 1234 cannot start from here"),
     'negative: отказ — словами отказавшего'),
    ('engine_pull_asks_a_name',
     'globalThis.__msg = null;'
     ' globalThis.__stubReturns["dialogs.appPrompt"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return " qwen3:4b "; };'
     ' globalThis.__fetchReply["/api/engines/pull"] = { ok: true, topology: { proxies: [], clients: [], routers: [], assignments: {}, nodes: [{ id: "box-a", engines: [{ kind: "ollama", downloading: { model: "qwen3:4b" } }] }] } };',
     'await (async () => { await rc.pullEngineButton({ dataset: { engineHost: "box-a", engineKind: "ollama", engineLabel: "Ollama" } }); return { calls: calls(), asked: globalThis.__msg, mark: st.topology.nodes[0].engines[0].downloading.model }; })()',
     json.dumps({"calls": [{"path": "/api/engines/pull", "method": "POST", "body": "{\"hostId\":\"box-a\",\"kind\":\"ollama\",\"model\":\"qwen3:4b\"}"}],
                 "asked": {"msg": en("nodeEnginePullPrompt", engine="Ollama", hint=en("nodeEnginePullHintOllama")),
                           "opts": {"value": "", "confirmLabel": en("nodeEnginePull")}},
                 "mark": "qwen3:4b"}, ensure_ascii=False),
     'positive: скачать — спросить имя с подсказкой по движку; имя без пробелов по краям; доска из ответа — сразу'),
    ('engine_pull_hint_by_kind',
     'globalThis.__msgs = []; globalThis.__stubReturns["dialogs.appPrompt"] = async (msg) => { globalThis.__msgs.push(msg); return null; };',
     'await (async () => { await rc.pullEngineModel("box-a", "lmstudio", "LM Studio"); await rc.pullEngineModel("box-a", "vllm", "vLLM"); return { msgs: globalThis.__msgs, calls: calls() }; })()',
     json.dumps({"msgs": [en("nodeEnginePullPrompt", engine="LM Studio", hint=en("nodeEnginePullHintLmStudio")),
                          en("nodeEnginePullPrompt", engine="vLLM", hint="")],
                 "calls": []}, ensure_ascii=False),
     'подсказка — своя у каждого движка; движок без подсказки — пусто, а не чужая; отмена — ничего не уходит'),
    ('engine_pull_name_typo_refused',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "qwen 3";',
     'await (async () => { await rc.pullEngineModel("box-a", "ollama", "Ollama"); return { calls: calls(), toast: toastText() }; })()',
     json.dumps({"calls": [], "toast": en("nodeEngineModelNameBad")}, ensure_ascii=False),
     'negative: имя с пробелом — отказ словами, ничего не уходит'),
    ('engine_delete_confirmed_as_danger',
     'globalThis.__msg = null;'
     ' globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; };',
     'await (async () => { await rc.actOnEngineButton({ dataset: { engineHost: "box-a", engineKind: "ollama", engineLabel: "Ollama", engineModel: "qwen2.5:0.5b", engineAct: "delete", engineMachine: "Box A" } }); return { calls: calls(), confirm: globalThis.__msg }; })()',
     json.dumps({"calls": [{"path": "/api/engines/delete", "method": "POST", "body": "{\"hostId\":\"box-a\",\"kind\":\"ollama\",\"model\":\"qwen2.5:0.5b\"}"}],
                 "confirm": {"msg": en("nodeEngineDeleteConfirm", model="qwen2.5:0.5b", engine="Ollama", machine="Box A"),
                             "opts": {"confirmLabel": en("nodeEngineDelete")}}}, ensure_ascii=False),
     'positive: удалить модель — только через окно (вид «опасно», без «stop»), называет модель, движок и машину'),
    ('engine_delete_declined',
     'globalThis.__stubReturns["dialogs.appConfirm"] = async () => false;',
     'await (async () => { await rc.actOnEngineModel("box-a", "ollama", "Ollama", "qwen2.5:0.5b", "delete", "Box A"); return calls(); })()',
     '[]',
     'negative: «нет» — ничего не удалено'),
    ('engine_delete_without_a_name_says_the_id',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg) => { globalThis.__msg = msg; return false; };',
     'await (async () => { await rc.actOnEngineModel("box-a", "ollama", "Ollama", "qwen2.5:0.5b", "delete"); return globalThis.__msg; })()',
     json.dumps(en("nodeEngineDeleteConfirm", model="qwen2.5:0.5b", engine="Ollama", machine="box-a"), ensure_ascii=False),
     'boundary: у машины нет имени — окно называет её id, а не пустое место'),
    ('engine_act_refusal_in_its_words',
     'globalThis.__fetchReply["/api/engines/unload"] = { __status: 409, error: "qwen3:8b is not loaded" };',
     'await (async () => { await rc.actOnEngineModel("box-a", "ollama", "Ollama", "qwen3:8b", "unload"); return { toast: toastText(), nodes: st.topology.nodes.length }; })()',
     '{"toast": "qwen3:8b is not loaded", "nodes": 0}',
     'negative: отказ — словами отказавшего, доска не тронута'),
    # ── a cell in an engine from the "+" on its model's line (2026-09-26, the operator's choice B) ──
    ('erc_plus_asks_nothing',
     ERC_SETUP + ' globalThis.__fetchReply["/api/topology/server-slot/add"] = { cell: { hostId: "h1", port: 22001 } };',
     'await (async () => { await rc.reserveEngineCell("h1", "ollama", "qwen2.5:0.5b"); return ' + ERC_RESULT + '; })()',
     json.dumps({"calls": rsc_add({"hostId": "h1", "engine": "ollama", "model": "qwen2.5:0.5b"}), "toast": "", "asked": [],
                 "reserving": [], "fresh": ["h1:22001"], "snap": [["h1", {"port": 22001, "startedAt": 1700000100000}]]}),
     'positive: «+» у модели не спрашивает ничего — строка уже назвала движок и модель; на провод {hostId, engine, '
     'model}; спиннер машины на следующем свободном порту, пока ячейка не на доске; вспышка новой ячейки'),
    ('erc_plus_takes_the_next_free_port',
     ERC_SETUP + ' st.topology.nodes = [{ id: "h1", servers: [{ port: 22001 }] }]; st.topology.proxies = [{ port: 22002 }];',
     'await (async () => { await rc.reserveEngineCell("h1", "lmstudio", "google/gemma-4-e4b"); return { snap: globalThis.__snap, fresh: [...rc._newReservedCells] }; })()',
     '{"snap": [["h1", {"port": 22003, "startedAt": 1700000100000}]], "fresh": ["h1:22003"]}',
     'boundary: порт — следующий свободный по всему флоту: мимо ячейки 22001 и прокси 22002'),
    ('erc_one_reserve_at_a_time',
     ERC_SETUP + ' rc._reservingCells.set("h1", { port: 22005, startedAt: 1 });',
     'await (async () => { await rc.reserveEngineCell("h1", "ollama", "qwen2.5:0.5b"); return ' + ERC_RESULT + '; })()',
     json.dumps({"calls": [], "toast": "", "asked": [], "reserving": [["h1", {"port": 22005, "startedAt": 1}]], "fresh": [],
                 "snap": None}),
     'negative: машина уже резервирует ячейку — второй «+» не берёт второй порт: ни запроса, ни рендера, прежний '
     'спиннер не тронут'),
    ('erc_other_machine_does_not_block',
     ERC_SETUP + ' rc._reservingCells.set("h2", { port: 22005, startedAt: 1 });',
     'await (async () => { await rc.reserveEngineCell("h1", "ollama", "qwen2.5:0.5b"); return calls().length; })()',
     '1',
     'boundary: резерв на другой машине этой не мешает'),
    ('erc_missing_parts_send_nothing',
     ERC_SETUP,
     'await (async () => { await rc.reserveEngineCell("", "ollama", "m"); await rc.reserveEngineCell("h1", "", "m"); await rc.reserveEngineCell("h1", "ollama", ""); return ' + ERC_RESULT + '; })()',
     json.dumps({"calls": [], "toast": "", "asked": [], "reserving": [], "fresh": [], "snap": None}),
     'negative: без машины, движка или модели — ничего: ячейка в движке резервируется только с моделью'),
    ('erc_refusal_in_its_words',
     ERC_SETUP + ' globalThis.__fetchReply["/api/topology/server-slot/add"] = { __status: 409, error: "Ollama has no model qwen9 on this machine" };',
     'await (async () => { await rc.reserveEngineCell("h1", "ollama", "qwen9"); return ' + ERC_RESULT + '; })()',
     json.dumps({"calls": rsc_add({"hostId": "h1", "engine": "ollama", "model": "qwen9"}),
                 "toast": "Error: Ollama has no model qwen9 on this machine", "asked": [], "reserving": [], "fresh": [],
                 "snap": [["h1", {"port": 22001, "startedAt": 1700000100000}]]}),
     'negative: отказ контроллера (engine_cells.py) — его словами; спиннер снят, вспышки нет'),
    ('erc_button_carries_its_line',
     ERC_SETUP,
     'await (async () => { await rc.reserveEngineButton({ dataset: { engineReserve: "h1", engineKind: "lmstudio", engineModel: "google/gemma-4-e4b" } }); return calls(); })()',
     json.dumps(rsc_add({"hostId": "h1", "engine": "lmstudio", "model": "google/gemma-4-e4b"})),
     'positive: кнопка «+» несёт машину, движок и модель — так, как их пишет shelfLineHtml'),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 40:
        print(f"js remote-cells FAILED: всего {len(PINS)} пинов — снимок пуст или урезан")
        return 1
    node = find_node()
    if node is None:
        print("js remote-cells: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    ids = [p[0] for p in PINS]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        print(f"js remote-cells FAILED: повторяющиеся id пинов: {sorted(dup)}")
        return 1
    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]
    # Every pin must be independent of its neighbors: that's exactly why
    # reset() sits in front of it. This is proven right here — the whole set
    # is run a SECOND time in reverse order, and the values must match.
    # Without this check a pin can pass because of state left behind by the
    # previous one (this actually happened: two "port not set" pins stayed
    # green only because they ran before the cell was opened).
    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev")).replace("out[", "rev[")
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    probe_path = ROOT / "scripts" / ".probe_js_remote_cells.tmp.mjs"
    probe_path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            [node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(probe_path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        probe_path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print("js remote-cells FAILED: node вышел с кодом %d" % run.returncode)
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    for pid, _s, _e, _x, _m in PINS:
        if got.get(pid, "\0missing") != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка: прямой прогон {json.dumps(got.get(pid), ensure_ascii=False)[:120]}, "
                         f"обратный {json.dumps(rev.get(pid), ensure_ascii=False)[:120]}")
    section = ""
    for pid, _setup, _expr, expected, msg in PINS:
        head = pid.split("_", 1)[0]
        if head != section:
            section = head
            print(f"{section}:")
        want = json.loads(expected)
        have = got.get(pid, {"__missing": True})
        ok = have == want
        check(ok, msg if ok else f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:300]}\n        получено  {json.dumps(have, ensure_ascii=False)[:300]}")
    print(f"порядок: {len(PINS)} пинов дают те же значения в обратном порядке" if not _fail else "")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for f in _fail:
            print("  - " + f.splitlines()[0])
        return 1
    print(f"js remote-cells OK: настоящий модуль в node, {len(PINS)} пинов действий клиентских ячеек значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
