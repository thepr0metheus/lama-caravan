#!/usr/bin/env python3
"""Снимок static/js/config-locator.js — найти настройку среди одиннадцати вкладок.

Контракт: индекс поиска — это поля СЕРВЕРА (state.fields), сужённые до тех, у
которых в этом редакторе есть живой инпут (id = pfx + FIELD); вкладка поля
берётся из тех же таблиц, что рисуют вкладки (`fieldLocations`, первое
попадание побеждает). Ранжирование: точное имя > начало имени > точный флаг >
флаг содержит > имя содержит > подсказка содержит; не больше 12 хитов; при
пустом результате — подсказка; верхний хит сразу подсвечивает свою вкладку.
Навигация: стрелки двигают курсор и подсветку, Enter выбирает (переключение
вкладки + подсветка поля + фокус в инпут), Escape закрывает и гасит подсветку.
Наведение на токен превью команды подсвечивает вкладку, не переключая её;
клик — переключает и показывает поле; локатор биндится один раз.

DOM — дерево элементов mkEl с querySelector/querySelectorAll по селекторам,
которые модуль использует; document.querySelectorAll обходит корни в
`globalThis.__roots`. setTimeout — рекордер (вспышка поля через 1.6 с не
ждётся). constants.js — настоящий (таблицы вкладок).

Запуск: python3 scripts/test_js_config_locator.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("polling,canvas,topology-dnd,topology-render,dialogs,charts,cables,cloud,history,favorites,"
         "system-panels,onboarding,onboarding-tours,usage-stats,dialog-llamas,models-page,system-page,memory,"
         "command-preview,llama-edit,remote-cells,topology-nodes,topology-modals,routers,topology-activity,topology-proxies,model-meta,form")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const C = await import(pathToFileURL(process.env.JS_ROOT + "/constants.js").href);
st.setState({ config: {}, fields: [], fieldFlags: {} });
globalThis.__timers = []; globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push(Number(ms) || 0); return 0; };
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), contains: (c) => s.has(c), has: (c) => s.has(c), list: () => [...s].sort() } };
// Элемент словарного DOM: дерево, classList, dataset, события; селекторы — ровно те, что нужны модулю.
const matchSel = (e, sel) => {
  const m = sel.match(/^\[data-adv-tab="(.+)"\]$/); if (m) return e.dataset.advTab === m[1];
  switch (sel) {
    case ".advanced-tab-bar": case ".advanced-tab-body": case ".advanced-tab-btn": case ".advanced-tab-panel": case ".config-search-hit": case ".field": return e.classList.has(sel.slice(1));
    case ".config-search-hit.active": return e.classList.has("config-search-hit") && e.classList.has("active");
    case "input, select, textarea": return ["input", "select", "textarea"].includes(e.tag);
    case "[data-hit]": return "hit" in e.dataset; case "[data-cmd-field]": return "cmdField" in e.dataset;
    case ".tab-located, .field-located": return e.classList.has("tab-located") || e.classList.has("field-located");
  } throw new Error("selector not modelled: " + sel); };
const mkEl = (tag, props = {}) => { const e = { tag, children: [], classList: cls(), dataset: {}, listeners: {}, events: [], value: "", hidden: false, parent: null, focused: 0, scrolled: 0,
  appendChild(c) { c.parent = this; this.children.push(c); return c; }, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, dispatchEvent(ev) { this.events.push(ev.type); return true; },
  setAttribute(k, v) { this.dataset["attr:" + k] = v; }, scrollIntoView() { this.scrolled += 1; }, focus() { this.focused += 1; }, blur() {}, get offsetWidth() { return 1; },
  closest(sel) { let n = this; while (n) { if (matchSel(n, sel)) return n; n = n.parent; } return null; }, contains(x) { let n = x; while (n) { if (n === this) return true; n = n.parent; } return false; },
  all() { return this.children.flatMap((c) => [c, ...c.all()]); }, querySelector(sel) { return this.all().find((c) => matchSel(c, sel)) || null; }, querySelectorAll(sel) { return this.all().filter((c) => matchSel(c, sel)); }, ...props };
  Object.defineProperty(e, "className", { get() { return this.classList.list().join(" "); }, set(v) { String(v).split(/\s+/).filter(Boolean).forEach((c) => this.classList.add(c)); } });
  // innerHTML — строка; результаты поиска разбираются в кнопки-хиты с data-hit и классом active.
  Object.defineProperty(e, "innerHTML", { get() { return this._html || ""; }, set(v) { this._html = v; this.children = []; for (const h of v.matchAll(/class="config-search-hit( active)?"\s+data-t="cell-config-search-hit" data-t-id="([^"]+)" data-hit="(\d+)"/g)) { const b = mkEl("button", { dataset: { hit: h[3], field: h[2] } }); b.classList.add("config-search-hit"); if (h[1]) b.classList.add("active"); this.appendChild(b); } } });
  if (props.className) { e.className = props.className; }
  return e; };
document.createElement = (tag) => mkEl(tag);
globalThis.__roots = [];
document.querySelectorAll = (sel) => globalThis.__roots.flatMap((r) => [r, ...r.all()]).filter((e) => matchSel(e, sel));
const docListeners = {}; document.addEventListener = (t, fn) => { (docListeners[t] ||= []).push(fn); };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/config-locator.js").href);
const LOC = m.fieldLocations();
// Редактор: панель вкладок с кнопками и панелями по индексам таблицы, три поля с инпутами (третьего — CTX_SIZE — нет: он «только на сервере»).
const FIELDS = ["N_GPU_LAYERS", "THREADS", "N_PREDICT", "CTX_SIZE"];
let E;
const build = () => {
  const host = mkEl("div"); const bar = host.appendChild(mkEl("div", { className: "advanced-tab-bar" })); const body = host.appendChild(mkEl("div", { className: "advanced-tab-body" }));
  C.advancedTabDefs.forEach((tab, i) => { const b = bar.appendChild(mkEl("button", { className: "advanced-tab-btn", dataset: { advTab: String(i) } })); const p = body.appendChild(mkEl("div", { className: "advanced-tab-panel", dataset: { advPanel: String(i) } })); if (i === 0) { b.classList.add("active"); p.classList.add("active"); } });
  const fieldsIn = {}; for (const f of ["N_GPU_LAYERS", "THREADS", "N_PREDICT"]) { const loc = LOC.get(f); const panel = body.children[loc ? loc.tabIndex : 0]; const fe = panel.appendChild(mkEl("div", { className: "field" })); const inp = fe.appendChild(mkEl("input")); fieldsIn[f] = inp; }
  const preview = mkEl("pre"); const tok = preview.appendChild(mkEl("span", { dataset: { cmdField: "THREADS" } })); const plain = preview.appendChild(mkEl("span"));
  globalThis.__fields = { dynamicFields: host, previewCmdline: preview, ...fieldsIn };
  globalThis.__roots = [host, preview];
  return { host, bar, body, fieldsIn, preview, tok, plain };
};
const reset = () => { st.setState({ config: {}, fields: FIELDS, fieldFlags: { N_GPU_LAYERS: ["--n-gpu-layers", "-ngl"], THREADS: ["--threads", "-t"], N_PREDICT: ["--n-predict", "-n"], CTX_SIZE: ["--ctx-size", "-c"] } }); E = build(); globalThis.__timers.length = 0; };
reset();
const tabOf = (f) => LOC.get(f)?.tabIndex;
const search = (q) => { const w = m.renderConfigSearch(""); const input = w.children[0], results = w.children[1]; input.value = q; input.listeners.input[0](); return { w, input, results, hits: results.children.map((b) => b.dataset.field) }; };
const litTab = () => E.bar.children.findIndex((b) => b.classList.has("tab-located"));
const activeTab = () => E.bar.children.findIndex((b) => b.classList.has("active"));
const out = {};
"""

