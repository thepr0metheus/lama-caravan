// Router node canvas: nodes, connectors, pan/zoom, schedule grid painting.
import { appConfirm } from "./dialogs.js";
import { option } from "./form.js";
import { t } from "./i18n.js";
import { closeConfirmModal } from "./llama-edit.js";
import { action } from "./polling.js";
import {
  renderServersBlockHtml,
  routerById,
  saveRouters,
  topologyRouterOutputLabel,
} from "./routers.js";
import { state, topology, ui } from "./state.js";
import {
  _proxyUpstreamStr,
  ensureStickyBarTicker,
  proxyEffectiveWaitTimeout,
  stickySlotAnims,
  topologyDurationMs,
  topologyFormatDuration,
  topologyItemGroup,
  topologyQueueRuntime,
  topologyRuntimeOverview,
} from "./topology-activity.js";
import {
  _cvProxyIsStale,
  _cvProxyIsTombstoned,
  topologyMutedProxyIds,
  topologyProxyOwner,
} from "./topology-proxies.js";
import { renderTopology, topologyStructureFingerprint } from "./topology-render.js";
import { $, api, escapeHtml, toast } from "./utils.js";

export let _cvQueueHistOpen = {};                 // nodeId -> bool: history pane open?
export let _cvQueueHistData = {};                 // nodeId -> { rows, ts } cached log data
export let _cvSchedHistOpen = {};                 // nodeId -> bool: schedule history pane open?
export let _cvSchedHistData = {};                 // nodeId -> { rows, ts } cached log data
// Canvas schedule node (new inline 2c design)
export let _cvSchedCollapsed = new Set();         // nodeIds in collapsed state (default = expanded)
export let _cvSchedPaintIds = {};                 // nodeId → current paint outputId
export let _cvSchedPainting = false;             // pointer is held down on grid
export let _cvSchedPaintNid = null;              // nodeId being painted
export let _cvSchedPendingGrid = null;           // { nid, grid } accumulated during active paint stroke
export let _cvSchedWorkingGrids = {};            // nid → last painted grid (survives between strokes so mid-save strokes don't lose changes)
// ── Router canvas (Phase 3: interactive node graph) ───────────────────────
// Free-form node view: input clients (left) → router (centre) → outputs (right).
// Drag nodes (positions persisted in localStorage), drag background to pan, wheel to
// zoom. Active links animate. The 3-column popover stays the editor.
// One canvas block per AGENT = (host, agent-name). The agent name comes from the
// route label minus its "primary"/"fallback" suffix (kept correct by the backend
// reconcile), so BOTH the primary and fallback ports of an agent land in the same
// block; clientId disambiguates the same agent name living on different hosts.
export function _cvAgentGroup(p) {
  return String(p.label || "").replace(/\s+(primary|fallback)$/i, "").trim();
}

// Normalize port to primary of its pair (odd=primary, even=primary's fallback → port-1).
export function _cvPrimaryPort(p) {
  const port = Number(p.port || 0);
  return port > 0 ? (port % 2 === 0 ? port - 1 : port) : 0;
}

// Build proxyId → {agentId, hostId} from topology.assignments (cached per topology snapshot).
export let _cvAgentMapCache = { topo: null, map: null };
export function _cvProxyToAgent() {
  if (_cvAgentMapCache.topo === topology && _cvAgentMapCache.map) return _cvAgentMapCache.map;
  const map = new Map();
  for (const [hostId, entry] of Object.entries(topology?.assignments || {})) {
    for (const ag of (entry.assignments || [])) {
      for (const r of (ag.routes || [])) {
        if (r.proxyId) map.set(String(r.proxyId), { agentId: String(ag.agentId || ""), hostId });
      }
    }
  }
  _cvAgentMapCache = { topo: topology, map };
  return map;
}

// Group primary+fallback pair by the primary (odd) port — label-independent.
export function canvasClientKey(p) {
  const host = String(p.clientId || "");
  const primary = _cvPrimaryPort(p);
  return host || primary ? `${host}::${primary || p.id}` : String(p.id);
}

export function canvasClientName(p) {
  const info = _cvProxyToAgent().get(String(p.id));
  if (info?.agentId) {
    const short = info.agentId.replace(/^agent-/, "");
    // Qualify with host when the same agent name exists on >1 host.
    const dupHosts = [..._cvProxyToAgent().values()]
      .filter((i) => i.agentId === info.agentId && i.hostId !== info.hostId);
    return dupHosts.length ? `${short} · ${info.hostId}` : short;
  }
  // Fallback: label (stripped), or host:port when label equals host (ambiguous).
  const label = _cvAgentGroup(p);
  const host = String(p.clientId || "");
  if (label && label !== host) return label;
  const primary = _cvPrimaryPort(p);
  return host ? (primary ? `${host}:${primary}` : host) : String(p.id);
}

export let _cvDupCache = { topo: null, set: null };
export function _cvAgentDupSet() {   // kept for any remaining callers
  if (_cvDupCache.topo === topology && _cvDupCache.set) return _cvDupCache.set;
  const byAgent = new Map();
  for (const p of (topology?.proxies || [])) {
    const a = _cvAgentGroup(p);
    if (!a) continue;
    if (!byAgent.has(a)) byAgent.set(a, new Set());
    byAgent.get(a).add(String(p.clientId || ""));
  }
  const set = new Set([...byAgent].filter(([, hosts]) => hosts.size > 1).map(([a]) => a));
  _cvDupCache = { topo: topology, set };
  return set;
}

export let _cvView = { tx: 24, ty: 24, scale: 1 };

// Rebinding an imported let throws — foreign modules (main, topology-dnd)
// reset the viewport through this setter instead.
export function cvSetViewport(pos, view) {
  _cvPos = pos;
  _cvView = view;
}   // world transform
export let _cvPos = {};                               // nodeId -> {x,y} for the open router
export let _cvDrag = null;                            // active node/pan drag
export const CV_NODE_W = 200, CV_ROW_H = 70;

export function canvasPosKey(routerId) { return `cvpos:${routerId}`; }
export function canvasLoadPositions(routerId) {
  try { return JSON.parse(localStorage.getItem(canvasPosKey(routerId)) || "{}") || {}; } catch { return {}; }
}
export function canvasSavePositions(routerId) {
  try { localStorage.setItem(canvasPosKey(routerId), JSON.stringify(_cvPos)); } catch {}
}

// Live queue state for a queue node: resolve its admit edge → guarded llama output,
// then count running/queued requests on that upstream group (matches the backend's
// route_group_key). Returns null for cloud/unwired admit (no slot queue there).
export function queueNodeLiveStats(router, node) {
  const cfg = node.config || {};
  const edges = (router.graph?.edges || []).filter((e) => e.from === `rule:${node.id}`);
  const admit = edges.find((e) => e.id === cfg.admitEdge) || edges[0];
  if (!admit || !String(admit.to).startsWith("out:")) return null;
  const out = (router.outputs || []).find((o) => o.id === String(admit.to).slice(4));
  if (!out || String(out.upstreamType || "") === "cloud") return null;
  const group = `${out.upstreamHost || "127.0.0.1"}:${out.upstreamPort || 8080}`;
  const overview = topologyRuntimeOverview();
  const running = overview.running.filter((it) => topologyItemGroup(it) === group).length;
  const qItems = overview.queued.filter((it) => topologyItemGroup(it) === group);
  const slotTotals = ui.latestSystemMonitor?.latest?.agentProxies?.slotTotals || {};
  const slots = Number(cfg.maxSlots) || Number(slotTotals[group] || 0) || 0;
  // Longest waiter's progress as a % of the FULL client wait-timeout (the gauge span).
  // queue.timeoutSec = the abort point = abortPct% of wait-timeout, so scale back up.
  const abortPct = Math.max(1, Number(cfg.abortPct ?? 85));
  let waitPct = 0;
  for (const it of qItems) {
    const ms = Number(it.queue?.queuedMs || 0);
    const abortSec = Number(it.queue?.timeoutSec || 0);
    const fullWait = abortSec > 0 ? abortSec / (abortPct / 100) : 0;
    if (fullWait > 0) waitPct = Math.max(waitPct, Math.min(100, (ms / 1000 / fullWait) * 100));
  }
  return { group, running, queued: qItems.length, slots, waitPct };
}

// Human name for a runtime item in the queue. The raw route label is often just
// "OpenClaw" for every host, which makes queue rows ambiguous — you can't tell
// one host's OpenClaw from another's. Resolve the item → proxy → owner
// and reuse the proxy-panel title (host name for the host OpenClaw agent, agent name
// otherwise) so each row is distinguishable. Fall back to the bare label.
export function _qClientName(it) {
  // Port is the source of truth; show "alias :port" or ":port"
  if (it.port) return _portDisplayName(it.port);
  // Fallback: strip role suffix from label
  const label = String(it.label || it.route || "");
  return label.replace(/\s+(primary|fallback)$/i, "").trim() || `:${it.port || "?"}`;
}

// Rich, self-explanatory queue node card: live "now processing" (client → upstream),
// the waiting queue with per-request expiring bars (spill + abort markers), a slot
// meter, and admit/spill destination rows each carrying their OWN output port (drag a
// cable from it). Unwired ports pulse so you know they must be connected.
// ── Queue history helpers ────────────────────────────────────────────────────
export function _cvQHistFmt(ms) {
  if (ms == null || ms < 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60000), s = Math.round((ms % 60000) / 1000);
  return `${m}m${s > 0 ? ` ${s}s` : ""}`;
}
export function _cvQHistModel(item) {
  // Overflow to cloud — return amber indicator + cloud model name
  if (item.queue?.cloudFallback || item.upstreamType === "cloud") {
    const m = String(item.model || "cloud");
    return { text: m, overflow: true };  // CSS text-overflow handles display
  }
  // Local model — shorten gguf name: "Qwen_Qwen3.6-27B-Q5_K_L.gguf" → "Qwen3.6-27B"
  const m = item.stream?.model || item.model || "";
  if (!m) return { text: "?", overflow: false };
  const base = m.replace(/.*\//, "").replace(/\.gguf$/i, "");
  const parts = base.split(/[-_]/);
  // Find size token like "27B", "3.6", combine with preceding family name
  let short = base;
  for (let i = 0; i < parts.length; i++) {
    if (/^\d+(\.\d+)?[BbMm]?$/.test(parts[i]) && parts[i].length > 1) {
      const family = parts.slice(0, i).filter(Boolean).pop() || parts[0];
      short = `${family}-${parts[i]}`;
      break;
    }
  }
  // No JS length limit — CSS text-overflow:ellipsis handles display, title shows full name
  return { text: short, overflow: false };
}
// Port-based display name for a proxy port.
// opts.short → use last-2 port digits as tag (:01); default → full port (:8101)
// opts.nameOnly → return just the alias without port tag
// Returns "host:01" (named+short), "host :8101" (named), ":8101" (unnamed)
export function _portDisplayName(port, opts = {}) {
  const p = Number(port);
  if (!p) return opts.short ? ":??" : ":????"  ;
  const proxy = (topology?.proxies || []).find((q) => Number(q.port) === p);
  const owner = proxy ? topologyProxyOwner(proxy.id) : null;
  // title = agent name or host name for openclaw agents
  const name = owner?.title && owner.title !== String(proxy?.id) ? owner.title : "";
  const portTag = opts.short ? `:${String(p).slice(-2)}` : ` :${p}`;
  if (name) return opts.nameOnly ? name : `${name}${portTag}`;
  return opts.short ? `:${String(p).slice(-2)}` : `:${p}`;
}

export function _cvQHistRoute(raw) {
  const item = raw.item || {};
  if (item.port) return _portDisplayName(item.port, { short: true });
  // Fallback when port missing: strip suffix from route label
  const r = String(raw.route || item.route || "");
  let name = r.replace(/ (?:primary|fallback)$/i, "").trim();
  if (name.includes("·")) name = name.split("·").pop().trim();
  return name.slice(0, 8) || ":?";
}

export function _fetchQueueHist(nodeId) {
  fetch("/api/agent-proxy-logs?event=finished&limit=40")
    .then((r) => r.json())
    .then((data) => {
      _cvQueueHistData[nodeId] = { rows: data.rows || [], ts: Date.now() };
      renderTopology();
    })
    .catch(() => {
      _cvQueueHistData[nodeId] = { rows: [], ts: Date.now(), err: true };
      renderTopology();
    });
}

export function _fetchSchedHist(nodeId) {
  fetch("/api/agent-proxy-logs?event=finished&limit=40")
    .then((r) => r.json())
    .then((data) => {
      _cvSchedHistData[nodeId] = { rows: data.rows || [], ts: Date.now() };
      renderTopology();
    })
    .catch(() => {
      _cvSchedHistData[nodeId] = { rows: [], ts: Date.now(), err: true };
      renderTopology();
    });
}

// Walk edges backwards from schedNodeId to find all proxy port numbers that reach it.
export function _cvSchedInputPorts(router, schedNodeId) {
  const edges = (router?.graph?.edges || []);
  const target = `rule:${schedNodeId}`;
  const reachable = new Set([target]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const e of edges) {
      const t = String(e.to || ""), f = String(e.from || "");
      if (reachable.has(t) && !reachable.has(f)) { reachable.add(f); changed = true; }
    }
  }
  const ports = new Set();
  for (const ref of reachable) {
    const m = ref.match(/:(\d+)$/);
    if (m && ref.startsWith("in:")) ports.add(Number(m[1]));
  }
  return ports;
}

// Render schedule history: only requests from ports wired into this schedule node.
export function _renderSchedHistHtml(nodeId, outputs, grid, inputPorts) {
  const cache = _cvSchedHistData[nodeId];
  if (!cache) return `<div class="cv-q-hist-loading">loading…</div>`;
  if (cache.err) return `<div class="cv-q-hist-loading">failed to load</div>`;

  if (inputPorts && inputPorts.size === 0) {
    return `<div class="cv-q-hist-loading">no inputs connected to this node</div>`;
  }

  // Filter to only rows from ports wired into this schedule node
  const filtered = (cache.rows || []).filter((raw) => {
    const port = raw.item?.port;
    return !inputPorts || !port || inputPorts.has(Number(port));
  }).slice(0, 20);

  if (!filtered.length) return `<div class="cv-q-hist-loading">no history yet</div>`;

  const rows = filtered.map((raw) => {
    const item = raw.item || {};
    const ok = !item.errorKind && (item.status || 200) < 500;
    const ts = item.startedAt ? new Date(item.startedAt * 1000) : null;
    const d = ts ? (ts.getDay() + 6) % 7 : -1;   // Mon=0
    const h = ts ? ts.getHours() : -1;
    const savedOutId = item.routedOutputId;
    const savedOutName = item.routedOutputName;
    let outName, outColor;
    if (savedOutId) {
      const savedOut = outputs.find((o) => o.id === savedOutId);
      outName = savedOutName || (savedOut ? savedOut.name : "default");
      outColor = savedOut ? _cvSchedColor(outputs, savedOut.id) : "";
    } else {
      const activeOutId = (d >= 0 && grid[d]?.[h]) || null;
      const activeOut = activeOutId ? outputs.find((o) => o.id === activeOutId) : null;
      outName = activeOut ? activeOut.name : "default";
      outColor = activeOut ? _cvSchedColor(outputs, activeOut.id) : "";
    }
    const dayLabel = d >= 0 ? CV_SCHED_DAY_LABELS[d] : "?";
    const timeStr = ts ? ts.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
    const route = escapeHtml(_cvQHistRoute(raw));
    const model = _cvQHistModel(item);
    const statusCls = ok ? "cv-q-hist-ok" : "cv-q-hist-err";
    const dotStyle = outColor ? `background:${outColor}` : "background:var(--muted)";
    return `<div class="cv-sched-hist-row" title="${dayLabel} ${h >= 0 ? h + ":00" : "?"} → ${escapeHtml(outName)}${item.errorKind ? " · " + item.errorKind.replace(/_/g, " ") : ""}">
      <span class="cv-q-hist-route">${route}</span>
      <span class="cv-q-hist-time">${timeStr}</span>
      <span class="cv-sched-hist-out"><i class="cv-sched-dot" style="${dotStyle}"></i>${escapeHtml(outName)}</span>
      <span class="cv-sched-hist-when">${dayLabel} ${h >= 0 ? h + "h" : "?"}</span>
      <span class="cv-q-hist-model${model.overflow ? " overflow" : ""}" title="${escapeHtml(model.text)}">${model.overflow ? "↗ " : ""}${escapeHtml(model.text)}</span>
      <span class="${statusCls}">${ok ? "✓" : "✗"}</span>
    </div>`;
  }).join("");

  const age = Math.round((Date.now() - cache.ts) / 1000);
  return rows + `<div class="cv-q-hist-age">${age}s ago · <button class="cv-q-hist-refresh" type="button" data-cv-sched-hist-refresh="${escapeHtml(nodeId)}">↻ refresh</button></div>`;
}

