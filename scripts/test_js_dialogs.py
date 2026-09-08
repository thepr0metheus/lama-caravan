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
const build = () => {
  const modal = { dataset: {} };
  globalThis.__fields = {
    confirmOverlay: { hidden: true, dataset: {}, querySelector: (sel) => (sel === ".modal" ? modal : null) },
    confirmTitle: node("title"), confirmText: node("text"), confirmMeta: node("meta"), confirmPath: node("path"),
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
