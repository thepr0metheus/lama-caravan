// The models on a machine's page, in two parts (the owner's choice М1, 2026-11-02: "at the bottom a list of all the models,
// row by row, with their likes and dislikes; a press on one shows the launches saved for it"; Н1 the same day: "we still have that block of
// cells for some reason. Move all that is useful into Models, and the cell rows there, and take nothing from them"; the same on 2026-11-05:
// "add a block under «What lies where» and above Models: it shows the row picked in Models and the Cell window and Start buttons there —
// Models keeps only the picking"; the place and the look, the owner's choice of 2026-11-06, variant А of the mockups: the block stands inside
// «What lies where», under its legend, and what its makers recommend is read on the row that is picked). So the page has a block that shows one
// model, and a list that picks which one.
//
// The block, the last part inside «What lies where», under its legend: what the picked model is, each of its cells on two lines — what it is,
// then what it holds or where it would go — with its own Window and Start or Stop, and the cells whose model has no row here to pick, named as
// the board names them; the button that makes a new cell from the model is at the end of the launch builder's rail (the owner's choice Б of
// 2026-11-08). With nothing picked the block is still there, and says so in words. It does
// not scroll, because it is not inside a pane that scrolls: a block inside the list would have moved away from under the lanes with every
// drawing of the board.
// The list: a row per model's folder — its repository, its work, the longest context it was trained for, its size, a 📦 per cell, the owner's
// mark — and nothing else, except what its makers said, which is read on the row that is picked: a press on a row picks the model the block
// shows, and a row that is not picked has nothing to say but its parts. The likes and dislikes stay on the row, because they are a fact about
// the model, not a thing to do with a cell.
// A press on a cell's row chooses it for the rack above, and its row then has a third line, with the plan; it can be dragged up there too
// (machine-plan.js), and a working one dropped back here stops. The block follows the chosen cell: it is where the chosen cell's row with its
// buttons is, so a choice always has a place to act from.
//
// Everything is drawn at once and shown or hidden in place: the board draws the page anew with every change, and the listeners of a
// cell's Start and Window are bound at that drawing, so a row between two drawings has them. What the owner chose — the filters,
// the words typed, the model picked — is held by MACHINE_MODELS, past every drawing. The list is shown in place; the block is drawn for one
// model, so a pick that moves it to another draws the page again (`show` says when).
//
// A cell is known by its cellId (MachineMap.idOf): its row, its chip, its note and its buttons are keyed by it, and it shows no port — a
// cell holds one only while it runs. MachineMap is machine-head.js's, which reads this module: it is asked at a drawing, never when the
// module is read.
import { CellNote } from "./cell-note.js";
import { CellContext } from "./card-rows.js";
import { MachineMap } from "./machine-head.js";
import { MACHINE_BUILD } from "./machine-build.js";
import { t } from "./i18n.js";
import { LibraryPath } from "./library-path.js";
import { ModelCopy } from "./model-copy.js";
import { ModelFacts } from "./model-facts.js";
import { JOBS, JOB_LABELS, JOB_MARKS } from "./model-jobs.js";
import { ModelRating } from "./model-rating.js";
import { Button, Pill } from "./ui-parts.js";
import { escapeHtml, formatCtxTokens } from "./utils.js";

/**
 * What the owner chose on the models, and the texts on them. `only` is a filter of FILTERS' ("" is all of them), `query` the words
 * typed, `job` the work it is narrowed to, `picked` the model the block shows ("" is nothing picked, which the block says in words).
 * Texts not read yet are null, and one that could not be read `unread`: neither says a model has no recommendation.
 */
export class MachineModelsChoice {
  /** The filters besides "all": what a row must be to stay. */
  static FILTERS = {
    cells: (line) => line.cells > 0,
    like: (line) => line.mark === "like",
  };

  constructor() {
    this.only = "";
    this.query = "";
    this.job = "";
    // The model the block shows. One field, because one model is shown: what a row of the list is pressed for is this, and the block
    // follows the chosen cell with it. An empty string is not a model with no name: it names that nothing is picked.
    this.picked = "";
    this.texts = null;
    // What each maker stated once, read from the program's table (`ModelDefaults`): a model not in it has nothing
    // stated once, which is not the same as a text not read yet.
    this.stated = null;
    this.unread = false;
    this.reading = null;
    this.bound = false;
    this.read = async () => null;
    this.redraw = () => {};
  }

  /** Whether what does `jobs` stays while the list is narrowed to `job`. */
  static does(jobs, job) {
    return !job || jobs.includes(job);
  }

  /** The one rule of whether a row stays: `line` says its name, its cells, its mark and its work; `job` is the work shown (jobOn). The picked
   *  row stays whatever the list is narrowed to: it is the row the block above is drawn for, and pressing it off would leave the block showing
   *  a model the list says is not picked. */
  keeps(line, job) {
    if (this.picked === line.name) return true;
    const words = this.query.trim().toLowerCase();
    const filter = MachineModelsChoice.FILTERS[this.only];
    return (!filter || filter(line)) && MachineModelsChoice.does(line.shownJobs, job) && (!words || String(line.name).toLowerCase().includes(words));
  }