export function _renderQueueHistHtml(nodeId) {
  const cache = _cvQueueHistData[nodeId];
  if (!cache) return `<div class="cv-q-hist-loading">loading…</div>`;
  if (cache.err) return `<div class="cv-q-hist-loading">failed to load</div>`;
  if (!cache.rows.length) return `<div class="cv-q-hist-loading">no history yet</div>`;

  const batch = cache.rows.slice(0, 25);
  // Pre-compute max processing time for relative bar scaling
  const procMsList = batch.map((raw) => {
    const item = raw.item || {};
    return Math.max(0, (item.durationMs || 0) - (item.queue?.queuedMs || 0));
  });
  const maxProc = Math.max(1, ...procMsList);

  const rows = batch.map((raw, idx) => {
    const item = raw.item || {};
    const ok = !item.errorKind && (item.status || 200) < 500;
    const route = escapeHtml(_cvQHistRoute(raw));
    const startTime = item.startedAt
      ? new Date(item.startedAt * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
      : "—";
    const waitMs = item.queue?.queuedMs ?? 0;
    const procMs = procMsList[idx];
    const barPct = Math.round((procMs / maxProc) * 100);
    const model = _cvQHistModel(item);
    const statusCls = ok ? "cv-q-hist-ok" : "cv-q-hist-err";
    const statusGlyph = ok ? "✓" : "✗";
    const errTitle = item.errorKind ? item.errorKind.replace(/_/g, " ") : "";
    const waitHtml = waitMs > 0
      ? `<span class="cv-q-hist-wait" title="queued ${_cvQHistFmt(waitMs)}">W:${_cvQHistFmt(waitMs)}</span>`
      : `<span class="cv-q-hist-wait muted">—</span>`;
    return `<div class="cv-q-hist-row" title="${escapeHtml(item.route || "")}${errTitle ? " · " + errTitle : ""}">
      <span class="cv-q-hist-route">${route}</span>
      <span class="cv-q-hist-time">${startTime}</span>
      ${waitHtml}
      <span class="cv-q-hist-bar-wrap">
        <span class="cv-q-hist-track"><span class="cv-q-hist-fill" style="width:${barPct}%"></span></span>
        <span class="cv-q-hist-dur">${_cvQHistFmt(procMs)}</span>
      </span>
      <span class="cv-q-hist-model${model.overflow ? " overflow" : ""}" title="${escapeHtml(model.text)}">${model.overflow ? "↗ " : ""}${escapeHtml(model.text)}</span>
      <span class="${statusCls}" title="${errTitle}">${statusGlyph}</span>
    </div>`;
  }).join("");

  const age = Math.round((Date.now() - cache.ts) / 1000);
  return rows + `<div class="cv-q-hist-age">${age}s ago · <button class="cv-q-hist-refresh" type="button" data-cv-q-hist-refresh="${escapeHtml(nodeId)}">↻ refresh</button></div>`;
}

// Live region of a queue node card: slot meter + now-processing + channel-reserve
// + waiting queue. Split out from queueNodeBodyHtml so syncQueueNodesLive() can
// re-render JUST this region on every monitor tick — the surrounding card (routing
// destinations, editable params, history pane) stays put, keeping cables/inputs/
// focus intact. Without this the lists froze at load time (the canvas queue node
// showed "queue empty / no active request" while a request streamed through it).
export function queueNodeLiveHtml(router, n) {
  const cfg = n.config || {};
  const live = queueNodeLiveStats(router, n);
  const edges = graphOutEdges(router, n.id);
  const spillEdge = edges.find((e) => e.id === cfg.spillEdge);
  const spillPct = Math.max(0, Math.min(100, Number(cfg.spillPct ?? 20)));
  const running = live?.running || 0, slots = live?.slots || 0;
  // ── slot meter ──
  let pips = "";
  if (slots > 0) {
    const cap = Math.min(slots, 8);
    for (let i = 0; i < cap; i++) pips += `<span class="cv-q-pip${i < running ? " on" : ""}"></span>`;
    if (slots > 8) pips += `<span class="cv-q-pip-more">+${slots - 8}</span>`;
  } else {
    pips = `<span class="cv-q-pip${running ? " on" : ""}"></span>`;
  }
  const slotText = slots > 0 ? `${running}/${slots}` : `${running}/<span class="cv-q-auto">auto</span>`;
  // ── live lists for this admit upstream ──
  const group = live?.group || "";
  const ov = topologyRuntimeOverview();
  const inG = (it) => group && topologyItemGroup(it) === group;
  // Show both main-admitted and cloud-overflow running items so the user can see
  // where each request actually went. Cloud items are filtered by same proxy port.
  const admitPort = (topology?.proxies || []).find((p) => group === _proxyUpstreamStr(p))?.port;
  const overflowItems = admitPort
    ? ov.running.filter((it) => {
        const itPort = Number(it.port || 0);
        return itPort === Number(admitPort) && (it.upstreamType === "cloud" || it.queue?.cloudFallback);
      })
    : [];
  const runningItems = ov.running.filter(inG).slice(0, 4);
  const allRunning = [
    ...runningItems.map((it) => ({ it, isCloud: false })),
    ...overflowItems.filter((it) => !runningItems.includes(it)).map((it) => ({ it, isCloud: true })),
  ];
  const waitingItems = ov.queued.filter(inG).sort((a, b) => (a.queue?.position ?? 99) - (b.queue?.position ?? 99));
  // now processing — animated chevrons + elapsed seconds + route indicator
  const chevrons = `<span class="cv-q-chevrons" aria-hidden="true"><i></i><i></i><i></i></span>`;
  const nowRows = allRunning.length
    ? allRunning.map(({ it, isCloud }) => {
        const el = topologyFormatDuration(it.elapsedMs || topologyDurationMs(it.startedAt));
        const routeTag = isCloud
          ? `<span class="cv-q-route cloud" title="${escapeHtml(it.model || "cloud overflow")}">↗ cloud</span>`
          : `<span class="cv-q-route main" title="main upstream">→ main</span>`;
        return `<div class="cv-q-now-row running">${chevrons}<span class="cv-q-cli">${escapeHtml(_qClientName(it))}</span>${routeTag}<span class="cv-q-elapsed">${escapeHtml(el)}</span></div>`;
      }).join("")
    : `<div class="cv-q-empty">— no active request —</div>`;
  // channel reservation (sticky) bar — driven by the shared rAF ticker (ensureStickyBarTicker)
  const stickyData = group ? (ui.latestSystemMonitor?.latest?.agentProxies?.stickySlots || {})[group] : null;
  let reserveRow = "";
  if (stickyData && Number(stickyData.remainingSec) > 0) {
    const totalSec = Math.max(1, Number(cfg.stickySlotSec ?? 20));
    const anim = _qSetStickyAnim(group, stickyData, totalSec);
    const remMs = Math.max(0, anim.durationMs - (Date.now() - anim.startMs));
    const startPct = anim.durationMs > 0 ? (remMs / anim.durationMs) * 100 : 0;
    reserveRow = `<div class="cv-q-reserve">`
      + `<span class="cv-q-rlabel">⏱ channel reserved · <span data-sticky-secs>${Math.ceil(remMs / 1000)}s</span></span>`
      + `<span class="topology-sticky-bar" data-sticky-group="${escapeHtml(group)}" aria-hidden="true"><i style="clip-path:inset(0 ${(100 - startPct).toFixed(3)}% 0 0)"></i></span>`
    + `</div>`;
  }
  // waiting queue with expiring bars
  // spillRel = spill marker position on the bar (bar spans full clientTimeoutSeconds)
  const spillRel = spillPct; // spillPct% of full timeout = spillPct% of bar width
  const waitRows = waitingItems.slice(0, 5).map((it) => {
    const rt = topologyQueueRuntime(it);
    const totalMs = Math.max(1, rt.timeoutSec * 1000);
    const fill = Math.min(100, (rt.queuedMs / totalMs) * 100);
    const leftLabel = topologyFormatDuration(rt.leftMs);
    // overflow countdown: how long until this client spills (from backend cloudAt threshold)
    const overflowInMs = rt.cloudAt > 0 ? Math.max(0, rt.cloudAt * 1000 - rt.queuedMs) : null;
    const switchLine = spillEdge && overflowInMs !== null
      ? `<div class="cv-q-wait-sub${overflowInMs === 0 ? " now" : ""}">`
          + (overflowInMs > 0 ? `↗ switch in ${topologyFormatDuration(overflowInMs)}` : `↗ switching now`)
        + `</div>`
      : `<div class="cv-q-wait-sub muted">—</div>`;
    return `<div class="cv-q-wait-row">`
      + `<div class="cv-q-wait-top">`
        + `<span class="cv-q-cli">${escapeHtml(_qClientName(it))}</span>`
        + `<span class="cv-q-left">${escapeHtml(leftLabel)}</span>`
      + `</div>`
      + `<span class="cv-q-bar">`
        + `<span class="cv-q-bar-fill" style="width:${fill}%"></span>`
        + (spillEdge && spillRel > 0 && spillRel < 100 ? `<span class="cv-q-bar-mk spill" style="left:${spillRel}%" title="spills at ${spillPct}%"></span>` : "")
      + `</span>`
      + switchLine
    + `</div>`;
  }).join("");
  const moreWaiting = waitingItems.length > 5 ? `<div class="cv-q-empty">+${waitingItems.length - 5} more waiting…</div>` : "";
  const waitBlock = waitingItems.length
    ? `<div class="cv-q-sec-h">waiting · ${waitingItems.length}</div>${waitRows}${moreWaiting}`
    : `<div class="cv-q-empty muted">queue empty</div>`;
  return `<div class="cv-q-meter${slots > 0 && running >= slots ? " full" : ""}">`
      + `<span class="cv-q-pips">${pips}</span><span class="cv-q-slotnum">${slotText}</span>`
      + (waitingItems.length ? `<span class="cv-q-qd waiting">⏳ ${waitingItems.length}</span>` : `<span class="cv-q-qd idle">idle</span>`)
    + `</div>`
    + `<div class="cv-q-now">${nowRows}</div>`
    + reserveRow
    + `<div class="cv-q-waitwrap">${waitBlock}</div>`;
}

// Re-patch the live region of every canvas queue node card on the background tick.
// Queue node cards are only (re)built by a full renderTopology(); steady traffic
// doesn't change topologyStructureFingerprint(), so without this the now-processing /
// waiting lists stay frozen at their last full-render snapshot. Mirrors how the
// Main SLOTS panel is kept live — replace only the inner .cv-q-live region so the
// node's cables, out-ports, param inputs and history pane are untouched.
export function syncQueueNodesLive() {
  if (!topology) return;
  const liveEls = document.querySelectorAll("[data-cv-q-live]");
  if (!liveEls.length) return;
  const byId = {};
  (topology.routers || []).forEach((r) => {
    ((r.graph && r.graph.nodes) || []).forEach((nd) => {
      if (nd.type === "queue") byId[nd.id] = { router: r, node: nd };
    });
  });
  liveEls.forEach((el) => {
    const ent = byId[el.getAttribute("data-cv-q-live")];
    if (!ent) return;
    const html = queueNodeLiveHtml(ent.router, ent.node);
    if (el.innerHTML !== html) el.innerHTML = html;  // skip churn (keeps CSS anims) when unchanged
  });
}

// "By request-type" node body: two dest rows, each with its own out-port. Ports are
// tagged with data-cv-sched-port so they reuse the schedule node's edge plumbing
// (connect/draw/rewire/persist all key off schedPortId). The backend _eval_rule_node
// "requestType" branch reads the same tags: embeddings → "embed", else "__default__".
export function requestTypeNodeBodyHtml(router, n) {
  const edges = graphOutEdges(router, n.id);
  const embedEdge = edges.find((e) => e.schedPortId === "embed");
  // default = the explicitly-tagged port; fall back to any non-embed edge (heals graphs).
  const defaultEdge = edges.find((e) => e.schedPortId === "__default__")
    || edges.find((e) => e.schedPortId !== "embed");
  const embedLabel = embedEdge ? edgeTargetLabel(router, embedEdge) : "drag a cable →";
  const defaultLabel = defaultEdge ? edgeTargetLabel(router, defaultEdge) : "drag a cable →";
  // role drives the existing cv-q-* colour classes: embeddings reuses the "spill"
  // (diverted) accent, default reuses the "admit" (main) accent.
  const destRow = (portId, role, name, hint, label, wired) =>
    `<div class="cv-q-dest ${role}${wired ? "" : " unset"}">`
      + `<span class="cv-q-dot ${role}"></span>`
      + `<span class="cv-q-dl">${name}</span>`
      + `<span class="cv-q-dt" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`
      + `<span class="cv-port out${wired ? "" : " unset"}" data-cv-port="out" data-cv-sched-port="${portId}" title="${escapeHtml(hint)}"></span>`
    + `</div>`;
  // The clients-panel EMBEDDINGS selector (rules.embeddingsOutput) is checked
  // BEFORE the graph — when it is set, this node's embed port never fires.
  const globalEmbed = (router.rules || {}).embeddingsOutput;
  const globalNote = globalEmbed
    ? `<div class="cv-q-note">${escapeHtml(t("cvReqTypeGlobalNote"))}</div>` : "";
  return `<div class="cv-q-body">` + globalNote
    + destRow("embed", "spill", "embeddings", "Drag to the embeddings target (e.g. a cloud embedder) →", embedLabel, !!embedEdge)
    + destRow("__default__", "admit", "default", "Drag to where everything else should go →", defaultLabel, !!defaultEdge)
    + `</div>`;
}

// "By size" node body: small requests (max_tokens ≤ threshold — heartbeat-scale
// asks) leave the "small" port; everything bigger or unspecified takes the
// "__default__" port. Same schedPortId edge plumbing as requestType/schedule;
// the threshold input reuses the generic cv-q-cfg-in config handler.
export function requestSizeNodeBodyHtml(router, n) {
  const cfg = n.config || {};
  const thr = Math.max(1, Math.min(100000, Number(cfg.maxTokensAt ?? 300)));
  const edges = graphOutEdges(router, n.id);
  const smallEdge = edges.find((e) => e.schedPortId === "small");
  const defaultEdge = edges.find((e) => e.schedPortId === "__default__")
    || edges.find((e) => e.schedPortId !== "small");
  const smallLabel = smallEdge ? edgeTargetLabel(router, smallEdge) : "drag a cable →";
  const defaultLabel = defaultEdge ? edgeTargetLabel(router, defaultEdge) : "drag a cable →";
  const destRow = (portId, role, name, hint, label, wired) =>
    `<div class="cv-q-dest ${role}${wired ? "" : " unset"}">`
      + `<span class="cv-q-dot ${role}"></span>`
      + `<span class="cv-q-dl">${name}</span>`
      + `<span class="cv-q-dt" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`
      + `<span class="cv-port out${wired ? "" : " unset"}" data-cv-port="out" data-cv-sched-port="${portId}" title="${escapeHtml(hint)}"></span>`
    + `</div>`;
  const thrRow = `<div class="cv-q-cfg">`
    + `<label class="cv-q-cfg-row"><span>small ≤ <span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">Requests with <code>max_tokens</code> at or below this leave the <strong>small</strong> port (heartbeat-scale replies); bigger or unspecified requests take <strong>default</strong>.</span></span></span>`
    + `<input class="cv-q-cfg-in" type="number" min="1" max="100000" data-cv-q="maxTokensAt" value="${thr}" title="max_tokens threshold"><span class="cv-q-u">tok</span></label>`
    + `</div>`;
  return `<div class="cv-q-body">`
    + thrRow
    + destRow("small", "spill", "small", "Drag to where small requests (max_tokens ≤ threshold) go →", smallLabel, !!smallEdge)
    + destRow("__default__", "admit", "default", "Drag to where everything else should go →", defaultLabel, !!defaultEdge)
    + `</div>`;
}

export function queueNodeBodyHtml(router, n) {
  const cfg = n.config || {};
  const edges = graphOutEdges(router, n.id);
  const spillEdge = edges.find((e) => e.id === cfg.spillEdge);
  // admit falls back to the first non-spill edge (matches the engine + heals old graphs).
  const admitEdge = edges.find((e) => e.id === cfg.admitEdge) || edges.find((e) => e.id !== cfg.spillEdge);
  const admitLabel = admitEdge ? edgeTargetLabel(router, admitEdge) : "drag a cable →";
  const spillLabel = spillEdge ? edgeTargetLabel(router, spillEdge) : "drag a cable →";
  const spillPct = Math.max(0, Math.min(100, Number(cfg.spillPct ?? 20)));
  // ── main (admit) / overflow (spill) destination rows, each with its own out-port ──
  // role = internal data role (admit/spill); the visible label is main / overflow.
  const destRow = (role, label, wired) => {
    const name = role === "admit" ? "main" : "overflow";
    return `<div class="cv-q-dest ${role}${wired ? "" : " unset"}">`
      + `<span class="cv-q-dot ${role}"></span>`
      + `<span class="cv-q-dl">${name}</span>`
      + `<span class="cv-q-dt" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`
      + `<span class="cv-port out${wired ? "" : " unset"}" data-cv-port="out" data-cv-qrole="${role}" title="Drag a cable to the ${role === "admit" ? "main upstream" : "overflow target (a provider or another queue)"}"></span>`
    + `</div>`;
  };
  // ── inline, editable parameters (also in the ⚙ panel) ──
  const qnum = (key, val, min, max, ph) =>
    `<input class="cv-q-cfg-in" type="number" min="${min}" max="${max}" data-cv-q="${key}" value="${val === null || val === undefined ? "" : val}" placeholder="${ph || ""}" title="${escapeHtml(ph || key)}">`;
  const paramsGrid = `<div class="cv-q-cfg">`
    + `<label class="cv-q-cfg-row"><span>overflow at <span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">At this % of the client's wait-timeout, the request is redirected to the overflow output instead of continuing to wait.</span></span></span>${qnum("spillPct", cfg.spillPct ?? 20, 0, 100, "% of wait")}<span class="cv-q-u">%</span></label>`
    + `<label class="cv-q-cfg-row"><span>reserve <span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">After a request finishes, hold the server slot for the same agent's next call for this many seconds. 0 = disabled.</span></span></span>${qnum("stickySlotSec", cfg.stickySlotSec ?? 20, 0, 120, "reserve for agent")}<span class="cv-q-u">s</span></label>`
    + `</div>`;
  // History pane — auto-refresh if stale while open
  const histOpen = !!_cvQueueHistOpen[n.id];
  const histCache = _cvQueueHistData[n.id];
  if (histOpen && histCache && Date.now() - histCache.ts > 15000) {
    // stale — kick a silent refresh; next render will pick up new data
    setTimeout(() => _fetchQueueHist(n.id), 0);
  }
  const histSection = `<div class="cv-q-hist${histOpen ? " open" : ""}">
    <button class="cv-act cv-q-hist-toggle" type="button" data-cv-q-hist-toggle="${escapeHtml(n.id)}">
      🕐 history ${histOpen ? "▴" : "▾"}
    </button>
    ${histOpen ? `<div class="cv-q-hist-body">${_renderQueueHistHtml(n.id)}</div>` : ""}
  </div>`;

  return `<div class="cv-q-body">`
    // routing first: main / overflow destinations (point 4 — above the live lists)
    + destRow("admit", admitLabel, !!admitEdge)
    + destRow("spill", spillLabel, !!spillEdge)
    + paramsGrid
    // live state below — wrapped in a stable container so syncQueueNodesLive() can
    // re-patch just this region every monitor tick (the rest of the card stays put).
    + `<div class="cv-q-live" data-cv-q-live="${escapeHtml(n.id)}">${queueNodeLiveHtml(router, n)}</div>`
    + histSection
    + `</div>`;
}

// Anchor a sticky-reservation bar's drain to an absolute clock (mirrors the classic
// slot view) so periodic re-renders never restart/rescale it. Shared rAF ticker
// (ensureStickyBarTicker) reads stickySlotAnims[group] every frame.
export function _qSetStickyAnim(group, stickyData, totalSec) {
  const rem = Math.max(0, Number(stickyData.remainingSec));
  const port = Number(stickyData.port);
  const totalMs = Math.max(1, Math.round(totalSec * 1000));
  const nowMs = Date.now();
  const elapsedPollMs = Math.max(0, totalMs - rem * 1000);
  const prev = stickySlotAnims[group];
  const drift = prev ? Math.abs((nowMs - prev.startMs) - elapsedPollMs) : Infinity;
  if (!prev || prev.port !== port || prev.durationMs !== totalMs || drift > 1500) {
    stickySlotAnims[group] = { port, startMs: nowMs - elapsedPollMs, durationMs: totalMs };
  }
  return stickySlotAnims[group];
}

// Build the node descriptors for a router (id, html, default position).
// ── Canvas schedule node helpers ──────────────────────────────────────────────
export const CV_SCHED_COLORS = ["#60a5fa", "#f59e0b", "#22c55e", "#ef4444", "#a78bfa", "#ec4899", "#14b8a6", "#eab308"];
export const CV_SCHED_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function _cvSchedColor(outputs, outId) {
  const i = (outputs || []).findIndex((o) => o.id === outId);
  return i < 0 ? "" : CV_SCHED_COLORS[i % CV_SCHED_COLORS.length];
}

export function _cvSchedMakeGrid(cfg) {
  const raw = cfg.grid || [];
  return Array.from({ length: 7 }, (_, d) =>
    Array.from({ length: 24 }, (_, h) => { const row = raw[d]; return (Array.isArray(row) ? row[h] : null) || null; })
  );
}

export function _cvSchedNow() {
  const now = new Date();
  return {
    d: (now.getDay() + 6) % 7,   // Mon=0 … Sun=6
    h: now.getHours(),
    timeStr: String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0"),
  };
}

export function renderSchedNodeHtml(n, router) {
  const nid = n.id;
  const cfg = n.config || {};
  const outputs = cfg.outputs || [];
  const grid = _cvSchedMakeGrid(cfg);
  const inputPorts = _cvSchedInputPorts(router, nid);  // ports that enter this node
  const paintId = _cvSchedPaintIds[nid] ?? (outputs[0]?.id || "");
  const collapsed = _cvSchedCollapsed.has(nid);
  const { d: nowD, h: nowH, timeStr: nowTimeStr } = _cvSchedNow();
  const activeNowId = grid[nowD]?.[nowH] || null;   // null → "default" is active

  const toggleBtn = `<button class="cv-act cv-sched-toggle" type="button" data-cv-sched-toggle="${escapeHtml(nid)}" title="${collapsed ? "Expand" : "Collapse"}">${collapsed ? "+" : "−"}</button>`;
  const head = `<span class="cv-rule-head"><strong>⏱ schedule</strong><span class="cv-sched-now-clock" data-cv-sched-clock="${escapeHtml(nid)}">${nowTimeStr}</span><span class="cv-rule-btns">${toggleBtn}<button class="cv-act cv-rule-del" type="button" data-cv-delnode="${escapeHtml(nid)}" title="Delete node">×</button></span></span>`;

  if (collapsed) {
    const activeName = activeNowId ? (outputs.find((o) => o.id === activeNowId)?.name || "output") : (cfg.defaultName || "default");
    const ports = [...outputs.map((o) =>
      `<div class="cv-sched-chip-stub"><span class="cv-port out" data-cv-port="out" data-cv-sched-port="${escapeHtml(o.id)}" title="${escapeHtml(o.name)} →"></span></div>`
    ), `<div class="cv-sched-chip-stub"><span class="cv-port out" data-cv-port="out" data-cv-sched-port="__default__" title="default →"></span></div>`].join("");
    return head
      + `<span class="cv-sub">${outputs.length} output${outputs.length !== 1 ? "s" : ""} · now → ${escapeHtml(activeName)}</span>`
      + ports;
  }

  // ── Output rows (full-width, like queue rows) ──────────────────────────────
  const rows = [
    ...outputs.map((o, i) => {
      const color = CV_SCHED_COLORS[i % CV_SCHED_COLORS.length];
      const active = paintId === o.id;
      const nowActive = o.id === activeNowId;
      return `<div class="cv-sched-row${active ? " cv-sched-row--active" : ""}${nowActive ? " cv-sched-row--now-active" : ""}" data-cv-sched-chip="${escapeHtml(nid)}:${escapeHtml(o.id)}">`
        + `<i class="cv-sched-dot" style="background:${color}"></i>`
        + `<span class="cv-sched-name" data-cv-sched-rename="${escapeHtml(nid)}:${escapeHtml(o.id)}" spellcheck="false">${escapeHtml(o.name)}</span>`
        + `<button class="cv-sched-rm" type="button" data-cv-sched-rmout="${escapeHtml(nid)}:${escapeHtml(o.id)}" title="Remove">×</button>`
        + `<span class="cv-port out" data-cv-port="out" data-cv-sched-port="${escapeHtml(o.id)}" title="Drag to connect →"></span>`
        + `</div>`;
    }),
    `<div class="cv-sched-row cv-sched-row--default${paintId === "__default__" ? " cv-sched-row--active" : ""}${activeNowId === null ? " cv-sched-row--now-active" : ""}" data-cv-sched-chip="${escapeHtml(nid)}:__default__">`
      + `<i class="cv-sched-dot cv-sched-dot--default"></i>`
      + `<span class="cv-sched-name" data-cv-sched-rename-default="${escapeHtml(nid)}" spellcheck="false">${escapeHtml(cfg.defaultName || "default")}</span>`
      + `<span class="cv-port out" data-cv-port="out" data-cv-sched-port="__default__" title="Drag to connect →"></span>`
      + `</div>`,
    `<button class="cv-sched-addrow" type="button" data-cv-sched-addout="${escapeHtml(nid)}">+ output</button>`,
  ].join("");

  // ── GCal grid: hours as rows (0→23), days as columns (Mon→Sun) ────────────
  const gcalHdr = `<div class="cv-sched-gcal-hdr">`
    + `<div class="cv-sched-gcal-corner"></div>`
    + CV_SCHED_DAY_LABELS.map((dl, d) => `<div class="cv-sched-gcal-dh${d === nowD ? " cv-sched-gcal-dh--now" : ""}">${dl}</div>`).join("")
    + `</div>`;

  const gcalRows = Array.from({ length: 24 }, (_, h) =>
    `<div class="cv-sched-gcal-row${h === nowH ? " cv-sched-gcal-row--now" : ""}" data-cv-sched-row-h="${h}">`
    + `<div class="cv-sched-gcal-hl">${h % 3 === 0 ? h : ""}</div>`
    + CV_SCHED_DAY_LABELS.map((_, d) => {
        const outId = grid[d][h];
        const color = outId ? _cvSchedColor(outputs, outId) : "";
        const isNowCell = (d === nowD && h === nowH);
        const isNowCol  = (d === nowD && h !== nowH);
        return `<div class="cv-sched-cell${outId ? " painted" : ""}${isNowCell ? " cv-sched-cell--now" : ""}${isNowCol ? " cv-sched-cell--now-d" : ""}" data-cv-sched-cell="${escapeHtml(nid)}" data-sched-d="${d}" data-sched-h="${h}"${color ? ` style="background:${color}"` : ""}></div>`;
      }).join("")
    + `</div>`
  ).join("");

  // ── History pane ──────────────────────────────────────────────────────────
  const histOpen = !!_cvSchedHistOpen[nid];
  const histCache = _cvSchedHistData[nid];
  if (histOpen && histCache && Date.now() - histCache.ts > 15000) {
    setTimeout(() => _fetchSchedHist(nid), 0);
  }
  const histSection = `<div class="cv-q-hist${histOpen ? " open" : ""}">
    <button class="cv-act cv-q-hist-toggle" type="button" data-cv-sched-hist-toggle="${escapeHtml(nid)}">
      🕐 history ${histOpen ? "▴" : "▾"}
    </button>
    ${histOpen ? `<div class="cv-q-hist-body">${_renderSchedHistHtml(nid, outputs, grid, inputPorts)}</div>` : ""}
  </div>`;

  return head
    + `<div class="cv-sched-rows">${rows}</div>`
    + `<div class="cv-sched-gcal">${gcalHdr}${gcalRows}</div>`
    + histSection;
}

// Lightweight ticker — updates clock text and "now" markers without full re-render
export function _cvSchedTickNow() {
  const { d: nowD, h: nowH, timeStr } = _cvSchedNow();

  // Update clock text in all rendered schedule nodes
  document.querySelectorAll("[data-cv-sched-clock]").forEach((el) => { el.textContent = timeStr; });

  // Move now-row class
  document.querySelectorAll(".cv-sched-gcal-row--now").forEach((r) => r.classList.remove("cv-sched-gcal-row--now"));
  document.querySelectorAll(`[data-cv-sched-row-h="${nowH}"]`).forEach((r) => r.classList.add("cv-sched-gcal-row--now"));

  // Move now-day column highlight + now-cell marker
  document.querySelectorAll(".cv-sched-cell--now, .cv-sched-cell--now-d").forEach((c) => {
    c.classList.remove("cv-sched-cell--now", "cv-sched-cell--now-d");
  });
  document.querySelectorAll("[data-cv-sched-cell]").forEach((cell) => {
    const d = +cell.dataset.schedD, h = +cell.dataset.schedH;
    if (d === nowD && h === nowH) cell.classList.add("cv-sched-cell--now");
    else if (d === nowD)          cell.classList.add("cv-sched-cell--now-d");
  });

  // Move now-day header highlight
  document.querySelectorAll(".cv-sched-gcal-dh--now").forEach((el) => el.classList.remove("cv-sched-gcal-dh--now"));
  document.querySelectorAll(".cv-sched-gcal-dh").forEach((el, i) => {
    if (i % 7 === nowD) el.classList.add("cv-sched-gcal-dh--now");
  });

  // Update "now active" output rows — read painted cell to find active outId
  document.querySelectorAll(".cv-sched-row--now-active").forEach((r) => r.classList.remove("cv-sched-row--now-active"));
  // For each schedule node, find the now cell and resolve which chip is active
  const nowCells = document.querySelectorAll(`[data-cv-sched-cell][data-sched-d="${nowD}"][data-sched-h="${nowH}"]`);
  nowCells.forEach((cell) => {
    const nid = cell.dataset.cvSchedCell;
    // painted cell → find matching chip row; unpainted → default row
    if (cell.classList.contains("painted")) {
      const color = cell.style.background;
      // Find the chip row whose dot matches this color
      const rows = document.querySelectorAll(`[data-cv-sched-chip^="${CSS.escape(nid)}:"]`);
      rows.forEach((row) => {
        const dot = row.querySelector(".cv-sched-dot");
        if (dot && dot.style.background === color) row.classList.add("cv-sched-row--now-active");
      });
    } else {
      // default row
      const defRow = document.querySelector(`[data-cv-sched-chip="${CSS.escape(nid)}:__default__"]`);
      if (defRow) defRow.classList.add("cv-sched-row--now-active");
    }
  });
}

if (typeof window !== "undefined" && !window._cvSchedNowTimer) {
  window._cvSchedNowTimer = setInterval(_cvSchedTickNow, 30_000);
}

export function _cvSchedPaintCell(nid, d, h) {
  if (!_cvSchedPendingGrid || _cvSchedPendingGrid.nid !== nid) return;
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
  const node = (router?.graph?.nodes || []).find((n) => n.id === nid);
  const outputs = node?.config?.outputs || [];
  // Default to first output if not explicitly chosen yet
  const paintId = _cvSchedPaintIds[nid] ?? (outputs[0]?.id || "");
  const grid = _cvSchedPendingGrid.grid;
  grid[d][h] = (paintId === "" || paintId === "__default__") ? null : paintId;
  // Update DOM immediately (optimistic paint)
  const cell = document.querySelector(`[data-cv-sched-cell="${CSS.escape(nid)}"][data-sched-d="${d}"][data-sched-h="${h}"]`);
  if (cell) {
    const color = grid[d][h] ? _cvSchedColor(outputs, grid[d][h]) : "";
    cell.style.background = color;
    cell.classList.toggle("painted", !!color);
  }
}

if (typeof window !== "undefined" && !window._cvSchedUpBound) {
  window._cvSchedUpBound = true;
  window.addEventListener("pointerup", () => {
    if (!_cvSchedPainting || !_cvSchedPendingGrid) return;
    _cvSchedPainting = false;
    const { nid, grid } = _cvSchedPendingGrid;
    _cvSchedWorkingGrids[nid] = grid;
    _cvSchedPendingGrid = null;
    _cvSchedPaintNid = null;
    _cvSchedSaveGrid(nid, grid);
  });
}

export function canvasNodes(router) {
  const inputs = router.inputs || [];
  const inProxies = (topology?.proxies || []).filter((p) => inputs.includes(p.id) && !_cvProxyIsTombstoned(p));
  const byClient = new Map();
  for (const p of inProxies) {
    const key = canvasClientKey(p);
    if (!byClient.has(key)) byClient.set(key, { key, proxies: [] });
    byClient.get(key).proxies.push(p);
  }
  const outputs = router.outputs || [];
  const defaultId = router.rules?.default || "";
  const nodes = [];
  const graph = router.graph || { nodes: [], edges: [] };
  const ruleNodes = graph.nodes || [];
  const PORT_OUT = `<span class="cv-port out" data-cv-port="out" title="Drag to connect →"></span>`;
  const PORT_IN = `<span class="cv-port in" data-cv-port="in" title="Drop a connection here"></span>`;
  // Single source of truth = the canvas. Only inputs WIRED into the graph (≥1 outgoing
  // edge) appear here; unwired proxies live in the left panel — drag one onto a node to
  // route it. Everything unwired falls through to the default output.
  const wiredProxyIds = new Set((graph.edges || []).map((e) => String(e.from)).filter((r) => r.startsWith("in:")).map((r) => r.slice(3)));
  const roleOf = (p) => (p.role || (String(p.label || "").match(/(primary|fallback)$/i)?.[1]?.toLowerCase()) || "");
  const mutedProxies = topologyMutedProxyIds();
  const graphInputs = graph.inputs || {};
  // Each client row inside the inputs block. Port dots are NOT inline — they are created
  // dynamically as direct children of the block by _cvSyncInputsBlockPortDots() so they
  // straddle the RIGHT border correctly even when the body is scrolled.
  const inPortRow = (role, p, wired) => p ? `
    <div class="cv-in-row ${role}${wired ? "" : " unwired"}" data-cv-in-row="in:${escapeHtml(p.id)}">
      <span class="cv-in-role">${role === "primary" ? "P" : "F"}</span>
      <span class="cv-in-port-num">:${escapeHtml(String(p.port))}</span>
      ${role === "fallback" && !wired ? `<span class="cv-in-follow">↳ follows</span>` : ""}
    </div>` : "";
  const waitRow = (p) => {
    if (!p) return "";
    const override = Number(graphInputs[p.id]?.clientTimeoutSeconds || 0);
    const synced = proxyEffectiveWaitTimeout(p);
    return `<div class="cv-in-wait" title="Wait budget — queue spill/give-up %25 scale against this. Auto-synced from the agent; type a value to override.">`
      + `<span class="cv-in-wait-lbl">wait</span>`
      + `<input class="cv-in-wait-in" type="number" min="0" max="86400" data-cv-wait="${escapeHtml(p.id)}" value="${override || ""}" placeholder="${synced || "auto"}">`
      + `<span class="cv-in-wait-u">s</span></div>`;
  };
  // Build the grouped inputs block — one block for all clients, each row has a port dot
  // on the right border (created by _cvSyncInputsBlockPortDots after render).
  const inputsBodyHtml = [...byClient.values()].map((c) => {
    const prim = c.proxies.find((p) => roleOf(p) === "primary") || c.proxies[0];
    const fb = c.proxies.find((p) => roleOf(p) === "fallback" && p !== prim && !mutedProxies.has(p.id));
    const anyWired = c.proxies.some((p) => wiredProxyIds.has(p.id));
    const isStale = c.proxies.some((p) => _cvProxyIsStale(p));
    const cls = `${anyWired ? "routed" : "unrouted"}${isStale ? " stale" : ""}`;
    return `<div class="cv-inputs-client ${cls}">`
      + `<span class="cv-in-name">${escapeHtml(canvasClientName(c.proxies[0]))}</span>`
      + inPortRow("primary", prim, wiredProxyIds.has(prim.id))
      + inPortRow("fallback", fb, fb && wiredProxyIds.has(fb.id))
      + waitRow(prim)
      + `</div>`;
  }).join("");
  // Embeddings slot — one global target for EVERY client's /v1/embeddings (Variant 1).
  // Pick a local embed-model server; empty ⇒ embeddings can't be served (warned).
  const embedOutId = router.rules?.embeddingsOutput || "";
  const localLlamaOuts = outputs.filter((o) => String(o.upstreamType || "llama") !== "cloud");
  const embedOut = localLlamaOuts.find((o) => o.id === embedOutId);
  const embedOpts = localLlamaOuts.map((o) =>
    `<option value="${escapeHtml(o.id)}"${o.id === embedOutId ? " selected" : ""}>${escapeHtml(topologyRouterOutputLabel(o))}</option>`).join("");
  const embedSlotHtml = `<div class="cv-embed-slot ${embedOut ? "assigned" : "unassigned"}">`
    + `<div class="cv-embed-head">🧬 embeddings <span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">Every client's <code>POST /v1/embeddings</code> goes to this one server — global, no per-route wiring. Pick a local embedding model; empty means embeddings can't be served.</span></span></div>`
    + `<select class="cv-embed-select" data-cv-embed-out><option value="">— not assigned —</option>${embedOpts}</select>`
    + `<div class="cv-embed-note">${embedOut ? `all /v1/embeddings → ${escapeHtml(topologyRouterOutputLabel(embedOut))}` : "not set — /v1/embeddings will fail"}</div>`
    + `</div>`;
  nodes.push({
    id: "inputs:block",
    type: "inputs",
    cls: "cv-inputs-block",
    fixed: { x: 20, y: 20 },
    html: `<div class="cv-inputs-head">Clients <span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">Proxy ports that feed requests into this board. Drag a cable from a client port to a rule node or server to route it.</span></span></div><div class="cv-inputs-body">${inputsBodyHtml || '<span class="router-cfg-muted" style="font-size:11px;padding:6px 0;display:block">no proxy ports</span>'}</div>${embedSlotHtml}`,
  });
  // Rule nodes (graph mode) — positioned by their stored x/y; input + output ports.
  const RULE_GLYPH = { schedule: "⏱", weighted: "⚖", roundRobin: "🔁", failover: "⚡", queue: "⏳", requestType: "🔀", requestSize: "📏" };
  ruleNodes.forEach((n) => {
    const isQueue = n.type === "queue";
    const isSchedule = n.type === "schedule";
    const isReqType = n.type === "requestType";
    const isReqSize = n.type === "requestSize";
    const ownPorts = isQueue || isReqType || isReqSize;  // render their own out-ports inside the body
    if (isSchedule) {
      // Schedule nodes have inline expanded/collapsed body with own ports — no generic PORT_OUT.
      nodes.push({
        id: `rule:${n.id}`, type: "rule", cls: "cv-rule-sched", fixed: { x: n.x || 0, y: n.y || 0 },
        html: renderSchedNodeHtml(n, router) + PORT_IN,
      });
      return;
    }
    // Queue nodes already have inline config fields on the card — show a ? help
    // tooltip instead of a gear button. Other rule nodes need the gear for setup.
    const cfgBtn = isQueue
      ? `<span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">Wire the <strong>main</strong> and <strong>spill</strong> ports on the node (drag a cable from each). Requests wait for a slot on the main upstream; at <strong>overflow%</strong> of the client's timeout they divert to the spill target. <em>overflow at</em> and <em>reserve</em> are editable inline on the card.</span></span>`
      : isReqType
      ? `<span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">Wire the two ports (drag a cable from each): <strong>embeddings</strong> sends <code>POST /v1/embeddings</code> to its target (e.g. a cloud embedder); <strong>default</strong> takes everything else.</span></span>`
      : isReqSize
      ? `<span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">Wire the two ports (drag a cable from each): <strong>small</strong> takes requests with <code>max_tokens</code> ≤ the threshold (heartbeat-scale asks); <strong>default</strong> takes the rest. The threshold edits inline on the card.</span></span>`
      : `<button class="cv-act cv-rule-cfg" type="button" data-cv-cfgnode="${escapeHtml(n.id)}" title="Configure this node">⚙</button>`;
    const head = `<span class="cv-rule-head"><strong>${RULE_GLYPH[n.type] || "•"} ${escapeHtml(n.type)}</strong>`
      + `<span class="cv-rule-btns">${cfgBtn}`
      + `<button class="cv-act cv-rule-del" type="button" data-cv-delnode="${escapeHtml(n.id)}" title="Delete node">×</button></span></span>`;
    const body = isQueue
      ? queueNodeBodyHtml(router, n)
      : isReqType
      ? requestTypeNodeBodyHtml(router, n)
      : isReqSize
      ? requestSizeNodeBodyHtml(router, n)
      : `<span class="cv-sub">${escapeHtml(_ruleNodeSummary(n, outputs))}</span>`;
    // Queue and request-type/size nodes carry their OWN out-ports inside the body;
    // other rule nodes use the single generic out-port.
    nodes.push({
      id: `rule:${n.id}`, type: "rule", cls: isQueue ? "cv-rule-queue" : ((isReqType || isReqSize) ? "cv-rule-reqtype" : ""), fixed: { x: n.x || 0, y: n.y || 0 },
      html: head + body + PORT_IN + (ownPorts ? "" : PORT_OUT),
    });
  });
  // Servers block — stationary canvas node (draggable, no delete button).
  // Each output row inside it carries data-cv-out-port="out:<id>" as its input port.
  nodes.push({
    id: "outputs:block",
    type: "outputs",
    cls: "cv-servers-block",
    fixed: { x: 700, y: 20 },
    html: `<div class="cv-servers-head">${escapeHtml(t("topologyServersHead"))} <span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">Output targets: local llama models and cloud providers. Connect rule nodes or client ports to an output here to send traffic to it.</span></span></div><div class="cv-servers-body">${renderServersBlockHtml(router)}</div>`,
  });
  return nodes;
}

// One-line summary shown under a rule node's title.
export function _ruleNodeSummary(n, outputs) {
  const c = n.config || {};
  if (n.type === "schedule") return `${(c.windows || []).length} window(s)`;
  if (n.type === "weighted") return (c.weights || []).map((w) => `${w.pct}%`).join(" / ") || "no weights";
  if (n.type === "failover") return `${(c.order || []).length} in order`;
  if (n.type === "roundRobin") return "rotate outputs";
  if (n.type === "queue") {
    const slots = c.maxSlots ? `${c.maxSlots} slot${c.maxSlots > 1 ? "s" : ""}` : "auto slots";
    return `${slots} · spill ${c.spillPct ?? 20}%`;
  }
  return "";
}

// ── Graph editing (Stage C): add/delete rule nodes + edges, persisted to router.graph ──
export function _newId(prefix) { return prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 5); }

