// Where a cell lays its model: the card a one-card start lands on and what it finds free there (CardPin, CardRoom,
// FreeVramStart: the cell form's rules, which the machine page's bench reads too), and how much of each card a llama.cpp cell
// may take, and what that leaves in RAM.
import { t } from "./i18n.js";
import { escapeHtml, formatSizeGb } from "./utils.js";

/**
 * What a card has free for a start, MiB: nvidia-smi's memory.free, else its total less what is used — null when the card says
 * neither, which is not known and not "nothing free". The form counts such a card as giving nothing (memory.js gpuFreeMiB);
 * the machine page's bench says it does not know (machine-head.js, CellFit). Until 1.3.634 the form's rule read a card with a
 * total and no use as wholly free.
 */
export class CardRoom {
  /** A number the scout said, or null: some come as text ("24576"), and one not said is not zero. The machine page reads every
   *  figure of its cards and its RAM so (machine-head.js). */
  static said(value) {
    if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }

  static freeMiB(card) {
    const free = CardRoom.said(card?.memoryFreeMiB);
    if (free > 0) return free;
    const total = CardRoom.said(card?.memoryTotalMiB);
    const used = CardRoom.said(card?.memoryUsedMiB);
    return total && used !== null ? Math.max(0, total - used) : null;
  }
}

// The card a one-card cell (Strata, GR00T, the voice servers: the registry's `oneCard`) is pinned to, in the cell's
// ENV: its last CUDA_VISIBLE_DEVICES, numbered as the board and nvidia-smi number the cards (the controller starts
// every engine with CUDA_DEVICE_ORDER=PCI_BUS_ID). The server reads the pin the same way (runner.py
// Runner.pinned_card), and one table of cases holds the two copies together (scripts/test_js_memory.py). The ENV box
// is hidden for these runners, so the pin is written by the card chips of the compute target.
export class CardPin {
  /** The card's index as text: the ENV's last CUDA_VISIBLE_DEVICES, else "0" (where an unpinned start lands);
   *  "" when the pin names no single card (a list, nothing, a UUID) — the server reserves nothing then. */
  static card(env) {
    const pins = [];
    for (const raw of String(env || "").split(/[\n,]/)) {
      const at = raw.indexOf("=");
      if (at > 0 && raw.slice(0, at).trim() === "CUDA_VISIBLE_DEVICES") pins.push(raw.slice(at + 1).trim());
    }
    const device = pins.length ? pins[pins.length - 1].replace(/^"+|"+$/g, "") : "0";
    return /^\d+$/.test(device) ? device : "";
  }

  /** The ENV with the pin set to card `index`: every earlier CUDA_VISIBLE_DEVICES row goes (the pin is one card, and
   *  the last row wins on the server), the cell's other rows stay as they were. */
  static write(env, index) {
    // The ENV is read by newline or comma (Runner.env_pairs): a pin written as a list ("0,1") is the pin "0" and a row
    // "1" with no "=", which the server skips — and so does this: a row that sets nothing is not kept.
    const rows = String(env || "").split(/[\n,]/).map((row) => row.trim()).filter(Boolean)
      .filter((row) => row.includes("=") || row.startsWith("#"))
      .filter((row) => !/^CUDA_VISIBLE_DEVICES\s*=/.test(row));
    rows.push(`CUDA_VISIBLE_DEVICES=${Number(index)}`);
    return rows.join("\n");
  }

  /** The ENV of a cell put on the processor: its device rows go, and what says "no card" takes their place. */
  static offCards(env) {
    const rows = String(env || "").split(/[\n,]/).map((s) => s.trim()).filter(Boolean)
      .filter((r) => !/^(TTS_DEVICE|CUDA_VISIBLE_DEVICES)=/i.test(r));
    rows.push("TTS_DEVICE=cpu", "CUDA_VISIBLE_DEVICES=");
    return rows.join("\n");
  }

  /** The ENV of a cell put on card `index`, off the processor if it was there: a "TTS_DEVICE=cpu" would keep it on it. */
  static onCard(env, index) {
    const rows = String(env || "").split(/[\n,]/).map((s) => s.trim()).filter((r) => !/^TTS_DEVICE=cpu$/i.test(r));
    return CardPin.write(rows.join("\n"), index);
  }
}

/** What "where it computes" writes into a llama.cpp cell: one rule for the form's tiles (memory.js applyComputeTarget) and the
 *  machine page's rack (machine-plan.js). */
export class ComputeFields {
  /** How many threads the processor's part runs on: the cores this cell may use (a pinned VM reports its slice), no more than the
   *  physical ones, whose hyperthreads rarely help compute-bound inference. Fallbacks for older reports. */
  static cores(cpu = {}) {
    const avail = Number(cpu?.availableCores || 0);
    const phys = Number(cpu?.physicalCores || 0);
    if (avail && phys) return Math.min(avail, phys);
    return avail || phys || Number(cpu?.logicalCores || 0) || Number(cpu?.ncpu || 0) || 1;
  }

  static cpu(cores) {
    const n = String(cores);
    return { N_GPU_LAYERS: "0", DEVICE: "", SPLIT_MODE: "", TENSOR_SPLIT: "", MAIN_GPU: "", THREADS: n, THREADS_BATCH: n };
  }

  /** On the cards `picked` out of `all`; none picked, all of them. "auto", not 999: llama.cpp's own -ngl puts as many layers on the
   *  cards as fit and leaves the rest in RAM, which is what makes a model larger than its cards start at all. */
  static cards(picked, all) {
    const every = (all || []).map(Number);
    const idx = (picked && picked.length ? picked : every).map(Number).slice().sort((a, b) => a - b);
    const isAll = idx.length === every.length;
    return { N_GPU_LAYERS: "auto", DEVICE: isAll ? "" : idx.map((i) => `CUDA${i}`).join(","), MAIN_GPU: isAll ? "" : String(idx[0]),
             THREADS: "1", THREADS_BATCH: "1" };
  }
}

// A start that takes its card's free VRAM (runner.py vram_plan: Strata sizes
// its expert cache to what is free). Its card is the one runner.py
// vram_reservation names, read off the cell's ENV the same way; its cost is
// what is free there less the reserve it leaves to others, and it needs its
// floor plus that reserve free. The scout refuses it below that, exactly
// (starts.py: free >= reserved), so the bar's 1 GB grace for estimates is not
// given. A class, not a function: the card, the reserve and the floor are read
// once and answer four questions.
export class FreeVramStart {
  /** The card's index as text — CardPin's rule, which is the server's. */
  static device(env) { return CardPin.card(env); }

  /** The start, or null where the server reserves nothing: no such card, or a
   *  reserve that is not a number of MiB (its Apply is refused, by name). */
  static of(plan, { env = "", reserve = "", gpus = [] } = {}) {
    const device = FreeVramStart.device(env);
    const card = device ? (gpus || []).find((g) => String(g.index) === device) : null;
    const raw = String(reserve ?? "").trim();
    if (!card || (raw && !/^\d+$/.test(raw))) return null;
    return new FreeVramStart(plan, card, raw ? Number(raw) : 0);
  }

  constructor(plan, card, reserveMiB) {
    this.card = card;
    this.floorMiB = Math.max(0, Number(plan?.floorMiB) || 0);
    this.reserveMiB = reserveMiB;
    this.freeMiB = CardRoom.freeMiB(card) ?? 0;
  }

