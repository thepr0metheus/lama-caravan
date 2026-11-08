// What the operator lays out on a machine's rack before it happens (the owner's choice К1, 2026-10-31: "drag a model onto a video
// card or elsewhere to start it and say where; divide it between the cards by dragging"). A model dropped on a lane, or a handle moved,
// is a plan: the rack draws it dashed where it would lie, by the same rules the cell's window draws by (machine-head.js CellFit), and
// nothing on the machine changes until Start. The plan is the fields of the cell's config it would change; a start saves them and
// starts the cell, stopping first what has to give way.
//
// Decisions apart from effects: MachineRoom, RackShares and the moves are rules on values; MachinePlan is the state; MachineDrag reads
// the pointer; MachinePlanStart talks to the controller, with everything it needs handed in.
//
// A cell is known here by its own name, `cellId` (the topology's `servers[].cellId`), and by nothing else: it holds a port only while it
// runs, and the page shows none. The launch being built under the map (machine-build.js) is no cell yet and has no cellId: it is planned
// under the builder's own key (MachineBuild.KEY) until its Start makes the cell.
import { t } from "./i18n.js";
import { CardPin, CardRoom, ComputeFields, PlacementPlan } from "./placement.js";

const GIB = 2 ** 30;

/** The machine as a start would find it. */
export class MachineRoom {
  /** A copy of the machine with the cells `cellIds` gone: what they hold on its cards and in its RAM is free, and they are marked
   *  `leaving` for whoever draws it. A cell on a card maps its model file and its RSS is not the machine's "used", unless its runner
   *  keeps its weights in RAM (`keepsRam`), so only those give RAM back: the rule the RAM's lane draws by. */
  static without(node, cellIds = [], keepsRam = () => false) {
    const gone = new Set((cellIds || []).map(String));
    if (!gone.size) return node;
    const leaving = (node?.servers || []).filter((s) => gone.has(String(s.cellId)));
    const gpus = (node?.gpus || []).map((g) => {
      const mib = leaving.reduce((sum, s) => sum + (CardRoom.said(s.gpuMem?.[String(g.index)]) || 0), 0);
      if (!(mib > 0)) return g;
      const used = CardRoom.said(g.memoryUsedMiB);
      const free = CardRoom.said(g.memoryFreeMiB);
      return { ...g, ...(used === null ? {} : { memoryUsedMiB: Math.max(0, used - mib) }), ...(free === null ? {} : { memoryFreeMiB: free + mib }) };
    });
    const ram = node?.cpu?.ram;
    const used = CardRoom.said(ram?.usedGb);
    const back = leaving.reduce((sum, s) => {
      const onCard = Object.values(s.gpuMem || {}).some((mib) => CardRoom.said(mib) > 0);
      return sum + (onCard && !keepsRam(s) ? 0 : (CardRoom.said(s.ramBytes) || 0) / GIB);
    }, 0);
    return { ...node, gpus,
      ...(ram && used !== null ? { cpu: { ...node.cpu, ram: { ...ram, usedGb: Math.max(0, used - back) } } } : {}),
      servers: (node?.servers || []).map((s) => (gone.has(String(s.cellId)) ? { ...s, leaving: true } : s)) };
  }

  /** What a start has to lay itself on: {cards: [{index, freeGb, ceilingGb}], all, ramFreeGb, cores}; a card nobody measured has no
   *  room to lay anything on, and a RAM nobody measured is null, not nothing. */
  static of(node) {
    const cards = (node?.gpus || []).map((g) => {
      const free = CardRoom.freeMiB(g);
      const freeGb = free === null ? 0 : free / 1024;
      return { index: Number(g.index), freeGb, ceilingGb: PlacementPlan.ceiling({ freeGb }) };
    }).sort((a, b) => a.index - b.index);
    const ram = node?.cpu?.ram || {};
    const total = CardRoom.said(ram.totalGb);
    const used = CardRoom.said(ram.usedGb);
    return { cards, all: cards.map((c) => c.index), ramFreeGb: total && used !== null ? Math.max(0, total - used) : null,
             cores: ComputeFields.cores(node?.cpu) };
  }

  /** Less room than this on a card, GB, is none: a crumb of a model on a nearly full card holds no layer and only names the card. */
  static LEAST_GB = 0.5;

  /** The room of each place by its id, the cards in their order and the RAM last. */
  static rooms(room) {
    return { ids: [...room.cards.map((c) => String(c.index)), "ram"],
             of: Object.fromEntries([...room.cards.map((c) => [String(c.index), c.ceilingGb >= MachineRoom.LEAST_GB ? c.ceilingGb : 0]), ["ram", room.ramFreeGb ?? 0]]) };
  }
}

/** How much of a model each place holds, GB, as the operator asks it: {"0": 22, "1": 28, ram: 14}. */
export class RackShares {
  /** Dropped on `first`: as much as it holds, the rest over the other cards in their order, what is left in RAM. */
  static dropped(needGb, first, rooms) {
    const shares = Object.fromEntries(rooms.ids.map((id) => [id, 0]));
    let left = Number(needGb) || 0;
    for (const id of [first, ...rooms.ids.filter((k) => k !== first)]) {
      const take = Math.min(left, rooms.of[id] || 0);
      shares[id] = take;
      left -= take;
    }
    return shares;
  }

