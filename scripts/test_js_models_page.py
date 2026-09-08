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
else) with restart:false; an empty path is never saved.

The DOM is the `globalThis.__fields` dict; `document.querySelectorAll` for a
selector string returns the checkbox list from `globalThis.__boxes`.

Run: python3 scripts/test_js_models_page.py
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
    const wiped = !String(globalThis.__fields.mdlTree.innerHTML).includes("<details");
    return wiped ? [] : globalThis.__openBranches.map((b) => ({ dataset: { branch: b } }));
  }
  return [];
};
await import(pathToFileURL(process.env.JS_ROOT + "/models-page.js").href);
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), has: (c) => s.has(c) } };
const mkEl = (onWipe) => ({ textContent: "", _html: "", get innerHTML() { return this._html; }, set innerHTML(v) { this._html = v; if (onWipe && !String(v).includes("<details")) onWipe(); }, hidden: false, disabled: false, value: "", classList: cls(), listeners: {}, focused: 0, clicked: 0, addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, setAttribute() {}, focus() { this.focused += 1; }, click() { this.clicked += 1; (this.listeners.click || []).forEach((fn) => fn({})); }, contains: () => false });
const IDS = ["mdlTree", "mdlPicked", "mdlDelete", "mdlPath", "mdlHeroStats", "confirmCancel", "confirmDelete", "confirmOverlay", "mdlPathEdit", "mdlPathInput", "mdlPathEditRow", "mdlPathCancel", "mdlPathSave", "mdlSelectAll", "toast", "userChipName", "userChip", "userMenu", "userChipBtn", "userMenuLogout", "mdlFreshCheck", "mdlFreshAuto", "mdlFreshStamp", "mdlFreshGet", "mdlFreshKeep", "mdlFreshAt"];
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
const boot = async (files = FILES(), disk = { ok: true, freeGb: 120 }, fresh = undefined, jobs = undefined) => {
  globalThis.__fetchReply["/api/models/unused"] = REPLY(files); globalThis.__fetchReply["/api/models/disk"] = disk;
  if (fresh !== undefined) globalThis.__fetchReply["/api/models/freshness"] = fresh;
  // Задания приходят С СЕРВЕРА при каждой отрисовке — поэтому то же самое
  // видно и после перезагрузки страницы, и во второй вкладке.
  if (jobs !== undefined) globalThis.__fetchReply["/api/hf/download/jobs"] = jobs;
  for (const fn of docListeners.DOMContentLoaded) await fn(); await settle(); globalThis.__fetchCalls.length = 0;
};
const reset = () => { globalThis.__fields = Object.fromEntries(IDS.map((id) => [id, mkEl(id === "mdlTree" ? _wipeScroll : null)])); globalThis.__boxes = []; globalThis.__openBranches = []; st.ui.pendingConfirm = null;
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = { "/api/auth/me": { enabled: false } }; globalThis.__stubReturns = { "dialogs.appConfirm": async () => true }; };
reset();
const tree = () => F().mdlTree.innerHTML;
const box = (path, size, checked) => ({ checked, dataset: { delPath: path, size: String(size) } });
const out = {};
"""

PINS = [
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
     '[["/api/models/staged/download",{"file":"qwen/Qwen/Q4/qwen-q4.gguf"}],["/api/models/unused",null],["/api/models/disk",null],["/api/models/freshness",null],["/api/hf/download/jobs",null]]',
     'кнопка шлёт ПУТЬ файла: одно имя лежит в репозитории дважды, и по имени она писала бы в чужую копию. Куда класть и откуда качать, знает отчёт сверки; страница сразу перечитывает себя — без ответа с jobId ждать нечего'),
    ("the_daily_check_has_a_time_of_day", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 1786000000, repos: {}, prev: {}, watch: { check: true, at: "04:30" } }); const shown = F().mdlFreshAt.value; const enabled = !F().mdlFreshAt.disabled; '
     'globalThis.__fetchReply["/api/models/freshness/watch"] = { ok: true, watch: { check: true, download: false, keepPrev: false, at: "07:05" } }; '
     'F().mdlFreshAt.value = "7:5"; (F().mdlFreshAt.listeners.change || []).forEach((fn) => fn({})); await settle(); '
     'return [shown, enabled, calls().filter((c) => c.path === "/api/models/freshness/watch").map((c) => c.body), F().mdlFreshAt.value]; })()',
     '["04:30",true,[{"check":true,"download":false,"keepPrev":false,"at":"7:5"}],"07:05"]',
     'positive: настроенное время видно в поле; правка уезжает ОДНИМ телом вместе с галками, и на экран возвращается то, что ПРИНЯЛ сервер («7:5» → «07:05»), а не то, что набрали'),
    ("the_time_field_is_dead_while_nobody_looks", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 0, repos: {}, prev: {}, watch: { check: false, at: "03:00" } }); const off = F().mdlFreshAt.disabled; '
     'await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 0, repos: {}, prev: {}, watch: { check: true, at: "03:00" } }); return [off, F().mdlFreshAt.disabled]; })()',
     '[true,false]',
     'negative: галка снята — поле времени выключено: настройка, которую некому исполнить, выглядела бы как обещание'),
    ("a_refused_time_does_not_stay_on_screen", '',
     'await (async () => { await boot(FILES(), { ok: true, freeGb: 120 }, { ok: true, checkedAt: 0, repos: {}, prev: {}, watch: { check: true, at: "03:00" } }); '
     'globalThis.__fetchReply["/api/models/freshness/watch"] = { __status: 400, error: "time out of range: 25:00" }; '
     'F().mdlFreshAt.value = "25:00"; (F().mdlFreshAt.listeners.change || []).forEach((fn) => fn({})); await settle(); '
     'return [F().mdlFreshAt.value, F().toast.textContent.includes("25:00")]; })()',
     '["03:00",true]',
     'negative: сервер отверг время — поле возвращается к прежнему и причина сказана вслух; иначе на экране осталась бы настройка, которой нет'),
    ("watch_sends_all_three_levels", '',
     'await (async () => { await boot(); F().mdlFreshKeep.checked = true; (F().mdlFreshKeep.listeners.change || []).forEach((fn) => fn({})); await settle(); return calls().map((c) => c.body); })()',
     '[{"check":false,"download":false,"keepPrev":true,"at":""}]',
     'галки и время едут ВМЕСТЕ одним телом — сервер сам включит «смотреть» под «обновлять», и спорить с ним по дороге незачем; пустое время означает «оставить как настроено», а не «сбросить»'),
    # ── Model freshness: the watcher's report is drawn as an icon, and the UNCHECKED stays silent.
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
     '[true,[["/api/models/freshness/watch",{"check":true,"download":false,"keepPrev":false,"at":""}]]]',
     'кнопка просит проверку; три галки уезжают ОДНИМ телом — сервер сам делает нижние обязательными для верхних'),
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
     '["/api/models/gc",{"files":["qwen/Qwen/Q8/qwen-q8.gguf"]},"9 GB freed",["/api/models/unused","/api/models/disk","/api/models/freshness","/api/hf/download/jobs"],false]', "удаление: POST только отмеченных путей, тост, перечитывание, кнопка снова включена"),
    ("path_edit_opens_with_current", '', 'await (async () => { await boot(); F().mdlPathEdit.listeners.click[0](); return [F().mdlPathInput.value, F().mdlPathEditRow.hidden, F().mdlPathInput.focused]; })()', '["/models",false,1]', "правка каталога: поле с текущим путём, строка показана, фокус"),
    ("path_save_merges_over_saved_config", 'globalThis.__fetchReply["/api/state"] = { config: { MODEL_FILE: "x.gguf", THREADS: "8" } };', 'await (async () => { await boot(); F().mdlPathInput.value = " /srv/models "; await F().mdlPathSave.listeners.click[0](); await settle(); const c = calls(); return [c[0].path, c[1].path, c[1].body, F().mdlPathEditRow.hidden, F().toast.textContent, c.slice(2).map((x) => x.path)]; })()',
     '["/api/state","/api/config",{"config":{"MODEL_FILE":"x.gguf","THREADS":"8","LLAMA_MODELS_DIR":"/srv/models"},"restart":false},true,"Saved.",["/api/models/unused","/api/models/disk","/api/models/freshness","/api/hf/download/jobs"]]', "сохранение каталога: путь обрезан и слит поверх ТЕКУЩЕГО сохранённого конфига, без рестарта; потом перечитывание"),
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

    # Pins don't depend on each other: the same set run in reverse order
    # must give the same values.
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
