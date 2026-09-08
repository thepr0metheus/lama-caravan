#!/usr/bin/env python3
"""Snapshot of static/js/onboarding-tours.js — which tour, and when.

What's pinned by value: picking the step set from the page's state (the
te/tr editor open → the editor tour with its prefix; standalone kanban → the
kanban tour; otherwise → the board tour); the board's and editor's step
anchors (this is data, and a step with a nonexistent anchor is a step nobody
will ever see); button captions from i18n; the language picker on the
welcome step calls setLang and redraws the tour; tour strings get merged into
the language table when it loads; the editor's first open starts its tour
after 0.9s — only if nothing was touched in that window, and only once (a flag).

The tour engine and i18n are stubs recording their calls; `document.getElementById`
is a dict; MutationObserver is a stub fired by hand.

Run: python3 scripts/test_js_onboarding_tours.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = "onboarding,i18n,i18n-data"

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
globalThis.__stubValues = { "i18n-data.LANGS": [{ code: "en", emoji: "🍔", label: "English" }, { code: "ru", emoji: "🥟", label: "Русский" }], "i18n-data.messages": { en: {}, ru: {} }, "i18n.lang": "en" };
globalThis.__loaded = []; globalThis.__timers = []; globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push({ fn, ms }); return 0; };
globalThis.__observers = []; globalThis.MutationObserver = class { constructor(cb) { this.cb = cb; this.targets = []; this.disconnected = false; globalThis.__observers.push(this); } observe(el) { this.targets.push(el); } disconnect() { this.disconnected = true; } fire() { this.cb(); } };
const docListeners = {}; document.addEventListener = (t, fn) => { (docListeners[t] ||= []).push(fn); }; document.removeEventListener = (t, fn) => { const l = docListeners[t] || []; const i = l.indexOf(fn); if (i >= 0) l.splice(i, 1); };
document.createElement = () => ({ className: "", innerHTML: "", listeners: {}, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } });
globalThis.__q = {}; document.querySelector = (sel) => (Object.prototype.hasOwnProperty.call(globalThis.__q, sel) ? globalThis.__q[sel] : null);
globalThis.__stubReturns = { "i18n.t": (k) => "T:" + k, "i18n-data.onLanguageLoaded": (fn) => { globalThis.__loaded.push(fn); } };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/onboarding-tours.js").href);
const S = await import(pathToFileURL(process.env.JS_ROOT + "/onboarding-strings.js").href);
const F = () => globalThis.__fields;
let tours = [], buttons = null, autos = [], langCalls = [];
const reset = () => { tours = []; buttons = null; autos = []; langCalls = []; localStorage.clear(); globalThis.__timers.length = 0; globalThis.__observers.length = 0; globalThis.__q = {}; globalThis.__fields = {}; delete globalThis.ROUTER_STANDALONE; for (const k of Object.keys(docListeners)) delete docListeners[k];
  globalThis.__stubReturns = { "i18n.t": (k) => "T:" + k, "i18n.setLang": async (c) => { langCalls.push(c); }, "i18n-data.onLanguageLoaded": (fn) => { globalThis.__loaded.push(fn); },
    "onboarding.createTour": (cfg) => { const t = { cfg, started: 0, start() { this.started += 1; }, stop() {} }; tours.push(t); return t; }, "onboarding.initTourButtons": (o) => { buttons = o; }, "onboarding.autoStartOnce": (key, ready, fn) => { autos.push({ key, ready, fn }); } }; };
reset();
const steps = () => tours.at(-1).cfg.steps();
const out = {};
"""

