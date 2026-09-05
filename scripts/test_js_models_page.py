#!/usr/bin/env python3
"""Снимок static/js/models-page.js — страница /models.

Модуль — вход страницы: без экспортов, всё внутри обработчика DOMContentLoaded.
Снимок перехватывает этот обработчик при импорте и вызывает его сам, а дальше
пинит значением: сводные плитки (число GGUF, общий объём с порогами формата
GB, неиспользуемые — warn/good, диск — warn ниже 50 GB), дерево
модель → автор → квант → файлы с суммами объёма и свежестью, сортировка
«крупные первыми» на каждом уровне, строка файла (используется — ✓ с именами
ячеек; нет — чекбокс с путём и размером), пустое дерево, отказы (ok:false и
исключение → текст и состояние страницы error), подсчёт выбранного, удаление
только выбранных и только после подтверждения, смена каталога моделей —
слияние поверх ТЕКУЩЕГО сохранённого конфига (иначе /api/config затёр бы всё
остальное) с restart:false; пустой путь не сохраняется.

DOM — словарь `globalThis.__fields`; `document.querySelectorAll` по строке
селектора отдаёт список чекбоксов из `globalThis.__boxes`.

Запуск: python3 scripts/test_js_models_page.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("dialogs,dialog-llamas,polling,canvas,topology-dnd,topology-render,charts,cables,cloud,history,favorites,"
         "config-locator,system-panels,onboarding,onboarding-tours,usage-stats,system-page,memory,command-preview,"
         "llama-edit,remote-cells,topology-nodes,topology-modals,routers,topology-activity,topology-proxies,model-meta,form")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
const docListeners = {}; document.addEventListener = (t, fn) => { (docListeners[t] ||= []).push(fn); };
document.body = { dataset: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, appendChild() {}, contains: () => false };
globalThis.__boxes = []; document.querySelectorAll = (sel) => (sel.startsWith("#mdlTree input[data-del-path]") ? (sel.endsWith(":checked") ? globalThis.__boxes.filter((b) => b.checked) : globalThis.__boxes) : []);
await import(pathToFileURL(process.env.JS_ROOT + "/models-page.js").href);
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), has: (c) => s.has(c) } };
const mkEl = () => ({ textContent: "", innerHTML: "", hidden: false, disabled: false, value: "", classList: cls(), listeners: {}, focused: 0, clicked: 0, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, setAttribute() {}, focus() { this.focused += 1; }, click() { this.clicked += 1; (this.listeners.click || []).forEach((fn) => fn({})); }, contains: () => false });
const IDS = ["mdlTree", "mdlPicked", "mdlDelete", "mdlPath", "mdlHeroStats", "confirmCancel", "confirmDelete", "confirmOverlay", "mdlPathEdit", "mdlPathInput", "mdlPathEditRow", "mdlPathCancel", "mdlPathSave", "mdlSelectAll", "toast", "userChipName", "userChip", "userMenu", "userChipBtn", "userMenuLogout"];
const F = () => globalThis.__fields;
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body === null ? null : JSON.parse(c.body) }));
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); };
const FILES = () => [
  { path: "qwen/Qwen/Q4/qwen-q4.gguf", sizeBytes: 4 * 2 ** 30, ageDays: 12, referenced: true, referencedBy: ["cell:22001"] },
  { path: "qwen/Qwen/Q8/qwen-q8.gguf", sizeBytes: 8 * 2 ** 30, ageDays: 3, referenced: false },
  { path: "llama/Meta/Q4/l-q4.gguf", sizeBytes: 2 * 2 ** 30, ageDays: 40, referenced: false },
  { path: "root.gguf", sizeBytes: 0.5 * 2 ** 30, ageDays: 1, referenced: false },
];
const REPLY = (files, extra = {}) => ({ ok: true, path: "/models", files, unusedCount: files.filter((f) => !f.referenced).length, unusedGb: 10.5, ...extra });
// Страница стартует обработчиком DOMContentLoaded: он биндит кнопки и делает первый refresh.
const boot = async (files = FILES(), disk = { ok: true, freeGb: 120 }) => {
  globalThis.__fetchReply["/api/models/unused"] = REPLY(files); globalThis.__fetchReply["/api/models/disk"] = disk;
  for (const fn of docListeners.DOMContentLoaded) await fn(); await settle(); globalThis.__fetchCalls.length = 0;
};
const reset = () => { globalThis.__fields = Object.fromEntries(IDS.map((id) => [id, mkEl()])); globalThis.__boxes = []; st.ui.pendingConfirm = null;
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = { "/api/auth/me": { enabled: false } }; globalThis.__stubReturns = { "dialogs.appConfirm": async () => true }; };
reset();
const tree = () => F().mdlTree.innerHTML;
const box = (path, size, checked) => ({ checked, dataset: { delPath: path, size: String(size) } });
const out = {};
"""

