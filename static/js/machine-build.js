// The machine page's launch builder (the owner, 2026-11-06: «ниже "What lies where" будем как бы собирать запуск»), in the look of variant
// А «Ступени и рельс» of the shelf's mockups (the owner, 2026-11-07: «не показывать бы их сразу три, а сначала "движок" и список,
// свайпаемый вправо… потом в этой же строке список квантов… чтобы органично и удобно пальцем или мышью перетаскивать»), laid out again in
// two rows by the owner's variant Б of 2026-11-08 (Papyrus caravan-machine-page-room): the launch is one rail of three places on top, and
// its places are the steps — the engine (a turbine), the carrier · quant (a cartridge), the setting · parameters (sliders); under the rail
// one shelf shows the cards of the step chosen and is swiped sideways. A card is carried up into its place, or pressed, and the shelf moves on
// to the next step. Once an engine and a quant stand there the rail is the strip, carried further up onto the map as a stopped cell is
// («эту сборную строку — чтобы её вверх можно было на видеокарты и место тащить»); until then the rail's end says what it is and gives the
// new-cell wizard for the model, the button the block of the model picked had.
//
// The builder decides nothing a cell decides. Which engine takes which file is `runnerAvailability`, the rule the runner tabs and the
// new-cell wizard answer with, told here by the board's builder with the registry (topology-nodes.js machineHeadOf, `runners`) as it
// tells the head every cell's facts; which engines are offered at all is the wizard's rule too (runner-offer.js). The strip is a cell
// that is not made yet: it has no cellId and no port — a cell is named when it is made and holds a port only while it runs — so it stands
// on the map under the builder's own key (`KEY`), with the facts the board's builder gives every stopped cell (topology-nodes.js
// `LaunchFacts`), and the map's own drag, places, plan, ghost and Start lay it as they lay any cell — nothing of the placement is worked
// out twice. Start makes the cell the way the wizard makes one: the cell form filled for a new cell of the machine (add-model.js
// `formConfig`), checked as the form checks its own, saved with the plan's fields — the save makes the cell and names it — and started by
// that name (machine-plan.js `MachinePlanStart`).
//
// The step of settings offers first what the model's maker stated once (`ModelDefaults`, read with the sets as `makers`): the preset a
// model's default cell became on 2026-11-07 (Papyrus `caravan-scout-port-lease`, step 1) — the maker's numbers with no cell and no port
// until a launch of them is started.
//
// What is not there is said in words, never drawn as a card: no model picked, no engine for its files, no file, no saved set, the
// sets not read. A card that does not go with what is picked is dim and says why; the owner's mark that an engine is not for this
// model only warns (the owner's answer: «Предупреждать», «Только в сборке»).
import { modelFields } from "./constants.js";
import { t } from "./i18n.js";
import { LibraryPath } from "./library-path.js";
import { CellFit, MachineMap } from "./machine-head.js";
import { MACHINE_PLAN } from "./machine-plan.js";
import { cellRunnerId } from "./model-jobs.js";
import { RunnerOffer } from "./runner-offer.js";
import { escapeHtml } from "./utils.js";

/** The mockups' three marks (var/mockups/launch-turbine-variants.html, the owner's «турбина — движок, картридж — квант, ползунки —
 *  сохранённые параметры»), drawn in the line's colour. */
const ICONS = {
  engine: '<circle cx="23" cy="24" r="15"/><circle cx="23" cy="24" r="4"/><path d="M23 9c7 4 8 9 3 12M38 24c-4 7-9 8-12 3M23 39c-7-4-8-9-3-12M8 24c4-7 9-8 12-3M39 18h4v12h-4"/>',
  quant: '<path d="M9 8h30v29H9zM13 8v8h22V8M14 37v4h20v-4M16 21h16M16 25h12M17 40v-3m5 3v-3m5 3v-3m5 3v-3"/>',
  params: '<rect x="6" y="7" width="36" height="34" rx="5"/><path d="M15 13v22m9-22v22m9-22v22"/><rect x="12" y="18" width="6" height="5" rx="1"/>'
    + '<rect x="21" y="26" width="6" height="5" rx="1"/><rect x="30" y="16" width="6" height="5" rx="1"/>',
};

export class MachineBuild {
  /** The key the launch stands under on the map, in its plan and in what the board's builder says of it (topology-nodes.js `LaunchFacts`),
   *  while it is no cell: not a cellId — one is `c` and digits — and never sent to the controller, which names the cell its Start makes. */
  static KEY = "new";

  /** The three steps, in the order they are taken: what runs it, which file, which settings. */
  static COLUMNS = ["engine", "quant", "params"];

  /** The words of each step, and of its place when nothing stands there. */
  static TITLES = { engine: "machineBuildEngine", quant: "machineBuildQuant", params: "machineBuildParams" };
  static EMPTY = { engine: "machineBuildNoEngine", quant: "machineBuildNoQuant", params: "machineBuildNoParams" };

