// Router cards, outputs panel, router detail popover.
import { _cvPos, _cvView, canvasNodes, canvasPanels, renderRouterNodeConfig } from "./canvas.js";
import { badge, option } from "./form.js";
import { helpTip, t } from "./i18n.js";
import { OutputCells } from "./output-cells.js";
import { SERVER_ORDER, ServerOrder } from "./server-order.js";
import { setTopology, state, topology, ui } from "./state.js";
import { topologyItemsActivity, topologyRouterActivity, topologyStateHealthClasses } from "./topology-activity.js";
import { bindTopologyDragAndDrop } from "./topology-dnd.js";
import { machineAt } from "./topology-nodes.js";
import { feedsRouters, topologyProxyOwner } from "./topology-proxies.js";
import { refreshTopology, renderTopology } from "./topology-render.js";
import { $, api, escapeHtml, isStaleCopy, pill, toast } from "./utils.js";

export let topologyOutputsFolded = {};            // "host:<host>" -> bool: rows folded on the canvas servers block
export let topologyQuietShown = {};               // machine key -> true: its fold of rows nothing leads to is listed
// Per-OUTPUT activity: is a request actually being served by THIS output right now?
// Matches active proxy items by their resolved upstream (host:port). Used so only the
// cable to the output actually carrying traffic animates (not every output).
// With `router`, only the requests that came in by its ports count: a pool also serves the
// entry's free clients directly (2026-10-11), their requests carry the pool's id as well, and the
// kanban's cable to that pool lit for traffic that never passed the kanban.
export function topologyOutputActivity(out, router = null) {
  const isCloud = String(out.upstreamType || "llama") === "cloud";
  const want = OutputCells.upstream(out);
  // Cloud upstreams collide on host:port, so match by providerId (the chosen block).
  // The models of one engine share its host:port too: matched by the output
  // the request was routed to, or every model of the engine would light up.
  // A machine's models are told apart by their queue's name, which holds the
  // model (OutputCells.upstream, 1.3.506).
  const matches = (it) => isCloud
    ? (String(it.upstreamType || "") === "cloud" && String(it.providerId || "") === String(out.providerId || ""))
    : String(out.upstreamType || "") === "engine"
      ? String(it.routedOutputId || "") === String(out.id || "")
      : (String(it.upstreamType || "llama") !== "cloud" && String(it.upstream || "") === want);
  const inputs = router ? new Set((router.inputs || []).map(String)) : null;
  const ports = inputs ? new Set((topology?.proxies || []).filter((p) => inputs.has(String(p.id))).map((p) => Number(p.port))) : null;
  return topologyItemsActivity((it, port) => (!ports || ports.has(port)) && matches(it));
}

export function topologyRouterOutputLabel(out) {
  if (String(out.upstreamType || "llama") === "cloud") {
    // A pool's output: the pool's name, as the controller labelled it.
    const pool = _poolForOut(out);
    return out.label || `☁ ${pool?.name || out.providerId || "cloud"}`;
  }
  // An engine's model: its name in the engine and the engine, as the
  // controller labelled it — no cell stands on the engine's port.
  if (String(out.upstreamType || "") === "engine") {
    return out.label || `${out.upstreamModel || ""} · ${out.engine || ""}`;
  }
  // A model of a machine's entry: its name — the port is the machine's entry, every model's.
  if (String(out.upstreamType || "") === "machine") return String(out.upstreamModel || out.label || "");
  // A cell: what it runs, as the cell itself is named (output-cells.js), then its port —
  // not the label the server baked from the model file, which read "en" for a moonshine cell.
  const name = new OutputCells(topology).name(out);
  return name ? `${name} :${out.upstreamPort}` : `${out.upstreamHost}:${out.upstreamPort}`;
}

// The pool a cloud output leads to (its output is `cb:<pool id>`), or null.
function _poolForOut(out) {
  return (topology?.pools || []).find((p) => p.id === String(out?.providerId || "")) || null;
}

