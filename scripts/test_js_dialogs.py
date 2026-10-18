#!/usr/bin/env python3
"""Snapshot of static/js/dialogs.js — appConfirm/appPrompt as promises over one modal.

Every dangerous action on the board goes through `appConfirm` (14 modules
import it), and this primitive had not had a single test. What's pinned by
VALUE is the contract every caller relies on: a promise settles only through
`settleAppConfirm`, confirming gives true/false, input gives a string or null
on cancel; settling again with no pending dialog gives false, not an
exception; once settled the modal is hidden and `ui.pendingConfirm` is
cleared. The styling that protects the operator: a "danger" tone by default,
and "ask" for input or `danger:false`; a passphrase input field is
type=password and autocomplete=off (a password manager must not offer to
save it); the button's default caption is the translated "OK", not an empty
string.

The DOM is the `globalThis.__fields` dict (see scripts/_js_globals.mjs): the
modal's elements are described by exactly the fields this module touches.

Run: python3 scripts/test_js_dialogs.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("canvas,polling,topology-dnd,topology-render,topology-modals,topology-nodes,charts,cables,cloud,history,"
         "favorites,config-locator,system-panels,onboarding,usage-stats,dialog-llamas,models-page,system-page,"
         "onboarding-tours,memory,command-preview,llama-edit,remote-cells,routers,topology-activity,topology-proxies,"
         "model-meta,form")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
const m = await import(pathToFileURL(process.env.JS_ROOT + "/dialogs.js").href);
const cls = () => { const s = new Set(); return { add: (c) => s.add(c), remove: (c) => s.delete(c), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), has: (c) => s.has(c) }; };
const focusLog = [];
const node = (name) => ({ name, textContent: "", hidden: false, value: "", type: "text", autocomplete: "", placeholder: "", onkeydown: null, innerHTML: "", dataset: {}, classList: cls(), focus() { focusLog.push(name); }, select() {} });
// The meta box of a prompt with choices: its buttons are read back from the
// markup the module wrote, once per markup, so a click handler set on one
// stays on it.
const metaNode = () => {
  const n = node("meta");
  let cache = { html: null, list: [] };
  // The boxes of a dialog with checks, read back the same way: the "all" box and the rest,
  // each with its checked and disabled state, so a handler set on one stays on it.
  let boxes = { html: null, all: null, list: [] };
  const readBoxes = () => {
    if (boxes.html !== n.innerHTML) {
      const found = [...n.innerHTML.matchAll(/<input type="checkbox" data-check(-all)?(?:="([^"]*)")? data-t="[^"]*"(?: data-t-id="[^"]*")?( checked)?( disabled)?><span>([^<]*)<\/span>/g)]
        .map((x) => ({ all: !!x[1], dataset: { check: x[2] }, checked: !!x[3], disabled: !!x[4], label: x[5], onchange: null }));
      boxes = { html: n.innerHTML, all: found.find((b) => b.all) || null, list: found.filter((b) => !b.all) };
    }
    return boxes;
  };
  n.querySelector = (sel) => (sel === "[data-check-all]" ? readBoxes().all : null);
  n.querySelectorAll = (sel) => {
    if (sel === "[data-check]") return readBoxes().list;
    if (cache.html !== n.innerHTML) {
      cache = { html: n.innerHTML, list: [...n.innerHTML.matchAll(/data-choice="([^"]*)"\s*aria-checked="(true|false)">([^<]*)</g)]
        .map((x) => ({ dataset: { choice: x[1] }, label: x[3], attrs: { "aria-checked": x[2] }, onclick: null,
          setAttribute(k, v) { this.attrs[k] = v; } })) };
    }
    return cache.list;
  };
  return n;
};
// The boxes as the operator sees them now: [value or "all", checked, disabled, label].
const ticks = () => { const meta = F().confirmMeta; const all = meta.querySelector("[data-check-all]");
  return [...(all ? [["all", all.checked, all.disabled, all.label]] : []), ...meta.querySelectorAll("[data-check]").map((b) => [b.dataset.check, b.checked, b.disabled, b.label])]; };
const POOLS = { choiceLabel: "Pools", allLabel: "All pools, new ones too", emptyLabel: "No pools yet",
  choices: [{ value: "std", label: "Standart" }, { value: "eco", label: "Econom" }, { value: "big", label: "Big Brain" }] };
const chips = () => F().confirmMeta.querySelectorAll().map((b) => [b.dataset.choice, b.attrs["aria-checked"], b.label]);
const HOLDS = { choiceLabel: "Unload when unused for", choice: "-1",
  choices: [{ value: "900", label: "15 min" }, { value: "3600", label: "1 h" }, { value: "-1", label: "until I unload it" }] };
const build = () => {
  const modal = { dataset: {} };
  globalThis.__fields = {
    confirmOverlay: { hidden: true, dataset: {}, querySelector: (sel) => (sel === ".modal" ? modal : null) },
    confirmTitle: node("title"), confirmText: node("text"), confirmMeta: metaNode(), confirmPath: node("path"),
    confirmInput: node("input"), confirmInputHint: node("hint"), confirmDelete: node("ok"), confirmCancel: node("cancel"),
  };
  return modal;
};
const F = () => globalThis.__fields;
const modalOf = () => F().confirmOverlay.querySelector(".modal");
// Фокус модуль ставит через requestAnimationFrame; планировщик — дело харнесса,
// здесь кадр наступает сразу, и лог фокуса читается синхронно.
globalThis.requestAnimationFrame = (fn) => { fn(); return 0; };
const reset = () => { build(); focusLog.length = 0; st.ui.pendingConfirm = null; m.settleAppConfirm(false); build(); focusLog.length = 0; };
reset();
const out = {};
"""

