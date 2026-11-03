// The head of a machine's page: who the machine is, what it does now, and where its memory goes — the map the page leads with
// (variant В «Карта памяти» of the screens' redesign, the owner's choice of 2026-10-25; 1.3.630 drew variant А's head and band).
// A lane per card and one for the RAM, every cell that holds memory a block of its measured share, named inside while it is wide
// enough; under the lanes the cells on their way; under the map the list of models with every cell of the machine in them (the bench
// of cards that stood there is gone, the owner's choice Н1 of 2026-11-02: machine-models.js), a standing cell laid by the cell window's
// own plan where its model is known (part 3, 1.3.635); at their right the column of the machine's engines,
// its model disk, the incidents and its activity (part 4, 1.3.636). A click on a block, a chip or a cell's row in the list chooses the
// cell: its row in the list says what it does and holds and gives its window, its Start or Stop and the places it can be laid on, and a
// chosen stopped cell shows dashed on the lanes where it would go.
// Drawn from the parts (ui-parts.js). Every button carries the attributes the board's listeners already bind by (topology-render.js,
// remote-cells.js, card-fold.js), so an item of the "⋯", a Start or Stop of a cell's row or Add model does what its button did.
//
// What the head needs from the board's own module — a card's outside owners, how long a silent machine has been silent, what the
// board's builder said of each cell (its name, its window, its start and stop, its work, its size) — comes in as a parameter:
// topology-nodes.js draws the head, and the head importing it back would be a cycle.
import { t } from "./i18n.js";
import { CellMemory } from "./cell-memory.js";
import { CellSpeed } from "./cell-speed.js";
import { CellFields, CellModel } from "./cell-plan.js";
import { JOBS } from "./model-jobs.js";
import { ModelCopy, ModelLoad } from "./model-copy.js";
import { ModelRating } from "./model-rating.js";
import { CellMove, MACHINE_PLAN, MachineDrag, MachineRoom } from "./machine-plan.js";
import { CardFigures } from "./card-figures.js";
import { CardPin, CardRoom, FreeVramStart, PlacementPlan } from "./placement.js";
import { MachineModels } from "./machine-models.js";
import { Band, Button, Frame, Lane, Menu, Meter, Pill, RackLegend } from "./ui-parts.js";
import { escapeHtml } from "./utils.js";

const GIB = 2 ** 30;

/**
 * Where a stopped cell would go if it started now — parts 2 and 3 of variant В (the owner, 2026-10-25: "by size first, then the
 * exact one: the true size, and in colour where the model is and where the cache"). A llama.cpp cell whose model the library
 * knows is weighed whole — its files, its KV cache and its buffers under its fields (cell-plan.js CellModel) — and laid by the
 * cell window's own plan (placement.js PlacementPlan.from), which tells its weights from its cache on every card and in RAM.
 * Any other cell is weighed by what its runner takes — the figure measured for it, vLLM's share of its cards — or, failing
 * that, by its files, and the page says which wherever the figure shows. Where it lays it is its runner's, by the rules the
 * cell form follows — a way per kind, each a class of its own:
 *  - "plan": llama.cpp with its model's header — PlacementPlan, fitted, held or tensor, against the cards' free room now;
 *  - "spread": llama.cpp with only its files' size — over the cards its DEVICE names. Left to fit itself, in proportion to the
 *    room each card has past the margin its --fit-target leaves (PlacementPlan.limitsFrom) while the files fit there, else
 *    those cards full and the rest in RAM, as llama.cpp fits a model larger than its cards; with its split set by hand, on the
 *    cards or not at all;
 *  - "ram": it computes on the CPU — all of it in RAM;
 *  - "card": a runner that loads onto one card — the card its ENV pins, else card 0 (CardPin), whole or not at all; one that
 *    picks its device itself (the registry's autoDevice) goes to RAM when that card has no room;
 *  - "free": Strata — what its card has free less its reserve, while the card has its floor (FreeVramStart);
 *  - "asks": vLLM — the share of each card it takes (VllmPlacement, memory.js: the board's builder works them out), its weights
 *    cut evenly over them and the rest of the share its cache.
 * A cell whose size or card nobody knows has no place ("unknown"), and one the machine cannot hold now says "none" — never a
 * guess that it fits.
 */
export class CellFit {
  /** The fields of a cell's config the ways read, as the form holds them (CellFields: a box as "1" or "0"). */
  static FIELDS = ["ENV", "DEVICE", "FIT_TARGET", "TENSOR_SPLIT", "FIT", "N_GPU_LAYERS", "N_CPU_MOE", "CPU_MOE", "KV_OFFLOAD", "CPU_OFFLOAD_GB"];

  /** The way of the cell's runner, as the board's builder named it. */
  static of(facts = {}) {
    const Way = FITS[facts?.how] || CellFit;
    return new Way(facts || {});
  }

  /**
   * What the board's builder knows of a stopped cell's start, as the page reads it (topology-nodes.js, nodeServerCardHtml):
   * the way its runner lays it, what it weighs and by what, and the fields of its config that way reads.
   * @param how the runner's way (FITS); a llama.cpp cell's "spread" becomes "plan" when its model's header is known
   * @param bytes what the cell weighs by its files or its runner's figure, when nothing better is known
   * @param planned whether `bytes` is its runner's own figure
   * @param measured whether `bytes` is what the cell holds now: said as its runner's figure, unless a model's header says more
   * @param config the cell's stored config; `defaults` the controller's, behind an empty field (the form's reading)
   * @param row the runner's registry row
   * @param mode the split mode of a llama.cpp cell, "layer" or "tensor"
   * @param vllm a vLLM start (VllmPlacement)
   * @param models the library's rows by path (form.js modelsByPath), for a llama.cpp cell's model and projector
   */
  static facts({ how = "", bytes = null, planned = false, measured = false, config = {}, defaults = {}, row = {}, mode = "layer", vllm = null,
                 models = null, family = "", caps = null, onCard = "card", asksFor = null } = {}) {
    const plan = row?.vramPlan || {};
    const fields = CellFields.ofConfig(config, defaults);
    const rowOf = (key) => models?.get?.(fields.value(key)) || null;
    const model = models && ["spread", "ram"].includes(how)
      ? CellModel.of({ row: rowOf("MODEL_FILE"), mmprojRow: rowOf("MMPROJ_FILE"), fields }) : null;
    // Known is a model whose header gave its layers: one without them has no cache anyone counted, and is weighed by its files.
    const known = !!model && model.weightsGb > 0 && model.layers > 0;
    return {
      how: how === "spread" && known ? "plan" : how,
      bytes: vllm ? vllm.totalGb * GIB : known ? (model.weightsGb + model.kvGb + model.batchGb) * GIB : bytes,
      // vLLM says it keeps weights in RAM (the registry's keepsRam) only for the cell that leaves them there.
      source: vllm || planned ? "runner" : known ? "plan" : measured ? "runner" : "files", keepsRam: !!row?.keepsRam && (!vllm || vllm.ridesGb > 0),
      fields: Object.fromEntries(CellFit.FIELDS.map((key) => [key, fields.text(key)])), mode,
      model: known ? model : null,
      split: known ? { weightsGb: model.weightsGb, cacheGb: model.kvGb + model.batchGb } : null,
      floorMiB: Number(plan.floorMiB || 0), reserve: plan.reserveField ? fields.text(plan.reserveField) : "",
      asks: vllm ? CellFit.asksOf(vllm) : [],
      over: !!vllm?.weightsOver || !!vllm?.kvOver, ridesGb: vllm?.ridesGb || 0, orRam: !!row?.autoDevice, oneCard: !!row?.oneCard,
      // Where the rack may lay it (machine-plan.js CellMove): its family of runners, what it can compute on, how it lies on a card.
      family, cpuOk: !!caps?.cpu, gpuOk: caps ? !!caps.gpu : true, onCard, parallel: Number(vllm?.tp) > 1, asksFor,
    };
  }

  /** What a vLLM start asks of each card it takes, its weights cut evenly over them, less those that stay in RAM. */
  static asksOf(vllm) {
    const weightsPerCard = vllm.weightsGb > 0 && vllm.tp > 0 ? vllm.weightsOnCardGb : null;
    return vllm.cards.map((g, i) => ({ index: String(g.index), mib: vllm.perCardGb[i] * 1024,
                                       weightsMib: weightsPerCard === null ? null : Math.min(weightsPerCard, vllm.perCardGb[i]) * 1024 }));
  }

  constructor(facts = {}) {
    this.facts = facts;
    // A size of nothing is no size: a file nobody measured, a vLLM start that takes no card.
    const bytes = CardRoom.said(facts.bytes);
    this.bytes = bytes > 0 ? bytes : null;
  }

  /** A field of the cell's config, as the builder kept it. */
  field(key) {
    return String(this.facts.fields?.[key] ?? "");
  }

  /** What it weighs, GB, or null. */
  get needGb() {
    return this.bytes === null ? null : this.bytes / GIB;
  }

  nowhere(verdict, needGb = this.needGb) {
    return { verdict, cards: [], ramGb: 0, needGb };
  }

  /** What the machine's RAM has free, GB, or null when it does not say. */
  static ramFree(node) {
    const ram = node?.cpu?.ram || {};
    const total = CardRoom.said(ram.totalGb);
    const used = CardRoom.said(ram.usedGb);
    return total && used !== null ? Math.max(0, total - used) : null;
  }

  /** All of it in RAM, while the RAM has the room — its weights and its cache apart where the builder knew them. */
  inRam(node) {
    const need = this.needGb;
    const free = CellFit.ramFree(node);
    if (!(need > 0) || free === null) return this.nowhere("unknown");
    if (need > free) return this.nowhere("none");
    const split = this.facts.split;
    return { verdict: "ram", cards: [], ramGb: need, needGb: need, ...(split ? { ramWeightsGb: split.weightsGb, ramCacheGb: split.cacheGb } : {}) };
  }

  /** {verdict, cards: [{index, gb, weightsGb?, cacheGb?}], ramGb, ramWeightsGb?, ramCacheGb?, needGb}: verdict one of cards,
   *  card, free, spill, kvRam, ram, none, unsized (the card is known, what it takes there is not: gb 0, needGb null),
   *  unknown; the weights and the cache told apart where the way knows them. The base
   *  knows no way: a runner that lays its memory where nobody here can say (an engine's cell, a command's). */
  place() {
    return this.nowhere("unknown");
  }
}

class RamFit extends CellFit {
  place(node) {
    return this.inRam(node);
  }
}

class SpreadFit extends CellFit {
  place(node) {
    const need = this.needGb;
    if (!(need > 0)) return this.nowhere("unknown");
    const gpus = node?.gpus || [];
    // No card on the machine: llama.cpp computes on the CPU.
    if (!gpus.length) return this.inRam(node);
    const f = this.facts;
    const held = PlacementPlan.heldBy({ fit: this.field("FIT"), nGpuLayers: this.field("N_GPU_LAYERS"), tensorSplit: this.field("TENSOR_SPLIT"),
                                        nCpuMoe: this.field("N_CPU_MOE"), cpuMoe: this.field("CPU_MOE") });
    // A layer count set by hand, or experts sent to the CPU by hand: what stays on the cards is the model's layers' to say, and
    // the size of the files does not say it (the plan does, from the model's header).
    if (held === "moe" || (held === "layers" && PlacementPlan.fixedFrom(this.field("N_GPU_LAYERS"), Infinity) !== Infinity)) {
      return this.nowhere("unknown");
    }
    const named = PlacementPlan.devices(this.field("DEVICE"), gpus.map((g) => Number(g.index)));
    const cards = gpus.filter((g) => named.includes(Number(g.index))).map((g) => ({ index: Number(g.index), free: CardRoom.freeMiB(g) }))
      .sort((a, b) => a.index - b.index);
    if (!cards.length || cards.some((c) => c.free === null)) return this.nowhere("unknown");
    const tensor = f.mode === "tensor";
    const limits = PlacementPlan.limitsFrom({ mode: tensor ? "tensor" : "layer", fitTarget: this.field("FIT_TARGET"),
                                              tensorSplit: this.field("TENSOR_SPLIT"), cards: cards.map((c) => ({ index: c.index, freeGb: c.free / 1024 })) });
    const room = limits.reduce((sum, gb) => sum + gb, 0);
    const laid = (share) => cards.map((c, i) => ({ index: String(c.index), gb: share(limits[i]) })).filter((c) => c.gb > 0);
    if (need <= room) {
      const parts = laid((gb) => (need * gb) / room);
      return { verdict: parts.length > 1 ? "cards" : "card", cards: parts, ramGb: 0, needGb: need };
    }
    // Only a cell left to fit itself sends what its cards cannot hold to RAM; a split set by hand loads as written, or fails.
    if (tensor || held !== null) return this.nowhere("none");
    const free = CellFit.ramFree(node);
    if (free === null) return this.nowhere("unknown");
    const spill = need - room;
    return spill <= free ? { verdict: "spill", cards: laid((gb) => gb), ramGb: spill, needGb: need } : this.nowhere("none");
  }
}

