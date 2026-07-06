// Remote cell lifecycle: reserve/start/stop, tr- edit form, remote backups.
import { appConfirm, appPrompt } from "./dialogs.js";
import { renderCommandPreview } from "./command-preview.js";
import { defaultOnOptionalToggles } from "./constants.js";
import { refreshFavoritesPanel } from "./favorites.js";
import {
  badge,
  maybeAutofillModelHelpersPfx,
  modelsByPath,
  readConfigForm,
  renderChatTemplateHint,
  renderFields,
  renderModelInsight,
  renderModelSelects,
  syncCompanionMuting,
  syncToggleLabel,
} from "./form.js";
import { t } from "./i18n.js";
import {
  applyConfigToForm,
  deleteBackup,
  openTopologyLlamaEdit,
  setEditCurrentCommand,
  suggestedSnapshotName,
  wireCellKindToggle,
} from "./llama-edit.js";
import { refreshComputeTarget } from "./memory.js";
import { action, startMonitor } from "./polling.js";
import { state, topology } from "./state.js";
import { topologyStatusPill } from "./topology-activity.js";
import { openNodeServerDetail } from "./topology-nodes.js";
import { _topologyRenderPending, markTopologyRenderPending, refreshTopology, renderTopology, topologyInteractionActive, topologyServerPhase } from "./topology-render.js";
import { $, api, escapeHtml, formatMemoryMiB, toast } from "./utils.js";

export let _trCachedModels = new Set(); // relative paths of .gguf files cached on the current remote host
export function topologyClientGpusHtml(client) {
  const gpus = client?.gpus || [];
  if (!gpus.length) return "";
  // A client can hold several concurrent slots (translator + whisper + …). We
  // can't map a node to a specific GPU from this data, so list every running
  // slot's port on each GPU row (same imprecision as the old single-node view).
  const lnodes = (Array.isArray(client?.llamaNodes) && client.llamaNodes.length)
    ? client.llamaNodes
    : (client?.llamaNode ? [client.llamaNode] : []);
  const running = lnodes.filter((n) => n && n.running === true && Number(n.port) > 0);

  const rows = gpus.map((gpu, idx) => {
    if (gpu.driverStatus === "driver_missing") {
      return `
        <div class="client-gpu-row" style="display:flex;align-items:center;justify-content:space-between;gap:8px">
          <span>🖥 <b>${escapeHtml(gpu.name || "GPU")}</b>
            <span class="topology-muted" style="color:var(--warn,#e0a000)">⚠ ${escapeHtml(t("topologyClientGpuNoDriver"))}</span>
          </span>
        </div>`;
    }
    const used = formatMemoryMiB(gpu.memoryUsedMiB);
    const total = formatMemoryMiB(gpu.memoryTotalMiB);
    const util = gpu.utilizationGpuPct ?? "0";
    const temp = gpu.temperatureC ?? "n/a";

    let actionHtml;
    if (running.length) {
      actionHtml = running.map((n) => {
        const uptime = n.uptimeSec ? t("topologyClientGpuUptime").replace("{sec}", n.uptimeSec) : "";
        const modelShort = (n.modelPath || "").split("/").pop() || "";
        return `<span class="topology-muted" style="font-size:11px">
          ▶ :${escapeHtml(String(n.port))} ${escapeHtml(uptime)}${modelShort ? " · " + escapeHtml(modelShort) : ""}
        </span>`;
      }).join("<br>");
    } else {
      actionHtml = `<span class="topology-muted" style="font-size:11px;font-style:italic">${escapeHtml(t("topologyClientGpuAvailable"))}</span>`;
    }

    return `
      <div class="client-gpu-row" style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">
        <span>🖥 <b>${escapeHtml(gpu.name || "GPU")}</b>
          <span class="topology-muted">VRAM ${used}/${total} · ${escapeHtml(String(util))}% · ${escapeHtml(String(temp))}C</span>
        </span>
        ${actionHtml}
      </div>`;
  }).join("");

  return `<div class="client-gpus" style="margin-top:6px;padding:6px 0;border-top:1px solid var(--border,#333);display:flex;flex-direction:column;gap:4px">
    <div class="topology-muted" style="font-size:11px">${escapeHtml(t("topologyClientGpus"))}</div>
    ${rows}
  </div>`;
}

// ── Remote llama-server start tracking ───────────────────────────────────────
// A remote model can take a while to download + load into VRAM. The route-agent
// only reports llamaNode.running once the HTTP server is actually up, so until
// then we show an optimistic "loading" placeholder card in the Llama Servers
// panel and poll topology until the real server appears (or we time out).
export const _pendingRemoteStarts = new Map(); // hostId -> { hostId, hostName, modelName, port, gpuName, clientIp, startedAt, phase, error }
export const _stoppingHosts = new Set(); // hostIds currently in the process of stopping
export const _deletingSlots = new Set(); // "hostId:port" keys currently being deleted
export const _reservingCells = new Map(); // hostId -> { port, startedAt }
export const _newReservedCells = new Set(); // "hostId:port" keys that should flash after creation
export const _expandedCellCfgs = new Set(); // "hostId:port" keys with expanded config block
export const _stoppingCells = new Set();   // "hostId:port" keys currently being stopped
// Any in-flight cell action ("hostId:port" -> "start"|"stop"|...): renders as a
// busy card and is part of the structure fingerprint, so poll renders can't
// skip the transition. Cleared in cellServiceAction's finally.
export const _pendingCellActions = new Map();

// 0 ms feedback without waiting for a render: disable the card's action row
// and put a spinner on the clicked button. The next full render recreates the
// buttons from _pendingCellActions, so the state carries over.
function _patchCellButtonsBusy(hostId, port, actionName) {
  const attr = actionName === "stop" ? "data-node-cell-stop"
    : actionName === "start" ? "data-node-cell-launch" : "data-node-cell-boot";
  const btn = document.querySelector(`[${attr}="${hostId}"][data-node-cell-port="${port}"]`);
  if (!btn) return;
  const row = btn.parentElement;
  row?.querySelectorAll("button").forEach((b) => { b.disabled = true; b.classList.add("muted"); b.classList.remove("ok", "warn", "del"); });
  const lbl = btn.querySelector(".nab-lbl");
  btn.innerHTML = `<span class="topology-spinner stopping-spinner" aria-hidden="true"></span>` + (lbl ? lbl.outerHTML : "");
}
export let _remoteStartWatchTimer = null;
export const REMOTE_START_TIMEOUT_MS = 240_000;

