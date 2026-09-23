#!/usr/bin/env python3
"""Снимок static/js/card-rows.js — свёрнутая строка карточки и место, где она стоит.

Строка — не вторая карточка: все факты ей передаёт сама карточка (имя, чип
памяти, атрибуты ▶, ручку каната), здесь они только раскладываются в линию.
Пинится ЗНАЧЕНИЯМИ: что строка показывает в каждом состоянии, где у неё
ручка каната (ровно одна — у строки), что показано у агента (только
заданное) и что стоит в обёртке в каждом режиме.

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
const { CellRow, AgentRow, FoldSlot } = await import(pathToFileURL(root + "/card-rows.js").href);
const en = (await import(pathToFileURL(root + "/i18n/en.js").href)).default;
const A = '<span class="topology-handle server-input" data-topology-llama-input="1" data-llama-port="22002"></span>';
const L = 'data-node-cell-launch="controller" data-node-cell-port="22002" data-node-cell-runner="llama-server"';
const C = '<span class="mbadge mbadge-vram-est">≈16.2G</span>';
const base = { key: "controller:22002", port: 22002, name: "gemma-4-31B-it", chip: C, anchor: A };
const facts = (html) => ({
  cls: (html.match(/^<div class="([^"]+)"/) || [])[1] || null,
  hook: [(html.match(/data-t="([^"]+)"/) || [])[1], (html.match(/data-t-id="([^"]+)"/) || [])[1]],
  anchors: (html.match(/data-topology-llama-input/g) || []).length,
  anchorFirst: html.indexOf("topology-handle") < html.indexOf("fr-port"),
  play: /<button type="button" class="fr-play" data-node-cell-launch="controller" data-node-cell-port="22002" data-node-cell-runner="llama-server" data-t="cell-row-start" data-t-id="controller:22002"/.test(html),
  dot: html.includes('class="fr-dot"'),
  name: (html.match(/<span class="fr-name">([^<]*)<\/span>/) || [])[1] ?? null,
  warn: html.includes("fr-warn"),
  tps: (html.match(/<span class="fr-tps" data-live-rowtps>([^<]*)<\/span>/) || [])[1] ?? null,
  chipLast: html.endsWith(C + "</div>"),
  port: html.includes('data-llama-port="22002"') && html.includes(">:22002<"),
});
const cell = {
  parked: facts(new CellRow({ ...base, state: "parked", launch: L }).html()),
  parkedNoLaunch: facts(new CellRow({ ...base, state: "parked" }).html()),
  running: facts(new CellRow({ ...base, state: "running", launch: L, tps: "41.7 t/s", busy: true, cpu: true }).html()),
  reserved: facts(new CellRow({ ...base, state: "reserved", name: "" }).html()),
  unknownState: facts(new CellRow({ ...base, state: "weird" }).html()),
  warned: facts(new CellRow({ ...base, state: "parked", warn: true }).html()),
  noAnchor: facts(new CellRow({ ...base, state: "parked", anchor: "" }).html()),
  escaped: new CellRow({ ...base, name: '"><b>x', title: '"><i>t' }).html(),
  titleDefault: (new CellRow({ ...base, state: "running" }).html().match(/ title="([^"]*)">/) || [])[1],
  warnWords: new CellRow({ ...base, warn: true }).html().includes(`title="${en.cellRowWarnTitle}"`),
  startWords: new CellRow({ ...base, launch: L }).html().includes(`title="${en.nodeStartServer}"`),
  reservedWords: en.topologyReservedCellLabel,
};

const H = (role) => `<span class="topology-handle output ${role}" data-topology-route-handle="1" data-route-role="${role}"></span>`;
const ok = { cls: "route-confirmed-tag", glyph: "✓", tip: "taTitleConfirmedRoute" };
const q = { cls: "route-unverified-tag", glyph: "?", tip: "taTitleUnverifiedRoute" };
const hermes = new AgentRow({ key: "agent:c1:hermes", name: "hermes", kind: "manual", routes: [
  { role: "primary", port: "23001", address: "http://10.0.0.20:23001/v1", face: ok, model: "hemi-proxy", locked: true, waitSec: 1800, limit: 256000, anchor: H("primary") },
  { role: "fallback", port: "23002", face: q, anchor: H("fallback"), muted: true },
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
  muted: hermes.includes('class="ar-route fallback muted"'),
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
  pinned: new FoldSlot({ key: "controller:22002", lane: "cells", mode: "pinned", line: lineHtml, card, peek: true }).html(),
  clients: new FoldSlot({ key: "agent:c:a", lane: "clients", mode: "line", line: lineHtml, card }).html(),
  oddLane: new FoldSlot({ key: "k", lane: "nope", mode: "line" }).html(),
  oddMode: new FoldSlot({ key: "k", lane: "cells", mode: "full" }).html(),
  escaped: new FoldSlot({ key: '"><b>', lane: "cells", mode: "line" }).html(),
  pinWords: [en.foldPinTitle, en.foldUnpinTitle],
};
console.log(JSON.stringify({ cell, agent, slot }));
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
c, a, s = got["cell"], got["agent"], got["slot"]

print("строка ячейки:")
check(c["parked"]["cls"] == "fold-row cell-row parked", "стоящая — класс parked, без cpu и busy")
check(c["parked"]["hook"] == ["cell-row", "controller:22002"], "у строки свой хук cell-row с ключом ячейки")
check(c["parked"]["anchors"] == 1 and c["parked"]["anchorFirst"],
      "ручка каната ровно одна и стоит первой — канат найдёт её, как находил на карточке")
check(c["noAnchor"]["anchors"] == 0, "строка без переданной ручки своей не выдумывает")
check(c["parked"]["play"] and not c["parked"]["dot"],
      "стоящая с атрибутами запуска — ▶ несёт те же data-node-cell-* что и ▶ карточки, плюс свой хук cell-row-start")
check(not c["parkedNoLaunch"]["play"] and c["parkedNoLaunch"]["dot"],
      "стоящая, которую запустить нельзя, — точка вместо ▶: кнопка, ведущая в отказ, хуже никакой")
check(not c["running"]["play"] and c["running"]["dot"], "работающая — точка, ▶ нет даже при переданных атрибутах")
check(c["running"]["cls"] == "fold-row cell-row running cpu busy", "работающая на CPU и генерирующая — классы running cpu busy")
check(c["running"]["tps"] == "41.7 t/s", "живая скорость лежит в span data-live-rowtps — его и подменяет опрос")
check(c["parked"]["tps"] == "", "без скорости span пуст, но есть: опросу есть куда писать")
check(c["reserved"]["name"] == c["reservedWords"] and c["reserved"]["cls"] == "fold-row cell-row reserved",
      "зарезервированная без модели — вместо имени слово «reserved» из en.js")
check(c["unknownState"]["cls"] == "fold-row cell-row parked", "неизвестное состояние — как стоящая, а не пустой класс")
check(c["warned"]["warn"] and not c["parked"]["warn"], "⚠ только когда карточке есть что показать (устаревший исходник, модель, диск)")
check(c["warnWords"] and c["startWords"], "подсказки ⚠ и ▶ — из en.js: cellRowWarnTitle, nodeStartServer")
check(c["parked"]["chipLast"] and c["parked"]["port"], "чип карточки стоит последним как есть; порт и data-llama-port на месте")
check("<b>x" not in c["escaped"] and "&lt;b&gt;x" in c["escaped"] and "<i>t" not in c["escaped"],
      "имя и подсказка экранируются")
check(c["titleDefault"] == "gemma-4-31B-it", "без переданной подсказки подсказка — имя")

print("строка агента:")
check(a["hook"] == ["agent-row", "agent:c1:hermes"], "у строки агента свой хук agent-row с ключом агента")
check(a["routes"] == 2 and a["anchors"] == 2, "две ветки — две строки маршрута и ровно две ручки каната")
check(a["primaryPort"] and a["fallbackMark"], "основной — «:23001» с полным адресом в подсказке; запасной — «↪ :23002»")
check(a["model"], "заданная модель с закрытым замком — «hemi-proxy 🔒»")
check(a["wait"] and a["limit"], "таймаут и лимит — теми же словами, что чипы карточки (routeWaitLabel, routeCtxLimit)")
check(a["faces"] == [True, True], "значки ✓ и ? — те же лица, что у карточки, с подсказками из en.js")
check(a["noStateHook"], "хука route-state у строки нет — он один, у карточки")
check(a["muted"], "неиспользуемый маршрут приглушён")
check(a["kind"], "вид агента («manual») виден и в свёрнутом")
check(a["bareRoutes"] == 1, "несуществующий маршрут и маршрут без порта не рисуются вовсе")
check(a["bareEmpty"] == [False, False, False],
      "незаданного нет: ни пустой модели, ни прочерков — отсутствие не рисуется нормой")
check("<b>x" not in a["escaped"] and "&lt;i&gt;" in a["escaped"], "имя и вид агента экранируются")
check(a["noFace"], "маршрут без переданного лица — ✓ по умолчанию, как у карточки")

print("обёртка (FoldSlot):")
check(s["line"].startswith('<div class="fold-slot cells-fold" data-fold-key="controller:22002" data-fold-mode="line">'),
      "свёрнутая — место с ключом и режимом line")
check('<div class="fold-row cell-row parked">line</div><article class="node-server">card</article>' in s["line"],
      "в свёрнутом месте — строка, за ней карточка (всплывает при наведении)")
check('data-t="fold-pin"' in s["line"] and "📌" in s["line"] and f'title="{s["pinWords"][0]}"' in s["line"],
      "у свёрнутой — 📌 «оставить открытой» (foldPinTitle)")
check(' peek"' in s["peek"] and ' peek"' not in s["line"], "всплывшая — класс peek, только если попросили")
check("peek-enter" not in s["peek"],
      "разметка всплывшей никогда не несёт peek-enter: перерисовка рисует открытое открытым, разворот не повторяется")
check(s["pinned"].startswith('<div class="fold-slot cells-fold" data-fold-key="controller:22002" data-fold-mode="pinned">'),
      "закреплённая — режим pinned, и peek ей не ставится даже по просьбе")
check("line</div>" not in s["pinned"] and "card</article>" in s["pinned"],
      "у закреплённой строки нет — только карточка на месте")
check('data-t="fold-unpin"' in s["pinned"] and "▴" in s["pinned"] and f'title="{s["pinWords"][1]}"' in s["pinned"],
      "у закреплённой — ▴ «свернуть обратно» (foldUnpinTitle)")
check('class="fold-slot clients-fold"' in s["clients"], "лента клиентов — свой класс места")
check('class="fold-slot cells-fold"' in s["oddLane"] and 'data-fold-mode="line"' in s["oddMode"],
      "неизвестная лента — ячейки, неизвестный режим — line: без пустых классов")
check('"><b>' not in s["escaped"] and "&quot;&gt;&lt;b&gt;" in s["escaped"], "ключ экранируется")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m_ in _fail:
        print("  - " + m_)
    sys.exit(1)
print("js card-rows OK: строка ячейки, строка агента, место свёрнутой карточки — значениями")