/** llama.cpp with its model's header: the cell window's own plan, against the free room of the cards its DEVICE names now. */
class PlanFit extends SpreadFit {
  static VERDICTS = { fits: null, spill: "spill", kvRam: "kvRam", over: "none", ramShort: "none" };

  place(node) {
    const gpus = node?.gpus || [];
    // No card on the machine: llama.cpp computes on the CPU, its weights and its cache in RAM.
    if (!gpus.length) return this.inRam(node);
    const named = PlacementPlan.devices(this.field("DEVICE"), gpus.map((g) => Number(g.index)));
    const cards = gpus.filter((g) => named.includes(Number(g.index))).map((g) => ({ index: Number(g.index), free: CardRoom.freeMiB(g) }));
    if (!cards.length || cards.some((c) => c.free === null)) return this.nowhere("unknown");
    const placed = PlacementPlan.from({
      facts: { model: this.facts.model, mode: this.facts.mode, ramFreeGb: CellFit.ramFree(node), cores: 1,
               cards: cards.map((c) => ({ index: c.index, freeGb: c.free / 1024 })) },
      get: (key) => this.field(key),
    }).placed();
    if (!(placed.verdict in PlanFit.VERDICTS)) return this.nowhere("unknown");
    const parts = placed.cards.filter((c) => c.totalGb > 0)
      .map((c) => ({ index: String(c.index), gb: c.totalGb, weightsGb: c.weightsGb, cacheGb: c.kvGb + c.buffersGb }));
    const ram = placed.ram;
    const needGb = parts.reduce((sum, c) => sum + c.gb, 0) + ram.totalGb;
    const verdict = PlanFit.VERDICTS[placed.verdict] ?? (parts.length > 1 ? "cards" : "card");
    // A plan that does not fit — a card given more than its room, or more in RAM than the machine has free — draws nothing.
    if (verdict === "none") return this.nowhere("none", needGb);
    // Whole layers dealt out can be named; experts in RAM, or a tensor split where every card holds a part of every layer, cannot.
    const dealt = this.facts.mode === "tensor" || ram.expertLayers > 0 ? null
      : Object.fromEntries([["ram", ram.layers], ...placed.cards.map((c) => [String(c.index), c.layers])]);
    return { verdict, cards: parts, ramGb: ram.totalGb, ramWeightsGb: ram.weightsGb, ramCacheGb: ram.kvGb, needGb, ...(dealt ? { layers: dealt } : {}) };
  }
}

class CardFit extends CellFit {
  place(node) {
    const need = this.needGb;
    const gpus = node?.gpus || [];
    const index = CardPin.card(this.field("ENV"));
    const card = index === "" ? null : gpus.find((g) => String(g.index) === index);
    // A runner that picks its device itself computes on the CPU of a machine with no card.
    if (!card) return this.facts.orRam && !gpus.length ? this.inRam(node) : this.nowhere("unknown");
    // A server that runs on one card (the registry's oneCard) has its card before its size: the pin, else card 0, where the
    // start lands (CUDA_DEVICE_ORDER=PCI_BUS_ID). What it takes there is not known, and nothing is laid there as if it were —
    // the card is named and the lane says so (the owner, 2026-10-27: a whisper cell and a seamless one read "place not known"
    // on a machine whose 3090 they start on). Any other runner walks this way too — a command, a server that picks its device
    // — and its card is a guess until it has a size: "unknown".
    if (!(need > 0)) return this.facts.oneCard ? { verdict: "unsized", cards: [{ index, gb: 0 }], ramGb: 0, needGb: null } : this.nowhere("unknown");
    const free = CardRoom.freeMiB(card);
    if (free === null) return this.nowhere("unknown");
    if (need * 1024 <= free) return { verdict: "card", cards: [{ index, gb: need }], ramGb: 0, needGb: need };
    return this.facts.orRam ? this.inRam(node) : this.nowhere("none");
  }
}

class FreeFit extends CellFit {
  place(node) {
    const f = this.facts;
    const start = FreeVramStart.of({ floorMiB: f.floorMiB }, { env: this.field("ENV"), reserve: f.reserve, gpus: node?.gpus || [] });
    if (!start || CardRoom.freeMiB(start.card) === null) return this.nowhere("unknown", null);
    if (!start.fits) return this.nowhere("none", start.needMiB / 1024);
    return { verdict: "free", cards: [{ index: String(start.card.index), gb: start.addGb }], ramGb: 0, needGb: start.addGb };
  }
}

class AsksFit extends CellFit {
  place(node) {
    const asks = this.facts.asks || [];
    if (!asks.length) return this.nowhere("unknown");
    const gpus = node?.gpus || [];
    const free = asks.map((a) => CardRoom.freeMiB(gpus.find((g) => String(g.index) === String(a.index))));
    if (free.some((mib) => mib === null)) return this.nowhere("unknown");
    // Its weights not fitting the share it asks (VllmPlacement.weightsOver) fail its start as surely as a card short of it.
    if (this.facts.over || asks.some((a, i) => free[i] < a.mib)) return this.nowhere("none");
    // Weights left in RAM (CPU_OFFLOAD_GB) need the room there: a machine that says how much it has refuses them as a card would.
    const rides = Number(this.facts.ridesGb) || 0;
    const ram = node?.cpu?.ram;
    if (rides > 0 && Number.isFinite(ram?.usedGb) && rides > Number(ram.totalGb) - ram.usedGb) return this.nowhere("none");
    const cards = asks.map((a) => ({ index: String(a.index), gb: a.mib / 1024,
                                      ...(a.weightsMib === null || a.weightsMib === undefined ? {}
                                        : { weightsGb: a.weightsMib / 1024, cacheGb: (a.mib - a.weightsMib) / 1024 }) }));
    return { verdict: rides > 0 ? "rides" : cards.length > 1 ? "cards" : "card", cards, ramGb: rides, needGb: this.needGb };
  }
}

/** The ways, by the name the board's builder gives them. */
const FITS = { ram: RamFit, spread: SpreadFit, plan: PlanFit, card: CardFit, free: FreeFit, asks: AsksFit };

/**
 * How a machine's lanes share one scale: a gigabyte is as long on a card as in RAM, so the eye compares them, and the largest card's
 * bar takes the share of the row its size says, with what is left for the words beside the bars. A machine whose RAM dwarfs its cards
 * (or the other way round) would leave a bar too short to read or no room for the words: the cards' column stays within TRACK, and a
 * RAM that then would not fit the row on the same scale takes the whole row on a scale of its own (`shared` says which). Sizes nobody
 * reported take no part: a lane without one draws no bar.
 */
export class RackScale {
  static TRACK = { min: 38, max: 62 };
  /** Less room than this on a device, GB, is no room to offer a handle for. */
  static ROOM_GB = 0.5;

  /** @param cards the cards' sizes, in any one unit; @param ram the RAM's, in the same */
  constructor(cards = [], ram = null) {
    const sizes = (cards || []).map(Number).filter((n) => n > 0);
    this.largest = sizes.length ? Math.max(...sizes) : 0;
    this.ram = Number(ram) > 0 ? Number(ram) : 0;
    const whole = Math.max(this.largest, this.ram);
    const track = !this.largest ? 100 : Math.min(RackScale.TRACK.max, Math.max(RackScale.TRACK.min, (this.largest * 100) / whole));
    const onScale = this.largest && this.ram ? (this.ram * track) / this.largest : 100;
    this.track = RackScale.two(track);
    this.shared = onScale <= 100 + 1e-9;
    this.ramBar = this.shared ? RackScale.two(onScale) : 100;
  }

  static two(value) {
    return Math.round(value * 100) / 100;
  }

  /** The share of the row a card's bar takes, in percent. */
  cardBar(size) {
    return Number(size) > 0 && this.largest ? RackScale.two((Number(size) * this.track) / this.largest) : this.track;
  }
}

/**
 * The pictures at the left of the rack's lanes (the owner, 2026-11-02: "on the left I'd also like pictures of the graphics cards and the
 * RAM"; his choice «заливка»): a graphics card and a memory stick, filled. The label beside each says the same in words, so a screen reader
 * is spared them. Their colours are the page's, by the classes of their shapes (machine.css), and their box is fixed there: the words of
 * every lane start at one place, and a rack of six cards is as thin as it was.
 */
export class LanePicture {
  static PICTURES = {
    card: { width: 34, height: 20, shapes: '<rect class="is-body" x="1.5" y="3" width="27" height="13" rx="2"/>'
      + '<circle class="is-hollow" cx="9" cy="9.5" r="4.2"/><circle class="is-hollow" cx="21" cy="9.5" r="4.2"/>'
      + '<circle class="is-hub" cx="9" cy="9.5" r="1.6"/><circle class="is-hub" cx="21" cy="9.5" r="1.6"/>'
      + '<rect class="is-bracket" x="29" y="2" width="2.5" height="16"/><rect class="is-contact" x="5" y="16" width="14" height="2"/>' },
    ram: { width: 34, height: 18, shapes: '<path class="is-body" d="M1.5 3h31v9h-14v2h-3v-2h-14z"/>'
      + '<rect class="is-hollow" x="5" y="5.5" width="4" height="4"/><rect class="is-hollow" x="12" y="5.5" width="4" height="4"/>'
      + '<rect class="is-hollow" x="19" y="5.5" width="4" height="4"/><rect class="is-hollow" x="26" y="5.5" width="4" height="4"/>'
      + '<rect class="is-contact" x="3" y="12" width="12" height="2"/><rect class="is-contact" x="19" y="12" width="12" height="2"/>' },
  };

  static html(kind) {
    const { width, height, shapes } = LanePicture.PICTURES[kind];
    return `<span class="machine-lane-pic" data-machine-lane-pic="${kind}" aria-hidden="true"><svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">${shapes}</svg></span>`;
  }
}

/**
 * The lanes laid out as a rack (the owner's choice К1, 2026-10-31: "which part of the cards is taken by which model, and by which
 * part of it"; thin rows Д1 and the list П3, 2026-11-02: 429 px of them, and names beside each lane read as a heap). A lane is one row, its
 * blocks in the colours of their cells. What lies on the rack is said once, in the list beside it (RackLegend): each holder, how much in
 * all, where. Each piece still says its own words — which part of the cell it is, which layers, the price of RAM — in its hover and in the
 * hover of its row. A line sews one cell's pieces together across the lanes, passing a lane it has nothing on: drawn for what is planned,
 * chosen or under the pointer. Measured pieces say their measured figures; the chosen stopped cell's say what its way would lay there.
 */
export class MachineRack {
  /** Other processes get a note of their own from this size, GB; smaller, they are hatch and a hover. */
  static NOTE_OTHER_GB = 1;

  constructor(map) {
    this.map = map;
  }

  /** The owner of a block: the cell it belongs to, measured or to come, or "" for other processes. */
  static ownerOf(block) {
    return String(block.port || block.ghostOf || "");
  }

  /** The lanes each cell has a piece on: port → [lane's position], in the lanes' order. */
  static spread(lanes) {
    const spread = new Map();
    lanes.forEach((lane, i) => {
      if (!lane.total) return;
      for (const port of new Set(lane.blocks.map(MachineRack.ownerOf).filter(Boolean))) {
        spread.set(port, [...(spread.get(port) || []), i]);
      }
    });
    return spread;
  }

