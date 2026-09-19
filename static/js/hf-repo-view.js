// The repository on the right of /hf: its header, its files, what goes with
// the chosen quant, the model tree and everything else in the repository.
//
// Quants are grouped by bit depth, best first; the parts of a split quant
// (-00001-of-00002 …) are one row, because nobody wants half of a model. The
// low ones (2- and 3-bit and below) sit folded. The companions — projectors and
// MTP heads — are their own table, and the ones that go with the chosen quant
// are marked: every mmproj, and the MTP whose own quant, read off its file
// name, is nearest in rank. The server gives companion files no quant at all,
// which is why reading it off the list never worked: every MTP ranked the
// same and the first one always won.
//
// Rendering only: the page owns the state and the requests.
import { compareLocalFile, freshMark } from "./model-freshness.js";
import { escapeHtml } from "./utils.js";
import { HfFormat, hfT, hfText } from "./hf-text.js";

const QUANT_RANK = {
  IQ1_S: 0.5, IQ1_M: 0.6,
  IQ2_XXS: 1, IQ2_XS: 1.2, IQ2_S: 1.4, IQ2_M: 1.6,
  Q2_K: 2, Q2_K_S: 2, Q2_K_L: 2.1, Q2_K_XL: 2.2, Q2_K_XXL: 2.3,
  IQ3_XXS: 2.5, IQ3_XS: 2.6, IQ3_S: 2.8, IQ3_M: 3,
  Q3_K_S: 3, Q3_K_M: 3.3, Q3_K_L: 3.6, Q3_K_XL: 3.8, Q3_K_XXL: 3.9,
  IQ4_XS: 3.8, IQ4_NL: 4,
  Q4_0: 4, Q4_1: 4.1, Q4_K_S: 4.2, Q4_K_M: 4.5, Q4_K_L: 4.8, Q4_K_XL: 4.9, Q4_K_XXL: 4.95,
  Q5_0: 5, Q5_1: 5.1, Q5_K_S: 5, Q5_K_M: 5.3, Q5_K_L: 5.6, Q5_K_XL: 5.8, Q5_K_XXL: 5.9,
  Q6_K: 6, Q6_K_L: 6.3, Q6_K_XL: 6.5,
  Q8_0: 8, Q8_K_XL: 8.5,
  F16: 15, BF16: 16, F32: 32,
};
//: Quants that lose too much to be a first choice: shown dim and folded.
const LOW_QUANT_RE = /\b(IQ[123]_|Q[23]_)/i;
//: The quant inside a file name — the same pattern the server uses for models.
const QUANT_IN_NAME_RE = /\b(NVFP4|MXFP4|IQ\d_[A-Z0-9]+|Q\d[_-][A-Z0-9]+(?:[_-][A-Z0-9]+)*|BF16|F16|F32)\b/i;
//: Bit-depth groups, best first; at or below this one a group is "low".
const LOW_BITS = 3;
//: How bad a copy's standing is: a row of parts shows its worst part.
const FRESH_ORDER = { size: 3, date: 3, unknown: 2, same: 1 };

export class HfQuant {
  // Unknown quants rank above the "low" line: better shown than hidden.
  static rank(quant) {
    if (!quant) return 5;
    const q = String(quant).toUpperCase();
    if (QUANT_RANK[q] !== undefined) return QUANT_RANK[q];
    for (const [re, value] of [[/^IQ1_/, 0.6], [/^IQ2_/, 1.5], [/^IQ3_/, 2.8], [/^Q2_/, 2], [/^Q3_/, 3.5], [/^IQ4_/, 3.9]]) {
      if (re.test(q)) return value;
    }
    return 5;
  }

  static isLow(quant) {
    return !!quant && LOW_QUANT_RE.test(quant);
  }

  static bits(quant) {
    const q = String(quant || "").toUpperCase();
    if (q === "F32") return 32;
    if (q === "BF16" || q === "F16") return 16;
    if (q === "NVFP4" || q === "MXFP4") return 4;
    const match = q.match(/^I?Q(\d)/);
    return match ? Number(match[1]) : 0;
  }