  get needMiB() { return this.floorMiB + this.reserveMiB; }
  get fits() { return this.freeMiB >= this.needMiB; }
  /** What the bar plans for it: what it will take, or — when it will not
   *  start — what it needs free. */
  get addGb() { return (this.fits ? this.freeMiB - this.reserveMiB : this.needMiB) / 1024; }
  /** How the bar draws it: on its card alone, overflowing exactly, saying how. */
  bar() {
    return { hard: true, cards: [Number(this.card.index)],
             vramNote: t("vramTakesFree", { gb: formatSizeGb(this.needMiB / 1024) }) };
  }
}

/**
 * A model's split between the cards and RAM, as llama.cpp makes it, and the estimate of it the form draws.
 *
 * The owner, 2026-10-24, after :22018 and :22020 died four times each on "failed to allocate CUDA buffer": "fill the 5090,
 * all or part of the 3090, and keep something in RAM — as other launchers split the weights and the cache between the
 * cards and RAM". llama.cpp (common/fit.cpp, b1141) splits a model three ways, and this class follows it in each:
 *
 *  - fitted (-sm layer, nothing set that llama.cpp would decide): it fits the model itself, --fit on by default. When every
 *    layer on the cards, dealt by their free memory, leaves each card the margin --fit-target names, that is the split.
 *    Otherwise it fills the cards from the LAST one back, each with whole layers and their KV down to its margin, and the
 *    first layers left over stay in RAM. An MoE model's experts go to RAM before any whole layer: the rest of every layer
 *    and its KV stay on the cards, and the cards take layers back whole from the first on while their room lasts
 *    (fittedExperts). "Take up to X GB" of a card IS that margin: the card's room less X. The exact accounting stays
 *    llama.cpp's, by its tensors; this is the estimate drawn before the start, by averages per layer. An MoE model whose
 *    header did not give what its experts weigh is drawn as a dense one: whole layers in RAM, more than llama.cpp puts there.
 *  - held (-sm layer, something set that llama.cpp would decide): it does not fit ("... already set by user, abort"), and
 *    the cell loads as written. N_GPU_LAYERS a number or "all" puts that many layers on the cards; a TENSOR_SPLIT, or the
 *    fitting turned off, leaves -ngl auto, which without fitting is every layer. They are dealt by the split, or by the
 *    cards' free memory without one; the rest stay in RAM. A hand-set N_CPU_MOE or CPU_MOE holds it too, and the experts
 *    it moves are not counted here: that plan says it does not know.
 *  - tensor (-sm tensor): every weight and the KV are cut between the cards by --tensor-split, in equal parts without one.
 *    No fitting ("llama_params_fit is not implemented for SPLIT_MODE_TENSOR") and nothing in RAM: the model and its cache
 *    fit the cards, or the start fails.
 *
 * A layer's KV lives with the layer, on its card or in RAM — as llama.cpp allocates it. Every card that computes layers keeps
 * a compute buffer of its own, so the buffers are shared out equally between those cards: Llama 3.3 70B in a layer split
 * (2026-10-17) held 1.1 GB over its weights on the 3090 with 34 layers and 1.0 GB on the 5090 with 46 — not the whole on the
 * first card, as this class first had it. Figures are GB as the rest of the form counts them (GiB), from the model's files,
 * its layer count and the KV and batch estimates of memory.js. The cards come in llama.cpp's order (ascending index,
 * CUDA_DEVICE_ORDER=PCI_BUS_ID). RAM the machine has not reported is not known (null), and no shortage is claimed of it.
 */
export class PlacementPlan {
  /** What llama.cpp leaves free on a card when --fit-target says nothing, MiB. */
  static DEFAULT_MARGIN_MIB = 1024;
  /** The least a card keeps free whatever the limit: its CUDA context and what allocation leaves between buffers. */
  static FLOOR_MARGIN_MIB = 256;
  /** The least part of a tensor split a card is given, GB: llama.cpp cuts nothing for a zero, and the card chips are the
   *  way to leave a card out. */
  static LEAST_PART_GB = 1;
  static MODES = ["layer", "tensor"];
  /** What stops llama.cpp from fitting a layer split, in the order it meets them: the fitting turned off (it is not called),
   *  -ngl set, a --tensor-split, a --n-cpu-moe or --cpu-moe (both are tensor overrides). */
  static HELD = ["off", "layers", "split", "moe"];

  /**
   * @param model {weightsGb, kvGb, batchGb, layers, experts, expertsGb} — the files, the KV cache, the compute buffers, the
   *   layer count, the experts of an MoE model (0 for a dense one) and what they weigh (0 when not known)
   * @param cards [{index, name, freeGb}] — the cards the cell uses and the room each has for it
   * @param limits [GB] — fitted: the most of each card the model may take
   * @param parts [number] — the split (--tensor-split) of a held or tensor plan; none: the cards' room (held) or equal (tensor)
   * @param held — what stops llama.cpp from fitting (one of HELD), or null
   * @param fixedLayers — held by -ngl: the layers it names
   * @param ramFreeGb — the machine's free RAM, or null when it has not reported it
   */
  constructor({ model = {}, cards = [], limits = [], parts = [], held = null, fixedLayers = null, mode = "layer",
                kvOnCards = true, ramFreeGb = 0, cores = 1 } = {}) {
    const pos = PlacementPlan.positive;
    this.model = { weightsGb: pos(model.weightsGb), kvGb: pos(model.kvGb), batchGb: pos(model.batchGb),
      layers: Math.floor(pos(model.layers)), experts: Math.floor(pos(model.experts)), expertsGb: pos(model.expertsGb) };
    this.cards = (cards || []).map((c) => ({ index: Number(c.index), name: String(c.name || ""), freeGb: pos(c.freeGb) }))
      .sort((a, b) => a.index - b.index);
    this.mode = PlacementPlan.MODES.includes(mode) ? mode : "layer";
    this.limits = this.cards.map((c, i) => Math.min(PlacementPlan.ceiling(c), pos((limits || [])[i])));
    // The split as the field says it, for the words; the parts it gives the cards only when there is one for each.
    this.given = (parts || []).map(Number).filter((p) => Number.isFinite(p));
    this.parts = this.given.length === this.cards.length && this.given.every((p) => p > 0) ? this.given : [];
    const named = held === "layers" && fixedLayers !== null && fixedLayers !== undefined && Number.isFinite(Number(fixedLayers))
      ? Math.max(0, Math.min(this.model.layers, Math.floor(Number(fixedLayers)))) : null;
    this.held = this.mode === "layer" && PlacementPlan.HELD.includes(held) && !(held === "layers" && named === null) ? held : null;
    // Held by -ngl: the layers it names. By a split or the fitting off: -ngl auto, which llama.cpp reads as every layer
    // when it does not fit (n_gpu_layers() is n_layer + 1 for -1).
    this.fixedLayers = this.held === "layers" ? named : this.held === "split" || this.held === "off" ? this.model.layers : null;
    this.kvOnCards = kvOnCards !== false;
    this.ramFreeGb = ramFreeGb === null || ramFreeGb === undefined ? null : pos(ramFreeGb);
    this.cores = Math.max(1, Math.floor(pos(cores)));
  }

