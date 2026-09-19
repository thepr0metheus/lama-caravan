// /models page: the models this controller can serve, wherever they lie. The
// side column chooses a place (drawn by model-stores.js) and a filter; the
// main column shows that place's summary and the tree of its files (model →
// author → quant → files) in columns — status, size here and in the library,
// age — with which cells use each file, downloads, moves (model-moves.js) and
// deletion of what nobody uses.
// Data: /api/models/unused (this disk), /api/model-stores/files (the
// libraries), /api/models/freshness, /api/hf/download/jobs; deletion:
// /api/models/gc (refuses referenced files server-side too).
import { appConfirm, settleAppConfirm } from "./dialogs.js";
import { initDialogLlamas } from "./dialog-llamas.js";
import { applyLanguage, applyTheme, initLanguage, onLangChange, setupLangSelect, t } from "./i18n.js";
import { mountMoves } from "./model-moves.js";
import { mountStores } from "./model-stores.js";
import { ui } from "./state.js";
import { $, api, escapeHtml, fmtGb, markPageState, toast, fillVersionChipFromHealth } from "./utils.js";

//: The controller's own models directory, as the stores registry names it.
const LOCAL_ID = "local";
//: The scope that shows every place at once.
const ALL = "all";

// The move tracker (model-moves.js), once mounted. Module-level because the
// tree and the selection bar both ask it: what a move says on each row, and
// what the move button says for the files picked now.
let moves = null;
// The stores the tree's ⇢ buttons were drawn for (see the stores' onChange).
let storesDrawn = "";
// The places panel. Module-level like `moves`, because every listing tells it
// what this disk now holds, and the tree asks it which place to show.
let stores = null;
// Whether the tree holds a drawn list (not "…", not an error): only then is
// there something worth keeping on screen while a refresh waits.
let treeDrawn = false;
// Refreshes started so far. Each one remembers its number, and an answer that
// lands after a newer refresh began is dropped instead of drawn.
let refreshes = 0;
// The last answers, kept so that another place, filter or name redraws the
// list without asking the server again.
let last = null;
// What the list shows besides the place: one filter of the side column (or
// none), and the words typed into the name box.
const view = { filter: "", query: "" };
// The branches that were open before a filter or a name narrowed the list.
// Narrowed, the list opens every branch it keeps — a match folded out of sight
// is a match not found — and clearing it gives back the branches that were
// open, instead of everything the narrowing opened.
let openBefore = null;

// The filters of the side column, in their order. What each keeps is decided
// in draw(), next to the data it reads.
const FILTERS = [
  { id: "moving", icon: "⇢", key: "mdlFilterMoving", tone: "mv" },
  { id: "unused", icon: "◌", key: "mdlFilterUnused", tone: "warn" },
  { id: "used", icon: "✓", key: "mdlFilterUsed", tone: "" },
  { id: "newer", icon: "⇪", key: "mdlFilterNewer", tone: "" },
];

// The picked rows, as the counter and the move panel both read them. A folder
// (a Hugging Face cache, a safetensors checkpoint) is one row here as it is one
// item everywhere else: deleted whole, moved whole. It says so in `kind`, and
// the move's confirm counts those apart — "one item" and "six thousand files"
// are the same move, and the one about to press it should know which.
function pickedFiles() {
  return [...document.querySelectorAll("#mdlTree input[data-del-path]:checked")].map((el) => ({
    path: el.dataset.delPath, size: Number(el.dataset.size || 0), kind: el.dataset.kind || "" }));
}

function updatePicked() {
  const picked = pickedFiles();
  const bytes = picked.reduce((a, f) => a + f.size, 0);
  $("mdlPicked").textContent = picked.length ? `${picked.length} · ${fmtGb(bytes)}` : "";
  $("mdlDelete").disabled = !picked.length;
  // The bar floats over the list only while something is picked: two
  // disabled buttons hovering over every row would be in the way of reading.
  if ($("mdlFoot")) $("mdlFoot").hidden = !picked.length;
  if (moves) moves.syncButton();
}

