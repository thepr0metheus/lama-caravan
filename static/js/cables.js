// SVG cable drawing between board cards.
import { topologyOutputActivity } from "./routers.js";
import { state, topology } from "./state.js";
import { topologyProxyActivity, topologyStateHealthClasses } from "./topology-activity.js";
import { topologyPointerDrag } from "./topology-dnd.js";
import { topologyAgentActiveRoles, topologyBoardAssignmentsForHost } from "./topology-proxies.js";
import { $, escapeHtml } from "./utils.js";

export function topologyBoardRect() {
  return document.querySelector(".topology-board")?.getBoundingClientRect();
}

export function topologyPointFor(el, side = "center") {
  const board = topologyBoardRect();
  const rect = el?.getBoundingClientRect();
  if (!board || !rect) return null;
  const x = side === "left" ? rect.left : side === "right" ? rect.right : rect.left + rect.width / 2;
  return {
    x: x - board.left,
    y: rect.top + rect.height / 2 - board.top,
  };
}

export function topologyCablePath(from, to) {
  const dx = Math.max(48, Math.abs(to.x - from.x) * 0.48);
  return `M ${from.x} ${from.y} C ${from.x + dx} ${from.y}, ${to.x - dx} ${to.y}, ${to.x} ${to.y}`;
}

export function topologySvgPath(from, to, className, title = "") {
  if (!from || !to) return "";
  return `<path class="${className}" d="${topologyCablePath(from, to)}">${title ? `<title>${escapeHtml(title)}</title>` : ""}</path>`;
}

export function topologyApplyStateForHost(hostId) {
  const desired = topology?.assignments?.[hostId]?.applyStatus?.state;
  const client = (topology?.clients || []).find((row) => row.id === hostId);
  return desired || client?.applyStatus?.state || "stored";
}

export function topologyCableStatusClass(state) {
  if (state === "error" || state === "failed") return "status-error";
  if (state === "stale" || state === "pending") return "status-warn";
  return "status-ok";
}

