#!/usr/bin/env python3
"""Snapshot of static/js/system-page.js — the /system page.

The page's entry point has no exports: the snapshot intercepts
DOMContentLoaded at import time and fires it itself. What's pinned by value:
the tab list is read FROM THE MARKUP (a hand-written list once turned a new
tab into a "dead button"), an unknown tab falls back to the first one,
deep-linking via hash and back, clicking a tab button; the summary tiles
(version, git with a warn on dirty, cells good when running, disk warn below
50 GB, models, python) and the footer; refreshAll — two requests, a failed
controller-info writes the reason into the panel and sets
`data-t-state=error`, success sets ready; the settings file: export with no
password is a GET with a flag, with a passphrase it's a POST body (the URL
would otherwise land in logs and history), the response becomes a download
of `caravan-settings-<stamp>.json`, the panel lists files with their sizes,
warns about credentials, and states what the file does NOT contain; import —
a dry run first, a confirmation listing the replacements, the passphrase is
asked for only on "locked", a result with what was skipped; the "with
secrets" toggle shows the password field only when the host can encrypt.

The DOM is the `globalThis.__fields` dict, `document.querySelectorAll` by tab/panel
classes, `history.replaceState` and `URL.createObjectURL` are stubs.

Run: python3 scripts/test_js_system_page.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

STUBS = ("system-panels,dialogs,dialog-llamas,polling,canvas,topology-dnd,topology-render,charts,cables,cloud,history,"
         "favorites,config-locator,onboarding,onboarding-tours,usage-stats,models-page,memory,command-preview,"
         "llama-edit,remote-cells,topology-nodes,topology-modals,routers,topology-activity,topology-proxies,model-meta,form")

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const st = await import(pathToFileURL(process.env.JS_ROOT + "/state.js").href);
st.setState({ config: {} });
const cls = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), toggle: (c, on) => (on ? s.add(c) : s.delete(c)), has: (c) => s.has(c) } };
const mkEl = (tag = "div", props = {}) => ({ tag, textContent: "", innerHTML: "", hidden: false, checked: false, value: "", href: "", download: "", attrs: {}, classList: cls(), dataset: {}, listeners: {}, clicked: 0, removed: false, after: null, files: [],
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, setAttribute(k, v) { this.attrs[k] = v; }, click() { this.clicked += 1; }, remove() { this.removed = true; },
  closest() { return this; }, contains: () => false, ...props });
// Разметка страницы: пять вкладок и панелей — список вкладок модуль читает ИЗ DOM при импорте.
const TAB_NAMES = ["controller", "llama", "security", "settings", "diag"];
const tabs = TAB_NAMES.map((n) => mkEl("button", { dataset: { tab: n } })); const panels = TAB_NAMES.map((n) => mkEl("div", { dataset: { panel: n } }));
const rowAfter = []; const passRowAfter = [];
document.querySelectorAll = (sel) => (sel === ".sys-tab" ? tabs : sel === ".sys-panel" ? panels : []);
globalThis.__q = {}; document.querySelector = (sel) => (Object.prototype.hasOwnProperty.call(globalThis.__q, sel) ? globalThis.__q[sel] : null);
const docListeners = {}; document.addEventListener = (t, fn) => { (docListeners[t] ||= []).push(fn); };
const winListeners = {}; globalThis.addEventListener = (t, fn) => { (winListeners[t] ||= []).push(fn); };
document.body = { dataset: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, appendChild() {}, contains: () => false };
globalThis.history = { hash: null, replaceState(_s, _t, h) { this.hash = h; } };
globalThis.__created = []; document.createElement = (tag) => { const e = mkEl(tag); if (tag === "p") { e.className = ""; } globalThis.__created.push(e); return e; };
globalThis.__blobs = []; globalThis.URL.createObjectURL = (b) => { globalThis.__blobs.push(b); return "blob:x" + globalThis.__blobs.length; }; globalThis.URL.revokeObjectURL = () => {};
globalThis.__timers = []; globalThis.setInterval = (fn, ms) => { globalThis.__timers.push("interval:" + ms); return 0; }; globalThis.setTimeout = (fn, ms) => { globalThis.__timers.push("timeout:" + ms); return 0; };
await import(pathToFileURL(process.env.JS_ROOT + "/system-page.js").href);
const IDS = ["sysHeroStats", "sysFoot", "controllerInfo", "sysTabs", "confirmCancel", "confirmDelete", "confirmOverlay", "checkLlamaBtn", "updateLlamaBtn", "repairUserServiceBtn", "authLogoutBtn", "settingsWithSecrets", "settingsPassphrase", "settingsPassRow", "settingsExportBtn", "settingsImportBtn", "settingsImportFile", "settingsBundleInfo", "toast", "userChipName", "userChip", "userMenu", "userChipBtn", "userMenuLogout"];
const F = () => globalThis.__fields;
const calls = () => globalThis.__fetchCalls.map((c) => ({ path: c.path, method: c.method, body: c.body === null ? null : JSON.parse(c.body) }));
const settle = async () => { for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r)); };
const panelCalls = () => globalThis.__panelCalls;
const INFO = () => ({ projectGit: { branch: "main", head: "abc1234", dirtyCount: 0 }, cells: { running: 3, total: 5 }, disk: { totalGb: 900, freeGb: 120 }, models: { count: 12, totalGb: 340 }, python: "3.12" });
const boot = async (extra = {}) => {
  globalThis.__fetchReply["/api/state"] = { config: {}, appVersion: "1.3.306", projectGit: { branch: "main", dirtyCount: 2 } }; globalThis.__fetchReply["/api/controller-info"] = INFO(); Object.assign(globalThis.__fetchReply, extra);
  for (const fn of docListeners.DOMContentLoaded) await fn(); await settle(); globalThis.__fetchCalls.length = 0;
};
const reset = () => { st.setState({ config: {} }); globalThis.__fields = Object.fromEntries(IDS.map((id) => [id, mkEl()])); F().settingsWithSecrets = mkEl("input", { after(el) { rowAfter.push(el); } }); F().settingsPassRow = mkEl("div", { after(el) { passRowAfter.push(el); } });
  globalThis.__q = {}; globalThis.__created.length = 0; globalThis.__blobs.length = 0; globalThis.__timers.length = 0; globalThis.location.hash = ""; globalThis.history.hash = null; rowAfter.length = 0; passRowAfter.length = 0;
  tabs.forEach((b) => { b.classList = cls(); b.attrs = {}; }); panels.forEach((p) => { p.classList = cls(); });
  globalThis.__fetchCalls.length = 0; globalThis.__fetchReply = { "/api/auth/me": { enabled: false }, "/api/auth/overview": { enabled: false } }; globalThis.__panelCalls = [];
  const rec = (name) => (...a) => { globalThis.__panelCalls.push([name, a[0] ?? null]); };
  globalThis.__stubReturns = { "dialogs.appConfirm": async () => true, "dialogs.appPrompt": async () => null, "dialogs.settleAppConfirm": () => true,
    "system-panels.renderLlamaCpp": rec("renderLlamaCpp"), "system-panels.renderKnownProblems": rec("renderKnownProblems"), "system-panels.renderProjectGitBranch": rec("renderProjectGitBranch"), "system-panels.renderControllerInfo": rec("renderControllerInfo"), "system-panels.refreshSecurity": rec("refreshSecurity"), "system-panels.bindModelGc": rec("bindModelGc"), "system-panels.checkLlamaCpp": async () => { globalThis.__panelCalls.push(["checkLlamaCpp", null]); } }; };
reset();
globalThis.__fetchReply["/api/state"] = { config: {}, appVersion: "0" }; globalThis.__fetchReply["/api/controller-info"] = { __status: 502, error: "first boot: scout down" };
for (const fn of docListeners.DOMContentLoaded) await fn(); await settle();
globalThis.__firstLoad = { tState: document.body.dataset.tState, detail: document.body.dataset.tStateDetail ?? null, panel: globalThis.__fields.controllerInfo.innerHTML };
reset();
const activeTab = () => tabs.filter((b) => b.classList.has("active")).map((b) => b.dataset.tab);
const activePanel = () => panels.filter((p) => p.classList.has("active")).map((p) => p.dataset.panel);
const out = {};
"""

