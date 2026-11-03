/*
 * river-trout.js: how a trout of the brook looks (the owner, 2026-10-18: of four mockups of the trout, drawn without the water from
 * the old code, he chose the third and the fourth together, and then "yes, it suits, do it"; and on 2026-10-19: "remove the shine, they
 * should be darker, a trout should blend with the bed", and a snout rounder, like the first version's). The old trout was a flat stick: an olive body
 * with three darker bands inside it, 55 round dots, two blades for fins, a wedge for a tail and a black dot for an eye. This one has a
 * body that narrows steadily into a thin stalk, a skin painted once (spots with faint halos, red spots with a blue ring, flecks, the
 * lateral line, a hint of scales) and bent along the spine in strips, light that is worked out for each strip (so that the flank
 * toward the sun is a little lighter and the far one shaded: the back rounds off, and nothing shines), gills that open and close, an eye
 * with a socket, fins made of rays, an adipose fin, and a forked tail that grows out of the stalk at the stalk's own width.
 *
 * What the trout does (hold, chase, flee …) and how its body moves is river-fish.js (Trout); this only draws what it hands over:
 * the spine and the phases it keeps, how hard it turns, how fast it swims, where it looks and its seed.
 */
import { FinFan, SoftShape } from "./river-art.js";
import { M, Rng } from "./river-core.js";
import { BROOK } from "./river-world.js";

/** The trout's half width along its length, as a share of the length. */
export class TroutShape {
  /** The body's segments: sixteen, so that the outline bends smoothly (the old trout had twelve). */
  static SEGMENTS = 16;
  /** How far ahead of the head's first point the painted snout reaches, in body lengths: the `nose` of the outline, the body's and the shadow's. */
  static NOSE = 0.03;
  /** Half width at a share of the length: a blunt, rounded snout like the first version's (0.0527 across at its tip; 0.050 here, the owner, 2026-10-19: "not so sharp, more rounded, as in the first version"), widest behind the gills, then one steady taper into a thin stalk. */
  static KEYS = Object.freeze([[0, 0.050], [0.012, 0.054], [0.03, 0.058], [0.055, 0.062], [0.085, 0.066], [0.13, 0.071], [0.19, 0.079],
    [0.26, 0.085], [0.33, 0.089], [0.45, 0.086], [0.58, 0.075], [0.70, 0.062], [0.80, 0.047], [0.88, 0.034], [0.94, 0.0245], [1, 0.019]]);

  /** The half width at `u`, snout (0) to tail (1): a smooth curve through the keys (Catmull-Rom). */
  static halfWidth(u) {
    const keys = TroutShape.KEYS;
    u = M.clamp(u, 0, 1);
    let i = 0;
    while (i < keys.length - 2 && keys[i + 1][0] < u) i++;
    const p0 = keys[Math.max(i - 1, 0)][1], p1 = keys[i][1], p2 = keys[i + 1][1], p3 = keys[Math.min(i + 2, keys.length - 1)][1];
    const t = (u - keys[i][0]) / (keys[i + 1][0] - keys[i][0]), t2 = t * t, t3 = t2 * t;
    return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
  }

  /** The half width at each node of a spine of `SEGMENTS` segments. */
  static profile() {
    const n = TroutShape.SEGMENTS, w = new Float32Array(n + 1);
    for (let i = 0; i <= n; i++) w[i] = TroutShape.halfWidth(i / n);
    return w;
  }

  static PROFILE = TroutShape.profile();
}