export function registerPendingRemoteStart(info) {
  _pendingRemoteStarts.set(info.hostId, {
    phase: "starting",
    startedAt: Date.now(),
    ...info,
  });
  startRemoteStartWatch();
}

export function clearPendingRemoteStart(hostId) {
  _pendingRemoteStarts.delete(hostId);
  // The watch loop itself decides when to stop (a server-side startup may
  // still be in flight after the client placeholder hands off).
}

// True while anything remote is still coming up: a client-side optimistic
// placeholder, or a server-reported resolving/downloading/loading server.
export function remoteStartupInFlight() {
  if ([..._pendingRemoteStarts.values()].some((p) => p.phase === "starting")) return true;
  const startup = ["resolving", "downloading", "loading"];
  return (topology?.server?.llamaServers || [])
    .some((s) => s.isRemote && startup.includes(s.phase));
}

export function startRemoteStartWatch() {
  if (_remoteStartWatchTimer) return;
  _remoteStartWatchTimer = setInterval(() => {
    // Time out optimistic client placeholders that never got picked up.
    const now = Date.now();
    for (const [, p] of _pendingRemoteStarts) {
      if (p.phase === "starting" && now - p.startedAt > REMOTE_START_TIMEOUT_MS) {
        p.phase = "timeout";
      }
    }
    if (!remoteStartupInFlight()) {
      // Nothing loading anymore — stop polling. Terminal (timeout/error)
      // placeholder cards stay on screen until the user dismisses them.
      clearInterval(_remoteStartWatchTimer);
      _remoteStartWatchTimer = null;
      if (topologyInteractionActive()) markTopologyRenderPending();
      else renderTopology();
      return;
    }
    refreshTopology().catch(() => {});
  }, 2000);
}

// Shared server-slot actions (used by the node view).
export function openRemoteFormForHost(hostId, port = "") {
  const client = (topology?.clients || []).find((c) => c.id === hostId) || {};
  openLlamaRemoteEdit(hostId, (client.gpus && client.gpus[0] && client.gpus[0].name) || "", client.gpus || [], port);
}

export function nextTopologyCellPort() {
  const used = new Set();
  (topology?.nodes || []).forEach((n) => (n.servers || []).forEach((s) => {
    const port = Number(s.port || 0);
    if (port) used.add(port);
  }));
  // Proxy routes (agent + bridge ports) share the fleet-wide numbering — a
  // cell must never take a port the proxy already listens on (the backend
  // used_server_cell_ports applies the same union).
  (topology?.proxies || []).forEach((p) => {
    const port = Number(p.port || 0);
    if (port) used.add(port);
  });
  let port = 8001;
  while (used.has(port)) port += 1;
  return port;
}

export async function reserveServerCell(hostId, portHint = "") {
  const hostKey = String(hostId || "");
  const pendingPort = Number(portHint || nextTopologyCellPort() || 0);
  if (!(await appConfirm(t("dlgReserveCell", { port: String(pendingPort || "?") }),
                         { danger: false, confirmLabel: t("topologyReserveCellLabel"), scene: "create" }))) return;
  if (hostKey && pendingPort) {
    _reservingCells.set(hostKey, { port: pendingPort, startedAt: Date.now() });
    renderTopology();
  }
  try {
    const result = await api("/api/topology/server-slot/add", {
      method: "POST",
      body: JSON.stringify({ hostId }),
    });
    const created = result?.cell || result?.slot || {};
    const createdHost = String(created.hostId || hostId || "");
    const createdPort = Number(created.port || pendingPort || 0);
    if (createdHost && createdPort) {
      const key = `${createdHost}:${createdPort}`;
      _newReservedCells.add(key);
      setTimeout(() => {
        _newReservedCells.delete(key);
        if (!topologyInteractionActive()) renderTopology();
      }, 1400);
    }
    // Keep the spinner up until the new cell is actually ON the board —
    // clearing it on the API reply left a dead gap while the heavier
    // /api/topology refetch was still in flight ("the UI hung").
    try {
      await refreshTopology();
    } catch { /* poll will catch up */ }
    _reservingCells.delete(hostKey);
    if (!topologyInteractionActive()) renderTopology();
  } catch (e) {
    _reservingCells.delete(hostKey);
    renderTopology();
    toast(String(e));
  }
}

export async function cellServiceAction(hostId, port, actionName) {
  const cellKey = `${hostId}:${port}`;
  _pendingCellActions.set(cellKey, actionName);
  _patchCellButtonsBusy(hostId, port, actionName);
  if (actionName === "stop") {
    _stoppingCells.add(cellKey);
    if (!topologyInteractionActive()) renderTopology();
  }
  try {
    const res = await api("/api/topology/server-cell/action", {
      method: "POST",
      body: JSON.stringify({ hostId, port: Number(port), action: actionName }),
      signal: AbortSignal.timeout(60000),
    });
    // The request can succeed (HTTP 200) but the agent may reject the action —
    // e.g. a client has a single server slot and another cell is still
    // starting/downloading. Surface that instead of silently doing nothing.
    if (res && res.ok === false) {
      const raw = String((res.result && res.result.error) || res.error || t("cellActionFailed"));
      const busy = /already|in progress|already running/i.test(raw);
      toast(busy
        ? `⚠️ ${raw} — ${t("cellSlotBusyHint")}`
        : `⚠️ ${raw}`);
    }
    if (actionName === "stop") {
      setTimeout(() => {
        _stoppingCells.delete(cellKey);
        _pendingCellActions.delete(cellKey);
        refreshTopology().catch(() => {});
      }, 1200);
    } else {
      _pendingCellActions.delete(cellKey);
      refreshTopology().catch(() => {});
    }
  } catch (e) {
    _stoppingCells.delete(cellKey);
    _pendingCellActions.delete(cellKey);
    if (!topologyInteractionActive()) renderTopology();
    toast(String(e));
  }
}