async function refresh() {
  const tree = $("mdlTree");
  const mine = ++refreshes;
  // The tree stays on screen while the new answer travels. It used to be wiped
  // to "…" before the requests went out, and a move redraws the tree every
  // time a file arrives — while the library is being measured over a network
  // busy with that very copy. Seen live: "…" where seventy models had been,
  // for as long as the NAS took to answer. "…" is for the first load only,
  // when there is nothing to keep.
  if (!treeDrawn) paint(tree, `<p class="muted">…</p>`);
  let data, fresh = null, jobs = null, libs = null;
  try {
    // Freshness comes from the SAVED watcher report, not a trip to HF on
    // every redraw: 75 files across 20 repositories would be 20 outbound
    // requests for a page that's opened to look at the disk.
    [data, fresh, jobs, libs] = await Promise.all([
      api("/api/models/unused"),
      api("/api/models/freshness").catch(() => null),
      // Jobs live on the SERVER. So progress survives a page reload, is
      // visible in another tab, and shows downloads started from /hf.
      api("/api/hf/download/jobs").catch(() => null),
      // What the libraries hold: a model moved to the NAS is still one of the
      // caravan's models, and the tree is where models are looked for.
      api("/api/model-stores/files").catch(() => null),
    ]);
  } catch (err) {
    if (mine !== refreshes) return;
    paint(tree, `<p class="muted">${escapeHtml(String(err.message || err))}</p>`);
    treeDrawn = false;
    last = null;
    markPageState("error", err.message);
    return;
  }
  // A later refresh started while this one waited: its answer is newer, and
  // this one must not paint an older tree over it when it lands second.
  if (mine !== refreshes) return;
  if (!data.ok) {
    paint(tree, `<p class="muted">${escapeHtml(data.error || "models dir not found")}</p>`);
    treeDrawn = false;
    last = null;
    markPageState("error", data.error || "models dir not found");
    return;
  }
  last = { data, fresh, jobs, libs };
  const dlByPath = draw();
  // Polling starts ONLY when there's something to show, and stops on its own
  // once no downloads are left: a timer ticking over an empty page is work
  // with nothing to do.
  if (dlByPath.size) pollDownloads();
}

