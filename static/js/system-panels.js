// Controller service/CPU/GPU panels, system-info modal, llama.cpp update/revert.
import { appConfirm } from "./dialogs.js";
import { formatCmdline } from "./command-preview.js";
import { helpTip, t } from "./i18n.js";
import { closeConfirmModal } from "./llama-edit.js";
import { estimateRuntimeMemoryGb, formatSizeGb, ramFit, vramFit } from "./memory.js";
import { formatTps, metricNumber, tokenSpeedState } from "./polling.js";
import { setState, state, ui } from "./state.js";
import { parseLlamaBuildVersion } from "./topology-nodes.js";
import { renderAll } from "./topology-render.js";
import { $, api, escapeHtml, formatBytesMiB, formatMemoryMiB, pill, toast } from "./utils.js";

export function renderService() {
  const svc = state.service || {};
  const status = state.runtime?.status || {};
  const phase = status.phase || svc.ActiveState || "unknown";
  const label = t(phase) || status.label || phase;
  $("serviceSummary").innerHTML = `
    <div>${pill(label, status.kind || (svc.ActiveState === "active" ? "good" : "bad"))} ${escapeHtml(svc.SubState || "")}</div>
    <div>${t("pid")}: <b>${svc.MainPID || "0"}</b></div>
    <div>${t("started")}: <b>${svc.ExecMainStartTimestamp || "n/a"}</b></div>
    <div>${t("service")}: <b>${state.paths.service}</b></div>
    ${status.detail ? `<div>${escapeHtml(status.detail)}</div>` : ""}
  `;
  $("cmdline").textContent = svc.cmdline ? formatCmdline(svc.cmdline) : t("noRunningCommand");
}

export function renderSectionTips() {
  const targets = {
    serviceTip: "serviceHelp",
    runtimeTip: "runtimeHelp",
    cpuTip: "cpuHelp",
    gpuTip: "gpuHelp",
    configTip: "configHelp",
    textOnlyTip: "textOnlyHelp",
    revertLatestTip: "revertLatestHelp",
    commandTip: "commandHelp",
    previewCommandTip: "previewCommandHelp",
    backupsTip: "backupsHelp",
    llamaCppTip: "llamaCppHelp",
    checkVersionsTip: "checkVersionsHelp",
    updateBuildTip: "updateBuildHelp",
    knownProblemsTip: "knownProblemsHelp",
    repairUserServiceTip: "repairUserServiceHelp",
    logsTip: "logsHelp",
    rawApiTip: "rawApiHelp",
    systemMonitorTip: "systemMonitorHelp",
    systemHistoryTip: "systemHistoryHelp",
    systemGpuTip: "gpuMonitorHelp",
    systemGpuUsersTip: "gpuUsersHelp",
    systemAgentProxyRoutesTip: "agentProxyRouteHelp",
    systemClientsTip: "clientsHelp",
    systemLlamaActivityTip: "llamaActivityHelp",
    systemTokenTip: "tokenSpeedHelp",
    systemVramTip: "vramMonitorHelp",
    systemCpuTip: "cpuMonitorHelp",
    systemMemoryTip: "memoryMonitorHelp",
    systemNetTip: "networkMonitorHelp",
    systemDiskTip: "diskMonitorHelp",
    systemPowerTip: "powerMonitorHelp",
    systemProcessesTip: "topProcessesHelp",
    nvidiaMonitorTip: "nvidiaMonitorHelp",
    nvidiaIntervalTip: "monitorIntervalHelp",
    topologyServerTip: "topologyServerHelp",

    topologyLlamaServersTip: "topologyLlamaServersHelp",
    topologyGpusTip: "topologyGpusHelp",
    topologyClientsTip: "topologyClientsHelp",
    topologyCloudTip: "topologyCloudHelp",
  };
  Object.entries(targets).forEach(([id, key]) => {
    const el = $(id);
    if (el) el.innerHTML = helpTip(key);
  });
}

