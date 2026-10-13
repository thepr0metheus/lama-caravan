#!/usr/bin/env python3
"""Carrying a pool's step (static/js/step-carry.js), by values, on a small model of the page.

The operator, 2026-10-11: steps are carried the way the home start page carries its cards — the card
follows the pointer, its seat stays as an empty place, the others slide aside, letting go lands it,
Esc gives it back, Alt+arrows move it. The model lays the rungs out by their order (40 px each), so
where the empty place goes, what is saved and what is not can be checked as values.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

PROBE = r'''
import assert from "node:assert/strict";
const { StepCarry, Slide } = await import("../static/js/step-carry.js");

// ── a small page: an <ol> of rungs laid out by their order, each 40 px tall, the list at y = 100 ──
const key = (attr) => attr.slice(6, -1).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
class El {
  constructor(cls = "", data = {}) {
    this.classes = new Set(cls.split(" ").filter(Boolean)); this.dataset = data; this.children = []; this.parentElement = null;
    this.h = 40; this.anims = []; this.listeners = {}; this.focused = 0;
    const props = {}; this.style = { props, transform: "", setProperty(k, v) { props[k] = v; }, removeProperty(k) { delete props[k]; } };
  }
  get classList() { const c = this.classes; return { add: (x) => c.add(x), remove: (x) => c.delete(x), contains: (x) => c.has(x) }; }
  matches(sel) { return sel.startsWith("[data-") ? key(sel) in this.dataset : sel.split(".").filter(Boolean).every((c) => this.classes.has(c)); }
  closest(sel) { for (let n = this; n; n = n.parentElement) if (n.matches(sel)) return n; return null; }
  querySelector(sel) {
    if (sel === ":scope > .pool-step") return this.children.find((c) => c.classes.has("pool-step")) || null;
    const walk = (n) => { for (const c of n.children) { if (c.matches(sel)) return c; const d = walk(c); if (d) return d; } return null; };
    return walk(this);
  }
  detach() { if (this.parentElement) this.parentElement.children.splice(this.parentElement.children.indexOf(this), 1); this.parentElement = null; }
  appendChild(el) { el.detach(); this.children.push(el); el.parentElement = this; return el; }
  insertBefore(el, ref) { el.detach(); const at = ref ? this.children.indexOf(ref) : -1; this.children.splice(at < 0 ? this.children.length : at, 0, el); el.parentElement = this; return el; }
  get nextSibling() { const s = this.parentElement?.children; return s ? s[s.indexOf(this) + 1] || null : null; }
  get isConnected() { let n = this; while (n.parentElement) n = n.parentElement; return n === page.root; }
  get offsetTop() { if (this === page.list) return 100; const s = this.parentElement.children; return 100 + s.slice(0, s.indexOf(this)).reduce((a, c) => a + c.h, 0); }
  get offsetHeight() { return this.h; }
  getBoundingClientRect() { return { top: this.parentElement === page.list ? this.offsetTop : this === page.list ? 100 : 0 }; }
  getAnimations() { return []; }
  animate(frames, opts) { const a = { frames, opts, id: "", cancel() {}, onfinish: null, oncancel: null }; this.anims.push(a); return a; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  focus() { this.focused += 1; }
}
const page = {};
function build(ids) {
  page.root = new El("lane");
  const section = page.root.appendChild(new El("subscription-pool", { poolId: "work" }));
  page.list = section.appendChild(new El("pool-ladder"));
  page.grips = {};
  for (const id of ids) {
    const rung = page.list.appendChild(new El("pool-rung"));
    const card = rung.appendChild(new El("pool-step", { poolStep: id }));
    card.h = 34;
    page.grips[id] = card.appendChild(new El("pool-grip", { poolGrip: "" }));
  }
  return page;
}
const win = {
  listeners: {}, frames: [], timers: [], innerHeight: 800, scrolled: 0,
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); },
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); },
  requestAnimationFrame(fn) { this.frames.push(fn); return this.frames.length; },
  cancelAnimationFrame() {},
  setTimeout(fn, ms) { this.timers.push({ fn, ms }); return this.timers.length; },
  clearTimeout() {},
  scrollBy(_x, y) { this.scrolled += y; },
  getSelection: () => ({ removeAllRanges() {} }),
};
const run = () => { while (win.frames.length) win.frames.shift()(); };
const tick = () => { const due = win.timers.splice(0); for (const t of due) t.fn(); };
const fire = (type, fields) => { for (const fn of [...(win.listeners[type] || [])]) fn({ pointerId: 1, preventDefault() {}, stopPropagation() {}, ...fields }); };
const doc = { body: new El("body") };
const saved = [];
let answer = () => Promise.resolve();
const order = () => StepCarry.order(page.list);

build(["a", "b", "c"]);
const carry = new StepCarry(page.root, { onSort: (poolId, ids) => { saved.push([poolId, ids]); return answer(); }, win, doc });
const press = (target, y, extra = {}) => page.root.listeners.pointerdown[0]({ target, button: 0, isPrimary: true, pointerId: 1, clientX: 50, clientY: y, preventDefault() {}, ...extra });

// a press anywhere but on a grip carries nothing
press(page.list.children[0].children[0], 120);
assert.equal(carry.phase, "idle", "negative: only the grip carries a step");

// a press on a's grip that stays within a few pixels is a press, not a carry
press(page.grips.a, 120);
assert.equal(carry.phase, "pending");
fire("pointermove", { clientX: 52, clientY: 123 });
assert.equal(carry.phase, "pending", "within 5 px it is still a press");
fire("pointerup", { clientX: 52, clientY: 123 });
assert.deepEqual([carry.phase, saved.length, order()], ["idle", 0, ["a", "b", "c"]], "negative: a plain press moves and saves nothing");

// carried down past b's middle: the empty place moves, b slides up, the card stays under the pointer
press(page.grips.a, 120);
fire("pointermove", { clientX: 50, clientY: 130 });
assert.equal(carry.phase, "carrying");
run();
const rungA = page.list.children[0];
assert.ok(rungA.classes.has("carried") && page.list.classes.has("sorting") && doc.body.classes.has("step-carrying"),
  "the card rises: the seat is marked, the list sorts, the page shows it");
assert.equal(rungA.style.props["--hole-h"], "34px", "the empty place is the size of what was lifted");
assert.equal(carry.busy, true, "a carried step holds the lane");
fire("pointermove", { clientX: 50, clientY: 170 });
run();
assert.deepEqual(order(), ["b", "a", "c"], "past b's middle the place goes after b");
assert.equal(page.list.children[0].anims.length, 1, "b slides into a's old place");
assert.equal(rungA.children[0].style.transform, "translate(0px, 10px)", "the card stays under the pointer though its seat moved 40 px");
fire("pointermove", { clientX: 50, clientY: 175 });
run();
assert.deepEqual(order(), ["b", "a", "c"], "negative: short of c's middle nothing moves again");

// letting go: the card glides home, then the order is saved — and the lane waits for the answer
let settle;
answer = () => new Promise((resolve) => { settle = resolve; });
fire("pointerup", { clientX: 50, clientY: 175 });
assert.equal(carry.phase, "landing");
assert.equal(rungA.children[0].anims.at(-1).opts.duration, StepCarry.GLIDE, "it glides into its place");
tick();
assert.deepEqual(saved, [["work", ["b", "a", "c"]]], "the order it left behind is saved, once, for its pool");
assert.ok(!rungA.classes.has("carried") && !page.list.classes.has("sorting") && !doc.body.classes.has("step-carrying"),
  "landed: the marks come off");
assert.equal(rungA.style.props["--hole-h"], undefined);
assert.equal(carry.phase, "saving");
assert.equal(carry.busy, true, "while the save is out, the lane is not drawn over the new order");
settle(); await Promise.resolve(); await Promise.resolve();
assert.deepEqual([carry.phase, carry.busy], ["idle", false], "the save answered: the lane may draw again");
rungA.children[0].anims.at(-1).onfinish?.();
assert.equal(saved.length, 1, "negative: the glide's own end lands nothing a second time");

// a refused save frees the lane too, and is named in the console
const errors = [];
const keepError = console.error;
console.error = (...args) => errors.push(args.map(String).join(" "));
answer = () => Promise.reject(new Error("refused"));
press(page.grips.c, 200);
fire("pointermove", { clientX: 50, clientY: 110 });
run();
assert.deepEqual(order(), ["c", "b", "a"], "carried to the top");
fire("pointerup", { clientX: 50, clientY: 110 });
tick();
await Promise.resolve().catch(() => {}); await new Promise((r) => setImmediate(r));
assert.deepEqual([saved.at(-1)[1], carry.phase], [["c", "b", "a"], "idle"], "negative: a refusal does not hold the lane forever");
console.error = keepError;
const mine = errors.filter((e) => e.startsWith("step-carry:"));
assert.ok(mine.length === 1 && mine[0].includes("not saved") && mine[0].includes("refused"), `the refusal is named, not swallowed (got ${JSON.stringify(mine)})`);
answer = () => Promise.resolve();

// Esc gives the step back: the order it had when it was lifted, nothing saved
const n = saved.length;
press(page.grips.a, 200);
fire("pointermove", { clientX: 50, clientY: 105 });
run();
assert.deepEqual(order(), ["a", "c", "b"]);
for (const fn of [...win.listeners.keydown]) fn({ key: "Escape", pointerId: undefined, preventDefault() {}, stopPropagation() {} });
assert.deepEqual(order(), ["c", "b", "a"], "Esc: the steps go back to where they were");
tick();
assert.deepEqual([saved.length, carry.phase], [n, "idle"], "negative: a carry given up saves nothing");

// given up, and the steps could not even be put back (a home that failed): still nothing is saved
const keepHome = carry.home;
carry.home = () => {};
press(page.grips.a, 200);
fire("pointermove", { clientX: 50, clientY: 105 });
run();
for (const fn of [...win.listeners.keydown]) fn({ key: "Escape", pointerId: undefined, preventDefault() {}, stopPropagation() {} });
tick();
carry.home = keepHome;
assert.deepEqual([saved.length, carry.phase], [n, "idle"], "negative: a cancelled carry never saves, whatever order it left");

// the lane drawn over a carried step (an answer that came in the middle): nothing lands, nothing is saved
press(page.grips.b, 160);
fire("pointermove", { clientX: 50, clientY: 110 });
run();
page.list.parentElement.detach();
fire("pointerup", { clientX: 50, clientY: 110 });
assert.deepEqual([carry.phase, saved.length], ["idle", n], "negative: a carry whose list is gone lands nothing");

// the keyboard: Alt+↑/↓ on a grip moves the step; one save a moment after the last press
build(["a", "b", "c"]);
const keys = new StepCarry(page.root, { onSort: (poolId, ids) => { saved.push([poolId, ids]); return Promise.resolve(); }, win, doc });
const altKey = (target, k) => page.root.listeners.keydown[0]({ target, key: k, altKey: true, preventDefault() {} });
altKey(page.grips.c, "ArrowUp");
altKey(page.grips.c, "ArrowUp");
assert.deepEqual(order(), ["c", "a", "b"], "two presses, two places up");
assert.equal(keys.busy, true, "the keyboard's moves hold the lane until they are saved");
altKey(page.grips.c, "ArrowUp");
assert.deepEqual(order(), ["c", "a", "b"], "negative: the first step has no place above it");
const m = saved.length;
tick();
assert.deepEqual(saved.slice(m), [["work", ["c", "a", "b"]]], "saved once, after the last press");
await Promise.resolve(); await Promise.resolve();
assert.equal(keys.busy, false);
page.root.listeners.keydown[0]({ target: page.grips.a, key: "ArrowUp", altKey: false, preventDefault() {} });
tick();
assert.equal(saved.length, m + 1, "negative: an arrow without Alt moves nothing");

// one step: nothing to carry it among
build(["solo"]);
const lone = new StepCarry(page.root, { onSort: () => saved.push("lone"), win, doc });
page.root.listeners.pointerdown[0]({ target: page.grips.solo, button: 0, isPrimary: true, pointerId: 1, clientX: 0, clientY: 120, preventDefault() {} });
assert.equal(lone.phase, "idle", "negative: a pool of one step has no order to change");

// Slide: what moved slides from where it was seen; what did not move does not
build(["a", "b"]);
const [ra, rb] = page.list.children;
Slide.run([rb], () => page.list.insertBefore(rb, ra));
assert.deepEqual(rb.anims[0].frames, [{ transform: "translateY(40px)" }, { transform: "none" }], "b slides up from where it was seen");
Slide.run([ra], () => {});
assert.equal(ra.anims.length, 0, "negative: nothing moved, nothing slides");
// ── the kanban's cards (1.3.503): the same carrier, told what a card is made of (`parts`). The column
//    is positioned — its seats' offsets count from it, not from the parent it shares with them — and the
//    board's own box scrolls when the pointer leans on its edge, not the window ──
class Seat extends El {
  get offsetParent() { return this.parentElement; }
  get offsetTop() { const s = this.parentElement.children; return s.slice(0, s.indexOf(this)).reduce((a, c) => a + c.h, 0); }
  getBoundingClientRect() { return { top: 100 + this.offsetTop }; }
  get isConnected() { let n = this; while (n.parentElement) n = n.parentElement; return n === column.root; }
}
const column = {};
function buildColumn(ids) {
  column.root = new El("board");
  column.list = column.root.appendChild(new El("pb-col", { pbList: "pools" }));
  Object.defineProperty(column.list, "offsetTop", { get: () => 7777 });   // where the column stands under the board: not a seat's offset
  column.list.getBoundingClientRect = () => ({ top: 100 });
  column.list.appendChild(new El("pb-col-head")).h = 30;
  column.grips = {};
  for (const id of ids) {
    const seat = column.list.appendChild(new Seat("pb-seat", { pbSeat: id }));
    seat.h = 120;
    const card = seat.appendChild(new El("pb-card"));
    card.h = 110;
    column.grips[id] = card.appendChild(new El("pb-card-grip", { pbCardGrip: "" }));
  }
}
buildColumn(["std", "eco", "fast"]);
const parts = { item: ".pb-seat", list: "[data-pb-list]", grip: "[data-pb-card-grip]", idOf: (seat) => seat.dataset.pbSeat,
  ownerOf: (list) => list.dataset.pbList, card: (seat) => seat.children[0] };
const box = { scrollTop: 0, getBoundingClientRect: () => ({ top: 100, bottom: 600 }) };
const sorted = [], moved = [];
const cards = new StepCarry(column.root, { onSort: (kind, ids) => { sorted.push([kind, ids]); return Promise.resolve(); }, win, doc, parts,
  scroller: () => box, onMove: () => moved.push(1) });
const seats = () => StepCarry.order(column.list, parts);
const once = () => { for (const fn of win.frames.splice(0)) fn(); };
assert.deepEqual([StepCarry.within(column.list, column.list.children[2]), StepCarry.within(page.list, page.list.children[1])], [150, 40],
  "a seat's place in its list: from the list itself when the list is what its offsets count from; else the list's own offset is taken away");
column.root.listeners.pointerdown[0]({ target: column.grips.std, button: 0, isPrimary: true, pointerId: 1, clientX: 50, clientY: 150, preventDefault() {} });
fire("pointermove", { clientX: 50, clientY: 320 });
once();
assert.deepEqual(seats(), ["eco", "std", "fast"], "past eco's middle the card's place goes after it — counted in the column, not by the column's place on the board");
assert.ok(moved.length >= 1 && column.list.children[2].children[0].style.transform.startsWith("translate("), "each step of the carry is told (the kanban draws its cables again), the card travels");
const scrolledBefore = win.scrolled;
fire("pointermove", { clientX: 50, clientY: 590 });
once();
once();
assert.ok(box.scrollTop > 0 && win.scrolled === scrolledBefore, `near the board's bottom edge the board scrolls, not the window (box ${box.scrollTop}, window ${win.scrolled - scrolledBefore})`);
fire("pointerup", { clientX: 50, clientY: 590 });
tick();
await Promise.resolve(); await Promise.resolve();
assert.deepEqual([sorted, cards.phase], [[["pools", ["eco", "fast", "std"]]], "idle"], "the column's kind and its cards' ids are saved, once");
assert.equal(column.list.children[0].classes.has("pb-col-head"), true, "negative: the column's head is no card — it stays first");
console.log("step carry OK: grip only, press vs carry, the empty place by the layout, the card under the pointer, glide and one save, the lane held until the answer, a refusal frees it, Esc gives back, a redrawn lane lands nothing, Alt+arrows with one save, a pool of one, slides from where seen; the kanban's cards in a positioned column, its box scrolled, each step told");
'''


def main():
    node = find_node()
    if not node:
        raise SystemExit("node required")
    probe = ROOT / "scripts" / ".probe_step_carry.tmp.mjs"
    probe.write_text(PROBE)
    try:
        harness = ROOT / "scripts" / "_js_harness.mjs"
        result = subprocess.run([node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');", str(probe)], cwd=ROOT,
                                env={**os.environ, "JS_ROOT": str(ROOT / "static/js"), "JS_STUBS": ""}, capture_output=True, text=True, timeout=30)
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
    finally:
        probe.unlink(missing_ok=True)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
