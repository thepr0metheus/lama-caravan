/*
 * river-frogs.js: the frogs of the brook and the tadpoles of its shallows: where they live, what they do, and how they go into the brook's
 * layers (the owner, 2026-10-21, choosing among the mockups: "Д, all of them, a few of each", "the plop quiet", "tadpoles, yes"). Two marsh
 * frogs sit on stones that stand out of the water and one floats by a bank with only its eyes out; a brown frog sits on the bank at the
 * water's edge; two tree frogs sit on fern fronds and sway with them; two parsley frogs sit in the shallows, legs in the water; five tadpoles
 * wriggle in slow water by a bank. A frog sits most of the time, breathing and now and then blinking or turning a little. A fly in reach in
 * front of it is taken with a flick of the tongue, even one a trout is rising to (the trout lets a fly that is gone go back to nothing).
 * A hand that moves fast close by, or a hand's plop, sends it into the water: a jump, a ring, a quiet plop, kicks under the water, up again
 * with only its eyes out, and back to its own place; a tree frog jumps to another frond instead. How a frog looks is river-frog.js.
 */
import { SoftShape } from "./river-art.js";
import { M, Rng } from "./river-core.js";
import { FrogArt, FrogInk, FrogKinds, FrogLight, FrogPose, FrogSkin, FrogStill, TadpoleArt } from "./river-frog.js";
import { BROOK_SHADOW } from "./river-world.js";

/** One frog: its kind, its place (`home`), what it is doing and the phases its drawing reads. */
export class Frog {
  /** How long a blink lasts, seconds: a frog blinks seldom and slowly. */
  static BLINK = 0.24;

  constructor(kind, home, len, seed) {
    this.kind = kind; this.home = home; this.len = len; this.seed = seed;
    this.x = home.x; this.y = home.y; this.heading = home.heading;
    this.rng = new Rng(seed * 7 + 1);
    this.skin = null;
    this.state = home.kind === 'float' ? 'float' : 'sit';
    this.t = 0; this.dur = this.rng.range(8, 20);
    this.breath = this.rng.range(0, M.TAU); this.blink = 0; this.blinkIn = this.rng.range(3, 12);
    this.phase = 0; this.speed = 0; this.z = 0; this.jump = null; this.target = null; this.next = null;
    this.kicks = 0; this.kick = 0; this.paddle = 0;
    this.turnTo = null; this.tongue = 0; this.tongueTo = [0, 0]; this.look = 0;
    this.barShift = this.rng.range(-0.09, 0.09);
    this.still = new FrogStill();          // what of it is above the water while it rests
    this.stillUnder = new FrogStill();     // and what is under it: a floater's body, a wader's legs
  }

  skinCanvas() { return this.skin || (this.skin = FrogSkin.bake(this.kind, this.seed)); }
  breathe() { return this.state === 'sit' || this.state === 'float' ? 0.014 * Math.sin(this.breath) : 0; }
  blinkAmount() { return this.blink > 0 ? Math.sin(Math.PI * M.clamp(this.blink / Frog.BLINK, 0, 1)) : 0; }
  get sitPose() { return FrogPose[this.kind.sit]; }

  /** Where it lies among the brook's layers: above the water, under it, afloat (eyes above, the rest under) or wading (legs under). */
  get layer() {
    if (this.state === 'swim' || this.state === 'return') return 'under';
    if (this.state === 'float') return 'split';
    if (this.state === 'sit' && this.home.kind === 'shallow') return 'wade';
    return 'top';
  }

  pose() {
    switch (this.state) {
      case 'crouch': return FrogPose.blend(this.sitPose, FrogPose.CROUCH, FrogPose.ease(this.t / FrogPond.CROUCH));
      case 'jump': return FrogPose.jump(this.jump.s, this.jump.water, this.sitPose);
      case 'swim': case 'return': return FrogPose.stroke(this.phase);
      case 'float': return FrogPose.blend(FrogPose.FLOAT, FrogPose.stroke(this.phase), M.clamp(this.speed / this.len, 0, 1));
      default: return this.sitPose;
    }
  }
}

