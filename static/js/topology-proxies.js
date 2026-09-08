// Agent cards and the proxy-route form/registry.
import { appConfirm } from "./dialogs.js";
import { _cvProxyToAgent } from "./canvas.js";
import { CONTROLLER_HOST_ID } from "./constants.js";
import { option } from "./form.js";
import { t } from "./i18n.js";
import { action } from "./polling.js";
import { state, topology, ui } from "./state.js";
import {
  sortedTopologyAgents,
  topologyAgentGroup,
  topologyAgentMeta,
  topologyAgentRouteRow,
  topologyAssignmentsByAgent,
  topologyGroupLabel,
  agentCallerHtml,
  sortedLaneCards,
  sortedTopologyClients,
} from "./topology-activity.js";
import { refreshTopology, renderTopology,
} from "./topology-render.js";
import { $, api, escapeHtml, toast } from "./utils.js";

// Find the topology client entry that corresponds to a specific agent by port (legacy helper).
export function topologyAgentSubClient(agent) {
  const port = Number(agent.port || 0);
  if (!port) return null;
  return (topology?.clients || []).find((c) => {
    const url = String(c.agentUrl || "");
    return url.endsWith(`:${port}`) || url.includes(`:${port}/`);
  }) || null;
}

// True if the route-agent that sent this client's state supports runtimeDetected probing.
export function clientSupportsRuntimeDetect(client) {
  return (client.agents || []).some((a) => a.runtimeDetected === true);
}

// True if the proxy's agent was manually deleted (tombstoned) — not in client.agents anymore.
export function _cvProxyIsTombstoned(p) {
  const info = _cvProxyToAgent().get(String(p.id));
  if (!info?.agentId || !info?.hostId) return false;
  const client = (topology?.clients || []).find((c) => c.id === info.hostId);
  if (!client || !(client.agents?.length)) return false;
  return !client.agents.some((a) => a.id === info.agentId);
}

// True if the proxy's backing agent has no confirmed runtime (deleted VM/container).
export function _cvProxyIsStale(p) {
  if (_cvProxyIsTombstoned(p)) return true;
  const info = _cvProxyToAgent().get(String(p.id));
  if (!info?.agentId || !info?.hostId) return false;
  const client = (topology?.clients || []).find((c) => c.id === info.hostId);
  if (!client || !clientSupportsRuntimeDetect(client)) return false;
  const agent = (client.agents || []).find((a) => a.id === info.agentId);
  return agent ? agent.runtimeDetected !== true : false;
}

