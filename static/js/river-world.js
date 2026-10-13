/*
 * river-world.js: the stream itself. The channel (banks, depth, current, rocks), the ripples
 * on the surface and the sun flecks under the canopy. Each of these is computed here once and
 * read by both the shader and the animals, so the trout and the water agree about where the
 * current runs and where the sun falls.
 */
import { M } from "./river-core.js";

export const BROOK = Object.freeze({
  layoutSeed: 41,
  /** The rock outline: radius * (1 + a1 sin 3θ + a2 sin 5θ + a3 sin 8θ). The shaders get the same numbers. */
  rockWobble: Object.freeze([0.085, 0.045, 0.02]),
  /** Toward the sun, screen axes (x right, y down, z up). Late afternoon, from the upper left. */
  sun: (() => { const v = [-0.42, -0.52, 0.74], l = Math.hypot(...v); return Object.freeze({ x: v[0] / l, y: v[1] / l, z: v[2] / l }); })(),
  /** Raw canopy value → sun: smoothstep(edge[0], edge[1], raw). One threshold for the shader and the JS. */
  sunEdge: Object.freeze([0.45, 0.58]),
  refractDepth: 0.07,   // refraction shift per unit of depth, as a share of the stream's width
  waterDepth: 0.09,     // the deepest water, as a share of the width; it sets how far shadows fall
  flowShare: 0.12,      // the fastest current, stream widths per second
  maxRocks: 8,
});

/** On the bed, an object `h` px above it throws its shadow by SHADOW * h. */
export const BROOK_SHADOW = Object.freeze({ x: -BROOK.sun.x / BROOK.sun.z, y: -BROOK.sun.y / BROOK.sun.z });

class Rock {
  constructor(x, y, r, height, seed) {
    this.x = x; this.y = y; this.r = r;
    this.height = height;   // in depth units: above the local depth, the top breaks the surface
    this.seed = seed;
  }
  radiusAt(ang) {
    const [a1, a2, a3] = BROOK.rockWobble;
    return this.r * (1 + a1 * Math.sin(3 * ang + this.seed) + a2 * Math.sin(5 * ang + 2 * this.seed) + a3 * Math.sin(8 * ang + 3.3 * this.seed));
  }
  /** How far inside the outline (px, > 0 inside), with a margin added to the radius. */
  inside(x, y, margin = 0) {
    const dx = x - this.x, dy = y - this.y;
    return this.radiusAt(Math.atan2(dy, dx)) + margin - Math.hypot(dx, dy);
  }
  /** Moves `o` (with x, y) out to the outline; returns the outward normal if it had to, else null. */
  pushOut(o, margin = 0) {
    const dx = o.x - this.x, dy = o.y - this.y, d = Math.hypot(dx, dy) || 1;
    const edge = this.radiusAt(Math.atan2(dy, dx)) + margin;
    if (d >= edge) return null;
    const nx = dx / d, ny = dy / d;
    o.x = this.x + nx * edge; o.y = this.y + ny * edge;
    return { x: nx, y: ny };
  }
  get emerges() { return this.height > 0.75; }
}

/**
 * Banks, depth and current. Works in stream space: s along the flow, n across it (CSS px).
 * The stream runs along the long side of the screen: left to right, or top to bottom.
 */
