// Styled in-app replacements for window.confirm()/window.prompt(): Promise
// wrappers over the shared #confirmOverlay dialog. Native dialogs block the
// renderer and look foreign — nothing in the app should call them directly.
import { ui } from "./state.js";
import { t } from "./i18n.js";
import { $, escapeHtml } from "./utils.js";

let _resolve = null;
let _mode = "confirm";
// The pressed choice of a "confirm-choice" dialog. Every dialog that opens
// resets it — also one opened over a dialog that never settled — and only a
// "confirm-choice" settle reads it.
let _choice = null;
// The ticks of a "confirm-checks" dialog: the "all" box, and the values ticked,
// in the order the dialog lists them. Reset by every dialog that opens, read
// only by a "confirm-checks" settle — as _choice is.
let _checks = null;
// The words a "confirm-typed" dialog waits for, or null for any other dialog. Reset by every dialog that
// opens, read by the box's typing, by Enter and by the settle itself: the gate is in one place, so a click, a key
// or a call of `ui.pendingConfirm` cannot get past it.
let _must = null;

const typedMatches = (value) => _must !== null && String(value).trim() === _must;

function openDialog(message, opts, mode) {
  return new Promise((resolve) => {
    _resolve = resolve;
    _mode = mode;
    _choice = null;
    _checks = null;
    _must = mode === "confirm-typed" ? String(opts.must ?? "") : null;
    // A prompt asks for text; a "confirm-choice" offers choices instead.
    const asks = mode === "prompt";
    const dlg = $("confirmOverlay").querySelector(".modal");
    dlg.dataset.tone = asks || opts.danger === false ? "ask" : "danger";
    // Scene hint for the animated llama (dialog-llamas.js); falls back by tone.
    if (opts.scene) $("confirmOverlay").dataset.dlgScene = opts.scene;
    else delete $("confirmOverlay").dataset.dlgScene;
    $("confirmTitle").textContent = opts.title || (asks ? message : t("confirmActionTitle"));
    $("confirmText").textContent = asks ? (opts.text || "") : message;
    const meta = $("confirmMeta");
    if (meta) { meta.hidden = true; meta.innerHTML = ""; }
    if (meta && mode === "confirm-choice") renderChoices(meta, opts);
    if (meta && mode === "confirm-checks") renderChecks(meta, opts);
    const path = $("confirmPath");
    if (path) path.textContent = opts.detail || "";
    const input = $("confirmInput");
    const btn = $("confirmDelete");
    btn.disabled = false;
    input.hidden = !(asks || _must !== null);
    const hint = $("confirmInputHint");
    if (hint) hint.hidden = true;
    if (_must !== null) {
      // Not a password, and no suggestion to Tab into: the words are TYPED. They stand above the box (opts.detail,
      // set by the caller); the box asks for them, and the confirm button stays off until they are there.
      input.type = "text";
      input.autocomplete = "off";
      input.value = "";
      input.placeholder = opts.placeholder || t("confirmTypeName");
      const sync = () => { btn.disabled = !typedMatches(input.value); };
      input.oninput = sync;
      input.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); if (typedMatches(input.value)) settleAppConfirm(true); }
      };
      sync();
    } else if (asks) {
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
    // The markup carries data-i18n="deleteAction", but this line overwrites the
    // text on every open — so the translated default never survived to be seen.
    // Most callers pass nothing, which is exactly when it mattered.
    btn.textContent = opts.confirmLabel || t("okAction");
    btn.classList.toggle("danger", !asks && opts.danger !== false);
    // "Cancel", unless the dialog says what not answering means ("Not now").
    $("confirmCancel").textContent = opts.cancelLabel || t("cancel");
    ui.pendingConfirm = () => settleAppConfirm(true);
    $("confirmOverlay").hidden = false;
    // Move focus into the dialog: the input for prompts, Cancel for dangerous
    // confirms (safe default), the confirm button otherwise.
    requestAnimationFrame(() => {
      if (asks || _must !== null) { input.focus(); input.select(); }
      else if (dlg.dataset.tone === "danger") $("confirmCancel").focus();
      else btn.focus();
    });
  });
}

// The choices of a "confirm-choice" dialog: one pressed at
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

// The boxes of a "confirm-checks" dialog: any number ticked. opts.allLabel puts a first
// box that stands for all of them, the ones added later too; ticked, it greys the others
// out. opts.checked is "all" or the values ticked first; opts.emptyLabel says what an
// empty list means, so a dialog with nothing to tick does not look broken.
function renderChecks(meta, opts) {
  const choices = Array.isArray(opts.choices) ? opts.choices : [];
  const first = opts.checked === "all" ? [] : (Array.isArray(opts.checked) ? opts.checked : []).map(String);
  _checks = { all: opts.checked === "all" && !!opts.allLabel, picked: new Set(first), order: choices.map((c) => String(c.value)) };
  meta.hidden = false;
  const box = (attrs, label, on, off) => `<label class="dlg-check"><input type="checkbox" ${attrs}${on ? " checked" : ""}${off ? " disabled" : ""}><span>${escapeHtml(label)}</span></label>`;
  meta.innerHTML = `<div class="dlg-checks" role="group" aria-label="${escapeHtml(opts.choiceLabel || "")}">`
    + (opts.choiceLabel ? `<span class="dlg-choices-label">${escapeHtml(opts.choiceLabel)}</span>` : "")
    + (opts.allLabel ? box(`data-check-all data-t="confirm-check-all"`, opts.allLabel, _checks.all, false) : "")
    + choices.map((c) => box(`data-check="${escapeHtml(String(c.value))}" data-t="confirm-check" data-t-id="${escapeHtml(String(c.value))}"`,
      c.label, _checks.all || _checks.picked.has(String(c.value)), _checks.all)).join("")
    + (choices.length ? "" : `<span class="dlg-checks-empty">${escapeHtml(opts.emptyLabel || "")}</span>`)
    + "</div>";
  const all = meta.querySelector("[data-check-all]");
  const each = [...meta.querySelectorAll("[data-check]")];
  if (all) {
    all.onchange = () => {
      _checks.all = all.checked;
      each.forEach((b) => { b.disabled = all.checked; b.checked = all.checked || _checks.picked.has(b.dataset.check); });
    };
  }
  each.forEach((b) => {
    b.onchange = () => { if (b.checked) _checks.picked.add(b.dataset.check); else _checks.picked.delete(b.dataset.check); };
  });
}