export function topologyAgentCard(client, agent, routeMap, ownsClient = false) {
  const routes = routeMap.get(agent.id) || new Map();
  const primary = routes.get("primary");
  const fallback = routes.get("fallback");
  const usageOf = (role, route) => topologyRouteUsage(client, agent.id, role, route);
  const isOpenclaw = String(agent.kind || "") === "openclaw";
  const isDocker = topologyAgentGroup(agent) === "docker";
  const summaryAttrs = isOpenclaw
    ? ` data-topology-client-detail="${escapeHtml(client.id)}" data-agent-id="${escapeHtml(agent.id)}" role="button" tabindex="0" title="${escapeHtml(t("tpTitleShowOpenclaw"))}"`
    : "";
  const configBtns = isOpenclaw && isDocker ? `
    <div class="agent-config-btns">
      <button class="mini-link" type="button"
        data-agent-config-open="ports"
        data-client-id="${escapeHtml(client.id)}"
        data-agent-id="${escapeHtml(agent.id)}"
        title="${escapeHtml(t("tpTitlePortsReal"))}">${escapeHtml(t("tpPorts"))}</button>
      <button class="mini-link" type="button"
        data-agent-config-open="raw"
        data-client-id="${escapeHtml(client.id)}"
        data-agent-id="${escapeHtml(agent.id)}"
        title="${escapeHtml(t("tpTitleShowRaw"))}">{ }</button>
    </div>` : "";

  // Stale: prefer runtimeDetected field if this client's route-agent supports it.
  // Fall back to sub-client state lookup for agents that have their own client entry.
  const supportsRD = clientSupportsRuntimeDetect(client);
  const rdStale = supportsRD && agent.runtimeDetected !== true;
  const subClient = topologyAgentSubClient(agent);
  const subClientStale = subClient?.state === "stale";
  const agentIsStale = rdStale || subClientStale;

  // Build delete button. Prefer direct agent removal; fall back to sub-client delete.
  let deleteBtn = "";
  if (supportsRD || subClient) {
    const title = agentIsStale ? t("agentRemoveStaleTitle") : t("agentRemoveTitle");
    if (supportsRD) {
      deleteBtn = `<button class="agent-remove-btn${agentIsStale ? " stale" : ""}" type="button"
        title="${title}"
        data-agent-delete-client="${escapeHtml(client.id)}"
        data-agent-delete-id="${escapeHtml(agent.id)}">×</button>`;
    } else {
      deleteBtn = `<button class="agent-remove-btn${agentIsStale ? " stale" : ""}" type="button"
        title="${title}"
        data-agent-client-delete="${escapeHtml(subClient.id)}">×</button>`;
    }
  }

  return `
    <div class="topology-agent ${escapeHtml(topologyAgentGroup(agent))}${agentIsStale ? " agent-stale" : ""}${deleteBtn ? " has-remove" : ""}" data-topology-agent="1" data-host-id="${escapeHtml(client.id)}" data-agent-id="${escapeHtml(agent.id)}">
      ${deleteBtn}
      <div class="topology-agent-summary${isOpenclaw ? " clickable" : ""}"${summaryAttrs}>
        <span class="topology-port-dot"></span>
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
          ${ownsClient ? `<!-- CLIENT management moved here. For a client created
               by hand with a single agent, a separate host card was a second
               card about the same thing: it had nothing left to say, and was
               only kept for these three buttons. With more than one agent,
               the card comes back — there it's the group's header. -->
          <button class="client-rename-btn" type="button" data-t="client-agent-add"
            title="${escapeHtml(t("topologyAgentAdd"))}"
            data-client-agent-add="${escapeHtml(client?.id || "")}">＋</button>
          <button class="client-rename-btn danger" type="button" data-t="client-delete"
            title="${escapeHtml(t("topologyClientDelete"))}"
            data-client-delete="${escapeHtml(client?.id || "")}">✕</button>` : ""}
          <!-- The agent's kind sits on the same line as its name, pushed to
               the right: on its own line it took up a whole row for two
               words and stretched the header out vertically. -->
          ${agentCallerHtml([primary, fallback])}
          <span class="agent-kind">${escapeHtml([agent.kind || "manual", topologyAgentMeta(agent)].filter(Boolean).join(" · "))}</span>
          </div>
          ${agent.endpoint || agent.url ? `<code>${escapeHtml(agent.endpoint || agent.url)}</code>` : ""}
        </div>
        ${configBtns}
      </div>
      <div class="topology-agent-routes">
        ${topologyAgentRouteRow(client, agent, "primary", primary, usageOf("primary", primary))}
        ${topologyAgentRouteRow(client, agent, "fallback", fallback, usageOf("fallback", fallback))}
      </div>
    </div>
  `;
}

// Lane cards for a SINGLE client: itself first, then EVERY one of its agents
// as its own block. Agents lumped into one card read as a single entity,
// even though they're different consumers with different ports and
// different context windows — and the lane is named "clients and their
// proxies".
//
// This is only drawn for a record the board owns. A scout-reported client
// keeps its old card: there, agents are grouped by where they live on the
// machine, and that's the scout's own information, not our layout.
export function clientLaneAgentCards(client, assignments) {
  if (!client?.manual) return [];
  const routeMap = topologyAssignmentsByAgent(assignments);
  const agents = sortedTopologyAgents(client.agents || []);
  // The sole agent of a silent manual client also takes over managing the
  // client itself: there will be no host card next to it.
  const owns = clientCardIsRedundant(client, agents.length) && agents.length === 1;
  return agents.map((agent) => {
    const routes = [...(routeMap.get(agent.id) || new Map()).values()];
    return { agentId: agent.id, name: agent.name || agent.id || "", html: topologyAgentCard(client, agent, routeMap, owns),
             idle: agentIsIdle(routes) };
  });
}

