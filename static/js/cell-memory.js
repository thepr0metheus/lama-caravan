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
import { t } from "./i18n.js";
import { escapeHtml } from "./utils.js";

const GIB = 2 ** 30;

export class CellMemory {
  /** The hook a test finds each badge by (docs/testability.md), and the word its text begins with. One place for both. */
  static HOOKS = { ram: "cell-ram", gpu: "cell-gpu" };
  static LABELS = { ram: "RAM", gpu: "GPU" };

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
   *   plannedGb  the runner's own measured figure for the card, in GiB (0: none)
   *   fileBytes  the model file's size, for the estimate (0: not known)
   *   heldTitle  the tip of a badge that says what is held, where the cell's own words are not the machine's: an engine's cell says it is the
   *              engine that reports it
   */
  constructor(f = {}) {
    this.reserved = !!f.reserved;
    const live = !!f.live;
    const number = (v) => (typeof v !== "boolean" && v !== null && v !== "" && Number.isFinite(Number(v)) && Number(v) >= 0 ? Number(v) : null);
    const ram = number(f.ramBytes);
    const vram = number(f.vramBytes);
    const plan = Number(f.plannedGb) > 0 ? Number(f.plannedGb) * GIB : 0;
    const file = Number(f.fileBytes) > 0 ? Number(f.fileBytes) : 0;
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

  /** What a badge says: the label, then the figure — "≈" before an estimate, "—" where nothing is told. */
  static textOf(label, part) {
    if (part.kind === "unknown" || part.kind === "idle") return `${label} —`;
    return `${label} ${part.kind === "expected" ? "≈" : ""}${CellMemory.gb(part.bytes)}`;
  }

  badge(which) {
    const part = this[which];
    return `<span class="mbadge ${CellMemory.classOf(which, part.kind)}" data-t="${CellMemory.HOOKS[which]}" data-t-state="${part.kind}"`
      + ` title="${escapeHtml(part.title)}">${escapeHtml(CellMemory.textOf(CellMemory.LABELS[which], part))}</span>`;
  }

  /** Both badges, RAM first; nothing for a port with no model yet. */
  html() {
    return this.reserved ? "" : `${this.badge("ram")}${this.badge("gpu")}`;
  }
}
