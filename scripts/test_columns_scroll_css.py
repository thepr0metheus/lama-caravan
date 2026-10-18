#!/usr/bin/env python3
"""Value snapshot: in Routing and on the main board the page does not scroll — each column does, on its own (1.3.548).

The owner, 2026-10-14: "on /routing and on /board, so that the whole screen is not scrolled — each column scrolled by itself".
Before, Routing's whole box (four columns) was one scroller, and the main board was a page that scrolled with its three columns.
A browser is not in CI, so what the stylesheets say about the boxes is read from their text (scripts/_css_rules.py): the claims
below are what the layout stands on, and each is easy to bend without a word:

  Routing (static/css/pool-board.css)
  - the board's box (`.pb`) is a column of flex that does not scroll down (`overflow-y: hidden`) and does scroll across
    (`overflow-x: auto`, a window narrower than the columns); an `overflow: auto` there would make the whole board scroll again;
  - the grid of columns (`.pb-cols`) takes the box's height and gives its row exactly that (`minmax(0, 1fr)`, `min-height: 0`),
    and its columns stretch: a column of no height of its own has nothing to scroll in;
  - a column (`.pb-col`) is a column of flex that does not scroll itself: it holds the head and the body, and may shrink (`min-height: 0`);
  - the body (`.pb-col-body`) is what scrolls down (`overflow-y: auto`), cuts across (`overflow-x: hidden`), takes what the head leaves
    (`flex: 1 1 auto`, `min-height: 0`) and is positioned (a card is carried along its list by its offset from it);
  - a scroller cuts what stands out of it, and the cables' dots stand 8px out of a card, with a 4px ring round them when a request
    runs (static/css/cables.css; 1.3.548 had brackets that stood 24px out and 14px of room: they came out cut off, 2026-10-14): the
    body has room for the dot and its ring inside (`--pb-col-room`, as padding) and is that much wider (the same, as a negative
    margin) — so the cards keep their places; the column is that much wider too, so the head stands over the cards' edge; the room is
    read from the dot's own rule, so a dot that is made to stand further out names the columns that have no room for it;
  - under its last card the body keeps more than the strip is high (`--pb-foot`), so the last card can be lifted clear of the strip;
  - the head (`.pb-col-head`) is outside what scrolls (the owner, 2026-10-18: "the headings outside the area I scroll, shown always"):
    it does not shrink (`flex: none`), is one height for all four columns (`--pb-head`, so the four titles stand on one line and the
    bodies start on one), and never sticks — nothing passes under it; a line under it shows, in its own border, while the body above is
    scrolled (`FixedHeads`);
  - the layer of cables cuts what runs off the board (`overflow: hidden`) and what runs up into the heads (`clip-path` at the head's height;
    a cable to a card scrolled up out of its body would end in nothing beside the title), the cable in the hand is cut by neither (`visible`);

  the main board (static/css/topology-board.css, static/css/columns.css, static/index.html)
  - the page does not scroll down (`overflow-y: hidden` on the document), the body is a column of the window's height, the board's
    `main` takes what is left, the grid stretches its row to it;
  - the clients' column and the machines' lane (the two that carry `board-col` in the markup) are a head and a body, like Routing's
    columns since 1.3.573 (the owner, 2026-10-18, of this board: "the headings outside the area I scroll, shown always"): the column is
    a column of flex that does not scroll itself, the title is its first child, and the body (`board-scroll`, the block after the title)
    scrolls on its own, with room inside and negative margin outside as above; Routing's lane between them carries neither mark (it
    holds the windows it opens);
  - the title (`.board-col-title`, static/css/columns.css) stands over the body: it does not stick, nothing is behind it (no strip), and
    nothing passes under it; it does not shrink, it is one height for both columns (`--board-head`, which the board sets and the cables are
    cut at), its line is clear at rest, and a line shows under it while the body above is scrolled; a section title inside a body — the
    cloud providers' — is a `board-sub-title`, not a column's, and scrolls with its section;
  - the layer of cables is cut at the board's edge and at the head's height, so a cable to a card scrolled up does not run across a title;
  - every one of these rules is for a board that is not a machine's own window (`html:not([data-board-view="machine"])`): that window
    is one column of cards and scrolls as a page, as before.

Each claim has a positive and a negative pin.

Run: python3 scripts/test_columns_scroll_css.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
_fail = []


def check(cond, msg):
    print(("  ok  " if cond else " FAIL ") + msg)
    if not cond:
        _fail.append(msg)


def declared(css, selector):
    """Every declaration of every rule whose selector is exactly this one, the later one over the earlier."""
    merged = {}
    for sel, decl in CssRules.rules(css):
        if sel == selector:
            merged.update(decl)
    return merged


class DotReach:
    """How far a dot stands out of its card, and the ring round it when its cable carries a request: what a column keeps room for."""

    @classmethod
    def of(cls, cables_css):
        rules = CssRules.rules(cables_css)
        stand = [abs(CssRules.px(d["right"]) or 0) for sel, d in rules if sel in (".pb-dot.out", ".topology-handle.output") and "right" in d]
        ring = [int(n) for sel, d in rules if sel in (".pb-dot.flowing", ".topology-handle.activity-active")
                for n in re.findall(r"0 0 0 (\d+)px", d.get("box-shadow", ""))]
        return (max(stand) if stand else 0.0) + (max(ring) if ring else 0.0)


class RoutingColumns:
    @classmethod
    def problems(cls, css, reach=12.0):
        board, cols, col = declared(css, ".pb"), declared(css, ".pb-cols"), declared(css, ".pb-col")
        head, body = declared(css, ".pb-col-head"), declared(css, ".pb-col-body")
        cables, live, dock = declared(css, ".pb-cables"), declared(css, ".pb-live-layer"), declared(css, ".pb-dock")
        cut = declared(css, ".pb-cables:not(.pb-live-layer)")
        bad = []
        if "overflow" in board:
            bad.append(".pb has an `overflow` shorthand: it is what made the whole board scroll as one")
        if board.get("overflow-y") != "hidden":
            bad.append("the board's box scrolls down as a whole: .pb has no overflow-y: hidden")
        if board.get("overflow-x") != "auto":
            bad.append("a window narrower than the columns cannot be scrolled across: .pb has no overflow-x: auto")
        if board.get("display") != "flex" or board.get("flex-direction") != "column":
            bad.append("the board's box is not a column of flex: the grid of columns gets no height to scroll in")
        if cols.get("flex") != "1 1 auto" or cols.get("min-height") != "0":
            bad.append("the grid of columns does not take the box's height: .pb-cols needs flex: 1 1 auto and min-height: 0")
        if "minmax(0, 1fr)" not in cols.get("grid-template-rows", "") or cols.get("align-items") != "stretch":
            bad.append("the columns do not stretch to the grid's height: .pb-cols needs grid-template-rows: minmax(0, 1fr) and align-items: stretch")
        tall = CssRules.px(cols.get("--pb-head", ""))
        if tall is None or tall <= 0:
            bad.append("the heads have no height of their own: .pb-cols does not declare --pb-head, the cables are cut nowhere")
        # the column holds the head and the body; it is not what scrolls
        if col.get("display") != "flex" or col.get("flex-direction") != "column":
            bad.append("a column is not a column of flex: its head and its body do not stand one over the other, .pb-col needs display: flex and flex-direction: column")
        if any(prop.startswith("overflow") and col.get(prop) not in (None, "visible") for prop in col):
            bad.append("the column scrolls as a whole again, with its head in what scrolls: .pb-col has an overflow")
        if col.get("min-height") != "0":
            bad.append("a column cannot shrink to the box: .pb-col has no min-height: 0")
        room = CssRules.px(col.get("--pb-col-room", ""))
        if room is None or room < reach:
            bad.append(f"a column has no room for the cables' dots and their ring ({reach:g}px) inside it: --pb-col-room is under {reach:g}px")
        shell = CssRules.sides(col.get("padding", "").replace("var(--pb-col-room)", "0"))
        if shell is None or any(shell) or "var(--pb-col-room)" not in col.get("padding", ""):
            bad.append("the column is not that much wider than its track on both sides and nothing else: .pb-col's padding is not 0 var(--pb-col-room)")
        if "calc(-1 * var(--pb-col-room))" not in col.get("margin", ""):
            bad.append("the column is not that much wider than its track: .pb-col's margin is not minus --pb-col-room, so the head and the cards moved")
        # the body is what scrolls
        if body.get("overflow-y") != "auto":
            bad.append("a column does not scroll down on its own: .pb-col-body has no overflow-y: auto")
        if body.get("overflow-x") != "hidden":
            bad.append("a column does not cut across: .pb-col-body has no overflow-x: hidden")
        if body.get("min-height") != "0" or body.get("flex") != "1 1 auto":
            bad.append("a column's body cannot shrink to what the head leaves: .pb-col-body needs flex: 1 1 auto and min-height: 0")
        if body.get("position") != "relative":
            bad.append("a carried card is placed from the wrong box: .pb-col-body is not position: relative, and it is the list the card is carried along")
        padding = CssRules.sides(body.get("padding", "").replace("var(--pb-col-room)", "0").replace("var(--pb-foot)", "0"))
        if "var(--pb-col-room)" not in body.get("padding", "") or "var(--pb-foot)" not in body.get("padding", ""):
            bad.append("the room is not the body's padding, or the foot is not under the last card: .pb-col-body's padding does not use --pb-col-room and --pb-foot")
        elif padding is None or padding[0] <= 0:
            bad.append("the first card stands against the head: .pb-col-body has no padding over it, and the ring of a lit first card is cut")
        if "calc(-1 * var(--pb-col-room))" not in body.get("margin", ""):
            bad.append("the body is not that much wider than its track: .pb-col-body's margin is not minus --pb-col-room, so the cards moved")
        foot, height = CssRules.px(col.get("--pb-foot", "")), CssRules.px(dock.get("height", ""))
        if foot is None or height is None or foot <= height:
            bad.append("the last card cannot be lifted clear of the strip: --pb-foot is not more than the strip's height")
        # the head stands over the body
        if head.get("flex") != "none":
            bad.append("a head can shrink away when the column is short: .pb-col-head needs flex: none")
        if head.get("height") != "var(--pb-head)" or head.get("box-sizing") != "border-box":
            bad.append("the four heads are not one height: .pb-col-head needs height: var(--pb-head) and box-sizing: border-box, or the titles do not stand on one line")
        if cables.get("overflow") != "hidden":
            bad.append("a cable to a card scrolled out of its column runs over the page: .pb-cables is not overflow: hidden")
        if "var(--pb-head)" not in cut.get("clip-path", "") or "inset(" not in cut.get("clip-path", ""):
            bad.append("a cable to a card scrolled up out of its body runs over the head and ends beside the title: .pb-cables:not(.pb-live-layer) is not cut at the head's height")
        if live.get("overflow") != "visible":
            bad.append("the cable in the hand is cut at the board's edge: .pb-live-layer is not overflow: visible")
        if live.get("clip-path", "none") != "none":
            bad.append("the cable in the hand is cut at the heads: .pb-live-layer has a clip-path")
        return bad


class FixedHeads:
    """A router column's head stands over the body that scrolls (static/css/pool-board.css; the owner, 2026-10-18): it does not stick,
    columns.css has nothing to say of it, and a line under it shows while the body is scrolled."""

    LINE = ".pb-col:has(> .pb-col-body.scrolled) > .pb-col-head"

    @classmethod
    def problems(cls, pool_css, columns_css):
        head, shown = declared(pool_css, ".pb-col-head"), declared(pool_css, cls.LINE)
        bad = []
        if "sticky" in head.get("position", "") or any("pb-col-head" in sel for sel, _decl in CssRules.rules(columns_css)):
            bad.append("Routing's head sticks again (position: sticky, or a rule of columns.css): the cards would pass under it")
        if "transparent" not in head.get("border-bottom", "") or "1px" not in head.get("border-bottom", ""):
            bad.append("the head has no clear line of its own at rest: .pb-col-head needs border-bottom: 1px solid transparent, or the line moves it when it shows")
        colour = shown.get("border-bottom-color", "").strip()
        if colour in ("", "transparent"):
            bad.append("a scrolled body shows no line under its head: the rule for a column whose body is `scrolled` is missing or clear")
        return bad


class BoardColumns:
    GUARD = 'html:not([data-board-view="machine"])'

    @classmethod
    def problems(cls, css, markup, reach=12.0):
        g = cls.GUARD
        page = declared(css, f"{g}:has(.topology-view)")
        body = declared(css, f"{g} body:has(.topology-view)")
        main = declared(css, f"{g} body:has(.topology-view) > .topology-view")
        grid = declared(css, f"{g} .topology-view > .topology-board")
        board = declared(css, f"{g} .topology-board")
        col = declared(css, f"{g} .topology-board .board-col")
        scroller = declared(css, f"{g} .topology-board .board-scroll")
        cables = declared(css, f"{g} .topology-cables")
        bad = []
        if page.get("overflow-y") != "hidden":
            bad.append("the page scrolls down as a whole: the document has no overflow-y: hidden")
        if body.get("height") != "100dvh" or body.get("display") != "flex" or body.get("flex-direction") != "column":
            bad.append("the body is not a column of the window's height: height: 100dvh, display: flex, flex-direction: column")
        if main.get("flex") != "1 1 auto" or main.get("min-height") != "0" or main.get("width") != "100%":
            bad.append("the board's main does not take what is left under the header: flex: 1 1 auto, min-height: 0, width: 100%")
        if grid.get("flex") != "1 1 auto" or grid.get("min-height") != "0" or grid.get("align-items") != "stretch" \
                or "minmax(0, 1fr)" not in grid.get("grid-template-rows", ""):
            bad.append("the grid of columns does not take the main's height: flex: 1 1 auto, min-height: 0, align-items: stretch, grid-template-rows: minmax(0, 1fr)")
        # a column is a head and a body: a column of flex that does not scroll itself
        if col.get("display") != "flex" or col.get("flex-direction") != "column" or col.get("min-height") != "0":
            bad.append("a column is not a column of flex that can shrink to the grid's row: .board-col needs display: flex, flex-direction: column, min-height: 0")
        if "overflow" in col or "overflow-y" in col:
            bad.append("a column scrolls as a whole again, with its title in what scrolls: .board-col has an overflow")
        # the body is what scrolls
        if scroller.get("overflow-y") != "auto" or scroller.get("overflow-x") != "hidden" or scroller.get("min-height") != "0" or scroller.get("flex") != "1 1 auto":
            bad.append("a column does not scroll on its own: .board-scroll needs overflow-y: auto, overflow-x: hidden, flex: 1 1 auto, min-height: 0")
        room = CssRules.px(col.get("--board-col-room", ""))
        if room is None or room < reach:
            bad.append(f"a column has no room for the cables' dots and their ring ({reach:g}px) inside it: --board-col-room is under {reach:g}px")
        if "var(--board-col-room)" not in scroller.get("padding-inline", "") or "calc(-1 * var(--board-col-room))" not in scroller.get("margin-inline", ""):
            bad.append("the room is not the body's padding, or the body is not that much wider (margin): the cards moved")
        if (CssRules.px(scroller.get("padding-top", "")) or 0) <= 0:
            bad.append("the first row stands against the title: .board-scroll has no padding-top, and the 12px from a title to its first row are short")
        if scroller.get("align-content") != "start":
            bad.append("a body that is a grid stretches its rows to its height: .board-scroll needs align-content: start")
        clients_body = declared(css, f"{g} .topology-column > .board-scroll")
        if clients_body.get("display") != "grid" or CssRules.px(clients_body.get("gap", "")) != 12:
            bad.append("the clients' tools and cards are not 12px apart: the clients' body is not a grid with gap: 12px, as the column's grid kept them before it was a head and a body")
        # a machine's own window hides the titles and what is not the machine's, in the lane's body now
        hidden = {sel for sel, decl in CssRules.rules(css) if decl.get("display") == "none"}
        for needed in ('html[data-board-view="machine"] .lane-servers > .board-col-title',
                       'html[data-board-view="machine"] .lane-servers .board-col-body > :not(.machines-head):not(.machine-cards)'):
            if needed not in hidden:
                bad.append(f"a machine's own window does not hide what is the board's (`{needed}` is not display: none): its title, the providers or the scouts' box would show")
        # the head's height is the board's, and the cables are cut at it
        if (CssRules.px(board.get("--board-head", "")) or 0) <= 0:
            bad.append("the board does not say how tall a title is: .topology-board has no --board-head, so the cables are cut nowhere")
        clip = cables.get("clip-path", "")
        if cables.get("overflow") != "hidden":
            bad.append("a cable to a card scrolled out of its column runs over the page: .topology-cables is not overflow: hidden")
        if "inset(" not in clip or "var(--board-head)" not in clip:
            bad.append("a cable to a card scrolled up out of its body runs across a title: .topology-cables is not cut at the head's height (clip-path: inset(var(--board-head) 0 0 0))")
        # every rule of the block that is about the scrolling is for a board, not for a machine's own window
        unguarded = sorted({sel for sel, decl in CssRules.rules(css)
                            if (("board-scroll" in sel or "board-col" in sel or ("topology-view" in sel and "overflow" in " ".join(decl))) and not sel.startswith(g)
                                and not sel.startswith('html[data-board-view="machine"]') and "board-col-title" not in sel)})
        if unguarded:
            bad.append("a rule of the column scroll is not for the board alone (no data-board-view guard): " + "; ".join(unguarded))
        # the columns carry `board-col`, the body that follows their title carries the scroll mark, the lane that holds windows carries neither
        title = r'<div class="board-col-title">(?:(?!</div>).)*(?:</h2>)?</div>'
        clients = re.search(r'<div class="([^"]*)">\s*(?:<!--(?:(?!-->).)*-->\s*)?' + title + r'\s*<div class="([^"]*)"', markup, re.S)
        servers = re.search(r'<section class="([^"]*lane-servers[^"]*)">\s*(?:<!--(?:(?!-->).)*-->\s*)?' + title + r'\s*<div class="([^"]*)"', markup, re.S)
        lane = re.search(r'<div class="topology-lanes[^"]*">\s*<section([^>]*)>', markup)
        if not clients or "board-col" not in clients.group(1).split():
            bad.append("the clients' column does not carry board-col")
        elif "board-scroll" in clients.group(1).split() or "board-scroll" not in clients.group(2).split():
            bad.append("the clients' body is not what scrolls: board-scroll belongs on the block after the title, not on the column")
        if not servers or "board-col" not in servers.group(1).split():
            bad.append("the machines' lane does not carry board-col")
        elif "board-scroll" in servers.group(1).split() or "board-scroll" not in servers.group(2).split():
            bad.append("the machines' body is not what scrolls: board-scroll belongs on the block after the title, not on the lane")
        if not lane or "board-scroll" in lane.group(1) or "board-col" in lane.group(1):
            bad.append("Routing's lane carries a column's mark: the windows it opens would be cut")
        return bad


class BoardHeads:
    """A column's title on the main board stands over the body that scrolls (static/css/columns.css; index.html; the owner, 2026-10-18): it does
    not stick, nothing is behind it, it is one height for both columns, and a line under it shows while the body is scrolled."""

    LINE = ".board-col:has(> .board-col-body.scrolled) > .board-col-title"

    @classmethod
    def problems(cls, css, markup):
        head, shown, strip = declared(css, ".board-col-title"), declared(css, cls.LINE), declared(css, ".board-col-title::before")
        bad = []
        if "sticky" in head.get("position", "") or strip or "scroll-padding-top" in declared(css, ".board-scroll"):
            bad.append("a board title sticks again (position: sticky, a strip behind it, or a scroll-padding kept for it): the cards would pass under it")
        if head.get("flex") != "none":
            bad.append("a title can shrink away when the column is short: .board-col-title needs flex: none")
        if head.get("box-sizing") != "border-box" or "var(--board-head" not in head.get("height", ""):
            bad.append("the two titles are not one height: .board-col-title needs height: var(--board-head, …) and box-sizing: border-box, or the bodies do not start on one line")
        if "transparent" not in head.get("border-bottom", "") or "1px" not in head.get("border-bottom", ""):
            bad.append("the title has no clear line of its own at rest: .board-col-title needs border-bottom: 1px solid transparent, or the line moves it when it shows")
        colour = shown.get("border-bottom-color", "").strip()
        if colour in ("", "transparent"):
            bad.append("a scrolled body shows no line under its title: the rule for a column whose body is `scrolled` is missing or clear")
        # the markup: the title is the first child of its column, over the body; a section title inside a body is not a column's
        for what, pattern in (("the clients' title", r'<div class="topology-column board-col">\s*(?:<!--(?:(?!-->).)*-->\s*)?<div class="board-col-title">'),
                              ("the machines' title", r'<section class="lane-servers board-col">\s*(?:<!--(?:(?!-->).)*-->\s*)?<div class="board-col-title">'),
                              ("the providers' title", r'<div class="board-sub-title providers-title"')):
            if not re.search(pattern, markup, re.S):
                bad.append(f"{what} is not where it belongs: a column's title is the first child of its column (over the body that scrolls), the providers' is a board-sub-title in the body")
        if re.search(r'class="(?:section-title topology-title|topology-lane-head [a-z-]*head)[^"]*"[^>]*>\s*(?:<!--(?:(?!-->).)*-->\s*)?<h2', markup, re.S):
            bad.append("a title is inside the head that holds the column's tools again: it cannot stand over the body")
        return bad


ROUTING_GOOD = """.pb { position: relative; height: 100%; display: flex; flex-direction: column; overflow-x: auto; overflow-y: hidden; padding: 14px 20px 0; }
.pb-cols { position: relative; display: grid; flex: 1 1 auto; min-height: 0; align-items: stretch; grid-template-rows: minmax(0, 1fr); gap: 80px; --pb-head: 28px; }
.pb-col { --pb-col-room: 14px; --pb-foot: 172px; position: relative; display: flex; flex-direction: column; min-width: 0; min-height: 0;
  padding: 0 var(--pb-col-room); margin: 0 calc(-1 * var(--pb-col-room)); }
