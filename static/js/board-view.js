// Which board a page shows (the owner, 2026-10-11): the main board — the clients, the pools, and
// every machine as its load at a glance — or one machine in a window of its own, opened from that
// glance: its servers, engines, models and cells, the card the main board used to show whole.
//
// Both are index.html: the machine's window needs every dialog, form and listener the card had
// on the main board, and a page of its own would have to carry them all a second time. The path
// tells them apart — /board, or /machine?host=<id> — and `data-board-view` on <html> lets the
// styles show each one its own parts (`main#topologyView` has a `data-view` of its own).

export class BoardView {
  static PATH = "/machine";
  static PARAM = "host";

  /** `loc`: where the page stands (`location`), a parameter so a test needs no window. */
  constructor(loc = globalThis.location) {
    const onMachinePath = String(loc?.pathname || "") === BoardView.PATH;
    const id = new URLSearchParams(String(loc?.search || "")).get(BoardView.PARAM);
    // The machine this window shows; "" when the window names none — a window for nothing,
    // said so on the page, not the main board in disguise. null on the main board.
    this.machine = onMachinePath ? String(id || "").trim() : null;
  }

  get isMachine() { return this.machine !== null; }

  get name() { return this.isMachine ? "machine" : "main"; }

  /** The address of a machine's window. */
  static url(hostId) { return `${BoardView.PATH}?${BoardView.PARAM}=${encodeURIComponent(String(hostId))}`; }

  /** The window's name: one window a machine, so a second click brings it forward. */
  static windowName(hostId) { return `caravan-machine-${String(hostId).replace(/[^\w-]/g, "_")}`; }

  /** Says on <html> which board this is, for the styles. */
  mark(root = globalThis.document?.documentElement) {
    if (root?.dataset) root.dataset.boardView = this.name;
  }

  /** Opens a machine's window, or brings it forward. False when the browser refused a window:
   *  the link then opens the address the usual way. `open` is `window.open`, a parameter so a
   *  test needs no browser. */
  static open(hostId, open = globalThis.open) {
    const win = typeof open === "function"
      ? open(BoardView.url(hostId), BoardView.windowName(hostId), "popup=yes,width=1180,height=920") : null;
    if (!win) return false;
    win.focus?.();
    return true;
  }
}

export const BOARD_VIEW = new BoardView();
