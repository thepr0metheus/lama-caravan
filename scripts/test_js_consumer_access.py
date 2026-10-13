#!/usr/bin/env python3
"""Snapshot of static/js/consumer-access.js — how a consumer reaches the caravan,
as the kanban's clients panel shows it (2026-10-07).

A consumer's line says what it has — a key (its last four characters), the
entry only or its port still open, when it last called — and offers the one
action it lacks: a key, closing the port, reopening it. The panel's head says
the entry's address, or that the entry is off. The actions ask first, call the
controller and draw the board it answers; a refusal is said, not swallowed.

Pinned by value, with the module loaded for real (scripts/_js_harness.mjs);
dialogs and the board's render are stubbed, the controller and the clipboard
are stand-ins passed to the class. Strings come from en.js, not from memory.

Run: python3 scripts/test_js_consumer_access.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

# The module's own neighbours (dialogs, the board's render) and the heavy modules the
# i18n chain would pull in through form.js (the canvas wires a MutationObserver at import).
STUBS = ("dialogs,topology-render,polling,remote-cells,topology-dnd,canvas,charts,cables,history,favorites,"
         "config-locator,system-panels,onboarding,onboarding-tours,dialog-llamas,models-page,system-page,memory,"
         "command-preview,llama-edit,topology-nodes,topology-modals,topology-activity,topology-proxies,routers,cloud")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const m = await import(pathToFileURL(process.env.JS_ROOT + "/consumer-access.js").href);
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const fill = (s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => v[k]);
const NOW = Date.UTC(2026, 9, 7, 15, 0, 0);
const TOPO = () => ({ proxies: [
    { id: "skynet:proxy:23001", port: 23001, label: "hermes primary", keyTail: "a1b2", portClosed: true, lastRequestAt: NOW / 1000 - 600 },
    { id: "skynet:proxy:8022", port: 8022, label: "promie-ui", keyTail: "9f3c", lastRequestAt: Date.UTC(2026, 9, 5, 9, 30) / 1000 },
    { id: "skynet:proxy:23009", port: 23009, label: "social-media-viewer port", keyTail: "" }],
  entry: { url: "https://caravan-api.example/v1", port: 23999 }, clients: [], routers: [], assignments: {} });
const desk = (over = {}) => {
  const log = { asks: [], calls: [], notes: [], applied: [], copied: [], prompts: [] };
  const answers = [...(over.answers || [true, true])];
  const typed = [...(over.prompts || [])];
  const d = new m.ConsumerAccess({
    confirm: async (text, opts) => { log.asks.push([text, opts]); return answers.length ? answers.shift() : true; },
    ask: async (text, opts) => { log.prompts.push([text, opts]); return typed.length ? typed.shift() : null; },
    call: async (path, o) => {
      log.calls.push(o ? [path, JSON.parse(o.body)] : [path]);
      if (over.fail) throw new Error("controller is down");
      if (path === "/api/topology") return over.top || { marker: "fresh" };
      if (path === "/api/agent-proxy-entry" && over.entryFails) throw new Error("port 23999 is already the fleet's");
      return "res" in over ? over.res : { ok: true };
    },
    notify: (x) => log.notes.push(x), copy: async (x) => { log.copied.push(x); return over.copyFails ? false : true; },
    apply: (top) => { log.applied.push(top); if (over.adopt) st.setTopology(top); }, now: () => NOW });
  return [d, log];
};
const reset = () => { st.setTopology(TOPO()); };
reset();
const out = {};
"""

