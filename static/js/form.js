// Launch-config form: fields, comboboxes, model insight, autofill, readConfigForm.
import { effectiveModelsDir, renderCommandPreview } from "./command-preview.js";
import {
  advancedGroups,
  advancedTabDefs,
  defaultOnOptionalToggles,
  dirtyOptionalToggles,
  fieldChoices,
  gemma4DefaultMmproj,
  gemma4DraftModel,
  modelFields,
  numericFields,
  optionalToggleFields,
  toggleFields,
} from "./constants.js";
import {
  attachFavStar,
  getFavFields,
  refreshFavoritesPanel,
  syncFavoriteMirrors,
  updateStarStates,
} from "./favorites.js";
import { bindCommandLocator, renderConfigSearch } from "./config-locator.js";
import { fieldHelp, labelWithTip, t } from "./i18n.js";
import { _commandCellSlot, gpuComputeCap, renderBackups, renderCommandCellPreview, runnerRegistry } from "./llama-edit.js";
import {
  applyComputeTarget,
  computeIsCpu,
  computeSelectedGpuIdx,
  currentComputeMode,
  shortGpuName,
  computeTargetGpus,
  estimateRuntimeMemoryGb,
  formatSizeGb,
  gpuFreeMiB,
  ramFit,
  ramFitForPfx,
  refreshComputeTarget,
  selectedModelRows,
  vramFit,
  vramFitForPfx,
} from "./memory.js";
import { _modelBenchKey, fetchPickerBenchBatch, serverBenchCache } from "./model-meta.js";
import { saveConfig } from "./polling.js";
import { _trCachedModels, _trClientCpu } from "./remote-cells.js";
import { state, topology } from "./state.js";
import { renderRuntime } from "./system-panels.js";
import { $, api, escapeHtml, formatBool, inferSpecType, toast } from "./utils.js";

export function syncToggleLabel(input) {
  const span = input?.closest(".check-row")?.querySelector("span");
  if (!span) return;
  // Stamp the state-matching key so applyLanguage() re-translates the label
  // in place when the language switches while the editor stays open.
  span.dataset.i18n = input.checked ? "enabled" : "disabled";
  span.textContent = t(span.dataset.i18n);
}

export function syncCompanionMuting(pfx = "") {
  const mmprojOn = $(pfx + "OFFLOAD_MMPROJ")?.checked;
  const specOn   = $(pfx + "SPEC_ENABLED")?.checked;
  const mmprojWrap = $(pfx + "MMPROJ_FILE")?.previousElementSibling;
  if (mmprojWrap?.classList.contains("mc-wrap"))
    mmprojWrap.classList.toggle("is-muted", !mmprojOn);
  const draftWrap = $(pfx + "SPEC_DRAFT_MODEL_FILE")?.previousElementSibling;
  if (draftWrap?.classList.contains("mc-wrap"))
    draftWrap.classList.toggle("is-muted", !specOn);
}

export function toggleChecked(field, config = state.config) {
  const value = config?.[field];
  if (value === undefined || value === null || String(value).trim() === "") {
    return defaultOnOptionalToggles.includes(field);
  }
  return formatBool(value);
}

export function syncAllToggleLabels(pfx = "") {
  toggleFields.forEach((field) => {
    const input = $(pfx + field);
    if (input) syncToggleLabel(input);
  });
}

export function option(path, label, selected) {
  const opt = document.createElement("option");
  opt.value = path;
  opt.textContent = label || path;
  opt.selected = selected;
  return opt;
}

// Re-run the tab bar's overflow bookkeeping for a form. Exported because the
// bar has no width until the modal holding it is actually shown: at build time
// the subtree is display:none, so the initial rAF measures zeros and the
// ResizeObserver does not fire for it either. The open path calls this.
export function syncConfigTabs(pfx) {
  const bar = $(pfx + "dynamicFields")?.querySelector(".advanced-tab-bar");
  if (!bar) return;
  bar.dispatchEvent(new Event("scroll"));      // drives the edge fades
  // Instant, not smooth: this is the opening frame, not a user gesture.
  bar.querySelector(".advanced-tab-btn.active")
    ?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

// The line under CTX_SIZE that says YaRN will auto-engage. Driven by the same
// numbers the backend uses: the field value against the model's native window.
// Self-sufficient: it resolves the native window from the MODEL_FILE field
// itself (and repairs the placeholder while at it), because an editor opened
// on an EXISTING cell never fires the model-change autofill that used to be
// the placeholder's only writer.
export function updateCtxYarnHint(pfx) {
  const ctxEl = $(pfx + "CTX_SIZE");
  const field = ctxEl?.closest(".field");
  const hint = field?.querySelector(".ctx-yarn-hint");
  const chip = field?.querySelector(".yarn-chip");
  if (!ctxEl || !hint) return;
  const modelVal = $(pfx + "MODEL_FILE")?.value || "";
  const native = Number(modelsByPath().get(modelVal)?.ggufMeta?.contextLength || 0)
    || Number(ctxEl.placeholder || 0);
  if (native > 0) ctxEl.placeholder = String(native);
  const val = Number(ctxEl.value || 0);
  const manual = !!($(pfx + "ROPE_SCALING")?.value || "").trim();
  const above = native > 0 && val > native;
  const factor = above ? Math.ceil((val / native) * 100) / 100 : 0;
  if (above && !manual) {
    hint.textContent = t("ctxYarnAutoHint", { native: String(native), factor: String(factor) });
    hint.hidden = false;
  } else {
    hint.hidden = true;
    hint.textContent = "";
  }
  if (chip) {
    if (manual) {
      chip.hidden = false;
      chip.className = "yarn-chip manual";
      chip.textContent = t("yarnChipManual");
      chip.title = t("yarnChipManualTitle");
    } else if (above) {
      chip.hidden = false;
      chip.className = "yarn-chip auto";
      chip.textContent = t("yarnChipAuto", { factor: String(factor) });
      chip.title = t("yarnChipAutoTitle");
    } else {
      chip.hidden = true;
    }
  }
}

// The chip's click: AUTO -> MANUAL materialises the derived values into the
// ROPE_* fields (so the operator can see and edit them); MANUAL -> AUTO clears
// them, handing the recipe back to the builder.
export function toggleYarnMode(pfx) {
  const ctxEl = $(pfx + "CTX_SIZE");
  const scalingEl = $(pfx + "ROPE_SCALING");
  const scaleEl = $(pfx + "ROPE_SCALE");
  if (!ctxEl || !scalingEl) return;
  if ((scalingEl.value || "").trim()) {
    scalingEl.value = "";
    if (scaleEl) scaleEl.value = "";
  } else {
    const native = Number(ctxEl.placeholder || 0);
    const val = Number(ctxEl.value || 0);
    if (!(native > 0 && val > native)) return;
    scalingEl.value = "yarn";
    if (scaleEl) scaleEl.value = String(Math.ceil((val / native) * 100) / 100);
  }
  scalingEl.dispatchEvent(new Event("change", { bubbles: true }));
  updateCtxYarnHint(pfx);
  renderCommandPreview(pfx);
}

export function modelsByPath() {
  return new Map((state.models || []).map((row) => [row.path, row]));
}

export function isQwenModelPath(path) {
  return /qwen/i.test(String(path || ""));
}

export function openClawQwenTemplatePath() {
  const templates = state.chatTemplates || [];
  const exact = templates.find((row) => /openclaw.*qwen|qwen.*openclaw/i.test(row.name || row.path));
  if (exact) return exact.path;
  return `${state.paths?.llamaHome || "~/llama.cpp"}/models/templates/openclaw-qwen.jinja`;
}

export function openClawQwenTemplateExists() {
  const wanted = openClawQwenTemplatePath();
  return (state.chatTemplates || []).some((row) => row.path === wanted);
}

export function isGemma4ModelPath(path) {
  return /gemma-4/i.test(String(path || ""));
}

export function selectedGemma4Mmproj() {
  const { selected } = selectedModelRows();
  return selected?.suggestedMmproj || gemma4DefaultMmproj;
}

export function badge(text, kind) {
  return `<span class="badge ${kind || ""}">${text}</span>`;
}

// `testId` stamps data-t on badges a test needs to find. Most badges describe a
// model and are asserted through the card that holds them; the ones that report
// a FAULT are the ones worth locating directly — see docs/testability.md.
export function mbadge(type, text, title, testId) {
  return `<span class="mbadge mbadge-${type}"${title ? ` title="${escapeHtml(title)}"` : ""}${
    testId ? ` data-t="${escapeHtml(testId)}"` : ""}>${text}</span>`;
}

// Format a model file's on-disk mtime (epoch seconds) as a short, locale-aware date.
// Returns "" when unknown so callers can skip rendering.
export function mcFormatMtime(mtime) {
  const sec = Number(mtime);
  if (!sec || sec <= 0) return "";
  try {
    return new Date(sec * 1000).toLocaleDateString(undefined, {
      year: "numeric", month: "short", day: "numeric",
    });
  } catch {
    return "";
  }
}

export function modelOptionLabel(row) {
  const tags = [];
  if (row.capability === "vision_likely") tags.push(t("visionLikelyBadge"));
  else tags.push(t("textBadge"));
  if (row.suggestedMmproj) tags.push(t("projectorFoundBadge"));
  return `${row.path} (${row.sizeGb} GB) - ${tags.join(" / ")}`;
}

// ── Model combobox ────────────────────────────────────────────────────────────
// Replaces native <select> for MODEL_FILE / MMPROJ_FILE with a searchable
// custom dropdown showing filename prominently, path dimmed, and status badges.

export function makeModelCombobox(selectEl) {
  if (!selectEl || selectEl.previousElementSibling?.classList.contains("mc-wrap")) return;

  const wrap = document.createElement("div");
  wrap.className = "mc-wrap";

  const trigger = document.createElement("div");
  trigger.className = "mc-trigger";
  // The native <select> stays in the DOM as the value carrier but is hidden
  // under this widget, so a hook on it can report a value and can never be
  // clicked or seen. The visible thing gets its own name: "<select's hook>-picker".
  // A hook that points at plumbing is a trap — the natural test to write
  // against it is one that cannot pass.
  if (selectEl.dataset.t) trigger.dataset.t = `${selectEl.dataset.t}-picker`;
  trigger.tabIndex = 0;
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  trigger.setAttribute("role", "combobox");
  // The SAME trap one level down. <label for="te-MODEL_FILE"> names the select
  // we are about to hide, so the name went with it and the thing that actually
  // takes focus had none. Point the trigger at that very label rather than
  // inventing a second string: the label is the name a sighted user reads, and
  // it stays correct on its own.
  const label = selectEl.id
    ? document.querySelector(`label[for="${CSS.escape(selectEl.id)}"]`)
    : null;
  if (label) {
    if (!label.id) label.id = `${selectEl.id}-label`;
    trigger.setAttribute("aria-labelledby", label.id);
  }

  const panel = document.createElement("div");
  panel.className = "mc-panel";
  panel.hidden = true;

  const search = document.createElement("input");
  search.type = "text";
  search.className = "mc-search";
  search.placeholder = t("filterPlaceholder");
  search.setAttribute("aria-label", t("a11yFilterModels"));
  search.setAttribute("autocomplete", "off");

  const list = document.createElement("div");
  list.className = "mc-list";
  list.setAttribute("role", "listbox");

  panel.appendChild(search);
  panel.appendChild(list);
  wrap.appendChild(trigger);
  wrap.appendChild(panel);
  selectEl.parentNode.insertBefore(wrap, selectEl);
  selectEl.style.display = "none";

  const openPanel = () => {
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    search.value = "";
    mcFilterList(list, "");
    const sel = list.querySelector(".mc-item.selected");
    if (sel) requestAnimationFrame(() => sel.scrollIntoView({ block: "nearest" }));
    requestAnimationFrame(() => search.focus());
  };
  const closePanel = () => {
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  };

  trigger.addEventListener("click", () => (panel.hidden ? openPanel() : closePanel()));
  trigger.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); panel.hidden ? openPanel() : closePanel(); }
    if (e.key === "ArrowDown") { e.preventDefault(); openPanel(); }
    if (e.key === "Escape") closePanel();
  });
  search.addEventListener("input", () => mcFilterList(list, search.value));
  search.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { closePanel(); trigger.focus(); }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      Array.from(list.children).find((el) => !el.hidden)?.focus();
    }
  });
  list.addEventListener("keydown", (e) => {
    const items = Array.from(list.children).filter((el) => !el.hidden);
    const idx = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[idx + 1]?.focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); idx > 0 ? items[idx - 1].focus() : search.focus(); }
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); document.activeElement?.click(); }
    if (e.key === "Escape") { closePanel(); trigger.focus(); }
  });
  document.addEventListener("click", (e) => { if (!wrap.contains(e.target) && !panel.hidden) closePanel(); }, true);
}

