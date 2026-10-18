/*
 * river-life.js: everything alive on and over the brook except the fish: insects on the surface
 * film, autumn leaves afloat and falling, ferns leaning over the water, foam and spray.
 * BrookLife places them, moves them and answers the pointer.
 */
import { BranchArt, FernArt, LeafArt, TopFishPainter } from "./river-art.js";
import { M, Rng } from "./river-core.js";
import { MinnowShoal, Trout } from "./river-fish.js";
import { BROOK, BROOK_SHADOW } from "./river-world.js";

/** An insect on the surface film: it struggles, sends out rings and drifts until a fish takes it. */
class Fly {
  constructor(x, y, size, rng) {
    this.x = x; this.y = y; this.vx = 0; this.vy = 0;
    this.size = size;
    this.alive = true;
    this.claimedBy = null;
    this.angle = rng.range(0, M.TAU);
    this.kick = rng.range(0.2, 0.7);
    this.wing = 0.3;
  }
  update(dt, life) {
    const ch = life.channel, w = ch.sample(this.x, this.y);
    this.vx = M.approach(this.vx, w.vx, 2, dt); this.vy = M.approach(this.vy, w.vy, 2, dt);
    this.x += this.vx * dt; this.y += this.vy * dt;
    for (const r of ch.rocks) r.pushOut(this, this.size * 0.5);
    this.kick -= dt;
    if (this.kick <= 0) {
      life.ripples.disturb(this.x, this.y, 0.16, this.size * 0.7);
      this.kick = life.rng.range(0.4, 1.4);
      this.wing = 0.35;
      this.angle += life.rng.range(-0.9, 0.9);
    }
    this.wing = Math.max(0, this.wing - dt);
    const m = 40;
    if (w.depth < 0.02 || this.x < -m || this.y < -m || this.x > ch.w + m || this.y > ch.h + m) this.alive = false;
  }
  draw(ctx, t) {
    const s = this.size, flick = this.wing > 0 ? Math.sin(t * 80) * 0.45 : 0;
    ctx.save();
    ctx.translate(this.x, this.y);
    ctx.rotate(this.angle);
    ctx.fillStyle = 'rgba(214, 208, 190, 0.55)';
    for (const side of [-1, 1]) {
      ctx.beginPath();
      ctx.ellipse(-s * 0.15, side * s * 0.2, s * 0.62, s * 0.2, side * (0.32 + flick), 0, M.TAU);
      ctx.fill();
    }
    ctx.fillStyle = '#4a3820';
    ctx.beginPath(); ctx.ellipse(0, 0, s * 0.5, s * 0.14, 0, 0, M.TAU); ctx.fill();
    ctx.beginPath(); ctx.arc(s * 0.5, 0, s * 0.11, 0, M.TAU); ctx.fill();
    ctx.strokeStyle = 'rgba(60, 46, 26, 0.8)';
    ctx.lineWidth = 0.6;
    ctx.beginPath(); ctx.moveTo(s * 0.55, 0); ctx.lineTo(s * 1.0, -s * 0.22); ctx.moveTo(s * 0.55, 0); ctx.lineTo(s * 1.0, s * 0.22); ctx.stroke();
    ctx.restore();
  }
  drawShadow(ctx, depthPx) {
    ctx.fillStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.beginPath(); ctx.arc(this.x + BROOK_SHADOW.x * depthPx, this.y + BROOK_SHADOW.y * depthPx, this.size * 0.6, 0, M.TAU); ctx.fill();
  }
}

/*
 * Water strider legs in body lengths, body along +x: shoulder, knee, tip. The middle pair rows;
 * `reach` moves its tips forward at the start of a stroke.
 */
const STRIDER_LEGS = Object.freeze([
  { hip: [0.3, 0.05], knee: [0.55, 0.18], tip: [0.75, 0.22], reach: 0, dimple: 0.6 },
  { hip: [0.1, 0.05], knee: [0.15, 0.9], tip: [-0.35, 1.55], reach: 0.6, dimple: 1 },
  { hip: [0.0, 0.05], knee: [-0.3, 0.45], tip: [-1.3, 0.75], reach: 0, dimple: 1 },
]);

