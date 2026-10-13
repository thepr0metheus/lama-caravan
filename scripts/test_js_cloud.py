#!/usr/bin/env python3
"""Snapshot of static/js/cloud.js — the pools' lane, the accounts their steps stand on, the write paths.

The cloud under Model servers is the pools' cards (pools.js, pinned in test_js_pools.py) wired
to this module's readings, and the accounts behind the steps: the provider picker, the account
window and the sign-in by a one-time code. What's worth pinning by VALUE here: an account's id is
derived from its name as a slug with a counted suffix; a new account is saved before its key, and
a key the provider refuses stops the chain without a second account on the next Save; the
account window gives a new account back to the step window that sent the operator there — on
every exit, and only once; the lane draws a card per pool, a subscription step's limit bars with
the step's own switch levels, the step's model share of the spend in its head, and waits while a
slider or a rung is in the operator's hand; it redraws when the proxy's word changes, but not for
the second a choice was made.

The module is loaded FOR REAL (scripts/_js_harness.mjs). `usage-stats`, `pools` and
`pool-step-dialog` are real too: they export Map caches and classes, and the harness's stub
turns any export into a function. DOM-heavy neighbours are stubbed: polling, remote-cells,
topology-render, dialogs (`appConfirm`), canvas, and others.

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
  { type: "openai-subscription", name: "ChatGPT Plus", baseUrl: "https://chatgpt.com/backend-api", authModes: ["oauth"], accountType: "openai-subscription", oauth: { clientId: "cid" }, deviceLogin: true },
  { type: "custom", name: "Custom", authModes: ["apiKey", "noKey"] },
];
const ACCOUNTS = () => [
  { id: "openai-subscription", type: "openai", name: "OpenAI (ChatGPT Plus)", baseUrl: "https://chatgpt.com/backend-api", accountType: "openai-subscription", subscription: true, authMode: "oauth", hasCredential: true, credentialKind: "oauth", deviceLogin: true,
    usedIn: [{ poolId: "work", poolName: "Work", stepId: "openai-subscription" }] },
  { id: "ollama", type: "ollama", name: "Ollama cloud", baseUrl: "https://ollama.com", authMode: "apiKey", hasCredential: true, credentialKind: "apiKey", keyLast4: "ab12",
    usedIn: [{ poolId: "work", poolName: "Work", stepId: "ollama" }, { poolId: "night", poolName: "Night", stepId: "ollama" }] },
  { id: "bare", type: "custom", name: "Bare", baseUrl: "http://10.0.0.9:8000/v1", authMode: "apiKey", hasCredential: false, usedIn: [] },
];
const STEP = (id, accountId, model, extra = {}) => ({ id, accountId, model, enabled: true, switchAt: {}, stopAt: {}, ...extra });
const POOLS = () => [
  { id: "work", name: "Work", contextAuto: true, ports: [23009], switchMax: 90,
    steps: [STEP("openai-subscription", "openai-subscription", "gpt-5.6-terra", { switchAt: { "18000": 30, "604800": 20 }, stopAt: { "18000": 10, "604800": 20 }, usageAccountId: "openai-subscription", switchReached: null }),
      STEP("ollama", "ollama", "deepseek-v4-flash")] },
  { id: "night", name: "Night", contextAuto: false, ports: [], switchMax: 90,
    steps: [STEP("ollama", "ollama", "qwen3")] },
];
const TOPO = (extra = {}) => ({ proxies: [], clients: [], routers: [], assignments: {}, cloudProviderPresets: PRESETS(), cloudAccounts: ACCOUNTS(), pools: POOLS(),
  poolsRuntime: { available: true, pools: {}, events: [] }, ...extra });
const reset = () => {
  st.setState({ config: {} }); st.setTopology(TOPO());
  Object.keys(mm.modelPricing).forEach((k) => delete mm.modelPricing[k]);
  mm.modelPricing["gpt-5.6-terra"] = { inputPer1M: 10, outputPer1M: 30 };
  m.closeCloudProviderModal(); m.ACCOUNT_RETURN.after = null; m.POOL_STEPS.form = null;
  m.POOL_CARDS.open.clear(); m.POOL_CARDS.shown.clear(); if (m.POOL_CARDS.carry) m.POOL_CARDS.carry.phase = "idle";
  us.switchDrag.active = false; us.switchDrag.deferred = false;
  us.subscriptionUsageCache.clear(); us.apiCostsCache.clear(); us.openrouterLimitsCache.clear();
  st.ui._lastCloudProvidersKey = "";
  globalThis.__fields = { toast: toastEl(), topologyCloudProviders: laneEl() }; globalThis.__q = {};
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; globalThis.__opened.length = 0; globalThis.__timers.length = 0;
  globalThis.__stubReturns = { "dialogs.appConfirm": async () => true };
};
reset();
// api() = fetch → response.json() → then: несколько микротиков; setImmediate не
// подменён и даёт настоящий макротик, за который всё это оседает.
const settle = async () => { for (let i = 0; i < 3; i++) await new Promise((r) => setImmediate(r)); };
const polls = () => globalThis.__timers.filter((x) => x.startsWith("poll:"));
// Строки для ожиданий — из настоящей языковой таблицы, не по памяти.
const en = (await import(pathToFileURL(process.env.JS_ROOT + "/i18n/en.js").href)).default;
const fill = (s, v) => String(s).replace(/\{(\w+)\}/g, (_, k) => v[k]);
const esc = (s) => String(s).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
// The saved resets live in cloud.js's own card (not exported) and outlive a pin: a pin that
// reads them uses an account of its own. The proxy's spend is read once per 30 s: a pin draws
// once, so the record exists, and then fills it.
const SUB = (id) => ({ ...ACCOUNTS()[0], id, name: `Plus ${id}`, usedIn: [] });
const withSub = (id, extra = {}) => TOPO({ cloudAccounts: [...ACCOUNTS(), SUB(id)],
  pools: [{ ...POOLS()[0], steps: [STEP(id, id, "gpt-5.6-terra", { switchAt: { "18000": 10 }, usageAccountId: id }), STEP("ollama", "ollama", "deepseek-v4-flash")] }], ...extra });
const spendOf = async (rows) => { await drawn(); Object.keys(us.proxySpendData || {}).forEach((k) => delete us.proxySpendData[k]); Object.assign(us.proxySpendData, rows); };
// The lane with its listeners kept, so a pin can fire them the way the browser does.
const liveLane = () => { const l = { innerHTML: "", dataset: {}, handlers: {}, addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }, querySelector: () => null }; globalThis.__fields.topologyCloudProviders = l; return l; };
const drawn = async () => { st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); for (let i = 0; i < 8; i++) await new Promise((r) => setImmediate(r)); st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); return lane(); };
// One step of the lane's HTML, by its id, in the card of `pool`; its head is what stands above its fold.
const stepOf = (html, pool, id) => { const card = html.slice(html.indexOf(`data-pool-card="${pool}"`)); const at = card.indexOf(`data-pool-step="${id}"`); return at < 0 ? "" : card.slice(at, card.indexOf("</li>", at)); };
const headOf = (step) => step.slice(0, step.indexOf(`class="pool-step-more"`));
const out = {};
"""

