// Benchmarks on /hf: per repository, and the frontier models they are read
// against.
//
// On the live fleet almost every repository has exactly one score — the AA
// Intelligence Index — and the frontier list is scored on the same index. So
// the score is drawn ON the frontier's scale: a bar in each list row with a
// few frontier models as ticks, and in the repository header the model's mark
// between its two nearest frontier neighbours. The full panel (groups, bars,
// links, where the numbers come from) opens from there.
//
// Group labels and descriptions come from the server in Russian; the page
// shows them in its own language by the benchmark's key, and only an unknown
// key falls back to the server's text.
import { escapeHtml } from "./utils.js";
import { hfT } from "./hf-text.js";

//: The index's own range; a model above it widens the scale rather than overflow.
const AA_SCALE = 65;
//: The benchmarks queue pauses this long between repositories: it runs behind a
//: user who is reading the list, and must not starve the page's other requests.
const QUEUE_PAUSE_MS = 80;

const GROUP_LABEL = {
  summary: () => hfT("benchGroupSummary"),
  knowledge: () => hfT("benchGroupKnowledge"),
  math: () => hfT("benchGroupMath"),
  code: () => hfT("benchGroupCode"),
  dialog: () => hfT("benchGroupDialog"),
};

const BENCH_DESC = {
  arena_elo: () => hfT("benchDescArenaElo"),
  open_llm_avg: () => hfT("benchDescOpenLlmAvg"),
  aa_intelligence: () => hfT("benchDescAaIntelligence"),
  mmlu: () => hfT("benchDescMmlu"),
  mmlu_pro: () => hfT("benchDescMmluPro"),
  arc: () => hfT("benchDescArc"),
  hellaswag: () => hfT("benchDescHellaswag"),
  winogrande: () => hfT("benchDescWinogrande"),
  truthfulqa: () => hfT("benchDescTruthfulqa"),
  gsm8k: () => hfT("benchDescGsm8k"),
  math: () => hfT("benchDescMath"),
  bbh: () => hfT("benchDescBbh"),
  gpqa: () => hfT("benchDescGpqa"),
  musr: () => hfT("benchDescMusr"),
  humaneval: () => hfT("benchDescHumaneval"),
  ifeval: () => hfT("benchDescIfeval"),
  mt_bench: () => hfT("benchDescMtBench"),
  eq_bench: () => hfT("benchDescEqBench"),
};

const ORG_COLOR = {
  Google: "#4285f4", OpenAI: "#10a37f", Anthropic: "#d97757",
  Meta: "#0064e0", DeepSeek: "#5b6cf9", Qwen: "#ff6b00", Mistral: "#fa5252",
};

export class HfBench {
  constructor({ getJson, wait } = {}) {
    this.getJson = getJson || ((url) => fetch(url).then((r) => r.json()));
    this.wait = wait || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
    this.cache = new Map();
    this.pending = new Map();
    this.frontier = null;
    this.frontierPending = null;
    this.queueToken = 0;
    this.done = 0;
    this.total = 0;
  }

  // null when the server has nothing (or failed): an answer, cached like one.
  data(id) {
    return this.cache.has(id) ? this.cache.get(id) : undefined;
  }

  scores(id) {
    const data = this.data(id);
    return (data && data.scores) || {};
  }

  aa(id) {
    const value = this.scores(id).aa_intelligence;
    return typeof value === "number" ? value : null;
  }

  // One request per repository at a time, however many callers ask.
  load(id, force = false) {
    if (!force && this.cache.has(id)) return Promise.resolve(this.cache.get(id));
    if (!force && this.pending.has(id)) return this.pending.get(id);
    const url = `/api/hf/benchmarks?repo=${encodeURIComponent(id)}${force ? "&force=1" : ""}`;
    const request = this.getJson(url)
      .then((data) => (data && data.ok ? data : null))
      .catch(() => null)
      .then((value) => {
        this.cache.set(id, value);
        this.pending.delete(id);
        return value;
      });
    this.pending.set(id, request);
    return request;
  }

