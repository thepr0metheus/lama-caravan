#!/usr/bin/env python3
"""Снимок static/js/card-rows.js — свёрнутая строка карточки и место, где она стоит.

Строка — не вторая карточка: все факты ей передаёт сама карточка (имя, чип
памяти, атрибуты ▶, ручку каната), здесь они только раскладываются в линию.
Пинится ЗНАЧЕНИЯМИ: что строка показывает в каждом состоянии, где у неё
ручка каната (ровно одна — у строки), что показано у агента (только
заданное), что стоит в обёртке в каждом режиме и из чего сделано окно, в
котором открывается карточка ячейки (с 2026-09-25 вместо всплытия).

Подписи берутся из static/js/i18n/en.js программно, а не по памяти.

Запуск: python3 scripts/test_js_card_rows.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const root = process.env.JS_ROOT;
const { CellRow, AgentRow, FoldSlot, CellWindow, CellEye, CellFilter } = await import(pathToFileURL(root + "/card-rows.js").href);
const en = (await import(pathToFileURL(root + "/i18n/en.js").href)).default;
const A = '<span class="topology-handle server-input" data-topology-llama-input="1" data-llama-port="22002"></span>';
const L = 'data-node-cell-launch="controller" data-node-cell-port="22002" data-node-cell-runner="llama-server"';
const S = 'data-node-cell-stop="controller" data-node-cell-port="22002"';
const C = '<span class="mbadge mbadge-vram-est">≈16.2G</span>';
const base = { key: "controller:22002", port: 22002, name: "gemma-4-31B-it", chip: C, anchor: A };
const facts = (html) => ({
  cls: (html.match(/^<div class="([^"]+)"/) || [])[1] || null,
  hook: [(html.match(/data-t="([^"]+)"/) || [])[1], (html.match(/data-t-id="([^"]+)"/) || [])[1]],
  anchors: (html.match(/data-topology-llama-input/g) || []).length,
  anchorFirst: html.indexOf("topology-handle") < html.indexOf("fr-port"),
  sw: (html.match(/<button type="button" class="fr-switch" role="switch" aria-checked="(true|false)" ([^>]*)><span class="fr-knob" aria-hidden="true"><\/span><\/button>/) || []).slice(1),
  name: (html.match(/<span class="fr-name">([^<]*)<\/span>/) || [])[1] ?? null,
  warn: html.includes("fr-warn"),
  tps: (html.match(/<span class="fr-tps" data-live-rowtps>([^<]*)<\/span>/) || [])[1] ?? null,
  chipLast: html.endsWith(C + "</div>"),
  port: html.includes('data-llama-port="22002"') && html.includes(">:22002<"),
});
const cell = {
  parked: facts(new CellRow({ ...base, state: "parked", launch: L, stop: S, why: "Start" }).html()),
  parkedNoLaunch: facts(new CellRow({ ...base, state: "parked", why: "Not stopped" }).html()),
  running: facts(new CellRow({ ...base, state: "running", launch: L, stop: S, why: "Stop", tps: "41.7 t/s", busy: true, cpu: true }).html()),
  runningNoStop: facts(new CellRow({ ...base, state: "running", launch: L, why: "Not running" }).html()),
  reserved: facts(new CellRow({ ...base, state: "reserved", name: "", launch: L, why: "Configure first" }).html()),
  whyEscaped: new CellRow({ ...base, state: "parked", why: '"><b>w' }).html(),
  unknownState: facts(new CellRow({ ...base, state: "weird" }).html()),
  warned: facts(new CellRow({ ...base, state: "parked", warn: true }).html()),
  noAnchor: facts(new CellRow({ ...base, state: "parked", anchor: "" }).html()),
  escaped: new CellRow({ ...base, name: '"><b>x', title: '"><i>t' }).html(),
  titleDefault: (new CellRow({ ...base, state: "running" }).html().match(/ title="([^"]*)">/) || [])[1],
  warnWords: new CellRow({ ...base, warn: true }).html().includes(`title="${en.cellRowWarnTitle}"`),
  reservedWords: en.topologyReservedCellLabel,
  shown: [new CellRow({ ...base, state: "reserved" }).shownName(), new CellRow({ ...base, state: "parked" }).shownName(),
          new CellRow({ ...base, state: "running", name: "" }).shownName()],
  engine: [facts(new CellRow({ ...base, state: "running", engine: "ollama", busy: true }).html()).cls,
           facts(new CellRow({ ...base, state: "parked", engine: "lmstudio" }).html()).cls,
           facts(new CellRow({ ...base, state: "parked", engine: 'x" onclick="y' }).html()).cls,
           facts(new CellRow({ ...base, state: "parked", engine: "Ollama" }).html()).cls],
  launcher: ["ollama", "lm-studio2", "", null, "Ollama", "a b", "9x", "x<"].map((x) => CellRow.launcher(x)),
};

const H = (role) => `<span class="topology-handle output ${role}" data-topology-route-handle="1" data-route-role="${role}"></span>`;
const ok = { cls: "route-confirmed-tag", glyph: "✓", tip: "taTitleConfirmedRoute" };
const q = { cls: "route-unverified-tag", glyph: "?", tip: "taTitleUnverifiedRoute" };
const hermes = new AgentRow({ key: "agent:c1:hermes", name: "hermes", kind: "manual", routes: [
  { role: "primary", port: "23001", address: "http://10.0.0.20:23001/v1", face: ok, model: "hemi-proxy", locked: true, waitSec: 1800, limit: 256000, anchor: H("primary") },
  { role: "fallback", port: "23002", face: q, anchor: H("fallback"), muted: true },  // an old field: ignored
] }).html();
const bare = new AgentRow({ key: "agent:c1:scribe", name: "scribe", kind: "manual", routes: [
  { role: "primary", port: "23101", face: ok, anchor: H("primary") }, null, { role: "fallback", port: "" },
] }).html();
const agent = {
  hook: [(hermes.match(/data-t="([^"]+)"/) || [])[1], (hermes.match(/data-t-id="([^"]+)"/) || [])[1]],
  routes: (hermes.match(/class="ar-route /g) || []).length,
  anchors: (hermes.match(/data-topology-route-handle/g) || []).length,
  fallbackMark: hermes.includes(">↪ :23002<"),
  primaryPort: hermes.includes(">:23001<") && hermes.includes('title="http://10.0.0.20:23001/v1"'),
  model: hermes.includes('<span class="ar-model">hemi-proxy 🔒</span>'),
  wait: hermes.includes(`<span class="ar-meta">${en.routeWaitLabel.replace("{sec}", "1800")}</span>`),
  limit: hermes.includes(`<span class="ar-meta">${en.routeCtxLimit.replace("{value}", "256000")}</span>`),
  faces: [hermes.includes(`<span class="route-confirmed-tag" title="${en.taTitleConfirmedRoute}">✓</span>`),
          hermes.includes(`<span class="route-unverified-tag" title="${en.taTitleUnverifiedRoute}">?</span>`)],
  noStateHook: !hermes.includes('data-t="route-state"'),
  muted: hermes.includes("muted"),
  kind: hermes.includes('<span class="ar-kind">manual</span>'),
  bareRoutes: (bare.match(/class="ar-route /g) || []).length,
  bareEmpty: [bare.includes("ar-model"), bare.includes("ar-meta"), bare.includes("—")],
  escaped: new AgentRow({ key: "k", name: '"><b>x', kind: "<i>", routes: [] }).html(),
  noFace: new AgentRow({ key: "k", name: "n", routes: [{ role: "primary", port: "1" }] }).html().includes('class="route-confirmed-tag"'),
};

const card = '<article class="node-server">card</article>';
const lineHtml = '<div class="fold-row cell-row parked">line</div>';
const slot = {
  line: new FoldSlot({ key: "controller:22002", lane: "cells", mode: "line", line: lineHtml, card }).html(),
  peek: new FoldSlot({ key: "controller:22002", lane: "cells", mode: "line", line: lineHtml, card, peek: true }).html(),
  open: new FoldSlot({ key: "controller:22002", lane: "cells", mode: "line", line: lineHtml, card, open: true }).html(),
  pinned: new FoldSlot({ key: "controller:22002", lane: "cells", mode: "pinned", line: lineHtml, card, peek: true, open: true }).html(),
  clients: new FoldSlot({ key: "agent:c:a", lane: "clients", mode: "line", line: lineHtml, card }).html(),
  clientsPinned: new FoldSlot({ key: "agent:c:a", lane: "clients", mode: "pinned", line: lineHtml, card }).html(),
  oddLane: new FoldSlot({ key: "k", lane: "nope", mode: "line" }).html(),
  oddMode: new FoldSlot({ key: "k", lane: "cells", mode: "full" }).html(),
  escaped: new FoldSlot({ key: '"><b>', lane: "cells", mode: "line" }).html(),
  pinWords: [en.foldPinTitle, en.foldUnpinTitle],
};
const win = new CellWindow({ key: "controller:22007", name: "gemma-4-12B-it", port: 22007, address: "10.0.0.5:22007", card }).html();
const windows = {
  full: win,
  noAddress: new CellWindow({ key: "k", name: "n", port: 1, card }).html(),
  escaped: new CellWindow({ key: '"><b>', name: "<i>x", port: '"1', address: "<u>", card }).html(),
  empty: new CellWindow({}).html(),
  engine: new CellWindow({ key: "h1:22031", name: "qwen3:8b", port: 22031, address: "10.0.0.5:22031", via: "127.0.0.1:11434",
                           viaTitle: 'to "Ollama"', engine: "ollama", card }).html(),
  engineOdd: new CellWindow({ key: "k", name: "n", port: 1, via: "<b>", engine: "a b", card }).html(),
  closeWord: en.close, cellWord: en.a11yCell,
};
const eyes = {
  off: new CellEye({ hostId: "controller" }).html(),
  on: new CellEye({ hostId: "controller", on: true, hidden: 16 }).html(),
  badCount: new CellEye({ hostId: "h", on: true, hidden: "x" }).html(),
  negative: new CellEye({ hostId: "h", on: true, hidden: -3 }).html(),
  escaped: new CellEye({ hostId: '"><b>' }).html(),
  words: [en.cellsHideIdleOff, en.cellsHideIdleOn],
};
const OPTS = [{ id: "", label: "All", count: 5, title: "every" }, { id: "caravan", label: "Caravan", count: 3, title: "only caravan" },
              { id: "ollama", label: "Ollama", count: 1, up: true, title: "only ollama" },
              { id: "lmstudio", label: "LM Studio", count: 1, up: false, title: "only lms" }];
const filters = {
  full: new CellFilter({ hostId: "h1", chosen: "ollama", options: OPTS }).html(),
  none: new CellFilter({ hostId: "h1" }).html(),
  odd: new CellFilter({ hostId: '"><b>', chosen: "", options: [{ id: 'a b', label: "<i>x", count: "7.9", up: "yes", title: '"t' }, { id: "", count: -2 }] }).html(),
  label: en.cellsFilterLabel,
  menu: new CellFilter({ hostId: "h1", options: [{ id: "", label: "All", count: 2 },
    { id: "ollama", label: "Ollama", count: 1, up: true, menu: true, open: true, menuTitle: 'Ollama: "x"' },
    { id: "lmstudio", label: "LM Studio", count: 1, menu: true, menuTitle: "LM Studio" },
    { id: "caravan", label: "Caravan", count: 1, menu: true, menuTitle: "c" },
    { id: "odd one", label: "Odd", count: 0, menu: true, menuTitle: "o" }],
    anchors: '<span class="topology-handle engine-input" data-output-id="eng:1"></span>' }).html(),
};
console.log(JSON.stringify({ cell, agent, slot, windows, eyes, filters }));
"""

