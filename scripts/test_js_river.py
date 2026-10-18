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

The take and the drop (1.3.546; the owner, 2026-10-14: "the fish eats the moth while its mouth is still far
from it", "remove the splashes", "let the sound be like a drop falling into water"). The trout runs as
itself in a stream with a fly drifting on it. What is pinned: where its mouth is and what the mouth takes
and passes over; that a chase brings the mouth to the fly (it took it 0.39 of its length from the nose
before), on a fast frame and on a slow one, for a fly that drifts down to a trout and for one thrown
beside it; that a take leaves a ring and no spray; that the sound of a landing fly, of a take and of a
hand's plop is one voice, a drop, each bigger drop lower and longer; and what that voice is made of: one
rising sine and no noise.

Run: python3 scripts/test_js_river.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node import find_node, node_search_paths  # noqa: E402

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
 * body lengths, or null when the chase ended with no take. A natural fly comes down the stream to a trout holding its lie; any other is
 * thrown anywhere ahead of it or beside it, as a click on the water does.
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
  let near = null;
  const flies = [fly];
  const life = { time: 0, noise: new core.Noise(new core.Rng(seed + 1)), channel: ch,
    flyFor: (fish) => lifeMod.BrookLife.prototype.flyFor.call({ flies }, fish),
    rise: (fish, g) => { g.alive = false; const m = fish.mouth(); near = Math.hypot(g.x - m.x, g.y - m.y) / fish.len; },
    freeLie: () => null, shelterNear: () => at };
  for (let t = 0; t < 12 && near === null; t += dt) {
    const w = ch.sample(fly.x, fly.y), k = Math.min(1, 2 * dt);
    fly.vx += (w.vx - fly.vx) * k; fly.vy += (w.vy - fly.vy) * k;
    fly.x += fly.vx * dt; fly.y += fly.vy * dt; life.time = t;
    f.update(dt, life);
    if (f.state === "back" && near === null && t > 0.2) break;
  }
  return near;
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
     "(() => { const ch = channelOf(), { at, f } = troutAt(ch); const m = f.mouth(), h = f.headFor(at.x + 100, at.y + 50);"
     " return { nose: fishMod.Trout.NOSE, gape: fishMod.Trout.GAPE, mouth: [Math.round(m.x - at.x), Math.round(m.y - at.y)], head: [Math.round(h.x - at.x), Math.round(h.y - at.y)] }; })()",
     {"nose": 0.03, "gape": 0.08, "mouth": [3, 0], "head": [97, 50]},
     "the mouth of a trout 100 px long, facing east, is 3 px ahead of the head's first point (the nose the outline draws), and the head must stand "
     "that far short of a fly for the mouth to be on it; a mouth takes a fly within 0.08 of the trout's length"),
    ("trout_takes_what_is_at_its_mouth", "",
     "(() => { const ch = channelOf(), { at, f } = troutAt(ch); const took = (dx, dy) => f.takes(at.x + dx, at.y + dy);"
     " return { onTip: took(3, 0), ahead7: took(10, 0), ahead9: took(12, 0), beside7: took(3, 7), beside9: took(3, 9), atHead: took(0, 0),"
     " oldReach41: took(41, 0), oldNose42: took(42, 0) }; })()",
     {"onTip": True, "ahead7": True, "ahead9": False, "beside7": True, "beside9": False, "atHead": True, "oldReach41": False, "oldNose42": False},
     "a trout takes a fly 7 px from the tip of its snout, ahead or beside, and does not take one 9 px from it; negative: a fly 41 px ahead of the head "
     "(38 from the nose) or 42 px ahead (39 from it) — where a trout took one before: within 0.42 of its length of the head — is not at its mouth"),
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
     " const fast = run(1 / 60), slow = run(1 / 20); return { took: [fast.length, slow.length], near: [Math.max(...fast) <= 0.15, Math.max(...slow) <= 0.2] }; })()",
     {"took": [40, 40], "near": [True, True]},
     "a fly that drifts down the stream to a trout holding its lie is taken every time, with the fly within 0.15 of the trout's length of the snout's tip "
     "on a fast frame (60 a second) and 0.2 on a slow one (20), where it was 0.39 away before"),
    ("chase_brings_the_mouth_to_a_thrown_fly", "",
     "(() => { const ch = channelOf(1200, 700); const run = (dt) => Array.from({ length: 40 }, (_, i) => chaseOf(ch, i + 1, dt, false)).filter((v) => v !== null);"
     " const fast = run(1 / 60), slow = run(1 / 20); return { took: [fast.length >= 36, slow.length >= 36], near: [Math.max(...fast) <= 0.15, Math.max(...slow) <= 0.25] }; })()",
     {"took": [True, True], "near": [True, True]},
     "a fly thrown anywhere ahead of a trout or beside it is taken in at least 36 of 40 chases, at the mouth as well; the others end after six seconds, "
     "the fly left to the water (the trout must turn sharply and slow down to reach it: slower or duller turns took 33 to 56 of every 100)"),
    ("chase_turns_sharper_than_the_rest", "",
     "(() => { const ch = channelOf(), { at, f } = troutAt(ch); const swimmer = fishMod.Trout.AGILITY, start = { ...f.agility };"
     " f.enter(\"chase\", {}); const chase = { ...f.agility }; f.enter(\"back\", {}); return { start, chase, back: { ...f.agility }, frozen: Object.isFrozen(swimmer) }; })()",
     {"start": {"gain": 2.4, "pivot": 0.35}, "chase": {"gain": 4.5, "pivot": 0.8}, "back": {"gain": 2.4, "pivot": 0.35}, "frozen": True},
     "a trout turns as every fish does, except while it chases a fly: then it turns sharper and keeps most of its turn with no way on; "
     "the next state gives it back"),
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
     " channel: { isWater: () => true }, ripples: { disturb() {} }, echoes: { add() {} }, shoal: { spook() {} } }); return calls; };"
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
    ("trout_nose_is_painted_where_the_mouth_is", "",
     "(() => { const src = readFileSync(process.env.JS_ROOT + \"/river-fish.js\", \"utf8\");"
     " return { body: /painter\\.outline\\(ctx, this\\.spine, this\\.widths, len \\* Trout\\.NOSE\\)/.test(src), literal: /this\\.widths, len \\* 0\\.03\\)/.test(src) }; })()",
     {"body": True, "literal": False},
     "the nose the outline of a trout draws and the nose its mouth is measured from are one number, Trout.NOSE: the fly is taken where the picture's "
     "snout ends, not 3% of the length short of it or past it"),
    ("brook_has_no_spray_and_no_noise_click", "",
     "(() => { const src = [\"river-life.js\", \"river-fish.js\", \"river-sound.js\", \"river-scene.js\"].map((f) => readFileSync(process.env.JS_ROOT + \"/\" + f, \"utf8\")).join(\"\\n\");"
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
    if len(PINS) < 46:
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
            run = subprocess.run(
                [node, "--import", f"data:text/javascript,import {{ register }} from 'node:module'; register('{harness.as_uri()}');",
                 str(probe_path)], capture_output=True, text=True, env=env, cwd=ROOT, timeout=60)
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
    print(f"js river OK: the real modules in node, {len(PINS)} pins of the brook's switch, its dock, its memory, its banks, the take and the drop")
    return 0


if __name__ == "__main__":
    sys.exit(main())