// World-space point at the centre of the current viewport (for placing new nodes).
export function _cvViewCentre() {
  const vp = document.querySelector("[data-cv-viewport]");
  const w = vp ? vp.clientWidth : 800, h = vp ? vp.clientHeight : 600;
  return { x: Math.round((w / 2 - _cvView.tx) / _cvView.scale), y: Math.round((h / 2 - _cvView.ty) / _cvView.scale) };
}

export function addRuleNode(type) {
  const c = _cvViewCentre();
  saveRouters((routers) => {
    const s = routerById(routers, ui.topologyCanvasRouterId);
    if (!s) return;
    s.graph = s.graph || { nodes: [], edges: [] };
    s.graph.nodes = s.graph.nodes || [];
    const cfg = type === "schedule"
      ? { outputs: [{ id: _newId("sout"), name: "output 1" }, { id: _newId("sout"), name: "output 2" }], grid: Array.from({ length: 7 }, () => Array(24).fill(null)) }
      : {};
    s.graph.nodes.push({ id: _newId("n"), type, x: c.x, y: c.y, config: cfg });
  }).catch((e) => toast(e.message));
}

export async function deleteRuleNode(nid) {
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
  const node = (router?.graph?.nodes || []).find((n) => n.id === nid);
  const kind = node ? node.type : "node";
  const nEdges = (router?.graph?.edges || []).filter((e) => e.from === `rule:${nid}` || e.to === `rule:${nid}`).length;
  const extra = nEdges ? t("dlgNodeEdges", { n: nEdges }) : "";
  if (!(await appConfirm(t("dlgDeleteNode", { kind, extra }), { confirmLabel: t("deleteAction") }))) return;
  saveRouters((routers) => {
    const s = routerById(routers, ui.topologyCanvasRouterId);
    if (!s || !s.graph) return;
    s.graph.nodes = (s.graph.nodes || []).filter((n) => n.id !== nid);
    s.graph.edges = (s.graph.edges || []).filter((e) => e.from !== `rule:${nid}` && e.to !== `rule:${nid}`);
  }).catch((e) => toast(e.message));
}

