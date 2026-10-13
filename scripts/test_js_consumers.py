#!/usr/bin/env python3
"""Snapshot of static/js/consumers.js — the consumers of the entry on the board (2026-10-11).

A consumer's card says its name, its key's last four characters and its
requests; with no cable to a set of models it says so in the alarm colour, and
"not known" when the controller said nothing (2026-10-12: one cable goes on
from a client, to its set, drawn on the kanban). ＋ asks a name, makes the
consumer and shows its key once beside the address and the models its set
gives (`models`, the controller's reading); a new key says first that the old one stops
working; rename and delete go through the route's own doors. A refusal is
said, not swallowed; a cancelled window sends nothing.

Pinned by value, with the module loaded for real (scripts/_js_harness.mjs);
dialogs and the board's render are stubbed, the controller, the clipboard and
the entry's desk are stand-ins passed to the class. Strings come from en.js.

Run: python3 scripts/test_js_consumers.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("dialogs,topology-render,consumer-access,polling,remote-cells,topology-dnd,canvas,charts,cables,history,"
         "favorites,config-locator,system-panels,onboarding,onboarding-tours,dialog-llamas,models-page,system-page,"
         "memory,command-preview,llama-edit,topology-nodes,topology-modals,topology-activity,topology-proxies,routers,cloud")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const m = await import(pathToFileURL(process.env.JS_ROOT + "/consumers.js").href);
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const fill = (s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => v[k]);
const ENTRY = { url: "https://caravan-api.example/v1", port: 23999 };
const TOPO = () => ({ proxies: [
    { port: 23003, label: "Zed", kind: "consumer", keyTail: "zz99", set: "cheap", setName: "Cheap", models: ["Econom"], mode: "paused" },
    { port: 23001, label: "Hermes", kind: "consumer", keyTail: "a1b2", set: "chat", setName: "Chat", models: ["Standart", "Econom"] },
    { port: 23002, label: "Bot", kind: "consumer", keyTail: "c3d4", set: "", setName: "", models: [] },
    { port: 23004, label: "Odd", kind: "consumer", keyTail: "e5f6" },
    { port: 8022, label: "promie-ui", keyTail: "9f3c", apiKey: "lcv1_legacy" }],
  pools: [{ id: "std", name: "Standart" }, { id: "eco", name: "Econom" }],
  sets: [{ id: "chat", name: "Chat", pools: ["std", "eco"] }, { id: "cheap", name: "Cheap", pools: ["eco"] }],
  entry: { ...ENTRY }, clients: [], routers: [], assignments: {} });
const desk = (over = {}) => {
  const log = { asks: [], calls: [], notes: [], applied: [], copied: [], prompts: [], setups: 0 };
  const answers = [...(over.answers || [true, true])];
  const typed = [...(over.prompts || [])];
  const access = {
    seenHtml: () => "", entryHtml: (entry) => `ENTRY(${entry?.url || "off"})`,
    setupEntry: async () => { log.setups++; if (over.entryOn) st.setTopology({ ...st.topology, entry: { ...ENTRY } }); return over.entryOn ? { port: 23999 } : null; },
    copyEntry: async () => { log.calls.push(["copyEntry"]); return true; },
    turnOffEntry: async () => { log.calls.push(["turnOffEntry"]); return true; },
  };
  const d = new m.ConsumerCards({
    confirm: async (text, opts) => { log.asks.push([text, opts]); return answers.length ? answers.shift() : true; },
    ask: async (text, opts) => { log.prompts.push([text, opts]); return typed.length ? typed.shift() : null; },
    call: async (path, o) => {
      log.calls.push(o ? [path, JSON.parse(o.body)] : [path]);
      if (over.fail) throw new Error("controller is down");
      if (path === "/api/topology") return over.top || { marker: "fresh" };
      return "res" in over ? over.res : { ok: true };
    },
    notify: (x) => log.notes.push(x), copy: async (x) => { log.copied.push(x); return true; },
    access, apply: (top) => { log.applied.push(top); if (over.adopt) st.setTopology(top); } });
  return [d, log];
};
const reset = () => { st.setTopology(TOPO()); };
reset();
const out = {};
"""

