// Styled in-app replacements for window.confirm()/window.prompt(): Promise
// wrappers over the shared #confirmOverlay dialog. Native dialogs block the
// renderer and look foreign — nothing in the app should call them directly.
import { ui } from "./state.js";
import { t } from "./i18n.js";
import { $ } from "./utils.js";

let _resolve = null;
let _mode = "confirm";

function openDialog(message, opts, mode) {
  return new Promise((resolve) => {
    _resolve = resolve;
    _mode = mode;
    const dlg = $("confirmOverlay").querySelector(".modal");
    dlg.dataset.tone = mode === "prompt" || opts.danger === false ? "ask" : "danger";
    $("confirmTitle").textContent = opts.title || (mode === "prompt" ? message : t("confirmActionTitle"));
    $("confirmText").textContent = mode === "prompt" ? (opts.text || "") : message;
    const meta = $("confirmMeta");
    if (meta) { meta.hidden = true; meta.innerHTML = ""; }
    const path = $("confirmPath");
    if (path) path.textContent = opts.detail || "";
    const input = $("confirmInput");
    input.hidden = mode !== "prompt";
    if (mode === "prompt") {
      input.value = opts.value == null ? "" : String(opts.value);
      input.placeholder = opts.placeholder || "";
      input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); settleAppConfirm(true); } };
    }
    const btn = $("confirmDelete");
    btn.textContent = opts.confirmLabel || "OK";
    btn.classList.toggle("danger", mode !== "prompt" && opts.danger !== false);
    ui.pendingConfirm = () => settleAppConfirm(true);
    $("confirmOverlay").hidden = false;
    // Move focus into the dialog: the input for prompts, Cancel for dangerous
    // confirms (safe default), the confirm button otherwise.
    requestAnimationFrame(() => {
      if (mode === "prompt") { input.focus(); input.select(); }
      else if (dlg.dataset.tone === "danger") $("confirmCancel").focus();
      else btn.focus();
    });
  });
}

export function appConfirm(message, opts = {}) {
  return openDialog(message, opts, "confirm");
}

// window.prompt() replacement: resolves the entered string, or null on cancel.
// The message becomes the dialog title (native prompts have no separate body);
// opts.value prefills the input, opts.placeholder/text are optional extras.
export function appPrompt(message, opts = {}) {
  return openDialog(message, opts, "prompt");
}

// Resolve the pending dialog (ok=true → confirmed / input submitted). Returns
// whether one was pending — closeConfirmModal calls this first so Cancel/
// Escape/overlay-click resolve the promise instead of leaving it hanging.
export function settleAppConfirm(ok) {
  const resolve = _resolve;
  _resolve = null;
  const value = _mode === "prompt" ? (ok ? $("confirmInput").value : null) : !!ok;
  _mode = "confirm";
  $("confirmOverlay").hidden = true;
  $("confirmInput").hidden = true;
  $("confirmDelete").classList.remove("danger");
  // Legacy openers (backup delete, service action, save/restart) write the
  // dialog fields directly and expect the destructive look.
  $("confirmOverlay").querySelector(".modal").dataset.tone = "danger";
  ui.pendingConfirm = null;
  if (!resolve) return false;
  resolve(value);
  return true;
}