export class Strider {
  /** How far inside the water's edge a strider stays, in body lengths: its legs reach about one and a half. */
  static BANK_ROOM = 1.8;
  constructor(x, y, size, rng) {
    this.x = x; this.y = y; this.size = size;
    this.heading = rng.range(0, M.TAU);
    this.push = { x: 0, y: 0 };
    this.timer = rng.range(0.3, 2);
    this.stroke = 0;
    this.depth = 0.2;
  }
  update(dt, life) {
    const ch = life.channel, w = ch.sample(this.x, this.y);
    this.depth = w.depth;
    this.push.x = M.approach(this.push.x, 0, 2.4, dt);
    this.push.y = M.approach(this.push.y, 0, 2.4, dt);
    this.x += (this.push.x + w.vx * 0.85) * dt;
    this.y += (this.push.y + w.vy * 0.85) * dt;
    this.timer -= dt;
    if (this.timer <= 0) this.row(life, w);
    this.stroke = Math.max(0, this.stroke - dt * 3.2);
    for (const r of ch.rocks) {
      const n = r.pushOut(this, this.size * 1.3);
      if (n) { const vn = this.push.x * n.x + this.push.y * n.y; if (vn < 0) { this.push.x -= 1.6 * vn * n.x; this.push.y -= 1.6 * vn * n.y; } }
    }
    if (w.depth < 0.05) {
      const g = ch.deeper(this.x, this.y);
      this.x += g.x * 1.5; this.y += g.y * 1.5;
      this.push.x += g.x * 20 * dt * 60 * 0.05; this.push.y += g.y * 20 * dt * 60 * 0.05;
    }
    // the bank is drawn over the water's edge: a strider whose legs reach it is put back, and what carried it there is lost
    const dn = ch.inward(this.x, this.y, this.size * Strider.BANK_ROOM);
    if (dn) {
      const to = ch.across(dn), into = ch.across(Math.sign(dn));
      this.x += to.x; this.y += to.y;
      const v = this.push.x * into.x + this.push.y * into.y;
      if (v < 0) { this.push.x -= v * into.x; this.push.y -= v * into.y; }
    }
    const m = this.size * 3;
    if (this.x < -m || this.y < -m || this.x > ch.w + m || this.y > ch.h + m) {
      const spot = life.calmSpot(true);
      if (spot) { this.x = spot.x; this.y = spot.y; this.push.x = this.push.y = 0; }
    }
    const p = life.pointerNear(this.x, this.y, this.size * 6);
    if (p && this.stroke < 0.2) this.flee(life, p);
  }
  row(life, w) {
    const rng = life.rng, drift = Math.hypot(w.vx, w.vy);
    const dir = drift > 22 ? Math.atan2(-w.vy, -w.vx) + rng.range(-1, 1) : this.heading + rng.range(-1.7, 1.7);
    this.kickToward(life, dir, rng.range(5, 12) * this.size);
    this.timer = rng.range(0.5, 2.4);
  }
  /** Dart from the pointer along the stream — the banks shut the other ways. */
  flee(life, p) {
    const away = life.channel.away(this.x, this.y, p.x, p.y, this.size * 2);
    this.kickToward(life, Math.atan2(away.y, away.x), 16 * this.size);
    this.timer = life.rng.range(0.6, 1.4);
  }
  kickToward(life, dir, speed) {
    this.heading = dir;
    this.push.x += Math.cos(dir) * speed; this.push.y += Math.sin(dir) * speed;
    this.stroke = 1;
    const nx = -Math.sin(dir) * this.size * 1.3, ny = Math.cos(dir) * this.size * 1.3;
    life.ripples.disturb(this.x + nx, this.y + ny, 0.08, this.size * 0.3);
    life.ripples.disturb(this.x - nx, this.y - ny, 0.08, this.size * 0.3);
  }
  /** Calls fn(tipX, tipY, dimpleWeight, hipX, hipY, kneeX, kneeY) for each of the six legs. */
  eachLeg(fn) {
    const B = this.size, c = Math.cos(this.heading), s = Math.sin(this.heading);
    const at = (lx, ly) => [this.x + (lx * c - ly * s) * B, this.y + (lx * s + ly * c) * B];
    for (const leg of STRIDER_LEGS) {
      for (const side of [-1, 1]) {
        const tipX = leg.tip[0] + leg.reach * this.stroke;
        const [hx, hy] = at(leg.hip[0], leg.hip[1] * side), [kx, ky] = at(leg.knee[0], leg.knee[1] * side), [tx, ty] = at(tipX, leg.tip[1] * side);
        fn(tx, ty, leg.dimple, hx, hy, kx, ky);
      }
    }
  }
  draw(ctx) {
    const B = this.size;
    ctx.strokeStyle = 'rgba(38, 30, 22, 0.9)';
    ctx.lineWidth = Math.max(0.6, B * 0.06);
    ctx.lineCap = 'round';
    ctx.beginPath();
    this.eachLeg((tx, ty, dimple, hx, hy, kx, ky) => { ctx.moveTo(hx, hy); ctx.lineTo(kx, ky); ctx.lineTo(tx, ty); });
    ctx.stroke();
    ctx.fillStyle = 'rgba(255, 255, 245, 0.55)';
    this.eachLeg((tx, ty, dimple) => { ctx.beginPath(); ctx.arc(tx, ty, B * 0.09 * dimple + 0.3, 0, M.TAU); ctx.fill(); });
    ctx.save();
    ctx.translate(this.x, this.y);
    ctx.rotate(this.heading);
    ctx.fillStyle = '#2e2419';
    ctx.beginPath(); ctx.ellipse(-0.05 * B, 0, 0.55 * B, 0.1 * B, 0, 0, M.TAU); ctx.fill();
    ctx.fillStyle = 'rgba(150, 130, 100, 0.5)';
    ctx.beginPath(); ctx.ellipse(-0.1 * B, 0, 0.35 * B, 0.03 * B, 0, 0, M.TAU); ctx.fill();
    ctx.restore();
  }
  /** The six dimples act as lenses: round shadows on the bed, each with a bright rim. */
  drawShadow(ctx, depthPx) {
    const dx = BROOK_SHADOW.x * depthPx, dy = BROOK_SHADOW.y * depthPx, B = this.size;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
    this.eachLeg((tx, ty, dimple) => { ctx.beginPath(); ctx.arc(tx + dx, ty + dy, B * 0.26 * dimple, 0, M.TAU); ctx.fill(); });
  }
  drawRims(ctx, depthPx) {
    const dx = BROOK_SHADOW.x * depthPx, dy = BROOK_SHADOW.y * depthPx, B = this.size;
    ctx.strokeStyle = 'rgba(255, 250, 225, 0.32)';
    ctx.lineWidth = Math.max(0.8, B * 0.08);
    this.eachLeg((tx, ty, dimple) => { ctx.beginPath(); ctx.arc(tx + dx, ty + dy, B * 0.33 * dimple, 0, M.TAU); ctx.stroke(); });
  }
}

