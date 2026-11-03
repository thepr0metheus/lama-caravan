#!/usr/bin/env python3
"""Snapshot of static/js/models-page.js — the /models page.

The module is the page's entry point: no exports, everything lives inside
the DOMContentLoaded handler. The snapshot intercepts that handler at import
time and fires it itself, then pins by value: the summary tiles (GGUF count,
total size with GB-format thresholds, unused ones — warn/good, disk — warn
below 50 GB), the model → author → quant → files tree with size and
freshness rollups, "largest first" sorting at every level, a file's row (in
use — a ✓ with cell names; not — a checkbox with its path and size), an
empty tree, failures (ok:false and an exception both → text and the page's
error state), counting the selection, deletion only of what's selected and
only after confirmation, changing the models directory — merged on top of
the CURRENT saved config (otherwise /api/config would wipe out everything
else) with restart:false; an empty path is never saved. The neighbours: the
stores panel gets its place, and the move tracker gets the tree, the line by
the button and the button; the tracker reads the libraries off the stores
panel, a new measurement re-labels the button and — only when the libraries
changed — redraws the tree, and an arrived file redraws the tree and
re-measures the stores. What a move says sits on the rows: a travelling file
shows its bar instead of a checkbox and the download buttons; a note from a
finished move sits on its row, the checkbox kept; ⇢ sits at the right edge of
every file and branch that can move (on this disk, unused, not a folder, not
travelling); a folded branch carries its progress. A picked folder says it is
one; the selection survives a redraw.

The DOM is the `globalThis.__fields` dict; `document.querySelectorAll` for a
selector string returns the checkbox list from `globalThis.__boxes`.

Run: python3 scripts/test_js_models_page.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402


def _english():
    """Every one-string line of en.js — expectations quote the page's own words
    instead of a copy of them that can drift."""
    out = {}
    for key, raw in re.findall(r'^  (\w+): (".*"),$', (ROOT / "static/js/i18n/en.js").read_text(encoding="utf-8"), re.M):
        try:
            out[key] = json.loads(raw)
        except ValueError:
            continue
    return out


EN = _english()


def en(key, **kw):
    text = EN[key]
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text

STUBS = ("dialogs,dialog-llamas,polling,canvas,topology-dnd,topology-render,charts,cables,cloud,history,favorites,"
         "config-locator,system-panels,onboarding,onboarding-tours,usage-stats,system-page,memory,command-preview,"
         "llama-edit,remote-cells,topology-nodes,topology-modals,routers,topology-activity,topology-proxies,model-meta,form,"
         "model-stores,model-moves")

PAGE_READS = ["/api/models/unused", "/api/models/freshness", "/api/hf/download/jobs", "/api/model-stores/files", "/api/model-notes",
              "/api/models/rows"]

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
const docListeners = {}; document.addEventListener = (t, fn) => { (docListeners[t] ||= []).push(fn); };
document.body = { dataset: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, appendChild() {}, contains: () => false };
globalThis.__boxes = []; globalThis.__openBranches = [];
globalThis.__scrolled = []; globalThis.scrollY = 0; globalThis.window = globalThis;
globalThis.scrollTo = (x, y) => { globalThis.__scrolled.push(y); globalThis.scrollY = y; };
// Стирание дерева укорачивает страницу, и браузер уводит её наверх. Без этого
// снимок не отличил бы «снял прокрутку до стирания» от «после».
const _wipeScroll = () => { globalThis.scrollY = 0; };
document.querySelectorAll = (sel) => {
  if (sel.startsWith("#mdlTree input[data-del-path]")) return sel.endsWith(":checked") ? globalThis.__boxes.filter((b) => b.checked) : globalThis.__boxes;
  // Раскрытые ветки живут В РАЗМЕТКЕ. Как только дерево стёрто плашкой, их там
  // нет — и заглушка обязана это повторить, иначе снимок пройдёт при коде,
  // который спрашивает уже после стирания (так и было: пин зелёный, страница
  // схлопывается). Заодно исчезает и прокрутка: страница стала короче.
  if (sel.includes("details[open][data-branch]")) {
    const html = String(globalThis.__fields.mdlTree.innerHTML);
    if (!html.includes("<details")) return [];
    // What the markup itself has open (a narrowed list opens everything it
    // keeps), plus what the operator opened since it was drawn.
    const drawn = [...html.matchAll(/data-branch="([^"]*)" open>/g)].map((x) => x[1]);
    return [...new Set([...drawn, ...globalThis.__openBranches])].map((b) => ({ dataset: { branch: b } }));
  }
  return [];
};
await import(pathToFileURL(process.env.JS_ROOT + "/models-page.js").href);
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), has: (c) => s.has(c), toggle: (c, on) => (on === undefined ? (s.has(c) ? s.delete(c) : s.add(c)) : (on ? s.add(c) : s.delete(c))) } };
const mkEl = (onWipe) => ({ textContent: "", _html: "", writes: 0, get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; this.writes += 1; if (onWipe && !String(v).includes("<details")) onWipe(); }, hidden: false, disabled: false, value: "", classList: cls(), listeners: {}, focused: 0, clicked: 0, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, setAttribute() {}, focus() { this.focused += 1; }, click() { this.clicked += 1; (this.listeners.click || []).forEach((fn) => fn({})); }, contains: () => false });
const IDS = ["mdlJobs", "mdlWindows", "mdlTree", "mdlPicked", "mdlDelete", "mdlUnused", "mdlStores", "mdlMovesSum", "mdlMove", "mdlMoveTo", "confirmCancel", "confirmDelete", "confirmOverlay", "mdlSelectAll", "toast", "userChipName", "userChip", "userMenu", "userChipBtn", "userMenuLogout", "mdlFreshCheck", "mdlFreshAuto", "mdlFreshStamp", "mdlFreshGet", "mdlFreshKeep", "mdlFoot", "mdlSummary", "mdlFilters", "mdlSearch"];
const F = () => globalThis.__fields;
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body === null ? null : JSON.parse(c.body) }));
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); };
const FILES = () => [
  { path: "qwen/Qwen/Q4/qwen-q4.gguf", sizeBytes: 4 * 2 ** 30, ageDays: 12, referenced: true,
    referencedBy: ["cell:22001"], readBy: ["cell:22001"] },
  { path: "qwen/Qwen/Q8/qwen-q8.gguf", sizeBytes: 8 * 2 ** 30, ageDays: 3, referenced: false },
  { path: "llama/Meta/Q4/l-q4.gguf", sizeBytes: 2 * 2 ** 30, ageDays: 40, referenced: false },
  { path: "root.gguf", sizeBytes: 0.5 * 2 ** 30, ageDays: 1, referenced: false },
];
const REPLY = (files, extra = {}) => ({ ok: true, path: "/models", files, unusedCount: files.filter((f) => !f.referenced).length, unusedGb: 10.5, ...extra });
// Страница стартует обработчиком DOMContentLoaded: он биндит кнопки и делает первый refresh.
const boot = async (files = FILES(), disk = { ok: true, freeGb: 120 }, fresh = undefined, jobs = undefined) => {
  globalThis.__fetchReply["/api/models/unused"] = REPLY(files); globalThis.__fetchReply["/api/models/disk"] = disk;
  if (fresh !== undefined) globalThis.__fetchReply["/api/models/freshness"] = fresh;
  // Задания приходят С СЕРВЕРА при каждой отрисовке — поэтому то же самое
  // видно и после перезагрузки страницы, и во второй вкладке.
  if (jobs !== undefined) globalThis.__fetchReply["/api/hf/download/jobs"] = jobs;
  for (const fn of docListeners.DOMContentLoaded) await fn(); await settle(); globalThis.__fetchCalls.length = 0;
};
const reset = () => { globalThis.__fields = Object.fromEntries(IDS.map((id) => [id, mkEl(id === "mdlTree" ? _wipeScroll : null)])); globalThis.__boxes = []; globalThis.__openBranches = []; st.ui.pendingConfirm = null;
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = { "/api/auth/me": { enabled: false } }; globalThis.__stubReturns = { "dialogs.appConfirm": async () => true,
  // The stores band is a module of its own; a pin that does not care about it
  // still needs the shape the page talks to.
  "model-stores.mountStores": () => ({ stores: [], render() {}, refresh() {}, holds() {} }) }; };
reset();
// The two columns of what a model does and how long a context it takes (model-facts.js, pinned in
// test_js_model_facts.py and by facts_columns_and_filters here) are empty for a page whose fixtures carry no
// editor rows; the other pins read the tree without those empty cells, as they read it before the columns came.
const EMPTY_FACTS = /<span class="mdl-c-job" data-t="models-row-jobs" data-t-id="[^"]*"><\/span><span class="mdl-c-window" data-t="models-row-window" data-t-id="[^"]*" data-t-state="none"><\/span>/g;
const tree = () => F().mdlTree.innerHTML.replace(EMPTY_FACTS, "");
const box = (path, size, checked) => ({ checked, dataset: { delPath: path, size: String(size) } });
// The move tracker's face as the page uses it; a pin overrides what it needs.
const tracker = (over = {}) => ({ onWay: () => null, rowHtml: () => "", stayedHtml: () => "", branchHtml: () => "", openHtml: () => "",
  storesKey: () => "", syncButton() {}, render() {}, ...over });
// One file's row, from its opening tag to its end: rows hold no nested divs.
const rowOf = (h, name) => { const hit = h.split('<div class="mdl-file').find((s) => s.includes(`>${name}</code>`)); return hit ? '<div class="mdl-file' + hit.split("</div>")[0] + "</div>" : ""; };
// A branch's own row: its <summary>, found by the chain of names.
const branchOf = (h, trail) => { const at = h.indexOf(`data-branch="${trail}"`); return at < 0 ? "" : h.slice(at, h.indexOf("</summary>", at)); };
// A filter's button in the side column.
const filterOf = (id) => { const f = F().mdlFilters.innerHTML; const at = f.indexOf(`data-t-id="${id}"`); return at < 0 ? "" : f.slice(at, f.indexOf("</button>", at)); };
const pressFilter = (id) => F().mdlFilters.listeners.click[0]({ target: { closest: (s) => (s === "[data-filter]" ? { dataset: { filter: id }, disabled: false } : null) } });
const typeName = (text) => { F().mdlSearch.value = text; F().mdlSearch.listeners.input[0]({}); };
// A library listing: one file only there, one moved away from here, one copy
// of a file this disk holds too; a second library that named only part of its files.
const LIBS = () => ({ ok: true, libraries: [
  { id: "lib-a", name: "NAS", state: "ok", more: 0, files: [{ path: "qwen/Qwen/Q5/qwen-q5.gguf", size: 5 * 2 ** 30, ageDays: 20 },
    { path: "moved/X/Q4/x.gguf", size: 20 * 2 ** 30, ageDays: 9 }, { path: "qwen/Qwen/Q8/qwen-q8.gguf", size: 8 * 2 ** 30, ageDays: 3 }] },
  { id: "lib-b", name: "Archive", state: "ok", more: 2, files: [{ path: "old/O/Q2/old.gguf", size: 2 ** 30, ageDays: 400 },
    { path: "qwen/Qwen/Q5/qwen-q5.gguf", size: 6 * 2 ** 30, ageDays: 30 }] }] });
// A places panel that can be steered: the page asks it for `scope`, and a
// choice tells the page through onScope, as the real one does.
const panel = (scope = "all") => { globalThis.__stubReturns["model-stores.mountStores"] = (root, opts) => { globalThis.__storesOpts = opts;
  return (globalThis.__panel = { scope, chosen: [], stores: [{ id: "local", builtin: true }, { id: "lib-a", builtin: false }, { id: "lib-b", builtin: false }],
    render() {}, refresh() {}, holds(x) { globalThis.__held = x; }, choose(s) { this.chosen.push(s); this.scope = s; opts.onScope(s); } }); }; };
const place = (scope) => { globalThis.__panel.scope = scope; globalThis.__storesOpts.onScope(scope); };
const out = {};
// The comments on the models as /api/model-notes answers them; `limit` is the server's own, so that a pin sees the page read it.
const NOTES = (notes = {}, limit = 777) => ({ ok: true, notes, limit, root: "(root)" });
// A button of the comment block pressed: the click reaches the tree's one listener, whichever button it was (attr: noteEdit, noteSave, noteCancel).
const hit = (attr, value = "") => { const sel = "[data-" + attr.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase()) + "]";
  const el = { dataset: { [attr]: value }, disabled: false, closest: (s) => (s === sel ? el : null) }; return el; };
const press = async (attr, value) => { const el = hit(attr, value); await F().mdlTree.listeners.click[0]({ target: el }); await settle(); return el; };
const typeNote = (text) => { const el = { value: text, closest: (s) => (s === "[data-note-input]" ? el : null) }; F().mdlTree.listeners.input[0]({ target: el }); };
const noteBox = () => { const m = /<textarea class="mdl-note-input"[^>]*>([^<]*)<\/textarea>/.exec(tree()); return m ? m[1] : null; };
const idsOf = (h, hook) => [...h.matchAll(new RegExp(`data-t="${hook}" data-t-id="([^"]*)"`, "g"))].map((m) => m[1]);
const textsOf = (h, hook = "models-note") => [...h.matchAll(new RegExp(`<div class="mdl-note" data-t="${hook}" data-t-id="([^"]*)"><span class="mdl-note-mark" aria-hidden="true">[^<]*</span><span class="mdl-note-head">[^<]*</span><span class="mdl-note-text">([^<]*)</span>`, "g"))].map((m) => [m[1], m[2]]);
const chipsOf = (h) => [...h.matchAll(/data-t="models-note-chip" data-t-id="([^"]*)" title="([^"]*)"/g)].map((m) => [m[1], m[2]]);
"""

