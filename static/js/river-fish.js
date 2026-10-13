/*
 * river-fish.js: the fish of the brook. A trout holds its lie behind a rock, facing the current,
 * and rises to insects that drift over it; a shoal of Colchic minnows works the shallows. Both
 * swim the same way (Swimmer): they want a ground velocity, the current pushes them, and they
 * swim through the water only where they point. A fish cannot swim sideways: it turns first,
 * and its turn builds up and settles like a body's would.
 */
import { M } from "./river-core.js";
import { BROOK_SHADOW } from "./river-world.js";

class Swimmer {
  constructor(x, y, len, segments, rng) {
    this.x = x; this.y = y; this.len = len;
    this.heading = rng.range(0, M.TAU);
    this.goal = this.heading;
    this.speed = 0; this.vx = 0; this.vy = 0;
    this.turnRate = 0; this.amp = 0.1; this.bend = 0;
    this.phase = rng.range(0, M.TAU);
    this.fin = rng.range(0, M.TAU);
    this.depth = 0.5;
    this.spine = Array.from({ length: segments + 1 }, () => ({ x, y, a: 0 }));
    this.widths = new Float32Array(segments + 1);
    this.inner = new Float32Array(segments + 1);
  }
  /** Ground velocity toward a point, slowing inside `slow` px. */
  seek(x, y, speed, slow = this.len) {
    const dx = x - this.x, dy = y - this.y, d = Math.hypot(dx, dy) || 1;
    const v = slow > 0 ? Math.min(speed, speed * d / slow) : speed;
    return { x: dx / d * v, y: dy / d * v };
  }
  /** Moves the fish: `want` is a ground velocity; `cap` (px/s), `turn` (rad/s), `accel` (1/s) limit it. */
  swim(dt, channel, want, cap, turn, accel, minDepth = 0.16) {
    const water = channel.sample(this.x, this.y);
    // a fish keeps low, in the slack water near the bed: it feels only part of the surface current
    const cx = water.vx * Swimmer.CURRENT_FELT, cy = water.vy * Swimmer.CURRENT_FELT;
    for (const r of channel.rocks) {
      const ahead = r.inside(this.x, this.y, this.len * 0.9);
      if (ahead > 0) {
        const dx = this.x - r.x, dy = this.y - r.y, d = Math.hypot(dx, dy) || 1;
        want.x += dx / d * ahead * 3; want.y += dy / d * ahead * 3;
      }
    }
    // shallows are steered away from, not shoved out of
    if (water.depth < minDepth) {
      const g = channel.deeper(this.x, this.y), k = (minDepth - water.depth) * this.len * 8;
      want.x += g.x * k; want.y += g.y * k;
    }
    let sx = want.x - cx, sy = want.y - cy;
    let sp = Math.hypot(sx, sy);
    if (sp > cap) { sx *= cap / sp; sy *= cap / sp; sp = cap; }
    if (sp > this.len * 0.05) this.goal = Math.atan2(sy, sx);
    // the turn: its rate builds and settles, and a fish with no way on turns slowly
    const err = M.wrap(this.goal - this.heading);
    const way = M.clamp(this.speed / (this.len * 1.5), 0, 1);
    const wantRate = M.clamp(err * 2.4, -turn, turn) * (0.35 + 0.65 * way);
    this.turnRate = M.approach(this.turnRate, wantRate, Swimmer.TURN_EASE, dt);
    this.heading = M.wrap(this.heading + this.turnRate * dt);
    // it swims only where it points; turned away from where it wants to go, it hardly swims at all
    const facing = Math.max(0, Math.cos(M.wrap(this.goal - this.heading)));
    this.speed = M.approach(this.speed, sp * facing * facing, accel, dt);
    // through the water it moves along its body; what is left of its old way sideways dies fast,
    // since water presses hard on a flank. The current's share is laid on top.
    const hx = Math.cos(this.heading), hy = Math.sin(this.heading);
    const ux = this.vx - cx, uy = this.vy - cy;
    const side = M.approach(-ux * hy + uy * hx, 0, Swimmer.FLANK_DRAG, dt);
    this.vx = hx * this.speed - hy * side + cx;
    this.vy = hy * this.speed + hx * side + cy;
    this.x += this.vx * dt; this.y += this.vy * dt;
    this.stayInWater(channel);
    this.depth = water.depth;
    this.phase += dt * M.TAU * (1.4 + this.speed / this.len * 1.3);
    const wantAmp = 0.08 + Math.min(0.24, Math.abs(this.turnRate) * 0.05) + Math.min(0.14, this.speed / this.len * 0.03);
    this.amp = M.approach(this.amp, wantAmp, 5, dt);
    this.bend = M.approach(this.bend, M.clamp(-this.turnRate * 0.22, -0.9, 0.9), 7, dt);
    this.fin += dt * (2.2 + this.speed / this.len);
    this.buildSpine();
  }
  /**
   * The last resort when steering was not enough: out of a rock, inside the banks, and inside the picture. The bank is
   * drawn over the water's edge, so a fish that crosses it swims under the moss (the owner, 2026-10-13: "they run under
   * the bank"): no point of the body — snout, middle, tail — goes past the edge, and the way it was going into the bank
   * is lost. It may still go along the stream as far as the picture allows.
   */
  stayInWater(channel) {
    for (const r of channel.rocks) r.pushOut(this, this.len * 0.12);
    const margin = this.len * Swimmer.BANK_ROOM, hx = Math.cos(this.heading), hy = Math.sin(this.heading);
    let dn = 0;
    for (const u of [0, 0.5, 1]) {
      const move = channel.inward(this.x - hx * this.len * u, this.y - hy * this.len * u, margin);
      if (Math.abs(move) > Math.abs(dn)) dn = move;
    }
    if (dn) {
      const to = channel.across(dn), into = channel.across(Math.sign(dn));
      this.x += to.x; this.y += to.y;
      const v = this.vx * into.x + this.vy * into.y;
      if (v < 0) { this.vx -= v * into.x; this.vy -= v * into.y; }
    }
    const m = this.len * 0.6;
    this.x = M.clamp(this.x, -m, channel.w + m);
    this.y = M.clamp(this.y, -m, channel.h + m);
  }
  buildSpine() {
    const sp = this.spine, n = sp.length - 1, seg = this.len / n, back = this.heading + Math.PI;
    let x = this.x, y = this.y;
    sp[0].x = x; sp[0].y = y;
    for (let i = 1; i <= n; i++) {
      const u = i / n;
      const a = back + this.amp * Math.pow(u, 1.5) * Math.sin(this.phase - u * 4.4) + this.bend * u;
      sp[i - 1].a = a;
      x += Math.cos(a) * seg; y += Math.sin(a) * seg;
      sp[i].x = x; sp[i].y = y; sp[i].a = a;
    }
  }
  /** A point on the body: u from snout (0) to tail (1), v across from -1 to 1. */
  bodyPoint(u, v, profile) {
    const sp = this.spine, n = sp.length - 1, f = M.clamp(u, 0, 1) * n, i = Math.min(n - 1, Math.floor(f)), t = f - i;
    const a = sp[i], b = sp[i + 1];
    const w = (profile[i] * (1 - t) + profile[i + 1] * t) * this.len;
    return { x: a.x + (b.x - a.x) * t - Math.sin(a.a) * w * v, y: a.y + (b.y - a.y) * t + Math.cos(a.a) * w * v, a: a.a };
  }
  /** The tail fin is upright, so from above it is a narrow wedge that shows more as it beats. */
  tailPath(ctx, k, dx = 0, dy = 0) {
    const sp = this.spine, p = sp[sp.length - 1];
    const a = p.a + Math.sin(this.phase - 4.9) * this.amp * 1.2;
    const cx = Math.cos(a), cy = Math.sin(a), nx = -cy, ny = cx;
    const reach = this.len * 0.17 * k, spread = this.len * (0.035 + 0.04 * Math.abs(Math.sin(this.phase - 4.9))) * k;
    const x = p.x + dx, y = p.y + dy;
    ctx.beginPath();
    ctx.moveTo(x + nx * spread * 0.3, y + ny * spread * 0.3);
    ctx.lineTo(x + cx * reach + nx * spread, y + cy * reach + ny * spread);
    ctx.lineTo(x + cx * reach * 0.86, y + cy * reach * 0.86);
    ctx.lineTo(x + cx * reach - nx * spread, y + cy * reach - ny * spread);
    ctx.lineTo(x - nx * spread * 0.3, y - ny * spread * 0.3);
    ctx.closePath();
  }
  /** A paired fin (pectoral or pelvic): a small translucent blade that rows slowly. */
  pairedFins(ctx, profile, u, size, spreadAngle, colour) {
    for (const side of [-1, 1]) {
      const b = this.bodyPoint(u, side * 0.9, profile);
      const a = b.a + side * (spreadAngle + 0.25 * Math.sin(this.fin + side));
      const l = this.len * size;
      ctx.beginPath();
      ctx.ellipse(b.x + Math.cos(a) * l * 0.5, b.y + Math.sin(a) * l * 0.5, l * 0.5, l * 0.17, a, 0, M.TAU);
      ctx.fillStyle = colour;
      ctx.fill();
    }
  }
}

