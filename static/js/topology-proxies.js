// Agent cards and the proxy routes' registry. A client has no port of its own (2026-11-07): the form that gave one left.
import { _cvProxyToAgent } from "./canvas.js";
import { t } from "./i18n.js";
import { topology } from "./state.js";
import { CARD_FOLD, CardFold } from "./card-fold.js";
import { AgentRow, FoldSlot } from "./card-rows.js";
import {
  routeAddressTip,
  routeErrBadgeHtml,
  routeRowClient,
  routeHandleHtml,
  routeIncident,
  routeStateFace,
  routeWaitSec,
  sortedTopologyAgents,
  topologyAgentGroup,
  topologyAgentMeta,
  topologyAgentRouteRow,
  topologyAssignmentsByAgent,
  agentCallerHtml,
  sortedLaneCards,
  sortedTopologyClients,
} from "./topology-activity.js";
import { escapeHtml } from "./utils.js";

// True if the proxy's agent was manually deleted (tombstoned) — not in client.agents anymore.
export function _cvProxyIsTombstoned(p) {
  const info = _cvProxyToAgent().get(String(p.id));
  if (!info?.agentId || !info?.hostId) return false;
  const client = (topology?.clients || []).find((c) => c.id === info.hostId);
  if (!client || !(client.agents?.length)) return false;
  return !client.agents.some((a) => a.id === info.agentId);
}

// `fold` asks for the lane's folding (card-fold.js): a quiet agent becomes its
// header and one line per route, and the full card floats open on hover.
// Without it the card is drawn exactly as it always was.
export function topologyAgentCard(client, agent, routeMap, { fold = false } = {}) {
  const routes = routeMap.get(agent.id) || new Map();
  const primary = routes.get("primary");
  const fallback = routes.get("fallback");

  // Every agent can be removed by hand. The record is the operator's: no
  // report adds it, none takes it away, and none may call it dead — so the ✕
  // is not reserved for agents a scout once reported, as it used to be.
  const deleteBtn = `<button class="agent-remove-btn" type="button" data-t="agent-remove"
        title="${escapeHtml(t("agentRemoveTitle"))}"
        data-agent-delete-client="${escapeHtml(client.id)}"
        data-agent-delete-id="${escapeHtml(agent.id)}">×</button>`;

  const foldKey = CardFold.agentKey(client.id, agent.id);
  // When a request last came through the agent's ports (AgentRow.dot): its dot and its line's.
  const seen = Math.max(0, ...[primary, fallback].map((route) => Number((topology?.proxies || [])
    .find((p) => route && p.id === route.proxyId)?.lastRequestAt || 0)));
  const foldMode = fold
    ? CARD_FOLD.mode("clients", foldKey, CardFold.agentQuiet({
        routes: (primary ? 1 : 0) + (fallback ? 1 : 0),
        incident: !!(routeIncident(primary) || routeIncident(fallback)),
      }))
    : "full";
  const kind = [agent.kind || "manual", topologyAgentMeta(agent)].filter(Boolean).join(" · ");
  // An agent that goes nowhere says so. Its card used to be two quiet empty
  // frames — "primary +", "fallback +" — and read as an agent at rest.
  const noRoute = !primary && !fallback
    ? `<div class="agent-noroute" data-t="agent-no-route">⚠ ${escapeHtml(t("agentNoRoute"))}</div>`
    : "";
  const card = (anchor) => `
    <div class="topology-agent ${escapeHtml(topologyAgentGroup(agent))} has-remove" data-topology-agent="1" data-host-id="${escapeHtml(client.id)}" data-agent-id="${escapeHtml(agent.id)}">
      ${deleteBtn}
      <div class="topology-agent-summary">
        ${AgentRow.dot(seen, "topology-port-dot")}
        <div>
          <div class="agent-title-line">
          <strong>${escapeHtml(agent.name || agent.id)}</strong>
          <!-- Rename the agent's block. The card used to have only a ✕: the
               name could be seen but not changed, even though the CLIENT
               card has had a ✎ from the start. -->
          <button class="client-rename-btn" type="button" data-t="agent-rename"
            title="${escapeHtml(t("topologyAgentRename"))}"
            data-agent-rename="${escapeHtml(agent.id || "")}"
            data-agent-rename-client="${escapeHtml(client?.id || "")}"
            data-agent-rename-name="${escapeHtml(agent.name || agent.id || "")}">✎</button>
          <!-- A client is one card: no ＋ for a second agent here — a card
               per client, made with the lane's ＋ — and no "delete client":
               the card's own × removes it. A red ✕ that removed the whole
               client took ten agents with one press (2026-09-24). -->
          <!-- The agent's kind sits on the same line as its name, pushed to
               the right: on its own line it took up a whole row for two
               words and stretched the header out vertically. -->
          ${agentCallerHtml([primary, fallback])}
          <span class="agent-kind">${escapeHtml(kind)}</span>
          </div>
          ${agent.endpoint || agent.url ? `<code>${escapeHtml(agent.endpoint || agent.url)}</code>` : ""}
        </div>
      </div>
      ${noRoute}<div class="topology-agent-routes">
        ${topologyAgentRouteRow(client, agent, "primary", primary, topologyRouteUsage(primary), { anchor })}
        ${topologyAgentRouteRow(client, agent, "fallback", fallback, topologyRouteUsage(fallback), { anchor })}
      </div>
    </div>
  `;
  if (foldMode === "full") return card(true);
  if (foldMode === "pinned") return new FoldSlot({ key: foldKey, lane: "clients", mode: "pinned", card: card(true) }).html();
  // The fold's facts come from the same fields the card's chips read; the
  // handles move to the line, so exactly one element per route carries them.
  const lineRoute = (role, route) => {
    if (!route) return null;
    const usage = topologyRouteUsage(route);
    const model = String(route.modelName || "").trim();
    // No number: an agent is pointed at no port of its own any more (2026-11-07).
    return {
      role, port: "", address: routeAddressTip(route), face: routeStateFace(usage),
      model, locked: !!model && !route.modelNameAuto, waitSec: routeWaitSec(route).sec,
      limit: Number(route.contextLength || 0) > 0 ? Number(route.contextLength) : 0,
      errBadge: routeErrBadgeHtml(routeRowClient(route)), anchor: routeHandleHtml(client, agent, role, route, usage),
    };
  };
  const line = new AgentRow({
    key: foldKey, name: agent.name || agent.id, kind, seen,
    routes: [lineRoute("primary", primary), lineRoute("fallback", fallback)],
  }).html();
  return new FoldSlot({ key: foldKey, lane: "clients", mode: "line", line, card: card(false),
                        peek: CARD_FOLD.peekKey === foldKey }).html();
}