export class Channel {
  constructor(w, h, rng, noise) {
    this.w = w; this.h = h;
    this.landscape = w >= h;
    this.A = this.landscape ? w : h;
    this.C = this.landscape ? h : w;
    this.axis = this.landscape ? { x: 1, y: 0 } : { x: 0, y: 1 };
    this.noise = noise;
    this.phase = rng.range(0, M.TAU);
    this.vmax = this.C * BROOK.flowShare;
    this.rocks = [];
    this.placeRocks(rng);
    this.buildGrid();
  }
  sOf(x, y) { return this.landscape ? x : y; }
  nOf(x, y) { return this.landscape ? y : x; }
  xy(s, n) { return this.landscape ? { x: s, y: n } : { x: n, y: s }; }
  centre(s) {
    const k = s / this.C;
    return this.C * (0.5 + 0.06 * Math.sin(k * 1.9 + this.phase) + 0.025 * Math.sin(k * 4.3 + 2.2 + this.phase));
  }
  halfWidth(s) { return this.C * (0.33 + 0.03 * Math.sin(s / this.C * 2.7 + 1.1 + this.phase)); }
  /** Signed distance to the shore, px: > 0 in the water, < 0 on land. Rocks are not counted. */
  shore(s, n) {
    const c = this.centre(s), side = n < c ? -1 : 1;
    const wobble = this.C * 0.028 * this.noise.fbm(s / this.C * 5, side * 3.7, 3);
    return this.halfWidth(s) + wobble - Math.abs(n - c);
  }
  pools(s) { return 0.72 + 0.28 * Math.sin(s / this.C * 2.3 + 0.4 + this.phase); }
  /** Water depth 0..1 at a stream point, rocks not counted. */
  depthAt(s, n) {
    const d = this.shore(s, n);
    if (d <= 0) return 0;
    const x = M.clamp(d / (this.halfWidth(s) * 0.75), 0, 1);
    return (1 - Math.pow(1 - x, 2.2)) * this.pools(s);
  }
  /** Current at a stream point (stream space, px/s): faster in the middle and over riffles, bent round rocks. */
  flowAt(s, n) {
    const d = this.shore(s, n);
    if (d <= 0) return [0, 0];
    const x = M.clamp(d / (this.halfWidth(s) * 0.8), 0, 1);
    const speed = this.vmax * Math.pow(x, 0.6) * (1.25 - 0.45 * this.pools(s));
    const slope = (this.centre(s + 2) - this.centre(s - 2)) / 4;
    let vs = speed, vn = speed * slope;
    let shelter = 0;
    for (const rk of this.rocks) {
      const dS = s - this.sOf(rk.x, rk.y), dN = n - this.nOf(rk.x, rk.y), R = rk.r;
      const r2 = dS * dS + dN * dN;
      if (r2 < R * R) return [0, 0];
      if (r2 > R * R * 49) continue;
      // potential flow round a cylinder: u - iv = U (1 - R²/z²)
      const R2 = R * R, r4 = r2 * r2;
      vs += -speed * R2 * (dS * dS - dN * dN) / r4;
      vn += -speed * R2 * 2 * dS * dN / r4;
      if (dS > 0) shelter = Math.max(shelter, 0.82 * Math.exp(-((dN / R) ** 2)) * Math.exp(-(dS - R) / (R * 3.5)));
    }
    return [vs * (1 - shelter), vn * (1 - shelter)];
  }
  /** Broken water: the shear lines behind rocks and the fast, shallow riffles. 0..1. */
  turbAt(s, n, depth, speedNorm) {
    let t = 0;
    for (const rk of this.rocks) {
      const dS = s - this.sOf(rk.x, rk.y), dN = n - this.nOf(rk.x, rk.y), R = rk.r;
      if (dS < -R * 1.5 || dS > R * 14) continue;
      const shear = Math.exp(-(((Math.abs(dN) - R * 0.9) / (R * 0.5)) ** 2));
      const along = dS < R ? Math.exp(-(((dS - R * 0.2) / R) ** 2) * 0.5) : Math.exp(-(dS - R) / (R * 5));
      t += shear * along * (rk.emerges ? 1 : 0.4);
    }
    t += M.smooth(0.7, 1.05, speedNorm) * (1 - depth) * 0.5;
    return M.clamp(t, 0, 1);
  }
  placeRocks(rng) {
    const { A, C } = this;
    const count = M.clamp(Math.round(A / C * 2.4), 3, BROOK.maxRocks - 2);
    for (let i = 0; i < count; i++) {
      for (let tries = 0; tries < 40; tries++) {
        const s = A * (0.06 + 0.88 * (i + rng.range(0.1, 0.9)) / count);
        const n = this.centre(s) + this.halfWidth(s) * rng.range(-0.7, 0.7);
        const r = C * rng.range(0.04, 0.072);
        const p = this.xy(s, n);
        if (this.rocks.some(o => Math.hypot(o.x - p.x, o.y - p.y) < (o.r + r) * 2.1)) continue;
        const depth = this.depthAt(s, n);
        // most rocks break the surface; one in four lies under it, furred with algae
        const height = rng.chance(0.25) ? depth * rng.range(0.45, 0.7) : depth + rng.range(0.2, 0.55);
        this.rocks.push(new Rock(p.x, p.y, r, height, rng.range(0, 100)));
        break;
      }
    }
    for (const side of [-1, 1]) {
      const s = A * rng.range(0.2, 0.8);
      const p = this.xy(s, this.centre(s) + side * this.halfWidth(s) * 0.97);
      this.rocks.push(new Rock(p.x, p.y, C * rng.range(0.06, 0.085), 1.4, rng.range(0, 100)));
    }
  }
  buildGrid() {
    const big = 192;
    const gw = this.w >= this.h ? big : Math.max(24, Math.round(big * this.w / this.h));
    const gh = this.w >= this.h ? Math.max(24, Math.round(big * this.h / this.w)) : big;
    const n = gw * gh;
    Object.assign(this, { gw, gh, gDepth: new Float32Array(n), gVx: new Float32Array(n), gVy: new Float32Array(n),
      gTurb: new Float32Array(n), bytes: new Uint8Array(n * 4) });
    const enc = 127 / (this.vmax * 1.8);
    for (let j = 0; j < gh; j++) {
      for (let i = 0; i < gw; i++) {
        const x = (i + 0.5) / gw * this.w, y = (j + 0.5) / gh * this.h;
        const s = this.sOf(x, y), nn = this.nOf(x, y);
        const shore = this.shore(s, nn);
        const depth = shore > 0 ? this.depthAt(s, nn) : 0;
        const [vs, vn] = this.flowAt(s, nn);
        const v = this.xy(vs, vn);
        const turb = depth > 0 ? this.turbAt(s, nn, depth, Math.hypot(vs, vn) / this.vmax) : 0;
        const k = j * gw + i;
        this.gDepth[k] = depth; this.gVx[k] = v.x; this.gVy[k] = v.y; this.gTurb[k] = turb;
        // r: 0.5 is the shore; above it the depth, below it how far inland (up to a quarter width)
        const code = shore > 0 ? 0.5 + 0.5 * depth : 0.5 - 0.5 * Math.min(1, -shore / (this.C * 0.25));
        this.bytes[k * 4] = Math.round(code * 255);
        this.bytes[k * 4 + 1] = M.clamp(Math.round(128 + v.x * enc), 0, 255);
        this.bytes[k * 4 + 2] = M.clamp(Math.round(128 - v.y * enc), 0, 255);   // y up for the shader
        this.bytes[k * 4 + 3] = Math.round(turb * 255);
      }
    }
  }
  /** Depth, current (screen px/s) and broken water at a screen point, interpolated from the grid. */
  sample(x, y) {
    const gw = this.gw, gh = this.gh;
    const gx = M.clamp(x / this.w * gw - 0.5, 0, gw - 1.001), gy = M.clamp(y / this.h * gh - 0.5, 0, gh - 1.001);
    const i = gx | 0, j = gy | 0, tx = gx - i, ty = gy - j;
    const k = j * gw + i;
    const bl = a => (a[k] * (1 - tx) + a[k + 1] * tx) * (1 - ty) + (a[k + gw] * (1 - tx) + a[k + gw + 1] * tx) * ty;
    return { depth: bl(this.gDepth), vx: bl(this.gVx), vy: bl(this.gVy), turb: bl(this.gTurb) };
  }
  rockAt(x, y, margin = 0) {
    for (const r of this.rocks) if (r.inside(x, y, margin) > 0) return r;
    return null;
  }
  isWater(x, y, minDepth = 0.04) {
    return this.sample(x, y).depth >= minDepth && !this.rockAt(x, y);
  }
  /** A move of `dn` px across the stream, as a screen vector. */
  across(dn) { return this.landscape ? { x: 0, y: dn } : { x: dn, y: 0 }; }
  /**
   * How far (px, across the stream, signed) a point must move toward the middle to stand `margin` px inside the
   * water's edge: 0 when it already does. The bank is drawn over the edge; what crosses it swims under the moss.
   */
  inward(x, y, margin = 0) {
    const s = this.sOf(x, y);
    let n = this.nOf(x, y), moved = 0;
    for (let i = 0; i < 3; i++) {
      const d = this.shore(s, n);
      if (d >= margin) break;
      const step = (n < this.centre(s) ? 1 : -1) * (margin - d);
      n += step; moved += step;
    }
    return moved;
  }
  /**
   * The way a startled animal at (x, y) may dart from (fromX, fromY): along the stream only, downstream or up, whichever
   * lies away from it — the banks shut the other ways. Level with the danger (within `level` px along the stream): downstream.
   */
  away(x, y, fromX, fromY, level = 0) {
    const ds = this.sOf(x, y) - this.sOf(fromX, fromY);
    const sign = Math.abs(ds) <= level ? 1 : Math.sign(ds);
    return { x: this.axis.x * sign, y: this.axis.y * sign };
  }
  /** Unit vector toward deeper water at a screen point. */
  deeper(x, y) {
    const e = this.C * 0.02;
    const gx = this.sample(x + e, y).depth - this.sample(x - e, y).depth;
    const gy = this.sample(x, y + e).depth - this.sample(x, y - e).depth;
    const l = Math.hypot(gx, gy);
    if (l > 1e-6) return { x: gx / l, y: gy / l };
    const c = this.xy(this.sOf(x, y), this.centre(this.sOf(x, y)));
    const dx = c.x - x, dy = c.y - y, d = Math.hypot(dx, dy) || 1;
    return { x: dx / d, y: dy / d };
  }
  /** Shadow height of a point on the surface above the bed, CSS px. */
  waterDepthPx(depth) { return depth * this.C * BROOK.waterDepth; }
}