// What a pool's row on the kanban says about the pool beside its name: how many steps — their
// names in the hint — and a mark when a request to it cannot be served as drawn: no step
// enabled (it is refused with "add one"), or a step whose model its provider no longer lists.
function _poolMarks(pool) {
  const steps = pool?.steps || [];
  const accounts = topology?.cloudAccounts || [];
  const named = steps.map((s, i) => `${i + 1}. ${accounts.find((a) => a.id === s.accountId)?.name || s.accountId} · ${s.model}${s.enabled === false ? ` (${t("poolDisabled")})` : ""}`);
  const live = steps.filter((s) => s.enabled !== false);
  const chip = `<span class="router-out-steps" title="${escapeHtml(named.join("\n"))}">${escapeHtml(t("rtPoolSteps", { n: String(steps.length) }))}</span>`;
  if (!live.length) return `${chip}<span class="router-out-unlisted-warn" title="${escapeHtml(t("rtPoolNoStep"))}">⚠</span>`;
  if (live.some((s) => s.unlisted)) return `${chip}<span class="router-out-unlisted-warn" title="${escapeHtml(t("cloudModelUnlisted"))}">⚠</span>`;
  return chip;
}

// The kanban on the main board (2026-10-12): the pools stand on the kanban, and the main board keeps
// the clients, this card, the machines and the cloud providers. The clients' cables come into the
// card on its left; from its right, cables go to the machines and the providers its pools lead to
// (the owner, 2026-10-12; cables.js, PoolReach). It is small (the owner, 2026-10-13: "small and tidy,
// without listing everything inside"): its name and two numbers — how many clients are cabled to a set,
// how many pools there are. The pools' names stand on the kanban, a click opens it (topology-dnd.js).
// It lights while a client's request runs — a client's or a port of the old kind that feeds it.
export function renderTopologyRouterCard(router) {
  const clients = (topology?.proxies || []).filter((p) => String(p.kind || "") === "consumer");
  const activity = topologyRouterActivity(router);
  const pools = topology?.pools || [];
  return `
    <article class="topology-card router-card ${escapeHtml(topologyStateHealthClasses(activity))}" data-router-id="${escapeHtml(router.id)}" data-topology-router="${escapeHtml(router.id)}" data-t="board-kanban-card" role="button" tabindex="0" title="${escapeHtml(t("rtTitleOpenKanban"))}">
      <span class="topology-handle input router-input" data-topology-router-input="1" data-router-id="${escapeHtml(router.id)}" title="${escapeHtml(t("rtTitleClientsIn"))}"></span>
      <span class="topology-handle output router-output" data-topology-router-output="1" data-router-id="${escapeHtml(router.id)}" aria-hidden="true"></span>
      <div class="topology-card-head">
        <strong>${escapeHtml(t("topologyRouterTitle"))}</strong>${helpTip("topologyKanbanHelp")}
        <span class="router-meta" data-t="board-kanban-counts">${escapeHtml(t("topologyClientsSection"))} ${clients.filter((c) => c.set).length}/${clients.length} · ${escapeHtml(t("topologyLlamaServersSection"))} ${pools.length}</span>
      </div>
    </article>`;
}

// The caravan's two model pages, under the kanban's card (the owner, 2026-10-12: "the way into them is lost";
// 2026-10-14: "move these two buttons somewhere more fitting"): the models in its folder, and Hugging Face to
// download more. They stood on each machine's caravan strip, then in the head of Machines among the board's tools.
// A model belongs to the caravan, not to a machine — the kanban's card is the caravan's own place on the board, and
// these are its other two pages. A machine's own window has them on its caravan strip (topology-nodes.js).
export function renderBoardPageLinks() {
  const link = (id, href, hook, title, sign, word) => `<a id="${id}" class="board-page-link" href="${href}" target="_blank" rel="noopener" data-t="${hook}" title="${escapeHtml(title)}">`
    + `<span aria-hidden="true">${sign}</span> <span>${escapeHtml(word)}</span> <span class="board-page-arrow" aria-hidden="true">↗</span></a>`;
  return `<div class="board-pages" data-t="board-pages">`
    + link("boardModelsLink", "/models", "board-models-open", t("modelsPageSub"), "📦", t("topologyModelsLabel"))
    + link("boardHfLink", "/hf", "board-hf-open", t("hfBrowserTitle"), "🤗", "Hugging Face")
    + `</div>`;
}

