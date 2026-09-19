#!/usr/bin/env python3
"""Snapshot of static/js/hf-page.js — the /hf page: what reaches the server and
the screen when the operator clicks.

The page is built on a document of its own (a small fake: elements with
listeners, parents, `closest` over the selectors the page uses) and a fetch
that records every request and answers from a table, can fail or can wait.
The tour module is a stub that records what the page asks of it.

Pinned by value. The dialog: its markup, Cancel, a click outside and Escape
answer no, OK answers yes, focus on OK, the key listener leaves with it.
Start: the words in the page language, one request each for the token, the
favorites, the jobs, the disk, the frontier, the version and the user; the
page marked ready (with how many start-up loads got nothing), the loader
hidden, the search box focused, the tour buttons. An address with ?q= searches
and an exact "author/repo" opens its repository with one request per kind.

The search: nothing for blank words, "Searching…" with the button off, the
results sorted, the server's refusal or a network error shown in the list.
The bar: files counted first, then benchmarks, then gone; a newer search takes
the counting over. The filters by clicks: size and capability chips (pressed
state, a click beside a chip does nothing), the name mask, the order and its
direction, the tabs. The list row: active, favorite, name, format, capability
icons, downloads, likes, size, age, files on disk, the score. The star saves
the favorites and does not select; a failed save is a toast. The pointer held
over the list holds its redraw until release. A container is rewritten only
when its markup changed, and the focused control gets its focus back.

The repository: files, on-disk check, tree and benchmarks on selection; a
failure shown, a failed tree asked again; Enter and Space select a row, not a
control in it. Its controls: benchmarks panel and refresh, low groups, tree
and other cards, star, frontier, checkpoint only with one, another repository.
A checkbox picks the files it names. Verify polls progress by bytes and ends
with the result or a toast. Delete asks first, deletes one by one, stops at
the first failure and re-reads the disk. The token: popover, change after a
question, save trimmed, Escape and Enter in the field, closing from outside
but not from inside or the dialog, clear after a question. The disk badge by
free space, hidden when unknown. The header: version, user chip and menu,
logout, the language menu of twenty with the current one chosen. The frontier
panel: opens, stays for clicks inside, closes outside, on Escape and by its
button, refreshes forced. The dock: every control reaches the downloads. The
tour: seven steps, the first centred with the languages; a language chosen
there is stored and relabels the tour button.

Run: python3 scripts/test_js_hf_page.py
"""
import json
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const NOW = Date.parse("2026-09-16T12:00:00Z"); Date.now = () => NOW;
const P = await import(pathToFileURL(process.env.JS_ROOT + "/hf-page.js").href);
const GB = 2 ** 30;
const G = "bartowski/gemma-4-12B-it-GGUF", Q = "unsloth/Qwen3.6-35B-A3B-GGUF", M = "mlx-community/Llama-4-Scout-17B-16E-4bit";
const enc = encodeURIComponent;
const SEARCH = (q, limit = "20") => `/api/hf/search?q=${enc(q)}&limit=${enc(limit)}`;
const FILES_URL = (id) => `/api/hf/files?repo=${enc(id)}`, LOCAL_URL = (id) => `/api/hf/local-check?repo=${enc(id)}`;
const TREE_URL = (id) => `/api/hf/model-tree?repo=${enc(id)}`, BENCH_URL = (id) => `/api/hf/benchmarks?repo=${enc(id)}`;
const FRONTIER = () => [{ org: "Anthropic", name: "Claude Fable 5", aa: 64.9 }, { org: "OpenAI", name: "GPT-5.4", aa: 56.8 }, { org: "Google", name: "Gemini 2.5 Flash", aa: 20.6 }, { org: "Meta", name: "Llama 4 Scout", aa: 13.5 }];
const REPOS = () => [
  { id: G, downloads: 61351, likes: 17, createdAt: "2026-08-10T00:00:00.000Z", pipelineTag: "image-text-to-text", tags: ["gguf"] },
  { id: Q, downloads: 250000, likes: 420, createdAt: "2026-05-01T00:00:00.000Z", tags: ["gguf"] },
  { id: M, downloads: 900, likes: 3, createdAt: "2025-01-10T00:00:00.000Z", tags: ["mlx"] },
];
const FILE = (quant, size, name, kind = "model") => ({ kind, quant, size, name, path: name, date: "2026-08-10T00:00:00Z" });
const FILES = () => ({ ok: true, lastModified: "2026-08-10T00:00:00Z", safetensors: null, otherFiles: [],
  files: [FILE("Q4_K_M", 7 * GB, "g-Q4_K_M.gguf"), FILE("Q8_0", 12 * GB, "g-Q8_0.gguf"), FILE("IQ2_M", 4 * GB, "g-IQ2_M.gguf"), FILE("", 175115712, "mmproj-g-bf16.gguf", "mmproj")] });

// ── a document of the page's own ────────────────────────────────────────────
let doc, page, replies, throws, gates, asked, answers, timers, intervals, tourCalls, plHidden, reloads;
const camel = (s) => s.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
const matches = (node, sel) => {
  const attr = sel.match(/^\[data-([\w-]+)(?:=['"]([^'"]*)['"])?\]$/);
  if (attr) { const key = camel(attr[1]); return Object.prototype.hasOwnProperty.call(node.dataset || {}, key) && (attr[2] === undefined || node.dataset[key] === attr[2]); }
  if (sel.startsWith("#")) return node.id === sel.slice(1);
  if (sel.startsWith(".")) return String(node.className || "").split(/\s+/).includes(sel.slice(1));
  throw new Error(`selector the fake document does not know: ${sel}`);
};
const classes = () => { const s = new Set(); return { add: (...c) => c.forEach((x) => s.add(x)), remove: (...c) => c.forEach((x) => s.delete(x)), contains: (c) => s.has(c),
  toggle: (c, on) => { const want = on === undefined ? !s.has(c) : !!on; if (want) s.add(c); else s.delete(c); return want; } }; };
const mkEl = (id = "") => ({ id, className: "", dataset: {}, style: {}, attrs: {}, listeners: {}, kids: {}, appended: [], parent: null, writes: 0, focused: 0, removed: false,
  _html: "", textContent: "", hidden: false, disabled: false, checked: false, value: "", placeholder: "", title: "", classList: classes(),
  get innerHTML() { return this._html; }, set innerHTML(v) { this._html = String(v); this.writes += 1; },
  setAttribute(k, v) { this.attrs[k] = String(v); },
  addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }, removeEventListener(t, fn) { this.listeners[t] = (this.listeners[t] || []).filter((f) => f !== fn); },
  focus() { this.focused += 1; doc.activeElement = this; },
  contains(n) { for (let x = n; x; x = x.parent) if (x === this) return true; return false; },
  // What the markup would hold: one element per selector, the same one each time.
  querySelector(sel) { const kid = (this.kids[sel] ||= mkEl()); kid.parent = this; return kid; },
  closest(sel) { for (let x = this; x; x = x.parent) if (matches(x, sel)) return x; return null; },
  appendChild(child) { child.parent = this; this.appended.push(child); if (child.id) doc.els[child.id] ||= child; return child; },
  remove() { this.removed = true; } });
const node = (parent, data = {}) => { const n = mkEl(); n.parent = parent; n.dataset = { ...data }; return n; };
const IDS = ["hfSearchForm", "hfSearchInput", "hfLimitSelect", "hfSearchBtn", "hfFilters", "hfSizeChips", "hfCapChips", "hfMaskInput", "hfSortSelect", "hfSortDir", "hfLoad", "hfLoadText", "hfLoadFill",
  "hfToken", "hfTokenBtn", "hfTokenStatus", "hfTokenPop", "hfTokenText", "hfTokenInput", "hfTokenSaveBtn", "hfTokenEditBtn", "hfTokenClearBtn", "hfTabs", "hfTabResults", "hfTabFavs",
  "hfListHead", "hfList", "hfRepo", "hfDock", "hfFrontier", "hfDiskBadge", "hfOnDiskBtn", "projectGitBranch", "userChip", "userMenu", "userChipBtn", "userChipName", "userMenuLogout",
  "langSelect", "langTrigger", "langMenu", "langTriggerEmoji", "langTriggerCode", "obBtnLabel"];
// Parents and the hidden attribute as static/hf.html has them.
const PARENTS = { hfTokenBtn: "hfToken", hfTokenPop: "hfToken", hfTokenStatus: "hfTokenBtn", hfTokenText: "hfTokenPop", hfTokenInput: "hfTokenPop", hfTokenSaveBtn: "hfTokenPop",
  hfTokenEditBtn: "hfTokenPop", hfTokenClearBtn: "hfTokenPop", hfSearchInput: "hfSearchForm", hfLimitSelect: "hfSearchForm", hfSearchBtn: "hfSearchForm", hfTabResults: "hfTabs", hfTabFavs: "hfTabs",
  userChipBtn: "userChip", userMenu: "userChip", userChipName: "userChipBtn", userMenuLogout: "userMenu", langTrigger: "langSelect", langMenu: "langSelect", langTriggerEmoji: "langTrigger", langTriggerCode: "langTrigger" };