  /** Whether a cell's own row stands, where the block shows it: while it is chosen, whatever its work. */
  static keepsCell(jobs, job, chosen) {
    return chosen || MachineModelsChoice.does(jobs, job);
  }

  /** Whether the cells with no row of their own stand: they are cells here, with no model to find by words or to mark, and each does
   *  its `jobs`. `chosen`: one of them is, and stands as any chosen cell does. */
  keepsRest(jobs, job, chosen = false) {
    return chosen || (!this.query.trim() && this.only !== "like" && jobs.some((own) => MachineModelsChoice.does(own, job)));
  }

  /** A row of the list pressed: the model the block shows, and stays shown until another is picked. A pick is not a switch — there is no way to
   *  have none picked once something is, and the state before the first pick is said in words, not drawn as an empty block. Says whether it changed. */
  pick(name) {
    const n = String(name || "");
    if (!n || n === this.picked) return false;
    this.picked = n;
    return true;
  }

  /** The block follows the chosen cell: `model` is the model that cell belongs to, named as the list names it, and where it has a row the block is
   *  drawn for it — a cell whose model has no row here keeps the block where it was, because its row stands among the cells with no model. */
  chose(model) {
    const m = String(model || "");
    if (m) this.picked = m;
  }

  /** A filter pressed; the chosen one again lets it go. */
  narrow(only) {
    this.only = this.only === only ? "" : String(only || "");
  }

  /** The list narrowed to one work, or widened again: the chosen work again lets it go. */
  narrowJob(job) {
    const j = String(job ?? "");
    this.job = j === this.job ? "" : j;
    return this.job;
  }

  /** The words of a list of works, as a row or a cell says them in an attribute. */
  static jobsSaid(said) {
    return String(said || "").split(" ").filter(Boolean);
  }

  /** What the rows of `root` say of themselves: enough to decide whether a row stays, and nothing more. Which row is picked is not something a row
   *  says of itself — it is the choice, and it has one place (`picked`). */
  static lineOf(row) {
    return { name: row.dataset.machineModel, cells: Number(row.dataset.machineModelCells) || 0, mark: row.dataset.machineModelMark || "",
             shownJobs: MachineModelsChoice.jobsSaid(row.dataset.machineModelJobs) };
  }

  /** The work the list is narrowed to: the chosen one, while a pill says it. One chosen on another machine, or whose last cell left, narrows
   *  nothing: no pill would be there to let it go. MachineMap.jobShown says the same at a drawing. */
  jobOn(root) {
    return [...(root?.querySelectorAll?.("[data-machine-job]") || [])].some((pill) => pill.dataset.machineJob === this.job) ? this.job : "";
  }

  /** The choice shown without a drawing of the board: the rows that stay, the row picked, the cells of other work, the filters pressed and
   *  how many each one holds. `model` is the model the chosen cell belongs to, named as the board's builder names it (`listed`), which is the same
   *  word a row's name is; a cell whose model has no row here moves nothing, because its row stands among the cells with no model.
   *  Says whether the block must be drawn again: it is drawn for one model, so a choice that moves it to another cannot be shown by hiding and
   *  pressing. The list can; the block cannot. */
  show(root, model = "") {
    const block = root?.querySelector?.('[data-t="machine-chosen"]');
    const drawn = String(block?.dataset?.tId || "");
    const rows = [...(root?.querySelectorAll?.("[data-machine-model]") || [])];
    if (model && rows.some((row) => row.dataset.machineModel === model)) this.chose(model);
    const job = this.jobOn(root);
    let shown = 0;
    for (const row of rows) {
      const line = MachineModelsChoice.lineOf(row);
      const keep = this.keeps(line, job);
      row.hidden = !keep;
      if (keep) shown += 1;
      const button = row.querySelector?.("[data-machine-model-choose]");
      button?.setAttribute?.("aria-pressed", String(this.picked === line.name));
    }
    const worksOf = (cell) => MachineModelsChoice.jobsSaid(cell.dataset.machineJobs);
    for (const cell of root?.querySelectorAll?.("[data-machine-jobs]") || []) {
      cell.hidden = !MachineModelsChoice.keepsCell(worksOf(cell), job, !!cell.classList?.contains?.("is-on"));
    }
    const rest = root?.querySelector?.("[data-machine-models-rest]");
    if (rest) rest.hidden = !this.keepsRest([...(rest.querySelectorAll?.("[data-machine-jobs]") || [])].map(worksOf), job, !!rest.querySelector?.(".machine-model-launch.is-on"));
    for (const pill of root?.querySelectorAll?.("[data-machine-job]") || []) pill.setAttribute?.("aria-pressed", String(pill.dataset.machineJob === job));
    const lines = rows.map(MachineModelsChoice.lineOf);
    for (const pill of root?.querySelectorAll?.("[data-machine-models-only]") || []) {
      const only = pill.dataset.machineModelsOnly;
      pill.setAttribute?.("aria-pressed", String(only === this.only));
      const filter = MachineModelsChoice.FILTERS[only];
      const count = pill.querySelector?.(".ui-count");
      if (count) count.textContent = String(filter ? lines.filter(filter).length : lines.length);
    }
    const none = root?.querySelector?.("[data-machine-models-none]");
    if (none) none.hidden = shown > 0 || !rows.length;
    return !!block && drawn !== this.picked;
  }