// Llama servers available as router output targets.
// Persist a mutation to the router list (no service restart on the backend).
// In-flight save indicator: while a router config write is pending, cables run a
// marching-ants animation and the palette hint flips to "saving…" so it is obvious
// something is happening (the write has no save button — it auto-persists).
export let _routersSaving = 0;
export function _setRoutersSaving(on) {
  _routersSaving = Math.max(0, _routersSaving + (on ? 1 : -1));
  const busy = _routersSaving > 0;
  document.querySelector(".router-workspace")?.classList.toggle("saving", busy);
  const hint = document.querySelector(".rw-palette-save");
  if (hint) hint.textContent = busy ? `⟳ ${t("rtSaving")}` : `⤓ ${t("rtAutoSave")}`;
}
// The routers as they go out: a copy of the page's own, changed by `mutator`, with the version
// of the routers it was copied from. The controller refuses a save made from an older version
// than its own (409, `stale`) and answers the current topology: the change is made again on
// that, once. A tab left open since the morning wrote its copy over the afternoon's with its
// first click — on the NAS it put back a deleted port's cable (2026-10-08). Refused twice, the
// error goes to the caller like any other.
function routersSave(mutator) {
  const routers = JSON.parse(JSON.stringify(topology.routers || []));
  mutator(routers);
  return JSON.stringify({ routers, revision: topology.proxyRevisions?.routers || "" });
}
export async function saveRouters(mutator) {
  let body = routersSave(mutator);
  _setRoutersSaving(true);
  const t0 = performance.now();
  try {
    let data;
    try {
      data = await api("/api/agent-proxies/routers", { method: "POST", body });
    } catch (err) {
      if (!isStaleCopy(err)) throw err;
      setTopology(err.data.topology);
      body = routersSave(mutator);
      data = await api("/api/agent-proxies/routers", { method: "POST", body });
      toast(t("staleCopyRetried"));
    }
    if (data.topology) setTopology(data.topology);
    renderTopology();                 // reflect the change immediately
    if (_routersSaving > 0) document.querySelector(".router-workspace")?.classList.add("saving");
    // Keep the marching-ants visible briefly so fast writes still register visually.
    const elapsed = performance.now() - t0;
    if (elapsed < 350) await new Promise((r) => setTimeout(r, 350 - elapsed));
  } finally {
    _setRoutersSaving(false);
  }
}

export function routerById(routers, id) { return routers.find((s) => s.id === id); }

// ── Outputs (servers) panel — the right rail of the router workspace ──
// The machines' outputs and the pools'. Every routable target carries ONE shared radio
// (rules.default — exactly one default across the whole panel). A pool is one output,
// cb:<pool id>, on the kanban for as long as the pool is.
// A router's local outputs by the machine that serves them: [{ key, name, address, outs }].
// One grouping for the router's panel and the kanban's servers block, which
// each held a copy. The machine is machineAt(the output's address) — two
// addresses of one machine (loopback and its LAN address) are one group; the
// groups go in the order of their lowest port, each group's outputs by port.
export function localOutputGroups(outputs) {
  const byMachine = new Map();
  (outputs || []).filter((o) => String(o.upstreamType || "llama") !== "cloud").forEach((o) => {
    const machine = machineAt(o.upstreamHost || "127.0.0.1");
    if (!byMachine.has(machine.key)) {
      byMachine.set(machine.key, { key: machine.key, name: machine.name, address: machine.address, outs: [] });
    }
    byMachine.get(machine.key).outs.push(o);
  });
  const port = (o) => Number(o.upstreamPort || 0);
  return [...byMachine.values()]
    .map((g) => ({ ...g, outs: [...g.outs].sort((a, b) => port(a) - port(b)) }))
    .sort((a, b) => port(a.outs[0]) - port(b.outs[0]));
}