// Lane cards for a SINGLE client: itself first, then EVERY one of its agents
// as its own block. Agents lumped into one card read as a single entity,
// even though they're different consumers with different ports and
// different context windows — and the lane is named "clients and their
// proxies".
//
// Every client's agents are drawn this way: every client is made by hand now.
// A scout's client used to keep its agents grouped HOST/VMS/DOCKER/OTHER inside
// its host card — the scout's word for where each one lived, gone with the
// scout's word about agents (2026-09-24).
export function clientLaneAgentCards(client, assignments) {
  const routeMap = topologyAssignmentsByAgent(assignments);
  const agents = sortedTopologyAgents(client.agents || []);
  return agents.map((agent) => {
    const routes = [...(routeMap.get(agent.id) || new Map()).values()];
    return { agentId: agent.id, name: agent.name || agent.id || "", html: topologyAgentCard(client, agent, routeMap, { fold: true }),
             idle: agentIsIdle(routes) };
  });
}

// How many hours this agent's proxy has carried no traffic. Computed from
// the most recent successful request across all its roles; none within the
// log's window (7 days) gives Infinity, not zero: "never, as far as we've
// seen" and "just now" are different answers, and confusing them is not allowed.
export function agentIdleHours(routes, nowSec = Date.now() / 1000) {
  const byId = new Map((topology?.proxies || []).map((p) => [String(p.id), p]));
  let last = 0;
  for (const route of routes || []) {
    const proxy = byId.get(String(route?.proxyId || ""));
    last = Math.max(last, Number(proxy?.lastRequestAt || 0));
  }
  if (!last) return Infinity;
  return Math.max(0, (nowSec - last) / 3600);
}

export const AGENT_IDLE_HOURS = 12;

// Idle means no successful request through its proxy longer than the
// threshold. This is an observation about traffic, not about a client's
// liveness: an agent can be alive and simply quiet, and the card says
// exactly that — in yellow, not red.
export function agentIsIdle(routes, nowSec = Date.now() / 1000) {
  return agentIdleHours(routes, nowSec) >= AGENT_IDLE_HOURS;
}

// A client is live when at least one of its agents carried a successful request
// within AGENT_IDLE_HOURS — the same measure that frames a quiet agent's card
// yellow. It ranks the lane blocks that stand for a whole client (a caption); a
// client with no agents, or whose agents are all quiet, is not live.
export function clientIsLive(client, nowSec = Date.now() / 1000) {
  const routeMap = topologyAssignmentsByAgent(topologyBoardAssignmentsForHost(client?.id));
  return (client?.agents || []).some((agent) => {
    const routes = [...(routeMap.get(agent.id) || new Map()).values()];
    return !agentIsIdle(routes, nowSec);
  });
}