export function mcFilterList(list, query) {
  const q = (query || "").toLowerCase();
  Array.from(list.children).forEach((item) => {
    item.hidden = !!q && !(item.dataset.search || "").toLowerCase().includes(q);
  });
}

export function mcSelectItem(selectEl, value) {
  if (!selectEl) return;
  selectEl.value = value;
  selectEl.dispatchEvent(new Event("change", { bubbles: true }));
  const wrap = selectEl.previousElementSibling;
  if (!wrap?.classList.contains("mc-wrap")) return;
  wrap.querySelector(".mc-panel").hidden = true;
  wrap.querySelector(".mc-trigger").setAttribute("aria-expanded", "false");
  wrap.querySelectorAll(".mc-item").forEach((el) => el.classList.toggle("selected", el.dataset.value === value));
  mcUpdateTrigger(selectEl);
}

export function mcUpdateTrigger(selectEl) {
  if (!selectEl) return;
  const wrap = selectEl.previousElementSibling;
  if (!wrap?.classList.contains("mc-wrap")) return;
  const trigger = wrap.querySelector(".mc-trigger");
  const value = selectEl.value;
  const itemEl = value ? wrap.querySelector(`.mc-item[data-value="${CSS.escape(value)}"]`) : null;

  trigger.innerHTML = "";
  const inner = document.createElement("span");
  inner.className = "mc-trigger-inner";

  if (!value) {
    const emptyItem = wrap.querySelector(".mc-item[data-value='']");
    const txt = emptyItem?.querySelector(".mc-item-name")?.textContent || "—";
    inner.innerHTML = `<span class="mc-item-name muted">${escapeHtml(txt)}</span>`;
  } else if (itemEl) {
    const main = itemEl.querySelector(".mc-item-main");
    const path = itemEl.querySelector(".mc-item-path");
    if (main) inner.appendChild(main.cloneNode(true));
    if (path) { const p2 = path.cloneNode(true); p2.style.display = "block"; inner.appendChild(p2); }
  } else {
    const fname = value.split("/").pop();
    inner.innerHTML = `<span class="mc-item-name">${escapeHtml(fname)}</span>`;
  }

  const caret = document.createElement("span");
  caret.className = "mc-caret";
  caret.textContent = "▾";
  trigger.appendChild(inner);
  trigger.appendChild(caret);

  if (value && selectEl.id?.endsWith("MODEL_FILE")) {
    const parts = value.split("/");
    if (parts.length >= 2) {
      const repoId = parts[1] + "/" + parts[0];
      const hfBtn = document.createElement("a");
      hfBtn.className = "mc-hf-link";
      hfBtn.href = `/hf?q=${encodeURIComponent(repoId)}`;
      hfBtn.target = "_blank";
      hfBtn.title = `Open ${repoId} in HF Browser`;
      hfBtn.textContent = "HF ↗";
      hfBtn.addEventListener("click", e => e.stopPropagation());
      trigger.appendChild(hfBtn);
    }
  }
}

export function updateModelComboboxItems(selectEl, items, currentValue) {
  const wrap = selectEl?.previousElementSibling;
  if (!wrap?.classList.contains("mc-wrap")) return;
  const list = wrap.querySelector(".mc-list");
  list.innerHTML = "";

  items.forEach((item) => {
    const el = document.createElement("div");
    el.className = "mc-item" + (item.value === currentValue ? " selected" : "");
    el.dataset.value = item.value ?? "";
    el.dataset.search = (item.value || "") + " " + (item.label || "");
    el.tabIndex = -1;
    el.setAttribute("role", "option");

    if (!item.value) {
      el.innerHTML = `<div class="mc-item-main"><span class="mc-item-name muted">${escapeHtml(item.label || "—")}</span></div>`;
    } else {
      const parts = (item.value || "").split("/");
      let fname = parts.pop();
      let dir = parts.join("/");
      // Safetensors artifact: the value is a directory (<model>/<author>/<FORMAT>);
      // show the model folder as the name and the full dir underneath.
      if (item.kind === "st") { fname = item.stName || fname; dir = item.value; }
      if (item.kind === "moonshine") {
        fname = `moonshine · ${item.msLang}`;
      } else if (item.kind === "whisper") {
        fname = `whisper · ${item.whSize}`;
        dir = item.value;
        if (!item.whOnDisk) el.classList.add("mc-dim");
      }
      // Runner icons LEFT of the name — which engines can launch this artifact:
      // gguf → llama.cpp (native) + vLLM (experimental, dimmed); safetensors →
      // vLLM, dimmed when NO fleet GPU meets the format's compute requirement.
      let runnerIcons = "";
      if (item.kind === "st" && String(item.stArch || "").startsWith("seamless_m4t")) {
        // This branch exists because the one below assumes safetensors means
        // vLLM — true when ST arrived, and now wrong for at least one family.
        // vLLM does not load this architecture, so the ⚡ was not merely
        // confusing next to a 🌐 runner tab: it named an engine that cannot
        // start the thing, which is worse than naming none.
        runnerIcons = `<span class="mc-runners" title="seamless (speech → translated text)">🌐</span>`;
      } else if (item.kind === "st") {
        const reqs = (state.runners || []).find((r) => r.id === "vllm")?.formatRequirements || {};
        const need = reqs[String(item.stFormat || "").toLowerCase()];
        let blocked = false;
        if (need) {
          let maxCap = null;
          (topology?.nodes || []).forEach((n) => (n.gpus || []).forEach((g) => {
            const c = gpuComputeCap(g.name);
            if (c != null && (maxCap == null || c > maxCap)) maxCap = c;
          }));
          blocked = maxCap != null && maxCap < need;
        }
        runnerIcons = blocked
          ? `<span class="mc-runners" title="${escapeHtml(`${item.stFormat} · ${t("runnerNeedsCompute", { n: need })}`)}"><span class="mc-run-exp">⚡</span></span>`
          : `<span class="mc-runners" title="vLLM">⚡</span>`;
      } else if (item.kind === "moonshine") {
        runnerIcons = `<span class="mc-runners" title="moonshine (CPU speech-to-text)">🌙</span>`;
      } else if (item.kind === "whisper") {
        runnerIcons = `<span class="mc-runners" title="whisper (faster-whisper)">🎙</span>`;
      } else if (item.kind === "model" && item.sttVariant && !item.missing) {
        // An ASR gguf is NOT a llama artifact: llama-server cannot load it, so
        // it must not wear the llama icon that every other gguf row wears.
        runnerIcons = `<span class="mc-runners" title="transcribe.cpp (${escapeHtml(item.sttVariant)})">📝</span>`;
      } else if (item.kind === "model" && !item.missing) {
        runnerIcons = `<span class="mc-runners" title="llama.cpp · vLLM (experimental)">🦙<span class="mc-run-exp">⚡</span></span>`;
      }
      // The picker is shared by every runner, so a row that the CURRENT runner
      // cannot launch is dimmed rather than hidden — the operator still sees
      // the file is there, and sees why it is not the one to pick. The flag is
      // stamped by the caller: this renderer has no idea which form it serves.
      if (item.wrongRunner) el.classList.add("mc-dim");
      let badges = "";
      if (item.kind === "st") badges += mbadge("st", item.stFormat || "safetensors", "safetensors");
      if (item.cached) badges += mbadge("cached", t("cachedOnHost"));
      if (item.missing) {
        el.dataset.missing = "1";
        badges += mbadge("missing", "⚠ not found");
      } else if (item.kind === "model" && item.sttVariant) {
        // What it recognizes and in which languages — the two facts that decide
        // whether this is the file you want, both read out of the gguf.
        badges += mbadge("embed", "🗣 " + item.sttVariant);
        if (item.langs && item.langs.length) badges += mbadge("it", item.langs.join(" "));
      } else if (item.kind === "model") {
        if (/[_-](it|instruct|chat|instruction)(?:[_-]|$)/i.test(fname)) badges += mbadge("it", "🤖 it");
        if (item.capability === "vision_likely" || item.suggestedMmproj) badges += mbadge("mmproj", "📷 mmproj");
        if (item.suggestedDraft || item.hasMtpBuiltin) badges += mbadge("mtp", "⚡ mtp");
        if (item.aaScore != null) badges += mbadge("bench", `🧠 ${item.aaScore}`);
      }
      const dateStr = mcFormatMtime(item.mtime);
      el.innerHTML = `
        <div class="mc-item-main">
          ${runnerIcons}<span class="mc-item-name">${escapeHtml(fname)}</span>
          ${item.sizeLabel ? `<span class="mc-item-size">${escapeHtml(item.sizeLabel)}</span>` : item.sizeGb ? `<span class="mc-item-size">${item.sizeGb} GB</span>` : ""}
          ${badges}
          ${dateStr ? `<span class="mc-item-date" title="${t("addedOnDisk")}">${dateStr}</span>` : ""}
        </div>
        ${dir ? `<div class="mc-item-path">${escapeHtml(dir)}/</div>` : ""}`;
    }

    el.addEventListener("mousedown", (e) => e.preventDefault()); // keep search focused
    el.addEventListener("click", () => mcSelectItem(selectEl, item.value ?? ""));
    list.appendChild(el);
  });

  mcUpdateTrigger(selectEl);
}
// ── End model combobox ────────────────────────────────────────────────────────

