// te- cell edit modal: backups, snapshots, confirm modal, command presets.
import { appPrompt, settleAppConfirm } from "./dialogs.js";
import {
  _cmdBaselineTokens,
  effectiveModelsDir,
  formatCmdline,
  renderCommandPreview,
  splitCommand,
} from "./command-preview.js";
import { dirtyOptionalToggles, modelFields, numericFields, toggleFields } from "./constants.js";
import { refreshFavoritesPanel } from "./favorites.js";
import { findSlotEntry, renderSchedulePanel } from "./remote-cells.js";
import {
  badge,
  mcUpdateTrigger,
  option,
  readConfigForm,
  renderChatTemplateHint,
  renderFields,
  renderModelInsight,
  renderModelSelects,
  syncAllToggleLabels,
  syncPortChipsEl,
  syncToggleLabel,
  toggleChecked,
} from "./form.js";
import { fieldHelp, t } from "./i18n.js";
import { refreshComputeTarget } from "./memory.js";
import { action, loadState, saveConfig } from "./polling.js";
import { _trCellPort, _trHostId } from "./remote-cells.js";
import { setState, state, topology, ui } from "./state.js";
import { renderAll } from "./topology-render.js";
import { $, api, escapeHtml, toast } from "./utils.js";

export let teLlamaFormReady = false;  // whether te-dynamicFields has been rendered at least once
export let pendingBackupDelete = "";


export function backupLabel(path) {
  return String(path).split("/").pop().replace("start-server.sh.bak.", "");
}

export function backupPath(row) {
  return typeof row === "string" ? row : row.path;
}

export function backupDisplayLabel(row) {
  if (typeof row === "string") return backupLabel(row);
  return row.label || backupLabel(row.path);
}

export function backupCreatedLabel(row) {
  const value = backupLabel(backupPath(row));
  const match = value.match(/^(\d{8})-(\d{6})/);
  if (!match) return value;
  const [, date, timeValue] = match;
  return `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)} ${timeValue.slice(0, 2)}:${timeValue.slice(2, 4)}:${timeValue.slice(4, 6)}`;
}

export function backupByPath(path) {
  return (state.backups || []).find((row) => backupPath(row) === path) || path;
}

// ── Topology Llama Edit Modal ────────────────────────────────────────────────
export let _teCellPort = "";
let _teTitleMode = "edit";

// Composed chrome of the OPEN cell editor (title with the server name, the
// state-dependent Apply/Start/Restart button) cannot be refreshed from
// data-i18n — rebuild those two pieces when the language changes while the
// overlay is visible. Everything else in the overlay is covered by the
// data-i18n / data-fieldhelp markers that applyLanguage() walks.
window.addEventListener("caravan:langchange", () => {
  const overlay = $("topologyLlamaEditOverlay");
  if (!overlay || overlay.hidden) return;
  const serverName = topology?.server?.name || "Controller";
  const gpuName = (topology?.server?.gpus || [])[0]?.name || "";
  const gpuSuffix = gpuName ? ` · ${gpuName}` : "";
  const titleEl = $("topologyLlamaEditTitle");
  if (titleEl) {
    titleEl.textContent = t(_teTitleMode === "add" ? "llamaEditTitleAdd" : "llamaEditTitleEdit",
      { name: `${serverName}${gpuSuffix}` });
  }
  const saveRestartBtn = $("topologyLlamaEditSaveRestart");
  if (saveRestartBtn) {
    const isRunning = !!(state.service?.active || state.service?.pid);
    saveRestartBtn.textContent = _teCellPort ? t("apply") : t(isRunning ? "restart" : "start");
  }
});
// Runner tabs (labels + trade-off tooltips + the benefits line) and the
// command-aside preview are rebuilt purely from state/t() — safe to re-render
// on language switch for whichever cell editor is open ("te-" controller,
// "tr-" client). Form inputs live outside these subtrees, so no edits are lost.
window.addEventListener("caravan:langchange", () => {
  ["te-", "tr-"].forEach((pfx) => {
    const overlay = _cellKindOverlay(pfx);
    if (!overlay || overlay.hidden) return;
    renderRunnerTabs(pfx);
    refreshComputeTarget(pfx);
    if (effectiveRunnerId(pfx) !== "llama-server") renderCommandCellPreview(pfx);
  });
});
export const _editCmdSeq = {};

// Fill a form's "current command" panel (<pfx>currentCmdline) and set the diff
// baseline for its New-Command preview, then (re)render the preview. The baseline
// is the form's CURRENT command, so editing a field highlights only what actually
// changed. Used by both the controller (te-) and client (tr-) Add-Llama modals so
// they behave identically. Modes:
//   • "main" — the controller's running service (state.service.cmdline);
//   • "cell" — a configured cell (controller or remote): build its command from the
//     form's initial config via the canonical builder, so an unedited form shows
//     "no changes" and edits highlight precisely;
//   • "new"  — a freshly reserved / brand-new server: no prior command, every flag
//     reads as added.
// Show a command line (or the localized "no command" placeholder) in the
// <pfx>currentCmdline panel. Stamps data-i18n on the placeholder so an open
// editor re-translates it on language switch; real cmdlines clear the marker.
function _showCurrentCmdline(cur, tokens) {
  if (!cur) return;
  if (tokens.length) {
    delete cur.dataset.i18n;
    cur.textContent = formatCmdline(tokens.join(" "));
  } else {
    cur.dataset.i18n = "noRunningCommand";
    cur.textContent = t("noRunningCommand");
  }
}

