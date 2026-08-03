// DOM/format/HTTP helpers with zero app-state and zero i18n dependencies
// (hf.js imports from here — keep this module free of i18n-data).

export function $(id) {
  return document.getElementById(id);
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** Fill the header's version chip from /health.
 *
 *  The richer label — version PLUS git branch and dirty count — comes from
 *  renderProjectGitBranch(), which needs /api/state. Pages that never fetch
 *  the fleet state (/models, the standalone kanban) were left showing the
 *  placeholder "branch n/a", which is worse than an empty chip: it reads as a
 *  fact about the checkout rather than as "nobody asked". /health is open and
 *  costs nothing, so those pages can at least say which build they are.
 *  Where state does arrive, renderProjectGitBranch() overwrites this.
 */
export function fillVersionChipFromHealth() {
  const el = $("projectGitBranch");
  if (!el) return;
  fetch("/health").then((r) => r.json()).then((d) => {
    if (!d || !d.version || el.textContent.includes("git:")) return;
    el.textContent = `v${d.version}`;
    el.title = `lama-caravan v${d.version}${d.commit ? ` @ ${d.commit}` : ""}`;
  }).catch(() => {});
}

export async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    // Session expired / auth just enabled: hand the user to the login page
    // (auth endpoints handle their own errors inline).
    if (response.status === 401 && !path.startsWith("/api/auth/")
        && location.pathname !== "/login") {
      window.location = "/login";
    }
    throw new Error(data.error || response.statusText);
  }
  return data;
}

export function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3200);
}

export function pill(text, kind) {
  return `<span class="pill ${kind || ""}">${text}</span>`;
}

// Clipboard with a plain-http fallback: navigator.clipboard needs a secure
// context, but the LAN UI usually runs on http:// — the legacy
// textarea+execCommand path still works there. Resolves true only when the
// text actually landed in the clipboard.
export async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return true; } catch { /* fall through */ }
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { /* stays false */ }
  ta.remove();
  return ok;
}

export function formatBool(value) {
  return ["1", "true", "yes", "on"].includes(String(value).toLowerCase());
}

export function formatBytesMiB(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return value || "";
  return `${Math.round(n)} MiB`;
}

export function formatMemoryMiB(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return value || "";
  if (n >= 1024) return `${(n / 1024).toFixed(n >= 10240 ? 1 : 2)} GB`;
  return `${Math.round(n)} MiB`;
}

export function positionTooltip(trigger) {
  const tooltip = trigger?.querySelector?.(".tooltip");
  if (!tooltip) return;
  const rect = trigger.getBoundingClientRect();
  const vw = window.innerWidth || document.documentElement.clientWidth || 1024;
  const pad = 12;
  const width = Math.min(tooltip.offsetWidth || 320, vw - pad * 2);
  const height = tooltip.offsetHeight || 80;
  let left = rect.left + rect.width / 2;
  left = Math.max(pad + width / 2, Math.min(vw - pad - width / 2, left));
  let top = rect.top - 8;
  const below = top - height < pad;
  if (below) top = rect.bottom + 8;
  tooltip.style.setProperty("--tooltip-left", `${Math.round(left)}px`);
  tooltip.style.setProperty("--tooltip-top", `${Math.round(top)}px`);
  tooltip.classList.toggle("below", below);
}

export function bindTooltips() {
  document.addEventListener("pointerover", (event) => {
    const trigger = event.target.closest?.(".tip-trigger, .inline-tip");
    if (trigger) positionTooltip(trigger);
  });
  document.addEventListener("focusin", (event) => {
    const trigger = event.target.closest?.(".tip-trigger, .inline-tip");
    if (trigger) positionTooltip(trigger);
  });
  window.addEventListener("resize", () => {
    document.querySelectorAll(".tip-trigger:hover, .inline-tip:hover, .tip-trigger:focus, .inline-tip:focus").forEach(positionTooltip);
  });
}


// ── Page readiness, for automation ───────────────────────────────────────────
// Pages fill from /api/* after first paint, so "the DOM exists" and "the data
// arrived" are different moments. Without a signal, anything driving this UI —
// a test, a screenshot job — has to guess which it is looking at, and guessing
// is how a suite becomes the kind that fails one run in ten and gets ignored.
//
// ONE flag on <body>, not one per container: every page here has a single
// first load that fills it, so a per-container version would be more moving
// parts saying the same thing.
//
//   data-t-state="loading"  set in the HTML, before any script runs
//                 "ready"   first load arrived and rendered
//                 "error"   first load FAILED — and this is the point: a page
//                           stuck at "loading" forever makes a waiter time out
//                           slowly with no reason; "error" fails it at once,
//                           with the cause in aria-label.
export function markPageState(state, detail = "") {
  const b = document.body;
  if (!b) return;
  b.dataset.tState = state;
  if (detail) b.dataset.tStateDetail = String(detail).slice(0, 200);
  else delete b.dataset.tStateDetail;
  b.setAttribute("aria-busy", state === "loading" ? "true" : "false");
}
