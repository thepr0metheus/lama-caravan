// What a cell holds in the machine's memory, said as two badges — RAM and GPU — on its line and on its card (1.3.583). The owner, 2026-10-18,
// looking at the thin rows of a machine's cells, where only the video memory a cell holds was written: "for each model show two badges, how
// much it holds in RAM and how much on the GPU, as separate badges, even if one of them is not occupied".
//
// Four things a badge can say, and they look different: what the cell HOLDS now (solid), what it is EXPECTED to hold when it runs (dashed, "≈"),
// that it holds NOTHING (a zero, plain), and that the caravan is NOT TOLD (a dash). A zero and a dash are not the same fact — "0" says the cell
// holds none, "—" says nobody measured — and drawing the second as the first is the defect this project keeps meeting.
//
// The RAM is the scout's (2.35: `ramBytes`, the RSS of the cell's processes): an older scout does not say it, and its running cells show a dash.
// The GPU is the controller's own, summed from the compute apps by pid (`gpuMem`): a machine whose cards were not read (no NVIDIA driver, macOS)
// has none to sum, and a running cell shows a dash there too, not a zero.
//
// What a running cell holds moves while it runs — a model can load after its server answers — and the board draws a card again only when
// its structure changes. So the card's builder draws the figures and the board's live patch (topology-render.js syncTopologyLive) writes
// them again on every tick, both from this class and from one reading of the cell's report (`measured`). Until then the patch did not
// touch them: a voice cell's badge said "GPU 0.3G", what its process held in the first seconds of its start, for minutes while it held
// 2.4, and only a tab opened later said so (2026-11-07).
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";

const GIB = 2 ** 30;

export class CellMemory {
  /** The hook a test finds each badge by (docs/testability.md), and the word its text begins with. One place for both. */
  static HOOKS = { ram: "cell-ram", gpu: "cell-gpu" };
  /** The phases in which a cell's process holds memory now: running, warming up (its model still loading), broken (the process
   *  is up, its engine is not). The card's badges and the machine's map of its memory (machine-head.js) read the same list. */
  static HOLDING = ["running", "warming", "broken"];

  static holds(phase) {
    return CellMemory.HOLDING.includes(String(phase || ""));
  }
  static LABELS = { ram: "RAM", gpu: "GPU" };
  /** What the figure of the cell window's Overview tile is, in words under it: one per kind of badge. */
  static WORDS = { held: "cwMemHeld", expected: "cwMemExpected", none: "cwMemNone", unknown: "cwMemUnknown", idle: "cwMemIdle" };
  /** The marks the live patch finds the window's two tiles by: the figure, and the words under it. */
  static TILE_HOOKS = { ram: { value: "data-live-cwram", sub: "data-live-cwramsub" }, gpu: { value: "data-live-cwgpu", sub: "data-live-cwgpusub" } };
  /** The mark of a card's figure in the window's Memory tab; its value is the card's index. */
  static CARD_HOOK = "data-live-cwcard";

  /** The cards a cell's processes hold memory on, as its entry in the topology says: their indexes (`gpuIndexes`) and what is held on
   *  each, in MiB (`gpuMem`, the controller's sum of the compute apps by pid). A card listed with no figure holds 0 there. */
  static cards(server) {
    const s = server || {};
    const mem = s.gpuMem || {};
    return (Array.isArray(s.gpuIndexes) ? s.gpuIndexes : []).map((i) => ({ i, mib: Number(mem[String(i)] || 0) }));
  }

  /** What a cell's own processes hold now, read off its entry and its machine as the badges take it: the RSS its scout measured, the
   *  video memory summed over its cards and split by card for the tip, the cards themselves, and whether the machine's cards were read
   *  at all. The card's builder and the live patch both read the report here, so they cannot read it two ways. */
  static measured(server, node) {
    const cards = CellMemory.cards(server);
    return {
      gpuKnown: (node?.gpus || []).length > 0,
      ramBytes: server?.ramBytes,
      vramBytes: cards.reduce((sum, c) => sum + c.mib, 0) * 2 ** 20,
      split: cards.filter((c) => c.mib).map((c) => `GPU${c.i}: ${(c.mib / 1024).toFixed(1)} GiB`).join(" · "),
      cards,
    };
  }

  /** A card's figure in the window's Memory tab: what the cell's processes hold on it ("2.4 GB"), a dash where they hold none. */
  static cardFigure(mib) {
    const n = Number(mib);
    return Number.isFinite(n) && n > 0 ? `${(n / 1024).toFixed(1)} GB` : "—";
  }