  static fromName(name) {
    const match = QUANT_IN_NAME_RE.exec(String(name || ""));
    return match ? match[0].toUpperCase() : "";
  }
}

export class HfRepoView {
  // The repository's files, shaped for the page: quant rows grouped by bits,
  // companions, and model files with no quant at all.
  static shape(facts) {
    const files = facts.files || [];
    const rows = new Map();
    const loose = [];
    const companions = [];
    for (const f of files) {
      if (f.kind === "mmproj" || f.kind === "mtp" || f.kind === "vocab") { companions.push(f); continue; }
      if (!f.quant) { loose.push(f); continue; }
      if (!rows.has(f.quant)) rows.set(f.quant, { quant: f.quant, files: [] });
      rows.get(f.quant).files.push(f);
    }
    const quants = [...rows.values()].map((row) => {
      row.files.sort((a, b) => String(a.name).localeCompare(String(b.name)));
      row.size = row.files.reduce((sum, f) => sum + (Number(f.size) || 0), 0);
      row.rank = HfQuant.rank(row.quant);
      row.bits = HfQuant.bits(row.quant);
      row.low = HfQuant.isLow(row.quant);
      row.date = row.files.map((f) => f.date || "").sort().pop() || "";
      return row;
    }).sort((a, b) => (b.rank - a.rank) || (b.size - a.size));
    const groups = [];
    for (const row of quants) {
      const bits = row.low && row.bits > LOW_BITS ? LOW_BITS : row.bits;
      let group = groups.find((g) => g.bits === bits);
      if (!group) {
        // A quant whose depth cannot be read is not "low": better shown than folded.
        group = { bits, low: bits > 0 && bits <= LOW_BITS, rows: [] };
        groups.push(group);
      }
      group.rows.push(row);
    }
    groups.sort((a, b) => b.bits - a.bits);
    return { groups, loose, companions };
  }

  // What goes with the chosen quants: every mmproj, and the one MTP nearest in
  // rank to the best chosen quant. Nothing chosen, nothing marked.
  static recommended(facts, pickedQuants) {
    const files = facts.files || [];
    if (!pickedQuants.length) return new Set();
    const target = Math.max(...pickedQuants.map((q) => HfQuant.rank(q)));
    let best = Infinity;
    let bestRank = -Infinity;
    let mtp = null;
    for (const f of files) {
      if (f.kind !== "mtp") continue;
      const rank = HfQuant.rank(HfQuant.fromName(f.name));
      const diff = Math.abs(rank - target);
      // Equally near: the better head, since a draft that is too coarse costs
      // accepted tokens and one that is too fine only costs a few megabytes.
      if (diff < best || (diff === best && rank > bestRank)) {
        best = diff;
        bestRank = rank;
        mtp = f.path;
      }
    }
    const out = new Set(files.filter((f) => f.kind === "mmproj").map((f) => f.path));
    if (mtp) out.add(mtp);
    return out;
  }

  // How our copy of one file stands against HF: a hash result wins over the
  // size-and-date guess.
  static fresh(facts, file, verified) {
    const meta = (facts.localFiles || {})[file.name];
    const check = verified && verified[file.name];
    if (check) {
      const state = { same: "same", differs: "size", unknown: "unknown", unreadable: "unknown" }[check.state] || "unknown";
      return { state, detail: compareLocalFile(meta, file).detail, verified: check.state };
    }
    return compareLocalFile(meta, file);
  }

