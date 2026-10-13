#!/usr/bin/env python3
"""Snapshot of static/js/model-schedule.js — when a model is open, on the kanban (1.3.498).

Pinned by value, with the module loaded for real (scripts/_js_harness.mjs): the
caravan's time in the board's language — the controller's zone by its name, by its
offset when the browser does not know the name, UTC when the controller does not
know its zone; a model's ⏱ in its five states (no schedule, switched off, open
until, open always, closed until) and a pool row's word for a model closed now;
the window — the zone said or its absence said, what the saved schedule says now,
a week of hours with the caravan's hour marked, the windows with exact times, the
cell's note that step 1 starts and stops no server, Save held back while a schedule
switched on has no window; the operator's acts — a window added, a day taken from
"every day", a window of no day dropped, the switch, an exact time, a stroke over
the hours read back as windows one way; the save — what goes on the wire, the
window closed and the board drawn from the answer, a refusal said with the window
kept. Strings come from en.js.

Run: python3 scripts/test_js_model_schedule.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

# i18n.js reaches the whole page through form.js; the modules that close the circle back to the
# kanban are stubs, as in scripts/test_js_pool_board.py — the window is loaded on its own.
STUBS = ("dialogs,topology-render,consumer-access,polling,remote-cells,topology-dnd,canvas,charts,cables,history,"
         "favorites,config-locator,system-panels,onboarding,onboarding-tours,dialog-llamas,models-page,system-page,"
         "memory,command-preview,llama-edit,topology-nodes,topology-modals,topology-activity,topology-proxies,routers,"
         "cloud,usage-stats")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const ms = await import(pathToFileURL(process.env.JS_ROOT + "/model-schedule.js").href);
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const fill = (s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => v[k]);
// Monday 2026-10-12, 12:00 in Tbilisi (UTC+4): 08:00 UTC.
const MON_NOON = Date.UTC(2026, 9, 12, 8, 0) / 1000;
const ZONE = { name: "Asia/Tbilisi", known: true, offsetMinutes: 240 };
const W = [{ days: [0, 1, 2, 3, 4], from: "09:00", to: "19:00" }];
const N = [{ days: [], from: "19:00", to: "09:00" }];
const TOP = () => ({ modelSchedules: { zone: ZONE, now: MON_NOON, models: {
  "acc:or/meta/llama": { enabled: true, windows: W, open: true, until: MON_NOON + 7 * 3600, opensAt: null },
  "out:srv:22011": { enabled: true, windows: N, open: false, until: null, opensAt: MON_NOON + 7 * 3600 },
  "acc:or/off": { enabled: false, windows: W, open: true, until: null, opensAt: null },
  "acc:or/always": { enabled: true, windows: [{ days: [], from: "00:00", to: "00:00" }], open: true, until: null, opensAt: null },
  "acc:or/later": { enabled: true, windows: W, open: false, until: null, opensAt: MON_NOON + 2 * 86400 } } } });
const editor = (over = {}) => {
  const log = { calls: [], notes: [], applied: [], redraws: 0 };
  const e = new ms.ModelScheduleEditor({
    call: async (path, o) => { log.calls.push([path, JSON.parse(o.body)]); if (over.fail) throw new Error("window 1: days must be numbers 0..6"); return over.res || { ok: true, topology: { marker: 1 } }; },
    notify: (x) => log.notes.push(x), apply: (top) => log.applied.push(top), redraw: () => { log.redraws += 1; }, now: () => MON_NOON });
  e.set(over.top || TOP());
  return [e, log];
};
// A stand-in for an element: attributes, dataset, classes, a parent — enough for the window's handlers.
const camel = (s) => s.replace(/-(\w)/g, (_, c) => c.toUpperCase());
const el = (attrs = {}, extra = {}) => {
  const n = { attrs, dataset: {}, classes: new Set(), ...extra };
  for (const [k, v] of Object.entries(attrs)) if (k.startsWith("data-")) n.dataset[camel(k.slice(5))] = v;
  n.classList = { remove: (...cs) => cs.forEach((c) => n.classes.delete(c)), toggle: (c, on) => (on ? n.classes.add(c) : n.classes.delete(c)) };
  n.hasAttribute = (a) => Object.prototype.hasOwnProperty.call(n.attrs, a);
  n.closest = (sel) => (sel === "[data-ms-cell]" && n.hasAttribute("data-ms-cell") ? n : null);
  return n;
};
const cell = (d, h) => el({ "data-ms-cell": `${d}:${h}` });
const ev = (target) => ({ target, preventDefault() {} });
const count = (h, re) => (h.match(re) || []).length;
// A string as the page writes it: an apostrophe as &#39; (utils.js escapeHtml).
const html = (s) => String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
const out = {};
"""