PINS = [
    ("tabs_from_markup_and_default", '', 'await (async () => { await boot(); return [activeTab(), activePanel(), tabs[0].attrs["aria-selected"], tabs[1].attrs["aria-selected"], globalThis.history.hash]; })()', '[["controller"],["controller"],"true","false",null]',
     "вкладки из разметки: без hash активна первая, aria-selected расставлен, hash при старте не переписывается"),
    ("deep_link_hash", 'globalThis.location.hash = "#security";', 'await (async () => { await boot(); return [activeTab(), activePanel(), globalThis.history.hash]; })()', '[["security"],["security"],null]', "deep-link /system#security открывает свою вкладку без записи в историю"),
    ("unknown_hash_falls_back", 'globalThis.location.hash = "#nope";', 'await (async () => { await boot(); return activeTab(); })()', '["controller"]', "negative: неизвестная вкладка в hash — первая"),
    ("tab_button_without_name_falls_back", '', 'await (async () => { await boot(); F().sysTabs.listeners.click[0]({ target: { closest: () => tabs[2] } }); F().sysTabs.listeners.click[0]({ target: { closest: () => mkEl("button", { dataset: {} }) } }); return [activeTab(), activePanel()]; })()', '[["controller"],["controller"]]', "negative: кнопка вкладки без имени — активной становится первая, а не никакая"),
    ("first_load_failure_is_error", '', 'globalThis.__firstLoad', '{"tState":"error","detail":"controller-info unavailable","panel":"<span class=\\"muted\\">first boot: scout down</span>"}', "первая загрузка без controller-info — страница честно в состоянии error с причиной (пробуется один раз при старте процесса)"),
    ("tab_click_and_hashchange", '', 'await (async () => { await boot(); F().sysTabs.listeners.click[0]({ target: { closest: () => tabs[3] } }); const a = [activeTab(), globalThis.history.hash]; F().sysTabs.listeners.click[0]({ target: { closest: () => null } }); const b = activeTab(); globalThis.location.hash = "#diag"; winListeners.hashchange[0](); return [...a, b, activeTab(), globalThis.history.hash]; })()',
     '[["settings"],"#settings",["settings"],["diag"],"#settings"]', "клик по вкладке переключает и пишет hash; клик мимо кнопки — ничего; hashchange переключает без записи"),
    ("hero_tiles", '', 'await (async () => { await boot(); const h = F().sysHeroStats.innerHTML; return [h.includes("<span>lama-caravan</span><strong title=\\"v1.3.306\\">v1.3.306</strong>"), h.includes("sys-stat \\"><span>git</span><strong title=\\"main @ abc1234\\">"), h.includes("sys-stat good\\"><span>server cells (units)</span><strong title=\\"3 / 5\\">"), h.includes("sys-stat good\\"><span>models disk</span><strong title=\\"120 GB free\\">"), h.includes("<strong title=\\"12 · 340 GB\\">"), h.includes("<span>Python</span><strong title=\\"3.12\\">"), F().sysFoot.textContent]; })()',
     '[true,true,true,true,true,true,"lama-caravan v1.3.306"]', "плитки: версия, git контроллера (чистый — без warn), ячейки good, диск good, модели, python; подвал с версией"),
    ("hero_warns_and_fallbacks", '', 'await (async () => { await boot({ "/api/controller-info": { projectGit: { branch: "main", dirtyCount: 3 }, cells: { running: 0, total: 2 }, disk: { totalGb: 100, freeGb: 10 } } }); const h = F().sysHeroStats.innerHTML; return [h.includes("sys-stat warn\\"><span>git</span>"), h.includes("sys-stat \\"><span>server cells (units)</span><strong title=\\"0 / 2\\">"), h.includes("sys-stat warn\\"><span>models disk</span>"), h.includes("Python")]; })()',
     '[true,true,true,false]', "git с грязными файлами — warn, ни одной запущенной ячейки — без good, диск ниже 50 GB — warn, без python плитки нет"),
    ("refresh_all_calls_and_ready", '', 'await (async () => { await boot(); return [panelCalls().filter((c) => c[0] !== "bindModelGc" && c[0] !== "refreshSecurity").map((c) => c[0]), panelCalls().find((c) => c[0] === "renderControllerInfo")[1].python, document.body.dataset.tState, st.state.appVersion, [...globalThis.__timers]]; })()',
     '[["renderLlamaCpp","renderKnownProblems","renderProjectGitBranch","renderControllerInfo"],"3.12","ready","1.3.306",["interval:30000"]]', "refreshAll: состояние применено и три панели перерисованы, controller-info передан в чипы, страница ready, автообновление каждые 30 с"),
    ("refresh_all_controller_info_failure_keeps_last_info", '', 'await (async () => { await boot(); await boot({ "/api/controller-info": { __status: 502, error: "scout down" } }); return [F().controllerInfo.innerHTML, document.body.dataset.tState, document.body.dataset.tStateDetail ?? null, F().sysHeroStats.innerHTML.includes("v1.3.306"), F().sysHeroStats.innerHTML.includes("3 / 5")]; })()',
     '["<span class=\\"muted\\">scout down</span>","ready",null,true,true]', "as-is: отказ controller-info на повторном обновлении — причина в панели, но страница остаётся ready и сводка строится из ПРЕЖНИХ данных (первую загрузку без данных снимок не изолирует — состояние модуля)"),
    ("refresh_all_state_failure_keeps_going", '', 'await (async () => { await boot({ "/api/state": { __status: 500, error: "boom" } }); return [document.body.dataset.tState, panelCalls().some((c) => c[0] === "renderControllerInfo"), F().sysHeroStats.innerHTML.includes("Python")]; })()',
     '["ready",true,true]', "отказ /api/state не мешает controller-info: страница ready, сводка из info"),
    ("export_without_passphrase_is_get", 'globalThis.__fetchReply["/api/settings/export?secrets=0"] = { ok: true, bundle: { files: { "agent-proxies.json": { content: "{}" } } } };',
     'await (async () => { await boot(); await F().settingsExportBtn.listeners.click[0](); await settle(); const a = globalThis.__created.find((e) => e.tag === "a"); return [calls()[0].path, calls()[0].method, /^caravan-settings-\\d{8}-\\d{4}\\.json$/.test(a.download), a.href, a.clicked, a.removed, F().toast.textContent, F().settingsBundleInfo.innerHTML.includes("<code>agent-proxies.json</code> <span class=\\"muted\\">2 chars</span>")]; })()',
     '["/api/settings/export?secrets=0","GET",true,"blob:x1",1,true,"Settings saved to a file",true]', "экспорт без пароля — GET с флагом секретов; ответ уходит скачиванием с штампом в имени, панель перечисляет файлы"),
    ("export_with_passphrase_is_post_body", 'globalThis.__fetchReply["/api/settings/export"] = { ok: true, bundle: { files: {}, containsCredentials: ["cloud"], redacted: ["a", "b"], excluded: { "token-history": "too big" } } };',
     'await (async () => { await boot(); F().settingsWithSecrets.checked = true; F().settingsPassphrase.value = " hunter2 "; await F().settingsExportBtn.listeners.click[0](); await settle(); const h = F().settingsBundleInfo.innerHTML; return [calls()[0].path, calls()[0].method, calls()[0].body, h.includes("settings-warn"), h.includes("2 secret(s) replaced with a placeholder; loading this file keeps the keys already on this controller"), h.includes("<code>token-history</code> — too big")]; })()',
     '["/api/settings/export","POST",{"secrets":true,"passphrase":"hunter2"},true,true,true]', "с паролем-фразой — POST телом (не в URL), фраза обрезана; панель предупреждает об учётных данных, считает вымаранное и перечисляет, чего в файле нет"),
    ("export_failure_toasts", 'globalThis.__fetchReply["/api/settings/export?secrets=0"] = { ok: false };', 'await (async () => { await boot(); await F().settingsExportBtn.listeners.click[0](); await settle(); return [F().toast.textContent, globalThis.__blobs.length]; })()', '["Could not save the settings",0]', "negative: ok:false — тост, скачивания нет"),
    ("import_dry_run_then_confirm_then_apply", 'globalThis.__fetchReply["/api/settings/import"] = { ok: true, changes: [{ name: "agent-proxies.json", action: "replace" }, { name: "cells", action: "keep", note: "same" }], skipped: [] };',
     'await (async () => { await boot(); let confirmMsg = ""; globalThis.__stubReturns["dialogs.appConfirm"] = async (m) => { confirmMsg = m; return true; }; const file = { text: async () => JSON.stringify({ files: { "agent-proxies.json": { content: "{}" } } }) }; const input = F().settingsImportFile; input.value = "x"; await input.listeners.change[0]({ target: { files: [file], value: "x" } }); await settle(); const c = calls(); return [c[0].body.dryRun, c[0].body.bundle.files ? true : false, confirmMsg.includes("agent-proxies.json"), c[1].body.dryRun, c[1].body.passphrase, F().toast.textContent, c.slice(2).map((x) => x.path), F().settingsBundleInfo.innerHTML.includes("<code>agent-proxies.json</code> — replace")]; })()',
     '[true,true,true,null,"","Settings loaded — a copy of the previous ones was kept",["/api/state","/api/controller-info"],true]', "импорт: сухой прогон → подтверждение с перечнем замен → применение без пароля → тост и перечитывание; панель показывает, что изменится"),
    ("import_refused_confirm", 'globalThis.__fetchReply["/api/settings/import"] = { ok: true, changes: [{ name: "x", action: "replace" }] };', 'await (async () => { await boot(); globalThis.__stubReturns["dialogs.appConfirm"] = async () => false; await F().settingsImportFile.listeners.change[0]({ target: { files: [{ text: async () => "{}" }], value: "" } }); await settle(); return calls().length; })()', '1', "negative: отказ подтверждения — только сухой прогон, применения нет"),
    ("import_locked_asks_passphrase", 'globalThis.__fetchReply["/api/settings/import"] = { ok: true, changes: [{ name: "cloud", action: "locked" }], skipped: ["cloud"] };',
     'await (async () => { await boot(); let promptOpts = null; globalThis.__stubReturns["dialogs.appPrompt"] = async (_m, o) => { promptOpts = o; return "pw"; }; await F().settingsImportFile.listeners.change[0]({ target: { files: [{ text: async () => "{}" }], value: "" } }); await settle(); return [promptOpts.password, calls()[1].body.passphrase, F().toast.textContent]; })()',
     '[true,"pw","Settings loaded; not restored: cloud"]', "заблокированные учётные данные: пароль-фраза запрашивается скрытым полем и уходит в тело; пропущенное названо в тосте"),
    ("import_unreadable_and_dry_run_error", '', 'await (async () => { await boot(); await F().settingsImportFile.listeners.change[0]({ target: { files: [{ text: async () => "{not json" }], value: "" } }); await settle(); const a = [F().toast.textContent, calls().length]; globalThis.__fetchReply["/api/settings/import"] = { ok: false, error: "bad bundle" }; await F().settingsImportFile.listeners.change[0]({ target: { files: [{ text: async () => "{}" }], value: "" } }); await settle(); return [...a, F().toast.textContent]; })()',
     '["Could not read that file — is it a settings export?",0,"bad bundle"]', "negative: нечитаемый файл — тост без запросов; отказ сухого прогона — его причина"),
    ("secrets_toggle_shows_pass_row_only_when_supported", '', 'await (async () => { await boot(); st.state.settingsPassphrase = undefined; const s = F().settingsWithSecrets; const a = F().settingsPassRow.hidden; s.checked = true; s.listeners.change[0](); const b = [F().settingsPassRow.hidden, rowAfter.at(-1)?.textContent]; st.state.settingsPassphrase = false; s.listeners.change[0](); const c = [F().settingsPassRow.hidden, passRowAfter[0]?.textContent]; s.checked = false; F().settingsPassphrase.value = "left"; s.listeners.change[0](); return [a, ...b, ...c, F().settingsPassphrase.value]; })()',
     '[true,false,"⚠ This file carries accounts (password hashes) and cloud API keys. Keep it as you would keep a password.",true,"Passphrase protection is unavailable on this controller: it needs the \'cryptography\' package in the service venv.",""]',
     "переключатель секретов: строка пароля появляется только с секретами и только когда хост умеет шифровать; без поддержки — объяснение; снятие галки очищает фразу"),
    ("confirm_and_section_wiring", '', 'await (async () => { await boot(); let settled = []; globalThis.__stubReturns["dialogs.settleAppConfirm"] = (ok) => settled.push(ok); F().confirmCancel.listeners.click[0](); F().confirmOverlay.listeners.click[0]({ target: { id: "confirmOverlay" } }); docListeners.keydown.at(-1)({ key: "Escape" }); let ran = 0; st.ui.pendingConfirm = () => ran++; F().confirmDelete.listeners.click[0](); await F().checkLlamaBtn.listeners.click[0](); return [settled, ran, panelCalls().some((c) => c[0] === "bindModelGc"), panelCalls().filter((c) => c[0] === "checkLlamaCpp").length, !!F().updateLlamaBtn.listeners.click, !!F().repairUserServiceBtn.listeners.click]; })()',
     '[[false,false,false],1,true,1,true,true]', "проводка: отмена/подложка/Escape оседают false, подтверждение зовёт pendingConfirm, сборщик мусора привязан, кнопки проверки/обновления/починки навешаны"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 18:
        print(f"js system-page FAILED: всего {len(PINS)} пинов — снимок урезан")
        return 1
    node = find_node()
    if node is None:
        print("js system-page: SKIPPED — node не найден: " + ", ".join(node_search_paths()))
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
    path = ROOT / "scripts" / ".probe_js_system_page.tmp.mjs"
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
        print(f"js system-page FAILED: node вышел с кодом {run.returncode}")
        return 1
    both = json.loads(run.stdout.strip().splitlines()[-1])
    got, rev = both["out"], both["rev"]
    print("страница /system: вкладки, сводка, файл настроек:")
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
    print(f"js system-page OK: настоящий модуль в node, {len(PINS)} пинов страницы System значениями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