// Whether this host has caravan-scout on it. The host card exists for what
// IT reports: address, CPU, memory, GPUs, liveness, discoveries. With no
// scout there's nothing left to report, and the card degrades into a frame
// around emptiness — sitting next to an agent card, with two cards about the
// same thing leaving it to guess which one deletes what.
//
// The signal isn't "is silent" but "are we talking to it": the agent address
// the controller reaches it at, or even a single answer ever received. A
// client that once answered and went quiet is still one the scout has — and
// its card stays, to show when that was.
export function clientHasScout(client) {
  return !!String(client?.agentUrl || "").trim() || !!Number(client?.lastSeen || 0);
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

// Whether a host card is needed. It exists for what the scout reported —
// so it's needed exactly where a scout exists.
//
// With no scout there's no card, but managing the client has to go
// somewhere: with a single agent, its card takes it over; with zero or
// several, a thin caption row remains — otherwise a "delete client" button
// would repeat on every agent, and the operator would have to guess which
// one is the real one.
export function clientCardIsRedundant(client, agentCount) {
  return !clientHasScout(client);
}

export function clientNeedsCaption(client, agentCount) {
  return clientCardIsRedundant(client, agentCount) && agentCount !== 1;
}

// Kanban clients come from the SOURCE OF TRUTH — the main board — not from the
// list of ports. The kanban used to enumerate routes, so it held rows the main
// board never had (a host with a port number for a name, an app's label) — two
// pictures of one fleet, and the screen could not say which one was true.
//
// A port wired into the graph but owned by nobody on the main board is NOT
// hidden: it comes back separately, so the kanban says it out loud. Silently
// dropping a routed input is exactly absence rendered as normality.
export function canvasBoardClients(proxies) {
  const byPort = new Map();
  for (const p of proxies || []) byPort.set(String(p.port), p);
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
        const port = String(route?.proxyId || "").split(":").pop();
        const proxy = byPort.get(port);
        if (proxy && !claimed.has(String(proxy.id))) { own.push(proxy); claimed.add(String(proxy.id)); }
      }
      if (own.length) rows.push({ key: `${client.id}::${row.agentId}`, clientId: client.id,
                                  agentId: row.agentId, proxies: own,
                                  name: row.name || row.agentId, live: !agentIsIdle(row.routes || []) });
    }
  }
  return { rows: sortedLaneCards(rows), unclaimed: (proxies || []).filter((p) => !claimed.has(String(p.id))) };
}

export function topologyGroupedAgents(client, assignments) {
  const routeMap = topologyAssignmentsByAgent(assignments);
  // The HOST/VMS/DOCKER/OTHER split retells what the scout reported: exactly
  // where on the machine an agent lives. A record the board owns has no such
  // report and never will, and four headers with dashes aren't information,
  // they're noise: three empty frames around a single agent. A manual client
  // shows its agents as a plain list instead.
  if (client?.manual) {
    const agents = sortedTopologyAgents(client.agents || []);
    return `
      <section class="topology-agent-group flat">
        <div class="topology-agent-list">
          ${agents.length
            ? agents.map((agent) => topologyAgentCard(client, agent, routeMap)).join("")
            : `<div class="topology-empty-group">-</div>`}
        </div>
      </section>
    `;
  }
  const groups = new Map();
  (client.agents || []).forEach((agent) => {
    const group = topologyAgentGroup(agent);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push(agent);
  });
  return ["host", "vm", "docker", "other"].map((group) => {
    const agents = sortedTopologyAgents(groups.get(group) || []);
    return `
      <section class="topology-agent-group">
        <h3>${escapeHtml(topologyGroupLabel(group))}</h3>
        <div class="topology-agent-list">
          ${agents.length
            ? agents.map((agent) => topologyAgentCard(client, agent, routeMap)).join("")
            : `<div class="topology-empty-group">-</div>`}
        </div>
      </section>
    `;
  }).join("");
}

export function topologyAssignmentsForHost(hostId) {
  const client = (topology?.clients || []).find((row) => row.id === hostId);
  if (Array.isArray(client?.assignments)) return client.assignments;
  const desired = topology?.assignments?.[hostId]?.assignments;
  return Array.isArray(desired) ? desired : [];
}