// Draws the list from the last answers, for the place, filter and name chosen
// now. Returns the downloads it drew, by path.
function draw() {
  if (!last) return new Map();
  const tree = $("mdlTree");
  const { data, fresh, jobs, libs } = last;
  const words = view.query.trim().toLowerCase();
  const narrowed = !!(view.filter || words);
  // What lives in the markup is read at the moment it is replaced — AFTER the
  // answer, not before the request: a branch opened or a box ticked while the
  // data travelled survives the redraw too. Open branches, because the whole
  // tree is rebuilt and a pressed button deep inside it would otherwise
  // collapse everything; the selection, because a move redraws on every file
  // that arrives and a pick wiped each time would be picked again mid-thought.
  const openBranches = branchesToKeep(narrowed);
  const pickedBefore = new Set(pickedFiles().map((f) => f.path));
  const wasScrolled = typeof window !== "undefined" ? window.scrollY || 0 : 0;
  const files = data.files || [];
  const totalBytes = files.reduce((a, f) => a + f.sizeBytes, 0);

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
  // What the libraries hold, path → its copies. A file only a library holds
  // takes its own place in the tree — the path is the same as it was here,
  // since a move keeps it.
  const libByPath = libraryFilesByPath(libs);
  const localPaths = new Set(files.map((f) => f.path));
  const libOnly = [...libByPath.entries()].filter(([path]) => !localPaths.has(path))
    .map(([path, copies]) => ({ path, sizeBytes: copies[0].size, ageDays: copies[0].ageDays,
      kind: copies[0].kind, libraryOnly: true, copies }));

  // What this disk holds goes to its place in the side column — the same
  // count the tree below is made of, said once — with the model families of
  // every place: a family is a top folder of the tree.
  const family = (path) => (path.includes("/") ? path.split("/")[0] : "(root)");
  const families = new Map([[ALL, new Set()], [LOCAL_ID, new Set()]]);
  const countFamily = (scope, path) => {
    if (!families.has(scope)) families.set(scope, new Set());
    families.get(scope).add(family(path));
  };
  for (const f of files) { countFamily(ALL, f.path); countFamily(LOCAL_ID, f.path); }
  for (const [path, copies] of libByPath) {
    countFamily(ALL, path);
    for (const c of copies) countFamily(c.id, path);
  }
  if (stores) {
    stores.holds({ files: files.length, size: totalBytes,
      families: Object.fromEntries([...families].map(([scope, names]) => [scope, names.size])) });
  }

  // The place the list shows: every place, this disk, or one library. A file
  // both here and in a library belongs to both.
  const scope = (stores && stores.scope) || ALL;
  const place = scope === ALL ? null : ((stores && stores.stores) || []).find((s) => s.id === scope) || null;
  const libScope = place && !place.builtin ? place.id : "";
  const inPlace = (f) => (!place ? true : place.builtin ? !f.libraryOnly
    : (libByPath.get(f.path) || []).some((c) => c.id === libScope));
  // Named by a cell and read by one are different facts, and they decide
  // different controls. The checkbox below (delete, and the server refuses it
  // too) goes by NAMED: removing a stopped cell's model breaks it silently. A
  // move only needs that nobody is READING it — a stopped cell's model travels,
  // and its start brings it back. A folder (a cache, a checkpoint) moves whole.
  const readBy = (f) => (f.readBy || []).join(", ");
  const movableFile = (f) => !f.libraryOnly && !readBy(f) && !(moves && moves.onWay(f.path));
  // What each filter keeps. "Unused" and "newer" are facts of this disk: a
  // file only a library holds is used by nobody here and compared with
  // nothing.
  const keeps = {
    moving: (f) => !!(moves && moves.onWay(f.path)),
    unused: (f) => !f.libraryOnly && !f.referenced,
    used: (f) => !!f.referenced,
    newer: (f) => !f.libraryOnly && differsAt(f.path) === 1,
  };
  const inView = [...files, ...libOnly].filter(inPlace);
  // The filters count what they would keep in THIS place — the number beside
  // a filter is the length of the list it gives.
  const counts = Object.fromEntries(FILTERS.map(({ id }) => {
    const kept = inView.filter(keeps[id]);
    return [id, { n: kept.length, size: kept.reduce((a, f) => a + f.sizeBytes, 0) }];
  }));
  drawFilters(counts);
  // The one number the stores cannot say: how much of this place is lying
  // unused. It is the reason the page has a Delete button, so it stands next
  // to the button that selects exactly those files — and it is the filter's
  // own count, in the filter's own words: the line used to print the
  // server's rounding ("159.9 GB") beside the filter's "160 GB".
  const idle = $("mdlUnused");
  const unused = counts.unused;
  idle.textContent = unused.n ? t("mdlUnusedLine", { n: String(unused.n), size: fmtGb(unused.size) })
    : place && !place.builtin ? "" : t("mdlUnusedNone");
  idle.classList.toggle("warn", !!unused.n);
  // A button that would pick nothing is not offered.
  $("mdlSelectAll").hidden = !unused.n;
  const named = (f) => !words || f.path.toLowerCase().includes(words);
  const shown = inView.filter((f) => (!keeps[view.filter] || keeps[view.filter](f)) && named(f));

  // What a row weighs in each column: this disk's bytes, and the library's —
  // every library's under "All models", the chosen one's under a library.
  const libSize = (f) => (libByPath.get(f.path) || []).filter((c) => !libScope || c.id === libScope)
    .reduce((a, c) => a + c.size, 0);
  const hereSize = (f) => (f.libraryOnly ? 0 : f.sizeBytes);
  const grouped = new Map();
  const node = (leaf) => (leaf ? { bytes: 0, libBytes: 0, minAge: Infinity, differs: 0, movable: 0, files: [] }
    : { bytes: 0, libBytes: 0, minAge: Infinity, differs: 0, movable: 0, children: new Map() });
  shown.forEach((f) => {
    const segs = f.path.split("/");
    const model = segs.length > 1 ? segs[0] : "(root)";
    const author = segs.length > 2 ? segs[1] : "·";
    const quant = segs.length > 3 ? segs[2] : "·";
    // Freshness rolls up the tree the same way bytes and age do: a file's
    // icon isn't visible until its branch is opened — and a collapsed list
    // exists for exactly that reason: so you don't have to open everything
    // just to find ten files.
    const d = f.libraryOnly ? 0 : differsAt(f.path);
    // What a branch's ⇢ would carry: the files a checkbox is offered for.
    const movable = movableFile(f) ? 1 : 0;
    const add = (n) => {
      n.bytes += hereSize(f);
      n.libBytes += libSize(f);
      n.minAge = Math.min(n.minAge, f.ageDays);
      n.differs += d;
      n.movable += movable;
    };
    if (!grouped.has(model)) grouped.set(model, node(false));
    const l1 = grouped.get(model); add(l1);
    if (!l1.children.has(author)) l1.children.set(author, node(false));
    const l2 = l1.children.get(author); add(l2);
    if (!l2.children.has(quant)) l2.children.set(quant, node(true));
    const l3 = l2.children.get(quant); add(l3);
    l3.files.push(f);
  });
  // Every size stands under its column's header, and the header says where
  // those bytes are: 🏠 this disk, 📚 the library. Under "All models" both
  // columns; a place of its own has one. A dash is "none there" — "0.00 GB"
  // beside a model would read as an empty folder.
  const two = !place;
  const dash = `<span class="mdl-dim">—</span>`;
  const sizes = (here, lib) => (two
    ? `<span class="mdl-c-size here">${here ? fmtGb(here) : dash}</span><span class="mdl-c-size lib">${lib ? fmtGb(lib) : dash}</span>`
    : `<span class="mdl-c-size ${libScope ? "lib" : "here"}">${fmtGb(libScope ? lib : here)}</span>`);
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
  // What a move says about a file (model-moves.js) is said on the file's own
  // row: on its way — a bar with the pass, the speed and Stop, instead of a
  // checkbox and the download buttons; left here by a finished move — why;
  // free to move — ⇢, at the row's right edge.
  const fileRow = (f, depth) => {
    const name = f.path.split("/").pop();
    const usedBy = (f.referencedBy || []).join(", ");
    const way = moves ? moves.onWay(f.path) : null;
    // A cell that has the file open says so plainly; one that only names it is
    // stopped, and the chip says the model may still travel.
    const used = f.referenced
      ? `<span class="mdl-used${readBy(f) ? "" : " parked"}"`
        + ` title="${escapeHtml(readBy(f) ? usedBy : t("mdlUsedStopped", { names: usedBy }))}">`
        + `✓ ${escapeHtml(usedBy || "used")}</span>`
      : "";
    // data-t-id is the model's PATH, not its display name: the name is just
    // the last segment and two quantisations of the same model share it, so a
    // test selecting by name would pick whichever came first. The path is
    // what the delete call sends.
    // aria-label is the path, the same string data-t-id carries. Without it a
    // screen reader reads fifty-nine identical "checkbox, not checked", and
    // the control after the list is Delete selected — so a keyboard user could
    // pick files for deletion with no way to hear which ones. The name exists
    // already; it was simply not exposed.
    const box = f.referenced || way
      ? `<span class="mdl-nobox"></span>`
      : `<input type="checkbox" aria-label="${escapeHtml(f.path)}" data-t="models-model-select" data-t-id="${escapeHtml(f.path)}"`
        + ` data-del-path="${escapeHtml(f.path)}" data-size="${f.sizeBytes}"${f.kind ? ` data-kind="${escapeHtml(f.kind)}"` : ""}`
        + `${pickedBefore.has(f.path) ? " checked" : ""}>`;
    const go = moves && movableFile(f) ? moves.openHtml("file", f.path, { size: f.sizeBytes, kind: f.kind }) : "";
    return `<div class="mdl-file mdl-row" style="--lvl:${depth}">`
      + `<span class="mdl-c-name"><span class="tw"></span>${box}${folderChip(f)}<code title="${escapeHtml(f.path)}">${escapeHtml(name)}</code></span>`
      + `<span class="mdl-c-status">${used}${alsoInLibrary(f.path)}${freshChip(f.path)}`
      + `${way ? moves.rowHtml(f.path) : updateBtns(f.path)}${way || !moves ? "" : moves.stayedHtml(f.path)}</span>`
      + `${sizes(f.sizeBytes, libSize(f))}<span class="mdl-c-age">${f.ageDays}d</span><span class="mdl-c-go">${go}</span></div>`;
  };
  // A row that is a whole folder says so. Without this a whisper cache reads
  // as one more file, and "move 1 item" would quietly mean six thousand.
  const folderChip = (f) => (f.kind
    ? `<span class="mdl-kind" data-t="models-folder-item" data-t-id="${escapeHtml(f.path)}"`
      + ` title="${escapeHtml(t("mdlFolderItem", { kind: f.kind }))}">📁</span>`
    : "");
  // A file on this disk that a library holds too: the icon, and the library
  // named in its tooltip.
  const alsoInLibrary = (path) => {
    const copies = libByPath.get(path);
    return copies ? `<span class="mdl-lib" title="${escapeHtml(t("mdlAlsoInLibrary", { name: copies.map((c) => c.name).join(", ") }))}">📚</span>` : "";
  };
  // A file only a library holds: where it is instead of a checkbox — it is not
  // on this disk to delete. It can still move: ⇢ sends it back here or on to
  // another library, and while it travels its row carries the same bar.
  const libRow = (f, depth) => {
    const where = f.copies.map((c) => c.name).join(", ");
    const way = moves ? moves.onWay(f.path) : null;
    const go = moves && !way ? moves.openHtml("file", f.path, { size: f.sizeBytes, from: f.copies[0].id, kind: f.kind }) : "";
    return `<div class="mdl-file mdl-file-lib mdl-row" data-t="models-library-file" data-t-id="${escapeHtml(f.path)}" style="--lvl:${depth}">`
      + `<span class="mdl-c-name"><span class="tw"></span><span class="mdl-nobox"></span>${folderChip(f)}`
      + `<code title="${escapeHtml(f.path)}">${escapeHtml(f.path.split("/").pop())}</code></span>`
      + `<span class="mdl-c-status"><span class="mdl-lib" title="${escapeHtml(t("mdlInLibrary", { name: where }))}">📚 ${escapeHtml(where)}</span>`
      + `${way ? moves.rowHtml(f.path) : ""}</span>`
      + `${sizes(0, libSize(f))}<span class="mdl-c-age">${f.ageDays}d</span><span class="mdl-c-go">${go}</span></div>`;
  };
  const age = (days) => (days === Infinity ? "" : `${days}d`);
  // Three nesting levels — model, author, quantisation — all rendered by this
  // one helper, so they share a hook and are told apart by data-t-id. The
  // <summary> carries its own hook because that is the element you click to
  // expand: `details > summary`, direct child, since a nested details' summary
  // would otherwise match too.
  // The count on a collapsed row: "how many inside need attention". Zero
  // means empty, not "0": the page shows what needs a look, not a tally.
  const groupChip = (n) => (n.differs
    ? `<span class="mdl-fresh newer" title="${escapeHtml(t("mdlFreshGroup", { n: String(n.differs) }))}">⇪ ${n.differs}</span>`
    : "");
  // Open branches survive a redraw (captured above). The whole tree is rebuilt
  // from scratch after every action, and without this pressing "update" deep
  // inside it collapsed everything — taking down the very progress bar the
  // operator had started it to watch. The key is the CHAIN of labels from the
  // root: one label ("bartowski", "Q8_0") repeats across different branches,
  // and keying on it alone would open someone else's branches too. A narrowed
  // list opens every branch it keeps (see branchesToKeep).
  // A branch whose files travel says how far they are (model-moves.js), and a
  // branch with files that can move offers ⇢ for all of them at once.
  // The way from a branch to Hugging Face. An author branch is a repository —
  // <model>/<author>/<quant> is how /hf lays its downloads out — so it opens
  // that one; a model branch searches its name, which finds every author's
  // build. A folder not laid out that way ("(root)", "·", a cache folder) has none.
  const HF_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
  const hfLink = (trail, depth) => {
    const [model, author] = trail.split("/");
    if (depth > 1 || !HF_ID.test(model) || model.startsWith("models--")) return "";
    if (depth === 1 && (!HF_ID.test(author || "") || author === "default")) return "";
    const query = depth === 1 ? `${author}/${model}` : model;
    const title = t(depth === 1 ? "mdlHfRepo" : "mdlHfSearch");
    return `<a class="mdl-tree-hf" href="/hf?q=${encodeURIComponent(query)}" data-t="models-hf-open" data-t-id="${escapeHtml(query)}"`
      + ` title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">🤗</a>`;
  };
  const lvl = (label, n, inner, trail, depth) => `
    <details data-t="models-tree-group" data-t-id="${escapeHtml(label)}"${n.differs ? " data-differs=\"1\"" : ""}`
      + ` data-branch="${escapeHtml(trail)}"${narrowed || openBranches.has(trail) ? " open" : ""}>
      <summary class="mdl-row" data-t="models-tree-group-toggle" data-t-id="${escapeHtml(label)}" style="--lvl:${depth}">`
      + `<span class="mdl-c-name"><span class="tw"></span><span class="mdl-name">${escapeHtml(label)}</span>${hfLink(trail, depth)}</span>`
      + `<span class="mdl-c-status">${groupChip(n)}${moves ? moves.branchHtml(trail) : ""}</span>`
      + `${sizes(n.bytes, n.libBytes)}<span class="mdl-c-age">${age(n.minAge)}</span>`
      + `<span class="mdl-c-go">${moves && n.movable ? moves.openHtml("branch", trail) : ""}</span></summary>
      <div class="mdl-lvl">${inner}</div>
    </details>`;
  // Every level sorts largest-first (authors, quants and files too — not just
  // the top-level repos), so the biggest disk eaters always float up. Under
  // "All models" what this disk holds sorts first and branches living only in
  // a library follow; a library sorts by what it holds.
  const weight = (n) => (libScope ? n.libBytes : n.bytes);
  const bySize = (a, b) => (weight(b[1]) - weight(a[1])) || (b[1].libBytes - a[1].libBytes);
  const fileWeight = (f) => (libScope ? libSize(f) : f.sizeBytes);
  // A library that names only part of its files says how many it left out,
  // instead of passing the list off as whole.
  const libMore = ((libs && libs.libraries) || []).filter((l) => l.more > 0 && (!place || l.id === libScope))
    .map((l) => `<p class="muted">📚 ${escapeHtml(l.name || l.id)}: ${escapeHtml(t("storeMore", { n: String(l.more) }))}</p>`).join("");
  storesDrawn = moves ? moves.storesKey() : "";
  const rows = [...grouped.entries()]
    .sort(bySize)
    .map(([model, l1]) => lvl(model, l1,
      [...l1.children.entries()].sort(bySize).map(([author, l2]) => lvl(author, l2,
        [...l2.children.entries()].sort(bySize).map(([quant, l3]) =>
          lvl(quant, l3, l3.files.slice().sort((a, b) => fileWeight(b) - fileWeight(a))
            .map((f) => (f.libraryOnly ? libRow(f, 3) : fileRow(f, 3))).join(""),
          `${model}/${author}/${quant}`, 2)).join(""), `${model}/${author}`, 1)).join(""), model, 0))
    .join("");
  const head = `<div class="mdl-row mdl-head" data-t="models-tree-head"><span>${escapeHtml(t("mdlColModel"))}</span>`
    + `<span>${escapeHtml(t("mdlColStatus"))}</span>`
    + (two
      ? `<span class="mdl-c-size">🏠 ${escapeHtml(t("mdlColHere"))}</span><span class="mdl-c-size">📚 ${escapeHtml(t("mdlColLibrary"))}</span>`
      : `<span class="mdl-c-size">${libScope ? "📚" : "🏠"} ${escapeHtml(t("mdlColSize"))}</span>`)
    + `<span class="mdl-c-age">${escapeHtml(t("mdlColAge"))}</span><span></span></div>`;
  tree.classList.toggle("one", !two);
  paint(tree, rows ? head + rows + libMore : (libMore || emptyList(narrowed, place)));
  treeDrawn = true;
  renderFreshnessRow(fresh, files.length, dlByPath);
  updatePicked();
  if (wasScrolled && typeof window.scrollTo === "function") window.scrollTo(0, wasScrolled);
  markPageState("ready");
  dlDrawn = dlSignature(dlByPath);
  return dlByPath;
}

