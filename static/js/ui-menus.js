// The parts' "⋯" menus come alive here (ui-parts.js, Menu), for every screen at once: one listener on the document, bound
// once by the page's entry. A menu opens by its button, and closes by its button again, by Escape (the focus back on its
// button), by a click anywhere outside it, and when one of its items is chosen — the item's own listener, the board's,
// runs as well: the menu only steps out of the way. One menu is open at a time.
//
// Escape that closes a menu is the menu's: no listener after this one sees it, and the cell window's own Escape stands
// aside while a menu is open over it (card-fold.js, FoldPeek.LAYERS) — a menu over a window closes before the window does.

export class UiMenus {
  static TOGGLE = "[data-ui-menu-toggle]";
  static LIST = ".ui-menu-list";

  constructor(doc) {
    this.doc = doc;
    this.bound = false;
  }

  bind() {
    if (this.bound || !this.doc?.addEventListener) return;
    this.bound = true;
    this.doc.addEventListener("click", (e) => this.onClick(e));
    this.doc.addEventListener("keydown", (e) => this.onKey(e));
  }

  /** The menus open now, each with its button. */
  open() {
    return [...(this.doc?.querySelectorAll?.(`${UiMenus.LIST}:not([hidden])`) || [])]
      .map((list) => ({ list, toggle: list.closest(".ui-menu")?.querySelector(UiMenus.TOGGLE) || null }));
  }

  show(list, toggle) {
    list.hidden = false;
    toggle?.setAttribute("aria-expanded", "true");
  }

  /** Close every open menu; the focus goes back to the button of the last one when `refocus`. */
  closeAll(refocus = false) {
    const open = this.open();
    for (const { list, toggle } of open) {
      list.hidden = true;
      toggle?.setAttribute("aria-expanded", "false");
    }
    if (refocus && open.length) open[open.length - 1].toggle?.focus?.();
    return open.length > 0;
  }

  onClick(e) {
    const target = e.target;
    const toggle = target?.closest?.(UiMenus.TOGGLE);
    if (toggle) {
      const list = toggle.closest(".ui-menu")?.querySelector(UiMenus.LIST);
      const wasOpen = list ? !list.hidden : false;
      this.closeAll();
      if (list && !wasOpen) this.show(list, toggle);
      return;
    }
    if (target?.closest?.(".ui-menu-item")) {
      this.closeAll();
      return;
    }
    if (!target?.closest?.(UiMenus.LIST)) this.closeAll();
  }

  onKey(e) {
    if (e.key !== "Escape") return;
    if (this.closeAll(true)) e.stopImmediatePropagation?.();
  }
}

export const UI_MENUS = new UiMenus(globalThis.document);
