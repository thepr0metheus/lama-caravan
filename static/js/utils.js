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

export async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
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