  /** `id` asked to hold `want`; the rest of the model moves to keep the whole. More here comes first from RAM, then from the last card
   *  in use; less here goes first to the cards in use, then to RAM, and only then to a card not in use. Nothing goes past a place's
   *  room, and a place cannot be left holding less than what the others have no room for. */
  static set(shares, id, want, rooms) {
    const p = Object.fromEntries(rooms.ids.map((k) => [k, Number(shares?.[k]) || 0]));
    const whole = rooms.ids.reduce((sum, k) => sum + p[k], 0);
    const others = rooms.ids.filter((k) => k !== id);
    const elsewhere = others.reduce((sum, k) => sum + (rooms.of[k] || 0), 0);
    const next = Math.min(rooms.of[id] || 0, whole, Math.max(whole - elsewhere, 0, Number(want) || 0));
    let delta = next - p[id];
    p[id] = next;
    if (delta > 0) {
      for (const k of [...others.filter((o) => o === "ram"), ...others.filter((o) => o !== "ram").reverse()]) {
        const take = Math.min(delta, p[k]);
        p[k] -= take;
        delta -= take;
      }
    } else if (delta < 0) {
      let give = -delta;
      const cards = others.filter((o) => o !== "ram");
      for (const k of [...cards.filter((o) => p[o] > 0), ...others.filter((o) => o === "ram"), ...cards.filter((o) => !(p[o] > 0))]) {
        const put = Math.min(give, Math.max(0, (rooms.of[k] || 0) - p[k]));
        p[k] += put;
        give -= put;
      }
    }
    return p;
  }

  /** The cards that hold something, by index, ascending. */
  static cards(shares) {
    return Object.keys(shares || {}).filter((k) => k !== "ram" && shares[k] > 0).map(Number).sort((a, b) => a - b);
  }
}

/**
 * How a cell's config says where it lies, a kind per family of runners (the board's builder names it: facts.family).
 * `to(target, room)` lays it on a card (its index as text) or in "ram": {how, fields, shares?, asks?}, or {refused: a word's key} when it
 * cannot lie there. `how` is the way CellFit then draws it by, `fields` what changes in its config.
 */
export class CellMove {
  /** Whether a share of a place can be set by a handle. */
  sizable = false;

  /** Whether the place `id` (a card's index, or "ram") has such a share. */
  canSet() {
    return true;
  }

  static of(facts = {}) {
    const Move = { llama: LlamaMove, pinned: PinnedMove, vllm: VllmMove }[facts?.family] || CellMove;
    return new Move(facts || {});
  }

  constructor(facts = {}) {
    this.facts = facts;
  }

  field(key) {
    return String(this.facts.fields?.[key] ?? "");
  }

  get needGb() {
    const bytes = CardRoom.said(this.facts.bytes);
    return bytes > 0 ? bytes / GIB : null;
  }

  /** A cell whose place is not the caravan's to set: an engine's. */
  to() {
    return { refused: "machineMoveFixed" };
  }
}

/** llama.cpp: DEVICE names its cards and --fit-target how much it may take of each; the rest stays in RAM, computed by the processor. */
class LlamaMove extends CellMove {
  sizable = true;

  to(target, room) {
    if (target === "ram") return { how: "ram", fields: { ...ComputeFields.cpu(room.cores), FIT_TARGET: "" }, shares: null };
    const card = room.cards.find((c) => String(c.index) === String(target));
    if (!card) return { refused: "machineMoveFixed" };
    const need = this.needGb;
    // Its size not known, or it fits this card: this card alone.
    if (!(need > card.ceilingGb)) return this.laid({ [String(card.index)]: need || card.ceilingGb }, room);
    return this.laid(RackShares.dropped(need, String(card.index), MachineRoom.rooms(room)), room);
  }

  /** The shares as fields. The limit of a card is its share and a layer more, so the cards together hold the whole model: llama.cpp
   *  deals whole layers, from the last card back, and a limit cut to the gigabyte would leave a layer in RAM nobody asked for. A share
   *  asked of the RAM has no such slack on the cards: that much stays there. */
  laid(shares, room) {
    const m = this.facts.model;
    const kvOn = this.field("KV_OFFLOAD") !== "0";
    const per = m && m.layers > 0 ? (m.weightsGb + (kvOn ? m.kvGb : 0)) / m.layers : 0;
    const slack = Number(shares.ram) > 0 ? 0 : per;
    const picked = RackShares.cards(shares);
    if (!picked.length) return this.to("ram", room);
    const cards = picked.map((index) => room.cards.find((c) => c.index === index));
    const limits = cards.map((c) => Math.min(c.ceilingGb, Number(shares[String(c.index)]) + slack));
    const tensor = this.facts.mode === "tensor" && cards.length > 1;
    const plan = new PlacementPlan({ model: m || {}, cards: cards.map((c) => ({ index: c.index, freeGb: c.freeGb })), limits, mode: tensor ? "tensor" : "layer",
                                     kvOnCards: kvOn, ramFreeGb: room.ramFreeGb, cores: room.cores });
    const fields = m ? plan.fields() : { KV_OFFLOAD: kvOn ? "1" : "0", N_CPU_MOE: "", CPU_MOE: "0", FIT: "1", SPLIT_MODE: cards.length > 1 ? "layer" : "",
                                         TENSOR_SPLIT: "", FIT_TARGET: plan.margins().join(",") };
    return { how: m ? "plan" : "spread", shares, fields: { ...ComputeFields.cards(picked, room.all), ...fields } };
  }

  /** The shares set by hand: `id` asked to hold `want`, from what is planned now. */
  share(shares, id, want, room) {
    return this.laid(RackShares.set(shares, id, want, MachineRoom.rooms(room)), room);
  }
}