// Whether a client needs a caption row of its own: a thin line with its name
// and the ✎ ＋ ✕ that manage it. A client with exactly one agent does not —
// that agent's card takes the client's controls over. With none, or several,
// the caption carries them: otherwise a "delete client" button would repeat
// on every agent, and the operator would have to guess which one is the real
// one.
//
// Every client is the operator's record now; the machine a scout reports is a
// node of its own (docs/scout-split.md). The host card that used to stand in
// for the caption, wherever a scout was, went with it.
export function clientNeedsCaption(agentCount) {
  return agentCount !== 1;
}

// Routing clients come from the SOURCE OF TRUTH — the main board — not from the
// list of ports. Routing used to enumerate routes, so it held rows the main
// board never had (a host with a port number for a name, an app's label) — two
// pictures of one fleet, and the screen could not say which one was true.
//
// A port wired into the graph but owned by nobody on the main board is NOT
// hidden: it comes back separately, so Routing says it out loud. Silently
// dropping a routed input is exactly absence rendered as normality.
export function canvasBoardClients(proxies) {
  const byId = new Map();
  for (const p of proxies || []) byId.set(String(p.id), p);
  const rows = [];
  const claimed = new Set();
  // Ports are claimed in name order (a port belongs to the first agent that names
  // it); the rows are then ordered as the board's cards are — the live agents
  // first, the quiet ones after, by name inside each group.
  for (const client of sortedTopologyClients(topology?.clients || [])) {
    // Ordering and a port's claim to a name both go by the agent's SHOWN
    // name — the same one on the lane card. While agentId stood here
    // instead, an alias split one fleet into two pictures: an agent whose id
    // is "openclaw" but which the board labels with an alias sat in the lane
    // under the alias's letter and here under "o".
    const shownName = new Map((client.agents || [])
      .map((a) => [String(a?.id || ""), String(a?.name || a?.id || "")]));
    for (const row of sortedTopologyAgents(topologyBoardAssignmentsForHost(client.id)
        .map((r) => ({ ...r, name: shownName.get(String(r.agentId)) || r.agentId })))) {
      const own = [];
      for (const route of (row?.routes || [])) {
        const proxy = byId.get(String(route?.proxyId || ""));
        if (proxy && !claimed.has(String(proxy.id))) { own.push(proxy); claimed.add(String(proxy.id)); }
      }
      if (own.length) rows.push({ key: `${client.id}::${row.agentId}`, clientId: client.id,
                                  agentId: row.agentId, proxies: own,
                                  name: row.name || row.agentId, live: !agentIsIdle(row.routes || []) });
    }
  }
  return { rows: sortedLaneCards(rows), unclaimed: (proxies || []).filter((p) => !claimed.has(String(p.id))) };
}

// Where each of a client's agents goes: the stored rows, and nothing else.
// No report speaks of agents any more (2026-09-24), so the record is the only
// truth there is and is drawn as it is. The board used to merge the scout's
// live report in — liveness from the report, settings from the record, an id
// recovered from the endpoint's port, a fallback inferred as the primary's +1
// pair — because the report said which port an agent really used.
export function topologyAssignmentsForHost(hostId) {
  const rows = topology?.assignments?.[hostId]?.assignments;
  return Array.isArray(rows) ? rows : [];
}

// The board draws exactly the stored rows. The merging reader kept its name for
// its callers: one reading, two names, no second rule.
export function topologyBoardAssignmentsForHost(hostId) { return topologyAssignmentsForHost(hostId); }

// Whether a route is known to be used. Caravan always knows what it assigned;
// use is known only from traffic: a route that carried a request within the
// log's window is "confirmed", one that did not is "unverified" — unknown, not
// unused. Collapsing the two made a silent agent look like a healthy one:
// absence drawn as normality. The third answer, "unused", was the agent's own
// word relayed by the scout, and went with it (2026-09-24).
export function topologyRouteUsage(route) {
  const proxy = route?.proxyId
    ? (topology?.proxies || []).find((p) => p.id === route.proxyId)
    : null;
  return Number(proxy?.lastRequestAt || 0) > 0 ? "confirmed" : "unverified";
}

export function sortedTopologyRoutes(routes) {
  const order = { primary: 0, fallback: 1 };
  return routes.slice().sort((left, right) => {
    const a = order[left.role] ?? 20;
    const b = order[right.role] ?? 20;
    return a - b || String(left.role || "").localeCompare(String(right.role || ""));
  });
}

// The proxy runs on the controller, so a server is addressed as its machine's
// scout reported it: its LAN IP, or loopback for the controller's own machine
// (its scout was paired at 127.0.0.1 — the controller's own cells, which were
// loopback by a flag of their own, went in step 6.9). Kept in sync with the
// data-llama-host stamped on server handles.
export function topologyServerUpstreamHost(s, node) {
  return (s && s.clientIp) || (node && node.ip) || "127.0.0.1";
}

