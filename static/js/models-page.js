// /models page: tree of downloaded GGUFs (model → author → quant → files)
// with size rollups, which cells reference each file, and deletion of the
// unreferenced ones. Data: /api/models/unused + /api/models/disk; deletion:
// /api/models/gc (refuses referenced files server-side too).
import { appConfirm, settleAppConfirm } from "./dialogs.js";
import { initDialogLlamas } from "./dialog-llamas.js";
import { applyLanguage, applyTheme, initLanguage, onLangChange, setupLangSelect, t } from "./i18n.js";
import { ui } from "./state.js";
import { $, api, escapeHtml, markPageState, toast, fillVersionChipFromHealth } from "./utils.js";

function fmtGb(bytes) {
  const gb = bytes / 2 ** 30;
  return gb >= 100 ? `${Math.round(gb)} GB` : `${gb.toFixed(gb >= 10 ? 1 : 2)} GB`;
}

function stat(label, value, kind = "") {
  return `<div class="mdl-stat ${kind}"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`;
}

function updatePicked() {
  const picked = [...document.querySelectorAll("#mdlTree input[data-del-path]:checked")];
  const bytes = picked.reduce((a, el) => a + Number(el.dataset.size || 0), 0);
  $("mdlPicked").textContent = picked.length ? `${picked.length} · ${fmtGb(bytes)}` : "";
  $("mdlDelete").disabled = !picked.length;
}

