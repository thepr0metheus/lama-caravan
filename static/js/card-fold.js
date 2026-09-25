// Which cards on the board fold into a line, and how a folded one opens.
import { t } from "./i18n.js";

/**
 * The board's two long lanes — model cells and client agents — drew every card
 * at full height. On 2026-09-23 the controller had 24 cells of which 6 ran, and
 * 14 client routes of which one had a fallback, yet every card carried its
 * whole body: seven screens of scrolling to find the six that work.
 *
 * This object holds what folding depends on: the operator's per-lane choice
 * (compact or full), the cards pinned open, and the one rule for what is quiet
 * enough to fold. A card in motion or in trouble never folds — a line drawn
 * over trouble is trouble drawn as normal.
 *
 * Automation (navigator.webdriver) sees full cards by default: the E2E suite
 * drives buttons that a folded card shows only when it floats open. It can
 * fold them with the lane switch like anyone else.
 */
export class CardFold {
  static LANES = ["cells", "clients"];
  static KEY_DENSITY = "boardCardDensity";
  static KEY_PINNED = "boardCardPinned";
  static KEY_HIDE_IDLE = "boardCellsHideIdle";
  static KEY_LAUNCHER = "boardCellsLauncher";
  // How a folded card of each lane opens. A cell opens in a window on a click
  // (2026-09-25, the operator's choice: the card that floated open on hover,
  // and could be pinned in place, is gone for cells). An agent still floats
  // over its lane on hover and pins with a click.
  static OPENS = { cells: "window", clients: "float" };

  constructor({ storage = CardFold.defaultStorage(), automated = !!globalThis.navigator?.webdriver } = {}) {
    this.storage = storage;
    this.automated = automated;
    this.densities = this.read(CardFold.KEY_DENSITY, {});
    this.pinned = new Set(this.read(CardFold.KEY_PINNED, []));
    // The machines whose eye hides the cells that are not running (2026-09-25):
    // a choice per machine, as the eye sits on each machine's list of cells.
    this.hideIdle = new Set(this.read(CardFold.KEY_HIDE_IDLE, []));
    // What each machine's chips narrow its cells to (2026-09-25): "caravan"
    // or an engine runner's id, by machine; a machine not here shows them all.
    this.launchers = this.read(CardFold.KEY_LAUNCHER, {});
    // The card floating open now. Kept here, not only as a class on the DOM:
    // the board repaints its lanes wholesale, and a float that vanished with
    // every repaint would flicker shut under a resting pointer.
    this.peekKey = "";
    // The cell whose window is open now — here for the same reason: the
    // window is drawn inside its lane, and a repaint redraws the lane.
    this.openKey = "";
    // The engine whose panel is open under its machine's chips ("<machine>:
    // <runner>"), for the same reason; one at a time, not kept across pages.
    this.engineKey = "";
  }

  static defaultStorage() {
    try { return globalThis.localStorage || null; } catch { return null; }
  }

  read(key, fallback) {
    try {
      const value = JSON.parse(this.storage?.getItem(key) || "null");
      const sameShape = value !== null && typeof value === "object"
        && Array.isArray(value) === Array.isArray(fallback);
      return sameShape ? value : fallback;
    } catch {
      return fallback;
    }
  }

  write(key, value) {
    // A convenience of this browser: the board draws correctly without it.
    try { this.storage?.setItem(key, JSON.stringify(value)); } catch { /* see above */ }
  }

  /** "compact" or "full" for `lane`: what the operator chose, else the default. */
  density(lane) {
    const chosen = this.densities[lane];
    if (chosen === "compact" || chosen === "full") return chosen;
    return this.automated ? "full" : "compact";
  }

  folds(lane) { return this.density(lane) === "compact"; }

  toggleDensity(lane) {
    this.densities = { ...this.densities, [lane]: this.folds(lane) ? "full" : "compact" };
    this.write(CardFold.KEY_DENSITY, this.densities);
    return this.density(lane);
  }

  isPinned(key) { return this.pinned.has(String(key)); }

  /** Whether the eye of machine `hostId` hides its cells that are not running. */
  hidesIdle(hostId) { return this.hideIdle.has(String(hostId)); }

  toggleHideIdle(hostId) {
    const k = String(hostId);
    if (this.hideIdle.has(k)) this.hideIdle.delete(k);
    else this.hideIdle.add(k);
    this.write(CardFold.KEY_HIDE_IDLE, [...this.hideIdle]);
    return this.hideIdle.has(k);
  }

  /** The launcher machine `hostId`'s chips narrow its cells to, or "" — all of them. */
  launcherOf(hostId) {
    const chosen = this.launchers[String(hostId)];
    return typeof chosen === "string" ? chosen : "";
  }

  /** Narrow machine `hostId`'s cells to the ones `launcher` runs; "" shows them all. */
  setLauncher(hostId, launcher) {
    const k = String(hostId);
    const v = String(launcher || "");
    if (v) this.launchers[k] = v;
    else delete this.launchers[k];
    this.write(CardFold.KEY_LAUNCHER, this.launchers);
    return this.launcherOf(k);
  }