export async function setEditCurrentCommand(pfx, mode) {
  const cur = $(pfx + "currentCmdline");
  const seq = (_editCmdSeq[pfx] = (_editCmdSeq[pfx] || 0) + 1);
  if (mode === "main") {
    const tokens = splitCommand(state.service?.cmdline || "");
    _cmdBaselineTokens[pfx] = tokens;
    _showCurrentCmdline(cur, tokens);
    renderCommandPreview(pfx);
    return;
  }
  if (mode === "new") {
    _cmdBaselineTokens[pfx] = [];
    _showCurrentCmdline(cur, []);
    renderCommandPreview(pfx);
    return;
  }
  // mode === "cell": fetch the canonical command for the form's initial config.
  const initialConfig = readConfigForm(pfx);
  _cmdBaselineTokens[pfx] = [];
  if (cur) cur.textContent = "";
  renderCommandPreview(pfx);
  try {
    const res = await api("/api/llama-command-preview", {
      method: "POST",
      body: JSON.stringify({ config: initialConfig }),
    });
    if (seq !== _editCmdSeq[pfx]) return;  // a newer open() superseded us
    const tokens = res.tokens || [];
    _cmdBaselineTokens[pfx] = tokens;
    _showCurrentCmdline(cur, tokens);
  } catch (err) {
    if (seq !== _editCmdSeq[pfx]) return;
    /* leave an empty baseline — preview still renders, just without a diff */
  }
  renderCommandPreview(pfx);
}

export function syncTeModelsDirPreview() {
  const input = $("te-LLAMA_MODELS_DIR");
  const hint = $("te-modelFileDirHint");
  const val = input?.value?.trim() || "";
  if (hint) {
    hint.hidden = !!val;
    if (!val) hint.textContent = t("modelFileDirHint");
  }
}

export function openTopologyLlamaEdit(mode = "edit", cellPort = "") {
  _teCellPort = cellPort ? String(cellPort) : "";
  renderSchedulePanel("te", "skynet", _teCellPort, findSlotEntry("skynet", _teCellPort)?.schedule);
  if (!teLlamaFormReady) {
    renderFields("te-");
    wireCellKindToggle("te-");
    $("te-LLAMA_MODELS_DIR")?.addEventListener("input", syncTeModelsDirPreview);
    teLlamaFormReady = true;
  }
  renderModelSelects("te-");
  // For a cell (cellPort set), load the cell's own saved slotConfig rather than
  // the controller's start-server.sh config — otherwise the form shows the main
  // service's model (e.g. gemma) instead of the model this cell actually runs.
  let _teFormConfig = state.config;
  let _teSlotHasConfig = false;
  if (_teCellPort) {
    const slot = (topology?.nodes || [])
      .flatMap((n) => n.servers || [])
      .find((s) => s.isSlot && String(s.port) === String(_teCellPort));
    if (slot?.slotConfig && Object.keys(slot.slotConfig).length) {
      _teFormConfig = { ...state.config, ...slot.slotConfig };
      _teSlotHasConfig = true;
    }
  }
  applyConfigToForm(_teFormConfig, "te-");
  // Populate hidden models-dir from effective value so command preview is correct
  const teMdEl = $("te-LLAMA_MODELS_DIR");
  if (teMdEl && !teMdEl.value) teMdEl.value = effectiveModelsDir(state.config);
  const tePortEl = $("te-PORT");
  if (tePortEl) {
    if (_teCellPort) {
      tePortEl.value = _teCellPort;
      tePortEl.readOnly = true;
    } else {
      tePortEl.readOnly = false;
    }
  }
  refreshComputeTarget("te-");
  renderChatTemplateHint("te-");
  renderBackups("te-");
  refreshFavoritesPanel("te-");  // reflect the latest global favorites order/set
  syncTeModelsDirPreview();
  // Fill the COMMAND panel and set the diff baseline for New Command, then render
  // the preview. Three cases: the controller's main service (no cell), a cell that
  // already has a saved config, or a freshly reserved (empty) cell.
  setEditCurrentCommand("te-", _teCellPort ? (_teSlotHasConfig ? "cell" : "new") : "main");

  // Dynamic title: show server name + first GPU name
  const serverName = topology?.server?.name || "Controller";
  const gpuName = (topology?.server?.gpus || [])[0]?.name || "";
  const gpuSuffix = gpuName ? ` · ${gpuName}` : "";
  _teTitleMode = mode;   // remembered so a language switch re-renders the title live
  const titleEl = $("topologyLlamaEditTitle");
  if (titleEl) {
    titleEl.textContent = t(mode === "add" ? "llamaEditTitleAdd" : "llamaEditTitleEdit", { name: `${serverName}${gpuSuffix}` });
    // LOCAL badge next to title (not in actions bar)
    let badge = titleEl.parentElement.querySelector(".topo-edit-mode-badge");
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "topo-edit-mode-badge local";
      badge.dataset.i18n = "badgeLocal";   // kept in sync by applyLanguage
      titleEl.after(badge);
    }
    badge.textContent = t("badgeLocal");   // update on every open, not just create
  }

  // Adaptive button: "OK" (save only) for cell config, Start/Restart for main config
  const saveRestartBtn = $("topologyLlamaEditSaveRestart");
  if (saveRestartBtn) {
    const isRunning = !!(state.service?.active || state.service?.pid);
    if (_teCellPort) {
      saveRestartBtn.textContent = t("apply");
      saveRestartBtn.className = "topo-ok-btn";
    } else {
      saveRestartBtn.textContent = t(isRunning ? "restart" : "start");
      saveRestartBtn.className = "danger";
    }
  }

  // The command-cell toggle only applies to reserved cells, not the main service.
  const teKindRow = $("topologyLlamaEditOverlay")?.querySelector(".cell-kind-row");
  if (teKindRow) teKindRow.hidden = !_teCellPort;
  if (!_teCellPort) {
    const k = $("te-CELL_KIND");
    const r = $("te-RUNNER");
    if ((k && k.value) || (r && r.value && r.value !== "llama-server")) {
      if (k) k.value = "";
      if (r) r.value = "";
      applyCellKindUI("te-");
    }
  }
  $("topologyLlamaEditOverlay").hidden = false;
}

export function closeTopologyLlamaEdit() {
  $("topologyLlamaEditOverlay").hidden = true;
}

