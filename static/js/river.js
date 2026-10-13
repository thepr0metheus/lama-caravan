/*
 * river.js: the switch of the brook behind the pages. Every page loads it; it puts one button in
 * the page's header, before the tour, and the button turns the brook on and off. The button stands
 * in a group of its own: while the brook runs, the dock's ▾ joins it there (river-dock.js).
 *
 * Off is the default (the owner's decision, 2026-10-13) and off means off: no canvas, no WebGL,
 * no sound, and the brook's code is not even downloaded until the first time it is turned on.
 * The choice is kept in this browser (river-prefs.js), so the brook is there, or not, on every
 * page alike.
 *
 * Words come from the shared dictionary through i18n-data.js, not i18n.js: /hf does not load the
 * shared i18n module (it keeps its own table), and i18n.js would bring half of the board with it.
 */
import { RiverPrefs } from "./river-prefs.js";

export class RiverSwitch {
  /**
   * doc: the page. prefs: a RiverPrefs. load(): brings in river-background.js; words(): brings in
   * i18n-data.js. A test hands in its own of each.
   */
  constructor(doc, prefs, {
    load = () => import("./river-background.js"),
    words = () => import("./i18n-data.js"),
  } = {}) {
    this.doc = doc;
    this.prefs = prefs;
    this.load = load;
    this.loadWords = words;
    this.on = prefs.on;
    this.group = null;      // the switch's place in the header; the dock hangs from it
    this.button = null;
    this.label = null;
    this.background = null;
    this.starts = 0;        // starts and stops are counted: a start whose code lands after either is dropped
    this.dict = null;       // i18n-data.js once it is here
    this.code = "en";
  }

  /** Puts the button in the header. A page without a header gets no brook: returns false. */
  mount() {
    const actions = this.doc.querySelector(".topbar .actions");
    if (!actions) return false;
    const b = this.doc.createElement("button");
    b.type = "button";
    b.className = "river-toggle";
    b.dataset.t = "header-river-toggle";
    const icon = this.doc.createElement("span");
    icon.className = "river-toggle-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "〰";
    const label = this.doc.createElement("span");
    label.className = "river-toggle-label";
    label.dataset.i18n = "riverToggle";
    b.append(icon, label);
    b.addEventListener("click", () => this.toggle());
    const group = this.doc.createElement("span");
    group.className = "river-switch";
    group.append(b);
    actions.insertBefore(group, actions.querySelector("[data-ob-tour]") || actions.querySelector("#langSelect") || null);
    this.group = group;
    this.button = b;
    this.label = label;
    this.render();
    if (this.on) this.start();
    return true;
  }

  /** Brings in the dictionary and the stored language, then names everything in it. */
  async learnWords() {
    this.dict = await this.loadWords();
    this.code = await this.dict.loadLanguage(this.dict.storedLanguage());
    this.render();
    if (this.background) this.background.relabel();
  }

  /** The word for `key` in the page's language. Until the dictionary is here there is no word
   *  yet, not a stand-in: the button shows its icon alone for that moment. */
  word(key) { return this.dict ? this.dict.translate(this.code, key) : ""; }

  toggle() {
    this.on = !this.on;
    this.prefs.on = this.on;
    if (this.on) this.start(); else this.stop();
    this.render();
  }

  async start() {
    const mine = ++this.starts;
    this.doc.documentElement.classList.add("river-on");
    const { RiverBackground } = await this.load();
    if (mine !== this.starts) return;   // the brook went off, or off and on again, while its code was on the way
    this.background = new RiverBackground(this.doc, this.prefs, (key) => this.word(key), this.group);
  }

  stop() {
    this.starts++;
    this.doc.documentElement.classList.remove("river-on");
    if (this.background) this.background.dispose();
    this.background = null;
  }

  render() {
    const b = this.button;
    if (!b) return;
    b.dataset.tState = this.on ? "on" : "off";
    b.setAttribute("aria-pressed", String(this.on));
    b.title = this.word(this.on ? "riverToggleOnTitle" : "riverToggleOffTitle");
    this.label.textContent = this.word("riverToggle");
  }
}

// One switch per page. The words arrive on their own; a page that switches its language says so
// with "caravan:langchange" (i18n.js applyLanguage), and the switch names everything again.
const riverSwitch = new RiverSwitch(document, RiverPrefs.open());
if (riverSwitch.mount()) {
  riverSwitch.learnWords().catch((err) => console.warn("river: no words", err));
  window.addEventListener("caravan:langchange", () => riverSwitch.learnWords().catch(() => { /* keeps the last words */ }));
}
