#!/usr/bin/env python3
"""Снимок static/js/i18n.js — перевод и применение языка/темы к странице.

Что пинится значением. `t` — ключ на текущем языке, иначе английский, иначе
сам ключ; подстановки через replaceAll (плейсхолдер может встречаться дважды).
`fieldHelp` — по языку, потом английский, потом пусто. `applyLanguage` —
каждое семейство атрибутов: data-i18n (текст), placeholder, title+aria,
только aria, подсказки полей IN PLACE (без пересборки инпутов — иначе
пропали бы несохранённые правки), затем событие `caravan:langchange` для
составных текстов и перерисовка выпадашки. `setLang` — неизвестный или тот
же код ничего не делает; иначе таблица языка загружается, код сохраняется,
страница перекрашивается, зовётся хук страницы. Выпадашка: открытие/закрытие,
выбор, клик вне, Escape, отсутствие элементов. Тема — атрибут корня и
активная кнопка.

Настоящий модуль, настоящий i18n-data (таблицы языков грузятся динамически).
DOM — словарь по id и по селектору.

Запуск: python3 scripts/test_js_i18n.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = "form"

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
localStorage.clear();
globalThis.__events = []; globalThis.dispatchEvent = (ev) => { globalThis.__events.push(ev.type); return true; };
globalThis.__q = {}; document.querySelectorAll = (sel) => globalThis.__q[sel] || [];
const docListeners = {}; document.addEventListener = (t, fn) => { (docListeners[t] ||= []).push(fn); };
const m = await import(pathToFileURL(process.env.JS_ROOT + "/i18n.js").href);
const D = await import(pathToFileURL(process.env.JS_ROOT + "/i18n-data.js").href);
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), has: (c) => s.has(c) } };
const mkEl = (props = {}) => ({ textContent: "", placeholder: "", title: "", innerHTML: "", hidden: true, attrs: {}, dataset: {}, classList: cls(), listeners: {}, setAttribute(k, v) { this.attrs[k] = v; }, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, querySelector(sel) { return sel === ".tooltip" ? (this.tip ||= mkEl()) : null; }, contains(x) { return x === this; }, ...props });
const F = () => globalThis.__fields;
const reset = () => { localStorage.clear(); m.onLangChange(null); globalThis.__events.length = 0; globalThis.__q = {}; globalThis.__fields = {}; document.documentElement = { dataset: {}, lang: "" }; };
reset();
const out = {};
"""