  /** Where the bar's free part starts, in percent of it: a line leaves the bar there, and crosses nothing that lies on it. */
  static freeFrom(lane) {
    return RackScale.two((Meter.cut(lane.total, lane.blocks) || []).reduce((sum, { width }) => sum + width, 0));
  }

  /** What a piece says of itself after its figure: which part of the cell it is, or how much of the device it takes; its runner. */
  partWords(i, gb, where, runner) {
    const n = where.length;
    const share = n > 1 ? t("machineNotePart", { i: where.indexOf(i) + 1, n }) : this.deviceShare(gb, this.lanes[i]);
    return [share, runner].filter(Boolean);
  }

  deviceShare(gb, lane) {
    const whole = lane.ram ? Number(lane.total) : Number(lane.total) / 1024;
    if (!(whole > 0)) return "";
    return t(lane.ram ? "machineNoteRam" : "machineNoteCard", { pct: Math.round((gb * 100) / whole) });
  }

  /** How fast a cell generates now, in the list's column: only while it answers a request. A held figure is no speed of now. */
  static speedOf(server) {
    const speed = new CellSpeed(server, true);
    return speed.working && speed.speed > 0 ? String(Math.round(speed.speed)) : "";
  }

  /** The note of a cell's piece on the lane at `i`. */
  note(i, port, where, ghost) {
    const lane = this.lanes[i];
    const blocks = lane.blocks.filter((b) => MachineRack.ownerOf(b) === port);
    const server = (this.map.node.servers || []).find((s) => String(s.port) === port);
    const facts = this.map.cells.get(port) || {};
    const coming = !!ghost && ghost.port === port;
    const value = blocks.reduce((sum, b) => sum + Number(b.value || 0), 0);
    const gb = lane.ram ? value : value / 1024;
    const figure = `${coming ? "≈" : ""}${MachineMap.gb(gb)} GB`;
    const layers = coming ? this.layerWords(ghost.place, lane) : "";
    // Strata's pieces are no parts of a whole: the card keeps the weights used most, and all of them stay in RAM, where the processor
    // computes those the card does not hold.
    const own = facts.fit?.how === "free" && where.length > 1 ? [t(lane.ram ? "machineNoteAllRam" : "machineNoteHot")]
      : this.partWords(i, gb, where, layers ? "" : String(facts.runner || ""));
    // A piece of llama.cpp's in RAM is computed there: the rack says so, it is the price of laying it there.
    const cpu = coming && lane.ram && where.length > 1 && facts.fit?.family === "llama" ? t("machineNoteCpu") : "";
    // vLLM's in RAM is computed on the card: it comes there for every pass. The opposite price, and the rack says it as plainly.
    const rides = lane.ram && facts.fit?.family === "vllm" ? t("machineNoteRides") : "";
    const words = [figure, ...own, layers, cpu, rides].filter(Boolean).join(" · ");
    const name = server ? this.map.cellName(server) : `:${port}`;
    return { port, name, shown: String(facts.name || "").trim() || `:${port}`, gb, coming, words, title: `${name} · ${words}`, on: this.map.chosen === port,
             speed: server ? MachineRack.speedOf(server) : "",
             ...(coming ? { kind: "estimate" } : { series: blocks[0].series }) };
  }

  /** Which of the model's layers a piece to come holds, while the plan deals whole layers: llama.cpp keeps the first in RAM, and
   *  then the cards take them in order. Nothing when it cannot say: experts in RAM, or a tensor split, leave no range of layers. */
  layerWords(place, lane) {
    const dealt = place?.layers;
    if (!dealt) return "";
    const key = lane.ram ? "ram" : lane.cardIndex;
    const here = Number(dealt[key] || 0);
    if (!(here > 0)) return "";
    let from = Number(dealt.ram || 0);
    if (lane.ram) from = 0;
    else {
      for (const card of this.lanes.filter((l) => !l.ram)) {
        if (card === lane) break;
        from += Number(dealt[card.cardIndex] || 0);
      }
    }
    return t("machineNoteLayers", { from, to: from + here - 1 });
  }

  /** The notes of the lane at `i`: its cells' pieces in the order of its blocks, and other processes large enough to name. */
  notes(i, spread, ghost) {
    const lane = this.lanes[i];
    if (!lane.total) return [];
    const seen = new Set();
    const notes = [];
    for (const block of lane.blocks) {
      const port = MachineRack.ownerOf(block);
      if (!port) {
        const gb = lane.ram ? Number(block.value) : Number(block.value) / 1024;
        if (!lane.ram && gb >= MachineRack.NOTE_OTHER_GB) notes.push({ port: "", name: block.name, shown: block.name, gb, words: block.figure, title: block.title, kind: "other" });
        continue;
      }
      if (seen.has(port)) continue;
      seen.add(port);
      notes.push(this.note(i, port, spread.get(port) || [i], ghost));
    }
    return notes;
  }

  /** The lines of the lane at `i`: one per cell with pieces on several lanes, in its own slot, from its first lane to its last. */
  links(i, spread, ghost) {
    const lines = [...spread.entries()].filter(([, where]) => where.length > 1)
      .sort(([a], [b]) => Number(!!ghost && ghost.port === b) - Number(!!ghost && ghost.port === a));
    return lines.flatMap(([port, where], slot) => {
      const first = where[0];
      const last = where[where.length - 1];
      if (i < first || i > last) return [];
      const here = where.includes(i);
      const coming = !!ghost && ghost.port === port;
      const block = this.lanes[where[0]].blocks.find((b) => MachineRack.ownerOf(b) === port);
      return [{ slot, up: i > first, down: i < last, here, from: here ? MachineRack.freeFrom(this.lanes[i]) : 0, owner: port, shown: this.map.chosen === port,
                ...(coming ? { kind: "estimate" } : { series: block.series }) }];
    });
  }

  /** The lanes as they stand on the rack. The last is the RAM. */
  laid(lanes, ghost = null) {
    this.lanes = lanes.map((lane, i) => ({ ...lane, ram: i === lanes.length - 1,
                                           cardIndex: i === lanes.length - 1 ? "" : String((this.map.node.gpus || [])[i]?.index ?? "") }));
    const cards = this.lanes.filter((l) => !l.ram);
    const scale = new RackScale(cards.map((l) => (l.total || 0) / 1024), this.lanes[this.lanes.length - 1].total);
    const spread = MachineRack.spread(this.lanes);
    const slots = [...spread.values()].filter((where) => where.length > 1).length;
    const plan = this.map.plan;
    return this.lanes.map((lane, i) => {
      const id = lane.ram ? "ram" : lane.cardIndex;
      const drop = plan && plan.dragging && plan.drop === id ? ` data-machine-drop="${plan.dropOk ? "ok" : "no"}"` : "";
      const notes = this.notes(i, spread, ghost);
      const told = (block) => {
        const note = block.ghostOf ? notes.find((n) => n.port === block.ghostOf) : null;
        return { ...block, owner: MachineRack.ownerOf(block), title: note ? `${note.title} · ${block.here}` : block.title };
      };
      return {
        ...lane,
        attrs: `${lane.attrs}${drop}`,
        rack: { bar: lane.ram ? scale.ramBar : scale.cardBar((lane.total || 0) / 1024), slots },
        blocks: lane.blocks.map(told),
        notes,
        links: this.links(i, spread, ghost),
        grips: this.grips(i, ghost),
      };
    });
  }

  /** Where a holder lies, as a word: the cards in runs, "GPU 1–4", and the RAM. */
  static whereWords(lanes) {
    const cards = lanes.filter((lane) => !lane.ram).map((lane) => Number(lane.cardIndex)).sort((a, b) => a - b);
    const runs = [];
    for (const card of cards) {
      const run = runs[runs.length - 1];
      if (run && run[1] === card - 1) run[1] = card;
      else runs.push([card, card]);
    }
    const said = runs.map(([from, to]) => (from === to ? `${from}` : `${from}–${to}`)).join(", ");
    return [said ? `GPU ${said}` : "", lanes.some((lane) => lane.ram) ? "RAM" : ""].filter(Boolean).join(" + ");
  }

  /** The rows of the list beside the lanes, from what the laid lanes say: each holder once — what is to come on top, then the cells
   *  the largest first, then the other processes large enough to name. */
  static legend(lanes) {
    const holders = new Map();
    for (const lane of lanes) {
      for (const note of lane.notes || []) {
        const key = note.port || `other:${note.name}`;
        const holder = holders.get(key) || { note, gb: 0, pieces: [] };
        holder.gb += note.gb;
        holder.pieces.push({ lane, note });
        holders.set(key, holder);
      }
    }
    const rank = ({ note }) => (note.coming ? 0 : note.port ? 1 : 2);
    return [...holders.values()].sort((a, b) => rank(a) - rank(b) || b.gb - a.gb || Number(a.note.port) - Number(b.note.port)).map(({ note, gb, pieces }) => {
      const figure = `${note.coming ? "≈" : ""}${MachineMap.gb(gb)}`;
      const title = [`${note.port ? note.name : note.shown} · ${figure} GB`, ...pieces.map(({ lane, note: piece }) => `${lane.label}: ${piece.words}`)].join("\n");
      const id = escapeHtml(note.port);
      return { name: note.shown, figure, where: MachineRack.whereWords(pieces.map(({ lane }) => lane)), speed: note.speed || "", owner: note.port, title, on: !!note.on,
               ...(note.coming ? { kind: "estimate" } : note.port ? { series: note.series } : { kind: "other" }),
               ...(note.port ? { pick: `data-machine-pick="${id}" data-t="machine-map-legend" data-t-id="${id}"` } : { attrs: 'data-t="machine-map-legend-other"' }) };
    });
  }

  /** The handles of the lane at `i`: the chosen cell's share of it, for a cell whose share can be set by hand — filled where it has a
   *  piece, hollow where the device has room for one. Not while a drag is in hand: the plan under it is not settled. */
  grips(i, ghost) {
    const lane = this.lanes[i];
    const move = ghost && CellMove.of(this.map.factsOf(ghost.port));
    if (!ghost || !lane.total || this.map.plan?.dragging || !move.sizable || !move.canSet(lane.ram ? "ram" : lane.cardIndex)) return [];
    const unit = lane.ram ? 1 : 1024;
    const mine = lane.blocks.filter((b) => b.ghostOf === ghost.port);
    const holds = mine.reduce((sum, b) => sum + Number(b.value || 0), 0) / unit;
    const from = lane.blocks.filter((b) => b.ghostOf !== ghost.port).reduce((sum, b) => sum + Number(b.value || 0), 0) / unit;
    const whole = Number(lane.total) / unit;
    if (!(holds > 0) && whole - from < RackScale.ROOM_GB) return [];
    const id = lane.ram ? "ram" : lane.cardIndex;
    return [{ at: MachineRack.freeFrom(lane), on: holds > 0, title: t(holds > 0 ? "machineGripSet" : "machineGripAdd", { device: lane.label }),
              attrs: `data-machine-grip="${escapeHtml(id)}" data-machine-grip-from="${RackScale.two(from)}" data-machine-grip-whole="${RackScale.two(whole)}"`
                + ` data-machine-grip-holds="${RackScale.two(holds)}" data-t="machine-map-grip" data-t-id="${escapeHtml(id)}"` }];
  }
}

/**
 * Where a machine's memory goes: a lane per card and one for the RAM, each the cells that hold it — a block in a colour per cell,
 * the same on every lane, a button that chooses it — what other processes hold hatched, by name where the scout names them, and how
 * much is free. Measured figures only: a card's are the cells' processes on it (`gpuMem`, the controller's sum of the compute apps
 * by pid); a lane whose size the scout does not report draws no bar and says so. The RAM's cells are the ones that hold no card: a
 * cell on a card maps its model file, the scout's RSS counts those pages, and the machine's "used" (MemTotal − MemAvailable) does
 * not — drawn, they would fill the RAM the machine has free. A cell that holds memory and is on no lane — nobody measured it — is
 * named under the lanes, so none that runs is missing from the map, and so are the cells on their way. A chosen stopped cell is
 * drawn dashed where it would go (CellFit), and the list of models under the map holds every cell, each saying what it does now by
 * the rules here (benchSize, benchVerdict: "the bench" is what the code calls the cells of the machine, and those that stand).
 */
