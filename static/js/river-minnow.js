/*
 * river-minnow.js: how a minnow of the brook looks (the owner, 2026-10-18: of three mockups of the shoal, drawn without the water from
 * the old code, he chose the third; and on 2026-10-19: "remove the shine, they should be darker, these are river fish, they should
 * blend with the bed"). The old minnow was a beige oval with a dark one inside it and twelve dots, a dark wedge for a tail, and no eyes.
 * This one has the shape of a minnow — a blunt head, a thin stalk that grows into a forked, clear tail — a back of dark olive that runs
 * to a duller side, a band of uneven blotches along each side, flecks and a dark line on the back, eyes, and two small fins. It takes
 * the light only so far as the flank away from the sun is shaded: nothing on it shines.
 *
 * The minnow's behaviour is river-fish.js (Minnow, MinnowShoal); this only draws what they hand over: the spine and widths the fish
 * keeps, its tone, its blotches (`pattern`, drawn once when it is made) and its phase.
 */
import { SoftShape, FinFan } from "./river-art.js";
import { M } from "./river-core.js";
import { BROOK } from "./river-world.js";

/** The minnow's half width along its length, as a share of the length. */
export class MinnowShape {
  /** The body's segments: eight, so that the outline bends smoothly (the old minnow had six). */
  static SEGMENTS = 8;
  /** Half width at a share of the length: a blunt head, widest a third of the way, one steady taper into a thin stalk. */
  static KEYS = Object.freeze([[0, 0.038], [0.015, 0.05], [0.04, 0.062], [0.08, 0.074], [0.14, 0.081], [0.22, 0.082], [0.32, 0.08],
    [0.45, 0.073], [0.6, 0.059], [0.75, 0.041], [0.88, 0.027], [1, 0.018]]);

  /** The half width at `u`, snout (0) to tail (1): a smooth curve through the keys (Catmull-Rom). */
  static halfWidth(u) {
    const keys = MinnowShape.KEYS;
    u = M.clamp(u, 0, 1);
    let i = 0;
    while (i < keys.length - 2 && keys[i + 1][0] < u) i++;
    const p0 = keys[Math.max(i - 1, 0)][1], p1 = keys[i][1], p2 = keys[i + 1][1], p3 = keys[Math.min(i + 2, keys.length - 1)][1];
    const t = (u - keys[i][0]) / (keys[i + 1][0] - keys[i][0]), t2 = t * t, t3 = t2 * t;
    return 0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
  }

  /** The half width at each node of a spine of `SEGMENTS` segments. */
  static profile() {
    const n = MinnowShape.SEGMENTS, w = new Float32Array(n + 1);
    for (let i = 0; i <= n; i++) w[i] = MinnowShape.halfWidth(i / n);
    return w;
  }

  static PROFILE = MinnowShape.profile();
}

export class MinnowArt {
  /** Colour from the dark olive back (0) to the duller side (1), [position, [r, g, b]]: of the bed's own tones, the lightest a muddy grey-olive. */
  static ACROSS = Object.freeze([[0, [34, 35, 22]], [0.18, [46, 48, 29]], [0.42, [70, 69, 42]], [0.66, [96, 94, 60]], [0.86, [118, 116, 80]], [1, [132, 130, 94]]]);
  /** The eye, in tables of stops for SoftShape: the socket's shade, the iris, the pupil, the wet sheen and its spark. */
  static EYE = Object.freeze({
    shade: Object.freeze([[0, 'rgba(10,10,6,0.40)'], [0.55, 'rgba(10,10,6,0.22)'], [1, 'rgba(10,10,6,0)']]),
    iris: Object.freeze([[0, 'rgb(40,34,22)'], [0.55, 'rgb(52,44,28)'], [0.7, 'rgb(118,102,62)'], [0.85, 'rgb(168,152,102)'], [0.94, 'rgb(196,184,140)'], [0.985, 'rgb(84,74,46)'], [1, 'rgba(40,36,24,0)']]),
    pupil: Object.freeze([[0, 'rgb(3,3,2)'], [0.78, 'rgb(6,6,4)'], [1, 'rgba(6,6,4,0)']]),
    sheen: Object.freeze([[0, 'rgba(255,255,244,0.10)'], [1, 'rgba(255,255,244,0)']]),
    spark: Object.freeze([[0, 'rgba(255,255,252,0.5)'], [0.6, 'rgba(255,255,252,0.35)'], [1, 'rgba(255,255,252,0)']]),
  });
  /** The small fins at the head: translucent, a dull grey-olive. */
  static FIN = Object.freeze({ base: [104, 100, 72], mid: [118, 116, 92], tip: [132, 130, 110], ray: [72, 68, 48] });
  /** The eye's radius, as a share of the length, and where it stands: along the body and across it (a share of the half width). */
  static EYE_RADIUS = 0.026;
  static EYE_AT = Object.freeze({ u: 0.1, v: 0.78 });

