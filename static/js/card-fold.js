// Which cards on the board fold into a line, and which one floats open now.
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

  constructor({ storage = CardFold.defaultStorage(), automated = !!globalThis.navigator?.webdriver } = {}) {
    this.storage = storage;
    this.automated = automated;
    this.densities = this.read(CardFold.KEY_DENSITY, {});
    this.pinned = new Set(this.read(CardFold.KEY_PINNED, []));
    // The card floating open now. Kept here, not only as a class on the DOM:
    // the board repaints its lanes wholesale, and a float that vanished with
    // every repaint would flicker shut under a resting pointer.
    this.peekKey = "";
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

  togglePin(key) {
    const k = String(key);
    if (this.pinned.has(k)) this.pinned.delete(k);
    else this.pinned.add(k);
    this.write(CardFold.KEY_PINNED, [...this.pinned]);
    if (this.peekKey === k) this.peekKey = "";
    return this.pinned.has(k);
  }

  /** How a card is drawn: "line" (folded; the full card floats on hover),
   *  "pinned" (the full card in place, with a control to fold it back) or
   *  "full" (never folds — the lane shows full cards, or the card is not quiet). */
  mode(lane, key, quiet) {
    if (!quiet || !this.folds(lane)) return "full";
    return this.isPinned(key) ? "pinned" : "line";
  }

  /** The lane switches say which way they are set, in words on hover. Called
   *  after every paint of the board, so a language change reaches them too. */
  syncSwitches(doc = globalThis.document) {
    for (const btn of doc?.querySelectorAll?.("[data-board-density]") || []) {
      const compact = this.folds(btn.dataset.boardDensity);
      btn.setAttribute("aria-pressed", String(compact));
      btn.title = t(compact ? "densityCompactTitle" : "densityFullTitle");
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
 * The pointer and keyboard side of folding. A folded card floats open in full
 * after the pointer rests on its line, or at once when keyboard focus enters
 * it; a click on the line or on the 📌 keeps it open, ▴ folds it back.
 *
 * Delegated on the document, once: the board repaints its lanes wholesale, and
 * listeners on the cards themselves would die with every repaint. The float is
 * the card itself, not a copy — the card's buttons are bound to their own
 * elements at render, and a copy would carry none of that.
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
    if (!slot || slot.classList.contains("peek")) return;
    this.timer = setTimeout(() => this.open(slot), FoldPeek.DELAY_MS);
  }

  onOut(e) {
    const slot = this.slotOf(e.target);
    if (!slot || slot.contains(e.relatedTarget)) return;
    this.close(slot);
  }

  // Keyboard focus only. A mouse click also focuses the line, and floating the
  // card open under a pressed button would swallow the click it started.
  onFocusIn(e) {
    const slot = this.slotOf(e.target);
    if (slot && e.target?.matches?.(":focus-visible")) this.open(slot);
  }

  onFocusOut(e) {
    const slot = this.slotOf(e.target);
    if (slot && !slot.contains(e.relatedTarget)) this.close(slot);
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
    const pin = target.closest?.("[data-fold-pin]");
    const line = pin ? null : target.closest?.(".fold-row");
    // The line's own controls (▶ start) and the cable's handle keep their jobs.
    if (!pin && (!line || target.closest("button, a, .topology-handle"))) return;
    const key = (pin || line).closest(".fold-slot")?.dataset.foldKey;
    if (!key) return;
    e.preventDefault();
    this.fold.togglePin(key);
    this.changed();
  }

  onKey(e) {
    if (e.key === "Escape") { this.close(); return; }
    if ((e.key === "Enter" || e.key === " ") && e.target?.matches?.(".fold-row")) {
      e.preventDefault();
      e.target.click();
    }
  }
}

/** The board's one fold state. */
export const CARD_FOLD = new CardFold();
