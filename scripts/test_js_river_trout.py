#!/usr/bin/env python3
"""Actual river-trout.js (+ the trout of river-fish.js): the few things that can break about how a trout of the brook looks and moves (1.3.595).

The owner, 2026-10-18: of four mockups of the trout, drawn without the water, he chose the third and the fourth together ("the motion from
the third, the light and the volume from the fourth"), and then "yes, it suits, do it". On 2026-10-19 he asked for the movements, and all the
behaviour, of the very first version back, and the look to stay: the trout swims as the first version did (the third mockup's motion is gone),
and is drawn as the fourth's. How it looks is the owner's eye and not these pins: the drawing was compared with the approved mockup by what both
ask the canvas to do over 40 seconds of motion (201 drawings did not differ, the skin pixels have the same checksum). What is pinned is what can
break without anyone seeing it:
  - the shape: sixteen segments, a width for each node, the stalk thin, one steady taper from the widest place to the stalk, one nose;
  - the motion, the first version's (the owner, 2026-10-19): the pace of the tail, its reach at rest, swimming and in a turn, and the line of the body;
  - a drawing leaves the canvas as it found it, and builds no gradient twice (a table of stops made afresh on every frame would grow without end);
  - the light on each strip of the body is a little lighter on the flank toward the brook's own sun, whichever way the strip points, and no brighter than 0.7 (no shine);
  - the tail comes out of the stalk at the stalk's width (the owner's old complaint of a thick stub);
  - the painter holds as many points as a body has (a typed array drops what is written past its end without a word);
  - nothing of the old trout is left, and the trout has no sun of its own.

Run: python3 scripts/test_js_river_trout.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _js_pins import run  # noqa: E402

PREAMBLE = r"""
import "./_js_globals.mjs";
import { pathToFileURL } from "node:url";
const mod = (name) => import(pathToFileURL(process.env.JS_ROOT + "/" + name).href);
const core = await mod("river-core.js");
const worldMod = await mod("river-world.js");
const fishMod = await mod("river-fish.js");
const artMod = await mod("river-art.js");
const { TroutArt, TroutShape, TroutSkin, TroutLight } = await mod("river-trout.js");
const { readFileSync } = await import("node:fs");
const { M } = core, { BROOK } = worldMod;
// what a drawing keeps for good is cleared before every pin
const reset = () => { artMod.SoftShape.GRADIENTS.clear(); TroutLight.STRIPS.clear(); };
const r6 = (v) => +v.toFixed(6);
const sun2 = (() => { const f = Math.hypot(BROOK.sun.x, BROOK.sun.y); return { x: BROOK.sun.x / f, y: BROOK.sun.y / f }; })();

