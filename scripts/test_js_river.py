#!/usr/bin/env python3
"""Snapshot of the brook behind the pages: static/js/river-prefs.js, river.js, river-dock.js and, since 1.3.536, the banks.

What is pinned. The choice a viewer makes is kept in the browser and read back right: off unless
turned on, the brightest level unless another was chosen, and an unknown or refused store reads
as those defaults instead of throwing (a private window must not take the header's switch down).
The switch stands in the header before the tour, or before the language picker where a page has
no tour, and only where a page has a header. Off loads nothing; on loads the brook once; off
again disposes it; a start that lands after the switch went off again is dropped. The dock hangs
from the switch's group: closed until its ▾ opens it, closed again by the ▾, a press elsewhere or
Escape, kept inside the window on a narrow screen, gone without a trace on dispose. The words come
from the shared dictionary, in the stored language, and every word the brook asks for is in it.

The switch and the dock run on the real modules in node with a small fake page: the header's
elements, the page's classes and listeners. The brook itself (WebGL, sound) is not loaded here:
`load` is a stand-in that records what the switch asked of it.

The banks (1.3.536; the owner, 2026-10-13: "the fish and the striders go under the bank, and the
splash looks wrong"): the stream's geometry, the fish and the strider run as themselves, with no
canvas. What is pinned: how far a point must move to stand inside the water's edge; that a trout
pressed at a bank, and a strider shoved at one, never cross it; that a scare sends an animal along
the stream, never across; and the rings of a hand's plop, which come once, in order.

The rocks (1.3.603; the owner, 2026-10-20: "the fish run away but stop against a rock, instead of going
round it as they come up to it"). Round stones put into the stream by hand, and the stream's own rocks.
What is pinned: a trout looks along the way it wants to go as far as it would swim in 0.7 s, and no
further than the place it goes to; a rock in that way is gone round — one ahead along the stream by its
side toward the middle (the owner: "a fish at the bank would go between the bank and the rock and get
stuck"), one across the stream by its end nearer the place; the side once taken is kept; a way along a
rock does not turn back on itself, and close to the stone it leads out; a fish never swims at a stone
faster than it could stop short of it, and comes up to the stone itself only for a place at it (a fly
drifting by); no point of a body enters a rock's margin. Startled trout behind the rocks of 18 streams go
round their rock and never touch one.

The chase and the drop (1.3.546, the first version's behaviour of 1.3.597, and 1.3.599: the owner, 2026-10-19, "again the fish can take the moth very far from the
mouth, and as soon as it appears they swim after it; they used to think longer before they started to swim"). The trout runs as itself in a stream with a fly drifting
on it. What is pinned: that a trout takes a fly only at its mouth (the tip of its snout, where the outline draws the nose: 0.08 of its length, along the whole way the tip went in
a step, never 0.39 away as in the first version), that the chase brings the mouth to a fly that drifts down to it and to one thrown beside it, on a fast frame and on a
slow one; that a fly it has seen is thought over for 0.8 to 1.8 s before it moves (the thinking drawn from a stream of its own, the eyes on the fly, a fly that is gone let go); that a
trout's constructor takes from the brook's stream the numbers the first version's did (so that every seed lays the brook out as it did); that a take leaves a ring and no spray;
that the sound of a landing fly, of a take and of a hand's plop is one voice, a drop, each bigger drop lower and longer; and what that voice is made of: one rising sine and no noise.

Run: python3 scripts/test_js_river.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths, probe_args  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const mod = (name) => import(pathToFileURL(process.env.JS_ROOT + "/" + name).href);
const { RiverPrefs, RIVER_LEVELS, RIVER_KEYS } = await mod("river-prefs.js");
const { RiverSwitch } = await mod("river.js");
const { RiverDock } = await mod("river-dock.js");
const dict = await mod("i18n-data.js");
const { readFileSync, readdirSync } = await import("node:fs");
const core = await mod("river-core.js");
const worldMod = await mod("river-world.js");
const fishMod = await mod("river-fish.js");
const lifeMod = await mod("river-life.js");
const soundMod = await mod("river-sound.js");
/** A stream seen from above, the same everywhere: left to right when wide, down the screen when tall. */
const channelOf = (w = 1000, h = 600) => new worldMod.Channel(w, h, new core.Rng(5), new core.Noise(new core.Rng(41)));
const shoreOf = (ch, x, y) => ch.shore(ch.sOf(x, y), ch.nOf(x, y));
/** The three points of a fish the banks are kept from: the snout, the middle of the spine, the tail. */
const bodyOf = (f) => [0, Math.floor(f.spine.length / 2), f.spine.length - 1].map((i) => f.spine[i]);
/** A trout at rest at the middle of the stream, 100 px long and facing east: where the numbers of the mouth are easy to read. */
const troutAt = (ch) => { const at = ch.xy(500, ch.centre(500)), f = new fishMod.Trout(new core.Rng(3), at, 100); f.heading = 0; f.goal = 0; f.buildSpine(); return { at, f }; };
/** A kit that writes down every sound asked of it, by the name of the call and the options it got. */
const kitOf = (calls) => new Proxy({}, { get: (_, name) => (t, opts) => calls.push([name, opts]) });
/** A stand-in for an AudioContext that writes down the nodes a sound makes and what was asked of each. */
class FakeParam {
  constructor() { this.value = 0; this.calls = []; }
  setValueAtTime(v, t) { this.calls.push(["set", v, t]); }
  exponentialRampToValueAtTime(v, t) { this.calls.push(["ramp", v, t]); }
  setTargetAtTime(v, t, k) { this.calls.push(["target", v, t, k]); }
  cancelScheduledValues(t) { this.calls.push(["cancel", t]); }
}
class FakeNode {
  constructor(kind, log) { this.kind = kind; this.gain = new FakeParam(); this.frequency = new FakeParam(); this.pan = new FakeParam(); this.calls = []; log.push(this); }
  connect(to) { return to; }
  start(...a) { this.calls.push(["start", ...a]); }
  stop(...a) { this.calls.push(["stop", ...a]); }
}
const fakeAudio = () => {
  const log = [], make = (kind) => () => new FakeNode(kind, log);
  return { sampleRate: 8000, currentTime: 0, log, createGain: make("gain"), createOscillator: make("osc"), createStereoPanner: make("pan"),
    createBiquadFilter: make("filter"), createBufferSource: make("buffer"), createConvolver: make("convolver"),
    createBuffer: (n, len) => ({ getChannelData: () => new Float32Array(len) }) };
};
/**
 * A trout chasing a fly that drifts with the water, run as itself: how far from the tip of its snout the fly was when it was taken, in
 * body lengths, when (seconds from the start) and how long the trout thought the fly over before it moved, or null when the chase ended with
 * no take. A natural fly comes down the stream to a trout holding its lie; any other is thrown anywhere ahead of it or beside it, as a click
 * on the water does.
 */
const chaseOf = (ch, seed, dt, natural) => {
  const rng = new core.Rng(seed), at = ch.xy(600, ch.centre(600)), len = ch.C * 0.12;
  const f = new fishMod.Trout(rng, at, len); f.heading = f.goal = Math.atan2(-ch.axis.y, -ch.axis.x); f.buildSpine();
  let fly = null;
  if (natural) {
    fly = { x: f.x - ch.axis.x * len * 3.5 + rng.range(-1, 1) * len * 0.4, y: f.y - ch.axis.y * len * 3.5 + rng.range(-1, 1) * len * 0.4, vx: 0, vy: 0, alive: true, claimedBy: null };
  } else {
    for (let i = 0; i < 100 && !fly; i++) {
      const a = f.heading + rng.range(-1.2, 1.2), d = len * rng.range(1.5, 6), x = f.x + Math.cos(a) * d, y = f.y + Math.sin(a) * d;
      if (ch.isWater(x, y, 0.2)) fly = { x, y, vx: 0, vy: 0, alive: true, claimedBy: null };
    }
  }
  let took = null, seen = null, thought = null;
  const flies = [fly];
  const life = { time: 0, noise: new core.Noise(new core.Rng(seed + 1)), channel: ch,
    flyFor: (fish) => lifeMod.BrookLife.prototype.flyFor.call({ flies }, fish),
    rise: (fish, g) => { const m = fish.mouth(); g.alive = false; took = { near: Math.hypot(g.x - m.x, g.y - m.y) / fish.len, at: life.time, thought }; },
    freeLie: () => null, shelterNear: () => at };
  for (let t = 0; t < 14 && took === null; t += dt) {
    const w = ch.sample(fly.x, fly.y), k = Math.min(1, 2 * dt);
    fly.vx += (w.vx - fly.vx) * k; fly.vy += (w.vy - fly.vy) * k;
    fly.x += fly.vx * dt; fly.y += fly.vy * dt; life.time = t;
    const before = f.state;
    f.update(dt, life);
    if (before !== "notice" && f.state === "notice") seen = t;
    if (before === "notice" && f.state === "chase") thought = t - seen;
    if (f.state === "back" && took === null && t > 0.2) break;
  }
  return took;
};
/**
 * A trout holding its lie and a fly that drifts down to it, run as themselves: every change of the trout's state with its time (seconds since the fly came) and whether the
 * fly was its own by then, how far from where it was it strayed while it thought, and when it took the fly. The trout has held its lie for three seconds when the fly comes.
 * `drop` lets the fly go: it dies, or another fish claims it, at a time.
 */
const thinkOf = (ch, seed, dt = 1 / 60, drop = null) => {
  const rng = new core.Rng(seed), at = ch.xy(600, ch.centre(600)), len = ch.C * 0.12, t0 = 3;
  const f = new fishMod.Trout(rng, at, len); f.heading = f.goal = Math.atan2(-ch.axis.y, -ch.axis.x); f.buildSpine();
  const other = { name: "another trout" }, flies = [], rose = [], log = [];
  const life = { time: 0, noise: new core.Noise(new core.Rng(seed + 1)), channel: ch,
    flyFor: (fish) => lifeMod.BrookLife.prototype.flyFor.call({ flies }, fish),
    rise: (fish, g) => { g.alive = false; rose.push(+(life.time - t0).toFixed(3)); }, freeLie: () => null, shelterNear: () => at };
  for (let t = 0; t < t0; t += dt) { life.time = t; f.update(dt, life); }
  const fly = { x: f.x - ch.axis.x * len * 3.5, y: f.y - ch.axis.y * len * 3.5, vx: 0, vy: 0, alive: true, claimedBy: null };
  flies.push(fly);
  const start = { x: f.x, y: f.y };
  let away = 0;
  for (let t = t0; t < t0 + 8; t += dt) {
    const w = ch.sample(fly.x, fly.y), k = Math.min(1, 2 * dt);
    fly.vx += (w.vx - fly.vx) * k; fly.vy += (w.vy - fly.vy) * k; fly.x += fly.vx * dt; fly.y += fly.vy * dt; life.time = t;
    if (drop && t - t0 >= drop.at) { if (drop.kind === "dies") fly.alive = false; else fly.claimedBy = other; }
    const before = f.state;
    f.update(dt, life);
    if (f.state !== before) log.push([before, f.state, +(t - t0).toFixed(3), fly.claimedBy === f]);
    if (f.state === "notice") away = Math.max(away, Math.hypot(f.x - start.x, f.y - start.y) / len);
  }
  return { log, rose, fly, other, away };
};
/** A round stone of radius r at (x, y), standing out of the water: a rock with no wobble, where the numbers of a way past it are easy to read. */
const stoneAt = (x, y, r) => ({ x, y, r, height: 1, emerges: true, radiusAt: () => r, inside(px, py, m = 0) { return r + m - Math.hypot(px - x, py - y); } });
/** The fish's rock handling taken away, for the negatives: no look ahead (the want as it is) and no brakes (stopping takes no time). */
const blind = () => { fishMod.Trout.prototype.steer = (want) => want; Object.getPrototypeOf(fishMod.Trout).STOP = 1e-9; };
/** A trout 100 px long at (x, y), facing along `heading`, and the way it steers `want` to: the turn from the want in whole degrees, and the steered want. */
const steerAt = (ch, x, y, want, heading = 0, f = null) => {
  f = f || new fishMod.Trout(new core.Rng(3), { x, y }, 100); f.x = x; f.y = y; f.heading = f.goal = heading;
  const out = f.steer(want, ch, 600), turn = Math.round(core.M.wrap(Math.atan2(out.y, out.x) - Math.atan2(want.y, want.x)) * 180 / Math.PI);
  return { f, out, turn, across: Math.sign(Math.round(ch.acrossOf(out))) };
};
/**
 * Trout at the lies behind the rocks that stand out of the water, 2.5 radii below each (as BrookLife lays them out), in streams of three sizes:
 * each holds its lie for a second, is scared from 1.2 of its lengths below and flees for its 0.9 s. What the flights did: how many trout; how
 * many brought the snout within ROCK_TOUCH of a rock (pressed) and in how many frames; how many had a point of the spine inside a rock; and
 * of those whose snout got level with their rock's centre within two seconds, how many on the rock's side toward the middle of the stream
 * (a rock on the middle line counted apart).
 */
const fleeOf = (seeds) => {
  const out = { trout: 0, pressed: 0, pressedFrames: 0, bodyIn: 0, level: 0, middleSide: 0, middleLine: 0 };
  for (const [w, h] of [[1440, 900], [1000, 600], [1920, 1080]]) for (const seed of seeds) {
    const ch = new worldMod.Channel(w, h, new core.Rng(seed), new core.Noise(new core.Rng(seed + 40))), C = ch.C;
    for (const r of ch.rocks) {
      if (!r.emerges) continue;
      const lie = { x: r.x + ch.axis.x * r.r * 2.5, y: r.y + ch.axis.y * r.r * 2.5 };
      if (!(lie.x > C * 0.04 && lie.y > C * 0.04 && lie.x < w - C * 0.04 && lie.y < h - C * 0.04)) continue;
      if (ch.sample(lie.x, lie.y).depth <= 0.35 || ch.rockAt(lie.x, lie.y, r.r * 0.4)) continue;
      const len = C * 0.125, f = new fishMod.Trout(new core.Rng(seed * 7 + out.trout), lie, len);
      f.heading = f.goal = Math.atan2(-ch.axis.y, -ch.axis.x); f.buildSpine();
      const life = { time: 0, noise: new core.Noise(new core.Rng(seed + 1)), channel: ch, flyFor: () => null, freeLie: () => null, rise: () => {},
        shelterNear: (fish) => lifeMod.BrookLife.prototype.shelterNear.call({ channel: ch }, fish) };
      f.state = "hold"; f.stateTime = 0;
      for (let i = 0; i < 60; i++) { life.time += 1 / 60; f.update(1 / 60, life); }
      f.spook(f.x + ch.axis.x * len * 1.2, f.y + ch.axis.y * len * 1.2, ch);
      out.trout++;
      let pressed = 0, inside = false, side = null;
      for (let i = 0; i < 120; i++) {
        life.time += 1 / 60; f.update(1 / 60, life);
        if (side === null && ch.sOf(f.x, f.y) < ch.sOf(r.x, r.y)) side = ch.middleSide(r.x, r.y, r.r * 0.25) * Math.sign(ch.nOf(f.x, f.y) - ch.nOf(r.x, r.y));
        if (i >= 54) continue;
        if (ch.rocks.some((q) => q.inside(f.x, f.y, f.len * fishMod.Trout.ROCK_TOUCH + 0.5) > 0)) pressed++;
        if (f.spine.some((p) => ch.rocks.some((q) => q.inside(p.x, p.y) > 0))) inside = true;
      }
      if (pressed) { out.pressed++; out.pressedFrames += pressed; }
      if (inside) out.bodyIn++;
      if (side !== null) { out.level++; if (side === 1) out.middleSide++; if (side === 0) out.middleLine++; }
    }
  }
  return out;
};

/** A store like localStorage; `refuse` makes every call throw, as a private window can. */
const store = (seed = {}, refuse = false) => {
  const m = new Map(Object.entries(seed));
  const no = () => { throw new Error("SecurityError"); };
  return { m, getItem: refuse ? no : (k) => (m.has(k) ? m.get(k) : null), setItem: refuse ? no : (k, v) => m.set(k, String(v)) };
};
const prefsOf = (p) => ({ on: p.on, level: p.level.id, paused: p.paused });

/** Listeners by type, as on an element, the page or its window; fire() calls them. */
class Ears {
  constructor() { this.listeners = {}; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn); }
  fire(type, ev) { for (const fn of this.listeners[type] || []) fn(ev); }
}
/** The few elements of a page's header the switch and the dock touch. */
class FakeEl extends Ears {
  static focused = null;
  constructor(tag, { id = "", tour = false } = {}) {
    super();
    this.tagName = tag.toUpperCase(); this.id = id; this.children = []; this.parentElement = null;
    this.dataset = tour ? { obTour: "" } : {}; this.attrs = {}; this.style = {}; this.hidden = false;
    this.className = ""; this.textContent = ""; this.title = ""; this.type = "";
    this.rect = { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  append(...els) { for (const e of els) { e.parentElement = this; this.children.push(e); } }
  insertBefore(el, ref) { el.parentElement = this; const i = ref ? this.children.indexOf(ref) : -1; if (i < 0) this.children.push(el); else this.children.splice(i, 0, el); }
  remove() { const p = this.parentElement; if (p) { p.children.splice(p.children.indexOf(this), 1); this.parentElement = null; } }
  contains(node) { for (let n = node; n; n = n.parentElement) if (n === this) return true; return false; }
  getBoundingClientRect() { return this.rect; }
  focus() { FakeEl.focused = this; }
  click() { this.fire("click", {}); }
  querySelector(sel) {
    const hit = (e) => (sel === "[data-ob-tour]" ? "obTour" in e.dataset : sel === "#langSelect" ? e.id === "langSelect" : false);
    return this.children.find(hit) || null;
  }
}
class FakePage extends Ears {
  constructor({ header = true, tour = true } = {}) {
    super();
    this.header = header;
    this.actions = new FakeEl("div");
    this.actions.append(new FakeEl("div", { id: "userChip" }));
    if (tour) this.actions.append(new FakeEl("button", { tour: true }));
    this.actions.append(new FakeEl("div", { id: "langSelect" }));
    this.classes = new Set();
    this.documentElement = { classList: { add: (c) => this.classes.add(c), remove: (c) => this.classes.delete(c) } };
    this.defaultView = new Ears();
  }
  querySelector(sel) { return this.header && sel === ".topbar .actions" ? this.actions : null; }
  createElement(tag) { return new FakeEl(tag); }
}
const page = (opts) => new FakePage(opts);
const order = (doc) => doc.actions.children.map((e) => e.dataset.t || e.id || (("obTour" in e.dataset) ? "tour" : e.className || "?"));
/** A dock in a fresh header group; `word` names a key in angle brackets, so a wrong key shows. */
const dockIn = (d = page()) => { const host = new FakeEl("span"); return { d, host, k: new RiverDock(d, host, (w) => `<${w}>`) }; };

/** A stand-in for river-background.js: records what the switch made and let go. */
const brook = () => {
  const log = { made: 0, disposed: 0, relabeled: 0, words: [] };
  let release;
  const gate = new Promise((r) => { release = r; });
  const RiverBackground = class {
    constructor(doc, prefs, word, host) { log.made++; log.words.push(word("riverToggle")); log.host = host ? host.className : null; }
    dispose() { log.disposed++; }
    relabel() { log.relabeled++; }
  };
  return { log, load: () => { log.loads = (log.loads || 0) + 1; return log.held ? gate.then(() => ({ RiverBackground })) : Promise.resolve({ RiverBackground }); },
           release: () => release() };
};
// setImmediate, not setTimeout: the harness unrefs timers, and a pending one would not hold node open
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };
const out = {};
"""