// A machine group's head: its name, and its address beside it, muted — the
// address once only, when no name was known for it.
export function machineLabelHtml(group) {
  const address = group.address && group.address !== group.name
    ? ` <span class="router-out-host-addr">${escapeHtml(group.address)}</span>` : "";
  return `${escapeHtml(group.name)}${address}`;
}

// ── Servers canvas block: the router's outputs, drawn as a canvas node ──
// Each output row has a [data-cv-out-port] dot (= in-port for cable connections) instead of
// the removed router-out-handle / overlay-SVG approach.
export function renderServersBlockHtml(router, modelQueues = {}) {
  const outputs = router.outputs || [];
  const defaultId = router.rules?.default || "";

  const liveTitle = { active: t("rtLiveActive"), recent: t("rtLiveRecent"), idle: t("cvQIdle") };
  const cells = new OutputCells(topology, router);
  // A serving cell's dot says its traffic. A cell that is not serving has no traffic to say:
  // its dot is a ring, and its state is said in words at the row's end.
  const liveDot = (out, st) => {
    if (st !== "running") return `<span class="router-out-live live-off" aria-hidden="true"></span>`;
    const act = topologyOutputActivity(out, router).state;
    return `<span class="router-out-live live-${act}" title="${liveTitle[act] || ""}"></span>`;
  };
  const stateWord = (st) => OutputCells.WORDS[st]
    ? `<span class="router-out-state state-${st}" data-t="kanban-out-state" data-t-state="${st}">${escapeHtml(t(OutputCells.WORDS[st]))}</span>` : "";
  const twinNote = (note) => {
    if (!note) return "";
    if (note.same) return `<span class="router-out-twin" title="${escapeHtml(t("rtTwinSame", { port: String(note.same) }))}">= :${escapeHtml(String(note.same))}</span>`;
    const shown = note.differ.slice(0, 2).map(([k, v]) => (v === null ? `${k} ≠` : `${k}=${v === "" ? "∅" : v.slice(0, 24)}`));
    const more = note.differ.length > 2 ? ` +${note.differ.length - 2}` : "";
    return `<span class="router-out-twin" title="${escapeHtml(t("rtTwinDiffer", { keys: note.keys.join(", ") }))}">${escapeHtml(shown.join(" · ") + more)}</span>`;
  };
  const outputRow = (out, extraCls, note) => {
    const isDef = out.id === defaultId;
    const isCloud = String(out.upstreamType || "") === "cloud";
    const pool = isCloud ? _poolForOut(out) : null;
    const badge = isDef ? `<span class="router-out-badge">default</span>` : "";
    const st = cells.state(out);
    const marks = isCloud ? "" : cells.marks(out);
    // A cell's port stands apart from its name: a long name gives way to the state word, the
    // port never does — "Qwen3-Coder-30B-A3B-Instruct :220…" named no cell at all.
    const cellRow = String(out.upstreamType || "llama") === "llama";
    const shown = cellRow ? (cells.name(out) || String(out.upstreamHost || "")) : topologyRouterOutputLabel(out);
    return `<label class="router-out-row ${isDef ? "is-default" : ""}${st && st !== "running" ? ` cell-${st}` : ""} ${extraCls || ""}" data-router-out-row="${escapeHtml(out.id)}" data-router-link-out="${escapeHtml(out.id)}"${st ? ` data-cell-state="${st}"` : ""}>
      <input class="router-out-radio" type="radio" name="rw-default" ${isDef ? "checked" : ""} data-router-set-default="${escapeHtml(router.id)}" data-output-id="${escapeHtml(out.id)}" title="${escapeHtml(t("rtTitleSetDefault"))}">
      ${isCloud ? "" : liveDot(out, st)}
      <span class="router-out-name">${marks ? `<span class="router-out-marks">${marks}</span> ` : ""}${escapeHtml(shown)}</span>
      ${cellRow ? `<span class="router-out-port cell-port">:${escapeHtml(String(out.upstreamPort))}</span>` : ""}
      ${twinNote(note)}
      ${pool ? _poolMarks(pool) : ""}
      ${badge}
      ${stateWord(st)}
    </label>`;
  };

  // Local servers — grouped by the machine that serves them.
  const groups = localOutputGroups(outputs);
  const localEntries = groups.map((g) => {
    const foldKey = `host:${g.key}`;
    const folded = !!topologyOutputsFolded[foldKey];
    const hdr = `<div class="router-out-host-head" data-router-group-fold="${escapeHtml(foldKey)}" role="button" tabindex="0" title="${escapeHtml(folded ? t("expand") : t("collapse"))}">
        <span class="router-prov-caret">${folded ? "▸" : "▾"}</span>
        <span class="router-out-host-label">${machineLabelHtml(g)}</span>
        <span class="router-prov-count">${g.outs.length}</span>
      </div>`;
    const notes = cells.twins(g.outs);
    const rows = (outs) => outs.map((o) => outputRow(o, "", notes.get(o.id)) + (modelQueues[o.id] || "")).join("");
    // The stopped cells nothing leads to, under one row of their own — folded until the operator
    // opens it. Their outputs stay named on the row (data-cv-group-outs), so a cable that comes
    // to one before the next render still has an end.
    const { shown, quiet } = cells.split(g.outs);
    const open = !!topologyQuietShown[g.key];
    const quietHtml = quiet.length ? `<div class="router-out-quiet${open ? "" : " folded"}" data-t="kanban-quiet-cells" data-t-id="${escapeHtml(g.key)}" data-cv-group-outs="${escapeHtml(quiet.map((o) => o.id).join(","))}">
        <div class="router-out-quiet-head" data-router-quiet-toggle="${escapeHtml(g.key)}" role="button" tabindex="0" aria-expanded="${open ? "true" : "false"}" title="${escapeHtml(t("rtQuietTip"))}">
          <span class="router-prov-caret">${open ? "▾" : "▸"}</span>
          <span class="router-out-quiet-label">${escapeHtml(t("rtQuietCells", { n: String(quiet.length) }))}</span>
        </div>${open ? rows(quiet) : ""}</div>` : "";
    return { key: ServerOrder.key("node", g.key),
      html: `<div class="router-out-host-group${folded ? " folded" : ""}" data-cv-group-outs="${escapeHtml(g.outs.map((o) => o.id).join(","))}">${hdr}${folded ? "" : rows(shown) + quietHtml}</div>` };
  });

  // Pools: one output each (cb:<pool id>) — every pool is on the kanban for as long as it is
  // (caravan/admin/proxies_config.py, pool_output). A pool's row stands where its card stands
  // under Pools; an output whose pool the page does not know keeps its row too, so no
  // cable loses its end.
  const known = new Set((topology?.pools || []).map((p) => p.id));
  const cloudOuts = outputs.filter((o) => String(o.upstreamType || "") === "cloud");
  const byPool = new Map(cloudOuts.map((o) => [String(o.providerId || ""), o]));
  const cloudEntries = [...(topology?.pools || []).filter((p) => byPool.has(p.id)).map((p) => byPool.get(p.id)),
    ...cloudOuts.filter((o) => !known.has(String(o.providerId || "")))].map((out) => ({
    key: ServerOrder.key("cloud", String(out.providerId || "")),
    html: `<div class="router-prov router-pool" data-cv-group-outs="${escapeHtml(out.id)}">${outputRow(out, "cloud")}</div>`,
  }));

  // Machines and pools in one list, in the board's order (server-order.js): a group stands
  // where its card stands in that order. A kind with no group says so after them.
  const listed = SERVER_ORDER.sorted([...localEntries, ...cloudEntries], (entry) => entry.key).map((entry) => entry.html).join("");
  const none = (entries, key) => entries.length ? "" : `<div class="router-cfg-muted router-prov-empty">${t(key)}</div>`;
  return `
    <div class="router-out-sec">
      ${listed}${none(localEntries, "rtNoLocalServers")}${none(cloudEntries, "rtNoPools")}
    </div>`;
}