// For the board we MERGE per agent+role: the LIVE client report is ground truth for
// which proxy an agent actually uses (it can drift from the stored/desired assignment
// after re-provisioning — e.g. a host agent lives on "<host> primary" live
// but stored still points at the stale "OpenClaw primary" :8117). Live wins per role;
// stored fills roles the agent doesn't currently report (shown muted) for completeness.
export function topologyBoardAssignmentsForHost(hostId) {
  const storedArr = topology?.assignments?.[hostId]?.assignments;
  const stored = Array.isArray(storedArr) ? storedArr : [];
  const client = (topology?.clients || []).find((row) => row.id === hostId);
  const live = Array.isArray(client?.assignments) ? client.assignments : null;
  if (!live) return stored;
  const liveBy = new Map(live.map((a) => [a.agentId, a]));
  const storedBy = new Map(stored.map((a) => [a.agentId, a]));
  const ids = [...new Set([...stored.map((a) => a.agentId), ...live.map((a) => a.agentId)])];
  const routeFor = (a, role) => (a?.routes || []).find((r) => (r.role || "primary") === role);
  const proxyById = new Map((topology?.proxies || []).map((p) => [p.id, p]));
  // A live client report knows its endpoint URL but NOT caravan's internal proxy
  // id, so its routes can arrive with proxyId "". Preferring the live route
  // wholesale then throws the binding away, and the board cable dies silently:
  // no proxy -> no routerId -> the router-input querySelector misses -> the path
  // is dropped by filter(Boolean). The agent still routes fine, so only the
  // drawing breaks. Refill the id from the stored route, else resolve the proxy
  // by the port in the endpoint.
  const proxyByPort = new Map((topology?.proxies || []).map((p) => [String(p.port), p]));
  // LIVENESS comes from the live report, SETTINGS come from the stored
  // record, and never the other way around. A live report carries no
  // settings and never will: an agent knows where it's calling, but not what
  // the operator decided about that route. While a live route was taken
  // wholesale, any setting used to vanish for EVERY agent the scout reports
  // on — and it looked like "not set", which is absence drawn as normal
  // (docs/why.md).
  //
  // The same reasoning covers what used to be a special case: an empty
  // proxyId from the live report doesn't win over the stored one. A client
  // knows its own endpoint but not the caravan's internal id, and preferring
  // the live one wholesale used to drop the binding entirely — the board's
  // cable would quietly stop being drawn.
  const LIVENESS_FIELDS = ["proxyId", "endpoint"];
  const mergeRoute = (liveRoute, storedRoute) => {
    if (!liveRoute) return storedRoute || null;
    if (!storedRoute) return liveRoute;
    const merged = { ...storedRoute, role: liveRoute.role || storedRoute.role };
    for (const key of LIVENESS_FIELDS) {
      if (liveRoute[key]) merged[key] = liveRoute[key];
    }
    // The merge takes liveness from one side and settings from the other —
    // and when the ports have DIVERGED, the result is a row that exists
    // nowhere: the board showed a window next to a port that doesn't publish
    // it (the one named by the record does). The setting isn't lost — it's
    // marked with the wrong port, and a chip says it's not in force here.
    if (storedRoute.proxyId && liveRoute.proxyId && storedRoute.proxyId !== liveRoute.proxyId) {
      merged.settingsProxyId = storedRoute.proxyId;
    }
    return merged;
  };
  // Neither side has an id — recover it from the port in the endpoint.
  const withProxyId = (route) => {
    if (!route || route.proxyId) return route;
    const port = (String(route.endpoint || "").match(/:(\d+)(?:\/|$)/) || [])[1];
    const byPort = port ? proxyByPort.get(port) : null;
    return byPort ? { ...route, proxyId: byPort.id } : route;
  };
  return ids.map((id) => {
    const lv = liveBy.get(id), st = storedBy.get(id);
    const primary = withProxyId(mergeRoute(routeFor(lv, "primary"), routeFor(st, "primary")));
    // Fallback = the PAIR PARTNER of the primary (primary port + 1). Proxies are
    // provisioned as contiguous odd/even pairs, so a client's fallback is always its
    // primary's +1 — not whatever stale port a re-provisioned stored assignment kept.
    let fallback = withProxyId(mergeRoute(routeFor(lv, "fallback"), routeFor(st, "fallback")));
    if (!fallback && primary) {
      const port = Number(String(primary.proxyId || "").split(":").pop());
      const pairId = `skynet:proxy:${port + 1}`;
      const pair = proxyById.get(pairId);
      if (pair && (pair.role === "fallback" || /fallback$/i.test(pair.label || ""))) {
        fallback = { role: "fallback", proxyId: pairId, endpoint: pair.endpoint };
      }
    }
    const routes = [];
    if (primary) routes.push({ ...primary, role: "primary" });
    if (fallback) routes.push({ ...fallback, role: "fallback" });
    return { agentId: id, routes };
  });
}

