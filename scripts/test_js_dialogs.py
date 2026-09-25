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
  n.querySelectorAll = () => {
    if (cache.html !== n.innerHTML) {
      cache = { html: n.innerHTML, list: [...n.innerHTML.matchAll(/data-choice="([^"]*)"\s*aria-checked="(true|false)">([^<]*)</g)]
        .map((x) => ({ dataset: { choice: x[1] }, label: x[3], attrs: { "aria-checked": x[2] }, onclick: null,
          setAttribute(k, v) { this.attrs[k] = v; } })) };
    }
    return cache.list;
  };
  return n;
};
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
     '["danger",true,["cancel"],"Confirm service action?","Stop the cell?"]',
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
     'await (async () => { const p = m.appPrompt("Name the agent", { value: "old" }); const before = [F().confirmInput.hidden, F().confirmInput.value, F().confirmTitle.textContent, modalOf().dataset.tone]; F().confirmInput.value = "hermes"; m.settleAppConfirm(true); return [await p, ...before, F().confirmInput.hidden]; })()',
     '["hermes",false,"old","Name the agent","ask",true]',
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
     'await (async () => { const p = m.appPrompt("Name", { placeholder: "hermes port" }); const shown = !F().confirmInputHint.hidden; let prevented = false; F().confirmInput.onkeydown({ key: "Tab", shiftKey: false, preventDefault: () => { prevented = true; } }); const after = [F().confirmInput.value, prevented, F().confirmInputHint.hidden, F().confirmOverlay.hidden]; m.settleAppConfirm(true); return [shown, after, await p]; })()',
     '[true,["hermes port",true,true,false],"hermes port"]',
     "positive: Tab в пустом поле подставляет подсказку из плейсхолдера, диалог остаётся открыт, клавиша-подсказка прячется; OK возвращает подставленное"),
    ("prompt_tab_moves_on_when_the_box_holds_it_or_something_else",
     '',
     '(() => { m.appPrompt("Name", { placeholder: "hermes port" }); const tab = () => { let prevented = false; F().confirmInput.onkeydown({ key: "Tab", shiftKey: false, preventDefault: () => { prevented = true; } }); return prevented; }; F().confirmInput.value = "hermes port"; const held = tab(); F().confirmInput.value = "other"; F().confirmInput.oninput(); const other = [tab(), F().confirmInput.value, F().confirmInputHint.hidden]; F().confirmInput.value = "her"; F().confirmInput.oninput(); const prefix = [F().confirmInputHint.hidden, tab(), F().confirmInput.value]; m.settleAppConfirm(false); return [held, other, prefix]; })()',
     '[false,[false,"other",true],[false,true,"hermes port"]]',
     "boundary: поле уже держит подсказку или чужой текст — Tab идёт дальше по фокусу, ничего не меняя, клавиша скрыта; набранный префикс подсказки — клавиша видна и Tab дописывает её"),
    ("prompt_shift_tab_and_no_placeholder_pass_through",
     '',
     '(() => { m.appPrompt("Name", { placeholder: "hermes port" }); let a = false; F().confirmInput.onkeydown({ key: "Tab", shiftKey: true, preventDefault: () => { a = true; } }); const v1 = F().confirmInput.value; m.settleAppConfirm(false); m.appPrompt("Name"); const hidden = F().confirmInputHint.hidden; let b = false; F().confirmInput.onkeydown({ key: "Tab", shiftKey: false, preventDefault: () => { b = true; } }); const v2 = F().confirmInput.value; m.settleAppConfirm(false); return [a, v1, hidden, b, v2]; })()',
     '[false,"",true,false,""]',
     "negative: Shift+Tab — обычная навигация назад, поле не трогается; без плейсхолдера подсказки нет: клавиша скрыта, Tab не перехватывается"),
    ("confirm_mode_hides_the_tab_hint",
     '',
     '(() => { m.appPrompt("Name", { placeholder: "x" }); const shown = !F().confirmInputHint.hidden; m.settleAppConfirm(false); const afterSettle = F().confirmInputHint.hidden; m.appConfirm("Sure?"); const inConfirm = F().confirmInputHint.hidden; m.settleAppConfirm(false); return [shown, afterSettle, inConfirm]; })()',
     '[true,true,true]',
     "negative: клавиша видна только в открытом prompt: после закрытия и у обычного confirm она скрыта"),
    ("choice_shows_its_choices",
     '',
     '(() => { m.appPromptChoice("Context window for m", HOLDS); return [F().confirmMeta.hidden, chips(), /data-t="confirm-choice"/.test(F().confirmMeta.innerHTML), /dlg-choices-label">Unload when unused for</.test(F().confirmMeta.innerHTML), F().confirmInput.hidden, modalOf().dataset.tone, F().confirmDelete.classList.has("danger")]; })()',
     '[false,[["900","false","15 min"],["3600","false","1 h"],["-1","true","until I unload it"]],true,true,false,"ask",false]',
     "prompt с выбором: варианты — кнопками в meta, нажат заданный; подпись — над ними; поле ввода видно; тон «спросить», кнопка не опасная"),
    ("choice_answer_is_text_and_choice",
     '',
     'await (async () => { const p = m.appPromptChoice("W", HOLDS); F().confirmInput.value = "4096"; m.settleAppConfirm(true); return [await p, F().confirmMeta.hidden, F().confirmMeta.innerHTML]; })()',
     '[{"value":"4096","choice":"-1"},true,""]',
     "ответ — текст и нажатый вариант; после — meta скрыта и пуста"),
    ("choice_click_moves_the_press",
     '',
     'await (async () => { const p = m.appPromptChoice("W", HOLDS); const b = F().confirmMeta.querySelectorAll(); b[0].onclick(); const pressed = chips().map((c) => c[1]); m.settleAppConfirm(true); return [pressed, await p]; })()',
     '[["true","false","false"],{"value":"","choice":"900"}]',
     "нажатие переносит выбор: нажат один, и ответ — он"),
    ("choice_cancel_is_null_and_forgets",
     '',
     'await (async () => { const p = m.appPromptChoice("W", HOLDS); F().confirmMeta.querySelectorAll()[1].onclick(); m.settleAppConfirm(false); const a = await p; const q = m.appPromptChoice("W", { choices: [] }); m.settleAppConfirm(true); const r = m.appPrompt("Name"); F().confirmInput.value = "x"; m.settleAppConfirm(true); return [a, await q, await r]; })()',
     '[null,{"value":"","choice":null},"x"]',
     "negative: отмена — null; выбор не переживает диалог: следующий без вариантов отвечает choice null, обычный prompt — строкой"),
    ("choice_forgotten_when_reopened_unsettled",
     '',
     'await (async () => { m.appPromptChoice("W", HOLDS); F().confirmMeta.querySelectorAll()[0].onclick(); const q = m.appPromptChoice("W2", { choices: [] }); m.settleAppConfirm(true); return await q; })()',
     '{"value":"","choice":null}',
     "negative: второй диалог открыт поверх неотвеченного первого — выбор первого ему не достаётся"),
    ("choice_unknown_default_is_first",
     '',
     '(() => { m.appPromptChoice("W", { ...HOLDS, choice: "86400" }); return chips().map((c) => c[1]); })()',
     '["true","false","false"]',
     "boundary: заданного варианта нет среди кнопок — нажат первый, а не ни один"),
    ("choice_labels_escaped",
     '',
     '(() => { m.appPromptChoice("W", { choiceLabel: "<i>x</i>", choices: [{ value: "a<b", label: "<b>1</b>" }] }); return [F().confirmMeta.innerHTML.includes("<b>"), F().confirmMeta.innerHTML.includes("&lt;b&gt;1&lt;/b&gt;"), F().confirmMeta.innerHTML.includes("<i>"), F().confirmMeta.innerHTML.includes(`data-choice="a&lt;b"`)]; })()',
     '[false,true,false,true]',
     "negative: подписи и значения экранированы — вариант не превращается в разметку"),
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