/** The skin: painted once for each trout on a small canvas, in the skin's own units, and laid along the body in strips. */
export class TroutSkin {
  /** The length of the fish the skin is painted for, in the skin's own units: a trout of any length wears it scaled. */
  static REF = 100;
  /** Pixels of the skin to a unit: four give a skin of 400 x 80 px, enough for a trout of 90 to 200 px at twice the pixel density. */
  static SCALE = 4;
  /** Colour from the dark back (0) to the duller rim (1 and past it), [position, [r, g, b]]: the bed's own tones, about 0.6 of the brightness the skin had at first. */
  static ACROSS = Object.freeze([[0, [28, 28, 19]], [0.14, [36, 34, 22]], [0.40, [58, 52, 30]], [0.62, [86, 76, 44]], [0.84, [108, 96, 58]], [1.0, [124, 112, 74]], [1.2, [132, 120, 84]]]);
  /** The soft spots, as tables of stops for SoftShape: a black spot, its faint halo, a red spot and its blue ring. */
  static INK = Object.freeze([[0, 'rgba(24,20,12,0.92)'], [0.84, 'rgba(26,22,14,0.9)'], [1, 'rgba(26,22,14,0)']]);
  static HALO = Object.freeze([[0, 'rgba(206,198,160,0.18)'], [0.62, 'rgba(206,198,160,0.14)'], [1, 'rgba(206,198,160,0)']]);
  static RED = Object.freeze([[0, 'rgba(166,64,44,0.95)'], [0.72, 'rgba(140,44,30,0.94)'], [1, 'rgba(110,30,22,0)']]);
  static BLUE = Object.freeze([[0, 'rgba(150,176,196,0.28)'], [0.6, 'rgba(150,176,196,0.22)'], [1, 'rgba(150,176,196,0)']]);