// The ticks as the dialog settles them: "all", or the values ticked in the dialog's order.
function checksValue() {
  if (!_checks) return [];
  return _checks.all ? "all" : _checks.order.filter((v) => _checks.picked.has(v));
}

export function appConfirm(message, opts = {}) {
  return openDialog(message, opts, "confirm");
}

// A confirm that cannot be answered by a click: the dialog shows a box, and its confirm button stays off until what
// is typed in it is `phrase` (trimmed, exactly). For what the board cannot take back — a machine let go of, rebooted,
// switched off: a click is a reflex, a name typed is a decision, and typing it makes the operator read which machine
// it is (the owner, 2026-10-14: "just pressing the button is not enough — the machine's name must be typed").
// opts.detail puts the phrase above the box (the caller names it there); opts.placeholder is the box's own words.
// Resolves true or false, as appConfirm does.
export function appConfirmTyped(message, phrase, opts = {}) {
  return openDialog(message, { ...opts, must: phrase }, "confirm-typed");
}

// A confirm that asks which of several things are meant — the pools a consumer may call.
// opts.choices: [{value, label}], opts.checked: "all" or the values ticked first,
// opts.allLabel: the box for all of them, opts.emptyLabel: what an empty list means.
// Resolves "all", the ticked values as an array (maybe empty), or null on cancel.
export function appConfirmChecks(message, opts = {}) {
  return openDialog(message, opts, "confirm-checks");
}

// (A mode whose answer is one of several buttons — appChoose — served one
// question: where a controller cell's start reads its model from. The question
// went with the controller's cells in step 6.9, and the mode with it. A prompt
// that also offered choices — appPromptChoice — served an engine model's load,
// and went when the board stopped loading engine models itself: a model is
// reached through a cell in its engine (2026-09-26). The choices of
// appConfirmChoice, below, are choices inside the dialog, not answers that
// close it.)

// window.prompt() replacement: resolves the entered string, or null on cancel.
// The message becomes the dialog title (native prompts have no separate body);
// opts.value prefills the input, opts.placeholder/text are optional extras.
export function appPrompt(message, opts = {}) {
  return openDialog(message, opts, "prompt");
}

// A confirm that also asks one of several choices — where a new cell runs, and
// for an engine the model it holds (docs/foreign-engines.md, cells in engines).
// opts.choices: [{value, label}], opts.choice: pressed first, opts.choiceLabel:
// what they choose, opts.list: a long list as a scrolling column. Resolves the
// pressed choice's value as a string, or null on cancel.
export function appConfirmChoice(message, opts = {}) {
  return openDialog(message, opts, "confirm-choice");
}

// Resolve the pending dialog (ok=true → confirmed / input submitted). Returns
// whether one was pending — closeConfirmModal calls this first so Cancel/
// Escape/overlay-click resolve the promise instead of leaving it hanging.
export function settleAppConfirm(ok) {
  // A confirm that waits for typed words is not confirmed by anything else: the call comes back as "a dialog is
  // pending" and the dialog stays open.
  if (ok && _must !== null && _resolve && !typedMatches($("confirmInput").value)) return true;
  const resolve = _resolve;
  _resolve = null;
  const value = _mode === "prompt" ? (ok ? $("confirmInput").value : null)
      : _mode === "confirm-choice" ? (ok ? _choice : null)
      : _mode === "confirm-checks" ? (ok ? checksValue() : null)
      : !!ok;
  _mode = "confirm";
  _must = null;
  $("confirmOverlay").hidden = true;
  $("confirmInput").hidden = true;
  $("confirmDelete").disabled = false;
  const hint = $("confirmInputHint");
  if (hint) hint.hidden = true;
  const meta = $("confirmMeta");
  if (meta) { meta.hidden = true; meta.innerHTML = ""; }
  $("confirmDelete").classList.remove("danger");
  // Legacy openers write the fields but not this caption: it goes back.
  $("confirmCancel").textContent = t("cancel");
  // Legacy openers (backup delete, service action, save/restart) write the
  // dialog fields directly and expect the destructive look.
  $("confirmOverlay").querySelector(".modal").dataset.tone = "danger";
  ui.pendingConfirm = null;
  if (!resolve) return false;
  resolve(value);
  return true;
}