export async function deleteTopologyClient(clientId) {
  const client = (topology?.clients || []).find((c) => c.id === clientId);
  const name = client?.name || clientId;
  if (!(await appConfirm(t("dlgDeleteClient", { name }), { confirmLabel: t("deleteAction") }))) return;
  try {
    await api("/api/topology/client/delete", {
      method: "POST",
      body: JSON.stringify({ clientId }),
    });
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

// Register a discovered (running but unregistered) agent into the fleet registry.
export async function discoveryAddCandidate(suggestedId, host) {
  const id = ((await appPrompt(t("dlgRegisterAgentId"), { value: suggestedId || "", scene: "create" })) || "").trim();
  if (!id) return;
  const ip = ((await appPrompt(t("dlgRegisterHost"), { value: host || "", scene: "create" })) || "").trim();
  if (!ip) return;
  const portStr = ((await appPrompt(t("dlgRegisterPort", { ip }), { value: "18796", scene: "create" })) || "").trim();
  const port = parseInt(portStr, 10);
  if (!port) { toast(t("portRequired")); return; }
  try {
    const res = await api("/api/topology/discover/add", {
      method: "POST",
      body: JSON.stringify({ id, name: id, host: ip, port }),
    });
    toast(res?.ok ? t("agentRegistered", { id }) : t("agentAddFailed", { err: res?.error || "?" }));
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

export async function deleteTopologyClientAgent(clientId, agentId) {
  const client = (topology?.clients || []).find((c) => c.id === clientId);
  const agent = (client?.agents || []).find((a) => a.id === agentId);
  const name = agent?.name || agentId;
  if (!(await appConfirm(t("dlgDeleteAgent", { name }), { confirmLabel: t("deleteAction") }))) return;
  try {
    await api("/api/topology/client/agent/delete", {
      method: "POST",
      body: JSON.stringify({ clientId, agentId }),
    });
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

export async function deleteOrphanAgent(clientId, agentId) {
  if (!(await appConfirm(t("dlgDeleteOrphan", { agent: agentId, client: clientId }), { confirmLabel: t("deleteAction") }))) return;
  try {
    const res = await api("/api/topology/orphan-assignment/delete", {
      method: "POST",
      body: JSON.stringify({ clientId, agentId }),
    });
    const freed = (res && res.freedPorts) || [];
    toast(freed.length ? t("agentRemovedPorts", { id: agentId, ports: freed.map((p) => ":" + p).join(" ") }) : t("agentRemoved", { id: agentId }));
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

export async function deleteServerSlot(hostId, port) {
  const key = `${hostId}:${port}`;
  _deletingSlots.add(key);
  renderTopology();
  try {
    await api("/api/topology/server-slot/delete", {
      method: "POST",
      body: JSON.stringify({ hostId, port: Number(port) }),
    });
    _deletingSlots.delete(key);
    refreshTopology().catch(() => {});
  } catch (e) {
    _deletingSlots.delete(key);
    renderTopology();
    toast(String(e));
  }
}

// Bind data-node-start / data-node-slot-del within a root element (scoped so
// classic board and node view don't double-bind each other's buttons).
export function bindServerSlotControls(root) {
  if (!root) return;
  root.querySelectorAll("[data-node-start]").forEach((b) =>
    b.addEventListener("click", () => openRemoteFormForHost(b.dataset.nodeStart, b.dataset.nodeStartPort || "")));
  root.querySelectorAll("[data-node-cell-start]").forEach((b) =>
    b.addEventListener("click", () => {
      const hostId = b.dataset.nodeCellStart;
      const port = b.dataset.nodeCellPort || "";
      if (b.dataset.nodeRole === "controller") openTopologyLlamaEdit("add", port);
      else openRemoteFormForHost(hostId, port);
    }));
  // Launch a configured cell directly (no modal — model already set)
  root.querySelectorAll("[data-node-cell-launch]").forEach((b) =>
    b.addEventListener("click", async () => {
      const port = b.dataset.nodeCellPort;
      const model = b.closest("article")?.querySelector(".node-model-name")?.textContent?.trim();
      const msg = model ? t("dlgStartModel", { model, port }) : t("dlgStartPort", { port });
      if (!(await appConfirm(msg, { danger: false, confirmLabel: t("dlgStartLabel"), scene: "start" }))) return;
      cellServiceAction(b.dataset.nodeCellLaunch, port, "start");
    }));
  root.querySelectorAll("[data-node-cell-stop]").forEach((b) =>
    b.addEventListener("click", async () => {
      const port = b.dataset.nodeCellPort;
      const model = b.closest("article")?.querySelector(".node-model-name")?.textContent?.trim();
      const msg = model ? t("dlgStopModel", { model, port }) : t("dlgStopPort", { port });
      if (!(await appConfirm(msg, { confirmLabel: t("stop"), scene: "stop" }))) return;
      cellServiceAction(b.dataset.nodeCellStop, port, "stop");
    }));
  root.querySelectorAll("[data-node-cell-boot]").forEach((b) =>
    b.addEventListener("click", () => cellServiceAction(b.dataset.nodeCellBoot, b.dataset.nodeCellPort, b.dataset.nodeCellBootAction)));
  root.querySelectorAll("[data-node-reserve]").forEach((b) =>
    b.addEventListener("click", () => reserveServerCell(b.dataset.nodeReserve, b.dataset.nodeReservePort || "")));
  // Add server — controller routes to the local the controller add flow, clients to the
  // remote route-agent add flow.
  root.querySelectorAll("[data-node-add]").forEach((b) =>
    b.addEventListener("click", () => {
      reserveServerCell(b.dataset.nodeAdd, b.dataset.nodeReservePort || "");
    }));
  // Controller server edit (the controller llama config)
  root.querySelectorAll("[data-node-ctrl-edit]").forEach((b) =>
    b.addEventListener("click", () => openTopologyLlamaEdit("edit")));
  // Controller server stop (stops llamacpp-current.service, not the admin panel)
  root.querySelectorAll("[data-node-ctrl-stop]").forEach((b) =>
    b.addEventListener("click", () => {
      appConfirm(t("dlgStopLlama"), { confirmLabel: t("stop"), scene: "stop" })
        .then((ok) => { if (ok) action("stop"); });
    }));
  // Controller server start
  root.querySelectorAll("[data-node-ctrl-start]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!(await appConfirm(t("dlgStartPort", { port: "" }).replace(" :?", "?"), { danger: false, confirmLabel: t("dlgStartLabel"), scene: "start" }))) return;
      action("start");
    }));
  root.querySelectorAll("[data-node-slot-del]").forEach((b) =>
    b.addEventListener("click", () => {
      const [hostId, port] = b.dataset.nodeSlotDel.split(":");
      appConfirm(t("dlgDeleteCell", { port }), { confirmLabel: t("deleteAction") })
        .then((ok) => { if (ok) deleteServerSlot(hostId, port); });
    }));
  // Drill into the full server detail modal
  root.querySelectorAll("[data-node-detail]").forEach((b) =>
    b.addEventListener("click", () => {
      const [nid, port] = b.dataset.nodeDetail.split(":");
      openNodeServerDetail(nid, port);
    }));
}

// Optimistic "starting…" card for the NODE view Gives immediate feedback on click, then hands
// off to the real card once the node reports a live/failed server — so a fast
// failure (e.g. graph_reserve OOM) no longer looks like the GUI ignored you.
export function nodeStartingCardHtml(node) {
  const p = _pendingRemoteStarts.get(String(node.id));
  if (!p || p.phase !== "starting") return "";
  if ((node.servers || []).some((s) => topologyServerPhase(s) !== "stopped")) {
    clearPendingRemoteStart(node.id);  // real card now drives the state
    return "";
  }
  return `
    <article class="node-server loading" data-pending-remote-start="${escapeHtml(String(node.id))}">
      <div class="node-server-head">
        <span class="topology-spinner" aria-hidden="true"></span>
        <span class="topology-addr-link" style="pointer-events:none">${escapeHtml(p.clientIp || node.ip || "")}${p.port ? ":" + escapeHtml(String(p.port)) : ""}</span>
        ${topologyStatusPill("loading")}
        <span style="flex:1"></span>
        <button class="mini-link" type="button" data-pending-remote-dismiss="${escapeHtml(String(node.id))}" style="color:var(--muted,#888)" title="${escapeHtml(t("topologyRemoteStartDismiss"))}">✕</button>
      </div>
      ${p.modelName ? `<div class="topology-muted" style="font-size:12px;padding:2px 0">${escapeHtml(p.modelName)}</div>` : ""}
      <div class="topology-muted" style="font-size:11px">${escapeHtml(t("topologyRemoteStarting"))}…</div>
    </article>`;
}

export async function submitLlamaStop(hostId) {
  const client = (topology?.clients || []).find((c) => c.id === hostId);
  const name = client?.name || hostId;
  if (!(await appConfirm(`${t("stopServerConfirm", { host: name })}`, { confirmLabel: t("stop"), scene: "stop" }))) return;

  _stoppingHosts.add(hostId);
  if (!topologyInteractionActive()) renderTopology();

  try {
    clearPendingRemoteStart(hostId);
    await api("/api/topology/client-llama/stop", { method: "POST", body: JSON.stringify({ hostId }) });
    setTimeout(() => {
      _stoppingHosts.delete(hostId);
      refreshTopology().catch(() => {});
    }, 1500);
  } catch (_) {
    _stoppingHosts.delete(hostId);
    if (!topologyInteractionActive()) renderTopology();
  }
}

// ── nvidia-smi source selector (drawer panel) ────────────────────────────────
export let _nvidiaSmiSource = "local"; // "local" = the controller, or a client hostId

export function renderNvidiaSmiSourceButtons() {
  const container = $("nvidiaSmiSources");
  if (!container) return;

  // Build list: the controller first, then online clients with GPUs
  const sources = [
    { id: "local", label: topology?.server?.name || "Controller" },
  ];
  for (const client of (topology?.clients || [])) {
    if (client.state !== "online") continue;
    if (!(client.gpus || []).length) continue;
    const gpu = client.gpus[0] || {};
    sources.push({
      id: client.id,
      label: client.name || client.id,
      gpu: gpu.name || "",
    });
  }

  // Only show buttons when there's more than one source
  if (sources.length <= 1) { container.innerHTML = ""; return; }

  // Ensure selected source still exists
  if (!sources.find((s) => s.id === _nvidiaSmiSource)) _nvidiaSmiSource = "local";

  container.innerHTML = sources.map((s) => {
    const active = _nvidiaSmiSource === s.id;
    const label = s.gpu ? `${s.label} · ${s.gpu.replace("NVIDIA GeForce ", "").replace("NVIDIA ", "")}` : s.label;
    return `<button type="button"
      class="mini-link${active ? "" : ""}"
      data-smi-source="${escapeHtml(s.id)}"
      style="font-size:11px;padding:2px 8px;border-radius:3px;
        background:${active ? "var(--accent,#4f8ef7)" : "var(--bg-card,#222)"};
        color:${active ? "#fff" : "inherit"};border:1px solid var(--border,#444)">
      ${escapeHtml(label)}
    </button>`;
  }).join("");

  container.querySelectorAll("[data-smi-source]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _nvidiaSmiSource = btn.dataset.smiSource;

      // Update active styles WITHOUT rebuilding DOM — rebuilding would destroy
      // the focused button, causing focusout on the drawer section which stops
      // the monitor interval.
      container.querySelectorAll("[data-smi-source]").forEach((b) => {
        const isActive = b.dataset.smiSource === _nvidiaSmiSource;
        b.style.background = isActive ? "var(--accent,#4f8ef7)" : "var(--bg-card,#222)";
        b.style.color = isActive ? "#fff" : "inherit";
      });

      const target = $("monitorNvidia");
      if (target) target.textContent = t("loadingEllipsis");
      // Restart interval so it uses the new source immediately
      startMonitor("nvidia-smi");
    });
  });
}

// ── Remote llama server — full edit modal (tr- prefix, mirrors the controller form) ──
export let _trFormReady = false;
export let _trHostId = "";
export let _trGpuName = "";
export let _trClientGpus = [];
export let _trClientCpu = {};
export let _trPurging = false; // true while cache purge is in flight → blocks Start
export let _trCellPort = "";

// ── Per-cell schedule panel (right rail of the cell editor) ──────────────────
const SCHED_DAY_KEYS = ["dayMo", "dayTu", "dayWe", "dayTh", "dayFr", "daySa", "daySu"];
let _schedSaveTimer = 0;
const _schedWired = new Set();
let _schedCtx = { pfx: "tr", hostId: "", port: 0 };

function _schedRead(pfx) {
  const days = [...document.querySelectorAll(`#${pfx}-schedDays [data-day]`)]
    .filter((b) => b.classList.contains("on"))
    .map((b) => Number(b.dataset.day));
  return {
    enabled: $(`${pfx}-schedEnabled`).checked,
    start: $(`${pfx}-schedStart`).value || "22:00",
    stop: $(`${pfx}-schedStop`).value || "08:00",
    days,
  };
}

function _schedQueueSave() {
  const { pfx, hostId, port } = _schedCtx;
  clearTimeout(_schedSaveTimer);
  _schedSaveTimer = setTimeout(async () => {
    try {
      const res = await api("/api/topology/server-cell/schedule", {
        method: "POST",
        body: JSON.stringify({ hostId, port, schedule: _schedRead(pfx) }),
      });
      const sc = res.schedule || {};
      $(`${pfx}-schedStatus`).textContent = sc.enabled
        ? t("schedSaved", { start: sc.start, stop: sc.stop })
        : t("schedOff");
      refreshTopology().catch(() => {});
    } catch (e) { toast(String(e)); }
  }, 450);
}

export function renderSchedulePanel(pfx, hostId, cellPort, schedule) {
  const panel = $(`${pfx}-schedulePanel`);
  if (!panel) return;
  // Панель имеет смысл только для сохранённой ячейки (slot существует).
  panel.hidden = !cellPort;
  if (!cellPort) return;
  _schedCtx = { pfx, hostId, port: parseInt(cellPort, 10) };
  const sc = schedule || {};
  $(`${pfx}-schedEnabled`).checked = !!sc.enabled;
  $(`${pfx}-schedStart`).value = sc.start || "22:00";
  $(`${pfx}-schedStop`).value = sc.stop || "08:00";
  const daysOn = new Set((sc.days || []).map(Number));
  $(`${pfx}-schedDays`).innerHTML = SCHED_DAY_KEYS.map((k, i) =>
    `<button type="button" class="sched-day${daysOn.size === 0 || daysOn.has(i) ? " on" : ""}${daysOn.size === 0 ? " implicit" : ""}" data-day="${i}">${escapeHtml(t(k))}</button>`).join("");
  $(`${pfx}-schedStatus`).textContent = sc.enabled ? t("schedSaved", { start: sc.start, stop: sc.stop }) : "";
  if (!_schedWired.has(pfx)) {
    _schedWired.add(pfx);
    $(`${pfx}-schedEnabled`).addEventListener("change", _schedQueueSave);
    $(`${pfx}-schedStart`).addEventListener("change", _schedQueueSave);
    $(`${pfx}-schedStop`).addEventListener("change", _schedQueueSave);
    $(`${pfx}-schedDays`).addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-day]");
      if (!b) return;
      // Первый клик по "неявным всем дням" фиксирует явный выбор одного дня.
      const implicit = $(`${pfx}-schedDays`).querySelector(".implicit");
      if (implicit) {
        document.querySelectorAll(`#${pfx}-schedDays [data-day]`).forEach((x) => x.classList.remove("on", "implicit"));
        b.classList.add("on");
      } else {
        b.classList.toggle("on");
      }
      _schedQueueSave();
    });
  }
}