  /** A mark pressed on a model: its row says so at once, the filter that counts marks follows. */
  marked(root, model, rating) {
    for (const row of root?.querySelectorAll?.("[data-machine-model]") || []) {
      if (row.dataset.machineModel === model) row.dataset.machineModelMark = rating;
    }
    this.show(root);
  }

  /** The texts on the models read, once the page shows them and again when the row that is picked is drawn: they are written on another page. An answer that
   *  says nothing new draws nothing. A failure keeps what was read; with nothing read, it is said where the text would stand. */
  async readTexts() {
    this.reading ||= Promise.resolve().then(() => this.read()).finally(() => { this.reading = null; });
    let answer = null;
    try {
      answer = await this.reading;
    } catch {
      answer = null;
    }
    const params = answer?.params && typeof answer.params === "object" ? answer.params : null;
    const stated = answer?.defaults && typeof answer.defaults === "object" ? answer.defaults : null;
    const unread = !params && !this.texts;
    const same = (params ? JSON.stringify(params) === JSON.stringify(this.texts) : unread === this.unread)
      && JSON.stringify(stated) === JSON.stringify(this.stated);
    if (same) return false;
    this.texts = params;
    this.stated = stated;
    this.unread = unread;
    this.redraw();
    return true;
  }

  /** The first reading of the texts, when a machine's page is drawn. */
  readOnce() {
    if (this.texts || this.unread || this.reading) return null;
    return this.readTexts();
  }

  /** The list's listeners: `read` asks for the texts, `redraw` draws the page, `newCell(host, model)` opens the new-cell wizard. */
  bind(doc, { read = async () => null, redraw = () => {}, newCell = () => {} } = {}) {
    if (this.bound || !doc?.addEventListener) return;
    this.bound = true;
    this.read = read;
    this.redraw = redraw;
    doc.addEventListener("click", (e) => {
      const only = e.target?.closest?.("[data-machine-models-only]");
      if (only) {
        e.preventDefault?.();
        this.narrow(only.dataset.machineModelsOnly);
        if (this.show(doc)) this.redraw();
        return;
      }
      const pill = e.target?.closest?.("[data-machine-job]");
      if (pill) {
        e.preventDefault?.();
        this.narrowJob(pill.dataset.machineJob);
        if (this.show(doc)) this.redraw();
        return;
      }
      const made = e.target?.closest?.("[data-machine-model-new]");
      if (made) {
        e.preventDefault?.();
        if (!made.disabled) newCell(made.dataset.machineModelHost, { value: made.dataset.machineModelNew, query: made.dataset.machineModelName, job: made.dataset.machineModelJob });
        return;
      }
      const picked = e.target?.closest?.("[data-machine-model-choose]");
      if (!picked) return;
      e.preventDefault?.();
      if (!this.pick(picked.dataset.machineModelChoose)) return;
      // A row here only picks, and the block is drawn for one model: so a pick draws the page again, and what its makers recommend is read
      // for the model now picked.
      this.redraw();
      this.readTexts();
    });
    doc.addEventListener("input", (e) => {
      const box = e.target?.closest?.("[data-machine-models-find]");
      if (!box) return;
      this.query = String(box.value || "");
      // A filter, a work or the words cannot move the pick, so `show` says nothing to draw there; it is honoured all the same, so that the
      // one rule of what to draw is read in one place.
      if (this.show(doc)) this.redraw();
    });
  }
}

export const MACHINE_MODELS = new MachineModelsChoice();

/**
 * The list of one drawing: the rows, worked out of the library's rows (state.models, state.artifacts: the same the new-cell form offers),
 * the cells of the machine, and the marks.
 *
 * `map` is the page's MachineMap: what a cell says of itself and the buttons it acts with are its rules and the panel's own.
 */
export class MachineModels {
  /** What a launch sets, in the words of its flags: what tells two saved launches of one model apart at a glance. */
  static MORE = [["PARALLEL", "parallel"], ["BATCH_SIZE", "batch"], ["TEMPERATURE", "temp"], ["TOP_P", "top_p"], ["TOP_K", "top_k"], ["MIN_P", "min_p"]];
  /** A cell in a row's count, and how many of them the count's column holds (the owner, 2026-11-02: "don't write text, let there be emoji by
   *  the count, and if there are more than fit, an emoji and a count with a plus at the right"). */
  static CELL_MARK = "\u{1F4E6}";
  static MARKS_FIT = 4;