/** A canvas that writes down what it is asked: a call is [name, ...args], an assignment ["=name", value]; save() and restore() keep the settings. */
const canvas = (w = 800, h = 450) => {
  const log = [], kept = [];
  const now = { fillStyle: "#000000", strokeStyle: "#000000", lineWidth: 1, lineCap: "butt", lineJoin: "miter", globalAlpha: 1, globalCompositeOperation: "source-over" };
  const gradient = () => ({ stops: [], addColorStop(at, colour) { this.stops.push([at, colour]); } });
  return new Proxy({}, {
    get(_, p) {
      if (p === "log") return log;
      if (p === "now") return now;
      if (p === "canvas") return { width: w, height: h };
      if (p in now) return now[p];
      if (p === "save") return () => { log.push(["save"]); kept.push({ ...now }); };
      if (p === "restore") return () => { log.push(["restore"]); Object.assign(now, kept.pop()); };
      if (p === "getTransform") return () => ({ a: 4, b: 0, c: 0, d: 4, e: 300, f: 225 });
      if (p === "createImageData") return (iw, ih) => ({ width: iw, height: ih, data: new Uint8ClampedArray(iw * ih * 4) });
      if (p === "createLinearGradient" || p === "createRadialGradient") return () => gradient();
      return (...args) => { log.push([p, ...args]); };
    },
    set(_, p, v) { now[p] = v; log.push(["=" + p, v]); return true; },
  });
};
// a page's canvases, made by hand: the skin and the grey maps take one each
const fakeCanvas = () => { const c = { width: 0, height: 0, ctx: null, getContext() { return c.ctx || (c.ctx = canvas(c.width, c.height)); } }; return c; };
TroutSkin.canvasOf = (w, h) => { const c = fakeCanvas(); c.width = w; c.height = h; return c; };
TroutLight.canvasOf = () => fakeCanvas();
const painter = new artMod.TopFishPainter();
/** A trout of 100 px at (100, 100), facing east and at rest, put into the pose asked. */
const trout = (pose = {}) => {
  const f = new fishMod.Trout(new core.Rng(3), { x: 100, y: 100 }, 100);
  Object.assign(f, { heading: 0, phase: 0, finPhase: 0, bend: 0 }, pose);
  f.buildSpine();
  return f;
};
/** The same trout, swum for `sec` seconds at a speed (px/s) and a turn rate (rad/s). */
const swum = (sec, speed, turnRate, pose = {}) => {
  const f = trout(pose);
  f.speed = speed; f.turnRate = turnRate;
  for (let i = 0; i < Math.round(sec * 60); i++) f.animate(1 / 60);
  f.buildSpine();
  return f;
};
const ofKind = (log, name) => log.filter((e) => e[0] === name);
const drawn = (f) => { const c = canvas(); TroutArt.draw(c, f, painter); return c; };
"""

PINS = [
    ("shape",
     "",
     "(() => { const h = TroutShape.halfWidth, grid = Array.from({ length: 1001 }, (_, i) => i / 1000), top = Math.max(...grid.map(h)), at = grid.find((u) => h(u) === top);"
     " return { segments: TroutShape.SEGMENTS, nodes: trout().spine.length, profile: Array.from(TroutShape.PROFILE, r6), widest: [r6(top), at], stalk: r6(h(1)),"
     " taper: grid.filter((u) => u >= at).every((u, i, a) => i === 0 || h(u) <= h(a[i - 1]) + 1e-12), nose: TroutShape.NOSE }; })()",
     '{"segments":16,"nodes":17,"profile":[0.05,0.062977,0.070307,0.078702,0.084265,0.088539,0.088739,0.086681,0.082443,0.076644,0.070359,0.063447,0.0545,0.044821,0.034713,0.024816,0.019],"widest":[0.089021,0.34],"stalk":0.019,"taper":true,"nose":0.03}',
     "sixteen segments (the old trout had twelve) and a half width for each of the seventeen nodes; the widest place is a third of the way down, from there to the stalk the width only falls "
     "and the stalk is thin (0.019 of the length, as the owner asked after the thick stub); the snout is blunt and rounded (0.050 of the length across at its tip, near the first version's 0.0527); the nose of the outline is one number"),
    ("motion",
     "",
     "(() => { const at = (f) => ({ eff: r6(f.eff), amp: r6(f.amp), bend: r6(f.bend) }), cycles = (f) => r6(f.phase / M.TAU);"
     " const rest = swum(5, 0, 0), usual = swum(5, 30, 0), swim = swum(5, 140, 0), turn = swum(5, 0, 2), line = trout({ amp: 0.2, phase: 1, bend: 0.4 });"
     " return { rest: [at(rest), cycles(rest)], usual: [at(usual), cycles(usual)], swim: [at(swim), cycles(swim)], turn: at(turn), tail: [r6(swim.tailAng), r6(swim.tailSpread)],"
     " line: [0, 0.5, 1].map((u) => r6(line.angleAt(u, 0))), eyesLook: [r6(rest.look.x), r6(rest.look.y)] }; })()",
     '{"rest":[{"eff":0,"amp":0.08,"bend":0},7],"usual":[{"eff":0.214286,"amp":0.089,"bend":0},8.95],"swim":[{"eff":1,"amp":0.122,"bend":0},16.1],"turn":{"eff":0,"amp":0.18,"bend":-0.44},"tail":[0.132411,0.071178],"line":[0,0.134095,0.451108],"eyesLook":[1,0]}',
     "a trout swims as in the first version (the owner, 2026-10-19: \"return the movements from the very first version\"): the tail goes round 1.4 times a second at rest and 1.3 more for every length a second "
     "(1.79 at its usual 0.3 of a length a second, 3.22 at 1.4); its reach is 0.08 at rest and grows with the speed and the turn; a turn at 2 rad/s bends the body by -0.44; "
     "the tail's swing and spread are the first version's tail's; the line of the body is the beat that grows toward the tail and the bend; a trout at rest looks ahead"),
    ("draw_leaves_the_canvas_as_found",
     "",
     "(() => { const f = swum(3, 60, 0.5, { heading: 0.4 }), first = drawn(f), size1 = artMod.SoftShape.GRADIENTS.size, log = first.log; const second = drawn(f), size2 = artMod.SoftShape.GRADIENTS.size;"
     " return { balanced: ofKind(log, 'save').length === ofKind(log, 'restore').length, left: first.now, clip: ofKind(log, 'clip').length,"
     " composites: [...new Set(log.filter((e) => e[0] === '=globalCompositeOperation').map((e) => e[1]))], gradientTables: [size1, size2], skin: [f.skin.W, f.skin.H],"
     " noPatterns: ['createPattern', 'getImageData'].every((n) => ofKind(log, n).length === 0) }; })()",
     '{"balanced":true,"left":{"fillStyle":"#000000","strokeStyle":"#000000","lineWidth":1,"lineCap":"butt","lineJoin":"miter","globalAlpha":1,"globalCompositeOperation":"source-over"},"clip":1,"composites":["overlay","source-over"],"gradientTables":[10,10],"skin":[400,80],"noPatterns":true}',
     "every save has its restore and the settings come back as they were (compositing, line cap, widths, styles); the body is clipped once, the light goes over it with overlay and nothing is composited with screen (no shine); "
     "the soft ellipses make ten gradients (four for the skin's spots, five for the eye, one for the adipose fin) on the first drawing and none after it; the skin is painted once, 400 x 80 px"),
    ("light_is_lighter_toward_the_brooks_sun",
     "",
     "(() => { const grey = (colour) => +/rgb\\((\\d+)/.exec(colour)[1]; const out = [];"
     " for (const ang of [0, Math.PI / 2, Math.PI, -Math.PI / 2, 0.7, -2.0]) { const s = TroutLight.strip(ang), key = Math.round(M.wrap(ang) / (M.TAU / 90)), a = key * M.TAU / 90;"
     " const g = s.diff.stops.map((t) => grey(t[1])), n = { x: -Math.sin(a), y: Math.cos(a) };"
     " out.push({ brighterRight: g[24] > g[0], sunOnRight: n.x * sun2.x + n.y * sun2.y > 0, lightest: Math.max(...g) / 255 <= TroutLight.LIGHTEST + 0.005 }); }"
     " return { out, maps: Object.keys(TroutLight.strip(0)), lightest: TroutLight.LIGHTEST, cached: TroutLight.strip(0) === TroutLight.strip(0.01), stops: TroutLight.strip(0).diff.stops.length }; })()",
     '{"out":[{"brighterRight":false,"sunOnRight":false,"lightest":true},{"brighterRight":true,"sunOnRight":true,"lightest":true},{"brighterRight":true,"sunOnRight":true,"lightest":true},{"brighterRight":false,"sunOnRight":false,"lightest":true},{"brighterRight":false,"sunOnRight":false,"lightest":true},{"brighterRight":false,"sunOnRight":false,"lightest":true}],"maps":["diff"],"lightest":0.7,"cached":true,"stops":25}',
     "whichever way a strip of the body points, its grey map is lighter on the flank toward the brook's sun (the sun is BROOK.sun, not a number of its own) and no strip is lighter than 0.7; "
     "there is one map for a strip, the diffuse one: no map for a shine; the maps are made once for every 4 degrees and shared (0 and 0.01 radian are one map)"),
    ("tail_grows_out_of_the_stalk",
     "",
     "(() => { const f = trout({ tailAng: 0, tailSpread: 0.05 }), c = canvas(), n = f.spine.length - 1, P = f.spine[n], got = TroutArt.tailPath(c, f), log = c.log, root = log.find((e) => e[0] === 'moveTo'), last = ofKind(log, 'bezierCurveTo')[1],"
     " lr = [root[1], root[2]], rr = [last[5], last[6]];"
     " return { rootOverStalk: r6(Math.hypot(lr[0] - rr[0], lr[1] - rr[1]) / (2 * f.widths[n])), centred: Math.hypot((lr[0] + rr[0]) / 2 - P.x, (lr[1] + rr[1]) / 2 - P.y) < 1e-9,"
     " stalk: r6(f.widths[n] / f.len), forked: got.R > 0 }; })()",
     '{"rootOverStalk":0.98,"centred":true,"stalk":0.019,"forked":true}',
     "the root of the tail is 98% of the stalk's width and centred on its end: the fin comes out of the stalk with no thick stub and no step"),
    ("painter_holds_every_point",
     "",
     "(() => { const f = trout({ heading: 0.3, beat: 0.2, phase: 1 }), p = new artMod.TopFishPainter(16), c = canvas(), n = f.spine.length - 1, s = f.spine[n], w = f.widths[n];"
     " p.outline(c, f.spine, f.widths, 3);"
     " const lines = ofKind(c.log, 'lineTo'), left = lines[0], want = [s.x - Math.sin(s.a) * w, s.y + Math.cos(s.a) * w];"
     " return { points: n + 1, buffer: p.L.length, tailLeftCorner: Math.hypot(left[1] - want[0], left[2] - want[1]) < 1e-3, open: (() => { const o = canvas(); p.outline(o, f.spine, f.widths, 3, 0, 0, true);"
     " return [ofKind(o.log, 'closePath').length, ofKind(o.log, 'moveTo').length, ofKind(c.log, 'closePath').length, ofKind(c.log, 'moveTo').length]; })() }; })()",
     '{"points":17,"buffer":34,"tailLeftCorner":true,"open":[0,2,1,1]}',
     "a painter made for 16 points draws a body of 17 with its whole tail (the buffer grows to hold it; a typed array would have dropped the last point without a word); "
     "an open outline leaves out the cut across the tail end: no closePath, one more moveTo"),
    ("old_trout_is_gone",
     "",
     "(() => { const fishSrc = readFileSync(process.env.JS_ROOT + '/river-fish.js', 'utf8'), art = readFileSync(process.env.JS_ROOT + '/river-trout.js', 'utf8');"
     " return { oldProfile: /TROUT_PROFILE|TROUT_LOOK|class TroutShape/.test(fishSrc), oldBlades: /pairedFins|tailPath\\(ctx, k/.test(fishSrc), oldDots: /this\\.spots/.test(fishSrc),"
     " delegates: /TroutArt\\.draw\\(ctx, this, painter\\)/.test(fishSrc), sunFromBrook: /BROOK\\.sun/.test(art), ownSun: /-0\\.83|\\bLIGHT\\b|\\bELEV\\b/.test(art),"
     " tablesMadeAfresh: /SoftShape\\.draw\\([^;]*,\\s*\\[\\[/.test(art), shine: /'screen'|glints|TroutSkin\\.SHINE|\\.spec\\b/.test(art + fishSrc) }; })()",
     '{"oldProfile":false,"oldBlades":false,"oldDots":false,"delegates":true,"sunFromBrook":true,"ownSun":false,"tablesMadeAfresh":false,"shine":false}',
     "nothing of the flat stick is left in river-fish.js: no old profile or look, no blades and wedge, no dots; the trout hands its drawing to TroutArt; the light is read from the brook's sun, "
     "with no sun of the trout's own; no table of stops is written inline where a soft ellipse is drawn (it would be made afresh every frame); and nothing shines: no screen compositing, no sparks, no specular map"),
]


def main():
    return run("js river trout", ".probe_river_trout.tmp.mjs", PREAMBLE, PINS)


if __name__ == "__main__":
    sys.exit(main())