// Proxy input refs for a client key (the engine keys inputs per proxy/port).
export function clientProxyInputRefs(router, clientKey) {
  return (topology?.proxies || [])
    .filter((p) => (router.inputs || []).includes(p.id) && canvasClientKey(p) === clientKey)
    .map((p) => `in:${p.id}`);
}

// A proxy port (in:<proxyId>) may have only ONE outgoing connection — a fresh wire
// replaces its existing one. Rule nodes can fan out to many.
export function _isSingleOut(ref) { return String(ref).startsWith("in:"); }

// fromRef may be "inc:<clientKey>" (expands to one edge per proxy) or a concrete ref.
// queueRole ("admit"|"spill") wires a queue node's dedicated port: it's single-out per
// role (replaces that role's existing edge) and records the new edge id in the node's
// config.admitEdge / spillEdge.
export function addGraphEdge(fromRef, toRef, queueRole, schedPortId) {
  if (!fromRef || !toRef || fromRef === toRef) return;
  saveRouters((routers) => {
    const s = routerById(routers, ui.topologyCanvasRouterId);
    if (!s) return;
    s.graph = s.graph || { nodes: [], edges: [] };
    s.graph.edges = s.graph.edges || [];
    // Schedule node: each output port gets exactly one edge tagged with schedPortId.
    if (schedPortId && fromRef.startsWith("rule:")) {
      s.graph.edges = s.graph.edges.filter((e) => !(e.from === fromRef && e.schedPortId === schedPortId));
      s.graph.edges.push({ id: _newId("e"), from: fromRef, to: toRef, schedPortId });
      return;
    }
    if (queueRole && fromRef.startsWith("rule:")) {
      const node = (s.graph.nodes || []).find((n) => `rule:${n.id}` === fromRef && n.type === "queue");
      if (!node) return;
      node.config = node.config || {};
      const roleKey = queueRole === "spill" ? "spillEdge" : "admitEdge";
      const otherKey = queueRole === "spill" ? "admitEdge" : "spillEdge";
      // Drop this role's previous edge (single-out per role). Keep the other role's edge.
      s.graph.edges = s.graph.edges.filter((e) => e.id !== node.config[roleKey]);
      // Reuse an existing from→to edge if present (e.g. the other role already points there
      // is disallowed by dedupe, so this only matches a stale same-role edge).
      let edge = s.graph.edges.find((e) => e.from === fromRef && e.to === toRef && e.id !== node.config[otherKey]);
      if (!edge) { edge = { id: _newId("e"), from: fromRef, to: toRef }; s.graph.edges.push(edge); }
      node.config[roleKey] = edge.id;
      return;
    }
    const froms = fromRef.startsWith("inc:") ? clientProxyInputRefs(s, fromRef.slice(4)) : [fromRef];
    froms.forEach((f) => {
      if (_isSingleOut(f)) s.graph.edges = s.graph.edges.filter((e) => e.from !== f);   // replace existing
      if (f !== toRef && !s.graph.edges.some((e) => e.from === f && e.to === toRef)) {
        s.graph.edges.push({ id: _newId("e"), from: f, to: toRef });
      }
    });
  }).catch((e) => toast(e.message));
}

