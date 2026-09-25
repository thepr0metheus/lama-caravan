// Styled in-app replacements for window.confirm()/window.prompt(): Promise
// wrappers over the shared #confirmOverlay dialog. Native dialogs block the
// renderer and look foreign — nothing in the app should call them directly.
import { ui } from "./state.js";
import { t } from "./i18n.js";
import { $, escapeHtml } from "./utils.js";

let _resolve = null;
let _mode = "confirm";
// The pressed choice of a "prompt-choice" or "confirm-choice" dialog. Every
// dialog that opens resets it — also one opened over a dialog that never
// settled — and only the settle of one of those two reads it.
let _choice = null;

function openDialog(message, opts, mode) {
  return new Promise((resolve) => {
    _resolve = resolve;
    _mode = mode;
    _choice = null;
    // Both prompt modes ask for text; "prompt-choice" also offers choices.
    const asks = mode === "prompt" || mode === "prompt-choice";
    const dlg = $("confirmOverlay").querySelector(".modal");
    dlg.dataset.tone = asks || opts.danger === false ? "ask" : "danger";
    // Scene hint for the animated llama (dialog-llamas.js); falls back by tone.
    if (opts.scene) $("confirmOverlay").dataset.dlgScene = opts.scene;
    else delete $("confirmOverlay").dataset.dlgScene;
    $("confirmTitle").textContent = opts.title || (asks ? message : t("confirmActionTitle"));
    $("confirmText").textContent = asks ? (opts.text || "") : message;
    const meta = $("confirmMeta");
    if (meta) { meta.hidden = true; meta.innerHTML = ""; }
    if (meta && (mode === "prompt-choice" || mode === "confirm-choice")) renderChoices(meta, opts);
    const path = $("confirmPath");
    if (path) path.textContent = opts.detail || "";
    const input = $("confirmInput");
    input.hidden = !asks;
    const hint = $("confirmInputHint");
    if (hint) hint.hidden = true;
    if (asks) {
      // A passphrase must not sit in plain sight, and must not be offered to a
      // password manager as a new credential — this box is a key someone else
      // chose, not an account being created.
      input.type = opts.password ? "password" : "text";
      input.autocomplete = opts.password ? "off" : "";
      input.value = opts.value == null ? "" : String(opts.value);
      input.placeholder = opts.placeholder || "";
      // The placeholder is a suggestion, and Tab takes it: an empty box (or a
      // typed prefix of the suggestion) fills with it and keeps the caret; a box
      // that already holds it, or something else, tabs on as usual. The keycap
      // under the box shows only while the suggestion is on offer.
      const offered = () => !!input.placeholder && input.value !== input.placeholder
        && input.placeholder.startsWith(input.value);
      const syncHint = () => { if (hint) { hint.hidden = !offered(); hint.title = t("promptTabHint"); } };
      input.oninput = syncHint;
      input.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); settleAppConfirm(true); return; }
        if (e.key === "Tab" && !e.shiftKey && offered()) {
          e.preventDefault();
          input.value = input.placeholder;
          if (typeof input.setSelectionRange === "function") input.setSelectionRange(input.value.length, input.value.length);
          syncHint();
        }
      };
      syncHint();
    }
    const btn = $("confirmDelete");
    // The markup carries data-i18n="deleteAction", but this line overwrites the
    // text on every open — so the translated default never survived to be seen.
    // Most callers pass nothing, which is exactly when it mattered.
    btn.textContent = opts.confirmLabel || t("okAction");
    btn.classList.toggle("danger", !asks && opts.danger !== false);
    ui.pendingConfirm = () => settleAppConfirm(true);
    $("confirmOverlay").hidden = false;
    // Move focus into the dialog: the input for prompts, Cancel for dangerous
    // confirms (safe default), the confirm button otherwise.
    requestAnimationFrame(() => {
      if (asks) { input.focus(); input.select(); }
      else if (dlg.dataset.tone === "danger") $("confirmCancel").focus();
      else btn.focus();
    });
  });
}

