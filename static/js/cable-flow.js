// The drops that run along a cable which carries a request now (the owner, 2026-10-14: "keep how an active
// connection is shown, dashes or a drop — on the main board, and in Routing too"). One module for both
// boards: the main board's cables (cables.js) and Routing's (pool-board.js) each draw their lit cable
// and put this twin over it. Its look is cables.css (.cable-flow); here is only what has to be said in the markup.
//
// Since 1.3.579 (the owner, 2026-10-18: "make the drops come up and go down smoothly, not abruptly, and run both
// ways at once, not only left to right"):
//   - the twin is a pair: the drops run from the cable's output to its input and, at the same time, from its input
//     back to its output, the second set half a lap behind the first so the two do not stand on one another;
//   - at each end of the cable the drops come up from nothing and go down to nothing (a gradient along the cable,
//     `EDGE` of its length at each end), so a drop is not there at the dot and gone at the other dot;
//   - a cable that begins to carry a request brings its drops up over `RISE_MS`, and one that stops lets them go over
//     `FALL_MS`: the board draws its cables anew many times a second and from the monitor's rows, so the cable's story is
//     kept here by the cable's key (`seen`) and every drawing says whether it carries now (`twin`) and then asks who
//     stopped (`ghosts`).
export class CableFlow {
  // One lap of the animation, in ms: the drops cross one period of their pattern (--flow-period in cables.css, 26px),
  // so a lap is 26px in 380ms, 68px a second.
  static LAP_MS = 380;
  // How long the drops of a cable that begins to carry a request take to come up, and the drops of one that stops to go down.
  static RISE_MS = 600;
  static FALL_MS = 900;
  // A cable seen carrying longer ago than this stopped long ago: it is not drawn fading, and a cable seen again after it begins anew.
  static GRACE_MS = 3000;
  // The share of a cable's length, at each end, over which its drops come up and go down.
  static EDGE = 0.16;

  static serial = 0;          // the ids of the gradients: one per twin drawn
  static seen = new Map();    // key → { d, kin, from, to, since, last, ended }: what the cables that carried a request were
  static drawn = new Set();   // the keys the drawing now under way has drawn

  // Where in its lap a twin made at `now` stands. Every twin on both pages reads the same clock: a cable drawn anew — a
  // scroll, a refresh of the activity — takes up its drops where the cable it replaces had them, and they do not
  // jump back to the start at every redraw (the board redraws its cables a few times a second).
  static lapAt(now) {
    const clock = Number(now);
    return Number.isFinite(clock) ? Math.round(clock % CableFlow.LAP_MS) : 0;   // a clock that says no time puts the drops at the start of their lap, not NaN in a style
  }

  // A board begins to draw its cables anew: what the last drawing drew is forgotten, so what this one does not draw is what stopped.
  static round() {
    CableFlow.drawn = new Set();
  }

  // Nothing is known of any cable (a page that begins again; the snapshots).
  static reset() {
    CableFlow.seen = new Map();
    CableFlow.drawn = new Set();
    CableFlow.serial = 0;
  }

