/*
 * river-frog.js: how a frog of the brook looks, seen from above, and how its tadpoles look (the owner, 2026-10-21, of the mockups: "Д, all of
 * them, a few of each"; "the big ones twice smaller, none bigger than that"). Four frogs of the brooks of Adjara: the marsh frog
 * (Pelophylax ridibundus), the long-legged brown frog (Rana macrocnemis), the eastern tree frog (Hyla orientalis) and the Caucasian parsley
 * frog (Pelodytes caucasicus). A frog is drawn the way the trout is: a skin painted once, with every mark that stays put, laid inside the
 * body's outline; the brook's own sun over it as a grey map with `overlay`, so that the flank toward the sun is a little lighter; nothing
 * shines (a faint catchlight in the eye is all of it, as in the trout's). The limbs are tapered segments set by a pose, the angles of the joints.
 *
 * What a frog does (sits, jumps, swims, floats, takes a fly) and where it lives is river-frogs.js; this only draws what it hands over: its kind,
 * its pose, which way it faces, its breath, its blink, where it looks and its tongue.
 */
import { SoftShape } from "./river-art.js";
import { M, Rng, Sprite } from "./river-core.js";
import { BROOK } from "./river-world.js";

/** The four kinds of frog. */
export class FrogKinds {
  /**
   * The longest a frog may be, as a share of the brook's short side (0.01 of it is about 2 cm, a minnow there is 0.04): half the marsh frog of
   * the mockup, 0.052 (the owner, 2026-10-21: "the big ones twice smaller; all of them no bigger than the middle of the big ones").
   */
  static LARGEST = 0.026;

  /**
   * `size`: the length from snout to vent as a share of the brook's short side, marsh frog > brown frog > the two small ones, as they are.
   * `body`: the half width (body lengths) at x along the body, from the snout to the vent at -0.52: a rounded triangle of a head, the hips a
   * little wider. `eye`, `hind`, `fore`: where the eye and the limbs are, the segments' lengths and radii; `web` how much of the toes the web
   * joins, `pads` the tree frog's discs. `skin`: colours and marks. `sit`: the pose it sits in. `homes`: where it lives in the brook.
   */
  static ALL = Object.freeze({
    ridibundus: Object.freeze({
      id: 'ridibundus', size: 0.026, sit: 'SIT', homes: Object.freeze(['rock', 'float']),
      body: Object.freeze([[0.52, 0], [0.505, 0.04], [0.47, 0.085], [0.41, 0.125], [0.34, 0.155], [0.26, 0.172], [0.17, 0.18], [0.06, 0.196], [-0.06, 0.208], [-0.18, 0.206], [-0.27, 0.196], [-0.34, 0.182], [-0.41, 0.15], [-0.47, 0.105], [-0.51, 0.055], [-0.52, 0]]),
      eye: Object.freeze({ x: 0.29, y: 0.125, r: 0.062, pupil: 'across', iris: [96, 72, 30], ring: [200, 166, 88] }),
      hind: Object.freeze({ hip: [-0.33, 0.12], len: [0.46, 0.47, 0.25, 0.33], r: [0.078, 0.052, 0.036, 0.026, 0.019], web: 0.92, pads: 0 }),
      fore: Object.freeze({ sh: [0.12, 0.15], len: [0.17, 0.17, 0.11], r: [0.044, 0.036, 0.027], pads: 0 }),
      // olive green with dark round spots, "often with a bright green line running down the back", the folds along the back paler
      skin: Object.freeze({
        base: [88, 108, 52], dark: [34, 44, 22], light: [140, 152, 82], leg: [94, 110, 58], bar: [40, 48, 26], mottle: 0.34,
        spots: Object.freeze({ n: 24, r: [0.022, 0.048] }), stripe: [150, 180, 96], folds: [160, 142, 86], foldAlpha: 0.75,
        cross: false, chevron: false, tubercles: 10, rows: false, red: 0, mask: null, lateral: null, flecks: 0, tympanum: [78, 76, 44],
      }),
    }),
    macrocnemis: Object.freeze({
      id: 'macrocnemis', size: 0.022, sit: 'SIT', homes: Object.freeze(['bank']),
      body: Object.freeze([[0.52, 0], [0.505, 0.035], [0.47, 0.078], [0.41, 0.118], [0.34, 0.146], [0.26, 0.162], [0.17, 0.17], [0.06, 0.184], [-0.06, 0.196], [-0.18, 0.196], [-0.27, 0.188], [-0.34, 0.174], [-0.41, 0.144], [-0.47, 0.1], [-0.51, 0.052], [-0.52, 0]]),
      eye: Object.freeze({ x: 0.29, y: 0.128, r: 0.062, pupil: 'across', iris: [90, 60, 32], ring: [192, 152, 98] }),
      hind: Object.freeze({ hip: [-0.33, 0.12], len: [0.52, 0.56, 0.28, 0.34], r: [0.07, 0.046, 0.032, 0.024, 0.018], web: 0.55, pads: 0 }),
      fore: Object.freeze({ sh: [0.12, 0.15], len: [0.17, 0.17, 0.11], r: [0.04, 0.032, 0.025], pads: 0 }),
      // brown with a reddish cast, a few dark spots, a large dark spot behind the eye over the ear drum, a dark chevron between the shoulders
      skin: Object.freeze({
        base: [116, 86, 62], dark: [56, 36, 26], light: [160, 126, 96], leg: [120, 90, 66], bar: [62, 40, 28], mottle: 0.26,
        spots: Object.freeze({ n: 10, r: [0.018, 0.036] }), stripe: null, folds: [168, 136, 104], foldAlpha: 0.45,
        cross: false, chevron: true, tubercles: 4, rows: false, red: 0, mask: [46, 28, 20], lateral: null, flecks: 0, tympanum: [58, 38, 28],
      }),
    }),
    orientalis: Object.freeze({
      id: 'orientalis', size: 0.02, sit: 'TIGHT', homes: Object.freeze(['fern']),
      body: Object.freeze([[0.48, 0], [0.47, 0.075], [0.44, 0.14], [0.38, 0.19], [0.3, 0.222], [0.2, 0.236], [0.08, 0.236], [-0.04, 0.228], [-0.16, 0.212], [-0.28, 0.186], [-0.38, 0.152], [-0.46, 0.104], [-0.51, 0.054], [-0.52, 0]]),
      eye: Object.freeze({ x: 0.3, y: 0.138, r: 0.074, pupil: 'across', iris: [124, 96, 40], ring: [216, 184, 102] }),
      hind: Object.freeze({ hip: [-0.33, 0.12], len: [0.42, 0.42, 0.2, 0.22], r: [0.08, 0.058, 0.038, 0.026, 0.02], web: 0.22, pads: 0.034 }),
      fore: Object.freeze({ sh: [0.12, 0.16], len: [0.16, 0.16, 0.1], r: [0.04, 0.034, 0.026], pads: 0.03 }),
      // leaf green and smooth, a dark stripe along the flank with a pale seam above it, discs on the toes
      skin: Object.freeze({
        base: [92, 148, 54], dark: [46, 86, 30], light: [156, 202, 100], leg: [96, 152, 60], bar: null, mottle: 0.1,
        spots: Object.freeze({ n: 0, r: [0, 0] }), stripe: null, folds: null, foldAlpha: 0,
        cross: false, chevron: false, tubercles: 0, rows: false, red: 0, mask: null, lateral: [72, 52, 34], flecks: 30, tympanum: [84, 124, 52],
      }),
    }),
    caucasicus: Object.freeze({
      id: 'caucasicus', size: 0.02, sit: 'SIT', homes: Object.freeze(['shallow']),
      body: Object.freeze([[0.5, 0], [0.485, 0.04], [0.45, 0.08], [0.39, 0.115], [0.32, 0.138], [0.24, 0.15], [0.15, 0.158], [0.04, 0.172], [-0.08, 0.182], [-0.2, 0.18], [-0.3, 0.168], [-0.38, 0.142], [-0.45, 0.102], [-0.5, 0.054], [-0.52, 0]]),
      eye: Object.freeze({ x: 0.29, y: 0.116, r: 0.06, pupil: 'upright', iris: [98, 82, 42], ring: [180, 162, 100] }),
      hind: Object.freeze({ hip: [-0.33, 0.11], len: [0.42, 0.45, 0.22, 0.27], r: [0.062, 0.044, 0.03, 0.022, 0.016], web: 0.35, pads: 0 }),
      fore: Object.freeze({ sh: [0.12, 0.14], len: [0.15, 0.15, 0.1], r: [0.036, 0.03, 0.022], pads: 0 }),
      // olive with dark greenish spots, an oblique cross with a light spot near each hind corner, tubercles in rows, now and then a red point
      skin: Object.freeze({
        base: [104, 102, 66], dark: [50, 56, 34], light: [152, 148, 104], leg: [110, 106, 70], bar: [54, 60, 36], mottle: 0.28,
        spots: Object.freeze({ n: 14, r: [0.012, 0.024] }), stripe: null, folds: null, foldAlpha: 0,
        cross: true, chevron: false, tubercles: 0, rows: true, red: 3, mask: null, lateral: null, flecks: 0, tympanum: [88, 82, 54],
      }),
    }),
  });

