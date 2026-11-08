#!/usr/bin/env python3
"""Snapshot of static/js/remote-cells.js — the actions behind client cells' buttons.

What's pinned for an action: WHAT goes out on the wire (calls(): path,
method, body), WHAT the operator sees (toastText()), and WHAT stays in state
(the sets _stoppingCells/_pendingCellActions/_deletingSlots/_reservingCells/
_newReservedCells). A history of fixes: instant busy and
pending state (87f5ea7), a "starting" card shown before the real one appears.
Since 2026-11-08 a cell is known by its id alone (cellId): it holds a port only
while it runs, the one its scout leased — no body, key, question or title here
names a port, and the port picker, swap, exclusions and scan are gone.

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
from _node import find_node, node_search_paths, probe_args  # noqa: E402

def _table(code):
    """Every one-string line of a language file (en.js, ru.js) — a pin quotes the page's own words, not a
    copy of them that can drift."""
    import re
    out = {}
    for key, raw in re.findall(r'^  (\w+): (".*"),$', (ROOT / f"static/js/i18n/{code}.js").read_text(encoding="utf-8"), re.M):
        try:
            out[key] = json.loads(raw)
        except ValueError:
            continue
    return out


EN = _table("en")
RU = _table("ru")


def _said(table, key, kw):
    text = table[key]
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def en(key, **kw):
    return _said(EN, key, kw)


def ru(key, **kw):
    """The same words in Russian: an English literal left in the code says the English words there too."""
    return _said(RU, key, kw)


STUBS = ("topology-render,topology-modals,cables,routers,cloud,history,dialogs,favorites,config-locator,system-panels,"
         "onboarding,topology-dnd,canvas,usage-stats,dialog-llamas,models-page,system-page,onboarding-tours")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {}, runners: [], artifacts: [], models: [], paths: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {}, nodes: [] });
Date.now = () => 1_700_000_100_000;
globalThis.__stubReturns = { "dialogs.appConfirm": async () => true, "dialogs.appConfirmTyped": async () => true };
const le = await import(pathToFileURL(process.env.JS_ROOT + "/llama-edit.js").href);
const rc = await import(pathToFileURL(process.env.JS_ROOT + "/remote-cells.js").href);
const cst = await import(pathToFileURL(process.env.JS_ROOT + "/constants.js").href);
const ui = st.ui;
const norm = (s) => String(s).replace(/\s+/g, " ").trim();
const toastEl = () => ({ textContent: "", classList: { add() {}, remove() {} } });
const F = (fields) => { globalThis.__fields = { toast: toastEl(), ...fields }; };
const reset = () => { st.setState({ config: {}, runners: [], artifacts: [], models: [], paths: {} });
  st.setTopology({ proxies: [], clients: [], routers: [], assignments: {}, nodes: [] });
  F({}); globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__stubReturns = { "dialogs.appConfirm": async () => true, "dialogs.appConfirmTyped": async () => true };
  for (const c of [rc._stoppingHosts, rc._stoppingCells, rc._deletingSlots, rc._newReservedCells, rc._pendingCellActions, rc._reservingCells]) c.clear();
  // The cell form's hearers and its keeper (the cell window, cell-settings.js) are the module's one form's: none between pins.
  rc.CELL_FORM.keeper = null; rc.CELL_FORM.watching = false; for (const k of Object.keys(rc.CELL_FORM.listeners)) rc.CELL_FORM.listeners[k].length = 0;
  delete globalThis.MutationObserver; };
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body }));
const toastText = () => globalThis.__fields.toast.textContent;
const out = {};
"""

# (id, setup, expression, expected JSON string, message). Filled from the pin
# workflow; see the OOP-rewrite journal (private), phase 7, snapshot 6.
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


# The model-cache panel of the cell form, as fake elements the page writes to, and the form opened over them.
OPEN_FORM = 'try { rc.openLlamaRemoteEdit("h1", "gpu0", [], ""); } catch (e) {}'
# Three kept cells of machine h1 on the board, by their ids: c22013 configured (a cell made before 2026-11-07 keeps its old
# port in its name only), c3f9a02b1 configured, c0a1b2c3d reserved. None runs, so none has a port. The form is filled for one by
# its id, and its machine is read from its row.
KEPT_CELLS = (
    'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }], nodes: [{ id: "h1", role: "host", servers: ['
    '{ isSlot: true, clientId: "h1", cellId: "c22013", port: null, phase: "stopped", model: "model", slotConfig: { RUNNER: "llama-server", MODEL_FILE: "m/model.gguf", KV_OFFLOAD: "0" } },'
    ' { isSlot: true, clientId: "h1", cellId: "c3f9a02b1", port: null, phase: "stopped", model: "other", slotConfig: { RUNNER: "llama-server", MODEL_FILE: "m/other.gguf" } },'
    ' { isSlot: true, clientId: "h1", cellId: "c0a1b2c3d", port: null, phase: "reserved", slotConfig: {} }] }] });'
    # The dialog as the form's first opening wires it (wireCellKindToggle): a dataset to mark, nothing to find in it.
    ' F({ llamaRemoteEditOverlay: { hidden: true, dataset: {}, querySelector: () => null, hasAttribute: () => true, focus() {} },'
    ' llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } });')
CACHE_PANEL = (
    'const panel = { note: { textContent: "kept" }, status: { textContent: "" }, '
    'btn: { disabled: false, textContent: "Clear", classList: { add() {}, remove() {} } }, start: { disabled: false, title: "" }, '
    'list: { innerHTML: "" } }; globalThis.__panel = panel; '
    'F({ llamaRemoteEditTitle: { textContent: "", parentElement: { querySelector: () => ({}) } }, "tr-purgeCache": panel.btn, '
    '"tr-purgeCacheNote": panel.note, "tr-purgeCacheStatus": panel.status, llamaRemoteEditStart: panel.start, "tr-cacheList": panel.list }); ')
PURGED = "✓ " + en("topologyPurgeCacheDone") + ": " + en("topologyPurgeCacheResult", n=3, gb="12.34")
PURGED_RU = "✓ " + ru("topologyPurgeCacheDone") + ": " + ru("topologyPurgeCacheResult", n=3, gb="12.34")
# The page in Russian for the length of a pin, and English again after it, whatever the pin does.
IN_RUSSIAN = ('const i18n = await import(new URL("i18n.js", "file://" + process.env.JS_ROOT + "/").href); await i18n.setLang("ru"); '
              'try { return {BODY}; } finally { await i18n.setLang("en"); }')