  /** What a runner that sizes itself by free memory says it takes: its card, or every card of the machine (the registry's `everyCard`).
   *  The words live here once, because two readers need them: this badge's tip and the row's size line (machine-head.js). They had
   *  drifted — a cell that takes every card still read "its card's free memory" on its badge (the owner, 2026-11-04). */
  static freeWords(everyCard) {
    return t(everyCard ? "machineSizeFreeEvery" : "machineSizeFree");
  }

  /** A size in bytes as the badge says it: gigabytes with one place, "0" for nothing, "<0.1G" for what one place would round to nothing. */
  static gb(bytes) {
    if (bytes === null || bytes === undefined || bytes === "" || typeof bytes === "boolean") return "";
    const n = Number(bytes);
    if (!Number.isFinite(n) || n < 0) return "";
    if (n === 0) return "0";
    const gb = n / GIB;
    return gb < 0.05 ? "<0.1G" : `${gb.toFixed(1)}G`;
  }

  /**
   * @param {object} f what the card knows of the cell
   *   live       a process holds memory now (running, warming up, broken)
   *   reserved   a port with no model yet: there is nothing to say
   *   cpu        the cell computes on the CPU
   *   gpuKnown   the machine's cards were read, so a cell that is on none holds zero there and not "unknown"
   *   ramBytes   the RSS of its processes, null when the scout does not say
   *   vramBytes  the video memory its processes hold, summed over the cards
   *   split      the same per card, for the tip ("GPU0: 31.0 GiB")
   *   cards      the same per card as figures, [{ i, mib }] (`cards`): the window's Memory tab says each
   *   plannedGb  the runner's own measured figure for the card, in GiB (0: none)
   *   fileBytes  the model file's size, for the estimate (0: not known)
   *   takesFree  its runner takes its card's free memory (Strata): what it is expected to hold is `freeBytes` — that room less its
   *              reserve, as a machine's page lays it (CellFit "free") — null where its card or the card's room is not known, or the card
   *              lacks its floor. Its files are no measure of it: it keeps its weights in RAM, and an 87 GB pack read "≈87.2G" of
   *              video memory on a 32 GB card (2026-10-26)
   *   everyCard  the same, asked of every card of the machine (the registry's `everyCard`: Strata's DeepSeek engine). Only the words
   *              change — the figure comes in as `freeBytes`, summed by `FreeVramEvery`.
   *   heldTitle  the tip of a badge that says what is held, where the cell's own words are not the machine's: an engine's cell says it is the
   *              engine that reports it
   */
  constructor(f = {}) {
    this.reserved = !!f.reserved;
    const live = !!f.live;
    // Only figures a process holds now are written again by the live patch (`patch`); an estimate is the config's, drawn with the card.
    this.live = live;
    this.cards = live && Array.isArray(f.cards) ? f.cards : [];
    const number = (v) => (typeof v !== "boolean" && v !== null && v !== "" && Number.isFinite(Number(v)) && Number(v) >= 0 ? Number(v) : null);
    const ram = number(f.ramBytes);
    const vram = number(f.vramBytes);
    const plan = Number(f.plannedGb) > 0 ? Number(f.plannedGb) * GIB : 0;
    const file = Number(f.fileBytes) > 0 ? Number(f.fileBytes) : 0;
    const free = number(f.freeBytes);
    const split = String(f.split || "");
    const held = String(f.heldTitle || "");
    if (live) {
      this.ram = ram === null ? { kind: "unknown", title: t("cellMemUnknownTitle") }
        : { kind: ram === 0 ? "none" : "held", bytes: ram, title: held || t("cellRamTitle") };
      this.gpu = !f.gpuKnown || vram === null ? { kind: "unknown", title: t("cellMemUnknownTitle") }
        : { kind: vram === 0 ? "none" : "held", bytes: vram, title: held || `${t("vramChipTitle")}${split ? ` — ${split}` : ""}` };
    } else {
      this.ram = f.cpu && file ? { kind: "expected", bytes: file, title: t("cellRamEstChipTitle") } : { kind: "idle", title: t("cellMemIdleTitle") };
      this.gpu = f.cpu ? { kind: "none", bytes: 0, title: t("topologyCpuCellsHint") }
        : f.takesFree ? (free ? { kind: "expected", bytes: free, title: CellMemory.freeWords(f.everyCard) } : { kind: "idle", title: CellMemory.freeWords(f.everyCard) })
        : plan ? { kind: "expected", bytes: plan, title: t("vramPlanChipTitle") }
          : file ? { kind: "expected", bytes: file, title: t("vramEstChipTitle") }
            : { kind: "idle", title: t("cellMemIdleTitle") };
    }
  }

