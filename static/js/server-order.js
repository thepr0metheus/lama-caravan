// The order of the cards under Model servers: machines and cloud providers in one list.
import { t } from "./i18n.js";
import { api, escapeHtml, toast } from "./utils.js";

/**
 * Under Model servers the board drew its machines first and its cloud providers after
 * them, always: two lanes, one above the other. Since 2026-10-04 the cards stand in one
 * list in the operator's order — a machine below the subscription pool, or between two
 * providers. The order is kept on the controller (POST /api/topology/server-order, read
 * back as topology.layout), so every browser and account sees the same board, and the
 * kanban's Servers panel follows it.
 *
 * The two lanes stay two containers: every binding and test of a lane addresses its own.
 * The list they make is one CSS flex column over both (`display: contents` takes their
 * boxes away), and a card's place is its `order`. A card the stored list names stands at
 * its index; a card it does not name — a new machine, a new provider, every card while
 * nothing is stored — stands after them, in the order the lanes draw them: the machines
 * as their scouts came, then the cloud. One rule, `rank`, places the board's cards and
 * the kanban's groups.
 *
 * A card moves by the ↑ and ↓ buttons first in its head, one place a click; the page
 * scrolls with the card, so the button stays under the pointer and a few clicks walk a card
 * down a long list. The cards were dragged at first, and the operator could not reach a
 * place a screen away — neither a wheel nor a trackpad scrolls while the browser drags —
 * so the drag went and the buttons stayed (2026-10-04, the operator: "the arrows are enough").
 *
 * Named deviation: Tab and a screen reader follow the DOM — the machines, then the cloud
 * — and not the order on screen. Moving the cards in the DOM would take them out of the
 * lanes whose listeners and tests address them.
 */
export class ServerOrder {
  // The kinds of card the list holds: a machine (its node) and a cloud provider or pool (its account).
  static KINDS = ["node", "cloud"];

  static key(kind, id) { return `${kind}:${id}`; }

  // What the controller sent, as a list the board can place by: distinct strings that name a
  // kind and an id. Anything else — a document edited by hand, an older controller — is no
  // order at all, never a guess at one.
  static clean(value) {
    if (!Array.isArray(value)) return [];
    const seen = new Set();
    return value.filter((key) => typeof key === "string" && !seen.has(key)
      && ServerOrder.KINDS.some((kind) => key.startsWith(`${kind}:`) && key.length > kind.length + 1)
      && !!seen.add(key));
  }

  static same(a, b) { return a.length === b.length && a.every((key, i) => key === b[i]); }

  // `keys` with `key` moved next to `target` — after it, or before it. Null when the move
  // changes nothing or names a key the list does not have.
  static moved(keys, key, target, after) {
    if (!keys.includes(key) || key === target || !keys.includes(target)) return null;
    const rest = keys.filter((k) => k !== key);
    const at = rest.indexOf(target) + (after ? 1 : 0);
    const next = [...rest.slice(0, at), key, ...rest.slice(at)];
    return ServerOrder.same(next, keys) ? null : next;
  }

  // `keys` with `key` one place down, or up. Null at the end it would leave.
  static stepped(keys, key, down) {
    return ServerOrder.moved(keys, key, keys[keys.indexOf(key) + (down ? 1 : -1)], down);
  }

  constructor({
    post = (order) => api("/api/topology/server-order", { method: "POST", body: JSON.stringify({ order }) }),
    redraw = () => {},
    scroll = (dy) => globalThis.scrollBy?.({ top: dy, behavior: "instant" }),
  } = {}) {
    this.post = post;
    this.redraw = redraw;   // cards stand elsewhere now: the cables that end on them follow
    this.scroll = scroll;   // the page's scrolling: a parameter, so a step can be checked without a window
    // What the controller holds, as far as this page knows, and its revision. A reading
    // older than the last answer is a poll that left before a save: it must not put the
    // old order back on the screen.
    this.held = { order: [], rev: -1 };
    // An order on screen ahead of the controller: from the click until the save answers.
    this.shown = null;
    this.wanted = null;   // the newest order not sent yet, while a save is on its way
    this.busy = false;
    this.sending = null;
  }

  /** Takes the order a topology carries; true when the order on screen changes. */
  read(topology) {
    const layout = topology?.layout || {};
    const rev = Number.isInteger(layout.serverOrderRev) ? layout.serverOrderRev : 0;
    if (rev < this.held.rev) return false;
    const before = this.current();
    this.held = { order: ServerOrder.clean(layout.serverOrder), rev };
    return !ServerOrder.same(before, this.current());
  }

