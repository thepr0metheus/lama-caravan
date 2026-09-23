#!/usr/bin/env python3
"""Снимок static/js/card-fold.js — какие карточки доски сворачиваются в строку.

На контроллере 24 ячейки, работают 6, а во весь рост рисовались все; у клиентов
14 маршрутов, запасной у одного. CardFold решает три вещи, и все три пинятся
ЗНАЧЕНИЯМИ: что тихо настолько, чтобы свернуться (беда — никогда), что выбрал
человек для ленты и что он закрепил открытым. FoldPeek — сторона указателя и
клавиатуры: клик по строке закрепляет, кнопки строки делают своё, Escape
закрывает, событие без цели не роняет страницу.

Хранилище подставное (Map), автоматизация — флагом: снимок не читает браузер.

Запуск: python3 scripts/test_js_card_fold.py
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
const { CardFold, FoldPeek } = await import(pathToFileURL(process.env.JS_ROOT + "/card-fold.js").href);
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;

const store = (init = {}) => {
  const m = new Map(Object.entries(init));
  return { m, getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
};
const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
const mk = (init, automated = false) => new CardFold({ storage: store(init), automated });

// Fake DOM pieces for FoldPeek: an element answers closest/matches from a table.
const el = (table = {}, extra = {}) => ({
  closest: (sel) => (Object.prototype.hasOwnProperty.call(table, sel) ? table[sel] : null),
  matches: (sel) => !!extra.matches?.includes(sel),
  dataset: extra.dataset || {},
  ownerDocument: { querySelectorAll: () => [] },
});

const out = {};
out.density = {
  fresh: mk().density("cells"),
  freshAutomated: mk({}, true).density("cells"),
  chosenFullWins: mk({ boardCardDensity: JSON.stringify({ cells: "full" }) }).density("cells"),
  chosenCompactBeatsAutomation: mk({ boardCardDensity: JSON.stringify({ clients: "compact" }) }, true).density("clients"),
  otherLaneUntouched: mk({ boardCardDensity: JSON.stringify({ cells: "full" }) }).density("clients"),
  garbageValue: mk({ boardCardDensity: JSON.stringify({ cells: "sideways" }) }).density("cells"),
  notJson: mk({ boardCardDensity: "{oops" }).density("cells"),
  arrayInsteadOfObject: mk({ boardCardDensity: JSON.stringify(["full"]) }).density("cells"),
  storageBlocked: new CardFold({ storage: broken, automated: false }).density("cells"),
  noStorage: new CardFold({ storage: null, automated: false }).density("cells"),
};
out.toggle = (() => {
  const s = store(); const f = new CardFold({ storage: s, automated: false });
  const a = f.toggleDensity("cells"); const saved1 = s.m.get("boardCardDensity");
  const b = f.toggleDensity("cells"); const saved2 = s.m.get("boardCardDensity");
  const blocked = new CardFold({ storage: broken, automated: false });
  let threw = false; try { blocked.toggleDensity("cells"); } catch { threw = true; }
  return { a, saved1, b, saved2, clientsAfter: f.density("clients"), blockedThrew: threw, blockedNow: blocked.density("cells") };
})();
out.pins = (() => {
  const s = store(); const f = new CardFold({ storage: s, automated: false });
  f.peekKey = "controller:22002";
  const on = f.togglePin("controller:22002");
  const saved = s.m.get("boardCardPinned");
  const peekAfterPin = f.peekKey;
  const g = mk(); g.togglePin(22003);
  const numberKey = [g.isPinned("22003"), g.isPinned(22003)];
  const off = f.togglePin("controller:22002");
  const restored = mk({ boardCardPinned: JSON.stringify(["agent:c:a"]) }).isPinned("agent:c:a");
  const objectInsteadOfArray = mk({ boardCardPinned: JSON.stringify({ a: 1 }) }).isPinned("a");
  return { on, saved, peekAfterPin, numberKey, off, savedOff: s.m.get("boardCardPinned"), restored, objectInsteadOfArray };
})();
out.mode = (() => {
  const f = mk(); f.togglePin("k-pinned");
  const full = mk({ boardCardDensity: JSON.stringify({ cells: "full" }) });
  return {
    quietCompact: f.mode("cells", "k", true),
    loudCompact: f.mode("cells", "k", false),
    quietPinned: f.mode("cells", "k-pinned", true),
    loudPinned: f.mode("cells", "k-pinned", false),
    quietFullLane: full.mode("cells", "k", true),
    otherLaneCompact: full.mode("clients", "k", true),
  };
})();
out.cellQuiet = Object.fromEntries([
  ["running", { phase: "running" }], ["stopped", { phase: "stopped" }], ["reserved", { phase: "reserved" }],
  ["starting", { phase: "starting" }], ["warming", { phase: "warming" }], ["downloading", { phase: "downloading" }],
  ["stopping", { phase: "stopping" }], ["error", { phase: "error" }], ["broken", { phase: "broken" }],
  ["runningTransient", { phase: "running", transient: true }], ["stoppedCrashed", { phase: "stopped", crashed: true }],
  ["runningUnreachable", { phase: "running", unreachable: true }], ["nothing", {}], ["undefinedArg", undefined],
].map(([k, f]) => [k, CardFold.cellQuiet(f)]));
out.agentQuiet = Object.fromEntries([
  ["one", { routes: 1 }], ["two", { routes: 2 }], ["none", { routes: 0 }], ["asText", { routes: "2" }],
  ["stale", { routes: 1, stale: true }], ["incident", { routes: 1, incident: true }], ["missing", {}],
].map(([k, f]) => [k, CardFold.agentQuiet(f)]));

// ── FoldPeek: clicks and keys ───────────────────────────────────────────
out.peek = await (async () => {
  const f = mk(); let changed = 0;
  const p = new FoldPeek(f, { changed: () => { changed += 1; } });
  const slot = { dataset: { foldKey: "controller:22006" } };
  const r = {};
  // a click on the line itself pins its card
  const line = el({ ".fold-row": { closest: (s) => (s === ".fold-slot" ? slot : null) } });
  let prevented = 0;
  p.onClick({ target: line, preventDefault: () => { prevented += 1; } });
  r.lineClick = [f.isPinned("controller:22006"), changed, prevented];
  // ▶ on the line starts the cell: no pin, nothing repainted
  const play = el({ ".fold-row": {}, "button, a, .topology-handle": {} });
  p.onClick({ target: play, preventDefault: () => {} });
  r.playClick = [f.isPinned("controller:22006"), changed];
  // the pin control folds it back
  const pin = el({ "[data-fold-pin]": { closest: (s) => (s === ".fold-slot" ? slot : null) } });
  p.onClick({ target: pin, preventDefault: () => {} });
  r.pinClick = [f.isPinned("controller:22006"), changed];
  // a click anywhere else is not ours
  p.onClick({ target: el({}), preventDefault: () => {} });
  r.elsewhere = changed;
  // the lane switch flips its lane and repaints
  const sw = el({ "[data-board-density]": { dataset: { boardDensity: "clients" } } });
  p.onClick({ target: sw, preventDefault: () => {} });
  r.switchClick = [f.density("clients"), f.density("cells"), changed];
  // events without a target (synthetic, some focus events) are ignored, not thrown on
  let threw = [];
  for (const [name, fn] of [["click", () => p.onClick({})], ["key", () => p.onKey({ key: "Enter" })],
                            ["focusin", () => p.onFocusIn({})], ["focusout", () => p.onFocusOut({})],
                            ["over", () => p.onOver({})], ["out", () => p.onOut({})]]) {
    try { fn(); } catch (e) { threw.push(name); }
  }
  r.noTarget = threw;
  // Enter on a focused line clicks it; Enter elsewhere does nothing
  let clicked = 0, kp = 0;
  p.onKey({ key: "Enter", target: { matches: (s) => s === ".fold-row", click: () => { clicked += 1; } }, preventDefault: () => { kp += 1; } });
  p.onKey({ key: "Enter", target: { matches: () => false, click: () => { clicked += 1; } }, preventDefault: () => { kp += 1; } });
  r.enter = [clicked, kp];
  // Escape closes whatever floats
  f.peekKey = "x"; p.onKey({ key: "Escape" }); r.escape = f.peekKey;
  // a busy lane (a cable being dragged) floats nothing
  const busy = new FoldPeek(mk(), { busy: () => true });
  const s2 = { dataset: { foldKey: "k" }, classList: { add() { this.on = true; }, remove() {}, contains: () => false }, ownerDocument: { querySelectorAll: () => [] } };
  busy.open(s2); r.busyOpen = [!!s2.classList.on, busy.fold.peekKey];
  const free = new FoldPeek(mk(), {});
  const s3 = { dataset: { foldKey: "k3" }, classList: { added: [], removed: [], on: false,
    add(...c) { this.added.push(...c); this.on = true; }, remove(...c) { this.removed.push(...c); }, contains: () => false },
    ownerDocument: { querySelectorAll: () => [] } };
  free.open(s3); r.freeOpen = [!!s3.classList.on, free.fold.peekKey];
  r.enterMarked = [...s3.classList.added];
  r.enterBeforeBeat = [...s3.classList.removed];
  // The harness unrefs every timer (a page's poll must not keep a snapshot
  // alive); this one wait is ref'd back, or node would exit before the beat.
  await new Promise((res) => setTimeout(res, FoldPeek.ENTER_MS + 40)?.ref?.());
  r.enterAfterBeat = [...s3.classList.removed];
  // closing takes both marks off at once, whatever beat it falls on
  const s4 = { dataset: { foldKey: "k4" }, classList: { removed: [], add() {}, remove(...c) { this.removed.push(...c); }, contains: () => false },
    ownerDocument: { querySelectorAll: () => [] } };
  free.open(s4); free.close(s4); r.closeMarks = [...s4.classList.removed];
  return r;
})();
out.words = {
  compact: en.densityCompactTitle, full: en.densityFullTitle,
  switchTitles: (() => {
    const f = mk({ boardCardDensity: JSON.stringify({ cells: "full" }) });
    const btn = (lane) => ({ dataset: { boardDensity: lane }, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, title: "", textContent: "" });
    const b1 = btn("cells"), b2 = btn("clients");
    f.syncSwitches({ querySelectorAll: () => [b1, b2] });
    return [[b1.attrs["aria-pressed"], b1.title === en.densityFullTitle, b1.textContent, b1.attrs["aria-label"] === b1.title],
            [b2.attrs["aria-pressed"], b2.title === en.densityCompactTitle, b2.textContent]];
  })(),
  noDocument: (() => { try { mk().syncSwitches(null); return "ok"; } catch (e) { return "threw"; } })(),
};
out.delay = FoldPeek.DELAY_MS;
console.log(JSON.stringify(out));
"""