  /** Open the panel of engine `key` ("<machine>:<runner>"), or close it when
   *  it is the one open; opening one closes any other. Whether it is open now. */
  toggleEngineMenu(key) {
    const k = String(key || "");
    this.engineKey = this.engineKey === k ? "" : k;
    return !!k && this.engineKey === k;
  }

  /** Whether a folded card of `lane` opens in a window (not floating over the lane). */
  opensInWindow(lane) { return CardFold.OPENS[lane] === "window"; }

  togglePin(key) {
    const k = String(key);
    if (this.pinned.has(k)) this.pinned.delete(k);
    else this.pinned.add(k);
    this.write(CardFold.KEY_PINNED, [...this.pinned]);
    if (this.peekKey === k) this.peekKey = "";
    return this.pinned.has(k);
  }

  /** How a card is drawn: "line" (folded; the full card opens on hover or on
   *  a click, by its lane), "pinned" (the full card in place, with a control to
   *  fold it back) or "full" (never folds — the lane shows full cards, or the
   *  card is not quiet). */
  mode(lane, key, quiet) {
    if (!quiet || !this.folds(lane)) return "full";
    // A lane whose cards open in a window keeps none pinned in place: a pin this
    // browser saved before the window came is ignored, not drawn.
    if (this.opensInWindow(lane)) return "line";
    return this.isPinned(key) ? "pinned" : "line";
  }

  /** The lane switches say which way they are set, in words on hover. Called
   *  after every paint of the board, so a language change reaches them too. */
  syncSwitches(doc = globalThis.document) {
    for (const btn of doc?.querySelectorAll?.("[data-board-density]") || []) {
      const lane = btn.dataset.boardDensity;
      const compact = this.folds(lane);
      btn.setAttribute("aria-pressed", String(compact));
      // Each lane says how ITS lines open: telling the cells lane to rest the
      // pointer on a line would describe a float that is no longer there.
      const compactKey = this.opensInWindow(lane) ? "densityCompactWindowTitle" : "densityCompactTitle";
      btn.title = t(compact ? compactKey : "densityFullTitle");
      btn.setAttribute("aria-label", btn.title);
      btn.textContent = compact ? "⊟" : "⊞";
    }
  }

  /** Whether a cell may fold. Settled states only: running with nothing to
   *  report, or parked — configured, or reserved with no model yet. Starting,
   *  warming, stopping, failed, crashed or out of reach keeps the full card. */
  static cellQuiet(f = {}) {
    const settled = f.phase === "running" || f.phase === "stopped" || f.phase === "reserved";
    return settled && !f.transient && !f.crashed && !f.unreachable;
  }

  /** Whether a machine's eye may hide a cell: quiet, and not running — parked,
   *  or reserved with no model yet. What moves or is in trouble never hides,
   *  for the reason it never folds: gone from view, trouble reads as calm. */
  static cellIdle(f = {}) {
    return CardFold.cellQuiet(f) && f.phase !== "running";
  }

  /** Whether an agent may fold: it goes somewhere, and its last request did
   *  not fail. An agent with no route at all is the loudest case of the lane —
   *  folded, it would read as one more quiet line. There is no "stale" here any
   *  more: no report says whether an agent runs, so nothing may fold on it or
   *  refuse to. */
  static agentQuiet(f = {}) {
    return Number(f.routes) > 0 && !f.incident;
  }
}

/**
 * The pointer and keyboard side of folding. An agent's folded card floats open
 * in full after the pointer rests on its line, or at once when keyboard focus
 * enters it; a click on the line or on the 📌 keeps it open, ▴ folds it back.
 * A cell's line opens its card as a window on a click (Enter, Space); ✕, a
 * click on the dimmed board or Escape closes it.
 *
 * Delegated on the document, once: the board repaints its lanes wholesale, and
 * listeners on the cards themselves would die with every repaint. The float and
 * the window are the card itself, not a copy — the card's buttons are bound to
 * their own elements at render, and a copy would carry none of that.
 */
export class FoldPeek {
  /** How long the pointer rests on a line before its card floats open: long
   *  enough that crossing the lane does not flash every card on the way, short
   *  enough that looking at one does not feel like waiting. */
  static DELAY_MS = 300;

  constructor(fold, { busy = () => false, changed = () => {} } = {}) {
    this.fold = fold;
    this.busy = busy;
    this.changed = changed;
    this.timer = 0;
    this.bound = false;
  }

  slotOf(node) { return node?.closest?.('.fold-slot[data-fold-mode="line"]') || null; }

  /** Whether a slot's card floats over its lane — as opposed to opening in a
   *  window, which a resting pointer or a passing focus never does. */
  floats(slot) { return !this.fold.opensInWindow(slot?.dataset?.foldLane); }

