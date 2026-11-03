#!/usr/bin/env python3
"""Actual river-minnow.js (+ the minnow of river-fish.js): the few things that can break about how a minnow of the brook looks (1.3.593).

The owner, 2026-10-18: the old minnow was a beige oval with a dark one inside it; of three mockups drawn without the water he chose the
third, "the silver minnow". How it looks is the owner's eye and not these pins: the port was compared with the approved mockup once, by
what both ask the canvas to do, and drew the same in 300 of 300 drawings. What is pinned is what can break without anyone seeing it:
  - the shape: eight segments, a width for each node, one steady taper from the widest place to the stalk;
  - the smoothing of the outline, which lives in the code the two kinds of fish share: a node points half way between two segments, and
    a point on the body is found along the angle half way between two nodes;
  - a minnow is made with its tone and its pattern (seven blotches on each side, sixteen flecks);
  - a drawing leaves the canvas as it found it, since the next fish is drawn on the same one;
  - the shade lies on the flank away from the brook's own sun, whichever way the fish points, and nothing is lit (no shine: the owner, 2026-10-19);
  - the tail beats at the pace of the first version (1.4 a second and 1.3 more for every length a second: the owner, 2026-10-19);
  - the tail comes out of the stalk at the stalk's width (the owner's old complaint of a thick stub);
  - nothing of the old minnow is left, and the minnow has no sun of its own.

Run: python3 scripts/test_js_river_minnow.py
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
const { MinnowArt, MinnowShape } = await mod("river-minnow.js");
const { readFileSync } = await import("node:fs");
const { M } = core, { BROOK } = worldMod;
const reset = () => artMod.SoftShape.GRADIENTS.clear();
const r6 = (v) => +v.toFixed(6);
const sun2 = (() => { const f = Math.hypot(BROOK.sun.x, BROOK.sun.y); return { x: BROOK.sun.x / f, y: BROOK.sun.y / f }; })();

/** A canvas that writes down what it is asked: a call is [name, ...args], an assignment ["=name", value], a gradient ["gradient", {kind, args, stops}].
 *  save() and restore() keep the settings as a canvas does, so what a drawing leaves behind can be read in `now`. */
const canvas = () => {
  const log = [], kept = [];
  const now = { fillStyle: "#000000", strokeStyle: "#000000", lineWidth: 1, lineCap: "butt", lineJoin: "miter", globalAlpha: 1, globalCompositeOperation: "source-over" };
  const gradient = (kind, args) => ({ kind, args, stops: [], addColorStop(at, colour) { this.stops.push([at, colour]); } });
  return new Proxy({}, {
    get(_, p) {
      if (p === "log") return log;
      if (p === "now") return now;
      if (p in now) return now[p];
      if (p === "save") return () => { log.push(["save"]); kept.push({ ...now }); };
      if (p === "restore") return () => { log.push(["restore"]); Object.assign(now, kept.pop()); };
      if (p === "createLinearGradient" || p === "createRadialGradient") {
        return (...args) => { const g = gradient(p === "createLinearGradient" ? "linear" : "radial", args); log.push(["gradient", g]); return g; };
      }
      return (...args) => { log.push([p, ...args]); };
    },
    set(_, p, v) { now[p] = v; log.push(["=" + p, v]); return true; },
  });
};
const painter = new artMod.TopFishPainter();
/** A minnow of 36 px at (100, 100), made as the shoal makes one, then put into the pose asked: heading, amp, bend, phase, tone. */
const minnow = ({ seed = 3, ...pose } = {}) => {
  const m = new fishMod.MinnowShoal(null, { x: 0, y: 0 }, 1, 36, new core.Rng(seed)).fish[0];
  Object.assign(m, { x: 100, y: 100, len: 36, heading: 0, amp: 0, bend: 0, phase: 0, fin: 0, tone: 0, dart: 0, turnRate: 0 }, pose);
  m.buildSpine();
  return m;
};
/** A trout of 100 px in the same place. */
const trout = (pose = {}) => {
  const f = new fishMod.Trout(new core.Rng(3), { x: 100, y: 100 }, 100);
  Object.assign(f, { heading: 0, amp: 0, bend: 0, phase: 0 }, pose);
  f.buildSpine();
  return f;
};
const drawn = (m) => { const c = canvas(); MinnowArt.draw(c, m, painter); return c; };
const ofKind = (log, name) => log.filter((e) => e[0] === name);
const BENT = { heading: 0.7, amp: 0.3, phase: 1.0, bend: 0.4 };
const segs = (f) => f.spine.slice(1).map((p, i) => Math.atan2(p.y - f.spine[i].y, p.x - f.spine[i].x));
const near = (a, b, e = 1e-9) => Math.abs(M.wrap(a - b)) < e;
"""