/** A leaf afloat: carried by the current, caught on rocks for a moment, turning slowly. */
class FloatingLeaf {
  constructor(sprite, x, y, angle, rng) {
    this.sprite = sprite;
    this.x = x; this.y = y; this.angle = angle;
    this.vx = 0; this.vy = 0;
    this.spin = rng.range(-0.25, 0.25);
    this.alive = true;
  }
  update(dt, life) {
    const ch = life.channel, w = ch.sample(this.x, this.y);
    this.depth = w.depth;
    this.vx = M.approach(this.vx, w.vx, 1.3, dt); this.vy = M.approach(this.vy, w.vy, 1.3, dt);
    this.x += this.vx * dt; this.y += this.vy * dt;
    this.spin = M.approach(this.spin, 0, 0.25, dt) + (w.turb - 0.15) * life.rng.range(-0.6, 0.6) * dt;
    this.angle += this.spin * dt;
    for (const r of ch.rocks) {
      const n = r.pushOut(this, this.sprite.w * 0.22);
      if (n) {
        const vn = this.vx * n.x + this.vy * n.y;
        if (vn < 0) { this.vx -= 1.2 * vn * n.x; this.vy -= 1.2 * vn * n.y; }
        this.spin += (n.x * this.vy - n.y * this.vx) * 0.004;
      }
    }
    if (w.depth < 0.035) {
      const g = ch.deeper(this.x, this.y);
      this.x += g.x * 1.2; this.y += g.y * 1.2;
      this.vx *= 0.96; this.vy *= 0.96;
    }
    const p = life.pointerNear(this.x, this.y, this.sprite.w * 0.8);
    if (p) { this.vx += p.vx * 0.02; this.vy += p.vy * 0.02; this.spin += (Math.random() - 0.5) * 0.4; }
    const m = this.sprite.w;
    if (this.x < -m * 2 || this.y < -m * 2 || this.x > ch.w + m || this.y > ch.h + m) this.alive = false;
  }
  draw(ctx, life) {
    this.sprite.draw(ctx, this.x, this.y, this.angle);
    const dark = M.clamp((1 - life.canopy.lightAt(this.x, this.y)) * 0.8, 0, 0.45);
    if (dark > 0.02) this.sprite.draw(ctx, this.x, this.y, this.angle, 1, dark, true);
  }
  drawShadow(ctx, life) {
    const h = life.channel.waterDepthPx(this.depth || 0.3);
    this.sprite.draw(ctx, this.x + BROOK_SHADOW.x * h, this.y + BROOK_SHADOW.y * h, this.angle, 1.05, 0.5, true);
  }
}

