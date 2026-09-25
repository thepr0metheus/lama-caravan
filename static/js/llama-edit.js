// The cell editor (tr-): runner tabs, command presets, the command preview, the confirm modal.
import { settleAppConfirm } from "./dialogs.js";
import {
  _cmdBaselineTokens,
  effectiveModelsDir,
  formatCmdline,
  renderCommandPreview,
} from "./command-preview.js";
import { modelFields, numericFields, toggleFields } from "./constants.js";
import {
  mcUpdateTrigger,
  readConfigForm,
  renderModelInsight,
  renderModelSelects,
  syncAllToggleLabels,
  syncPortChipsEl,
  syncToggleLabel,
  toggleChecked,
} from "./form.js";
import { fieldHelp, t } from "./i18n.js";
import { currentComputeMode, refreshAsidePanels, refreshComputeTarget } from "./memory.js";
import { _trCellPort, _trHostId, formOnControllerMachine } from "./remote-cells.js";
import { state, topology, ui } from "./state.js";
import { $, api, escapeHtml } from "./utils.js";

// Runner tabs (labels + trade-off tooltips + the benefits line) and the
// command-aside preview are rebuilt purely from state/t() — safe to re-render
// on language switch while the cell editor is open. Form inputs live outside
// these subtrees, so no edits are lost.
window.addEventListener("caravan:langchange", () => {
  const overlay = _cellKindOverlay("tr-");
  if (!overlay || overlay.hidden) return;
  renderRunnerTabs("tr-");
  refreshComputeTarget("tr-");
  if (effectiveRunnerId("tr-") !== "llama-server") renderCommandCellPreview("tr-");
});
export const _editCmdSeq = {};

// Fill a form's "current command" panel (<pfx>currentCmdline) and set the diff
// baseline for its New-Command preview, then (re)render the preview. The baseline
// is the form's CURRENT command, so editing a field highlights only what actually
// changed. Modes:
//   • "cell" — a configured cell: build its command from the form's initial
//     config via the canonical builder, so an unedited form shows "no changes"
//     and edits highlight precisely;
//   • "new"  — a freshly reserved / brand-new server: no prior command, every flag
//     reads as added.
// (A third, "main" — the controller's own running service — went with the
// controller's own cells in step 6.9.)
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

