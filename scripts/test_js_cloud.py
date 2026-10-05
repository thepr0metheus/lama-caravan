#!/usr/bin/env python3
"""Snapshot of static/js/cloud.js — cloud accounts, model blocks, bridges; the write paths.

By volume, this module is the second-largest write door after the routers:
six paths (`saveCloudAccount`, `saveCloudBlock`, `deleteCloudBlock`,
`deleteCloudAccount`, `startCloudOauthLogin`, `pollCloudOauth`), and every one
of them had lived without a test before this snapshot. What's worth pinning
by VALUE here: an account's and a block's ids are derived from the name as a
slug, with a counted suffix; the context window goes out on the wire even
when empty — empty means "not set", not zero (a trap this code had fallen
into before); changing an existing block's model, and a second block for the
same model, both require confirmation; a key failure stops the chain before
blocks get auto-created.

Rendering the lane: blocks are sorted from expensive to cheap, a model
outside the provider's list is flagged, bridges (kind=service) sit on their
own block's card, a bridge with no block lands in the orphan strip (otherwise
it would sit listening on a port, invisible and undeletable), memoization by
key skips redrawing the lane when nothing changed.

The module is loaded FOR REAL (scripts/_js_harness.mjs). `usage-stats` is
real too: it exports Map caches, and the harness's stub turns any export into
a function — `.get` on a function would be a harness artifact, not real
behaviour. DOM-heavy neighbors are stubbed: polling, remote-cells
topology-render, dialogs
(`appConfirm`), canvas, and others.

Run: python3 scripts/test_js_cloud.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("polling,remote-cells,topology-render,dialogs,topology-dnd,canvas,charts,cables,history,favorites,"
         "config-locator,system-panels,onboarding,onboarding-tours,dialog-llamas,models-page,system-page,memory,"
         "command-preview,llama-edit,topology-nodes,topology-modals,topology-activity,topology-proxies,routers")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
st.setTopology({ proxies: [], clients: [], routers: [], assignments: {} });
const mm = await import(pathToFileURL(process.env.JS_ROOT + "/model-meta.js").href);
const m = await import(pathToFileURL(process.env.JS_ROOT + "/cloud.js").href);
const cm = await import(pathToFileURL(process.env.JS_ROOT + "/cloud-models.js").href);
const us = await import(pathToFileURL(process.env.JS_ROOT + "/usage-stats.js").href);
globalThis.location.hostname = "ctl";
// Форма модала читается через document.querySelector(selector): словарь по селектору,
// чего нет — null, как в браузере.
globalThis.__q = {};
document.querySelector = (s) => (Object.prototype.hasOwnProperty.call(globalThis.__q, s) ? globalThis.__q[s] : null);
globalThis.__opened = []; globalThis.open = (u) => { globalThis.__opened.push(String(u)); };
// Таймеры записываются с меткой источника: повторный опрос OAuth отличим от
// таймера тоста, который ставит utils.toast.
globalThis.__timers = []; globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push((String(fn).includes("pollCloudOauth") ? "poll:" : "other:") + (Number(ms) || 0)); return 0; };
const toastEl = () => ({ textContent: "", classList: { add() {}, remove() {} } });
const toastText = () => globalThis.__fields.toast.textContent;
const laneEl = () => ({ innerHTML: "", dataset: {}, addEventListener() {}, querySelector: () => null });
const lane = () => globalThis.__fields.topologyCloudProviders.innerHTML;
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body === null ? null : JSON.parse(c.body) }));
const PRESETS = () => [
  { type: "openai", name: "OpenAI", baseUrl: "https://api.openai.com/v1", authModes: ["apiKey"] },
  { type: "openai-subscription", name: "ChatGPT Plus", baseUrl: "https://chatgpt.com/backend-api", authModes: ["oauth"], accountType: "openai-subscription", oauth: { clientId: "cid" } },
  { type: "custom", name: "Custom", authModes: ["apiKey", "noKey"] },
];
const ACCOUNTS = () => [
  { id: "openai-subscription", type: "openai", name: "OpenAI (ChatGPT Plus)", baseUrl: "https://chatgpt.com/backend-api", accountType: "openai-subscription", authMode: "oauth", hasCredential: true, credentialKind: "oauth" },
  { id: "ollama", type: "ollama", name: "Ollama cloud", baseUrl: "https://ollama.com", authMode: "apiKey", hasCredential: true, credentialKind: "apiKey", keyLast4: "ab12" },
  { id: "bare", type: "custom", name: "Bare", baseUrl: "http://10.0.0.9:8000/v1", authMode: "apiKey", hasCredential: false },
];
const BLOCKS = () => [
  { id: "gpt-5-6-luna", accountId: "openai-subscription", model: "gpt-5.6-luna", name: "gpt-5.6-luna", exposed: true },
  { id: "gpt-5-6-terra", accountId: "openai-subscription", model: "gpt-5.6-terra", name: "gpt-5.6-terra", exposed: true, contextLength: 158000 },
  { id: "deepseek-v4-flash", accountId: "ollama", model: "deepseek-v4-flash", contextAuto: true },
];
const BRIDGES = () => [
  { id: "controller:proxy:8083", port: 8083, kind: "service", providerId: "gpt-5-6-terra", label: "voice bridge" },
  { id: "controller:proxy:8084", port: 8084, kind: "service", providerId: "gone", label: "orphan" },
  { id: "controller:proxy:23001", port: 23001, providerId: "gpt-5-6-terra", label: "agent proxy" },
];
const TOPO = (extra = {}) => ({ proxies: [], clients: [], routers: [], assignments: {}, cloudProviderPresets: PRESETS(), cloudAccounts: ACCOUNTS(), cloudProviders: BLOCKS(), ...extra });
const reset = () => {
  st.setState({ config: {} }); st.setTopology(TOPO());
  Object.keys(mm.modelPricing).forEach((k) => delete mm.modelPricing[k]);
  mm.modelPricing["gpt-5.6-terra"] = { inputPer1M: 10, outputPer1M: 30 };
  mm.modelPricing["gpt-5.6-luna"] = { inputPer1M: 1, outputPer1M: 3 };
  m.topologyCloudModelCache.clear(); m.closeCloudBlockModal(); m.closeCloudProviderModal();
  globalThis.__clock = 1000000; m.MODEL_LIST_ASKS.now = () => globalThis.__clock; m.MODEL_LIST_ASKS.failedAt.clear();
  st.ui._lastCloudProvidersKey = ""; st.ui.cloudModelsOpen = {}; st.ui.bridgeBlockChoice = {};
  globalThis.__fields = { toast: toastEl(), topologyCloudProviders: laneEl() }; globalThis.__q = {};
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__opened.length = 0; globalThis.__timers.length = 0;
  globalThis.__stubReturns = { "dialogs.appConfirm": async () => true };
};
reset();
// openCloudBlockModal сам тянет список моделей аккаунта — для пинов ЗАПИСИ этот
// GET не интересен, счётчик вызовов начинается после открытия.
const openBlock = (b, a) => { m.openCloudBlockModal(b, a); globalThis.__fetchCalls.length = 0; };
// api() = fetch → response.json() → then: несколько микротиков; setImmediate не
// подменён и даёт настоящий макротик, за который всё это оседает.
const settle = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setImmediate(r)); };
const polls = () => globalThis.__timers.filter((x) => x.startsWith("poll:"));
// The "new model" window: strings from en.js, a provider with two models in
// use (two cables into one, the default on the other) and a batch of newcomers.
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const fill = (s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => v[k]);
const escapeHtmlLike = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const NM_T = 10000000;   // seconds; newcomers came an hour ago, a week is 604800 s
const NM_NOW = NM_T * 1000;
const NM_TOP = (blocks) => ({ cloudAccounts: [{ id: "a", name: "OpenAI" }],
  routers: [{ rules: { default: "cb:mini" }, graph: { edges: [{ to: "out:cb:sol" }, { to: "out:cb:sol" }] } }],
  cloudProviders: blocks || [
    { id: "sol", accountId: "a", model: "gpt-6-sol", exposed: true },
    { id: "mini", accountId: "a", model: "gpt-5-mini", exposed: true },
    { id: "zeta", accountId: "a", model: "zeta-9", newSince: NM_T - 3600 },
    { id: "sol61", accountId: "a", model: "gpt-6.1-sol", newSince: NM_T - 3600 },
    { id: "sol62", accountId: "a", model: "gpt-6.2-sol", newSince: NM_T - 3600, announced: true },
  ] });
const NMA = (over = {}) => {
  const log = { asks: [], calls: [], notes: [], applied: [] };
  const a = new cm.NewModelAnnouncer({
    dialog: async (msg, opts) => { log.asks.push({ msg, opts }); return "answer" in over ? over.answer : null; },
    call: async (path, o) => { log.calls.push([path, JSON.parse(o.body)]); if (over.fail) throw new Error("controller is down");
      return "res" in over ? over.res : { moved: 3, topology: { t: 1 } }; },
    notify: (x) => log.notes.push(x), apply: (top) => log.applied.push(top), now: () => NM_NOW, quiet: () => over.quiet !== false });
  return [a, log];
};
// "⇄ Move cables…": a gone model two cables lead to, and where they may go.
const GM_TOP = (extra = []) => ({ cloudAccounts: [{ id: "a", name: "OpenAI" }],
  routers: [{ rules: {}, graph: { edges: [{ to: "out:cb:old" }, { to: "out:cb:old" }, { to: "out:cb:sol7" }] } }],
  cloudProviders: [
    { id: "old", accountId: "a", model: "gpt-6-sol", exposed: true, unlisted: true },
    { id: "gone2", accountId: "a", model: "gpt-5-nano", unlisted: true },
    { id: "misc", accountId: "a", model: "o9-mini" },
    { id: "luna", accountId: "a", model: "gpt-6-luna" },
    { id: "terra", accountId: "a", model: "gpt-6-terra", exposed: true },
    { id: "sol7", accountId: "a", model: "gpt-7-sol", exposed: true },
    ...extra,
  ] });
// Closing a model's port: sol has two ports, luna one, terra none; two cables lead to sol.
const PC_T = 1790000000;
const PC_TOP = () => ({ cloudAccounts: [{ id: "a", name: "OpenAI" }],
  routers: [{ rules: {}, graph: { edges: [{ to: "out:cb:sol" }, { to: "out:cb:sol" }] } }],
  proxies: [{ port: 23009, kind: "service", providerId: "sol", lastRequestAt: 0 },
    { port: 23004, kind: "service", providerId: "sol", lastRequestAt: PC_T },
    { port: 23005, kind: "service", providerId: "luna", lastRequestAt: 0 }],
  cloudProviders: [{ id: "sol", accountId: "a", model: "gpt-6-sol", exposed: true },
    { id: "luna", accountId: "a", model: "gpt-6-luna", exposed: true }, { id: "terra", accountId: "a", model: "gpt-5.6-terra" }] });
const PCL = (over = {}) => {
  const log = { asks: [], confirms: [], calls: [], notes: [], applied: [] };
  const c = new cm.PortCloser({
    dialog: async (msg, opts) => { log.asks.push({ msg, opts }); return "answer" in over ? over.answer : null; },
    confirm: async (msg, opts) => { log.confirms.push({ msg, opts }); return "ok" in over ? over.ok : true; },
    call: async (path, o) => {
      log.calls.push(o ? [path, JSON.parse(o.body)] : [path]);
      if (path.startsWith("/api/cloud-blocks/refs")) { if (over.refsFail) throw new Error("refs down"); return "refs" in over ? over.refs : { held: { cables: 0, rules: [] } }; }
      if (over.fail) throw new Error("controller is down");
      return "res" in over ? over.res : { closed: [0], topology: { t: 9 } };
    },
    notify: (x) => log.notes.push(x), apply: (top) => log.applied.push(top), now: () => NM_NOW });
  return [c, log];
};
const pcWhen = (at) => new Date(at * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const GMC = (over = {}) => {
  const log = { asks: [], calls: [], notes: [], applied: [] };
  const g = new cm.GoneModelCables({
    dialog: async (msg, opts) => { log.asks.push({ msg, opts }); return "answer" in over ? over.answer : null; },
    call: async (path, o) => { log.calls.push([path, JSON.parse(o.body)]); if (over.fail) throw new Error("controller is down");
      return "res" in over ? over.res : { moved: 2, topology: { t: 3 } }; },
    notify: (x) => log.notes.push(x), apply: (top) => log.applied.push(top), now: () => NM_NOW });
  return [g, log];
};
const out = {};
"""