async function refresh() {
  const tree = $("mdlTree");
  // Capture what lives in the markup FIRST, and only then wipe it. The "…"
  // placeholder carries away every <details> and shortens the page — after
  // it runs there are no open branches left, and scroll is already zero, so
  // asking either of them afterward is pointless. The first cut asked
  // afterward, and the snapshot didn't catch it: the DOM stub answered the
  // same before and after the wipe.
  const openBranches = treeOpenBranches();
  const wasScrolled = typeof window !== "undefined" ? window.scrollY || 0 : 0;
  tree.innerHTML = `<p class="muted">…</p>`;
  let data, disk = null, fresh = null, jobs = null;
  try {
    // Freshness comes from the SAVED watcher report, not a trip to HF on
    // every redraw: 75 files across 20 repositories would be 20 outbound
    // requests for a page that's opened to look at the disk.
    [data, disk, fresh, jobs] = await Promise.all([
      api("/api/models/unused"),
      api("/api/models/disk").catch(() => null),
      api("/api/models/freshness").catch(() => null),
      // Jobs live on the SERVER. So progress survives a page reload, is
      // visible in another tab, and shows downloads started from /hf.
      api("/api/hf/download/jobs").catch(() => null),
    ]);
  } catch (err) {
    tree.innerHTML = `<p class="muted">${escapeHtml(String(err.message || err))}</p>`;
    markPageState("error", err.message);
    return;
  }
  if (!data.ok) {
    tree.innerHTML = `<p class="muted">${escapeHtml(data.error || "models dir not found")}</p>`;
    markPageState("error", data.error || "models dir not found");
    return;
  }
  const files = data.files || [];
  const totalBytes = files.reduce((a, f) => a + f.sizeBytes, 0);
  $("mdlPath").textContent = data.path || "";
  const hero = $("mdlHeroStats");
  const tiles = [
    stat("GGUF", String(files.length)),
    stat(t("ctrlModels"), fmtGb(totalBytes)),
    stat(t("gcTitle"), `${data.unusedCount} · ${data.unusedGb} GB`, data.unusedCount ? "warn" : "good"),
  ];
  if (disk && disk.ok) tiles.push(stat(t("ctrlDisk"), `${disk.freeGb} GB ${t("ctrlDiskFree")}`, (disk.freeGb || 0) < 50 ? "warn" : "good"));
  hero.innerHTML = tiles.join("");

  // Group flat rel-paths into model → author → quant → files. Each level also
  // rolls up the FRESHEST file age inside it — the collapsed row answers
  // "when was anything in here last touched" without expanding.
  // The key is the file's PATH, the same one data-t-id and the delete
  // checkbox already carry. By name, two quants of one repository are
  // indistinguishable: a live check found the same file in `Q5_K_M` and
  // `default`, and by name the tree lit up both rows with one verdict,
  // counting one divergence as two.
  // What's downloading right now: file path → how many bytes out of how
  // many. The same key as the tree row, so the bar is drawn ON ITS OWN file
  // no matter how many downloads run at once. Progress used to be a single
  // one for the whole page, and a second button press erased the first one's
  // reading.
  const dlByPath = downloadsByPath(jobs);
  const prevByPath = (fresh && fresh.prev) || {};
  const freshByPath = new Map();
  for (const repo of Object.values((fresh && fresh.repos) || {})) {
    for (const [key, row] of Object.entries(repo.files || {})) freshByPath.set(key, row);
  }
  const differsAt = (path) => {
    const row = freshByPath.get(path);
    return row && (row.state === "size" || row.state === "date") ? 1 : 0;
  };
  // The buttons live right on the file's row: looking for them anywhere else
  // after spotting a ⇪ here is an extra step at the exact moment the
  // decision is already made.
  const updateBtns = (path) => {
    // While a file is downloading, its row has no button at all: there's a
    // bar instead. A button next to an active download would be offering to
    // start what's already running.
    const dl = dlByPath.get(path);
    if (dl) return progressBar(path, dl);
    const st = prevByPath[path] || {};
    const row = freshByPath.get(path);
    const differs = row && (row.state === "size" || row.state === "date");
    const get = differs
      ? `<button class="mdl-mini get" type="button" data-t="models-staged-download"`
        + ` data-staged-get="${escapeHtml(path)}" title="${escapeHtml(t("mdlStagedGetTip"))}">`
        + `${escapeHtml(t("mdlStagedGet"))}</button>`
      : "";
    // The rollback shows only while the kept build is STILL THERE. It no
    // longer exists on HF, so the size next to it is the cost of the
    // decision, not decoration.
    return get + (st.prev ? prevBtn(path, st) : "");
  };
  // The previous build is no longer on HF — there's nowhere to get it back
  // from except this copy. So the rollback button shows while the copy
  // exists, with its size right next to it: freeing that space is also the
  // operator's decision.
  const prevBtn = (path, st) => `<button class="mdl-mini prev" type="button" data-t="models-staged-revert"`
    + ` data-staged-prev="${escapeHtml(path)}" title="${escapeHtml(t("mdlStagedPrevTip"))}">`
    + `${escapeHtml(t("mdlStagedPrev"))} · ${fmtGb(st.prevSize || 0)}</button>`;
  const grouped = new Map();
  files.forEach((f) => {
    const segs = f.path.split("/");
    const model = segs.length > 1 ? segs[0] : "(root)";
    const author = segs.length > 2 ? segs[1] : "·";
    const quant = segs.length > 3 ? segs[2] : "·";
    // Freshness rolls up the tree the same way bytes and age do: a file's
    // icon isn't visible until its branch is opened — and a collapsed list
    // exists for exactly that reason: so you don't have to open everything
    // just to find ten files.
    const d = differsAt(f.path);
    if (!grouped.has(model)) grouped.set(model, { bytes: 0, minAge: Infinity, differs: 0, children: new Map() });
    const l1 = grouped.get(model); l1.bytes += f.sizeBytes; l1.minAge = Math.min(l1.minAge, f.ageDays); l1.differs += d;
    if (!l1.children.has(author)) l1.children.set(author, { bytes: 0, minAge: Infinity, differs: 0, children: new Map() });
    const l2 = l1.children.get(author); l2.bytes += f.sizeBytes; l2.minAge = Math.min(l2.minAge, f.ageDays); l2.differs += d;
    if (!l2.children.has(quant)) l2.children.set(quant, { bytes: 0, minAge: Infinity, differs: 0, files: [] });
    const l3 = l2.children.get(quant); l3.bytes += f.sizeBytes; l3.minAge = Math.min(l3.minAge, f.ageDays); l3.differs += d;
    l3.files.push(f);
  });
  // filename → state from the report. The key is the name because the
  // report is stored per repository, while this tree is grouped by
  // directory; same-named files from different repositories already sit in
  // different branches on disk.
  const freshChip = (path) => {
    const row = freshByPath.get(path);
    // No entry means not checked. Stay silent: an empty space is more honest than a ✓.
    if (!row || row.state === "same") return "";
    if (row.state === "unknown") return `<span class="mdl-fresh unknown" title="${escapeHtml(t("mdlFreshUnknown"))}">?</span>`;
    const title = t("mdlFreshNewer", {
      ours: `${fmtGb(row.localSize || 0)} · ${row.localDate || "?"}`,
      theirs: `${fmtGb(row.remoteSize || 0)} · ${row.remoteDate || "?"}`,
    });
    return `<span class="mdl-fresh newer" title="${escapeHtml(title)}">⇪</span>`;
  };
  const fileRow = (f) => {
    const name = f.path.split("/").pop();
    const usedBy = (f.referencedBy || []).join(", ");
    const used = f.referenced
      ? `<span class="mdl-used" title="${escapeHtml(usedBy)}">✓ ${escapeHtml(usedBy || "used")}</span>`
      // data-t-id is the model's PATH, not its display name: the name is just
      // the last segment and two quantisations of the same model share it, so a
      // test selecting by name would pick whichever came first. The path is
      // what the delete call sends.
      // aria-label is the path, the same string data-t-id carries. Without it a
      // screen reader reads fifty-nine identical "checkbox, not checked", and
      // the control after the list is Delete selected — so a keyboard user could
      // pick files for deletion with no way to hear which ones. The name exists
      // already; it was simply not exposed.
      : `<input type="checkbox" aria-label="${escapeHtml(f.path)}" data-t="models-model-select" data-t-id="${escapeHtml(f.path)}"`
        + ` data-del-path="${escapeHtml(f.path)}" data-size="${f.sizeBytes}">`;
    return `<div class="mdl-file">${used}${freshChip(f.path)}<code title="${escapeHtml(f.path)}">${escapeHtml(name)}</code>` +
      `${updateBtns(f.path)}` +
      `<span class="meta">${fmtGb(f.sizeBytes)} · ${f.ageDays}d</span></div>`;
  };
  const freshness = (age) => (age === Infinity ? "" : ` · ${age}d`);
  // Three nesting levels — model, author, quantisation — all rendered by this
  // one helper, so they share a hook and are told apart by data-t-id. The
  // <summary> carries its own hook because that is the element you click to
  // expand: `details > summary`, direct child, since a nested details' summary
  // would otherwise match too.
  // The count on a collapsed row: "how many inside need attention". Zero
  // means empty, not "0": the page shows what needs a look, not a tally.
  const groupChip = (node) => (node.differs
    ? `<span class="mdl-fresh newer" title="${escapeHtml(t("mdlFreshGroup", { n: String(node.differs) }))}">⇪ ${node.differs}</span>`
    : "");
  // Open branches survive a redraw (captured above, before the wipe). The
  // whole tree is rebuilt from scratch after every action, and without this
  // pressing "update" deep inside it collapsed everything — taking down the
  // very progress bar the operator had started it to watch. The key is the
  // CHAIN of labels from the root: one label ("bartowski", "Q8_0") repeats
  // across different branches, and keying on it alone would open someone
  // else's branches too.
  const lvl = (label, node, inner, trail = "") => `
    <details data-t="models-tree-group" data-t-id="${escapeHtml(label)}"${node.differs ? " data-differs=\"1\"" : ""}`
      + ` data-branch="${escapeHtml(trail)}"${openBranches.has(trail) ? " open" : ""}>
      <summary data-t="models-tree-group-toggle" data-t-id="${escapeHtml(label)}"><span class="tw"></span><span class="mdl-name">${escapeHtml(label)}</span>${groupChip(node)}
        <span class="mdl-size">${fmtGb(node.bytes)}${freshness(node.minAge)}</span></summary>
      <div class="mdl-lvl">${inner}</div>
    </details>`;
  // Every level sorts largest-first (authors, quants and files too — not just
  // the top-level repos), so the biggest disk eaters always float up.
  const bySize = (a, b) => b[1].bytes - a[1].bytes;
  tree.innerHTML = [...grouped.entries()]
    .sort(bySize)
    .map(([model, l1]) => lvl(model, l1,
      [...l1.children.entries()].sort(bySize).map(([author, l2]) => lvl(author, l2,
        [...l2.children.entries()].sort(bySize).map(([quant, l3]) =>
          lvl(quant, l3, l3.files.slice().sort((a, b) => b.sizeBytes - a.sizeBytes).map(fileRow).join(""),
              `${model}/${author}/${quant}`)).join(""), `${model}/${author}`)).join(""), model))
    .join("") || `<p class="muted">${escapeHtml(t("gcNoUnused"))}</p>`;
  renderFreshnessRow(fresh, files.length, dlByPath);
  updatePicked();
  if (wasScrolled && typeof window.scrollTo === "function") window.scrollTo(0, wasScrolled);
  markPageState("ready");
  dlDrawn = dlSignature(dlByPath);
  // Polling starts ONLY when there's something to show, and stops on its own
  // once no downloads are left: a timer ticking over an empty page is work
  // with nothing to do.
  if (dlByPath.size) pollDownloads();
}