// Puts markup on screen unless the same markup is already there. The page
// draws itself again after every answer, and markup replaced under a pressed
// mouse button swallows the click: the press lands on one element, the
// release on its copy. What the element last got is kept on the element, so a
// replaced element is always drawn.
function paint(el, html) {
  if (el.__painted === html) return;
  el.innerHTML = html;
  el.__painted = html;
}

// An empty list says why it is empty: a filter or a name that keeps nothing
// (with the way back), a place that holds nothing, or a disk with nothing on
// it at all.
function emptyList(narrowed, place) {
  if (narrowed) {
    return `<div class="mdl-empty" data-t="models-filter-empty"><span>${escapeHtml(t("mdlFilterEmpty"))}</span>`
      + `<button class="mini-link" type="button" data-show-all data-t="models-filter-clear">${escapeHtml(t("mdlShowAll"))}</button></div>`;
  }
  return `<p class="muted mdl-empty">${escapeHtml(t(place ? "storeEmpty" : "gcNoUnused"))}</p>`;
}

// The open branches the next drawing keeps. Narrowed, every kept branch opens
// anyway — so the markup no longer says which ones the operator had opened —
// and the ones open before the narrowing are put aside to come back when it is
// cleared.
function branchesToKeep(narrowed) {
  const now = treeOpenBranches();
  if (narrowed) {
    if (openBefore === null) openBefore = now;
    return now;
  }
  if (openBefore === null) return now;
  const back = openBefore;
  openBefore = null;
  return back;
}