export function renderRuntime() {
  const runtime = state.runtime || {};
  const config = state.config || {};
  const props = runtime.props || {};
  const models = runtime.models || {};
  const memory = state.memory || {};
  const ctx = props.default_generation_settings?.n_ctx || "n/a";
  const vision = props.modalities?.vision;
  const modelId = models.data?.[0]?.id || models.models?.[0]?.name || "n/a";
  const metrics = runtime.metrics || {};
  const estimate = estimateRuntimeMemoryGb();
  const vram = vramFit(estimate.runtimeSize);
  const ram = ramFit(estimate.runtimeSize);
  const ramLine = memory.ok
    ? `<div>${t("ram")}: <b>${formatMemoryMiB(memory.usedMiB)}</b> ${t("used")}, <b>${formatMemoryMiB(memory.availableMiB)}</b> ${t("available")}, <b>${formatMemoryMiB(memory.totalMiB)}</b> ${t("total")}</div>`
    : `<div>${memory.error || t("noRamData")}</div>`;
  const specTypeVal = (config.SPEC_TYPE || "").trim().toLowerCase();
  const specEnabled = !!config.SPEC_DRAFT_MODEL_FILE && !!specTypeVal && specTypeVal !== "none";
  const specLabel = specTypeVal === "mtp" ? "draft-mtp" : specTypeVal;
  const mtpLine = specEnabled
    ? `<div>Speculative: ${pill(specLabel, "good")} <span class="muted">${escapeHtml(config.SPEC_DRAFT_MODEL_FILE)}</span></div>`
    : `<div>Speculative: ${pill("off", "")}</div>`;
  const status = runtime.status || {};
  const currentTps = {
    prompt: metricNumber(metrics["llamacpp:prompt_tokens_seconds"]),
    predict: metricNumber(metrics["llamacpp:predicted_tokens_seconds"]),
  };
  if (state.time && state.time !== tokenSpeedState.lastTime) {
    tokenSpeedState.previous = tokenSpeedState.current;
    tokenSpeedState.current = currentTps;
    tokenSpeedState.lastTime = state.time;
  } else if (!tokenSpeedState.current) {
    tokenSpeedState.current = currentTps;
  }
  const previousTps = tokenSpeedState.previous;
  const promptPrevious = previousTps ? formatTps(previousTps.prompt) : "n/a";
  const predictPrevious = previousTps ? formatTps(previousTps.predict) : "n/a";
  const runtimeEl = $("runtimeSummary");
  if (runtimeEl) runtimeEl.innerHTML = `
    <div>${pill(t(status.phase || "unknown") || status.label || "unknown", status.kind || "")} ${status.detail ? escapeHtml(status.detail) : ""}</div>
    <div>${t("model")}: <b>${modelId}</b></div>
    <div>${t("context")}: <b>${ctx}</b></div>
    <div>${t("vision")}: ${pill(vision ? t("on") : t("off"), vision ? "good" : "")}</div>
    ${mtpLine}
    <div>${t("runtimeSize")}: <b>${estimate.runtimeSize ? formatSizeGb(estimate.runtimeSize) : "n/a"}</b></div>
    <div>${t("vramFit")}: ${vram.html}</div>
    <div>${t("ramFit")}: ${ram.html}</div>
    ${ramLine}
    <div class="runtime-rate">${t("promptTps")}: <b>${formatTps(currentTps.prompt)}</b> <span>prev ${promptPrevious}</span></div>
    <div class="runtime-rate">${t("predictTps")}: <b>${formatTps(currentTps.predict)}</b> <span>prev ${predictPrevious}</span></div>
  `;
}

export function renderOpenClawLinks() {
  const target = $("openclawLinksSummary");
  if (!target) return;
  const links = state.openclawConfigManagers || {};
  const last = links.lastNotify || {};
  const results = new Map((last.results || []).map((row) => [row.name, row]));
  const rows = (links.targets || []).map((link) => {
    const result = results.get(link.name);
    const status = result ? (result.ok ? "connected" : "error") : "configured";
    const kind = result ? (result.ok ? "good" : "bad") : "";
    const detail = result?.response?.status || result?.error || result?.response?.profile || "";
    return `<div>${pill(status, kind)} <b>${escapeHtml(link.name)}</b> <span class="muted">${escapeHtml(link.url)}</span>${detail ? `<br><span class="muted">${escapeHtml(String(detail))}</span>` : ""}</div>`;
  }).join("");
  target.innerHTML = rows || `<div>${pill("not configured", "bad")}</div>`;
  if (last.modelHint) {
    target.innerHTML += `<div class="muted">Last model: ${escapeHtml(last.modelHint)}</div>`;
  }
}

