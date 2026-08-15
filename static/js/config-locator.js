// Finding a setting among eleven tabs: hover a flag in the command preview to
// light up the tab and input that produced it, or search by name, flag or help
// text and jump straight to it.
//
// Neither direction keeps its own list of settings, because a list is a thing
// that can be forgotten — and a forgotten field looks exactly like a field with
// nothing to say, which is the failure this codebase keeps rediscovering.
// Instead:
//   * the searchable set is the server's own CONFIG_FIELDS, narrowed to those
//     with a live input (id = pfx + FIELD) in this editor;
//   * a token's owning field is measured server-side per request
//     (command_token_owners) and arrives as data-cmd-field;
//   * the tab a field sits on comes from the same advancedGroups/advancedTabDefs
//     that render the tabs.
// So a field added tomorrow is searchable and highlightable by virtue of being
// rendered at all. scripts/check_field_homes.py closes the last gap: a field
// with no group has no tab to be pointed at, and CI refuses it.
import { advancedGroups, advancedTabDefs } from "./constants.js";
import { fieldHelp, t } from "./i18n.js";
import { state } from "./state.js";
import { $, escapeHtml } from "./utils.js";

// field -> { tabIndex, tabKey, groupKey }, built from the same tables that
// render the tabs.
export function fieldLocations() {
  const map = new Map();
  advancedTabDefs.forEach((tab, tabIndex) => {
    tab.groups.forEach((groupKey) => {
      const group = advancedGroups.find((g) => g.titleKey === groupKey);
      (group?.fields || []).forEach((field) => {
        if (!map.has(field)) map.set(field, { tabIndex, tabKey: tab.key, groupKey });
      });
    });
  });
  return map;
}

function tabsRoot(pfx) {
  const host = $(pfx + "dynamicFields");
  return {
    bar: host?.querySelector(".advanced-tab-bar") || null,
    body: host?.querySelector(".advanced-tab-body") || null,
  };
}