export function renderModelSelects(pfx = "") {
  const models = state.models || [];
  // Preserve the form's current selection if the element already has a value (e.g. after
  // cache-list arrives and we re-render without losing what the user picked).
  const modelEl = $(pfx + "MODEL_FILE");
  const mmprojEl = $(pfx + "MMPROJ_FILE");
  const draftEl = $(pfx + "SPEC_DRAFT_MODEL_FILE");
  const currentModel = modelEl?.value || state.config.MODEL_FILE || "";
  let currentMmproj = mmprojEl?.value || state.config.MMPROJ_FILE || "";
  let currentDraft = draftEl?.value || state.config.SPEC_DRAFT_MODEL_FILE || "";
  if (!modelEl || !mmprojEl) return;

  // Init custom dropdowns (idempotent — wraps once, updates on subsequent calls)
  makeModelCombobox(modelEl);
  makeModelCombobox(mmprojEl);
  if (draftEl) makeModelCombobox(draftEl);

  // Model items
  const modelItems = models
    .filter((row) => row.kind === "model")
    .map((row) => ({
      value: row.path,
      sizeGb: row.sizeGb,
      mtime: row.mtime,
      kind: row.kind,
      capability: row.capability,
      suggestedMmproj: row.suggestedMmproj,
      suggestedDraft: row.suggestedDraft,
      hasMtpBuiltin: row.hasMtpBuiltin,
      detectedFamily: row.detectedFamily,
      familyDefaults: row.familyDefaults,
      // Speech weights, straight from the file's own stt.* metadata — the only
      // thing that separates the recognizer from forty chat models that look
      // exactly like it in a list of filenames.
      sttVariant: (row.ggufMeta || {}).sttVariant || "",
      langs: (row.ggufMeta || {}).languages || [],
      cached: pfx === "tr-" && _trCachedModels.has(row.path),
    }));
  // Safetensors artifacts (vLLM launches them). Controller forms only: client
  // hosts don't have the controller's models tree and the scout syncs gguf only.
  if (pfx !== "tr-") {
    (state.artifacts || []).forEach((row) => modelItems.push({
      value: row.path,
      sizeGb: row.sizeGb,
      mtime: row.mtime,
      kind: "st",
      stName: row.name,
      stFormat: row.format,
      stArch: row.arch || "",
    }));
  }
  // Whisper models join the same picker (🎙) on EVERY form: the "model" is a
  // size name and faster-whisper downloads it on the target host itself.
  // Dimming marks sizes missing from the CONTROLLER's disk — client (tr-)
  // caches are unknown here, so their rows never dim.
  {
    const have = new Set(state.whisperOnDisk || []);
    [["tiny", "75 MB"], ["base", "145 MB"], ["small", "480 MB"], ["medium", "1.5 GB"],
     ["large-v3", "3 GB"], ["large-v3-turbo", "1.6 GB"], ["distil-large-v3", "1.5 GB"]]
      .forEach(([size, sizeLabel]) => modelItems.push({
        value: `whisper/models--Systran--faster-whisper-${size}`,
        kind: "whisper",
        whSize: size,
        sizeLabel,
        whOnDisk: pfx === "tr-" || have.has(size),
        mtime: 0,
      }));
  }
  // Moonshine languages join the picker too (🌙): CPU-only STT, the model is a
  // LANGUAGE code and downloads itself on the target host. en is MIT; the rest
  // ship under the free Moonshine Community License — said right on the row.
  {
    [["en", "MIT · ~250 MB"], ["es", "Community license"], ["zh", "Community license"],
     ["ja", "Community license"], ["ko", "Community license"], ["vi", "Community license"],
     ["uk", "Community license"], ["ar", "Community license"]]
      .forEach(([lang, sizeLabel]) => modelItems.push({
        value: `moonshine/${lang}`,
        kind: "moonshine",
        msLang: lang,
        sizeLabel,
        whOnDisk: true,
        mtime: 0,
      }));
  }
  if (currentModel && !modelItems.find((i) => i.value === currentModel)) {
    modelItems.unshift({ value: currentModel, kind: "model", label: currentModel, missing: true });
  }
  // Attach cached bench scores and trigger background fetch for the rest
  modelItems.forEach(item => {
    if (item.kind !== "model" || !item.value) return;
    const key = _modelBenchKey(item.value);
    if (!key) return;
    const cached = serverBenchCache.get(key);
    if (cached?.scores?.aa_intelligence != null) item.aaScore = cached.scores.aa_intelligence;
  });
  fetchPickerBenchBatch(modelItems, pfx);
  // Which rows this runner cannot launch. Resolved HERE, where pfx exists, and
  // carried on the item — the row renderer is shared and form-agnostic.
  //
  // The same acceptance table the runner TABS use, so the two halves of the
  // dialog cannot disagree: it dimmed only gguf rows before, which left a
  // whisper runner offering moonshine languages and vice versa.
  {
    const rid = (($(pfx + "RUNNER")?.value || "").trim())
      || (($(pfx + "CELL_KIND")?.value || "") === "command" ? "custom" : "llama-server");
    const accepts = (runnerRegistry().find((r) => r.id === rid) || {}).artifacts || ["*"];
    if (!accepts.includes("*")) {
      const ROW_KIND = { whisper: "whisper-size", moonshine: "moonshine-lang", st: "safetensors" };
      modelItems.forEach((it) => {
        if (it.missing) return;
        // A SeamlessM4T folder is its own kind, so a generic ST runner does not
        // claim it and it does not claim every other ST folder in return.
        const kind = it.kind === "model"
          ? (it.sttVariant ? "asr-gguf" : "llm-gguf")
          : (it.kind === "st" && String(it.stArch || "").startsWith("seamless_m4t")
             ? "seamless-st" : ROW_KIND[it.kind]);
        if (kind) it.wrongRunner = !accepts.includes(kind);
      });
    }
  }
  // Keep hidden <select> in sync for .value reads and option checks elsewhere
  modelEl.innerHTML = "";
  modelItems.forEach((item) => modelEl.appendChild(option(item.value, item.value, item.value === currentModel)));
  updateModelComboboxItems(modelEl, modelItems, currentModel);

  // Same-folder filter: companion files must live in the exact same directory as the model
  const _modelParts = currentModel.split("/");
  const repoPrefix = _modelParts.length >= 2 ? _modelParts.slice(0, -1).join("/") + "/" : "";

  // Auto-correct stale companions that don't belong to the selected model's folder
  if (repoPrefix) {
    const _selectedRow = (state.models || []).find(m => m.path === currentModel);
    if (currentMmproj && !currentMmproj.startsWith(repoPrefix)) {
      currentMmproj = _selectedRow?.suggestedMmproj || "";
      if (mmprojEl) mmprojEl.value = currentMmproj;
    }
    if (currentDraft && !currentDraft.startsWith(repoPrefix)) {
      currentDraft = _selectedRow?.suggestedDraft || "";
      if (draftEl) draftEl.value = currentDraft;
    }
  }

  // Mmproj items
  const mmprojItems = [
    { value: "", label: t("textOnlyOption"), kind: "mmproj" },
    ...models
      .filter((row) => row.kind === "mmproj" && (!repoPrefix || row.path.startsWith(repoPrefix)))
      .map((row) => ({ value: row.path, sizeGb: row.sizeGb, kind: "mmproj" })),
  ];
  if (currentMmproj && !mmprojItems.find((i) => i.value === currentMmproj)) {
    mmprojItems.push({ value: currentMmproj, kind: "mmproj", label: `${currentMmproj} (${t("currentNotFiltered")})` });
  }
  mmprojEl.innerHTML = "";
  mmprojItems.forEach((item) =>
    mmprojEl.appendChild(option(item.value, item.label || item.value || t("textOnlyOption"), item.value === currentMmproj))
  );
  updateModelComboboxItems(mmprojEl, mmprojItems, currentMmproj);

  // Spec draft items
  if (draftEl) {
    const draftItems = [
      { value: "", label: t("textOnlyOption"), kind: "draft" },
      ...models
        .filter((row) => row.kind === "draft" && (!repoPrefix || row.path.startsWith(repoPrefix)))
        .map((row) => ({ value: row.path, sizeGb: row.sizeGb, kind: "draft" })),
    ];
    if (currentDraft && !draftItems.find((i) => i.value === currentDraft)) {
      draftItems.push({ value: currentDraft, kind: "draft", label: `${currentDraft} (${t("currentNotFiltered")})` });
    }
    draftEl.innerHTML = "";
    draftItems.forEach((item) =>
      draftEl.appendChild(option(item.value, item.label || item.value || "—", item.value === currentDraft))
    );
    updateModelComboboxItems(draftEl, draftItems, currentDraft);
  }

  renderChatTemplateOptions(pfx);
  renderChatTemplateHint(pfx);
  syncCompanionMuting(pfx);

  renderModelInsight(pfx);
}