/** A server that loads onto one card, or computes on the processor: its ENV says which. */
class PinnedMove extends CellMove {
  to(target) {
    const env = this.field("ENV");
    if (target === "ram") {
      return this.facts.cpuOk ? { how: "ram", fields: { ENV: CardPin.offCards(env) } } : { refused: "machineMoveNeedsCard" };
    }
    if (this.facts.gpuOk === false) return { refused: "machineMoveCpuOnly" };
    return { how: this.facts.onCard || "card", fields: { ENV: CardPin.onCard(env, target) } };
  }
}

/** vLLM: its ENV pins its card and it asks a share of it. A tensor-parallel cell takes its cards in order: that is its window's to set. */
class VllmMove extends CellMove {
  constructor(facts) {
    super(facts);
    this.sizable = !facts?.parallel && !!facts?.asksFor;
  }

  /** The card's share is its GPU_MEMORY_UTILIZATION, which is no handle's to set; what a handle sets is what stays in RAM. */
  canSet(id) {
    return id === "ram";
  }

  laid(fields) {
    const at = this.facts.asksFor?.(fields);
    return { how: "asks", fields, asks: at?.asks ?? [], over: !!at?.over, ridesGb: at?.ridesGb ?? 0, speed: at?.speed ?? null };
  }

  /** On a card. Weights its share does not hold stay in RAM and come to it for every pass: that is how they run at all, and the plan says
   *  so before anything starts. What the operator left there stays, however large the card. */
  to(target) {
    if (target === "ram") return { refused: "machineMoveNeedsCard" };
    if (this.facts.parallel) return { refused: "machineMoveParallel" };
    const env = CardPin.write(this.field("ENV"), target);
    const own = Number(this.field("CPU_OFFLOAD_GB")) || 0;
    const need = this.facts.asksFor?.({ ENV: env, CPU_OFFLOAD_GB: "" })?.offloadNeededGb ?? 0;
    const gb = Math.max(own, need);
    return this.laid({ ENV: env, CPU_OFFLOAD_GB: gb > 0 ? String(gb) : "" });
  }

  /** The handle on the RAM: in half gigabytes, no more than the room there or the weights there are. */
  share(_shares, _id, want, room) {
    const free = Number.isFinite(room?.ramFreeGb) ? room.ramFreeGb : Infinity;
    const top = Math.floor(Math.min(free, this.facts.asksFor?.({ ENV: this.field("ENV"), CPU_OFFLOAD_GB: "" })?.weightsGb || Infinity) * 2) / 2;
    const gb = Math.min(Math.round(Math.max(0, Number(want) || 0) * 2) / 2, top);
    return this.laid({ ENV: this.field("ENV"), CPU_OFFLOAD_GB: gb > 0 ? String(gb) : "" });
  }
}

/**
 * The plan on the rack: which cell, what would change in its config, and who would give way. One, as one cell is chosen; held here and
 * not on the page, as the choice is: the board draws the page anew with every change.
 */
export class MachinePlan {
  constructor() {
    this.clear();
  }

  clear() {
    // The cell the plan is for, by its cellId; "" is no plan.
    this.cellId = "";
    this.how = "";
    this.fields = null;
    this.asks = null;
    this.over = false;
    this.ridesGb = 0;
    this.speed = null;
    this.shares = null;
    this.evict = [];
    this.moved = false;
    this.dragging = false;
    this.drop = "";
    this.dropOk = true;
    // While a drag lasts: whether the cell in hand may lie on each lane, by its id ("0", "1", "ram") — MachineDrag.targetsOf.
    this.targets = null;
    this.busy = false;
    this.room = null;
  }

  get on() {
    return this.cellId !== "" && !!this.fields;
  }

  /** The plan for the cell `cellId`: `result` as a move gives it; `evict` the cells that give way, by their cellIds. */
  set(cellId, result, { evict = [], moved = false } = {}) {
    this.cellId = String(cellId);
    this.how = result.how;
    this.fields = result.fields;
    this.asks = result.asks ?? null;
    this.over = !!result.over;
    this.ridesGb = Number(result.ridesGb) || 0;
    this.speed = result.speed ?? null;
    this.shares = result.shares ?? null;
    this.evict = (evict || []).map(String);
    this.moved = !!moved;
  }

  /** A start takes it: `room` is the machine as the operator was shown it, what the map keeps drawing it on until it is over. A stop
   *  reaches the topology before the cards' next reading does, and a plan redrawn in between promised 34.8 GB of RAM instead of 6.8. */
  begin(room = null) {
    this.busy = true;
    this.room = room;
  }

  /** The start did not get through: the plan is the operator's again. */
  end() {
    this.busy = false;
    this.room = null;
  }

  /** Those that were to give way have let go: a start that fails from here on leaves a plan for a cell that stands. */
  letGone() {
    this.evict = [];
    this.moved = false;
  }

  /** The launch the plan was laid for is a cell now, made by the start's save (MachinePlanStart): the plan is that cell's from here on, so a
   *  start that fails after it leaves the plan on the cell that stands, and a second Start starts it instead of making another. */
  becomes(cellId) {
    this.cellId = String(cellId);
  }

  /** What is held now, to go back to when a drag is let go nowhere. */
  snapshot() {
    return { cellId: this.cellId, how: this.how, fields: this.fields, asks: this.asks, over: this.over, ridesGb: this.ridesGb, speed: this.speed, shares: this.shares, evict: this.evict, moved: this.moved };
  }