  /** One frog's length in a brook whose short side is C px: each a little different, none longer than LARGEST. */
  static lengthOf(kind, C, rng) { return C * Math.min(kind.size * rng.range(0.92, 1.08), FrogKinds.LARGEST); }
}

/**
 * Poses: the angles of the right limbs in degrees, from the way the snout points and turning toward the frog's right; the left ones mirror
 * them. `fold`, `armFold`, `toeFold`: how much of the thigh and shin, the upper arm and the toes shows from above (a sitting frog's thigh
 * goes steeply down to the ground, and from above it looks short).
 */
export class FrogPose {
  /** Sitting: knees out to the sides, the feet turned out beside them, the toes folded together (a "W" from above). */
  static SIT = Object.freeze({ thigh: 62, shin: 210, tarsus: 52, toe: 60, toeSpread: 40, arm: 116, fore: 22, hand: 10, handSpread: 60, fold: 0.58, armFold: 0.6, toeFold: 0.8 });
  /** A tree frog sits pressed into itself: knees at its sides, hands under its chin. */
  static TIGHT = Object.freeze({ thigh: 22, shin: 186, tarsus: 10, toe: 16, toeSpread: 30, arm: 128, fore: 8, hand: -12, handSpread: 50, fold: 0.7, armFold: 0.55, toeFold: 0.85 });
  static CROUCH = Object.freeze({ thigh: 56, shin: 212, tarsus: 44, toe: 52, toeSpread: 34, arm: 124, fore: 14, hand: 4, handSpread: 54, fold: 0.54, armFold: 0.6, toeFold: 0.8 });
  /** Legs thrown straight back, arms along the body: the flight of a jump, and the glide after a kick. */
  static STRETCH = Object.freeze({ thigh: 162, shin: 176, tarsus: 178, toe: 179, toeSpread: 34, arm: 160, fore: 172, hand: 176, handSpread: 20, fold: 1, armFold: 1, toeFold: 1 });
  /** Coming down onto land: the arms forward to meet it. */
  static LAND = Object.freeze({ thigh: 150, shin: 172, tarsus: 170, toe: 172, toeSpread: 40, arm: 62, fore: 12, hand: 4, handSpread: 56, fold: 1, armFold: 0.9, toeFold: 1 });
  /** The legs drawn up for the next kick, the feet turned out. */
  static TUCK = Object.freeze({ thigh: 100, shin: 208, tarsus: 120, toe: 128, toeSpread: 60, arm: 150, fore: 165, hand: 172, handSpread: 24, fold: 0.9, armFold: 1, toeFold: 1 });
  /** Afloat at the surface: limbs spread loose, the webs open. */
  static FLOAT = Object.freeze({ thigh: 128, shin: 166, tarsus: 150, toe: 158, toeSpread: 70, arm: 74, fore: 40, hand: 30, handSpread: 70, fold: 1, armFold: 1, toeFold: 1 });

  static blend(a, b, t) {
    const o = {};
    for (const k in a) o[k] = a[k] + (b[k] - a[k]) * t;
    return o;
  }
  static ease(t) { t = M.clamp(t, 0, 1); return t * t * (3 - 2 * t); }

  /** A stroke under the water at `phase` (0..1): a quick kick back, a long glide with the legs together, a slow draw of the legs up again. */
  static stroke(phase) {
    if (phase < 0.2) return FrogPose.blend(FrogPose.TUCK, FrogPose.STRETCH, FrogPose.ease(phase / 0.2));
    if (phase < 0.62) return FrogPose.STRETCH;
    return FrogPose.blend(FrogPose.STRETCH, FrogPose.TUCK, FrogPose.ease((phase - 0.62) / 0.38));
  }