PINS = [
    ("line_without_a_key",
     '',
     '(() => { const [d] = desk(); const h = d.lineHtml(st.topology.proxies[2]); return [h.includes(en.consumerNoKey), h.includes(\'data-t-state="none"\'),'
     ' h.includes(\'class="cv-in-port-num">:23009<\'), h.includes(\'data-cv-port-key="23009"\'), h.includes(">" + en.consumerGiveKey + "<"), h.includes("🔑")]; })()',
     '[true,true,true,true,true,false]',
     "без ключа: «нет ключа», номер порта и «Выдать ключ»; negative: значка ключа нет"),
    ("line_entry_only",
     '',
     '(() => { const [d] = desk(); const h = d.lineHtml(st.topology.proxies[0]); return [h.includes("🔑 …a1b2"), h.includes(\'data-t-state="entry"\'), h.includes(">" + en.consumerEntryOnly + "<"),'
     ' h.includes(\'data-cv-port-reopen="23001"\'), h.includes(fill(en.consumerReopenTitle, { port: "23001" })), h.includes("data-cv-port-close"), h.includes("cv-in-port-num")]; })()',
     '[true,true,true,true,true,false,false]',
     "порт закрыт: последние 4 знака ключа и «только вход», ↺ — открыть снова; negative: ни «Закрыть порт», ни номера порта"),
    ("line_key_and_open_port",
     '',
     '(() => { const [d] = desk(); const open = d.lineHtml(st.topology.proxies[1]);'
     ' return [open.includes("🔑 …9f3c"), open.includes(">" + fill(en.consumerPortOpen, { port: "8022" }) + "<"), open.includes(\'data-cv-port-close="8022"\'),'
     ' open.includes(\'data-t-state="open"\'), open.includes("data-cv-port-key")]; })()',
     '[true,true,true,true,false]',
     "ключ был и раньше, порт открыт: «порт :8022 открыт» и «Закрыть порт»; negative: «Выдать ключ» не предлагается"),
    ("seen_today_another_day_never",
     '',
     '(() => { const [d] = desk(); const today = d.seenHtml(NOW / 1000 - 600); const before = d.seenHtml(Date.UTC(2026, 9, 5, 9, 30) / 1000);'
     ' return [today.includes("· " + new Date(NOW - 600000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })),'
     ' before.includes("· " + new Date(Date.UTC(2026, 9, 5, 9, 30)).toLocaleDateString([], { day: "numeric", month: "short" })), d.seenHtml(0), d.seenHtml(undefined)]; })()',
     '[true,true,"",""]',
     "когда звонил: сегодня — время, раньше — день; negative: запроса нет в журнале — ничего, а не «никогда»"),
    ("entry_line_on_and_off",
     '',
     '(() => { const [d] = desk(); const on = d.entryHtml(st.topology.entry); const off = d.entryHtml({ url: "", port: null }); const none = d.entryHtml(undefined);'
     ' const nameless = d.entryHtml({ url: "", port: 23999 });'
     ' return [on.includes(">caravan-api.example/v1<"), on.includes("data-cv-entry-copy"), on.includes(\'data-t-state="on"\'), on.includes(\'data-cv-entry-setup\') && on.includes(en.consumerEntryEdit.replaceAll("\'", "&#39;")),'
     ' off.includes(">" + en.consumerEntryOff + "<") && off.includes(\'data-t-state="off"\'), off.includes("data-cv-entry-copy"), off.includes(">" + en.consumerEntrySetup + "<"), none === off,'
     ' nameless.includes(fill(en.consumerEntryNoName, { port: "23999" })) && nameless.includes(\'data-t-state="nameless"\') && nameless.includes("data-cv-entry-setup")]; })()',
     '[true,true,true,true,true,false,true,true,true]',
     "строка входа: адрес без схемы, копирование и ✎; negative: вход выключен — так и сказано, копировать нечего, а «Настроить вход» есть (раньше путь кончался тут); "
     "нет сведений — то же; порт есть, а имени нет там, где до порта достаёт только эта машина, — сказано и это"),
    ("entry_off_says_why",
     '',
     '(() => { const [d] = desk(); const off = d.entryHtml({ url: "", port: null }); const nameless = d.entryHtml({ url: "", port: 23999 }); const on = d.entryHtml(st.topology.entry);'
     ' const why = \'data-t="kanban-entry-why">\' + en.consumerEntryWhy.replaceAll("\'", "&#39;") + "<";'
     ' return [off.includes(why), nameless.includes(why), on.includes("kanban-entry-why"), off.includes(\'title="\' + en.consumerEntryOffTitle.replaceAll("\'", "&#39;") + \'"\')]; })()',
     '[true,true,false,true]',
     "вход выключен или без имени — под строкой сказано, зачем вход: один адрес и свой ключ у каждого клиента, как в OpenAI "
     "(«The entry is off» одно ничего не объясняло, 2026-10-11); negative: включённый вход пояснения не повторяет"),
    ("entry_line_shows_port_and_off",
     '',
     '(() => { const [d] = desk(); const on = d.entryHtml(st.topology.entry); const own = d.entryHtml({ url: "http://10.0.30.20:23999/v1", port: 23999 });'
     ' const nameless = d.entryHtml({ url: "", port: 23999 }); const off = d.entryHtml({ url: "", port: null }); const tag = \'data-t="kanban-entry-port"\';'
     ' return [on.includes(tag) && on.includes(">" + fill(en.consumerEntryPort, { port: "23999" }) + "<"),'
     ' on.includes(\'title="\' + fill(en.consumerEntryPortTitle, { port: "23999" }) + \'"\'),'
     ' on.includes(\'data-cv-entry-off data-t="kanban-entry-off" title="\' + en.consumerEntryTurnOff + \'"\') && on.indexOf("data-cv-entry-off") > on.indexOf("data-cv-entry-setup"),'
     ' own.includes(tag), own.includes("data-cv-entry-off"), nameless.includes("data-cv-entry-off"), nameless.includes(tag), off.includes("data-cv-entry-off")]; })()',
     '[true,true,true,false,true,true,false,false]',
     "строка входа называет порт — его ждёт правило обратного прокси (раньше порт был виден только во втором окне ✎); ✕ — последней кнопкой; "
     "negative: адрес сам называет порт — второй раз не пишется; без имени порт уже в тексте; вход выключен — выключать нечего, ✕ нет"),
    ("entry_off_asks_then_turns_off",
     '',
     'await (async () => { const [d, log] = desk({ res: { ok: true, port: null, publicUrl: "" }, top: { marker: "fresh" } }); const r = await d.turnOffEntry();'
     ' return [log.asks[0][0] === fill(en.entryOffText, { port: "23999" }), log.asks[0][1].title === en.entryOffAsk, log.asks[0][1].danger,'
     ' log.asks[0][1].confirmLabel === en.entryOffConfirm, log.calls, log.applied, log.notes, r.ok]; })()',
     '[true,true,true,true,[["/api/agent-proxy-entry",{"port":0,"publicUrl":""}],["/api/topology"]],[{"marker":"fresh"}],["The entry is off"],true]',
     "✕: окно спрашивает и называет порт, который закроется; кнопка «Turn off»; запрос — порт 0 и пустой адрес; доска перечитана; тост «вход выключен»"),
    ("entry_off_cancel_refusal_nothing_to_turn_off",
     '',
     'await (async () => { const [a, la] = desk({ answers: [false] }); const ra = await a.turnOffEntry(); const [b, lb] = desk({ entryFails: true }); const rb = await b.turnOffEntry();'
     ' st.setTopology({ ...st.topology, entry: { url: "", port: null } }); const [c, lc] = desk(); const rc = await c.turnOffEntry();'
     ' return [ra, la.calls.length, rb, lb.calls.length, lb.notes, lb.applied.length, rc, lc.asks.length + lc.calls.length]; })()',
     '[null,0,null,1,["port 23999 is already the fleet\'s"],0,null,0]',
     "negative: «отмена» — запроса нет; отказ контроллера (есть клиенты входа) — его слова, доска не перечитывается; вход и так выключен — ни окна, ни запроса"),
    ("give_a_key_asks_then_shows_it",
     '',
     'await (async () => { const [d, log] = desk({ res: { ok: true, port: 23009, key: "lcv1_" + "c".repeat(48), entryUrl: "https://caravan-api.example/v1", topology: { marker: 1 } } });'
     ' const r = await d.giveKey("23009");'
     ' return [log.asks[0][0] === fill(en.consumerGiveKeyText, { name: "social-media-viewer port", port: "23009", address: "https://caravan-api.example/v1" }) && log.asks[0][1].danger, log.calls,'
     ' log.applied, log.asks[1][0] === fill(en.consumerKeyGivenText, { name: "social-media-viewer port", key: "lcv1_" + "c".repeat(48), address: "https://caravan-api.example/v1" }),'
     ' log.asks[1][1].confirmLabel === en.consumerCopyKey, log.copied, log.notes, !!r]; })()',
     '[true,[["/api/agent-proxies/route-key",{"port":23009}]],[{"marker":1}],true,true,["lcv1_cccccccccccccccccccccccccccccccccccccccccccccccc"],["Key copied"],true]',
     "«Выдать ключ»: вопрос говорит, что порт закроется сразу и куда теперь ходить; ключ делает контроллер; окно показывает ключ и адрес, копирует по слову"),
    ("give_a_key_says_no_and_fails_safe",
     '',
     'await (async () => { const [a, la] = desk({ answers: [false] }); const ra = await a.giveKey("23009");'
     ' const [b, lb] = desk({ fail: true }); const rb = await b.giveKey("23009");'
     ' const [c, lc] = desk({ answers: [true, false], res: { key: "lcv1_x", entryUrl: "https://caravan-api.example/v1" } }); await c.giveKey("23009");'
     ' st.setTopology({ ...st.topology, entry: { url: "", port: null } }); const [e, le] = desk(); const re = await e.giveKey("23009");'
     ' return [ra, la.calls.length, rb, lb.notes, lb.asks.length, lc.copied, re, le.asks.length + le.calls.length, le.notes[0] === en.entryNeedsSetupFirst, le.prompts.length]; })()',
     '[null,0,null,["controller is down"],1,[],null,0,true,1]',
     "negative: «отмена» — ничего не шлёт; отказ — тост с причиной, второго окна нет; «Готово» — ключ не копируется; "
     "вход выключен — сначала спрашивается вход (раньше — тупик «вход выключен»); его отменили — ни вопроса о ключе, ни запроса"),
    ("no_key_is_red_only_without_a_door",
     '',
     '(() => { const [d] = desk(); const p = st.topology.proxies[2]; const states = [true, null, false].map((reach) => { st.setTopology({ ...st.topology, portsReachable: reach });'
     ' return d.lineHtml(p).includes(\'class="cv-in-key none quiet"\') ? "quiet" : "red"; }); reset(); return states; })()',
     '["quiet","quiet","red"]',
     "«нет ключа» красным только там, где у портов нет двери (клиенту не войти); где порт открыт — это норма, серым; дверь не известна — тоже серым"),
    ("entry_setup_asks_address_then_port",
     '',
     'await (async () => { st.setTopology({ ...st.topology, entry: { url: "", port: null } });'
     ' const [d, log] = desk({ prompts: ["https://caravan-api.example/v1 ", " 23999"], res: { ok: true, port: 23999, publicUrl: "https://caravan-api.example/v1" }, top: { marker: "fresh" } });'
     ' const r = await d.setupEntry("caravan.example.org"); reset();'
     ' return [log.prompts.map(([text, o]) => [text === en.entryAddressAsk || text === en.entryPortAsk, o.title === undefined && (o.text === en.entryAddressText || o.text === en.entryPortText), o.value, o.placeholder]), log.calls, log.applied,'
     ' log.notes[0] === fill(en.entrySaved, { port: "23999", url: "https://caravan-api.example/v1" }), r.port]; })()',
     '[[[true,true,"","https://caravan-api.example.org/v1"],[true,true,"","23999"]],[["/api/agent-proxy-entry",{"port":23999,"publicUrl":"https://caravan-api.example/v1"}],["/api/topology"]],[{"marker":"fresh"}],true,23999]',
     "«Настроить вход»: адрес, потом порт — вопрос в заголовке окна (общий заголовок его закрывал), пояснение под ним; подсказаны имя доски с -api и 23999; пробелы срезаны; контроллер открывает вход, доска берёт свежую топологию и говорит, что вход включён"),
    ("entry_setup_asks_back_what_is_set",
     '',
     'await (async () => { st.setTopology({ ...st.topology, entry: { url: "https://caravan-api.example/v1", port: 23999, publicUrl: "https://caravan-api.example/v1" } });'
     ' const [d, log] = desk({ prompts: [null] }); const r = await d.setupEntry("10.0.30.20"); reset(); return [log.prompts[0][1].value, log.prompts[0][1].placeholder, log.prompts.length, log.calls, r]; })()',
     '["https://caravan-api.example/v1","",1,[],null]',
     "✎ спрашивает введённое имя (а не адрес, собранный из порта); доска по IP — имя не подсказывается; negative: «отмена» на адресе — ни второго вопроса, ни запроса"),
    ("entry_setup_cancel_off_and_refusal",
     '',
     'await (async () => { const [a, la] = desk({ prompts: ["https://x.example/v1", null] }); const ra = await a.setupEntry("c.example");'
     ' const [b, lb] = desk({ prompts: ["", ""], res: { ok: true, port: null, publicUrl: "" } }); await b.setupEntry("c.example");'
     ' const [c, lc] = desk({ prompts: ["https://x.example/v1", "23999"], entryFails: true }); const rc = await c.setupEntry("c.example");'
     ' return [ra, la.calls.length, lb.calls[0], lb.notes, rc, lc.calls.length, lc.notes]; })()',
     '[null,0,["/api/agent-proxy-entry",{"port":0,"publicUrl":""}],["The entry is off"],null,1,["port 23999 is already the fleet\'s"]]',
     "negative: «отмена» на порту — запроса нет; пустой порт — вход выключается, и так и сказано; отказ контроллера — его слова, топология не запрашивается"),
    ("give_a_key_goes_on_after_the_entry_is_set",
     '',
     'await (async () => { st.setTopology({ ...st.topology, entry: { url: "", port: null } });'
     ' const top = { ...TOPO(), entry: { url: "https://caravan-api.example/v1", port: 23999 } };'
     ' const [d, log] = desk({ adopt: true, top, prompts: ["https://caravan-api.example/v1", "23999"], answers: [false], res: { ok: true, port: 23999, publicUrl: "https://caravan-api.example/v1" } });'
     ' const r = await d.giveKey("23009"); reset();'
     ' return [log.notes[0] === en.entryNeedsSetupFirst, log.prompts.length, log.asks.length, log.asks[0][0] === fill(en.consumerGiveKeyText, { name: "social-media-viewer port", port: "23009", address: "https://caravan-api.example/v1" }), r]; })()',
     '[true,2,1,true,null]',
     "вход настроен из «Выдать ключ» — тот же нажим продолжается вопросом о ключе с новым адресом входа (ответ «нет» — ключа нет)"),
    ("suggested_address_is_the_boards_name_with_api",
     '',
     '["caravan.example.org", "board.example.org", "10.0.30.20", "localhost", "", "[::1]"].map((h) => m.ConsumerAccess.suggestedAddress(h))',
     '["https://caravan-api.example.org/v1","https://board-api.example.org/v1","","","",""]',
     "подсказка адреса входа — имя доски с -api (два имени владельца: доска и вход); negative: IP, имя без точки, пусто — подсказки нет"),
    ("close_port_names_the_entry",
     '',
     'await (async () => { const [d, log] = desk(); await d.closePort("8022");'
     ' return [log.asks[0][0] === fill(en.consumerCloseText, { name: "promie-ui", port: "8022", address: "https://caravan-api.example/v1" }),'
     ' log.asks[0][1].danger, log.calls, log.applied, log.notes]; })()',
     '[true,true,[["/api/agent-proxies/route-policy",{"port":8022,"portClosed":true}],["/api/topology"]],[{"marker":"fresh"}],["Port :8022 closed — the entry only"]]',
     "«Закрыть порт»: вопрос называет адрес, куда агент должен уже ходить; запрос — закрыть; доска перечитана"),
    ("close_port_says_no_and_fails_safe",
     '',
     'await (async () => { const [a, la] = desk({ answers: [false] }); const ra = await a.closePort("8022"); const [b, lb] = desk({ fail: true }); const rb = await b.closePort("8022");'
     ' return [ra, la.calls.length, rb, lb.notes, lb.applied.length]; })()',
     '[null,0,null,["controller is down"],0]',
     "negative: «отмена» — порт не трогается; отказ контроллера (вход выключен, нет ключа) — тост с его словами"),
    ("reopen_and_copy_the_entry",
     '',
     'await (async () => { const [d, log] = desk(); await d.reopenPort("23001"); const copied = await d.copyEntry();'
     ' st.setTopology({ ...st.topology, entry: { url: "", port: null } }); const none = await d.copyEntry();'
     ' return [log.asks.length, log.calls[0], log.notes, log.copied, copied, none]; })()',
     '[0,["/api/agent-proxies/route-policy",{"port":23001,"portClosed":false}],["Port :23001 is open again","Address copied"],["https://caravan-api.example/v1"],true,false]',
     "↺ открывает порт без вопроса (это путь назад); адрес входа копируется; negative: вход выключен — копировать нечего"),
    ("name_from_the_label",
     '',
     '(() => { const [d] = desk(); return [d.name("23001"), d.name("8022"), d.name("23999")]; })()',
     '["hermes","promie-ui",":23999"]',
     "имя потребителя — из подписи порта без primary/fallback; negative: неизвестный порт — сам номер, а не пустота"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    node = find_node()
    if node is None:
        print("js consumer-access: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_consumer_access.tmp.mjs"
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
        print(f"js consumer-access FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("потребитель на канбане: ключ, вход, порт и действия:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:220]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:220]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js consumer-access OK: настоящий модуль в node, {len(PINS)} пинов значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