export function renderCpu() {
  if (!$("cpuSummary")) return;
  const cpu = state.cpu || {};
  if (!cpu.ok) {
    $("cpuSummary").innerHTML = `<div>${cpu.error || t("noCpuData")}</div>`;
    return;
  }
  $("cpuSummary").innerHTML = `
    <div><b>${escapeHtml(cpu.model || "unknown")}</b></div>
    <div>${t("util")}: <b>${cpu.usagePct || 0}%</b></div>
    <div>${t("load")}: <b>${cpu.load1}</b> / ${cpu.load5} / ${cpu.load15}</div>
    <div>${t("cores")}: <b>${cpu.physicalCores}</b> physical, <b>${cpu.logicalCores}</b> logical</div>
  `;
}

export function renderGpu() {
  if (!$("gpuSummary")) return;
  const gpu = state.gpu || {};
  if (!gpu.ok || !gpu.gpus?.length) {
    $("gpuSummary").innerHTML = `<div>${gpu.error || t("noGpuData")}</div>`;
    return;
  }
  const rows = gpu.gpus.map((row) => `
    <div><b>${row.name}</b></div>
    <div>${t("vram")}: <b>${formatBytesMiB(row.memoryUsedMiB)}</b> ${t("used")}, <b>${formatBytesMiB(row.memoryFreeMiB)}</b> ${t("free")}</div>
    <div>${t("util")}: <b>${row.utilizationGpuPct}%</b>, ${t("gpuMemory")}: <b>${row.utilizationMemoryPct || 0}%</b></div>
    <div>${t("temp")}: <b>${row.temperatureC} C</b>, ${t("power")}: <b>${row.powerDrawW} W</b></div>
    <div>${t("pcie")}: <b>Gen${row.pcieGenCurrent} x${row.pcieWidthCurrent}</b> / Gen${row.pcieGenMax} x${row.pcieWidthMax}</div>
    <div>${t("bandwidth")}: <b>${row.pcieBandwidthCurrentGBs || "n/a"} GB/s</b> PCIe, <b>${row.memoryBandwidthGBs || "n/a"} GB/s</b> VRAM</div>
    <div>Bus: <b>${row.pciBusId || "n/a"}</b>, mem clock: <b>${row.memoryClockMHz || "n/a"} MHz</b></div>
  `);
  $("gpuSummary").innerHTML = rows.join("");
}

export function openSystemInfoModal() {
  const overlay = $("systemInfoOverlay");
  if (!overlay) return;
  renderLlamaCpp();        // refresh from current state before showing
  renderKnownProblems();
  overlay.hidden = false;
  api("/api/controller-info").then(renderControllerInfo).catch((err) => {
    const el = $("controllerInfo");
    if (el) el.innerHTML = `<span class="muted">${escapeHtml(String(err.message || err))}</span>`;
  });
}

// The Controller card: what this host runs (admin/proxy services, cells),
// app git, python and models-disk headroom.
export function renderControllerInfo(info) {
  const el = $("controllerInfo");
  if (!el || !info) return;
  const chips = [];
  for (const svc of info.services || []) {
    const activeTxt = svc.ok ? `${svc.active || "?"} / ${svc.sub || "?"}` : "n/a";
    const good = svc.active === "active";
    const since = svc.since ? ` · ${svc.since.replace(/^\w+ /, "")}` : "";
    chips.push(`<div class="llama-chip ${good ? "good" : "warn"}"><span>${escapeHtml(svc.unit || "")}</span><strong>${escapeHtml(activeTxt)}${svc.pid && svc.pid !== "0" ? ` · PID ${escapeHtml(svc.pid)}` : ""}${escapeHtml(since)}</strong></div>`);
  }
  const cells = info.cells || {};
  if (cells.total != null) {
    chips.push(`<div class="llama-chip ${cells.running ? "good" : ""}"><span>${t("ctrlCells")}</span><strong>${cells.running || 0} / ${cells.total || 0}</strong></div>`);
  }
  const git = info.projectGit || {};
  chips.push(`<div class="llama-chip ${git.dirtyCount ? "warn" : "good"}"><span>${t("ctrlAppGit")}</span><strong>${escapeHtml(git.branch || "n/a")}${git.head ? " @ " + escapeHtml(git.head) : ""}${git.dirtyCount ? ` +${git.dirtyCount}` : ""}</strong></div>`);
  chips.push(`<div class="llama-chip"><span>Python</span><strong>${escapeHtml(info.python || "n/a")}</strong></div>`);
  const disk = info.disk || {};
  if (disk.error) {
    chips.push(`<div class="llama-chip warn"><span>${t("ctrlDisk")}</span><strong>${escapeHtml(disk.path || "")}: ${escapeHtml(disk.error)}</strong></div>`);
  } else if (disk.totalGb != null) {
    const low = (disk.freeGb || 0) < 50;
    chips.push(`<div class="llama-chip ${low ? "warn" : "good"}"><span>${t("ctrlDisk")}</span><strong>${disk.freeGb} GB ${t("ctrlDiskFree")} / ${disk.totalGb} GB</strong></div>`);
  }
  const models = info.models || {};
  if (models.count != null) {
    chips.push(`<div class="llama-chip"><span>${t("ctrlModels")}</span><strong>${models.count} · ${models.totalGb || 0} GB</strong></div>`);
  }
  el.innerHTML = chips.join("");
}
export function closeSystemInfoModal() {
  const overlay = $("systemInfoOverlay");
  if (overlay) overlay.hidden = true;
}