  static positive(value) {
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  /** Whether there is a plan at all: a model with a known layer count, and a card. */
  get known() { return this.model.layers > 0 && this.model.weightsGb > 0 && this.cards.length > 0; }

  /** Whether this class can count where the model lands: a known plan that no expert override moves in ways it cannot see. */
  get counted() { return this.known && this.held !== "moe"; }

  get moe() { return this.model.experts > 0; }

  /** Whether the experts can be told from the rest of each layer: an MoE model whose header gave what they weigh. */
  get expertsKnown() { return this.moe && this.model.expertsGb > 0 && this.model.expertsGb < this.model.weightsGb; }

  /** Whether llama.cpp fits this plan itself: a layer split with nothing set that it would decide. */
  get fitted() { return this.mode === "layer" && this.held === null; }

  /** The most a card may take: its room, less the floor every card keeps. */
  static ceiling(card) {
    return Math.max(0, PlacementPlan.positive(card.freeGb) - PlacementPlan.FLOOR_MARGIN_MIB / 1024);
  }

  /** What in a cell's fields stops llama.cpp from fitting a layer split — one of HELD — or null. -ngl "auto" or "-1" is
   *  llama.cpp's own choice, a --tensor-split of zeros is none ("tensor_split[id] != 0.0f"), and a --n-cpu-moe of 0 moves
   *  nothing. */
  static heldBy({ fit = "", nGpuLayers = "", tensorSplit = "", nCpuMoe = "", cpuMoe = "" } = {}) {
    if (String(fit).trim() === "0") return "off";
    if (PlacementPlan.fixedFrom(nGpuLayers, Infinity) !== null) return "layers";
    if (PlacementPlan.numbers(tensorSplit).some((x) => x !== 0)) return "split";
    if (Number(nCpuMoe) > 0 || String(cpuMoe).trim() === "1") return "moe";
    return null;
  }

  /** The split the cards get: the parts a held or tensor plan names, else their room (a layer split — llama.cpp reads the
   *  free memory at load) or equal parts (tensor — what llama.cpp cuts without --tensor-split: 21.1 + 21.4 GB of a 39.6 GB
   *  model on a 24 and a 32 GB card). A fitted plan has no parts: one would have held it. */
  shares() {
    const parts = this.fitted ? [] : this.parts;
    const weights = parts.length ? parts : this.cards.map((c) => (this.mode === "tensor" ? 1 : c.freeGb));
    const sum = weights.reduce((a, b) => a + b, 0);
    return weights.map((w) => (sum > 0 ? w / sum : 1 / weights.length));
  }

  /** `n` layers dealt out by the shares; the last card takes what rounding left. */
  dealt(n) {
    const shares = this.shares();
    let left = n;
    return this.cards.map((c, i) => {
      const k = i === this.cards.length - 1 ? left : Math.min(left, Math.round(n * shares[i]));
      left -= k;
      return k;
    });
  }

  /**
   * Where the model lands: {cards: [{index, name, freeGb, limitGb, layers, weightsGb, kvGb, buffersGb, totalGb, over}],
   * ram: {layers, expertLayers, weightsGb, kvGb, totalGb, freeGb, short}, layersOnCards, verdict} — `ram.layers` are the
   * layers there whole, `ram.expertLayers` the layers whose experts alone are there; verdict "unknown", "fits", "spill"
   * (a part of the model in RAM), "kvRam" (every layer on the cards, the cache in RAM), "ramShort" (more in RAM than the
   * machine has free) or "over" (a card given more than its room).
   */
  placed() {
    if (!this.counted) {
      return { cards: [],
        ram: { layers: 0, expertLayers: 0, weightsGb: 0, kvGb: 0, totalGb: 0, freeGb: this.ramFreeGb, short: false },
        layersOnCards: 0, verdict: "unknown" };
    }
    const { layers, full } = this.mode === "tensor" ? PlacementPlan.whole(this.tensorLayers())
      : !this.fitted ? PlacementPlan.whole(this.dealt(this.fixedLayers))
        : this.expertsKnown ? this.fittedExperts() : PlacementPlan.whole(this.fittedLayers());
    const m = this.model;
    // A layer by averages: its experts, which only a fitted MoE plan keeps apart, and the rest of it.
    const experts = this.expertsKnown ? m.expertsGb / m.layers : 0;
    const rest = m.weightsGb / m.layers - experts;
    const perKv = this.kvOnCards ? m.kvGb / m.layers : 0;
    const computing = layers.filter((n) => n > 0).length;
    const cards = this.cards.map((c, i) => {
      // In a tensor split every card holds a part of every layer: its share of the weights and of the cache.
      const share = this.mode === "tensor" ? this.shares()[i] : null;
      const weightsGb = share !== null ? share * m.weightsGb : layers[i] * rest + full[i] * experts;
      const kvGb = share !== null ? share * (this.kvOnCards ? m.kvGb : 0) : layers[i] * perKv;
      const buffersGb = layers[i] > 0 ? m.batchGb / computing : 0;
      const totalGb = weightsGb + kvGb + buffersGb;
      return { index: c.index, name: c.name, freeGb: c.freeGb, limitGb: this.limits[i], layers: layers[i], weightsGb, kvGb,
        buffersGb, totalGb, over: totalGb > PlacementPlan.ceiling(c) + 1e-9 };
    });
    const left = this.mode === "tensor" ? 0 : m.layers - layers.reduce((a, b) => a + b, 0);
    const expertLayers = layers.reduce((a, n, i) => a + n - full[i], 0);
    const weightsGb = left * (rest + experts) + expertLayers * experts;
    const kvGb = this.kvOnCards ? left * perKv : m.kvGb;
    const ram = { layers: left, expertLayers, weightsGb, kvGb, totalGb: weightsGb + kvGb, freeGb: this.ramFreeGb, short: false };
    ram.short = this.ramFreeGb !== null && ram.totalGb > this.ramFreeGb;
    // The cache in RAM is no fit either: the cards hold every layer, but the CPU computes the attention over it.
    const verdict = cards.some((c) => c.over) ? "over" : ram.short ? "ramShort" : ram.weightsGb > 0 ? "spill"
      : ram.kvGb > 0 ? "kvRam" : "fits";
    return { cards, ram, layersOnCards: m.layers - left, verdict };
  }

  /** Layers as a dense model's are held: each card keeps the whole of every layer it has. */
  static whole(layers) {
    return { layers, full: layers };
  }

  /** Whether the layers, dealt as `layers` at `per` GB each, leave every card within its limit with its part of the buffers
   *  — llama.cpp's first look ("targets for free memory can be met on all devices, no changes needed"). */
  fitsAsDealt(layers, per) {
    const sharing = layers.filter((n) => n > 0).length;
    return layers.every((n, i) => n * per + (n > 0 ? this.model.batchGb / sharing : 0) <= this.limits[i] + 1e-9);
  }

  /** `left` layers of `per` GB each, filled into the cards from the last one back, each card up to its room: the layers
   *  each card takes. */
  static backToFront(rooms, per, left) {
    const layers = rooms.map(() => 0);
    for (let i = rooms.length - 1; i >= 0; i--) {
      layers[i] = per > 0 ? Math.max(0, Math.min(left, Math.floor(rooms[i] / per + 1e-9))) : 0;
      left -= layers[i];
    }
    return layers;
  }

  /**
   * Fitted, as common/fit.cpp does it. Every layer dealt by the cards' free memory, when that leaves each card within its
   * limit. Otherwise the cards filled from the last one back ("filling dense layers back-to-front"), each with whole layers
   * and their KV up to its limit less its part of the buffers; what is left over stays in RAM. A card left with no layer
   * computes nothing and keeps no buffer, so the others are dealt again with the buffers shared among fewer; should that give
   * a card back a layer, the larger part stays reserved — the estimate errs towards RAM, not over a card.
   */
  fittedLayers() {
    const m = this.model;
    const per = m.weightsGb / m.layers + (this.kvOnCards ? m.kvGb / m.layers : 0);
    const whole = this.dealt(m.layers);
    if (this.fitsAsDealt(whole, per)) return whole;
    let computing = this.cards.length;
    for (;;) {
      const layers = PlacementPlan.backToFront(this.limits.map((l) => l - m.batchGb / computing), per, m.layers);
      const used = layers.filter((n) => n > 0).length;
      if (used === 0 || used >= computing) return layers;
      computing = used;
    }
  }

  /**
   * Fitted, for an MoE model whose experts' weight is known: common/fit.cpp's steps 3 and 4. When every layer dealt whole
   * fits, that is the split. Otherwise llama.cpp first keeps only the rest of each layer and its KV on the cards, from the
   * last one back ("filling dense-only layers back-to-front"), every expert in RAM. When that takes them all, the cards before
   * the ones holding them take layers whole from the first on, and the first card holding them turns its own layers whole
   * while its room lasts ("converting dense-only layers to full layers and filling them front-to-back"): the experts of the
   * layers still without theirs are what RAM keeps. When even the rest of every layer does not fit, the first layers stay in
   * RAM whole, and every expert with them. By whole layers: llama.cpp also cuts one layer at a card's edge, not drawn here.
   * Qwen3-Coder-Next on a 3090 and a 5090: the map put about 5 whole layers in RAM, the start held everything on the cards.
   * @returns {{layers: number[], full: number[]}} — the layers each card holds, and of those the ones it holds whole
   */
  fittedExperts() {
    const m = this.model;
    const experts = m.expertsGb / m.layers;
    const rest = m.weightsGb / m.layers - experts + (this.kvOnCards ? m.kvGb / m.layers : 0);
    const dealt = this.dealt(m.layers);
    if (this.fitsAsDealt(dealt, rest + experts)) return PlacementPlan.whole(dealt);
    const n = this.cards.length;
    let computing = n;
    for (;;) {
      const rooms = this.limits.map((l) => l - m.batchGb / computing);
      const layers = PlacementPlan.backToFront(rooms, rest, m.layers);
      const full = layers.map(() => 0);
      if (layers.reduce((a, b) => a + b, 0) === m.layers) {
        let start = n - 1;
        while (start > 0 && layers[start - 1] > 0) start -= 1;
        for (let id = 0; id < start; id++) {
          let take = Math.min(layers.slice(start).reduce((a, b) => a + b, 0), Math.max(0, Math.floor(rooms[id] / (rest + experts) + 1e-9)));
          layers[id] = take;
          full[id] = take;
          for (let jd = start; jd < n && take > 0; jd++) {
            const moved = Math.min(take, layers[jd]);
            layers[jd] -= moved;
            take -= moved;
          }
        }
        full[start] = Math.min(layers[start], Math.max(0, Math.floor((rooms[start] - layers[start] * rest) / experts + 1e-9)));
      }
      const used = layers.filter((k) => k > 0).length;
      if (used === 0 || used >= computing) return { layers, full };
      computing = used;
    }
  }

  /** Tensor: every layer is on the cards, a part of it on each. */
  tensorLayers() {
    return this.cards.map(() => this.model.layers);
  }

  /** --fit-target for the cards, MiB, in llama.cpp's order: each card's room less what the model may take of it. */
  margins() {
    return this.cards.map((c, i) => Math.max(PlacementPlan.FLOOR_MARGIN_MIB, Math.round((c.freeGb - this.limits[i]) * 1024)));
  }

  /** The cell's fields a placement writes. The cards themselves are the card chips' (DEVICE): --fit-target and
   *  --tensor-split name the cards they picked, in order. */
  fields() {
    const placed = this.placed();
    const kv = { KV_OFFLOAD: this.kvOnCards ? "1" : "0" };
    // A plan this class cannot count moves the cache and nothing else: the threads would follow a RAM part it does not know.
    if (!this.counted) return kv;
    // A layer, an expert or the cache in RAM is computed by the CPU: with one thread there (the GPU tile's default) it crawled.
    const cpu = placed.ram.totalGb > 0 ? String(this.cores) : "1";
    const own = { ...kv, THREADS: cpu, THREADS_BATCH: cpu };
    // Held, the plan is the operator's: the cache moves, the threads follow, and what holds it stays as they wrote it — a
    // handle moved or "Fit by the handles" lifts it, and that is a fitted plan.
    if (this.held !== null) return this.held === "layers" ? { ...own, N_GPU_LAYERS: String(this.fixedLayers) } : own;
    // The experts are llama.cpp's to place while it fits: a --n-cpu-moe set by hand stops it from fitting at all
    // ("tensor_buft_overrides already set by user, abort").
    const shared = { ...own, N_CPU_MOE: "", CPU_MOE: "0", FIT: "1" };
    if (this.mode === "tensor") {
      // Parts as GB of each card, one decimal: "24,32" is the whole of a 3090 and a 5090, as the split tile writes it.
      return { ...shared, SPLIT_MODE: "tensor", N_GPU_LAYERS: "auto", FIT_TARGET: "",
        TENSOR_SPLIT: this.limits.map((g) => PlacementPlan.decimal(Math.max(PlacementPlan.LEAST_PART_GB, g))).join(",") };
    }
    // llama.cpp fits only what is not set: the layer count and the split stay unset for it to decide.
    return { ...shared, SPLIT_MODE: this.cards.length > 1 ? "layer" : "", TENSOR_SPLIT: "", N_GPU_LAYERS: "auto",
      FIT_TARGET: this.margins().join(",") };
  }

  static decimal(gb) {
    return String(Math.round(gb * 10) / 10);
  }

  /** The plan a llama.cpp cell's fields say over the facts of its model and its machine ({model, cards, ramFreeGb, cores,
   *  mode}): what the cell window's map draws (PlacementPanel.plan) and where the machine page's bench lays a stopped cell
   *  (machine-head.js) — one reading of the fields. `get` reads a field as the form holds it, a box as "1" or "0". */
  static from({ facts = {}, get = () => "" } = {}) {
    const f = facts || {};
    const mode = f.mode === "tensor" ? "tensor" : "layer";
    const split = get("TENSOR_SPLIT");
    return new PlacementPlan({ model: f.model, cards: f.cards, mode,
      limits: PlacementPlan.limitsFrom({ mode, fitTarget: get("FIT_TARGET"), tensorSplit: split, cards: f.cards }),
      parts: PlacementPlan.numbers(split),
      held: PlacementPlan.heldBy({ fit: get("FIT"), nGpuLayers: get("N_GPU_LAYERS"), tensorSplit: split,
        nCpuMoe: get("N_CPU_MOE"), cpuMoe: get("CPU_MOE") }),
      fixedLayers: PlacementPlan.fixedFrom(get("N_GPU_LAYERS"), Number(f.model?.layers || 0)),
      kvOnCards: get("KV_OFFLOAD") !== "0", ramFreeGb: f.ramFreeGb, cores: f.cores });
  }

  /** The cards a cell's DEVICE names ("CUDA0,CUDA1" → [0, 1]), out of `all`; none named, all of them. The cell form's reading
   *  (memory.js computeSelectedGpuIdx) and the machine page's (machine-head.js, CellFit). */
  static devices(device, all = []) {
    const dev = String(device ?? "").trim();
    if (!dev) return [...all];
    const picked = dev.split(",").map((d) => Number(String(d).replace(/[^0-9]/g, ""))).filter((n) => !Number.isNaN(n));
    return picked.length ? picked : [...all];
  }

  /** The numbers of a comma-separated field, "" or anything else giving []. */
  static numbers(raw) {
    return String(raw ?? "").split(",").map((x) => x.trim()).filter(Boolean).map(Number);
  }

  /**
   * The limits a cell's fields say, one per card. Fitted: the card's room less the margin --fit-target leaves on it (one
   * value is every card's, as llama.cpp reads it; none is llama.cpp's own 1024 MiB). Tensor: the parts of its split, each
   * at most the card's room (none, or a split of another count of cards: every card whole).
   */
  static limitsFrom({ mode = "layer", fitTarget = "", tensorSplit = "", cards = [] } = {}) {
    const sorted = (cards || []).map((c) => ({ ...c, freeGb: PlacementPlan.positive(c.freeGb) }))
      .sort((a, b) => Number(a.index) - Number(b.index));
    if (mode === "tensor") {
      const parts = PlacementPlan.numbers(tensorSplit);
      const usable = parts.length === sorted.length && parts.every((p) => Number.isFinite(p) && p > 0);
      // No split: llama.cpp cuts equal parts, so every card shows the same part — the smallest card's whole room.
      const equal = Math.min(...sorted.map((c) => PlacementPlan.ceiling(c)));
      return sorted.map((c, i) => (usable ? Math.min(parts[i], PlacementPlan.ceiling(c)) : equal));
    }
    const given = PlacementPlan.numbers(fitTarget).filter((x) => Number.isFinite(x) && x >= 0);
    return sorted.map((c, i) => {
      const margin = given.length === 0 ? PlacementPlan.DEFAULT_MARGIN_MIB : given.length === 1 ? given[0]
        : (given[i] ?? PlacementPlan.DEFAULT_MARGIN_MIB);
      return Math.max(0, c.freeGb - Math.max(margin, PlacementPlan.FLOOR_MARGIN_MIB) / 1024);
    });
  }

  /** The layers -ngl fixes: a number, "all" or "max" (every layer), or null — "auto" or nothing, llama.cpp fits. */
  static fixedFrom(raw, layers) {
    const v = String(raw ?? "").trim().toLowerCase();
    if (v === "all" || v === "max") return layers;
    if (/^\d+$/.test(v)) return Math.min(layers, parseInt(v, 10));
    return null;
  }
}

/**
 * The placement panel of a llama.cpp cell's form: a map of where the model lives. On top, the model as one bar, cut by the
 * device each part lands on. Under it a lane for each card and one for RAM, as long as the device is big, with what fills
 * it: other processes (hatched), the model's weights, its KV cache and the buffers, and the free rest. A card's limit is a
 * handle on its lane — the most of the card the model may take (fitted), or its part (tensor): dragged, the map follows at
 * once, and the cell's fields are written when it is let go. Then where the KV cache lives, and the verdict in the four
 * colours of the house: green fits, yellow a part in RAM, red does not fit, grey not known.
 *
 * It reads and writes the cell's fields through `form` ({get(key), set(key, value), changed()}) and draws into a box, so a
 * test drives it without a page. `facts` are what the form knows of the model and the machine: {model, cards: [{index,
 * name, freeGb, totalGb}], ramFreeGb, ramTotalGb, cores, mode}.
 */
export class PlacementPanel {
  /** The panel's data-t names, spelled out: docs/testability.md publishes each one, and its guard
   *  (scripts/testability_names.py) finds a composed hook only as a literal. data-t-state says the panel's plan (fitted,
   *  held, tensor, unknown), the verdict's (fits, spill, kvRam, ramShort, over, unknown) and the held note's reason (one of
   *  PlacementPlan.HELD); data-t-id says a card's index, or where the KV cache goes (cards, ram). */
  static HOOKS = {
    panel: "cell-remote-placement", card: "cell-remote-placement-card", limit: "cell-remote-placement-limit",
    all: "cell-remote-placement-all", none: "cell-remote-placement-none", ram: "cell-remote-placement-ram",
    kv: "cell-remote-placement-kv", verdict: "cell-remote-placement-verdict", held: "cell-remote-placement-held",
    fit: "cell-remote-placement-fit", threads: "cell-remote-placement-threads",
  };
  static STEP_GB = 0.5;

