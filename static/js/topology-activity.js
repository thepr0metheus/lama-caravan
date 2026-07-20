// Per-card activity/health classes and live runtime panels.
import { drawTopologyCables, topologyProxyClass } from "./cables.js";
import { drawCanvasConnectors, syncQueueNodesLive } from "./canvas.js";
import { attachTokenChartHover, drawMetricChart, drawTopologyGpuHistory } from "./charts.js";
import { t } from "./i18n.js";
import { messages } from "./i18n-data.js";
import { topologyCrownSvg } from "./model-meta.js";
import { action, formatTps } from "./polling.js";
import { state, topology, ui } from "./state.js";
import { topologyRouteDetail } from "./topology-dnd.js";
import { queueThresholds } from "./topology-modals.js";
import { topologyAssignmentsForHost, topologyProxyOwner } from "./topology-proxies.js";
import { _lastRuntimePanelHtml } from "./topology-render.js";
import { $, api, escapeHtml, formatMemoryMiB, pill } from "./utils.js";

export let stickySlotAnims = {};             // group -> absolute-time anchor for that server's sticky-slot bar { port, startMs, durationMs }
export function topologyStatusPill(value) {
  // "warming" = process up but model still loading into VRAM — show a clear,
  // amber, localized label rather than the raw token.
  if (value === "warming") return pill(t("topologyWarmingShort"), "warn");
  const kind = value === "online" || value === "running" || value === "ok" ? "good"
    : value === "stale" || value === "loading" || value === "pending" || value === "stored" || value === "warming" ? "warn"
    : value === "error" || value === "failed" ? "bad" : "";
  return pill(value || "unknown", kind);
}

export function topologyAgentMeta(agent) {
  const details = [
    agent.scope && agent.scope !== "agent" ? agent.scope : "",
    agent.runtime || "",
    agent.container || "",
    agent.port ? `:${agent.port}` : "",
  ].filter(Boolean);
  return details.join(" ");
}

export function topologyAssignmentsByAgent(assignments = []) {
  const rows = new Map();
  assignments.forEach((assignment) => {
    const routes = new Map();
    (assignment.routes || []).forEach((route) => routes.set(route.role || "primary", route));
    rows.set(assignment.agentId, routes);
  });
  return rows;
}

export function topologyAgentGroup(agent) {
  const runtime = String(agent.runtime || "").toLowerCase();
  const scope = String(agent.scope || "").toLowerCase();
  if (scope === "host" || runtime === "host" || runtime === "launchd") return "host";
  if (runtime === "vm" || runtime === "virtual-machine") return "vm";
  if (runtime === "docker" || agent.container) return "docker";
  return "other";
}

export function topologyGroupLabel(group) {
  const keys = { host: "topologyHostGroup", vm: "topologyVmGroup", docker: "topologyDockerGroup", other: "topologyOtherGroup" };
  return t(keys[group] || "topologyOtherGroup");
}

export function topologyAgentSortPort(agent) {
  const explicit = Number(agent.port || 0);
  if (explicit) return explicit;
  const endpoint = String(agent.endpoint || agent.url || "");
  const match = endpoint.match(/:(\d+)(?:\/|$)/);
  return match ? Number(match[1]) : 0;
}

export function sortedTopologyAgents(agents) {
  return agents.slice().sort((left, right) => {
    const leftPort = topologyAgentSortPort(left);
    const rightPort = topologyAgentSortPort(right);
    return (leftPort || 999999) - (rightPort || 999999)
      || String(left.name || left.id || "").localeCompare(String(right.name || right.id || ""));
  });
}

export function topologyActivityClass(activity) {
  if (!activity) return "";
  if (activity.state === "active") return "activity-active";
  if (activity.state === "error") return "activity-error";
  if (activity.state === "recent") return "activity-recent";
  return "";
}

export const topologyActivityClasses = ["activity-active", "activity-error", "activity-degraded", "activity-recent", "activity-queued"];
export const topologyHealthClasses = ["health-ok", "health-degraded", "health-failed", "health-fallback"];

export function topologyHealthClass(activity) {
  if (!activity) return "";
  if (activity.health === "failed") return "health-failed";
  if (activity.health === "degraded") return "health-degraded";
  if (activity.health === "fallback") return "health-fallback";
  if (activity.health === "ok") return "health-ok";
  return "";
}

export function topologyStateHealthClasses(activity) {
  return [topologyActivityClass(activity), topologyHealthClass(activity)].filter(Boolean).join(" ");
}

export function setTopologyActivityClass(element, activity) {
  if (!element) return;
  element.classList.remove(...topologyActivityClasses, ...topologyHealthClasses);
  const classNames = topologyStateHealthClasses(activity).split(" ").filter(Boolean);
  if (classNames.length) element.classList.add(...classNames);
}

export function updateTopologyActivityChip(container, activity) {
  if (!container) return;
  let chip = container.querySelector(".topology-activity-chip.compact");
  if (!activity?.label) {
    chip?.remove();
    return;
  }
  if (!chip) {
    chip = document.createElement("span");
    chip.className = "topology-activity-chip compact";
    container.appendChild(chip);
  }
  chip.classList.remove("active", "error", "degraded", "recent", "failed", "fallback", "ok", "queued");
  chip.classList.add(activity.health === "failed" ? "failed" : (activity.health || activity.state));
  if (activity.state === "active") chip.classList.add("active");
  chip.title = activity.title || activity.label;
  chip.setAttribute("aria-label", activity.label);
}

export function updateTopologyServerStats() {
  const latest = ui.latestSystemMonitor?.latest;
  if (!latest) return;
  const cpuEl = $("topologyServerCpu");
  if (cpuEl) {
    const pct = latest.cpu?.total ?? "?";
    const load = Array.isArray(latest.cpuLoad) ? latest.cpuLoad[0] : null;
    cpuEl.textContent = load != null ? `CPU ${pct}% · load ${load}` : `CPU ${pct}%`;
  }
  const ramEl = $("topologyServerRam");
  if (ramEl) {
    const mem = latest.memory || {};
    if (mem.ok) ramEl.textContent = `RAM ${formatMemoryMiB(mem.usedMiB)} / ${formatMemoryMiB(mem.totalMiB)}`;
  }
}

export function updateTopologyRuntimePanels() {
  // One panel per server, each tagged with its upstream queue group — rebuild
  // each independently (per-group HTML cache skips untouched servers).
  document.querySelectorAll("[data-topology-runtime-panel]").forEach((panel) => {
    const group = panel.getAttribute("data-topology-runtime-panel") || "";
    const html = topologyRuntimePanelHtml(group).trim();
    if (_lastRuntimePanelHtml[group] === html && panel.isConnected) return;  // unchanged
    _lastRuntimePanelHtml[group] = html;
    const temp = document.createElement("div");
    temp.innerHTML = html;
    const next = temp.firstElementChild;
    if (next) panel.replaceWith(next);
  });
  // Sticky reservations are driven by a rAF loop (smooth shrink + seconds), so it
  // doesn't matter that this rebuild recreated the bar nodes every second.
  ensureStickyBarTicker();
}

export let _stickyBarRaf = 0;
export function ensureStickyBarTicker() {
  if (_stickyBarRaf) return;            // already running
  if (!Object.keys(stickySlotAnims).length) return;  // no active reservation on any server
  const step = () => {
    // Each server's sticky bar carries its own group; drive them all from one rAF.
    const bars = document.querySelectorAll(".topology-sticky-bar[data-sticky-group]");
    let anyActive = false;
    bars.forEach((bar) => {
      const anim = stickySlotAnims[bar.getAttribute("data-sticky-group")];
      const fill = bar.querySelector("i");
      if (!anim || !fill) return;
      anyActive = true;
      const remMs = Math.max(0, anim.durationMs - (Date.now() - anim.startMs));
      const pct = anim.durationMs > 0 ? (remMs / anim.durationMs) * 100 : 0;
      // Eat from the right (pacman) so the gradient stays pinned to the track instead of
      // compressing — the passed path leaves no color behind.
      fill.style.clipPath = "inset(0 " + (100 - pct).toFixed(3) + "% 0 0)";
      const secsEl = bar.parentElement?.querySelector("[data-sticky-secs]");
      if (secsEl) {
        const txt = Math.ceil(remMs / 1000) + "s";
        if (secsEl.textContent !== txt) secsEl.textContent = txt;
      }
    });
    if (!anyActive) { _stickyBarRaf = 0; return; }  // all reservations gone → stop
    _stickyBarRaf = requestAnimationFrame(step);
  };
  _stickyBarRaf = requestAnimationFrame(step);
}