  restore(saved) {
    Object.assign(this, saved);
  }

  /** The cells that would have let go when it starts, by their cellIds. */
  leaving() {
    return this.on ? [...this.evict, ...(this.moved ? [this.cellId] : [])] : [];
  }

  /** The builder's facts of the planned cell, as the plan would have them. */
  facts(facts = {}) {
    return { ...facts, how: this.how || facts.how, fields: { ...facts.fields, ...Object.fromEntries(Object.entries(this.fields || {}).filter(([k]) => k in (facts.fields || {}))) },
             ...(this.asks ? { asks: this.asks, over: this.over, ridesGb: this.ridesGb, speed: this.speed } : {}) };
  }

  /** What a start would change in the config it has, as "KEY=value": the words of the panel. */
  changes(config = {}) {
    return Object.entries(this.fields || {}).filter(([key, value]) => String(config[key] ?? "") !== String(value))
      .map(([key, value]) => `${key}=${String(value).replace(/\n/g, " ") || '""'}`);
  }

  /** What differs from another drawing, for whoever redraws only when it must. */
  key() {
    return this.on ? JSON.stringify([this.cellId, this.how, this.fields, this.evict, this.moved, this.busy]) : "";
  }

  /** Whether the plan still means anything on this machine: a stopped cell to start, or a running one to move, and those that are to
   *  give way still there. While a start carries it out it is the start's. `launch` is the launch being built on the page (machine-build.js,
   *  MachineBuild.server): no cell of the machine yet, standing under the builder's key, planned as one. */
  validFor(node, phaseOf = (s) => String(s?.phase || ""), launch = null) {
    if (!this.on || this.busy) return this.on;
    const of = (cellId) => (node?.servers || []).find((s) => String(s.cellId) === String(cellId))
      || (launch && String(launch.cellId) === String(cellId) ? launch : undefined);
    const server = of(this.cellId);
    if (!server) return false;
    const holds = ["running", "warming", "broken"].includes(phaseOf(server));
    if (holds !== this.moved) return false;
    return this.evict.every((cellId) => of(cellId) && ["running", "warming", "broken"].includes(phaseOf(of(cellId))));
  }
}

export const MACHINE_PLAN = new MachinePlan();

/**
 * How a pointer held near a pane's edge leans: toward the top below 0, toward the bottom above 0, 0 in the middle. On a window too low
 * for the rack to stay (machine.css), a cell's row far down the list is dragged up to a rack scrolled out of sight, so the pane has to
 * come along.
 */
export class PaneLean {
  /** How near an edge the pane starts to move, px. */
  static ZONE = 56;
  /** How far it moves in a frame with the pointer at the very edge, px. */
  static SPEED = 18;

  static at(y, top, bottom) {
    // Above the pane the pointer is on the rack, and the pane has no reason to move.
    if (!(bottom - top > 2 * PaneLean.ZONE) || y < top) return 0;
    if (y < top + PaneLean.ZONE) return -Math.min(1, (top + PaneLean.ZONE - y) / PaneLean.ZONE);
    if (y > bottom - PaneLean.ZONE) return Math.min(1, (y - bottom + PaneLean.ZONE) / PaneLean.ZONE);
    return 0;
  }
}

/**
 * The pointer on the rack: a cell dragged from its row in the list of models, a block or a note onto a lane; a running one dragged onto
 * the list stops; a handle sets a card's share, by pointer or arrow keys. A press that does not move is a click, as it was. Everything it
 * decides goes through the plan and `patch`, which draws the map again: the listeners are on the document, so a lane drawn anew under the
 * pointer loses nothing.
 */
export class MachineDrag {
  /** How far a press moves before it is a drag, px. */
  static SLOP = 5;
  /** How much an arrow key moves a handle, GB. */
  static STEP_GB = 0.5;
  /** How long after a drag a click still belongs to it, ms. */
  static CLICK_MS = 50;
  static MOVABLE = "[data-machine-pick]";
  /** What is a button of its own where a press could fall on a movable thing: a cell's Window, Start and Stop, a model's mark. */
  static OWN = ["[data-machine-own]", "[data-model-rate]"];
  /** The block of the model picked, where a cell's row stands: where a cell is taken from, and where a working one dropped stops. The block is
   *  inside the same pane as the list that picks which model it shows. */
  static BLOCK = '[data-t="machine-chosen"]';
  /** The pane the list stands in. Where it does not scroll (a narrow screen), the wheel moves the page. */
  static PANE = ".machine-main";
  /** The page's own body on a wide screen, which scrolls when the window is too low for the rack, the launch builder and the panes
   *  (machine.css); narrower, the page scrolls as one, and the document is what moves. */
  static PAGE = ".machine-page > .ui-win--page > .ui-win-body";

  /** What a press takes: the block, chip or cell's row it fell on — one rule for the click that chooses and the press that drags. A press on
   *  a button of its own there takes nothing, and only does what that button does. */
  static taken(target) {
    if (MachineDrag.OWN.some((own) => target?.closest?.(own))) return null;
    return target?.closest?.(MachineDrag.MOVABLE) || null;
  }

  constructor(plan = MACHINE_PLAN) {
    this.plan = plan;
    this.press = null;
    this.drag = null;
    this.grip = null;
    this.swallow = false;
    this.bound = false;
    this.tag = null;
  }

  /** A drag or a handle in hand: the board does not draw the page anew under it. */
  get busy() {
    return !!(this.drag || this.grip);
  }

