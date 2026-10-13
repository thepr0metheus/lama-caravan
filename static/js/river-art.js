/*
 * river-art.js: sprites painted once for the brook: autumn leaves of the three trees that stand
 * over Adjarian streams (sweet chestnut, oriental beech, alder), fern fronds, an alder branch
 * hanging over the water, and the painter that draws a fish seen from above.
 */
import { M, Sprite } from "./river-core.js";

/* Leaf shapes: aspect = half width / length; widest = where along the midrib; teeth along the edge. */
const LEAF_SHAPES = Object.freeze({
  chestnut: { aspect: 0.21, widest: 0.47, teeth: 17, tooth: 0.22, veins: 15, ends: 1.25, size: 0.075,
    palettes: [[[214, 172, 64], [150, 104, 36]], [[196, 168, 70], [112, 116, 40]], [[180, 116, 46], [118, 70, 30]]] },
  beech: { aspect: 0.33, widest: 0.42, teeth: 8, tooth: 0.06, veins: 8, ends: 0.9, size: 0.045,
    palettes: [[[208, 118, 44], [146, 70, 28]], [[222, 160, 62], [168, 98, 36]], [[164, 86, 38], [108, 54, 28]]] },
  alder: { aspect: 0.4, widest: 0.62, teeth: 15, tooth: 0.07, veins: 7, ends: 0.55, size: 0.04,
    palettes: [[[116, 120, 54], [78, 82, 36]], [[152, 142, 62], [100, 90, 42]]] },
});

export class LeafArt {
  /** Paints every shape in every palette; `C` is the stream's width (leaf size follows it). */
  constructor(C, dpr, rng) {
    this.sprites = [];
    for (const [kind, shape] of Object.entries(LEAF_SHAPES)) {
      for (const pal of shape.palettes) this.sprites.push(Object.assign(this.paint(shape, pal, C * shape.size, dpr, rng), { kind }));
    }
  }
  pick(rng) { return rng.pick(this.sprites); }
  static halfWidth(shape, t, L) {
    if (t <= 0 || t >= 1) return 0;
    const k = Math.log(0.5) / Math.log(shape.widest);
    let w = Math.pow(Math.sin(Math.PI * Math.pow(t, k)), shape.ends) * shape.aspect * L;
    if (t > 0.08 && t < 0.96) w *= 1 - shape.tooth * ((t * shape.teeth) % 1) * Math.min(1, w / (shape.aspect * L * 0.3));
    return w;
  }
  static outline(ctx, shape, L, x0, y0) {
    const steps = 90;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    for (let i = 1; i <= steps; i++) { const t = i / steps; ctx.lineTo(x0 + t * L, y0 - LeafArt.halfWidth(shape, t, L)); }
    for (let i = steps - 1; i >= 1; i--) { const t = i / steps; ctx.lineTo(x0 + t * L, y0 + LeafArt.halfWidth(shape, t, L)); }
    ctx.closePath();
  }
  paint(shape, [base, edge], L, dpr, rng) {
    const stalk = L * 0.12, pad = 2;
    const w = Math.ceil(L + stalk + pad * 2), h = Math.ceil(shape.aspect * L * 2 + pad * 2);
    const x0 = pad + stalk, y0 = h / 2;
    const sp = new Sprite(w, h, dpr, x0 + L * 0.45, y0);
    const c = sp.ctx;
    c.strokeStyle = M.rgba(M.mix(edge, [60, 40, 20], 0.4), 1);
    c.lineWidth = Math.max(0.8, L * 0.022);
    c.lineCap = 'round';
    c.beginPath(); c.moveTo(pad, y0 + L * 0.01); c.lineTo(x0 + 1, y0); c.stroke();
    LeafArt.outline(c, shape, L, x0, y0);
    const g = c.createLinearGradient(x0, 0, x0 + L, 0);
    g.addColorStop(0, M.rgba(M.mix(base, edge, 0.35), 1));
    g.addColorStop(0.5, M.rgba(base, 1));
    g.addColorStop(1, M.rgba(M.mix(base, edge, 0.55), 1));
    c.fillStyle = g;
    c.fill();
    c.save();
    c.clip();
    for (let i = 0; i < 9; i++) {
      c.fillStyle = M.rgba(edge, rng.range(0.12, 0.3));
      c.beginPath(); c.arc(x0 + rng.range(0, L), y0 + rng.range(-1, 1) * shape.aspect * L, rng.range(0.05, 0.16) * L, 0, M.TAU); c.fill();
    }
    c.lineWidth = Math.max(1, shape.aspect * L * 0.35);
    c.strokeStyle = M.rgba(edge, 0.55);
    LeafArt.outline(c, shape, L, x0, y0);
    c.stroke();
    const vein = M.rgba(M.mix(base, [255, 240, 200], 0.35), 0.55);
    c.strokeStyle = vein;
    c.lineWidth = Math.max(0.6, L * 0.014);
    for (let i = 0; i < shape.veins; i++) {
      const t = 0.07 + 0.86 * (i + 0.5) / shape.veins, t2 = Math.min(0.98, t + 0.1);
      for (const side of [-1, 1]) {
        c.beginPath();
        c.moveTo(x0 + t * L, y0);
        c.lineTo(x0 + t2 * L, y0 + side * LeafArt.halfWidth(shape, t2, L) * 0.92);
        c.stroke();
      }
    }
    c.lineWidth = Math.max(0.8, L * 0.024);
    c.strokeStyle = M.rgba(M.mix(base, [255, 245, 210], 0.45), 0.8);
    c.beginPath(); c.moveTo(x0, y0); c.lineTo(x0 + L * 0.97, y0); c.stroke();
    const sheen = c.createLinearGradient(0, y0 - shape.aspect * L, 0, y0 + shape.aspect * L);
    sheen.addColorStop(0, 'rgba(255,255,240,0.18)');
    sheen.addColorStop(0.5, 'rgba(255,255,240,0)');
    c.fillStyle = sheen;
    c.fillRect(0, 0, w, h);
    c.restore();
    return sp.seal();
  }
}