// A client of the entry (kind "consumer", 2026-10-12) never feeds a router: its one cable leads
// to a pool, and the pool's rows decide — the same rule the server's normalizer keeps
// (rust/crates/admin/src/proxies/dsl.rs), which clears its router binding on every save.
export function feedsRouters(proxy) {
  return String(proxy.kind || "") !== "consumer";
}

export function isEntryClient(proxy) {
  return String(proxy?.kind || "") === "consumer";
}

export function topologyProxyGroupInfo(proxy) {
  const label = String(proxy.label || "").trim();
  const match = label.match(/^(.*)\s+(primary|fallback)$/i);
  if (!match) {
    return { key: `single:${proxy.id}`, title: label || String(proxy.id || ""), role: "", grouped: false };
  }
  return {
    key: `group:${match[1].trim().toLowerCase()}`,
    title: match[1].trim(),
    role: match[2].toLowerCase(),
    grouped: true,
  };
}

export function topologyProxyOwner(proxyId) {
  // Returns {clientId, clientName, agentId, agentName, title, role} if the proxy is assigned to a client agent.
  for (const client of (topology?.clients || [])) {
    for (const assignment of topologyAssignmentsForHost(client.id)) {
      for (const route of (assignment.routes || [])) {
        if (route.proxyId === proxyId) {
          const agent = (client.agents || []).find((a) => a.id === assignment.agentId);
          const agentId = agent?.id || assignment.agentId;
          const agentName = agent?.name || agentId;
          // Host OpenClaw agent → use client name; docker/other agents → use agent name
          const title = (agentId === "openclaw")
            ? (client.name || client.id)
            : agentName;
          return {
            clientId: client.id,
            clientName: client.name || client.id,
            agentId: assignment.agentId,
            agentName,
            title,
            role: route.role || "primary",
            // live = the assigned agent is still reported by the host. When false
            // the port is owned only by a dead assignment (agent gone) → orphan.
            live: !!agent,
          };
        }
      }
    }
  }
  return null;
}

export function groupedTopologyProxies(proxies) {
  const groups = new Map();
  proxies.forEach((proxy) => {
    const owner = topologyProxyOwner(proxy.id);
    if (owner) {
      const key = `client:${owner.clientId}:${owner.agentId}`;
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          title: owner.title,
          role: "",
          grouped: true,
          proxies: [],
        });
      }
      groups.get(key).proxies.push({ ...proxy, topologyRole: owner.role });
    } else {
      // Standalone proxy — fall back to name-suffix grouping
      const info = topologyProxyGroupInfo(proxy);
      if (!groups.has(info.key)) groups.set(info.key, { ...info, proxies: [] });
      groups.get(info.key).proxies.push({ ...proxy, topologyRole: info.role });
    }
  });

  // Merge name-suffix groups (key: "group:*") into client-based groups that share
  // the same title. This handles cloud fallback proxies that aren't wired via a
  // client assignment route but whose label encodes the agent name, e.g.
  // "agent-a fallback" (base "agent-a") belongs with the client-owned primary proxy.
  // Single-proxy groups ("single:*") are left alone — they have no reliable role.
  const titleToClientKey = new Map(
    [...groups.entries()]
      .filter(([k]) => k.startsWith("client:"))
      .map(([k, g]) => [g.title.toLowerCase(), k])
  );
  for (const [key, group] of [...groups.entries()]) {
    if (!key.startsWith("group:")) continue;
    const clientKey = titleToClientKey.get(group.title.toLowerCase());
    if (!clientKey) continue;
    const target = groups.get(clientKey);
    for (const p of group.proxies) {
      // Only merge when the role is explicit and not already filled in the target.
      if (p.topologyRole && !target.proxies.some((t) => t.topologyRole === p.topologyRole)) {
        target.proxies.push(p);
      }
    }
    groups.delete(key);
  }

  return [...groups.values()].map((group) => ({
    ...group,
    proxies: group.proxies.sort((a, b) => {
      const order = { primary: 0, fallback: 1 };
      return (order[a.topologyRole] ?? 10) - (order[b.topologyRole] ?? 10) || String(a.label || "").localeCompare(String(b.label || ""));
    }),
  }));
}

export function proxyGroupCloudProviderId(proxy) {
  // Find the group this proxy belongs to, then find a cloud sibling within it.
  const sorted = (topology?.proxies || []).slice().sort((a, b) => String(a.label || "").localeCompare(String(b.label || "")));
  const group = groupedTopologyProxies(sorted).find((g) => g.proxies.some((p) => p.id === proxy.id));
  if (!group) return "";
  const cloud = group.proxies.find((p) => String(p.upstreamType || "llama") === "cloud" && p.providerId);
  return cloud?.providerId || "";
}