export function renderChatTemplateOptions(pfx = "") {
  const datalist = $(pfx + "chatTemplateFileOptions");
  if (!datalist) return;
  const current = $(pfx + "CHAT_TEMPLATE_FILE")?.value || state.config.CHAT_TEMPLATE_FILE || "";
  const suggested = openClawQwenTemplatePath();
  const paths = [suggested, ...(state.chatTemplates || []).map((row) => row.path)].filter(Boolean);
  const unique = [...new Set(paths)];
  datalist.innerHTML = unique.map((path) => `<option value="${escapeHtml(path)}">${escapeHtml(path === current ? `${path} (${t("currentNotFiltered")})` : path)}</option>`).join("");
}


export function renderChatTemplateHint(pfx = "") {
  const box = $(pfx + "chatTemplateHint");
  if (!box) return;
  const { selected } = selectedModelRows(pfx);
  if (!selected || !isQwenModelPath(selected.path)) {
    box.innerHTML = "";
    return;
  }
  const suggested = openClawQwenTemplatePath();
  const missing = openClawQwenTemplateExists() ? "" : `<span class="insight-warn">${t("templateMissing")}</span>`;
  box.innerHTML = `
    <span>${t("templateSuggestion")}:</span>
    <button class="link-button" type="button">${escapeHtml(suggested)}</button>
    ${missing}
  `;
  box.querySelector("button.link-button")?.addEventListener("click", () => {
    $(pfx + "CHAT_TEMPLATE_FILE").value = suggested;
    renderChatTemplateOptions(pfx);
    renderChatTemplateHint(pfx);
    renderCommandPreview(pfx);
  });
}