  static of(facts) {
    return new CellMemory(facts);
  }

  /** The class a badge wears: solid where the cell holds something, dashed where it is expected to, plain for a zero, muted for a dash. */
  static classOf(which, kind) {
    if (kind === "held") return which === "ram" ? "mbadge-ram" : "mbadge-vram";
    if (kind === "expected") return which === "ram" ? "mbadge-ram-est" : "mbadge-vram-est";
    return kind === "none" ? "mbadge-mem-zero" : "mbadge-mem-unknown";
  }

  /** The figure of a part: "≈" before an estimate, "—" where nothing is told. The badge and the window's tile say it alike. */
  static figure(part) {
    if (part.kind === "unknown" || part.kind === "idle") return "—";
    return `${part.kind === "expected" ? "≈" : ""}${CellMemory.gb(part.bytes)}`;
  }

  /** What a badge says: the label, then the figure. */
  static textOf(label, part) {
    return `${label} ${CellMemory.figure(part)}`;
  }

  /** The class attribute of a badge: every badge's, and its kind's. The badge is drawn with it and written again with it. */
  static classes(which, kind) {
    return `mbadge ${CellMemory.classOf(which, kind)}`;
  }

  badge(which) {
    const part = this[which];
    return `<span class="${CellMemory.classes(which, part.kind)}" data-t="${CellMemory.HOOKS[which]}" data-t-state="${part.kind}"`
      + ` title="${escapeHtml(part.title)}">${escapeHtml(CellMemory.textOf(CellMemory.LABELS[which], part))}</span>`;
  }

  /** Both badges, RAM first; nothing for a port with no model yet. */
  html() {
    return this.reserved ? "" : `${this.badge("ram")}${this.badge("gpu")}`;
  }

  /** The cell window's Overview tile of one part: the figure its badge says and, under it, what kind of figure that is — marked for
   *  the live patch. */
  tile(which, label) {
    const part = this[which];
    const hooks = CellMemory.TILE_HOOKS[which];
    return { id: which, label, value: CellMemory.figure(part), sub: t(CellMemory.WORDS[part.kind]), live: hooks.value, liveSub: hooks.sub };
  }

  /** Words written again in place, only where they changed: a tick that moves nothing writes nothing. */
  static say(el, words) {
    if (el && el.textContent !== words) el.textContent = words;
  }

  /** One badge drawn earlier, written again from this memory — its class, its state, its tip and its words — where it says otherwise. */
  write(el, which) {
    if (!el) return;
    const part = this[which];
    const cls = CellMemory.classes(which, part.kind);
    if (el.className !== cls) el.className = cls;
    if (el.getAttribute("data-t-state") !== part.kind) el.setAttribute("data-t-state", part.kind);
    if (el.getAttribute("title") !== part.title) el.setAttribute("title", part.title);
    CellMemory.say(el, CellMemory.textOf(CellMemory.LABELS[which], part));
  }

  /** What this memory says, written into a cell's line, card or window drawn earlier: its two badges, the window's two tiles and the
   *  figure of each card it lists. Only what a process holds now is written: a parked cell keeps the estimate it was drawn with — its
   *  phase is structure, and a start or a stop draws the card anew. */
  patch(root) {
    if (!this.live || this.reserved || !root?.querySelector) return;
    for (const which of ["ram", "gpu"]) {
      this.write(root.querySelector(`[data-t="${CellMemory.HOOKS[which]}"]`), which);
      const hooks = CellMemory.TILE_HOOKS[which];
      CellMemory.say(root.querySelector(`[${hooks.value}]`), CellMemory.figure(this[which]));
      CellMemory.say(root.querySelector(`[${hooks.sub}]`), t(CellMemory.WORDS[this[which].kind]));
    }
    for (const el of root.querySelectorAll?.(`[${CellMemory.CARD_HOOK}]`) || []) {
      const card = this.cards.find((c) => String(c.i) === el.getAttribute(CellMemory.CARD_HOOK));
      CellMemory.say(el, CellMemory.cardFigure(card?.mib));
    }
  }
}