// Time of day configures ONLY the daily check. With the checkbox off, the
// field is disabled: a setting nobody is going to act on would look like a promise.
function applyWatchState(w) {
  const at = $("mdlFreshAt");
  if (at) at.disabled = !w.check;
}

// A timestamp and a count, right next to the button. Without the time, a
// report reads as "just checked", and yesterday's "everything matches" looks
// like today's.
function renderFreshnessRow(fresh, fileCount, dlByPath) {
  const stamp = $("mdlFreshStamp");
  const w = (fresh && fresh.watch) || {};
  const auto = $("mdlFreshAuto");
  if (auto) auto.checked = !!w.check;
  if ($("mdlFreshGet")) $("mdlFreshGet").checked = !!w.download;
  if ($("mdlFreshKeep")) $("mdlFreshKeep").checked = !!w.keepPrev;
  if ($("mdlFreshAt") && w.at) { $("mdlFreshAt").value = w.at; $("mdlFreshAt").__accepted = w.at; }
  applyWatchState(w);
  if (!stamp) return;
  // While something is downloading, the row says so: per-file details live
  // on their own rows, and this is the overall total, visible without
  // scrolling the tree.
  const dl = dlByPath || new Map();
  if (dl.size) {
    stamp.textContent = downloadsSummary(dl);
    return;
  }
  if (!fresh || !fresh.checkedAt) {
    stamp.textContent = t("mdlFreshNever");
    return;
  }
  let differs = 0, checked = 0;
  for (const repo of Object.values(fresh.repos || {})) {
    for (const row of Object.values(repo.files || {})) {
      checked += 1;
      if (row.state === "size" || row.state === "date") differs += 1;
    }
  }
  stamp.textContent = t("mdlFreshStamp", {
    when: new Date(fresh.checkedAt * 1000).toLocaleString(),
    differs: String(differs),
    // The denominator is CHECKED files, not everything on disk: a
    // repository that couldn't be reached must not dissolve into "so-many
    // out of seventy-five".
    files: String(checked || fileCount),
  });
}

