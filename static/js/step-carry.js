// Carrying a pool's step to another place in its order — the way the home start page carries its
// cards (the home portal's sort.js; the operator, 2026-10-11: "сделай красивее, как там"). A press on a
// step's grip that moves a few pixels lifts the step: the card follows the pointer, its seat stays
// behind as a dashed empty place, and the other steps slide aside as the place moves. Letting go
// glides the card into the place; Esc gives it back. Alt+↑/↓ on a focused grip moves the step one
// place. Only elements move here: what the new order means — the save — is the caller's (`onSort`),
// and until the save answers, the lane is not drawn over the carried order (`busy`).
//
// The seat is the step's own list item, left in the flow: the card inside it is what travels, by a
// transform. So nothing leaves its frame — the card keeps every style its pool gives it — and the
// place it will land in is exactly the size of what was lifted.
//
// The same carrier carries Routing's own cards — its clients, sets and pools (the owner,
// 2026-10-12: "the order of the blocks changed by dragging", 1.3.503): what a seat, a list, a grip and
// an id are is told it (`parts`), and so is what scrolls when the pointer leans on an edge — the
// Routing scrolls its board, not the window, and a carry along it scrolled nothing until then.

// First (where the elements are seen), change, play (slide from there to where they now stand).
export class Slide {
  static DURATION = 220;
  static EASING = "cubic-bezier(.2, .8, .2, 1)";
  static ID = "step-slide";   // the slides this class starts, told from an element's other animations

  static reduced() {
    return !!globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;
  }

  static run(elements, change) {
    const seen = new Map(elements.map((el) => [el, el.getBoundingClientRect().top]));
    // A slide still running carries its own offset: it goes before the new places are measured,
    // and the new slide starts from where the element was seen, not from where it was going.
    for (const el of elements) for (const a of el.getAnimations?.() || []) if (a.id === Slide.ID) a.cancel();
    change();
    if (Slide.reduced()) return;
    for (const el of elements) {
      if (!el.isConnected) continue;
      const dy = seen.get(el) - el.getBoundingClientRect().top;
      if (Math.abs(dy) < 0.5) continue;
      const slide = el.animate?.([{ transform: `translateY(${dy}px)` }, { transform: "none" }],
        { duration: Slide.DURATION, easing: Slide.EASING });
      if (slide) slide.id = Slide.ID;
    }
  }
}

export class StepCarry {
  static SLOP = 5;      // px a press travels before it becomes a carry
  static EDGE = 60;     // px from the scroller's top or bottom where carrying scrolls it
  static GLIDE = 180;   // ms the card glides into its place
  static LAZY = 700;    // ms the keyboard waits after its last move before the order is saved
  //: What a pool's steps are made of: the seat, its list, the grip, the step's id, the pool's id, and
  //: the card that travels. A carrier of other cards is given its own (`parts`).
  static STEPS = {
    item: ".pool-rung",
    list: ".pool-ladder",
    grip: "[data-pool-grip]",
    idOf: (rung) => rung.querySelector("[data-pool-step]")?.dataset.poolStep,
    ownerOf: (list) => list.closest("[data-pool-id]")?.dataset.poolId || "",
    card: (rung) => rung.querySelector(":scope > .pool-step"),
  };

