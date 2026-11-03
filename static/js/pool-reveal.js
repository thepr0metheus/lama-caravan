// Routing follows a path that leads off the screen (the owner, 2026-10-18: "I hover a row whose cable leads to something
// beyond the edge of the screen, the cable on the left or on the right, it makes no difference: scroll what is beyond the screen
// into view by itself, smoothly").
//
// The cards a path touches stand in three columns (1.3.675: clients, what they call, models). Each column scrolls on its own, and across the board scrolls in its box on a
// window narrower than the columns. What lies beyond the edge of a column or of the box is not seen, and the lit path then ends at
// the edge. The board reads where the cards of the path stand (PoolBoard.reveal) and hands the rectangles over; this works out how
// far the box and each column must scroll, and the board does the scrolling. It decides over plain numbers, so the rule is told by
// values (scripts/test_js_pool_reveal.py).
//
// The rule, in four sentences. The card under the pointer stays where it is, and so does the column it stands in. What is already in
// view is left alone, even when more of the path lies out of it. What is out of view is brought in, the nearest column first, as much
// of it as fits, with clear room round it. The strip under the columns covers their foot, so what stands under it is out of view too.
export class PoolReveal {
  /** Clear room kept round what is brought in, px. */
  static MARGIN = 12;
  /** Of a tall card only its head counts, px: its name, and the dots the cables run to, stand there. */
  static HEAD = 56;
  /** How long the pointer rests on a card before the board follows its path, ms: a pointer passing over cards on its way elsewhere moves nothing. */
  static DELAY = 220;
  /** How long after the person's own scrolling the board leaves the scrolling alone, ms. */
  static QUIET = 700;
  /** How far the pointer must go, px, before it is moving again after the board scrolled under it. */
  static STEP = 4;
  /** The columns, left to right (the marks the columns' bodies carry, `data-pb-scroll`): a cable joins two neighbours. */
  static COLUMNS = ["clients", "pools", "models"];
  /** The kinds of node that are rows, one line high — a pool's row, a row of «Напрямую»; every other kind is a card. */
  static ROWS = new Set(["row", "direct"]);
  /** The kinds whose own cable leaves them going right: a client's, a pool's row's. */
  static RIGHT = new Set(["client", "row"]);

  /** The side a card's own cable leaves it by: a client's and a pool's row's go right, a model's comes from the left; a pool and a row of «Напрямую» have cables both ways. */
  static side(key) {
    const kind = String(key).split(":", 1)[0];
    return kind === "model" ? "left" : PoolReveal.RIGHT.has(kind) ? "right" : null;
  }

  /** What counts of a node's rectangle: the whole of a row, the head of a card. A node key is the board's own (PoolBoard.path). */
  static anchor(key, rect) {
    const kind = String(key).split(":", 1)[0];
    const bottom = PoolReveal.ROWS.has(kind) ? rect.bottom : Math.min(rect.bottom, rect.top + PoolReveal.HEAD);
    return { left: rect.left, right: rect.right, top: rect.top, bottom };
  }

  /**
   * How far to scroll: `dx` the box across, `dy[column]` each column's body up (negative) or down (positive); 0 and a missing
   * column mean no scrolling. The input is rectangles in the screen's own numbers —
   *   screen: {width, height}       the window the page stands in;
   *   box: {left, right}            the board's box across;
   *   floor: number | null          where the strip begins, which covers the columns' foot;
   *   hovered: {column, rect}       the card under the pointer;
   *   columns: {name: {top, bottom}}  each column's body, the room a card can be seen in;
   *   anchors: [{column, rect}]     the cards of the path, already cut to what counts (anchor());
   *   side: "left" | "right" | null  where the pointer's own cable goes (side()): of two columns as near, that one comes in first.
   */
  static plan({ screen, box, floor = null, hovered, columns, anchors, side = null }) {
    const m = PoolReveal.MARGIN, order = PoolReveal.COLUMNS, here = order.indexOf(hovered.column);
    const by = new Map();
    for (const a of anchors) {
      if (a.column === hovered.column || !order.includes(a.column)) continue;    // the pointer's own column is the person's
      if (!by.has(a.column)) by.set(a.column, []);
      by.get(a.column).push(a.rect);
    }
    const hop = (c) => Math.abs(order.indexOf(c) - here), own = (c) => ((order.indexOf(c) < here ? "left" : "right") === side ? 0 : 1);
    const near = [...by.keys()].sort((p, q) => hop(p) - hop(q) || own(p) - own(q) || order.indexOf(p) - order.indexOf(q));

    // Across: the nearest columns first, each as a whole if it fits with what is taken; the card under the pointer must stay in view
    // with them, but it is not chased: with nothing taken, or with what is taken already in view, the box stays.
    const left = Math.max(box.left, 0) + m, right = Math.min(box.right, screen.width) - m, wide = right - left;
    let lo = Infinity, hi = -Infinity;
    for (const column of near) {
      const rects = by.get(column);
      const l = Math.min(lo, ...rects.map((r) => r.left)), h = Math.max(hi, ...rects.map((r) => r.right));
      if (Math.max(h, hovered.rect.right) - Math.min(l, hovered.rect.left) <= wide) { lo = l; hi = h; }
    }
    const dx = lo === Infinity ? 0 : lo < left ? lo - left : hi > right ? hi - right : 0;

    // Up and down, column by column: what is nearest to the room is taken first, then what fits with it.
    const dy = {};
    for (const column of near) {
      const body = columns[column];
      if (!body) continue;
      const top = Math.max(body.top, 0) + m, bottom = Math.min(body.bottom, screen.height, floor ?? Infinity) - m, room = bottom - top;
      if (!(room > 0)) continue;
      const gap = (r) => (r.top < top ? top - r.top : r.bottom > bottom ? r.bottom - bottom : 0);
      const rects = by.get(column).slice().sort((p, q) => gap(p) - gap(q) || p.top - q.top);
      let a = null, b = null;
      for (const r of rects) {
        const l = a === null ? r.top : Math.min(a, r.top), h = b === null ? r.bottom : Math.max(b, r.bottom);
        if (a === null || h - l <= room) { a = l; b = h; }
      }
      if (b - a > room) b = a + room;                                            // taller than the room: its top is what is shown
      const d = a < top ? a - top : b > bottom ? b - bottom : 0;
      if (d) dy[column] = Math.round(d);
    }
    return { dx: Math.round(dx), dy };
  }

  /** Whether the pointer has gone from `place` far enough to be moving: what scrolls past a still pointer is not pointed at. */
  static moved(place, x, y) {
    return Math.hypot((Number(x) || 0) - place.x, (Number(y) || 0) - place.y) >= PoolReveal.STEP;
  }
}
