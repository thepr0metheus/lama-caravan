// Language + theme: t(), applyLanguage/applyTheme, the language dropdown.
import { option } from "./form.js";
import { LANGS, messages } from "./i18n-data.js";
import { renderAll, renderTopology } from "./topology-render.js";
import { $, escapeHtml } from "./utils.js";

// Language options for the dropdown. `emoji` is a country-flavoured glyph
// (not a flag) — swap these freely; add a new entry to support more languages.
// Strings without a translation in `messages` fall back to English (see t()).
// Order: the 20 most-spoken languages worldwide.
export let lang = localStorage.getItem("llamacppAdminLang") || "en";
export let theme = localStorage.getItem("llamacppAdminTheme") || "dark";
export function t(key, vars = {}) {
  let text = messages[lang]?.[key] || messages.en[key] || key;
  Object.entries(vars).forEach(([name, value]) => {
    text = text.replace(`{${name}}`, value);
  });
  return text;
}

// Programmatic language switch (used by the onboarding tour's picker).
// On the standalone kanban page renderAll() would touch board-only DOM,
// so re-render only what exists there.
export function setLang(code) {
  if (!code || code === lang || !LANGS.some((l) => l.code === code)) return;
  lang = code;
  localStorage.setItem("llamacppAdminLang", lang);
  if (window.ROUTER_STANDALONE) {
    applyLanguage();
    renderTopology();
  } else {
    renderAll();
  }
}

export function fieldHelp(field) {
  return messages[lang]?.fieldHelp?.[field] || messages.en.fieldHelp[field] || "";
}

export function labelWithTip(field) {
  const help = fieldHelp(field);
  return `
    <div class="label-row">
      <label for="${field}">${field}</label>
      <button class="tip-trigger" type="button" data-fieldhelp="${field}" aria-label="${field}: ${help}">
        ?
        <span class="tooltip" role="tooltip">${help}</span>
      </button>
    </div>
  `;
}

export function applyTheme() {
  document.documentElement.dataset.theme = theme;
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    button.classList.toggle("active", button.dataset.themeChoice === theme);
  });
}

export function applyLanguage() {
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-title-i18n]").forEach((el) => {
    const text = t(el.dataset.titleI18n);
    el.title = text;
    el.setAttribute("aria-label", text);
  });
  // Dynamic (?) tooltips are built with fieldHelp()/t() at render time, not via
  // [data-i18n] (which would overwrite the whole element, wiping the "?" glyph
  // and the tooltip). Refresh their text + aria IN PLACE so switching language
  // updates an OPEN cell editor without rebuilding its inputs (that would drop
  // unsaved edits). Field NAMES stay as the raw env-var keys, by design.
  document.querySelectorAll("[data-fieldhelp]").forEach((el) => {
    const key = el.dataset.fieldhelp;
    const help = fieldHelp(key);
    const tip = el.querySelector(".tooltip");
    if (tip) tip.textContent = help;
    el.setAttribute("aria-label", `${key}: ${help}`);
  });
  document.querySelectorAll("[data-fieldhelp-text]").forEach((el) => {
    el.textContent = fieldHelp(el.dataset.fieldhelpText);
  });
  document.querySelectorAll("[data-i18n-tip]").forEach((el) => {
    const text = t(el.dataset.i18nTip);
    const tip = el.querySelector(".tooltip");
    if (tip) tip.textContent = text;
    el.setAttribute("aria-label", text);
  });
  // Composed texts (a key + runtime params, e.g. the cell-editor title with the
  // server name, or the state-dependent Apply/Restart button) cannot be
  // re-rendered from a data attribute — modules listen for this event and
  // refresh their own pieces if visible.
  window.dispatchEvent(new CustomEvent("caravan:langchange"));
  renderLangSelect();
}

// Build/refresh the language dropdown to reflect the current `lang`.
export function renderLangSelect() {
  const current = LANGS.find((l) => l.code === lang) || LANGS[0];
  const emoji = document.getElementById("langTriggerEmoji");
  const code = document.getElementById("langTriggerCode");
  if (emoji) emoji.textContent = current.emoji;
  if (code) code.textContent = current.code.toUpperCase();
  const menu = document.getElementById("langMenu");
  if (!menu) return;
  menu.innerHTML = LANGS.map((l) => {
    const selected = l.code === lang;
    return `<li class="lang-option${selected ? " selected" : ""}" role="option"`
      + ` data-lang="${l.code}" aria-selected="${selected}">`
      + `<span class="lang-emoji">${l.emoji}</span>`
      + `<span class="lang-name">${l.label}</span></li>`;
  }).join("");
}

// Wire up the language dropdown: open/close, pick an option, dismiss on
// outside-click or Escape.
export function setupLangSelect() {
  const root = document.getElementById("langSelect");
  const trigger = document.getElementById("langTrigger");
  const menu = document.getElementById("langMenu");
  if (!root || !trigger || !menu) return;
  const close = () => {
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  };
  const open = () => {
    menu.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
  };
  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    menu.hidden ? open() : close();
  });
  menu.addEventListener("click", (e) => {
    const option = e.target.closest(".lang-option");
    if (!option) return;
    close();
    setLang(option.dataset.lang);
  });
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !root.contains(e.target)) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !menu.hidden) close();
  });
  renderLangSelect();
}

export function helpTip(key) {
  const text = t(key);
  return `
    <span class="inline-tip help-tip" tabindex="0" data-i18n-tip="${key}" aria-label="${escapeHtml(text)}">
      ?
      <span class="tooltip" role="tooltip">${escapeHtml(text)}</span>
    </span>
  `;
}

