#!/usr/bin/env python3
"""Actual header-machines.js: the bar's list of machines on every page, by value.

The owner, 2026-10-29: "buttons to all the connected machines, by a drop-down list is fine". What is pinned, on the real
module with a small page of its own: nothing is asked until the button is pressed; each press reads the list anew; each
machine is a link to its page, in the order answered, with a word for one that does not answer; the machine this page shows
says so; and each thing that is not a list of machines says what it is — reading, none, refused, an answer with no list.
An older reading that lands after a newer one says nothing.

Run: python3 scripts/test_js_header_machines.py
"""
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, probe_args
ROOT = Path(__file__).resolve().parent.parent
PROBE = r'''
globalThis.__stubReturns = {
  "utils.escapeHtml": (x) => String(x ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
};
const { HeaderMachines } = await import("../static/js/header-machines.js");
const { BoardView } = await import("../static/js/board-view.js");
const failed = [];
let pins = 0;
const pin = (what, got, want) => {
  pins++;
  const a = JSON.stringify(got), b = JSON.stringify(want);
  console.log(a === b ? `  ok  ${what}` : ` FAIL ${what}\n       got  ${a}\n       want ${b}`);
  if (a !== b) failed.push(what);
};
const el = () => ({ hidden: true, innerHTML: "", attrs: {}, on: {}, setAttribute(k, v) { this.attrs[k] = v; },
  addEventListener(type, fn) { this.on[type] = fn; }, contains(x) { return x === this || x === this.within; } });
const MAIN = new BoardView({ pathname: "/board", search: "" });
// A page with the bar's three elements, and a controller that answers `answers` in turn.
const page = (answers, { view = MAIN } = {}) => {
  const box = el(), button = el(), menu = el();
  box.within = menu;
  const listeners = {}, capture = {};
  const doc = { getElementById: (id) => ({ headerMachines: box, headerMachinesBtn: button, headerMachinesMenu: menu })[id] || null,
    addEventListener: (type, fn, phase) => { listeners[type] = fn; capture[type] = phase === true; } };
  const asked = [], queue = [...answers];
  const get = (url) => { asked.push(url); const next = queue.shift(); return typeof next === "function" ? next() : Promise.resolve(next); };
  const words = (key, values) => (values ? `${key}${JSON.stringify(values)}` : key);
  const header = new HeaderMachines({ doc, get, words, view });
  return { header, bound: header.bind(), button, menu, box, asked, listeners, capture,
    press: () => button.on.click({ stopPropagation() {} }) };
};
const LIST = { machines: [{ id: "alpha 1", name: "Alpha", online: true }, { id: "b", name: "B<ta", online: false }, { id: "c", name: "", online: true }] };
const rows = (html) => [...html.matchAll(/<a [^>]*href="([^"]*)"[^>]*data-t-id="([^"]*)"[^>]*>(.*?)<\/a>/g)].map((m) => [m[1], m[2], m[3].replace(/<[^>]+>/g, "|")]);

{
  const p = page([LIST]);
  pin("привязан; пока кнопку не нажали, ничего не спрошено и меню закрыто", [p.bound, p.asked, p.menu.hidden], [true, [], true]);
  const opening = p.press();
  pin("нажата: меню открыто и говорит, что читает, пока ответа нет", [p.menu.hidden, p.button.attrs["aria-expanded"], p.menu.innerHTML.includes(">headerMachinesReading<"), p.asked],
    [false, "true", true, ["/api/machines"]]);
  await opening;
  pin("каждая машина — ссылка на свою страницу, в порядке ответа, без имени — по id; не отвечающая так и названа",
    rows(p.menu.innerHTML), [["/machine?host=alpha%201", "alpha 1", "|||Alpha|"], ["/machine?host=b", "b", "|||B&lt;ta||headerMachineOff|"], ["/machine?host=c", "c", "|||c|"]]);
  pin("отвечающая — с зелёной точкой, не отвечающая — без неё", (p.menu.innerHTML.match(/topbar-machine-dot( on)?"/g) || []),
    ['topbar-machine-dot on"', 'topbar-machine-dot"', 'topbar-machine-dot on"']);
  pin("negative: на главной доске ни кнопка, ни строка не говорят «эта страница»", [p.button.attrs["aria-current"] ?? null, p.menu.innerHTML.includes("aria-current")], [null, false]);
}
{
  const p = page([LIST, { machines: [] }]);
  await p.press();
  p.press();
  pin("второе нажатие закрывает и ничего не спрашивает", [p.menu.hidden, p.button.attrs["aria-expanded"], p.asked.length], [true, "false", 1]);
  await p.press();
  pin("открыто снова — список читается заново: машина, подключённая минуту назад, в нём есть", [p.asked.length, p.menu.innerHTML.includes(">headerMachinesNone<"), p.menu.innerHTML.includes("<a ")], [2, true, false]);
}
{
  const p = page([{ machines: [] }]);
  await p.press();
  pin("машин нет — так и сказано, ссылок нет", [p.menu.innerHTML.includes(">headerMachinesNone<"), p.menu.innerHTML.includes("<a ")], [true, false]);
}
{
  const p = page([() => Promise.reject(new Error("controller is down"))]);
  await p.press();
  pin("negative: отказ — сказано, что не прочитано и почему, а не «машин нет»", [p.menu.innerHTML.includes("headerMachinesFailed"), p.menu.innerHTML.includes("controller is down"), p.menu.innerHTML.includes("headerMachinesNone")], [true, true, false]);
}
{
  const p = page([{ ok: true }]);
  await p.press();
  pin("negative: ответ без списка — тоже «не прочитано», а не «машин нет»", [p.menu.innerHTML.includes('headerMachinesFailed'), p.menu.innerHTML.includes("headerMachinesNone")], [true, false]);
}
{
  const p = page([LIST]);
  await p.press();
  p.listeners.keydown({ key: "Enter" });
  const after = p.menu.hidden;
  p.listeners.keydown({ key: "Escape" });
  pin("Esc закрывает; negative: другая клавиша — нет", [after, p.menu.hidden, p.button.attrs["aria-expanded"]], [false, true, "false"]);
}
{
  const p = page([LIST]);
  await p.press();
  p.listeners.click({ target: p.menu });
  const inside = p.menu.hidden;
  p.listeners.click({ target: {} });
  pin("щелчок мимо закрывает, ловится на фазе захвата (маршрутизатор доски гасит всплытие); negative: щелчок внутри — нет", [inside, p.menu.hidden, p.capture.click], [false, true, true]);
}
{
  let first;
  const p = page([() => new Promise((ok) => { first = ok; }), { machines: [{ id: "new", name: "New", online: true }] }]);
  const older = p.press();
  p.press();
  await p.press();
  first(LIST);
  await older;
  pin("negative: старое чтение, пришедшее после нового, ничего не рисует", rows(p.menu.innerHTML).map((r) => r[1]), ["new"]);
}
{
  const p = page([LIST], { view: new BoardView({ pathname: "/machine", search: "?host=b" }) });
  await p.press();
  pin("на странице машины кнопка горит, её строка — «эта страница»; negative: другие строки — нет",
    [p.button.attrs["aria-current"], (p.menu.innerHTML.match(/<a [^>]*aria-current="page"/g) || []).length, /data-t-id="b" aria-current="page"/.test(p.menu.innerHTML)], ["page", 1, true]);
}
{
  const listened = [];
  const header = new HeaderMachines({ doc: { getElementById: () => null, addEventListener: (t) => listened.push(t) }, get: () => { throw new Error("asked"); }, words: (k) => k });
  pin("negative: страница без шапки — не привязан и не слушает", [header.bind(), listened], [false, []]);
}
if (failed.length) {
  console.log(`\nFAILED (${failed.length}):`);
  process.exit(1);
}
console.log(`js header machines OK: настоящий модуль в node, ${pins} пинов значениями`);
'''
node = find_node()
if not node:
    raise SystemExit('node required')
probe = ROOT / 'scripts' / '.probe_header_machines.tmp.mjs'
probe.write_text(PROBE)
try:
    harness = ROOT / 'scripts' / '_js_harness.mjs'
    result = subprocess.run(probe_args(node, harness, probe), cwd=ROOT,
                            env={**os.environ, 'JS_ROOT': str(ROOT / 'static/js'), 'JS_STUBS': 'utils'}, capture_output=True, text=True, timeout=120)
    print(result.stdout, end='')
    print(result.stderr, end='', file=sys.stderr)
finally:
    probe.unlink(missing_ok=True)
raise SystemExit(result.returncode)