// A download runs as a job ON THE SERVER, and the page only displays it.
// Everything else follows from that: progress survives a page reload, is
// visible in a second tab, and covers downloads started from /hf. The page
// keeps no state of its own about downloads — keeping one would be a second
// source of truth.
let stagedPoll = null;
// The signature of the download set the page last DREW. Comparisons must go
// against this, not the DOM: a mismatch against the DOM (a row not yet
// drawn, a file missing from the on-disk list) would mean "redraw" — and the
// very next tick would see the same mismatch again. That's an endless
// redraw loop, not a refresh.
let dlDrawn = "";

const dlSignature = (byPath) => [...byPath.keys()].sort().join("|");

function treeOpenBranches() {
  const open = new Set();
  for (const el of document.querySelectorAll("#mdlTree details[open][data-branch]")) {
    open.add(el.dataset.branch);
  }
  return open;
}

// The overall total across all downloads — the same number as in the status
// row. Computed in one place: two separate tallies of the same thing will
// drift apart (and did — a file's own row kept counting while the total sat
// frozen at zero, because only the render used to update it).
function downloadsSummary(byPath) {
  let done = 0, total = 0;
  for (const x of byPath.values()) { done += x.done || 0; total += x.total || 0; }
  return t("mdlStagedGetting", {
    pct: String(total ? Math.min(100, Math.round((done * 100) / total)) : 0),
  });
}

