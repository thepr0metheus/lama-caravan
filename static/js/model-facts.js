// What a model on /models does and how long a context its weights were trained with (1.3.637): the owner's "on the models
// page I want to see at once what context a model supports and what it is for" (2026-10-25). Read, never guessed: a GGUF's
// own header — its <arch>.context_length, and the stt.* and pooling facts its job is told by — through the rows the cell
// editor's picker gets (/api/models/rows), a checkpoint folder's config.json through the page's own listing (model_gc.py:
// `arch`, `contextLength`), and the job by the picker's rule (model-jobs.js jobsForArtifact), so a model is said to do here
// what the editor says it does — a translator's HF cache by its folder, as one model. A model whose window nothing states
// says so ("not known"); a job that takes no window in tokens — a recognizer, a voice — says that instead; a file that is no
// model (a projector, a draft, an importance matrix: models.py LoadsAlone keeps it out of the rows) says nothing. A later part
// of a split GGUF says what its first part says: its own header names nothing, and it read "LLM · not known" on fifteen rows of
// the live page (2026-10-26).
import { t } from "./i18n.js";
import { ModelCopy } from "./model-copy.js";
import { JOBS, JOB_LABELS, JOB_MARKS, jobsForArtifact } from "./model-jobs.js";
import { escapeHtml } from "./utils.js";

export class ModelFacts {
  /** The windows the side column narrows the list to: a long context, a very long one, a million tokens. */
  static WINDOWS = [131072, 262144, 1048576];
  /** The jobs whose models take a context in tokens: a model of these with no window stated has one nobody named. */
  static TOKEN_JOBS = new Set(["llm", "embed", "translate"]);
  /** The data-t names of the side column's filters and the tree's two columns (docs/testability.md). */
  static HOOKS = { job: "models-job-filter", window: "models-window-filter", jobs: "models-row-jobs", ctx: "models-row-window" };

  constructor(byPath = new Map()) {
    this.byPath = byPath;
  }

