// Getting files onto the models disk from /hf: the selection, the plan of
// where each file lands, the jobs on the server and the partials they left.
//
// The selection spans repositories and survives a new search. The plan shows,
// before anything is sent, the folder each file lands in, whether the whole
// selection fits the models disk and which files it would write over. Starting
// sends one job per repository (the endpoint takes one repository id). Writing
// over a file on disk and downloading more than fits both ask first, in the
// page's own dialog; a declined question sends nothing.
//
// Jobs are polled while they run, including while the server retries a dropped
// connection. Cancel stops the job on the server; what it fetched comes back as
// an interrupted partial with Resume. Jobs survive a reload: the server lists
// them, and this browser's own list is the fallback when it cannot.
import { escapeHtml } from "./utils.js";
import { HfFormat, hfT } from "./hf-text.js";

//: This browser's own copy of the running jobs, for when the server list fails.
const STORE_KEY = "hfDlJobs";
//: How often a running job is asked about.
const POLL_MS = 600;
//: A finished job stays on screen this long, then leaves.
const DONE_LINGER_MS = 4000;
//: Room a multi-part file needs on top of its size while it is assembled.
const ASSEMBLY_SLACK_GB = 5;
const GIB = 1073741824;

export class HfDownloads {
  // `confirm(title, body, okLabel, danger)` resolves true or false;
  // `onFinished(repoId)` hears about a job that landed its files.
  constructor({ getJson, postJson, confirm, toast, storage, later, now, onChange, onFinished } = {}) {
    this.getJson = getJson;
    this.postJson = postJson;
    this.confirm = confirm;
    this.toast = toast || (() => {});
    this.storage = storage;
    this.later = later || ((fn, ms) => setTimeout(fn, ms));
    this.now = now || (() => Date.now());
    this.onChange = onChange || (() => {});
    this.onFinished = onFinished || (() => {});
    this.selection = new Map();
    this.jobs = [];
    this.interrupted = [];
    this.disk = null;
    this.seq = 0;
    this.detailsOpen = false;
    this.jobsOpen = false;
  }

  static destDir(repoId, file) {
    const author = repoId.includes("/") ? repoId.split("/")[0] : "unknown";
    return `${repoId.split("/").pop()}/${author}/${file.quant || "default"}`;
  }

  static checkpointDir(repoId, format) {
    const author = repoId.includes("/") ? repoId.split("/")[0] : "unknown";
    return `${repoId.split("/").pop()}/${author}/${format}`;
  }

  changed() {
    this.onChange();
  }

  // ── the selection ─────────────────────────────────────────────────────────
  toggle(repoId, files, on) {
    const picked = this.selection.get(repoId) || new Map();
    for (const f of files) {
      if (on) picked.set(f.path, f);
      else picked.delete(f.path);
    }
    if (picked.size) this.selection.set(repoId, picked);
    else this.selection.delete(repoId);
    this.changed();
  }

  picks(repoId) {
    return [...((this.selection.get(repoId) || new Map()).keys())];
  }

  remove(repoId, path) {
    const picked = this.selection.get(repoId);
    if (!picked) return;
    picked.delete(path);
    if (!picked.size) this.selection.delete(repoId);
    this.changed();
  }

  clear() {
    this.selection.clear();
    this.detailsOpen = false;
    this.changed();
  }

  files() {
    return [...this.selection.entries()].flatMap(([repoId, picked]) => [...picked.values()].map((file) => ({ repoId, file })));
  }

  count() {
    return this.files().length;
  }

  bytes() {
    return this.files().reduce((sum, { file }) => sum + (Number(file.size) || 0), 0);
  }

  // Where everything lands, grouped by repository and folder, and which of it
  // is already on disk by name. The server is the one that refuses to write
  // over a file; this is the warning before the button, not the guard.
  plan(localNamesOf) {
    const groups = [];
    const overwrite = [];
    for (const [repoId, picked] of this.selection) {
      const dirs = new Map();
      const local = (localNamesOf && localNamesOf(repoId)) || new Set();
      for (const file of picked.values()) {
        const dir = HfDownloads.destDir(repoId, file);
        if (!dirs.has(dir)) dirs.set(dir, []);
        dirs.get(dir).push(file);
        if (local.has(file.name)) overwrite.push(`${dir}/${file.name}`);
      }
      groups.push({ repoId, dirs: [...dirs.entries()].map(([dir, files]) => ({ dir, files })) });
    }
    return { groups, count: this.count(), bytes: this.bytes(), overwrite };
  }