  /** `build` is the launch builder under the map (machine-build.js), taken as a param for the reason `choice` is: a snapshot draws one without
   *  writing to the one the page holds. `runners` is what the board's builder told of the engines (the registry's rows and what each takes),
   *  for the builder; null draws no builder. */
  constructor({ map, rows = [], artifacts = [], ratings = {}, reserving = false, choice = MACHINE_MODELS, build = MACHINE_BUILD, runners = null } = {}) {
    this.map = map;
    this.rows = rows || [];
    this.artifacts = artifacts || [];
    this.ratings = ratings || {};
    this.reserving = !!reserving;
    this.choice = choice;
    this.build = build;
    this.runners = runners;
  }

  static number(n) {
    return Number(n).toLocaleString("en-US");
  }

  /** The sizes of a model's builds as a figure: one, or the smallest to the largest. Null when no file of it is in the library. */
  static sizeWords(sizes) {
    const known = sizes.filter((gb) => Number(gb) > 0);
    if (!known.length) return null;
    const low = Math.min(...known);
    const high = Math.max(...known);
    const one = (gb) => Number(gb).toFixed(1);
    return low === high ? `${one(low)} GB` : `${one(low)}–${one(high)} GB`;
  }

  /** A row's count of cells, by value: a mark per cell; more than fit, one mark less and how many more. No cell is `none`, not a zero. */
  static cellMarks(cells) {
    const n = Math.max(0, Math.floor(Number(cells) || 0));
    if (!n) return { none: true, marks: "", more: "" };
    const shown = n > MachineModels.MARKS_FIT ? MachineModels.MARKS_FIT - 1 : n;
    return { none: false, marks: MachineModels.CELL_MARK.repeat(shown), more: n > shown ? `+${n - shown}` : "" };
  }

  /** A work in words: its mark and its label, as a pill and a row say it. */
  static jobWords(job) {
    return `${JOB_MARKS[job] || ""} ${t(JOB_LABELS[job])}`.trim();
  }

  /** What a launch sets of MORE, in order. */
  static moreOf(config) {
    return MachineModels.MORE.map(([field, word]) => [word, String(config?.[field] ?? "").trim()]).filter(([, value]) => value)
      .map(([word, value]) => `${word} ${value}`).join(" · ");
  }

  /** The models to list, each with its cells here: those with a cell first, then by name. A row never moves under a press: neither a mark
   *  nor being open sorts. A later part of a split model is no model of its own. A file that lies straight in the library is listed by its
   *  own name, and has no mark: marks are kept by a model's folder. `repo` is the first cell the list shows that names one: its author is
   *  not guessed. */
  lines() {
    const facts = ModelFacts.of({ models: this.rows }, this.artifacts);
    const models = new Map();
    const line = (name) => {
      if (!models.has(name)) models.set(name, { name, rated: false, repo: "", sizes: [], files: [], jobs: new Set(), launches: [], window: ModelFacts.blank() });
      return models.get(name);
    };
    const laterPart = (path) => (ModelCopy.part(path)?.index || 0) > 1;
    const rows = this.rows.filter((row) => row?.kind === "model" && !laterPart(row.path));
    for (const row of [...rows, ...this.artifacts.filter(Boolean)]) {
      const path = new LibraryPath(row.path);
      if (!path.listed()) continue;
      const model = line(path.listed());
      model.rated ||= !!path.model();
      model.sizes.push(row.sizeGb);
      model.files.push(row.path);
      facts.take(model.window, row.path);
      for (const job of facts.of(row.path)?.jobs || []) model.jobs.add(job);
    }
    for (const server of this.map.node.servers || []) {
      const cell = this.map.cells.get(MachineMap.idOf(server));
      if (!cell?.listed) continue;
      const model = line(cell.listed);
      model.rated ||= !!cell.model;
      model.launches.push(server);
      // What a cell's own model said: all there is of a model the library does not list.
      ModelFacts.told(model.window, { jobs: cell.jobs || [], window: ModelFacts.positive(cell.ctx?.max) });
      for (const job of cell.jobs || []) model.jobs.add(job);
    }
    // The cells of one model stand in the order this machine gave them, the order they were made: nothing sorts by phase. (Until
    // 2026-11-07 a model's default cell stood first; it is the launch builder's maker's set now, and not a cell.)
    return [...models.values()].map((model) => {
      const launches = model.launches;
      return { ...model, launches, cells: model.launches.length,
               // The repository is named by the first cell in the order the list shows them, so the line under the model's name and the
               // rows of its cells read one order, not two pictures of the same cells.
               repo: launches.map((server) => String(this.map.cells.get(MachineMap.idOf(server))?.repo || "").trim()).find((repo) => repo) || "",
               mark: ModelRating.of(this.ratings, model.name),
               shownJobs: JOBS.filter((job) => model.jobs.has(job)),
               chosen: launches.some((server) => this.map.chosen === MachineMap.idOf(server)) };
    })
      .sort((a, b) => Number(b.cells > 0) - Number(a.cells > 0) || a.name.localeCompare(b.name));
  }