/** Tadpoles in slow water by a bank: they rest on the bed, wriggle to another spot near their place now and then, and scatter from a hand. */
export class TadpoleSchool {
  constructor(life, home, count, len, rng) {
    this.life = life; this.home = home; this.rng = rng; this.radius = life.channel.C * 0.06;
    this.tadpoles = [];
    for (let i = 0; i < count; i++) {
      const a = rng.range(0, M.TAU), d = rng.range(0, this.radius);
      this.tadpoles.push({ x: home.x + Math.cos(a) * d, y: home.y + Math.sin(a) * d, len: len * rng.range(0.85, 1.05), heading: rng.range(0, M.TAU),
        speed: 0, wave: rng.range(0, M.TAU), rest: rng.range(0.5, 4), target: null });
    }
  }

  /** A spot near the school's place, or (`away` given) one a few lengths away from a danger; null when no water there will do. */
  spot(tp, away = null) {
    const ch = this.life.channel;
    for (let k = 0; k < 12; k++) {
      const a = away ? Math.atan2(tp.y - away.y, tp.x - away.x) + this.rng.range(-0.6, 0.6) : this.rng.range(0, M.TAU);
      const d = away ? tp.len * this.rng.range(3, 5) : this.rng.range(0, this.radius);
      const from = away ? tp : this.home, p = { x: from.x + Math.cos(a) * d, y: from.y + Math.sin(a) * d }, w = ch.sample(p.x, p.y);
      if (w.depth > 0.1 && w.depth < 0.45 && !ch.rockAt(p.x, p.y, tp.len * 0.4)) return p;
    }
    return null;
  }

  update(dt) {
    const life = this.life, ch = life.channel;
    for (const tp of this.tadpoles) {
      const p = life.pointerNear(tp.x, tp.y, tp.len * 5, 300);
      if (p) { tp.target = this.spot(tp, p) || tp.target; tp.speed = tp.len * 5; tp.rest = this.rng.range(2, 4); }
      tp.rest -= dt;
      if (tp.rest <= 0 && !tp.target) { tp.target = this.spot(tp); tp.rest = this.rng.range(1.5, 6); }
      if (tp.target) {
        const dx = tp.target.x - tp.x, dy = tp.target.y - tp.y;
        tp.heading = M.turnToward(tp.heading, Math.atan2(dy, dx), 5 * dt);
        tp.speed = M.approach(tp.speed, tp.len * 2.2, 3, dt);
        if (Math.hypot(dx, dy) < tp.len * 0.5) tp.target = null;
      } else tp.speed = M.approach(tp.speed, 0, 2.5, dt);
      tp.wave += dt * M.TAU * (1.5 + 8 * M.clamp(tp.speed / (tp.len * 2.2), 0, 1.4));
      const w = ch.sample(tp.x, tp.y);
      tp.x += (Math.cos(tp.heading) * tp.speed + w.vx * 0.05) * dt; tp.y += (Math.sin(tp.heading) * tp.speed + w.vy * 0.05) * dt;
      for (const r of ch.rocks) r.pushOut(tp, tp.len * 0.3);
      if (w.depth < 0.05) { const g = ch.deeper(tp.x, tp.y); tp.x += g.x; tp.y += g.y; }
    }
  }

  /** On the bed: a shadow almost under each, and the tadpole itself in the layer under the surface. */
  drawUnder(u, s) {
    const ch = this.life.channel;
    for (const tp of this.tadpoles) {
      const h = ch.waterDepthPx(ch.sample(tp.x, tp.y).depth) * 0.12;
      s.save(); s.translate(tp.x + BROOK_SHADOW.x * h, tp.y + BROOK_SHADOW.y * h); s.rotate(tp.heading); s.scale(tp.len, tp.len);
      s.fillStyle = 'rgba(0,0,0,0.5)'; s.beginPath(); s.ellipse(0.2, 0, 0.22, 0.15, 0, 0, M.TAU); s.fill(); s.restore();
      u.save(); u.translate(tp.x, tp.y); u.rotate(tp.heading); u.scale(tp.len, tp.len);
      TadpoleArt.draw(u, tp.wave, tp.speed / (tp.len * 2));
      u.restore();
    }
  }
}

