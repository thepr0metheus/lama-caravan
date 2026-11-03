/*
 * river-fish.js: the fish of the brook. A trout holds its lie behind a rock, facing the current,
 * and rises to insects that drift over it; a shoal of Colchic minnows works the shallows. Both
 * swim the same way (Swimmer): they want a ground velocity, the current pushes them, and they
 * swim through the water only where they point. A fish cannot swim sideways: it turns first,
 * and its turn builds up and settles like a body's would.
 */
import { M, Rng } from "./river-core.js";
import { MinnowArt, MinnowShape } from "./river-minnow.js";
import { TroutArt, TroutShape } from "./river-trout.js";
import { BROOK_SHADOW } from "./river-world.js";

class Swimmer {
  constructor(x, y, len, segments, rng) {
    this.x = x; this.y = y; this.len = len;
    this.heading = rng.range(0, M.TAU);
    this.goal = this.heading;
    this.speed = 0; this.vx = 0; this.vy = 0;
    this.turnRate = 0; this.amp = 0.1; this.bend = 0;
    this.agility = Swimmer.AGILITY;
    this.phase = rng.range(0, M.TAU);
    this.fin = rng.range(0, M.TAU);
    this.depth = 0.5;
    this.passing = null;           // the rock it is going round and on which hand ({ rock, turn }), kept while that rock is in its way
    this.smooth = false;           // a node points half way between its two segments (the outline of the minnow and of the trout), not along the next one
    this.spine = Array.from({ length: segments + 1 }, () => ({ x, y, a: 0 }));
    this.widths = new Float32Array(segments + 1);
    this.inner = new Float32Array(segments + 1);
  }
  /** Ground velocity toward a point, slowing inside `slow` px, and the point itself (`to`): the way ends there (see `steer`). */
  seek(x, y, speed, slow = this.len) {
    const dx = x - this.x, dy = y - this.y, d = Math.hypot(dx, dy) || 1;
    const v = slow > 0 ? Math.min(speed, speed * d / slow) : speed;
    return { x: dx / d * v, y: dy / d * v, to: { x, y } };
  }
  /**
   * Moves the fish: `want` is a ground velocity, with the point it leads to (`to`) when it leads somewhere; `cap` (px/s),
   * `turn` (rad/s), `accel` (1/s) limit it.
   */
  swim(dt, channel, want, cap, turn, accel, minDepth = 0.16) {
    const water = channel.sample(this.x, this.y);
    // a fish keeps low, in the slack water near the bed: it feels only part of the surface current
    const cx = water.vx * Swimmer.CURRENT_FELT, cy = water.vy * Swimmer.CURRENT_FELT;
    // shallows are steered away from, not shoved out of
    if (water.depth < minDepth) {
      const g = channel.deeper(this.x, this.y), k = (minDepth - water.depth) * this.len * 8;
      want.x += g.x * k; want.y += g.y * k;
    }
    // a rock in the way is gone round, not pushed against
    const to = want.to || null;
    want = this.steer(want, channel, cap);
    let sx = want.x - cx, sy = want.y - cy;
    let sp = Math.hypot(sx, sy);
    if (sp > cap) { sx *= cap / sp; sy *= cap / sp; sp = cap; }
    if (sp > this.len * 0.05) this.goal = Math.atan2(sy, sx);
    // the turn: its rate builds and settles, and a fish with no way on turns slowly
    const err = M.wrap(this.goal - this.heading);
    const way = M.clamp(this.speed / (this.len * 1.5), 0, 1);
    const wantRate = M.clamp(err * this.agility.gain, -turn, turn) * (this.agility.pivot + (1 - this.agility.pivot) * way);
    this.turnRate = M.approach(this.turnRate, wantRate, Swimmer.TURN_EASE, dt);
    this.heading = M.wrap(this.heading + this.turnRate * dt);
    // it swims only where it points; turned away from where it wants to go, it hardly swims at all
    const facing = Math.max(0, Math.cos(M.wrap(this.goal - this.heading)));
    this.speed = M.approach(this.speed, sp * facing * facing, accel, dt);
    // through the water it moves along its body; what is left of its old way sideways dies fast,
    // since water presses hard on a flank. The current's share is laid on top.
    const hx = Math.cos(this.heading), hy = Math.sin(this.heading);
    // it never swims at a stone faster than it could stop short of it in STOP seconds: a fish brakes with its fins. Short of the
    // stone is outside its margin (ROCK_TOUCH, where stayInWater holds it) — unless where it goes is at the stone (a fly drifting
    // by it): then it comes up to the stone itself, slowly, and can take the fly there.
    const touch = this.len * Swimmer.ROCK_TOUCH, stone = this.rockAhead(channel, hx, hy, Infinity, touch);
    if (stone) {
      const upTo = to && stone.rock.inside(to.x, to.y, touch) > 0 ? touch : 0;
      this.speed = Math.min(this.speed, Math.max(0, stone.enter + upTo) / Swimmer.STOP);
    }
    const ux = this.vx - cx, uy = this.vy - cy;
    const side = M.approach(-ux * hy + uy * hx, 0, Swimmer.FLANK_DRAG, dt);
    this.vx = hx * this.speed - hy * side + cx;
    this.vy = hy * this.speed + hx * side + cy;
    this.x += this.vx * dt; this.y += this.vy * dt;
    this.stayInWater(channel);
    this.depth = water.depth;
    this.animate(dt);
    this.buildSpine();
  }
  /**
   * The ground velocity it wants, turned round the first rock in its way (the owner, 2026-10-20: "the fish run away but stop
   * against a rock, instead of going round it as they come up to it"). It looks along the way it wants to go, as far as it
   * would swim in `LOOK` seconds (never less than `LOOK_LEAST` of its length) and no further than where that way ends
   * (`want.to`): a rock beyond its lie, its hiding place or a fly is not in its way. A rock whose outline, grown by `ROCK_ROOM`
   * and by `TURN_LEAD` for its speed, crosses that line turns the want onto a line that grazes the grown outline (`pastRock`
   * says on which side). The side, once taken, is kept while that rock is in the way: a fish that chose again every frame would
   * wobble into it. The way turned past one rock is looked along once more, for another one. How much it wants is kept: a rock
   * changes where a fish goes, not how hard. Until 1.3.603 a rock only pushed a fish straight away from its centre once it was
   * within 0.9 of its length; head on, that push only braked, and a trout scared from below ran into the rock it holds behind
   * every time.
   */
  steer(want, channel, cap) {
    const speed = Math.hypot(want.x, want.y);
    if (speed < 1e-9) { this.passing = null; return want; }
    const going = Math.min(speed, cap), reach = Math.max(this.len * Swimmer.LOOK_LEAST, going * Swimmer.LOOK);
    const room = this.len * Swimmer.ROCK_ROOM + going * Swimmer.TURN_LEAD;
    let wx = want.x / speed, wy = want.y / speed, passed = null;
    for (let look = 0; look < 2; look++) {          // rocks stand apart (Channel.placeRocks): a way turned past one meets at most one more
      // the second look leaves out the rock just gone round: a way along its outline touches it, and a fresh choice of side there flips the fish round
      const block = this.rockAhead(channel, wx, wy, reach, room, want.to || null, passed);
      if (!block) { if (look === 0) this.passing = null; break; }
      passed = block.rock;
      const way = this.pastRock(block, channel, look === 0, wx, wy);
      wx = way.x; wy = way.y;
    }
    return { x: wx * speed, y: wy * speed };
  }
  /**
   * The first rock in the way of the line from the head along (ux, uy), or null: one whose outline, grown by `grow` px, the line
   * enters within `reach` px. A line that leads to a place (`to`) ends there, and a rock beyond it is not in the way. A place in
   * the water about a rock (inside its grown outline: a lie, a hiding place, a fly by the stone) is gone to straight, and that
   * rock is in the way only when the line passes the stone itself (`ROCK_TOUCH` round it) before it gets there. `enter` is how
   * far along the line it meets the outline: below 0 when the head is already inside it. `except` is a rock left out.
   */
  rockAhead(channel, ux, uy, reach, grow, to = null, except = null) {
    const until = to ? Math.hypot(to.x - this.x, to.y - this.y) : Infinity, far = Math.min(reach, until);
    let best = null;
    for (const rock of channel.rocks) {
      if (rock === except) continue;
      const dx = rock.x - this.x, dy = rock.y - this.y, along = dx * ux + dy * uy;
      if (along <= 0) continue;
      const edge = rock.radiusAt(Math.atan2(-dy, -dx)), room = edge + grow, miss = Math.abs(dx * uy - dy * ux);
      let enter;
      if (to && rock.inside(to.x, to.y, grow) > 0) {
        const stone = edge + this.len * Swimmer.ROCK_TOUCH;
        if (miss >= stone || along + Math.sqrt(stone * stone - miss * miss) > until) continue;
        enter = along - Math.sqrt(stone * stone - miss * miss);
      } else {
        if (miss >= room) continue;
        enter = along - Math.sqrt(room * room - miss * miss);
        if (enter > far) continue;
      }
      if (!best || enter < best.enter) best = { rock, dx, dy, edge, room, enter };
    }
    return best;
  }
  /**
   * The way past a rock in the way of a fish going along (ux, uy): of the two lines from the head that graze its grown outline
   * (inside it already, of the two ways along it), the side taken before while it is the same rock (`keep`), or else:
   * - for a rock ahead along the stream, the one by its side toward the middle of the stream (`Channel.middleSide`; the owner,
   *   2026-10-20: "not the side nearer the goal — a fish at the bank would go between the bank and the rock and get stuck").
   *   A rock on the middle line is passed on the side the fish is on;
   * - for a rock that lies more across the stream than along it from the fish, the one nearer the way it goes: both go by the
   *   rock's side the fish is on, and the other leads round the far end of the rock, away from where it goes.
   */
  pastRock({ rock, dx, dy, edge, room }, channel, keep, ux, uy) {
    const d = Math.hypot(dx, dy) || 1, at = Math.atan2(dy, dx), inside = d <= room;
    // inside the grown outline the way goes along it, and within ROCK_ROOM of the stone out of it too, the more the nearer: straight
    // along, the current set the nose of a fish that had come close a little into the stone, and the stone held it back (STOP)
    const near = Math.min(1, Math.max(0, 1 - (d - edge) / (this.len * Swimmer.ROCK_ROOM)));
    const spread = inside ? Math.PI / 2 + Math.asin(near) : Math.asin(room / d), graze = inside ? 0 : Math.sqrt(d * d - room * room);
    let turn = keep && this.passing && this.passing.rock === rock ? this.passing.turn : 0;
    if (!turn) {
      const way = (t) => ({ x: Math.cos(at + t * spread), y: Math.sin(at + t * spread) });
      if (Math.abs(channel.acrossOf({ x: dx, y: dy })) > d * Math.SQRT1_2) {
        const a = way(1), b = way(-1);
        turn = a.x * ux + a.y * uy >= b.x * ux + b.y * uy ? 1 : -1;
      } else {
        let side = channel.middleSide(rock.x, rock.y, rock.r * 0.25);
        if (!side) side = Math.sign(channel.acrossOf({ x: -dx, y: -dy })) || 1;
        // how far to that side of the rock each way goes by it: where it grazes the grown outline (or, inside it, where it heads)
        const by = (t) => {
          const u = way(t);
          return side * (inside ? channel.acrossOf(u) : channel.acrossOf({ x: u.x * graze - dx, y: u.y * graze - dy }));
        };
        turn = by(1) >= by(-1) ? 1 : -1;
      }
      if (keep) this.passing = { rock, turn };
    }
    return { x: Math.cos(at + turn * spread), y: Math.sin(at + turn * spread) };
  }
  /** What the body does as the fish swims, as it did in the first version (the owner, 2026-10-19: "return the movements from the very first version"): the beat's phase and reach, the bend of a turn, the fins' rowing. */
  animate(dt) {
    this.phase += dt * M.TAU * (1.4 + this.speed / this.len * 1.3);
    const wantAmp = 0.08 + Math.min(0.24, Math.abs(this.turnRate) * 0.05) + Math.min(0.14, this.speed / this.len * 0.03);
    this.amp = M.approach(this.amp, wantAmp, 5, dt);
    this.bend = M.approach(this.bend, M.clamp(-this.turnRate * 0.22, -0.9, 0.9), 7, dt);
    this.fin += dt * (2.2 + this.speed / this.len);
  }
  /** The direction of the segment that ends at u (snout 0, tail 1) along the body, as the body bends: `back` is the way from the head to the tail when it is straight. */
  angleAt(u, back) {
    return back + this.amp * Math.pow(u, 1.5) * Math.sin(this.phase - u * 4.4) + this.bend * u;
  }
  /**
   * The last resort when steering was not enough: out of a rock, inside the banks, and inside the picture. The bank is
   * drawn over the water's edge, so a fish that crosses it swims under the moss (the owner, 2026-10-13: "they run under
   * the bank"): no point of the body — snout, middle, tail — goes past the edge, and the way it was going into the bank
   * is lost. It may still go along the stream as far as the picture allows.
   */
  stayInWater(channel) {
    const hx = Math.cos(this.heading), hy = Math.sin(this.heading);
    // a rock as a bank: no point of the body comes within ROCK_TOUCH of it, and the way into it is lost (until 1.3.603 only the
    // snout was kept out, and a fish turning away from a rock swept its body across the stone)
    for (const r of channel.rocks) {
      for (const u of [0, 0.5, 1]) {
        const px = this.x - hx * this.len * u, py = this.y - hy * this.len * u, deep = r.inside(px, py, this.len * Swimmer.ROCK_TOUCH);
        if (deep <= 0) continue;
        const ox = px - r.x, oy = py - r.y, od = Math.hypot(ox, oy) || 1, nx = ox / od, ny = oy / od;
        this.x += nx * deep; this.y += ny * deep;
        const v = this.vx * nx + this.vy * ny;
        if (v < 0) { this.vx -= v * nx; this.vy -= v * ny; }
      }
    }
    const margin = this.len * Swimmer.BANK_ROOM;
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
      const a = this.angleAt(i / n, back);
      sp[i - 1].a = a;
      x += Math.cos(a) * seg; y += Math.sin(a) * seg;
      sp[i].x = x; sp[i].y = y; sp[i].a = a;
    }
    // Down from the tail, so that the node before is still the angle of the segment it leaves by when this one takes the mean.
    if (this.smooth) for (let i = n - 1; i >= 1; i--) sp[i].a = M.meanAngle(sp[i - 1].a, sp[i].a);
  }
  /** A point on the spine: u from snout (0) to tail (1). Its angle is the node's own, or, on a smooth body, the one half way between the two nodes it lies between. */
  at(u) {
    const sp = this.spine, n = sp.length - 1, f = M.clamp(u, 0, 1) * n, i = Math.min(n - 1, Math.floor(f)), t = f - i, a = sp[i], b = sp[i + 1];
    return { x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t, a: this.smooth ? a.a + M.wrap(b.a - a.a) * t : a.a };
  }
  /** The half width of the body at u, read from `widths` (the drawing fills them in from its profile). */
  halfAt(u) {
    const n = this.widths.length - 1, f = M.clamp(u, 0, 1) * n, i = Math.min(n - 1, Math.floor(f));
    return M.lerp(this.widths[i], this.widths[i + 1], f - i);
  }
  /** A point on the body: u from snout (0) to tail (1), v across from -1 to 1. */
  bodyPoint(u, v, profile) {
    const n = this.spine.length - 1, f = M.clamp(u, 0, 1) * n, i = Math.min(n - 1, Math.floor(f)), t = f - i;
    const p = this.at(u), w = (profile[i] * (1 - t) + profile[i + 1] * t) * this.len;
    return { x: p.x - Math.sin(p.a) * w * v, y: p.y + Math.cos(p.a) * w * v, a: p.a };
  }
}