export async function saveTopologyLlamaConfig(restart) {
  const btn = $("topologyLlamaEditSaveRestart");
  const orig = btn ? btn.textContent : "";
  if (btn) {
    btn.textContent = restart ? t("topologyClientGpuStarting") : t("savingConfig");
    btn.disabled = true;
    btn.classList.add("btn-busy");
  }
  try {
    const config = readConfigForm("te-");
    const data = await api("/api/config", {
      method: "POST",
      body: JSON.stringify({ config, restart, cellPort: _teCellPort }),
    });
    setState(data.state);
    closeTopologyLlamaEdit();
    renderAll();
    toast(restart ? t("savedRestarted") : t("saved"));
  } catch (err) {
    toast(err.message);
  } finally {
    if (btn) {
      btn.textContent = orig;
      btn.disabled = false;
      btn.classList.remove("btn-busy");
    }
  }
}

// ── End Topology Llama Edit Modal ────────────────────────────────────────────

export function renderBackups(pfx = "") {
  const rows = state.backups || [];
  const infoEl = $(pfx + "backupInfo");
  const listEl = $(pfx + "backups");
  if (!infoEl || !listEl) return;
  infoEl.textContent = rows.length ? t("clickBackupHint") : t("noBackups");
  const saveCurrentHtml = `
    <button class="backup-save-current" type="button" data-snapshot-config title="${escapeHtml(t("saveSnapshotHint"))}">
      + ${escapeHtml(t("saveSnapshot"))}
    </button>`;
  listEl.innerHTML = saveCurrentHtml + rows.map((row) => {
    const path = backupPath(row);
    const label = backupDisplayLabel(row);
    const title = `${label}\n${path}`;
    return `
      <div class="backup-row" title="${escapeHtml(title)}">
        <button class="backup-item" type="button" data-backup-path="${escapeHtml(path)}">
          <span>${escapeHtml(label)}</span>
          <code>${escapeHtml(path)}</code>
        </button>
        <button class="backup-delete" type="button" data-delete-backup="${escapeHtml(path)}" aria-label="${escapeHtml(t("deleteBackup"))}">×</button>
      </div>
    `;
  }).join("");
  const snapBtn = listEl.querySelector("[data-snapshot-config]");
  if (snapBtn) snapBtn.addEventListener("click", () => snapshotConfig(pfx));
  listEl.querySelectorAll("[data-backup-path]").forEach((button) => {
    button.addEventListener("click", () => loadBackup(button.dataset.backupPath, pfx));
  });
  listEl.querySelectorAll("[data-delete-backup]").forEach((button) => {
    button.addEventListener("click", () => openDeleteBackupModal(backupByPath(button.dataset.deleteBackup)));
  });
}

export function applyConfigToForm(config, pfx = "") {
  if (!pfx) dirtyOptionalToggles.clear();
  modelFields.forEach((field) => {
    const el = $(pfx + field);
    if (!el) return;
    el.value = config[field] || "";
    // Refresh the searchable-combobox label; setting .value alone leaves the
    // trigger showing whatever renderModelSelects computed (often the stale
    // state.config model), even though the value/command preview are correct.
    if (el.tagName === "SELECT") mcUpdateTrigger(el);
  });
  numericFields.forEach((field) => {
    const el = $(pfx + field);
    if (el) el.value = config[field] || "";
  });
  toggleFields.forEach((field) => {
    const el = $(pfx + field);
    if (el) el.checked = toggleChecked(field, config);
  });
  syncAllToggleLabels(pfx);
  // Sync synthetic SPEC_ENABLED checkbox from SPEC_TYPE value
  const specEnabledEl = $(pfx + "SPEC_ENABLED");
  if (specEnabledEl) {
    specEnabledEl.checked = !!(config.SPEC_TYPE && config.SPEC_TYPE !== "none");
    syncToggleLabel(specEnabledEl);
  }
  // Sync port chips after value is set
  const portInput = $(pfx + "PORT");
  if (portInput) {
    const chips = portInput.closest(".port-picker")?.querySelectorAll(".port-chip");
    if (chips?.length) syncPortChipsEl(chips, portInput.value);
  }
  renderModelInsight(pfx);
  renderCommandPreview(pfx);
  // Generic command cell fields + llama/command visibility.
  const ckEl = $(pfx + "CELL_KIND");
  if (ckEl) ckEl.value = config.CELL_KIND || "";
  const runEl = $(pfx + "RUNNER");
  if (runEl) runEl.value = config.RUNNER || "";
  const cmdEl = $(pfx + "COMMAND");
  if (cmdEl) cmdEl.value = config.COMMAND || "";
  const hpEl = $(pfx + "HEALTH_PATH");
  if (hpEl) hpEl.value = config.HEALTH_PATH || "";
  ["VLLM_MODEL", "MAX_MODEL_LEN", "GPU_MEMORY_UTILIZATION", "QUANTIZATION", "DTYPE", "TENSOR_PARALLEL"].forEach((k) => {
    const el = $(pfx + k);
    if (el) el.value = config[k] || "";
  });
  const whEl = $(pfx + "WHISPER_MODEL");
  if (whEl) whEl.value = config.WHISPER_MODEL || "large-v3";
  // vLLM/whisper cells clear MODEL_FILE on save, and merging with the global
  // config would leak the main service's model into the picker. So the picker
  // ALWAYS shows the cell's own artifact (vLLM with a local path) or nothing
  // (HF repo id / whisper, whose model is a size name) — never the leak.
  const _rid = String(config.RUNNER || "").toLowerCase();
  if (_rid === "vllm" || _rid === "whisper") {
    const vm = String(config.VLLM_MODEL || "").trim().replace(/\/+$/, "");
    const base = (state.paths?.modelsDir || "").replace(/\/+$/, "");
    let rel = "";
    if (_rid === "vllm" && vm && base && vm.startsWith(base + "/")) {
      const cand = vm.slice(base.length + 1);
      if ((state.artifacts || []).some((a) => a.path === cand)) rel = cand;
    }
    if (_rid === "whisper") {
      // Every size has a picker row now (undownloaded ones dimmed).
      const size = String(config.WHISPER_MODEL || "").trim() || "large-v3";
      rel = `whisper/models--Systran--faster-whisper-${size}`;
    }
    const mEl = $(pfx + "MODEL_FILE");
    if (mEl) {
      mEl.value = rel;
      if (mEl.tagName === "SELECT") mcUpdateTrigger(mEl);
    }
  }
  const envEl = $(pfx + "ENV");
  if (envEl) envEl.value = config.ENV || "";
  const wdEl = $(pfx + "WORKDIR");
  if (wdEl) wdEl.value = config.WORKDIR || "";
  applyCellKindUI(pfx);
}