  /** Fields a set taken from a cell never carries beside the files of its model (constants.js `modelFields`: the quant picks the file, and
   *  the form takes its companions with it) and the map's own (CellFit.FIELDS): the engine, which is the engine step's; what names the
   *  cell and where it answers — two cells by one name would be one model twice to a client, and a port is its scout's to lease at a start;
   *  and which card leads and how the layers are cut, which are where it lies. The strip is laid by the map, and a place copied from another
   *  cell would be a placement nobody chose. */
  static NOT_A_SETTING = ["RUNNER", "CELL_KIND", "MODEL_NAME", "PORT", "ALIAS", "API_PREFIX", "MAIN_GPU", "SPLIT_MODE"];

  /** Whether a field of a cell's config is a setting another launch may take (`NOT_A_SETTING`). Asked at a press, not when the module is
   *  read: CellFit is machine-head.js's, which reads this module. */
  static setting(key) {
    return !MachineBuild.NOT_A_SETTING.includes(key) && !modelFields.includes(key) && !CellFit.FIELDS.includes(key);
  }

  /** How far a press may move and still be a press, px. */
  static SLOP = 5;

  /** What a press that moves does on the shelf, by its first move past the slop: up or down (as much as sideways or more) it carries the
   *  card towards the launch; sideways a mouse drags the shelf, and a finger is the browser's own scroll — the shelf lets only that through
   *  (machine.css `touch-action: pan-x`), so a finger that swipes never picks a card up. "carry", "scroll" or "" (nothing of the builder's). */
  static gesture(dx, dy, mouse) {
    if (Math.abs(dy) >= Math.abs(dx)) return "carry";
    return mouse ? "scroll" : "";
  }

  /** Which ends of the shelf have cards out of sight, by the track's scroll: an edge fades and an arrow stands there. */
  static ends({ scrollLeft = 0, clientWidth = 0, scrollWidth = 0 } = {}) {
    const from = Number(scrollLeft) || 0;
    return { back: from > 1, more: from + (Number(clientWidth) || 0) < (Number(scrollWidth) || 0) - 1 };
  }

  constructor() {
    this.reset();
    // What the controller keeps (GET /api/runner-presets): read once a page, kept as it came. `read` is "", "asking", "read" or
    // "failed", so the shelf of settings says which absence it is.
    this.presets = {};
    this.warnings = {};
    // What each model's maker stated once, by the model's folder: the program's own table, read with the sets.
    this.makers = {};
    this.unread = 0;
    this.read = "";
    this.bound = false;
    this.carry = null;
    // The step the last drawing showed, so that the cards of a new step come in once and a drawing of the same step does not move them.
    this.shown = "";
    // What the last drawing showed — the model's line, the board's word on each cell, and the engines it was told (`runners`: the
    // registry's rows and `takes(row, file)`) — so that a press acts on the cards it was pressed on, not on a list worked out again since.
    this.drawn = { line: null, cells: new Map(), runners: null };
    // What `bind` gives: the page's ways to read, to choose, to draw, and its plan.
    this.doc = null;
    this.ask = async () => null;
    this.choose = () => {};
    this.redraw = () => {};
    this.plan = null;
  }

  /** Nothing picked: the model's three places empty, no strip, the shelf on the first step. `held` keeps each card as it was picked — its
   *  name, its file, its fields — so the launch is read from what was chosen, not worked out again from a list that may have moved since. */
  reset() {
    this.model = "";
    this.host = "";
    this.picked = { engine: "", quant: "", params: "" };
    this.held = { engine: null, quant: null, params: null };
    this.step = "engine";
    // Where the shelf was swiped to, so that the board drawn again under the operator's finger does not swipe it back; another model's
    // shelf, or a launch begun again, starts from its beginning.
    this.shelf = { step: "", left: 0 };
  }

  /** The step the shelf goes to once a card is put: the first of the engine and the quant still missing, else the settings — which a launch
   *  may go without, so the shelf stays there with them. */
  nextStep() {
    return ["engine", "quant"].find((kind) => !this.picked[kind]) || "params";
  }

  // ── what each step offers ────────────────────────────────────────────────────────────────────────────

  /** The registry's row of a runner, as the drawing was told it. */
  row(id) {
    return (this.drawn.runners?.rows || []).find((r) => r.id === id) || null;
  }

  /** Whether runner `row` takes `file`: {ok, reasonKey}, the rule the drawing was told. */
  takes(row, file) {
    return this.drawn.runners.takes(row, file);
  }