  /** A canvas of w x h px; a test names another maker, since node has no page. */
  static canvasOf = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };

  /** The colour across the body at `v` (0 the back, 1 the rim), as [r, g, b]. */
  static acrossColor(v) {
    const across = TroutSkin.ACROSS;
    let i = 0;
    while (i < across.length - 2 && across[i + 1][0] < v) i++;
    const a = across[i], b = across[i + 1], t = M.clamp((v - a[0]) / (b[0] - a[0]), 0, 1);
    return [M.lerp(a[1][0], b[1][0], t), M.lerp(a[1][1], b[1][1], t), M.lerp(a[1][2], b[1][2], t)];
  }

  /**
   * The marks of one fish, in the skin's units: black spots small on the back and near the head, larger on the flanks, many with a
   * pale halo and some doubled; and up to thirteen red ones along the flanks. No two touch.
   */
  static spots(seed) {
    const rng = new Rng(seed * 31 + 5), black = [], red = [], L = TroutSkin.REF, half = TroutShape.halfWidth;
    for (let tries = 0; tries < 3200 && black.length < 160; tries++) {
      const u = M.lerp(0.07, 0.92, rng.next()), side = rng.next() < 0.5 ? -1 : 1, v = 0.06 + Math.pow(rng.next(), 0.8) * 0.8, w = half(u);
      if (u < 0.13 && v > 0.4) continue;                 // the eyes are there
      const flank = M.smooth(0.3, 0.75, v), head = M.smooth(0.06, 0.24, u), tail = 1 - 0.35 * M.smooth(0.7, 0.92, u);
      const r = M.lerp(M.lerp(0.0030, 0.0062, rng.next()), M.lerp(0.0055, 0.0105, rng.next()), flank) * M.lerp(0.5, 1, head) * tail;
      const X = u * L, D = side * v * w * L;
      if (black.some((s) => Math.hypot(s.X - X, s.D - D) < (s.r + r) * L * 1.2)) continue;
      black.push({
        u, v: side * v, X, D, r, stretch: M.lerp(1, 1.5, rng.next() * rng.next()), rot: (rng.next() - 0.5) * 0.6,
        halo: flank > 0.25 && v < 0.8 && rng.next() < 0.6, haloK: 1.7 + rng.next() * 0.5,
        twin: rng.next() < 0.25 ? { dx: (rng.next() - 0.5) * 2.2, dy: (rng.next() - 0.5) * 1.6, k: 0.55 + rng.next() * 0.2 } : null,
      });
    }
    for (let tries = 0; tries < 600 && red.length < 13; tries++) {
      const u = M.lerp(0.24, 0.76, rng.next()), side = red.length % 2 ? 1 : -1, v = M.lerp(0.4, 0.7, rng.next()), r = M.lerp(0.0065, 0.0100, rng.next());
      const X = u * L, D = side * v * half(u) * L;
      if (black.some((s) => Math.hypot(s.X - X, s.D - D) < (s.r + r) * L * 1.05)) continue;
      if (red.some((s) => Math.hypot(s.X - X, s.D - D) < (s.r + r) * L * 2.4)) continue;
      red.push({ u, v: side * v, X, D, r });
    }
    return { black, red };
  }

  /**
   * Paints the skin of the trout with this seed: the colour across the body from the dark back to the pale rim, mottled by three
   * noises and a grain, darker at the head and warmer at the tail, then flecks, spots, the lateral line and a hint of scales.
   * The noises are measured in units, so a skin of any scale shows the same marks.
   */
  static bake(seed, S = TroutSkin.SCALE) {
    const L = TroutSkin.REF, W = Math.round(L * S), H = Math.round(L * 0.2 * S), f = S / 8, half = TroutShape.halfWidth;
    const canvas = TroutSkin.canvasOf(W, H), g = canvas.getContext('2d'), img = g.createImageData(W, H), d = img.data;
    for (let y = 0; y < H; y++) {
      const dd = (y - H / 2) / (L * S);
      for (let x = 0; x < W; x++) {
        const u = x / W, w = half(u), v = Math.min(Math.abs(dd) / w, 1.2);
        const c = TroutSkin.acrossColor(v), head = 1 - M.smooth(0.10, 0.24, u), tail = M.smooth(0.74, 0.95, u);
        const n1 = M.vnoise(x / (5.2 * f), y / (2.6 * f), seed), n2 = M.vnoise(x / (15 * f), y / (7.5 * f), seed + 7), n3 = M.vnoise(x / (2.6 * f), y / (2.2 * f), seed + 13);
        const m = (n1 * 0.5 + n2 * 0.5 - 0.5) * 2, calm = 1 - 0.65 * M.smooth(0.75, 1.0, v);
        let k = 1 + m * 0.34 * calm;
        k *= 1 - 0.15 * M.smooth(0.58, 0.72, n3) * (1 - M.smooth(0.2, 0.9, v));
        const grain = (M.hash2(x, y, seed + 3) - 0.5) * 9, i = (y * W + x) * 4;
        d[i] = M.clamp(c[0] * M.lerp(1, 0.86, head) * M.lerp(1, 1.07, tail) * k + grain, 0, 255);
        d[i + 1] = M.clamp(c[1] * M.lerp(1, 0.97, head) * M.lerp(1, 0.99, tail) * k + grain, 0, 255);
        d[i + 2] = M.clamp(c[2] * M.lerp(1, 0.84, head) * M.lerp(1, 0.82, tail) * k + grain * 0.8, 0, 255);
        d[i + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
    const marks = TroutSkin.spots(seed), px = (X) => X * S, py = (D) => H / 2 + D * S, rng = new Rng(seed + 9), U = L * S;
    for (let i = 0; i < 520; i++) {                      // fine flecks on the back
      const u = M.lerp(0.1, 0.9, rng.next()), side = rng.next() < 0.5 ? -1 : 1, v = rng.next() * 0.62, r = M.lerp(0.0014, 0.0027, rng.next()) * U;
      g.fillStyle = 'rgba(18,17,10,0.38)'; g.beginPath(); g.arc(px(u * L), py(side * v * half(u) * L), r, 0, M.TAU); g.fill();
    }
    for (const s of marks.black) {
      const X = px(s.X), Y = py(s.D), r = s.r * U;
      if (s.halo) SoftShape.draw(g, X, Y, r * s.haloK * s.stretch, r * s.haloK, s.rot, TroutSkin.HALO);
      SoftShape.draw(g, X, Y, r * s.stretch, r, s.rot, TroutSkin.INK);
      if (s.twin) SoftShape.draw(g, X + s.twin.dx * r, Y + s.twin.dy * r, r * s.twin.k * s.stretch, r * s.twin.k, s.rot + 0.5, TroutSkin.INK);
    }
    for (const s of marks.red) {
      const X = px(s.X), Y = py(s.D), r = s.r * U;
      SoftShape.draw(g, X, Y, r * 1.95, r * 1.95, 0, TroutSkin.BLUE);
      SoftShape.draw(g, X, Y, r * 1.08, r, 0.3, TroutSkin.RED);
    }
    g.fillStyle = 'rgba(206,198,160,0.08)';              // the lateral line
    for (const side of [-1, 1]) for (let u = 0.2; u < 0.9; u += 0.006) { g.beginPath(); g.arc(px(u * L), py(side * 0.3 * half(u) * L), 0.5 * S * 0.16 + 0.4, 0, M.TAU); g.fill(); }
    g.strokeStyle = 'rgba(20,18,10,0.05)'; g.lineWidth = 0.9 * f;   // a hint of scales
    for (let X = 0.22 * W; X < 0.94 * W; X += 0.012 * L * S) { g.beginPath(); for (let k = -1; k <= 1; k += 2) { g.moveTo(X, 0); g.lineTo(X + k * H * 0.6, H); } g.stroke(); }
    return { canvas, W, H, S };
  }
}

/**
 * The light on the body. Each thin strip of the body is lit for the way it points: the strip's own grey map (how much light a point
 * across it gets, from the sun's direction and the round of the back) is laid over the skin with `overlay`, so that the flank toward
 * the sun is a little lighter and the far one shaded. Nothing shines: no sheen, no sparks (the owner, 2026-10-19). A map is made once
 * for every 4 degrees of a strip's direction and shared by every trout.
 */
export class TroutLight {
  /** The grey maps of the strips, by direction: gradients. */
  static STRIPS = new Map();
  /** The canvases the strips are drawn on, as big as a trout's box (they only grow), kept for each canvas a trout is drawn on. */
  static PAPERS = new WeakMap();
  /** Where the strips lie along the body: thin at the snout and the tail, where the body's width changes fast. */
  static US = (() => { const u = [0], run = (a, b, n) => { for (let i = 1; i <= n; i++) u.push(a + (b - a) * i / n); }; run(0, 0.15, 30); run(0.15, 0.8, 16); run(0.8, 1, 22); return u; })();
  static CORNERS = Object.freeze([[-1, -1], [1, -1], [-1, 1], [1, 1]]);
  /** The brightest grey a map has: the lit flank is no more than a little lighter than the skin (0.5 leaves it as it is). */
  static LIGHTEST = 0.7;
  /** A canvas of the given size or any size: the same maker as the skin's. */
  static canvasOf = () => document.createElement('canvas');

  /** The direction toward the brook's sun. */
  static sun() {
    return [BROOK.sun.x, BROOK.sun.y, BROOK.sun.z];
  }

  /** The grey map of a strip that runs in direction `ang`: across it, as over a round back, from the left flank (-1) to the right (1). */
  static strip(ang) {
    const key = Math.round(M.wrap(ang) / (M.TAU / 90));
    let s = TroutLight.STRIPS.get(key);
    if (s) return s;
    const c = TroutLight.canvasOf().getContext('2d'), a = key * M.TAU / 90, px = -Math.sin(a), py = Math.cos(a), L = TroutLight.sun();
    const diff = c.createLinearGradient(0, -1, 0, 1);
    for (let i = 0; i <= 24; i++) {
      const t = i / 24, v = t * 2 - 1, up = Math.sqrt(Math.max(0, 1 - v * v));
      const nl = v * (px * L[0] + py * L[1]) + up * L[2], lam = nl - 0.66;
      const grey = M.clamp(lam >= 0 ? 0.5 + lam * 0.5 : 0.5 + lam * 0.45, 0.2, TroutLight.LIGHTEST);
      diff.addColorStop(t, `rgb(${grey * 255 | 0},${grey * 255 | 0},${grey * 255 | 0})`);
    }
    s = { diff };
    TroutLight.STRIPS.set(key, s);
    return s;
  }

  /** A grey map as big as the fish's box on the canvas `ctx` is of, cleared. */
  static paper(ctx, box) {
    let c = TroutLight.PAPERS.get(ctx);
    if (!c) { c = TroutLight.canvasOf(); TroutLight.PAPERS.set(ctx, c); }
    if (c.width < box.w || c.height < box.h) { c.width = Math.max(c.width, box.w); c.height = Math.max(c.height, box.h); }
    const g = c.getContext('2d');
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, box.w, box.h);
    return { g, c };
  }

  /** The fish's box on the canvas, in its pixels, or null when none of it is on the canvas. */
  static box(fish, ctx, m) {
    const cw = ctx.canvas.width, ch = ctx.canvas.height, pad = fish.len * 0.11;
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const sp of fish.spine) {
      for (const [dx, dy] of TroutLight.CORNERS) {
        const wx = sp.x + dx * pad, wy = sp.y + dy * pad, X = m.a * wx + m.c * wy + m.e, Y = m.b * wx + m.d * wy + m.f;
        if (X < x0) x0 = X;
        if (X > x1) x1 = X;
        if (Y < y0) y0 = Y;
        if (Y > y1) y1 = Y;
      }
    }
    x0 = Math.max(0, Math.floor(x0)); y0 = Math.max(0, Math.floor(y0)); x1 = Math.min(cw, Math.ceil(x1)); y1 = Math.min(ch, Math.ceil(y1));
    return x1 > x0 && y1 > y0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
  }

  /** Lays the light on the body, inside the clip the caller has set to the body's outline. */
  static apply(ctx, fish) {
    const m = ctx.getTransform(), box = TroutLight.box(fish, ctx, m);
    if (!box) return;
    const diff = TroutLight.paper(ctx, box), cap = fish.len * 0.05, us = TroutLight.US, K = us.length - 1;
    let p0 = fish.at(0);
    for (let k = 0; k < K; k++) {
      const p1 = fish.at(us[k + 1]), ang = Math.atan2(p1.y - p0.y, p1.x - p0.x), L = Math.hypot(p1.x - p0.x, p1.y - p0.y), w = fish.halfAt((us[k] + us[k + 1]) / 2) * 1.06;
      const sh = TroutLight.strip(ang), lead = k === 0 ? cap : 0, c = Math.cos(ang), sn = Math.sin(ang), cx = (p0.x + p1.x) / 2, cy = (p0.y + p1.y) / 2;
      // the strip's own matrix (centre, direction, half width) laid over the view's: world -> pixels of the map
      const a = m.a * c + m.c * sn, b = m.b * c + m.d * sn, cc = (-m.a * sn + m.c * c) * w, d = (-m.b * sn + m.d * c) * w;
      const e = m.a * cx + m.c * cy + m.e - box.x, f = m.b * cx + m.d * cy + m.f - box.y;
      diff.g.setTransform(a, b, cc, d, e, f); diff.g.fillStyle = sh.diff; diff.g.fillRect(-L / 2 - 0.35 - lead, -1, L + 0.7 + lead, 2);
      p0 = p1;
    }
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = 'overlay'; ctx.drawImage(diff.c, 0, 0, box.w, box.h, box.x, box.y, box.w, box.h);
    ctx.restore();
  }
}

