// The bar's list of machines, on every page: a button that opens the machines connected to the caravan, each a link to its own
// page (the owner, 2026-10-29: "and buttons to all the connected machines, by a drop-down list is fine"). The bar is one template
// (scripts/gen_header.py), and a page's own script starts this class: /hf, which does not load the shared dictionary, hands in
// its own table, which holds these keys with the same words.
//
// The list is read when the button is pressed, each time: a machine connected a moment ago is in it, and a page that nobody opens
// the list on asks nothing. What is not known is said: while it reads, when it failed and why, when there are no machines.
import { BoardView } from "./board-view.js";
import { escapeHtml } from "./utils.js";

export class HeaderMachines {
  constructor({ doc = globalThis.document, get, words, view = new BoardView() } = {}) {
    this.doc = doc;
    this.get = get;       // (url) → a promise of the parsed answer; it throws when the controller refuses
    this.words = words;   // (key, values) → the words in the page's language
    this.view = view;     // where this page stands: its machine's row and the button say so
    this.asked = 0;       // the newest reading: an older one that lands later says nothing
    this.box = this.button = this.menu = null;
  }

  // Binds once; false on a page whose bar has no list (a test's bare page).
  bind() {
    const $ = (id) => this.doc?.getElementById?.(id);
    this.box = $("headerMachines");
    this.button = $("headerMachinesBtn");
    this.menu = $("headerMachinesMenu");
    if (!this.box || !this.button || !this.menu) return false;
    if (this.view.isMachine) this.button.setAttribute("aria-current", "page");
    this.button.addEventListener("click", (event) => {
      event.stopPropagation();
      return this.menu.hidden ? this.open() : this.close();
    });
    // Capture phase, as the account menu's: the board's delegated click router stops most clicks before a bubbling listener sees them.
    this.doc.addEventListener("click", (event) => { if (!this.box.contains(event.target)) this.close(); }, true);
    this.doc.addEventListener("keydown", (event) => { if (event.key === "Escape" && !this.menu.hidden) this.close(); });
    return true;
  }

  close() {
    this.menu.hidden = true;
    this.button.setAttribute("aria-expanded", "false");
  }

  async open() {
    this.menu.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
    const asked = ++this.asked;
    this.menu.innerHTML = this.noteHtml(this.words("headerMachinesReading"));
    const html = await this.get("/api/machines").then((answer) => this.listHtml(answer),
      (err) => this.noteHtml(this.words("headerMachinesFailed", { error: err?.message || String(err) })));
    if (asked === this.asked) this.menu.innerHTML = html;
  }

  noteHtml(words) {
    return `<div class="topbar-machines-note" data-t="header-machines-note">${escapeHtml(words)}</div>`;
  }

  // An answer with no list is not "no machines": that says the fleet is empty, and it may be nothing of the kind.
  listHtml(answer) {
    if (!Array.isArray(answer?.machines)) return this.noteHtml(this.words("headerMachinesFailed", { error: "no list in the answer" }));
    if (!answer.machines.length) return this.noteHtml(this.words("headerMachinesNone"));
    return answer.machines.map((machine) => this.rowHtml(machine)).join("");
  }

  rowHtml({ id, name, online }) {
    const key = String(id);
    const here = this.view.machine === key ? ' aria-current="page"' : "";
    const off = online ? "" : `<span class="topbar-machine-off">${escapeHtml(this.words("headerMachineOff"))}</span>`;
    return `<a class="topbar-machine" role="menuitem" href="${escapeHtml(BoardView.url(key))}" data-t="header-machine" data-t-id="${escapeHtml(key)}"${here}>`
      + `<span class="topbar-machine-dot${online ? " on" : ""}" aria-hidden="true"></span><span>${escapeHtml(String(name || key))}</span>${off}</a>`;
  }
}