// Active downloads as {file path: {done, total}}. The key is the
// destination path, because one name can sit in a repository twice, and the
// bar has to land on its own row. `filePaths` line up in order with
// `fileNames`; bytes are known precisely only for the file downloading right
// now, the rest of a job is just waiting its turn.
function downloadsByPath(jobs) {
  const out = new Map();
  for (const job of (jobs && jobs.jobs) || []) {
    if (job.done) continue;
    const paths = job.filePaths || [];
    paths.forEach((path, i) => {
      const current = job.current_path ? job.current_path === path : i === (job.current_idx || 0);
      out.set(path, {
        done: current ? (job.file_bytes_done || 0) : (i < (job.current_idx || 0) ? 1 : 0),
        total: current ? (job.file_bytes_total || 0) : 0,
        // An interrupted download isn't an active one: its bar has stopped,
        // and that has to be said with a word, not with frozen percentages.
        status: job.status || "running",
        whole: i !== (job.current_idx || 0),
      });
    });
  }
  return out;
}

function progressBar(path, dl) {
  const pct = dl.total ? Math.min(100, Math.round((dl.done * 100) / dl.total)) : 0;
  const label = dl.status === "interrupted"
    ? t("mdlStagedInterrupted")
    : (dl.whole ? t("mdlStagedQueued")
                : `${fmtGb(dl.done)} / ${fmtGb(dl.total)} · ${pct}%`);
  return `<span class="mdl-dl${dl.status === "interrupted" ? " stalled" : ""}"`
    + ` data-t="models-staged-progress" data-t-id="${escapeHtml(path)}"`
    + ` data-dl-path="${escapeHtml(path)}" title="${escapeHtml(t("mdlStagedGetTip"))}">`
    + `<span class="mdl-dl-bar" style="width:${pct}%"></span>`
    + `<span class="mdl-dl-text">${escapeHtml(label)}</span></span>`;
}

async function stagedAction(endpoint, file, btn, busyKey) {
  btn.disabled = true;
  const was = btn.textContent;
  btn.textContent = t(busyKey);
  try {
    const res = await api(endpoint, { method: "POST", body: { file } });
    if (res && res.ok === false) throw new Error(res.error || "failed");
    // The job is accepted — from here the shared poller takes over showing
    // it. The page doesn't remember its own jobId: there can be several at
    // once, and remembering just one would crowd out the rest (that's
    // exactly what used to erase the first download's progress).
    await refresh();
  } catch (err) {
    toast(String(err.message || err));
    btn.disabled = false;
    btn.textContent = was;
  }
}

// One poller for every download. Bars move in place — the tree can't be
// redrawn once a second, or collapsed branches would fold shut mid-interaction.
function pollDownloads() {
  clearTimeout(stagedPoll);
  const tick = async () => {
    let jobs = null;
    try { jobs = await api("/api/hf/download/jobs"); } catch { /* network hiccup */ }
    const live = downloadsByPath(jobs);
    // The set changed (something arrived, something started) — redraw the
    // whole thing ONCE: refresh will remember the new set, and the next tick
    // won't repeat this.
    if (dlSignature(live) !== dlDrawn) { await refresh(); return; }
    // Walk the bars already drawn and read the path off the element itself:
    // a filename is free to contain anything, and building a SELECTOR out of
    // it risks a syntax error the day a path shows up with a quote in it.
    for (const el of document.querySelectorAll("[data-dl-path]")) {
      const dl = live.get(el.dataset.dlPath);
      if (!dl) continue;
      const pct = dl.total ? Math.min(100, Math.round((dl.done * 100) / dl.total)) : 0;
      const bar = el.querySelector(".mdl-dl-bar");
      const text = el.querySelector(".mdl-dl-text");
      if (bar) bar.style.width = `${pct}%`;
      if (text && !dl.whole && dl.status !== "interrupted") {
        text.textContent = `${fmtGb(dl.done)} / ${fmtGb(dl.total)} · ${pct}%`;
      }
    }
    // The total updates on the same tick as the bars. Otherwise it stays
    // whatever it was at the moment of drawing — meaning zero.
    const stamp = $("mdlFreshStamp");
    if (stamp && live.size) stamp.textContent = downloadsSummary(live);
    if (live.size) stagedPoll = setTimeout(tick, 1200);
  };
  tick();
}

