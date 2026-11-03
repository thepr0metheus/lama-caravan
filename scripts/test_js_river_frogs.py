#!/usr/bin/env python3
"""Actual river-frogs.js and river-frog.js: the frogs of the brook and its tadpoles (1.3.605).

The owner, 2026-10-21, of the mockups of the frogs of Adjara: "Д, all of them, a few of each"; "the big ones twice smaller, all of them no
bigger than the middle of the big ones"; "the plop quiet"; "tadpoles, yes". How a frog looks is the owner's eye and not these pins (he
judged the mockups by their pictures in the brook). The brook is laid out by BrookLife itself, with stand-ins for the leaves' and the ferns'
pictures (their size is all a frog reads of them). What is pinned is what can break without anyone seeing it:
  - the cast and its size: who lives where, how many, and that no frog and no tadpole is longer than the owner's limit, whatever its kind;
  - the places: on a stone that stands out of the water, afloat in slow water by a bank, on the bank at the edge, on a fern frond, in the
    shallows; and never under a frond or the branch, where a frog would be out of sight (the mockup put a frog and the tadpoles there);
  - a startled frog: into the water with one quiet drop and a ring, the minnows scattering, kicks under the water, up with its eyes out, and
    back to its own place; a tree frog to another frond, and into the water only with no other clump near;
  - a floater stays at its place in the current (the mockup's went 352 px down the stream in 45 s);
  - the tongue takes a fly in reach in front, even one a trout is rising to, and not one too far or behind (that one is turned to);
  - the layers: what is drawn above the water, under it, both; and on which side of the fern fronds;
  - a drawing leaves the canvas as it found it, builds no gradient twice, lays the brook's own sun over the skin, and nothing shines;
  - the tadpoles stay in the water near their place and scatter from a hand;
  - the brook calls the frogs where it must, and makes them with a stream of their own (the rest of the brook is laid out as before).

Run: python3 scripts/test_js_river_frogs.py
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
const artMod = await mod("river-art.js");
const lifeMod = await mod("river-life.js");
const { FrogKinds, FrogPose, FrogArt, FrogInk, FrogLight, FrogSkin } = await mod("river-frog.js");
const { Frog, FrogPond } = await mod("river-frogs.js");
const { readFileSync } = await import("node:fs");
const { M, Rng, Noise } = core, { BROOK } = worldMod;
// what a drawing keeps for good is cleared before every pin
const reset = () => { artMod.SoftShape.GRADIENTS.clear(); FrogLight.ACROSS.clear(); FrogLight.ROUND = null; FrogInk.CACHE.clear(); };
const r3 = (v) => +v.toFixed(3);
const src = (name) => readFileSync(process.env.JS_ROOT + "/" + name, "utf8");

/** A canvas that writes down what it is asked: a call is [name, ...args], an assignment ["=name", value]; save() and restore() keep the settings. */
const canvas = (w = 800, h = 450, name = "") => {
  const log = [], kept = [];
  const now = { fillStyle: "#000000", strokeStyle: "#000000", lineWidth: 1, lineCap: "butt", globalAlpha: 1, globalCompositeOperation: "source-over" };
  const gradient = () => ({ stops: [], addColorStop(at, colour) { this.stops.push([at, colour]); } });
  return new Proxy({}, {
    get(_, p) {
      if (p === "log") return log;
      if (p === "now") return now;
      if (p === "name") return name;
      if (p === "canvas") return { width: w, height: h };
      if (p in now) return now[p];
      if (p === "save") return () => { log.push(["save"]); kept.push({ ...now }); };
      if (p === "restore") return () => { log.push(["restore"]); Object.assign(now, kept.pop()); };
      if (p === "createImageData") return (iw, ih) => ({ width: iw, height: ih, data: new Uint8ClampedArray(iw * ih * 4) });
      if (p === "createLinearGradient" || p === "createRadialGradient") return (...args) => Object.assign(gradient(), { args });
      return (...args) => { log.push([p, ...args]); };
    },
    set(_, p, v) { now[p] = v; log.push(["=" + p, v]); return true; },
  });
};
const ofKind = (log, name) => log.filter((e) => e[0] === name);
FrogSkin.canvasOf = (w, h) => { const c = { width: w, height: h, ctx: null, getContext() { return c.ctx || (c.ctx = canvas(w, h)); } }; return c; };
// the still pictures are Sprites, whose layers ask the page for canvases
const pageCanvas = () => { const c = { width: 0, height: 0, ctx: null, getContext() { return c.ctx || (c.ctx = canvas(c.width, c.height)); } }; return c; };
const makeElement = document.createElement;
document.createElement = (tag) => (tag === "canvas" ? pageCanvas() : makeElement(tag));

/**
 * A brook laid out by BrookLife.populate itself, with no page: the leaves' and the ferns' pictures are stand-ins of their size (all a frog
 * reads of a frond is its length and angle). The rings, the sounds and the minnows' scares are written down; the hand is `life.pointerState`.
 */
const brookOf = (w = 1440, h = 900) => {
  const noise = new Noise(new Rng(BROOK.layoutSeed)), ch = new worldMod.Channel(w, h, new Rng(BROOK.layoutSeed), noise), C = ch.C;
  const rings = [], sounds = [], scared = [];
  const life = Object.create(lifeMod.BrookLife.prototype);
  Object.assign(life, { scene: { sound: (fn) => fn({ plink: (t, o) => sounds.push(o) }, 0) }, channel: ch, ripples: { disturb: (...a) => rings.push(a) },
    canopy: { lightAt: () => 1 }, noise, rng: new Rng(7), C, time: 0, dpr: 1, pointerState: { inside: false, speed: 0, x: 0, y: 0 }, flies: [], leaves: [], falling: [],
    leafArt: { pick: () => ({ w: C * 0.05 }) }, fernArt: { fronds: [0.2, 0.22, 0.24, 0.26, 0.27].map((k) => ({ w: Math.ceil(C * k * 1.04) })) } });
  life.populate(new Rng(BROOK.layoutSeed + 9));
  life.shoal.spook = (...a) => scared.push(a);
  return { ch, life, pond: life.frogs, rings, sounds, scared };
};
/** Steps a pond for `sec` seconds at `dt`, the brook's clock with it; `each` sees every step. */
const live = (b, sec, dt = 1 / 30, each = null) => { for (let t = 0; t < sec; t += dt) { b.life.time += dt; b.pond.update(dt); if (each) each(b.life.time); } };
/** The states a frog went through, each once in a row. */
const watch = (b, f, sec, dt = 1 / 30) => { const seen = [f.state]; live(b, sec, dt, () => { if (seen[seen.length - 1] !== f.state) seen.push(f.state); }); return seen; };
const cast = (pond) => pond.frogs.map((f) => f.kind.id + ":" + f.home.kind).reduce((o, k) => ({ ...o, [k]: (o[k] || 0) + 1 }), {});
"""

