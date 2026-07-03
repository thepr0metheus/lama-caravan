// Dependency-free onboarding tour engine + floating "?" button.
// No app imports on purpose: /hf.js reuses it without pulling i18n-data.
// Tours are declared elsewhere (onboarding-tours.js for the board/kanban,
// inline in hf.js) and passed in; strings arrive pre-translated.

const BTN_SEEN_KEY = "caravanTourBtnUsed";

// Only one tour at a time: starting a new one stops the previous instance
// (button clicked while a tour is already open = restart, not stacking).
let activeTour = null;

function visibleEl(selector) {
  if (!selector) return null;
  const el = document.querySelector(selector);
  if (!el) return null;
  if (el.closest("[hidden]")) return null;
  const rect = el.getBoundingClientRect();
  if (rect.width < 4 && rect.height < 4) return null;
  if (getComputedStyle(el).visibility === "hidden") return null;
  return el;
}

export function createTour(config) {
  // labels may be a function so a language switch mid-tour re-resolves them.
  const L = () => (typeof config.labels === "function" ? config.labels() : config.labels) || {};
  let steps = [];
  let idx = 0;
  let root = null;
  let spot = null;
  let card = null;

  function liveSteps() {
    return (config.steps() || []).filter((s) => s.center || visibleEl(s.anchor));
  }

  function build() {
    root = document.createElement("div");
    root.className = "ob-root";
    root.innerHTML = `
      <div class="ob-spot" aria-hidden="true"></div>
      <div class="ob-card" role="dialog" aria-modal="true">
        <button class="ob-close" type="button" aria-label="${L().skip || "Close"}">×</button>
        <h3 class="ob-title"></h3>
        <div class="ob-body"></div>
        <div class="ob-foot">
          <span class="ob-count"></span>
          <span class="ob-nav">
            <button class="ob-back" type="button"></button>
            <button class="ob-next" type="button"></button>
          </span>
        </div>
      </div>`;
    spot = root.querySelector(".ob-spot");
    card = root.querySelector(".ob-card");
    root.querySelector(".ob-close").addEventListener("click", stop);
    root.querySelector(".ob-back").addEventListener("click", () => go(idx - 1));
    root.querySelector(".ob-next").addEventListener("click", () => go(idx + 1));
    document.body.appendChild(root);
    window.addEventListener("resize", position, { passive: true });
    window.addEventListener("scroll", position, { passive: true, capture: true });
    document.addEventListener("keydown", onKey, true);
  }

  function onKey(ev) {
    if (ev.key === "Escape") { ev.stopPropagation(); stop(); }
    else if (ev.key === "ArrowRight") go(idx + 1);
    else if (ev.key === "ArrowLeft") go(idx - 1);
  }

  function position() {
    if (!root) return;
    const step = steps[idx];
    if (!step) return;
    const el = step.center ? null : visibleEl(step.anchor);
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const pad = 6;
    let r;
    if (el) {
      const b = el.getBoundingClientRect();
      r = { x: b.left - pad, y: b.top - pad, w: b.width + pad * 2, h: b.height + pad * 2 };
      spot.classList.remove("ob-spot-center");
    } else {
      r = { x: vw / 2, y: vh / 2, w: 0, h: 0 };
      spot.classList.add("ob-spot-center");
    }
    spot.style.left = `${r.x}px`;
    spot.style.top = `${r.y}px`;
    spot.style.width = `${r.w}px`;
    spot.style.height = `${r.h}px`;

    // Card placement: below the target, flip above if cramped, centered for center steps.
    const cw = Math.min(360, vw - 24);
    card.style.width = `${cw}px`;
    const ch = card.offsetHeight || 180;
    let cx, cy;
    if (!el) {
      cx = (vw - cw) / 2;
      cy = Math.max(16, (vh - ch) / 2);
    } else {
      cx = Math.min(Math.max(12, r.x + r.w / 2 - cw / 2), vw - cw - 12);
      cy = r.y + r.h + 14;
      if (cy + ch > vh - 12) cy = r.y - ch - 14;      // flip above
      if (cy < 12) cy = Math.max(12, vh - ch - 16);   // fallback: pin bottom
    }
    card.style.left = `${cx}px`;
    card.style.top = `${cy}px`;
  }

  function render() {
    const step = steps[idx];
    if (!step) { stop(); return; }
    root.querySelector(".ob-title").textContent = step.title || "";
    root.querySelector(".ob-body").innerHTML = step.body || "";
    if (step.onRender) step.onRender(root.querySelector(".ob-body"), { rerender: rebuildStep });
    root.querySelector(".ob-count").textContent = `${idx + 1}/${steps.length}`;
    const back = root.querySelector(".ob-back");
    back.textContent = L().back || "← Back";
    back.style.visibility = idx === 0 ? "hidden" : "visible";
    root.querySelector(".ob-next").textContent =
      idx === steps.length - 1 ? (L().done || "Done") : (L().next || "Next →");
    const el = step.center ? null : visibleEl(step.anchor);
    if (el) el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
    position();
    // Re-measure after smooth scroll / card reflow settles.
    requestAnimationFrame(position);
    setTimeout(position, 260);
  }

  // Re-resolve steps (e.g. after a language switch) and redraw in place.
  function rebuildStep() {
    const kept = idx;
    steps = liveSteps();
    if (!steps.length) { stop(); return; }
    idx = Math.min(kept, steps.length - 1);
    render();
  }

  function go(next) {
    if (next < 0) return;
    if (next >= steps.length) { stop(true); return; }
    idx = next;
    render();
  }

  function start() {
    if (activeTour) activeTour.stop();
    steps = liveSteps();
    if (!steps.length) return;
    idx = 0;
    build();
    render();
    activeTour = api;
  }

  function stop(finished) {
    if (activeTour === api) activeTour = null;
    if (!root) return;
    window.removeEventListener("resize", position);
    window.removeEventListener("scroll", position, { capture: true });
    document.removeEventListener("keydown", onKey, true);
    root.remove();
    root = spot = card = null;
    if (config.onStop) config.onStop(!!finished);
  }

  const api = { start, stop, active: () => !!root };
  return api;
}

