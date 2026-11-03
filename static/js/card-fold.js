// Which cards on the board fold into a line, and how a folded one opens.
import { t } from "./i18n.js";
import { copyText } from "./utils.js";

/**
 * The board's two long lanes — model cells and client agents — drew every card
 * at full height. On 2026-09-23 the controller had 24 cells of which 6 ran, and
 * 14 client routes of which one had a fallback, yet every card carried its
 * whole body: seven screens of scrolling to find the six that work.
 *
 * This object holds what folding depends on: the operator's per-lane choice
 * (compact or full), the cards pinned open, and the one rule for what is quiet
 * enough to fold. A card in motion or in trouble never folds quietly — a line
 * drawn over trouble in the colour of the rest is trouble drawn as normal. A cell
 * that FAILED folds into a red line (cellFailed), and its window opens on the reason.
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
    // The tab each cell's window shows, chosen in this visit (cell-window.js) — kept here so a repaint of the lane
    // draws the window on the tab the operator left it on. Not stored: the next visit opens on the overview.
    this.windowTabs = new Map();
    // The cards the operator is setting up in this visit — a client just added, an agent just
    // given a port: drawn open in place (as if pinned) until folded by hand or the page
    // reloads. A new card folded into a line the moment its first port came, and the fallback
    // "+" the operator was about to press went with it (2026-10-08). Not stored: a setup ends
    // with the visit. A key ending in ":" holds every card it begins (a client's agents).
    this.fresh = new Set();
    // How many cards each lane holds, as the last board paint counted them (syncSwitches):
    // a lane with none shows no fold switch. Null until a paint has counted.
    this.counts = null;
  }

  /** The tab the window of cell `key` shows: the one chosen in this visit, "" before any was. */
  windowTab(key) { return this.windowTabs.get(String(key)) || ""; }

  chooseWindowTab(key, tab) { this.windowTabs.set(String(key), String(tab || "")); }

  /** The key of an agent's card; with no agent, the prefix of every card of the client. */
  static agentKey(hostId, agentId = "") { return `agent:${hostId}:${agentId}`; }

  /** Keep the card `key` (or the cards a "…:" prefix begins) open for this visit. */
  hold(key) { if (key) this.fresh.add(String(key)); }

  /** The hold that keeps `key` open, or "". */
  holdOf(key) {
    const k = String(key);
    for (const held of this.fresh) if (held === k || (held.endsWith(":") && k.startsWith(held))) return held;
    return "";
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

  /** Let machine `hostId`'s chips show a new cell `launcher` runs, as it comes:
   *  a chip that would hide it gives way to that launcher's (2026-09-26 — the
   *  "+" of an engine's model stands over the chips, under any of them); "all"
   *  shows it already and stays. */
  reveal(hostId, launcher) {
    const chosen = this.launcherOf(hostId);
    return chosen && chosen !== String(launcher || "") ? this.setLauncher(hostId, launcher) : chosen;
  }

  /** Whether a folded card of `lane` opens in a window (not floating over the lane). */
  opensInWindow(lane) { return CardFold.OPENS[lane] === "window"; }

  togglePin(key) {
    const k = String(key);
    // A card held open for its setup folds back at the first press, and is not pinned for good;
    // a press on a pinned one drops its hold too, or the unpinned card would stay open.
    const held = this.holdOf(k);
    if (held) this.fresh.delete(held);
    if (held && !this.pinned.has(k)) {
      if (this.peekKey === k) this.peekKey = "";
      return false;
    }
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
    return this.isPinned(key) || this.holdOf(key) ? "pinned" : "line";
  }

  /** The lane switches say which way they are set, in words on hover. Called
   *  after every paint of the board, so a language change reaches them too. */
  syncSwitches(doc = globalThis.document, counts = null) {
    if (counts) this.counts = counts;
    for (const btn of doc?.querySelectorAll?.("[data-board-density]") || []) {
      const lane = btn.dataset.boardDensity;
      // "⊟" over an empty lane folded nothing and read as a control without a purpose
      // (2026-10-08). A lane not counted keeps its switch.
      if (this.counts && lane in this.counts) btn.hidden = !(Number(this.counts[lane]) > 0);
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

  /** Whether a cell has failed: its start ended in an error, or its process lives around a dead engine. It folds
   *  into a RED line, and its window opens on the reason (2026-10-17, the owner, shown the big card of a cell
   *  that failed to load its projector: "red, but thin, like the usual one — and the description of the error
   *  when the window opens"). Not while it is being deleted: that is motion. */
  static cellFailed(f = {}) {
    return !!f.failed && !f.deleting;
  }

  /** A requested start/stop stays in its line, with a locked spinning switch.
   *  So does a start in progress — the copy of the model, its load, its
   *  warm-up — when the line can say how it goes (`progress`: the strip under
   *  the name, start-strip.js); the full card used to open for it by itself,
   *  and the owner (2026-10-18) did not want a cell widened when he started it.
   *  Incidents still need the full card. Motion is foldable, but never idle:
   *  the machine's eye must keep it visible. A failed cell folds too, as a red
   *  line (cellFailed), and never hides either. */
  static cellFoldable(f = {}) {
    return CardFold.cellQuiet(f) || CardFold.cellFailed(f) || (["start", "stop"].includes(f.motion)
      && !f.deleting && !f.crashed && !f.unreachable && !f.failed)
      || (!!f.progress && !f.deleting && !f.crashed && !f.unreachable && !f.failed);
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
  /** What stands over a cell's window: a confirm, the launch command, the cell editor, a talk window — and an open "⋯" menu of
   *  the parts (ui-menus.js), which Escape closes first. */
  static LAYERS = ".modal-overlay, .topology-llama-edit-overlay, .history-detail-overlay, .talk-overlay, .ui-menu-list";

  /** True while one of them is shown: Escape is that dialog's then, not the window's under it. */
  static layerAbove(doc) {
    return [...(doc?.querySelectorAll?.(FoldPeek.LAYERS) || [])].some((el) => !el.hidden && (el.getClientRects?.().length ?? 1) > 0);
  }

  constructor(fold, { busy = () => false, changed = () => {} } = {}) {
    this.fold = fold;
    this.busy = busy;
    this.changed = changed;
    this.timer = 0;
    this.copyTimer = 0;
    this.bound = false;
    // The button a window was opened by from outside its line — the panel of a cell chosen on the machine's map
    // (machine-head.js): Escape gives it the keyboard back.
    this.returnTo = null;
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

  /** A cell's window over the board. The window is already in its slot
   *  (cell-window.js CellWindow); opening it is a class, and openKey keeps
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

  /** The window of cell `key` opened by a button outside its line: the panel of a cell chosen on the machine's map. The window is
   *  in its slot; a cell whose slot the page does not hold has none to open. */
  openFrom(button, key, doc = globalThis.document) {
    const k = String(key || "").replace(/["\\]/g, "\\$&");
    const slot = k ? doc?.querySelector?.(`.fold-slot[data-fold-key="${k}"]`) : null;
    if (!slot) return false;
    this.openWindow(slot);
    this.returnTo = button || null;
    return true;
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
    const opener = target.closest("[data-cell-window-open]");
    if (opener) {
      e.preventDefault();
      this.openFrom(opener, opener.dataset.cellWindowOpen, target.ownerDocument);
      return;
    }
    if (this.onWindowClick(e, target)) return;
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

  /** A click in a cell's window that is the window's own business — a tab, the "⋯", the address — changes what it shows,
   *  not the board: no repaint. True when it was one. Any other click in the window shuts its open menu, after the item's
   *  own handler (bound on the item by the lane) has run. */
  onWindowClick(e, target) {
    const win = target.closest(".cell-window");
    if (!win) return false;
    const tab = target.closest("[data-cell-window-tab]");
    if (tab) {
      e.preventDefault();
      this.showTab(win, tab.dataset.cellWindowTab || "");
      this.closeMenu(win);
      return true;
    }
    if (target.closest("[data-cell-window-more]")) {
      e.preventDefault();
      this.toggleMenu(win);
      return true;
    }
    const copy = target.closest("[data-cell-window-copy]");
    if (copy) {
      e.preventDefault();
      this.copy(win, copy.dataset.cellWindowCopy || "");
    }
    this.closeMenu(win);
    return !!copy;
  }

  /** Shows tab `tab` of window `win` and remembers it for the repaints to come. The band's "Log" leads to a tab and is
   *  none itself: only the tab buttons change their look. */
  showTab(win, tab) {
    this.fold.chooseWindowTab(win.dataset.tId || "", tab);
    for (const b of win.querySelectorAll('[role="tab"][data-cell-window-tab]')) {
      const on = b.dataset.cellWindowTab === tab;
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", String(on));
    }
    for (const p of win.querySelectorAll("[data-cell-window-panel]")) p.hidden = p.dataset.cellWindowPanel !== tab;
  }

  toggleMenu(win) {
    const menu = win.querySelector(".cwh-menu");
    if (!menu) return;
    const open = menu.hidden;
    menu.hidden = !open;
    win.querySelector("[data-cell-window-more]")?.setAttribute("aria-expanded", String(open));
    if (open) menu.querySelector("button:not([disabled])")?.focus?.();
  }

  /** Shuts the "⋯" of window `win`; true when it was open. */
  closeMenu(win) {
    const menu = win?.querySelector?.(".cwh-menu");
    if (!menu || menu.hidden) return false;
    menu.hidden = true;
    win.querySelector("[data-cell-window-more]")?.setAttribute("aria-expanded", "false");
    return true;
  }

  /** Copies the address and says so where it is written, for a moment: copied, or that the copy did not land. */
  async copy(win, text, copy = copyText) {
    const shown = win.querySelector("[data-cell-window-copied]");
    const ok = await copy(text);
    if (!shown) return ok;
    shown.textContent = t(ok ? "cwCopied" : "cwCopyFailed");
    clearTimeout(this.copyTimer);
    this.copyTimer = setTimeout(() => { shown.textContent = text; }, 1600);
    return ok;
  }

  onKey(e) {
    if (e.key === "Escape") {
      // A dialog over the window takes its own Escape: the window under it closed with it — under the window's own Apply
      // question too — and the launch command was left over the bare board.
      if (FoldPeek.layerAbove(globalThis.document)) return;
      // A menu open in the window shuts first; the window itself on the next Escape.
      const open = this.fold.openKey ? globalThis.document?.querySelector?.(".fold-slot.open > .cell-window") : null;
      if (open && this.closeMenu(open)) return;
      this.close();
      const was = this.closeWindow();
      // Back to the button the window was opened by, else to the line whose window it was — not to the top of the page.
      const back = this.returnTo?.isConnected ? this.returnTo : null;
      this.returnTo = null;
      if (was) (back || this.lineOf(was))?.focus?.();
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