PINS = [
    ("tour_strings_merge_into_language_table", '', '(() => { const table = {}; globalThis.__loaded[0]("ru", table); const en = {}; globalThis.__loaded[0]("en", en); const none = {}; globalThis.__loaded[0]("xx", none); return [Object.keys(table).length > 10, table.tourNext === S.TOUR_STRINGS.ru.tourNext, Object.keys(en).length > 10, Object.keys(none).length]; })()',
     '[true,true,true,0]', "строки туров вливаются в таблицу языка при её загрузке; языку без своих строк ничего не подмешивается (t() отдаст английский)"),
    ("index_tour_by_default", '', '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); return [st.length, st[0].center, st[0].title, typeof st[0].onRender, st[2].anchor, st[3].anchor, st.at(-1).center, tours.at(-1).started]; })()',
     '[14,true,"T:tourIxWelcomeT","function",".topology-board","#topologyClients",true,1]', "по умолчанию — тур доски: 14 шагов, приветствие с пикером языка, якоря лейн, финальный центрированный; кнопка запускает тур"),
    ("kanban_tour_when_standalone", 'globalThis.ROUTER_STANDALONE = true;', '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); return [st.length, st[1].anchor, st[2].anchor, autos[0].key]; })()',
     '[4,"[data-cv-viewport]",".cv-palette-btn","kanban"]', "standalone-канбан — свой тур из четырёх шагов и свой ключ автостарта"),
    ("editor_tour_when_modal_open", 'globalThis.__fields = { topologyLlamaEditOverlay: { hidden: false } };', '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); return [st.length, st[0].anchor, st[1].anchor, st.at(-1).anchor]; })()',
     '[12,"#topologyLlamaEditForm .cell-kind-toggle","#te-MODEL_FILE","#topologyLlamaEditSaveRestart"]', "открыт редактор ячейки доски (te) — тур редактора с его префиксом и кнопкой старта"),
    ("remote_editor_tour_prefix", 'globalThis.__fields = { llamaRemoteEditOverlay: { hidden: false } };', '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); return [st[1].anchor, st.at(-1).anchor]; })()',
     '["#tr-MODEL_FILE","#llamaRemoteEditStart"]', "удалённый редактор (tr) — те же шаги с префиксом tr и своей кнопкой"),
    ("labels_from_i18n", '', '(() => { m.initOnboarding(); buttons.onClick(); const L = tours.at(-1).cfg.labels; return [typeof L === "function" ? L() : L, buttons.title()]; })()',
     '[{"next":"T:tourNext","back":"T:tourBack","done":"T:tourDone","skip":"T:tourSkip"},"T:tourBtnTitle"]', "подписи кнопок и заголовок кнопки тура — из i18n"),
    ("auto_start_ready_and_guard", '', '(() => { m.initOnboarding(); const a = autos[0]; const notReady = a.ready(); globalThis.__fields = { appLoader: null }; globalThis.__q[".topology-board"] = {}; const ready = a.ready(); globalThis.__q[".ob-root"] = {}; a.fn(); const skipped = tours.length; delete globalThis.__q[".ob-root"]; a.fn(); return [a.key, notReady, ready, skipped, tours.length]; })()',
     '["index",false,true,0,1]', "автостарт доски: готовность = лоадер ушёл и доска есть; если тур уже открыт — не мешает"),
    ("auto_start_ready_with_loader_present", 'globalThis.__fields = { appLoader: {} }; globalThis.__q[".topology-board"] = {};', '(() => { m.initOnboarding(); return autos[0].ready(); })()', 'false', "negative: пока лоадер на месте — не готово"),
    ("lang_picker_switches_and_rerenders", '', '(() => { m.initOnboarding(); buttons.onClick(); const body = { appended: null, appendChild(el) { this.appended = el; } }; let rerendered = 0; steps()[0].onRender(body, { rerender: () => rerendered++ }); const wrap = body.appended; const html = wrap.innerHTML; wrap.listeners.click[0]({ target: { closest: () => ({ dataset: { obLang: "ru" } }) } }); wrap.listeners.click[0]({ target: { closest: () => null } }); return [wrap.className, html.includes(\'data-ob-lang="ru"\'), html.includes(\'ob-lang selected" data-ob-lang="en"\'), langCalls, rerendered]; })()',
     '["ob-langs",true,true,["ru"],1]', "пикер языка: кнопка на язык, текущий отмечен, клик переключает язык и перерисовывает тур; клик мимо — ничего"),
    ("editor_first_open_starts_tour_once", 'globalThis.__fields = { topologyLlamaEditOverlay: { hidden: true }, llamaRemoteEditOverlay: { hidden: true } };', '(() => { m.initOnboarding(); const obs = globalThis.__observers[0]; obs.fire(); const closedYet = [tours.length, localStorage.getItem("caravanTourSeen:config")]; globalThis.__fields.topologyLlamaEditOverlay.hidden = false; obs.fire(); const armed = [(docListeners.pointerdown || []).length, localStorage.getItem("caravanTourSeen:config"), globalThis.__timers.at(-1)?.ms]; globalThis.__timers.at(-1).fn(); return [...closedYet, ...armed, tours.length, obs.disconnected, (docListeners.pointerdown || []).length]; })()',
     '[0,null,1,"1",900,1,true,0]', "первое открытие редактора: пока закрыт — ничего; открылся — флаг, слушатели, через 0.9 с тур; наблюдатель отключён, слушатели сняты"),
    ("editor_first_open_cancelled_by_interaction", 'globalThis.__fields = { topologyLlamaEditOverlay: { hidden: false } };', '(() => { m.initOnboarding(); globalThis.__observers[0].fire(); docListeners.pointerdown[0](); globalThis.__timers.at(-1).fn(); return [tours.length, localStorage.getItem("caravanTourSeen:config")]; })()',
     '[0,"1"]', "клик за 0.9 с отменяет тур редактора, флаг всё равно записан — второй раз не предложит"),
    ("editor_watch_skipped_when_seen_or_no_overlays", '', '(() => { localStorage.setItem("caravanTourSeen:config", "1"); globalThis.__fields = { topologyLlamaEditOverlay: { hidden: true } }; m.initOnboarding(); const a = globalThis.__observers.length; localStorage.clear(); globalThis.__fields = {}; m.initOnboarding(); return [a, globalThis.__observers.length]; })()',
     '[0,0]', "negative: тур редактора уже виден или редакторов на странице нет — наблюдатель не ставится"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 10:
        print(f"js onboarding-tours FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js onboarding-tours: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_onboarding_tours.tmp.mjs"
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
        print(f"js onboarding-tours FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("туры онбординга: выбор набора шагов, подписи, первое открытие редактора:")
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
    print(f"js onboarding-tours OK: настоящий модуль в node, {len(PINS)} пинов туров значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