// Tour buttons live in each page's header (static HTML or a JS-rendered
// template) and are marked with [data-ob-tour]. One document-level click
// delegation survives header re-renders; a decorator interval keeps
// late-rendered buttons titled and pulsing until the tour is used once.
export function initTourButtons(opts) {
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-ob-tour]");
    if (!btn) return;
    ev.preventDefault();
    localStorage.setItem(BTN_SEEN_KEY, "1");
    document.querySelectorAll("[data-ob-tour]").forEach((b) => b.classList.remove("ob-btn-pulse"));
    opts.onClick();
  });
  const decorate = () => {
    const title = typeof opts.title === "function" ? opts.title() : opts.title;
    document.querySelectorAll("[data-ob-tour]").forEach((b) => {
      if (title) { b.title = title; b.setAttribute("aria-label", title); }
      b.classList.toggle("ob-btn-pulse", !localStorage.getItem(BTN_SEEN_KEY));
    });
  };
  decorate();
  setInterval(decorate, 1500);
  // Fallback: if the page has no header button (none rendered within 4 s),
  // mount the old floating one so the tour stays reachable.
  setTimeout(() => {
    if (document.querySelector("[data-ob-tour]")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "ob-btn-float";
    btn.textContent = "?";
    btn.setAttribute("data-ob-tour", "");
    document.body.appendChild(btn);
    decorate();
  }, 4000);
}

// First-visit auto start: waits until `ready()` is true (app loader gone,
// content rendered), then runs `fn` once per storage key.
export function autoStartOnce(key, ready, fn, timeoutMs = 20000) {
  const storageKey = `caravanTourSeen:${key}`;
  if (localStorage.getItem(storageKey)) return;
  const startedAt = Date.now();
  const timer = setInterval(() => {
    if (Date.now() - startedAt > timeoutMs) { clearInterval(timer); return; }
    let ok = false;
    try { ok = ready(); } catch { ok = false; }
    if (!ok) return;
    clearInterval(timer);
    localStorage.setItem(storageKey, "1");
    setTimeout(fn, 600);
  }, 400);
}

export function markTourSeen(key) {
  localStorage.setItem(`caravanTourSeen:${key}`, "1");
}
