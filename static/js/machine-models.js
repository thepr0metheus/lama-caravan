// The models on a machine's page, under its rack (the owner's choice М1, 2026-11-02: "at the bottom a list of all the models, row by
// row, with their likes and dislikes; a press on one shows the launches saved for it"; Н1 the same day: "we still have that block of
// cells for some reason. Move all that is useful into Models, and the cell rows there, and take nothing from them"). What the library
// holds and what this machine's cells run, a row per model's folder — its repository, its work, the longest context it was trained for,
// its size, a 📦 per cell here, the owner's mark — and, opened under its row, each cell of it on two lines: what it is, then what it holds
// or where it would go; its own Window and Start or Stop; what its makers recommend; a new cell from it. A click on a cell's row chooses it
// for the rack above, and its row then has a third line, with the plan; it can be dragged up there too (machine-plan.js).
//
// Everything is drawn at once and shown or hidden in place: the board draws the page anew with every change, and the listeners of a
// cell's Start and Window are bound at that drawing, so a row opened between two drawings has them. What the owner chose — the filters,
// the words typed, the rows he pressed — is held by MACHINE_MODELS, past every drawing.
import { CellNote } from "./cell-note.js";
import { CellContext } from "./card-rows.js";
import { t } from "./i18n.js";
import { LibraryPath } from "./library-path.js";
import { ModelCopy } from "./model-copy.js";
import { ModelFacts } from "./model-facts.js";
import { JOBS, JOB_LABELS, JOB_MARKS } from "./model-jobs.js";
import { ModelRating } from "./model-rating.js";
import { Button, Pill } from "./ui-parts.js";
import { escapeHtml, formatCtxTokens } from "./utils.js";

