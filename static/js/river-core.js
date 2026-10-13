/*
 * river-core.js: the groundwork of the brook behind the pages — seeded randomness and noise,
 * small helpers, drawing layers and sprites — and the Stage that runs the brook: it sizes it,
 * feeds it frames and the page's pointer, lowers the resolution on a slow machine and lets
 * everything go on dispose. The brook comes from the concept page of 2026-10-13.
 */

/** Seeded random numbers (mulberry32): a scene is laid out the same way on every load. */
export class Rng {
  constructor(seed) { this.state = (seed >>> 0) || 1; }
  next() {
    let t = (this.state = (this.state + 0x6D2B79F5) >>> 0);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }
  range(a, b) { return a + (b - a) * this.next(); }
  int(a, b) { return Math.floor(a + (b - a + 1) * this.next()); }
  pick(list) { return list[Math.floor(this.next() * list.length)]; }
  chance(p) { return this.next() < p; }
  sign() { return this.next() < 0.5 ? -1 : 1; }
  gauss() {
    const u = 1 - this.next(), v = this.next();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }
}

const GRAD2 = [[1, 1], [-1, 1], [1, -1], [-1, -1], [1, 0], [-1, 0], [1, 0], [-1, 0], [0, 1], [0, -1], [0, 1], [0, -1]];

/** 2D simplex noise (Gustavson) over a seeded permutation. */
export class Noise {
  constructor(rng) {
    const p = new Uint8Array(256);
    for (let i = 0; i < 256; i++) p[i] = i;
    for (let i = 255; i > 0; i--) {
      const j = Math.floor(rng.next() * (i + 1));
      const t = p[i]; p[i] = p[j]; p[j] = t;
    }
    this.perm = new Uint8Array(512);
    this.grad = new Uint8Array(512);
    for (let i = 0; i < 512; i++) { this.perm[i] = p[i & 255]; this.grad[i] = this.perm[i] % 12; }
  }
  n2(x, y) {
    const F2 = 0.3660254037844386, G2 = 0.21132486540518713;
    const s = (x + y) * F2, i = Math.floor(x + s), j = Math.floor(y + s);
    const t = (i + j) * G2, x0 = x - (i - t), y0 = y - (j - t);
    const i1 = x0 > y0 ? 1 : 0, j1 = 1 - i1;
    const x1 = x0 - i1 + G2, y1 = y0 - j1 + G2, x2 = x0 - 1 + 2 * G2, y2 = y0 - 1 + 2 * G2;
    const ii = i & 255, jj = j & 255, perm = this.perm, grad = this.grad;
    let n = 0, q;
    q = 0.5 - x0 * x0 - y0 * y0;
    if (q > 0) { const g = GRAD2[grad[ii + perm[jj]]]; q *= q; n += q * q * (g[0] * x0 + g[1] * y0); }
    q = 0.5 - x1 * x1 - y1 * y1;
    if (q > 0) { const g = GRAD2[grad[ii + i1 + perm[jj + j1]]]; q *= q; n += q * q * (g[0] * x1 + g[1] * y1); }
    q = 0.5 - x2 * x2 - y2 * y2;
    if (q > 0) { const g = GRAD2[grad[ii + 1 + perm[jj + 1]]]; q *= q; n += q * q * (g[0] * x2 + g[1] * y2); }
    return 70 * n;
  }
  fbm(x, y, octaves = 4) {
    let sum = 0, amp = 0.5, norm = 0, f = 1;
    for (let o = 0; o < octaves; o++) { sum += amp * this.n2(x * f, y * f); norm += amp; amp *= 0.5; f *= 2.03; }
    return sum / norm;
  }
}

/*
 * Plain arithmetic, kept as functions on purpose: none of it holds state, and a class around
 * clamp() and lerp() would only add a name to type.
 */