export function applyConfigToForm(config, pfx = "") {
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
  const msEl = $(pfx + "MOONSHINE_MODEL");
  if (msEl) msEl.value = config.MOONSHINE_MODEL || "en";
  // Everything else inside a runner panel, keyed by the field's own id. This
  // was a hand-written list and it went stale exactly as such lists do: the
  // seamless and translate panels were never added, so a cell saved with
  // SEAMLESS_TGT_LANG=eng opened showing the select's default "rus" — the form
  // presenting its own default as the cell's setting, and Apply silently
  // retargeting the cell. A new panel is now populated by existing.
  ["commandFields", "vllmFields", "whisperFields", "moonshineFields",
   "seamlessFields", "translateFields"].forEach((panel) => {
    $(pfx + panel)?.querySelectorAll("input, select, textarea").forEach((el) => {
      const key = String(el.id || "").slice(pfx.length);
      if (!key || !(key in config)) return;
      if (el.type === "checkbox") el.checked = !!config[key];
      else el.value = config[key] ?? "";
    });
  });
  // vLLM/whisper cells clear MODEL_FILE on save, and merging with the global
  // config would leak the main service's model into the picker. So the picker
  // ALWAYS shows the cell's own artifact (vLLM with a local path) or nothing
  // (HF repo id / whisper, whose model is a size name) — never the leak.
  const _rid = String(config.RUNNER || "").toLowerCase();
  if (_rid === "vllm" || _rid === "whisper" || _rid === "moonshine" || _rid === "translate") {
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
    if (_rid === "moonshine") {
      const lang = String(config.MOONSHINE_MODEL || "").trim().toLowerCase() || "en";
      rel = `moonshine/${lang}`;
    }
    if (_rid === "translate") {
      const repo = String(config.TRANSLATE_MODEL || "").trim() || "facebook/nllb-200-distilled-600M";
      rel = `translate/models--${repo.replace("/", "--")}`;
    }
    const mEl = $(pfx + "MODEL_FILE");
    if (mEl) {
      mEl.value = rel;
      if (mEl.tagName === "SELECT") mcUpdateTrigger(mEl);
    }
  }
  const envEl = $(pfx + "ENV");
  if (envEl) envEl.value = config.ENV || "";
  const devSel = $(pfx + "CELL_DEVICE");
  if (devSel) devSel.value = _envDeviceState(config.ENV || "", config.COMMAND || "");
  syncCmdExtras(pfx);
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

export function closeConfirmModal() {
  settleAppConfirm(false);
  ui.pendingConfirm = null;
  $("confirmOverlay").hidden = true;
  // Reset button state so next caller starts clean (danger/non-danger).
  $("confirmDelete").classList.remove("danger");
}

// ── Generic command cell: toggle a cell config form between llama-server fields
// and a single raw COMMAND. The one cell form is the scout's (tr-); the
// controller's own (te-) went with its cells in step 6.9. ──
export function _cellKindOverlay(pfx) {
  return pfx === "tr-" ? $("llamaRemoteEditOverlay") : null;
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
  // Mirrors `runner_id` in caravan/domain/runner.py: same trim, same lower-case,
  // on both fields. It used to differ — RUNNER kept its case and CELL_KIND was
  // compared raw — so a config the SERVER runs as whisper was previewed here as
  // something else entirely, and " command " was drawn as a llama cell. The same
  // config must not mean two different cells depending on who reads it.
  const explicit = ($(pfx + "RUNNER")?.value || "").trim().toLowerCase();
  if (explicit) return explicit;
  const kind = ($(pfx + "CELL_KIND")?.value || "").trim().toLowerCase();
  return kind === "command" ? "custom" : "llama-server";
}

// What KIND of artifact a MODEL_FILE value names. The extension is not enough:
// an LLM and a speech recognizer are both ".gguf", and llama-server can no more
// load GigaAM than transcribe.cpp can load Qwen. The picker already separates
// them by the file's own stt.* metadata, so the tabs read the same signal.
//
// Returns "" for anything we cannot classify, and "" NEVER blocks a tab. A
// remote form can hold a path that is not in the controller's model list, and
// greying a runner the user may well be right about is worse than letting the
// start fail with the engine's own message.
export function artifactKind(model) {
  const path = String(model || "").trim();
  if (!path) return "";
  if (path.startsWith("moonshine/")) return "moonshine-lang";
  if (path.startsWith("whisper/models--Systran--faster-whisper-")) return "whisper-size";
  if (path.startsWith("translate/models--")) return "nllb-repo";
  if (!path.toLowerCase().endsWith(".gguf")) {
    // A SeamlessM4T checkpoint gets its OWN kind, not the generic one. If it
    // answered "safetensors", the runner picker's "a runner that names this
    // kind wins" rule would drag every ST folder — Qwen, anything — onto the
    // seamless runner the moment it was selected.
    const st = (state.artifacts || []).find((r) => r.path === path);
    return String(st?.arch || "").startsWith("seamless_m4t") ? "seamless-st" : "safetensors";
  }
  const row = (state.models || []).find((r) => r.path === path);
  if (!row) return "";                       // unknown file — see above
  return (row.ggufMeta || {}).sttVariant ? "asr-gguf" : "llm-gguf";
}

const KIND_REASON = {
  "llm-gguf": "runnerNeedsLlmGguf",
  "asr-gguf": "runnerNeedsAsrGguf",
  "whisper-size": "runnerNeedsWhisperSize",
  "moonshine-lang": "runnerNeedsMoonshineLang",
  "seamless-st": "runnerNeedsSeamlessSt",
  "nllb-repo": "runnerNeedsNllbRepo",
};

// Can this runner launch the currently selected artifact? "*" accepts anything —
// vLLM and custom read their artifact from somewhere other than MODEL_FILE, so
// what sits in that field cannot disqualify them.
function runnerAvailability(runner, pfx) {
  // A form whose machine does not read the controller's models tree cannot
  // offer a directory checkpoint: the scout's model cache is .gguf throughout —
  // download, listing and eviction all key on that suffix. Leaving the runner
  // selectable there produced a panel with nothing to pick, which reads as
  // broken rather than unsupported. (formOnControllerMachine.)
  if (!formOnControllerMachine(pfx) && (runner.artifacts || []).includes("seamless-st")) {
    return { ok: false, reasonKey: "runnerControllerOnly" };
  }
  // `artifacts` is the current field; `formats` is what older registries carry.
  const accepts = runner.artifacts || null;
  if (!accepts) {
    const formats = runner.formats || [];
    if (formats.includes("*")) return { ok: true };
    const model = $(pfx + "MODEL_FILE")?.value || "";
    if (!model) return { ok: true };
    const fmt = model.toLowerCase().endsWith(".gguf") ? "gguf" : "other";
    return formats.includes(fmt) ? { ok: true } : { ok: false, reasonKey: "runnerNeedsGguf" };
  }
  if (accepts.includes("*")) return { ok: true };
  const kind = artifactKind($(pfx + "MODEL_FILE")?.value || "");
  if (!kind || accepts.includes(kind)) return { ok: true };
  return { ok: false, reasonKey: KIND_REASON[accepts[0]] || "runnerNeedsGguf" };
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
// picker), and always where the controller's paths don't apply (a machine that
// does not read its models tree — formOnControllerMachine).
function syncVllmModelVisibility(pfx) {
  const el = $(pfx + "VLLM_MODEL");
  if (!el) return;
  const picked = !!(($(pfx + "MODEL_FILE")?.value || "").trim());
  const hide = picked && formOnControllerMachine(pfx);
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
  "DTYPE", "TENSOR_PARALLEL", "WHISPER_MODEL", "MOONSHINE_MODEL",
  "SEAMLESS_TGT_LANG", "TRANSLATE_MODEL", "TRANSLATE_SRC_LANG", "TRANSLATE_TGT_LANG"];
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
                      "whisper": "runnerWhisperMinus", "moonshine": "runnerMoonshineMinus",
                      "transcribe": "runnerTranscribeMinus",
                      "seamless": "runnerSeamlessMinus",
                      "translate": "runnerTranslateMinus",
                      "custom": "runnerCustomMinus" };
  // A runner that says editorTab: false has no tab: an engine cell (Ollama, LM
  // Studio) is made on the reserve step, choosing the engine and its model.
  wrap.innerHTML = runnerRegistry().filter((r) => r.editorTab !== false).map((r) => {
    const avail = runnerAvailability(r, pfx);
    const label = (r.icon ? r.icon + " " : "") + t(r.labelKey || r.id);
    const tipParts = [r.benefitsKey ? t(r.benefitsKey) : "", MINUS_KEY[r.id] ? t(MINUS_KEY[r.id]) : ""];
    if (!avail.ok) tipParts.unshift(t(avail.reasonKey));
    const tip = tipParts.filter(Boolean).join("\n\n");
    return `<button type="button" class="cell-kind-btn${r.id === current ? " is-active" : ""}"` +
      ` data-t="cell-remote-runner-tab" data-t-id="${escapeHtml(r.id)}"` +
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
  // Does this runner read anything from the shared picker? It is the runner's
  // own declaration (sharedPicker in the registry), not a list maintained here:
  // "ignored" means the field is dead weight for it. A new cell inherits the
  // controller's MODEL_FILE like every other default, so an NLLB cell — whose
  // model is a repo id in its own field — opened showing a 21 GB gemma GGUF
  // with its size, its chips and its HF link, directly above a runner that
  // cannot load it. Dimming was not enough: a dimmed model card is still a
  // model card. Runners that ignore the picker do not get one.
  const _rmeta = runnerRegistry().find((r) => r.id === runner) || {};
  const ignoresPicker = (_rmeta.sharedPicker || (isCommand ? "ignored" : "source")) === "ignored";
  const modelField = $(pfx + "MODEL_FILE")?.closest(".field");
  if (modelField) {
    modelField.style.display = ignoresPicker ? "none" : "";
    modelField.classList.remove("runner-ignores-model");
  }
  // Keep both hidden inputs coherent: RUNNER is the source of truth, CELL_KIND
  // stays populated for legacy readers (scout, old backups, start.sh blocks).
  const rEl = $(pfx + "RUNNER");
  if (rEl) rEl.value = runner;
  kindEl.value = isCommand ? "command" : "";
  renderRunnerTabs(pfx);
  const isVllm = runner === "vllm";
  const isWhisper = runner === "whisper";
  const isMoonshine = runner === "moonshine";
  // transcribe hides the llama flags like every other command-path runner, but
  // it is the only one that genuinely CONSUMES the shared model picker — its
  // model is a GGUF path, so nothing dims and nothing gets cleared on save.
  const isTranscribe = runner === "transcribe";
  // seamless behaves like transcribe: a command-path runner that genuinely
  // consumes the shared picker — its model is a downloaded ST directory.
  const isSeamless = runner === "seamless";
  // translate takes no MODEL_FILE at all: its model is a repo id in its own
  // field, so the shared picker is irrelevant to it — like vLLM.
  const isTranslate = runner === "translate";
  const nonLlama = isCommand || isVllm || isWhisper || isMoonshine || isTranscribe
                   || isSeamless || isTranslate;
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
  // Same pattern for moonshine: the LANGUAGE is picked in the shared model
  // picker; the container stays as the hidden carrier of MOONSHINE_MODEL.
  const moonshineFields = $(pfx + "moonshineFields");
  if (moonshineFields) moonshineFields.style.display = "none";
  // Unlike whisper/moonshine, seamless has a real setting of its own — the
  // language it translates INTO — so its block is shown, not just carried.
  const seamlessFields = $(pfx + "seamlessFields");
  if (seamlessFields) seamlessFields.style.display = (isSeamless && formOnControllerMachine(pfx)) ? "" : "none";
  const translateFields = $(pfx + "translateFields");
  if (translateFields) translateFields.style.display = isTranslate ? "" : "none";
  // TRANSLATE_MODEL is now picked in the SHARED picker (a 🔄 row per NLLB
  // checkpoint) — two inputs for one value is what made the editor able to
  // disagree with itself in the first place. The input stays in the DOM as the
  // carrier of the value, like whisper's size and moonshine's language.
  const trModelField = $(pfx + "TRANSLATE_MODEL")?.closest(".field");
  if (trModelField) trModelField.style.display = "none";
  // Aside: llama VRAM/preview vs. the command preview + history (vllm/whisper
  // reuse the command aside — their exec line renders into the same preview).
  const llamaAside = $(pfx + "llamaAside");
  if (llamaAside) llamaAside.style.display = nonLlama ? "none" : "";
  const cmdAside = $(pfx + "commandAside");
  if (cmdAside) cmdAside.style.display = nonLlama ? "" : "none";
  if (nonLlama) renderCommandCellPreview(pfx);
  // The unified compute-target card sits above MODEL_FILE and serves EVERY
  // runner — repaint it so its available/disabled tiles follow the new runner.
  refreshComputeTarget(pfx);
  // The picker dims what the CURRENT runner cannot launch (a chat gguf under
  // transcribe, an ASR gguf under llama), so it has to be repainted here too —
  // otherwise the dimming still describes the runner you just left.
  renderModelSelects(pfx);
  // Runs on open and on every runner switch — the right beat to (re)decide
  // whether this window is editing something that is already live.
  syncRunningBeam(pfx);
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
    if ((btn.dataset.runner || "") === "moonshine") {
      const mEl = $(pfx + "MODEL_FILE");
      const lang = ($(pfx + "MOONSHINE_MODEL")?.value || "").trim().toLowerCase() || "en";
      const want = `moonshine/${lang}`;
      if (mEl && mEl.value !== want) {
        mEl.value = want;
        if (mEl.tagName === "SELECT") mcUpdateTrigger(mEl);
      }
      applyCellKindUI(pfx);
      return;
    }
    if ((btn.dataset.runner || "") === "translate") {
      const mEl = $(pfx + "MODEL_FILE");
      const repo = ($(pfx + "TRANSLATE_MODEL")?.value || "").trim() || "facebook/nllb-200-distilled-600M";
      const want = `translate/models--${repo.replace("/", "--")}`;
      if (mEl && mEl.value !== want) {
        mEl.value = want;
        if (mEl.tagName === "SELECT") mcUpdateTrigger(mEl);
      }
    }
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
    const ms = model.match(/^moonshine\/([a-z]{2})$/);
    if (ms) {
      const rEl = $(pfx + "RUNNER");
      if (rEl) rEl.value = "moonshine";
      const mEl2 = $(pfx + "MOONSHINE_MODEL");
      if (mEl2) mEl2.value = ms[1];
      applyCellKindUI(pfx);
      return;
    }
    const tr = model.match(/^translate\/models--(.+)$/);
    if (tr) {
      const rEl = $(pfx + "RUNNER");
      if (rEl) rEl.value = "translate";
      const tEl = $(pfx + "TRANSLATE_MODEL");
      if (tEl) tEl.value = tr[1].replace("--", "/");
      applyCellKindUI(pfx);
      return;
    }
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
    // Only where the target reads the controller's models tree: these are its
    // paths, other machines don't have them (formOnControllerMachine).
    const vmEl = $(pfx + "VLLM_MODEL");
    if (vmEl && model && formOnControllerMachine(pfx)) {
      const base = (state.paths?.modelsDir || effectiveModelsDir(state.config) || "").replace(/\/+$/, "");
      if (stRow) vmEl.value = base + "/" + stRow.path;
      else if (model.toLowerCase().endsWith(".gguf")) vmEl.value = base + "/" + model;
    }
    const cur = runnerRegistry().find((r) => r.id === effectiveRunnerId(pfx));
    if (cur && !runnerAvailability(cur, pfx).ok) {
      // The active runner can't launch this artifact — jump to one that can.
      // A runner that names this KIND wins over one that merely accepts
      // anything: picking GigaAM must land on transcribe.cpp, and "first
      // available" would hand it to vLLM, which sits earlier and takes "*".
      const kind = artifactKind($(pfx + "MODEL_FILE")?.value || "");
      const named = kind && runnerRegistry().find((r) => (r.artifacts || []).includes(kind));
      const fit = named || runnerRegistry().find((r) => runnerAvailability(r, pfx).ok);
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
  // Device pin: the unified compute-target card above MODEL_FILE writes ENV for
  // command-path runners (see applyComputeMode → _applyDeviceToEnv). A hand-typed
  // ENV pin feeds back into the card so the two never disagree.
  const devSel = $(pfx + "CELL_DEVICE");
  const envEl = $(pfx + "ENV");
  if (envEl) {
    envEl.addEventListener("input", () => {
      if (devSel) devSel.value = _envDeviceState(envEl.value, $(pfx + "COMMAND")?.value || "");
      refreshComputeTarget(pfx);
    });
  }
  // Health switch: off = clear the path (plain TCP probe), on = /health seed.
  const healthTog = $(pfx + "HEALTH_TOGGLE");
  const healthPath = $(pfx + "HEALTH_PATH");
  if (healthTog && healthPath) {
    healthTog.addEventListener("change", () => {
      healthPath.disabled = !healthTog.checked;
      if (!healthTog.checked) healthPath.value = "";
      else if (!healthPath.value.trim()) healthPath.value = "/health";
      healthPath.dispatchEvent(new Event("input", { bubbles: true }));
      if (healthTog.checked) healthPath.focus();
    });
  }
  overlay.dataset.cellKindWired = "1";
}

// Device pin selector (command/whisper/vLLM cells) — pure sugar over ENV so
// neither launcher (controller launch.py, scout) needs to change: cpu writes
// TTS_DEVICE=cpu + CUDA_VISIBLE_DEVICES= (hard, runner-agnostic), gpu writes
// TTS_DEVICE=cuda, auto removes both and leaves the runner's own probe.
export function _envDeviceState(envStr, cmdStr) {
  const all = `${envStr}\n${cmdStr}`;
  if (/(?:^|[\s;,])(?:TTS_DEVICE|DEVICE)=cpu\b|--device[=\s]+cpu\b/i.test(all)
      || /(?:^|[\n,;\s])CUDA_VISIBLE_DEVICES=(?:""|'')?(?:[\n,;\s]|$)/.test(envStr)) return "cpu";
  if (/(?:^|[\s;,])(?:TTS_DEVICE|DEVICE)=(?:cuda|gpu)\b|--device[=\s]+(?:cuda|gpu)\b/i.test(all)) return "gpu";
  return "auto";
}

export function _applyDeviceToEnv(envStr, mode) {
  const rows = String(envStr || "").split(/[\n,]/).map((s) => s.trim()).filter(Boolean)
    .filter((r) => !/^(TTS_DEVICE|CUDA_VISIBLE_DEVICES)=/i.test(r));
  if (mode === "cpu") rows.push("TTS_DEVICE=cpu", "CUDA_VISIBLE_DEVICES=");
  if (mode === "gpu") rows.push("TTS_DEVICE=cuda");
  return rows.join("\n");
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
  //
  // The licence is in the label because it differs per engine and it is the
  // model's, not the code's: XTTS-v2 ships under the Coqui Public Model
  // Licence, which forbids commercial use, and F5-TTS is MIT code over a base
  // model trained on CC-BY-NC data. Someone picking an engine from a dropdown
  // has no other moment to learn that — cells/tts_server.py says it too, but
  // nobody reads a server file before clicking a preset.
  { id: "tts-xtts", label: "tts · XTTS-v2 (voice clone) — non-commercial",
    COMMAND: "bash ~/run_tts.sh $PORT xtts", HEALTH_PATH: "/health" },
  { id: "tts-f5", label: "tts · F5-TTS (voice clone) — MIT code, NC base model",
    COMMAND: "bash ~/run_tts.sh $PORT f5", HEALTH_PATH: "/health" },
  { id: "tts-cosyvoice", label: "tts · CosyVoice2 (voice clone) — Apache-2.0",
    COMMAND: "bash ~/run_tts.sh $PORT cosyvoice", HEALTH_PATH: "/health" },
];

// Command-tab field sync: the device now lives in the unified compute-target
// card above MODEL_FILE (repaint it), and the health switch mirrors whether
// HEALTH_PATH is set (off = plain TCP port probe).
export function syncCmdExtras(pfx) {
  refreshComputeTarget(pfx);
  const hp = $(pfx + "HEALTH_PATH");
  const tog = $(pfx + "HEALTH_TOGGLE");
  if (hp && tog) {
    tog.checked = !!hp.value.trim();
    hp.disabled = !tog.checked;
  }
}

export function populateCommandPresets(pfx) {
  const sel = $(pfx + "CMD_PRESET");
  if (!sel || sel.dataset.filled) return;
  sel.innerHTML = COMMAND_PRESETS.map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.labelKey ? t(p.labelKey) : p.label)}</option>`).join("");
  sel.dataset.filled = "1";
  const applyPreset = (p) => {
    ["COMMAND", "ENV", "WORKDIR", "HEALTH_PATH"].forEach((k) => {
      const el = $(pfx + k);
      if (el) el.value = p[k] || "";
    });
    const devSel = $(pfx + "CELL_DEVICE");
    if (devSel) devSel.value = _envDeviceState(p.ENV || "", p.COMMAND || "");
    syncCmdExtras(pfx);
    renderCommandCellPreview(pfx);
  };
  sel.addEventListener("change", () => {
    const p = COMMAND_PRESETS.find((x) => x.id === sel.value);
    sel.value = "";
    if (p && p.id) applyPreset(p);
  });
  // Chips row — the visible face of the presets (the select stays for compat).
  const chips = $(pfx + "CMD_PRESET_CHIPS");
  if (chips && !chips.dataset.filled) {
    chips.innerHTML = COMMAND_PRESETS.filter((p) => p.id)
      .map((p) => `<button type="button" class="cmd-preset-chip" data-cmd-preset="${escapeHtml(p.id)}">${escapeHtml(p.label)}</button>`).join("");
    chips.dataset.filled = "1";
    chips.addEventListener("click", (e) => {
      const b = e.target.closest("[data-cmd-preset]");
      if (!b) return;
      const p = COMMAND_PRESETS.find((x) => x.id === b.dataset.cmdPreset);
      if (p) applyPreset(p);
    });
  }
}

export function _commandCellSlot(pfx) {
  const port = pfx === "tr-" ? _trCellPort : "";
  if (!port) return null;
  return (topology?.nodes || [])
    .flatMap((n) => n.servers || [])
    .find((s) => s.isSlot && String(s.port) === String(port) && String(s.clientId || "") === String(_trHostId)) || null;
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
  const port = $(pfx + "PORT")?.value || _trCellPort || "PORT";
  const runner = effectiveRunnerId(pfx);
  if (runner === "vllm") {
    return [`export PORT=${port}`,
            "# first start on a host provisions ~/vllm-venv (several minutes)",
            `exec ${buildVllmCommandPreview(pfx)}`].join("\n");
  }
  if (runner === "whisper") {
    const size = ($(pfx + "WHISPER_MODEL")?.value || "").trim() || "large-v3";
    return [`export PORT=${port}`,
            "# model downloads on first start into <models root>/whisper",
            `exec env HUGGINGFACE_HUB_CACHE="\${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/whisper" bash $HOME/run_whisper.sh "$PORT" ${size}`].join("\n");
  }
  if (runner === "transcribe") {
    const mf = ($(pfx + "MODEL_FILE")?.value || "").trim();
    const model = (mf && !mf.startsWith("/") && !mf.startsWith("$"))
      ? `"\${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/${mf}`
      : `"${mf || "…"}"`;
    return [`export PORT=${port}`,
            "# the engine and its venv come from scripts/install-transcribe.sh",
            `exec bash $HOME/run_transcribe.sh "$PORT" ${model}`].join("\n");
  }
  if (runner === "moonshine") {
    // This branch was missing: a moonshine cell showed the llama-server line,
    // which is a preview of a command it would never run — the operator reads
    // it as what will happen and it is simply another cell's command.
    const lang = ($(pfx + "MOONSHINE_MODEL")?.value || "en").trim() || "en";
    return [`export PORT=${port}`,
            "# first start provisions ~/moonshine-venv and fetches the model",
            `exec bash $HOME/run_moonshine.sh "$PORT" ${lang}`].join("\n");
  }
  if (runner === "translate") {
    const model = ($(pfx + "TRANSLATE_MODEL")?.value || "").trim()
      || "facebook/nllb-200-distilled-600M";
    // trim BEFORE the fallback, like the model line above and every other
    // runner here: with `|| ` first, a field holding only spaces is truthy,
    // survives the fallback, and trims down to nothing — the command then ended
    // with two blanks where the languages belong.
    const src = ($(pfx + "TRANSLATE_SRC_LANG")?.value || "").trim() || "eng_Latn";
    const tgt = ($(pfx + "TRANSLATE_TGT_LANG")?.value || "").trim() || "rus_Cyrl";
    return [`export PORT=${port}`,
            "# model downloads on first start into <models root>/translate",
            `exec env HUGGINGFACE_HUB_CACHE="\${LLAMA_MODELS_DIR:-$HOME/llama-model-cache}/translate" `
            + `bash $HOME/run_translate.sh "$PORT" ${model} ${src} ${tgt}`].join("\n");
  }
  if (runner === "seamless") {
    const mf = ($(pfx + "MODEL_FILE")?.value || "").trim();
    const model = (mf && !mf.startsWith("/") && !mf.startsWith("$"))
      ? `"\${LLAMA_MODELS_DIR:-$HOME/llama.cpp/models}"/${mf}`
      : `"${mf || "…"}"`;
    const tgt = ($(pfx + "SEAMLESS_TGT_LANG")?.value || "rus").trim() || "rus";
    return [`export PORT=${port}`,
            "# first start provisions ~/seamless-venv (torch + transformers)",
            `exec bash $HOME/run_seamless.sh "$PORT" ${model} ${tgt}`].join("\n");
  }
  // Runners this builder has no command for, told apart instead of being
  // swept into the custom branch. Both used to land there and print `exec …` —
  // a preview of a command that will never run, which the operator reads as
  // what will happen. llama-server's command is rendered by the CONTROLLER
  // (/api/llama-command-preview) and never came from here; an unknown runner is
  // a cell whose start this caravan does not know, which is what the server
  // already says in `UnknownRunner` (command_path = False).
  if (runner === "llama-server") {
    return [`export PORT=${port}`,
            "# llama-server: the controller renders this command, not this preview"].join("\n");
  }
  if (runner !== "custom") {
    return [`export PORT=${port}`,
            `# unknown runner "${runner}" — this caravan does not know how it starts`].join("\n");
  }
  // `exec` alone is not a command: the old pattern demanded whitespace after it,
  // so COMMAND="exec" survived the strip and came back out as `exec exec`.
  const cmd = ($(pfx + "COMMAND")?.value || "").trim().replace(/^\s*exec(?:\s+|$)/, "");
  const lines = [`export PORT=${port}`];
  ($(pfx + "ENV")?.value || "").split(/[\n,]/).forEach((raw) => {
    const item = raw.trim();
    if (!item || item.startsWith("#") || !item.includes("=")) return;
    const i = item.indexOf("=");
    const k = item.slice(0, i).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k)) return;
    // Escaped exactly as `command_cell_env_exports` escapes it in launch.py —
    // backslash and quote, and deliberately NOT `$`, so paths and spaces survive
    // while $VARS still expand. Unescaped, a value that already carried a quote
    // came out as ""quoted"": the preview showed shell the cell would never run.
    const v = item.slice(i + 1).trim().replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    lines.push(`export ${k}="${v}"`);
  });
  const wd = ($(pfx + "WORKDIR")?.value || "").trim();
  if (wd) lines.push(`cd ${wd}`);
  lines.push(cmd ? `exec ${cmd}` : "exec …");
  return lines.join("\n");
}

