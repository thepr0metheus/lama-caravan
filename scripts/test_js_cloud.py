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
    ("lane_without_accounts",
     'st.setTopology(TOPO({ cloudAccounts: [], cloudProviders: [] }));',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [h.includes("no cloud providers — click + to add one"), h.includes("data-topo-add-cloud"), (h.match(/cloud-account-card/g) || []).length]; })()',
     '[true,true,0]', "без аккаунтов — подсказка и кнопка добавления"),
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
