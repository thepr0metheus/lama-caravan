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
/** A stream seen from above, the same everywhere: left to right when wide, down the screen when tall. */
const channelOf = (w = 1000, h = 600) => new worldMod.Channel(w, h, new core.Rng(5), new core.Noise(new core.Rng(41)));
const shoreOf = (ch, x, y) => ch.shore(ch.sOf(x, y), ch.nOf(x, y));
/** The three points of a fish the banks are kept from: the snout, the middle of the spine, the tail. */
const bodyOf = (f) => [0, Math.floor(f.spine.length / 2), f.spine.length - 1].map((i) => f.spine[i]);

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
    if len(PINS) < 32:
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
    print(f"js river OK: the real modules in node, {len(PINS)} pins of the brook's switch, its dock, its memory and its banks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