// A model of an engine next to the cells becomes a router output, or stops
// being one. The server answers with the board it now is.
export async function setEngineModelExposed(hostId, kind, model, exposed) {
  try {
    const res = await api("/api/engine-outputs/expose", {
      method: "POST", body: JSON.stringify({ hostId, kind, model, exposed: !!exposed }),
    });
    if (res.topology) setTopology(res.topology);
    renderTopology();
  } catch (e) { toast(e.message); }
}

// Re-bind a proxy to another router (drag proxy output → router input).
export async function rebindProxyRouter(proxyId, routerId) {
  const proxy = (topology?.proxies || []).find((p) => p.id === proxyId);
  if (!proxy || !routerId || proxy.routerId === routerId) return;
  const data = await api("/api/agent-proxies/route-policy", {
    method: "POST",
    body: JSON.stringify({ port: proxy.port, routerId }),
  });
  if (data.config) await refreshTopology(); else renderTopology();
  toast("proxy re-bound");
}

// Create a new (empty) router. The user then drags proxy inputs into it.
export function renderTopologyRouterDetail() {
  if (!ui.topologyRouterDetailId) return "";
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyRouterDetailId);
  if (!router) return "";
  const outputs = router.outputs || [];
  const defaultId = router.rules?.default || "";
  const inputs = router.inputs || [];

  const bySource = router.rules?.bySource || [];
  const ruleCount = bySource.length + (router.rules?.schedule?.length || 0);

  // The ports that could feed this kanban and do not, for the head's list. Only those that can
  // feed a router count: a cloud model's own port is an output of the Servers panel, and four of
  // them read as "4 unassigned" clients — a false alarm.
  const allProxies = (topology?.proxies || []).filter(feedsRouters).sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
  const routerIds = new Set((topology?.routers || []).map((s) => s.id));
  const routerNameOf = (id) => (topology?.routers || []).find((s) => s.id === id)?.name || id;
  const onOther = allProxies.filter((p) => p.routerId && p.routerId !== router.id && routerIds.has(p.routerId));
  const free = allProxies.filter((p) => !p.routerId || !routerIds.has(p.routerId));
  const portRole = (p) => (p.role || (String(p.label || "").match(/(primary|fallback)$/i)?.[1]?.toLowerCase()) || "");
  const portName = (p) => p.label || ("proxy " + p.port);
  const pill = (p, kind) => {
    const ri = (portRole(p)[0] || "").toUpperCase();
    const head = `<span class="router-pill-r">${escapeHtml(ri)}</span><span class="router-pill-port">${escapeHtml(p.port)}</span>`;
    // In the unassigned list a port says whose it is: the number alone named nobody.
    const name = `<span class="router-pill-name">${escapeHtml(topologyProxyOwner(p.id)?.title || portName(p))}</span>`;
    if (kind === "other") {
      return `<span class="router-pill other" data-router-attach="${escapeHtml(p.id)}" data-confirm="1" role="button" tabindex="0" title="${escapeHtml(t("rtTitleMoveFrom", { name: routerNameOf(p.routerId) }))}">${head}${name}<span class="router-pill-where">${escapeHtml(routerNameOf(p.routerId))}</span></span>`;
    }
    // A free port answers 503 until a kanban takes it. A client of the entry is never listed:
    // it feeds no router (feedsRouters), its cable leads to a set of models.
    return `<span class="router-pill free" data-router-attach="${escapeHtml(p.id)}" role="button" tabindex="0" title="${escapeHtml(t("rtTitleAttachHere", { name: portName(p) + " :" + p.port }))}">${head}${name}<span class="router-pill-503">503</span></span>`;
  };
  // The ports that could feed this kanban and do not: free ones (no kanban — 503 until bound)
  // and those on another kanban. The badge opens their list, and a click on a port binds it
  // here (topology-dnd.js binds [data-router-attach]; a port on another kanban asks first).
  const unassignedHtml = (onOther.length + free.length) ? `<details class="rw-unassigned" data-t="kanban-unassigned">
      <summary class="rw-unassigned-badge" title="${escapeHtml(t("rtTitleUnassigned", { f: free.length, o: onOther.length }))}">${escapeHtml(t("rtUnassigned", { n: free.length + onOther.length }))}</summary>
      <div class="rw-unassigned-list">${free.map((p) => pill(p, "free")).join("")}${onOther.map((p) => pill(p, "other")).join("")}</div>
    </details>` : "";

  // Center pane = the interactive canvas (was the separate ⤢ modal). Reuses the same
  // node descriptors + cv-* markup; the bind/render cycle (search ui.topologyCanvasRouterId)
  // redraws + rebinds it on every render, and we set ui.topologyCanvasRouterId together with
  // the workspace on open. The CLIENTS and SERVERS panels stand on its two sides, as tall as
  // the workspace — they are not nodes of the canvas, so they do not pan or zoom with it.
  const cvPanels = canvasPanels(router);
  const cvNodeHtml = canvasNodes(router).map((n) => {
    // A drop whose save has not landed yet, else the server's place — there is no third.
    const pos = _cvPos[n.id] || n.fixed || { x: n.dx, y: n.dy };
    return `<div class="cv-node cv-${n.type} ${n.cls || ""}" data-t="kanban-node" data-t-id="${escapeHtml(n.id)}" data-cv-node="${escapeHtml(n.id)}" style="left:${pos.x}px;top:${pos.y}px">${n.html}</div>`;
  }).join("");
  const cvTf = `translate(${_cvView.tx}px, ${_cvView.ty}px) scale(${_cvView.scale})`;
  const foOn = (router.rules?.failover || []).length > 0;
  const enoughOutputs = outputs.length >= 2;
  const scheduleCount = router.rules?.schedule?.length || 0;
  const defaultOut = outputs.length ? (outputs.find((o) => o.id === defaultId) || outputs[0]) : null;

  return `
    <div class="topology-policy-overlay router-workspace-overlay" data-topology-router-overlay>
      <div class="router-workspace">
        ${window.ROUTER_STANDALONE ? `
        <div class="rw-head rw-head-standalone">
          <div class="rw-head-title-group">
            <div class="rw-head-badges">
              <span class="badge rw-stat-badge">in <strong>${inputs.length}</strong></span>
              <span class="badge rw-stat-badge">out <strong>${outputs.length}</strong></span>
              ${ruleCount ? `<span class="badge rw-stat-badge">${escapeHtml(t("rtRules", { n: ruleCount }))}</span>` : ""}
              ${defaultOut ? `<span class="badge rw-default-chip" data-router-link-out="${escapeHtml(defaultOut.id)}" title="${escapeHtml(t("rtTitleDefaultOutput"))}">default → ${escapeHtml(topologyRouterOutputLabel(defaultOut))}</span>` : ""}
              ${unassignedHtml}
            </div>
          </div>
        </div>` : `
        <div class="rw-head">
          <span class="router-cfg-title">
            <strong>${escapeHtml(t("topologyRouterTitle"))}</strong>
            <span class="router-cfg-sub">in ${inputs.length} · out ${outputs.length}${ruleCount ? ` · ${escapeHtml(t("rtRules", { n: ruleCount }))}` : ""}</span>
            ${defaultOut ? `<span class="rw-default-badge" data-router-link-out="${escapeHtml(defaultOut.id)}" title="${escapeHtml(t("rtTitleDefaultOutput"))}">default → <strong>${escapeHtml(topologyRouterOutputLabel(defaultOut))}</strong></span>` : ""}
          </span>
          <span class="topology-policy-head-actions">
            ${unassignedHtml}
            <button class="icon-action compact" type="button" data-topology-router-close aria-label="${escapeHtml(t("close"))}" title="${escapeHtml(t("close"))}">×</button>
          </span>
        </div>`}
        <div class="rw-cols" data-cv-cols>
          ${cvPanels.left}
          <section class="rw-pane rw-center">
            <div class="rw-palette">
              <span class="rw-palette-label">${escapeHtml(t("rtRuleNodeLabel"))} ${helpTip("rtPaletteTip")}</span>
              <button class="cv-palette-btn" data-t="kanban-palette-add" data-t-id="schedule" type="button" data-cv-add="schedule" title="${escapeHtml(t("rtTitleSchedule"))}">⏱ ${escapeHtml(t("cvNodeSchedule"))}</button>
              <button class="cv-palette-btn" data-t="kanban-palette-add" data-t-id="weighted" type="button" data-cv-add="weighted" title="${escapeHtml(t("rtTitleWeighted"))}">⚖ ${escapeHtml(t("cvNodeWeighted"))}</button>
              <button class="cv-palette-btn" data-t="kanban-palette-add" data-t-id="roundRobin" type="button" data-cv-add="roundRobin" title="${escapeHtml(t("rtTitleRoundRobin"))}">🔁 ${escapeHtml(t("cvNodeRoundRobin"))}</button>
              <button class="cv-palette-btn" data-t="kanban-palette-add" data-t-id="failover" type="button" data-cv-add="failover" title="${escapeHtml(t("rtTitleFailover"))}">⚡ ${escapeHtml(t("cvNodeFailover"))}</button>
              <button class="cv-palette-btn" data-t="kanban-palette-add" data-t-id="onError" type="button" data-cv-add="onError" title="${escapeHtml(t("rtTitleOnError"))}">🛟 ${escapeHtml(t("cvNodeOnError"))}</button>
              <button class="cv-palette-btn" data-t="kanban-palette-add" data-t-id="requestType" type="button" data-cv-add="requestType" title="${escapeHtml(t("rtTitleByType"))}">🔀 ${escapeHtml(t("cvNodeByType"))}</button>
              <button class="cv-palette-btn" data-t="kanban-palette-add" data-t-id="requestSize" type="button" data-cv-add="requestSize" title="${escapeHtml(t("rtTitleBySize"))}">📏 ${escapeHtml(t("cvNodeBySize"))}</button>
              <span class="rw-palette-save" data-t="kanban-save-status" title="${escapeHtml(t("rtTitleAutoSaveInstant"))}">⤓ ${escapeHtml(t("rtAutoSave"))}</span>
            </div>
            ${renderRouterNodeConfig(router)}
            <div class="cv-viewport" data-t="kanban-canvas" role="region"
                 aria-label="${escapeHtml(t("a11yRoutingGraph"))}" data-cv-viewport>
              <div class="cv-world" data-cv-world style="transform:${cvTf}">
                <svg class="cv-svg" data-t="kanban-cables" data-cv-svg width="4000" height="3000" viewBox="0 0 4000 3000"></svg>
                ${cvNodeHtml}
                <svg class="cv-svg cv-svg-over" data-cv-over aria-hidden="true" width="4000" height="3000" viewBox="0 0 4000 3000"></svg>
              </div>
              <div class="rw-canvas-hint muted">${escapeHtml(t("rtCanvasHint"))}</div>
              <button class="cv-fit-btn" type="button" data-cv-fit data-t="kanban-fit" title="${escapeHtml(t("cvFitAllTip"))}">⤢ ${escapeHtml(t("cvFitAll"))}</button>
            </div>
          </section>
          ${cvPanels.right}
        </div>
      </div>
    </div>`;
}