PINS = [
    # ── what the browser keeps ──
    ("prefs_defaults", "",
     "prefsOf(new RiverPrefs(store()))",
     {"on": False, "level": "bright", "paused": False},
     "nothing kept yet: the brook is off, at its brightest, not paused (the owner's defaults, 2026-10-13)"),
    ("prefs_round_trip", "",
     "(() => { const s = store(), p = new RiverPrefs(s); p.on = true; p.level = RIVER_LEVELS[2]; p.paused = true;"
     " return { kept: Object.fromEntries(s.m), read: prefsOf(new RiverPrefs(s)) }; })()",
     {"kept": {"riverOn": "1", "riverLevel": "dim", "riverPaused": "1"}, "read": {"on": True, "level": "dim", "paused": True}},
     "a choice is written under its key and read back the same on the next page"),
    ("prefs_unknown_words", "",
     "prefsOf(new RiverPrefs(store({ riverOn: \"yes\", riverLevel: \"neon\", riverPaused: \"true\" })))",
     {"on": False, "level": "bright", "paused": False},
     "boundary: anything but the written words reads as the default, never as a guess"),
    ("prefs_refused_store", "",
     "(() => { const p = new RiverPrefs(store({}, true)); p.on = true; p.level = RIVER_LEVELS[1]; return prefsOf(p); })()",
     {"on": False, "level": "bright", "paused": False},
     "negative: a store that throws (private window) reads the defaults and drops the writes without throwing"),
    ("prefs_no_store", "",
     "prefsOf(new RiverPrefs(null))",
     {"on": False, "level": "bright", "paused": False},
     "negative: no store at all is the same as an empty one"),
    ("prefs_open_refused",
     "Object.defineProperty(globalThis, \"localStorage\", { get() { throw new Error(\"SecurityError\"); }, configurable: true });",
     "(() => { const p = RiverPrefs.open(); return { store: p.storage, ...prefsOf(p) }; })()",
     {"store": None, "on": False, "level": "bright", "paused": False},
     "negative: a browser that refuses even to hand out localStorage still gets a switch, with no memory"),
    ("prefs_levels_named", "",
     "[RIVER_LEVELS.map((l) => [l.id, l.key, l.shade]), RIVER_KEYS]",
     [[["bright", "riverLevelBright", 0.12], ["soft", "riverLevelSoft", 0.34], ["dim", "riverLevelDim", 0.56]],
      {"on": "riverOn", "level": "riverLevel", "paused": "riverPaused"}],
     "the levels, brightest first (it is the default), each with its word and its shade"),
    # ── where the switch stands ──
    ("switch_before_tour", "",
     "(() => { const d = page(), b = brook(); const s = new RiverSwitch(d, new RiverPrefs(store()), { load: b.load, words: async () => dict });"
     " const ok = s.mount(); const btn = s.button; return { ok, order: order(d), group: s.group.children.map((c) => c.dataset.t),"
     " t: btn.dataset.t, state: btn.dataset.tState, pressed: btn.getAttribute(\"aria-pressed\"), type: btn.type, i18n: s.label.dataset.i18n }; })()",
     {"ok": True, "order": ["userChip", "river-switch", "tour", "langSelect"], "group": ["header-river-toggle"], "t": "header-river-toggle",
      "state": "off", "pressed": "false", "type": "button", "i18n": "riverToggle"},
     "the switch stands in the header between the account and the tour, in a group of its own, off, with its test name"),
    ("switch_before_language", "",
     "(() => { const d = page({ tour: false }); new RiverSwitch(d, new RiverPrefs(store()), { load: brook().load }).mount(); return order(d); })()",
     ["userChip", "river-switch", "langSelect"],
     "a page with no tour (/models, /system): the switch stands before the language picker"),
    ("switch_no_header", "",
     "(() => { const b = brook(); const s = new RiverSwitch(page({ header: false }), new RiverPrefs(store({ riverOn: \"1\" })), { load: b.load });"
     " return { ok: s.mount(), loads: b.log.loads || 0, button: s.button }; })()",
     {"ok": False, "loads": 0, "button": None},
     "negative: a page without a header gets no switch and no brook, even when the brook was left on"),
    # ── on and off ──
    ("switch_off_loads_nothing", "",
     "await (async () => { const d = page(), b = brook(); new RiverSwitch(d, new RiverPrefs(store()), { load: b.load }).mount(); await settle();"
     " return { loads: b.log.loads || 0, made: b.log.made, classes: [...d.classes] }; })()",
     {"loads": 0, "made": 0, "classes": []},
     "off by default means off: the brook's code is not even fetched and the page keeps its look"),
    ("switch_left_on_starts", "",
     "await (async () => { const d = page(), b = brook(); const s = new RiverSwitch(d, new RiverPrefs(store({ riverOn: \"1\" })), { load: b.load });"
     " s.mount(); await settle(); return { loads: b.log.loads, made: b.log.made, classes: [...d.classes], state: s.button.dataset.tState,"
     " pressed: s.button.getAttribute(\"aria-pressed\"), host: b.log.host }; })()",
     {"loads": 1, "made": 1, "classes": ["river-on"], "state": "on", "pressed": "true", "host": "river-switch"},
     "left on in this browser: the next page starts the brook once, by itself, and hands it the switch's group for its dock"),
    ("switch_click_on_then_off", "",
     "await (async () => { const d = page(), b = brook(), s0 = store(); const s = new RiverSwitch(d, new RiverPrefs(s0), { load: b.load });"
     " s.mount(); s.button.click(); await settle(); const on = { made: b.log.made, kept: s0.m.get(\"riverOn\"), classes: [...d.classes] };"
     " s.button.click(); await settle(); return { on, off: { disposed: b.log.disposed, kept: s0.m.get(\"riverOn\"), classes: [...d.classes],"
     " state: s.button.dataset.tState } }; })()",
     {"on": {"made": 1, "kept": "1", "classes": ["river-on"]},
      "off": {"disposed": 1, "kept": "0", "classes": [], "state": "off"}},
     "a click turns it on and remembers it; the next click takes the brook down and remembers that too"),
    ("switch_late_start_dropped", "",
     "await (async () => { const d = page(), b = brook(); b.log.held = true; const s = new RiverSwitch(d, new RiverPrefs(store()), { load: b.load });"
     " s.mount(); s.button.click(); s.button.click(); b.release(); await settle();"
     " return { made: b.log.made, background: s.background, classes: [...d.classes] }; })()",
     {"made": 0, "background": None, "classes": []},
     "defect guard: on and off again before the brook's code arrives — the late start is dropped, no brook left running unseen"),
    # ── the dock under the switch ──
    ("dock_starts_closed", "",
     "(() => { const { host, k } = dockIn(); return { host: host.children.map((c) => c.dataset.t), hidden: k.panel.hidden,"
     " expanded: k.button.getAttribute(\"aria-expanded\"), state: k.button.dataset.tState, controls: k.button.getAttribute(\"aria-controls\"),"
     " id: k.panel.id, role: k.panel.getAttribute(\"role\"), type: k.button.type }; })()",
     {"host": ["header-river-settings", "river-dock"], "hidden": True, "expanded": "false", "state": "closed",
      "controls": "riverDock", "id": "riverDock", "role": "group", "type": "button"},
     "the dock hangs in the switch's group right after its ▾ (Tab goes from the ▾ into it), closed until asked"),
    ("dock_button_toggles", "",
     "(() => { const { k } = dockIn(); k.button.click(); const opened = { hidden: k.panel.hidden, expanded: k.button.getAttribute(\"aria-expanded\"),"
     " state: k.button.dataset.tState }; k.button.click(); return { opened, closed: { hidden: k.panel.hidden, state: k.button.dataset.tState } }; })()",
     {"opened": {"hidden": False, "expanded": "true", "state": "open"}, "closed": {"hidden": True, "state": "closed"}},
     "the ▾ opens the dock and a second press on it closes it, and says which in aria-expanded and data-t-state"),
    ("dock_press_elsewhere_closes", "",
     "(() => { const { k } = dockIn(); const inside = new FakeEl(\"button\"); k.panel.append(inside); k.show();"
     " k.pressed(inside); const afterInside = k.open; k.pressed(k.button); const afterButton = k.open;"
     " k.pressed(new FakeEl(\"div\")); return { afterInside, afterButton, afterElsewhere: k.open }; })()",
     {"afterInside": True, "afterButton": True, "afterElsewhere": False},
     "a press in the dock or on its ▾ keeps it open (the ▾'s own click decides); a press anywhere else closes it"),
    ("dock_escape", "",
     "(() => { const { d, k } = dockIn(); k.show(); d.fire(\"keydown\", { key: \"Enter\" }); const afterEnter = k.open;"
     " d.fire(\"keydown\", { key: \"Escape\" }); return { afterEnter, afterEscape: k.open, focus: FakeEl.focused === k.button }; })()",
     {"afterEnter": True, "afterEscape": False, "focus": True},
     "Escape closes the dock and puts focus back on its ▾; another key leaves it open"),
    ("dock_stays_in_window", "",
     "(() => { const { d, k } = dockIn(); k.panel.rect = { left: -55 }; k.show(); const narrow = k.panel.style.right;"
     " k.panel.rect = { left: 600 }; d.defaultView.fire(\"resize\", {}); const wide = k.panel.style.right;"
     " k.close(); k.panel.rect = { left: -20 }; d.defaultView.fire(\"resize\", {}); return { narrow, wide, closed: k.panel.style.right }; })()",
     {"narrow": "-63px", "wide": "0px", "closed": "0px"},
     "boundary: on a narrow screen the dock moves right until its left edge is 8 px inside the window; on a wide one it stays "
     "level with the ▾; a closed dock is not moved"),
    ("dock_words", "",
     "(() => { const { k } = dockIn(); k.relabel(); return { name: k.button.getAttribute(\"aria-label\"), title: k.button.title,"
     " group: k.panel.getAttribute(\"aria-label\") }; })()",
     {"name": "<riverSettings>", "title": "<riverSettings>", "group": "<riverDockLabel>"},
     "the ▾ is named by its word, since its face is only an arrow, and the dock by its own"),
    ("dock_dispose", "",
     "(() => { const { d, host, k } = dockIn(); k.show(); k.dispose(); return { host: host.children.length,"
     " keys: (d.listeners.keydown || []).length, resize: (d.defaultView.listeners.resize || []).length }; })()",
     {"host": 0, "keys": 0, "resize": 0},
     "dispose takes the ▾, the dock and both listeners away: a brook turned off leaves nothing in the header"),
    # ── the banks: nothing alive crosses them, and a scare goes along the stream ──
    ("channel_inward", "",
     "(() => { const ch = channelOf(); const s = 500, c = ch.centre(s), hw = ch.halfWidth(s);"
     " const mid = ch.xy(s, c), top = ch.xy(s, c - hw * 1.3), bottom = ch.xy(s, c + hw * 1.3), near = ch.xy(s, c - hw * 0.97);"
     " const settle = (p, m) => { const q = ch.across(ch.inward(p.x, p.y, m)); return shoreOf(ch, p.x + q.x, p.y + q.y) >= m - 1e-6; };"
     " return [ch.inward(mid.x, mid.y, 20), Math.sign(ch.inward(top.x, top.y, 20)), Math.sign(ch.inward(bottom.x, bottom.y, 20)),"
     " settle(top, 20), settle(bottom, 20), settle(near, 30), ch.across(5), channelOf(600, 1000).across(5)]; })()",
     [0, 1, -1, True, True, True, {"x": 0, "y": 5}, {"x": 5, "y": 0}],
     "a point in the middle needs no move; one past the top bank is told to move down toward the middle, one past the bottom bank up, and "
     "after the move it stands the margin inside the edge; a move across the stream is vertical where the stream runs left to right "
     "and horizontal where it runs down the screen"),
    ("channel_away", "",
     "(() => { const land = channelOf(), port = channelOf(600, 1000); const a = land.xy(500, land.centre(500)), b = port.xy(500, port.centre(500));"
     " const dir = (v) => [v.x === 0 ? 0 : v.x, v.y === 0 ? 0 : v.y];"
     " return [dir(land.away(a.x, a.y, a.x - 100, a.y)), dir(land.away(a.x, a.y, a.x + 100, a.y)), dir(land.away(a.x, a.y, a.x, a.y - 80)), dir(land.away(a.x, a.y, a.x, a.y + 80)),"
     " dir(land.away(a.x, a.y, a.x + 5, a.y, 10)), dir(land.away(a.x, a.y, a.x + 5, a.y, 0)), dir(port.away(b.x, b.y, b.x, b.y - 100)), dir(port.away(b.x, b.y, b.x, b.y + 100))]; })()",
     [[1, 0], [-1, 0], [1, 0], [1, 0], [1, 0], [-1, 0], [0, 1], [0, -1]],
     "a scare sends an animal along the stream, away from the danger: the danger upstream — downstream, the danger downstream — up; "
     "from straight above or below, with nothing to tell the ways apart, downstream; within `level` of it the same, past `level` away from it; "
     "where the stream runs down the screen the same on the other axis"),
    ("trout_stays_in_the_banks",
     "",
     "(() => { const ch = channelOf(); const s0 = 500, c = ch.centre(s0), hw = ch.halfWidth(s0);"
     " const press = (sign) => { const f = new fishMod.Trout(new core.Rng(3), ch.xy(s0, c + sign * hw * 0.6), 60); let body = Infinity, snout = Infinity;"
     " for (let i = 0; i < 480; i++) { f.swim(1 / 60, ch, { x: 0, y: sign * 600 }, 6 * f.len, 4.5, 6);"
     " const at = bodyOf(f).map((p) => shoreOf(ch, p.x, p.y)); body = Math.min(body, ...at); snout = Math.min(snout, at[0]); }"
     " return [body >= 0, snout >= f.len * fishMod.Trout.BANK_ROOM - 1e-6]; };"
     " return [press(-1), press(1), fishMod.Trout.BANK_ROOM]; })()",
     [[True, True], [True, True], 0.2],
     "a trout pressed against a bank for eight seconds — fast, with its whole will across the stream — never has snout, middle or tail past "
     "the water's edge, and its snout stays the margin inside it: the bank is drawn over the edge, and a fish past it swims under the moss "
     "(the owner, 2026-10-13); either bank"),
    ("trout_turned_from_a_bank_keeps_its_tail_in", "",
     "(() => { const ch = channelOf(); const s0 = 500, c = ch.centre(s0), hw = ch.halfWidth(s0); let n = c - hw; for (let i = 0; i < 5; i++) n += 25 - ch.shore(s0, n);"
     " const at = ch.xy(s0, n), f = new fishMod.Trout(new core.Rng(3), at, 60); f.heading = Math.PI / 2; f.goal = Math.PI / 2;"
     " const before = shoreOf(ch, f.x - Math.cos(f.heading) * f.len, f.y - Math.sin(f.heading) * f.len);"
     " f.swim(1 / 60, ch, { x: 0, y: 0 }, 2 * f.len, 1.3, 2);"
     " const tail = shoreOf(ch, f.x - Math.cos(f.heading) * f.len, f.y - Math.sin(f.heading) * f.len);"
     " return [Math.round(shoreOf(ch, at.x, at.y)), before < 0, tail >= f.len * fishMod.Trout.BANK_ROOM - 1e-6]; })()",
     [25, True, True],
     "a trout whose snout is 25 px inside the bank and whose body points away from it, so its tail would lie across the edge, is moved in until "
     "its tail stands the margin inside it: the snout alone is not the fish"),
    ("spook_goes_along_the_stream", "",
     "(() => { const ch = channelOf(); const me = ch.xy(500, ch.centre(500)); const dir = (v) => [v.x === 0 ? 0 : v.x, v.y === 0 ? 0 : v.y];"
     " const dart = (dx, dy) => { const f = new fishMod.Trout(new core.Rng(3), me, 60); f.spook(me.x + dx, me.y + dy, ch); return [f.state, ...dir(f.away)]; };"
     " const shoal = new fishMod.MinnowShoal(null, me, 6, 20, new core.Rng(2)); shoal.spook(me.x - 50, me.y - 10, 400, ch);"
     " const darted = shoal.fish.filter((m) => m.dart > 0);"
     " return [dart(-120, 0), dart(120, 0), dart(0, -80), dart(0, 80), darted.length > 0,"
     " darted.every((m) => m.escape.y === 0 && Math.abs(m.escape.x) === 1), darted.every((m) => Math.sign(m.escape.x) === (m.x >= me.x - 50 ? 1 : -1))]; })()",
     [["flee", 1, 0], ["flee", -1, 0], ["flee", 1, 0], ["flee", 1, 0], True, True, True],
     "a trout scared by a hand darts along the stream — downstream from a hand upstream of it, up from one downstream, downstream from one level "
     "with it — and never across it; so do the minnows the hand scatters, each away from the hand along the stream (the owner, 2026-10-13: "
     "\"they may flee only up and down the stream\")"),
    # ── the rocks: a fish goes round them as it comes up to them, and never runs into one (1.3.603) ──
    ("middle_side_of_the_stream", "",
     "(() => { const land = channelOf(), port = channelOf(600, 1000);"
     " const side = (ch, dn, level) => { const p = ch.xy(500, ch.centre(500) + dn); return ch.middleSide(p.x, p.y, level); };"
     " return { land: [side(land, -100), side(land, 100), side(land, 6, 10), side(land, 6)], port: [side(port, -100), side(port, 100), side(port, -6, 10)],"
     " across: [land.acrossOf({ x: 3, y: -7 }), port.acrossOf({ x: 3, y: -7 })] }; })()",
     {"land": [1, -1, 0, -1], "port": [1, -1, 0], "across": [-7, 3]},
     "which way across the stream its middle lies from a point: from above the middle line, down toward it (1), from below it, up (-1); within "
     "`level` of the line, neither (0) — a rock there is passed on the side the fish is on; where the stream runs down the screen the same on "
     "the other axis; how much of a screen vector goes across the stream"),
    ("a_trout_looks_as_far_ahead_as_it_swims", "",
     "(() => { const ch = channelOf(), s = 300, p = ch.xy(s, ch.centre(s));"
     " const put = (dx, dn) => { const c = ch.xy(s + dx, ch.centre(s) + dn); ch.rocks = [stoneAt(c.x, c.y, 40)]; };"
     " put(300, 0); const fast = steerAt(ch, p.x, p.y, { x: 500, y: 0 }), slow = steerAt(ch, p.x, p.y, { x: 100, y: 0 });"
     " put(300, 150); const beside = steerAt(ch, p.x, p.y, { x: 500, y: 0 }); put(-300, 0); const behind = steerAt(ch, p.x, p.y, { x: 500, y: 0 });"
     " return { fast: Math.abs(fast.turn), slow: slow.turn, beside: beside.turn, behind: behind.turn, kept: Math.round(Math.hypot(fast.out.x, fast.out.y)),"
     " look: [fishMod.Trout.LOOK, fishMod.Trout.LOOK_LEAST, fishMod.Trout.ROCK_ROOM, fishMod.Trout.TURN_LEAD] }; })()",
     {"fast": 20, "slow": 0, "beside": 0, "behind": 0, "kept": 500, "look": [0.7, 0.5, 0.25, 0.08]},
     "a trout looks along the way it wants to go as far as it would swim in 0.7 s: a stone of radius 0.4 three lengths ahead turns a trout that "
     "wants 5 lengths a second by 20 degrees, onto the line that passes the stone with room (a quarter of its length, and 0.08 s of its way to "
     "turn in), and does not turn one that wants 1 length a second (it sees 0.7 of its length ahead, the stone is not near yet); negative: a "
     "stone 1.5 lengths beside the way, or behind the trout, turns nothing; how much it wants is kept"),
    ("round_a_rock_on_its_middle_side", "",
     "(() => { const go = (ch, edge) => { const s = 300, hw = ch.halfWidth(s), n = ch.centre(s + 250) + edge * hw * 0.5, c = ch.xy(s + 250, n);"
     " ch.rocks = [stoneAt(c.x, c.y, 40)]; const p = ch.xy(s, n + edge * 20), w = ch.xy(300, 0), r = steerAt(ch, p.x, p.y, w, Math.atan2(w.y, w.x));"
     " return [r.across, Math.sign(ch.acrossOf({ x: p.x - c.x, y: p.y - c.y }))]; };"
     " const land = channelOf(), port = channelOf(600, 1000); const a = go(land, -1), b = go(land, 1), c = go(port, -1), d = go(port, 1);"
     " return { goes: [a[0], b[0], c[0], d[0]], nearerSideWouldBe: [a[1], b[1], c[1], d[1]] }; })()",
     {"goes": [1, -1, 1, -1], "nearerSideWouldBe": [-1, 1, -1, 1]},
     "a stone ahead along the stream, half way between the middle and a bank, is gone round on its side toward the middle of the stream — by a "
     "trout coming down to it 20 px nearer the bank than the stone's centre, for whom the other side, toward the bank, is the smaller turn (the "
     "owner, 2026-10-20: \"not the side nearer the goal — a fish at the bank would go between the bank and the rock and get stuck\"); either "
     "bank, and the same where the stream runs down the screen"),
    ("a_rock_beside_is_gone_round_by_the_end_nearer_where_it_goes", "",
     "(() => { const ch = channelOf(), s = 500, c = ch.xy(s, ch.centre(s) + 30), p = ch.xy(s, ch.centre(s) + 180); ch.rocks = [stoneAt(c.x, c.y, 40)];"
     " const round = (ds) => { const f = new fishMod.Trout(new core.Rng(3), p, 100), q = ch.xy(s + ds, ch.centre(s) - 120);"
     " const r = steerAt(ch, p.x, p.y, f.seek(q.x, q.y, 300), -Math.PI / 2, f); return Math.sign(ch.sOf(r.out.x, r.out.y)); };"
     " return { downstream: round(150), upstream: round(-150) }; })()",
     {"downstream": 1, "upstream": -1},
     "a stone that lies across the stream from a trout, in its way to a place beyond it, is gone round by its end nearer that place: down the "
     "stream for a place below, up it for a place above — both ways keep to the trout's side of the stone, and the other leads round the far "
     "end, away from where it goes"),
    ("the_side_taken_is_kept", "",
     "(() => { const ch = channelOf(), s = 300, n = ch.centre(s + 250), c = ch.xy(s + 250, n), w = { x: 300, y: 0 }; ch.rocks = [stoneAt(c.x, c.y, 40)];"
     " const above = ch.xy(s, n - 5), below = ch.xy(s, n + 5), first = steerAt(ch, above.x, above.y, w), f = first.f;"
     " const kept = steerAt(ch, below.x, below.y, w, 0, f).across, fresh = steerAt(ch, below.x, below.y, w).across;"
     " ch.rocks = []; steerAt(ch, below.x, below.y, w, 0, f); const forgotten = f.passing === null; ch.rocks = [stoneAt(c.x, c.y, 40)];"
     " return { first: first.across, kept, fresh, forgotten, again: steerAt(ch, below.x, below.y, w, 0, f).across }; })()",
     {"first": -1, "kept": -1, "fresh": 1, "forgotten": True, "again": 1},
     "a stone on the middle line is gone round on the side the trout is on (here above it), and the side, once taken, is kept while that stone "
     "is in the way: drifted to 5 px below the stone's line, the trout still goes round above, where one seeing the stone first from there "
     "would go round below (a fish that chose again every frame would wobble into the stone); once nothing is in its way the side is forgotten, "
     "and the next sight chooses afresh"),
    ("a_rock_beyond_where_it_goes_is_not_in_the_way", "",
     "(() => { const ch = channelOf(), s = 300, p = ch.xy(s, ch.centre(s)), c = ch.xy(s + 250, ch.centre(s)); ch.rocks = [stoneAt(c.x, c.y, 40)];"
     " const to = (d) => { const f = new fishMod.Trout(new core.Rng(3), p, 100), q = { x: p.x + d, y: p.y }; return steerAt(ch, p.x, p.y, f.seek(q.x, q.y, 300), 0, f).turn; };"
     " return { before: to(150), beyond: to(400) !== 0, nearSide: to(250 - 40 - 20), farSide: to(250 + 40 + 20) !== 0 }; })()",
     {"before": 0, "beyond": True, "nearSide": 0, "farSide": True},
     "a trout going to a place goes no further, and a stone beyond the place is not in its way: a place 1.5 lengths ahead with a stone 2.5 "
     "lengths ahead is gone to straight, a place past the stone is gone round to; a place in the water about the stone (20 px off it, inside "
     "the room a trout passes a stone with: a lie, a hiding place, a fly drifting by it) is gone to straight from the near side, and round "
     "the stone from the far side"),
    ("a_way_along_a_rock_keeps_its_side", "",
     "(() => { const ch = channelOf(), s = 400, o = ch.xy(s, ch.centre(s)), stone = stoneAt(o.x, o.y, 40); ch.rocks = [stone]; let turned = 0, along = 0;"
     " for (let deg = 0; deg < 360; deg += 3) for (const k of [1, -1]) { const a = deg * Math.PI / 180, u = { x: Math.cos(a), y: Math.sin(a) }, p = { x: o.x + u.x * 70, y: o.y + u.y * 70 };"
     " const f = new fishMod.Trout(new core.Rng(3), p, 100), want = f.seek(o.x - u.x * 200, o.y - u.y * 200, 300); f.passing = { rock: stone, turn: k };"
     " const r = steerAt(ch, p.x, p.y, want, a + Math.PI, f), kept = { x: Math.cos(a + Math.PI + k * Math.PI / 2), y: Math.sin(a + Math.PI + k * Math.PI / 2) };"
     " const dot = (r.out.x * kept.x + r.out.y * kept.y) / 300; if (dot < 0) turned++; if (dot > 0.999) along++; }"
     " return { ways: 240, along, turned }; })()",
     {"ways": 240, "along": 240, "turned": 0},
     "a trout already inside the room it passes a stone with (30 px off a stone of radius 40), wanting to go through the stone, goes along "
     "the stone's outline on the side it took — either side, from every one of 120 places round the stone; negative: never the other way: the "
     "way along the outline touches the stone, and a second look that saw the same stone there chose its side afresh — toward the middle of "
     "the stream, against the side taken — and turned the fish round, frame after frame: in three minutes of 18 brooks a trout's goal jumped "
     "by more than a right angle in a frame 7101 times, and about 1700 with that stone left out"),
    ("close_to_a_stone_the_way_leads_out", "",
     "(() => { const ch = channelOf(), s = 400, o = ch.xy(s, ch.centre(s)); ch.rocks = [stoneAt(o.x, o.y, 40)];"
     " const off = (gap) => { const p = { x: o.x - 40 - gap, y: o.y }, f = new fishMod.Trout(new core.Rng(3), p, 100);"
     " const r = steerAt(ch, p.x, p.y, f.seek(o.x + 200, o.y, 300), 0, f); return Math.round(Math.atan2(-r.out.x, Math.abs(r.out.y)) * 180 / Math.PI); };"
     " return { far: off(30), near: off(8), touching: off(0), room: fishMod.Trout.ROCK_ROOM }; })()",
     {"far": 0, "near": 43, "touching": 90, "room": 0.25},
     "a trout inside the room it passes a stone with, wanting to go through the stone, goes along the stone; come within ROCK_ROOM of the stone "
     "itself, it goes out of the room too, the more the nearer: 30 px off a stone (more than a quarter of its length) its way runs straight "
     "along the outline, 8 px off it leans 43 degrees away from the stone, touching it straight out; straight along, the current set the nose of "
     "a fish that had come close a little into the stone, and the brakes held it there (a trout after a fly crept along a stone for 2.7 s at "
     "0.2 of its length a second)"),
    ("a_startled_trout_goes_round_its_rock", "",
     "(() => { const seen = fleeOf([1, 2, 3, 4, 5, 6]); blind(); const blindly = fleeOf([1, 2, 3, 4, 5, 6]);"
     " return { trout: seen.trout, pressed: seen.pressed, bodyIn: seen.bodyIn, level: seen.level, middleSide: seen.middleSide, middleLine: seen.middleLine,"
     " blindly: { pressed: blindly.pressed, bodyIn: blindly.bodyIn } }; })()",
     {"trout": 45, "pressed": 0, "bodyIn": 0, "level": 25, "middleSide": 21, "middleLine": 4, "blindly": {"pressed": 45, "bodyIn": 0}},
     "45 trout at the lies behind the rocks of 18 streams (three sizes, six layouts each), scared from below, flee up the stream toward the rock "
     "they hold behind (the owner, 2026-10-20: \"the fish run away but stop against a rock, instead of going round it as they come up to it\"): "
     "in its 0.9 s flight no trout brings its snout within the margin of a rock, and no point of any body is ever inside one; of the 25 that get "
     "level with their rock within two seconds, 21 go by its side toward the middle of the stream and 4 by a rock on the middle line — none by "
     "the bank's side; negative: the same trout with no look ahead and no brakes run into their rock, all 45 (the stone keeps their bodies off "
     "it, and their snouts at its margin)"),
    ("a_trout_wants_a_place_a_shoal_does_not", "",
     "(() => { const ch = channelOf(), at = ch.xy(500, ch.centre(500)), S = Object.getPrototypeOf(fishMod.Trout).prototype, swim = S.swim, seen = [];"
     " S.swim = function (dt, c, want, ...rest) { seen.push([this.constructor.name, want.to ? \"to\" : \"none\"]); return swim.call(this, dt, c, want, ...rest); };"
     " const life = { time: 0, channel: ch, noise: new core.Noise(new core.Rng(1)), trout: [], flyFor: () => null, freeLie: () => null, shallowSpot: () => null, shelterNear: () => at };"
     " const f = new fishMod.Trout(new core.Rng(3), at, 100); f.update(1 / 60, life); f.spook(at.x - 100, at.y, ch); f.update(1 / 60, life);"
     " new fishMod.MinnowShoal(life, at, 2, 24, new core.Rng(2)).update(1 / 60, life); return seen; })()",
     [["Trout", "to"], ["Trout", "none"], ["Minnow", "none"], ["Minnow", "none"]],
     "what a fish wants says where it leads, when it leads to a place: a trout drifting about its lie wants a place, and a stone beyond it is "
     "not in its way; a startled trout's flight and a shoal's sum of pulls lead nowhere in particular, and every stone along them counts"),
    ("a_trout_brakes_short_of_a_stone", "",
     "(() => { const ch = channelOf(), s = 300, p = ch.xy(s, ch.centre(s));"
     " const one = (dn, at) => { const c = ch.xy(s + 152, ch.centre(s) + dn); ch.rocks = [stoneAt(c.x, c.y, 40)];"
     " const f = new fishMod.Trout(new core.Rng(3), p, 100); f.heading = f.goal = 0; f.speed = 400; f.vx = 400; f.vy = 0; f.buildSpine();"
     " const want = { x: 400, y: 0 }; if (at) want.to = { x: c.x - 45, y: c.y }; f.swim(1 / 60, ch, want, 600, 4.5, 6); return Math.round(f.speed); };"
     " return { ahead: one(0, false), aPlaceAtIt: one(0, true), beside: one(120, false) > 350, stop: fishMod.Trout.STOP }; })()",
     {"ahead": 250, "aPlaceAtIt": 280, "beside": True, "stop": 0.4},
     "a trout swimming 4 lengths a second straight at a stone whose margin (ROCK_TOUCH) is one length ahead slows at once to 2.5 lengths a "
     "second: never faster than it could stop short of the margin in 0.4 s; when where it goes is at the stone (a fly drifting by it) it may "
     "come up to the stone itself, and slows to what stops it there; negative: a stone 1.2 lengths beside its way does not slow it"),
    ("the_whole_body_keeps_off_a_rock", "",
     "(() => { const ch = channelOf(), s = 300, p = ch.xy(s, ch.centre(s)); ch.rocks = [stoneAt(p.x - 120, p.y, 30)];"
     " const gaps = (f) => [0, 0.5, 1].map((u) => Math.round(-ch.rocks[0].inside(f.x - f.len * u, f.y, f.len * fishMod.Trout.ROCK_TOUCH)));"
     " const f = new fishMod.Trout(new core.Rng(3), p, 100); f.heading = 0; const before = gaps(f); f.vx = -50; f.vy = 20; f.stayInWater(ch);"
     " const g = new fishMod.Trout(new core.Rng(3), p, 100); g.heading = 0; g.vx = 80; g.vy = 20; g.stayInWater(ch);"
     " return { before, after: gaps(f), into: Math.round(f.vx), along: Math.round(f.vy), away: [Math.round(g.vx), Math.round(g.vy)] }; })()",
     {"before": [78, 28, -22], "after": [100, 50, 0], "into": 0, "along": 20, "away": [80, 20]},
     "a trout whose head is clear of a stone but whose tail lies on it (22 px inside the margin ROCK_TOUCH keeps round a stone) is moved off "
     "until no point of it — snout, middle, tail — is inside the margin, as at a bank, and the way it had into the stone is lost while the way "
     "along it is kept (until 1.3.603 only the snout was kept out, and a fish turning away from a rock swept its body across the stone); "
     "negative: a way out of the stone is kept"),
    ("strider_stays_in_the_banks",
     "",
     "(() => { const ch = channelOf(); const c = ch.centre(500), hw = ch.halfWidth(500); const dir = (v) => [v.x === 0 ? 0 : v.x, v.y === 0 ? 0 : v.y];"
     " const life = { channel: ch, rng: new core.Rng(4), ripples: { disturb() {} }, pointerNear: () => null, calmSpot: () => null };"
     " const press = (sign) => { const p = ch.xy(500, c + sign * hw * 0.8), st = new lifeMod.Strider(p.x, p.y, 12, new core.Rng(2)); let low = Infinity;"
     " for (let i = 0; i < 360; i++) { st.push.y = sign * 300; st.update(1 / 60, life); low = Math.min(low, shoreOf(ch, st.x, st.y)); }"
     " return low >= st.size * lifeMod.Strider.BANK_ROOM - 1e-6; };"
     " const q = ch.xy(500, c), sc = new lifeMod.Strider(q.x, q.y, 12, new core.Rng(2)); sc.flee(life, { x: q.x - 40, y: q.y - 30 });"
     " const away = [Math.abs(Math.sin(sc.heading)) < 1e-9, Math.cos(sc.heading) > 0, sc.push.x > 0, Math.abs(sc.push.y) < 1e-9];"
     " return [press(-1), press(1), away]; })()",
     [True, True, [True, True, True, True]],
     "a water strider shoved at a bank for six seconds stays the margin inside its edge (its legs reach it, the bank is drawn over it), "
     "either bank; scared by the pointer it darts along the stream, away from it, and not across"),
    ("echoes_come_once_in_order", "",
     "(() => { const e = new lifeMod.Echoes(); e.add(1.0, 10, 20); e.add(2.0, 30, 40); const first = e.due(0.5), second = e.due(1.5), again = e.due(1.5), last = e.due(3);"
     " return [first, second, again, last, e.waiting.length]; })()",
     [[], [{"at": 1.0, "x": 10, "y": 20}], [], [{"at": 2.0, "x": 30, "y": 40}], 0],
     "a hand's second ring (the one that follows the big one) comes once its time is due, in the order it was added, and not again; "
     "negative: nothing is due before its time, and nothing is left waiting after the last"),
    # ── the take and the drop ──
    ("segment_gap", "",
     "[[5, 0], [5, 3], [13, 4], [-3, 4]].map(([x, y]) => core.M.segmentGap(0, 0, 10, 0, x, y)).concat(core.M.segmentGap(2, 2, 2, 2, 5, 6))",
     [0, 3, 5, 5, 5],
     "how near a point lay to the way something went: on it, beside it, past its end, before its start, and a way that is a single point"),
    ("trout_mouth_is_the_tip_of_the_snout", "",
     r"""await (async () => { const ch = channelOf(), { at, f } = troutAt(ch), T = await mod("river-trout.js"); const m = f.mouth(), h = f.headFor(at.x + 100, at.y + 50);
       return { nose: T.TroutShape.NOSE, gape: fishMod.Trout.GAPE, mouth: [Math.round(m.x - at.x), Math.round(m.y - at.y)], head: [Math.round(h.x - at.x), Math.round(h.y - at.y)] }; })()""",
     {"nose": 0.03, "gape": 0.08, "mouth": [3, 0], "head": [97, 50]},
     "the mouth of a trout 100 px long, facing east, is 3 px ahead of the head's first point (the nose the outline draws), and the head must stand "
     "that far short of a fly for the mouth to be on it; a mouth takes a fly within 0.08 of the trout's length"),
    ("trout_takes_what_is_at_its_mouth", "",
     "(() => { const ch = channelOf(), { at, f } = troutAt(ch); const took = (dx, dy) => f.takes(at.x + dx, at.y + dy);"
     " return { onTip: took(3, 0), ahead7: took(10, 0), ahead9: took(12, 0), beside7: took(3, 7), beside9: took(3, 9), atHead: took(0, 0),"
     " oldReach41: took(41, 0), oldNose42: took(42, 0) }; })()",
     {"onTip": True, "ahead7": True, "ahead9": False, "beside7": True, "beside9": False, "atHead": True, "oldReach41": False, "oldNose42": False},
     "a trout takes a fly 7 px from the tip of its snout, ahead or beside, and does not take one 9 px from it; negative: a fly 41 px ahead of the head "
     "(38 from the nose) or 42 px ahead (39 from it) — where a trout took one in the first version: within 0.42 of its length of the head — is not at its mouth"),
    ("trout_takes_what_its_mouth_passes_over", "",
     "(() => { const ch = channelOf(); const step = (way) => { const { at, f } = troutAt(ch); if (way) f.mouthWas = f.mouth(); f.x += 60; f.buildSpine(); return { at, f }; };"
     " const a = step(true), b = step(false); const took = (r, dx, dy) => r.f.takes(r.at.x + dx, r.at.y + dy);"
     " return { onWay: took(a, 33, 0), off7: took(a, 33, 7), off9: took(a, 33, 9), behindStart: took(a, -10, 0), pastEnd: took(a, 75, 0), noWay: took(b, 33, 0) }; })()",
     {"onWay": True, "off7": True, "off9": False, "behindStart": False, "pastEnd": False, "noWay": False},
     "a step of 60 px on a slow frame carries the mouth over a fly in the middle of it: the fly is taken; 7 px beside the way it is still taken, 9 px not; "
     "negative: a fly behind where the step began or past where it ended is not; with no way recorded only where the mouth is now counts"),
    ("trout_update_keeps_the_way_of_its_mouth", "",
     "(() => { const ch = channelOf(), { at, f } = troutAt(ch); f.speed = 300; f.vx = 300; const before = f.mouth();"
     " f.update(1 / 60, { time: 0, noise: new core.Noise(new core.Rng(2)), channel: ch, flyFor: () => null, freeLie: () => null, shelterNear: () => at });"
     " return { was: [Math.round(f.mouthWas.x - before.x), Math.round(f.mouthWas.y - before.y)], moved: Math.hypot(f.x - at.x, f.y - at.y) > 0.5 }; })()",
     {"was": [0, 0], "moved": True},
     "every step of a trout writes down where its mouth stood before it, so that the next look at a fly sees the whole way the mouth went"),
    ("chase_brings_the_mouth_to_a_natural_fly", "",
     "(() => { const ch = channelOf(1200, 700); const run = (dt) => Array.from({ length: 40 }, (_, i) => chaseOf(ch, i + 1, dt, true)).filter((v) => v !== null);"
     " const fast = run(1 / 60), slow = run(1 / 20); const near = (r) => Math.max(...r.map((v) => v.near));"
     " return { took: [fast.length, slow.length], near: [near(fast) <= 0.15, near(slow) <= 0.2] }; })()",
     {"took": [40, 40], "near": [True, True]},
     "a fly that drifts down the stream to a trout holding its lie is taken every time, with the fly within 0.15 of the trout's length of the snout's tip "
     "on a fast frame (60 a second) and 0.2 on a slow one (20), where it was 0.39 away in the first version"),
    ("chase_brings_the_mouth_to_a_thrown_fly", "",
     "(() => { const ch = channelOf(1200, 700); const run = (dt) => Array.from({ length: 40 }, (_, i) => chaseOf(ch, i + 1, dt, false)).filter((v) => v !== null);"
     " const fast = run(1 / 60), slow = run(1 / 20); const near = (r) => Math.max(...r.map((v) => v.near));"
     " return { took: [fast.length >= 36, slow.length >= 36], near: [near(fast) <= 0.15, near(slow) <= 0.25] }; })()",
     {"took": [True, True], "near": [True, True]},
     "a fly thrown anywhere ahead of a trout or beside it is taken in at least 36 of 40 chases, at the mouth as well; the others end after six seconds, "
     "the fly left to the water (the trout must turn sharply and slow down to reach it: slower or duller turns took 33 to 56 of every 100)"),
    ("chase_turns_sharper_than_the_rest", "",
     "(() => { const ch = channelOf(), { at, f } = troutAt(ch); const swimmer = fishMod.Trout.AGILITY, start = { ...f.agility };"
     " f.enter(\"chase\", {}); const chase = { ...f.agility }; f.enter(\"back\", {}); const back = { ...f.agility }; f.spook(at.x - 100, at.y, ch);"
     " return { start, chase, back, flee: { ...f.agility }, frozen: Object.isFrozen(swimmer) }; })()",
     {"start": {"gain": 2.4, "pivot": 0.35}, "chase": {"gain": 4.5, "pivot": 0.8}, "back": {"gain": 2.4, "pivot": 0.35},
      "flee": {"gain": 5, "pivot": 0.9}, "frozen": True},
     "a trout turns as every fish does, except while it chases a fly: then it turns sharper and keeps most of its turn with no way on; "
     "the next state gives it back; and except when it is startled (1.3.603): it turns at once, from rest too, as a fish escapes — turning "
     "as slowly as it swims about, it stood at the rock it holds behind while its way round was still ahead of it"),
    ("a_trout_thinks_over_a_fly_before_it_moves", "",
     r"""(() => { const ch = channelOf(1200, 700), T = fishMod.Trout.THINK; const runs = Array.from({ length: 30 }, (_, i) => thinkOf(ch, i + 1));
       const first = runs.map((r) => r.log[0]), second = runs.map((r) => r.log[1]), waits = runs.map((r) => r.log[1][2] - r.log[0][2]);
       const slow = Array.from({ length: 30 }, (_, i) => thinkOf(ch, i + 1, 1 / 20)).map((r) => r.log[1][2] - r.log[0][2]);
       return { saw: [...new Set(first.map((l) => l[0] + ">" + l[1]))], then: [...new Set(second.map((l) => l[0] + ">" + l[1]))], sightAt: Math.max(...first.map((l) => l[2])),
         claimed: first.every((l) => l[3]), within: [Math.min(...waits) >= T.least - 0.02, Math.max(...waits) <= T.most + 0.02], slowFrames: [Math.min(...slow) >= T.least - 0.06, Math.max(...slow) <= T.most + 0.06],
         varied: Math.max(...waits) - Math.min(...waits) > 0.4, keepsItsLie: Math.max(...runs.map((r) => r.away)) < 0.7, tookAfter: runs.every((r) => r.rose.length === 1 && r.rose[0] > r.log[1][2]), limits: [T.least, T.most] }; })()""",
     {"saw": ["hold>notice"], "then": ["notice>chase"], "sightAt": 0, "claimed": True, "within": [True, True], "slowFrames": [True, True], "varied": True,
      "keepsItsLie": True, "tookAfter": True, "limits": [0.8, 1.8]},
     "a trout that sees a fly does not move at once (the owner, 2026-10-19: \"the moment the moth appears they swim after it; they used to think longer\"): it goes from hold "
     "to notice the step it sees it, makes the fly its own, keeps near its lie for a time between 0.8 and 1.8 s, a different one for each fly and the same on a fast frame and on a slow, "
     "then chases it and takes it — never before the thinking is done"),
    ("a_fly_that_is_gone_is_let_go", "",
     r"""(() => { const ch = channelOf(1200, 700); const one = (kind) => thinkOf(ch, 4, 1 / 60, { kind, at: 0.3 }); const dies = one("dies"), claimed = one("claimed");
       const names = (r) => r.log.map((l) => l[0] + ">" + l[1]);
       return { dies: [names(dies), dies.rose.length], claimed: [names(claimed), claimed.rose.length, claimed.fly.claimedBy === claimed.other, claimed.fly.alive] }; })()""",
     {"dies": [["hold>notice", "notice>hold"], 0], "claimed": [["hold>notice", "notice>hold"], 0, True, True]},
     "negative: a fly that dies while the trout thinks, or that another fish makes its own, is let go: the trout goes back to holding its lie, takes nothing, "
     "and leaves the other fish's claim as it was"),
    ("thinking_draws_from_its_own_stream", "",
     r"""(() => { const draws = (seed) => { const r = new core.Rng(seed); let n = 0; const next = r.next.bind(r); r.next = () => { n++; return next(); };
         const f = new fishMod.Trout(r, { x: 0, y: 0 }, 100); const built = n; f.enter("notice", {}); return { extra: n - built, think: f.thinkFor }; };
       const a = draws(3), again = draws(3), b = draws(4), T = fishMod.Trout.THINK;
       return { extra: [a.extra, b.extra], inside: [a.think, b.think].every((v) => v >= T.least && v <= T.most), same: a.think === again.think, differ: a.think !== b.think }; })()""",
     {"extra": [0, 0], "inside": True, "same": True, "differ": True},
     "how long a trout thinks is drawn from a stream of its own: entering the state takes nothing from the brook's stream (every seed lays the brook out as it did), "
     "the same trout thinks the same time and another trout another time, both within the limits"),
    ("its_eyes_follow_the_fly_while_it_thinks", "",
     r"""(() => { const ch = channelOf(), { at, f } = troutAt(ch); const a = Math.PI / 3, d = 400;
       const fly = { x: at.x + Math.cos(a) * d, y: at.y + Math.sin(a) * d, vx: 0, vy: 0, alive: true, claimedBy: f };
       const watch = (state) => { f.target = fly; f.state = state; f.look = { x: 1, y: 0 }; for (let i = 0; i < 120; i++) f.animate(1 / 60);
         const m = f.mouth(), dx = fly.x - m.x, dy = fly.y - m.y; return +((f.look.x * dx + f.look.y * dy) / (Math.hypot(dx, dy) * Math.hypot(f.look.x, f.look.y))).toFixed(3); };
       return { far: d / f.len, thinking: watch("notice"), holding: watch("hold") }; })()""",
     {"far": 4, "thinking": 1, "holding": 0.494},
     "while it thinks a fly over, the trout's eyes are on the fly however far it is (4 lengths away, 60 degrees to the side: the look comes to it); "
     "negative: not thinking and the fly that far, the eyes stay ahead (the fly lies at 60 degrees to them, seen from the mouth: 0.494)"),
    ("rise_leaves_a_ring_and_no_spray", "",
     "(() => { const rings = [], spray = [], calls = []; const life = { C: 600, ripples: { disturb: (...a) => rings.push(a) }, specks: { splash: (...a) => spray.push(a) },"
     " scene: { sound: (fn) => fn(kitOf(calls), 0) } }; const fly = { x: 120, y: 80, alive: true };"
     " lifeMod.BrookLife.prototype.rise.call(life, new fishMod.Trout(new core.Rng(1), { x: 0, y: 0 }, 60), fly);"
     " return { alive: fly.alive, rings: rings.map((r) => r.map((v) => +v.toFixed(3))), spray: spray.length, sounds: calls.map((c) => c[0]) }; })()",
     {"alive": False, "rings": [[120, 80, 1.7, 7.2]], "spray": 0, "sounds": ["plink"]},
     "a trout's take eats the fly, leaves one ring where it lay, throws no spray (the owner took it out) and sounds once, as a drop"),
    ("water_sounds_are_drops", "",
     "(() => { const real = Math.random; Math.random = () => 0.5;"
     " const play = (what) => { const calls = []; what({ scene: { sound: (fn) => fn(kitOf(calls), 0) }, C: 600, flies: [], rng: new core.Rng(1), time: 0, trout: [], falling: [],"
     " channel: { isWater: () => true }, ripples: { disturb() {} }, echoes: { add() {} }, shoal: { spook() {} }, frogs: { plop() {} } }); return calls; };"
     " const proto = lifeMod.BrookLife.prototype;"
     " const take = play((life) => proto.rise.call(life, new fishMod.Trout(new core.Rng(1), { x: 0, y: 0 }, 60), { x: 5, y: 5, alive: true }));"
     " const tap = play((life) => proto.pointer.call(life, \"down\", { x: 50, y: 50 }));"
     " const plop = play((life) => proto.pointer.call(life, \"double\", { x: 50, y: 50 }));"
     " Math.random = real; const o = (c) => c[0][1];"
     " return { take, tap, plop, lower: [o(plop).f < o(take).f, o(take).f < o(tap).f], longer: [o(plop).ring > o(take).ring, o(take).ring > o(tap).ring] }; })()",
     {"take": [["plink", {"f": 640, "ring": 0.26, "gain": 0.09}]], "tap": [["plink", {"f": 900, "ring": 0.2, "gain": 0.06}]],
      "plop": [["plink", {"f": 330, "ring": 0.42, "gain": 0.14, "room": 0.3}]], "lower": [True, True], "longer": [True, True]},
     "a fly landing on the water, a trout taking one and a hand's plop each make one sound, a drop — not a tap and a splash of noise; "
     "the bigger the drop, the lower it starts and the longer it rings: the plop below the take below the landing"),
    ("plink_is_one_rising_sine", "",
     "(() => { const ctx = fakeAudio(), kit = new soundMod.SoundKit(ctx, {}); ctx.log.length = 0; const real = Math.random; Math.random = () => 0.5;"
     " kit.plink(1, { f: 900, ring: 0.2, gain: 0.06, pan: 0.1, room: 0.2 }); Math.random = real;"
     " const osc = ctx.log.filter((n) => n.kind === \"osc\"), env = ctx.log.filter((n) => n.kind === \"gain\")[0].gain.calls;"
     " const r = (c) => [c[0], +c[1].toPrecision(4), +c[2].toFixed(3)];"
     " const from = (rand) => { const c = fakeAudio(), k = new soundMod.SoundKit(c, {}); c.log.length = 0; const was = Math.random; Math.random = () => rand; k.plink(0, { f: 900 }); Math.random = was;"
     " return Math.round(c.log.find((n) => n.kind === \"osc\").frequency.calls[0][1]); };"
     " return { oscillators: osc.length, noise: ctx.log.filter((n) => n.kind === \"buffer\" || n.kind === \"filter\").length, type: osc[0].type,"
     " pitch: osc[0].frequency.calls.map(r), envelope: env.map(r), start: osc[0].calls.filter((c) => c[0] === \"start\"), stop: osc[0].calls.filter((c) => c[0] === \"stop\").map((c) => [c[0], +c[1].toFixed(3)]),"
     " pan: ctx.log.find((n) => n.kind === \"pan\").pan.value, send: ctx.log.filter((n) => n.kind === \"gain\")[1].gain.value, rise: soundMod.SoundKit.PLINK_RISE,"
     " spread: [from(0), from(0.999)] }; })()",
     {"oscillators": 1, "noise": 0, "type": "sine", "pitch": [["set", 900, 1], ["ramp", 1620, 1.1]],
      "envelope": [["set", 0.0001, 1], ["ramp", 0.06, 1.004], ["ramp", 0.0001, 1.2]], "start": [["start", 1]], "stop": [["stop", 1.25]],
      "pan": 0.1, "send": 0.2, "rise": 1.8, "spread": [828, 972]},
     "a drop is one sine voice and nothing else — no noise source, no filter: it starts at its pitch, climbs 1.8 times over half its ring while "
     "it dies away, and is done at the end of the ring; it sits where it is panned and sends a little to the room; each drop starts within 8% of "
     "its pitch, either way; a burst of noise was what the owner did not like in a tap and a splash"),
    ("drop_of_the_trickle_is_unchanged", "",
     "(() => { const ctx = fakeAudio(), kit = new soundMod.SoundKit(ctx, {}); ctx.log.length = 0; const real = Math.random; Math.random = () => 0.5;"
     " kit.drop(1, { f: 1000, gain: 0.01, pan: 0, room: 0.1 }); Math.random = real; const o = ctx.log.find((n) => n.kind === \"osc\");"
     " return { pitch: o.frequency.calls.map((c) => [c[0], Math.round(c[1]), +c[2].toFixed(3)]), stop: o.calls.filter((c) => c[0] === \"stop\").map((c) => +c[1].toFixed(3)) }; })()",
     {"pitch": [["set", 1000, 1], ["ramp", 1800, 1.055]], "stop": [1.105]},
     "the short drops of the brook's trickle (river-scene.js) are as they were: a pitch that climbs over the whole of a few hundredths of a second; "
     "the drop of a landing, a take and a plop glides over half of its ring and nothing else changed for these"),
    ("trout_nose_is_one_number", "",
     "await (async () => { const art = readFileSync(process.env.JS_ROOT + \"/river-trout.js\", \"utf8\"), fish = readFileSync(process.env.JS_ROOT + \"/river-fish.js\", \"utf8\"), T = await mod(\"river-trout.js\");"
     " return { body: /const len = fish\\.len,[^;]*nose = len \\* TroutShape\\.NOSE/.test(art), shadow: /this\\.len \\* TroutShape\\.NOSE, dx, dy/.test(fish), nose: T.TroutShape.NOSE,"
     " mouth: (fish.match(/reach = this\\.len \\* TroutShape\\.NOSE/g) || []).length, literal: /outline\\([^)]*len \\* 0\\.03\\b/.test(art + fish) }; })()",
     {"body": True, "shadow": True, "nose": 0.03, "mouth": 2, "literal": False},
     "the nose the outline of a trout draws, the body's and the shadow's, and the tip its mouth takes a fly at (where the mouth is, and where the head must stand for it to be there) "
     "are one number, TroutShape.NOSE (0.03 of the length, as in the first version)"),
    ("brook_has_no_spray_and_no_noise_click", "",
     "(() => { const src = [\"river-life.js\", \"river-fish.js\", \"river-frogs.js\", \"river-frog.js\", \"river-sound.js\", \"river-scene.js\"].map((f) => readFileSync(process.env.JS_ROOT + \"/\" + f, \"utf8\")).join(\"\\n\");"
     " return { splash: /\\bsplash\\s*\\(/.test(src), drops: /\\.drops\\b/.test(src), click: /\\.click\\s*\\(/.test(src), white: /\\bwhite\\s*:/.test(src) }; })()",
     {"splash": False, "drops": False, "click": False, "white": False},
     "nothing in the brook throws spray any more and the sound kit has no burst of noise to make one with: a call to splash(), a list of drops, "
     "a click() or a white-noise colour coming back would be the owner's tap and splash again"),
    # ── words ──
    ("switch_words_wait", "",
     "(() => { const s = new RiverSwitch(page(), new RiverPrefs(store()), { load: brook().load }); s.mount();"
     " return { label: s.label.textContent, title: s.button.title }; })()",
     {"label": "", "title": ""},
     "before the dictionary arrives the button has no word at all, not a key's name standing in for one"),
    ("switch_words_stored_language",
     "globalThis.localStorage = { getItem: (k) => (k === dict.LANG_KEY ? \"ru\" : null), setItem() {} };",
     "await (async () => { const b = brook(); const s = new RiverSwitch(page(), new RiverPrefs(store()), { load: b.load, words: async () => dict });"
     " s.mount(); await s.learnWords(); const off = { label: s.label.textContent, title: s.button.title };"
     " s.button.click(); await settle(); return { off, on: s.button.title, brook: b.log.words }; })()",
     {"off": {"label": "Ручей", "title": "Включить ручей под страницами"}, "on": "Выключить ручей и его звук", "brook": ["Ручей"]},
     "the words are the stored language's (here Russian), and the brook gets the same words to name its dock"),
    ("words_fall_back", "",
     "[dict.translate(\"xx\", \"riverToggle\"), dict.translate(\"en\", \"riverNoSuchWord\"), dict.translate(\"en\", \"riverLevelTitle\")]",
     ["Brook", "riverNoSuchWord", "How much of the brook shows through the page"],
     "one rule for every page (translate in i18n-data.js): a language without the word speaks English, a word nobody has is its key"),
    ("words_all_present", "",
     "(() => { const src = [\"river.js\", \"river-background.js\", \"river-dock.js\", \"river-prefs.js\"].map((f) => readFileSync(process.env.JS_ROOT + \"/\" + f, \"utf8\")).join(\"\\n\");"
     " const inWord = [...src.matchAll(/word\\(([^()]*)\\)/g)].flatMap((m) => [...m[1].matchAll(/\"(river\\w+)\"/g)].map((k) => k[1]));"
     " const asked = new Set([...inWord, ...[...src.matchAll(/(?:key: |dataset\\.i18n = )\"(river\\w+)\"/g)].map((m) => m[1])]);"
     " return { asked: asked.size >= 15, missing: [...asked].filter((k) => !(k in dict.messages.en)).sort() }; })()",
     {"asked": True, "missing": []},
     "every word the brook asks for is in the English table, and so in all twenty (check_messages_i18n): "
     "the brook asks through word(), which check_i18n_calls does not read"),
]


