#!/usr/bin/env python3
"""Value snapshot: the cables of the main board and of Routing are one look (1.3.549).

The owner, 2026-10-14: "the connections on the main board — make them like Routing's, and keep how an active one is shown,
dashes or a drop; carry that to Routing too". Before it the main board ended a cable in a 20×34 bracket that stood 24px out of
a card (the columns that scroll cut it: the clients' brackets came out half-cut the same day), drew a line that was dimmed by how
many converged, and a request as a thick dashed one; Routing had a 12px dot and a calm thin line and showed no request at all.
A browser is not in CI, so what the stylesheets say is read from their text (scripts/_css_rules.py). The claims, each with a
positive and a negative pin:

  - the dot — size, shape, ring, which edge it stands on and how far — is one rule for Routing's `.pb-dot`, the main board's
    `.topology-handle` and the head of a card with no handle of its own (`.cable-end::before`), in static/css/cables.css; no other
    rule gives a dot its size, so the two boards' ends cannot drift apart again;
  - the line — its colour and its width, calm and lit — is one rule for Routing's `.pb-cable` and the main board's
    `.topology-cable`, with tokens the two layers take; no other rule of a base cable sets its stroke;
  - the main board has not kept the old shapes: no bracket (a handle 20px wide or 34px high, one that stands 24px out), no coloured
    dot inside a handle (`::after`), no `.idle` dimming of a cable;
  - the drops of a cable that carries a request: its twin (`.cable-flow`) runs one period of its dash pattern per lap — the keyframes
    and the dash use the same `--flow-period` — so the loop does not jump; its lap and its delay are set where the twin is made
    (cable-flow.js), not here; it takes no pointer; and with `prefers-reduced-motion` it stands still;
  - since 1.3.579 (the owner, 2026-10-18: "come up and go down smoothly, not abruptly, and run both ways at once"): the twin is a pair,
    and the one on the way back (`.back`) runs the same keyframes the other way (`animation-direction: reverse`); a twin that is coming
    up (`.rising`) or going down (`.fading`) has a second animation, its opacity (`cableFlowIn`, `cableFlowOut`), which runs once —
    the going down stays at nothing once it is done (`forwards`), the coming up does not stay at anything (it would hold the hover's
    dimming down) — and the way back must not run it backwards (`reverse, normal`); the colour of the gradient the drops come up and
    go down by is the stylesheet's (`.cable-flow-stop`); and with reduced motion a twin that is going down is not drawn at all;
  - since 1.3.580 (the owner, 2026-10-18: "when blocks are selected and the bold paths between them are shown, hide the other cables, so they
    cannot be seen or clicked — they are hard to see anyway, and when I want to let the selection go I sometimes hit them"): a pinned path of the
    Routing (`.pb.path-alone`, set by pool-board.js `lightPath`) shows only its own cables — a cable that is not on it is `display: none`, because
    the wide twin of a cable is found by `pointer-events: stroke`, which `opacity` and `visibility` do not take away, and a click on a cable cuts
    it; pointing at a card, without a pin, still only dims them;
  - both pages link the two stylesheets, after base.css.

Run: python3 scripts/test_cables_css.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _css_rules import CssRules  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STYLES = ROOT / "static" / "css"
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


class CablesCss:
    DOTS = (".pb-dot", ".topology-handle", ".cable-end::before")
    LINES = (".pb-cables .pb-cable", ".topology-cable")
    LIT = (".pb-cables .pb-cable.lit", ".topology-cable.activity-active", ".topology-cable.activity-recent")

    @classmethod
    def problems(cls, cables, others):
        """`cables` is cables.css; `others` is every other stylesheet joined (what must not repeat it)."""
        bad = []
        # the dot
        for sel in cls.DOTS:
            rule = declared(cables, sel)
            if CssRules.px(rule.get("width", "")) != 12 or CssRules.px(rule.get("height", "")) != 12 or rule.get("border-radius") != "50%":
                bad.append(f"{sel} is not the 12px round dot")
        if declared(cables, ".pb-dot").get("border") != declared(cables, ".topology-handle").get("border"):
            bad.append("Routing's dot and the main board's have borders of their own")
        outs = {CssRules.px(declared(cables, sel).get("right", "")) for sel in (".pb-dot.out", ".topology-handle.output", ".topology-handle.proxy-output")}
        ins = {CssRules.px(declared(cables, sel).get("left", "")) for sel in (".pb-dot.in", ".topology-handle.input", ".topology-handle.server-input", ".cable-end::before")}
        if outs != {-8.0} or ins != {-8.0}:
            bad.append(f"the dots do not all stand 8px out of the card's edge: outputs {sorted(outs, key=str)}, inputs {sorted(ins, key=str)}")
        ring = {declared(cables, sel).get("box-shadow") for sel in (".pb-dot.flowing", ".topology-handle.activity-active", ".cable-end.flowing::before")}
        if len(ring) != 1 or None in ring or "0 0 0 4px" not in next(iter(ring)):
            bad.append("the ring of a dot whose cable carries a request is not one and the same 4px ring")
        if declared(cables, ".cable-end").get("position") != "relative":
            bad.append("a head with a dot of its own (.cable-end) is not positioned: its dot would stand at the corner of some far box")
        # the pointer's target round a handle is bigger than the dot (hovering it lights its cable)
        target = declared(others, ".topology-handle::before")
        inset = CssRules.px(target.get("inset", ""))
        if inset is None or inset > -5:
            bad.append("the pointer's target round a handle is no bigger than the 12px dot (.topology-handle::before needs an inset of -5px or more)")
        # the pinned path of Routing shows only its own cables (pool-board.js, lightPath)
        if declared(others, ".pb.path-alone .pb-cables g:not(.on-path)").get("display") != "none":
            bad.append("a pinned path of Routing leaves the cables that are not on it drawn: .pb.path-alone .pb-cables g:not(.on-path) needs display: none "
                       "(opacity or visibility would leave the cable's wide twin under the pointer: `pointer-events: stroke` ignores both, and a click on a cable cuts it)")
        for sel in (".pb.tracing .pb-cables g:not(.on-path)", ".pb.tracing .pb-cables g:not(.on-path) .pb-cable", ".pb.traced .pb-cables g:not(.on-path)"):
            if declared(others, sel).get("display") == "none":
                bad.append(f"{sel} hides the cables that are not on the path: only a pinned path does (pointing at a card only dims them)")
        # nobody else sizes a dot (a handle's hover target, `::before` with an inset, is no dot: it has no width or height of its own)
        for sel, decl in CssRules.rules(others):
            sized = {"width", "height"} | ({"border-radius"} if "::" not in sel else set())
            if re.fullmatch(r"(?:\.pb-dot|\.topology-handle)(?:\.[\w-]+)*(?:::before|::after)?", sel) and (sized & decl.keys()):
                bad.append(f"{sel} sizes a dot of its own ({', '.join(sorted(sized & decl.keys()))}) outside cables.css")
            if re.fullmatch(r"\.topology-handle(?:\.[\w-]+)*::after", sel):
                bad.append(f"{sel}: the coloured dot inside a handle is back (a handle is the dot now)")
        # the line
        layer = declared(cables, ".pb-cables")
        for token in ("--cable-calm", "--cable-lit", "--cable-width", "--cable-lit-width"):
            if token not in layer or token not in declared(cables, ".topology-cables"):
                bad.append(f"{token} is not given to both layers of cables")
        for sel in cls.LINES:
            rule = declared(cables, sel)
            if rule.get("stroke") != "var(--cable-calm)" or rule.get("stroke-width") != "var(--cable-width)":
                bad.append(f"{sel} does not take the calm line from the tokens")
        for sel in cls.LIT:
            rule = declared(cables, sel)
            if rule.get("stroke") != "var(--cable-lit)" or rule.get("stroke-width") != "var(--cable-lit-width)":
                bad.append(f"{sel} does not take the lit line from the tokens")
        for sel, decl in CssRules.rules(others):
            if sel in cls.LINES and ({"stroke", "stroke-width"} & decl.keys()):
                bad.append(f"{sel} sets a stroke outside cables.css: the two boards' lines would drift apart")
            if sel in cls.LIT and ({"stroke", "stroke-width"} & decl.keys()):
                bad.append(f"{sel} sets a lit stroke outside cables.css")
            if re.fullmatch(r"\.topology-cable(?:\.[\w-]+)*\.idle", sel) or re.fullmatch(r"html\.river-on \.topology-cable(?:\.[\w-]+)*\.idle", sel):
                bad.append(f"{sel}: a cable is dimmed by being idle again (the calm line is the dim one now)")
        # the drops (what the stylesheet says outside its @media blocks: inside the one for reduced motion the animation is switched off)
        outside = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", cables)
        flow = declared(outside, ".cable-flow")
        dash = re.fullmatch(r"([\d.]+)px calc\(var\(--flow-period\) - ([\d.]+)px\)", flow.get("stroke-dasharray", ""))
        if not dash or dash.group(1) != dash.group(2):
            bad.append("the dash and the gap of the drops are not one period (--flow-period): the loop would jump")
        keyframes = re.search(r"@keyframes cableFlow\s*\{\s*to\s*\{([^}]*)\}", cables)
        if not keyframes or "stroke-dashoffset: calc(-1 * var(--flow-period))" not in keyframes.group(1):
            bad.append("the keyframes do not run exactly one period of the dash pattern")
        if flow.get("animation-name") != "cableflow" or flow.get("animation-iteration-count") != "infinite" or flow.get("animation-timing-function") != "linear":
            bad.append("the drops do not run linear and for ever under the name cableFlow")
        if any(key in flow for key in ("animation", "animation-duration", "animation-delay")):
            bad.append("the lap or the delay of the drops is set in the stylesheet: it is set where the twin is made, so they share one clock")
        if flow.get("pointer-events") != "none":
            bad.append("the drops take the pointer: a click on a cable to cut it would land on its twin")
        # the pair: the way back, and the coming up and going down
        back = declared(outside, ".cable-flow.back")
        rising, fading = declared(outside, ".cable-flow.rising"), declared(outside, ".cable-flow.fading")
        if back.get("animation-direction") != "reverse":
            bad.append("the drops on the way back do not run the other way: .cable-flow.back needs animation-direction: reverse")
        if rising.get("animation-name") != "cableflow, cableflowin" or rising.get("animation-iteration-count") != "infinite, 1":
            bad.append("the drops of a cable that begins to carry do not come up: .cable-flow.rising needs the names cableFlow, cableFlowIn and the counts infinite, 1")
        if fading.get("animation-name") != "cableflow, cableflowout" or fading.get("animation-iteration-count") != "infinite, 1":
            bad.append("the drops of a cable that stopped do not go down: .cable-flow.fading needs the names cableFlow, cableFlowOut and the counts infinite, 1")
        if rising.get("animation-timing-function") != "linear, ease-out" or fading.get("animation-timing-function") != "linear, ease-in":
            bad.append("the coming up and the going down are not mirrors (.cable-flow.rising needs linear, ease-out and .cable-flow.fading linear, ease-in): "
                       "a cable that carries again before its drops are gone brings them up from where they had got to (cable-flow.js), and only mirrors make that the same opacity")
        if fading.get("animation-fill-mode") != "none, forwards":
            bad.append("the drops that went down come back at the end: .cable-flow.fading needs animation-fill-mode: none, forwards")
        if "animation-fill-mode" in rising and "forwards" in rising.get("animation-fill-mode", ""):
            bad.append("the drops that came up hold their opacity for ever: .cable-flow.rising keeps its last frame, and it would override the dimming of a hover")
        for sel in (".cable-flow.back.rising", ".cable-flow.back.fading"):
            if declared(outside, sel).get("animation-direction") != "reverse, normal":
                bad.append(f"{sel} runs the opacity backwards too (needs animation-direction: reverse, normal): the drops would go down while they come up")
        for sel in (".cable-flow.back", ".cable-flow.rising", ".cable-flow.fading", ".cable-flow.back.rising", ".cable-flow.back.fading"):
            if any(key in declared(outside, sel) for key in ("animation", "animation-duration", "animation-delay")):
                bad.append(f"{sel} sets a lap, a duration or a delay in the stylesheet: they are set where the twin is made")
        if not re.search(r"@keyframes cableFlowIn\s*\{\s*from\s*\{\s*opacity:\s*0;\s*\}\s*to\s*\{\s*opacity:\s*1;\s*\}\s*\}", cables) \
                or not re.search(r"@keyframes cableFlowOut\s*\{\s*from\s*\{\s*opacity:\s*1;\s*\}\s*to\s*\{\s*opacity:\s*0;\s*\}\s*\}", cables):
            bad.append("the keyframes of the coming up and the going down are not an opacity from 0 to 1 and from 1 to 0")
        if "var(--accent" not in declared(outside, ".cable-flow-stop").get("stop-color", ""):
            bad.append("the gradient the drops come up and go down by has no colour of the stylesheet's: .cable-flow-stop needs stop-color: var(--accent-strong, var(--accent))")
        # reduced motion: every twin stands still, and one that is going down is not drawn
        reduced = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{((?:[^{}]*\{[^{}]*\})*)\s*\}", cables)
        inner = CssRules.rules(reduced.group(1)) if reduced else []
        still = {sel for sel, decl in inner if decl.get("animation") == "none"}
        if not {".cable-flow", ".cable-flow.rising", ".cable-flow.fading"} <= still:
            bad.append("the drops move for a reader who asked for no motion (.cable-flow, .cable-flow.rising and .cable-flow.fading are not all animation: none)")
        if not any(sel == ".cable-flow.fading" and decl.get("display") == "none" for sel, decl in inner):
            bad.append("a twin that is going down is drawn, still, for a reader who asked for no motion: it would hang on the cable for ever")
        return bad

    @classmethod
    def pages(cls, *pages):
        bad = []
        for name, markup in pages:
            links = re.findall(r'<link rel="stylesheet" href="/css/([\w-]+)\.css">', markup)
            for sheet in ("cables", "columns"):
                if sheet not in links:
                    bad.append(f"{name} does not link {sheet}.css")
            if "base" in links and "cables" in links and links.index("cables") < links.index("base"):
                bad.append(f"{name} links cables.css before base.css: its tokens would not see the page's colours")
        return bad


GOOD_CABLES = """.pb-cables, .topology-cables { --cable-calm: x; --cable-lit: y; --cable-width: 1px; --cable-lit-width: 1.5px; }
.pb-cables .pb-cable, .topology-cable { fill: none; stroke: var(--cable-calm); stroke-width: var(--cable-width); }
.pb-cables .pb-cable.lit, .topology-cable.activity-active, .topology-cable.activity-recent { stroke: var(--cable-lit); stroke-width: var(--cable-lit-width); }
.pb-dot, .topology-handle, .cable-end::before { position: absolute; z-index: 4; width: 12px; height: 12px; border-radius: 50%; border: 2px solid m; }
.pb-dot.out, .topology-handle.output, .topology-handle.proxy-output { right: -8px; }
.pb-dot.in, .topology-handle.input, .topology-handle.server-input, .cable-end::before { left: -8px; }
.pb-dot.flowing, .topology-handle.activity-active, .cable-end.flowing::before { border-color: a; box-shadow: 0 0 0 4px a; }
.cable-end { position: relative; }
.cable-flow { --flow-period: 26px; pointer-events: none; stroke-dasharray: 1px calc(var(--flow-period) - 1px);
  animation-name: cableFlow; animation-timing-function: linear; animation-iteration-count: infinite; }