// The filters with what each would keep here. A filter that keeps nothing is
// off — unless it is the one on, which must stay reachable to be cleared.
function drawFilters(counts) {
  const box = $("mdlFilters");
  if (!box) return;
  paint(box, FILTERS.map(({ id, icon, key, tone }) => {
    const on = view.filter === id;
    const { n, size } = counts[id] || { n: 0, size: 0 };
    const count = !n ? "" : id === "unused" ? `${n} · ${fmtGb(size)}` : String(n);
    return `<button class="mdl-filter" type="button" data-filter="${id}" data-t="models-filter" data-t-id="${id}"`
      + ` aria-pressed="${on}"${n || on ? "" : " disabled"}><span aria-hidden="true">${icon}</span>`
      + `<span>${escapeHtml(t(key))}</span><span class="c${n && tone ? ` ${tone}` : ""}">${escapeHtml(count)}</span></button>`;
  }).join(""));
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

// What the libraries hold as path → [{id, name, size, ageDays, kind}]. The key
// is the path relative to the store's root — the same as on this disk. `kind`
// is set for a model folder (a whisper cache, a checkpoint) and empty for a
// file, the same word the models disk uses for it.
function libraryFilesByPath(libs) {
  const out = new Map();
  for (const lib of (libs && libs.libraries) || []) {
    for (const f of lib.files || []) {
      if (!out.has(f.path)) out.set(f.path, []);
      out.get(f.path).push({ id: lib.id, name: lib.name || lib.id, size: f.size || 0, ageDays: f.ageDays || 0, kind: f.kind || "" });
    }
  }
  return out;
}

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

// Both buttons write over the file a cell runs from — "fetch new" with the
// build on Hugging Face, "revert" with the kept one — so each asks first, and
// the question says what is lost. They used to act on the click: a mis-click
// on "fetch new" with no previous build kept replaced a working model for good.
async function stagedAction(endpoint, file, btn, busyKey, question) {
  if (!(await appConfirm(question.text, question.opts))) return;
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

// The report's row for a file on this disk, by its path.
function freshRow(fresh, path) {
  for (const repo of Object.values((fresh && fresh.repos) || {})) {
    if (repo.files && repo.files[path]) return repo.files[path];
  }
  return null;
}

// Before "fetch new": which file, how big the build that replaces it is, and
// whether the build on disk now survives — kept as the previous one only when
// the watch setting says so.
function fetchQuestion(path) {
  const fresh = (last && last.fresh) || null;
  const row = freshRow(fresh, path) || {};
  const kept = !!(fresh && fresh.watch && fresh.watch.keepPrev);
  return {
    text: t("mdlStagedGetConfirm", { name: path.split("/").pop(), size: fmtGb(row.remoteSize || 0) })
      + `\n\n${t(kept ? "mdlStagedGetKept" : "mdlStagedGetLost")}`,
    opts: { title: t("mdlStagedGetTitle"), confirmLabel: t("mdlStagedGet"), danger: !kept, scene: "change" },
  };
}

// Before "revert": the newer file is deleted — it can always be fetched again.
function revertQuestion(path) {
  return {
    text: t("mdlStagedPrevConfirm", { name: path.split("/").pop() }),
    opts: { title: t("mdlStagedPrevTitle"), confirmLabel: t("mdlStagedPrev"), danger: true, scene: "change" },
  };
}

function bindStagedButtons() {
  const tree = $("mdlTree");
  if (!tree || tree.__stagedBound) return;
  tree.__stagedBound = true;
  // Delegation: the tree is rebuilt from scratch after every action, and
  // handlers bound to the buttons themselves would be gone along with them.
  tree.addEventListener("click", (e) => {
    const get = e.target.closest?.("[data-staged-get]");
    if (get) return stagedAction("/api/models/staged/download", get.dataset.stagedGet, get, "mdlStagedStarting", fetchQuestion(get.dataset.stagedGet));
    const prev = e.target.closest?.("[data-staged-prev]");
    if (prev) return stagedAction("/api/models/staged/revert", prev.dataset.stagedPrev, prev, "mdlStagedApplying", revertQuestion(prev.dataset.stagedPrev));
    if (e.target.closest?.("[data-show-all]")) showAll();
    return undefined;
  });
}

// Clears what narrows the list — the filter and the name — and keeps the place.
function showAll() {
  view.filter = "";
  view.query = "";
  if ($("mdlSearch")) $("mdlSearch").value = "";
  draw();
}

// The side column's filters and the name box redraw the list from what the
// page already has: choosing what to look at asks the server nothing.
function bindListControls() {
  const filters = $("mdlFilters");
  if (filters) {
    filters.addEventListener("click", (e) => {
      const btn = e.target.closest?.("[data-filter]");
      if (!btn || btn.disabled) return;
      // The filter on is pressed again to take it off.
      view.filter = view.filter === btn.dataset.filter ? "" : btn.dataset.filter;
      draw();
    });
  }
  const search = $("mdlSearch");
  if (search) {
    search.addEventListener("input", () => { view.query = search.value; draw(); });
    search.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !search.value) return;
      e.preventDefault();
      search.value = "";
      view.query = "";
      draw();
    });
  }
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
  // A page opens on the whole list: no filter, no name, nothing put aside.
  view.filter = "";
  view.query = "";
  openBefore = null;
  initDialogLlamas();
  applyTheme();
  // The language table is its own module now (see i18n-data.js), so it has
  // to arrive before the first render — otherwise the page paints English
  // and only repaints on the next language change.
  await initLanguage();
  applyLanguage();
  setupLangSelect();
  // The places panel and the move tracker are modules with their own data;
  // the page gives each its place and connects them: the move button and every
  // ⇢ need the libraries the panel measured, and a file that arrived changes
  // both the tree and the places' numbers. `stores` exists before the tracker
  // mounts, because the tracker asks for it right away.
  moves = mountMoves({
    tree: $("mdlTree"), summary: $("mdlMovesSum"), button: $("mdlMove"), select: $("mdlMoveTo"), picked: pickedFiles,
    stores: () => (stores ? stores.stores : null),
    onChange: () => { refresh(); if (stores) stores.refresh(true); },
    // The line "⇢ N files on their way" shows exactly those files: every
    // place, the filter that keeps them, no name — then the tracker brings the
    // first bar into view.
    onReveal: () => {
      view.filter = "moving";
      view.query = "";
      if ($("mdlSearch")) $("mdlSearch").value = "";
      if (stores && stores.scope && stores.scope !== ALL) stores.choose(ALL);
      else draw();
    },
  });
  // A new measurement re-labels the button; and when the places a ⇢ can send
  // to have changed — the first answer, one added, one gone — the tree is
  // redrawn, or its ⇢ buttons would offer the old ones.
  stores = mountStores($("mdlStores"), {
    summary: $("mdlSummary"),
    onChange: () => {
      if (!moves) return;
      moves.syncButton();
      if (moves.storesKey() !== storesDrawn) refresh();
    },
    // Another place chosen: the list shows it, from what the page already has.
    onScope: () => draw(),
    // Where the models directory is: the panel owns the row and the pencil,
    // the page owns what saving one means. Same contract as the board's MODELS
    // bar — /api/config replaces the WHOLE saved config, so the new path is
    // merged over the current one, fetched at save time.
    onSavePath: async (newPath) => {
      const st = await api("/api/state");
      const config = Object.assign({}, st.config || {}, { LLAMA_MODELS_DIR: newPath });
      await api("/api/config", { method: "POST", body: JSON.stringify({ config, restart: false }) });
      toast(t("saved"));
      await refresh();
    },
  });
  // The tree, the filters and the places are built with t() into innerHTML,
  // so switching language rebuilds them.
  onLangChange(() => { refresh(); if (stores) stores.render(); if (moves) moves.render(); });
  bindUserChip();
  bindFreshness();
  bindStagedButtons();
  bindListControls();
  fillVersionChipFromHealth();

  $("confirmCancel").addEventListener("click", () => settleAppConfirm(false));
  $("confirmDelete").addEventListener("click", () => { if (ui.pendingConfirm) ui.pendingConfirm(); });
  $("confirmOverlay").addEventListener("click", (e) => {
    if (e.target.id === "confirmOverlay") settleAppConfirm(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("confirmOverlay").hidden) settleAppConfirm(false);
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