/** Places and runs the frogs and the tadpoles of a brook; BrookLife hands it the frame, the layers and the hand's plop. */
export class FrogPond {
  /** Who lives here, [kind, home, how many]: the variant Д of the mockups, a few of each (the owner, 2026-10-21). */
  static CAST = Object.freeze([['ridibundus', 'rock', 2], ['ridibundus', 'float', 1], ['macrocnemis', 'bank', 1], ['orientalis', 'fern', 2], ['caucasicus', 'shallow', 2]]);
  static TADPOLES = 5;
  /** A tadpole's length as a share of the short side: the parsley frog's are big, but none is longer than the longest frog. */
  static TADPOLE = 0.022;
  /** How long a frog gathers itself before it jumps, and one stroke under the water, seconds. */
  static CROUCH = 0.12;
  static STROKE = 0.9;
  /**
   * The sound of a frog going into the water: one drop, as every sound on the water is — lower and longer than a trout's take of a fly (640),
   * higher and shorter than a hand's plop (330), and quieter than a fly landing (0.06): the owner, 2026-10-21, "the plop quiet".
   */
  static PLOP = Object.freeze({ f: 560, ring: 0.28, gain: 0.04 });
  /** How far from its middle a frog's tongue takes a fly, in body lengths: half a length of head and about a length of tongue. */
  static REACH = 1.45;
  /** How much further than it meant a frog may jump to reach water: a stone can be three of its lengths across (a frog jumps ten). */
  static FAR = Object.freeze([1, 1.5, 2.1, 2.8, 3.4]);

  constructor(life, rng) {
    this.life = life;
    this.frogs = [];
    this.school = null;
    this.populate(rng);
  }

  get ch() { return this.life.channel; }
  inView(p, m = 0.05) { const C = this.ch.C; return p.x > C * m && p.y > C * m && p.x < this.ch.w - C * m && p.y < this.ch.h - C * m; }

  /** Puts the cast in their places; a kind with no place for it on this brook (a narrow screen has fewer stones) is left out. */
  populate(rng) {
    const used = new Set();
    for (const [id, home, count] of FrogPond.CAST) {
      const kind = FrogKinds.ALL[id];
      for (let i = 0; i < count; i++) {
        const len = FrogKinds.lengthOf(kind, this.ch.C, rng), spot = this.spot(home, len, rng, used);
        if (spot) this.frogs.push(new Frog(kind, spot, len, rng.int(1, 1e6)));
      }
    }
    const shallows = this.shallows(rng);
    if (shallows) this.school = new TadpoleSchool(this.life, shallows, FrogPond.TADPOLES, this.ch.C * FrogPond.TADPOLE, rng);
  }

  /**
   * Whether a fern frond or the alder branch hangs over p: a frog put there would stay hidden under them (a frog that swims under a frond
   * for a while comes out again). The mockup put a frog and the tadpoles out of sight that way, under a frond and under the branch.
   */
  covered(p) { return this.underFrond(p) || this.underBranch(p); }
  underFrond(p) {
    for (const clump of this.life.ferns) {
      for (const fr of clump.fronds) {
        const L = fr.sprite.w * fr.scale, dx = p.x - clump.x, dy = p.y - clump.y, c = Math.cos(fr.angle), sn = Math.sin(fr.angle);
        const along = dx * c + dy * sn, across = Math.abs(dy * c - dx * sn);
        if (along > 0 && along < L * 1.02 && across < L * 0.3) return true;
      }
    }
    return false;
  }
  /** The alder branch close to the eye, out of focus, in the top left corner (BrookLife.branch and BranchArt: 0.62 of the short side long). */
  underBranch(p) { const b = this.life.branch, C = this.ch.C; return p.x < b.x + C * 0.62 && p.y < b.y + C * 0.45; }

  /** The water's edge across the stream at s on a side (-1 or 1), as n: the bank's line wobbles, and the shore says where it runs. */
  edgeN(s, side) {
    const ch = this.ch, c = ch.centre(s), hw = ch.halfWidth(s);
    return c + side * (hw + ch.shore(s, c + side * hw));
  }

