// Model moves on the /models page, drawn where the files are. A file on its
// way carries its own bar — the pass it is in, how fast, how long — and its
// Stop, on its own row of the tree; a folded branch says how far its files
// are; one line by the move button counts everything on its way and opens the
// branches it is in. There is no panel of jobs: a finished move shows in the
// tree itself (the file becomes a 📚 row), and a move that left a file here
// says why on that file's row, until the note is hidden.
// Data: /api/model-stores/moves; starting: /api/model-stores/move; stopping:
// /api/model-stores/moves/cancel.
//
// The job runs ON THE SERVER (caravan/admin/store_moves.py) and the page only
// draws it, so progress survives a reload and shows in a second tab. Every
// file is read back from the library and compared before the copy here is
// deleted — and the question before the start says so, because that deletion
// is the one step of a move that cannot be undone.
import { appConfirm } from "./dialogs.js";
import { t } from "./i18n.js";
import { Pace } from "./pace.js";
import { api, escapeHtml, fmtGb, toast } from "./utils.js";

// A library takes files only in these states; the server refuses the rest too.
const USABLE = new Set(["ok", "low-space"]);
const FINISHED = new Set(["done", "failed", "cancelled"]);
const ITEM_FINAL = new Set(["done", "skipped", "cancelled"]);
// Why a file stayed here, code → key. A code the server adds tomorrow is shown
// as it is, never dropped: "not moved" with no reason would be half an answer.
const NOTES = { "local-gone": "moveNoteLocalGone", "local-changed": "moveNoteLocalChanged", mismatch: "moveNoteMismatch", "name-taken": "moveNoteNameTaken", "copy-missing": "moveNoteCopyMissing", "in-use": "moveNoteInUse", "unlink-failed": "moveNoteUnlinkFailed", errors: "moveNoteErrors", "link-out": "moveNoteLinkOut", "folder-odd": "moveNoteFolderOdd", "folder-changed": "moveNoteFolderChanged" };
const POLL_MS = 1200;
// How far one new speed reading moves the shown one: enough to follow a real
// change within a few polls, not so far that one slow block makes the time
// left jump.
const PACE_WEIGHT = 0.3;
// Notes the operator hid, "<job>|<path>" — per browser, never shared.
const SEEN_KEY = "mdl.moveSeen";
const SEEN_MAX = 200;
//: The controller's own models directory, as the stores registry names it.
const LOCAL_ID = "local";

const pct = (done, total) => (total ? Math.min(100, Math.round((done * 100) / total)) : 0);

export class MoveTracker {
  static mount(opts = {}) {
    const tracker = new MoveTracker(opts);
    tracker.bind();
    tracker.syncButton();
    // The first answer may already hold files on their way (a move started in
    // another tab, or before a reload) or notes about finished ones, and the
    // tree drawn meanwhile knows neither.
    tracker.refresh().then(() => { if (tracker.shape()) tracker.onChange(); });
    return tracker;
  }

  constructor(opts = {}) {
    this.tree = opts.tree || null;
    this.summary = opts.summary || null;
    this.button = opts.button || null;
    this.select = opts.select || null;
    this.picked = opts.picked || (() => []);
    this.stores = opts.stores || (() => null);
    this.onChange = opts.onChange || (() => {});
    // Told before the line by the button shows the files on their way: the
    // page decides what its list must show for them to be there to show.
    this.onReveal = opts.onReveal || null;
    this.now = opts.now || (() => Date.now());
    this.storage = "storage" in opts ? opts.storage : MoveTracker.browserStorage();
    // null = not loaded yet: nothing is drawn before the first answer.
    this.jobs = null;
    // path → {job, row} from the newest job that holds the file.
    this.byPath = new Map();
    // job id → {t, work, rate}: the last reading of its work, and the speed.
    this.pace = new Map();
    this.seen = this.loadSeen();
    this.timer = null;
    this.menu = null;
    this.menuClose = null;
  }

  static browserStorage() {
    try { return globalThis.localStorage || null; } catch { return null; }
  }

  loadSeen() {
    try { return new Set(JSON.parse((this.storage && this.storage.getItem(SEEN_KEY)) || "[]")); } catch { return new Set(); }
  }