export class TroutArt {
  /** The eye, in tables of stops for SoftShape: the socket's shade, the iris, the pupil, a faint sheen and its spark (the catchlight is all the shine a fish has). */
  static EYE = Object.freeze({
    shade: Object.freeze([[0, 'rgba(10,8,4,0.42)'], [0.55, 'rgba(10,8,4,0.24)'], [1, 'rgba(10,8,4,0)']]),
    iris: Object.freeze([[0, 'rgb(54,38,18)'], [0.5, 'rgb(64,44,20)'], [0.64, 'rgb(128,98,48)'], [0.8, 'rgb(174,146,84)'], [0.9, 'rgb(196,172,116)'], [0.97, 'rgb(84,68,38)'], [1, 'rgba(40,30,16,0)']]),
    pupil: Object.freeze([[0, 'rgb(3,2,2)'], [0.78, 'rgb(6,5,3)'], [1, 'rgba(6,5,3,0)']]),
    sheen: Object.freeze([[0, 'rgba(255,252,236,0.07)'], [1, 'rgba(255,252,236,0)']]),
    spark: Object.freeze([[0, 'rgba(255,255,250,0.45)'], [0.6, 'rgba(255,255,250,0.3)'], [1, 'rgba(255,255,250,0)']]),
  });
  /** The adipose fin's spot behind the dorsal: dark at the middle, a red-orange rim. */
  static ADIPOSE = Object.freeze([[0, 'rgba(40,34,20,0.92)'], [0.5, 'rgba(54,40,22,0.88)'], [0.82, 'rgba(140,60,34,0.9)'], [1, 'rgba(140,60,34,0)']]);
  /** The paired fins: base, middle and tip colours, the rays' own colour and width, and the bright leading edge. */
  static PECTORAL = Object.freeze({ base: [112, 84, 40], mid: [120, 102, 62], tip: [132, 122, 92], ray: [66, 50, 26], edge: [142, 136, 120], rayWidth: [0.3, 0.0022] });
  static PELVIC = Object.freeze({ base: [106, 82, 42], mid: [114, 98, 62], tip: [126, 118, 92], ray: [66, 50, 26], edge: [138, 132, 118], rayWidth: [0.3, 0.0022] });