  /** A place to live for a frog `len` long: on a stone, afloat in slow water by a bank, on the bank, on a fern frond, in the shallows; or null. */
  spot(home, len, rng, used) {
    const ch = this.ch, C = ch.C, clear = (p, gap) => !this.frogs.some((f) => Math.hypot(f.x - p.x, f.y - p.y) < gap);
    if (home === 'rock') {
      const rocks = ch.rocks.filter((r) => r.emerges && !used.has(r) && this.inView(r) && r.r > len * 0.6 && !this.covered(r));
      if (!rocks.length) return null;
      const r = rng.pick(rocks), a = rng.range(0, M.TAU), d = r.r * rng.range(0.05, 0.3);
      used.add(r);
      return { kind: 'rock', rock: r, x: r.x + Math.cos(a) * d, y: r.y + Math.sin(a) * d, heading: rng.range(0, M.TAU) };
    }
    if (home === 'fern') {
      const ferns = this.life.ferns.filter((f) => !used.has(f) && this.inView(f, 0.02) && !this.underBranch(this.frondPoint(f, f.fronds[f.fronds.length - 1], 0.55, 0)));
      if (!ferns.length) return null;
      const clump = rng.pick(ferns), frond = clump.fronds[clump.fronds.length - 1], along = rng.range(0.45, 0.62);
      used.add(clump);
      const p = this.frondPoint(clump, frond, along, this.life.time), offset = rng.range(-0.4, 0.4) + (rng.chance(0.5) ? Math.PI : 0);
      return { kind: 'fern', clump, frond, along, offset, x: p.x, y: p.y, heading: p.a + offset };
    }
    for (let tries = 0; tries < 600; tries++) {
      if (home === 'bank') {
        const side = rng.sign(), s = rng.range(0, ch.A), q = ch.xy(s, this.edgeN(s, side) + side * len * 0.3);
        if (!this.inView(q) || ch.rockAt(q.x, q.y, len) || !clear(q, len * 6) || this.covered(q)) continue;
        const mid = ch.xy(s, ch.centre(s));
        return { kind: 'bank', x: q.x, y: q.y, heading: Math.atan2(mid.y - q.y, mid.x - q.x) + rng.range(-0.5, 0.5) };
      }
      const p = { x: rng.range(0, ch.w), y: rng.range(0, ch.h) };
      if (!this.inView(p) || ch.rockAt(p.x, p.y, len * 1.5) || !clear(p, len * 4) || this.covered(p)) continue;
      const w = ch.sample(p.x, p.y), toShore = ch.shore(ch.sOf(p.x, p.y), ch.nOf(p.x, p.y));
      if (home === 'float' && w.depth > 0.18 && w.depth < 0.6 && Math.hypot(w.vx, w.vy) < ch.vmax * 0.35 && toShore < C * 0.14) return { kind: 'float', x: p.x, y: p.y, heading: rng.range(0, M.TAU) };
      if (home === 'shallow' && w.depth > 0.04 && w.depth < 0.12) {
        const deep = ch.deeper(p.x, p.y);
        return { kind: 'shallow', x: p.x, y: p.y, heading: Math.atan2(deep.y, deep.x) + rng.range(-1.2, 1.2) };
      }
    }
    return null;
  }

  /** Slow water by a bank for the tadpoles, out from under the fronds; null when there is none. */
  shallows(rng) {
    const ch = this.ch;
    for (let k = 0; k < 400; k++) {
      const p = { x: rng.range(0, ch.w), y: rng.range(0, ch.h) }, w = ch.sample(p.x, p.y);
      if (this.inView(p, 0.1) && w.depth > 0.16 && w.depth < 0.34 && Math.hypot(w.vx, w.vy) < ch.vmax * 0.3 && !ch.rockAt(p.x, p.y, ch.C * 0.05) && !this.covered(p)) return p;
    }
    return null;
  }

  /** A point `along` (0..1) a frond of a clump at time t, as the frond sways (FernClump.sway), and the frond's direction there. */
  frondPoint(clump, frond, along, t) {
    const a = frond.angle + clump.sway(frond, t), L = frond.sprite.w * frond.scale * along;
    return { x: clump.x + Math.cos(a) * L, y: clump.y + Math.sin(a) * L, a };
  }

  /**
   * A spot in water deep enough to swim in, about `dist` away from (x, y) and as near the way `dir` as there is one; further, up to
   * FAR times as far, when there is none that near (a small frog in the middle of a big stone has to jump further to clear it); null
   * when there is none at all.
   */
  waterAhead(x, y, dir, dist, len) {
    const ch = this.ch;
    for (const far of FrogPond.FAR) {
      for (let k = 0; k < 24; k++) {
        const a = dir + (k ? (k % 2 ? 1 : -1) * Math.ceil(k / 2) * 0.22 : 0), d = dist * far * (1 - 0.02 * k);
        const p = { x: x + Math.cos(a) * d, y: y + Math.sin(a) * d }, w = ch.sample(p.x, p.y);
        if (w.depth > 0.14 && !ch.rockAt(p.x, p.y, len * 0.8) && this.inView(p, 0.02)) return p;
      }
    }
    return null;
  }

