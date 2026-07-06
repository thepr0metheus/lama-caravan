// Animated pixel llamas for the shared confirm dialog (#confirmOverlay).
// Scene kinds: "delete" — the llama stomps a crate flat (a fresh one slides
// in, loop); "change" — it nose-flips a big toggle; "start" — a night launch:
// the llama presses the button, the rocket climbs out of the frame past a
// crescent moon, and a fresh rocket rolls onto the pad.
// The kind comes from overlay.dataset.dlgScene (set by appConfirm/appPrompt
// opts.scene) or falls back by tone: danger→delete, ask→change. Colors are
// re-rolled from the loader palette on every open, so the llama differs.
import { $ } from "./utils.js";

const BODIES = ["#d9c29a", "#e8e2d4", "#a97e4f", "#b9b3a7", "#8a6f52", "#cbb188"];
const BLANKETS = ["#43b3a4", "#d98c4a", "#9a7bd0", "#c4574e", "#4f8fd0", "#c9a83b"];
const HOOF = "#6e5137";

// ── llama pixels (the loader's 16×13 grid), poses as leg/head variations ────
const HEAD = [[11, 0], [13, 0], [11, 1], [12, 1], [14, 1], [11, 2], [12, 2], [13, 2], [14, 2]];
const EYE = [[13, 1]];
const NOSE = [[15, 2]];
const NECK = [[10, 3], [11, 3], [10, 4], [11, 4], [10, 5], [11, 5]];
const BODY = [];
for (let y = 6; y <= 9; y += 1) for (let x = 2; x <= 11; x += 1) BODY.push([x, y]);
BODY.push([1, 6], [1, 7]);
const BLANKET = [];
for (let y = 6; y <= 8; y += 1) for (let x = 4; x <= 8; x += 1) BLANKET.push([x, y]);

const LEGS = {
  standA: { b: [[3, 10], [3, 11], [5, 10], [5, 11], [8, 10], [8, 11], [10, 10], [10, 11]], h: [[3, 12], [10, 12]] },
  standB: { b: [[4, 10], [4, 11], [2, 10], [2, 11], [9, 10], [9, 11], [11, 10], [11, 11]], h: [[4, 12], [9, 12]] },
  // hind legs planted, front pair raised in the air, head thrown up a bit
  rear:   { b: [[3, 10], [3, 11], [5, 10], [5, 11], [10, 8], [11, 8], [10, 9]], h: [[3, 12]], headDy: -1 },
  // front legs slam down-forward (onto the crate zone)
  stomp:  { b: [[3, 10], [3, 11], [5, 10], [5, 11], [12, 9], [12, 10], [13, 9], [13, 10]], h: [[3, 12]], headDy: 1 },
  // one front paw reaches forward to a button, the rest stand
  press:  { b: [[3, 10], [3, 11], [5, 10], [5, 11], [8, 10], [8, 11], [11, 9], [12, 9]], h: [[3, 12], [13, 10]] },
  // standA legs, neck craned up — watching the rocket climb without moving
  watch:  { b: [[3, 10], [3, 11], [5, 10], [5, 11], [8, 10], [8, 11], [10, 10], [10, 11]], h: [[3, 12], [10, 12]], headDy: -1 },
};

// Lying-down sprite for the stop scene: body dropped to the ground, legs
// tucked, head resting low with the eye closed (a body-colored pixel).
function lieShadow(variant, body, blanket) {
  const px = [];
  for (let y = 8; y <= 11; y += 1) for (let x = 2; x <= 11; x += 1) px.push([x, y, body]);
  px.push([1, 8, body], [1, 9, body]);
  for (let y = 8; y <= 10; y += 1) for (let x = 4; x <= 8; x += 1) px.push([x, y, blanket]);
  // neck + resting head (ear up, eye closed, nose)
  px.push([10, 6, body], [11, 6, body], [10, 7, body], [11, 7, body]);
  px.push([11, 3, body], [13, 3, body]);
  for (let x = 11; x <= 14; x += 1) { px.push([x, 4, body]); px.push([x, 5, body]); }
  px.push([15, 5, HOOF]);
  // tucked front hooves peeking out; variant B twitches an ear
  px.push([3, 11, HOOF], [9, 11, HOOF]);
  if (variant === "b") px.push([13, 2, body]);
  return px.map(([x, y, c]) => `${x}em ${y}em 0 0 ${c}`).join(", ");
}

const ZZ = "#dce9e9";
function zzz(stage) {
  const px = [];
  // small rising dots near the head, then a proper 3×3 Z above
  if (stage >= 1) px.push([16, 4, ZZ], [17, 3, ZZ]);
  if (stage >= 2) px.push([16, 0, ZZ], [17, 0, ZZ], [18, 0, ZZ], [17, 1, ZZ], [16, 2, ZZ], [17, 2, ZZ], [18, 2, ZZ]);
  return px;
}