// Heal queue nodes authored before role-ports existed (or left with a stray edge):
// adopt the first unassigned outgoing edge as `admit` so it anchors at the main port and
// the row shows its target. Persists only when something changes (converges, no loop).
export function healQueueNodeEdges() {
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
  if (!router?.graph?.nodes?.length) return;
  const needs = (g) => (g.nodes || []).some((n) => {
    if (n.type !== "queue") return false;
    const c = n.config || {};
    const outs = (g.edges || []).filter((e) => e.from === `rule:${n.id}`);
    const admitOk = c.admitEdge && outs.some((e) => e.id === c.admitEdge);
    return !admitOk && outs.some((e) => e.id !== c.spillEdge);
  });
  if (!needs(router.graph)) return;
  saveRouters((routers) => {
    const s = routerById(routers, ui.topologyCanvasRouterId);
    for (const n of (s?.graph?.nodes || [])) {
      if (n.type !== "queue") continue;
      n.config = n.config || {};
      const outs = (s.graph.edges || []).filter((e) => e.from === `rule:${n.id}`);
      const admitOk = n.config.admitEdge && outs.some((e) => e.id === n.config.admitEdge);
      if (admitOk) continue;
      const free = outs.find((e) => e.id !== n.config.spillEdge);
      if (free) n.config.admitEdge = free.id;
    }
  }).catch(() => {});
}

// Re-point an existing edge (drag its endpoint to a new target).
export function rewireGraphEdge(fromRef, oldTo, newTo) {
  if (!fromRef || !newTo || newTo === oldTo) return;
  saveRouters((routers) => {
    const s = routerById(routers, ui.topologyCanvasRouterId);
    if (!s || !s.graph) return;
    // Preserve schedPortId from the old edge so rewired schedule cables stay tagged.
    const oldEdge = (s.graph.edges || []).find((e) => e.from === fromRef && e.to === oldTo);
    const inherited = oldEdge?.schedPortId ? { schedPortId: oldEdge.schedPortId } : {};
    s.graph.edges = (s.graph.edges || []).filter((e) => !(e.from === fromRef && e.to === oldTo));
    if (fromRef !== newTo && !s.graph.edges.some((e) => e.from === fromRef && e.to === newTo)) {
      s.graph.edges.push({ id: _newId("e"), from: fromRef, to: newTo, ...inherited });
    }
  }).catch((e) => toast(e.message));
}

// Ask before removing a cable. Uses the shared confirm modal; raised above the
// router-workspace overlay via #confirmOverlay's z-index in CSS.
export function confirmDeleteGraphEdge(domFrom, domTo) {
  $("confirmTitle").textContent = t("deleteCableTitle");
  $("confirmText").textContent = t("deleteCableText");
  $("confirmMeta").hidden = true;
  $("confirmPath").textContent = "";
  $("confirmDelete").textContent = t("deleteAction");
  $("confirmDelete").classList.add("danger");
  ui.pendingConfirm = () => { closeConfirmModal(); deleteGraphEdgesBetween(domFrom, domTo); };
  $("confirmOverlay").hidden = false;
}

export function deleteGraphEdgesBetween(domFrom, domTo) {
  saveRouters((routers) => {
    const s = routerById(routers, ui.topologyCanvasRouterId);
    if (!s || !s.graph) return;
    const expand = (ref) => ref.startsWith("inc:") ? clientProxyInputRefs(s, ref.slice(4)) : [ref];
    const froms = new Set(expand(domFrom)), tos = new Set(expand(domTo));
    s.graph.edges = (s.graph.edges || []).filter((e) => !(froms.has(e.from) && tos.has(e.to)));
  }).catch((e) => toast(e.message));
}

// ── Per-node config editor (Stage C.2) ──────────────────────────────────────────
export const CV_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export function graphOutEdges(router, nodeId) {
  return (router.graph?.edges || []).filter((e) => e.from === `rule:${nodeId}`);
}

export function edgeTargetLabel(router, edge) {
  const to = String(edge.to || "");
  if (to.startsWith("out:")) {
    const o = (router.outputs || []).find((x) => x.id === to.slice(4));
    return o ? topologyRouterOutputLabel(o) : to.slice(4);
  }
  if (to.startsWith("rule:")) {
    const n = (router.graph?.nodes || []).find((x) => x.id === to.slice(5));
    return n ? `▢ ${n.type}` : to.slice(5);
  }
  return to;
}

// Per-node save queue for the schedule grid.
// Only one HTTP request per node is in-flight at a time; if new strokes arrive
// while a save is in-flight, the latest grid is stored as `pending` and fired
// immediately when the current request settles — preventing out-of-order writes.
export const _cvSchedSaveQueue = {}; // nid → { inFlight: bool, pending: grid | null }

export function _cvSchedSaveGrid(nid, grid) {
  const q = _cvSchedSaveQueue[nid] || (_cvSchedSaveQueue[nid] = { inFlight: false, pending: null });
  if (q.inFlight) { q.pending = grid; return; }
  q.inFlight = true;
  saveRouters((routers) => {
    const n = (routerById(routers, ui.topologyCanvasRouterId)?.graph?.nodes || []).find((x) => x.id === nid);
    if (n) { n.config = n.config || {}; n.config.grid = grid; }
  }).catch((e) => toast(e.message)).finally(() => {
    q.inFlight = false;
    if (q.pending !== null) { const next = q.pending; q.pending = null; _cvSchedSaveGrid(nid, next); }
  });
}

// Merge a patch into a rule node's config and persist (auto-save).
export function saveNodeConfig(nid, patchFn) {
  saveRouters((routers) => {
    const n = (routerById(routers, ui.topologyCanvasRouterId)?.graph?.nodes || []).find((x) => x.id === nid);
    if (n) { n.config = n.config || {}; patchFn(n.config); }
  }).catch((e) => toast(e.message));
}

export function renderRouterNodeConfig(router) {
  if (!ui.topologyRouterNodeCfgId) return "";
  const node = (router.graph?.nodes || []).find((n) => n.id === ui.topologyRouterNodeCfgId);
  if (!node) return "";
  const edges = graphOutEdges(router, node.id);
  const cfg = node.config || {};
  const glyph = { schedule: "⏱", weighted: "⚖", roundRobin: "🔁", failover: "⚡", queue: "⏳", requestType: "🔀", requestSize: "📏" }[node.type] || "•";
  const edgeOpt = (sel) => `<option value="">(first connection)</option>` +
    edges.map((e) => `<option value="${escapeHtml(e.id)}"${e.id === sel ? " selected" : ""}>${escapeHtml(edgeTargetLabel(router, e))}</option>`).join("");
  let body;
  if (!edges.length && node.type !== "queue") {
    body = `<div class="rw-cfg-hint">Connect this node to one or more targets first — drag from its right port to a rule or output.</div>`;
  } else if (node.type === "weighted") {
    body = `<div class="rw-cfg-hint">Split traffic across connections by weight.</div>`
      + edges.map((e) => {
        const w = (cfg.weights || []).find((x) => x.edge === e.id);
        return `<label class="rw-cfg-row"><span class="rw-cfg-tgt" title="${escapeHtml(edgeTargetLabel(router, e))}">${escapeHtml(edgeTargetLabel(router, e))}</span><input class="rw-cfg-in rw-cfg-num" type="number" min="0" max="100" data-cfg-weight="${escapeHtml(e.id)}" value="${w ? w.pct : 0}"><span class="rw-cfg-unit">%</span></label>`;
      }).join("");
  } else if (node.type === "failover") {
    const order = (cfg.order && cfg.order.length ? cfg.order.filter((id) => edges.some((e) => e.id === id)) : edges.map((e) => e.id));
    body = `<div class="rw-cfg-hint">Try connections in order; spill to the next when the target is busy.</div><ol class="rw-cfg-order">`
      + order.map((id, i) => {
        const e = edges.find((x) => x.id === id);
        return `<li data-cfg-ord-id="${escapeHtml(id)}"><span class="rw-cfg-tgt">${escapeHtml(edgeTargetLabel(router, e))}</span><span class="rw-cfg-ord"><button class="icon-action compact" type="button" data-cfg-up="${escapeHtml(id)}" ${i === 0 ? "disabled" : ""}>↑</button><button class="icon-action compact" type="button" data-cfg-down="${escapeHtml(id)}" ${i === order.length - 1 ? "disabled" : ""}>↓</button></span></li>`;
      }).join("") + `</ol>`;
  } else if (node.type === "schedule") {
    body = `<div class="rw-cfg-hint">Schedule is configured directly on the canvas node — use the grid and palette there.</div>`;
  } else if (node.type === "queue") {
    const num = (key, val, min, max, ph) =>
      `<input class="rw-cfg-in rw-cfg-num" type="number" min="${min}" max="${max}" data-cfg-q="${key}" value="${val === null || val === undefined ? "" : val}" placeholder="${ph || ""}">`;
    body = `<div class="rw-cfg-hint">Wire the <strong>main</strong> and <strong>spill</strong> ports on the node itself (drag a cable from each). Requests wait for a slot on the main upstream; at <strong>overflow%</strong> of the client's timeout they divert to the spill target. No priorities here — pure FIFO.</div>`
      + `<label class="rw-cfg-row"><span class="rw-cfg-tgt" title="At this % of the client's wait-timeout, redirect to the spill path">overflow at</span>${num("spillPct", cfg.spillPct ?? 20, 0, 100)}<span class="rw-cfg-unit">%</span></label>`
      + `<label class="rw-cfg-row"><span class="rw-cfg-tgt" title="After a request finishes, reserve the slot for the same agent's follow-up calls">reserve for agent</span>${num("stickySlotSec", cfg.stickySlotSec ?? 20, 0, 120)}<span class="rw-cfg-unit">s</span></label>`;
  } else {
    body = `<div class="rw-cfg-hint">Round-robin rotates evenly across all ${edges.length} connection(s). No configuration needed.</div>`;
  }
  return `
    <div class="rw-node-cfg" data-rw-node-cfg>
      <div class="rw-node-cfg-head"><strong>${glyph} ${escapeHtml(node.type)}</strong><button class="icon-action compact" type="button" data-cfg-close aria-label="Close">×</button></div>
      <div class="rw-node-cfg-body">${body}</div>
    </div>`;
}

export function renderTopologyCanvasModal() {
  if (!ui.topologyCanvasRouterId) return "";
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
  if (!router) return "";
  const nodes = canvasNodes(router);
  const nodeHtml = nodes.map((n) => {
    const pos = _cvPos[n.id] || n.fixed || { x: n.dx, y: n.dy };
    return `<div class="cv-node cv-${n.type} ${n.cls || ""}" data-cv-node="${escapeHtml(n.id)}" style="left:${pos.x}px;top:${pos.y}px">${n.html}</div>`;
  }).join("");
  const tf = `translate(${_cvView.tx}px, ${_cvView.ty}px) scale(${_cvView.scale})`;
  return `
    <div class="topology-policy-overlay" data-topology-canvas-overlay>
      <div class="topology-policy-modal canvas-modal">
        <div class="topology-policy-head">
          <strong>⤢ ${escapeHtml(t("topologyRouterTitle"))} — canvas</strong>
          <span class="muted" style="font-size:11px">drag nodes · scroll = zoom · drag background = pan</span>
          <span class="topology-policy-head-actions">
            <button class="icon-action compact" type="button" data-topology-canvas-close aria-label="Close" title="Close">×</button>
          </span>
        </div>
        <div class="cv-viewport" data-cv-viewport>
          <div class="cv-world" data-cv-world style="transform:${tf}">
            <svg class="cv-svg" data-cv-svg width="4000" height="3000" viewBox="0 0 4000 3000"></svg>
            ${nodeHtml}
          </div>
        </div>
      </div>
    </div>`;
}