export function updateTopologyIncidentLine(routeRow, activity) {
  if (!routeRow) return;
  const incident = activity?.incident || topologyIncidentForItem(activity?.item);
  let line = routeRow.querySelector(".topology-incident-line");
  if (!incident) {
    line?.remove();
    return;
  }
  if (!line) {
    line = document.createElement("small");
    line.className = "topology-incident-line";
    const telemetry = routeRow.querySelector(".topology-telemetry-line");
    routeRow.insertBefore(line, telemetry || null);
  }
  line.classList.toggle("failed", incident.kind === "failed");
  line.textContent = `${incident.title}: ${incident.summary}`;
}

export function buildActivityFingerprint() {
  // Captures everything that would change activity classes on proxy/llama/GPU cards.
  // Changes only when a request starts, finishes, errors, or sticky-slot state changes.
  const agents = ui.latestSystemMonitor?.latest?.agentProxies?.agents || {};
  const items = Object.entries(agents)
    .flatMap(([, row]) => (row.active || []).map((i) => `${i.route}:${i.phase}:${i.status || ""}`))
    .sort()
    .join("|");
  const sticky = ui.latestSystemMonitor?.latest?.agentProxies?.stickySlots || {};
  const stickyStr = Object.entries(sticky)
    .map(([group, s]) => `:s${group}:${s.port}:${Math.ceil(s.remainingSec)}`)
    .sort()
    .join("");
  const llamaActive = ui.latestSystemMonitor?.latest?.correlatedActivity?.llamaServer?.activeRequestCount ?? 0;
  return `${items}${stickyStr}:l${llamaActive}`;
}

export function refreshTopologyActivityState() {
  if (!topology) return;

  // Activity class DOM walk — only when something actually started/stopped/errored
  const fingerprint = buildActivityFingerprint();
  if (fingerprint !== ui._lastActivityFingerprint) {
    ui._lastActivityFingerprint = fingerprint;
    document.querySelectorAll("[data-topology-proxy]").forEach((row) => {
      const proxy = (topology.proxies || []).find((item) => item.id === row.dataset.proxyId);
      const activity = topologyProxyActivity(proxy);
      setTopologyActivityClass(row, activity);
    });
    document.querySelectorAll("[data-topology-proxy-input], [data-topology-proxy-output]").forEach((handle) => {
      const proxy = (topology.proxies || []).find((item) => item.id === handle.dataset.proxyId);
      setTopologyActivityClass(handle, topologyProxyActivity(proxy));
    });
    document.querySelectorAll("[data-topology-route-handle]").forEach((handle) => {
      const activity = topologyProxyActivity(handle.dataset.proxyId || "");
      setTopologyActivityClass(handle, activity);
      const routeRow = handle.closest(".topology-agent-route");
      setTopologyActivityClass(routeRow, activity);
      updateTopologyIncidentLine(routeRow, activity);
      if (activity.title) handle.title = activity.title;
    });
    document.querySelectorAll("[data-topology-llama]").forEach((card) => {
      const activity = topologyLlamaActivity(card.dataset.llamaPort);
      setTopologyActivityClass(card, activity);
      updateTopologyActivityChip(card.querySelector(".topology-meta"), activity);
    });
    document.querySelectorAll("[data-topology-llama-input]").forEach((handle) => {
      setTopologyActivityClass(handle, topologyLlamaActivity(handle.dataset.llamaPort));
    });
    const gpuActivity = topologyGpuActivity();
    document.querySelectorAll(".gpu-card").forEach((card) => {
      setTopologyActivityClass(card, gpuActivity);
      updateTopologyActivityChip(card.querySelector(".topology-meta"), gpuActivity);
    });
    (topology.proxies || []).forEach((proxy) => {
      const activity = topologyProxyActivity(proxy);
      document.querySelectorAll(`.${CSS.escape(topologyProxyClass(proxy.id))}`).forEach((element) => {
        setTopologyActivityClass(element, activity);
      });
    });
    // Router→server cables are per-output (only the output actually serving a
    // request animates) — redraw them when activity changes.
    drawTopologyCables();
    if (ui.topologyCanvasRouterId) drawCanvasConnectors();
  }

  // Runtime panel (slots/queue) — HTML cache handles skipping when output unchanged
  updateTopologyRuntimePanels();
  syncQueueNodesLive();   // canvas queue node cards — re-patch their live now/waiting region
  updateTopologyServerStats();
  // Charts always redraw — new sample every second
  drawTopologyGpuHistory();
}

export function topologyDurationMs(startedAt, finishedAt) {
  const start = Number(startedAt || 0);
  const end = Number(finishedAt || 0) || Math.floor(Date.now() / 1000);
  if (!start) return 0;
  return Math.max(0, (end - start) * 1000);
}

export function topologyAgentProxyRows() {
  const agents = ui.latestSystemMonitor?.latest?.agentProxies?.agents || {};
  return Object.entries(agents).flatMap(([key, row]) => {
    const active = Array.isArray(row.active) ? row.active : [];
    // agents dict is now keyed by port string; row.label holds the route label name
    const rowLabel = row.label || key;
    return active.map((item) => ({
      ...item,
      label: item.label || item.route || rowLabel,
      route: item.route || item.label || rowLabel,
      port: item.port ?? row.port,
    }));
  });
}

export function topologyRowsForProxy(proxy) {
  if (!proxy) return [];
  return topologyAgentProxyRows().filter((item) => {
    const itemPort = Number(item.port || 0);
    const proxyPort = Number(proxy.port || 0);
    if (itemPort && proxyPort) return itemPort === proxyPort;
    return String(item.label || item.route || "") === String(proxy.label || "");
  });
}

export function topologyIsQueuedItem(item) {
  return String(item?.phase || "").toLowerCase() === "queued";
}

export function topologyIsRunningItem(item) {
  return item && !topologyIsQueuedItem(item);
}