  constructor(root, { onSort = async () => {}, win = globalThis, doc = globalThis.document, parts = {}, scroller = null,
    sway = Infinity, onMove = null } = {}) {
    this.root = root;
    this.parts = { ...StepCarry.STEPS, ...parts };
    this.scroller = scroller;   // (the list carried in) → the element that scrolls, or none: the window
    this.sway = sway;           // px the card may go to either side of where it stands: a column that scrolls cuts what stands out of it
    this.onMove = onMove;       // () → after each step of a carry: Routing measures its cables again
    this.onSort = onSort;   // (ownerId, ids) → a promise: the order a carry left behind
    this.win = win;
    this.doc = doc;
    this.phase = "idle";    // idle | pending (pressed, not yet carried) | carrying | landing | saving
    this.rung = null;       // the list item whose card is carried
    this.list = null;       // the pool's ordered list
    this.pointerId = null;
    this.start = { x: 0, y: 0 };
    this.pointer = { x: 0, y: 0 };
    this.before = [];       // the order at the moment of lifting
    this.seatTop = 0;       // where the seat stood at that moment
    this.frame = 0;
    this.scrollFrame = 0;
    this.scrolling = 0;
    this.keyed = null;      // {list, before} while the keyboard's moves wait to be saved
    this.lazy = 0;
    this.onPointerMove = (event) => this.move(event);
    this.onUp = (event) => this.release(event, false);
    this.onCancel = (event) => this.release(event, true);
    this.onEsc = (event) => { if (event.key === "Escape" && this.phase === "carrying") this.release(event, true); };
    root.addEventListener("pointerdown", (event) => this.press(event));
    root.addEventListener("keydown", (event) => this.key(event));
  }

  // While a step is carried, landing, being saved or waiting for the keyboard's save, the lane must not
  // be drawn anew: the drawing would put back the order the controller still holds.
  get busy() {
    return this.phase !== "idle" || !!this.keyed;
  }

  static rungs(list, parts = StepCarry.STEPS) {
    return [...list.children].filter((el) => el.matches(parts.item));
  }

  static order(list, parts = StepCarry.STEPS) {
    return StepCarry.rungs(list, parts).map((rung) => parts.idOf(rung)).filter(Boolean);
  }

  static poolOf(list, parts = StepCarry.STEPS) {
    return parts.ownerOf(list);
  }

  card() {
    return this.rung ? this.parts.card(this.rung) : null;
  }

  // ── the pointer ──

  press(event) {
    if (this.phase !== "idle" || event.button !== 0 || event.isPrimary === false) return;
    const rung = event.target.closest?.(this.parts.grip)?.closest(this.parts.item);
    const list = rung?.parentElement;
    if (!rung || !list?.matches(this.parts.list) || StepCarry.rungs(list, this.parts).length < 2) return;
    event.preventDefault();   // no text selection, and no drag of the browser's own
    this.flush();
    Object.assign(this, { rung, list, phase: "pending", pointerId: event.pointerId,
      start: { x: event.clientX, y: event.clientY }, pointer: { x: event.clientX, y: event.clientY } });
    this.win.addEventListener("pointermove", this.onPointerMove);
    this.win.addEventListener("pointerup", this.onUp);
    this.win.addEventListener("pointercancel", this.onCancel);
    this.win.addEventListener("keydown", this.onEsc);
  }

  move(event) {
    if (event.pointerId !== this.pointerId) return;
    this.pointer = { x: event.clientX, y: event.clientY };
    if (this.phase === "pending" && Math.hypot(this.pointer.x - this.start.x, this.pointer.y - this.start.y) > StepCarry.SLOP) this.lift();
    else if (this.phase === "carrying") this.follow();
  }

  release(event, cancelled) {
    if (event.pointerId !== undefined && event.pointerId !== this.pointerId) return;
    this.win.removeEventListener("pointermove", this.onPointerMove);
    this.win.removeEventListener("pointerup", this.onUp);
    this.win.removeEventListener("pointercancel", this.onCancel);
    this.win.removeEventListener("keydown", this.onEsc);
    if (this.phase === "pending") { this.reset(); return; }   // never carried: a plain press
    if (this.phase !== "carrying") return;
    if (!this.rung.isConnected) { this.reset(); return; }      // the lane was drawn over it: nothing to land
    if (!cancelled && Number.isFinite(event.clientX)) {
      // A flick can end inside one frame: let go where the pointer is now.
      this.pointer = { x: event.clientX, y: event.clientY };
      this.settle();
    }
    if (cancelled) this.home();
    this.land(cancelled);
  }