export const M = Object.freeze({
  TAU: Math.PI * 2,
  clamp: (v, a, b) => (v < a ? a : v > b ? b : v),
  lerp: (a, b, t) => a + (b - a) * t,
  smooth(a, b, v) { const t = M.clamp((v - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); },
  wrap: a => Math.atan2(Math.sin(a), Math.cos(a)),
  /** Frame-rate independent pull of `cur` toward `target`: `rate` is per second. */
  approach: (cur, target, rate, dt) => target + (cur - target) * Math.exp(-rate * dt),
  turnToward(cur, target, maxStep) {
    const d = M.wrap(target - cur);
    return cur + M.clamp(d, -maxStep, maxStep);
  },
  rgba: (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`,
  mix: (c1, c2, t) => [c1[0] + (c2[0] - c1[0]) * t, c1[1] + (c2[1] - c1[1]) * t, c1[2] + (c2[2] - c1[2]) * t],
  hex(h) { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; },
});

/** An offscreen canvas with its 2D context; scenes paint their still layers into these once. */
export class Layer {
  constructor(w, h) {
    this.canvas = document.createElement('canvas');
    this.canvas.width = Math.max(1, Math.round(w));
    this.canvas.height = Math.max(1, Math.round(h));
    this.ctx = this.canvas.getContext('2d');
  }
  get width() { return this.canvas.width; }
  get height() { return this.canvas.height; }
}

/** A sprite: the picture, its black silhouette for shadows, its size (CSS px) and its pivot. */
export class Sprite {
  constructor(w, h, dpr, ox, oy) {
    this.w = w; this.h = h; this.ox = ox; this.oy = oy;
    this.art = new Layer(w * dpr, h * dpr);
    this.art.ctx.scale(dpr, dpr);
    this.shadow = null;
  }
  get ctx() { return this.art.ctx; }
  /** Makes the silhouette from the painted picture. Call once painting is done. */
  seal() {
    const s = new Layer(this.art.width, this.art.height);
    s.ctx.drawImage(this.art.canvas, 0, 0);
    s.ctx.globalCompositeOperation = 'source-in';
    s.ctx.fillStyle = '#000';
    s.ctx.fillRect(0, 0, s.width, s.height);
    this.shadow = s;
    return this;
  }
  draw(ctx, x, y, angle, scale = 1, alpha = 1, shadow = false) {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.globalAlpha = alpha;
    ctx.drawImage((shadow ? this.shadow : this.art).canvas, -this.ox * scale, -this.oy * scale, this.w * scale, this.h * scale);
    ctx.restore();
  }
}

/**
 * Watches the frame interval and lowers the scene's resolution when the machine cannot keep
 * up, then raises it again when there is room. A background page must not heat the laptop.
 */
export class QualityGovernor {
  constructor() {
    this.levels = [1, 0.85, 0.7, 0.55, 0.42];
    this.index = 0;
    this.avg = 1 / 60;
    this.slowFor = 0;
    this.fastFor = 0;
    this.settleFor = 2;   // the first frames after a change are not representative
  }
  get level() { return this.levels[this.index]; }
  /** Returns true when the level changed and the scene must rebuild its buffers. */
  observe(dt) {
    this.avg += (dt - this.avg) * 0.05;
    if (this.settleFor > 0) { this.settleFor -= dt; return false; }
    this.slowFor = this.avg > 1 / 40 ? this.slowFor + dt : 0;
    this.fastFor = this.avg < 1 / 57 ? this.fastFor + dt : 0;
    if (this.slowFor > 1.5 && this.index < this.levels.length - 1) return this.step(1);
    if (this.fastFor > 8 && this.index > 0) return this.step(-1);
    return false;
  }
  step(d) {
    this.index += d;
    this.slowFor = this.fastFor = 0;
    this.settleFor = 2;
    return true;
  }
}

/** Where the pointer is over the stage and how fast it moves, in CSS pixels. */
export class PointerState {
  constructor() {
    this.x = 0; this.y = 0;
    this.vx = 0; this.vy = 0;
    this.inside = false;
    this.down = false;
    this.lastMove = -1;     // stage time of the last move; -1 = the pointer never moved here
    this.kind = 'mouse';
  }
  get speed() { return Math.hypot(this.vx, this.vy); }
  move(x, y, now) {
    if (this.lastMove >= 0) {
      const dt = Math.max(1 / 240, now - this.lastMove);
      this.vx = M.lerp(this.vx, (x - this.x) / dt, 0.35);
      this.vy = M.lerp(this.vy, (y - this.y) / dt, 0.35);
    }
    this.x = x; this.y = y; this.lastMove = now; this.inside = true;
  }
  settle(dt) {
    this.vx = M.approach(this.vx, 0, 6, dt);
    this.vy = M.approach(this.vy, 0, 6, dt);
  }
}


/**
 * Runs the brook behind a page: sizes it with its box, feeds it frames and the pointer events
 * the page hands over (the stage sits under the page and never gets the pointer itself), and
 * lets everything go on dispose.
 *
 * Frames are drawn every `frameStep` seconds (30 a second by default: a background needs no
 * more, and every other screen frame is left to the page). The quality governor still watches
 * the screen's own pace, so a slow machine gets a lighter brook. A paused stage keeps its last
 * frame and draws nothing.
 *
 * The scene contract: constructor(stage), resize(w, h, dpr), frame(dt, t),
 * pointer(kind, p) with kind 'move' | 'down' | 'up' | 'leave' | 'double', soundscape(kit),
 * dispose().
 */
export class Stage {
  constructor(root, { frameStep = 1 / 30 } = {}) {
    this.root = root;
    this.scene = null;
    this.width = 1; this.height = 1; this.dpr = 1;
    this.time = 0;
    this.lastFrame = 0;
    this.pending = 0;            // screen time not drawn yet
    this.frameStep = frameStep;
    this.paused = false;
    this.alive = true;
    this.quality = new QualityGovernor();
    this.pointer = new PointerState();
    this.motionQuery = matchMedia('(prefers-reduced-motion: reduce)');
    this.lastTap = { t: -1, x: 0, y: 0 };
    this.tick = this.tick.bind(this);
    this.onVisibility = () => { this.lastFrame = 0; };
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(root);
    document.addEventListener('visibilitychange', this.onVisibility);
    this.frameId = requestAnimationFrame(this.tick);
  }
  get reducedMotion() { return this.motionQuery.matches; }
  show(SceneClass) {
    if (this.scene) this.scene.dispose();
    this.root.replaceChildren();
    this.quality = new QualityGovernor();
    this.scene = new SceneClass(this);
    this.resize();
    return this.scene;
  }
  resize() {
    const r = this.root.getBoundingClientRect();
    this.width = Math.max(1, Math.round(r.width));
    this.height = Math.max(1, Math.round(r.height));
    this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (this.scene) this.scene.resize(this.width, this.height, this.dpr);
  }
  /** A pointer event of the page, in the page's coordinates; the background passes them on. */
  onPointer(kind, e) {
    const r = this.root.getBoundingClientRect();
    const x = e.clientX - r.left, y = e.clientY - r.top, p = this.pointer;
    p.kind = e.pointerType || 'mouse';
    if (kind === 'leave') { p.inside = false; p.down = false; }
    else p.move(x, y, this.time);
    if (kind === 'down') {
      p.down = true;
      const tap = this.lastTap;
      const isDouble = this.time - tap.t < 0.35 && Math.hypot(x - tap.x, y - tap.y) < 30;
      this.lastTap = { t: isDouble ? -1 : this.time, x, y };
      if (this.scene) this.scene.pointer(isDouble ? 'double' : 'down', p);
      return;
    }
    if (kind === 'up') p.down = false;
    if (this.scene) this.scene.pointer(kind, p);
  }
  tick(now) {
    if (!this.alive) return;
    this.frameId = requestAnimationFrame(this.tick);
    const dt = this.lastFrame ? Math.min((now - this.lastFrame) / 1000, 1 / 20) : 1 / 60;
    this.lastFrame = now;
    // No document.hidden check: the browser already stops animation frames in a hidden tab.
    if (this.quality.observe(dt)) this.resize();
    if (this.paused) return;
    this.pending += dt;
    if (this.pending + 0.004 < this.frameStep) return;
    this.advance(Math.min(this.pending, 0.1));
    this.pending = 0;
  }
  /** One frame of `dt` seconds; a test steps the scene by hand with it. */
  advance(dt) {
    if (!this.scene) return;
    this.time += dt;
    this.scene.frame(dt, this.time);
    this.pointer.settle(dt);
  }
  dispose() {
    this.alive = false;
    cancelAnimationFrame(this.frameId);
    this.observer.disconnect();
    document.removeEventListener('visibilitychange', this.onVisibility);
    if (this.scene) this.scene.dispose();
    this.scene = null;
    this.root.replaceChildren();
  }
}
