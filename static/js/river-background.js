/*
 * river-background.js: the brook behind a page, while the switch (river.js) is on.
 *
 * It lays the stage under everything the page draws, a shade over the stage that sets how much
 * of the water shows through, and the dock's buttons (river-dock.js, under the header's switch):
 * brightness, pause, sound.
 * The page keeps the pointer: movement anywhere ripples the water, and a press on the page's open
 * space (no control and no painted card under it) drops a fly on the water.
 * dispose() takes everything away again: the canvases, the WebGL context, the sound, the listeners,
 * the dock.
 */
import { Stage } from "./river-core.js";
import { RiverDock } from "./river-dock.js";
import { RIVER_LEVELS } from "./river-prefs.js";
import { BrookScene } from "./river-scene.js";
import { Ambience } from "./river-sound.js";

/** What on a page takes a press itself; a press there is never the water's. */
const PRESSABLE = 'a, button, input, select, textarea, label, summary, [role="button"], [role="dialog"], [role="menu"], [role="listbox"], [contenteditable="true"], [tabindex]:not([tabindex="-1"])';

export class RiverBackground {
  /** doc: the page. prefs: a RiverPrefs. word(key): the page's word for a key.
   *  host: the switch's group in the header, where the dock hangs. */
  constructor(doc, prefs, word, host) {
    this.doc = doc;
    this.prefs = prefs;
    this.word = word;
    this.root = RiverBackground.element(doc, "div", "river-stage");
    this.shade = RiverBackground.element(doc, "div", "river-shade");
    this.root.setAttribute("aria-hidden", "true");
    this.shade.setAttribute("aria-hidden", "true");
    doc.body.prepend(this.root, this.shade);
    this.dock = new RiverDock(doc, host, word);
    this.stage = new Stage(this.root);
    this.sound = new Ambience();
    this.stage.sound = this.sound;
    this.scene = this.stage.show(BrookScene);
    this.levelButtons = new Map();
    this.note = null;
    this.buildDock();
    this.setLevel(prefs.level, false);
    // a viewer who asked the system for less motion gets a still brook until pressing Resume
    this.setPaused(prefs.paused || this.stage.reducedMotion, false);
    this.listen();
    this.relabel();
  }

  static element(doc, tag, className) {
    const el = doc.createElement(tag);
    el.className = className;
    return el;
  }

  /** True when nothing of the page under a press takes it: no control, no painted card. */
  static isOpenWater(target, win) {
    for (let el = target; el && el.nodeType === 1; el = el.parentElement) {
      if (el === el.ownerDocument.body || el === el.ownerDocument.documentElement) return true;
      if (el.matches(PRESSABLE)) return false;
      const bg = win.getComputedStyle(el).backgroundColor;
      if (bg && bg !== "transparent" && !/^rgba\(.*,\s*0\)$/.test(bg)) return false;
    }
    return true;
  }

  buildDock() {
    if (this.scene.failure) {
      // no WebGL in this browser: the brook cannot run, and the dock says so instead of its
      // buttons, open at once, since the viewer has just turned on a brook that does not show
      this.note = RiverBackground.element(this.doc, "p", "river-dock-note");
      this.dock.panel.append(this.note);
      this.dock.show();
      return;
    }
    for (const level of RIVER_LEVELS) {
      const b = this.button("river-level", () => this.setLevel(level, true));
      b.dataset.tId = level.id;
      this.levelButtons.set(level.id, b);
    }
    this.dock.panel.append(RiverBackground.element(this.doc, "span", "river-sep"));
    this.pauseButton = this.button("river-pause", () => this.setPaused(!this.stage.paused, true));
    this.soundButton = this.button("river-sound", () => this.toggleSound());
    this.soundButton.setAttribute("aria-pressed", "false");
  }

  button(testId, onClick) {
    const b = this.doc.createElement("button");
    b.type = "button";
    b.className = "river-dock-button";
    b.dataset.t = testId;
    b.addEventListener("click", onClick);
    this.dock.panel.append(b);
    return b;
  }

  /** Names everything in the page's language; river.js calls it again when the language changes. */
  relabel() {
    this.dock.relabel();
    if (this.note) { this.note.textContent = this.word("riverNoWebgl"); return; }
    for (const level of RIVER_LEVELS) {
      const b = this.levelButtons.get(level.id);
      b.textContent = this.word(level.key);
      b.title = this.word("riverLevelTitle");
    }
    this.pauseButton.textContent = this.word(this.stage.paused ? "riverResume" : "riverPause");
    this.pauseButton.title = this.word("riverPauseTitle");
    this.soundButton.textContent = this.word("riverSound");
    this.soundButton.title = this.word("riverSoundTitle");
  }

  /** `keep`: the viewer chose it, so the browser remembers it; a level set at start is not a choice. */
  setLevel(level, keep) {
    this.shade.style.setProperty("--river-shade", String(level.shade));
    for (const [id, b] of this.levelButtons) b.setAttribute("aria-pressed", String(id === level.id));
    if (keep) this.prefs.level = level;
  }

  setPaused(on, keep) {
    this.stage.paused = on;
    if (this.pauseButton) {
      this.pauseButton.setAttribute("aria-pressed", String(on));
      this.pauseButton.textContent = this.word(on ? "riverResume" : "riverPause");
    }
    if (keep) this.prefs.paused = on;
  }

  toggleSound() {
    const on = this.sound.toggle(this.scene);
    this.soundButton.setAttribute("aria-pressed", String(on));
  }

  listen() {
    const win = this.doc.defaultView;
    this.onMove = (e) => this.stage.onPointer("move", e);
    this.onDown = (e) => {
      this.dock.pressed(e.target);
      if (RiverBackground.isOpenWater(e.target, win)) this.stage.onPointer("down", e);
    };
    this.onUp = (e) => this.stage.onPointer("up", e);
    this.onLeave = (e) => this.stage.onPointer("leave", e);
    win.addEventListener("pointermove", this.onMove, { passive: true });
    win.addEventListener("pointerdown", this.onDown, { passive: true });
    win.addEventListener("pointerup", this.onUp, { passive: true });
    this.doc.documentElement.addEventListener("pointerleave", this.onLeave);
  }

  dispose() {
    const win = this.doc.defaultView;
    win.removeEventListener("pointermove", this.onMove);
    win.removeEventListener("pointerdown", this.onDown);
    win.removeEventListener("pointerup", this.onUp);
    this.doc.documentElement.removeEventListener("pointerleave", this.onLeave);
    this.sound.dispose();
    this.stage.dispose();
    this.dock.dispose();
    this.root.remove();
    this.shade.remove();
  }
}