const HIDDEN = ["hfCapChips", "hfLoad", "hfTokenPop", "hfTokenInput", "hfTokenSaveBtn", "hfTokenClearBtn", "hfDock", "hfFrontier", "hfDiskBadge", "userChip", "userMenu", "langMenu"];
const settle = async () => { for (let i = 0; i < 30; i++) await new Promise((r) => setImmediate(r)); };
// An event the way the browser runs it: the document's capture listeners, then
// the target and its parents (until one stops it), then the document.
const fire = async (target, type, extra = {}) => {
  const ev = { type, target, stopped: false, prevented: false, stopPropagation() { this.stopped = true; }, preventDefault() { this.prevented = true; }, ...extra };
  for (const fn of [...(doc.listeners[`${type}:capture`] || [])]) fn(ev);
  for (let x = target; x && !ev.stopped; x = x.parent) for (const fn of [...(x.listeners[type] || [])]) fn(ev);
  if (!ev.stopped) for (const fn of [...(doc.listeners[type] || [])]) fn(ev);
  await settle();
  return ev;
};
globalThis.fetch = async (path, opts = {}) => {
  const p = String(path);
  globalThis.__fetchCalls.push({ path: p, method: opts.method || "GET", body: opts.body === undefined ? null : opts.body });
  if (gates.has(p)) await gates.get(p);
  if (Object.prototype.hasOwnProperty.call(throws, p)) throw new TypeError(throws[p]);
  const reply = Object.prototype.hasOwnProperty.call(replies, p) ? replies[p] : { ok: true };
  return { json: async () => JSON.parse(JSON.stringify(reply)) };
};
// A request that waits until the pin lets it through.
const gate = (path) => { let open; gates.set(path, new Promise((r) => { open = r; })); return () => { gates.delete(path); open(); }; };
const calls = () => globalThis.__fetchCalls.map((c) => [c.method, c.path, c.body === null ? null : JSON.parse(c.body)]);
const results = (html) => [...html.matchAll(/data-t="hf-result" data-t-id="([^"]+)"/g)].map((m) => m[1]);
const pressed = (html, id) => (html.match(new RegExp(`data-t-id="${id}" aria-pressed="(true|false)"`)) || [])[1];
const runTimers = async () => { const due = timers.splice(0); for (const t of due) await t.fn(); await settle(); };
globalThis.setInterval = (fn, ms) => { intervals.push([ms, fn]); return intervals.length; };
const DEFAULTS = () => ({ "/api/hf/token": { ok: true, set: false }, "/api/hf/favorites": { ok: true, favorites: [] }, "/api/hf/download/jobs": { ok: true, jobs: [] },
  "/api/models/disk": { ok: true, path: "/models", freeGb: 120, totalGb: 1800 }, "/api/hf/reference-models": { ok: true, source: "default", models: FRONTIER() },
  "/health": { ok: true }, "/api/auth/me": { enabled: false } });
const boot = async (over = {}, search = "") => { Object.assign(replies, DEFAULTS(), over); page.location = { search }; page.start(); await settle();
  const made = calls(); globalThis.__fetchCalls.length = 0; return made; };
const reset = () => { localStorage.clear(); globalThis.__fetchCalls.length = 0; replies = {}; throws = {}; gates = new Map(); asked = []; answers = []; timers = []; intervals = []; tourCalls = []; plHidden = 0; reloads = 0;
  globalThis.__plHide = () => { plHidden += 1; };
  globalThis.location = { pathname: "/hf", search: "", reload: () => { reloads += 1; } };
  globalThis.document.body = { dataset: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = String(v); } };
  globalThis.__stubReturns = { "onboarding.initTourButtons": (opts) => { tourCalls.push(["init", opts]); }, "onboarding.autoStartOnce": (key, ready, fn) => { tourCalls.push(["auto", key, ready, fn]); },
    "onboarding.createTour": (config) => { tourCalls.push(["create", config]); return { start: () => tourCalls.push(["start"]) }; } };
  doc = { els: {}, listeners: {}, activeElement: null, body: null, getElementById(id) { return this.els[id] || null; },
    addEventListener(t, fn, capture) { (this.listeners[capture ? `${t}:capture` : t] ||= []).push(fn); },
    removeEventListener(t, fn, capture) { const k = capture ? `${t}:capture` : t; this.listeners[k] = (this.listeners[k] || []).filter((f) => f !== fn); },
    createElement(tag) { const e = mkEl(); e.tag = tag; return e; } };
  doc.body = mkEl("body");
  for (const id of IDS) doc.els[id] = mkEl(id);
  for (const [id, parent] of Object.entries(PARENTS)) doc.els[id].parent = doc.els[parent];
  for (const id of HIDDEN) doc.els[id].hidden = true;
  page = new P.HfPage(doc, { storage: localStorage, later: (fn, ms) => timers.push({ fn, ms }), now: () => 1000, location: { search: "" } });
  page.bench.wait = async () => {};
  page.dialog = { confirm: async (...a) => { asked.push(a); return answers.length ? answers.shift() : false; } }; };