// Three distinct truths, not two. Caravan ALWAYS knows what it ASSIGNED; whether
// the agent actually uses that route is only knowable when the agent reports its
// own config, and several agents never do (a VM's openclaw config is not readable
// from its host). Collapsing "unverified" into "confirmed" made a silent agent
// look identical to a healthy one — the same defect as a dropped cable: absence
// rendered as normality.
//   confirmed  — the agent reported this role as one it uses
//   unused     — the agent reported, and this role was NOT among them
//   unverified — the agent reports nothing, so usage is simply unknown
export function topologyRouteUsage(client, agentId, role, route) {
  // Order matters, and it is not "evidence always wins". The agent's own report is
  // CURRENT and authoritative about intent; traffic is HISTORICAL. A route the
  // agent has since stopped using still has yesterday's requests in the log, and
  // letting those override the agent's word would relabel a genuinely retired
  // route as healthy. So: a live report is taken at face value, and traffic is
  // what fills the gap when the agent says nothing at all.
  const roles = topologyAgentActiveRoles(client, agentId);
  if (roles) return roles.has(role || "primary") ? "confirmed" : "unused";
  // Silent agent — fall back to evidence. The backend only reports lastRequestAt
  // inside the log retention window, so a long-abandoned route stops vouching
  // for itself instead of being confirmed forever.
  const proxy = route?.proxyId
    ? (topology?.proxies || []).find((p) => p.id === route.proxyId)
    : null;
  return Number(proxy?.lastRequestAt || 0) > 0 ? "confirmed" : "unverified";
}

// Which roles the agent actually USES right now (from the live client report).
// null = unknown (agent offline / not reported) → treat all roles as active.
// Otherwise a role missing from the live set is "muted": its proxy stays provisioned
// and wired but inactive.
export function topologyAgentActiveRoles(client, agentId) {
  const live = Array.isArray(client?.assignments) ? client.assignments : null;
  if (!live) return null;
  const ag = live.find((a) => a.agentId === agentId);
  if (!ag) return null;
  return new Set((ag.routes || []).map((r) => r.role || "primary"));
}

// Proxy ids whose role is NOT in their agent's live config — "inactive" (the proxy
// is kept but unused, shown as INACTIVE on the board). Used to hide inactive ports.
export function topologyMutedProxyIds() {
  const muted = new Set();
  for (const client of (topology?.clients || [])) {
    for (const a of topologyBoardAssignmentsForHost(client.id)) {
      const activeRoles = topologyAgentActiveRoles(client, a.agentId);
      if (!activeRoles) continue;
      for (const r of (a.routes || [])) {
        if (!activeRoles.has(r.role || "primary")) muted.add(r.proxyId);
      }
    }
  }
  return muted;
}

export function sortedTopologyRoutes(routes) {
  const order = { primary: 0, fallback: 1 };
  return routes.slice().sort((left, right) => {
    const a = order[left.role] ?? 20;
    const b = order[right.role] ?? 20;
    return a - b || String(left.role || "").localeCompare(String(right.role || ""));
  });
}

// The proxy runs on the controller, so controller-local servers are reached via
// loopback; remote client servers must be addressed by their
// LAN IP. Kept in sync with the data-llama-host stamped on server handles.
export function topologyServerUpstreamHost(s, node) {
  if (s && s.isController) return "127.0.0.1";
  return (s && s.clientIp) || (node && node.ip) || "127.0.0.1";
}

export async function connectTopologyProxyToLlama(proxyId, llamaPort, llamaHost) {
  const targetHost = (llamaHost || "").trim() || "127.0.0.1";
  // There used to be a SECOND, near-verbatim copy of the route-build logic
  // here, and the drift came from exactly that: a field added to one never
  // showed up in the other. Now it's one list with a targeted replacement of
  // a single route — this file has exactly one rebuild boundary left.
  const routes = topologyProxyRoutes().map((route) => (
    `skynet:proxy:${route.port}` === proxyId
      ? { ...route, upstreamHost: targetHost, upstreamPort: Number(llamaPort),
          upstreamType: "llama", providerId: "" }
      : route));
  const changed = routes.find((route) => `skynet:proxy:${route.port}` === proxyId);
  if (!changed) {
    toast("Proxy route not found");
    return;
  }
  await api("/api/agent-proxies/config", {
    method: "POST",
    body: JSON.stringify({ routes }),
  });
  await refreshTopology();
  toast(`${changed.label || changed.port} -> llama ${targetHost}:${llamaPort}: ok`);
}

