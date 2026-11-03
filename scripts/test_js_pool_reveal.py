#!/usr/bin/env python3
"""Actual pool-reveal.js: how far Routing scrolls to follow a path that leads off the screen (1.3.592).

The owner, 2026-10-18: "I hover a row whose cable leads to something beyond the edge of the screen, the cable on the left or on the
right, it makes no difference: scroll what is beyond the screen into view by itself, smoothly." The path of a card (PoolBoard.path)
touches cards in three columns (1.3.675: clients, what they call, models); each column scrolls on its own, and across the board scrolls in its box on a window narrower than the
columns. The board reads the places of the cards and hands the rectangles to PoolReveal.plan, which says how far to scroll; the board
does the scrolling (scripts/test_js_pool_board.py pins that half).

The screen of these pins is 1440 x 800, the columns' bodies stand at 120..760, and the strip over their foot begins at 604, so a card
is in view when it stands between 132 and 592 (a margin of 12 inside the strip's edge). Pinned, by value, each with its negative:
  - what counts of a card: the head of a card, the whole of a row;
  - up and down: a card below the room is brought up to its margin, one above is brought down, one under the strip is out of view too
    (and without a strip it is not), a card inside the margin is moved only that far, a card in view is left alone;
  - what to take when there are several: what fits together comes in together, what does not fit is left when one card is in view,
    and the nearest is taken when none is; a card taller than the room shows its top; no room, no move;
  - the pointer's own column is never scrolled, and a column of the path with no body is skipped;
  - across: a card beyond the right edge brings the box left, beyond the left edge right; the nearest columns come in first and the
    ones that do not fit with them stay out; the card under the pointer is kept in view, and is not chased when nothing else is taken.

Run: python3 scripts/test_js_pool_reveal.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const { PoolReveal: M } = await import(pathToFileURL(process.env.JS_ROOT + "/pool-reveal.js").href);
const reset = () => {};
const R = (left, top, width = 200, height = 30) => ({ left, top, right: left + width, bottom: top + height });
const body = { top: 120, bottom: 760 };
const COL = { clients: body, pools: body, models: body };
const plan = (over = {}) => M.plan({ screen: { width: 1440, height: 800 }, box: { left: 0, right: 1440 }, floor: 604, hovered: { column: "pools", rect: R(740, 300) }, columns: COL, anchors: [], ...over });
const at = (column, rect) => ({ column, rect });
const narrow = { screen: { width: 1000, height: 800 }, box: { left: 0, right: 1000 } };
"""

