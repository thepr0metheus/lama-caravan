#!/usr/bin/env python3
"""Snapshot of static/js/onboarding-tours.js — which tour, and when.

What's pinned by value: picking the step set from the page's state (the
te/tr editor open → the editor tour with its prefix; standalone Routing → the
Routing tour; otherwise → the board tour); the board's and editor's step
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
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

STUBS = "onboarding,i18n,i18n-data,board-view"

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
globalThis.__view = { isMachine: false };
globalThis.__stubValues = { "board-view.BOARD_VIEW": globalThis.__view, "i18n-data.LANGS": [{ code: "en", emoji: "🍔", label: "English" }, { code: "ru", emoji: "🥟", label: "Русский" }], "i18n-data.messages": { en: {}, ru: {} }, "i18n.lang": "en" };
globalThis.__loaded = []; globalThis.__timers = []; globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push({ fn, ms }); return 0; };
globalThis.__observers = []; globalThis.MutationObserver = class { constructor(cb) { this.cb = cb; this.targets = []; this.disconnected = false; globalThis.__observers.push(this); } observe(el) { this.targets.push(el); } disconnect() { this.disconnected = true; } fire() { this.cb(); } };
const docListeners = {}; document.addEventListener = (t, fn) => { (docListeners[t] ||= []).push(fn); }; document.removeEventListener = (t, fn) => { const l = docListeners[t] || []; const i = l.indexOf(fn); if (i >= 0) l.splice(i, 1); };
document.createElement = () => ({ className: "", innerHTML: "", listeners: {}, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } });
globalThis.__q = {}; document.querySelector = (sel) => (Object.prototype.hasOwnProperty.call(globalThis.__q, sel) ? globalThis.__q[sel] : null);
globalThis.__stubReturns = { "i18n.t": (k) => "T:" + k, "i18n-data.onLanguageLoaded": (fn) => { globalThis.__loaded.push(fn); } };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/onboarding-tours.js").href);
// A machine's page as its builder draws it, to hold the machine tour's anchors to what the page draws (scripts/_tour_anchors.mjs).
const MH = await import(pathToFileURL(process.env.JS_ROOT + "/machine-head.js").href);
const { drawn } = await import("./_tour_anchors.mjs");
const S = await import(pathToFileURL(process.env.JS_ROOT + "/onboarding-strings.js").href);
const F = () => globalThis.__fields;
let tours = [], buttons = null, autos = [], langCalls = [];
const reset = () => { globalThis.__view.isMachine = false; tours = []; buttons = null; autos = []; langCalls = []; localStorage.clear(); globalThis.__timers.length = 0; globalThis.__observers.length = 0; globalThis.__q = {}; globalThis.__fields = {}; delete globalThis.ROUTER_STANDALONE; for (const k of Object.keys(docListeners)) delete docListeners[k];
  globalThis.__stubReturns = { "i18n.t": (k) => "T:" + k, "i18n.setLang": async (c) => { langCalls.push(c); }, "i18n-data.onLanguageLoaded": (fn) => { globalThis.__loaded.push(fn); },
    "onboarding.createTour": (cfg) => { const t = { cfg, started: 0, start() { this.started += 1; }, stop() {} }; tours.push(t); return t; }, "onboarding.initTourButtons": (o) => { buttons = o; }, "onboarding.autoStartOnce": (key, ready, fn) => { autos.push({ key, ready, fn }); } }; };
reset();
const steps = () => tours.at(-1).cfg.steps();
const out = {};
"""