  /** The engines offered for the model: those the wizard offers (RunnerOffer) that take at least one of its files. Each says whether it
   *  takes the quant picked (`ok`), why not (`why`), and the owner's mark that it is not for this model (`unwanted`). */
  engines() {
    const line = this.drawn.line;
    const files = line?.files || [];
    return (this.drawn.runners?.rows || []).filter((row) => RunnerOffer.offered(row) && files.some((file) => this.takes(row, file).ok)).map((row) => {
      const takes = this.picked.quant ? this.takes(row, this.picked.quant) : { ok: true };
      return { kind: "engine", key: row.id, name: t(row.labelKey || row.id), mark: String(row.icon || ""), ok: takes.ok,
               why: takes.ok ? "" : t(takes.reasonKey || "machineBuildCannotRun"), unwanted: !!this.warnings?.[line.name]?.[row.id] };
    });
  }

  /** The model's files, each by its quant and what it weighs; one the picked engine does not take is dim and says why. */
  quants() {
    const line = this.drawn.line;
    const engine = this.row(this.picked.engine);
    return (line?.files || []).map((file, i) => {
      const takes = engine ? this.takes(engine, file) : { ok: true };
      const size = Number(line.sizes?.[i]);
      return { kind: "quant", key: file, name: new LibraryPath(file).quant() || String(file).split("/").pop(), sizeGb: size > 0 ? size : 0,
               detail: size > 0 ? `${size >= 100 ? Math.round(size) : size.toFixed(1)} GB` : "", ok: takes.ok,
               why: takes.ok ? "" : t(takes.reasonKey || "machineBuildCannotRun") };
    });
  }

  /** The settings offered for the picked engine: what the model's maker stated once (`makerSet`), its saved sets (the same for every
   *  machine), then the settings of each cell of this model here that runs on it — «Использовать настройки существующей ячейки», read
   *  from what the cell keeps, so nothing is guessed. A cell's card says the cell's own name, its cellId — the one its row's chip says —
   *  because every cell on this shelf is a cell of the one model, and the model would name them all alike. None before an engine is
   *  picked: a set belongs to its engine. */
  params() {
    const { line, cells } = this.drawn;
    const engine = this.picked.engine;
    if (!engine) return [];
    const maker = this.makerSet(line, engine);
    const saved = Object.entries(this.presets?.[engine] || {}).map(([name, fields]) => ({ kind: "params", key: `set:${name}`, name,
      detail: t("machineBuildSaved"), ok: true, fields: MachineBuild.fieldsOfSet(fields) }));
    const own = (line?.launches || []).filter((server) => MachineMap.idOf(server) && cellRunnerId(server.slotConfig) === engine).map((server) => {
      const cellId = MachineMap.idOf(server);
      return { kind: "params", key: `cell:${cellId}`, name: t("machineBuildCellSet", { cell: cellId }),
               detail: String(cells.get(cellId)?.quant || ""), ok: true, fields: MachineBuild.fieldsOfCell(server.slotConfig || {}) };
    });
    return [...(maker ? [maker] : []), ...saved, ...own];
  }

  /** The maker's numbers of the model as a card, or null: a model its maker stated nothing once for has none, and neither has an engine
   *  that writes no sampling flag of its own (the registry's `llamaConfig`, the rule the saved sets are held to on the controller), where
   *  the numbers would sit in the config and change nothing. */
  makerSet(line, engine) {
    const stated = this.makers?.[line?.name];
    const fields = stated && typeof stated === "object" ? Object.entries(stated) : [];
    if (!fields.length || this.row(engine)?.llamaConfig !== true) return null;
    return { kind: "params", key: "maker", name: t("machineBuildMaker"), ok: true, fields: MachineBuild.fieldsOfSet(stated),
             detail: fields.map(([field, value]) => `${field} ${value}`).join(", ") };
  }

  /** A saved set as config fields: the controller keeps numbers and booleans, a cell's config holds words (a box as "1" or "0"). */
  static fieldsOfSet(fields) {
    return Object.fromEntries(Object.entries(fields || {}).map(([key, value]) => [key, typeof value === "boolean" ? (value ? "1" : "0") : String(value)]));
  }

  /** A cell's settings: everything it keeps but its name, its files and its place (`setting`). */
  static fieldsOfCell(config) {
    return Object.fromEntries(Object.entries(config || {}).filter(([key]) => MachineBuild.setting(key)).map(([k, v]) => [k, String(v ?? "")]));
  }

  // ── picking ──────────────────────────────────────────────────────────────────────────────────────────

  /** The model the builder shows: picking another one empties the places, because nothing picked for one model goes with another. The
   *  board's builder asks it too, with the model picked, before it tells the map of the launch (topology-nodes.js), so that the map never
   *  draws a launch the builder is about to let go. */
  follow(line, host) {
    const name = String(line?.name || "");
    if (name !== this.model || String(host || "") !== this.host) {
      this.reset();
      this.model = name;
      this.host = String(host || "");
    }
  }