  constructor({ form, facts }) {
    this.form = form;
    this.facts = facts || {};
  }

  /** The plan the cell's fields say now. */
  plan() {
    return PlacementPlan.from({ facts: this.facts, get: (key) => this.form.get(key) });
  }

  /** `plan`, fitted by its limits (or split by them, in tensor), written into the cell's fields. */
  write(plan) {
    for (const [key, value] of Object.entries(plan.fields())) this.form.set(key, value);
    this.form.changed();
  }

  /** `plan` with `change` made: the same model, cards and machine. */
  with(plan, change) {
    return new PlacementPlan({ model: plan.model, cards: plan.cards, limits: plan.limits, mode: plan.mode, parts: plan.given,
      held: plan.held, fixedLayers: plan.fixedLayers, kvOnCards: plan.kvOnCards, ramFreeGb: plan.ramFreeGb,
      cores: plan.cores, ...change });
  }

  /** The plan with one card's limit at `gb`: the most it may take (fitted), its part (tensor). A handle moved asks llama.cpp
   *  to fit by the handles, so whatever held the plan is lifted. */
  withLimit(index, gb) {
    const plan = this.plan();
    const limits = plan.cards.map((c, i) => (c.index === Number(index) ? Number(gb) : plan.limits[i]));
    return this.with(plan, { limits, parts: plan.mode === "tensor" ? limits : [], held: null, fixedLayers: null });
  }

