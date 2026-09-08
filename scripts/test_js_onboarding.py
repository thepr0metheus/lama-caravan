#!/usr/bin/env python3
"""Snapshot of static/js/onboarding.js — the tour engine, with no dependencies.

What's pinned by value. `createTour`: live steps are only the ones whose
anchor is visible (a hidden ancestor, zero size, visibility:hidden — the step
is dropped; a step with `center` always stays); the card — title, body, an
"n/N" counter, "Back" hidden on the first step, "Next" turning into "Done" on
the last; `go` never runs past the edges, past the last step it stops with
`finished=true`; Escape stops with `finished=false`; the arrow keys page
through; a second tour stops the first one (not a stack); `rebuildStep`
rebuilds the steps in place after a language change; a tour with no live
steps never starts. `autoStartOnce`: an already-seen key does nothing; the
first real action taken BEFORE readiness cancels the tour and STILL RECORDS
the flag (a surprise on the next visit would be the same bug); readiness
starts the tour after a pause, if nothing was clicked during that pause; a
timeout exits quietly. `initTourButtons`: clicking [data-ob-tour] clears the
pulse and calls onClick; the decorator adds the caption and the pulse for as
long as the button goes unused; with no button in the markup, a floating one
appears after 4s.

The DOM is minimal elements with classList/style/listeners; timers are a
queue advanced by hand (`tick`), so nothing waits on a real second.

Run: python3 scripts/test_js_onboarding.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ""

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
// Таймеры — очередь с ручным продвижением: tick(ms) исполняет всё, что должно было сработать.
let now = 0; const timers = []; let tid = 0;
globalThis.setTimeout = (fn, ms) => { timers.push({ id: ++tid, at: now + (Number(ms) || 0), fn, every: 0 }); return tid; };
globalThis.setInterval = (fn, ms) => { timers.push({ id: ++tid, at: now + (Number(ms) || 1), fn, every: Number(ms) || 1 }); return tid; };
globalThis.clearTimeout = globalThis.clearInterval = (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); };
const tick = (ms) => { const until = now + ms; for (;;) { const due = timers.filter((t) => t.at <= until).sort((a, b) => a.at - b.at)[0]; if (!due) break; now = due.at; if (due.every) due.at += due.every; else timers.splice(timers.indexOf(due), 1); due.fn(); } now = until; };
Date.now = () => 1_700_000_000_000 + now;
globalThis.requestAnimationFrame = (fn) => { fn(); return 0; };
globalThis.innerWidth = 1000; globalThis.innerHeight = 800;
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), has: (c) => s.has(c) } };
const mkEl = (props = {}) => { const e = { textContent: "", innerHTML: "", title: "", attrs: {}, style: {}, classList: cls(), listeners: {}, children: [], parent: null, hiddenAncestor: false, rect: { left: 100, top: 100, width: 50, height: 20 }, visibility: "visible", offsetHeight: 180, scrolled: 0, removed: false,
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, setAttribute(k, v) { this.attrs[k] = v; }, getBoundingClientRect() { return this.rect; }, closest(sel) { return sel === "[hidden]" && this.hiddenAncestor ? this : null; },
  scrollIntoView() { this.scrolled += 1; }, remove() { this.removed = true; }, appendChild(c) { c.parent = this; this.children.push(c); }, querySelector(sel) { return this.q?.[sel] || null; }, ...props }; return e; };
globalThis.getComputedStyle = (el) => ({ visibility: el.visibility || "visible" });
// Корень тура строится через innerHTML и потом ищется по классам — модель отдаёт ожидаемые узлы.
document.createElement = (tag) => { const e = mkEl({ tag }); if (tag === "div") { const parts = {}; for (const c of [".ob-spot", ".ob-card", ".ob-close", ".ob-title", ".ob-body", ".ob-back", ".ob-next", ".ob-count"]) parts[c] = mkEl({ cls: c }); e.q = parts; } globalThis.__created.push(e); return e; };
globalThis.__created = [];
globalThis.__anchors = {}; document.querySelector = (sel) => (Object.prototype.hasOwnProperty.call(globalThis.__anchors, sel) ? globalThis.__anchors[sel] : null);
globalThis.__all = []; document.querySelectorAll = (sel) => (sel === "[data-ob-tour]" ? globalThis.__all : []);
const docListeners = {}; document.addEventListener = (t, fn) => { (docListeners[t] ||= []).push(fn); }; document.removeEventListener = (t, fn) => { const l = docListeners[t] || []; const i = l.indexOf(fn); if (i >= 0) l.splice(i, 1); };
const winListeners = {}; globalThis.addEventListener = (t, fn) => { (winListeners[t] ||= []).push(fn); }; globalThis.removeEventListener = (t, fn) => { const l = winListeners[t] || []; const i = l.indexOf(fn); if (i >= 0) l.splice(i, 1); };
document.body = { appended: [], appendChild(e) { this.appended.push(e); } };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/onboarding.js").href);
const STEPS = () => [{ anchor: "#a", title: "A", body: "<b>a</b>" }, { anchor: "#gone", title: "G" }, { anchor: "#b", title: "B" }, { center: true, title: "C" }];
const LABELS = { back: "Назад", next: "Далее", done: "Готово", skip: "Закрыть" };
const root = () => globalThis.__created.filter((e) => e.tag === "div" && e.className === "ob-root").at(-1);
const part = (sel) => root().q[sel];
let stopped = []; const tours = [];
const reset = () => { for (const t of tours.splice(0)) { try { t.stop(); } catch {} } stopped = []; timers.length = 0; now = 0; localStorage.clear(); globalThis.__created.length = 0; globalThis.__anchors = { "#a": mkEl(), "#b": mkEl() }; globalThis.__all = []; document.body.appended.length = 0; for (const k of Object.keys(docListeners)) delete docListeners[k]; for (const k of Object.keys(winListeners)) delete winListeners[k]; };
reset();
const tourOf = (steps = STEPS()) => { const t = m.createTour({ steps: () => steps, labels: () => LABELS, onStop: (f) => stopped.push(f) }); tours.push(t); return t; };
const out = {};
"""