  static freshTitle(fresh) {
    const d = fresh.detail || {};
    const ours = `${hfT("freshOurs")}: ${d.localSize ? HfFormat.bytes(d.localSize) : "?"}${d.localDate ? ` · ${d.localDate}` : ""}`;
    const theirs = `${hfT("freshTheirs")}: ${d.remoteSize ? HfFormat.bytes(d.remoteSize) : "?"}${d.remoteDate ? ` · ${d.remoteDate}` : ""}`;
    let head;
    if (fresh.verified) {
      head = { same: hfT("verifiedSame"), differs: hfT("verifiedDiffers"), unknown: hfT("verifiedUnknown"), unreadable: hfT("verifiedUnreadable") }[fresh.verified] || hfT("verifiedUnknown");
    } else {
      head = { size: hfT("freshSize"), date: hfT("freshDate"), unknown: hfT("freshUnknown"), same: hfT("freshSame") }[fresh.state] || "";
    }
    return `${head}\n${ours}\n${theirs}`;
  }

  static freshWord(state) {
    if (state === "size" || state === "date") return hfT("freshWordDiffers");
    if (state === "unknown") return hfT("freshWordUnknown");
    return hfT("freshWordSame");
  }

  // The worst standing among the local parts of one row decides the row.
  static rowFresh(facts, row, verified) {
    let worst = null;
    for (const f of row.files) {
      if (!facts.localNames || !facts.localNames.has(f.name)) continue;
      const fresh = HfRepoView.fresh(facts, f, verified);
      if (!worst || (FRESH_ORDER[fresh.state] || 0) > (FRESH_ORDER[worst.state] || 0)) worst = fresh;
    }
    return worst;
  }

  // A copy in a library — a move carried it to a NAS share — held against
  // Hugging Face the same way as ours: by size and day. The first library's
  // copy is compared; the places name every library holding one.
  static libraryFresh(facts, file) {
    const copies = facts.inLibrary(file.name);
    if (!copies.length) return null;
    return { ...compareLocalFile(copies[0], file), places: copies.map((copy) => copy.store.name) };
  }

  // A row of parts in libraries: the worst part's standing, every library named.
  static rowLibraryFresh(facts, row) {
    let worst = null;
    const places = new Set();
    for (const f of row.files) {
      const fresh = HfRepoView.libraryFresh(facts, f);
      if (!fresh) continue;
      fresh.places.forEach((place) => places.add(place));
      if (!worst || (FRESH_ORDER[fresh.state] || 0) > (FRESH_ORDER[worst.state] || 0)) worst = fresh;
    }
    return worst ? { ...worst, places: [...places] } : null;
  }

  constructor({ bench, catalog }) {
    this.bench = bench;
    this.catalog = catalog;
  }

  // state: { picks: Set of paths, lowOpen: Set of bits, benchOpen, treeOpen,
  //          otherOpen, verify: { running, pct } | null, verified: {name: {state}},
  //          loading, error }
  html(facts, state) {
    if (!facts) return `<div class="hfp-empty">${escapeHtml(hfT("selectRepo"))}</div>`;
    const head = this.headHtml(facts, state);
    if (state.error) return `${head}<div class="hfp-error">${escapeHtml(state.error)}</div>`;
    if (!facts.files) return `${head}<div class="hfp-empty">${escapeHtml(hfT("loading"))}</div>`;
    // The full benchmark panel scrolls with the files: in the sticky header a
    // panel of five groups would cover the files it is meant to explain.
    const panel = state.benchOpen ? this.bench.panelHtml(facts.id) : "";
    return `${head}<div class="hfp-repo-body">${panel}${this.checkpointHtml(facts)}${this.filesHtml(facts, state)}${this.cardsHtml(facts, state)}</div>`;
  }

