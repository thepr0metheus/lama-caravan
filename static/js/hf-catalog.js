// What the /hf page knows about repositories, and which of them it shows.
//
// HfRepoFacts is one repository: the search record, its file list, what of it
// is on disk, its benchmarks — and every fact derived from those (size, format,
// capabilities, scores), computed here and nowhere else. HfCatalog holds the
// search results and the favorites, the filters and the order, and answers
// "what does this tab show".
//
// No DOM here: the page renders what these classes answer, and the snapshot in
// scripts/test_js_hf_catalog.py pins the answers.
import { HfFormat, hfT } from "./hf-text.js";

//: The number before "B" in a repository name, as a whole token: 27B, 0.6B.
const PARAMS_RE = /(?:^|[-_])(\d+(?:\.\d+)?)[Bb](?:[-_]|$)/;
//: File kinds in the order a file list shows them.
const KIND_ORDER = { model: 0, mmproj: 1, mtp: 2, vocab: 3 };

// The size buckets of the filter. The ids are the values the page filters on
// and the test hooks name (docs/testability.md), never the labels. Each bucket
// runs up to the next one's start: a 9.5B model is in "≤9B", not in neither.
export const SIZE_BUCKETS = [
  { id: "all", label: () => hfT("sizeAll") },
  { id: "0-9", lo: 0, below: 10, label: () => "≤9B" },
  { id: "10-19", lo: 10, below: 20, label: () => "10–19B" },
  { id: "20-29", lo: 20, below: 30, label: () => "20–29B" },
  { id: "30-39", lo: 30, below: 40, label: () => "30–39B" },
  { id: "40-74", lo: 40, below: 75, label: () => "40–74B" },
  { id: "75+", lo: 75, below: Infinity, label: () => "75B+" },
];

// Capabilities in the order their chips stand. The tag is the name the API and
// the hooks use; the title says what it means in the page's language.
export const CAPABILITIES = [
  { id: "it", icon: "🤖", title: () => hfT("capTitleIt") },
  { id: "vision", icon: "👁", title: () => hfT("capTitleVision") },
  { id: "audio", icon: "🎙", title: () => hfT("capTitleAudio") },
  { id: "mmproj", icon: "📷", title: () => hfT("capTitleMmproj") },
  { id: "mtp", icon: "⚡", title: () => hfT("capTitleMtp") },
  { id: "uncensored", icon: "🔞", title: () => hfT("capTitleUncensored") },
];

export const SORT_KEYS = [
  { id: "downloads", label: () => hfT("sortDownloads") },
  { id: "likes", label: () => hfT("sortLikes") },
  { id: "params", label: () => hfT("sortSize") },
  { id: "date", label: () => hfT("sortDate") },
  { id: "aa", label: () => hfT("sortAa") },
  { id: "olb", label: () => hfT("sortOlb") },
];

export class HfRepoFacts {
  constructor(id) {
    this.id = id;
    this.record = { id };
    // null until the file list arrives: "no files" and "not loaded" are
    // different answers, and the capability filter must tell them apart.
    this.files = null;
    this.meta = null;
    this.filesError = "";
    this.localNames = null;
    this.localFiles = {};
    this.libraryFiles = {};
    this.tree = undefined;
  }

  merge(record) {
    for (const key of ["downloads", "likes", "createdAt", "pipelineTag", "tags"]) {
      if (record && record[key] !== undefined && record[key] !== "") this.record[key] = record[key];
    }
    return this;
  }

  setFiles(data) {
    this.files = [...(data.files || [])].sort((a, b) =>
      ((KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9)) || String(a.quant || "").localeCompare(String(b.quant || "")) || String(a.name).localeCompare(String(b.name)));
    this.meta = { lastModified: data.lastModified || "", safetensors: data.safetensors || null, otherFiles: data.otherFiles || [] };
    this.filesError = "";
  }

  // What we have of this repository: on this disk (localNames, localFiles) and
  // in the libraries a move carried files to (libraryFiles: name → one entry
  // per library, with its size and time).
  setLocal(data) {
    this.localNames = new Set(data.localNames || []);
    this.localFiles = data.localFiles || {};
    this.libraryFiles = data.libraryFiles || {};
  }

  // The copies of one file in libraries, or an empty list.
  inLibrary(name) {
    return (this.libraryFiles || {})[name] || [];
  }

  get author() {
    return this.id.includes("/") ? this.id.split("/")[0] : "unknown";
  }

  get model() {
    return this.id.split("/").pop();
  }

  get downloads() {
    return Number(this.record.downloads) || 0;
  }

  get likes() {
    return Number(this.record.likes) || 0;
  }

