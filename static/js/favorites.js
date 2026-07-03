// Starred launch-form fields: the Favorites tab mirror + drag reorder.
import { readConfigForm, syncToggleLabel } from "./form.js";
import { fieldHelp, t } from "./i18n.js";
import { state } from "./state.js";
import { $, api, escapeHtml, toast } from "./utils.js";

// ── Favorites: a personal set of starred fields mirrored into the first tab ──
// The set is global (same across all launch forms) and persisted server-side
// via /api/config-favorites. Canonical inputs stay in their home tabs (they are
// what readConfigForm/preview read); the Favorites tab shows lightweight proxy
// controls that two-way-sync with the canonical input by dispatching its events.
export function getFavFields() {
  return Array.isArray(state?.favFields) ? state.favFields : [];
}

export function isFav(field) {
  return getFavFields().includes(field);
}

export async function toggleFavorite(field, pfx = "") {
  const cur = getFavFields().slice();
  const i = cur.indexOf(field);
  if (i >= 0) cur.splice(i, 1); else cur.push(field);
  if (state) state.favFields = cur;
  refreshFavoritesPanel(pfx);
  updateStarStates(pfx);
  try {
    await api("/api/config-favorites", { method: "POST", body: JSON.stringify({ favorites: cur }) });
  } catch (err) {
    toast(err.message);
  }
}

// Star button injected into a field's .label-row (canonical fields and mirrors).
export function attachFavStar(div, field, pfx, alwaysOn = false) {
  const row = div.querySelector(".label-row");
  if (!row) return;
  const star = document.createElement("button");
  star.type = "button";
  star.className = "fav-star" + ((alwaysOn || isFav(field)) ? " is-fav" : "");
  star.dataset.favField = field;
  star.textContent = "★";
  star.title = t("favStarTip");
  star.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    toggleFavorite(field, pfx);
  });
  row.appendChild(star);
}

// Reflect the current favorite set onto every canonical field's star icon.
export function updateStarStates(pfx = "") {
  const wrap = $(pfx + "dynamicFields");
  if (!wrap) return;
  const favs = new Set(getFavFields());
  wrap.querySelectorAll('.fav-star[data-fav-field]').forEach((s) => {
    // Mirror stars (inside the fav panel) stay lit; only update canonical ones.
    if (s.closest('[data-adv-panel="fav"]')) return;
    s.classList.toggle("is-fav", favs.has(s.dataset.favField));
  });
}

