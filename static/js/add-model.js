// The new-cell wizard — "+ Add model" on a machine's page and card (1.3.638). The owner chose variant А of the canvas with three
// changes (2026-10-25): "first choose what the model is for, what it must be able to do" (variant Б's tiles); "llama.cpp has very
// many settings, I want access to them, I fear you will lose them — the important ones (you decide which) in a more visible place";
// "and on the model, at once, the largest context it takes". Then "А2 with the stars of А3": the settings that move the memory
// stand beside the map, all the others fold under them, and a star at any field brings it up among the main ones.
//
// Nothing here is a second form. The wizard drives the cell editor's own form (remote-cells.js CellForm), filled for a new cell of
// the machine without its dialog: the model it picks, the runner, every field are written there, so the checks, the companions, the
// command and the Apply stay the dialog's. The list of the models is the picker's (form.js ModelChoices); the map is the cell
// window's (cell-settings.js over memory.js's placement map); the full list of the settings is the cell window's editor of that
// form; what a model weighs and where it would go is the machine page's rule (machine-head.js CellFit, MachineMap's words). Its
// own are the order of the questions, the jobs and the abilities to narrow the list by, the eight main fields, and the window it
// offers for a model as a tip — the largest of the usual windows the cards hold whole; none is written by itself (WindowPick).
//
// A new cell has no name and no port while the wizard asks about it: the form holds it under the key of a cell not made yet on its
// machine (CellForm.newKey). Create saves it, and the save makes the cell — the controller names it, and the form holds it by that
// name from then on (CellForm.cellId), the name its start is asked by. Its port is its scout's to lease at each start, and nothing
// here says one: a model is called by its name — the pools' rows name "machine + model" since step 3 of the owner's plan (2026-10-26).
import { AskedWindow } from "./asked-window.js";
import { CELL_SETTINGS, CellSettings } from "./cell-settings.js";
import { toggleFields } from "./constants.js";
import { getFavFields } from "./favorites.js";
import { mcSelectItem, ModelChoices, modelsByPath } from "./form.js";
import { ModelRating } from "./model-rating.js";
import { RunnerOffer } from "./runner-offer.js";
import { t } from "./i18n.js";
import { chooseRunner, effectiveRunnerId, runnerAvailability, runnerNaming, runnerRegistry, usesLlamaConfig } from "./llama-edit.js";
import { CellFit, MachineMap } from "./machine-head.js";
import { applyComputeMode, estimateKvCacheGb, shortGpuName } from "./memory.js";
import { ModelFacts } from "./model-facts.js";
import { JOBS, JOB_LABELS, JOB_MARKS, jobRunners, jobsForArtifact } from "./model-jobs.js";
import { CELL_FORM, CellForm, cellServiceAction } from "./remote-cells.js";
import { state, topology } from "./state.js";
import { Band, Button, Pill, Seg, Switch } from "./ui-parts.js";
import { $, escapeHtml, toast } from "./utils.js";

const GIB = 2 ** 30;

/** The windows a model is offered. None is written into the form by itself: an empty field starts the cell with the window its
 *  model was trained for (AskedWindow, the owner's word of 2026-10-26). Until then the wizard wrote the largest window the
 *  cards held whole — a number nobody typed, and a cell of a 131 072-token model started at 32 768. Such a window is only
 *  offered now: AddModel.tip, a button. */
export class WindowPick {
  /** The usual windows, in tokens. */
  static STOPS = [4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576];
  /** The verdicts of a start the cards hold whole (CellFit). */
  static WHOLE = new Set(["cards", "card", "free"]);

  /** The usual windows up to the one the model was trained with, and that one; a model that states none — the usual ones up to
   *  131 072. */
  static stops(trained) {
    const known = Number(trained) > 0 ? Number(trained) : 0;
    const out = WindowPick.STOPS.filter((n) => n <= (known || 131072));
    if (known && !out.includes(known)) out.push(known);
    return out.sort((a, b) => a - b);
  }

}

export class AddModel {
  /** The eight main fields of a llama.cpp cell, the wizard's choice: the window, the requests at once, the cache's type, where it
   *  computes and flash attention decide what it takes and where it goes — the map beside them answers each; the reasoning and the
   *  temperature decide what a client gets; the name is what a client calls it by. CACHE_TYPE_K stands for both types. */
  static MAIN = ["CTX_SIZE", "PARALLEL", "CACHE_TYPE_K", "DEVICE", "ENABLE_FLASH_ATTN", "ENABLE_THINKING", "TEMPERATURE", "MODEL_NAME"];
  /** Fields a main one already sets, never drawn twice among the starred. */
  static COVERED = ["CACHE_TYPE_V", "N_GPU_LAYERS", "MAIN_GPU", "SPLIT_MODE", "TENSOR_SPLIT", "ALIAS", "EXTRA_ARGS"];
  static PARALLEL = [1, 2, 4, 8];
  static CACHE = ["f16", "q8_0", "q4_0"];
  /** What a chat model must be able to do, to narrow the list by: take pictures or sound (a projector), a long context, a cell of
   *  it already on this machine. */
  static ABILITIES = ["projector", "long", "cell"];
  static LONG = 262144;
  static STEPS = ["amStepPick", "amStepRunner", "amStepPlace"];

  /** The parts the wizard is made of, real ones by default; a test gives its own. */
  static defaults() {
    return {
      form: CELL_FORM,
      settings: CELL_SETTINGS,
      choices: () => ModelChoices.items("tr-").filter((c) => c && c.value && !c.missing),
      rows: () => modelsByPath(),
      node: (hostId) => (topology?.nodes || []).find((n) => String(n.id) === String(hostId)) || null,
      // The key the form holds a cell not made yet on a machine under: the form's own rule.
      newKey: (hostId) => CellForm.newKey(hostId),
      pickModel: (value) => mcSelectItem($("tr-MODEL_FILE"), value),
      picked: () => $("tr-MODEL_FILE")?.value || "",
      runner: () => effectiveRunnerId("tr-"),
      llama: (id) => usesLlamaConfig(id),
      chooseRunner: (id) => chooseRunner("tr-", id),
      runners: () => runnerRegistry(),
      available: (row) => runnerAvailability(row, "tr-").ok,
      naming: (value) => runnerNaming(value),
      compute: (sel) => applyComputeMode("tr-", sel),
      kvGb: (row) => estimateKvCacheGb(row, "tr-"),
      favorites: () => getFavFields(),
      start: (cellId) => cellServiceAction(cellId, "start"),
      notify: (words) => toast(words),
      defaults: () => state.config || {},
      doc: () => globalThis.document,
      later: (fn) => setTimeout(fn, 0),
    };
  }