  /** The flight of a jump at `s` (0..1), from a crouch: the legs thrown back; onto land the arms come forward, into water they stay back. */
  static jump(s, water, sit) {
    if (s < 0.3) return FrogPose.blend(FrogPose.CROUCH, FrogPose.STRETCH, FrogPose.ease(s / 0.3));
    if (water) return FrogPose.STRETCH;
    if (s < 0.8) return FrogPose.blend(FrogPose.STRETCH, FrogPose.LAND, FrogPose.ease((s - 0.3) / 0.5));
    return FrogPose.blend(FrogPose.LAND, sit, FrogPose.ease((s - 0.8) / 0.2));
  }
}

/** The body's outline from above. */
export class FrogShape {
  static POINTS = new Map();

  /** The half width at x (body lengths), through the kind's keys (Catmull-Rom); 0 past the snout and the vent. */
  static half(kind, x) {
    const k = kind.body;
    if (x >= k[0][0] || x <= k[k.length - 1][0]) return 0;
    let i = 0;
    while (i < k.length - 2 && k[i + 1][0] > x) i++;
    const p0 = k[Math.max(i - 1, 0)][1], p1 = k[i][1], p2 = k[i + 1][1], p3 = k[Math.min(i + 2, k.length - 1)][1];
    const t = (k[i][0] - x) / (k[i][0] - k[i + 1][0]), t2 = t * t, t3 = t2 * t;
    return Math.max(0, 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3));
  }

  /** Points of the right side from the snout to the vent, closer together at the two ends, where the outline bends most; made once a kind. */
  static points(kind) {
    let pts = FrogShape.POINTS.get(kind.id);
    if (pts) return pts;
    pts = [];
    const x0 = kind.body[0][0], x1 = kind.body[kind.body.length - 1][0], n = 44;
    for (let i = 0; i <= n; i++) {
      const x = M.lerp(x0, x1, 0.5 - 0.5 * Math.cos(Math.PI * i / n));
      pts.push([x, FrogShape.half(kind, x)]);
    }
    FrogShape.POINTS.set(kind.id, pts);
    return pts;
  }

  /** Traces the outline as a new subpath, its width breathing by `breath`. It winds as FrogLimbs.capsule does, so the two fill as one shape. */
  static trace(ctx, kind, breath = 0) {
    const pts = FrogShape.points(kind), k = 1 + breath;
    ctx.moveTo(pts[0][0], 0);
    for (const [x, w] of pts) ctx.lineTo(x, w * k);
    for (let i = pts.length - 1; i >= 0; i--) ctx.lineTo(pts[i][0], -pts[i][1] * k);
    ctx.closePath();
  }
}

/** Where the joints of the limbs are in a pose. */
export class FrogLimbs {
  static TOES = Object.freeze([0.5, 0.68, 0.92, 1.0, 0.72]);
  static FINGERS = Object.freeze([0.6, 0.95, 1.0, 0.72]);

  static chain(base, lens, angles, side) {
    const out = [[base[0], side * base[1]]];
    let p = out[0];
    for (let i = 0; i < angles.length; i++) {
      const a = side * angles[i] * Math.PI / 180;
      p = [p[0] + lens[i] * Math.cos(a), p[1] + lens[i] * Math.sin(a)];
      out.push(p);
    }
    return out;
  }

  /** The hind leg of a side (1 the right, -1 the left): hip, knee, ankle, the foot's root and the tips of the toes. */
  static hind(kind, pose, side) {
    const h = kind.hind, lens = [h.len[0] * pose.fold, h.len[1] * pose.fold, h.len[2]], toe = h.len[3] * pose.toeFold;
    const [H, K, A, F] = FrogLimbs.chain(h.hip, lens, [pose.thigh, pose.shin, pose.tarsus], side);
    const toes = FrogLimbs.TOES.map((k, i) => {
      const a = side * (pose.toe + (i / 4 - 0.5) * pose.toeSpread) * Math.PI / 180;
      return [F[0] + toe * k * Math.cos(a), F[1] + toe * k * Math.sin(a)];
    });
    return { H, K, A, F, toes };
  }

  /** The foreleg of a side: shoulder, elbow, wrist and the tips of the fingers. */
  static fore(kind, pose, side) {
    const f = kind.fore, [S, E, W] = FrogLimbs.chain(f.sh, [f.len[0] * pose.armFold, f.len[1]], [pose.arm, pose.fore], side);
    const fingers = FrogLimbs.FINGERS.map((k, i) => {
      const a = side * (pose.hand + (i / 3 - 0.5) * pose.handSpread) * Math.PI / 180;
      return [W[0] + f.len[2] * k * Math.cos(a), W[1] + f.len[2] * k * Math.sin(a)];
    });
    return { S, E, W, fingers };
  }

  /** A tapered segment from P (radius r0) to Q (radius r1), round at both ends, as a closed subpath wound like the body's outline. */
  static capsule(ctx, P, Q, r0, r1) {
    const a = Math.atan2(Q[1] - P[1], Q[0] - P[0]);
    ctx.moveTo(P[0] + Math.cos(a - Math.PI / 2) * r0, P[1] + Math.sin(a - Math.PI / 2) * r0);
    ctx.arc(Q[0], Q[1], r1, a - Math.PI / 2, a + Math.PI / 2, false);
    ctx.arc(P[0], P[1], r0, a + Math.PI / 2, a + Math.PI * 1.5, false);
    ctx.closePath();
  }
}

/**
 * The colours of one kind, made once. SoftShape keeps a gradient for every table of stops it is given, by the table itself: a table made
 * anew in every frame would leave a gradient behind in every frame.
 */
export class FrogInk {
  static CACHE = new Map();
  static of(kind) {
    let ink = FrogInk.CACHE.get(kind.id);
    if (!ink) FrogInk.CACHE.set(kind.id, (ink = new FrogInk(kind)));
    return ink;
  }
  /** A table of stops for SoftShape, frozen. */
  static table(...stops) { return Object.freeze(stops); }