// Слот из текущей топологии для (hostId, port) — источник schedule.
export function findSlotEntry(hostId, port) {
  return ((topology?.server || {}).llamaServers || [])
    .find((sv) => String(sv.port) === String(port) &&
                  ((sv.clientId || "") === (hostId === "skynet" ? "" : hostId)));
}

export function openLlamaRemoteEdit(hostId, gpuName, clientGpus, cellPort = "") {
  _trHostId = hostId;
  _trClientGpus = Array.isArray(clientGpus) ? clientGpus : [];
  _trGpuName = String(gpuName || _trClientGpus[0]?.name || "");
  _trClientCpu = ((topology?.clients || []).find((c) => c.id === hostId) || {}).cpu || {};
  _trCellPort = cellPort ? String(cellPort) : "";

  // One-time form field injection
  if (!_trFormReady) {
    renderFields("tr-");
    wireCellKindToggle("tr-");
    // MODEL_FILE change: auto-fill mmproj + refresh insight + preview
    $("tr-MODEL_FILE")?.addEventListener("change", () => {
      maybeAutofillModelHelpersPfx("tr-", { aliasFollow: true });
    });
    $("tr-OFFLOAD_MMPROJ")?.addEventListener("change", (e) => {
      syncToggleLabel(e.target);
      syncCompanionMuting("tr-");
    });
    $("tr-SPEC_ENABLED")?.addEventListener("change", (e) => {
      const selected = modelsByPath().get($("tr-MODEL_FILE")?.value || "");
      const specTypeEl = $("tr-SPEC_TYPE");
      if (specTypeEl) specTypeEl.value = e.target.checked ? (selected?.familyDefaults?.SPEC_TYPE || "draft-mtp") : "";
      syncToggleLabel(e.target);
      syncCompanionMuting("tr-");
    });
    // MMPROJ / other fields: refresh insight + preview
    $("llamaRemoteEditForm")?.addEventListener("change", (e) => {
      if (e.target.id === "tr-MODEL_FILE") return; // handled above
      const bareId = (e.target?.id || "").replace(/^tr-/, "");
      if (["N_GPU_LAYERS", "DEVICE", "THREADS"].includes(bareId)) refreshComputeTarget("tr-");
      renderModelInsight("tr-");
      renderCommandPreview("tr-");
      renderChatTemplateHint("tr-");
    });
    $("llamaRemoteEditForm")?.addEventListener("input", () => {
      renderCommandPreview("tr-");
    });
    _trFormReady = true;
  }

  renderSchedulePanel("tr", hostId, cellPort, findSlotEntry(hostId, cellPort)?.schedule);

  // Populate model dropdowns (same models as the controller since admin serves them)
  _trCachedModels = new Set(); // reset until the async fetch arrives
  renderModelSelects("tr-");

  // Б: clean-slate defaults — only carry the params that make sense cross-host.
  // Optional toggles (KV_OFFLOAD, MMAP, FIT, CACHE_PROMPT, ENABLE_SLOTS…) are
  // intentionally omitted so defaultOnOptionalToggles alone governs them,
  // avoiding silent carry-over of the controller-specific flags to a different GPU.
  const skynetCfg = state?.config || {};
  const remoteDefaults = {
    MODEL_FILE:           skynetCfg.MODEL_FILE       || "",
    MMPROJ_FILE:          skynetCfg.MMPROJ_FILE      || "",
    CHAT_TEMPLATE_FILE:   "",
    CTX_SIZE:             skynetCfg.CTX_SIZE         || "4096",
    N_GPU_LAYERS:         skynetCfg.N_GPU_LAYERS     || "999",
    CACHE_TYPE_K:         skynetCfg.CACHE_TYPE_K     || "q8_0",
    CACHE_TYPE_V:         skynetCfg.CACHE_TYPE_V     || "q8_0",
    ENABLE_FLASH_ATTN:    skynetCfg.ENABLE_FLASH_ATTN    || "",
    ENABLE_CONT_BATCHING: skynetCfg.ENABLE_CONT_BATCHING || "",
    ENABLE_METRICS:       skynetCfg.ENABLE_METRICS   || "",
    OFFLOAD_MMPROJ:       skynetCfg.OFFLOAD_MMPROJ   || "",
    ENABLE_JINJA:         skynetCfg.ENABLE_JINJA     || "",
    PARALLEL:             "1",
    HOST:                 "0.0.0.0",
    PORT:                 _trCellPort || "8180",
    THREADS:              "1",
    THREADS_BATCH:        "1",
    BATCH_SIZE:           "1024",
    UBATCH_SIZE:          "1024",
    ENABLE_WEBUI:         "1",
    LLAMA_MODELS_DIR:     "",
  };

  // п.4: for an existing cell, the authoritative config is the slotConfig the
  // controller persisted for this host:port — overlay it so the form shows what
  // the cell was actually configured with, not the cross-host defaults above.
  // This is the single source of truth (serverSlots on the controller); we no
  // longer keep a per-host localStorage copy that could drift from it.
  let _trSlotHasConfig = false;
  if (_trCellPort) {
    const slot = (topology?.nodes || [])
      .flatMap((n) => n.servers || [])
      .find((s) => s.isSlot && String(s.clientId || "") === String(hostId) &&
                   String(s.port) === String(_trCellPort));
    if (slot?.slotConfig && Object.keys(slot.slotConfig).length) {
      Object.assign(remoteDefaults, slot.slotConfig);
      _trSlotHasConfig = true;
    }
  }
  if (_trCellPort) remoteDefaults.PORT = _trCellPort;

  applyConfigToForm(remoteDefaults, "tr-");
  const trPortEl = $("tr-PORT");
  if (trPortEl) trPortEl.readOnly = !!_trCellPort;

  // Set hidden LLAMA_MODELS_DIR so command preview shows ~remote path
  const trMdEl = $("tr-LLAMA_MODELS_DIR");
  if (trMdEl) trMdEl.value = "~/llama-model-cache";

  // Auto-correct mmproj on form open: localStorage may have a stale/wrong mmproj
  // from a previous host config. Re-run autofill so the right projector is selected
  // for the current MODEL_FILE (same logic as when the user changes the model).
  maybeAutofillModelHelpersPfx("tr-");

  // Current command + New-command diff baseline (mirrors the controller modal):
  // an existing remote cell shows its own current command; a brand-new add has none.
  setEditCurrentCommand("tr-", (_trCellPort && _trSlotHasConfig) ? "cell" : "new");
  renderModelInsight("tr-");
  renderChatTemplateHint("tr-");
  refreshFavoritesPanel("tr-");  // reflect the latest global favorites order/set

  // п.5: fetch cached model list from remote host asynchronously
  const cacheListEl = $("tr-cacheList");
  if (cacheListEl) cacheListEl.innerHTML = `<span class="topology-muted" style="font-size:11px">${t("cacheListing")}</span>`;
  api(`/api/topology/client-llama/list-cache?hostId=${encodeURIComponent(hostId)}`)
    .then((res) => {
      if (res?.models?.length) {
        _trCachedModels = new Set(res.models.map((m) => m.path));
        renderModelSelects("tr-"); // re-render with ✓ cached labels
      }
      if (cacheListEl) {
        const models = res?.models || [];
        if (!models.length) {
          cacheListEl.innerHTML = `<span class="topology-muted" style="font-size:11px">${t("cacheEmpty")}</span>`;
        } else {
          const totalGb = models.reduce((s, m) => s + (m.sizeBytes || 0), 0) / 1e9;
          cacheListEl.innerHTML = `<div class="tr-cache-list">${
            models.map((m) => {
              const gb = ((m.sizeBytes || 0) / 1e9).toFixed(2);
              const name = (m.path || "").split("/").pop();
              return `<div class="tr-cache-item" title="${escapeHtml(m.path || "")}">
                <span class="tr-cache-name">${escapeHtml(name)}</span>
                <span class="tr-cache-size">${gb} GB</span>
              </div>`;
            }).join("")
          }<div class="tr-cache-total">${models.length} file(s) · ${totalGb.toFixed(2)} GB total</div></div>`;
        }
      }
    })
    .catch(() => {
      if (cacheListEl) cacheListEl.innerHTML = "";
    }); // non-fatal — old route-agents won't have this endpoint

  // Remote GPU info panel
  const gpuBox = $("tr-remoteGpuInfo");
  if (gpuBox) {
    if (_trClientGpus.length) {
      gpuBox.innerHTML = _trClientGpus.map((g) => {
        const totalGb = (Number(g.memoryTotalMiB || 0) / 1024).toFixed(1);
        const freeGb  = (Number(g.memoryFreeMiB  || 0) / 1024).toFixed(1);
        return `<div>🖥 <b>${escapeHtml(g.name || "GPU")}</b><br>
          <span class="topology-muted">${freeGb} GB free / ${totalGb} GB total</span></div>`;
      }).join("");
    } else {
      gpuBox.textContent = t("gpuInfoUnavailable");
    }
  }

  const remTitleEl = $("llamaRemoteEditTitle");
  if (remTitleEl) {
    remTitleEl.textContent = t("remoteAddTitle", { host: `${hostId}${gpuName ? " · " + gpuName : ""}` });
    if (!remTitleEl.parentElement.querySelector(".topo-edit-mode-badge")) {
      const b = document.createElement("span");
      b.className = "topo-edit-mode-badge remote";
      b.textContent = t("badgeRemote");
      remTitleEl.after(b);
    }
  }
  $("llamaRemoteEditOverlay").hidden = false;

  // Load backups asynchronously
  fetchAndRenderRemoteBackups(hostId).catch(() => {});
}