  constructor(deps = {}) {
    this.given = deps;
    this.made = null;
    this.reset();
  }

  /** The parts, put together at their first use: the board's modules import one another in a ring (the board, this wizard,
   *  the form, the board), and the form's object does not exist yet when this module is read. */
  get deps() {
    if (!this.made) this.made = { ...AddModel.defaults(), ...this.given };
    return this.made;
  }

  reset() {
    this.hostId = "";
    this.step = 0;
    this.job = "llm";
    this.abilities = new Set();
    this.query = "";
    this.allOpen = false;
    this.busy = false;
    this.opened = false;
    // What the list says of each model, worked out once an opening: value -> {window, runner, size, fit, tone, verdict}.
    this.figured = new Map();
    // The form as it was filled for the new cell: the config every model of the list is weighed with.
    this.base = {};
  }

  /** The key the form and the settings' editor hold the new cell under while it is not made: its machine's (CellForm.newKey); "" before
   *  an opening. No cellId — the cell has none until Create saves it — and no port. */
  get key() {
    return this.hostId ? this.deps.newKey(this.hostId) : "";
  }

  // ── opening and closing ─────────────────────────────────────────────────────────────────────────────────

  /** Opens the wizard for a new cell on machine `hostId`. The form is filled for it without its dialog — unless the cell window keeps
   *  edits of another cell the operator does not let go. `value` a model to start from, past the first question; `query` the words its
   *  list opens narrowed by and `job` the work it opens on, for a model of several builds. False when it did not open. */
  async open(hostId, { value = "", query = "", job = "" } = {}) {
    if (!hostId) return false;
    if (!(await this.deps.form.mayFill(this.deps.newKey(String(hostId))))) return false;
    this.reset();
    this.hostId = String(hostId);
    if (!this.deps.form.fill(this.key, { pickModel: true, hidden: true })) {
      this.reset();
      return false;
    }
    this.deps.settings.adopt(this.key, { onlySet: false });
    this.base = { ...this.deps.form.read() };
    this.opened = true;
    if (job) this.job = String(job);
    this.query = String(query || "");
    this.paint();
    if (value) this.pick(value);
    return true;
  }

  /** Closes the wizard: nothing was made unless Create was pressed, and the form is no one's to keep. */
  close() {
    if (!this.opened) return false;
    this.deps.settings.release(this.key);
    this.opened = false;
    const root = this.root(false);
    if (root) root.hidden = true;
    return true;
  }

  // ── what is known ───────────────────────────────────────────────────────────────────────────────────────

  node() {
    return this.deps.node(this.hostId) || {};
  }

  value(field) {
    return String(this.deps.form.read()?.[field] ?? "");
  }

  /** The model picked, or "" while none is. Asked of the field: the form's reading empties it for a runner that names its model
   *  in a field of its own (vLLM, whisper, moonshine), and the wizard stood on an empty second step with Next shut (2026-11-03). */
  picked() {
    return String(this.deps.picked() ?? "");
  }

  choices() {
    return this.deps.choices() || [];
  }

  choice(value = this.picked()) {
    return this.choices().find((c) => c.value === value) || null;
  }

  jobsOf(choice) {
    return jobsForArtifact(choice.kind, choice.sttVariant, choice.stArch, choice.detectedFamily);
  }

  /** The cells of this machine that already run this model, by their cellIds. */
  cellsOf(value) {
    return (this.node().servers || []).filter((s) => {
      const cfg = s.slotConfig || s.config || {};
      return String(cfg.MODEL_FILE || "") === value || String(s.modelPath || "").endsWith(`/${value}`);
    }).map((s) => MachineMap.idOf(s)).filter(Boolean);
  }

  /** The runner a model is made for: the one that names its kind, else llama.cpp's (the form's own jump, runnerNaming). */
  /** The runner a row is figured for: the one that names it; a checkpoint no runner names is vLLM's, where the form jumps when it is picked. */
  runnerOf(choice) {
    return this.deps.naming(choice.value)?.id || (choice.kind === "st" ? "vllm" : "llama-server");
  }

  runnerRow(id) {
    return (this.deps.runners() || []).find((r) => r.id === id) || {};
  }

  /** What a model of the list would weigh and where it would go on this machine, with the config the form was filled with: a
   *  llama.cpp model at the window its start would ask for (AskedWindow: the form's, else the one the model was trained for) by
   *  the cell window's plan, any other by its runner's own figure or its files — the machine page's rule and words (CellFit,
   *  MachineMap). Worked out once an opening. */
  figures(choice) {
    if (this.figured.has(choice.value)) return this.figured.get(choice.value);
    const runner = this.runnerOf(choice);
    const row = this.runnerRow(runner);
    const node = this.node();
    let fit;
    let window = null;
    if (this.deps.llama(runner)) {
      // The model alone: the form's projector and draft are another model's (or none), and a pick brings the model's own (form.js).
      const config = { ...this.base, MODEL_FILE: choice.value, MMPROJ_FILE: "", SPEC_DRAFT_MODEL_FILE: "", RUNNER: runner };
      window = AskedWindow.of(config.CTX_SIZE, choice.window);
      fit = CellFit.of(CellFit.facts({ how: "spread", config, defaults: this.deps.defaults(), row, models: this.deps.rows() }));
    } else {
      const fixed = Number(row.vramPlan?.fixedMiB || 0) / 1024;
      const files = Number(choice.sizeGb || 0);
      fit = CellFit.of(CellFit.facts({ how: row.vramPlan?.takesFree ? "free" : "card", bytes: fixed > 0 ? fixed * GIB : files > 0 ? files * GIB : null,
                                       planned: fixed > 0, config: this.base, row }));
    }
    const placed = fit.place(node);
    const out = { runner, size: MachineMap.sizeOf(fit.facts), fit: MachineMap.fitWords(placed), tone: MachineMap.fitTone(placed.verdict),
                  verdict: placed.verdict, window };
    this.figured.set(choice.value, out);
    return out;
  }

  /** Does a model pass the abilities chosen? */
  able(choice) {
    for (const a of this.abilities) {
      if (a === "projector" && !(choice.capability === "vision_likely" || choice.suggestedMmproj)) return false;
      if (a === "long" && !(Number(choice.window) >= AddModel.LONG)) return false;
      if (a === "cell" && !this.cellsOf(choice.value).length) return false;
    }
    return true;
  }