  constructor(kind) {
    const T = FrogInk.table, sk = kind.skin, e = kind.eye, dark = sk.dark, light = sk.light, top = M.mix(light, [214, 204, 170], 0.25), lid = M.mix(sk.base, light, 0.3);
    this.spot = T([0, M.rgba(dark, 0.86)], [0.7, M.rgba(dark, 0.78)], [1, M.rgba(dark, 0)]);
    this.cross = T([0, M.rgba(dark, 0.5)], [0.75, M.rgba(dark, 0.36)], [1, M.rgba(dark, 0)]);
    this.pale = T([0, M.rgba(light, 0.92)], [0.65, M.rgba(light, 0.66)], [1, M.rgba(light, 0)]);
    this.chevron = T([0, M.rgba(dark, 0.55)], [1, M.rgba(dark, 0)]);
    this.wartFoot = T([0, M.rgba(dark, 0.42)], [1, M.rgba(dark, 0)]);
    this.wartTop = T([0, M.rgba(top, 0.5)], [0.7, M.rgba(top, 0.3)], [1, M.rgba(top, 0)]);
    this.red = T([0, 'rgba(170,66,42,0.85)'], [0.7, 'rgba(170,66,42,0.55)'], [1, 'rgba(170,66,42,0)']);
    this.fleck = T([0, 'rgba(210,236,176,0.4)'], [1, 'rgba(210,236,176,0)']);
    this.mask = sk.mask ? T([0, M.rgba(sk.mask, 0.72)], [0.7, M.rgba(sk.mask, 0.52)], [1, M.rgba(sk.mask, 0)]) : null;
    this.tympanum = T([0, M.rgba(sk.tympanum, 0.35)], [0.7, M.rgba(sk.tympanum, 0.45)], [0.86, M.rgba(light, 0.25)], [1, M.rgba(light, 0)]);
    this.socket = T([0, M.rgba(dark, 0.42)], [0.75, M.rgba(dark, 0.22)], [1, M.rgba(dark, 0)]);
    this.dome = T([0, M.rgba(M.mix(sk.base, light, 0.35), 1)], [0.75, M.rgba(sk.base, 1)], [0.92, M.rgba(M.mix(sk.base, dark, 0.35), 0.95)], [1, M.rgba(dark, 0)]);
    this.iris = T([0, M.rgba(M.mix(e.iris, e.ring, 0.55), 1)], [0.6, M.rgba(M.mix(e.iris, e.ring, 0.8), 1)], [0.86, M.rgba(M.mix(e.ring, dark, 0.3), 1)], [1, M.rgba(M.mix(e.ring, dark, 0.6), 0)]);
    this.pupil = T([0, 'rgba(6,5,3,0.96)'], [0.75, 'rgba(8,6,4,0.92)'], [1, 'rgba(8,6,4,0)']);
    this.lid = T([0, M.rgba(lid, 1)], [0.82, M.rgba(lid, 0.96)], [1, M.rgba(lid, 0)]);
    this.spark = T([0, `rgba(255,253,240,${FrogInk.SPARK})`], [1, 'rgba(255,253,240,0)']);
    this.pad = T([0, M.rgba(light, 0.95)], [0.7, M.rgba(sk.leg, 0.9)], [1, M.rgba(sk.leg, 0)]);
    this.contact = T([0, 'rgba(0,0,0,0.3)'], [0.6, 'rgba(0,0,0,0.15)'], [1, 'rgba(0,0,0,0)']);
    this.leg = M.rgba(sk.leg, 1);
    this.legLit = M.rgba(M.mix(sk.leg, light, 0.55), 0.42);
    this.legEdge = M.rgba(dark, 0.14);
    this.limbShade = M.rgba(dark, 0.2);
    this.toe = M.rgba(M.mix(sk.leg, dark, 0.12), 1);
    this.web = M.rgba(M.mix(sk.leg, dark, 0.3), 0.6);
    this.bar = sk.bar ? M.rgba(sk.bar, 0.36) : null;
    this.edge = M.rgba(dark, 0.14);
  }
}
/** The catchlight of the eye, the only light on a frog that is not the sun's grey map: as faint as the trout's (0.45). */
FrogInk.SPARK = 0.34;

/**
 * The light on a frog's back: a grey map laid over the skin with `overlay`, the flank toward the brook's sun a little lighter and the far one
 * shaded, and the round of the back darker toward its edge. Nothing shines (the owner, 2026-10-19, of the trout). The map across is made once
 * for every 4 degrees of the sun's way across the frog, in body units, so one map serves every frog of every size.
 */
export class FrogLight {
  static ACROSS = new Map();
  static ROUND = null;
  static STEPS = 90;
  /** The lightest grey of the maps: 0.5 leaves the skin as it is; the lit flank is no more than a little lighter (the trout's is 0.7). */
  static LIGHTEST = 0.62;

  static grey(v) { const c = Math.round(M.clamp(v, 0, 1) * 255); return `rgb(${c},${c},${c})`; }
  /** The key of the sun's way across a frog that faces `heading`. */
  static key(heading) { return Math.round(M.wrap(Math.atan2(BROOK.sun.y, BROOK.sun.x) - heading) / (M.TAU / FrogLight.STEPS)); }
  /** The sun's way across the frog for a key, a unit vector in the frog's own axes. */
  static sun(key) { const a = key * M.TAU / FrogLight.STEPS; return [Math.cos(a), Math.sin(a)]; }
  static across(ctx, key) {
    let g = FrogLight.ACROSS.get(key);
    if (g) return g;
    const [sx, sy] = FrogLight.sun(key);
    g = ctx.createLinearGradient(-sx * 0.26, -sy * 0.26, sx * 0.26, sy * 0.26);
    g.addColorStop(0, FrogLight.grey(0.36)); g.addColorStop(0.55, FrogLight.grey(0.52)); g.addColorStop(1, FrogLight.grey(FrogLight.LIGHTEST));
    FrogLight.ACROSS.set(key, g);
    return g;
  }
  /** Drawn in a space squeezed across by 0.42: a round map there is the long round of a back. */
  static round(ctx) {
    if (FrogLight.ROUND) return FrogLight.ROUND;
    const g = ctx.createRadialGradient(0.02, 0, 0.05, 0, 0, 0.56);
    g.addColorStop(0, FrogLight.grey(0.56)); g.addColorStop(0.62, FrogLight.grey(0.5)); g.addColorStop(0.9, FrogLight.grey(0.42)); g.addColorStop(1, FrogLight.grey(0.34));
    return (FrogLight.ROUND = g);
  }
}