export async function connectTopologyProxyToCloud(proxyId, providerId) {
  const proxy = (topology?.proxies || []).find((row) => row.id === proxyId);
  if (!proxy) { toast("Proxy route not found"); return; }
  const provider = (topology?.cloudProviders || []).find((p) => p.id === providerId);
  await api("/api/agent-proxies/route-policy", {
    method: "POST",
    body: JSON.stringify({ port: proxy.port, upstreamType: "cloud", providerId }),
  });
  await refreshTopology();
  toast(`${proxy.label || proxy.port} -> ${provider?.name || providerId}: ok`);
}

export async function toggleTopologyGroupCloudFallback(groupKey) {
  // Per-client toggle: flips cloud fallback for every local (llama) proxy in the group.
  const sorted = (topology?.proxies || []).slice().sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
  const group = groupedTopologyProxies(sorted).find((g) => g.key === groupKey);
  const proxies = group ? group.proxies : [];
  const eligible = proxies.filter((p) => p.cloudFallbackEligible && String(p.upstreamType || "llama") !== "cloud");
  if (!eligible.length) { toast("Connect this client's fallback proxy to a cloud provider first"); return; }
  const active = eligible.some((p) => p.cloudFallbackProviderId);
  const providerId = active ? "" : proxyGroupCloudProviderId(eligible[0]);
  if (!active && !providerId) { toast("Connect this client's fallback proxy to a cloud provider first"); return; }
  for (const proxy of eligible) {
    await api("/api/agent-proxies/route-policy", {
      method: "POST",
      body: JSON.stringify({ port: proxy.port, cloudFallbackProviderId: providerId }),
    });
  }
  await refreshTopology();
  toast(active ? "cloud fallback disabled" : "cloud fallback enabled");
}

// How many records still belong to the scout: clients with no "manual" mark,
// and their assignment rows. The adopt button shows ONLY when this is
// nonzero, and disappears once there's nothing left to adopt — an offer that
// does nothing reads as broken.
//
// The controller's sentinel isn't counted here: it isn't a scout client, and
// adopting its record would pretend the operator decided something about it.
export function scoutOwnedCounts() {
  const assignments = topology?.assignments || {};
  let clients = 0, agents = 0;
  for (const client of (topology?.clients || [])) {
    const id = String(client?.id || "");
    if (!id || id.toLowerCase() === CONTROLLER_HOST_ID.toLowerCase()) continue;
    const rows = (assignments[id]?.assignments) || [];
    const owned = rows.filter((row) => !row?.manual).length;
    agents += owned;
    if (!client?.manual || owned) clients += 1;
  }
  return { clients, agents };
}

export function topologyProxyRoutes() {
  // IMPORTANT: preserve the router binding + ownership fields so that saving
  // the full routes array (add/edit/delete a single proxy) never wipes them.
  return (topology?.proxies || []).map((proxy) => ({
    label: proxy.label || "",
    port: Number(proxy.port),
    upstreamHost: proxy.upstreamHost || "127.0.0.1",
    upstreamPort: Number(proxy.upstreamPort || 8080),
    upstreamType: proxy.upstreamType || "llama",
    providerId: proxy.providerId || "",
    enabled: proxy.enabled !== false,
    mode: proxy.mode || "open",
    priority: Number(proxy.priority || 0),
    preemptible: proxy.preemptible !== false,
    clientTimeoutSeconds: Number(proxy.clientTimeoutSeconds || 0),
    cloudFallbackProviderId: proxy.cloudFallbackProviderId || "",
    apiKey: proxy.apiKey || "",
    // Same preservation rule as connectTopologyProxyToLlama: bridges keep
    // kind="service" and their intentional empty router binding.
    kind: proxy.kind || "",
    routerId: proxy.kind === "service" ? "" : (proxy.routerId || "router:default"),
    role: proxy.role || "",
    clientId: proxy.clientId || "",
    ...(Number(proxy.contextLength) > 0 ? { contextLength: Number(proxy.contextLength) } : {}),
    ...(proxy.contextAuto === undefined || proxy.contextAuto === null
      ? {} : { contextAuto: !!proxy.contextAuto }),
  })).sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
}

