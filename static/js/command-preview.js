// Live llama-server command preview with LCS token diffing.
import { readConfigForm } from "./form.js";
import { t } from "./i18n.js";
import { setEditCurrentCommand } from "./llama-edit.js";
import { state } from "./state.js";
import { $, api, escapeHtml } from "./utils.js";

export function effectiveModelsDir(config = {}) {
  return String(config.LLAMA_MODELS_DIR || state.paths?.modelsDir || state.config?.LLAMA_MODELS_DIR || "")
    .replace(/\/+$/, "");
}

// Variant 2: the command is built by the single source of truth on the
// controller (build_llama_args in app.py). The old client-side buildPreviewTokens
// mirror was removed — renderCommandPreview() now fetches /api/llama-command-preview.

export function splitCommand(command) {
  return String(command || "").trim().split(/\s+/).filter(Boolean);
}

export function formatCmdline(command) {
  const tokens = splitCommand(command);
  const lines = [];
  let i = 0;
  while (i < tokens.length) {
    const tok = tokens[i];
    if (tok.startsWith("--") && i + 1 < tokens.length && !tokens[i + 1].startsWith("-")) {
      lines.push(tok + " " + tokens[i + 1]);
      i += 2;
    } else {
      lines.push(tok);
      i += 1;
    }
  }
  return lines.join("\n");
}

export function lcsPreviewIndexes(currentTokens, previewTokens) {
  const dp = Array.from({ length: currentTokens.length + 1 }, () => Array(previewTokens.length + 1).fill(0));
  for (let i = currentTokens.length - 1; i >= 0; i -= 1) {
    for (let j = previewTokens.length - 1; j >= 0; j -= 1) {
      dp[i][j] = currentTokens[i] === previewTokens[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const unchanged = new Set();
  let i = 0;
  let j = 0;
  while (i < currentTokens.length && j < previewTokens.length) {
    if (currentTokens[i] === previewTokens[j]) {
      unchanged.add(j);
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      i += 1;
    } else {
      j += 1;
    }
  }
  return unchanged;
}

// Debounce + stale-response guard, per form prefix. The preview is computed by
// the controller (single source of truth) so it always matches the real launch
// command; a short debounce avoids a request per keystroke.
export const _cmdPreviewTimers = {};
export const _cmdPreviewSeq = {};

// The "current command" each form's New-Command preview diffs against. The main
// page diffs against the running controller service (state.service.cmdline). The
// cell-edit modals (te- controller, tr- client) instead diff against the cell's
// OWN current command — set by setEditCurrentCommand() when the modal opens —
// otherwise they'd compare against the unrelated controller service (or, if that's
// not running, an empty baseline that flags every flag as changed).
export const _cmdBaselineTokens = {};

export function currentBaselineTokens(pfx) {
  if (Object.prototype.hasOwnProperty.call(_cmdBaselineTokens, pfx)) {
    return _cmdBaselineTokens[pfx] || [];
  }
  return splitCommand(state.service?.cmdline || "");
}

export function renderCommandPreview(pfx = "") {
  const target = $(pfx + "previewCmdline");
  if (!target || !state) return;
  // Visual "still computing" state: dim the previous command and show a spinner;
  // if there's nothing yet, show a placeholder line.
  target.classList.add("cmd-loading");
  if (!target.dataset.ready) {
    target.innerHTML = `<span class="cmd-note">${escapeHtml(t("commandComputing"))}</span>`;
  }
  const cfg = readConfigForm(pfx);
  const seq = (_cmdPreviewSeq[pfx] = (_cmdPreviewSeq[pfx] || 0) + 1);
  clearTimeout(_cmdPreviewTimers[pfx]);
  _cmdPreviewTimers[pfx] = setTimeout(async () => {
    let tokens = [];
    try {
      const res = await api("/api/llama-command-preview", {
        method: "POST",
        body: JSON.stringify({ config: cfg }),
      });
      tokens = res.tokens || [];
    } catch (err) {
      if (seq !== _cmdPreviewSeq[pfx]) return;  // a newer request superseded us
      target.classList.remove("cmd-loading");
      target.textContent = t("noPreviewCommand");
      return;
    }
    if (seq !== _cmdPreviewSeq[pfx]) return;     // stale response, ignore
    renderPreviewTokens(pfx, target, tokens);
  }, 160);
}

export function renderPreviewTokens(pfx, target, previewTokens) {
  target.classList.remove("cmd-loading");
  const currentTokens = currentBaselineTokens(pfx);
  if (!previewTokens.length) {
    target.textContent = t("noPreviewCommand");
    target.dataset.ready = "";
    return;
  }
  target.dataset.ready = "1";
  const unchanged = lcsPreviewIndexes(currentTokens, previewTokens);
  const previewChanged = previewTokens.some((_, index) => !unchanged.has(index));
  const removedTokens = currentTokens.filter((token) => !previewTokens.includes(token));
  const hasChanges = previewChanged || removedTokens.length > 0;

  // Show removed (struck-through) flags whenever there's a real baseline to diff
  // against. Both te- and tr- now diff against the cell's own current command, so
  // this is meaningful for both; "new"/add modes have an empty baseline, so nothing
  // is flagged removed anyway.
  const showRemoved = true;
  const removedHtml = (showRemoved && hasChanges && currentTokens.length && removedTokens.length)
    ? `\n<span class="cmd-removed-row"><span class="cmd-removed-label">${t("removedFlags")}:</span> ${
        removedTokens.map((tk) => `<span class="cmd-token cmd-removed">${escapeHtml(tk)}</span>`).join(" ")
      }</span>`
    : "";

  // Group --flag value pairs into single visual blocks.
  const cmdParts = [];
  let ti = 0;
  while (ti < previewTokens.length) {
    const tok = previewTokens[ti];
    const hasValue = tok.startsWith("--") && ti + 1 < previewTokens.length && !previewTokens[ti + 1].startsWith("-");
    if (hasValue) {
      const val = previewTokens[ti + 1];
      const changed = !unchanged.has(ti) || !unchanged.has(ti + 1);
      const cls = changed ? "cmd-token changed" : "cmd-token";
      cmdParts.push(`<span class="${cls}">${escapeHtml(tok)} <span class="cmd-value">${escapeHtml(val)}</span></span>`);
      ti += 2;
    } else {
      const changed = !unchanged.has(ti);
      const cls = changed ? "cmd-token changed" : "cmd-token";
      cmdParts.push(`<span class="${cls}">${escapeHtml(tok)}</span>`);
      ti += 1;
    }
  }
  target.innerHTML = cmdParts.join("\n") + (hasChanges ? removedHtml : `\n<span class="cmd-note">${t("noCommandChanges")}</span>`);

  // п.3: dirty-indicator on Save/Start buttons
  if (pfx === "te-") {
    $("topologyLlamaEditSaveRestart")?.classList.toggle("cmd-dirty", hasChanges);
  } else if (pfx === "tr-") {
    $("llamaRemoteEditStart")?.classList.toggle("cmd-dirty", hasChanges);
  }
}

