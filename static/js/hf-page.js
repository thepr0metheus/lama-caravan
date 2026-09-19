// The /hf page: search Hugging Face, choose a repository and its files,
// download them to the models disk.
//
// Two columns. On the left, the search and its filters over the list, with
// the results and the favorites as two tabs. On the right, the repository
// (hf-repo-view.js). Along the bottom, the selection and the downloads
// (hf-downloads.js). What is known about repositories lives in hf-catalog.js,
// benchmarks and the frontier in hf-bench.js, words in hf-text.js.
//
// Every click goes through a few containers that never change (delegation),
// and a container is only rewritten when its markup changed — and never while
// a pointer is held down over the list: a row replaced between mousedown and
// mouseup swallows the click, and background loads replace rows all the time.
import { autoStartOnce, createTour, initTourButtons } from "./onboarding.js";
import { escapeHtml, markPageState } from "./utils.js";
import { HfBench } from "./hf-bench.js";
import { CAPABILITIES, HfCatalog, SIZE_BUCKETS, SORT_KEYS } from "./hf-catalog.js";
import { HfDownloads } from "./hf-downloads.js";
import { HfRepoView } from "./hf-repo-view.js";
import { HF_LANGS, HfFormat, LANG_KEY, hfT, hfText } from "./hf-text.js";

//: Repositories whose file lists load at once in the background.
const FILES_CONCURRENCY = 5;
//: The models-disk badge is refreshed this often.
const DISK_REFRESH_MS = 60000;
//: A running sha256 check is asked about this often.
const VERIFY_POLL_MS = 700;
//: How long a message stays.
const TOAST_MS = 4000;

// The page's question dialog. Cancel, a click outside and Escape all answer no.
export class HfDialog {
  constructor(doc) {
    this.doc = doc;
  }

  confirm(title, body, okLabel = hfT("deleteWord"), danger = true) {
    return new Promise((resolve) => {
      const overlay = this.doc.createElement("div");
      overlay.className = "hf-confirm-overlay";
      overlay.setAttribute("data-t", "hf-confirm");
      overlay.innerHTML = `<div class="hf-confirm-box" role="dialog" aria-modal="true">`
        + `<div class="hf-confirm-title">${escapeHtml(title)}</div>`
        + (body ? `<div class="hf-confirm-body">${escapeHtml(body)}</div>` : "")
        + `<div class="hf-confirm-actions"><button type="button" class="hf-confirm-cancel" data-t="hf-confirm-cancel">${escapeHtml(hfT("cancelWord"))}</button>`
        + `<button type="button" class="hf-confirm-ok ${danger ? "danger" : "primary"}" data-t="hf-confirm-ok">${escapeHtml(okLabel)}</button></div></div>`;
      const close = (value) => {
        overlay.remove();
        this.doc.removeEventListener("keydown", onKey, true);
        resolve(value);
      };
      const onKey = (e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          close(false);
        }
      };
      overlay.addEventListener("click", (e) => { if (e.target === overlay) close(false); });
      overlay.querySelector(".hf-confirm-cancel").addEventListener("click", () => close(false));
      overlay.querySelector(".hf-confirm-ok").addEventListener("click", () => close(true));
      this.doc.addEventListener("keydown", onKey, true);
      this.doc.body.appendChild(overlay);
      overlay.querySelector(".hf-confirm-ok").focus();
    });
  }
}

export class HfPage {
  static boot(doc = document) {
    const page = new HfPage(doc);
    page.start();
    return page;
  }

  constructor(doc, { storage = globalThis.localStorage, later, now, location = globalThis.location } = {}) {
    this.doc = doc;
    this.storage = storage;
    this.later = later || ((fn, ms) => setTimeout(fn, ms));
    this.location = location;
    this.dialog = new HfDialog(doc);
    this.bench = new HfBench({ getJson: (url) => this.getJson(url) });
    this.catalog = new HfCatalog(this.bench);
    this.view = new HfRepoView({ bench: this.bench, catalog: this.catalog });
    this.downloads = new HfDownloads({
      getJson: (url) => this.getJson(url),
      postJson: (url, body) => this.postJson(url, body),
      confirm: (...args) => this.dialog.confirm(...args),
      toast: (message) => this.toast(message),
      storage,
      later: this.later,
      now: now || (() => (globalThis.performance ? globalThis.performance.now() : Date.now())),
      onChange: () => { this.renderDock(); this.renderRepo(); },
      onFinished: (repoId) => this.refreshLocal(repoId),
    });
    this.activeId = null;
    this.repoStates = new Map();
    this.searching = false;
    this.searchError = "";
    this.filesToken = 0;
    this.filesPending = new Map();
    this.filesDone = 0;
    this.filesTotal = 0;
    this.token = null;
    this.tokenOpen = false;
    this.tokenEditing = false;
    this.frontierOpen = false;
    this.frontierFor = null;
    this.holding = false;
    this.listPending = false;
    this.painted = new Map();
  }

  // ── requests ──────────────────────────────────────────────────────────────
  async getJson(url) {
    const response = await fetch(url);
    return response.json();
  }

  async postJson(url, body) {
    const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return response.json();
  }