  /** The works a cell does, as far as the vocabulary names them. */
  static jobsOf(cell) {
    return (cell?.jobs || []).filter((job) => JOB_LABELS[job]);
  }

  /** A cell of the model, on two lines between the chip of its name and its buttons (the owner's choice Н1, 2026-11-02): its runner, its
   *  build, its windows and what else it sets; what it holds or weighs, and what it does now or where it would go, which the live patch keeps
   *  current (MachineHeadLive). The dot says that too: machine.css reads it off the verdict's data-t-state, so there is no second copy of
   *  the state. The chip says the cell's own name, its cellId: the model names every cell of its block alike, and the chip is what tells two
   *  of them apart — a port did, until a cell held one only while it runs. A click anywhere on the row chooses the cell, as the chip does
   *  from the keyboard; its Window, Start and Stop are their own (MachineDrag.taken). The rows of the model picked stand in its block,
   *  `chosenHtml`; a cell with no model's row over it says its name and work as well (`named`). */
  launchHtml(server, job, { named = false } = {}) {
    const cellId = MachineMap.idOf(server);
    const id = escapeHtml(cellId);
    const cell = this.map.cells.get(cellId) || {};
    const verdict = this.map.benchVerdict(server);
    const more = MachineModels.moreOf(server.slotConfig);
    const on = this.map.chosen === cellId;
    const jobs = MachineModels.jobsOf(cell);
    const name = [String(cell.name || "").trim(), ...jobs.map((j) => MachineModels.jobWords(j))].filter(Boolean).join(" · ");
    return `<div class="machine-model-launch${on ? " is-on" : ""}" data-machine-pick="${id}" data-machine-jobs="${escapeHtml(jobs.join(" "))}" data-t="machine-model-launch" data-t-id="${id}"`
      + ` title="${escapeHtml(t("machineCellRowHint"))}"${MachineModelsChoice.keepsCell(jobs, job, on) ? "" : " hidden"}>`
      + `<button type="button" class="machine-model-port${on ? " is-on" : ""}" aria-pressed="${on}" data-machine-pick="${id}" data-t="machine-model-cell" data-t-id="${id}"`
      + ` title="${escapeHtml(t("machineBlockChoose", { cell: this.map.cellName(server) }))}"><span class="machine-model-dot" aria-hidden="true"></span>${id}</button>`
      + `<div class="machine-model-line">${named ? `<strong class="machine-model-cell-name">${escapeHtml(name)}</strong>` : ""}`
      + `<span class="machine-model-runner">${escapeHtml(String(cell.runner || ""))}</span>`
      + `<span class="machine-model-quant">${escapeHtml(String(cell.quant || ""))}</span>`
      + new CellContext(cell.ctx).html({ cls: "machine-model-ctx", name: "machine-model-ctx", id: cellId })
      + `<span class="machine-model-set" title="${escapeHtml(more)}">${escapeHtml(more)}</span></div>`
      + `<div class="machine-model-line"><span class="machine-bench-size" data-machine-bench-size="${id}">${escapeHtml(this.map.benchSize(server))}</span>`
      + `<span class="machine-bench-fit machine-bench-fit--${verdict.tone}" data-machine-bench-fit="${id}" data-t-state="${escapeHtml(verdict.state)}"`
      + `${verdict.state === "failed" && cell.reason ? ` title="${escapeHtml(String(cell.reason))}"` : ""}>${escapeHtml(verdict.words)}</span></div>`
      // The cell's note (cell-note.js), under its two lines; a cell with none has the ✎ that asks for one by its buttons. The question names
      // the cell as the page does.
      + CellNote.lineHtml(cellId, this.map.cellName(server))
      + `<span class="machine-model-acts" data-machine-own>${CellNote.addHtml(cellId, this.map.cellName(server))}${this.map.actionsHtml(server)}</span>`
      + `${this.map.choiceHtml(server)}</div>`;
  }

  /** What a model's makers recommend, as the owner keeps it on /models. Nothing when it says nothing, and a word when it could not be read. */
  saidHtml(name) {
    if (this.choice.unread) return `<p class="machine-model-said is-unread" data-t="machine-model-said" data-t-id="${escapeHtml(name)}" data-t-state="unread">${escapeHtml(t("machineModelsTextsUnread"))}</p>`;
    const texts = this.choice.texts;
    const said = texts && Object.prototype.hasOwnProperty.call(texts, name) ? String(texts[name] ?? "").trim() : "";
    if (!said) return "";
    return `<p class="machine-model-said" data-t="machine-model-said" data-t-id="${escapeHtml(name)}" data-t-state="said"><b>${escapeHtml(t("machineModelsMakers"))}</b> ${escapeHtml(said)}</p>`;
  }