/** Share of the surface current a fish near the bed is carried by. */
Swimmer.CURRENT_FELT = 0.35;
/** How fast a turn builds up or settles (1/s). */
Swimmer.TURN_EASE = 5;
/** How fast a fish loses sideways way through the water (1/s): its flank is a broad paddle. */
Swimmer.FLANK_DRAG = 12;
/** How far inside the water's edge every point of a fish's body stays, as a share of its length. */
Swimmer.BANK_ROOM = 0.2;

/* Half width along a trout, as a share of its length, snout → tail. */
class TroutShape {
  static profile() {
  const n = 12, w = new Float32Array(n + 1);
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    let k;
    if (u < 0.08) k = 0.62 + 0.3 * (u / 0.08);
    else if (u < 0.3) k = 0.92 + 0.08 * Math.sin((u - 0.08) / 0.22 * Math.PI / 2);
    else k = 1 - 0.78 * Math.pow((u - 0.3) / 0.7, 1.15);
    w[i] = 0.085 * k;
  }
  return w;
  }
}
const TROUT_PROFILE = TroutShape.profile();

const TROUT_LOOK = Object.freeze({
  flank: [172, 150, 86], back: [40, 42, 26], spot: [30, 28, 20], red: [176, 62, 42], halo: [214, 204, 168],
  fin: 'rgba(138, 120, 70, 0.55)', tail: 'rgba(70, 66, 40, 0.8)',
});