export async function submitRemoteLlamaStart() {
  if (_trPurging) { toast(t("topologyPurgeCacheBlocksStart")); return; }
  const config = readConfigForm("tr-");
  // Command-path runners (custom/vllm/whisper) carry no MODEL_FILE — their
  // artifact lives in COMMAND/VLLM_MODEL/WHISPER_MODEL respectively.
  const runnerId       = (config.RUNNER || "").trim() || (config.CELL_KIND === "command" ? "custom" : "llama-server");
  const isCommandPath  = runnerId !== "llama-server";
  const isCommand      = runnerId === "custom";
  const port           = parseInt(config.PORT || "8180", 10);
  const modelPath      = (config.MODEL_FILE || "").trim();
  const gpuLayers      = parseInt(config.N_GPU_LAYERS || "999", 10);
  const ctxSize        = parseInt(config.CTX_SIZE || "4096", 10);
  const cacheModels    = !!$("tr-cacheModels")?.checked;
  const _startMsg = isCommandPath || !modelPath
    ? t("dlgStartPort", { port: String(port) })
    : t("dlgStartModel", { model: modelPath.split("/").pop(), port: String(port) });
  if (!(await appConfirm(_startMsg, { danger: false, confirmLabel: t("dlgStartLabel"), scene: "start" }))) return;
  if (isCommand) {
    if (!(config.COMMAND || "").trim()) { toast(t("enterCommand")); return; }
  } else if (runnerId === "vllm") {
    if (!(config.VLLM_MODEL || "").trim()) { toast(t("selectModel")); return; }
  } else if (!isCommandPath && !modelPath) { toast(t("selectModel")); return; }

  // Cell mode: save config without starting (same as controller "Применить")
  if (_trCellPort) {
    const btn = $("llamaRemoteEditStart");
    const orig = btn.textContent;
    btn.textContent = t("savingConfig");
    btn.disabled = true;
    btn.classList.add("btn-busy");
    try {
      await api("/api/topology/server-cell/save-config", {
        method: "POST",
        body: JSON.stringify({ hostId: _trHostId, port, config, cacheModels }),
      });
      $("llamaRemoteEditOverlay").hidden = true;
      toast(t("saved"));
      // Pulse the cell card so the eye lands where the chip flips to CONFIGURED.
      const key = `${_trHostId}:${port}`;
      _newReservedCells.add(key);
      setTimeout(() => {
        _newReservedCells.delete(key);
        if (!topologyInteractionActive()) renderTopology();
      }, 2600);
      refreshTopology().catch(() => {});
    } catch (e) {
      toast(String(e));
    } finally {
      btn.textContent = orig;
      btn.disabled = false;
      btn.classList.remove("btn-busy");
    }
    return;
  }

  const btn  = $("llamaRemoteEditStart");
  const orig = btn.textContent;
  btn.textContent = t("topologyClientGpuStarting");
  btn.disabled = true;
  btn.classList.add("btn-busy");
  try {
    const result = await api("/api/topology/client-llama/start", {
      method: "POST",
      // Forward the full form config so the remote builds the same command
      // (mmproj/vision, flash-attn, cache types, threads, jinja, …).
      body: JSON.stringify({ hostId: _trHostId, modelPath, port, gpuLayers, ctxSize, cacheModels, config, cellPort: _trCellPort }),
    });
    if (result?.ok) {
      // Config is persisted server-side in the cell's slot (single source of
      // truth); no per-host localStorage copy needed for the next form open.
      const client = (topology?.clients || []).find((c) => c.id === _trHostId) || {};
      registerPendingRemoteStart({
        hostId: _trHostId,
        hostName: client.name || _trHostId,
        modelName: modelPath.split("/").pop(),
        port,
        clientIp: client.ip || "",
        gpuName: (client.gpus && client.gpus[0] && client.gpus[0].name) || "",
      });
      $("llamaRemoteEditOverlay").hidden = true;
      toast(t("topologyRemoteStartSent", { host: client.name || _trHostId }));
      renderTopology();
    } else {
      toast(result?.result?.error || result?.error || "Error starting remote server");
    }
  } catch (e) {
    const msg = String(e);
    // "startup already in progress" means we sent a duplicate — treat as success:
    // close the dialog and show a friendly notice instead of an error.
    if (msg.toLowerCase().includes("already in progress") || msg.toLowerCase().includes("already starting")) {
      const client = (topology?.clients || []).find((c) => c.id === _trHostId) || {};
      if (!_pendingRemoteStarts.has(_trHostId)) {
        registerPendingRemoteStart({
          hostId: _trHostId,
          hostName: client.name || _trHostId,
          modelName: modelPath.split("/").pop(),
          port,
          clientIp: client.ip || "",
          gpuName: (client.gpus && client.gpus[0] && client.gpus[0].name) || "",
        });
      }
      $("llamaRemoteEditOverlay").hidden = true;
      toast(t("topologyRemoteStartAlreadyInProgress", { host: client.name || _trHostId }));
      renderTopology();
    } else {
      toast(msg);
    }
  } finally {
    btn.textContent = orig;
    btn.disabled = false;
    btn.classList.remove("btn-busy");
  }
}