  /** The cards of one step, for what was drawn. */
  cards(kind) {
    return kind === "engine" ? this.engines() : kind === "quant" ? this.quants() : this.params();
  }

  /** A card put in its place: a dim card is refused (false), and an engine that changes takes the set of the engine before away. */
  pick(kind, key) {
    const card = this.cards(kind).find((c) => c.key === key);
    if (!card || !card.ok) return false;
    if (kind === "engine" && this.picked.engine !== key) this.unpick("params");
    this.picked[kind] = key;
    this.held[kind] = card;
    return true;
  }

  /** A place emptied. Without an engine there is no set either. */
  unpick(kind) {
    this.picked[kind] = "";
    this.held[kind] = null;
    if (kind === "engine") this.unpick("params");
  }

  /** Whether the launch has what a start needs: an engine and a quant (the mockup: «Для запуска нужны движок и квант»). */
  whole() {
    return !!(this.picked.engine && this.picked.quant);
  }

  /** The launch as a cell to be: its machine, engine, file, what the file weighs, and the settings — the set picked, or none: the engine's
   *  own defaults. No cellId and no port: its Start makes the cell, and the cell's scout leases a port when it runs. null while it is not
   *  whole or no machine is shown. */
  launch() {
    if (!this.whole() || !this.host) return null;
    const quant = this.held.quant || {};
    // A file that lies straight in the library has no quant's folder: its card is named by the file, which is the model's name too, and
    // "x · x" was the name the start was asked about (seen on the stand).
    const build = String(quant.name || "");
    return { host: this.host, runner: this.picked.engine, file: this.picked.quant,
             name: build && build !== this.model ? `${this.model} · ${build}` : this.model,
             sizeGb: Number(quant.sizeGb) || 0, fields: { ...(this.held.params?.fields || {}) } };
  }

  /** The strip's cell as the map reads a cell (MachineMap `launch`): one that stands, under the builder's key, which no list of the machine
   *  holds. */
  server() {
    return this.launch() ? { cellId: MachineBuild.KEY, phase: "stopped", virtual: true } : null;
  }

  /** The config the strip's facts are worked out from: the engine, the file and the settings — what the form makes of it at Start. */
  static config(launch) {
    return launch ? { ...launch.fields, RUNNER: launch.runner, MODEL_FILE: launch.file } : {};
  }

  /** Whether `cellId` — a key of the map, the plan or the choice — is the strip's cell to be. */
  owns(cellId) {
    return String(cellId ?? "") === MachineBuild.KEY && !!this.server();
  }

  // ── drawing ──────────────────────────────────────────────────────────────────────────────────────────

  static icon(kind) {
    return `<svg class="machine-build-icon is-${kind}" viewBox="0 0 48 48" aria-hidden="true">${ICONS[kind]}</svg>`;
  }

  /** A card's name as it stands on the card, on its step and in its place: an engine's mark before its name. */
  static named(card) {
    return `${card.mark ? `${card.mark} ` : ""}${card.name}`;
  }

  cardHtml(card) {
    const on = this.picked[card.kind] === card.key;
    const title = [card.why, card.unwanted ? t("machineBuildUnwanted") : ""].filter(Boolean).join(" · ");
    const state = !card.ok ? "dim" : on ? "on" : "ok";
    return `<button type="button" class="machine-build-card is-${escapeHtml(card.kind)}${on ? " is-on" : ""}${card.ok ? "" : " is-dim"}" data-build-card="${escapeHtml(card.kind)}"`
      + ` data-build-key="${escapeHtml(card.key)}" data-t="machine-build-card" data-t-id="${escapeHtml(`${card.kind}:${card.key}`)}" data-t-state="${state}"`
      + `${title ? ` title="${escapeHtml(title)}"` : ""}${card.ok ? "" : ' aria-disabled="true"'} aria-pressed="${on}">${MachineBuild.icon(card.kind)}`
      + `<span class="machine-build-words"><strong>${escapeHtml(MachineBuild.named(card))}</strong>`
      + `${card.detail ? `<small>${escapeHtml(card.detail)}</small>` : ""}${card.unwanted ? `<small class="machine-build-warn">⚠ ${escapeHtml(t("machineBuildUnwanted"))}</small>` : ""}</span>`
      + `${on ? '<span class="machine-build-tick" aria-hidden="true">✓</span>' : ""}</button>`;
  }

  /** What a step's shelf says when it has no card: which absence it is. A set is known to be missing only once the sets were read. */
  noneWords(kind) {
    if (kind === "engine") return t("machineBuildNoEngines");
    if (kind === "quant") return t("machineBuildNoFiles");
    if (!this.picked.engine) return t("machineBuildEngineFirst");
    return this.read === "read" ? t("machineBuildNoSets") : "";
  }