  /** What the maker stated once — the numbers the launch builder offers as the model's own set (machine-build.js `makerSet`). A
   *  model the table does not name has nothing stated once: it is not a gap, and the row draws the prose instead (`saidHtml`). Each
   *  value names itself, so the source is named per field, not once for the row. */
  statedHtml(name) {
    const stated = this.choice.stated;
    if (!stated || typeof stated !== "object" || !Object.prototype.hasOwnProperty.call(stated, name)) return "";
    const fields = Object.entries(stated[name]);
    if (!fields.length) return "";
    return `<p class="machine-model-said" data-t="machine-model-stated" data-t-id="${escapeHtml(name)}" data-t-state="stated">`
      + `<b>${escapeHtml(t("machineModelsStatedOnce"))}</b> ${fields.map(([field, value]) => `${escapeHtml(field)} ${escapeHtml(String(value))}`).join(", ")}</p>`;
  }

  /** A new cell of the model: the wizard asks its usual questions about it, past the choice of a model when it has one build only. */
  newHtml(line) {
    const host = String(this.map.node.id || "");
    const one = line.files.length === 1 ? line.files[0] : "";
    return new Button({ kind: "plain", icon: "plus", text: t("machineModelsNew"), disabled: this.reserving || !line.files.length,
                        attrs: `data-machine-model-new="${escapeHtml(one)}" data-machine-model-host="${escapeHtml(host)}" data-machine-model-name="${escapeHtml(line.name)}"`
                          + ` data-machine-model-job="${escapeHtml(line.shownJobs[0] || "")}" data-t="machine-model-new" data-t-id="${escapeHtml(line.name)}"` }).html();
  }

  /** A row's count of cells: the marks, the words in its hover and for a screen reader. */
  static cellsHtml(cells) {
    const { none, marks, more } = MachineModels.cellMarks(cells);
    const words = escapeHtml(none ? t("machineModelsNoCell") : cells === 1 ? t("machineModelsOneCell") : t("machineModelsCells", { n: cells }));
    return `<span class="machine-model-cells${none ? " is-none" : ""}" role="img" title="${words}" aria-label="${words}">${none ? "—" : marks}${more ? `<i>${more}</i>` : ""}</span>`;
  }

  /** The longest context a model was trained for, on its row (the owner, 2026-11-02): what /models says of it, in the short figures and under the 🎓 of
   *  its cells' rows. */
  static contextHtml(line) {
    const { state, text, tip } = ModelFacts.windowSaid(line.window, formatCtxTokens);
    return `<span class="machine-model-context${state === "known" ? "" : " is-dim"}" data-t="machine-model-context" data-t-id="${escapeHtml(line.name)}" data-t-state="${state}"${tip ? ` title="${escapeHtml(tip)}"` : ""}>`
      + `${escapeHtml(state === "known" ? `🎓 ${text}` : text)}</span>`;
  }

  /** The repository a model comes from, in small print under its name: whose build it is (the owner, 2026-10-27: "in small print, ISTA-DASLab
   *  and Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF"). It may break after its "/" (a <wbr>, for a name with no hyphen): cut at its end, it lost the
   *  very part that told two builds apart. A model whose cells' paths name no repository has no such line. */
  static repoHtml(line) {
    return line.repo ? `<small class="machine-model-repo" data-t="machine-model-repo" data-t-id="${escapeHtml(line.name)}" title="${escapeHtml(line.repo)}">`
      + `${line.repo.split("/").map((part) => escapeHtml(part)).join("/<wbr>")}</small>` : "";
  }

  /** The parts a model says of itself: its name and its repository, its work, the longest context it was trained for, its size, its cells.
   *  Drawn once, for the row of the list and for the line in the block above, so the two cannot say two things about one model. The likes and
   *  dislikes are not here: they are a fact about the model and stay on the row of the list, where a press keeps them. */
  static partsHtml(line) {
    const jobs = escapeHtml(line.shownJobs.map((j) => MachineModels.jobWords(j)).join(", "));
    return `<span class="machine-model-title"><b class="machine-model-name">${escapeHtml(line.name)}</b>${MachineModels.repoHtml(line)}</span>`
      + `<span class="machine-model-job" title="${jobs}">${jobs}</span>${MachineModels.contextHtml(line)}`
      + `<span class="machine-model-sizes">${escapeHtml(MachineModels.sizeWords(line.sizes) ?? t("machineModelsNotHere"))}</span>${MachineModels.cellsHtml(line.cells)}`;
  }