/** The back's skin, painted once for each frog in body units (x -0.6..0.6, y -0.4..0.4), with every mark that does not move. */
export class FrogSkin {
  /** Pixels to a body length: 128 is enough for the longest frog (0.026 of a short side of 1440 px is 37 px) at twice the pixel density. */
  static S = 128;
  /** A canvas of w x h px; a test names another maker, since node has no page. */
  static canvasOf = (w, h) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };

  /** Paints the skin of a frog of `kind` with this seed. The noises are measured in body units, so a skin of any scale shows the same marks. */
  static bake(kind, seed, S = FrogSkin.S) {
    const W = Math.round(1.2 * S), H = Math.round(0.8 * S), sk = kind.skin, ink = FrogInk.of(kind), rng = new Rng(seed * 17 + 3);
    const c = FrogSkin.canvasOf(W, H), g = c.getContext('2d'), img = g.createImageData(W, H), d = img.data;
    for (let py = 0; py < H; py++) {
      const y = py / S - 0.4;
      for (let px = 0; px < W; px++) {
        const x = px / S - 0.6, hw = FrogShape.half(kind, x) || 0.001, v = Math.min(Math.abs(y) / hw, 1.3);
        const m = (M.vnoise(x * 29, y * 29, seed) * 0.55 + M.vnoise(x * 10, y * 10, seed + 5) * 0.45 - 0.5) * 2;
        const k = 1 + m * sk.mottle - 0.1 * M.smooth(0.55, 1.0, v) + (M.vnoise(x * 65, y * 65, seed + 9) - 0.5) * 0.06;
        const col = M.mix(sk.base, sk.light, M.clamp(0.18 * (1 - v), 0, 1)), grain = (M.hash2(px, py, seed + 3) - 0.5) * 8, i = (py * W + px) * 4;
        d[i] = M.clamp(col[0] * k + grain, 0, 255); d[i + 1] = M.clamp(col[1] * k + grain, 0, 255); d[i + 2] = M.clamp(col[2] * k + grain * 0.7, 0, 255); d[i + 3] = 255;
      }
    }
    g.putImageData(img, 0, 0);
    g.setTransform(S, 0, 0, S, 0.6 * S, 0.4 * S);       // body units from here on
    if (sk.stripe) FrogSkin.stripe(g, sk);
    if (sk.cross) FrogSkin.cross(g, ink, seed);
    if (sk.chevron) for (const s of [-1, 1]) for (let t = 0; t <= 1; t += 0.1) SoftShape.draw(g, M.lerp(0.11, -0.02, t), s * M.lerp(0, 0.085, t), 0.028, 0.016, s * -0.6, ink.chevron);
    FrogSkin.spots(g, kind, ink, rng);
    if (sk.folds) FrogSkin.folds(g, sk);
    for (let i = 0; i < sk.tubercles; i++) {
      const x = M.lerp(-0.44, 0.2, rng.next()), y = (rng.next() * 2 - 1) * FrogShape.half(kind, x) * 0.8;
      FrogSkin.tubercle(g, ink, x, y, rng.range(0.008, 0.014));
    }
    if (sk.rows) FrogSkin.rows(g, kind, ink, rng);
    for (let i = 0; i < sk.red; i++) {
      const x = M.lerp(-0.4, 0.1, rng.next()), y = (rng.next() * 2 - 1) * FrogShape.half(kind, x) * 0.7;
      SoftShape.draw(g, x, y, 0.008, 0.008, 0, ink.red);
    }
    for (let i = 0; i < sk.flecks; i++) {
      const x = M.lerp(-0.44, 0.3, rng.next()), y = (rng.next() * 2 - 1) * FrogShape.half(kind, x) * 0.8;
      SoftShape.draw(g, x, y, 0.006, 0.006, 0, ink.fleck);
    }
    FrogSkin.head(g, kind, ink);
    return c;
  }

  /** A pale line down the spine. */
  static stripe(g, sk) {
    const grad = g.createLinearGradient(0, -0.03, 0, 0.03);
    grad.addColorStop(0, M.rgba(sk.stripe, 0)); grad.addColorStop(0.5, M.rgba(sk.stripe, 0.85)); grad.addColorStop(1, M.rgba(sk.stripe, 0));
    g.fillStyle = grad; g.fillRect(-0.46, -0.03, 0.9, 0.06);
  }

  /** The parsley frog's cross, set obliquely on the back and broken by the noise, with a light spot near each of its hind corners. */
  static cross(g, ink, seed) {
    const cx = -0.05, reach = 0.2;
    for (const a of [0.77, -0.47]) {
      const ux = Math.cos(a), uy = Math.sin(a);
      for (let t = -1; t <= 1.0001; t += 0.07) {
        if (M.vnoise(t * 7 + a * 5, 3, seed) < 0.28) continue;
        SoftShape.draw(g, cx + ux * reach * t, uy * reach * t, 0.04, 0.026, a, ink.cross);
      }
      SoftShape.draw(g, cx - ux * reach * 1.15, -uy * reach * 1.15, 0.036, 0.03, 0, ink.pale);
    }
  }

  /** Dark spots, no two touching, off the pale line where there is one. */
  static spots(g, kind, ink, rng) {
    const sk = kind.skin, placed = [];
    for (let tries = 0; tries < 900 && placed.length < sk.spots.n; tries++) {
      const x = M.lerp(-0.44, 0.24, rng.next()), hw = FrogShape.half(kind, x), y = (rng.next() * 2 - 1) * hw * 0.86, r = M.lerp(sk.spots.r[0], sk.spots.r[1], rng.next());
      if (sk.stripe && Math.abs(y) < 0.045) continue;
      if (placed.some((p) => Math.hypot(p[0] - x, p[1] - y) < (p[2] + r) * 1.15)) continue;
      placed.push([x, y, r]);
      const rot = rng.range(0, Math.PI);
      SoftShape.draw(g, x, y, r * rng.range(1, 1.5), r, rot, ink.spot);
      if (rng.chance(0.4)) SoftShape.draw(g, x + rng.range(-1, 1) * r, y + rng.range(-1, 1) * r * 0.6, r * 0.7, r * 0.55, rot + 0.8, ink.spot);
    }
  }

  /** The folds along the back: a pale ridge with its shade outside it. */
  static folds(g, sk) {
    g.lineCap = 'round';
    for (const s of [-1, 1]) {
      g.strokeStyle = M.rgba(sk.dark, 0.35 * sk.foldAlpha); g.lineWidth = 0.016;
      g.beginPath(); g.moveTo(0.17, s * 0.148); g.quadraticCurveTo(-0.1, s * 0.162, -0.38, s * 0.142); g.stroke();
      g.strokeStyle = M.rgba(sk.folds, sk.foldAlpha); g.lineWidth = 0.012;
      g.beginPath(); g.moveTo(0.17, s * 0.138); g.quadraticCurveTo(-0.1, s * 0.151, -0.38, s * 0.132); g.stroke();
    }
  }

  static tubercle(g, ink, x, y, r) {
    SoftShape.draw(g, x + r * 0.3, y + r * 0.3, r * 1.3, r * 1.3, 0, ink.wartFoot);
    SoftShape.draw(g, x, y, r, r, 0, ink.wartTop);
  }

  /** Tubercles in rows, as the parsley frog has them ("regular in arrangement"), each a little off its place. */
  static rows(g, kind, ink, rng) {
    for (let x = -0.42; x <= 0.16; x += 0.055) {
      const hw = FrogShape.half(kind, x) * 0.84;
      for (let y = 0.03; y < hw; y += 0.05) {
        for (const s of [-1, 1]) FrogSkin.tubercle(g, ink, x + rng.range(-0.012, 0.012), s * y + rng.range(-0.012, 0.012), rng.range(0.006, 0.011));
      }
    }
  }

  /** The head's marks that stay put: the brown frog's temporal spot behind the eye, the tree frog's side stripe, the ear drums, the nostrils. */
  static head(g, kind, ink) {
    const sk = kind.skin;
    for (const s of [-1, 1]) {
      if (ink.mask) {
        for (let t = 0; t <= 1; t += 0.08) {
          const x = M.lerp(0.26, 0.06, t), y = s * (FrogShape.half(kind, x) - M.lerp(0.022, 0.036, t));
          SoftShape.draw(g, x, y, 0.034, M.lerp(0.024, 0.038, t), 0, ink.mask);
        }
      }
      if (sk.lateral) FrogSkin.lateral(g, kind, s);
      SoftShape.draw(g, 0.185, s * (FrogShape.half(kind, 0.185) - 0.012), 0.04, 0.034, 0, ink.tympanum);
      g.fillStyle = M.rgba(sk.dark, 0.78);
      g.beginPath(); g.ellipse(kind.body[0][0] - 0.065, s * 0.036, 0.009, 0.006, s * 0.4, 0, M.TAU); g.fill();
    }
  }

  /** The tree frog's stripe is on its flank: from above only its upper edge shows, darkest by the eye and gone toward the hip, a pale seam over it. */
  static lateral(g, kind, s) {
    const sk = kind.skin;
    const along = (inset, from, to) => {
      g.beginPath();
      for (let x = from, first = true; x >= to; x -= 0.02, first = false) {
        const y = s * (FrogShape.half(kind, x) - inset);
        if (first) g.moveTo(x, y); else g.lineTo(x, y);
      }
    };
    const fade = (rgb, a) => {
      const gr = g.createLinearGradient(0.46, 0, -0.2, 0);
      gr.addColorStop(0, M.rgba(rgb, a)); gr.addColorStop(0.55, M.rgba(rgb, a * 0.6)); gr.addColorStop(1, M.rgba(rgb, 0));
      return gr;
    };
    g.lineCap = 'round';
    along(0.004, 0.46, -0.2);
    g.strokeStyle = fade(sk.lateral, 0.7); g.lineWidth = 0.018; g.stroke();
    along(0.016, 0.42, -0.2);
    g.strokeStyle = fade([232, 226, 190], 0.45); g.lineWidth = 0.006; g.stroke();
  }
}

