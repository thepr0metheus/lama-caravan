#!/usr/bin/env python3
"""Value snapshot: the caravan's parts (static/js/ui-parts.js), step 0 of the screens' redesign.

Every screen draws its buttons, switches, choices, badges, status bands, rows, meters, lanes, tabs, addresses and window
frames through these classes, so their markup and accessibility are pinned here by value: the classes each kind wears, the
attributes a reader and a test find them by, the words escaped, and the refusals — a kind the part does not know, an icon
with no label, a part with no words. A meter with no known total draws no bar (an empty bar would read as a free card),
and its segments never add up past the whole. A lane of the memory map (variant В) draws by the same shares: a block
carries its words only while it is wide enough, is a button only when it chooses something, and says which one is chosen.

Run: python3 scripts/test_js_ui_parts.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _node import find_node, node_search_paths, probe_args  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const P = await import(pathToFileURL(process.env.JS_ROOT + "/ui-parts.js").href);
const out = {};
// No refusal is said in words, so a pin that wanted one reads FAIL rather than crashing on a null.
const err = (fn) => { try { fn(); return "(no refusal)"; } catch (e) { return String(e.message); } };

out.button = {
  plain: new P.Button({ text: "Open all settings…" }).html(),
  main: new P.Button({ kind: "main", text: "Add model", icon: "plus", attrs: 'data-x="1"' }).html(),
  halt: new P.Button({ kind: "halt", text: "Stop" }).html(),
  icon: new P.Button({ kind: "icon", icon: "more", label: "More actions" }).html(),
  off: new P.Button({ text: "Delete <all>", disabled: true, title: "only a stopped \"cell\"" }).html(),
  quiet: new P.Button({ kind: "quiet", text: "Log" }).html(),
  danger: new P.Button({ kind: "danger", text: "Delete…" }).html(),
  noKind: err(() => new P.Button({ kind: "ghost", text: "x" })),
  noLabel: err(() => new P.Button({ kind: "icon", icon: "more" })),
  noText: err(() => new P.Button({ kind: "plain" }))
};
out.switch = {
  off: new P.Switch({ label: "Cell :22001" }).html(),
  busy: new P.Switch({ label: "Cell :22002", on: true, busy: true, title: "Starting…", attrs: "data-s", disabled: true }).html(),
  noLabel: err(() => new P.Switch({}))
};
out.seg = new P.Seg({ label: "State", options: [{ text: "All", count: 28, on: true, attrs: "data-a" }, { text: "Running", count: 0 }, { text: "<b>" }] }).html();
out.segNoLabel = err(() => new P.Seg({ options: [] }));
out.pill = [new P.Pill({ text: "Chat", count: 15, on: true }).html(), new P.Pill({ text: "Voice" }).html(), err(() => new P.Pill({}))];
out.badge = [new P.Badge({ text: "autostart" }).html(), new P.Badge({ tone: "good", text: "on", title: "a \"b\"" }).html(),
             err(() => new P.Badge({ tone: "green", text: "x" })), err(() => new P.Badge({ tone: "bad" }))];
out.band = {
  idle: new P.Band({ title: "Stopped", sub: "the cards are free" }).html(),
  good: new P.Band({ tone: "good", title: "Running <1>", sub: '<span data-live>6.1 t/s</span>', action: "<button>Stop</button>", attrs: 'data-t="b"' }).html(),
  bare: new P.Band({ tone: "bad", title: "Failed" }).html(),
  noTone: err(() => new P.Band({ tone: "red", title: "x" })),
  noTitle: err(() => new P.Band({ tone: "good" }))
};
out.bandInline = new P.Band({ tone: "good", title: "Cells running: 1 of 28", inline: true, attrs: 'data-t="h"' }).html();
const lane = (o) => new P.Lane(Object.assign({ label: "GPU 1" }, o));
out.lane = {
  html: lane({ side: "RTX 5090 · 31.8 GB", free: "9.1 GB free", total: 32,
               blocks: [{ value: 1, kind: "other", name: "Xorg", figure: "1.0 GB", title: "Xorg · 1.0 GB" },
                        { value: 16, series: 2, name: ":22020 Hermes", figure: "16.0 GB", title: ":22020 Hermes — click to choose", pick: 'data-machine-pick="22020"', on: true },
                        { value: 8, series: 3, name: ":22007 gemma", figure: "8.0 GB", title: "t", pick: 'data-machine-pick="22007"' }] }).html(),
  narrow: lane({ total: 100, blocks: [{ value: 11.99, series: 1, name: "n", figure: "f", title: "t", pick: "data-p" },
                                      { value: 12, kind: "estimate", name: "would go", figure: "≈9.0 GB" }] }).html(),
  clamp: lane({ total: 10, blocks: [{ value: 8, name: "a" }, { value: 8, series: 2, name: "b" }, { value: 1, name: "c" }] }).html(),
  noBar: lane({ total: null, foot: "the scout does not report this card's memory", blocks: [{ value: 5 }] }).html(),
  bare: lane({}).html(),
  // On a rack: one thin row, its bar's share of the row, its blocks' figures by that share, and the line that sews a cell's pieces together.
  rack: lane({ side: "RTX 3090", free: "6.2 free", total: 100, rack: { bar: 75, slots: 2 },
               blocks: [{ value: 15, series: 2, name: ":1 small", figure: "15 GB", short: "15", title: "t", pick: "data-a", owner: "1" }, { value: 17, series: 3, name: ":2 mid", figure: "17 GB", short: "17", title: "u", pick: "data-b", owner: "2" },
                        { value: 30, series: 4, name: ":3 wide", figure: "30 GB", short: "30", title: "w", pick: "data-c", owner: "3" },
                        { value: 10, kind: "other", name: "Xorg", short: "Xorg", figure: "20", title: "v" }, { value: 22, kind: "other", name: "the system", short: "system", figure: "20", title: "v" },
                        { value: 6, kind: "estimate", name: "would go", figure: "≈6 GB", short: "≈6", owner: "4" }],
               links: [{ slot: 0, up: false, down: true, here: true, from: 69, owner: "3", shown: true, series: 3 }, { slot: 1, up: true, down: true, here: false, from: 0, owner: "4", kind: "estimate" }] }).html(),
  metrics: lane({ total: 10, rack: { bar: 50, slots: 0 }, metrics: [
    { word: "34%", cls: "is-load", attrs: 'data-a="1"', valAttrs: 'data-v="1"', sparkAttrs: 'data-s="1"' }, {} ] }).html(),
  heads: P.Lane.heads(["LOAD", "<M>"], 2),
  pic: [lane({ pic: "<i>p</i>" }).html(), lane({ pic: "<i>p</i>", total: 1, rack: { bar: 50, slots: 0 } }).html()],
  rackBlind:lane({ total: null, foot: "no size", rack: { bar: 100, slots: 1 }, links: [{ slot: 0, up: true, down: true, here: true, from: 0, series: 2 }] }).html(),
  linkBad: err(() => lane({ total: 1, rack: {}, links: [{ slot: 0, kind: "ghost" }] }).html()),
  badSeries: err(() => lane({ total: 1, blocks: [{ value: 1, series: 9 }] }).html()),
  badKind: err(() => lane({ total: 1, blocks: [{ value: 1, kind: "ghost" }] }).html()),
  noLabel: err(() => new P.Lane({}))
};
// The list beside a rack: each holder once, a cell's row a button that chooses it, tied to its blocks by its owner.
out.legend = {
  rows: new P.RackLegend({ empty: "none", rows: [
    { name: "new <one>", figure: "≈49.9 GB", where: "GPU 0–5 + RAM", owner: "9", title: "t", kind: "estimate", pick: "data-p" },
    { name: "Hermes", figure: "64.0 GB", where: "GPU 1–4", owner: "8", title: "u", series: 3, on: true, pick: "data-q" },
    { name: "Xorg", figure: "1.0 GB", where: "GPU 0", title: "v", kind: "other", attrs: "data-r" }] }).html(),
  empty: new P.RackLegend({ empty: "Nothing <holds>", heads: ["GB", "t/s"] }).html(),
  headed: new P.RackLegend({ heads: ["GB", "t/s"], rows: [{ name: "n", figure: "1.0", where: "RAM", speed: "38", owner: "9", series: 2, pick: "data-p" }] }).html(),
  bad: err(() => new P.RackLegend({ rows: [{ name: "n", series: 9 }] }).html()),
};

out.cut = [P.Meter.cut(10, [{ value: 4 }, { value: 0 }, { value: 8 }]).map((c) => c.width), P.Meter.cut(0, [{ value: 1 }]), P.Meter.cut("x", [])];
out.row = {
  open: new P.Row({ state: "<i>s</i>", title: "Hermes-4-70B", facts: ":22020 · llama.cpp", value: "≈ 39,6 ГБ", note: "part goes to RAM",
                    tail: "<em>t</em>", live: true, open: 'data-open="22020"', label: "Open the cell", attrs: 'data-t="r"', cols: "48px 1fr" }).html(),
  plain: new P.Row({ title: "large-v3-turbo", note: "not measured" }).html(),
  warn: new P.Row({ title: "x", note: "will not fit", noteTone: "busy" }).html(),
  noNote: err(() => new P.Row({ title: "x", noteTone: "warn" })),
  noLabel: err(() => new P.Row({ title: "x", open: "data-o" })),
  noTitle: err(() => new P.Row({}))
};
const meter = (o) => new P.Meter(Object.assign({ label: "GPU 0" }, o));
out.meter = {
  parts: meter({ value: "12,0", unit: "of 24,0 GB", total: 24, side: "51 °C", foot: "held by :22020",
                 parts: [{ value: 6, series: 1, title: ":22020" }, { value: 3, series: 2 }, { value: 1.2, kind: "other" }, { value: 2.4, kind: "estimate", title: "would go" }] }).segments(),
  clamp: meter({ total: 10, parts: [{ value: 6 }, { value: 6, series: 3 }, { value: 2 }] }).segments(),
  skip: meter({ total: 10, parts: [{ value: 0 }, { value: -2 }, { value: "x" }, { value: 5 }] }).segments(),
  unknown: meter({ total: null, parts: [{ value: 5 }] }).segments(),
  zero: meter({ total: 0, parts: [{ value: 5 }] }).segments(),
  html: meter({ value: "12,0", unit: "of 24,0 GB", total: 24, parts: [{ value: 6, title: ":22020" }] }).html(),
  noBar: meter({ value: "—", foot: "the scout does not report it", total: null }).html(),
  bare: meter({ tile: false }).html(),
  badSeries: err(() => meter({ total: 1, parts: [{ value: 1, series: 7 }] }).segments()),
  badKind: err(() => meter({ total: 1, parts: [{ value: 1, kind: "ghost" }] }).segments()),
  noLabel: err(() => new P.Meter({}))
};
out.tabs = [new P.Tabs({ label: "Machine", cls: "ui-win-tabs", tabs: [{ text: "Cells", count: 28, on: true, attrs: 'data-tab="cells"' }, { text: "Disk", count: "" }] }).html(),
            err(() => new P.Tabs({ tabs: [] }))];
out.addr = [new P.Addr({ text: "10.0.0.5:22020", label: "Copy the address", attrs: 'data-copy="1"' }).html(), err(() => new P.Addr({}))];
out.frame = {
  full: new P.Frame({ title: "Hermes <4>", facts: "chat · llama.cpp", addr: "<a1>", tools: "<b1>", band: "<band>", tabs: "<tabs>", body: "<body>", foot: "", label: "Cell window", attrs: 'data-t="w"' }).html(),
  noFoot: new P.Frame({ title: "Machine", tag: "div" }).html(),
  noTag: err(() => new P.Frame({ title: "x", tag: "aside" })),
  noTitle: err(() => new P.Frame({}))
};
out.icon = [P.Icon.svg("close", 12), err(() => P.Icon.svg("gear"))];
out.menu = {
  full: new P.Menu({ label: "Machine <actions>", attrs: 'data-t="m"', items: [{ text: "Reboot…", attrs: 'data-reboot-host="box"', title: 'a "b"' }, "-",
                                                                 { text: "Power off…", danger: true, disabled: true }] }).html(),
  empty: new P.Menu({ label: "x" }).html(),
  noLabel: err(() => new P.Menu({ items: [] })),
  noWords: err(() => new P.Menu({ label: "x", items: [{ attrs: "data-x" }] })),
};
out.page = {
  html: new P.Frame({ kind: "page", tag: "div", title: "Box <A>", facts: "host", band: "<band>", body: "<map>" }).html(),
  noKind: err(() => new P.Frame({ kind: "sheet", title: "x" })),
};
// Every word a part writes, hostile: each must come out escaped, in every slot.
const H = '<x&"y">';
out.escaped = {
  seg: new P.Seg({ label: H, options: [{ text: H, count: H }] }).html(),
  pill: new P.Pill({ text: H, count: H }).html(),
  badge: new P.Badge({ text: H, title: H }).html(),
  row: new P.Row({ title: H, facts: H, value: H, note: H, open: "data-o", label: H }).html(),
  meter: new P.Meter({ label: H, side: H, value: H, unit: H, foot: H, total: 10, parts: [{ value: 1, title: H }] }).html(),
  tabs: new P.Tabs({ label: H, tabs: [{ text: H, count: H }] }).html(),
  addr: new P.Addr({ text: H, label: H }).html(),
  frame: new P.Frame({ title: H, facts: H, label: H }).html(),
  lane: new P.Lane({ label: H, side: H, free: H, foot: H, total: 10, blocks: [{ value: 5, name: H, figure: H, title: H, pick: "data-p" }] }).html()
};
console.log(JSON.stringify(out));
"""