  static positive(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  /** The facts of every model the page lists: the editor's rows (`{models}`, or null when they did not come) for the GGUF
   *  files here and in the libraries, the page's own listing for the folders. */
  static of(rows, files = []) {
    const byPath = new Map();
    const models = ((rows && rows.models) || []).filter((row) => row && row.kind === "model" && row.path);
    const later = (path) => (ModelCopy.part(path)?.index || 0) > 1;
    for (const row of models.filter((r) => !later(r.path))) {
      const meta = row.ggufMeta || {};
      byPath.set(row.path, { jobs: jobsForArtifact("model", meta.sttVariant || "", "", row.detectedFamily || ""),
                             window: ModelFacts.positive(meta.contextLength) });
    }
    // A later part is a part of the model its first part speaks for; without that part it is a fragment with nothing to say.
    for (const row of models.filter((r) => later(r.path))) {
      const first = byPath.get(ModelCopy.part(row.path).first);
      if (first) byPath.set(row.path, first);
    }
    for (const f of files || []) {
      if (!f || byPath.has(f.path)) continue;
      if (f.kind === "safetensors") {
        byPath.set(f.path, { jobs: jobsForArtifact("st", "", f.arch || ""), window: ModelFacts.positive(f.contextLength) });
      } else if (f.kind === "translate") {
        // A translator's HF cache, whole (model_artifacts.py): its window is what its main snapshot's config says.
        byPath.set(f.path, { jobs: jobsForArtifact("translate"), window: ModelFacts.positive(f.contextLength) });
      } else if (f.kind === "whisper") {
        byPath.set(f.path, { jobs: jobsForArtifact("whisper"), window: null });
      }
    }
    return new ModelFacts(byPath);
  }

  /** What one file is, or null for a file that is no model. */
  of(path) {
    return this.byPath.get(path) || null;
  }

  /** An empty branch: the jobs of its models, the smallest and largest window among them, and whether one of them takes a
   *  window in tokens that nothing states. */
  static blank() {
    return { jobs: new Set(), lo: Infinity, hi: 0, unnamed: false, models: 0 };
  }

  /** A branch told what one model does and how long a window it takes. */
  static told(branch, { jobs = [], window = null } = {}) {
    branch.models += 1;
    jobs.forEach((job) => branch.jobs.add(job));
    if (window) {
      branch.lo = Math.min(branch.lo, window);
      branch.hi = Math.max(branch.hi, window);
    } else if (jobs.some((job) => ModelFacts.TOKEN_JOBS.has(job))) {
      branch.unnamed = true;
    }
    return branch;
  }

  /** Adds a file to a branch's facts. */
  take(branch, path) {
    const facts = this.of(path);
    return facts ? ModelFacts.told(branch, facts) : branch;
  }

  /** A file's facts as a branch of one. */
  single(path) {
    return this.take(ModelFacts.blank(), path);
  }

  /** Does the file pass the side column's choice: a job, a window at least this long (0 — any)? */
  keeps(path, { job = "", window = 0 } = {}) {
    const facts = this.of(path);
    if (job && !(facts && facts.jobs.includes(job))) return false;
    if (window && !(facts && facts.window && facts.window >= window)) return false;
    return true;
  }

  static number(n) {
    return Number(n).toLocaleString("en-US");
  }

  /** The "What for" cell of a row: the jobs of its models, in the vocabulary's order. */
  jobsHtml(branch, id = "") {
    const jobs = JOBS.filter((job) => branch.jobs.has(job));
    const chips = jobs.map((job) => `<span class="mdl-job" data-job="${job}">${JOB_MARKS[job] || ""} ${escapeHtml(t(JOB_LABELS[job]))}</span>`).join("");
    return `<span class="mdl-c-job" data-t="${ModelFacts.HOOKS.jobs}" data-t-id="${escapeHtml(id)}">${chips}</span>`;
  }

  /** What a branch says of its window, in `figure`'s figures: the window, a range when its models differ, "not known" for a model that takes one nobody
   *  stated, a dash for a job with no window in tokens, nothing with no model in it. {state, text, tip}. */
  static windowSaid(branch, figure = ModelFacts.number) {
    if (branch.hi > 0) {
      return { state: "known", text: branch.lo === branch.hi ? figure(branch.hi) : `${figure(branch.lo)} – ${figure(branch.hi)}`, tip: t("mdlWindowTip") };
    }
    if (!branch.models) return { state: "none", text: "", tip: "" };
    if (branch.unnamed) return { state: "unknown", text: t("mdlWindowUnknown"), tip: t("mdlWindowUnknownTip") };
    return { state: "none", text: "—", tip: t("mdlWindowNoneTip") };
  }

  /** The "Context up to" cell. */
  windowHtml(branch, id = "") {
    const { state, text, tip } = ModelFacts.windowSaid(branch);
    return `<span class="mdl-c-window${text && state !== "known" ? " mdl-dim" : ""}" data-t="${ModelFacts.HOOKS.ctx}" data-t-id="${escapeHtml(id)}" data-t-state="${state}"`
      + `${tip ? ` title="${escapeHtml(tip)}"` : ""}>${escapeHtml(text)}</span>`;
  }

  /** The side column's two groups for the files of the place shown: each job with how many of them do it, each window with
   *  how many reach it; a choice is pressed again to take it off, and a group that would keep nothing is not offered. */
  jobsNavHtml(files, chosen = "") {
    return JOBS.map((job) => {
      const n = files.filter((f) => this.keeps(f.path, { job })).length;
      const on = chosen === job;
      if (!n && !on) return "";
      return `<button class="mdl-filter" type="button" data-mdl-job="${job}" data-t="${ModelFacts.HOOKS.job}" data-t-id="${job}"`
        + ` aria-pressed="${on}"><span aria-hidden="true">${JOB_MARKS[job] || ""}</span>`
        + `<span>${escapeHtml(t(JOB_LABELS[job]))}</span><span class="c">${n}</span></button>`;
    }).join("");
  }

  windowsNavHtml(files, chosen = 0) {
    return ModelFacts.WINDOWS.map((window) => {
      const n = files.filter((f) => this.keeps(f.path, { window })).length;
      const on = chosen === window;
      if (!n && !on) return "";
      return `<button class="mdl-filter" type="button" data-mdl-window="${window}" data-t="${ModelFacts.HOOKS.window}"`
        + ` data-t-id="${window}" aria-pressed="${on}"><span aria-hidden="true">≥</span>`
        + `<span>${escapeHtml(t("mdlWindowFrom", { n: ModelFacts.number(window) }))}</span><span class="c">${n}</span></button>`;
    }).join("");
  }
}