export class MachineMap {
  static SERIES = 6;
  static GIB = GIB;
  /** The phases of a cell on its way to holding memory, or out of it: copying its model, starting, loading, stopping. */
  static COMING = ["downloading", "starting", "loading", "resolving", "stopping"];

  static number(value) {
    return CardRoom.said(value);
  }

  static gb(value) {
    return value.toFixed(1);
  }

  static phase(server) {
    return String(server?.phase || server?.status?.phase || "stopped");
  }

  /** Where a cell stands on the page: on the lanes while it holds memory, under them on its way, else only in the list ("bench"). One
   *  rule for the map and the board's builder (topology-nodes.js) — what it hands the head of each cell names this group. */
  static groupOf(phase) {
    if (CellMemory.holds(phase)) return "holds";
    return MachineMap.COMING.includes(String(phase || "")) ? "coming" : "bench";
  }

  /** A card's maker's words stand out of its name in a lane's label: "RTX 5090". */
  static cardName(name) {
    return String(name || "").replace(/^NVIDIA\s+(GeForce\s+)?/i, "").trim();
  }

  /**
   * @param node the machine as the topology gives it
   * @param owners (card) → [{name, engine, mib}]: what holds the card that is no cell (topology-nodes.js, gpuOutsideOwners)
   * @param cells port → {key, name, stop, stopTitle, launch, playTitle, window, group, failed, reason, crashed, unreachable, reserved, jobs,
   *   runner, fit, ctx, repo, model, rating}: what the board's builder said of each cell (MachinePick.know)
   * @param chosen the port chosen on the map, or ""
   */
  constructor(node, { owners = () => [], cells = new Map(), chosen = "", plan = null } = {}) {
    this.owners = owners;
    this.cells = cells instanceof Map ? cells : new Map();
    // A plan in hand (machine-plan.js): the map draws the machine as the plan would leave it, with its cell chosen.
    this.plan = plan?.on ? plan : null;
    this.node = this.plan
      ? MachineRoom.without(node || {}, this.plan.leaving(), (server) => !!this.cells.get(String(server.port))?.fit?.keepsRam)
      : node || {};
    this.chosen = this.plan ? this.plan.port : String(chosen ?? "");
  }

  /** What the builder said of how a cell starts, as the plan would have it. */
  factsOf(port) {
    const facts = this.cells.get(String(port))?.fit;
    return this.plan?.port === String(port) ? this.plan.facts(facts) : facts;
  }

  /** Every cell whose processes hold memory now, by port, each with its colour: the same cell, the same colour on every lane. */
  held() {
    return (this.node.servers || [])
      .filter((s) => s && s.port && CellMemory.holds(MachineMap.phase(s)))
      .sort((a, b) => Number(a.port) - Number(b.port))
      .map((server, i) => ({ server, series: (i % MachineMap.SERIES) + 1 }));
  }

  /** The cells on the lanes: those that hold memory, less those a plan would have let go. */
  holders() {
    return this.held().filter(({ server }) => !server.leaving);
  }

  /** The cells on their way, by port. */
  coming() {
    return (this.node.servers || []).filter((s) => s && s.port && MachineMap.groupOf(MachineMap.phase(s)) === "coming")
      .sort((a, b) => Number(a.port) - Number(b.port));
  }

  /** The cells that stand — stopped, failed, a port with no model — the largest first by what each would take now, the ones
   *  nobody weighed last. */
  standing() {
    const size = new Map();
    const cells = (this.node.servers || []).filter((s) => s && s.port && MachineMap.groupOf(MachineMap.phase(s)) === "bench");
    for (const server of cells) size.set(server, this.fit(server).needGb);
    return cells.sort((a, b) => (size.get(b) ?? -1) - (size.get(a) ?? -1) || Number(a.port) - Number(b.port));
  }

  /** The cells the list under the map says a word on: every cell of the machine — the ones that work, then the ones on their way, then
   *  the ones that stand. The bench that stood there held the standing ones only, and a cell started from it left it (the owner,
   *  2026-10-26: "the running cells — why are they taken away from here? don't take them away, show them, and show that they load or run"). */
  bench() {
    return this.everyCell();
  }

  /** Whether a cell works or is on its way: what opens its model's row in the list by itself (MachineModelsChoice.opens). */
  works(server) {
    return MachineMap.groupOf(MachineMap.phase(server)) !== "bench";
  }

  static onCards(server) {
    return Object.values(server?.gpuMem || {}).some((mib) => CardRoom.said(mib) > 0);
  }

  /** A cell as its block and its panel name it: the port and the name the board shows ("" while the builder said none). */
  cellName(server) {
    const name = String(this.cells.get(String(server.port))?.name || "").trim();
    return `:${server.port}${name ? ` ${name}` : ""}`;
  }

  /** Where the chosen cell would go, while it is one that stands: {port, place, words}; else null. */
  ghost() {
    const server = this.plan ? (this.node.servers || []).find((s) => String(s.port) === this.plan.port)
      : this.standing().find((s) => String(s.port) === this.chosen);
    return server ? { port: String(server.port), place: this.fit(server), words: this.sizeWords(server) } : null;
  }

  /** Where a cell would go now, by its runner's way (CellFit) and the plan laid for it. */
  fit(server) {
    const room = this.plan?.port === String(server.port) && this.plan.room ? this.plan.room : this.node;
    return CellFit.of(this.factsOf(server.port)).place(room);
  }

  /** The dashed blocks of the chosen cell on one lane: its weights and, paler, its cache and buffers where its way tells them
   *  apart, else one block of its part there; what it weighs and by what in their hover. `scale` turns GB into the lane's own
   *  unit (MiB on a card, GB in RAM). */
  ghostBlocks(ghost, part, scale) {
    return this.ghostParts(ghost, part, scale).map((b) => ({ ...b, ghostOf: ghost.port }));
  }

  ghostParts(ghost, part, scale) {
    const cell = `:${ghost.port}`;
    const name = t("machineGhost", { cell });
    const gb = (v) => `≈${MachineMap.gb(v)} GB`;
    const split = Number.isFinite(part?.weightsGb) && Number.isFinite(part?.cacheGb);
    const here = split ? t("machineGhostSplit", { weights: MachineMap.gb(part.weightsGb), cache: MachineMap.gb(part.cacheGb) }) : gb(part.gb);
    const title = `${name} · ${here} · ${ghost.words}`;
    const short = (v) => `≈${MachineMap.gb(v)}`;
    if (!split) return part.gb > 0 ? [{ value: part.gb * scale, kind: "estimate", name, figure: gb(part.gb), short: short(part.gb), title, here: ghost.words }] : [];
    return [{ value: part.weightsGb * scale, kind: "estimate", name, figure: gb(part.weightsGb), short: short(part.weightsGb), title, here },
            { value: part.cacheGb * scale, kind: "estimate-cache", name: t("machineGhostCache", { cell }), figure: gb(part.cacheGb), short: short(part.cacheGb), title, here }]
      .filter((b) => b.value > 0);
  }

  /** The figures at the end of a device's row, as the monitor's tick fills them (charts.js drawNodeTelemetry): `keys` its keys by
   *  column, `words` what they read now. A press opens the machine's chart of that figure. */
  rowMetrics(device, columns) {
    const id = String(this.node.id ?? "");
    return columns.map(({ column, key, word, chart }) => (key === null ? {} : {
      word, cls: `is-${column}`,
      attrs: `data-t="machine-map-metric" data-t-id="${escapeHtml(`${device}:${column}`)}"${chart ? ` data-machine-chart="${escapeHtml(`node:${id}:${chart}`)}"` : ""}`,
      valAttrs: `data-node-metric-val="${escapeHtml(`${id}:${key}`)}"`, sparkAttrs: `data-node-metric-spark="${escapeHtml(`${id}:${key}`)}"`,
    }));
  }

  /** How much of a device is free, GB, and after what is to come on it: then it is an estimate, and says so. */
  static freeWords(free, coming) {
    return t("machineLaneFree", { gb: `${coming > 0 ? "≈" : ""}${MachineMap.gb(Math.max(0, free - coming))}` });
  }

  /** A cell's block: its share, its colour, its words, and the button that chooses it. */
  block(server, series, value, gb, title) {
    const port = escapeHtml(String(server.port));
    const name = this.cellName(server);
    return { value, series, name, figure: `${MachineMap.gb(gb)} GB`, short: MachineMap.gb(gb), on: this.chosen === String(server.port), port: String(server.port),
             title: t("machineBlockChoose", { cell: `${name} · ${MachineMap.gb(gb)} GB${title ? ` · ${title}` : ""}` }),
             pick: `data-machine-pick="${port}" data-t="machine-map-block" data-t-id="${port}"` };
  }

  card(g, holders, ghost) {
    const index = String(g?.index ?? "?");
    const total = CardRoom.said(g?.memoryTotalMiB);
    const used = CardRoom.said(g?.memoryUsedMiB);
    const blocks = [];
    let cells = 0;
    for (const { server, series } of holders) {
      const mib = CardRoom.said((server.gpuMem || {})[index]);
      if (!(mib > 0)) continue;
      cells += mib;
      blocks.push(this.block(server, series, mib, mib / 1024, ""));
    }
    const outside = (this.owners(g) || []).map((o) => {
      const gb = MachineMap.gb(Number(o.mib) / 1024);
      const name = String(o.name || t("machineMapOther"));
      return { value: Number(o.mib), kind: "other", name, short: name, figure: `${gb} GB`, title: `${name} · ${gb} GB` };
    });
    const named = outside.reduce((sum, o) => sum + o.value, 0);
    // The rest of what the card says it holds is no cell's and no process the scout could name: the driver, a display.
    const rest = used === null ? 0 : Math.max(0, used - cells - named);
    if (rest >= 64) {
      const gb = MachineMap.gb(rest / 1024);
      outside.push({ value: rest, kind: "other", name: t("machineMapOther"), short: t("machineMapOther"), figure: `${gb} GB`, title: `${t("machineMapOther")} · ${gb} GB` });
    }
    const here = ghost?.place.cards.find((c) => c.index === index);
    const dashed = here ? this.ghostBlocks(ghost, here, 1024) : [];
    // The chosen cell starts on this card, and how much it takes is not known: no block is drawn, the lane says it in words.
    const unsized = here && ghost.place.verdict === "unsized" ? t("machineGhostUnsized", { cell: `:${ghost.port}` }) : "";
    const temp = CardRoom.said(g?.temperatureC);
    const name = MachineMap.cardName(g?.name);
    return {
      label: `GPU ${index}`,
      side: [name, total ? `${MachineMap.gb(total / 1024)} GB` : "", temp === null ? "" : `${temp} °C`].filter(Boolean).join(" · "),
      free: total && used !== null ? MachineMap.freeWords(Math.max(0, total - used) / 1024, Number(here?.gb) || 0) : "",
      total: total || null,
      blocks: [...outside, ...blocks, ...dashed],
      foot: total ? unsized : t("machineMapNoCard"),
      pic: LanePicture.html("card"),
      attrs: `data-t="machine-map-lane" data-t-id="gpu-${escapeHtml(index)}"`,
      metrics: this.rowMetrics(`gpu-${index}`, [
        { column: "load", key: `gpu:${index}`, chart: "gpu", word: CardFigures.load(CardRoom.said(g?.utilizationGpuPct)) },
        { column: "memory", key: `mem:${index}`, chart: "vram", word: CardFigures.memory(used === null ? null : used / 1024, total ? total / 1024 : null) },
        { column: "power", key: `power:${index}`, chart: "power", word: CardFigures.power(CardRoom.said(g?.powerDrawW)) },
      ]),
    };
  }

