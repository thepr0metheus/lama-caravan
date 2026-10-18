/*
 * river-sound.js: the brook's sound, synthesized in the browser — nothing is downloaded.
 * Noise colours, the kit of loops and short events a scene plays, and the switch that owns the
 * AudioContext. Sound starts only from a click (browsers allow nothing else) and is off until then.
 */

/** Noise colours as generators: one row per colour instead of a branch per colour. */
const NOISE_COLOURS = Object.freeze({
  pink: () => {
    let b0 = 0, b1 = 0, b2 = 0, b3 = 0, b4 = 0, b5 = 0, b6 = 0;
    return () => {
      const w = Math.random() * 2 - 1;
      b0 = 0.99886 * b0 + w * 0.0555179; b1 = 0.99332 * b1 + w * 0.0750759;
      b2 = 0.96900 * b2 + w * 0.1538520; b3 = 0.86650 * b3 + w * 0.3104856;
      b4 = 0.55000 * b4 + w * 0.5329522; b5 = -0.7616 * b5 - w * 0.0168980;
      const out = (b0 + b1 + b2 + b3 + b4 + b5 + b6 + w * 0.5362) * 0.11;
      b6 = w * 0.115926;
      return out;
    };
  },
  brown: () => {
    let last = 0;
    return () => { last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02; return last * 3.5; };
  },
});

/**
 * One scene's sounds: loops of filtered noise and short synthesized events (drops).
 * Each kit has its own fader, so switching scenes crossfades kits. `stop()` takes
 * down every source and timer the kit started, the timers included.
 */
export class SoundKit {
  constructor(ctx, destination) {
    this.ctx = ctx;
    this.alive = true;
    this.sources = [];
    this.timers = new Set();
    this.out = ctx.createGain();
    this.out.gain.value = 0.0001;
    this.out.connect(destination);
    this.out.gain.setTargetAtTime(1, ctx.currentTime, 0.7);
    this.room = ctx.createConvolver();
    this.room.buffer = SoundKit.impulse(ctx, 3.4, 2.4);
    this.roomGain = ctx.createGain();
    this.roomGain.gain.value = 0.42;
    this.room.connect(this.roomGain).connect(this.out);
  }
  static buffer(ctx, colour, seconds) {
    const cache = SoundKit.cache || (SoundKit.cache = new Map());
    const key = colour + seconds + ctx.sampleRate;
    if (cache.has(key)) return cache.get(key);
    const len = Math.floor(ctx.sampleRate * seconds);
    const buf = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let c = 0; c < 2; c++) {
      const next = NOISE_COLOURS[colour](), d = buf.getChannelData(c);
      for (let i = 0; i < len; i++) d[i] = next();
      // fade the seam so the loop does not click
      const edge = Math.min(2000, len >> 3);
      for (let i = 0; i < edge; i++) { const k = i / edge; d[i] *= k; d[len - 1 - i] *= k; }
    }
    cache.set(key, buf);
    return buf;
  }
  static impulse(ctx, seconds, decay) {
    const len = Math.floor(ctx.sampleRate * seconds), buf = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let c = 0; c < 2; c++) {
      const d = buf.getChannelData(c);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay) * (i < 90 ? i / 90 : 1);
    }
    return buf;
  }
  /** A looped noise bed through one filter, with optional slow wobble of the filter and level. */
  bed({ colour = 'pink', gain = 0.2, type = 'lowpass', freq = 800, q = 0.7, pan = 0,
        wobble = 0, wobbleRate = 0.1, swell = 0, swellRate = 0.05, room = 0 } = {}) {
    const ctx = this.ctx;
    const src = ctx.createBufferSource();
    src.buffer = SoundKit.buffer(ctx, colour, 6);
    src.loop = true;
    src.loopStart = Math.random() * 3;
    const f = ctx.createBiquadFilter();
    f.type = type; f.frequency.value = freq; f.Q.value = q;
    const g = ctx.createGain(); g.gain.value = gain;
    const p = ctx.createStereoPanner(); p.pan.value = pan;
    src.connect(f).connect(g).connect(p).connect(this.out);
    if (room) { const s = ctx.createGain(); s.gain.value = room; p.connect(s).connect(this.room); }
    if (wobble) this.lfo(f.frequency, wobble, wobbleRate);
    if (swell) this.lfo(g.gain, gain * swell, swellRate);
    src.start(ctx.currentTime, Math.random() * 5);
    this.sources.push(src);
    return { filter: f, gain: g };
  }
  /** Slow random-ish modulation: two detuned sines summed, so the motion does not repeat soon. */
  lfo(param, depth, rate) {
    const ctx = this.ctx;
    for (const k of [1, 1.618]) {
      const o = ctx.createOscillator();
      o.frequency.value = rate * k * (0.8 + Math.random() * 0.4);
      const g = ctx.createGain(); g.gain.value = depth / 2;
      o.connect(g).connect(param);
      o.start(ctx.currentTime + Math.random());
      this.sources.push(o);
    }
  }
  /** Calls `fn(when)` again and again at random gaps between minS and maxS seconds. */
  every(minS, maxS, fn) {
    const loop = () => {
      if (!this.alive) return;
      try { fn(this.ctx.currentTime + 0.05); } catch (err) { console.warn('sound event failed', err); }
      const id = setTimeout(() => { this.timers.delete(id); loop(); }, (minS + Math.random() * (maxS - minS)) * 1000);
      this.timers.add(id);
    };
    const first = setTimeout(() => { this.timers.delete(first); loop(); }, Math.random() * maxS * 1000);
    this.timers.add(first);
  }
  /** One sine voice with a pitch glide (over `glide`, the whole `dur` unless said) and a fast attack: bird notes, drops and hoots. */
  voice(t, { f0, f1 = f0, dur, glide = dur, gain, pan = 0, room = 0.3, type = 'sine', attack = 0.006, vib = 0, vibRate = 0 }) {
    const ctx = this.ctx;
    const o = ctx.createOscillator(); o.type = type;
    o.frequency.setValueAtTime(f0, t);
    o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + glide);
    if (vib) {
      const l = ctx.createOscillator(), lg = ctx.createGain();
      l.frequency.value = vibRate; lg.gain.value = vib;
      l.connect(lg).connect(o.frequency);
      l.start(t); l.stop(t + dur + 0.05);
    }
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(gain, t + Math.min(attack, dur * 0.4));
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    const p = ctx.createStereoPanner(); p.pan.value = pan;
    o.connect(g).connect(p).connect(this.out);
    if (room) { const s = ctx.createGain(); s.gain.value = room; p.connect(s).connect(this.room); }
    o.start(t); o.stop(t + dur + 0.05);
  }
  /** A water drop: a short sine whose pitch rises, the way a small bubble rings (Minnaert). */
  drop(t, { f = 700 + Math.random() * 900, gain = 0.03, pan = Math.random() * 1.6 - 0.8, room = 0.15 } = {}) {
    const dur = 0.025 + Math.random() * 0.06;
    this.voice(t, { f0: f, f1: f * (1.4 + Math.random() * 0.8), dur, gain, pan, room, attack: 0.002 });
  }
  /**
   * A drop falling into water: the ring of the bubble it takes down — one sine whose pitch climbs fast and then settles while it
   * dies away (Minnaert), and nothing else. A burst of noise, which is what a tap or a splash is made of, did not sound right
   * (the owner, 2026-10-14: "let it be a sound like a drop falling into water"). `f` is where the ring starts — a small drop
   * rings high, a big one low and longer — and each drop comes a little different.
   */
  plink(t, { f = 900, ring = 0.24, gain = 0.07, pan = Math.random() * 1.2 - 0.6, room = 0.2 } = {}) {
    const start = f * (0.92 + Math.random() * 0.16);
    this.voice(t, { f0: start, f1: start * SoundKit.PLINK_RISE, dur: ring, glide: ring * 0.5, gain, pan, room, attack: 0.004 });
  }
  stop(fade = 0.8) {
    if (!this.alive) return;
    this.alive = false;
    for (const id of this.timers) clearTimeout(id);
    this.timers.clear();
    const t = this.ctx.currentTime;
    this.out.gain.cancelScheduledValues(t);
    this.out.gain.setValueAtTime(Math.max(0.0001, this.out.gain.value), t);
    this.out.gain.exponentialRampToValueAtTime(0.0001, t + fade);
    setTimeout(() => {
      for (const s of this.sources) { try { s.stop(); } catch (_) { /* already stopped */ } }
      this.out.disconnect();
    }, fade * 1000 + 100);
  }
}