  headHtml(facts, state) {
    const fav = this.catalog.isFavorite(facts.id);
    const hasLocal = facts.localCount > 0;
    const verifyLabel = state.verify && state.verify.running
      ? (state.verify.pct ? hfT("verifyPct", { pct: state.verify.pct }) : hfT("verifyRunning")) : hfT("verifyBtn");
    const verify = hasLocal
      ? `<button type="button" class="hfp-btn" data-act="verify" data-t="hf-verify" title="${escapeHtml(hfT("verifyTitle"))}"${state.verify && state.verify.running ? " disabled" : ""}>${escapeHtml(verifyLabel)}</button>`
      : "";
    const meta = [`↓ ${facts.countLabel("downloads")}`, `♥ ${facts.countLabel("likes")}`];
    if (facts.paramsLabel) meta.push(`<b class="hfp-params">${escapeHtml(facts.paramsLabel)}</b>`);
    // Created, when the search said so; a favorite saved without it would
    // only repeat the "updated" date beside it.
    if (facts.record.createdAt) meta.push(`<span title="${escapeHtml(facts.record.createdAt)}">${escapeHtml(hfText.ago(facts.record.createdAt))}</span>`);
    if (facts.meta && facts.meta.lastModified) {
      meta.push(`<span title="${escapeHtml(facts.meta.lastModified)}">${escapeHtml(hfT("updatedAgo", { ago: hfText.ago(facts.meta.lastModified) }))}</span>`);
    }
    return `<header class="hfp-repo-head">`
      + `<div class="hfp-line"><h2 class="hfp-repo-name">${this.nameHtml(facts)}</h2>`
      + `<button type="button" class="hfp-star${fav ? " is-on" : ""}" data-act="star" data-t="hf-repo-star" aria-pressed="${fav}" title="${escapeHtml(hfT(fav ? "favRemove" : "favAdd"))}" aria-label="${escapeHtml(hfT(fav ? "favRemove" : "favAdd"))}">${fav ? "★" : "☆"}</button>`
      + `<span class="grow"></span>${verify}</div>`
      + `<div class="hfp-repo-sub"><span class="hfp-meta">${meta.join(`<span class="hfp-dot">·</span>`)}</span>${this.badgesHtml(facts)}</div>`
      + this.bench.stripHtml(facts.id, !!state.benchOpen)
      + `</header>`;
  }

  nameHtml(facts) {
    return facts.id.includes("/")
      ? `<span class="hfp-author">${escapeHtml(facts.author)}/</span>${escapeHtml(facts.model)}`
      : escapeHtml(facts.id);
  }

  badgesHtml(facts) {
    const out = [];
    if (facts.format) out.push(`<span class="hfp-badge is-fmt">${escapeHtml(facts.format)}</span>`);
    const labels = { it: "🤖 it", vision: "👁 vision", audio: "🎙 audio", mmproj: "📷 mmproj", mtp: "⚡ mtp", uncensored: "🔞 uncensored" };
    for (const cap of facts.capabilities()) out.push(`<span class="hfp-badge is-${cap}">${escapeHtml(labels[cap])}</span>`);
    return `<span class="hfp-badges">${out.join("")}</span>`;
  }

  // A safetensors checkpoint is one artifact: the whole folder downloads
  // together into <model>/<author>/<FORMAT>/.
  checkpointHtml(facts) {
    const st = facts.meta && facts.meta.safetensors;
    if (!st || !(st.files || []).length) return "";
    return `<div class="hfp-checkpoint" data-t="hf-checkpoint">`
      + `<span class="hfp-badge is-fmt">${escapeHtml(st.format)}</span>`
      + `<span class="hfp-checkpoint-name">${escapeHtml(hfT("stTitle", { n: st.files.length }))}</span>`
      + `<span class="hfp-num">${escapeHtml(HfFormat.bytes(st.totalSize))}</span><span class="grow"></span>`
      + `<button type="button" class="hfp-btn" data-act="checkpoint" data-t="hf-checkpoint-download" aria-label="${escapeHtml(`${hfT("a11yDownloadCheckpoint")}: ${st.format}`)}">⬇ ${escapeHtml(hfT("a11yStartDownload"))}</button></div>`;
  }