PINS = [
    ("constants",
     "",
     "[M.MARGIN, M.HEAD, M.DELAY, M.QUIET, M.STEP, M.COLUMNS.join(','), [...M.ROWS].sort().join(',')]",
     '[12,56,220,700,4,"clients,pools,models","direct,row"]',
     "the numbers the board's pins lean on: a margin of 12 px, a head of 56 px, a rest of 220 ms, a quiet of 700 ms after the person's scrolling, "
     "4 px for a moving pointer, the three columns left to right, and two kinds of row: a pool's, and a row of «Напрямую»"),
    ("anchor_head_of_a_card_whole_row",
     "",
     "(() => { const tall = { left: 1, right: 2, top: 100, bottom: 900 }, low = { left: 1, right: 2, top: 100, bottom: 130 };"
     " return [...['pool:p', 'set:s', 'client:1', 'model:acc:a/b'].map((k) => M.anchor(k, tall).bottom), ...['row:p/r', 'direct:live:mm:x'].map((k) => M.anchor(k, tall).bottom),"
     " M.anchor('client:1', low).bottom, M.anchor('pool:p', tall)]; })()",
     '[156,156,156,156,900,900,130,{"left":1,"right":2,"top":100,"bottom":156}]',
     "of a tall card only its head counts (100 + 56), of a row — a pool's, a row of «Напрямую» — the whole of it, whatever its height; negative: a card shorter than "
     "a head keeps its own height; a set's key (no sets since 1.3.675) is no row"),
    ("all_in_view",
     "",
     "plan({ anchors: [at('clients', R(50, 250)), at('models', R(1080, 300))] })",
     '{"dx":0,"dy":{}}',
     "everything the path touches is in view: nothing scrolls"),
    ("below_the_room",
     "",
     "plan({ anchors: [at('models', R(1080, 650))] })",
     '{"dx":0,"dy":{"models":88}}',
     "a card whose foot (680) is below the room's foot (592) is brought up by the difference, 88, and only its column moves"),
    ("above_the_room",
     "",
     "plan({ anchors: [at('models', R(1080, 40))] })",
     '{"dx":0,"dy":{"models":-92}}',
     "a card above the room's top (132) is brought down: the column scrolls up (negative) by 92"),
    ("under_the_strip_is_out_of_view",
     "",
     "[plan({ anchors: [at('models', R(1080, 560, 200, 60))] }), plan({ floor: null, anchors: [at('models', R(1080, 560, 200, 60))] })]",
     '[{"dx":0,"dy":{"models":28}},{"dx":0,"dy":{}}]',
     "the strip covers the columns' foot from 604: a card at 560..620 is lifted clear of it (28); negative: with no strip the same card is in view and stays"),
    ("margin_counts",
     "",
     "[plan({ anchors: [at('models', R(1080, 125))] }), plan({ anchors: [at('models', R(1080, 132))] }), plan({ anchors: [at('models', R(1080, 562))] })]",
     '[{"dx":0,"dy":{"models":-7}},{"dx":0,"dy":{}},{"dx":0,"dy":{}}]',
     "a card 7 px inside the column's top is within the margin and is moved 7; negative: a card exactly on the margin (132..162, 562..592) is in view and stays"),
    ("pointers_own_column_is_never_scrolled",
     "",
     "plan({ anchors: [at('pools', R(740, 2000)), at('models', R(1080, 300))] })",
     '{"dx":0,"dy":{}}',
     "a card of the path in the pointer's own column — here far below — moves nothing: that column is the person's (negative: a card in another column would)"),
    ("two_fit_together",
     "",
     "plan({ anchors: [at('models', R(1080, 560)), at('models', R(1080, 620))] })",
     '{"dx":0,"dy":{"models":58}}',
     "two cards of a column that fit in the room together come in together: one in view (560..590), one out (620..650): the column moves 58 to take both"),
    ("far_apart_one_in_view_is_left_alone",
     "",
     "plan({ anchors: [at('models', R(1080, 300)), at('models', R(1080, 1500))] })",
     '{"dx":0,"dy":{}}',
     "two cards that do not fit together, one of them in view: the one in view stays and the column is not disturbed for the far one"),
    ("far_apart_both_out_the_nearest",
     "",
     "plan({ anchors: [at('models', R(1080, 1800)), at('models', R(1080, 850))] })",
     '{"dx":0,"dy":{"models":288}}',
     "two cards that do not fit together, neither in view: the nearer one (850..880, 288 under the room) is brought in, whatever the order they come in"),
    ("taller_than_the_room_shows_its_top",
     "",
     "plan({ anchors: [at('models', R(1080, 900, 200, 800))] })",
     '{"dx":0,"dy":{"models":768}}',
     "a card taller than the room (800 against 460) is brought in by its top: it lands at the room's top, 132 (900 - 768)"),
    ("no_room_no_move",
     "",
     "[plan({ floor: 130, anchors: [at('models', R(1080, 1500))] }), plan({ columns: { ...COL, models: undefined }, anchors: [at('models', R(1080, 1500))] }), plan({ ...narrow, anchors: [at('nowhere', R(1080, 300, 260))] })]",
     '[{"dx":0,"dy":{}},{"dx":0,"dy":{}},{"dx":0,"dy":{}}]',
     "a strip that leaves no room above it, a column that has no body on the screen, a column nobody knows (not even across): nothing to scroll, and no crash"),
    ("each_column_by_itself",
     "",
     "[plan({ anchors: [at('clients', R(50, 700)), at('models', R(1080, 40))] }), plan({ anchors: [at('clients', R(50, 700)), at('models', R(1080, 300))] })]",
     '[{"dx":0,"dy":{"clients":138,"models":-92}},{"dx":0,"dy":{"clients":138}}]',
     "every column is worked out on its own: the client below the room comes up 138 (730 - 592), the model above it comes down 92; negative: a model in view stays"),
    ("rounds_to_whole_pixels",
     "",
     "[plan({ anchors: [at('models', R(1080, 650.4))] }), plan({ ...narrow, anchors: [at('models', R(1080.4, 300, 260))] })]",
     '[{"dx":0,"dy":{"models":88}},{"dx":352,"dy":{}}]',
     "a fraction of a pixel is rounded, up and down (88.4 -> 88) and across (352.4 -> 352): the scroll is a whole number"),
    ("across_to_the_right",
     "",
     "plan({ ...narrow, anchors: [at('models', R(1080, 300, 260))] })",
     '{"dx":352,"dy":{}}',
     "the window is narrower than the columns: a card beyond the right edge (1080..1340 on a window of 1000) brings the box left by 352, so that its right edge stands at 988"),
    ("across_to_the_left",
     "",
     "plan({ ...narrow, hovered: { column: 'pools', rect: R(500, 300) }, anchors: [at('clients', R(-100, 300, 140))] })",
     '{"dx":-112,"dy":{}}',
     "a card beyond the left edge (-100..40) brings the box right (negative): by 112, to the margin at 12"),
    ("across_neighbours_come_together",
     "",
     "plan({ ...narrow, anchors: [at('models', R(1080, 300, 260)), at('clients', R(390, 300, 280))] })",
     '{"dx":352,"dy":{}}',
     "the client beside the pool and the model beside it come in together with the card under the pointer (390..1340 fits in 976): the box moves 352"),
    ("across_nearest_columns_first",
     "",
     "plan({ ...narrow, hovered: { column: 'clients', rect: R(20, 300, 280) }, anchors: [at('models', R(1080, 300, 260)), at('pools', R(390, 300, 280))] })",
     '{"dx":0,"dy":{}}',
     "pointed at a client: the pool beside it is taken first and fits with it (20..670); the model, two columns away, would not fit with them (20..1340, 1320) and "
     "stays out — the nearest columns are taken first, whatever order they come in — and with the pool in view the box does not move"),
    ("across_what_does_not_fit_stays_out",
     "",
     "plan({ ...narrow, anchors: [at('clients', R(-60, 300, 280)), at('models', R(1080, 300, 260))] })",
     '{"dx":352,"dy":{}}',
     "the client (-60..220) would make 1000 with the card under the pointer (740..940) and stays out, though it comes first; the model fits with it and comes in (352)"),
    ("across_prefers_the_side_of_the_cable",
     "",
     "(() => { const hovered = { column: 'pools', rect: R(667, 144, 327) }, anchors = [at('clients', R(200, 144, 300)), at('models', R(1071, 179, 335))], w = { screen: { width: 1100, height: 800 }, box: { left: 0, right: 1100 } };"
     " return ['right', 'left', null].map((side) => plan({ ...w, hovered, anchors, side }).dx); })()",
     "[318,0,0]",
     "the window is 1100 and the client on the left and the model on the right do not fit together with the pool's row (200..1406 against 1076): the row's own cable goes "
     "right, so the model comes in (318) and the client stays; negative: for a card whose cable goes left, or that has cables both ways, the client (the left one) comes in "
     "first and the box stays"),
    ("side_of_a_card",
     "",
     "['row:p/r', 'client:1', 'model:acc:a/b', 'direct:live:mm:x', 'pool:p', 'setpool:s/p', 'set:s', 'nonsense'].map((k) => M.side(k))",
     '["right","right","left",null,null,null,null,null]',
     "the side a card's own cable leaves it by: a pool's row and a client go right, a model's comes from the left; a pool and a row of «Напрямую» have cables on both "
     "sides; a set's keys (no sets since 1.3.675) and a key nobody knows, none"),
    ("across_all_inside_nothing",
     "",
     "[plan({ ...narrow, anchors: [at('clients', R(400, 300)), at('models', R(800, 300, 180))] }), plan({ anchors: [at('models', R(1080, 300, 260))] })]",
     '[{"dx":0,"dy":{}},{"dx":0,"dy":{}}]',
     "everything in the window: the box stays, and with a window as wide as the columns a card at 1340 is in view too"),
    ("across_pointers_card_is_kept_but_not_chased",
     "",
     "[plan({ ...narrow, hovered: { column: 'pools', rect: R(800, 300, 280) } }), plan({ ...narrow, hovered: { column: 'pools', rect: R(800, 300, 280) }, anchors: [at('clients', R(400, 300))] }),"
     " plan({ ...narrow, hovered: { column: 'pools', rect: R(200, 300, 280) }, anchors: [at('models', R(1080, 300, 260))] })]",
     '[{"dx":0,"dy":{}},{"dx":0,"dy":{}},{"dx":0,"dy":{}}]',
     "a card under the pointer that is cut by the window's edge is not chased when nothing is taken or what is taken is in view; negative: a card that would take the pointer's "
     "card out of view (200..480 with a model at 1340: 1140 > 976) is not taken at all, so the box stays"),
    ("window_shorter_than_the_column",
     "",
     "[plan({ screen: { width: 1440, height: 500 }, floor: null, anchors: [at('models', R(1080, 470))] }), plan({ floor: null, anchors: [at('models', R(1080, 470))] })]",
     '[{"dx":0,"dy":{"models":12}},{"dx":0,"dy":{}}]',
     "a window shorter than the column's body (500 against 760) ends the room at 488: a card at 470..500 is lifted 12; negative: on the 800 window the same card is in view"),
    ("box_wider_than_the_window",
     "",
     "[plan({ screen: { width: 1000, height: 800 }, box: { left: 0, right: 1600 }, anchors: [at('models', R(1080, 300, 260))] }), plan({ anchors: [at('models', R(1080, 300, 260))] })]",
     '[{"dx":352,"dy":{}},{"dx":0,"dy":{}}]',
     "the box reaches past the window (1600 against 1000): the room across ends at the window's edge, so a card at 1080..1340 is out of view and the box moves 352; negative: on a 1440 window it is in view"),
    ("box_starts_after_the_edge",
     "",
     "plan({ screen: { width: 1000, height: 800 }, box: { left: 100, right: 1000 }, anchors: [at('clients', R(90, 300, 140))] })",
     '{"dx":-22,"dy":{}}',
     "the box begins at 100 on the screen: the room across begins at 112, so a card at 90..230 is brought in by 22 (the box moves right)"),
    ("moved",
     "",
     "[M.moved({ x: 10, y: 10 }, 12, 11), M.moved({ x: 10, y: 10 }, 14, 10), M.moved({ x: 10, y: 10 }, undefined, undefined), M.moved({ x: 0, y: 0 }, undefined, undefined)]",
     "[false,true,true,false]",
     "a pointer that went less than 4 px is still; 4 px or more is moving; no coordinates count as the origin: a still pointer at the origin stays still, "
     "one standing elsewhere is not the one that is missing"),
]


def main():
    return run("js pool-reveal", ".probe_pool_reveal.tmp.mjs", PREAMBLE, PINS)


if __name__ == "__main__":
    sys.exit(main())