  /**
   * What is particular to one minnow, drawn once from the brook's own stream of random numbers when it is made: seven blotches
   * along each side, uneven, and flecks on the back, as shares of its length (`u` along, `v` across).
   */
  static pattern(rng) {
    const blotches = [], flecks = [];
    for (const side of [-1, 1]) {
      for (let k = 0; k < 7; k++) {
        blotches.push({ u: M.lerp(0.2, 0.82, (k + rng.range(0.1, 0.9)) / 7), v: side * (0.5 + rng.range(-0.09, 0.09)),
          rx: rng.range(0.026, 0.046), ry: rng.range(0.011, 0.018), a: rng.range(0.35, 0.6) });
      }
    }
    for (let k = 0; k < 16; k++) flecks.push({ u: rng.range(0.12, 0.9), v: rng.sign() * rng.range(0, 0.34), r: rng.range(0.005, 0.010), a: rng.range(0.25, 0.4) });
    return { blotches, flecks };
  }

  /** The colour across the body at `k` (0 the back, 1 the side), shifted by the minnow's tone. */
  static colour(k, tone) {
    const across = MinnowArt.ACROSS;
    let i = 0;
    while (i < across.length - 2 && across[i + 1][0] < k) i++;
    const a = across[i], b = across[i + 1], t = M.clamp((k - a[0]) / (b[0] - a[0]), 0, 1);
    return `rgb(${(M.lerp(a[1][0], b[1][0], t) + tone) | 0},${(M.lerp(a[1][1], b[1][1], t) + tone) | 0},${(M.lerp(a[1][2], b[1][2], t) + tone) | 0})`;
  }