node = find_node()
if node is None:
    print("js card-rows: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
    sys.exit(0)
probe = ROOT / "scripts" / ".probe_card_rows.tmp.mjs"
probe.write_text(PROBE, encoding="utf-8")
try:
    hook = (f"data:text/javascript,import {{ register }} from 'node:module'; "
            f"register('file://{ROOT}/scripts/_js_harness.mjs');")
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
           "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"}
    proc = subprocess.run([node, "--import", hook, str(probe)], capture_output=True, text=True,
                          cwd=ROOT, env=env, timeout=60)
finally:
    probe.unlink(missing_ok=True)
if proc.returncode != 0:
    print("js card-rows: FAILED — харнесс не отработал")
    print(proc.stderr.strip()[:900])
    sys.exit(1)
got = json.loads(proc.stdout.strip().splitlines()[-1])
c, a, s, w, e = got["cell"], got["agent"], got["slot"], got["windows"], got["eyes"]

print("строка ячейки:")
check(c["parked"]["cls"] == "fold-row cell-row parked", "стоящая — класс parked, без cpu и busy")
check(c["parked"]["hook"] == ["cell-row", "controller:22002"], "у строки свой хук cell-row с ключом ячейки")
check(c["parked"]["anchors"] == 1 and c["parked"]["anchorFirst"],
      "ручка каната ровно одна и стоит первой — канат найдёт её, как находил на карточке")
