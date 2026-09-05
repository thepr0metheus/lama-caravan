#!/usr/bin/env python3
"""Снимок static/js/favorites.js — избранные поля формы запуска.

Контракт: набор избранного глобален и живёт в state.favFields, каждое
изменение уходит на /api/config-favorites; канонические инпуты остаются в
своих вкладках, а вкладка избранного показывает ЗЕРКАЛА, которые пробрасывают
правку в канонический инпут его же событием (input/change) — так вся
существующая проводка (подписи переключателей, превью команды, dirty)
срабатывает без изменений. Пинится значением: включение/выключение звезды и
что уходит на провод, звёзды канонических полей обновляются, а звёзды в
панели избранного не трогаются; зеркало без канонического поля — только
подпись; зеркало-чекбокс и текстовое зеркало пробрасывают события; панель
строится только для существующих полей и без EXTRA_ARGS; перестановка
перетаскиванием до/после и её граничные случаи; синхронизация значений при
открытии вкладки.

DOM — словарь `globalThis.__fields` и элементы mkEl с querySelector по
простым селекторам, classList, dispatchEvent-журналом.

Запуск: python3 scripts/test_js_favorites.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("polling,canvas,topology-dnd,topology-render,dialogs,charts,cables,cloud,history,config-locator,"
         "system-panels,onboarding,onboarding-tours,usage-stats,dialog-llamas,models-page,system-page,memory,"
         "command-preview,llama-edit,remote-cells,topology-nodes,topology-modals,routers,topology-activity,topology-proxies,model-meta")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {}, favFields: [] });
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), contains: (c) => s.has(c), has: (c) => s.has(c), list: () => [...s].sort() } };
// Элемент словарного DOM: дети, querySelector по классу/тегу/атрибуту, closest по data-adv-panel, события.
const mkEl = (tag, props = {}) => { const e = { tag, children: [], className: "", classList: cls(), dataset: {}, listeners: {}, events: [], innerHTML: "", value: "", checked: false, type: "", title: "", textContent: "", parent: null,
  appendChild(c) { c.parent = this; this.children.push(c); return c; },
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); },
  dispatchEvent(ev) { this.events.push(ev.type); return true; },
  closest(sel) { let n = this; while (n) { if (sel === '[data-adv-panel="fav"]' && n.dataset.advPanel === "fav") return n; n = n.parent; } return null; },
  all() { return this.children.flatMap((c) => [c, ...c.all()]); },
  match(sel) { if (sel === ".label-row") return this.className.split(" ").includes("label-row"); if (sel === "input") return this.tag === "input"; if (sel === ".fav-drag-handle") return this.classList.has("fav-drag-handle") || this.className.includes("fav-drag-handle");
    if (sel === '.fav-star[data-fav-field]') return this.className.includes("fav-star") && "favField" in this.dataset; if (sel === '[data-adv-panel="fav"] .fav-mirrors') return this.className === "fav-mirrors" && !!this.closest('[data-adv-panel="fav"]');
    if (sel === ".field[data-fav-field]") return this.className === "field" && "favField" in this.dataset; return false; },
  querySelector(sel) { return this.all().find((c) => c.match(sel)) || null; }, querySelectorAll(sel) { return this.all().filter((c) => c.match(sel)); },
  getBoundingClientRect() { return { left: 0, width: 100 }; }, ...props };
  // innerHTML в этом DOM — строка; модуль после innerHTML ищет input внутри — разбираем минимально: <input id=… type=checkbox checked?>
  Object.defineProperty(e, "innerHTML", { get() { return this._html || ""; }, set(v) { this._html = v; this.children = []; const m = v.match(/<input id="([^"]+)"( type="checkbox")?( checked)?/); if (m) { const inp = mkEl("input", { type: m[2] ? "checkbox" : "text", checked: !!m[3] }); inp.id = m[1]; this.appendChild(inp); } if (v.includes('class="label-row"')) { const row = mkEl("div", { className: "label-row" }); this.appendChild(row); } } });
  return e; };
document.createElement = (tag) => mkEl(tag);
const m = await import(pathToFileURL(process.env.JS_ROOT + "/favorites.js").href);
const toastEl = () => ({ textContent: "", classList: cls() });
const toastText = () => globalThis.__fields.toast.textContent;
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, body: JSON.parse(c.body) }));
// Форма: канонические поля CTX (текст) и FLASH (чекбокс); панель избранного внутри dynamicFields.
const buildForm = () => {
  const wrap = mkEl("div"); const favPanel = wrap.appendChild(mkEl("div", { dataset: { advPanel: "fav" } })); const mirrors = favPanel.appendChild(mkEl("div", { className: "fav-mirrors" }));
  const starOf = (field, inPanel) => { const s = mkEl("button", { className: "fav-star", dataset: { favField: field } }); (inPanel ? favPanel : wrap).appendChild(s); return s; };
  globalThis.__fields = { toast: toastEl(), dynamicFields: wrap, CTX: mkEl("input", { type: "text", value: "8192" }), FLASH: mkEl("input", { type: "checkbox", checked: true }), EXTRA_ARGS: mkEl("textarea", { type: "textarea", value: "--flag" }) };
  return { wrap, favPanel, mirrors, starOf };
};
let F;
const reset = () => { st.setState({ config: {}, favFields: [] }); F = buildForm(); globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = {}; };
reset();
const out = {};
"""