_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def main():
    if len(PINS) < 50:
        print(f"js river FAILED: only {len(PINS)} pins — the snapshot is empty or cut")
        return 1
    node = find_node()
    if node is None:
        print("js river: SKIPPED — node not found on PATH nor with the version managers: " + ", ".join(node_search_paths()))
        return 0
    ids = [p[0] for p in PINS]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        print(f"js river FAILED: repeated pin ids: {sorted(dup)}")
        return 1
    # Each pin runs in its own node process: a pin that replaces localStorage or the store
    # must not leave it behind for the next one, so independence is by construction.
    harness = ROOT / "scripts" / "_js_harness.mjs"
    env = {**os.environ, "JS_ROOT": str(ROOT / "static" / "js"), "JS_STUBS": "", "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "TZ": "UTC"}
    got = {}
    for pid, setup, expr, _expected, _msg in PINS:
        probe = (PREAMBLE + f"try {{ {setup}\n  out.v = {expr}; }} catch (e) {{ out.v = {{ __threw: String(e && e.message || e) }}; }}\n"
                 "console.log(JSON.stringify(out.v === undefined ? null : out.v)); process.exit(0);\n")
        probe_path = ROOT / "scripts" / f".probe_js_river_{pid}.tmp.mjs"
        probe_path.write_text(probe)
        try:
            # this file's pins hung node in process.exit now and then, the heaviest one most: NODE_FLAGS in scripts/_node.py
            run = subprocess.run(probe_args(node, harness, probe_path), capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
        finally:
            probe_path.unlink(missing_ok=True)
        if run.returncode != 0:
            print(run.stdout); print(run.stderr)
            print(f"js river FAILED: node exited with {run.returncode} on pin {pid}")
            return 1
        got[pid] = json.loads(run.stdout.strip().splitlines()[-1])
    for pid, _setup, _expr, expected, msg in PINS:
        have = got.get(pid, {"__missing": True})
        ok = have == expected
        check(ok, msg if ok else f"{msg}\n        expected {json.dumps(expected, ensure_ascii=False)[:300]}\n        got      {json.dumps(have, ensure_ascii=False)[:300]}")
    print()
    if _fail:
        print(f"FAILED ({len(_fail)}):")
        for f in _fail:
            print("  - " + f.splitlines()[0])
        return 1
    print(f"js river OK: the real modules in node, {len(PINS)} pins of the brook's switch, its dock, its memory, its banks and rocks, the take and the drop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
