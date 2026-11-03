#!/usr/bin/env python3
"""Snapshot of static/js/consumers.js — the consumers of the entry on the board (2026-10-11).

A consumer's card says its name, its key's last four characters and its
requests, and carries the handle its one cable to Routing leaves from (since
1.3.675 every client has it: each sees every pool and every model that runs, but
what is blocked for it). ＋ asks a name, makes the consumer and shows its key once
beside the address and the models it sees (`models`, the controller's reading); a
new key says first that the old one stops working; rename and delete go through
the route's own doors. A refusal is said, not swallowed; a cancelled window sends nothing.

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
from _node import find_node, node_search_paths, probe_args  # noqa: E402

STUBS = ("dialogs,topology-render,consumer-access,polling,remote-cells,topology-dnd,canvas,charts,cables,history,"
         "favorites,config-locator,system-panels,onboarding,onboarding-tours,dialog-llamas,models-page,system-page,"
         "memory,command-preview,llama-edit,topology-nodes,topology-modals,topology-activity,topology-proxies,routers,cloud")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
const m = await import(pathToFileURL(process.env.JS_ROOT + "/consumers.js").href);
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const { escapeHtml: esc } = await import(pathToFileURL(process.env.JS_ROOT + "/utils.js").href);
const fill = (s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => v[k]);
const ENTRY = { url: "https://caravan-api.example/v1", port: 23999 };
// What each client sees (`models`) against what a client blocked for nothing sees (`entryModels`, 1.3.675): Hermes all, Zed all
// but a pool, Bot nothing — every pool and model is blocked for it; Odd is a client the controller said nothing of.
const TOPO = () => ({ proxies: [
    { port: 23003, label: "Zed", kind: "consumer", keyTail: "zz99", deny: ["pool:std"], models: ["Econom", "qwen-x", "small"], mode: "paused" },
    { port: 23001, label: "Hermes", kind: "consumer", keyTail: "a1b2", deny: [], models: ["Standart", "Econom", "qwen-x", "small"] },
    { port: 23002, label: "Bot", kind: "consumer", keyTail: "c3d4", deny: ["pool:std", "pool:eco", "model:mm:aaa", "account:r"], models: [] },
    { port: 23004, label: "Odd", kind: "consumer", keyTail: "e5f6" },
    { port: 8022, label: "promie-ui", keyTail: "9f3c", apiKey: "lcv1_legacy" }],
  pools: [{ id: "std", name: "Standart" }, { id: "eco", name: "Econom" }], entryModels: ["Standart", "Econom", "qwen-x", "small"],
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
const B = (over = {}) => ({ id: "ctl:proxy:23009", port: 23009, label: "Open WebUI", kind: "consumer", builtin: "open-webui", keyTail: "b0b0", deny: [],
  models: ["Standart", "Econom", "qwen-x", "small"], lastRequestAt: 0, ...over });
// The built-in opencode client (2026-10-27) is given its opencode.json (`offer`): the pools first, then every model the caravan knows.
const OC = (over = {}) => ({ id: "ctl:proxy:23003", port: 23003, label: "opencode", kind: "consumer", builtin: "opencode", keyTail: "c0c0", deny: [],
  models: ["Standart", "Econom", "qwen-x", "small"],
  offer: [{ id: "coder-auto", name: "coder-auto — sol → qwen-x" }, { id: "qwen-x", name: "qwen-x" }, { id: "gemma-x", name: "gemma-x" }], ...over });
// What the built-in card reads besides its client: the entry, and what a client blocked for nothing sees.
const TOP = { entry: ENTRY, entryModels: ["Standart", "Econom", "qwen-x", "small"] };
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
     "порядок оператора (1.3.503, перенос карточки в Маршрутизации): названные — первыми, в его порядке, остальные — по имени; порт строкой — "
     "в порядке и у клиента — тот же порт; negative: порт без клиента ничего не рисует, пустой или несказанный порядок — по имени, как раньше"),
    ("card_parts",
     '',
     '(() => { const [d] = desk(); const h = d.cardHtml(st.topology.proxies[1]); const z = d.cardHtml(st.topology.proxies[0]);'
     ' return [h.includes(\'data-t="board-consumer-card" data-t-id="23001"\'), h.includes(">Hermes<"), h.includes("🔑 …a1b2"),'
     ' ["key", "rename", "delete", "models"].map((a) => h.includes(`data-consumer-${a}="23001"`)), h.includes(">" + en.consumerNewKey + "<"),'
     ' h.includes("lcv1_"), h.includes(" paused"), z.includes("consumer-card paused")]; })()',
     '[true,true,true,[true,true,true,false],true,false,false,true]',
     "карточка: имя, четыре знака ключа, кнопки ключа, имени и удаления; negative: кнопки выбора моделей нет — набор даёт канат "
     "в Маршрутизации; ключа целиком нет; клиент на паузе — блеклый"),
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
     ' hh.includes(handle("ctl:proxy:23001")), zz.includes(handle("ctl:proxy:23003")), zz.includes("activity-"), bb.includes(handle("ctl:proxy:23002")),'
     ' oo.includes(handle("ctl:proxy:23004"))]; }'
     ' finally { delete R["topology-activity.topologyProxyActivity"]; delete R["topology-activity.topologyStateHealthClasses"]; } })()',
     '[true,true,true,true,false,true,true]',
     "карточка горит, пока идёт запрос её клиента, и у каждого клиента гнездо, откуда выходит его канат к Маршрутизации (1.3.675: каждый видит все пулы и "
     "модели — и тот, кому запрещено всё, и тот, о ком контроллер молчит: его запросы идут туда же); negative: тихая карточка не горит"),
    # 2026-10-12, the owner: the set's name off the card (Routing names the sets), the
    # client's requests on it — the strip under the clients moved onto them (charts.js draws it).
    ("card_on_one_line_with_quiet_actions",
     '',
     '(() => { const [d] = desk(); const h = d.cardHtml({ ...st.topology.proxies[1], lastRequestAt: 0 });'
     ' const head = h.slice(h.indexOf(\'<div class="consumer-head">\'), h.indexOf("</div>", h.indexOf(\'<div class="consumer-head">\')));'
     ' const acts = head.slice(head.indexOf(\'<span class="consumer-acts">\'));'
     ' return [head.includes(">Hermes<") && head.includes("🔑 …a1b2"), ["key", "rename", "delete"].map((a) => acts.includes(`data-consumer-${a}="23001"`)),'
     ' (h.match(/class="consumer-line"/g) || []).length]; })()',
     '[true,[true,true,true],0]',
     "карточка клиента в одну строку (владелец, 2026-10-12: чище, как в Маршрутизации): имя, четыре знака ключа и в конце строки "
     "три действия — новый ключ, имя, удаление — тихие, пока на карточку не навели; negative: второй строки с ключом нет, "
     "у клиента с канатом под строкой только его запросы"),
    # 2026-10-12, the owner: the client's requests on its card — the strip under the clients moved onto them (charts.js draws it).
    ("card_shows_its_requests",
     '',
     '(() => { const [d] = desk(); const cards = st.topology.proxies.slice(0, 4).map((p) => d.cardHtml(p)); const h = cards[1];'
     ' return [h.includes(\'data-consumer-activity="Hermes" data-open-route-activity data-t="consumer-activity" data-t-id="23001"\'),'
     ' h.includes(`title="${en.consumerActivityTitle.replaceAll("\'", "&#39;")}"`), cards.every((x) => x.includes("consumer-activity")),'
     ' cards.some((x) => x.includes("consumer-set") || x.includes("consumer-models"))]; })()',
     '[true,true,true,false]',
     "на карточке каждого клиента — строка его запросов, по имени, и подсказка, что откроет щелчок; negative: строки набора нет ни у кого (наборов нет с 1.3.675)"),
    ("lane_entry_then_cards",
     '',
     '(() => { const [d] = desk(); const h = d.laneHtml(st.topology); const at = (n) => h.indexOf(`>${n}<`);'
     ' return [h.startsWith(\'<div class="consumer-entry">ENTRY(https://caravan-api.example/v1)</div>\'), at("Bot") < at("Hermes") && at("Hermes") < at("Odd") && at("Odd") < at("Zed"), h.includes("promie-ui")]; })()',
     '[true,true,false]',
     "полоса: сверху адрес входа, под ним карточки по имени; negative: порт старого вида здесь не рисуется"),
    ("create_name_then_key",
     '',
     'await (async () => { const top = { ...TOPO(), proxies: [...TOPO().proxies, { port: 23005, label: "Hermes 2", kind: "consumer", keyTail: "e000", deny: [], models: [] }] };'
     ' const [d, log] = desk({ prompts: ["  Hermes 2 "], adopt: true,'
     ' res: { ok: true, port: 23005, name: "Hermes 2", key: "lcv1_new", entryUrl: ENTRY.url, topology: top } });'
     ' const r = await d.create();'
     ' return [log.prompts[0][0] === en.consumerNameAsk && log.prompts[0][1].text === en.consumerNameText,'
     ' log.calls, log.applied.length,'
     ' log.asks[0][0] === fill(en.consumerKeyShownText, { name: "Hermes 2", key: "lcv1_new", address: ENTRY.url, model: en.consumerNoModels }),'
     ' [log.asks[0][1].title === fill(en.consumerKeyShownTitle, { name: "Hermes 2" }), log.asks[0][1].danger, log.asks[0][1].confirmLabel === en.consumerCopyKey, log.asks[0][1].cancelLabel === en.consumerDone],'
     ' log.copied, log.notes, r.port]; })()',
     '[true,[["/api/consumers/create",{"name":"Hermes 2"}]],1,true,[true,false,true,true],["lcv1_new"],["Key copied"],23005]',
     "＋: имя (пробелы срезаны), и клиент сделан — без выбора моделей: он видит всё сразу (владелец, 2026-10-27); ключ показан один раз с адресом, а вместо "
     "модели сказано, что ни одна ещё не работает; копируется по слову"),
    ("plus_of_a_block_makes_a_client_of_its_program",
     'st.setTopology({ ...TOPO(), entry: { ...ENTRY } });',
     'await (async () => { const res = { ok: true, port: 23005, name: "opencode m2", key: "lcv1_new", entryUrl: ENTRY.url, topology: { marker: 1 } };'
     ' const [d, log] = desk({ res, answers: [false], prompts: ["  opencode m2 "] }); const r = await d.createOf("opencode");'
     ' const [c, lc] = desk({ res, prompts: [null] }); const none = await c.createOf("opencode");'
     ' const [e, le] = desk({ res, answers: [false], prompts: [""] }); await e.createOf("opencode");'
     ' return [log.prompts.length, log.prompts[0][1].text === en.consumerKindNameText, log.calls, log.asks[0][1].title === fill(en.consumerKeyShownTitle, { name: "opencode m2" }), r.port, d.howto.has("23005"),'
     ' lc.calls, none, c.howto.size, le.calls, d.opencodeHtml(OC({ port: 23005 }), ENTRY).includes("data-consumer-first-key"), d.opencodeHtml(OC({ port: 23005 }), ENTRY).includes(esc(en.consumerKeyWasShown)),'
     ' d.opencodeHtml(OC(), ENTRY).includes("data-consumer-first-key")]; })()',
     '[1,true,[["/api/consumers/create",{"kind":"opencode","name":"opencode m2"}]],true,23005,true,[],null,0,[["/api/consumers/create",{"kind":"opencode","name":""}]],false,true,true]',
     "＋ блока (владелец, 2026-11-01): спрашивает имя, делает клиента этого вида, показывает ключ один раз, и его строка открыта на том, как подключить; "
     "ключ уже показан — второй кнопки «выдать ключ» нет: она заменила бы только что вставленный; negative: отмена — ничего не сделано; пустое имя — решает контроллер: "
     "имя программы с номером; клиент, сделанный не здесь, кнопку сохраняет"),
    ("small_plus_needs_the_entry",
     'st.setTopology({ ...TOPO(), entry: { url: "" } });',
     'await (async () => { const [d, log] = desk(); const r = await d.createOf("open-webui"); return [r, log.calls, log.setups, log.notes.includes(en.entryNeedsSetupFirst)]; })()',
     '[null,[],1,true]',
     "negative: вход выключен — сначала настройка входа, а без неё клиент не делается"),
    ("the_last_of_a_kind_stays",
     '',
     '(() => { const [d] = desk(); const has = (h) => h.includes(\'data-consumer-delete="23009"\'); const others = (...p) => ({ ...TOP, proxies: p });'
     ' return [has(d.builtinHtml(B(), others(B(), B({ port: 23010, id: "x" })))), has(d.builtinHtml(B(), others(B(), OC()))), has(d.builtinHtml(B(), others(B())))]; })()',
     '[true,false,false]',
     "✕ у клиента программы, пока есть другой того же вида; negative: opencode рядом не считается, а последний остаётся: караван сделал бы его снова"),
    ("key_window_names_what_the_client_sees",
     '',
     'await (async () => { const [d, log] = desk(); await d.showKey({ port: 23001, name: "Hermes", key: "lcv1_k", entryUrl: ENTRY.url });'
     ' return log.asks[0][0] === fill(en.consumerKeyShownText, { name: "Hermes", key: "lcv1_k", address: ENTRY.url, model: "Standart, Econom, qwen-x, small" }); })()',
     'true',
     "окно ключа называет модели, которые клиент видит, — все пулы и работающие модели, кроме запрещённых"),
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
     ' log.calls, log.applied, log.asks[1][0] === fill(en.consumerKeyShownText, { name: "Hermes", key: "lcv1_fresh", address: ENTRY.url, model: "Standart, Econom, qwen-x, small" }),'
     ' log.copied, lc.calls.length]; })()',
     '[true,[["/api/consumers/key",{"port":23001}]],[{"marker":3}],true,[],0]',
     "новый ключ: сначала сказано, что старый перестанет работать; новый показан один раз с моделями, которые видит клиент, «Готово» не копирует; "
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
     ' d.remove = (p) => seen.push(["delete", p]); d.createOf = (k) => seen.push(["add", k]); d.toggleHowto = (p) => seen.push(["howto", p]);'
     ' const handlers = []; const lane = { dataset: {}, addEventListener: (type, fn) => handlers.push([type, fn]) }; d.bind(lane); d.bind(lane);'
     ' const btn = (ds, attr = "") => ({ dataset: ds, hasAttribute: (a) => a === attr }); const click = (target) => handlers[0][1]({ target: { closest: () => target }, stopPropagation() {} });'
     ' click(btn({ consumerKey: "23001" })); click(btn({ consumerRename: "23002" })); click(btn({ consumerDelete: "23004" })); click(btn({ clientAddKind: "opencode" })); click(btn({ consumerHowto: "23003" }));'
     ' click(btn({}, "data-cv-entry-setup")); click(btn({}, "data-cv-entry-copy")); click(btn({}, "data-cv-entry-off"));'
     ' handlers[0][1]({ target: { closest: () => null }, stopPropagation() {} });'
     ' return [handlers.length, handlers[0][0], seen, log.setups, log.calls]; })()',
     '[1,"click",[["key","23001"],["rename","23002"],["delete","23004"],["add","opencode"],["howto","23003"]],1,[["copyEntry"],["turnOffEntry"]]]',
     "кнопки полосы ловит один слушатель, повторная привязка его не множит; кнопки входа (✎, ⧉, ✕), ＋ блока и «как подключить» — тоже здесь; negative: щелчок мимо кнопок — ничего"),
    # The owner, 2026-10-27: Open WebUI is the caravan's own client — first, under it a line, then the clients with sets; no set,
    # no ✕; it sees every model that runs (`catalog`, the controller's reading); until its first request its card says how to connect it.
    ("builtin_stands_first",
     'st.setTopology({ ...TOPO(), proxies: [...TOPO().proxies, B()], layout: { clientOrder: [23003, 23001] } });',
     '[m.ConsumerCards.of(st.topology).map((p) => p.label),'
     ' m.ConsumerCards.of({ proxies: [{ port: 1, label: "Open WebUI", kind: "consumer" }, { port: 2, label: "Alpha", kind: "consumer" }] }).map((p) => p.label)]',
     '[["Open WebUI","Zed","Hermes","Bot","Odd"],["Alpha","Open WebUI"]]',
     "встроенный клиент — первым, что бы ни говорил порядок оператора; negative: клиент с именем Open WebUI без поля builtin стоит по имени"),
    ("lane_with_builtin",
     'st.setTopology({ ...TOPO(), proxies: [...TOPO().proxies, B()] });',
     '(() => { const d = new m.ConsumerCards({ access: { seenHtml: () => "", entryHtml: (e, o) => `ENTRY(${e?.url || "off"},${o?.stays})` } });'
     ' const h = d.laneHtml(st.topology); const at = (x) => h.indexOf(x); const plain = d.laneHtml(TOPO());'
     ' return [h.startsWith("<div class=\\"consumer-entry\\">ENTRY(https://caravan-api.example/v1,true)"), at(\'data-t-state="builtin"\') < at(\'data-t="consumer-divider"\'),'
     ' at(\'data-t="consumer-divider"\') < at(\'data-t-id="23001"\'), h.includes(">" + en.consumerOthers + "<"), h.includes("consumer-empty"),'
     ' plain.startsWith("<div class=\\"consumer-entry\\">ENTRY(https://caravan-api.example/v1,false)"), plain.includes("consumer-divider")]; })()',
     '[true,true,true,true,false,true,false]',
     "адрес входа — без ✕ (встроенный не удаляют, вход остаётся), под ним встроенный, черта «другие клиенты», остальные; "
     "negative: без встроенного — ни черты, ни запрета ✕"),
    ("builtin_card_parts",
     '',
     '(() => { const [d] = desk(); const closed = d.builtinHtml(B(), TOP); d.howto.add("23009"); const h = d.builtinHtml(B(), TOP);'
     ' const used = d.builtinHtml(B({ lastRequestAt: 1793000000 }), TOP);'
     ' return [["key", "rename", "delete"].map((a) => h.includes(`data-consumer-${a}="23009"`)),'
     ' h.includes(\'data-topology-proxy-output="1" data-proxy-id="ctl:proxy:23009"\'), h.includes(\'data-t="consumer-live" data-t-state="all"\'),'
     ' h.includes(">" + fill(en.pbClientSeesAll, { all: "4" }) + "<"),'
     ' (h.match(/class="consumer-step"/g) || []).length, h.includes(\'data-consumer-first-key="23009"\'), h.includes(">https://caravan-api.example/v1<"),'
     ' h.includes("consumer-adopt"),'
     ' used.includes("consumer-connect"), used.includes(\'data-consumer-activity="Open WebUI"\'), h.includes("data-consumer-activity"),'
     ' closed.includes("consumer-connect"), closed.includes(\'data-consumer-howto="23009"\'), closed.includes(\'aria-expanded="false"\'), h.includes(\'aria-expanded="true"\'), used.includes("data-consumer-howto")]; })()',
     '[[true,true,false],true,true,true,3,true,true,false,false,true,false,false,true,true,true,false]',
     "строка клиента: новый ключ и имя, ✕ нет; канат идёт, как у всех; сколько моделей он видит — словами Маршрутизации; пока не звонил — кнопка «как подключить», "
     "шаги закрыты (занимали 315 px у клиента, которого никто не подключал) и открываются по кнопке: три шага с адресом и «выдать ключ»; переноса старого клиента больше нет; "
     "клиент с именем open-webui предложен первым, но не выбран за оператора без такого имени; после первого запроса — его запросы, кнопки и шагов нет"),
    ("builtin_live_states",
     '',
     '(() => { const all = TOP.entryModels; const words = (p, seen = all) => [m.ConsumerCards.liveHtml(p, seen).includes(en.consumerLiveUnknown),'
     ' m.ConsumerCards.liveHtml(p, seen).includes(en.consumerLiveNone), m.ConsumerCards.seesText(p, seen)];'
     ' return [words(B({ models: undefined })), words(B(), null), words(B({ models: [] })), words(B({ models: ["Standart"] })), words(B())]; })()',
     json.dumps([[True, False, "Models: not known"], [True, False, "Models: not known"], [False, True, "Sees 0 of 4"],
                 [False, False, "Sees 1 of 4"], [False, False, "Sees all 4"]]),
     "что видит встроенный: не прочитано — «не известно» (и когда не прочитано, что видит клиент, которому ничего не запрещено: сравнить не с чем); "
     "ничего — «моделей пока нет, запустите или подключите облако», а счёт — «видит 0 из 4»; часть — «видит 1 из 4»; всё — «видит все 4»; "
     "negative: не прочитано — не «нет моделей»; не видит ничего — не «видит все»"),
    ("builtin_connect_without_entry",
     '',
     '(() => { const [d] = desk(); const h = d.connectHtml(B(), { url: "" });'
     ' return [h.includes(en.consumerConnectNoEntry), h.includes("data-cv-entry-copy")]; })()',
     '[true,false]',
     "вход закрыт — шаг адреса говорит это, копировать нечего"),
    ("lane_only_builtin",
     'st.setTopology({ ...TOPO(), proxies: [B()] });',
     '(() => { const [d] = desk(); return [d.laneHtml(st.topology).includes(en.consumerOthersNone), d.laneHtml(st.topology, { others: true }).includes(en.consumerOthersNone)]; })()',
     '[true,false]',
     "под чертой никого — сказано, для кого это место; negative: ниже стоят клиенты старого вида — подсказки нет"),
    ("builtins_stand_first_in_their_kinds_order",
     '',
     'm.ConsumerCards.of({ proxies: [OC(), { port: 23001, label: "Alpha", kind: "consumer" }, B()], layout: { clientOrder: [23001, 23003] } }).map((p) => p.label)',
     '["Open WebUI","opencode","Alpha"]',
     "встроенные — первыми, в порядке видов: Open WebUI, потом opencode, что бы ни говорил порядок оператора; потом остальные"),
    ("opencode_card_parts",
     '',
     '(() => { const [d] = desk(); d.howto.add("23003");'
     ' const h = d.builtinHtml(OC(), TOP); const block = d.blockHtml("opencode", [OC()], TOP);'
     ' return [h.includes(\'data-builtin="opencode"\'), block.includes(`title="${esc(en.consumerOcBuiltinTitle)}"`), h.includes("consumer-set"),'
     ' (h.match(/class="consumer-step"/g) || []).length, h.includes(\'data-consumer-first-key="23003"\'), h.includes(esc(en.consumerOcKeyWhere)),'
     ' h.includes(\'data-consumer-oc-config="23003"\'), h.includes(esc(fill(en.consumerOcConfigModels, { n: "3" }))),'
     ' block.includes("consumer-adopt"),'
     ' h.includes(esc(en.consumerConnectWhere)), h.includes(\'data-consumer-delete="23003"\')]; })()',
     '[true,true,false,2,true,true,true,true,false,false,false]',
     "строка opencode: два шага — ключ (вписать /connect → Other → caravan) и «скопировать opencode.json» с числом моделей; "
     "negative: набора нет (1.3.675), переноса старого клиента нет (владелец, 2026-11-02), шагов Open WebUI нет, у последнего ✕ нет"),
    ("a_block_holds_all_the_clients_of_a_program",
     'st.setTopology({ ...TOPO(), entry: { ...ENTRY }, entryModels: TOP.entryModels, proxies: [B(), OC(), OC({ port: 23008, id: "ctl:proxy:23008", label: "opencode m1", lastRequestAt: 1793000000 }),'
     ' { port: 23001, id: "ctl:proxy:23001", label: "hermes", kind: "consumer", keyTail: "d9a3" }, { port: 23033, id: "ctl:proxy:23033", label: "opencode old", kind: "consumer", keyTail: "aaaa" }] });',
     '(() => { const [d] = desk(); const h = d.laneHtml(st.topology); const blocks = h.split(\'<section class="consumer-block"\').slice(1); const [owui, oc] = blocks; const rest = oc.split(\'data-t="consumer-divider"\')[1];'
     ' const count = (s, x) => s.split(x).length - 1;'
     ' return [blocks.length, owui.includes(\'data-t-id="open-webui"\'), oc.includes(\'data-t-id="opencode"\'),'
     ' count(owui, \'data-t="board-consumer-card"\'), count(oc.split(\'data-t="consumer-divider"\')[0], \'data-t="board-consumer-card"\'), count(rest, \'data-t="board-consumer-card"\'),'
     ' count(h, \'data-client-add-kind\'), oc.includes(\'data-client-add-kind="opencode" data-t="client-add-kind" data-t-id="opencode"\'), owui.includes(\'consumer-block-count\'), oc.includes(\'consumer-block-count" data-t="consumer-block-count">2<\'),'
     ' count(oc.split(\'data-t="consumer-divider"\')[0], \'data-consumer-oc-config="23003"\'), count(oc.split(\'data-t="consumer-divider"\')[0], \'data-consumer-oc-config="23008"\'),'
     ' count(owui, \'data-t="consumer-live"\'), count(oc.split(\'data-t="consumer-divider"\')[0], \'data-t="consumer-live"\'),'
     ' h.includes("consumer-adopt"),'
     ' count(h, \'data-topology-proxy-output="1"\'), count(owui, \'data-consumer-delete\'), count(oc, \'data-consumer-delete="23003"\')]; })()',
     '[2,true,true,1,2,2,1,true,false,true,1,0,1,1,false,5,0,1]',
     "блок на программу (владелец, 2026-11-01, Б1): Open WebUI один, opencode два, остальные под чертой; ＋ только у opencode и счёт только у него; "
     "opencode.json один, в шапке: файл без ключа, у них одинаковый; «видит» один раз на блок; у каждого клиента свой канат; "
     "negative: у Open WebUI нет ни ＋, ни счёта, ни ✕; переноса нет нигде (владелец, 2026-11-02); у строки opencode ✕ есть, пока есть второй"),
    ("a_block_says_on_its_rows_what_they_do_not_share",
     '',
     '(() => { const [d] = desk(); const one = OC(), two = OC({ port: 23008, id: "x", label: "m1", offer: [{ id: "qwen-x", name: "qwen-x" }], models: ["qwen-x"] });'
     ' const h = d.blockHtml("opencode", [one, two], TOP); const count = (x) => h.split(x).length - 1; const off = d.blockHtml("opencode", [one], { ...TOP, entry: { url: "" } });'
     ' const unknown = d.blockHtml("opencode", [OC({ offer: null })], TOP); const nobody = d.blockHtml("opencode", [], TOP);'
     ' return [count(\'data-consumer-oc-config="23003"\'), count(\'data-consumer-oc-config="23008"\'), count(\'data-t="consumer-live"\'), h.includes("consumer-block-tools\\">⧉"), count("consumer-oc-file"),'
     ' off.includes("data-consumer-oc-config"), off.includes(esc(en.consumerConnectNoEntry)), unknown.includes(esc(en.consumerOcConfigUnknown)), nobody]; })()',
     '[1,1,2,false,2,false,true,true,""]',
     "запрет у одного клиента: списки и «видит» разные — у каждой строки свой файл и свой счёт, в шапке их нет; "
     "negative: вход закрыт или модели не прочитаны — кнопки нет, и сказано почему; клиентов вида нет — блока нет"),
    ("how_to_connect_opens_and_closes",
     'st.setTopology({ ...TOPO(), entry: { ...ENTRY }, proxies: [OC()] });',
     '(() => { const [d, log] = desk(); d.toggleHowto("23003"); const open = d.howto.has("23003"); d.toggleHowto(23003); return [open, d.howto.has("23003"), log.applied.length]; })()',
     '[true,false,2]',
     "«как подключить» открывается и закрывается по кнопке, и доска рисуется заново"),
    ("opencode_file_stays_after_first_call",
     '',
     '(() => { const [d] = desk(); const used = d.builtinHtml(OC({ lastRequestAt: 1793000000 }), TOP); const owui = d.builtinHtml(B({ lastRequestAt: 1793000000 }), TOP);'
     ' const off = d.builtinHtml(OC({ lastRequestAt: 1793000000 }), { ...TOP, entry: { url: "" } });'
     ' return [used.includes(\'data-consumer-activity="opencode"\'), used.includes(\'data-consumer-oc-config="23003"\'), used.includes("consumer-connect"),'
     ' owui.includes("data-consumer-oc-config"), off.includes("data-consumer-oc-config"), off.includes(esc(en.consumerConnectNoEntry))]; })()',
     '[true,true,false,false,false,true]',
     "после первого запроса у opencode — его запросы и всё равно «скопировать opencode.json»: файл меняется с новой моделью, а сам opencode "
     "о ней не узнаёт; negative: шагов подключения уже нет, у Open WebUI такой кнопки нет; вход закрыт — копировать нечего, так и сказано"),
    ("opencode_config_file",
     '',
     '(() => { const c = m.ConsumerCards.opencodeConfig(OC(), "https://caravan-api.example/v1");'
     ' return [c, m.ConsumerCards.opencodeConfig(OC(), ""), m.ConsumerCards.opencodeConfig(OC({ offer: null }), "https://x/v1")]; })()',
     json.dumps([{"$schema": "https://opencode.ai/config.json", "provider": {"caravan": {"npm": "@ai-sdk/openai-compatible", "name": "Caravan",
                 "options": {"baseURL": "https://caravan-api.example/v1"},
                 "models": {"coder-auto": {"name": "coder-auto — sol → qwen-x"}, "qwen-x": {"name": "qwen-x"}, "gemma-x": {"name": "gemma-x"}}}}},
                None, None], ensure_ascii=False),
     "opencode.json — провайдер caravan (@ai-sdk/openai-compatible) по адресу входа и модели по именам, пул набора — с тем, что он пробует; "
     "ключа в файле нет; negative: вход закрыт или модели не прочитаны — файла нет, а не пустой"),
    ("opencode_copy",
     'st.setTopology({ ...TOPO(), proxies: [...TOPO().proxies, OC({ label: "opencode 2", port: 23040, id: "ctl:proxy:23040" })] });',
     'await (async () => { const [c, lc] = desk(); await c.copyOpencodeConfig("23040");'
     ' return [JSON.parse(lc.copied[0]).provider.caravan.options.baseURL, lc.copied[0].includes("\\n  "), lc.notes]; })()',
     json.dumps(["https://caravan-api.example/v1", True, ["Copied: opencode.json, 3 models"]], ensure_ascii=False),
     "«скопировать opencode.json» кладёт файл с отступами и говорит, сколько в нём моделей"),
    ("builtin_first_key",
     'st.setTopology({ ...TOPO(), proxies: [...TOPO().proxies, B()] });',
     'await (async () => { const [k, lk] = desk({ res: { port: 23009, name: "Open WebUI", key: "lcv1_new" } }); await k.firstKey("23009");'
     ' return [lk.calls, lk.asks.length, lk.asks[0][1].confirmLabel === en.consumerCopyKey,'
     ' ["consumerAdoptTextNoSet", "consumerOcAdoptTextNoSet", "consumerAdoptedDropped", "consumerAdoptedKept", "consumerMoveHere", "consumerAdoptAction", "consumerJoined"].filter((k) => k in en)]; })()',
     '[[["/api/consumers/key",{"port":23009}]],1,true,[]]',
     "первый ключ — без вопроса «старый перестанет работать» (его никто не видел), сразу окно ключа; "
     "negative: ни набора, ни переноса старого клиента в словах больше нет (1.3.675; владелец, 2026-11-02)"),
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
            probe_args(node, harness, path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
    finally:
        path.unlink(missing_ok=True)
    if run.returncode != 0:
        print(run.stdout); print(run.stderr)
        print(f"js consumers FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("клиенты входа на доске: карточка, ＋, ключ, пул:")
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    render = (ROOT / "static" / "js" / "topology-render.js").read_text(encoding="utf-8")
    head = index[index.index('id="topologyClientAddBtn"'):index.index('id="topologyClients"')]
    check('data-client-add-kind' not in head and 'data-client-add-kind' not in render,
          "negative: маленьких кнопок программ в шапке клиентов больше нет: ＋ стоит в блоке программы, и его ловит лента клиентов")
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