export function suggestedSnapshotName(pfx = "") {
  const modelFile = ($(pfx + "MODEL_FILE")?.value) || (state && state.config && state.config.MODEL_FILE) || "";
  const base = (modelFile.split("/").pop() || "config").replace(/\.gguf$/i, "");
  const d = new Date();
  const date = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
  return [base, date, "stable"].filter(Boolean).join("-");
}

// The CURRENTLY-SAVED config for whatever this form targets — deliberately NOT
// readConfigForm(), so "Save current config" snapshots the running config and
// ignores unsaved edits in the open form. For a configured server cell that's the
// cell's own saved slotConfig; otherwise null → the backend copies the live
// start-server.sh (the main launcher's current config).
export function currentSavedConfig(pfx) {
  if (pfx === "te-" && _teCellPort) {
    const slot = (topology?.nodes || [])
      .flatMap((n) => n.servers || [])
      .find((s) => s.isSlot && String(s.port) === String(_teCellPort));
    if (slot?.slotConfig && Object.keys(slot.slotConfig).length) {
      return { ...state.config, ...slot.slotConfig };
    }
  }
  return null;
}

export async function snapshotConfig(pfx = "") {
  const name = await appPrompt(t("snapshotNamePrompt"), { value: suggestedSnapshotName(pfx), confirmLabel: t("save"), scene: "create" });
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed) {
    toast(t("snapshotNameRequired"));
    return;
  }
  const cellConfig = currentSavedConfig(pfx);
  // The prompt modal is gone the moment it resolves, and the snapshot call
  // can take a couple of seconds — keep the trigger button visibly busy so
  // the pause reads as "saving", not "nothing happened".
  const snapBtn = $(pfx + "backups")?.querySelector("[data-snapshot-config]");
  snapBtn?.classList.add("btn-busy");
  if (snapBtn) snapBtn.disabled = true;
  toast(t("snapshotSaving"));
  try {
    const data = await api("/api/config/snapshot", {
      method: "POST",
      body: JSON.stringify(cellConfig ? { name: trimmed, config: cellConfig } : { name: trimmed }),
    });
    if (data.state) setState(data.state);
    renderBackups(pfx);
    toast(`${t("snapshotSaved")}: ${backupLabel(data.snapshot)}`);
  } catch (err) {
    toast(err.message);
  } finally {
    snapBtn?.classList.remove("btn-busy");
    if (snapBtn) snapBtn.disabled = false;
  }
}

export async function loadBackup(path, pfx = "") {
  try {
    const data = await api(`/api/backup?path=${encodeURIComponent(path)}`);
    applyConfigToForm(data.config || {}, pfx);
    const infoEl = $(pfx + "backupInfo");
    if (infoEl) infoEl.textContent = `${t("loadedBackup")}: ${data.path}`;
    toast(`${t("loadedBackup")}: ${backupLabel(data.path)}`);
  } catch (err) {
    const infoEl = $(pfx + "backupInfo");
    if (infoEl) infoEl.textContent = err.message;
    toast(err.message);
  }
}