  open(slot) {
    clearTimeout(this.timer);
    if (!slot || this.busy()) return;
    for (const other of slot.ownerDocument.querySelectorAll(".fold-slot.peek")) {
      if (other !== slot) other.classList.remove("peek");
    }
    slot.classList.add("peek");
    this.fold.peekKey = slot.dataset.foldKey || "";
  }

  close(slot, doc = globalThis.document) {
    clearTimeout(this.timer);
    const open = slot ? [slot] : [...(doc?.querySelectorAll(".fold-slot.peek") || [])];
    for (const s of open) s.classList.remove("peek");
    this.fold.peekKey = "";
  }

  /** A cell's card as a window over the board. The window is already in its
   *  slot (card-rows.js CellWindow); opening it is a class, and openKey keeps
   *  it open through a repaint of the lane. */
  openWindow(slot) {
    if (!slot || this.busy()) return;
    this.closeWindow(slot.ownerDocument);
    slot.classList.add("open");
    this.fold.openKey = slot.dataset.foldKey || "";
    // The keyboard lands in the window, on its way out: on the ✕ itself — the
    // dimmed board carries the same close mark and cannot take focus.
    slot.querySelector?.("button[data-cell-window-close]")?.focus?.();
  }

  /** The folded line of the card under `key`, in `doc`. */
  lineOf(key, doc = globalThis.document) {
    const k = String(key).replace(/["\\]/g, "\\$&");
    return doc?.querySelector?.(`.fold-slot[data-fold-key="${k}"] > .fold-row`) || null;
  }

  /** Closes the open window, if any; returns the key it had. */
  closeWindow(doc = globalThis.document) {
    for (const s of doc?.querySelectorAll?.(".fold-slot.open") || []) s.classList.remove("open");
    const was = this.fold.openKey;
    this.fold.openKey = "";
    return was;
  }

  bind(doc = globalThis.document) {
    if (this.bound || !doc) return;
    this.bound = true;
    doc.addEventListener("pointerover", (e) => this.onOver(e));
    doc.addEventListener("pointerout", (e) => this.onOut(e));
    doc.addEventListener("focusin", (e) => this.onFocusIn(e));
    doc.addEventListener("focusout", (e) => this.onFocusOut(e));
    doc.addEventListener("click", (e) => this.onClick(e));
    doc.addEventListener("keydown", (e) => this.onKey(e));
    this.fold.syncSwitches(doc);
  }

  onOver(e) {
    const slot = this.slotOf(e.target);
    clearTimeout(this.timer);
    if (!slot || !this.floats(slot) || slot.classList.contains("peek")) return;
    this.timer = setTimeout(() => this.open(slot), FoldPeek.DELAY_MS);
  }

  onOut(e) {
    const slot = this.slotOf(e.target);
    if (!slot || !this.floats(slot) || slot.contains(e.relatedTarget)) return;
    this.close(slot);
  }

  // Keyboard focus only. A mouse click also focuses the line, and floating the
  // card open under a pressed button would swallow the click it started.
  onFocusIn(e) {
    const slot = this.slotOf(e.target);
    if (slot && this.floats(slot) && e.target?.matches?.(":focus-visible")) this.open(slot);
  }

  onFocusOut(e) {
    const slot = this.slotOf(e.target);
    if (slot && this.floats(slot) && !slot.contains(e.relatedTarget)) this.close(slot);
  }

  onClick(e) {
    const target = e.target;
    if (!target?.closest) return;
    const lane = target.closest?.("[data-board-density]");
    if (lane) {
      this.fold.toggleDensity(lane.dataset.boardDensity);
      this.fold.syncSwitches(target.ownerDocument);
      this.changed();
      return;
    }
    // ✕ and the dimmed board around a window close it.
    if (target.closest("[data-cell-window-close]")) {
      e.preventDefault();
      this.closeWindow(target.ownerDocument);
      return;
    }
    const pin = target.closest?.("[data-fold-pin]");
    const line = pin ? null : target.closest?.(".fold-row");
    // The line's own controls (▶ start) and the cable's handle keep their jobs.
    if (!pin && (!line || target.closest("button, a, .topology-handle"))) return;
    const slot = (pin || line).closest(".fold-slot");
    const key = slot?.dataset?.foldKey;
    if (!key) return;
    e.preventDefault();
    if (line && !this.floats(slot)) {
      this.openWindow(slot);
      return;
    }
    this.fold.togglePin(key);
    this.changed();
  }

  onKey(e) {
    if (e.key === "Escape") {
      this.close();
      const was = this.closeWindow();
      // Back to the line whose window it was, not to the top of the page.
      if (was) this.lineOf(was)?.focus?.();
      return;
    }
    if ((e.key === "Enter" || e.key === " ") && e.target?.matches?.(".fold-row")) {
      e.preventDefault();
      e.target.click();
    }
  }
}

/** The board's one fold state. */
export const CARD_FOLD = new CardFold();
