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
(`nextTopologyCellPort` via __stubReturns), topology-render, dialogs
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
  st.ui._lastCloudProvidersKey = ""; st.ui.cloudModelsOpen = {}; st.ui.bridgeBlockChoice = {};
  globalThis.__fields = { toast: toastEl(), topologyCloudProviders: laneEl() }; globalThis.__q = {};
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__opened.length = 0; globalThis.__timers.length = 0;
  globalThis.__stubReturns = { "remote-cells.nextTopologyCellPort": () => 22011, "dialogs.appConfirm": async () => true };
};
reset();
// openCloudBlockModal сам тянет список моделей аккаунта — для пинов ЗАПИСИ этот
// GET не интересен, счётчик вызовов начинается после открытия.
const openBlock = (b, a) => { m.openCloudBlockModal(b, a); globalThis.__fetchCalls.length = 0; };
// api() = fetch → response.json() → then: несколько микротиков; setImmediate не
// подменён и даёт настоящий макротик, за который всё это оседает.
const settle = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setImmediate(r)); };
const polls = () => globalThis.__timers.filter((x) => x.startsWith("poll:"));
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
    ("fetch_models_failure_forgets_marker",
     'globalThis.__fetchReply["/api/cloud-accounts/models?id=ollama"] = { __status: 500, error: "boom" };',
     'await (async () => { await m.fetchCloudAccountModels("ollama"); await m.fetchCloudAccountModels("ollama"); return [calls().length, m.topologyCloudModelCache.get("ollama")]; })()',
     '[2,null]', "отказ не запоминается как ответ: маркер снят, следующий вызов идёт в сеть заново"),
    ("fetch_models_retry_after_failure_succeeds",
     '',
     'await (async () => { const k = "/api/cloud-accounts/models?id=ollama";'
     ' globalThis.__fetchReply[k] = { __status: 500, error: "boom" }; await m.fetchCloudAccountModels("ollama");'
     ' globalThis.__fetchReply[k] = { ok: true, models: [{ id: "qwen3" }] }; await m.fetchCloudAccountModels("ollama");'
     ' return [calls().length, (m.topologyCloudModelCache.get("ollama") || []).map((x) => x.id)]; })()',
     '[2,["qwen3"]]', "positive: попытка после отказа приносит список — пустая выдача не осталась на его месте"),
    ("fetch_subscription_failure_forgets_marker",
     'globalThis.__fetchReply["/api/cloud-accounts/subscription-models?id=openai-subscription"] = { __status: 500, error: "boom" };',
     'await (async () => { await m.fetchCloudSubscriptionModels("openai-subscription"); await m.fetchCloudSubscriptionModels("openai-subscription"); return [calls().length, m.topologyCloudModelCache.get("openai-subscription")]; })()',
     '[2,null]', "подписочный список — тот же ответ на отказ: у обоих одно тело, разъехаться нечему"),
    ("prefetch_all_by_kind", '',
     'await (async () => { m.prefetchAllSubscriptionModels(); await Promise.resolve(); return calls().map((c) => c.path).sort(); })()',
     '["/api/cloud-accounts/models?id=ollama","/api/cloud-accounts/subscription-models?id=openai-subscription"]',
     "префетч: подписка — всегда, API-аккаунт — только с учётными данными, bare — нет"),
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
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [(h.match(/cloud-account-card/g) || []).length, h.indexOf("gpt-5.6-terra") < h.indexOf("gpt-5.6-luna"), h.includes("$10.00 / $30.00 /1M") || h.includes("/1M"), h.includes("needs-key"), h.includes("key set ••••ab12"), h.includes("Show all 2 models")]; })()',
     '[3,true,true,true,true,true]',
     "карточка на аккаунт; блоки от дорогих к дешёвым; без ключа — needs-key; счётчик моделей"),
    ("lane_marks_model_missing_from_provider_list",
     'm.topologyCloudModelCache.set("openai-subscription", [{ id: "gpt-5.6-terra" }]);',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [(h.match(/cloud-block-row stale/g) || []).length, h.includes("not listed by provider")]; })()',
     '[1,true]', "модель, которой провайдер больше не отдаёт, помечена — ровно одна"),
    ("lane_bridges_on_their_block_orphans_in_strip",
     'st.setTopology(TOPO({ proxies: BRIDGES() }));',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [h.includes(":8083"), h.includes("http://ctl:8083"), h.includes("cloud-orphan-bridges"), h.includes(":8084"), h.includes(":23001"), h.includes(\'data-bridge-mint="openai-subscription"\')]; })()',
     '[true,true,true,true,false,true]',
     "мост стоит на карточке блока с URL хоста; мост без блока — в полосе сирот; прокси агента (не service) в лейне нет"),
    ("lane_bridge_choice_survives_rerender",
     'st.ui.bridgeBlockChoice = { "openai-subscription": "gpt-5-6-luna" };',
     '(() => { m.renderTopologyCloudProviders(); return lane().includes(\'<option value="gpt-5-6-luna" selected>\'); })()',
     'true', "несохранённый выбор блока для моста живёт в ui и возвращается в select"),
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