// Switch to a tab by index, mirroring what the tab-bar click handler does.
export function activateTab(pfx, idx) {
  const { bar, body } = tabsRoot(pfx);
  if (!bar || !body) return;
  const key = String(idx);
  bar.querySelectorAll(".advanced-tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.advTab === key));
  body.querySelectorAll(".advanced-tab-panel").forEach((p) => p.classList.toggle("active", p.dataset.advPanel === key));
  const btn = bar.querySelector(`[data-adv-tab="${key}"]`);
  btn?.scrollIntoView({ block: "nearest", inline: "nearest" });
  bar.dispatchEvent(new Event("scroll"));
}

// Locate by the canonical input id (pfx + FIELD) rather than by a marker
// attribute: MODEL_FILE, MMPROJ_FILE and the runner panels live in static HTML
// that renderField never touches, and a marker they lack is a setting the
// search silently cannot find. Every config input carries this id already, so
// nothing has to be remembered for a new field to be locatable.
function fieldInput(pfx, field) {
  return $(pfx + field) || null;
}

function fieldEl(pfx, field) {
  return fieldInput(pfx, field)?.closest(".field") || null;
}

// Present in this editor at all? Runner panels (vLLM, whisper) and the
// llama-only tabs are mutually exclusive, so the index must follow the DOM.
function fieldPresent(pfx, field) {
  return !!fieldInput(pfx, field);
}

// Light the tab a field lives on without moving the operator off the tab they
// are on — hovering a flag should tell you where it is, not navigate for you.
export function markFieldTab(pfx, field) {
  clearMarks(pfx);
  if (!field) return;
  const loc = fieldLocations().get(field);
  const { bar } = tabsRoot(pfx);
  if (loc && bar) bar.querySelector(`[data-adv-tab="${loc.tabIndex}"]`)?.classList.add("tab-located");
  fieldEl(pfx, field)?.classList.add("field-located");
}

export function clearMarks(pfx) {
  // Field marks are cleared document-wide: MODEL_FILE and the mmproj row live
  // in static markup outside dynamicFields, and a mark scoped to the tab host
  // would be lit with no way to put it out.
  document.querySelectorAll(".tab-located, .field-located").forEach((el) => {
    el.classList.remove("tab-located", "field-located");
  });
}

// Go to a field: switch tab, scroll it into view, flash it.
export function revealField(pfx, field) {
  const loc = fieldLocations().get(field);
  if (loc) activateTab(pfx, loc.tabIndex);
  const el = fieldEl(pfx, field);
  if (!el) return false;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  el.classList.remove("field-flash");
  void el.offsetWidth;                      // restart the animation on re-pick
  el.classList.add("field-flash");
  setTimeout(() => el.classList.remove("field-flash"), 1600);
  markFieldTab(pfx, field);
  el.querySelector("input, select, textarea")?.focus({ preventScroll: true });
  return true;
}

// ── hovering the command preview ────────────────────────────────────────────
export function bindCommandLocator(pfx) {
  const target = $(pfx + "previewCmdline");
  if (!target || target.dataset.locatorBound) return;
  target.dataset.locatorBound = "1";
  target.addEventListener("mouseover", (e) => {
    const tok = e.target.closest("[data-cmd-field]");
    if (!tok) return;
    markFieldTab(pfx, tok.dataset.cmdField);
  });
  target.addEventListener("mouseleave", () => clearMarks(pfx));
  target.addEventListener("click", (e) => {
    const tok = e.target.closest("[data-cmd-field]");
    if (!tok) return;
    revealField(pfx, tok.dataset.cmdField);
  });
}

// ── the search box above the tabs ───────────────────────────────────────────
// The index is the set of fields actually rendered for this editor — taken
// from the server's own field list, not from a UI-side copy of it. A field
// added to CONFIG_FIELDS and given an input is searchable the same day; one
// that exists only on the server is correctly absent.
function searchIndex(pfx) {
  const flags = (state?.fieldFlags && typeof state.fieldFlags === "object") ? state.fieldFlags : {};
  const locations = fieldLocations();
  const all = Array.isArray(state?.fields) ? state.fields : [...locations.keys()];
  return all.filter((field) => fieldPresent(pfx, field)).map((field) => {
    const loc = locations.get(field);
    return {
      field,
      tabKey: loc?.tabKey || "",
      tabIndex: loc ? loc.tabIndex : -1,
      flags: flags[field] || [],
      help: fieldHelp(field),
    };
  });
}

function scoreEntry(entry, query) {
  const q = query.toLowerCase();
  const name = entry.field.toLowerCase();
  if (name === q) return 100;
  if (name.startsWith(q)) return 80;
  if (entry.flags.some((f) => f.toLowerCase() === q)) return 75;
  if (entry.flags.some((f) => f.toLowerCase().includes(q))) return 60;
  if (name.includes(q)) return 50;
  if (entry.help.toLowerCase().includes(q)) return 20;
  return 0;
}

export function renderConfigSearch(pfx) {
  const wrap = document.createElement("div");
  wrap.className = "config-search";
  const input = document.createElement("input");
  input.type = "search";
  input.className = "config-search-input";
  input.autocomplete = "off";
  input.placeholder = t("configSearchPlaceholder");
  input.dataset.i18nPlaceholder = "configSearchPlaceholder";
  input.setAttribute("data-t", "cell-config-search");
  const results = document.createElement("div");
  results.className = "config-search-results";
  results.hidden = true;
  results.setAttribute("data-t", "cell-config-search-results");
  wrap.appendChild(input);
  wrap.appendChild(results);

  let matches = [];
  let cursor = -1;

  const paint = () => {
    results.querySelectorAll(".config-search-hit").forEach((el, i) => {
      el.classList.toggle("active", i === cursor);
    });
  };

  const close = () => {
    results.hidden = true;
    results.innerHTML = "";
    matches = [];
    cursor = -1;
    clearMarks(pfx);
  };

  const search = () => {
    const q = input.value.trim();
    if (!q) return close();
    matches = searchIndex(pfx)
      .map((entry) => ({ entry, score: scoreEntry(entry, q) }))
      .filter((m) => m.score > 0)
      .sort((a, b) => b.score - a.score || a.entry.field.localeCompare(b.entry.field))
      .slice(0, 12)
      .map((m) => m.entry);
    cursor = matches.length ? 0 : -1;
    if (!matches.length) {
      results.innerHTML = `<div class="config-search-empty">${escapeHtml(t("configSearchEmpty"))}</div>`;
      results.hidden = false;
      return;
    }
    results.innerHTML = matches.map((entry, i) => `
      <button type="button" class="config-search-hit${i === 0 ? " active" : ""}"
              data-t="cell-config-search-hit" data-t-id="${escapeHtml(entry.field)}" data-hit="${i}">
        <span class="hit-head">
          <span class="hit-field">${escapeHtml(entry.field)}</span>
          ${entry.flags.length ? `<code class="hit-flag">${escapeHtml(entry.flags[0])}</code>` : ""}
          ${entry.tabKey ? `<span class="hit-tab">${escapeHtml(t(entry.tabKey))}</span>` : ""}
        </span>
        <span class="hit-help">${escapeHtml(entry.help)}</span>
      </button>`).join("");
    results.hidden = false;
    // Light the top hit's tab straight away — the answer to "where is it?"
    // should be visible before anything is clicked.
    markFieldTab(pfx, matches[0].field);
  };

  const pick = (i) => {
    const entry = matches[i];
    if (!entry) return;
    revealField(pfx, entry.field);
    results.hidden = true;
  };

  input.addEventListener("input", search);
  input.addEventListener("focus", () => { if (input.value.trim()) search(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { input.value = ""; close(); input.blur(); return; }
    if (!matches.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      cursor = (cursor + (e.key === "ArrowDown" ? 1 : matches.length - 1)) % matches.length;
      paint();
      markFieldTab(pfx, matches[cursor].field);
      results.querySelector(".config-search-hit.active")?.scrollIntoView({ block: "nearest" });
      return;
    }
    if (e.key === "Enter") { e.preventDefault(); pick(cursor); }
  });
  results.addEventListener("mouseover", (e) => {
    const hit = e.target.closest("[data-hit]");
    if (!hit) return;
    cursor = Number(hit.dataset.hit);
    paint();
    markFieldTab(pfx, matches[cursor]?.field);
  });
  results.addEventListener("click", (e) => {
    const hit = e.target.closest("[data-hit]");
    if (hit) pick(Number(hit.dataset.hit));
  });
  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) results.hidden = true;
  });

  return wrap;
}
