/*
 * river-prefs.js: what a viewer chose for the brook behind the pages, kept in this browser.
 *
 * The brook is off until the viewer turns it on (the owner's decision, 2026-10-13), and then it
 * is there on every page until it is turned off again. How bright it is and whether it stands
 * still are kept too. The sound is not: a browser starts sound only from a click, so it is off on
 * every load.
 *
 * Storage may be refused (a private window, blocked site data). Then every read is the default
 * and every write is dropped: the pages work the same, they only forget the choice.
 */

/** How much of the brook shows through a page: the shade laid over it, and the word for it. */
export const RIVER_LEVELS = Object.freeze([
  Object.freeze({ id: "bright", key: "riverLevelBright", shade: 0.12 }),
  Object.freeze({ id: "soft", key: "riverLevelSoft", shade: 0.34 }),
  Object.freeze({ id: "dim", key: "riverLevelDim", shade: 0.56 }),
]);

/** Where each choice is kept. */
export const RIVER_KEYS = Object.freeze({ on: "riverOn", level: "riverLevel", paused: "riverPaused" });

export class RiverPrefs {
  /** `storage` is a Storage, or null when the browser gives none. */
  constructor(storage) { this.storage = storage; }
  /** The browser's localStorage, or none when it refuses even to be asked for. */
  static open() {
    try { return new RiverPrefs(window.localStorage); } catch (_) { return new RiverPrefs(null); }
  }
  read(key) {
    try { return this.storage ? this.storage.getItem(key) : null; } catch (_) { return null; }
  }
  write(key, value) {
    try { if (this.storage) this.storage.setItem(key, value); } catch (_) { /* refused: the choice lasts as long as this page */ }
  }
  /** Off unless this browser turned it on: anything else read back is off. */
  get on() { return this.read(RIVER_KEYS.on) === "1"; }
  set on(value) { this.write(RIVER_KEYS.on, value ? "1" : "0"); }
  /** The brightest level unless another was chosen; an unknown word read back is the default too. */
  get level() { return RIVER_LEVELS.find((l) => l.id === this.read(RIVER_KEYS.level)) || RIVER_LEVELS[0]; }
  set level(level) { this.write(RIVER_KEYS.level, level.id); }
  get paused() { return this.read(RIVER_KEYS.paused) === "1"; }
  set paused(value) { this.write(RIVER_KEYS.paused, value ? "1" : "0"); }
}