  saveSeen() {
    try {
      if (this.storage) this.storage.setItem(SEEN_KEY, JSON.stringify([...this.seen].slice(-SEEN_MAX)));
    } catch { /* a private window keeps the note hidden for this visit only */ }
  }

  libraries() {
    return (this.stores() || []).filter((s) => s.role === "library" && USABLE.has(s.state));
  }

  // Where files can go from a store: every other place that is here and can
  // take them. This disk is one of them — a move back is a move like any other.
  destinations(from = LOCAL_ID) {
    return (this.stores() || []).filter((s) => s.id !== from && USABLE.has(s.state));
  }

  // A store's name as the page says it: the controller's own directory has no
  // name of its own, and it is called the same thing everywhere.
  nameOf(store) {
    const id = (store && store.id) || "";
    const row = (this.stores() || []).find((s) => s.id === id) || {};
    return row.name || (row.role === "local" ? t("storeLocalName") : (store && store.name) || id);
  }

  // What the ⇢ buttons depend on: the page redraws the tree when this changes.
  storesKey() {
    return ((this.stores() || []).filter((s) => USABLE.has(s.state))).map((s) => `${s.id}:${s.name || ""}`).join("|");
  }

  syncButton() {
    // The button below moves what is PICKED, and only this disk's files carry a
    // checkbox — so its choice is the places they can go from here.
    const libs = this.destinations(LOCAL_ID);
    // Folders move too now (a cache is one item, walked by the mover), so
    // everything picked counts.
    if (this.select) {
      const was = this.select.value;
      this.select.innerHTML = libs.map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(this.nameOf(s))}</option>`).join("");
      // One library needs no choice: its name is on the button.
      this.select.hidden = libs.length < 2;
      if (libs.some((s) => s.id === was)) this.select.value = was;
    }
    if (!this.button) return;
    const movable = this.picked();
    this.button.disabled = !movable.length || !libs.length;
    this.button.textContent = libs.length === 1 ? t("moveSelectedTo", { name: this.nameOf(libs[0]) }) : t("moveSelected");
    // With no library the button says what is missing, not just sits there
    // grey — once the stores are known; before their first answer nothing is.
    this.button.title = libs.length || this.stores() === null ? "" : t("moveNoLibrary");
  }

  target() {
    const libs = this.destinations(LOCAL_ID);
    if (libs.length > 1 && this.select) return libs.find((s) => s.id === this.select.value) || null;
    return libs[0] || null;
  }

  // ── What a row says ─────────────────────────────────────────────────────

  static settled(r) {
    return r.phase === "removed" || ITEM_FINAL.has(r.item);
  }

  static why(r) {
    return NOTES[r.note] ? t(NOTES[r.note]) : String(r.note || "?");
  }

  // How far one file is, out of 2 × its size — the server's own rule
  // (MoveJob._work): the copy is one pass over the link, the proof another.
  static work(r) {
    const size = r.size || 0;
    if (ITEM_FINAL.has(r.item) || r.phase === "proven" || r.phase === "removed") return 2 * size;
    if (r.phase === "copying") return Math.min(size, r.done || 0);
    if (r.phase === "checking") return size + Math.min(size, r.done || 0);
    return 0;
  }

  // One row's state, word and bar. The copy and the proof each fill the bar
  // once and the word says which pass it is; a pass the library is holding up
  // turns red and says why, instead of freezing blue.
  static view(j, r) {
    const pass = pct(r.done || 0, r.size || 0);
    if (r.phase === "removed" || r.item === "done") return { kind: "moved", label: "", width: 100, stalled: false };
    if (r.item === "skipped") return { kind: "skipped", label: t("movePhaseSkipped", { why: MoveTracker.why(r) }), width: 0, stalled: true };
    if (r.item === "cancelled" || FINISHED.has(j.status)) return { kind: "stopped", label: "", width: 0, stalled: true };
    const active = r.phase === "copying" || r.phase === "checking";
    if (active && j.status === "waiting") {
      return { kind: "waiting", label: j.reason ? t("moveRowWaiting", { why: j.reason }) : t("moveStatusWaiting"), width: pass, stalled: true };
    }
    if (r.phase === "copying") return { kind: "copying", label: `${t("movePhaseCopying")} ${pass}%`, width: pass, stalled: false };
    if (r.phase === "checking") return { kind: "checking", label: `${t("movePhaseChecking")} ${pass}%`, width: pass, stalled: false };
    if (r.phase === "proven") return { kind: "checked", label: t("movePhaseChecked"), width: 100, stalled: false };
    return { kind: "queued", label: t("movePhaseQueued"), width: 0, stalled: false };
  }

  // The wording lives in pace.js, shared with the board's loading cells.
  static speed(bps) { return Pace.speed(bps); }
  static eta(seconds) { return Pace.eta(seconds); }

  // ── What the tree asks ──────────────────────────────────────────────────

  // The newest job that holds a file decides what its row says. The server
  // lists jobs newest first.
  reindex() {
    this.byPath = new Map();
    for (const job of this.jobs || []) {
      for (const row of job.files || []) if (!this.byPath.has(row.path)) this.byPath.set(row.path, { job, row });
    }
  }

  // A file still here and still travelling: its row carries the bar instead
  // of a checkbox — deleting it, or moving it a second time, while it travels
  // would argue with the job.
  onWay(path) {
    const hit = this.byPath.get(path);
    if (!hit || FINISHED.has(hit.job.status) || MoveTracker.settled(hit.row)) return null;
    return hit;
  }

  // A finished move that left this file here, and why — until the note is
  // hidden. A move stopped by hand says nothing: the operator knows.
  stayed(path) {
    const hit = this.byPath.get(path);
    if (!hit || !FINISHED.has(hit.job.status) || this.seen.has(`${hit.job.id}|${path}`)) return null;
    const { job, row } = hit;
    if (row.item === "skipped") return { job, row, why: MoveTracker.why(row) };
    if (job.status === "failed" && !MoveTracker.settled(row)) return { job, row, why: job.reason || t("moveStatusFailed") };
    return null;
  }

  label(job, row, v = MoveTracker.view(job, row)) {
    const parts = [`⇢ ${this.nameOf(job.target)}`, v.label];
    if (v.kind === "copying" || v.kind === "checking") {
      const rate = (this.pace.get(job.id) || {}).rate || 0;
      if (rate > 0) {
        parts.push(MoveTracker.speed(rate));
        const left = MoveTracker.eta((2 * (row.size || 0) - MoveTracker.work(row)) / rate);
        if (left) parts.push(left);
      }
    }
    // A checked copy waits before the one here goes — the library confirms a
    // write before its disks hold it. The row counts that wait down instead of
    // standing at "checked" for two minutes with nothing to say why.
    if (v.kind === "checked" && row.removeIn > 0) parts.push(MoveTracker.eta(row.removeIn));
    return parts.join(" · ");
  }

  static tip(row) {
    return `${fmtGb(row.done || 0)} / ${fmtGb(row.size || 0)}${row.detail ? ` — ${row.detail}` : ""}`;
  }

  // The bar on a file's row while it travels — where to, the pass, how fast
  // and how long — with Stop right beside it.
  rowHtml(path) {
    const hit = this.onWay(path);
    if (!hit) return "";
    const { job, row } = hit;
    const v = MoveTracker.view(job, row);
    const stop = escapeHtml(t("moveStop"));
    return `<span class="mdl-dl mdl-move-bar${v.stalled ? " stalled" : ""}" data-t="models-move-progress" data-t-id="${escapeHtml(path)}"`
      + ` data-move-job="${escapeHtml(job.id)}" data-move-path="${escapeHtml(path)}" title="${escapeHtml(MoveTracker.tip(row))}">`
      + `<span class="mdl-dl-bar" style="width:${v.width}%"></span><span class="mdl-dl-text">${escapeHtml(this.label(job, row, v))}</span></span>`
      + `<button class="mdl-mini mdl-move-stop" type="button" data-move-stop="${escapeHtml(job.id)}" data-t="models-move-stop"`
      + ` data-t-id="${escapeHtml(path)}" title="${stop}" aria-label="${stop}">✕</button>`;
  }

  // The note a finished move left on a file that stayed here.
  stayedHtml(path) {
    const s = this.stayed(path);
    if (!s) return "";
    const hide = escapeHtml(t("moveStayedHide"));
    return `<span class="mdl-stayed" data-t="models-move-stayed" data-t-id="${escapeHtml(path)}"${s.row.detail ? ` title="${escapeHtml(s.row.detail)}"` : ""}>`
      + `⚠ ${escapeHtml(t("movePhaseSkipped", { why: s.why }))}</span>`
      + `<button class="mdl-mini" type="button" data-move-seen="${escapeHtml(s.job.id)}" data-move-seen-path="${escapeHtml(path)}"`
      + ` data-t="models-move-dismiss" data-t-id="${escapeHtml(path)}" title="${hide}" aria-label="${hide}">×</button>`;
  }

  // How far a branch's files are, on its folded row: a move deep inside must
  // not hide behind a closed ▸.
  branch(trail) {
    const prefix = `${trail}/`;
    let n = 0, work = 0, total = 0, stalled = false;
    for (const [path, { job, row }] of this.byPath) {
      if (!path.startsWith(prefix) || !this.onWay(path)) continue;
      n += 1;
      work += MoveTracker.work(row);
      total += 2 * (row.size || 0);
      // Red when a file in it is held up — not merely queued behind one.
      if (MoveTracker.view(job, row).stalled) stalled = true;
    }
    return n ? { n, pct: pct(work, total), stalled } : null;
  }

  branchHtml(trail) {
    const b = this.branch(trail);
    if (!b) return "";
    return `<span class="mdl-move-branch${b.stalled ? " stalled" : ""}" data-t="models-move-branch" data-t-id="${escapeHtml(trail)}"`
      + ` data-move-branch="${escapeHtml(trail)}">⇢ ${b.n} · ${b.pct}%</span>`;
  }

  // ⇢ on a file's row or a branch: the move the button below makes, for just
  // these files and without picking them first. Absent while no library can
  // take files — the button below says what is missing.
  // `item` is the row it stands on: {size, from, kind}. A branch has none of
  // them — it carries whatever its checkboxes carry.
  openHtml(scope, value, item = {}) {
    const from = item.from || LOCAL_ID;
    const where = this.destinations(from);
    if (!where.length) return "";
    const title = escapeHtml(where.length === 1 ? t("moveSelectedTo", { name: this.nameOf(where[0]) }) : t("moveSelected"));
    return `<button class="mdl-go" type="button" data-move-open="${escapeHtml(value)}" data-move-scope="${scope === "file" ? "file" : "branch"}"`
      + `${from !== LOCAL_ID ? ` data-move-from="${escapeHtml(from)}"` : ""}`
      + `${scope === "file" ? ` data-size="${Number(item.size) || 0}"` : ""}`
      + `${scope === "file" && item.kind ? ` data-kind="${escapeHtml(item.kind)}"` : ""}`
      + ` data-t="models-move-open" data-t-id="${escapeHtml(value)}"`
      + ` title="${title}" aria-label="${title}">⇢</button>`;
  }

  // ── The line by the button ──────────────────────────────────────────────

  totals() {
    let n = 0, work = 0, total = 0, rate = 0, settle = 0;
    for (const job of this.jobs || []) {
      if (FINISHED.has(job.status)) continue;
      for (const row of job.files || []) {
        if (MoveTracker.settled(row)) continue;
        n += 1;
        work += MoveTracker.work(row);
        total += 2 * (row.size || 0);
        settle = Math.max(settle, row.removeIn || 0);
      }
      rate += (this.pace.get(job.id) || {}).rate || 0;
    }
    // The time left: the wait before the checked copy here goes, then the
    // bytes still to go at the last speed read — one after the other, as the
    // worker takes them. With bytes still to go and no speed read yet — a page
    // just opened, the worker holding at a checked copy — the time is NOT
    // known, and the line says none: counted as the wait alone, it read
    // "~20 s left" over three hundred gigabytes still in line (seen live).
    const bytes = total - work;
    const left = bytes > 0 && !(rate > 0) ? null : settle + (bytes > 0 ? bytes / rate : 0);
    return { n, pct: pct(work, total), left };
  }

  summaryText() {
    const s = this.totals();
    if (!s.n) return "";
    const left = MoveTracker.eta(s.left);
    return t("movesInFlight", { n: String(s.n), pct: String(s.pct) }) + (left ? ` · ${left}` : "");
  }

  drawSummary() {
    if (!this.summary) return;
    const text = this.summaryText();
    this.summary.textContent = text;
    this.summary.hidden = !text;
    this.summary.title = text ? t("movesInFlightTip") : "";
  }

  // The line opens the branches its files are in and brings the first bar
  // into view: the tree may be folded, filtered, or scrolled far from them.
  reveal() {
    if (this.onReveal) this.onReveal();
    if (!this.tree) return;
    const trails = new Set();
    for (const path of this.byPath.keys()) {
      if (!this.onWay(path)) continue;
      const segs = path.split("/");
      for (let i = 1; i < segs.length; i += 1) trails.add(segs.slice(0, i).join("/"));
    }
    for (const el of this.tree.querySelectorAll("details[data-branch]")) if (trails.has(el.dataset.branch)) el.open = true;
    const first = this.tree.querySelector("[data-move-path]");
    if (first && first.scrollIntoView) first.scrollIntoView({ block: "center" });
  }

  // ── Talking to the server ───────────────────────────────────────────────

  async refresh() {
    try {
      const res = await api("/api/model-stores/moves");
      if (res && Array.isArray(res.jobs)) {
        this.jobs = res.jobs;
        this.measure();
        this.reindex();
      }
    } catch { /* a missed poll keeps the last picture; the next one tries again */ }
    this.drawSummary();
    this.schedule();
  }

  // Speed from the work each open job did between two answers, smoothed:
  // blocks arrive in bursts.
  measure() {
    const now = this.now();
    const open = new Set();
    for (const job of this.jobs) {
      if (FINISHED.has(job.status)) continue;
      open.add(job.id);
      const prev = this.pace.get(job.id);
      const work = job.workDone || 0;
      let rate = prev ? prev.rate : 0;
      // A pause in the bytes — the wait after a check, a library holding up —
      // is not a slower link: the speed keeps its last reading. Letting it
      // fade made the time left for what is queued grow without bound (seen
      // live: "~299 h 24 min left" while a checked copy waited).
      if (prev && now > prev.t && work > prev.work) {
        const seen = (work - prev.work) / ((now - prev.t) / 1000);
        rate = prev.rate ? prev.rate + PACE_WEIGHT * (seen - prev.rate) : seen;
      }
      this.pace.set(job.id, { t: now, work, rate });
    }
    for (const id of [...this.pace.keys()]) if (!open.has(id)) this.pace.delete(id);
  }

  schedule() {
    clearTimeout(this.timer);
    this.timer = null;
    // Polling runs only while something moves, and stops on its own after.
    if ((this.jobs || []).some((j) => !FINISHED.has(j.status))) this.timer = setTimeout(() => this.tick(), POLL_MS);
  }

  // Everything that changes what the TREE draws: which files travel and
  // which carry a note. Bytes are not in it — they move in place (update),
  // because a tree rebuilt every 1.2 s would fold branches and eat the click
  // on Stop.
  shape() {
    const parts = [];
    for (const path of this.byPath.keys()) {
      if (this.onWay(path)) parts.push(`>${path}`);
      else if (this.stayed(path)) parts.push(`!${path}`);
    }
    return parts.sort().join("|");
  }

  async tick() {
    const before = this.shape();
    await this.refresh();
    // A file arrived, a file stayed, a job ended: the tree and the stores have
    // changed under the page, and it redraws them. A tick that only moved
    // bytes changed nothing there.
    if (this.shape() !== before) this.onChange();
    else this.update();
  }

  // Bytes moved, the shape did not: bars, words and counts change in place,
  // read off the elements themselves — a path is free to contain anything,
  // and a selector built from it would break on the first quote.
  update() {
    if (this.tree) {
      for (const el of this.tree.querySelectorAll("[data-move-path]")) {
        const hit = this.onWay(el.dataset.movePath);
        if (!hit) continue;
        const v = MoveTracker.view(hit.job, hit.row);
        const bar = el.querySelector(".mdl-dl-bar");
        const text = el.querySelector(".mdl-dl-text");
        if (bar) bar.style.width = `${v.width}%`;
        if (text) text.textContent = this.label(hit.job, hit.row, v);
        el.title = MoveTracker.tip(hit.row);
        el.classList.toggle("stalled", v.stalled);
      }
      for (const el of this.tree.querySelectorAll("[data-move-branch]")) {
        const b = this.branch(el.dataset.moveBranch);
        if (!b) continue;
        el.textContent = `⇢ ${b.n} · ${b.pct}%`;
        el.classList.toggle("stalled", b.stalled);
      }
    }
    this.drawSummary();
  }

  // ── Starting, stopping, hiding ──────────────────────────────────────────

  async start(files = this.picked(), target = this.target(), from = LOCAL_ID) {
    if (!target || !files.length) return;
    const size = fmtGb(files.reduce((a, f) => a + (f.size || 0), 0));
    // A folder counts as one item here, as it does everywhere else — but it is
    // thousands of files on the wire, so the confirm says how many of the items
    // are folders before the copying starts.
    const folders = files.filter((f) => f.kind).length;
    const text = t("moveConfirm", { count: String(files.length), size, name: this.nameOf(target) })
      + (folders ? `\n\n${t("moveConfirmFolders", { n: String(folders) })}` : "");
    // The pack llama carries a parcel to the library shelf: this dialog is
    // about carrying, and the crate-stomping scene it used to borrow is the
    // one that means deleting.
    if (!(await appConfirm(text, { title: t("movesTitle"), confirmLabel: t("moveStart"), danger: false, scene: "move" }))) return;
    if (this.button) this.button.disabled = true;
    try {
      const res = await api("/api/model-stores/move", { method: "POST", body: { files: files.map((f) => f.path), to: target.id, from } });
      if (res && res.ok === false) throw new Error(res.error || "failed");
      await this.refresh();
      this.onChange();
    } catch (err) {
      toast(String((err && err.message) || err));
    } finally {
      this.syncButton();
    }
  }

  // What a ⇢ carries: its own file, or everything in its branch that offers a
  // ⇢ of its own — the same rule in one place instead of two. Rows that carry
  // "from" are library rows: a branch's ⇢ moves what is on THIS disk, and
  // asking the disk for a file that is in a library would be asking for a file
  // that is not there.
  static filesFor(btn) {
    if (btn.dataset.moveScope === "file") {
      return [{ path: btn.dataset.moveOpen, size: Number(btn.dataset.size || 0), kind: btn.dataset.kind || "" }];
    }
    const branch = btn.closest ? btn.closest("details") : null;
    if (!branch) return [];
    return [...branch.querySelectorAll('[data-move-scope="file"]')].filter((el) => !el.dataset.moveFrom)
      .map((el) => ({ path: el.dataset.moveOpen, size: Number(el.dataset.size || 0), kind: el.dataset.kind || "" }));
  }

  async open(btn) {
    // Where the files sit now: this disk unless the row says otherwise — a
    // library's row carries its store, so a move back starts from there.
    const from = btn.dataset.moveFrom || LOCAL_ID;
    const files = MoveTracker.filesFor(btn);
    const where = this.destinations(from);
    if (!files.length || !where.length) return undefined;
    // One place to go needs no list: the question names it.
    if (where.length === 1) return this.start(files, where[0], from);
    this.showMenu(btn, where, (store) => this.start(files, store, from));
    return undefined;
  }

  // Several places to go: a short list by the ⇢, each with its free space.
  showMenu(btn, libs, pick) {
    this.closeMenu();
    const doc = globalThis.document;
    const menu = doc.createElement("div");
    menu.className = "mdl-move-menu";
    menu.setAttribute("role", "menu");
    menu.setAttribute("aria-label", t("a11yMoveMenu"));
    menu.dataset.t = "models-move-menu";
    menu.innerHTML = libs.map((s) => `<button type="button" role="menuitem" data-move-dest="${escapeHtml(s.id)}" data-t="models-move-dest"`
      + ` data-t-id="${escapeHtml(s.id)}">${s.role === "local" ? "🏠" : "📚"} ${escapeHtml(this.nameOf(s))}`
      + `${s.total ? `<span class="meta">${escapeHtml(t("storeFree", { free: fmtGb(s.free || 0), total: fmtGb(s.total) }))}</span>` : ""}</button>`).join("");
    const r = btn.getBoundingClientRect ? btn.getBoundingClientRect() : { left: 0, bottom: 0 };
    menu.style.left = `${Math.round(Math.max(8, Math.min(r.left, (globalThis.innerWidth || 1e6) - 280)))}px`;
    menu.style.top = `${Math.round(r.bottom + 4)}px`;
    menu.addEventListener("click", (e) => {
      const dest = e.target && e.target.closest ? e.target.closest("[data-move-dest]") : null;
      const lib = dest && libs.find((s) => s.id === dest.dataset.moveDest);
      if (!lib) return;
      this.closeMenu();
      pick(lib);
    });
    doc.body.appendChild(menu);
    this.menu = menu;
    // A click anywhere else or Escape closes it. Added while the opening
    // click is on its way down, a capturing listener does not see that click.
    this.menuClose = (e) => {
      if (e.type === "keydown" ? e.key === "Escape" : !menu.contains(e.target)) this.closeMenu();
    };
    doc.addEventListener("click", this.menuClose, true);
    doc.addEventListener("keydown", this.menuClose, true);
  }

  closeMenu() {
    if (!this.menu) return;
    const doc = globalThis.document;
    this.menu.remove();
    doc.removeEventListener("click", this.menuClose, true);
    doc.removeEventListener("keydown", this.menuClose, true);
    this.menu = null;
    this.menuClose = null;
  }

  async stop(id, btn) {
    // Stop is on a file's row, but it stops the whole move: the question says
    // so when the move carries more than this file.
    const job = (this.jobs || []).find((j) => j.id === id);
    const left = job ? (job.files || []).filter((r) => !MoveTracker.settled(r)).length : 0;
    const text = t("moveStopConfirm") + (left > 1 ? `\n\n${t("moveStopConfirmJob", { count: String(left) })}` : "");
    if (!(await appConfirm(text, { title: t("movesTitle"), confirmLabel: t("moveStop"), scene: "move" }))) return;
    if (btn) btn.disabled = true;
    try {
      const res = await api("/api/model-stores/moves/cancel", { method: "POST", body: { id } });
      if (res && res.ok === false) throw new Error(res.error || "failed");
      await this.tick();
    } catch (err) {
      toast(String((err && err.message) || err));
      if (btn) btn.disabled = false;
    }
  }

  // The note leaves in place: a whole redraw for one hidden line would fold
  // the branch the operator is reading.
  dismiss(btn) {
    this.seen.add(`${btn.dataset.moveSeen}|${btn.dataset.moveSeenPath}`);
    this.saveSeen();
    const note = btn.previousElementSibling;
    if (note && note.dataset && note.dataset.t === "models-move-stayed") note.remove();
    btn.remove();
  }

  bind() {
    // Delegation: the tree is rebuilt whenever its shape changes, and a
    // handler bound to a button would leave together with the button.
    if (this.tree) {
      this.tree.addEventListener("click", (e) => {
        const find = (sel) => (e.target && e.target.closest ? e.target.closest(sel) : null);
        const stop = find("[data-move-stop]");
        if (stop) return this.stop(stop.dataset.moveStop, stop);
        const open = find("[data-move-open]");
        if (open) {
          // A branch's ⇢ sits on its summary: the click moves, it does not fold.
          e.preventDefault();
          return this.open(open);
        }
        const seen = find("[data-move-seen]");
        if (seen) return this.dismiss(seen);
        return undefined;
      });
    }
    if (this.summary) {
      this.summary.addEventListener("click", () => this.reveal());
      this.summary.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); this.reveal(); }
      });
    }
    if (this.button) this.button.addEventListener("click", () => this.start());
  }

  // A new language: the line by the button and the button speak it; the
  // page redraws the tree itself.
  render() {
    this.drawSummary();
    this.syncButton();
  }
}

// The page's one entry point: models-page.js mounts the tracker with the tree,
// the line and the button, asks it what each row says, and tells it when the
// selection changes.
export const mountMoves = (opts) => MoveTracker.mount(opts);