PINS = [
    ("tour_strings_merge_into_language_table", '', '(() => { const table = {}; globalThis.__loaded[0]("ru", table); const en = {}; globalThis.__loaded[0]("en", en); const none = {}; globalThis.__loaded[0]("xx", none); return [Object.keys(table).length > 10, table.tourNext === S.TOUR_STRINGS.ru.tourNext, Object.keys(en).length > 10, Object.keys(none).length]; })()',
     '[true,true,true,0]', "строки туров вливаются в таблицу языка при её загрузке; языку без своих строк ничего не подмешивается (t() отдаст английский)"),
    ("index_tour_by_default", '', '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); out.indexAnchors = st.map((x) => x.anchor).filter(Boolean); return [st.length, st[0].center, st[0].title, typeof st[0].onRender, st[2].anchor, st[3].anchor, st.at(-1).center, tours.at(-1).started]; })()',
     '[11,true,"T:tourIxWelcomeT","function",".topology-board","#topologyClients",true,1]', "по умолчанию — тур доски: 11 шагов (шаг пулов ушёл: пулы в Маршрутизации, 2026-10-12; жизнь ячейки и новая ячейка — на странице машины, 2026-10-27), приветствие с пикером языка, якоря лейн, финальный центрированный; кнопка запускает тур"),
    ("routing_tour_when_standalone", 'globalThis.ROUTER_STANDALONE = true;', '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); return [st.length, st[1].anchor, st[2].anchor, autos[0].key]; })()',
     '[6,"[data-t=\'pb-clients\']","[data-t=\'pb-direct\']","routing"]', "standalone-Маршрутизация — свой тур: приветствие, клиенты, «Напрямую», пулы, модели, очередь — и свой ключ автостарта (наборов нет с 1.3.675)"),
    ("editor_tour_when_modal_open", 'globalThis.__fields = { llamaRemoteEditOverlay: { hidden: false } };', '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); return [st.length, st[0].anchor]; })()',
     '[12,"#llamaRemoteEditForm .cell-kind-toggle"]', "открыт редактор ячейки — тур редактора, двенадцать шагов"),
    ("no_editor_tour_for_the_retired_overlay", 'globalThis.__fields = { topologyLlamaEditOverlay: { hidden: false } };', '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); return [st.length, st.some((x) => String(x.anchor || "").includes("te-") || String(x.anchor || "").includes("topologyLlamaEdit"))]; })()',
     '[11,false]', "negative: оверлей прежнего редактора ячеек контроллера (ушёл в шаге 6.9) тур не узнаёт — тур доски, без его якорей"),
    ("remote_editor_tour_prefix", 'globalThis.__fields = { llamaRemoteEditOverlay: { hidden: false } };', '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); return [st[1].anchor, st.at(-1).anchor]; })()',
     '["#llamaRemoteEditForm .model-file-field","#llamaRemoteEditStart"]', "удалённый редактор (tr) — те же шаги с префиксом tr и своей кнопкой"),
    ("machine_tour_on_a_machines_page", 'globalThis.__view.isMachine = true;',
     '(() => { m.initOnboarding(); buttons.onClick(); const st = steps(); return [st.length, typeof st[0].onRender, st.map((x) => x.center ? null : x.anchor), autos[0].key]; })()',
     json.dumps([11, "function", [None, ".machine-tools", "[data-machine-map]", '[data-t="machine-chosen"]', '[data-t="machine-models"]',
                 '[data-t="machine-add"]',
                 '[data-t="machine-side-engines"]', '[data-t="machine-side-disk"]', '[data-t="machine-side-incidents"]', '[data-t="machine-side-activity"]', None],
                "machine"]),
     "страница машины — свой тур из 11 шагов по её частям (владелец, 2026-10-27: «проверь работу тура на этой странице»: там шёл тур главной "
     "доски — клиенты и Маршрутизация, которых на ней нет, и кольцо вокруг всей страницы); свой ключ автостарта. Шаг о блоке выбранной модели "
     "стоит перед шагом о списке: блок — над списком (2026-11-05)"),
    ("machine_tour_anchors_are_drawn", '',
     '(() => { const node = { id: "h1", name: "h1", role: "host", online: true, platform: "linux", ip: "10.0.0.5", cpu: { ram: { totalGb: 64, usedGb: 8 } },'
     ' gpus: [{ index: 0, name: "RTX", memoryTotalMiB: 24576, memoryUsedMiB: 2000 }], servers: [{ port: 22001, phase: "running", gpuMem: { "0": 2048 } }, { port: 22002, phase: "stopped" }] };'
     ' const cells = new Map([["22001", { key: "h1:22001", name: "a", window: true, group: "holds", stop: "x", launch: "", jobs: ["llm"], runner: "llama.cpp", fit: {} }],'
     ' ["22002", { key: "h1:22002", name: "b", window: true, group: "bench", stop: "", launch: "y", jobs: ["llm"], runner: "llama.cpp", fit: {} }]]);'
     ' const side = new MH.MachineSide({ engines: "<div>e</div>", disk: "<div>d</div>", incidents: 2, activity: "<div>a</div>" }).html();'
     ' const html = new MH.MachineHead(node, { cells, side }).html();'
     ' return [m.TOURS.machine().filter((x) => x.anchor && !drawn(html, x.anchor)).map((x) => x.anchor), drawn(html, \'[data-t="machine-chosen"]\'), '
     ' drawn(html, \'[data-t="machine-chosen-none"]\'), html.includes("T:machineChosenNone"), drawn(html, \'[data-t="machine-nope"]\'), drawn(html, "#topologyClients")]; })()',
     '[[],true,true,true,false,false]',
     "каждый якорь тура страницы машины она и рисует (шапка, карта, блок выбранной модели, список моделей, «Добавить модель», колонка справа); "
     "блок рисуется всегда, даже когда ничего не выбрано, и говорит об этом словами; "
     "negative: якорь, которого страница не рисует (выдуманный, клиенты главной доски), не находится"),
    ("machine_auto_start_ready", 'globalThis.__view.isMachine = true;',
     '(() => { m.initOnboarding(); const a = autos[0]; const before = a.ready(); globalThis.__fields = { appLoader: null }; globalThis.__q["[data-machine-head]"] = {}; return [a.key, before, a.ready()]; })()',
     '["machine",false,true]',
     "автостарт страницы машины: готово, когда лоадер ушёл и голова машины нарисована; negative: раньше — нет"),
    ("editor_anchors_stand_on_what_the_form_shows", 'globalThis.__fields = { llamaRemoteEditOverlay: { hidden: false } };',
     '(() => { m.initOnboarding(); buttons.onClick(); out.editorAnchors = steps().map((x) => x.anchor); const st = steps(); return [st[2].anchor, st[3].anchor, st[9].anchor]; })()',
     json.dumps(["#llamaRemoteEditForm .companion-field:has(#tr-MMPROJ_FILE)", "#llamaRemoteEditForm .companion-field:has(#tr-SPEC_DRAFT_MODEL_FILE)",
                 "#tr-previewCmdline, #tr-cmdPreview"]),
     "шаги формы стоят на том, что форма показывает: пара — на своей строке, а не на select за переключателем; команда — на превью llama.cpp "
     "или других раннеров, какое видно (2026-10-27: три шага не показывались никогда)"),
    ("labels_from_i18n", '', '(() => { m.initOnboarding(); buttons.onClick(); const L = tours.at(-1).cfg.labels; return [typeof L === "function" ? L() : L, buttons.title()]; })()',
     '[{"next":"T:tourNext","back":"T:tourBack","done":"T:tourDone","skip":"T:tourSkip"},"T:tourBtnTitle"]', "подписи кнопок и заголовок кнопки тура — из i18n"),
    ("auto_start_ready_and_guard", '', '(() => { m.initOnboarding(); const a = autos[0]; const notReady = a.ready(); globalThis.__fields = { appLoader: null }; globalThis.__q[".topology-board"] = {}; const ready = a.ready(); globalThis.__q[".ob-root"] = {}; a.fn(); const skipped = tours.length; delete globalThis.__q[".ob-root"]; a.fn(); return [a.key, notReady, ready, skipped, tours.length]; })()',
     '["index",false,true,0,1]', "автостарт доски: готовность = лоадер ушёл и доска есть; если тур уже открыт — не мешает"),
    ("auto_start_ready_with_loader_present", 'globalThis.__fields = { appLoader: {} }; globalThis.__q[".topology-board"] = {};', '(() => { m.initOnboarding(); return autos[0].ready(); })()', 'false', "negative: пока лоадер на месте — не готово"),
    ("lang_picker_switches_and_rerenders", '', '(() => { m.initOnboarding(); buttons.onClick(); const body = { appended: null, appendChild(el) { this.appended = el; } }; let rerendered = 0; steps()[0].onRender(body, { rerender: () => rerendered++ }); const wrap = body.appended; const html = wrap.innerHTML; wrap.listeners.click[0]({ target: { closest: () => ({ dataset: { obLang: "ru" } }) } }); wrap.listeners.click[0]({ target: { closest: () => null } }); return [wrap.className, html.includes(\'data-ob-lang="ru"\'), html.includes(\'ob-lang selected" data-ob-lang="en"\'), langCalls, rerendered]; })()',
     '["ob-langs",true,true,["ru"],1]', "пикер языка: кнопка на язык, текущий отмечен, клик переключает язык и перерисовывает тур; клик мимо — ничего"),
    ("editor_first_open_starts_tour_once", 'globalThis.__fields = { topologyLlamaEditOverlay: { hidden: true }, llamaRemoteEditOverlay: { hidden: true } };', '(() => { m.initOnboarding(); const obs = globalThis.__observers[0]; obs.fire(); globalThis.__fields.topologyLlamaEditOverlay.hidden = false; obs.fire(); const closedYet = [tours.length, localStorage.getItem("caravanTourSeen:config")]; globalThis.__fields.llamaRemoteEditOverlay.hidden = false; obs.fire(); const armed = [(docListeners.pointerdown || []).length, localStorage.getItem("caravanTourSeen:config"), globalThis.__timers.at(-1)?.ms]; globalThis.__timers.at(-1).fn(); return [...closedYet, ...armed, tours.length, obs.disconnected, (docListeners.pointerdown || []).length]; })()',
     '[0,null,1,"1",900,1,true,0]', "первое открытие редактора: пока закрыт — ничего (и открытый оверлей прежнего редактора контроллера — тоже ничего); открылся — флаг, слушатели, через 0.9 с тур; наблюдатель отключён, слушатели сняты"),
    ("editor_first_open_cancelled_by_interaction", 'globalThis.__fields = { llamaRemoteEditOverlay: { hidden: false } };', '(() => { m.initOnboarding(); globalThis.__observers[0].fire(); docListeners.pointerdown[0](); globalThis.__timers.at(-1).fn(); return [tours.length, localStorage.getItem("caravanTourSeen:config")]; })()',
     '[0,"1"]', "клик за 0.9 с отменяет тур редактора, флаг всё равно записан — второй раз не предложит"),
    ("editor_watch_skipped_when_seen_or_no_overlays", '', '(() => { localStorage.setItem("caravanTourSeen:config", "1"); globalThis.__fields = { llamaRemoteEditOverlay: { hidden: true } }; m.initOnboarding(); const a = globalThis.__observers.length; localStorage.clear(); globalThis.__fields = { topologyLlamaEditOverlay: { hidden: true } }; m.initOnboarding(); return [a, globalThis.__observers.length]; })()',
     '[0,0]', "negative: тур редактора уже виден или редактора на странице нет (только оверлей прежнего редактора контроллера — не в счёт) — наблюдатель не ставится"),
]


