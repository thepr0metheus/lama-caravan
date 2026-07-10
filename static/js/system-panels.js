// Controller service/CPU/GPU panels, the /system page sections, llama.cpp
// update/revert. Renderers null-guard their targets: some ids exist only on
// the board page, some only on /system.
import { appConfirm, settleAppConfirm } from "./dialogs.js";
import { formatCmdline } from "./command-preview.js";
import { helpTip, t } from "./i18n.js";
import { estimateRuntimeMemoryGb, formatSizeGb, ramFit, vramFit } from "./memory.js";
import { formatTps, metricNumber, tokenSpeedState } from "./polling.js";
import { setState, state, ui } from "./state.js";
import { parseLlamaBuildVersion } from "./topology-nodes.js";
import { $, api, escapeHtml, formatBytesMiB, formatMemoryMiB, pill, toast } from "./utils.js";

// Close the shared confirm dialog (the repair/update flows fill it directly).
function closeConfirmModal() {
  settleAppConfirm(false);
}

// The state-driven System sections — refreshed after repair/update instead of
// the board-wide renderAll (this module also runs on /system, no board there).
function renderSystemSections() {
  renderService();
  renderLlamaCpp();
  renderKnownProblems();
  renderProjectGitBranch();
}

export function renderService() {
  const svc = state.service || {};
  const el = $("serviceSummary");
  if (!el) return;
  const status = state.runtime?.status || {};
  const phase = status.phase || svc.ActiveState || "unknown";
  const label = t(phase) || status.label || phase;
  el.innerHTML = `
    <div>${pill(label, status.kind || (svc.ActiveState === "active" ? "good" : "bad"))} ${escapeHtml(svc.SubState || "")}</div>
    <div>${t("pid")}: <b>${svc.MainPID || "0"}</b></div>
    <div>${t("started")}: <b>${svc.ExecMainStartTimestamp || "n/a"}</b></div>
    <div>${t("service")}: <b>${state.paths.service}</b></div>
    ${status.detail ? `<div>${escapeHtml(status.detail)}</div>` : ""}
  `;
  const cmdEl = $("cmdline");
  if (cmdEl) cmdEl.textContent = svc.cmdline ? formatCmdline(svc.cmdline) : t("noRunningCommand");
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

// ── Models-disk GC modal ─────────────────────────────────────────────────────

export async function openModelGcModal() {
  const overlay = $("modelGcOverlay");
  overlay.hidden = false;
  $("modelGcList").innerHTML = `<span class="muted">…</span>`;
  $("modelGcSummary").textContent = "";
  $("modelGcSelected").textContent = "";
  try {
    const data = await api("/api/models/unused");
    const unused = (data.files || []).filter((f) => !f.referenced)
      .sort((a, b) => b.sizeBytes - a.sizeBytes);
    $("modelGcSummary").textContent = t("gcSummary", {
      path: data.path, count: String(data.unusedCount), gb: String(data.unusedGb) });
    if (!unused.length) {
      $("modelGcList").innerHTML = `<p class="muted">${escapeHtml(t("gcNoUnused"))}</p>`;
      return;
    }
    $("modelGcList").innerHTML = unused.map((f) => `
      <label class="model-gc-row">
        <input type="checkbox" data-gc-file="${escapeHtml(f.path)}" data-gc-size="${f.sizeBytes}">
        <span class="model-gc-name" title="${escapeHtml(f.path)}">${escapeHtml(f.path)}</span>
        <span class="model-gc-meta">${f.sizeGb} GB · ${f.ageDays}d</span>
      </label>`).join("");
    const updateSel = () => {
      const picked = [...document.querySelectorAll("[data-gc-file]:checked")];
      const gb = picked.reduce((a, el) => a + Number(el.dataset.gcSize), 0) / 2 ** 30;
      $("modelGcSelected").textContent = picked.length
        ? `${picked.length} · ${gb.toFixed(1)} GB` : "";
    };
    $("modelGcList").addEventListener("change", updateSel);
  } catch (err) {
    $("modelGcList").innerHTML = `<p class="muted">${escapeHtml(String(err.message || err))}</p>`;
  }
}

export function bindModelGc() {
  $("modelGcBtn")?.addEventListener("click", openModelGcModal);
  $("modelGcClose")?.addEventListener("click", () => { $("modelGcOverlay").hidden = true; });
  $("modelGcOverlay")?.addEventListener("click", (e) => {
    if (e.target === $("modelGcOverlay")) $("modelGcOverlay").hidden = true;
  });
  $("modelGcSelectAll")?.addEventListener("click", () => {
    document.querySelectorAll("[data-gc-file]").forEach((el) => { el.checked = true; });
    $("modelGcList").dispatchEvent(new Event("change"));
  });
  $("modelGcDelete")?.addEventListener("click", async () => {
    const files = [...document.querySelectorAll("[data-gc-file]:checked")].map((el) => el.dataset.gcFile);
    if (!files.length) return;
    if (!(await appConfirm(t("gcConfirm", { count: String(files.length) }), { confirmLabel: t("gcDelete") }))) return;
    const btn = $("modelGcDelete");
    btn.disabled = true; btn.classList.add("btn-busy");
    try {
      const res = await api("/api/models/gc", { method: "POST", body: JSON.stringify({ files }) });
      toast(t("gcFreed", { gb: String(res.freedGb) }));
      openModelGcModal();
      api("/api/controller-info").then(renderControllerInfo).catch(() => {});
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false; btn.classList.remove("btn-busy");
    }
  });
}

// ── Security panel: accounts, sessions, fleet token ─────────────────────────

export function refreshSecurity() {
  api("/api/auth/overview").then(renderSecurity).catch(() => {
    // Auth off → overview is still reachable; a failure here means no session
    // on an auth-enabled instance, which the 401 handler already redirects.
  });
}

function fmtWhen(ts) {
  return ts ? new Date(ts * 1000).toLocaleString() : "—";
}

export function renderSecurity(sec) {
  const el = $("securityInfo");
  if (!el || !sec) return;
  $("authLogoutBtn").hidden = !sec.user;
  if (!sec.enabled) {
    el.innerHTML = `
      <p class="muted">${escapeHtml(t("authOffHint"))}</p>
      <form id="authSetupForm" class="auth-form">
        <input id="authSetupUser" placeholder="${escapeHtml(t("authUsername"))}" autocomplete="off">
        <input id="authSetupPass" type="password" placeholder="${escapeHtml(t("authPassword"))}" autocomplete="new-password">
        <button type="submit">${escapeHtml(t("authEnable"))}</button>
      </form>
      <p id="authSetupMsg" class="muted"></p>`;
    $("authSetupForm").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        const res = await api("/api/auth/setup", { method: "POST", body: JSON.stringify({
          username: $("authSetupUser").value.trim(), password: $("authSetupPass").value }) });
        $("authSetupMsg").innerHTML = `${escapeHtml(t("authFleetTokenIntro"))}<br>` +
          `<code class="auth-token">${escapeHtml(res.fleetToken)}</code><br>` +
          `<span class="muted">${escapeHtml(t("authFleetTokenHint"))}</span>`;
        toast(t("authEnabled"));
        refreshSecurity();
      } catch (err) { toast(err.message); }
    });
    return;
  }
  const users = (sec.users || []).map((u) => {
    const role = u.role || "admin";
    const target = role === "admin" ? "viewer" : "admin";
    return `
    <div class="diagnostic-row">
      <span>${escapeHtml(u.username)}${u.username === sec.user ? " · " + escapeHtml(t("authYou")) : ""}
        <em class="auth-role ${role}">${escapeHtml(role === "viewer" ? t("authRoleViewer") : "admin")}</em></span>
      <strong>
        <button class="mini-btn" data-auth-role="${escapeHtml(u.username)}:${target}" title="${escapeHtml(t("authToggleRole"))}">→ ${escapeHtml(target)}</button>
        <button class="mini-btn" data-auth-passwd="${escapeHtml(u.username)}">${escapeHtml(t("authSetPassword"))}</button>
        <button class="mini-btn danger" data-auth-del="${escapeHtml(u.username)}">✕</button>
      </strong>
    </div>`;
  }).join("");
  const allSessions = sec.sessions || [];
  const sessions = allSessions.slice(0, 5).map((sess) => `
    <div class="diagnostic-row">
      <span>${escapeHtml(sess.username)} · ${escapeHtml(sess.ip || "?")}</span>
      <strong>${escapeHtml(fmtWhen(sess.lastSeen))}
        <button class="mini-btn danger" data-auth-revoke="${escapeHtml(sess.id)}">✕</button>
      </strong>
    </div>`).join("")
    + (allSessions.length > 5 ? `<p class="muted">+${allSessions.length - 5}</p>` : "");
  el.innerHTML = `
    <div class="llama-chip good"><span>${escapeHtml(t("authStatus"))}</span><strong>${escapeHtml(t("authOn"))} · ${escapeHtml(sec.user || "")}</strong></div>
    <h3 class="security-sub">${escapeHtml(t("authUsers"))}</h3>
    <div class="diagnostic-list">${users}</div>
    <form id="authAddForm" class="auth-form">
      <input id="authAddUser" placeholder="${escapeHtml(t("authUsername"))}" autocomplete="off">
      <input id="authAddPass" type="password" placeholder="${escapeHtml(t("authPassword"))}" autocomplete="new-password">
      <select id="authAddRole">
        <option value="admin">admin</option>
        <option value="viewer">${escapeHtml(t("authRoleViewer"))}</option>
      </select>
      <button type="submit">${escapeHtml(t("authAddUser"))}</button>
    </form>
    <h3 class="security-sub">${escapeHtml(t("authSessions"))}
      <button class="mini-btn" id="authRevokeOthers">${escapeHtml(t("authRevokeOthers"))}</button></h3>
    <div class="diagnostic-list">${sessions}</div>
    <h3 class="security-sub">${escapeHtml(t("authFleetToken"))}</h3>
    <p class="muted">${escapeHtml(t("authFleetTokenHint"))}</p>
    <div class="button-row">
      <button id="authShowToken" type="button">${escapeHtml(t("authShowToken"))}</button>
      <button id="authRegenToken" type="button" class="danger">${escapeHtml(t("authRegenToken"))}</button>
    </div>
    <p id="authTokenOut" class="muted"></p>`;

  $("authAddForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api("/api/auth/users", { method: "POST", body: JSON.stringify({
        action: "create", username: $("authAddUser").value.trim(), password: $("authAddPass").value,
        role: $("authAddRole").value }) });
      toast(t("saved"));
      refreshSecurity();
    } catch (err) { toast(err.message); }
  });
  el.querySelectorAll("[data-auth-role]").forEach((b) => b.addEventListener("click", async () => {
    const [user, role] = b.dataset.authRole.split(":");
    try {
      await api("/api/auth/users", { method: "POST", body: JSON.stringify({
        action: "set-role", username: user, role }) });
      refreshSecurity();
    } catch (err) { toast(err.message); }
  }));
  el.querySelectorAll("[data-auth-del]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/auth/users", { method: "POST", body: JSON.stringify({
        action: "delete", username: b.dataset.authDel }) });
      refreshSecurity();
    } catch (err) { toast(err.message); }
  }));
  el.querySelectorAll("[data-auth-passwd]").forEach((b) => b.addEventListener("click", async () => {
    const pass = prompt(t("authNewPasswordPrompt", { user: b.dataset.authPasswd }));
    if (!pass) return;
    try {
      await api("/api/auth/users", { method: "POST", body: JSON.stringify({
        action: "set-password", username: b.dataset.authPasswd, password: pass }) });
      toast(t("saved"));
    } catch (err) { toast(err.message); }
  }));
  el.querySelectorAll("[data-auth-revoke]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api("/api/auth/sessions/revoke", { method: "POST", body: JSON.stringify({ id: b.dataset.authRevoke }) });
      refreshSecurity();
    } catch (err) { toast(err.message); }
  }));
  $("authRevokeOthers")?.addEventListener("click", async () => {
    try {
      await api("/api/auth/sessions/revoke", { method: "POST", body: JSON.stringify({ others: true }) });
      refreshSecurity();
    } catch (err) { toast(err.message); }
  });
  $("authShowToken").addEventListener("click", async () => {
    const res = await api("/api/auth/fleet-token", { method: "POST", body: JSON.stringify({}) });
    $("authTokenOut").innerHTML = `<code class="auth-token">${escapeHtml(res.fleetToken)}</code>`;
  });
  $("authRegenToken").addEventListener("click", async () => {
    if (!(await appConfirm(t("authRegenConfirm"), { confirmLabel: t("authRegenToken") }))) return;
    const res = await api("/api/auth/fleet-token", { method: "POST", body: JSON.stringify({ regenerate: true }) });
    $("authTokenOut").innerHTML = `<code class="auth-token">${escapeHtml(res.fleetToken)}</code> · ${escapeHtml(t("authRegenDone"))}`;
  });
}