export async function purgeRemoteModelCache() {
  if (!_trHostId) return;
  if (!(await appConfirm(t("topologyPurgeCacheConfirm", { host: _trHostId })))) return;
  const btn = $("tr-purgeCache");
  const info = $("tr-purgeCacheInfo");
  const startBtn = $("llamaRemoteEditStart");

  // Block Start button and show indeterminate progress while purging
  _trPurging = true;
  if (btn) { btn.disabled = true; btn.textContent = t("topologyPurgeCacheProgress"); }
  if (startBtn) { startBtn.disabled = true; startBtn.title = t("topologyPurgeCacheBlocksStart"); }
  if (info) info.innerHTML = `<span class="topology-spinner" aria-hidden="true"></span> ${escapeHtml(t("topologyPurgeCacheDeleting"))}`;

  try {
    const res = await api("/api/topology/client-llama/purge-cache", {
      method: "POST",
      body: JSON.stringify({ hostId: _trHostId }),
    });
    const r = res?.result || {};
    const freedGb = (Number(r.freedBytes || 0) / 1e9).toFixed(2);
    const msg = `✓ ${t("topologyPurgeCacheDone")}: ${r.removed || 0} file(s), ${freedGb} GB freed`;
    if (info) info.textContent = msg;
    toast(msg);
    // Refresh cache list to show it's now empty
    const cacheListEl = $("tr-cacheList");
    if (cacheListEl) cacheListEl.innerHTML = `<span class="topology-muted" style="font-size:11px">${t("cacheEmpty")}</span>`;
    _trCachedModels = new Set();
    renderModelSelects("tr-");
  } catch (e) {
    if (info) info.textContent = `⚠ ${String(e)}`;
    toast(String(e));
  } finally {
    _trPurging = false;
    if (btn) { btn.disabled = false; btn.textContent = t("topologyPurgeCacheBtn"); }
    if (startBtn) { startBtn.disabled = false; startBtn.title = ""; }
  }
}