  // Everything not loaded yet, one after another. A newer queue replaces an
  // older one: two loops counting into the same progress bar is how the bar
  // used to run backwards.
  async loadAll(ids, onStep) {
    const token = ++this.queueToken;
    const todo = ids.filter((id) => !this.cache.has(id));
    this.total = todo.length;
    this.done = 0;
    if (onStep) onStep(null);
    for (const id of todo) {
      if (token !== this.queueToken) return;
      await this.load(id);
      if (token !== this.queueToken) return;
      this.done += 1;
      if (onStep) onStep(id);
      await this.wait(QUEUE_PAUSE_MS);
    }
  }

  get running() {
    return this.total > 0 && this.done < this.total;
  }

  loadFrontier(force = false) {
    if (this.frontierPending && !force) return this.frontierPending;
    this.frontierPending = this.getJson(`/api/hf/reference-models${force ? "?force=1" : ""}`)
      .then((data) => {
        if (data && data.ok) {
          const models = (data.models || []).filter((m) => typeof m.aa === "number").sort((a, b) => b.aa - a.aa);
          this.frontier = { source: String(data.source || ""), models };
        }
        return this.frontier;
      })
      .catch(() => this.frontier)
      .finally(() => { this.frontierPending = null; });
    return this.frontierPending;
  }

  frontierModels() {
    return (this.frontier && this.frontier.models) || [];
  }

  scale(value = 0) {
    const top = this.frontierModels().reduce((m, x) => Math.max(m, x.aa), 0);
    return Math.max(AA_SCALE, top, Number(value) || 0);
  }

  // The frontier models just below and just above a score.
  neighbours(aa) {
    const models = this.frontierModels();
    const below = models.filter((m) => m.aa <= aa);
    const above = models.filter((m) => m.aa > aa);
    return {
      lo: below.length ? below.reduce((a, b) => (b.aa > a.aa ? b : a)) : null,
      hi: above.length ? above.reduce((a, b) => (b.aa < a.aa ? b : a)) : null,
    };
  }

  // Up to four frontier models spread over the ranking — top, bottom and two
  // between — as ticks a narrow bar can still read.
  ticks(max = 4) {
    const models = this.frontierModels();
    if (models.length <= max) return models;
    const picks = new Set();
    for (let k = 0; k < max; k += 1) picks.add(Math.round((k * (models.length - 1)) / (max - 1)));
    return [...picks].sort((a, b) => a - b).map((i) => models[i]);
  }

  // The row's score: a bar on the frontier scale with ticks, and any other
  // headline score (an Elo, an Open LLM average) as a chip beside it.
  rowHtml(id) {
    const data = this.data(id);
    if (data === undefined) return `<span class="hfp-aa is-pending" aria-hidden="true"></span>`;
    const aa = this.aa(id);
    const chips = (data && data.inline ? data.inline : []).filter((key) => key !== "aa_intelligence").slice(0, 2)
      .map((key) => this.chipHtml(data, key)).join("");
    if (aa === null && !chips) return `<span class="hfp-aa is-none">${escapeHtml(hfT("noBenchShort"))}</span>`;
    return `${aa === null ? "" : this.barHtml(aa, this.ticks())}${chips}`;
  }

  barHtml(aa, ticks) {
    const scale = this.scale(aa);
    const marks = ticks.map((m) => `<i class="hfp-tick" style="left:${((m.aa / scale) * 100).toFixed(1)}%" title="${escapeHtml(`${m.name} ${m.aa}`)}"></i>`).join("");
    return `<span class="hfp-aa" title="AA Intelligence ${aa}"><span class="hfp-aa-k">AA</span>`
      + `<span class="hfp-aa-track"><i class="hfp-aa-fill" style="width:${((aa / scale) * 100).toFixed(1)}%"></i>${marks}</span>`
      + `<b>${escapeHtml(String(aa))}</b></span>`;
  }

  chipHtml(data, key) {
    const meta = (data.meta || {})[key] || [key, "", "", "", ""];
    const value = key === "mt_bench" ? Number(data.scores[key]).toFixed(1) : data.scores[key];
    return `<span class="hfp-bchip${key === "arena_elo" ? " is-elo" : ""}" title="${escapeHtml(meta[0])}">`
      + `${escapeHtml(meta[0])} <b>${escapeHtml(String(value))}</b></span>`;
  }