/** Share of the surface current a fish near the bed is carried by. */
Swimmer.CURRENT_FELT = 0.35;
/** How fast a turn builds up or settles (1/s). */
Swimmer.TURN_EASE = 5;
/** How fast a fish turns toward a new goal (`gain`, 1/s of the angle left) and how much of that it keeps with no way on (`pivot`). */
Swimmer.AGILITY = Object.freeze({ gain: 2.4, pivot: 0.35 });
/** How fast a fish loses sideways way through the water (1/s): its flank is a broad paddle. */
Swimmer.FLANK_DRAG = 12;
/** How far inside the water's edge every point of a fish's body stays, as a share of its length. */
Swimmer.BANK_ROOM = 0.2;
/** How far ahead a fish looks for a rock in its way: as far as it would swim in this many seconds, and never less than LOOK_LEAST of its length. */
Swimmer.LOOK = 0.7;
Swimmer.LOOK_LEAST = 0.5;
/** How much wider of a rock a fish passes for every px/s it wants to go, in seconds: the room its turn needs, so that it turns before it is there. */
Swimmer.TURN_LEAD = 0.08;
/** How wide of a rock's outline the way of a fish passes, as a share of its length: half its body, and water to turn in. */
Swimmer.ROCK_ROOM = 0.25;
/** How near a rock's outline a point of the body — snout, middle, tail — may come, as a share of its length. */
Swimmer.ROCK_TOUCH = 0.12;
/** How soon a fish can stop with its fins, in seconds: it never swims at a stone faster than it could stop short of it in this time. */
Swimmer.STOP = 0.4;