.pb-col-head { flex: none; box-sizing: border-box; height: var(--pb-head); border-bottom: 1px solid transparent; }
.pb-col-body { position: relative; flex: 1 1 auto; min-height: 0; overflow-x: hidden; overflow-y: auto;
  padding: 10px var(--pb-col-room) var(--pb-foot); margin: 0 calc(-1 * var(--pb-col-room)); }
.pb-cables { position: absolute; inset: 0; overflow: hidden; z-index: 2; }
.pb-live-layer { z-index: 30; overflow: visible; }
.pb-cables:not(.pb-live-layer) { clip-path: inset(var(--pb-head) 0 0 0); }
.pb-dock { position: sticky; left: 0; height: 156px; margin: -156px -20px 0; }"""

BOARD_GOOD = """html:not([data-board-view="machine"]):has(.topology-view) { overflow-y: hidden; }
html:not([data-board-view="machine"]) body:has(.topology-view) { height: 100dvh; display: flex; flex-direction: column; }
html:not([data-board-view="machine"]) body:has(.topology-view) > .topology-view { flex: 1 1 auto; min-height: 0; width: 100%; display: flex; flex-direction: column; }
html:not([data-board-view="machine"]) .topology-view > .topology-board { flex: 1 1 auto; min-height: 0; align-items: stretch; grid-template-rows: minmax(0, 1fr); }
html:not([data-board-view="machine"]) .topology-board { --board-head: 28px; }
html:not([data-board-view="machine"]) .topology-board .board-col { --board-col-room: 14px; display: flex; flex-direction: column; gap: 0; min-height: 0; }
html:not([data-board-view="machine"]) .topology-board .board-scroll { flex: 1 1 auto; min-height: 0; overflow-x: hidden; overflow-y: auto; align-content: start;
  padding-top: 6px; padding-inline: var(--board-col-room); margin-inline: calc(-1 * var(--board-col-room)); }