// allowEmpty: draw the pool bar even with nothing to estimate (a custom command
// is an opaque process — its host still has a use/free picture worth seeing).
export function renderAsideVramBar(pfx, runtimeSizeGb, allowEmpty = false) {
  const el = $(pfx + "asideVramBar");
  if (!el) return;
  if (!runtimeSizeGb && !allowEmpty) {
    el.innerHTML = `<span class="aside-vram-empty">${escapeHtml(t("selectModelEstimate"))}</span>`;
    return;
  }
  // BOTH pools are drawn. The cell's runtime lands on exactly one of them —
  // whichever the unified compute target points at (llama's N_GPU_LAYERS is not
  // consulted: moonshine is CPU-only, so its weight belongs on RAM) — and the
  // other pool is still shown, with its current use but no cell segment, so the
  // whole memory picture of the host is visible while planning.
  const onCpu = currentComputeMode(pfx) === "cpu";
  const clientRam = (pfx === "tr-" && _trClientCpu && _trClientCpu.ram) || {};
  const ramTotal = pfx === "tr-" ? Number(clientRam.totalGb || 0)
    : Number(state.memory?.totalMiB || 0) / 1024;
  const ramFree = pfx === "tr-" ? Math.max(0, ramTotal - Number(clientRam.usedGb || 0))
    : Number(state.memory?.availableMiB || 0) / 1024;
  const allGpus = computeTargetGpus(pfx);
  const selIdx = computeSelectedGpuIdx(pfx);
  const gs = (selIdx && selIdx.length) ? allGpus.filter((g) => selIdx.includes(Number(g.index))) : allGpus;
  const vramTotal = gs.reduce((sum, g) => sum + Number(g.memoryTotalMiB || 0) / 1024, 0);
  const vramFree = gs.reduce((sum, g) => sum + gpuFreeMiB(g) / 1024, 0);

  // Stacked segments over TOTAL: [already in use] + [this cell] + [free].
  // Two different questions, depending on whether the cell already runs:
  //   parked  → "starting this WILL COST x" — a planned segment appended past
  //             the pool's current use, with the won't-fit check.
  //   running → "this cell IS COSTING x" — its share is ALREADY inside the used
  //             figure, so it gets carved out of that block and highlighted
  //             rather than added; appending it would count the cell twice.
  const pool = (icon, label, totalGb, freeGb, addGb, ownGb, note = "") => {
    if (!totalGb) return "";
    const usedGb = Math.max(0, totalGb - freeGb);
    const mine = Math.min(ownGb, usedGb);            // never wider than the used block
    const othersPct = Math.min(100, ((usedGb - mine) / totalGb) * 100);
    const minePct = Math.min(100 - othersPct, (mine / totalGb) * 100);
    const overflow = addGb > freeGb + 1;
    const addPct = Math.min(100 - othersPct - minePct, (addGb / totalGb) * 100);
    const kind = overflow ? "bad" : (freeGb - addGb < 1 ? "warn" : "good");
    const head = mine
      ? `<span class="aside-pool-mine">this cell <strong>${formatSizeGb(mine)}</strong></span>`
      : (addGb ? `<span>≈ <strong>${formatSizeGb(addGb)}</strong>${overflow ? `<span class="aside-vram-overflow"> ✗ won't fit</span>` : ""}</span>` : "");
    return `
      <div class="aside-pool">
        <div class="aside-pool-head">
          <span class="aside-pool-name">${icon} ${label}${note ? ` <span class="aside-pool-note">· ${escapeHtml(note)}</span>` : ""}</span>
          ${head}
        </div>
        <div class="aside-vram-track" title="${formatSizeGb(usedGb)} in use${mine ? ` (${formatSizeGb(mine)} of it this cell)` : ""}${addGb ? ` · ${formatSizeGb(addGb)} this cell would add` : ""} · ${formatSizeGb(totalGb)} total ${label}">
          <div class="aside-vram-fill used" style="width:${othersPct.toFixed(1)}%"></div>
          ${mine ? `<div class="aside-vram-fill mine" style="width:${minePct.toFixed(1)}%"></div>` : ""}
          ${addGb ? `<div class="aside-vram-fill ${kind}" style="width:${addPct.toFixed(1)}%"></div>` : ""}
        </div>
        <div class="aside-vram-label">
          <span>${usedGb > 0.05 ? `${formatSizeGb(usedGb)} used · ` : ""}${formatSizeGb(freeGb)} free / ${formatSizeGb(totalGb)}</span>
        </div>
      </div>`;
  };
  // Name the card on the VRAM row — the standalone GPU panel is gone, and this
  // is the only place left that says WHICH card the free/total belongs to.
  const cardNote = gs.length === 1 ? shortGpuName(gs[0].name) : (gs.length > 1 ? `${gs.length} GPUs` : "");
  // A live cell reports what it ACTUALLY holds: gpuMem is per-process GPU memory
  // (nvidia-smi compute-apps, summed over the cell's PIDs, so a forked vLLM
  // worker counts too). RAM has no equally honest source — llama.cpp mmaps its
  // weights, so RSS tracks page cache more than the cell's own cost — hence RAM
  // keeps the estimate, only moved inside the used block once the cell is live.
  const slot = _commandCellSlot(pfx);
  const live = !!slot && ["running", "warming"].includes(String(slot.phase || ""));
  const ownVram = live ? Object.values(slot.gpuMem || {}).reduce((a, v) => a + Number(v || 0), 0) / 1024 : 0;
  el.innerHTML = pool("🧠", "RAM", ramTotal, ramFree, (onCpu && !live) ? runtimeSizeGb : 0, (onCpu && live) ? runtimeSizeGb : 0)
    + pool("🎮", "VRAM", vramTotal, vramFree, (!onCpu && !live) ? runtimeSizeGb : 0, ownVram, cardNote);
}

// Returns family default fields that differ from current form / saved config values.
// SPEC_* fields are only included when the model has a draft or built-in MTP.
export function getFamilyRecommendations(selected, pfx) {
  const defaults = selected?.familyDefaults || {};
  if (!Object.keys(defaults).length) return {};
  const hasMtp = !!(selected.suggestedDraft || selected.hasMtpBuiltin);
  const specFields = new Set(["SPEC_TYPE", "SPEC_DRAFT_N_MAX", "SPEC_DRAFT_N_MIN", "SPEC_DRAFT_N_GPU_LAYERS"]);
  const result = {};
  for (const [key, recommended] of Object.entries(defaults)) {
    // Hide SPEC_* recommendations for non-MTP models — but only when ENABLING them.
    // A "clear" rec (e.g. embed wants SPEC_TYPE off) must still show so leaked spec
    // flags can be removed.
    if (specFields.has(key) && !hasMtp && String(recommended).trim() !== "") continue;
    const el = $(pfx + key);
    const current = el
      ? (el.type === "checkbox" ? (el.checked ? "1" : "0") : el.value)
      : (state.config[key] ?? "");
    if (String(current).trim() !== String(recommended).trim()) {
      result[key] = recommended;
    }
  }
  return result;
}

// Render one family-recommendation chip. A toggle recommended "1"/"true" reads
// "on", "0"/"false" reads "off"; a value field recommended "" reads "remove".
// off/remove get a distinct style so the panel can recommend DISABLING or
// dropping flags (e.g. chat-only cruft on an embed server), not only setting them.
export function familyRecChipHtml(key, val) {
  let label, kind;
  if (toggleFields.includes(key)) {
    const on = val === "1" || val === "true";
    label = on ? t("recOn") : t("recOff");
    kind = on ? "set" : "off";
  } else if (String(val).trim() === "") {
    label = t("recRemove");
    kind = "off";
  } else {
    label = val;
    kind = "set";
  }
  return `<span class="insight-family-item ${kind}"><span class="insight-family-key">${escapeHtml(key)}</span><span class="insight-family-val">${escapeHtml(label)}</span></span>`;
}

export function renderModelInsight(pfx = "") {
  const box = $(pfx + "modelInsight");
  if (!box) return;
  const selectedMmproj = $(pfx + "MMPROJ_FILE")?.value;
  const { selected, selectedMmprojRow } = selectedModelRows(pfx);
  if (!selected) {
    box.innerHTML = "";
    return;
  }

  const hasDraft = !!(selected.suggestedDraft || selected.hasMtpBuiltin);
  const badges = [];
  if (selected.capability === "vision_likely" || selected.suggestedMmproj) badges.push(mbadge("mmproj", "📷 mmproj"));
  if (selected.suggestedDraft || selected.hasMtpBuiltin) badges.push(mbadge("mtp", "⚡ mtp"));
  if (selected.capability === "embedding_likely") badges.push(mbadge("embed", "🧬 embed"));

  const { modelSize, mmprojSize, fileTotalSize, kvSize, batchSize, runtimeSize } = estimateRuntimeMemoryGb(pfx);
  const cpuMode = computeIsCpu(pfx);
  const fit = cpuMode
    ? ramFitForPfx(runtimeSize, pfx)
    : (pfx ? vramFitForPfx(runtimeSize, pfx) : vramFit(runtimeSize));
  const ram = ramFit(runtimeSize);
  const sizeChips = `
    <div class="size-grid">
      <div class="size-chip"><span>${t("modelSize")}</span><strong>${formatSizeGb(modelSize)}</strong></div>
      <div class="size-chip"><span>${t("mmprojSize")}</span><strong>${selectedMmprojRow ? formatSizeGb(mmprojSize) : "none"}</strong></div>
      <div class="size-chip"><span>${t("fileTotalSize")}</span><strong>${formatSizeGb(fileTotalSize)}</strong></div>
      <div class="size-chip estimate"><span>${t("kvCacheSize")}</span><strong>${kvSize ? formatSizeGb(kvSize) : "n/a"}</strong></div>
      <div class="size-chip estimate"><span>${t("batchBufferSize")}</span><strong>${batchSize ? formatSizeGb(batchSize) : "n/a"}</strong></div>
      <div class="size-chip estimate runtime-total ${fit.kind}"><span>${t("runtimeSize")}</span><strong>${kvSize ? formatSizeGb(runtimeSize) : "n/a"}</strong></div>
      <div class="size-chip estimate ${fit.kind}"><span>${cpuMode ? t("ramFit") : t("vramFit")}</span><strong>${fit.html}</strong></div>
      <div class="size-chip estimate ram-fit ${ram.kind}"><span>${t("ramFit")}</span><strong>${ram.html}</strong></div>
    </div>
  `;

  const warning = selected.capability === "vision_likely" && !selectedMmproj
    ? `<div class="insight-warn">${t("chooseProjectorHint")}</div>`
    : "";

  const mtpBuiltinLine = (selected.hasMtpBuiltin && !selected.suggestedDraft)
    ? `<div class="insight-mtp-builtin">${t("mtpBuiltinBadge")} — ${t("mtpBuiltinExplain")}</div>`
    : "";

  const familyRecs = getFamilyRecommendations(selected, pfx);
  const familyRecKeys = Object.keys(familyRecs);
  const familyBox = familyRecKeys.length
    ? `<div class="insight-family-recs">
        <span class="insight-family-label">${t("familyRecommends")} <strong>${selected.detectedFamily}</strong>:</span>
        ${familyRecKeys.map((k) => familyRecChipHtml(k, familyRecs[k])).join("")}
        <button class="link-button apply-family-defaults" type="button">${t("applyFamilyDefaults")}</button>
       </div>`
    : "";

  if (pfx) {
    // Compact layout for edit modals (te-, tr-)
    const fmt = (v) => v ? formatSizeGb(v) : "n/a";
    const vramPill = fit.kind ? `<span class="size-chip-inline ${fit.kind}">${fit.html}</span>` : "";
    const ramPill = (pfx !== "tr-" && ram.kind)
      ? `<span class="size-chip-inline ${ram.kind}" style="border-style:dashed">${ram.html}</span>`
      : "";
    const warnLine = warning ? `<div class="insight-warn" style="font-size:11px">${t("chooseProjectorHint")}</div>` : "";
    const mtpBuiltinCompact = (selected.hasMtpBuiltin && !selected.suggestedDraft)
      ? `<div style="font-size:11px;color:var(--muted)">${t("mtpBuiltinBadge")} — ${t("mtpBuiltinExplain")}</div>`
      : "";
    const familyBoxCompact = familyRecKeys.length
      ? `<div class="insight-family-recs" style="font-size:11px">
          <span class="insight-family-label">${t("familyRecommends")} <strong>${selected.detectedFamily}</strong>:</span>
          ${familyRecKeys.map((k) => familyRecChipHtml(k, familyRecs[k])).join("")}
          <button class="link-button apply-family-defaults" type="button" style="font-size:11px">${t("applyFamilyDefaults")}</button>
         </div>`
      : "";

    box.innerHTML = `
      <div style="display:flex;align-items:center;flex-wrap:wrap;gap:6px">
        ${badges.join("")}
      </div>
      <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px 10px;font-size:12px;color:var(--muted)">
        <span>${t("modelSize")} <strong style="color:var(--text)">${fmt(modelSize)}</strong></span>
        ${selectedMmprojRow ? `<span style="color:var(--line)">+</span>
        <span>${t("mmprojSize")} <strong style="color:var(--text)">${fmt(mmprojSize)}</strong></span>
        <span style="color:var(--line)">=</span>
        <span>${t("fileTotalSize")} <strong style="color:var(--text)">${fmt(fileTotalSize)}</strong></span>` : ""}
        <span style="color:var(--line)">|</span>
        <span>KV≈<strong style="color:var(--text)">${fmt(kvSize)}</strong></span>
        <span>Batch≈<strong style="color:var(--text)">${fmt(batchSize)}</strong></span>
        <span style="color:var(--line)">|</span>
        <span>${t("runtimeSize")} <strong style="color:var(--text);font-size:13px">${fmt(runtimeSize)}</strong></span>
        ${vramPill}
        ${ramPill}
      </div>
      ${mtpBuiltinCompact}
      ${warnLine}
      ${familyBoxCompact}
    `;
    renderAsideVramBar(pfx, runtimeSize);
  } else {
    // Full tile layout
    box.innerHTML = `
      <div class="badge-row">${badges.join("")}</div>
      ${sizeChips}
      ${mtpBuiltinLine}
      ${warning}
      ${familyBox}
    `;
  }

  box.querySelector(".apply-family-defaults")?.addEventListener("click", () => {
    const recs = getFamilyRecommendations(selected, pfx);
    for (const [key, val] of Object.entries(recs)) {
      const el = $(pfx + key);
      if (!el) continue;
      if (el.type === "checkbox") {
        // Toggle fields use checked, not value
        el.checked = val === "1" || val === "true";
        syncToggleLabel(el);
      } else {
        el.value = val;
      }
    }
    // Fill draft path: replace if empty or if it was auto-set for a different model
    const specDraftEl = $(pfx + "SPEC_DRAFT_MODEL_FILE");
    if (specDraftEl && selected.suggestedDraft) {
      const curDraft = specDraftEl.value || "";
      const curDraftRow = modelsByPath().get(curDraft);
      const looksLikeDraft = curDraft.toLowerCase().includes("/mtp/") ||
                             curDraft.toLowerCase().includes("-mtp") ||
                             curDraft.toLowerCase().includes("draft");
      if (!curDraft || curDraft !== selected.suggestedDraft &&
          (curDraftRow?.kind === "draft" || looksLikeDraft)) {
        specDraftEl.value = selected.suggestedDraft;
      }
    }
    syncFavoriteMirrors(pfx);
    renderModelInsight(pfx);
    renderCommandPreview(pfx);
  });
}

export function syncPortChipsEl(chips, value) {
  chips.forEach((chip) => chip.classList.toggle("active", chip.dataset.port === String(value)));
}

export function renderField(field, pfx = "") {
  const div = document.createElement("div");
  div.className = "field";
  // Every field is addressable by name. The config search and the
  // hover-a-flag-find-its-input link both resolve through this one attribute,
  // so a field added later is covered by having been rendered at all — there is
  // no second registry that could quietly omit it.
  div.dataset.field = field;
  const help = fieldHelp(field);
  const fid = pfx + field;
  const labelRow = pfx
    ? `<div class="label-row"><label for="${fid}">${field}</label><button class="tip-trigger" type="button" data-fieldhelp="${field}" aria-label="${field}: ${escapeHtml(help)}">?<span class="tooltip" role="tooltip">${escapeHtml(help)}</span></button></div>`
    : labelWithTip(field);

  if (field === "PORT") {
    const currentPort = String(state.config.PORT || "8080");
    if (!pfx) {
      // Main config form: full port picker with chips
      const portOptions = Array.from({ length: 10 }, (_, i) => 8080 + i);
      const chipsHtml = portOptions.map((p) =>
        `<button class="port-chip${String(p) === currentPort ? " active" : ""}" type="button" data-port="${p}">${p}</button>`
      ).join("");
      div.innerHTML = `
        ${labelRow}
        <div class="port-combo">
          <input id="${fid}" name="${field}" type="number" min="1024" max="65535"
            value="${escapeHtml(currentPort)}" autocomplete="off">
          <button class="port-dropdown-btn" type="button" tabindex="-1" aria-haspopup="true" title="${escapeHtml(t("pickPort"))}">▾</button>
          <div class="port-dropdown" hidden>${chipsHtml}</div>
        </div>
        <p>${escapeHtml(help)}</p>
      `;
      const input = div.querySelector("input");
      const dropdown = div.querySelector(".port-dropdown");
      const toggleBtn = div.querySelector(".port-dropdown-btn");
      const chips = div.querySelectorAll(".port-chip");
      toggleBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        dropdown.hidden = !dropdown.hidden;
      });
      chips.forEach((chip) => chip.addEventListener("click", () => {
        input.value = chip.dataset.port;
        dropdown.hidden = true;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }));
      input.addEventListener("input", () => syncPortChipsEl(chips, input.value));
    } else {
      // Topology modal forms (te-, tr-): plain readonly input, no dropdown
      div.innerHTML = `
        ${labelRow}
        <input id="${fid}" name="${field}" type="number" min="1024" max="65535"
          value="${escapeHtml(currentPort)}" autocomplete="off">
        <p>${escapeHtml(help)}</p>
      `;
    }
    return div;
  }

  if (toggleFields.includes(field)) {
    const checked = toggleChecked(field);
    div.innerHTML = `
      ${labelRow}
      <label class="check-row" for="${fid}">
        <input id="${fid}" name="${field}" type="checkbox" ${checked ? "checked" : ""}>
        <span>${checked ? t("enabled") : t("disabled")}</span>
      </label>
      <p>${help}</p>
    `;
    const input = div.querySelector("input");
    syncToggleLabel(input);
    input.addEventListener("change", () => {
      if (optionalToggleFields.includes(field)) dirtyOptionalToggles.add(field);
      syncToggleLabel(input);
      renderModelInsight(pfx);
    });
  } else if (field === "BATCH_SIZE" || field === "UBATCH_SIZE") {
    div.innerHTML = `
      ${labelRow}
      <div class="batch-combo">
        <input id="${fid}" name="${field}" type="number" min="1" value="${escapeHtml(state.config[field] || "")}">
        <button class="batch-scale-btn" type="button" data-scale="0.5">÷2</button>
        <button class="batch-scale-btn" type="button" data-scale="2">×2</button>
      </div>
      <p>${help}</p>
    `;
    const input = div.querySelector("input");
    input.addEventListener("input", () => renderModelInsight(pfx));
    div.querySelectorAll(".batch-scale-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const v = Math.max(1, Math.round(Number(input.value || 0) * Number(btn.dataset.scale)));
        input.value = v;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    });
  } else if (field === "CTX_SIZE") {
    // Wider than a normal field, with a live YaRN chip beside the input: the
    // fine-print hint alone was invisible in this dense grid — the operator
    // typed 300000 and saw nothing change. The chip is also a real toggle
    // between the two modes: AUTO (the builder derives the recipe) and MANUAL
    // (explicit ROPE_* fields, which always win over the automation).
    div.classList.add("ctx-size-field");
    div.innerHTML = `
      ${labelRow}
      <div class="ctx-size-row">
        <div class="batch-combo">
          <input id="${fid}" name="${field}" value="${escapeHtml(state.config[field] || "")}">
          <button class="batch-scale-btn" type="button" data-scale="0.5">÷2</button>
          <button class="batch-scale-btn" type="button" data-scale="2">×2</button>
        </div>
        <button type="button" class="yarn-chip" id="${fid}-yarn-chip" data-t="cell-yarn-chip" hidden></button>
      </div>
      <p class="ctx-yarn-hint" data-t="cell-ctx-yarn-hint" hidden></p>
      <p>${help}</p>
    `;
    const input = div.querySelector("input");
    input.addEventListener("input", () => { updateCtxYarnHint(pfx); renderModelInsight(pfx); });
    div.querySelector(".yarn-chip").addEventListener("click", () => toggleYarnMode(pfx));
    // Same halve/double affordance the batch fields carry — context is the
    // other number an operator walks up and down by powers of two, and it is
    // the one where the next step may cross the model's native window and
    // engage YaRN, so the chip has to re-read after every press.
    div.querySelectorAll(".batch-scale-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const v = Math.max(1, Math.round(Number(input.value || 0) * Number(btn.dataset.scale)));
        input.value = v;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    });
  } else {
    // Fields with a closed value set get a datalist: every legal value becomes
    // discoverable without taking away free text, so a value llama.cpp adds
    // tomorrow is still typeable today.
    const choices = fieldChoices[field];
    const listId = choices ? `${fid}-choices` : "";
    div.innerHTML = `
      ${labelRow}
      <input id="${fid}" name="${field}" value="${escapeHtml(state.config[field] || "")}"${
        listId ? ` list="${escapeHtml(listId)}"` : ""}>
      ${choices ? `<datalist id="${escapeHtml(listId)}">${
        choices.map((v) => `<option value="${escapeHtml(v)}"></option>`).join("")}</datalist>` : ""}
      <p>${help}</p>
    `;
    div.querySelector("input")?.addEventListener("input", () => {
      if (field === "ROPE_SCALING" || field === "ROPE_SCALE") updateCtxYarnHint(pfx);
      renderModelInsight(pfx);
    });
  }
  attachFavStar(div, field, pfx);
  return div;
}