  /** The models of the job chosen that pass the abilities and the words typed. */
  listed() {
    const q = this.query.trim().toLowerCase();
    return this.choices().filter((c) => this.jobsOf(c).includes(this.job) && (this.job !== "llm" || this.able(c))
      && (!q || String(c.value).toLowerCase().includes(q) || String(c.stName || "").toLowerCase().includes(q)));
  }

  static number(n) {
    return Number(n).toLocaleString("en-US");
  }

  static gb(n) {
    return Number(n).toFixed(1);
  }

  // ── the parts ───────────────────────────────────────────────────────────────────────────────────────────

  machineName() {
    const n = this.node();
    return String(n.name || n.id || this.hostId);
  }

  headHtml() {
    return `<header class="am-head"><div class="am-head-text"><h2 class="am-title" id="amTitle">${escapeHtml(t("amTitle"))}</h2>`
      + `<span class="am-sub">${escapeHtml(t("amSub", { machine: this.machineName() }))}</span></div>`
      + `${new Button({ kind: "icon", icon: "close", label: t("amClose"), title: t("amClose"), attrs: 'data-am-close data-t="add-model-close"' }).html()}`
      + `</header>`;
  }

  /** The line under the head: what will be made, in one line, in the tone of where it would go. */
  bandHtml() {
    const choice = this.choice();
    if (!choice) return new Band({ tone: "idle", title: t("amBandEmpty"), sub: escapeHtml(t("amSummaryNone")), attrs: 'data-am-band role="status"' }).html();
    const runner = this.runnerRow(this.deps.runner());
    const now = this.now();
    const label = t(runner.labelKey || runner.id || "");
    return new Band({ tone: now.tone, title: `${this.nameOf(choice)} · ${label}`, sub: escapeHtml([now.size, now.fit].filter(Boolean).join(" · ")),
                      attrs: 'data-am-band role="status"' }).html();
  }

  nameOf(choice) {
    if (!choice) return "";
    if (choice.kind === "st") return String(choice.stName || choice.value);
    if (choice.kind === "whisper") return `whisper · ${choice.whSize}`;
    if (choice.kind === "moonshine") return `moonshine · ${choice.msLang}`;
    if (choice.kind === "translate") return `nllb · ${choice.trName}`;
    return String(choice.value).split("/").pop();
  }

  /** What the model picked weighs and where it goes, as the form holds it now — the plan with the form's own fields. */
  now() {
    const choice = this.choice();
    if (!choice) return { size: "", fit: "", tone: "idle", verdict: "unknown" };
    const runner = this.deps.runner();
    const row = this.runnerRow(runner);
    const config = this.deps.form.read();
    const fit = this.deps.llama(runner)
      ? CellFit.of(CellFit.facts({ how: "spread", config, defaults: this.deps.defaults(), row, models: this.deps.rows() }))
      : CellFit.of(CellFit.facts({ how: row.vramPlan?.takesFree ? "free" : "card", config, row,
                                   bytes: Number(row.vramPlan?.fixedMiB || 0) > 0 ? Number(row.vramPlan.fixedMiB) * 1024 * 1024
                                     : Number(choice.sizeGb || 0) > 0 ? Number(choice.sizeGb) * GIB : null,
                                   planned: Number(row.vramPlan?.fixedMiB || 0) > 0 }));
    const placed = fit.place(this.node());
    return { size: MachineMap.sizeOf(fit.facts), fit: MachineMap.fitWords(placed), tone: MachineMap.fitTone(placed.verdict), verdict: placed.verdict };
  }

  railHtml() {
    const picked = !!this.choice();
    const values = [this.choice() ? this.nameOf(this.choice()) : t("amPickFirst"),
                    picked ? t(this.runnerRow(this.deps.runner()).labelKey || "") : "—", picked ? this.now().fit : "—"];
    return `<nav class="am-rail" aria-label="${escapeHtml(t("amStepsLabel"))}">${AddModel.STEPS.map((key, i) => {
      const on = i === this.step;
      const done = i < this.step;
      const off = i > 0 && !picked;
      return `<button type="button" class="am-step${on ? " on" : ""}${done ? " done" : ""}" data-am-step="${i}" data-t="add-model-step" data-t-id="${i}"`
        + `${on ? ' aria-current="step"' : ""}${off ? " disabled" : ""}><span class="am-num">${i + 1}</span>`
        + `<span class="am-step-text"><b>${escapeHtml(t(key))}</b><span>${escapeHtml(values[i])}</span></span></button>`;
    }).join("")}</nav>`;
  }

  // Step 1: what the model is for, and which.

  tilesHtml() {
    const all = this.choices();
    return `<div class="am-tiles" role="group" aria-label="${escapeHtml(t("amJobsLabel"))}">${JOBS.map((job) => {
      const mine = all.filter((c) => this.jobsOf(c).includes(job));
      const runners = [...new Set(mine.length ? mine.map((c) => this.runnerOf(c)) : jobRunners(job))]
        .map((id) => t(this.runnerRow(id).labelKey || id)).filter(Boolean);
      const on = this.job === job;
      return `<button type="button" class="am-tile${on ? " on" : ""}" data-am-job="${job}" data-t="add-model-job" data-t-id="${job}" aria-pressed="${on}">`
        + `<span class="am-tile-mark" aria-hidden="true">${JOB_MARKS[job] || ""}</span><b>${escapeHtml(t(JOB_LABELS[job]))}</b>`
        + `<span class="am-tile-count">${escapeHtml(t("amJobCount", { n: String(mine.length) }))}</span>`
        + `<span class="am-tile-runners">${escapeHtml(runners.join(" · "))}</span></button>`;
    }).join("")}</div>`;
  }

  abilitiesHtml() {
    if (this.job !== "llm") return "";
    const words = { projector: t("amAbilityProjector"), long: t("amAbilityLong", { n: AddModel.number(AddModel.LONG) }), cell: t("amAbilityCell") };
    const tips = { projector: t("amAbilityProjectorTip"), long: "", cell: "" };
    return `<div class="am-abilities"><span class="am-label">${escapeHtml(t("amAbilitiesLabel"))}</span>${AddModel.ABILITIES.map((a) => {
      const attrs = `data-am-ability="${a}" data-t="add-model-ability" data-t-id="${a}"${tips[a] ? ` title="${escapeHtml(tips[a])}"` : ""}`;
      return new Pill({ text: words[a], on: this.abilities.has(a), attrs }).html();
    }).join("")}</div>`;
  }