PINS = [
    ("hero_tiles", '', 'await (async () => { await boot(); const h = F().mdlHeroStats.innerHTML; return [h.includes("<span>GGUF</span><strong title=\\"4\\">4</strong>"), h.includes("<strong title=\\"14.5 GB\\">14.5 GB</strong>"), h.includes("mdl-stat warn\\"><span>Unused models</span>") || /mdl-stat warn"><span>[^<]*<\\/span><strong title="3 · 10.5 GB"/.test(h), h.includes("mdl-stat good\\"><span>models disk</span><strong title=\\"120 GB free\\">"), F().mdlPath.textContent]; })()',
     '[true,true,true,true,"/models"]', "плитки: число GGUF, общий объём, неиспользуемые — warn, диск — good при 120 GB; путь каталога"),
    ("hero_disk_low_and_missing", '', 'await (async () => { await boot(FILES(), { ok: true, freeGb: 20 }); const a = F().mdlHeroStats.innerHTML.includes("mdl-stat warn\\"><span>models disk</span>"); await boot(FILES(), { ok: false }); return [a, F().mdlHeroStats.innerHTML.includes("models disk")]; })()',
     '[true,false]', "диск ниже 50 GB — warn; без данных о диске плитки нет"),
    ("hero_all_used_is_good", '', 'await (async () => { await boot([{ path: "a/b/c/d.gguf", sizeBytes: 2 ** 30, ageDays: 1, referenced: true, referencedBy: ["x"] }]); return /mdl-stat good"><span>[^<]*<\\/span><strong title="0 · 10.5 GB"/.test(F().mdlHeroStats.innerHTML); })()', 'true', "ничего неиспользуемого — плитка good"),
    ("tree_grouping_and_rollups", '', 'await (async () => { await boot(); const h = tree(); return [h.includes(\'data-t="models-tree-group" data-t-id="qwen"\'), h.includes("mdl-name\\">qwen</span>\\n        <span class=\\"mdl-size\\">12.0 GB · 3d</span>"), h.includes("mdl-name\\">Q8</span>\\n        <span class=\\"mdl-size\\">8.00 GB · 3d</span>"), h.includes(\'data-t-id="(root)"\'), h.includes("mdl-name\\">·</span>"), (h.match(/<details/g) || []).length]; })()',
     '[true,true,true,true,true,10]', "дерево: модель с суммой объёма и свежестью (самый свежий файл внутри), квант с двумя десятичными до 10 GB, файл в корне — (root) с «·» уровнями; 3 модели × 3 уровня + 1"),
    ("tree_largest_first_every_level", '', 'await (async () => { await boot(); const h = tree(); const i = (s) => h.indexOf(s); return [i(\'data-t-id="qwen"\') < i(\'data-t-id="llama"\'), i(\'data-t-id="llama"\') < i(\'data-t-id="(root)"\'), i(\'data-t-id="Q8"\') < i(\'data-t-id="Q4"\')]; })()', '[true,true,true]', "крупные первыми на каждом уровне: модели, кванты"),
    ("file_rows_used_and_deletable", '', 'await (async () => { await boot(); const h = tree(); return [h.includes("<span class=\\"mdl-used\\" title=\\"cell:22001\\">✓ cell:22001</span><code title=\\"qwen/Qwen/Q4/qwen-q4.gguf\\">qwen-q4.gguf</code>"), h.includes(\'aria-label="qwen/Qwen/Q8/qwen-q8.gguf" data-t="models-model-select" data-t-id="qwen/Qwen/Q8/qwen-q8.gguf" data-del-path="qwen/Qwen/Q8/qwen-q8.gguf" data-size="8589934592"\'), (h.match(/data-del-path=/g) || []).length, h.includes("8.00 GB · 3d</span>"), h.includes("0.50 GB · 1d")]; })()',
     '[true,true,3,true,true]', "строка файла: используемый — ✓ с ячейками и без чекбокса; неиспользуемый — чекбокс с путём (не именем) и размером; размер и возраст"),
    ("tree_empty", '', 'await (async () => { await boot([]); return [tree().includes("Nothing unused"), F().mdlDelete.disabled, F().mdlPicked.textContent, document.body.dataset.tState]; })()', '[true,true,"","ready"]', "пустой каталог — подсказка, удаление выключено, страница ready"),
    ("refresh_not_ok_and_throw", '', 'await (async () => { globalThis.__fetchReply["/api/models/unused"] = { ok: false, error: "no such dir" }; for (const fn of docListeners.DOMContentLoaded) await fn(); await settle(); const a = [tree().includes("no such dir"), document.body.dataset.tState]; globalThis.__fetchReply["/api/models/unused"] = { __status: 500, error: "boom" }; for (const fn of docListeners.DOMContentLoaded) await fn(); await settle(); return [...a, tree().includes("boom"), document.body.dataset.tState]; })()',
     '[true,"error",true,"error"]', "negative: ok:false и исключение — текст в дереве и состояние error (страница честно говорит, что не загрузилась)"),
    ("picked_counter", '', 'await (async () => { await boot(); globalThis.__boxes = [box("a", 2 ** 30, true), box("b", 3 * 2 ** 30, true), box("c", 2 ** 30, false)]; F().mdlTree.listeners.change[0](); return [F().mdlPicked.textContent, F().mdlDelete.disabled]; })()', '["2 · 4.00 GB",false]', "счётчик выбранного: число и объём отмеченных; кнопка удаления включена"),
    ("select_all", '', 'await (async () => { await boot(); globalThis.__boxes = [box("a", 2 ** 30, false), box("b", 2 ** 30, false)]; F().mdlSelectAll.listeners.click[0](); return [globalThis.__boxes.every((b) => b.checked), F().mdlPicked.textContent]; })()', '[true,"2 · 2.00 GB"]', "«выбрать всё» отмечает все чекбоксы и пересчитывает"),
    ("delete_nothing_selected", '', 'await (async () => { await boot(); await F().mdlDelete.listeners.click[0](); return calls().length; })()', '0', "negative: ничего не выбрано — ни запроса"),
    ("delete_refused_by_confirm", '', 'await (async () => { await boot(); globalThis.__boxes = [box("a/b", 2 ** 30, true)]; globalThis.__stubReturns["dialogs.appConfirm"] = async () => false; await F().mdlDelete.listeners.click[0](); return calls().length; })()', '0', "negative: отказ подтверждения — ни запроса"),
    ("delete_selected_posts_and_refreshes", 'globalThis.__fetchReply["/api/models/gc"] = { ok: true, freedGb: 9 };', 'await (async () => { await boot(); globalThis.__boxes = [box("qwen/Qwen/Q8/qwen-q8.gguf", 8 * 2 ** 30, true), box("root.gguf", 1, false)]; await F().mdlDelete.listeners.click[0](); await settle(); const c = calls(); return [c[0].path, c[0].body, F().toast.textContent, c.slice(1).map((x) => x.path), F().mdlDelete.disabled]; })()',
     '["/api/models/gc",{"files":["qwen/Qwen/Q8/qwen-q8.gguf"]},"9 GB freed",["/api/models/unused","/api/models/disk"],false]', "удаление: POST только отмеченных путей, тост, перечитывание, кнопка снова включена"),
    ("path_edit_opens_with_current", '', 'await (async () => { await boot(); F().mdlPathEdit.listeners.click[0](); return [F().mdlPathInput.value, F().mdlPathEditRow.hidden, F().mdlPathInput.focused]; })()', '["/models",false,1]', "правка каталога: поле с текущим путём, строка показана, фокус"),
    ("path_save_merges_over_saved_config", 'globalThis.__fetchReply["/api/state"] = { config: { MODEL_FILE: "x.gguf", THREADS: "8" } };', 'await (async () => { await boot(); F().mdlPathInput.value = " /srv/models "; await F().mdlPathSave.listeners.click[0](); await settle(); const c = calls(); return [c[0].path, c[1].path, c[1].body, F().mdlPathEditRow.hidden, F().toast.textContent, c.slice(2).map((x) => x.path)]; })()',
     '["/api/state","/api/config",{"config":{"MODEL_FILE":"x.gguf","THREADS":"8","LLAMA_MODELS_DIR":"/srv/models"},"restart":false},true,"Saved.",["/api/models/unused","/api/models/disk"]]', "сохранение каталога: путь обрезан и слит поверх ТЕКУЩЕГО сохранённого конфига, без рестарта; потом перечитывание"),
    ("path_save_empty_is_noop", '', 'await (async () => { await boot(); F().mdlPathInput.value = "   "; await F().mdlPathSave.listeners.click[0](); return calls().length; })()', '0', "negative: пустой путь не сохраняется"),
    ("path_keys_enter_and_escape", '', 'await (async () => { await boot(); let p = 0; F().mdlPathInput.listeners.keydown[0]({ key: "Enter", preventDefault: () => p++ }); F().mdlPathInput.listeners.keydown[0]({ key: "Escape", preventDefault: () => p++ }); return [p, F().mdlPathSave.clicked, F().mdlPathCancel.clicked, F().mdlPathEditRow.hidden]; })()', '[2,1,1,true]', "Enter сохраняет, Escape отменяет, оба события погашены"),
    ("confirm_wiring", '', 'await (async () => { await boot(); let settled = []; globalThis.__stubReturns["dialogs.settleAppConfirm"] = (ok) => settled.push(ok); F().confirmCancel.listeners.click[0](); F().confirmOverlay.listeners.click[0]({ target: { id: "confirmOverlay" } }); F().confirmOverlay.listeners.click[0]({ target: { id: "inner" } }); let ran = 0; st.ui.pendingConfirm = () => ran++; F().confirmDelete.listeners.click[0](); return [settled, ran]; })()', '[[false,false],1]', "проводка общего confirm: отмена и клик по подложке оседают false, клик внутри — нет; кнопка подтверждения зовёт pendingConfirm"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 16:
        print(f"js models-page FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js models-page: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_models_page.tmp.mjs"
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
        print(f"js models-page FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("страница /models: дерево GGUF, сводки, удаление, путь к моделям:")
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
    print(f"js models-page OK: настоящий модуль в node, {len(PINS)} пинов страницы моделей значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