export function _cvPath(a, b, active) {
  if (!a || !b) return "";
  const mx = (a.x + b.x) / 2;
  return `<path d="M ${a.x} ${a.y} C ${mx} ${a.y}, ${mx} ${b.y}, ${b.x} ${b.y}" class="cv-cable ${active ? "active" : ""}" fill="none"></path>`;
}

// Sync port dots on the Servers canvas block.
// Dots are direct children of the block (position:absolute, left:-9px) so they
// straddle the left border just like .cv-port.in on regular nodes.
// Y is computed from getBoundingClientRect() divided by scale so it stays correct
// when the body is scrolled or the canvas is zoomed.
export function _cvSyncServersPortDots() {
  const world = document.querySelector("[data-cv-world]");
  if (!world) return;
  const block = world.querySelector(".cv-servers-block");
  if (!block) return;
  const blockRect = block.getBoundingClientRect();
  const scale = _cvView.scale || 1;
  const seen = new Set();
  block.querySelectorAll("[data-router-out-row]").forEach((row) => {
    const id = row.dataset.routerOutRow;
    if (!id) return;
    const rowRect = row.getBoundingClientRect();
    if (rowRect.height < 1) return;      // collapsed / hidden accordion row
    seen.add(id);
    const key = `out:${id}`;
    // Find existing dot or create one as a direct child of the block.
    let dot = block.querySelector(`:scope > [data-cv-out-port="${CSS.escape(key)}"]`);
    if (!dot) {
      dot = document.createElement("span");
      dot.className = "cv-port in";
      dot.dataset.cvNode = key;
      dot.dataset.cvOutPort = key;
      dot.title = "Drop a cable here to route to this output";
      block.appendChild(dot);
    }
    // Position in block's coordinate space (world units = CSS px at scale 1).
    // yBlock is already the row's vertical center, so override the .cv-port class's
    // "margin-top: -8px" to prevent a visual/anchor mismatch.
    const yBlock = (rowRect.top - blockRect.top + rowRect.height / 2) / scale;
    dot.style.top = yBlock + "px";
    dot.style.marginTop = "0";
  });
  // Remove stale dots (output no longer in list or accordion is fully collapsed).
  block.querySelectorAll(":scope > [data-cv-out-port]").forEach((dot) => {
    const id = dot.dataset.cvOutPort?.replace(/^out:/, "");
    if (id && !seen.has(id)) dot.remove();
  });
}

// Sync port dots on the Inputs canvas block (mirror of _cvSyncServersPortDots).
// Dots are direct children of the block (position:absolute, right:-9px) so they
// straddle the RIGHT border just like .cv-port.out on regular nodes.
// Y is computed from getBoundingClientRect() so it tracks correctly when scrolled.
export function _cvSyncInputsBlockPortDots() {
  const world = document.querySelector("[data-cv-world]");
  if (!world) return;
  const block = world.querySelector(".cv-inputs-block");
  if (!block) return;
  const blockRect = block.getBoundingClientRect();
  const scale = _cvView.scale || 1;
  const seen = new Set();
  block.querySelectorAll("[data-cv-in-row]").forEach((row) => {
    const ref = row.dataset.cvInRow;
    if (!ref) return;
    const rowRect = row.getBoundingClientRect();
    if (rowRect.height < 1) return;
    seen.add(ref);
    let dot = block.querySelector(`:scope > .cv-port.out[data-cv-ref="${CSS.escape(ref)}"]`);
    if (!dot) {
      dot = document.createElement("span");
      dot.className = "cv-port out";
      dot.dataset.cvRef = ref;
      dot.title = "Drag to route this port →";
      block.appendChild(dot);
    }
    const yBlock = (rowRect.top - blockRect.top + rowRect.height / 2) / scale;
    dot.style.top = yBlock + "px";
    dot.style.marginTop = "0";
  });
  block.querySelectorAll(":scope > .cv-port.out[data-cv-ref]").forEach((dot) => {
    if (!seen.has(dot.dataset.cvRef)) dot.remove();
  });
}

export function drawCanvasConnectors() {
  // Always sync block port dots before drawing — ensures they exist and
  // are correctly positioned even if the initial bind ran before layout was ready.
  _cvSyncInputsBlockPortDots();
  _cvSyncServersPortDots();
  const world = document.querySelector("[data-cv-world]");
  const svg = document.querySelector("[data-cv-svg]");
  if (!world || !svg) return;
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
  if (!router) { svg.innerHTML = ""; return; }
  const graph = router.graph || { nodes: [], edges: [] };
  // Queue nodes colour/anchor their admit/spill cables. admit falls back to the first
  // non-spill edge (matches the engine + heals pre-role-port graphs). queueFroms lets us
  // anchor any stray queue edge at the main port instead of the node centre.
  const qRole = {};
  const queueFroms = new Set();
  (graph.nodes || []).forEach((n) => {
    if (n.type !== "queue") return;
    const ref = `rule:${n.id}`;
    queueFroms.add(ref);
    const c = n.config || {};
    const outs = (graph.edges || []).filter((e) => e.from === ref);
    let admitId = (c.admitEdge && outs.some((e) => e.id === c.admitEdge)) ? c.admitEdge : null;
    if (!admitId) { const f = outs.find((e) => e.id !== c.spillEdge); if (f) admitId = f.id; }
    if (admitId) qRole[admitId] = "admit";
    if (c.spillEdge) qRole[c.spillEdge] = "spill";
  });
  // Schedule nodes: map ref → outputs so we can distribute untagged edges by index.
  const schedOutputsMap = {}; // `rule:${nid}` -> outputs[]
  (graph.nodes || []).forEach((n) => {
    if (n.type === "schedule") schedOutputsMap[`rule:${n.id}`] = (n.config?.outputs || []);
  });
  // Node rectangles (world coords) — cables route around any they don't terminate on.
  const nodeRects = [...world.querySelectorAll("[data-cv-node]")].map((el) => {
    let x = 0, y = 0, e = el;
    while (e && !(e.classList && e.classList.contains("cv-world"))) { x += e.offsetLeft; y += e.offsetTop; e = e.offsetParent; }
    return { x, y, w: el.offsetWidth, h: el.offsetHeight };
  });
  // First pass: resolve each edge's two anchor points + its CSS class.
  const cables = [];
  const seen = new Set();
  (graph.edges || []).forEach((e) => {
    const from = String(e.from), to = String(e.to);
    const k = `${from}->${to}`;
    if (seen.has(k)) return;
    seen.add(k);
    // Queue admit/spill edges anchor at their dedicated role port.
    // Schedule node edges anchor at their per-output port (data-cv-sched-port).
    let a = null;
    const role = qRole[e.id] || (queueFroms.has(from) ? "admit" : null);
    if (role) {
      const p = world.querySelector(`[data-cv-node="${CSS.escape(from)}"] .cv-port.out[data-cv-qrole="${role}"]`);
      if (p) a = _cvWorldPoint(p, "right");
    }
    if (!a && e.schedPortId) {
      const p = world.querySelector(`[data-cv-node="${CSS.escape(from)}"] [data-cv-sched-port="${CSS.escape(e.schedPortId)}"]`);
      if (p) a = _cvWorldPoint(p, "right");
    }
    // Fallback for schedule edges that predate schedPortId: distribute untagged edges
    // across chip ports by index so cables fan out from distinct points.
    if (!a && schedOutputsMap[from]) {
      const nodeEl = world.querySelector(`[data-cv-node="${CSS.escape(from)}"]`);
      if (nodeEl) {
        const untagged = (graph.edges || []).filter((e2) => String(e2.from) === from && !e2.schedPortId);
        const idx = untagged.findIndex((e2) => e2.id === e.id);
        const ports = [...nodeEl.querySelectorAll("[data-cv-sched-port]")];
        const p = ports[idx >= 0 ? idx : 0] || ports[0];
        if (p) a = _cvWorldPoint(p, "right");
      }
    }
    if (!a) a = _cvAnchorFrom(from);
    // _cvAnchorTo handles "out:" refs by finding [data-cv-out-port] inside Servers block.
    const b = _cvAnchorTo(to);
    if (!a || !b) return;
    let cls = "cv-cable";
    if (qRole[e.id]) cls += ` cv-cable-${qRole[e.id]}`;
    if (_cvDrag && _cvDrag.kind === "rewire" && from === _cvDrag.id && to === _cvDrag.oldTo) cls += " removing";
    else if (_cvDrag && _cvDrag.kind === "connect" && _cvDrag.replaceFrom && from === _cvDrag.replaceFrom) cls += " removing";
    cables.push({ a, b, cls, to, edgeKey: `${escapeHtml(from)}|${escapeHtml(to)}` });
  });
  // Route each cable: obstacles = node rects that contain NEITHER endpoint (so a cable
  // never avoids its own source/target block). Then collect every vertical segment so a
  // horizontal run can hop over the OTHERS where they cross.
  const _pad = 4;
  const _contains = (r, p) => p.x > r.x - _pad && p.x < r.x + r.w + _pad && p.y > r.y - _pad && p.y < r.y + r.h + _pad;
  cables.forEach((c) => {
    const obstacles = nodeRects.filter((r) => !_contains(r, c.a) && !_contains(r, c.b));
    c.pts = _cvOrthoPts(c.a, c.b, 12, obstacles);
  });
  const verts = [];
  cables.forEach((c, i) => {
    for (let k = 1; k < c.pts.length; k++) {
      const [px, py] = c.pts[k - 1], [cx, cy] = c.pts[k];
      if (Math.abs(cx - px) < 0.6 && Math.abs(cy - py) > 0.6) verts.push({ x: cx, y1: Math.min(py, cy), y2: Math.max(py, cy), idx: i });
    }
  });
  const paths = [];
  cables.forEach((c, i) => {
    const crossVerts = verts.filter((v) => v.idx !== i);
    const mx = (c.a.x + c.b.x) / 2, my = (c.a.y + c.b.y) / 2;
    paths.push(`<g class="cv-edge-grp">`
      + `<path data-cv-edge="${c.edgeKey}" d="${_cvCableD(c.pts, 12, crossVerts)}" class="${c.cls}" fill="none"><title>Drag to re-point · ✕ to delete</title></path>`
      + `<g class="cv-edge-x" data-cv-edge-del="${c.edgeKey}" transform="translate(${mx},${my})">`
      + `<circle r="8"></circle><path d="M -3.2 -3.2 L 3.2 3.2 M 3.2 -3.2 L -3.2 3.2"></path>`
      + `</g></g>`);
  });
  // Junction dots: where a horizontal run of one cable meets a vertical segment of a
  // SIBLING (same destination), the wires really merge — mark the joint with a dot.
  const horiz = [];
  cables.forEach((c, i) => {
    for (let k = 1; k < c.pts.length; k++) {
      const [px, py] = c.pts[k - 1], [cx, cy] = c.pts[k];
      if (Math.abs(cy - py) < 0.6 && Math.abs(cx - px) > 0.6) horiz.push({ y: cy, x1: Math.min(px, cx), x2: Math.max(px, cx), idx: i });
    }
  });
  const junctions = new Map();
  const EPS = 2.5;
  horiz.forEach((h) => {
    verts.forEach((v) => {
      if (v.idx === h.idx || cables[v.idx].to !== cables[h.idx].to) return;
      // Слияние = T-примыкание: вертикаль ЗАКАНЧИВАЕТСЯ на горизонтали (или
      // горизонталь на вертикали). Сквозное пересечение — это мост, не точка.
      const vEndsOnH = (Math.abs(h.y - v.y1) <= EPS || Math.abs(h.y - v.y2) <= EPS)
        && v.x > h.x1 + EPS && v.x < h.x2 - EPS;
      const hEndsOnV = (Math.abs(v.x - h.x1) <= EPS || Math.abs(v.x - h.x2) <= EPS)
        && h.y > v.y1 + EPS && h.y < v.y2 - EPS;
      if (!vEndsOnH && !hEndsOnV) return;
      const bA = cables[h.idx].b, bB = cables[v.idx].b;
      if (Math.hypot(v.x - bA.x, h.y - bA.y) < 16 || Math.hypot(v.x - bB.x, h.y - bB.y) < 16) return; // порт и так с точкой
      junctions.set(`${Math.round(v.x)},${Math.round(h.y)}`, [v.x, h.y]);
    });
  });
  junctions.forEach(([x, y]) => paths.push(`<circle class="cv-junction" cx="${Math.round(x * 10) / 10}" cy="${Math.round(y * 10) / 10}" r="6.5"></circle>`));
  if (_cvDrag && (_cvDrag.kind === "connect" || _cvDrag.kind === "rewire") && _cvDrag.cur) {
    paths.push(`<path d="${_cvPathD(_cvDrag.from, _cvDrag.cur)}" class="cv-cable connecting" fill="none"></path>`);
  }
  svg.innerHTML = paths.filter(Boolean).join("");
}

// World-space point at an element's left/right/center edge (sums offsets up to cv-world,
// so it works for ports nested inside nodes too).
export function _cvWorldPoint(el, side) {
  let x = 0, y = 0, e = el;
  while (e && !(e.classList && e.classList.contains("cv-world"))) { x += e.offsetLeft; y += e.offsetTop; e = e.offsetParent; }
  if (side === "right")  return { x: x + el.offsetWidth, y: y + el.offsetHeight / 2 };
  if (side === "center") return { x: x + el.offsetWidth / 2, y: y + el.offsetHeight / 2 };
  return { x, y: y + el.offsetHeight / 2 }; // "left"
}

// World point of an edge's source (out) / target (in) anchor, by ref. Shared by the
// connector renderer and the rewire/connect drags.
export function _cvAnchorFrom(ref) {
  const world = document.querySelector("[data-cv-world]");
  if (!world) return null;
  if (ref.startsWith("in:")) {
    // Dots are created by _cvSyncInputsBlockPortDots as direct children of the inputs block.
    const port = world.querySelector(`.cv-port.out[data-cv-ref="${CSS.escape(ref)}"]`);
    return port ? _cvWorldPoint(port, "right") : null;
  }
  const node = world.querySelector(`[data-cv-node="${CSS.escape(ref)}"]`);
  return node ? _cvWorldPoint(node, "right") : null;
}
export function _cvAnchorTo(ref) {
  const world = document.querySelector("[data-cv-world]");
  if (!world) return null;
  if (ref.startsWith("out:")) {
    // Output ports live inside the Servers canvas block as [data-cv-out-port] spans.
    const port = world.querySelector(`[data-cv-out-port="${CSS.escape(ref)}"]`);
    return port ? _cvWorldPoint(port, "center") : null;
  }
  const node = world.querySelector(`[data-cv-node="${CSS.escape(ref)}"]`);
  return node ? _cvWorldPoint(node.querySelector(".cv-port.in") || node, "left") : null;
}