  // A count as the page shows it, or "—" when no answer has carried it: a
  // repository opened by its exact id before Hugging Face answered has none,
  // and a zero would read as a repository nobody downloads.
  countLabel(key) {
    const value = this.record[key];
    return value === undefined || value === null ? "—" : HfFormat.count(value);
  }

  // The size in billions, read off the name. Outside 0.1–10000 it is a version
  // or a date, not a size, and the answer is "unknown".
  get params() {
    const match = this.model.match(PARAMS_RE);
    if (!match) return null;
    const n = parseFloat(match[1]);
    return n >= 0.1 && n <= 10000 ? n : null;
  }

  get paramsLabel() {
    const n = this.params;
    return n === null ? "" : `${n}B`;
  }

  get bucket() {
    const n = this.params;
    if (n === null) return null;
    const hit = SIZE_BUCKETS.find((b) => b.id !== "all" && n >= b.lo && n < b.below);
    return hit ? hit.id : null;
  }

  get kinds() {
    return this.files ? new Set(this.files.map((f) => f.kind)) : null;
  }

  get modality() {
    return [String(this.record.pipelineTag || ""), ...(this.record.tags || [])].join(" ").toLowerCase();
  }

  has(cap) {
    const kinds = this.kinds;
    switch (cap) {
      case "it": return /[-_]it[-_/]|[-_]it-gguf|[-_]it$/i.test(this.id);
      case "uncensored": return /uncensored|heretic|abliterat|unfiltered|unrestricted/i.test(this.id);
      case "vision": return !!(kinds && kinds.has("mmproj")) || /image-text-to-text|any-to-any|\bvision\b|\bvlm\b|multimodal/.test(this.modality);
      case "audio": return /audio-text-to-text|any-to-any|automatic-speech-recognition|\baudio\b/.test(this.modality);
      case "mmproj":
      case "mtp": return !!(kinds && kinds.has(cap));
      default: return false;
    }
  }

  // Whether "does not have it" is an answer yet. The file kinds, and vision
  // through an mmproj file, are only known once the file list is in.
  knows(cap) {
    return this.files !== null || !["mmproj", "mtp", "vision"].includes(cap);
  }

  capabilities() {
    return CAPABILITIES.filter((c) => this.has(c.id)).map((c) => c.id);
  }

  // The artifact format, best effort: tags, then the checkpoint in the file
  // list, then the name. "" when nothing says.
  get format() {
    const tags = (this.record.tags || []).map((x) => String(x).toLowerCase());
    if (tags.includes("gguf")) return "GGUF";
    const st = this.meta && this.meta.safetensors;
    if (st && st.format) return st.format;
    if (tags.includes("mlx")) return "MLX";
    const up = this.id.toUpperCase();
    if (up.endsWith("-GGUF") || up.includes("-GGUF-")) return "GGUF";
    for (const hint of ["NVFP4", "MXFP4", "AWQ", "GPTQ", "AUTOROUND", "FP8", "W4A16", "BNB"]) {
      if (up.includes(hint) || tags.includes(hint.toLowerCase())) return hint;
    }
    return tags.includes("safetensors") ? "ST" : "";
  }

  // Created for a search record; for a favorite saved without one, the newest
  // file date is the best date there is.
  get date() {
    return this.record.createdAt || (this.meta && this.meta.lastModified) || "";
  }

  get localCount() {
    return this.localNames ? this.localNames.size : 0;
  }

  get libraryCount() {
    return Object.keys(this.libraryFiles || {}).length;
  }

  // The libraries holding any file of this repository, by name, each once.
  get libraryNames() {
    const names = Object.values(this.libraryFiles || {}).flat().map((copy) => copy.store && copy.store.name).filter(Boolean);
    return [...new Set(names)];
  }
}

export class HfCatalog {
  constructor(bench) {
    this.bench = bench;
    this.repos = new Map();
    this.resultIds = [];
    this.favoriteIds = [];
    this.searched = false;
    this.tab = "results";
    this.size = "all";
    this.caps = new Set();
    this.mask = "";
    this.sortKey = "downloads";
    this.sortDir = "desc";
  }

  repo(id) {
    let facts = this.repos.get(id);
    if (!facts) {
      facts = new HfRepoFacts(id);
      this.repos.set(id, facts);
    }
    return facts;
  }

  setResults(records) {
    this.searched = true;
    this.resultIds = (records || []).filter((r) => r && r.id).map((r) => this.repo(r.id).merge(r).id);
  }

  setFavorites(records) {
    this.favoriteIds = (records || []).filter((r) => r && r.id).map((r) => this.repo(r.id).merge(r).id);
  }