@keyframes cableFlow { to { stroke-dashoffset: calc(-1 * var(--flow-period)); } }
@keyframes cableFlowIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes cableFlowOut { from { opacity: 1; } to { opacity: 0; } }
.cable-flow.back { animation-direction: reverse; }
.cable-flow.rising { animation-name: cableFlow, cableFlowIn; animation-iteration-count: infinite, 1; animation-timing-function: linear, ease-out; }
.cable-flow.fading { animation-name: cableFlow, cableFlowOut; animation-iteration-count: infinite, 1; animation-timing-function: linear, ease-in; animation-fill-mode: none, forwards; }
.cable-flow.back.rising, .cable-flow.back.fading { animation-direction: reverse, normal; }
.cable-flow-stop { stop-color: var(--accent-strong, var(--accent)); }
@media (prefers-reduced-motion: reduce) { .cable-flow, .cable-flow.rising, .cable-flow.fading { animation: none; } .cable-flow.fading { display: none; } }"""
GOOD_OTHERS = """.topology-handle::before { content: ""; position: absolute; inset: -7px; border-radius: 50%; }
.pb-dot.open { border-style: dashed; }
.topology-handle.primary { border-color: var(--accent); }
.pb-cables .pb-cable.live { stroke: var(--accent); }
.pb.tracing .pb-cables g:not(.on-path) .pb-cable { opacity: .14; }
.pb.path-alone .pb-cables g:not(.on-path) { display: none; }
.topology-cable.fallback { stroke: blue; }"""
GOOD_PAGE = '<link rel="stylesheet" href="/css/base.css">\n<link rel="stylesheet" href="/css/cables.css">\n<link rel="stylesheet" href="/css/columns.css">'


def test_the_rule():
    print("the cables' look — on samples of their own:")
    check(CablesCss.problems(GOOD_CABLES, GOOD_OTHERS) == [], "one dot, one line, drops of one period, a still twin for reduced motion — no remarks")

    def named(old, new, *parts, others=GOOD_OTHERS):
        got = CablesCss.problems(GOOD_CABLES.replace(old, new), others)
        return len(got) >= 1 and all(any(part in line for line in got) for part in parts)

    check(named(".pb-dot, .topology-handle, .cable-end::before { position: absolute; z-index: 4; width: 12px;", ".pb-dot, .topology-handle, .cable-end::before { position: absolute; z-index: 4; width: 20px;", "is not the 12px round dot"),
          "negative: a dot 20px wide (the bracket of 1.3.548) — named")
    check(named("border-radius: 50%; border: 2px solid m; }\n.pb-dot.out", "border-radius: 0 8px 8px 0; border: 2px solid m; }\n.pb-dot.out", "is not the 12px round dot"), "negative: a dot that is a bracket — named")
    check(named(".pb-dot.out, .topology-handle.output, .topology-handle.proxy-output { right: -8px; }", ".pb-dot.out, .topology-handle.output, .topology-handle.proxy-output { right: -24px; }",
                "do not all stand 8px out"), "negative: a dot that stands 24px out of the card — it would be cut by the column that scrolls — named")
    check(named("box-shadow: 0 0 0 4px a;", "box-shadow: 0 0 0 4px a; }\n.pb-dot.flowing { box-shadow: 0 0 0 9px a;", "ring"), "negative: Routing's ring is not the main board's — named")
    check(named("", "", "sizes a dot of its own", others=GOOD_OTHERS + "\n.topology-handle.server-input { height: 22px; }"), "negative: another rule gives a handle its height (nodes.css had one) — named")
    check(named(".cable-end { position: relative; }", "", "not positioned"), "negative: a head with a dot that is not positioned — its dot would stand at the corner of some far box — named")
    check(named("", "", "no bigger than the 12px dot", others=GOOD_OTHERS.replace("inset: -7px;", "inset: 0;")), "negative: the pointer's target round a handle is the dot itself (12px) — named")
    check(CablesCss.problems(GOOD_CABLES, GOOD_OTHERS.replace(".topology-handle::before { content: \"\"; position: absolute; inset: -7px; border-radius: 50%; }\n", "")) != [],
          "negative: no target round a handle at all — named")
    check(named("", "", "sizes a dot of its own", others=GOOD_OTHERS + "\n.pb-dot.out { width: 14px; }"), "negative: another rule gives Routing's dot its width — named")
    check(named("", "", "coloured dot inside a handle", others=GOOD_OTHERS + "\n.topology-handle.primary::after { background: var(--accent); }"), "negative: the coloured dot inside a handle is back — named")
    check(named("--cable-calm: x; ", "", "--cable-calm is not given"), "negative: a layer that takes no calm colour — named")
    check(named("stroke: var(--cable-calm); stroke-width: var(--cable-width);", "stroke: var(--accent); stroke-width: 1px;", "does not take the calm line"), "negative: a line of its own on both boards — named")
    check(named("", "", "sets a stroke outside cables.css", others=GOOD_OTHERS + "\n.pb-cables .pb-cable { stroke: red; }"), "negative: Routing's calm stroke set again in pool-board.css — named")
    check(named("", "", "sets a stroke outside cables.css", others=GOOD_OTHERS + "\n.topology-cable { stroke-width: 4; }"), "negative: the main board's cable thick again — named")
    check(named("", "", "dimmed by being idle", others=GOOD_OTHERS + "\n.topology-cable.consumer.idle { opacity: .13; }"), "negative: a cable dimmed for being idle — named")
    check(named("stroke-dasharray: 1px calc(var(--flow-period) - 1px);", "stroke-dasharray: 1px calc(var(--flow-period) - 3px);", "not one period"), "negative: a dash and a gap that are not one period — the loop jumps — named")
    check(named("stroke-dashoffset: calc(-1 * var(--flow-period))", "stroke-dashoffset: -40px", "exactly one period"), "negative: keyframes of their own length — named")
    check(named("animation-timing-function: linear;", "animation-timing-function: ease;", "linear and for ever"), "negative: drops that ease at every lap — they would pulse — named")
    check(named("pointer-events: none;", "animation-duration: 0.4s;", "set in the stylesheet", "take the pointer"), "negative: the lap set in the stylesheet, and a twin that takes the click — both named")
    check(named("animation: none; }", "opacity: 1; }", "no motion"), "negative: drops that move for a reader who asked for none — named")
    check(named(".cable-flow.back { animation-direction: reverse; }", "", "do not run the other way"), "negative: the way back runs the same way as the way there — named")
    check(named(".cable-flow.back { animation-direction: reverse; }", ".cable-flow.back { animation-direction: alternate; }", "do not run the other way"), "negative: the way back goes and comes back — named")
    check(named("animation-name: cableFlow, cableFlowIn;", "animation-name: cableFlow;", "do not come up"), "negative: the drops of a cable that begins to carry do not come up — named")
    check(named("animation-name: cableFlow, cableFlowOut;", "animation-name: cableFlow;", "do not go down"), "negative: the drops of a cable that stopped do not go down — named")
    check(named("", "", "leaves the cables that are not on it drawn", others=GOOD_OTHERS.replace(".pb.path-alone .pb-cables g:not(.on-path) { display: none; }\n", "")),
          "negative: a pinned path that leaves the other cables drawn — they would be under the pointer when the owner clicks to let it go — named")
    check(named("", "", "leaves the cables that are not on it drawn", others=GOOD_OTHERS.replace(".pb.path-alone .pb-cables g:not(.on-path) { display: none; }", ".pb.path-alone .pb-cables g:not(.on-path) { opacity: 0; }")),
          "negative: the other cables made clear — their wide twins are still found by the pointer — named")
    check(named("", "", "leaves the cables that are not on it drawn", others=GOOD_OTHERS.replace(".pb.path-alone .pb-cables g:not(.on-path) { display: none; }", ".pb.path-alone .pb-cables g:not(.on-path) { visibility: hidden; }")),
          "negative: the other cables hidden by visibility — `pointer-events: stroke` finds them still — named")
    check(named("", "", "only a pinned path does", others=GOOD_OTHERS + "\n.pb.tracing .pb-cables g:not(.on-path) { display: none; }"),
          "negative: pointing at a card hides the other cables too (they would flicker as the pointer goes over the board) — named")
    check(named("", "", "only a pinned path does", others=GOOD_OTHERS.replace(".pb.tracing .pb-cables g:not(.on-path) .pb-cable { opacity: .14; }", ".pb.tracing .pb-cables g:not(.on-path) .pb-cable { display: none; }")),
          "negative: pointing at a card takes the line of the other cables away — named")
    check(named("animation-timing-function: linear, ease-in;", "animation-timing-function: linear, ease-out;", "not mirrors"), "negative: the drops go down and come up by the same easing — a cable that carries again would have them jump — named")
    check(named("animation-timing-function: linear, ease-out;", "animation-timing-function: linear, ease-in;", "not mirrors"), "negative: the drops come up by the easing that goes down — named")
    check(named("animation-fill-mode: none, forwards;", "animation-fill-mode: none;", "come back at the end"), "negative: the drops that went down come back at the end — named")
    check(named(".cable-flow.rising { animation-name", ".cable-flow.rising { animation-fill-mode: forwards, forwards; animation-name", "hold their opacity for ever"),
          "negative: the drops that came up keep their last frame — the dimming of a hover would not show on them — named")
    check(named(".cable-flow.back.rising, .cable-flow.back.fading { animation-direction: reverse, normal; }", ".cable-flow.back.rising, .cable-flow.back.fading { animation-direction: reverse; }", "backwards too"),
          "negative: the way back runs the opacity backwards — they would go down while they come up — named")
    check(named("animation-timing-function: linear, ease-out;", "animation-timing-function: linear, ease-out; animation-duration: 0.6s, 0.6s;", "set where the twin is made"),
          "negative: the time of the coming up set in the stylesheet — named")
    check(named("@keyframes cableFlowIn { from { opacity: 0; } to { opacity: 1; } }", "@keyframes cableFlowIn { from { opacity: 0.5; } to { opacity: 1; } }", "from 0 to 1"),
          "negative: drops that come up from half — named")
    check(named("@keyframes cableFlowOut { from { opacity: 1; } to { opacity: 0; } }", "@keyframes cableFlowOut { from { opacity: 1; } to { opacity: 0.3; } }", "from 0 to 1 and from 1 to 0"),
          "negative: drops that go down to a third and stay — named")
    check(named(".cable-flow-stop { stop-color: var(--accent-strong, var(--accent)); }", "", "no colour of the stylesheet's"), "negative: a gradient with no colour of the stylesheet's — the drops would be black — named")
    check(named(".cable-flow.fading { display: none; }", "", "drawn, still"), "negative: a twin that is going down is drawn, still, for ever, when motion is off — named")
    check(named(".cable-flow, .cable-flow.rising, .cable-flow.fading { animation: none; }", ".cable-flow { animation: none; }", "no motion"), "negative: only the steady twin stands still when motion is off — named")
    print("the pages:")
    check(CablesCss.pages(("a.html", GOOD_PAGE)) == [], "a page that links base, cables and columns, in that order — no remarks")
    check(CablesCss.pages(("a.html", GOOD_PAGE.replace('<link rel="stylesheet" href="/css/cables.css">\n', ""))) == ["a.html does not link cables.css"], "negative: a page without cables.css — named")
    check(CablesCss.pages(("a.html", GOOD_PAGE.replace('<link rel="stylesheet" href="/css/columns.css">', ""))) == ["a.html does not link columns.css"], "negative: a page without columns.css — named")
    swapped = '<link rel="stylesheet" href="/css/cables.css">\n<link rel="stylesheet" href="/css/base.css">\n<link rel="stylesheet" href="/css/columns.css">'
    check(len(CablesCss.pages(("a.html", swapped))) == 1 and "before base.css" in CablesCss.pages(("a.html", swapped))[0], "negative: cables.css before base.css — named")


def test_the_pages():
    print("the stylesheets (static/css) and the pages:")
    cables = (STYLES / "cables.css").read_text(encoding="utf-8")
    others = "\n".join(path.read_text(encoding="utf-8") for path in sorted(STYLES.glob("*.css")) if path.name != "cables.css")
    bad = CablesCss.problems(cables, others)
    check(bad == [], "Routing and the main board end a cable in one dot, draw it in one line, and show a request in one way" + (f" — {'; '.join(bad)}" if bad else ""))
    pages = [(name, (ROOT / "static" / name).read_text(encoding="utf-8")) for name in ("index.html", "routing.html")]
    bad = CablesCss.pages(*pages)
    check(bad == [], "both boards link cables.css and columns.css after base.css" + (f" — {'; '.join(bad)}" if bad else ""))


test_the_rule()
test_the_pages()
print()
if _fail:
    print(f"FAILED ({len(_fail)}):")
    for m in _fail:
        print("  - " + m)
    sys.exit(1)
print("cables css snapshot holds")