PINS = [
    ("locations_cover_every_grouped_field_first_wins", '', '(() => { const all = new Set(); const dup = new Set(); C.advancedTabDefs.forEach((tab) => tab.groups.forEach((g) => (C.advancedGroups.find((x) => x.titleKey === g)?.fields || []).forEach((f) => { if (all.has(f)) dup.add(f); all.add(f); }))); const first = [...dup].every((f) => { const firstTab = C.advancedTabDefs.findIndex((tab) => tab.groups.some((g) => (C.advancedGroups.find((x) => x.titleKey === g)?.fields || []).includes(f))); return LOC.get(f).tabIndex === firstTab; }); return [LOC.size === all.size, LOC.size > 50, dup.size, first, typeof LOC.get("N_GPU_LAYERS")?.tabKey, LOC.get("NOPE")]; })()',
     '[true,true,0,true,"string",null]', "карта полей строится из таблиц вкладок: каждое сгруппированное поле; ни одно поле не сидит на двух вкладках (правило «первое побеждает» здесь ненаблюдаемо); неизвестное поле — нет записи"),
    ("activate_tab_switches_buttons_and_panels", '', '(() => { m.activateTab("", 2); return [activeTab(), E.body.children.findIndex((p) => p.classList.has("active")), E.bar.children[2].scrolled, E.bar.events]; })()', '[2,2,1,["scroll"]]',
     "переключение вкладки: активны кнопка и панель с индексом, кнопка прокручена в вид, панель уведомлена scroll"),
    ("activate_tab_without_bar", 'delete globalThis.__fields.dynamicFields;', '(() => { m.activateTab("", 1); return true; })()', 'true', "negative: без панели вкладок — без исключения"),
    ("mark_field_lights_tab_and_field_without_switching", '', '(() => { m.markFieldTab("", "THREADS"); return [litTab() === tabOf("THREADS"), activeTab(), E.fieldsIn.THREADS.parent.classList.has("field-located")]; })()', '[true,0,true]',
     "подсветка: вкладка поля и само поле помечены, активная вкладка НЕ меняется"),
    ("mark_field_clears_previous", '', '(() => { m.markFieldTab("", "THREADS"); m.markFieldTab("", "N_GPU_LAYERS"); const a = [litTab() === tabOf("N_GPU_LAYERS"), E.fieldsIn.THREADS.parent.classList.has("field-located"), E.fieldsIn.N_GPU_LAYERS.parent.classList.has("field-located")]; m.markFieldTab("", ""); return [...a, litTab()]; })()',
     '[true,false,true,-1]', "новая подсветка снимает прежнюю; пустое поле — только снятие"),
    ("mark_absent_field", '', '(() => { m.markFieldTab("", "CTX_SIZE"); return [litTab() === tabOf("CTX_SIZE"), document.querySelectorAll(".tab-located, .field-located").length]; })()', '[true,1]',
     "поле без инпута в этом редакторе: вкладка подсвечена, самого поля нет — помечена только вкладка"),
    ("reveal_field_switches_flashes_focuses", '', '(() => { const ok = m.revealField("", "THREADS"); const fe = E.fieldsIn.THREADS.parent; return [ok, activeTab() === tabOf("THREADS"), fe.classList.has("field-flash"), fe.classList.has("field-located"), fe.scrolled, E.fieldsIn.THREADS.focused, [...globalThis.__timers]]; })()',
     '[true,true,true,true,1,1,[1600]]', "показать поле: вкладка переключена, поле прокручено, вспыхнуло, подсвечено, фокус в инпуте, вспышка гаснет через 1.6 с"),
    ("reveal_absent_field_is_false", '', '(() => { const ok = m.revealField("", "CTX_SIZE"); return [ok, activeTab() === tabOf("CTX_SIZE")]; })()', '[false,true]',
     "negative: поля нет в редакторе — false, но вкладка всё же переключена (as-is)"),
    ("search_ranks_name_prefix_first", '', '(() => search("thr").hits)()', '["THREADS"]', "поиск по началу имени"),
    ("search_exact_flag_beats_partial", '', '(() => [search("-ngl").hits, search("gpu").hits, search("--threads").hits])()', '[["N_GPU_LAYERS"],["N_GPU_LAYERS"],["THREADS"]]', "поиск по флагу: точный и частичный; имя содержит"),
    ("search_exact_flag_first_partial_second", '', '(() => [search("-n").hits, (h => [h[0], h.length >= 2])(search("t").hits)])()', '[["N_PREDICT","N_GPU_LAYERS"],["THREADS",true]]', "точный флаг (-n у N_PREDICT) выше частичного (-ngl содержит -n); однобуквенный -t — THREADS первым"),
    ("search_ignores_server_only_fields", '', '(() => search("ctx").hits)()', '[]', "поле есть у сервера, но инпута в редакторе нет — не ищется"),
    ("search_empty_shows_hint", '', '(() => { const r = search("zzzz"); return [r.results.hidden, r.results.innerHTML.includes("config-search-empty"), r.hits.length]; })()', '[false,true,0]', "ничего не найдено — подсказка, результаты показаны"),
    ("search_blank_closes", '', '(() => { const r = search("thr"); r.input.value = "   "; r.input.listeners.input[0](); return [r.results.hidden, r.results.innerHTML, litTab()]; })()', '[true,"",-1]', "пустой запрос закрывает результаты и гасит подсветку"),
    ("search_top_hit_lights_tab", '', '(() => { search("thr"); return [litTab() === tabOf("THREADS"), activeTab()]; })()', '[true,0]', "верхний хит сразу подсвечивает вкладку, не переключая её"),
    ("search_arrows_move_cursor", '', '(() => { const r = search("t"); const kd = (key) => { let p = 0; r.input.listeners.keydown[0]({ key, preventDefault: () => p++ }); return p; }; const a = kd("ArrowDown"); const active1 = r.results.children.findIndex((b) => b.classList.has("active")); const lit1 = litTab() === tabOf(r.hits[1]); kd("ArrowDown"); const active2 = r.results.children.findIndex((b) => b.classList.has("active")); kd("ArrowDown"); const wrapped = r.results.children.findIndex((b) => b.classList.has("active")); kd("ArrowUp"); const active3 = r.results.children.findIndex((b) => b.classList.has("active")); return [r.hits.length, a, active1, lit1, active2, wrapped, active3]; })()',
     '[3,1,1,true,2,0,2]', "стрелки по трём хитам: вниз — второй (его вкладка подсвечена), третий, по кругу — первый; вверх — назад на третий"),
    ("search_enter_reveals", '', '(() => { const r = search("thr"); let p = 0; r.input.listeners.keydown[0]({ key: "Enter", preventDefault: () => p++ }); return [p, r.results.hidden, activeTab() === tabOf("THREADS"), E.fieldsIn.THREADS.focused]; })()', '[1,true,true,1]',
     "Enter выбирает текущий хит: результаты спрятаны, вкладка переключена, фокус в поле"),
    ("search_escape_closes", '', '(() => { const r = search("thr"); r.input.listeners.keydown[0]({ key: "Escape", preventDefault() {} }); return [r.input.value, r.results.hidden, litTab()]; })()', '["",true,-1]', "Escape: поле поиска очищено, результаты спрятаны, подсветка снята"),
    ("search_hover_and_click_hit", '', '(() => { const r = search("t"); const second = r.results.children[1]; r.results.listeners.mouseover[0]({ target: second }); const lit = litTab() === tabOf(r.hits[1]); r.results.listeners.click[0]({ target: second }); return [lit, r.results.hidden, activeTab() === tabOf(r.hits[1])]; })()', '[true,true,true]',
     "наведение на хит подсвечивает его вкладку, клик — показывает поле"),
    ("search_click_outside_hides", '', '(() => { const r = search("thr"); docListeners.click.at(-1)({ target: E.preview }); const a = r.results.hidden; r.input.listeners.focus[0](); return [a, r.results.hidden]; })()', '[true,false]', "клик вне поиска прячет результаты; фокус с непустым запросом показывает снова"),
    ("locator_binds_once_and_marks_on_hover", '', '(() => { m.bindCommandLocator(""); m.bindCommandLocator(""); const p = E.preview; const n = (p.listeners.mouseover || []).length; p.listeners.mouseover[0]({ target: E.tok }); const lit = litTab() === tabOf("THREADS"); p.listeners.mouseover[0]({ target: E.plain }); const still = litTab() === tabOf("THREADS"); p.listeners.mouseleave[0](); return [n, lit, activeTab(), still, litTab()]; })()',
     '[1,true,0,true,-1]', "локатор биндится один раз; наведение на токен подсвечивает вкладку без переключения, на обычный текст — ничего не меняет, уход — гасит"),
    ("locator_click_reveals", '', '(() => { m.bindCommandLocator(""); E.preview.listeners.click[0]({ target: E.tok }); return [activeTab() === tabOf("THREADS"), E.fieldsIn.THREADS.focused]; })()', '[true,1]', "клик по токену переключает вкладку и показывает поле"),
    ("locator_without_preview", 'delete globalThis.__fields.previewCmdline;', '(() => { m.bindCommandLocator(""); return true; })()', 'true', "negative: без превью — без исключения"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 18:
        print(f"js config-locator FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js config-locator: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_config_locator.tmp.mjs"
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
        print(f"js config-locator FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("поиск настройки: индекс, ранжирование, подсветка вкладки:")
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
    print(f"js config-locator OK: настоящий модуль в node, {len(PINS)} пинов локатора значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
