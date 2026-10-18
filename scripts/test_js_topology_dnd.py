#!/usr/bin/env python3
"""Snapshot of static/js/topology-dnd.js — the board's delegated binder.

`bindTopologyDragAndDrop` attaches listeners to ~a hundred selectors after
every render. The snapshot fills the selector dict with elements, calls the
binder, and fires the listeners, pinning the CONSEQUENCES: calls to
neighbors (stubs recording them), `ui` state, module-level modal flags, the
shared confirm's texts and what confirming it does. What matters here: the
port key — "don't require a key" clears the field, and unchecking the box
with an empty field GENERATES a key (an empty field would have been saved as
"open"); the account window's exits — "Done" gives no click event for an
account id, deleting an account asks in cloud.js's words; deleting a proxy
names the agents bound to it; the
"default" radio rolls back until confirmed, and confirming clears
`dormantDefault`; threshold sliders: mouse/keys, a 1% floor for abort, a live
caption in seconds; drag-reordering priority rows up/down; the schedule — a
grid of rules, a paint brush, clearing, saving via saveRouters,
pointerdown/over drawing; failover — a chain with default first, or turned
off; a proxy entering/leaving a router — with confirmation; cable
hover-highlighting; route details keep their range on the same route.

The DOM is a selector dict; elementFromPoint is a stub; rAF is synchronous.

Run: python3 scripts/test_js_topology_dnd.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("dialogs,cables,canvas,charts,cloud,remote-cells,history,llama-edit,routers,topology-activity,topology-modals,"
         "topology-nodes,topology-proxies,topology-render,usage-stats,favorites,config-locator,system-panels,onboarding,"
         "onboarding-tours,dialog-llamas,models-page,system-page,memory,command-preview,llama-edit,polling,form,model-meta")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} }); st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
globalThis.requestAnimationFrame = (fn) => { fn(); return 0; }; globalThis.CSS = { escape: (s) => String(s) };
globalThis.__opened = []; globalThis.open = (u) => { globalThis.__opened.push(String(u)); };
// Where this tab was sent (location.assign): a window.open is a NEW tab, and the owner asked for none (2026-10-17).
globalThis.__navigated = []; globalThis.location.assign = (u) => { globalThis.__navigated.push(String(u)); };
const G = () => Array.from({ length: 7 }, () => Array(24).fill(""));
globalThis.__stubValues = { "canvas._cvQueueHistOpen": {}, "canvas._cvQueueHistData": {}, "canvas._cvSchedHistOpen": {}, "canvas._cvSchedHistData": {}, "canvas._cvPos": {}, "canvas._cvView": {},
  "routers.topologyOutputsFolded": {}, "routers.topologyQuietShown": {},
  // The step window listens on the board's permanent container (pool-step-dialog.js): a value
  // that writes down where it was bound.
  "cloud.POOL_STEPS": { bound: [], bind(root) { this.bound.push(root); } },
  "topology-modals.topologyPriorityOrder": [], "topology-modals.topologyQueuePriorityEdits": {},
  "usage-stats.subscriptionUsageCache": new Map(), "usage-stats.apiCostsCache": new Map(), "usage-stats.openrouterLimitsCache": new Map(), "usage-stats.usageStatsApiPriceEdit": {}, "usage-stats.usageStatsData": { rate: { inputPer1M: 1, outputPer1M: 2 } } };
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on === undefined ? (s.has(c) ? s.delete(c) : s.add(c)) : (on ? s.add(c) : s.delete(c))), has: (c) => s.has(c), list: () => [...s].sort() } };
const mkEl = (props = {}) => { const e = { tagName: "DIV", dataset: {}, listeners: {}, classList: cls(), style: {}, value: "", checked: false, hidden: false, textContent: "", children: [], parent: null, rect: { left: 0, top: 0, width: 100, height: 20 },
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, getBoundingClientRect() { return this.rect; }, closest(sel) { return this.q?.[sel] ?? (this.parent ? this.parent.closest(sel) : null); }, querySelector(sel) { return this.q?.[sel] ?? null; }, querySelectorAll(sel) { return this.qa?.[sel] ?? []; }, remove() { this.removed = true; }, ...props }; return e; };
globalThis.__q = {}; globalThis.__qa = {};
document.querySelector = (sel) => (Object.prototype.hasOwnProperty.call(globalThis.__q, sel) ? globalThis.__q[sel] : null);
document.querySelectorAll = (sel) => globalThis.__qa[sel] || [];
document.getElementById = (id) => (Object.prototype.hasOwnProperty.call(globalThis.__fields, id) ? globalThis.__fields[id] : null);
const docListeners = {}; document.addEventListener = (t, fn) => { (docListeners[t] ||= []).push(fn); if (t === "pointerup") globalThis.__pointerUp = fn; }; document.removeEventListener = (t, fn) => { const l = docListeners[t] || []; const i = l.indexOf(fn); if (i >= 0) l.splice(i, 1); };
globalThis.__atPoint = null; document.elementFromPoint = () => globalThis.__atPoint;
const m = await import(pathToFileURL(process.env.JS_ROOT + "/topology-dnd.js").href);
const V = (key) => globalThis.__stubValues[key];
globalThis.__calls = []; const isEventLike = (x) => x && typeof x === "object" && (x.listeners || "target" in x || typeof x.preventDefault === "function" || "currentTarget" in x);
const arg = (x) => (typeof x === "function" ? "fn" : isEventLike(x) ? null : x);
const rec = (name, ret) => (...a) => { globalThis.__calls.push([name, ...a.map(arg)]); return ret; }; const arec = (name, ret) => async (...a) => { globalThis.__calls.push([name, ...a.map(arg)]); return ret; };
const calls = () => globalThis.__calls; const names = () => globalThis.__calls.map((c) => c[0]);
const one = (sel, props = {}) => { const e = mkEl(props); globalThis.__q[sel] = e; return e; };
const many = (sel, ...list) => { const els = list.map((p) => mkEl(p)); globalThis.__qa[sel] = els; return els; };
const F = () => globalThis.__fields; const fire = (el, type, ev = {}) => (el.listeners[type] || []).forEach((fn) => fn(ev));
const confirmState = () => ({ title: F().confirmTitle.textContent, text: F().confirmText.textContent, path: F().confirmPath.textContent, ok: F().confirmDelete.textContent, danger: F().confirmDelete.classList.has("danger"), shown: !F().confirmOverlay.hidden });
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); };
const ROUTERS = () => [{ id: "router:a", outputs: [{ id: "srv:1" }, { id: "cb:x" }, { id: "srv:2" }], rules: { default: "cb:x", dormantDefault: "srv:1", schedule: [{ days: ["mon"], from: "09:00", to: "10:59", output: "srv:1" }], bySource: [{ proxyId: "p1", output: "srv:1" }, { proxyId: "p2", output: "srv:2" }], failover: [] } }];
const reset = () => { st.setTopology({ proxies: [{ id: "skynet:proxy:23001", port: 23001, label: "hotel", priority: 2 }, { id: "skynet:proxy:23002", port: 23002, label: "" }], clients: [{ id: "box-a", agents: [{ id: "hotel", name: "Hotel" }] }], routers: ROUTERS(), assignments: { "box-a": { assignments: [{ agentId: "hotel", routes: [{ role: "primary", proxyId: "skynet:proxy:23001" }] }] } }, cloudAccounts: [{ id: "acct", name: "OpenAI" }], proxyPolicy: { cloudFallbackPct: 20, priorityPreemptPct: 50, queueAbortPct: 85 } });
  st.ui.pendingConfirm = null; st.ui.topologyCloudForm = null; st.ui.topologyProxyFormOpen = true; st.ui.topologyProxyEditingId = "skynet:proxy:23001"; st.ui.topologyRouterDetailId = "router:a"; st.ui.topologyCanvasRouterId = ""; st.ui.usageStatsModalOpen = true; st.ui.usageStatsExpanded = ""; st.ui.usageStatsRateEdit = null; st.ui.topologyCloudPickerOpen = false; st.ui.topologyCloudModalOpen = true;
  globalThis.__q = {}; globalThis.__qa = {}; globalThis.__calls = []; globalThis.__opened.length = 0; globalThis.__navigated.length = 0; globalThis.__atPoint = null; for (const k of Object.keys(docListeners)) delete docListeners[k];
  globalThis.__fields = { confirmTitle: mkEl(), confirmText: mkEl(), confirmPath: mkEl(), confirmMeta: mkEl(), confirmDelete: mkEl(), confirmOverlay: mkEl({ hidden: true }), toast: mkEl(), topologyCables: mkEl() };
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {};
  for (const k of ["canvas._cvQueueHistOpen", "canvas._cvQueueHistData", "canvas._cvSchedHistOpen", "canvas._cvSchedHistData", "routers.topologyOutputsFolded", "routers.topologyQuietShown", "topology-modals.topologyQueuePriorityEdits", "usage-stats.usageStatsApiPriceEdit"]) for (const kk of Object.keys(V(k))) delete V(k)[kk];
  V("topology-modals.topologyPriorityOrder").length = 0; V("cloud.POOL_STEPS").bound.length = 0; V("usage-stats.subscriptionUsageCache").clear(); V("usage-stats.apiCostsCache").clear(); V("usage-stats.openrouterLimitsCache").clear();
  globalThis.__stubReturns = { "topology-render.renderTopology": rec("renderTopology"), "topology-render.flushPendingTopologyRender": rec("flushPendingTopologyRender"), "llama-edit.closeConfirmModal": rec("closeConfirmModal"), "dialogs.appConfirm": arec("appConfirm", true),
    "topology-modals.openQueuePriorityModal": rec("openQueuePriorityModal"), "topology-modals.closeQueuePriorityModal": rec("closeQueuePriorityModal"), "topology-modals.saveQueuePriorityModal": arec("saveQueuePriorityModal"), "topology-modals.openRawConfigViewer": arec("openRawConfigViewer"), "topology-modals.closeRawConfigViewer": rec("closeRawConfigViewer"), "topology-modals.closePriorityModal": rec("closePriorityModal"), "topology-modals.savePriorityModal": arec("savePriorityModal"), "topology-modals.setTopologyProxyRoutePolicy": arec("setTopologyProxyRoutePolicy"), "topology-modals.editTopologyClientAlias": arec("editTopologyClientAlias"), "topology-modals._fmtSec": (s) => s + "s", "topology-modals._queuePctExampleText": (a, b, c) => `ex ${a}/${b}/${c}`, "topology-modals.scheduleRulesToGrid": (r) => { const g = G(); for (const rule of (r?.rules?.schedule || [])) g[0][9] = rule.output; return g; }, "topology-modals.scheduleGridToRules": rec("scheduleGridToRules", [{ days: ["mon"], from: "09:00", to: "09:59", output: "srv:1" }]),
    "topology-proxies.saveTopologyProxyForm": arec("saveTopologyProxyForm"), "topology-proxies.editTopologyProxy": rec("editTopologyProxy"), "topology-proxies.isEntryClient": (p) => String(p?.kind || "") === "consumer", "history.openRequestHistory": rec("openRequestHistory"), "charts.openRouteActivityModal": rec("openRouteActivityModal"), "charts.closeRouteActivityModal": rec("closeRouteActivityModal"), "charts.openChartModal": rec("openChartModal"), "charts.closeChartModal": rec("closeChartModal"), "topology-nodes.closeIncidentsModal": rec("closeIncidentsModal"),
    "cloud.closeCloudProviderModal": rec("closeCloudProviderModal"), "cloud.saveCloudAccount": arec("saveCloudAccount"), "cloud.deleteCloudAccount": arec("deleteCloudAccount"), "cloud.startCloudOauthLogin": arec("startCloudOauthLogin"), "cloud.cancelCloudAccountWindow": arec("cancelCloudAccountWindow"), "cloud.cloudDeleteWords": (acct) => `words:${acct?.id}`, "cloud.copyCloudDeviceCode": arec("copyCloudDeviceCode", true), "cloud.finishCloudAccountWindow": rec("finishCloudAccountWindow"), "cloud.selectCloudProviderType": rec("selectCloudProviderType"), "cloud.pickCloudProvider": rec("pickCloudProvider"),
    "usage-stats.refreshUsageReading": rec("refreshUsageReading"), "usage-stats.fetchSubscriptionUsage": rec("fetchSubscriptionUsage"), "usage-stats.fetchApiCosts": rec("fetchApiCosts"), "usage-stats.fetchOpenRouterLimits": rec("fetchOpenRouterLimits"), "usage-stats.fetchUsageStats": rec("fetchUsageStats"), "usage-stats.saveLocalPricing": rec("saveLocalPricing"), "usage-stats.saveApiPrice": rec("saveApiPrice"),
    "routers.routerById": (routers, id) => routers.find((r) => r.id === id), "routers.saveRouters": async (mut) => { const copy = JSON.parse(JSON.stringify(st.topology.routers)); mut(copy); globalThis.__calls.push(["saveRouters", copy]); },
    "topology-activity.proxyEffectiveWaitTimeout": () => 1800, "topology-activity.loadRouteTokenHistory": rec("loadRouteTokenHistory"), "cables.highlightTopologyCable": rec("highlightTopologyCable"), "cables.scheduleClearTopologyCableHighlight": rec("scheduleClearTopologyCableHighlight"), "cables.topologyRouteClass": (h, a, r) => `route-${h}-${a}-${r}`, "cables.topologyProxyClass": (id) => `proxy-${id}`,
    "canvas.cvSetViewport": rec("cvSetViewport"), "canvas.canvasOpenPositions": rec("canvasOpenPositions", { n: 1 }), "canvas.canvasInitialView": rec("canvasInitialView", { n: 2 }), "canvas.drawCanvasConnectors": rec("drawCanvasConnectors"), "canvas.bindCanvasInteractions": rec("bindCanvasInteractions"), "canvas._fetchQueueHist": rec("_fetchQueueHist"), "canvas._fetchSchedHist": rec("_fetchSchedHist"), "canvas.scheduleOutputColor": (r, o) => (o ? "#c0ffee" : ""),
    "remote-cells.renameTopologyAgent": arec("renameTopologyAgent") }; };
reset();
const bind = () => m.bindTopologyDragAndDrop();
const out = {};
"""