export function openDeleteBackupModal(row) {
  const path = backupPath(row);
  pendingBackupDelete = path;
  $("confirmText").textContent = t("deleteBackupText");
  const model = typeof row === "string" ? "" : row.modelFile;
  const ctx = typeof row === "string" ? "" : row.ctxSize;
  const meta = [
    [t("created"), backupCreatedLabel(row)],
    [t("model"), model ? model.split("/").pop() : ""],
    [t("context"), ctx],
  ].filter(([, value]) => value);
  $("confirmMeta").hidden = !meta.length;
  $("confirmMeta").innerHTML = meta.map(([label, value]) => `
    <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
  $("confirmPath").textContent = path;
  $("confirmDelete").textContent = t("deleteAction");
  $("confirmDelete").classList.add("danger");
  ui.pendingConfirm = () => deleteBackup();
  $("confirmOverlay").hidden = false;
}

export function closeConfirmModal() {
  settleAppConfirm(false);
  pendingBackupDelete = "";
  ui.pendingConfirm = null;
  $("confirmOverlay").hidden = true;
  // Reset button state so next caller starts clean (danger/non-danger).
  $("confirmDelete").classList.remove("danger");
}

export async function deleteBackup(path = pendingBackupDelete) {
  if (!path) return;
  try {
    const data = await api("/api/backup/delete", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
    setState(data.state);
    closeConfirmModal();
    renderAll();
    toast(t("deletedBackup"));
  } catch (err) {
    toast(err.message);
  }
}

export function openActionModal(name) {
  $("confirmTitle").textContent = t("confirmActionTitle");
  $("confirmText").textContent = t("confirmActionText", { action: t(name) });
  const meta = [
    [t("actionLabel"), t(name)],
    [t("service"), state.paths?.service || "llamacpp-current.service"],
    [t("pid"), state.service?.MainPID || "n/a"],
  ];
  $("confirmMeta").hidden = false;
  $("confirmMeta").innerHTML = meta.map(([label, value]) => `
    <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>
  `).join("");
  $("confirmPath").textContent = state.paths?.service || "llamacpp-current.service";
  $("confirmDelete").textContent = t(name);
  $("confirmDelete").classList.add("danger");
  ui.pendingConfirm = () => action(name);
  $("confirmOverlay").hidden = false;
}

export function openToolbarConfirm(kind) {
  const isReload = kind === "reload";
  const isSave = kind === "save";
  const titleKey = isReload ? "confirmReloadTitle" : isSave ? "confirmSaveTitle" : "confirmSaveRestartTitle";
  const textKey = isReload ? "confirmReloadText" : isSave ? "confirmSaveText" : "confirmSaveRestartText";
  const config = readConfigForm();
  $("confirmTitle").textContent = t(titleKey);
  $("confirmText").textContent = t(textKey);
  const meta = [
    [t("actionLabel"), isReload ? t("reload") : isSave ? t("save") : t("saveRestart")],
    [t("model"), config.MODEL_FILE ? config.MODEL_FILE.split("/").pop() : "n/a"],
    [t("context"), config.CTX_SIZE || "n/a"],
  ];
  $("confirmMeta").hidden = false;
  $("confirmMeta").innerHTML = meta.map(([label, value]) => `
    <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>
  `).join("");
  $("confirmPath").textContent = state.paths?.startScript || "start-server.sh";
  $("confirmDelete").textContent = isReload ? t("reload") : isSave ? t("save") : t("saveRestart");
  $("confirmDelete").classList.add("danger");
  ui.pendingConfirm = async () => {
    closeConfirmModal();
    if (isReload) {
      await loadState();
      toast(t("reloaded"));
    } else {
      await saveConfig(!isSave);
    }
  };
  $("confirmOverlay").hidden = false;
}

// ── Generic command cell: toggle a cell config form between llama-server fields
// and a single raw COMMAND (pfx "te-" = controller cell, "tr-" = client cell). ──
export function _cellKindOverlay(pfx) {
  const id = pfx === "te-" ? "topologyLlamaEditOverlay"
           : pfx === "tr-" ? "llamaRemoteEditOverlay" : "";
  return id ? $(id) : null;
}

// Runner metadata: prefer the backend registry (state.runners), fall back to
// the built-in pair so the form works before /api/state lands.
export function runnerRegistry() {
  const rs = state.runners;
  return (Array.isArray(rs) && rs.length) ? rs : [
    { id: "llama-server", icon: "🦙", labelKey: "runnerLlama", benefitsKey: "runnerLlamaBenefits", formats: ["gguf"] },
    { id: "custom", icon: "🛠️", labelKey: "runnerCustom", benefitsKey: "runnerCustomBenefits", formats: ["*"] },
  ];
}

export function effectiveRunnerId(pfx) {
  const explicit = ($(pfx + "RUNNER")?.value || "").trim();
  if (explicit) return explicit;
  return ($(pfx + "CELL_KIND")?.value || "") === "command" ? "custom" : "llama-server";
}

// Can this runner launch the currently selected artifact? An empty model never
// blocks a tab (the form starts empty); "*" accepts anything. Today the only
// concrete format is gguf — safetensors variants arrive with the vLLM runner.
function runnerAvailability(runner, pfx) {
  const formats = runner.formats || [];
  if (formats.includes("*")) return { ok: true };
  const model = $(pfx + "MODEL_FILE")?.value || "";
  if (!model) return { ok: true };
  const fmt = model.toLowerCase().endsWith(".gguf") ? "gguf" : "other";
  return formats.includes(fmt) ? { ok: true } : { ok: false, reasonKey: "runnerNeedsGguf" };
}

// CUDA compute capability by GPU marketing name — best-effort map used only to
// gate quant formats (formatRequirements). Unknown GPUs render as "?".
export function gpuComputeCap(name) {
  const n = String(name || "").toUpperCase();
  if (/RTX 50/.test(n)) return 12.0;                     // Blackwell consumer
  if (/\bB[12]00\b|\bGB[12]0/.test(n)) return 10.0;      // Blackwell datacenter
  if (/H100|H200|GH200/.test(n)) return 9.0;             // Hopper
  if (/RTX 40|\bL4\b|\bL40/.test(n)) return 8.9;         // Ada
  if (/RTX 30|\bA(40|10|16|2)\b|A[45]000|A6000/.test(n)) return 8.6;  // Ampere consumer/pro
  if (/\bA100\b|\bA30\b/.test(n)) return 8.0;            // Ampere datacenter
  if (/RTX 20|TITAN RTX|\bT4\b/.test(n)) return 7.5;     // Turing
  if (/\bV100\b/.test(n)) return 7.0;                    // Volta
  return null;
}

// "Which hosts can run this artifact's format?" — one line under the runner
// benefits, only when the format has a compute requirement (NVFP4/FP8).
function runnerHostGateHtml(pfx) {
  const runner = runnerRegistry().find((r) => r.id === effectiveRunnerId(pfx));
  const reqs = runner?.formatRequirements || {};
  const model = $(pfx + "MODEL_FILE")?.value || "";
  // vLLM does load GGUF (that's why the tab stays enabled) — but it's the
  // experimental path there; say so instead of silently allowing it.
  if (runner?.id === "vllm" && model.toLowerCase().endsWith(".gguf")) {
    return `<br><span class="runner-host-gate">⚠ ${escapeHtml(t("runnerVllmGgufNote"))}</span>`;
  }
  const art = (state.artifacts || []).find((a) => a.path === model);
  const need = art ? reqs[String(art.format || "").toLowerCase()] : null;
  if (!need) return "";
  const rows = [];
  (topology?.nodes || []).forEach((n) => (n.gpus || []).forEach((g) => {
    const cap = gpuComputeCap(g.name);
    const ok = cap != null && cap >= need;
    const mark = cap == null ? "?" : (ok ? "✓" : "✗");
    rows.push(`<span class="${ok ? "gate-ok" : "gate-no"}" title="${escapeHtml(String(g.name || ""))}${cap != null ? ` · compute ${cap}` : ""}">${escapeHtml(String(n.name || n.id))} ${mark}</span>`);
  }));
  if (!rows.length) return "";
  return `<br><span class="runner-host-gate">${escapeHtml(art.format)} · ${escapeHtml(t("runnerNeedsCompute", { n: need }))} → ${rows.join(" · ")}</span>`;
}

// VLLM_MODEL derives from the model picker, so the raw field is noise while a
// model is picked — show it only for the hand-typed HF-repo-id case (empty
// picker), and always on client (tr-) cells where controller paths don't apply.
function syncVllmModelVisibility(pfx) {
  const el = $(pfx + "VLLM_MODEL");
  if (!el) return;
  const picked = !!(($(pfx + "MODEL_FILE")?.value || "").trim());
  const hide = picked && pfx !== "tr-";
  el.style.display = hide ? "none" : "";
  const lbl = el.previousElementSibling;
  if (lbl?.classList?.contains("label-row")) lbl.style.display = hide ? "none" : "";
}

// "✓" on whisper sizes that are already on disk under <models root>/whisper.
function markWhisperOptions(pfx) {
  const sel = $(pfx + "WHISPER_MODEL");
  if (!sel) return;
  const have = new Set(state.whisperOnDisk || []);
  [...sel.options].forEach((o) => {
    const base = o.dataset.baseLabel || (o.dataset.baseLabel = o.textContent);
    o.textContent = have.has(o.value) ? `✓ ${base}` : base;
  });
}

// The runner panels (command/vLLM/whisper) are static HTML — give their field
// labels the SAME (?) tip-trigger the llama fields get from labelWithTip.
// Idempotent and re-run on every render so tooltips follow language switches.
const _STATIC_TIP_FIELDS = ["COMMAND", "ENV", "WORKDIR", "HEALTH_PATH",
  "VLLM_MODEL", "MAX_MODEL_LEN", "GPU_MEMORY_UTILIZATION", "QUANTIZATION",
  "DTYPE", "TENSOR_PARALLEL", "WHISPER_MODEL"];
function injectStaticFieldTips(pfx) {
  _STATIC_TIP_FIELDS.forEach((f) => {
    const label = _cellKindOverlay(pfx)?.querySelector(`label[for="${pfx}${f}"]`);
    if (!label) return;
    const help = fieldHelp(f);
    if (!help) return;
    let btn = label.parentElement?.querySelector(".tip-trigger");
    if (!btn) {
      btn = document.createElement("button");
      btn.className = "tip-trigger";
      btn.type = "button";
      btn.innerHTML = `?<span class="tooltip" role="tooltip"></span>`;
      label.after(btn);
    }
    btn.setAttribute("aria-label", `${f}: ${help}`);
    btn.querySelector(".tooltip").textContent = help;
  });
}

export function renderRunnerTabs(pfx) {
  const overlay = _cellKindOverlay(pfx);
  const wrap = overlay?.querySelector(".runner-tabs");
  if (!wrap) return;
  syncVllmModelVisibility(pfx);
  markWhisperOptions(pfx);
  injectStaticFieldTips(pfx);
  const current = effectiveRunnerId(pfx);
  // Each tab carries a (?) with the full trade-off story: what the runner is
  // good at (benefitsKey) and what it costs (runner*Minus).
  const MINUS_KEY = { "llama-server": "runnerLlamaMinus", "vllm": "runnerVllmMinus",
                      "whisper": "runnerWhisperMinus", "custom": "runnerCustomMinus" };
  wrap.innerHTML = runnerRegistry().map((r) => {
    const avail = runnerAvailability(r, pfx);
    const label = (r.icon ? r.icon + " " : "") + t(r.labelKey || r.id);
    const tipParts = [r.benefitsKey ? t(r.benefitsKey) : "", MINUS_KEY[r.id] ? t(MINUS_KEY[r.id]) : ""];
    if (!avail.ok) tipParts.unshift(t(avail.reasonKey));
    const tip = tipParts.filter(Boolean).join("\n\n");
    return `<button type="button" class="cell-kind-btn${r.id === current ? " is-active" : ""}"` +
      ` data-runner="${escapeHtml(r.id)}"${avail.ok ? "" : " disabled"} title="${escapeHtml(tip)}"` +
      ` style="flex:1;padding:6px 10px;cursor:pointer">${escapeHtml(label)}` +
      `<span class="runner-tab-help" title="${escapeHtml(tip)}">?</span></button>`;
  }).join("");
  const benefits = $(pfx + "runnerBenefits");
  if (benefits) {
    const meta = runnerRegistry().find((r) => r.id === current);
    benefits.innerHTML = (meta?.benefitsKey ? escapeHtml(t(meta.benefitsKey)) : "") + runnerHostGateHtml(pfx);
  }
}

export function applyCellKindUI(pfx) {
  const overlay = _cellKindOverlay(pfx);
  const kindEl = $(pfx + "CELL_KIND");
  if (!overlay || !kindEl) return;
  const runner = effectiveRunnerId(pfx);
  const isCommand = runner === "custom";
  // A custom command ignores the shared model picker (only COMMAND + $PORT
  // reach the exec line) — dim the MODEL_FILE block so the picked model does
  // not read as active config. whisper/vLLM DO consume the shared picker.
  const modelField = $(pfx + "MODEL_FILE")?.closest(".field");
  if (modelField) modelField.classList.toggle("runner-ignores-model", isCommand);
  // Keep both hidden inputs coherent: RUNNER is the source of truth, CELL_KIND
  // stays populated for legacy readers (scout, old backups, start.sh blocks).
  const rEl = $(pfx + "RUNNER");
  if (rEl) rEl.value = runner;
  kindEl.value = isCommand ? "command" : "";
  renderRunnerTabs(pfx);
  const isVllm = runner === "vllm";
  const isWhisper = runner === "whisper";
  const nonLlama = isCommand || isVllm || isWhisper;
  // Use inline display, not the [hidden] attr: .field has a stylesheet `display`
  // rule that would otherwise keep the command fields visible in llama mode.
  const llamaFields = $(pfx + "llamaFields");
  if (llamaFields) llamaFields.style.display = nonLlama ? "none" : "";
  const cmdFields = $(pfx + "commandFields");
  if (cmdFields) cmdFields.style.display = isCommand ? "" : "none";
  const vllmFields = $(pfx + "vllmFields");
  if (vllmFields) vllmFields.style.display = isVllm ? "" : "none";
  // The whisper size is picked in the SHARED model picker on every form —
  // the container stays as the hidden carrier of the WHISPER_MODEL value.
  const whisperFields = $(pfx + "whisperFields");
  if (whisperFields) whisperFields.style.display = "none";
  // Aside: llama VRAM/preview vs. the command preview + history (vllm/whisper
  // reuse the command aside — their exec line renders into the same preview).
  const llamaAside = $(pfx + "llamaAside");
  if (llamaAside) llamaAside.style.display = nonLlama ? "none" : "";
  const cmdAside = $(pfx + "commandAside");
  if (cmdAside) cmdAside.style.display = nonLlama ? "" : "none";
  if (nonLlama) renderCommandCellPreview(pfx);
}

export function wireCellKindToggle(pfx) {
  const overlay = _cellKindOverlay(pfx);
  if (!overlay || overlay.dataset.cellKindWired) return;
  // Delegated: the tab buttons are re-rendered on every model/runner change.
  overlay.querySelector(".runner-tabs")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-runner]");
    if (!btn || btn.disabled) return;
    const rEl = $(pfx + "RUNNER");
    if (rEl) rEl.value = btn.dataset.runner || "";
    // Manual switch to whisper: aim the shared picker at the current size —
    // the dedicated select is hidden everywhere.
    if ((btn.dataset.runner || "") === "whisper") {
      const mEl = $(pfx + "MODEL_FILE");
      const size = ($(pfx + "WHISPER_MODEL")?.value || "").trim() || "large-v3";
      const want = `whisper/models--Systran--faster-whisper-${size}`;
      if (mEl && mEl.value !== want) {
        mEl.value = want;
        if (mEl.tagName === "SELECT") mcUpdateTrigger(mEl);
      }
    }
    applyCellKindUI(pfx);
  });
  // Model switch can change which runners fit the artifact — and picking a
  // safetensors artifact aims the vLLM runner at its local path.
  $(pfx + "MODEL_FILE")?.addEventListener("change", () => {
    const model = $(pfx + "MODEL_FILE")?.value || "";
    // A downloaded whisper model picked from the shared picker: flip the
    // runner to whisper with that size — same pattern as st→vLLM.
    const wh = model.match(/^whisper\/models--Systran--faster-whisper-(.+)$/);
    if (wh) {
      const rEl = $(pfx + "RUNNER");
      if (rEl) rEl.value = "whisper";
      const wEl = $(pfx + "WHISPER_MODEL");
      if (wEl) wEl.value = wh[1];
      applyCellKindUI(pfx);
      return;
    }
    const stRow = (state.artifacts || []).find((a) => a.path === model);
    // VLLM_MODEL is DERIVED from the picked model (folder for safetensors,
    // file path for gguf) — the field stays editable only for HF repo ids
    // with no local copy. An explicit pick always rewrites it, like ALIAS.
    // Controller cells only: these are controller paths, clients don't have them.
    const vmEl = $(pfx + "VLLM_MODEL");
    if (vmEl && model && pfx !== "tr-") {
      const base = (state.paths?.modelsDir || effectiveModelsDir(state.config) || "").replace(/\/+$/, "");
      if (stRow) vmEl.value = base + "/" + stRow.path;
      else if (model.toLowerCase().endsWith(".gguf")) vmEl.value = base + "/" + model;
    }
    const cur = runnerRegistry().find((r) => r.id === effectiveRunnerId(pfx));
    if (cur && !runnerAvailability(cur, pfx).ok) {
      // The active runner can't launch this artifact — jump to the first that can.
      const fit = runnerRegistry().find((r) => runnerAvailability(r, pfx).ok);
      const rEl = $(pfx + "RUNNER");
      if (fit && rEl) rEl.value = fit.id;
      applyCellKindUI(pfx);
    } else {
      renderRunnerTabs(pfx);
      if (effectiveRunnerId(pfx) === "vllm") renderCommandCellPreview(pfx);
    }
  });
  // Command-tab conveniences: preset dropdown + live preview on edit.
  populateCommandPresets(pfx);
  ["COMMAND", "ENV", "WORKDIR", "HEALTH_PATH",
   "VLLM_MODEL", "MAX_MODEL_LEN", "GPU_MEMORY_UTILIZATION", "QUANTIZATION", "DTYPE", "TENSOR_PARALLEL",
   "WHISPER_MODEL"].forEach((k) => {
    const el = $(pfx + k);
    if (el) {
      el.addEventListener("input", () => renderCommandCellPreview(pfx));
      el.addEventListener("change", () => renderCommandCellPreview(pfx));
    }
  });
  overlay.dataset.cellKindWired = "1";
}

export const COMMAND_PRESETS = [
  { id: "", labelKey: "cmdPresetPlaceholder" },   // t() at render — module scope hits the i18n TDZ
  // Standardized on faster-whisper (fastest on NVIDIA GPU). run_whisper.sh uses
  // the ~/wsr venv and puts cuDNN/cuBLAS on LD_LIBRARY_PATH; the agent installer
  // auto-provisions it, so this one preset works on every GPU host.
  { id: "whisper", label: "whisper · faster-whisper (large-v3)",
    COMMAND: "bash ~/run_whisper.sh $PORT large-v3", HEALTH_PATH: "/health" },
  // Voice-clone TTS cells: one server file, the engine is picked per cell
  // (scripts/install-tts.sh drops ~/run_tts.sh + ffmpeg; the engine venv and
  // model self-install on first start — 10–20 min — unless pre-warmed with
  // install-tts.sh --prewarm). POST /v1/audio/speech-clone: text+lang+ref wav.
  { id: "tts-xtts", label: "tts · XTTS-v2 (voice clone)",
    COMMAND: "bash ~/run_tts.sh $PORT xtts", HEALTH_PATH: "/health" },
  { id: "tts-f5", label: "tts · F5-TTS (voice clone)",
    COMMAND: "bash ~/run_tts.sh $PORT f5", HEALTH_PATH: "/health" },
  { id: "tts-cosyvoice", label: "tts · CosyVoice2 (voice clone)",
    COMMAND: "bash ~/run_tts.sh $PORT cosyvoice", HEALTH_PATH: "/health" },
];

export function populateCommandPresets(pfx) {
  const sel = $(pfx + "CMD_PRESET");
  if (!sel || sel.dataset.filled) return;
  sel.innerHTML = COMMAND_PRESETS.map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.labelKey ? t(p.labelKey) : p.label)}</option>`).join("");
  sel.dataset.filled = "1";
  sel.addEventListener("change", () => {
    const p = COMMAND_PRESETS.find((x) => x.id === sel.value);
    sel.value = "";
    if (!p || !p.id) return;
    ["COMMAND", "ENV", "WORKDIR", "HEALTH_PATH"].forEach((k) => {
      const el = $(pfx + k);
      if (el) el.value = p[k] || "";
    });
    renderCommandCellPreview(pfx);
  });
}