  /**
   * The tail's outline: the fin grows out of the stalk at the stalk's own width (98% of it) and opens out in smooth curves; `fish.tailAng`
   * swings it and `fish.tailSpread` opens it as it beats. (dx, dy) lays it somewhere else: the shadow's.
   */
  static tailPath(ctx, fish, dx = 0, dy = 0) {
    const n = fish.spine.length - 1, P = fish.spine[n], w0 = fish.widths[n] * 0.98, a0 = P.a, a1 = a0 + fish.tailAng;
    const d0 = [Math.cos(a0), Math.sin(a0)], n0 = [-d0[1], d0[0]], d1 = [Math.cos(a1), Math.sin(a1)], n1 = [-d1[1], d1[0]];
    const R = fish.len * 0.17, S = fish.len * fish.tailSpread;
    const q = (dist, lat, d, nn) => [P.x + dx + d[0] * dist + nn[0] * lat, P.y + dy + d[1] * dist + nn[1] * lat];
    const lr = q(0, w0, d0, n0), rr = q(0, -w0, d0, n0);
    const lc1 = q(R * 0.36, w0 * 1.05, d0, n0), lc2 = q(R * 0.62, S * 0.8, d1, n1), lt = q(R, S, d1, n1);
    const rc1 = q(R * 0.36, -w0 * 1.05, d0, n0), rc2 = q(R * 0.62, -S * 0.8, d1, n1), rt = q(R, -S, d1, n1);
    const notch = q(R * 0.84, 0, d1, n1), lm = q(R * 0.95, S * 0.5, d1, n1), rm = q(R * 0.95, -S * 0.5, d1, n1);
    ctx.beginPath(); ctx.moveTo(lr[0], lr[1]);
    ctx.bezierCurveTo(lc1[0], lc1[1], lc2[0], lc2[1], lt[0], lt[1]);
    ctx.quadraticCurveTo(lm[0], lm[1], notch[0], notch[1]);
    ctx.quadraticCurveTo(rm[0], rm[1], rt[0], rt[1]);
    ctx.bezierCurveTo(rc2[0], rc2[1], rc1[0], rc1[1], rr[0], rr[1]);
    ctx.closePath();
    return { q, w0, d0, n0, d1, n1, R, S, P };
  }