// ── Remote llama-node config backups ─────────────────────────────────────────

// Save the current tr- form config as a named backup for this host, stored on the
// controller under <host>/<gpu-or-CPU>/ — mirrors the controller's "Save current
// config" so the client Add-Llama modal works the same.
export async function snapshotRemoteConfig(hostId) {
  const name = await appPrompt(t("snapshotNamePrompt"), { value: suggestedSnapshotName("tr-"), confirmLabel: t("save"), scene: "create" });
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed) { toast(t("snapshotNameRequired")); return; }
  // Same busy treatment as the controller editor: the prompt is already gone,
  // so the save button carries the "working…" signal until the API returns.
  const snapBtn = $("tr-backups")?.querySelector("[data-snapshot-remote]");
  snapBtn?.classList.add("btn-busy");
  if (snapBtn) snapBtn.disabled = true;
  toast(t("snapshotSaving"));
  try {
    await api("/api/topology/client-llama/configs/save", {
      method: "POST",
      body: JSON.stringify({
        hostId,
        gpuName: _trGpuName,
        name: trimmed,
        config: readConfigForm("tr-"),
      }),
    });
    await fetchAndRenderRemoteBackups(hostId);
    toast(`${t("snapshotSaved")}: ${trimmed}`);
  } catch (err) {
    toast(err.message || String(err));
  } finally {
    snapBtn?.classList.remove("btn-busy");
    if (snapBtn) snapBtn.disabled = false;
  }
}