/** A leaf coming down from the canopy: large and soft while it is near the eye, then it lands. */
class FallingLeaf {
  constructor(sprite, x, y, C, rng) {
    this.sprite = sprite;
    this.tx = x; this.ty = y;
    this.C = C;
    this.t = 0;
    this.dur = rng.range(5.5, 8.5);
    this.angle = rng.range(0, M.TAU);
    this.spin = rng.range(-1.1, 1.1);
    this.sway = rng.range(0.7, 1.2);
    this.phase = rng.range(0, M.TAU);
    this.from = { x: rng.range(-1, 1) * C * 0.12, y: rng.range(-1, 1) * C * 0.12 };
    this.landed = false;
    this.place();
  }
  get z() { return M.clamp(1 - this.t / this.dur, 0, 1); }
  place() {
    const z = this.z, swing = Math.sin(this.t * this.sway * 2.1 + this.phase) * this.C * 0.035 * z;
    this.x = this.tx + this.from.x * z + swing;
    this.y = this.ty + this.from.y * z + swing * 0.4;
  }
  update(dt) {
    this.t += dt;
    this.angle += this.spin * dt;
    this.place();
    if (this.t >= this.dur) this.landed = true;
  }
  draw(ctx) {
    const z = this.z, flip = Math.cos(this.t * 2.4 + this.phase);
    ctx.save();
    if (z > 0.15) ctx.filter = `blur(${(z * 3.5).toFixed(1)}px)`;
    ctx.translate(this.x, this.y);
    ctx.rotate(this.angle);
    ctx.scale(1 + z * 1.8, (1 + z * 1.8) * Math.max(0.18, Math.abs(flip)));
    this.sprite.draw(ctx, 0, 0, 0, 1, 1);
    ctx.restore();
  }
  drawShadow(ctx, life) {
    const z = this.z, h = z * this.C * 0.45 + life.channel.waterDepthPx(0.4);
    this.sprite.draw(ctx, this.x + BROOK_SHADOW.x * h, this.y + BROOK_SHADOW.y * h, this.angle, 1 + z * 0.6, 0.45 * (1 - z * 0.7), true);
  }
}

/** A fern clump on the bank: three to five fronds leaning out over the water, moving in the air. */
class FernClump {
  constructor(x, y, dir, art, rng) {
    this.x = x; this.y = y;
    this.fronds = [];
    const n = rng.int(3, 5);
    for (let i = 0; i < n; i++) {
      this.fronds.push({ sprite: rng.pick(art.fronds), angle: dir + rng.range(-0.8, 0.8), scale: rng.range(0.8, 1.1), phase: rng.range(0, M.TAU) });
    }
    this.fronds.sort((a, b) => a.scale - b.scale);
  }
  sway(f, t) { return 0.03 * Math.sin(t * 0.7 + f.phase) + 0.015 * Math.sin(t * 1.9 + f.phase * 2); }
  draw(ctx, t, life) {
    const dark = M.clamp((1 - life.canopy.lightAt(this.x, this.y)) * 0.7, 0, 0.4);
    for (const f of this.fronds) {
      const a = f.angle + this.sway(f, t);
      f.sprite.draw(ctx, this.x, this.y, a, f.scale);
      if (dark > 0.02) f.sprite.draw(ctx, this.x, this.y, a, f.scale, dark, true);
    }
  }
  drawShadow(ctx, t, h) {
    for (const f of this.fronds) f.sprite.draw(ctx, this.x + BROOK_SHADOW.x * h, this.y + BROOK_SHADOW.y * h, f.angle + this.sway(f, t), f.scale, 0.55, true);
  }
}

