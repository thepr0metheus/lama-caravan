// SVG cable drawing between board cards.
import { BOARD_VIEW } from "./board-view.js";
import { CableFlow } from "./cable-flow.js";
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

// The classes of a cable that things find it by: the hovered handle lights the cables of its route or of its proxy.
const CABLE_KIN = /^(proxy|route)-/;

export function topologySvgPath(from, to, className, title = "", key = "") {
  if (!from || !to) return "";
  const d = topologyCablePath(from, to);
  const cable = `<path class="${className}" d="${d}">${title ? `<title>${escapeHtml(title)}</title>` : ""}</path>`;
  // A cable that carries a request now has its drops over it, both ways (cable-flow.js, cables.css). `key` names the cable, the same at every
  // drawing, so its drops come up when it begins to carry a request and go down when it stops.
  const classes = String(className).split(/\s+/);
  return classes.includes("activity-active")
    ? cable + CableFlow.twin(d, classes.filter((c) => CABLE_KIN.test(c)).join(" "), Date.now(), { key: key ? `main:${key}` : "", from, to })
    : cable;
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
  document.querySelectorAll(".topology-cable, .cable-flow").forEach((path) => {
    const active = path.classList.contains(className);
    path.classList.toggle("muted-by-hover", !active && !path.classList.contains("trunk"));
    path.classList.toggle("hovered", active);
  });
}

export function clearTopologyCableHighlight() {
  document.querySelectorAll(".topology-cable, .cable-flow").forEach((path) => {
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
  const from = topologyPointFor(source, "center");
  const to = { x: toClientX - board.left, y: toClientY - board.top };
  const previous = svg.querySelector(".topology-cable.live");
  previous?.remove();
  if (!from) return;
  svg.insertAdjacentHTML("beforeend", topologySvgPath(from, to, "topology-cable live"));
}

// The end of a cable on a card that has no dot of its own: a machine's head, a provider's. The head has the class
// `cable-end` while a cable comes to it — its dot (cables.css) then stands on its edge, as every cable's end does —
// and `flowing` while that cable carries a request. The lane draws its heads anew, so each drawing says which of them
// have a cable now, and the ones that had and have not lose the marks.
export class CableEnds {
  static marked = new Set();

  static mark(ends) {
    const now = new Set(ends.map((end) => end.el));
    for (const el of CableEnds.marked) if (!now.has(el)) el.classList?.remove("cable-end", "flowing");
    for (const { el, lit } of ends) {
      el.classList?.add("cable-end");
      el.classList?.toggle("flowing", !!lit);
    }
    CableEnds.marked = now;
  }
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
  // The clients and Routing's node are in the page, hidden — a cable to them would start at
  // the corner of the board.
  if (BOARD_VIEW.isMachine) { CableEnds.mark([]); return; }
  CableFlow.round();    // the drops of a cable this drawing does not carry go down, not off (cable-flow.js)
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
          topologyPointFor(source, "center"),
          topologyPointFor(target, "center"),
          `topology-cable ${escapeHtml(role)} ${unverified ? "unverified" : ""} ${idle ? "idle" : ""} ${Number(proxy?.priority || 0) > 0 ? "priority" : ""} ${topologyStateHealthClasses(activity)} ${topologyProxyClass(route.proxyId)} ${topologyRouteClass(client.id, assignment.agentId, role)}`,
          unverified ? t("taTitleUnverifiedRoute") : "",
          `route:${client.id}/${assignment.agentId}/${role}`,
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
  // Segment 2: a client of the entry (consumers.js) → Routing, lit by its requests (the owner,
  // 2026-10-11: a client's activity on the cables, as the agents' was). Its one cable leads to a set
  // of models (2026-10-12), and the sets and pools stand in Routing, not on the main board: on the
  // main board the cable comes into Routing's card. A client no cable reaches (`set`, the
  // controller's reading) has none here either. Every request of the client goes down it, whichever
  // pool and row serve it.
  const Routing = document.querySelector('[data-topology-router-input][data-router-id="router:default"]');
  (topology.proxies || []).filter(isEntryClient).forEach((p) => {
    if (!String(p.set || "")) return;
    const source = document.querySelector(`[data-topology-proxy-output][data-proxy-id="${CSS.escape(p.id)}"]`);
    const activity = topologyItemsActivity((it, port) => port === Number(p.port));
    const cable = topologySvgPath(topologyPointFor(source, "center"), topologyPointFor(Routing, "center"),
      `topology-cable consumer ${activity.state === "idle" ? "idle" : topologyStateHealthClasses(activity)} ${topologyProxyClass(p.id)}`, "", `consumer:${p.id}`);
    if (!cable) noteCableDrop(`client ${p.label || p.id} -> routing`, { handleFound: !!source, routingFound: !!Routing });
    paths.push(cable);
  });
  // Segment 3: Routing's card → the machines and the cloud providers its pools lead to (the owner,
  // 2026-10-12). The rows themselves are Routing's (pool-board.js); here a cable says only that
  // requests can go there — a machine one of whose cells is a pool's row, an account a pool's row
  // calls (PoolReach) — and it lights while a request runs there: a cell's leg names its output
  // (`routedOutputId`), a provider's its account (`cloudAccountId`, caravan/proxy/handler.py).
  const out = document.querySelector('[data-topology-router-output][data-router-id="router:default"]');
  const reach = PoolReach.of(topology);
  const ends = [];
  const towards = (target, activity, what) => {
    const cable = topologySvgPath(topologyPointFor(out, "center"), topologyPointFor(target, "left"),
      `topology-cable router ${activity.state === "idle" ? "idle" : topologyStateHealthClasses(activity)}`, "", `router:${what}`);
    if (!cable) noteCableDrop(`routing -> ${what}`, { routingOutputFound: !!out, targetFound: !!target });
    else ends.push({ el: target, lit: activity.state === "active" });
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
  svg.innerHTML = paths.filter(Boolean).join("") + CableFlow.ghosts();
  CableEnds.mark(ends);
}