// ── HuggingFace Browser moved to /hf (static/hf.js) ─────────────────────────


export function renderLlamaCpp() {
  const info = state.llamaCpp || {};
  const git = info.git || {};
  const localBuild = parseLlamaBuildVersion(info.version || "");
  const upstreamBuild = git.upstreamBuild || 0;
  const upstreamHead = git.upstreamChecked ? (git.upstreamHead || git.upstreamError || "n/a") : "not checked";
  const upstreamBuildLabel = git.upstreamChecked
    ? (upstreamBuild > 0 ? `b${upstreamBuild}` : (git.upstreamError || "n/a"))
    : "not checked";
  const upstreamNewer = upstreamBuild > 0 && localBuild && upstreamBuild > localBuild.build;
  $("llamaCppSummary").innerHTML = `
    <div class="llama-chip"><span>${t("binary")}</span><strong>${escapeHtml(info.binary || "n/a")}</strong></div>
    <div class="llama-chip"><span>${t("built")}</span><strong>${escapeHtml(info.binaryMtime || "n/a")}</strong></div>
    <div class="llama-chip"><span>${t("commit")}</span><strong>${escapeHtml(git.head || "n/a")}</strong></div>
    <div class="llama-chip"><span>${t("branch")}</span><strong>${escapeHtml(git.branch || "n/a")}</strong></div>
    <div class="llama-chip"><span>${t("upstream")}</span><strong>${escapeHtml(upstreamHead)}</strong></div>
    <div class="llama-chip ${upstreamNewer ? "warn" : (upstreamBuild > 0 ? "good" : "")}"><span>upstream build</span><strong>${escapeHtml(upstreamBuildLabel)}</strong></div>
    <div class="llama-chip"><span>${t("dirty")}</span><strong>${git.dirtyCount || 0}</strong></div>
    <div class="llama-chip ${git.trackedDirtyCount ? "warn" : "good"}"><span>${t("trackedDirty")}</span><strong>${git.trackedDirtyCount || 0}</strong></div>
    <div class="llama-chip ${info.supportsChatTemplateFile ? "good" : "warn"}"><span>${t("supportsChatTemplateFile")}</span><strong>${info.supportsChatTemplateFile ? "yes" : "no"}</strong></div>
  `;
  $("llamaUpdateLog").textContent = info.version || "";
}

export function renderProjectGitBranch() {
  const el = $("projectGitBranch");
  if (!el) return;
  const git = state.projectGit || {};
  const branch = git.branch || "n/a";
  const dirty = Number(git.dirtyCount || 0);
  const label = `git: ${branch}${dirty ? ` +${dirty}` : ""}`;
  el.textContent = label;
  el.title = git.ok === false
    ? `Project git branch unavailable: ${git.error || "unknown error"}`
    : `Project branch ${branch}${git.head ? ` @ ${git.head}` : ""}${dirty ? `, ${dirty} dirty file${dirty === 1 ? "" : "s"}` : ""}`;
  el.classList.toggle("dirty", dirty > 0);
}