  // ── start ─────────────────────────────────────────────────────────────────
  start() {
    const $ = (id) => this.doc.getElementById(id);
    this.el = {
      searchForm: $("hfSearchForm"), searchInput: $("hfSearchInput"), limit: $("hfLimitSelect"), searchBtn: $("hfSearchBtn"),
      sizeChips: $("hfSizeChips"), capChips: $("hfCapChips"), mask: $("hfMaskInput"), sort: $("hfSortSelect"), sortDir: $("hfSortDir"),
      load: $("hfLoad"), loadText: $("hfLoadText"), loadFill: $("hfLoadFill"),
      tokenBtn: $("hfTokenBtn"), tokenStatus: $("hfTokenStatus"), tokenPop: $("hfTokenPop"), tokenText: $("hfTokenText"),
      tokenInput: $("hfTokenInput"), tokenSave: $("hfTokenSaveBtn"), tokenEdit: $("hfTokenEditBtn"), tokenClear: $("hfTokenClearBtn"),
      tabs: $("hfTabs"), tabResults: $("hfTabResults"), tabFavs: $("hfTabFavs"), listHead: $("hfListHead"), list: $("hfList"),
      repo: $("hfRepo"), dock: $("hfDock"), frontier: $("hfFrontier"), diskBadge: $("hfDiskBadge"), onDisk: $("hfOnDiskBtn"),
    };
    this.staticText();
    this.bind();
    this.headerChrome();
    this.renderAll();
    const initial = [this.loadToken(), this.loadFavorites(), this.downloads.restore()];
    this.refreshDisk();
    setInterval(() => this.refreshDisk(), DISK_REFRESH_MS);
    this.bench.loadFrontier().then(() => this.renderAll());
    // The pixel loader (inline in hf.html) goes when the start-up data is in.
    // Each loader keeps the page working through its own failure and answers
    // false when it got nothing; the page state counts those for tests.
    Promise.allSettled(initial).then((results) => {
      if (globalThis.__plHide) globalThis.__plHide();
      const bad = results.filter((r) => r.status === "rejected" || r.value === false).length;
      markPageState("ready", bad ? `${bad} of ${results.length} initial loads failed` : "");
    });
    const query = new URLSearchParams((this.location && this.location.search) || "").get("q");
    if (query) {
      this.el.searchInput.value = query;
      this.search();
    } else {
      this.el.searchInput.focus();
    }
    this.startTourButtons();
  }

  // Words the markup ships in English, set in the page's language once.
  staticText() {
    const e = this.el;
    e.searchInput.placeholder = hfT("searchPlaceholder");
    e.searchInput.setAttribute("aria-label", hfT("a11ySearchModels"));
    e.limit.setAttribute("aria-label", hfT("a11yResultsCount"));
    e.limit.title = hfT("a11yResultsCount");
    e.searchBtn.textContent = hfT("searchBtn");
    e.sizeChips.setAttribute("aria-label", hfT("a11ySizeFilter"));
    e.capChips.setAttribute("aria-label", hfT("a11yCapFilter"));
    e.mask.placeholder = hfT("maskPlaceholder");
    e.mask.setAttribute("aria-label", hfT("a11yFilterByName"));
    e.sort.setAttribute("aria-label", hfT("a11ySortOrder"));
    e.sort.innerHTML = SORT_KEYS.map((k) => `<option value="${k.id}">${escapeHtml(k.label())}</option>`).join("");
    const tokenLabel = e.tokenBtn.querySelector ? e.tokenBtn.querySelector(".hfp-token-label") : null;
    if (tokenLabel) tokenLabel.textContent = hfT("tokenLabel");
    e.tokenInput.setAttribute("aria-label", hfT("a11yHfToken"));
    e.tokenSave.textContent = hfT("tokenSave");
    e.tokenEdit.textContent = hfT("tokenEdit");
    e.tokenClear.textContent = hfT("tokenClear");
    if (e.onDisk) {
      e.onDisk.title = hfT("onDiskTitle");
      const label = e.onDisk.querySelector ? e.onDisk.querySelector("[data-label]") : null;
      if (label) label.textContent = hfT("onDisk");
    }
  }