PINS = [
    ("consumers_by_name",
     '',
     'm.ConsumerCards.of(st.topology).map((p) => p.label)',
     '["Bot","Hermes","Odd","Zed"]',
     "клиенты входа по имени; negative: порт старого вида (без kind) — не клиент входа"),
    ("consumers_in_the_operators_order",
     '',
     '(() => { const of = (layout) => m.ConsumerCards.of({ ...st.topology, layout }).map((p) => p.label);'
     ' const typed = m.ConsumerCards.of({ proxies: [{ port: 23001, label: "A", kind: "consumer" }, { port: "23005", label: "S", kind: "consumer" }], layout: { clientOrder: [23005] } }).map((p) => p.label);'
     ' return [of({ clientOrder: [23003, 23001] }), of({ clientOrder: ["23004", 9999, 23003] }), of({ clientOrder: [] }), of({}), of(undefined), typed]; })()',
     '[["Zed","Hermes","Bot","Odd"],["Odd","Zed","Bot","Hermes"],["Bot","Hermes","Odd","Zed"],["Bot","Hermes","Odd","Zed"],["Bot","Hermes","Odd","Zed"],["S","A"]]',
     "порядок оператора (1.3.503, перенос карточки на канбане): названные — первыми, в его порядке, остальные — по имени; порт строкой — "
     "в порядке и у клиента — тот же порт; negative: порт без клиента ничего не рисует, пустой или несказанный порядок — по имени, как раньше"),
    ("card_parts",
     '',
     '(() => { const [d] = desk(); const h = d.cardHtml(st.topology.proxies[1]); const z = d.cardHtml(st.topology.proxies[0]);'
     ' return [h.includes(\'data-t="board-consumer-card" data-t-id="23001"\'), h.includes(">Hermes<"), h.includes("🔑 …a1b2"),'
     ' ["key", "rename", "delete", "models"].map((a) => h.includes(`data-consumer-${a}="23001"`)), h.includes(">" + en.consumerNewKey + "<"),'
     ' h.includes("lcv1_"), h.includes(" paused"), z.includes("consumer-card paused")]; })()',
     '[true,true,true,[true,true,true,false],true,false,false,true]',
     "карточка: имя, четыре знака ключа, кнопки ключа, имени и удаления; negative: кнопки выбора моделей нет — набор даёт канат "
     "на канбане; ключа целиком нет; клиент на паузе — блеклый"),
    # 2026-10-11 (the owner: a client's activity on the cables, as the agents' was): the card lights
    # with its client's request and carries the handle its cable leaves from (cables.js).
    ("card_lights_and_carries_its_cable_handle",
     '',
     '(() => { const R = globalThis.__stubReturns = globalThis.__stubReturns || {};'
     ' R["topology-activity.topologyProxyActivity"] = (p) => ({ state: p.port === 23001 ? "active" : "idle" });'
     ' R["topology-activity.topologyStateHealthClasses"] = (a) => (a?.state === "active" ? "activity-active health-ok" : "");'
     ' try { const [d] = desk(); const [zz, hh, bb, oo] = st.topology.proxies.slice(0, 4).map((p) => d.cardHtml({ ...p, id: `ctl:proxy:${p.port}` }));'
     ' const handle = (id) => `data-topology-proxy-output="1" data-proxy-id="${id}"`;'
     ' return [hh.includes(\'class="topology-card consumer-card activity-active health-ok"\'), hh.includes(\'data-topology-proxy="1" data-proxy-id="ctl:proxy:23001"\'),'
     ' hh.includes(handle("ctl:proxy:23001")), zz.includes(handle("ctl:proxy:23003")), zz.includes("activity-"), bb.includes("data-topology-proxy-output"),'
     ' oo.includes("data-topology-proxy-output")]; }'
     ' finally { delete R["topology-activity.topologyProxyActivity"]; delete R["topology-activity.topologyStateHealthClasses"]; } })()',
     '[true,true,true,true,false,false,false]',
     "карточка горит, пока идёт запрос её клиента, и несёт гнездо, откуда выходит её канат к набору; "
     "negative: тихая карточка не горит; у клиента без набора и у клиента, о чьём наборе контроллер молчит, гнезда нет"),
    # 2026-10-12, the owner: the set's name off the card (the kanban names the sets), the
    # client's requests on it — the strip under the clients moved onto them (charts.js draws it).
    ("card_on_one_line_with_quiet_actions",
     '',
     '(() => { const [d] = desk(); const h = d.cardHtml({ ...st.topology.proxies[1], lastRequestAt: 0 });'
     ' const head = h.slice(h.indexOf(\'<div class="consumer-head">\'), h.indexOf("</div>", h.indexOf(\'<div class="consumer-head">\')));'
     ' const acts = head.slice(head.indexOf(\'<span class="consumer-acts">\'));'
     ' return [head.includes(">Hermes<") && head.includes("🔑 …a1b2"), ["key", "rename", "delete"].map((a) => acts.includes(`data-consumer-${a}="23001"`)),'
     ' (h.match(/class="consumer-line"/g) || []).length]; })()',
     '[true,[true,true,true],0]',
     "карточка клиента в одну строку (владелец, 2026-10-12: чище, как на канбане): имя, четыре знака ключа и в конце строки "
     "три действия — новый ключ, имя, удаление — тихие, пока на карточку не навели; negative: второй строки с ключом нет, "
     "у клиента с канатом под строкой только его запросы"),
    ("card_shows_its_requests_not_its_set",
     '',
     '(() => { const [d] = desk(); const [z, h, b, o] = st.topology.proxies.slice(0, 4).map((p) => d.cardHtml(p));'
     ' return [h.includes(\'data-consumer-activity="Hermes" data-open-route-activity data-t="consumer-activity" data-t-id="23001"\'),'
     ' h.includes(`title="${en.consumerActivityTitle.replaceAll("\'", "&#39;")}"`), h.includes("consumer-set") || h.includes(">Chat<") || z.includes("Cheap"),'
     ' b.includes(\'data-t="consumer-set" data-t-state="none"\') && !b.includes("consumer-activity"),'
     ' o.includes(\'data-t-state="unknown"\') && !o.includes("consumer-activity")]; })()',
     '[true,true,false,true,true]',
     "клиент с канатом: на карточке строка его запросов, по имени, и подсказка, что откроет щелчок; negative: имени набора на "
     "карточке нет — наборы называет канбан; без каната — сказано красным, строки запросов нет; контроллер не "
     "сказал — «неизвестно»"),
    ("set_three_states",
     '',
     '(() => { const [d] = desk(); const [z, h, b, o] = st.topology.proxies.map((p) => d.setHtml(p));'
     ' return [h.includes(\'data-t="consumer-set" data-t-state="cabled"\') && h.includes(\'<span class="consumer-model">Chat</span>\'),'
     ' z.includes(">Cheap<") && !z.includes("Chat"),'
     ' b.includes(\'data-t-state="none"\') && b.includes(en.consumerSetNone) && b.includes("consumer-models none"),'
     ' o.includes(\'data-t-state="unknown"\') && o.includes(en.consumerSetUnknown), d.setHtml({ set: null }).includes(\'data-t-state="unknown"\')]; })()',
     '[true,true,true,true,true]',
     "набор клиента — имя, которое прислал контроллер; у другого клиента — его имя; negative: каната нет — сказано красным, "
     "что провести его на канбане; контроллер не сказал — «неизвестно», а не «нет»"),
    ("lane_entry_then_cards",
     '',
     '(() => { const [d] = desk(); const h = d.laneHtml(st.topology); const at = (n) => h.indexOf(`>${n}<`);'
     ' return [h.startsWith(\'<div class="consumer-entry">ENTRY(https://caravan-api.example/v1)</div>\'), at("Bot") < at("Hermes") && at("Hermes") < at("Odd") && at("Odd") < at("Zed"), h.includes("promie-ui")]; })()',
     '[true,true,false]',
     "полоса: сверху адрес входа, под ним карточки по имени; negative: порт старого вида здесь не рисуется"),
    ("create_name_then_key",
     '',
     'await (async () => { const top = { ...TOPO(), proxies: [...TOPO().proxies, { port: 23005, label: "Hermes 2", kind: "consumer", keyTail: "e000", set: "", setName: "", models: [] }] };'
     ' const [d, log] = desk({ prompts: ["  Hermes 2 "], adopt: true,'
     ' res: { ok: true, port: 23005, name: "Hermes 2", key: "lcv1_new", set: "", entryUrl: ENTRY.url, topology: top } });'
     ' const r = await d.create();'
     ' return [log.prompts[0][0] === en.consumerNameAsk && log.prompts[0][1].text === en.consumerNameText,'
     ' log.calls, log.applied.length,'
     ' log.asks[0][0] === fill(en.consumerKeyShownText, { name: "Hermes 2", key: "lcv1_new", address: ENTRY.url, model: en.consumerSetNone }),'
     ' [log.asks[0][1].title === fill(en.consumerKeyShownTitle, { name: "Hermes 2" }), log.asks[0][1].danger, log.asks[0][1].confirmLabel === en.consumerCopyKey, log.asks[0][1].cancelLabel === en.consumerDone],'
     ' log.copied, log.notes, r.port]; })()',
     '[true,[["/api/consumers/create",{"name":"Hermes 2"}]],1,true,[true,false,true,true],["lcv1_new"],["Key copied"],23005]',
     "＋: имя (пробелы срезаны), и клиент сделан — без выбора моделей; ключ показан один раз с адресом, а вместо модели сказано, "
     "что канат к набору ещё не проведён; копируется по слову"),
    ("create_cancelled_or_refused",
     '',
     'await (async () => { const [a, la] = desk({ prompts: [null] }); await a.create(); const [b, lb] = desk({ prompts: ["   "] }); await b.create();'
     ' const [e, le] = desk({ prompts: ["X"], fail: true }); const re = await e.create();'
     ' return [la.calls.length, lb.calls.length, le.calls, le.notes, le.asks.length, re]; })()',
     '[0,0,[["/api/consumers/create",{"name":"X"}]],["controller is down"],0,null]',
     "negative: отмена имени и имя из пробелов — ничего не шлётся; отказ контроллера — тост с причиной, окна с ключом нет"),
    ("create_entry_first",
     '',
     'await (async () => { st.setTopology({ ...TOPO(), entry: { url: "", port: null } }); const [a, la] = desk(); const ra = await a.create();'
     ' st.setTopology({ ...TOPO(), entry: { url: "", port: null } }); const [b, lb] = desk({ entryOn: true, prompts: [null] }); await b.create();'
     ' return [ra, la.notes, la.setups, la.prompts.length, lb.setups, lb.prompts.length]; })()',
     '[null,["A key works only through the entry: set up the entry first"],1,0,1,1]',
     "вход выключен: сначала «Настроить вход»; negative: его отменили — имя не спрашивается; включили — дальше имя"),
    ("new_key_warns_first",
     '',
     'await (async () => { const [d, log] = desk({ answers: [true, false], res: { ok: true, port: 23001, name: "Hermes", key: "lcv1_fresh", entryUrl: ENTRY.url, topology: { marker: 3 } } });'
     ' await d.newKey(23001); const [c, lc] = desk({ answers: [false] }); await c.newKey(23001);'
     ' return [log.asks[0][0] === fill(en.consumerNewKeyText, { name: "Hermes" }) && log.asks[0][1].danger && log.asks[0][1].confirmLabel === en.consumerNewKey,'
     ' log.calls, log.applied, log.asks[1][0] === fill(en.consumerKeyShownText, { name: "Hermes", key: "lcv1_fresh", address: ENTRY.url, model: "Standart, Econom" }),'
     ' log.copied, lc.calls.length]; })()',
     '[true,[["/api/consumers/key",{"port":23001}]],[{"marker":3}],true,[],0]',
     "новый ключ: сначала сказано, что старый перестанет работать; новый показан один раз с моделями набора клиента, «Готово» не копирует; "
     "negative: отмена — ничего"),
    ("rename_and_delete",
     '',
     'await (async () => { const [d, log] = desk({ prompts: [" Hermes the 2nd "], top: { marker: "t" } }); await d.rename(23001);'
     ' const [s, ls] = desk({ prompts: ["Hermes"] }); await s.rename(23001); const [b, lb] = desk({ prompts: ["  "] }); await b.rename(23001);'
     ' const [x, lx] = desk({ answers: [true], res: { ok: true, topology: { marker: "gone" } } }); await x.remove(23001); const [y, ly] = desk({ answers: [false] }); await y.remove(23001);'
     ' return [log.prompts[0][1].value, log.calls, log.applied, log.notes, ls.calls.length + lb.calls.length,'
     ' lx.asks[0][0] === fill(en.consumerDeleteText, { name: "Hermes" }) && lx.asks[0][1].danger, lx.calls, lx.applied, lx.notes, ly.calls.length]; })()',
     '["Hermes",[["/api/agent-proxies/route-policy",{"port":23001,"label":"Hermes the 2nd"}],["/api/topology"]],[{"marker":"t"}],["Renamed: Hermes the 2nd"],0,'
     'true,[["/api/agent-proxies/route-delete",{"port":23001}]],[{"marker":"gone"}],["Deleted: Hermes"],0]',
     "имя — дверью маршрута, доска перечитана; удаление — после вопроса; negative: то же имя, пустое имя, отмена удаления — ничего не шлётся"),
    ("lane_buttons_bound_once",
     '',
     'await (async () => { const [d, log] = desk({ answers: [false] }); const seen = []; d.newKey = (p) => seen.push(["key", p]); d.rename = (p) => seen.push(["rename", p]);'
     ' d.remove = (p) => seen.push(["delete", p]);'
     ' const handlers = []; const lane = { dataset: {}, addEventListener: (type, fn) => handlers.push([type, fn]) }; d.bind(lane); d.bind(lane);'
     ' const btn = (ds, attr = "") => ({ dataset: ds, hasAttribute: (a) => a === attr }); const click = (target) => handlers[0][1]({ target: { closest: () => target }, stopPropagation() {} });'
     ' click(btn({ consumerKey: "23001" })); click(btn({ consumerRename: "23002" })); click(btn({ consumerDelete: "23004" }));'
     ' click(btn({}, "data-cv-entry-setup")); click(btn({}, "data-cv-entry-copy")); click(btn({}, "data-cv-entry-off"));'
     ' handlers[0][1]({ target: { closest: () => null }, stopPropagation() {} });'
     ' return [handlers.length, handlers[0][0], seen, log.setups, log.calls]; })()',
     '[1,"click",[["key","23001"],["rename","23002"],["delete","23004"]],1,[["copyEntry"],["turnOffEntry"]]]',
     "кнопки полосы ловит один слушатель, повторная привязка его не множит; кнопки входа (✎, ⧉, ✕) — тоже здесь; negative: щелчок мимо кнопок — ничего"),
]

_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    node = find_node()
    if node is None:
        print("js consumers: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_consumers.tmp.mjs"
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
        print(f"js consumers FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("клиенты входа на доске: карточка, ＋, ключ, пул:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:300]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:300]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js consumers OK: настоящий модуль в node, {len(PINS)} пинов значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