export function _commandCellSlot(pfx) {
  const port = pfx === "te-" ? _teCellPort : (pfx === "tr-" ? _trCellPort : "");
  if (!port) return null;
  const hostId = pfx === "tr-" ? _trHostId : "skynet";
  return (topology?.nodes || [])
    .flatMap((n) => n.servers || [])
    .find((s) => s.isSlot && String(s.port) === String(port) &&
                 (pfx === "te-" ? s.isController : String(s.clientId || "") === String(hostId))) || null;
}

// Mirror of build_vllm_command() in caravan/admin/runners.py — the backend
// renders the real script; this only feeds the NEW COMMAND preview pane.
export function buildVllmCommandPreview(pfx) {
  const v = (id) => ($(pfx + id)?.value || "").trim();
  const model = v("VLLM_MODEL");
  const parts = ["$HOME/vllm-venv/bin/vllm", "serve", model || "…", "--host", "0.0.0.0", "--port", '"$PORT"'];
  const served = v("ALIAS") || (model ? model.split("/").pop().toLowerCase() : "");
  if (served) parts.push("--served-model-name", served);
  if (v("MAX_MODEL_LEN")) parts.push("--max-model-len", v("MAX_MODEL_LEN"));
  if (v("GPU_MEMORY_UTILIZATION")) parts.push("--gpu-memory-utilization", v("GPU_MEMORY_UTILIZATION"));
  const quant = v("QUANTIZATION").toLowerCase();
  if (quant && quant !== "auto") parts.push("--quantization", quant);
  const dtype = v("DTYPE").toLowerCase();
  if (dtype && dtype !== "auto") parts.push("--dtype", dtype);
  const tp = v("TENSOR_PARALLEL");
  if (tp && tp !== "0" && tp !== "1") parts.push("--tensor-parallel-size", tp);
  return parts.join(" ");
}