  rowHtml(choice) {
    const fig = this.figures(choice);
    const on = this.picked() === choice.value;
    const cells = this.cellsOf(choice.value);
    const dir = choice.kind === "st" ? choice.value : String(choice.value).split("/").slice(0, -1).join("/");
    const facts = [dir, choice.libraryOnly ? `📚 ${choice.store?.name || ""}` : "", choice.cached ? t("cachedOnHost") : "",
                   cells.length ? t("amRowCell", { n: String(cells.length) }) : ""].filter(Boolean).join(" · ");
    // The model's trained window; "not known" for one that takes a window in tokens and states none, a dash for a job that takes
    // none — the models page's rule (model-facts.js).
    const tokens = this.jobsOf(choice).some((job) => ModelFacts.TOKEN_JOBS.has(job));
    const window = choice.window ? AddModel.number(choice.window) : tokens ? t("mdlWindowUnknown") : "—";
    const size = fig.window ? `${fig.size} · ${t("amSizeAt", { n: AddModel.number(fig.window) })}` : fig.size;
    return `<button type="button" class="am-row${on ? " on" : ""}" data-am-pick="${escapeHtml(choice.value)}" data-t="add-model-row"`
      + ` data-t-id="${escapeHtml(choice.value)}" aria-pressed="${on}"><span class="am-row-name"><b>${escapeHtml(this.nameOf(choice))}${ModelRating.markHtml(choice.rating, t)}</b>`
      + `<span>${escapeHtml(facts)}</span></span><span class="am-row-window${choice.window ? "" : " dim"}" title="${escapeHtml(t("mdlWindowTip"))}">`
      + `${escapeHtml(window)}</span><span class="am-row-size">${escapeHtml(size)}</span>`
      + `<span class="am-row-fit ${fig.tone}">${escapeHtml(fig.fit)}</span></button>`;
  }

  listHtml() {
    const rows = this.listed();
    const body = rows.length ? rows.map((c) => this.rowHtml(c)).join("")
      : `<p class="am-empty" data-t="add-model-empty">${escapeHtml(t("amNoModels"))}</p>`;
    return `<div class="am-list-head"><span>${escapeHtml(t("amColModel"))}</span><span>${escapeHtml(t("mdlColWindow"))}</span>`
      + `<span>${escapeHtml(t("amColSize"))}</span><span>${escapeHtml(t("amColFit"))}</span></div><div class="am-list" data-am-list>${body}</div>`;
  }

  pickHtml() {
    return `<div class="am-pick"><span class="am-label">${escapeHtml(t("amJobsLabel"))}</span>${this.tilesHtml()}${this.abilitiesHtml()}`
      + `<div class="am-find"><input type="search" id="amQuery" class="am-input" data-am-query data-t="add-model-search" value="${escapeHtml(this.query)}"`
      + ` placeholder="${escapeHtml(t("amSearch"))}" aria-label="${escapeHtml(t("amSearch"))}" autocomplete="off" spellcheck="false">`
      + `<a class="am-link" href="/hf" data-t="add-model-hf">${escapeHtml(t("amFindHf"))}</a></div>`
      + `<div data-am-rows>${this.listHtml()}</div><p class="am-note">${escapeHtml(t("amListNote"))}</p></div>`;
  }

  // Step 2: how it is run.

  runnerStepHtml() {
    const choice = this.choice();
    if (!choice) return "";
    const id = this.deps.runner();
    const row = this.runnerRow(id);
    // Which runners are offered at all is RunnerOffer's (runner-offer.js), the rule the launch builder of a machine's page offers by too.
    const others = (this.deps.runners() || []).filter((r) => r.id !== id && RunnerOffer.offered(r) && this.deps.available(r));
    const alts = others.map((r) => `<div class="am-alt"><b>${escapeHtml(`${r.icon || ""} ${t(r.labelKey || r.id)}`.trim())}</b>`
      + `<span>${escapeHtml(r.benefitsKey ? t(r.benefitsKey) : "")}</span>`
      + `${new Button({ text: t("amRunnerPick"), attrs: `data-am-runner="${escapeHtml(r.id)}" data-t="add-model-runner" data-t-id="${escapeHtml(r.id)}"` }).html()}</div>`).join("");
    return `<div class="am-runner"><div class="am-runner-chosen"><b>${escapeHtml(`${row.icon || ""} ${t(row.labelKey || id)}`.trim())}</b>`
      + `<span class="am-tag">${escapeHtml(t("amRunnerChosen"))}</span><p>${escapeHtml(row.benefitsKey ? t(row.benefitsKey) : "")}</p>`
      + `${row.minusKey ? `<p class="am-minus">${escapeHtml(t(row.minusKey))}</p>` : ""}</div>`
      + `${alts ? `<span class="am-label">${escapeHtml(t("amRunnerOthers"))}</span>${alts}` : ""}`
      + `${this.companionsHtml(choice)}`
      + `<div class="am-runner-all"><span>${escapeHtml(t("amRunnerAllNote"))}</span>`
      + `${new Button({ text: t("amFullForm"), attrs: 'data-am-full data-t="add-model-full"' }).html()}</div></div>`;
  }

  /** The projector and the draft a model may start with: as the form offers them (its lists, ModelCompanions). */
  companionsHtml(choice) {
    if (!this.deps.llama(this.deps.runner())) return "";
    const row = this.deps.rows()?.get?.(choice.value) || {};
    const projectors = Array.isArray(row.compatibleMmprojs) ? row.compatibleMmprojs : [];
    const drafts = (Array.isArray(row.compatibleDrafts) ? row.compatibleDrafts : []).length || row.hasMtpBuiltin;
    if (!projectors.length && !drafts) return "";
    const mmproj = this.value("MMPROJ_FILE");
    const proj = projectors.length
      ? `<label class="am-comp"><span>${escapeHtml(t("amProjector"))}</span><select id="amProjector" class="am-input" data-am-mmproj data-t="add-model-mmproj">`
        + `<option value=""${mmproj ? "" : " selected"}>${escapeHtml(t("amProjectorNone"))}</option>`
        + projectors.map((p) => `<option value="${escapeHtml(p)}"${p === mmproj ? " selected" : ""}>${escapeHtml(String(p).split("/").pop())}</option>`).join("")
        + `</select></label>` : "";
    const on = this.deps.form.checked("SPEC_ENABLED");
    const draft = drafts
      ? `<div class="am-comp"><span>${escapeHtml(t("amDraft"))}</span>`
        + `${new Switch({ on, label: t("amDraft"), attrs: 'id="amDraft" data-am-toggle="SPEC_ENABLED" data-t="add-model-draft"' }).html()}`
        + `<span>${escapeHtml(on ? (this.value("SPEC_DRAFT_MODEL_FILE").split("/").pop() || t("enabled")) : t("amDraftOff"))}</span></div>` : "";
    return `<div class="am-comps">${proj}${draft}</div>`;
  }