/**
 * Ripples: a damped wave equation on a coarse grid, carried downstream by the current, so
 * rings drift with the water as real ones do. The shader reads its slopes as extra normals.
 */
export class RippleField {
  constructor(channel) {
    const big = 220, w = channel.w, h = channel.h;
    this.cols = w >= h ? big : Math.max(24, Math.round(big * w / h));
    this.rows = w >= h ? Math.max(24, Math.round(big * h / w)) : big;
    this.sx = this.cols / w; this.sy = this.rows / h;
    const n = this.cols * this.rows;
    this.cur = new Float32Array(n); this.prev = new Float32Array(n); this.next = new Float32Array(n);
    this.tmpA = new Float32Array(n); this.tmpB = new Float32Array(n);
    this.water = new Uint8Array(n);
    this.fx = new Float32Array(n); this.fy = new Float32Array(n);
    this.bytes = new Uint8Array(n * 4);
    for (let j = 0; j < this.rows; j++) {
      for (let i = 0; i < this.cols; i++) {
        const x = (i + 0.5) / this.sx, y = (j + 0.5) / this.sy, k = j * this.cols + i;
        const s = channel.sample(x, y);
        this.water[k] = s.depth > 0.02 && !channel.rockAt(x, y) ? 1 : 0;
        this.fx[k] = s.vx * this.sx / 60;   // cells per step
        this.fy[k] = s.vy * this.sy / 60;
      }
    }
    this.acc = 0;
  }
  /** Presses the surface down at a screen point: amount ~0.1 (a strider) to ~2 (a pebble). */
  disturb(x, y, amount, radius) {
    const cx = x * this.sx, cy = y * this.sy, rc = Math.max(0.8, radius * this.sx);
    const i0 = Math.max(1, Math.floor(cx - rc * 2)), i1 = Math.min(this.cols - 2, Math.ceil(cx + rc * 2));
    const j0 = Math.max(1, Math.floor(cy - rc * 2)), j1 = Math.min(this.rows - 2, Math.ceil(cy + rc * 2));
    for (let j = j0; j <= j1; j++) {
      for (let i = i0; i <= i1; i++) {
        const dx = i + 0.5 - cx, dy = j + 0.5 - cy, d2 = (dx * dx + dy * dy) / (rc * rc);
        if (d2 < 4) { const k = j * this.cols + i; this.cur[k] -= amount * Math.exp(-d2 * 1.5) * this.water[k]; }
      }
    }
  }
  step(dt) {
    this.acc = Math.min(this.acc + dt, 0.1);
    while (this.acc >= 1 / 60) {
      this.acc -= 1 / 60;
      this.wave();
      this.advect();
    }
  }
  wave() {
    const { cols, rows, cur, prev, next, water } = this;
    const c2 = 0.24, damp = 0.986;
    for (let j = 1; j < rows - 1; j++) {
      for (let i = 1; i < cols - 1; i++) {
        const k = j * cols + i;
        if (!water[k]) { next[k] = 0; continue; }
        const lap = cur[k - 1] + cur[k + 1] + cur[k - cols] + cur[k + cols] - 4 * cur[k];
        next[k] = (2 * cur[k] - prev[k] + c2 * lap) * damp;
      }
    }
    this.prev = cur; this.cur = next; this.next = prev;
  }
  advect() {
    const { cols, rows, fx, fy } = this;
    const move = (src, dst) => {
      for (let j = 0; j < rows; j++) {
        for (let i = 0; i < cols; i++) {
          const k = j * cols + i;
          const x = M.clamp(i - fx[k], 0, cols - 1.001), y = M.clamp(j - fy[k], 0, rows - 1.001);
          const i0 = x | 0, j0 = y | 0, tx = x - i0, ty = y - j0, q = j0 * cols + i0;
          dst[k] = (src[q] * (1 - tx) + src[q + 1] * tx) * (1 - ty) + (src[q + cols] * (1 - tx) + src[q + cols + 1] * tx) * ty;
        }
      }
    };
    move(this.cur, this.tmpA); move(this.prev, this.tmpB);
    [this.cur, this.tmpA] = [this.tmpA, this.cur];
    [this.prev, this.tmpB] = [this.tmpB, this.prev];
  }
  /** Slopes and height as bytes for the shader: r, g = slope x, y (y up), b = height. */
  pack() {
    const { cols, rows, cur, bytes } = this;
    for (let j = 0; j < rows; j++) {
      for (let i = 0; i < cols; i++) {
        const k = j * cols + i;
        const l = cur[i > 0 ? k - 1 : k], r = cur[i < cols - 1 ? k + 1 : k];
        const u = cur[j > 0 ? k - cols : k], d = cur[j < rows - 1 ? k + cols : k];
        bytes[k * 4] = M.clamp(128 + (r - l) * 150, 0, 255);
        bytes[k * 4 + 1] = M.clamp(128 - (d - u) * 150, 0, 255);
        bytes[k * 4 + 2] = M.clamp(128 + cur[k] * 120, 0, 255);
        bytes[k * 4 + 3] = 255;
      }
    }
    return bytes;
  }
}