/** Fern fronds (lady fern): a curved stalk with pinnae on both sides, each pinna a crenate blade. */
export class FernArt {
  constructor(C, dpr, rng) {
    this.fronds = [];
    for (let i = 0; i < 5; i++) {
      const autumn = i === 4 ? 0.55 : rng.range(0, 0.18);
      this.fronds.push(this.paint(C * rng.range(0.2, 0.27), dpr, rng, autumn));
    }
  }
  paint(len, dpr, rng, autumn) {
    const w = Math.ceil(len * 1.04), h = Math.ceil(len * 0.66), mid = h / 2;
    const sp = new Sprite(w, h, dpr, 0, mid);
    const c = sp.ctx;
    const curl = rng.range(-0.09, 0.09) * len;
    const at = t => ({ x: t * len, y: mid + curl * Math.sin(t * Math.PI * 0.85) * t });
    const young = [66, 104, 32], old = [40, 72, 22], tipCol = [120, 150, 52], fade = [168, 142, 66];
    for (let i = 0; i < 30; i++) {
      const t = 0.06 + 0.92 * i / 29;
      const p = at(t), q = at(Math.min(1, t + 0.01));
      const dir = Math.atan2(q.y - p.y, q.x - p.x);
      const pl = len * 0.27 * Math.pow(Math.sin(Math.PI * Math.min(1, t * 1.02)), 0.75) * (1 - 0.32 * t);
      for (const side of [-1, 1]) {
        let col = M.mix(old, young, t);
        col = M.mix(col, tipCol, Math.pow(t, 2) * 0.6);
        col = M.mix(col, fade, autumn * (0.4 + 0.6 * t));
        this.pinna(c, p.x, p.y, dir + side * (1.1 - 0.42 * t), pl * rng.range(0.92, 1.05), col, -side * 0.35);
      }
    }
    c.strokeStyle = M.rgba(M.mix([70, 84, 30], [120, 100, 50], autumn), 1);
    c.lineWidth = Math.max(1, len * 0.011);
    c.lineCap = 'round';
    c.beginPath();
    for (let i = 0; i <= 40; i++) { const p = at(i / 40); i ? c.lineTo(p.x, p.y) : c.moveTo(p.x, p.y); }
    c.stroke();
    return sp.seal();
  }
  /** One pinna: a thin, slightly drooping midrib carrying separate toothed pinnules, so light shows between them. */
  pinna(c, x, y, ang, len, col, curve) {
    const count = Math.max(3, Math.round(len / 3.4));
    // the midrib bends toward the frond's tip: its angle turns by `curve` over its length
    const at = u => {
      const mid = ang + curve * u * 0.5;
      return { x: x + Math.cos(mid) * len * u, y: y + Math.sin(mid) * len * u, a: ang + curve * u };
    };
    c.strokeStyle = M.rgba(M.mix(col, [36, 52, 18], 0.4), 0.9);
    c.lineWidth = 0.55;
    c.beginPath();
    for (let i = 0; i <= 8; i++) { const p = at(i / 8 * 0.96); i ? c.lineTo(p.x, p.y) : c.moveTo(p.x, p.y); }
    c.stroke();
    for (let k = 0; k < count; k++) {
      const u = (k + 0.6) / (count + 0.4);
      const p = at(u);
      const l = len * 0.2 * (1 - u * 0.72);
      const w = l * 0.36;
      const tone = M.mix(M.mix(col, [24, 44, 12], 0.22), M.mix(col, [196, 214, 120], 0.2), u);
      c.fillStyle = M.rgba(tone, 0.96);
      for (const side of [-1, 1]) {
        const a = p.a + side * 1.0 - side * 0.25 * u;
        const ca = Math.cos(a), sa = Math.sin(a);
        const tx = p.x + ca * l, ty = p.y + sa * l;
        const nx = -sa * w, ny = ca * w;
        c.beginPath();
        c.moveTo(p.x, p.y);
        c.quadraticCurveTo(p.x + ca * l * 0.45 + nx, p.y + sa * l * 0.45 + ny, tx, ty);
        c.quadraticCurveTo(p.x + ca * l * 0.5 - nx * 0.8, p.y + sa * l * 0.5 - ny * 0.8, p.x, p.y);
        c.fill();
      }
    }
  }
}