  // The twin of a cable: its own `d`, run from the cable's start to its end and back. `kin` is the classes of its cable
  // that things find it by (the main board lights a cable by the hovered handle's route class, cables.js), without
  // `topology-cable`: the twin is no cable, it keeps to the line. `key` names the cable (the same one at every drawing) so
  // its drops can come up when it begins to carry and go down when it stops; with none they are simply there. `from` and `to`
  // are the points the cable runs between: with them the drops come up and go down along it.
  static twin(d, kin = "", now = Date.now(), { key = "", from = null, to = null } = {}) {
    const clock = Number.isFinite(Number(now)) ? Number(now) : Date.now();
    let age = Infinity;     // how long its drops have been coming up; Infinity: they are up
    if (key) {
      let entry = CableFlow.seen.get(key);
      if (!entry || clock - entry.last > CableFlow.GRACE_MS) {
        entry = { since: clock, ended: null };
      } else if (entry.ended !== null) {
        // It carries again before its drops were gone: they come up from where they had got to in going down, not from nothing and not at
        // once. The two easings are mirrors of each other (ease-in down, ease-out up), so coming up by the share that is left to go down
        // is the opacity the going down had reached.
        const gone = Math.min(1, (clock - entry.ended) / CableFlow.FALL_MS);
        entry.since = clock - Math.round(CableFlow.RISE_MS * (1 - gone));
        entry.ended = null;
      }
      Object.assign(entry, { d, kin, from, to, last: clock });
      CableFlow.seen.set(key, entry);
      CableFlow.drawn.add(key);
      age = clock - entry.since;
    }
    return CableFlow.pair(d, kin, clock, { from, to, rising: age < CableFlow.RISE_MS ? Math.max(0, Math.round(age)) : null });
  }

  // The twins of the cables that carried a request in the last drawing and do not now: their drops go down over FALL_MS from the drawing
  // that first misses them (the next drawings take it up from where it was, by the clock), and then they are gone.
  static ghosts(now = Date.now()) {
    const clock = Number.isFinite(Number(now)) ? Number(now) : Date.now();
    let out = "";
    for (const [key, entry] of [...CableFlow.seen]) {
      if (CableFlow.drawn.has(key)) continue;
      if (clock - entry.last > CableFlow.GRACE_MS) { CableFlow.seen.delete(key); continue; }
      if (entry.ended === null) entry.ended = clock;
      const gone = clock - entry.ended;
      if (gone >= CableFlow.FALL_MS) { CableFlow.seen.delete(key); continue; }
      out += CableFlow.pair(entry.d, entry.kin, clock, { from: entry.from, to: entry.to, falling: Math.max(0, Math.round(gone)) });
    }
    return out;
  }

  // The two paths of a twin, and the gradient they are painted by. `rising` / `falling`: how long ago the drops began to come up / to go down.
  static pair(d, kin, now, { from = null, to = null, rising = null, falling = null } = {}) {
    const fade = falling !== null ? "fading" : rising !== null ? "rising" : "";
    const lap = CableFlow.lapAt(now);
    const back = (lap + CableFlow.LAP_MS / 2) % CableFlow.LAP_MS;
    const paint = from && to ? ++CableFlow.serial : 0;
    const style = (phase) => `${paint ? `stroke:url(#cf${paint}) var(--accent-strong, var(--accent));` : ""}`
      + `animation-duration:${CableFlow.LAP_MS}ms${fade ? `,${falling !== null ? CableFlow.FALL_MS : CableFlow.RISE_MS}ms` : ""};`
      + `animation-delay:-${phase}ms${fade ? `,-${falling ?? rising}ms` : ""}`;
    const classes = (way) => ["cable-flow", way, fade, ...String(kin || "").split(/\s+/)].filter(Boolean).join(" ");
    return CableFlow.gradient(paint, from, to)
      + `<path class="${classes("fwd")}" d="${d}" style="${style(lap)}"></path>`
      + `<path class="${classes("back")}" d="${d}" style="${style(back)}"></path>`;
  }

  // The drops come up and go down along the cable: opaque between the two ends' `EDGE`, clear at the ends themselves. The colour is the
  // stylesheet's (.cable-flow-stop), so the theme is.
  static gradient(id, from, to) {
    if (!id) return "";
    const stop = (offset, opacity) => `<stop class="cable-flow-stop" offset="${offset}" stop-opacity="${opacity}"></stop>`;
    return `<defs><linearGradient id="cf${id}" gradientUnits="userSpaceOnUse" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}">`
      + `${stop(0, 0)}${stop(CableFlow.EDGE, 1)}${stop(1 - CableFlow.EDGE, 1)}${stop(1, 0)}</linearGradient></defs>`;
  }
}
