// Remote cell lifecycle: reserve/start/stop, tr- edit form, remote backups.
import { appConfirm, appPrompt, appPromptChoice } from "./dialogs.js";
import { renderCommandPreview } from "./command-preview.js";
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
  syncConfigTabs,
  syncToggleLabel,
} from "./form.js";
import { t } from "./i18n.js";
import { saveRouters } from "./routers.js";
import {
  applyConfigToForm,
  setEditCurrentCommand,
  suggestedSnapshotName,
  wireCellKindToggle,
} from "./llama-edit.js";
import { refreshComputeTarget } from "./memory.js";
import { startMonitor } from "./polling.js";
import { setTopology, state, topology } from "./state.js";
import { topologyAssignmentsByAgent, topologyStatusPill } from "./topology-activity.js";
import {
  engineSizeText, hostAgeText, hostPowerTextKey, isControllerMachine, machineAt, openNodeServerDetail,
} from "./topology-nodes.js";
import { markTopologyRenderPending, refreshTopology, renderTopology, topologyInteractionActive, topologyServerPhase } from "./topology-render.js";
import { $, api, escapeHtml, toast } from "./utils.js";

export let _trCachedModels = new Set(); // relative paths of .gguf files cached on the current remote host
// The machine a scout reports, by its id: GPUs, CPU, address, liveness. Its
// own record (topology.hosts) — not the client that may share the id, which
// is the operator's and carries agents, no hardware (docs/scout-split.md).
// null when no scout reported for the id: an absence, not an empty machine.
export function topologyHost(hostId) {
  return (topology?.hosts || []).find((h) => h.id === hostId) || null;
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
  const host = topologyHost(hostId) || {};
  openLlamaRemoteEdit(hostId, (host.gpus && host.gpus[0] && host.gpus[0].name) || "", host.gpus || [], port);
}

// ── Port picker: move a parked cell to another free port ─────────────────────
// Grid of the fleet-wide port pool (cells on every host + agent/bridge proxy
// ports share the numbering). Occupied tiles are colored by owner kind and
// carry the owner in the tooltip; a click on a free tile confirms and calls
// the reassign endpoint — cables and rules follow the cell server-side.
// Ports the operator (or a scan) marked as belonging to something else on the
// box. Fetched with the picker so a reopen shows the current set.
let _portExclusions = [];

// The fleet's real port window, served in the topology payload. The fallback
// mirrors the shipped default and only matters for the first paint before
// topology arrives — every later read tracks whatever CARAVAN_CELL_* says.
function cellPortRange() {
  const r = topology?.cellPortRange || {};
  const from = Number(r.from) || 22001;
  return { from, to: Number(r.to) || (from + 998) };
}
async function _loadPortExclusions() {
  try {
    const r = await api("/api/port-exclusions");
    _portExclusions = r.exclusions || [];
  } catch { /* the picker still works; the tiles just lack the extra colour */ }
}