PINS = [
    ("shape",
     "",
     "(() => { const h = MinnowShape.halfWidth, grid = Array.from({ length: 1001 }, (_, i) => i / 1000), top = Math.max(...grid.map(h)), at = grid.find((u) => h(u) === top);"
     " return { segments: MinnowShape.SEGMENTS, nodes: Array.from(MinnowShape.PROFILE, r6), widest: [r6(top), at], taper: grid.filter((u) => u >= at).every((u, i, a) => i === 0 || h(u) <= h(a[i - 1]) + 1e-12) }; })()",
     '{"segments":8,"nodes":[0.038,0.079789,0.081778,0.077752,0.069,0.056185,0.041,0.027447,0.018],"widest":[0.082111,0.193],"taper":true}',
     "eight segments (the old minnow had six) and a half width for each of the nine nodes; the widest place is a fifth of the way down and from there to the stalk the width only falls"),
    ("outline_bends_through_the_mean",
     "",
     "(() => { const probe = (f) => { const s = segs(f), n = s.length, a = f.spine.map((p) => p.a), k = 3, u = (k + 0.5) / n, prof = new Float32Array(n + 1).fill(0.05), p = f.bodyPoint(u, 1, prof),"
     " want = f.smooth ? a[k] + M.wrap(a[k + 1] - a[k]) / 2 : a[k];"
     " return { smooth: f.smooth, nodesAreMeans: s.slice(0, n - 1).every((v, i) => near(a[i + 1], M.meanAngle(v, s[i + 1]))), pointAngle: near(p.a, want), pointIsNodeAngle: near(p.a, a[k], 1e-3) }; };"
     " return { minnow: probe(minnow(BENT)), trout: probe(trout(BENT)), seam: r6(M.meanAngle(3.1, -3.1)) }; })()",
     '{"minnow":{"smooth":true,"nodesAreMeans":true,"pointAngle":true,"pointIsNodeAngle":false},"trout":{"smooth":true,"nodesAreMeans":true,"pointAngle":true,"pointIsNodeAngle":false},"seam":3.141593}',
     "a fish's node points half way between the two segments it joins, and a point between two nodes lies along the angle half way between theirs, for a minnow and for a trout; "
     "the mean of two directions goes the short way round the circle (3.1 and -3.1 meet at pi)"),
    ("minnow_is_made_with_its_look",
     "",
     "(() => { const fish = new fishMod.MinnowShoal(null, { x: 0, y: 0 }, 12, 36, new core.Rng(9)).fish, sides = (m, s) => m.pattern.blotches.filter((b) => Math.sign(b.v) === s).length;"
     " return { n: fish.length, nodes: [...new Set(fish.map((m) => m.spine.length))], smooth: fish.every((m) => m.smooth), tone: fish.every((m) => m.tone >= -12 && m.tone <= 12),"
     " toneVaries: new Set(fish.map((m) => m.tone)).size, patterns: [...new Set(fish.map((m) => m.pattern.blotches.length + '/' + m.pattern.flecks.length))], sides: [...new Set(fish.map((m) => sides(m, -1) + '/' + sides(m, 1)))] }; })()",
     '{"n":12,"nodes":[9],"smooth":true,"tone":true,"toneVaries":12,"patterns":["14/16"],"sides":["7/7"]}',
     "a shoal of twelve is twelve minnows of nine nodes each, every one with its own tone within 12 and a pattern of seven blotches on each side and sixteen flecks"),
    ("draw_leaves_the_canvas_as_found",
     "",
     "(() => { const c = drawn(minnow(BENT)), log = c.log; return { balanced: ofKind(log, 'save').length === ofKind(log, 'restore').length, left: c.now, clip: ofKind(log, 'clip').length,"
     " composites: log.filter((e) => e[0] === '=globalCompositeOperation').map((e) => e[1]), noTextures: ['drawImage', 'createPattern', 'getImageData', 'putImageData'].every((n) => ofKind(log, n).length === 0) }; })()",
     '{"balanced":true,"left":{"fillStyle":"#000000","strokeStyle":"#000000","lineWidth":1,"lineCap":"butt","lineJoin":"miter","globalAlpha":1,"globalCompositeOperation":"source-over"},"clip":1,"composites":["multiply","source-over"],"noTextures":true}',
     "every save has its restore and the settings come back as they were (compositing, line cap, widths, styles): the next fish, the trout and the striders are drawn on the same canvas; "
     "the compositing goes multiply, source-over (nothing is lit: no screen); the skin is clipped once; no textures"),
    ("shade_lies_away_from_the_brooks_sun",
     "",
     "(() => { const lanes = (log, op) => log.slice(log.findIndex((e) => e[0] === '=globalCompositeOperation' && e[1] === op)).filter((e) => e[0] === 'gradient' && e[1].kind === 'linear').map((e) => e[1]);"
     " const heads = [0, Math.PI / 2, Math.PI, -Math.PI / 2, 0.7, -2.0], seen = heads.map((heading) => { const m = minnow({ heading }), log = drawn(m).log, g = lanes(log, 'multiply')[0], p = m.spine[1], o = [g.args[0] - p.x, g.args[1] - p.y];"
     " return { shadeToward: o[0] * sun2.x + o[1] * sun2.y > 0, lit: log.some((e) => e[0] === '=globalCompositeOperation' && e[1] === 'screen'), lanes: lanes(log, 'multiply').length }; }); return seen; })()",
     '[{"shadeToward":false,"lit":false,"lanes":2},{"shadeToward":false,"lit":false,"lanes":2},{"shadeToward":false,"lit":false,"lanes":2},{"shadeToward":false,"lit":false,"lanes":2},{"shadeToward":false,"lit":false,"lanes":2},{"shadeToward":false,"lit":false,"lanes":2}]',
     "whichever way the fish points, the shade lies on the flank away from the brook's sun (the sun is BROOK.sun, not a number of its own), and nothing is laid on the other flank: no stroke is composited with screen, the minnow shines nowhere"),
    ("tail_beats_as_in_the_first_version",
     "",
     "(() => { const hz = (lengthsPerSecond) => { const m = minnow(); m.speed = lengthsPerSecond * m.len; const before = m.phase; m.animate(1); return r6((m.phase - before) / M.TAU); };"
     " return [0, 0.5, 1.5, 6].map(hz); })()",
     '[1.4,2.05,3.35,9.2]',
     "a minnow beats its tail 1.4 times a second at rest and 1.3 more for every length a second it swims, as in the first version (the owner, 2026-10-19: \"return the movements from the very first version\"): "
     "2.05 at its usual half a length a second, 3.35 at 1.5, 9.2 in a dart at 6"),
    ("tail_grows_out_of_the_stalk",
     "",
     "(() => { const m = minnow({ phase: 4.9 }), log = drawn(m).log, n = m.spine.length - 1, P = m.spine[n], root = log.find((e) => e[0] === 'moveTo'), last = ofKind(log, 'bezierCurveTo')[1],"
     " rr = [last[5], last[6]], lr = [root[1], root[2]];"
     " return { rootOverStalk: r6(Math.hypot(lr[0] - rr[0], lr[1] - rr[1]) / (2 * m.widths[n])), centred: Math.hypot((lr[0] + rr[0]) / 2 - P.x, (lr[1] + rr[1]) / 2 - P.y) < 1e-9 }; })()",
     '{"rootOverStalk":0.98,"centred":true}',
     "the root of the tail is 98% of the stalk's width and centred on its end: the fin comes out of the stalk with no thick stub and no step"),
    ("old_minnow_is_gone",
     "",
     "(() => { const fishSrc = readFileSync(process.env.JS_ROOT + '/river-fish.js', 'utf8'), art = readFileSync(process.env.JS_ROOT + '/river-minnow.js', 'utf8'), minnowClass = /class Minnow extends Swimmer[\\s\\S]*?\\n}\\n/.exec(fishSrc)[0];"
     " return { oldProfile: /MINNOW_PROFILE/.test(fishSrc), delegates: /MinnowArt\\.draw\\(ctx, this, painter\\)/.test(minnowClass), oldWedgeAndBlades: /tailPath\\(ctx, k|pairedFins\\(/.test(fishSrc), shine: /'screen'/.test(art),"
     " sunFromBrook: /BROOK\\.sun/.test(art), ownSun: /-0\\.55|-0\\.83|LIGHT/.test(art) }; })()",
     '{"oldProfile":false,"delegates":true,"oldWedgeAndBlades":false,"shine":false,"sunFromBrook":true,"ownSun":false}',
     "nothing of the beige oval is left in river-fish.js (nor the old wedge of a tail and blades of fins, which the trout had too), the art composites nothing with screen, and the minnow hands its drawing to MinnowArt; "
     "the light is read from the brook's sun, with no sun of the minnow's own"),
]


def main():
    return run("js river minnow", ".probe_river_minnow.tmp.mjs", PREAMBLE, PINS)


if __name__ == "__main__":
    sys.exit(main())