/*
 * What a trout does in each state: the ground velocity it wants, its limits (body lengths per
 * second, radians per second, 1/s) and what ends the state. One row per state.
 */
const TROUT_STATES = Object.freeze({
  hold: {
    cap: 2.2, turn: 1.3, accel: 2,
    want(f, life) {
      const t = life.time * 0.07;
      const wx = life.noise.n2(f.seed, t) * f.len * 0.6, wy = life.noise.n2(f.seed + 40, t) * f.len * 0.6;
      return f.seek(f.lie.x + wx, f.lie.y + wy, f.len * 1.2);
    },
    next(f, life) {
      const fly = life.flyFor(f);
      if (fly) { fly.claimedBy = f; f.target = fly; return 'chase'; }
      return f.stateTime > f.roamAfter ? 'roam' : null;
    },
  },
  chase: {
    cap: 4.4, turn: 3.4, accel: 3.6,
    want(f) { const g = f.target; return f.seek(g.x + g.vx * 0.3, g.y + g.vy * 0.3, f.len * 6, 0); },
    next(f, life) {
      const g = f.target;
      if (!g.alive || g.claimedBy !== f) return 'back';
      if (Math.hypot(g.x - f.x, g.y - f.y) < f.len * 0.42) { life.rise(f, g); return 'back'; }
      if (f.stateTime > 6) { g.claimedBy = null; return 'back'; }
      return null;
    },
  },
  back: {
    cap: 2.4, turn: 1.8, accel: 2.4,
    want(f) { return f.seek(f.lie.x, f.lie.y, f.len * 2.2); },
    next(f) { return Math.hypot(f.lie.x - f.x, f.lie.y - f.y) < f.len * 0.7 ? 'hold' : null; },
  },
  roam: {
    cap: 2, turn: 1.5, accel: 2,
    want(f) { return f.seek(f.lie.x, f.lie.y, f.len * 1.6); },
    next(f) { return Math.hypot(f.lie.x - f.x, f.lie.y - f.y) < f.len * 0.7 ? 'hold' : null; },
  },
  flee: {
    cap: 6, turn: 4.5, accel: 6,
    want(f) { return { x: f.away.x * f.len * 9, y: f.away.y * f.len * 9 }; },
    next(f) { return f.stateTime > 0.9 ? 'hide' : null; },
  },
  hide: {
    cap: 2, turn: 1.8, accel: 2.2,
    want(f) { return f.seek(f.hideAt.x, f.hideAt.y, f.len * 2); },
    next(f) { return f.stateTime > f.hideFor ? 'back' : null; },
  },
});

