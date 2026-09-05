#!/usr/bin/env python3
"""Снимок static/js/history.js — модал истории запросов.

Что пинится значением: фильтры (подстрока клиента по маршруту и адресу; via
llama/cloud и «спасённые» — не тип апстрима, а свойство пути: хотя бы один
провалившийся выход; статус ok/error), строки таблицы (длительность ms/s/m,
токены p+c с подсказкой, TPS только при completion>0 и длительности >100 мс,
класс статуса, класс строки с ошибкой, модель обрезается на 24 символах, бэйдж
спасения с трейлом выходов), пустые состояния, загрузка (запрос с limit и
event=finished, дата в запросе, ошибка — в обёртку), кэш событий по дате,
список событий, полная карточка деталей с Raw JSON всегда раскрытым, модал
создаётся один раз и переиспользуется.

DOM — словарь `globalThis.__fields`; `document.createElement` здесь создаёт
элементы, которые регистрируются в словаре по id (модуль строит модал сам и
потом находит его через $(id)); слушатели записываются и вызываются из пинов.
`Date.now` заморожен — «N s ago» детерминирован; локальное время не пинится.

Запуск: python3 scripts/test_js_history.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("polling,canvas,topology-dnd,topology-render,dialogs,charts,cables,cloud,favorites,config-locator,"
         "system-panels,onboarding,onboarding-tours,usage-stats,dialog-llamas,models-page,system-page,memory,"
         "command-preview,llama-edit,remote-cells,topology-nodes,routers,topology-activity,topology-proxies")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
Date.now = () => 1_700_000_100_000;
globalThis.__created = [];
// Элемент словарного DOM: атрибуты, слушатели, innerHTML; присвоение id регистрирует его в __fields.
const mkEl = (tag) => { const e = { tag, attrs: {}, listeners: {}, innerHTML: "", value: "", className: "", children: [], _id: "",
  setAttribute(k, v) { this.attrs[k] = v; }, removeAttribute(k) { delete this.attrs[k]; }, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); },
  appendChild(c) { this.children.push(c); }, remove() {}, select() {}, querySelector(sel) { return mkEl("q:" + sel); }, dataset: {} };
  Object.defineProperty(e, "id", { get() { return this._id; }, set(v) { this._id = v; globalThis.__fields[v] = e; } }); globalThis.__created.push(e); return e; };
document.createElement = mkEl; document.body = { appendChild() {} }; globalThis.location.origin = "http://ctl:7990";
const m = await import(pathToFileURL(process.env.JS_ROOT + "/history.js").href);
const wrap = () => globalThis.__fields.historyTableWrap;
const F = () => globalThis.__fields;
const fire = (id, type) => (F()[id].listeners[type] || []).forEach((fn) => fn({ target: F()[id] }));
const calls = () => globalThis.__fetchCalls.map((c) => c.path);
const ROW = (over = {}, item = {}) => ({ time: 1_700_000_070, event: "finished", item: { route: "hermes", client: "10.0.0.7", startedAt: 1_700_000_070, status: 200, durationMs: 2500, upstreamType: "llama", request: { model: "gpt-5.6-terra-extended-long-name" }, stream: { usage: { prompt_tokens: 100, completion_tokens: 50 } }, ...item }, ...over });
const ROWS = () => [ROW({}, { rescued: { hops: 0, trail: [] } }), ROW({}, { route: "scout", client: "10.0.0.8", status: 502, error: "boom", upstreamType: "cloud", durationMs: 90, stream: null }), ROW({}, { route: "saved", upstreamType: "cloud", rescued: { hops: 1, trail: [{ from: "srv:22001", status: 400 }] }, durationMs: 65000 })];
const reqUrl = () => "/api/agent-proxy-logs?limit=500&event=finished" + (m.historyCurrentDate ? "&date=" + m.historyCurrentDate : "");
const evUrl = () => "/api/agent-proxy-logs?limit=500" + (m.historyCurrentDate ? "&date=" + m.historyCurrentDate : "");
const load = async (rows, extra = {}) => { globalThis.__fetchReply[reqUrl()] = { rows, dates: [m.historyCurrentDate || "2026-09-05"], date: m.historyCurrentDate || "2026-09-05", ...extra }; await m.loadRequestHistory(); };
const setFilter = (id, value) => { F()[id].value = value; fire(id, id === "historyClientInput" ? "input" : "change"); };
// Экспортные let модуля снаружи не присваиваются (живые привязки ESM только на чтение):
// фильтры меняются ТОЛЬКО слушателями модала — как в браузере. reset() строит модал,
// биндит слушатели на элементы словаря и сбрасывает фильтры через них; попутный
// fetch открытия вычёркивается из журнала вызовов.
const reset = () => { st.setState({ config: {} });
  globalThis.__fields = { historyTableWrap: mkEl("div"), historyCloseBtn: mkEl("button"), historyDateSelect: mkEl("select"), historyClientInput: mkEl("input"), historyViaSelect: mkEl("select"), historyStatusSelect: mkEl("select") };
  globalThis.__fetchReply = {}; m.openRequestHistory(); ["historyClientInput", "historyViaSelect", "historyStatusSelect"].forEach((id) => setFilter(id, ""));
  globalThis.__created.length = 0; globalThis.__fetchCalls.length = 0; };
reset();
const out = {};
"""