  ram(holders, ghost) {
    const cpu = this.node.cpu || {};
    const ram = cpu.ram || {};
    const total = CardRoom.said(ram.totalGb);
    const used = CardRoom.said(ram.usedGb);
    const blocks = [];
    let drawn = 0;
    for (const { server, series } of holders) {
      // A runner that keeps its weights in RAM (the registry's keepsRam: Strata) means its RSS: that is its own piece, card or no card.
      if (MachineMap.onCards(server) && !this.cells.get(String(server.port))?.fit?.keepsRam) continue;
      const bytes = CardRoom.said(server.ramBytes);
      if (!(bytes > 0)) continue;
      // A cell is never drawn past what the machine says it uses: the RSS of a model file mapped twice is in both cells.
      const gb = Math.min(bytes / GIB, used === null ? bytes / GIB : Math.max(0, used - drawn));
      if (!(gb > 0)) continue;
      drawn += gb;
      blocks.push(this.block(server, series, gb, bytes / GIB, t("machineMapRss")));
    }
    const rest = used === null ? 0 : Math.max(0, used - drawn);
    const system = rest > 0.05 ? [{ value: rest, kind: "other", name: t("machineMapSystem"), short: t("machineMapSystemShort"), figure: `${MachineMap.gb(rest)} GB`,
                                    title: `${t("machineMapSystem")} · ${MachineMap.gb(rest)} GB` }] : [];
    const p = ghost?.place;
    const dashed = p && p.ramGb > 0 ? this.ghostBlocks(ghost, { gb: p.ramGb, weightsGb: p.ramWeightsGb, cacheGb: p.ramCacheGb }, 1) : [];
    const load = CardRoom.said(cpu.loadPct);
    return {
      label: "RAM",
      side: [total ? `${MachineMap.gb(total)} GB` : "", load === null ? "" : `CPU ${load}%`].filter(Boolean).join(" · "),
      free: total && used !== null ? MachineMap.freeWords(Math.max(0, total - used), Number(p?.ramGb) || 0) : "",
      total: total || null,
      blocks: [...system, ...blocks, ...dashed],
      foot: total ? "" : t("machineMapNoRam"),
      pic: LanePicture.html("ram"),
      attrs: 'data-t="machine-map-lane" data-t-id="ram"',
      metrics: this.rowMetrics("ram", [
        { column: "load", key: "cpu", word: CardFigures.load(load) },
        { column: "memory", key: "ram", word: CardFigures.memory(used, total) },
        { column: "power", key: null },
      ]),
    };
  }

  lanes() {
    const holders = this.holders();
    const ghost = this.ghost();
    return new MachineRack(this).laid([...(this.node.gpus || []).map((g) => this.card(g, holders, ghost)), this.ram(holders, ghost)], ghost);
  }

  /** The cells that hold memory and are on no lane: nobody measured what they hold — the scout said no RSS, no card was read. */
  unplaced(lanes = this.lanes()) {
    const placed = new Set(lanes.flatMap((lane) => (lane.total ? lane.blocks : []).filter((b) => b.port).map((b) => b.port)));
    return this.holders().filter(({ server }) => !placed.has(String(server.port)));
  }

  chip(server, hook, words = "") {
    const port = escapeHtml(String(server.port));
    return new Pill({ text: `${this.cellName(server)}${words ? ` · ${words}` : ""}`, on: this.chosen === String(server.port),
                      attrs: `data-machine-pick="${port}" data-t="${hook}" data-t-id="${port}"` }).html();
  }

  unplacedHtml(lanes) {
    const cells = this.unplaced(lanes);
    if (!cells.length) return "";
    return `<div class="machine-map-unplaced" data-t="machine-map-unplaced"><span>${escapeHtml(t("machineMapUnplaced"))}</span>`
      + `${cells.map(({ server }) => this.chip(server, "machine-map-unplaced-cell")).join("")}</div>`;
  }

  /** What a cell on its way is doing, in the words its line and card say it. */
  comingWords(server) {
    const phase = MachineMap.phase(server);
    if (phase === "downloading") return ModelCopy.line(ModelCopy.now(server), server.downloadingFile || t("topologyRemoteDownloading"));
    if (phase === "stopping") return t("machineComingStopping");
    // A start whose process already reads its model says how far, how fast and how long (scout 2.43, ModelLoad).
    const words = t(phase === "loading" || phase === "resolving" ? "topologyRemoteLoading" : "topologyRemoteStarting");
    const load = ModelLoad.now(server);
    return load ? ModelCopy.line(load, words) : words;
  }

  /** The cells on their way under the lanes, a line each way: the ones starting, then the ones stopping, each line said what it
   *  is (1.3.657; the owner, 2026-10-26: "and where does one see which cell is starting?" — the line said "On their way:", and
   *  the band "Starting 1" named no cell). */
  comingHtml() {
    const cells = this.coming();
    const line = (list, words) => (list.length
      ? `<div class="machine-map-coming" data-t="machine-map-coming"><span>${escapeHtml(t(words))}</span>`
        + `${list.map((server) => this.chip(server, "machine-map-coming-cell", this.comingWords(server))).join("")}</div>` : "");
    const stopping = (server) => MachineMap.phase(server) === "stopping";
    return line(cells.filter((server) => !stopping(server)), "machineMapStarting") + line(cells.filter(stopping), "machineMapStopping");
  }

  lanesHtml(lanes = this.lanes()) {
    const heads = Lane.heads([t("machineColLoad"), t("machineColMemory"), t("machineColPower")], lanes[0]?.rack?.slots);
    return `<div class="machine-rack"><div class="machine-rack-lanes">${heads}${lanes.map((lane) => new Lane(lane).html()).join("")}</div>`
      + `${new RackLegend({ rows: MachineRack.legend(lanes), empty: t("machineLegendEmpty"), heads: [t("machineColGb"), t("machineColSpeed")] }).html()}</div>${this.unplacedHtml(lanes)}${this.comingHtml()}`;
  }

  /** What a cell holds, as its panel says it: the cards' share, else its RSS, else that nobody measured it — the lanes' own figures. */
  memoryWords(server) {
    const cards = Object.values(server?.gpuMem || {}).map((mib) => CardRoom.said(mib)).filter((mib) => mib > 0)
      .reduce((sum, mib) => sum + mib, 0);
    if (cards > 0) return t("machineMemCards", { gb: MachineMap.gb(cards / 1024) });
    const bytes = CardRoom.said(server?.ramBytes);
    return bytes > 0 ? t("machineMemRam", { gb: MachineMap.gb(bytes / GIB) }) : t("machineMemUnmeasured");
  }

  /** What a stopped cell weighs, and by what: its files, its cache and its buffers (the plan), what its runner takes, or its
   *  files alone — and then it says the cache is not counted. A runner that sizes itself to its card's free memory (Strata)
   *  says so instead of a figure, and one that keeps a share of RAM too (the registry's keepsRam) says that share is not on the
   *  lanes. */
  sizeWords(server) {
    return MachineMap.sizeOf(this.cells.get(String(server.port))?.fit || {});
  }

  /** What a start weighs, in words, from what CellFit.facts says of it — a cell's row in the list and the new-cell wizard's rows
   *  (add-model.js) say it alike. */
  static sizeOf(fit = {}) {
    const bytes = CardRoom.said(fit.bytes);
    const words = { plan: "machineSizeExact", runner: "machineSizePlanned", files: "machineSizeFiles" };
    const size = fit.how === "free" ? t("machineSizeFree") : !(bytes > 0) ? t("machineSizeUnknown")
      : t(words[fit.source] || words.files, { gb: MachineMap.gb(bytes / GIB) });
    // vLLM's share of RAM is counted, and the plan and the panel say it: only what nobody weighed is "not counted".
    return fit.keepsRam && !(Number(fit.ridesGb) > 0) ? `${size} · ${t("machineSizeRam")}` : size;
  }

  /** Where it would go, in a word, and the tone of that word. */
  static fitWords(place) {
    const card = t("machineFitCard", { index: place.cards[0]?.index ?? "" });
    const words = {
      cards: t("machineFitCards"), card, free: card, spill: t("machineFitSpill", { gb: MachineMap.gb(place.ramGb || 0) }),
      rides: t("machineFitRides", { gb: MachineMap.gb(place.ramGb || 0) }),
      kvRam: t("machineFitKvRam"), ram: t("machineFitRam"), none: t("machineFitNone"), unknown: t("machineFitUnknown"),
      unsized: t("machineFitUnsized", { index: place.cards[0]?.index ?? "" }),
    };
    return words[place.verdict] ?? words.unknown;
  }

  static fitTone(verdict) {
    return ["cards", "card", "free"].includes(verdict) ? "good" : verdict === "none" ? "busy" : "idle";
  }

  /** What is wrong with a cell that holds its memory, in words, for its row: the controller does not reach its port, it crashed
   *  since it was last started by hand (the scout's watchdog brought it back). The board shows such a cell as a full card; the
   *  machine's page has only its window, so its row says it — gone from view, trouble would read as calm. */
  trouble(server) {
    const facts = this.cells.get(String(server.port)) || {};
    const crashed = Number(facts.crashed) || 0;
    return [facts.unreachable ? t("topologyRemoteUnreachable") : "", crashed > 0 ? t("machinePickCrashed", { count: String(crashed) }) : ""]
      .filter(Boolean);
  }

  /** A cell's own Window and its Start or Stop, as the board's builder gave them, on its row in the list of models. */
  actionsHtml(server) {
    const port = String(server.port);
    const facts = this.cells.get(port) || {};
    const id = escapeHtml(port);
    const windowBtn = facts.window && facts.key
      ? new Button({ kind: "plain", text: t("machinePickWindow"), attrs: `data-cell-window-open="${escapeHtml(facts.key)}" data-t="machine-model-window" data-t-id="${id}"` }).html() : "";
    const act = MachineMap.groupOf(MachineMap.phase(server)) === "bench"
      ? new Button({ kind: "main", text: t("start"), title: String(facts.playTitle || ""), disabled: !facts.launch,
                     attrs: `${facts.launch ? `${facts.launch} ` : ""}data-t="machine-model-start" data-t-id="${id}"` }).html()
      : new Button({ kind: "halt", text: t("stop"), title: String(facts.stopTitle || ""), disabled: !facts.stop,
                     attrs: `${facts.stop ? `${facts.stop} ` : ""}data-t="machine-model-stop" data-t-id="${id}"` }).html();
    return `${windowBtn}${act}`;
  }

  /** The places a cell can be laid on without dragging it (a keyboard, a touch screen): a button per card and for the RAM, those it
   *  cannot lie on left out. A cell that can act now, and only while it stands or runs. */
  placesHtml(server) {
    const port = String(server.port);
    const facts = this.cells.get(port) || {};
    const group = MachineMap.groupOf(MachineMap.phase(server));
    if (group === "bench" ? !facts.launch : group !== "holds" || !facts.stop) return "";
    const move = CellMove.of(this.factsOf(port));
    const room = MachineRoom.of(this.node);
    const places = [...room.cards.map((c) => [String(c.index), `GPU ${c.index}`]), ["ram", "RAM"]].filter(([target]) => !move.to(target, room).refused);
    return places.map(([target, label]) => new Pill({ text: label, attrs: `title="${escapeHtml(t("machinePlaceOn", { device: label }))}" data-machine-place="${escapeHtml(target)}"`
      + ` data-machine-place-for="${escapeHtml(port)}" data-t="machine-place" data-t-id="${escapeHtml(target)}"` }).html()).join("");
  }

  /** The price when llama.cpp's part of a cell lies in RAM: the processor computes it. "" when there is none. */
  cpuNote(server, place = this.fit(server)) {
    const cpu = (place.cards || []).length > 0 && Number(place.ramGb) > 0 && this.factsOf(server.port)?.family === "llama";
    return cpu ? t("machineNoteCpu") : "";
  }

  /** Where a cell would go, in words, and that price. */
  fitSaid(server, place = this.fit(server)) {
    return [MachineMap.fitWords(place), this.cpuNote(server, place)].filter(Boolean).join(" · ");
  }

  /** Where a plan lays a cell, in a word per place. */
  planWhere(place) {
    const cards = (place.cards || []).map((c) => `GPU ${c.index}`);
    return [...cards, ...(Number(place.ramGb) > 0 ? ["RAM"] : [])].join(" · ");
  }