export class Trout extends Swimmer {
  constructor(rng, lie, len) {
    super(lie.x, lie.y, len, 12, rng);
    this.rng = rng;
    this.lie = lie;
    this.seed = rng.range(0, 1000);
    this.state = 'hold';
    this.stateTime = rng.range(0, 10);
    this.roamAfter = rng.range(50, 110);
    this.target = null;
    this.away = { x: 0, y: 0 };
    this.hideAt = { x: lie.x, y: lie.y };
    this.hideFor = 4;
    this.spots = [];
    for (let i = 0; i < 46; i++) {
      const u = rng.range(0.08, 0.78), v = rng.range(-0.95, 0.95);
      this.spots.push({ u, v, r: rng.range(0.008, 0.016), red: false });
    }
    for (let i = 0; i < 9; i++) this.spots.push({ u: rng.range(0.22, 0.68), v: rng.sign() * rng.range(0.74, 0.95), r: rng.range(0.012, 0.017), red: true });
  }
  enter(state, life) {
    if (state === 'back' && this.target) { this.target = null; }
    if (state === 'roam') this.lie = life.freeLie(this) || this.lie;
    if (state === 'hide') { this.hideAt = life.shelterNear(this); this.hideFor = this.rng.range(3, 6); }
    if (state === 'hold') this.roamAfter = this.rng.range(50, 110);
    this.state = state;
    this.stateTime = 0;
  }
  /** Something startled it: dart away from (x, y) — along the stream, the banks shut the other ways. */
  spook(x, y, channel) {
    if (this.state === 'flee') return;
    if (this.target) { this.target.claimedBy = null; this.target = null; }
    this.away = channel.away(this.x, this.y, x, y, this.len * 0.3);
    this.enter('flee');
  }
  update(dt, life) {
    this.stateTime += dt;
    const next = TROUT_STATES[this.state].next(this, life);
    if (next) this.enter(next, life);
    const st = TROUT_STATES[this.state];
    this.swim(dt, life.channel, st.want(this, life), st.cap * this.len, st.turn, st.accel);
  }
  /** Height above the bed (px) — it sets how far the shadow falls. */
  height(channel) { return channel.waterDepthPx(this.depth) * 0.55; }
  draw(ctx, painter) {
    const len = this.len, n = this.spine.length - 1, look = TROUT_LOOK;
    for (let i = 0; i <= n; i++) this.widths[i] = TROUT_PROFILE[i] * len;
    this.tailPath(ctx, 1);
    ctx.fillStyle = look.tail;
    ctx.fill();
    this.pairedFins(ctx, TROUT_PROFILE, 0.2, 0.15, 1.0, look.fin);
    this.pairedFins(ctx, TROUT_PROFILE, 0.52, 0.09, 0.7, look.fin);
    painter.outline(ctx, this.spine, this.widths, len * 0.03);
    ctx.fillStyle = M.rgba(look.flank, 1);
    ctx.fill();
    for (const [k, a] of [[0.74, 0.35], [0.52, 0.45], [0.3, 0.6]]) {
      for (let i = 0; i <= n; i++) this.inner[i] = this.widths[i] * k;
      painter.outline(ctx, this.spine, this.inner, len * 0.02 * k);
      ctx.fillStyle = M.rgba(look.back, a);
      ctx.fill();
    }
    for (const s of this.spots) {
      const p = this.bodyPoint(s.u, s.v, TROUT_PROFILE);
      if (s.red) {
        ctx.fillStyle = M.rgba(look.halo, 0.5);
        ctx.beginPath(); ctx.arc(p.x, p.y, s.r * len * 1.6, 0, M.TAU); ctx.fill();
        ctx.fillStyle = M.rgba(look.red, 0.9);
      } else ctx.fillStyle = M.rgba(look.spot, 0.75);
      ctx.beginPath(); ctx.arc(p.x, p.y, s.r * len, 0, M.TAU); ctx.fill();
    }
    ctx.strokeStyle = 'rgba(28, 26, 18, 0.55)';
    ctx.lineWidth = Math.max(1, len * 0.012);
    ctx.beginPath();
    const d0 = this.bodyPoint(0.36, 0, TROUT_PROFILE), d1 = this.bodyPoint(0.52, 0, TROUT_PROFILE);
    ctx.moveTo(d0.x, d0.y); ctx.lineTo(d1.x, d1.y); ctx.stroke();
    for (const side of [-1, 1]) {
      const e = this.bodyPoint(0.075, side * 0.72, TROUT_PROFILE);
      ctx.fillStyle = '#17150e';
      ctx.beginPath(); ctx.arc(e.x, e.y, len * 0.013, 0, M.TAU); ctx.fill();
      ctx.fillStyle = 'rgba(255, 250, 220, 0.55)';
      ctx.beginPath(); ctx.arc(e.x - len * 0.004, e.y - len * 0.004, len * 0.0045, 0, M.TAU); ctx.fill();
    }
  }
  drawShadow(ctx, painter, channel) {
    const h = this.height(channel), dx = BROOK_SHADOW.x * h, dy = BROOK_SHADOW.y * h;
    const n = this.spine.length - 1;
    for (let i = 0; i <= n; i++) this.inner[i] = TROUT_PROFILE[i] * this.len * 1.1;
    painter.outline(ctx, this.spine, this.inner, this.len * 0.03, dx, dy);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
    ctx.fill();
    this.tailPath(ctx, 1, dx, dy);
    ctx.fill();
  }
}