"""

G = "bartowski/gemma-4-12B-it-GGUF"
Q = "unsloth/Qwen3.6-35B-A3B-GGUF"
M = "mlx-community/Llama-4-Scout-17B-16E-4bit"


def enc(s):
    return quote(s, safe="")


def J(value):
    return json.dumps(value, ensure_ascii=False)


FILES_G, LOCAL_G, TREE_G, BENCH_G = (f"/api/hf/files?repo={enc(G)}", f"/api/hf/local-check?repo={enc(G)}",
                                     f"/api/hf/model-tree?repo={enc(G)}", f"/api/hf/benchmarks?repo={enc(G)}")
DIALOG = ('<div class="hf-confirm-box" role="dialog" aria-modal="true"><div class="hf-confirm-title">Delete &lt;b&gt;?</div>'
          '<div class="hf-confirm-body">a\nb</div><div class="hf-confirm-actions"><button type="button" class="hf-confirm-cancel" data-t="hf-confirm-cancel">Cancel</button>'
          '<button type="button" class="hf-confirm-ok danger" data-t="hf-confirm-ok">Delete</button></div></div>')
HEAD = ('<span class="hfp-listhead-count"><span>0 of 0</span></span><span class="hfp-legend" title="Claude Fable 5 64.9\nGPT-5.4 56.8\nGemini 2.5 Flash 20.6\nLlama 4 Scout 13.5">'
        'AA ticks: Claude Fable 5 · GPT-5.4 · Gemini 2.5 Flash · Llama 4 Scout</span><button type="button" class="hfp-link" data-act="frontier" data-t="hf-frontier-open">all 4 ›</button>')
SORT = ('<option value="downloads">Downloads</option><option value="likes">Likes</option><option value="params">Size</option>'
        '<option value="date">Date</option><option value="aa">AA Score</option><option value="olb">Open LLM</option>')
TOKEN_OFF = ["○ not set", "not set — gated models unavailable"]

PINS = [
    ("dialog_answers_no_unless_ok", "",
     r"""await (async () => { const D = new P.HfDialog(doc); const last = () => doc.body.appended[doc.body.appended.length - 1];
        const answer = (p) => Promise.race([p, new Promise((r) => setImmediate(() => r("pending")))]);
        const keyCount = () => (doc.listeners["keydown:capture"] || []).length;
        const p1 = D.confirm("Delete <b>?", "a\nb", "Delete", true); const o1 = last();
        const first = [o1.className, o1.attrs["data-t"], o1.innerHTML, o1.kids[".hf-confirm-ok"].focused, keyCount()];
        o1.kids[".hf-confirm-cancel"].listeners.click[0](); const cancel = [await answer(p1), o1.removed, keyCount()];
        const p2 = D.confirm("Go?", "", "Go", false); const o2 = last();
        const plain = [o2.innerHTML.includes("hf-confirm-body"), o2.innerHTML.includes('<button type="button" class="hf-confirm-ok primary" data-t="hf-confirm-ok">Go</button>')];
        o2.kids[".hf-confirm-ok"].listeners.click[0](); const ok = await answer(p2);
        const p3 = D.confirm("Sure?"); const o3 = last(); const defaults = o3.innerHTML.includes('<button type="button" class="hf-confirm-ok danger" data-t="hf-confirm-ok">Delete</button>');
        o3.listeners.click[0]({ target: o3.kids[".hf-confirm-ok"] }); const insideStays = o3.removed; o3.listeners.click[0]({ target: o3 }); const outside = [await answer(p3), o3.removed];
        const p4 = D.confirm("Esc?"); const o4 = last(); const onKey = doc.listeners["keydown:capture"][0];
        const enter = { key: "Enter", stopped: false, stopPropagation() { this.stopped = true; } }; onKey(enter); const enterStays = [o4.removed, enter.stopped];
        const esc = { key: "Escape", stopped: false, stopPropagation() { this.stopped = true; } }; onKey(esc);
        return [first, cancel, plain, ok, defaults, insideStays, outside, enterStays, [await answer(p4), esc.stopped, o4.removed, keyCount()]]; })()""",
     J([["hf-confirm-overlay", "hf-confirm", DIALOG, 1, 1], [False, True, 0], [False, True], True, True, False, [False, True], [False, False], [False, True, True, 0]]),
     "окно вопроса: разметка с экранированием, фокус на OK; «Отмена», клик мимо окна и Esc — «нет», OK — «да», клик внутри и другие клавиши не закрывают; слушатель клавиш уходит с окном; по умолчанию — «Удалить», опасное"),

    ("start_wires_the_page", "",
     r"""await (async () => { const made = await boot({ "/api/hf/token": { ok: true, set: true, masked: "hf_…Zx9q" }, "/api/hf/favorites": { ok: true, favorites: [{ id: G, downloads: 61351, likes: 17 }] } });
        const e = page.el; const b = globalThis.document.body;
        return { paths: made.map(([m, p]) => `${m} ${p}`).sort(),
          text: [e.searchInput.placeholder, e.searchInput.attrs["aria-label"], e.limit.title, e.limit.attrs["aria-label"], e.searchBtn.textContent, e.sizeChips.attrs["aria-label"], e.capChips.attrs["aria-label"],
                 e.mask.placeholder, e.mask.attrs["aria-label"], e.sort.attrs["aria-label"], e.tokenInput.attrs["aria-label"], e.tokenSave.textContent, e.tokenEdit.textContent, e.tokenClear.textContent,
                 e.onDisk.title, e.onDisk.kids["[data-label]"].textContent],
          sort: e.sort.innerHTML,
          ready: [b.dataset.tState, "tStateDetail" in b.dataset, b.attrs["aria-busy"], plHidden, e.searchInput.focused, intervals.map((i) => i[0])],
          tour: [tourCalls.map((c) => c[0]), tourCalls[0][1].title(), tourCalls[1][1], tourCalls[1][2](), doc.els.obBtnLabel.textContent],
          token: [e.tokenStatus.textContent, e.tokenStatus.classList.contains("is-set"), e.tokenText.textContent, e.tokenPop.hidden, e.tokenEdit.hidden, e.tokenClear.hidden, e.tokenInput.hidden, e.tokenSave.hidden],
          tabs: [e.tabResults.innerHTML, e.tabResults.classList.contains("is-on"), e.tabResults.attrs["aria-selected"], e.tabFavs.innerHTML, e.tabFavs.classList.contains("is-on"), e.tabFavs.attrs["aria-selected"]],
          list: e.list.innerHTML, head: e.listHead.innerHTML,
          chips: [(e.sizeChips.innerHTML.match(/data-t="hf-size-filter"/g) || []).length, e.sizeChips.innerHTML.split("</button>")[0], e.capChips.hidden],
          disk: [e.diskBadge.hidden, e.diskBadge.textContent, e.diskBadge.title, e.diskBadge.classList.contains("low")],
          dock: [e.dock.hidden, e.dock.innerHTML], frontier: [e.frontier.hidden, e.frontier.innerHTML] }; })()""",
     J({"paths": sorted(["GET /api/auth/me", f"GET {BENCH_G}", "GET /api/hf/download/jobs", "GET /api/hf/favorites", f"GET {FILES_G}", f"GET {LOCAL_G}",
                         "GET /api/hf/reference-models", "GET /api/hf/token", "GET /api/models/disk", "GET /health"]),
        "text": ["author/repo or search words…", "Search Hugging Face", "Number of results", "Number of results", "Search", "Model size", "Capabilities", "name contains…",
                 "Filter by file name", "Sort order", "Hugging Face access token", "Save", "Change", "Clear", "Manage downloaded models", "on disk"],
        "sort": SORT,
        "ready": ["ready", False, "false", 1, 1, [60000]],
        "tour": [["init", "auto"], "How to use this page", "hf", True, "Tour"],
        "token": ["● set", True, "Set: hf_…Zx9q", True, False, False, True, True],
        "tabs": ["Results <em>0</em>", True, "true", "★ Favorites <em>1</em>", False, "false"],
        "list": '<div class="hfp-empty">Search to browse repositories</div>', "head": HEAD,
        "chips": [7, '<button type="button" class="hfp-chip is-on is-zero" data-size="all" data-t="hf-size-filter" data-t-id="all" aria-pressed="true">All <em>0</em>', True],
        "disk": [False, "disk: 120 GB free", "/models — 120 GB free of 1800 GB", False],
        "dock": [True, ""], "frontier": [True, ""]}),
     "старт: слова страницы; по одному запросу — токен, избранное (и фоновая догрузка его файлов и бенчмарков), задания, диск, фронтир, версия, пользователь; ready, лоадер скрыт, фокус в поиске, диск раз в минуту; тур; токен задан; вкладки; пустой список зовёт искать; засечки фронтира; бейдж места; док и фронтир скрыты"),

    ("start_counts_loads_that_got_nothing", "",
     r"""await (async () => { for (const p of ["/api/hf/token", "/api/hf/favorites", "/api/hf/download/jobs", "/api/models/disk", "/api/hf/reference-models", "/health", "/api/auth/me"]) throws[p] = "offline";
        await boot(); const e = page.el; const b = globalThis.document.body;
        const failed = [b.dataset.tState, b.dataset.tStateDetail, plHidden, e.tokenStatus.textContent, e.tokenText.textContent, e.diskBadge.hidden, e.listHead.innerHTML, page.downloads.fit(1).known, e.dock.hidden];
        reset(); await boot({ "/api/hf/favorites": { ok: false, error: "unreadable" } });
        return [failed, [globalThis.document.body.dataset.tState, globalThis.document.body.dataset.tStateDetail]]; })()""",
     J([["ready", "2 of 3 initial loads failed", 1, "checking…", "not set — gated models unavailable", True, '<span class="hfp-listhead-count"><span>0 of 0</span></span>', False, True],
        ["ready", "1 of 3 initial loads failed"]]),
     "сбои старта: страница всё равно готова, в состоянии — сколько загрузок ничего не получили (токен, избранное); токен «проверяю…», бейдж скрыт, без фронтира нет засечек, место неизвестно; отказ сервера — тоже сбой"),

    ("address_query_opens_exact_repository", "",
     r"""await (async () => { const made = await boot({ [SEARCH(G)]: { ok: true, repos: [REPOS()[0]] }, [FILES_URL(G)]: FILES(), [LOCAL_URL(G)]: { ok: true, localNames: ["g-Q8_0.gguf"], localFiles: {} } }, `?q=${enc(G)}`);
        const e = page.el; const count = (p) => made.filter(([, path]) => path === p).length;
        return [e.searchInput.value, e.searchInput.focused, page.activeId, [count(SEARCH(G)), count(FILES_URL(G)), count(LOCAL_URL(G)), count(TREE_URL(G)), count(BENCH_URL(G))],
                results(e.list.innerHTML), e.list.innerHTML.includes('class="hfp-row is-active"'), e.repo.innerHTML.includes('data-t="hf-quant" data-t-id="Q4_K_M"'), e.repo.innerHTML.includes('data-act="verify"')]; })()""",
     J([G, 0, G, [1, 1, 1, 1, 1], [G], True, True, True]),
     "?q= в адресе: ищет (без фокуса в поле); точный author/repo открывает репозиторий — файлы, проверка диска, дерево и бенчмарки по одному разу, хотя их просят и выбор, и фоновая догрузка"),

    ("exact_search_keeps_known_counts", "",
     r"""await (async () => { await boot({ "/api/hf/favorites": { ok: true, favorites: [{ id: G, downloads: 61351, likes: 17 }] },
          [SEARCH(G)]: { ok: true, repos: [{ id: G }] }, [SEARCH("x/unknown-GGUF")]: { ok: true, repos: [{ id: "x/unknown-GGUF" }] }, [FILES_URL(G)]: FILES() });
        const e = page.el; e.searchInput.value = G; await page.search(); await page.select(G); await settle();
        const meta = (h) => (h.match(/<span class="hfp-meta">(↓ [^<]*)<span class="hfp-dot">·<\/span>(♥ [^<]*)</) || []).slice(1);
        const row = meta(e.list.innerHTML), head = meta(e.repo.innerHTML);
        globalThis.__fetchCalls.length = 0; await fire(node(node(e.list, { repo: G }), { act: "star" }), "click"); await fire(node(node(e.list, { repo: G }), { act: "star" }), "click");
        const saved = calls().filter(([m, path]) => m === "POST" && path === "/api/hf/favorites").map(([, , b]) => b);
        e.searchInput.value = "x/unknown-GGUF"; await page.search(); await settle();
        return [row, head, saved, meta(e.list.innerHTML)]; })()""",
     J([["↓ 61.4k", "♥ 17"], ["↓ 61.4k", "♥ 17"], [{"favorites": []}, {"favorites": [{"id": G, "downloads": 61351, "likes": 17}]}], ["↓ —", "♥ —"]]),
     "точный author/repo без чисел в ответе: строка и шапка показывают известные числа избранного, звезда сохраняет их, а не нули; репозиторий, чьих чисел никто не знает, — «↓ —», «♥ —»"),

    ("search_states", "",
     r"""await (async () => { await boot(); const e = page.el;
        e.searchInput.value = "   "; await page.search(); const blank = calls().length;
        page.catalog.tab = "favorites"; e.searchInput.value = " gemma 4 "; e.limit.value = "50"; replies[SEARCH("gemma 4", "50")] = { ok: true, repos: REPOS() };
        const release = gate(SEARCH("gemma 4", "50")); const running = page.search(); await settle();
        const during = [e.searchBtn.disabled, page.catalog.tab, e.list.innerHTML];
        release(); await running; await settle(); const found = [e.searchBtn.disabled, results(e.list.innerHTML), page.activeId];
        replies[SEARCH("x", "50")] = { ok: false, error: "rate limited" }; e.searchInput.value = "x"; await page.search(); await settle(); const refused = [e.list.innerHTML, page.catalog.resultIds.length];
        replies[SEARCH("y", "50")] = { ok: false }; e.searchInput.value = "y"; await page.search(); await settle(); const bare = e.list.innerHTML;
        throws[SEARCH("z", "50")] = "offline"; e.searchInput.value = "z"; await page.search(); await settle(); const thrown = [e.list.innerHTML, e.searchBtn.disabled];
        replies[SEARCH("a/b", "50")] = { ok: true, repos: REPOS().slice(0, 2) }; e.searchInput.value = "a/b"; await page.search(); await settle(); const slashTwo = [page.activeId, results(e.list.innerHTML).length];
        replies[SEARCH("none", "50")] = { ok: true, repos: [] }; e.searchInput.value = "none"; await page.search(); await settle();
        const submit = await fire(e.searchForm, "submit");
        return [blank, during, found, refused, bare, thrown, slashTwo, e.list.innerHTML, submit.prevented]; })()""",
     J([0, [True, "results", '<div class="hfp-empty">Searching…</div>'], [False, [Q, G, M], None], ['<div class="hfp-error">rate limited</div>', 0],
        '<div class="hfp-error">Error</div>', ['<div class="hfp-error">offline</div>', False], [None, 2], '<div class="hfp-empty">No results</div>', True]),
     "поиск: пустые слова — без запроса; во время — «Searching…», кнопка выключена, вкладка «результаты»; слова обрезаны, лимит из списка; результаты по загрузкам; отказ, пустой отказ и сеть — в списке; несколько по author/repo — не открывает; ничего — «No results»; отправка формы не перезагружает страницу"),

    ("background_bar_counts_files_then_benchmarks", "",
     r"""await (async () => { await boot(); const e = page.el; const bar = () => [e.load.hidden, e.loadText.textContent, e.loadFill.style.width];
        replies[SEARCH("gemma")] = { ok: true, repos: REPOS() }; const filesM = gate(FILES_URL(M)); const benchQ = gate(BENCH_URL(Q));
        e.searchInput.value = "gemma"; await page.search(); await settle(); const files = bar();
        filesM(); await settle(); const bench = bar(); benchQ(); await settle(); const done = bar();
        const X1 = "a/x1-GGUF", X2 = "a/x2-GGUF", X3 = "b/x3-GGUF";
        replies[SEARCH("r1")] = { ok: true, repos: [{ id: X1 }, { id: X2 }] }; replies[SEARCH("r2")] = { ok: true, repos: [{ id: X3 }] };
        const filesX1 = gate(FILES_URL(X1)); e.searchInput.value = "r1"; await page.search(); await settle(); const first = bar();
        e.searchInput.value = "r2"; await page.search(); await settle(); const second = bar();
        filesX1(); await settle();
        return [files, bench, done, first, second, bar(), [page.filesDone, page.filesTotal]]; })()""",
     J([[False, "files 2/3", "67%"], [False, "benchmarks 1/3", "33%"], [True, "", "0%"], [False, "files 1/2", "50%"], [True, "", "0%"], [True, "", "0%"], [1, 1]]),
     "полоса: сначала файлы (2/3, 67%), потом бенчмарки (1/3), потом скрыта; новый поиск забирает счёт — запоздавший ответ старого круга не считается"),

    ("filters_by_clicks", "",
     r"""await (async () => { await boot({ [SEARCH("gemma")]: { ok: true, repos: REPOS() }, [FILES_URL(G)]: FILES() }); const e = page.el; e.searchInput.value = "gemma"; await page.search(); await settle();
        const ids = () => results(e.list.innerHTML);
        const initial = [ids(), [...e.capChips.innerHTML.matchAll(/data-cap="([^"]+)"/g)].map((m) => m[1]), e.capChips.hidden];
        await fire(node(e.sizeChips, { size: "10-19" }), "click"); const sized = [ids(), pressed(e.sizeChips.innerHTML, "10-19"), pressed(e.sizeChips.innerHTML, "all"), e.listHead.innerHTML.includes("<span>2 of 3</span>")];
        await fire(node(e.capChips, { cap: "mmproj" }), "click"); const capped = [ids(), pressed(e.capChips.innerHTML, "mmproj")];
        await fire(node(e.capChips, { cap: "mmproj" }), "click"); const uncapped = [ids(), pressed(e.capChips.innerHTML, "mmproj")];
        await fire(node(e.sizeChips, {}), "click"); const beside = page.catalog.size;
        e.mask.value = "LLAMA"; await fire(e.mask, "input"); const masked = ids();
        e.mask.value = "qwen"; await fire(e.mask, "input"); const none = e.list.innerHTML;
        e.mask.value = ""; await fire(e.mask, "input"); e.sort.value = "likes"; await fire(e.sort, "change"); const byLikes = ids();
        await fire(e.sortDir, "click"); const asc = [ids(), e.sortDir.textContent, e.sortDir.title, e.sortDir.attrs["aria-label"]];
        await fire(node(e.tabs, { tab: "favorites" }), "click");
        const favs = [page.catalog.tab, e.list.innerHTML, e.tabFavs.classList.contains("is-on"), e.tabFavs.attrs["aria-selected"], e.tabResults.classList.contains("is-on"), e.tabResults.attrs["aria-selected"]];
        return [initial, sized, capped, uncapped, beside, masked, none, [byLikes, ...asc], favs]; })()""",
     J([[[Q, G, M], ["it", "vision", "mmproj"], False], [[G, M], "true", "false", True], [[G], "true"], [[G, M], "false"], "10-19", [M],
        '<div class="hfp-empty">No matches for the filter</div>', [[G, M], [M, G], "↑", "Ascending — press for descending", "Ascending — press for descending"],
        ["favorites", '<div class="hfp-empty">No favorites yet — ☆ on a repository keeps it here</div>', True, "true", False, "false"]]),
     "фильтры кликами: чип размера нажат и сужает список (2 из 3); возможность — вкл/выкл; клик мимо чипа — ничего; маска по имени без регистра; ничего не подошло — своё сообщение; порядок и направление ↑ с подсказкой; вкладка избранного"),

    ("list_row_markup", "",
     r"""await (async () => { await boot({ "/api/hf/favorites": { ok: true, favorites: [{ id: G, downloads: 61351, likes: 17 }, { id: "tinymodel", downloads: 5, likes: 0 }] },
          [SEARCH("gemma")]: { ok: true, repos: REPOS() }, [FILES_URL(G)]: FILES(), [LOCAL_URL(G)]: { ok: true, localNames: ["g-Q8_0.gguf", "mmproj-g-bf16.gguf"], localFiles: {} },
          [BENCH_URL(G)]: { ok: true, scores: { aa_intelligence: 14.2 }, inline: ["aa_intelligence"] } });
        const e = page.el; e.searchInput.value = "gemma"; await page.search(); await settle(); await fire(node(node(e.list, { repo: G }), {}), "click");
        const row = (id) => e.list.innerHTML.split(/(?=<div class="hfp-row(?: is-active)?" data-repo=)/).find((r) => r.includes(`data-repo="${id}"`)) || "";
        const g = row(G), q = row(Q), m = row(M);
        const out = [g.startsWith(`<div class="hfp-row is-active" data-repo="${G}" data-t="hf-result" data-t-id="${G}" role="button" tabindex="0" aria-current="true">`),
          g.includes(`<span class="hfp-name" title="${G}"><span class="hfp-author">bartowski/</span><b>gemma-4-12B-it-GGUF</b></span><span class="hfp-badge is-fmt">GGUF</span>`),
          g.includes('<span class="hfp-icons"><span class="hfp-icon" title="it — Instruction-tuned">🤖</span><span class="hfp-icon" title="vision — Accepts images">👁</span><span class="hfp-icon" title="mmproj — Has a vision projector (mmproj)">📷</span></span>'),
          g.includes(`<button type="button" class="hfp-star is-on" data-act="star" data-t="hf-star" data-t-id="${G}" aria-pressed="true" title="Remove from favorites" aria-label="Remove from favorites">★</button>`),
          g.includes('<span class="hfp-meta">↓ 61.4k<span class="hfp-dot">·</span>♥ 17<span class="hfp-dot">·</span><b class="hfp-params">12B</b><span class="hfp-dot">·</span><span title="2026-08-10T00:00:00.000Z">1mo ago</span></span>'),
          g.includes('<span class="hfp-local" title="Files on disk: 2">✓ 2</span>'), g.includes('class="hfp-aa-fill"'),
          q.startsWith(`<div class="hfp-row" data-repo="${Q}"`) && q.includes('aria-current="false"'),
          q.includes('aria-pressed="false" title="Add to favorites" aria-label="Add to favorites">☆</button>'),
          q.includes('↓ 250.0k<span class="hfp-dot">·</span>♥ 420<span class="hfp-dot">·</span><b class="hfp-params">35B</b><span class="hfp-dot">·</span><span title="2026-05-01T00:00:00.000Z">4mo ago</span>'),
          q.includes("hfp-local"), q.includes('<span class="hfp-aa is-none">no data</span>'),
          m.includes('<span class="hfp-badge is-fmt">MLX</span>') && m.includes('<b class="hfp-params">17B</b>') && m.includes(">1y ago</span>")];
        await fire(node(e.tabs, { tab: "favorites" }), "click"); const t = row("tinymodel");
        return [...out, results(e.list.innerHTML), t.includes('<span class="hfp-name" title="tinymodel"><b>tinymodel</b></span><span class="hfp-icons"></span>'), t.includes('<span class="hfp-meta">↓ 5<span class="hfp-dot">·</span>♥ 0</span>')]; })()""",
     J([True, True, True, True, True, True, True, True, True, True, False, True, True, [G, "tinymodel"], True, True]),
     "строка списка: выбранная и в избранном; автор/модель, формат, значки возможностей, загрузки, лайки, размер, возраст, ✓ файлов на диске, полоса AA; чужая — ☆, без ✓, «нет данных»; MLX и «1y ago»; имя без автора — без формата, размера и даты"),

    ("list_row_counts_library_copies", "",
     r"""await (async () => { await boot({ [SEARCH("gemma")]: { ok: true, repos: REPOS() },
          [LOCAL_URL(G)]: { ok: true, localNames: ["g-Q8_0.gguf"], localFiles: {}, libraryFiles: { "g-Q4_K_M.gguf": [{ store: { id: "a", name: "lama-caravan-models" }, size: 1, mtime: 1 }],
            "g-Q6_K.gguf": [{ store: { id: "a", name: "lama-caravan-models" }, size: 1, mtime: 1 }, { store: { id: "b", name: "second-shelf" }, size: 1, mtime: 1 }] } },
          [LOCAL_URL(Q)]: { ok: true, localNames: [], localFiles: {}, libraryFiles: { "q.gguf": [{ store: { id: "a", name: "lama-caravan-models" }, size: 1, mtime: 1 }] } } });
        const e = page.el; e.searchInput.value = "gemma"; await page.search(); await settle();
        const row = (id) => e.list.innerHTML.split(/(?=<div class="hfp-row(?: is-active)?" data-repo=)/).find((r) => r.includes(`data-repo="${id}"`)) || "";
        const g = row(G), q = row(Q), m = row(M);
        return [g.includes('<span class="hfp-local" title="Files on disk: 1">✓ 1</span><span class="hfp-lib" data-t="hf-in-library" data-t-id="' + G + '" title="Files in a library: 2 · lama-caravan-models, second-shelf">📚 2</span>'),
                q.includes("hfp-local"), q.includes('title="Files in a library: 1 · lama-caravan-models">📚 1</span>'), m.includes("hfp-lib")]; })()""",
     J([True, False, True, False]),
     "строка списка: «✓ N» — на этом диске, рядом «📚 N» — в библиотеках, с их названиями в подсказке; только в библиотеке — одна «📚»; нигде — ничего"),

    ("star_saves_favorites_without_selecting", "",
     r"""await (async () => { await boot({ [SEARCH("gemma")]: { ok: true, repos: REPOS() } }); const e = page.el; e.searchInput.value = "gemma"; await page.search(); await settle(); globalThis.__fetchCalls.length = 0;
        const ev = await fire(node(node(e.list, { repo: Q }), { act: "star" }), "click");
        const first = [calls(), page.catalog.favoriteIds, page.activeId, ev.stopped, e.tabFavs.innerHTML, e.list.innerHTML.includes(`class="hfp-star is-on" data-act="star" data-t="hf-star" data-t-id="${Q}"`)];
        globalThis.__fetchCalls.length = 0; throws["/api/hf/favorites"] = "offline"; await fire(node(node(e.list, { repo: Q }), { act: "star" }), "click");
        await fire(node(e.list, {}), "click");
        return [first, calls(), page.catalog.favoriteIds, doc.els.hfToast.textContent, doc.els.hfToast.classList.contains("show"), page.activeId]; })()""",
     J([[[["POST", "/api/hf/favorites", {"favorites": [{"id": Q, "downloads": 250000, "likes": 420, "createdAt": "2026-05-01T00:00:00.000Z", "tags": ["gguf"]}]}]], [Q], None, True, "★ Favorites <em>1</em>", True],
        [["POST", "/api/hf/favorites", {"favorites": []}]], [], "network error", True, None]),
     "звезда в строке: избранное уходит на сервер целиком (новое первым), строку не выбирает; сбой сохранения — тост «network error», звезда остаётся снятой (as-is); клик по списку мимо строки — ничего"),

    ("held_pointer_holds_the_list", "",
     r"""await (async () => { await boot(); const e = page.el; page.catalog.setResults(REPOS()); page.renderList(); const w0 = e.list.writes;
        await fire(node(e.list, { repo: G }), "pointerdown"); page.catalog.setResults(REPOS().slice(0, 1)); page.renderList(); const held = [e.list.writes - w0, page.listPending];
        await fire(node(null, {}), "pointerup"); const released = [e.list.writes - w0, page.listPending, results(e.list.innerHTML)];
        await fire(node(null, {}), "pointerup"); const idle = e.list.writes - w0;
        await fire(node(e.list, { repo: G }), "pointerdown"); await fire(node(null, {}), "pointercancel");
        return [held, released, idle, [page.holding, e.list.writes - w0]]; })()""",
     J([[0, True], [1, False, [G]], 1, [False, 1]]),
     "зажатая кнопка над списком: перерисовка ждёт отпускания и выполняется один раз; отпускание без ожидания — ничего; pointercancel тоже отпускает"),

    ("paint_only_changes_and_keeps_focus", "",
     r"""(() => { const el = mkEl("box"); const a = page.paint(el, "<b>1</b>"); const b = page.paint(el, "<b>1</b>"); const c = page.paint(null, "<b>1</b>");
        doc.activeElement = node(el, { t: "hf-star", tId: "a/b" }); page.paint(el, "<b>2</b>");
        const key = '[data-t="hf-star"][data-t-id="a/b"]'; const refocused = el.kids[key] ? el.kids[key].focused : 0;
        doc.activeElement = node(null, { repo: "z" }); page.paint(el, "<b>3</b>");
        return [a, b, c, el.writes, el.innerHTML, refocused, Object.keys(el.kids), page.focusKey({ dataset: { repo: "x/y" } }), page.focusKey({ dataset: { act: "download" } }),
                page.focusKey({ dataset: { t: "hf-tab" } }), page.focusKey({}), page.focusKey({ dataset: { t: "x", tId: 'q"\\' } }) === '[data-t="x"][data-t-id="q\\"\\\\"]']; })()""",
     J([True, False, False, 3, "<b>3</b>", 1, ['[data-t="hf-star"][data-t-id="a/b"]'], '[data-repo="x/y"]', '[data-act="download"]', "", "", True]),
     "перерисовка: та же разметка — не пишется; фокус внутри контейнера возвращается на тот же элемент (по data-t+id, репозиторию или действию, кавычки экранированы); фокус снаружи — не трогается"),

    ("select_loads_and_reports", "",
     r"""await (async () => { await boot({ [FILES_URL(G)]: FILES(), [LOCAL_URL(G)]: { ok: true, localNames: [], localFiles: {} }, [TREE_URL(G)]: { ok: true, base: [], quantizations: [] } });
        const e = page.el; page.catalog.setResults(REPOS()); page.renderAll(); globalThis.__fetchCalls.length = 0;
        const openFiles = gate(FILES_URL(G)); await fire(node(node(e.list, { repo: G }), {}), "click");
        const loading = [calls().map(([, p]) => p), page.activeId, e.repo.innerHTML.includes('class="hfp-repo-head"') && e.repo.innerHTML.includes('<div class="hfp-empty">Loading…</div>'), e.list.innerHTML.includes(`class="hfp-row is-active" data-repo="${G}"`)];
        openFiles(); await settle(); const loaded = [e.repo.innerHTML.includes('data-t="hf-quant" data-t-id="Q4_K_M"'), page.stateFor(G).error];
        globalThis.__fetchCalls.length = 0; await page.select(G); await settle(); const again = calls().map(([, p]) => p);
        replies[FILES_URL(M)] = { ok: false, error: "gated" }; replies[TREE_URL(M)] = { ok: false }; await page.select(M); await settle();
        const gated = [e.repo.innerHTML.includes('<div class="hfp-error">gated</div>'), page.catalog.repo(M).tree === undefined];
        globalThis.__fetchCalls.length = 0; replies[FILES_URL(M)] = FILES(); await page.select(M); await settle();
        const retried = [calls().map(([, p]) => p).sort(), page.stateFor(M).error, e.repo.innerHTML.includes("hfp-error")];
        throws[FILES_URL(Q)] = "offline"; await page.select(Q); await settle(); const thrown = e.repo.innerHTML.includes('<div class="hfp-error">offline</div>');
        const keys = [];
        for (const [target, key] of [[node(e.list, { repo: G }), "Enter"], [node(node(e.list, { repo: M }), { act: "star" }), "Enter"], [node(e.list, { repo: Q }), "a"], [node(e.list, { repo: M }), " "]]) {
          const ev = await fire(target, "keydown", { key }); keys.push([page.activeId, ev.prevented]); }
        return [loading, loaded, again, gated, retried, thrown, keys]; })()""",
     J([[[TREE_G, BENCH_G, FILES_G, LOCAL_G], G, True, True], [True, ""], [LOCAL_G], [True, True],
        [sorted([f"/api/hf/files?repo={enc(M)}", f"/api/hf/local-check?repo={enc(M)}", f"/api/hf/model-tree?repo={enc(M)}"]), "", False], True,
        [[G, True], [G, False], [G, False], [M, True]]]),
     "выбор: дерево, бенчмарки, файлы и диск; пока грузится — шапка и «Loading…»; повторный выбор — только диск; отказ файлов — ошибка в панели, дерево без ответа спрашивается снова; сеть — ошибка; Enter и пробел на строке выбирают, на кнопке в строке — нет"),

    ("repository_controls", "",
     r"""await (async () => { await boot({ [FILES_URL(G)]: FILES(), [LOCAL_URL(G)]: { ok: true, localNames: ["g-Q8_0.gguf"], localFiles: {} } });
        const e = page.el; page.catalog.setResults(REPOS()); await page.select(G); await settle(); globalThis.__fetchCalls.length = 0;
        const click = (data) => fire(node(e.repo, data), "click"); const st = () => page.stateFor(G);
        await click({ act: "bench" }); const benchOpen = [st().benchOpen, e.repo.innerHTML.includes('data-t="hf-bench-panel"')]; await click({ act: "bench" }); const benchClosed = st().benchOpen;
        await click({ act: "bench-refresh" }); const refreshed = calls().map(([, p]) => p);
        await click({ act: "low", bits: "2" }); const lowOpen = [...st().lowOpen]; await click({ act: "low", bits: "2" }); const lowClosed = [...st().lowOpen];
        await click({ act: "tree" }); await click({ act: "other" }); const cards = [st().treeOpen, st().otherOpen];
        await click({ act: "star" }); const starred = [page.catalog.favoriteIds, calls().slice(-1)[0][1]];
        await click({ act: "frontier" }); const frontier = [page.frontierOpen, page.frontierFor, e.frontier.hidden]; page.closeFrontier();
        await click({ act: "checkpoint" }); const noCheckpoint = asked.length;
        page.catalog.repo(G).meta.safetensors = { format: "safetensors", totalSize: 24e9, files: [{ path: "model.safetensors", name: "model.safetensors", size: 24e9 }] };
        await click({ act: "checkpoint" }); const checkpoint = asked.map((a) => a[0]);
        const before = JSON.stringify([...page.repoStates.get(G).lowOpen, st().benchOpen, st().treeOpen, st().otherOpen]); await click({ act: "unknown" }); await click({});
        const untouched = before === JSON.stringify([...page.repoStates.get(G).lowOpen, st().benchOpen, st().treeOpen, st().otherOpen]);
        await click({ act: "open-repo", repo: Q }); const opened = page.activeId;
        page.activeId = null; const states = page.repoStates.size; await click({ act: "bench" });
        return [benchOpen, benchClosed, refreshed, lowOpen, lowClosed, cards, starred, frontier, noCheckpoint, checkpoint, untouched, opened, page.repoStates.size - states]; })()""",
     J([[True, True], False, [f"{BENCH_G}&force=1"], [2], [], [True, True], [[G], "/api/hf/favorites"], [True, G, False], 0, ["⬇ safetensors · 22.4 GB"], True, Q, 0]),
     "кнопки репозитория: панель бенчмарков и обновление с force=1; низкие группы по числу бит; дерево и прочие файлы; звезда; фронтир с меткой репозитория; чекпойнт — только если он есть (вопрос); чужое действие и клик мимо — ничего; переход в другой репозиторий; без выбранного — ничего"),

    ("checkbox_picks_named_files", "",
     r"""await (async () => { await boot({ [FILES_URL(G)]: FILES() }); const e = page.el; page.catalog.setResults(REPOS()); await page.select(G); await settle();
        const box = (paths, checked) => { const n = node(e.repo, { act: "pick", paths: JSON.stringify(paths) }); n.checked = checked; return n; };
        await fire(box(["g-Q4_K_M.gguf", "mmproj-g-bf16.gguf", "not-there.gguf"], true), "change");
        const picked = [page.downloads.picks(G), e.dock.hidden, e.dock.innerHTML.includes('<span class="hfp-sel">Selected 2 · 7.2 GB</span>'), e.repo.innerHTML.includes('data-t="hf-file-check" data-t-id="g-Q4_K_M.gguf" checked')];
        await fire(box(["g-Q4_K_M.gguf"], false), "change"); const unpicked = page.downloads.picks(G);
        await fire(node(e.repo, { act: "bench" }), "change"); const notABox = page.downloads.picks(G);
        page.activeId = null; await fire(box(["g-Q8_0.gguf"], true), "change");
        return [picked, unpicked, notABox, page.downloads.count()]; })()""",
     J([[["g-Q4_K_M.gguf", "mmproj-g-bf16.gguf"], False, True, True], ["mmproj-g-bf16.gguf"], ["mmproj-g-bf16.gguf"], 1]),
     "галочка: выбирает файлы, которые называет (чужих имён нет в списке репозитория — не берёт), док появляется с размером, галочка отмечена; снятая — убирает; не галочка и без выбранного репозитория — ничего"),

    ("verify_polls_by_bytes", "",
     r"""await (async () => { await boot({ [FILES_URL(G)]: FILES(), [LOCAL_URL(G)]: { ok: true, localNames: ["g-Q8_0.gguf"], localFiles: {} } }); const e = page.el; page.catalog.setResults(REPOS()); await page.select(G); await settle(); globalThis.__fetchCalls.length = 0;
        replies["/api/hf/verify"] = { ok: true, jobId: "v1" }; replies["/api/hf/verify?job=v1"] = { ok: true, job: { done: false, bytesDone: 50, totalBytes: 200, files: { "g-Q8_0.gguf": { state: "running" } } } };
        await fire(node(e.repo, { act: "verify" }), "click");
        const running = [calls(), page.stateFor(G).verify, page.stateFor(G).verified, timers.map((t) => t.ms), e.repo.innerHTML.includes(" disabled>Verifying… 25%</button>")];
        replies["/api/hf/verify?job=v1"] = { ok: true, job: { done: true, bytesDone: 200, totalBytes: 200, files: { "g-Q8_0.gguf": { state: "ok" } } } }; await runTimers();
        const done = [page.stateFor(G).verify, page.stateFor(G).verified, timers.length, doc.els.hfToast ? doc.els.hfToast.textContent : ""];
        replies["/api/hf/verify?job=v1"] = { ok: true, job: { done: true, error: "hash mismatch", files: {} } }; await page.verify(G); await settle(); const failedJob = doc.els.hfToast.textContent;
        replies["/api/hf/verify?job=v1"] = { ok: false }; await page.verify(G); await settle(); const gone = page.stateFor(G).verify;
        const toasts = [];
        for (const reply of [{ ok: false, error: "busy" }, { ok: false }]) { replies["/api/hf/verify"] = reply; await page.verify(G); await settle(); toasts.push([doc.els.hfToast.textContent, page.stateFor(G).verify]); }
        throws["/api/hf/verify"] = "offline"; await page.verify(G); await settle(); toasts.push([doc.els.hfToast.textContent, page.stateFor(G).verify]);
        return [running, done, failedJob, gone, toasts]; })()""",
     J([[[["POST", "/api/hf/verify", {"repo": G}], ["GET", "/api/hf/verify?job=v1", None]], {"running": True, "pct": 25}, {"g-Q8_0.gguf": {"state": "running"}}, [700], True],
        [None, {"g-Q8_0.gguf": {"state": "ok"}}, 0, ""], "hash mismatch", None,
        [["busy", None], ["Verification could not start", None], ["network error", None]]]),
     "проверка sha256: запуск, опрос раз в 700 мс с долей по байтам, кнопка выключена; итог — по файлам без тоста; ошибка задания — тост; задание пропало — проверка снята; отказ запуска — тост с причиной, без причины и при сбое сети — свой"),

    ("delete_asks_and_stops_at_failure", "",
     r"""await (async () => { await boot({ [FILES_URL(G)]: FILES(), [LOCAL_URL(G)]: { ok: true, localNames: ["g-Q8_0.gguf", "g-Q4_K_M.gguf", "mmproj-g-bf16.gguf"], localFiles: {} } });
        const e = page.el; page.catalog.setResults(REPOS()); await page.select(G); await settle(); globalThis.__fetchCalls.length = 0;
        const names = ["g-Q8_0.gguf", "g-Q4_K_M.gguf", "mmproj-g-bf16.gguf"]; const DEL = (n) => `/api/hf/local-file?repo=${enc(G)}&name=${enc(n)}`;
        const click = () => fire(node(e.repo, { act: "delete", names: JSON.stringify(names) }), "click");
        await fire(node(e.repo, { act: "delete", names: "[]" }), "click"); const empty = [asked.length, calls().length];
        answers = [false]; await click(); const declined = [asked, calls().length];
        asked = []; answers = [true]; replies[DEL(names[1])] = { ok: false, error: "busy" }; const openLocal = gate(LOCAL_URL(G)); await click();
        const partial = [calls().map(([m, p]) => `${m} ${p}`), [...page.catalog.repo(G).localNames], doc.els.hfToast.textContent];
        openLocal(); await settle(); globalThis.__fetchCalls.length = 0; delete replies[DEL(names[1])]; throws[DEL(names[0])] = "offline"; answers = [true]; await click();
        return [empty, declined, partial, [calls().map(([m, p]) => `${m} ${p}`), doc.els.hfToast.textContent]]; })()""",
     J([[0, 0], [[["Delete local file?", "g-Q8_0.gguf\ng-Q4_K_M.gguf\nmmproj-g-bf16.gguf", "Delete", True]], 0],
        [[f"DELETE /api/hf/local-file?repo={enc(G)}&name=g-Q8_0.gguf", f"DELETE /api/hf/local-file?repo={enc(G)}&name=g-Q4_K_M.gguf", f"GET {LOCAL_G}"],
         ["g-Q4_K_M.gguf", "mmproj-g-bf16.gguf"], "Failed to delete: busy"],
        [[f"DELETE /api/hf/local-file?repo={enc(G)}&name=g-Q8_0.gguf", f"GET {LOCAL_G}"], "Failed to delete: network error"]]),
     "удаление: пустой список — ничего; всегда сначала вопрос со списком (опасное); «нет» — ни одного запроса; удаляет по одному, на первом отказе останавливается с тостом, удалённое уходит из отметок, потом диск перечитывается; сбой сети — тоже остановка"),

    ("token_popover", "",
     r"""await (async () => { await boot(); const e = page.el;
        const look = () => [e.tokenStatus.textContent, e.tokenText.textContent, e.tokenPop.hidden, e.tokenBtn.attrs["aria-expanded"], e.tokenInput.hidden, e.tokenSave.hidden, e.tokenEdit.hidden, e.tokenClear.hidden];
        const start = look(); await fire(e.tokenBtn, "click"); const opened = look();
        answers = [false]; await fire(e.tokenEdit, "click"); const declinedEdit = [asked.pop(), page.tokenEditing];
        answers = [true]; await fire(e.tokenEdit, "click"); const editing = [look(), e.tokenInput.focused];
        e.tokenInput.value = "  hf_example_value  "; replies["/api/hf/token"] = { ok: true, set: true, masked: "hf_…alue" };
        globalThis.__fetchCalls.length = 0; await fire(e.tokenSave, "click"); const saved = [calls(), look(), e.tokenInput.value, e.tokenSave.disabled];
        answers = [true]; await fire(e.tokenEdit, "click"); e.tokenInput.value = "abc"; const esc = await fire(e.tokenInput, "keydown", { key: "Escape" });
        const escaped = [page.tokenEditing, e.tokenInput.value, e.tokenPop.hidden, esc.stopped];
        answers = [true]; await fire(e.tokenEdit, "click"); e.tokenInput.value = " hf_second "; globalThis.__fetchCalls.length = 0; await fire(e.tokenInput, "keydown", { key: "Enter" }); const entered = calls();
        await fire(node(e.tokenPop, {}), "click"); const insideStays = e.tokenPop.hidden;
        const overlay = mkEl(); overlay.className = "hf-confirm-overlay"; await fire(node(overlay, {}), "click"); const overlayStays = e.tokenPop.hidden;
        await fire(node(null, {}), "click"); const outsideCloses = [e.tokenPop.hidden, page.tokenEditing];
        await fire(e.tokenBtn, "click"); await fire(node(null, {}), "keydown", { key: "Escape" }); const escCloses = e.tokenPop.hidden;
        answers = [false]; globalThis.__fetchCalls.length = 0; await fire(e.tokenClear, "click"); const clearDeclined = [asked.pop(), calls().length];
        answers = [true]; replies["/api/hf/token"] = { ok: true, set: false }; await fire(e.tokenClear, "click"); const cleared = [calls(), look()];
        answers = [true]; await page.editToken(); throws["/api/hf/token"] = "offline"; e.tokenInput.value = "x"; await page.saveToken(); const failedSave = [page.tokenEditing, doc.els.hfToast.textContent, e.tokenSave.disabled];
        return { start, opened, declinedEdit, editing, saved, escaped, entered, insideStays, overlayStays, outsideCloses, escCloses, clearDeclined, cleared, failedSave }; })()""",
     J({"start": TOKEN_OFF + [True, "false", True, True, False, True], "opened": TOKEN_OFF + [False, "true", True, True, False, True],
        "declinedEdit": [["Change HF token?", "", "Change", False], False], "editing": [TOKEN_OFF + [False, "true", False, False, True, True], 1],
        "saved": [[["POST", "/api/hf/token", {"token": "hf_example_value"}]], ["● set", "Set: hf_…alue", False, "true", True, True, False, False], "", False],
        "escaped": [False, "", False, True], "entered": [["POST", "/api/hf/token", {"token": "hf_second"}]],
        "insideStays": False, "overlayStays": False, "outsideCloses": [True, False], "escCloses": True,
        "clearDeclined": [["Clear HF token?", "", "Clear", True], 0],
        "cleared": [[["POST", "/api/hf/token", {"token": ""}], ["GET", "/api/hf/token", None]], TOKEN_OFF + [True, "false", True, True, False, True]],
        "failedSave": [True, "offline", False]}),
     "токен: статус и поповер; «изменить» только после вопроса, поле с фокусом; сохранение обрезает пробелы, показывает маску с сервера и чистит поле; Esc в поле отменяет правку, не закрывая поповер; Enter сохраняет; клик внутри и в окне вопроса не закрывает, снаружи и Esc — закрывают; «очистить» после опасного вопроса и перечитывает; сбой сохранения — тост, правка остаётся"),

    ("disk_badge_by_free_space", "",
     r"""await (async () => { await boot(); const e = page.el;
        const look = () => [e.diskBadge.hidden, e.diskBadge.textContent, e.diskBadge.title, e.diskBadge.classList.contains("low"), e.diskBadge.classList.contains("critical"), page.downloads.fit(0).known];
        const out = [look()];
        for (const freeGb of [49, 14, 50]) { replies["/api/models/disk"] = { ok: true, path: "/models", freeGb, totalGb: 1800 }; await page.refreshDisk(); out.push(look()); }
        replies["/api/models/disk"] = { ok: false, error: "no dir" }; await page.refreshDisk(); out.push(look());
        throws["/api/models/disk"] = "offline"; await page.refreshDisk(); out.push(look());
        delete throws["/api/models/disk"]; globalThis.__fetchCalls.length = 0; intervals[0][1](); await settle(); out.push(calls().map(([, p]) => p));
        return out; })()""",
     J([[False, "disk: 120 GB free", "/models — 120 GB free of 1800 GB", False, False, True],
        [False, "disk: 49 GB free", "/models — 49 GB free of 1800 GB", True, False, True],
        [False, "disk: 14 GB free", "/models — 14 GB free of 1800 GB", True, True, True],
        [False, "disk: 50 GB free", "/models — 50 GB free of 1800 GB", False, False, True],
        [True, "disk: 50 GB free", "/models — 50 GB free of 1800 GB", False, False, False],
        [True, "disk: 50 GB free", "/models — 50 GB free of 1800 GB", False, False, False],
        ["/api/models/disk"]]),
     "бейдж места: свободно и всего; меньше 50 GB — жёлтый, меньше 15 — красный; нет ответа или сбой — скрыт, место для загрузок неизвестно (текст остаётся прежним, as-is); таймер перечитывает диск"),

    ("header_version_user_language", "",
     r"""await (async () => { localStorage.setItem("llamacppAdminLang", "ru");
        await boot({ "/health": { ok: true, version: "1.3.350", commit: "abc1234" }, "/api/auth/me": { enabled: true, authenticated: true, user: "operator", role: "viewer" } });
        const $ = (id) => doc.els[id];
        const version = [$("projectGitBranch").textContent, $("projectGitBranch").title]; const user = [$("userChip").hidden, $("userChipName").textContent];
        const ub = await fire($("userChipBtn"), "click"); const menuOpen = [$("userMenu").hidden, $("userChipBtn").attrs["aria-expanded"], ub.stopped];
        await fire(node(null, {}), "click"); const menuClosed = [$("userMenu").hidden, $("userChipBtn").attrs["aria-expanded"]];
        const lang = [$("langTriggerEmoji").textContent, $("langTriggerCode").textContent, $("langTrigger").attrs["aria-label"], ($("langMenu").innerHTML.match(/class="lang-option/g) || []).length,
          $("langMenu").innerHTML.includes('<li class="lang-option selected" role="option" data-lang="ru" aria-selected="true"><span class="lang-emoji">🪆</span><span class="lang-name">Русский</span></li>'),
          $("langMenu").innerHTML.includes('<li class="lang-option" role="option" data-lang="id" aria-selected="false"><span class="lang-emoji">🦎</span><span class="lang-name">Bahasa Indonesia</span></li>')];
        await fire($("langTrigger"), "click"); const langOpen = [$("langMenu").hidden, $("langTrigger").attrs["aria-expanded"]];
        const option = node($("langMenu"), { lang: "de" }); option.className = "lang-option"; await fire(node(option, {}), "click"); const picked = [localStorage.getItem("llamacppAdminLang"), reloads, $("langMenu").hidden];
        await fire(node(null, {}), "click"); const langClosed = $("langMenu").hidden;
        globalThis.__fetchCalls.length = 0; await fire($("userMenuLogout"), "click"); const loggedOut = [calls(), globalThis.location];
        reset(); await boot({ "/api/auth/me": { enabled: true, authenticated: false } });
        return [version, user, menuOpen, menuClosed, lang, langOpen, picked, langClosed, loggedOut, doc.els.userChip.hidden]; })()""",
     J([["v1.3.350", "lama-caravan v1.3.350 @ abc1234"], [False, "operator · viewer"], [False, "true", True], [True, "false"],
        ["🪆", "RU", "Язык интерфейса", 20, True, True], [False, "true"], ["de", 1, False], True,
        [[["POST", "/api/auth/logout", {}]], "/login"], True]),
     "шапка: версия и коммит; пользователь с ролью, меню открывается и закрывается кликом снаружи; выход — POST и на /login; язык: двадцать вариантов, текущий выбран, выбор сохраняется для всего приложения и перезагружает страницу; без входа — чип скрыт"),

    ("frontier_panel", "",
     r"""await (async () => { await boot(); const e = page.el; const state = () => [page.frontierOpen, e.frontier.hidden, page.frontierFor];
        await fire(node(e.listHead, { act: "frontier" }), "click"); const opened = [...state(), e.frontier.innerHTML.includes('data-t="hf-frontier-refresh"'), e.frontier.innerHTML.includes("is-own")];
        await fire(node(e.frontier, {}), "click"); const inside = page.frontierOpen;
        await fire(node(e.listHead, { act: "frontier" }), "click"); const opener = page.frontierOpen;
        await fire(node(null, {}), "click"); const outside = [...state(), e.frontier.innerHTML];
        page.openFrontier(G); await fire(node(null, {}), "keydown", { key: "Escape" }); const escaped = state();
        page.openFrontier(null); await fire(node(e.frontier, { act: "frontier-close" }), "click"); const closedByButton = state();
        page.openFrontier(null); globalThis.__fetchCalls.length = 0; replies["/api/hf/reference-models?force=1"] = { ok: true, source: "aa", models: FRONTIER().slice(0, 2) };
        const openRefresh = gate("/api/hf/reference-models?force=1"); await fire(node(e.frontier, { act: "frontier-refresh" }), "click");
        const refreshing = [page.bench.frontier, e.frontier.innerHTML.includes("Loading data from Artificial Analysis…"), calls().map(([, p]) => p)];
        openRefresh(); await settle(); const refreshed = [page.bench.frontierModels().length, e.frontier.innerHTML.includes("built-in snapshot"), e.frontier.hidden];
        page.closeFrontier(); page.bench.frontier = null; globalThis.__fetchCalls.length = 0; page.openFrontier(null); await settle(); const lazy = calls().map(([, p]) => p);
        return [opened, inside, opener, outside, escaped, closedByButton, refreshing, refreshed, lazy]; })()""",
     J([[True, False, None, True, False], True, True, [False, True, None, ""], [False, True, None], [False, True, None],
        [None, True, ["/api/hf/reference-models?force=1"]], [2, False, False], ["/api/hf/reference-models"]]),
     "фронтир: открывается из шапки списка; клик внутри и по самой кнопке не закрывает; снаружи, Esc и ✕ — закрывают и чистят; обновление — сразу «загружаю», запрос с force=1, новый источник без пометки снимка; не загруженный — грузится при открытии"),

    ("dock_controls_reach_downloads", "",
     r"""await (async () => { await boot({ [FILES_URL(G)]: FILES() }); const e = page.el; page.catalog.setResults(REPOS()); await page.select(G); await settle();
        const pick = async () => { const n = node(e.repo, { act: "pick", paths: JSON.stringify(["g-Q4_K_M.gguf"]) }); n.checked = true; await fire(n, "change"); };
        const click = (data) => fire(node(e.dock, data), "click"); const d = page.downloads;
        await pick(); await click({ act: "sel-details" }); const details = [d.detailsOpen, e.dock.innerHTML.includes('data-t="hf-selection-plan"')]; await click({ act: "sel-details" }); details.push(d.detailsOpen);
        await click({ act: "sel-remove", repo: G, path: "g-Q4_K_M.gguf" }); const removed = [d.count(), e.dock.hidden];
        await pick(); await click({ act: "sel-clear" }); const cleared = d.count();
        await pick(); globalThis.__fetchCalls.length = 0; replies["/api/hf/download"] = { ok: true, jobId: "j1" }; replies["/api/hf/download/status?job=j1"] = { ok: true, status: "running", total_bytes: 100, total_bytes_done: 10 };
        await click({ act: "download" }); const started = [calls().map(([m, p]) => `${m} ${p}`), d.jobsOpen, d.count(), e.dock.innerHTML.includes('data-t="hf-download-job" data-t-id="j1"')];
        await click({ act: "jobs" }); const jobsClosed = [d.jobsOpen, e.dock.innerHTML.includes('data-t="hf-downloads"')]; await click({ act: "jobs" });
        globalThis.__fetchCalls.length = 0; await click({ act: "job-cancel", uid: "dlj1" }); const cancel = calls();
        d.addJob({ jobId: "j9", state: "error", error: "x" }); await click({ act: "job-dismiss", uid: "dlj2" }); const dismissed = d.jobs.map((j) => j.jobId);
        globalThis.__fetchCalls.length = 0; replies["/api/hf/download/resume"] = { ok: false, error: "no manifest" };
        await click({ act: "resume", dest: "gemma-4-12B-it-GGUF/bartowski/Q4_K_M", name: "g-Q4_K_M.gguf" }); const resume = [calls(), doc.els.hfToast.textContent];
        globalThis.__fetchCalls.length = 0; await click({}); await click({ act: "unknown" });
        return [details, removed, cleared, started, jobsClosed, cancel, dismissed, resume, calls().length]; })()""",
     J([[True, True, False], [0, True], 0, [["POST /api/hf/download", "GET /api/hf/download/status?job=j1"], True, 0, True], [False, False],
        [["POST", "/api/hf/download/cancel", {"jobId": "j1"}]], ["j1"],
        [[["POST", "/api/hf/download/resume", {"destDir": "gemma-4-12B-it-GGUF/bartowski/Q4_K_M", "name": "g-Q4_K_M.gguf"}]], "no manifest"], 0]),
     "док: подробности, ✕ у файла (док прячется), очистка, «скачать» (задание в списке), свернуть/развернуть задания, отмена, ✕ у ошибки, «продолжить» — всё доходит до загрузок; клик мимо — ничего"),

    ("tour_steps_and_languages", "",
     r"""await (async () => { await boot(); page.startTour(); const config = tourCalls.find((c) => c[0] === "create")[1];
        const steps = config.steps().map((s) => [s.anchor, s.center, typeof s.onRender]); const labels = config.labels(); const started = tourCalls.filter((c) => c[0] === "start").length;
        const holder = mkEl(); let rerendered = 0; config.steps()[0].onRender(holder, { rerender: () => { rerendered += 1; } });
        const wrap = holder.appended[0]; const buttons = (wrap.innerHTML.match(/data-ob-lang=/g) || []).length;
        const head = wrap.innerHTML.startsWith('<div class="ob-langs-head">Language</div><div class="ob-langs-grid">');
        const selected = wrap.innerHTML.includes('<button type="button" class="ob-lang selected" data-ob-lang="en">☕ English</button>');
        wrap.listeners.click[0]({ target: node(wrap, {}) }); const idle = [localStorage.getItem("llamacppAdminLang"), rerendered];
        wrap.listeners.click[0]({ target: node(node(wrap, { obLang: "ru" }), {}) }); const chosen = [localStorage.getItem("llamacppAdminLang"), doc.els.obBtnLabel.textContent, rerendered];
        const auto = tourCalls.find((c) => c[0] === "auto"); doc.els.appLoader = mkEl("appLoader"); const readyWithLoader = auto[2](); auto[3]();
        return [steps, labels, started, wrap.className, head, buttons, selected, idle, chosen, readyWithLoader, tourCalls.filter((c) => c[0] === "start").length,
                tourCalls.find((c) => c[0] === "init")[1].title()]; })()""",
     J([[[None, True, "function"], ["#hfSearchForm", False, "undefined"], ["#hfFilters", False, "undefined"], ["#hfTabs", False, "undefined"],
         ["#hfList", False, "undefined"], ["#hfRepo", False, "undefined"], ["#hfDock", False, "undefined"]],
        {"next": "Next →", "back": "← Back", "done": "Done", "skip": "Close"}, 1, "ob-langs", True, 20, True, [None, 0], ["ru", "Тур", 1], False, 2,
        "Как пользоваться этой страницей"]),
     "тур: семь шагов, первый по центру с выбором языка (все двадцать, текущий отмечен); выбор сохраняется, переименовывает кнопку тура и перерисовывает шаг; клик мимо — ничего; автостарт ждёт, пока уйдёт лоадер"),

    ("words_in_the_page_language", "",
     r"""await (async () => { localStorage.setItem("llamacppAdminLang", "ru"); await boot(); const e = page.el;
        return [e.searchInput.placeholder, e.searchInput.attrs["aria-label"], e.searchBtn.textContent, e.tokenSave.textContent, e.tokenEdit.textContent, e.tokenClear.textContent,
                e.onDisk.kids["[data-label]"].textContent, e.sort.innerHTML.split("</option>")[0], e.tabResults.innerHTML, e.tabFavs.innerHTML,
                e.sizeChips.innerHTML.includes('aria-pressed="true">Все <em>0</em></button>'), e.list.innerHTML.includes("Search to browse"), e.tokenBtn.kids[".hfp-token-label"].textContent]; })()""",
     J(["автор/репозиторий или слова для поиска…", "Поиск по Hugging Face", "Найти", "Сохранить", "Изменить", "Очистить", "на диске",
        '<option value="downloads">Загрузки', "Результаты <em>0</em>", "★ Избранное <em>0</em>", True, False, "HF-токен"]),
     "язык страницы: подписи, кнопки, порядок, вкладки, чипы и подпись токена — по-русски, английского не остаётся"),
]


if __name__ == "__main__":
    sys.exit(run("js hf-page", ".probe_js_hf_page.tmp.mjs", PREAMBLE, PINS, stubs="onboarding"))
