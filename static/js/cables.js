// SVG cable drawing between board cards.
import { BOARD_VIEW } from "./board-view.js";
import { PoolReach } from "./provider-glances.js";
import { state, topology } from "./state.js";
import { topologyItemsActivity, topologyProxyActivity, topologyStateHealthClasses } from "./topology-activity.js";
import { topologyPointerDrag } from "./topology-dnd.js";
import { isEntryClient, topologyBoardAssignmentsForHost, topologyRouteUsage } from "./topology-proxies.js";
import { t } from "./i18n.js";
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

// A cable whose anchor or binding is missing renders to "" and used to disappear
// into filter(Boolean): no error, no console line, nothing on screen you could
// name — the board simply looked fine minus one curve. That silence hid a missing
// agent cable for a month (fixed in v1.3.92, and misdiagnosed twice before that).
// Every drop now says which cable it was and what was missing. Deduped by exact
// signature, because the board redraws on every activity change and would
// otherwise flood the console with the same line.
const _cableDropSigs = new Set();
export const cableDrops = [];
function noteCableDrop(what, why) {
  const entry = { what, ...why };
  const at = cableDrops.findIndex((d) => d.what === what);
  if (at >= 0) cableDrops[at] = entry; else cableDrops.push(entry);
  const sig = JSON.stringify(entry);
  if (_cableDropSigs.has(sig)) return;
  _cableDropSigs.add(sig);
  console.warn("[caravan] board cable not drawn —", what, why);
}

export function drawTopologyCables() {
  const svg = $("topologyCables");
  const board = document.querySelector(".topology-board");
  if (!svg || !board || !topology) return;
  const rect = board.getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${Math.max(rect.width, 1)} ${Math.max(rect.height, 1)}`);
  svg.innerHTML = "";
  const paths = [];
  cableDrops.length = 0;   // rebuilt every draw; the dedup set outlives it
  // A machine's own window shows its card alone (board-view.js): no cable has its other end there.
  // The clients and the kanban's node are in the page, hidden — a cable to them would start at
  // the corner of the board.
  if (BOARD_VIEW.isMachine) return;
  // Segment 1: client route handle (the proxy entry point, now on the client card)
  // → router input. The proxy is identified by route.proxyId; its router
  // (proxy.routerId) is the cable target. Muted/inactive roles draw a faint cable.
  (topology.clients || []).forEach((client) => {
    const assignments = topologyBoardAssignmentsForHost(client.id);
    assignments.forEach((assignment) => {
      (assignment.routes || []).forEach((route) => {
        const role = route.role || "primary";
        const source = document.querySelector(`[data-topology-route-handle][data-host-id="${CSS.escape(client.id)}"][data-agent-id="${CSS.escape(assignment.agentId)}"][data-route-role="${CSS.escape(role)}"]`);
        const proxy = (topology?.proxies || []).find((row) => row.id === route.proxyId);
        const routerId = proxy?.routerId || "";
        const target = document.querySelector(`[data-topology-router-input][data-router-id="${CSS.escape(routerId)}"]`);
        // "unverified" is NOT "in use": a route with no traffic in the log's
        // window used to be drawn exactly like a confirmed one, so a silent
        // agent and a healthy one were indistinguishable.
        const unverified = topologyRouteUsage(route) === "unverified";
        const activity = topologyProxyActivity(route.proxyId || "");
        // Dim idle client→router cables (32 converge on one input) so the one
        // actually carrying a request stands out + animates — mirrors segment 3.
        const idle = activity.state === "idle";
        const cable = topologySvgPath(
          topologyPointFor(source, "right"),
          topologyPointFor(target, "left"),
          `topology-cable ${escapeHtml(role)} ${unverified ? "unverified" : ""} ${idle ? "idle" : ""} ${Number(proxy?.priority || 0) > 0 ? "priority" : ""} ${topologyStateHealthClasses(activity)} ${topologyProxyClass(route.proxyId)} ${topologyRouteClass(client.id, assignment.agentId, role)}`,
          unverified ? t("taTitleUnverifiedRoute") : "",
        );
        if (!cable) {
          noteCableDrop(`${client.id}/${assignment.agentId} ${role} -> router`, {
            routeHandleFound: !!source,
            proxyId: route.proxyId || "(empty — live report carried none)",
            proxyResolved: !!proxy,
            routerId: routerId || "(unresolved)",
            routerInputFound: !!target,
          });
        }
        paths.push(cable);
      });
    });
  });
  // Segment 2: a client of the entry (consumers.js) → the kanban, lit by its requests (the owner,
  // 2026-10-11: a client's activity on the cables, as the agents' was). Its one cable leads to a set
  // of models (2026-10-12), and the sets and pools stand on the kanban, not on the main board: on the
  // main board the cable comes into the kanban's card. A client no cable reaches (`set`, the
  // controller's reading) has none here either. Every request of the client goes down it, whichever
  // pool and row serve it.
  const kanban = document.querySelector('[data-topology-router-input][data-router-id="router:default"]');
  (topology.proxies || []).filter(isEntryClient).forEach((p) => {
    if (!String(p.set || "")) return;
    const source = document.querySelector(`[data-topology-proxy-output][data-proxy-id="${CSS.escape(p.id)}"]`);
    const activity = topologyItemsActivity((it, port) => port === Number(p.port));
    const cable = topologySvgPath(topologyPointFor(source, "right"), topologyPointFor(kanban, "left"),
      `topology-cable consumer ${activity.state === "idle" ? "idle" : topologyStateHealthClasses(activity)} ${topologyProxyClass(p.id)}`);
    if (!cable) noteCableDrop(`client ${p.label || p.id} -> kanban`, { handleFound: !!source, kanbanFound: !!kanban });
    paths.push(cable);
  });
  // Segment 3: the kanban's card → the machines and the cloud providers its pools lead to (the owner,
  // 2026-10-12). The rows themselves are the kanban's (pool-board.js); here a cable says only that
  // requests can go there — a machine one of whose cells is a pool's row, an account a pool's row
  // calls (PoolReach) — and it lights while a request runs there: a cell's leg names its output
  // (`routedOutputId`), a provider's its account (`cloudAccountId`, caravan/proxy/handler.py).
  const out = document.querySelector('[data-topology-router-output][data-router-id="router:default"]');
  const reach = PoolReach.of(topology);
  const towards = (target, activity, what) => {
    const cable = topologySvgPath(topologyPointFor(out, "right"), topologyPointFor(target, "left"),
      `topology-cable router ${activity.state === "idle" ? "idle" : topologyStateHealthClasses(activity)}`);
    if (!cable) noteCableDrop(`kanban -> ${what}`, { kanbanOutputFound: !!out, targetFound: !!target });
    paths.push(cable);
  };
  reach.machines.forEach(({ key, outputs }) => towards(
    document.querySelector(`.machine-glance[data-node-id="${CSS.escape(key)}"] > .node-head`),
    topologyItemsActivity((it) => String(it.upstreamType || "") === "llama" && outputs.includes(String(it.routedOutputId || ""))),
    `machine ${key}`));
  reach.accounts.forEach((id) => towards(
    document.querySelector(`[data-board-provider="${CSS.escape(id)}"] > .node-head`),
    topologyItemsActivity((it) => String(it.cloudAccountId || "") === id),
    `provider ${id}`));
  svg.innerHTML = paths.filter(Boolean).join("");
}