// The choices of a "prompt-choice" or "confirm-choice" dialog: one pressed at
// a time, as radio buttons are; opts.choice is pressed first, else the first
// one. opts.list lays a long list out as a column that scrolls.
function renderChoices(meta, opts) {
  const choices = Array.isArray(opts.choices) ? opts.choices : [];
  if (!choices.length) return;
  const first = choices.some((c) => String(c.value) === String(opts.choice)) ? String(opts.choice) : String(choices[0].value);
  _choice = first;
  meta.hidden = false;
  meta.innerHTML = `<div class="dlg-choices${opts.list ? " dlg-choices-list" : ""}" role="radiogroup" aria-label="${escapeHtml(opts.choiceLabel || "")}">`
    + (opts.choiceLabel ? `<span class="dlg-choices-label">${escapeHtml(opts.choiceLabel)}</span>` : "")
    + choices.map((c) => `<button type="button" class="dlg-choice" role="radio" data-t="confirm-choice"
        data-t-id="${escapeHtml(String(c.value))}" data-choice="${escapeHtml(String(c.value))}"
        aria-checked="${String(c.value) === first}">${escapeHtml(c.label)}</button>`).join("")
    + "</div>";
  const buttons = [...meta.querySelectorAll("[data-choice]")];
  buttons.forEach((b) => {
    b.onclick = () => {
      _choice = b.dataset.choice;
      buttons.forEach((x) => x.setAttribute("aria-checked", String(x === b)));
    };
  });
}

export function appConfirm(message, opts = {}) {
  return openDialog(message, opts, "confirm");
}

// (A mode whose answer is one of several buttons — appChoose — served one
// question: where a controller cell's start reads its model from. The question
// went with the controller's cells in step 6.9, and the mode with it. A prompt
// that also offers choices — appPromptChoice, below — answers text AND a choice;
// its buttons are choices inside the dialog, not answers that close it.)

// window.prompt() replacement: resolves the entered string, or null on cancel.
// The message becomes the dialog title (native prompts have no separate body);
// opts.value prefills the input, opts.placeholder/text are optional extras.
export function appPrompt(message, opts = {}) {
  return openDialog(message, opts, "prompt");
}

// A prompt that also asks one of several choices — an engine model's load:
// its window, and how long it stays unused (docs/foreign-engines.md, 3б).
// opts.choices: [{value, label}], opts.choice: pressed first, opts.choiceLabel:
// what they choose. Resolves {value, choice} — the text and the pressed
// choice's value as a string — or null on cancel.
export function appPromptChoice(message, opts = {}) {
  return openDialog(message, opts, "prompt-choice");
}

// A confirm that also asks one of several choices — where a new cell runs, and
// for an engine the model it holds (docs/foreign-engines.md, cells in engines).
// The same opts as appPromptChoice, without the text. Resolves the pressed
// choice's value as a string, or null on cancel.
export function appConfirmChoice(message, opts = {}) {
  return openDialog(message, opts, "confirm-choice");
}

// Resolve the pending dialog (ok=true → confirmed / input submitted). Returns
// whether one was pending — closeConfirmModal calls this first so Cancel/
// Escape/overlay-click resolve the promise instead of leaving it hanging.
export function settleAppConfirm(ok) {
  const resolve = _resolve;
  _resolve = null;
  const value = _mode === "prompt" ? (ok ? $("confirmInput").value : null)
    : _mode === "prompt-choice" ? (ok ? { value: $("confirmInput").value, choice: _choice } : null)
      : _mode === "confirm-choice" ? (ok ? _choice : null)
      : !!ok;
  _mode = "confirm";
  $("confirmOverlay").hidden = true;
  $("confirmInput").hidden = true;
  const hint = $("confirmInputHint");
  if (hint) hint.hidden = true;
  const meta = $("confirmMeta");
  if (meta) { meta.hidden = true; meta.innerHTML = ""; }
  $("confirmDelete").classList.remove("danger");
  // Legacy openers (backup delete, service action, save/restart) write the
  // dialog fields directly and expect the destructive look.
  $("confirmOverlay").querySelector(".modal").dataset.tone = "danger";
  ui.pendingConfirm = null;
  if (!resolve) return false;
  resolve(value);
  return true;
}