  current() { return this.shown || this.held.order; }

  /** Where the card `key` stands: its index in the order, or after every card the order names. */
  rank(key) {
    const order = this.current();
    const at = order.indexOf(key);
    return at < 0 ? order.length : at;
  }

  /** `items` in the order on screen: by rank, and in their own order among equals. */
  sorted(items, keyOf) {
    return items.map((item, i) => ({ item, rank: this.rank(keyOf(item)), i }))
      .sort((a, b) => a.rank - b.rank || a.i - b.i).map(({ item }) => item);
  }

  /** The attributes a card's root carries: its key, and its place. */
  attrs(key) { return ` data-server-card="${escapeHtml(key)}" style="order:${this.rank(key)}"`; }

  /** What a card is moved by, first in its head: ↑ and ↓, one place a click. */
  controls(key, name) {
    const k = escapeHtml(key);
    const words = { name: String(name ?? "") };
    const up = escapeHtml(t("serverOrderUp", words)), down = escapeHtml(t("serverOrderDown", words));
    return `<span class="server-order">`
      + `<button type="button" class="server-step" data-server-step="up" data-t="server-step-up" data-t-id="${k}" title="${up}" aria-label="${up}">↑</button>`
      + `<button type="button" class="server-step" data-server-step="down" data-t="server-step-down" data-t-id="${k}" title="${down}" aria-label="${down}">↓</button>`
      + `</span>`;
  }

  /** Puts every card under `root` in its place, and says where the list ends: the first card's ↑
   *  and the last card's ↓ have nowhere to go. True when a card moved. */
  apply(root = globalThis.document) {
    let moved = false;
    const cards = [...(root?.querySelectorAll?.("[data-server-card]") || [])];
    cards.forEach((card) => {
      const order = String(this.rank(card.dataset.serverCard));
      if (card.style.order !== order) {
        card.style.order = order;
        moved = true;
      }
    });
    const keys = this.sorted(cards.map((card) => card.dataset.serverCard), (key) => key);
    cards.forEach((card) => {
      const key = card.dataset.serverCard;
      const up = card.querySelector?.('[data-server-step="up"]'), down = card.querySelector?.('[data-server-step="down"]');
      if (up) up.disabled = key === keys[0];
      if (down) down.disabled = key === keys[keys.length - 1];
    });
    return moved;
  }

  /** The keys of the cards under `root`, in the order on screen. */
  onScreen(root) {
    const keys = [...(root?.querySelectorAll?.("[data-server-card]") || [])].map((card) => card.dataset.serverCard);
    return this.sorted(keys, (key) => key);
  }

  /** Shows `order` at once and sends it. While a save is on its way, the newest order waits for it. */
  save(order) {
    this.shown = order;
    this.wanted = order;
    this.show();
    if (!this.busy) {
      this.busy = true;
      this.sending = this.send();
    }
    return this.sending;
  }

  async send() {
    try {
      while (this.wanted) {
        const order = this.wanted;
        this.wanted = null;
        const answer = await this.post(order);
        this.held = { order: ServerOrder.clean(answer?.order), rev: Number.isInteger(answer?.rev) ? answer.rev : this.held.rev };
      }
    } catch (err) {
      // Refused (a viewer account, a lost connection): the cards go back to what the controller holds.
      this.wanted = null;
      toast(err.message);
    } finally {
      // Every way out lets the page save again and shows what the controller holds.
      this.busy = false;
      this.shown = null;
      this.show();
    }
  }

  show() { if (this.apply()) this.redraw(); }

  /** ↑ or ↓ in a card's head: the card moves one place, and the page scrolls with it, so the
   *  button stays under the pointer for the next click. */
  async step(event) {
    const button = event.target.closest?.("[data-server-step]");
    if (!button) return false;
    event.stopPropagation();   // the head under the button opens and folds nothing
    const key = button.closest("[data-server-card]")?.dataset.serverCard;
    const next = ServerOrder.stepped(this.onScreen(event.currentTarget), key, button.dataset.serverStep === "down");
    if (!next) return true;
    const before = button.getBoundingClientRect().top;
    const saving = this.save(next);   // on screen at once
    const moved = button.getBoundingClientRect().top - before;
    if (moved) this.scroll(moved);
    await saving;
    return true;
  }

  /** Listens on the list once: the lanes inside it are drawn over and over, the list is not. */
  bind(root) {
    if (!root || root.dataset.serverOrderBound) return;
    root.dataset.serverOrderBound = "1";
    root.addEventListener("click", (event) => { this.step(event); });
  }
}

export const SERVER_ORDER = new ServerOrder();