  isFavorite(id) {
    return this.favoriteIds.includes(id);
  }

  // A new favorite goes first. Returns the list as the server stores it.
  toggleFavorite(id) {
    this.favoriteIds = this.isFavorite(id) ? this.favoriteIds.filter((x) => x !== id) : [id, ...this.favoriteIds];
    return this.favoritesPayload();
  }

  // Only what is known travels: a count nobody reported is left out rather
  // than saved as zero over the numbers the next answer will bring.
  favoritesPayload() {
    return this.favoriteIds.map((id) => {
      const r = this.repo(id).record;
      const out = { id };
      for (const key of ["downloads", "likes"]) if (r[key] !== undefined && r[key] !== null) out[key] = Number(r[key]) || 0;
      for (const key of ["createdAt", "pipelineTag", "tags"]) if (r[key] !== undefined) out[key] = r[key];
      return out;
    });
  }

  ids(tab = this.tab) {
    return tab === "favorites" ? this.favoriteIds : this.resultIds;
  }

  // Everything the background loaders should fetch: favorites and results,
  // each once.
  allIds() {
    return [...new Set([...this.favoriteIds, ...this.resultIds])];
  }

  score(facts, key) {
    const scores = (this.bench && this.bench.scores(facts.id)) || {};
    return typeof scores[key] === "number" ? scores[key] : null;
  }

  // One tab as it is shown. What a filter could not check is not shown as a
  // match: a repository with no size in its name is hidden by a size filter,
  // and one whose files are not in yet by a capability filter — and the view
  // says how many of each it hid.
  view(tab = this.tab) {
    const ids = this.ids(tab);
    const items = [];
    let hiddenNoSize = 0;
    let unchecked = 0;
    for (const id of ids) {
      const facts = this.repo(id);
      if (!this.passesMask(facts)) continue;
      if (this.size !== "all") {
        if (facts.bucket === null) { hiddenNoSize += 1; continue; }
        if (facts.bucket !== this.size) continue;
      }
      const caps = this.capsVerdict(facts);
      if (caps === "unknown") { unchecked += 1; continue; }
      if (caps === "no") continue;
      items.push(facts);
    }
    return { items: this.sorted(items), total: ids.length, hiddenNoSize, unchecked };
  }

  passesMask(facts) {
    return !this.mask || facts.id.toLowerCase().includes(this.mask.toLowerCase());
  }

  // "yes" when any chosen capability is there, "no" when all of them are known
  // to be absent, "unknown" when one of them cannot be told yet.
  capsVerdict(facts) {
    if (!this.caps.size) return "yes";
    const chosen = [...this.caps];
    if (chosen.some((c) => facts.has(c))) return "yes";
    return chosen.every((c) => facts.knows(c)) ? "no" : "unknown";
  }

  // How many each size chip would show, under the other filters.
  sizeCounts(tab = this.tab) {
    const counts = Object.fromEntries(SIZE_BUCKETS.map((b) => [b.id, 0]));
    for (const id of this.ids(tab)) {
      const facts = this.repo(id);
      if (!this.passesMask(facts) || this.capsVerdict(facts) !== "yes") continue;
      counts.all += 1;
      if (facts.bucket) counts[facts.bucket] += 1;
    }
    return counts;
  }

  // Each capability with how many repositories of the tab have it, under the
  // other filters. A capability nobody has gets no chip — unless it is chosen,
  // so it can still be unchosen.
  capCounts(tab = this.tab) {
    const out = [];
    for (const cap of CAPABILITIES) {
      let n = 0;
      for (const id of this.ids(tab)) {
        const facts = this.repo(id);
        if (!this.passesMask(facts)) continue;
        if (this.size !== "all" && facts.bucket !== this.size) continue;
        if (facts.has(cap.id)) n += 1;
      }
      if (n || this.caps.has(cap.id)) out.push({ ...cap, count: n });
    }
    return out;
  }

  // Stable: equal values keep the order the server gave.
  sorted(items) {
    const dir = this.sortDir === "asc" ? 1 : -1;
    const value = (facts) => {
      switch (this.sortKey) {
        case "likes": return facts.likes;
        case "params": return facts.params ?? -1;
        case "date": return facts.date;
        case "aa": return this.score(facts, "aa_intelligence") ?? -1;
        case "olb": return this.score(facts, "open_llm_avg") ?? -1;
        default: return facts.downloads;
      }
    };
    return items.map((facts, i) => [facts, i]).sort(([a, i], [b, j]) => {
      const va = value(a);
      const vb = value(b);
      if (va < vb) return -dir;
      if (va > vb) return dir;
      return i - j;
    }).map(([facts]) => facts);
  }
}