check(c["noAnchor"]["anchors"] == 0, "строка без переданной ручки своей не выдумывает")
check(c["parked"]["sw"] == ["false", 'data-node-cell-launch="controller" data-node-cell-port="22002" data-node-cell-runner="llama-server" '
                                     'data-t="cell-row-start" data-t-id="controller:22002" title="Start" aria-label="Start"'],
      "стоящая — тумблер выключен и несёт атрибуты ▶ карточки (тот же старт, то же подтверждение), хук cell-row-start; "
      "атрибуты ⏹ ей не нужны, даже если переданы")
check(c["running"]["sw"] == ["true", 'data-node-cell-stop="controller" data-node-cell-port="22002" '
                                      'data-t="cell-row-stop" data-t-id="controller:22002" title="Stop" aria-label="Stop"'],
      "работающая — тумблер включён и несёт атрибуты ⏹ карточки, хук cell-row-stop; атрибуты ▶ ей не нужны")
check(c["parkedNoLaunch"]["sw"] == ["false", 'disabled title="Not stopped" aria-label="Not stopped"'],
      "negative: запустить нельзя — тумблер выключен и недоступен, с причиной, а не кнопка, ведущая в отказ")
check(c["runningNoStop"]["sw"] == ["true", 'disabled title="Not running" aria-label="Not running"'],
      "negative: остановить нельзя — тумблер включён, недоступен, с причиной; атрибуты ▶ не подставлены вместо ⏹")