  /** What the shelf of settings says of the saved sets beside its cards: that they are being read, that they could not be, that some rows
   *  could not — never left out, or a shelf of the cells' settings alone would read as "no set is saved". */
  setsWords() {
    const words = this.read === "failed" ? [t("machineBuildSetsUnread")] : this.read === "read" ? [] : [t("machineBuildSetsReading")];
    if (this.read === "read" && this.unread > 0) words.push(t("machineBuildSetsSkipped", { n: String(this.unread) }));
    return words;
  }

  /** The shelf: the cards of the step shown, in one row swiped sideways — an arrow stands at an end that has more, for a mouse — and what the
   *  step says when it has no card, with, for the settings, what became of the saved sets. `entering`: the shelf has just moved to this
   *  step, and its cards come in. */
  shelfHtml(entering = false) {
    const kind = this.step;
    const cards = this.cards(kind);
    const none = cards.length ? "" : this.noneWords(kind);
    const notes = [...(none ? [none] : []), ...(kind === "params" ? this.setsWords() : [])];
    const said = notes.map((words, i) => `<p class="machine-build-none" data-t="machine-build-none" data-t-id="${kind}${i ? `-${i}` : ""}">${escapeHtml(words)}</p>`).join("");
    const arrow = (way, side, label) => `<button type="button" class="machine-build-arrow is-${side}" data-build-scroll="${way}" tabindex="-1"`
      + ` aria-label="${escapeHtml(t(label))}" title="${escapeHtml(t(label))}">${way < 0 ? "‹" : "›"}</button>`;
    return `<div class="machine-build-shelf is-${kind}" data-build-shelf="${kind}" data-t="machine-build-shelf" data-t-id="${kind}">${arrow(-1, "back", "machineBuildShelfBack")}`
      + `<div class="machine-build-track${entering ? " is-entering" : ""}" data-build-track role="tabpanel" aria-label="${escapeHtml(t(MachineBuild.TITLES[kind]))}">`
      + `${cards.map((c) => this.cardHtml(c)).join("")}${said}</div>${arrow(1, "more", "machineBuildShelfMore")}</div>`;
  }

  /** One place of the launch, which is the step of its part too (the owner's choice Б, 2026-11-08: the rail's places are the steps): its
   *  number, its part, what stands there or the words that nothing does. A press on it shows its cards on the shelf under the rail, and the
   *  place of the step shown is ringed in its part's colour (`aria-selected`). A part standing there has its ✕, which empties the place. Both
   *  are buttons of their own (`data-machine-own`): in the strip a press on a place shows its step too, and neither chooses the strip nor
   *  carries it — the strip's handle does. What stands there is read from what was picked (`held`), so a list that moved since does not
   *  empty it in silence. */
  slotHtml(kind, at) {
    const card = this.picked[kind] ? this.held[kind] : null;
    const words = card ? MachineBuild.named(card) : t(MachineBuild.EMPTY[kind]);
    const empty = escapeHtml(t("machineBuildEmptyIt"));
    const shown = this.step === kind;
    const x = card ? `<button type="button" class="machine-build-x" data-build-empty="${kind}" data-machine-own data-t="machine-build-empty" data-t-id="${kind}"`
      + ` title="${empty}" aria-label="${empty}">✕</button>` : "";
    return `<span class="machine-build-slot is-${kind}${card ? " is-full" : ""}${shown ? " is-shown" : ""}" data-build-slot="${kind}" data-t="machine-build-slot"`
      + ` data-t-id="${kind}" data-t-state="${card ? "full" : "empty"}"><button type="button" class="machine-build-step" role="tab" aria-selected="${shown}"`
      + ` data-build-step="${kind}" data-machine-own data-t="machine-build-step" data-t-id="${kind}" title="${escapeHtml(t("machineBuildShowStep"))}">`
      + `<i class="machine-build-step-mark" aria-hidden="true">${at + 1}</i>${MachineBuild.icon(kind)}`
      + `<span class="machine-build-words"><small>${escapeHtml(t(MachineBuild.TITLES[kind]))}</small><strong>${escapeHtml(words)}</strong></span></button>${x}</span>`;
  }