export function renderKnownProblems() {
  const diagnostics = state.diagnostics || {};
  const checks = diagnostics.checks || [];
  const row = (check) => `
    <div class="diagnostic-row ${escapeHtml(check.kind || "")}">
      <span>${escapeHtml(check.title || "")}</span>
      <strong>${escapeHtml(check.detail || "")}</strong>
    </div>
  `;
  // The single-server unit is legacy: when it is intentionally off (cells do
  // the serving) its checks and the PID-0 how-to collapse into a details
  // block instead of shouting red at every visitor.
  const isLegacy = (c) => /legacy/i.test(c.title || "");
  const mainRows = checks.filter((c) => !isLegacy(c)).map(row).join("");
  const legacyRows = checks.filter(isLegacy).map(row).join("");
  const legacyArticle = `
    <article class="problem-item">
      <h3>${escapeHtml(t("problemUserBusTitle"))}</h3>
      <p>${escapeHtml(t("problemUserBusCause"))}</p>
      <p>${escapeHtml(t("problemUserBusFix"))}</p>
    </article>
    <div class="diagnostic-list">${legacyRows}</div>
  `;
  const legacyBlock = diagnostics.legacyActive
    ? legacyArticle
    : `<details class="legacy-details">
         <summary>${escapeHtml(t("legacyProblems"))}</summary>
         ${legacyArticle}
       </details>`;
  $("knownProblems").innerHTML = `
    <article class="problem-item">
      <h3>${escapeHtml(t("diagnostics"))}</h3>
      <p>${escapeHtml(diagnostics.summary || "")}</p>
      <div class="diagnostic-list">${mainRows}</div>
      <p>${escapeHtml(diagnostics.fix || "")}</p>
    </article>
    ${legacyBlock}
  `;
}

export function openRepairUserServiceModal() {
  $("confirmTitle").textContent = t("repairUserServiceTitle");
  $("confirmText").textContent = t("repairUserServiceText");
  const meta = [
    [t("service"), state.paths?.service || "llamacpp-current.service"],
    [t("pid"), state.service?.MainPID || "n/a"],
    [t("actionLabel"), t("repairUserService")],
  ];
  $("confirmMeta").hidden = false;
  $("confirmMeta").innerHTML = meta.map(([label, value]) => `
    <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>
  `).join("");
  $("confirmPath").textContent = state.paths?.service || "llamacpp-current.service";
  $("confirmDelete").textContent = t("repairUserService");
  $("confirmDelete").classList.add("danger");
  ui.pendingConfirm = async () => {
    closeConfirmModal();
    const data = await api("/api/repair/user-service", { method: "POST", body: JSON.stringify({}) });
    setState(data.state);
    renderAll();
    toast(t("repairComplete"));
  };
  $("confirmOverlay").hidden = false;
}

export async function checkLlamaCpp() {
  const info = await api("/api/llamacpp");
  state.llamaCpp = info;
  renderLlamaCpp();
  toast(t("reloaded"));
}

export function openUpdateLlamaModal() {
  $("confirmTitle").textContent = t("updateBuildTitle");
  $("confirmText").textContent = t("updateBuildText");
  const info = state.llamaCpp || {};
  const git = info.git || {};
  const meta = [
    [t("branch"), git.branch || "n/a"],
    [t("commit"), git.head || "n/a"],
    [t("trackedDirty"), git.trackedDirtyCount || 0],
  ];
  $("confirmMeta").hidden = false;
  $("confirmMeta").innerHTML = meta.map(([label, value]) => `
    <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>
  `).join("");
  $("confirmPath").textContent = info.binary || "";
  $("confirmDelete").textContent = t("updateBuild");
  $("confirmDelete").classList.add("danger");
  ui.pendingConfirm = async () => {
    closeConfirmModal();
    $("llamaUpdateLog").textContent = "Updating llama.cpp...";
    try {
      const data = await api("/api/llamacpp/update", { method: "POST", body: JSON.stringify({}) });
      setState(data.state);
      const steps = data.result?.steps || [];
      $("llamaUpdateLog").textContent = steps.map((step) => [
        `$ ${step.cmd}`,
        step.stdout,
        step.stderr,
      ].filter(Boolean).join("\n")).join("\n\n");
      renderAll();
      toast(t("updateComplete"));
    } catch (err) {
      $("llamaUpdateLog").textContent = err.message;
      toast(err.message);
    }
  };
  $("confirmOverlay").hidden = false;
}

export async function revertLatest() {
  if (!(await appConfirm(t("revertConfirm")))) return;
  const data = await api("/api/revert", {
    method: "POST",
    body: JSON.stringify({ restart: true }),
  });
  setState(data.state);
  renderAll();
  toast(t("reverted"));
}