export function topologyFormatDuration(ms) {
  const seconds = Math.round(Number(ms || 0) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
}

export function topologyQueueRuntime(item) {
  const queue = item?.queue || {};
  const queuedMs = Number(queue.queuedMs || topologyDurationMs(item?.startedAt));
  // Use the full clientTimeoutSeconds (from backend thresholds or OpenClaw config).
  // No more abort% — we wait until the client's own timeout runs out.
  const proxyPort = Number(item?.port || 0);
  const proxy = proxyPort ? (topology?.proxies || []).find((p) => Number(p.port || 0) === proxyPort) : null;
  const effWait = proxy ? proxyEffectiveWaitTimeout(proxy) : 0;
  const timeoutSec = Number(queue.thresholds?.clientTimeoutSeconds || 0) || effWait || 3600;
  const leftMs = Math.max(0, timeoutSec * 1000 - queuedMs);
  const position = queue.position;
  // cloudAt: seconds from queue start when overflow fires (backend thresholds).
  // Used to show per-client overflow countdown in the queue node card.
  const cloudAt = Number(queue.thresholds?.cloudAt || 0);
  return {
    queuedMs,
    timeoutSec,
    leftMs,
    cloudAt,
    position: position === null || position === undefined ? null : Number(position),
  };
}

export function notchTimeHint(eventSec, queue) {
  if (eventSec == null || !queue?.clientTimeoutSeconds) return "";
  const elapsedSec = queue.clientTimeoutSeconds - queue.leftMs / 1000;
  const secUntil = eventSec - elapsedSec;
  if (secUntil <= 0) return " · triggered";
  return ` · in ${topologyFormatDuration(secUntil * 1000)}`;
}

export function topologyRuntimeClass(item) {
  if (!item) return "idle";
  if (topologyIsQueuedItem(item)) return "queued";
  if (String(item.phase || "") === "preempting") return "preempting";
  return "running";
}

export function topologyRuntimeLabel(item, compact = false) {
  if (!item) return "";
  if (topologyIsQueuedItem(item)) {
    const queue = topologyQueueRuntime(item);
    const pos = queue.position === null ? "" : ` #${queue.position + 1}`;
    const left = topologyFormatDuration(queue.leftMs);
    const elapsed = topologyFormatDuration(queue.queuedMs);
    return compact
      ? `queued${pos} · ${left} left`
      : `queued${pos} · ${elapsed}/${queue.timeoutSec}s · ${left} left`;
  }
  const elapsed = topologyFormatDuration(item.elapsedMs || topologyDurationMs(item.startedAt));
  const phase = String(item.phase || "running");
  return compact ? `${phase} ${elapsed}` : `${phase} · ${elapsed}`;
}

export function topologyProxyRuntime(proxy) {
  const rows = topologyRowsForProxy(proxy);
  const queued = rows.filter(topologyIsQueuedItem);
  const running = rows.filter(topologyIsRunningItem);
  const primary = running[running.length - 1] || queued[0] || null;
  return {
    rows,
    running,
    queued,
    primary,
    state: primary ? topologyRuntimeClass(primary) : "idle",
    label: primary ? topologyRuntimeLabel(primary, true) : "",
    detail: [
      running.length ? `${running.length} running` : "",
      queued.length ? `${queued.length} queued` : "",
    ].filter(Boolean).join(" · "),
  };
}

export function topologyRuntimeOverview() {
  const rows = topologyAgentProxyRows();
  // Sort queued items by queue position (position 0 = first in line, at top)
  const queued = rows.filter(topologyIsQueuedItem).sort((a, b) => {
    const posA = a.queue?.position ?? 9999;
    const posB = b.queue?.position ?? 9999;
    return posA - posB;
  });
  const running = rows.filter(topologyIsRunningItem);
  return { rows, queued, running };
}

export function topologyRuntimeList(items, limit = 4) {
  const policy = topology?.proxyPolicy || {};
  const priorityPreemptPct = Math.max(0, Math.min(100, Number(policy.priorityPreemptPct ?? 50)));
  const proxies = topology?.proxies || [];
  const rows = items.slice(0, limit).map((item) => {
    const state = topologyRuntimeClass(item);
    const proxy = proxies.find((row) =>
      (item.port !== undefined && Number(row.port || 0) === Number(item.port || 0)) ||
      (item.label && String(row.label || "") === String(item.label))
    );
    const priorityLevel = Math.max(0, Number(proxy?.priority || 0));
    // Display the slot's owner the same way the rest of Topology does: resolve the
    // proxy (by listen port — the source of truth) to its assigned client/agent via
    // topologyProxyOwner, not the raw agent-proxies.json route label. That label is
    // cosmetic and often stale (e.g. a port still labelled by its old agent while it serves
    // a host's OpenClaw agent), which is why slots showed the wrong agent.
    const owner = proxy ? topologyProxyOwner(proxy.id) : null;
    const row = {
      name: owner?.title || item.label || item.route || `:${item.port}`,
      state,
      text: topologyRuntimeLabel(item, true),
      priorityLevel,
      item,
    };
    if (state === "queued") {
      const queue = topologyQueueRuntime(item);
      // queue.timeoutSec = full clientTimeoutSeconds (no abort% scaling anymore).
      const totalMs = Math.max(1, queue.timeoutSec * 1000);
      const remMs = queue.leftMs;
      const leftPct = Math.max(0, Math.min(100, (remMs / totalMs) * 100));
      row.queue = {
        leftMs: remMs,
        leftPct,
        elapsedPct: Math.max(0, Math.min(100, 100 - leftPct)),
        timeoutSec: queue.timeoutSec,
        clientTimeoutSeconds: queue.timeoutSec,
      };
      // Notches at their raw % of wait_timeout (same scale as the Agent timelines).
      const proxyPort = Number(item.port || 0);
      const proxyLabel = String(item.label || "");
      const threshEntry = (queueThresholds?.proxies || []).find((p) =>
        (proxyPort && Number(p.port || 0) === proxyPort) ||
        (proxyLabel && String(p.label || "") === proxyLabel)
      );
      if (priorityLevel > 0 && priorityPreemptPct > 0 && priorityPreemptPct < 100) {
        row.queue.preemptNotchPct = priorityPreemptPct;
        row.queue.priorityPreemptPct = priorityPreemptPct;
        row.queue.preemptSec = threshEntry?.priorityPreemptSec ?? null;
      }
      const cloudFallbackPct = Math.max(0, Math.min(100, Number(policy.cloudFallbackPct ?? 20)));
      if (proxy?.cloudFallbackProviderId && cloudFallbackPct > 0 && cloudFallbackPct < 100) {
        row.queue.cloudNotchPct = cloudFallbackPct;
        row.queue.cloudFallbackSec = threshEntry?.cloudFallbackSec ?? null;
      }
    }
    return row;
  });
  const rest = Math.max(0, items.length - rows.length);
  if (rest) rows.push({ name: `+${rest} more`, state: "idle", text: "" });
  return rows;
}

export function topologyAssignRunningToSlots(running, total) {
  const slots = new Array(total).fill(null);
  const remaining = running.slice();
  remaining.forEach((row) => {
    const ids = Array.isArray(row?.item?.slotIds) ? row.item.slotIds : [];
    if (!ids.length) return;
    const target = Number(ids[0]);
    if (Number.isFinite(target) && target >= 0 && target < total && !slots[target]) {
      slots[target] = row;
      row._placed = true;
    }
  });
  let cursor = 0;
  remaining.forEach((row) => {
    if (row._placed) return;
    while (cursor < total && slots[cursor]) cursor += 1;
    if (cursor < total) slots[cursor] = row;
    cursor += 1;
  });
  return slots;
}

// Queue partition key for an active/queued request — the upstream llama-server
// it competes for. Matches the backend's route_group_key ("upstreamHost:upstreamPort").
export function topologyItemGroup(item) {
  if (item?.upstream) return String(item.upstream);
  const port = Number(item?.port || 0);
  const proxy = port ? (topology?.proxies || []).find((p) => Number(p.port || 0) === port) : null;
  if (!proxy) return "";
  const h = proxy.resolvedUpstreamHost || proxy.upstreamHost || "127.0.0.1";
  const pt = proxy.resolvedUpstreamPort || proxy.upstreamPort || 8080;
  return `${h}:${pt}`;
}

// Effective upstream host:port for a proxy — prefers the router-resolved upstream
// (set when route.upstreamPort is a legacy placeholder and the graph output is the real target).
export function _proxyUpstreamStr(proxy) {
  const h = proxy.resolvedUpstreamHost || proxy.upstreamHost || "127.0.0.1";
  const pt = proxy.resolvedUpstreamPort || proxy.upstreamPort || 8080;
  return `${h}:${pt}`;
}

// Display the effective upstream for a route row, using topology.proxies resolved values.
export function _routeDisplayUpstream(route) {
  const port = Number(route?.port || 0);
  const proxy = port ? (topology?.proxies || []).find((p) => Number(p.port || 0) === port) : null;
  if (proxy) return _proxyUpstreamStr(proxy);
  return `${route.upstreamHost || "127.0.0.1"}:${route.upstreamPort || 8080}`;
}

// Queue group for a llama-server card: the upstream key of any proxy targeting it.
// Servers with no proxy get a unique non-matching key so their panel stays empty.
export function topologyServerGroup(llama) {
  const port = Number(llama?.port || 0);
  if (!port) return "__srv__:none";
  // Check proxies first (resolvedUpstreamPort wins over the legacy placeholder upstreamPort).
  const proxy = (topology?.proxies || []).find((p) =>
    Number(p.resolvedUpstreamPort || p.upstreamPort || 0) === port
  );
  if (proxy) return _proxyUpstreamStr(proxy);
  // No proxy targets this server — fall back to router outputs.
  // Graph-routed items set item.upstream = "host:port" from the router output, so match that format.
  for (const router of (topology?.routers || [])) {
    const out = (router.outputs || []).find((o) => Number(o.upstreamPort || 0) === port);
    if (out) return `${out.upstreamHost || "127.0.0.1"}:${out.upstreamPort}`;
  }
  return `__srv__:${port}`;
}

export function topologyRuntimePanelHtml(group = "") {
  const overview = topologyRuntimeOverview();
  const liveSlots = Number(ui.latestSystemMonitor?.latest?.llamaActivity?.totalSlots || 0);
  const effective = Number(topology?.effectiveSlots || 0);
  const policy = topology?.proxyPolicy || {};
  // Per-server slot total: authoritative count tracked by the proxy from this
  // upstream's --parallel (length of /slots). Falls back to the controller's
  // live slots / policy default until the first request populates it.
  const slotTotals = ui.latestSystemMonitor?.latest?.agentProxies?.slotTotals || {};
  const groupSlots = group ? Number(slotTotals[group] || 0) : 0;
  const totalSlots = Math.max(1, groupSlots || liveSlots || effective || Number(policy.maxSlots || 1));
  // Scope rows to this server's queue group, and drop cloud routes (no slots).
  const proxies = topology?.proxies || [];
  const inGroup = (item) => !group || topologyItemGroup(item) === group;
  const llamaRunning = overview.running.filter((item) => {
    if (!inGroup(item)) return false;
    const proxy = proxies.find((p) => Number(p.port || 0) === Number(item.port || 0) || String(p.label || "") === String(item.label || ""));
    return !proxy || String(proxy.upstreamType || "llama") !== "cloud";
  });
  const runningRows = topologyRuntimeList(llamaRunning, totalSlots);
  const slotMap = topologyAssignRunningToSlots(runningRows, totalSlots);
  const stickySlots = ui.latestSystemMonitor?.latest?.agentProxies?.stickySlots || {};
  const stickySlotData = group ? (stickySlots[group] || null) : null;
  const stickySlotSec = Number(policy.stickySlotSec || 0);
  // Find first idle slot index to display sticky reservation
  const stickySlotIdx = (stickySlotData && stickySlotSec > 0)
    ? slotMap.findIndex((row) => !row)
    : -1;
  // Drop this group's bar anchor when its reservation disappears so the next one re-anchors fresh.
  if (!stickySlotData) delete stickySlotAnims[group];
  const stickyProxy = stickySlotData
    ? proxies.find((p) => Number(p.port) === Number(stickySlotData.port))
    : null;
  const stickyProxyLabel = stickyProxy
    ? (topologyProxyOwner(stickyProxy.id)?.title || stickyProxy.label || `port ${stickySlotData.port}`)
    : "";

  const renderSlotRow = (row, idx) => {
    const label = `${t("topologySlot")} ${idx + 1}`;
    if (!row) {
      if (idx === stickySlotIdx && stickySlotData) {
        // Anchor the drain to an absolute client clock so periodic re-renders never
        // restart or rescale the bar. Compute the fill rate once when the reservation
        // first appears (or changes proxy / drifts from the poll), then let CSS drain it.
        const rem = Math.max(0, Number(stickySlotData.remainingSec));
        const port = Number(stickySlotData.port);
        const totalMs = Math.max(1, Math.round(stickySlotSec * 1000));
        const nowMs = Date.now();
        const elapsedPollMs = Math.max(0, totalMs - rem * 1000);
        const prevAnim = stickySlotAnims[group];
        const drift = prevAnim ? Math.abs((nowMs - prevAnim.startMs) - elapsedPollMs) : Infinity;
        if (!prevAnim || prevAnim.port !== port || prevAnim.durationMs !== totalMs || drift > 1500) {
          stickySlotAnims[group] = { port, startMs: nowMs - elapsedPollMs, durationMs: totalMs };
        }
        const anim = stickySlotAnims[group];
        const elapsedMs = Math.min(anim.durationMs, Math.max(0, nowMs - anim.startMs));
        const remMs = anim.durationMs - elapsedMs;
        const startPct = anim.durationMs > 0 ? (remMs / anim.durationMs) * 100 : 0;
        // The bar width + seconds are driven by ensureStickyBarTicker() (rAF), reading the
        // same absolute anchor every frame. So the per-second panel rebuild recreating this
        // node never matters: the next frame re-applies the correct width — smooth, no jumps.
        const stickyBar = `<span class="topology-sticky-bar" data-sticky-group="${escapeHtml(group)}" aria-hidden="true"><i style="clip-path:inset(0 ${(100 - startPct).toFixed(3)}% 0 0)"></i></span>`;
        return `<span class="slot-chip sticky-reserved" title="${escapeHtml(label)}: ${escapeHtml(stickyProxyLabel)}">${stickyBar}<span class="slot-chip-name">${escapeHtml(stickyProxyLabel)}</span><span class="slot-chip-sub" data-sticky-secs>${Math.ceil(remMs / 1000)}s</span></span>`;
      }
      return `<span class="slot-chip idle" title="${escapeHtml(label)}"></span>`;
    }
    const slotCrown = row.priorityLevel > 0 ? `<span class="topology-slot-crown" title="Priority ${row.priorityLevel} — protected, will not be preempted">${topologyCrownSvg("crown-icon")}</span>` : "";
    return `<span class="slot-chip ${escapeHtml(row.state)}" title="${escapeHtml(label)}: ${escapeHtml(row.name)}${row.text ? ` · ${row.text}` : ""}">${slotCrown}<span class="slot-chip-name">${escapeHtml(row.name)}</span>${row.text ? `<span class="slot-chip-sub">${escapeHtml(row.text)}</span>` : ""}</span>`;
  };
  const slotsHtml = slotMap.map(renderSlotRow).join("");
  // Generation speed for the slots head — the server whose upstream matches
  // this group. genTps rides the topology poll, so the per-second panel
  // rebuild picks fresh numbers without extra requests.
  const allSrv = [
    ...(topology?.server?.llamaServers || []),
    ...((topology?.nodes || []).flatMap((n) => n.servers || [])),
  ];
  const srv = group ? allSrv.find((x) => topologyServerGroup(x) === group) : null;
  const gen = Number(srv?.genTps || 0);
  // genTps is the LAST completed request's rate — llama.cpp holds it while the
  // slot is idle, so label it "last" to not read as a live figure.
  const tpsHtml = gen > 0
    ? `<span class="slots-head-tps" title="${escapeHtml(t("tpsLastHelp"))}"><span class="slots-head-tps-lbl">${escapeHtml(t("tpsLastLabel"))}</span> ${escapeHtml(gen.toFixed(1))} t/s</span>`
    : "";
  // The queue lane moved to the Router canvas (queue nodes). This classic panel now
  // shows live SLOTS only.
  return `
    <div class="topology-runtime-panel llama" data-topology-runtime-panel="${escapeHtml(group)}">
      <div class="topology-runtime-slots-head">
        <strong>${escapeHtml(t("topologySlots"))} <span class="topology-muted">${totalSlots}</span></strong>${tpsHtml}
      </div>
      <div class="topology-runtime-slots slot-chips-row">${slotsHtml}</div>
    </div>
  `;
}

export function proxyTelemetryLines(item) {
  const request = item?.request || {};
  const response = item?.response || {};
  const stream = item?.stream || {};
  const usage = response.usage || stream.usage || {};
  return [
    request.model ? `model: ${request.model}` : "",
    request.stream !== undefined ? `stream: ${request.stream ? "yes" : "no"}` : "",
    request.messages !== undefined ? `messages: ${request.messages}, chars: ${request.promptTextChars || 0}, images: ${request.imageParts || 0}` : "",
    request.maxTokens ? `max tokens: ${request.maxTokens}` : "",
    item?.firstByteMs ? `first byte: ${item.firstByteMs} ms` : "",
    item?.chunks ? `chunks: ${item.chunks}` : "",
    stream.events ? `stream events: ${stream.events}, delta chars: ${stream.deltaTextChars || 0}` : "",
    usage.prompt_tokens || usage.completion_tokens || usage.total_tokens
      ? `usage: prompt ${usage.prompt_tokens ?? "?"}, completion ${usage.completion_tokens ?? "?"}, total ${usage.total_tokens ?? "?"}`
      : "",
    (response.finishReasons || stream.finishReasons || []).length ? `finish: ${(response.finishReasons || stream.finishReasons || []).join(", ")}` : "",
  ].filter(Boolean);
}

export function proxyTelemetrySummary(item) {
  const request = item?.request || {};
  const response = item?.response || {};
  const stream = item?.stream || {};
  const usage = response.usage || stream.usage || {};
  const timing = item?.timing || {};
  const context = item?.context || {};
  const liveLlama = ui.latestSystemMonitor?.latest?.correlatedActivity?.llamaServer || {};
  const liveTokens = ui.latestSystemMonitor?.latest?.tokens || {};
  const liveTiming = liveLlama.lastTiming || ui.latestSystemMonitor?.latest?.llamaActivity?.lastTiming || {};
  const isActiveRoute = item?.state === "active" || (liveLlama.activeRoutes || []).includes(item?.label || "");
  const model = request.model || stream.model || response.model || "-";
  const messages = request.messages !== undefined ? `${request.messages} msg` : "msg -";
  const totalTokens = usage.total_tokens || usage.totalTokens || item?.usageTokens || "-";
  const promptTokens = timing.promptTokens ?? usage.prompt_tokens ?? usage.promptTokens ?? "-";
  const evalTokens = timing.evalTokens ?? usage.completion_tokens ?? usage.completionTokens ?? "-";
  const promptTpsValue = timing.promptTps ?? (isActiveRoute ? liveTokens.promptTokensPerSecond : liveTiming.promptTps);
  const evalTpsValue = timing.evalTps ?? (isActiveRoute ? liveTokens.predictedTokensPerSecond : liveTiming.evalTps);
  const promptTps = promptTpsValue !== undefined ? formatTps(promptTpsValue) : "-";
  const evalTps = evalTpsValue !== undefined ? formatTps(evalTpsValue) : "-";
  const contextTokens = context.tokens || "-";
  const firstByte = item?.firstByteMs ? `${item.firstByteMs}ms` : "-";
  const chunks = item?.chunks !== undefined ? item.chunks : "-";
  return [
    model,
    messages,
    `${totalTokens} tok`,
    `${promptTokens}/${evalTokens} tok`,
    `speed ${promptTps}/${evalTps} t/s`,
    `ctx ${contextTokens}`,
    `fb ${firstByte}`,
    `${chunks} chunks`,
  ].join(" · ");
}

export function topologyRouteDetailHtml() {
  if (!topologyRouteDetail) return "";
  const proxyId = topologyRouteDetail.proxyId || "";
  const proxy = (topology?.proxies || []).find((row) => row.id === proxyId);
  const activity = topologyProxyActivity(proxy || proxyId);
  const item = activity?.item || {};
  const incident = activity?.incident || topologyIncidentForItem(item);
  const policy = topology?.proxyPolicy || {};
  const llamaCtx = ui.latestSystemMonitor?.latest?.llamaActivity?.context || {};
  const totalSlots = Number(ui.latestSystemMonitor?.latest?.llamaActivity?.totalSlots || 0);
  const priorityLevel = Math.max(0, Number(proxy?.priority || 0));
  const lines = [
    activity?.label ? `state: ${activity.label}${activity.detail ? ` - ${activity.detail}` : ""}` : "",
    incident ? `incident: ${incident.title} - ${incident.summary}` : "",
    proxy ? `route: ${proxy.label || ""} (${proxy.topologyRole || "route"})` : "",
    priorityLevel > 0 ? `priority: ${priorityLevel}/10${policy.priorityPreemptPct ? ` · preempts at ${policy.priorityPreemptPct}% of wait_timeout` : ""}` : "",
    proxy?.mode && proxy.mode !== "open" ? `mode: ${proxy.mode}` : "",
    item.method || item.path ? `${item.method || ""} ${item.path || ""}`.trim() : "",
    item.status ? `status: ${item.status}` : "",
    item.error ? `error: ${item.error}` : "",
    item.client ? `client: ${item.client}` : "",
    item.bytes !== undefined ? `bytes: ${item.bytes}` : "",
    item.durationMs ? `duration: ${topologyFormatDuration(item.durationMs)}` : "",
    item.queue?.queuedMs ? `queue: ${topologyFormatDuration(item.queue.queuedMs)}${item.queue.position !== undefined && item.queue.position !== null ? `, position ${item.queue.position + 1}` : ""}` : "",
    proxy ? `proxy: :${proxy.port} -> ${proxy.upstreamHost}:${proxy.upstreamPort}` : "",
    totalSlots ? `llama slots: ${totalSlots} · abort at ${policy.queueAbortPct ?? 85}% of wait_timeout` : "",
    llamaCtx.tokens ? `llama context: ${llamaCtx.tokens}/${llamaCtx.limit || "?"} (${llamaCtx.pct ?? "?"}%)` : "",
    proxyTelemetrySummary(item),
    ...proxyTelemetryLines(item),
  ].filter(Boolean);
  return `
    <div class="topology-policy-overlay" data-topology-route-detail-overlay>
      <div class="topology-policy-modal topology-detail-modal" role="dialog" aria-modal="true" aria-label="Route details">
        <div class="topology-card-head">
          <strong>${escapeHtml(proxy?.label || item.label || item.route || "Route details")}</strong>
          <button class="icon-action compact" type="button" data-topology-route-detail-close aria-label="Close route details" title="Close">×</button>
        </div>
        <div class="topology-detail-lines">
          ${lines.length ? lines.map((line) => `<div>${escapeHtml(line)}</div>`).join("") : `<div class="muted">No request details yet.</div>`}
        </div>
        ${topologyRouteTokenHistoryHtml()}
      </div>
    </div>
  `;
}

export function topologyRouteTokenHistoryHtml() {
  // Per-consumer view: keyed by the proxy port (each agent has its own proxy
  // entry port). Fall back to client IP for legacy history without a port.
  if (!topologyRouteDetail?.port && !topologyRouteDetail?.clientIp) return "";
  const range = topologyRouteDetail.range || "all";
  const ranges = [["1h", "1h"], ["12h", "12h"], ["24h", "24h"], ["all", t("topologyTokenRangeAll")]];
  const buttons = ranges.map(([key, label]) =>
    `<button type="button" class="token-range-btn ${range === key ? "active" : ""}" data-token-range="${escapeHtml(key)}">${escapeHtml(label)}</button>`
  ).join("");
  const who = topologyRouteDetail.routeLabel || topologyRouteDetail.clientName || topologyRouteDetail.clientIp;
  return `
    <div class="topology-token-history">
      <div class="topology-token-history-head">
        <strong>${escapeHtml(t("topologyTokenHistoryTitle"))} · ${escapeHtml(who)}</strong>
        <div class="token-range-group">${buttons}</div>
      </div>
      <canvas id="routeTokenHistoryChart" class="topology-token-speed-chart" width="460" height="96"></canvas>
      <div id="routeTokenHistoryMeta" class="topology-history-meta"></div>
      <div class="topology-history-legend">
        <span class="topology-history-route" style="--route-color: rgba(96,165,250,0.95)">prompt</span>
        <span class="topology-history-route" style="--route-color: rgba(105,208,144,0.95)">gen</span>
      </div>
    </div>
  `;
}

export async function loadRouteTokenHistory() {
  const detail = topologyRouteDetail;
  if (!detail?.port && !detail?.clientIp) return;
  // Attribute by proxy port (consumer identity); fall back to client IP for
  // legacy history recorded before per-port attribution.
  const qs = detail.port
    ? `port=${encodeURIComponent(detail.port)}`
    : `client=${encodeURIComponent(detail.clientIp)}`;
  try {
    const res = await api(`/api/token-history?${qs}&range=${encodeURIComponent(detail.range || "all")}`);
    if (topologyRouteDetail && topologyRouteDetail.proxyId === detail.proxyId) {
      topologyRouteDetail.samples = res.samples || [];
      drawRouteTokenHistory();
    }
  } catch (err) {
    /* ignore */
  }
}

export function drawRouteTokenHistory() {
  const canvas = $("routeTokenHistoryChart");
  if (!canvas || !topologyRouteDetail) return;
  const samples = topologyRouteDetail.samples || [];
  const meta = $("routeTokenHistoryMeta");
  const roundMax = (vals) => Math.max(10, Math.ceil(Math.max(...vals, 0) / 10) * 10);
  const promptMax = roundMax(samples.map((s) => Number(s.promptTps || 0)).filter((v) => v > 0));
  const genMax = roundMax(samples.map((s) => Number(s.evalTps || 0)).filter((v) => v > 0));
  drawMetricChart(canvas, samples, [
    { color: "rgba(96, 165, 250, 0.9)", mode: "line", value: (s) => Number(s.promptTps || 0), max: promptMax },
    { color: "rgba(105, 208, 144, 0.95)", mode: "line", value: (s) => Number(s.evalTps || 0), max: genMax },
  ], { max: Math.max(promptMax, genMax), markers: true });
  attachTokenChartHover(canvas, samples, (s) => ({
    genTps: s.evalTps, genTokens: s.evalTokens, genMs: s.genMs,
    promptTps: s.promptTps, promptTokens: s.promptTokens, promptMs: s.promptMs,
    cacheTokens: s.cacheTokens, finish: s.finish, time: s.t,
  }));
  if (meta) {
    if (!samples.length) {
      meta.textContent = t("topologyTokenHistoryEmpty");
    } else {
      const avg = (fn) => samples.reduce((sum, s) => sum + Number(fn(s) || 0), 0) / samples.length;
      meta.textContent = `${samples.length} ${t("topologyTokenHistoryRuns")} · avg prompt ${formatTps(avg((s) => s.promptTps))} / gen ${formatTps(avg((s) => s.evalTps))} t/s`;
    }
  }
}

export function correlatedProxyActivity(proxy) {
  const correlated = ui.latestSystemMonitor?.latest?.correlatedActivity;
  const byProxy = correlated?.byProxy || {};
  return byProxy[proxy?.label || ""] || Object.values(byProxy).find((row) => Number(row?.port) === Number(proxy?.port));
}

export function correlatedTelemetryLines(item) {
  const timing = item?.timing || {};
  const context = item?.context || {};
  const lines = [];
  if (timing.promptTokens || timing.evalTokens) {
    lines.push(`timing: prompt ${timing.promptTokens || 0} tok @ ${timing.promptTps || 0} t/s, eval ${timing.evalTokens || 0} tok @ ${timing.evalTps || 0} t/s`);
  }
  if (context.tokens) {
    lines.push(`context: ${context.tokens}/${context.limit || "?"} tokens (${context.pct ?? "?"}%)`);
  }
  if (item?.slotIds?.length) lines.push(`llama slots: ${item.slotIds.join(", ")}`);
  if (item?.correlation) lines.push(`correlation: ${item.correlation}`);
  return lines;
}

export function topologyIncidentForItem(item) {
  if (!item) return null;
  const status = String(item.status || "");
  const firstByte = Number(item.firstByteMs || 0);
  const duration = Number(item.durationMs || item.elapsedMs || 0);
  const label = String(item.label || item.route || "");
  if (item.error || (status && !status.startsWith("2") && status !== "?")) {
    const errorKind = item.errorKind || (String(item.error || "").includes("Broken pipe") ? "client_disconnected"
      : String(item.error || "").includes("timed out") ? "upstream_timeout" : "failed");
    return {
      kind: errorKind,
      title: `${label || "route"} ${errorKind === "client_disconnected" ? "client disconnected" : "failed"}`,
      summary: item.error || `status ${status}`,
      cause: topologyIncidentCause(item, errorKind),
    };
  }
  if (firstByte >= 30000) {
    return {
      kind: "slow",
      title: `${label || "route"} slow first byte`,
      summary: `fb ${topologyFormatDuration(firstByte)} · ${item.chunks || 0} chunks`,
      cause: topologyIncidentCause(item, "slow_first_byte"),
    };
  }
  if (duration >= 120000) {
    return {
      kind: "slow",
      title: `${label || "route"} slow request`,
      summary: `${topologyFormatDuration(duration)} · ${item.chunks || 0} chunks`,
      cause: topologyIncidentCause(item, "slow_request"),
    };
  }
  return null;
}

export function topologyIncidentCause(item, kind) {
  if (item?.cause) return item.cause;
  if (kind === "client_disconnected") return "client closed connection while proxy was still streaming";
  if (kind === "upstream_timeout") return "proxy waited too long for llama.cpp upstream";
  if (kind === "slow_first_byte") {
    return Number(item?.chunks || 0) <= 1
      ? "likely queued or busy in prompt processing"
      : "likely overloaded shared llama.cpp server";
  }
  if (kind === "slow_request") return "long prompt/context or overloaded llama.cpp server";
  return "proxy/upstream error";
}

export function topologyIncidentHealth(item, fallbackHealth) {
  const incident = topologyIncidentForItem(item);
  if (!incident) return fallbackHealth;
  return ["failed", "upstream_timeout"].includes(incident.kind) ? "failed" : "degraded";
}

export function topologyProxyActivity(proxyOrId) {
  const proxy = typeof proxyOrId === "string"
    ? (topology?.proxies || []).find((row) => row.id === proxyOrId)
    : proxyOrId;
  if (!proxy) return { state: "idle", label: "", title: "" };
  const runtime = topologyProxyRuntime(proxy);
  if (runtime.primary) {
    const item = runtime.primary;
    const isQueued = topologyIsQueuedItem(item);
    const state = isQueued ? "queued" : "active";
    return {
      state,
      health: "ok",
      label: topologyRuntimeLabel(item, true),
      detail: runtime.detail,
      title: [
        `${proxy.label || proxy.port} ${isQueued ? "is queued" : "is running"}`,
        `${item.method || "POST"} ${item.path || ""}`,
        `phase: ${item.phase || state}`,
        `client: ${item.client || "?"}`,
        isQueued ? `queue: ${topologyRuntimeLabel(item)}` : `duration: ${topologyRuntimeLabel(item)}`,
        `proxy: :${proxy.port} -> ${_proxyUpstreamStr(proxy)}`,
      ].filter(Boolean).join("\n"),
      item,
    };
  }
  const correlated = correlatedProxyActivity(proxy);
  if (correlated?.last) {
    const active = Array.isArray(correlated.active) ? correlated.active : [];
    const item = active.length ? active[active.length - 1] : correlated.last;
    const isQueued = topologyIsQueuedItem(item);
    const isActive = item.state === "active" && !isQueued;
    const duration = isActive
      ? topologyFormatDuration(topologyDurationMs(item.startedAt))
      : topologyFormatDuration(item.durationMs || topologyDurationMs(item.startedAt, item.finishedAt));
    const status = String(item.status || "?");
    const isError = item.error || (!isActive && !status.startsWith("2"));
    const state = isQueued ? "queued" : (isActive ? "active" : (isError ? "error" : "recent"));
    const incident = topologyIncidentForItem(item);
    const health = topologyIncidentHealth(item, isError ? "failed" : "ok");
    return {
      state,
      health,
      label: isQueued ? topologyRuntimeLabel(item, true) : (isActive ? `active ${duration}` : `${status} ${duration}`),
      title: [
        incident ? `Incident: ${incident.title} - ${incident.summary}` : "",
        `${proxy.label || proxy.port} ${isActive ? "is active" : "last request"}`,
        `${item.method || "POST"} ${item.path || ""}`,
        isActive ? `duration: ${duration}` : `status: ${status}, duration: ${duration}`,
        `client: ${item.client || "?"}`,
        `bytes: ${item.bytes || 0}`,
        ...proxyTelemetryLines(item),
        ...correlatedTelemetryLines(item),
        `proxy: :${proxy.port} -> ${_proxyUpstreamStr(proxy)}`,
        item.error ? `error: ${item.error}` : "",
      ].filter(Boolean).join("\n"),
      item,
      incident,
    };
  }
  const agents = ui.latestSystemMonitor?.latest?.agentProxies?.agents || {};
  const byLabel = agents[proxy.label || ""];
  const byPort = Object.values(agents).find((row) => Number(row?.port) === Number(proxy.port));
  const row = byLabel || byPort || {};
  const active = Array.isArray(row.active) ? row.active : [];
  const recent = Array.isArray(row.recent) ? row.recent : [];
  const latest = recent[recent.length - 1] || null;
  if (active.length) {
    const item = active.find((row) => !topologyIsQueuedItem(row)) || active[0];
    const isQueued = topologyIsQueuedItem(item);
    const duration = topologyFormatDuration(topologyDurationMs(item.startedAt));
    const state = isQueued ? "queued" : "active";
    const incident = topologyIncidentForItem(item);
    const health = topologyIncidentHealth(item, "ok");
    return {
      state,
      health,
      label: isQueued ? topologyRuntimeLabel(item, true) : `active ${duration}`,
      title: [
        incident ? `Incident: ${incident.title} - ${incident.summary}` : "",
        `${proxy.label || proxy.port} is active`,
        `${item.method || "POST"} ${item.path || ""}`,
        `client: ${item.client || "?"}`,
        `duration: ${duration}`,
        `bytes: ${item.bytes || 0}`,
        ...proxyTelemetryLines(item),
        `proxy: :${proxy.port} -> ${_proxyUpstreamStr(proxy)}`,
      ].filter(Boolean).join("\n"),
      item,
      incident,
    };
  }
  if (latest) {
    const duration = topologyFormatDuration(latest.durationMs || topologyDurationMs(latest.startedAt, latest.finishedAt));
    const status = String(latest.status || "?");
    const isError = latest.error || !status.startsWith("2");
    const state = isError ? "error" : "recent";
    const incident = topologyIncidentForItem(latest);
    const health = topologyIncidentHealth(latest, isError ? "failed" : "ok");
    return {
      state,
      health,
      label: `${status} ${duration}`,
      title: [
        incident ? `Incident: ${incident.title} - ${incident.summary}` : "",
        `${proxy.label || proxy.port} last request`,
        `${latest.method || "POST"} ${latest.path || ""}`,
        `status: ${status}`,
        `duration: ${duration}`,
        `client: ${latest.client || "?"}`,
        `bytes: ${latest.bytes || 0}`,
        ...proxyTelemetryLines(latest),
        latest.error ? `error: ${latest.error}` : "",
      ].filter(Boolean).join("\n"),
      item: latest,
      incident,
    };
  }
  return { state: "idle", label: "", title: "" };
}

export function topologyLlamaActivity(port) {
  const overview = topologyRuntimeOverview();
  const correlated = ui.latestSystemMonitor?.latest?.correlatedActivity?.llamaServer;
  if (correlated && (!port || Number(correlated.port) === Number(port))) {
    const activeCount = Number(correlated.activeRequestCount || 0);
    const processing = Number(correlated.processingSlotCount || 0);
    const context = correlated.context || {};
    const cache = correlated.promptCache || {};
    if (activeCount || processing) {
      return {
        state: "active",
        label: `${overview.running.length || activeCount} running${overview.queued.length ? ` · ${overview.queued.length} queued` : ""}`,
        summary: [
          context.tokens ? `ctx ${context.tokens}/${context.limit || "?"}` : "",
          cache.prompts ? `cache ${Math.round(cache.usedMiB || 0)}/${Math.round(cache.limitMiB || 0)} MiB` : "",
        ].filter(Boolean).join(" · "),
      };
    }
    if (context.tokens || cache.prompts) {
      return {
        state: "recent",
        label: context.tokens ? `ctx ${context.pct ?? "?"}%` : `${cache.prompts} cache`,
        summary: [
          context.tokens ? `context ${context.tokens}/${context.limit || "?"}` : "",
          cache.prompts ? `cache ${Math.round(cache.usedMiB || 0)}/${Math.round(cache.limitMiB || 0)} MiB` : "",
        ].filter(Boolean).join(" · "),
      };
    }
  }
  const related = (topology?.proxies || []).filter((proxy) => Number(proxy.upstreamPort || 0) === Number(port || 0));
  const entries = related.map((proxy) => ({ proxy, activity: topologyProxyActivity(proxy) }));
  const active = entries.filter((entry) => entry.activity.state === "active");
  const errors = entries.filter((entry) => entry.activity.state === "error");
  const recent = entries.filter((entry) => entry.activity.state === "recent");
  const activeOrRecent = [...active, ...errors, ...recent];
  const items = activeOrRecent.map((entry) => entry.activity.item).filter(Boolean);
  const clients = new Set(items.map((item) => item.client).filter(Boolean));
  const routes = new Set(activeOrRecent.map((entry) => entry.proxy.label || `:${entry.proxy.port}`));
  const usageTotal = items.reduce((sum, item) => {
    const usage = item.response?.usage || item.stream?.usage || {};
    return sum + Number(usage.total_tokens || 0);
  }, 0);
  if (active.length) {
    return {
      state: "active",
      label: `${active.length} active`,
      summary: [
        `${clients.size || active.length} clients`,
        `${routes.size || active.length} routes`,
        usageTotal ? `${usageTotal} tok` : "",
      ].filter(Boolean).join(" · "),
    };
  }
  if (errors.length) {
    return {
      state: "error",
      label: `${errors.length} error`,
      summary: `${clients.size || errors.length} clients · ${routes.size || errors.length} routes`,
    };
  }
  if (recent.length) {
    return {
      state: "recent",
      label: `${recent.length} recent`,
      summary: [
        `${clients.size || recent.length} clients`,
        `${routes.size || recent.length} routes`,
        usageTotal ? `${usageTotal} tok` : "",
      ].filter(Boolean).join(" · "),
    };
  }
  return { state: "idle", label: "", summary: "" };
}

export function topologyGpuActivity() {
  const overview = topologyRuntimeOverview();
  const correlated = ui.latestSystemMonitor?.latest?.correlatedActivity?.gpu;
  if (correlated) {
    const activeCount = Number(correlated.activeRequestCount || 0);
    const processing = Number(correlated.processingSlotCount || 0);
    if (activeCount || processing) {
      return {
        state: "active",
        label: `${overview.running.length || activeCount} running${overview.queued.length ? ` · ${overview.queued.length} queued` : ""}`,
        summary: [
          `${overview.running.length || activeCount} running`,
          overview.queued.length ? `${overview.queued.length} queued` : "",
          correlated.activeClients?.length ? `${correlated.activeClients.length} clients` : "",
          correlated.activeRoutes?.length ? `${correlated.activeRoutes.length} routes` : "",
          `${correlated.utilPct || 0}% GPU`,
          correlated.memoryPct ? `${correlated.memoryPct}% VRAM` : "",
        ].filter(Boolean).join(" · "),
      };
    }
  }
  const activity = ui.latestSystemMonitor?.latest?.llamaActivity || {};
  const activeSlots = Array.isArray(activity.activeSlots) ? activity.activeSlots : [];
  const processing = activeSlots.filter((slot) => slot.isProcessing);
  const proxyAgents = ui.latestSystemMonitor?.latest?.agentProxies?.agents || {};
  const proxyActive = Object.values(proxyAgents).flatMap((row) => Array.isArray(row.active) ? row.active : []);
  const proxyRecent = Object.values(proxyAgents).flatMap((row) => Array.isArray(row.recent) ? row.recent.slice(-1) : []);
  if (processing.length) {
    return {
      state: "active",
      label: `${processing.length} processing`,
      summary: [
        `${activeSlots.length || processing.length} slots`,
        proxyActive.length ? `${proxyActive.length} proxy req` : "",
      ].filter(Boolean).join(" · "),
    };
  }
  const recent = Array.isArray(activity.recentRequests) ? activity.recentRequests : [];
  if (recent.length) {
    const row = recent[recent.length - 1] || {};
    return {
      state: "recent",
      label: "",
      summary: [
        `${recent.length} llama recent`,
        proxyRecent.length ? `${proxyRecent.length} proxy routes` : "",
      ].filter(Boolean).join(" · "),
    };
  }
  return { state: "idle", label: "", summary: "" };
}

export function proxyEffectiveWaitTimeout(proxy) {
  const direct = Number(proxy?.clientTimeoutSeconds || 0);
  if (direct > 0) return direct;
  // Scan all client routes for one pointing at this proxy port, then use
  // topologyRouteTimeoutSec (which reads OpenClaw provider config) to get real timeout
  const port = String(proxy?.port || "");
  if (!port) return 0;
  const portStr = `:${port}`;
  for (const client of (topology?.clients || [])) {
    for (const assignment of topologyAssignmentsForHost(client.id)) {
      for (const route of (assignment.routes || [])) {
        if (String(route.endpoint || "").includes(portStr)) {
          const agent = (client.agents || []).find((a) => a.id === assignment.agentId);
          const t = topologyRouteTimeoutSec(client, agent, route);
          if (t > 0) return t;
        }
      }
    }
  }
  return 0;
}

export function topologyRouteTimeoutSec(client, agent, route) {
  const cfg = topology?.openclawConfigs?.[client?.id]?.data;
  if (!cfg || !route) return 0;
  const defaults = cfg.agents?.defaults || {};
  let timeout = Number(defaults.timeoutSeconds || 0);
  const port = String(route.endpoint || "").match(/:(\d+)/)?.[1];
  if (port) {
    const providers = cfg.models?.providers || {};
    for (const prov of Object.values(providers)) {
      if (String(prov?.baseUrl || "").includes(`:${port}`)) {
        if (prov.timeoutSeconds) timeout = Number(prov.timeoutSeconds);
        break;
      }
    }
  }
  return timeout || 0;
}

export function topologyRouteTimeoutHtml(client, agent, route, activity) {
  const timeoutSec = topologyRouteTimeoutSec(client, agent, route);
  if (!timeoutSec) return "";
  const item = activity?.item;
  const totalMs = timeoutSec * 1000;
  if (item && topologyIsQueuedItem(item)) {
    // Queued: show remaining client budget as a depleting bar (same style as running).
    const rt = topologyQueueRuntime(item);
    // rt.leftMs is time until abort (abortPct% of clientTimeout). Scale back to full budget.
    const queuedMs = rt.queuedMs;
    const leftMs = Math.max(0, totalMs - queuedMs);
    const leftPct = Math.max(0, Math.min(100, (leftMs / totalMs) * 100));
    const label = t("topologyTimeoutWaiting", { left: topologyFormatDuration(leftMs), total: timeoutSec });
    return `<div class="topology-route-timeout waiting queued"><span>${escapeHtml(label)}</span><span class="topology-wait-bar" aria-hidden="true"><i style="animation-duration:${Math.round(leftMs)}ms;--queue-start:${leftPct.toFixed(2)}%"></i></span></div>`;
  }
  const running = item && (activity.state === "active" || activity.state === "running");
  if (running) {
    const elapsedMs = Number(item.elapsedMs || topologyDurationMs(item.startedAt));
    const leftMs = Math.max(0, totalMs - elapsedMs);
    const leftPct = Math.max(0, Math.min(100, (leftMs / totalMs) * 100));
    const label = t("topologyTimeoutWaiting", { left: topologyFormatDuration(leftMs), total: timeoutSec });
    return `<div class="topology-route-timeout waiting"><span>${escapeHtml(label)}</span><span class="topology-wait-bar" aria-hidden="true"><i style="animation-duration:${Math.round(leftMs)}ms;--queue-start:${leftPct.toFixed(2)}%"></i></span></div>`;
  }
  return `<div class="topology-route-timeout"><span>${escapeHtml(t("topologyTimeoutIdle", { total: timeoutSec }))}</span></div>`;
}

// ── Per-hour error badge on route rows ───────────────────────────────────────
// ui.routeErrHour (port → {errors, byKind}) is refreshed once a minute from
// /api/agent-proxy-logs?summary=1&since=60; the badge shows from 3 failures/h.
const ROUTE_ERR_BADGE_MIN = 3;

function routeErrTitle(st) {
  const kinds = Object.entries(st.byKind || {}).map(([k, v]) => `${k} ${v}`).join(", ");
  return `${st.errors} failed request${st.errors === 1 ? "" : "s"} in the last hour${kinds ? `: ${kinds}` : ""}`;
}

function routeErrBadgeHtml(port) {
  const st = port && ui.routeErrHour ? ui.routeErrHour[String(port)] : null;
  if (!st || (st.errors || 0) < ROUTE_ERR_BADGE_MIN) return "";
  return `<span class="route-err-badge" title="${escapeHtml(routeErrTitle(st))}">⚠ ${st.errors}</span>`;
}

export async function refreshRouteErrBadges() {
  try {
    const d = await api("/api/agent-proxy-logs?summary=1&since=60");
    ui.routeErrHour = d.summary || {};
  } catch {
    return;  // keep the previous cache; the board just misses one refresh
  }
  // Patch in place too, so badges update without waiting for a full re-render.
  document.querySelectorAll(".topology-agent-route .route-port-chip").forEach((chip) => {
    const st = ui.routeErrHour[chip.textContent.trim()];
    let badge = chip.parentElement.querySelector(".route-err-badge");
    if (st && (st.errors || 0) >= ROUTE_ERR_BADGE_MIN) {
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "route-err-badge";
        chip.after(badge);
      }
      badge.textContent = `⚠ ${st.errors}`;
      badge.title = routeErrTitle(st);
    } else if (badge) {
      badge.remove();
    }
  });
}