  /**
   * @param cells () → the builder's word on each cell, by cellId (MachinePick.cells)
   * @param node () → the machine of the page, or null on any other page
   * @param place (facts, node) → where those facts lay the cell (CellFit)
   * @param chosenId () → the cellId of the cell chosen now
   * @param choose (cellId) → that cell chosen
   * @param patch () → the map drawn again
   * @param bring (cellId) → the cell's row in sight: its plan and its buttons are there
   * @param stop (cellId) → the cell's own Stop pressed, with its question
   * @param name (cellId) → the cell as the page names it (MachinePick.nameOf), for the tag under the pointer
   * @param notify (words) → said to the operator
   * @param nextFrame (fn) → fn called at the next frame; what it returns says one is waiting
   */
  bind(doc, { cells = () => new Map(), node = () => null, place = () => ({ verdict: "unknown", cards: [], ramGb: 0 }), chosenId = () => "", choose = () => {},
              patch = () => {}, bring = () => {}, stop = () => {}, name = (cellId) => String(cellId), notify = () => {},
              nextFrame = (fn) => globalThis.requestAnimationFrame?.(fn) || 0 } = {}) {
    if (this.bound || !doc?.addEventListener) return;
    this.bound = true;
    Object.assign(this, { doc, cells, node, place, chosenId, choose, patch, bring, stop, name, notify, nextFrame });
    doc.addEventListener("pointerdown", (e) => this.down(e), true);
    doc.addEventListener("pointermove", (e) => this.moved(e));
    doc.addEventListener("pointerup", (e) => this.up(e));
    doc.addEventListener("pointercancel", () => this.cancel());
    doc.addEventListener("keydown", (e) => this.key(e));
    // The click that ends a drag is not a choice.
    doc.addEventListener("click", (e) => {
      if (!this.swallow) return;
      this.swallow = false;
      e.stopPropagation?.();
      e.preventDefault?.();
    }, true);
    // The same plan without a pointer: the buttons on the chosen cell's row, for a keyboard and a touch screen.
    doc.addEventListener("click", (e) => {
      const el = e.target?.closest?.("[data-machine-place]");
      if (!el) return;
      e.preventDefault?.();
      this.placeAt(el.dataset.machinePlaceFor, el.dataset.machinePlace);
    });
  }

  /** The cell `cellId` laid on `target`: a plan, or the reason said. */
  placeAt(cellId, target) {
    const facts = this.factsOf(cellId);
    if (!facts || !this.node()) return;
    const found = this.attempt(String(cellId), facts.group === "holds", target, "");
    if (found.result.refused) {
      this.notify(t(found.result.refused));
      return;
    }
    this.plan.set(cellId, found.result, { evict: found.evict, moved: facts.group === "holds" });
    this.choose(cellId);
    this.patch();
    this.bring(cellId);
  }

  /** Where the cell `cellId` would lie on `target`, as it is or with `occupant` (a cellId) gone: a model that fits leaves what lies there
   *  alone; one that does not, dropped on a block, takes that block's place. {result, verdict, evict}. */
  attempt(cellId, moved, target, occupant) {
    const node = this.node();
    const facts = this.factsOf(cellId)?.fit || {};
    const own = occupant === cellId ? "" : occupant;
    const lay = (evict) => {
      const { after, room } = this.roomOf(node, [...evict, ...(moved ? [cellId] : [])]);
      const result = CellMove.of(facts).to(target, room);
      if (result.refused) return { result, verdict: "none", evict };
      const probe = new MachinePlan();
      probe.set(cellId, result, { evict, moved });
      return { result, verdict: this.place(probe.facts(facts), after).verdict, evict };
    };
    const found = lay([]);
    if (found.result.refused || !own || MachineDrag.fits(found.verdict) || !this.factsOf(own)?.stop) return found;
    const instead = lay([own]);
    return MachineDrag.lies(instead) ? instead : found;
  }

  /** Whether the cell lies where `found` (`attempt`) lays it: the move is not refused and it fits somewhere. One rule for the ring of the lane
   *  under the pointer and for every lane lit or dim while a drag lasts. */
  static lies(found) {
    return !found.result.refused && found.verdict !== "none";
  }

  /** Whether the cell in hand may lie on each lane of the machine as it is now, by the lane's id: the rule the lane under the pointer is
   *  judged by (`lies`), asked of every lane at once when the cell is taken, so the rack says where it may go before the pointer gets there —
   *  lit where it may, dim where it may not (the owner's choice for the launch builder, 2026-11-06; the cells of the list are carried the
   *  same way). null on no machine. */
  targetsOf(cellId, moved) {
    const node = this.node();
    if (!node) return null;
    const ids = [...MachineRoom.of(node).cards.map((c) => String(c.index)), "ram"];
    return Object.fromEntries(ids.map((id) => [id, MachineDrag.lies(this.attempt(cellId, moved, id, ""))]));
  }

  factsOf(cellId) {
    return this.cells().get(String(cellId));
  }

  /** The machine as this start would find it, and the moves' view of it. */
  roomOf(node, leaving) {
    const keeps = (server) => !!this.factsOf(server.cellId)?.fit?.keepsRam;
    const after = MachineRoom.without(node, leaving, keeps);
    return { after, room: MachineRoom.of(after) };
  }