  /** A plan in words, beside where it lays the cell: who gives way, what changes. Where it would go by the same words as ever only for a cell that
   *  works: the second line of a standing cell's row says that already, and a working one's says what it does now. */
  planWords(server) {
    const plan = this.plan;
    const changes = plan.changes(server.slotConfig || {});
    const standing = MachineMap.groupOf(MachineMap.phase(server)) === "bench";
    return [standing ? this.cpuNote(server) : this.fitSaid(server), plan.evict.length ? t("machinePlanEvict", { cells: plan.evict.map((p) => `:${p}`).join(", ") }) : "",
            changes.length ? t("machinePlanChanges", { fields: changes.join(" · ") }) : t("machinePlanSame")].filter(Boolean).join(" · ");
  }

  /** The last line of a cell's row, shown while it is chosen (the owner, 2026-11-02: "remove that strip, and give its data and its functions to the row
   *  below it, taking nothing from the row"): the places it can be laid on and, with a plan in hand, where the plan lays it, what that changes and the
   *  plan's Start and Cancel; a failed cell's whole reason, which is too long for its row's second line. Every cell has one, written anew by the live
   *  patch when a plan changes: nothing here is bound at a drawing, and the plan's Start stands in for the row's own by machine.css. */
  choiceHtml(server) {
    const port = String(server.port);
    const id = escapeHtml(port);
    const hook = `data-machine-panel="${id}" data-machine-own data-t="machine-pick" data-t-id="${id}"`;
    const shown = this.chosen === port ? "" : " hidden";
    const places = this.placesHtml(server);
    if (this.plan?.port !== port) {
      const facts = this.cells.get(port) || {};
      const reason = MachineMap.phase(server) === "error" ? String(facts.reason || "").trim() : "";
      const inner = `${reason ? `<span class="machine-pick-words">${escapeHtml(reason)}</span>` : ""}${places ? `<span class="machine-pick-acts">${places}</span>` : ""}`;
      return `<div class="machine-pick" ${hook}${shown}>${inner}</div>`;
    }
    const plan = this.plan;
    const place = this.fit(server);
    const none = place.verdict === "none";
    const where = this.planWhere(place);
    const tone = none ? "bad" : MachineMap.fitTone(place.verdict) === "good" ? "good" : "busy";
    const start = new Button({ kind: "main", text: t(plan.moved ? "machinePlanRestart" : "machinePlanStart"), disabled: none || plan.busy,
                               attrs: `data-machine-plan-start="${id}" data-t="machine-plan-start" data-t-id="${id}"` }).html();
    const cancel = new Button({ kind: "plain", text: t("machinePlanCancel"), disabled: plan.busy,
                                attrs: `data-machine-plan-cancel="${id}" data-t="machine-plan-cancel" data-t-id="${id}"` }).html();
    return `<div class="machine-pick machine-pick--${tone}" ${hook} data-t-state="planned"${shown}>`
      + `<span class="machine-pick-words">${where ? `<b>→ ${escapeHtml(where)}</b> ` : ""}${escapeHtml(this.planWords(server))}</span>`
      + `<span class="machine-pick-acts">${places}${cancel}${start}</span></div>`;
  }

  /** Every cell the page shows, each once: on the lanes, on their way, standing. */
  everyCell() {
    return [...this.held().map(({ server }) => server), ...this.coming(), ...this.standing()];
  }

  html() {
    return `<section class="machine-map" aria-label="${escapeHtml(t("machineMapTitle"))}" data-t="machine-map">`
      + `<div class="machine-map-head"><strong class="machine-map-title">${escapeHtml(t("machineMapTitle"))}</strong>`
      + `<span class="machine-map-hint">${escapeHtml(t("machineMapHint"))}</span>`
      + `<span class="machine-map-key"><i class="is-weights" aria-hidden="true"></i>${escapeHtml(t("machineLegendWeights"))}`
      + `<i class="is-cache" aria-hidden="true"></i>${escapeHtml(t("machineLegendCache"))}</span>${this.totalsHtml()}</div>`
      + `<div class="machine-map-lanes" data-machine-map>${this.lanesHtml()}</div></section>`;
  }

  /** All the cards together, at the end of the map's head: what the board's Activity block says of them, as the monitor's tick fills it. */
  totalsHtml() {
    if (!(this.node.gpus || []).length) return "";
    const id = escapeHtml(String(this.node.id ?? ""));
    const part = (key) => `<button type="button" class="machine-map-total" data-machine-chart="node:${id}:${key}" data-t="machine-map-total" data-t-id="${key}"><span data-node-metric-val="${id}:${key}">—</span></button>`;
    return `<span class="machine-map-totals"><span>${escapeHtml(t("machineAllCards"))}</span>${part("gpu")}${part("vram")}${part("power")}</span>`;
  }

  /** The works the machine's cells do, each with how many of them do it, in the vocabulary's order: the pills over the list of models. */
  benchJobs(cells = this.bench()) {
    const count = new Map();
    for (const server of cells) {
      for (const job of this.cells.get(String(server.port))?.jobs || []) count.set(job, (count.get(job) || 0) + 1);
    }
    return JOBS.filter((job) => count.has(job)).map((job) => ({ job, count: count.get(job) }));
  }

  /** The work the list is narrowed to, of the one chosen (`job`): the chosen one while a cell of the machine does it. A work chosen on
   *  another machine, or one whose last cell left, narrows nothing — no pill would be there to let it go. */
  jobShown(job, cells = this.bench()) {
    return this.benchJobs(cells).some((one) => one.job === job) ? job : "";
  }

  /** What a cell's row in the list says on its second line, in what tone: a cell that works — that it runs, loads its weights or is
   *  broken; one on its way — what it does, the copy's figures included; one that stands — where it would go, or that it failed or
   *  has no model. The live patch asks the same. {tone, words, state}. */
  benchVerdict(server) {
    const phase = MachineMap.phase(server);
    const group = MachineMap.groupOf(phase);
    if (group === "holds") {
      const facts = this.cells.get(String(server.port)) || {};
      const trouble = this.trouble(server);
      if (phase === "warming") {
        // Loading its weights: how far, how fast and how long, while its scout measures the reading (2.43, ModelLoad).
        const load = ModelLoad.now(server);
        return { tone: "busy", words: [load ? ModelCopy.line(load, t("machinePickWarming")) : t("machinePickWarming"), ...trouble].join(" · "), state: "warming" };
      }
      if (phase === "broken") return { tone: "bad", words: [t("machinePickBroken"), ...trouble].join(" · "), state: "broken" };
      const words = [t("machinePickRunning"), ...trouble].join(" · ");
      if (facts.unreachable) return { tone: "bad", words, state: "unreachable" };
      return Number(facts.crashed) > 0 ? { tone: "busy", words, state: "crashed" } : { tone: "good", words, state: "running" };
    }
    if (group === "coming") return { tone: "busy", words: this.comingWords(server), state: phase };
    if (phase === "error") return { tone: "bad", words: t("machinePickFailed"), state: "failed" };
    if (phase === "reserved") return { tone: "idle", words: t("machinePickReserved"), state: "reserved" };
    const place = this.fit(server);
    return { tone: MachineMap.fitTone(place.verdict), words: this.fitSaid(server, place), state: place.verdict };
  }

  /** What a cell's row in the list says on its second line, before that: what a working cell holds now, what another weighs; nothing for
   *  a port with no model. The live patch asks the same. */
  benchSize(server) {
    const phase = MachineMap.phase(server);
    if (phase === "reserved") return "";
    return MachineMap.groupOf(phase) === "holds" ? this.memoryWords(server) : this.sizeWords(server);
  }
}

/**
 * What the machine does now, said in the line of its head beside its name: the tone (good — a cell runs; busy — one is on its way;
 * idle — none runs; bad — the machine is silent) and the words; a silent machine says how long it has been silent.
 */
export class MachineBand {
  /** The phases of a cell on its way: copying its model, starting, loading its weights. */
  static ON_ITS_WAY = ["downloading", "starting", "warming", "loading", "resolving"];

  constructor(node, { age = () => "", nameOf = (server) => `:${server.port}` } = {}) {
    this.node = node || {};
    this.age = age;
    this.nameOf = nameOf;
  }

  counts() {
    const cells = (this.node.servers || []).filter((s) => s && s.port && MachineMap.phase(s) !== "reserved");
    const running = cells.filter((s) => MachineMap.phase(s) === "running").length;
    const starting = cells.filter((s) => MachineBand.ON_ITS_WAY.includes(MachineMap.phase(s)));
    return { cells: cells.length, running, coming: starting.length, starting };
  }

  tone() {
    if (this.node.role === "host" && !this.node.online) return "bad";
    const { running, coming } = this.counts();
    if (coming) return "busy";
    return running ? "good" : "idle";
  }

  title() {
    const { cells, running, coming, starting } = this.counts();
    const tone = this.tone();
    if (tone === "bad") return t("nodeScoutSilent");
    // One cell on its way is named: "Starting 1" sent the owner looking for which one (2026-10-26).
    if (tone === "busy" && coming === 1) return t("machineBandStartingOne", { name: this.nameOf(starting[0]), m: running, k: cells });
    if (tone === "busy") return t("machineBandStarting", { n: coming, m: running, k: cells });
    if (tone === "good") return t("machineBandRunning", { n: running, m: cells });
    return cells ? t("machineBandIdle") : t("machineBandEmpty");
  }

  /** How long a silent machine has said nothing (HTML: the age stays live); nothing else — the lanes say the use. */
  sub() {
    return this.tone() === "bad" ? `<span data-live-hostage>${escapeHtml(this.age(this.node))}</span>` : "";
  }

  html() {
    const tone = this.tone();
    return new Band({ tone, title: this.title(), sub: this.sub(), inline: true,
                      attrs: `data-machine-band data-t="machine-band" data-t-state="${tone}"` }).html();
  }
}

/**
 * What stands at the right of a machine's map (variant В, part 4 — 1.3.636): what the machine runs its cells with — the caravan's
 * llama.cpp and its build, the engines and the models they hold with no cell — the disk its model copies go to, the incidents of
 * the caravan's ports, and how busy the machine has been, a line per chart, always in sight (the owner chose "Б" on 2026-10-25).
 * The old column of the machine's servers is gone: its strips are the engines here, its cells are on the map and in the list. The
 * board's builder draws each part with what only it knows (topology-nodes.js machineSideHtml); this frames them, says what is not
 * there, and gives the incidents their way in.
 */
export class MachineSide {
  /** The parts' data-t names, spelled out: docs/testability.md publishes each one, and its guard (scripts/testability_names.py)
   *  finds a composed hook only as a literal. */
  static HOOKS = { engines: "machine-side-engines", disk: "machine-side-disk", incidents: "machine-side-incidents",
                   activity: "machine-side-activity" };

  /**
   * @param warnings HTML: what the machine's next boot does to its driver (topology-nodes.js nodeDriverWarningsHtml), "" when nothing
   * @param engines HTML: the caravan's strip and the engines' groups
   * @param disk HTML: the model cache's line (model-cache.js), "" when the scout does not report it
   * @param incidents how many incidents the caravan's ports had in the last day, or null while the monitor has not said
   * @param activity HTML: the machine's charts (charts.js nodeTelemetryRowsHtml), "" when nothing is measured
   * @param stats HTML: the controller machine's own server stats and their switch, "" on any other machine
   * @param machine the machine's name, said on the parts that are its own; "" when not known, and then none is made up
   */
  constructor({ warnings = "", engines = "", disk = "", incidents = null, activity = "", stats = "", machine = "" } = {}) {
    Object.assign(this, { warnings: String(warnings || ""), engines: String(engines || ""), disk: String(disk || ""),
                          activity: String(activity || ""), stats: String(stats || ""), machine: String(machine || "").trim() });
    const n = Number(incidents);
    this.incidents = incidents === null || incidents === undefined || !Number.isFinite(n) || n < 0 ? null : Math.floor(n);
  }

  static none(key) {
    return `<p class="machine-side-none">${escapeHtml(t(key))}</p>`;
  }

  /** A part of the column: its title, whose it is, and what it holds. The owner, 2026-11-03: "label the blocks with their machine — with
   *  scouts on several machines it is not clear which one is meant": the machine's own parts carry its name, the incidents the whole
   *  caravan's. */
  static part(key, title, body, whose = "") {
    const said = whose ? `${title} · ${whose}` : title;
    const of = whose ? `<span class="machine-side-whose">${escapeHtml(whose)}</span>` : "";
    return `<section class="machine-side-part" aria-label="${escapeHtml(said)}" data-t="${MachineSide.HOOKS[key]}">`
      + `<div class="machine-side-title">${escapeHtml(title)}${of}</div>${body}</section>`;
  }

