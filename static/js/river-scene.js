/*
 * river-scene.js: the brook seen from above, the scene object. It wires the world
 * (river-world.js), the water (river-water.js) and the life (river-life.js) to the stage, plays
 * a calm brook when the sound is on, and answers the pointer.
 */
import { Layer, Noise, Rng } from "./river-core.js";
import { BrookLife } from "./river-life.js";
import { BrookWater } from "./river-water.js";
import { BROOK, CanopyLight, Channel, RippleField } from "./river-world.js";

export class BrookScene {
  constructor(stage) {
    this.stage = stage;
    this.glCanvas = document.createElement('canvas');
    this.topCanvas = document.createElement('canvas');
    stage.root.append(this.glCanvas, this.topCanvas);
    this.top = this.topCanvas.getContext('2d');
    this.noise = new Noise(new Rng(BROOK.layoutSeed));
    this.rng = new Rng((Date.now() % 2147483647) | 1);
    this.world = null;
    this.life = null;
    this.failure = null;
    try {
      this.water = new BrookWater(this.glCanvas);
    } catch (err) {
      // no WebGL here: the scene stays empty and says so through `failure`; the page names it
      this.failure = err;
      console.warn(err);
    }
  }
  resize(w, h, dpr) {
    if (this.failure) return;
    const q = this.stage.quality.level;
    const glScale = Math.min(dpr, 1.25) * q;
    const glW = Math.max(2, Math.round(w * glScale)), glH = Math.max(2, Math.round(h * glScale));
    const sizeChanged = !this.world || this.world.channel.w !== w || this.world.channel.h !== h;
    if (sizeChanged) {
      const channel = new Channel(w, h, new Rng(BROOK.layoutSeed), this.noise);
      this.world = {
        channel,
        ripples: new RippleField(channel),
        canopy: new CanopyLight(w, h, channel.C, this.noise),
        under: null, shade: null,
      };
    }
    const underScale = glScale * 0.8;
    this.world.under = new Layer(w * underScale, h * underScale);
    this.world.underScale = underScale;
    this.world.shade = new Layer(Math.ceil(glW / 3), Math.ceil(glH / 3));
    this.world.shadeScale = glScale / 3;
    this.glCanvas.width = glW; this.glCanvas.height = glH;
    this.topCanvas.width = Math.round(w * dpr); this.topCanvas.height = Math.round(h * dpr);
    this.dpr = dpr;
    this.water.resize(glW, glH, glScale, this.world);
    if (sizeChanged || !this.life) this.life = new BrookLife(this, this.world, dpr);
    else this.life.rescale(dpr);
  }
  frame(dt, t) {
    if (this.failure || !this.world) return;
    const { ripples, canopy, under, shade } = this.world;
    canopy.step(t);
    ripples.step(dt);
    this.life.update(dt, t);
    const u = under.ctx, s = shade.ctx;
    u.setTransform(1, 0, 0, 1, 0, 0); u.clearRect(0, 0, under.width, under.height);
    s.setTransform(1, 0, 0, 1, 0, 0); s.clearRect(0, 0, shade.width, shade.height);
    u.setTransform(this.world.underScale, 0, 0, this.world.underScale, 0, 0);
    s.setTransform(this.world.shadeScale, 0, 0, this.world.shadeScale, 0, 0);
    this.life.drawUnder(u, s, t);
    this.water.draw(t, this.world);
    const top = this.top;
    top.setTransform(1, 0, 0, 1, 0, 0);
    top.clearRect(0, 0, this.topCanvas.width, this.topCanvas.height);
    top.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.life.drawTop(top, t);
  }
  pointer(kind, p) {
    if (this.failure || !this.life) return;
    this.life.pointer(kind, p);
  }
  /**
   * A calm brook and nothing else (the owner, 2026-10-13: no roaring, bubbling waterfall, only a
   * quiet stream): a soft murmur that swells and settles, a light babble over it, and now and then
   * a small trickle of two or three quiet plips.
   */
  soundscape(kit) {
    kit.bed({ colour: 'brown', gain: 0.06, type: 'lowpass', freq: 260, q: 0.4, swell: 0.25, swellRate: 0.05 });
    kit.bed({ colour: 'pink', gain: 0.13, type: 'bandpass', freq: 750, q: 0.6, wobble: 220, wobbleRate: 0.12, swell: 0.4, swellRate: 0.08, pan: -0.2 });
    kit.bed({ colour: 'pink', gain: 0.06, type: 'bandpass', freq: 1700, q: 0.9, wobble: 400, wobbleRate: 0.17, swell: 0.6, swellRate: 0.11, pan: 0.25, room: 0.2 });
    kit.every(0.6, 2.2, t => {
      const n = 1 + Math.floor(Math.random() * 3);
      for (let i = 0; i < n; i++) kit.drop(t + i * (0.05 + Math.random() * 0.09), { f: 1100 + Math.random() * 900, gain: 0.004 + Math.random() * 0.008, room: 0.25 });
    });
  }
  /** A sound the scene asks for (a rise, a pebble); silent when the page sound is off. */
  sound(fn) {
    const kit = this.stage.sound && this.stage.sound.live;
    if (kit) fn(kit, kit.ctx.currentTime + 0.01);
  }
  dispose() {
    if (this.water) this.water.dispose();
  }
}