/** Draws a frog in body units: (0, 0) its middle, +x the way it faces, the context scaled to its length. */
export class FrogArt {
  /** (x, y) turned by `a`: the brook's shadow and a fly's place, said in a frog's own axes. */
  static turn(x, y, a) { const c = Math.cos(a), s = Math.sin(a); return [x * c - y * s, x * s + y * c]; }

  /** A limb's segment: its colour, the dark bars across it (where this frog has them), a soft shade at its edge and its lit side toward the sun. */
  static segment(ctx, ink, P, Q, r0, r1, bars, sun, shift = 0) {
    ctx.beginPath(); FrogLimbs.capsule(ctx, P, Q, r0, r1);
    ctx.fillStyle = ink.leg; ctx.fill();
    ctx.save(); ctx.clip();
    if (bars && ink.bar) {
      const dx = Q[0] - P[0], dy = Q[1] - P[1], L = Math.hypot(dx, dy) || 1e-6, ux = dx / L, uy = dy / L, w = Math.max(r0, r1) * 1.6;
      ctx.strokeStyle = ink.bar; ctx.lineCap = 'butt';
      for (const [i, f] of bars.entries()) {
        const at = M.clamp(f + shift * (i % 2 ? -1 : 1), 0.08, 0.92), cx = P[0] + dx * at, cy = P[1] + dy * at;
        ctx.lineWidth = L * (0.13 + 0.05 * Math.abs(Math.sin(i * 2.3 + shift * 40)));
        ctx.beginPath(); ctx.moveTo(cx - uy * w, cy + ux * w); ctx.lineTo(cx + uy * w, cy - ux * w); ctx.stroke();
      }
    }
    ctx.beginPath(); FrogLimbs.capsule(ctx, P, Q, r0, r1);
    ctx.strokeStyle = ink.limbShade; ctx.lineWidth = (r0 + r1) * 0.32; ctx.stroke();
    ctx.restore();
    const ox = sun[0] * 0.4, oy = sun[1] * 0.4;
    ctx.beginPath(); FrogLimbs.capsule(ctx, [P[0] + ox * r0, P[1] + oy * r0], [Q[0] + ox * r1, Q[1] + oy * r1], r0 * 0.5, r1 * 0.5);
    ctx.fillStyle = ink.legLit; ctx.fill();
    ctx.beginPath(); FrogLimbs.capsule(ctx, P, Q, r0, r1);
    ctx.strokeStyle = ink.legEdge; ctx.lineWidth = 0.008; ctx.stroke();
  }

  /** The foot: the web between the toes (hidden while the toes are folded), the toes, and the tree frog's discs. */
  static foot(ctx, kind, ink, leg, pose) {
    const h = kind.hind, F = leg.F;
    if (h.web > 0.05) {
      ctx.save(); ctx.globalAlpha *= M.clamp((pose.toeSpread - 18) / 40, 0.2, 1);
      ctx.beginPath(); ctx.moveTo(F[0], F[1]); ctx.lineTo(leg.toes[0][0], leg.toes[0][1]);
      for (let i = 0; i < 4; i++) {
        const a = leg.toes[i], b = leg.toes[i + 1], k = 0.18 + 0.7 * h.web;
        ctx.quadraticCurveTo(F[0] + ((a[0] + b[0]) / 2 - F[0]) * k, F[1] + ((a[1] + b[1]) / 2 - F[1]) * k, b[0], b[1]);
      }
      ctx.closePath();
      ctx.fillStyle = ink.web; ctx.fill();
      ctx.restore();
    }
    ctx.fillStyle = ink.toe;
    for (const tip of leg.toes) { ctx.beginPath(); FrogLimbs.capsule(ctx, F, tip, h.r[4], h.r[4] * 0.55); ctx.fill(); }
    if (h.pads) for (const tip of leg.toes) SoftShape.draw(ctx, tip[0], tip[1], h.pads, h.pads, 0, ink.pad);
  }