  // The repository header's line: the mark between its frontier neighbours,
  // where the data comes from, and the ways into the full panel and the list.
  stripHtml(id, open) {
    const data = this.data(id);
    const refresh = `<button type="button" class="hfp-icon-btn" data-act="bench-refresh" data-t="hf-bench-refresh" title="${escapeHtml(hfT("a11yRefreshBench"))}" aria-label="${escapeHtml(hfT("a11yRefreshBench"))}">🔄</button>`;
    if (data === undefined) {
      return `<div class="hfp-strip"><span class="hfp-muted">${escapeHtml(hfT("benchLoadingRepo"))}</span></div>`;
    }
    const aa = this.aa(id);
    const frontierBtn = `<button type="button" class="hfp-link" data-act="frontier" data-t="hf-frontier-open">${escapeHtml(hfT("frontierOpen"))}</button>`;
    const toggle = data && data.scores && Object.keys(data.scores).length
      ? `<button type="button" class="hfp-link" data-act="bench" data-t="hf-bench-toggle" aria-expanded="${open ? "true" : "false"}">${escapeHtml(hfT(open ? "benchHide" : "benchAll"))} ${open ? "▴" : "▾"}</button>`
      : "";
    const source = data
      ? [data.data_from && data.data_from !== id ? hfT("benchFor", { repo: data.data_from }) : "", hfT(data.from_cache ? "benchCached" : "benchFresh")].filter(Boolean)
      : [];
    const sourceHtml = source.map((s) => `<span>${escapeHtml(s)}</span>`).join(`<span class="hfp-dot">·</span>`);
    if (aa === null) {
      return `<div class="hfp-strip"><span class="hfp-aa is-none">AA — ${escapeHtml(hfT(data ? "noBenchShort" : "benchNone"))}</span>`
        + `${sourceHtml}${refresh}${toggle}${frontierBtn}</div>`;
    }
    const scale = this.scale(aa);
    const ticks = this.frontierModels().map((m) => `<i class="hfp-tick" style="left:${((m.aa / scale) * 100).toFixed(1)}%" title="${escapeHtml(`${m.name} ${m.aa}`)}"></i>`).join("");
    const { lo, hi } = this.neighbours(aa);
    let where = "";
    if (lo && hi) where = hfT("aaBetween", { lo: `${lo.name} ${lo.aa}`, hi: `${hi.name} ${hi.aa}` });
    else if (lo) where = hfT("aaTop");
    else if (hi) where = hfT("aaBottom");
    return `<div class="hfp-strip">`
      + `<span class="hfp-aa-big"><span class="hfp-aa-k">AA</span> <b>${escapeHtml(String(aa))}</b></span>`
      + `<span class="hfp-scale" aria-hidden="true"><i class="hfp-scale-track"></i>${ticks}<i class="hfp-scale-me" style="left:${((aa / scale) * 100).toFixed(1)}%"></i></span>`
      + `<span class="hfp-strip-text">${where ? `<span>${escapeHtml(where)}</span><span class="hfp-dot">·</span>` : ""}${sourceHtml}${refresh}${toggle}${frontierBtn}</span>`
      + `</div>`;
  }

  // The full panel: every group with a score, a bar per benchmark, a link to
  // the benchmark itself.
  panelHtml(id) {
    const data = this.data(id);
    if (!data || !data.scores || !Object.keys(data.scores).length) {
      return `<div class="hfp-bench-panel" data-t="hf-bench-panel"><div class="hfp-muted">${escapeHtml(hfT("benchNone"))}</div></div>`;
    }
    const groups = (data.groups || []).filter((g) => g.keys && g.keys.length).map((g) => {
      const label = GROUP_LABEL[g.id] ? GROUP_LABEL[g.id]() : String(g.label || g.id);
      const rows = g.keys.filter((key) => data.scores[key] !== undefined).map((key) => this.benchRowHtml(data, key)).join("");
      return `<div class="hfp-bench-group"><div class="hfp-bench-label">${escapeHtml(label)}</div>${rows}</div>`;
    }).join("");
    return `<div class="hfp-bench-panel" data-t="hf-bench-panel">${groups}</div>`;
  }

