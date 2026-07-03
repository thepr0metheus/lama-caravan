// Agent cards and the proxy-route form/registry.
import { appConfirm } from "./dialogs.js";
import { _cvProxyToAgent } from "./canvas.js";
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
} from "./topology-activity.js";
import { refreshTopology, renderTopology } from "./topology-render.js";
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

export function topologyAgentCard(client, agent, routeMap) {
  const routes = routeMap.get(agent.id) || new Map();
  const primary = routes.get("primary");
  const fallback = routes.get("fallback");
  const activeRoles = topologyAgentActiveRoles(client, agent.id);
  const isActive = (role) => !activeRoles || activeRoles.has(role);
  const isOpenclaw = String(agent.kind || "") === "openclaw";
  const isDocker = topologyAgentGroup(agent) === "docker";
  const summaryAttrs = isOpenclaw
    ? ` data-topology-client-detail="${escapeHtml(client.id)}" data-agent-id="${escapeHtml(agent.id)}" role="button" tabindex="0" title="Show OpenClaw config"`
    : "";
  const configBtns = isOpenclaw && isDocker ? `
    <div class="agent-config-btns">
      <button class="mini-link" type="button"
        data-agent-config-open="ports"
        data-client-id="${escapeHtml(client.id)}"
        data-agent-id="${escapeHtml(agent.id)}"
        title="Real port values from agent config">ports</button>
      <button class="mini-link" type="button"
        data-agent-config-open="raw"
        data-client-id="${escapeHtml(client.id)}"
        data-agent-id="${escapeHtml(agent.id)}"
        title="Show .openclaw/openclaw.json">{ }</button>
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
    const title = agentIsStale ? "Нет связи — удалить агента" : "Удалить агента из списка";
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
          <strong>${escapeHtml(agent.name || agent.id)}</strong>
          <span>${escapeHtml([agent.kind || "manual", topologyAgentMeta(agent)].filter(Boolean).join(" - "))}</span>
          ${agent.endpoint || agent.url ? `<code>${escapeHtml(agent.endpoint || agent.url)}</code>` : ""}
        </div>
        ${configBtns}
      </div>
      <div class="topology-agent-routes">
        ${topologyAgentRouteRow(client, agent, "primary", primary, isActive("primary"))}
        ${topologyAgentRouteRow(client, agent, "fallback", fallback, isActive("fallback"))}
      </div>
    </div>
  `;
}

export function topologyGroupedAgents(client, assignments) {
  const routeMap = topologyAssignmentsByAgent(assignments);
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
  return ids.map((id) => {
    const lv = liveBy.get(id), st = storedBy.get(id);
    const primary = routeFor(lv, "primary") || routeFor(st, "primary");
    // Fallback = the PAIR PARTNER of the primary (primary port + 1). Proxies are
    // provisioned as contiguous odd/even pairs, so a client's fallback is always its
    // primary's +1 — not whatever stale port a re-provisioned stored assignment kept.
    let fallback = routeFor(lv, "fallback");
    if (!fallback && primary) {
      const port = Number(String(primary.proxyId || "").split(":").pop());
      const pairId = `skynet:proxy:${port + 1}`;
      const pair = proxyById.get(pairId);
      if (pair && (pair.role === "fallback" || /fallback$/i.test(pair.label || ""))) {
        fallback = { role: "fallback", proxyId: pairId, endpoint: pair.endpoint };
      }
    }
    if (!fallback) fallback = routeFor(st, "fallback");
    const routes = [];
    if (primary) routes.push({ ...primary, role: "primary" });
    if (fallback) routes.push({ ...fallback, role: "fallback" });
    return { agentId: id, routes };
  });
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
  const routes = (topology?.proxies || []).map((proxy) => ({
    label: proxy.label,
    port: Number(proxy.port),
    upstreamHost: proxy.id === proxyId ? targetHost : (proxy.upstreamHost || "127.0.0.1"),
    upstreamPort: proxy.id === proxyId ? Number(llamaPort) : Number(proxy.upstreamPort || 8080),
    upstreamType: proxy.id === proxyId ? "llama" : (proxy.upstreamType || "llama"),
    providerId: proxy.id === proxyId ? "" : (proxy.providerId || ""),
    enabled: proxy.enabled !== false,
    mode: proxy.mode || "open",
    priority: Number(proxy.priority || 0),
    preemptible: proxy.preemptible !== false,
    // Preserve admin-managed fields the full-rebuild would otherwise drop.
    clientTimeoutSeconds: Number(proxy.clientTimeoutSeconds || 0),
    cloudFallbackProviderId: proxy.cloudFallbackProviderId || "",
  })).sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
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
    routerId: proxy.routerId || "router:default",
    role: proxy.role || "",
    clientId: proxy.clientId || "",
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
  } : {
    label: "",
    port: nextTopologyProxyPort(),
    upstreamHost: "127.0.0.1",
    upstreamPort: 8080,
    mode: "open",
  };
  // Show advanced section open if editing and has a non-default mode. Queue/priority is
  // configured on the Router canvas (queue nodes), not here.
  const advancedOpen = !isNew && values.mode !== "open";
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
          </details>
          <div class="proxy-route-actions">
            <button class="primary-mini-action" type="button" data-topology-proxy-save>Save</button>
            <button class="mini-link" type="button" data-topology-proxy-cancel>Cancel</button>
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