  /** The tail: filled from the stalk's colour to a clear edge, with a fan of fine rays, each ending just inside the trailing edge. */
  static tailFin(ctx, fish) {
    const { q, w0, d0, n0, d1, n1, R, S, P } = TroutArt.tailPath(ctx, fish);
    const g = ctx.createLinearGradient(P.x, P.y, P.x + d1[0] * R, P.y + d1[1] * R);
    g.addColorStop(0, 'rgba(60,54,30,0.96)'); g.addColorStop(0.4, 'rgba(66,60,36,0.72)'); g.addColorStop(1, 'rgba(84,78,52,0.22)');
    ctx.fillStyle = g; ctx.fill();
    ctx.strokeStyle = 'rgba(58,52,28,0.26)'; ctx.lineWidth = Math.max(0.3, fish.len * 0.002); ctx.beginPath();
    for (let k = -6; k <= 6; k++) {                       // the trailing edge is the curve notch - control - tip
      const f = k / 6, t = Math.abs(f), edge = (1 - t) * (1 - t) * 0.84 + 2 * (1 - t) * t * 0.95 + t * t, from = q(0, w0 * f * 0.9, d0, n0), to = q(R * edge * 0.96, S * f * 0.97, d1, n1);
      ctx.moveTo(from[0], from[1]); ctx.lineTo(to[0], to[1]);
    }
    ctx.stroke();
  }

