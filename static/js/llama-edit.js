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
import { t } from "./i18n.js";
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
export async function setEditCurrentCommand(pfx, mode) {
  const cur = $(pfx + "currentCmdline");
  const seq = (_editCmdSeq[pfx] = (_editCmdSeq[pfx] || 0) + 1);
  if (mode === "main") {
    const tokens = splitCommand(state.service?.cmdline || "");
    _cmdBaselineTokens[pfx] = tokens;
    if (cur) cur.textContent = tokens.length ? formatCmdline(tokens.join(" ")) : t("noRunningCommand");
    renderCommandPreview(pfx);
    return;
  }
  if (mode === "new") {
    _cmdBaselineTokens[pfx] = [];
    if (cur) cur.textContent = t("noRunningCommand");
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
    if (cur) cur.textContent = tokens.length ? formatCmdline(tokens.join(" ")) : t("noRunningCommand");
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
  const action = mode === "add" ? "Add" : "Edit";
  const titleEl = $("topologyLlamaEditTitle");
  if (titleEl) {
    titleEl.textContent = `${action} Llama Server — ${serverName}${gpuSuffix}`;
    // LOCAL badge next to title (not in actions bar)
    let badge = titleEl.parentElement.querySelector(".topo-edit-mode-badge");
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "topo-edit-mode-badge local";
      badge.textContent = "LOCAL";
      titleEl.after(badge);
    }
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
    if (k && k.value) { k.value = ""; applyCellKindUI("te-"); }
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
  const cmdEl = $(pfx + "COMMAND");
  if (cmdEl) cmdEl.value = config.COMMAND || "";
  const hpEl = $(pfx + "HEALTH_PATH");
  if (hpEl) hpEl.value = config.HEALTH_PATH || "";
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

export function applyCellKindUI(pfx) {
  const overlay = _cellKindOverlay(pfx);
  const kindEl = $(pfx + "CELL_KIND");
  if (!overlay || !kindEl) return;
  const isCommand = (kindEl.value || "") === "command";
  overlay.querySelectorAll(".cell-kind-btn").forEach((b) => {
    b.classList.toggle("is-active", (b.dataset.cellKind || "") === (isCommand ? "command" : ""));
  });
  // Use inline display, not the [hidden] attr: .field has a stylesheet `display`
  // rule that would otherwise keep the command fields visible in llama mode.
  const llamaFields = $(pfx + "llamaFields");
  if (llamaFields) llamaFields.style.display = isCommand ? "none" : "";
  const cmdFields = $(pfx + "commandFields");
  if (cmdFields) cmdFields.style.display = isCommand ? "" : "none";
  // Aside: llama VRAM/preview vs. the command preview + history.
  const llamaAside = $(pfx + "llamaAside");
  if (llamaAside) llamaAside.style.display = isCommand ? "none" : "";
  const cmdAside = $(pfx + "commandAside");
  if (cmdAside) cmdAside.style.display = isCommand ? "" : "none";
  if (isCommand) renderCommandCellPreview(pfx);
}

export function wireCellKindToggle(pfx) {
  const overlay = _cellKindOverlay(pfx);
  if (!overlay || overlay.dataset.cellKindWired) return;
  overlay.querySelectorAll(".cell-kind-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const kindEl = $(pfx + "CELL_KIND");
      if (kindEl) kindEl.value = btn.dataset.cellKind || "";
      applyCellKindUI(pfx);
    });
  });
  // Command-tab conveniences: preset dropdown + live preview on edit.
  populateCommandPresets(pfx);
  ["COMMAND", "ENV", "WORKDIR", "HEALTH_PATH"].forEach((k) => {
    const el = $(pfx + k);
    if (el) el.addEventListener("input", () => renderCommandCellPreview(pfx));
  });
  overlay.dataset.cellKindWired = "1";
}

export const COMMAND_PRESETS = [
  { id: "", label: "— preset —" },
  // Standardized on faster-whisper (fastest on NVIDIA GPU). run_whisper.sh uses
  // the ~/wsr venv and puts cuDNN/cuBLAS on LD_LIBRARY_PATH; the agent installer
  // auto-provisions it, so this one preset works on every GPU host.
  { id: "whisper", label: "whisper · faster-whisper (large-v3)",
    COMMAND: "bash ~/run_whisper.sh $PORT large-v3", HEALTH_PATH: "/health" },
];

export function populateCommandPresets(pfx) {
  const sel = $(pfx + "CMD_PRESET");
  if (!sel || sel.dataset.filled) return;
  sel.innerHTML = COMMAND_PRESETS.map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`).join("");
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

export function _buildCommandExecPreview(pfx) {
  const port = $(pfx + "PORT")?.value || (pfx === "te-" ? _teCellPort : _trCellPort) || "PORT";
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
    cur.textContent = saved || "— not saved yet";
  }
  const hist = $(pfx + "cmdHistory");
  if (hist) {
    const items = (slot && slot.commandHistory) || [];
    if (!items.length) {
      hist.innerHTML = `<div class="cmd-history-empty">No previous commands.</div>`;
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