  /**
   * Something came at a frog from `from`: into the water with it; a tree frog jumps to another frond instead, of its own clump or of one
   * near it (clumps stand 0.6 of the short side apart along a bank, too far for one jump), and goes into the water only with none in reach.
   */
  startle(f, from) {
    if (f.state !== 'sit' && f.state !== 'float') return;
    const away = Math.atan2(f.y - from.y, f.x - from.x);
    if (f.home.kind === 'fern') {
      const t = this.life.time, fronds = this.life.ferns.flatMap((clump) => clump.fronds.map((frond) => ({ clump, frond, at: this.frondPoint(clump, frond, 0.55, t) })))
        .filter((o) => o.frond !== f.home.frond && Math.hypot(o.at.x - f.x, o.at.y - f.y) < f.len * 8 && !this.underBranch(o.at));
      if (fronds.length) {
        const { clump, frond } = f.rng.pick(fronds), along = f.rng.range(0.45, 0.62);
        f.home = { kind: 'fern', clump, frond, along, offset: f.home.offset };
        this.leap(f, this.frondPoint(clump, frond, along, t), f.len * 1.2, 0.55, false);
        return;
      }
    }
    if (f.state === 'float') {                            // afloat: it dives and swims off under the water
      f.state = 'swim'; f.t = 0; f.kicks = 3; f.kick = 3.2; f.phase = 0;
      f.target = this.waterAhead(f.x, f.y, away, f.len * 4, f.len);
      this.life.ripples.disturb(f.x, f.y, 0.5, f.len * 0.5);
      return;
    }
    const p = this.waterAhead(f.x, f.y, away, f.len * f.rng.range(2.4, 3.4), f.len);
    if (!p) return;
    f.state = 'crouch'; f.t = 0; f.next = p;
  }

  /** A jump to `to`: the longer, the higher and the longer in the air, from the given height and time of a jump of three lengths. */
  leap(f, to, height, dur, water) {
    const k = Math.max(1, Math.hypot(to.x - f.x, to.y - f.y) / (f.len * 3));
    f.jump = { from: { x: f.x, y: f.y }, to, s: 0, dur: dur * Math.sqrt(k), height: height * Math.sqrt(k), water };
    f.heading = Math.atan2(to.y - f.y, to.x - f.x);
    f.state = 'jump'; f.t = 0;
  }

  /** The end of a jump: into the water with a ring and a quiet plop (the minnows near it scatter), or onto the stone, the bank or the frond. */
  land(f) {
    const life = this.life, ch = this.ch, j = f.jump;
    f.z = 0;
    if (!j.water) {
      f.state = 'sit'; f.t = 0; f.dur = f.rng.range(10, 24);
      if (f.home.kind === 'fern') f.home.offset = M.wrap(f.heading - this.frondPoint(f.home.clump, f.home.frond, f.home.along, life.time).a);
      return;
    }
    life.ripples.disturb(f.x, f.y, 0.6 * f.len / (ch.C * FrogKinds.LARGEST), f.len * 0.5);
    life.scene.sound((kit, t) => kit.plink(t, FrogPond.PLOP));
    life.shoal.spook(f.x, f.y, ch.C * 0.1, ch);
    f.state = 'swim'; f.t = 0; f.kicks = f.rng.int(2, 4); f.kick = 2.6; f.phase = 0.2; f.speed = f.len * 2.4;
    f.target = this.waterAhead(f.x, f.y, f.heading + f.rng.range(-0.7, 0.7), f.len * 3.5, f.len);
  }

  /** Whether a frog coming back under the water is near enough to its place to get out onto it. */
  nearHome(f) {
    const h = f.home;
    if (h.kind === 'rock') return h.rock.inside(f.x, f.y, f.len * 0.9) > 0;
    if (h.kind === 'fern') { const p = this.frondPoint(h.clump, h.frond, h.along, this.life.time); return Math.hypot(p.x - f.x, p.y - f.y) < f.len * 1.8; }
    return Math.hypot(h.x - f.x, h.y - f.y) < f.len * (h.kind === 'float' ? 1 : 1.5);
  }

  update(dt) {
    const life = this.life, ch = this.ch;
    for (const f of this.frogs) {
      f.t += dt; f.breath += dt * (f.state === 'float' ? 2.0 : 2.8);
      f.blinkIn -= dt;
      if (f.blinkIn <= 0) { f.blink = Frog.BLINK; f.blinkIn = f.rng.range(5, 14); }
      f.blink = Math.max(0, f.blink - dt);
      f.tongue = Math.max(0, f.tongue - dt / 0.16);
      if (f.turnTo !== null) { f.heading = M.turnToward(f.heading, f.turnTo, 1.6 * dt); if (Math.abs(M.wrap(f.turnTo - f.heading)) < 0.02) f.turnTo = null; }
      if (f.state === 'sit' || f.state === 'float') {
        const p = life.pointerNear(f.x, f.y, f.len * 3.5, 380);
        if (p) { this.startle(f, p); continue; }
        if (f.home.kind !== 'fern') this.hunt(f);
      }
      this.act(f, dt);
    }
    if (this.school) this.school.update(dt);
  }