PINS = [
    # ── What a model does and how long a context it takes (model-facts.js, 1.3.637): the editor's rows, read once more.
    ("facts_columns_and_filters",
     'globalThis.__fetchReply["/api/models/rows"] = { ok: true, models: ['
     '{ path: "qwen/Qwen/Q4/qwen-q4.gguf", kind: "model", detectedFamily: "qwen3", ggufMeta: { contextLength: 32768 } }, '
     '{ path: "qwen/Qwen/Q8/qwen-q8.gguf", kind: "model", detectedFamily: "qwen3", ggufMeta: { contextLength: 262144 } }, '
     '{ path: "llama/Meta/Q4/l-q4.gguf", kind: "model", detectedFamily: "llama3", ggufMeta: { contextLength: 131072 } }, '
     '{ path: "root.gguf", kind: "model", detectedFamily: "embedding", ggufMeta: {} }] };',
     r"""await (async () => { await boot(); const h = F().mdlTree.innerHTML; const nav = F().mdlJobs.innerHTML, win = F().mdlWindows.innerHTML;
       const cell = (hook, id) => { const at = h.indexOf(`data-t="${hook}" data-t-id="${id}"`); return at < 0 ? "" : h.slice(at, h.indexOf("</span>", h.indexOf(">", at) + 1)); };
       const ids = () => [...F().mdlTree.innerHTML.matchAll(/data-t="models-tree-group" data-t-id="([^"]*)"/g)].map((m) => m[1]).filter((x) => !["Qwen", "Meta", "Q4", "Q8", "·"].includes(x));
       const press = (box, attr, value) => box.listeners.click[0]({ target: { closest: (sel) => (sel === `[data-${attr}]` ? { dataset: { [attr.replace(/-([a-z])/g, (m, c) => c.toUpperCase())]: value } } : null) } });
       const head = h.includes('<span class="mdl-c-job">What for</span><span class="mdl-c-window">Context up to</span>');
       const qwenWindow = cell("models-row-window", "qwen"), rootWindow = cell("models-row-window", "(root)");
       const navCounts = [...nav.matchAll(/data-mdl-job="([^"]*)"[^>]*><span aria-hidden="true">[^<]*<\/span><span>[^<]*<\/span><span class="c">(\d+)/g)].map((m) => [m[1], Number(m[2])]);
       const all = ids();
       press(F().mdlJobs, "mdl-job", "embed"); const embedOnly = ids();
       press(F().mdlJobs, "mdl-job", "embed"); const back = ids();
       press(F().mdlWindows, "mdl-window", "131072"); const long = ids();
       press(F().mdlWindows, "mdl-window", "131072");  // the page's choice outlives a pin: taken off for the next ones
       return [head, qwenWindow.includes('data-t-state="known"') && qwenWindow.endsWith("32,768 – 262,144"), rootWindow.includes('data-t-state="unknown"'),
               h.includes('data-job="llm">💬 LLM</span>'), navCounts, win.includes('data-mdl-window="262144"'), all, embedOnly, back, long]; })()""",
     json.dumps([True, True, True, True, [["llm", 3], ["embed", 1]], True, ["qwen", "llama", "(root)"], ["(root)"], ["qwen", "llama", "(root)"], ["qwen", "llama"]]),
     "страница берёт строки редактора: у ветки — работы её моделей и окно (диапазон, когда кванты разные), модель векторов без окна — "
     "«не известен»; слева — работы со счётом и окна; выбор сужает дерево, повторное нажатие снимает его"),
    # ── Download alongside and install: buttons on a file's row.
    ("staged_buttons_appear_only_where_there_is_work", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "size" }, "qwen/Qwen/Q8/qwen-q8.gguf": { state: "same" } } } }, prev: {}, watch: {} }); const h = tree(); return [(h.match(/data-staged-get=/g) || []).length, h.includes(\'data-staged-get="qwen/Qwen/Q4/qwen-q4.gguf"\'), h.includes("data-staged-apply"), h.includes("data-staged-prev")]; })()',
     '[1,true,false,false]',
     'positive: «обновить» только у разошедшегося файла; совпавший кнопки не получает, а ставить и откатывать нечего'),
    ("prev_kept_offers_revert_with_its_size", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "same" } } } }, prev: { "qwen/Qwen/Q4/qwen-q4.gguf": { prev: "/m/qwen-q4.gguf.prev", prevSize: 2 ** 33 } }, watch: {} }); const h = tree(); return [h.includes("data-staged-prev"), h.includes("8.00 GB"), h.includes("data-staged-get")]; })()',
     '[true,true,false]',
     'обновили и всё сходится — откат остаётся, пока лежит прежняя сборка, и рядом её размер: на HF её больше нет, удалять или нет решает оператор'),
    ("no_prev_no_revert", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "size" } } } }, prev: {}, watch: {} }); const h = tree(); return [h.includes("data-staged-prev"), h.includes("data-staged-get")]; })()',
     '[false,true]',
     'negative: сохранения не было — откат не предлагаем, а «обновить» на месте'),
    ("staged_buttons_post_by_path", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "size" } } } }, prev: {}, watch: {} }); const btn = { dataset: { stagedGet: "qwen/Qwen/Q4/qwen-q4.gguf" }, disabled: false, textContent: "", closest: (s) => (s === "[data-staged-get]" ? btn : null) }; const h = (F().mdlTree.listeners.click || [])[0]; await h({ target: btn }); await settle(); return calls().map((c) => [c.path, c.body]); })()',
     json.dumps([["/api/models/staged/download", {"file": "qwen/Qwen/Q4/qwen-q4.gguf"}]] + [[p, None] for p in PAGE_READS]),
     'кнопка шлёт ПУТЬ файла: одно имя лежит в репозитории дважды, и по имени она писала бы в чужую копию. Куда класть и откуда качать, знает отчёт сверки; страница сразу перечитывает себя — без ответа с jobId ждать нечего'),
    ("fetching_a_new_build_asks_what_is_lost",
     'globalThis.__asked = []; globalThis.__answer = false; '
     'globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__asked.push([msg, opts]); return globalThis.__answer; };',
     r"""await (async () => { const report = (keepPrev) => ({ ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "size", remoteSize: 2 ** 33 } } } }, prev: {}, watch: { keepPrev } });
       const press = async () => { const btn = { dataset: { stagedGet: "qwen/Qwen/Q4/qwen-q4.gguf" }, disabled: false, textContent: "fetch new", closest: (s) => (s === "[data-staged-get]" ? btn : null) };
         await F().mdlTree.listeners.click[0]({ target: btn }); await settle(); return btn; };
       await boot(FILES(), { ok: true, freeGb: 120 }, report(false)); const no = await press(); const declined = [calls().length, no.disabled, no.textContent];
       globalThis.__answer = true; await press(); const yes = calls().map((c) => c.path)[0];
       await boot(FILES(), { ok: true, freeGb: 120 }, report(true)); globalThis.__answer = false; await press();
       return [globalThis.__asked[0][0], globalThis.__asked[0][1], declined, yes, globalThis.__asked[2][0], globalThis.__asked[2][1].danger]; })()""",
     json.dumps([en("mdlStagedGetConfirm", name="qwen-q4.gguf", size="8.00 GB") + "\n\n" + EN["mdlStagedGetLost"],
                 {"title": EN["mdlStagedGetTitle"], "confirmLabel": EN["mdlStagedGet"], "danger": True, "scene": "change"},
                 [0, False, "fetch new"], "/api/models/staged/download",
                 en("mdlStagedGetConfirm", name="qwen-q4.gguf", size="8.00 GB") + "\n\n" + EN["mdlStagedGetKept"], False], ensure_ascii=False),
     "«fetch new» пишет поверх файла, с которого работает ячейка, — поэтому сначала вопрос: какой файл, сколько весит новая сборка и что "
     "станет с текущей (не сохраняется — вернуть нельзя, красным; сохраняется как прежняя — можно вернуть); после «да» — запрос; "
     "negative: «нет» — ни запроса, кнопка на месте со своим словом"),
    ("reverting_asks_and_says_what_is_deleted",
     'globalThis.__asked = []; globalThis.__answer = false; '
     'globalThis.__stubReturns["dialogs.appConfirm"] = async (msg, opts) => { globalThis.__asked.push([msg, opts]); return globalThis.__answer; };',
     r"""await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "same" } } } }, prev: { "qwen/Qwen/Q4/qwen-q4.gguf": { prev: "/m/qwen-q4.gguf.prev", prevSize: 2 ** 33 } }, watch: {} });
       const press = async () => { const btn = { dataset: { stagedPrev: "qwen/Qwen/Q4/qwen-q4.gguf" }, disabled: false, textContent: "revert", closest: (s) => (s === "[data-staged-prev]" ? btn : null) };
         await F().mdlTree.listeners.click[0]({ target: btn }); await settle(); return btn; };
       const no = await press(); const declined = [calls().length, no.disabled]; globalThis.__answer = true; await press();
       return [globalThis.__asked[0][0], globalThis.__asked[0][1], declined, calls().map((c) => [c.path, c.body])[0]]; })()""",
     json.dumps([en("mdlStagedPrevConfirm", name="qwen-q4.gguf"),
                 {"title": EN["mdlStagedPrevTitle"], "confirmLabel": EN["mdlStagedPrev"], "danger": True, "scene": "change"},
                 [0, False], ["/api/models/staged/revert", {"file": "qwen/Qwen/Q4/qwen-q4.gguf"}]], ensure_ascii=False),
     "«revert» кладёт сохранённую сборку на место рабочей, и новый файл удаляется — сначала вопрос, который это говорит, красным; после "
     "«да» — запрос по пути; negative: «нет» — ни запроса"),
    ("the_daily_check_has_no_hour", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 0, repos: {}, prev: {}, watch: { check: true, at: "04:30" } }); '
     'globalThis.__fetchReply["/api/models/freshness/watch"] = { ok: true, watch: { check: false, download: false, keepPrev: false } }; '
     'F().mdlFreshAuto.checked = false; (F().mdlFreshAuto.listeners.change || []).forEach((fn) => fn({})); await settle(); '
     'return [calls().filter((c) => c.path === "/api/models/freshness/watch").map((c) => c.body), F().mdlFreshAuto.checked]; })()',
     '[[{"check":false,"download":false,"keepPrev":false}],false]',
     '1.3.678 (владелец, 2026-10-27: «раз в день запускать, если открыли доску»): часа больше нет — настройки едут без него; '
     'negative: «at», пришедший от старого сервера, обратно не уезжает (до 1.3.678 тело несло «at» всегда, пустым — тоже)'),
    ("watch_sends_all_three_levels", '',
     'await (async () => { await boot(); F().mdlFreshKeep.checked = true; (F().mdlFreshKeep.listeners.change || []).forEach((fn) => fn({})); await settle(); return calls().map((c) => c.body); })()',
     '[{"check":false,"download":false,"keepPrev":true}]',
     'галки едут ВМЕСТЕ одним телом — сервер сам включит «смотреть» под «обновлять», и спорить с ним по дороге незачем'),
    # ── Model freshness: the watcher's report is drawn as an icon, and the UNCHECKED stays silent.
    ("freshness_title_says_what_is_known", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { "Qwen/qwen": { files: { '
     '"qwen/Qwen/Q4/qwen-q4.gguf": { state: "size", localSize: 2 ** 34, remoteSize: 2 ** 33, localDate: "2026-08-15", remoteDate: "2026-08-19" }, '
     '"qwen/Qwen/Q8/qwen-q8.gguf": { state: "date", localSize: 2 ** 34, remoteSize: 2 ** 34, localDate: "2026-10-17", remoteDate: "2026-10-19" } } } }, '
     'watch: { check: true } }); return [...tree().matchAll(/class="mdl-fresh newer" title="([^"]*)">⇪</g)].map((m) => m[1]).sort(); })()',
     json.dumps(sorted([en("mdlFreshNewer", ours="16.0 GB · 2026-08-15", theirs="8.00 GB · 2026-08-19"),
                        en("mdlFreshReuploaded", ours="16.0 GB · 2026-10-17", theirs="16.0 GB · 2026-10-19")]), ensure_ascii=False),
     "1.3.679 (2026-10-27: ⇪ на части IQ1_M, совпавшей с HF до байта, говорил «на HF другой файл»): разный размер — другая сборка, так и "
     "сказано; тот же размер и коммит на HF новее — «возможно, перезалит», как на /hf, и что байты сравнит «Verify» на /hf; "
     "negative: про файл с тем же размером не сказано «другой файл»"),
    ("freshness_marks_only_what_differs", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { "Qwen/qwen": { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "size", localSize: 2 ** 34, remoteSize: 2 ** 33, localDate: "2026-08-15", remoteDate: "2026-08-19" }, "qwen/Qwen/Q8/qwen-q8.gguf": { state: "same" }, "llama/Meta/Q4/l-q4.gguf": { state: "unknown" } } } }, watch: { check: false } }); const h = tree(); return [(h.match(/mdl-fresh newer/g) || []).length, (h.match(/mdl-fresh unknown/g) || []).length, h.includes("16.0 GB · 2026-08-15"), h.includes("8.00 GB · 2026-08-19"), (h.match(/⇪ 1</g) || []).length, h.includes(\'data-differs="1"\')]; })()',
     '[4,1,true,true,3,true]',
     'positive: разошедшийся файл получает ⇪, несравнимый — «?», СОВПАВШИЙ не помечается ничем, в подсказке обе пары — и счётчик «⇪ 1» поднимается на ВСЕ ТРИ свёрнутых уровня, иначе значок на файле не виден, пока ветку не раскрыли'),
    # ── Download streams: every file has its own bar, and it comes from the server.
    ("every_download_shows_on_its_own_row", '',
     'await (async () => { const fresh = { ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "size" }, "qwen/Qwen/Q8/qwen-q8.gguf": { state: "size" }, "llama/Meta/Q4/l-q4.gguf": { state: "size" } } } }, prev: {}, watch: {} }; '
     'const jobs = { ok: true, jobs: [ { done: false, status: "running", filePaths: ["qwen/Qwen/Q4/qwen-q4.gguf"], current_path: "qwen/Qwen/Q4/qwen-q4.gguf", current_idx: 0, file_bytes_done: 2 ** 30, file_bytes_total: 4 * 2 ** 30 }, '
     '{ done: false, status: "running", filePaths: ["qwen/Qwen/Q8/qwen-q8.gguf"], current_path: "qwen/Qwen/Q8/qwen-q8.gguf", current_idx: 0, file_bytes_done: 6 * 2 ** 30, file_bytes_total: 8 * 2 ** 30 } ] }; '
     'await boot(FILES(), { ok: true, freeGb: 120 }, fresh, jobs); const h = tree(); '
     'return [(h.match(/data-dl-path=/g) || []).length, h.includes(\'data-dl-path="qwen/Qwen/Q4/qwen-q4.gguf"\'), h.includes("1.00 GB / 4.00 GB · 25%"), h.includes("6.00 GB / 8.00 GB · 75%"), (h.match(/data-staged-get=/g) || []).length, h.includes(\'data-staged-get="llama/Meta/Q4/l-q4.gguf"\')]; })()',
     '[2,true,true,true,1,true]',
     'positive: две загрузки — две полосы, каждая со СВОИМИ байтами на своей строке; у качающихся файлов кнопки «обновить» больше нет, у третьего разошедшегося она на месте (раньше показатель был один на страницу и вторая кнопка стирала первую)'),
    ("downloads_come_from_the_server_so_a_reload_shows_them", '',
     'await (async () => { const jobs = { ok: true, jobs: [{ done: false, status: "running", filePaths: ["qwen/Qwen/Q4/qwen-q4.gguf"], current_path: "qwen/Qwen/Q4/qwen-q4.gguf", current_idx: 0, file_bytes_done: 2 ** 30, file_bytes_total: 4 * 2 ** 30 }] }; '
     'await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: {}, prev: {}, watch: {} }, jobs); const first = tree().includes("1.00 GB / 4.00 GB"); '
     'await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: {}, prev: {}, watch: {} }, jobs); '
     'return [first, tree().includes("1.00 GB / 4.00 GB"), F().mdlFreshStamp.textContent]; })()',
     '[true,true,"downloading… 25%"]',
     'страница не помнит загрузки, а СПРАШИВАЕТ их: после перезагрузки те же полосы, и общий итог в строке отметки вместо времени сверки'),
    ("a_stalled_download_says_so_instead_of_frozen_percent", '',
     'await (async () => { const jobs = { ok: true, jobs: [{ done: false, status: "interrupted", filePaths: ["qwen/Qwen/Q4/qwen-q4.gguf"], current_path: "qwen/Qwen/Q4/qwen-q4.gguf", current_idx: 0, file_bytes_done: 2 ** 30, file_bytes_total: 4 * 2 ** 30 }, '
     '{ done: false, status: "running", filePaths: ["qwen/Qwen/Q8/qwen-q8.gguf", "llama/Meta/Q4/l-q4.gguf"], current_path: "qwen/Qwen/Q8/qwen-q8.gguf", current_idx: 0, file_bytes_done: 1, file_bytes_total: 2 }] }; '
     'await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: {}, prev: {}, watch: {} }, jobs); const h = tree(); '
     'return [h.includes("interrupted"), (h.match(/mdl-dl stalled/g) || []).length, h.includes("queued"), h.includes("· 25%"), h.includes("width:25%")]; })()',
     '[true,1,true,false,true]',
     'negative: прервано — своё СЛОВО вместо процентов в тексте и свой цвет; полоса при этом честно стоит на достигнутых 25 % (докачали столько, и это факт); файл, ждущий очереди в том же задании, назван очередью, а не нулевым прогрессом'),
    ("a_finished_download_leaves_no_button_behind", '',
     'await (async () => { const jobs = { ok: true, jobs: [{ done: true, status: "done", filePaths: ["qwen/Qwen/Q4/qwen-q4.gguf"], current_path: "qwen/Qwen/Q4/qwen-q4.gguf", current_idx: 0, file_bytes_done: 4 * 2 ** 30, file_bytes_total: 4 * 2 ** 30 }] }; '
     'await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "same" } } } }, prev: {}, watch: {} }, jobs); const h = tree(); '
     'return [h.includes("data-dl-path"), h.includes("data-staged-get"), h.includes("mdl-fresh")]; })()',
     '[false,false,false]',
     'скачалось и сошлось — ни полосы, ни кнопки, ни значка: предложить обновить то, что только что обновили, значит соврать (сервер меряет локальную сторону при каждом чтении, поэтому вердикт свежий без новой сверки)'),
    ("open_branches_survive_the_redraw", '',
     'await (async () => { await boot(); const shut = tree().includes("<details"); const closed = (tree().match(/ open>/g) || []).length; '
     'globalThis.__openBranches = ["qwen/Qwen/Q4", "llama"]; await boot(); const h = tree(); '
     'return [shut, closed, (h.match(/ open>/g) || []).length, h.includes(\'data-branch="qwen/Qwen/Q4" open\'), h.includes(\'data-branch="qwen/Qwen" open\')]; })()',
     '[true,0,2,true,false]',
     'дерево перерисовывается целиком после каждого действия — и раскрытые ветки обязаны пережить это, иначе нажатая в глубине кнопка схлопывает всё вместе с полосой, ради которой её нажали; ключ — цепочка от корня, поэтому раскрывается ровно названная ветка, а не одноимённая соседка'),
    ("the_summary_counts_all_streams_together", '',
     'await (async () => { const jobs = { ok: true, jobs: [ { done: false, status: "running", filePaths: ["qwen/Qwen/Q4/qwen-q4.gguf"], current_path: "qwen/Qwen/Q4/qwen-q4.gguf", current_idx: 0, file_bytes_done: 2 ** 30, file_bytes_total: 4 * 2 ** 30 }, '
     '{ done: false, status: "running", filePaths: ["qwen/Qwen/Q8/qwen-q8.gguf"], current_path: "qwen/Qwen/Q8/qwen-q8.gguf", current_idx: 0, file_bytes_done: 6 * 2 ** 30, file_bytes_total: 8 * 2 ** 30 } ] }; '
     'await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: {}, prev: {}, watch: {} }, jobs); return F().mdlFreshStamp.textContent; })()',
     '"downloading… 58%"',
     'итог — по ВСЕМ потокам вместе (7 из 12 ГБ), а не по одному из них; считается там же, где обновляются полосы, поэтому не отстаёт от них'),
    ("the_page_keeps_its_place_across_a_redraw", '',
     'await (async () => { globalThis.scrollY = 0; globalThis.__scrolled.length = 0; await boot(); const atTop = globalThis.__scrolled.length; '
     'globalThis.scrollY = 640; globalThis.__scrolled.length = 0; await boot(); const moved = globalThis.__scrolled; '
     'return [atTop, moved.length > 0, [...new Set(moved)]]; })()',
     '[0,true,[640]]',
     'дерево пересобирается целиком и на миг становится ниже — браузер увёл бы страницу в шапку; позиция восстанавливается, а из нулевой прокрутки никто никуда не прыгает'),
    ("the_list_pane_keeps_its_place_across_a_redraw", '',
     'await (async () => { const was = document.querySelector; let written = []; '
     'const pane = (top) => ({ get scrollTop() { return top; }, set scrollTop(v) { written.push(v); top = v; } }); '
     'document.querySelector = (sel) => (sel === ".mdl-main" ? pane(640) : was?.call(document, sel)); await boot(); const scrolled = [...written]; written = []; '
     'document.querySelector = (sel) => (sel === ".mdl-main" ? pane(0) : was?.call(document, sel)); await boot(); const atTop = [...written]; '
     'document.querySelector = was; await boot(); return [scrolled, atTop]; })()',
     '[[640],[]]',
     'на широком экране список прокручивается в своей панели: она и держит место через перерисовку; negative: панель наверху не трогается, панели нет — ничего не падает'),
    ("one_name_two_copies_one_verdict_each", '',
     'await (async () => { const files = [{ path: "M/A/Q5_K_M/dup.gguf", sizeBytes: 2 ** 30, ageDays: 5, referenced: false }, { path: "M/A/default/dup.gguf", sizeBytes: 2 ** 30, ageDays: 9, referenced: false }]; '
     'await boot(files, { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { "A/M": { files: { "M/A/Q5_K_M/dup.gguf": { state: "size" } } } }, prev: {}, watch: {} }); const h = tree(); '
     'return [(h.match(/mdl-fresh newer/g) || []).length, (h.match(/⇪ 1</g) || []).length, (h.match(/⇪ 2</g) || []).length, h.includes(\'data-staged-get="M/A/Q5_K_M/dup.gguf"\'), h.includes(\'data-staged-get="M/A/default/dup.gguf"\')]; })()',
     '[4,3,0,true,false]',
     'одно имя в двух квантах: значок и кнопка достаются ТОЙ копии, которая сверялась, счётчик наверху говорит «1», а не «2» — по имени дерево насчитывало 11 расхождений против 10 в отчёте (найдено живой проверкой 2026-09-07)'),
    ("freshness_silent_when_never_checked", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 0, repos: {}, watch: { check: false } }); return [tree().includes("mdl-fresh"), F().mdlFreshStamp.textContent]; })()',
     '[false,"never checked"]',
     'negative: не проверяли — ни одного значка, и сказано прямо, а не молчанием'),
    ("freshness_survives_missing_endpoint", '',
     'await (async () => { globalThis.__fetchReply["/api/models/freshness"] = { __status: 500, error: "boom" }; await boot(); return [tree().includes("mdl-fresh"), document.body.dataset.tState, tree().includes("qwen-q4.gguf")]; })()',
     '[false,"ready","true"]'.replace('"true"', 'true'),
     'отчёт не отдался — страница живёт дальше и просто молчит про свежесть'),
    ("freshness_stamp_counts_checked_only", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { a: { files: { "qwen/Qwen/Q4/qwen-q4.gguf": { state: "size" }, "qwen/Qwen/Q8/qwen-q8.gguf": { state: "same" } } }, b: { error: "404", files: {} } }, watch: { check: true } }); return [F().mdlFreshStamp.textContent.includes("1 of 2 differ"), F().mdlFreshAuto.checked]; })()',
     '[true,true]',
     'знаменатель — СВЕРЕННЫЕ файлы: недостучавшийся репозиторий не растворяется в общем числе; галка показывает сохранённое'),
    ("freshness_button_and_checkbox_talk_to_the_server", '',
     'await (async () => { await boot(); F().mdlFreshCheck.click(); await settle(); const a = calls().map((c) => c.path); globalThis.__fetchCalls.length = 0; F().mdlFreshAuto.checked = true; (F().mdlFreshAuto.listeners.change || []).forEach((fn) => fn({})); await settle(); return [a.includes("/api/models/freshness/check"), calls().map((c) => [c.path, c.body])]; })()',
     '[true,[["/api/models/freshness/watch",{"check":true,"download":false,"keepPrev":false}]]]',
     'кнопка просит проверку; три галки уезжают ОДНИМ телом — сервер сам делает нижние обязательными для верхних'),
    ("the_unused_line_is_the_reason_for_the_buttons", '',
     r"""await (async () => { await boot(); const idle = [F().mdlUnused.textContent, F().mdlUnused.classList.has("warn")];
       await boot([{ path: "a/b/c/d.gguf", sizeBytes: 2 ** 30, ageDays: 1, referenced: true, referencedBy: ["x"], readBy: ["x"] }]);
       return [idle, F().mdlUnused.textContent, F().mdlUnused.classList.has("warn")]; })()""",
     json.dumps([[en("mdlUnusedLine", n=3, size="10.5 GB"), True], EN["mdlUnusedNone"], False], ensure_ascii=False),
     "над деревом — одна строка про то, ради чего страница: сколько лежит без дела, предупреждающим тоном; "
     "ничего лишнего нет — обычным. Плиток с цифрами больше нет: свободное место и счёт каждого хранилища "
     "стоят на его собственной строке, а раньше тот же диск отвечал дважды разными словами"),
    ("saving_the_models_directory_is_the_pages_business",
     'globalThis.__fetchReply["/api/state"] = { config: { MODEL_FILE: "x.gguf", THREADS: "8" } };'
     ' globalThis.__stubReturns["model-stores.mountStores"] = (root, opts) => { globalThis.__storesOpts = opts; return { stores: [], render() {}, refresh() {}, holds() {} }; };',
     r"""await (async () => { await boot(); await globalThis.__storesOpts.onSavePath("/srv/models"); await settle();
       const c = calls(); return [c[0].path, c[1].path, c[1].body, F().toast.textContent, c.slice(2).map((x) => x.path)]; })()""",
     json.dumps(["/api/state", "/api/config", {"config": {"MODEL_FILE": "x.gguf", "THREADS": "8", "LLAMA_MODELS_DIR": "/srv/models"}, "restart": False},
                 "Saved.", PAGE_READS]),
     "каталог моделей правится в сводке своего диска, а страница отвечает за то, ЧТО значит сохранить: "
     "путь сливается поверх ТЕКУЩЕГО сохранённого конфига (POST /api/config заменяет его целиком), без рестарта, "
     "и потом всё перечитывается"),
    ("the_stores_band_is_told_what_this_disk_holds",
     'panel(); globalThis.__fetchReply["/api/model-stores/files"] = LIBS();',
     'await (async () => { await boot(); return globalThis.__held; })()',
     '{"files":4,"size":15569256448,"families":{"all":5,"local":3,"lib-a":2,"lib-b":2}}',
     "панель мест получает счёт этого диска от страницы: дерево уже посчитало те же файлы, "
     "и мерить их второй раз значило бы завести второе число, которое может разойтись с первым; "
     "заодно — сколько семейств у каждого места (семейство — верхняя папка дерева; копия файла считается в обоих местах)"),
    ("tree_grouping_and_rollups", '',
     r"""await (async () => { await boot(); const h = tree(); return [h.includes('data-t="models-tree-group" data-t-id="qwen"'),
       branchOf(h, "qwen").includes('<span class="mdl-name">qwen</span><a class="mdl-tree-hf" href="/hf?q=qwen" data-t="models-hf-open" data-t-id="qwen" title="Find this model on Hugging Face" aria-label="Find this model on Hugging Face">🤗</a></span><span class="mdl-c-status"></span><span class="mdl-c-size here">12.0 GB</span><span class="mdl-c-size lib"><span class="mdl-dim">—</span></span><span class="mdl-c-age">3d</span>'),
       branchOf(h, "qwen/Qwen/Q8").includes('<span class="mdl-c-size here">8.00 GB</span>'), branchOf(h, "qwen/Qwen/Q8").includes('<span class="mdl-c-age">3d</span>'),
       h.includes('data-t-id="(root)"'), h.includes('mdl-name">·</span>'), (h.match(/<details/g) || []).length,
       h.startsWith('<div class="mdl-row mdl-head" data-t="models-tree-head">'), branchOf(h, "qwen/Qwen").includes('style="--lvl:1"'), rowOf(h, "qwen-q8.gguf").includes('style="--lvl:3"')]; })()""",
     '[true,true,true,true,true,true,10,true,true,true]',
     "дерево — колонками под заголовком: у модели объём здесь, прочерк в библиотеке и свежесть (самый свежий файл внутри); квант с двумя "
     "десятичными до 10 GB; файл в корне — (root) с «·» уровнями; 3 модели × 3 уровня + 1; вложенность — отступ в колонке имени, а не сдвиг строки"),
    ("branches_lead_to_hugging_face", '',
     r"""await (async () => { const files = [...FILES(), { path: "models--facebook--nllb/snap/x.gguf", sizeBytes: 5, ageDays: 1, referenced: false },
         { path: "gemma/default/Q4/g.gguf", sizeBytes: 5, ageDays: 1, referenced: false }]; await boot(files); const h = tree();
       const links = [...h.matchAll(/<a class="mdl-tree-hf" href="([^"]*)" data-t="models-hf-open" data-t-id="([^"]*)" title="([^"]*)"/g)].map((m) => [m[1], m[2], m[3]]).sort((a, b) => (a[1] < b[1] ? -1 : 1));
       const inBranch = (trail) => branchOf(h, trail).includes('data-t="models-hf-open"');
       return [links, inBranch("qwen/Qwen/Q8"), inBranch("(root)"), inBranch("(root)/·"), inBranch("models--facebook--nllb/snap"), inBranch("gemma/default")]; })()""",
     '[[["/hf?q=Meta%2Fllama","Meta/llama","Open this repository on Hugging Face"],["/hf?q=Qwen%2Fqwen","Qwen/qwen","Open this repository on Hugging Face"],'
     '["/hf?q=gemma","gemma","Find this model on Hugging Face"],["/hf?q=llama","llama","Find this model on Hugging Face"],["/hf?q=qwen","qwen","Find this model on Hugging Face"]],false,false,false,false,false]',
     "дорога на Hugging Face: ветка автора — это репозиторий, 🤗 открывает его на /hf; ветка модели ищет по имени (все авторы); у кванта, (root), «·», кэша models-- и автора default ссылки нет"),

    ("a_link_opens_the_page_on_a_model", '',
     r"""await (async () => { globalThis.location.search = "?q=qwen%2FQwen%2FQ8%2F"; try { await boot(); } finally { globalThis.location.search = ""; }
       const h = tree(); const named = [h.includes("qwen-q8.gguf"), h.includes("qwen-q4.gguf"), h.includes("l-q4.gguf"), h.includes("root.gguf")];
       const box = F().mdlSearch.value; await boot(); const again = tree();
       return [box, named, F().mdlSearch.value, again.includes("l-q4.gguf")]; })()""",
     '["qwen/Qwen/Q8/",[true,false,false,false],"",true]',
     "1.3.660 (владелец, 2026-10-26: «ссылку на модель в нашем хранилище»): ссылка окна ячейки `?q=` открывает страницу уже суженной "
     "до папки кванта модели, и поле поиска говорит, по чему; negative: другие файлы не видны; без `?q=` — весь список и пустое поле"),
    ("tree_largest_first_every_level", '', 'await (async () => { await boot(); const h = tree(); const i = (s) => h.indexOf(s); return [i(\'data-t-id="qwen"\') < i(\'data-t-id="llama"\'), i(\'data-t-id="llama"\') < i(\'data-t-id="(root)"\'), i(\'data-t-id="Q8"\') < i(\'data-t-id="Q4"\')]; })()', '[true,true,true]', "крупные первыми на каждом уровне: модели, кванты"),
    ("file_rows_used_and_deletable", '',
     r"""await (async () => { await boot(); const h = tree(); const used = rowOf(h, "qwen-q4.gguf"), free = rowOf(h, "qwen-q8.gguf"); return [
       used.includes('<span class="mdl-nobox"></span><code title="qwen/Qwen/Q4/qwen-q4.gguf">qwen-q4.gguf</code></span><span class="mdl-c-status"><span class="mdl-used" title="cell:22001">✓ cell:22001</span>'),
       used.includes("data-del-path"),
       free.includes('aria-label="qwen/Qwen/Q8/qwen-q8.gguf" data-t="models-model-select" data-t-id="qwen/Qwen/Q8/qwen-q8.gguf" data-del-path="qwen/Qwen/Q8/qwen-q8.gguf" data-size="8589934592"'),
       (h.match(/data-del-path=/g) || []).length,
       free.includes('<span class="mdl-c-size here">8.00 GB</span><span class="mdl-c-size lib"><span class="mdl-dim">—</span></span><span class="mdl-c-age">3d</span>'),
       rowOf(h, "root.gguf").includes('<span class="mdl-c-size here">0.50 GB</span>')]; })()""",
     '[true,false,true,3,true,true]',
     "строка файла: используемый — пустое место вместо чекбокса и ✓ с ячейками в колонке состояния; неиспользуемый — чекбокс с путём (не именем) "
     "и размером; размер и возраст — в своих колонках"),
    ("tree_empty", '', 'await (async () => { await boot([]); return [tree().includes("Nothing unused"), F().mdlDelete.disabled, F().mdlPicked.textContent, document.body.dataset.tState]; })()', '[true,true,"","ready"]', "пустой каталог — подсказка, удаление выключено, страница ready"),
    ("refresh_not_ok_and_throw", '', 'await (async () => { globalThis.__fetchReply["/api/models/unused"] = { ok: false, error: "no such dir" }; for (const fn of docListeners.DOMContentLoaded) await fn(); await settle(); const a = [tree().includes("no such dir"), document.body.dataset.tState]; globalThis.__fetchReply["/api/models/unused"] = { __status: 500, error: "boom" }; for (const fn of docListeners.DOMContentLoaded) await fn(); await settle(); return [...a, tree().includes("boom"), document.body.dataset.tState]; })()',
     '[true,"error",true,"error"]', "negative: ok:false и исключение — текст в дереве и состояние error (страница честно говорит, что не загрузилась)"),
    ("picked_counter", '', 'await (async () => { await boot(); globalThis.__boxes = [box("a", 2 ** 30, true), box("b", 3 * 2 ** 30, true), box("c", 2 ** 30, false)]; F().mdlTree.listeners.change[0](); return [F().mdlPicked.textContent, F().mdlDelete.disabled]; })()', '["2 · 4.00 GB",false]', "счётчик выбранного: число и объём отмеченных; кнопка удаления включена"),
    ("select_all", '', 'await (async () => { await boot(); globalThis.__boxes = [box("a", 2 ** 30, false), box("b", 2 ** 30, false)]; F().mdlSelectAll.listeners.click[0](); return [globalThis.__boxes.every((b) => b.checked), F().mdlPicked.textContent]; })()', '[true,"2 · 2.00 GB"]', "«выбрать всё» отмечает все чекбоксы и пересчитывает"),
    ("delete_nothing_selected", '', 'await (async () => { await boot(); await F().mdlDelete.listeners.click[0](); return calls().length; })()', '0', "negative: ничего не выбрано — ни запроса"),
    ("delete_refused_by_confirm", '', 'await (async () => { await boot(); globalThis.__boxes = [box("a/b", 2 ** 30, true)]; globalThis.__stubReturns["dialogs.appConfirm"] = async () => false; await F().mdlDelete.listeners.click[0](); return calls().length; })()', '0', "negative: отказ подтверждения — ни запроса"),
    ("delete_selected_posts_and_refreshes", 'globalThis.__fetchReply["/api/models/gc"] = { ok: true, freedGb: 9 };', 'await (async () => { await boot(); globalThis.__boxes = [box("qwen/Qwen/Q8/qwen-q8.gguf", 8 * 2 ** 30, true), box("root.gguf", 1, false)]; await F().mdlDelete.listeners.click[0](); await settle(); const c = calls(); return [c[0].path, c[0].body, F().toast.textContent, c.slice(1).map((x) => x.path), F().mdlDelete.disabled]; })()',
     json.dumps(["/api/models/gc", {"files": ["qwen/Qwen/Q8/qwen-q8.gguf"]}, "9 GB freed", PAGE_READS, False]), "удаление: POST только отмеченных путей, тост, перечитывание, кнопка снова включена"),
    ("confirm_wiring", '', 'await (async () => { await boot(); let settled = []; globalThis.__stubReturns["dialogs.settleAppConfirm"] = (ok) => settled.push(ok); F().confirmCancel.listeners.click[0](); F().confirmOverlay.listeners.click[0]({ target: { id: "confirmOverlay" } }); F().confirmOverlay.listeners.click[0]({ target: { id: "inner" } }); let ran = 0; st.ui.pendingConfirm = () => ran++; F().confirmDelete.listeners.click[0](); return [settled, ran]; })()', '[[false,false],1]', "проводка общего confirm: отмена и клик по подложке оседают false, клик внутри — нет; кнопка подтверждения зовёт pendingConfirm"),
    ("stores_panel_gets_its_place", 'globalThis.__stubReturns["model-stores.mountStores"] = (root) => { globalThis.__mountedInto = root; return { render() {}, refresh() {}, holds() {}, stores: [] }; };',
     'await (async () => { globalThis.__mountedInto = undefined; await boot(); return [globalThis.__mountedInto === F().mdlStores, !!F().mdlStores]; })()', '[true,true]',
     "панель хранилищ получает свой #mdlStores — и только его: свои данные она берёт сама, а перечитывания страницы (пины выше пересчитывают их запросы поштучно) её не касаются"),
    ("moves_get_the_tree_the_line_and_the_button",
     'globalThis.__movesOpts = null; globalThis.__storesOpts = null; globalThis.__syncs = 0; globalThis.__storeRefreshes = []; globalThis.__libKey = ""; '
     'globalThis.__stubReturns["model-moves.mountMoves"] = (opts) => { globalThis.__movesOpts = opts; return tracker({ storesKey: () => globalThis.__libKey, syncButton() { globalThis.__syncs += 1; } }); }; '
     'globalThis.__stubReturns["model-stores.mountStores"] = (root, opts) => { globalThis.__storesOpts = opts; return { render() {}, holds() {}, stores: [{ id: "lib-a" }], refresh(force) { globalThis.__storeRefreshes.push(force); } }; };',
     r"""await (async () => { await boot(); const o = globalThis.__movesOpts; const before = globalThis.__syncs; globalThis.__storesOpts.onChange(); await settle();
       const same = [globalThis.__syncs - before, calls().length]; globalThis.__libKey = "lib-a:NAS"; globalThis.__storesOpts.onChange(); await settle(); const fresh = calls().map((c) => c.path);
       globalThis.__fetchCalls.length = 0; globalThis.__storesOpts.onChange(); await settle(); const again = calls().length;
       o.onChange(); await settle();
       return [o.tree === F().mdlTree, o.summary === F().mdlMovesSum, o.button === F().mdlMove, o.select === F().mdlMoveTo, o.stores().map((s) => s.id), same, fresh, again, calls().map((c) => c.path), globalThis.__storeRefreshes]; })()""",
     json.dumps([True, True, True, True, ["lib-a"], [1, 0], PAGE_READS, 0, PAGE_READS, [True]]),
     "трекер переносов получает дерево, строку у кнопки, кнопку и выбор библиотеки; библиотеки берёт у панели хранилищ; новый замер пересчитывает кнопку, а дерево перерисовывает, только если состав библиотек изменился (иначе ⇢ предлагали бы старые); приехавший файл перерисовывает дерево и заново меряет хранилища"),
    ("a_travelling_file_shows_its_bar_instead_of_a_checkbox",
     'globalThis.__stubReturns["model-moves.mountMoves"] = () => tracker({ onWay: (p) => (p === "qwen/Qwen/Q8/qwen-q8.gguf" ? { job: {}, row: {} } : null), '
     'rowHtml: (p) => `<i data-bar="${p}"></i>`, openHtml: (s, v) => `<b data-open="${s}:${v}"></b>`, stayedHtml: () => "<i data-note></i>" });',
     r"""await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q8/qwen-q8.gguf": { state: "size" } } } }, prev: {}, watch: {} }); const h = tree();
       const row = rowOf(h, "qwen-q8.gguf");
       return [row.includes('<span class="mdl-c-status"><span class="mdl-fresh newer"'), row.includes('<i data-bar="qwen/Qwen/Q8/qwen-q8.gguf"></i>'), row.includes("data-del-path"), row.includes("data-staged-get"), row.includes("data-open="), row.includes("data-note"), (h.match(/data-del-path=/g) || []).length]; })()""",
     '[true,true,false,false,false,false,2]',
     "файл в пути — на его строке полоса переноса вместо чекбокса и кнопок загрузки (удалить, обновить или перенести второй раз посреди переноса нельзя), без ⇢ и без старой пометки; остальные неиспользуемые — с чекбоксами"),
    ("a_stopped_cells_model_can_still_move",
     'globalThis.__stubReturns["model-moves.mountMoves"] = () => tracker({ openHtml: (s, v) => `<b data-open="${s}:${v}"></b>` });',
     r"""await (async () => { const files = [...FILES(), { path: "parked/P/Q4/p.gguf", sizeBytes: 2 ** 30, ageDays: 5, referenced: true, referencedBy: ["cell:22002"], readBy: [] }];
       await boot(files); const h = tree(); const row = (name) => rowOf(h, name);
       return [row("p.gguf").includes('data-open="file:parked/P/Q4/p.gguf"'), row("p.gguf").includes("data-del-path"),
               row("p.gguf").includes('class="mdl-used parked"'), (row("p.gguf").match(/class="mdl-used parked" title="([^"]*)"/) || [])[1],
               row("qwen-q4.gguf").includes("data-open="), row("qwen-q4.gguf").includes('class="mdl-used"')]; })()""",
     json.dumps([True, False, True, EN["mdlUsedStopped"].replace("{names}", "cell:22002"), False, True], ensure_ascii=False),
     "модель ОСТАНОВЛЕННОЙ ячейки: ⇢ есть (перенос вернётся при старте), чекбокса нет (удаление ячейку сломает), "
     "а ✓ приглушён и говорит почему; модель ЗАПУЩЕННОЙ ячейки ⇢ не получает"),
    ("the_arrow_sits_where_a_file_can_move",
     'globalThis.__stubReturns["model-moves.mountMoves"] = () => tracker({ openHtml: (s, v) => `<b data-open="${s}:${v}"></b>` }); '
     'globalThis.__fetchReply["/api/model-stores/files"] = { ok: true, libraries: [{ id: "lib-a", name: "NAS", state: "ok", more: 0, files: [{ path: "moved/X/Q4/x.gguf", size: 2 ** 30, ageDays: 9 }] }] };',
     r"""await (async () => { const files = [...FILES(), { path: "whisper/models--x", kind: "whisper", sizeBytes: 5, ageDays: 2, referenced: false }]; await boot(files); const h = tree();
       return [[...h.matchAll(/data-open="([^"]+)"/g)].map((x) => x[1]).sort(), h.includes('<span class="mdl-c-age">3d</span><span class="mdl-c-go"><b data-open="file:qwen/Qwen/Q8/qwen-q8.gguf"></b></span></div>')]; })()""",
     json.dumps([sorted(["file:qwen/Qwen/Q8/qwen-q8.gguf", "file:llama/Meta/Q4/l-q4.gguf", "file:root.gguf", "file:moved/X/Q4/x.gguf",
                         "file:whisper/models--x", "branch:whisper", "branch:whisper/·", "branch:whisper/·/·",
                         "branch:qwen", "branch:qwen/Qwen", "branch:qwen/Qwen/Q8", "branch:llama", "branch:llama/Meta", "branch:llama/Meta/Q4",
                         "branch:(root)", "branch:(root)/·", "branch:(root)/·/·"]), True], ensure_ascii=False),
     "⇢ стоит у каждого предмета, который можно перенести, и у каждой ветки с такими предметами — в последней колонке строки: у файлов и ПАПОК этого диска (не занятых) и у файла из библиотеки, которому есть куда ехать; занятый файл и ветка только из занятых ⇢ не получают"),
    ("a_library_row_can_move_too",
     'globalThis.__stubReturns["model-moves.mountMoves"] = () => tracker({ openHtml: (s, v, it = {}) => `<b data-open="${s}:${v}:${it.from}:${it.kind || ""}"></b>`, '
     'onWay: (p) => (p === "moved/X/Q4/x.gguf" ? { job: {}, row: {} } : null), rowHtml: (p) => `<i data-bar="${p}"></i>` }); '
     'globalThis.__fetchReply["/api/model-stores/files"] = { ok: true, libraries: [{ id: "lib-a", name: "NAS", state: "ok", more: 0, files: ['
     '{ path: "qwen/Qwen/Q5/qwen-q5.gguf", size: 5 * 2 ** 30, ageDays: 20 }, { path: "moved/X/Q4/x.gguf", size: 2 * 2 ** 30, ageDays: 9 }, '
     '{ path: "whisper/models--gone", kind: "whisper", size: 3 * 2 ** 30, ageDays: 4 }] }] };',
     r"""await (async () => { await boot(); const h = tree(); const row = (name) => rowOf(h, name);
       return [row("qwen-q5.gguf").includes('<b data-open="file:qwen/Qwen/Q5/qwen-q5.gguf:lib-a:"></b>'), row("qwen-q5.gguf").includes("data-bar"),
               row("x.gguf").includes('<i data-bar="moved/X/Q4/x.gguf"></i>'), row("x.gguf").includes("data-open"),
               row("models--gone").includes('<b data-open="file:whisper/models--gone:lib-a:whisper"></b>'),
               row("models--gone").includes('title="A whole folder (whisper): it is moved and deleted as one item, with everything inside it.">📁</span>')]; })()""",
     '[true,false,true,false,true,true]',
     "строка библиотеки тоже переносится: её ⇢ несёт хранилище как «откуда» — обратно на этот диск или в другую библиотеку; пока файл едет, на строке та же полоса, и ⇢ нет; папка-модель в библиотеке — такая же строка с 📁, и её ⇢ несёт вид: она вернётся целиком"),
    ("a_note_from_a_finished_move_sits_on_the_row",
     'globalThis.__stubReturns["model-moves.mountMoves"] = () => tracker({ stayedHtml: (p) => (p === "llama/Meta/Q4/l-q4.gguf" ? "<i data-note></i>" : "") });',
     r"""await (async () => { await boot(); const h = tree(); return [rowOf(h, "l-q4.gguf").includes('<i data-note></i></span><span class="mdl-c-size here">2.00 GB</span>'), h.includes('data-del-path="llama/Meta/Q4/l-q4.gguf"'), (h.match(/data-note/g) || []).length]; })()""",
     '[true,true,1]',
     "пометка законченного переноса стоит в колонке состояния строки своего файла, перед размерами; чекбокс остаётся — файл здесь, с ним можно работать"),
    ("a_folded_branch_carries_its_progress",
     'globalThis.__stubReturns["model-moves.mountMoves"] = () => tracker({ branchHtml: (trail) => (trail === "qwen/Qwen" ? `<i data-branch-bar="${trail}"></i>` : "") });',
     r"""await (async () => { await boot(); const h = tree(); return [h.includes('<span class="mdl-name">Qwen</span><a class="mdl-tree-hf" href="/hf?q=Qwen%2Fqwen" data-t="models-hf-open" data-t-id="Qwen/qwen" title="Open this repository on Hugging Face" aria-label="Open this repository on Hugging Face">🤗</a></span><span class="mdl-c-status"><i data-branch-bar="qwen/Qwen"></i></span>'), (h.match(/data-branch-bar/g) || []).length]; })()""",
     '[true,1]',
     "свёрнутая ветка несёт свой прогресс в колонке состояния: ключ — цепочка от корня, поэтому чип попадает ровно на свою ветку"),
    ("picking_tells_the_move_button_and_folders_say_so",
     'globalThis.__syncs = 0; globalThis.__stubReturns["model-moves.mountMoves"] = (opts) => { globalThis.__movesOpts = opts; return tracker({ syncButton() { globalThis.__syncs += 1; } }); };',
     r"""await (async () => { const files = [...FILES(), { path: "whisper/models--x", kind: "whisper", sizeBytes: 5, ageDays: 2, referenced: false }]; await boot(files); const h = tree();
       const marked = h.includes('data-del-path="whisper/models--x" data-size="5" data-kind="whisper"');
       const chip = h.includes('<span class="mdl-kind" data-t="models-folder-item" data-t-id="whisper/models--x" title="A whole folder (whisper): it is moved and deleted as one item, with everything inside it.">📁</span>');
       globalThis.__boxes = [box("a.gguf", 2 ** 30, true), { checked: true, dataset: { delPath: "whisper/models--x", size: "5", kind: "whisper" } }]; const before = globalThis.__syncs; F().mdlTree.listeners.change[0]();
       return [marked, chip, (h.match(/mdl-kind/g) || []).length, globalThis.__syncs - before, globalThis.__movesOpts.picked()]; })()""",
     '[true,true,1,1,[{"path":"a.gguf","size":1073741824,"kind":""},{"path":"whisper/models--x","size":5,"kind":"whisper"}]]',
     "выбор меняется — кнопка переноса пересчитывается; папка (кэш HF, safetensors) названа папкой и в разметке, и значком 📁, и в выборе — её переносят и удаляют целиком; обычный файл значка не получает"),
    ("the_tree_stays_while_a_refresh_waits",
     'globalThis.__stubReturns["model-moves.mountMoves"] = (opts) => { globalThis.__movesOpts = opts; return tracker(); };',
     r"""await (async () => { await boot(); const before = tree();
       let release; const gate = new Promise((r) => { release = r; }); const plain = globalThis.fetch;
       globalThis.fetch = async (path, o) => { if (String(path) === "/api/models/unused") await gate; return plain(path, o); };
       try {
         globalThis.__movesOpts.onChange(); await settle();
         const during = tree(); release(); await settle();
         return [before.includes("<details"), during === before, tree().includes("<details")];
       } finally { globalThis.fetch = plain; } })()""",
     '[true,true,true]',
     "пока новый ответ в пути, дерево остаётся на экране: раньше оно стиралось в «…» ДО запросов, а перенос "
     "перерисовывает дерево на каждом приехавшем файле, пока библиотеку меряют по сети, занятой этой же копией — "
     "живьём на месте семидесяти моделей висело «…», сколько отвечал NAS"),
    ("an_older_answer_does_not_paint_over_a_newer_one",
     'globalThis.__stubReturns["model-moves.mountMoves"] = (opts) => { globalThis.__movesOpts = opts; return tracker(); };',
     r"""await (async () => { await boot();
       let release; const gate = new Promise((r) => { release = r; }); const plain = globalThis.fetch; let held = false;
       const old = REPLY([{ path: "stale/S/Q4/stale.gguf", sizeBytes: 2 ** 30, ageDays: 1, referenced: false }]);
       globalThis.fetch = async (path, o) => {
         if (String(path) === "/api/models/unused" && !held) { held = true; await gate; return new Response(JSON.stringify(old)); }
         return plain(path, o); };
       try {
         globalThis.__movesOpts.onChange(); await settle();
         globalThis.__movesOpts.onChange(); await settle();
         const newer = tree().includes("qwen-q8.gguf"); release(); await settle();
         return [newer, tree().includes("stale.gguf"), tree().includes("qwen-q8.gguf")];
       } finally { globalThis.fetch = plain; } })()""",
     '[true,false,true]',
     "negative: две перерисовки наперегонки — ответ первой пришёл ПОСЛЕ второй и выброшен: иначе медленный старый "
     "ответ закрасил бы новое дерево старым списком"),
    ("the_selection_survives_a_redraw", '',
     r"""await (async () => { await boot(); globalThis.__boxes = [box("qwen/Qwen/Q8/qwen-q8.gguf", 8 * 2 ** 30, true)]; await boot(); const h = tree();
       return [h.includes('data-del-path="qwen/Qwen/Q8/qwen-q8.gguf" data-size="8589934592" checked>'), h.includes('data-del-path="llama/Meta/Q4/l-q4.gguf" data-size="2147483648">')]; })()""",
     '[true,true]',
     "отмеченное переживает перерисовку: перенос перерисовывает дерево на каждом приехавшем файле, и выбор не должен слетать; неотмеченное остаётся неотмеченным"),
    ("library_files_take_their_place_in_the_tree",
     'globalThis.__fetchReply["/api/model-stores/files"] = { ok: true, libraries: [{ id: "lib-a", name: "NAS", state: "ok", more: 0, files: ['
     '{ path: "qwen/Qwen/Q5/qwen-q5.gguf", size: 5 * 2 ** 30, ageDays: 20 }, { path: "moved/X/Q4/x.gguf", size: 2 * 2 ** 30, ageDays: 9 }, '
     '{ path: "qwen/Qwen/Q8/qwen-q8.gguf", size: 8 * 2 ** 30, ageDays: 3 }] }] };',
     r"""await (async () => { await boot(); const h = tree(); return [
       rowOf(h, "qwen-q5.gguf") === '<div class="mdl-file mdl-file-lib mdl-row" data-t="models-library-file" data-t-id="qwen/Qwen/Q5/qwen-q5.gguf" style="--lvl:3"><span class="mdl-c-name"><span class="tw"></span><span class="mdl-nobox"></span><code title="qwen/Qwen/Q5/qwen-q5.gguf">qwen-q5.gguf</code></span><span class="mdl-c-status"><span class="mdl-lib" title="In the library NAS, not on this disk">📚 NAS</span></span><span class="mdl-c-size here"><span class="mdl-dim">—</span></span><span class="mdl-c-size lib">5.00 GB</span><span class="mdl-c-age">20d</span><span class="mdl-c-go"></span></div>',
       h.includes('data-t="models-library-file" data-t-id="moved/X/Q4/x.gguf"'), h.includes('data-del-path="qwen/Qwen/Q5/qwen-q5.gguf"'),
       rowOf(h, "qwen-q8.gguf").includes('<span class="mdl-c-status"><span class="mdl-lib" title="Also in the library NAS">📚</span>'),
       rowOf(h, "qwen-q8.gguf").includes('<span class="mdl-c-size here">8.00 GB</span><span class="mdl-c-size lib">8.00 GB</span>'),
       branchOf(h, "qwen").includes('<span class="mdl-c-size here">12.0 GB</span><span class="mdl-c-size lib">13.0 GB</span>'),
       branchOf(h, "moved").includes('<span class="mdl-c-size here"><span class="mdl-dim">—</span></span><span class="mdl-c-size lib">2.00 GB</span>'),
       h.includes('data-t="models-library-file" data-t-id="qwen/Qwen/Q8/qwen-q8.gguf"'), (h.match(/data-del-path=/g) || []).length,
       F().mdlUnused.textContent, h.includes("…and")]; })()""",
     json.dumps([True, True, False, True, True, True, True, False, 3, en("mdlUnusedLine", n=3, size="10.5 GB"), False],
                ensure_ascii=False),
     "файлы библиотеки — в дереве на своих местах: 📚 с именем библиотеки в колонке состояния и пустое место вместо чекбокса (на этом диске их нет ни для удаления, ни для переноса); "
     "файл, который есть и здесь, и в библиотеке, остаётся строкой диска с 📚, и его байты стоят в ОБЕИХ колонках — они и там, и там; "
     "у ветки то же: здесь — что держит этот диск, в библиотеке — что держит библиотека; прочерк вместо «0.00 GB»; строка «не используются» считает только этот диск"),
    ("a_library_that_does_not_answer_leaves_the_tree_as_it_was",
     'globalThis.__fetchReply["/api/model-stores/files"] = { __status: 502, error: "no answer" };',
     r"""await (async () => { await boot(); const h = tree(); return [h.includes("models-library-file"), (h.match(/data-del-path=/g) || []).length, document.body.dataset.tState]; })()""",
     '[false,3,"ready"]',
     "negative: список библиотек не пришёл — дерево то же, что было, страница готова: без библиотеки в дереве её файлов нет, и только"),
    ("a_long_library_says_what_it_left_out",
     'globalThis.__fetchReply["/api/model-stores/files"] = { ok: true, libraries: [{ id: "lib-a", name: "NAS", state: "ok", more: 7, files: [{ path: "moved/X/Q4/x.gguf", size: 2 ** 30, ageDays: 1 }] }] };',
     r"""await (async () => { await boot(); return tree().includes('<p class="muted">📚 NAS: …and 7 more</p>'); })()""",
     'true',
     "библиотека назвала не все файлы — дерево говорит, сколько осталось за кадром, а не выдаёт список за полный"),
    ("a_place_shows_its_own_files",
     'panel(); globalThis.__fetchReply["/api/model-stores/files"] = LIBS();',
     r"""await (async () => { await boot(); const all = tree(); const reads = calls().length;
       place("local"); const local = tree(); const localOne = F().mdlTree.classList.has("one");
       place("lib-a"); const lib = tree(); const libOne = F().mdlTree.classList.has("one");
       place("all"); const back = [tree() === all, F().mdlTree.classList.has("one")];
       const order = [all.indexOf('data-branch="qwen"') < all.indexOf('data-branch="moved"'), lib.indexOf('data-branch="moved"') < lib.indexOf('data-branch="qwen"'),
                      rowOf(all, "qwen-q5.gguf").includes('<span class="mdl-c-size lib">11.0 GB</span>'), rowOf(lib, "qwen-q5.gguf").includes('<span class="mdl-c-size lib">5.00 GB</span>')];
       return [...order, all.includes(`📚 ${EN.mdlColLibrary}`), all.includes("📚 Archive: …and 2 more"),
               local.includes("models-library-file"), (local.match(/data-del-path=/g) || []).length, localOne, local.includes(`🏠 ${EN.mdlColSize}</span>`),
               lib.includes('data-t-id="qwen/Qwen/Q5/qwen-q5.gguf"'), lib.includes(">l-q4.gguf</code>"), lib.includes(">old.gguf</code>"),
               rowOf(lib, "qwen-q8.gguf").includes('<span class="mdl-c-size lib">8.00 GB</span><span class="mdl-c-age">'), libOne, lib.includes(`📚 ${EN.mdlColSize}</span>`),
               lib.includes("Archive: …and"), ...back, calls().length - reads]; })()""",
     '[true,true,true,true,true,true,false,3,true,true,true,false,false,true,true,true,false,true,false,0]',
     "выбранное место — это список его файлов: свой диск — только файлы этого диска (без строк библиотеки) с одной колонкой «🏠 Размер»; "
     "библиотека — её файлы, включая копии файлов этого диска, с одной колонкой «📚 Размер» и её байтами (у «Все модели» — байты всех копий), "
     "крупное в ней — первым; «…и ещё N» — только у того места, "
     "которое назвало не всё; negative: чужих файлов в месте нет, а переключение мест не ходит на сервер и возвращает тот же список"),
    ("the_filters_count_what_they_would_keep_here",
     'panel(); globalThis.__fetchReply["/api/model-stores/files"] = LIBS(); '
     'globalThis.__stubReturns["model-moves.mountMoves"] = () => tracker({ onWay: (p) => (p === "llama/Meta/Q4/l-q4.gguf" ? { job: {}, row: {} } : null) });',
     r"""await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: { r: { files: { "qwen/Qwen/Q8/qwen-q8.gguf": { state: "size" } } } }, prev: {}, watch: {} });
       const all = ["moving", "unused", "used", "newer"].map(filterOf);
       place("lib-a"); const lib = ["moving", "unused", "used", "newer"].map(filterOf);
       return [all[0].includes('<span class="c mv">1</span>'), all[1].includes('<span class="c warn">3 · 10.5 GB</span>'), all[2].includes('<span class="c">1</span>'), all[3].includes('<span class="c">1</span>'),
               all.map((b) => b.includes("disabled")), all[1].includes(`<span>${EN.mdlFilterUnused}</span>`),
               lib[0].includes("disabled"), lib[1].includes('<span class="c warn">1 · 8.00 GB</span>'), lib[2].includes("disabled"), lib[3].includes('<span class="c">1</span>')]; })()""",
     '[true,true,true,true,[false,false,false,false],true,true,true,true,true]',
     "число у фильтра — длина списка, который он даст, в ЭТОМ месте: в пути, не используются (с объёмом), используются ячейками, новее на HF; "
     "negative: в библиотеке «не используются» — это только копии файлов этого диска, а фильтр без единого файла выключен"),
    ("a_filter_keeps_its_files_and_opens_their_branches", '',
     r"""await (async () => { await boot(); globalThis.__openBranches = ["llama"]; pressFilter("unused"); const h = tree();
       const on = [h.includes(">qwen-q8.gguf</code>"), h.includes(">qwen-q4.gguf</code>"), (h.match(/ open>/g) || []).length, (h.match(/<details/g) || []).length,
                   filterOf("unused").includes('aria-pressed="true"'), calls().length];
       pressFilter("unused"); const off = tree();
       return [...on, off.includes(">qwen-q4.gguf</code>"), (off.match(/ open>/g) || []).length, off.includes('data-branch="llama" open>'), filterOf("unused").includes('aria-pressed="false"')]; })()""",
     '[true,false,9,9,true,0,true,1,true,true]',
     "фильтр оставляет только свои файлы и сам раскрывает ветки, где они лежат (найденное, свёрнутое с глаз, не найдено); повторное нажатие снимает фильтр и возвращает ровно те ветки, что были открыты до него, а не всё раскрытое фильтром; "
     "negative: фильтр не ходит на сервер"),
    ("a_filter_that_is_on_stays_reachable",
     'panel(); globalThis.__way = "llama/Meta/Q4/l-q4.gguf"; '
     'globalThis.__stubReturns["model-moves.mountMoves"] = () => tracker({ onWay: (p) => (p === globalThis.__way ? { job: {}, row: {} } : null) });',
     r"""await (async () => { await boot(); pressFilter("moving"); const moving = filterOf("moving"); globalThis.__way = ""; place("all");
       const done = filterOf("moving"); pressFilter("used"); const other = filterOf("moving");
       return [moving.includes("disabled"), done.includes('aria-pressed="true"'), done.includes("disabled"), other.includes("disabled")]; })()""",
     '[false,true,false,true]',
     "фильтр, который включён, остаётся нажимаемым, даже когда под него больше ничего не подходит (переносы доехали): иначе его нечем "
     "было бы выключить; negative: выключенный фильтр без файлов — неактивен"),
    ("the_name_box_narrows_the_list", '',
     r"""await (async () => { await boot(); typeName("QWEN-Q8"); const h = tree(); const found = [h.includes(">qwen-q8.gguf</code>"), h.includes(">l-q4.gguf</code>"), (h.match(/<details/g) || []).length];
       let prevented = 0; F().mdlSearch.listeners.keydown[0]({ key: "a", preventDefault() { prevented += 1; } }); const kept = [F().mdlSearch.value, tree().includes(">l-q4.gguf</code>")];
       F().mdlSearch.listeners.keydown[0]({ key: "Escape", preventDefault() { prevented += 1; } });
       return [...found, ...kept, F().mdlSearch.value, tree().includes(">l-q4.gguf</code>"), prevented]; })()""",
     '[true,false,3,"QWEN-Q8",false,"",true,1]',
     "поле имени сужает список по пути файла без учёта регистра; Escape очищает поле и возвращает весь список; negative: другие клавиши — просто ввод"),
    ("nothing_matches_says_so_with_the_way_back", '',
     r"""await (async () => { await boot(); pressFilter("used"); typeName("zzz"); const h = tree();
       const empty = [h.includes('data-t="models-filter-empty"'), h.includes(EN.mdlFilterEmpty), h.includes('data-t="models-filter-clear"'), h.includes("models-tree-head")];
       F().mdlTree.listeners.click[0]({ target: { closest: (s) => (s === "[data-show-all]" ? {} : null) } });
       const back = [F().mdlSearch.value, tree().includes(">qwen-q8.gguf</code>"), filterOf("used").includes('aria-pressed="false"')];
       await boot([]); const disk = tree();
       return [...empty, ...back, disk.includes(EN.gcNoUnused), disk.includes("models-filter-empty")]; })()""",
     '[true,true,true,false,"",true,true,true,false]',
     "фильтр и имя, под которые ничего не подошло, говорят это и дают дорогу назад: «Показать всё» снимает и фильтр, и имя, место остаётся; "
     "negative: пустой диск без фильтра — прежнее «ничего не лежит без дела», а не «под фильтр ничего не подошло»"),
    ("an_empty_place_says_it_holds_nothing",
     'panel(); globalThis.__fetchReply["/api/model-stores/files"] = { ok: true, libraries: [] };',
     r"""await (async () => { await boot(); place("lib-a"); const h = tree(); return [h.includes(EN.storeEmpty), h.includes(EN.mdlFilterEmpty), h.includes(EN.gcNoUnused), F().mdlUnused.textContent, F().mdlSelectAll.hidden]; })()""",
     '[true,false,false,"",true]',
     "место, в котором ничего нет, говорит «моделей пока нет», а не про фильтр и не про неиспользуемые; строка «не используются» в библиотеке "
     "без копий этого диска молчит, и кнопка выбора, которой нечего выбрать, не показана"),
    ("the_unused_line_counts_this_place",
     'panel(); globalThis.__fetchReply["/api/model-stores/files"] = LIBS();',
     r"""await (async () => { await boot(); const all = [F().mdlUnused.textContent, F().mdlSelectAll.hidden];
       place("lib-a"); const lib = [F().mdlUnused.textContent, F().mdlUnused.classList.has("warn"), F().mdlSelectAll.hidden];
       return [...all, ...lib]; })()""",
     json.dumps([en("mdlUnusedLine", n=3, size="10.5 GB"), False, en("mdlUnusedLine", n=1, size="8.00 GB"), True, False], ensure_ascii=False),
     "строка «не используются» — это счёт фильтра «Не используются» в том же месте и теми же словами (раньше рядом стояли «159.9 GB» сервера "
     "и «160 GB» фильтра): в библиотеке это копии этого диска, которые никто не использует"),
    ("the_moves_line_shows_what_is_on_its_way",
     'panel("lib-a"); globalThis.__fetchReply["/api/model-stores/files"] = LIBS(); '
     'globalThis.__stubReturns["model-moves.mountMoves"] = (opts) => { globalThis.__movesOpts = opts; return tracker({ onWay: (p) => (p === "llama/Meta/Q4/l-q4.gguf" ? { job: {}, row: {} } : null) }); };',
     r"""await (async () => { await boot(); typeName("qwen"); globalThis.__movesOpts.onReveal();
       const h = tree(); const moved = [globalThis.__panel.chosen, F().mdlSearch.value, filterOf("moving").includes('aria-pressed="true"'), h.includes(">l-q4.gguf</code>"), h.includes(">qwen-q8.gguf</code>")];
       pressFilter("moving"); globalThis.__movesOpts.onReveal();
       return [...moved, globalThis.__panel.chosen, filterOf("moving").includes('aria-pressed="true"'), calls().length]; })()""",
     '[["all"],"",true,true,false,["all"],true,0]',
     "строка «⇢ N файлов в пути» показывает ровно их: все места, фильтр «В пути», имя очищено — и только потом трекер подводит к первой полосе; "
     "negative: когда место уже «Все модели», его не выбирают второй раз; на сервер ничего не уходит"),
    ("the_selection_bar_shows_only_while_something_is_picked", '',
     r"""await (async () => { await boot(); const idle = F().mdlFoot.hidden; globalThis.__boxes = [box("a", 2 ** 30, true)]; F().mdlTree.listeners.change[0]();
       const picked = F().mdlFoot.hidden; globalThis.__boxes = [box("a", 2 ** 30, false)]; F().mdlTree.listeners.change[0](); return [idle, picked, F().mdlFoot.hidden]; })()""",
     '[true,false,true]',
     "плашка «выбрано · перенести · удалить» всплывает над списком только пока что-то выбрано; negative: без выбора её нет — две выключенные кнопки над каждой строкой мешали бы читать"),
    ("an_identical_redraw_leaves_the_markup_alone",
     'panel();',
     r"""await (async () => { await boot(); const t0 = F().mdlTree.writes, f0 = F().mdlFilters.writes;
       place("all"); const same = [F().mdlTree.writes - t0, F().mdlFilters.writes - f0];
       pressFilter("unused"); pressFilter("unused"); const twice = [F().mdlTree.writes - t0, F().mdlFilters.writes - f0];
       return [same, twice]; })()""",
     '[[0,0],[2,2]]',
     "перерисовка, которая ничего не меняет, разметку не трогает: страница рисует себя после каждого ответа, а разметка, заменённая под "
     "зажатой кнопкой мыши, съедает клик (живьём терялись клики по фильтрам и местам); negative: фильтр туда и обратно перерисовывает дважды"),
    # ── The comments on the models: one for each model, whatever its quants.
    ("a_model_with_a_comment_shows_it_and_the_others_offer_one",
     'globalThis.__fetchReply["/api/model-notes"] = NOTES({ qwen: "A <b>dense</b> model & more", "(root)": "never shown", nobody: "a model that is not on the list" });',
     r"""await (async () => { await boot(); const h = tree(); const at = (s, from = 0) => h.indexOf(s, from);
       const start = at('data-branch="qwen"'), block = at('data-t="models-note"', start), firstAuthor = at('data-branch="qwen/Qwen"');
       return { chips: chipsOf(h), texts: textsOf(h), adds: idsOf(h, "models-note-add").sort(), edits: idsOf(h, "models-note-edit"),
         aboveTheAuthors: start < block && block < firstAuthor, noUnknownLine: !h.includes("models-notes-unknown"), noBoxYet: !h.includes("<textarea") }; })()""",
     json.dumps({"chips": [["qwen", "A &lt;b&gt;dense&lt;/b&gt; model &amp; more"]], "texts": [["qwen", "A &lt;b&gt;dense&lt;/b&gt; model &amp; more"]],
                 "adds": ["llama"], "edits": ["qwen"], "aboveTheAuthors": True, "noUnknownLine": True, "noBoxYet": True}),
     "a model with a comment shows 💬 on its folded row (the words in the tooltip) and the comment itself above its authors, escaped, with a pencil to change it; "
     "a model without one offers the way to write it; the row of the loose files (\"(root)\") takes none even when the file holds a stray one, and a comment on a model "
     "that is not on the list is not drawn; no box is open until it is asked for"),
    ("a_page_that_did_not_get_the_comments_offers_none",
     'globalThis.__fetchReply["/api/model-notes"] = { __status: 500, error: "down" };',
     r"""await (async () => { await boot(); const h = tree(); const none = [chipsOf(h).length, textsOf(h).length, idsOf(h, "models-note-add").length, idsOf(h, "models-note-edit").length];
       const line = /<p class="muted mdl-notes-unknown" data-t="models-notes-unknown">([^<]*)<\/p>/.exec(h);
       globalThis.__fetchReply["/api/model-notes"] = NOTES({}); await boot(); const known = tree();
       return { none, line: line && line[1], knownAdds: idsOf(known, "models-note-add").sort(), knownLine: known.includes("models-notes-unknown") }; })()""",
     json.dumps({"none": [0, 0, 0, 0], "line": EN["mdlNoteUnknown"], "knownAdds": ["llama", "qwen"], "knownLine": False}, ensure_ascii=False),
     "negative: a page that could not read the comments draws no chip, no text and no box to write one in — a box that opened empty over a comment it did not read "
     "would save over it — and says so under the list; once they are read the line is gone and every model offers its comment"),
    ("writing_a_comment_for_one_model",
     'globalThis.__fetchReply["/api/model-notes"] = NOTES({});',
     r"""await (async () => { await boot(); await press("noteEdit", "llama"); const opened = [noteBox(), /maxlength="777"/.test(tree()), idsOf(tree(), "models-note-add")];
       typeNote("Meta's 70B"); pressFilter("unused"); const afterRedraw = noteBox(); pressFilter("unused");
       globalThis.__fetchReply["/api/model-notes"] = { ok: true, model: "llama", note: "Meta's 70B" }; globalThis.__fetchCalls.length = 0;
       const save = await press("noteSave", "llama"); const h = tree();
       return { opened, afterRedraw, calls: calls(), saved: textsOf(h), chips: chipsOf(h).map((c) => c[0]), boxGone: noteBox() === null, adds: idsOf(h, "models-note-add"),
         toast: F().toast.textContent, busy: save.disabled }; })()""",
     json.dumps({"opened": ["", True, ["qwen"]], "afterRedraw": "Meta&#39;s 70B",
                 "calls": [{"path": "/api/model-notes", "method": "POST", "body": {"model": "llama", "field": "note", "note": "Meta's 70B"}}],
                 "saved": [["llama", "Meta&#39;s 70B"]], "chips": ["llama"], "boxGone": True, "adds": ["qwen"], "toast": EN["mdlNoteSaved"], "busy": True}, ensure_ascii=False),
     "the add button opens an empty box for that model with the limit the server told (not one of the page's own); what is typed is kept through a redraw of the tree "
     "(a filter pressed there and back); Save sends the model's folder and the words in one POST, and the tree then shows the comment, its chip and a pencil with no second trip; "
     "the box is gone and the toast says the comment is saved"),
    ("a_comment_is_changed_and_taken_away",
     'globalThis.__fetchReply["/api/model-notes"] = NOTES({ qwen: "old words" });',
     r"""await (async () => { await boot(); await press("noteEdit", "qwen"); const opened = noteBox(); typeNote("");
       globalThis.__fetchReply["/api/model-notes"] = { ok: true, model: "qwen", note: "" }; globalThis.__fetchCalls.length = 0;
       await press("noteSave", "qwen"); const h = tree();
       return { opened, calls: calls(), texts: textsOf(h).length, chips: chipsOf(h).length, adds: idsOf(h, "models-note-add").sort(), toast: F().toast.textContent }; })()""",
     json.dumps({"opened": "old words", "calls": [{"path": "/api/model-notes", "method": "POST", "body": {"model": "qwen", "field": "note", "note": ""}}],
                 "texts": 0, "chips": 0, "adds": ["llama", "qwen"], "toast": EN["mdlNoteGone"]}, ensure_ascii=False),
     "the pencil opens the box with the comment the model has now; an emptied box saved is an empty note to the server, and the comment is gone from the tree — "
     "text, chip and pencil — with the add button back and the toast saying it was removed, not saved"),
    ("a_refused_comment_stays_in_the_box",
     'globalThis.__fetchReply["/api/model-notes"] = NOTES({});',
     r"""await (async () => { await boot(); await press("noteEdit", "llama"); typeNote("words that took long to write");
       globalThis.__fetchReply["/api/model-notes"] = { __status: 400, error: "a comment is at most 1000 characters, this one has 1001" };
       const save = await press("noteSave", "llama"); pressFilter("unused"); pressFilter("unused");
       const got = { toast: F().toast.textContent, box: noteBox(), busy: save.disabled, chips: chipsOf(tree()).length };
       await press("noteCancel"); return got; })()""",
     json.dumps({"toast": "a comment is at most 1000 characters, this one has 1001", "box": "words that took long to write", "busy": False, "chips": 0}),
     "negative: a refusal says why in the toast and leaves the box open, with the words still held (a redraw of the tree puts them back) and Save pressable again; nothing is drawn as kept"),
    ("the_other_two_texts_of_a_model",
     'globalThis.__fetchReply["/api/model-notes"] = { ...NOTES({}), params: { qwen: "--temp 1" }, comments: {}, limits: { note: 777, params: 4000, comment: 500 } };',
     r"""await (async () => { await boot(); const h = tree(); const shown = { params: textsOf(h, "models-params"), adds: [idsOf(h, "models-note-add").sort(), idsOf(h, "models-params-add").sort(), idsOf(h, "models-comment-add").sort()], edits: idsOf(h, "models-params-edit") };
       const edit = hit("noteEdit", "qwen"); edit.dataset.noteField = "params"; await F().mdlTree.listeners.click[0]({ target: edit }); await settle();
       const opened = [noteBox(), /maxlength="4000"/.test(tree()), idsOf(tree(), "models-params-input"), idsOf(tree(), "models-params-add").includes("qwen"), idsOf(tree(), "models-note-input")];
       typeNote("--temp 0.7"); globalThis.__fetchReply["/api/model-notes"] = { ok: true, model: "qwen", field: "params", note: "--temp 0.7" }; globalThis.__fetchCalls.length = 0;
       await press("noteSave", "qwen"); const saved = [calls(), textsOf(tree(), "models-params"), chipsOf(tree()).length, F().toast.textContent];
       const add = hit("noteEdit", "llama"); add.dataset.noteField = "comment"; await F().mdlTree.listeners.click[0]({ target: add }); await settle();
       const comment = [noteBox(), /maxlength="500"/.test(tree()), idsOf(tree(), "models-comment-input")]; typeNote("mine");
       globalThis.__fetchReply["/api/model-notes"] = { ok: true, model: "llama", field: "comment", note: "mine" }; globalThis.__fetchCalls.length = 0; await press("noteSave", "llama");
       return { shown, opened, saved, comment, commentCall: calls(), comments: textsOf(tree(), "models-comment"), desc: textsOf(tree()) }; })()""",
     json.dumps({"shown": {"params": [["qwen", "--temp 1"]], "adds": [["llama", "qwen"], ["llama"], ["llama", "qwen"]], "edits": ["qwen"]},
                 "opened": ["--temp 1", True, ["qwen"], False, []],
                 "saved": [[{"path": "/api/model-notes", "method": "POST", "body": {"model": "qwen", "field": "params", "note": "--temp 0.7"}}], [["qwen", "--temp 0.7"]], 0, EN["mdlNoteSaved"]],
                 "comment": ["", True, ["llama"]],
                 "commentCall": [{"path": "/api/model-notes", "method": "POST", "body": {"model": "llama", "field": "comment", "note": "mine"}}],
                 "comments": [["llama", "mine"]], "desc": []}, ensure_ascii=False),
     "у модели три текста (владелец, 2026-10-31): описание, рекомендованные параметры от разработчика и свой комментарий, каждый со своей кнопкой, своим пределом от сервера и своим полем в запросе; "
     "negative: сохранённые параметры не становятся описанием и не дают чипа описания, а открытый ящик одного поля не открывает другое"),
    ("a_models_mark_on_the_list",
     'globalThis.__fetchReply["/api/model-notes"] = { ...NOTES({}), ratings: { qwen: "like", "(root)": "like", nobody: "dislike" } };',
     r"""await (async () => { await boot(); const h = tree(); const marks = [...h.matchAll(/data-t="model-rating" data-t-state="(like|dislike)"/g)].map((m) => m[1]);
       const pressed = (m) => [...tree().matchAll(new RegExp(`aria-pressed="true" data-model-rate="(like|dislike)" data-model-rate-for="${m}"`, "g"))].map((x) => x[1]);
       const buttons = [pressed("qwen"), pressed("llama"), idsOf(h, "models-rate").sort()];
       const button = (kind, model) => { const el = { dataset: { modelRate: kind, modelRateFor: model }, closest: (s) => (s === "[data-model-rate]" ? el : null) }; return el; };
       const click = async (kind, model) => { await F().mdlTree.listeners.click[0]({ target: button(kind, model) }); await settle(); };
       globalThis.__fetchReply["/api/model-rating"] = { ok: true, model: "llama", rating: "dislike", ratings: { qwen: "like", llama: "dislike" } }; globalThis.__fetchCalls.length = 0;
       await click("dislike", "llama"); const set = [calls(), pressed("llama")];
       globalThis.__fetchReply["/api/model-rating"] = { ok: true, model: "qwen", rating: "", ratings: { llama: "dislike" } }; globalThis.__fetchCalls.length = 0;
       await click("like", "qwen"); const taken = [calls(), pressed("qwen")];
       globalThis.__fetchReply["/api/model-rating"] = { __status: 400, error: "no such model" }; await click("like", "llama"); const refused = [pressed("llama"), F().toast.textContent];
       return { marks, buttons, set, taken, refused }; })()""",
     json.dumps({"marks": ["like"], "buttons": [["like"], [], ["llama:dislike", "llama:like", "qwen:dislike", "qwen:like"]],
                 "set": [[{"path": "/api/model-rating", "method": "POST", "body": {"model": "llama", "rating": "dislike"}}], ["dislike"]],
                 "taken": [[{"path": "/api/model-rating", "method": "POST", "body": {"model": "qwen", "rating": ""}}], []],
                 "refused": [["dislike"], "no such model"]}, ensure_ascii=False),
     "хранилище показывает оценку на строке модели, а в открытой модели её можно поставить и снять тем же щелчком; negative: у строки россыпью и у модели не из списка значка нет, а отказ оставляет оценку прежней и говорит почему"),
    ("cancel_and_escape_leave_nothing_behind",
     'globalThis.__fetchReply["/api/model-notes"] = NOTES({ qwen: "kept" });',
     r"""await (async () => { await boot(); globalThis.__fetchCalls.length = 0;
       await press("noteEdit", "llama"); typeNote("a draft"); await press("noteCancel"); const cancelled = [noteBox(), calls().length];
       await press("noteEdit", "llama"); const again = noteBox();
       const other = { closest: () => null }; F().mdlTree.listeners.keydown[0]({ key: "Escape", target: other }); const elsewhere = noteBox();
       const esc = { closest: (s) => (s === "[data-note-input]" ? esc : null) }; F().mdlTree.listeners.keydown[0]({ key: "Enter", target: esc }); const enter = noteBox();
       F().mdlTree.listeners.keydown[0]({ key: "Escape", target: esc });
       return { cancelled, again, elsewhere, enter, escaped: [noteBox(), calls().length], kept: textsOf(tree()) }; })()""",
     '{"cancelled":[null,0],"again":"","elsewhere":"","enter":"","escaped":[null,0],"kept":[["qwen","kept"]]}',
     "Cancel and Escape in the box close it and send nothing; the next box opens with what the model has (nothing), not with the draft that was let go; "
     "negative: Escape pressed anywhere else does not touch a comment; the kept comment of another model is as it was"),
    ("a_refresh_that_cannot_read_the_comments_keeps_the_last_ones",
     'globalThis.__fetchReply["/api/model-notes"] = NOTES({ qwen: "kept" }); globalThis.__stubReturns["model-moves.mountMoves"] = (opts) => { globalThis.__movesOpts = opts; return tracker(); };',
     r"""await (async () => { await boot(); globalThis.__fetchReply["/api/model-notes"] = { __status: 500, error: "down" };
       globalThis.__movesOpts.onChange(); await settle(); const h = tree();
       return { chips: chipsOf(h).map((c) => c[0]), noUnknownLine: !h.includes("models-notes-unknown") }; })()""",
     '{"chips":["qwen"],"noUnknownLine":true}',
     "a refresh that could not read the comments keeps the ones the page read before: they change rarely and a box being typed in must not vanish "
     "(the page's first look is another matter: see the pin of the page that never got them)"),
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

    # Pins don't depend on each other: the same set run in reverse order
    # must give the same values.
    # The words pins compare against, from en.js — never retyped in a pin.
    words = "const EN = " + json.dumps({k: EN[k] for k in ("mdlColLibrary", "mdlColSize", "mdlFilterUnused", "mdlFilterEmpty",
                                                             "gcNoUnused", "storeEmpty")}, ensure_ascii=False) + ";\n"
    probe = (PREAMBLE + words + "\n".join(blocks(PINS, "out")) + "\nconst rev = {};\n"
             + "\n".join(blocks(list(reversed(PINS)), "rev"))
             + "\nconsole.log(JSON.stringify({ out, rev })); process.exit(0);\n")
    harness = ROOT / "scripts" / "_js_harness.mjs"
    path = ROOT / "scripts" / ".probe_js_models_page.tmp.mjs"
    path.write_text(probe)
    try:
        env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": STUBS,
               "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
        run = subprocess.run(
            probe_args(node, harness, path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=120)
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
    page = (ROOT / "static" / "models.html").read_text(encoding="utf-8")
    check("mdlFreshAt" not in page and 'type="time"' not in page and "Look once a day, when the main board is opened" in page,
          "1.3.678: у галки «раз в сутки» нет поля часа — когда смотреть, говорят её слова (первая доска за день); "
          "negative: поля времени в разметке нет")
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