  // Step 3: where, and the settings.

  segs(field, options, current, hook, label) {
    return new Seg({ label, options: options.map((o) => ({ text: o.label, count: o.tag || "", on: String(o.value) === String(current),
                                                           attrs: `data-am-set="${field}" data-am-value="${escapeHtml(String(o.value))}"`
                                                             + ` data-t="${hook}" data-t-id="${escapeHtml(String(o.value))}"` })) }).html();
  }

  field(title, env, body, hint = "", tone = "") {
    return `<div class="am-field"><div class="am-field-top"><b>${escapeHtml(title)}</b><code>${escapeHtml(env)}</code></div>${body}`
      + `${hint ? `<span class="am-hint${tone ? ` ${tone}` : ""}">${escapeHtml(hint)}</span>` : ""}</div>`;
  }

  switchHtml(field, hook, label, id = "") {
    const on = this.deps.form.checked(field);
    return `<span class="am-switch">${new Switch({ on, label, attrs: `id="am-${field}" data-am-toggle="${field}" data-t="${hook}"${id ? ` data-t-id="${id}"` : ""}` }).html()}`
      + `<span>${escapeHtml(t(on ? "enabled" : "disabled"))}</span></span>`;
  }

  textHtml(field, hook, placeholder = "") {
    return `<input type="text" id="am-${field}" class="am-input" data-am-field="${field}" data-t="${hook}" value="${escapeHtml(this.value(field))}"`
      + ` placeholder="${escapeHtml(placeholder)}" autocomplete="off" spellcheck="false">`;
  }

  ctxHtml(choice) {
    const trained = Number(choice?.window || 0);
    // The window the start asks for: an empty field is the trained one, and its segment is the one pressed.
    const ctx = AskedWindow.of(this.value("CTX_SIZE"), trained) || 0;
    const stops = WindowPick.stops(trained);
    if (trained && trained <= 524288) stops.push(trained * 2);
    const options = stops.map((n) => ({ value: n, label: AddModel.number(n),
                                        tag: n === trained ? t("amCtxMax") : n > trained && trained ? "YaRN" : "" }));
    const row = this.deps.rows()?.get?.(choice?.value) || null;
    const kv = row ? Number(this.deps.kvGb(row) || 0) : 0;
    const hint = !trained ? t("amCtxUnknown") : ctx > trained ? `${t("cellRowCtxOver")} · ${t("cellRowCtxMax", { n: AddModel.number(trained) })}`
      : t("amCtxTrained", { n: AddModel.number(trained) });
    const own = `<input type="text" inputmode="numeric" id="am-CTX_SIZE" class="am-input am-own" data-am-field="CTX_SIZE" data-t="add-model-ctx-own"`
      + ` value="${escapeHtml(this.value("CTX_SIZE"))}" placeholder="${trained || ""}" aria-label="${escapeHtml(t("amCtxOwn"))}" autocomplete="off">`;
    const cost = kv > 0 ? `<span class="am-cost">${escapeHtml(t("amCtxCost", { gb: AddModel.gb(kv) }))}</span>` : "";
    return this.field(t("amCtx"), "CTX_SIZE", `${this.segs("CTX_SIZE", options, ctx, "add-model-ctx", t("amCtx"))}<div class="am-own-row">${own}${cost}</div>`,
                      hint, ctx > trained && trained ? "warn" : "");
  }

  parallelHtml() {
    const par = Number(this.value("PARALLEL") || 0);
    const ctx = AskedWindow.of(this.value("CTX_SIZE"), this.choice()?.window) || 0;
    const unified = this.deps.form.checked("KV_UNIFIED");
    // One request takes the whole window, and that needs no word; more share it, unless one cache serves them all.
    const hint = !ctx || !(par > 1) ? "" : unified ? t("amPerRequestShared") : t("amPerRequest", { n: AddModel.number(Math.floor(ctx / par)) });
    return this.field(t("amParallel"), "PARALLEL", this.segs("PARALLEL", AddModel.PARALLEL.map((n) => ({ value: n, label: String(n) })), par,
                                                             "add-model-parallel", t("amParallel")), hint);
  }

  cacheHtml() {
    const type = this.value("CACHE_TYPE_K") || "f16";
    const hints = { f16: t("amCacheF16"), q8_0: t("amCacheQ8"), q4_0: t("amCacheQ4") };
    return this.field(t("amCacheType"), "CACHE_TYPE_K / V", this.segs("CACHE_TYPE", AddModel.CACHE.map((v) => ({ value: v, label: v })), type,
                                                                       "add-model-cache", t("amCacheType")), hints[type] || "");
  }

  /** Where it computes: every card, one of them, the processor — the compute target's own choices (memory.js). */
  whereHtml() {
    const gpus = (this.node().gpus || []).filter((g) => g && g.index !== undefined);
    const cpu = this.value("N_GPU_LAYERS").trim() === "0";
    const device = this.value("DEVICE").trim();
    const current = cpu ? "cpu" : !device ? "all" : (/^CUDA(\d+)$/.exec(device) || [])[1] ?? "all";
    const options = [...(gpus.length > 1 ? [{ value: "all", label: t("amWhereAll") }] : []),
                     ...gpus.map((g) => ({ value: String(g.index), label: `GPU ${g.index} · ${shortGpuName(g.name)}` })),
                     { value: "cpu", label: t("amWhereCpu") }];
    const hint = current === "cpu" ? t("amWhereCpuHint") : current === "all" ? t("amWhereAllHint") : t("amWhereOneHint");
    return this.field(t("amWhere"), "DEVICE · N_GPU_LAYERS", this.segs("WHERE", options, gpus.length === 1 && current === "all" ? String(gpus[0].index) : current,
                                                                       "add-model-where", t("amWhere")), hint);
  }