PINS = [
    ("fav_fields_and_is_fav", 'st.state.favFields = ["CTX"];', '[m.getFavFields(), m.isFav("CTX"), m.isFav("FLASH"), (st.state.favFields = "nope", m.getFavFields())]', '[["CTX"],true,false,[]]',
     "набор из state; не массив — пусто"),
    ("toggle_adds_and_posts", '', 'await (async () => { await m.toggleFavorite("CTX"); return [st.state.favFields, calls()]; })()',
     '[["CTX"],[{"path":"/api/config-favorites","body":{"favorites":["CTX"]}}]]', "звезда включена: поле в наборе, набор ушёл на провод"),
    ("toggle_removes", 'st.state.favFields = ["CTX", "FLASH"];', 'await (async () => { await m.toggleFavorite("CTX"); return [st.state.favFields, calls()[0].body.favorites]; })()', '[["FLASH"],["FLASH"]]', "повторная звезда снимает поле"),
    ("toggle_failure_keeps_local_and_toasts", 'globalThis.__fetchReply["/api/config-favorites"] = { __status: 500, error: "ro-fs" };', 'await (async () => { await m.toggleFavorite("CTX"); return [st.state.favFields, toastText()]; })()', '[["CTX"],"ro-fs"]',
     "as-is: отказ сервера — локальный набор остаётся изменённым, оператору тост"),
    ("toggle_refreshes_panel_and_stars", '', 'await (async () => { const s = F.starOf("CTX", false); await m.toggleFavorite("CTX"); return [s.classList.has("is-fav"), F.mirrors.children.length, F.mirrors.children[0]?.className]; })()',
     '[true,1,"advanced-grid"]', "включение звезды перестраивает панель (сетка зеркал) и зажигает каноническую звезду"),
    ("attach_star_needs_label_row", '', '(() => { const d = mkEl("div"); m.attachFavStar(d, "CTX", ""); const n = d.children.length; d.appendChild(mkEl("div", { className: "label-row" })); m.attachFavStar(d, "CTX", ""); const star = d.querySelector(".label-row").children[0]; return [n, star.className, star.dataset.favField, star.textContent, star.type]; })()',
     '[0,"fav-star","CTX","★","button"]', "звезда вставляется только в строку подписи; кнопка с полем в dataset"),
    ("attach_star_lit_when_fav_or_always", 'st.state.favFields = ["CTX"];', '(() => { const mk = (f, always) => { const d = mkEl("div"); d.appendChild(mkEl("div", { className: "label-row" })); m.attachFavStar(d, f, "", always); return d.querySelector(".label-row").children[0].className; }; return [mk("CTX", false), mk("FLASH", false), mk("FLASH", true)]; })()',
     '["fav-star is-fav","fav-star","fav-star is-fav"]', "звезда горит для избранного поля и всегда — в панели избранного"),
    ("attach_star_click_toggles", '', 'await (async () => { const d = mkEl("div"); d.appendChild(mkEl("div", { className: "label-row" })); m.attachFavStar(d, "FLASH", ""); const star = d.querySelector(".label-row").children[0]; let prevented = 0; star.listeners.click[0]({ preventDefault: () => prevented++, stopPropagation: () => prevented++ }); await new Promise((r) => setImmediate(r)); return [prevented, st.state.favFields]; })()',
     '[2,["FLASH"]]', "клик по звезде переключает избранное и гасит событие"),
    ("update_star_states_skips_panel", 'st.state.favFields = ["CTX"];', '(() => { const a = F.starOf("CTX", false); const b = F.starOf("FLASH", false); const p = F.starOf("FLASH", true); p.classList.add("is-fav"); m.updateStarStates(); return [a.classList.has("is-fav"), b.classList.has("is-fav"), p.classList.has("is-fav")]; })()',
     '[true,false,true]', "канонические звёзды по набору; звезда внутри панели избранного не гасится"),
    ("update_star_states_without_wrap", 'delete globalThis.__fields.dynamicFields;', '(() => { m.updateStarStates(); m.refreshFavoritesPanel(); return true; })()', 'true', "negative: без формы — без исключения"),
    ("mirror_without_canonical", '', '(() => { const d = m.renderFavoriteMirror("GONE"); return [d.className, d.dataset.favField, d.innerHTML.includes("<label for=\\"fav-GONE\\">GONE</label>"), d.innerHTML.includes("<input"), d.querySelector(".label-row").children.length]; })()',
     '["field","GONE",true,false,1]', "зеркало поля, которого нет в форме: только подпись со звездой, без инпута"),
    ("mirror_text_forwards_input", '', '(() => { const d = m.renderFavoriteMirror("CTX"); const inp = d.querySelector("input"); const before = [inp.id, d.innerHTML.includes(\'value="8192"\')]; inp.value = "4096"; inp.listeners.input[0](); return [...before, globalThis.__fields.CTX.value, globalThis.__fields.CTX.events]; })()',
     '["fav-CTX",true,"4096",["input"]]', "текстовое зеркало: префилл из канонического, правка уходит в него его же событием input"),
    ("mirror_checkbox_forwards_change", '', '(() => { const d = m.renderFavoriteMirror("FLASH"); const inp = d.querySelector("input"); const before = [inp.id, inp.type, inp.checked]; inp.checked = false; inp.listeners.change[0](); return [...before, globalThis.__fields.FLASH.checked, globalThis.__fields.FLASH.events]; })()',
     '["fav-FLASH","checkbox",true,false,["change"]]', "зеркало-чекбокс: состояние из канонического, переключение уходит событием change"),
    ("mirror_prefixed_ids", 'globalThis.__fields["rc-CTX"] = mkEl("input", { type: "text", value: "1" });', '(() => { const d = m.renderFavoriteMirror("CTX", "rc-"); return d.querySelector("input").id; })()', '"rc-fav-CTX"', "префикс формы участвует в id зеркала"),
    ("panel_empty_hint", 'st.state.favFields = ["EXTRA_ARGS", "GONE"];', '(() => { m.refreshFavoritesPanel(); return [F.mirrors.innerHTML.includes("fav-empty"), F.mirrors.children.length]; })()', '[true,0]',
     "панель: EXTRA_ARGS закреплён отдельно, несуществующее поле пропущено — остаётся подсказка «пусто»"),
    ("panel_grid_of_existing", 'st.state.favFields = ["FLASH", "GONE", "CTX", "EXTRA_ARGS"];', '(() => { m.refreshFavoritesPanel(); const grid = F.mirrors.children[0]; return [grid.className, grid.children.map((c) => c.dataset.favField), grid.children.every((c) => !!c.listeners.dragover)]; })()',
     '["advanced-grid",["FLASH","CTX"],true]', "панель: сетка зеркал в порядке набора, только существующие поля, перетаскивание навешано"),
    ("panel_without_mirrors_area", '', '(() => { F.mirrors.className = "other"; m.refreshFavoritesPanel(); return F.mirrors.children.length; })()', '0', "negative: без области зеркал панель не трогается"),
    ("reorder_before_and_after", 'st.state.favFields = ["A", "B", "C"];', 'await (async () => { await m.reorderFavorites("C", "A", false); const a = st.state.favFields.slice(); await m.reorderFavorites("A", "B", true); return [a, st.state.favFields, calls().length, calls()[1].body.favorites]; })()',
     '[["C","A","B"],["C","B","A"],2,["C","B","A"]]', "перестановка: до цели и после цели; каждая уходит на провод"),
    ("reorder_noops", 'st.state.favFields = ["A", "B"];', 'await (async () => { await m.reorderFavorites("A", "A", true); await m.reorderFavorites("Z", "A", true); await m.reorderFavorites("A", "Z", true); await m.reorderFavorites("", "A", true); return [st.state.favFields, calls().length]; })()',
     '[["A","B"],0]', "negative: на себя, неизвестный источник или цель, пустой источник — ничего"),
    ("sync_mirrors_copies_values", 'st.state.favFields = ["CTX", "FLASH", "GONE"]; globalThis.__fields["fav-CTX"] = mkEl("input", { type: "text" }); globalThis.__fields["fav-FLASH"] = mkEl("input", { type: "checkbox" }); globalThis.__fields.FLASH.checked = false;',
     '(() => { m.syncFavoriteMirrors(); return [globalThis.__fields["fav-CTX"].value, globalThis.__fields["fav-FLASH"].checked]; })()', '["8192",false]', "открытие вкладки: значения и галки копируются из канонических; поле без зеркала пропущено"),
    ("dnd_drop_reorders", 'st.state.favFields = ["CTX", "FLASH"];', 'await (async () => { m.refreshFavoritesPanel(); const grid = F.mirrors.children[0]; const target = grid.children[0]; const dt = { getData: () => "FLASH", setData() {}, effectAllowed: "", dropEffect: "" }; target.listeners.drop[0]({ preventDefault() {}, dataTransfer: dt, clientX: 10 }); await new Promise((r) => setImmediate(r)); return st.state.favFields; })()',
     '["FLASH","CTX"]', "drop левее середины цели — источник встаёт перед ней"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 18:
        print(f"js favorites FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js favorites: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_favorites.tmp.mjs"
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
        print(f"js favorites FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("избранные поля: звёзды, зеркала, порядок:")
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
    print(f"js favorites OK: настоящий модуль в node, {len(PINS)} пинов избранного значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