  setDisk(info) {
    this.disk = info && info.ok ? info : null;
  }

  // Needs the files plus room to assemble a split one. Unknown disk: no claim.
  fit(bytes) {
    if (!this.disk) return { known: false };
    const needGb = bytes / GIB + ASSEMBLY_SLACK_GB;
    const freeGb = Number(this.disk.freeGb) || 0;
    return { known: true, needGb, freeGb, totalGb: Number(this.disk.totalGb) || 0, fits: needGb <= freeGb, leftGb: freeGb - bytes / GIB };
  }

  async askRoom(bytes) {
    const fit = this.fit(bytes);
    if (!fit.known || fit.fits) return true;
    return this.confirm(hfT("diskFitTitle"), hfT("diskFitBody", { need: fit.needGb.toFixed(1), free: fit.freeGb }), hfT("diskFitOk"), true);
  }

  // ── starting ──────────────────────────────────────────────────────────────
  async start() {
    const byRepo = [...this.selection.entries()].map(([repoId, picked]) => [repoId, [...picked.values()]]);
    if (!byRepo.length) return;
    if (!(await this.askRoom(this.bytes()))) return;
    for (const [repoId, files] of byRepo) {
      const payload = files.map((f) => ({ path: f.path, name: f.name, size: f.size, destDir: HfDownloads.destDir(repoId, f) }));
      await this.launch(repoId, payload);
    }
  }

  // A safetensors checkpoint is one artifact in one folder, asked about first.
  async startCheckpoint(repoId, st) {
    const destDir = HfDownloads.checkpointDir(repoId, st.format);
    if (!(await this.askRoom(Number(st.totalSize) || 0))) return;
    // The size in the units the checkpoint row shows it in.
    if (!(await this.confirm(`⬇ ${st.format} · ${HfFormat.bytes(st.totalSize)}`, `${repoId} → ${destDir}/`, hfT("a11yStartDownload"), false))) return;
    await this.launch(repoId, st.files.map((f) => ({ path: f.path, name: f.name, size: f.size, destDir })), false);
  }

  async launch(repoId, payload, fromSelection = true) {
    const job = this.addJob({ repoId, title: repoId, totalFiles: payload.length, state: "starting" });
    this.jobsOpen = true;
    this.changed();
    let answer;
    try {
      answer = await this.send(repoId, payload);
    } catch (e) {
      answer = { ok: false, error: String((e && e.message) || e) };
    }
    if (answer.declined) {
      this.dropJob(job);
      return;
    }
    if (!answer.ok) {
      job.state = "error";
      job.error = answer.error || "unknown";
      this.changed();
      return;
    }
    job.jobId = answer.jobId;
    job.state = "running";
    // The files belong to the job now: out of the selection, so the button
    // cannot start a second job for the same destinations.
    if (fromSelection) {
      const picked = this.selection.get(repoId);
      if (picked) {
        for (const p of payload) picked.delete(p.path);
        if (!picked.size) this.selection.delete(repoId);
      }
    }
    this.persist();
    this.changed();
    this.poll(job);
  }

  // Sends a download, asking first when it would write over files already on
  // disk: the server refuses such a download until told otherwise (code
  // "exists", with the files), and only a yes resends it with replace:true.
  async send(repoId, payload) {
    const first = await this.postJson("/api/hf/download", { repo: repoId, files: payload });
    if (first.ok || first.code !== "exists") return first;
    const taken = first.files || [];
    const body = `${hfT("replaceLocalCount", { n: String(taken.length) })}\n${taken.join("\n")}`;
    if (!(await this.confirm(hfT("replaceLocalTitle"), body, hfT("replaceLocalOk"), true))) return { ok: false, declined: true };
    return this.postJson("/api/hf/download", { repo: repoId, files: payload, replace: true });
  }

