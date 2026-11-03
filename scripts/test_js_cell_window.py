#!/usr/bin/env python3
"""Value snapshot: a cell's window, variant Г (static/js/cell-window.js; the owner's choice of 2026-10-24).

The window is drawn from facts the board gathers (topology-nodes.js); this test feeds the class those facts by hand and
reads what it draws: the band's state and tone, the one main button and the attributes it carries, the "⋯" items and
which of them are shut (and why), the tabs (the talk only for a runner that talks) and the tab a repaint keeps, every
panel with nothing to say saying so, and what is escaped. The words come from static/js/i18n/en.js, read by the probe.

Run: python3 scripts/test_js_cell_window.py
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


def esc(text):
    """A word as the page writes it: escapeHtml of static/js/utils.js."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


CFG = 'data-node-cell-start="h1" data-node-cell-port="22020" data-node-role="client"'

PROBE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const root = process.env.JS_ROOT;
const { CellWindow } = await import(pathToFileURL(root + "/cell-window.js").href);
const en = (await import(pathToFileURL(root + "/i18n/en.js").href)).default;

const START = 'data-node-cell-launch="h1" data-node-cell-port="22020" data-node-cell-runner="llama-server" data-node-cell-model="Hermes"';
const STOP = 'data-node-cell-stop="h1" data-node-cell-port="22020" data-node-cell-model="Hermes"';
const CFG = 'data-node-cell-start="h1" data-node-cell-port="22020" data-node-role="client"';
const BOOT = 'data-node-cell-boot="h1" data-node-cell-port="22020" data-node-cell-boot-action="enable"';
const base = {
  key: "h1:22020", name: "Hermes-4-70B", port: 22020, address: "10.0.0.5:22020",
  facts: ["LLM", "llama.cpp", "Q4_K_M", "70B", "", "39.6 GB"], place: ["Pipeline", "GPU0 · GPU1", "autostart off", ""],
  state: "running", sub: '<span data-live-cwband>6.1 t/s</span>',
  actions: { start: START, stop: STOP, configure: CFG, why: "not stopped" },
  menu: { boot: { attrs: BOOT, on: false, supported: true, title: "enable autostart" }, port: "", detail: 'data-node-detail="h1:22020"',
          del: "", delTitle: "only a stopped cell" },
  overview: { notice: "", tiles: [{ id: "speed", label: "Speed", value: "6.1 t/s", sub: "reading 30.6", live: "data-live-cwtps", liveSub: "data-live-cwtpssub" },
                                  { id: "gpu", label: "Video memory", value: "", sub: "not reported" }],
              alerts: '<span class="mbadge">⇪</span>', notes: '<div class="node-server-note model">📖 a model</div>',
              slots: '<div class="topology-runtime-panel">slots</div>', extra: "" },
  memory: { badges: '<span class="mbadge">RAM 12.2G</span>', cards: [{ name: "GPU0 · RTX 3090", figure: "22.1 GB", sub: "of 24.0 GB" }],
            rows: [{ k: "Split", v: "Pipeline" }, { k: "Empty", v: "" }], configure: CFG },
  settings: { rows: [{ k: "Context", v: "131072" }], configure: CFG, port: "", detail: 'data-node-detail="h1:22020"' },
  log: [], talk: "",
};
const win = (o = {}) => new CellWindow({ ...base, ...o }).html();
const html = (o = {}) => win(o);
// What one part of a drawn window says: the band, its button, a tab's list, a panel, the menu.
const band = (h) => (h.match(/<div class="cw-band [^"]*"[^>]*>.*?<\/div><\/div>|<div class="cw-band [^"]*"[^>]*>[\s\S]*?(?=<div class="cw-tabs")/) || [""])[0];
const action = (h) => {
  const m = h.match(/<button type="button" class="cw-act ([a-z]+)"([^>]*)>([\s\S]*?)<\/button>/);
  return m ? { cls: m[1], attrs: m[2], words: m[3].replace(/<span[^>]*><\/span>/, "") } : null;
};
const tabs = (h) => [...h.matchAll(/role="tab" class="cw-tab( on)?" aria-selected="(true|false)" data-cell-window-tab="([a-z]+)"/g)].map((m) => [m[3], m[2] === "true", !!m[1]]);
const panels = (h) => [...h.matchAll(/data-cell-window-panel="([a-z]+)" data-t="cell-window-panel" data-t-id="[^"]*"( hidden)?>/g)].map((m) => [m[1], !m[2]]);
const panel = (h, id) => { const i = h.indexOf(`data-cell-window-panel="${id}"`); if (i < 0) return null; const rest = h.slice(i); const end = rest.indexOf('data-cell-window-panel="', 10); return end > 0 ? rest.slice(0, end) : rest; };
const items = (h) => [...h.matchAll(/<button type="button" role="(menuitem|menuitemcheckbox)"( aria-checked="(true|false)")? class="cwm-item([^"]*)" ([^>]*?)data-t="cell-window-item" data-t-id="h1:22020:([a-z]+)"( title="([^"]*)")?>/g)]
  .map((m) => ({ id: m[6], role: m[1], checked: m[3] || null, cls: m[4].trim(), attrs: m[5].trim(), tip: m[8] || "" }));