  filesHtml(facts, state) {
    const shape = HfRepoView.shape(facts);
    const st = facts.meta && facts.meta.safetensors;
    if (!shape.groups.length && !shape.loose.length && !shape.companions.length) {
      return st ? "" : `<div class="hfp-empty">${escapeHtml(hfT("noGguf"))}</div>`;
    }
    const picked = new Set(state.picks || []);
    const pickedQuants = shape.groups.flatMap((g) => g.rows).filter((row) => row.files.every((f) => picked.has(f.path))).map((row) => row.quant);
    const rec = HfRepoView.recommended(facts, pickedQuants);
    let body = "";
    for (const group of shape.groups) {
      const open = !group.low || (state.lowOpen && state.lowOpen.has(group.bits));
      if (group.low) {
        const names = group.rows.map((r) => r.quant).join(", ");
        body += `<tr class="hfp-bits is-low"><td colspan="7"><button type="button" class="hfp-fold" data-act="low" data-bits="${group.bits}" data-t="hf-low-toggle" data-t-id="${group.bits}" aria-expanded="${open}">`
          + `${open ? "▾" : "▸"} ${escapeHtml(hfT("bitsLow", { n: group.bits || "?", count: group.rows.length }))}`
          + `${open ? "" : ` <span class="hfp-fold-names">${escapeHtml(names)}</span>`}</button></td></tr>`;
      } else {
        body += `<tr class="hfp-bits"><td colspan="7">${escapeHtml(hfT("bitsGroup", { n: group.bits || "?" }))}</td></tr>`;
      }
      if (open) body += group.rows.map((row) => this.quantRowHtml(facts, row, picked, state)).join("");
    }
    if (shape.loose.length) {
      body += `<tr class="hfp-bits"><td colspan="7">${escapeHtml(hfT("noQuantGroup"))}</td></tr>`;
      body += shape.loose.map((f) => this.fileRowHtml(facts, f, picked, rec, state)).join("");
    }
    let html = shape.groups.length || shape.loose.length ? this.tableHtml(body) : "";
    if (shape.companions.length) {
      const note = pickedQuants.length ? hfT("companionsFor", { quant: pickedQuants.join(", ") }) : hfT("companionsPick");
      html += `<div class="hfp-sect"><span>${escapeHtml(hfT("companionsTitle"))}</span><em>· ${escapeHtml(note)}</em></div>`;
      html += this.tableHtml(shape.companions.map((f) => this.fileRowHtml(facts, f, picked, rec, state)).join(""), false);
      html += `<p class="hfp-note">${escapeHtml(hfT("companionsWhere"))}</p>`;
    }
    return html;
  }

  tableHtml(body, head = true) {
    const cols = `<colgroup><col class="c-check"><col class="c-quant"><col class="c-file"><col class="c-size"><col class="c-disk"><col class="c-date"><col class="c-del"></colgroup>`;
    const thead = head ? `<thead><tr><th></th><th>${escapeHtml(hfT("colQuant"))}</th><th>${escapeHtml(hfT("colFile"))}</th><th class="r">${escapeHtml(hfT("colSize"))}</th><th>${escapeHtml(hfT("colDisk"))}</th><th>${escapeHtml(hfT("colDate"))}</th><th></th></tr></thead>` : "";
    return `<table class="hfp-files">${cols}${thead}<tbody>${body}</tbody></table>`;
  }

  // Where we have the file and how it stands against HF: this disk first, then
  // 📚 for a library's copy — with the word only when this disk has none.
  diskCellHtml(fresh, library = null) {
    const cls = (f) => (f.state === "size" || f.state === "date" ? "is-differs" : `is-${f.state}`);
    const parts = [];
    if (fresh) {
      parts.push(`<span class="hfp-fresh ${cls(fresh)}${fresh.verified ? " is-verified" : ""}" title="${escapeHtml(HfRepoView.freshTitle(fresh))}">`
        + `${escapeHtml(freshMark(fresh))} ${escapeHtml(HfRepoView.freshWord(fresh.state))}</span>`);
    }
    if (library) {
      const title = `${hfT("inLibrary", { places: library.places.join(", ") })}\n${HfRepoView.freshTitle(library)}`;
      parts.push(`<span class="hfp-fresh hfp-in-lib ${cls(library)}" data-t="hf-file-in-library" title="${escapeHtml(title)}">`
        + `📚 ${escapeHtml(freshMark(library))}${fresh ? "" : ` ${escapeHtml(HfRepoView.freshWord(library.state))}`}</span>`);
    }
    return parts.join(" ");
  }