PINS = [
    ("cast_and_size",
     "",
     "(() => { const sizes = Object.fromEntries(Object.values(FrogKinds.ALL).map((k) => [k.id, k.size])), out = {};"
     " for (const [w, h] of [[1440, 900], [1000, 600], [1920, 1080], [600, 1000]]) { const b = brookOf(w, h), C = b.ch.C;"
     " out[w + 'x' + h] = { cast: cast(b.pond), tadpoles: b.pond.school ? b.pond.school.tadpoles.length : 0,"
     " longest: r3(Math.max(...b.pond.frogs.map((f) => f.len / C), ...(b.pond.school ? b.pond.school.tadpoles.map((t) => t.len / C) : [0]))) }; }"
     " const rng = new Rng(3), big = { size: 0.04 }, draws = Array.from({ length: 500 }, () => FrogKinds.lengthOf(big, 1000, rng));"
     " return { largest: FrogKinds.LARGEST, sizes, out, aBigKindHeldDown: Math.max(...draws) <= 26 + 1e-9 }; })()",
     '{"largest":0.026,"sizes":{"ridibundus":0.026,"macrocnemis":0.022,"orientalis":0.02,"caucasicus":0.02},"out":{"1440x900":{"cast":{"ridibundus:rock":2,"ridibundus:float":1,"macrocnemis:bank":1,"orientalis:fern":2,"caucasicus:shallow":2},"tadpoles":5,"longest":0.026},"1000x600":{"cast":{"ridibundus:rock":2,"ridibundus:float":1,"macrocnemis:bank":1,"orientalis:fern":2,"caucasicus:shallow":2},"tadpoles":5,"longest":0.026},"1920x1080":{"cast":{"ridibundus:rock":2,"ridibundus:float":1,"macrocnemis:bank":1,"orientalis:fern":2,"caucasicus:shallow":2},"tadpoles":5,"longest":0.026},"600x1000":{"cast":{"ridibundus:rock":2,"ridibundus:float":1,"macrocnemis:bank":1,"orientalis:fern":2,"caucasicus:shallow":1},"tadpoles":5,"longest":0.026}},"aBigKindHeldDown":true}',
     "the cast of the variant Д, a few of each: two marsh frogs on stones and one afloat, a brown frog on the bank, two tree frogs on fronds, two parsley frogs in the "
     "shallows, five tadpoles; the marsh frog is half the mockup's (0.052) and no frog or tadpole is longer than 0.026 of the short side (the owner, 2026-10-21); a tall "
     "narrow brook (a phone) has room for fewer; negative: a kind of any size is held down to the limit"),
    ("homes_fit_and_in_sight",
     "",
     "(() => { const out = {};"
     " for (const [w, h] of [[1440, 900], [1000, 600], [1920, 1080], [600, 1000]]) { const b = brookOf(w, h), ch = b.ch, p = b.pond;"
     " const fit = (f) => { const H = f.home, d = ch.sample(H.x, H.y), slow = Math.hypot(d.vx, d.vy) < ch.vmax * 0.35, shore = ch.shore(ch.sOf(H.x, H.y), ch.nOf(H.x, H.y));"
     " if (H.kind === 'rock') return H.rock.emerges && H.rock.inside(H.x, H.y) > 0; if (H.kind === 'float') return d.depth > 0.18 && d.depth < 0.6 && slow;"
     " if (H.kind === 'bank') return shore < 0 && shore > -f.len; if (H.kind === 'shallow') return d.depth > 0.04 && d.depth < 0.12;"
     " return b.life.ferns.includes(H.clump) && H.frond === H.clump.fronds[H.clump.fronds.length - 1]; };"
     " out[w + 'x' + h] = { fit: p.frogs.every(fit), inSight: p.frogs.every((f) => f.home.kind === 'fern' ? !p.underBranch(f) : !p.covered(f.home)),"
     " tadpolesInSight: !!p.school && !p.covered(p.school.home), inView: p.frogs.every((f) => p.inView(f, 0.02)) }; }"
     " const b = brookOf(), p = b.pond, clump = b.life.ferns[0], fr = clump.fronds[0], L = fr.sprite.w * fr.scale * 0.5;"
     " const under = { x: clump.x + Math.cos(fr.angle) * L, y: clump.y + Math.sin(fr.angle) * L }, behind = { x: clump.x - Math.cos(fr.angle) * L, y: clump.y - Math.sin(fr.angle) * L };"
     " const C = b.ch.C, branch = { x: C * 0.2, y: C * 0.1 }; b.life.branch.x = b.life.branch.y = 1e6;"
     " const hidden = new FrogPond(b.life, new Rng(BROOK.layoutSeed + 21));"
     " return { out, frond: [p.underFrond(under), p.underFrond(behind)], branch: p.underBranch(branch), everywhereCovered: [hidden.frogs.length, hidden.school] }; })()",
     '{"out":{"1440x900":{"fit":true,"inSight":true,"tadpolesInSight":true,"inView":true},"1000x600":{"fit":true,"inSight":true,"tadpolesInSight":true,"inView":true},"1920x1080":{"fit":true,"inSight":true,"tadpolesInSight":true,"inView":true},"600x1000":{"fit":true,"inSight":true,"tadpolesInSight":true,"inView":true}},"frond":[true,false],"branch":true,"everywhereCovered":[0,null]}',
     "every frog lives where its kind does — on a stone that stands out of the water, afloat in slow water (depth 0.18–0.6), on the bank within its length of the "
     "edge, in the shallows (depth 0.04–0.12), on the longest frond of a fern clump — in all four brooks, and in sight: never under a frond or the alder branch (the "
     "mockup put a frog and the tadpoles out of sight there); negative: a point along a frond is under it and one behind the clump is not, the branch's corner is "
     "covered; a brook covered everywhere gets no frogs and no tadpoles rather than hidden ones"),
    ("startled_frog_goes_in_and_comes_back",
     "",
     "(() => { const b = brookOf(), p = b.pond, f = p.frogs.find((g) => g.home.kind === 'rock'), home = { x: f.x, y: f.y };"
     " p.startle(f, { x: f.x - Math.cos(f.heading) * f.len, y: f.y - Math.sin(f.heading) * f.len });"
     " let backAt = null; const seen = [f.state];"
     " live(b, 60, 1 / 30, (t) => { if (seen[seen.length - 1] !== f.state) seen.push(f.state); if (backAt === null && seen.length > 2 && f.state === 'sit') backAt = t; });"
     " return { seen, backWithin45s: backAt !== null && backAt < 45, onItsPlace: Math.hypot(f.x - home.x, f.y - home.y) < 1e-6, sounds: b.sounds,"
     " rings: b.rings.map((r) => r3(r[2])), scared: b.scared.length }; })()",
     '{"seen":["crouch","jump","swim","float","return","jump","sit"],"backWithin45s":true,"onItsPlace":true,"sounds":[{"f":560,"ring":0.28,"gain":0.04}],"rings":[0.6,0.3,0.5],"scared":1}',
     "a frog on a stone, startled: it gathers itself, jumps into the water, kicks under it, comes up with its eyes out, swims back and jumps out onto its own place "
     "(to the pixel) within 45 s; going in it makes one drop, the quiet plop, and one ring no bigger than 0.6 (a fly's landing is 0.35, a hand's plop 2.6), and the "
     "minnows near it scatter; coming up and getting out make two small rings more"),
    ("floater_keeps_its_place",
     "",
     "(() => { const b = brookOf(), p = b.pond, f = p.frogs.find((g) => g.home.kind === 'float'); let far = 0;"
     " live(b, 120, 1 / 30, () => { far = Math.max(far, Math.hypot(f.x - f.home.x, f.y - f.home.y) / f.len); });"
     " const d = brookOf(), q = d.pond, g = q.frogs.find((h) => h.home.kind === 'float'), ax = d.ch.axis; g.x += ax.x * g.len * 6; g.y += ax.y * g.len * 6;"
     " const back = watch(d, g, 40);"
     " const fl = brookOf(), r = fl.pond, h = r.frogs.find((k) => k.home.kind === 'float'); r.startle(h, { x: h.x + h.len, y: h.y }); const startled = watch(fl, h, 60);"
     " return { far: far < 2.6, back, home: Math.hypot(g.x - g.home.x, g.y - g.home.y) / g.len <= 2.5, startled, near: Math.hypot(h.x - h.home.x, h.y - h.home.y) / h.len <= 2.5 }; })()",
     '{"far":true,"back":["float","return","float"],"home":true,"startled":["swim","float","return","float"],"near":true}',
     "a frog afloat in the current stays near its place for two minutes, within 2.6 of its lengths (the mockup's went 352 px down the stream in 45 s); "
     "negative: carried six lengths down the stream it swims back under the water and floats at its place again; startled, it dives, swims off under the water, "
     "comes up with its eyes out and swims back to its place"),
    ("tongue_takes_a_fly_in_reach",
     "",
     "(() => { const b = brookOf(), p = b.pond, f = p.frogs.find((g) => g.home.kind === 'rock'), a = f.heading;"
     " const at = (d, ang = 0) => ({ x: f.x + Math.cos(a + ang) * f.len * d, y: f.y + Math.sin(a + ang) * f.len * d, alive: true, claimedBy: null });"
     " const try1 = (fly, sec = 1 / 30) => { f.tongue = 0; f.turnTo = null; f.heading = a; b.life.flies = [fly]; live(b, sec); return { taken: !fly.alive, turning: f.turnTo !== null }; };"
     " const inReach = at(1.2), taken = try1(inReach), tongue = f.tongueTo.map(r3);"
     " const claimed = at(1.2, 0.3); claimed.claimedBy = { name: 'a trout' };"
     " const tree = b.pond.frogs.find((g) => g.home.kind === 'fern'), treeFly = { x: tree.x + Math.cos(tree.heading) * tree.len, y: tree.y + Math.sin(tree.heading) * tree.len, alive: true };"
     " b.life.flies = [treeFly]; live(b, 1 / 30);"
     " return { inReach: taken, tongue, tooFar: try1(at(1.7)), behind: try1(at(1.0, Math.PI)), behindLater: try1(at(1.0, Math.PI), 3), claimed: try1(claimed), treeFrog: treeFly.alive,"
     " reach: FrogPond.REACH }; })()",
     '{"inReach":{"taken":true,"turning":false},"tongue":[1.2,0],"tooFar":{"taken":false,"turning":false},"behind":{"taken":false,"turning":true},"behindLater":{"taken":true,"turning":false},"claimed":{"taken":true,"turning":false},"treeFrog":true,"reach":1.45}',
     "a fly 1.2 lengths ahead of a frog on a stone is taken at once with the tongue, which reaches out to where it was; one a trout is rising to, too (the trout lets "
     "a fly that is gone go); negative: one 1.7 lengths ahead is not (the reach is 1.45 from its middle), one behind it is not taken at once but turned to, and taken "
     "when the frog has turned; a tree frog on a frond takes no fly off the water"),
    ("tree_frog_hops_between_fronds",
     "",
     "(() => { const b = brookOf(), p = b.pond, f = p.frogs.find((g) => g.home.kind === 'fern'), was = f.home.frond;"
     " p.startle(f, { x: f.x + 5, y: f.y }); const seen = watch(b, f, 3), on = p.frondPoint(f.home.clump, f.home.frond, f.home.along, b.life.time);"
     " const lone = brookOf(), q = lone.pond, g = q.frogs.find((h) => h.home.kind === 'fern'); g.home.clump.fronds = [g.home.frond]; lone.life.ferns = [g.home.clump];"
     " q.startle(g, { x: g.x + 5, y: g.y });"
     " return { seen, other: f.home.frond !== was, onTheFrond: Math.hypot(f.x - on.x, f.y - on.y) < 1e-6, wet: seen.some((s) => s === 'swim' || s === 'float'), alone: watch(lone, g, 3) }; })()",
     '{"seen":["jump","sit"],"other":true,"onTheFrond":true,"wet":false,"alone":["crouch","jump","swim"]}',
     "a startled tree frog jumps to another frond, of its own clump or of one near it, sits on it and sways with it, never touching the water; "
     "negative: with no other frond in reach (a clump of one frond and no other clump near) it goes into the water as any frog does"),
    ("hand_sends_frogs_in",
     "",
     "(() => { const one = (speed, dist, plop = null) => { const b = brookOf(), p = b.pond, f = p.frogs.find((g) => g.home.kind === 'rock'), C = b.ch.C;"
     " if (plop !== null) p.plop(f.x + C * plop, f.y, C * 0.4); else { b.life.pointerState = { inside: true, speed, x: f.x + f.len * dist, y: f.y }; live(b, 1 / 30); }"
     " return f.state; };"
     " return { fastNear: one(400, 3), slowNear: one(300, 3), fastFar: one(400, 3.6), plopNear: one(0, 0, 0.39), plopFar: one(0, 0, 0.41) }; })()",
     '{"fastNear":"crouch","slowNear":"sit","fastFar":"sit","plopNear":"crouch","plopFar":"sit"}',
     "a hand moving fast (380 px/s and more) within 3.5 lengths of a frog sends it off, and so does a hand's plop within 0.4 of the short side; "
     "negative: a slow hand, a fast one further off, a plop further off leave it sitting"),
    ("layers_and_levels",
     "",
     "(() => { const b = brookOf(), p = b.pond, calls = [], keep = {};"
     " for (const n of ['whole', 'aboveWater', 'wading', 'limbs', 'silhouette']) { keep[n] = FrogArt[n]; FrogArt[n] = (ctx, f) => calls.push(ctx.name + ' ' + n + ' ' + f.kind.id + ':' + f.home.kind); }"
     " for (const f of p.frogs) f.blink = 0.1;"
     " try { p.drawTop(canvas(800, 450, 'low'), 'low'); p.drawTop(canvas(800, 450, 'high'), 'high'); p.drawUnder(canvas(800, 450, 'u'), canvas(800, 450, 's')); }"
     " finally { Object.assign(FrogArt, keep); }"
     " const count = (prefix) => [...new Set(calls.filter((c) => c.startsWith(prefix + ' ')).map((c) => c.slice(prefix.length + 1)))].sort();"
     " const f = new Frog(FrogKinds.ALL.caucasicus, { kind: 'shallow', x: 0, y: 0, heading: 0 }, 10, 1), g = new Frog(FrogKinds.ALL.ridibundus, { kind: 'rock', x: 0, y: 0, heading: 0 }, 10, 1);"
     " const layer = (fr) => Object.fromEntries(['sit', 'crouch', 'jump', 'swim', 'return', 'float'].map((s) => { fr.state = s; fr.jump = { s: 0.5, water: true }; return [s, fr.layer]; }));"
     " return { low: count('low'), high: count('high'), under: count('u'), shade: count('s'), layers: { shallow: layer(f), rock: layer(g) } }; })()",
     '{"low":["aboveWater ridibundus:float","wading caucasicus:shallow","whole macrocnemis:bank","whole ridibundus:rock"],"high":["whole orientalis:fern"],"under":["limbs caucasicus:shallow","silhouette caucasicus:shallow","silhouette ridibundus:float","whole ridibundus:float"],"shade":["silhouette caucasicus:shallow","silhouette macrocnemis:bank","silhouette orientalis:fern","silhouette ridibundus:float","silhouette ridibundus:rock"],"layers":{"shallow":{"sit":"wade","crouch":"top","jump":"top","swim":"under","return":"under","float":"split"},"rock":{"sit":"top","crouch":"top","jump":"top","swim":"under","return":"under","float":"split"}}}',
     "drawn live (a frog that blinks is): above the water before the ferns, the frogs on stones and on the bank whole, the floater's head and eyes, the waders' bodies; after the ferns, the tree "
     "frogs; under the surface: the floater's body and the waders' legs, each tinted by the water; every frog throws a shadow; what a frog's state puts where"),
    ("still_pictures_of_frogs_at_rest",
     "",
     "(() => { const b = brookOf(), p = b.pond, f = p.frogs.find((g) => g.home.kind === 'rock'), whole = FrogArt.whole; let painted = 0;"
     " FrogArt.whole = (...a) => { painted++; return whole(...a); };"
     " try { const above = () => { const c = canvas(800, 450, 'top'); p.drawTop(c, 'low'); p.drawTop(c, 'high'); return c; };"
     " const first = above(), once = painted; above(); const again = painted - once;"
     " f.heading += 5 * Math.PI / 180; above(); const turned = painted - once - again;"
     " f.blink = 0.1; above(); f.blink = 0; const blinkingDrawnLive = painted - once - again - turned;"
     " const u = canvas(800, 450, 'u'), s = canvas(800, 450, 's'), n = (layers) => p.frogs.filter((g) => layers.includes(g.layer)).length; p.drawUnder(u, s);"
     " return { onePictureEach: ofKind(first.log, 'drawImage').length === p.frogs.length, paintedOnce: once === n(['top']), again, turned, blinkingDrawnLive,"
     " shadowsArePictures: ofKind(s.log, 'drawImage').length === p.frogs.length, onlyTadpolesFilled: ofKind(s.log, 'fill').length === p.school.tadpoles.length,"
     " underArePictures: ofKind(u.log, 'drawImage').length === n(['split', 'wade']) }; }"
     " finally { FrogArt.whole = whole; } })()",
     '{"onePictureEach":true,"paintedOnce":true,"again":0,"turned":1,"blinkingDrawnLive":1,"shadowsArePictures":true,"onlyTadpolesFilled":true,"underArePictures":true}',
     "a frog at rest (sitting, or afloat and still) is laid on the brook as a picture of its own, one drawImage each, painted once: drawn stroke by stroke the "
     "frogs above the water cost the brook 2.6 ms a frame against its 10.4, as pictures 0.05; the picture is painted again when the sun falls across the frog "
     "another way (a turn of 5 degrees) and a frog that blinks is drawn live; the shadows of frogs at rest are their pictures' silhouettes (the only shapes "
     "filled in the shade layer are the tadpoles'), and the floater's body and the waders' legs go under the water as pictures too"),
    ("quiet_plop",
     "",
     "(() => { const P = FrogPond.PLOP, drops = [...src('river-life.js').matchAll(/plink\\(t, \\{ f: (\\d+), ring: ([\\d.]+), gain: ([\\d.]+)/g)].map((m) => ({ f: +m[1], ring: +m[2], gain: +m[3] }));"
     " const take = drops.find((d) => d.f === 640), hand = drops.find((d) => d.f === 330), quietest = Math.min(...drops.map((d) => d.gain));"
     " return { plop: P, brook: drops.length, between: [hand.f < P.f && P.f < take.f, take.ring < P.ring && P.ring < hand.ring], quieterThanAnyOther: P.gain < quietest }; })()",
     '{"plop":{"f":560,"ring":0.28,"gain":0.04},"brook":3,"between":[true,true],"quieterThanAnyOther":true}',
     "a frog's plop is one drop like every sound on the water: lower and longer than a trout's take, higher and shorter than a hand's plop, and quieter than "
     "anything else on the water (the owner, 2026-10-21: \"the plop quiet\")"),
    ("draw_leaves_the_canvas_as_found",
     "",
     "(() => { const b = brookOf(), f = b.pond.frogs.find((g) => g.home.kind === 'rock'), c = canvas(), log = c.log, ink = FrogInk.of(f.kind);"
     " FrogArt.whole(c, f, f.pose()); const first = artMod.SoftShape.GRADIENTS.size, skin = f.skin;"
     " FrogArt.whole(c, f, f.pose()); FrogArt.aboveWater(c, f, ink, 0.2); FrogArt.wading(c, f, ink, 0.2);"
     " return { balanced: ofKind(log, 'save').length === ofKind(log, 'restore').length, left: c.now,"
     " composites: [...new Set(log.filter((e) => e[0] === '=globalCompositeOperation').map((e) => e[1]))], gradientTables: [first, artMod.SoftShape.GRADIENTS.size],"
     " skinOnce: f.skin === skin, skin: [skin.width, skin.height], lightMaps: FrogLight.ACROSS.size }; })()",
     '{"balanced":true,"left":{"fillStyle":"#000000","strokeStyle":"#000000","lineWidth":1,"lineCap":"butt","globalAlpha":1,"globalCompositeOperation":"source-over"},"composites":["overlay"],"gradientTables":[10,10],"skinOnce":true,"skin":[154,102],"lightMaps":1}',
     "every save has its restore and the canvas is left as it was found, whether a frog is drawn whole, afloat or wading; the light goes over the skin with "
     "overlay and nothing else is composited; the soft ellipses make their gradients on the first drawing and none after it; the skin is painted once, "
     "154 x 102 px; one grey map of the light for the way the frog faces"),
    ("light_from_the_brooks_sun_and_no_shine",
     "",
     "(() => { const grey = (c) => +/rgb\\((\\d+)/.exec(c)[1], sun = Math.atan2(BROOK.sun.y, BROOK.sun.x), out = [];"
     " for (const heading of [0, 1, 2, -2.5, Math.PI]) { const g = FrogLight.across(canvas(), FrogLight.key(heading)), [x0, y0, x1, y1] = g.args, stops = g.stops.map((s) => grey(s[1]));"
     " out.push({ towardTheSun: Math.abs(M.wrap(Math.atan2(y1 - y0, x1 - x0) + heading - sun)) < 0.04, lighterThere: stops[stops.length - 1] > stops[0], lightest: stops[stops.length - 1] / 255 <= FrogLight.LIGHTEST + 0.003 }); }"
     " const code = src('river-frog.js') + src('river-frogs.js'), spark = Object.values(FrogKinds.ALL).map((k) => FrogInk.of(k).spark[0][1]);"
     " return { out, lightest: FrogLight.LIGHTEST, spark: [...new Set(spark)], sparkFainterThanTheTrouts: FrogInk.SPARK < 0.45, shine: /'screen'|'lighter'|'color-dodge'|\\.spec\\b|glint/.test(code),"
     " tablesMadeAfresh: /SoftShape\\.draw\\([^;]*,\\s*\\[\\[/.test(code), brooksSun: /BROOK\\.sun/.test(src('river-frog.js')) }; })()",
     '{"out":[{"towardTheSun":true,"lighterThere":true,"lightest":true},{"towardTheSun":true,"lighterThere":true,"lightest":true},{"towardTheSun":true,"lighterThere":true,"lightest":true},{"towardTheSun":true,"lighterThere":true,"lightest":true},{"towardTheSun":true,"lighterThere":true,"lightest":true}],"lightest":0.62,"spark":["rgba(255,253,240,0.34)"],"sparkFainterThanTheTrouts":true,"shine":false,"tablesMadeAfresh":false,"brooksSun":true}',
     "whichever way a frog faces, the grey map over its back runs toward the brook's sun (BROOK.sun, not a sun of its own) and is lighter there, and no lighter "
     "than 0.62; the one light that is not the sun's map is a catchlight in the eye fainter than the trout's; nothing shines (no screen or lighter compositing, "
     "no glints), and no table of stops is written where a soft ellipse is drawn (it would be made afresh every frame)"),
    ("tadpoles_stay_in_the_shallows",
     "",
     "(() => { const b = brookOf(), sc = b.pond.school, ch = b.ch, home = sc.home; let wet = true, far = 0;"
     " live(b, 120, 1 / 30, () => { for (const t of sc.tadpoles) { if (!ch.isWater(t.x, t.y)) wet = false; far = Math.max(far, Math.hypot(t.x - home.x, t.y - home.y) / ch.C); } });"
     " const t0 = sc.tadpoles[0], hand = { inside: true, speed: 600, x: t0.x + t0.len, y: t0.y }, before = Math.hypot(t0.x - hand.x, t0.y - hand.y);"
     " b.life.pointerState = hand; live(b, 0.5); b.life.pointerState = { inside: false, speed: 0, x: 0, y: 0 };"
     " return { count: sc.tadpoles.length, wet, near: far < 0.12, scattered: Math.hypot(t0.x - hand.x, t0.y - hand.y) > before * 2, length: r3(t0.len / ch.C) <= FrogKinds.LARGEST }; })()",
     '{"count":5,"wet":true,"near":true,"scattered":true,"length":true}',
     "five tadpoles: for two minutes they stay in the water (by the brook's own rule, Channel.isWater) and within 0.12 of the short side of their place; "
     "a fast hand by one sends it off, more than twice as far"),
    ("brook_calls_the_frogs",
     "",
     "(() => { const life = src('river-life.js'), body = (head) => { const i = life.indexOf(head); return life.slice(i, life.indexOf('\\n  }\\n', i)); };"
     " const update = body('  update(dt, t) {'), top = body('  drawTop(ctx, t) {'), under = body('  drawUnder(u, s) {'), populate = body('  populate(rng) {'), dbl = life.slice(life.indexOf(\"kind === 'double'\"));"
     " const at = (s) => top.indexOf(s);"
     " return { update: update.includes('this.frogs.update(dt);'), under: under.includes('this.frogs.drawUnder(u, s);'),"
     " order: at(\"this.frogs.drawTop(ctx, 'low')\") > 0 && at(\"this.frogs.drawTop(ctx, 'low')\") < at('this.ferns') && at('this.ferns') < at(\"this.frogs.drawTop(ctx, 'high')\") && at(\"this.frogs.drawTop(ctx, 'high')\") < at('this.falling'),"
     " plop: dbl.includes('this.frogs.plop(p.x, p.y, C * 0.4);'), lastInPopulate: populate.trim().split('\\n').pop().trim() === 'this.frogs = new FrogPond(this, new Rng(BROOK.layoutSeed + 21));' }; })()",
     '{"update":true,"under":true,"order":true,"plop":true,"lastInPopulate":true}',
     "the brook moves the frogs every frame, draws them under the water with the fish, above it before the ferns and after them (before the falling leaves and the "
     "branch), hands them a hand's plop, and makes them last in its layout with a stream of their own: the rest of the brook is laid out as it was"),
]


def main():
    return run("js river frogs", ".probe_river_frogs.tmp.mjs", PREAMBLE, PINS)


if __name__ == "__main__":
    sys.exit(main())