/** How far a drop's ring climbs from where it starts to where it settles, as a ratio of pitch: the bubble shrinks as it rings. */
SoundKit.PLINK_RISE = 1.8;


/**
 * The brook's sound switch. It owns the AudioContext (made on the first click: browsers start
 * sound only after a gesture) and the kit of the scene that plays.
 */
export class Ambience {
  constructor() {
    this.ctx = null;
    this.master = null;
    this.kit = null;
    this.on = false;
  }
  toggle(scene) {
    this.on = !this.on;
    if (this.on) {
      if (!this.ctx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        this.ctx = new Ctx();
        this.master = this.ctx.createGain();
        this.master.gain.value = 0.85;
        const comp = this.ctx.createDynamicsCompressor();
        comp.threshold.value = -18; comp.ratio.value = 3;
        this.master.connect(comp).connect(this.ctx.destination);
      }
      this.ctx.resume();
      this.follow(scene);
    } else if (this.kit) {
      this.kit.stop(0.6);
      this.kit = null;
    }
    return this.on;
  }
  follow(scene) {
    if (!this.on || !this.ctx) return;
    if (this.kit) this.kit.stop(1.2);
    this.kit = new SoundKit(this.ctx, this.master);
    if (scene && scene.soundscape) scene.soundscape(this.kit);
  }
  /** Lets the sound go for good: the kit fades, the AudioContext closes. */
  dispose() {
    this.on = false;
    if (this.kit) { this.kit.stop(0.3); this.kit = null; }
    const ctx = this.ctx;
    this.ctx = null; this.master = null;
    if (ctx) setTimeout(() => { ctx.close().catch(() => { /* already closed */ }); }, 500);
  }
  /** A scene asks for a one-off sound (a splash, a crackle) only when sound is on. */
  get live() { return this.on && this.kit && this.kit.alive ? this.kit : null; }
}