  /** The launch: one rail of three places, which are the steps (`slotHtml`). While it is not whole, the rail's end says what it is and holds
   *  `fresh`, the new-cell wizard for the model (MachineModels.newHtml: the same button the block of the model picked had); what a start
   *  needs is in its hover, and the empty places name what is missing. Once an engine and a quant stand there the rail is the strip — a cell
   *  to be, chosen and carried as a cell's row is (MachinePick, MachineDrag: `data-machine-pick`, the builder's key), with its handle and the
   *  button that chooses it from a keyboard, which names it as what it is: a new cell, with no name of its own until its Start makes it — and
   *  the map's last line for that cell stands under it (`choice`, MachineMap.choiceHtml: its places, its plan, Start and Cancel). */
  railHtml(choice, on = false, fresh = "") {
    const strip = !!this.server();
    const places = `<div class="machine-build-places" role="tablist" aria-label="${escapeHtml(t("machineBuildSteps"))}">`
      + `${MachineBuild.COLUMNS.map((kind, at) => this.slotHtml(kind, at)).join("")}</div>`;
    if (!strip) {
      return `<div class="machine-build-rail" data-build-rail data-t="machine-build-slots">${places}<span class="machine-build-end" title="${escapeHtml(t("machineBuildNeeds"))}">`
        + `<strong class="machine-build-title">${escapeHtml(t("machineBuildTitle"))}</strong>${fresh}</span></div>`;
    }
    const key = escapeHtml(MachineBuild.KEY);
    return `<div class="machine-build-rail is-whole${on ? " is-on" : ""}" data-build-rail data-machine-pick="${key}" data-t="machine-build-strip" data-t-id="${key}"`
      + ` title="${escapeHtml(t("machineBuildTakeHint"))}">${places}<span class="machine-build-take"><span class="machine-build-grip" aria-hidden="true">⠿</span>`
      + `<span class="machine-build-words"><strong><span aria-hidden="true">↑ </span>${escapeHtml(t("machineBuildTake"))}</strong><small>${escapeHtml(t("machineBuildTakeShort"))}</small></span>`
      + `<button type="button" class="machine-build-port${on ? " is-on" : ""}" aria-pressed="${on}" data-machine-pick="${key}" data-t="machine-build-port"`
      + ` data-t-id="${key}">${escapeHtml(t("machineBuildNewCell"))}</button></span></div>${choice || ""}`;
  }

  /** The builder for the model picked (`line`) on machine `host`, or the words that no model is picked: two rows, the rail and under it the
   *  shelf of the step shown (the owner's choice Б, 2026-11-08). `cells` is what the board's builder said of each cell; `choice` the map's last
   *  line for the strip's cell, and `on` whether it is the cell chosen on the map; `fresh` the new-cell wizard for the model, at the rail's end. */
  html(line, host, { cells = new Map(), choice = "", on = false, runners = null, fresh = "" } = {}) {
    // Drawn only where the board's builder told the engines: a builder that knew none would say that no engine runs the model.
    if (!runners) return "";
    this.drawn = { line: line || null, cells, runners };
    // A model that is not picked any more, or no model, takes what was picked for it away.
    this.follow(line, host);
    const title = escapeHtml(t("machineBuildTitle"));
    if (!line) {
      return `<section class="machine-build is-none" aria-label="${title}" data-t="machine-build" data-t-state="none"><strong class="machine-build-title">${title}</strong>`
        + `<p class="machine-build-none" data-t="machine-build-none" data-t-id="model">${escapeHtml(t("machineBuildNoModel"))}</p></section>`;
    }
    // The cards of a step come in once, when the shelf moves to it: a drawing of the same step leaves them where they stand.
    const entering = this.shown !== this.step;
    this.shown = this.step;
    return `<section class="machine-build" aria-label="${title}" data-t="machine-build" data-t-id="${escapeHtml(line.name)}" data-t-state="${this.whole() ? "whole" : "building"}">`
      + `${this.railHtml(choice, on, fresh)}${this.shelfHtml(entering)}</section>`;
  }

  // ── the controller's sets ────────────────────────────────────────────────────────────────────────────

  /** The saved sets and marks, once a page (`ask`, given by `bind`); a failure is kept as a failure, and the next drawing says so. */
  async readOnce() {
    if (this.read === "asking" || this.read === "read") return;
    this.read = "asking";
    try {
      const said = await this.ask();
      this.presets = said?.presets || {};
      this.warnings = said?.warnings || {};
      this.makers = said?.makers || {};
      this.unread = Number(said?.unread) || 0;
      this.read = "read";
    } catch {
      this.read = "failed";
    }
    this.redraw();
  }

  // ── presses and carrying ─────────────────────────────────────────────────────────────────────────────

  /** @param ask () → what the controller keeps (GET /api/runner-presets); @param choose (key) → the strip's cell to be chosen on the map, by
   *  the builder's key; @param redraw () → the page drawn again; @param plan the map's plan (machine-plan.js) */
  bind(doc, { ask = async () => null, choose = () => {}, redraw = () => {}, plan = MACHINE_PLAN } = {}) {
    if (this.bound || !doc?.addEventListener) return;
    this.bound = true;
    Object.assign(this, { doc, ask, choose, redraw, plan });
    doc.addEventListener("click", (e) => this.clicked(e));
    doc.addEventListener("pointerdown", (e) => this.down(e));
    doc.addEventListener("pointermove", (e) => this.moving(e));
    doc.addEventListener("pointerup", (e) => this.up(e));
    doc.addEventListener("pointercancel", () => this.drop());
    // A scroll does not bubble: the shelf's is heard on its way down.
    doc.addEventListener("scroll", (e) => this.scrolled(e.target), true);
    globalThis.addEventListener?.("resize", () => this.mounted());
  }