PINS = [
    ("slug_from_display_name", '', 'm.topologyCloudSlug("OpenAI (ChatGPT Plus)")', '"openai-chatgpt-plus"',
     "слаг: строчные, всё лишнее — в дефис, края обрезаны"),
    ("slug_empty_is_acct", '', '[m.topologyCloudSlug(""), m.topologyCloudSlug("!!!")]', '["acct","acct"]',
     "negative: пустое имя и имя из одних знаков — «acct», а не пустой id"),
    ("slug_cut_to_40", '', 'm.topologyCloudSlug("a".repeat(60)).length', '40', "boundary: слаг режется до 40 символов"),
    ("unique_id_counts_up", '', '[m.topologyCloudUniqueId("x", ["x", "x-2"]), m.topologyCloudUniqueId("x", [])]', '["x-3","x"]',
     "занятый id получает суффикс -2, -3…; свободный остаётся как есть"),
    ("preset_by_type", '', '[m.topologyCloudPresetByType("openai")?.name, m.topologyCloudPresetByType("nope")]', '["OpenAI",null]',
     "пресет по типу; неизвестный тип — null, не {}"),
    # ── account window: opening ──
    ("select_type_fills_form_from_preset", '',
     '(() => { m.selectCloudProviderType("openai-subscription"); const f = st.ui.topologyCloudForm; return [f.isNew, f.name, f.baseUrl, f.authMode, f.oauthConfig.clientId, st.ui.topologyCloudModalOpen, st.ui.topologyCloudPickerOpen]; })()',
     '[true,"ChatGPT subscription 2","https://chatgpt.com/backend-api","oauth","cid",true,false]',
     "выбор типа: форма из пресета; подписка названа как её блок, по счёту («ChatGPT subscription 2» — одна уже есть; до 1.3.494 «OpenAI subscription 2»), две одноимённые делали «у какой кончился лимит» догадкой; пикер закрыт, модал открыт"),
    ("select_key_type_named_by_provider", '',
     '(() => { m.selectCloudProviderType("openai"); return st.ui.topologyCloudForm.name === en.cloudNameOpenai; })()',
     'true', "учётка с ключом названа словами провайдера из языковой таблицы"),
    ("select_unknown_type_defaults", '',
     '(() => { m.selectCloudProviderType("weird"); const f = st.ui.topologyCloudForm; return [f.type, f.name, f.authMode, f.baseUrl]; })()',
     '["weird","weird","apiKey",""]',
     "negative: тип без пресета — apiKey по умолчанию; имя — сам тип, а не пустота"),
    ("open_account_modal_unknown_is_noop", '',
     '(() => { m.openCloudAccountModal("ghost"); return [st.ui.topologyCloudModalOpen, st.ui.topologyCloudForm]; })()',
     '[false,null]', "negative: неизвестный аккаунт модал не открывает"),
    ("open_account_modal_edit", '',
     '(() => { m.openCloudAccountModal("ollama"); const f = st.ui.topologyCloudForm; return [f.isNew, f.accountId, f.type, f.name, f.authMode, f.apiKey]; })()',
     '[false,"ollama","ollama","Ollama cloud","apiKey",""]',
     "редактирование: форма из аккаунта, ключ никогда не подставляется"),
    ("close_provider_modal_resets", '',
     '(() => { const back = []; m.openCloudPicker((id) => back.push(id)); m.openCloudAccountModal("ollama"); m.closeCloudProviderModal(); m.closeCloudProviderModal(); return [st.ui.topologyCloudModalOpen, st.ui.topologyCloudPickerOpen, st.ui.topologyCloudForm, m.topologyCloudBusy, back]; })()',
     '[false,false,null,false,[null]]', "закрытие снимает всё, включая busy; окно шага, ждавшее учётку, получает «ничего» — один раз, второе закрытие его уже не зовёт"),
    # ── the account window returns its account to the step window ──
    ("account_return_once_on_every_exit", '',
     '(() => { const r = new m.AccountWindowReturn(); const got = []; r.wait((id) => got.push(id)); const waiting = r.waiting(); r.done("acc"); r.done("again"); r.wait("not a function"); const none = r.waiting(); r.wait((id) => got.push(id)); r.done(""); return [waiting, none, got]; })()',
     '[true,false,["acc",null]]', "ждущий получает учётку один раз; повтор — никому; не функция — не ждут; пустой id — это «ничего», а не пустая строка"),
    ("finish_gives_the_account_back", '',
     '(() => { const back = []; m.openCloudPicker((id) => back.push(id)); m.selectCloudProviderType("openai"); st.ui.topologyCloudForm.accountId = "fresh"; m.finishCloudAccountWindow(); return [back, st.ui.topologyCloudModalOpen, st.ui.topologyCloudForm]; })()',
     '[["fresh"],false,null]', "«Готово» и сохранение новой учётки отдают её окну шага и закрывают окно"),
    ("picker_opens_from_the_step_window", '',
     '(() => { m.openCloudPicker(() => {}); return [st.ui.topologyCloudPickerOpen, st.ui.topologyCloudModalOpen, m.ACCOUNT_RETURN.waiting()]; })()',
     '[true,false,true]', "«Подключить новую учётку» открывает выбор провайдера и запоминает, кому вернуть учётку"),
    # ── picker and modals: HTML ──
    ("picker_closed_is_empty", '', 'm.renderTopologyCloudPicker()', '""', "negative: закрытый пикер — пустая строка"),
    ("picker_two_groups",
     'st.ui.topologyCloudPickerOpen = true;',
     '(h => { const sub = h.indexOf(en.cloudPickerSubscription), key = h.indexOf(en.cloudPickerApiKey), tileSub = h.indexOf(\'data-pick-type="openai-subscription"\'), tileKey = h.indexOf(\'data-pick-type="openai"\'); return [(h.match(/data-pick-type="/g) || []).length, sub >= 0 && sub < tileSub && tileSub < key && key < tileKey, h.includes(">" + en.cloudNameSubscription + "<"), h.includes(">" + en.cloudDescSubscription + "<"), h.includes("ChatGPT Plus · OAuth")]; })(m.renderTopologyCloudPicker())',
     '[3,true,true,true,false]', "выбор провайдера: подписка отдельной группой над провайдерами с ключом; имена и описания из языковой таблицы; negative: английской строки, вшитой в код, нет"),
    ("window_new_key_account",
     'm.selectCloudProviderType("openai");',
     '(h => [m.cloudAccountWindowState(st.ui.topologyCloudForm, null), h.includes(">" + fill(en.cloudAddTitle, { name: en.cloudNameOpenai }) + "<"), h.includes(\'data-cloud-field="apiKey"\'), h.includes("data-cloud-delete-account"), h.includes(\'data-cloud-field="baseUrl"\'), h.includes("data-cloud-save")])(m.renderTopologyCloudAccountModal())',
     '["newKey",true,true,false,false,true]', "новая учётка с ключом: «Добавить: OpenAI API», поле ключа, Save; negative: ни удаления, ни адреса у большого провайдера"),
    ("window_new_custom_has_address_and_auth",
     'm.selectCloudProviderType("custom");',
     '(h => [h.includes(\'data-cloud-field="baseUrl"\'), h.includes(\'data-cloud-field="authMode"\')])(m.renderTopologyCloudAccountModal())',
     '[true,true]', "свой адрес: поле адреса и выбор «ключ / без ключа»"),
    ("window_connect_subscription",
     'm.selectCloudProviderType("openai-subscription");',
     '(h => [m.cloudAccountWindowState(st.ui.topologyCloudForm, null), h.includes(">" + fill(en.cloudConnectTitle, { name: en.cloudNameSubscription }) + "<"), h.includes(">" + en.cloudSignInChatgpt + "<"), h.includes(\'data-cloud-field="apiKey"\'), h.includes(\'data-cloud-field="baseUrl"\'), h.includes("data-cloud-save"), h.includes("localhost")])(m.renderTopologyCloudAccountModal())',
     '["connect",true,true,false,false,false,false]', "подписка до входа: «Подключить», одна кнопка входа через ChatGPT; negative: ни ключа, ни адреса, ни Save, ни localhost"),
    ("window_key_account_with_key",
     'm.openCloudAccountModal("ollama");',
     '(h => [m.cloudAccountWindowState(st.ui.topologyCloudForm, st.topology.cloudAccounts[1]), h.includes("<strong>Ollama cloud</strong>"), h.includes("✓ " + fill(en.cloudKeyShort, { last4: "ab12" })), h.includes("data-cloud-delete-account"), h.includes(\'data-cloud-field="apiKey"\'), h.includes(\'data-cloud-field="baseUrl"\'), h.includes("data-cloud-picker-change")])(m.renderTopologyCloudAccountModal())',
     '["keyAccount",true,true,true,true,true,false]', "учётка с ключом: имя в заголовке, «✓ Ключ ••••ab12», удаление, поле нового ключа, адрес у Ollama; negative: смены типа нет"),
    ("window_key_account_without_key",
     'm.openCloudAccountModal("bare");',
     '(h => [h.includes(\'data-t-state="no-key"\'), h.includes(">" + en.cloudNoKeyYet + "<")])(m.renderTopologyCloudAccountModal())',
     '[true,true]', "учётка без ключа: «Ключа пока нет», предупреждением"),
    ("window_subscription_signed_in",
     'm.openCloudAccountModal("openai-subscription");',
     '(h => [m.cloudAccountWindowState(st.ui.topologyCloudForm, st.topology.cloudAccounts[0]), h.includes("✓ " + en.cloudSignedIn), h.includes(">" + en.cloudSignInAgain + "<"), h.includes(\'data-cloud-field="apiKey"\'), h.includes("needs key"), h.includes("data-cloud-delete-account")])(m.renderTopologyCloudAccountModal())',
     '["subscription",true,true,false,false,true]', "подписка со входом: «✓ Вход выполнен», «Войти заново»; negative: ни поля ключа, ни «needs key»"),
    ("window_subscription_signed_out",
     'st.setTopology(TOPO({ cloudAccounts: ACCOUNTS().map((a) => a.id === "openai-subscription" ? { ...a, hasCredential: false } : a) })); m.openCloudAccountModal("openai-subscription");',
     '(h => [h.includes(\'data-t-state="signed-out"\'), h.includes(">" + en.cloudNotSignedIn + "<"), h.includes(">" + en.cloudSignInChatgpt + "<")])(m.renderTopologyCloudAccountModal())',
     '[true,true,true]', "подписка без входа: «Вход не выполнен» и кнопка входа — а не «needs key»"),
    ("window_says_its_pools", '',
     '(() => { const line = (id) => { m.openCloudAccountModal(id); const h = m.renderTopologyCloudAccountModal(); return (h.match(/data-t="cloud-account-pools">([^<]*)</) || [])[1] || null; };'
     ' return [line("ollama") === fill(en.cloudInPools, { pools: "Work, Night" }), line("openai-subscription") === fill(en.cloudInPools, { pools: "Work" }), line("bare") === en.cloudInNoPool]; })()',
     '[true,true,true]', "окно учётки называет пулы, где стоят её шаги, — каждый раз один (два шага в одном пуле — одно имя); negative: шагов нет — «пока ни в одном пуле»"),
    ("account_modal_closed_is_empty", '', 'm.renderTopologyCloudAccountModal()', '""', "negative: закрытый модал аккаунта — пустая строка"),
    # ── the providers on the main board (the owner, 2026-10-12) ──
    ("picker_marks_what_is_on_board",
     'st.setTopology(TOPO({ boardProviders: [{ kind: "openai-subscription", accounts: ["openai-subscription"] }] })); st.ui.topologyCloudPickerOpen = true;',
     '''(() => { const tile = (h, type) => { const at = h.indexOf(`data-pick-type="${type}"`); return h.slice(h.lastIndexOf("<button", at), h.indexOf("</button>", at)); };
       const board = m.renderTopologyCloudPicker(); const sub = tile(board, "openai-subscription"), key = tile(board, "openai");
       m.ACCOUNT_RETURN.wait(() => {}); const choosing = m.renderTopologyCloudPicker(); m.ACCOUNT_RETURN.after = null;
       return [sub.includes("on-board") && sub.includes(" disabled") && sub.includes(">" + esc(en.cloudPickerOnBoard) + "<"), key.includes("disabled"),
         key.includes(">" + esc(en.cloudDescOpenai) + "<"), board.includes(">" + esc(en.cloudPickerTitle) + "<"),
         choosing.includes("disabled"), choosing.includes(">" + esc(en.topologyCloudAccountModalTitleNew) + "<")]; })()''',
     '[true,false,true,true,false,true]',
     "с главной доски провайдер, который уже на доске, — бледная плитка, её не нажать: «уже на доске»; остальные говорят, что дают; "
     "заголовок — «добавить провайдера»; negative: окно, ждущее учётку (окно шага), ничего не отмечает и держит свой заголовок"),
    ("pick_puts_a_provider_on_the_board",
     '',
     '''await (async () => { st.ui.topologyCloudPickerOpen = true;
       globalThis.__fetchReply["/api/board-providers/add"] = { ok: true, providers: [], topology: TOPO({ boardProviders: [{ kind: "openai", accounts: [] }] }) };
       await m.pickCloudProvider("openai");
       const mine = () => calls().filter((c) => c.path.startsWith("/api/board-providers"));
       const made = [mine(), st.ui.topologyCloudPickerOpen, st.ui.topologyCloudModalOpen, (st.topology.boardProviders || []).map((p) => p.kind)];
       globalThis.__fetchCalls.length = 0; m.ACCOUNT_RETURN.wait(() => {}); m.pickCloudProvider("custom");
       const chose = [mine().length, st.ui.topologyCloudModalOpen, st.ui.topologyCloudForm?.type]; m.ACCOUNT_RETURN.after = null;
       return [made, chose]; })()''',
     '[[[{"path":"/api/board-providers/add","method":"POST","body":{"kind":"openai"}}],false,false,["openai"]],[0,true,"custom"]]',
     "плитка с главной доски ставит провайдера на доску — пустым блоком; окно выбора закрыто, доска нарисована по ответу; "
     "negative: окно, ждущее учётку, по-прежнему открывает окно новой учётки и ничего не ставит на доску"),
    ("remove_provider_and_its_refusal",
     '',
     '''await (async () => { globalThis.__fetchReply["/api/board-providers/remove"] = { ok: true, providers: [], topology: TOPO({ boardProviders: [] }) };
       const ok = await m.removeBoardProvider("anthropic"); const sent = calls().filter((c) => c.path.startsWith("/api/board-providers"));
       globalThis.__fetchReply["/api/board-providers/remove"] = { __status: 409, error: "openai-subscription: 1 account(s) stand under it — delete them first" };
       const refused = await m.removeBoardProvider("openai-subscription"); await settle();
       return [ok, sent, refused, toastText().includes("delete them first")]; })()''',
     '[true,[{"path":"/api/board-providers/remove","method":"POST","body":{"kind":"anthropic"}}],false,true]',
     "✕ пустого провайдера — один запрос; negative: провайдер с аккаунтами — отказ контроллера сказан тостом, и ничего не меняется"),
    ("connect_account_from_a_block",
     '',
     '''await (async () => { globalThis.__fetchReply["/api/cloud-accounts/save"] = { ok: true, topology: TOPO() };
       globalThis.__fetchReply["/api/cloud-accounts/oauth/device-start"] = { ok: true, userCode: "AB-CD", state: "s1", verifyUrl: "https://auth.openai.com/codex/device", expiresAt: 9999999999 };
       await m.connectAccount("openai-subscription"); await settle();
       const sub = [m.cloudAccountWindowState(st.ui.topologyCloudForm, null), calls().map((c) => c.path).slice(0, 2), st.ui.topologyCloudForm.name === en.cloudNameSubscription + " 2"];
       m.closeCloudProviderModal(); globalThis.__fetchCalls.length = 0;
       await m.connectAccount("openai"); const key = [m.cloudAccountWindowState(st.ui.topologyCloudForm, null), calls().length];
       return [sub, key]; })()''',
     '[["waiting",["/api/cloud-accounts/save","/api/cloud-accounts/oauth/device-start"],true],["newKey",0]]',
     "«＋ подписка» в блоке сразу ведёт к коду входа: учётка сохранена, код запрошен, окно ждёт код; имя — как у блока и плитки, "
     "«ChatGPT subscription 2» рядом с первой (до 1.3.494 — «OpenAI subscription 2»); "
     "«＋ ключ» открывает окно нового ключа; negative: для ключа ничего не сохранено и не запрошено до Save"),
    ("window_says_plan_and_provider_word",
     '',
     '''(() => { us.subscriptionUsageCache.set("openai-subscription", { data: { ok: true, limits: [], planType: "plus" }, fetchedAt: 1, loading: false });
       m.openCloudAccountModal("openai-subscription"); const sub = m.renderTopologyCloudAccountModal(); m.closeCloudProviderModal();
       us.subscriptionUsageCache.set("openai-subscription", { data: null, fetchedAt: Date.now(), loading: false, error: "x" });
       m.openCloudAccountModal("openai-subscription"); const unknown = m.renderTopologyCloudAccountModal(); m.closeCloudProviderModal();
       st.setTopology(TOPO({ cloudAccounts: [...ACCOUNTS(), { id: "or", type: "openrouter", name: "Router", baseUrl: "https://openrouter.ai/api/v1", authMode: "apiKey", hasCredential: true, keyLast4: "zz99", usedIn: [] }] }));
       m.openCloudAccountModal("or"); const key = m.renderTopologyCloudAccountModal(); m.closeCloudProviderModal();
       m.openCloudAccountModal("ollama"); const other = m.renderTopologyCloudAccountModal();
       return [sub.includes('data-t="cloud-account-plan">Plus</span>'), unknown.includes("cloud-account-plan"), key.includes('data-t="cloud-provider-word"'), other.includes("cloud-provider-word")]; })()''',
     '[true,false,true,false]',
     "окно подписки называет план, который назвало последнее чтение лимитов (Plus); окно ключа OpenRouter — слово провайдера "
     "(до 2026-10-12 оно было под ⋯ канбана); negative: план не прочитан — слова нет, а не догадка; у Ollama слова провайдера нет"),
    # ── the pools' lane ──
    # 2026-09-28: while a switch-level slider on a limit bar is being dragged, the lane is not
    # rebuilt under the pointer — the redraw waits for the release.
    ("lane_waits_for_switch_drag",
     'globalThis.__fields.topologyCloudProviders.innerHTML = "BEFORE"; us.switchDrag.active = true; us.switchDrag.deferred = false;',
     '(() => { m.renderTopologyCloudProviders(); const held = [lane(), us.switchDrag.deferred]; us.switchDrag.active = false; us.switchDrag.deferred = false; m.renderTopologyCloudProviders(); return [...held, lane() === "BEFORE"]; })()',
     '["BEFORE",true,false]', "ползунок уровня тянут — полосу не перерисовывают, перерисовка отложена; отпустили — рисуется"),
    # 2026-10-11: a step is carried by its grip (step-carry.js, the home start page's way); while it is
    # carried, lands or its new order is saved, the lane is not drawn over it.
    ("lane_waits_for_a_carried_step", '',
     'await (async () => { const l = liveLane(); m.renderTopologyCloudProviders(); l.innerHTML = "BEFORE"; st.ui._lastCloudProvidersKey = "";'
     ' const carry = m.POOL_CARDS.carry; carry.phase = "carrying"; m.renderTopologyCloudProviders(); const held = l.innerHTML;'
     ' carry.phase = "saving"; m.renderTopologyCloudProviders(); const saving = l.innerHTML;'
     ' carry.phase = "idle"; m.renderTopologyCloudProviders();'
     ' return [held, saving, l.innerHTML === "BEFORE", carry.root === l, ["dragstart", "dragover", "drop", "dragend"].some((type) => l.handlers[type]?.length)]; })()',
     '["BEFORE","BEFORE",false,true,false]', "шаг несут или сохраняют его новый порядок — полосу не перерисовывают; отпустили и сохранили — рисуется; перевозчик привязан к самой полосе, жестов перетаскивания браузера нет"),
    ("lane_one_card_per_pool", 'st.topology.proxies = [];',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [(h.match(/data-pool-card="/g) || []).length, (h.match(/data-topology-cloud-input="1" data-pool-id="(work|night)"/g) || []).length,'
     ' /data-server-card="cloud:work" style="order:\\d+"/.test(h), /<header class="pool-top">\\s*<span class="server-order">[^\\n]*data-t-id="cloud:work"[^\\n]*<\\/span><span class="cloud-account-icon pool-icon"/.test(h),'
     ' h.includes(`data-pool-field="name" data-t="pool-name" value="Work"`), h.includes("pool-port")]; })()',
     '[2,2,true,true,true,false]', "карточка на пул: своя ручка каната, своё место в списке Pools (ключ cloud:<id>), ↑ ↓ и значок пула в шапке, имя — заголовок; "
     "negative: своих портов у пула нет (владелец, 2026-10-12)"),
    ("lane_subscription_step_bars_carry_its_levels",
     'us.subscriptionUsageCache.set("openai-subscription", { data: { ok: true, limits: [{ label: "5H LIMIT", remainingPct: 80, windowSeconds: 18000 }, { label: "WEEKLY", remainingPct: 50, windowSeconds: 604800 }, { label: "RESERVE", remainingPct: 100 }] }, fetchedAt: Date.now(), loading: false });',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); const sub = stepOf(h, "work", "openai-subscription"), key = stepOf(h, "work", "ollama");'
     ' const sliders = [...headOf(sub).matchAll(/data-pool-switch="([^"]*)" data-step-id="([^"]*)" data-window-seconds="(\\d+)"/g)].map((x) => x.slice(1).join("/"));'
     ' const values = [...headOf(sub).matchAll(/class="sub-usage-switch (switch|stop)[^"]*" type="range" min="0" max="(\\d+)" step="1" value="(\\d+)"/g)].map((x) => `${x[1]}:${x[2]}:${x[3]}`);'
     ' return [sliders, values, key.includes("sub-usage-panel"), sub.includes("data-usage-refresh") ? "head" : "none"]; })()',
     '[["work/openai-subscription/18000","work/openai-subscription/18000","work/openai-subscription/604800","work/openai-subscription/604800"],["switch:90:30","stop:90:10","switch:90:20","stop:90:20"],false,"head"]',
     "полосы подписки — над сгибом ступени, с порогами ЭТОГО шага: на 5H переключение 30% и стоп 10%, на неделе оба 20%, потолок сервера 90; у окна без длины ручек нет; у шага с ключом полос нет; ↻ прочитанных лимитов — в голове ступени"),
    ("lane_step_reads_resets_and_its_model_spend", '',
     'await (async () => { liveLane(); st.setTopology(withSub("r1")); us.subscriptionUsageCache.set("r1", { data: { ok: true, limits: [{ label: "5H LIMIT", remainingPct: 80, windowSeconds: 18000 }] }, fetchedAt: Date.now(), loading: false });'
     ' globalThis.__fetchReply["/api/cloud-accounts/subscription-resets?id=r1"] = { availableCount: 3, credits: [], pending: [] };'
     ' await spendOf({ r1: { total: 809, requests: 8200, promptTokens: 6, completionTokens: 1, windowDays: 30, byModel: [{ model: "GPT-5.6-terra", cost: 700, requests: 8000 }, { model: "other", cost: 109, requests: 200 }] } });'
     ' const h = await drawn(); const sub = stepOf(h, "work", "r1"); const fold = sub.indexOf(`class="pool-step-more"`);'
     ' return [headOf(sub).includes("↺ " + fill(en.resetCount, { count: "3" })), headOf(sub).includes("≈ " + esc(fill(en.cloudModelSpend, { cost: "$700", days: "30" }))), headOf(sub).includes("$809"),'
     ' !sub.includes("subscription-resets") && !sub.includes("data-reset-use"), sub.indexOf("spend-line") > fold, sub.indexOf("$809") > fold]; })()',
     '[true,true,false,true,true,true]',
     "голова ступени — только числа: ↺ сбросов и доля ЕЁ модели в расходе (имя модели без учёта регистра, $700, а не $809 всей учётки); списка сбросов под сгибом нет — их выбирают в окне по ↺ (1.3.464); строка всей учётки — под сгибом"),
    ("lane_alias_step_takes_the_original_resets", '',
     'await (async () => { liveLane(); const alias = { ...SUB("r2"), id: "r2-test", name: "Plus test", testAliasOf: "r2" };'
     ' st.setTopology(TOPO({ cloudAccounts: [...ACCOUNTS(), SUB("r2"), alias], pools: [{ ...POOLS()[0], steps: [STEP("r2-test", "r2-test", "gpt-5.6-terra", { usageAccountId: "r2" })] }] }));'
     ' globalThis.__fetchReply["/api/cloud-accounts/subscription-resets?id=r2"] = { availableCount: 2, credits: [], pending: [] };'
     ' await spendOf({ "r2-test": { total: 120, requests: 90, windowDays: 30, byModel: [{ model: "gpt-5.6-terra", cost: 120, requests: 90 }] } });'
     ' const h = await drawn(); const head = headOf(stepOf(h, "work", "r2-test"));'
     ' return [head.includes("↺ " + fill(en.resetCount, { count: "2" })), head.includes("$120"), h.includes(`data-pool-edit-account="r2"`), h.includes(`data-pool-resets="r2"`), h.includes(`data-pool-edit-account="r2-test"`)]; })()',
     '[true,true,true,true,false]', "тестовый шаг берёт сбросы и ⚙ у исходной подписки, а расход — свой; negative: ⚙ на сам псевдоним не ведёт"),
    ("lane_uncertain_reset_warns_in_its_head", '',
     'await (async () => { liveLane(); st.setTopology(withSub("r3")); globalThis.__fetchReply["/api/cloud-accounts/subscription-resets?id=r3"] = { availableCount: 2, credits: [], pending: [{ creditId: "c1", idempotencyKey: "k1" }] };'
     ' const h = await drawn(); const sub = stepOf(h, "work", "r3"), key = stepOf(h, "work", "ollama");'
     ' return [headOf(sub).includes("pool-warn"), /class="pool-step[^"]* open" data-pool-step="r3"/.test(h), headOf(key).includes("pool-warn"), /class="pool-step[^"]* open" data-pool-step="ollama"/.test(h)]; })()',
     '[true,false,false,false]', "незавершённый сброс: голова ступени предупреждает ⚠, окно по ↺ предложит повтор; ступень не раскрывается — под сгибом сбросов больше нет; negative: у шага с ключом — ни того, ни другого"),
    ("lane_unread_resets_say_so", '',
     'await (async () => { liveLane(); st.setTopology(withSub("r5")); globalThis.__fetchReply["/api/cloud-accounts/subscription-resets?id=r5"] = { __status: 500, error: "boom" };'
     ' const h = await drawn(); const head = headOf(stepOf(h, "work", "r5"));'
     ' return [head.includes(`<span class="pool-resets none" title="${esc(en.resetUnavailable)}">↺ ?</span>`), head.includes("data-pool-resets=")]; })()',
     '[true,false]', "сбросы прочитать не удалось — в голове ступени «↺ ?» с причиной, а не пустота; кнопки выбора нет"),
    ("lane_drawn_alone_marks_the_ends_of_the_list", '',
     'await (async () => { const btn = () => ({ disabled: false }); const card = (key) => { const c = { dataset: { serverCard: key }, style: { order: "" }, up: btn(), down: btn() };'
     ' c.querySelector = (sel) => (sel === \'[data-server-step="up"]\' ? c.up : sel === \'[data-server-step="down"]\' ? c.down : null); return c; };'
     ' const cards = [card("node:a"), card("cloud:work")]; const keep = document.querySelectorAll;'
     ' document.querySelectorAll = (sel) => (sel === "[data-server-card]" ? cards : []);'
     ' try { m.renderTopologyCloudProviders(); return cards.map((c) => `${c.dataset.serverCard}:${c.up.disabled ? "-" : "↑"}${c.down.disabled ? "-" : "↓"}`); }'
     ' finally { document.querySelectorAll = keep; } })()',
     '["node:a:-↓","cloud:work:↑-"]',
     "облачная полоса, перерисованная сама по себе, заново отмечает концы всего списка: у первой карточки (машины) нет ↑, у последней (пула) нет ↓"),
    ("lane_step_refresh_sits_in_head",
     'us.subscriptionUsageCache.set("openai-subscription", { data: { ok: true, limits: [{ label: "5H LIMIT", remainingPct: 80, windowSeconds: 18000 }] }, fetchedAt: Date.now(), loading: false });',
     '(() => { m.renderTopologyCloudProviders(); const head = headOf(stepOf(lane(), "work", "openai-subscription")); const at = head.indexOf(`data-usage-refresh="openai-subscription"`); const panel = head.slice(head.indexOf(`class="sub-usage-panel"`));'
     ' return [(lane().match(/data-usage-refresh="openai-subscription"/g) || []).length, at > head.indexOf(`class="pool-step-tools"`) && at < head.indexOf("data-pool-fold"), panel.includes("data-usage-refresh"), panel.includes("sub-usage-head")]; })()',
     '[1,true,false,false]', "кнопка ↻ ступени — в её голове между числами и свёрткой, одна; в полосах её нет"),
    ("lane_counter_opens_window_of_choice", '',
     'await (async () => { const l = liveLane(); st.setTopology(withSub("r4")); const soon = new Date(Date.now() + 5 * 86400e3).toISOString(), late = new Date(Date.now() + 40 * 86400e3).toISOString();'
     ' globalThis.__fetchReply["/api/cloud-accounts/subscription-resets?id=r4"] = { availableCount: 4, credits: [{ id: "late", resetType: "codex_rate_limits", usable: true, expiresAt: late }, { id: "soon", resetType: "codex_rate_limits", usable: true, expiresAt: soon }, { id: "spent", resetType: "codex_rate_limits", usable: false, expiresAt: soon }], pending: [] };'
     ' const h = await drawn(); let asked = null; globalThis.__stubReturns["dialogs.appConfirmChoice"] = async (message, opts) => { asked = [message, opts]; return null; };'
     ' const chip = { dataset: { poolResets: "r4" }, disabled: false, matches: () => false, hasAttribute: (a) => a === "data-pool-resets", closest: (sel) => (sel.includes("data-pool-resets") ? chip : null) };'
     ' await l.handlers.click[0]({ type: "click", target: chip, stopPropagation() {} }); const posts = calls().filter((c) => c.method === "POST" && c.path.includes("subscription-reset"));'
     ' return [h.includes(`data-pool-resets="r4"`), asked && asked[1].choices.map((c) => c.value), !!asked && asked[0].includes("Plus r4"), posts.length]; })()',
     '[true,["soon","late"],true,0]', "счётчик сбросов в голове ступени — кнопка; открывает окно выбора: только то, что можно потратить, ближайший срок первым, и ничего не отправляет"),
    ("lane_key_account_usage_under_the_fold", '',
     'await (async () => { liveLane(); st.setTopology(TOPO({ cloudAccounts: [...ACCOUNTS(), { id: "or", type: "openrouter", name: "Router", hasCredential: true, usedIn: [] }, { id: "api", type: "openai", name: "API", baseUrl: "https://api.openai.com/v1", hasCredential: true, usedIn: [] }],'
     ' pools: [{ ...POOLS()[1], steps: [STEP("or", "or", "m1"), STEP("api", "api", "m2"), STEP("ollama", "ollama", "m3")] }] }));'
     ' await drawn(); const paths = calls().map((c) => c.path).filter((p) => p.includes("openrouter-limits") || p.includes("api-costs")).sort(); const h = lane();'
     ' const fold = (id) => { const s = stepOf(h, "night", id); return s.slice(s.indexOf(`class="pool-step-more"`)); };'
     ' return [paths, fold("or").includes("data-or-limits-refresh"), fold("api").includes("data-api-costs-refresh"), fold("ollama").includes("sub-usage-head")]; })()',
     '[["/api/cloud-accounts/api-costs?id=api","/api/cloud-accounts/openrouter-limits?id=or"],true,true,false]',
     "шаг учётки с ключом: под сгибом то, что говорит провайдер, — OpenRouter свои лимиты ключа, OpenAI API свой расход; negative: у остальных (Ollama) ничего не спрашивается"),
    ("lane_without_pools",
     'st.setTopology(TOPO({ pools: [] }));',
     '(() => { m.renderTopologyCloudProviders(); const h = lane(); return [h.includes(esc(en.poolNone)), h.includes("data-pool-new"), (h.match(/data-pool-card=/g) || []).length, (h.match(/data-t="pool-loose-account"/g) || []).length]; })()',
     '[true,true,0,3]', "пулов нет — сказано, что такое пул, и есть «＋ Новый пул»; подключённые учётки не пропадают с доски: они в полосе «вне пулов»"),
    ("lane_redraws_for_the_proxy_word_not_its_second", '',
     '(() => { const rt = (at, reason = "ready") => ({ available: true, pools: { work: { selectedStepId: "ollama", decidedAt: at, steps: [{ stepId: "ollama", reason }] } }, events: [] });'
     ' return [m.poolsRuntimeKey(rt(1000020)) === m.poolsRuntimeKey(rt(1000050)), m.poolsRuntimeKey(rt(1000020)) === m.poolsRuntimeKey(rt(1000080)), m.poolsRuntimeKey(rt(1000020)) === m.poolsRuntimeKey(rt(1000020, "quota")),'
     ' m.poolsRuntimeKey({ available: false, pools: { work: {} } }), m.poolsRuntimeKey(undefined)]; })()',
     '[true,false,false,"silent","silent"]', "полоса перерисовывается от слова прокси (другая причина, другая минута последнего выбора), но не от его секунды — иначе на каждом запросе пропадала бы подсказка под курсором; прокси молчит — одно состояние"),
    ("usage_refresh_once_per_click_after_renders",
     '',
     'await (async () => { const lane = { innerHTML: "", dataset: {}, handlers: [], addEventListener(type, fn) { if (type === "click") this.handlers.push(fn); }, querySelector: () => null };'
     ' globalThis.__fields.topologyCloudProviders = lane;'
     ' for (let i = 0; i < 3; i++) { st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); }'
     ' await settle(); globalThis.__fetchCalls.length = 0; let sp = 0;'
     ' const ev = (sel, data) => ({ stopPropagation: () => sp++, target: { closest: (s) => (s === sel ? { dataset: data } : null) } });'
     ' for (const [sel, data] of [["[data-usage-refresh]", { usageRefresh: "openai-subscription" }], ["[data-api-costs-refresh]", { apiCostsRefresh: "ollama" }],'
     '   ["[data-or-limits-refresh]", { orLimitsRefresh: "bare" }], ["nothing", {}]]) { for (const h of lane.handlers) await h(ev(sel, data)); }'
     ' await settle(); return [lane.handlers.length, sp, calls().map((c) => c.path)]; })()',
     '[1,3,["/api/cloud-accounts/subscription-usage?id=openai-subscription","/api/cloud-accounts/api-costs?id=ollama","/api/cloud-accounts/openrouter-limits?id=bare"]]',
     "defect-history: три перерисовки — один делегат на лейне, один ↻ после первых чтений — один запрос своего вида (было: делегат на каждой перерисовке, K запросов в chatgpt.com); щелчок мимо кнопок — ничего"),
    ("lane_memoised_by_key", '',
     'await (async () => { m.renderTopologyCloudProviders(); await settle(); m.renderTopologyCloudProviders(); globalThis.__fields.topologyCloudProviders.innerHTML = "WIPED"; m.renderTopologyCloudProviders(); const a = lane();'
     ' st.ui._lastCloudProvidersKey = ""; m.renderTopologyCloudProviders(); return [a, lane().includes("pool-card")]; })()',
     '["WIPED",true]', "тот же ключ — лейна не перерисовывается; сброс ключа — перерисовывается (первые чтения лимитов сами меняют ключ — они дочитаны до проверки)"),
    ("lane_no_element_is_noop",
     'delete globalThis.__fields.topologyCloudProviders;',
     '(() => { m.renderTopologyCloudProviders(); return st.ui._lastCloudProvidersKey.length > 0; })()',
     'true', "negative: элемента лейны нет — без исключения"),
    ("price_money_and_step_spend",
     'mm.modelPricing["x"] = { inputPer1M: 0, outputPer1M: 0 };',
     '(() => { const spend = (id, model) => m.cloudStepSpend(id, model).cost; us.proxySpendData && Object.keys(us.proxySpendData).forEach((k) => delete us.proxySpendData[k]);'
     ' return [m.cloudPrice("gpt-5.6-terra"), m.cloudPrice("a:free"), m.cloudPrice("x"), m.cloudPrice(""), m.cloudMoney(1234.5), m.cloudMoney(0.5), m.cloudMoney(0.004), m.cloudMoney(undefined), spend("nobody", "m")]; })()',
     '["$10 · $30","FREE","","","$1,235","$0.50","<$0.01","<$0.01",""]',
     "цена модели за 1M — вход · выход; :free — FREE; цена из нулей и неизвестная — пусто, а не «$0»; деньги — целыми от доллара, центами ниже, «<$0.01» вместо $0; расхода нет — пусто"),
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
    # ── saveCloudAccount ──
    ("save_account_rejects_bad_url",
     'm.selectCloudProviderType("custom"); st.ui.topologyCloudForm.name = "Local"; st.ui.topologyCloudForm.baseUrl = "10.0.0.9:8000";',
     'await (async () => { await m.saveCloudAccount(); return [calls().length, toastText(), m.topologyCloudBusy, st.ui.topologyCloudModalOpen]; })()',
     '[0,"base URL must be http(s)",false,true]', "negative: URL без схемы — ни одного запроса, модал остаётся открытым"),
    ("save_account_new_chain",
     'const back = []; m.openCloudPicker((id) => back.push(id)); globalThis.__back = back; m.selectCloudProviderType("openai"); st.ui.topologyCloudForm.name = "OpenAI (ChatGPT Plus)"; st.ui.topologyCloudForm.apiKey = " sk-x ";'
     ' globalThis.__fetchReply["/api/cloud-accounts/key"] = { ok: true };',
     'await (async () => { await m.saveCloudAccount(); const c = calls(); return [c.map((x) => x.path), c[0].body.account.id, c[0].body.account.baseUrl, c[0].body.account.authMode, c[1].body.apiKey, toastText() === en.cloudAccountSaved, st.ui.topologyCloudModalOpen, globalThis.__back]; })()',
     '[["/api/cloud-accounts/save","/api/cloud-accounts/key"],"openai-chatgpt-plus","https://api.openai.com/v1","apiKey","sk-x",true,false,["openai-chatgpt-plus"]]',
     "новая учётка: save → key (обрезан); id — слаг имени; baseUrl из пресета, когда поле пустое; учётка возвращается окну шага; negative: моделей сама не создаёт — модель выбирает шаг"),
    ("save_account_key_rejected_stops_chain",
     'm.selectCloudProviderType("openai"); st.ui.topologyCloudForm.name = "Fresh"; st.ui.topologyCloudForm.apiKey = "bad";'
     ' globalThis.__fetchReply["/api/cloud-accounts/key"] = { ok: false, test: { error: "401" } };'
     ' globalThis.__fetchReply["/api/cloud-accounts/save"] = { ok: true, topology: TOPO({ cloudAccounts: [...ACCOUNTS(), { id: "fresh", type: "openai", name: "Fresh", baseUrl: "https://api.openai.com/v1", authMode: "apiKey", usedIn: [] }] }) };',
     'await (async () => { await m.saveCloudAccount(); const first = [calls().map((x) => x.path), toastText(), m.topologyCloudBusy, st.ui.topologyCloudModalOpen, st.ui.topologyCloudForm.isNew, st.ui.topologyCloudForm.accountId];'
     ' globalThis.__fetchCalls.length = 0; await m.saveCloudAccount(); return [...first, calls().map((x) => x.path)]; })()',
     '[["/api/cloud-accounts/save","/api/cloud-accounts/key"],"key rejected: 401",false,true,false,"fresh",["/api/cloud-accounts/key"]]',
     "отказ ключа: окно открыто, busy снят, причина сказана; учётка уже сохранена — окно правит её, и второй Save шлёт только ключ (раньше делал вторую учётку)"),
    ("save_account_edit_without_key_sends_nothing",
     'm.openCloudAccountModal("ollama");',
     'await (async () => { await m.saveCloudAccount(); return [calls().length, toastText() === en.cloudAccountSaved, st.ui.topologyCloudModalOpen]; })()',
     '[0,true,false]', "правка без нового ключа: на провод ничего, модал закрыт"),
    ("save_account_edit_rename_saves",
     'm.openCloudAccountModal("ollama"); st.ui.topologyCloudForm.name = "Ollama (home)"; globalThis.__fetchReply["/api/cloud-accounts/save"] = { ok: true };',
     'await (async () => { await m.saveCloudAccount(); const c = calls(); return [c.map((x) => x.path), c[0].body.account, toastText() === en.cloudAccountSaved, st.ui.topologyCloudModalOpen]; })()',
     '[["/api/cloud-accounts/save"],{"id":"ollama","type":"ollama","name":"Ollama (home)","baseUrl":"https://ollama.com","authMode":"apiKey"},true,false]',
     "defect-history: правка имени уходит на сервер — раньше правка существующего аккаунта не отправляла ничего и всё равно говорила «saved»"),
    ("save_account_edit_rename_and_key",
     'm.openCloudAccountModal("ollama"); st.ui.topologyCloudForm.name = "Ollama (home)"; st.ui.topologyCloudForm.apiKey = "k3";'
     ' globalThis.__fetchReply["/api/cloud-accounts/save"] = { ok: true }; globalThis.__fetchReply["/api/cloud-accounts/key"] = { ok: true };',
     'await (async () => { await m.saveCloudAccount(); return calls().map((x) => x.path); })()',
     '["/api/cloud-accounts/save","/api/cloud-accounts/key"]', "имя и ключ вместе: сначала учётка, потом ключ"),
    ("save_account_edit_bad_url",
     'm.openCloudAccountModal("bare"); st.ui.topologyCloudForm.baseUrl = "10.0.0.9:9000";',
     'await (async () => { await m.saveCloudAccount(); return [calls().length, toastText(), m.topologyCloudBusy, st.ui.topologyCloudModalOpen]; })()',
     '[0,"base URL must be http(s)",false,true]', "negative: правка адреса без схемы — ни запроса, модал открыт"),
    ("save_account_edit_with_key_only_key",
     'm.openCloudAccountModal("ollama"); st.ui.topologyCloudForm.apiKey = "k2"; globalThis.__fetchReply["/api/cloud-accounts/key"] = { ok: true };',
     'await (async () => { await m.saveCloudAccount(); const c = calls(); return [c.map((x) => x.path), c[0].body]; })()',
     '[["/api/cloud-accounts/key"],{"id":"ollama","apiKey":"k2"}]', "правка с ключом: только /key, без save и автосоздания"),
    ("save_account_no_form_is_noop", '', 'await (async () => { await m.saveCloudAccount(); return calls().length; })()', '0', "negative: без формы — ничего"),
    ("delete_account_posts_and_closes",
     'm.openCloudAccountModal("bare");',
     'await (async () => { await m.deleteCloudAccount(); const c = calls(); return [c[0].path, c[0].body, st.ui.topologyCloudModalOpen]; })()',
     '["/api/cloud-accounts/delete",{"id":"bare"},false]', "удаление аккаунта: один POST, модал закрыт"),
    ("delete_account_without_form_is_noop", '', 'await (async () => { await m.deleteCloudAccount(); return calls().length; })()', '0', "negative: без формы — ничего"),
    # ── signing in: by a one-time code only (the return to localhost is gone) ──
    # A pin that starts a login settles before it returns: the first status
    # reply resolves a turn later and would land its timer in the next pin.
    ("device_start_saves_then_device_start_then_polls",
     'm.selectCloudProviderType("openai-subscription"); st.ui.topologyCloudForm.name = "Plus"; globalThis.__fetchReply["/api/cloud-accounts/oauth/device-start"] = { ok: true, state: "d1", userCode: "ABCD-12345", verifyUrl: "https://auth.openai.com/codex/device", expiresAt: 1800000600, interval: 5 };',
     'await (async () => { await m.startCloudOauthLogin(); await settle(); const c = calls(); const f = st.ui.topologyCloudForm; return [c.map((x) => x.path), c[0].body.account.authMode, c[0].body.account.oauthConfig.clientId, c[1].body, f.isNew, f.connecting, f.createdForSignIn, f.deviceLogin, [...globalThis.__opened]]; })()',
     '[["/api/cloud-accounts/save","/api/cloud-accounts/oauth/device-start","/api/cloud-accounts/oauth/status?state=d1"],"oauth","cid",{"id":"plus"},false,true,true,{"state":"d1","userCode":"ABCD-12345","verifyUrl":"https://auth.openai.com/codex/device","expiresAt":1800000600},[]]',
     "вход по коду: учётка сохранена сразу — код принадлежит учётке, — код получен, опрос пошёл; окно само ничего не открывает (это не клик); negative: ни в какой пул она сама не встаёт — пул называет её шагом"),
    ("device_start_without_code_stops",
     'm.openCloudAccountModal("openai-subscription"); globalThis.__fetchReply["/api/cloud-accounts/oauth/device-start"] = { ok: true };',
     'await (async () => { await m.startCloudOauthLogin(); return [calls().map((x) => x.path), toastText(), st.ui.topologyCloudForm.deviceLogin || null, polls().length]; })()',
     '[["/api/cloud-accounts/oauth/device-start"],"device sign-in failed",null,0]', "negative: ответ без кода — тост, опроса нет"),
    ("window_waiting_shows_code_and_one_way_on",
     'm.selectCloudProviderType("openai-subscription"); Object.assign(st.ui.topologyCloudForm, { isNew: false, connecting: true, accountId: "openai-subscription", deviceLogin: { state: "d1", userCode: "ABCD-12345", verifyUrl: "https://auth.openai.com/codex/device", expiresAt: 1800000600 } });',
     '(h => [m.cloudAccountWindowState(st.ui.topologyCloudForm, null), h.includes(">" + fill(en.cloudConnectTitle, { name: en.cloudNameSubscription }) + "<"), h.includes(`<code class="cloud-device-code" role="button" tabindex="0" title="${en.cloudCodeCopyTip}" data-cloud-device-code data-t="cloud-device-code">ABCD-12345</code>`), h.includes(`<a class="primary-mini-action cloud-open" href="https://auth.openai.com/codex/device" target="_blank" rel="noopener noreferrer" data-cloud-device-open`), h.includes(fill(en.cloudWaitingUntil, { time: "08:10 AM" })), h.includes(">" + en.cloudNewCode + "<"), h.includes("Device code authorization"), h.includes(en.cloudSignInChatgpt), h.includes("data-cloud-save")])(m.renderTopologyCloudAccountModal())',
     '["waiting",true,true,true,true,true,true,false,false]', "ждём код: заголовок «Подключить» не сменился на правку; код — кнопка «скопировать» с подсказкой, одна кнопка «скопировать и открыть», срок по часам, ссылка «новый код»; negative: ни второй кнопки входа, ни Save"),
    ("window_endings_say_why",
     'm.openCloudAccountModal("openai-subscription");',
     '(() => { const f = st.ui.topologyCloudForm; const say = (ended) => { f.loginEnded = ended; const h = m.renderTopologyCloudAccountModal(); return [m.cloudAccountWindowState(f, null), h.includes(\'data-t-state="\' + (ended.reason || "failed") + \'"\'), h.includes("data-cloud-oauth-login")]; }; return [say({ reason: "replaced" }), say({ reason: "expired" }), say({ reason: "unknown" }), say({ reason: "removed" }), say({ reason: "", error: "OpenAI refused the sign-in (HTTP 400 x)" }), m.renderTopologyCloudAccountModal().includes(fill(en.cloudSignInFailed, { error: "OpenAI refused the sign-in (HTTP 400 x)" }))]; })()',
     '[["ended",true,true],["ended",true,true],["ended",true,true],["ended",true,false],["ended",true,true],true]', "вход кончился без входа — сказано почему; новый код, где старый просто пропал; negative: учётку удалили — кнопки нет"),
    ("window_connected_then_done",
     'm.openCloudAccountModal("openai-subscription"); Object.assign(st.ui.topologyCloudForm, { connecting: true, connected: { email: "me@x" } });',
     '(() => { const words = () => { const h = m.renderTopologyCloudAccountModal(); return [h.includes(fill(en.cloudConnectedAs, { email: "me@x" })), h.includes(en.cloudConnectedNext), h.includes(en.cloudConnectedAddStep)]; };'
     ' const alone = words(); m.ACCOUNT_RETURN.wait(() => {}); const fromStep = words(); const h = m.renderTopologyCloudAccountModal();'
     ' return [m.cloudAccountWindowState(st.ui.topologyCloudForm, null), alone, fromStep, h.includes("data-cloud-done"), h.includes("data-cloud-cancel"), h.includes("data-cloud-save")]; })()',
     '["connected",[true,false,true],[true,true,false],true,false,false]',
     "вошли: «Подключено: почта» и что дальше — из окна шага «выберите модель для шага», а без него «добавьте её шагом в пул»; одна кнопка «Готово»; negative: ни Cancel, ни Save"),
    ("delete_words_say_what_the_delete_does",
     '',
     '(() => { const a = { id: "a", name: "Plus", signOutOnDelete: true, usedIn: [{ poolId: "w", poolName: "Work" }, { poolId: "w", poolName: "Work" }, { poolId: "n", poolName: "Night" }] };'
     ' return [m.cloudDeleteWords(a) === fill(en.accountDeleteSteps, { name: "Plus", pools: "Work, Night", count: "3" }) + " " + en.cloudDeleteSignsOut,'
     ' m.cloudDeleteWords({ ...a, signOutOnDelete: false }) === fill(en.accountDeleteSteps, { name: "Plus", pools: "Work, Night", count: "3" }),'
     ' m.cloudDeleteWords({ id: "k", name: "Ollama", usedIn: [] }) === fill(en.accountDeleteText, { name: "Ollama" }),'
     ' m.cloudDeleteWords({ id: "k" }) === fill(en.accountDeleteText, { name: "k" })]; })()',
     '[true,true,true,true]', "слова удаления: шаги учётки уходят из её пулов (пул назван один раз, шагов — сколько есть), пулы остаются; выход у OpenAI — только где его обещает сервер; negative: шагов нет — просто «удалить?»; без имени — по id"),
    ("device_poll_done_connects",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.deviceLogin = { state: "d1", userCode: "X" }; globalThis.__fetchReply["/api/cloud-accounts/oauth/status?state=d1"] = { state: "done", email: "me@x", topology: TOPO({ cloudAccounts: [] }) };',
     'await (async () => { m.pollCloudOauth("d1"); await settle(); const f = st.ui.topologyCloudForm; return [f.deviceLogin, f.connected, st.topology.cloudAccounts.length, polls().length, toastText()]; })()',
     '[null,{"email":"me@x"},0,0,""]', "вход состоялся: код убран, окно «подключено», доска применена, опрос кончился; тоста нет — говорит окно"),
    ("device_poll_pending_reschedules_2s",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.deviceLogin = { state: "d1", userCode: "X" }; globalThis.__fetchReply["/api/cloud-accounts/oauth/status?state=d1"] = { state: "pending" };',
     'await (async () => { m.pollCloudOauth("d1"); await settle(); return polls(); })()',
     '["poll:2000"]', "ждём: следующий опрос через 2 с"),
    ("device_poll_replaced_ends_with_reason",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.deviceLogin = { state: "d1", userCode: "X" }; globalThis.__fetchReply["/api/cloud-accounts/oauth/status?state=d1"] = { state: "error", reason: "replaced", error: "a newer sign-in replaced this code" };',
     'await (async () => { m.pollCloudOauth("d1"); await settle(); const f = st.ui.topologyCloudForm; return [f.deviceLogin, f.loginEnded, polls().length]; })()',
     '[null,{"reason":"replaced","error":"a newer sign-in replaced this code"},0]', "код заменён в другом окне — окно знает это и не ждёт 15 минут (2026-10-07)"),
    ("device_poll_unknown_current_ends",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.deviceLogin = { state: "d1", userCode: "X" }; globalThis.__fetchReply["/api/cloud-accounts/oauth/status?state=d1"] = { state: "unknown" };',
     'await (async () => { m.pollCloudOauth("d1"); await settle(); return [st.ui.topologyCloudForm.loginEnded, st.ui.topologyCloudForm.deviceLogin, polls().length]; })()',
     '[{"reason":"unknown","error":""},null,0]', "контроллер забыл текущий код (перезапуск) — конец с причиной, а не 15 минут опроса"),
    ("device_poll_stale_stops_quietly",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.deviceLogin = { state: "d2", userCode: "X" }; globalThis.__fetchReply["/api/cloud-accounts/oauth/status?state=d1"] = { state: "error", reason: "replaced" };',
     'await (async () => { m.pollCloudOauth("d1"); await settle(); return [st.ui.topologyCloudForm.loginEnded || null, st.ui.topologyCloudForm.deviceLogin.state, calls().length, polls().length]; })()',
     '[null,"d2",0,0]', "negative: опрос старого кода в этом окне молча кончается — новый код не тронут, запроса нет"),
    ("device_poll_closed_modal_does_nothing", '',
     '(() => { m.pollCloudOauth("d1"); return calls().length; })()', '0', "negative: окно закрыто — опроса нет"),
    ("device_poll_long_limit",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.deviceLogin = { state: "d1", userCode: "X" }; globalThis.__fetchReply["/api/cloud-accounts/oauth/status?state=d1"] = { state: "pending" };',
     # The timers are run by hand here: the limit must travel with every repeat, not only the first call.
     'await (async () => { const keep = globalThis.setTimeout; const due = []; globalThis.setTimeout = (fn) => { due.push(fn); return 0; }; try { m.pollCloudOauth("d1", 459); await settle(); due.shift()(); await settle(); const asked = calls().length; due.shift()(); await settle(); return [m.DEVICE_LOGIN_POLLS, asked, calls().length, st.ui.topologyCloudForm.loginEnded, st.ui.topologyCloudForm.deviceLogin]; } finally { globalThis.setTimeout = keep; } })()',
     '[460,2,2,{"reason":"expired"},null]', "boundary: код живёт 15 минут — 459-я и 460-я попытки спрашивают, 461-я — «код истёк» без запроса"),
    ("cancel_takes_back_a_half_made_account",
     'st.setTopology(TOPO({ cloudAccounts: ACCOUNTS().map((a) => a.id === "openai-subscription" ? { ...a, hasCredential: false } : a) })); m.openCloudAccountModal("openai-subscription"); Object.assign(st.ui.topologyCloudForm, { connecting: true, createdForSignIn: true, deviceLogin: { state: "d1", userCode: "X" } });',
     'await (async () => { await m.cancelCloudAccountWindow(); const c = calls(); return [c.map((x) => x.path), c[0] && c[0].body, st.ui.topologyCloudModalOpen]; })()',
     '[["/api/cloud-accounts/delete"],{"id":"openai-subscription"},false]', "Cancel посреди первого входа забирает назад учётку, сделанную для него — без входа она висела бы на доске"),
    ("cancel_keeps_a_signed_in_or_older_account",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.createdForSignIn = true;',
     'await (async () => { await m.cancelCloudAccountWindow(); const signedIn = calls().length; m.openCloudAccountModal("bare"); await m.cancelCloudAccountWindow(); return [signedIn, calls().length, st.ui.topologyCloudModalOpen]; })()',
     '[0,0,false]', "negative: учётка уже вошла — не удаляется; учётку открыли, а не сделали в этом окне — тоже; окно закрыто"),
    ("cancel_tells_the_step_window_nothing_came", '',
     'await (async () => { const back = []; m.openCloudPicker((id) => back.push(id)); m.selectCloudProviderType("openai-subscription"); await m.cancelCloudAccountWindow(); return back; })()',
     '[null]', "Cancel в окне учётки возвращает окну шага «ничего»: оно встаёт на место таким, каким было"),
    ("delete_says_how_the_sign_out_went",
     'm.openCloudAccountModal("openai-subscription");',
     'await (async () => { const said = []; for (const signOut of [{ ok: true, error: "" }, { ok: false, error: "HTTP 400 invalid_request" }, undefined]) { m.openCloudAccountModal("openai-subscription"); globalThis.__fields.toast.textContent = ""; globalThis.__fetchReply["/api/cloud-accounts/delete"] = { ok: true, ...(signOut ? { signOut } : {}) }; await m.deleteCloudAccount(); said.push(toastText()); } return [said[0] === en.cloudSignedOut, said[1] === fill(en.cloudSignOutFailed, { error: "HTTP 400 invalid_request" }), said[2], st.ui.topologyCloudModalOpen]; })()',
     '[true,true,"",false]', "удаление говорит, чем кончился выход у OpenAI: завершён / не подтверждён с причиной; negative: учётка без своего входа — молча, как раньше"),
    ("device_copy_code",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.deviceLogin = { state: "d1", userCode: "ABCD-12345" }; globalThis.__copied = []; Object.defineProperty(globalThis.navigator, "clipboard", { value: { writeText: async (s) => { globalThis.__copied.push(s); } }, configurable: true });',
     'await (async () => { const ok = await m.copyCloudDeviceCode(); st.ui.topologyCloudForm.deviceLogin = null; globalThis.__fields.toast.textContent = ""; const none = await m.copyCloudDeviceCode(); return [ok, [...globalThis.__copied], none, toastText()]; })()',
     '[true,["ABCD-12345"],false,""]', "код копируется в буфер; negative: нет кода — нечего копировать, тоста нет"),
    ("device_copy_says_how_it_went",
     'm.openCloudAccountModal("openai-subscription"); st.ui.topologyCloudForm.deviceLogin = { state: "d1", userCode: "ABCD-12345" };',
     'await (async () => { const doc = { createElement: document.createElement, body: document.body, execCommand: document.execCommand }; const said = []; const results = []; '
     'document.createElement = () => ({ style: {}, select() {}, remove() {} }); document.body = { appendChild() {} }; '
     'for (const [writeText, legacy] of [[async () => {}, false], [async () => { throw new Error("denied"); }, false], [async () => { throw new Error("denied"); }, true]]) { '
     'Object.defineProperty(globalThis.navigator, "clipboard", { value: { writeText }, configurable: true }); document.execCommand = () => legacy; '
     'globalThis.__fields.toast.textContent = ""; results.push(await m.copyCloudDeviceCode()); said.push(toastText()); } '
     'Object.assign(document, doc); return [results, said[0] === en.deviceLoginCopied, said[1] === en.cloudCodeNotCopied, said[2] === en.deviceLoginCopied]; })()',
     '[[true,false,true],true,true,true]', "тост говорит, чем кончилось копирование: скопирован; буфер отказал — «код не скопирован, выделите и нажмите Ctrl+C» (раньше молчал, и оператор вставлял старое содержимое буфера); запасной путь для http скопировал — «скопирован»"),
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
    print("облако: полоса пулов, учётки шагов и пути записи:")
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