def main():
    node = find_node()
    if node is None:
        print("js ui-parts: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
        return 0
    probe = ROOT / "scripts" / ".probe_ui_parts.tmp.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    try:
        env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin"}
        proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True,
                              text=True, cwd=ROOT, env=env, timeout=60)
    finally:
        probe.unlink(missing_ok=True)
    if proc.returncode != 0:
        print("js ui-parts: FAILED — харнесс не отработал")
        print(proc.stderr.strip()[:1500])
        return 1
    got = json.loads(proc.stdout.strip().splitlines()[-1])

    print("кнопка:")
    b = got["button"]
    check(b["plain"] == '<button type="button" class="ui-btn">Open all settings…</button>', "обычная — класс и слова")
    check(b["main"].startswith('<button type="button" class="ui-btn ui-btn--main" data-x="1"><svg width="14" height="14"')
          and b["main"].endswith('</svg>Add model</button>') and 'aria-hidden="true"' in b["main"],
          "главная — свой класс, атрибуты вызывающего, значок рядом со словами скрыт от чтеца")
    check(b["halt"] == '<button type="button" class="ui-btn ui-btn--main ui-btn--danger">Stop</button>', "«Остановить» полосы — главная и опасная разом")
    check(b["icon"].startswith('<button type="button" class="ui-btn ui-btn--icon" aria-label="More actions"><svg width="16"')
          and b["icon"].endswith("</svg></button>"), "значок без слов — с подписью для чтеца")
    check(b["off"] == '<button type="button" class="ui-btn" title="only a stopped &quot;cell&quot;" disabled>Delete &lt;all&gt;</button>',
          "закрытая — disabled и причина подсказкой; слова и подсказка экранированы")
    check('class="ui-btn ui-btn--quiet"' in b["quiet"] and 'class="ui-btn ui-btn--danger"' in b["danger"], "тихая и опасная — свои классы")
    check(b["noKind"].startswith('Button: no kind "ghost"') and b["noLabel"] == "Button: an icon alone needs a label"
          and b["noText"] == "Button: needs its words",
          "negative: незнакомый вид, значок без подписи и кнопка без слов — отказ, а не догадка")

    print("переключатель, выбор, фильтр:")
    s = got["switch"]
    check(s["off"] == '<button type="button" class="ui-switch" role="switch" aria-checked="false" aria-label="Cell :22001"></button>',
          "переключатель говорит своё состояние и чьё оно")
    check(s["busy"] == '<button type="button" class="ui-switch is-busy" role="switch" aria-checked="true" aria-label="Cell :22002" title="Starting…" data-s disabled></button>',
          "в пути — свой класс, подсказка, закрыт")
    check(s["noLabel"] == "Switch: needs a label", "negative: переключатель без подписи — отказ")
    check(got["seg"] == '<div class="ui-seg" role="group" aria-label="State">'
          '<button type="button" class="ui-seg-opt" aria-pressed="true" data-a>All <span class="ui-count">28</span></button>'
          '<button type="button" class="ui-seg-opt" aria-pressed="false">Running <span class="ui-count">0</span></button>'
          '<button type="button" class="ui-seg-opt" aria-pressed="false">&lt;b&gt;</button></div>',
          "выбор — группа с подписью, выбранный говорит aria-pressed, счёт 0 показан; negative: без счёта — без пустого места")
    check(got["segNoLabel"] == "Seg: needs a label", "negative: выбор без подписи — отказ")
    check(got["pill"][0] == '<button type="button" class="ui-pill" aria-pressed="true">Chat <span class="ui-count">15</span></button>'
          and got["pill"][1] == '<button type="button" class="ui-pill" aria-pressed="false">Voice</button>' and got["pill"][2] == "Pill: needs its words",
          "фильтр — вкл/выкл словами для чтеца; negative: без слов — отказ")

    print("метка и полоса:")
    bd = got["badge"]
    check(bd[0] == '<span class="ui-badge">autostart</span>' and bd[1] == '<span class="ui-badge ui-badge--good" title="a &quot;b&quot;">on</span>',
          "метка: тихая — без модификатора, тон — своим классом")
    check(bd[2].startswith('Badge: no kind "green"') and bd[3] == "Badge: needs its words", "negative: незнакомый тон и метка без слов — отказ")
    bn = got["band"]
    check(bn["idle"] == '<div class="ui-band" role="status"><span class="ui-band-dot" aria-hidden="true"></span><div class="ui-band-text">'
          '<strong class="ui-band-title">Stopped</strong><span class="ui-band-sub">the cards are free</span></div></div>',
          "полоса «стоит» — без модификатора, role=status, точка скрыта от чтеца")
    check(bn["good"].startswith('<div class="ui-band ui-band--good" role="status" data-t="b">')
          and "Running &lt;1&gt;" in bn["good"] and '<span class="ui-band-sub"><span data-live>6.1 t/s</span></span>' in bn["good"]
          and bn["good"].endswith("<button>Stop</button></div>"),
          "работает — тон классом, заголовок экранирован, вторая строка и кнопка — разметкой вызывающего")
    check('<span class="ui-band-sub">' not in bn["bare"] and 'ui-band--bad' in bn["bare"], "negative: без второй строки — без пустого места")
    check(bn["noTone"].startswith('Band: no kind "red"') and bn["noTitle"] == "Band: needs a title", "negative: незнакомый тон, полоса без заголовка — отказ")
    check(got["bandInline"] == '<div class="ui-band ui-band--good ui-band--inline" role="status" data-t="h"><span class="ui-band-dot" aria-hidden="true"></span>'
          '<div class="ui-band-text"><strong class="ui-band-title">Cells running: 1 of 28</strong></div></div>',
          "полоса в строке шапки (вариант В) — та же часть с тоном и role=status, без рамки: свой класс")

    print("строка:")
    r = got["row"]
    check(r["open"] == '<div class="ui-row ui-row--live" style="--ui-row-cols: 48px 1fr" data-t="r"><div class="ui-row-state"><i>s</i></div>'
          '<button type="button" class="ui-row-name" aria-label="Open the cell" data-open="22020"><span class="ui-row-title">Hermes-4-70B</span>'
          '<span class="ui-row-facts">:22020 · llama.cpp</span></button><div class="ui-row-figure"><span class="ui-row-value">≈ 39,6 ГБ</span>'
          '<span class="ui-row-note">part goes to RAM</span></div><div class="ui-row-tail"><em>t</em></div></div>',
          "строка: состояние, имя-кнопка с подписью, факты, цифра и примечание справа, хвост; работает — подкрашена; столбцы — своей переменной")
    check('<div class="ui-row-name"><span class="ui-row-title">large-v3-turbo</span></div>' in r["plain"]
          and '<span class="ui-row-note">not measured</span>' in r["plain"] and "ui-row--live" not in r["plain"] and "ui-row-facts" not in r["plain"],
          "имя, что ничего не открывает, — не кнопка; отсутствие сказано словами; negative: без фактов — без пустой строки")
    check('<span class="ui-row-note ui-row-note--busy">will not fit</span>' in r["warn"], "примечание-исключение — своим тоном")
    check(r["noNote"].startswith('Row note: no kind "warn"') and r["noLabel"] == "Row: a name that opens needs a label"
          and r["noTitle"] == "Row: needs a title", "negative: незнакомый тон примечания, имя-кнопка без подписи, строка без имени — отказ")

    print("шкала:")
    m = got["meter"]
    check(m["parts"] == [{"cls": "ui-meter-seg", "width": 25, "title": ":22020"}, {"cls": "ui-meter-seg ui-meter-seg--s2", "width": 12.5, "title": ""},
                         {"cls": "ui-meter-seg ui-meter-seg--other", "width": 5, "title": ""},
                         {"cls": "ui-meter-seg ui-meter-seg--estimate", "width": 10, "title": "would go"}],
          "доли — в процентах итога: цвет ячейки, штриховка чужих, пунктир оценки")
    check(m["clamp"] == [{"cls": "ui-meter-seg", "width": 60, "title": ""}, {"cls": "ui-meter-seg ui-meter-seg--s3", "width": 40, "title": ""}],
          "negative: доли не уходят за целое — последняя обрезана, лишняя не рисуется")
    check(m["skip"] == [{"cls": "ui-meter-seg", "width": 50, "title": ""}], "negative: нулевая, отрицательная и нечисловая доли не рисуются")
    check(m["unknown"] is None and m["zero"] is None, "negative: итог не известен — долей нет")
    check(m["html"] == '<div class="ui-meter ui-tile"><div class="ui-meter-head"><span class="ui-meter-label">GPU 0</span></div>'
          '<div class="ui-meter-figure"><span class="ui-meter-value">12,0</span><span class="ui-meter-unit">of 24,0 GB</span></div>'
          '<div class="ui-meter-bar" role="img" aria-label="GPU 0 12,0 of 24,0 GB"><span class="ui-meter-seg" style="width: 25%" title=":22020"></span></div></div>',
          "шкала: подпись, цифра, полоса с подписью для чтеца, доля с подсказкой")
    check("ui-meter-bar" not in m["noBar"] and '<span class="ui-meter-foot">the scout does not report it</span>' in m["noBar"],
          "negative: итог не известен — полосы нет вовсе (пустая читалась бы как свободная карта), причина — в подписи под ней")
    check(m["bare"] == '<div class="ui-meter"><div class="ui-meter-head"><span class="ui-meter-label">GPU 0</span></div></div>',
          "без плитки и без цифр — одна подпись, без пустых мест")
    check(m["badSeries"] == 'Meter part: no series "7" (1–6)' and m["badKind"].startswith('Meter part: no kind "ghost"')
          and m["noLabel"] == "Meter: needs a label", "negative: незнакомый цвет ряда, незнакомая доля, шкала без подписи — отказ")

    print("полоса карты памяти (вариант В):")
    ln = got["lane"]
    check(ln["html"] == '<div class="ui-lane"><div class="ui-lane-head"><span class="ui-lane-label">GPU 1</span>'
          '<span class="ui-lane-side">RTX 5090 · 31.8 GB</span><span class="ui-lane-free">9.1 GB free</span></div><div class="ui-lane-bar">'
          '<span class="ui-lane-blk ui-lane-blk--other" style="width: 3.13%" title="Xorg · 1.0 GB"></span>'
          '<button type="button" class="ui-lane-blk ui-lane-blk--s2 is-on" style="width: 50%" aria-pressed="true" aria-label=":22020 Hermes — click to choose"'
          ' title=":22020 Hermes — click to choose" data-machine-pick="22020"><strong>:22020 Hermes</strong><span>16.0 GB</span></button>'
          '<button type="button" class="ui-lane-blk ui-lane-blk--s3" style="width: 25%" aria-pressed="false" aria-label="t" title="t" data-machine-pick="22007">'
          '<strong>:22007 gemma</strong><span>8.0 GB</span></button></div></div>',
          "полоса: подпись, карта, свободно справа; блок ячейки — кнопка своего цвета с именем и цифрой внутри, выбранная — is-on и "
          "aria-pressed; чужой процесс — штриховкой и не кнопка; узкий (3%) — без слов, слова в подсказке")
    check('<button type="button" class="ui-lane-blk" style="width: 11.99%" aria-pressed="false" aria-label="t" title="t" data-p></button>' in ln["narrow"]
          and '<span class="ui-lane-blk ui-lane-blk--estimate" style="width: 12%"><strong>would go</strong><span>≈9.0 GB</span></span>' in ln["narrow"],
          "boundary: блок уже 12% слов не несёт — только подсказку; от 12% — несёт; оценка — пунктиром, не кнопка")
    check(ln["clamp"].count('class="ui-lane-blk') == 2 and 'style="width: 80%"' in ln["clamp"] and 'style="width: 20%"' in ln["clamp"]
          and "<strong>c</strong>" not in ln["clamp"], "negative: блоки не уходят за целое — второй обрезан, третий не нарисован")
    check("ui-lane-bar" not in ln["noBar"] and '<span class="ui-lane-foot">the scout does not report this card&#39;s memory</span>' in ln["noBar"],
          "negative: итог не известен — полосы нет вовсе (пустая читалась бы как свободная карта), причина — под подписью")
    check(ln["bare"] == '<div class="ui-lane"><div class="ui-lane-head"><span class="ui-lane-label">GPU 1</span></div></div>',
          "без карты, свободного и блоков — одна подпись, без пустых мест")
    print("полоса на стойке:")
    rk = ln["rack"]
    check(rk.startswith('<div class="ui-lane ui-lane--rack" style="--lane-bar: 75%; --lane-slots: 2"><div class="ui-lane-head"><span class="ui-lane-label">GPU 1</span>'
                        '<span class="ui-lane-side" title="RTX 3090">RTX 3090</span></div><span class="ui-lane-free">6.2 free</span><div class="ui-lane-line"><div class="ui-lane-bar">'),
          "на стойке полоса: имя с подсказкой, отдельно сколько свободно, отдельно брусок и его доля строки")
    check('style="width: 15%" aria-pressed="false" aria-label="t" title="t" data-lane-owner="1" data-a></button>' in rk,
          "boundary: блок уже 12% строки (15% бруска длиной 75%) не несёт ничего: скажет в подсказке и в списке")
    check('data-lane-owner="2" data-b><span>17</span></button>' in rk, "boundary: от 12% строки — только число")
    check('data-lane-owner="3" data-c><span>30 GB</span></button>' in rk, "boundary: от 22% строки — цифра с единицей")
    check("<strong>:1 small</strong>" not in rk and "<strong>:3 wide</strong>" not in rk, "negative: имени ячейки в блоке нет: оно в списке рядом")
    check('title="v"></span>' in rk and "<strong>system</strong>" in rk and "<strong>Xorg</strong>" not in rk and "<span>20</span>" not in rk,
          "чужой процесс несёт короткое слово от 16% строки, уже — ничего, и своей цифры в блоке не несёт")
    check('data-lane-owner="4"></span>' in rk and "<strong>would go</strong>" not in rk and "≈6" not in rk, "пунктир уже 12% строки: без цифры и без имени, только чей он")
    check('<i class="ui-lane-lead ui-lane-c ui-lane-c--s3 is-shown" data-lane-owner="3" style="--lane-slot: 0; --lane-from: 69"></i>' in rk and rk.count("ui-lane-lead") == 1,
          "отвод к линии — только там, где у ячейки здесь есть кусок, от начала свободной части бруска; выбранная помечена, чтобы её линия рисовалась")
    check('<div class="ui-lane-spine"><i class="ui-lane-link ui-lane-c ui-lane-c--s3 is-shown is-down is-here" data-lane-owner="3" style="--lane-slot: 0"></i>'
          '<i class="ui-lane-link ui-lane-c ui-lane-c--estimate is-up is-down" data-lane-owner="4" style="--lane-slot: 1"></i></div>' in rk,
          "линии: откуда пришла, куда идёт, есть ли здесь кусок, чья; пунктирная у того, что ещё не запущено")
    check('<div class="ui-lane-metrics"><span class="ui-lane-metric is-load" data-a="1"><span class="ui-lane-metric-val" data-v="1">34%</span><span class="ui-lane-metric-spark" data-s="1"></span></span><span class="ui-lane-metric"></span></div></div>' in ln["metrics"],
          "показатели в конце строки: значение и место для графика; negative: у столбца без показателя пустая ячейка, чтобы остальные стояли ровно")
    check("ui-lane-metrics" not in rk, "negative: показателей не дали: их места в строке нет")
    check(all('<div class="ui-lane-head"><i>p</i><span class="ui-lane-label">GPU 1</span>' in html for html in ln["pic"]) and '<div class="ui-lane-head"><span class="ui-lane-label">' in ln["bare"],
          "картинка, которую дал вызвавший, — перед подписью, в обеих раскладках; negative: не дали — её места нет")
    check(ln["heads"] == '<div class="ui-lane-heads" style="--lane-slots: 2"><div class="ui-lane-metrics"><span class="ui-lane-metric">LOAD</span><span class="ui-lane-metric">&lt;M&gt;</span></div></div>',
          "заголовки столбцов в той же сетке, слова экранированы")
    check("ui-lane-notes" not in rk and "ui-lane-note" not in rk, "negative: подписей у полосы нет: куча имён ушла в один список")
    check("ui-lane-bar" not in ln["rackBlind"] and "ui-lane-lead" not in ln["rackBlind"] and 'is-up is-down is-here' in ln["rackBlind"] and '<span class="ui-lane-foot">no size</span>' in ln["rackBlind"],
          "negative: размера нет — нет ни бруска, ни отвода, слова об этом есть, а линия мимо проходит")
    check(ln["linkBad"].startswith('Lane link part: no kind "ghost"'), "negative: незнакомый вид линии — отказ")
    lg = got["legend"]
    check('<div class="ui-legend"><button type="button" class="ui-legend-row ui-lane-c ui-lane-c--estimate" aria-pressed="false" title="t" data-lane-owner="9" data-p><span class="ui-lane-dot" aria-hidden="true"></span>'
          '<strong class="ui-legend-name">new &lt;one&gt;</strong><span class="ui-legend-figure">≈49.9 GB</span><span class="ui-legend-where">GPU 0–5 + RAM</span><span class="ui-legend-speed"></span></button>' in lg["rows"],
          "строка списка: точка её цвета, имя (экранировано), сколько в сумме, где; кнопка, связанная со своими кусками")
    check('class="ui-legend-row ui-lane-c ui-lane-c--s3 is-on" aria-pressed="true" title="u" data-lane-owner="8" data-q>' in lg["rows"], "выбранная ячейка помечена")
    check('<div class="ui-legend-row ui-lane-c ui-lane-c--other" title="v" data-r>' in lg["rows"] and lg["rows"].count("<button") == 2, "negative: чужой процесс — не кнопка и ни с чем не связан")
    check('<div class="ui-legend"><div class="ui-legend-row ui-legend-heads"><span></span><span></span><span class="ui-legend-figure">GB</span><span></span><span class="ui-legend-speed">t/s</span></div><button' in lg["headed"] and '<span class="ui-legend-speed">38</span>' in lg["headed"],
          "над списком единицы его столбцов, в строке скорость модели")
    check(lg["empty"] == '<div class="ui-legend"><p class="ui-legend-empty">Nothing &lt;holds&gt;</p></div>', "negative: никто ничего не держит: так и сказано, слова экранированы")
    check(lg["bad"] == 'Legend row part: no series "9" (1–6)', "negative: незнакомый цвет строки — отказ")
    check(ln["badSeries"] == 'Lane part: no series "9" (1–6)' and ln["badKind"].startswith('Lane part: no kind "ghost"')
          and ln["noLabel"] == "Lane: needs a label", "negative: незнакомый цвет, незнакомая доля, полоса без подписи — отказ")
    check(got["cut"] == [[40, 60], None, None], "одно правило долей для шкалы и полосы (Meter.cut): обрезка по целому; negative: итог 0 или не число — долей нет")

    print("вкладки, адрес, рамка, значки:")
    check(got["tabs"][0] == '<div class="ui-tabs ui-win-tabs" role="tablist" aria-label="Machine">'
          '<button type="button" role="tab" class="ui-tab" aria-selected="true" data-tab="cells">Cells<span class="ui-tab-count">28</span></button>'
          '<button type="button" role="tab" class="ui-tab" aria-selected="false">Disk</button></div>' and got["tabs"][1] == "Tabs: needs a label",
          "вкладки — список с подписью, выбранная говорит aria-selected, счёт — рядом; negative: без подписи — отказ")
    a = got["addr"]
    check(a[0].startswith('<button type="button" class="ui-addr" title="Copy the address" data-copy="1"><span>10.0.0.5:22020</span><svg width="12"')
          and a[1] == "Addr: needs the address", "адрес — кнопка, что копирует себя; negative: без адреса — отказ")
    f = got["frame"]
    check(f["full"] == '<section class="ui-win" aria-label="Cell window" data-t="w"><div class="ui-win-head"><div class="ui-win-id"><div class="ui-win-title-row">'
          '<strong class="ui-win-title">Hermes &lt;4&gt;</strong><span class="ui-win-facts">chat · llama.cpp</span></div><a1></div><b1></div>'
          '<div class="ui-win-band"><band></div><tabs><div class="ui-win-body"><body></div><div class="ui-win-foot"></div></section>',
          "рамка: паспорт, полоса, вкладки, тело и место подвала — пустое, пока не применять нечего")
    check(f["noFoot"] == '<div class="ui-win"><div class="ui-win-head"><div class="ui-win-id"><div class="ui-win-title-row"><strong class="ui-win-title">Machine</strong></div></div></div></div>',
          "negative: подвал не нужен (null) — места нет; без полосы, вкладок и тела — без пустых обёрток")
    check(f["noTag"].startswith('Frame tag: no kind "aside"') and f["noTitle"] == "Frame: needs a title", "negative: незнакомый тег и рамка без имени — отказ")
    check(got["icon"][0].startswith('<svg width="12" height="12" viewBox="0 0 16 16"') and 'aria-hidden="true"' in got["icon"][0]
          and got["icon"][1].startswith('Icon: no kind "gear"'), "значки — из одного набора, скрыты от чтеца; negative: незнакомый — отказ")

    print("меню и страница:")
    mn = got["menu"]
    check(mn["full"].startswith('<div class="ui-menu" data-t="m"><button type="button" class="ui-btn ui-btn--icon" aria-label="Machine &lt;actions&gt;" '
                                'data-ui-menu-toggle aria-haspopup="menu" aria-expanded="false">')
          and '<div class="ui-menu-list" role="menu" aria-label="Machine &lt;actions&gt;" hidden>' in mn["full"]
          and '<button type="button" role="menuitem" class="ui-menu-item" title="a &quot;b&quot;" data-reboot-host="box">Reboot…</button>' in mn["full"]
          and '<div class="ui-menu-sep" role="separator"></div>' in mn["full"]
          and '<button type="button" role="menuitem" class="ui-menu-item ui-menu-item--danger" disabled>Power off…</button>' in mn["full"],
          "меню: кнопка «⋯» с подписью для чтеца, закрытый список role=menu, пункт с атрибутами доски, черта, красный закрытый пункт")
    check(mn["empty"].endswith('<div class="ui-menu-list" role="menu" aria-label="x" hidden></div></div>'),
          "boundary: меню без пунктов — пустой список, а не исключение")
    check(mn["noLabel"] == "Menu: needs a label" and mn["noWords"] == "Menu item: needs its words",
          "negative: меню без подписи и пункт без слов — отказ")
    pg = got["page"]
    check(pg["html"] == '<div class="ui-win ui-win--page"><div class="ui-win-head"><div class="ui-win-id"><div class="ui-win-title-row">'
          '<h1 class="ui-win-title">Box &lt;A&gt;</h1><span class="ui-win-facts">host</span></div></div></div>'
          '<div class="ui-win-band"><band></div><div class="ui-win-body"><map></div></div>',
          "рамка-страница: тот же паспорт и полоса, имя — заголовок страницы h1, без подвала")
    check(pg["noKind"].startswith('Frame: no kind "sheet"'), "negative: незнакомый вид рамки — отказ")

    print("экранирование:")
    # Word slots per part: the escaped word must appear once per slot (the meter's bar label joins three of them), the raw one never.
    slots = {"seg": 3, "pill": 2, "badge": 2, "row": 5, "meter": 9, "tabs": 3, "addr": 2, "frame": 3, "lane": 8}
    for part, n in slots.items():
        html = got["escaped"][part]
        check("<x" not in html and html.count("&lt;x&amp;&quot;y&quot;&gt;") == n,
              f"{part}: каждое слово экранировано, мест — {n}; negative: сырого слова в разметке нет")

    print()
    if _fail:
        print(f"js ui-parts FAILED ({len(_fail)}):")
        for msg in _fail:
            print("  - " + msg.splitlines()[0])
        return 1
    print("js ui-parts OK: кнопка, переключатель, выбор, фильтр, метка, полоса, строка, шкала, вкладки, адрес, рамка — значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