PINS = [
    ("t_lookup_fallback_and_key", '', '[m.t("saved"), m.t("noSuchKey"), m.t("gcFreed", { gb: "1.2" })]', '["Saved.","noSuchKey","1.2 GB freed"]', "перевод: английский по умолчанию; неизвестный ключ — сам ключ; подстановка"),
    ("t_replaces_repeated_placeholder", '', '(s => [(s.match(/ZZQ/g) || []).length, s.includes("{to}")])(m.t("topologyCloudModelChangeWarn", { id: "b", from: "x", to: "ZZQ" }))', '[2,false]', "плейсхолдер, встречающийся дважды, подставляется оба раза"),
    ("t_uses_current_language_with_english_fallback", '', 'await (async () => { await m.setLang("ru"); D.messages.en.__probeKey = "probe-en"; const a = [m.lang, m.t("saved") !== "Saved.", m.t("noSuchKey"), m.t("__probeKey")]; delete D.messages.en.__probeKey; await m.setLang("en"); return [...a, m.t("saved")]; })()', '["ru",true,"noSuchKey","probe-en","Saved."]',
     "на русском — русская строка; ключ, которого нет ни в одной таблице, — сам ключ; ключ только в английской таблице — английский текст (в настоящих таблицах такого нет: гвард полного покрытия, поэтому проба); обратно на английский"),
    ("set_lang_noops", '', 'await (async () => { await m.setLang("zz"); const a = m.lang; await m.setLang(""); await m.setLang("en"); return [a, m.lang, localStorage.getItem("llamacppAdminLang")]; })()', '["en","en",null]', "negative: неизвестный, пустой и тот же код — ничего, в хранилище ничего"),
    ("set_lang_persists_applies_and_calls_hook", '', 'await (async () => { let hooked = 0; m.onLangChange(() => hooked++); await m.setLang("de"); const r = [localStorage.getItem("llamacppAdminLang"), document.documentElement.lang, hooked, [...globalThis.__events]]; await m.setLang("en"); return r; })()', '["de","de",1,["caravan:langchange"]]',
     "смена языка: сохранена, применена к корню, хук страницы вызван, событие для составных текстов отправлено"),
    ("init_language_loads_stored", '', 'await (async () => { localStorage.setItem("llamacppAdminLang", "fr"); const r = await m.initLanguage(); return [r, m.lang]; })()', '["en","en"]',
     "as-is: initLanguage грузит ТЕКУЩИЙ `lang` (прочитанный при импорте модуля), а не значение из хранилища на момент вызова"),
    ("field_help_fallbacks", '', '[typeof m.fieldHelp("THREADS"), m.fieldHelp("THREADS").length > 0, m.fieldHelp("NOPE_FIELD")]', '["string",true,""]', "подсказка поля: строка на языке или английская; неизвестное поле — пусто"),
    ("label_with_tip_markup", '', '(h => [h.includes(\'<label for="THREADS">THREADS</label>\'), h.includes(\'data-fieldhelp="THREADS"\'), h.includes("aria-label=\\"THREADS: "), h.includes(\'<span class="tooltip" role="tooltip">\')])(m.labelWithTip("THREADS"))', '[true,true,true,true]', "подпись поля с кнопкой-подсказкой и tooltip"),
    ("help_tip_escapes", '', '(h => [h.includes(\'data-i18n-tip="saved"\'), h.includes("aria-label=\\"Saved.\\""), (h.match(/Saved\\./g) || []).length])(m.helpTip("saved"))', '[true,true,2]', "инлайн-подсказка по ключу: текст в aria и в tooltip"),
    ("apply_theme", '', '(() => { const a = mkEl({ dataset: { themeChoice: "dark" } }); const b = mkEl({ dataset: { themeChoice: "light" } }); globalThis.__q["[data-theme-choice]"] = [a, b]; m.applyTheme(); return [document.documentElement.dataset.theme, a.classList.has("active"), b.classList.has("active")]; })()', '["dark",true,false]', "тема: атрибут корня и активная кнопка"),
    ("apply_language_attribute_families", '', '(() => { const el = { i18n: mkEl({ dataset: { i18n: "saved" } }), ph: mkEl({ dataset: { i18nPlaceholder: "saved" } }), title: mkEl({ dataset: { titleI18n: "saved" } }), aria: mkEl({ dataset: { i18nAria: "saved" } }), fh: mkEl({ dataset: { fieldhelp: "THREADS" } }), fht: mkEl({ dataset: { fieldhelpText: "THREADS" } }), tip: mkEl({ dataset: { i18nTip: "saved" } }) }; globalThis.__q = { "[data-i18n]": [el.i18n], "[data-i18n-placeholder]": [el.ph], "[data-title-i18n]": [el.title], "[data-i18n-aria]": [el.aria], "[data-fieldhelp]": [el.fh], "[data-fieldhelp-text]": [el.fht], "[data-i18n-tip]": [el.tip] }; m.applyLanguage(); return [el.i18n.textContent, el.ph.placeholder, el.title.title, el.title.attrs["aria-label"], el.aria.attrs["aria-label"], "title" in el.aria.attrs || el.aria.title !== "", el.fh.tip.textContent === m.fieldHelp("THREADS"), el.fh.attrs["aria-label"].startsWith("THREADS: "), el.fht.textContent === m.fieldHelp("THREADS"), el.tip.tip.textContent, el.tip.attrs["aria-label"], [...globalThis.__events], document.documentElement.lang]; })()',
     '["Saved.","Saved.","Saved.","Saved.","Saved.",false,true,true,true,"Saved.","Saved.",["caravan:langchange"],"en"]',
     "применение языка: текст, placeholder, title+aria, только aria (без title), подсказки полей на месте, i18n-tip, событие, lang корня"),
    ("render_lang_select", '', '(() => { globalThis.__fields = { langTriggerEmoji: mkEl(), langTriggerCode: mkEl(), langMenu: mkEl() }; m.renderLangSelect(); const h = F().langMenu.innerHTML; return [F().langTriggerCode.textContent, F().langTriggerEmoji.textContent.length > 0, (h.match(/class="lang-option/g) || []).length === D.LANGS.length, h.includes(\'lang-option selected" role="option" data-lang="en" aria-selected="true"\'), (h.match(/aria-selected="true"/g) || []).length]; })()',
     '["EN",true,true,true,1]', "выпадашка: код и глиф текущего языка, опция на каждый язык, отмечен ровно текущий"),
    ("render_lang_select_without_menu", '', '(() => { globalThis.__fields = { langTriggerCode: mkEl() }; m.renderLangSelect(); return F().langTriggerCode.textContent; })()', '"EN"', "negative: без меню — только триггер обновлён, без исключения"),
    ("setup_lang_select_open_close_pick", '', 'await (async () => { const root = mkEl({ contains: (x) => x === "inside" }); const trigger = mkEl(); const menu = mkEl(); globalThis.__fields = { langSelect: root, langTrigger: trigger, langMenu: menu, langTriggerCode: mkEl(), langTriggerEmoji: mkEl() }; m.setupLangSelect(); let stopped = 0; trigger.listeners.click[0]({ stopPropagation: () => stopped++ }); const opened = [menu.hidden, trigger.attrs["aria-expanded"]]; docListeners.click.at(-1)({ target: "outside" }); const closedOutside = menu.hidden; trigger.listeners.click[0]({ stopPropagation: () => stopped++ }); docListeners.keydown.at(-1)({ key: "Escape" }); const closedEsc = menu.hidden; trigger.listeners.click[0]({ stopPropagation: () => stopped++ }); menu.listeners.click[0]({ target: { closest: () => ({ dataset: { lang: "de" } }) } }); await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r)); const r = [stopped, ...opened, closedOutside, closedEsc, menu.hidden, m.lang, trigger.attrs["aria-expanded"]]; await m.setLang("en"); return r; })()',
     '[3,false,"true",true,true,true,"de","false"]', "выпадашка: клик открывает (aria-expanded), клик вне и Escape закрывают, выбор опции закрывает и переключает язык"),
    ("setup_lang_select_missing_elements", '', '(() => { const before = (docListeners.click || []).length; globalThis.__fields = { langSelect: mkEl() }; m.setupLangSelect(); return (docListeners.click || []).length - before; })()', '0', "negative: без триггера/меню слушатели не вешаются"),
    ("menu_click_outside_option", '', '(() => { const root = mkEl(); const trigger = mkEl(); const menu = mkEl(); globalThis.__fields = { langSelect: root, langTrigger: trigger, langMenu: menu }; m.setupLangSelect(); trigger.listeners.click[0]({ stopPropagation() {} }); menu.listeners.click[0]({ target: { closest: () => null } }); return [menu.hidden, m.lang]; })()', '[false,"en"]', "negative: клик по меню мимо опции ничего не меняет"),
    ("theme_default_from_storage", '', '[m.theme, m.lang]', '["dark","en"]', "умолчания при пустом хранилище: тёмная тема, английский"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 16:
        print(f"js i18n FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js i18n: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
        return 0

    def blocks(pins, sink):
        return [f"try {{ reset(); {setup}\n  {sink}[{json.dumps(pid)}] = {expr}; }} "
                f"catch (e) {{ {sink}[{json.dumps(pid)}] = {{ __threw: String(e && e.message || e) }}; }}"
                for pid, setup, expr, _exp, _msg in pins]

    # Пины не опираются друг на друга: тот же набор в обратном порядке обязан
    # дать те же значения.
    probe = (PREAMBLE + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_i18n.tmp.mjs"
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
        print(f"js i18n FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("i18n: перевод, подстановки, применение к DOM, переключатель языка:")
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
    print(f"js i18n OK: настоящий модуль в node, {len(PINS)} пинов i18n значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