const out = {};
out.en = Object.fromEntries(Object.entries(en).filter(([k]) => k.startsWith("cw") || ["start", "stop", "stoppingLabel", "removingSlotLabel", "close", "a11yCell"].includes(k)));

const running = html();
out.running = { head: running.slice(0, running.indexOf('<div class="cw-live"')), band: band(running), action: action(running), tabs: tabs(running),
                panels: panels(running), items: items(running), live: (running.match(/<div class="cw-live" data-cell-window-live="1" data-llama-port="([^"]*)">/) || [])[1] ?? null,
                callMarks: (running.match(/ data-cell-live=/g) || []).length,
                startsWithBackdrop: running.startsWith('<div class="cell-window-backdrop" data-cell-window-close="1" aria-hidden="true"></div>'),
                dialog: (running.match(/<div class="(cell-window[^"]*)" role="dialog" aria-modal="true" aria-label="([^"]*)" data-t="cell-window" data-t-id="([^"]*)">/) || []).slice(1),
                overview: panel(running, "overview"), memory: panel(running, "memory"), settings: panel(running, "settings"), log: panel(running, "log") };

// The band and its one button, state by state.
const states = ["running", "starting", "warming", "downloading", "broken", "stopped", "failed", "reserved", "stopping", "deleting", "nonsense"];
out.states = Object.fromEntries(states.map((st) => {
  const h = html({ state: st });
  return [st, { tone: (h.match(/<div class="cw-band ([a-z]+)"/) || [])[1], state: (h.match(/data-t="cell-window-band" data-t-id="h1:22020" data-t-state="([a-z]+)"/) || [])[1],
                title: (h.match(/<strong class="cw-band-title">([^<]*)</) || [])[1], action: action(h), logButton: h.includes('class="cw-band-more" data-cell-window-tab="log"') }];
}));
out.shut = {
  noStart: action(html({ state: "stopped", actions: { ...base.actions, start: "" } })),
  noStartFailed: action(html({ state: "failed", actions: { ...base.actions, start: "" } })),
  noStop: action(html({ state: "running", actions: { ...base.actions, stop: "" } })),
  reservedNoCfg: action(html({ state: "reserved", actions: { ...base.actions, configure: "" } })),
};

// The tabs: the talk only for a runner that talks, and the tab a repaint keeps.
out.tabs = {
  talk: tabs(html({ talk: '<button data-cell-talk="h1">🎙</button>' })),
  chosen: [tabs(html({ tab: "log" })), panels(html({ tab: "log" }))],
  talkChosenNoTalk: tabs(html({ tab: "talk" })),
  stranger: tabs(html({ tab: "nonsense" })),
  talkPanel: panel(html({ talk: '<button data-cell-talk="h1">🎙</button>', tab: "talk" }), "talk"),
};

// The "⋯", shut items and their reasons.
out.menu = {
  open: items(html({ menu: { ...base.menu, port: 'data-cell-port-reassign="h1:22020"', del: 'data-node-slot-del="h1:22020"', boot: { ...base.menu.boot, on: true } } })),
  unsupported: items(html({ menu: { ...base.menu, boot: { attrs: "", on: true, supported: false, title: "too old" } } }))[0],
  noAddress: items(html({ address: "" })).map((i) => i.id),
  hidden: /<div class="cwh-menu" role="menu" aria-label="[^"]*" hidden data-t="cell-window-menu" data-t-id="h1:22020">/.test(running),
};

// Panels with nothing to say say so.
const bare = html({ overview: { tiles: [] }, memory: {}, settings: {}, log: [], tab: "overview" });
out.empty = { overview: panel(bare, "overview"), memory: panel(bare, "memory"), settings: panel(bare, "settings"), log: panel(bare, "log") };
out.log = panel(html({ log: [{ tone: "bad", title: "Start failed", detail: "out of memory", hint: "Try a <smaller> quant.", raw: "cudaMalloc <failed>" },
                             { tone: "info", title: "noted" }] }), "log");
// The server's own log stands under the reported events, whatever they are.
out.logTail = [panel(html({ log: [], logTail: '<section class="cw-tail">TAIL</section>' }), "log"),
               panel(html({ log: [{ tone: "bad", title: "Start failed" }], logTail: '<section class="cw-tail">TAIL</section>' }), "log"),
               panel(html({ log: [] }), "log")];