// usage: "confirmed" | "unused" | "unverified" (see topologyRouteUsage). It used
// to be a boolean, which had no room for "the agent never told us".
export function topologyAgentRouteRow(client, agent, role, route, usage = "confirmed") {
  const activity = route ? topologyProxyActivity(route.proxyId || "") : null;
  const incident = activity?.incident || topologyIncidentForItem(activity?.item);
  // The proxy port is now shown ON this route row (no separate proxy column). The
  // handle is just the cable anchor for the proxy's entry point. A role
  // the agent doesn't currently use is "muted": still wired + provisioned, but faint.
  const proxy = route ? (topology?.proxies || []).find((p) => p.id === route.proxyId) : null;
  const port = proxy?.port || (route?.proxyId || "").split(":").pop() || "";
  const muted = !!route && usage === "unused";
  const unverified = !!route && usage === "unverified";
  const handle = route ? `
    <span class="topology-handle output ${escapeHtml(role)} ${muted ? "muted" : ""}"
      data-topology-route-handle="1"
      data-host-id="${escapeHtml(client.id || "")}"
      data-agent-id="${escapeHtml(agent.id || "")}"
      data-route-role="${escapeHtml(role)}"
      data-proxy-id="${escapeHtml(route.proxyId || "")}"
      title="${escapeHtml(muted ? `${role} (inactive)` : unverified ? `${role} — ${t("taTitleUnverifiedRoute")}` : role)}"></span>
  ` : "";
  const detailAttrs = route ? ` data-topology-route-detail="${escapeHtml(route.proxyId || "")}" data-client-ip="${escapeHtml(client?.ip || "")}" data-client-name="${escapeHtml(client?.name || client?.id || "")}" tabindex="0" role="button"` : "";
  const timeoutHtml = route ? topologyRouteTimeoutHtml(client, agent, route, activity) : "";
  return `
    <div class="topology-agent-route ${escapeHtml(role)} ${route ? "" : "empty"} ${muted ? "muted" : ""} ${unverified ? "unverified" : ""} ${escapeHtml(topologyStateHealthClasses(activity))}"${detailAttrs}>
      ${handle}
      <span class="route-role-label">${escapeHtml(role)}${port ? `<span class="route-port-chip" title="${escapeHtml(t("taTitleProxyPort"))}">${escapeHtml(port)}</span>` : ""}${routeErrBadgeHtml(port)}</span>
      <code>${route ? escapeHtml(route.endpoint || "") : "-"}${muted ? ` <span class="route-muted-tag" title="${escapeHtml(t("taTitleMutedRoute"))}">${escapeHtml(t("taInactive"))}</span>` : ""}${unverified ? ` <span class="route-unverified-tag" title="${escapeHtml(t("taTitleUnverifiedRoute"))}">${escapeHtml(t("taUnverified"))}</span>` : ""}</code>
      ${timeoutHtml}
      ${incident ? `<small class="topology-incident-line ${incident.kind === "failed" ? "failed" : ""}">${escapeHtml(`${incident.title}: ${incident.summary}`)}</small>` : ""}
    </div>
  `;
}