  /** How many incidents, live in the board's own counter (charts.js renderTopologyIncidents writes every
   *  [data-board-incidents-count]), and the way into them. Not known yet — a dash, not a zero. */
  incidentsHtml() {
    const known = this.incidents !== null;
    return `<div class="machine-incidents"><span class="machine-incidents-count" data-board-incidents-count`
      + ` data-t="machine-incidents-count" data-t-state="${known ? (this.incidents ? "some" : "none") : "unknown"}">${known ? this.incidents : "—"}</span>`
      + `<span class="machine-incidents-hint">${escapeHtml(t("machineIncidentsHint"))}</span>`
      + new Button({ kind: "quiet", text: t("machineIncidentsOpen"), attrs: 'data-machine-incidents data-t="machine-incidents-open"' }).html()
      + "</div>";
  }

  html() {
    return `<aside class="machine-side" aria-label="${escapeHtml(t("machineSideLabel"))}" data-t="machine-side">${this.warnings}`
      + MachineSide.part("engines", t("machineEnginesTitle"), this.engines || MachineSide.none("machineEnginesNone"), this.machine)
      + MachineSide.part("disk", t("machineDiskTitle"), this.disk || MachineSide.none("machineDiskUnknown"), this.machine)
      + MachineSide.part("incidents", t("machineIncidentsTitle"), this.incidentsHtml(), t("machineSideWholeCaravan"))
      + MachineSide.part("activity", t("machineActivityTitle"), `${this.activity || MachineSide.none("machineActivityNone")}${this.stats}`, this.machine)
      + "</aside>";
  }
}

/** The way into the board's incidents from a machine's page: the side column's "Open" (MachineSide). One listener on the document,
 *  bound once by main.js with the board's own opener (topology-nodes.js openIncidentsModal, the "⚠" of the board's bar). */
export class SideIncidents {
  constructor() {
    this.bound = false;
  }

  bind(doc, { open = () => {} } = {}) {
    if (this.bound || !doc?.addEventListener) return;
    this.bound = true;
    doc.addEventListener("click", (e) => {
      if (!e.target?.closest?.("[data-machine-incidents]")) return;
      e.preventDefault?.();
      open();
    });
  }
}

export const SIDE_INCIDENTS = new SideIncidents();

/**
 * The head of a machine's page: the passport — its name, what it is, its address, its scout — and, in the same line, what it does
 * now, the "⋯" of what is rare and what cannot be undone (reboot, the power schedule, power off, letting the scout go) and Add model;
 * under them the map of its memory and the list of its models with their cells, and at their right the column of what the machine runs
 * them with (MachineSide, drawn by the board's builder: `side`).
 */
export class MachineHead {
  constructor(node, { owners = () => [], age = () => "", reserving = false, addTitle = "", oldScout = "", cells = new Map(), chosen = "",
                      side = "", plan = null, library = {} } = {}) {
    this.node = node || {};
    this.side = String(side || "");
    this.library = library;
    this.map = new MachineMap(this.node, { owners, cells, chosen, plan });
    this.band = new MachineBand(this.node, { age, nameOf: (server) => this.map.cellName(server) });
    this.reserving = !!reserving;
    this.addTitle = String(addTitle || "");
    this.oldScout = String(oldScout || "");
  }

  facts() {
    const n = this.node;
    const role = n.role === "host" ? t("nodeRoleHost") : String(n.role || "");
    // A scout is a release of the caravan: its commit says which. Its version stands still, and a scout that names no commit is an older one.
    const scout = String(n.scoutCommit || n.scoutVersion || "").trim();
    return [role, String(n.platform || ""), String(n.ip || ""), scout ? t("machineScoutVersion", { version: scout }) : ""]
      .filter(Boolean).join(" · ");
  }

  menu() {
    const id = escapeHtml(String(this.node.id || ""));
    const schedule = this.node.powerSchedule || {};
    const items = [
      { text: t("machineMenuReboot"), title: t("hostRebootTitle"), attrs: `data-reboot-host="${id}" data-t="node-reboot" data-t-id="${id}"` },
      { text: t("machineMenuSchedule"), attrs: `data-power-schedule-host="${id}" data-t="node-power-schedule" data-t-id="${id}"`,
        title: schedule.enabled ? t("hostPowerSchedArmedTitle", { at: schedule.at || "",
                                                                  daily: schedule.daily ? t("hostPowerSchedDaily") : t("hostPowerSchedOnce") })
          : t("hostPowerSchedTitle") },
      { text: t("machineMenuPowerOff"), title: t("hostPowerOffTitle"), danger: true,
        attrs: `data-poweroff-host="${id}" data-t="node-poweroff" data-t-id="${id}"` },
    ];
    if (this.node.role === "host") {
      items.push("-", { text: t("machineMenuScoutUpdate"), title: t("scoutUpdateTitle"),
                        attrs: `data-scout-update="${id}" data-t="node-scout-update" data-t-id="${id}"` },
                 { text: t("machineMenuRelease"), title: t("nodeDisconnectScoutTitle"), danger: true,
                        attrs: `data-scout-disconnect="${id}" data-t="node-disconnect" data-t-id="${id}"` });
    }
    return new Menu({ label: t("machineMenuLabel"), items, attrs: `data-t="machine-menu" data-t-id="${id}"` }).html();
  }

  /** Add model: the attributes of the card's own button (topology-nodes.js, nodeCaravanGroupHtml), shut while a cell is reserved. */
  addButton() {
    const id = escapeHtml(String(this.node.id || ""));
    const attrs = `data-t="machine-add" data-t-id="${id}"${this.reserving ? "" : ` data-caravan-add="${id}"`}`;
    return new Button({ kind: "main", icon: "plus", text: t("caravanAddModel"), title: this.reserving ? t("shelfReserveBusy") : this.addTitle,
                        attrs, disabled: this.reserving }).html();
  }

  html() {
    const tools = `<div class="machine-tools">${this.band.html()}${this.menu()}${this.addButton()}</div>`;
    const models = new MachineModels({ map: this.map, reserving: this.reserving, ...this.library }).html();
    // The rack across the whole page (the owner's choice Ш1, 2026-11-02), and under it the list and the column, each scrolling by itself.
    const main = `<div class="machine-main">${models}</div>`;
    return new Frame({ kind: "page", tag: "div", title: String(this.node.name || this.node.id || ""), facts: this.facts(),
                       addr: this.oldScout, tools, body: `${this.map.html()}${this.side ? `<div class="machine-grid">${main}${this.side}</div>` : main}`,
                       attrs: `data-machine-head data-t="machine-head" data-t-id="${escapeHtml(String(this.node.id || ""))}"` }).html();
  }
}

/**
 * A cell chosen on the map of the machine's page: its row in the list of models says all of it, its blocks, chip or row are ringed.
 * Held here and not on the page, as the open cell's window is (card-fold.js): the board draws the page anew with every change, and a
 * choice that vanished with each drawing would be no choice. What the board's builder said of the cells — their names, windows, starts
 * and stops — is held with it (`know`), for the head drawn between two drawings of the board (MachineHeadLive). Choosing the chosen cell
 * again lets it go.
 */
export class MachinePick {
  constructor() {
    this.port = "";
    this.cells = new Map();
    this.bound = false;
    this.listed = () => {};
  }

  /** What the board's builder said of the cells of the machine shown (topology-nodes.js, nodeServerCardHtml). */
  know(cells) {
    this.cells = cells instanceof Map ? cells : new Map();
  }

  chosen(port) {
    return this.port !== "" && String(port ?? "") === this.port;
  }

  choose(port) {
    const p = String(port ?? "");
    this.port = p === this.port ? "" : p;
    return this.port;
  }

  /** The choice shown without a drawing of the board: the blocks, chips and rows say which one is chosen, its row shows its last line, and the
   *  list of models hears: the chosen cell's model opens and stands whatever the list is narrowed to (`listed`, MachineModelsChoice.show). */
  show(root) {
    for (const el of root?.querySelectorAll?.("[data-machine-pick]") || []) {
      const on = this.chosen(el.dataset.machinePick);
      el.classList?.toggle?.("is-on", on);
      // A cell's row is no button, and has no pressed to say: its port is one, and says it.
      if (el.hasAttribute?.("aria-pressed") !== false) el.setAttribute?.("aria-pressed", String(on));
    }
    for (const p of root?.querySelectorAll?.("[data-machine-panel]") || []) p.hidden = !this.chosen(p.dataset.machinePanel);
    for (const line of root?.querySelectorAll?.("i[data-lane-owner]") || []) line.classList?.toggle?.("is-shown", this.chosen(line.dataset.laneOwner));
    this.listed(root);
  }

  /** One holder lit on every lane and in the list, its line drawn, the rest stepped back; "" lets go. It lives on the page and goes
   *  with a drawing: the next move of the pointer lights it again. */
  light(root, owner) {
    const rack = root?.querySelector?.(".machine-rack");
    if (!rack || (rack.dataset.laneLit || "") === owner) return;
    rack.dataset.laneLit = owner;
    rack.classList?.toggle?.("is-lighting", !!owner);
    for (const el of rack.querySelectorAll?.("[data-lane-owner]") || []) el.classList?.toggle?.("is-lit", !!owner && el.dataset.laneOwner === owner);
  }

  /** A like or a dislike pressed: shown at once on every row of the model and kept by the controller (`save`); refused, it goes back to what it was and the
   *  reason is said (`notify`). What the builder said of the cell follows it, so the next press turns it the right way. A model with no
   *  cell here says what stands on its own buttons: the list of models shows them all. `marked` hears of each mark shown. */
  async rate(el, { save = async () => {}, notify = () => {}, root = null, marked = () => {} } = {}) {
    const model = String(el?.dataset?.modelRateFor || "");
    const kind = String(el?.dataset?.modelRate || "");
    const cells = [...this.cells.values()].filter((facts) => facts.model === model);
    if (!model || !kind) return false;
    const buttons = () => [el, ...(root?.querySelectorAll?.("[data-model-rate-for]") || [])].filter((button) => button.dataset.modelRateFor === model);
    const was = cells.length ? String(cells[0].rating || "") : String(buttons().find((button) => button.getAttribute?.("aria-pressed") === "true")?.dataset.modelRate || "");
    const now = ModelRating.pressed(was, kind);
    const show = (rating) => {
      for (const facts of cells) facts.rating = rating;
      for (const button of buttons()) ModelRating.mark(button, rating);
      marked(model, rating);
    };
    show(now);
    try {
      await save(model, now);
      return true;
    } catch (err) {
      show(was);
      notify(String(err?.message || err));
      return false;
    }
  }

  /** Whether a choice moves what the lanes draw: a cell that stands is drawn dashed where it would go, and only a drawing of the
   *  board puts that on the lanes or takes it off. */
  standing(port) {
    return this.cells.get(String(port ?? ""))?.group === "bench";
  }