// A proxy control bound to the canonical input $(pfx+field). Edits are forwarded
// by dispatching the canonical's native events, so all existing wiring (toggle
// labels, model insight, command preview, dirty tracking) fires unchanged.
export function renderFavoriteMirror(field, pfx = "") {
  const canonical = $(pfx + field);
  const div = document.createElement("div");
  div.className = "field";
  div.dataset.favField = field;  // drop-target identity for drag-reorder
  const help = fieldHelp(field);
  const favId = pfx + "fav-" + field;
  const dragHandle = `<button class="fav-drag-handle" type="button" draggable="true" title="Drag to reorder" aria-label="Reorder">⠿</button>`;
  const labelRow = `<div class="label-row">${dragHandle}<label for="${favId}">${field}</label><button class="tip-trigger" type="button" aria-label="${field}: ${escapeHtml(help)}">?<span class="tooltip" role="tooltip">${escapeHtml(help)}</span></button></div>`;
  if (!canonical) {
    div.innerHTML = labelRow;
    attachFavStar(div, field, pfx, true);
    return div;
  }
  if (canonical.type === "checkbox") {
    const checked = canonical.checked;
    div.innerHTML = `${labelRow}<label class="check-row" for="${favId}"><input id="${favId}" type="checkbox" ${checked ? "checked" : ""}><span>${checked ? t("enabled") : t("disabled")}</span></label><p>${help}</p>`;
    const inp = div.querySelector("input");
    syncToggleLabel(inp);
    inp.addEventListener("change", () => {
      canonical.checked = inp.checked;
      canonical.dispatchEvent(new Event("change", { bubbles: true }));
      syncToggleLabel(inp);
    });
  } else {
    div.innerHTML = `${labelRow}<input id="${favId}" value="${escapeHtml(canonical.value)}"><p>${help}</p>`;
    const inp = div.querySelector("input");
    inp.addEventListener("input", () => {
      canonical.value = inp.value;
      canonical.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  attachFavStar(div, field, pfx, true);
  return div;
}

// Rebuild the Favorites panel content from the current favorite set.
export function refreshFavoritesPanel(pfx = "") {
  const wrap = $(pfx + "dynamicFields");
  if (!wrap) return;
  // Only the dynamic mirrors area is rebuilt — the pinned EXTRA_ARGS box above
  // it is left intact so unsaved text there survives star toggles.
  const mirrors = wrap.querySelector('[data-adv-panel="fav"] .fav-mirrors');
  if (!mirrors) return;
  mirrors.innerHTML = "";
  const favs = getFavFields().filter((f) => f !== "EXTRA_ARGS" && $(pfx + f));
  if (!favs.length) {
    mirrors.innerHTML = `<div class="fav-empty">${escapeHtml(t("favEmptyHint"))}</div>`;
    return;
  }
  const grid = document.createElement("div");
  grid.className = "advanced-grid";
  favs.forEach((field) => grid.appendChild(renderFavoriteMirror(field, pfx)));
  mirrors.appendChild(grid);
  wireFavoriteDnd(grid, pfx);
}

// Drag-to-reorder the Favorites tab. Only the mirror cells are draggable (via a
// grip handle so the inputs stay editable); EXTRA_ARGS is pinned above and never
// part of this grid. Order lives in the global favFields array, which already
// persists via /api/config-favorites — so a drop just reorders + re-saves.
export function wireFavoriteDnd(grid, pfx = "") {
  const cells = [...grid.querySelectorAll(".field[data-fav-field]")];
  const clearMarks = () => cells.forEach((c) => c.classList.remove("drop-before", "drop-after", "dragging"));
  cells.forEach((cell) => {
    const handle = cell.querySelector(".fav-drag-handle");
    if (handle) {
      handle.addEventListener("dragstart", (e) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", cell.dataset.favField);
        cell.classList.add("dragging");
        try { e.dataTransfer.setDragImage(cell, 12, 12); } catch {}
      });
      handle.addEventListener("dragend", clearMarks);
    }
    cell.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      const rect = cell.getBoundingClientRect();
      const after = (e.clientX - rect.left) > rect.width / 2;
      cell.classList.toggle("drop-after", after);
      cell.classList.toggle("drop-before", !after);
    });
    cell.addEventListener("dragleave", () => cell.classList.remove("drop-before", "drop-after"));
    cell.addEventListener("drop", (e) => {
      e.preventDefault();
      const source = e.dataTransfer.getData("text/plain");
      const rect = cell.getBoundingClientRect();
      const after = (e.clientX - rect.left) > rect.width / 2;
      clearMarks();
      reorderFavorites(source, cell.dataset.favField, after, pfx);
    });
  });
}

export async function reorderFavorites(sourceField, targetField, insertAfter, pfx = "") {
  if (!sourceField || sourceField === targetField) return;
  const cur = getFavFields().slice();
  const si = cur.indexOf(sourceField);
  if (si === -1 || cur.indexOf(targetField) === -1) return;
  cur.splice(si, 1);
  const ti = cur.indexOf(targetField);
  cur.splice(ti + (insertAfter ? 1 : 0), 0, sourceField);
  if (state) state.favFields = cur;
  refreshFavoritesPanel(pfx);
  try {
    await api("/api/config-favorites", { method: "POST", body: JSON.stringify({ favorites: cur }) });
  } catch (err) {
    toast(err.message);
  }
}

// Copy canonical values into the mirrors (called when the Favorites tab opens).
export function syncFavoriteMirrors(pfx = "") {
  getFavFields().forEach((field) => {
    const c = $(pfx + field);
    const m = $(pfx + "fav-" + field);
    if (!c || !m) return;
    if (c.type === "checkbox") { m.checked = c.checked; syncToggleLabel(m); }
    else { m.value = c.value; }
  });
}