  /** One frame of what a frog is doing. */
  act(f, dt) {
    const life = this.life, ch = this.ch;
    switch (f.state) {
      case 'sit':
        if (f.home.kind === 'fern') {                      // the frond moves in the air, and the frog with it
          const p = this.frondPoint(f.home.clump, f.home.frond, f.home.along, life.time);
          f.x = p.x; f.y = p.y; f.heading = p.a + f.home.offset;
        } else if (f.t > f.dur) { f.t = 0; f.dur = f.rng.range(10, 26); f.turnTo = f.heading + f.rng.range(-0.7, 0.7); }
        break;
      case 'crouch':
        if (f.t > FrogPond.CROUCH) this.leap(f, f.next, f.len * 0.7, 0.42, true);
        break;
      case 'jump': {
        const j = f.jump;
        if (f.home.kind === 'fern' && !j.water) j.to = this.frondPoint(f.home.clump, f.home.frond, f.home.along, life.time);
        j.s = Math.min(1, f.t / j.dur);
        f.x = M.lerp(j.from.x, j.to.x, j.s); f.y = M.lerp(j.from.y, j.to.y, j.s); f.z = 4 * j.height * j.s * (1 - j.s);
        if (j.s >= 1) this.land(f);
        break;
      }
      case 'swim': case 'return': {
        const before = f.phase;
        f.phase = (f.phase + dt / FrogPond.STROKE) % 1;
        if (f.phase < 0.2) f.speed += f.len * f.kick * dt / (0.2 * FrogPond.STROKE);
        if (f.phase < before) f.kicks--;
        f.speed = M.approach(f.speed, 0, 2.2, dt);
        const to = f.state === 'return' ? (f.home.kind === 'fern' ? this.frondPoint(f.home.clump, f.home.frond, f.home.along, life.time) : f.home) : f.target;
        if (to) f.heading = M.turnToward(f.heading, Math.atan2(to.y - f.y, to.x - f.x), 2.4 * dt);
        const w = ch.sample(f.x, f.y);
        if (f.state === 'swim' && w.depth < 0.1) { const g = ch.deeper(f.x, f.y); f.heading = M.turnToward(f.heading, Math.atan2(g.y, g.x), 3 * dt); }
        f.x += Math.cos(f.heading) * f.speed * dt + w.vx * 0.15 * dt; f.y += Math.sin(f.heading) * f.speed * dt + w.vy * 0.15 * dt;
        for (const r of ch.rocks) if (!(f.state === 'return' && r === f.home.rock)) r.pushOut(f, f.len * 0.4);
        if (f.state === 'swim' && f.kicks <= 0 && f.phase > 0.6) {
          f.state = 'float'; f.t = 0; f.dur = f.rng.range(6, 14); f.speed = 0;
          life.ripples.disturb(f.x, f.y, 0.3, f.len * 0.5);
        } else if (f.state === 'return' && this.nearHome(f)) {
          if (f.home.kind === 'float') { f.state = 'float'; f.t = 0; f.dur = f.rng.range(10, 20); break; }
          const at = f.home.kind === 'fern' ? this.frondPoint(f.home.clump, f.home.frond, f.home.along, life.time) : { x: f.home.x, y: f.home.y };
          life.ripples.disturb(f.x, f.y, 0.5, f.len * 0.5);
          this.leap(f, at, f.len * (f.home.kind === 'fern' ? 1.2 : 0.4), 0.34, false);
        }
        break;
      }
      case 'float': {
        const w = ch.sample(f.x, f.y);
        f.x += w.vx * 0.1 * dt; f.y += w.vy * 0.1 * dt;    // the water takes it a little: it floats where the water is slow
        // carried well off its place (the mockup's floater went 352 px down the stream in 45 s), it swims back under the water
        if (f.home.kind === 'float' && Math.hypot(f.home.x - f.x, f.home.y - f.y) > f.len * 2.5) { f.state = 'return'; f.t = 0; f.phase = 0.65; f.kick = 2.2; break; }
        if (f.paddle > 0) {
          f.paddle -= dt; f.phase = (f.phase + dt / FrogPond.STROKE) % 1;
          if (f.phase < 0.2) f.speed += f.len * 1.2 * dt / (0.2 * FrogPond.STROKE);
        }
        f.speed = M.approach(f.speed, 0, 1.8, dt);
        f.x += Math.cos(f.heading) * f.speed * dt; f.y += Math.sin(f.heading) * f.speed * dt;
        for (const r of ch.rocks) r.pushOut(f, f.len * 0.4);
        if (f.t > f.dur) {
          f.t = 0;
          if (f.home.kind !== 'float') { f.state = 'return'; f.phase = 0.65; f.kick = 2.2; break; }
          f.dur = f.rng.range(6, 14);                      // a few lazy strokes back to its place, or a turn
          const dx = f.home.x - f.x, dy = f.home.y - f.y;
          if (Math.hypot(dx, dy) > f.len * 1.2) { f.turnTo = Math.atan2(dy, dx); f.paddle = FrogPond.STROKE * f.rng.int(1, 3); f.phase = 0.65; }
          else f.turnTo = f.heading + f.rng.range(-1, 1);
        }
        break;
      }
    }
  }