  static hand(ctx, kind, ink, arm) {
    const f = kind.fore;
    ctx.fillStyle = ink.toe;
    for (const tip of arm.fingers) { ctx.beginPath(); FrogLimbs.capsule(ctx, arm.W, tip, f.r[2] * 0.62, f.r[2] * 0.4); ctx.fill(); }
    if (f.pads) for (const tip of arm.fingers) SoftShape.draw(ctx, tip[0], tip[1], f.pads, f.pads, 0, ink.pad);
  }

  /** The four limbs from the bottom up: the foot and toes, the shin, the thigh; the fingers, the forearm, the upper arm. */
  static limbs(ctx, frog, pose, ink, sun) {
    const kind = frog.kind, h = kind.hind, f = kind.fore;
    for (const side of [-1, 1]) {
      const leg = FrogLimbs.hind(kind, pose, side), arm = FrogLimbs.fore(kind, pose, side), shift = frog.barShift * side;
      FrogArt.foot(ctx, kind, ink, leg, pose);
      FrogArt.segment(ctx, ink, leg.A, leg.F, h.r[2], h.r[3], [0.5], sun, shift);
      FrogArt.segment(ctx, ink, leg.K, leg.A, h.r[1], h.r[2], [0.3, 0.68], sun, shift);
      FrogArt.segment(ctx, ink, leg.H, leg.K, h.r[0], h.r[1], [0.42, 0.78], sun, shift);
      FrogArt.hand(ctx, kind, ink, arm);
      FrogArt.segment(ctx, ink, arm.E, arm.W, f.r[1], f.r[2], [0.5], sun, shift);
      FrogArt.segment(ctx, ink, arm.S, arm.E, f.r[0], f.r[1], null, sun, shift);
    }
  }

  /** The body: the skin inside the outline, the light across it and the round of the back over it, a faint edge. */
  static body(ctx, frog, ink, key) {
    const kind = frog.kind, breath = frog.breathe();
    ctx.beginPath(); FrogShape.trace(ctx, kind, breath);
    ctx.save(); ctx.clip();
    ctx.drawImage(frog.skinCanvas(), -0.6, -0.4, 1.2, 0.8);
    ctx.globalCompositeOperation = 'overlay';
    ctx.fillStyle = FrogLight.across(ctx, key); ctx.fillRect(-0.6, -0.4, 1.2, 0.8);
    ctx.save(); ctx.scale(1, 0.42); ctx.fillStyle = FrogLight.round(ctx); ctx.fillRect(-0.7, -1, 1.4, 2); ctx.restore();
    ctx.restore();
    ctx.beginPath(); FrogShape.trace(ctx, kind, breath);
    ctx.strokeStyle = ink.edge; ctx.lineWidth = 0.01; ctx.stroke();
  }

  /**
   * An eye seen from above: a bulge out over the head's edge, the upper lid's skin over its top, a golden crescent of iris looking out to
   * the side with the pupil in it (across, or upright for the parsley frog), the lid sliding out over it in a blink, and a faint catchlight.
   */
  static eye(ctx, frog, ink, side, sun) {
    const e = frog.kind.eye, x = e.x, y = side * e.y, r = e.r, lid = frog.blinkAmount(), iy = y + side * r * 0.42;
    SoftShape.draw(ctx, x, y, r * 1.5, r * 1.36, 0, ink.socket);
    SoftShape.draw(ctx, x, y, r * 1.14, r * 1.06, 0, ink.dome);
    ctx.save(); ctx.beginPath(); ctx.ellipse(x, y, r * 1.06, r * 0.99, 0, 0, M.TAU); ctx.clip();
    SoftShape.draw(ctx, x, iy, r * 0.86, r * 0.66, 0, ink.iris);
    if (e.pupil === 'across') SoftShape.draw(ctx, x + frog.look * r * 0.1, iy + side * r * 0.1, r * 0.5, r * 0.2, 0, ink.pupil);
    else SoftShape.draw(ctx, x, iy + side * r * 0.1, r * 0.2, r * 0.3, 0, ink.pupil);
    ctx.restore();
    SoftShape.draw(ctx, x, M.lerp(y - side * r * 0.2, y + side * r * 0.3, lid), r, r * M.lerp(0.62, 1.0, lid), 0, ink.lid);
    SoftShape.draw(ctx, x + sun[0] * r * 0.35, iy + sun[1] * r * 0.25, r * 0.13, r * 0.1, 0, ink.spark);
  }

  /** The eyes, and the tongue while it is out. */
  static head(ctx, frog, ink, sun) {
    for (const side of [-1, 1]) FrogArt.eye(ctx, frog, ink, side, sun);
    if (frog.tongue > 0) {
      const [tx, ty] = frog.tongueTo, k = Math.sin(Math.PI * M.clamp(frog.tongue, 0, 1)), x0 = frog.kind.body[0][0] - 0.02;
      ctx.strokeStyle = 'rgba(206,124,122,0.95)'; ctx.lineWidth = 0.05; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(x0, 0); ctx.lineTo(M.lerp(x0, tx, k), M.lerp(0, ty, k)); ctx.stroke();
    }
  }

  /** One frog, whole. */
  static whole(ctx, frog, pose, ink = FrogInk.of(frog.kind)) {
    const key = FrogLight.key(frog.heading), sun = FrogLight.sun(key);
    ctx.save();
    FrogArt.limbs(ctx, frog, pose, ink, sun);
    FrogArt.body(ctx, frog, ink, key);
    FrogArt.head(ctx, frog, ink, sun);
    ctx.restore();
  }