export function maybeAutofillChatTemplate() {
  const selected = modelsByPath().get($("MODEL_FILE").value);
  const current = $("CHAT_TEMPLATE_FILE").value.trim();
  if (!selected || !isQwenModelPath(selected.path) || current || !openClawQwenTemplateExists()) return;
  $("CHAT_TEMPLATE_FILE").value = openClawQwenTemplatePath();
  toast(t("templateAutoFilled"));
}

export function maybeAutofillModelHelpers() {
  maybeAutofillModelHelpersPfx("", { aliasFollow: true });
  renderRuntime();
  maybeAutofillChatTemplate();
}

/**
 * Prefixed version — works for any form prefix (e.g. "tr-" for remote modal).
 * Always rewrites all companion fields to match the selected model.
 * Called on MODEL_FILE change and on form open.
 */
export function maybeAutofillModelHelpersPfx(pfx, opts = {}) {
  const modelVal = $(pfx + "MODEL_FILE")?.value || "";
  const selected = modelsByPath().get(modelVal);

  // ALIAS — derive from the model file name. On an explicit model change
  // (opts.aliasFollow, set by the change listeners) the alias ALWAYS follows
  // the newly picked model, even over a custom value. On form open / backup
  // load (no aliasFollow) only an empty field or our own previous auto-fill
  // (tracked in data-auto-alias) is rewritten, so saved aliases survive.
  const aliasEl = $(pfx + "ALIAS");
  if (aliasEl && modelVal) {
    const cur = aliasEl.value.trim();
    if (opts.aliasFollow || !cur || cur === aliasEl.dataset.autoAlias) {
      // Safetensors artifact paths end in a FORMAT folder — the alias should be
      // the model folder (first segment), not "nvfp4".
      const stRow = (state.artifacts || []).find((a) => a.path === modelVal);
      const derived = stRow
        ? stRow.name.toLowerCase()
        : modelVal.split("/").pop()
            .replace(/\.gguf$/i, "").replace(/-\d{5}-of-\d{5}$/i, "").toLowerCase();
      aliasEl.value = derived;
      aliasEl.dataset.autoAlias = derived;
    }
  }

  // CTX_SIZE placeholder — the model's own native window, read from the GGUF
  // header. Not a value: the field stays whatever the operator set, but an
  // emptied field now says what the model itself was trained to (and going
  // past it is a conscious YaRN decision, not a guess).
  const ctxEl = $(pfx + "CTX_SIZE");
  if (ctxEl) {
    const nativeCtx = Number(selected?.ggufMeta?.contextLength || 0);
    ctxEl.placeholder = nativeCtx > 0 ? String(nativeCtx) : "";
    updateCtxYarnHint(pfx);
  }

  // MMPROJ — always overwrite (clear if none found).
  const mmprojEl = $(pfx + "MMPROJ_FILE");
  if (mmprojEl) {
    const wanted = selected?.suggestedMmproj || "";
    if (mmprojEl.value !== wanted) { mmprojEl.value = wanted; mcUpdateTrigger(mmprojEl); }
  }

  // OFFLOAD_MMPROJ — enable when a projector is available, disable otherwise.
  const offloadEl = $(pfx + "OFFLOAD_MMPROJ");
  if (offloadEl) {
    const wantOffload = !!(selected?.suggestedMmproj);
    if (offloadEl.type === "checkbox") {
      if (offloadEl.checked !== wantOffload) { offloadEl.checked = wantOffload; syncToggleLabel(offloadEl); }
    } else {
      offloadEl.value = wantOffload ? "1" : "0";
    }
  }

  // SPEC_DRAFT_MODEL_FILE + SPEC_TYPE — always overwrite together.
  const draftEl = $(pfx + "SPEC_DRAFT_MODEL_FILE");
  const specTypeEl = $(pfx + "SPEC_TYPE");
  if (draftEl) {
    const wantedDraft = selected?.suggestedDraft || "";
    const draftChanged = draftEl.value !== wantedDraft;
    if (draftChanged) { draftEl.value = wantedDraft; mcUpdateTrigger(draftEl); }
    if (specTypeEl) {
      const hasMtp = !!(wantedDraft || selected?.hasMtpBuiltin);
      // The type must come from the SIDECAR, not from the family default: a
      // DFlash sidecar launched as draft-mtp starts happily and drafts nothing,
      // which is how a cell ends up at a third of its throughput while the panel
      // looks correct. Family defaults only get to speak for a built-in MTP head.
      const wantedSpec = !hasMtp ? ""
        : wantedDraft ? inferSpecType(wantedDraft)
        : (selected?.familyDefaults?.SPEC_TYPE || "draft-mtp");
      if (specTypeEl.value !== wantedSpec) specTypeEl.value = wantedSpec;
      const specEnabledEl = $(pfx + "SPEC_ENABLED");
      if (specEnabledEl) { specEnabledEl.checked = !!hasMtp; syncToggleLabel(specEnabledEl); }

      // Draft depth follows the sidecar's own block size — a block-diffusion
      // drafter proposes a whole block per pass, so the default 3 wastes most of
      // it (measured: 157 tok/s at 3 against 227 at this file's 16).
      //
      // The depth belongs to the SIDECAR, not to the operator, so it is rewritten
      // whenever a different sidecar is attached — same rule MMPROJ already
      // follows. Without that, a stale value inherited from whichever model the
      // form last held wins and silently caps the new drafter. A deliberate value
      // still survives everything except swapping the drafter underneath it.
      const nMaxEl = $(pfx + "SPEC_DRAFT_N_MAX");
      const blockSize = Number(modelsByPath().get(wantedDraft)?.ggufMeta?.specBlockSize || 0);
      if (nMaxEl && wantedDraft) {
        // Upstream's own ceiling: n_draft_max = block_size for dspark, one less
        // for dflash (the block's first slot holds the last real token, not a
        // draft). Asking for the full block starts fine but logs "exceeds the
        // trained block size -- clamping", which reads like a misconfiguration.
        const usable = wantedSpec === "draft-dspark" ? blockSize : blockSize - 1;
        const derived = usable > 1
          ? String(usable)
          : String(selected?.familyDefaults?.SPEC_DRAFT_N_MAX || "");
        const cur = nMaxEl.value.trim();
        if (derived && (draftChanged || !cur || cur === nMaxEl.dataset.autoNMax)) {
          nMaxEl.value = derived;
          nMaxEl.dataset.autoNMax = derived;
        }
      }
    }
  }

  // Embedding models default to CPU (light & bursty — keep VRAM for chat);
  // otherwise just sync the compute-target cards to the current fields.
  if (selected?.capability === "embedding_likely" && computeTargetGpus(pfx).length) {
    applyComputeTarget(pfx, { mode: "cpu" });
  } else {
    refreshComputeTarget(pfx);
  }

  renderModelSelects(pfx); // re-filter companion dropdowns for the newly selected model
  renderChatTemplateHint(pfx);
  syncFavoriteMirrors(pfx);
  renderModelInsight(pfx);
  renderCommandPreview(pfx);
  // transcribe is the one command-path runner whose exec line is built FROM
  // MODEL_FILE, so picking a model has to repaint the command preview too —
  // otherwise the box keeps naming the file you just replaced.
  if ((($(pfx + "RUNNER")?.value || "").trim()) === "transcribe") renderCommandCellPreview(pfx);
}