  quantRowHtml(facts, row, picked, state) {
    const on = row.files.every((f) => picked.has(f.path));
    const fresh = HfRepoView.rowFresh(facts, row, state.verified);
    const library = HfRepoView.rowLibraryFresh(facts, row);
    const local = row.files.filter((f) => facts.localNames && facts.localNames.has(f.name));
    const paths = JSON.stringify(row.files.map((f) => f.path));
    const cls = ["hfp-q", on ? "is-picked" : "", local.length ? "is-local" : library ? "is-library" : "", row.low ? "is-low" : ""].filter(Boolean).join(" ");
    const del = local.length
      ? `<button type="button" class="hfp-icon-btn" data-act="delete" data-names="${escapeHtml(JSON.stringify(local.map((f) => f.name)))}" data-t="hf-file-delete" data-t-id="${escapeHtml(local[0].name)}" title="${escapeHtml(hfT("deleteLocalTitle"))}" aria-label="${escapeHtml(hfT("deleteLocalTitle"))}">🗑</button>`
      : "";
    const parts = row.files.length > 1 ? ` <span class="hfp-parts">×${row.files.length}</span>` : "";
    return `<tr class="${cls}" data-t="hf-quant" data-t-id="${escapeHtml(row.quant)}">`
      + `<td><input type="checkbox" class="hfp-check" data-act="pick" data-paths="${escapeHtml(paths)}" data-t="hf-file-check" data-t-id="${escapeHtml(row.files[0].path)}"${on ? " checked" : ""} aria-label="${escapeHtml(`${hfT("selectForDownload")}: ${row.quant}`)}"></td>`
      + `<td class="q">${escapeHtml(row.quant)}${parts}</td>`
      + `<td class="fn" title="${escapeHtml(row.files.map((f) => f.path).join("\n"))}">${escapeHtml(row.files[0].name)}</td>`
      + `<td class="r">${escapeHtml(HfFormat.bytes(row.size))}</td>`
      + `<td>${this.diskCellHtml(fresh, library)}</td>`
      + `<td class="hfp-muted" title="${escapeHtml(row.date)}">${escapeHtml(hfText.ago(row.date))}</td>`
      + `<td>${del}</td></tr>`;
  }

  fileRowHtml(facts, f, picked, rec, state) {
    const on = picked.has(f.path);
    const local = facts.localNames && facts.localNames.has(f.name);
    const fresh = local ? HfRepoView.fresh(facts, f, state.verified) : null;
    const library = HfRepoView.libraryFresh(facts, f);
    const isRec = rec.has(f.path);
    const cls = ["hfp-q", on ? "is-picked" : "", local ? "is-local" : library ? "is-library" : "", isRec ? "is-rec" : ""].filter(Boolean).join(" ");
    const kind = f.kind === "mmproj" ? "📷 mmproj" : f.kind === "mtp" ? "⚡ mtp" : f.kind;
    const del = local
      ? `<button type="button" class="hfp-icon-btn" data-act="delete" data-names="${escapeHtml(JSON.stringify([f.name]))}" data-t="hf-file-delete" data-t-id="${escapeHtml(f.name)}" title="${escapeHtml(hfT("deleteLocalTitle"))}" aria-label="${escapeHtml(hfT("deleteLocalTitle"))}">🗑</button>`
      : "";
    return `<tr class="${cls}" data-t="hf-file" data-t-id="${escapeHtml(f.path)}">`
      + `<td><input type="checkbox" class="hfp-check" data-act="pick" data-paths="${escapeHtml(JSON.stringify([f.path]))}" data-t="hf-file-check" data-t-id="${escapeHtml(f.path)}"${on ? " checked" : ""} aria-label="${escapeHtml(`${hfT("selectForDownload")}: ${f.name}`)}"></td>`
      + `<td class="q">${f.kind === "model" ? escapeHtml(f.quant || "—") : `<span class="hfp-badge is-${escapeHtml(f.kind)}">${escapeHtml(kind)}</span>`}</td>`
      + `<td class="fn" title="${escapeHtml(f.path)}">${escapeHtml(f.name)}</td>`
      + `<td class="r">${escapeHtml(HfFormat.bytes(f.size))}</td>`
      + `<td>${this.diskCellHtml(fresh, library)}${isRec ? ` <span class="hfp-rec">${escapeHtml(hfT("recLabel"))}</span>` : ""}</td>`
      + `<td class="hfp-muted" title="${escapeHtml(f.date || "")}">${escapeHtml(hfText.ago(f.date))}</td>`
      + `<td>${del}</td></tr>`;
  }