  /** A row of the list: a press on it picks the model the block shows, and nothing else — its cells and their buttons are in the block, so a row
   *  here is no place to act. What the row says of itself is the same helper the block uses (`partsHtml`); the mark is the row's own. */
  rowHtml(line, job) {
    const id = escapeHtml(line.name);
    const picked = this.choice.picked === line.name;
    return `<div class="machine-model${line.cells ? "" : " is-idle"}" data-machine-model="${id}" data-machine-model-cells="${line.cells}" data-machine-model-mark="${escapeHtml(line.mark)}"`
      + ` data-machine-model-jobs="${escapeHtml(line.shownJobs.join(" "))}" data-t="machine-model" data-t-id="${id}" data-t-state="${line.cells ? "cells" : "none"}"${this.choice.keeps(line, job) ? "" : " hidden"}>`
      + `<div class="machine-model-row"><button type="button" class="machine-model-choose" aria-pressed="${picked}" data-machine-model-choose="${id}"`
      + ` data-t="machine-model-choose" data-t-id="${id}" title="${escapeHtml(t("machineModelsHint"))}">${MachineModels.partsHtml(line)}</button>`
      // A file with no folder has no mark to keep, and its empty place keeps the columns even.
      + `${line.rated ? ModelRating.buttonsHtml(line.name, line.mark, t, { cls: "machine-model-rate", hook: 'data-t="machine-model-rate"' }) : '<span class="machine-model-rate"></span>'}</div>`
      // What its makers keep is read on the row that is picked (the owner, 2026-11-06, variant А of the mockups): the block under the legend has
      // no room for nine lines of prose, and a row that is not picked has nothing to say but its parts. A row that is not picked draws no texts,
      // so the page never says the same model twice.
      + `${picked ? this.statedHtml(line.name) + this.saidHtml(line.name) : ""}</div>`;
  }

  /** The block under the legend of the map (the owner, 2026-11-05, and its place the owner's choice of 2026-11-06, variant А of the mockups): the
   *  model picked in the list, and what is done with it — each of its cells with its Window and Start or Stop, and the cells whose model has no
   *  row here to pick. A new cell from it is at the end of the launch builder's rail (`buildHtml`, the owner's choice Б of 2026-11-08). What its makers recommend is not here: it is read on the row that picked, so the block stays the short
   *  part of the map it is. With nothing picked it is still drawn, and says so in words; a model picked with no saved launch on this machine says
   *  that on its own line. The block is drawn for one model, so a pick draws the page again — `show` says when. */
  chosenHtml(lines, job) {
    const line = lines.find((l) => this.choice.picked === l.name);
    const id = escapeHtml(line?.name || "");
    const title = t("machineChosenTitle");
    const cells = line ? (line.launches.map((server) => this.launchHtml(server, job)).join("")
      || `<p class="machine-model-nolaunch">${escapeHtml(t("machineModelsNoLaunch"))}</p>`) : "";
    return `<section class="machine-chosen" aria-label="${escapeHtml(title)}" data-t="machine-chosen" data-t-id="${id}" data-t-state="${line ? "chosen" : "none"}">`
      + `<div class="machine-chosen-head"><strong class="machine-chosen-title">${escapeHtml(title)}</strong>`
      + `<span class="machine-chosen-hint">${escapeHtml(t("machineChosenHint"))}</span></div>`
      + (line ? `<div class="machine-chosen-line" data-t="machine-chosen-line" data-t-id="${id}">${MachineModels.partsHtml(line)}</div>`
        : `<p class="machine-chosen-none" data-t="machine-chosen-none" data-t-state="none">${escapeHtml(t("machineChosenNone"))}</p>`)
      // The picked model's own cells stand first; the cells of no model here come after them, under their own words.
      + `<div class="machine-chosen-cells" data-machine-chosen-cells data-t="machine-chosen-cells" data-t-id="${id}">${cells}${this.restHtml(job)}</div></section>`;
  }

  /** The cells this page has no row to pick for: a model named by its runner's own word or on a disk of the machine, an engine's, said as the
   *  board names them; a cell with no model yet, which says so itself. They have no row that a press could pick, so the block is the only place
   *  to choose one, to start it or to open its window — and the words that say why they have no row to pick name them there. */
  restHtml(job) {
    const servers = this.map.cellsMade().filter((server) => !this.map.cells.get(MachineMap.idOf(server))?.listed);
    if (!servers.length) return "";
    const names = servers.filter((server) => String(server.phase) !== "reserved").map((server) => this.map.cellName(server));
    const jobs = servers.map((server) => MachineModels.jobsOf(this.map.cells.get(MachineMap.idOf(server))));
    const chosen = servers.some((server) => this.map.chosen === MachineMap.idOf(server));
    return `<div class="machine-models-rest" data-machine-models-rest${this.choice.keepsRest(jobs, job, chosen) ? "" : " hidden"}>`
      + `${names.length ? `<p class="machine-models-none" data-t="machine-models-outside">${escapeHtml(t("machineModelsOutside", { cells: names.join(", ") }))}</p>` : ""}`
      + `${servers.map((server) => this.launchHtml(server, job, { named: true })).join("")}</div>`;
  }