/* Colchic minnow: small, olive above, a row of dark blotches along each side. */
class MinnowShape {
  static profile() {
  const n = 6, w = new Float32Array(n + 1);
  for (let i = 0; i <= n; i++) { const u = i / n; w[i] = 0.1 * (u < 0.25 ? 0.65 + 0.35 * u / 0.25 : 1 - 0.75 * Math.pow((u - 0.25) / 0.75, 1.1)); }
  return w;
  }
}
const MINNOW_PROFILE = MinnowShape.profile();

class Minnow extends Swimmer {
  constructor(x, y, len, rng) {
    super(x, y, len, 6, rng);
    this.tone = rng.range(-12, 12);
    this.dart = 0;
    this.escape = null;
  }
  draw(ctx, painter) {
    const len = this.len, n = this.spine.length - 1, t = this.tone;
    for (let i = 0; i <= n; i++) this.widths[i] = MINNOW_PROFILE[i] * len;
    this.tailPath(ctx, 1.1);
    ctx.fillStyle = 'rgba(80, 76, 50, 0.7)';
    ctx.fill();
    painter.outline(ctx, this.spine, this.widths, len * 0.035);
    ctx.fillStyle = `rgb(${150 + t}, ${142 + t}, ${98 + t})`;
    ctx.fill();
    for (let i = 0; i <= n; i++) this.inner[i] = this.widths[i] * 0.55;
    painter.outline(ctx, this.spine, this.inner, len * 0.02);
    ctx.fillStyle = 'rgba(60, 58, 36, 0.75)';
    ctx.fill();
    ctx.fillStyle = 'rgba(36, 32, 22, 0.6)';
    for (let k = 0; k < 6; k++) {
      const u = 0.3 + k * 0.1;
      for (const side of [-1, 1]) {
        const p = this.bodyPoint(u, side * 0.7, MINNOW_PROFILE);
        ctx.beginPath(); ctx.arc(p.x, p.y, len * 0.022, 0, M.TAU); ctx.fill();
      }
    }
  }
  drawShadow(ctx, painter, channel) {
    const h = channel.waterDepthPx(this.depth) * 0.5, dx = BROOK_SHADOW.x * h, dy = BROOK_SHADOW.y * h;
    const n = this.spine.length - 1;
    for (let i = 0; i <= n; i++) this.inner[i] = MINNOW_PROFILE[i] * this.len * 1.15;
    painter.outline(ctx, this.spine, this.inner, this.len * 0.035, dx, dy);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
    ctx.fill();
  }
}