export function _buildCommandExecPreview(pfx) {
  const port = $(pfx + "PORT")?.value || (pfx === "te-" ? _teCellPort : _trCellPort) || "PORT";
  if (effectiveRunnerId(pfx) === "vllm") {
    return [`export PORT=${port}`,
            "# first start on a host provisions ~/vllm-venv (several minutes)",
            `exec ${buildVllmCommandPreview(pfx)}`].join("\n");
  }
  if (effectiveRunnerId(pfx) === "whisper") {
    const size = ($(pfx + "WHISPER_MODEL")?.value || "").trim() || "large-v3";
    return [`export PORT=${port}`,
            "# model downloads on first start into <models root>/whisper",
            `exec env HUGGINGFACE_HUB_CACHE="\${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper" bash $HOME/run_whisper.sh "$PORT" ${size}`].join("\n");
  }
  const cmd = ($(pfx + "COMMAND")?.value || "").trim().replace(/^\s*exec\s+/, "");
  const lines = [`export PORT=${port}`];
  ($(pfx + "ENV")?.value || "").split(/[\n,]/).forEach((raw) => {
    const item = raw.trim();
    if (!item || item.startsWith("#") || !item.includes("=")) return;
    const i = item.indexOf("=");
    const k = item.slice(0, i).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k)) return;
    lines.push(`export ${k}="${item.slice(i + 1).trim()}"`);
  });
  const wd = ($(pfx + "WORKDIR")?.value || "").trim();
  if (wd) lines.push(`cd ${wd}`);
  lines.push(cmd ? `exec ${cmd}` : "exec …");
  return lines.join("\n");
}