  setLimit(index, gb) {
    this.write(this.withLimit(index, gb));
  }

  /** THREADS and THREADS_BATCH at `n`: the RAM lane's "Use N" — the part in RAM computed by all the machine's cores. */
  setThreads(n) {
    this.form.set("THREADS", String(n));
    this.form.set("THREADS_BATCH", String(n));
    this.form.changed();
  }

  /** The threads the cell computes its part in RAM with: what THREADS says, or the machine's cores when it says none
   *  (llama.cpp's own default). The GPU tile writes 1, and a cell switched to a split that spills kept it: the lane said
   *  "8 threads" while the cell ran its RAM layers on one (2026-10-24). */
  threads(plan) {
    const set = Math.floor(PlacementPlan.positive(this.form.get("THREADS")));
    return set > 0 ? set : plan.cores;
  }

  setKv(onCards) {
    this.write(this.with(this.plan(), { kvOnCards: !!onCards }));
  }

  /** Something held the plan: hand it back to llama.cpp's fitting, by the limits drawn. */
  fitByLimits() {
    this.write(this.with(this.plan(), { held: null, fixedLayers: null, parts: [] }));
  }

  static gb(value) {
    return `${(Math.round(value * 10) / 10).toFixed(1)} GB`;
  }

  static pct(part, whole) {
    return whole > 0 ? Math.max(0, Math.min(100, (100 * part) / whole)) : 0;
  }