check(c["reserved"]["sw"] == ["false", 'data-node-cell-launch="controller" data-node-cell-port="22002" data-node-cell-runner="llama-server" '
                                       'data-t="cell-row-start" data-t-id="controller:22002" title="Configure first" aria-label="Configure first"'],
      "зарезервированная — выключен; запускать ли, решает переданное (у доски его не передают — см. снимок карточки)")
check('"><b>w' not in c["whyEscaped"] and "&quot;&gt;&lt;b&gt;w" in c["whyEscaped"], "причина экранируется")
check(c["running"]["cls"] == "fold-row cell-row running cpu busy", "работающая на CPU и генерирующая — классы running cpu busy")
check(c["engine"] == ["fold-row cell-row running engine-ollama busy", "fold-row cell-row parked engine-lmstudio",
                      "fold-row cell-row parked", "fold-row cell-row parked"],
      "ячейка в движке — класс engine-<раннер> (цвет запускающего); negative: слово, не годное в имя класса "
      "(кавычки, заглавные), класса не даёт")
check(c["launcher"] == ["ollama", "lm-studio2", "", "", "", "", "", ""],
      "launcher: только строчное слово из букв, цифр и дефиса, с буквы — иначе пусто")
check(c["running"]["tps"] == "41.7 t/s", "живая скорость лежит в span data-live-rowtps — его и подменяет опрос")
check(c["parked"]["tps"] == "", "без скорости span пуст, но есть: опросу есть куда писать")
check(c["reserved"]["name"] == c["reservedWords"] and c["reserved"]["cls"] == "fold-row cell-row reserved",
      "зарезервированная без модели — вместо имени слово «reserved» из en.js")
check(c["unknownState"]["cls"] == "fold-row cell-row parked", "неизвестное состояние — как стоящая, а не пустой класс")
check(c["warned"]["warn"] and not c["parked"]["warn"], "⚠ только когда карточке есть что показать (устаревший исходник, модель, диск)")
check(c["warnWords"], "подсказка ⚠ — из en.js: cellRowWarnTitle")
check(c["parked"]["chipLast"] and c["parked"]["port"], "чип карточки стоит последним как есть; порт и data-llama-port на месте")
check("<b>x" not in c["escaped"] and "&lt;b&gt;x" in c["escaped"] and "<i>t" not in c["escaped"],
      "имя и подсказка экранируются")