/**
 * What the owner chose in the list, and the texts on the models. `only` is a filter of FILTERS' ("" is all of them), `query` the words
 * typed, `job` the work it is narrowed to, `pressed` what he pressed on each model's row: open or closed. Texts not read yet are null,
 * and one that could not be read `unread`: neither says a model has no recommendation.
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
    this.pressed = new Map();
    this.chosenPort = "";
    this.texts = null;
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

  /** The one rule of whether a row stays: `line` says its name, its cells, its mark and its work; `job` is the work shown (jobOn). The row of the
   *  chosen cell stays whatever the list is narrowed to: it is where that cell says what it does and has its buttons. */
  keeps(line, job) {
    if (line.chosen) return true;
    const words = this.query.trim().toLowerCase();
    const filter = MachineModelsChoice.FILTERS[this.only];
    return (!filter || filter(line)) && MachineModelsChoice.does(line.shownJobs, job) && (!words || String(line.name).toLowerCase().includes(words));
  }

  /** Whether a cell's own row stands, in a row that does: while it is chosen, whatever its work. */
  static keepsCell(jobs, job, chosen) {
    return chosen || MachineModelsChoice.does(jobs, job);
  }

  /** Whether the cells with no row of their own stand: they are cells here, with no model to find by words or to mark, and each does
   *  its `jobs`. `chosen`: one of them is, and stands as any chosen cell does. */
  keepsRest(jobs, job, chosen = false) {
    return chosen || (!this.query.trim() && this.only !== "like" && jobs.some((own) => MachineModelsChoice.does(own, job)));
  }

  /** The cell chosen now, and the model it belongs to if it has a row. A new choice opens that row, whatever was pressed on it before: closed, it
   *  would hide what the choice is for. It can be pressed closed again, and stays so while this cell stays chosen. */
  chose(port, name) {
    const now = String(port || "");
    if (now === this.chosenPort) return;
    this.chosenPort = now;
    if (name) this.pressed.delete(String(name));
  }

  /** Whether a row stands open: as it was pressed; with no press, while a cell of it works or is on its way, or is the chosen one. */
  opens(line) {
    return this.pressed.has(line.name) ? this.pressed.get(line.name) : !!(line.works || line.chosen);
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

  /** A row pressed: it turns from what it shows, and stays so whatever its cells do. Says whether it is open now. */
  press(name, wasOpen) {
    this.pressed.set(String(name), !wasOpen);
    return !wasOpen;
  }

  /** The words of a list of works, as a row or a cell says them in an attribute. */
  static jobsSaid(said) {
    return String(said || "").split(" ").filter(Boolean);
  }

  /** What the rows of `root` say of themselves. */
  static lineOf(row) {
    return { name: row.dataset.machineModel, cells: Number(row.dataset.machineModelCells) || 0, mark: row.dataset.machineModelMark || "",
             shownJobs: MachineModelsChoice.jobsSaid(row.dataset.machineModelJobs), works: row.dataset.machineModelWorks === "1",
             chosen: !!row.querySelector?.(".machine-model-launch.is-on") };
  }

  /** The work the list is narrowed to: the chosen one, while a pill says it. One chosen on another machine, or whose last cell left, narrows
   *  nothing: no pill would be there to let it go. MachineMap.jobShown says the same at a drawing. */
  jobOn(root) {
    return [...(root?.querySelectorAll?.("[data-machine-job]") || [])].some((pill) => pill.dataset.machineJob === this.job) ? this.job : "";
  }

  /** The choice shown without a drawing of the board: the rows that stay, the rows open, the cells of other work, the filters pressed and
   *  how many each one holds. */
  show(root) {
    const chosen = root?.querySelector?.(".machine-model-launch.is-on");
    this.chose(chosen?.dataset?.machinePick, chosen?.closest?.("[data-machine-model]")?.dataset?.machineModel);
    const rows = [...(root?.querySelectorAll?.("[data-machine-model]") || [])];
    const job = this.jobOn(root);
    let shown = 0;
    for (const row of rows) {
      const line = MachineModelsChoice.lineOf(row);
      const keep = this.keeps(line, job);
      row.hidden = !keep;
      if (keep) shown += 1;
      const on = keep && this.opens(line);
      row.classList?.toggle?.("is-open", on);
      const button = row.querySelector?.("[data-machine-model-open]");
      button?.setAttribute?.("aria-expanded", String(on));
      const more = row.querySelector?.("[data-machine-model-more]");
      if (more) more.hidden = !on;
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
  }

  /** A mark pressed on a model: its row says so at once, the filter that counts marks follows. */
  marked(root, model, rating) {
    for (const row of root?.querySelectorAll?.("[data-machine-model]") || []) {
      if (row.dataset.machineModel === model) row.dataset.machineModelMark = rating;
    }
    this.show(root);
  }

  /** The texts on the models read, once the page shows them and again as a row opens: they are written on another page. An answer that
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
    const unread = !params && !this.texts;
    if (params ? JSON.stringify(params) === JSON.stringify(this.texts) : unread === this.unread) return false;
    this.texts = params;
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
        this.show(doc);
        return;
      }
      const pill = e.target?.closest?.("[data-machine-job]");
      if (pill) {
        e.preventDefault?.();
        this.narrowJob(pill.dataset.machineJob);
        this.show(doc);
        return;
      }
      const made = e.target?.closest?.("[data-machine-model-new]");
      if (made) {
        e.preventDefault?.();
        if (!made.disabled) newCell(made.dataset.machineModelHost, { value: made.dataset.machineModelNew, query: made.dataset.machineModelName, job: made.dataset.machineModelJob });
        return;
      }
      const opener = e.target?.closest?.("[data-machine-model-open]");
      if (!opener) return;
      e.preventDefault?.();
      if (this.press(opener.dataset.machineModelOpen, opener.getAttribute?.("aria-expanded") === "true")) this.readTexts();
      this.show(doc);
    });
    doc.addEventListener("input", (e) => {
      const box = e.target?.closest?.("[data-machine-models-find]");
      if (!box) return;
      this.query = String(box.value || "");
      this.show(doc);
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

  constructor({ map, rows = [], artifacts = [], ratings = {}, reserving = false, choice = MACHINE_MODELS } = {}) {
    this.map = map;
    this.rows = rows || [];
    this.artifacts = artifacts || [];
    this.ratings = ratings || {};
    this.reserving = !!reserving;
    this.choice = choice;
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
   *  own name, and has no mark: marks are kept by a model's folder. `repo` is the first cell's that names one: its author is not guessed. */
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
      const cell = this.map.cells.get(String(server.port));
      if (!cell?.listed) continue;
      const model = line(cell.listed);
      model.rated ||= !!cell.model;
      model.launches.push(server);
      model.repo ||= String(cell.repo || "").trim();
      // What a cell's own model said: all there is of a model the library does not list.
      ModelFacts.told(model.window, { jobs: cell.jobs || [], window: ModelFacts.positive(cell.ctx?.max) });
      for (const job of cell.jobs || []) model.jobs.add(job);
    }
    return [...models.values()].map((model) => ({ ...model, cells: model.launches.length, mark: ModelRating.of(this.ratings, model.name),
                                                  shownJobs: JOBS.filter((job) => model.jobs.has(job)),
                                                  works: model.launches.some((server) => this.map.works(server)),
                                                  chosen: model.launches.some((server) => this.map.chosen === String(server.port)) }))
      .sort((a, b) => Number(b.cells > 0) - Number(a.cells > 0) || a.name.localeCompare(b.name));
  }

  /** The works a cell does, as far as the vocabulary names them. */
  static jobsOf(cell) {
    return (cell?.jobs || []).filter((job) => JOB_LABELS[job]);
  }

  /** A cell of the model, on two lines between its port and its buttons (the owner's choice Н1, 2026-11-02): its runner, its build, its
   *  windows and what else it sets; what it holds or weighs, and what it does now or where it would go, which the live patch keeps current
   *  (MachineHeadLive). The dot says that too: machine.css reads it off the verdict's data-t-state, so there is no second copy of the
   *  state. A click anywhere on it chooses the cell, as the port does from the keyboard; its Window, Start and Stop are their own
   *  (MachineDrag.taken). A cell with no model's row over it says its name and work as well (`named`). */
  launchHtml(server, job, { named = false } = {}) {
    const port = String(server.port);
    const id = escapeHtml(port);
    const hostId = String(this.map.node?.id ?? "");
    const cell = this.map.cells.get(port) || {};
    const verdict = this.map.benchVerdict(server);
    const more = MachineModels.moreOf(server.slotConfig);
    const on = this.map.chosen === port;
    const jobs = MachineModels.jobsOf(cell);
    const name = [String(cell.name || "").trim(), ...jobs.map((j) => MachineModels.jobWords(j))].filter(Boolean).join(" · ");
    return `<div class="machine-model-launch${on ? " is-on" : ""}" data-machine-pick="${id}" data-machine-jobs="${escapeHtml(jobs.join(" "))}" data-t="machine-model-launch" data-t-id="${id}"`
      + ` title="${escapeHtml(t("machineModelsHint"))}"${MachineModelsChoice.keepsCell(jobs, job, on) ? "" : " hidden"}>`
      + `<button type="button" class="machine-model-port${on ? " is-on" : ""}" aria-pressed="${on}" data-machine-pick="${id}" data-t="machine-model-cell" data-t-id="${id}"`
      + ` title="${escapeHtml(t("machineBlockChoose", { cell: this.map.cellName(server) }))}"><span class="machine-model-dot" aria-hidden="true"></span>:${id}</button>`
      + `<div class="machine-model-line">${named ? `<strong class="machine-model-cell-name">${escapeHtml(name)}</strong>` : ""}`
      + `<span class="machine-model-runner">${escapeHtml(String(cell.runner || ""))}</span>`
      + `<span class="machine-model-quant">${escapeHtml(String(cell.quant || ""))}</span>`
      + new CellContext(cell.ctx).html({ cls: "machine-model-ctx", name: "machine-model-ctx", id: port })
      + `<span class="machine-model-set" title="${escapeHtml(more)}">${escapeHtml(more)}</span></div>`
      + `<div class="machine-model-line"><span class="machine-bench-size" data-machine-bench-size="${id}">${escapeHtml(this.map.benchSize(server))}</span>`
      + `<span class="machine-bench-fit machine-bench-fit--${verdict.tone}" data-machine-bench-fit="${id}" data-t-state="${escapeHtml(verdict.state)}"`
      + `${verdict.state === "failed" && cell.reason ? ` title="${escapeHtml(String(cell.reason))}"` : ""}>${escapeHtml(verdict.words)}</span></div>`
      // The cell's note (cell-note.js), under its two lines; a cell with none has the ✎ that asks for one by its buttons.
      + CellNote.lineHtml(hostId, port)
      + `<span class="machine-model-acts" data-machine-own>${CellNote.addHtml(hostId, port)}${this.map.actionsHtml(server)}</span>${this.map.choiceHtml(server)}`
      + `</div>`;
  }

  /** What a model's makers recommend, as the owner keeps it on /models. Nothing when it says nothing, and a word when it could not be read. */
  saidHtml(name) {
    if (this.choice.unread) return `<p class="machine-model-said is-unread" data-t="machine-model-said" data-t-id="${escapeHtml(name)}" data-t-state="unread">${escapeHtml(t("machineModelsTextsUnread"))}</p>`;
    const texts = this.choice.texts;
    const said = texts && Object.prototype.hasOwnProperty.call(texts, name) ? String(texts[name] ?? "").trim() : "";
    if (!said) return "";
    return `<p class="machine-model-said" data-t="machine-model-said" data-t-id="${escapeHtml(name)}" data-t-state="said"><b>${escapeHtml(t("machineModelsMakers"))}</b> ${escapeHtml(said)}</p>`;
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

  rowHtml(line, job) {
    const id = escapeHtml(line.name);
    const keep = this.choice.keeps(line, job);
    const open = keep && this.choice.opens(line);
    const size = MachineModels.sizeWords(line.sizes);
    const jobs = escapeHtml(line.shownJobs.map((j) => MachineModels.jobWords(j)).join(", "));
    const launches = line.launches.map((server) => this.launchHtml(server, job)).join("")
      || `<p class="machine-model-nolaunch">${escapeHtml(t("machineModelsNoLaunch"))}</p>`;
    return `<div class="machine-model${open ? " is-open" : ""}${line.cells ? "" : " is-idle"}" data-machine-model="${id}" data-machine-model-cells="${line.cells}" data-machine-model-mark="${escapeHtml(line.mark)}"`
      + ` data-machine-model-jobs="${escapeHtml(line.shownJobs.join(" "))}" data-machine-model-works="${line.works ? 1 : 0}"`
      + ` data-t="machine-model" data-t-id="${id}" data-t-state="${line.cells ? "cells" : "none"}"${keep ? "" : " hidden"}>`
      + `<div class="machine-model-row"><button type="button" class="machine-model-open" aria-expanded="${open}" data-machine-model-open="${id}" data-t="machine-model-open" data-t-id="${id}">`
      + `<span class="machine-model-title"><b class="machine-model-name">${id}</b>${MachineModels.repoHtml(line)}</span>`
      + `<span class="machine-model-job" title="${jobs}">${jobs}</span>${MachineModels.contextHtml(line)}`
      + `<span class="machine-model-sizes">${escapeHtml(size ?? t("machineModelsNotHere"))}</span>${MachineModels.cellsHtml(line.cells)}</button>`
      // A file with no folder has no mark to keep, and its empty place keeps the columns even.
      + `${line.rated ? ModelRating.buttonsHtml(line.name, line.mark, t, { cls: "machine-model-rate", hook: 'data-t="machine-model-rate"' }) : '<span class="machine-model-rate"></span>'}</div>`
      + `<div class="machine-model-more" data-machine-model-more data-t="machine-model-more" data-t-id="${id}"${open ? "" : " hidden"}>${launches}${this.saidHtml(line.name)}`
      + `<div class="machine-model-foot">${this.newHtml(line)}</div></div></div>`;
  }

  /** The cells this list has no row for: a model named by its runner's own word or on a disk of the machine, an engine's, said by their ports;
   *  a port with no model yet, whose cell says so itself. They have no block while they stand, so here is the only place to choose one, to
   *  start it or to open its window. */
  restHtml(job) {
    const servers = (this.map.node.servers || []).filter((server) => !this.map.cells.get(String(server.port))?.listed);
    if (!servers.length) return "";
    const ports = servers.filter((server) => String(server.phase) !== "reserved").map((server) => `:${server.port}`);
    const jobs = servers.map((server) => MachineModels.jobsOf(this.map.cells.get(String(server.port))));
    const chosen = servers.some((server) => this.map.chosen === String(server.port));
    return `<div class="machine-models-rest" data-machine-models-rest${this.choice.keepsRest(jobs, job, chosen) ? "" : " hidden"}>`
      + `${ports.length ? `<p class="machine-models-none" data-t="machine-models-outside">${escapeHtml(t("machineModelsOutside", { cells: ports.join(", ") }))}</p>` : ""}`
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

  html() {
    const lines = this.lines();
    this.choice.chose(this.map.chosen, lines.find((line) => line.chosen)?.name);
    const job = this.map.jobShown(this.choice.job);
    const title = t("machineModelsTitle");
    const count = (only) => lines.filter(MachineModelsChoice.FILTERS[only]).length;
    const shown = lines.some((line) => this.choice.keeps(line, job));
    const pills = this.pillHtml("", t("machineModelsAll"), lines.length) + this.pillHtml("cells", t("machineModelsWithCell"), count("cells"))
      + this.pillHtml("like", ModelRating.GLYPHS.like, count("like"));
    const rows = (keep) => lines.filter(keep).map((line) => this.rowHtml(line, job)).join("");
    const rest = this.restHtml(job);
    return `<section class="machine-models" aria-label="${escapeHtml(title)}" data-t="machine-models" data-t-state="${lines.length ? "models" : "empty"}">`
      + `<div class="machine-models-top"><div class="machine-models-head"><strong class="machine-models-title">${escapeHtml(title)}</strong>`
      + `<div class="machine-models-filters" role="group">${pills}</div>`
      + `<span class="machine-models-hint">${escapeHtml(t("machineModelsHint"))}</span>`
      + `<input type="search" class="machine-models-find" data-machine-models-find data-t="machine-models-find" placeholder="${escapeHtml(t("machineModelsFind"))}"`
      + ` aria-label="${escapeHtml(t("machineModelsFind"))}" value="${escapeHtml(this.choice.query)}"></div>${this.jobsHtml(job)}</div>`
      // The cells with no row stand among those with a cell, before the models with none: on a long list, the bottom is far.
      + (lines.length || rest ? `<div class="machine-models-list">${rows((line) => line.cells > 0)}${rest}${rows((line) => !line.cells)}</div>` : "")
      + (lines.length ? `<p class="machine-models-none" data-machine-models-none data-t="machine-models-none"${shown ? " hidden" : ""}>${escapeHtml(t("machineModelsNone"))}</p>`
        : `<p class="machine-models-empty">${escapeHtml(t("machineModelsEmpty"))}</p>`)
      + `</section>`;
  }
}