  /** How long a lane is drawn, GB: the device itself, or what is asked of it with what others hold when that is more. The
   *  part past the device's end is then drawn, hatched red, rather than cut off at the lane's end: on the live board a card
   *  given 2.7 GB more than it had looked merely full (2026-10-24). */
  static span(dev, askedGb) {
    return Math.max(dev.totalGb, dev.othersGb + askedGb);
  }

  /** The red hatch over what does not fit a device: from its end to the lane's, "" when everything fits. */
  static pastHtml(dev, whole, overGb) {
    return whole > dev.totalGb + 0.01
      ? `<span class="place-past" style="left:${PlacementPanel.pct(dev.totalGb, whole).toFixed(2)}%" title="${escapeHtml(t("placeOverBy", { gb: PlacementPanel.gb(overGb) }))}"></span>`
      : "";
  }

  /** A card as the machine reports it: the lane is as long as its total, and what it lacks of it other processes hold. */
  device(index) {
    const c = (this.facts.cards || []).find((x) => Number(x.index) === Number(index)) || {};
    const freeGb = PlacementPlan.positive(c.freeGb);
    const totalGb = Math.max(PlacementPlan.positive(c.totalGb), freeGb);
    return { totalGb, freeGb, othersGb: Math.max(0, totalGb - freeGb) };
  }

  /** The cell's field names in escaped text, set as code: the note names the field to look for, among plain words. */
  static fieldsAsCode(html) {
    return html.replace(/\b(N_GPU_LAYERS|TENSOR_SPLIT|N_CPU_MOE|CPU_MOE|FIT)\b/g, "<code>$1</code>");
  }

  /** Why llama.cpp will not fit the plan, in the panel's words. */
  static heldText(plan) {
    return {
      layers: () => t("placeFixed", { n: plan.fixedLayers, total: plan.model.layers }),
      split: () => t("placeHeldSplit", { split: plan.given.join(",") }),
      off: () => t("placeHeldOff"),
      moe: () => t("placeHeldMoe"),
    }[plan.held]();
  }

  /** The panel's HTML: "" with no model or no card to place it on; the reason, when the plan cannot be counted. */
  html(plan = this.plan()) {
    if (!(plan.model.weightsGb > 0) || !plan.cards.length) return "";
    const hook = PlacementPanel.HOOKS;
    const legend = `<span class="place-legend" aria-hidden="true"><i class="weights"></i>${escapeHtml(t("placeLegendWeights"))}<i class="kv"></i>KV`
      + `<i class="buffers"></i>${escapeHtml(t("placeLegendBuffers"))}<i class="others"></i>${escapeHtml(t("placeLegendOthers"))}</span>`;
    const head = `<div class="place-head"><span class="compute-label">${escapeHtml(t("placeLabel"))}</span>${plan.counted ? legend : ""}</div>`;
    // A model whose layer count is not known is said so, rather than left out as if there were nothing to place.
    if (!plan.known) {
      return `<div class="placement" data-t="${hook.panel}" data-t-state="unknown">${head}`
        + `<div class="place-foot"><p class="place-verdict">${this.verdictHtml(plan, plan.placed())}</p></div></div>`;
    }
    const held = plan.held === null ? ""
      : `<div class="place-held" data-t="${hook.held}" data-t-state="${plan.held}"><span class="place-held-icon" aria-hidden="true">⚠</span>`
        + `<p class="place-held-text">${PlacementPanel.fieldsAsCode(escapeHtml(PlacementPanel.heldText(plan)))}</p>`
        + `<button type="button" class="place-fit" data-place-fit="1" data-t="${hook.fit}">${escapeHtml(t("placeFitByLimits"))}</button></div>`;
    if (!plan.counted) return `<div class="placement" data-t="${hook.panel}" data-t-state="held">${head}${held}</div>`;
    const placed = plan.placed();
    const state = plan.mode === "tensor" ? "tensor" : plan.fitted ? "fitted" : "held";
    const kv = `<div class="place-kv" role="group" aria-label="${escapeHtml(t("placeKv"))}"><span class="place-kv-label">${escapeHtml(t("placeKv"))}</span>`
      + ["cards", "ram"].map((where) => {
        const on = (where === "cards") === plan.kvOnCards;
        return `<button type="button" class="place-kv-btn${on ? " on" : ""}" data-place-kv="${where}" data-t="${hook.kv}" data-t-id="${where}"`
          + ` aria-pressed="${on}" title="${escapeHtml(t(where === "cards" ? "placeKvCardsHint" : "placeKvRamHint"))}">`
          + `${escapeHtml(t(where === "cards" ? "placeKvCards" : "placeKvRam"))}</button>`;
      }).join("") + "</div>";
    return `<div class="placement ${plan.mode}" data-t="${hook.panel}" data-t-state="${state}">${head}`
      + `<p class="place-how">${escapeHtml(t(plan.mode === "tensor" ? "placeHowTensor" : "placeHowLayer"))}</p>${held}`
      + `<div class="place-sum" data-place-sum>${this.sumHtml(plan, placed)}</div>`
      + `<div class="place-lanes">${placed.cards.map((c, i) => this.laneHtml(plan, c, i)).join("")}`
      + `<div class="place-lane ram" data-place-lane="ram" data-t="${hook.ram}">${this.ramInnerHtml(plan, placed)}</div></div>`
      + `<div class="place-foot">${kv}<p class="place-verdict" data-place-verdict>${this.verdictHtml(plan, placed)}</p></div>`
      + `<p class="place-flags"><span>${escapeHtml(t("placeFlags"))}</span> <code data-place-flags>${escapeHtml(PlacementPanel.flags(plan, this.form.get("N_GPU_LAYERS")))}</code></p></div>`;
  }

  /** The model as one bar, cut by the device each part lands on. */
  sumHtml(plan, placed) {
    const parts = placed.cards.map((c, i) => ({ id: `gpu${i % 4}`, name: `GPU${c.index}`, gb: c.totalGb }))
      .concat([{ id: "ram", name: "RAM", gb: placed.ram.totalGb }]).filter((p) => p.gb > 0.05);
    const total = parts.reduce((a, p) => a + p.gb, 0);
    const segs = parts.map((p) => `<span class="place-sum-seg ${p.id}" style="width:${PlacementPanel.pct(p.gb, total).toFixed(2)}%"`
      + ` title="${escapeHtml(`${p.name} · ${PlacementPanel.gb(p.gb)}`)}">${PlacementPanel.wordsHtml(p.name, PlacementPanel.gb(p.gb))}</span>`).join("");
    return `<span class="place-sum-label">${escapeHtml(t("placeModel", { gb: PlacementPanel.gb(total) }))}</span><span class="place-sum-bar">${segs}</span>`;
  }