  benchRowHtml(data, key) {
    const [name, serverDesc, scale, , url] = (data.meta || {})[key] || [key, "", "0–100 %", "", ""];
    const value = data.scores[key];
    const desc = BENCH_DESC[key] ? BENCH_DESC[key]() : String(serverDesc || "");
    let pct;
    if (key === "arena_elo") pct = Math.min(100, Math.max(0, Math.round((value - 800) / 6)));
    else if (key === "mt_bench") pct = Math.round((value / 10) * 100);
    else if (key === "aa_intelligence") pct = Math.round((value / this.scale(value)) * 100);
    else pct = Math.min(100, Math.max(0, Math.round(value)));
    const shown = key === "mt_bench" ? `${Number(value).toFixed(1)}/10` : `${value}${String(scale).includes("%") ? " %" : ""}`;
    const nameHtml = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener">${escapeHtml(name)}</a>` : escapeHtml(name);
    return `<div class="hfp-bench-row${key === "arena_elo" ? " is-elo" : ""}">`
      + `<span class="hfp-bench-name">${nameHtml}</span><span class="hfp-bench-desc" title="${escapeHtml(desc)}">${escapeHtml(desc)}</span>`
      + `<span class="hfp-bench-bar"><i style="width:${pct}%"></i></span><span class="hfp-bench-val">${escapeHtml(shown)}</span></div>`;
  }

  // The frontier list in full, for its own panel.
  frontierHtml(markId) {
    const models = this.frontierModels();
    const mark = markId ? this.aa(markId) : null;
    const scale = this.scale(mark || 0);
    const rows = models.map((m) => {
      const color = ORG_COLOR[m.org] || "#8a9aa0";
      return `<div class="hfp-front-row"><span class="hfp-front-org" style="color:${color}">${escapeHtml(m.org || "")}</span>`
        + `<span class="hfp-front-name">${escapeHtml(m.name)}</span>`
        + `<span class="hfp-front-bar"><i style="width:${((m.aa / scale) * 100).toFixed(1)}%;background:${color}"></i></span>`
        + `<span class="hfp-front-val">${escapeHtml(String(m.aa))}</span></div>`;
    });
    if (mark !== null) {
      const at = models.findIndex((m) => m.aa <= mark);
      const own = `<div class="hfp-front-row is-own"><span class="hfp-front-org"></span><span class="hfp-front-name">${escapeHtml(markId.split("/").pop())}</span>`
        + `<span class="hfp-front-bar"><i style="width:${((mark / scale) * 100).toFixed(1)}%"></i></span><span class="hfp-front-val">${escapeHtml(String(mark))}</span></div>`;
      rows.splice(at < 0 ? rows.length : at, 0, own);
    }
    const snapshot = this.frontier && this.frontier.source === "default" ? ` · ${escapeHtml(hfT("frontierSnapshot"))}` : "";
    const body = models.length ? rows.join("") : `<div class="hfp-muted">${escapeHtml(hfT("benchLoading"))}</div>`;
    return `<div class="hfp-front-head"><b>${escapeHtml(hfT("frontierTitle"))}</b><span class="grow"></span>`
      + `<button type="button" class="hfp-icon-btn" data-act="frontier-refresh" data-t="hf-frontier-refresh" title="${escapeHtml(hfT("a11yRefreshBench"))}" aria-label="${escapeHtml(hfT("a11yRefreshBench"))}">🔄</button>`
      + `<button type="button" class="hfp-icon-btn" data-act="frontier-close" aria-label="${escapeHtml(hfT("frontierClose"))}">✕</button></div>`
      + `<div class="hfp-front-list">${body}</div>`
      + `<div class="hfp-front-foot">AA Intelligence Index · <a href="https://artificialanalysis.ai/leaderboards/models" target="_blank" rel="noopener">artificialanalysis.ai</a>${snapshot}</div>`;
  }
}
