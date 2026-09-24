// Agent cards and the proxy-route form/registry.
import { appConfirm } from "./dialogs.js";
import { _cvProxyToAgent } from "./canvas.js";
import { option } from "./form.js";
import { t } from "./i18n.js";
import { action } from "./polling.js";
import { state, topology, ui } from "./state.js";
import { CARD_FOLD, CardFold } from "./card-fold.js";
import { AgentRow, FoldSlot } from "./card-rows.js";
import {
  routeAddress,
  routeErrBadgeHtml,
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
import { refreshTopology, renderTopology,
} from "./topology-render.js";
import { $, api, escapeHtml, toast } from "./utils.js";

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

  const foldKey = `agent:${client.id}:${agent.id}`;
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
    const proxy = (topology?.proxies || []).find((p) => p.id === route.proxyId);
    const port = proxy?.port || String(route.proxyId || "").split(":").pop() || "";
    const usage = topologyRouteUsage(route);
    const model = String(route.modelName || "").trim();
    return {
      role, port, address: routeAddress(route, port), face: routeStateFace(usage),
      model, locked: !!model && !route.modelNameAuto, waitSec: routeWaitSec(route).sec,
      limit: Number(route.contextLength || 0) > 0 ? Number(route.contextLength) : 0,
      errBadge: routeErrBadgeHtml(port), anchor: routeHandleHtml(client, agent, role, route, usage),
    };
  };
  const line = new AgentRow({
    key: foldKey, name: agent.name || agent.id, kind,
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