  // The press became a carry: the card rises, and its seat stays as the empty place.
  lift() {
    this.before = StepCarry.order(this.list, this.parts);
    this.seatTop = this.rung.getBoundingClientRect().top;
    this.rung.style.setProperty("--hole-h", `${this.card()?.offsetHeight || 0}px`);
    this.rung.classList.add("carried");
    this.list.classList.add("sorting");
    this.doc.body?.classList.add("step-carrying");
    this.win.getSelection?.()?.removeAllRanges?.();
    this.phase = "carrying";
    this.follow();
  }

  // One update per frame, however fast the pointer reports.
  follow() {
    if (this.frame) return;
    this.frame = this.win.requestAnimationFrame(() => {
      this.frame = 0;
      this.settle();
    });
  }

  settle() {
    if (this.phase !== "carrying") return;
    this.place();
    const moved = this.rung.getBoundingClientRect().top - this.seatTop;   // the seat itself moved with the order
    const across = Math.max(-this.sway, Math.min(this.sway, this.pointer.x - this.start.x));
    this.card().style.transform = `translate(${across}px, ${this.pointer.y - this.start.y - moved}px)`;
    this.edge();
    this.onMove?.();
  }

  // Where a seat stands in its list, by the layout: its offsetTop counts from its offsetParent — the
  // list itself when the list is positioned (Routing's columns), else the parent both share (a
  // pool's ladder in its card), from which the list's own offset is taken away.
  static within(list, rung) {
    return rung.offsetParent === list ? rung.offsetTop : rung.offsetTop - list.offsetTop;
  }

  // The empty place goes where the pointer says: before the first step whose middle is below it.
  // Middles come from the layout (offsetTop), not from what is seen: a step sliding aside must not
  // send the place back and forth while it slides.
  place() {
    const others = StepCarry.rungs(this.list, this.parts).filter((rung) => rung !== this.rung);
    // A list that scrolls itself (a column of Routing) is read from its scrolled top: offsetTop counts from the top of what it holds.
    const y = this.pointer.y - this.list.getBoundingClientRect().top + (this.list.scrollTop || 0);
    const index = others.filter((rung) => y > StepCarry.within(this.list, rung) + rung.offsetHeight / 2).length;
    if (index === StepCarry.rungs(this.list, this.parts).indexOf(this.rung)) return;
    Slide.run(others, () => this.list.insertBefore(this.rung, others[index] || null));
  }

  // Esc: the steps go back to the order they had when the card was lifted.
  home() {
    const rungs = StepCarry.rungs(this.list, this.parts);
    const byId = new Map(rungs.map((rung) => [this.parts.idOf(rung), rung]));
    const others = rungs.filter((rung) => rung !== this.rung);
    Slide.run(others, () => { for (const id of this.before) if (byId.get(id)) this.list.appendChild(byId.get(id)); });
  }

  // What scrolls when the pointer leans on an edge: the element given for the list carried in (Routing's
  // column), or the window — its top and bottom, and the way to scroll it.
  scrollBox() {
    const el = this.scroller?.(this.list);
    if (!el) return { top: 0, bottom: this.win.innerHeight || 0, by: (dy) => this.win.scrollBy(0, dy) };
    const box = el.getBoundingClientRect();
    return { top: box.top, bottom: box.bottom, by: (dy) => { el.scrollTop += dy; } };
  }

  // Near the top or bottom of the scroller, carrying scrolls it the way the pointer leans.
  edge() {
    const box = this.scrollBox();
    const lean = this.pointer.y < box.top + StepCarry.EDGE ? -1 : this.pointer.y > box.bottom - StepCarry.EDGE ? 1 : 0;
    const depth = lean < 0 ? box.top + StepCarry.EDGE - this.pointer.y : this.pointer.y - (box.bottom - StepCarry.EDGE);
    this.scrolling = lean * Math.min(16, Math.max(2, depth / 4));
    if (lean && !this.scrollFrame) this.scrollFrame = this.win.requestAnimationFrame(() => this.scrollStep());
  }