function bindStagedButtons() {
  const tree = $("mdlTree");
  if (!tree || tree.__stagedBound) return;
  tree.__stagedBound = true;
  // Delegation: the tree is rebuilt from scratch after every action, and
  // handlers bound to the buttons themselves would be gone along with them.
  tree.addEventListener("click", (e) => {
    const get = e.target.closest?.("[data-staged-get]");
    if (get) return stagedAction("/api/models/staged/download", get.dataset.stagedGet, get, "mdlStagedStarting");
    const prev = e.target.closest?.("[data-staged-prev]");
    if (prev) return stagedAction("/api/models/staged/revert", prev.dataset.stagedPrev, prev, "mdlStagedApplying");
  });
}

function bindFreshness() {
  const btn = $("mdlFreshCheck");
  if (btn) {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const was = btn.textContent;
      btn.textContent = t("mdlFreshChecking");
      try {
        await api("/api/models/freshness/check", { method: "POST", body: {} });
        await refresh();
      } catch (err) {
        toast(String(err.message || err));
      } finally {
        btn.disabled = false;
        btn.textContent = was;
      }
    });
  }
  // The checkboxes and the TIME travel as ONE body: the server itself makes
  // the lower tiers required by the upper ones, and decides for itself
  // whether today counts as done — sending fields one at a time would mean
  // arguing with it along the way.
  const boxes = ["mdlFreshAuto", "mdlFreshGet", "mdlFreshKeep"].map((id) => $(id)).filter(Boolean);
  const at = $("mdlFreshAt");
  const sendWatch = async () => {
    const body = {
      check: !!$("mdlFreshAuto")?.checked,
      download: !!$("mdlFreshGet")?.checked,
      keepPrev: !!$("mdlFreshKeep")?.checked,
      at: at ? at.value : "",
    };
    const before = boxes.map((b) => b.checked);
    // A rollback must go to the last time the server ACCEPTED, not to what's
    // in the field: the field already holds the garbage just typed into it,
    // and rolling back to that would be rolling back to nowhere (caught by a pin).
    const wasAt = at ? (at.__accepted || "") : "";
    try {
      const res = await api("/api/models/freshness/watch", { method: "POST", body });
      const w = (res && res.watch) || {};
      if ($("mdlFreshAuto")) $("mdlFreshAuto").checked = !!w.check;
      if ($("mdlFreshGet")) $("mdlFreshGet").checked = !!w.download;
      if ($("mdlFreshKeep")) $("mdlFreshKeep").checked = !!w.keepPrev;
      // The time shown is WHATEVER THE SERVER ACCEPTED: it normalizes "7:5"
      // to "07:05" and is free to reject garbage. Leaving the typed value on
      // screen would show a setting that doesn't exist.
      if (at && w.at) { at.value = w.at; at.__accepted = w.at; }
      applyWatchState(w);
    } catch (err) {
      boxes.forEach((b, i) => { b.checked = before[i]; });
      if (at) at.value = wasAt;
      toast(String(err.message || err));
    }
  };
  boxes.forEach((b) => b.addEventListener("change", sendWatch));
  // change, not input: <input type="time"> fires input on every digit typed,
  // and the server would receive "0", "03", "03:0" in turn — two of those
  // are invalid, and the third would mean midnight.
  if (at) at.addEventListener("change", sendWatch);
}