check(c["titleDefault"] == "gemma-4-31B-it", "без переданной подсказки подсказка — имя")
check(c["shown"] == [c["reservedWords"], "gemma-4-31B-it", ""],
      "показанное имя — одно правило для строки и окна: у зарезервированной слово из en.js, у прочих имя как есть, пустое пустым")

print("строка агента:")
check(a["hook"] == ["agent-row", "agent:c1:hermes"], "у строки агента свой хук agent-row с ключом агента")
check(a["routes"] == 2 and a["anchors"] == 2, "две ветки — две строки маршрута и ровно две ручки каната")
check(a["primaryPort"] and a["fallbackMark"], "основной — «:23001» с полным адресом в подсказке; запасной — «↪ :23002»")
check(a["model"], "заданная модель с закрытым замком — «hemi-proxy 🔒»")
check(a["wait"] and a["limit"], "таймаут и лимит — теми же словами, что чипы карточки (routeWaitLabel, routeCtxLimit)")
check(a["faces"] == [True, True], "значки ✓ и ? — те же лица, что у карточки, с подсказками из en.js")
check(a["noStateHook"], "хука route-state у строки нет — он один, у карточки")
check(not a["muted"], "negative: «приглушённого» маршрута больше нет — это было слово агента через скаута; "
      "старое поле muted на входе ничего не рисует")
check(a["kind"], "вид агента («manual») виден и в свёрнутом")
check(a["bareRoutes"] == 1, "несуществующий маршрут и маршрут без порта не рисуются вовсе")
check(a["bareEmpty"] == [False, False, False],
      "незаданного нет: ни пустой модели, ни прочерков — отсутствие не рисуется нормой")
check("<b>x" not in a["escaped"] and "&lt;i&gt;" in a["escaped"], "имя и вид агента экранируются")
check(a["noFace"], "маршрут без переданного лица — ✓ по умолчанию, как у карточки")

print("обёртка (FoldSlot):")
check(s["line"].startswith('<div class="fold-slot cells-fold" data-fold-key="controller:22002" data-fold-lane="cells" data-fold-mode="line">'),
      "свёрнутая — место с ключом, лентой и режимом line: лента нужна FoldPeek, чтобы знать, как открывать")
check('<div class="fold-row cell-row parked">line</div><article class="node-server">card</article>' in s["line"],
      "в свёрнутом месте — строка, за ней карточка (у ячейки — в окне CellWindow)")
check('data-t="fold-pin"' not in s["line"] and "📌" not in s["line"],
      "negative: у ячейки 📌 нет — её карточка открывается окном, закреплять на месте нечего")
check(' peek"' in s["peek"] and ' peek"' not in s["line"], "всплывшая — класс peek, только если попросили")
check(s["open"].startswith('<div class="fold-slot cells-fold open"') and ' open"' not in s["line"],
      "открытое окно — класс open, только если попросили")
check(s["pinned"].startswith('<div class="fold-slot cells-fold" data-fold-key="controller:22002" data-fold-lane="cells" data-fold-mode="pinned">'),
      "закреплённая — режим pinned, и ни peek, ни open ей не ставятся даже по просьбе")
check("line</div>" not in s["pinned"] and "card</article>" in s["pinned"] and "▴" not in s["pinned"],
      "у закреплённой строки нет — только карточка; у ячейки и ▴ нет")
check('data-t="fold-pin"' in s["clients"] and "📌" in s["clients"] and f'title="{s["pinWords"][0]}"' in s["clients"],
      "у свёрнутого агента — 📌 «оставить открытой» (foldPinTitle)")
check('data-t="fold-unpin"' in s["clientsPinned"] and "▴" in s["clientsPinned"] and f'title="{s["pinWords"][1]}"' in s["clientsPinned"],
      "у закреплённого агента — ▴ «свернуть обратно» (foldUnpinTitle)")