  // ── jobs ──────────────────────────────────────────────────────────────────
  addJob(fields) {
    const job = { uid: `dlj${++this.seq}`, jobId: null, repoId: "", title: "", totalFiles: 1, pct: 0, state: "starting",
      idx: 0, file: "", filePct: 0, speed: 0, error: "", pollError: "", ...fields };
    this.jobs.push(job);
    return job;
  }

  dropJob(job) {
    this.jobs = this.jobs.filter((j) => j !== job);
    this.persist();
    this.changed();
  }

  poll(job) {
    const tick = async () => {
      if (!this.jobs.includes(job)) return;
      let s;
      try {
        s = await this.getJson(`/api/hf/download/status?job=${encodeURIComponent(job.jobId)}`);
      } catch (e) {
        // A missed answer is not the end of the job: say so and ask again.
        job.pollError = String((e && e.message) || e);
        this.changed();
        this.later(tick, POLL_MS);
        return;
      }
      if (!this.jobs.includes(job)) return;
      if (!s || !s.ok) {
        this.dropJob(job);
        return;
      }
      job.pollError = "";
      job.pct = s.total_bytes > 0 ? Math.round((s.total_bytes_done / s.total_bytes) * 100)
        : (s.total_files > 0 ? Math.round((s.current_idx / s.total_files) * 100) : 0);
      if (s.status === "done") {
        job.state = "done";
        job.pct = 100;
        this.persist();
        this.changed();
        this.onFinished(s.repo || job.repoId);
        this.later(() => this.dropJob(job), DONE_LINGER_MS);
        return;
      }
      if (s.status === "cancelled") {
        this.dropJob(job);
        this.refreshInterrupted();
        return;
      }
      if (s.status === "error") {
        job.state = "error";
        job.error = s.error || "unknown";
        this.persist();
        this.changed();
        return;
      }
      // Running — or retrying a dropped connection, which is still running.
      if (!job.cancelling) job.state = s.status === "retrying" ? "retrying" : "running";
      job.idx = Math.min((Number(s.current_idx) || 0) + 1, job.totalFiles);
      job.file = s.current_file || "";
      job.filePct = s.file_bytes_total > 0 ? Math.round((s.file_bytes_done / s.file_bytes_total) * 100) : 0;
      const t = this.now();
      // No speed from a sample of zero: a resumed job reports nothing until the
      // server has counted the part already on disk, and that jump is not speed.
      if (job.lastBytes > 0 && t > job.lastTime) {
        const inst = (s.total_bytes_done - job.lastBytes) / ((t - job.lastTime) / 1000);
        if (inst >= 0) job.speed = job.speed ? job.speed * 0.7 + inst * 0.3 : inst;
      }
      job.lastBytes = s.total_bytes_done;
      job.lastTime = t;
      this.changed();
      this.later(tick, POLL_MS);
    };
    tick();
  }

  // Stops the job on the server. The poll sees it end and brings back what it
  // fetched as an interrupted partial.
  async cancel(uid) {
    const job = this.jobs.find((j) => j.uid === uid);
    if (!job) return;
    if (!job.jobId) {
      this.dropJob(job);
      return;
    }
    job.cancelling = true;
    job.state = "cancelling";
    this.changed();
    let answer;
    try {
      answer = await this.postJson("/api/hf/download/cancel", { jobId: job.jobId });
    } catch (e) {
      answer = { ok: false, error: String((e && e.message) || e) };
    }
    if (!answer.ok) {
      job.cancelling = false;
      job.state = "running";
      this.toast(hfT("jobCancelFailed", { err: answer.error || "" }));
      this.changed();
    }
  }

  dismiss(uid) {
    const job = this.jobs.find((j) => j.uid === uid);
    if (job && job.state === "error") this.dropJob(job);
  }

