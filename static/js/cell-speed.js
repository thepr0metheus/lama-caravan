// What the line of a running cell says of speed — and whether the line breathes.
import { t } from "./i18n.js";

/**
 * The speed on a cell's line and whether the cell is working, from one rule.
 *
 * A cell is working while it answers a request: its server says how many it has (`requestsProcessing`), and the line breathes on a number
 * above 0. The speed is another fact. The scout reports the rate of the last request and holds it while the cell is idle, so a speed above 0
 * is no sign of work. The line used to breathe on it: a cell that had answered once breathed for good, with both video cards at 0 %
 * (the owner, 2026-10-18). A held speed stays on the line, quiet, and the word `last` stands before it.
 *
 * A scout that does not say how many requests run (an older one, a server without the number) leaves "not told" (null). A line that cannot
 * tell work from a held speed does not claim work: no breathing, and the speed is the last one. "Not told" is not 0, and it is not 1.
 *
 * The line is drawn twice — by the card builder and by the live patch — and both ask this class, so they cannot disagree.
 */
export class CellSpeed {
  /** A request count as the scout told it: a whole number from 0, or null — not told. Never a 0 in its place. */
  static count(value) {
    return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
  }

  constructor(server, running) {
    const s = server || {};
    const speed = Number(s.genTps);
    this.running = !!running;
    this.requests = CellSpeed.count(s.requestsProcessing);
    // The speed the line may show: only a running cell has one, and only a figure above 0.
    this.speed = this.running && Number.isFinite(speed) && speed > 0 ? speed : 0;
    this.working = this.running && this.requests !== null && this.requests > 0;
    this.held = this.speed > 0 && !this.working;
  }

  /** The words on the line: the speed, its number written by `format` (the board's formatTps), with `last` before it when it is held. */
  words(format) {
    if (!(this.speed > 0)) return "";
    const speed = `${format(this.speed)} t/s`;
    return this.held ? `${t("tpsLastLabel")} ${speed}` : speed;
  }

  /** What hovering the speed says: only a held speed needs explaining. "" for any other. */
  hint() {
    return this.held ? t("tpsLastHelp") : "";
  }
}