function llamaShadow(pose, body, blanket) {
  const px = [];
  const dy = LEGS[pose].headDy || 0;
  HEAD.forEach(([x, y]) => px.push([x, y + dy, body]));
  NECK.forEach(([x, y]) => px.push([x, y + Math.min(0, dy), body]));
  EYE.forEach(([x, y]) => px.push([x, y + dy, "#141c20"]));
  NOSE.forEach(([x, y]) => px.push([x, y + dy, HOOF]));
  BODY.forEach(([x, y]) => px.push([x, y, body]));
  BLANKET.forEach(([x, y]) => px.push([x, y, blanket]));
  LEGS[pose].b.forEach(([x, y]) => px.push([x, y, body]));
  LEGS[pose].h.forEach(([x, y]) => px.push([x, y, HOOF]));
  return px.map(([x, y, c]) => `${x}em ${y}em 0 0 ${c}`).join(", ");
}

// ── props (drawn to the RIGHT of the llama, x13..21) ─────────────────────────
const CRATE = "#8a7351", CRATE2 = "#6e5137", ROPE = "#c8a06c";
function crate(state) {
  const px = [];
  if (state === "ok") {
    // 6×5 crate with a rope band — big enough to read at a glance
    for (let y = 7; y <= 11; y += 1) for (let x = 14; x <= 19; x += 1) {
      const edge = x === 14 || x === 19 || y === 7 || y === 11;
      px.push([x, y, x === 16 || x === 17 ? ROPE : (edge ? CRATE2 : CRATE)]);
    }
  } else if (state === "dent") {
    for (let y = 9; y <= 11; y += 1) for (let x = 14; x <= 19; x += 1) px.push([x, y, y === 10 ? ROPE : CRATE]);
    px.push([13, 11, CRATE2], [20, 11, CRATE2], [15, 8, CRATE2], [18, 8, CRATE2]);
  } else if (state === "flat") {
    for (let x = 13; x <= 20; x += 1) px.push([x, 11, CRATE2]);
    px.push([14, 10, CRATE], [15, 10, ROPE], [16, 10, CRATE2], [18, 10, CRATE], [19, 10, CRATE2]);
    px.push([16, 9, CRATE2], [15, 8, CRATE]);  // splinters in the air
  }
  return px;
}
// start scene, night launch. Static scenery (crescent moon, pad, unlit launch
// button) lives on the sky layer; the prop layer carries only the rocket,
// flame, smoke and the button glow — so the slide-in animation on the prop
// layer moves the NEW rocket in without dragging the moon or the pad along.
// cool steel tones so the hull never matches a llama body (those are all warm)
const FL1 = "#ffd75e", FL2 = "#f0a44a", SMOKE = "#9aa5a8", ROCK1 = "#dfe9f2", ROCK2 = "#9fb4c4", RRED = "#c4574e", MOON = "#e6e0c0";
function startSky() {
  const px = [];
  // crescent moon top-left (open side facing the rocket's path)
  px.push([4, 0, MOON], [3, 0, MOON], [2, 1, MOON], [2, 2, MOON], [3, 3, MOON], [4, 3, MOON]);
  // launch button x12..14 (base y11, unlit cap y10) — a paw tip lands on x13
  [[12, 11], [13, 11], [14, 11]].forEach(([x, y]) => px.push([x, y, "#20282c"]));
  [[12, 10], [13, 10], [14, 10]].forEach(([x, y]) => px.push([x, y, "#2f6b46"]));
  // pad x16..20 with two legs — stays behind after liftoff
  [[16, 11], [17, 11], [18, 11], [19, 11], [20, 11]].forEach(([x, y]) => px.push([x, y, "#20282c"]));
  px.push([16, 10, CRATE2], [20, 10, CRATE2]);
  return px;
}
// stage: idle | lit | ignite | up1 | up2 | up4 | up7 | gone | empty | new
// (the stage box has overflow:hidden, so above-frame pixels just clip away)
function startProp(stage) {
  const px = [];
  const rocketAt = (lift) => {
    const dy = -lift;
    for (let y = 5; y <= 9; y += 1) for (let x = 17; x <= 19; x += 1) px.push([x, y + dy, x === 18 ? ROCK1 : ROCK2]);
    px.push([17, 4 + dy, RRED], [18, 4 + dy, RRED], [19, 4 + dy, RRED], [18, 3 + dy, RRED]);  // nose cone
    px.push([16, 9 + dy, RRED], [20, 9 + dy, RRED]);                                          // fins
    px.push([18, 6 + dy, "#4f8fd0"]);                                                         // porthole
  };
  const flameAt = (lift) => {
    px.push([18, 10 - lift, FL1], [17, 10 - lift, FL2], [19, 10 - lift, FL2], [18, 11 - lift, FL2]);
  };
  if (stage === "lit") px.push([12, 10, "#3fae6a"], [13, 10, "#3fae6a"], [14, 10, "#3fae6a"],
                               [12, 9, "#baf3c9"], [13, 8, "#baf3c9"], [14, 9, "#baf3c9"]);
  if (stage === "idle" || stage === "lit" || stage === "new") rocketAt(0);
  if (stage === "ignite") { rocketAt(0); px.push([18, 10, FL1], [17, 10, FL2], [19, 10, FL2]); }
  if (stage === "up1") { rocketAt(1); flameAt(1); }
  if (stage === "up2") { rocketAt(2); flameAt(2); px.push([16, 10, SMOKE], [20, 10, SMOKE]); }
  if (stage === "up4") { rocketAt(4); flameAt(4); px.push([16, 9, SMOKE], [20, 9, SMOKE], [16, 10, SMOKE], [20, 10, SMOKE]); }
  if (stage === "up7") { rocketAt(7); flameAt(7); px.push([16, 10, SMOKE], [18, 9, SMOKE], [20, 10, SMOKE]); }
  if (stage === "gone") px.push([16, 9, SMOKE], [18, 10, SMOKE], [20, 9, SMOKE], [17, 8, SMOKE], [19, 8, SMOKE], [18, 0, FL2]);
  if (stage === "empty") px.push([18, 10, SMOKE]);
  return px;
}
function toggle(side, accent) {
  // fat lever on a base: stick leans left/right, accent knob on top
  const px = [[15, 11, "#20282c"], [16, 11, "#20282c"], [17, 11, "#20282c"], [18, 11, "#20282c"],
              [16, 10, CRATE], [17, 10, CRATE]];
  if (side === "l") px.push([15, 9, CRATE], [14, 8, CRATE], [13, 7, accent], [14, 7, accent], [13, 8, accent]);
  else px.push([18, 9, CRATE], [19, 8, CRATE], [20, 7, accent], [19, 7, accent], [20, 8, accent]);
  return px;
}
// create scene: the llama STACKS crates (the delete scene's counterpart —
// there it stomps one flat, here it builds a tower and tops it with a flag).
function smallCrate(x0, y0) {
  const px = [];
  for (let y = y0; y <= y0 + 2; y += 1) for (let x = x0; x <= x0 + 3; x += 1) {
    const edge = y === y0 || y === y0 + 2 || x === x0 || x === x0 + 3;
    px.push([x, y, edge ? CRATE2 : CRATE]);
  }
  px.push([x0 + 1, y0 + 1, ROPE], [x0 + 2, y0 + 1, ROPE]);
  return px;
}
function tower(stage, accent) {
  const px = [];
  if (stage >= 1) px.push(...smallCrate(14, 9));            // first crate on the ground
  if (stage === 1.5) px.push(...smallCrate(15, 4));         // second crate mid-air
  if (stage >= 2) px.push(...smallCrate(14, 6));            // ...landed on top
  if (stage >= 3) px.push([15, 4, CRATE2], [15, 5, CRATE2], // flag pole
                          [16, 4, accent], [17, 4, accent], [16, 5, accent]); // banner
  return px;
}
const propShadow = (px) => px.map(([x, y, c]) => `${x}em ${y}em 0 0 ${c}`).join(", ");