PINS = [
    # ── the caravan's time ──
    ("clock_in_the_caravans_zone",
     'const c = new ms.ScheduleClock(ZONE, "en");',
     '[c.parts(MON_NOON), c.when(MON_NOON + 7 * 3600, MON_NOON), c.when(MON_NOON + 2 * 86400, MON_NOON), c.offsetText(),'
     ' new ms.ScheduleClock(ZONE, "ru").dayName(0), new ms.ScheduleClock({ name: "Nowhere/X", known: true, offsetMinutes: 240 }).parts(MON_NOON).hour,'
     ' new ms.ScheduleClock({ name: "", known: false, offsetMinutes: 0 }).parts(MON_NOON).hour, new ms.ScheduleClock(null).offsetText()]',
     '[{"day":0,"hour":12,"minute":0,"date":"2026-10-12"},"19:00","Wed 12:00","UTC+04:00","пн",12,8,"UTC+00:00"]',
     "время каравана: по имени зоны; сегодня — часы, позже — день и часы; день недели на языке доски; зона, которой браузер не знает, — "
     "по сдвигу; зона не известна — UTC, а не часы браузера"),
    # ── a model's ⏱ ──
    ("chip_five_states",
     'const [e] = editor(); const chip = (k) => e.chipHtml(k, "Llama");'
     ' const of = (h) => [(h.match(/data-t-state="([^"]*)"/) || [])[1], (h.match(/>([^<]*)<\\/button>/) || [])[1], (h.match(/ title="([^"]*)"/) || [])[1]];',
     '[of(chip("acc:or/meta/llama")), of(chip("out:srv:22011")), of(chip("acc:or/off")), of(chip("acc:or/always")), of(chip("acc:or/none")),'
     ' chip("acc:or/meta/llama").includes(\'data-ms-open="acc:or/meta/llama" data-ms-title="Llama"\'), chip("acc:or/meta/llama").includes(\'data-t="pb-model-schedule"\')]',
     '[["open","⏱ until 19:00","When the model is open: no schedule, so at any time. Click to set one."],'
     '["closed","⏱ closed until 19:00","When the model is open: no schedule, so at any time. Click to set one."],'
     '["off","⏱","The schedule is off: the model is open at any time."],'
     '["open","⏱ always open","When the model is open: no schedule, so at any time. Click to set one."],'
     '["none","⏱","When the model is open: no schedule, so at any time. Click to set one."],true,true]',
     "⏱ модели: открыта до…, закрыта до…, выключено — тихий ⏱ (открыта всегда), открыта всегда, нет расписания — тихий ⏱; "
     "кнопка знает модель и её имя"),
    ("pool_row_word",
     'const [e] = editor();',
     '[e.closedWord("out:srv:22011"), e.closedWord("acc:or/later"), e.closedWord("acc:or/meta/llama"), e.closedWord("acc:or/off"), e.closedWord("acc:or/none")]',
     '["closed until 19:00","closed until Wed 12:00",null,null,null]',
     "строка пула закрытой модели говорит, до когда; negative: открыта, расписание выключено, расписания нет — слова нет"),
    # ── the window ──
    ("open_copies_what_is_kept",
     'const [e, log] = editor(); const f = e.open("acc:or/meta/llama", "Llama"); f.windows[0].days.push(6);',
     '[e.entry("acc:or/meta/llama").windows[0].days, e.open("acc:or/new", "New").enabled, e.form.windows, log.redraws]',
     '[[0,1,2,3,4],true,[],2]',
     "окно правит копию: сохранённое не меняется до «Сохранить»; у модели без расписания переключатель сразу включён"),
    ("window_says_zone_and_now",
     'const [e] = editor(); e.open("acc:or/meta/llama", "Llama"); const h = e.html();'
     ' const [u] = editor({ top: { modelSchedules: { zone: { name: "UTC", known: false, offsetMinutes: 0 }, now: MON_NOON, models: {} } } }); u.open("acc:x/y", "Y"); const hu = u.html();',
     '[h.includes(fill(en.pbSchedZone, { zone: "Asia/Tbilisi", offset: "UTC+04:00", now: "Mon 12:00" })),'
     ' h.includes(\'data-t-state="open">\' + fill(en.pbSchedNowOpen, { time: "19:00" })), h.includes(fill(en.pbSchedTitle, { model: "Llama" })),'
     ' hu.includes(html(en.pbSchedZoneUnknown)), hu.includes("pb-schedule-now"), h.includes(\'data-t="pb-schedule" data-t-id="acc:or/meta/llama" data-t-state="on"\')]',
     '[true,true,true,true,false,true]',
     "окно: зона каравана и её сдвиг, время сейчас по ней, что расписание говорит сейчас; negative: зона не известна — сказано; "
     "у модели без расписания строки «сейчас» нет — нечего сказать"),
    ("grid_week_of_hours",
     'const [e] = editor(); e.open("acc:or/meta/llama", "Llama"); const h = e.html();',
     '[count(h, /class="ms-cell[^"]*" data-ms-cell=/g), count(h, /class="ms-cell full[^"]*"/g), count(h, /class="ms-cell[^"]* now"/g),'
     ' h.includes(\'class="ms-cell full now" data-ms-cell="0:12"\'), h.includes(\'data-ms-cell="5:12"\') && !h.includes(\'class="ms-cell full" data-ms-cell="5:12"\'),'
     ' count(h, /class="ms-day"/g)]',
     '[168,50,1,true,true,7]',
     "сетка недели: 7 дней по 24 часа; будни 09–19 — 50 закрашенных часов; час каравана сейчас отмечен (понедельник, 12); "
     "суббота не закрашена"),
    ("windows_with_exact_times",
     'const [e] = editor(); e.open("acc:or/meta/llama", "Llama"); const h = e.html();',
     '[count(h, /data-t="pb-schedule-window"/g), count(h, /class="ms-daybtn on"/g), h.includes(\'data-ms-from="0" value="09:00"\'),'
     ' h.includes(\'data-ms-to="0" value="19:00"\'), h.includes(\'data-ms-day="0:5" aria-pressed="false"\')]',
     '[1,5,true,true,true]',
     "окна с точным временем: одно окно, пять дней нажаты, с 09:00 до 19:00; суббота не нажата"),
    ("cell_note_and_save_held",
     'const [e] = editor(); e.open("out:srv:22099", "Coder :22099"); const h = e.html(); e.form.enabled = false; const off = e.html();',
     '[h.includes(html(en.pbSchedCellNote)), h.includes(en.pbSchedNeedsWindow), /data-ms-save data-t="pb-schedule-save" disabled/.test(h), h.includes(en.pbSchedNoWindows),'
     ' /data-ms-save data-t="pb-schedule-save" disabled/.test(off), off.includes(en.pbSchedNeedsWindow), off.includes(\'class="ms-grid off"\')]',
     '[true,true,true,true,false,false,true]',
     "ячейка: сказано, что сервер по расписанию пока не запускается; включено без окон — «Сохранить» недоступна и сказано почему; "
     "выключено — сохранить можно, сетка бледная"),
    # ── what the operator does ──
    ("add_remove_and_days",
     'const [e] = editor(); e.open("acc:or/new", "New"); e.click(el({ "data-ms-add": "" }));'
     ' const added = JSON.parse(JSON.stringify(e.form.windows)); e.click(el({ "data-ms-day": "0:2" })); const six = [...e.form.windows[0].days];'
     ' e.click(el({ "data-ms-day": "0:2" })); const back = [...e.form.windows[0].days];'
     ' e.form.windows = [{ days: [3], from: "08:00", to: "09:00" }]; e.click(el({ "data-ms-day": "0:3" })); const gone = e.form.windows.length;'
     ' e.click(el({ "data-ms-add": "" })); e.click(el({ "data-ms-remove": "0" }));',
     '[added, six, back, gone, e.form.windows.length]',
     '[[{"days":[],"from":"09:00","to":"18:00"}],[0,1,3,4,5,6],[],0,0]',
     "＋ окно — каждый день 09–18; день, снятый с «каждого дня», оставляет шесть; все семь снова — каждый день; "
     "negative: окно без дней убирается, а не читается как каждый день; ✕ убирает окно"),
    ("switch_and_exact_time",
     'const [e] = editor(); e.open("acc:or/meta/llama", "Llama");'
     ' e.change(el({ "data-ms-enabled": "" }, { checked: false })); const off = e.form.enabled;'
     ' e.change(el({ "data-ms-from": "0" }, { value: "07:30" })); e.change(el({ "data-ms-to": "0" }, { value: "" }));',
     '[off, e.form.windows[0].from, e.form.windows[0].to, e.change(el({ "data-x": "" }))]',
     '[false,"07:30","19:00",false]',
     "переключатель выключает; точное время ставится; negative: недописанное время окно не меняет; чужое поле окно не трогает"),
    ("stroke_over_hours",
     'const [e, log] = editor(); e.open("acc:or/meta/llama", "Llama"); const noon = cell(0, 12);'
     ' const pressed = e.press(ev(noon)); const closing = e.painting.open; e.release();'
     ' const afterClose = JSON.parse(JSON.stringify(e.form.windows));'
     ' const a = cell(6, 3); e.press(ev(a)); e.over(ev(cell(6, 4))); e.over(ev(cell(6, 5))); const lit = [...a.classes]; e.release();',
     '[pressed, closing, afterClose, e.form.windows.find((w) => w.days.length === 1 && w.days[0] === 6), lit, e.press(ev(el())), e.painting, e.release()]',
     '[true,false,[{"days":[0],"from":"09:00","to":"12:00"},{"days":[0],"from":"13:00","to":"19:00"},{"days":[1,2,3,4],"from":"09:00","to":"19:00"}],'
     '{"days":[6],"from":"03:00","to":"06:00"},["full"],false,null,false]',
     "нажатие на открытый час закрывает его, на закрытый — открывает, и так каждый час, по которому прошёл указатель; окна "
     "пишутся заново одним видом; negative: нажатие мимо сетки — не рисование, отпускание без рисования — ничего"),
    ("save_sends_and_closes",
     'const [e, log] = editor(); e.open("acc:or/meta/llama", "Llama"); await e.save();',
     '[log.calls, log.applied, log.notes, e.form]',
     '[[["/api/models/schedule",{"model":"acc:or/meta/llama","schedule":{"enabled":true,"windows":[{"days":[0,1,2,3,4],"from":"09:00","to":"19:00"}]}}]],'
     '[{"marker":1}],["Saved: when Llama is open"],null]',
     "«Сохранить»: модель и расписание уходят в дверь, окно закрыто, доска нарисована из ответа, сказано, что сохранено"),
    ("save_refused_or_held",
     'const [e, log] = editor({ fail: true }); e.open("acc:or/meta/llama", "Llama"); const res = await e.save();'
     ' const [h, hl] = editor(); h.open("acc:or/new", "New"); const held = await h.save();',
     '[res, log.notes, e.form && e.form.key, e.form && e.form.busy, held, hl.calls.length]',
     '[null,["window 1: days must be numbers 0..6"],"acc:or/meta/llama",false,null,0]',
     "отказ контроллера сказан его словами, окно остаётся с правкой; negative: включено без окон — ничего не уходит"),
    ("close_and_escape",
     'const [e] = editor(); e.open("acc:or/meta/llama", "Llama"); const closed = e.click(el({ "data-ms-close": "" }));',
     '[closed, e.form, e.html(), e.close(), e.click(el({ "data-ms-add": "" }))]',
     '[true,null,"",null,false]',
     "✕ и «Отмена» закрывают окно без записи; negative: закрытое окно не рисуется и кнопок не принимает"),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    node = find_node()
    if node is None:
        print("js model schedule: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.stack || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_model_schedule.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "America/Los_Angeles"}
        run = subprocess.run(
            [node, "--import",
             f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
             str(path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout)
        print(run.stderr)
        print(f"js model schedule FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("расписание модели на канбане (браузер в другой зоне — Лос-Анджелес):")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:500]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:500]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js model schedule OK: настоящий модуль в node, {len(PINS)} пинов значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
