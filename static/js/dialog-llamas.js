// Animated pixel llamas for the shared confirm dialog (#confirmOverlay).
// Scene kinds: "delete" — the llama stomps a crate flat (a fresh one slides
// in, loop); "change" — it nose-flips a big toggle; "start" — it steps
// between a green and a red button, pressing them with a front paw.
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
  press:  { b: [[3, 10], [3, 11], [5, 10], [5, 11], [8, 10], [8, 11], [11, 9], [12, 9]], h: [[3, 12], [12, 10]] },
};

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

// ── props (drawn to the RIGHT of the llama, x13..18) ─────────────────────────
const CRATE = "#8a7351", CRATE2 = "#6e5137", ROPE = "#c8a06c";
function crate(state) {
  const px = [];
  if (state === "ok") {
    for (let y = 8; y <= 11; y += 1) for (let x = 14; x <= 17; x += 1) px.push([x, y, y === 9 ? ROPE : (x === 14 || x === 17 ? CRATE2 : CRATE)]);
  } else if (state === "dent") {
    for (let y = 9; y <= 11; y += 1) for (let x = 14; x <= 17; x += 1) px.push([x, y, y === 10 ? ROPE : CRATE]);
    px.push([13, 11, CRATE2], [18, 11, CRATE2]);
  } else if (state === "flat") {
    for (let x = 13; x <= 18; x += 1) px.push([x, 11, CRATE2]);
    px.push([14, 10, ROPE], [17, 10, CRATE]);
  }
  return px;
}
function buttons(lit) {
  const px = [];
  const G = lit === "g" ? "#3fae6a" : "#2f6b46", R = lit === "r" ? "#e05555" : "#7d3030";
  [[13, 10], [14, 10], [13, 11], [14, 11]].forEach(([x, y]) => px.push([x, y, G]));
  [[16, 10], [17, 10], [16, 11], [17, 11]].forEach(([x, y]) => px.push([x, y, R]));
  if (lit === "g") px.push([13, 9, "#baf3c9"], [14, 9, "#baf3c9"]);
  if (lit === "r") px.push([16, 9, "#f6c0ba"], [17, 9, "#f6c0ba"]);
  return px;
}
function toggle(side, accent) {
  const px = [[14, 11, CRATE2], [15, 11, CRATE2], [16, 11, CRATE2], [15, 9, CRATE], [15, 10, CRATE]];
  if (side === "l") px.push([14, 8, CRATE], [13, 7, accent], [13, 8, accent]);
  else px.push([16, 8, CRATE], [17, 7, accent], [17, 8, accent]);
  return px;
}
const propShadow = (px) => px.map(([x, y, c]) => `${x}em ${y}em 0 0 ${c}`).join(", ");

// ── scene timelines: [pose, propShadow, llamaShiftEm, propSlide] per tick ────
function timeline(kind, accent) {
  if (kind === "delete") {
    return [
      ["standA", propShadow(crate("ok")), 0, false],
      ["rear", propShadow(crate("ok")), 0, false],
      ["stomp", propShadow(crate("dent")), 0, false],
      ["stomp", propShadow(crate("flat")), 0, false],
      ["standB", propShadow(crate("flat")), 0, false],
      ["standA", propShadow(crate("ok")), 0, true],   // fresh crate slides in
    ];
  }
  if (kind === "start") {
    return [
      ["press", propShadow(buttons("g")), 0, false],
      ["standA", propShadow(buttons("")), 0, false],
      ["press", propShadow(buttons("r")), 3, false],  // steps over to the red one
      ["standB", propShadow(buttons("")), 3, false],
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
  const ico = overlay.querySelector(".dlg-ico");
  if (!ico) return;
  teardown(overlay);
  const modal = overlay.querySelector(".modal");
  const kind = overlay.dataset.dlgScene
    || (modal?.dataset.tone === "danger" ? "delete" : "change");
  const body = BODIES[Math.floor(Math.random() * BODIES.length)];
  const blanket = BLANKETS[Math.floor(Math.random() * BLANKETS.length)];
  const accent = getComputedStyle(document.documentElement).getPropertyValue("--accent").trim() || "#4da392";
  const frames = timeline(kind, accent);
  ico.classList.add("dlg-live");
  const lay = document.createElement("span");
  lay.className = "dlg-sc";
  lay.innerHTML = `<i class="dlg-sc-llama"></i><i class="dlg-sc-prop"></i>`;
  ico.appendChild(lay);
  const llamaEl = lay.firstElementChild;
  const propEl = lay.lastElementChild;
  let i = 0;
  const paint = () => {
    const [pose, prop, shift, slide] = frames[i % frames.length];
    llamaEl.style.boxShadow = llamaShadow(pose, body, blanket);
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
  const ico = overlay.querySelector(".dlg-ico");
  ico?.classList.remove("dlg-live");
  ico?.querySelector(".dlg-sc")?.remove();
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