// Path `d` attribute only (so callers can add their own attributes).
// Path d-string through a polyline of [x,y] points, with rounded corners (radius R,
// clamped per-corner so it never overshoots a short segment). Circuit-schematic look.
export function _cvRoundedPolyD(pts, R) {
  if (!pts || pts.length < 2) return "";
  const f = (n) => (Math.round(n * 10) / 10);
  let d = `M ${f(pts[0][0])} ${f(pts[0][1])}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1], [cx, cy] = pts[i], [nx, ny] = pts[i + 1];
    const l1 = Math.hypot(cx - px, cy - py) || 1, l2 = Math.hypot(nx - cx, ny - cy) || 1;
    const r = Math.min(R, l1 / 2, l2 / 2);
    const a1x = cx - (cx - px) / l1 * r, a1y = cy - (cy - py) / l1 * r;
    const a2x = cx + (nx - cx) / l2 * r, a2y = cy + (ny - cy) / l2 * r;
    d += ` L ${f(a1x)} ${f(a1y)} Q ${f(cx)} ${f(cy)} ${f(a2x)} ${f(a2y)}`;
  }
  const last = pts[pts.length - 1];
  d += ` L ${f(last[0])} ${f(last[1])}`;
  return d;
}

// Orthogonal corner points from out-port `a` (exits right) to in-port `b` (enters from
// the left). Forward (b right of a) → 3-segment elbow via the mid-x. Backward / too
// close → a C-route: right stub, vertical to mid-y, left, vertical, right stub into b.
export function _cvOrthoPts(a, b, R, obstacles) {
  if (Math.abs(b.y - a.y) < 0.6) return [[a.x, a.y], [b.x, b.y]];
  if (b.x - a.x >= 2 * R + 12) {
    let mx = (a.x + b.x) / 2;
    if (obstacles && obstacles.length) mx = _cvClearMidX(mx, a, b, obstacles, R);
    return [[a.x, a.y], [mx, a.y], [mx, b.y], [b.x, b.y]];
  }
  const s = 30, my = (a.y + b.y) / 2;
  return [[a.x, a.y], [a.x + s, a.y], [a.x + s, my], [b.x - s, my], [b.x - s, b.y], [b.x, b.y]];
}
// Nudge the vertical mid-segment's x out of any block it would pass through, into the
// nearest clear channel (clamped between the two ports). Best-effort — gives up if no
// clear x exists in range. Keeps cables from hiding under nodes.
export function _cvClearMidX(mx, a, b, obstacles, R) {
  const ylo = Math.min(a.y, b.y), yhi = Math.max(a.y, b.y), pad = 16;
  const minX = a.x + R + 6, maxX = b.x - R - 6;
  if (maxX <= minX) return mx;
  const blocks = obstacles.filter((o) => o.y - pad < yhi && o.y + o.h + pad > ylo);
  const hits = (x) => blocks.some((o) => o.x - pad < x && x < o.x + o.w + pad);
  if (!hits(mx)) return mx;
  const inside = blocks.filter((o) => o.x - pad < mx && mx < o.x + o.w + pad);
  const right = Math.min(maxX, Math.max(...inside.map((o) => o.x + o.w)) + pad);
  const left = Math.max(minX, Math.min(...inside.map((o) => o.x)) - pad);
  if (right <= maxX && !hits(right)) return right;
  if (left >= minX && !hits(left)) return left;
  return mx;
}

export function _cvPathD(a, b) {
  const R = 12;
  return _cvRoundedPolyD(_cvOrthoPts(a, b, R), R);
}

// Cable through its orthogonal polyline with rounded corners AND a small "hop" arc
// wherever a horizontal run crosses one of `crossVerts` (the vertical segments of OTHER
// cables) — the circuit-schematic jump-over so crossing wires read as not-connected.
export function _cvCableD(pts, R, crossVerts) {
  if (!pts || pts.length < 2) return "";
  const f = (n) => Math.round(n * 10) / 10;
  const HR = 11;
  let d = `M ${f(pts[0][0])} ${f(pts[0][1])}`;
  let pen = [pts[0][0], pts[0][1]];
  const lineTo = (x, y) => {
    if (crossVerts && crossVerts.length && Math.abs(y - pen[1]) < 0.6 && Math.abs(x - pen[0]) > 0.6) {
      const yv = pen[1], x1 = pen[0], dir = Math.sign(x - x1);
      const lo = Math.min(x1, x) + HR, hi = Math.max(x1, x) - HR;
      const hops = crossVerts
        .filter((v) => v.y1 + 2 < yv && yv < v.y2 - 2 && v.x > lo && v.x < hi)
        .map((v) => v.x).sort((p, q) => dir * (p - q));
      let prev = -Infinity;
      for (const hx of hops) {
        if (Math.abs(hx - prev) < HR * 2) continue;  // merge near-coincident crossings
        prev = hx;
        d += ` L ${f(hx - dir * HR)} ${f(yv)} A ${HR} ${HR} 0 0 ${dir > 0 ? 1 : 0} ${f(hx + dir * HR)} ${f(yv)}`;
      }
    }
    d += ` L ${f(x)} ${f(y)}`;
    pen = [x, y];
  };
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1], [cx, cy] = pts[i], [nx, ny] = pts[i + 1];
    const l1 = Math.hypot(cx - px, cy - py) || 1, l2 = Math.hypot(nx - cx, ny - cy) || 1;
    const r = Math.min(R, l1 / 2, l2 / 2);
    lineTo(cx - (cx - px) / l1 * r, cy - (cy - py) / l1 * r);
    const a2x = cx + (nx - cx) / l2 * r, a2y = cy + (ny - cy) / l2 * r;
    d += ` Q ${f(cx)} ${f(cy)} ${f(a2x)} ${f(a2y)}`;
    pen = [a2x, a2y];
  }
  lineTo(pts[pts.length - 1][0], pts[pts.length - 1][1]);
  return d;
}

// Convert a world-space point to rw-cols-relative coordinates (for overlay SVG).
// Uses the cv-viewport's screen position + current pan/zoom transform.
export function _cvWorldToOverlay(a) {
  const vp = document.querySelector("[data-cv-viewport]");
  const cols = document.querySelector("[data-rw-cols]");
  if (!vp || !cols) return null;
  const vpR = vp.getBoundingClientRect();
  const colsR = cols.getBoundingClientRect();
  return {
    x: a.x * _cvView.scale + _cvView.tx + vpR.left - colsR.left,
    y: a.y * _cvView.scale + _cvView.ty + vpR.top - colsR.top,
  };
}

// Get rw-cols-relative position of a panel output handle.
// outId = the full "out:cb:gpt-5.4-mini" value (matches data-cv-panel-out exactly).
export function _cvPanelAnchor(outId) {
  // Use unescaped value in a quoted CSS attribute selector — colons/dots are safe.
  const handle = document.querySelector(`[data-cv-panel-out="${outId}"]`);
  const cols = document.querySelector("[data-rw-cols]");
  if (!handle || !cols) return null;
  const hr = handle.getBoundingClientRect();
  const cr = cols.getBoundingClientRect();
  if (!hr.width && !hr.height) return null;   // element not visible / not laid out
  return { x: hr.left + hr.width / 2 - cr.left, y: (hr.top + hr.bottom) / 2 - cr.top };
}

export function _cvApplyView() {
  const world = document.querySelector("[data-cv-world]");
  if (world) world.style.transform = `translate(${_cvView.tx}px, ${_cvView.ty}px) scale(${_cvView.scale})`;
}
export function _cvClientToWorld(cx, cy) {
  const vp = document.querySelector("[data-cv-viewport]");
  const r = vp ? vp.getBoundingClientRect() : { left: 0, top: 0 };
  return { x: (cx - r.left - _cvView.tx) / _cvView.scale, y: (cy - r.top - _cvView.ty) / _cvView.scale };
}
export function _cvOnMove(e) {
  if (!_cvDrag) return;
  if (_cvDrag.kind === "node") {
    const x = _cvDrag.ox + (e.clientX - _cvDrag.sx) / _cvView.scale;
    const y = _cvDrag.oy + (e.clientY - _cvDrag.sy) / _cvView.scale;
    _cvDrag.node.style.left = `${x}px`;
    _cvDrag.node.style.top = `${y}px`;
    _cvPos[_cvDrag.id] = { x: Math.round(x), y: Math.round(y) };
    drawCanvasConnectors();
  } else if (_cvDrag.kind === "pan") {
    _cvView.tx = _cvDrag.tx + (e.clientX - _cvDrag.sx);
    _cvView.ty = _cvDrag.ty + (e.clientY - _cvDrag.sy);
    _cvApplyView();
  } else if (_cvDrag.kind === "connect" || _cvDrag.kind === "rewire") {
    _cvDrag.cur = _cvClientToWorld(e.clientX, e.clientY);
    const over = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    document.querySelectorAll(".cv-drop-ok").forEach((n) => { if (n !== over) n.classList.remove("cv-drop-ok"); });
    if (over && /^(rule:|out:)/.test(over.dataset.cvNode || "")) over.classList.add("cv-drop-ok");
    drawCanvasConnectors();
  } else if (_cvDrag.kind === "panelwire") {
    _cvShowGhost(e.clientX, e.clientY, _cvDrag.label);
    const over = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    document.querySelectorAll(".cv-drop-ok").forEach((n) => { if (n !== over) n.classList.remove("cv-drop-ok"); });
    if (over && /^(rule:|out:)/.test(over.dataset.cvNode || "")) over.classList.add("cv-drop-ok");
  }
}
export function _cvShowGhost(x, y, label) {
  let g = document.getElementById("cvGhost");
  if (!g) { g = document.createElement("div"); g.id = "cvGhost"; g.className = "cv-ghost"; document.body.appendChild(g); }
  g.textContent = `⠿ ${label}`;
  g.style.left = `${x}px`; g.style.top = `${y}px`;
}
export function _cvHideGhost() { document.getElementById("cvGhost")?.remove(); }
export function _cvOnUp(e) {
  if (!_cvDrag) return;
  if (_cvDrag.kind === "node") {
    _cvDrag.node.classList.remove("dragging");
    if (String(_cvDrag.id).startsWith("rule:")) {
      // Rule-node position is real data → persist to router.graph.
      const nid = _cvDrag.id.slice(5), pos = _cvPos[_cvDrag.id];
      if (pos) saveRouters((routers) => {
        const n = (routerById(routers, ui.topologyCanvasRouterId)?.graph?.nodes || []).find((x) => x.id === nid);
        if (n) { n.x = pos.x; n.y = pos.y; }
      }).catch(() => {});
    } else {
      canvasSavePositions(ui.topologyCanvasRouterId);
    }
  } else if (_cvDrag.kind === "connect") {
    document.querySelectorAll(".cv-node.cv-drop-ok").forEach((n) => n.classList.remove("cv-drop-ok"));
    const tgt = e && document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    if (tgt && /^(rule:|out:)/.test(tgt.dataset.cvNode || "") && tgt.dataset.cvNode !== _cvDrag.id) addGraphEdge(_cvDrag.id, tgt.dataset.cvNode, _cvDrag.qrole, _cvDrag.schedPortId);
    _cvDrag = null;
    drawCanvasConnectors();
    return;
  } else if (_cvDrag.kind === "rewire") {
    document.querySelectorAll(".cv-node.cv-drop-ok").forEach((n) => n.classList.remove("cv-drop-ok"));
    const tgt = e && document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    if (tgt && /^(rule:|out:)/.test(tgt.dataset.cvNode || "")) rewireGraphEdge(_cvDrag.id, _cvDrag.oldTo, tgt.dataset.cvNode);
    _cvDrag = null;
    drawCanvasConnectors();
    return;
  } else if (_cvDrag.kind === "panelwire") {
    _cvHideGhost();
    document.querySelectorAll(".cv-node.cv-drop-ok").forEach((n) => n.classList.remove("cv-drop-ok"));
    const tgt = e && document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    if (tgt && /^(rule:|out:)/.test(tgt.dataset.cvNode || "")) addGraphEdge(_cvDrag.ref, tgt.dataset.cvNode);
    _cvDrag = null;
    return;
  }
  document.querySelector("[data-cv-viewport]")?.classList.remove("panning");
  _cvDrag = null;
}
export let _cvWindowBound = false;

export function bindCanvasInteractions() {
  const viewport = document.querySelector("[data-cv-viewport]");
  const world = document.querySelector("[data-cv-world]");
  if (!viewport || !world) return;
  if (!_cvWindowBound) {
    _cvWindowBound = true;
    window.addEventListener("pointermove", _cvOnMove);
    window.addEventListener("pointerup", _cvOnUp);
  }
  // Edit-in-canvas controls (stop pointerdown so they don't start a node drag).
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
  world.querySelectorAll(".cv-act").forEach((el) => el.addEventListener("pointerdown", (e) => e.stopPropagation()));
  world.querySelectorAll("[data-cv-setdefault]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    const out = b.dataset.cvSetdefault;
    saveRouters((routers) => { const s = routerById(routers, ui.topologyCanvasRouterId); if (s) { s.rules = s.rules || {}; s.rules.default = out; } }).catch((err) => toast(err.message));
  }));
  world.querySelector("[data-cv-failover]")?.addEventListener("click", (e) => {
    e.stopPropagation();
    saveRouters((routers) => {
      const s = routerById(routers, ui.topologyCanvasRouterId);
      if (!s) return;
      s.rules = s.rules || {};
      const on = (s.rules.failover || []).length > 0;
      if (on) { s.rules.failover = []; return; }
      const ids = (s.outputs || []).map((o) => o.id);
      const def = s.rules.default;
      s.rules.failover = def && ids.includes(def) ? [def, ...ids.filter((x) => x !== def)] : ids;
    }).catch((err) => toast(err.message));
  });
  world.querySelectorAll("[data-cv-pin]").forEach((selEl) => selEl.addEventListener("change", () => {
    const key = selEl.dataset.cvPin, out = selEl.value;
    const proxyIds = (topology?.proxies || []).filter((p) => (router?.inputs || []).includes(p.id) && canvasClientKey(p) === key).map((p) => p.id);
    saveRouters((routers) => {
      const s = routerById(routers, ui.topologyCanvasRouterId);
      if (!s) return;
      s.rules = s.rules || {};
      let bs = (s.rules.bySource || []).filter((r) => !proxyIds.includes(r.proxyId));
      if (out) proxyIds.forEach((pid) => bs.push({ proxyId: pid, clientId: "", output: out }));
      s.rules.bySource = bs;
    }).catch((err) => toast(err.message));
  }));
  // Stage D: drag a proxy from the left panel onto a canvas node to route it.
  document.querySelectorAll(".rw-proxy-drag").forEach((h) => {
    h.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      _cvDrag = { kind: "panelwire", ref: h.dataset.wireRef, label: h.dataset.wireLabel || h.dataset.wireRef };
      _cvShowGhost(e.clientX, e.clientY, _cvDrag.label);
    });
  });
  // Stage C graph editing: palette add, node delete, port-drag connect, edge delete.
  document.querySelectorAll("[data-cv-add]").forEach((b) => b.addEventListener("click", () => addRuleNode(b.dataset.cvAdd)));
  world.querySelectorAll("[data-cv-delnode]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); deleteRuleNode(b.dataset.cvDelnode); }));
  // Per-input wait-budget override on client nodes. Don't let them start a node drag.
  world.querySelectorAll(".cv-in-wait-in[data-cv-wait]").forEach((inp) => {
    inp.addEventListener("pointerdown", (e) => e.stopPropagation());
    inp.addEventListener("change", () => {
      const pid = inp.dataset.cvWait;
      const raw = inp.value.trim();
      const val = raw === "" ? 0 : Math.max(0, Math.min(86400, parseInt(raw, 10) || 0));
      saveRouters((routers) => {
        const s = routerById(routers, ui.topologyCanvasRouterId);
        if (!s) return;
        s.graph = s.graph || { nodes: [], edges: [] };
        s.graph.inputs = s.graph.inputs || {};
        if (val > 0) s.graph.inputs[pid] = { ...(s.graph.inputs[pid] || {}), clientTimeoutSeconds: val };
        else delete s.graph.inputs[pid];   // 0/empty → fall back to the auto-synced value
      }).catch((e) => toast(e.message));
    });
  });
  // Embeddings slot — the one global /v1/embeddings target. Don't start a node drag.
  world.querySelectorAll("[data-cv-embed-out]").forEach((sel) => {
    sel.addEventListener("pointerdown", (e) => e.stopPropagation());
    sel.addEventListener("change", () => {
      const val = sel.value;
      saveRouters((routers) => {
        const s = routerById(routers, ui.topologyCanvasRouterId);
        if (!s) return;
        s.rules = s.rules || {};
        s.rules.embeddingsOutput = val;
      }).catch((e) => toast(e.message));
    });
  });
  // Inline queue-node param inputs (on the card itself). Don't let them start a node drag.
  world.querySelectorAll(".cv-q-cfg-in[data-cv-q]").forEach((inp) => {
    inp.addEventListener("pointerdown", (e) => e.stopPropagation());
    inp.addEventListener("change", () => {
      const nodeEl = inp.closest("[data-cv-node]");
      const nid = nodeEl && String(nodeEl.dataset.cvNode || "").startsWith("rule:") ? nodeEl.dataset.cvNode.slice(5) : "";
      if (!nid) return;
      const key = inp.dataset.cvQ, raw = inp.value.trim();
      saveNodeConfig(nid, (cfg) => {
        if (key === "maxSlots") { cfg.maxSlots = raw === "" ? null : Math.max(1, Math.min(64, parseInt(raw, 10) || 1)); return; }
        const lo = Number(inp.min || 0), hi = Number(inp.max || 100);
        cfg[key] = Math.max(lo, Math.min(hi, parseInt(raw, 10) || 0));
      });
    });
  });
  // Delegated port drag: covers both static inline ports AND dynamically-created dots
  // from _cvSyncInputsBlockPortDots / _cvSyncServersPortDots that are appended after bind.
  world.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const port = e.target.closest(".cv-port.out");
    if (!port) return;
    e.stopPropagation(); e.preventDefault();
    const nodeEl = port.closest("[data-cv-node]");
    if (!nodeEl) return;
    const ref = port.dataset.cvRef || nodeEl.dataset.cvNode;   // per-port (in:<proxyId>) or node id
    const qrole = port.dataset.cvQrole || null;
    const schedPortId = port.dataset.cvSchedPort || null;
    const from = _cvWorldPoint(port, "right");
    _cvDrag = { kind: "connect", id: ref, qrole, schedPortId, from, cur: from, replaceFrom: _isSingleOut(ref) ? ref : null };
  });
  // Delegated on the SVG (paths are re-created every redraw): grab a cable anywhere
  // along its length to re-point its target end; click the ✕ at its midpoint (shown
  // on hover) to delete it. Applies to both cv-svg (canvas) and cv-overlay-svg (panel).
  const _bindSvgEdgeEvents = (svgEl) => {
    if (!svgEl) return;
    svgEl.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest && e.target.closest("[data-cv-edge-del]")) return;
      const path = e.target.closest && e.target.closest("[data-cv-edge]");
      if (!path) return;
      e.stopPropagation(); e.preventDefault();
      const [from, to] = (path.dataset.cvEdge || "").split("|");
      if (!from || !to) return;
      const cur = _cvClientToWorld(e.clientX, e.clientY);
      _cvDrag = { kind: "rewire", id: from, oldTo: to, from: _cvAnchorFrom(from) || cur, cur };
      drawCanvasConnectors();
    });
    svgEl.addEventListener("click", (e) => {
      const del = e.target.closest && e.target.closest("[data-cv-edge-del]");
      if (!del) return;
      e.stopPropagation();
      const [a, b2] = (del.dataset.cvEdgeDel || "").split("|");
      if (a && b2) confirmDeleteGraphEdge(a, b2);
    });
  };
  _bindSvgEdgeEvents(document.querySelector("[data-cv-svg]"));

  // Sync block port dots after initial render and on body scroll. Also schedule a rAF
  // pass in case getBoundingClientRect() returned zeros before layout was complete.
  _cvSyncInputsBlockPortDots();
  _cvSyncServersPortDots();
  requestAnimationFrame(() => { _cvSyncInputsBlockPortDots(); _cvSyncServersPortDots(); drawCanvasConnectors(); });
  const serversBody = document.querySelector(".cv-servers-body");
  if (serversBody && !serversBody._cvPortSyncBound) {
    serversBody._cvPortSyncBound = true;
    serversBody.addEventListener("scroll", _cvSyncServersPortDots, { passive: true });
  }
  const inputsBody = document.querySelector(".cv-inputs-body");
  if (inputsBody && !inputsBody._cvPortSyncBound) {
    inputsBody._cvPortSyncBound = true;
    inputsBody.addEventListener("scroll", _cvSyncInputsBlockPortDots, { passive: true });
  }

  // Stage C.2: open / edit the per-node config panel.
  world.querySelectorAll("[data-cv-cfgnode]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation(); ui.topologyRouterNodeCfgId = b.dataset.cvCfgnode; renderTopology();
  }));
  const cfgPanel = document.querySelector("[data-rw-node-cfg]");
  if (cfgPanel) {
    const cid = ui.topologyRouterNodeCfgId;
    cfgPanel.querySelector("[data-cfg-close]")?.addEventListener("click", () => { ui.topologyRouterNodeCfgId = ""; renderTopology(); });
    cfgPanel.querySelectorAll("[data-cfg-match]").forEach((inp) => inp.addEventListener("change", () => {
      const cases = [...cfgPanel.querySelectorAll("[data-cfg-match]")].map((i) => ({ edge: i.dataset.cfgMatch, match: i.value.trim() })).filter((c) => c.match);
      saveNodeConfig(cid, (cfg) => { cfg.cases = cases; });
    }));
    cfgPanel.querySelector("[data-cfg-else]")?.addEventListener("change", (e) => saveNodeConfig(cid, (cfg) => { cfg.elseEdge = e.target.value; }));
    cfgPanel.querySelectorAll("[data-cfg-weight]").forEach((inp) => inp.addEventListener("change", () => {
      const weights = [...cfgPanel.querySelectorAll("[data-cfg-weight]")].map((i) => ({ edge: i.dataset.cfgWeight, pct: Math.max(0, Math.min(100, parseInt(i.value, 10) || 0)) }));
      saveNodeConfig(cid, (cfg) => { cfg.weights = weights; });
    }));
    const moveOrder = (id, dir) => {
      const ids = [...cfgPanel.querySelectorAll("[data-cfg-ord-id]")].map((el) => el.dataset.cfgOrdId);
      const i = ids.indexOf(id), j = i + dir;
      if (i < 0 || j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      saveNodeConfig(cid, (cfg) => { cfg.order = ids; });
    };
    cfgPanel.querySelectorAll("[data-cfg-up]").forEach((b) => b.addEventListener("click", () => moveOrder(b.dataset.cfgUp, -1)));
    cfgPanel.querySelectorAll("[data-cfg-down]").forEach((b) => b.addEventListener("click", () => moveOrder(b.dataset.cfgDown, 1)));
    // ── queue node (admit/spill are wired via the node's ports, not here) ──
    cfgPanel.querySelectorAll("[data-cfg-q]").forEach((inp) => inp.addEventListener("change", () => {
      const key = inp.dataset.cfgQ;
      const raw = inp.value.trim();
      saveNodeConfig(cid, (cfg) => {
        if (key === "maxSlots") { cfg.maxSlots = raw === "" ? null : Math.max(1, Math.min(64, parseInt(raw, 10) || 1)); return; }
        const lo = Number(inp.min || 0), hi = Number(inp.max || 100);
        cfg[key] = Math.max(lo, Math.min(hi, parseInt(raw, 10) || 0));
      });
    }));
  }
  // Node drag: world coords = client delta / current scale.
  world.querySelectorAll("[data-cv-node]").forEach((node) => {
    node.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest(".cv-act") || e.target.closest(".cv-port") || e.target.closest(".cv-q-cfg") || e.target.closest(".cv-in-wait") || e.target.closest(".cv-servers-body") || e.target.closest(".cv-inputs-body") || e.target.closest("[data-cv-sched-cell]") || e.target.closest(".cv-sched-row") || e.target.closest(".cv-sched-addrow")) return;   // control/port/inline-input/servers-body/inputs-body/schedule, not a drag
      e.stopPropagation();
      _cvDrag = { kind: "node", node, id: node.dataset.cvNode, sx: e.clientX, sy: e.clientY, ox: node.offsetLeft, oy: node.offsetTop };
      node.classList.add("dragging");
      e.preventDefault();
    });
  });
  // Pan when dragging the empty background.
  viewport.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest("[data-cv-node]")) return;
    _cvDrag = { kind: "pan", sx: e.clientX, sy: e.clientY, tx: _cvView.tx, ty: _cvView.ty };
    viewport.classList.add("panning");
  });
  // Wheel = zoom toward the cursor.
  viewport.addEventListener("wheel", (e) => {
    if (e.target.closest(".cv-servers-body, .cv-inputs-body, .router-prov-models")) return;
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    const old = _cvView.scale;
    const next = Math.min(2.2, Math.max(0.35, old * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
    _cvView.tx = cx - (cx - _cvView.tx) * (next / old);
    _cvView.ty = cy - (cy - _cvView.ty) * (next / old);
    _cvView.scale = next;
    _cvApplyView();
  }, { passive: false });
  // One-off: adopt stray queue edges as `admit` (heals pre-role-port graphs). Converges.
  healQueueNodeEdges();
  // Drive queue-node channel-reservation bars (shared with the classic slot view).
  ensureStickyBarTicker();

  // ── Canvas schedule node interactions ─────────────────────────────────────
  // Collapse/expand toggle
  world.querySelectorAll("[data-cv-sched-toggle]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const nid = btn.dataset.cvSchedToggle;
      if (_cvSchedCollapsed.has(nid)) _cvSchedCollapsed.delete(nid); else _cvSchedCollapsed.add(nid);
      renderTopology();
      requestAnimationFrame(() => { drawCanvasConnectors(); bindCanvasInteractions(); });
    });
  });

  // Chip click — select paint colour
  world.querySelectorAll("[data-cv-sched-chip]").forEach((chip) => {
    chip.addEventListener("click", (e) => {
      if (e.target.closest(".cv-sched-rm") || e.target.closest("[contenteditable]") || e.target.closest(".cv-port")) return;
      e.stopPropagation();
      const [nid, outId] = chip.dataset.cvSchedChip.split(":");
      _cvSchedPaintIds[nid] = outId;
      renderTopology();
      requestAnimationFrame(() => { drawCanvasConnectors(); bindCanvasInteractions(); });
    });
  });

  // Add output
  world.querySelectorAll("[data-cv-sched-addout]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const nid = btn.dataset.cvSchedAddout;
      saveNodeConfig(nid, (cfg) => {
        cfg.outputs = cfg.outputs || [];
        const n = cfg.outputs.length + 1;
        cfg.outputs.push({ id: _newId("sout"), name: `output ${n}` });
        if (!cfg.grid) cfg.grid = Array.from({ length: 7 }, () => Array(24).fill(null));
      });
    });
  });

  // Remove output — single saveRouters call to avoid race condition
  world.querySelectorAll("[data-cv-sched-rmout]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const parts = btn.dataset.cvSchedRmout.split(":");
      const nid = parts[0], outId = parts.slice(1).join(":");
      saveRouters((routers) => {
        const s = routerById(routers, ui.topologyCanvasRouterId);
        if (!s) return;
        // Patch node config
        const n = (s.graph?.nodes || []).find((x) => x.id === nid);
        if (n) {
          n.config = n.config || {};
          n.config.outputs = (n.config.outputs || []).filter((o) => o.id !== outId);
          n.config.grid = (n.config.grid || []).map((row) => row.map((c) => (c === outId ? null : c)));
        }
        // Clean up edges in same transaction
        if (s.graph) s.graph.edges = (s.graph.edges || []).filter((e) => !(e.from === `rule:${nid}` && e.schedPortId === outId));
      }).catch((e) => toast(e.message));
    });
  });

  // Rename output — double-click activates editing, blur/Enter saves
  function _cvSchedActivateEdit(span) {
    span.contentEditable = "true";
    span.focus();
    const sel = window.getSelection(), range = document.createRange();
    range.selectNodeContents(span); sel.removeAllRanges(); sel.addRange(range);
  }
  world.querySelectorAll("[data-cv-sched-rename]").forEach((span) => {
    span.addEventListener("pointerdown", (e) => e.stopPropagation());
    span.addEventListener("dblclick", (e) => { e.stopPropagation(); _cvSchedActivateEdit(span); });
    span.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); span.blur(); } });
    span.addEventListener("blur", () => {
      if (span.contentEditable !== "true") return;
      span.removeAttribute("contenteditable");
      const parts = span.dataset.cvSchedRename.split(":");
      const nid = parts[0], outId = parts.slice(1).join(":");
      const name = span.textContent.trim().slice(0, 40) || "output";
      saveNodeConfig(nid, (cfg) => {
        const o = (cfg.outputs || []).find((x) => x.id === outId);
        if (o) o.name = name;
      });
    });
  });

  // Rename default label — double-click activates editing, blur/Enter saves
  world.querySelectorAll("[data-cv-sched-rename-default]").forEach((span) => {
    span.addEventListener("pointerdown", (e) => e.stopPropagation());
    span.addEventListener("dblclick", (e) => { e.stopPropagation(); _cvSchedActivateEdit(span); });
    span.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); span.blur(); } });
    span.addEventListener("blur", () => {
      if (span.contentEditable !== "true") return;
      span.removeAttribute("contenteditable");
      const nid = span.dataset.cvSchedRenameDefault;
      const name = span.textContent.trim().slice(0, 40) || "default";
      saveNodeConfig(nid, (cfg) => { cfg.defaultName = name; });
    });
  });

  // Grid painting: pointerdown/over paint cells; pointerup saves
  world.querySelectorAll("[data-cv-sched-cell]").forEach((cell) => {
    cell.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.stopPropagation(); e.preventDefault();
      const nid = cell.dataset.cvSchedCell;
      _cvSchedPainting = true;
      _cvSchedPaintNid = nid;
      const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
      const node = (router?.graph?.nodes || []).find((n) => n.id === nid);
      const _wg = _cvSchedWorkingGrids[nid];
      _cvSchedPendingGrid = { nid, grid: _wg ? _wg.map((r) => [...r]) : _cvSchedMakeGrid(node?.config || {}) };
      _cvSchedPaintCell(nid, parseInt(cell.dataset.schedD, 10), parseInt(cell.dataset.schedH, 10));
    });
    cell.addEventListener("pointerover", (e) => {
      if (!_cvSchedPainting || _cvSchedPaintNid !== cell.dataset.cvSchedCell) return;
      _cvSchedPaintCell(cell.dataset.cvSchedCell, parseInt(cell.dataset.schedD, 10), parseInt(cell.dataset.schedH, 10));
    });
  });
}

// ── Weekly schedule editor (paint days×hours → router outputs) ────────────
export const SCHEDULE_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const SCHEDULE_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const SCHEDULE_COLORS = ["#60a5fa", "#f59e0b", "#22c55e", "#ef4444", "#a78bfa", "#ec4899", "#14b8a6", "#eab308"];

export function scheduleOutputColor(router, outputId) {
  const i = (router?.outputs || []).findIndex((o) => o.id === outputId);
  return i < 0 ? "" : SCHEDULE_COLORS[i % SCHEDULE_COLORS.length];
}