export function renderCommandCellPreview(pfx) {
  const prev = $(pfx + "cmdPreview");
  if (prev) prev.textContent = _buildCommandExecPreview(pfx);
  const slot = _commandCellSlot(pfx);
  const cur = $(pfx + "cmdCurrent");
  if (cur) {
    const saved = ((slot && slot.slotConfig && slot.slotConfig.COMMAND) || "").trim();
    cur.textContent = saved || t("cmdNotSavedYet");
  }
  const hist = $(pfx + "cmdHistory");
  if (hist) {
    const items = (slot && slot.commandHistory) || [];
    if (!items.length) {
      hist.innerHTML = `<div class="cmd-history-empty">${t("cmdHistoryEmpty")}</div>`;
    } else {
      hist.innerHTML = items.map((h, i) => {
        const when = h.ts ? new Date(h.ts * 1000).toLocaleString() : "";
        return `<div class="cmd-history-item"><code class="cmd-history-cmd">${escapeHtml(h.command || "")}</code>`
          + `<div class="cmd-history-row"><span class="cmd-history-when">${escapeHtml(when)}</span>`
          + `<button type="button" class="cmd-history-revert" data-cmd-revert="${i}">↺ revert</button></div></div>`;
      }).join("");
      hist.querySelectorAll("[data-cmd-revert]").forEach((b) => {
        b.addEventListener("click", () => {
          const h = items[parseInt(b.dataset.cmdRevert, 10)];
          if (!h) return;
          const set = (k, v) => { const el = $(pfx + k); if (el) el.value = v || ""; };
          set("COMMAND", h.command); set("ENV", h.env); set("WORKDIR", h.workdir); set("HEALTH_PATH", h.healthPath);
          renderCommandCellPreview(pfx);
        });
      });
    }
  }
}