  /** A press on the builder: an arrow moves the shelf, ✕ empties its place, a card goes to its place or out of it, and a place of the rail
   *  shows its step's cards — in the strip too, where the rest of the rail is the strip's, chosen and carried with it. The click that ends a
   *  carry or a drag of the shelf is none of these. */
  clicked(e) {
    if (this.carry?.moved) return undefined;
    const arrow = e.target?.closest?.("[data-build-scroll]");
    if (arrow) return this.slide(arrow);
    const x = e.target?.closest?.("[data-build-empty]");
    if (x) return this.starting() ? false : this.empty(x.dataset.buildEmpty);
    const card = e.target?.closest?.("[data-build-card]");
    if (card) return this.press(card.dataset.buildCard, card.dataset.buildKey);
    const step = e.target?.closest?.("[data-build-step]");
    if (step) return this.show(step.dataset.buildStep);
    return undefined;
  }

  /** Whether the launch's start is being made now: then it stays as it was asked. */
  starting() {
    return !!(this.plan?.busy && this.owns(this.plan.cellId));
  }

  /** A card pressed: put in its place, or taken out of it when it stands there already (its pressed state says so). */
  press(kind, key) {
    if (this.starting()) return false;
    return this.picked[kind] === key ? this.empty(kind) : this.put(kind, key);
  }

  /** A card put in its place, pressed or carried there; the shelf moves on to the next step. Not while the launch's start is being made: the
   *  cell that start makes is the launch as it was asked. */
  put(kind, key) {
    if (this.starting() || !this.pick(kind, key)) return false;
    this.step = this.nextStep();
    this.changed();
    return true;
  }

  /** A place emptied; the shelf shows what may stand there instead. */
  empty(kind) {
    this.unpick(kind);
    this.step = kind;
    this.changed();
    return true;
  }

  /** The shelf on a step's cards. */
  show(kind) {
    if (!MachineBuild.COLUMNS.includes(kind) || kind === this.step) return false;
    this.step = kind;
    this.redraw();
    return true;
  }

  /** What is picked changed. A plan laid for the launch was laid for another cell, and goes (a plan belongs to its cell, MachinePick). The
   *  launch, whole, is chosen on the map, so its places and where it would lie show at once; not whole, the map has no launch to lay. */
  changed() {
    if (this.plan?.cellId === MachineBuild.KEY) this.plan.clear();
    if (this.server()) this.choose(MachineBuild.KEY);
    this.redraw();
  }

  // ── the shelf ────────────────────────────────────────────────────────────────────────────────────────

  /** An arrow pressed: the shelf moves most of its width towards its start (-1) or its end (1). */
  slide(arrow) {
    const track = arrow.closest?.("[data-build-shelf]")?.querySelector?.("[data-build-track]");
    if (!track?.scrollBy) return false;
    track.scrollBy({ left: Number(arrow.dataset.buildScroll) * Math.max(1, Math.round((Number(track.clientWidth) || 0) * 0.8)), behavior: "smooth" });
    return true;
  }

  /** The shelf scrolled: where it stands kept for the next drawing of the same step, and its ends said again. */
  scrolled(target) {
    if (!target?.matches?.("[data-build-track]")) return;
    this.shelf = { step: this.step, left: Number(target.scrollLeft) || 0 };
    this.ends(target);
  }

  /** The ends of the shelf said by its classes: an edge with cards out of sight fades, and its arrow stands there. */
  ends(track) {
    const ends = MachineBuild.ends(track || {});
    const shelf = track?.closest?.("[data-build-shelf]");
    shelf?.classList?.toggle?.("has-back", ends.back);
    shelf?.classList?.toggle?.("has-more", ends.more);
    return ends;
  }

  /** The page drawn by the board (topology-render.js), or the window resized: the shelf where it was swiped to on the same step, its ends said. */
  mounted(doc = this.doc) {
    const track = doc?.querySelector?.("[data-build-track]");
    if (!track) return null;
    if (this.shelf.step === this.step) track.scrollLeft = this.shelf.left;
    return this.ends(track);
  }

  // ── a card carried ───────────────────────────────────────────────────────────────────────────────────

  /** A card or the shelf in hand: the board does not draw the page anew under it (topology-render.js). */
  get busy() {
    return !!this.carry?.mode;
  }