  starredHtml() {
    const shown = (this.deps.favorites() || []).filter((f) => !AddModel.MAIN.includes(f) && !AddModel.COVERED.includes(f));
    if (!shown.length) return `<p class="am-note" data-t="add-model-starred-none">${escapeHtml(t("amStarredHint"))}</p>`;
    const form = this.deps.form;
    return `<span class="am-label">${escapeHtml(t("amStarredLabel"))}</span><div class="am-starred">${shown.map((f) => {
      const box = toggleFields.includes(f);
      const input = box
        ? this.switchHtml(f, "add-model-starred", f, f)
        : `<input type="text" id="am-${f}" class="am-input" data-am-field="${f}" data-t="add-model-starred" data-t-id="${f}" value="${escapeHtml(this.value(f))}"`
          + ` placeholder="${escapeHtml(t("cwSetUnset"))}" autocomplete="off" spellcheck="false">`;
      return `<div class="am-field am-star-field"><div class="am-field-top"><code>${escapeHtml(f)}</code></div>${input}</div>`;
    }).join("")}</div>`;
  }

  /** The main fields: for a llama.cpp cell the eight, then the starred; any other runner is set in the full form. */
  mainHtml() {
    const choice = this.choice();
    const runner = this.deps.runner();
    if (!this.deps.llama(runner)) {
      const row = this.runnerRow(runner);
      return `<div class="am-main" data-am-main><span class="am-label">${escapeHtml(t("amMainLabel"))}</span>`
        + `<p class="am-note">${escapeHtml(t("amRunnerFields", { runner: t(row.labelKey || runner) }))}</p>`
        + `${new Button({ text: t("amFullForm"), attrs: 'data-am-full data-t="add-model-full"' }).html()}</div>`;
    }
    const alias = this.value("ALIAS");
    return `<div class="am-main" data-am-main><span class="am-label">${escapeHtml(t("amMainLabel"))}</span>`
      + `${this.ctxHtml(choice)}<div class="am-grid">${this.parallelHtml()}${this.cacheHtml()}${this.whereHtml()}`
      + `${this.field(t("amFlash"), "ENABLE_FLASH_ATTN", this.switchHtml("ENABLE_FLASH_ATTN", "add-model-flash", t("amFlash")), t("amFlashHint"))}</div>`
      + `<span class="am-label">${escapeHtml(t("amMainAnswers"))}</span><div class="am-grid am-grid3">`
      + `${this.field(t("amThinking"), "ENABLE_THINKING", this.switchHtml("ENABLE_THINKING", "add-model-thinking", t("amThinking")), t("amThinkingHint"))}`
      + `${this.field(t("amTemp"), "TEMPERATURE", this.textHtml("TEMPERATURE", "add-model-temp", "0.80"), t("amTempHint"))}`
      + `${this.field(t("amName"), "MODEL_NAME", this.textHtml("MODEL_NAME", "add-model-name", alias), t("amNameHint"))}</div>`
      + `${this.starredHtml()}</div>`;
  }

  /** A smaller window that the cards hold whole, when the one the start asks for does not — the one set, or for an empty field
   *  the trained one. Offered, never written: the operator presses it. */
  tip() {
    const choice = this.choice();
    if (!choice || !this.deps.llama(this.deps.runner())) return null;
    const ctx = AskedWindow.of(this.value("CTX_SIZE"), choice.window) || 0;
    if (!ctx || WindowPick.WHOLE.has(this.now().verdict)) return null;
    const row = this.runnerRow(this.deps.runner());
    const config = this.deps.form.read();
    const verdictAt = (n) => CellFit.of(CellFit.facts({ how: "spread", config: { ...config, CTX_SIZE: String(n) }, defaults: this.deps.defaults(),
                                                         row, models: this.deps.rows() })).place(this.node()).verdict;
    const smaller = WindowPick.stops(choice.window).filter((n) => n < ctx);
    for (let i = smaller.length - 1; i >= 0; i -= 1) if (WindowPick.WHOLE.has(verdictAt(smaller[i]))) return smaller[i];
    return null;
  }

  placeHtml() {
    const llama = this.deps.llama(this.deps.runner());
    const now = this.now();
    const tip = this.tip();
    const map = llama ? this.deps.settings.placeHtml(this.key, { llama: true, editable: true }) : "";
    return `<div class="am-place" data-t="add-model-place"><div class="am-place-head"><b>${escapeHtml(t("amPlaceTitle"))}</b>`
      + `<span class="am-fit ${now.tone}">${escapeHtml([now.size, now.fit].filter(Boolean).join(" · "))}</span></div>`
      + `${map || `<p class="am-note">${escapeHtml(t("amNoMap"))}</p>`}`
      + `${tip ? `<div class="am-tip"><span>${escapeHtml(t("amTip", { n: AddModel.number(tip),
                                                                      was: AddModel.number(AskedWindow.of(this.value("CTX_SIZE"), this.choice()?.window)) }))}</span>`
        + `${new Button({ text: t("amTipSet", { n: AddModel.number(tip) }), attrs: `data-am-set="CTX_SIZE" data-am-value="${tip}" data-t="add-model-tip"` }).html()}</div>` : ""}</div>`;
  }

  allHtml() {
    if (!this.deps.llama(this.deps.runner())) return "";
    // The fields of llama-server the form has, EXTRA_ARGS — any other flag — aside.
    const count = String(CellSettings.groups().flatMap((g) => g.fields).filter((f) => f !== "EXTRA_ARGS").length);
    const head = `<div class="am-all-head"><div><b>${escapeHtml(t("amAllTitle", { n: count }))}</b><span>${escapeHtml(t("amAllLine"))}</span></div>`
      + `${new Button({ text: t(this.allOpen ? "amAllClose" : "amAllOpen"), attrs: `data-am-all data-t="add-model-all" aria-expanded="${this.allOpen}"` }).html()}</div>`;
    return `<section class="am-all" data-am-all-box>${head}${this.allOpen ? this.deps.settings.html(this.key, { llama: true, editable: true }) : ""}</section>`;
  }

  cellHtml() {
    // A runner that keeps its models in a folder of its own (the registry's workFolder: Strata) keeps them by that folder's limit,
    // whatever a switch here would say (the owner, 2026-11-03): the words say where they are instead.
    if (this.runnerRow(this.deps.runner()).workFolder) {
      return `<div class="am-cell"><span class="am-label">${escapeHtml(t("amCell"))}</span>`
        + `<span class="am-note" data-t="add-model-keep-folder">${escapeHtml(t("cacheModelsFolder"))}</span></div>`;
    }
    const keep = this.deps.form.checked("cacheModels");
    return `<div class="am-cell"><span class="am-label">${escapeHtml(t("amCell"))}</span>`
      + `<span class="am-switch">${new Switch({ on: keep, label: t("amCacheModel"), attrs: 'id="am-cacheModels" data-am-toggle="cacheModels" data-t="add-model-keep"' }).html()}`
      + `<span>${escapeHtml(t("amCacheModel"))}</span></span></div>`;
  }