// ── scene timelines: [pose, propShadow, llamaShiftEm, propSlide] per tick ────
function timeline(kind, accent) {
  if (kind === "create") {
    return [
      ["standA", propShadow(tower(0, accent)), 0, false],
      ["standB", propShadow(tower(1, accent)), 1, true],    // first crate slides in
      ["rear", propShadow(tower(1.5, accent)), 1, false],   // hoists the second one
      ["standA", propShadow(tower(2, accent)), 0, false],   // stacked!
      ["standB", propShadow(tower(3, accent)), 1, false],   // plants the flag
      ["standA", propShadow(tower(3, accent)), 0, false],
    ];
  }
  if (kind === "delete") {
    return [
      ["standA", propShadow(crate("ok")), 0, false],
      ["rear", propShadow(crate("ok")), 1, false],
      ["stomp", propShadow(crate("dent")), 1, false],
      ["stomp", propShadow(crate("flat")), 1, false],
      ["standB", propShadow(crate("flat")), 0, false],
      ["standA", propShadow(crate("ok")), 0, true],   // fresh crate slides in
    ];
  }
  if (kind === "stop") {
    return [
      ["standA", "", 0, false],
      ["lieA", "", 0, false],
      ["lieA", propShadow(zzz(1)), 0, false],
      ["lieB", propShadow(zzz(2)), 0, false],
      ["lieA", propShadow(zzz(2)), 0, false],
      ["lieB", propShadow(zzz(1)), 0, false],
    ];
  }
  if (kind === "start") {
    // after the press the llama keeps all four feet planted — only the head
    // tips up to follow the rocket (no marching, no second jab at the button)
    return [
      ["standA", propShadow(startProp("idle")), 0, false],
      ["press", propShadow(startProp("lit")), 0, false],    // paw hits the button
      ["standA", propShadow(startProp("ignite")), 0, false],
      ["standA", propShadow(startProp("up1")), 0, false],
      ["watch", propShadow(startProp("up2")), 0, false],    // head tilts up, feet planted
      ["watch", propShadow(startProp("up4")), 0, false],
      ["watch", propShadow(startProp("up7")), 0, false],    // only the tail flame still in frame
      ["watch", propShadow(startProp("gone")), 0, false],   // smoke on the pad, a spark far above
      ["standA", propShadow(startProp("empty")), 0, false], // quiet beat, head comes back down
      ["standA", propShadow(startProp("new")), 0, true],    // next rocket rolls onto the pad
    ];
  }
  return [ // change: nose-flip the toggle
    ["standA", propShadow(toggle("l", accent)), 0, false],
    ["standA", propShadow(toggle("l", accent)), 1, false],
    ["standB", propShadow(toggle("r", accent)), 0, false],
    ["standB", propShadow(toggle("r", accent)), 1, false],
  ];
}