// ── Script preview: show the content of the .sh/.py the command points at ──
// Parsed from the BUILT exec preview (covers whisper's baked-in run_whisper.sh
// and any custom COMMAND). A cell of the controller's own machine has its
// files under the controller's home, read via /api/script-preview; any other
// machine's files live there — shown as a note until the scout grows a
// matching endpoint.
function _scriptTokenFromPreview(pfx) {
  const text = _buildCommandExecPreview(pfx);
  const execLine = text.split("\n").filter((l) => l.startsWith("exec ")).pop() || "";
  for (let tok of execLine.replace(/^exec\s+/, "").split(/\s+/)) {
    tok = tok.replace(/^["']|["']$/g, "").replace(/^env$/, "");
    if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(tok)) continue;           // env assignments
    if (tok.startsWith("-")) continue;                            // flags
    if (/\.(sh|bash|py)$/i.test(tok)) return tok.replace(/^\$HOME/, "~");
  }
  return "";
}

let _scriptPreviewSeq = 0;
function _refreshScriptPreview(pfx) {
  const meta = $(pfx + "scriptMeta");
  const pre = $(pfx + "scriptPreview");
  if (!meta || !pre) return;
  const panel = pre.closest(".panel");
  const tok = effectiveRunnerId(pfx) === "vllm" ? "" : _scriptTokenFromPreview(pfx);
  if (!tok) { if (panel) panel.style.display = "none"; return; }
  if (panel) panel.style.display = "";
  if (!formOnControllerMachine(pfx)) {
    meta.textContent = tok;
    pre.dataset.i18n = "scriptClientNote";
    pre.textContent = t("scriptClientNote");
    return;
  }
  const seq = ++_scriptPreviewSeq;
  api("/api/script-preview?path=" + encodeURIComponent(tok)).then((res) => {
    if (seq !== _scriptPreviewSeq) return;
    delete pre.dataset.i18n;
    meta.textContent = `${res.path} · ${res.size} B`;
    pre.textContent = res.content + (res.truncated ? "\n…" : "");
  }).catch((e) => {
    if (seq !== _scriptPreviewSeq) return;
    delete pre.dataset.i18n;
    meta.textContent = tok;
    pre.textContent = String(e && e.message || e);
  });
}

// The board rings a live cell with a border comet. The config window wears the
// same one when the cell it edits is already running, so "this is live — edits
// land on something serving traffic" reads identically in both places. Colour
// follows the board's rule: CPU cells run blue, everything else green.
export function syncRunningBeam(pfx) {
  const modal = _cellKindOverlay(pfx)?.querySelector(".topology-llama-edit-modal");
  if (!modal) return;
  const slot = _commandCellSlot(pfx);
  const live = !!slot && ["running", "warming"].includes(String(slot.phase || ""));
  const beam = modal.querySelector(":scope > .cell-beam");
  if (!live) { beam?.remove(); modal.style.removeProperty("--cell-accent"); return; }
  modal.style.setProperty("--cell-accent", currentComputeMode(pfx) === "cpu" ? "#4593ff" : "var(--ok, #3fb950)");
  if (!beam) {
    const el = document.createElement("div");
    el.className = "cell-beam cell-beam-modal";
    el.setAttribute("aria-hidden", "true");
    modal.prepend(el);
  }
}

export function renderCommandCellPreview(pfx) {
  // The aside panels ride the same refresh as the command preview, so they track
  // every edit: runner switch, model pick, device change, utilization tweak.
  refreshAsidePanels(pfx);
  const prev = $(pfx + "cmdPreview");
  if (prev) prev.textContent = _buildCommandExecPreview(pfx);
  _refreshScriptPreview(pfx);
  const slot = _commandCellSlot(pfx);
  const cur = $(pfx + "cmdCurrent");
  if (cur) {
    // savedCommand is the backend's own render of the saved config, so runners
    // that build their line from fields (vLLM, whisper, seamless, NLLB) show
    // what they actually run. COMMAND is the custom cell's copy of the same
    // thing and stays as the fallback for an older payload.
    const saved = ((slot && (slot.savedCommand
      || (slot.slotConfig && slot.slotConfig.COMMAND))) || "").trim();
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
          + `<button type="button" class="cmd-history-revert" data-cmd-revert="${i}">↺ ${escapeHtml(t("cmdHistoryRevert"))}</button></div></div>`;
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