  /** The paired fins: the pectorals row, wave and, in a turn, the one on the inside presses in; the pelvics hang under the middle. */
  static fins(ctx, fish) {
    const tr = fish.turnRate, len = fish.len, profile = TroutShape.PROFILE;
    const fold = 0.28 * Math.min(1, Math.abs(tr) * 0.5), wamp = 0.16 * (1 - 0.6 * fish.eff);
    for (const side of [-1, 1]) {
      const b = fish.bodyPoint(0.205, side * 0.9, profile), inner = (side * tr) > 0 ? fold : 0;
      FinFan.draw(ctx, len, b.x, b.y, b.a + side * (0.88 + 0.24 * Math.sin(fish.finPhase + side * 0.7) + 0.3 * M.clamp(-side * tr * 0.1, -1, 1) - inner * 1.4), len * 0.15 * (1 - inner), 0.95, 9, fish.finPhase, wamp, TroutArt.PECTORAL, 0.8, side);
    }
    for (const side of [-1, 1]) {
      const b = fish.bodyPoint(0.5, side * 0.6, profile);
      FinFan.draw(ctx, len, b.x, b.y, b.a + side * (0.7 + 0.14 * Math.sin(fish.finPhase * 0.8 + side * 1.4)), len * 0.09, 0.8, 6, fish.finPhase * 0.9, 0.12, TroutArt.PELVIC, 0.62, side);
    }
  }

  /**
   * The body: the skin laid along the spine in 56 strips inside the outline, then the light, then the end of the body takes the tint of
   * the fin (so that no step shows where they meet).
   */
  static body(ctx, fish, painter) {
    const len = fish.len, skin = fish.skin, tex = skin.canvas, H = skin.H, hW = H / skin.S * (len / TroutSkin.REF), K = 56, nose = len * TroutShape.NOSE;
    painter.outline(ctx, fish.spine, fish.widths, nose);
    ctx.fillStyle = 'rgb(46,45,26)'; ctx.fill();       // the cap of the snout lies ahead of the first strip
    ctx.save(); ctx.clip();
    const pts = []; for (let k = 0; k <= K; k++) pts.push(fish.at(k / K));
    for (let k = 0; k < K; k++) {
      const p0 = pts[k], p1 = pts[k + 1], mx = (p0.x + p1.x) / 2, my = (p0.y + p1.y) / 2, ang = Math.atan2(p1.y - p0.y, p1.x - p0.x), L = Math.hypot(p1.x - p0.x, p1.y - p0.y);
      const um = (k + 0.5) / K, du = 1 / K, sx = M.clamp((um - du * 0.58) * skin.W, 0, skin.W - 1), sw = Math.min(skin.W - sx, du * 1.16 * skin.W);
      ctx.save(); ctx.translate(mx, my); ctx.rotate(ang);
      if (k === 0) ctx.drawImage(tex, 0, 0, 2, H, -L * 0.58 - len * 0.05, -hW / 2, len * 0.05 + 0.6, hW);
      ctx.drawImage(tex, sx, 0, sw, H, -L * 0.58, -hW / 2, L * 1.16, hW); ctx.restore();
    }
    TroutLight.apply(ctx, fish);
    ctx.globalCompositeOperation = 'source-over';
    const e = pts[K], e0 = fish.at(0.76), box = len * 0.4, fade = ctx.createLinearGradient(e0.x, e0.y, e.x, e.y);
    fade.addColorStop(0, 'rgba(58,52,30,0)'); fade.addColorStop(0.5, 'rgba(58,52,30,0.35)'); fade.addColorStop(1, 'rgba(54,49,28,0.97)');
    ctx.fillStyle = fade; ctx.fillRect(e.x - box, e.y - box, box * 2, box * 2);
    ctx.restore();
  }

  /**
   * An eye as the trout has it seen from above: it looks sideways, so it is short across the body; a dark socket round it, a golden iris with
   * no hard rim, a pupil that goes toward what the fish looks at, and a faint catchlight toward the sun.
   */
  static eye(ctx, fish, p, r) {
    const rx = r * 1.3, ry = r * 0.98, a = p.a, sun = BROOK.sun, flat = Math.hypot(sun.x, sun.y), eye = TroutArt.EYE;
    SoftShape.draw(ctx, p.x, p.y, rx * 1.9, ry * 2.1, a, eye.shade);
    SoftShape.draw(ctx, p.x, p.y, rx, ry, a, eye.iris);
    SoftShape.draw(ctx, p.x + fish.look.x * r * 0.3, p.y + fish.look.y * r * 0.3, rx * 0.52, ry * 0.52, a, eye.pupil);
    const sx = sun.x / flat * r * 0.42, sy = sun.y / flat * r * 0.42;
    SoftShape.draw(ctx, p.x + sx * 0.8, p.y + sy * 0.8, rx * 0.62, ry * 0.5, a, eye.sheen);
    SoftShape.draw(ctx, p.x + sx, p.y + sy, rx * 0.15, ry * 0.15, 0, eye.spark);
  }