/** Rings still to come: a plop of a hand sends one at once and a smaller one a moment later. */
export class Echoes {
  constructor() { this.waiting = []; }
  add(at, x, y) { this.waiting.push({ at, x, y }); }
  /** The rings due by `time`, in the order they were added; they are taken off the list. */
  due(time) {
    const now = this.waiting.filter((e) => e.at <= time);
    this.waiting = this.waiting.filter((e) => e.at > time);
    return now;
  }
}

/** Foam specks shed by the rocks. (Drops of spray went: a hand's plop in 1.3.536, a trout's rise in 1.3.546 — the owner took them out.) */
class Specks {
  constructor() { this.foam = []; }
  addFoam(x, y, r) { if (this.foam.length < 160) this.foam.push({ x, y, r, life: 1, fade: 0.18 + Math.random() * 0.25 }); }
  update(dt, life) {
    const ch = life.channel;
    for (const f of this.foam) {
      const w = ch.sample(f.x, f.y);
      f.x += w.vx * dt; f.y += w.vy * dt;
      f.life -= f.fade * dt;
      for (const r of ch.rocks) r.pushOut(f, 1);
    }
    this.foam = this.foam.filter(f => f.life > 0);
  }
  draw(ctx) {
    for (const f of this.foam) {
      ctx.fillStyle = `rgba(240, 246, 242, ${(0.55 * f.life).toFixed(3)})`;
      ctx.beginPath(); ctx.arc(f.x, f.y, f.r, 0, M.TAU); ctx.fill();
    }
  }
}