  async resume(destDir, name) {
    const row = this.interrupted.find((r) => r.destDir === destDir && r.current_file === name);
    let answer;
    try {
      answer = await this.postJson("/api/hf/download/resume", { destDir, name });
    } catch (e) {
      answer = { ok: false, error: String((e && e.message) || e) };
    }
    if (!answer || !answer.ok) {
      this.toast((answer && answer.error) || "resume failed");
      return;
    }
    // The partial is a live job now: not listed twice while it reports.
    this.interrupted = this.interrupted.filter((r) => r !== row);
    const job = this.addJob({ jobId: answer.jobId, repoId: (row && row.repo) || "", title: (row && (row.repo || row.title)) || name, totalFiles: 1, state: "resuming" });
    this.jobsOpen = true;
    this.persist();
    this.changed();
    this.poll(job);
  }

  // Re-attaches to what the server is still doing, and lists the partials no
  // job owns. This browser's saved list stands in only when the server's
  // cannot be read.
  async restore() {
    let saved = null;
    try {
      const answer = await this.getJson("/api/hf/download/jobs");
      if (answer && answer.ok && Array.isArray(answer.jobs)) {
        this.interrupted = answer.jobs.filter((j) => j.status === "interrupted");
        saved = answer.jobs.filter((j) => j.status !== "interrupted")
          .map((j) => ({ jobId: j.jobId, title: j.title, repoId: j.repo || "", totalFiles: j.total_files }));
      }
    } catch { /* the saved list below */ }
    if (!saved) {
      try {
        saved = JSON.parse((this.storage && this.storage.getItem(STORE_KEY)) || "[]");
      } catch {
        saved = [];
      }
    }
    for (const st of Array.isArray(saved) ? saved : []) {
      if (!st || !st.jobId || this.jobs.some((j) => j.jobId === st.jobId)) continue;
      const job = this.addJob({ jobId: st.jobId, title: st.title || "", repoId: st.repoId || "", totalFiles: st.totalFiles || 1, state: "resuming" });
      this.poll(job);
    }
    // Running downloads open the list; interrupted ones only colour the button,
    // so a partial left from last week does not take half the screen.
    if (this.jobs.length) this.jobsOpen = true;
    this.changed();
  }

  async refreshInterrupted() {
    try {
      const answer = await this.getJson("/api/hf/download/jobs");
      if (answer && answer.ok && Array.isArray(answer.jobs)) {
        this.interrupted = answer.jobs.filter((j) => j.status === "interrupted");
        this.changed();
      }
    } catch { /* the next restore will */ }
  }

  persist() {
    try {
      const live = this.jobs.filter((j) => j.jobId && !["done", "error"].includes(j.state))
        .map((j) => ({ jobId: j.jobId, title: j.title, repoId: j.repoId, totalFiles: j.totalFiles }));
      if (this.storage) this.storage.setItem(STORE_KEY, JSON.stringify(live));
    } catch { /* storage unavailable — the server list still works */ }
  }

  // ── the dock ──────────────────────────────────────────────────────────────
  jobLabel(job) {
    let text;
    switch (job.state) {
      case "starting": text = hfT("jobStarting"); break;
      case "resuming": text = hfT("dlResuming"); break;
      case "cancelling": text = hfT("jobCancelling"); break;
      case "done": text = hfT("jobDone", { n: job.totalFiles }); break;
      case "error": text = hfT("jobError", { err: job.error }); break;
      default: {
        text = hfT("jobFile", { i: job.idx || 1, n: job.totalFiles, name: job.file, pct: job.filePct });
        if (job.speed > 0) text += ` — ${hfT("jobSpeed", { speed: (job.speed / 1048576).toFixed(1) })}`;
        if (job.state === "retrying") text = `${hfT("jobRetrying")} — ${text}`;
      }
    }
    return job.pollError ? `${text} · ${hfT("jobPollError", { err: job.pollError })}` : text;
  }

  visible() {
    return this.count() > 0 || this.jobs.length > 0 || this.interrupted.length > 0;
  }