  /** The head: the gill covers open and close with the breath, two nostrils, the mouth's line, the eyes. */
  static head(ctx, fish) {
    const len = fish.len, g = fish.breath, profile = TroutShape.PROFILE;
    for (const side of [-1, 1]) {
      const p0 = fish.bodyPoint(0.145, side * 0.18, profile), pc = fish.bodyPoint(0.195 + 0.004 * g, side * 0.55, profile), p1 = fish.bodyPoint(0.215 + 0.012 * g, side * 0.93, profile);
      ctx.lineCap = 'round';
      ctx.strokeStyle = 'rgba(26,24,12,0.42)'; ctx.lineWidth = len * 0.0065; ctx.beginPath(); ctx.moveTo(p0.x, p0.y); ctx.quadraticCurveTo(pc.x, pc.y, p1.x, p1.y); ctx.stroke();
      ctx.strokeStyle = 'rgba(200,184,130,0.10)'; ctx.lineWidth = len * 0.0032; ctx.beginPath(); ctx.moveTo(p0.x - 0.4, p0.y + 0.4); ctx.quadraticCurveTo(pc.x - 0.4, pc.y + 0.4, p1.x - 0.4, p1.y + 0.4); ctx.stroke();
      const nr = fish.bodyPoint(0.045, side * 0.34, profile);
      ctx.fillStyle = 'rgba(14,12,8,0.7)'; ctx.beginPath(); ctx.ellipse(nr.x, nr.y, len * 0.0034, len * 0.0022, nr.a, 0, M.TAU); ctx.fill();
    }
    const m0 = fish.bodyPoint(0.012, -0.55, profile), m1 = fish.bodyPoint(0.012, 0.55, profile);
    ctx.strokeStyle = 'rgba(16,12,8,0.55)'; ctx.lineWidth = len * (0.0035 + 0.0035 * g); ctx.beginPath(); ctx.moveTo(m0.x, m0.y); ctx.lineTo(m1.x, m1.y); ctx.stroke();
    for (const side of [-1, 1]) TroutArt.eye(ctx, fish, fish.bodyPoint(0.082, side * 0.74, profile), len * 0.0125);
  }

  /** The dorsal fin, leaning a little into a turn, and the adipose fin's spot behind it. */
  static dorsal(ctx, fish) {
    const len = fish.len, profile = TroutShape.PROFILE, lean = M.clamp(fish.turnRate * 0.05, -0.06, 0.06);
    const a = fish.bodyPoint(0.37, 0, profile), b = fish.bodyPoint(0.43, 0.09 + lean, profile), c = fish.bodyPoint(0.5, 0, profile), d = fish.bodyPoint(0.43, -0.09 + lean, profile);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.lineTo(c.x, c.y); ctx.lineTo(d.x, d.y); ctx.closePath(); ctx.fillStyle = 'rgba(36,34,20,0.78)'; ctx.fill();
    ctx.strokeStyle = 'rgba(150,134,84,0.10)'; ctx.lineWidth = Math.max(0.3, len * 0.002); ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(c.x, c.y); ctx.stroke();
    const ad = fish.bodyPoint(0.775, 0, profile);
    SoftShape.draw(ctx, ad.x, ad.y, len * 0.0145, len * 0.0082, ad.a, TroutArt.ADIPOSE);
  }

  /** One trout, whole: the tail under the body, the paired fins, the body with its skin and light, the head, the dorsal. The canvas is left as it was found. */
  static draw(ctx, fish, painter) {
    if (!fish.skin) fish.skin = TroutSkin.bake(fish.skinSeed);
    ctx.save();
    TroutArt.tailFin(ctx, fish);
    TroutArt.fins(ctx, fish);
    TroutArt.body(ctx, fish, painter);
    TroutArt.head(ctx, fish);
    TroutArt.dorsal(ctx, fish);
    ctx.restore();
  }
}