  down(e) {
    this.swallow = false;
    if (e.button || !this.node()) return;
    const grip = e.target?.closest?.("[data-machine-grip]");
    if (grip) {
      e.preventDefault?.();
      e.stopPropagation?.();
      this.grip = { id: grip.dataset.machineGrip, from: Number(grip.dataset.machineGripFrom) || 0, whole: Number(grip.dataset.machineGripWhole) || 0 };
      return;
    }
    const el = MachineDrag.taken(e.target);
    if (!el) return;
    const facts = this.factsOf(el.dataset.machinePick);
    if (!facts) return;
    const standing = facts.group === "bench";
    if (standing ? !facts.launch : facts.group !== "holds" || !facts.stop) return;
    this.press = { cellId: String(el.dataset.machinePick), x: e.clientX, y: e.clientY, moved: !standing };
  }

  moved(e) {
    if (this.grip) {
      if (!e.buttons) return this.cancel();
      this.gripAt(e.clientX);
      return undefined;
    }
    if (this.press && !this.drag) {
      if (!e.buttons) { this.press = null; return undefined; }
      if (Math.abs(e.clientX - this.press.x) + Math.abs(e.clientY - this.press.y) < MachineDrag.SLOP) return undefined;
      this.begin(e);
    }
    if (this.drag) {
      if (!e.buttons) return this.cancel();
      e.preventDefault?.();
      this.follow(e.clientX, e.clientY);
      this.over(e.clientX, e.clientY);
      this.lean(e.clientX, e.clientY);
    }
    return undefined;
  }

  /** The pointer of a drag where it is now, and the pane on its way if it leans on an edge. One frame waits at a time. */
  lean(x, y) {
    const drag = this.drag;
    drag.pointer = { x, y };
    if (!drag.frame) drag.frame = this.nextFrame(() => this.leanStep(drag));
  }

  /** One frame of the pane moving: what lies under a pointer that stands still changes with it. At the pane's end it stops until the
   *  pointer moves again, and the drag's end ends it. The list's pane moves where the pointer leans on its edge; elsewhere the page does,
   *  where the pointer leans on the edge of what shows it: on a phone, or a window too low for the rack and the launch builder both, the
   *  rack is out of sight above the launch carried up to it (the owner, 2026-11-07: «вверх на видеокарты… пальцем или мышью»). */
  leanStep(drag) {
    drag.frame = 0;
    if (this.drag !== drag) return;
    for (const scroller of [this.paneOf(), this.pageOf()]) {
      const step = scroller ? Math.round(PaneLean.at(drag.pointer.y, scroller.top, scroller.bottom) * PaneLean.SPEED) : 0;
      if (!step) continue;
      const was = scroller.el.scrollTop;
      scroller.el.scrollTop = was + step;
      if (scroller.el.scrollTop === was) continue;
      this.over(drag.pointer.x, drag.pointer.y);
      drag.frame = this.nextFrame(() => this.leanStep(drag));
      return;
    }
  }

  /** The list's pane and where it shows, or null. */
  paneOf() {
    const el = this.doc.querySelector?.(MachineDrag.PANE);
    const box = el?.getBoundingClientRect?.();
    return box ? { el, top: box.top, bottom: box.bottom } : null;
  }

  /** What scrolls the page and where it shows: the page's body while it has more than it shows, else the document in the window; null
   *  where neither is known. */
  pageOf() {
    const body = this.doc.querySelector?.(MachineDrag.PAGE);
    const box = body && Number(body.scrollHeight) > Number(body.clientHeight) + 1 ? body.getBoundingClientRect?.() : null;
    if (box) return { el: body, top: box.top, bottom: box.bottom };
    const root = this.doc.scrollingElement;
    const height = Number(this.doc.defaultView?.innerHeight) || 0;
    return root && height ? { el: root, top: 0, bottom: height } : null;
  }

  begin() {
    const { cellId, moved } = this.press;
    this.drag = { cellId, moved, saved: this.plan.snapshot(), key: null, result: null };
    this.press = null;
    this.plan.dragging = true;
    this.plan.targets = this.targetsOf(cellId, moved);
    this.doc.documentElement?.classList?.add?.("machine-dragging");
    this.tag = this.doc.createElement?.("div") || null;
    if (this.tag) {
      this.tag.className = "machine-drag-tag";
      this.tag.textContent = String(this.name(cellId));
      this.doc.body?.appendChild?.(this.tag);
    }
  }

  follow(x, y) {
    if (this.tag?.style) this.tag.style.transform = `translate(${Math.round(x + 14)}px, ${Math.round(y - 12)}px)`;
  }

  /** What is under the pointer: {target, occupant} — the occupant the cellId of the block there — or {block: true} for the block of the
   *  model picked, or nothing. */
  under(x, y) {
    const el = this.doc.elementFromPoint?.(x, y);
    const lane = el?.closest?.('[data-t="machine-map-lane"]');
    if (lane) {
      const id = String(lane.dataset.tId || "");
      const block = el.closest?.('[data-t="machine-map-block"]');
      return { target: id === "ram" ? "ram" : id.replace(/^gpu-/, ""), occupant: block ? String(block.dataset.machinePick || "") : "" };
    }
    return el?.closest?.(MachineDrag.BLOCK) ? { block: true } : {};
  }