  stepHtml() {
    if (this.step === 0) return this.pickHtml();
    if (this.step === 1) return this.runnerStepHtml();
    return `<div class="am-third"><div class="am-cols">${this.mainHtml()}<div data-am-place>${this.placeHtml()}</div></div>`
      + `${this.cellHtml()}${this.allHtml()}</div>`;
  }

  footHtml() {
    const picked = !!this.choice();
    const now = picked ? this.now() : null;
    const summary = picked ? t("amSummary", { model: this.nameOf(this.choice()), machine: this.machineName(), size: now.size }) : t("amSummaryNone");
    const shut = !picked || this.busy;
    return `<footer class="am-foot" data-am-foot><span class="am-summary">${escapeHtml(summary)}</span>`
      + `${picked ? new Button({ kind: "quiet", text: t("amFullForm"), attrs: 'data-am-full data-t="add-model-full"' }).html() : ""}`
      + `${new Button({ text: t("amBack"), attrs: 'data-am-back data-t="add-model-back"', disabled: this.step === 0 }).html()}`
      + `${this.step < 2 ? new Button({ text: t("amNext"), attrs: 'data-am-next data-t="add-model-next"', disabled: !picked }).html() : ""}`
      + `${new Button({ text: t("amCreate"), attrs: 'data-am-create data-t="add-model-create"', disabled: shut }).html()}`
      + `${new Button({ kind: "main", text: t("amCreateStart"), attrs: 'data-am-create-start data-t="add-model-create-start"', disabled: shut }).html()}`
      + `</footer>`;
  }

  html() {
    return `<section class="am" role="dialog" aria-modal="true" aria-labelledby="amTitle" data-t="add-model" data-t-id="${escapeHtml(this.key)}"`
      + ` data-t-state="${["pick", "runner", "place"][this.step]}">${this.headHtml()}<div data-am-band-box>${this.bandHtml()}</div>`
      + `<div class="am-body">${this.railHtml()}<div class="am-content" data-am-content>${this.stepHtml()}</div></div>`
      + `${this.footHtml()}</section>`;
  }

  // ── on the page ─────────────────────────────────────────────────────────────────────────────────────────

  /** The wizard's layer over the page, made once. */
  root(make = true) {
    const doc = this.deps.doc();
    let root = doc?.getElementById?.("addModelOverlay") || null;
    if (!root && make && doc?.createElement) {
      root = doc.createElement("div");
      root.id = "addModelOverlay";
      root.className = "am-overlay";
      root.hidden = true;
      doc.body?.appendChild?.(root);
    }
    if (root && !root.__amBound) {
      root.__amBound = true;
      root.addEventListener?.("click", (e) => this.onClick(e));
      root.addEventListener?.("input", (e) => this.onInput(e));
      root.addEventListener?.("change", (e) => this.onChange(e));
      root.addEventListener?.("keydown", (e) => { if (e.key === "Escape") this.close(); });
    }
    return root;
  }

  /** Draws the whole wizard; the map and, when open, the full list of the settings are the cell window's to draw into it. */
  paint() {
    const root = this.root();
    if (!root) return;
    root.innerHTML = this.html();
    root.hidden = false;
    if (this.step === 2) this.deps.settings.mountMap(this.deps.doc());
  }

  /** Draws again what an edit can change, and keeps what is being typed: the band, the rail, the main fields, the map's words and
   *  the foot — not the full list of the settings, whose own editor draws itself. */
  repaint() {
    const root = this.root(false);
    if (!root || !this.opened) return;
    const doc = this.deps.doc();
    const active = doc?.activeElement;
    const id = active?.id && root.contains?.(active) ? active.id : "";
    const at = id && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
    const swap = (sel, html) => { const el = root.querySelector?.(sel); if (el) el.outerHTML = html; };
    swap("[data-am-band]", this.bandHtml());
    swap(".am-rail", this.railHtml());
    swap("[data-am-foot]", this.footHtml());
    if (this.step === 0) {
      const rows = root.querySelector?.("[data-am-rows]");
      if (rows) rows.innerHTML = this.listHtml();
    }
    if (this.step === 2) {
      swap("[data-am-main]", this.mainHtml());
      const place = root.querySelector?.("[data-am-place]");
      if (place) place.innerHTML = this.placeHtml();
      this.deps.settings.mountMap(doc);
    }
    if (!id) return;
    const again = doc.getElementById?.(id);
    if (again && again !== active) {
      again.focus?.({ preventScroll: true });
      if (at && typeof again.setSelectionRange === "function") again.setSelectionRange(at[0], at[1]);
    }
  }

  // ── what the operator does ──────────────────────────────────────────────────────────────────────────────

  go(step) {
    const n = Math.max(0, Math.min(2, Number(step) || 0));
    if (n > 0 && !this.choice()) return false;
    this.step = n;
    this.paint();
    return true;
  }

  setJob(job) {
    if (!JOBS.includes(job)) return false;
    this.job = job;
    this.paint();
    return true;
  }

  toggleAbility(a) {
    if (!AddModel.ABILITIES.includes(a)) return false;
    if (this.abilities.has(a)) this.abilities.delete(a); else this.abilities.add(a);
    this.paint();
    return this.abilities.has(a);
  }

  setQuery(text) {
    this.query = String(text || "");
    this.repaint();
  }

  /** A model picked: the form picks it as its own list does — the runner made for it follows, its projector and draft come with it;
   *  its window is the form's, an empty one the trained window (AskedWindow); then the next question. */
  pick(value) {
    const choice = this.choice(value);
    if (!choice) return false;
    this.deps.pickModel(value);
    const llama = this.deps.llama(this.deps.runner());
    // "Where it computes" reads a form that pins no card as every card, and a new cell's form holds N_GPU_LAYERS 999: every
    // layer forced onto the cards, which the map draws as a split set by hand and warns about — the wizard opened its third step
    // on that warning (2026-10-26). What it shows is written, by the compute target's own rule ("auto", the cards' split), so
    // the map fits by its handles from the first look. A card or the processor chosen earlier is left as it is.
    const gpus = (this.node().gpus || []).filter((g) => g && g.index !== undefined).map((g) => Number(g.index));
    if (llama && gpus.length && !this.value("DEVICE").trim() && this.value("N_GPU_LAYERS").trim() !== "0") {
      this.deps.compute({ mode: "gpu", gpuIdx: gpus });
    }
    this.step = 1;
    this.paint();
    return true;
  }