/** An alder branch close to the camera: out of focus, so it is painted sharp and then blurred. */
export class BranchArt {
  constructor(C, dpr, rng) {
    const L = C * 0.62, w = Math.ceil(L * 1.05), h = Math.ceil(L * 0.7);
    const sharp = new Sprite(w, h, dpr, 0, 0);
    const c = sharp.ctx;
    const leaf = LEAF_SHAPES.alder;
    const twig = t => ({ x: t * L * 0.95, y: L * 0.05 + Math.sin(t * 2.2) * L * 0.18 + t * t * L * 0.12 });
    c.strokeStyle = '#2b2a1c';
    c.lineCap = 'round';
    c.lineWidth = L * 0.016;
    c.beginPath();
    for (let i = 0; i <= 30; i++) { const p = twig(i / 30); i ? c.lineTo(p.x, p.y) : c.moveTo(p.x, p.y); }
    c.stroke();
    for (let i = 0; i < 11; i++) {
      const t = 0.12 + 0.86 * i / 10, p = twig(t), q = twig(t + 0.01);
      const dir = Math.atan2(q.y - p.y, q.x - p.x) + (i % 2 ? 1 : -1) * rng.range(0.6, 1.1);
      const size = L * rng.range(0.15, 0.21) * (1 - t * 0.25);
      c.save();
      c.translate(p.x, p.y);
      c.rotate(dir);
      LeafArt.outline(c, leaf, size, size * 0.12, 0);
      const tone = rng.range(0, 1);
      c.fillStyle = M.rgba(M.mix([30, 52, 20], [62, 86, 30], tone), 1);
      c.fill();
      c.strokeStyle = M.rgba([96, 120, 52], 0.35);
      c.lineWidth = size * 0.02;
      c.beginPath(); c.moveTo(size * 0.12, 0); c.lineTo(size * 1.08, 0); c.stroke();
      c.restore();
    }
    this.sprite = new Sprite(w, h, dpr, 0, 0);
    const b = this.sprite.ctx;
    b.filter = `blur(${Math.max(2, C * 0.009)}px)`;
    b.drawImage(sharp.art.canvas, 0, 0, w, h);
    b.filter = 'none';
    this.sprite.seal();
  }
}

/** Draws a fish seen from above along its spine; keeps its edge buffers between frames. */
export class TopFishPainter {
  constructor(maxPoints = 16) {
    this.L = new Float32Array(maxPoints * 2);
    this.R = new Float32Array(maxPoints * 2);
  }
  /** Traces the outline: spine points carry x, y and a (the direction toward the tail). */
  outline(ctx, spine, widths, nose, dx = 0, dy = 0) {
    const n = spine.length - 1, L = this.L, R = this.R;
    for (let i = 0; i <= n; i++) {
      const s = spine[i], nx = -Math.sin(s.a), ny = Math.cos(s.a), w = widths[i];
      L[i * 2] = s.x + nx * w + dx; L[i * 2 + 1] = s.y + ny * w + dy;
      R[i * 2] = s.x - nx * w + dx; R[i * 2 + 1] = s.y - ny * w + dy;
    }
    const h = spine[0], fx = -Math.cos(h.a), fy = -Math.sin(h.a);
    ctx.beginPath();
    ctx.moveTo(R[0], R[1]);
    ctx.quadraticCurveTo(h.x + dx + fx * nose * 2, h.y + dy + fy * nose * 2, L[0], L[1]);
    for (let i = 1; i < n; i++) ctx.quadraticCurveTo(L[i * 2], L[i * 2 + 1], (L[i * 2] + L[i * 2 + 2]) / 2, (L[i * 2 + 1] + L[i * 2 + 3]) / 2);
    ctx.lineTo(L[n * 2], L[n * 2 + 1]);
    ctx.lineTo(R[n * 2], R[n * 2 + 1]);
    for (let i = n - 1; i > 0; i--) ctx.quadraticCurveTo(R[i * 2], R[i * 2 + 1], (R[i * 2] + R[i * 2 - 2]) / 2, (R[i * 2 + 1] + R[i * 2 - 1]) / 2);
    ctx.lineTo(R[0], R[1]);
    ctx.closePath();
  }
}