/** A shoal of minnows: they keep together, keep to the shallows and scatter from trout and hands. */
export class MinnowShoal {
  constructor(life, home, count, len, rng) {
    this.rng = rng;
    this.home = { x: home.x, y: home.y };
    this.homeTimer = rng.range(8, 16);
    this.fish = [];
    for (let i = 0; i < count; i++) {
      const m = new Minnow(home.x + rng.gauss() * len * 2, home.y + rng.gauss() * len * 2, len * rng.range(0.85, 1.15), rng);
      this.fish.push(m);
    }
  }
  update(dt, life) {
    const ch = life.channel;
    this.homeTimer -= dt;
    if (this.homeTimer <= 0) {
      const next = life.shallowSpot();
      if (next) this.home = next;
      this.homeTimer = this.rng.range(9, 20);
    }
    const fish = this.fish;
    for (const m of fish) {
      const L = m.len;
      let sx = 0, sy = 0, ax = 0, ay = 0, cx = 0, cy = 0, n = 0;
      for (const o of fish) {
        if (o === m) continue;
        const dx = o.x - m.x, dy = o.y - m.y, d = Math.hypot(dx, dy);
        if (d > L * 5) continue;
        n++;
        cx += o.x; cy += o.y; ax += o.vx; ay += o.vy;
        if (d < L * 1.3 && d > 0) { sx -= dx / d * (L * 1.3 - d); sy -= dy / d * (L * 1.3 - d); }
      }
      const want = m.seek(this.home.x, this.home.y, L * 1.6, L * 6);
      if (n) {
        want.x += (cx / n - m.x) * 0.5 + (ax / n) * 0.35 + sx * 3;
        want.y += (cy / n - m.y) * 0.5 + (ay / n) * 0.35 + sy * 3;
      }
      const wob = life.noise.n2(m.phase * 0.02 + m.tone, life.time * 0.3) * L * 2;
      want.x += Math.cos(m.heading + 1.57) * wob; want.y += Math.sin(m.heading + 1.57) * wob;
      for (const t of life.trout) {
        const d = Math.hypot(m.x - t.x, m.y - t.y);
        if (d < t.len * 1.4 && d > 0) { m.escape = ch.away(m.x, m.y, t.x, t.y, L * 0.3); m.dart = Math.max(m.dart, 0.4); }
      }
      if (m.dart > 0 && m.escape) { want.x += m.escape.x * L * 10; want.y += m.escape.y * L * 10; }
      const depth = ch.sample(m.x, m.y).depth;
      if (depth > 0.55) { const g = ch.deeper(m.x, m.y); want.x -= g.x * L * 2.5; want.y -= g.y * L * 2.5; }
      m.dart = Math.max(0, m.dart - dt);
      const cap = (m.dart > 0 ? 6 : 2.8) * L;
      m.swim(dt, ch, want, cap, m.dart > 0 ? 6 : 3.2, m.dart > 0 ? 7 : 3, 0.08);
    }
  }
  spook(x, y, radius, channel) {
    for (const m of this.fish) {
      const d = Math.hypot(m.x - x, m.y - y);
      if (d < radius && d > 0) { m.dart = 0.6; m.escape = channel.away(m.x, m.y, x, y, m.len * 0.3); }
    }
  }
}