  /** What the drag says over `what`: a plan laid there, a refusal, or nothing. */
  over(x, y) {
    const what = this.under(x, y);
    const key = JSON.stringify(what);
    if (key === this.drag.key) return;
    this.drag.key = key;
    const { cellId, moved, saved } = this.drag;
    const node = this.node();
    this.plan.drop = "";
    this.plan.dropOk = true;
    this.drag.result = null;
    if (what.target !== undefined && node) {
      const found = this.attempt(cellId, moved, what.target, what.occupant);
      this.plan.drop = what.target;
      this.plan.dropOk = MachineDrag.lies(found);
      this.drag.result = found.result;
      if (found.result.refused) this.plan.restore(saved);
      else this.plan.set(cellId, found.result, { evict: found.evict, moved });
    } else {
      this.plan.restore(saved);
    }
    this.drag.block = !!what.block;
    this.patch();
  }

  static fits(verdict) {
    return ["cards", "card", "free", "unsized", "ram", "rides"].includes(verdict);
  }

  up() {
    if (this.grip) {
      this.grip = null;
      this.plan.dragging = false;
      this.patch();
      return;
    }
    this.press = null;
    if (!this.drag) return;
    const { cellId, moved, result, block, saved } = this.drag;
    this.finish();
    // The click that ends a drag comes at once, if it comes at all: a press and a release on different elements may give none, and
    // the next real click must not be taken for it.
    this.swallow = true;
    let stopping = false;
    const laid = !!result && !result.refused;
    if (laid) {
      this.choose(cellId);
    } else {
      this.plan.restore(saved);
      if (result?.refused) this.notify(t(result.refused));
      else stopping = block && moved;
    }
    // The cell's own Stop is pressed by a click too: pressed with the guard still up, the guard took it for the drag's last click
    // and a running cell dragged down stayed as it was (1.3.695, seen first on the real page).
    setTimeout(() => {
      this.swallow = false;
      if (stopping) this.stop(cellId);
    }, MachineDrag.CLICK_MS);
    this.patch();
    if (laid) this.bring(cellId);
  }

  cancel() {
    this.press = null;
    if (this.grip) {
      this.grip = null;
      this.patch();
      return undefined;
    }
    if (!this.drag) return undefined;
    const { saved } = this.drag;
    this.finish();
    this.plan.restore(saved);
    this.patch();
    return undefined;
  }

  finish() {
    this.drag = null;
    this.plan.dragging = false;
    this.plan.drop = "";
    this.plan.dropOk = true;
    this.plan.targets = null;
    this.doc.documentElement?.classList?.remove?.("machine-dragging");
    this.tag?.remove?.();
    this.tag = null;
  }

  /** The share a handle is asked for at this place on its bar. */
  gripAt(x) {
    const el = this.doc.querySelector?.(`[data-machine-grip="${String(this.grip.id).replace(/["\\]/g, "\\$&")}"]`);
    const bar = el?.closest?.(".ui-lane-line")?.querySelector?.(".ui-lane-bar")?.getBoundingClientRect?.();
    if (!bar || !(bar.width > 0)) return;
    this.setShare(this.grip.id, ((x - bar.left) / bar.width) * this.grip.whole - this.grip.from);
  }

  /** The chosen cell with a share of `id` set: a plan made from where it would lie now, when it has none yet. */
  setShare(id, want) {
    const cellId = String(this.chosenId());
    const facts = this.factsOf(cellId)?.fit;
    if (!facts) return;
    const mine = this.plan.cellId === cellId;
    const move = CellMove.of(mine ? this.plan.facts(facts) : facts);
    if (!move.sizable) return;
    const node = this.node();
    const leaving = mine ? this.plan.leaving() : [];
    const { after, room } = this.roomOf(node, leaving);
    const shares = mine && this.plan.shares ? this.plan.shares : MachineDrag.sharesOf(this.place(facts, after), room);
    this.plan.set(cellId, move.share(shares, id, want, room), { evict: mine ? this.plan.evict : [], moved: mine && this.plan.moved });
    this.patch();
  }

  /** The shares of where a cell would lie now. */
  static sharesOf(place, room) {
    const shares = Object.fromEntries([...room.cards.map((c) => [String(c.index), 0]), ["ram", Number(place?.ramGb) || 0]]);
    for (const c of place?.cards || []) shares[String(c.index)] = Number(c.gb) || 0;
    return shares;
  }

  /** Arrows on a focused handle, Escape out of a drag. */
  key(e) {
    if (e.key === "Escape" && this.drag) {
      this.cancel();
      return;
    }
    const grip = e.target?.closest?.("[data-machine-grip]");
    if (!grip) return;
    const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
    if (!step) return;
    e.preventDefault?.();
    const id = grip.dataset.machineGrip;
    const cellId = String(this.chosenId());
    const now = this.plan.cellId === cellId && this.plan.shares ? Number(this.plan.shares[id]) || 0 : Number(grip.dataset.machineGripHolds) || 0;
    this.setShare(id, now + step * MachineDrag.STEP_GB);
    this.doc.querySelector?.(`[data-machine-grip="${String(id).replace(/["\\]/g, "\\$&")}"]`)?.focus?.();
  }
}

export const MACHINE_DRAG = new MachineDrag();

/**
 * A plan carried out: those that give way stopped and waited for, the config saved, the cell started; each step's failure said, and
 * the plan kept so nothing is lost. Everything it touches is handed in, so a test drives it without a controller.
 */
export class MachinePlanStart {
  /** How long a cell is waited for to let go of its memory, ms. */
  static WAIT_MS = 120_000;
  static TICK_MS = 1500;
  /** How long a start is waited for to show on the topology, ms. The scout's next pulse says it; a start it never says is the board's
   *  usual business then, and the plan goes all the same. */
  static SEEN_MS = 15_000;