// The Controller card: what this host runs (admin/proxy services, cells),
// app git, python and models-disk headroom.
export function renderControllerInfo(info) {
  const el = $("controllerInfo");
  if (!el || !info) return;
  // Container mode: there is no user systemd to repair — the button would
  // only ever answer with a 400.
  if (info.container) $("repairUserServiceBtn")?.closest(".button-with-tip")?.remove();
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
// ── HuggingFace Browser moved to /hf (static/hf.js) ─────────────────────────


export function renderLlamaCpp() {
  const el = $("llamaCppSummary");
  if (!el) return;   // the llama.cpp panel lives on /system only
  const info = state.llamaCpp || {};
  const git = info.git || {};
  const localBuild = parseLlamaBuildVersion(info.version || "");
  const upstreamBuild = git.upstreamBuild || 0;
  const upstreamHead = git.upstreamChecked ? (git.upstreamHead || git.upstreamError || "n/a") : "not checked";
  const upstreamBuildLabel = git.upstreamChecked
    ? (upstreamBuild > 0 ? `b${upstreamBuild}` : (git.upstreamError || "n/a"))
    : "not checked";
  // Local build numbers are clone-local commit counts (shallow clones undercount
  // hugely), so compare COMMITS with the release tag when both sides are known;
  // the numeric comparison is only a fallback. Hash abbrevs vary in length →
  // prefix equality.
  const sameCommit = (a, b) => !!a && !!b && (a.startsWith(b) || b.startsWith(a));
  const upstreamNewer = upstreamBuild > 0 && (
    (git.upstreamBuildCommit && git.head)
      ? !sameCommit(git.upstreamBuildCommit, git.head)
      : (localBuild && upstreamBuild > localBuild.build)
  );
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
  const ver = state.appVersion ? `v${state.appVersion} · ` : "";
  const label = `${ver}git: ${branch}${dirty ? ` +${dirty}` : ""}`;
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
  // All green → just the checks; the how-to prose appears only when a check
  // is actually red/amber (the old always-on advice read as "known problems"
  // even on a perfectly healthy install).
  const unhealthy = checks.some((c) => !isLegacy(c) && (c.kind === "bad" || c.kind === "warn"));
  const advice = unhealthy
    ? `<p>${escapeHtml(diagnostics.summary || "")}</p><p>${escapeHtml(diagnostics.fix || "")}</p>`
    : "";
  const kpEl = $("knownProblems");
  if (!kpEl) return;
  kpEl.innerHTML = `
    <article class="problem-item">
      <div class="diagnostic-list">${mainRows}</div>
      ${advice}
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
    renderSystemSections();
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
      await api("/api/llamacpp/update", { method: "POST", body: JSON.stringify({}) });
      pollLlamaUpdate();
    } catch (err) {
      $("llamaUpdateLog").textContent = err.message;
      toast(err.message);
    }
  };
  $("confirmOverlay").hidden = false;
}

// The update runs install-llama.sh as a background job on the server (a CUDA
// build takes 10-20 min — no HTTP request survives that); poll its log tail
// into the same <pre> the old synchronous flow used.
let _llamaUpdatePollTimer = 0;
async function pollLlamaUpdate() {
  clearTimeout(_llamaUpdatePollTimer);
  let job;
  try {
    job = await api("/api/llamacpp/update-status");
  } catch (err) {
    toast(err.message);
    return;
  }
  const el = $("llamaUpdateLog");
  if (el) {
    el.textContent = (job.lines || []).join("\n") || "...";
    el.scrollTop = el.scrollHeight;
  }
  if (job.running) {
    _llamaUpdatePollTimer = setTimeout(pollLlamaUpdate, 2000);
    return;
  }
  if (job.done && job.rc === 0) {
    toast(t("updateComplete"));
    try { await checkLlamaCpp(); } catch { /* chips refresh is best-effort */ }
  } else if (job.done) {
    toast(job.error || `update failed (rc=${job.rc})`);
  }
}

export async function revertLatest() {
  if (!(await appConfirm(t("revertConfirm")))) return;
  const data = await api("/api/revert", {
    method: "POST",
    body: JSON.stringify({ restart: true }),
  });
  setState(data.state);
  renderSystemSections();
  toast(t("reverted"));
}