PINS = [
    ("live_steps_skip_invisible_anchors", '', '(() => { const t = tourOf(); t.start(); return [t.active(), part(".ob-count").textContent, part(".ob-title").textContent, part(".ob-body").innerHTML]; })()', '[true,"1/3","A","<b>a</b>"]',
     "старт: шаг с отсутствующим якорем выпал (3 из 4), первый шаг на карточке: заголовок, тело, счётчик"),
    ("hidden_ancestor_zero_size_and_visibility_drop_steps", 'globalThis.__anchors["#a"].hiddenAncestor = true; globalThis.__anchors["#b"].rect = { left: 0, top: 0, width: 1, height: 1 };', '(() => { const t = tourOf(); t.start(); const a = part(".ob-count").textContent; t.stop(); globalThis.__anchors["#b"] = mkEl({ visibility: "hidden" }); globalThis.__anchors["#a"] = mkEl(); const t2 = tourOf(); t2.start(); return [a, part(".ob-count").textContent]; })()', '["1/1","1/2"]',
     "якорь под скрытым предком, нулевого размера или visibility:hidden — шаг выпадает; центрированный шаг остаётся всегда"),
    ("no_live_steps_no_tour", 'globalThis.__anchors = {};', '(() => { const t = tourOf([{ anchor: "#zzz", title: "Z" }]); t.start(); return [t.active(), globalThis.__created.length, stopped.length]; })()', '[false,0,0]', "negative: ни одного живого шага — тур не строится и не зовёт onStop"),
    ("navigation_labels_and_bounds", '', '(() => { stopped = []; const t = tourOf(); t.start(); const first = [part(".ob-back").style.visibility, part(".ob-next").textContent]; part(".ob-next").listeners.click[0](); const second = [part(".ob-count").textContent, part(".ob-back").style.visibility, part(".ob-title").textContent]; part(".ob-back").listeners.click[0](); part(".ob-back").listeners.click[0](); const back = part(".ob-count").textContent; part(".ob-next").listeners.click[0](); part(".ob-next").listeners.click[0](); const last = [part(".ob-count").textContent, part(".ob-next").textContent]; part(".ob-next").listeners.click[0](); return [...first, ...second, back, ...last, t.active(), stopped]; })()',
     '["hidden","Далее","2/3","visible","B","1/3","3/3","Готово",false,[true]]', "«Назад» скрыт на первом, назад за край не уводит, на последнем «Готово», и оно завершает тур с finished=true"),
    ("escape_stops_unfinished_arrows_navigate", '', '(() => { stopped = []; const t = tourOf(); t.start(); const key = docListeners.keydown.at(-1); key({ key: "ArrowRight", stopPropagation() {} }); const a = part(".ob-count").textContent; key({ key: "ArrowLeft", stopPropagation() {} }); const b = part(".ob-count").textContent; let sp = 0; key({ key: "Escape", stopPropagation: () => sp++ }); return [a, b, t.active(), stopped, sp, root().removed]; })()',
     '["2/3","1/3",false,[false],1,true]', "стрелки листают; Escape останавливает с finished=false, гасит событие и снимает корень"),
    ("stop_unhooks_listeners", '', '(() => { const t = tourOf(); t.start(); const before = [docListeners.keydown.length, winListeners.resize.length, winListeners.scroll.length]; t.stop(); return [...before, docListeners.keydown.length, winListeners.resize.length, winListeners.scroll.length]; })()', '[1,1,1,0,0,0]', "стоп снимает слушатели клавиш, resize и scroll"),
    ("second_tour_replaces_first", '', '(() => { stopped = []; const t1 = tourOf(); t1.start(); const s0 = [...stopped]; const t2 = tourOf(); t2.start(); return [t1.active(), t2.active(), s0, [...stopped]]; })()', '[false,true,[],[false]]', "второй тур останавливает первый (не стопка), первому — finished=false"),
    ("card_positioned_below_then_flipped", '', '(() => { const t = tourOf(); t.start(); const below = [part(".ob-spot").style.left, part(".ob-spot").style.top, part(".ob-card").style.top, part(".ob-card").style.width]; globalThis.__anchors["#a"].rect = { left: 100, top: 700, width: 50, height: 20 }; winListeners.resize[0](); return [...below, part(".ob-card").style.top]; })()', '["94px","94px","140px","360px","500px"]',
     "пятно вокруг якоря с отступом 6; карточка под ним; когда снизу не помещается — над ним (700-180-14)"),
    ("center_step_positions_middle", '', '(() => { const t = tourOf([{ center: true, title: "C" }]); t.start(); return [part(".ob-spot").classList.has("ob-spot-center"), part(".ob-spot").style.left, part(".ob-card").style.left, part(".ob-card").style.top]; })()', '[true,"500px","320px","310px"]', "центрированный шаг: пятно в центре, карточка посередине"),
    ("rebuild_keeps_index_after_language_switch", '', '(() => { let n = 0; const steps = () => (n++ === 0 ? STEPS() : [{ anchor: "#a", title: "A2" }, { anchor: "#b", title: "B2" }]); const t = m.createTour({ steps, labels: LABELS, onStop() {} }); t.start(); part(".ob-next").listeners.click[0](); const before = part(".ob-title").textContent; let rerender = null; const t2 = m.createTour({ steps: () => [{ anchor: "#a", title: "X", onRender: (_b, api) => { rerender = api.rerender; } }, { anchor: "#b", title: "Y" }], labels: LABELS, onStop() {} }); t2.start(); part(".ob-next").listeners.click[0](); rerender(); return [before, part(".ob-count").textContent, part(".ob-title").textContent]; })()', '["B","2/2","Y"]',
     "пересборка шагов на месте сохраняет индекс"),
    ("auto_start_after_ready", '', '(() => { let ran = 0; m.autoStartOnce("k", () => now >= 1000, () => ran++); tick(900); const early = ran; tick(400); const readyNow = [ran, localStorage.getItem("caravanTourSeen:k")]; tick(600); return [early, ...readyNow, ran]; })()', '[0,0,"1",1]', "автостарт: опрос готовности раз в 400 мс; флаг записывается сразу при готовности, запуск — после паузы 600 мс"),
    ("auto_start_seen_key_skips", 'localStorage.setItem("caravanTourSeen:k", "1");', '(() => { let ran = 0; m.autoStartOnce("k", () => true, () => ran++); tick(5000); return [ran, docListeners.pointerdown ? docListeners.pointerdown.length : 0]; })()', '[0,0]', "negative: уже виденный ключ — ничего, слушатели не вешаются"),
    ("auto_start_cancelled_by_interaction", '', '(() => { let ran = 0; m.autoStartOnce("k", () => now >= 1000, () => ran++); tick(300); docListeners.pointerdown[0](); tick(3000); return [ran, localStorage.getItem("caravanTourSeen:k"), timers.length]; })()', '[0,"1",0]', "клик до готовности отменяет тур и ЗАПИСЫВАЕТ флаг; таймер снят"),
    ("auto_start_click_in_grace_cancels", '', '(() => { let ran = 0; m.autoStartOnce("k", () => true, () => ran++); tick(400); docListeners.keydown[0](); tick(700); return [ran, localStorage.getItem("caravanTourSeen:k")]; })()', '[0,"1"]', "клавиша в паузе перед запуском тоже отменяет"),
    ("auto_start_timeout", '', '(() => { let ran = 0; m.autoStartOnce("k", () => false, () => ran++, 2000); tick(2500); return [ran, localStorage.getItem("caravanTourSeen:k"), timers.length, (docListeners.pointerdown || []).length]; })()', '[0,null,0,0]', "таймаут без готовности — тихий выход без флага, слушатели сняты"),
    ("mark_tour_seen", '', '(() => { m.markTourSeen("x"); return localStorage.getItem("caravanTourSeen:x"); })()', '"1"', "ручная отметка «тур виден»"),
    ("tour_buttons_click_and_decorate", '', '(() => { const b = mkEl({ dataset: {} }); b.closest = () => b; globalThis.__all = [b]; let clicks = 0; m.initTourButtons({ onClick: () => clicks++, title: () => "Тур" }); const decorated = [b.title, b.attrs["aria-label"], b.classList.has("ob-btn-pulse")]; let prevented = 0; docListeners.click.at(-1)({ target: b, preventDefault: () => prevented++ }); tick(1500); return [...decorated, clicks, prevented, localStorage.getItem("caravanTourBtnUsed"), b.classList.has("ob-btn-pulse")]; })()',
     '["Тур","Тур",true,1,1,"1",false]', "кнопка тура: подпись и пульс до первого использования; клик зовёт onClick, снимает пульс и запоминает"),
    ("tour_buttons_fallback_floating", '', '(() => { m.initTourButtons({ onClick() {}, title: "T" }); tick(4000); const fl = document.body.appended.find((e) => e.className === "ob-btn-float"); return [!!fl, fl?.textContent, fl?.attrs["data-ob-tour"]]; })()', '[true,"?",""]', "без кнопки в разметке через 4 с появляется плавающая «?»"),
    ("tour_buttons_no_fallback_when_present", '', '(() => { const b = mkEl({ dataset: {} }); globalThis.__all = [b]; globalThis.__anchors["[data-ob-tour]"] = b; m.initTourButtons({ onClick() {}, title: "T" }); tick(4000); return document.body.appended.filter((e) => e.className === "ob-btn-float").length; })()', '0', "negative: кнопка есть — плавающая не добавляется"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 16:
        print(f"js onboarding FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js onboarding: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_onboarding.tmp.mjs"
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
        print(f"js onboarding FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("онбординг: движок тура, автостарт, кнопки:")
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
    print(f"js onboarding OK: настоящий модуль в node, {len(PINS)} пинов онбординга значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