PINS = [
    ("confirm_resolves_true_on_ok", '',
     'await (async () => { const p = m.appConfirm("Delete it?"); const pending = typeof st.ui.pendingConfirm === "function"; const shown = F().confirmOverlay.hidden === false; const settled = m.settleAppConfirm(true); return [await p, pending, shown, settled, F().confirmOverlay.hidden, st.ui.pendingConfirm === null]; })()',
     '[true,true,true,true,true,true]',
     "подтверждение: промис даёт true; пока ждёт — модал показан и pendingConfirm поставлен; после — скрыт и снят"),
    ("confirm_resolves_false_on_cancel", '',
     'await (async () => { const p = m.appConfirm("Delete it?"); m.settleAppConfirm(false); return await p; })()',
     'false', "negative: отмена даёт false, а не null и не «висящий» промис"),
    ("confirm_default_tone_is_danger_and_focus_on_cancel", '',
     '(() => { m.appConfirm("Stop the cell?"); return [modalOf().dataset.tone, F().confirmDelete.classList.has("danger"), [...focusLog], F().confirmTitle.textContent, F().confirmText.textContent]; })()',
     '["danger",true,["cancel"],"Confirm the action","Stop the cell?"]',
     "опасный тон по умолчанию: красная кнопка, фокус на «Отмена», заголовок переведён, текст — сообщение"),
    ("confirm_ask_tone_focuses_ok", '',
     '(() => { m.appConfirm("Adopt?", { danger: false, confirmLabel: "Adopt" }); return [modalOf().dataset.tone, F().confirmDelete.classList.has("danger"), [...focusLog], F().confirmDelete.textContent]; })()',
     '["ask",false,["ok"],"Adopt"]',
     "danger:false — тон «ask», кнопка не красная, фокус на подтверждении, своя подпись"),
    ("confirm_default_label_is_translated_ok", '',
     '(() => { m.appConfirm("x"); return F().confirmDelete.textContent; })()',
     '"OK"', "подпись кнопки без confirmLabel — переведённое OK, не пустая строка (так и терялся перевод)"),
    ("confirm_detail_and_scene", '',
     '(() => { m.appConfirm("x", { detail: "/var/x.json", scene: "delete" }); const a = [F().confirmPath.textContent, F().confirmOverlay.dataset.dlgScene]; m.settleAppConfirm(false); m.appConfirm("y"); return [...a, "dlgScene" in F().confirmOverlay.dataset]; })()',
     '["/var/x.json","delete",false]', "detail попадает в путь; сцена ламы ставится и снимается на следующем открытии"),
    ("prompt_resolves_entered_text", '',
     'await (async () => { const p = m.appPrompt("Name the agent", { value: "old" }); const before = [F().confirmInput.hidden, F().confirmInput.value, F().confirmTitle.textContent, modalOf().dataset.tone]; F().confirmInput.value = "hotel"; m.settleAppConfirm(true); return [await p, ...before, F().confirmInput.hidden]; })()',
     '["hotel",false,"old","Name the agent","ask",true]',
     "ввод: промис даёт введённую строку; поле показано с префиллом, сообщение — заголовок, тон «ask»; после — поле скрыто"),
    ("prompt_cancel_is_null", '',
     'await (async () => { const p = m.appPrompt("Name"); F().confirmInput.value = "typed"; m.settleAppConfirm(false); return await p; })()',
     'null', "negative: отмена ввода — null, даже если что-то напечатано"),
    ("prompt_password_hides_and_blocks_autofill", '',
     '(() => { m.appPrompt("Passphrase", { password: true }); const a = [F().confirmInput.type, F().confirmInput.autocomplete]; m.settleAppConfirm(false); m.appPrompt("Plain"); return [...a, F().confirmInput.type, F().confirmInput.autocomplete]; })()',
     '["password","off","text",""]', "парольная фраза: type=password и autocomplete=off; обычный ввод — text без запрета"),
    ("prompt_enter_submits", '',
     'await (async () => { const p = m.appPrompt("Name"); F().confirmInput.value = "v"; let prevented = false; F().confirmInput.onkeydown({ key: "Enter", preventDefault: () => { prevented = true; } }); return [await p, prevented]; })()',
     '["v",true]', "Enter в поле ввода = подтверждение, и событие погашено"),
    ("prompt_other_key_does_nothing", '',
     '(() => { m.appPrompt("Name"); F().confirmInput.onkeydown({ key: "a", preventDefault: () => {} }); return F().confirmOverlay.hidden; })()',
     'false', "negative: обычная клавиша диалог не закрывает"),
    ("prompt_focuses_input", '',
     '(() => { m.appPrompt("Name"); return [...focusLog]; })()',
     '["input"]', "фокус при вводе — в поле"),
    ("settle_without_pending_is_false", '',
     '(() => { F().confirmOverlay.hidden = false; const r = m.settleAppConfirm(true); return [r, F().confirmOverlay.hidden, modalOf().dataset.tone]; })()',
     '[false,true,"danger"]', "negative: оседание без ожидающего диалога — false, но модал всё равно прибран и тон возвращён легаси-открывалкам"),
    ("settle_twice_second_is_false", '',
     'await (async () => { const p = m.appConfirm("x"); const a = m.settleAppConfirm(true); const b = m.settleAppConfirm(true); return [a, b, await p]; })()',
     '[true,false,true]', "boundary: второе оседание того же диалога — false, промис не переоседает"),
    ("pending_confirm_hook_settles_true", '',
     'await (async () => { const p = m.appConfirm("x"); st.ui.pendingConfirm(); return await p; })()',
     'true', "ui.pendingConfirm (клавиша Enter на оверлее) подтверждает"),
    ("meta_cleared_on_open", '',
     '(() => { F().confirmMeta.hidden = false; F().confirmMeta.innerHTML = "<b>old</b>"; m.appConfirm("x"); return [F().confirmMeta.hidden, F().confirmMeta.innerHTML]; })()',
     '[true,""]', "мета-блок легаси-открывалок очищается при каждом открытии"),
    ("prompt_tab_takes_the_suggestion",
     '',
     'await (async () => { const p = m.appPrompt("Name", { placeholder: "hotel port" }); const shown = !F().confirmInputHint.hidden; let prevented = false; F().confirmInput.onkeydown({ key: "Tab", shiftKey: false, preventDefault: () => { prevented = true; } }); const after = [F().confirmInput.value, prevented, F().confirmInputHint.hidden, F().confirmOverlay.hidden]; m.settleAppConfirm(true); return [shown, after, await p]; })()',
     '[true,["hotel port",true,true,false],"hotel port"]',
     "positive: Tab в пустом поле подставляет подсказку из плейсхолдера, диалог остаётся открыт, клавиша-подсказка прячется; OK возвращает подставленное"),
    ("prompt_tab_moves_on_when_the_box_holds_it_or_something_else",
     '',
     '(() => { m.appPrompt("Name", { placeholder: "hotel port" }); const tab = () => { let prevented = false; F().confirmInput.onkeydown({ key: "Tab", shiftKey: false, preventDefault: () => { prevented = true; } }); return prevented; }; F().confirmInput.value = "hotel port"; const held = tab(); F().confirmInput.value = "other"; F().confirmInput.oninput(); const other = [tab(), F().confirmInput.value, F().confirmInputHint.hidden]; F().confirmInput.value = "hot"; F().confirmInput.oninput(); const prefix = [F().confirmInputHint.hidden, tab(), F().confirmInput.value]; m.settleAppConfirm(false); return [held, other, prefix]; })()',
     '[false,[false,"other",true],[false,true,"hotel port"]]',
     "boundary: поле уже держит подсказку или чужой текст — Tab идёт дальше по фокусу, ничего не меняя, клавиша скрыта; набранный префикс подсказки — клавиша видна и Tab дописывает её"),
    ("prompt_shift_tab_and_no_placeholder_pass_through",
     '',
     '(() => { m.appPrompt("Name", { placeholder: "hotel port" }); let a = false; F().confirmInput.onkeydown({ key: "Tab", shiftKey: true, preventDefault: () => { a = true; } }); const v1 = F().confirmInput.value; m.settleAppConfirm(false); m.appPrompt("Name"); const hidden = F().confirmInputHint.hidden; let b = false; F().confirmInput.onkeydown({ key: "Tab", shiftKey: false, preventDefault: () => { b = true; } }); const v2 = F().confirmInput.value; m.settleAppConfirm(false); return [a, v1, hidden, b, v2]; })()',
     '[false,"",true,false,""]',
     "negative: Shift+Tab — обычная навигация назад, поле не трогается; без плейсхолдера подсказки нет: клавиша скрыта, Tab не перехватывается"),
    ("confirm_mode_hides_the_tab_hint",
     '',
     '(() => { m.appPrompt("Name", { placeholder: "x" }); const shown = !F().confirmInputHint.hidden; m.settleAppConfirm(false); const afterSettle = F().confirmInputHint.hidden; m.appConfirm("Sure?"); const inConfirm = F().confirmInputHint.hidden; m.settleAppConfirm(false); return [shown, afterSettle, inConfirm]; })()',
     '[true,true,true]',
     "negative: клавиша видна только в открытом prompt: после закрытия и у обычного confirm она скрыта"),
    ("checks_show_boxes_and_ticks",
     '',
     '(() => { m.appConfirmChecks("Pools Hermes may call", { ...POOLS, danger: false, checked: ["eco"] }); return [F().confirmMeta.hidden, ticks(), /data-t="confirm-check-all"/.test(F().confirmMeta.innerHTML), /dlg-choices-label">Pools</.test(F().confirmMeta.innerHTML), F().confirmInput.hidden, modalOf().dataset.tone]; })()',
     '[false,[["all",false,false,"All pools, new ones too"],["std",false,false,"Standart"],["eco",true,false,"Econom"],["big",false,false,"Big Brain"]],true,true,true,"ask"]',
     "флажки: «все» первым, потом пулы; отмечено заданное; подпись над ними; поля ввода нет"),
    ("checks_settle_in_the_dialogs_order",
     '',
     'await (async () => { const p = m.appConfirmChecks("W", { ...POOLS, checked: ["eco"] }); const [std, eco, big] = F().confirmMeta.querySelectorAll("[data-check]"); big.checked = true; big.onchange(); std.checked = true; std.onchange(); eco.checked = false; eco.onchange(); m.settleAppConfirm(true); const a = await p; const q = m.appConfirmChecks("W", { ...POOLS, checked: ["eco"] }); m.settleAppConfirm(false); return [a, await q, F().confirmMeta.hidden, F().confirmMeta.innerHTML]; })()',
     '[["std","big"],null,true,""]',
     "отмеченное уходит в порядке окна, а не в порядке щелчков; negative: отмена — null, окно чистое"),
    ("checks_all_box_stands_for_every_pool",
     '',
     'await (async () => { const p = m.appConfirmChecks("W", { ...POOLS, checked: "all" }); const before = ticks(); m.settleAppConfirm(true); const all = await p; const q = m.appConfirmChecks("W", { ...POOLS, checked: "all" }); const box = F().confirmMeta.querySelector("[data-check-all]"); box.checked = false; box.onchange(); const after = ticks(); m.settleAppConfirm(true); return [before, all, after, await q]; })()',
     '[[["all",true,false,"All pools, new ones too"],["std",true,true,"Standart"],["eco",true,true,"Econom"],["big",true,true,"Big Brain"]],"all",[["all",false,false,"All pools, new ones too"],["std",false,false,"Standart"],["eco",false,false,"Econom"],["big",false,false,"Big Brain"]],[]]',
     "«все» отмечено — пулы отмечены и серые, ответ «all»; снятое «все» возвращает свой выбор (пусто) и пустой ответ, а не «all»"),
    ("checks_without_choices_or_all_box",
     '',
     'await (async () => { const p = m.appConfirmChecks("W", { emptyLabel: "No pools yet", choices: [] }); const html = F().confirmMeta.innerHTML; m.settleAppConfirm(true); const a = await p; const q = m.appConfirmChecks("W", { choices: POOLS.choices, checked: "all" }); const t = ticks(); m.settleAppConfirm(true); const r = m.appConfirm("Sure?"); m.settleAppConfirm(true); return [html.includes(\'dlg-checks-empty">No pools yet<\'), a, t.map((x) => x[1]), await q, await r]; })()',
     '[true,[],[false,false,false],[],true]',
     "negative: пустой список — сказано, что он значит, ответ — пустой; «all» без коробки «все» — не «all»: ничего не отмечено; следующий confirm снова отвечает true"),
    ("checks_escape_labels",
     '',
     '(() => { m.appConfirmChecks("W", { allLabel: "<i>all</i>", choices: [{ value: "a<b", label: "<b>1</b>" }] }); const h = F().confirmMeta.innerHTML; return [h.includes("<b>"), h.includes("&lt;b&gt;1&lt;/b&gt;"), h.includes("<i>"), h.includes(`data-check="a&lt;b"`)]; })()',
     '[false,true,false,true]',
     "negative: подписи и значения экранированы"),
    ("choice_shows_its_label_and_press",
     '',
     '(() => { m.appConfirmChoice("Keep for how long?", { ...HOLDS, danger: false }); return [F().confirmMeta.hidden, chips(), /data-t="confirm-choice"/.test(F().confirmMeta.innerHTML), /dlg-choices-label">Unload when unused for</.test(F().confirmMeta.innerHTML), F().confirmInput.hidden]; })()',
     '[false,[["900","false","15 min"],["3600","false","1 h"],["-1","true","until I unload it"]],true,true,true]',
     "выбор: варианты — кнопками в meta, нажат заданный (choice), подпись — над ними; поля ввода нет"),
    ("choice_click_moves_the_press",
     '',
     'await (async () => { const p = m.appConfirmChoice("W", HOLDS); const b = F().confirmMeta.querySelectorAll(); b[0].onclick(); const pressed = chips().map((c) => c[1]); m.settleAppConfirm(true); return [pressed, await p, F().confirmMeta.hidden, F().confirmMeta.innerHTML]; })()',
     '[["true","false","false"],"900",true,""]',
     "нажатие переносит выбор: нажат один, и ответ — он; после — meta скрыта и пуста"),
    ("choice_cancel_is_null_and_forgets",
     '',
     'await (async () => { const p = m.appConfirmChoice("W", HOLDS); F().confirmMeta.querySelectorAll()[1].onclick(); m.settleAppConfirm(false); const a = await p; const q = m.appConfirmChoice("W", { choices: [] }); m.settleAppConfirm(true); const r = m.appPrompt("Name"); F().confirmInput.value = "x"; m.settleAppConfirm(true); return [a, await q, await r]; })()',
     '[null,null,"x"]',
     "negative: отмена — null; выбор не переживает диалог: следующий без вариантов отвечает null "
     "(as-is: без вариантов «OK» и «отмена» неотличимы — такого окна доска не открывает), обычный prompt — строкой"),
    ("choice_forgotten_when_reopened_unsettled",
     '',
     'await (async () => { m.appConfirmChoice("W", HOLDS); F().confirmMeta.querySelectorAll()[0].onclick(); const q = m.appConfirmChoice("W2", { choices: [] }); m.settleAppConfirm(true); return await q; })()',
     'null',
     "negative: второй диалог открыт поверх неотвеченного первого — выбор первого ему не достаётся"),
    ("choice_unknown_default_is_first",
     '',
     '(() => { m.appConfirmChoice("W", { ...HOLDS, choice: "86400" }); return chips().map((c) => c[1]); })()',
     '["true","false","false"]',
     "boundary: заданного варианта нет среди кнопок — нажат первый, а не ни один"),
    ("choice_labels_escaped",
     '',
     '(() => { m.appConfirmChoice("W", { choiceLabel: "<i>x</i>", choices: [{ value: "a<b", label: "<b>1</b>" }] }); return [F().confirmMeta.innerHTML.includes("<b>"), F().confirmMeta.innerHTML.includes("&lt;b&gt;1&lt;/b&gt;"), F().confirmMeta.innerHTML.includes("<i>"), F().confirmMeta.innerHTML.includes(`data-choice="a&lt;b"`)]; })()',
     '[false,true,false,true]',
     "negative: подписи и значения экранированы — вариант не превращается в разметку"),
    ("no_prompt_choice_mode",
     '',
     '(() => { const kind = typeof m.appPromptChoice; m.appPrompt("Name", HOLDS); return [kind, F().confirmMeta.hidden, F().confirmInput.hidden]; })()',
     '["undefined",true,false]',
     "negative: окна «ввод + выбор» больше нет — оно служило загрузке модели в движок, а модель теперь берут через ячейку "
     "(2026-09-26); prompt с вариантами — просто prompt"),
    ("choice_not_in_plain_prompt",
     '',
     '(() => { m.appPrompt("Name", HOLDS); return [F().confirmMeta.hidden, F().confirmMeta.innerHTML]; })()',
     '[true,""]',
     "negative: обычный prompt вариантов не рисует, даже если их передали"),
    ("no_choose_mode",
     '',
     'await (async () => { const kind = typeof m.appChoose; const p = m.appConfirm("x", { options: [{ value: "a", label: "A" }] }); const shown = [F().confirmMeta.innerHTML, F().confirmMeta.hidden, F().confirmDelete.hidden]; m.settleAppConfirm("a"); return [kind, shown, await p]; })()',
     '["undefined",["",true,false],true]',
     "negative: режима с несколькими ответами нет (appChoose служил вопросу старта ячейки контроллера): options не рисуются кнопками, OK на месте, строка-ответ — просто «да»"),
    ("confirm_choice_shows_choices_without_input",
     '',
     '(() => { m.appConfirmChoice("Reserve cell :22022?", { danger: false, title: "Where", choiceLabel: "Runs in", choices: [{ value: "", label: "Caravan" }, { value: "ollama", label: "Ollama" }] }); return [F().confirmTitle.textContent, F().confirmText.textContent, F().confirmMeta.hidden, chips(), F().confirmInput.hidden, modalOf().dataset.tone, F().confirmDelete.classList.has("danger"), /class="dlg-choices"/.test(F().confirmMeta.innerHTML), [...focusLog]]; })()',
     '["Where","Reserve cell :22022?",false,[["","true","Caravan"],["ollama","false","Ollama"]],true,"ask",false,true,["ok"]]',
     "confirm с выбором (где работает новая ячейка): вопрос — текстом, варианты — кнопками, нажат первый; поля ввода нет; тон «спросить», фокус на кнопке подтверждения; раскладка — строкой"),
    ("confirm_choice_answer_is_the_value",
     '',
     'await (async () => { const two = [{ value: "", label: "Caravan" }, { value: "ollama", label: "Ollama" }]; const a = m.appConfirmChoice("Q", { danger: false, choices: two }); m.settleAppConfirm(true); const first = await a; const b = m.appConfirmChoice("Q", { danger: false, choices: two }); F().confirmMeta.querySelectorAll()[1].onclick(); m.settleAppConfirm(true); return [first, await b, F().confirmMeta.hidden, F().confirmMeta.innerHTML]; })()',
     '["","ollama",true,""]',
     "ответ — значение нажатого варианта строкой; пустое значение первого варианта — ответ, а не отмена; после — meta скрыта и пуста"),
    ("confirm_choice_cancel_is_null",
     '',
     'await (async () => { const a = m.appConfirmChoice("Q", { danger: false, choices: [{ value: "x", label: "X" }] }); m.settleAppConfirm(false); const r = m.appConfirm("Sure?"); m.settleAppConfirm(true); return [await a, await r]; })()',
     '[null,true]',
     "negative: отмена — null, а не пустая строка; следующий обычный confirm отвечает true, а не выбором"),
    ("confirm_choice_list_is_a_column",
     '',
     '(() => { m.appConfirmChoice("Q", { danger: false, list: true, choices: [{ value: "a", label: "A" }] }); return /class="dlg-choices dlg-choices-list"/.test(F().confirmMeta.innerHTML); })()',
     'true',
     "list: true — длинный список (модели движка) столбцом: класс dlg-choices-list"),
    ("cancel_label_shown_then_restored",
     '',
     'await (async () => { const p = m.appConfirmChoice("Q", { danger: false, cancelLabel: "Not now", choices: [{ value: "x", label: "X" }] }); const shown = F().confirmCancel.textContent; m.settleAppConfirm(false); const after = F().confirmCancel.textContent; m.appConfirm("Sure?"); const plain = F().confirmCancel.textContent; m.settleAppConfirm(true); return [shown, await p, after, plain]; })()',
     '["Not now",null,"Cancel","Cancel"]',
     "подпись отмены («Не сейчас» у окна новой модели) — на время окна; после закрытия и у обычного confirm снова «Cancel»"),
    ("cancel_label_restored_for_legacy_openers",
     '',
     '(() => { m.appConfirm("x", { cancelLabel: "Not now" }); F().confirmCancel.textContent = "Not now"; m.settleAppConfirm(true); return F().confirmCancel.textContent; })()',
     '"Cancel"',
     "negative: окно, закрытое с подписью, не оставляет её легаси-открывалкам — они пишут поля сами, а подпись отмены нет"),
    ("typed_confirm_opens_with_the_button_off",
     '',
     '(() => { m.appConfirmTyped("Disconnect Box?", "Box B", { detail: "Box B", confirmLabel: "Disconnect" }); const a = [F().confirmInput.hidden, F().confirmDelete.disabled, F().confirmPath.textContent, F().confirmInput.placeholder, F().confirmDelete.textContent, modalOf().dataset.tone, F().confirmDelete.classList.has("danger"), [...focusLog], F().confirmInput.type, F().confirmInput.autocomplete]; m.settleAppConfirm(false); return a; })()',
     '[false,true,"Box B","Type the name above to confirm","Disconnect","danger",true,["input"],"text","off"]',
     "owner 2026-10-14: a click is not enough — the box is shown, the confirm button is OFF, the name stands above the box, the box asks for it in words, red tone, focus in the box (not on Cancel)"),
    ("typed_confirm_waits_for_the_exact_name",
     '',
     '(() => { m.appConfirmTyped("x", "Box B"); const inp = F().confirmInput; const off = (v) => { inp.value = v; inp.oninput(); return F().confirmDelete.disabled; }; const r = ["", "Box", "Box B", "  Box B  ", "box b", "Box B2", "Box  B"].map(off); m.settleAppConfirm(false); return r; })()',
     '[true,true,false,false,true,true,true]',
     "the button is on only when what is typed IS the name (spaces round it do not count); a part of it, another case, more or a gap inside — it stays off"),
    ("typed_confirm_enter_needs_the_name",
     '',
     'await (async () => { const p = m.appConfirmTyped("x", "Box B"); const inp = F().confirmInput; inp.value = "Box"; inp.oninput(); let prevented = 0; inp.onkeydown({ key: "Enter", preventDefault: () => { prevented++; } }); const still = F().confirmOverlay.hidden; inp.value = "Box B"; inp.oninput(); inp.onkeydown({ key: "Enter", preventDefault: () => { prevented++; } }); return [still, await p, F().confirmOverlay.hidden, prevented]; })()',
     '[false,true,true,2]',
     "Enter in the box closes nothing while the name is not there, and confirms once it is; the key is taken both times"),
    ("typed_confirm_cannot_be_settled_without_the_name",
     '',
     'await (async () => { const p = m.appConfirmTyped("x", "Box B"); F().confirmInput.value = "nope"; const first = m.settleAppConfirm(true); st.ui.pendingConfirm(); const open = [F().confirmOverlay.hidden, st.ui.pendingConfirm !== null]; F().confirmInput.value = "Box B"; const second = m.settleAppConfirm(true); return [first, open, await p, second, F().confirmOverlay.hidden]; })()',
     '[true,[false,true],true,true,true]',
     "negative: neither a call of settleAppConfirm(true) nor ui.pendingConfirm gets past the gate — the dialog stays open and says one is pending; with the name the same call confirms"),
    ("typed_confirm_cancel_is_false_whatever_is_typed",
     '',
     'await (async () => { const p = m.appConfirmTyped("x", "Box B"); F().confirmInput.value = "Box B"; m.settleAppConfirm(false); return await p; })()',
     'false', "negative: Cancel (and Escape, and a click outside) answers false even with the right name typed"),
    ("typed_confirm_leaves_nothing_behind",
     '',
     '(() => { m.appConfirmTyped("x", "Box B"); m.settleAppConfirm(false); const a = [F().confirmDelete.disabled, F().confirmInput.hidden]; m.appConfirmTyped("x", "Box B"); m.appConfirm("y"); return [...a, F().confirmDelete.disabled, F().confirmInput.hidden, m.settleAppConfirm(true)]; })()',
     '[false,true,false,true,true]',
     "negative: after a typed dialog the next plain confirm has its button on and no box — also one opened over a typed dialog that never settled, and it confirms by a plain settle"),
    ("typed_confirm_has_no_tab_suggestion",
     '',
     '(() => { m.appConfirmTyped("x", "Box B", { placeholder: "Box B" }); const inp = F().confirmInput; let prevented = false; inp.onkeydown({ key: "Tab", shiftKey: false, preventDefault: () => { prevented = true; } }); return [inp.value, prevented, F().confirmInputHint.hidden, F().confirmDelete.disabled]; })()',
     '["",false,true,true]',
     "negative: Tab does not fill the name in, as it does for a prompt's suggestion — the name is typed, which is the point"),
    ("typed_confirm_takes_a_number_as_text",
     '',
     '(() => { m.appConfirmTyped("x", 22009); const inp = F().confirmInput; inp.value = "22009"; inp.oninput(); const r = F().confirmDelete.disabled; m.settleAppConfirm(false); return r; })()',
     'false', "boundary: a name that is a number is a string to type, and the same string matches"),
    ("plain_confirm_ignores_choices",
     '',
     'await (async () => { const p = m.appConfirm("x", { danger: false, choices: [{ value: "a", label: "A" }] }); const shown = [F().confirmMeta.hidden, F().confirmMeta.innerHTML]; m.settleAppConfirm(true); return [shown, await p]; })()',
     '[[true,""],true]',
     "negative: обычный confirm вариантов не рисует, даже если их передали, и отвечает true"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 14:
        print(f"js dialogs FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js dialogs: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_dialogs.tmp.mjs"
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
        print(f"js dialogs FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("диалоги: подтверждение и ввод как промисы:")
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
    print(f"js dialogs OK: настоящий модуль в node, {len(PINS)} пинов диалогов значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