PINS = [
    # ── remote_actions ──
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
    ('port_helpers_are_gone',
     '',
     '["openPortPicker", "usedTopologyPorts", "nextTopologyCellPort", "findSlotEntry", "openRemoteFormForHost", "_trCellPort", "_expandedCellCfgs"].filter((n) => n in rc)',
     '[]',
     'defect-guard: выбора порта, обмена портами, исключений и скана больше нет (их маршруты у контроллера — 404), нет и «следующего '
     'свободного порта»: порт ячейке даёт её скаут при старте; ячейку знают по id, а не по hostId:port'),
    ('checked_llama_goes',
     '',
     'rc.cellConfigChecked({ RUNNER: "llama-server", MODEL_FILE: "m/a.gguf" })',
     '{"config": {"RUNNER": "llama-server", "MODEL_FILE": "m/a.gguf"}, "refused": ""}',
     'cellConfigChecked: модель llama.cpp с файлом — без отказа, конфиг как есть'),
    ('checked_llama_no_model',
     '',
     'rc.cellConfigChecked({ RUNNER: "llama-server" }).refused',
     json.dumps(en("selectModel"), ensure_ascii=False),
     'negative: cellConfigChecked: модели нет — «выберите модель»'),
    ('checked_command',
     '',
     '[rc.cellConfigChecked({ RUNNER: "custom" }).refused, rc.cellConfigChecked({ CELL_KIND: "command", COMMAND: "run.sh" }).refused]',
     json.dumps([en("enterCommand"), ""], ensure_ascii=False),
     'cellConfigChecked: команда без команды — отказ; negative: ячейка-команда с командой идёт'),
    ('checked_vllm_takes_the_picked_model',
     'globalThis.__vllmIn = { RUNNER: "vllm", VLLM_MODEL: "" };',
     '(() => { const got = rc.cellConfigChecked(globalThis.__vllmIn, " Org/Model "); return [got.config.VLLM_MODEL, got.refused, globalThis.__vllmIn.VLLM_MODEL]; })()',
     '["Org/Model", "", ""]',
     'cellConfigChecked: vLLM без своей модели берёт выбранную в списке; negative: пришедший конфиг не тронут'),
    ('checked_vllm_keeps_its_own',
     '',
     '[rc.cellConfigChecked({ RUNNER: "vllm", VLLM_MODEL: "own" }, "picked").config.VLLM_MODEL, rc.cellConfigChecked({ RUNNER: "vllm" }, "").refused]',
     json.dumps(["own", en("selectModel")], ensure_ascii=False),
     'cellConfigChecked: своя модель vLLM остаётся своей; negative: ни своей, ни выбранной — «выберите модель»'),
    ('checked_kv_needs_flash',
     '',
     '[rc.cellConfigChecked({ MODEL_FILE: "m/a.gguf", ENABLE_FLASH_ATTN: "0", CACHE_TYPE_V: "q8_0" }).refused, rc.cellConfigChecked({ MODEL_FILE: "m/a.gguf", ENABLE_FLASH_ATTN: "1", CACHE_TYPE_V: "q8_0" }).refused]',
     json.dumps([en("kvCacheNeedsFlash", type="q8_0"), ""], ensure_ascii=False),
     'cellConfigChecked: сжатый кэш V без flash attention — отказ словами с типом; negative: с flash attention идёт'),
    ('board_cell_by_its_id',
     'st.topology.nodes = [{ id: "h1", servers: [{ cellId: "c22001", port: null, tag: "a" }] }, { id: "h2", servers: [{ cellId: "c3f9a02b1", port: 22007, tag: "b" }] }];',
     '[rc.boardCell("c22001")?.tag ?? null, rc.boardCell("c3f9a02b1")?.tag ?? null]',
     '["a", "b"]',
     'positive: boardCell — строка ячейки на доске по её id, на любой машине; порт прогона у строки (у работающей) роли не играет'),
    ('board_cell_not_by_a_port',
     'st.topology.nodes = [{ id: "h1", servers: [{ cellId: "c3f9a02b1", port: 22001 }, { port: 22002 }] }];',
     '[rc.boardCell("c22001"), rc.boardCell("22001"), rc.boardCell("22002"), rc.boardCell(""), rc.boardCell(null), rc.boardCell("nope")]',
     '[null, null, null, null, null, null]',
     'negative: ячейку не находят по порту её прогона — ни «c<порт>», ни голым номером; строка без cellId — ничья; пустой и неизвестный id — '
     'null, а не первая попавшаяся строка'),
    ('board_cell_without_nodes',
     'st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });',
     'rc.boardCell("c22001")',
     'null',
     'negative: в ответе нет nodes — null без броска'),
    ('form_cell_is_the_kept_cell_the_form_holds',
     KEPT_CELLS + ' rc.CELL_FORM.fill("c22013", { hidden: true });',
     '(() => { const a = rc.formCell("tr-")?.cellId ?? null; const b = rc.formCell("te-"); rc.CELL_FORM.fill(rc.CellForm.newKey("h1"), { hidden: true }); return [a, b, rc.formCell("tr-")]; })()',
     '["c22013", null, null]',
     'formCell: строка доски той сохранённой ячейки, которую держит форма tr-; negative: у другой формы её нет, у новой ячейки (ещё без id) — тоже'),
    ('form_cell_skips_a_row_the_board_keeps_no_record_of',
     'st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", servers: [{ isSlot: false, clientId: "h1", cellId: "c22013", port: 22013, phase: "running" }] }] }); try { rc.openLlamaRemoteEdit("h1", "gpu0", [], "c22013"); } catch (e) {}',
     'rc.formCell("tr-")',
     'null',
     'negative: ячейка, о которой контроллер не хранит записи (сирота, isSlot=false), — не сохранённая ячейка формы'),
    ('csa_stop_wire_and_state',
     '',
     'await (async () => { await rc.cellServiceAction("c22001", "stop"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("c22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\",\\"action\\":\\"stop\\"}"}], "toast": "", "pending": "stop", "stopping": ["c22001"]}',
     'defect-history: cellServiceAction (87f5ea7): stop — на провод {cellId, action}; сразу после await pending="stop" и _stoppingCells держат id ячейки (их снимет таймер 1200 мс); тоста нет'),
    ('csa_start_clears_pending',
     '',
     'await (async () => { await rc.cellServiceAction("c22001", "start"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("c22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\",\\"action\\":\\"start\\"}"}], "toast": "", "pending": null, "stopping": []}',
     'defect-history: cellServiceAction: start — pending снят сразу после ответа, _stoppingCells пуст, тоста нет'),
    ('csa_body_carries_no_port_nor_machine',
     '',
     'await (async () => { await rc.cellServiceAction("c22001", "restart"); await rc.cellServiceAction("c3f9a02b1", "enable"); return calls().map((c) => Object.keys(JSON.parse(c.body))); })()',
     '[["cellId", "action"], ["cellId", "action"]]',
     'negative: тело действия — только id ячейки и действие: ни port, ни hostId (контроллер знает машину ячейки, порт даёт скаут при старте)'),
    ('csa_boot_clears_pending',
     '',
     'await (async () => { await rc.cellServiceAction("c22001", "boot"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("c22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\",\\"action\\":\\"boot\\"}"}], "toast": "", "pending": null, "stopping": []}',
     'positive: cellServiceAction: boot идёт по ветке start — pending снят сразу'),
    ('csa_library_model_starts_like_any',
     'globalThis.__asked = []; globalThis.__stubReturns["dialogs.appConfirm"] = async (text) => { globalThis.__asked.push(text); return true; };'
     ' globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: true, bringing: { id: "mv-1" } };',
     r'''await (async () => {
       const handlers = [];
       const btn = { dataset: { nodeCellLaunch: "h1", cellId: "c22001", nodeCellRunner: "llama-server",
                                nodeCellLibrary: "NAS", nodeCellLibraryFiles: "model, mmproj" },
                     addEventListener: (ev, fn) => handlers.push(fn) };
       const root = { querySelectorAll: (sel) => (sel === "[data-node-cell-launch]" ? [btn] : []) };
       // The vram hover binds once per page, on the body's dataset.
       document.body ||= {}; document.body.dataset ||= { vramHoverBound: "1" };
       rc.bindServerSlotControls(root);
       await handlers[0]();
       for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
       return ({ asked: globalThis.__asked, body: calls().map((c) => c.body), toast: toastText(), choose: typeof rc.askWhereFrom }); })()''',
     json.dumps({"asked": [en("dlgStartCell", cell="c22001")],
                 "body": [json.dumps({"cellId": "c22001", "action": "start"}, separators=(",", ":"))],
                 "toast": "", "choose": "undefined"}, ensure_ascii=False),
     'negative: ▶ у ячейки с моделью в библиотеке — обычное подтверждение старта, без вопроса «с диска или из '
     'библиотеки» и без поля modelFrom на проводе: ответ читали только ячейки контроллера, скаут читает модель на '
     'месте; и ответ сервера «везу модель» больше ничего не говорит; без имени на кнопке ячейку называет её id, не порт'),
    ('csa_engine_cell_start_speaks_of_the_model',
     'globalThis.__asked = []; globalThis.__stubReturns["dialogs.appConfirm"] = async (text) => { globalThis.__asked.push(text); return false; };'
     ' st.setState({ config: {}, runners: [{ id: "llama-server" }, { id: "custom" }, { id: "ollama", engineCell: true }], artifacts: [], models: [], paths: {} });',
     r'''await (async () => {
       const ask = async (runner, model) => {
         const handlers = [];
         const btn = { dataset: { nodeCellLaunch: "h1", cellId: "c3f9a02b1", nodeCellRunner: runner, nodeCellModel: model },
                       addEventListener: (ev, fn) => handlers.push(fn) };
         const root = { querySelectorAll: (sel) => (sel === "[data-node-cell-launch]" ? [btn] : []) };
         document.body ||= {}; document.body.dataset ||= { vramHoverBound: "1" };
         rc.bindServerSlotControls(root);
         await handlers[0]();
       };
       await ask("ollama", "qwen3:8b"); await ask("custom", "bash run.sh"); await ask("lmstudio", "m");
       return { asked: globalThis.__asked, calls: calls() }; })()''',
     json.dumps({"asked": [en("dlgStartModel", model="qwen3:8b"), en("dlgStartCommand", cell="bash run.sh"),
                           en("dlgStartCommand", cell="m")], "calls": []}, ensure_ascii=False),
     'positive: ▶ у ячейки в Ollama спрашивает о её модели — модель загрузится в память (движка); negative: у командной '
     'ячейки — о команде, названной так, как её показывает доска; раннер, которого реестр не называет ячейкой движка (lmstudio здесь), — тоже о команде; '
     'отказ в диалоге — ни одного запроса'),
    ('csa_line_switch_names_its_model',
     'globalThis.__asked = []; globalThis.__stubReturns["dialogs.appConfirm"] = async (text) => { globalThis.__asked.push(text); return false; };',
     r'''await (async () => {
       const press = async (sel, dataset) => {
         const handlers = [];
         // A folded line's switch: its dataset is the card's, and no card is around it — no closest().
         const btn = { dataset, addEventListener: (ev, fn) => handlers.push(fn) };
         const root = { querySelectorAll: (q) => (q === sel ? [btn] : []) };
         document.body ||= {}; document.body.dataset ||= { vramHoverBound: "1" };
         rc.bindServerSlotControls(root);
         await handlers[0]();
       };
       await press("[data-node-cell-launch]", { nodeCellLaunch: "h1", cellId: "c22001", nodeCellRunner: "llama-server", nodeCellModel: "Qwen3-Embedding-0.6B" });
       await press("[data-node-cell-stop]", { nodeCellStop: "h1", cellId: "c22001", nodeCellModel: "Qwen3-Embedding-0.6B" });
       await press("[data-node-cell-stop]", { nodeCellStop: "h1", cellId: "c3f9a02b1" });
       return { asked: globalThis.__asked, calls: calls() }; })()''',
     json.dumps({"asked": [en("dlgStartModel", model="Qwen3-Embedding-0.6B"),
                           en("dlgStopModel", model="Qwen3-Embedding-0.6B"),
                           en("dlgStopCell", cell="c3f9a02b1")], "calls": []}, ensure_ascii=False),
     'defect-history: тумблер свёрнутой строки спрашивал «Start the server on :22001?» без имени модели — искал её в '
     'карточке через closest("article"), а вокруг строки карточки нет; теперь имя едет в атрибутах ▶/⏹ (живая проверка '
     '2026-09-26); negative: у кнопки без имени — вопрос о ячейке по её id, ни в одном вопросе нет порта; отказ — ни одного запроса'),
    ('csa_engine_start_short_asks_then_forces',
     'globalThis.__asked = [];'
     ' globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__asked.push({ msg, opts }); return true; };'
     ' let n = 0; globalThis.__fetchReply["/api/topology/server-cell/action"] = () => (++n === 1'
     ' ? { ok: false, hostId: "h1", cellId: "c22041", action: "start", short: { model: "big:70b", needBytes: 45097156608, freeBytes: 1048576000, basis: "weights" } }'
     ' : { ok: true, hostId: "h1", cellId: "c22041", action: "start" });',
     'await (async () => { await rc.cellServiceAction("c22041", "start"); return { bodies: calls().map((c) => c.body), asked: globalThis.__asked, pending: rc._pendingCellActions.get("c22041") ?? null, toast: toastText() }; })()',
     json.dumps({"bodies": ['{"cellId":"c22041","action":"start"}',
                            '{"cellId":"c22041","action":"start","force":true}'],
                 "asked": [{"msg": en("cellEngineShort", model="big:70b", need="≥ 42.0 GB", free="1000 MB"),
                            "opts": {"confirmLabel": en("cellStartAnyway"), "scene": "start"}}],
                 "pending": None, "toast": ""}, ensure_ascii=False),
     'positive: ячейка в движке не влезет — контроллер не стартует её, а спрашивает: вопрос с числами («≥» — только '
     'файл, не меньше) и без порта, согласие — тот же старт с force; тоста «не удалось» нет, метка «запускается» снята'),
    ('csa_engine_start_short_declined',
     'globalThis.__asked = [];'
     ' globalThis.__stubReturns["dialogs.appConfirm"] = async (msg) => { globalThis.__asked.push(msg); return false; };'
     ' globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, short: { model: "google/gemma-4-e4b", needBytes: 7000000000, freeBytes: 4294967296, basis: "engine" } };',
     'await (async () => { await rc.cellServiceAction("c22041", "start"); return { n: calls().length, asked: globalThis.__asked, pending: rc._pendingCellActions.get("c22041") ?? null, toast: toastText() }; })()',
     json.dumps({"n": 1, "asked": [en("cellEngineShort", model="google/gemma-4-e4b", need="≈ 6.5 GB", free="4.0 GB")],
                 "pending": None, "toast": ""}, ensure_ascii=False),
     'negative: «нет» — второго старта нет, метка снята, тоста нет; boundary: оценка не по одному файлу — «≈», а не «≥»'),
    ('csa_no_cell_sends_nothing',
     '',
     'await (async () => { const said = await rc.cellServiceAction("", "start"); return { said, calls: calls(), toast: toastText(), pending: [...rc._pendingCellActions.keys()], stopping: [...rc._stoppingCells] }; })()',
     json.dumps({"said": False, "calls": [], "toast": "⚠️ " + en("cellActionFailed"), "pending": [], "stopping": []}, ensure_ascii=False),
     'negative: кнопка без id ячейки (доска нарисована не так) — ничего не уходит, ни одной метки «идёт», и оператор слышит, что ничего не '
     'сделано; раньше нечисловой порт уходил на провод как port:null'),
    ('csa_reply_busy_hint',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, error: "slot already in progress" };',
     'await (async () => { await rc.cellServiceAction("c22001", "start"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("c22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\",\\"action\\":\\"start\\"}"}], "toast": "⚠️ slot already in progress — this host runs one server slot at a time — wait for the current start to finish", "pending": null, "stopping": []}',
     'defect-history: cellServiceAction: ответ ok:false с «already/in progress» → тост с ошибкой И подсказкой cellSlotBusyHint'),
    ('csa_reply_busy_case_insensitive',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, error: "Already Running here" };',
     'await (async () => { await rc.cellServiceAction("c22001", "start"); return toastText(); })()',
     '"⚠️ Already Running here — this host runs one server slot at a time — wait for the current start to finish"',
     'boundary: cellServiceAction: регэксп busy нечувствителен к регистру («Already Running») → подсказка добавлена'),
    ('csa_says_how_it_went',
     '',
     r'''await (async () => {
       const asked = async (reply, boom) => {
         globalThis.__fetchReply["/api/topology/server-cell/action"] = reply;
         return rc.cellServiceAction("c22001", "start");
       };
       const out = { done: await asked({ ok: true }), refused: await asked({ ok: false, error: "boom" }) };
       globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: true };
       out.stop = await rc.cellServiceAction("c22001", "stop");
       return out;
     })()''',
     '{"done": true, "refused": false, "stop": true}',
     'defect-history (1.3.695, стенд): cellServiceAction говорит, как прошло: true — ячейку попросили, false — отказ, причина уже сказана; без этого план запуска считал отказ успехом'),
    ('csa_says_how_it_went_declined_short',
     'globalThis.__stubReturns["dialogs.appConfirm"] = async () => false;'
     ' globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, short: { model: "m", needBytes: 1, freeBytes: 0, basis: "weights" } };',
     'await rc.cellServiceAction("c22001", "start")',
     'false',
     'negative: оператор не стал запускать ячейку движка, которой не хватает места: это тоже «не запущено»'),
    ('csa_says_how_it_went_failed_request',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { __status: 502, error: "unreachable" };',
     'await rc.cellServiceAction("c22001", "start")',
     'false',
     'negative: запрос не прошёл (502, сеть): причина сказана тостом, ответ — false, а не молчаливый успех'),
    ('csa_reply_plain_error',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, error: "boom" };',
     'await (async () => { await rc.cellServiceAction("c22001", "start"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("c22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\",\\"action\\":\\"start\\"}"}], "toast": "⚠️ boom", "pending": null, "stopping": []}',
     'negative: cellServiceAction: ответ ok:false «boom» → тост «⚠️ boom» без подсказки busy'),
    ('csa_reply_result_error_precedence',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, result: { error: "nested" }, error: "outer" };',
     'await (async () => { await rc.cellServiceAction("c22001", "start"); return toastText(); })()',
     '"⚠️ nested"',
     'positive: cellServiceAction: result.error имеет приоритет над error верхнего уровня'),
    ('csa_reply_false_no_text',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false };',
     'await (async () => { await rc.cellServiceAction("c22001", "start"); return toastText(); })()',
     '"⚠️ the action failed"',
     'boundary: cellServiceAction: ok:false без текста → t("cellActionFailed")'),
    ('csa_reply_ok_missing_no_toast',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { result: "whatever" };',
     'await (async () => { await rc.cellServiceAction("c22001", "start"); return toastText(); })()',
     '""',
     'negative: cellServiceAction: ответ без поля ok (не === false) → тоста нет'),
    ('csa_stop_reply_error_keeps_pending',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { ok: false, error: "boom" };',
     'await (async () => { await rc.cellServiceAction("c22001", "stop"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("c22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\",\\"action\\":\\"stop\\"}"}], "toast": "⚠️ boom", "pending": "stop", "stopping": ["c22001"]}',
     'as-is: КАК ЕСТЬ: агент отверг stop (ok:false), но pending/_stoppingCells всё равно висят до таймера 1200 мс — тост «⚠️ boom» при занятых кнопках'),
    ('csa_throw_500_start',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.cellServiceAction("c22001", "start"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("c22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\",\\"action\\":\\"start\\"}"}], "toast": "Error: nope", "pending": null, "stopping": []}',
     'negative: cellServiceAction: api бросил (500 «nope») → catch: тост «Error: nope», pending и stopping очищены'),
    ('csa_throw_500_stop',
     'globalThis.__fetchReply["/api/topology/server-cell/action"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.cellServiceAction("c22001", "stop"); return ({ calls: calls(), toast: toastText(), pending: rc._pendingCellActions.get("c22001") ?? null, stopping: [...rc._stoppingCells] }); })()',
     '{"calls": [{"path": "/api/topology/server-cell/action", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\",\\"action\\":\\"stop\\"}"}], "toast": "Error: nope", "pending": null, "stopping": []}',
     'negative: cellServiceAction: stop при 500 → catch снимает _stoppingCells и pending немедленно (без таймера), тост «Error: nope»'),
    ('dss_success',
     '',
     'await (async () => { await rc.deleteServerSlot("c22001"); return { calls: calls(), toast: toastText(), deleting: [...rc._deletingSlots] }; })()',
     '{"calls": [{"path": "/api/topology/server-slot/delete", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\"}"}], "toast": "", "deleting": []}',
     'positive: deleteServerSlot: на провод {cellId} — без hostId и порта; после успеха _deletingSlots пуст, тоста нет'),
    ('dss_deleting_set_before_wire',
     'globalThis.__snap = null; globalThis.__stubReturns["topology-render.renderTopology"] = () => { if (globalThis.__snap === null) globalThis.__snap = [...rc._deletingSlots]; };',
     'await (async () => { await rc.deleteServerSlot("c22001"); return globalThis.__snap; })()',
     '["c22001"]',
     'positive: deleteServerSlot: id ячейки лежит в _deletingSlots уже на первом renderTopology — до запроса'),
    ('dss_error_500',
     'globalThis.__fetchReply["/api/topology/server-slot/delete"] = { __status: 500, error: "nope" };',
     'await (async () => { await rc.deleteServerSlot("c22001"); return { calls: calls(), toast: toastText(), deleting: [...rc._deletingSlots] }; })()',
     '{"calls": [{"path": "/api/topology/server-slot/delete", "method": "POST", "body": "{\\"cellId\\":\\"c22001\\"}"}], "toast": "Error: nope", "deleting": []}',
     'as-is: КАК ЕСТЬ: при 500 метка снята, а тост показывает сырой String(Error) — «Error: nope»'),
    ('dss_no_cell_sends_nothing',
     '',
     'await (async () => { await rc.deleteServerSlot(""); return { calls: calls(), deleting: [...rc._deletingSlots] }; })()',
     '{"calls": [], "deleting": []}',
     'negative: без id ячейки удалять нечего — ни запроса, ни метки'),
    ('bind_delete_names_the_cell_and_sends_its_id',
     'globalThis.__asked = []; globalThis.__stubReturns["dialogs.appConfirm"] = async (text) => { globalThis.__asked.push(text); return true; };',
     r'''await (async () => {
       const press = async (dataset) => {
         const handlers = [];
         const btn = { dataset, addEventListener: (ev, fn) => handlers.push(fn) };
         const root = { querySelectorAll: (q) => (q === "[data-node-slot-del]" ? [btn] : []) };
         document.body ||= {}; document.body.dataset ||= { vramHoverBound: "1" };
         rc.bindServerSlotControls(root);
         handlers[0]();
         for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
       };
       await press({ nodeSlotDel: "c22001", cellId: "c22001", nodeCellModel: "Qwen3-8B" });
       await press({ nodeSlotDel: "c3f9a02b1", cellId: "c3f9a02b1" });
       return { asked: globalThis.__asked, sent: calls().map((c) => [c.path, c.body]) }; })()''',
     json.dumps({"asked": [en("dlgDeleteCell", cell="Qwen3-8B"), en("dlgDeleteCell", cell="c3f9a02b1")],
                 "sent": [["/api/topology/server-slot/delete", '{"cellId":"c22001"}'],
                          ["/api/topology/server-slot/delete", '{"cellId":"c3f9a02b1"}']]}, ensure_ascii=False),
     '✕ спрашивает о ячейке так, как её называет доска (имя едет с кнопкой), а без имени — её id; negative: ни порта в вопросе, ни порта на проводе'),
    ('bind_boot_sends_the_cell_and_its_switch',
     '',
     r'''await (async () => {
       const handlers = [];
       const btn = { dataset: { nodeCellBoot: "h1", cellId: "c22001", nodeCellBootAction: "enable" }, addEventListener: (ev, fn) => handlers.push(fn) };
       const root = { querySelectorAll: (q) => (q === "[data-node-cell-boot]" ? [btn] : []) };
       document.body ||= {}; document.body.dataset ||= { vramHoverBound: "1" };
       rc.bindServerSlotControls(root);
       await handlers[0]();
       return calls().map((c) => c.body); })()''',
     json.dumps(['{"cellId":"c22001","action":"enable"}']),
     'автозапуск: ↥ шлёт id ячейки со своей кнопки и своё действие; negative: без порта и без машины'),
    ('bind_configure_opens_the_form_of_the_cell',
     KEPT_CELLS,
     r'''await (async () => {
       const handlers = [];
       const btn = { dataset: { nodeCellStart: "h1", cellId: "c3f9a02b1", nodeRole: "host" }, addEventListener: (ev, fn) => handlers.push(fn) };
       const root = { querySelectorAll: (q) => (q === "[data-node-cell-start]" ? [btn] : []) };
       document.body ||= {}; document.body.dataset ||= { vramHoverBound: "1" };
       rc.bindServerSlotControls(root);
       handlers[0]();
       for (let i = 0; i < 5; i++) await new Promise((r) => setImmediate(r));
       return [rc.CELL_FORM.holds("c3f9a02b1"), rc.CELL_FORM.cellId(), globalThis.__fields.llamaRemoteEditOverlay.hidden]; })()''',
     '[true, "c3f9a02b1", false]',
     '⚙ открывает форму той ячейки, чей id на кнопке, — её машину форма берёт из строки доски; окно показано'),
    ('dtca_yes_named',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; st.topology.clients = [{ id: "c1", agents: [{ id: "a1", name: "Scout" }] }];',
     'await (async () => { await rc.deleteTopologyClientAgent("c1", "a1"); return { calls: calls(), toast: toastText(), confirm: globalThis.__msg }; })()',
     '{"calls": [{"path": "/api/topology/client/agent/delete", "method": "POST", "body": "{\\"clientId\\":\\"c1\\",\\"agentId\\":\\"a1\\"}"}], "toast": "Removed Scout", "confirm": {"msg": "Delete agent “Scout” from the list?", "opts": {"title": "Delete agent", "confirmLabel": "Delete"}}}',
     'positive: deleteTopologyClientAgent: диалог с именем агента «Scout» и своим заголовком (раньше — общий «Confirm service action?»), на провод {clientId, agentId}; обещания «вернётся с heartbeat» больше нет — вернуть его некому'),
    ('dtca_ports_named',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return true; }; st.topology.clients = [{ id: "c1", agents: [{ id: "a1", name: "Scout" }, { id: "a2", name: "Other" }] }]; st.topology.assignments = { c1: { assignments: [{ agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23001" }, { role: "fallback", proxyId: "skynet:proxy:23002" }] }, { agentId: "a2", routes: [{ role: "primary", proxyId: "skynet:proxy:23009" }] }] } }; globalThis.__fetchReply["/api/topology/client/agent/delete"] = { ok: true, freedPorts: [23001] };',
     'await (async () => { await rc.deleteTopologyClientAgent("c1", "a1"); return { toast: toastText(), confirm: globalThis.__msg.msg }; })()',
     '{"toast": "Removed Scout; freed ports: :23001", "confirm": "Delete agent “Scout” from the list?\\n\\nIts ports :23001 :23002 stay free: bind them to another agent, or delete them with ✎ in Routing."}',
     'positive: у агента есть порты — диалог называет его порты (оба, по порядку ролей, без чужого :23009), говорит, что они останутся, и где их удалить (✎ в Маршрутизации — «окна порта» для порта без клиента не было); тост — какие порты больше никто не держит'),
    ('dtca_one_port_in_the_singular',
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__msg = { msg, opts }; return false; }; st.topology.clients = [{ id: "c1", agents: [{ id: "a1", name: "Scout" }] }]; st.topology.assignments = { c1: { assignments: [{ agentId: "a1", routes: [{ role: "primary", proxyId: "skynet:proxy:23001" }] }] } };',
     'await (async () => { await rc.deleteTopologyClientAgent("c1", "a1"); return { calls: calls(), confirm: globalThis.__msg.msg }; })()',
     '{"calls": [], "confirm": "Delete agent “Scout” from the list?\\n\\nIts port :23001 stays free: bind it to another agent, or delete it with ✎ in Routing."}',
     'один порт — в единственном числе (было «Its ports :23001»); negative: «отмена» — запроса нет'),
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
    ('rsif_empty_false',
     '',
     'rc.remoteStartupInFlight()',
     'false',
     'negative: remoteStartupInFlight: ничего не стартует → false'),
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
     'as-is: пробелы — это СНЯТИЕ псевдонима, а не отмена (в отличие от имени нового клиента входа, где пробелы = отмена: consumers.js); расхождение зафиксировано'),
    ('route_wait_clamped_silently',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "999999";'
     ' st.setTopology({ proxies: [], clients: [], routers: [{ id: "r1", graph: { nodes: [], edges: [], inputs: {} } }], assignments: {}, nodes: [] });',
     'await (async () => { await rc.editRouteWait("p1", 30); return { saved: (globalThis.__stubCalls || []).length, toast: toastText() }; })()',
     '{"saved": 0, "toast": ""}',
     'as-is: 999999 обрезается до 86400 БЕЗ единого слова оператору — он видит не то число, которое ввёл (saveRouters под заглушкой, сюда пинится молчание)'),
    ('route_wait_not_a_number_refused',
     'globalThis.__stubReturns["dialogs.appPrompt"] = async () => "30s";',
     'await (async () => { await rc.editRouteWait("p1", 30); return { calls: calls(), toast: toastText() }; })()',
     '{"calls": [], "toast": "Enter a number of seconds, or leave it empty to use the port\'s own wait budget."}',
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
    ('nvidia_sources_skip_a_controller_that_cannot_read_its_gpu',
     '',
     '(() => { const host = (id, state, gpus) => ({ id, name: id.toUpperCase(), state, gpus }); const top = { hosts: [host("box-a", "online", [{ name: "RTX" }]), host("box-b", "offline", [{ name: "RTX" }]), host("box-c", "online", [])] };'
     ' const ids = (mon) => rc.nvidiaSmiSources(top, mon, () => "me").map((s) => s.id);'
     ' return [ids({ latest: { gpu: { ok: false, error: "no scout" } } }), ids({ latest: { gpu: { ok: true } } }), ids(null), rc.nvidiaSmiSources({ hosts: [] }, { latest: { gpu: { ok: false } } }, () => "me")]; })()',
     '[["box-a"],["local","box-a"],["local","box-a"],[]]',
     'контроллер, который не читает свою карту (в контейнере без скаута своей машины), — не источник; источников нет — пусто, и ящик nvidia-smi на краю доски прячется (был над карточкой пула NAS); negative: показаний ещё нет — контроллер в списке, как раньше; машины без карты и молчащие не в списке'),
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
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirmTyped"] = async (msg, phrase, opts) => { globalThis.__msg = { msg, phrase, opts }; return true; };'
     ' st.topology.hosts = [{ id: "h2", name: "Box B", state: "online", ageSeconds: 20 }];'
     ' globalThis.__fetchReply["/api/topology/scout/disconnect"] = { ok: true, hostId: "h2", unpaired: true };',
     'await (async () => { await rc.disconnectScout("h2"); return { calls: calls(), toast: toastText(), confirm: globalThis.__msg }; })()',
     json.dumps({"calls": [{"path": "/api/topology/scout/disconnect", "method": "POST", "body": "{\"hostId\":\"h2\"}"}],
                 "toast": en("scoutDisconnected", name="Box B"),
                 "confirm": {"msg": en("dlgDisconnectScout", name="Box B"), "phrase": "Box B",
                             "opts": {"confirmLabel": en("nodeDisconnectScout"), "detail": "Box B"}}}, ensure_ascii=False),
     'positive: скаут отвечает — диалог «отключить» просит ВПИСАТЬ имя машины (не только нажать), на провод только {hostId}; тост — скаут отключён'),
    ('disconnect_silent_scout_forgets',
     'globalThis.__msg = null; globalThis.__phrase = null; globalThis.__stubReturns["dialogs.appConfirmTyped"] = async (msg, phrase) => { globalThis.__msg = msg; globalThis.__phrase = phrase; return true; };'
     ' st.topology.hosts = [{ id: "h2", name: "Box B", state: "stale", ageSeconds: 600 }];'
     ' globalThis.__fetchReply["/api/topology/scout/disconnect"] = { ok: true, hostId: "h2", unpaired: false };',
     'await (async () => { await rc.disconnectScout("h2"); return { toast: toastText(), msg: globalThis.__msg, phrase: globalThis.__phrase }; })()',
     json.dumps({"toast": en("scoutForgottenSilent", name="Box B"),
                 "msg": en("dlgForgetSilentScout", name="Box B", ago=en("nodeScoutLastReport", ago="10m")),
                 "phrase": "Box B"},
                ensure_ascii=False),
     'positive: скаут молчит — диалог говорит «забыть» и сколько он молчит и тоже просит вписать имя машины, а тост — что забыта, скаут не ответил'),
    ('disconnect_declined',
     'globalThis.__stubReturns["dialogs.appConfirmTyped"] = async () => false; st.topology.hosts = [{ id: "h2", name: "Box B", state: "online" }];',
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
     'globalThis.__msg = null; globalThis.__stubReturns["dialogs.appConfirmTyped"] = async (msg, phrase) => { globalThis.__msg = [msg, phrase]; return false; };',
     'await (async () => { await rc.disconnectScout("h9"); return globalThis.__msg; })()',
     json.dumps([en("dlgDisconnectScout", name="h9"), "h9"], ensure_ascii=False),
     'boundary: записи нет — диалог называет id и просит вписать его; «молчит» он сказать не может, и не говорит'),
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
    ('engine_no_download_from_the_board',
     '',
     '[typeof rc.pullEngineModel, typeof rc.pullEngineButton]',
     '["undefined","undefined"]',
     "defect-guard: окна «скачать модель в Ollama / LM Studio» нет — скачивания через караван нет (оператор, 2026-09-27)"),
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
     ERC_SETUP + ' globalThis.__fetchReply["/api/topology/server-slot/add"] = { ok: true, slot: { id: "c3f9a02b1", hostId: "h1" }, cell: { id: "c3f9a02b1", hostId: "h1" } };',
     'await (async () => { await rc.reserveEngineCell("h1", "ollama", "qwen2.5:0.5b"); return ' + ERC_RESULT + '; })()',
     json.dumps({"calls": rsc_add({"hostId": "h1", "engine": "ollama", "model": "qwen2.5:0.5b"}), "toast": "", "asked": [],
                 "reserving": [], "fresh": ["c3f9a02b1"], "snap": [["h1", {"startedAt": 1700000100000}]]}),
     'positive: «+» у модели не спрашивает ничего — строка уже назвала движок и модель; на провод {hostId, engine, '
     'model}; спиннер машины, пока ячейка не на доске; вспышка новой ячейки — по id из ответа контроллера'),
    ('erc_plus_takes_no_port',
     ERC_SETUP + ' st.topology.nodes = [{ id: "h1", servers: [{ cellId: "c22001", port: 22001 }] }]; st.topology.proxies = [{ port: 22002 }];',
     'await (async () => { await rc.reserveEngineCell("h1", "lmstudio", "google/gemma-4-e4b"); return { body: JSON.parse(calls()[0].body), snap: globalThis.__snap }; })()',
     json.dumps({"body": {"hostId": "h1", "engine": "lmstudio", "model": "google/gemma-4-e4b"}, "snap": [["h1", {"startedAt": 1700000100000}]]}),
     'negative: резерв не берёт порта — ни в запросе, ни в метке машины: порт ячейке даёт её скаут при старте (раньше — «следующий свободный по флоту», мимо ячейки 22001 и прокси 22002)'),
    ('erc_one_reserve_at_a_time',
     ERC_SETUP + ' rc._reservingCells.set("h1", { startedAt: 1 });',
     'await (async () => { await rc.reserveEngineCell("h1", "ollama", "qwen2.5:0.5b"); return ' + ERC_RESULT + '; })()',
     json.dumps({"calls": [], "toast": "", "asked": [], "reserving": [["h1", {"startedAt": 1}]], "fresh": [],
                 "snap": None}),
     'negative: машина уже делает ячейку — второй «+» не делает вторую: ни запроса, ни рендера, прежний спиннер не тронут'),
    ('erc_other_machine_does_not_block',
     ERC_SETUP + ' rc._reservingCells.set("h2", { startedAt: 1 });',
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
                 "snap": [["h1", {"startedAt": 1700000100000}]]}),
     'negative: отказ контроллера (engine_cells.py) — его словами; спиннер снят, вспышки нет'),
    # What a reserve does with the controller's answer (postReserve — the one way
    # in since the Reserve-cell stub left in 1.3.393).
    ('erc_reply_names_the_cell_by_its_id',
     ERC_SETUP + ' globalThis.__fetchReply["/api/topology/server-slot/add"] = { ok: true, cell: { id: "c0a1b2c3d", hostId: "h1" } };',
     'await (async () => { await rc.reserveEngineCell("h1", "ollama", "qwen2.5:0.5b"); return [...rc._newReservedCells]; })()',
     '["c0a1b2c3d"]',
     'positive: вспыхивает ячейка по id, который ей дал контроллер (cell.id ответа)'),
    ('erc_reply_without_a_cell_flashes_nothing',
     ERC_SETUP + ' globalThis.__fetchReply["/api/topology/server-slot/add"] = { ok: true, slot: { hostId: "h1", port: 22008 } };',
     'await (async () => { await rc.reserveEngineCell("h1", "ollama", "qwen2.5:0.5b"); return { fresh: [...rc._newReservedCells], reserving: [...rc._reservingCells.entries()] }; })()',
     '{"fresh": [], "reserving": []}',
     'negative: ответ без cell.id — вспыхивать нечему: ключ не выдумывается ни из машины и порта (так было: «h1:22001»), ни из порта ответа'),
    ('erc_button_carries_its_line',
     ERC_SETUP,
     'await (async () => { await rc.reserveEngineButton({ dataset: { engineReserve: "h1", engineKind: "lmstudio", engineModel: "google/gemma-4-e4b" } }); return calls(); })()',
     json.dumps(rsc_add({"hostId": "h1", "engine": "lmstudio", "model": "google/gemma-4-e4b"})),
     'positive: кнопка «+» несёт машину, движок и модель — так, как их пишет shelfLineHtml'),
    # ── Apply without a model: said first, nothing asked, nothing sent ──
    ('apply_without_model_says_so_first',
     'let asked = 0; globalThis.__stubReturns["dialogs.appConfirm"] = async () => { asked += 1; return true; };'
     ' globalThis.__asked = () => asked; F({ "tr-MODEL_FILE": { value: "" } });',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), globalThis.__asked(), calls()]; })()',
     json.dumps([en("selectModel"), 0, []], ensure_ascii=False),
     'модель не выбрана («＋ Add model» открывает пустое поле) — сразу «выберите модель», без вопроса «применить?» и без '
     'запроса (раньше сначала спрашивалось, потом отказывалось)'),
    # ── vLLM without a path: a model picked in the list is not a path on THIS machine ──
    ('apply_vllm_with_a_pick_and_no_path_names_the_pick',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }] }); ' + OPEN_FORM +
     ' F({ "tr-RUNNER": { value: "vllm" }, "tr-VLLM_MODEL": { value: "" }, "tr-MODEL_FILE": { value: "Omni-AWQ/org/AWQ" },'
     ' llamaRemoteEditOverlay: { hidden: false }, llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), calls().map((c) => [c.path, JSON.parse(c.body).config.VLLM_MODEL])]; })()',
     json.dumps([en("saved"), [["/api/topology/server-cell/save-config", "Omni-AWQ/org/AWQ"]]]),
     'defect-history (2026-10-17, 2026-11-03): выбор в списке — это место среди моделей контроллера, на любой машине: путь на самой машине больше не нужен, и Apply не просит его вписать'),
    ('apply_vllm_with_nothing_picked_still_says_select_a_model',
     'F({ "tr-RUNNER": { value: "vllm" }, "tr-VLLM_MODEL": { value: "" }, "tr-MODEL_FILE": { value: "  " } });',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), calls()]; })()',
     json.dumps([en("selectModel"), []], ensure_ascii=False),
     'negative: ни выбора, ни пути — по-прежнему «выберите модель»'),
    ('apply_vllm_with_a_typed_path_goes_on',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }] }); ' + OPEN_FORM +
     ' F({ "tr-RUNNER": { value: "vllm" }, "tr-VLLM_MODEL": { value: "/mnt/lib/Omni-AWQ" }, "tr-MODEL_FILE": { value: "Omni-AWQ/org/AWQ" },'
     ' llamaRemoteEditOverlay: { hidden: false }, llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), calls().map((c) => c.path)]; })()',
     json.dumps([en("saved"), ["/api/topology/server-cell/save-config"]]),
     'negative: путь вписан — запрос уходит как раньше, выбор в списке ему не мешает'),
    # ── Flash attention and the V cache: the pair llama.cpp stops at is never offered, and never sent ──
    ('new_cell_opens_with_flash_attention_on',
     'F({ "tr-ENABLE_FLASH_ATTN": { checked: false }, "tr-CACHE_TYPE_V": { value: "" }, "tr-CACHE_TYPE_K": { value: "" } }); ' + OPEN_FORM,
     '[globalThis.__fields["tr-ENABLE_FLASH_ATTN"].checked, globalThis.__fields["tr-CACHE_TYPE_K"].value, globalThis.__fields["tr-CACHE_TYPE_V"].value]',
     '[true, "q8_0", "q8_0"]',
     'defect-history (2026-10-14): форма новой ячейки открывалась с кэшем q8_0 и ВЫКЛЮЧЕННЫМ flash attention — '
     'llama.cpp с такой парой не запускается («quantized V cache requires flash_attn…»), ячейка упала 4 раза; теперь он включён'),
    ('new_cell_keeps_the_machines_own_flash_attention',
     'st.setState({ ...st.state, config: { ENABLE_FLASH_ATTN: "0" } }); F({ "tr-ENABLE_FLASH_ATTN": { checked: true } }); ' + OPEN_FORM,
     'globalThis.__fields["tr-ENABLE_FLASH_ATTN"].checked',
     'false',
     'negative: что сказано в настройках машины («0»), остаётся как сказано — умолчание «включён» стоит только там, где сказать было нечего'),
    # ── The window: left empty, it asks for the one the model was trained for ──
    ('new_cell_opens_with_an_empty_window',
     'F({ "tr-CTX_SIZE": { value: "4096" } }); ' + OPEN_FORM,
     'globalThis.__fields["tr-CTX_SIZE"].value',
     '""',
     'defect-history (2026-10-26): новая ячейка открывалась с окном 4096, которого никто не вводил (у контроллера на NAS своего '
     'CTX_SIZE нет), — и у пяти ячеек llama.cpp осталось 4096; теперь поле пустое: старт попросит окно обучения модели'),
    ('new_cell_keeps_the_machines_own_window',
     'st.setState({ ...st.state, config: { CTX_SIZE: "32768" } }); F({ "tr-CTX_SIZE": { value: "" } }); ' + OPEN_FORM,
     'globalThis.__fields["tr-CTX_SIZE"].value',
     '"32768"',
     'negative: окно, сказанное в настройках машины, остаётся как сказано'),
    ('cell_form_says_its_window_field_and_the_models_most',
     'st.setState({ ...st.state, runners: [{ id: "llama-server", modelField: "MODEL_FILE" }, { id: "vllm", contextField: "MAX_MODEL_LEN", modelField: "VLLM_MODEL" }],'
     ' models: [{ path: "m/a.gguf", ggufMeta: { contextLength: 131072 } }, { path: "Qwen/Qwen3-8B/BF16", contextLength: 40960 }] });'
     ' F({ "tr-RUNNER": { value: "" }, "tr-MODEL_FILE": { value: "m/a.gguf" }, "tr-VLLM_MODEL": { value: "Qwen/Qwen3-8B/BF16" } });',
     '(() => { const f = rc.CELL_FORM; const a = [f.windowField(), f.modelWindow()]; globalThis.__fields["tr-RUNNER"].value = "vllm";'
     ' const b = [f.windowField(), f.modelWindow()]; globalThis.__fields["tr-VLLM_MODEL"].value = "elsewhere/x"; return [...a, ...b, f.modelWindow()]; })()',
     '["CTX_SIZE",131072,"MAX_MODEL_LEN",40960,0]',
     'форма ячейки говорит окну ячейки поле окна своего раннера и максимум его модели — из заголовка GGUF или конфига '
     'чекпойнта; negative: модели нет в библиотеке — 0, а не выдуманное'),
    # ── Jinja: llama.cpp's own default, and the builder says OFF out loud ──
    ('new_cell_opens_with_jinja_on',
     'F({ "tr-ENABLE_JINJA": { checked: false } }); ' + OPEN_FORM,
     'globalThis.__fields["tr-ENABLE_JINJA"].checked',
     'true',
     'defect-history (2026-10-26): новая ячейка открывалась с выключенным Jinja, сборщик писал --no-jinja, и ячейка gemma-4 из '
     'мастера ответила на первый вопрос 500 «this custom template is not supported, try using --jinja»; теперь включён'),
    ('new_cell_keeps_the_machines_own_jinja',
     'st.setState({ ...st.state, config: { ENABLE_JINJA: "0" } }); F({ "tr-ENABLE_JINJA": { checked: true } }); ' + OPEN_FORM,
     'globalThis.__fields["tr-ENABLE_JINJA"].checked',
     'false',
     'negative: что сказано в настройках машины («0»), остаётся как сказано — «включён» стоит только там, где сказать было нечего'),
    ('apply_refuses_quantized_v_cache_without_flash_attention',
     'let asked = 0; globalThis.__stubReturns["dialogs.appConfirm"] = async () => { asked += 1; return true; }; globalThis.__asked = () => asked;'
     ' F({ "tr-MODEL_FILE": { value: "m/model.gguf" }, "tr-ENABLE_FLASH_ATTN": { checked: false }, "tr-CACHE_TYPE_V": { value: "q8_0" } });',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), globalThis.__asked(), calls()]; })()',
     json.dumps([en("kvCacheNeedsFlash", type="q8_0"), 0, []], ensure_ascii=False),
     'сжатый кэш V при выключенном flash attention — отказ сразу, словами с типом и выходом, без вопроса «применить?» и без запроса '
     '(раньше ячейка падала 4 раза, а карточка показывала последнюю строку лога)'),
    ('apply_with_flash_attention_on_goes_on',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }] }); ' + OPEN_FORM +
     ' F({ "tr-MODEL_FILE": { value: "m/model.gguf" }, "tr-ENABLE_FLASH_ATTN": { checked: true }, "tr-CACHE_TYPE_V": { value: "q8_0" },'
     ' llamaRemoteEditOverlay: { hidden: false }, llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), calls().map((c) => c.path)]; })()',
     json.dumps([en("saved"), ["/api/topology/server-cell/save-config"]]),
     'negative: та же пара с включённым flash attention уходит как раньше'),
    ('apply_with_f16_v_cache_and_flash_attention_off_goes_on',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }] }); ' + OPEN_FORM +
     ' F({ "tr-MODEL_FILE": { value: "m/model.gguf" }, "tr-ENABLE_FLASH_ATTN": { checked: false }, "tr-CACHE_TYPE_V": { value: "f16" },'
     ' llamaRemoteEditOverlay: { hidden: false }, llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), calls().map((c) => c.path)]; })()',
     json.dumps([en("saved"), ["/api/topology/server-cell/save-config"]]),
     'negative: flash attention выключен, но кэш V из чисел (f16) — сохраняется: отказ только для сжатого'),
    # ── A cell's Apply only SAVES: a running cell keeps its old settings until it restarts, and the toast says so ──
    ('apply_of_a_stopped_cell_says_saved',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }],'
     ' nodes: [{ id: "h1", role: "host", servers: [{ isSlot: true, clientId: "h1", cellId: "c22013", port: null, phase: "stopped" }] }] });'
     ' try { rc.openLlamaRemoteEdit("h1", "gpu0", [], "c22013"); } catch (e) {}'
     ' F({ "tr-MODEL_FILE": { value: "m/model.gguf" }, llamaRemoteEditOverlay: { hidden: false },'
     ' llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), calls().map((c) => c.path), globalThis.__fields.llamaRemoteEditOverlay.hidden]; })()',
     json.dumps([en("saved"), ["/api/topology/server-cell/save-config"], True]),
     'positive: Apply остановленной ячейки только сохраняет — «Saved.», один запрос save-config, окно закрыто; запуска нет'),
    # ── The new-cell wizard's Create: its button was the question, and Apply does not ask it again (1.3.638) ──
    ('apply_confirmed_by_its_caller_asks_nothing',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }],'
     ' nodes: [{ id: "h1", role: "host", servers: [{ isSlot: true, clientId: "h1", cellId: "c22013", port: null, phase: "stopped" }] }] });'
     ' try { rc.openLlamaRemoteEdit("h1", "gpu0", [], "c22013"); } catch (e) {}'
     ' globalThis.__asked = []; globalThis.__stubReturns["dialogs.appConfirm"] = async (text) => { globalThis.__asked.push(text); return false; };'
     ' F({ "tr-MODEL_FILE": { value: "m/model.gguf" }, llamaRemoteEditOverlay: { hidden: false },'
     ' llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { const asked = await rc.submitRemoteLlamaStart(); const before = [asked, globalThis.__asked.length, calls().length];'
     ' const sure = await rc.submitRemoteLlamaStart({ confirmed: true }); return [before, sure, globalThis.__asked.length, calls().map((c) => c.path)]; })()',
     json.dumps([[False, 1, 0], True, 1, ["/api/topology/server-cell/save-config"]]),
     'negative: Apply спрашивает, и «нет» не сохраняет ничего; positive: вызов от «Создать» мастера (confirmed) не спрашивает второй раз и сохраняет'),
    ('apply_of_a_running_cell_says_it_keeps_its_old_settings',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }],'
     ' nodes: [{ id: "h1", role: "host", servers: [{ isSlot: true, clientId: "h1", cellId: "c22013", port: 22013, phase: "running", gpuMem: { "0": 18350, "1": 24364 } }] }] });'
     ' try { rc.openLlamaRemoteEdit("h1", "gpu0", [], "c22013"); } catch (e) {}'
     ' F({ "tr-MODEL_FILE": { value: "m/model.gguf" }, llamaRemoteEditOverlay: { hidden: false },'
     ' llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), calls().map((c) => c.path), globalThis.__fields.llamaRemoteEditOverlay.hidden]; })()',
     json.dumps([en("savedKeepsRunning"), ["/api/topology/server-cell/save-config"], True]),
     'defect-history (2026-10-17): Apply работающей ячейки закрывал окно на «Saved.», будто изменение вступило в силу, — а запущенный сервер держит '
     'прежние настройки до перезапуска (выбранное на 70B деление между картами «ничего не сделало»); теперь тост говорит это словами'),
    ('apply_of_a_cell_that_runs_nothing_yet_says_saved',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }],'
     ' nodes: [{ id: "h1", role: "host", servers: [{ isSlot: true, clientId: "h1", cellId: "c22013", port: 22013, phase: "starting", gpuMem: {} },'
     ' { isSlot: true, clientId: "h1", cellId: "c3f9a02b1", port: 22014, phase: "running", gpuMem: { "0": 100 } }] }] });'
     ' try { rc.openLlamaRemoteEdit("h1", "gpu0", [], "c22013"); } catch (e) {}'
     ' F({ "tr-MODEL_FILE": { value: "m/model.gguf" }, llamaRemoteEditOverlay: { hidden: false },'
     ' llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { await rc.submitRemoteLlamaStart(); return toastText(); })()',
     json.dumps(en("saved")),
     'negative: другая ячейка той же машины работает, а эта ещё нет — «Saved.»: вопрос о ЭТОЙ ячейке (по её id), не о машине'),
    # ── The compute target follows the fields that decide the cards: a vLLM cell's TENSOR_PARALLEL and ENV pin ──
    # The form's `change` listener is bound once, when the form first opens; it reads the fields by id when it fires.
    ('change_of_tensor_parallel_redraws_the_cards_tile',
     'const form = { addEventListener: (ev, fn) => { if (ev === "change") (globalThis.__trListeners ||= {}).form ||= fn; } };'
     ' const box = { innerHTML: "", querySelectorAll: () => [], querySelector: () => null }; globalThis.__box = box;'
     ' const two = [{ index: 0, name: "NVIDIA GeForce RTX 3090", memoryTotalMiB: 24576, memoryFreeMiB: 24000, memoryUsedMiB: 576 },'
     ' { index: 1, name: "NVIDIA GeForce RTX 5090", memoryTotalMiB: 32607, memoryFreeMiB: 32000, memoryUsedMiB: 607 }];'
     ' F({ llamaRemoteEditForm: form, "tr-computeTarget": box, "tr-RUNNER": { value: "vllm" }, "tr-TENSOR_PARALLEL": { value: "1" }, "tr-ENV": { value: "" } });'
     ' try { rc.openLlamaRemoteEdit("h1", "gpu0", two, ""); } catch (e) {}'   # the machine's cards: memory.js reads them from THIS module instance
     ' try { (await import(pathToFileURL(process.env.JS_ROOT + "/remote-cells.js").href + "?tp-tile")).openLlamaRemoteEdit("h1", "gpu0", two, ""); } catch (e) {}'
     ' globalThis.__fields = { ...globalThis.__fields, "tr-computeTarget": box, "tr-RUNNER": { value: "vllm" }, "tr-TENSOR_PARALLEL": { value: "1" }, "tr-ENV": { value: "" } };',
     '(() => { const main = () => (globalThis.__box.innerHTML.match(/data-compute="gpu"[^>]*>[\\s\\S]*?compute-card-main">([^<]*)</) || [])[1] ?? null;'
     ' const fire = (id, value) => { globalThis.__fields["tr-" + id] = { value }; globalThis.__box.innerHTML = ""; globalThis.__trListeners.form({ target: { id: "tr-" + id } }); return main(); };'
     ' return [fire("TENSOR_PARALLEL", "2"), fire("TENSOR_PARALLEL", "1"), fire("ENV", "CUDA_VISIBLE_DEVICES=1"), fire("CTX_SIZE", "4096")]; })()',
     json.dumps(["2/2 · 55.8 GB", "1/2 · 24.0 GB", "1/2 · 31.8 GB", None]),
     'defect-history (2026-10-17): у vLLM плитка GPU называла одну карту, что бы ни стояло в TENSOR_PARALLEL; теперь перерисовывается при смене TENSOR_PARALLEL и ENV (пин карты) — '
     'и только при них: negative: чужое поле (CTX_SIZE) плитку не трогает'),
    ('apply_for_another_runner_ignores_the_llama_fields',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }] }); ' + OPEN_FORM +
     ' F({ "tr-RUNNER": { value: "vllm" }, "tr-VLLM_MODEL": { value: "org/m" }, "tr-ENABLE_FLASH_ATTN": { checked: false }, "tr-CACHE_TYPE_V": { value: "q8_0" },'
     ' llamaRemoteEditOverlay: { hidden: false }, llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { await rc.submitRemoteLlamaStart(); return [toastText(), calls().map((c) => c.path)]; })()',
     json.dumps([en("saved"), ["/api/topology/server-cell/save-config"]]),
     'negative: у vLLM поля формы llama.cpp скрыты и ничего не значат — «сжатый кэш V без flash attention» его сохранение не останавливает'),
    # ── Speculation switched on: the type the draft is for, as a model pick writes it ──
    # The switch is bound once, when the form opens first; its handler reads the
    # fields by id when it fires, so the pin keeps the handler it caught.
    ('spec_switch_names_the_draft_type',
     'const sw = { checked: false, closest: () => null,'
     ' addEventListener: (ev, fn) => { if (ev === "change") (globalThis.__trListeners ||= {}).spec ||= fn; } };'
     ' globalThis.__sw = sw; F({ "tr-SPEC_ENABLED": sw });'
     ' try { (await import(pathToFileURL(process.env.JS_ROOT + "/remote-cells.js").href + "?spec-switch")).openLlamaRemoteEdit("h1", "gpu0", [], ""); } catch (e) {}',
     '(() => { const sw = globalThis.__sw; const fire = (draft, family) => {'
     ' st.setState({ ...st.state, models: [{ path: "m/model.gguf", familyDefaults: family ? { SPEC_TYPE: family } : {} }] });'
     ' F({ "tr-SPEC_ENABLED": sw, "tr-SPEC_TYPE": { value: "stale" }, "tr-SPEC_DRAFT_MODEL_FILE": { value: draft }, "tr-MODEL_FILE": { value: "m/model.gguf" } });'
     ' sw.checked = true; globalThis.__trListeners.spec({ target: sw }); const on = globalThis.__fields["tr-SPEC_TYPE"].value;'
     ' sw.checked = false; globalThis.__trListeners.spec({ target: sw }); return [on, globalThis.__fields["tr-SPEC_TYPE"].value]; };'
     ' return [fire("m/dflash-x.gguf", "draft-mtp"), fire("g/mtp/head.gguf", ""), fire("", "draft-eagle3"), fire("", "")]; })()',
     json.dumps([["draft-dflash", "none"], ["draft-mtp", "none"], ["draft-eagle3", "none"], ["draft-mtp", "none"]]),
     'включённая спекуляция пишет тип черновика, как выбор модели: DFlash остаётся DFlash (раньше — тип семейства '
     'draft-mtp поверх него), голова из папки mtp/ — draft-mtp; без файла — тип семейства, иначе draft-mtp; '
     'выключенная — none, слово сборщика для «нет» (2026-11-07; было пусто)'),
    # Switched off, the start loads no draft: the builder's rule (cell-plan.js CellDraft) over the form as the switch left it.
    # Until 2026-11-07 off wrote an empty type and kept the file, and the builder launches a file with no type by its own.
    ('spec_switch_off_loads_no_draft',
     'const sw = { type: "checkbox", checked: true, closest: () => null,'
     ' addEventListener: (ev, fn) => { if (ev === "change") (globalThis.__trListeners ||= {}).spec ||= fn; } };'
     ' F({ "tr-SPEC_ENABLED": sw });'
     ' try { (await import(pathToFileURL(process.env.JS_ROOT + "/remote-cells.js").href + "?spec-switch")).openLlamaRemoteEdit("h1", "gpu0", [], ""); } catch (e) {}'
     ' globalThis.__P = await import(pathToFileURL(process.env.JS_ROOT + "/cell-plan.js").href);'
     ' globalThis.__FM = await import(pathToFileURL(process.env.JS_ROOT + "/form.js").href);',
     '(() => { const P = globalThis.__P; const file = "Qwen3.8-27B-GGUF/unsloth/default/mtp-Qwen3.8-27B-Q4_0.gguf";'
     ' st.setState({ ...st.state, models: [{ path: "m/model.gguf", familyDefaults: {} }] });'
     ' const sw = { type: "checkbox", checked: true, closest: () => null,'
     '   dispatchEvent: (ev) => { if (ev.type === "change") globalThis.__trListeners.spec({ target: sw }); } };'
     ' F({ "tr-SPEC_ENABLED": sw, "tr-SPEC_TYPE": { value: "draft-mtp" }, "tr-SPEC_DRAFT_MODEL_FILE": { value: file }, "tr-MODEL_FILE": { value: "m/model.gguf" } });'
     ' const f = () => globalThis.__fields; const rule = () => P.CellDraft.start(P.CellFields.ofConfig({ SPEC_TYPE: f()["tr-SPEC_TYPE"].value,'
     '   SPEC_DRAFT_MODEL_FILE: f()["tr-SPEC_DRAFT_MODEL_FILE"].value }));'
     ' sw.checked = false; globalThis.__trListeners.spec({ target: sw }); const off = rule();'
     # What the form's Apply sends (readConfigForm): the config the controller saves and builds the start's command from.
     ' const sent = globalThis.__FM.readConfigForm("tr-");'
     ' const offWords = [f()["tr-SPEC_TYPE"].value, f()["tr-SPEC_DRAFT_MODEL_FILE"].value === file, off.loads, off.spec,'
     '   sent.SPEC_TYPE, sent.SPEC_DRAFT_MODEL_FILE === file];'
     ' sw.checked = true; globalThis.__trListeners.spec({ target: sw }); const on = rule();'
     ' const onWords = [f()["tr-SPEC_TYPE"].value, on.loads, on.spec];'
     # The new-cell wizard's switch writes the form through CellForm.set, which fires the switch's own change.
     ' rc.CELL_FORM.set("SPEC_ENABLED", "0"); const wiz = [sw.checked, f()["tr-SPEC_TYPE"].value, rule().loads];'
     ' rc.CELL_FORM.set("SPEC_ENABLED", "1"); wiz.push(f()["tr-SPEC_TYPE"].value, rule().loads);'
     ' return [offWords, onWords, wiz, P.CellDraft.OFF]; })()',
     json.dumps([["none", True, False, None, "none", True], ["draft-mtp", True, "draft-mtp"], [False, "none", False, "draft-mtp", True], "none"]),
     'positive (дефект 2026-11-07): выключенная спекуляция пишет none, файл черновика остаётся в поле, а старт по правилу сборщика его '
     'не грузит и типа не говорит; включённая снова — тип самого файла, файл грузится; так же — переключатель мастера новой ячейки '
     '(CellForm.set); negative: «выключено» больше не пустой тип, при котором сборщик грузил названный файл'),
    # ── A start that is already under way: a notice that names the machine, not an error ──
    # The form's own fields are set after it opens: opening it needs the whole page.
    ('new_cell_save_makes_it_and_holds_its_id',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }] }); ' + OPEN_FORM +
     ' F({ "tr-MODEL_FILE": { value: "m/model.gguf" }, llamaRemoteEditOverlay: { hidden: false },'
     ' llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;'
     ' globalThis.__fetchReply["/api/topology/server-cell/save-config"] = { ok: true, hostId: "h1", cellId: "c3f9a02b1" };',
     'await (async () => { const f = rc.CELL_FORM; const before = [f.holds(rc.CellForm.newKey("h1")), f.cellId()];'
     ' const first = await f.save({ confirmed: true }); const after = [f.holds("c3f9a02b1"), f.holds(rc.CellForm.newKey("h1")), f.cellId(), [...rc._newReservedCells]];'
     ' const second = await f.save({ confirmed: true });'
     ' const sent = calls().map((c) => { const b = JSON.parse(c.body); return [c.path, b.cellId ?? null, b.hostId ?? null, "port" in b, "PORT" in b.config]; });'
     ' return { before, first, after, second, sent, toast: toastText() }; })()',
     json.dumps({"before": [True, ""], "first": True, "after": [True, False, "c3f9a02b1", ["c3f9a02b1"]], "second": True,
                 "sent": [["/api/topology/server-cell/save-config", None, "h1", False, False],
                          ["/api/topology/server-cell/save-config", "c3f9a02b1", None, False, False]], "toast": en("saved")}),
     'новая ячейка (мастер, «＋ Add model»): Apply сохраняет её по машине — без cellId и без порта, — контроллер делает ячейку и называет её '
     'id; форма держит её с этих пор по id, и второй Apply сохраняет ту же ячейку, а не делает вторую; вспышка — по id; negative: в конфиге нет PORT'),
    ('new_cell_save_refused_stays_new',
     'st.setTopology({ ...st.topology, hosts: [{ id: "h1", name: "box-a", ip: "192.0.2.21", gpus: [] }] }); ' + OPEN_FORM +
     ' F({ "tr-MODEL_FILE": { value: "m/model.gguf" }, llamaRemoteEditOverlay: { hidden: false },'
     ' llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;'
     ' globalThis.__fetchReply["/api/topology/server-cell/save-config"] = { __status: 500, error: "disk full" };',
     'await (async () => { const f = rc.CELL_FORM; const said = await f.save({ confirmed: true }); return [said, f.cellId(), f.holds(rc.CellForm.newKey("h1")), [...rc._newReservedCells], toastText()]; })()',
     json.dumps([False, "", True, [], "Error: disk full"]),
     'negative: отказ контроллера — ячейка не сделана: форма держит её как новую, id не выдуман, вспышки нет, отказ сказан'),
    ('apply_sends_no_port_even_with_a_port_input_on_the_page',
     KEPT_CELLS + ' rc.CELL_FORM.fill("c22013", { hidden: true }); F({ "tr-PORT": { value: "22013" }, "tr-MODEL_FILE": { value: "m/model.gguf" },'
     ' llamaRemoteEditOverlay: { hidden: true, hasAttribute: () => true, focus() {} }, llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { await rc.CELL_FORM.save({ confirmed: true }); const b = JSON.parse(calls()[0].body); return [calls()[0].path, Object.keys(b).sort(), b.cellId, "PORT" in b.config]; })()',
     json.dumps(["/api/topology/server-cell/save-config", ["cacheModels", "cellId", "config"], "c22013", False]),
     'negative: сохранённая ячейка уходит по id — {cellId, config, cacheModels}, без hostId и port, а в конфиге нет PORT, даже если на странице осталось поле порта'),
    # ── The form's title: which cell it sets up, not which engine ──
    ('title_existing_cell', '', 'rc.cellFormTitle("h1 · gpu0", "Qwen3-8B", true)',
     json.dumps(en("remoteCellTitle", cell="Qwen3-8B", host="h1 · gpu0"), ensure_ascii=False),
     'defect-history: форма настроенной ячейки называет её саму — по модели, как доска, — и машину; было «Add llama server» у любой '
     'ячейки, у настроенной Strata тоже (живая проверка 2026-10-13); порта в заголовке нет'),
    ('title_new_cell', '', 'rc.cellFormTitle("h1", "", false)',
     json.dumps(en("remoteNewCellTitle", host="h1")),
     'новая ячейка («＋ Add model»): «настройки новой ячейки» — без порта, которого у неё нет'),
    ('title_unconfigured_is_a_new_cells', '', '[rc.cellFormTitle("h1", "c22011", false), rc.cellFormTitle("h1", "", true)]',
     json.dumps([en("remoteNewCellTitle", host="h1")] * 2),
     'negative: сохранённая, но не настроенная ячейка (резерв) — заголовок новой, её id не показывается; без имени — тоже, а не пустые кавычки'),
    ('title_names_every_card', '',
     '[rc.cellFormMachine("h1", [{ name: "NVIDIA GeForce RTX 3090" }, { name: "NVIDIA GeForce RTX 5090" }], "NVIDIA GeForce RTX 3090"),'
     ' rc.cellFormMachine("h1", [{ name: "NVIDIA GeForce RTX 5090" }, { name: "NVIDIA GeForce RTX 5090" }], ""),'
     ' rc.cellFormMachine("h1", [{ name: "NVIDIA GeForce RTX 5090" }], ""), rc.cellFormMachine("h1", [], "gpu0"), rc.cellFormMachine("h1", null, "")]',
     '["h1 · RTX 3090 + RTX 5090","h1 · 2 × RTX 5090","h1 · NVIDIA GeForce RTX 5090","h1 · gpu0","h1"]',
     'defect-history (2026-10-17): форма машины с 3090 и 5090 называла её «NVIDIA GeForce RTX 3090» — именем первой карты; теперь называет обе: '
     '«RTX 3090 + RTX 5090», две одинаковые — «2 × …»; negative: машина с одной картой — её имя, как было; карт нет — имя из запроса, а нет и его — одно имя машины'),
    ('title_on_open_names_both_cards',
     'globalThis.__title = () => { st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", servers: [] }] });'
     ' F({ llamaRemoteEditTitle: { textContent: "", parentElement: { querySelector: () => ({}) } } });'
     ' try { rc.openLlamaRemoteEdit("h1", "NVIDIA GeForce RTX 3090", [{ index: 0, name: "NVIDIA GeForce RTX 3090" }, { index: 1, name: "NVIDIA GeForce RTX 5090" }], ""); } catch (e) {}'
     ' const v = globalThis.__fields.llamaRemoteEditTitle.textContent; try { rc.openLlamaRemoteEdit("h1", "gpu0", [], ""); } catch (e) {} return v; };',
     '__title()',
     json.dumps(en("remoteNewCellTitle", host="h1 · RTX 3090 + RTX 5090")),
     'форма открывается с заголовком, который называет обе карты машины, а не карту из первого аргумента'),
    ('title_on_open',
     'globalThis.__title = (slot, id) => { st.setTopology({ ...st.topology, nodes: [{ id: "h1", role: "host", servers: slot ? [slot] : [] }] });'
     ' F({ llamaRemoteEditTitle: { textContent: "", parentElement: { querySelector: () => ({}) } } });'
     ' try { rc.openLlamaRemoteEdit("h1", "gpu0", [], id); } catch (e) {}'
     ' const v = globalThis.__fields.llamaRemoteEditTitle.textContent; try { rc.openLlamaRemoteEdit("h1", "gpu0", [], ""); } catch (e) {} return v; };',
     '[__title({ isSlot: true, clientId: "h1", cellId: "c22009", port: 22009, phase: "running", model: "Qwen3-8B", slotConfig: { RUNNER: "strata", MODEL_FILE: "m.gguf" } }, "c22009"),'
     ' __title({ isSlot: true, clientId: "h1", cellId: "c3f9a02b1", port: null, model: "", slotConfig: { RUNNER: "custom", COMMAND: "run.sh" } }, "c3f9a02b1"),'
     ' __title(null, "")]',
     json.dumps([en("remoteCellTitle", cell="Qwen3-8B", host="h1 · gpu0"), en("remoteCellTitle", cell="c3f9a02b1", host="h1 · gpu0"),
                 en("remoteNewCellTitle", host="h1 · gpu0")], ensure_ascii=False),
     'форма открывается с заголовком своей ячейки: у настроенной — её модель, у ячейки без модели в имени — её id; у новой — «настройки новой '
     'ячейки»; negative: порт работающей ячейки (22009) в заголовок не попадает'),
    # ── the model-cache panel: its words are the page's, the status line is not the note ──
    ('purge_result_is_said_in_the_pages_words_on_the_status_line',
     CACHE_PANEL + OPEN_FORM + ' globalThis.__fetchReply["/api/topology/client-llama/purge-cache"] = { ok: true, result: { removed: 3, freedBytes: 12340000000 } };',
     'await (async () => { await rc.purgeRemoteModelCache(); return { status: __panel.status.textContent, note: __panel.note.textContent, toast: toastText(), '
     'sent: calls().filter((c) => c.path.includes("purge-cache")).map((c) => c.body) }; })()',
     json.dumps({"status": PURGED, "note": "kept", "toast": PURGED, "sent": ['{"hostId":"h1"}']}, ensure_ascii=False),
     'positive: after a purge the status line (not the note) says the result in the page\'s words — no «file(s)» and «GB freed» written in the code'),
    ('purge_status_is_cleared_when_the_form_opens',
     CACHE_PANEL + '__panel.status.textContent = "✓ an earlier purge"; ' + OPEN_FORM,
     '__panel.status.textContent',
     json.dumps(""),
     'positive: the result of an earlier purge belongs to the host it ran on: the form that opens next does not show it'),
    ('cache_total_line_is_said_in_the_pages_words',
     CACHE_PANEL + 'globalThis.__fetchReply["/api/topology/client-llama/list-cache?hostId=h1"] = { models: [{ path: "a/x.gguf", sizeBytes: 1000000000 }, { path: "b/y.gguf", sizeBytes: 2500000000 }] }; ' + OPEN_FORM,
     'await (async () => { const { setTimeout: wait } = await import("node:timers/promises"); await wait(60); return __panel.list.innerHTML.includes(' + json.dumps(en("cacheTotal", n=2, gb="3.50")) + '); })()',
     json.dumps(True),
     'positive: the cache list\'s total line is the page\'s own words with the count and the size filled in'),
    ('purge_result_is_said_in_russian_on_a_russian_page',
     CACHE_PANEL + OPEN_FORM + ' globalThis.__fetchReply["/api/topology/client-llama/purge-cache"] = { ok: true, result: { removed: 3, freedBytes: 12340000000 } };',
     'await (async () => { ' + IN_RUSSIAN.replace("{BODY}", '(await rc.purgeRemoteModelCache(), { status: __panel.status.textContent, toast: toastText() })') + ' })()',
     json.dumps({"status": PURGED_RU, "toast": PURGED_RU}, ensure_ascii=False),
     'positive: on a Russian page the result of a purge is said in Russian — the words of the result are a key of the table, '
     'not English written in the code'),
    ('cache_total_line_is_said_in_russian_on_a_russian_page',
     CACHE_PANEL + 'globalThis.__fetchReply["/api/topology/client-llama/list-cache?hostId=h1"] = { models: [{ path: "a/x.gguf", sizeBytes: 1000000000 }, { path: "b/y.gguf", sizeBytes: 2500000000 }] }; ',
     'await (async () => { ' + IN_RUSSIAN.replace("{BODY}", '(' + OPEN_FORM.replace("try {", "(() => { try {").replace("catch (e) {}", "catch (e) {} })()") + ', await (await import("node:timers/promises")).setTimeout(60), __panel.list.innerHTML.includes(' + json.dumps(ru("cacheTotal", n=2, gb="3.50"), ensure_ascii=False) + '))') + ' })()',
     json.dumps(True),
     'positive: on a Russian page the total under the list of cached files is said in Russian'),
    # The 🌐 of a cell that serves its own page (cell-page.js, 1.3.613) is a link: the browser follows it in this tab.
    # ── The cell form for the cell window (cell-settings.js): one form, heard when filled, saved and closed ──
    ('cellform_holds_the_cell_it_was_filled_for',
     KEPT_CELLS,
     '(() => { const f = rc.CELL_FORM; const filled = f.fill("c22013", { hidden: true }); const a = [filled, f.holds("c22013"), f.holds("c3f9a02b1"), f.holds("h1"), f.holds(""), f.key()];'
     ' f.fill(rc.CellForm.newKey("h1"), { hidden: true }); const b = [f.holds(rc.CellForm.newKey("h1")), f.holds("c22013"), f.cellId()];'
     ' const stray = f.fill("c-gone", { hidden: true }); return [...a, ...b, stray, f.key()]; })()',
     json.dumps([True, True, False, False, False, "c22013", True, False, "", False, "new:h1"]),
     "the form holds the cell it was filled for, by its id; a cell not made yet is held under its machine's new key; negative: "
     "another cell, the machine's id and an empty key are not held, and a key of no cell the board shows fills nothing — the form keeps what it held"),
    ('cellform_filled_heard_without_the_dialog',
     KEPT_CELLS,
     '(() => { const heard = []; rc.CELL_FORM.on("filled", (...a) => heard.push(a.length)); rc.CELL_FORM.fill("c22013", { hidden: true });'
     ' const shut = globalThis.__fields.llamaRemoteEditOverlay.hidden; rc.CELL_FORM.fill("c22013");'
     ' return [heard, shut, globalThis.__fields.llamaRemoteEditOverlay.hidden]; })()',
     json.dumps([[0, 0], True, False]),
     "a filling is heard, with nothing carried; the window's own filling shows no dialog; negative: the dialog's own does"),
    ('cellform_saved_heard_with_the_config_sent',
     KEPT_CELLS + ' rc.CELL_FORM.fill("c22013", { hidden: true }); F({ "tr-MODEL_FILE": { value: "m/model.gguf" },'
     ' llamaRemoteEditOverlay: { hidden: true, hasAttribute: () => true, focus() {} }, llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { const heard = []; rc.CELL_FORM.on("saved", (cfg) => heard.push(["PORT" in cfg, cfg.MODEL_FILE]));'
     ' const ok = await rc.CELL_FORM.save(); return [ok, heard, calls().map((c) => c.path)]; })()',
     json.dumps([True, [[False, "m/model.gguf"]], ["/api/topology/server-cell/save-config"]]),
     "the window's Apply is the dialog's: it saves, answers true, and the save is heard with the config sent — which carries no PORT"),
    ('cellform_save_refused_or_declined_is_false',
     KEPT_CELLS + ' rc.CELL_FORM.fill("c22013", { hidden: true }); F({ "tr-MODEL_FILE": { value: "m/model.gguf" },'
     ' llamaRemoteEditOverlay: { hidden: true, hasAttribute: () => true, focus() {} }, llamaRemoteEditStart: { textContent: "Apply", disabled: false, classList: { add() {}, remove() {} } } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { const heard = []; rc.CELL_FORM.on("saved", () => heard.push(1));'
     ' globalThis.__stubReturns["dialogs.appConfirm"] = async () => false; const declined = await rc.CELL_FORM.save();'
     ' globalThis.__stubReturns["dialogs.appConfirm"] = async () => true; globalThis.__fetchReply["/api/topology/server-cell/save-config"] = { __status: 500, error: "disk full" };'
     ' const failed = await rc.CELL_FORM.save(); return [declined, failed, heard.length, calls().length]; })()',
     json.dumps([False, False, 0, 1]),
     "negative: a declined question and a failed save answer false and are not heard as saved — the window keeps its edits"),
    ('open_dialog_shows_the_edits_the_window_keeps',
     KEPT_CELLS + ' rc.CELL_FORM.fill("c22013", { hidden: true });',
     'await (async () => { const heard = []; rc.CELL_FORM.on("filled", () => heard.push("filled")); const asked = [];'
     ' rc.CELL_FORM.keepBy({ keeps: (k) => k === "c22013", leave: async () => { asked.push(1); return true; } });'
     ' await rc.openCellForm("c22013"); return [heard, asked.length, globalThis.__fields.llamaRemoteEditOverlay.hidden]; })()',
     json.dumps([[], 0, False]),
     "the dialog of the cell whose edits the window keeps comes up with the form as it stands — not filled again, nothing asked"),
    ('open_dialog_for_another_cell_asks_first',
     KEPT_CELLS + ' rc.CELL_FORM.fill("c22013", { hidden: true });',
     'await (async () => { const heard = []; rc.CELL_FORM.on("filled", () => heard.push("filled")); let answer = false; const asked = [];'
     ' rc.CELL_FORM.keepBy({ keeps: () => false, leave: async (k) => { asked.push(k); return answer; } });'
     ' await rc.openCellForm("c3f9a02b1"); const first = [heard.length, globalThis.__fields.llamaRemoteEditOverlay.hidden, rc.CELL_FORM.holds("c22013")];'
     ' answer = true; await rc.openCellForm("c3f9a02b1");'
     ' return [first, heard.length, globalThis.__fields.llamaRemoteEditOverlay.hidden, rc.CELL_FORM.holds("c3f9a02b1"), asked]; })()',
     json.dumps([[0, True, True], 1, False, True, ["c3f9a02b1", "c3f9a02b1"]]),
     "negative: edits the window keeps are not dropped by a dialog for another cell without the operator's word — declined, the "
     "form keeps its cell and no dialog comes up; agreed, the form is filled for the other and its dialog shown; the keeper is asked by the cell's id"),
    ('open_dialog_kept_for_a_cell_the_form_no_longer_holds_fills',
     KEPT_CELLS + ' rc.CELL_FORM.fill("c22013", { hidden: true });',
     'await (async () => { const heard = []; rc.CELL_FORM.on("filled", () => heard.push("filled"));'
     ' rc.CELL_FORM.keepBy({ keeps: () => true, leave: async () => true }); await rc.openCellForm("c0a1b2c3d");'
     ' return [heard, rc.CELL_FORM.holds("c0a1b2c3d")]; })()',
     json.dumps([["filled"], True]),
     "negative: a keeper's word alone does not show the form as it stands — the form holds another cell, so it is filled for this one"),
    ('open_dialog_to_add_a_model_never_shows_the_kept_form',
     KEPT_CELLS + ' rc.CELL_FORM.fill("c22013", { hidden: true });',
     'await (async () => { const asked = []; rc.CELL_FORM.keepBy({ keeps: () => true, leave: async () => { asked.push(1); return true; } });'
     ' await rc.openCellForm("c22013", { pickModel: true }); return asked.length; })()',
     '1',
     "negative: «+ Add model» is a new choice of a model — the form is filled afresh (asked first), never shown as it stood"),
    ('cellform_set_writes_as_typing_would',
     'const ev = []; const rec = (o) => ({ ...o, dispatchEvent: (e) => { ev.push([e.type, e.bubbles]); return true; } });'
     ' F({ "tr-CTX_SIZE": rec({ value: "4096" }), "tr-MMAP": rec({ type: "checkbox", checked: false }) }); globalThis.__ev = ev;',
     '[rc.CELL_FORM.set("CTX_SIZE", 8192), globalThis.__fields["tr-CTX_SIZE"].value, rc.CELL_FORM.set("MMAP", "1"), globalThis.__fields["tr-MMAP"].checked,'
     ' rc.CELL_FORM.set("MMAP", "0"), globalThis.__fields["tr-MMAP"].checked, rc.CELL_FORM.set("NOPE", "1"), globalThis.__ev]',
     json.dumps([True, "8192", True, True, True, False, False, [["input", True], ["change", True], ["input", True], ["change", True], ["input", True], ["change", True]]]),
     "a write is the form's own: the value (a box by \"1\"/\"0\"), then input and change that bubble — the form's listeners redraw "
     "what reads it and mark an optional toggle as stated; negative: a field the form has not is not written"),
    ('cellform_checked_locked_settle',
     'F({ "tr-MMAP": { type: "checkbox", checked: true }, "tr-HEALTH_PATH": { value: "", disabled: true }, "tr-CTX_SIZE": { value: "1" },'
     ' "tr-EXTRA_ARGS": { value: "--ctx-size 8192" } }); globalThis.__fetchCalls.length = 0;',
     'await (async () => { const f = rc.CELL_FORM; const a = [f.checked("MMAP"), f.checked("NOPE"), f.locked("HEALTH_PATH"), f.locked("CTX_SIZE"), f.locked("PORT"), f.locked("NOPE")];'
     ' await f.settle("CTX_SIZE"); const before = calls().length; await f.settle("EXTRA_ARGS"); return [...a, before, calls().map((c) => c.path)]; })()',
     json.dumps([True, False, True, False, False, False, 0, ["/api/parse-extra-args"]]),
     "the box as the form draws it, a field switched off is locked; leaving EXTRA_ARGS asks the controller which flags have fields of their own, "
     "as leaving it in the dialog does; negative: leaving another field asks nothing, and the form has no port to lock — a cell's port is its scout's"),
    ('cellform_place_map_none_for_another_runner',
     'F({ "tr-RUNNER": { value: "vllm" } });',
     '(() => { const box = { innerHTML: "old map" }; return [rc.CELL_FORM.placeMap(box), box.innerHTML, rc.CELL_FORM.placeMap(null)]; })()',
     json.dumps([False, "", False]),
     "negative: a cell of another runner has no map — false, and the box is emptied (memory.js mountPlacementMap, the dialog's own rule); no box — false"),
    ('cellform_hidden_heard_once_however_closed',
     'F({ llamaRemoteEditOverlay: { hidden: false } }); globalThis.__mo = [];'
     ' globalThis.MutationObserver = class { constructor(cb) { this.cb = cb; globalThis.__mo.push(this); } observe(el, opts) { this.el = el; this.opts = opts; } };',
     '(() => { const heard = []; rc.CELL_FORM.on("hidden", () => heard.push(1)); rc.CELL_FORM.on("hidden", () => heard.push(2));'
     ' const mo = globalThis.__mo; mo[0].cb(); globalThis.__fields.llamaRemoteEditOverlay.hidden = true; mo[0].cb();'
     ' return [mo.length, mo[0].el === globalThis.__fields.llamaRemoteEditOverlay, mo[0].opts, heard]; })()',
     json.dumps([1, True, {"attributes": True, "attributeFilter": ["hidden"]}, [1, 2]]),
     "the dialog closed by any hand is heard once, by its hidden attribute, by every hearer; negative: watched once however many hear, "
     "and a change that leaves it shown is not heard as closed"),
    ('page_link_click_stays_with_the_link',
     '',
     r'''await (async () => {
       const handlers = [];
       const a = { dataset: { cellPage: "c22021" }, addEventListener: (ev, fn) => handlers.push([ev, fn]) };
       const root = { querySelectorAll: (q) => (q === "[data-cell-page]" ? [a] : []) };
       document.body ||= {}; document.body.dataset ||= { vramHoverBound: "1" };
       rc.bindServerSlotControls(root);
       const ev = { stopped: 0, prevented: 0, stopPropagation() { this.stopped += 1; }, preventDefault() { this.prevented += 1; } };
       handlers.forEach(([name, fn]) => { if (name === "click") fn(ev); });
       return { bound: handlers.map(([name]) => name), stopped: ev.stopped, prevented: ev.prevented, calls: calls().length }; })()''',
     json.dumps({"bound": ["click"], "stopped": 1, "prevented": 0, "calls": 0}),
     "the card's 🌐 is the browser's to follow: the card under it hears nothing of the click; negative: the link is not "
     "held back (no preventDefault) and nothing is asked of the controller"),
    ('cell_button_selector_quotes_the_id',
     'globalThis.__css = globalThis.CSS; delete globalThis.CSS;',
     '(() => { try { return [rc.CellButton.selector("data-node-cell-stop", "c22001"), rc.CellButton.selector("data-node-cell-launch", \'c"x\')]; } finally { if (globalThis.__css) globalThis.CSS = globalThis.__css; } })()',
     json.dumps(['[data-node-cell-stop][data-cell-id="c22001"]', '[data-node-cell-launch][data-cell-id="c\\"x"]']),
     'кнопку ячейки находят по её data-cell-id (мгновенная метка «идёт» на нажатой кнопке); boundary: кавычка в id экранируется и без CSS.escape'),
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
            probe_args(node, harness, probe_path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
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
    # The port picker, its swap, the exclusions and the scan left with their controller routes (404): the module draws none of
    # their markup and sends none of their requests, and no cell's button is read by a port any more.
    print("ушло с доски:")
    js = (ROOT / "static" / "js" / "remote-cells.js").read_text(encoding="utf-8")
    for gone in ("port-picker", "port-tile", "port-scan", "data-pick-port", "data-swap-port", "data-release-port",
                 "/api/port-exclusions", "reassign-port", "swap-port", "data-cell-port-reassign", "nodeCellPort",
                 "data-node-cell-port", "nodeStartPort", "cellPort"):
        check(gone not in js, f"negative: в remote-cells.js нет «{gone}»")
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