check('class="fold-slot clients-fold" data-fold-key="agent:c:a" data-fold-lane="clients"' in s["clients"],
      "лента клиентов — свой класс места и своя лента")
check('class="fold-slot cells-fold"' in s["oddLane"] and 'data-fold-mode="line"' in s["oddMode"],
      "неизвестная лента — ячейки, неизвестный режим — line: без пустых классов")
check('"><b>' not in s["escaped"] and "&quot;&gt;&lt;b&gt;" in s["escaped"], "ключ экранируется")

print("окно ячейки (CellWindow):")
check(w["full"].startswith('<div class="cell-window-backdrop" data-cell-window-close="1" aria-hidden="true"></div>'),
      "первым — затемнение доски; клик по нему закрывает окно")
check(f'<div class="cell-window" role="dialog" aria-modal="true" aria-label="{w["cellWord"]} :22007 gemma-4-12B-it" '
      'data-t="cell-window" data-t-id="controller:22007">' in w["full"],
      "окно — диалог с именем «Cell :порт имя» (a11yCell из en.js) и своим хуком")
check('<strong class="cwh-name">gemma-4-12B-it</strong><span class="cwh-port">:22007</span><span class="cwh-addr">10.0.0.5:22007</span>' in w["full"],
      "заголовок: имя, :порт, адрес машины")
check(f'data-t="cell-window-close" data-t-id="controller:22007" title="{w["closeWord"]}" aria-label="{w["closeWord"]}">✕</button>' in w["full"],
      "✕ со словом close из en.js и своим хуком")
check(w["full"].endswith('</div><article class="node-server">card</article></div>'),
      "под заголовком — сама карточка, как есть")
check("cwh-addr" not in w["noAddress"], "negative: адрес не передан — его нет, а не пустой span")
check("<i>x" not in w["escaped"] and "&lt;i&gt;x" in w["escaped"] and "<u>" not in w["escaped"] and '"><b>' not in w["escaped"],
      "имя, адрес, ключ и порт экранируются")
check('aria-label="Cell :"' in w["empty"] or 'aria-label="' + w["cellWord"] + ' :"' in w["empty"],
      "пустое окно не падает — подпись без имени, как есть")
check('<div class="cell-window engine-ollama" role="dialog"' in w["engine"]
      and '<span class="cwh-addr">10.0.0.5:22031</span><span class="cwh-via" data-t="cell-window-via" '
          'title="to &quot;Ollama&quot;">→ 127.0.0.1:11434</span>' in w["engine"],
      "окно ячейки в движке — в цвет запускающего; после адреса машины — куда идут запросы (127.0.0.1 движка), "
      "подсказка экранирована")
check("cwh-via" not in w["full"] and '<div class="cell-window" role="dialog"' in w["full"],
      "negative: ячейка каравана — ни строки движка, ни класса")
check('<div class="cell-window" role="dialog"' in w["engineOdd"] and "→ &lt;b&gt;" in w["engineOdd"],
      "negative: слово, не годное в имя класса, класса не даёт; адрес движка экранирован")

print("чипы машины (CellFilter):")
fl = got["filters"]
check(fl["full"].startswith(f'<div class="node-cell-filter" role="group" aria-label="{fl["label"]}">'),
      "группа чипов подписана словами из en.js")
check('<button type="button" class="ncf-chip" data-cell-filter="h1" data-cell-filter-id="" data-t="node-cell-filter" '
      'data-t-id="h1:all" aria-pressed="false" title="every">All<span class="ncf-count">5</span></button>' in fl["full"],
      "«все» — пустой id, хук h1:all, счётчик; без точки и без цвета движка")
check('<button type="button" class="ncf-chip engine-ollama" data-cell-filter="h1" data-cell-filter-id="ollama" '
      'data-t="node-cell-filter" data-t-id="h1:ollama" aria-pressed="true" title="only ollama">'
      '<span class="ncf-dot up" aria-hidden="true"></span>Ollama<span class="ncf-count">1</span></button>' in fl["full"],
      "чип движка — в его цвет, нажат выбранный, точка «работает», счётчик")
check('class="ncf-chip" data-cell-filter="h1" data-cell-filter-id="caravan"' in fl["full"]
      and '<span class="ncf-dot" aria-hidden="true"></span>LM Studio' in fl["full"],
      "negative: у каравана нет цвета движка; у стоящего движка точка без «up»")