PINS = [
    ("load_requests_query_and_rows", '', 'await (async () => { await load(ROWS()); return [calls(), m.historyRows.length, m.historyCurrentDate, (wrap().innerHTML.match(/history-data-row/g) || []).length]; })()',
     '[["/api/agent-proxy-logs?limit=500&event=finished"],3,"2026-09-05",3]', "загрузка: limit 500 и только finished; строки и дата из ответа; три строки в таблице"),
    ("load_requests_with_date_and_error", 'globalThis.__fetchReply["/api/agent-proxy-logs?limit=500&event=finished&date=2026-09-01"] = { __status: 500, error: "disk" };',
     'await (async () => { setFilter("historyDateSelect", "2026-09-01"); await new Promise((r) => setImmediate(r)); const a = [calls()[0], wrap().innerHTML.includes("history-error"), wrap().innerHTML.includes("disk")]; globalThis.__fetchReply[reqUrl()] = { rows: [], dates: [], date: "" }; setFilter("historyDateSelect", ""); await new Promise((r) => setImmediate(r)); return [...a, m.historyCurrentDate]; })()',
     '["/api/agent-proxy-logs?limit=500&event=finished&date=2026-09-01",true,true,""]', "дата попадает в запрос; отказ сервера — текст ошибки в обёртке"),
    ("sync_date_select", '', '(() => { const cur = m.historyCurrentDate || "2026-09-05"; m._syncHistoryDateSelect({ dates: [cur, "2026-09-04"], date: cur }); const a = [F().historyDateSelect.innerHTML.includes(`<option value="${cur}" selected>${cur}</option><option value="2026-09-04">2026-09-04</option>`), m.historyCurrentDate === cur]; const before = F().historyDateSelect.innerHTML; m._syncHistoryDateSelect({ dates: [] }); return [...a, F().historyDateSelect.innerHTML === before]; })()',
     '[true,true,true]', "выбор даты: опции с текущей отмеченной; пустой список дат ничего не трогает"),
    ("row_cells", '', 'await (async () => { await load([ROW()]); const h = wrap().innerHTML; return [h.includes("30s ago"), h.includes("<b>hermes</b><span class=\\"history-sub\\">10.0.0.7</span>"), h.includes(">gpt-5.6-terra-extended…<"), h.includes("history-tag-llama"), h.includes(">2.5s<"), h.includes(\'title="100p + 50c">150<\'), h.includes(">20.0<"), h.includes(\'history-status-ok">200<\'), h.includes("history-row-error")]; })()',
     '[true,true,true,true,true,true,true,true,false]', "строка: «N s ago», маршрут и адрес, модель обрезана на 24, тег llama, длительность, токены p+c, TPS, статус ok, без класса ошибки"),
    ("row_error_and_rescued", '', 'await (async () => { await load(ROWS()); const h = wrap().innerHTML; return [(h.match(/history-row-error/g) || []).length, h.includes(\'history-status-err">502<\'), h.includes(">90ms<"), (h.match(/history-tag-cloud/g) || []).length, h.includes("Failed exits before this answer: srv:22001 (400)"), h.includes(">1.1m<"), (h.match(/>—</g) || []).length >= 2, (h.match(/history-tag-rescued/g) || []).length]; })()',
     '[1,true,true,2,true,true,true,1]', "ошибка — класс строки и статус err; облако — тег; спасённый — бэйдж с трейлом; минуты; прочерки без токенов/TPS"),
    ("tps_needs_completion_and_duration", '', 'await (async () => { await load([ROW({}, { durationMs: 100 }), ROW({}, { stream: { usage: { prompt_tokens: 5, completion_tokens: 0 } } })]); const h = wrap().innerHTML; return (h.match(/history-td-tps">—</g) || []).length; })()',
     '2', "boundary: длительность ≤100 мс или ноль completion — TPS не считается"),
    ("filter_client_substring", '', 'await (async () => { await load(ROWS()); setFilter("historyClientInput", "10.0.0.8"); const a = (wrap().innerHTML.match(/history-data-row/g) || []).length; setFilter("historyClientInput", "HERM"); const b = (wrap().innerHTML.match(/history-data-row/g) || []).length; setFilter("historyClientInput", "zzz"); const c = (wrap().innerHTML.match(/history-data-row/g) || []).length; return [a, b, c, m.historyClientFilter]; })()',
     '[1,1,0,"zzz"]', "фильтр клиента: по адресу и по маршруту, ввод приводится к нижнему регистру; чужое — ноль строк"),
    ("filter_via_and_rescued", '', 'await (async () => { await load(ROWS()); const n = () => (wrap().innerHTML.match(/history-data-row/g) || []).length; setFilter("historyViaSelect", "cloud"); const c = n(); setFilter("historyViaSelect", "rescued"); const r = n(); setFilter("historyViaSelect", "llama"); const l = n(); return [c, r, l]; })()',
     '[2,1,1]', "via: облако — двое; спасённые — только с провалившимся выходом; llama — один"),
    ("filter_status", '', 'await (async () => { await load(ROWS()); const n = () => (wrap().innerHTML.match(/history-data-row/g) || []).length; setFilter("historyStatusSelect", "ok"); const ok = n(); setFilter("historyStatusSelect", "error"); const er = n(); return [ok, er]; })()',
     '[2,1]', "статус: ok — 2xx, error — 4xx/5xx"),
    ("empty_states", '', 'await (async () => { await load([]); const a = wrap().innerHTML.includes("No requests found"); await load(ROWS()); setFilter("historyClientInput", "zzz"); const b = wrap().innerHTML.includes("No matching requests"); return [a, b, m._historyFilteredRows.length]; })()',
     '[true,true,0]', "пусто: «No requests found»; отфильтровано в ноль — «No matching requests», список для кликов пуст"),
    ("render_without_wrap", 'delete globalThis.__fields.historyTableWrap;', 'await (async () => { await m.loadRequestHistory(); m.renderHistoryTable(); m.renderHistoryEvents(); return calls().length; })()', '0', "negative: без обёртки — ни запроса, ни исключения"),
    ("events_load_and_cache", 'globalThis.__fetchReply[evUrl()] = { rows: [ROW(), ROW({}, { status: 500 })], dates: [m.historyCurrentDate || "2026-09-05"], date: m.historyCurrentDate || "2026-09-05" };',
     'await (async () => { await m.loadHistoryEvents(); const a = [calls().length, (wrap().innerHTML.match(/history-event-row/g) || []).length, (wrap().innerHTML.match(/history-event-row failed/g) || []).length]; await m.loadHistoryEvents(); return [...a, calls().length, m.historyEventDateLoaded === m.historyCurrentDate]; })()',
     '[1,2,1,1,true]', "события: запрос без event; строка с ошибкой помечена; повторная загрузка той же даты — из кэша"),
    ("events_empty", '', '(() => { m.historyEventRows.length = 0; m.renderHistoryEvents(); return wrap().innerHTML; })()', '"<div class=\\"history-loading\\">No events found</div>"', "negative: без событий — подсказка"),
    ("detail_full_sections", '', '(h => [h.includes("Upstream error body"), h.includes("&quot;code&quot;: 400"), h.includes("model: gpt"), h.includes("<td>2500 ms</td>"), h.includes("waited: 800 m"), h.includes("<details"), h.includes("Raw JSON")])(m.renderHistoryDetailFull({ upstreamErrorBody: "{\\"code\\":400}", cloudMeta: { model: "gpt" }, item: { durationMs: 2500, queue: { queuedMs: 800 } } }))',
     '[true,true,true,true,true,false,true]', "детали: секции как в логе, но Raw JSON всегда раскрыт (без details)"),
    ("detail_error_without_body", '', '(h => [h.includes("log-detail-value\\">boom"), h.includes("Upstream error body")])(m.renderHistoryDetailFull({ item: { error: "boom" } }))', '[true,false]', "ошибка без тела апстрима — отдельной строкой"),
    ("popup_created_and_bound", '', '(() => { m.openHistoryDetailPopup(ROW()); const p = F().historyDetailPanel; return [!!p, p.innerHTML.includes("history-detail-popup-title"), p.innerHTML.includes("hermes · :"), "hidden" in p.attrs, p.className]; })()',
     '[true,true,false,false,"history-detail-overlay"]', "попап деталей создан, заголовок — сводка строки, показан"),
    ("popup_close_and_reuse", '', '(() => { m.openHistoryDetailPopup(ROW()); const n = globalThis.__created.length; m.closeHistoryDetailPopup(); const hidden = "hidden" in F().historyDetailPanel.attrs; m.openHistoryDetailPopup(ROW()); return [hidden, globalThis.__created.length > n, "hidden" in F().historyDetailPanel.attrs]; })()',
     '[true,true,false]', "закрытие прячет; повторное открытие переиспользует панель (создаются только внутренние элементы) и снова показывает"),
    ("open_history_builds_once", '',
     'await (async () => { const ov = F().requestHistoryOverlay; const created = globalThis.__created.length; m.closeRequestHistory(); const hidden = "hidden" in ov.attrs; m.openRequestHistory(); await new Promise((r) => setImmediate(r)); return [!!ov, ov.className, hidden, "hidden" in ov.attrs, globalThis.__created.length === created, calls().length, calls()[0] === reqUrl()]; })()',
     '[true,"topology-policy-overlay history-overlay",true,false,true,1,true]', "модал строится один раз: повторное открытие переиспользует оверлей (ничего не создаётся), снимает hidden и перезагружает историю"),
    ("close_history_hides", '', '(() => { m.closeRequestHistory(); return F().requestHistoryOverlay.attrs.hidden; })()', '""', "закрытие ставит hidden"),
    ("filters_combine", '',
     'await (async () => { await load(ROWS()); const n = () => (wrap().innerHTML.match(/history-data-row/g) || []).length; setFilter("historyClientInput", "SCOUT"); const a = n(); setFilter("historyViaSelect", "llama"); const b = n(); setFilter("historyClientInput", ""); setFilter("historyStatusSelect", "error"); const c = n(); setFilter("historyViaSelect", "cloud"); const d = n(); return [a, b, c, d]; })()',
     '[1,0,0,1]', "фильтры складываются: scout — облако, поэтому с via=llama — ноль; error+llama — ноль, error+cloud — один"),
    ("date_listener_reloads", 'globalThis.__fetchReply["/api/agent-proxy-logs?limit=500&event=finished&date=2026-09-04"] = { rows: [ROW()], dates: ["2026-09-05", "2026-09-04"], date: "2026-09-05" };',
     'await (async () => { setFilter("historyDateSelect", "2026-09-04"); await new Promise((r) => setImmediate(r)); const a = [calls()[0], m.historyCurrentDate, m.historyRows.length]; globalThis.__fetchReply[reqUrl()] = { rows: [], dates: [], date: "" }; setFilter("historyDateSelect", ""); await new Promise((r) => setImmediate(r)); return [...a, m.historyCurrentDate]; })()',
     '["/api/agent-proxy-logs?limit=500&event=finished&date=2026-09-04","2026-09-04",1,""]', "смена даты перезагружает историю за выбранный день; пустая дата — без параметра"),
    ("close_listener", '', '(() => { fire("historyCloseBtn", "click"); return F().requestHistoryOverlay.attrs.hidden; })()', '""', "кнопка × прячет модал"),
    ("overlay_click_outside_closes", '', '(() => { const ov = F().requestHistoryOverlay; (ov.listeners.click || []).forEach((fn) => fn({ target: F().historyCloseBtn })); const a = "hidden" in ov.attrs; (ov.listeners.click || []).forEach((fn) => fn({ target: ov })); return [a, "hidden" in ov.attrs]; })()', '[false,true]', "клик по содержимому не закрывает, клик по подложке закрывает"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 22:
        print(f"js history FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js history: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_history.tmp.mjs"
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
        print(f"js history FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("история запросов: фильтры, строки таблицы, детали:")
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
    print(f"js history OK: настоящий модуль в node, {len(PINS)} пинов истории значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