/*
 * What a trout does in each state: the ground velocity it wants, its limits (body lengths per
 * second, radians per second, 1/s) and what ends the state. One row per state.
 */
const TROUT_STATES = Object.freeze({
  hold: {
    cap: 2.2, turn: 1.3, accel: 2,
    want(f, life) { return f.idle(life); },
    next(f, life) {
      const fly = life.flyFor(f);
      if (fly) { fly.claimedBy = f; f.target = fly; return 'notice'; }
      return f.stateTime > f.roamAfter ? 'roam' : null;
    },
  },
  // A fly it has seen is thought over before the fish moves (the owner, 2026-10-19: "the moment the moth appears they swim after it; they used to think
  // longer before they started to swim"). For `thinkFor` seconds it keeps its lie as in `hold`, its eyes on the fly. A fly that is gone by then is let go.
  notice: {
    cap: 2.2, turn: 1.3, accel: 2,
    want(f, life) { return f.idle(life); },
    next(f) {
      const g = f.target;
      if (!g || !g.alive || g.claimedBy !== f) return 'hold';
      return f.stateTime >= f.thinkFor ? 'chase' : null;
    },
  },
  chase: {
    // a trout turns sharply to a fly beside it — the take lands at its mouth only if it can still turn when the fly is near
    cap: 4.4, turn: 6, accel: 3.6, agility: Object.freeze({ gain: 4.5, pivot: 0.8 }),
    // the tip of the snout is what must arrive: at the place the fly will be when the fish gets there
    want(f, life) { return f.meet(f.target, life.channel, this.cap * f.len); },
    next(f, life) {
      const g = f.target;
      if (!g.alive || g.claimedBy !== f) return 'back';
      if (f.takes(g.x, g.y)) { life.rise(f, g); return 'back'; }
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
  // a startled trout turns at once, even from rest (a fish's escape: it bends and is off). Turning as slowly as it swims about
  // (until 1.3.603: 4.5 rad/s, the common agility), it stood at the rock it holds behind while its way round was still ahead of it.
  flee: {
    cap: 6, turn: 6, accel: 6, agility: Object.freeze({ gain: 5, pivot: 0.9 }),
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
    super(lie.x, lie.y, len, TroutShape.SEGMENTS, rng);
    this.smooth = true;
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
    this.mouthWas = null;   // where the tip of the snout stood before the last step: the way it went since is what takes a fly
    // The first version made its 55 dots here. The draws are kept, and thrown away, so that every seed lays the brook out as it did: where each
    // trout holds, and when it goes roaming (the owner, 2026-10-19: the behaviour of the first version, all of it).
    for (let i = 0; i < Trout.DOT_DRAWS; i++) rng.next();
    // What its drawing needs (river-trout.js): the skin's seed and the skin once it is painted (when the trout is first drawn: a page is needed
    // for its canvas), how hard it swims, the fins' phase, the swing and the spread of the tail, the gills' breath, where the eyes look.
    this.skinSeed = Math.floor(this.seed * 1000);
    // How long it thinks over a fly it has seen comes from a stream of its own, so that the brook's stream keeps the order the first version drew it in.
    this.thinkRng = new Rng(this.skinSeed + 202);
    this.thinkFor = 0;
    this.skin = null;
    this.clock = 0; this.eff = 0; this.finPhase = 0; this.breath = 0.5; this.tailAng = 0; this.tailSpread = 0.05;
    this.look = { x: Math.cos(this.heading), y: Math.sin(this.heading) };
  }
  /** The ground velocity of a trout idling at its lie: it drifts slowly about it, a little differently each time. */
  idle(life) {
    const t = life.time * 0.07;
    const wx = life.noise.n2(this.seed, t) * this.len * 0.6, wy = life.noise.n2(this.seed + 40, t) * this.len * 0.6;
    return this.seek(this.lie.x + wx, this.lie.y + wy, this.len * 1.2);
  }
  enter(state, life) {
    if (state === 'back' && this.target) { this.target = null; }
    if (state === 'roam') this.lie = life.freeLie(this) || this.lie;
    if (state === 'hide') { this.hideAt = life.shelterNear(this); this.hideFor = this.rng.range(3, 6); }
    if (state === 'hold') this.roamAfter = this.rng.range(50, 110);
    if (state === 'notice') this.thinkFor = this.thinkRng.range(Trout.THINK.least, Trout.THINK.most);
    this.agility = TROUT_STATES[state].agility || Swimmer.AGILITY;
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
    this.mouthWas = this.mouth();
    this.swim(dt, life.channel, st.want(this, life), st.cap * this.len, st.turn, st.accel);
  }
  /**
   * The body of a swimming trout is the first version's (the owner, 2026-10-19: "return the movements from the very first version"): the
   * beat's phase and reach, the bend of a turn and the fins' rowing are Swimmer's. What the drawing needs besides (river-trout.js) is read
   * from them: how hard the fish swims (`eff`, 0 at rest and 1 at 1.4 lengths a second), the swing and the spread of the tail as the first
   * version's tail had them, the gills' breath, and where the eyes look.
   */
  animate(dt) {
    super.animate(dt);
    const len = this.len;
    this.clock += dt;
    this.eff = M.clamp(this.speed / (len * 1.4), 0, 1);
    this.finPhase = this.fin;
    this.tailAng = Math.sin(this.phase - 4.9) * this.amp * 1.2;
    this.tailSpread = 0.035 + 0.04 * Math.abs(Math.sin(this.phase - 4.9));
    this.breath = 0.5 + 0.5 * Math.sin(this.clock * M.TAU * 1.15 + this.skinSeed);
    // where the eyes look: at the fly while it thinks it over, and at the one it chases when it is near, else ahead
    const fly = this.target, m = this.mouth();
    let lx = Math.cos(this.heading), ly = Math.sin(this.heading);
    if (fly && fly.alive && (this.state === 'notice' || Math.hypot(fly.x - m.x, fly.y - m.y) < len * 1.3)) {
      const dx = fly.x - m.x, dy = fly.y - m.y, d = Math.hypot(dx, dy) || 1;
      lx = dx / d; ly = dy / d;
    }
    this.look.x = M.approach(this.look.x, lx, 8, dt);
    this.look.y = M.approach(this.look.y, ly, 8, dt);
  }
  buildSpine() {
    super.buildSpine();
    for (let i = 0; i < this.widths.length; i++) this.widths[i] = TroutShape.PROFILE[i] * this.len;
  }
  /** The tip of the snout, where the painted nose ends (TopFishPainter): where a fly must come to be taken. */
  mouth() {
    const reach = this.len * TroutShape.NOSE;
    return { x: this.x + Math.cos(this.heading) * reach, y: this.y + Math.sin(this.heading) * reach };
  }
  /** Where the head's first point must stand for the tip of the snout to stand at (x, y). */
  headFor(x, y) {
    const reach = this.len * TroutShape.NOSE;
    return { x: x - Math.cos(this.heading) * reach, y: y - Math.sin(this.heading) * reach };
  }
  /**
   * The ground velocity that brings the tip of the snout to where a fly will be when the fish gets there. The fish feels
   * only part of the current and the fly all of it, so a fly goes by the fish at the difference of the two, and a fish that
   * only points at the fly passes beside it: the line of sight swings faster than a fish can turn. `speed` is the fish's
   * way through the water at most; it shrinks with the distance (`EASE`), so that the fish can still turn when it is near.
   * `to` is where the head goes to meet the fly: a fly drifting by a rock is taken there, not gone round with the rock.
   */
  meet(fly, channel, speed) {
    const water = channel.sample(this.x, this.y), cx = water.vx * Swimmer.CURRENT_FELT, cy = water.vy * Swimmer.CURRENT_FELT;
    const head = this.headFor(fly.x, fly.y), dx = head.x - this.x, dy = head.y - this.y;
    const rx = fly.vx - cx, ry = fly.vy - cy;
    speed = Math.min(speed, Trout.EASE * Math.hypot(dx, dy));
    // the time to meet: |D + r t| = speed t
    const a = rx * rx + ry * ry - speed * speed, b = 2 * (dx * rx + dy * ry), c = dx * dx + dy * dy;
    let t = 0;
    if (Math.abs(a) < 1e-9) t = b < 0 ? -c / b : 0;
    else if (b * b - 4 * a * c >= 0) {
      const root = Math.sqrt(b * b - 4 * a * c);
      t = [(-b - root) / (2 * a), (-b + root) / (2 * a)].filter((v) => v > 0).sort((p, q) => p - q)[0] || 0;
    }
    const ax = dx + rx * Math.min(t, 3), ay = dy + ry * Math.min(t, 3), far = Math.hypot(ax, ay) || 1;
    return { x: cx + ax / far * speed, y: cy + ay / far * speed, to: { x: this.x + ax, y: this.y + ay } };
  }
  /**
   * Whether the mouth took the fly at (x, y) in the step it has just made: the fly's centre lay within `GAPE` of the tip of
   * the snout somewhere along the way the tip went. A slow frame moves a fish far in one step, and it must not swim over a
   * fly unseen. (The owner, 2026-10-14 and again 2026-10-19: "the fish eats the fly while the mouth is still far from it" — it
   * was 0.42 of its length from the head's first point, 0.39 from the nose.)
   */
  takes(x, y) {
    const now = this.mouth(), was = this.mouthWas || now;
    return M.segmentGap(was.x, was.y, now.x, now.y, x, y) <= this.len * Trout.GAPE;
  }
  /** Height above the bed (px) — it sets how far the shadow falls. */
  height(channel) { return channel.waterDepthPx(this.depth) * 0.55; }
  draw(ctx, painter) {
    TroutArt.draw(ctx, this, painter);
  }
  drawShadow(ctx, painter, channel) {
    const h = this.height(channel), dx = BROOK_SHADOW.x * h, dy = BROOK_SHADOW.y * h;
    const n = this.spine.length - 1;
    for (let i = 0; i <= n; i++) this.inner[i] = TroutShape.PROFILE[i] * this.len * 1.1;
    painter.outline(ctx, this.spine, this.inner, this.len * TroutShape.NOSE, dx, dy);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
    ctx.fill();
    TroutArt.tailPath(ctx, this, dx, dy);
    ctx.fill();
  }
}

/** How near a fly's centre must come to the tip of the snout to be taken, in body lengths: a mouth's width and a fly's. */
Trout.GAPE = 0.08;
/** How far the way through the water may grow with the distance to a fly (1/s): a trout slows as it comes up to a fly. */
Trout.EASE = 8;
/** How long a trout thinks over a fly it has seen before it moves, in seconds: each time, a draw between the two. */
Trout.THINK = Object.freeze({ least: 0.8, most: 1.8 });
/** How many random numbers the first version's 55 dots took (46 dots of three, 9 red ones of four): see the constructor. */
Trout.DOT_DRAWS = 46 * 3 + 9 * 4;

/*
 * Colchic minnow: small, olive above and silver at the side, a band of uneven blotches along each side. What it does is here;
 * how it is drawn is river-minnow.js (the owner, 2026-10-18: "the silver minnow").
 */
class Minnow extends Swimmer {
  constructor(x, y, len, rng) {
    super(x, y, len, MinnowShape.SEGMENTS, rng);
    this.smooth = true;
    this.tone = rng.range(-12, 12);
    this.pattern = MinnowArt.pattern(new Rng(Math.floor((this.tone + 12) * 1e6) + 1));   // a stream of its own: the brook's stays as the first version left it
    this.dart = 0;
    this.escape = null;
  }
  draw(ctx, painter) {
    MinnowArt.draw(ctx, this, painter);
  }
  drawShadow(ctx, painter, channel) {
    const h = channel.waterDepthPx(this.depth) * 0.5, dx = BROOK_SHADOW.x * h, dy = BROOK_SHADOW.y * h;
    const n = this.spine.length - 1;
    for (let i = 0; i <= n; i++) this.inner[i] = MinnowShape.PROFILE[i] * this.len * 1.15;
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
      // the pull home is one of the shoal's pulls, and their sum leads nowhere in particular: no `to`, every rock along it counts
      const pull = m.seek(this.home.x, this.home.y, L * 1.6, L * 6), want = { x: pull.x, y: pull.y };
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