check(fl["full"].count('aria-pressed="true"') == 1, "нажат ровно один чип")
check(fl["none"] == "", "negative: выбирать не из чего — чипов нет вовсе, а не один «все»")
odd = fl["odd"]
check('<b>' not in odd and "&lt;i&gt;x" in odd and 'title="&quot;t"' in odd and 'data-t-id="&quot;&gt;&lt;b&gt;:a b"' in odd,
      "машина, подпись и подсказка экранированы")
check('class="ncf-chip" data-cell-filter' in odd and "engine-a b" not in odd and "ncf-dot" not in odd,
      "negative: слово, не годное в имя класса, цвета не даёт; «up» не булево — точки нет, а не догадка")
check('<span class="ncf-count">7</span>' in odd and '<span class="ncf-count">0</span>' in odd,
      "boundary: счётчик — целое неотрицательное (7.9 → 7, −2 → 0)")
check(odd.count('aria-pressed="true"') == 1 and 'data-t-id="&quot;&gt;&lt;b&gt;:all" aria-pressed="true"' in odd,
      "без выбора нажат «все»")

mn = fl["menu"]
check('<span class="ncf-group"><button type="button" class="ncf-chip engine-ollama" data-cell-filter="h1" data-cell-filter-id="ollama"' in mn
      and '<button type="button" class="ncf-menu engine-ollama" data-engine-menu="h1:ollama" data-t="node-engine-menu" '
          'data-t-id="h1:ollama" aria-expanded="true" title="Ollama: &quot;x&quot;" aria-label="Ollama: &quot;x&quot;">▴</button></span>' in mn,
      "у чипа движка — ▾ в одной группе с ним, в его цвет; открыт — нажат и смотрит вверх; подсказка экранирована")
check('data-engine-menu="h1:lmstudio" data-t="node-engine-menu" data-t-id="h1:lmstudio" aria-expanded="false" '
      'title="LM Studio" aria-label="LM Studio">▾</button>' in mn,
      "закрытый ▾ — aria-expanded false и стрелка вниз")
check('data-engine-menu="h1:caravan"' not in mn and "odd one" not in mn.split("ncf-menu")[0] and 'data-engine-menu="h1:odd' not in mn,
      "negative: у каравана и у слова, не годного в класс, ▾ нет — меню только у движка")
check(mn.startswith('<div class="node-cell-filter" role="group" aria-label="' + fl["label"] + '">'
                    '<span class="topology-handle engine-input" data-output-id="eng:1"></span><button'),
      "якоря выходов — первыми в строке чипов, у её края")
check('ncf-group' not in fl["full"] and "data-engine-menu" not in fl["full"],
      "negative: без menu у варианта ▾ не рисуется — чип как был")

print("глаз машины (CellEye):")
off_words, on_words = e["words"]
check(e["off"].startswith(f'<button type="button" class="node-eye" data-cell-eye="controller" data-t="node-hide-idle" '
                          f'data-t-id="controller" aria-pressed="false" title="{off_words}" aria-label="{off_words}">'),
      "выключен — не нажат, хук node-hide-idle с id машины, слова cellsHideIdleOff из en.js")
check("node-eye-count" not in e["off"] and "M2.5 13.5" not in e["off"], "выключен — без счётчика, глаз открыт (без черты)")
check(f'aria-pressed="true" title="{on_words.replace("{count}", "16")}"' in e["on"]
      and '<span class="node-eye-count">16</span></button>' in e["on"] and "M2.5 13.5" in e["on"],
      "включён — нажат, говорит и показывает, сколько скрыто (16), глаз перечёркнут: скрытое названо вслух")
check('<span class="node-eye-count">0</span>' in e["badCount"] and '<span class="node-eye-count">0</span>' in e["negative"],
      "negative: мусор и минус в счётчике — 0, а не NaN и не минус")
check('"><b>' not in e["escaped"] and "&quot;&gt;&lt;b&gt;" in e["escaped"], "id машины экранируется")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m_ in _fail:
        print("  - " + m_)
    sys.exit(1)
print("js card-rows OK: строка ячейки, строка агента, место свёрнутой карточки — значениями")