export function nextTopologyProxyPort() {
  const ports = topologyProxyRoutes().map((route) => Number(route.port || 0));
  return Math.max(8080, ...ports) + 1;
}

export function renderTopologyProxyForm() {
  if (!ui.topologyProxyFormOpen) return "";
  const editingProxy = (topology?.proxies || []).find((proxy) => proxy.id === ui.topologyProxyEditingId);
  const isNew = !editingProxy;
  const values = editingProxy ? {
    label: editingProxy.label || "",
    port: editingProxy.port || "",
    upstreamHost: editingProxy.upstreamHost || "127.0.0.1",
    upstreamPort: editingProxy.upstreamPort || 8080,
    mode: editingProxy.mode || "open",
    apiKey: editingProxy.apiKey || "",
  } : {
    label: "",
    port: nextTopologyProxyPort(),
    upstreamHost: "127.0.0.1",
    upstreamPort: 8080,
    mode: "open",
    apiKey: "",
  };
  // Show advanced section open if editing and has a non-default mode. Queue/priority is
  // configured on the Router canvas (queue nodes), not here.
  const advancedOpen = !isNew && (values.mode !== "open" || !!values.apiKey);
  return `
    <div class="topology-policy-overlay" data-topology-proxy-overlay>
      <div class="topology-policy-modal proxy-form-modal" role="dialog" aria-modal="true" aria-label="${isNew ? "Add Standalone Proxy" : "Edit Proxy Port"}">
        <div class="topology-card-head">
          <strong>${isNew ? "Add Standalone Proxy" : "Edit Proxy Port"}</strong>
          <button class="icon-action compact" type="button" data-topology-proxy-cancel aria-label="Close" title="Close">×</button>
        </div>
        <div class="topology-proxy-form" data-topology-proxy-form="1">
          <label>Name<input name="label" placeholder="agent-a primary" value="${escapeHtml(String(values.label))}" autofocus></label>
          <div class="proxy-form-row">
            <label>Port<input name="port" type="number" min="1024" max="65535" value="${escapeHtml(String(values.port))}"></label>
          </div>
          <div class="proxy-form-row">
            <label>To host<input name="upstreamHost" value="${escapeHtml(String(values.upstreamHost))}"></label>
            <label>To port<input name="upstreamPort" type="number" min="1" max="65535" value="${escapeHtml(String(values.upstreamPort))}"></label>
          </div>
          <details class="proxy-form-advanced"${advancedOpen ? " open" : ""}>
            <summary>Advanced</summary>
            <label>Mode
              <select name="mode">
                ${["open", "paused", "drain"].map((mode) => `<option value="${mode}"${values.mode === mode ? " selected" : ""}>${mode}</option>`).join("")}
              </select>
            </label>
            <label class="proxy-nokey-row">
              <input type="checkbox" name="noApiKey"${values.apiKey ? "" : " checked"} data-proxy-nokey>
              <span>${escapeHtml(t("proxyNoKeyLabel"))}</span>
            </label>
            <label class="proxy-apikey-label"${values.apiKey ? "" : " hidden"}>${escapeHtml(t("proxyApiKeyLabel"))}
              <span class="proxy-apikey-row">
                <input name="apiKey" placeholder="${escapeHtml(t("proxyApiKeyPlaceholder"))}" value="${escapeHtml(String(values.apiKey))}" autocomplete="off" spellcheck="false">
                <button class="mini-link" type="button" data-proxy-genkey title="${escapeHtml(t("proxyApiKeyGenTip"))}">🎲</button>
              </span>
              <span class="muted proxy-apikey-hint">${escapeHtml(t("proxyApiKeyHint"))}</span>
            </label>
          </details>
          <div class="proxy-route-actions">
            <button class="primary-mini-action" type="button" data-topology-proxy-save>Save</button>
            <button class="mini-link" type="button" data-topology-proxy-cancel>Cancel</button>
            <!-- Deleting a port had no button anywhere: bridges could be removed
                 from the Cloud card and agent routes only by reconcile noticing
                 they were unreferenced, so a port made by hand could be edited
                 forever and never taken away. It belongs beside the settings it
                 was created with — but only when there is something to delete;
                 the same form is also the ADD form, where Delete would offer to
                 remove a port that does not exist yet. -->
            ${editingProxy ? `<button class="mini-link danger" type="button" data-topology-proxy-delete
              title="${escapeHtml(t("proxyDeleteTip"))}">${escapeHtml(t("proxyDelete"))}</button>` : ""}
          </div>
        </div>
      </div>
    </div>
  `;
}