  /** What stands above the surface of a frog afloat: the top of its head and its eyes, a thin bright line of water across the head; `dark` the canopy's shade. */
  static aboveWater(ctx, frog, ink, dark) {
    const kind = frog.kind, e = kind.eye, key = FrogLight.key(frog.heading), sun = FrogLight.sun(key), cx = e.x + 0.03, rx = 0.2, ry = e.y + e.r * 1.25;
    const lens = () => { ctx.beginPath(); ctx.ellipse(cx, 0, rx, ry, 0, 0, M.TAU); };
    const outline = () => { ctx.beginPath(); FrogShape.trace(ctx, kind, frog.breathe()); };
    ctx.save();
    ctx.save(); lens(); ctx.clip();
    FrogArt.body(ctx, frog, ink, key);
    if (dark > 0.02) { outline(); ctx.fillStyle = `rgba(0,0,0,${dark.toFixed(3)})`; ctx.fill(); }
    ctx.restore();
    ctx.save(); outline(); ctx.clip(); lens(); ctx.strokeStyle = 'rgba(222,236,228,0.22)'; ctx.lineWidth = 0.014; ctx.stroke(); ctx.restore();
    FrogArt.head(ctx, frog, ink, sun);
    ctx.restore();
  }

  /** A frog sitting in the shallows: its body and head above the water (the legs are drawn under it), the water's line round the body. */
  static wading(ctx, frog, ink, dark) {
    const key = FrogLight.key(frog.heading), sun = FrogLight.sun(key);
    ctx.save();
    FrogArt.body(ctx, frog, ink, key);
    FrogArt.head(ctx, frog, ink, sun);
    ctx.beginPath(); FrogShape.trace(ctx, frog.kind, frog.breathe());
    if (dark > 0.02) { ctx.fillStyle = `rgba(0,0,0,${dark.toFixed(3)})`; ctx.fill(); }
    ctx.strokeStyle = 'rgba(222,236,228,0.18)'; ctx.lineWidth = 0.016; ctx.stroke();
    ctx.restore();
  }

  /** The silhouette as a path, for the shadow and the shade: body and limbs as one shape (they all wind the same way). */
  static silhouette(ctx, frog, pose) {
    const kind = frog.kind, h = kind.hind, f = kind.fore;
    ctx.beginPath(); FrogShape.trace(ctx, kind, frog.breathe());
    for (const side of [-1, 1]) {
      const leg = FrogLimbs.hind(kind, pose, side), arm = FrogLimbs.fore(kind, pose, side);
      FrogLimbs.capsule(ctx, leg.H, leg.K, h.r[0], h.r[1]); FrogLimbs.capsule(ctx, leg.K, leg.A, h.r[1], h.r[2]); FrogLimbs.capsule(ctx, leg.A, leg.F, h.r[2], h.r[3]);
      for (const t of leg.toes) FrogLimbs.capsule(ctx, leg.F, t, h.r[4] * 1.4, h.r[4]);
      FrogLimbs.capsule(ctx, arm.S, arm.E, f.r[0], f.r[1]); FrogLimbs.capsule(ctx, arm.E, arm.W, f.r[1], f.r[2]);
      for (const t of arm.fingers) FrogLimbs.capsule(ctx, arm.W, t, f.r[2] * 0.7, f.r[2] * 0.45);
    }
  }
}

/**
 * A frog at rest, painted once into a picture of its own and laid on the brook with drawImage, as the leaves are. Drawn stroke by stroke a
 * frog takes about 150 canvas calls, and the seven above the water cost the brook 2.6 ms a frame against its 10.4 (measured 2026-10-21 on
 * the brook, the cost spread over the limbs, the body and the eyes alike); a frog sits nearly all the time, so its picture is kept until
 * what it shows changes: the way the sun falls across it (every 4 degrees of a turn) or what it does.
 */
export class FrogStill {
  constructor() { this.sprite = null; this.key = null; }

  /** The picture for `key`, `reach` body lengths each way from the frog's middle, painted by `paint(ctx)` in body units; painted again on a new key. */
  of(frog, key, reach, dpr, paint) {
    if (this.sprite && this.key === key) return this.sprite;
    const half = Math.ceil(frog.len * reach), sp = new Sprite(half * 2, half * 2, dpr, half, half), c = sp.ctx;
    c.save(); c.translate(half, half); c.scale(frog.len, frog.len); paint(c); c.restore();
    this.sprite = sp.seal(); this.key = key;
    return this.sprite;
  }
}

/** A tadpole in its own lengths, (0, 0) its middle facing +x: a dark round body, two small eyes, a tail with a clear fin that waves. */
export class TadpoleArt {
  static BODY = FrogInk.table([0, 'rgb(40,36,24)'], [0.72, 'rgb(30,27,18)'], [0.9, 'rgba(24,21,14,0.92)'], [1, 'rgba(24,21,14,0)']);
  static EYE = FrogInk.table([0, 'rgba(10,8,6,0.95)'], [0.6, 'rgba(14,12,8,0.9)'], [0.8, 'rgba(150,126,70,0.8)'], [1, 'rgba(150,126,70,0)']);

  /** `wave`: the tail's phase; `speed`: as a share of what it swims at, which makes the wave wider. */
  static draw(ctx, wave, speed) {
    const amp = 0.05 + 0.05 * M.clamp(speed, 0, 1), N = 12, up = [], down = [], core = [];
    for (let i = 0; i <= N; i++) {
      const u = i / N, x = 0.1 - 0.72 * u, y = amp * Math.pow(u, 1.4) * Math.sin(wave - u * 5.5);
      const fin = 0.075 * Math.pow(Math.sin(Math.PI * M.clamp(u * 0.92 + 0.08, 0, 1)), 0.7), mus = 0.05 * Math.pow(1 - u, 1.2) + 0.003;
      up.push([x, y - fin]); down.push([x, y + fin]); core.push([x, y, mus]);
    }
    ctx.save();
    ctx.beginPath(); ctx.moveTo(up[0][0], up[0][1]);
    for (const q of up) ctx.lineTo(q[0], q[1]);
    for (let i = N; i >= 0; i--) ctx.lineTo(down[i][0], down[i][1]);
    ctx.closePath(); ctx.fillStyle = 'rgba(58,52,36,0.62)'; ctx.fill();
    ctx.beginPath(); ctx.moveTo(core[0][0], core[0][1] - core[0][2]);
    for (const q of core) ctx.lineTo(q[0], q[1] - q[2]);
    for (let i = N; i >= 0; i--) ctx.lineTo(core[i][0], core[i][1] + core[i][2]);
    ctx.closePath(); ctx.fillStyle = 'rgba(26,23,15,0.95)'; ctx.fill();
    SoftShape.draw(ctx, 0.2, 0, 0.21, 0.14, 0, TadpoleArt.BODY);
    for (const s of [-1, 1]) SoftShape.draw(ctx, 0.31, s * 0.095, 0.03, 0.03, 0, TadpoleArt.EYE);
    ctx.restore();
  }
}