html:not([data-board-view="machine"]) .topology-column > .board-scroll { display: grid; gap: 12px; }
html[data-board-view="machine"] .lane-servers > .board-col-title,
html[data-board-view="machine"] .lane-servers .board-col-body > :not(.machines-head):not(.machine-cards) { display: none; }
html:not([data-board-view="machine"]) .topology-cables { overflow: hidden; clip-path: inset(var(--board-head) 0 0 0); }"""

MARKUP_GOOD = """<section class="topology-board">
  <div class="topology-column board-col">
    <!-- the title is a block of its own -->
    <div class="board-col-title"></div>
    <div class="board-col-body board-scroll">
      <div class="section-title topology-title"></div>
    </div>
  </div>
  <div class="topology-column topology-server-column">
    <div class="topology-lanes nodes-on">
      <section>
        <div id="topologyProxies"></div>
      </section>
      <section class="lane-servers board-col">
        <div class="board-col-title"></div>
        <div class="board-col-body board-scroll">"""


def test_routing():
    print("Routing's columns — on samples of their own:")
    check(RoutingColumns.problems(ROUTING_GOOD) == [], "a board that does not scroll down, columns that hold a head and a body that scrolls, with room inside and a foot under the last card — no remarks")

    def named(old, new, *parts):
        got = RoutingColumns.problems(ROUTING_GOOD.replace(old, new))
        return len(got) >= 1 and all(any(part in line for line in got) for part in parts)

    check(named("overflow-x: auto; overflow-y: hidden;", "overflow: auto;", "an `overflow` shorthand", "scrolls down as a whole", "scrolled across"),
          "negative: the board's box scrolls as a whole again (overflow: auto) — three things named")
    check(named("overflow-y: hidden; padding: 14px", "padding: 14px", "scrolls down as a whole"), "negative: the box may scroll down — named")
    check(named("overflow-x: auto;", "", "cannot be scrolled across"), "negative: a narrow window cannot be scrolled across — named")
    check(named("display: flex; flex-direction: column;", "", "not a column of flex"), "negative: the box is not a column of flex — named")
    check(named("flex: 1 1 auto; min-height: 0; align-items", "align-items", "does not take the box's height"), "negative: the grid takes no height — named")
    check(named("grid-template-rows: minmax(0, 1fr);", "", "do not stretch"), "negative: the grid's row has no height of its own — named")
    check(named("align-items: stretch;", "align-items: start;", "do not stretch"), "negative: the columns stop at their content — named (they were `start` before)")
    check(named(" --pb-head: 28px; }", " }", "no height of their own"), "negative: the grid does not say how tall a head is — the cables are cut nowhere — named")
    # the column holds the head and the body, and is not what scrolls
    check(named("position: relative; display: flex; flex-direction: column; min-width: 0;", "position: relative; min-width: 0;", "not a column of flex"),
          "negative: a column that is not a column of flex — the head and the body do not stand one over the other — named")
    check(named("min-width: 0; min-height: 0;\n  padding: 0 var(--pb-col-room);", "min-width: 0; min-height: 0; overflow-y: auto;\n  padding: 0 var(--pb-col-room);", "scrolls as a whole again"),
          "negative: the column scrolls itself again (it did until 1.3.573) — its head is in what scrolls — named")
    check(named("min-width: 0; min-height: 0;\n  padding: 0 var(--pb-col-room);", "min-width: 0;\n  padding: 0 var(--pb-col-room);", "cannot shrink to the box"), "negative: a column that cannot shrink — named")
    check(named("padding: 0 var(--pb-col-room);", "padding: 4px var(--pb-col-room);", "padding is not 0 var(--pb-col-room)"),
          "negative: 4px of padding over the head — the heads move by it — named")
    check(named("padding: 0 var(--pb-col-room);", "padding: 0 14px;", "padding is not 0 var(--pb-col-room)"), "negative: the column's room is not the variable — named")
    # the body is what scrolls
    check(named("overflow-y: auto;\n", "overflow-y: visible;\n", "does not scroll down on its own"), "negative: a body that does not scroll — named")
    check(named("overflow-x: hidden;", "", "does not cut across"), "negative: a body that does not cut across — named")
    check(named("flex: 1 1 auto; min-height: 0; overflow-x", "min-height: 0; overflow-x", "cannot shrink to what the head leaves"), "negative: a body that does not take what the head leaves — named")
    check(named("flex: 1 1 auto; min-height: 0; overflow-x", "flex: 1 1 auto; overflow-x", "cannot shrink to what the head leaves"), "negative: a body that may not shrink below its content — it would not scroll — named")
    check(named(".pb-col-body { position: relative;", ".pb-col-body {", "placed from the wrong box"), "negative: a body that is not positioned — the carried card is placed from the wrong box — named")
    check(named("--pb-col-room: 14px;", "--pb-col-room: 4px;", "no room for the cables' dots"), "negative: room under 12px — the dots are cut — named")
    check(RoutingColumns.problems(ROUTING_GOOD, reach=24.0) != [] and "no room for the cables' dots" in RoutingColumns.problems(ROUTING_GOOD, reach=24.0)[0],
          "negative: a dot that stands out 24px (the main board's brackets did) — the room of 14px is named too small")
    check(named("padding: 10px var(--pb-col-room) var(--pb-foot);", "padding: 10px 14px var(--pb-foot);", "not the body's padding"), "negative: the room is not the body's padding — named")
    check(named("padding: 10px var(--pb-col-room) var(--pb-foot);", "padding: 0 var(--pb-col-room) var(--pb-foot);", "against the head"),
          "negative: no padding over the first card — it stands against the head and the ring of a lit card is cut — named")
    check(named("margin: 0 calc(-1 * var(--pb-col-room));", "margin: 0;", "cards moved", "head and the cards moved"), "negative: the column and the body are not wider than their track — the cards moved — named")
    check(named("overflow-y: auto;\n  padding: 10px var(--pb-col-room) var(--pb-foot); margin: 0 calc(-1 * var(--pb-col-room));", "overflow-y: auto;\n  padding: 10px var(--pb-col-room) var(--pb-foot); margin: 0;", "body is not that much wider"),
          "negative: the body is not wider than its track — named")
    check(named("--pb-foot: 172px;", "--pb-foot: 100px;", "lifted clear of the strip"), "negative: a foot shorter than the strip — named")
    # the head stands over the body
    check(named(".pb-col-head { flex: none;", ".pb-col-head {", "can shrink away"), "negative: a head that can shrink away when the column is short — named")
    check(named("height: var(--pb-head);", "height: auto;", "not one height"), "negative: a head as tall as its content — the titles of the four columns do not stand on one line — named")
    check(named("box-sizing: border-box; height", "height", "not one height"), "negative: a head whose line adds to its height — named")
    check(named("overflow: hidden; z-index: 2;", "overflow: visible; z-index: 2;", "runs over the page"), "negative: cables that are not cut — named")
    check(named(".pb-cables:not(.pb-live-layer) { clip-path: inset(var(--pb-head) 0 0 0); }", "", "ends beside the title"),
          "negative: cables that are not cut at the heads — a cable to a card scrolled up ends in nothing beside the title — named")
    check(named("inset(var(--pb-head) 0 0 0)", "inset(0 0 0 0)", "ends beside the title"), "negative: cables cut at the top of the board, not at the head's height — named")
    check(named("z-index: 30; overflow: visible;", "z-index: 30;", "cut at the board's edge"), "negative: the cable in the hand is cut — named")
    check(named("z-index: 30; overflow: visible; }", "z-index: 30; overflow: visible; clip-path: inset(var(--pb-head) 0 0 0); }", "cut at the heads"),
          "negative: the cable in the hand is cut at the heads — named")
    print("Routing's columns (static/css/pool-board.css):")
    reach = DotReach.of((ROOT / "static" / "css" / "cables.css").read_text(encoding="utf-8"))
    check(reach == 12.0, f"the dot stands 8px out of its card and its ring is 4px: the columns keep room for {reach:g}px")
    real = RoutingColumns.problems((ROOT / "static" / "css" / "pool-board.css").read_text(encoding="utf-8"), reach)
    check(real == [], "the board does not scroll down, each column's body does under a head that stays, with room and a foot" + (f" — {'; '.join(real)}" if real else ""))


FIXED_POOL = """.pb-col-head { flex: none; box-sizing: border-box; height: var(--pb-head); border-bottom: 1px solid transparent; }
.pb-col:has(> .pb-col-body.scrolled) > .pb-col-head { border-bottom-color: color-mix(in srgb, var(--line) 80%, transparent); }"""
FIXED_COLUMNS = ".board-col-title { position: sticky; top: 0; z-index: 5; }"


def test_fixed_heads():
    print("Routing's heads — on samples of their own:")
    check(FixedHeads.problems(FIXED_POOL, FIXED_COLUMNS) == [], "a head that does not stick, with a clear line of its own that shows when the body is scrolled — no remarks")

    def named(old, new, *parts, pool=FIXED_POOL, columns=FIXED_COLUMNS):
        got = FixedHeads.problems(pool.replace(old, new), columns)
        return len(got) >= 1 and all(any(part in line for line in got) for part in parts)

    check(named("flex: none;", "flex: none; position: sticky; top: 0;", "sticks again"), "negative: the head sticks again (its own rule) — named")
    check(FixedHeads.problems(FIXED_POOL, FIXED_COLUMNS + "\n.board-col-title, .pb-col-head { position: sticky; top: 0; }") != [] and
          "sticks again" in FixedHeads.problems(FIXED_POOL, FIXED_COLUMNS + "\n.board-col-title, .pb-col-head { position: sticky; top: 0; }")[0],
          "negative: columns.css makes Routing's head sticky again, as it did until 1.3.573 — named")
    check(named("border-bottom: 1px solid transparent;", "", "no clear line of its own"), "negative: no border at rest — the line would move the head when it shows — named")
    check(named("1px solid transparent", "1px solid red", "no clear line of its own"), "negative: a line that is there at rest — the head stands on a line before anything is above — named")
    check(named(".pb-col:has(> .pb-col-body.scrolled) > .pb-col-head { border-bottom-color: color-mix(in srgb, var(--line) 80%, transparent); }", "", "shows no line"),
          "negative: a scrolled body that shows no line — named")
    check(named("border-bottom-color: color-mix(in srgb, var(--line) 80%, transparent)", "border-bottom-color: transparent", "shows no line"), "negative: the line is clear when scrolled — named")
    print("Routing's heads (static/css/pool-board.css, static/css/columns.css):")
    real = FixedHeads.problems((ROOT / "static" / "css" / "pool-board.css").read_text(encoding="utf-8"), (ROOT / "static" / "css" / "columns.css").read_text(encoding="utf-8"))
    check(real == [], "the heads of Routing's columns stand over the body that scrolls, and nothing sticks" + (f" — {'; '.join(real)}" if real else ""))


def test_board():
    print("the main board's columns — on samples of their own:")
    check(BoardColumns.problems(BOARD_GOOD, MARKUP_GOOD) == [], "a page that does not scroll down, two columns that are a head and a body, Routing's lane left alone — no remarks")

    def named(old, new, *parts, markup=MARKUP_GOOD, css=None):
        got = BoardColumns.problems((css or BOARD_GOOD).replace(old, new), markup)
        return len(got) >= 1 and all(any(part in line for line in got) for part in parts)

    check(named("{ overflow-y: hidden; }", "{ overflow-y: auto; }", "scrolls down as a whole"), "negative: the page scrolls — named")
    check(named("height: 100dvh;", "min-height: 100dvh;", "not a column of the window's height"), "negative: the body is not the window's height — named")
    check(named("width: 100%;", "", "does not take what is left"), "negative: the main shrinks to its content (a column of flex with margins auto) — named")
    check(named("align-items: stretch;", "align-items: start;", "does not take the main's height"), "negative: the board's columns stop at their content — named")
    # a column is a head and a body, and is not what scrolls
    check(named("display: flex; flex-direction: column; gap: 0; min-height: 0; }", "min-height: 0; }", "not a column of flex"),
          "negative: a column that is not a column of flex — the title and the body do not stand one over the other — named")
    check(named("gap: 0; min-height: 0; }", "gap: 0; min-height: 0; overflow-y: auto; }", "scrolls as a whole again"),
          "negative: the column scrolls itself again (it did until 1.3.578) — its title is in what scrolls — named")
    check(named("gap: 0; min-height: 0; }", "gap: 0; }", "not a column of flex that can shrink"), "negative: a column that cannot shrink — named")
    # the body is what scrolls
    check(named("overflow-y: auto;", "overflow-y: visible;", "does not scroll on its own"), "negative: a body that does not scroll — named")
    check(named("flex: 1 1 auto; min-height: 0; overflow-x", "min-height: 0; overflow-x", "does not scroll on its own"), "negative: a body that does not take what the title leaves — named")
    check(named("--board-col-room: 14px;", "--board-col-room: 4px;", "no room for the cables' dots"), "negative: room under 12px — the dots are cut — named")
    check(BoardColumns.problems(BOARD_GOOD, MARKUP_GOOD, reach=24.0) != [] and "no room for the cables' dots" in BoardColumns.problems(BOARD_GOOD, MARKUP_GOOD, reach=24.0)[0],
          "negative: a handle that stands out 24px (the brackets of 1.3.548) — the room of 14px is named too small, as the owner saw it on 2026-10-14")
    check(named("margin-inline: calc(-1 * var(--board-col-room));", "margin-inline: 0;", "cards moved"), "negative: the body is not wider than its track — named")
    check(named("padding-inline: var(--board-col-room);", "padding-inline: 14px;", "not the body's padding"), "negative: the room is not the body's padding — named")
    check(named("padding-top: 6px; ", "", "against the title"), "negative: no padding over the first row — it stands against the title — named")
    check(named("align-content: start;", "", "stretches its rows"), "negative: a grid body stretches its rows — the cards spread — named")
    check(named("{ display: grid; gap: 12px; }", "{ display: grid; gap: 30px; }", "not 12px apart"), "negative: the clients' tools and cards 30px apart — named")
    check(named("{ display: grid; gap: 12px; }", "{ display: block; }", "not 12px apart"), "negative: the clients' body is no grid, so its children touch — named")
    check(named("html[data-board-view=\"machine\"] .lane-servers > .board-col-title,\n", "", "does not hide what is the board's"),
          "negative: a machine's own window shows the machines' title — named")
    check(named("html[data-board-view=\"machine\"] .lane-servers .board-col-body > :not(.machines-head):not(.machine-cards) { display: none; }", "", "does not hide what is the board's"),
          "negative: a machine's own window shows the providers and the scouts' box — named")
    # the head's height and the cut
    check(named("{ --board-head: 28px; }", "{ }", "does not say how tall a title is"), "negative: the board does not say how tall a title is — the cables are cut nowhere — named")
    check(named("overflow: hidden; clip-path", "overflow: visible; clip-path", "runs over the page"), "negative: cables that are not cut at the board's edge — named")
    check(named("clip-path: inset(var(--board-head) 0 0 0);", "", "across a title"),
          "negative: cables that are not cut at the title's height — a cable to a card scrolled up runs across the title — named")
    check(named("inset(var(--board-head) 0 0 0)", "inset(0 0 0 0)", "across a title"), "negative: cables cut at the top of the board, not at the title's height — named")
    unguarded = BOARD_GOOD + "\n.topology-board .board-scroll { overflow-y: auto; }"
    check(named("", "", "no data-board-view guard", css=unguarded), "negative: a rule that would scroll a machine's own window too — named")
    check(named("", "", "clients' column does not carry board-col", markup=MARKUP_GOOD.replace('"topology-column board-col"', '"topology-column"')),
          "negative: the clients' column does not carry the mark — named")
    check(named("", "", "clients' body is not what scrolls", markup=MARKUP_GOOD.replace('"topology-column board-col"', '"topology-column board-col board-scroll"')),
          "negative: the mark of the scroll is on the clients' column, with the title in it again — named")
    check(named("", "", "clients' body is not what scrolls", markup=MARKUP_GOOD.replace('"board-col-body board-scroll"', '"board-col-body"', 1)),
          "negative: the clients' body does not carry the scroll mark — named")
    check(named("", "", "machines' lane does not carry", markup=MARKUP_GOOD.replace("lane-servers board-col", "lane-servers")), "negative: the machines' lane does not carry the mark — named")
    check(named("", "", "machines' body is not what scrolls", markup=MARKUP_GOOD.replace("lane-servers board-col", "lane-servers board-col board-scroll")),
          "negative: the machines' lane scrolls as a whole — its title is in what scrolls — named")
    check(named("", "", "windows it opens would be cut", markup=MARKUP_GOOD.replace("<section>", "<section class=\"board-scroll\">")),
          "negative: Routing's lane carries the scroll mark — the windows it opens would be cut — named")
    check(named("", "", "windows it opens would be cut", markup=MARKUP_GOOD.replace("<section>", "<section class=\"board-col\">")),
          "negative: Routing's lane carries the column mark — named")
    print("the main board (static/css/topology-board.css, static/index.html):")
    reach = DotReach.of((ROOT / "static" / "css" / "cables.css").read_text(encoding="utf-8"))
    real = BoardColumns.problems((ROOT / "static" / "css" / "topology-board.css").read_text(encoding="utf-8"),
                                 (ROOT / "static" / "index.html").read_text(encoding="utf-8"), reach)
    check(real == [], "the page does not scroll down, the clients' body and the machines' body do, under titles that stay" + (f" — {'; '.join(real)}" if real else ""))


HEADS_CSS = """.board-col-title { flex: none; box-sizing: border-box; height: var(--board-head, 28px); padding: 0 2px; border-bottom: 1px solid transparent; }
.board-col:has(> .board-col-body.scrolled) > .board-col-title { border-bottom-color: color-mix(in srgb, var(--line) 70%, transparent); }
.board-sub-title { padding: 0 2px; }"""
HEADS_MARKUP = """<div class="topology-column board-col">
  <!-- a title of its own -->
  <div class="board-col-title"><h2>Clients</h2></div>
  <div class="board-col-body board-scroll">
    <div class="section-title topology-title"><div class="topology-head-actions"></div></div>
  </div>