export function readTopologyProxyForm() {
  const form = document.querySelector("[data-topology-proxy-form]");
  if (!form) return null;
  return {
    label: form.querySelector('[name="label"]')?.value.trim() || "",
    port: Number(form.querySelector('[name="port"]')?.value || 0),
    upstreamHost: form.querySelector('[name="upstreamHost"]')?.value.trim() || "127.0.0.1",
    upstreamPort: Number(form.querySelector('[name="upstreamPort"]')?.value || 8080),
    enabled: true,
    mode: form.querySelector('[name="mode"]')?.value || "open",
    // The checkbox is the statement; the text field is only where the key
    // lives when there is one. Reading the field regardless would let a key
    // typed and then waved off with the checkbox stay in force.
    apiKey: form.querySelector('[data-proxy-nokey]')?.checked
      ? "" : (form.querySelector('[name="apiKey"]')?.value.trim() || ""),
  };
}

export async function saveTopologyProxyForm() {
  const route = readTopologyProxyForm();
  if (!route) return;
  const existingRoutes = topologyProxyRoutes().filter((row) => `skynet:proxy:${row.port}` !== ui.topologyProxyEditingId);
  if (existingRoutes.some((row) => Number(row.port) === Number(route.port))) {
    toast("proxy port already exists");
    return;
  }
  const routes = [
    ...existingRoutes,
    route,
  ].sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
  const data = await api("/api/agent-proxies/config", {
    method: "POST",
    body: JSON.stringify({ routes }),
  });
  ui.latestSystemMonitor = data.monitor || ui.latestSystemMonitor;
  ui.topologyProxyFormOpen = false;
  ui.topologyProxyEditingId = "";
  await refreshTopology();
  toast("proxy route saved");
}

export function editTopologyProxy(proxyId) {
  ui.topologyProxyEditingId = proxyId;
  ui.topologyProxyFormOpen = true;
  renderTopology();
}

export async function deleteTopologyProxy(proxyId) {
  const proxy = (topology?.proxies || []).find((row) => row.id === proxyId);
  if (!proxy) return;
  if (!(await appConfirm(t("dlgDeleteProxy", { name: proxy.label || proxy.port }), { confirmLabel: t("deleteAction") }))) return;
  const routes = topologyProxyRoutes().filter((route) => `skynet:proxy:${route.port}` !== proxyId);
  const data = await api("/api/agent-proxies/config", {
    method: "POST",
    body: JSON.stringify({ routes }),
  });
  ui.latestSystemMonitor = data.monitor || ui.latestSystemMonitor;
  await refreshTopology();
  toast("proxy route deleted");
}

export function topologyProxyGroupInfo(proxy) {
  const label = String(proxy.label || "").trim();
  const match = label.match(/^(.*)\s+(primary|fallback)$/i);
  if (!match) {
    return { key: `single:${proxy.id}`, title: label || `proxy ${proxy.port}`, role: "", grouped: false };
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
    // The live client report is ground truth but partial: a scout only echoes
    // the agents it currently supervises, and often with an empty proxyId. The
    // controller's STORED assignments know every agent↔proxy pair — so the
    // queue card showed a bare ":8121" for an agent the store knew perfectly
    // well. Search live first (drift truth), stored fills the gaps.
    const live = topologyAssignmentsForHost(client.id);
    const stored = topology?.assignments?.[client.id]?.assignments;
    const rows = Array.isArray(stored) ? live.concat(stored) : live;
    for (const assignment of rows) {
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
      return (order[a.topologyRole] ?? 10) - (order[b.topologyRole] ?? 10) || Number(a.port || 0) - Number(b.port || 0);
    }),
  }));
}

export function proxyGroupCloudProviderId(proxy) {
  // Find the group this proxy belongs to, then find a cloud sibling within it.
  const sorted = (topology?.proxies || []).slice().sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
  const group = groupedTopologyProxies(sorted).find((g) => g.proxies.some((p) => p.id === proxy.id));
  if (!group) return "";
  const cloud = group.proxies.find((p) => String(p.upstreamType || "llama") === "cloud" && p.providerId);
  return cloud?.providerId || "";
}