  /**
   * @param save ({cellId, config, cacheModels} | {hostId, config, cacheModels}) → the controller keeps the config
   *   (POST /api/topology/server-cell/save-config): for the cell named, or, with no cellId, for a new cell it makes on that machine —
   *   its answer then names the new cell (`cellId`)
   * @param act (cellId, action) → true when a cell was asked to start or stop; false when it was refused, the reason already said
   * @param phase (cellId) → the phase of a cell now, as the topology says, the topology read anew
   * @param name (cellId) → the cell as the page names it, for the words of a failure
   * @param pause (ms) → a wait
   */
  constructor({ save, act, phase, name = (cellId) => String(cellId), pause = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); }),
                now = () => Date.now() } = {}) {
    Object.assign(this, { save, act, phase, name, pause, now });
  }

  /** Whether a phase is a cell that stands and was asked for nothing. */
  static stands(phase) {
    return ["stopped", "reserved", ""].includes(String(phase || ""));
  }

  /** Whether a phase has let go of the memory. */
  static letGo(phase) {
    return MachinePlanStart.stands(phase) || String(phase) === "error";
  }

  async waitFor(cellId) {
    const until = this.now() + MachinePlanStart.WAIT_MS;
    for (;;) {
      if (MachinePlanStart.letGo(await this.phase(cellId))) return;
      if (this.now() >= until) throw new Error(t("machinePlanStuck", { cell: String(this.name(cellId)) }));
      await this.pause(MachinePlanStart.TICK_MS);
    }
  }

  /** Until the topology says the start, or the time is up. Drawn before that, the cell stands there with its old settings and a live
   *  Start button: 1.6 s on the stand with its pulse of 5 s (the settings told a plan of 11.0 + 17.4 GB as 12.2 + 16.3). */
  async waitSeen(cellId) {
    const until = this.now() + MachinePlanStart.SEEN_MS;
    while (MachinePlanStart.stands(await this.phase(cellId)) && this.now() < until) await this.pause(MachinePlanStart.TICK_MS);
  }

  /** The config saved, and the cell it was saved for: the plan's own (`cellId`), or — for the launch built under the map, which is no cell
   *  yet — the one the save made on `makeOn`, its machine, as the answer names it. A save that names no new cell is said, never started by a
   *  guess. */
  async saved(cellId, makeOn, body) {
    const answer = await this.save(makeOn ? { hostId: makeOn, ...body } : { cellId, ...body });
    if (!makeOn) return cellId;
    const made = String(answer?.cellId ?? "").trim();
    if (!made) throw new Error(t("machinePlanNoCell"));
    return made;
  }

  /** @param plan the plan, for the cell it names (MachinePlan.cellId); @param makeOn "" for a cell that is kept, or the machine the launch
   *  built under the map is made on — the plan then names the builder's key, and the save makes the cell; @param config the config as
   *  stored; @param cacheModels its own setting
   *  @param made (key, cellId) → heard as soon as the save made the launch's cell, `key` the one the plan was laid under: the plan is that
   *  cell's from then on (MachinePlan.becomes), whatever the start does next
   *  @returns whether the cell was asked to start; false when an action was refused. */
  async run({ plan, makeOn = "", config, cacheModels, made = () => {} }) {
    const key = plan.cellId;
    const leaving = plan.leaving();
    const fields = { ...plan.fields };
    for (const id of leaving) {
      if (!await this.act(id, "stop")) return false;
    }
    for (const id of leaving) await this.waitFor(id);
    plan.letGone();
    const id = await this.saved(key, makeOn, { config: { ...config, ...fields }, cacheModels: !!cacheModels });
    if (makeOn) {
      plan.becomes(id);
      made(key, id);
    }
    if (!await this.act(id, "start")) return false;
    await this.waitSeen(id);
    return true;
  }

  /** The plan's two buttons. `target` says what a start needs of the planned cell: {config, cacheModels, question, room}, and `makeOn`, the
   *  machine, for the launch being built, which the save makes — at once or as a promise (the launch is given its config by the cell form,
   *  add-model.js `formConfig`); `redraw` draws the map again; `made` (key, cellId) hears the launch's cell made (`run`). Refused or failed,
   *  the plan stays and the reason is said. */
  bind(doc, { plan = MACHINE_PLAN, target = () => null, confirm = async () => true, notify = () => {}, redraw = () => {}, made = () => {} } = {}) {
    if (this.bound || !doc?.addEventListener) return;
    this.bound = true;
    doc.addEventListener("click", async (e) => {
      if (e.target?.closest?.("[data-machine-plan-cancel]")) {
        e.preventDefault?.();
        plan.clear();
        redraw();
        return;
      }
      if (!e.target?.closest?.("[data-machine-plan-start]") || !plan.on || plan.busy || this.asking) return;
      e.preventDefault?.();
      // What the start needs may take a while (a form filled), and a second press in between is no second start.
      const asked = plan.cellId;
      this.asking = true;
      let what = null;
      try {
        what = await target(plan);
        if (!what || !(await confirm(what.question))) return;
      } finally {
        this.asking = false;
      }
      // The plan may have gone while the operator was asked (a drawing found its cell gone): nothing is started for it.
      if (!plan.on || plan.cellId !== asked) return;
      plan.begin(what.room);
      redraw();
      try {
        if (await this.run({ plan, makeOn: String(what.makeOn || ""), config: what.config, cacheModels: what.cacheModels, made })) plan.clear();
        else plan.end();
      } catch (err) {
        plan.end();
        notify(String(err?.message || err));
      }
      redraw();
    });
  }
}
