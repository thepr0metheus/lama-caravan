#!/usr/bin/env python3
"""Snapshot of static/js/main.js — the board's and the standalone kanban's entry point.

The module is a single DOMContentLoaded handler with two branches. The
snapshot intercepts it at import time and fires it itself; neighbors are
stubs recording their calls, so what's pinned is loading ORDER and WHAT gets
bound, not what the neighbors do. The board: language before the first
render, theme, onboarding, the language-change hook = renderAll, the user
chip (GET /api/auth/me — the chip appears only with sign-in enabled), header
and modal buttons, document-level keys: Escape closes confirm → the cell
editor, in that priority, and cancels dragging, Ctrl/⌘+Enter starts from an
open cell editor; pointermove clears drag-over and drives the live cable,
pointerup over a router input rewires the proxy; resize/scroll redraw cables
through rAF only on the board view; the click delegate (cloud); focusout
resets the delayed render after 60ms; the loader hides
once the board is populated, or after 15s; a loadState failure hides the
loader, sets the error state, shows a toast; after loading — stats/pricing/
route errors and their intervals. The kanban: its own language hook
(renderTopology), a router from ?id= or the default, not found → a message
and error, found → ui identifiers, a viewport from saved positions, the
board monitor, ready.

The DOM is auto-created elements by id (index.html has all of them; the
deliberately-missing ones are listed), selector dicts, a timer queue advanced
by hand, rAF is synchronous. The controller's own cell editor and the classic
single-server form went with the controller's own cells in step 6.9; the pins
that watched their bindings now say that nothing binds them any more.

Run: python3 scripts/test_js_main.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("dialogs,dialog-llamas,cables,canvas,charts,cloud,command-preview,form,llama-edit,memory,model-meta,"
         "onboarding-tours,polling,topology-activity,remote-cells,routers,system-panels,topology-dnd,topology-render,"
         "usage-stats,history,favorites,config-locator,onboarding,models-page,system-page,topology-nodes,topology-modals,topology-proxies,"
         "scout-add")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} }); st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
let now = 0; const timers = []; let tid = 0;
globalThis.setTimeout = (fn, ms) => { timers.push({ id: ++tid, at: now + (Number(ms) || 0), fn, every: 0 }); return tid; };
globalThis.setInterval = (fn, ms) => { timers.push({ id: ++tid, at: now + (Number(ms) || 1), fn, every: Number(ms) || 1 }); return tid; };
globalThis.clearTimeout = globalThis.clearInterval = (id) => { const i = timers.findIndex((t) => t.id === id); if (i >= 0) timers.splice(i, 1); };
const tick = (ms) => { const until = now + ms; for (;;) { const due = timers.filter((t) => t.at <= until).sort((a, b) => a.at - b.at)[0]; if (!due) break; now = due.at; if (due.every) due.at += due.every; else timers.splice(timers.indexOf(due), 1); due.fn(); } now = until; };
Date.now = () => 1_700_000_000_000 + now;
globalThis.requestAnimationFrame = (fn) => { fn(); return 0; };
globalThis.ResizeObserver = class { constructor(cb) { this.cb = cb; globalThis.__ro = this; } observe(el) { this.target = el; } };
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), has: (c) => s.has(c) } };
const mkEl = (id) => ({ id, textContent: "", innerHTML: "", value: "", hidden: true, tabIndex: 0, attrs: {}, dataset: {}, classList: cls(), listeners: {}, children: [], addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, setAttribute(k, v) { this.attrs[k] = v; }, hasAttribute(k) { return k in this.attrs; }, contains: () => false, closest: () => null });
// Элементы по id создаются по требованию (в index.html они есть все); отсутствующие — в списке __missing.
globalThis.__missing = new Set(); globalThis.__els = {};
document.getElementById = (id) => (globalThis.__missing.has(id) ? null : (globalThis.__els[id] ||= mkEl(id)));
globalThis.__q = {}; document.querySelector = (sel) => (Object.prototype.hasOwnProperty.call(globalThis.__q, sel) ? globalThis.__q[sel] : null);
globalThis.__qa = {}; document.querySelectorAll = (sel) => globalThis.__qa[sel] || [];
const docListeners = {}; document.addEventListener = (t, fn, opts) => { (docListeners[t] ||= []).push({ fn, capture: opts === true || !!opts?.capture }); };
const winListeners = {}; globalThis.addEventListener = (t, fn) => { (winListeners[t] ||= []).push(fn); };
document.body = { appendChild() {}, dataset: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } };
globalThis.__plHide = () => { globalThis.__hidden += 1; }; globalThis.__hidden = 0;
// "+ New pool" opens the step window for a pool that does not exist yet (cloud.js POOL_STEPS):
// an object, so its stand-in is a value that writes the call down with the others.
globalThis.__stubValues = { "topology-render.activeView": "topology", "topology-dnd.topologyPointerDrag": null,
  "cloud.POOL_STEPS": { open: (poolId) => { globalThis.__calls.push(["POOL_STEPS.open", poolId]); } } };
globalThis.__calls = []; const rec = (name, ret) => (...a) => { globalThis.__calls.push([name, ...a.map((x) => (x && typeof x === "object" && !Array.isArray(x)) ? (x.id ?? x.routerId ?? "obj") : (typeof x === "function" ? "fn" : x))]); return ret; };
const setv = (key, v) => globalThis.__stubSetters[key](v);
const arec = (name, ret) => async (...a) => { globalThis.__calls.push([name, ...a.map((x) => (typeof x === "function" ? "fn" : x))]); return ret; };
await import(pathToFileURL(process.env.JS_ROOT + "/main.js").href);
const boot = docListeners.DOMContentLoaded[0].fn;
const names = () => globalThis.__calls.map((c) => c[0]);
const calls = () => globalThis.__fetchCalls.map((c) => c.path);
const E = (id) => document.getElementById(id);
const fire = (id, type, ev = {}) => (E(id).listeners[type] || []).forEach((l) => l(ev));
const docFire = (type, ev = {}) => (docListeners[type] || []).forEach((l) => l.fn(ev));
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); };
const reset = () => { st.setState({ config: {} }); st.setTopology({ proxies: [], clients: [], routers: [{ id: "router:default", outputs: [] }, { id: "router:b", outputs: [] }], assignments: {} }); st.ui.pendingConfirm = null; st.ui.latestSystemMonitor = null; st.ui.topologyRouterDetailId = ""; st.ui.topologyCanvasRouterId = "";
  timers.length = 0; now = 0; globalThis.__hidden = 0; globalThis.__els = {}; globalThis.__missing = new Set(); globalThis.__q = {}; globalThis.__qa = {}; globalThis.__calls = []; delete globalThis.ROUTER_STANDALONE; globalThis.location = { pathname: "/board", search: "", hash: "", href: "http://ctl/board" }; globalThis.window = globalThis;
  for (const k of Object.keys(docListeners)) if (k !== "DOMContentLoaded") delete docListeners[k]; for (const k of Object.keys(winListeners)) delete winListeners[k];
  document.body.dataset = {}; setv("topology-render.activeView", "topology"); setv("topology-dnd.topologyPointerDrag", null);
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = { "/api/auth/me": { enabled: false } };
  globalThis.__stubReturns = {
    "dialog-llamas.initDialogLlamas": rec("initDialogLlamas"), "i18n.initLanguage": arec("initLanguage", "en"), "onboarding-tours.initOnboarding": rec("initOnboarding"),
    "scout-add.mountScoutAdd": rec("mountScoutAdd"), "topology-nodes.openIncidentsModal": rec("openIncidentsModal"),
    "polling.loadState": arec("loadState"), "polling.bindMonitorDrawer": rec("bindMonitorDrawer"), "polling.startTopologyMonitor": rec("startTopologyMonitor"),
    "topology-render.renderAll": rec("renderAll"), "topology-render.renderTopology": rec("renderTopology"), "topology-render.setActiveView": rec("setActiveView"), "topology-render.refreshTopology": arec("refreshTopology"), "topology-render.flushPendingTopologyRender": rec("flushPendingTopologyRender"),
    "model-meta.fetchProxyDailyStats": arec("fetchProxyDailyStats"), "model-meta.fetchModelPricing": arec("fetchModelPricing"), "topology-activity.refreshRouteErrBadges": arec("refreshRouteErrBadges"),
    "cables.drawTopologyCables": rec("drawTopologyCables"), "cables.drawLiveTopologyCable": rec("drawLiveTopologyCable"), "canvas.drawCanvasConnectors": rec("drawCanvasConnectors"), "canvas.canvasOpenPositions": rec("canvasOpenPositions", { "n1": { x: 1 } }), "canvas.canvasInitialView": rec("canvasInitialView", { tx: 5, ty: 6, scale: 1 }), "canvas.cvSetViewport": rec("cvSetViewport"),
    "llama-edit.closeConfirmModal": rec("closeConfirmModal"),
    "remote-cells.submitRemoteLlamaStart": arec("submitRemoteLlamaStart"), "routers.rebindProxyRouter": arec("rebindProxyRouter"), "topology-dnd.clearTopologyPointerDrag": rec("clearTopologyPointerDrag"), "topology-dnd.topologyRouterInputAtPoint": () => globalThis.__routerAt || null,
    "usage-stats.openUsageStatsModal": rec("openUsageStatsModal"), "charts.systemSamples": () => [{ t: 1 }], "charts.drawTopologyServerStats": rec("drawTopologyServerStats"),
  };
  globalThis.__routerAt = null; };
reset();
const bootBoard = async () => { await boot(); await settle(); };
const out = {};
"""