// An overview with nothing to show says the words it was given; with anything to show, it does not.
out.overviewEmpty = {
  said: panel(html({ overview: { tiles: [], empty: "No <figures> yet" } }), "overview"),
  withNote: panel(html({ overview: { tiles: [], notes: '<div class="node-server-note">💬 kept</div>', empty: "No figures yet" } }), "overview"),
  withTile: panel(html({ overview: { tiles: [{ id: "speed", label: "Speed", value: "", sub: "" }], empty: "No figures yet" } }), "overview"),
};

// Where the model is in the caravan's own pages (1.3.660): under what is said of it, in this tab; only the links it has.
const LINKS = { models: "/models?q=Hermes%2Flms%2FQ4%2F", hf: "/hf?q=lms%2FHermes" };
out.links = {
  both: panel(html({ overview: { tiles: [], notes: '<div class="node-server-note model">📖 a model</div>', links: LINKS } }), "overview"),
  alone: panel(html({ overview: { tiles: [], links: { models: LINKS.models, hf: "" }, empty: "No figures yet" } }), "overview"),
  none: panel(html({ overview: { tiles: [], links: { models: "", hf: "" }, empty: "No figures yet" } }), "overview"),
  evil: panel(html({ key: 'h"1', overview: { tiles: [], links: { models: '/models?q="><b>', hf: "" } } }), "overview"),
};

// What is escaped, and what passes as the HTML the board made.
const evil = html({ key: '"><b>', name: "<i>x", port: '"1', address: "<u>1:2", facts: ["<s>a"], place: ["<p>b"], via: "<v>", viaTitle: 'say "hi"',
                    engine: "a b", overview: { tiles: [{ id: "<t>", label: "<l>", value: "<v>", sub: "<sub>" }] },
                    memory: { cards: [{ name: "<n>", figure: "<f>", sub: "<c>" }], rows: [{ k: "<k>", v: "<w>" }] }, log: [{ title: "<lt>", detail: "<ld>", raw: "<lr>" }] });
out.evil = evil;
out.engine = html({ engine: "ollama", via: "127.0.0.1:11434", viaTitle: 'to "Ollama"' });

// The band's words for a running cell, by the line's rule: answering, waiting, or — not told — the speed alone.
const speed = (requests, gen, running = true) => ({ requests, running, speed: running && gen > 0 ? gen : 0,
  working: running && requests !== null && requests > 0,
  words: (fmt) => (gen > 0 ? `${requests !== null && requests > 0 ? "" : "last "}${fmt(gen)} t/s` : "") });
const fmt = (n) => n.toFixed(1);
out.speedWords = {
  answering: CellWindow.speedWords(speed(1, 6.1), fmt), waiting: CellWindow.speedWords(speed(0, 6.1), fmt),
  waitingNone: CellWindow.speedWords(speed(0, 0), fmt), untold: CellWindow.speedWords(speed(null, 6.1), fmt),
  untoldNone: CellWindow.speedWords(speed(null, 0), fmt),
};
// The line under the speed figure: the prompt's speed, "no request yet" only without any speed, nothing otherwise.
out.speedSub = {
  prompt: CellWindow.speedSub(speed(0, 6.1), 30.6, fmt), speedOnly: CellWindow.speedSub(speed(1, 6.1), 0, fmt),
  none: CellWindow.speedSub(speed(0, 0), 0, fmt), promptText: CellWindow.speedSub(speed(0, 6.1), "fast", fmt),
  parked: CellWindow.speedSub(speed(null, 0, false), 0, fmt), parkedWithPrompt: CellWindow.speedSub(speed(0, 6.1, false), 30.6, fmt),
  noMetrics: CellWindow.speedSub({ ...speed(null, 0), unmeasured: true, measuredNext: false }, 0, fmt),
  noMetricsNext: CellWindow.speedSub({ ...speed(null, 0), unmeasured: true, measuredNext: true }, 0, fmt),
  noMetricsParked: CellWindow.speedSub({ ...speed(null, 0, false), unmeasured: true, measuredNext: true }, 0, fmt),
};
out.place = [CellWindow.place("sierra-pc:22001"), CellWindow.place("a:b:22001"), CellWindow.place("nokey")];
// The talk: a chat alone, a chat with the voice ways under it, the ways alone.
const CHAT = '<section class="cw-chat">CHAT</section>';
out.talkTabs = [tabs(html({ chat: CHAT })).map((x) => x[0]), tabs(html({ chat: "", talk: "" })).map((x) => x[0])];
out.talkPanels = [panel(html({ chat: CHAT, tab: "talk" }), "talk"), panel(html({ chat: CHAT, talk: '<button data-cell-talk="h1">🎙</button>', tab: "talk" }), "talk"),
                  panel(html({ talk: '<button data-cell-talk="h1">🎙</button>', tab: "talk" }), "talk")];