  pillHtml(only, text, count) {
    return new Pill({ text, count: String(count), on: this.choice.only === only, attrs: `data-machine-models-only="${only}" data-t="machine-models-filter" data-t-id="${only || "all"}"` }).html();
  }

  /** The second row over the list: the works the machine's cells do, each with how many of them do it; a press narrows the list to it in
   *  place. None when no cell says what it does. */
  jobsHtml(job) {
    const pills = this.map.benchJobs().map(({ job: j, count }) => new Pill({
      text: MachineModels.jobWords(j), count: String(count), on: job === j,
      attrs: `data-machine-job="${escapeHtml(j)}" data-t="machine-models-job" data-t-id="${escapeHtml(j)}"` }).html()).join("");
    return pills ? `<div class="machine-models-jobs" role="group" aria-label="${escapeHtml(t("machineModelsJobs"))}">${pills}</div>` : "";
  }

  /** What the choice draws: the rows, and the work the list is narrowed to. Read once, so the block and the list cannot say two things about
   *  one pick. `show` reads the same rule on a page already drawn. */
  shown() {
    const lines = this.lines();
    // The block shows the model the chosen cell belongs to, when that model has a row here; a cell whose model has none keeps the block on
    // what was picked. One rule, in `chose`, read here and by `show`.
    this.choice.chose(lines.find((l) => l.chosen)?.name);
    return { lines, job: this.map.jobShown(this.choice.job) };
  }

  /** The block, as the map draws the place it stands in (MachineHead): the two are read together, so one cannot move the other. */
  blockHtml() {
    const { lines, job } = this.shown();
    return this.chosenHtml(lines, job);
  }

  /** The launch builder under the map (the owner, 2026-11-06: under «What lies where»), for the model picked: what it offers is read off the
   *  same rows the list and the block read, and the launch it builds is laid by the map — its places and, with a plan in hand, the plan's
   *  Start are the map's last line for that cell (`choiceHtml`), the line every cell of the block has. A new cell from the model, the wizard
   *  that asks its usual questions (`newHtml`), stands at the end of the rail while the launch is not whole (the owner's choice Б, 2026-11-08). */
  buildHtml() {
    const { lines } = this.shown();
    const line = lines.find((l) => l.name === this.choice.picked) || null;
    const launch = this.map.launch;
    return this.build.html(line, String(this.map.node.id ?? ""), { cells: this.map.cells, choice: launch ? this.map.choiceHtml(launch) : "",
                                                                  on: !!launch && this.map.chosen === MachineMap.idOf(launch), runners: this.runners,
                                                                  fresh: line ? this.newHtml(line) : "" });
  }

  /** The list: its title, the filters, the words typed, the pills of work, and a row per model. Nothing else is here — the cells of the model
   *  picked, and the cells with no row to pick, are in the block the map holds — so a row here is a thing to press, not a place to act. Its
   *  texts are the one thing a row keeps showing: they are read on the row that is picked. */
  listHtml() {
    const { lines, job } = this.shown();
    const title = t("machineModelsTitle");
    const count = (only) => lines.filter(MachineModelsChoice.FILTERS[only]).length;
    const shown = lines.some((line) => this.choice.keeps(line, job));
    const pills = this.pillHtml("", t("machineModelsAll"), lines.length) + this.pillHtml("cells", t("machineModelsWithCell"), count("cells"))
      + this.pillHtml("like", ModelRating.GLYPHS.like, count("like"));
    const rows = (keep) => lines.filter(keep).map((line) => this.rowHtml(line, job)).join("");
    return `<section class="machine-models" aria-label="${escapeHtml(title)}" data-t="machine-models" data-t-state="${lines.length ? "models" : "empty"}">`
      + `<div class="machine-models-top"><div class="machine-models-head"><strong class="machine-models-title">${escapeHtml(title)}</strong>`
      + `<div class="machine-models-filters" role="group">${pills}</div>`
      + `<span class="machine-models-hint">${escapeHtml(t("machineModelsHint"))}</span>`
      + `<input type="search" class="machine-models-find" data-machine-models-find data-t="machine-models-find" placeholder="${escapeHtml(t("machineModelsFind"))}"`
      + ` aria-label="${escapeHtml(t("machineModelsFind"))}" value="${escapeHtml(this.choice.query)}"></div>${this.jobsHtml(job)}</div>`
      + (lines.length ? `<div class="machine-models-list">${rows((line) => line.cells > 0)}${rows((line) => !line.cells)}</div>` : "")
      + (lines.length ? `<p class="machine-models-none" data-machine-models-none data-t="machine-models-none"${shown ? " hidden" : ""}>${escapeHtml(t("machineModelsNone"))}</p>`
        : `<p class="machine-models-empty">${escapeHtml(t("machineModelsEmpty"))}</p>`)
      + `</section>`;
  }
}