/**
 * Sun flecks through the canopy: a slow-moving noise field on a coarse grid. The shader
 * sharpens it into flecks; the animals and leaves above the water read the same grid, so a
 * leaf that drifts into the shade darkens with the water around it.
 */
export class CanopyLight {
  constructor(w, h, C, noise) {
    const big = 128;
    this.cols = w >= h ? big : Math.max(16, Math.round(big * w / h));
    this.rows = w >= h ? Math.max(16, Math.round(big * h / w)) : big;
    this.w = w; this.h = h; this.C = C; this.noise = noise;
    const n = this.cols * this.rows;
    this.front = new Float32Array(n); this.back = new Float32Array(n);
    this.bytes = new Uint8Array(n * 4);
    this.row = 0;
    this.dirty = true;
    this.fill(this.front, 0, this.rows, 0);
    this.pack();
  }
  raw(x, y, t) {
    const n = this.noise, k = 3.2 / this.C;
    const qx = x * k + Math.sin(t * 0.043) * 0.22, qy = y * k + Math.cos(t * 0.031) * 0.22;
    // leaves grow in clumps: warp the field so the gaps between them are ragged, not round
    const wx = n.n2(qx * 0.7 + 11.3, qy * 0.7 - 4.1) * 0.35;
    const wy = n.n2(qx * 0.7 - 7.9, qy * 0.7 + 2.6) * 0.35;
    // whole crowns cast the large, slow shade
    const crowns = n.n2(x * 0.9 / this.C + 3.3, y * 0.9 / this.C - 1.7) * 0.16;
    return 0.47 + 0.62 * n.fbm(qx + wx, qy + wy, 4) + crowns;
  }
  fill(target, j0, j1, t) {
    for (let j = j0; j < j1; j++) {
      for (let i = 0; i < this.cols; i++) {
        target[j * this.cols + i] = this.raw((i + 0.5) / this.cols * this.w, (j + 0.5) / this.rows * this.h, t);
      }
    }
  }
  /** Computes a slice of the next field each frame; swaps when a whole field is ready (~10 Hz). */
  step(t) {
    const slice = Math.ceil(this.rows / 6);
    const j1 = Math.min(this.rows, this.row + slice);
    this.fill(this.back, this.row, j1, t);
    this.row = j1;
    if (this.row >= this.rows) {
      [this.front, this.back] = [this.back, this.front];
      this.row = 0;
      this.pack();
      this.dirty = true;
    }
  }
  pack() {
    for (let k = 0; k < this.front.length; k++) {
      const v = M.clamp(Math.round(this.front[k] * 255), 0, 255);
      this.bytes[k * 4] = v; this.bytes[k * 4 + 1] = v; this.bytes[k * 4 + 2] = v; this.bytes[k * 4 + 3] = 255;
    }
  }
  /** Sun at a screen point: 0 in the shade, 1 in a fleck. */
  sunAt(x, y) {
    const gx = M.clamp(x / this.w * this.cols - 0.5, 0, this.cols - 1.001), gy = M.clamp(y / this.h * this.rows - 0.5, 0, this.rows - 1.001);
    const i = gx | 0, j = gy | 0, tx = gx - i, ty = gy - j, k = j * this.cols + i, a = this.front;
    const v = (a[k] * (1 - tx) + a[k + 1] * tx) * (1 - ty) + (a[k + this.cols] * (1 - tx) + a[k + this.cols + 1] * tx) * ty;
    return M.smooth(BROOK.sunEdge[0], BROOK.sunEdge[1], v);
  }
  /** The light factor the shader applies to a lit surface, for the same point. */
  lightAt(x, y) { return M.lerp(0.55, 1.15, this.sunAt(x, y)); }
}