  // The model tree and the other files: folded cards under the files, each a
  // button, so a redraw never loses what was open.
  cardsHtml(facts, state) {
    const tree = facts.tree;
    const cards = [];
    if (tree && ((tree.quantizations || []).length || (tree.siblings || []).length)) {
      const q = tree.quantizations || [];
      const s = tree.siblings || [];
      let body = "";
      if (state.treeOpen) {
        body = this.treeListHtml(hfT("treeQuants"), q) + this.treeListHtml(hfT("treeSiblings", { base: tree.base || "" }), s);
      }
      cards.push(`<div class="hfp-card"><button type="button" class="hfp-fold" data-act="tree" data-t="hf-tree-toggle" aria-expanded="${!!state.treeOpen}">`
        + `${state.treeOpen ? "▾" : "▸"} 🧬 ${escapeHtml(hfT("treeTitle"))} <span class="hfp-muted">· ${q.length + s.length}</span></button>${body}</div>`);
    }
    const others = (facts.meta && facts.meta.otherFiles) || [];
    if (others.length) {
      const bytes = others.reduce((sum, f) => sum + (Number(f.size) || 0), 0);
      const body = state.otherOpen
        ? `<div class="hfp-other">${others.map((f) => `<div class="hfp-other-row"><span>${escapeHtml(f.name)}</span><span class="hfp-num">${escapeHtml(HfFormat.bytes(f.size))}</span></div>`).join("")}</div>`
        : "";
      cards.push(`<div class="hfp-card is-grey"><button type="button" class="hfp-fold" data-act="other" data-t="hf-other-toggle" aria-expanded="${!!state.otherOpen}" aria-label="${escapeHtml(hfT("a11yOtherFiles"))}">`
        + `${state.otherOpen ? "▾" : "▸"} … ${escapeHtml(hfT("otherTitle"))} <span class="hfp-muted">· ${others.length} · ${escapeHtml(HfFormat.bytes(bytes))}</span></button>${body}</div>`);
    }
    return cards.length ? `<div class="hfp-cards">${cards.join("")}</div>` : "";
  }

  treeListHtml(title, items) {
    if (!items.length) return "";
    const rows = items.map((it) => `<button type="button" class="hfp-tree-row" data-act="open-repo" data-repo="${escapeHtml(it.id)}" data-t="hf-tree-repo" data-t-id="${escapeHtml(it.id)}" title="${escapeHtml(it.id)}">`
      + `<span class="hfp-badge is-fmt">${escapeHtml(it.format || "?")}</span><span class="hfp-tree-id">${escapeHtml(it.id)}</span>`
      + `<span class="hfp-muted">↓ ${escapeHtml(HfFormat.count(it.downloads))}${it.likes ? ` · ♥ ${escapeHtml(HfFormat.count(it.likes))}` : ""}</span></button>`).join("");
    return `<div class="hfp-tree"><div class="hfp-tree-title">${escapeHtml(title)} · ${items.length}</div>${rows}</div>`;
  }
}