out.empty_ctor = new CellWindow().html();
// The settings edited in the window (cell-settings.js): the editor in place of the summary, the map in place of the placement's
// summary, and the foot after the panels.
const EDITOR = '<section class="cw-sec cws">EDITOR</section>';
const PLACE = '<div class="cw-place">MAP</div>';
const edited = html({ settings: { ...base.settings, editor: EDITOR }, memory: { ...base.memory, place: PLACE }, foot: "FOOT", footSlot: true, running: true, tab: "settings" });
const tail = (h) => h.slice(h.indexOf('<div class="cw-panels">'));
out.edited = { settings: panel(edited, "settings"), memory: panel(edited, "memory"),
               foot: (tail(edited).match(/<\/div>(<div class="cw-foot"[^>]*>[^<]*<\/div>)<\/div><\/div>$/) || [])[1] ?? null,
               footParked: (html({ footSlot: true }).match(/<div class="cw-foot"[^>]*>[^<]*<\/div>/) || [])[0] ?? null,
               noSlot: html({ foot: "FOOT" }).includes("cw-foot"), noEditor: panel(html(), "settings"), noPlace: panel(html(), "memory") };
console.log(JSON.stringify(out));
"""

node = find_node()
if node is None:
    print("js cell-window: SKIPPED — node не найден ни в PATH, ни у менеджеров версий: " + ", ".join(node_search_paths()))
    sys.exit(0)
probe = ROOT / "scripts" / ".probe_cell_window.tmp.mjs"
probe.write_text(PROBE, encoding="utf-8")
try:
    env = {"JS_ROOT": str(ROOT / "static" / "js"), "PATH": "/usr/bin:/bin",
           "JS_STUBS": "command-preview,favorites,llama-edit,form,remote-cells,cloud,topology-render,polling"}
    proc = subprocess.run(probe_args(node, ROOT / "scripts" / "_js_harness.mjs", probe), capture_output=True,
                          text=True, cwd=ROOT, env=env, timeout=60)
finally:
    probe.unlink(missing_ok=True)
if proc.returncode != 0:
    print("js cell-window: FAILED — харнесс не отработал")
    print(proc.stderr.strip()[:1200])
    sys.exit(1)
got = json.loads(proc.stdout.strip().splitlines()[-1])
en = got["en"]

print("паспорт и ✕:")
r = got["running"]
check(r["startsWithBackdrop"], "первым — затемнение доски; клик по нему закрывает окно")
check(r["dialog"] == ["cell-window cw", f'{en["a11yCell"]} :22020 Hermes-4-70B', "h1:22020"],
      f"окно — диалог «Cell :порт имя» со своим хуком (got {r['dialog']})")
check('<strong class="cwh-name">Hermes-4-70B</strong><span class="cwh-port">:22020</span>'
      '<span class="cwh-facts">LLM · llama.cpp · Q4_K_M · 70B · 39.6 GB</span>' in r["head"],
      "под именем — что она делает, чем запущена и что за файл, через « · »; negative: пустые слова выпали, двойных « ·  · » нет")
check('<button type="button" class="cwh-addr" data-cell-window-copy="10.0.0.5:22020" data-t="cell-window-copy" data-t-id="h1:22020"'
      f' title="{en["cwCopyAddress"]}"><span data-cell-window-copied>10.0.0.5:22020</span>' in r["head"],
      "адрес машины — кнопка, которая копирует его; слово на время копирования встаёт в его span")
check('<span class="cwh-place">Pipeline · GPU0 · GPU1 · autostart off</span>' in r["head"], "где считает: деление, карты, автозапуск")
check(f'data-t="cell-window-close" data-t-id="h1:22020" title="{en["close"]}" aria-label="{en["close"]}">✕</button>' in r["head"],
      "✕ со словом close и своим хуком")
check(f'data-cell-window-more="h1:22020" aria-haspopup="menu" aria-expanded="false" data-t="cell-window-more" data-t-id="h1:22020"'
      f' title="{en["cwMore"]}" aria-label="{en["cwMore"]}">' in r["head"], "«⋯» — кнопка меню, закрытого")
check(r["live"] == "22020", "полоса и панели — в контейнере живых цифр с портом ячейки (syncTopologyLive находит их там)")
check(r["callMarks"] == 0,
      "defect-history (1.3.621, до выкладки): negative — у окна (без кнопок разговора) нет ни одного data-cell-live: лента вешает живой "
      "звонок на каждый такой элемент (remote-cells.js), и обёртка с ним открывала бы звонок по клику на вкладку и глушила её")

print("полоса статуса и главная кнопка:")
st = got["states"]
tones = {k: v["tone"] for k, v in st.items()}
check(tones == {"running": "good", "starting": "busy", "warming": "busy", "downloading": "busy", "broken": "bad",
                "stopped": "idle", "failed": "bad", "reserved": "idle", "stopping": "idle", "deleting": "idle", "nonsense": "idle"},
      f"тон полосы по состоянию: работает — зелёный, в пути — жёлтый, упала или сломана — красный, остальное — тихий (got {tones})")
check(st["nonsense"]["state"] == "stopped" and st["nonsense"]["title"] == en["cwStateStopped"],
      "negative: состояние, которого нет в таблице, — «Остановлена», а не пустая полоса")
check(st["starting"]["title"] == en["cwStateStarting"] and st["warming"]["title"] == en["cwStateWarming"]
      and st["broken"]["title"] == en["cwStateBroken"], "заголовки из en.js: загрузка процесса — «Starting», прогрев — свой, сломана — с причиной")
stop_states = ["running", "starting", "warming", "downloading", "broken"]
check(all(st[k]["action"]["cls"] == "halt" and 'data-node-cell-stop="h1"' in st[k]["action"]["attrs"]
          and 'data-t-state="stop"' in st[k]["action"]["attrs"] and st[k]["action"]["words"] == en["stop"] for k in stop_states),
      "процесс жив или в пути (и сломан — тоже) — одна кнопка «Stop» с атрибутами ⏹ карточки")
check(st["stopped"]["action"]["cls"] == "go" and 'data-node-cell-launch="h1"' in st["stopped"]["action"]["attrs"]
      and st["stopped"]["action"]["words"] == en["start"], "остановлена — «Start» с атрибутами ▶ карточки (имя модели для вопроса)")
check(st["failed"]["action"]["words"] == en["cwStartAgain"] and 'data-node-cell-launch="h1"' in st["failed"]["action"]["attrs"],
      "упала — «Start again», та же ▶")
check(st["reserved"]["action"]["words"] == en["cwChooseModel"] and 'data-node-cell-start="h1"' in st["reserved"]["action"]["attrs"]
      and 'data-t-state="configure"' in st["reserved"]["action"]["attrs"], "зарезервирована — «Pick a model»: открывает форму ячейки")
check(st["stopping"]["action"]["cls"] == "busy" and "disabled" in st["stopping"]["action"]["attrs"]
      and st["stopping"]["action"]["words"] == en["stoppingLabel"] and st["deleting"]["action"]["words"] == en["removingSlotLabel"],
      "останавливается и удаляется — кнопка закрыта и крутится, со словами карточки")
check(st["failed"]["logButton"] and st["broken"]["logButton"] and not st["running"]["logButton"] and not st["stopped"]["logButton"],
      "у упавшей и сломанной на полосе — «Журнал», ведущий во вкладку; negative: у работающей и стоящей его нет")
sh = got["shut"]
check(sh["noStart"]["cls"] == "go" and "disabled" in sh["noStart"]["attrs"] and 'title="not stopped"' in sh["noStart"]["attrs"]
      and 'data-t-state="shut"' in sh["noStart"]["attrs"] and "data-node-cell-launch" not in sh["noStart"]["attrs"],
      "negative: стоящая, которой нельзя стартовать сейчас, — «Start» закрыт, с причиной карточки в подсказке, без атрибутов ▶")
check(sh["noStartFailed"]["words"] == en["cwStartAgain"] and "disabled" in sh["noStartFailed"]["attrs"], "negative: то же у упавшей — «Start again», закрыто")
check(sh["noStop"]["cls"] == "halt" and sh["noStop"]["words"] == en["stop"] and "disabled" in sh["noStop"]["attrs"]
      and 'title="not stopped"' in sh["noStop"]["attrs"] and 'data-t-state="shut"' in sh["noStop"]["attrs"]
      and "data-node-cell-stop" not in sh["noStop"]["attrs"] and "spinner" not in str(sh["noStop"]),
      "defect-history (1.3.621, до выкладки): живая, у которой ⏹ сейчас нет (старт только что попросили), — «Stop» закрыт, с причиной "
      "строки в подсказке; negative: не крутящееся «STOPPING…» — ячейка не останавливается, она запускается")
check(sh["reservedNoCfg"] is None, "negative: зарезервирована и форму не открыть — кнопки нет совсем")

print("вкладки:")
check(r["tabs"] == [["overview", True, True], ["memory", False, False], ["settings", False, False], ["log", False, False]],
      f"четыре вкладки, первая выбрана; negative: «Разговор» не рисуется у раннера, который не говорит (got {r['tabs']})")
check(r["panels"] == [["overview", True], ["memory", False], ["settings", False], ["log", False]], "видна только панель выбранной вкладки")
tb = got["tabs"]
check([x[0] for x in tb["talk"]] == ["overview", "memory", "settings", "log", "talk"], "раннер говорит — пятая вкладка «Разговор»")
check(tb["chosen"][0][3] == ["log", True, True] and tb["chosen"][1][3] == ["log", True] and tb["chosen"][1][0] == ["overview", False],
      "выбранная вкладка (CardFold.windowTab) переживает перерисовку: открыта она, обзор скрыт")
check(tb["talkChosenNoTalk"][0] == ["overview", True, True] and tb["stranger"][0] == ["overview", True, True],
      "negative: выбрана вкладка, которой у ячейки нет (разговор без голоса, мусор), — открывается обзор")
check(en["cwTalkLead"] in tb["talkPanel"] and '<button data-cell-talk="h1">🎙</button>' in tb["talkPanel"],
      "во вкладке «Разговор» — строка о ней и кнопки голоса, как их нарисовала доска")

print("меню «⋯»:")
mn = got["menu"]
check(mn["hidden"], "меню нарисовано закрытым")
ids = [i["id"] for i in mn["open"]]
check(ids == ["boot", "copy", "port", "detail", "delete"], f"пункты по порядку: автозапуск, адрес, порт, команда, удаление (got {ids})")
boot = mn["open"][0]
check(boot["role"] == "menuitemcheckbox" and boot["checked"] == "true" and 'data-node-cell-boot="h1"' in boot["attrs"]
      and boot["tip"] == "enable autostart", "автозапуск — пункт-флажок с атрибутами ↥ карточки и её подсказкой")
check(mn["unsupported"]["checked"] == "false" and mn["unsupported"]["attrs"] == "disabled" and mn["unsupported"]["tip"] == "too old",
      "negative: скаут не умеет автозапуск — флажок снят (не «вкл» без поддержки), пункт закрыт, причина в подсказке")
dele = mn["open"][4]
check("cwm-danger" in dele["cls"] and 'data-node-slot-del="h1:22020"' in dele["attrs"], "удаление — красный пункт с атрибутами ✕ карточки")
shut = {i["id"]: i for i in got["running"]["items"]}
check(shut["port"]["attrs"] == "disabled" and shut["port"]["tip"] == en["cwPortOnlyParked"]
      and shut["delete"]["attrs"] == "disabled" and shut["delete"]["tip"] == "only a stopped cell",
      "negative: работающей нельзя ни переехать, ни удалиться — пункты остаются закрытыми и говорят почему, а не исчезают")
check("copy" not in mn["noAddress"], "negative: адреса нет — нет и пункта «скопировать адрес»")

print("панели:")
ov = r["overview"]
check('data-t="cell-window-tile" data-t-id="h1:22020:speed"' in ov and '<span class="cw-tile-value" data-live-cwtps>6.1 t/s</span>' in ov
      and '<span class="cw-tile-sub" data-live-cwtpssub>reading 30.6</span>' in ov,
      "плитка скорости — число и его строка с метками живого патча")
check('data-t-id="h1:22020:gpu"' in ov and '<span class="cw-tile-value">—</span><span class="cw-tile-sub">not reported</span>' in ov,
      "negative: значения нет — «—» и причина под ним, а не пустая плитка и не 0")
check(f'<h4 class="cw-sec-title">{en["cwAlerts"]}</h4><div class="cw-chips"><span class="mbadge">⇪</span></div>' in ov
      and f'<h4 class="cw-sec-title">{en["cwAboutModel"]}</h4><div class="node-server-note model">' in ov
      and '<div class="topology-runtime-panel">slots</div>' in ov, "обзор: что стоит знать, описание модели, слоты — как их нарисовала доска")
lk = got["links"]
check(f'<h4 class="cw-sec-title">{en["cwAboutModel"]}</h4><div class="node-server-note model">📖 a model</div>'
      '<div class="cw-buttons cw-links">'
      '<a class="cw-btn cw-link" href="/models?q=Hermes%2Flms%2FQ4%2F" data-t="cell-window-link" '
      f'data-t-id="h1:22020:models">{en["cwModelInLibrary"]}</a>'
      '<a class="cw-btn cw-link" href="/hf?q=lms%2FHermes" data-t="cell-window-link" '
      f'data-t-id="h1:22020:hf">{en["cwModelOnHf"]}</a></div>' in lk["both"],
      "1.3.660 (владелец, 2026-10-26: «ссылку на модель в нашем хранилище и ещё на нашу страницу в HF»): под тем, что сказано о "
      "модели, — две ссылки; negative: не в новой вкладке — всё в караване открывается в этой же (check_same_tab_links.py)")
check(f'<h4 class="cw-sec-title">{en["cwAboutModel"]}</h4><div class="cw-buttons cw-links">' in lk["alone"]
      and "cwModelOnHf" not in lk["alone"] and 'data-t-id="h1:22020:hf"' not in lk["alone"] and "No figures yet" not in lk["alone"],
      "только хранилище (у пути нет репозитория) — одна ссылка, и секция стоит без описания; negative: ссылки на HF нет, "
      "«нечего показать» не сказано")
check("cw-links" not in lk["none"] and en["cwAboutModel"] not in lk["none"] and "No figures yet" in lk["none"],
      "negative: ссылок нет — ни пустой строки ссылок, ни пустой секции")
check('href="/models?q=&quot;&gt;&lt;b&gt;"' in lk["evil"] and 'data-t-id="h&quot;1:models"' in lk["evil"] and "<b>" not in lk["evil"],
      "адрес и ключ экранированы")
me = r["memory"]
check('<span class="cw-mem-name">GPU0 · RTX 3090</span><span class="cw-mem-figure">22.1 GB</span><span class="cw-mem-sub">of 24.0 GB</span>' in me
      and '<dt>Split</dt><dd>Pipeline</dd>' in me and "<dt>Empty</dt>" not in me,
      "память: что держит каждая карта и размещение из настроек; negative: пустое поле размещения не рисуется строкой")
check('data-t="cell-window-button" data-t-id="h1:22020:placement">' + en["cwPlacementEdit"] in me and 'data-node-cell-start="h1"' in me,
      "«Изменить размещение…» открывает форму ячейки")
se = r["settings"]
check("<dt>Context</dt><dd>131072</dd>" in se and en["cwSettingsLead"] in se
      and 'data-t-id="h1:22020:configure">' + en["cwSettingsOpen"] in se and 'data-t-id="h1:22020:detail">' + en["cwDetails"] in se
      and "h1:22020:port" not in se, "настройки: главное, «все настройки», команда; negative: порта нет — нет и его кнопки")
check(en["cwLogEmpty"] in r["log"], "журнал без записей так и говорит")
em = got["empty"]
check(en["cwHeldNothing"] in em["memory"] and en["cwPlacementDefault"] in em["memory"] and "cell-window-button" not in em["memory"],
      "negative: памяти и размещения не сказано — так и написано, кнопки без действия нет")
check(esc(en["cwSettingsNone"]) in em["settings"] and esc(en["cwSettingsShut"]) in em["settings"] and "cell-window-button" not in em["settings"],
      "negative: форму не открыть — сказано почему, кнопок нет")
check("cw-tiles" not in em["overview"] and "cw-sec" not in em["overview"], "negative: обзор без цифр и заметок не рисует пустых рамок")
lg = got["log"]
check('<div class="cw-ev bad"><strong class="cw-ev-title">Start failed</strong><span class="cw-ev-detail">out of memory</span>'
      '<span class="cw-ev-detail">Try a &lt;smaller&gt; quant.</span>'
      '<pre class="cw-ev-raw">cudaMalloc &lt;failed&gt;</pre></div>' in lg and '<div class="cw-ev info"><strong class="cw-ev-title">noted</strong></div>' in lg,
      "запись журнала: заголовок, пояснение, совет своей строкой, сырые строки — экранированы; без пояснения — без пустых полей "
      "(defect-history 1.3.621, до выкладки: причина и совет склеивались без точки)")
lt = got["logTail"]
check(lt[0].index(en["cwLogEmpty"]) < lt[0].index('<section class="cw-tail">TAIL</section>')
      and lt[1].index("Start failed") < lt[1].index('<section class="cw-tail">TAIL</section>') and "cw-tail" not in lt[2],
      "журнал сервера (cell-log.js) — под событиями: и под «записей нет», и под записями; negative: не дали — нет и его")
oe = got["overviewEmpty"]
check('<p class="cw-empty">No &lt;figures&gt; yet</p>' in oe["said"], "обзор, которому нечего показать, говорит данные ему слова — экранированными")
check("cw-empty" not in oe["withNote"] and "💬 kept" in oe["withNote"] and "cw-empty" not in oe["withTile"],
      "negative: есть заметка или плитка — пустых слов нет")

print("экранирование и движок:")
ev = got["evil"]
check(all(x not in ev for x in ['"><b>', "<i>x", "<u>", "<s>a", "<p>b", "<v>", "<l>", "<sub>", "<n>", "<f>", "<k>", "<w>", "<lt>", "<ld>", "<lr>", '"hi"']),
      "имя, порт, ключ, адрес, факты, место, движок, плитки, карты, строки и журнал экранируются")
check('class="cell-window cw" role="dialog"' in ev, "negative: слово, не годное в класс движка, класса не даёт")
check('<div class="cell-window cw engine-ollama" role="dialog"' in got["engine"]
      and '<span class="cwh-via" data-t="cell-window-via" title="to &quot;Ollama&quot;">→ 127.0.0.1:11434</span>' in got["engine"],
      "ячейка в движке — в его цвет; после адреса — куда идут запросы, подсказка экранирована")
check('aria-label="' + en["a11yCell"] + ' :"' in got["empty_ctor"] and 'data-t-state="stopped"' in got["empty_ctor"],
      "пустое окно не падает: подпись без имени, состояние «стоит»")

check(got["place"] == [{"hostId": "sierra-pc", "port": "22001"}, {"hostId": "a:b", "port": "22001"}, {"hostId": "", "port": ""}],
      "ключ ячейки — машина и порт по последнему «:» (журнал и чат окна спрашивают по ним); negative: без «:» — ничего")
tt, tp = got["talkTabs"], got["talkPanels"]
check(tt[0][-1] == "talk" and "talk" not in tt[1], "чат — уже повод для вкладки «Разговор»; negative: ни чата, ни кнопок — вкладки нет")
check('<section class="cw-chat">CHAT</section>' in tp[0] and en["cwTalkLead"] not in tp[0]
      and tp[1].index("CHAT") < tp[1].index('<div class="cw-talk-ways">') and en["cwTalkLead"] in tp[1]
      and "CHAT" not in tp[2] and en["cwTalkLead"] in tp[2],
      "сначала чат, под ним — голос, звонок и страница, если раннер их умеет; negative: без кнопок — без строки о них")

print("слова полосы у работающей (правило строки, cell-speed.js):")
sw = got["speedWords"]
check(sw["answering"] == f'{en["cwAnswering"]} · 6.1 t/s' and sw["waiting"] == f'{en["cwWaiting"]} · last 6.1 t/s'
      and sw["waitingNone"] == en["cwWaiting"], "отвечает · скорость; ждёт · последняя скорость; ждёт — без скорости, если её не было")
check(sw["untold"] == "last 6.1 t/s" and sw["untoldNone"] == "",
      "negative: сервер не говорит, сколько запросов, — ни «отвечает», ни «ждёт»: только скорость, а без неё — ничего")

print("строка под скоростью:")
ss = got["speedSub"]
check(ss["prompt"] == en["cwPromptSpeed"].replace("{tps}", "30.6"), "сервер сказал скорость чтения запроса — она и написана")
check(ss["speedOnly"] == "" and ss["promptText"] == "",
      "defect-history (1.3.621, до выкладки): скорость есть, скорости чтения нет — строка пуста; negative: не «запросов ещё не было» "
      "под замеренной скоростью, и текст вместо числа скоростью не считается")
check(ss["none"] == en["cwSpeedNone"], "ни одной скорости — «запросов ещё не было»")
check(ss["noMetrics"] == en["cwSpeedNoMetrics"] and ss["noMetricsNext"] == en["cwSpeedNoMetricsNext"],
      "defect-history (Гермес, 2026-10-26): сервер не отдаёт метрики — «не измеряется», а не «запросов ещё не было»; и если следующий "
      "запуск их даст — так и сказано")
check(ss["noMetricsParked"] == en["cwNotRunning"], "negative: ячейка не работает — сказано это, а не про метрики")
check(ss["parked"] == en["cwNotRunning"] and ss["parkedWithPrompt"] == en["cwNotRunning"],
      "negative: ячейка не работает — так и сказано, даже если последний отчёт нёс скорость чтения")

print("настройки, правленые в окне:")
ed = got["edited"]
check(('<section class="cw-sec cws">EDITOR</section><div class="cw-buttons cw-set-more">'
                              f'<button type="button" class="cw-btn" {CFG} data-t="cell-window-button" data-t-id="h1:22020:configure">{en["cwSettingsOpen"]}</button>'
                              f'<button type="button" class="cw-btn" data-node-detail="h1:22020" data-t="cell-window-button" data-t-id="h1:22020:detail">{en["cwDetails"]}</button></div></div>') in ed["settings"]
      and "cw-rows" not in ed["settings"] and en["cwSettingsLead"] not in ed["settings"],
      "редактор полей стоит во вкладке вместо сводки «главного» и её слов; под ним — все настройки и команда (порт закрыт — его кнопки нет)")
check('<section class="cw-sec"><div class="cw-place">MAP</div></section>' in ed["memory"] and en["cwPlacement"] not in ed["memory"]
      and "cw-rows" not in ed["memory"] and en["cwPlacementEdit"] not in ed["memory"]
      and f'data-t-id="h1:22020:placement">{en["cwSettingsOpen"]}</button>' in ed["memory"],
      "negative: при карте сводки сохранённого размещения нет — пока не применено, она рассказывала бы другое; заголовка секции "
      "тоже нет — карта называет себя сама; где считать — в полных настройках")
check(ed["foot"] == '<div class="cw-foot" data-cell-window-foot="h1:22020" data-running="1">FOOT</div>',
      "подвал — после панелей, не прокручивается с ними; знает, что ячейка работает")
check(ed["footParked"] == '<div class="cw-foot" data-cell-window-foot="h1:22020" data-running=""></div>',
      "место подвала есть и пустым, пока не применять нечего; не работает — пусто")
check(ed["noSlot"] is False and "cw-rows" in ed["noEditor"] and "cw-rows" in ed["noPlace"],
      "negative: окно не правит настройки — подвала нет вовсе, а вкладки показывают сводки, как раньше")

print()
if _fail:
    print(f"js cell-window FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m.splitlines()[0])
    sys.exit(1)
print("js cell-window OK: полоса, кнопка, меню, вкладки, панели и экранирование окна — значениями")
