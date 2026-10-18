/*
 * river-dock.js: the brook's settings under the header's switch: how bright, pause, sound.
 *
 * While the brook runs a small ▾ joins the switch, and it opens and closes the dock. The dock
 * hangs under the header, not over the page: fixed at the bottom of the window it covered the
 * end of the lists on /hf and /routing and sat on /hf's own dock. It follows its ▾ in the page's
 * order, so Tab goes from the ▾ into it; a press anywhere else, or Escape, closes it.
 *
 * The dock only opens, closes and names itself; what its buttons do is river-background.js's.
 */
export class RiverDock {
  /** How close to the window's edge the dock may come, in CSS pixels. */
  static MARGIN = 8;

  /** doc: the page. host: the switch's group in the header. word(key): the page's word for a key. */
  constructor(doc, host, word) {
    this.doc = doc;
    this.word = word;
    this.button = doc.createElement("button");
    this.button.type = "button";
    this.button.className = "river-more";
    this.button.dataset.t = "header-river-settings";
    this.button.setAttribute("aria-controls", "riverDock");
    const arrow = doc.createElement("span");
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "▾";
    this.button.append(arrow);
    this.panel = doc.createElement("div");
    this.panel.id = "riverDock";
    this.panel.className = "river-dock";
    this.panel.dataset.t = "river-dock";
    this.panel.setAttribute("role", "group");
    host.append(this.button, this.panel);
    this.button.addEventListener("click", () => (this.open ? this.close() : this.show()));
    this.onKey = (e) => {
      if (e.key !== "Escape" || !this.open) return;
      this.close();
      this.button.focus();
    };
    this.onResize = () => { if (this.open) this.place(); };
    doc.addEventListener("keydown", this.onKey);
    doc.defaultView.addEventListener("resize", this.onResize);
    this.close();
  }

  get open() { return !this.panel.hidden; }

  show() {
    this.panel.hidden = false;
    this.mark(true);
    this.place();
  }

  close() {
    this.panel.hidden = true;
    this.mark(false);
  }

  mark(open) {
    this.button.setAttribute("aria-expanded", String(open));
    this.button.dataset.tState = open ? "open" : "closed";
  }

  /** river-background.js reports every press on the page: one outside the dock and its ▾ closes it.
   *  A press on the ▾ is left to the ▾'s own click, which closes an open dock itself. */
  pressed(target) {
    if (this.open && !this.panel.contains(target) && !this.button.contains(target)) this.close();
  }

  /** Under its ▾, right edges level; on a narrow screen the dock moves right to stay whole. */
  place() {
    this.panel.style.right = "0px";
    const short = RiverDock.MARGIN - this.panel.getBoundingClientRect().left;
    if (short > 0) this.panel.style.right = `${-short}px`;
  }

  /** The ▾'s face is only an arrow, so its word is its name; the dock is named by its own. */
  relabel() {
    const name = this.word("riverSettings");
    this.button.setAttribute("aria-label", name);
    this.button.title = name;
    this.panel.setAttribute("aria-label", this.word("riverDockLabel"));
  }

  dispose() {
    this.doc.removeEventListener("keydown", this.onKey);
    this.doc.defaultView.removeEventListener("resize", this.onResize);
    this.button.remove();
    this.panel.remove();
  }
}