export function topologyProxyClass(proxyId) {
  return `proxy-${String(proxyId || "").replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

export function topologyAccentStyle(key) {
  const hues = [174, 202, 268, 326, 36, 142, 218, 288, 18, 96, 234, 4];
  const text = String(key || "item");
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
  }
  const hue = hues[Math.abs(hash) % hues.length];
  return `--topology-accent: hsl(${hue} 70% 62%); --topology-accent-soft: hsl(${hue} 70% 62% / 0.13);`;
}

export function topologyAccentColor(key, alpha = 1) {
  const hues = [174, 202, 268, 326, 36, 142, 218, 288, 18, 96, 234, 4];
  const text = String(key || "item");
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(i)) | 0;
  }
  const hue = hues[Math.abs(hash) % hues.length];
  return `hsl(${hue} 70% 62% / ${alpha})`;
}

export function topologyRouteClass(hostId, agentId, role) {
  return `route-${[hostId, agentId, role].map((part) => String(part || "").replace(/[^A-Za-z0-9_-]/g, "-")).join("-")}`;
}

export let _cableHighlightClearTimer = null;

export function highlightTopologyCable(className) {
  if (!className) return;
  clearTimeout(_cableHighlightClearTimer);
  _cableHighlightClearTimer = null;
  document.querySelectorAll(".topology-cable").forEach((path) => {
    const active = path.classList.contains(className);
    path.classList.toggle("muted-by-hover", !active && !path.classList.contains("trunk"));
    path.classList.toggle("hovered", active);
  });
}

export function clearTopologyCableHighlight() {
  document.querySelectorAll(".topology-cable").forEach((path) => {
    path.classList.remove("muted-by-hover", "hovered");
  });
}

export function scheduleClearTopologyCableHighlight() {
  clearTimeout(_cableHighlightClearTimer);
  _cableHighlightClearTimer = setTimeout(clearTopologyCableHighlight, 5000);
}

export function topologySvgText(point, text, className = "topology-cable-label") {
  if (!point || !text) return "";
  return `<text class="${className}" x="${point.x}" y="${point.y}">${escapeHtml(text)}</text>`;
}

export function drawLiveTopologyCable(toClientX, toClientY) {
  const svg = $("topologyCables");
  const board = topologyBoardRect();
  const source = topologyPointerDrag?.source;
  if (!svg || !board || !source) return;
  const from = topologyPointFor(source, "right");
  const to = { x: toClientX - board.left, y: toClientY - board.top };
  const previous = svg.querySelector(".topology-cable.live");
  previous?.remove();
  if (!from) return;
  svg.insertAdjacentHTML("beforeend", topologySvgPath(from, to, "topology-cable live"));
}

export function drawTopologyCables() {
  const svg = $("topologyCables");
  const board = document.querySelector(".topology-board");
  if (!svg || !board || !topology) return;
  const rect = board.getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${Math.max(rect.width, 1)} ${Math.max(rect.height, 1)}`);
  svg.innerHTML = "";
  const paths = [];
  // Segment 1: client route handle (the proxy entry point, now on the client card)
  // → router input. The proxy is identified by route.proxyId; its router
  // (proxy.routerId) is the cable target. Muted/inactive roles draw a faint cable.
  (topology.clients || []).forEach((client) => {
    const assignments = topologyBoardAssignmentsForHost(client.id);
    assignments.forEach((assignment) => {
      const activeRoles = topologyAgentActiveRoles(client, assignment.agentId);
      (assignment.routes || []).forEach((route) => {
        const role = route.role || "primary";
        const source = document.querySelector(`[data-topology-route-handle][data-host-id="${CSS.escape(client.id)}"][data-agent-id="${CSS.escape(assignment.agentId)}"][data-route-role="${CSS.escape(role)}"]`);
        const proxy = (topology?.proxies || []).find((row) => row.id === route.proxyId);
        const routerId = proxy?.routerId || "";
        const target = document.querySelector(`[data-topology-router-input][data-router-id="${CSS.escape(routerId)}"]`);
        const muted = activeRoles ? !activeRoles.has(role) : false;
        const activity = topologyProxyActivity(route.proxyId || "");
        // Dim idle client→router cables (32 converge on one input) so the one
        // actually carrying a request stands out + animates — mirrors segment 3.
        const idle = !muted && activity.state === "idle";
        paths.push(topologySvgPath(
          topologyPointFor(source, "right"),
          topologyPointFor(target, "left"),
          `topology-cable ${escapeHtml(role)} ${muted ? "muted" : ""} ${idle ? "idle" : ""} ${Number(proxy?.priority || 0) > 0 ? "priority" : ""} ${topologyStateHealthClasses(activity)} ${topologyProxyClass(route.proxyId)} ${topologyRouteClass(client.id, assignment.agentId, role)}`,
        ));
      });
    });
  });
  // Segment 3: router output → llama server (or cloud). One cable per output;
  // only the output actually carrying a request animates (per-output activity).
  (topology.routers || []).forEach((router) => {
    (router.outputs || []).forEach((out) => {
      const source = document.querySelector(`[data-topology-router-output][data-router-id="${CSS.escape(router.id)}"][data-output-id="${CSS.escape(out.id)}"]`);
      const isCloud = String(out.upstreamType || "llama") === "cloud";
      // Cloud cable attaches to the PROVIDER (account), not a specific model-block.
      const target = isCloud
        ? document.querySelector(`[data-topology-cloud-input][data-account-id="${CSS.escape(String(out.accountId || ""))}"]`)
        : document.querySelector(`[data-topology-llama-input][data-llama-port="${CSS.escape(String(out.upstreamPort || ""))}"]`);
      const activity = topologyOutputActivity(out);
      paths.push(topologySvgPath(
        topologyPointFor(source, "right"),
        topologyPointFor(target, "left"),
        `topology-cable router ${isCloud ? "cloud" : ""} ${activity.state === "idle" ? "idle" : topologyStateHealthClasses(activity)}`,
      ));
    });
  });
  svg.innerHTML = paths.filter(Boolean).join("");
}