  html(localNamesOf) {
    const count = this.count();
    const bar = [];
    if (count) {
      const plan = this.plan(localNamesOf);
      const dirs = plan.groups.flatMap((g) => g.dirs.map((d) => `${d.dir}/`));
      const shownDirs = dirs.slice(0, 2).join(" · ") + (dirs.length > 2 ? ` +${dirs.length - 2}` : "");
      bar.push(`<span class="hfp-sel">${escapeHtml(hfT("selSummary", { n: count, size: HfFormat.bytes(plan.bytes) }))}</span>`
        + `<span class="hfp-sel-dirs" title="${escapeHtml(dirs.join("\n"))}">→ ${escapeHtml(shownDirs)}</span>`
        + `<button type="button" class="hfp-btn" data-act="sel-details" data-t="hf-selection-toggle" aria-expanded="${this.detailsOpen}">${escapeHtml(hfT(this.detailsOpen ? "selHide" : "selDetails"))} ${this.detailsOpen ? "▴" : "▾"}</button>`
        + `<button type="button" class="hfp-btn is-primary" data-act="download" data-t="hf-download-start">${escapeHtml(hfT("a11yStartDownload"))}</button>`);
    }
    bar.push(`<span class="grow"></span>`);
    if (this.jobs.length || this.interrupted.length) bar.push(this.jobsButtonHtml());
    let html = `<div class="hfp-dock-bar">${bar.join("")}</div>`;
    if (count && this.detailsOpen) html += this.planHtml(localNamesOf);
    if (this.jobsOpen && (this.jobs.length || this.interrupted.length)) html += this.jobsHtml();
    return html;
  }

  jobsButtonHtml() {
    const running = this.jobs.filter((j) => !["done", "error"].includes(j.state));
    const parts = [hfT("jobsBtn")];
    if (running.length) {
      const pct = Math.round(running.reduce((sum, j) => sum + (j.pct || 0), 0) / running.length);
      parts.push(`${hfT("jobsRunning", { n: running.length })} · ${pct}%`);
    }
    if (this.interrupted.length) parts.push(hfT("jobsInterrupted", { n: this.interrupted.length }));
    const warn = this.interrupted.length || this.jobs.some((j) => j.state === "error");
    return `<button type="button" class="hfp-btn${warn ? " is-warn" : ""}" data-act="jobs" data-t="hf-downloads-toggle" aria-expanded="${this.jobsOpen}">⬇ ${escapeHtml(parts.join(" · "))} ${this.jobsOpen ? "▴" : "▾"}</button>`;
  }

  planHtml(localNamesOf) {
    const plan = this.plan(localNamesOf);
    const groups = plan.groups.map((g) => `<div class="hfp-plan-repo"><div class="hfp-plan-name">${escapeHtml(g.repoId)}</div>`
      + g.dirs.map((d) => `<div class="hfp-plan-dir">${escapeHtml(d.dir)}/</div>`
        + d.files.map((f) => `<div class="hfp-plan-file"><span class="hfp-plan-fn">${escapeHtml(f.name)}</span><span class="hfp-num">${escapeHtml(HfFormat.bytes(f.size))}</span>`
          + `<button type="button" class="hfp-icon-btn" data-act="sel-remove" data-repo="${escapeHtml(g.repoId)}" data-path="${escapeHtml(f.path)}" data-t="hf-selection-remove" data-t-id="${escapeHtml(f.path)}" title="${escapeHtml(hfT("selRemove"))}" aria-label="${escapeHtml(hfT("selRemove"))}">✕</button></div>`).join("")).join("")
      + `</div>`).join("");
    const fit = this.fit(plan.bytes);
    let disk;
    if (!fit.known) {
      disk = `<div class="hfp-plan-disk"><span class="hfp-muted">${escapeHtml(hfT("diskUnknown"))}</span></div>`;
    } else {
      const total = fit.totalGb || fit.freeGb;
      const used = Math.max(0, total - fit.freeGb);
      const pct = (v) => (total > 0 ? Math.min(100, Math.max(0, (v / total) * 100)) : 0).toFixed(1);
      const needGb = plan.bytes / GIB;
      disk = `<div class="hfp-plan-disk"><span class="hfp-diskbar"><i class="used" style="width:${pct(used)}%"></i><i class="plan" style="left:${pct(used)}%;width:${pct(needGb)}%"></i></span>`
        + `<span class="${fit.fits ? "hfp-good" : "hfp-bad"}">${escapeHtml(hfT(fit.fits ? "diskFits" : "diskNoFit"))}</span>`
        // Past the free space "left after" would go negative: say what is
        // missing instead, counted as the question counts it (with room to assemble).
        + `<span class="hfp-muted">${escapeHtml(fit.fits
          ? hfT("diskLeft", { free: fit.freeGb, total: fit.totalGb, left: fit.leftGb.toFixed(1) })
          : hfT("diskShort", { free: fit.freeGb, total: fit.totalGb, short: (fit.needGb - fit.freeGb).toFixed(1) }))}</span></div>`;
    }
    const overwrite = plan.overwrite.length
      ? `<div class="hfp-warn" title="${escapeHtml(plan.overwrite.join("\n"))}">⚠ ${escapeHtml(hfT("overwriteSome", { n: plan.overwrite.length }))}</div>`
      : `<div class="hfp-good">✓ ${escapeHtml(hfT("overwriteNone"))}</div>`;
    return `<div class="hfp-plan" data-t="hf-selection-plan">${groups}${disk}<div class="hfp-line">${overwrite}<span class="grow"></span>`
      + `<button type="button" class="hfp-link" data-act="sel-clear" data-t="hf-selection-clear">${escapeHtml(hfT("selClear"))}</button></div></div>`;
  }