export function setInputValue(id, value) {
  const input = $(id);
  if (!input) return;
  input.value = value;
  // Keep model combobox trigger in sync when value is set programmatically
  if (input.tagName === "SELECT") mcUpdateTrigger(input);
}

export function ensureGemma4MtpFields() {
  setInputValue("SPEC_DRAFT_MODEL_FILE", $("SPEC_DRAFT_MODEL_FILE")?.value || gemma4DraftModel);
  setInputValue("SPEC_TYPE", $("SPEC_TYPE")?.value || "draft-mtp");
  setInputValue("SPEC_DRAFT_N_GPU_LAYERS", $("SPEC_DRAFT_N_GPU_LAYERS")?.value || "999");
  setInputValue("SPEC_DRAFT_N_MAX", $("SPEC_DRAFT_N_MAX")?.value || "16");
  setInputValue("SPEC_DRAFT_N_MIN", $("SPEC_DRAFT_N_MIN")?.value || "0");
  setInputValue("SPEC_DRAFT_CACHE_TYPE_K", $("SPEC_DRAFT_CACHE_TYPE_K")?.value || "q8_0");
  setInputValue("SPEC_DRAFT_CACHE_TYPE_V", $("SPEC_DRAFT_CACHE_TYPE_V")?.value || "q8_0");
}

export async function setGemma4Mode(mode) {
  if (!isGemma4ModelPath($("MODEL_FILE")?.value || state.config.MODEL_FILE)) {
    toast(t("gemmaModeNeedsGemma"));
    return;
  }
  ensureGemma4MtpFields();
  if (mode === "vision") {
    const projector = selectedGemma4Mmproj();
    if (!projector) {
      toast(t("gemmaVisionNeedsProjector"));
      return;
    }
    setInputValue("MMPROJ_FILE", projector);
  } else {
    setInputValue("MMPROJ_FILE", "");
  }
  renderModelInsight();
  renderRuntime();
  renderCommandPreview();
  await saveConfig(true);
  toast(mode === "vision" ? t("gemmaVisionApplied") : t("gemmaTextBoostApplied"));
}

// Auto-parse EXTRA_ARGS: pull any flag that has a dedicated form field out of the
// raw box and into its field, leaving only truly-extra flags. The flag→field map
// lives on the controller (single source of truth, inverse of build_llama_args).
export async function hoistExtraArgs(pfx = "") {
  const el = $(pfx + "EXTRA_ARGS");
  if (!el) return;
  const text = (el.value || "").trim();
  if (!text) return;
  let res;
  try {
    res = await api("/api/parse-extra-args", { method: "POST", body: JSON.stringify({ extraArgs: text }) });
  } catch { return; }
  const rec = res.recognized || {};
  const applied = [];
  for (const [field, value] of Object.entries(rec)) {
    const f = $(pfx + field);
    if (!f || f.readOnly || f.disabled) continue;  // can't touch locked fields (e.g. a cell's PORT)
    if (f.type === "checkbox") {
      f.checked = (String(value) === "1");
      if (optionalToggleFields.includes(field)) dirtyOptionalToggles.add(field);
      syncToggleLabel(f);
    } else {
      f.value = value;
      if (f.tagName === "SELECT") mcUpdateTrigger(f);
    }
    applied.push(field);
  }
  if (!applied.length) return;  // nothing we could hoist → leave EXTRA_ARGS as typed
  el.value = res.remaining || "";
  try { syncCompanionMuting(pfx); } catch {}
  renderModelInsight(pfx);
  refreshComputeTarget(pfx);
  renderCommandPreview(pfx);
  toast(`EXTRA_ARGS → ${applied.join(", ")}`);
}