  /** A fly in reach in front of a frog that sits or floats: a flick of the tongue takes it. One further off, or to the side, is turned to. */
  hunt(f) {
    if (f.tongue > 0) return;
    for (const fly of this.life.flies) {
      if (!fly.alive) continue;
      const dx = fly.x - f.x, dy = fly.y - f.y, d = Math.hypot(dx, dy);
      if (d > f.len * 3) continue;
      const off = Math.abs(M.wrap(Math.atan2(dy, dx) - f.heading));
      if (d > f.len * FrogPond.REACH || off > 1.0) { if (f.turnTo === null && off > 0.3) f.turnTo = Math.atan2(dy, dx); continue; }
      const [lx, ly] = FrogArt.turn(dx, dy, -f.heading);
      f.tongueTo = [lx / f.len, ly / f.len]; f.tongue = 1; fly.alive = false;
      this.life.ripples.disturb(fly.x, fly.y, 0.25, f.len * 0.3);
      return;
    }
  }

  /** A hand's plop at (x, y): the frogs within `radius` of it go. */
  plop(x, y, radius) {
    for (const f of this.frogs) if (Math.hypot(f.x - x, f.y - y) < radius) this.startle(f, { x, y });
  }

  /** Under the water, through it: what of the frogs is under the surface, and the shadows of all of them on the bed, the bank, the stone. */
  drawUnder(u, s) {
    const ch = this.ch;
    for (const f of this.frogs) {
      const layer = f.layer, ink = FrogInk.of(f.kind), depth = ch.sample(f.x, f.y).depth;
      let h;                                                // how high it is over where its shadow falls: that sets how far the shadow goes
      if (layer === 'under') h = ch.waterDepthPx(depth) * 0.5;
      else if (layer === 'split') h = ch.waterDepthPx(depth);
      else h = (f.home.kind === 'fern' ? ch.C * 0.05 : f.len * 0.22) + f.z + ch.waterDepthPx(depth);
      const sx = f.x + BROOK_SHADOW.x * h, sy = f.y + BROOK_SHADOW.y * h, shade = layer === 'under' ? 0.5 : 0.58;
      const above = this.stillOf(f, ink), below = this.stillUnderOf(f, ink);
      if (above) {                                          // at rest: its pictures, and the shadow of the whole of it
        (below || above).draw(s, sx, sy, f.heading, 1, shade, true);
        if (below) below.draw(u, f.x, f.y, f.heading);
        continue;
      }
      const pose = f.pose();
      s.save(); s.translate(sx, sy); s.rotate(f.heading); s.scale(f.len, f.len);
      FrogArt.silhouette(s, f, pose); s.fillStyle = `rgba(0,0,0,${shade})`; s.fill();
      s.restore();
      if (layer === 'top') continue;
      u.save(); u.translate(f.x, f.y); u.rotate(f.heading); u.scale(f.len, f.len);
      FrogPond.paintUnder(u, f, pose, ink, layer);
      u.restore();
    }
    if (this.school) this.school.drawUnder(u, s);
  }