_fail = []


class Markup(HTMLParser):
    """index.html as a tree, to find the editor tour's anchors in it the way a browser does: the editor's form is static
    markup, so a step that stands on nothing in it stands on nothing on the page."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    class Node:
        def __init__(self, tag, attrs, parent):
            self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    def __init__(self, text):
        super().__init__()
        self.root = self.cur = Markup.Node("#root", {}, None)
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Markup.Node(tag, {k: v or "" for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in self.VOID:
            self.cur = node

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    @staticmethod
    def walk(node):
        for child in node.children:
            yield child
            yield from Markup.walk(child)

    COMPOUND = re.compile(r"^([a-z][\w-]*)?((?:[#.][\w-]+|\[[\w-]+(?:=(?:\"[^\"]*\"|'[^']*'))?\])*)(?::has\((.+)\))?$")

    def fits(self, node, compound):
        m = self.COMPOUND.match(compound)
        if not m:
            raise ValueError(f"an anchor this check cannot read: {compound}")
        tag, parts, has = m.groups()
        if tag and node.tag != tag:
            return False
        for part in re.findall(r"[#.][\w-]+|\[[^\]]+\]", parts or ""):
            if part[0] == "#" and node.attrs.get("id") != part[1:]:
                return False
            if part[0] == "." and part[1:] not in node.attrs.get("class", "").split():
                return False
            if part[0] == "[":
                key, _, value = part[1:-1].partition("=")
                if key not in node.attrs or (value and node.attrs[key] != value.strip("\"'")):
                    return False
        return not has or bool(self.select(has, node))

    def select(self, selector, scope=None):
        """What `selector` matches under `scope`: a list of selectors ("A, B"), each compounds with descendants."""
        scope = scope or self.root
        found = []
        for one in [x.strip() for x in re.split(r",(?![^(]*\))", selector)]:
            parts = one.split()
            for node in self.walk(scope):
                if not self.fits(node, parts[-1]):
                    continue
                need, up = parts[:-1][::-1], node.parent
                while need and up is not None and up is not scope:
                    if self.fits(up, need[0]):
                        need.pop(0)
                    up = up.parent
                if not need:
                    found.append(node)
        return found


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
            probe_args(node, harness, path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
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

    print("якоря тура главной доски — в её разметке (index.html):")
    page = Markup((ROOT / "static" / "index.html").read_text(encoding="utf-8"))
    # A machine's glance is drawn by the board (topology-nodes.js) into the lane index.html holds.
    glance = {"#topologyLlamaServers .node-card": ("static/js/topology-nodes.js", '<section class="node-card machine-glance ')}
    index = got.get("indexAnchors") or []
    check(len(index) == 8 and not [a for a in index if a not in glance and not page.select(a)]
          and bool(page.select("#topologyLlamaServers"))
          and all(snippet in (ROOT / path).read_text(encoding="utf-8") for path, snippet in glance.values()),
          "каждый из 8 якорей тура доски — в её разметке, а карточка машины — в полосе, которую та держит; "
          "negative: шагов «жизнь ячейки» и «новая ячейка» нет — их кнопок на главной доске нет с переезда ячеек на страницу машины")
    print()

    print("якоря тура формы ячейки — в её разметке (index.html):")
    # Drawn when the form opens, not in the static markup: the tabs' bar (form.js builds it into #tr-dynamicFields).
    built = {"#llamaRemoteEditForm .advanced-tab-bar": ("static/js/form.js", 'bar.className = "advanced-tab-bar"')}
    anchors = got.get("editorAnchors") or []
    missing = [a for a in anchors if a not in built and not page.select(a)]
    on_selects = [a for a in anchors if a not in built and any(n.tag == "select" for n in page.select(a))]
    check(len(anchors) == 12 and not missing,
          f"каждый из 12 якорей формы находится в её разметке так, как его ищет браузер (не найдены: {missing})")
    check(not on_selects,
          f"ни один шаг не стоит на select: select модели и пары спрятаны за выбором и переключателем, такой шаг не показывался "
          f"(на select: {on_selects})")
    check(all(snippet in (ROOT / path).read_text(encoding="utf-8") for path, snippet in built.values()),
          "якорь, который строится при открытии формы, строится там, где сказано (панель вкладок — form.js)")
    check(not page.select("#llamaRemoteEditForm .nope-field") and len(page.select("#tr-previewCmdline, #tr-cmdPreview")) == 2,
          "negative: якорь, которого в разметке нет, не находится; список «A, B» находит оба")
    print()

    print("шаг тура страницы машины про модели:")
    strings = (ROOT / "static" / "js" / "onboarding-strings.js").read_text(encoding="utf-8")
    bodies = re.findall(r'^  tourMcModelsB: "(.*)",$', strings, re.M)
    check(len(bodies) == 6 and len(set(bodies)) == 6 and all("📦" in body for body in bodies),
          "шаг говорит, что там теперь: модели и их ячейки, 📦 — ячейка; на всех шести языках, и каждый по-своему")
    check("tourMcBench" not in strings, "negative: слов про блок «Ячейки», которого нет, не осталось ни на одном языке")
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
