// Agent proxy route list editor.
import { appConfirm } from "./dialogs.js";
import { t } from "./i18n.js";
import { action, renderSystemMonitor } from "./polling.js";
import { ui } from "./state.js";
import { _routeDisplayUpstream } from "./topology-activity.js";
import { $, api, escapeHtml, toast } from "./utils.js";

export let editingAgentProxyRouteIndex = null;
export function currentAgentProxyRoutes() {
  const routes = ui.latestSystemMonitor?.latest?.agentProxyConfig?.routes || [];
  return Array.isArray(routes) ? routes : [];
}

export function renderAgentProxyRouteForm(route = {}, index = "new") {
  return `
    <div class="proxy-route-form" data-proxy-form="${escapeHtml(String(index))}">
      <label>${escapeHtml(t("proxyClientName"))}<input name="label" value="${escapeHtml(route.label || "")}" placeholder="agent-a"></label>
      <label>${escapeHtml(t("proxyListenPort"))}<input name="port" type="number" min="1024" max="65535" value="${escapeHtml(String(route.port || ""))}" placeholder="8083"></label>
      <div class="proxy-route-actions">
        <button class="primary-mini-action" type="button" data-proxy-save="${escapeHtml(String(index))}">${escapeHtml(t("save"))}</button>
        <button class="mini-link" type="button" data-proxy-cancel>${escapeHtml(t("cancel"))}</button>
      </div>
    </div>
  `;
}

export function renderAgentProxyRoutes(data) {
  const routes = data?.latest?.agentProxyConfig?.routes || [];
  const rows = routes.map((route, index) => {
    if (editingAgentProxyRouteIndex === index) return renderAgentProxyRouteForm(route, index);
    const status = route.enabled ? "on" : "off";
    const action = route.enabled ? "disable" : "enable";
    return `
      <div class="system-user-row proxy-route ${route.enabled ? "active" : ""}">
        <strong>${escapeHtml(route.label || `port-${route.port}`)}</strong>
        <code>${escapeHtml(`:${route.port} -> ${_routeDisplayUpstream(route)}`)}</code>
        <span>${escapeHtml(t(status))}</span>
        <small>
          <button class="mini-link" type="button" data-proxy-edit="${index}">${escapeHtml(t("edit"))}</button>
          <button class="mini-link" type="button" data-proxy-toggle="${index}">${escapeHtml(t(action))}</button>
          <button class="mini-link danger-link" type="button" data-proxy-delete="${index}">${escapeHtml(t("deleteAction"))}</button>
        </small>
      </div>
    `;
  }).join("");
  const addForm = editingAgentProxyRouteIndex === "new"
    ? renderAgentProxyRouteForm({ enabled: true }, "new")
    : "";
  return `${addForm}${rows || (addForm ? "" : `<div class="system-process-empty">${escapeHtml(t("agentProxyRoutesEmpty"))}</div>`)}`;
}

export function bindAgentProxyRouteControls() {
  const panel = $("systemAgentProxyRoutes");
  if (!panel) return;
  panel.querySelectorAll("[data-proxy-edit]").forEach((button) => {
    button.addEventListener("click", () => editAgentProxyRoute(Number(button.dataset.proxyEdit)));
  });
  panel.querySelectorAll("[data-proxy-save]").forEach((button) => {
    const value = button.dataset.proxySave;
    button.addEventListener("click", () => saveAgentProxyRoute(value === "new" ? "new" : Number(value)));
  });
  panel.querySelectorAll("[data-proxy-cancel]").forEach((button) => {
    button.addEventListener("click", cancelAgentProxyEdit);
  });
  panel.querySelectorAll("[data-proxy-toggle]").forEach((button) => {
    button.addEventListener("click", () => toggleAgentProxyRoute(Number(button.dataset.proxyToggle)));
  });
  panel.querySelectorAll("[data-proxy-delete]").forEach((button) => {
    button.addEventListener("click", () => deleteAgentProxyRoute(Number(button.dataset.proxyDelete)));
  });
}

export function drawAgentProxyRoutes() {
  const panel = $("systemAgentProxyRoutes");
  if (!panel || !ui.latestSystemMonitor) return;
  panel.innerHTML = renderAgentProxyRoutes(ui.latestSystemMonitor);
  bindAgentProxyRouteControls();
}

export async function saveAgentProxyRoutes(routes) {
  const data = await api("/api/agent-proxies/config", {
    method: "POST",
    body: JSON.stringify({ routes }),
  });
  renderSystemMonitor(data.monitor);
  toast(t("saved"));
}

export function readProxyRouteForm(index) {
  const form = document.querySelector(`[data-proxy-form="${String(index)}"]`);
  if (!form) return null;
  return {
    label: form.querySelector('[name="label"]')?.value.trim() || "",
    port: Number(form.querySelector('[name="port"]')?.value || 0),
    upstreamHost: form.querySelector('[name="upstreamHost"]')?.value.trim() || "127.0.0.1",
    upstreamPort: Number(form.querySelector('[name="upstreamPort"]')?.value || 8080),
  };
}

export function redrawAgentProxyRoutes() {
  drawAgentProxyRoutes();
}

export function addAgentProxyRoute() {
  editingAgentProxyRouteIndex = "new";
  redrawAgentProxyRoutes();
}

export async function saveAgentProxyRoute(index) {
  const routes = currentAgentProxyRoutes().slice();
  const formRoute = readProxyRouteForm(index);
  if (!formRoute) return;
  const route = {
    ...formRoute,
    enabled: index === "new" ? true : routes[index]?.enabled !== false,
  };
  if (index === "new") routes.push(route);
  else routes[index] = route;
  try {
    editingAgentProxyRouteIndex = null;
    await saveAgentProxyRoutes(routes);
  } catch (err) {
    toast(err.message);
    editingAgentProxyRouteIndex = index;
    redrawAgentProxyRoutes();
  }
}

export function editAgentProxyRoute(index) {
  editingAgentProxyRouteIndex = index;
  redrawAgentProxyRoutes();
}

export function cancelAgentProxyEdit() {
  editingAgentProxyRouteIndex = null;
  redrawAgentProxyRoutes();
}

export async function toggleAgentProxyRoute(index) {
  const routes = currentAgentProxyRoutes().slice();
  if (!routes[index]) return;
  routes[index] = { ...routes[index], enabled: !routes[index].enabled };
  try {
    await saveAgentProxyRoutes(routes);
  } catch (err) {
    toast(err.message);
  }
}

export async function deleteAgentProxyRoute(index) {
  const routes = currentAgentProxyRoutes().slice();
  if (!routes[index]) return;
  if (!(await appConfirm(t("dlgDeleteProxy", { name: routes[index].label || routes[index].port }), { confirmLabel: t("deleteAction") }))) return;
  routes.splice(index, 1);
  try {
    await saveAgentProxyRoutes(routes);
  } catch (err) {
    toast(err.message);
  }
}