  /** A line along the body at a share `off` of the half width, from node `from` to node `to`. */
  static lane(ctx, fish, off, from, to) {
    ctx.beginPath();
    for (let i = from; i <= to; i++) {
      const s = fish.spine[i], w = fish.widths[i] * off, x = s.x - Math.sin(s.a) * w, y = s.y + Math.cos(s.a) * w;
      if (i === from) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
  }

  /** A lane that fades out at both ends, so that it has no round caps. */
  static taper(ctx, fish, off, from, to, rgb, alpha, width) {
    const s0 = fish.spine[from], s1 = fish.spine[to], w0 = fish.widths[from] * off, w1 = fish.widths[to] * off;
    const g = ctx.createLinearGradient(s0.x - Math.sin(s0.a) * w0, s0.y + Math.cos(s0.a) * w0, s1.x - Math.sin(s1.a) * w1, s1.y + Math.cos(s1.a) * w1);
    g.addColorStop(0, `rgba(${rgb},0)`); g.addColorStop(0.2, `rgba(${rgb},${alpha})`); g.addColorStop(0.8, `rgba(${rgb},${alpha})`); g.addColorStop(1, `rgba(${rgb},0)`);
    ctx.strokeStyle = g; ctx.lineWidth = width;
    MinnowArt.lane(ctx, fish, off, from, to);
    ctx.stroke();
  }

  /**
   * The tail: forked and clear. It grows out of the stalk at the stalk's own width, flares out in smooth curves and opens as it
   * beats; its rays end just inside its trailing edge. Drawn first, so that the body covers its root.
   */
  static tailFin(ctx, fish) {
    const n = fish.spine.length - 1, P = fish.spine[n], w0 = fish.widths[n] * 0.98, a0 = P.a, a1 = a0 + Math.sin(fish.phase - 4.9) * fish.amp * 1.2;
    const d0 = [Math.cos(a0), Math.sin(a0)], n0 = [-d0[1], d0[0]], d1 = [Math.cos(a1), Math.sin(a1)], n1 = [-d1[1], d1[0]];
    const R = fish.len * 0.22, S = fish.len * (0.05 + 0.055 * Math.abs(Math.sin(fish.phase - 4.9))), notchAt = 0.7;
    const at = (dist, lat, d, nn) => [P.x + d[0] * dist + nn[0] * lat, P.y + d[1] * dist + nn[1] * lat];
    const lr = at(0, w0, d0, n0), rr = at(0, -w0, d0, n0);
    const lc1 = at(R * 0.34, w0 * 1.05, d0, n0), lc2 = at(R * 0.6, S * 0.8, d1, n1), lt = at(R, S, d1, n1);
    const rc1 = at(R * 0.34, -w0 * 1.05, d0, n0), rc2 = at(R * 0.6, -S * 0.8, d1, n1), rt = at(R, -S, d1, n1);
    const notch = at(R * notchAt, 0, d1, n1), lm = at(R * 0.93, S * 0.5, d1, n1), rm = at(R * 0.93, -S * 0.5, d1, n1);
    ctx.beginPath(); ctx.moveTo(lr[0], lr[1]);
    ctx.bezierCurveTo(lc1[0], lc1[1], lc2[0], lc2[1], lt[0], lt[1]);
    ctx.quadraticCurveTo(lm[0], lm[1], notch[0], notch[1]);
    ctx.quadraticCurveTo(rm[0], rm[1], rt[0], rt[1]);
    ctx.bezierCurveTo(rc2[0], rc2[1], rc1[0], rc1[1], rr[0], rr[1]);
    ctx.closePath();
    const g = ctx.createLinearGradient(P.x, P.y, P.x + d1[0] * R, P.y + d1[1] * R);
    g.addColorStop(0, 'rgba(66,64,46,0.92)'); g.addColorStop(0.45, 'rgba(74,72,56,0.55)'); g.addColorStop(1, 'rgba(86,86,70,0.18)');
    ctx.fillStyle = g; ctx.fill();
    ctx.strokeStyle = 'rgba(70,66,46,0.3)'; ctx.lineWidth = Math.max(0.25, fish.len * 0.003);
    ctx.beginPath();
    for (let k = -4; k <= 4; k++) {
      const f = k / 4, t = Math.abs(f), edge = (1 - t) * (1 - t) * notchAt + 2 * (1 - t) * t * 0.93 + t * t;
      const from = at(0, w0 * f * 0.9, d0, n0), to = at(R * edge * 0.96, S * f * 0.97, d1, n1);
      ctx.moveTo(from[0], from[1]); ctx.lineTo(to[0], to[1]);
    }
    ctx.stroke();
  }

  /** The two small fins by the head, rowing a little. */
  static pectorals(ctx, fish) {
    for (const side of [-1, 1]) {
      const base = fish.bodyPoint(0.2, side * 0.9, MinnowShape.PROFILE);
      FinFan.draw(ctx, fish.len, base.x, base.y, base.a + side * (0.95 + 0.22 * Math.sin(fish.fin + side * 0.7)), fish.len * 0.13, 0.9, 5, fish.fin * 1.3, 0.2, MinnowArt.FIN, 0.6, side);
    }
  }

  /**
   * An eye as the minnow has it seen from above: it looks sideways, so it is short across the body; a dark socket round it, a
   * dark pupil that looks a little ahead, a golden ring and a faint catchlight toward the sun, with no hard rim.
   */
  static eye(ctx, fish, p, r) {
    const rx = r * 1.3, ry = r * 0.98, a = p.a, sun = BROOK.sun, flat = Math.hypot(sun.x, sun.y), eye = MinnowArt.EYE;
    SoftShape.draw(ctx, p.x, p.y, rx * 1.9, ry * 2.1, a, eye.shade);
    SoftShape.draw(ctx, p.x, p.y, rx, ry, a, eye.iris);
    SoftShape.draw(ctx, p.x + Math.cos(fish.heading) * r * 0.22, p.y + Math.sin(fish.heading) * r * 0.22, rx * 0.62, ry * 0.62, a, eye.pupil);
    const sx = sun.x / flat * r * 0.42, sy = sun.y / flat * r * 0.42;
    SoftShape.draw(ctx, p.x + sx * 0.8, p.y + sy * 0.8, rx * 0.62, ry * 0.5, a, eye.sheen);
    SoftShape.draw(ctx, p.x + sx, p.y + sy, rx * 0.15, ry * 0.15, 0, eye.spark);
  }

  /**
   * The shade on the sides. Which flank faces the sun follows from how each part of the body points: the near one is left as it is and
   * the far one darkens, the more the more squarely the flank faces the sun. Nothing is lit: a river fish takes no shine.
   */
  static light(ctx, fish) {
    const sp = fish.spine, n = sp.length - 1, sun = BROOK.sun, flat = Math.hypot(sun.x, sun.y), len = fish.len;
    let k = 0;
    for (let i = 1; i < n; i++) k += (-Math.sin(sp[i].a) * sun.x + Math.cos(sp[i].a) * sun.y) / flat;
    k /= n - 1;
    const side = k >= 0 ? 1 : -1, a = Math.min(1, Math.abs(k) * 1.25);
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.globalCompositeOperation = 'multiply';
    MinnowArt.taper(ctx, fish, -side * 0.62, 1, n - 1, '30,34,22', 0.30 * (0.4 + a), len * 0.1);
    ctx.globalCompositeOperation = 'source-over';
  }

  /** The body: nested outlines from the duller side to the dark back, then, cut to its outline, the blotches, the flecks, the line and the shade. */
  static body(ctx, fish, painter) {
    const len = fish.len, n = fish.spine.length - 1, steps = 9, nose = len * 0.03;
    for (let j = 0; j < steps; j++) {
      const k = 1 - j / steps * 0.92;
      for (let i = 0; i <= n; i++) fish.inner[i] = fish.widths[i] * k;
      painter.outline(ctx, fish.spine, fish.inner, nose * k);
      ctx.fillStyle = MinnowArt.colour(k, fish.tone); ctx.fill();
    }
    ctx.save();
    painter.outline(ctx, fish.spine, fish.widths, nose); ctx.clip();      // nothing painted on the body goes past its edge
    for (const m of fish.pattern.blotches) {
      const p = fish.bodyPoint(m.u, m.v, MinnowShape.PROFILE);
      ctx.fillStyle = `rgba(38,34,22,${m.a})`; ctx.beginPath(); ctx.ellipse(p.x, p.y, m.rx * len, m.ry * len, p.a, 0, M.TAU); ctx.fill();
    }
    for (const f of fish.pattern.flecks) {
      const p = fish.bodyPoint(f.u, f.v, MinnowShape.PROFILE);
      ctx.fillStyle = `rgba(30,30,18,${f.a})`; ctx.beginPath(); ctx.arc(p.x, p.y, f.r * len, 0, M.TAU); ctx.fill();
    }
    ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    ctx.strokeStyle = 'rgba(40,38,24,0.32)'; ctx.lineWidth = Math.max(0.5, len * 0.013);       // the dark line along the back
    MinnowArt.lane(ctx, fish, 0, 1, n - 1); ctx.stroke();
    MinnowArt.light(ctx, fish);
    const end = fish.spine[n], from = fish.bodyPoint(0.7, 0, MinnowShape.PROFILE), tint = ctx.createLinearGradient(from.x, from.y, end.x, end.y);   // the end of the body takes the tint of the tail
    tint.addColorStop(0, 'rgba(64,62,44,0)'); tint.addColorStop(0.5, 'rgba(64,62,44,0.4)'); tint.addColorStop(1, 'rgba(62,60,42,0.96)');
    ctx.fillStyle = tint; ctx.fillRect(end.x - 30, end.y - 30, 60, 60);
    ctx.restore();
  }

  /** One minnow, whole: the tail under the body, the fins, the body, the eyes. The canvas is left as it was found: the next fish is drawn on it. */
  static draw(ctx, fish, painter) {
    const n = fish.spine.length - 1;
    ctx.save();
    for (let i = 0; i <= n; i++) fish.widths[i] = MinnowShape.PROFILE[i] * fish.len;
    MinnowArt.tailFin(ctx, fish);
    MinnowArt.pectorals(ctx, fish);
    MinnowArt.body(ctx, fish, painter);
    const r = fish.len * MinnowArt.EYE_RADIUS, at = MinnowArt.EYE_AT;
    for (const side of [-1, 1]) MinnowArt.eye(ctx, fish, fish.bodyPoint(at.u, side * at.v, MinnowShape.PROFILE), r);
    ctx.restore();
  }
}