  jobsHtml() {
    const rows = this.jobs.map((job) => {
      const live = !["done", "error", "cancelling"].includes(job.state);
      const action = live
        ? `<button type="button" class="hfp-btn" data-act="job-cancel" data-uid="${escapeHtml(job.uid)}" data-t="hf-download-cancel" data-t-id="${escapeHtml(String(job.jobId || job.uid))}" aria-label="${escapeHtml(hfT("jobCancel"))}">${escapeHtml(hfT("cancelWord"))}</button>`
        : (job.state === "error" ? `<button type="button" class="hfp-icon-btn" data-act="job-dismiss" data-uid="${escapeHtml(job.uid)}" data-t="hf-download-dismiss" aria-label="${escapeHtml(hfT("frontierClose"))}">✕</button>` : "");
      return `<div class="hfp-job is-${escapeHtml(job.state)}" data-t="hf-download-job" data-t-id="${escapeHtml(String(job.jobId || job.uid))}">`
        + `<div class="hfp-job-main"><div class="hfp-job-title">${escapeHtml(job.title)}</div>`
        + `<span class="hfp-bar"><i style="width:${Math.min(100, job.pct || 0)}%"></i></span>`
        + `<div class="hfp-job-label">${escapeHtml(this.jobLabel(job))}</div></div>${action}</div>`;
    });
    for (const row of this.interrupted) {
      const done = row.total_bytes_done || 0;
      const total = row.total_bytes || 0;
      const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
      const size = total > 0 ? `${HfFormat.bytes(done)} / ${HfFormat.bytes(total)}` : HfFormat.bytes(done);
      const name = row.current_file || "";
      const resume = row.resumable
        ? `<button type="button" class="hfp-btn" data-act="resume" data-dest="${escapeHtml(row.destDir || "")}" data-name="${escapeHtml(name)}" data-t="hf-download-resume" data-t-id="${escapeHtml(name)}">${escapeHtml(hfT("dlResume"))}</button>`
        : "";
      rows.push(`<div class="hfp-job is-interrupted" data-t="hf-download-interrupted" data-t-id="${escapeHtml(name)}">`
        + `<div class="hfp-job-main"><div class="hfp-job-title">${escapeHtml(row.title || "")} · ${escapeHtml(name)}</div>`
        + `<span class="hfp-bar is-stalled"><i style="width:${pct}%"></i></span>`
        + `<div class="hfp-job-label hfp-warn">${escapeHtml(hfT(row.resumable ? "dlInterrupted" : "dlInterruptedNoManifest", { size }))}</div></div>${resume}</div>`);
    }
    return `<div class="hfp-jobs" data-t="hf-downloads">${rows.join("")}</div>`;
  }
}