export function renderFields(pfx = "") {
  const wrap = $(pfx + "dynamicFields");
  if (!wrap) return;
  // Save panels before clearing (they may already live inside dynamicFields from a previous call)
  const ctPanel = document.getElementById((pfx || "") + "chatTemplatePanel");
  wrap.innerHTML = "";

  const tabsEl = document.createElement("div");
  tabsEl.className = "advanced-tabs";

  const bar = document.createElement("div");
  bar.className = "advanced-tab-bar";

  const body = document.createElement("div");
  body.className = "advanced-tab-body";

  // Favorites tab (first): aggregates the fields the user starred elsewhere.
  // Active by default only when non-empty, so an empty Favorites doesn't hijack
  // the form. Uses the panel id "fav" (not a number) so the numeric indices of
  // the other tabs — and the chat-template transplant into panel "3" — are
  // unaffected.
  const favActive = getFavFields().filter((f) => f !== "EXTRA_ARGS").length > 0;
  const favBtn = document.createElement("button");
  favBtn.className = "advanced-tab-btn" + (favActive ? " active" : "");
  favBtn.type = "button";
  favBtn.textContent = t("tabFavorites");
  favBtn.dataset.i18n = "tabFavorites";   // refreshed in place on language switch
  favBtn.dataset.advTab = "fav";
  bar.appendChild(favBtn);

  const favPanel = document.createElement("div");
  favPanel.className = "advanced-tab-panel" + (favActive ? " active" : "");
  favPanel.dataset.advPanel = "fav";
  // Pinned first row: the manual extra-args box lives here (its canonical input,
  // full-width). It is always present and cannot be un-starred.
  const favExtraSection = document.createElement("section");
  favExtraSection.className = "advanced-group extra-args-group";
  favExtraSection.innerHTML = `<h3 data-i18n="advancedExtraArgs">${t("advancedExtraArgs")}</h3><div class="advanced-grid extra-args-grid"></div>`;
  const favExtraField = renderField("EXTRA_ARGS", pfx);
  favExtraField.querySelector(".fav-star")?.remove();
  // Auto-hoist known flags into their fields on blur / paste.
  const extraInput = favExtraField.querySelector("input, textarea");
  if (extraInput) {
    extraInput.addEventListener("blur", () => hoistExtraArgs(pfx));
    extraInput.addEventListener("paste", () => setTimeout(() => hoistExtraArgs(pfx), 0));
  }
  favExtraSection.querySelector(".advanced-grid").appendChild(favExtraField);
  favPanel.appendChild(favExtraSection);
  // Dynamic area for the starred field mirrors.
  const favMirrors = document.createElement("div");
  favMirrors.className = "fav-mirrors";
  favPanel.appendChild(favMirrors);
  body.appendChild(favPanel);

  // Tabs 0-10: every field lives in a group now, and every group in a tab.
  // The old hardcoded "Params" tab (a flat basicFields list) is gone — its
  // fields were dissolved into Basics / Performance / Memory / Tools&Service,
  // so a field has exactly one home and the tab bar reads as a list of
  // questions rather than three catch-alls.
  // EXTRA_ARGS stays pinned at the top of the Favorites tab (built above).
  advancedTabDefs.forEach((tab, i) => {
    const idx = i;
    const btn = document.createElement("button");
    btn.className = "advanced-tab-btn" + (!favActive && idx === 0 ? " active" : "");
    btn.type = "button";
    btn.textContent = t(tab.key);
    btn.dataset.i18n = tab.key;
    btn.dataset.advTab = String(idx);
    // Literal data-t so the contract scanner (scripts/testability_names.py,
    // which greps for data-t="…") sees it — a dataset assignment is invisible
    // to it, and an unseen hook is one the E2E suite cannot rely on.
    btn.setAttribute("data-t", "cell-config-tab");
    btn.setAttribute("data-t-id", tab.key);
    bar.appendChild(btn);

    const panel = document.createElement("div");
    panel.className = "advanced-tab-panel" + (!favActive && idx === 0 ? " active" : "");
    panel.dataset.advPanel = String(idx);

    // A dot on the tab when any of its fields carries a value: with eleven tabs
    // the operator must see WHERE this cell differs from a vanilla one without
    // opening each in turn.
    const tabFields = tab.groups.flatMap((gk) =>
      advancedGroups.find((g) => g.titleKey === gk)?.fields || []);
    if (tabFields.some((f) => String(state.config[f] ?? "").trim() !== "")) {
      btn.classList.add("has-values");
    }

    tab.groups.forEach((groupKey) => {
      const group = advancedGroups.find((g) => g.titleKey === groupKey);
      if (!group) return;
      const section = document.createElement("section");
      section.className = "advanced-group";
      section.innerHTML = `<h3 data-i18n="${group.titleKey}">${t(group.titleKey)}</h3><div class="advanced-grid"></div>`;
      const grid = section.querySelector(".advanced-grid");
      group.fields.forEach((field) => grid.appendChild(renderField(field, pfx)));
      panel.appendChild(section);
    });

    body.appendChild(panel);
  });

  // ── overflow plumbing ────────────────────────────────────────────────────
  // Twelve tabs overflow a narrow modal. The bar scrolls; these keep the edge
  // fades honest about which direction still has tabs, and let a trackpad's
  // vertical gesture drive it (a horizontal-only scroller is otherwise
  // unreachable on a mouse with no tilt wheel).
  const syncTabFades = () => {
    const max = bar.scrollWidth - bar.clientWidth;
    tabsEl.classList.toggle("scroll-left", bar.scrollLeft > 1);
    tabsEl.classList.toggle("scroll-right", bar.scrollLeft < max - 1);
  };
  bar.addEventListener("scroll", syncTabFades, { passive: true });
  bar.addEventListener("wheel", (e) => {
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
    if (bar.scrollWidth <= bar.clientWidth) return;
    e.preventDefault();
    bar.scrollLeft += e.deltaY;
    syncTabFades();
  }, { passive: false });
  // The bar has no width until it is in the DOM and the modal is laid out.
  // Bring the active tab into view at the same moment: an active tab parked
  // past the right edge would look like no tab is active at all.
  requestAnimationFrame(() => {
    syncTabFades();
    bar.querySelector(".advanced-tab-btn.active")
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
  new ResizeObserver(syncTabFades).observe(bar);

  bar.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-adv-tab]");
    if (!btn) return;
    const idx = btn.dataset.advTab;
    // A tab clicked at the clipped edge should finish the journey itself.
    btn.scrollIntoView({ block: "nearest", inline: "nearest" });
    // Called outright rather than waiting on the scroll event: a programmatic
    // scroll does not reliably deliver one here, and a stale fade is a lie
    // about which direction still has tabs.
    syncTabFades();
    bar.querySelectorAll(".advanced-tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.advTab === idx));
    body.querySelectorAll(".advanced-tab-panel").forEach((p) => p.classList.toggle("active", p.dataset.advPanel === idx));
    // Refresh the favorite mirrors from their canonical inputs when shown.
    if (idx === "fav") syncFavoriteMirrors(pfx);
  });

  tabsEl.appendChild(bar);
  tabsEl.appendChild(body);
  // Search above the bar: with eleven tabs, knowing a setting exists is no
  // longer the same as being able to find it. It sits outside .advanced-tabs
  // because the edge fades there are positioned from that box's top — inside,
  // they would drift down onto the search row instead of the tabs.
  wrap.appendChild(renderConfigSearch(pfx));
  wrap.appendChild(tabsEl);
  // Hovering a flag in the command preview lights up its tab and input.
  bindCommandLocator(pfx);

  // Fill the Favorites panel now that the canonical inputs exist in the DOM
  // (the mirrors bind to them by id).
  refreshFavoritesPanel(pfx);

  // Transplant the chat-template panel into the Server tab (last panel) and
  // give its field the same label-row treatment as the rest (? help + ★ star).
  if (ctPanel) {
    const serverPanel = body.querySelector('[data-adv-panel="3"]');
    if (serverPanel) serverPanel.appendChild(ctPanel);
    enhanceChatTemplatePanel(ctPanel, pfx);
  }
  // The chat-template star is built once (panel persists across renders), so
  // re-sync all canonical stars to the current favorite set after each render.
  updateStarStates(pfx);

  if (!pfx) {
    document.querySelector('[data-help="MODEL_FILE"]').innerHTML = `<span data-fieldhelp-text="MODEL_FILE">${fieldHelp("MODEL_FILE")}</span><span class="inline-tip" tabindex="0" data-fieldhelp="MODEL_FILE">?<span class="tooltip" role="tooltip">${fieldHelp("MODEL_FILE")}</span></span>`;
    document.querySelector('[data-help="LLAMA_MODELS_DIR"]').innerHTML = `<span data-fieldhelp-text="LLAMA_MODELS_DIR">${fieldHelp("LLAMA_MODELS_DIR")}</span><span class="inline-tip" tabindex="0" data-fieldhelp="LLAMA_MODELS_DIR">?<span class="tooltip" role="tooltip">${fieldHelp("LLAMA_MODELS_DIR")}</span></span>`;
  }
}

// Give the custom chat-template panel the same label-row as renderField fields:
// a "?" help tip and a ★ favorite star, plus a plain help line below. Works for
// all form prefixes and is idempotent.
export function enhanceChatTemplatePanel(panel, pfx = "") {
  if (!panel || panel.querySelector(".label-row")) return;
  const field = "CHAT_TEMPLATE_FILE";
  const help = fieldHelp(field);
  const input = panel.querySelector("input");
  if (!input) return;
  // Drop any pre-existing bare label (main form had one).
  panel.querySelectorAll("label").forEach((l) => {
    if (l.getAttribute("for") === input.id) l.remove();
  });
  const row = document.createElement("div");
  row.className = "label-row";
  row.innerHTML = `<label for="${input.id}">${field}</label>` +
    `<button class="tip-trigger" type="button" data-fieldhelp="${field}" aria-label="${field}: ${escapeHtml(help)}">?<span class="tooltip" role="tooltip">${escapeHtml(help)}</span></button>`;
  input.parentNode.insertBefore(row, input);
  attachFavStar(panel, field, pfx);
  // Help line below the input, matching other fields.
  let p = panel.querySelector('p[data-help], p.ct-help');
  if (!p) {
    p = document.createElement("p");
    p.className = "ct-help";
    input.insertAdjacentElement("afterend", p);
  }
  p.dataset.fieldhelpText = field;   // refreshed in place on language switch
  p.textContent = help;
}

export function renderStaticConfigFields() {
  const modelsDir = $("LLAMA_MODELS_DIR");
  if (modelsDir && !modelsDir.value) {
    modelsDir.value = effectiveModelsDir(state.config);
  }
  const preview = $("modelsDirPreview");
  if (preview && modelsDir) {
    preview.textContent = modelsDir.value || effectiveModelsDir(state.config);
    preview.title = preview.textContent;
  }
}

export function renderRaw() {
  const summary = {
    paths: state.paths,
    config: state.config,
    runtime: {
      models: state.runtime?.models,
      props: {
        n_ctx: state.runtime?.props?.default_generation_settings?.n_ctx,
        modalities: state.runtime?.props?.modalities,
        model_path: state.runtime?.props?.model_path,
      },
      metrics: state.runtime?.metrics,
    },
    cpu: state.cpu,
    gpu: state.gpu,
    memory: state.memory,
  };
  renderBackups();
}

export function readConfigForm(pfx = "") {
  const config = {};
  modelFields.forEach((field) => {
    config[field] = $(pfx + field)?.value || "";
  });
  config.LLAMA_MODELS_DIR = effectiveModelsDir(config);
  numericFields.forEach((field) => config[field] = $(pfx + field)?.value?.trim() || "");
  toggleFields.forEach((field) => {
    if (optionalToggleFields.includes(field) && !dirtyOptionalToggles.has(field) && !state.config[field]) {
      config[field] = "";
    } else {
      config[field] = $(pfx + field)?.checked ? "1" : "0";
    }
  });
  // Generic command cell (CELL_KIND="command"): raw COMMAND instead of a model.
  config.CELL_KIND = $(pfx + "CELL_KIND")?.value || "";
  config.RUNNER = ($(pfx + "RUNNER")?.value || "").trim()
    || (config.CELL_KIND === "command" ? "custom" : "llama-server");
  config.COMMAND = ($(pfx + "COMMAND")?.value || "").trim();
  config.HEALTH_PATH = ($(pfx + "HEALTH_PATH")?.value || "").trim();
  config.ENV = $(pfx + "ENV")?.value || "";
  config.WORKDIR = ($(pfx + "WORKDIR")?.value || "").trim();
  ["VLLM_MODEL", "MAX_MODEL_LEN", "GPU_MEMORY_UTILIZATION", "QUANTIZATION", "DTYPE", "TENSOR_PARALLEL",
   "WHISPER_MODEL", "MOONSHINE_MODEL", "SEAMLESS_TGT_LANG",
   "TRANSLATE_MODEL", "TRANSLATE_SRC_LANG", "TRANSLATE_TGT_LANG"].forEach((k) => {
    config[k] = ($(pfx + k)?.value || "").trim();
  });
  if (config.CELL_KIND === "command" || config.RUNNER === "vllm" || config.RUNNER === "whisper" || config.RUNNER === "moonshine") {
    // Not a llama-server — don't carry a stale model/mmproj/draft into the slot.
    config.MODEL_FILE = "";
    config.MMPROJ_FILE = "";
    config.SPEC_DRAFT_MODEL_FILE = "";
  }
  return config;
}