  scrollStep() {
    this.scrollFrame = 0;
    if (this.phase !== "carrying" || !this.scrolling) return;
    this.scrollBox().by(this.scrolling);
    this.settle();   // the places under the pointer have changed
  }

  // Letting go: the card glides from where it is seen into its place.
  land(cancelled) {
    this.phase = "landing";
    this.scrolling = 0;
    // The click that follows a carry is the carry's own, not a press on what lies under the pointer.
    const swallow = (event) => { event.preventDefault(); event.stopPropagation(); };
    this.win.addEventListener("click", swallow, { capture: true, once: true });
    this.win.setTimeout(() => this.win.removeEventListener("click", swallow, { capture: true }), 400);
    const card = this.card();
    const from = card.style.transform || "none";
    const glide = Slide.reduced() ? null : card.animate?.([{ transform: from }, { transform: "translate(0px, 0px)" }],
      { duration: StepCarry.GLIDE, easing: Slide.EASING });
    card.style.transform = "";
    const done = () => this.settleDown(cancelled);
    if (glide) { glide.onfinish = done; glide.oncancel = done; }
    // A page that is not painted (a hidden tab) does not finish its animations; whichever comes first lands the card.
    this.win.setTimeout(done, StepCarry.GLIDE + 120);
  }

  settleDown(cancelled) {
    if (this.phase !== "landing") return;   // landed already
    const list = this.list;
    this.rung.classList.remove("carried");
    this.rung.style.removeProperty("--hole-h");
    list.classList.remove("sorting");
    this.doc.body?.classList.remove("step-carrying");
    const after = StepCarry.order(list, this.parts), before = this.before;
    const changed = !cancelled && after.join("\n") !== before.join("\n");
    this.reset();
    if (changed) this.save(StepCarry.poolOf(list, this.parts), after);
    this.onMove?.();
  }

  // The caller saves and says what went wrong (PoolCards.sort toasts the refusal); a save that throws
  // anyway is named in the console, and on every way out the lane is free to draw again.
  async save(poolId, order) {
    this.phase = "saving";
    try {
      await this.onSort(poolId, order);
    } catch (err) {
      globalThis.console?.error?.("step-carry: the new order was not saved", err);
    } finally {
      this.phase = "idle";
    }
  }

  reset() {
    if (this.frame) this.win.cancelAnimationFrame?.(this.frame);
    Object.assign(this, { phase: "idle", rung: null, list: null, pointerId: null, frame: 0, scrolling: 0 });
  }

  // ── the keyboard ──

  // Alt+↑/↓ on a step's grip moves it one place; the order is saved a moment after the last press.
  key(event) {
    if (!event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key) || this.phase !== "idle") return;
    const rung = event.target.closest?.(this.parts.grip)?.closest(this.parts.item);
    const list = rung?.parentElement;
    if (!rung || !list?.matches(this.parts.list)) return;
    event.preventDefault();
    const rungs = StepCarry.rungs(list, this.parts), at = rungs.indexOf(rung);
    const to = event.key === "ArrowUp" ? at - 1 : at + 1;
    if (to < 0 || to >= rungs.length) return;
    if (this.keyed && this.keyed.list !== list) this.flush();
    if (!this.keyed) this.keyed = { list, before: StepCarry.order(list, this.parts) };
    Slide.run(rungs.filter((r) => r !== rung), () => list.insertBefore(rung, event.key === "ArrowUp" ? rungs[to] : rungs[to].nextSibling));
    event.target.focus?.();
    this.win.clearTimeout(this.lazy);
    this.lazy = this.win.setTimeout(() => this.flush(), StepCarry.LAZY);
  }

  // Saves the keyboard's moves so far as one change of order. Safe to call when there are none.
  flush() {
    this.win.clearTimeout(this.lazy);
    if (!this.keyed) return;
    const { list, before } = this.keyed;
    this.keyed = null;
    const after = StepCarry.order(list, this.parts);
    if (after.join("\n") !== before.join("\n")) this.save(StepCarry.poolOf(list, this.parts), after);
  }
}