  /** A card pressed on the shelf: what the press does is decided by its first move past the slop (`gesture`). */
  down(e) {
    if (e.button) return;
    const card = e.target?.closest?.("[data-build-card]");
    if (!card || card.getAttribute?.("aria-disabled") === "true") return;
    const track = card.closest?.("[data-build-track]") || null;
    this.carry = { kind: card.dataset.buildCard, key: card.dataset.buildKey, x: e.clientX, y: e.clientY, moved: false, mode: "",
                   mouse: !e.pointerType || e.pointerType === "mouse", card, track, left: Number(track?.scrollLeft) || 0, ghost: null, over: false };
  }

  moving(e) {
    const carry = this.carry;
    if (!carry || carry.done) return undefined;
    if (!e.buttons) return this.drop();
    const dx = e.clientX - carry.x;
    const dy = e.clientY - carry.y;
    if (!carry.mode) {
      if (Math.abs(dx) + Math.abs(dy) < MachineBuild.SLOP) return undefined;
      carry.mode = MachineBuild.gesture(dx, dy, carry.mouse);
      if (!carry.mode) {
        this.carry = null;
        return undefined;
      }
      carry.moved = true;
      if (carry.mode === "carry") this.lift(carry);
    }
    e.preventDefault?.();
    if (carry.mode === "scroll") {
      if (carry.track) carry.track.scrollLeft = carry.left - dx;
      return undefined;
    }
    this.carryTo(carry, e.clientX, e.clientY);
    return undefined;
  }

  /** The card taken into the hand: its copy goes under the pointer, the card itself steps back, the launch lights and its place for this card
   *  in it (machine.css, `data-carrying`). */
  lift(carry) {
    const panel = this.doc.querySelector?.("[data-t=\"machine-build\"]");
    panel?.classList?.add?.("is-carrying");
    if (panel) panel.dataset.carrying = carry.kind;
    const box = carry.card?.getBoundingClientRect?.();
    // The copy keeps the place the card was taken by, under the pointer.
    carry.grab = box ? { x: carry.x - box.left, y: carry.y - box.top } : { x: 0, y: 0 };
    const ghost = carry.card?.cloneNode?.(true);
    if (ghost) {
      ghost.removeAttribute?.("data-t");
      ghost.setAttribute?.("aria-hidden", "true");
      ghost.classList?.add?.("machine-build-ghost");
      if (box && ghost.style) ghost.style.width = `${Math.round(box.width)}px`;
      this.doc.body?.appendChild?.(ghost);
      carry.ghost = ghost;
    }
    carry.card?.classList?.add?.("is-lifted");
  }

  /** The card's copy where the pointer is, and the launch lit while the pointer is over it: let go there, the card goes to its own place. */
  carryTo(carry, x, y) {
    if (carry.ghost?.style) carry.ghost.style.transform = `translate(${Math.round(x - carry.grab.x)}px, ${Math.round(y - carry.grab.y)}px)`;
    carry.over = !!this.doc.elementFromPoint?.(x, y)?.closest?.("[data-build-rail]");
    this.doc.querySelector?.("[data-build-rail]")?.classList?.toggle?.("is-over", carry.over);
  }

  /** A card let go over the launch goes to its own place there; anywhere else nothing happens. */
  up(e) {
    const carry = this.carry;
    if (!carry || carry.done) return;
    if (!carry.moved) {
      this.carry = null;
      return;
    }
    if (carry.mode === "carry") this.carryTo(carry, e.clientX, e.clientY);
    const put = carry.mode === "carry" && carry.over && this.picked[carry.kind] !== carry.key;
    this.drop();
    if (put) this.put(carry.kind, carry.key);
    // The click that ends a carry or a drag of the shelf is no press on the card.
    this.carry = { moved: true, done: true };
    globalThis.setTimeout?.(() => { this.carry = null; }, 0);
  }

  /** The hand emptied: the copy gone, the card and the launch as they were. A carry the browser took over (a finger's scroll) or a button let
   *  go out of the window ends here, and no click follows it. */
  drop() {
    const carry = this.carry;
    carry?.ghost?.remove?.();
    carry?.card?.classList?.remove?.("is-lifted");
    const panel = this.doc?.querySelector?.("[data-t=\"machine-build\"]");
    panel?.classList?.remove?.("is-carrying");
    if (panel) delete panel.dataset.carrying;
    this.doc?.querySelector?.("[data-build-rail]")?.classList?.remove?.("is-over");
    this.carry = null;
  }

  /** After the launch's Start made its cell (machine-plan.js MachinePlanStart, `made`): it is a cell now, with a row and a name of its own,
   *  whatever its start does next, and the places are empty again for the next launch — a second Start of this one would make a second cell. */
  made() {
    const { model, host } = this;
    this.reset();
    Object.assign(this, { model, host });
  }
}

export const MACHINE_BUILD = new MachineBuild();