/** Places and runs everything alive in the brook. The fish ask it about flies, lies and shelter. */
export class BrookLife {
  constructor(scene, world, dpr) {
    this.scene = scene;
    this.channel = world.channel; this.ripples = world.ripples; this.canopy = world.canopy;
    this.noise = scene.noise; this.rng = scene.rng;
    this.C = this.channel.C;
    this.time = 0;
    this.painter = new TopFishPainter(16);
    this.pointerState = scene.stage.pointer;
    this.paint(dpr);
    this.flies = []; this.leaves = []; this.falling = []; this.specks = new Specks();
    this.echoes = new Echoes();
    this.populate(new Rng(BROOK.layoutSeed + 9));
    this.leafTimer = 7;
    this.riseTimer = 12;
    this.foamTimer = 0;
  }
  paint(dpr) {
    this.dpr = dpr;
    const art = new Rng(BROOK.layoutSeed + 3);
    this.leafArt = new LeafArt(this.C, dpr, art);
    this.fernArt = new FernArt(this.C, dpr, art);
    this.branchArt = new BranchArt(this.C, dpr, art);
  }
  rescale(dpr) { if (dpr !== this.dpr) { this.paint(dpr); this.populate(new Rng(BROOK.layoutSeed + 9)); } }
  populate(rng) {
    const ch = this.channel, C = this.C;
    const inView = p => p.x > C * 0.04 && p.y > C * 0.04 && p.x < ch.w - C * 0.04 && p.y < ch.h - C * 0.04;
    this.lies = [];
    for (const r of ch.rocks) {
      if (!r.emerges) continue;
      const p = { x: r.x + ch.axis.x * r.r * 2.5, y: r.y + ch.axis.y * r.r * 2.5 };
      if (inView(p) && ch.sample(p.x, p.y).depth > 0.35 && !ch.rockAt(p.x, p.y, r.r * 0.4)) this.lies.push(p);
    }
    for (let i = 0; i < 300 && this.lies.length < 6; i++) {
      const p = { x: rng.range(0, ch.w), y: rng.range(0, ch.h) };
      if (inView(p) && ch.sample(p.x, p.y).depth > 0.6 && !ch.rockAt(p.x, p.y, C * 0.06) && this.lies.every(l => Math.hypot(l.x - p.x, l.y - p.y) > C * 0.2)) this.lies.push(p);
    }
    const troutCount = Math.min(this.lies.length, ch.A / C > 1.5 ? 4 : 3);
    this.trout = this.lies.slice(0, troutCount).map(lie => {
      const f = new Trout(rng, lie, C * rng.range(0.1, 0.15));
      f.heading = f.goal = Math.atan2(-ch.axis.y, -ch.axis.x);
      f.buildSpine();
      return f;
    });
    const home = this.shallowSpot(rng) || { x: ch.w * 0.5, y: ch.h * 0.5 };
    this.shoal = new MinnowShoal(this, home, ch.A / C > 1.5 ? 14 : 10, C * 0.04, rng);
    this.striders = [];
    for (let i = 0; i < 6; i++) {
      const p = this.calmSpot(false, rng);
      if (p) this.striders.push(new Strider(p.x, p.y, C * 0.016, rng));
    }
    this.leaves = [];
    for (let i = 0; i < 7; i++) {
      const p = this.waterSpot(rng, 0.05);
      if (p) this.leaves.push(new FloatingLeaf(this.leafArt.pick(rng), p.x, p.y, rng.range(0, M.TAU), rng));
    }
    this.ferns = [];
    for (const side of [-1, 1]) {
      const count = Math.max(2, Math.round(ch.A / C * 1.6));
      for (let i = 0; i < count; i++) {
        const s = ch.A * (i + rng.range(0.2, 0.8)) / count;
        const n = ch.centre(s) + side * (ch.halfWidth(s) + C * rng.range(0.05, 0.1));
        const p = ch.xy(s, n), dir = ch.xy(0, -side);
        this.ferns.push(new FernClump(p.x, p.y, Math.atan2(dir.y, dir.x), this.fernArt, rng));
      }
    }
    this.branch = { x: -C * 0.06, y: -C * 0.05, angle: 0.18, phase: rng.range(0, M.TAU) };
  }
  /* -------- places the animals ask for -------- */
  waterSpot(rng, minDepth, maxDepth = 1, test = null) {
    const ch = this.channel;
    for (let i = 0; i < 200; i++) {
      const p = { x: rng.range(0, ch.w), y: rng.range(0, ch.h) };
      const d = ch.sample(p.x, p.y).depth;
      if (d >= minDepth && d <= maxDepth && !ch.rockAt(p.x, p.y, this.C * 0.02) && (!test || test(p))) return p;
    }
    return null;
  }
  shallowSpot(rng = this.rng) { return this.waterSpot(rng, 0.15, 0.42); }
  /** Calm water near the banks; `upstream` places it at the upstream edge of the view. */
  calmSpot(upstream, rng = this.rng) {
    const ch = this.channel;
    const test = p => {
      const w = ch.sample(p.x, p.y);
      if (Math.hypot(w.vx, w.vy) > ch.vmax * 0.55) return false;
      return !upstream || ch.sOf(p.x, p.y) < ch.A * 0.3;
    };
    return this.waterSpot(rng, 0.06, 0.4, test);
  }
  flyFor(f) {
    let best = null, bestD = f.len * 7;
    for (const fly of this.flies) {
      if (!fly.alive || fly.claimedBy) continue;
      const dx = fly.x - f.x, dy = fly.y - f.y, d = Math.hypot(dx, dy);
      if (d > bestD) continue;
      if ((dx * Math.cos(f.heading) + dy * Math.sin(f.heading)) / (d || 1) < -0.35) continue;
      best = fly; bestD = d;
    }
    return best;
  }
  /** A trout takes a fly: a ring where its mouth closed on it and the sound of a small drop — no spray (the owner, 2026-10-14). */
  rise(f, fly) {
    fly.alive = false;
    this.ripples.disturb(fly.x, fly.y, 1.7, this.C * 0.012);
    this.scene.sound((kit, t) => kit.plink(t, { f: 640, ring: 0.26, gain: 0.09 }));
  }
  freeLie(f) {
    const free = this.lies.filter(l => l !== f.lie && this.trout.every(o => o === f || Math.hypot(o.lie.x - l.x, o.lie.y - l.y) > f.len));
    return free.length ? this.rng.pick(free) : null;
  }
  shelterNear(f) {
    const ch = this.channel;
    let best = null, bestD = Infinity;
    for (const r of ch.rocks) {
      if (!r.emerges) continue;
      const p = { x: r.x + ch.axis.x * r.r * 1.8, y: r.y + ch.axis.y * r.r * 1.8 };
      const d = Math.hypot(p.x - f.x, p.y - f.y);
      if (d < bestD && ch.sample(p.x, p.y).depth > 0.3) { best = p; bestD = d; }
    }
    return best || { x: f.lie.x, y: f.lie.y };
  }
  /** The pointer, when it is over the stage within `radius` of (x, y) and moving faster than `minSpeed`. */
  pointerNear(x, y, radius, minSpeed = 260) {
    const p = this.pointerState;
    if (!p.inside || p.speed < minSpeed) return null;
    return Math.hypot(p.x - x, p.y - y) < radius ? p : null;
  }
  /* -------- time -------- */
  update(dt, t) {
    this.time = t;
    const ch = this.channel, rng = this.rng, C = this.C;
    const p = this.pointerState;
    if (p.inside && p.speed > 30 && ch.isWater(p.x, p.y, 0.02) && (p.kind === 'mouse' || p.down)) {
      this.ripples.disturb(p.x, p.y, Math.min(0.55, p.speed / 1500), C * 0.007);
      if (p.speed > 700) {
        for (const f of this.trout) if (Math.hypot(f.x - p.x, f.y - p.y) < f.len * 2.2) f.spook(p.x, p.y, ch);
        this.shoal.spook(p.x, p.y, C * 0.12, ch);
      }
    }
    for (const f of this.flies) f.update(dt, this);
    this.flies = this.flies.filter(f => f.alive);
    for (const f of this.trout) f.update(dt, this);
    this.shoal.update(dt, this);
    for (const s of this.striders) s.update(dt, this);
    for (const l of this.leaves) l.update(dt, this);
    this.leaves = this.leaves.filter(l => l.alive);
    for (const l of this.falling) l.update(dt);
    for (const l of this.falling.filter(l => l.landed)) this.land(l);
    this.falling = this.falling.filter(l => !l.landed);
    this.specks.update(dt, this);
    for (const e of this.echoes.due(this.time)) this.ripples.disturb(e.x, e.y, 1.1, C * 0.011);
    this.leafTimer -= dt;
    if (this.leafTimer <= 0) {
      this.leafTimer = rng.range(9, 18);
      if (this.leaves.length < 7 && rng.chance(0.5)) this.driftIn(rng);
      else { const s = this.waterSpot(rng, 0.1); if (s) this.falling.push(new FallingLeaf(this.leafArt.pick(rng), s.x, s.y, C, rng)); }
    }
    this.riseTimer -= dt;
    if (this.riseTimer <= 0) { this.riseTimer = rng.range(22, 45); this.naturalFly(rng); }
    this.foamTimer -= dt;
    if (this.foamTimer <= 0) {
      this.foamTimer = 0.12;
      for (const r of ch.rocks) {
        if (!r.emerges || !rng.chance(0.5)) continue;
        const side = rng.sign(), perp = { x: -ch.axis.y, y: ch.axis.x };
        this.specks.addFoam(r.x + perp.x * side * r.r * 1.02 + ch.axis.x * r.r * 0.4, r.y + perp.y * side * r.r * 1.02 + ch.axis.y * r.r * 0.4, rng.range(0.6, 1.6));
      }
    }
  }
  land(l) {
    this.ripples.disturb(l.x, l.y, 0.5, this.C * 0.01);
    if (this.channel.isWater(l.x, l.y)) this.leaves.push(new FloatingLeaf(l.sprite, l.x, l.y, l.angle, this.rng));
  }
  driftIn(rng) {
    const ch = this.channel;
    const s = -this.C * 0.05, n = ch.centre(0) + ch.halfWidth(0) * rng.range(-0.8, 0.8);
    const p = ch.xy(s, n);
    this.leaves.push(new FloatingLeaf(this.leafArt.pick(rng), p.x, p.y, rng.range(0, M.TAU), rng));
  }
  naturalFly(rng) {
    const holding = this.trout.filter(f => f.state === 'hold');
    if (!holding.length) return;
    const f = rng.pick(holding), ch = this.channel;
    const x = f.x - ch.axis.x * f.len * 3.5 + rng.range(-1, 1) * f.len * 0.4, y = f.y - ch.axis.y * f.len * 3.5 + rng.range(-1, 1) * f.len * 0.4;
    if (ch.isWater(x, y, 0.1)) this.flies.push(new Fly(x, y, this.C * 0.012, rng));
  }
  /* -------- drawing -------- */
  drawUnder(u, s) {
    const ch = this.channel, painter = this.painter;
    for (const m of this.shoal.fish) { m.drawShadow(s, painter, ch); }
    for (const f of this.trout) f.drawShadow(s, painter, ch);
    for (const m of this.shoal.fish) m.draw(u, painter);
    for (const f of this.trout) f.draw(u, painter);
    for (const st of this.striders) { const h = ch.waterDepthPx(st.depth); st.drawShadow(s, h); st.drawRims(u, h); }
    for (const l of this.leaves) l.drawShadow(s, this);
    for (const f of this.flies) f.drawShadow(s, ch.waterDepthPx(0.3));
    for (const f of this.ferns) f.drawShadow(s, this.time, this.C * 0.05 + ch.waterDepthPx(0.3));
    for (const l of this.falling) l.drawShadow(s, this);
    const b = this.branch, sway = Math.sin(this.time * 0.35 + b.phase) * 0.012, h = this.C * 0.7;
    this.branchArt.sprite.draw(s, b.x + BROOK_SHADOW.x * h, b.y + BROOK_SHADOW.y * h, b.angle + sway, 1.15, 0.45, true);
  }
  drawTop(ctx, t) {
    for (const l of this.leaves) l.draw(ctx, this);
    for (const f of this.flies) f.draw(ctx, t);
    for (const s of this.striders) s.draw(ctx);
    this.specks.draw(ctx);
    for (const f of this.ferns) f.draw(ctx, t, this);
    for (const l of this.falling) l.draw(ctx);
    const b = this.branch, sway = Math.sin(t * 0.35 + b.phase) * 0.012;
    this.branchArt.sprite.draw(ctx, b.x, b.y, b.angle + sway, 1, 0.96);
  }
  /* -------- the pointer -------- */
  pointer(kind, p) {
    const ch = this.channel, C = this.C;
    if (kind === 'down') {
      if (ch.isWater(p.x, p.y, 0.03)) {
        if (this.flies.length < 6) this.flies.push(new Fly(p.x, p.y, C * 0.012, this.rng));
        this.ripples.disturb(p.x, p.y, 0.35, C * 0.006);
        this.scene.sound((kit, t) => kit.plink(t, { f: 900, ring: 0.2, gain: 0.06 }));
      } else if (this.falling.length < 4) {
        const s = this.waterSpot(this.rng, 0.08, 1, q => Math.hypot(q.x - p.x, q.y - p.y) < C * 0.35);
        if (s) this.falling.push(new FallingLeaf(this.leafArt.pick(this.rng), s.x, s.y, C, this.rng));
      }
    }
    if (kind === 'double' && ch.isWater(p.x, p.y, 0.03)) {
      // A plop of a hand: one big ring and, a moment later, a smaller one as the water closes over it, and the sound of a big
      // drop. It threw drops into the air before (1.3.536: they flew out over the bank in every direction, the owner took them out).
      this.ripples.disturb(p.x, p.y, 2.6, C * 0.018);
      this.echoes.add(this.time + 0.16, p.x, p.y);
      for (const f of this.trout) if (Math.hypot(f.x - p.x, f.y - p.y) < C * 0.4) f.spook(p.x, p.y, ch);
      this.shoal.spook(p.x, p.y, C * 0.3, ch);
      this.scene.sound((kit, t) => kit.plink(t, { f: 330, ring: 0.42, gain: 0.14, room: 0.3 }));
    }
  }
}