  /** One listener on the document, bound once. `redraw` draws the board again: when the choice puts a stopped cell's dashes on the
   *  lanes or takes them off, and when the chosen cell's window is not in the page yet; the keyboard is given back to its block,
   *  chip or port. Any other choice is shown in place. A like or a dislike (`save` keeps it, `notify` says a refusal) chooses nothing,
   *  and neither does a cell's Window, Start or Stop (MachineDrag.taken): each only does what it does. */
  bind(doc, { redraw = () => {}, save = async () => {}, notify = () => {}, marked = () => {}, listed = () => {}, openChart = () => {} } = {}) {
    if (this.bound || !doc?.addEventListener) return;
    this.bound = true;
    this.listed = listed;
    doc.addEventListener("click", (e) => {
      // Here and not at a drawing: the lanes are written anew between two drawings of the board (MachineHeadLive), and their figures with them.
      const chart = e.target?.closest?.("[data-machine-chart]");
      if (chart) {
        e.preventDefault?.();
        openChart(chart.dataset.machineChart);
        return;
      }
      const rate = e.target?.closest?.("[data-model-rate]");
      if (rate) {
        e.preventDefault?.();
        this.rate(rate, { save, notify, root: doc, marked });
        return;
      }
      const el = MachineDrag.taken(e.target);
      if (!el) return;
      e.preventDefault?.();
      const was = this.port;
      const port = this.choose(el.dataset.machinePick);
      // A plan belongs to its cell: another choice, or letting this one go, drops it.
      if (MACHINE_PLAN.on && MACHINE_PLAN.port !== port) MACHINE_PLAN.clear();
      const facts = this.cells.get(port);
      const key = String(facts?.key || "").replace(/["\\]/g, "\\$&");
      const missing = facts?.window && key && !doc.querySelector?.(`.fold-slot[data-fold-key="${key}"]`);
      if (this.standing(was) || this.standing(port) || missing) {
        redraw();
        const back = String(el.dataset.machinePick || "").replace(/["\\]/g, "\\$&");
        doc.querySelector?.(`[data-t="${String(el.dataset.t || "").replace(/["\\]/g, "\\$&")}"][data-machine-pick="${back}"]`)?.focus?.();
      } else {
        this.show(doc);
      }
      this.bringRow(doc, port);
    });
    this.bindLight(doc);
  }

  /** The pointer's listeners of the rack: not during a drag, whose pieces are a plan's. */
  bindLight(doc) {
    const light = (owner) => { if (!doc.body?.classList?.contains?.("machine-dragging")) this.light(doc, owner); };
    doc.addEventListener("mouseover", (e) => light(String(e.target?.closest?.("[data-lane-owner]")?.dataset?.laneOwner || "")));
    doc.addEventListener("mouseout", (e) => { if (!e.relatedTarget) light(""); });
  }

  /** The chosen cell's row whole in sight, with its buttons: chosen on the rack, it may be anywhere on a long list; chosen in the list, its new line
   *  may fall under the pane's edge, and the list moves by that much and no more. Letting a cell go brings nothing. */
  bringRow(doc, port) {
    if (port) doc.querySelector?.(`.machine-model-launch[data-machine-pick="${String(port).replace(/["\\]/g, "\\$&")}"]`)?.scrollIntoView?.({ block: "nearest" });
  }
}

export const MACHINE_PICK = new MachinePick();

/**
 * The page's head kept current between two drawings of the board (topology-render.js, syncTopologyLive). The lanes' blocks are
 * buttons (variant В): the RAM's use moves a little with every reading, and lanes written again whole with every tick took the focus
 * and the hover off the block under the pointer, and a click could land between two writes. So while the lanes hold the same blocks
 * — the same cells, the same other holders, the same cells named under them — their figures move in place: widths, words, hovers,
 * which one is chosen, the chips' words; written whole only when the blocks change. The size and the verdict of each cell's row in the
 * list and the band's words change in place too; the band is drawn whole only when its tone changes.
 */
export class MachineHeadLive {
  constructor() {
    this.lanes = new WeakMap();
  }

  static CHIPS = '[data-t="machine-map-unplaced-cell"], [data-t="machine-map-coming-cell"]';

  /** What blocks the lanes are drawn with, in order — a cell by its port, another holder by its kind — and the cells named under
   *  them: read off the page, and worked out of the figures, by one rule each, so the two compare. */
  static shapeOf(map) {
    const lanes = [...(map?.querySelectorAll?.(".ui-lane") || [])].map((el) => {
      const bar = el.querySelector?.(".ui-lane-bar");
      return bar ? [[...(bar.querySelectorAll?.(".ui-lane-blk") || [])]
        .map((b) => b.dataset?.machinePick || (b.classList?.contains?.("ui-lane-blk--estimate") ? "estimate" : "other")),
                    (el.querySelectorAll?.(".ui-lane-grip") || []).length] : null;
    });
    const named = [...(map?.querySelectorAll?.(MachineHeadLive.CHIPS) || [])].map((b) => `${b.dataset?.t || ""}:${b.dataset?.machinePick || ""}`);
    const rows = [...(map?.querySelectorAll?.(".ui-legend-row") || [])].map((row) => row.dataset?.laneOwner || "other");
    return JSON.stringify([lanes, named, rows]);
  }

  static shape(lanes, map) {
    const named = [...map.unplaced(lanes).map(({ server }) => `machine-map-unplaced-cell:${server.port}`),
                   ...map.coming().map((server) => `machine-map-coming-cell:${server.port}`)];
    return JSON.stringify([lanes.map((lane) => {
      const blocks = Meter.cut(lane.total, lane.blocks)?.map(({ part }) => (part.port || String(part.kind || "").replace("-cache", "") || "")) ?? null;
      return blocks && [blocks, (lane.grips || []).length];
    }), named, MachineRack.legend(lanes).map((row) => row.owner || "other")]);
  }

  static text(el, words) {
    if (el && el.textContent !== words) el.textContent = words;
  }

  /** The lanes' figures written into the blocks already drawn: the widths and the words by the part's own rules (Meter.cut,
   *  Lane.inner), the hovers, the chosen one; and the words of the cells on their way. */
  static fill(root, lanes, map) {
    const els = [...(root?.querySelectorAll?.(".ui-lane") || [])];
    lanes.forEach((lane, i) => {
      const el = els[i];
      if (!el) return;
      MachineHeadLive.text(el.querySelector?.(".ui-lane-free"), lane.free);
      MachineHeadLive.text(el.querySelector?.(".ui-lane-side"), lane.side);
      const blocks = [...(el.querySelectorAll?.(".ui-lane-blk") || [])];
      (Meter.cut(lane.total, lane.blocks) || []).forEach(({ part, width }, j) => {
        const b = blocks[j];
        if (!b) return;
        if (b.style) b.style.width = `${width}%`;
        const title = String(part.title || "");
        if (b.title !== title) b.title = title;
        if (part.pick) {
          b.setAttribute?.("aria-label", title);
          b.setAttribute?.("aria-pressed", String(!!part.on));
          b.classList?.toggle?.("is-on", !!part.on);
        }
        const inner = Lane.inner(part, width, lane.rack ? lane.rack.bar : null);
        if (b.innerHTML !== inner) b.innerHTML = inner;
      });
      // Where a sewn piece ends moved with its figures.
      const leads = [...(el.querySelectorAll?.(".ui-lane-lead") || [])];
      (lane.links || []).filter((l) => l.here).forEach((link, j) => leads[j]?.style?.setProperty?.("--lane-from", String(link.from)));
      // A handle moves with the piece it ends, and is written whole only when one comes or goes.
      const grips = [...(el.querySelectorAll?.(".ui-lane-grip") || [])];
      (lane.grips || []).forEach((grip, j) => {
        const g = grips[j];
        if (!g) return;
        g.style?.setProperty?.("--lane-grip", String(grip.at));
        for (const m of grip.attrs.matchAll(/data-machine-grip-(from|whole|holds)="([^"]*)"/g)) g.setAttribute?.(`data-machine-grip-${m[1]}`, m[2]);
        g.classList?.toggle?.("is-on", !!grip.on);
      });
    });
    // The list says the same figures: its words and hovers, the chosen one.
    const rows = [...(root?.querySelectorAll?.(".ui-legend-row") || [])];
    MachineRack.legend(lanes).forEach((row, j) => {
      const el = rows[j];
      if (!el) return;
      MachineHeadLive.text(el.querySelector?.(".ui-legend-figure"), row.figure);
      MachineHeadLive.text(el.querySelector?.(".ui-legend-where"), row.where);
      MachineHeadLive.text(el.querySelector?.(".ui-legend-speed"), row.speed);
      if (el.title !== row.title) el.title = row.title;
      if (row.pick) {
        el.setAttribute?.("aria-pressed", String(!!row.on));
        el.classList?.toggle?.("is-on", !!row.on);
      }
    });
    const coming = new Map(map.coming().map((server) => [String(server.port), `${map.cellName(server)} · ${map.comingWords(server)}`]));
    for (const chip of root?.querySelectorAll?.('[data-t="machine-map-coming-cell"]') || []) {
      const words = coming.get(String(chip.dataset?.machinePick || ""));
      if (words !== undefined) MachineHeadLive.text(chip, words);
    }
  }

  patch(root, head) {
    // The scout's release changes under an open page: Update the scout.
    MachineHeadLive.text(root?.querySelector?.(".ui-win-facts"), head.facts());
    // A plan laid, moved or let go changes a row's last line whole: its words and its buttons are the plan's.
    const models = root?.querySelector?.('[data-t="machine-models"]');
    if (models?.dataset) {
      const key = head.map.plan?.key() || "";
      if ((models.dataset.machinePlanKey || "") !== key) {
        models.dataset.machinePlanKey = key;
        for (const server of head.map.bench()) {
          const line = root.querySelector?.(`[data-machine-panel="${String(server.port).replace(/["\\]/g, "\\$&")}"]`);
          if (line) line.outerHTML = head.map.choiceHtml(server);
        }
      }
    }
    const map = root?.querySelector?.("[data-machine-map]");
    if (map) {
      const lanes = head.map.lanes();
      const html = head.map.lanesHtml(lanes);
      if (this.lanes.get(map) !== html) {
        if (MachineHeadLive.shapeOf(map) === MachineHeadLive.shape(lanes, head.map)) MachineHeadLive.fill(map, lanes, head.map);
        else map.innerHTML = html;
        this.lanes.set(map, html);
      }
    }
    for (const server of head.map.bench()) {
      const port = String(server.port).replace(/["\\]/g, "\\$&");
      MachineHeadLive.text(root?.querySelector?.(`[data-machine-bench-size="${port}"]`), head.map.benchSize(server));
      const el = root?.querySelector?.(`[data-machine-bench-fit="${port}"]`);
      if (!el || ["failed", "reserved"].includes(el.dataset?.tState)) continue;
      const verdict = head.map.benchVerdict(server);
      MachineHeadLive.text(el, verdict.words);
      if (el.dataset && el.dataset.tState !== verdict.state) {
        el.dataset.tState = verdict.state;
        el.className = `machine-bench-fit machine-bench-fit--${verdict.tone}`;
      }
    }
    const band = root?.querySelector?.("[data-machine-band]");
    if (!band) return;
    if (band.dataset?.tState !== head.band.tone()) {
      band.outerHTML = head.band.html();
      return;
    }
    const title = band.querySelector?.(".ui-band-title");
    const words = head.band.title();
    if (title && title.textContent !== words) title.textContent = words;
    const sub = band.querySelector?.(".ui-band-sub");
    const subWords = head.band.sub();
    if (sub && sub.innerHTML !== subWords) sub.innerHTML = subWords;
  }
}

export const MACHINE_HEAD_LIVE = new MachineHeadLive();

/**
 * Where the panes of a machine's page stand when the board draws it anew. The page scrolled as one before (the owner, 2026-11-01,
 * variant Р2): the window kept its place by itself. A pane is inside what is drawn, so every drawing would throw it back to the top
 * while the operator reads the rows at the bottom. `replace` is the drawing, with the panes where they were.
 */
export class MachinePanes {
  static PANES = [".machine-main", ".machine-side"];

  static read(root) {
    return MachinePanes.PANES.map((pane) => Number(root?.querySelector?.(pane)?.scrollTop) || 0);
  }

  static write(root, tops) {
    MachinePanes.PANES.forEach((pane, at) => {
      const el = root?.querySelector?.(pane);
      if (el && tops[at]) el.scrollTop = tops[at];
    });
  }

  /** Where the caret stands in the list's search box, while it has the keyboard. */
  static typing(root) {
    const box = root?.ownerDocument?.activeElement;
    return box?.matches?.("[data-machine-models-find]") ? { start: box.selectionStart, end: box.selectionEnd } : null;
  }

  static resume(root, typing) {
    if (!typing) return;
    const box = root?.querySelector?.("[data-machine-models-find]");
    box?.focus?.();
    box?.setSelectionRange?.(typing.start, typing.end);
  }

  static replace(root, html) {
    const tops = MachinePanes.read(root);
    const typing = MachinePanes.typing(root);
    root.innerHTML = html;
    MachinePanes.write(root, tops);
    MachinePanes.resume(root, typing);
  }
}