  useRunner(id) {
    this.deps.chooseRunner(id);
    this.paint();
    return this.deps.runner();
  }

  /** A field written as typing would write it, the cache's type into both of its fields, where it computes through the compute
   *  target's own rule. */
  set(field, value) {
    if (field === "CACHE_TYPE") {
      this.deps.form.set("CACHE_TYPE_K", value);
      this.deps.form.set("CACHE_TYPE_V", value);
    } else if (field === "WHERE") {
      const all = (this.node().gpus || []).map((g) => Number(g.index));
      this.deps.compute(value === "cpu" ? { mode: "cpu" } : { mode: "gpu", gpuIdx: value === "all" ? all : [Number(value)] });
      this.deps.settings.sync?.(this.deps.doc());
    } else {
      this.deps.form.set(field, value);
    }
    // The runner's step is drawn whole (its projector and draft follow the model); the others keep what is typed.
    if (this.step === 1) this.paint(); else this.repaint();
    return true;
  }

  toggleAll() {
    this.allOpen = !this.allOpen;
    const box = this.root(false)?.querySelector?.("[data-am-all-box]");
    if (box) box.outerHTML = this.allHtml();
    return this.allOpen;
  }

  /** The full form: the dialog itself, with everything the wizard set, for what the wizard does not ask — the schedule, the
   *  command, every runner. The wizard steps aside. */
  full() {
    this.deps.settings.release(this.key);
    this.opened = false;
    const root = this.root(false);
    if (root) root.hidden = true;
    this.deps.form.show();
    return true;
  }

  /** What a new cell of `hostId` is saved with when it runs `file` on `runner` with `fields` written: the cell form filled for a new cell of
   *  that machine as this wizard fills it, without a window — for the launch builder's Start (machine-build.js), so that a launch built on a
   *  machine's page is saved as one made here, with the form's defaults and its companions; its checks are the form's too (remote-cells.js
   *  `cellConfigChecked`). Nothing is saved here: the Start's own save makes the cell. {config, cacheModels}, or null when the form is held by
   *  edits of another cell the operator keeps. */
  async formConfig({ hostId, file, runner, fields = {} }) {
    if (!hostId || !file || !runner) return null;
    const key = this.deps.newKey(String(hostId));
    if (!(await this.deps.form.mayFill(key))) return null;
    if (!this.deps.form.fill(key, { pickModel: true, hidden: true })) return null;
    this.deps.pickModel(file);
    this.deps.chooseRunner(runner);
    for (const [field, value] of Object.entries(fields || {})) this.deps.form.set(field, value);
    return { config: { ...this.deps.form.read() }, cacheModels: !!this.deps.form.checked("cacheModels") };
  }

  /** Create, and Create and start: the dialog's own Apply — its checks, its save, which makes the cell — and, asked for, the cell's own
   *  start, by the name the save gave it (CellForm.cellId). A save that names no cell is said, and nothing is started by a guess. */
  async create(start = false) {
    if (this.busy || !this.choice()) return false;
    this.busy = true;
    this.repaint();
    let saved = false;
    try {
      saved = !!(await this.deps.form.save({ confirmed: true }));
    } finally {
      this.busy = false;
    }
    if (!saved) {
      this.repaint();
      return false;
    }
    const made = String(this.deps.form.cellId() ?? "").trim();
    this.close();
    if (!start) return true;
    if (!made) {
      this.deps.notify(t("machinePlanNoCell"));
      return true;
    }
    await this.deps.start(made);
    return true;
  }

  onClick(e) {
    const target = e.target;
    const hit = (sel) => target?.closest?.(sel);
    if (hit("[data-am-close]")) return this.close();
    const step = hit("[data-am-step]");
    if (step) return step.disabled ? null : this.go(step.dataset.amStep);
    const job = hit("[data-am-job]");
    if (job) return this.setJob(job.dataset.amJob);
    const ability = hit("[data-am-ability]");
    if (ability) return this.toggleAbility(ability.dataset.amAbility);
    const row = hit("[data-am-pick]");
    if (row) return this.pick(row.dataset.amPick);
    const runner = hit("[data-am-runner]");
    if (runner) return this.useRunner(runner.dataset.amRunner);
    const seg = hit("[data-am-set]");
    if (seg) return this.set(seg.dataset.amSet, seg.dataset.amValue);
    const toggle = hit("[data-am-toggle]");
    if (toggle) return this.set(toggle.dataset.amToggle, toggle.getAttribute?.("aria-checked") === "true" ? "0" : "1");
    if (hit("[data-am-all]")) return this.toggleAll();
    if (hit("[data-am-full]")) return this.full();
    if (hit("[data-am-back]")) return this.go(this.step - 1);
    if (hit("[data-am-next]")) return this.go(this.step + 1);
    if (hit("[data-am-create-start]")) return this.create(true);
    if (hit("[data-am-create]")) return this.create(false);
    // A star of the full list changes the starred among the main fields: drawn once the editor has written it.
    if (hit("[data-cell-settings-star]")) {
      this.deps.later(() => this.repaint());
      return "star";
    }
    // A button of the map — fit by the handles, all or none of a card, the threads for the RAM — writes the form itself: the band,
    // the main fields and the foot are drawn again once it has. The band said "fits on the cards" beside a map that had just put two
    // layers in RAM (2026-10-26).
    if (hit("[data-cell-window-place] button")) {
      this.deps.later(() => this.repaint());
      return "map";
    }
    return null;
  }

  onInput(e) {
    const target = e.target;
    if (target?.closest?.("[data-am-query]")) return this.setQuery(target.value);
    const field = target?.closest?.("[data-am-field]");
    // Typed: written into the form at once, drawn when the field is left (onChange) — a field drawn again under the caret
    // would take the typing from it.
    if (field) return this.deps.form.set(field.dataset.amField, field.value);
    return null;
  }

  onChange(e) {
    const target = e.target;
    if (target?.closest?.("[data-am-mmproj]")) return this.set("MMPROJ_FILE", target.value);
    if (target?.closest?.("[data-am-field]")) {
      this.repaint();
      return true;
    }
    return null;
  }
}

export const ADD_MODEL = new AddModel();