node = find_node()
if node is None:
    print("js card-fold: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
    sys.exit(0)
probe = ROOT / "scripts" / ".probe_card_fold.tmp.mjs"
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
    print("js card-fold: FAILED — харнесс не отработал")
    print(proc.stderr.strip()[:900])
    sys.exit(1)
got = json.loads(proc.stdout.strip().splitlines()[-1])

print("выбор ленты (compact / full):")
d = got["density"]
check(d["fresh"] == "compact", "человеку без выбора — свёрнуто: ради этого всё и делалось")
check(d["freshAutomated"] == "full",
      "автоматике без выбора — полностью: E2E жмёт кнопки, которые свёрнутая карточка показывает лишь всплыв")
check(d["chosenFullWins"] == "full", "выбранное «full» держится")
check(d["chosenCompactBeatsAutomation"] == "compact", "явный выбор сильнее умолчания автоматики")
check(d["otherLaneUntouched"] == "compact", "выбор одной ленты не трогает другую")
check(d["garbageValue"] == "compact", "мусор в хранилище («sideways») — умолчание, а не мусор в работе")
check(d["notJson"] == "compact" and d["arrayInsteadOfObject"] == "compact",
      "битый JSON и не та форма (массив вместо объекта) — умолчание")
check(d["storageBlocked"] == "compact" and d["noStorage"] == "compact",
      "хранилище недоступно или бросает — доска рисуется по умолчанию, без исключения")
tg = got["toggle"]
check(tg["a"] == "full" and json.loads(tg["saved1"]) == {"cells": "full"}, "переключатель переворачивает ленту и записывает выбор")
check(tg["b"] == "compact" and json.loads(tg["saved2"]) == {"cells": "compact"}, "второй щелчок возвращает и тоже записывает")
check(tg["clientsAfter"] == "compact", "переключение ячеек не трогает клиентов")
check(tg["blockedThrew"] is False and tg["blockedNow"] == "full",
      "запись заблокирована — выбор живёт до перезагрузки, исключения нет")

print("закреплённые карточки:")
pn = got["pins"]
check(pn["on"] is True and json.loads(pn["saved"]) == ["controller:22002"], "булавка ставится и записывается")
check(pn["peekAfterPin"] == "", "закреплённая карточка перестаёт считаться всплывшей")
check(pn["numberKey"] == [True, True], "ключ-число и тот же ключ строкой — одно и то же")
check(pn["off"] is False and json.loads(pn["savedOff"]) == [], "повторный клик снимает булавку и записывает пустой список")
check(pn["restored"] is True, "булавки переживают перезагрузку страницы")
check(pn["objectInsteadOfArray"] is False, "не та форма в хранилище — ничего не закреплено, без исключения")

print("как рисуется карточка:")
m = got["mode"]
check(m["quietCompact"] == "line", "тихая в свёрнутой ленте — строка")
check(m["loudCompact"] == "full", "беда в свёрнутой ленте — полная карточка: беда не сворачивается")
check(m["quietPinned"] == "pinned", "закреплённая тихая — полная на месте, с кнопкой свернуть")
check(m["loudPinned"] == "full", "закреплённая, но в беде — просто полная (булавка ни при чём)")
check(m["quietFullLane"] == "full", "лента «full» — всё полностью")
check(m["otherLaneCompact"] == "line", "«full» у ячеек не разворачивает клиентов")

print("что тихо у ячейки:")
cq = got["cellQuiet"]
check(cq["running"] and cq["stopped"] and cq["reserved"], "работает, стоит, зарезервирована — тихо")
check(not any(cq[k] for k in ("starting", "warming", "downloading", "stopping", "error", "broken")),
      "старт, прогрев, загрузка, остановка, ошибка, поломка — не тихо")
check(not cq["runningTransient"], "работает, но идёт действие (стоп, удаление, ожидание) — не тихо")
check(not cq["stoppedCrashed"], "стоит, но падала — не тихо: счётчик падений должен быть виден")
check(not cq["runningUnreachable"], "работает, но недостижима (файрвол) — не тихо")
check(not cq["nothing"] and not cq["undefinedArg"], "нет фактов — не тихо: незнание не сворачивается")

print("что тихо у агента:")
aq = got["agentQuiet"]
check(aq["one"] and aq["two"] and aq["asText"], "один или два маршрута — тихо; число строкой — тоже число")
check(not aq["none"], "без маршрута — не тихо: агент, который никуда не ходит, — самый громкий случай ленты")
check(not aq["stale"] and not aq["incident"], "исчезнувшая машина агента и инцидент на маршруте — не тихо")
check(not aq["missing"], "нет фактов — не тихо")

print("FoldPeek — клики и клавиши:")
pk = got["peek"]
check(pk["lineClick"] == [True, 1, 1], "клик по строке закрепляет карточку, перерисовывает доску, гасит действие по умолчанию")
check(pk["playClick"] == [True, 1], "▶ в строке запускает ячейку — булавка не трогается, лишней перерисовки нет")
check(pk["pinClick"] == [False, 2], "▴ сворачивает закреплённую обратно")
check(pk["elsewhere"] == 2, "клик мимо строк и булавок — не наш, ничего не происходит")
check(pk["switchClick"] == ["full", "compact", 3], "переключатель клиентов разворачивает клиентов, ячеек не трогает")
check(pk["noTarget"] == [], "события без цели не роняют страницу — ни один обработчик не бросает")
check(pk["enter"] == [1, 1], "Enter на строке — клик по ней; Enter вне строки — ничего")
check(pk["escape"] == "", "Escape закрывает всплывшую карточку")
check(pk["busyOpen"] == [False, ""], "пока тянут канат, карточки не всплывают")
check(pk["freeOpen"] == [True, "k3"], "в покое карточка всплывает и запоминается как всплывшая")
check(pk["enterMarked"] == ["peek", "peek-enter"] and pk["enterBeforeBeat"] == [],
      "открытие жестом ставит peek и на один такт peek-enter — это он играет разворот")
check(pk["enterAfterBeat"] == ["peek-enter"], "через ENTER_MS peek-enter снят сам — раскрытая карточка остаётся раскрытой, но не проигрывается заново")
check(pk["closeMarks"] == ["peek", "peek-enter"], "закрытие снимает обе метки сразу — даже посреди разворота")
check(got["delay"] == 300, "задержка перед всплытием — 300 мс: пересечь ленту — не мигать каждой карточкой")

print("подписи переключателя:")
w = got["words"]
check(w["switchTitles"][0] == ["false", True, "⊞", True],
      "лента «full»: не нажат, подпись «всё полностью» из en.js, значок ⊞, aria-label совпадает с подсказкой")
check(w["switchTitles"][1] == ["true", True, "⊟"], "лента «compact»: нажат, подпись «спокойные свёрнуты», значок ⊟")
check(w["noDocument"] == "ok", "без документа (снимок, ранний вызов) — ничего не делает и не падает")

print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m_ in _fail:
        print("  - " + m_)
    sys.exit(1)
print("js card-fold OK: правило свёртки, выбор ленты, булавки и клики — значениями")