export function openPortPicker(hostId, port) {
  const used = new Map();   // port -> {kind, label, host, name, swappable}
  _portExclusions.forEach((x) => used.set(Number(x.port), {
    kind: "excluded", label: x.note || x.host || "", note: x.note || "", excluded: true }));
  const SWAPPABLE = new Set(["stopped", "reserved", "error"]);
  (topology?.nodes || []).forEach((n) => (n.servers || []).forEach((s) => {
    const p = Number(s.port || 0);
    if (!p) return;
    const host = s.clientId || n.id;
    const what = (s.model || (s.config || {}).COMMAND || "cell").toString().slice(0, 48);
    const phase = s.phase || (s.status && s.status.phase) || "";
    used.set(p, { kind: "cell", label: `${host} · ${what}`, host, name: what,
                  swappable: SWAPPABLE.has(phase) });
  }));
  (topology?.proxies || []).forEach((pr) => {
    const p = Number(pr.port || 0);
    if (!p) return;
    used.set(p, { kind: pr.kind === "service" ? "bridge" : "proxy", label: pr.label || "" });
  });
  const cur = Number(port);
  // The grid covers the fleet's configured range (the firewall-friendly window)
  // and stretches further if something already sits above it. Anything OCCUPIED
  // below the base — legacy proxies, bridges, exclusions, a not-yet-migrated
  // cell — is shown as a compact strip above a divider: those numbers must stay
  // visible (and swappable/releasable), but the thousands of FREE ports between
  // them and the base are not on offer any more, so they are not drawn. A first
  // version drew the full run from 8022 to the base — a wall of dead tiles.
  const range = cellPortRange();
  const usedPorts = [...used.keys()].filter(Number.isFinite);
  const maxUsed = Math.max(range.from, ...usedPorts);
  const upper = Math.max(range.to, maxUsed + 10);
  const legacyPorts = usedPorts.filter((p) => p < range.from).sort((a, b) => a - b);
  if (cur < range.from && !legacyPorts.includes(cur)) legacyPorts.push(cur);
  const curName = used.get(cur)?.name || "";
  let tiles = "";
  const drawTile = (p) => {
    const u = used.get(p);
    const isCur = p === cur;
    let cls, attr, title;
    if (isCur) {
      cls = "current"; attr = " disabled"; title = t("portPickerLegendCurrent");
    } else if (!u) {
      cls = "free"; attr = ` data-pick-port="${p}"`; title = t("portPickerLegendFree");
    } else if (u.excluded) {
      // Clickable: an exclusion you cannot undo from the same place you made it
      // is a trap. Clicking releases the number back into the pool.
      cls = "busy excluded"; attr = ` data-release-port="${p}"`;
      title = t("portPickerReleaseTitle", { p: String(p), why: u.note || "—" });
    } else if (u.kind === "cell" && u.swappable) {
      // A stopped cell → offer a port swap (both cells trade ports + wiring).
      cls = "busy cell swappable"; attr = ` data-swap-port="${p}"`;
      title = t("portPickerSwapTitle", { p: String(p), name: u.name });
    } else {
      cls = `busy ${u.kind}`; attr = " disabled"; title = `${u.kind} · ${u.label}`;
    }
    tiles += `<button type="button" class="port-tile ${cls}"${attr} title="${escapeHtml(title)}">${p}</button>`;
  };
  legacyPorts.forEach(drawTile);
  if (legacyPorts.length) tiles += `<span class="port-grid-divider" aria-hidden="true"></span>`;
  for (let p = range.from; p <= upper; p++) drawTile(p);
  const legend = [["free", t("portPickerLegendFree")], ["busy cell", t("portPickerLegendCell")],
                  ["busy proxy", t("portPickerLegendProxy")], ["busy bridge", t("portPickerLegendBridge")],
                  ["busy excluded", t("portPickerLegendExcluded")],
                  ["current", t("portPickerLegendCurrent")]]
    .map(([cls, lbl]) => `<span class="port-picker-key"><span class="port-tile mini ${cls}"></span>${escapeHtml(lbl)}</span>`).join("");
  const ovl = document.createElement("div");
  ovl.className = "topology-policy-overlay port-picker-overlay";
  ovl.innerHTML = `
    <div class="topology-policy-modal port-picker-modal" role="dialog" aria-modal="true" aria-label="${escapeHtml(t("portPickerTitle", { port: String(cur) }))}">
      <div class="topology-card-head">
        <strong>${escapeHtml(t("portPickerTitle", { port: String(cur) }))}</strong>
        <button class="icon-action compact" type="button" data-pp-close aria-label="${escapeHtml(t("a11yClosePortPicker"))}">×</button>
      </div>
      <div class="port-picker-legend">${legend}</div>
      <div class="port-picker-hint">${escapeHtml(t("portPickerSwapHint"))}
        <button type="button" class="port-scan-btn" data-port-scan>🔍 ${escapeHtml(t("portScanBtn"))}</button>
      </div>
      <div class="port-scan-result" hidden></div>
      <div class="port-picker-grid">${tiles}</div>
    </div>`;
  const close = () => ovl.remove();
  ovl.addEventListener("click", async (e) => {
    if (e.target === ovl || e.target.closest("[data-pp-close]")) { close(); return; }
    // ── Scan: ask every host what it is listening on, offer to hold those ──
    if (e.target.closest("[data-port-scan]")) {
      const box = ovl.querySelector(".port-scan-result");
      const btn = ovl.querySelector("[data-port-scan]");
      box.hidden = false;
      box.innerHTML = `<div class="muted">${escapeHtml(t("portScanRunning"))}</div>`;
      btn.disabled = true;
      try {
        const r = await api("/api/port-exclusions?scan=1");
        const hosts = (r.scan || {}).hosts || [];
        // A host we could not reach is NOT a clean host — say which is which.
        const dead = hosts.filter((h) => !h.ok);
        const rows = hosts.filter((h) => h.ok && (h.ports || []).length);
        const total = rows.reduce((n, h) => n + h.ports.length, 0);
        const list = rows.map((h) => `<div class="port-scan-host"><strong>${escapeHtml(h.hostId)}</strong> `
          + h.ports.map((p) => `<span class="port-scan-port" title="${escapeHtml(p.proc || "?")}${p.pid ? ` · pid ${p.pid}` : ""}">${p.port}<span class="muted"> ${escapeHtml((p.proc || "?").slice(0, 14))}</span></span>`).join("")
          + `</div>`).join("");
        const deadLine = dead.length
          ? `<div class="port-scan-dead">⚠ ${escapeHtml(t("portScanUnreachable", { hosts: dead.map((h) => h.hostId).join(", ") }))}</div>` : "";
        box.innerHTML = total
          ? `<div class="port-scan-head">${escapeHtml(t("portScanFound", { n: total }))}</div>${list}${deadLine}`
            + `<button type="button" class="port-scan-apply" data-port-exclude-all>${escapeHtml(t("portScanExcludeAll"))}</button>`
          : `<div class="muted">${escapeHtml(t("portScanClean"))}</div>${deadLine}`;
        box._found = rows;
      } catch (err) {
        box.innerHTML = `<div class="port-scan-dead">⚠ ${escapeHtml(String(err.message || err))}</div>`;
      }
      btn.disabled = false;
      return;
    }
    if (e.target.closest("[data-port-exclude-all]")) {
      const box = ovl.querySelector(".port-scan-result");
      const add = (box._found || []).flatMap((h) => h.ports.map((p) => ({
        port: p.port, host: h.hostId, auto: true,
        note: `${p.proc || "?"}${p.pid ? ` (pid ${p.pid})` : ""} · ${h.hostId}` })));
      if (!add.length) return;
      if (!(await appConfirm(t("portScanExcludeConfirm", { n: add.length }), { danger: false }))) return;
      try {
        await api("/api/port-exclusions", { method: "POST", body: JSON.stringify({ add }) });
        toast(t("portScanExcluded", { n: add.length }));
        close();
        await _loadPortExclusions();
        openPortPicker(hostId, port);        // repaint with the new colours
      } catch (err) { toast(err.message); }
      return;
    }
    const releaseTile = e.target.closest("[data-release-port]");
    if (releaseTile) {
      const p = Number(releaseTile.dataset.releasePort);
      if (!(await appConfirm(t("portPickerReleaseConfirm", { p: String(p) }), { danger: false }))) return;
      try {
        await api("/api/port-exclusions", { method: "POST", body: JSON.stringify({ remove: [p] }) });
        close();
        await _loadPortExclusions();
        openPortPicker(hostId, port);
      } catch (err) { toast(err.message); }
      return;
    }
    const freeTile = e.target.closest("[data-pick-port]");
    const swapTile = e.target.closest("[data-swap-port]");
    const tile = freeTile || swapTile;
    if (!tile) return;
    // Free tile → reassign to a free port; stopped-cell tile → swap the two cells.
    const swap = !!swapTile;
    const target = Number(tile.dataset.pickPort || tile.dataset.swapPort);
    const prompt = swap
      ? t("portPickerSwapConfirm", { a: String(cur), an: curName || String(cur),
                                     b: String(target), bn: used.get(target)?.name || String(target) })
      : t("portPickerConfirm", { from: String(cur), to: String(target) });
    if (!(await appConfirm(prompt, { danger: false }))) return;
    tile.disabled = true;
    try {
      const res = await api(swap ? "/api/topology/server-cell/swap-port"
                                 : "/api/topology/server-cell/reassign-port", {
        method: "POST",
        body: JSON.stringify(swap ? { hostId, port: cur, targetPort: target }
                                  : { hostId, port: cur, newPort: target }),
      });
      if (res.topology) setTopology(res.topology);
      renderTopology();
      toast(swap ? t("portPickerSwapDone", { a: String(cur), b: String(target) })
                 : t("portPickerDone", { port: String(target) }));
      close();
    } catch (err) {
      toast(err.message);
      tile.disabled = false;
    }
  });
  document.body.appendChild(ovl);
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
  let port = cellPortRange().from;
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

// The operator's context limit for one role of one agent. Both fields travel
// together because on the server they are one state: a missing field means
// "clear", not "leave as is" — so the switch is re-sent with the number here,
// and the number with the switch in setRouteContextPrefer.
export async function editRouteContext(hostId, agentId, role, current, prefer) {
  const answer = await appPrompt(t("dlgRouteContext"), {
    value: current || "",
    confirmLabel: t("topologySave"),
  });
  if (answer === null) return;
  const text = String(answer).trim();
  // A typo is not "clear". The server accepts anything and reads any value it
  // cannot parse as absence, so "8k" or "81 92" SILENTLY dropped the limit
  // while the board reported success: the operator asked for a window and got
  // its removal without hearing of it. Ask to say it plainly — and send nothing.
  const clearing = text === "";
  if (!clearing && !/^[1-9]\d*$/.test(text)) {
    toast(t("routeContextNotANumber"));
    return;
  }
  await saveRouteContext({
    hostId, agentId, role,
    ...(clearing ? {} : { contextLength: text }),
    ...(prefer ? { contextAuto: true } : {}),
  });
}

// The "model if larger" switch of one role. The limit stays what it is: it is
// re-sent because a missing field would clear it (see editRouteContext).
export async function setRouteContextPrefer(hostId, agentId, role, current, prefer) {
  const value = String(current || "").trim();
  await saveRouteContext({
    hostId, agentId, role,
    ...(value ? { contextLength: value } : {}),
    ...(prefer ? { contextAuto: true } : {}),
  });
}

async function saveRouteContext(body) {
  try {
    await api("/api/topology/agent-route/context", { method: "POST", body });
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

// Rename an agent's block. Via an alias, not by editing the record: the
// scout's report replaces the agent list wholesale, and an edit inside the
// record would only last until the next poll and vanish silently.
export async function renameTopologyAgent(clientId, agentId, current) {
  const answer = await appPrompt(t("dlgRenameAgent"), {
    value: current || "",
    confirmLabel: t("topologySave"),
  });
  if (answer === null) return;
  try {
    await api("/api/topology/client/agent-alias", {
      method: "POST",
      body: { hostId: clientId, agentId, name: String(answer).trim() },
    });
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

// A route's wait budget. Edited HERE, on the client's card: the field used
// to live only on the kanban, while the card showed a different number —
// from the agent's config — and a client created by hand has no config, so
// the row didn't exist at all.
export async function editRouteWait(proxyId, current) {
  const answer = await appPrompt(t("dlgRouteWait"), {
    value: current || "",
    confirmLabel: t("topologySave"),
  });
  if (answer === null) return;
  const text = String(answer).trim();
  if (text !== "" && !/^\d+$/.test(text)) { toast(t("routeWaitNotANumber")); return; }
  const val = text === "" ? 0 : Math.max(0, Math.min(86400, parseInt(text, 10)));
  try {
    await saveRouters((routers) => {
      for (const r of routers) {
        r.graph = r.graph || { nodes: [], edges: [] };
        r.graph.inputs = r.graph.inputs || {};
        // Empty means CLEAR its own budget: then whatever's synced from the
        // client's config takes over again. Zero doesn't mean "wait for
        // nothing" here.
        if (val > 0) r.graph.inputs[proxyId] = { ...(r.graph.inputs[proxyId] || {}), clientTimeoutSeconds: val };
        else if (r.graph.inputs[proxyId]) delete r.graph.inputs[proxyId];
      }
    });
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

// The model name a port advertises itself under. Empty clears it: then
// whatever the upstream calls itself is published. A separate dialog, not
// bundled with the window: these are different decisions, and one form
// would mean editing one erases the other.
export async function editRouteModel(hostId, agentId, role, current, auto) {
  const answer = await appPrompt(t("dlgRouteModel"), {
    value: current || "",
    confirmLabel: t("topologySave"),
  });
  if (answer === null) return;
  await saveRouteModel({ hostId, agentId, role, modelName: String(answer).trim(), auto });
}

// Open/close the lock on the name. The name travels together with the
// lock's state: the server accepts both fields at once (a missing one =
// "clear"), and the lock must leave the name sitting there — otherwise
// closing it again would need the name retyped.
export async function setRouteModelLock(hostId, agentId, role, current, auto) {
  await saveRouteModel({ hostId, agentId, role, modelName: String(current || "").trim(), auto });
}

async function saveRouteModel({ hostId, agentId, role, modelName, auto }) {
  try {
    await api("/api/topology/agent-route/model", {
      method: "POST",
      body: { hostId, agentId, role, modelName, ...(auto ? { modelNameAuto: true } : {}) },
    });
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

// Create a client by hand. It's under no obligation to answer: the record
// means "exists and is configured", not "is reachable". It appears on the
// board right away as silent, with an unknown age, and that's the truth, not
// an unfinished state.
export async function addTopologyClient() {
  const name = await appPrompt(t("dlgAddClient"), { confirmLabel: t("topologyClientAdd") });
  const hostId = String(name || "").trim();
  if (!hostId) return;
  try {
    await api("/api/topology/client/create", { method: "POST", body: { hostId } });
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

// Let go of a machine: when its scout answers, it forgets this controller and
// stops reporting; either way the machine's record goes. The dialog says which
// of the two will happen — a silent scout can only be forgotten here, and
// comes back with its next report if it returns still paired. The cells
// running there keep running: stopping them is a decision of its own.
export async function disconnectScout(hostId) {
  const host = topologyHost(hostId);
  const name = host?.name || hostId;
  const silent = !!host && host.state !== "online";
  const question = silent
    ? t("dlgForgetSilentScout", { name, ago: hostAgeText(host) })
    : t("dlgDisconnectScout", { name });
  if (!(await appConfirm(question, { confirmLabel: t("nodeDisconnectScout") }))) return;
  try {
    const res = await api("/api/topology/scout/disconnect", { method: "POST", body: JSON.stringify({ hostId }) });
    toast(res?.unpaired ? t("scoutDisconnected", { name }) : t("scoutForgottenSilent", { name }));
    refreshTopology().catch(() => {});
  } catch (e) { toast(String(e)); }
}

// The ports an agent's saved routes go through. Its delete leaves them free,
// and the dialog names them, so the operator knows what stays behind.
export function savedAgentPorts(clientId, agentId) {
  const rows = topology?.assignments?.[clientId]?.assignments || [];
  const routes = topologyAssignmentsByAgent(rows).get(agentId) || new Map();
  const ports = [...routes.values()].map((r) => String(r?.proxyId || "").split(":").pop()).filter(Boolean);
  return [...new Set(ports)];
}

export async function deleteTopologyClientAgent(clientId, agentId) {
  const client = (topology?.clients || []).find((c) => c.id === clientId);
  const agent = (client?.agents || []).find((a) => a.id === agentId);
  const name = agent?.name || agentId;
  const ports = savedAgentPorts(clientId, agentId);
  const question = ports.length
    ? t("dlgDeleteAgentPorts", { name, ports: ports.map((p) => ":" + p).join(" ") })
    : t("dlgDeleteAgent", { name });
  if (!(await appConfirm(question, { confirmLabel: t("deleteAction") }))) return;
  try {
    const res = await api("/api/topology/client/agent/delete", {
      method: "POST",
      body: JSON.stringify({ clientId, agentId }),
    });
    const freed = (res && res.freedPorts) || [];
    toast(freed.length ? t("agentRemovedPorts", { id: name, ports: freed.map((p) => ":" + p).join(" ") })
                       : t("agentRemoved", { id: name }));
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

// ── VRAM share on hover ─────────────────────────────────────────────────────
// Hovering a running cell lights up its own slice of the node's VRAM bar, so
// "how much of the card is this model?" is answerable without reading numbers.
function _vramClaims(card) {
  return String(card?.dataset?.cellVram || "").split(",").filter(Boolean)
    .map((pair) => { const [i, mib] = pair.split(":"); return { i, mib: Number(mib) || 0 }; });
}

function _clearVramSlices() {
  document.querySelectorAll(".node-vram-slice:not([hidden])").forEach((el) => { el.hidden = true; });
}

function _showVramSlice(card) {
  _clearVramSlices();
  const nodeId = card.dataset.cellNode || "";
  const port = Number(card.dataset.llamaPort || 0);
  if (!nodeId) return;
  // Cells sharing this node — used to stack bands left-to-right by port so the
  // hovered one sits where its memory actually is, not always at zero.
  const peers = [...document.querySelectorAll("[data-cell-vram][data-cell-node]")]
    .filter((p) => p.dataset.cellNode === nodeId);
  _vramClaims(card).forEach(({ i, mib }) => {
    const bar = document.querySelector(`[data-gpu-row="${CSS.escape(`${nodeId}:${i}`)}"] .node-vram-bar`);
    const slice = bar?.querySelector(".node-vram-slice");
    const total = Number(bar?.dataset.vramTotal || 0);
    if (!slice || !(total > 0) || !(mib > 0)) return;
    const before = peers
      .filter((p) => Number(p.dataset.llamaPort || 0) < port)
      .reduce((a, p) => a + (_vramClaims(p).find((c) => c.i === i)?.mib || 0), 0);
    slice.style.left = `${Math.min(100, (before / total) * 100)}%`;
    slice.style.width = `${Math.min(100, (mib / total) * 100)}%`;
    slice.hidden = false;
  });
}

// Delegated on document and bound once: the board rebuilds itself on every
// structure change, so listeners living on the cards themselves come unstuck.
function bindVramHoverOnce() {
  if (document.body.dataset.vramHoverBound) return;
  document.body.dataset.vramHoverBound = "1";
  document.addEventListener("mouseover", (e) => {
    const card = e.target?.closest?.("[data-cell-vram]");
    if (card) _showVramSlice(card);
  });
  document.addEventListener("mouseout", (e) => {
    const card = e.target?.closest?.("[data-cell-vram]");
    if (card && !card.contains(e.relatedTarget)) _clearVramSlices();
  });
}

// Bind data-node-start / data-node-slot-del within a root element (scoped to
// the root just rendered, so a repaint does not bind a button twice).
export function bindServerSlotControls(root) {
  if (!root) return;
  bindVramHoverOnce();
  root.querySelectorAll("[data-node-start]").forEach((b) =>
    b.addEventListener("click", () => openRemoteFormForHost(b.dataset.nodeStart, b.dataset.nodeStartPort || "")));
  root.querySelectorAll("[data-node-cell-start]").forEach((b) =>
    b.addEventListener("click", () => {
      openRemoteFormForHost(b.dataset.nodeCellStart, b.dataset.nodeCellPort || "");
    }));
  // Launch a configured cell directly (no modal — model already set)
  root.querySelectorAll("[data-node-cell-launch]").forEach((b) =>
    b.addEventListener("click", async () => {
      const port = b.dataset.nodeCellPort;
      const model = b.closest("article")?.querySelector(".node-model-name")?.textContent?.trim();
      // For a command-path cell that .node-model-name row is the command line,
      // so the model wording announced "bash ~/run_tts.sh $PORT cosyvoice" as a
      // model and promised it would load into memory — neither is true. (A
      // model in a library was asked "disk or library?" here, for the
      // controller's own cells; a scout reads it where it is, and the answer
      // was ignored once those cells moved to it — step 6.9.)
      const msg = (b.dataset.nodeCellRunner || "llama-server") !== "llama-server"
        ? t("dlgStartCommand", { port })
        : (model ? t("dlgStartModel", { model, port }) : t("dlgStartPort", { port }));
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
  // ⇄ RESERVED step → the free-port picker (parked cells only; the render
  // sets the attr under the same conditions as delete).
  root.querySelectorAll("[data-cell-port-reassign]").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const [hostId, p] = String(b.dataset.cellPortReassign).split(":");
      // Load the held-out ports before painting, so they never flash as free.
      _loadPortExclusions().then(() => openPortPicker(hostId, Number(p)));
    }));
  root.querySelectorAll("[data-node-reserve]").forEach((b) =>
    b.addEventListener("click", () => reserveServerCell(b.dataset.nodeReserve, b.dataset.nodeReservePort || "")));
  // Add server — a new cell on the machine's scout.
  root.querySelectorAll("[data-node-add]").forEach((b) =>
    b.addEventListener("click", () => {
      reserveServerCell(b.dataset.nodeAdd, b.dataset.nodeReservePort || "");
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
  if (!p) return "";
  if ((node.servers || []).some((s) => topologyServerPhase(s) !== "stopped")) {
    clearPendingRemoteStart(node.id);  // real card now drives the state
    return "";
  }
  // A record that ended badly KEEPS its card. This used to return "" for any
  // phase but "starting", so the moment the watch wrote "timeout" the card
  // vanished — and it is the only place the ✕ lives, so the record could no
  // longer be dismissed. It stayed in `_pendingRemoteStarts`, whose `.has()`
  // goes on forcing every stopped cell of that host to read "starting": a start
  // that failed, drawn as work still in progress, with nothing left to press.
  // The two strings below were translated into all twenty languages when this
  // card was designed and had never once been reached.
  const failed = p.phase === "timeout" || p.phase === "error";
  const host = node.name || node.id;
  const note = failed
    ? t(p.phase === "timeout" ? "topologyRemoteStartTimeout" : "topologyRemoteStartFailed", { host })
    : t("topologyRemoteStarting") + "…";
  return `
    <article class="node-server ${failed ? "error" : "loading"}" data-pending-remote-start="${escapeHtml(String(node.id))}">
      <div class="node-server-head">
        ${failed ? "" : `<span class="topology-spinner" aria-hidden="true"></span>`}
        <span class="topology-addr-link" style="pointer-events:none">${escapeHtml(p.clientIp || node.ip || "")}${p.port ? ":" + escapeHtml(String(p.port)) : ""}</span>
        ${topologyStatusPill(failed ? "error" : "loading")}
        <span style="flex:1"></span>
        <button class="mini-link" type="button" data-pending-remote-dismiss="${escapeHtml(String(node.id))}" style="color:var(--muted,#888)" title="${escapeHtml(t("topologyRemoteStartDismiss"))}">✕</button>
      </div>
      ${p.modelName ? `<div class="topology-muted" style="font-size:12px;padding:2px 0">${escapeHtml(p.modelName)}</div>` : ""}
      <div class="topology-muted" style="font-size:11px">${escapeHtml(note)}</div>
    </article>`;
}

//: Whether a host has a start still genuinely in flight — as opposed to a
//: record that ended in timeout or error and is only waiting to be dismissed.
export function remoteStartPending(hostId) {
  return (_pendingRemoteStarts.get(String(hostId)) || {}).phase === "starting";
}

export async function submitLlamaStop(hostId) {
  const name = topologyHost(hostId)?.name || hostId;
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

// The server of an engine next to a machine's cells started or stopped from
// its card (step 3г, scout 2.16+). A stop is confirmed like stopping a cell —
// its loaded models go with it; a start is not: it takes memory only when a
// model loads. The server answers with the board as it is now, the engine
// already marked as starting or stopping.
export async function serveEngine(hostId, kind, label, machine, op) {
  if (op === "stop" && !(await appConfirm(t("nodeEngineStopConfirm", { engine: label, machine }),
    { confirmLabel: t("nodeEngineStop"), scene: "stop" }))) {
    return;
  }
  try {
    const res = await api(`/api/engines/${op}`, { method: "POST", body: JSON.stringify({ hostId, kind }) });
    if (res.topology) setTopology(res.topology);
    renderTopology();
  } catch (err) {
    toast(err.message);
  }
}

// A start/stop button in an engine card's header, as its markup says it
// (engineServerHtml in topology-nodes.js).
export function serveEngineButton(btn) {
  const d = btn.dataset;
  return serveEngine(d.engineHost, d.engineKind, d.engineLabel, d.engineMachine, d.engineServe);
}

// A load/unload button on an engine model's row, as its markup says it
// (engineActHtml in topology-nodes.js): which machine, engine and model, the
// act, and whether the engine can be told how long to hold the model.
export function actOnEngineButton(btn) {
  const d = btn.dataset;
  return actOnEngineModel(d.engineHost, d.engineKind, d.engineLabel, d.engineModel, d.engineAct,
    d.engineHolds === "1", d.engineMachine || d.engineHost);
}

// What to download into each engine, as the prompt hints it.
const ENGINE_PULL_HINTS = { ollama: "nodeEnginePullHintOllama", lmstudio: "nodeEnginePullHintLmStudio" };

// A model downloaded into an engine next to a machine's cells (step 3д, scout
// 2.17+): its name asked — one word, a typo sends nothing — and the download
// runs on the machine, its progress on the engine's card.
export async function pullEngineModel(hostId, kind, label) {
  const hint = ENGINE_PULL_HINTS[kind] ? t(ENGINE_PULL_HINTS[kind]) : "";
  const answer = await appPrompt(t("nodeEnginePullPrompt", { engine: label, hint }),
    { value: "", confirmLabel: t("nodeEnginePull") });
  if (answer === null) return;
  const model = String(answer).trim();
  if (!/^[^\s\x00-\x1f\x7f]{1,300}$/.test(model)) { toast(t("nodeEngineModelNameBad")); return; }
  try {
    const res = await api("/api/engines/pull", { method: "POST", body: JSON.stringify({ hostId, kind, model }) });
    if (res.topology) setTopology(res.topology);
    renderTopology();
  } catch (err) {
    toast(err.message);
  }
}

// The download button in an engine card's header, as its markup says it.
export function pullEngineButton(btn) {
  const d = btn.dataset;
  return pullEngineModel(d.engineHost, d.engineKind, d.engineLabel);
}

// How long a model loaded from the board stays unused before its engine lets
// it go (docs/foreign-engines.md, 3б): seconds, -1 — until it is unloaded.
// Offered only where the engine can be told (its `holds`, scout 2.15+).
export const ENGINE_HOLDS = [
  { value: 900, label: () => t("nodeEngineHoldMinutes", { n: 15 }) },
  { value: 3600, label: () => t("nodeEngineHoldHours", { n: 1 }) },
  { value: 14400, label: () => t("nodeEngineHoldHours", { n: 4 }) },
  { value: -1, label: () => t("nodeEngineHoldUntilUnloaded") },
];

// Load a model of an engine next to a machine's cells, or unload it (step 3):
// the load asks for a window (empty keeps the engine's own) and, where the
// engine can be told, how long the model stays unused; the unload is
// confirmed like stopping a cell. A load that would not fit into the cards'
// free memory is not started by the scout (2.15): it is asked about, and
// loaded anyway only when the operator says so. The server answers with the
// board as it is now — the model already marked as being acted on.
export async function actOnEngineModel(hostId, kind, label, model, op, holds = false, machine = "") {
  let contextLength = null;
  let hold = null;
  if (op === "load") {
    const opts = { value: "", confirmLabel: t("nodeEngineLoad") };
    const answer = holds
      ? await appPromptChoice(t("nodeEngineLoadPrompt", { model }), {
        ...opts, choiceLabel: t("nodeEngineHoldLabel"), choice: "-1",
        choices: ENGINE_HOLDS.map((h) => ({ value: String(h.value), label: h.label() })),
      })
      : await appPrompt(t("nodeEngineLoadPrompt", { model }), opts);
    if (answer === null) return;
    const text = String(holds ? answer.value : answer).trim();
    if (text !== "") {
      // A typo is not "the engine's default": say it, and send nothing.
      if (!/^[1-9]\d*$/.test(text)) { toast(t("nodeEngineContextNotANumber")); return; }
      contextLength = Number(text);
    }
    if (holds) hold = Number(answer.choice);
  } else if (op === "delete") {
    // Its files go from the disk: the danger look, and the machine named.
    if (!(await appConfirm(t("nodeEngineDeleteConfirm", { model, engine: label, machine: machine || hostId }),
      { confirmLabel: t("nodeEngineDelete") }))) {
      return;
    }
  } else if (!(await appConfirm(t("nodeEngineUnloadConfirm", { model, engine: label }),
    { confirmLabel: t("nodeEngineUnload"), scene: "stop" }))) {
    return;
  }
  const send = (force) => api(`/api/engines/${op}`, {
    method: "POST",
    body: JSON.stringify({
      hostId, kind, model, ...(contextLength ? { contextLength } : {}),
      ...(Number.isFinite(hold) ? { hold } : {}), ...(force ? { force: true } : {}),
    }),
  });
  try {
    let res = await send(false);
    if (res.short) {
      const s = res.short;
      const need = `${s.basis === "weights" ? "≥" : "≈"} ${engineSizeText(s.needBytes)}`;
      const anyway = await appConfirm(t("nodeEngineShort", { model, need, free: engineSizeText(s.freeBytes) }),
        { confirmLabel: t("nodeEngineLoadAnyway") });
      if (!anyway) return;
      res = await send(true);
    }
    if (res.topology) setTopology(res.topology);
    renderTopology();
  } catch (err) {
    toast(err.message);
  }
}

// ── nvidia-smi source selector (drawer panel) ────────────────────────────────
export let _nvidiaSmiSource = "local"; // "local" = the controller, or a client hostId

//: Which source survives a topology change: the chosen one if it is still
//: listed, otherwise the controller. A rule rather than a line inside the
//: renderer, because the renderer returns early when only one source is left
//: and the repair used to sit past that return.
export function surviving_nvidiaSmiSource(sources, current) {
  return (sources || []).some((s) => s.id === current) ? current : "local";
}

export function renderNvidiaSmiSourceButtons() {
  const container = $("nvidiaSmiSources");
  if (!container) return;

  // Build list: the controller's own machine first (it runs nvidia-smi
  // itself), then the other machines whose scouts answer and report a GPU. The
  // controller's machine is named as the board names it, by its node
  // (machineAt) — not by the controller's old display name — and its scout is
  // not listed again: the same machine, twice, under two names.
  const sources = [
    { id: "local", label: machineAt("127.0.0.1").name },
  ];
  for (const host of (topology?.hosts || [])) {
    if (host.state !== "online") continue;
    if (!(host.gpus || []).length) continue;
    if (isControllerMachine(host.id)) continue;
    const gpu = host.gpus[0] || {};
    sources.push({
      id: host.id,
      label: host.name || host.id,
      gpu: gpu.name || "",
    });
  }

  // Repair the selection BEFORE the early return below. This used to come
  // after it, so when the selected client was the one that vanished (leaving
  // only the controller) the buttons were erased while _nvidiaSmiSource still
  // named the departed host, and polling.js went on asking
  // /api/topology/client-monitor for it — with no control left to switch back.
  _nvidiaSmiSource = surviving_nvidiaSmiSource(sources, _nvidiaSmiSource);

  // Only show buttons when there's more than one source
  if (sources.length <= 1) { container.innerHTML = ""; return; }

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

// Is the machine this cell form targets the controller's own? Then its files
// are the controller's: the models tree the controller lists and the home it
// reads scripts from. Any other scout machine has neither, so the choices only
// that tree backs are held back from it — a safetensors folder in the picker,
// the seamless runner and its language, a vLLM path derived from the picked
// folder — and a script its command names is not read. Since step 6.8 the
// controller's machine runs its cells through its scout and they are edited in
// this form; before, the controller's own form (te-) offered them, and holding
// them back here left that machine's seamless and vLLM cells uneditable.
export function formOnControllerMachine(pfx) {
  return pfx === "tr-" && isControllerMachine(_trHostId);
}

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
  // The panel only makes sense for a saved cell (the slot exists).
  panel.hidden = !cellPort;
  if (!cellPort) return;
  _schedCtx = { pfx, hostId, port: parseInt(cellPort, 10) };
  const sc = schedule || {};
  $(`${pfx}-schedEnabled`).checked = !!sc.enabled;
  $(`${pfx}-schedStart`).value = sc.start || "22:00";
  $(`${pfx}-schedStop`).value = sc.stop || "08:00";
  const daysOn = new Set((sc.days || []).map(Number));
  $(`${pfx}-schedDays`).innerHTML = SCHED_DAY_KEYS.map((k, i) =>
    `<button type="button" class="sched-day${daysOn.size === 0 || daysOn.has(i) ? " on" : ""}${daysOn.size === 0 ? " implicit" : ""}" data-day="${i}" data-i18n="${k}">${escapeHtml(t(k))}</button>`).join("");
  $(`${pfx}-schedStatus`).textContent = sc.enabled ? t("schedSaved", { start: sc.start, stop: sc.stop }) : "";
  if (!_schedWired.has(pfx)) {
    _schedWired.add(pfx);
    $(`${pfx}-schedEnabled`).addEventListener("change", _schedQueueSave);
    $(`${pfx}-schedStart`).addEventListener("change", _schedQueueSave);
    $(`${pfx}-schedStop`).addEventListener("change", _schedQueueSave);
    $(`${pfx}-schedDays`).addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-day]");
      if (!b) return;
      // The first click on the "implicitly every day" state locks in an
      // explicit choice of one day.
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

// Scheduled poweroff editor for a host. Built from JS as a one-off overlay
// rather than markup, because it lives only on the board and only opens on a
// deliberate ⏰ click — no reason to carry it in every page's HTML. Reuses the
// shared modal look; resolves when the operator saves or dismisses.
export function openHostPowerScheduleModal(hostId, sched) {
  const s = sched || {};
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay hps-overlay";
  overlay.innerHTML = `
    <div class="modal" data-tone="ask" role="dialog" aria-modal="true" aria-labelledby="hpsTitle" data-t="host-power-schedule-modal">
      <h2 id="hpsTitle">${escapeHtml(t("hostPowerSchedModalTitle", { host: hostId }))}</h2>
      <p class="hps-warn">${escapeHtml(t(hostPowerTextKey(hostId, "schedule")))}</p>
      <label class="hps-row"><input type="checkbox" id="hpsEnabled" data-t="host-power-schedule-enabled"${s.enabled ? " checked" : ""}> <span>${escapeHtml(t("hostPowerSchedEnable"))}</span></label>
      <div class="hps-row"><label for="hpsAt">${escapeHtml(t("hostPowerSchedAt"))}</label>
        <input type="time" id="hpsAt" data-t="host-power-schedule-at" value="${escapeHtml(s.at || "03:00")}"></div>
      <label class="hps-row"><input type="checkbox" id="hpsDaily" data-t="host-power-schedule-daily"${s.daily === false ? "" : " checked"}> <span>${escapeHtml(t("hostPowerSchedDailyLabel"))}</span></label>
      <p class="hps-next" id="hpsNext" data-t="host-power-schedule-next"></p>
      <div class="hps-actions">
        <button type="button" class="mini-link" id="hpsCancel" data-t="host-power-schedule-cancel">${escapeHtml(t("cancel"))}</button>
        <button type="button" class="primary" id="hpsSave" data-t="host-power-schedule-save">${escapeHtml(t("save"))}</button>
      </div>
    </div>`;
  const close = () => overlay.remove();
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape" && document.body.contains(overlay)) { close(); document.removeEventListener("keydown", esc); }
  });
  overlay.querySelector("#hpsCancel").addEventListener("click", close);
  overlay.querySelector("#hpsSave").addEventListener("click", async () => {
    const schedule = {
      enabled: overlay.querySelector("#hpsEnabled").checked,
      at: overlay.querySelector("#hpsAt").value || "03:00",
      daily: overlay.querySelector("#hpsDaily").checked,
    };
    try {
      const res = await api("/api/host/power-schedule", {
        method: "POST", body: JSON.stringify({ hostId, schedule }),
      });
      const sc = res?.schedule || schedule;
      toast(sc.enabled
        ? t("hostPowerSchedSaved", { host: hostId, at: sc.at, when: sc.daily ? t("hostPowerSchedDaily") : t("hostPowerSchedOnce") })
        : t("hostPowerSchedCleared", { host: hostId }));
      close();
      refreshTopology();
    } catch (err) { toast(err.message); }
  });
  const nextLine = () => {
    const el = overlay.querySelector("#hpsNext");
    if (!overlay.querySelector("#hpsEnabled").checked) { el.textContent = ""; return; }
    const at = overlay.querySelector("#hpsAt").value || "03:00";
    const [ah, am] = at.split(":").map(Number);
    const now = new Date();
    // A time still ahead today fires today; a time already past waits for the
    // next day — the very rule the operator could not see before.
    const past = ah * 60 + am <= now.getHours() * 60 + now.getMinutes();
    el.textContent = t(past ? "hostPowerSchedNextTomorrow" : "hostPowerSchedNextToday", { at });
  };
  overlay.querySelector("#hpsEnabled").addEventListener("change", nextLine);
  overlay.querySelector("#hpsAt").addEventListener("input", nextLine);
  nextLine();
  document.body.appendChild(overlay);
  overlay.querySelector("#hpsAt").focus();
}

// The slot from the current topology for (hostId, port) — schedule's source.
export function findSlotEntry(hostId, port) {
  return ((topology?.server || {}).llamaServers || [])
    .find((sv) => String(sv.port) === String(port) && (sv.clientId || "") === hostId);
}

export function openLlamaRemoteEdit(hostId, gpuName, clientGpus, cellPort = "") {
  _trHostId = hostId;
  _trClientGpus = Array.isArray(clientGpus) ? clientGpus : [];
  _trGpuName = String(gpuName || _trClientGpus[0]?.name || "");
  _trClientCpu = (topologyHost(hostId) || {}).cpu || {};
  _trCellPort = cellPort ? String(cellPort) : "";
  // Same as the controller editor: the tab bar's overflow state is only
  // measurable once this modal is actually on screen.
  setTimeout(() => syncConfigTabs("tr-"), 0);

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

  // B: clean-slate defaults — only carry the params that make sense cross-host.
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

  // 4: for an existing cell, the authoritative config is the slotConfig the
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

  // 5: fetch cached model list from remote host asynchronously
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
  const _ov = $("llamaRemoteEditOverlay");
  _ov.hidden = false;
  // Focus into the dialog — same reason as the controller editor.
  if (!_ov.hasAttribute("tabindex")) _ov.tabIndex = -1;
  _ov.focus({ preventScroll: true });

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
  // "auto"/"all" are legal values (llama.cpp fits what the card holds and
  // leaves the rest in RAM). parseInt would send NaN; the real -ngl travels
  // inside `config`, this number is bookkeeping for the heartbeat.
  const _nglRaw = String(config.N_GPU_LAYERS ?? "").trim().toLowerCase();
  const gpuLayers = /^\d+$/.test(_nglRaw) ? parseInt(_nglRaw, 10) : 999;
  const ctxSize        = parseInt(config.CTX_SIZE || "4096", 10);
  const cacheModels    = !!$("tr-cacheModels")?.checked;
  // A CELL's Apply only saves the config (the start is the card's ▶ button), so
  // it must not promise a start — it used to ask "Start the server on :N?" and
  // then just save, which reads as a failed start.
  const _isCellSave = !!_trCellPort;
  // A command-path cell starts a command, not a model server — saying "the
  // model will load into memory" (or even "server") describes something else.
  const _startMsg = _isCellSave
    ? t("dlgApplyCellConfig")
    : isCommandPath
      ? t("dlgStartCommand", { port: String(port) })
      : (!modelPath
          ? t("dlgStartPort", { port: String(port) })
          : t("dlgStartModel", { model: modelPath.split("/").pop(), port: String(port) }));
  if (!(await appConfirm(_startMsg, {
    danger: false,
    confirmLabel: _isCellSave ? "OK" : t("dlgStartLabel"),
    scene: "start",
  }))) return;
  if (isCommand) {
    if (!(config.COMMAND || "").trim()) { toast(t("enterCommand")); return; }
  } else if (runnerId === "vllm") {
    if (!(config.VLLM_MODEL || "").trim()) { toast(t("selectModel")); return; }
  } else if (!isCommandPath && !modelPath) { toast(t("selectModel")); return; }

  // Cell mode: save config without starting (same as controller "Apply")
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
      const host = topologyHost(_trHostId) || {};
      registerPendingRemoteStart({
        hostId: _trHostId,
        hostName: host.name || _trHostId,
        modelName: modelPath.split("/").pop(),
        port,
        clientIp: host.ip || "",
        gpuName: (host.gpus && host.gpus[0] && host.gpus[0].name) || "",
      });
      $("llamaRemoteEditOverlay").hidden = true;
      toast(t("topologyRemoteStartSent", { host: host.name || _trHostId }));
      renderTopology();
    } else {
      toast(result?.result?.error || result?.error || "Error starting remote server");
    }
  } catch (e) {
    const msg = String(e);
    // "startup already in progress" means we sent a duplicate — treat as success:
    // close the dialog and show a friendly notice instead of an error.
    if (msg.toLowerCase().includes("already in progress") || msg.toLowerCase().includes("already starting")) {
      const host = topologyHost(_trHostId) || {};
      if (!_pendingRemoteStarts.has(_trHostId)) {
        registerPendingRemoteStart({
          hostId: _trHostId,
          hostName: host.name || _trHostId,
          modelName: modelPath.split("/").pop(),
          port,
          clientIp: host.ip || "",
          gpuName: (host.gpus && host.gpus[0] && host.gpus[0].name) || "",
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