  laneHtml(plan, c, i) {
    const hook = PlacementPanel.HOOKS;
    const dev = this.device(c.index);
    const step = PlacementPanel.STEP_GB;
    const max = Math.floor(PlacementPlan.ceiling(c) / step) * step;
    const min = plan.mode === "tensor" ? PlacementPlan.LEAST_PART_GB : 0;
    const none = plan.mode === "tensor" ? ""
      : `<button type="button" data-place-none="${c.index}" data-t="${hook.none}" data-t-id="${c.index}">${escapeHtml(t("placeNone"))}</button>`;
    // The handle runs over the part of the lane the model may have: from what others hold to the card's ceiling.
    const whole = PlacementPanel.span(dev, c.totalGb);
    const left = PlacementPanel.pct(dev.othersGb, whole);
    const width = PlacementPanel.pct(max, whole);
    return `<div class="place-lane gpu gpu${i % 4}${c.over ? " bad" : ""}" data-place-lane="${c.index}" data-t="${hook.card}" data-t-id="${c.index}">`
      + `<div class="place-lane-head"><span class="place-lane-name">🎮 GPU${c.index}${c.name ? ` <span class="place-lane-model">${escapeHtml(c.name)}</span>` : ""}</span>`
      + `<span class="place-lane-size">${escapeHtml(t("placeDevice", { total: PlacementPanel.gb(dev.totalGb), free: PlacementPanel.gb(dev.freeGb) }))}</span></div>`
      + `<div class="place-track"><div class="place-segs" data-place-segs>${this.segsHtml(dev, c)}</div>`
      + `<span class="place-keep" data-place-keep style="${this.keepStyle(plan, dev, c)}" title="${escapeHtml(t("placeKept"))}"></span>`
      + `<input type="range" class="place-handle" min="${min}" max="${max.toFixed(1)}" step="${step}" value="${(Math.round(c.limitGb / step) * step).toFixed(1)}"`
      + ` style="left:${left.toFixed(2)}%;width:${width.toFixed(2)}%" data-place-limit="${c.index}" data-t="${hook.limit}" data-t-id="${c.index}"`
      + ` aria-label="${escapeHtml(`GPU${c.index} — ${t(plan.mode === "tensor" ? "placePart" : "placeUpTo")}`)}"></div>`
      + `<div class="place-lane-foot"><span class="place-limit"><span>${escapeHtml(t(plan.mode === "tensor" ? "placePart" : "placeUpTo"))}</span>`
      + ` <b class="place-limit-gb" data-place-limit-gb>${escapeHtml(PlacementPanel.gb(c.limitGb))}</b>`
      + `<span class="place-quick"><button type="button" data-place-all="${c.index}" data-t="${hook.all}" data-t-id="${c.index}">${escapeHtml(t("placeAll"))}</button>${none}</span></span>`
      + `<span class="place-lane-text" data-place-text>${escapeHtml(this.cardText(plan, c))}</span></div></div>`;
  }

  /** The part of a card the model leaves alone, right of its handle: what llama.cpp keeps free there — while it fits. A
   *  tensor part is no such bound, nor is a handle llama.cpp does not fit by (a held plan), and a lane with no room left
   *  past the handle has none. A fitted card is never over its end, so its lane is the card. */
  keepStyle(plan, dev, c) {
    const keep = plan.fitted ? Math.max(0, c.freeGb - c.limitGb) : 0;
    return `width:${PlacementPanel.pct(keep, dev.totalGb).toFixed(2)}%`;
  }

  /** One part of a lane — its colour and its width out of `whole` — with what it is and how much written in it; nothing for a
   *  part too small to hold anything. */
  static segHtml(cls, gb, name, whole) {
    if (!(gb > 0.01)) return "";
    const size = PlacementPanel.gb(gb);
    return `<span class="place-seg ${cls}" style="width:${PlacementPanel.pct(gb, whole).toFixed(2)}%" title="${escapeHtml(`${name} · ${size}`)}">`
      + `${PlacementPanel.wordsHtml(name, size)}</span>`;
  }

  /** A part's words, what it is and then how much (the owner, 2026-10-26: "if it fits, label it — the model, the KV cache or
   *  whatever it is"). A lane's colour is its device's — the colours of the model's bar above, GPU0's part and GPU1's — so
   *  weights on two cards are two colours, and only words say what a part is. Which words fit is the browser's to measure, not
   *  a width guessed here (a word in German is longer than in English): the stylesheet lays them on the part's one line and
   *  hides what wraps below it (form.css, the part's words) — a narrow part says only what it is, a narrower one nothing. */
  static wordsHtml(name, size) {
    return `<span class="place-word">${escapeHtml(name)}</span><span class="place-word">${escapeHtml(size)}</span>`;
  }

  /** What fills a card's lane, left to right: other processes, the model's weights, its KV, the buffers; the rest is free. */
  segsHtml(dev, c) {
    const whole = PlacementPanel.span(dev, c.totalGb);
    const seg = (cls, gb, name) => PlacementPanel.segHtml(cls, gb, name, whole);
    return seg("others", dev.othersGb, t("placeLegendOthers")) + seg("weights", c.weightsGb, t("placeLegendWeights"))
      + seg("kv", c.kvGb, "KV") + seg("buffers", c.buffersGb, t("placeLegendBuffers"))
      + PlacementPanel.pastHtml(dev, whole, c.totalGb - PlacementPlan.ceiling(c));
  }

  cardText(plan, c) {
    const what = plan.mode === "tensor" ? t("placeCardTensor", { gb: PlacementPanel.gb(c.totalGb) })
      : t("placeCardLayers", { n: c.layers, gb: PlacementPanel.gb(c.totalGb) });
    const parts = [t("placeWeights", { gb: PlacementPanel.gb(c.weightsGb) }),
      c.kvGb > 0.05 ? t("placeKvPart", { gb: PlacementPanel.gb(c.kvGb) }) : "",
      c.buffersGb > 0.05 ? t("placeBuffers", { gb: PlacementPanel.gb(c.buffersGb) }) : ""].filter(Boolean).join(" · ");
    const over = c.over ? ` — ${t("placeOverBy", { gb: PlacementPanel.gb(c.totalGb - PlacementPlan.ceiling(c)) })}` : "";
    return `${what} — ${parts}${over}`;
  }