function bindUserChip() {
  const doLogout = async () => {
    try { await api("/api/auth/logout", { method: "POST", body: "{}" }); } catch { /* ignore */ }
    window.location = "/login";
  };
  api("/api/auth/me").then((me) => {
    if (!me.enabled || !me.authenticated) return;
    $("userChipName").textContent = me.user + (me.role === "viewer" ? t("userViewerSuffix") : "");
    $("userChip").hidden = false;
    const menu = $("userMenu");
    const closeMenu = () => { menu.hidden = true; $("userChipBtn").setAttribute("aria-expanded", "false"); };
    $("userChipBtn").addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      $("userChipBtn").setAttribute("aria-expanded", String(!menu.hidden));
    });
    document.addEventListener("click", (e) => { if (!$("userChip").contains(e.target)) closeMenu(); }, true);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) closeMenu(); });
    $("userMenuLogout").addEventListener("click", doLogout);
  }).catch(() => {});
}

document.addEventListener("DOMContentLoaded", async () => {
  initDialogLlamas();
  applyTheme();
  // The language table is its own module now (see i18n-data.js), so it has
  // to arrive before the first render — otherwise the page paints English
  // and only repaints on the next language change.
  await initLanguage();
  applyLanguage();
  setupLangSelect();
  // The hero tiles and the empty-tree line are built with t() into innerHTML,
  // so switching language has to rebuild them. It never did: the shared
  // handler ran the BOARD's renderer, which threw on this page before it got
  // anywhere near here.
  onLangChange(refresh);
  bindUserChip();
  bindFreshness();
  bindStagedButtons();
  fillVersionChipFromHealth();

  $("confirmCancel").addEventListener("click", () => settleAppConfirm(false));
  $("confirmDelete").addEventListener("click", () => { if (ui.pendingConfirm) ui.pendingConfirm(); });
  $("confirmOverlay").addEventListener("click", (e) => {
    if (e.target.id === "confirmOverlay") settleAppConfirm(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("confirmOverlay").hidden) settleAppConfirm(false);
  });

  // Models-dir editing: same contract as the board's MODELS bar — /api/config
  // replaces the WHOLE saved config, so merge over the current one (fetched
  // at save time; it is the only consumer of the heavy /api/state here).
  $("mdlPathEdit").addEventListener("click", () => {
    $("mdlPathInput").value = $("mdlPath").textContent.trim();
    $("mdlPathEditRow").hidden = false;
    $("mdlPathInput").focus();
  });
  $("mdlPathCancel").addEventListener("click", () => { $("mdlPathEditRow").hidden = true; });
  $("mdlPathInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("mdlPathSave").click(); }
    if (e.key === "Escape") { e.preventDefault(); $("mdlPathCancel").click(); }
  });
  $("mdlPathSave").addEventListener("click", async () => {
    const newPath = $("mdlPathInput").value.trim();
    if (!newPath) return;
    const btn = $("mdlPathSave");
    btn.disabled = true; btn.classList.add("btn-busy");
    try {
      const st = await api("/api/state");
      const config = Object.assign({}, st.config || {}, { LLAMA_MODELS_DIR: newPath });
      await api("/api/config", { method: "POST", body: JSON.stringify({ config, restart: false }) });
      $("mdlPathEditRow").hidden = true;
      toast(t("saved"));
      await refresh();
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false; btn.classList.remove("btn-busy");
    }
  });

  $("mdlTree").addEventListener("change", updatePicked);
  $("mdlSelectAll").addEventListener("click", () => {
    document.querySelectorAll("#mdlTree input[data-del-path]").forEach((el) => { el.checked = true; });
    updatePicked();
  });
  $("mdlDelete").addEventListener("click", async () => {
    const picked = [...document.querySelectorAll("#mdlTree input[data-del-path]:checked")];
    if (!picked.length) return;
    const bytes = picked.reduce((a, el) => a + Number(el.dataset.size || 0), 0);
    if (!(await appConfirm(t("gcConfirm", { count: String(picked.length) }) + ` (${fmtGb(bytes)})`,
                           { confirmLabel: t("gcDelete") }))) return;
    const btn = $("mdlDelete");
    btn.disabled = true; btn.classList.add("btn-busy");
    try {
      const res = await api("/api/models/gc", {
        method: "POST",
        body: JSON.stringify({ files: picked.map((el) => el.dataset.delPath) }),
      });
      toast(t("gcFreed", { gb: String(res.freedGb) }));
      await refresh();
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false; btn.classList.remove("btn-busy");
    }
  });

  refresh();
});