PINS = [
    # 2026-10-12: the pools left the main board for the kanban, and so did the list that ordered them.
    ("board_binds_no_pool_list",
     '',
     'await (async () => { await bootBoard(); const el = E("boardServerCards"); return [Object.keys(el.listeners), el.dataset.serverOrderBound || ""]; })()',
     '[[],""]',
     "negative: на главной доске нет списка пулов — и ничего не вешается на его место (пулы на канбане, 2026-10-12)"),
    ("board_boot_order", '', 'await (async () => { await bootBoard(); const n = names(); const pos = (x) => n.indexOf(x); return [n.slice(0, 5), document.documentElement.lang === "en", pos("bindMonitorDrawer") >= 0, pos("loadState") < pos("setActiveView"), n.filter((x) => x === "renderAll").length, calls(), timers.map((t) => t.every).filter(Boolean), n.slice(-3), n.filter((x) => x === "mountScoutAdd").length]; })()',
     '[["initDialogLlamas","initOnboarding","mountScoutAdd","bindMonitorDrawer","loadState"],true,true,true,0,["/api/auth/me"],[60000,86400000,60000],["fetchProxyDailyStats","fetchModelPricing","refreshRouteErrBadges"],1]',
     "доска (i18n настоящий, initLanguage не записывается): онбординг после ламы, поле «＋ Добавить скаута» связано один раз и до загрузки состояния, монитор-ящик привязан, loadState → setActiveView, renderAll не зовётся сам (только хук языка), чип пользователя спрошен, три интервала: 60 с / сутки / 60 с"),
    ("board_ready_hides_loader_when_filled", '', 'await (async () => { await bootBoard(); tick(500); const early = globalThis.__hidden; E("topologyClients").children = [1]; globalThis.__q["[data-node-cell-port]"] = {}; tick(200); const filled = globalThis.__hidden; document.body.dataset.tState = "ready"; tick(200); await settle(); return [early, filled, globalThis.__hidden, timers.some((t) => !t.every && t.at > now)]; })()', '[0,0,1,false]',
     "лоадер прячется, когда доска сказала «готово» (её первая отрисовка, refreshTopology); опрос прекращается. negative: "
     "лейна клиентов и порт ячейки — ещё не готовность: раньше лоадер ждал ячейку, а на главной доске ячеек нет с окон машин, "
     "и доска без машин стояла под заставкой все 15 с (2026-10-11)"),
    ("board_ready_on_error_too", '', 'await (async () => { await bootBoard(); tick(500); const early = globalThis.__hidden; document.body.dataset.tState = "error"; tick(200); await settle(); return [early, globalThis.__hidden]; })()', '[0,1]',
     "доска сказала, почему не готова, — лоадер прячется: причина на странице, а не под заставкой"),
    ("board_marks_its_view", '', 'await (async () => { const bv = (await import(pathToFileURL(process.env.JS_ROOT + "/board-view.js").href)).BOARD_VIEW; document.documentElement.dataset = {};'
     ' await bootBoard(); const main = document.documentElement.dataset.boardView; reset(); bv.machine = "box"; document.documentElement.dataset = {};'
     ' try { await bootBoard(); return [main, document.documentElement.dataset.boardView]; } finally { bv.machine = null; } })()', '["main","machine"]',
     "до первой отрисовки страница говорит, какая она доска (data-board-view на <html>): главная или окно машины — по ней стили прячут лишнее"),
    ("board_machine_open_link", '', 'await (async () => { await bootBoard(); const opened = []; globalThis.open = (...a) => { opened.push(a.slice(0, 2)); return { focus() {} }; };'
     ' const LINK = "[data-machine-open]", CARD = ".machine-glance[data-node-id]", OWN = "[data-open-chart],[data-open-route-activity],a,button,input,select,textarea";'
     ' let followed = 0; const link = { dataset: { machineOpen: "h2" } }; const card = { dataset: { nodeId: "h3" }, querySelector: (sel) => (sel === LINK ? { click() { followed += 1; } } : null) };'
     ' const ev = (hits, extra = {}) => ({ target: { closest: (sel) => hits[sel] ?? null }, button: 0, prevented: 0, preventDefault() { this.prevented += 1; }, ...extra });'
     ' const plain = ev({ [LINK]: link, [CARD]: card, [OWN]: link }); fire("topologyLlamaServers", "click", plain);'
     ' const meta = ev({ [LINK]: link, [CARD]: card, [OWN]: link }, { metaKey: true }); fire("topologyLlamaServers", "click", meta);'
     ' const body = ev({ [CARD]: card }); fire("topologyLlamaServers", "click", body);'
     ' const chart = ev({ [CARD]: card, [OWN]: {} }); fire("topologyLlamaServers", "click", chart);'
     ' const shifted = ev({ [CARD]: card }, { shiftKey: true }); fire("topologyLlamaServers", "click", shifted);'
     ' const off = ev({}); fire("topologyLlamaServers", "click", off); const before = followed;'
     ' globalThis.open = () => null; const refused = ev({ [LINK]: link, [CARD]: card, [OWN]: link }); fire("topologyLlamaServers", "click", refused);'
     ' const refusedCard = ev({ [CARD]: card }); fire("topologyLlamaServers", "click", refusedCard);'
     ' delete globalThis.open; return [opened, plain.prevented, meta.prevented, refused.prevented, off.prevented, before, followed, (E("topologyLlamaServers").listeners.click || []).length]; })()',
     '[[["/machine?host=h2","caravan-machine-h2"],["/machine?host=h3","caravan-machine-h3"]],1,0,0,0,0,1,1]',
     "машину открывает её имя и вся карточка (2026-10-12: кнопки ↗ Open больше нет) — окно по адресу и имени, слушатель один, "
     "на статичной лейне; negative: щелчок с модификатором и окно, которое браузер не дал, идут по ссылке имени (без preventDefault), "
     "а щелчок по карточке, которой окно не дали, — тоже по ней, а не впустую; график и кнопка на карточке открывают своё, не машину; "
     "щелчок мимо карточек — ничего"),
    ("board_ready_gives_up_after_15s", '', 'await (async () => { await bootBoard(); tick(15200); await settle(); return globalThis.__hidden; })()', '1', "boundary: доска так и не заполнилась — лоадер всё равно прячется через 15 с"),
    ("board_loadstate_failure", 'globalThis.__stubReturns["polling.loadState"] = async () => { throw new Error("state down"); };', 'await (async () => { await bootBoard(); return [globalThis.__hidden, document.body.dataset.tState, document.body.dataset.tStateDetail, E("toast").textContent, names().includes("setActiveView"), names().includes("fetchProxyDailyStats")]; })()',
     '[1,"error","state down","state down",false,true]', "negative: отказ loadState — лоадер спрятан, состояние error с причиной, тост; вид не переключается, а фоновые загрузки всё равно идут"),
    ("board_user_chip_only_when_signed_in", '', 'await (async () => { await bootBoard(); const off = E("userChip").hidden; reset(); globalThis.__fetchReply["/api/auth/me"] = { enabled: true, authenticated: true, user: "admin", role: "viewer" }; await bootBoard(); return [off, E("userChip").hidden, E("userChipName").textContent, docListeners.click.filter((l) => l.capture).length]; })()',
     '[true,false,"admin · viewer",1]', "чип пользователя: скрыт без входа; с входом — имя с суффиксом роли и закрытие меню в capture-фазе"),
    ("board_header_buttons", '', 'await (async () => { await bootBoard(); fire("systemInfoBtn", "click"); fire("usageStatsBtn", "click"); await settle(); return [globalThis.location.href, names().filter((x) => x === "openUsageStatsModal"), ["gemmaTextBoostBtn", "gemmaVisionBtn", "textOnlyBtn", "revertBtn"].filter((id) => Object.keys(E(id).listeners).length)]; })()',
     '["/system",["openUsageStatsModal"],[]]',
     "кнопки заголовка: System — переход, статистика; negative: кнопки классической формы (gemma text/vision, «без mmproj», откат) ничем не связаны — форма ушла с ячейками контроллера (шаг 6.9)"),
    ("board_incidents_button", '', 'await (async () => { await bootBoard(); fire("boardIncidentsBtn", "click"); await settle(); return names().filter((x) => x === "openIncidentsModal").length; })()',
     '1',
     "⚠ в строке Pools открывает окно инцидентов — привязан один раз при загрузке, а не при каждой перерисовке узла контроллера"),
    ("board_confirm_trio", '', 'await (async () => { await bootBoard(); fire("confirmCancel", "click"); let ran = 0; st.ui.pendingConfirm = () => ran++; fire("confirmDelete", "click"); fire("confirmOverlay", "click", { target: { id: "confirmOverlay" } }); fire("confirmOverlay", "click", { target: { id: "inner" } }); return [names().filter((x) => x === "closeConfirmModal").length, ran]; })()', '[2,1]', "общий confirm: отмена и подложка закрывают, содержимое — нет, подтверждение зовёт pendingConfirm"),
    ("escape_priority_confirm_then_remote", '', 'await (async () => { await bootBoard(); const n0 = names().length; E("confirmOverlay").hidden = false; E("llamaRemoteEditOverlay").hidden = false; E("topologyLlamaEditOverlay").hidden = false; docFire("keydown", { key: "Escape" }); const a = names().slice(-1)[0]; E("confirmOverlay").hidden = true; docFire("keydown", { key: "Escape" }); const b = [E("llamaRemoteEditOverlay").hidden, names().length - n0]; docFire("keydown", { key: "Escape" }); return [a, ...b, names().length - n0, E("topologyLlamaEditOverlay").hidden]; })()',
     '["closeConfirmModal",true,1,1,false]', "Escape: сначала confirm, потом редактор ячейки (прячется); negative: третий Escape ничего не зовёт — своего редактора у контроллера нет (шаг 6.9), его оверлей никто не закрывает"),
    ("escape_clears_drag", '', 'await (async () => { await bootBoard(); setv("topology-dnd.topologyPointerDrag", { proxyId: "p1" }); docFire("keydown", { key: "Escape" }); return names().includes("clearTopologyPointerDrag"); })()', 'true', "Escape при перетаскивании — снимает перетаскивание"),
    ("ctrl_enter_starts_from_the_cell_editor", '', 'await (async () => { await bootBoard(); const n0 = names().length; E("topologyLlamaEditOverlay").hidden = false; let p = 0; docFire("keydown", { key: "Enter", ctrlKey: true, preventDefault: () => p++ }); await settle(); const before = [p, names().length - n0]; E("llamaRemoteEditOverlay").hidden = false; docFire("keydown", { key: "Enter", metaKey: true, preventDefault: () => p++ }); await settle(); return [before, p, names().includes("submitRemoteLlamaStart")]; })()',
     '[[0,0],1,true]', "Ctrl/⌘+Enter: открыт редактор ячейки — старт, событие погашено; negative: оверлей прежнего редактора контроллера не сохраняет ничего"),
    ("editor_overlay_escape_in_capture", '', 'await (async () => { await bootBoard(); const ov = E("llamaRemoteEditOverlay"); ov.hidden = false; let sp = 0; ov.listeners.keydown[0]({ key: "Escape", stopPropagation: () => sp++ }); const closed = ov.hidden; ov.listeners.keydown[0]({ key: "Escape", stopPropagation: () => sp++ }); return [ov.tabIndex, sp, closed, (E("topologyLlamaEditOverlay").listeners.keydown || []).length]; })()', '[-1,1,true,0]',
     "Escape на самом оверлее редактора ячейки (capture): закрывает и гасит; на скрытом — ничего; оверлей фокусируемый; negative: на оверлее прежнего редактора контроллера слушателя нет"),
    ("pointermove_drag_over_and_live_cable", '', 'await (async () => { await bootBoard(); setv("topology-dnd.topologyPointerDrag", { proxyId: "p1" }); const stale = { classList: cls() }; stale.classList.add("drag-over"); globalThis.__qa["[data-topology-router-input]"] = [stale]; const target = { classList: cls(), dataset: { routerId: "router:b" } }; globalThis.__routerAt = target; docFire("pointermove", { clientX: 10, clientY: 20 }); return [stale.classList.has("drag-over"), target.classList.has("drag-over"), globalThis.__calls.find((c) => c[0] === "drawLiveTopologyCable")?.slice(1)]; })()',
     '[false,true,[10,20]]', "pointermove при перетаскивании: прежние drag-over сняты, вход под курсором подсвечен, живой кабель ведётся к курсору"),
    ("pointermove_without_drag_is_noop", '', 'await (async () => { await bootBoard(); docFire("pointermove", { clientX: 1, clientY: 1 }); return names().includes("drawLiveTopologyCable"); })()', 'false', "negative: без перетаскивания pointermove ничего не делает"),
    ("pointerup_rebinds_on_router_input", '', 'await (async () => { await bootBoard(); setv("topology-dnd.topologyPointerDrag", { proxyId: "p1" }); globalThis.__routerAt = { dataset: { routerId: "router:b" } }; docFire("pointerup", { clientX: 1, clientY: 1 }); await settle(); const a = globalThis.__calls.find((c) => c[0] === "rebindProxyRouter"); globalThis.__routerAt = null; globalThis.__calls = []; docFire("pointerup", {}); return [a?.slice(1), names().includes("clearTopologyPointerDrag"), names().includes("rebindProxyRouter")]; })()',
     '[["p1","router:b"],true,false]', "pointerup над входом роутера перецепляет прокси; мимо входа — только снятие перетаскивания"),
    ("resize_and_scroll_redraw_only_on_board", '', 'await (async () => { await bootBoard(); winListeners.resize[0](); winListeners.scroll[0](); const a = names().filter((x) => x === "drawTopologyCables").length; setv("topology-render.activeView", "system"); winListeners.resize[0](); winListeners.scroll[0](); return [a, names().filter((x) => x === "drawTopologyCables").length]; })()', '[2,2]',
     "resize и scroll перерисовывают кабели на виде доски; на другом виде — нет"),
    ("resize_observer_on_board", 'globalThis.__q[".topology-board"] = { id: "board" };', 'await (async () => { await bootBoard(); globalThis.__ro.cb(); return [globalThis.__ro.target.id, names().filter((x) => x === "drawTopologyCables").length]; })()', '["board",1]', "наблюдатель размера доски перерисовывает кабели"),
    ("classic_and_te_forms_unbound", '', 'await (async () => { await bootBoard(); return ["configForm", "MODEL_FILE", "MMPROJ_FILE", "OFFLOAD_MMPROJ", "SPEC_DRAFT_MODEL_FILE", "SPEC_ENABLED", "CHAT_TEMPLATE_FILE", "LLAMA_MODELS_DIR", "topologyLlamaEditForm", "te-MODEL_FILE", "te-MMPROJ_FILE", "te-OFFLOAD_MMPROJ", "te-SPEC_DRAFT_MODEL_FILE", "te-SPEC_ENABLED", "te-CHAT_TEMPLATE_FILE"].filter((id) => Object.keys(E(id).listeners).length); })()',
     '[]', "negative: ни поля классической формы одиночного сервера, ни поля редактора ячеек контроллера (te-) никто не слушает — обе ушли с его ячейками в шаге 6.9"),
    ("click_delegate_cloud_only", '', 'await (async () => { await bootBoard(); const n0 = names().length; const dd = { hidden: false }; globalThis.__qa[".port-dropdown:not([hidden])"] = [dd]; docFire("click", { target: { closest: (s) => s === "[data-topo-add-cloud]" ? {} : null, id: "" } }); docFire("click", { target: { closest: (s) => s === "[data-topo-edit-close]" ? {} : null, id: "" } }); docFire("click", { target: { closest: () => null, id: "topologyLlamaEditOverlay" } }); docFire("click", { target: { closest: () => null, id: "topologyLlamaEditSaveRestart" } }); await settle(); return [dd.hidden, globalThis.__calls.slice(n0)]; })()',
     '[false,[]]', "negative: «＋ New pool» на главной доске больше ничего не открывает — новый пул делают на канбане (2026-10-12); выпадашки портов классической формы, закрытие, подложка и «сохранить и перезапустить» прежнего редактора контроллера тоже ничего не делают"),
    ("action_and_view_buttons_unbound_focusout_delays", 'globalThis.__qa["[data-action]"] = [{ dataset: { action: "restart" }, listeners: {}, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } }]; globalThis.__qa["[data-view-tab]"] = [{ dataset: { viewTab: "system" }, listeners: {}, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); } }];',
     'await (async () => { await bootBoard(); const bound = [Object.keys(globalThis.__qa["[data-action]"][0].listeners).length, Object.keys(globalThis.__qa["[data-view-tab]"][0].listeners).length]; docFire("focusout"); const before = names().includes("flushPendingTopologyRender"); tick(60); return [bound, before, names().includes("flushPendingTopologyRender")]; })()',
     '[[0,0],false,true]', "negative: кнопки действий одиночного сервера и вкладки вида не связаны — классический вид ушёл; focusout сбрасывает отложенный рендер через 60 мс, не сразу"),
    ("standalone_boot_draws_the_pools_board", 'globalThis.ROUTER_STANDALONE = true; globalThis.location.search = "?id=router:b";',
     'await (async () => { await bootBoard(); const n = names(); return [n.includes("renderAll"), n.includes("bindMonitorDrawer"), st.ui.topologyRouterDetailId || "",'
     ' st.ui.topologyCanvasRouterId || "", n.includes("cvSetViewport") || n.includes("canvasInitialView") || n.includes("canvasOpenPositions"),'
     ' n.includes("renderTopology"), n.includes("startTopologyMonitor"), globalThis.__hidden, document.body.dataset.tState, calls(), n.includes("fetchModelPricing")]; })()',
     '[false,false,"","",false,true,true,1,"ready",["/api/auth/me","/health"],true]',
     "канбан (2026-10-12: доска пулов, pool-board.js): без доски и монитор-ящика; рендер, монитор, лоадер спрятан, ready; версия из /health; "
     "цены подгружены; negative: ?id= роутера больше ничего не называет — ни ui-идентификаторов роутера, ни вьюпорта холста"),
    ("standalone_topology_refused", 'globalThis.ROUTER_STANDALONE = true; globalThis.__stubReturns["topology-render.refreshTopology"] = async () => { throw new Error("controller is down"); };',
     'await (async () => { await bootBoard(); await settle(); return [document.body.dataset.tState, document.body.dataset.tStateDetail, globalThis.__hidden, E("toast").textContent,'
     ' names().includes("renderTopology"), names().includes("startTopologyMonitor")]; })()',
     '["error","controller is down",1,"controller is down",false,false]',
     "negative: топологию не прочитать — состояние error с причиной, лоадер спрятан, тост; ни рендера, ни монитора"),
    ("standalone_confirm_and_escape", 'globalThis.ROUTER_STANDALONE = true;', 'await (async () => { await bootBoard(); E("confirmOverlay").hidden = false; docFire("keydown", { key: "Escape" }); fire("confirmCancel", "click"); return names().filter((x) => x === "closeConfirmModal").length; })()', '2', "канбан: общий confirm закрывается Escape и отменой"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    # 23 since step 6.9: the controller's own cell editor and classic form went,
    # and the pins that watched their bindings folded into negatives.
    if len(PINS) < 23:
        print(f"js main FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js main: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_main.tmp.mjs"
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
        print(f"js main FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("main: загрузка доски и канбана, привязки, клавиши, перетаскивание:")
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
    print(f"js main OK: настоящий модуль в node, {len(PINS)} пинов входа значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