  /**
   * What of a frog is under the surface, in its body units: the whole of it swimming or afloat, the legs of a wader, seen through the water
   * (a little of the bed shows through it) and tinted by it. The tint lies over the whole silhouette, so that the still picture of a wader
   * throws the shadow of the whole frog.
   */
  static paintUnder(ctx, f, pose, ink, layer) {
    ctx.save();
    ctx.globalAlpha = layer === 'under' ? 0.84 : 0.92;
    if (layer === 'wade') FrogArt.limbs(ctx, f, pose, ink, FrogLight.sun(FrogLight.key(f.heading)));
    else FrogArt.whole(ctx, f, pose, ink);
    ctx.globalAlpha = 1;
    FrogArt.silhouette(ctx, f, pose); ctx.fillStyle = layer === 'under' ? 'rgba(28,70,66,0.24)' : 'rgba(28,70,66,0.14)'; ctx.fill();
    ctx.restore();
  }

  /** The still picture of what of a resting floater or wader is under the water; null for a frog all above it, or one that moves. */
  stillUnderOf(f, ink) {
    const layer = f.layer;
    if ((layer !== 'split' && layer !== 'wade') || !this.stillOf(f, ink)) return null;
    // afloat its legs spread to 1.8 lengths behind its middle; sitting, they stay within 0.8
    return f.stillUnder.of(f, layer + ' ' + FrogLight.key(f.heading), layer === 'split' ? 1.9 : 0.8, this.life.dpr, (c) => FrogPond.paintUnder(c, f, f.pose(), ink, layer));
  }

  /**
   * Above the water. `level` 'low': on stones, on the bank, afloat, in the shallows: under the fern fronds that lean over them, so BrookLife
   * draws it before the ferns; 'high': the tree frogs on the fronds, after them.
   */
  drawTop(ctx, level) {
    const life = this.life;
    for (const f of this.frogs) {
      if ((f.home.kind === 'fern') !== (level === 'high')) continue;
      const layer = f.layer;
      if (layer === 'under') continue;
      const ink = FrogInk.of(f.kind), dark = M.clamp((1 - life.canopy.lightAt(f.x, f.y)) * 0.7, 0, 0.4);   // the canopy's shade, as on the leaves
      const still = this.stillOf(f, ink);
      if (still) {
        still.draw(ctx, f.x, f.y, f.heading);
        if (dark > 0.02) still.draw(ctx, f.x, f.y, f.heading, 1, dark, true);
        continue;
      }
      ctx.save(); ctx.translate(f.x, f.y); ctx.rotate(f.heading);
      if (layer === 'split') { ctx.scale(f.len, f.len); FrogArt.aboveWater(ctx, f, ink, dark); ctx.restore(); continue; }
      if (layer === 'wade') { ctx.scale(f.len, f.len); FrogArt.wading(ctx, f, ink, dark); ctx.restore(); continue; }
      const pose = f.pose(), lift = 1 + f.z / this.ch.C * 1.5;
      ctx.scale(f.len * lift, f.len * lift);
      if (f.z < f.len * 0.05) FrogPond.contact(ctx, f, ink);
      FrogArt.whole(ctx, f, pose, ink);
      if (dark > 0.02) { FrogArt.silhouette(ctx, f, pose); ctx.fillStyle = `rgba(0,0,0,${dark.toFixed(3)})`; ctx.fill(); }
      ctx.restore();
    }
  }

  /** A frog at rest (sitting, or afloat and still) as its still picture (FrogStill); null while it moves, blinks or has its tongue out. */
  stillOf(f, ink) {
    const resting = f.state === 'sit' || (f.state === 'float' && f.paddle <= 0 && f.speed < f.len * 0.05);
    if (!resting || f.blink > 0 || f.tongue > 0) return null;
    const layer = f.layer, key = layer + ' ' + FrogLight.key(f.heading), dpr = this.life.dpr;
    if (layer === 'split') return f.still.of(f, key, 0.6, dpr, (c) => FrogArt.aboveWater(c, f, ink, 0));
    if (layer === 'wade') return f.still.of(f, key, 0.65, dpr, (c) => FrogArt.wading(c, f, ink, 0));
    return f.still.of(f, key, 0.8, dpr, (c) => { FrogPond.contact(c, f, ink); FrogArt.whole(c, f, f.pose(), ink); });
  }

  /** The shade right under a frog, where it touches the stone or the leaf, in its body units. */
  static contact(ctx, f, ink) {
    const [sx, sy] = FrogArt.turn(BROOK_SHADOW.x, BROOK_SHADOW.y, -f.heading);
    SoftShape.draw(ctx, sx * 0.06 - 0.04, sy * 0.06, 0.56, 0.36, 0, ink.contact);
  }
}