PINS = [
    ("proxy_nokey_clears_and_regenerates_key", '', '(() => { const nokey = one("[data-proxy-nokey]"); const label = one("[data-topology-proxy-form] .proxy-apikey-label"); const input = one(\'[data-topology-proxy-form] [name="apiKey"]\', { value: "lcv1_old" }); bind(); fire(nokey, "change", { target: { checked: true } }); const a = [label.hidden, input.value]; fire(nokey, "change", { target: { checked: false } }); const b = [label.hidden, /^lcv1_[0-9a-f]{32}$/.test(input.value)]; input.value = "keep"; fire(nokey, "change", { target: { checked: false } }); return [...a, ...b, input.value]; })()',
     '[true,"",false,true,"keep"]', "«не требовать ключ»: поле очищено и спрятано; снятие галки с ПУСТЫМ полем генерирует ключ (пустое сохранилось бы как «открыто»); непустое не трогается"),
    ("proxy_genkey_and_overlay", '', '(() => { const gen = one("[data-proxy-genkey]"); const input = one(\'[data-topology-proxy-form] [name="apiKey"]\'); const ov = one("[data-topology-proxy-overlay]"); bind(); fire(gen, "click"); const key = input.value; fire(ov, "click", { target: { dataset: {} } }); const still = st.ui.topologyProxyFormOpen; fire(ov, "click", { target: { dataset: { topologyProxyOverlay: "" } } }); return [/^lcv1_[0-9a-f]{48}$/.test(key), still, st.ui.topologyProxyFormOpen, st.ui.topologyProxyEditingId, names().includes("renderTopology")]; })()',
     '[true,true,false,"",true]', "генерация ключа — 24 байта hex с префиксом; подложка формы прокси закрывает форму и сбрасывает редактируемый id"),
    # 2026-10-11: the clients' activity strip is in index.html and outlives every render — a listener
    # added on each render opened the window once per render so far.
    ("route_activity_opener_bound_once",
     '',
     '(() => { const [ra] = many("[data-open-route-activity]", { dataset: {} }); bind(); bind(); bind(); fire(ra, "click");'
     ' return calls().filter((c) => c[0] === "openRouteActivityModal").map((c) => c.slice(1)); })()',
     '[[null]]',
     "открывашка окна активности привязана один раз: три отрисовки — один щелчок открывает окно один раз; без машины — окно целиком (null)"),
    ("history_route_activity_chart_incidents", '', '(() => { F().topologyRequestHistoryBtn = mkEl(); const [ra] = many("[data-open-route-activity]", { dataset: { routeNode: "box-a" } }); F().routeActivityClose = mkEl(); F().routeActivityOverlay = mkEl(); const [ch] = many("[data-open-chart]", { dataset: { openChart: "gpu" } }); F().chartExpandClose = mkEl(); F().chartExpandOverlay = mkEl(); F().incidentsModalClose = mkEl(); F().incidentsModalOverlay = mkEl(); bind(); fire(F().topologyRequestHistoryBtn, "click"); fire(ra, "click"); fire(F().routeActivityClose, "click"); fire(F().routeActivityOverlay, "click", { target: F().routeActivityOverlay }); fire(F().routeActivityOverlay, "click", { target: {} }); fire(ch, "click"); fire(F().chartExpandOverlay, "click", { target: F().chartExpandOverlay }); fire(F().incidentsModalClose, "click"); return [names(), calls().find((c) => c[0] === "openRouteActivityModal")[1], calls().find((c) => c[0] === "openChartModal")[1]]; })()',
     '[["openRequestHistory","openRouteActivityModal","closeRouteActivityModal","closeRouteActivityModal","openChartModal","closeChartModal","closeIncidentsModal"],"box-a","gpu"]', "история, активность маршрутов узла, графики, инциденты: открытие с аргументом, закрытие кнопкой и подложкой (не содержимым)"),
    ("cloud_account_modal_and_delete_confirm", '', 'await (async () => { const x = one("[data-cloud-close]"); const cancel = one("[data-cloud-cancel]"); const ov = one("[data-topology-cloud-overlay]"); const done = one("[data-cloud-done]"); const save = one("[data-cloud-save]"); const del = one("[data-cloud-delete-account]"); bind(); fire(x, "click"); fire(cancel, "click"); fire(ov, "click", { target: { dataset: { topologyCloudOverlay: "" } } }); fire(ov, "click", { target: { dataset: {} } }); fire(done, "click", { type: "click" }); fire(save, "click"); st.ui.topologyCloudForm = { accountId: "acct" }; fire(del, "click"); const c = confirmState(); st.ui.pendingConfirm(); await settle(); return [names().filter((x) => x === "cancelCloudAccountWindow").length, names().filter((x) => x === "closeCloudProviderModal").length, calls().filter((x) => x[0] === "finishCloudAccountWindow"), names().includes("saveCloudAccount"), c.text, c.danger, c.shown, names().slice(-2)]; })()',
     '[3,0,[["finishCloudAccountWindow"]],true,"words:acct",true,true,["closeConfirmModal","deleteCloudAccount"]]', "модал аккаунта: ×, Cancel и подложка — отмена окна (она забирает учётку, сделанную для незавершённого входа); клик по содержимому — нет; «Готово» завершает окно без аргументов — событие клика не выдаётся за id учётки; сохранение; удаление — красный confirm со словами cloud.js о том, что сделает удаление; подтверждение удаляет"),
    ("cloud_delete_confirm_takes_the_words_of_cloud_js", '', '(() => { const del = one("[data-cloud-delete-account]"); bind(); st.ui.topologyCloudForm = { accountId: "acct" }; fire(del, "click"); const known = confirmState().text; st.ui.topologyCloudForm = { accountId: "gone" }; fire(del, "click"); return [known, confirmState().text]; })()',
     '["words:acct","words:undefined"]', "подтверждение удаления говорит словами cloudDeleteWords (они проверены значениями в снимке cloud.js); negative: учётки нет — слова всё равно спрошены, без неё"),
    ("step_window_listens_on_the_board_container", '', '(() => { F().topologyProxies = mkEl(); bind(); bind(); return V("cloud.POOL_STEPS").bound.map((r) => r === F().topologyProxies); })()',
     '[true,true]', "окно шага слушает постоянный контейнер доски — привязка просится на каждой перерисовке, а повтор окно отбрасывает само (снимок pools)"),
    ("usage_refresh_not_bound_per_render", '', '(() => { const lane = mkEl(); F().topologyCloudProviders = lane; bind(); bind(); return Object.keys(lane.listeners || {}); })()',
     '[]', "defect-history: ↻ облачной карточки больше не привязывается здесь — bind() идёт на каждой полной перерисовке, и после K перерисовок один ↻ спрашивал провайдера K раз; делегат живёт в cloud.js и привязывается один раз (пин — в снимке cloud.js)"),
    ("device_code_copies_on_its_own_click", '',
     '(() => { const code = one("[data-cloud-device-code]"); bind(); const ev = (key) => ({ key, held: false, preventDefault() { this.held = true; } }); const keys = [ev("Enter"), ev(" "), ev("Tab"), ev("a")]; fire(code, "click"); keys.forEach((k) => fire(code, "keydown", k)); return [names().filter((n) => n === "copyCloudDeviceCode").length, keys.map((k) => k.held)]; })()',
     '[3,[true,true,false,false]]', "клик по самому коду копирует его, Enter и пробел — тоже, без прокрутки страницы пробелом; negative: Tab и буква не копируют и фокус не держат"),
    ("device_open_copies_then_goes_in_this_tab", '',
     'await (async () => { const open = one("[data-cloud-device-open]"); bind(); const tick = () => new Promise((r) => setImmediate(r));'
     ' const click = (extra = {}) => { const ev = { button: 0, held: 0, preventDefault() { this.held += 1; }, currentTarget: { href: "https://auth.openai.com/codex/device" }, ...extra }; fire(open, "click", ev); return ev; };'
     ' const plain = click(); const wentAtOnce = globalThis.__navigated.length; await tick(); const went = [...globalThis.__navigated];'
     ' const others = []; for (const extra of [{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }, { button: 2 }]) { others.push(click(extra).held); await tick(); }'
     ' return [plain.held, wentAtOnce, went, others, names().filter((n) => n === "copyCloudDeviceCode").length, [...globalThis.__navigated], [...globalThis.__opened]]; })()',
     '[1,0,["https://auth.openai.com/codex/device"],[0,0,0,0,0,0],7,["https://auth.openai.com/codex/device"],[]]',
     "ссылка на страницу OpenAI уходит в ЭТОЙ ЖЕ вкладке (2026-10-17), но после копирования кода: клик не даёт браузеру уйти сам (preventDefault), страница идёт на адрес ссылки, когда копирование закончилось, окон не открывается; "
     "negative: клик с Cmd, Ctrl, Shift или Alt (новая вкладка или окно — выбор браузера), средней и правой кнопкой копируют код, но не уводят и не отменяют переход"),
    ("cloud_fields_and_sign_in", '', '(() => { const [auth, key, name] = many("[data-cloud-field]", { tagName: "SELECT", dataset: { cloudField: "authMode" }, value: "noKey" }, { tagName: "INPUT", dataset: { cloudField: "apiKey" }, value: "sk-x" }, { tagName: "INPUT", dataset: { cloudField: "name" }, value: "N" }); const login = one("[data-cloud-oauth-login]"); const open = one("[data-cloud-device-open]"); const gone = ["[data-cloud-oauth-loopback]", "[data-cloud-oauth-complete]", "[data-cloud-device-copy]"].map((sel) => one(sel)); bind(); fire(name, "input"); const noForm = st.ui.topologyCloudForm; st.ui.topologyCloudForm = {}; fire(auth, "change"); fire(key, "input"); fire(name, "input"); fire(login, "click"); fire(open, "click", { metaKey: true }); return [noForm, st.ui.topologyCloudForm, names().includes("renderTopology"), names().includes("startCloudOauthLogin"), names().includes("copyCloudDeviceCode"), !!auth.listeners.change, !!name.listeners.input, gone.map((el) => Object.keys(el.listeners || {}).length)]; })()',
     '[null,{"authMode":"noKey","apiKey":"sk-x","name":"N"},true,true,true,true,true,[0,0,0]]', "поля аккаунта: select — change, input — input; без формы игнор; authMode перерисовывает; вход — по коду, ссылка на страницу OpenAI копирует код (щелчок с модификатором — переход остаётся браузеру, уход в этой вкладке пинит соседний пин); negative: вход через localhost, «вставить адрес» и отдельное «копировать» не привязываются — их больше нет"),
    ("picker_tile_and_change", '', '(() => { const [tile, pale] = many("[data-pick-type]", { dataset: { pickType: "ollama" } }, { dataset: { pickType: "openrouter" }, disabled: true }); const change = one("[data-cloud-picker-change]"); one("[data-cloud-picker-close]"); bind(); fire(tile, "click"); fire(pale, "click"); fire(change, "click"); return [calls().filter((c) => c[0] === "pickCloudProvider").map((c) => c[1]), st.ui.topologyCloudPickerOpen, st.ui.topologyCloudModalOpen, st.ui.topologyCloudForm]; })()',
     '[["ollama"],true,false,null]', "плитка пикера выбирает провайдера (с главной доски — ставит его на доску пустым блоком, 2026-10-12); "
     "negative: бледная плитка «уже на доске» ничего не делает; «сменить тип» открывает пикер и сбрасывает форму"),
    ("gpu_and_llama_detail_modals_gone", '', '(() => { const [g] = many("[data-topology-gpu-modal]", {}); const [l] = many("[data-topology-llama-detail]", {}); bind(); return [Object.keys(g.listeners || {}).length, Object.keys(l.listeners || {}).length, "topologyGpuModalOpen" in m, "topologyLlamaDetailOpen" in m]; })()',
     '[0,0,false,false]', "negative: модалы «GPU — логи и сырой API» и «детали модели» одиночного сервера контроллера больше не открываются — ни привязок, ни флагов (шаг 6.9)"),
    ("usage_stats_controls", '', '(() => { const close = one("[data-usage-stats-close]"); const [d7] = many("[data-usage-stats-days]", { dataset: { usageStatsDays: "7" } }); const [sc] = many("[data-usage-stats-scope]", { dataset: { usageStatsScope: "cloud" } }); const [mdl] = many("[data-usage-stats-model]", { dataset: { usageStatsModel: "gpt" } }); const [rate] = many("[data-usage-stats-rate]", { dataset: { usageStatsRate: "inputPer1M" }, value: "3" }); const rs = one("[data-usage-stats-rate-save]"); const [ap] = many("[data-us-apiprice]", { dataset: { usApipriceModel: "gpt", usApiprice: "outputPer1M" }, value: "9" }); const [aps] = many("[data-us-apiprice-save]", { dataset: { usApipriceSave: "gpt" } }); bind(); st.ui.usageStatsExpanded = "x"; fire(d7, "click"); const days = [st.ui.usageStatsDays, st.ui.usageStatsExpanded]; fire(sc, "click"); fire(mdl, "click"); const exp1 = st.ui.usageStatsExpanded; fire(mdl, "click"); fire(rate, "input"); fire(rs, "click"); let sp = 0; fire(ap, "input"); fire(ap, "click", { stopPropagation: () => sp++ }); fire(aps, "click", { stopPropagation: () => sp++ }); fire(close, "click"); return [days, st.ui.usageStatsScope, exp1, st.ui.usageStatsExpanded, st.ui.usageStatsRateEdit, JSON.parse(JSON.stringify(V("usage-stats.usageStatsApiPriceEdit"))), sp, calls().filter((c) => ["fetchUsageStats", "saveLocalPricing", "saveApiPrice"].includes(c[0])).map((c) => c[0] + (typeof c[1] === "string" ? ":" + c[1] : "")), st.ui.usageStatsModalOpen]; })()',
     '[[7,""],"cloud","gpt","",{"inputPer1M":3,"outputPer1M":2},{"gpt":{"outputPer1M":9}},2,["fetchUsageStats","saveLocalPricing","saveApiPrice:gpt"],false]',
     "статистика расходов: дни (сброс раскрытия) → запрос, область, раскрытие модели туда-обратно, правка курса поверх текущего, цена API по модели без сворачивания строки, закрытие"),
    ("queue_priority_raw_priority_modals", '', 'await (async () => { const [qp] = many("[data-topology-queue-priority-open]", {}); const qc = one("[data-topology-queue-priority-close]"); const qs = one("[data-topology-queue-priority-save]"); const raw = one("[data-topology-raw-config]"); one("[data-topology-raw-close]"); const pc = one("[data-topology-priority-cancel]"); const ps = one("[data-topology-priority-save]"); bind(); fire(qp, "keydown", { key: "Enter", preventDefault() {} }); fire(qc, "click"); fire(qs, "click"); fire(raw, "click"); fire(pc, "click"); fire(ps, "click"); await settle(); return [names(), calls()[0][1]]; })()',
     '[["openQueuePriorityModal","closeQueuePriorityModal","saveQueuePriorityModal","openRawConfigViewer","closePriorityModal","savePriorityModal"],null]', "модалы очереди/сырого конфига/приоритетов: открыть, закрыть, сохранить — через свои функции"),
    ("priority_remove_and_drag_reorder", '', '(() => { const order = V("topology-modals.topologyPriorityOrder"); order.push("a", "b", "c"); const [rm] = many("[data-priority-remove]", { dataset: { priorityRemove: "b" } }); const [ra, rc] = many("[data-priority-row]", { dataset: { priorityRow: "a" }, rect: { top: 0, height: 20 } }, { dataset: { priorityRow: "c" }, rect: { top: 100, height: 20 } }); bind(); fire(rm, "click"); const afterRemove = [...order]; fire(rm, "click"); const dt = { data: "", setData(_, v) { this.data = v; }, getData() { return this.data; } }; fire(ra, "dragstart", { dataTransfer: dt }); fire(rc, "dragover", { preventDefault() {}, dataTransfer: dt, clientY: 115 }); const marks = [rc.classList.has("drop-below"), rc.classList.has("drop-above")]; fire(rc, "drop", { preventDefault() {}, dataTransfer: dt, clientY: 115 }); const below = [...order]; fire(ra, "dragstart", { dataTransfer: dt }); fire(ra, "drop", { preventDefault() {}, dataTransfer: dt, clientY: 0 }); const self = [...order]; fire(ra, "dragstart", { dataTransfer: dt }); fire(rc, "drop", { preventDefault() {}, dataTransfer: dt, clientY: 101 }); return [afterRemove, marks, below, self, [...order], ra.classList.has("dragging")]; })()',
     '[["a","c"],[true,false],["c","a"],["c","a"],["a","c"],true]', "приоритеты: удаление из списка (повтор — ничего), бросок ниже цели ставит после неё, на себя — ничего, ВЫШЕ цели — перед ней"),
    ("qp_proxy_handle_mouse_keys_and_reset", '', '(() => { const edits = V("topology-modals.topologyQueuePriorityEdits"); const fill = mkEl(); const track = mkEl({ rect: { left: 100, width: 200 }, q: { "[data-qp-proxy-fill]": fill } }); const timeEl = mkEl(); const [h] = many("[data-qp-proxy-handle]", { dataset: { qpProxyHandle: "23001", qpPctKey: "queueAbortPct" }, style: { left: "85%" }, q: { "[data-qp-proxy-track]": track, ".qp-handle-time": timeEl } }); const [rst] = many("[data-qp-proxy-reset]", { dataset: { qpProxyReset: "23001" } }); bind(); fire(h, "mousedown", { preventDefault() {} }); docListeners.mousemove[0]({ clientX: 100 }); const atMin = [edits.routes[23001].queueAbortPct, h.style.left, timeEl.textContent, fill.style.width]; docListeners.mousemove[0]({ clientX: 250 }); docListeners.mouseup[0](); const after = [edits.routes[23001].queueAbortPct, docListeners.mousemove.length]; fire(h, "keydown", { key: "ArrowRight", preventDefault() {} }); fire(h, "keydown", { key: "ArrowLeft", preventDefault() {} }); fire(h, "keydown", { key: "ArrowLeft", preventDefault() {} }); const keys = edits.routes[23001].queueAbortPct; fire(rst, "click"); return [atMin, after, keys, edits.routes[23001], names().includes("renderTopology")]; })()',
     '[[1,"1%","18s","1%"],[75,0],74,{"cloudFallbackPct":null,"priorityPreemptPct":null,"queueAbortPct":null},true]', "ползунок прокси: мышь — процент от трека с минимумом 1% у abort, живая подпись секундами (1800 с × 1%) и заливка; отпускание снимает слушатели; стрелки ±1; сброс — три null и перерисовка"),
    ("qp_policy_inputs_and_global_handles", '', '(() => { const edits = V("topology-modals.topologyQueuePriorityEdits"); const [num, chk] = many("[data-topology-qp-policy]", { type: "number", dataset: { topologyQpPolicy: "stickySlotSec" }, value: "15" }, { type: "checkbox", dataset: { topologyQpPolicy: "preemptEnabled" }, checked: false }); const fill = mkEl(); const pctEl = mkEl(); const hc = mkEl({ dataset: { qpHandle: "cloudFallbackPct" }, style: {}, q: { ".qp-handle-pct": pctEl } }); const ha = mkEl({ dataset: { qpHandle: "queueAbortPct" }, style: {}, q: {} }); const track = one("[data-qp-track]", { rect: { left: 0, width: 100 }, q: { "[data-qp-fill]": fill }, qa: { "[data-qp-handle]": [hc, ha] } }); const ex = one("[data-qp-example]"); bind(); fire(num, "input"); num.value = "abc"; fire(num, "input"); fire(chk, "change", { target: chk }); chk.checked = true; fire(chk, "change"); fire(hc, "keydown", { key: "ArrowUp", preventDefault() {} }); const a = [edits.cloudFallbackPct, hc.style.left, pctEl.textContent, ex.textContent, fill.style.width]; fire(ha, "mousedown", { preventDefault() {} }); docListeners.mousemove.at(-1)({ clientX: -50 }); docListeners.mouseup.at(-1)(); return [edits.stickySlotSec, edits.preemptEnabled, a, edits.queueAbortPct, fill.style.width]; })()',
     '[15,true,[21,"21%","21%","ex 21/50/85","85%"],1,"1%"]', "политика: число только конечное, галка; глобальные ползунки: стрелка от политики (+1), подпись/пример/заливка живые; мышь левее трека — минимум 1% у abort"),
    ("route_detail_open_keeps_range_for_same_route", '', '(() => { const [row] = many("[data-topology-route-detail]", { dataset: { topologyRouteDetail: "skynet:proxy:23001", clientIp: "10.0.0.7", clientName: "box" } }); const [row2] = [mkEl({ dataset: { topologyRouteDetail: "skynet:proxy:29999" } })]; globalThis.__qa["[data-topology-route-detail]"].push(row2); const [rng] = many("[data-token-range]", { dataset: { tokenRange: "24h" } }); const close = one("[data-topology-route-detail-close]"); bind(); fire(row, "click", { target: { closest: () => null } }); const first = { ...m.topologyRouteDetail }; fire(rng, "click"); const ranged = m.topologyRouteDetail.range; fire(row, "click", { target: { closest: () => null } }); const kept = m.topologyRouteDetail.range; fire(row2, "click", { target: { closest: () => null } }); const other = { port: m.topologyRouteDetail.port, range: m.topologyRouteDetail.range }; fire(row, "click", { target: { closest: () => ({}) } }); fire(close, "click"); return [first, ranged, kept, other, m.topologyRouteDetail, names().filter((x) => x === "loadRouteTokenHistory").length]; })()',
     '[{"proxyId":"skynet:proxy:23001","port":23001,"routeLabel":"hotel","clientIp":"10.0.0.7","clientName":"box","range":"all","tab":"details","modelCard":null},"24h","24h",{"port":29999,"range":"all"},null,4]',
     "детали маршрута: порт из прокси или из id, диапазон И ВКЛАДКА сохраняются при том же маршруте и сбрасываются при другом (чужая карточка модели на вкладке была бы ложью); клик по ручке не открывает; закрытие"),
    ("proxy_form_cancel_and_delete_names_bound_agents", 'globalThis.__fetchReply["/api/agent-proxies/route-delete"] = { ok: true, topology: { proxies: [], clients: [], routers: [], assignments: {} } };', 'await (async () => { const cancel = one("[data-topology-proxy-cancel]"); const del = one("[data-topology-proxy-delete]"); bind(); let opts = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (_m, o) => { opts = o; return false; }; await fire(del, "click"); await settle(); const refused = [opts.detail, opts.danger, globalThis.__fetchCalls.length]; globalThis.__stubReturns["dialogs.appConfirm"] = async () => true; await fire(del, "click"); await settle(); const done = [JSON.parse(globalThis.__fetchCalls[0].body), st.topology.proxies.length, st.ui.topologyProxyFormOpen, F().toast.textContent.includes("23001")]; st.ui.topologyProxyFormOpen = true; fire(cancel, "click"); return [refused, done, st.ui.topologyProxyFormOpen]; })()',
     '[[":23001 hotel\\nstill used by: box-a/hotel",true,0],[{"port":23001},0,false,true],false]', "удаление прокси: confirm называет порт и привязанных агентов; отказ — ни запроса; согласие — POST порта, topology из ответа, форма закрыта, тост; отмена закрывает форму"),
    ("route_detail_model_card_click_opens_the_model_tab", '', "(() => { globalThis.__stubReturns[\"topology-activity.loadRouteModelCard\"] = rec(\"loadRouteModelCard\"); const btn = mkEl(); const [row] = many(\"[data-topology-route-detail]\", { dataset: { topologyRouteDetail: \"skynet:proxy:23001\", clientIp: \"10.0.0.7\", clientName: \"box\" }, q: { \"[data-route-model-card]\": btn } }); const close = one(\"[data-topology-route-detail-close]\"); bind(); fire(close, \"click\"); let stopped = 0; fire(btn, \"click\", { stopPropagation: () => { stopped += 1; } }); const first = { tab: m.topologyRouteDetail.tab, port: m.topologyRouteDetail.port, card: m.topologyRouteDetail.modelCard }; const asked = names().filter((x) => x === \"loadRouteModelCard\").length; m.topologyRouteDetail.modelCard = { state: \"ok\" }; fire(btn, \"click\", { stopPropagation: () => { stopped += 1; } }); const again = names().filter((x) => x === \"loadRouteModelCard\").length; fire(row, \"click\", { target: { closest: () => null } }); const rowTab = m.topologyRouteDetail.tab; fire(close, \"click\"); fire(row, \"click\", { target: { closest: () => null } }); const plain = [m.topologyRouteDetail.tab, names().filter((x) => x === \"loadRouteModelCard\").length]; fire(close, \"click\"); return [first, stopped, asked, again, rowTab, plain]; })()",
     '[{"tab":"model","port":23001,"card":null},2,1,1,"model",["details",1]]',
     "🪟 спрашивает порт: клик открывает окно маршрута сразу на карточке модели и спрашивает порт один раз; клик по строке под ним не идёт (stopPropagation); карточка уже есть — второго вопроса нет (заново — ⟳); тот же маршрут держит вкладку; закрытое окно от строки открывается на подробностях и порт не спрашивает"),
    ("route_detail_keydown_is_the_rows_own", '', "(() => { const [row] = many(\"[data-topology-route-detail]\", { dataset: { topologyRouteDetail: \"skynet:proxy:23001\", clientIp: \"10.0.0.7\", clientName: \"box\" } }); const close = one(\"[data-topology-route-detail-close]\"); bind(); fire(close, \"click\"); let prevented = 0; const ev = (target, key) => ({ key, target, preventDefault: () => { prevented += 1; } }); fire(row, \"keydown\", ev(mkEl({ tagName: \"BUTTON\" }), \"Enter\")); fire(row, \"keydown\", ev(mkEl({ tagName: \"BUTTON\" }), \" \")); const fromButton = [m.topologyRouteDetail, prevented]; fire(row, \"keydown\", ev(row, \"x\")); const otherKey = [m.topologyRouteDetail, prevented]; fire(row, \"keydown\", ev(row, \"Enter\")); const fromRow = [m.topologyRouteDetail?.proxyId, prevented]; fire(close, \"click\"); return [fromButton, otherKey, fromRow]; })()",
     '[[null,0],[null,0],["skynet:proxy:23001",1]]',
     "клавиши строки — только её собственные: Enter и пробел на кнопке внутри (📏, 🪟, порт) — нажатие этой кнопки, строка не открывает подробности и не гасит его preventDefault; другая клавиша на строке — ничего; Enter на самой строке — открывает"),
    ("route_detail_edit_and_delete_lead_to_the_port_form_and_the_delete_path", 'globalThis.__fetchReply["/api/agent-proxies/route-delete"] = { ok: true, topology: { proxies: [], clients: [], routers: [], assignments: {} } };', 'await (async () => { const [row] = many("[data-topology-route-detail]", { dataset: { topologyRouteDetail: "skynet:proxy:23001", clientIp: "10.0.0.7", clientName: "box" } }); const [ed] = many("[data-route-detail-edit]", { dataset: { routeDetailEdit: "skynet:proxy:23001" } }); const [del] = many("[data-route-detail-delete]", { dataset: { routeDetailDelete: "23001" } }); bind(); fire(row, "click", { target: { closest: () => null } }); const opened = m.topologyRouteDetail?.proxyId; fire(ed, "click"); const afterEdit = [opened, calls().filter((c) => c[0] === "editTopologyProxy").map((c) => c[1]), m.topologyRouteDetail]; st.ui.topologyProxyEditingId = ""; let opts = null; globalThis.__stubReturns["dialogs.appConfirm"] = async (_m, o) => { opts = o; return true; }; await fire(del, "click"); await settle(); return [afterEdit, opts.detail, opts.danger, globalThis.__fetchCalls.map((c) => [c.path, JSON.parse(c.body)]), F().toast.textContent.includes("23001")]; })()',
     '[["skynet:proxy:23001",["skynet:proxy:23001"],null],":23001 hotel\\nstill used by: box-a/hotel",true,[["/api/agent-proxies/route-delete",{"port":23001}]],true]', "окно деталей: открыто кликом по строке, «✎» закрывает его и открывает форму порта; «✕» берёт порт с кнопки (форма порта не открыта) и идёт тем же путём, что удаление из формы — confirm называет порт и привязанных агентов, POST порта, тост"),
    ("router_card_opens_routing_unless_on_handle", '', '(() => { const [card] = many("[data-topology-router]", { dataset: { topologyRouter: "router:a" } }); const close = one("[data-topology-router-close]"); bind(); fire(card, "click", { target: { closest: (s) => (s.includes(".topology-handle") ? {} : null) } }); const onHandle = globalThis.__navigated.length; fire(card, "keydown", { key: "Enter", preventDefault() {}, target: { closest: () => null } }); fire(close, "click"); return [onHandle, [...globalThis.__opened], [...globalThis.__navigated], st.ui.topologyRouterDetailId, st.ui.topologyCanvasRouterId]; })()',
     '[0,[],["/routing"],"",""]', "карточка роутера ведёт в Маршрутизацию в ЭТОЙ ЖЕ вкладке (не с ручки/подсказки; 2026-10-17: была новая вкладка); negative: window.open не вызван — новой вкладки нет; закрытие сбрасывает id"),
    ("set_default_reverts_radio_until_confirmed", '', 'await (async () => { const prev = one(\'[data-router-set-default="router:a"][data-output-id="cb:x"]\'); const [radio] = many("[data-router-set-default]", { dataset: { routerSetDefault: "router:a", outputId: "srv:2" }, checked: true, q: { "[data-router-out-row]": { querySelector: () => ({ textContent: " Second " }) } } }); bind(); fire(radio, "change"); const c = confirmState(); const reverted = [radio.checked, prev.checked]; st.ui.pendingConfirm(); await settle(); const saved = calls().find((x) => x[0] === "saveRouters")?.[1][0].rules; return [reverted, c.text.includes("Second"), c.danger, c.shown, saved.default, "dormantDefault" in saved]; })()',
     '[[false,true],true,false,true,"srv:2",false]', "радио «default»: откат до подтверждения (прежнее снова отмечено), не-красный confirm с подписью выхода; подтверждение ставит default и снимает dormantDefault"),
    ("hist_toggles_and_refresh", '', '(() => { const qo = V("canvas._cvQueueHistOpen"), qd = V("canvas._cvQueueHistData"), so = V("canvas._cvSchedHistOpen"), sd = V("canvas._cvSchedHistData"); const [qt] = many("[data-cv-q-hist-toggle]", { dataset: { cvQHistToggle: "n1" } }); const [qr] = many("[data-cv-q-hist-refresh]", { dataset: { cvQHistRefresh: "n1" } }); const [stg] = many("[data-cv-sched-hist-toggle]", { dataset: { cvSchedHistToggle: "n2" } }); bind(); let sp = 0; const ev = { stopPropagation: () => sp++ }; fire(qt, "click", ev); const a = [qo.n1, names().at(-1)]; qd.n1 = { x: 1 }; fire(qt, "click", ev); fire(qt, "click", ev); const b = [qo.n1, names().at(-1)]; fire(qr, "click", ev); const c = [qd.n1, names().at(-1)]; sd.n2 = { y: 1 }; fire(stg, "click", ev); return [a, b, c, so.n2, names().at(-1), sp]; })()',
     '[[true,"_fetchQueueHist"],[true,"renderTopology"],[null,"_fetchQueueHist"],true,"renderTopology",5]', "история очереди/расписания: открыть без данных — запрос; с данными — только перерисовка; обновить — данные сброшены и запрошены"),
    ("group_fold_and_no_source_rules", '', 'await (async () => { const [fold] = many("[data-router-group-fold]", { dataset: { routerGroupFold: "host:x" } }); const [add] = many("[data-router-add-rule]", { dataset: { routerAddRule: "router:a" } }); one(\'[data-router-rule-source="router:a"]\', { value: "p1" }); one(\'[data-router-rule-output="router:a"]\', { value: "srv:2" }); const [del] = many("[data-router-del-rule]", { dataset: { routerDelRule: "router:a", ruleIndex: "0" } }); bind(); fire(fold, "click", { stopPropagation() {} }); fire(add, "click"); fire(del, "click"); await settle(); return [V("routers.topologyOutputsFolded")["host:x"], calls().filter((c) => c[0] === "saveRouters").length]; })()',
     '[true,0]',
     "сворачивание группы машины; negative: кнопки правил по источнику ни к чему не привязаны — их список и форму Маршрутизация не "
     "рисует с 1.3.417, 2026-10-11 код убран"),
    ("quiet_cells_toggle_by_click_and_key", '', 'await (async () => { const [q] = many("[data-router-quiet-toggle]", { dataset: { routerQuietToggle: "m1" } }); bind(); const renders0 = calls().filter((c) => c[0] === "renderTopology").length;'
     ' fire(q, "click", { stopPropagation() {} }); const opened = V("routers.topologyQuietShown").m1; fire(q, "keydown", { key: "Enter", preventDefault() {}, stopPropagation() {} }); const closed = V("routers.topologyQuietShown").m1;'
     ' fire(q, "keydown", { key: "Tab", preventDefault() {}, stopPropagation() {} }); return [opened, closed, V("routers.topologyQuietShown").m1, calls().filter((c) => c[0] === "renderTopology").length - renders0]; })()',
     '[true,false,false,2]',
     "строка «N stopped, no cables» открывается и закрывается щелчком и клавишей Enter, каждый раз — перерисовка; "
     "negative: другая клавиша (Tab) ничего не меняет"),
    ("unassigned_list_shuts_like_a_menu", '', 'await (async () => { const [d] = many("[data-t=\'routing-unassigned\']", { open: false, contains: (t) => t === "inside" }); bind();'
     ' const downs = () => (docListeners.pointerdown || []).slice(); const before = downs().length; d.open = true; fire(d, "toggle"); const added = downs().length - before;'
     ' downs().forEach((fn) => fn({ target: "inside" })); const keptOnInside = d.open; downs().forEach((fn) => fn({ target: "outside" })); const shut = !d.open;'
     ' const left = downs().length - before; d.open = true; fire(d, "keydown", { key: "Escape" }); const esc = d.open; d.open = true; fire(d, "keydown", { key: "a" });'
     ' return [added, keptOnInside, shut, left, esc, d.open]; })()',
     '[1,true,true,0,false,true]',
     "список «unassigned» закрывается, как меню: нажатие мимо него закрывает и снимает свой слушатель, Escape закрывает; "
     "negative: нажатие внутри и другая клавиша — список остаётся открытым"),
    ("attach_detach_with_confirm", '', 'await (async () => { const [at, atc] = many("[data-router-attach]", { dataset: { routerAttach: "skynet:proxy:23002" } }, { dataset: { routerAttach: "skynet:proxy:23001", confirm: "1" } }); const [dt] = many("[data-router-detach]", { dataset: { routerDetach: "skynet:proxy:23001" } }); bind(); fire(at, "click"); await settle(); globalThis.__stubReturns["dialogs.appConfirm"] = async () => false; fire(atc, "click"); await settle(); const refused = calls().filter((c) => c[0] === "setTopologyProxyRoutePolicy").length; globalThis.__stubReturns["dialogs.appConfirm"] = async () => true; fire(atc, "keydown", { key: " ", preventDefault() {} }); await settle(); fire(dt, "click", { stopPropagation() {} }); await settle(); return [refused, calls().filter((c) => c[0] === "setTopologyProxyRoutePolicy").map((c) => c.slice(1))]; })()',
     '[1,[["skynet:proxy:23002",{"routerId":"router:a"}],["skynet:proxy:23001",{"routerId":"router:a"}]]]', "вход прокси в роутер: без подтверждения для свободного, с подтверждением для чужого (отказ — ничего); "
     "negative: кнопка ⊘ «снять из Маршрутизации» ни к чему не привязана — её рисовала только строка клиента входа, а клиент больше не вход Маршрутизации (2026-10-12)"),
    # 2026-10-11: the old canvas insert (open, close, its overlay), the failover button and the inputs
    # toggle have no element on any page; their handlers went, and so did the inputs field of ui.
    ("old_canvas_insert_buttons_bind_nothing", '', 'await (async () => { const oc = one("[data-router-open-canvas]", { dataset: { routerOpenCanvas: "router:a" } }); const cc = one("[data-topology-canvas-close]"); const ov = one("[data-topology-canvas-overlay]"); const fo = one("[data-router-failover-toggle]", { dataset: { routerFailoverToggle: "router:a" } }); const it = one("[data-router-inputs-toggle]"); st.ui.topologyCanvasRouterId = "router:z"; bind(); fire(oc, "click", { currentTarget: oc }); fire(cc, "click"); fire(ov, "click", { target: ov, currentTarget: ov }); fire(fo, "click", { currentTarget: fo }); fire(it, "click"); await settle(); const watched = ["canvasOpenPositions", "canvasInitialView", "cvSetViewport", "renderTopology", "drawCanvasConnectors", "bindCanvasInteractions", "saveRouters"]; return [st.ui.topologyCanvasRouterId, names().filter((n) => watched.includes(n)), "topologyRouterInputsExpanded" in st.ui]; })()',
     '["router:z",[],false]',
     "кнопки старой вставки холста (открыть, закрыть, подложка), failover и раскрытия входов ни к чему не привязаны — "
     "их не рисует ни одна страница, 2026-10-11 код убран: вставка не открылась и не закрылась, цепочка не сохранена; "
     "negative: поля ui раскрытия входов тоже нет"),
    ("hover_links_and_no_input_search", '', '(() => { const outRow = one(\'[data-router-out-row="srv:1"]\'); const [link] = many("[data-router-link-out]", { dataset: { routerLinkOut: "srv:1" } }); globalThis.__qa[\'[data-router-link-out="srv:1"]\'] = [link]; const search = one("[data-router-input-search]", { value: "hot" }); const [pa, pb] = many("[data-router-pill-wrap] [data-pill-name]", { dataset: { pillName: "hotel", pillPort: "23001" } }, { dataset: { pillName: "crane", pillPort: "23101" } }); bind(); fire(link, "mouseenter"); const on = [outRow.classList.has("link-hi"), link.classList.has("link-hi")]; fire(link, "mouseleave"); fire(search, "input"); return [on, outRow.classList.has("link-hi"), "topologyRouterInputSearch" in st.ui, [pa.style.display ?? "", pb.style.display ?? ""]]; })()',
     '[[true,true],false,false,["",""]]',
     "hover подсвечивает строку выхода и его ссылки; negative: поиск по входам ни к чему не привязан — ни поля поиска, ни "
     "пилюль Маршрутизация не рисует, 2026-10-11 код и его поле в ui убраны"),
    ("schedule_editor_flow", '', 'await (async () => { const open = one("[data-router-open-schedule]", { dataset: { routerOpenSchedule: "router:a" } }); const [p1, p2] = many("[data-sched-paint]", { dataset: { schedPaint: "" } }, { dataset: { schedPaint: "srv:2" } }); const clear = one("[data-schedule-clear]"); const save = one("[data-schedule-save]"); bind(); fire(open, "click", { currentTarget: open }); const opened = [m.topologyScheduleRouterId, m.topologyScheduleGrid[0][9], m.topologySchedulePaintOutput]; fire(p2, "click"); const paint = [m.topologySchedulePaintOutput, p2.classList.has("active"), p1.classList.has("active")]; const cell = mkEl({ dataset: { day: "1", hour: "3" } }); globalThis.__qa["[data-sched-cell]"] = [cell]; const grid = one("[data-schedule-grid]"); bind(); fire(grid, "pointerdown", { target: { closest: () => cell }, preventDefault() {} }); const painted = [m.topologyScheduleGrid[1][3], cell.style.background, cell.classList.has("painted")]; const cell2 = mkEl({ dataset: { day: "1", hour: "4" } }); fire(grid, "pointerover", { target: { closest: () => cell2 } }); globalThis.__pointerUp(); fire(grid, "pointerover", { target: { closest: () => mkEl({ dataset: { day: "1", hour: "5" } }) } }); const drag = [m.topologyScheduleGrid[1][4], m.topologyScheduleGrid[1][5]]; fire(clear, "click"); const cleared = [m.topologyScheduleGrid.flat().filter(Boolean).length, cell.classList.has("painted")]; m.topologyScheduleGrid[0][0] = "srv:1"; fire(save, "click"); await settle(); const saved = calls().filter((c) => c[0] === "saveRouters").at(-1)[1][0].rules.schedule; return [opened, paint, painted, drag, cleared, [m.topologyScheduleRouterId, m.topologyScheduleGrid], saved.length]; })()',
     '[["router:a","srv:1","srv:1"],["srv:2",true,false],["srv:2","#c0ffee",true],["srv:2",""],[0,false],["",null],1]',
     "расписание: открытие берёт сетку из правил и кисть — первый выход; выбор кисти; pointerdown красит клетку, pointerover — пока не отпущено; очистка; сохранение через saveRouters и закрытие (pointerup документа биндится один раз на процесс)"),
    ("agent_client_proxy_buttons", '', 'await (async () => { const [rn] = many("[data-agent-rename]", { dataset: { agentRenameClient: "box-a", agentRename: "hotel", agentRenameName: "Hotel" } }); const [ad] = many("[data-client-agent-add]", { dataset: { clientAgentAdd: "box-a" } }); const [cr] = many("[data-client-rename]", { dataset: { clientRename: "box-a", clientName: "Box" } }); const [pe] = many("[data-topology-proxy-edit]", { dataset: { topologyProxyEdit: "skynet:proxy:23001" } }); const [pd] = many("[data-topology-proxy-delete]", { dataset: { topologyProxyDelete: "skynet:proxy:23001" } }); const [ce] = many("[data-topology-client-edit]", { dataset: { hostId: "box-a", currentName: "Box" } }); bind(); let sp = 0; fire(rn, "click", { stopPropagation: () => sp++ }); fire(ad, "click"); fire(cr, "click"); fire(pe, "click"); fire(pd, "click"); fire(ce, "click"); await settle(); return [sp, calls().map((c) => c.join(":"))]; })()',
     '[1,["renameTopologyAgent:box-a:hotel:Hotel","editTopologyClientAlias:box-a:Box","editTopologyClientAlias:box-a:Box"]]',
     "кнопки агента и клиента зовут свои функции с данными из dataset; negative: старая кнопка «＋ добавить агента» "
     "(data-client-agent-add) ни к чему не привязана — второй агент клиента убран с доски; ✎ и 🗑 строк портов Маршрутизации "
     "тоже ни к чему не привязаны — эти строки не рисуются, 2026-10-11 код убран (у формы порта своя кнопка удаления)"),
    ("route_handle_and_proxy_card_hover", '', '(() => { const [h] = many("[data-topology-route-handle]", { dataset: { hostId: "box-a", agentId: "hotel", routeRole: "primary" } }); const [card] = many("[data-topology-proxy]", { dataset: { proxyId: "skynet:proxy:23001" } }); const [pin] = many("[data-topology-proxy-input]", {}); bind(); fire(h, "mouseenter"); fire(h, "mouseleave"); fire(card, "mouseenter"); fire(pin, "dragover", { preventDefault() {}, dataTransfer: {} }); const over = pin.classList.has("drag-over"); fire(pin, "drop", { preventDefault() {} }); return [calls().map((c) => c[0] + (typeof c[1] === "string" ? ":" + c[1] : "")), over, pin.classList.has("drag-over")]; })()',
     '[["highlightTopologyCable:route-box-a-hotel-primary","scheduleClearTopologyCableHighlight","highlightTopologyCable:proxy-skynet:proxy:23001"],true,false]', "наведение на ручку маршрута и карточку прокси подсвечивает их кабель, уход — отложенное снятие; drag-over на входе прокси ставится и снимается"),
    ("at_point_helpers", '', '(() => { globalThis.__atPoint = { closest: (s) => ({ kind: s }) }; const a = [m.topologyLlamaAtPoint(1, 1)?.kind, m.topologyRouterInputAtPoint(1, 1)?.kind, m.topologyCloudAtPoint(1, 1)?.kind]; globalThis.__atPoint = null; return [a, m.topologyLlamaAtPoint(1, 1) ?? null]; })()',
     '[["[data-topology-llama-input]","[data-topology-router-input]","[data-topology-cloud-input]"],null]', "попадания: ближайший вход нужного вида под точкой; ничего под точкой — null"),
    ("clear_pointer_drag", '', '(() => { const src = mkEl(); src.classList.add("dragging"); globalThis.__stubSetters; m.topologyPointerDrag; const live = mkEl(); F().topologyCables = mkEl({ q: { ".topology-cable.live": live } }); const inp = mkEl(); inp.classList.add("drag-over"); globalThis.__qa["[data-topology-router-input]"] = [inp]; m.clearTopologyPointerDrag(); return [inp.classList.has("drag-over"), live.removed, names().includes("flushPendingTopologyRender"), m.topologyPointerDrag]; })()',
     '[false,true,true,null]', "снятие перетаскивания: drag-over убраны, живой кабель удалён, отложенный рендер сброшен"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 28:
        print(f"js topology-dnd FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js topology-dnd: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_topology_dnd.tmp.mjs"
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
        print(f"js topology-dnd FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("биндер доски: модалы, ползунки очереди, расписание, роутер, перетаскивание:")
    for pid, _s, _e, expected, msg in PINS:
        want, have = json.loads(expected), got.get(pid, "\0missing")
        check(have == want, msg if have == want else
              f"{msg}\n        ожидалось {json.dumps(want, ensure_ascii=False)[:200]}"
              f"\n        получено  {json.dumps(have, ensure_ascii=False)[:200]}")
        if have != rev.get(pid, "\0missing"):
            _fail.append(f"пин {pid} зависит от порядка")
    print(f"порядок: {len(PINS)} пинов дают те же значения в обратном порядке" if not _fail else "")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for m in _fail:
            print("  - " + m.splitlines()[0])
        return 1
    print(f"js topology-dnd OK: настоящий модуль в node, {len(PINS)} пинов биндера значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