</div>
<section class="lane-servers board-col">
  <div class="board-col-title"><h2>Machines</h2></div>
  <div class="board-col-body board-scroll">
    <div class="topology-lane-head machines-head"><div class="board-pages"></div></div>
    <div class="board-sub-title providers-title" data-board-providers-head><h2>Cloud providers</h2></div>
    <div class="topology-lane-head providers-head" data-board-providers-head><div class="topology-head-actions"></div></div>
  </div>
</section>"""


def test_heads():
    print("the columns' heads — on samples of their own:")
    check(BoardHeads.problems(HEADS_CSS, HEADS_MARKUP) == [], "titles that stand over the bodies, one height, a clear line that shows when scrolled, the providers' title a section's — no remarks")

    def named(old, new, *parts, css=HEADS_CSS, markup=HEADS_MARKUP):
        got = BoardHeads.problems(css.replace(old, new), markup)
        return len(got) >= 1 and all(any(part in line for line in got) for part in parts)

    check(named("flex: none;", "flex: none; position: sticky; top: 0;", "sticks again"), "negative: the title sticks again (as it did until 1.3.578) — named")
    check(BoardHeads.problems(HEADS_CSS + '\n.board-col-title::before { content: ""; position: absolute; opacity: 0; }', HEADS_MARKUP) != [],
          "negative: the strip behind the title is back — named")
    check(BoardHeads.problems(HEADS_CSS + "\n.board-scroll { scroll-padding-top: 40px; }", HEADS_MARKUP) != [],
          "negative: the scroll-padding kept for a sticky title is back — named")
    check(named("flex: none; ", "", "can shrink away"), "negative: a title that can shrink away when the column is short — named")
    check(named("height: var(--board-head, 28px);", "height: auto;", "not one height"), "negative: a title as tall as its content — the bodies of the two columns do not start on one line — named")
    check(named("box-sizing: border-box; ", "", "not one height"), "negative: a title whose line adds to its height — named")
    check(named("1px solid transparent", "1px solid red", "no clear line of its own"), "negative: a line that is there at rest — named")
    check(named("border-bottom: 1px solid transparent;", "", "no clear line of its own"), "negative: no border at rest — the line would move the title when it shows — named")
    check(named(".board-col:has(> .board-col-body.scrolled) > .board-col-title { border-bottom-color: color-mix(in srgb, var(--line) 70%, transparent); }", "", "shows no line"),
          "negative: a scrolled body that shows no line — named")
    check(named("border-bottom-color: color-mix(in srgb, var(--line) 70%, transparent)", "border-bottom-color: transparent", "shows no line"), "negative: the line is clear when scrolled — named")
    check(named("", "", "clients' title is not where it belongs", markup=HEADS_MARKUP.replace('<div class="board-col-title"><h2>Clients</h2></div>', "")),
          "negative: the clients' title is not over the body — named")
    check(named("", "", "machines' title is not where it belongs", markup=HEADS_MARKUP.replace('<div class="board-col-title"><h2>Machines</h2></div>', "")),
          "negative: the machines' title is not over the body — named")
    check(named("", "", "providers' title is not where it belongs", markup=HEADS_MARKUP.replace('board-sub-title providers-title', 'board-col-title providers-title')),
          "negative: the providers' title is a column title again — it would be a head of its own inside the body — named")
    check(named("", "", "inside the head that holds", markup=HEADS_MARKUP.replace('<div class="topology-lane-head machines-head">', '<div class="topology-lane-head machines-head"><h2>Machines</h2>')),
          "negative: a title is back inside the machines' head — named")
    print("the columns' heads (static/css/columns.css, static/index.html):")
    real = BoardHeads.problems((ROOT / "static" / "css" / "columns.css").read_text(encoding="utf-8"), (ROOT / "static" / "index.html").read_text(encoding="utf-8"))
    check(real == [], "the titles of the main board's columns stand over the bodies that scroll, and nothing sticks" + (f" — {'; '.join(real)}" if real else ""))


test_routing()
test_fixed_heads()
test_board()
test_heads()
print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("columns scroll css snapshot holds")