  /** The RAM lane: what other processes hold of it, the part of the model there, the free rest — and who computes it, with how
   *  many threads; fewer than the machine's cores is said, with the button that gives it all of them. */
  ramInnerHtml(plan, placed, threads = this.threads(plan)) {
    const ram = placed.ram;
    const reported = ram.freeGb !== null;
    const totalGb = reported ? Math.max(PlacementPlan.positive(this.facts.ramTotalGb), ram.freeGb) : 0;
    const othersGb = reported ? Math.max(0, totalGb - ram.freeGb) : 0;
    const device = { totalGb, othersGb };
    const whole = PlacementPanel.span(device, ram.totalGb);
    const seg = (cls, gb, name) => PlacementPanel.segHtml(cls, gb, name, whole);
    const gb = PlacementPanel.gb(ram.weightsGb);
    const what = plan.mode === "tensor" && ram.totalGb <= 0.05 ? t("placeRamTensor")
      : ram.layers > 0 && ram.expertLayers > 0 ? t("placeRamLayersExperts", { n: ram.layers, m: ram.expertLayers, gb })
        : ram.layers > 0 ? t("placeRamLayers", { n: ram.layers, gb })
          : ram.expertLayers > 0 ? t("placeRamExperts", { n: ram.expertLayers, gb })
            : ram.kvGb > 0.05 ? t("placeRamKvOnly") : t("placeRamNone");
    const kvPart = ram.kvGb > 0.05 ? ` · ${t("placeKvPart", { gb: PlacementPanel.gb(ram.kvGb) })}` : "";
    const few = ram.totalGb > 0.05 && threads < plan.cores;
    const cpu = ram.totalGb > 0.05 ? ` · ${t(few ? "placeCpuFew" : "placeCpuThreads", { n: threads, cores: plan.cores })}` : "";
    const cores = few
      ? ` <button type="button" class="place-cores" data-place-cores="${plan.cores}" data-t="${PlacementPanel.HOOKS.threads}">`
        + `${escapeHtml(t("placeUseCores", { cores: plan.cores }))}</button>` : "";
    const size = reported ? t("placeDevice", { total: PlacementPanel.gb(totalGb), free: PlacementPanel.gb(ram.freeGb) })
      : t("placeRamNotReported");
    const track = reported
      ? `<div class="place-track${ram.short ? " bad" : ""}"><div class="place-segs" data-place-segs>`
        + seg("others", othersGb, t("placeLegendOthers")) + seg("weights", ram.weightsGb, t("placeLegendWeights")) + seg("kv", ram.kvGb, "KV")
        + PlacementPanel.pastHtml(device, whole, ram.totalGb - (ram.freeGb ?? 0))
        + `</div></div>`
      : "";
    return `<div class="place-lane-head"><span class="place-lane-name">🧠 RAM</span>`
      + `<span class="place-lane-size">${escapeHtml(size)}</span></div>${track}`
      + `<div class="place-lane-foot"><span class="place-lane-text" data-place-text>${escapeHtml(what + kvPart + cpu)}</span>${cores}</div>`;
  }

  verdictHtml(plan, placed) {
    const ram = placed.ram;
    // What is in RAM decides the words: whole layers, the experts of layers, or (MoE with not even the rest of every layer on
    // the cards) whole layers and every other layer's experts.
    const spill = ram.layers > 0 && ram.expertLayers > 0 ? "placeSpillDense" : ram.expertLayers > 0 ? "placeSpillExperts"
      : "placeSpillLayers";
    const key = { fits: "placeFits", spill, kvRam: "placeKvInRam",
      ramShort: "placeRamShort", over: plan.mode === "tensor" ? "placeOver" : "placeOverHeld", unknown: "placeUnknown" }[placed.verdict];
    return `<span class="place-pill ${placed.verdict}" data-t="${PlacementPanel.HOOKS.verdict}" data-t-state="${placed.verdict}">`
      + `${escapeHtml(t(key, { n: spill === "placeSpillExperts" ? ram.expertLayers : ram.layers, total: plan.model.layers,
        gb: PlacementPanel.gb(ram.totalGb),
        short: PlacementPanel.gb(Math.max(0, ram.totalGb - (ram.freeGb ?? 0))), layer: t("splitLayer"), fit: t("placeFitByLimits") }))}</span>`;
  }

  /** The flags of the plan as the command says them — what the panel's limits become, or what holds the plan: -ngl as the
   *  field has it (999 is in the command, not the 48 layers it comes to). */
  static flags(plan, nGpuLayers = "") {
    const kv = plan.kvOnCards ? "" : " --no-kv-offload";
    if (plan.mode === "tensor") return `--split-mode tensor --tensor-split ${plan.fields().TENSOR_SPLIT}${kv}`;
    if (plan.held !== null) {
      return {
        layers: () => `--n-gpu-layers ${String(nGpuLayers || "").trim() || plan.fixedLayers}`,
        split: () => `--split-mode layer --tensor-split ${plan.given.join(",")}`,
        off: () => "--fit off",
        moe: () => "--n-cpu-moe / --cpu-moe",
      }[plan.held]() + kv;
    }
    return `${plan.cards.length > 1 ? "--split-mode layer " : ""}--fit on --fit-target ${plan.margins().join(",")}${kv}`;
  }

  /** The map for a limit being dragged, drawn again around the handle under the finger, which stays where it is. */
  preview(box, index, gb) {
    const plan = this.withLimit(index, gb);
    const placed = plan.placed();
    const sum = box.querySelector("[data-place-sum]");
    if (sum) sum.innerHTML = this.sumHtml(plan, placed);
    placed.cards.forEach((c) => {
      const lane = box.querySelector(`[data-place-lane="${c.index}"]`);
      if (!lane) return;
      lane.classList.toggle("bad", c.over);
      const segs = lane.querySelector("[data-place-segs]");
      if (segs) segs.innerHTML = this.segsHtml(this.device(c.index), c);
      const text = lane.querySelector("[data-place-text]");
      if (text) text.textContent = this.cardText(plan, c);
      const label = lane.querySelector("[data-place-limit-gb]");
      if (label) label.textContent = PlacementPanel.gb(c.limitGb);
      const keep = lane.querySelector("[data-place-keep]");
      if (keep) keep.setAttribute("style", this.keepStyle(plan, this.device(c.index), c));
    });
    // The threads the release will write (a fitted plan with a part in RAM gives it the machine's cores), not those of now.
    const next = Math.floor(Number(plan.fields().THREADS));
    const ram = box.querySelector('[data-place-lane="ram"]');
    if (ram) ram.innerHTML = this.ramInnerHtml(plan, placed, next > 0 ? next : this.threads(plan));
    this.wireCores(box);
    const verdict = box.querySelector("[data-place-verdict]");
    if (verdict) verdict.innerHTML = this.verdictHtml(plan, placed);
    const flags = box.querySelector("[data-place-flags]");
    if (flags) flags.textContent = PlacementPanel.flags(plan, this.form.get("N_GPU_LAYERS"));
  }

  /** Draw into `box` and wire it: a handle moved redraws the map at once and writes the fields when let go. */
  mount(box) {
    if (!box) return;
    box.innerHTML = this.html();
    const redraw = () => this.mount(box);
    box.querySelectorAll("[data-place-limit]").forEach((input) => {
      input.addEventListener("input", () => this.preview(box, input.dataset.placeLimit, input.value));
      input.addEventListener("change", () => { this.setLimit(input.dataset.placeLimit, input.value); redraw(); });
    });
    box.querySelectorAll("[data-place-all]").forEach((btn) => btn.addEventListener("click", () => {
      const card = this.plan().cards.find((c) => c.index === Number(btn.dataset.placeAll));
      if (card) { this.setLimit(card.index, PlacementPlan.ceiling(card)); redraw(); }
    }));
    box.querySelectorAll("[data-place-none]").forEach((btn) => btn.addEventListener("click", () => {
      this.setLimit(btn.dataset.placeNone, 0);
      redraw();
    }));
    box.querySelectorAll("[data-place-kv]").forEach((btn) => btn.addEventListener("click", () => {
      this.setKv(btn.dataset.placeKv === "cards");
      redraw();
    }));
    box.querySelector("[data-place-fit]")?.addEventListener("click", () => { this.fitByLimits(); redraw(); });
    this.wireCores(box);
  }

  /** The RAM lane's "Use N": drawn again with the lane (a drag redraws it), so wired again with it. */
  wireCores(box) {
    box.querySelector("[data-place-cores]")?.addEventListener("click", () => { this.setThreads(this.plan().cores); this.mount(box); });
  }
}