export async function fetchAndRenderRemoteBackups(hostId) {
  const infoEl = $("tr-backupInfo");
  const listEl = $("tr-backups");
  if (!infoEl || !listEl) return;
  infoEl.textContent = t("loadingEllipsis");
  listEl.innerHTML = "";
  const saveCurrentHtml = `
    <button class="backup-save-current" type="button" data-snapshot-remote title="${escapeHtml(t("saveSnapshotHint"))}">
      + ${escapeHtml(t("saveSnapshot"))}
    </button>`;
  try {
    const data = await api(`/api/topology/client-llama/configs?hostId=${encodeURIComponent(hostId)}`);
    const configs = data?.configs || [];
    infoEl.textContent = configs.length ? t("clickBackupHint") : t("noBackups");
    listEl.innerHTML = saveCurrentHtml + configs.map((cfg) => {
      const modelShort = (cfg.modelName || cfg.modelPath || "").split("/").pop();
      // Named snapshots lead with the user's name (the timestamp moves into the
      // meta line); legacy no-name entries keep the old timestamp label.
      const label = cfg.name ? `${cfg.name} — ${modelShort}` : `${cfg.savedAt} — ${modelShort}`;
      const meta = `${cfg.name ? cfg.savedAt + " · " : ""}${cfg.target || "?"} · port ${cfg.port} · ctx ${cfg.ctxSize} · ${cfg.gpuLayers} layers`;
      return `
        <div class="backup-row" title="${escapeHtml(meta)}">
          <button class="backup-item" type="button" data-remote-backup="${escapeHtml(cfg.filename)}">
            <span>${escapeHtml(label)}</span>
            <code>${escapeHtml(meta)}</code>
          </button>
          <button class="backup-delete" type="button"
            data-remote-backup-delete="${escapeHtml(cfg.filename)}"
            aria-label="${escapeHtml(t("deleteBackup"))}">×</button>
        </div>`;
    }).join("");

    // Click: load the full saved config into the form (model, ctx, port, flags…).
    listEl.querySelectorAll("[data-remote-backup]").forEach((btn) => {
      const cfg = configs.find((c) => c.filename === btn.dataset.remoteBackup);
      if (!cfg) return;
      btn.addEventListener("click", () => {
        applyConfigToForm(cfg.config || {}, "tr-");
        maybeAutofillModelHelpersPfx("tr-");
        refreshComputeTarget("tr-");
        toast(`${t("loadedBackup")}: ${cfg.savedAt}`);
        if ($("tr-backupInfo")) $("tr-backupInfo").textContent = `${t("loadedBackup")}: ${cfg.savedAt}`;
      });
    });

    // Delete button
    listEl.querySelectorAll("[data-remote-backup-delete]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        if (!(await appConfirm(t("dlgDeleteBackupName", { name: btn.dataset.remoteBackupDelete }), { confirmLabel: t("deleteAction") }))) return;
        try {
          await api("/api/topology/client-llama/configs/delete", {
            method: "POST",
            body: JSON.stringify({ hostId, filename: btn.dataset.remoteBackupDelete }),
          });
          await fetchAndRenderRemoteBackups(hostId);
        } catch (e) { toast(String(e)); }
      });
    });
  } catch (err) {
    // Even on a list error, keep the Save button usable.
    listEl.innerHTML = saveCurrentHtml;
    if (infoEl) infoEl.textContent = `Error: ${err.message}`;
  }
  const saveBtn = listEl.querySelector("[data-snapshot-remote]");
  if (saveBtn) saveBtn.addEventListener("click", () => snapshotRemoteConfig(hostId));
}