PINS = [
    # ── id from the name ──
    ("slug_from_display_name", '', 'm.topologyCloudSlug("OpenAI (ChatGPT Plus)")', '"openai-chatgpt-plus"',
     "слаг: строчные, всё лишнее — в дефис, края обрезаны"),
    ("slug_empty_is_acct", '', '[m.topologyCloudSlug(""), m.topologyCloudSlug("!!!")]', '["acct","acct"]',
     "negative: пустое имя и имя из одних знаков — «acct», а не пустой id"),
    ("slug_cut_to_40", '', 'm.topologyCloudSlug("a".repeat(60)).length', '40', "boundary: слаг режется до 40 символов"),
    ("unique_id_counts_up", '', '[m.topologyCloudUniqueId("x", ["x", "x-2"]), m.topologyCloudUniqueId("x", [])]', '["x-3","x"]',
     "занятый id получает суффикс -2, -3…; свободный остаётся как есть"),
    ("preset_by_type", '', '[m.topologyCloudPresetByType("openai")?.name, m.topologyCloudPresetByType("nope")]', '["OpenAI",null]',
     "пресет по типу; неизвестный тип — null, не {}"),
    # ── account modal: opening ──
    ("select_type_fills_form_from_preset", '',
     '(() => { m.selectCloudProviderType("openai-subscription"); const f = st.ui.topologyCloudForm; return [f.isNew, f.name, f.baseUrl, f.authMode, f.oauthConfig.clientId, st.ui.topologyCloudModalOpen, st.ui.topologyCloudPickerOpen]; })()',
     '[true,"ChatGPT Plus","https://chatgpt.com/backend-api","oauth","cid",true,false]',
     "выбор типа: форма из пресета, первый authMode, копия oauth; пикер закрыт, модал открыт"),
    ("select_unknown_type_defaults", '',
     '(() => { m.selectCloudProviderType("weird"); const f = st.ui.topologyCloudForm; return [f.type, f.name, f.authMode, f.baseUrl]; })()',
     '["weird","","apiKey",""]',
     "negative: тип без пресета — apiKey по умолчанию и пустые поля, без исключения"),
    ("open_account_modal_unknown_is_noop", '',
     '(() => { m.openCloudAccountModal("ghost"); return [st.ui.topologyCloudModalOpen, st.ui.topologyCloudForm]; })()',
     '[false,null]', "negative: неизвестный аккаунт модал не открывает"),
    ("open_account_modal_edit", '',
     '(() => { m.openCloudAccountModal("ollama"); const f = st.ui.topologyCloudForm; return [f.isNew, f.accountId, f.type, f.name, f.authMode, f.apiKey]; })()',
     '[false,"ollama","ollama","Ollama cloud","apiKey",""]',
     "редактирование: форма из аккаунта, ключ никогда не подставляется"),
    ("close_provider_modal_resets", '',
     '(() => { m.openCloudAccountModal("ollama"); m.closeCloudProviderModal(); return [st.ui.topologyCloudModalOpen, st.ui.topologyCloudPickerOpen, st.ui.topologyCloudForm, m.topologyCloudBusy]; })()',
     '[false,false,null,false]', "закрытие снимает всё, включая busy"),
    ("is_subscription_by_account_type_or_url", '',
     '(() => { const r = []; m.openCloudAccountModal("openai-subscription"); r.push(m.cloudModalIsSubscription()); m.openCloudAccountModal("ollama"); r.push(m.cloudModalIsSubscription()); m.closeCloudProviderModal(); r.push(m.cloudModalIsSubscription()); return r; })()',
     '[true,false,false]', "подписка узнаётся по accountType/chatgpt.com; без формы — false"),
    # ── block modal ──
    ("open_block_modal_edit_carries_settings", '',
     '(() => { m.openCloudBlockModal("gpt-5-6-terra", null); const f = m.topologyCloudBlockForm; return [f.isNew, f.blockId, f.accountId, f.model, f.origModel, f.modelMode, f.contextLength, f.contextAuto, m.topologyCloudBlockModalOpen]; })()',
     '[false,"gpt-5-6-terra","openai-subscription","gpt-5.6-terra","gpt-5.6-terra","rewrite","158000",false,true]',
     "правка блока: окно контекста — строкой, origModel запоминается для предупреждения о смене модели"),
    ("open_block_modal_new_for_account", '',
     '(() => { m.openCloudBlockModal(null, "ollama"); const f = m.topologyCloudBlockForm; return [f.isNew, f.blockId, f.accountId, f.model, f.contextLength, f.contextAuto]; })()',
     '[true,"","ollama","","",false]', "новый блок: пустая форма с аккаунтом; окно не задано — пустая строка, не 0"),
    ("open_block_modal_fetches_models_by_account_kind", '',
     '(() => { m.openCloudBlockModal(null, "ollama"); m.openCloudBlockModal(null, "openai-subscription"); m.openCloudBlockModal(null, "bare"); return calls().map((c) => c.path); })()',
     '["/api/cloud-accounts/models?id=ollama","/api/cloud-accounts/subscription-models?id=openai-subscription"]',
     "список моделей тянется по виду аккаунта; без учётных данных — не тянется"),
    ("fetch_models_once_then_cached",
     'globalThis.__fetchReply["/api/cloud-accounts/models?id=ollama"] = { ok: true, models: [{ id: "deepseek-v4-flash" }, { id: "qwen3" }] };',
     'await (async () => { await m.fetchCloudAccountModels("ollama"); await m.fetchCloudAccountModels("ollama"); return [calls().length, m.topologyCloudModelCache.get("ollama").map((x) => x.id)]; })()',
     '[1,["deepseek-v4-flash","qwen3"]]', "второй вызов не ходит в сеть — кэш на страницу"),
    ("fetch_models_failure_forgets_marker_and_pauses",
     'globalThis.__fetchReply["/api/cloud-accounts/models?id=ollama"] = { __status: 500, error: "boom" };',
     'await (async () => { await m.fetchCloudAccountModels("ollama"); await m.fetchCloudAccountModels("ollama"); const soon = calls().length;'
     ' globalThis.__clock += 59999; await m.fetchCloudAccountModels("ollama"); const almost = calls().length;'
     ' globalThis.__clock += 1; await m.fetchCloudAccountModels("ollama"); return [soon, almost, calls().length, m.topologyCloudModelCache.get("ollama") ?? null]; })()',
     '[1,1,2,null]', "defect-history: отказ не запоминается как ответ (маркер снят), но и не повторяется сразу — пауза 60 с; "
     "страница спрашивает на каждом опросе, и отказывающий аккаунт спрашивали каждые 1.5 с (граница: 59.999 с — ещё нет, 60 с — да)"),
    ("fetch_models_retry_after_failure_succeeds",
     '',
     'await (async () => { const k = "/api/cloud-accounts/models?id=ollama";'
     ' globalThis.__fetchReply[k] = { __status: 500, error: "boom" }; await m.fetchCloudAccountModels("ollama");'
     ' globalThis.__clock += 60000; globalThis.__fetchReply[k] = { ok: true, models: [{ id: "qwen3" }] }; await m.fetchCloudAccountModels("ollama");'
     ' return [calls().length, (m.topologyCloudModelCache.get("ollama") || []).map((x) => x.id)]; })()',
     '[2,["qwen3"]]', "positive: попытка после паузы приносит список — пустая выдача не осталась на его месте"),
    ("open_block_modal_asks_inside_a_pause",
     'globalThis.__fetchReply["/api/cloud-accounts/models?id=ollama"] = { __status: 500, error: "boom" };',
     'await (async () => { await m.fetchCloudAccountModels("ollama"); m.openCloudBlockModal(null, "ollama"); await Promise.resolve(); return calls().map((c) => c.path); })()',
     '["/api/cloud-accounts/models?id=ollama","/api/cloud-accounts/models?id=ollama"]',
     "оператор открыл редактор модели — список спрашивается сразу, пауза не мешает"),
    ("fetch_subscription_failure_forgets_marker",
     'globalThis.__fetchReply["/api/cloud-accounts/subscription-models?id=openai-subscription"] = { __status: 500, error: "boom" };',
     'await (async () => { await m.fetchCloudSubscriptionModels("openai-subscription"); await m.fetchCloudSubscriptionModels("openai-subscription"); return [calls().length, m.topologyCloudModelCache.get("openai-subscription") ?? null]; })()',
     '[1,null]', "подписочный список — тот же ответ на отказ и та же пауза: у обоих одно тело, разъехаться нечему"),
    ("prefetch_all_by_kind", '',
     'await (async () => { m.prefetchAllSubscriptionModels(); await Promise.resolve(); return calls().map((c) => c.path).sort(); })()',
     '["/api/cloud-accounts/models?id=ollama","/api/cloud-accounts/subscription-models?id=openai-subscription"]',
     "префетч: подписка и API-аккаунт — с учётными данными, bare без них — нет"),
    ("prefetch_skips_a_subscription_nobody_signed_into",
     'st.setTopology(TOPO({ cloudAccounts: ACCOUNTS().map((a) => ({ ...a, hasCredential: false })) }));',
     'await (async () => { m.prefetchAllSubscriptionModels(); await Promise.resolve(); return calls().length; })()',
     '0', "defect-history: в подписку никто не вошёл — список не спрашивается (раньше спрашивался на каждом опросе и получал отказ)"),
    # ── picker and modals: HTML ──
    ("picker_closed_is_empty", '', 'm.renderTopologyCloudPicker()', '""', "negative: закрытый пикер — пустая строка"),
    ("picker_tiles_per_preset",
     'st.ui.topologyCloudPickerOpen = true;',
     '(h => [(h.match(/data-pick-type="/g) || []).length, h.includes(\'data-pick-type="openai-subscription"\'), h.includes("ChatGPT Plus · OAuth")])(m.renderTopologyCloudPicker())',
     '[3,true,true]', "плитка на пресет с подписью из CLOUD_PICKER_META"),
    ("account_modal_new_openai_has_key_no_delete",
     'm.selectCloudProviderType("openai");',
     '(h => [h.includes("Add cloud account"), h.includes(\'data-cloud-field="apiKey"\'), h.includes("data-cloud-delete-account"), h.includes(\'data-cloud-field="baseUrl"\')])(m.renderTopologyCloudAccountModal())',
     '[true,true,false,true]', "новый API-аккаунт: поле ключа есть, кнопки удаления нет, baseUrl виден"),
    ("account_modal_subscription_hides_base_url",
     'm.selectCloudProviderType("openai-subscription");',
     '(h => [h.includes(\'data-cloud-field="baseUrl"\'), h.includes("data-cloud-oauth-login"), h.includes(\'data-cloud-field="apiKey"\')])(m.renderTopologyCloudAccountModal())',
     '[false,true,false]', "подписка: baseUrl скрыт, вход по OAuth, ключа нет"),
    ("account_modal_edit_shows_delete_and_credential",
     'm.openCloudAccountModal("ollama");',
     '(h => [h.includes("Edit cloud account"), h.includes("data-cloud-delete-account"), h.includes("key set ••••ab12"), h.includes("data-cloud-picker-change")])(m.renderTopologyCloudAccountModal())',
     '[true,true,true,false]', "правка: кнопка удаления, статус ключа по last4, смены типа нет"),
    ("account_modal_closed_is_empty", '', 'm.renderTopologyCloudAccountModal()', '""', "negative: закрытый модал аккаунта — пустая строка"),
    ("block_modal_closed_is_empty", '', 'm.renderTopologyCloudBlockModal()', '""', "negative: закрытый модал блока — пустая строка"),
    ("block_modal_models_from_cache_marks_unlisted",
     'm.topologyCloudModelCache.set("openai-subscription", [{ id: "gpt-5.6-terra", contextLength: 400000 }]); m.openCloudBlockModal("gpt-5-6-luna", null);',
     '(h => [h.includes(\'<option value="gpt-5.6-luna" selected>gpt-5.6-luna ⚠</option>\'), h.includes(\'<option value="gpt-5.6-terra">gpt-5.6-terra</option>\'), h.includes("data-block-field-custom"), h.includes("data-cloud-delete-block"), h.includes("data-block-field-expose")])(m.renderTopologyCloudBlockModal())',
     '[true,true,true,true,false]',
     "список = кэш ∪ модели блоков; не в списке провайдера — ⚠; правка: удаление есть, галки expose нет"),
    ("block_modal_reported_window",
     'm.topologyCloudModelCache.set("openai-subscription", [{ id: "gpt-5.6-terra", contextLength: 400000 }]);',
     '(() => { m.openCloudBlockModal("gpt-5-6-terra", null); const a = m.renderTopologyCloudBlockModal().includes("<b>400000</b>"); m.openCloudBlockModal("gpt-5-6-luna", null); const b = m.renderTopologyCloudBlockModal().includes("<b>provider reports none</b>"); return [a, b]; })()',
     '[true,true]', "что провайдер сообщил об окне — числом; не сообщил — так и написано, не 0"),
    ("block_modal_new_without_models_is_text_input",
     'm.openCloudBlockModal(null, "bare");',
     '(h => [h.includes("Add model block"), h.includes(\'<input type="text" data-block-field="model"\'), h.includes("data-block-field-expose"), h.includes("data-cloud-delete-block")])(m.renderTopologyCloudBlockModal())',
     '[true,true,true,false]', "новый блок без списка моделей: текстовое поле, галка expose, удаления нет"),
    # ── providers lane ──
    # 2026-09-28: while the reserve slider on a limit bar is being dragged, the
    # lane is not rebuilt under the pointer — the redraw waits for the release.
    ("lane_waits_for_reserve_drag",
     'st.setTopology(TOPO({ cloudAccounts: [], cloudProviders: [] })); globalThis.__fields.topologyCloudProviders.innerHTML = "BEFORE"; st.ui._lastCloudProvidersKey = ""; us.reserveDrag.active = true; us.reserveDrag.deferred = false;',
     '(() => { m.renderTopologyCloudProviders(); const held = [lane(), us.reserveDrag.deferred]; us.reserveDrag.active = false; us.reserveDrag.deferred = false; m.renderTopologyCloudProviders(); return [...held, lane() === "BEFORE"]; })()',
     '["BEFORE",true,false]', "ползунок запаса тянут — полосу не перерисовывают, перерисовка отложена; отпустили — рисуется"),
    # 2026-10-04: a pool's rung is dragged by its grip (HTML5 drag, which cancels pointer events),
    # so the reserve-slider guard cannot hold the lane for it; the pool card says when a rung is in the air.
    ("lane_waits_for_pool_rung_in_flight", '',
     'await (async () => { const lane = { innerHTML: "", dataset: {}, handlers: {}, addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }, querySelector: () => null }; globalThis.__fields.topologyCloudProviders = lane; st.setTopology(TOPO({ cloudAccounts: [], cloudProviders: [] })); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); lane.innerHTML = "BEFORE"; st.ui._lastCloudProvidersKey = ""; const rung = { dataset: { poolMember: "a" }, classList: { add() {}, remove() {} } }, section = { dataset: { poolId: "p" }, querySelectorAll: () => ({ forEach() {} }) }; const grip = { closest: (sel) => (sel === "[data-pool-grip]" ? grip : sel === "[data-pool-member]" ? rung : sel === "[data-pool-id]" ? section : null) }; lane.handlers.dragstart[0]({ type: "dragstart", target: grip, dataTransfer: { setData() {}, setDragImage() {} } }); globalThis.__q[".pool-step.dragging"] = {}; m.renderTopologyCloudProviders(); const held = lane.innerHTML; delete globalThis.__q[".pool-step.dragging"]; m.renderTopologyCloudProviders(); return [held, lane.innerHTML === "BEFORE", ["dragstart", "dragover", "drop", "dragend"].every((type) => lane.handlers[type]?.length === 1)]; })()',
     '["BEFORE",false,true]', "ступень пула в воздухе — полосу не перерисовывают; ступени нет (перерисовали поверх, dragend не пришёл) — рисуется, флаг не держит полосу вечно; четыре жеста перетаскивания привязаны по разу"),
    ("lane_pool_rung_reads_usage_resets_and_spend", '',
     'await (async () => { const lane = laneEl(); globalThis.__fields.topologyCloudProviders = lane; us.subscriptionUsageCache.set("m1", { data: { ok: true, limits: [{ label: "5H LIMIT", remainingPct: 80, windowSeconds: 18000 }] }, fetchedAt: Date.now(), loading: false }); globalThis.__fetchReply["/api/cloud-accounts/proxy-spend"] = { spend: { m1: { total: 809, requests: 8200, promptTokens: 6, completionTokens: 1, windowDays: 30 }, "m1-test": { total: 120, requests: 90, promptTokens: 2, completionTokens: 1, windowDays: 30 } } }; globalThis.__fetchReply["/api/cloud-accounts/subscription-resets?id=m1"] = { availableCount: 3, credits: [], pending: [] }; st.setTopology(TOPO({ cloudAccounts: [{ id: "pool", name: "Work pool", type: "openai", isPool: true, hasCredential: true, pool: { id: "pool", name: "Work pool", mode: "auto", members: [{ accountId: "m1", enabled: true, automatic: true }, { accountId: "m1-test", enabled: true, automatic: true }] } }, { id: "m1", name: "Plus", type: "openai", accountType: "openai-subscription", hasCredential: true, credentialKind: "oauth", oauthEmail: "m1@example.test", baseUrl: "https://chatgpt.com/backend-api" }, { id: "m1-test", name: "Plus test", type: "openai", accountType: "openai-subscription", testAliasOf: "m1", hasCredential: true, credentialKind: "oauth", oauthEmail: "m1@example.test", baseUrl: "https://chatgpt.com/backend-api" }], cloudProviders: [] })); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r)); const h = lane.innerHTML; const rungs = h.split("</li>").filter((x) => x.includes(`class="pool-step`)); const rung = rungs[0], alias = rungs[1]; const fold = rung.indexOf(`class="pool-step-more"`); const head = (r) => r.slice(0, r.indexOf(`class="pool-step-more"`)); return [rung.includes("↺ 3"), rung.includes("≈ $809"), rung.indexOf("sub-usage-panel") > -1 && rung.indexOf("sub-usage-panel") < fold, rung.indexOf("subscription-resets") > fold, rung.indexOf("spend-line") > fold, rung.includes("m1@example.test"), head(alias).includes("↺ 3") && head(alias).includes("≈ $120") && !head(alias).includes("$809")]; })()',
     '[true,true,true,true,true,true,true]', "ступень пула в полосе читает три источника: полосы лимитов — над сгибом, сохранённые сбросы и расход — под ним, а в голове только числа (↺ 3, ≈ $809), которые появляются, когда чтение пришло; тестовый участник берёт сбросы у исходной подписки, а расход — свой"),
    # 2026-10-04: a reset whose outcome is uncertain waits for a retry and nothing may hide it — the pool card
    # opens the rung and flags the head, for the account itself and for a TEST member of the same credential.
    ("lane_pool_rung_flags_uncertain_reset", '',
     'await (async () => { const lane = laneEl(); globalThis.__fields.topologyCloudProviders = lane; globalThis.__fetchReply["/api/cloud-accounts/subscription-resets?id=q1"] = { availableCount: 2, credits: [], pending: [{ creditId: "c1", idempotencyKey: "k1" }] }; globalThis.__fetchReply["/api/cloud-accounts/subscription-resets?id=q2"] = { availableCount: 1, credits: [], pending: [] }; st.setTopology(TOPO({ cloudAccounts: [{ id: "pool", name: "Work pool", type: "openai", isPool: true, hasCredential: true, pool: { id: "pool", name: "Work pool", mode: "auto", members: [{ accountId: "q1", enabled: true, automatic: true }, { accountId: "q1-test", enabled: true, automatic: true }, { accountId: "q2", enabled: true, automatic: true }] } }, { id: "q1", name: "Plus", type: "openai", accountType: "openai-subscription", hasCredential: true, credentialKind: "oauth", oauthEmail: "q1@example.test", baseUrl: "https://chatgpt.com/backend-api" }, { id: "q1-test", name: "Plus test", type: "openai", accountType: "openai-subscription", testAliasOf: "q1", hasCredential: true, credentialKind: "oauth", oauthEmail: "q1@example.test", baseUrl: "https://chatgpt.com/backend-api" }, { id: "q2", name: "Pro", type: "openai", accountType: "openai-subscription", hasCredential: true, credentialKind: "oauth", oauthEmail: "q2@example.test", baseUrl: "https://chatgpt.com/backend-api" }], cloudProviders: [] })); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r)); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); const rungs = lane.innerHTML.split("</li>").filter((x) => x.includes(`class="pool-step`)); const head = (r) => r.slice(0, r.indexOf(`class="pool-step-more"`)); return [rungs.length, rungs.map((r) => head(r).includes("pool-warn")), rungs.map((r) => /class="pool-step( serving)? open"/.test(r))]; })()',
     '[3,[true,true,false],[true,true,false]]', "незавершённый сброс: голова ступени владельца и его TEST-участника предупреждает и раскрыта, у другой подписки — нет (свои id: кэш сбросов и попытки переживают пин)"),
    # 2026-10-04: a pool draws its own top (the icon, the name as the title, the mode) — the generic head with its
    # "configured" pill and its gear belongs to the other accounts, and they keep it.
    # 2026-10-04: the cloud lane is drawn anew on its own; its cards' ↑ ↓ learn again which card stands
    # first or last in the whole list (machines and cloud) — a fresh ↑ is never left enabled on the first card.
    ("lane_drawn_alone_marks_the_ends_of_the_list", '',
     'await (async () => { const lane = laneEl(); globalThis.__fields.topologyCloudProviders = lane;'
     ' const btn = () => ({ disabled: false }); const card = (key) => { const c = { dataset: { serverCard: key }, style: { order: "" }, up: btn(), down: btn() };'
     ' c.querySelector = (sel) => (sel === \'[data-server-step="up"]\' ? c.up : sel === \'[data-server-step="down"]\' ? c.down : null); return c; };'
     ' const cards = [card("node:a"), card("cloud:s")]; const keep = document.querySelectorAll;'
     ' document.querySelectorAll = (sel) => (sel === "[data-server-card]" ? cards : []);'
     ' try { st.setTopology(TOPO({ cloudAccounts: [{ id: "s", name: "Solo", type: "openai", hasCredential: true, credentialKind: "apiKey", keyLast4: "1234" }], cloudProviders: [] }));'
     ' st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders();'
     ' return cards.map((c) => `${c.dataset.serverCard}:${c.up.disabled ? "-" : "↑"}${c.down.disabled ? "-" : "↓"}`); }'
     ' finally { document.querySelectorAll = keep; } })()',
     '["node:a:-↓","cloud:s:↑-"]',
     "облачная полоса, перерисованная сама по себе, заново отмечает концы всего списка: у первой карточки (машины) нет ↑, "
     "у последней (облачной) нет ↓"),
    ("lane_pool_card_draws_its_own_top", '',
     'await (async () => { const lane = laneEl(); globalThis.__fields.topologyCloudProviders = lane; st.setTopology(TOPO({ cloudAccounts: [{ id: "tp", name: "Top pool", type: "openai", isPool: true, hasCredential: true, pool: { id: "tp", name: "Top pool", mode: "auto", members: [{ accountId: "t1", enabled: true, automatic: true }] } }, { id: "t1", name: "Plus", type: "openai", accountType: "openai-subscription", hasCredential: true, credentialKind: "oauth", oauthEmail: "t1@example.test", baseUrl: "https://chatgpt.com/backend-api" }, { id: "t2", name: "Solo", type: "openai", accountType: "openai-subscription", hasCredential: true, credentialKind: "oauth", oauthEmail: "t2@example.test", baseUrl: "https://chatgpt.com/backend-api" }], cloudProviders: [] })); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); const cards = lane.innerHTML.split("</article>").filter((x) => x.includes("cloud-account-card")); const [pool, solo] = cards; return [cards.length, pool.includes("cloud-account-head"), /<header class="pool-top">\\s*<span class="server-order"><button type="button" class="server-step" data-server-step="up" data-t="server-step-up" data-t-id="cloud:tp"[^\\n]*?data-server-step="down"[^\\n]*?<\\/button><\\/span><span class="cloud-account-icon"/.test(pool), pool.includes(`data-pool-field="name" value="Top pool"`), pool.includes("poolTitle") || pool.includes("OpenAI pool"), solo.includes(`<div class="cloud-account-head">`), solo.includes(`data-cloud-edit-account="t2"`), solo.includes(`<span class="pill good">ChatGPT</span>`), /<div class="cloud-account-head">\\s*<span class="server-order"><button type="button" class="server-step" data-server-step="up" data-t="server-step-up" data-t-id="cloud:t2"[^\\n]*?data-server-step="down"[^\\n]*?<\\/button><\\/span><span class="cloud-account-icon"/.test(solo), solo.includes("pool-top"), [pool, solo].map((c) => (c.match(/data-server-card="[^"]*" style="order:\\d+"/) || [""])[0]), (lane.innerHTML.match(/data-server-step="up"/g) || []).length]; })()',
     '[2,false,true,true,false,true,true,true,true,false,["data-server-card=\\"cloud:tp\\" style=\\"order:0\\"","data-server-card=\\"cloud:t2\\" style=\\"order:0\\""],2]', "карточка пула рисует свою шапку: кнопки ↑ ↓ списка, значок, имя-заголовок, режим; общая шапка с плашкой и шестерёнкой — у остальных подписок, и они её сохранили; каждая карточка — одна в списке Model servers: ключ и место (ничего не сохранено — место одно на всех, порядок полос), ручка одна на карточку — у участника пула её нет"),
    # 2026-10-04: the pool rung's refresh button is in its head; the bars carry none. Another subscription's panel keeps its own.
    ("lane_pool_rung_refresh_sits_in_head", '',
     'await (async () => { const lane = laneEl(); globalThis.__fields.topologyCloudProviders = lane; for (const id of ["u1", "u2"]) us.subscriptionUsageCache.set(id, { data: { ok: true, limits: [{ label: "5H LIMIT", remainingPct: 80, windowSeconds: 18000 }] }, fetchedAt: Date.now(), loading: false }); st.setTopology(TOPO({ cloudAccounts: [{ id: "up", name: "Top pool", type: "openai", isPool: true, hasCredential: true, pool: { id: "up", name: "Top pool", mode: "auto", members: [{ accountId: "u1", enabled: true, automatic: true }] } }, { id: "u1", name: "Plus", type: "openai", accountType: "openai-subscription", hasCredential: true, credentialKind: "oauth", oauthEmail: "u1@example.test", baseUrl: "https://chatgpt.com/backend-api" }, { id: "u2", name: "Solo", type: "openai", accountType: "openai-subscription", hasCredential: true, credentialKind: "oauth", oauthEmail: "u2@example.test", baseUrl: "https://chatgpt.com/backend-api" }], cloudProviders: [] })); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); const cards = lane.innerHTML.split("</article>").filter((x) => x.includes("cloud-account-card")); const [pool, solo] = cards; const rung = pool.split("</li>")[0]; const fold = rung.indexOf(`class="pool-step-more"`); const head = rung.slice(0, fold); const at = head.indexOf(`data-usage-refresh="u1"`); const panel = head.slice(head.indexOf(`class="sub-usage-panel"`)); return [(pool.match(/data-usage-refresh="u1"/g) || []).length, at > head.indexOf(`class="pool-step-tools"`) && at < head.indexOf("data-pool-fold"), panel.includes("data-usage-refresh"), panel.includes("sub-usage-head"), solo.includes(`class="sub-usage-head"`) && solo.includes(`data-usage-refresh="u2"`)]; })()',
     '[1,true,false,false,true]', "кнопка ↻ ступени пула — в её голове между числами и свёрткой; в полосах её нет; панель подписки вне пула держит свою кнопку"),
    # 2026-10-04: the number of saved resets in a rung's head opens the window that asks which one to spend. The
    # lane wires it to the credential's owner (a TEST member opens its original's), and opening it sends nothing.
    ("lane_pool_counter_opens_window_of_choice", '',
     'await (async () => { const lane = { innerHTML: "", dataset: {}, handlers: {}, addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }, querySelector: () => null }; globalThis.__fields.topologyCloudProviders = lane; const soon = new Date(Date.now() + 5 * 86400e3).toISOString(), late = new Date(Date.now() + 40 * 86400e3).toISOString(); globalThis.__fetchReply["/api/cloud-accounts/subscription-resets?id=k1"] = { availableCount: 4, credits: [{ id: "late", resetType: "codex_rate_limits", usable: true, expiresAt: late }, { id: "soon", resetType: "codex_rate_limits", usable: true, expiresAt: soon }, { id: "spent", resetType: "codex_rate_limits", usable: false, expiresAt: soon }], pending: [] }; st.setTopology(TOPO({ cloudAccounts: [{ id: "kp", name: "Window pool", type: "openai", isPool: true, hasCredential: true, pool: { id: "kp", name: "Window pool", mode: "auto", members: [{ accountId: "k1", enabled: true, automatic: true }, { accountId: "k1-test", enabled: true, automatic: true }] } }, { id: "k1", name: "Plus", type: "openai", accountType: "openai-subscription", hasCredential: true, credentialKind: "oauth", oauthEmail: "k1@example.test", baseUrl: "https://chatgpt.com/backend-api" }, { id: "k1-test", name: "Plus test", type: "openai", accountType: "openai-subscription", testAliasOf: "k1", hasCredential: true, credentialKind: "oauth", oauthEmail: "k1@example.test", baseUrl: "https://chatgpt.com/backend-api" }], cloudProviders: [] })); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r)); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); const chips = [...lane.innerHTML.matchAll(/data-pool-resets="([^"]*)"/g)].map((x) => x[1]); let asked = null; globalThis.__stubReturns["dialogs.appConfirmChoice"] = async (message, opts) => { asked = [message, opts]; return null; }; const chip = { dataset: { poolResets: "k1" }, disabled: false, matches: () => false, hasAttribute: (a) => a === "data-pool-resets", closest: (sel) => (sel.includes("data-pool-resets") ? chip : null) }; await lane.handlers.click[0]({ type: "click", target: chip, stopPropagation() {} }); const posts = calls().filter((c) => c.method === "POST" && c.path.includes("subscription-reset")); return [chips, asked && asked[1].choices.map((c) => c.value), asked && asked[1].detail, !!asked && asked[0].includes("Plus"), posts.length]; })()',
     '[["k1","k1"],["soon","late"],"k1@example.test",true,0]', "счётчик сбросов в голове ступени открывает окно выбора для владельца учётных данных (у TEST-участника — для оригинала): предлагает только то, что можно потратить, ближайший срок первым, и ничего не отправляет"),
    ("lane_without_accounts",
     'st.setTopology(TOPO({ cloudAccounts: [], cloudProviders: [] }));',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [h.includes("no cloud providers — click + to add one"), h.includes("data-topo-add-cloud"), (h.match(/cloud-account-card/g) || []).length]; })()',
     '[true,false,0]', "без аккаунтов — подсказка; кнопки добавления в полосе нет — она в шапке Model servers, главное действие полосы (2026-10-04)"),
    ("lane_cards_and_price_order", '',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [(h.match(/cloud-account-card/g) || []).length, h.indexOf("gpt-5.6-terra") < h.indexOf("gpt-5.6-luna"), h.includes("$10.00 / $30.00 /1M") || h.includes("/1M"), h.includes("needs-key"), h.includes("key set ••••ab12"), h.includes(\'<span class="cloud-models-n">2</span>\')]; })()',
     '[3,true,true,true,true,true]',
     "карточка на аккаунт; блоки от дорогих к дешёвым; без ключа — needs-key; счётчик моделей"),
    ("lane_marks_model_missing_from_provider_list",
     'st.setTopology(TOPO({ cloudProviders: BLOCKS().map((b) => (b.id === "gpt-5-6-luna" ? { ...b, unlisted: true } : b)) }));',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [(h.match(/cloud-block-row stale/g) || []).length, (h.match(/class="cloud-chip gone"/g) || []).length, h.includes("cloud-models-gone")]; })()',
     '[1,1,true]', "модель, которой провайдер больше не отдаёт, помечена «gone» — ровно одна, и счёт в шапке списка"),
    ("lane_page_cache_alone_marks_nothing",
     'm.topologyCloudModelCache.set("openai-subscription", [{ id: "gpt-5.6-terra" }]);',
     '(() => { m.renderTopologyCloudProviders(); return (lane().match(/cloud-block-row stale/g) || []).length; })()',
     '0', "negative: список страницы сам не метит — «ушла» говорит сервер, который сверяет списки каждые 10 минут"),
    ("lane_bridges_on_their_block_orphans_in_strip",
     'st.setTopology(TOPO({ proxies: BRIDGES() }));',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [h.includes(":8083"), h.includes("http://ctl:8083"), h.includes("cloud-orphan-bridges"), h.includes(":8084"), h.includes(":23001"), h.includes(\'data-bridge-mint="gpt-5-6-luna"\'), h.includes(\'data-bridge-mint="gpt-5-6-terra"\')]; })()',
     '[true,true,true,true,false,true,false]',
     "решение оператора (2026-09-27): порт модели — на её строке: у terra свой :8083 с адресом хоста, у luna — «＋ port»; "
     "мост без модели — в полосе сирот; прокси агента (не service) в лейне нет"),
    ("lane_bridge_button_promises_the_servers_port",
     'st.setTopology(TOPO({ nextAppPort: 23004 }));',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [h.includes("(:23004)"), h.includes(":22")]; })()',
     '[true,false]', "defect-history: «＋ port» обещает порт, который выдаст сервер (topology.nextAppPort) — раньше номер следующей ЯЧЕЙКИ"),
    ("lane_bridge_button_without_a_known_port",
     '',
     '(() => { m.renderTopologyCloudProviders(); return lane().includes("(:…)"); })()',
     'true', "negative: порт неизвестен — кнопка без номера, а не с чужим"),
    ("lane_removed_models_with_undo",
     'st.setTopology(TOPO({ cloudRemoved: [{ accountId: "ollama", id: "old-7b", model: "old-7b", at: 1 }] }));',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [(h.match(/data-cloud-restore="ollama\\|old-7b"/g) || []).length, (h.match(/class="cloud-removed"/g) || []).length]; })()',
     '[1,1]', "убранные сами — одной строкой на карточке своего аккаунта, у каждой ↶; на других карточках строки нет"),
    ("restore_brings_it_back",
     'globalThis.__fetchReply["/api/cloud-blocks/restore"] = { ok: true, block: { id: "old-7b", model: "old-7b" } };',
     'await (async () => { const lane = { innerHTML: "", dataset: {}, handlers: [], addEventListener(type, fn) { if (type === "click") this.handlers.push(fn); }, querySelector: () => null };'
     ' globalThis.__fields.topologyCloudProviders = lane; st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders();'
     ' const btn = { dataset: { cloudRestore: "ollama|old-7b" }, disabled: false };'
     ' for (const h of lane.handlers) await h({ stopPropagation() {}, target: { closest: (s) => (s === "[data-cloud-restore]" ? btn : null) } });'
     ' await settle(); return [calls().map((c) => [c.path, c.body]), toastText()]; })()',
     '[[["/api/cloud-blocks/restore",{"accountId":"ollama","id":"old-7b"}]],"old-7b is back"]',
     "↶ шлёт машину и id убранной модели и говорит, что она вернулась"),
    ("provider_models_groups_and_marks",
     '',
     '(() => { const blocks = [{ id: "h", accountId: "a", model: "h" }, { id: "k", accountId: "a", model: "k", exposed: true },'
     ' { id: "n", accountId: "a", model: "n", newSince: 1000 }, { id: "g", accountId: "a", model: "g", unlisted: true, newSince: 1000 },'
     ' { id: "o", accountId: "a", model: "o", newSince: 1 }, { id: "x", accountId: "b", model: "x" }];'
     ' const routers = [{ rules: { default: "cb:k" }, graph: { edges: [{ to: "out:cb:g" }, { to: "out:cb:g" }, { to: "out:cb:k" }, { to: "srv:1" }] } }];'
     ' const pm = new cm.ProviderModels({ account: { id: "a" }, blocks, routers, now: (1000 + 7 * 24 * 3600) * 1000 - 1 });'
     ' const rows = pm.rows().map((r) => [r.block.id, r.gone, r.fresh, r.shown, r.cables, r.isDefault]);'
     ' const edge = new cm.ProviderModels({ account: { id: "a" }, blocks, routers, now: (1000 + 7 * 24 * 3600) * 1000 }).summary().fresh;'
     ' return [rows, pm.summary(), edge]; })()',
     json.dumps([[["g", True, False, False, 2, False], ["n", False, True, False, 0, False], ["k", False, False, True, 1, True],
                  ["h", False, False, False, 0, False], ["o", False, False, False, 0, False]],
                 {"total": 5, "shown": 1, "fresh": 1, "gone": 1}, 0]),
     "строки по вниманию: ушедшая (два каната в неё), новая, на канбане (и «по умолчанию»), скрытые; ушедшая не «новая»; "
     "модели чужого аккаунта не в списке; boundary: «новая» ровно 7 суток — на миллисекунду раньше ещё да, ровно в 7 суток уже нет"),
    ("new_model_words_and_likeness",
     '',
     '[cm.ModelNames.words("openai/gpt-6.1-sol"), cm.ModelNames.words("qwen3-coder:480b-cloud"), cm.ModelNames.words(""),'
     ' cm.ModelNames.words("gpt-gpt-4o"), cm.ModelNames.likeness("gpt-6.1-sol", "gpt-6-sol"),'
     ' cm.ModelNames.likeness("gpt-6.1-sol", "claude-sonnet-5"), cm.ModelNames.likeness("openai/gpt-6", "anthropic/gpt-6")]',
     '[["gpt","sol"],["qwen3","coder","cloud"],[],["gpt"],2,0,1]',
     "слова имени модели — без поставщика и версий, без повторов; похожесть — сколько слов общих; negative: чужое семейство — 0"),
    ("new_model_pending_closest_first",
     '',
     '(() => { const [a] = NMA(); const p = a.pending(NM_TOP()); mm.modelPricing["zeta-9"] = { inputPer1M: 50, outputPer1M: 100 };'
     ' const q = a.pending(NM_TOP()); const busy = NM_TOP(); busy.routers[0].graph.edges.push(...[1, 2, 3].map(() => ({ to: "out:cb:mini" })));'
     ' return [p.account.id, p.block.id, p.sources.map((s) => s.block.id), p.batch, q.block.id, q.batch,'
     ' a.pending(busy).sources.map((s) => [s.block.id, s.cables])]; })()',
     '["a","sol61",["sol","mini"],["sol61","zeta"],"sol61",["zeta","sol61"],[["sol",2],["mini",3]]]',
     "окно спрашивает о новой модели, ближайшей по имени к модели в деле, и первой предлагает ближайшую по имени "
     "(даже если к другой идёт больше канатов); "
     "партия — новые без ответа (отвеченная gpt-6.2-sol не в ней); boundary: карточка ставит дорогую чужую первой — окно всё равно о ближайшей"),
    ("new_model_pending_nothing_to_ask",
     '',
     '(() => { const [a] = NMA(); const b = NM_TOP().cloudProviders;'
     ' const allAnswered = a.pending(NM_TOP(b.map((x) => ({ ...x, announced: true }))));'
     ' const unused = a.pending({ ...NM_TOP(), routers: [] });'
     ' const old = a.pending(NM_TOP(b.map((x) => (x.newSince ? { ...x, newSince: NM_T - 8 * 24 * 3600 } : x))));'
     ' a.failed.add("sol61"); const next = a.pending(NM_TOP()).block.id; a.failed.add("zeta");'
     ' return [allAnswered, unused, old, next, a.pending(NM_TOP()), a.pending(null)]; })()',
     '[null,null,null,"zeta",null,null]',
     "negative: всё отвечено, ни одна модель провайдера не в деле, новые старше недели, нет топологии — не спрашивать; "
     "модель, ответ о которой не дошёл, пропускается до перезагрузки страницы"),
    ("new_model_move_asks_and_moves",
     '',
     'await (async () => { const [a, log] = NMA({ answer: "sol" }); const r = await a.maybeAsk(NM_TOP()); const { msg, opts } = log.asks[0];'
     ' return [r, msg === fill(en.newModelText, { model: "gpt-6.1-sol" }) + " " + fill(en.newModelMore, { n: "1" }),'
     ' opts.title === fill(en.newModelTitle, { provider: "OpenAI" }), opts.cancelLabel === en.newModelNotNow,'
     ' opts.confirmLabel === en.newModelApply, opts.choiceLabel === en.newModelChoiceLabel, opts.danger,'
     ' opts.choices.map((c) => c.value), opts.choices[0].label === "gpt-6-sol · " + fill(en.cloudModelCables, { n: "2" }),'
     ' opts.choices[1].label === "gpt-5-mini · " + en.cloudChipDefault, opts.choices[2].label === en.newModelJustAdd,'
     ' log.calls, log.notes[0] === fill(en.newModelMoved, { model: "gpt-6.1-sol", n: "3" }), log.applied, a.asking]; })()',
     '["sol",true,true,true,true,true,false,["sol","mini","__add__"],true,true,true,'
     '[["/api/cloud-blocks/move-cables",{"from":"sol","to":"sol61"}]],true,[{"t":1}],false]',
     "окно: заголовок с провайдером, текст с моделью и «пришло ещё», «Не сейчас» вместо «Отмена», тон вопроса; "
     "варианты — модели в деле с канатами и «по умолчанию», последним «просто добавить»; ответ — перенос, тост с числом, доска из ответа"),
    ("new_model_not_now_answers_the_batch",
     '',
     'await (async () => { const [a, log] = NMA({ answer: null }); const r = await a.maybeAsk(NM_TOP()); return [r, log.calls, log.notes, log.applied]; })()',
     '[null,[["/api/cloud-blocks/announced",{"ids":["sol61","zeta"]}]],[],[{"t":1}]]',
     "«Не сейчас» — ответ за всю партию провайдера (OpenRouter принёс 184 модели разом: окно на каждую — 184 окна); без тоста"),
    ("new_model_just_add_answers_one",
     '',
     'await (async () => { const [a, log] = NMA({ answer: "__add__" }); const r = await a.maybeAsk(NM_TOP()); return [r, log.calls, log.notes]; })()',
     '["__add__",[["/api/cloud-blocks/announced",{"ids":["sol61"],"expose":true}]],[]]',
     "«просто добавить» — только эта модель, на канбан; следующая из партии спросит потом"),
    ("new_model_does_not_ask_over_something",
     '',
     'await (async () => { const [a, l1] = NMA({ quiet: false }); const r1 = await a.maybeAsk(NM_TOP());'
     ' const [b, l2] = NMA(); b.asking = true; const r2 = await b.maybeAsk(NM_TOP());'
     ' const [c, l3] = NMA(); const r3 = await c.maybeAsk(NM_TOP([]));'
     ' return [r1 === undefined, r2 === undefined, r3 === undefined, l1.asks.length + l2.asks.length + l3.asks.length,'
     ' l1.calls.length + l2.calls.length + l3.calls.length]; })()',
     '[true,true,true,0,0]',
     "negative: открыто другое окно, окно уже спрашивает, спрашивать не о чем — не спрашивает и ничего не шлёт"),
    ("new_model_failed_answer_is_not_asked_again",
     '',
     'await (async () => { const [a, log] = NMA({ answer: "sol", fail: true }); const r = await a.maybeAsk(NM_TOP());'
     ' return [r === undefined, log.notes, [...a.failed], a.asking, a.pending(NM_TOP()).block.id, log.applied.length]; })()',
     '[true,["controller is down"],["sol61"],false,"zeta",0]',
     "отказ контроллера: тост с причиной, окно свободно, о той же модели не спрашивает (иначе окно открывалось бы каждый опрос)"),
    ("new_model_absent_count_is_not_zero",
     '',
     'await (async () => { const [a, log] = NMA({ answer: "sol", res: { topology: { t: 2 } } }); await a.maybeAsk(NM_TOP());'
     ' const [b, l2] = NMA({ answer: null, res: {} }); await b.maybeAsk(NM_TOP()); return [log.notes, log.applied, l2.applied]; })()',
     '[[],[{"t":2}],[]]',
     "negative: ответ без числа перенесённого — тоста «перенесено: 0» нет; ответ без доски — доска не трогается"),
    ("new_model_window_is_one_and_draws_its_answer",
     '',
     '(() => { const one = m.NEW_MODELS instanceof cm.NewModelAnnouncer; m.NEW_MODELS.apply({ ...TOPO(), marker: 7 }); return [one, st.topology.marker]; })()',
     '[true,7]',
     "окно одно на доску; его ответ приходит с доской, и она ставится сразу"),
    ("gone_cables_targets_closest_then_shown",
     '',
     '(() => { const [g] = GMC(); const p = g.targets("old", GM_TOP([{ id: "nova", accountId: "a", model: "gpt-6-nova", newSince: NM_T - 3600 }]));'
     ' return [p.account.id, p.from.block.id, p.from.gone, p.onto.map((r) => r.block.id)]; })()',
     '["a","old",true,["sol7","terra","nova","luna","misc"]]',
     "куда перецепить ушедшую gpt-6-sol: ближайшая по имени (gpt-7-sol), при равной похожести — та, что на канбане "
     "(terra раньше новой скрытой nova, хотя карточка ставит новые выше), потом порядок карточки; сама модель и другая ушедшая — не цели"),
    ("gone_cables_nothing_to_offer",
     '',
     'await (async () => { const [g, log] = GMC({ answer: "sol7" }); const lone = { cloudAccounts: [{ id: "a" }], routers: [],'
     ' cloudProviders: [{ id: "old", accountId: "a", model: "m", unlisted: true }, { id: "g2", accountId: "a", model: "n", unlisted: true }] };'
     ' const orphan = { cloudAccounts: [], routers: [], cloudProviders: [{ id: "old", accountId: "gone-account", model: "m" }] };'
     ' return [g.targets("nope", GM_TOP()), g.targets("old", orphan), g.targets("old", null), await g.offer("old", lone), log.asks.length, log.calls.length]; })()',
     '[null,null,null,null,0,0]',
     "negative: модели нет, её провайдера нет, нет топологии — целей нет (null, а не пустой список); все остальные модели провайдера тоже ушли — окно не открывается"),
    ("gone_cables_offer_moves",
     '',
     'await (async () => { const [g, log] = GMC({ answer: "sol7" }); const r = await g.offer("old", GM_TOP()); const { msg, opts } = log.asks[0];'
     ' return [r, msg === fill(en.goneMoveText, { model: "gpt-6-sol", provider: "OpenAI" }), opts.title === fill(en.goneMoveTitle, { model: "gpt-6-sol" }),'
     ' opts.choiceLabel === en.goneMoveChoiceLabel, opts.confirmLabel === en.goneMoveApply, opts.danger, opts.list,'
     ' opts.choices.map((c) => c.value), opts.choices[0].label === "gpt-7-sol · " + en.cloudChipKanban + " · " + fill(en.cloudModelCables, { n: "1" }),'
     ' opts.choices[2].label === "gpt-6-luna", log.calls, log.notes[0] === fill(en.newModelMoved, { model: "gpt-7-sol", n: "2" }), log.applied]; })()',
     '["sol7",true,true,true,true,false,true,["sol7","terra","luna","misc"],true,true,'
     '[["/api/cloud-blocks/move-cables",{"from":"old","to":"sol7"}]],true,[{"t":3}]]',
     "окно: заголовок и текст с моделью и провайдером, «На», «Перецепить», тон вопроса, длинный список столбцом; "
     "варианты с метками «на канбане» и канатами; перенос — тем же маршрутом, что у окна новой модели; тост с числом; доска из ответа"),
    ("gone_cables_cancel_and_refusal",
     '',
     'await (async () => { const [g, l1] = GMC({ answer: null }); const r1 = await g.offer("old", GM_TOP());'
     ' const [h, l2] = GMC({ answer: "sol7", fail: true }); const r2 = await h.offer("old", GM_TOP());'
     ' const [k, l3] = GMC({ answer: "sol7", res: {} }); const r3 = await k.offer("old", GM_TOP());'
     ' return [r1, l1.calls.length, r2, l2.notes, l2.applied.length, r3, l3.notes, l3.applied.length]; })()',
     '[null,0,null,["controller is down"],0,"sol7",[],0]',
     "negative: отмена — ничего не шлёт; отказ контроллера — тост с причиной, доска не трогается; ответ без числа и доски — ни тоста «0», ни доски"),
    ("gone_row_button_only_where_it_can_help",
     '',
     '(() => { const html = (top) => new cm.ProviderModels({ account: top.cloudAccounts[0], blocks: top.cloudProviders, routers: top.routers, now: NM_NOW }).html();'
     ' const h = html(GM_TOP()); const lone = GM_TOP(); lone.cloudProviders = lone.cloudProviders.filter((b) => b.unlisted);'
     ' const dflt = GM_TOP(); dflt.routers = [{ rules: { default: "cb:gone2" }, graph: { edges: [] } }];'
     ' return [(h.match(/data-cloud-move-cables="([^"]+)"/g) || []), h.includes(escapeHtmlLike(en.cloudMoveCables)),'
     ' (html(lone).match(/data-cloud-move-cables/g) || []).length, (html(dflt).match(/data-cloud-move-cables="([^"]+)"/g) || [])]; })()',
     '[["data-cloud-move-cables=\\"old\\""],true,0,["data-cloud-move-cables=\\"gone2\\""]]',
     "кнопка «⇄ Перецепить…» — только у ушедшей модели, к которой что-то ведёт (канаты или «по умолчанию»); "
     "negative: у ушедшей без канатов её нет, у живой с канатами нет, и нет, когда у провайдера не осталось живых моделей"),
    ("gone_button_click_offers_the_move",
     '',
     'await (async () => { const lane = { innerHTML: "", dataset: {}, handlers: [], addEventListener(type, fn) { if (type === "click") this.handlers.push(fn); }, querySelector: () => null };'
     ' globalThis.__fields.topologyCloudProviders = lane; m.renderTopologyCloudProviders(); const seen = [];'
     ' m.GONE_CABLES.offer = async (id) => { seen.push(id); return null; };'
     ' try { let sp = 0; const btn = { dataset: { cloudMoveCables: "old" }, disabled: false };'
     ' const ev = { stopPropagation: () => sp++, target: { closest: (s) => (s === "[data-cloud-move-cables]" ? btn : (s === "[data-cloud-block]" ? { dataset: { cloudBlock: "old" } } : null)) } };'
     ' for (const h of lane.handlers) await h(ev); return [seen, sp, btn.disabled, m.topologyCloudBlockForm, m.GONE_CABLES instanceof cm.GoneModelCables]; }'
     ' finally { delete m.GONE_CABLES.offer; } })()',
     '[["old"],1,false,null,true]',
     "щелчок по «⇄ Перецепить…» предлагает перенос этой модели, а не открывает её окно (строка под кнопкой не срабатывает); кнопка снова доступна после ответа"),
    ("codex_version_under_the_gear",
     'st.setTopology(TOPO({ cloudApiHealth: { codexClientVersion: { value: "0.160.0", source: "floor" } } }));',
     '(() => { const line = (h) => (h.match(/cloud-api-version"[^>]*>([^<]*)</) || [])[1] || null;'
     ' m.openCloudAccountModal("openai-subscription"); const sub = line(m.renderTopologyCloudAccountModal()); m.closeCloudProviderModal();'
     ' m.openCloudAccountModal("ollama"); const other = line(m.renderTopologyCloudAccountModal()); m.closeCloudProviderModal();'
     ' m.renderTopologyCloudProviders(); const card = lane().includes("cloud-api-version");'
     ' st.setTopology(TOPO()); m.openCloudAccountModal("openai-subscription"); const none = line(m.renderTopologyCloudAccountModal()); m.closeCloudProviderModal();'
     ' st.setTopology(TOPO({ cloudApiHealth: { codexClientVersion: { value: "0.161.0" } } })); m.openCloudAccountModal("openai-subscription");'
     ' const noSource = line(m.renderTopologyCloudAccountModal()); m.closeCloudProviderModal();'
     ' return [sub, other, card, none, noSource, m.isSubscriptionAccount({ baseUrl: "https://chatgpt.com/backend-api" }),'
     ' m.isSubscriptionAccount({ accountType: "openai-subscription" }), m.isSubscriptionAccount({ accountType: "openai", baseUrl: "https://api.openai.com/v1" }),'
     ' m.isSubscriptionAccount(null)]; })()',
     '["codex client_version: 0.160.0 · floor",null,false,null,"codex client_version: 0.161.0",true,true,false,false]',
     "версия Codex — под ⚙, в окне аккаунта подписки (решение оператора, вариант A), а не на карточке; "
     "negative: у другого провайдера её нет; версия неизвестна — строки нет (а не «undefined»); без источника — без « · »"),
    ("port_closer_keeps_the_model_when_a_port_remains",
     '',
     'await (async () => { const [c, log] = PCL(); const r = await c.close("sol", 23009, PC_TOP()); const { msg, opts } = log.confirms[0];'
     ' return [msg === fill(en.portCloseKeep, { model: "gpt-6-sol", ports: ":23004" }) + " " + en.portNoRequest,'
     ' opts.title === fill(en.portCloseTitle, { port: ":23009" }), opts.danger, opts.confirmLabel === en.portCloseApply,'
     ' log.asks.length, log.calls, log.notes[0] === fill(en.portClosed, { port: ":23009" }), log.applied, !!r]; })()',
     '[true,true,true,true,0,[["/api/cloud-accounts/bridge-port-delete",{"port":23009}]],true,[{"t":9}],true]',
     "закрыть один из двух портов: простой вопрос «останется на канбане на :23004» и когда через порт шёл запрос; "
     "про канаты не спрашивает — модель с канбана не уходит; ответ — доска"),
    ("port_closer_last_port_nothing_held",
     '',
     'await (async () => { const [c, log] = PCL(); await c.close("luna", 23005, PC_TOP()); const { msg } = log.confirms[0];'
     ' return [msg === fill(en.portCloseConfirm, { model: "gpt-6-luna" }) + " " + en.portNoRequest, log.calls]; })()',
     '[true,[["/api/cloud-blocks/refs?id=luna"],["/api/cloud-accounts/bridge-port-delete",{"port":23005}]]]',
     "последний порт модели, которую ничего не держит: сначала спрашивает у контроллера, что держит, потом — «уйдёт с канбана»"),
    ("port_closer_last_port_held_asks_where",
     '',
     'await (async () => { const top = PC_TOP(); top.proxies = top.proxies.filter((p) => p.port !== 23009);'
     ' const [c, log] = PCL({ refs: { held: { cables: 2, rules: ["default", "failover"] } }, answer: "luna", res: { closed: [23004], onto: "luna", moved: 4, topology: { t: 1 } } });'
     ' await c.close("sol", 23004, top); const { msg, opts } = log.asks[0];'
     ' return [msg === [fill(en.portCloseHeld, { model: "gpt-6-sol", cables: "2", rules: "2" }), en.portCloseDefault, fill(en.portLastRequest, { when: pcWhen(PC_T) })].join(" "),'
     ' opts.choiceLabel === en.portCloseChoiceLabel, opts.danger, opts.choices.map((x) => x.value), opts.choices[0].label === "gpt-6-luna · " + en.cloudChipKanban,'
     ' opts.choices[2].label === en.portCloseCut, log.calls[1], log.notes[0] === fill(en.portClosedMoved, { port: ":23004", model: "gpt-6-luna", n: "4" })]; })()',
     '[true,true,true,["luna","terra","__cut__"],true,true,["/api/cloud-accounts/bridge-port-delete",{"port":23004,"resolution":{"moveTo":"luna"}}],true]',
     "последний порт, а канаты и «по умолчанию» ещё ведут к модели: окно спрашивает куда — модели провайдера (ближайшая по имени, "
     "на канбане раньше) и «отсоединить»; ответ уходит резолюцией; тост называет, куда и сколько перенесено"),
    ("port_closer_cut",
     '',
     'await (async () => { const top = PC_TOP(); top.proxies = top.proxies.filter((p) => p.port !== 23009);'
     ' const [c, log] = PCL({ refs: { held: { cables: 2, rules: [] } }, answer: "__cut__", res: { closed: [23004], cut: 2, topology: {} } });'
     ' await c.close("sol", 23004, top); return [log.calls[1][1], log.notes[0] === fill(en.portClosedCut, { port: ":23004", n: "2" }), log.asks[0].msg.includes(en.portCloseDefault)]; })()',
     '[{"port":23004,"resolution":{"cut":true}},true,false]',
     "«отсоединить» — резолюция cut, тост со счётом; negative: не «по умолчанию» — строки про него нет"),
    ("port_closer_kanban_closes_all_ports",
     '',
     'await (async () => { const [c, log] = PCL(); await c.close("sol", null, PC_TOP());'
     ' return [log.confirms[0].opts.title === fill(en.portCloseTitle, { port: ":23004, :23009" }), log.calls[1]]; })()',
     '[true,["/api/cloud-blocks/expose",{"id":"sol","exposed":false}]]',
     "снять галочку на канбане = закрыть все порты модели: один вопрос на оба, запрос — снять с канбана"),
    ("port_closer_says_no_and_fails_safe",
     '',
     'await (async () => { const [a, la] = PCL({ ok: false }); const ra = await a.close("sol", 23009, PC_TOP());'
     ' const [b, lb] = PCL({ refs: { held: { cables: 1, rules: [] } }, answer: null }); const rb = await b.close("luna", 23005, PC_TOP());'
     ' const [c, lc] = PCL({ refsFail: true }); const rc = await c.close("luna", 23005, PC_TOP());'
     ' const [d, ld] = PCL({ refs: {} }); const rd = await d.close("luna", 23005, PC_TOP());'
     ' const [e, le] = PCL({ fail: true }); const re = await e.close("sol", 23009, PC_TOP());'
     ' const [f, lf] = PCL(); const rf = await f.close("terra", 23099, PC_TOP());'
     ' return [ra, la.calls.length, rb, lb.calls.length, rc, lc.notes, rd, ld.notes[0] === en.portCloseUnknown, ld.calls.length,'
     ' re, le.notes, le.applied.length, rf, lf.confirms.length + lf.calls.length]; })()',
     '[null,0,null,1,null,["refs down"],null,true,1,null,["controller is down"],0,null,0]',
     "negative: «отмена» в вопросе и в окне — ничего не шлёт; контроллер не сказал, что держит модель, — порт остаётся (а не закрывается вслепую); "
     "отказ при закрытии — тост с причиной, доска не трогается; порта нет — ничего не спрашивает"),
    ("port_closer_last_request_line",
     '',
     '[cm.PortCloser.lastRequestLine(PC_TOP(), [23004, 23009]) === fill(en.portLastRequest, { when: pcWhen(PC_T) }),'
     ' cm.PortCloser.lastRequestLine(PC_TOP(), [23005]) === en.portNoRequest, cm.PortCloser.lastRequestLine(null, [1]) === en.portNoRequest]',
     '[true,true,true]',
     "когда через порт шёл последний запрос (за приложением может кто-то сидеть); negative: не шёл или не знаем — так и сказано, а не «0»"),
    ("card_x_closes_through_the_closer",
     '',
     'await (async () => { const lane = { innerHTML: "", dataset: {}, handlers: [], addEventListener(type, fn) { if (type === "click") this.handlers.push(fn); }, querySelector: () => null };'
     ' globalThis.__fields.topologyCloudProviders = lane; st.setTopology(TOPO({ proxies: [{ port: 23004, kind: "service", providerId: "gpt-5-6-terra" }] }));'
     ' m.renderTopologyCloudProviders(); const seen = []; m.PORT_CLOSER.close = async (id, port) => { seen.push([id, port]); return null; };'
     ' try { let sp = 0; const ev = { stopPropagation: () => sp++, target: { closest: (s) => (s === "[data-bridge-delete]" ? { dataset: { bridgeDelete: "23004" } } : null) } };'
     ' for (const h of lane.handlers) await h(ev); return [seen, sp, m.PORT_CLOSER instanceof cm.PortCloser, calls().length]; }'
     ' finally { delete m.PORT_CLOSER.close; } })()',
     '[[["gpt-5-6-terra",23004]],1,true,0]',
     "✕ у порта на карточке закрывает через окно закрытия (модель берётся из маршрута порта), сам ничего не шлёт"),
    ("card_row_chip_says_on_kanban_only",
     '',
     '(() => { const pm = new cm.ProviderModels({ account: { id: "a", hasCredential: true }, blocks: PC_TOP().cloudProviders, routers: [], proxies: PC_TOP().proxies, now: NM_NOW });'
     ' const rows = pm.rows(); const row = (id) => pm.rowHtml(rows.find((r) => r.block.id === id), true);'
     ' return [row("sol").includes(\'class="cloud-chip shown"\'), row("terra").includes("cloud-chip hidden"), row("terra").includes(\'class="cloud-chip shown"\'), row("terra").includes("data-bridge-mint")]; })()',
     '[true,false,false,true]',
     "у модели с портом — «на канбане»; у модели без порта метки нет — её место на канбане открывает «＋ port»"),
    ("provider_models_spend_on_their_rows",
     '',
     '(() => { const spend = { windowDays: 30, total: 700, requests: 60, byModel: [{ model: "GPT-5.6-TERRA", cost: 547.38, requests: 40 },'
     ' { model: "gpt-6-luna", cost: 0, requests: 12 }, { model: "gpt-4o", cost: 3.2, requests: 5 }, { model: "mystery", cost: 0, requests: 3 }] };'
     ' const pm = new cm.ProviderModels({ account: { id: "a" }, blocks: PC_TOP().cloudProviders,'
     ' routers: [], proxies: [], now: NM_NOW, spend }); const rows = pm.rows(); const cell = (id) => (pm.rowHtml(rows.find((r) => r.block.id === id)).match(/<span class="cloud-block-spend" title="([^"]*)">([^<]*)</) || [0, null, null]);'
     ' const html = pm.html();'
     ' return [cell("terra")[2] === fill(en.cloudModelSpend, { cost: "$547", days: "30" }), cell("terra")[1] === fill(en.cloudModelSpendTitle, { days: "30", req: "40" }),'
     ' cell("luna")[2] === fill(en.cloudModelSpendReq, { req: "12", days: "30" }), cell("sol")[2],'
     ' [...html.matchAll(/<span class="cloud-spend-item"><code>([^<]*)<\\/code> ([^<]*)</g)].map((x) => [x[1], x[2]]),'
     ' html.includes(fill(en.cloudSpendElsewhere, { days: "30" }))]; })()',
     json.dumps([True, True, True, None, [["gpt-4o", "≈ $3"], ["mystery", "3 req"]], True]),
     "доля модели за 30 дней — в её строке (оператор: «зачем строки дублировать»), по имени без учёта регистра; цены нет — "
     "число запросов, а не «$0»; negative: трафика не было — пусто; модели не из списка — одной строкой под ним, чтобы итог сходился"),
    ("provider_models_money_and_no_spend",
     '',
     '(() => { const M = cm.ProviderModels.money; const bare = new cm.ProviderModels({ account: { id: "a" }, blocks: PC_TOP().cloudProviders, now: NM_NOW });'
     ' return [M(547.38), M(1234.5), M(0.4), M(0.004), M(0), bare.html().includes("cloud-block-spend"), bare.html().includes("cloud-spend-elsewhere"),'
     ' new cm.ProviderModels({ account: { id: "a" }, blocks: [], spend: { byModel: "junk" } }).spentOn("x")]; })()',
     '["$547","$1,235","$0.40","<$0.01","<$0.01",false,false,null]',
     "деньги в строках: от доллара — целыми (как итоговая строка), меньше — центами, совсем мало — «<$0.01», а не «$0»; "
     "negative: записи о трафике нет или она испорчена — ни долей, ни строки «ещё»"),
    ("new_model_nothing_open",
     '',
     '(() => { const seen = []; const N = cm.NewModelAnnouncer.nothingOpen; const drawn = { getClientRects: () => [{}] };'
     ' const waiting = { getClientRects: () => [], closest: () => null };'
     ' return [N({ querySelectorAll: (s) => (seen.push(s), [waiting, drawn]) }), N({ querySelectorAll: () => [waiting, waiting] }),'
     ' N({ querySelectorAll: () => [] }), N({}), N(null), seen]; })()',
     '[false,true,true,false,false,["[aria-modal=\\"true\\"]"]]',
     "открыто (нарисовано) окно — не спрашивать; defect-history: окошко ячейки ждёт в строке с display:none без атрибута hidden — "
     "на живой доске семь таких считались открытыми, и окно не спросило бы никогда; negative: нет документа — считать, что занято"),
    ("row_keys_open_the_model_not_over_its_buttons",
     '',
     'await (async () => { const lane = { innerHTML: "", dataset: {}, keys: [], addEventListener(type, fn) { if (type === "keydown") this.keys.push(fn); }, querySelector: () => null };'
     ' globalThis.__fields.topologyCloudProviders = lane; m.renderTopologyCloudProviders();'
     ' const row = { dataset: { cloudBlock: "gpt-5-6-terra" }, matches: (s) => s === "[data-cloud-block]", closest: (s) => (s === "[data-cloud-block]" ? row : null) };'
     ' const button = { dataset: { bridgeMint: "gpt-5-6-terra" }, matches: () => false, closest: (s) => (s === "[data-cloud-block]" ? row : null) };'
     ' const press = (target, key) => { let prevented = false; lane.keys.forEach((fn) => fn({ key, target, preventDefault: () => { prevented = true; } })); return prevented; };'
     ' const onButton = [press(button, "Enter"), m.topologyCloudBlockForm];'
     ' const onRow = [press(row, "Enter"), m.topologyCloudBlockForm?.blockId]; m.closeCloudBlockModal();'
     ' const other = [press(row, "a"), m.topologyCloudBlockForm];'
     ' return [lane.keys.length, onButton, onRow, other]; })()',
     '[1,[false,null],[true,"gpt-5-6-terra"],[false,null]]',
     "defect-history: Enter на «＋ port» в строке модели открывал окно модели и гасил нажатие — порт с клавиатуры не выдавался; "
     "Enter на самой строке открывает её модель; negative: другая клавиша — ничего"),
    ("usage_refresh_once_per_click_after_renders",
     '',
     'await (async () => { const lane = { innerHTML: "", dataset: {}, handlers: [], addEventListener(type, fn) { if (type === "click") this.handlers.push(fn); }, querySelector: () => null };'
     ' globalThis.__fields.topologyCloudProviders = lane;'
     ' for (let i = 0; i < 3; i++) { st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); }'
     ' globalThis.__fetchCalls.length = 0; let sp = 0;'
     ' const ev = (sel, data) => ({ stopPropagation: () => sp++, target: { closest: (s) => (s === sel ? { dataset: data } : null) } });'
     ' for (const [sel, data] of [["[data-usage-refresh]", { usageRefresh: "openai-subscription" }], ["[data-api-costs-refresh]", { apiCostsRefresh: "ollama" }],'
     '   ["[data-or-limits-refresh]", { orLimitsRefresh: "bare" }], ["nothing", {}]]) { for (const h of lane.handlers) await h(ev(sel, data)); }'
     ' await settle(); return [lane.handlers.length, sp, calls().map((c) => c.path)]; })()',
     '[1,3,["/api/cloud-accounts/subscription-usage?id=openai-subscription","/api/cloud-accounts/api-costs?id=ollama","/api/cloud-accounts/openrouter-limits?id=bare"]]',
     "defect-history: три перерисовки — один делегат на лейне, один ↻ — один запрос своего вида (было: делегат на каждой перерисовке, K запросов в chatgpt.com); щелчок мимо кнопок — ничего"),
    ("lane_memoised_by_key", '',
     '(() => { m.renderTopologyCloudProviders(); globalThis.__fields.topologyCloudProviders.innerHTML = "WIPED"; m.renderTopologyCloudProviders(); const a = lane(); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); return [a, lane().includes("cloud-account-card")]; })()',
     '["WIPED",true]', "тот же ключ — лейна не перерисовывается; сброс ключа — перерисовывается"),
    ("lane_no_element_is_noop",
     'delete globalThis.__fields.topologyCloudProviders;',
     '(() => { m.renderTopologyCloudProviders(); return st.ui._lastCloudProvidersKey.length > 0; })()',
     'true', "negative: элемента лейны нет — без исключения"),
    # ── saveCloudAccount ──
    ("save_account_rejects_bad_url",
     'm.selectCloudProviderType("custom"); st.ui.topologyCloudForm.name = "Local"; st.ui.topologyCloudForm.baseUrl = "10.0.0.9:8000";',
     'await (async () => { await m.saveCloudAccount(); return [calls().length, toastText(), m.topologyCloudBusy, st.ui.topologyCloudModalOpen]; })()',
     '[0,"base URL must be http(s)",false,true]', "negative: URL без схемы — ни одного запроса, модал остаётся открытым"),
    ("save_account_new_chain",
     'm.selectCloudProviderType("openai"); st.ui.topologyCloudForm.name = "OpenAI (ChatGPT Plus)"; st.ui.topologyCloudForm.apiKey = " sk-x ";'
     ' globalThis.__fetchReply["/api/cloud-accounts/key"] = { ok: true }; globalThis.__fetchReply["/api/cloud-accounts/auto-create-blocks"] = { ok: true, created: 2, total: 5 };',
     'await (async () => { await m.saveCloudAccount(); const c = calls(); return [c.map((x) => x.path), c[0].body.account.id, c[0].body.account.baseUrl, c[0].body.account.authMode, c[1].body.apiKey, toastText(), st.ui.topologyCloudModalOpen]; })()',
     '[["/api/cloud-accounts/save","/api/cloud-accounts/key","/api/cloud-accounts/auto-create-blocks"],"openai-chatgpt-plus","https://api.openai.com/v1","apiKey","sk-x","cloud provider saved · 2 models added",false]',
     "новый аккаунт: save → key (обрезан) → автосоздание блоков; id — слаг имени; baseUrl из пресета, когда поле пустое"),
    ("save_account_key_rejected_stops_chain",
     'm.selectCloudProviderType("openai"); st.ui.topologyCloudForm.name = "Fresh"; st.ui.topologyCloudForm.apiKey = "bad";'
     ' globalThis.__fetchReply["/api/cloud-accounts/key"] = { ok: false, test: { error: "401" } };',
     'await (async () => { await m.saveCloudAccount(); return [calls().map((x) => x.path), toastText(), m.topologyCloudBusy, st.ui.topologyCloudModalOpen]; })()',
     '[["/api/cloud-accounts/save","/api/cloud-accounts/key"],"key rejected: 401",false,true]',
     "отказ ключа: автосоздания нет, модал открыт, busy снят — оператор видит причину"),
    ("save_account_edit_without_key_sends_nothing",
     'm.openCloudAccountModal("ollama");',
     'await (async () => { await m.saveCloudAccount(); return [calls().length, toastText(), st.ui.topologyCloudModalOpen]; })()',
     '[0,"cloud provider saved",false]', "правка без нового ключа: на провод ничего, модал закрыт"),
    ("save_account_edit_rename_saves",
     'm.openCloudAccountModal("ollama"); st.ui.topologyCloudForm.name = "Ollama (home)"; globalThis.__fetchReply["/api/cloud-accounts/save"] = { ok: true };',
     'await (async () => { await m.saveCloudAccount(); const c = calls(); return [c.map((x) => x.path), c[0].body.account, toastText(), st.ui.topologyCloudModalOpen]; })()',
     '[["/api/cloud-accounts/save"],{"id":"ollama","type":"ollama","name":"Ollama (home)","baseUrl":"https://ollama.com","authMode":"apiKey"},"cloud provider saved",false]',
     "defect-history: правка имени уходит на сервер — раньше правка существующего аккаунта не отправляла ничего и всё равно говорила «saved»"),
    ("save_account_edit_rename_and_key",
     'm.openCloudAccountModal("ollama"); st.ui.topologyCloudForm.name = "Ollama (home)"; st.ui.topologyCloudForm.apiKey = "k3";'
     ' globalThis.__fetchReply["/api/cloud-accounts/save"] = { ok: true }; globalThis.__fetchReply["/api/cloud-accounts/key"] = { ok: true };',
     'await (async () => { await m.saveCloudAccount(); return calls().map((x) => x.path); })()',
     '["/api/cloud-accounts/save","/api/cloud-accounts/key"]', "имя и ключ вместе: сначала аккаунт, потом ключ; автосоздания блоков нет"),
    ("save_account_edit_bad_url",
     'm.openCloudAccountModal("bare"); st.ui.topologyCloudForm.baseUrl = "10.0.0.9:9000";',
     'await (async () => { await m.saveCloudAccount(); return [calls().length, toastText(), m.topologyCloudBusy, st.ui.topologyCloudModalOpen]; })()',
     '[0,"base URL must be http(s)",false,true]', "negative: правка адреса без схемы — ни запроса, модал открыт"),
    ("save_account_edit_with_key_only_key",
     'm.openCloudAccountModal("ollama"); st.ui.topologyCloudForm.apiKey = "k2"; globalThis.__fetchReply["/api/cloud-accounts/key"] = { ok: true };',
     'await (async () => { await m.saveCloudAccount(); const c = calls(); return [c.map((x) => x.path), c[0].body]; })()',
     '[["/api/cloud-accounts/key"],{"id":"ollama","apiKey":"k2"}]', "правка с ключом: только /key, без save и автосоздания"),
    ("save_account_no_form_is_noop", '', 'await (async () => { await m.saveCloudAccount(); return calls().length; })()', '0', "negative: без формы — ничего"),
    # ── saveCloudBlock ──
    ("save_block_needs_model",
     'm.openCloudBlockModal(null, "bare");',
     'await (async () => { await m.saveCloudBlock(); return [calls().length, toastText(), m.topologyCloudBlockModalOpen]; })()',
     '[0,"Pick a model first",true]', "negative: без модели — ни запроса, модал открыт"),
    ("save_block_new_sends_blank_window_as_blank",
     'm.openCloudBlockModal(null, "bare"); globalThis.__q = { \'[data-block-field="model"]\': { value: "llama-x" }, \'[data-block-field="contextLength"]\': { value: "  " }, "[data-block-field-expose]": { checked: false } };',
     'await (async () => { await m.saveCloudBlock(); const c = calls(); return [c[0].path, c[0].body.block, m.topologyCloudBlockModalOpen]; })()',
     '["/api/cloud-blocks/save",{"id":"llama-x","accountId":"bare","name":"llama-x","model":"llama-x","modelMode":"rewrite","contextLength":"","contextAuto":false,"exposed":false},false]',
     "defect-class: пустое окно уходит пустым (не 0), contextAuto false уходит явно; id блока — слаг модели; expose из галки"),
    ("save_block_custom_model_wins_and_window_sent",
     'openBlock("gpt-5-6-terra", null); globalThis.__q = { \'[data-block-field="model"]\': { value: "gpt-5.6-terra" }, "[data-block-field-custom]": { value: "gpt-5.6-terra" }, \'[data-block-field="contextLength"]\': { value: "158000" }, "[data-block-field-context-auto]": { checked: true }, \'[data-block-field="modelMode"]\': { value: "passthrough" } };',
     'await (async () => { await m.saveCloudBlock(); const b = calls()[0].body.block; return [b.id, b.model, b.modelMode, b.contextLength, b.contextAuto, "exposed" in b]; })()',
     '["gpt-5-6-terra","gpt-5.6-terra","passthrough","158000",true,false]',
     "правка: id сохраняется, режим и окно уходят как введены, exposed при правке не шлётся"),
    ("save_block_model_change_needs_confirm",
     'openBlock("gpt-5-6-terra", null); globalThis.__q = { \'[data-block-field="model"]\': { value: "gpt-5.6-luna" } }; globalThis.__stubReturns["dialogs.appConfirm"] = async () => false;',
     'await (async () => { await m.saveCloudBlock(); return [calls().length, m.topologyCloudBlockModalOpen]; })()',
     '[0,true]', "смена модели существующего блока без подтверждения — ни запроса (так terra однажды стала второй sol)"),
    ("save_block_duplicate_model_needs_confirm",
     'openBlock(null, "openai-subscription"); globalThis.__q = { \'[data-block-field="model"]\': { value: "gpt-5.6-luna" } }; globalThis.__stubReturns["dialogs.appConfirm"] = async () => false;',
     'await (async () => { await m.saveCloudBlock(); return calls().length; })()',
     '0', "второй блок той же модели без подтверждения — ни запроса"),
    ("save_block_duplicate_confirmed_gets_suffix",
     'openBlock(null, "openai-subscription"); globalThis.__q = { \'[data-block-field="model"]\': { value: "gpt-5.6-luna" }, "[data-block-field-expose]": { checked: true } };',
     'await (async () => { await m.saveCloudBlock(); return [calls()[0].body.block.id, calls()[0].body.block.exposed]; })()',
     '["gpt-5-6-luna-2",true]', "подтверждённый дубль получает id с суффиксом"),
    # ── deletions ──
    ("delete_block_posts_and_closes",
     'openBlock("gpt-5-6-luna", null);',
     'await (async () => { await m.deleteCloudBlock(); const c = calls(); return [c[0].path, c[0].body, m.topologyCloudBlockModalOpen, m.topologyCloudBlockForm]; })()',
     '["/api/cloud-blocks/delete",{"id":"gpt-5-6-luna"},false,null]', "удаление блока: один POST с id, модал закрыт"),
    ("delete_block_new_form_is_noop",
     'openBlock(null, "ollama");',
     'await (async () => { await m.deleteCloudBlock(); return [calls().length, m.topologyCloudBlockModalOpen]; })()',
     '[0,true]', "negative: у нового блока нет id — удалять нечего, модал остаётся"),
    ("delete_account_posts_and_closes",
     'm.openCloudAccountModal("bare");',
     'await (async () => { await m.deleteCloudAccount(); const c = calls(); return [c[0].path, c[0].body, st.ui.topologyCloudModalOpen]; })()',
     '["/api/cloud-accounts/delete",{"id":"bare"},false]', "удаление аккаунта: один POST, модал закрыт"),
    ("delete_account_without_form_is_noop", '', 'await (async () => { await m.deleteCloudAccount(); return calls().length; })()', '0', "negative: без формы — ничего"),
    # ── OAuth ──
    ("pool_connect_simple_form",
     'm.selectCloudProviderType("openai-subscription", "work-pool");',
     '(() => { const h=m.renderTopologyCloudAccountModal(); return [st.ui.topologyCloudForm.poolId,h.includes("Client ID"),h.includes("data-cloud-oauth-login"),h.includes("data-cloud-picker-change")]; })()',
     '["work-pool",false,true,false]', "новая подписка из пула: простой вход без настроек протокола"),
    ("pool_oauth_creates_pending_member_then_starts",
     'm.selectCloudProviderType("openai-subscription", "work-pool"); st.ui.topologyCloudForm.name="Third"; globalThis.__fetchReply["/api/cloud-accounts/oauth/start"]={ok:true,authorizeUrl:"https://auth.example/x",state:"s3"};',
     'await (async () => { await m.startCloudOauthLogin(); const c=calls(); return [c[0].path,c[0].body.poolId,c[0].body.account.id,c[1].path,st.ui.topologyCloudForm.oauthLoginState]; })()',
     '["/api/cloud-pools/connect-account","work-pool","third","/api/cloud-accounts/oauth/start","s3"]', "третья подписка резервируется в пуле перед входом"),
    ("pool_save_without_login_does_not_create_standalone_model",
     'm.selectCloudProviderType("openai-subscription", "work-pool"); st.ui.topologyCloudForm.name="Third";',
     'await (async () => { await m.saveCloudAccount(); return [calls().map(c=>c.path),m.topologyCloudBlockModalOpen]; })()',
     '[["/api/cloud-pools/connect-account"],false]', "без входа сохранён только ожидающий участник; отдельный блок не создаётся"),
    ("oauth_pasted_callback_cleared_after_completion",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.oauthLoginState="s3"; st.ui.topologyCloudForm.oauthCallbackUrl="http://localhost:1455/auth/callback?code=secret&state=s3"; globalThis.__fetchReply["/api/cloud-accounts/oauth/complete"]={state:"done"};',
     'await (async () => { await m.completeCloudOauthLogin(); return [calls()[0].path,calls()[0].body.state,st.ui.topologyCloudForm.oauthLoginState,st.ui.topologyCloudForm.oauthCallbackUrl]; })()',
     '["/api/cloud-accounts/oauth/complete","s3","",""]', "вставленная ссылка заканчивает нужный вход и удаляется из формы"),
    ("oauth_new_account_saves_then_starts_then_opens",
     'm.selectCloudProviderType("openai-subscription"); st.ui.topologyCloudForm.name = "Plus"; globalThis.__fetchReply["/api/cloud-accounts/oauth/start"] = { ok: true, authorizeUrl: "https://auth.example/x", state: "s1" };',
     'await (async () => { await m.startCloudOauthLogin(); const c = calls(); const f = st.ui.topologyCloudForm; return [c.map((x) => x.path), c[0].body.account.authMode, c[0].body.account.oauthConfig.clientId, f.isNew, f.accountId, [...globalThis.__opened], c[2]?.path]; })()',
     '[["/api/cloud-accounts/save","/api/cloud-accounts/oauth/start","/api/cloud-accounts/oauth/status?state=s1"],"oauth","cid",false,"plus",["https://auth.example/x"],"/api/cloud-accounts/oauth/status?state=s1"]',
     "OAuth для нового аккаунта: save с authMode oauth и конфигом → start → окно браузера → первый опрос статуса"),
    ("oauth_start_without_url_stops",
     'm.openCloudAccountModal("openai-subscription"); globalThis.__fetchReply["/api/cloud-accounts/oauth/start"] = { ok: false };',
     'await (async () => { await m.startCloudOauthLogin(); return [calls().map((x) => x.path), toastText(), globalThis.__opened.length]; })()',
     '[["/api/cloud-accounts/oauth/start"],"oauth start failed",0]', "negative: start без authorizeUrl — окно не открывается"),
    ("oauth_poll_done_sets_status_and_topology",
     'm.openCloudAccountModal("openai-subscription"); globalThis.__fetchReply["/api/cloud-accounts/oauth/status?state=s1"] = { state: "done", email: "me@x", topology: TOPO({ cloudAccounts: [] }) };',
     'await (async () => { m.pollCloudOauth("s1"); await settle(); return [st.ui.topologyCloudForm.oauthStatus, toastText(), st.topology.cloudAccounts.length, polls().length]; })()',
     '["OAuth connected · me@x","OAuth connected",0,0]', "done: статус с почтой, тост, topology применена, повторного опроса нет"),
    ("oauth_poll_pending_reschedules_2s",
     'm.openCloudAccountModal("openai-subscription"); globalThis.__fetchReply["/api/cloud-accounts/oauth/status?state=s1"] = { state: "pending" };',
     'await (async () => { m.pollCloudOauth("s1"); await settle(); return polls(); })()',
     '["poll:2000"]', "pending: следующий опрос через 2 с"),
    ("oauth_poll_error_sets_status", 
     'm.openCloudAccountModal("openai-subscription"); globalThis.__fetchReply["/api/cloud-accounts/oauth/status?state=s1"] = { state: "error", error: "denied" };',
     'await (async () => { m.pollCloudOauth("s1"); await settle(); return [st.ui.topologyCloudForm.oauthStatus, polls().length]; })()',
     '["OAuth failed: denied",0]', "error: причина в статусе, опрос остановлен"),
    ("oauth_poll_closed_modal_does_nothing", '',
     '(() => { m.pollCloudOauth("s1"); return calls().length; })()', '0', "negative: модал закрыт — опроса нет"),
    ("oauth_poll_timeout_after_150",
     'm.openCloudAccountModal("openai-subscription");',
     '(() => { m.pollCloudOauth("s1", 151); return [st.ui.topologyCloudForm.oauthStatus, calls().length]; })()',
     '["OAuth timed out — try again",0]', "boundary: после 150 попыток — таймаут без запроса"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 40:
        print(f"js cloud FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js cloud: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_cloud.tmp.mjs"
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
        print(f"js cloud FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("облако: аккаунты, блоки моделей, мосты и пути записи:")
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
    print(f"js cloud OK: настоящий модуль в node, {len(PINS)} пинов облака значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