let _timer = null;

function mountScene(overlay) {
  const modal = overlay.querySelector(".modal");
  if (!modal) return;
  teardown(overlay);
  const kind = overlay.dataset.dlgScene
    || (modal.dataset.tone === "danger" ? "delete" : "change");
  const body = BODIES[Math.floor(Math.random() * BODIES.length)];
  // The blanket must READ against the body — the pale bodies swallow the
  // pale blankets, leaving a seemingly naked llama.
  const lum = (hex) => parseInt(hex.slice(1, 3), 16) + parseInt(hex.slice(3, 5), 16) + parseInt(hex.slice(5, 7), 16);
  let blanket = BLANKETS[Math.floor(Math.random() * BLANKETS.length)];
  for (let tries = 0; tries < 5 && Math.abs(lum(blanket) - lum(body)) < 130; tries += 1) {
    blanket = BLANKETS[Math.floor(Math.random() * BLANKETS.length)];
  }
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#4da392";
  const frames = timeline(kind, accent);
  modal.classList.add("dlg-staged");   // hides the small header tile
  const stage = document.createElement("div");
  stage.className = "dlg-stage";
  stage.innerHTML = `<span class="dlg-sc"><i class="dlg-sc-sky"></i><i class="dlg-sc-llama"></i><i class="dlg-sc-prop"></i></span>`;
  modal.prepend(stage);
  const llamaEl = stage.querySelector(".dlg-sc-llama");
  const propEl = stage.querySelector(".dlg-sc-prop");
  const skyEl = stage.querySelector(".dlg-sc-sky");
  skyEl.style.boxShadow = kind === "start" ? propShadow(startSky()) : "";
  let i = 0;
  const paint = () => {
    const [pose, prop, shift, slide] = frames[i % frames.length];
    llamaEl.style.boxShadow = pose.startsWith("lie")
      ? lieShadow(pose.endsWith("B") ? "b" : "a", body, blanket)
      : llamaShadow(pose, body, blanket);
    llamaEl.style.transform = `translateX(${shift}em)`;
    propEl.style.boxShadow = prop;
    propEl.classList.toggle("dlg-sc-slide", !!slide);
    i += 1;
  };
  paint();
  _timer = setInterval(paint, 320);
}

function teardown(overlay) {
  if (_timer) { clearInterval(_timer); _timer = null; }
  const modal = overlay.querySelector(".modal");
  modal?.classList.remove("dlg-staged");
  modal?.querySelector(".dlg-stage")?.remove();
}

// Watch the shared overlay: legacy openers unhide it directly, so an
// attribute observer covers every path without touching the callers.
export function initDialogLlamas() {
  const overlay = $("confirmOverlay");
  if (!overlay) return;
  const sync = () => { if (overlay.hidden) { teardown(overlay); delete overlay.dataset.dlgScene; } else mountScene(overlay); };
  new MutationObserver(sync).observe(overlay, { attributes: true, attributeFilter: ["hidden"] });
  if (!overlay.hidden) sync();
}