  bind() {
    const e = this.el;
    e.searchForm.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this.search();
    });
    e.sizeChips.addEventListener("click", (ev) => {
      const chip = ev.target.closest("[data-size]");
      if (!chip) return;
      this.catalog.size = chip.dataset.size;
      this.renderAll();
    });
    e.capChips.addEventListener("click", (ev) => {
      const chip = ev.target.closest("[data-cap]");
      if (!chip) return;
      const cap = chip.dataset.cap;
      if (this.catalog.caps.has(cap)) this.catalog.caps.delete(cap);
      else this.catalog.caps.add(cap);
      this.renderAll();
    });
    e.mask.addEventListener("input", () => {
      this.catalog.mask = e.mask.value;
      this.renderAll();
    });
    e.sort.addEventListener("change", () => {
      this.catalog.sortKey = e.sort.value;
      this.renderAll();
    });
    e.sortDir.addEventListener("click", () => {
      this.catalog.sortDir = this.catalog.sortDir === "desc" ? "asc" : "desc";
      this.renderAll();
    });
    e.tabs.addEventListener("click", (ev) => {
      const tab = ev.target.closest("[data-tab]");
      if (!tab) return;
      this.catalog.tab = tab.dataset.tab;
      this.renderAll();
    });
    e.listHead.addEventListener("click", (ev) => {
      if (ev.target.closest("[data-act='frontier']")) this.openFrontier(null);
    });
    e.list.addEventListener("pointerdown", () => { this.holding = true; });
    this.doc.addEventListener("pointerup", () => this.release(), true);
    this.doc.addEventListener("pointercancel", () => this.release(), true);
    e.list.addEventListener("click", (ev) => this.onListClick(ev));
    e.list.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter" && ev.key !== " ") return;
      const row = ev.target.closest("[data-repo]");
      if (!row || ev.target.closest("[data-act]")) return;
      ev.preventDefault();
      this.select(row.dataset.repo);
    });
    e.repo.addEventListener("click", (ev) => this.onRepoClick(ev));
    e.repo.addEventListener("change", (ev) => this.onRepoChange(ev));
    e.dock.addEventListener("click", (ev) => this.onDockClick(ev));
    e.frontier.addEventListener("click", (ev) => {
      const act = ev.target.closest("[data-act]");
      if (!act) return;
      if (act.dataset.act === "frontier-close") this.closeFrontier();
      if (act.dataset.act === "frontier-refresh") {
        this.bench.frontier = null;
        this.renderFrontier();
        this.bench.loadFrontier(true).then(() => this.renderAll());
      }
    });
    e.tokenBtn.addEventListener("click", () => {
      this.tokenOpen = !this.tokenOpen;
      if (!this.tokenOpen) this.tokenEditing = false;
      this.renderToken();
    });
    e.tokenEdit.addEventListener("click", () => this.editToken());
    e.tokenSave.addEventListener("click", () => this.saveToken());
    e.tokenClear.addEventListener("click", () => this.clearToken());
    e.tokenInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") this.saveToken();
      if (ev.key === "Escape") {
        ev.stopPropagation();
        this.tokenEditing = false;
        e.tokenInput.value = "";
        this.renderToken();
      }
    });
    this.doc.addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape") return;
      if (this.frontierOpen) this.closeFrontier();
      if (this.tokenOpen) {
        this.tokenOpen = false;
        this.tokenEditing = false;
        this.renderToken();
      }
    });
    this.doc.addEventListener("click", (ev) => {
      const target = ev.target;
      if (this.frontierOpen && target && typeof target.closest === "function"
          && !target.closest("#hfFrontier") && !target.closest("[data-act='frontier']")) this.closeFrontier();
      if (this.tokenOpen && target && typeof target.closest === "function" && !target.closest("#hfToken") && !target.closest(".hf-confirm-overlay")) {
        this.tokenOpen = false;
        this.tokenEditing = false;
        this.renderToken();
      }
    }, true);
  }

  release() {
    if (!this.holding) return;
    this.holding = false;
    if (this.listPending) {
      this.listPending = false;
      this.renderList();
    }
  }

  onListClick(ev) {
    const star = ev.target.closest("[data-act='star']");
    const row = ev.target.closest("[data-repo]");
    if (!row) return;
    if (star) {
      ev.stopPropagation();
      this.toggleFavorite(row.dataset.repo);
      return;
    }
    this.select(row.dataset.repo);
  }

  onRepoClick(ev) {
    const target = ev.target.closest("[data-act]");
    if (!target || !this.activeId) return;
    const id = this.activeId;
    const state = this.stateFor(id);
    switch (target.dataset.act) {
      case "star": this.toggleFavorite(id); break;
      case "verify": this.verify(id); break;
      case "bench":
        state.benchOpen = !state.benchOpen;
        this.renderRepo();
        break;
      case "bench-refresh":
        this.bench.cache.delete(id);
        this.renderRepo();
        this.bench.load(id, true).then(() => { this.renderList(); this.renderRepo(); });
        break;
      case "frontier": this.openFrontier(id); break;
      case "low": {
        const bits = Number(target.dataset.bits);
        if (state.lowOpen.has(bits)) state.lowOpen.delete(bits);
        else state.lowOpen.add(bits);
        this.renderRepo();
        break;
      }
      case "tree":
        state.treeOpen = !state.treeOpen;
        this.renderRepo();
        break;
      case "other":
        state.otherOpen = !state.otherOpen;
        this.renderRepo();
        break;
      case "open-repo": this.select(target.dataset.repo); break;
      case "delete": this.deleteLocal(id, JSON.parse(target.dataset.names || "[]")); break;
      case "checkpoint": {
        const st = this.catalog.repo(id).meta && this.catalog.repo(id).meta.safetensors;
        if (st) this.downloads.startCheckpoint(id, st);
        break;
      }
      default: break;
    }
  }

  onRepoChange(ev) {
    const box = ev.target.closest("[data-act='pick']");
    if (!box || !this.activeId) return;
    const paths = new Set(JSON.parse(box.dataset.paths || "[]"));
    const files = (this.catalog.repo(this.activeId).files || []).filter((f) => paths.has(f.path));
    this.downloads.toggle(this.activeId, files, box.checked);
  }

  onDockClick(ev) {
    const target = ev.target.closest("[data-act]");
    if (!target) return;
    const d = this.downloads;
    switch (target.dataset.act) {
      case "sel-details":
        d.detailsOpen = !d.detailsOpen;
        this.renderDock();
        break;
      case "download": d.start(); break;
      case "sel-remove": d.remove(target.dataset.repo, target.dataset.path); break;
      case "sel-clear": d.clear(); break;
      case "jobs":
        d.jobsOpen = !d.jobsOpen;
        this.renderDock();
        break;
      case "job-cancel": d.cancel(target.dataset.uid); break;
      case "job-dismiss": d.dismiss(target.dataset.uid); break;
      case "resume": d.resume(target.dataset.dest, target.dataset.name); break;
      default: break;
    }
  }

  stateFor(id) {
    if (!this.repoStates.has(id)) {
      this.repoStates.set(id, { lowOpen: new Set(), benchOpen: false, treeOpen: false, otherOpen: false, verify: null, verified: {}, error: "" });
    }
    return this.repoStates.get(id);
  }

  // ── searching and loading ─────────────────────────────────────────────────
  async search() {
    const query = this.el.searchInput.value.trim();
    if (!query) return;
    const limit = this.el.limit.value || "20";
    this.searching = true;
    this.searchError = "";
    this.catalog.tab = "results";
    this.el.searchBtn.disabled = true;
    this.renderAll();
    try {
      const data = await this.getJson(`/api/hf/search?q=${encodeURIComponent(query)}&limit=${encodeURIComponent(limit)}`);
      if (data && data.ok) {
        this.catalog.setResults(data.repos || []);
        // An exact "author/repo" is one repository: open it.
        if (query.includes("/") && (data.repos || []).length === 1) this.select(data.repos[0].id);
      } else {
        this.catalog.setResults([]);
        this.searchError = (data && data.error) || hfT("errorWord");
      }
    } catch (err) {
      this.catalog.setResults([]);
      this.searchError = String((err && err.message) || err);
    } finally {
      this.searching = false;
      this.el.searchBtn.disabled = false;
    }
    this.renderAll();
    this.loadInBackground();
  }

  loadInBackground() {
    const ids = this.catalog.allIds();
    this.loadFiles(ids);
    this.bench.loadAll(ids, () => {
      this.renderProgress();
      this.renderList();
      if (this.activeId) this.renderRepo();
    });
  }

  // File lists and what of them is on disk, a few repositories at a time. A
  // newer round replaces an older one's counting.
  async loadFiles(ids) {
    const token = ++this.filesToken;
    const queue = ids.filter((id) => !this.catalog.repo(id).files);
    this.filesTotal = queue.length;
    this.filesDone = 0;
    this.renderProgress();
    const worker = async () => {
      while (queue.length) {
        const id = queue.shift();
        await this.filesFor(id);
        if (token !== this.filesToken) return;
        this.filesDone += 1;
        this.renderProgress();
        this.renderChips();
        this.renderList();
        if (id === this.activeId) this.renderRepo();
      }
    };
    await Promise.all(Array.from({ length: FILES_CONCURRENCY }, worker));
  }

  async select(id) {
    this.activeId = id;
    const facts = this.catalog.repo(id);
    const state = this.stateFor(id);
    this.renderList();
    this.renderRepo();
    this.ensureTree(id);
    this.bench.load(id).then(() => { this.renderList(); if (this.activeId === id) this.renderRepo(); });
    if (facts.files) {
      this.refreshLocal(id);
      return;
    }
    const files = await this.filesFor(id);
    state.error = files && files.ok ? "" : (files && files.error) || hfT("errorWord");
    this.renderChips();
    this.renderList();
    this.renderRepo();
  }

  // A repository's file list and what of it is on disk: one pair of requests
  // however many callers ask. An exact "author/repo" search opens the
  // repository and queues it in the background at the same moment.
  filesFor(id) {
    if (!this.filesPending.has(id)) {
      const request = Promise.all([
        this.getJson(`/api/hf/files?repo=${encodeURIComponent(id)}`).catch((err) => ({ ok: false, error: String((err && err.message) || err) })),
        this.getJson(`/api/hf/local-check?repo=${encodeURIComponent(id)}`).catch(() => null),
      ]).then(([files, local]) => {
        const facts = this.catalog.repo(id);
        if (local && local.ok) facts.setLocal(local);
        if (files && files.ok) facts.setFiles(files);
        return files;
      }).finally(() => this.filesPending.delete(id));
      this.filesPending.set(id, request);
    }
    return this.filesPending.get(id);
  }

  ensureTree(id) {
    const facts = this.catalog.repo(id);
    if (facts.tree !== undefined) return;
    facts.tree = null;
    this.getJson(`/api/hf/model-tree?repo=${encodeURIComponent(id)}`)
      .then((data) => { facts.tree = data && data.ok ? data : undefined; })
      .catch(() => { facts.tree = undefined; })
      .then(() => { if (this.activeId === id) this.renderRepo(); });
  }

  async refreshLocal(id) {
    try {
      const data = await this.getJson(`/api/hf/local-check?repo=${encodeURIComponent(id)}`);
      if (data && data.ok) this.catalog.repo(id).setLocal(data);
    } catch { /* the markers stay as they were */ }
    this.renderList();
    if (this.activeId === id) this.renderRepo();
    this.renderDock();
  }

  async loadFavorites() {
    try {
      const data = await this.getJson("/api/hf/favorites");
      if (data && data.ok && Array.isArray(data.favorites)) {
        this.catalog.setFavorites(data.favorites);
        this.renderAll();
        this.loadInBackground();
        return true;
      }
    } catch { /* no favorites shown */ }
    return false;
  }

  async toggleFavorite(id) {
    const payload = this.catalog.toggleFavorite(id);
    this.renderAll();
    try {
      await this.postJson("/api/hf/favorites", { favorites: payload });
    } catch {
      this.toast(hfT("networkError"));
    }
  }

  async verify(id) {
    const state = this.stateFor(id);
    state.verify = { running: true, pct: 0 };
    this.renderRepo();
    let answer;
    try {
      answer = await this.postJson("/api/hf/verify", { repo: id });
    } catch {
      answer = { ok: false, error: hfT("networkError") };
    }
    if (!answer || !answer.ok) {
      state.verify = null;
      this.renderRepo();
      this.toast((answer && answer.error) || hfT("verifyFailed"));
      return;
    }
    this.pollVerify(id, answer.jobId);
  }

  // Progress in bytes, not files: one file can be 17 GB, and "1 of 3" would
  // sit still on it for minutes.
  pollVerify(id, jobId) {
    const tick = async () => {
      let data = null;
      try {
        data = await this.getJson(`/api/hf/verify?job=${encodeURIComponent(jobId)}`);
      } catch { /* treated as no job below */ }
      const state = this.stateFor(id);
      const job = data && data.job;
      if (!job) {
        state.verify = null;
        this.renderRepo();
        return;
      }
      state.verified = job.files || {};
      if (!job.done) {
        state.verify = { running: true, pct: job.totalBytes ? Math.min(100, Math.round((job.bytesDone * 100) / job.totalBytes)) : 0 };
        this.renderRepo();
        this.later(tick, VERIFY_POLL_MS);
        return;
      }
      state.verify = null;
      this.renderRepo();
      if (job.error) this.toast(job.error);
    };
    tick();
  }

  async deleteLocal(id, names) {
    if (!names.length) return;
    if (!(await this.dialog.confirm(hfT("deleteLocalConfirm"), names.join("\n"), hfT("deleteWord"), true))) return;
    const facts = this.catalog.repo(id);
    for (const name of names) {
      let answer;
      try {
        const response = await fetch(`/api/hf/local-file?repo=${encodeURIComponent(id)}&name=${encodeURIComponent(name)}`, { method: "DELETE" });
        answer = await response.json();
      } catch {
        answer = { ok: false, error: hfT("networkError") };
      }
      if (!answer || !answer.ok) {
        this.toast(hfT("deleteFailed", { err: (answer && answer.error) || "" }));
        break;
      }
      if (facts.localNames) facts.localNames.delete(name);
    }
    this.renderList();
    this.renderRepo();
    this.refreshLocal(id);
  }

  // ── the token ─────────────────────────────────────────────────────────────
  async loadToken() {
    try {
      this.token = await this.getJson("/api/hf/token");
    } catch {
      this.token = null;
    }
    this.tokenEditing = false;
    this.renderToken();
    return this.token !== null;
  }

  async editToken() {
    if (!(await this.dialog.confirm(hfT("tokenChangeTitle"), "", hfT("tokenChangeOk"), false))) return;
    this.tokenOpen = true;
    this.tokenEditing = true;
    this.renderToken();
    this.el.tokenInput.focus();
  }

  async saveToken() {
    const value = this.el.tokenInput.value.trim();
    this.el.tokenSave.disabled = true;
    try {
      this.token = await this.postJson("/api/hf/token", { token: value });
      this.tokenEditing = false;
      this.el.tokenInput.value = "";
    } catch (err) {
      this.toast(String((err && err.message) || err));
    } finally {
      this.el.tokenSave.disabled = false;
    }
    this.renderToken();
  }

  async clearToken() {
    if (!(await this.dialog.confirm(hfT("tokenClearTitle"), "", hfT("tokenClearOk"), true))) return;
    try {
      await this.postJson("/api/hf/token", { token: "" });
    } catch {
      this.toast(hfT("networkError"));
    }
    await this.loadToken();
  }

  // ── the header ────────────────────────────────────────────────────────────
  async refreshDisk() {
    let info = null;
    try {
      info = await this.getJson("/api/models/disk");
    } catch { /* unknown below */ }
    this.downloads.setDisk(info);
    const badge = this.el.diskBadge;
    if (badge) {
      if (!info || !info.ok) {
        badge.hidden = true;
      } else {
        badge.hidden = false;
        badge.textContent = hfT("diskFree", { free: info.freeGb });
        badge.title = hfT("diskFreeTitle", { path: info.path, free: info.freeGb, total: info.totalGb });
        badge.classList.toggle("low", info.freeGb < 50);
        badge.classList.toggle("critical", info.freeGb < 15);
      }
    }
    this.renderDock();
  }

  // The version, the signed-in user and the language picker. This page does
  // not load the shared i18n module, so the picker is built here from HF_LANGS
  // against the same storage key the rest of the app reads.
  headerChrome() {
    const $ = (id) => this.doc.getElementById(id);
    this.getJson("/health").then((d) => {
      const el = $("projectGitBranch");
      if (el && d && d.version) {
        el.textContent = `v${d.version}`;
        el.title = `lama-caravan v${d.version}${d.commit ? ` @ ${d.commit}` : ""}`;
      }
    }).catch(() => {});
    this.getJson("/api/auth/me").then((me) => {
      if (!me || !me.enabled || !me.authenticated) return;
      const chip = $("userChip");
      const menu = $("userMenu");
      const btn = $("userChipBtn");
      if (!chip || !menu || !btn) return;
      $("userChipName").textContent = me.user + (me.role === "viewer" ? " · viewer" : "");
      chip.hidden = false;
      const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        menu.hidden = !menu.hidden;
        btn.setAttribute("aria-expanded", String(!menu.hidden));
      });
      this.doc.addEventListener("click", (ev) => { if (!chip.contains(ev.target)) close(); }, true);
      this.doc.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !menu.hidden) close(); });
      $("userMenuLogout").addEventListener("click", async () => {
        try {
          await fetch("/api/auth/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        } catch { /* going to /login either way */ }
        globalThis.location = "/login";
      });
    }).catch(() => {});
    const trigger = $("langTrigger");
    const menu = $("langMenu");
    if (!trigger || !menu) return;
    const current = hfText.lang;
    const entry = HF_LANGS.find(([code]) => code === current) || HF_LANGS[0];
    $("langTriggerEmoji").textContent = String(entry[1]).split(" ")[0];
    $("langTriggerCode").textContent = entry[0].toUpperCase();
    trigger.setAttribute("aria-label", hfT("a11yInterfaceLanguage"));
    menu.setAttribute("aria-label", hfT("a11yInterfaceLanguage"));
    menu.innerHTML = HF_LANGS.map(([code, label]) => {
      const [emoji, ...name] = String(label).split(" ");
      const selected = code === current;
      return `<li class="lang-option${selected ? " selected" : ""}" role="option" data-lang="${escapeHtml(code)}" aria-selected="${selected}">`
        + `<span class="lang-emoji">${escapeHtml(emoji)}</span><span class="lang-name">${escapeHtml(name.join(" "))}</span></li>`;
    }).join("");
    const close = () => { menu.hidden = true; trigger.setAttribute("aria-expanded", "false"); };
    trigger.addEventListener("click", (ev) => {
      ev.stopPropagation();
      menu.hidden = !menu.hidden;
      trigger.setAttribute("aria-expanded", String(!menu.hidden));
    });
    menu.addEventListener("click", (ev) => {
      const option = ev.target.closest(".lang-option");
      if (!option) return;
      this.storage.setItem(LANG_KEY, option.dataset.lang);
      // A reload, not an in-place redraw: half-translating a live page is
      // worse than a blink.
      globalThis.location.reload();
    });
    this.doc.addEventListener("click", (ev) => { if (!menu.hidden && !menu.contains(ev.target) && ev.target !== trigger) close(); }, true);
    this.doc.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && !menu.hidden) close(); });
  }

  startTourButtons() {
    const label = this.doc.getElementById("obBtnLabel");
    if (label) label.textContent = hfText.tour().label;
    initTourButtons({ title: () => hfText.tour().btn, onClick: () => this.startTour() });
    autoStartOnce("hf", () => !this.doc.getElementById("appLoader"), () => this.startTour());
  }

  startTour() {
    createTour({
      steps: () => hfText.tour().steps.map(([anchor, title, body], i) => ({
        anchor, title, body, center: !anchor,
        onRender: !anchor && i === 0 ? (node, api) => this.tourLanguages(node, api) : undefined,
      })),
      labels: () => {
        const s = hfText.tour();
        return { next: s.next, back: s.back, done: s.done, skip: s.skip };
      },
    }).start();
  }

  // Every app language, offered in the tour's first step; the choice goes to
  // the shared language key, so the other pages pick it up too.
  tourLanguages(node, api) {
    const s = hfText.tour();
    const current = hfText.lang;
    const wrap = this.doc.createElement("div");
    wrap.className = "ob-langs";
    wrap.innerHTML = `<div class="ob-langs-head">${escapeHtml(s.langPick)}</div><div class="ob-langs-grid">`
      + HF_LANGS.map(([code, label]) => `<button type="button" class="ob-lang${code === current ? " selected" : ""}" data-ob-lang="${escapeHtml(code)}">${escapeHtml(label)}</button>`).join("")
      + `</div>`;
    wrap.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-ob-lang]");
      if (!btn) return;
      this.storage.setItem(LANG_KEY, btn.dataset.obLang);
      const label = this.doc.getElementById("obBtnLabel");
      if (label) label.textContent = hfText.tour().label;
      api.rerender();
    });
    node.appendChild(wrap);
  }

  // ── the frontier panel ────────────────────────────────────────────────────
  openFrontier(markId) {
    this.frontierOpen = true;
    this.frontierFor = markId;
    this.renderFrontier();
    if (!this.bench.frontier) this.bench.loadFrontier().then(() => this.renderAll());
  }

  closeFrontier() {
    this.frontierOpen = false;
    this.frontierFor = null;
    this.renderFrontier();
  }

  toast(message) {
    let el = this.doc.getElementById("hfToast");
    if (!el) {
      el = this.doc.createElement("div");
      el.id = "hfToast";
      el.setAttribute("role", "status");
      this.doc.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => el.classList.remove("show"), TOAST_MS);
  }

  // ── drawing ───────────────────────────────────────────────────────────────
  // Rewrites a container only when its markup changed, and puts focus back on
  // the control that had it.
  paint(el, html) {
    if (!el || this.painted.get(el) === html) return false;
    const active = this.doc.activeElement;
    const key = active && typeof el.contains === "function" && el.contains(active) ? this.focusKey(active) : "";
    el.innerHTML = html;
    this.painted.set(el, html);
    if (key && typeof el.querySelector === "function") {
      const again = el.querySelector(key);
      if (again && typeof again.focus === "function") again.focus();
    }
    return true;
  }

  focusKey(node) {
    const d = node.dataset || {};
    const esc = (v) => String(v).replace(/["\\]/g, "\\$&");
    if (d.t && d.tId) return `[data-t="${esc(d.t)}"][data-t-id="${esc(d.tId)}"]`;
    if (d.repo) return `[data-repo="${esc(d.repo)}"]`;
    if (d.act) return `[data-act="${esc(d.act)}"]`;
    return "";
  }

  renderAll() {
    this.renderChips();
    this.renderSort();
    this.renderTabs();
    this.renderList();
    this.renderProgress();
    this.renderToken();
    this.renderRepo();
    this.renderDock();
    this.renderFrontier();
  }

  renderChips() {
    const counts = this.catalog.sizeCounts();
    this.paint(this.el.sizeChips, SIZE_BUCKETS.map((b) => {
      const on = this.catalog.size === b.id;
      return `<button type="button" class="hfp-chip${on ? " is-on" : ""}${counts[b.id] ? "" : " is-zero"}" data-size="${b.id}" data-t="hf-size-filter" data-t-id="${b.id}" aria-pressed="${on}">`
        + `${escapeHtml(b.label())} <em>${counts[b.id]}</em></button>`;
    }).join(""));
    const caps = this.catalog.capCounts();
    this.el.capChips.hidden = !caps.length;
    this.paint(this.el.capChips, caps.map((c) => {
      const on = this.catalog.caps.has(c.id);
      return `<button type="button" class="hfp-chip${on ? " is-on" : ""}" data-cap="${c.id}" data-t="hf-capability-filter" data-t-id="${c.id}" aria-pressed="${on}" title="${escapeHtml(c.title())}">`
        + `${c.icon} ${c.id} <em>${c.count}</em></button>`;
    }).join(""));
  }

  renderSort() {
    this.el.sort.value = this.catalog.sortKey;
    const desc = this.catalog.sortDir === "desc";
    this.el.sortDir.textContent = desc ? "↓" : "↑";
    this.el.sortDir.title = hfT(desc ? "sortDesc" : "sortAsc");
    this.el.sortDir.setAttribute("aria-label", this.el.sortDir.title);
  }

  renderTabs() {
    const tabs = [[this.el.tabResults, "results", hfT("tabResults"), this.catalog.resultIds.length],
      [this.el.tabFavs, "favorites", `★ ${hfT("tabFavorites")}`, this.catalog.favoriteIds.length]];
    for (const [el, id, label, n] of tabs) {
      const on = this.catalog.tab === id;
      this.paint(el, `${escapeHtml(label)} <em>${n}</em>`);
      el.classList.toggle("is-on", on);
      el.setAttribute("aria-selected", String(on));
    }
  }

  listHeadHtml(view) {
    const parts = [`<span>${escapeHtml(hfT("listShown", { shown: view.items.length, total: view.total }))}</span>`];
    if (view.hiddenNoSize) parts.push(`<span class="hfp-warn">${escapeHtml(hfT("hiddenNoSize", { n: view.hiddenNoSize }))}</span>`);
    if (view.unchecked) parts.push(`<span class="hfp-warn">${escapeHtml(hfT("hiddenUnchecked", { n: view.unchecked }))}</span>`);
    const ticks = this.bench.ticks();
    const legend = ticks.length ? `<span class="hfp-legend" title="${escapeHtml(ticks.map((m) => `${m.name} ${m.aa}`).join("\n"))}">${escapeHtml(hfT("frontierTicks", { names: ticks.map((m) => m.name).join(" · ") }))}</span>` : "";
    const all = this.bench.frontierModels().length
      ? `<button type="button" class="hfp-link" data-act="frontier" data-t="hf-frontier-open">${escapeHtml(hfT("frontierAll", { n: this.bench.frontierModels().length }))}</button>` : "";
    return `<span class="hfp-listhead-count">${parts.join(`<span class="hfp-dot">·</span>`)}</span>${legend}${all}`;
  }

  renderList() {
    if (this.holding) {
      this.listPending = true;
      return;
    }
    const view = this.catalog.view();
    this.paint(this.el.listHead, this.listHeadHtml(view));
    let html;
    if (this.catalog.tab === "results" && this.searching) html = `<div class="hfp-empty">${escapeHtml(hfT("searching"))}</div>`;
    else if (this.catalog.tab === "results" && this.searchError) html = `<div class="hfp-error">${escapeHtml(this.searchError)}</div>`;
    else if (this.catalog.tab === "results" && !this.catalog.searched) html = `<div class="hfp-empty">${escapeHtml(hfT("searchToBrowse"))}</div>`;
    else if (this.catalog.tab === "results" && !view.total) html = `<div class="hfp-empty">${escapeHtml(hfT("noResults"))}</div>`;
    else if (this.catalog.tab === "favorites" && !view.total) html = `<div class="hfp-empty">${escapeHtml(hfT("favEmpty"))}</div>`;
    else if (!view.items.length) html = `<div class="hfp-empty">${escapeHtml(hfT("noFilterMatches"))}</div>`;
    else html = view.items.map((facts) => this.rowHtml(facts)).join("");
    this.paint(this.el.list, html);
  }

  rowHtml(facts) {
    const on = facts.id === this.activeId;
    const fav = this.catalog.isFavorite(facts.id);
    const caps = CAPABILITIES.filter((c) => facts.has(c.id))
      .map((c) => `<span class="hfp-icon" title="${escapeHtml(`${c.id} — ${c.title()}`)}">${c.icon}</span>`).join("");
    const meta = [`↓ ${facts.countLabel("downloads")}`, `♥ ${facts.countLabel("likes")}`];
    if (facts.paramsLabel) meta.push(`<b class="hfp-params">${escapeHtml(facts.paramsLabel)}</b>`);
    if (facts.date) meta.push(`<span title="${escapeHtml(facts.date)}">${escapeHtml(hfText.ago(facts.date))}</span>`);
    const local = facts.localCount ? `<span class="hfp-local" title="${escapeHtml(hfT("localCount", { n: facts.localCount }))}">✓ ${facts.localCount}</span>` : "";
    const library = facts.libraryCount
      ? `<span class="hfp-lib" data-t="hf-in-library" data-t-id="${escapeHtml(facts.id)}" title="${escapeHtml(hfT("libraryCount", { n: facts.libraryCount, places: facts.libraryNames.join(", ") }))}">📚 ${facts.libraryCount}</span>`
      : "";
    const name = facts.id.includes("/") ? `<span class="hfp-author">${escapeHtml(facts.author)}/</span><b>${escapeHtml(facts.model)}</b>` : `<b>${escapeHtml(facts.id)}</b>`;
    return `<div class="hfp-row${on ? " is-active" : ""}" data-repo="${escapeHtml(facts.id)}" data-t="hf-result" data-t-id="${escapeHtml(facts.id)}" role="button" tabindex="0" aria-current="${on}">`
      + `<div class="hfp-row-top"><span class="hfp-name" title="${escapeHtml(facts.id)}">${name}</span>`
      + (facts.format ? `<span class="hfp-badge is-fmt">${escapeHtml(facts.format)}</span>` : "")
      + `<span class="hfp-icons">${caps}</span>`
      + `<button type="button" class="hfp-star${fav ? " is-on" : ""}" data-act="star" data-t="hf-star" data-t-id="${escapeHtml(facts.id)}" aria-pressed="${fav}" title="${escapeHtml(hfT(fav ? "favRemove" : "favAdd"))}" aria-label="${escapeHtml(hfT(fav ? "favRemove" : "favAdd"))}">${fav ? "★" : "☆"}</button></div>`
      + `<div class="hfp-row-bot"><span class="hfp-meta">${meta.join(`<span class="hfp-dot">·</span>`)}</span><span class="grow"></span>${local}${library}${this.bench.rowHtml(facts.id)}</div>`
      + `</div>`;
  }

  renderProgress() {
    const e = this.el;
    let text = "";
    let pct = 0;
    if (this.filesTotal > 0 && this.filesDone < this.filesTotal) {
      text = hfT("loadFiles", { done: this.filesDone, total: this.filesTotal });
      pct = (this.filesDone / this.filesTotal) * 100;
    } else if (this.bench.running) {
      text = hfT("loadBench", { done: this.bench.done, total: this.bench.total });
      pct = (this.bench.done / this.bench.total) * 100;
    }
    e.load.hidden = !text;
    e.loadText.textContent = text;
    e.loadFill.style.width = `${pct.toFixed(0)}%`;
  }

  renderToken() {
    const e = this.el;
    const set = !!(this.token && this.token.set);
    e.tokenStatus.textContent = this.token ? `${set ? "●" : "○"} ${hfT(set ? "tokenSetShort" : "tokenUnsetShort")}` : hfT("tokenChecking");
    e.tokenStatus.classList.toggle("is-set", set);
    e.tokenBtn.setAttribute("aria-expanded", String(this.tokenOpen));
    e.tokenPop.hidden = !this.tokenOpen;
    e.tokenText.textContent = set ? hfT("tokenIsSet", { masked: this.token.masked || "" }) : hfT("tokenNotSet");
    e.tokenInput.hidden = !this.tokenEditing;
    e.tokenSave.hidden = !this.tokenEditing;
    e.tokenEdit.hidden = this.tokenEditing;
    e.tokenClear.hidden = this.tokenEditing || !set;
  }

  renderRepo() {
    const facts = this.activeId ? this.catalog.repo(this.activeId) : null;
    const state = facts ? { ...this.stateFor(facts.id), picks: this.downloads.picks(facts.id) } : {};
    this.paint(this.el.repo, this.view.html(facts, state));
  }

  renderDock() {
    const visible = this.downloads.visible();
    this.el.dock.hidden = !visible;
    this.paint(this.el.dock, visible ? this.downloads.html((repoId) => this.catalog.repo(repoId).localNames || new Set()) : "");
  }

  renderFrontier() {
    this.el.frontier.hidden = !this.frontierOpen;
    this.paint(this.el.frontier, this.frontierOpen ? this.bench.frontierHtml(this.frontierFor) : "");
  }
}

document.addEventListener("DOMContentLoaded", () => HfPage.boot(document));
