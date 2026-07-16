// Router cards, outputs panel, router detail popover.
import { _cvPos, _cvView, canvasNodes, renderRouterNodeConfig } from "./canvas.js";
import { badge, option } from "./form.js";
import { helpTip, t } from "./i18n.js";
import {
  aaBadgeHtml,
  formatPricePer1M,
  modelPricing,
  parseModelName,
  requestAaScores,
} from "./model-meta.js";
import { action } from "./polling.js";
import { setTopology, state, topology, ui } from "./state.js";
import { topologyProxyActivity, topologyStateHealthClasses } from "./topology-activity.js";
import { bindTopologyDragAndDrop } from "./topology-dnd.js";
import { topologyProxyOwner } from "./topology-proxies.js";
import { refreshTopology, renderTopology } from "./topology-render.js";
import { $, api, escapeHtml, pill, toast } from "./utils.js";

export let topologyOutputsCloudExpanded = {};     // accountId -> bool: cloud provider's model checklist open?
export let topologyOutputsFolded = {};            // "host:<host>" / "prov:<accountId>" -> bool: rows folded on the canvas servers block
// Per-OUTPUT activity: is a request actually being served by THIS output right now?
// Matches active proxy items by their resolved upstream (host:port). Used so only the
// cable to the output actually carrying traffic animates (not every output).
export function topologyOutputActivity(out) {
  const isCloud = String(out.upstreamType || "llama") === "cloud";
  const want = `${out.upstreamHost || ""}:${out.upstreamPort || ""}`;
  // Cloud upstreams collide on host:port, so match by providerId (the chosen block).
  const matches = (it) => isCloud
    ? (String(it.upstreamType || "") === "cloud" && String(it.providerId || "") === String(out.providerId || ""))
    : (String(it.upstreamType || "llama") !== "cloud" && String(it.upstream || "") === want);
  const agents = ui.latestSystemMonitor?.latest?.agentProxies?.agents || {};
  let active = false, recent = false;
  for (const row of Object.values(agents)) {
    for (const it of (row.active || [])) {
      if (matches(it) && it.phase !== "queued") active = true;
    }
    for (const it of (row.recent || [])) {
      if (matches(it) && Number(it.finishedAt || 0) * 1000 > Date.now() - 8000) recent = true;
    }
  }
  if (active) return { state: "active", title: "" };
  if (recent) return { state: "recent", title: "" };
  return { state: "idle", title: "" };
}

// Aggregate activity of a router = the liveliest of the proxies feeding it.
export function topologyRouterActivity(router) {
  const ids = new Set((router?.inputs || []).map(String));
  const acts = (topology?.proxies || []).filter((p) => ids.has(String(p.id))).map(topologyProxyActivity);
  return acts.find((a) => a.state === "active")
    || acts.find((a) => a.state === "error")
    || acts.find((a) => a.state === "recent")
    || { state: "idle", title: "" };
}

export function topologyRouterOutputLabel(out) {
  if (String(out.upstreamType || "llama") === "cloud") {
    // Per-account cloud output; the model (block) is shown via its own dropdown.
    const acc = (topology?.cloudAccounts || []).find((a) => a.id === out.accountId);
    return out.label || `☁ ${acc?.name || out.accountId || "cloud"}`;
  }
  // Local server: use the SAME short/pretty model name as the server card
  // (parseModelName), not the raw .gguf filename baked into out.label.
  const srv = (topology?.server?.llamaServers || []).find((s) => Number(s.port) === Number(out.upstreamPort));
  const pretty = srv ? parseModelName(srv.model)?.label : "";
  if (pretty) return `${pretty} :${out.upstreamPort}`;
  return out.label || `${out.upstreamHost}:${out.upstreamPort}`;
}

// Price tag for a cloud output row: resolve the model via its provider block
// and look it up in the pricing map (LiteLLM + manual overrides). ":free"
// OpenRouter models get a FREE chip instead of $0/$0.
function _outPriceTag(out) {
  const block = _blockForOut(out);
  const model = block?.model || "";
  if (!model) return "";
  if (model.endsWith(":free")) return `<span class="router-out-price free">FREE</span>`;
  const mp = modelPricing[model];
  if (!mp || (!mp.inputPer1M && !mp.outputPer1M)) return "";
  return `<span class="router-out-price">${formatPricePer1M(mp.inputPer1M)}/${formatPricePer1M(mp.outputPer1M)}</span>`;
}

function _blockForOut(out) {
  return (topology?.cloudProviders || []).find((b) => b.id === String(out?.providerId || "")) || null;
}

// ⚠ mark for a block whose model the provider no longer lists (server-annotated).
function _unlistedTag(block) {
  return block?.unlisted
    ? `<span class="router-out-unlisted-warn" title="${escapeHtml(t("cloudModelUnlisted"))}">⚠</span>`
    : "";
}

// Cloud model lists sort expensive→cheap (price = the interesting attribute);
// unknown-price models sink to the bottom, name breaks ties.
function _priceRank(model) {
  const mp = modelPricing[model || ""];
  return mp ? [Number(mp.inputPer1M) || 0, Number(mp.outputPer1M) || 0] : [-1, -1];
}

function _byPriceDesc(modelOf) {
  return (a, b) => {
    const ra = _priceRank(modelOf(a));
    const rb = _priceRank(modelOf(b));
    return (rb[0] - ra[0]) || (rb[1] - ra[1])
      || String(modelOf(a) || "").localeCompare(String(modelOf(b) || ""));
  };
}

export function renderTopologyRouterCard(router) {
  const activity = topologyRouterActivity(router);
  const outputs = router.outputs || [];
  const inCount = (router.inputs || []).length;
  const ruleCount = (router.rules?.schedule?.length || 0) + (router.rules?.bySource?.length || 0);
  // Compact board card: the full per-output list lives in the kanban workspace;
  // here just the default route + a local/cloud tally, one shared cable anchor.
  const defaultOut = outputs.find((o) => o.id === (router.rules?.default || ""));
  const localCount = outputs.filter((o) => String(o.upstreamType || "llama") !== "cloud").length;
  const cloudCount = outputs.length - localCount;
  return `
    <article class="topology-card router-card ${escapeHtml(topologyStateHealthClasses(activity))}" data-router-id="${escapeHtml(router.id)}" data-topology-router="${escapeHtml(router.id)}" role="button" tabindex="0" title="${escapeHtml(t("rtTitleConfigure"))}">
      <span class="topology-handle input router-input" data-topology-router-input="1" data-router-id="${escapeHtml(router.id)}" title="${escapeHtml(t("rtTitleProxiesIn"))}"></span>
      <div class="topology-card-head">
        <strong>${escapeHtml(t("topologyRouterTitle"))}</strong>${helpTip("topologyProxyPortsHelp")}
        <span class="router-meta">in ${inCount} · out ${outputs.length}${ruleCount ? ` · ${escapeHtml(t("rtRules", { n: ruleCount }))}` : ""}</span>
      </div>
      <div class="router-outputs">
        ${outputs.length ? `
          ${defaultOut ? `
          <div class="router-output-row is-default">
            <span class="router-output-label">${escapeHtml(topologyRouterOutputLabel(defaultOut))}</span>
            <span class="router-default-chip" title="${escapeHtml(t("rtTitleDefaultOutput"))}">default</span>
          </div>` : ""}
          <div class="router-output-row">
            <span class="router-output-label muted">${escapeHtml(t("rtOutputsSummary", { l: localCount, c: cloudCount }))}</span>
          </div>` : `<div class="router-output-row empty"><span class="router-output-label muted">${t("rtNoOutputs")}</span></div>`}
      </div>
      <span class="topology-handle output router-output" data-topology-router-output="1" data-router-id="${escapeHtml(router.id)}" title="${escapeHtml(t("rtTitleOutputServer"))}"></span>
    </article>`;
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
export async function saveRouters(mutator) {
  const routers = JSON.parse(JSON.stringify(topology.routers || []));
  mutator(routers);
  _setRoutersSaving(true);
  const t0 = performance.now();
  try {
    const data = await api("/api/agent-proxies/routers", {
      method: "POST",
      body: JSON.stringify({ routers: routers }),
    });
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
// Two sections: LOCAL llama servers + CLOUD providers. Every routable target carries
// ONE shared radio (rules.default — exactly one default across the whole panel). A
// cloud provider is a collapsible header: click it to reveal a checklist of ALL its
// models; ticked models (block.exposed) become routable cloud outputs (cb:<blockId>)
// and show as radio rows beneath the provider.
export function renderRouterOutputsPanel(router) {
  const outputs = router.outputs || [];
  const defaultId = router.rules?.default || "";
  const liveTitle = { active: t("rtLiveActive"), recent: t("rtLiveRecent"), idle: t("cvQIdle") };
  const accounts = topology?.cloudAccounts || [];
  const blocks = topology?.cloudProviders || [];

  const liveDot = (out) => {
    const st = topologyOutputActivity(out).state;
    return `<span class="router-out-live live-${st}" title="${liveTitle[st] || ""}" aria-label="${liveTitle[st] || ""}"></span>`;
  };
  // One routable target row: connector handle + radio + live dot (local only) + name + default badge.
  const outputRow = (out, extraCls) => {
    const isDef = out.id === defaultId;
    const isCloud = String(out.upstreamType || "") === "cloud";
    const blk = isCloud ? _blockForOut(out) : null;
    const priceHtml = isCloud ? _outPriceTag(out) : "";
    const badge = isDef ? `<span class="router-out-badge">★ default</span>` : "";
    return `<label class="router-out-row ${isDef ? "is-default" : ""}${blk?.unlisted ? " unlisted" : ""} ${extraCls || ""}" data-router-out-row="${escapeHtml(out.id)}" data-router-link-out="${escapeHtml(out.id)}">
      <span class="router-out-handle" data-cv-node="out:${escapeHtml(out.id)}" data-cv-panel-out="out:${escapeHtml(out.id)}" title="${escapeHtml(t("rtTitleDragCable"))}"></span>
      <input class="router-out-radio" type="radio" name="rw-default" ${isDef ? "checked" : ""} data-router-set-default="${escapeHtml(router.id)}" data-output-id="${escapeHtml(out.id)}" title="${escapeHtml(t("rtTitleSetDefault"))}">
      ${isCloud ? "" : liveDot(out)}
      <span class="router-out-name">${escapeHtml(topologyRouterOutputLabel(out))}</span>
      ${_unlistedTag(blk)}
      ${badge}
      ${priceHtml}
    </label>`;
  };

  // LOCAL llama servers — grouped by upstream host.
  const localOuts = outputs.filter((o) => String(o.upstreamType || "llama") !== "cloud");
  const adminIp = topology?.server?.ip || null;
  const adminName = topology?.server?.name || "local";
  const hostMap = new Map();
  localOuts.forEach((o) => {
    const h = o.upstreamHost || "127.0.0.1";
    if (!hostMap.has(h)) hostMap.set(h, []);
    hostMap.get(h).push(o);
  });
  const localHtml = hostMap.size
    ? [...hostMap.entries()]
        .sort(([, a], [, b]) => Math.min(...a.map((o) => Number(o.upstreamPort || 0))) - Math.min(...b.map((o) => Number(o.upstreamPort || 0))))
        .map(([host, outs]) => {
          const isAdmin = !host || host === "127.0.0.1" || host === "localhost" || (adminIp && host === adminIp);
          const label = isAdmin ? adminName : host;
          const hdr = hostMap.size > 1 ? `<div class="router-out-host-label">${escapeHtml(label)}</div>` : "";
          const sorted = [...outs].sort((a, b) => Number(a.upstreamPort || 0) - Number(b.upstreamPort || 0));
          return `<div class="router-out-host-group">${hdr}${sorted.map((o) => outputRow(o)).join("")}</div>`;
        }).join("")
    : `<div class="router-cfg-muted">${t("rtNoLocalServers")}</div>`;

  // CLOUD: group exposed outputs by account; the header expands a checklist of all blocks.
  const cloudOutsByAcc = new Map();
  outputs.filter((o) => String(o.upstreamType || "") === "cloud").forEach((o) => {
    if (!cloudOutsByAcc.has(o.accountId)) cloudOutsByAcc.set(o.accountId, []);
    cloudOutsByAcc.get(o.accountId).push(o);
  });
  const cloudHtml = accounts.map((acc) => {
    const accBlocks = blocks.filter((b) => b.accountId === acc.id);
    const exposedOuts = cloudOutsByAcc.get(acc.id) || [];
    const exposedCount = accBlocks.filter((b) => b.exposed).length;
    // Auto-open a provider with nothing chosen yet (so the checklist is discoverable).
    const expanded = (acc.id in topologyOutputsCloudExpanded) ? topologyOutputsCloudExpanded[acc.id] : exposedCount === 0;
    const header = `<button class="router-prov-head" type="button" data-router-prov-toggle="${escapeHtml(acc.id)}" title="${escapeHtml(t("rtTitleProvToggle"))}">
      <span class="router-prov-caret">${expanded ? "▾" : "▸"}</span>
      <span class="router-prov-name">☁ ${escapeHtml(acc.name || acc.id)}</span>
      <span class="router-out-unlimited" title="${escapeHtml(t("rtTitleCloudUnlimited"))}">∞</span>
      <span class="router-prov-count" title="${escapeHtml(t("rtTitleExposedTotal"))}">${exposedCount}/${accBlocks.length}</span>
    </button>`;
    const checklist = expanded
      ? (accBlocks.length
          ? `<div class="router-prov-models">` + accBlocks.slice().sort((a, b) => (b.exposed ? 1 : 0) - (a.exposed ? 1 : 0) || _byPriceDesc((x) => x.model)(a, b)).map((b) => {
              const mp = modelPricing[b.model || ""] || null;
              const priceHtml = mp
                ? `<span class="router-prov-model-price">${formatPricePer1M(mp.inputPer1M)} in / ${formatPricePer1M(mp.outputPer1M)} out /1M</span>`
                : "";
              return `<label class="router-prov-model${b.unlisted ? " unlisted" : ""}" title="${escapeHtml(b.unlisted ? t("cloudModelUnlisted") : (b.model || b.name || b.id))}">
                <input type="checkbox" data-router-expose="${escapeHtml(b.id)}" ${b.exposed ? "checked" : ""}>
                <div class="router-prov-model-info">
                  <span class="router-prov-model-name">${escapeHtml(b.model || b.name || b.id)}</span>
                  ${priceHtml}
                </div>
                ${_unlistedTag(b)}
                ${aaBadgeHtml(b.model)}
              </label>`;
            }).join("")
            + `</div>`
          : `<div class="router-cfg-muted router-prov-empty">${escapeHtml(t("rtNoModelsYet"))}</div>`)
      : "";
    const rows = exposedOuts.slice().sort(_byPriceDesc((o) => _blockForOut(o)?.model)).map((o) => outputRow(o, "cloud")).join("");
    return `<div class="router-prov ${expanded ? "open" : ""}">${header}${checklist}${rows}</div>`;
  }).join("") || `<div class="router-cfg-muted">${t("rtNoCloudProviders")}</div>`;

  return `
    <div class="router-out-sec">
      <div class="router-out-sec-h">${escapeHtml(t("rtLocalServers"))}</div>
      ${localHtml}
    </div>
    <div class="router-out-sec">
      <div class="router-out-sec-h">${escapeHtml(t("rtCloud"))}</div>
      ${cloudHtml}
    </div>`;
}

// ── Servers canvas block: same content as the old right panel, now lives as a canvas node ──
// Each output row has a [data-cv-out-port] dot (= in-port for cable connections) instead of
// the removed router-out-handle / overlay-SVG approach.
export function renderServersBlockHtml(router) {
  const outputs = router.outputs || [];
  const defaultId = router.rules?.default || "";
  const accounts = topology?.cloudAccounts || [];
  const blocks = topology?.cloudProviders || [];
  const _aaWant = [];  // model ids whose AA Intelligence Index to lazily fetch (exposed first)

  const liveTitle = { active: t("rtLiveActive"), recent: t("rtLiveRecent"), idle: t("cvQIdle") };
  const liveDot = (out) => {
    const st = topologyOutputActivity(out).state;
    return `<span class="router-out-live live-${st}" title="${liveTitle[st] || ""}"></span>`;
  };
  const outputRow = (out, extraCls) => {
    const isDef = out.id === defaultId;
    const isCloud = String(out.upstreamType || "") === "cloud";
    const blk = isCloud ? _blockForOut(out) : null;
    const priceHtml = isCloud ? _outPriceTag(out) : "";
    const badge = isDef ? `<span class="router-out-badge">default</span>` : "";
    return `<label class="router-out-row ${isDef ? "is-default" : ""}${blk?.unlisted ? " unlisted" : ""} ${extraCls || ""}" data-router-out-row="${escapeHtml(out.id)}" data-router-link-out="${escapeHtml(out.id)}">
      <input class="router-out-radio" type="radio" name="rw-default" ${isDef ? "checked" : ""} data-router-set-default="${escapeHtml(router.id)}" data-output-id="${escapeHtml(out.id)}" title="${escapeHtml(t("rtTitleSetDefault"))}">
      ${isCloud ? "" : liveDot(out)}
      <span class="router-out-name">${escapeHtml(topologyRouterOutputLabel(out))}</span>
      ${_unlistedTag(blk)}
      ${badge}
      ${priceHtml}
    </label>`;
  };

  // Local servers — group by host.
  const localOuts = outputs.filter((o) => String(o.upstreamType || "llama") !== "cloud");
  const adminIp = topology?.server?.ip || null;
  const adminName = topology?.server?.name || "local";
  const hostMap = new Map();
  localOuts.forEach((o) => {
    const h = o.upstreamHost || "127.0.0.1";
    if (!hostMap.has(h)) hostMap.set(h, []);
    hostMap.get(h).push(o);
  });
  const localHtml = hostMap.size
    ? [...hostMap.entries()]
        .sort(([, a], [, b]) => Math.min(...a.map((o) => Number(o.upstreamPort || 0))) - Math.min(...b.map((o) => Number(o.upstreamPort || 0))))
        .map(([host, outs]) => {
          const isAdmin = !host || host === "127.0.0.1" || host === "localhost" || (adminIp && host === adminIp);
          const label = isAdmin ? adminName : host;
          const foldKey = `host:${host}`;
          const folded = !!topologyOutputsFolded[foldKey];
          const hdr = `<div class="router-out-host-head" data-router-group-fold="${escapeHtml(foldKey)}" role="button" tabindex="0" title="${escapeHtml(folded ? t("expand") : t("collapse"))}">
            <span class="router-prov-caret">${folded ? "▸" : "▾"}</span>
            <span class="router-out-host-label">${escapeHtml(label)}</span>
            <span class="router-prov-count">${outs.length}</span>
          </div>`;
          const sorted = [...outs].sort((a, b) => Number(a.upstreamPort || 0) - Number(b.upstreamPort || 0));
          return `<div class="router-out-host-group${folded ? " folded" : ""}" data-cv-group-outs="${escapeHtml(outs.map((o) => o.id).join(","))}">${hdr}${folded ? "" : sorted.map((o) => outputRow(o)).join("")}</div>`;
        }).join("")
    : `<div class="router-cfg-muted router-prov-empty">${t("rtNoLocalServers")}</div>`;

  // Cloud providers — collapsible with model checklist.
  const cloudOutsByAcc = new Map();
  outputs.filter((o) => String(o.upstreamType || "") === "cloud").forEach((o) => {
    if (!cloudOutsByAcc.has(o.accountId)) cloudOutsByAcc.set(o.accountId, []);
    cloudOutsByAcc.get(o.accountId).push(o);
  });
  const cloudHtml = accounts.map((acc) => {
    const accBlocks = blocks.filter((b) => b.accountId === acc.id);
    const exposedOuts = cloudOutsByAcc.get(acc.id) || [];
    const exposedCount = accBlocks.filter((b) => b.exposed).length;
    const expanded = (acc.id in topologyOutputsCloudExpanded) ? topologyOutputsCloudExpanded[acc.id] : exposedCount === 0;
    const foldKey = `prov:${acc.id}`;
    const folded = !!topologyOutputsFolded[foldKey];
    const header = `<div class="router-prov-headrow">
      <button class="router-prov-head" type="button" data-router-prov-toggle="${escapeHtml(acc.id)}">
        <span class="router-prov-caret">${expanded ? "▾" : "▸"}</span>
        <span class="router-prov-name">☁ ${escapeHtml(acc.name || acc.id)}</span>
        <span class="router-out-unlimited" title="${escapeHtml(t("rtTitleCloudUnlimited"))}">∞</span>
        <span class="router-prov-count">${exposedCount}/${accBlocks.length}</span>
      </button>
      <button class="router-group-fold" type="button" data-router-group-fold="${escapeHtml(foldKey)}" title="${escapeHtml(folded ? t("expand") : t("collapse"))}">${folded ? "▸" : "▾"}</button>
    </div>`;
    const sortedBlocks = accBlocks.slice().sort((a, b) => (b.exposed ? 1 : 0) - (a.exposed ? 1 : 0) || _byPriceDesc((x) => x.model)(a, b));
    if (expanded) sortedBlocks.forEach((b) => { if (b.model) _aaWant.push(b.model); });
    const checklist = expanded
      ? (accBlocks.length
          ? `<div class="router-prov-models">` + sortedBlocks.map((b) => {
              const mp = modelPricing[b.model || ""] || null;
              const isFree = String(b.model || b.id || "").endsWith(":free");
              const priceHtml = isFree
                ? `<span class="router-prov-model-free">FREE</span>`
                : (mp ? `<span class="router-prov-model-price">${formatPricePer1M(mp.inputPer1M)} in / ${formatPricePer1M(mp.outputPer1M)} out /1M</span>` : "");
              return `<label class="router-prov-model${isFree ? " is-free" : ""}${b.unlisted ? " unlisted" : ""}"${b.unlisted ? ` title="${escapeHtml(t("cloudModelUnlisted"))}"` : ""}>
                <input type="checkbox" data-router-expose="${escapeHtml(b.id)}" ${b.exposed ? "checked" : ""}>
                <div class="router-prov-model-info">
                  <span class="router-prov-model-name">${escapeHtml(b.model || b.name || b.id)}</span>
                  ${priceHtml}
                </div>
                ${_unlistedTag(b)}
                ${aaBadgeHtml(b.model)}
              </label>`;
            }).join("") + `</div>`
          : `<div class="router-cfg-muted router-prov-empty">${escapeHtml(t("rtNoModelsYet"))}</div>`)
      : "";
    const rows = folded ? "" : exposedOuts.slice().sort(_byPriceDesc((o) => _blockForOut(o)?.model)).map((o) => outputRow(o, "cloud")).join("");
    return `<div class="router-prov ${expanded ? "open" : ""}${folded ? " folded" : ""}" data-cv-group-outs="${escapeHtml(exposedOuts.map((o) => o.id).join(","))}">${header}${folded ? "" : checklist}${rows}</div>`;
  }).join("") || `<div class="router-cfg-muted router-prov-empty">${t("rtNoCloudProviders")}</div>`;
  requestAaScores(_aaWant);

  return `
    <div class="router-out-sec">
      <div class="router-out-sec-h">${escapeHtml(t("rtLocal"))}</div>
      ${localHtml}
    </div>
    <div class="router-out-sec">
      <div class="router-out-sec-h">${escapeHtml(t("rtCloud"))}</div>
      ${cloudHtml}
    </div>`;
}

// Tick/untick a cloud model in the Outputs panel → routable cloud output (cb:<blockId>).
// Lets you tick several models in one go: the native checkbox reflects each click
// instantly, saves are chained so they apply in click order (the last response is
// always the authoritative full topology — no out-of-order clobbering), and the
// panel re-render is debounced so the checklist rebuilds once after you pause
// instead of fighting your clicks. The provider is pinned open so the auto-collapse
// heuristic (which closes a provider once it has ≥1 exposed model) can't snap it shut.
export let _cloudExposeChain = Promise.resolve();
export let _cloudExposeRenderTimer = null;
export function setCloudModelExposed(blockId, exposed) {
  const block = (topology?.cloudProviders || []).find((b) => b.id === blockId);
  if (block?.accountId) topologyOutputsCloudExpanded[block.accountId] = true;
  _cloudExposeChain = _cloudExposeChain.then(async () => {
    try {
      const res = await api("/api/cloud-blocks/expose", { method: "POST", body: JSON.stringify({ id: blockId, exposed: !!exposed }) });
      if (res.topology) setTopology(res.topology);
      clearTimeout(_cloudExposeRenderTimer);
      _cloudExposeRenderTimer = setTimeout(renderTopology, 250);
    } catch (e) { toast(e.message); }
  });
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
  const inputProxies = (topology?.proxies || []).filter((p) => inputs.includes(p.id));

  const bySource = router.rules?.bySource || [];
  const ruleCount = bySource.length + (router.rules?.schedule?.length || 0);
  const rulesHtml = bySource.length ? bySource.map((r, i) => {
    const srcProxy = (topology?.proxies || []).find((p) => p.id === r.proxyId);
    const srcLabel = srcProxy ? srcProxy.label : (r.proxyId || r.clientId || "?");
    const outLabel = (() => { const o = outputs.find((x) => x.id === r.output); return o ? topologyRouterOutputLabel(o) : r.output; })();
    return `
      <div class="router-cfg-rule-row" data-router-link-out="${escapeHtml(r.output)}">
        <span class="router-cfg-rule-text" title="${escapeHtml(srcLabel + " → " + outLabel)}">${escapeHtml(srcLabel)} → ${escapeHtml(outLabel)}</span>
        <button class="icon-action compact danger" type="button" data-router-del-rule="${escapeHtml(router.id)}" data-rule-index="${i}" aria-label="${escapeHtml(t("rtTitleRemoveRule"))}" title="${escapeHtml(t("rtTitleRemoveRule"))}">×</button>
      </div>`;
  }).join("") : `<div class="router-cfg-muted">${t("rtNoSourceRules")}</div>`;

  const addRuleHtml = (inputProxies.length && outputs.length) ? `
    <div class="router-cfg-add-row">
      <select class="router-cfg-select" data-router-rule-source="${escapeHtml(router.id)}">
        ${inputProxies.map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.label)}</option>`).join("")}
      </select>
      <span class="router-cfg-arrow">→</span>
      <select class="router-cfg-select" data-router-rule-output="${escapeHtml(router.id)}">
        ${outputs.map((o) => `<option value="${escapeHtml(o.id)}">${escapeHtml(topologyRouterOutputLabel(o))}</option>`).join("")}
      </select>
      <button class="primary-mini-action" type="button" data-router-add-rule="${escapeHtml(router.id)}">${escapeHtml(t("rtAddRule"))}</button>
    </div>` : "";

  // ── LEFT column: input ports, grouped by their relation to THIS router ──
  const allProxies = (topology?.proxies || []).slice().sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
  const routerIds = new Set((topology?.routers || []).map((s) => s.id));
  const routerNameOf = (id) => (topology?.routers || []).find((s) => s.id === id)?.name || id;
  const onThis = allProxies.filter((p) => p.routerId === router.id);
  const onOther = allProxies.filter((p) => p.routerId && p.routerId !== router.id && routerIds.has(p.routerId));
  const free = allProxies.filter((p) => !p.routerId || !routerIds.has(p.routerId));
  const portRole = (p) => (p.role || (String(p.label || "").match(/(primary|fallback)$/i)?.[1]?.toLowerCase()) || "");
  const portName = (p) => p.label || ("proxy " + p.port);
  const pill = (p, kind) => {
    const ri = (portRole(p)[0] || "").toUpperCase();
    const title = escapeHtml(`${portName(p)} :${p.port}`);
    const head = `<span class="router-pill-r">${escapeHtml(ri)}</span><span class="router-pill-port">${escapeHtml(p.port)}</span>`;
    if (kind === "this") {
      return `<span class="router-pill this" data-pill-name="${escapeHtml(portName(p).toLowerCase())}" data-pill-port="${escapeHtml(p.port)}" title="${title}">${head}<button class="router-pill-x" type="button" data-router-detach="${escapeHtml(p.id)}" title="${escapeHtml(t("rtTitleDetachConfirm"))}">×</button></span>`;
    }
    if (kind === "other") {
      return `<span class="router-pill other" data-router-attach="${escapeHtml(p.id)}" data-confirm="1" role="button" tabindex="0" title="${escapeHtml(t("rtTitleMoveFrom", { name: routerNameOf(p.routerId) }))}">${head}<span class="router-pill-where">${escapeHtml(routerNameOf(p.routerId))}</span></span>`;
    }
    return `<span class="router-pill free" data-router-attach="${escapeHtml(p.id)}" role="button" tabindex="0" title="${escapeHtml(t("rtTitleAttachHere", { name: portName(p) + " :" + p.port }))}">${head}<span class="router-pill-503">503</span></span>`;
  };
  const thisPills = onThis.map((p) => pill(p, "this")).join("") || `<div class="router-cfg-muted">${t("rtNoneYet")}</div>`;
  // Left-pane proxy CRUD rows (Stage A.2): the registry table, inlined as a rail list.
  // edit/delete/router-select handlers live in bindTopologyDragAndDrop (bound globally).
  const onlineClientIds = new Set((topology?.clients || []).map((c) => c.id));
  const proxyRow = (p) => {
    const owner = topologyProxyOwner(p.id);
    const orphan = !owner && !(p.clientId && onlineClientIds.has(p.clientId));
    const role = portRole(p);
    return `
      <div class="rw-proxy-row ${orphan ? "orphan" : ""}" data-pill-name="${escapeHtml(portName(p).toLowerCase())}" data-pill-port="${escapeHtml(p.port)}">
        <span class="rw-proxy-drag" data-wire-ref="in:${escapeHtml(p.id)}" data-wire-label="${escapeHtml(portName(p))}" title="${escapeHtml(t("rtTitleDragPort"))}">⠿</span>
        <span class="rw-proxy-port">:${escapeHtml(p.port)}</span>
        <span class="rw-proxy-name" title="${escapeHtml(portName(p))}">${escapeHtml(owner?.title || portName(p))}${orphan ? ` <span class="rw-proxy-orphan" title="${escapeHtml(t("rtTitleOrphan"))}">${escapeHtml(t("rtOrphan"))}</span>` : ""}</span>
        ${role ? `<span class="rw-proxy-role ${escapeHtml(role)}" title="${escapeHtml(role)}">${escapeHtml((role[0] || "").toUpperCase())}</span>` : `<span class="rw-proxy-role">·</span>`}
        <span class="rw-proxy-actions">
          <button class="icon-action compact" type="button" data-topology-proxy-edit="${escapeHtml(p.id)}" aria-label="${escapeHtml(t("rtTitleRenamePort"))}" title="${escapeHtml(t("rtTitleRenamePort"))}">✎</button>
          <button class="icon-action compact" type="button" data-router-detach="${escapeHtml(p.id)}" aria-label="${escapeHtml(t("rtTitleDetach"))}" title="${escapeHtml(t("rtTitleDetach"))}">⊘</button>
          <button class="icon-action compact danger" type="button" data-topology-proxy-delete="${escapeHtml(p.id)}" aria-label="${escapeHtml(t("rtTitleDeletePort"))}" title="${escapeHtml(t("rtTitleDeletePort"))}">🗑</button>
        </span>
      </div>`;
  };
  const thisRows = onThis.map(proxyRow).join("") || `<div class="router-cfg-muted">${t("rtNoneYet")}</div>`;

  // Center pane = the interactive canvas (was the separate ⤢ modal). Reuses the same
  // node descriptors + cv-* markup; the bind/render cycle (search ui.topologyCanvasRouterId)
  // redraws + rebinds it on every render, and we set ui.topologyCanvasRouterId together with
  // the workspace on open.
  const cvNodeHtml = canvasNodes(router).map((n) => {
    const pos = _cvPos[n.id] || n.fixed || { x: n.dx, y: n.dy };
    return `<div class="cv-node cv-${n.type} ${n.cls || ""}" data-cv-node="${escapeHtml(n.id)}" style="left:${pos.x}px;top:${pos.y}px">${n.html}</div>`;
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
          <a class="rw-back-link" href="/">← Main</a>
          <div class="rw-head-title-group">
            <span class="rw-head-name">${escapeHtml(t("topologyRouterTitle"))}</span>
            <div class="rw-head-badges">
              <span class="badge rw-stat-badge">in <strong>${inputs.length}</strong></span>
              <span class="badge rw-stat-badge">out <strong>${outputs.length}</strong></span>
              ${ruleCount ? `<span class="badge rw-stat-badge">${escapeHtml(t("rtRules", { n: ruleCount }))}</span>` : ""}
              ${defaultOut ? `<span class="badge rw-default-chip" data-router-link-out="${escapeHtml(defaultOut.id)}" title="${escapeHtml(t("rtTitleDefaultOutput"))}">default → ${escapeHtml(topologyRouterOutputLabel(defaultOut))}</span>` : ""}
              ${(onOther.length + free.length) ? `<span class="rw-unassigned-badge" title="${escapeHtml(t("rtTitleUnassigned", { f: free.length, o: onOther.length }))}">${escapeHtml(t("rtUnassigned", { n: free.length + onOther.length }))}</span>` : ""}
            </div>
          </div>
          <span class="topology-policy-head-actions">
            <button type="button" class="ob-btn-head" data-ob-tour>
              <span class="ob-q">?</span>${escapeHtml(t("tourBtnLabel"))}
            </button>
          </span>
        </div>` : `
        <div class="rw-head">
          <span class="router-cfg-title">
            <strong>${escapeHtml(t("topologyRouterTitle"))}</strong>
            <span class="router-cfg-sub">in ${inputs.length} · out ${outputs.length}${ruleCount ? ` · ${escapeHtml(t("rtRules", { n: ruleCount }))}` : ""}</span>
            ${defaultOut ? `<span class="rw-default-badge" data-router-link-out="${escapeHtml(defaultOut.id)}" title="${escapeHtml(t("rtTitleDefaultOutput"))}">default → <strong>${escapeHtml(topologyRouterOutputLabel(defaultOut))}</strong></span>` : ""}
          </span>
          <span class="topology-policy-head-actions">
            ${(onOther.length + free.length) ? `<span class="rw-unassigned-badge" title="${escapeHtml(t("rtTitleUnassigned", { f: free.length, o: onOther.length }))}">${escapeHtml(t("rtUnassigned", { n: free.length + onOther.length }))}</span>` : ""}
            <button class="icon-action compact" type="button" data-topology-router-close aria-label="${escapeHtml(t("close"))}" title="${escapeHtml(t("close"))}">×</button>
          </span>
        </div>`}
        <div class="rw-cols">
          <section class="rw-pane rw-center">
            <div class="rw-palette">
              <span class="rw-palette-label">${escapeHtml(t("rtRuleNodeLabel"))} <span class="inline-tip help-tip" tabindex="0">?<span class="tooltip">${t("rtPaletteTip")}</span></span></span>
              <button class="cv-palette-btn" type="button" data-cv-add="schedule" title="${escapeHtml(t("rtTitleSchedule"))}">⏱ ${escapeHtml(t("cvNodeSchedule"))}</button>
              <button class="cv-palette-btn" type="button" data-cv-add="weighted" title="${escapeHtml(t("rtTitleWeighted"))}">⚖ ${escapeHtml(t("cvNodeWeighted"))}</button>
              <button class="cv-palette-btn" type="button" data-cv-add="roundRobin" title="${escapeHtml(t("rtTitleRoundRobin"))}">🔁 ${escapeHtml(t("cvNodeRoundRobin"))}</button>
              <button class="cv-palette-btn" type="button" data-cv-add="failover" title="${escapeHtml(t("rtTitleFailover"))}">⚡ ${escapeHtml(t("cvNodeFailover"))}</button>
              <button class="cv-palette-btn" type="button" data-cv-add="queue" title="${escapeHtml(t("rtTitleQueue"))}">⏳ ${escapeHtml(t("cvNodeQueue"))}</button>
              <button class="cv-palette-btn" type="button" data-cv-add="requestType" title="${escapeHtml(t("rtTitleByType"))}">🔀 ${escapeHtml(t("cvNodeByType"))}</button>
              <button class="cv-palette-btn" type="button" data-cv-add="requestSize" title="${escapeHtml(t("rtTitleBySize"))}">📏 ${escapeHtml(t("cvNodeBySize"))}</button>
              <span class="rw-palette-save" title="${escapeHtml(t("rtTitleAutoSaveInstant"))}">⤓ ${escapeHtml(t("rtAutoSave"))}</span>
            </div>
            ${renderRouterNodeConfig(router)}
            <div class="cv-viewport" data-cv-viewport>
              <div class="cv-world" data-cv-world style="transform:${cvTf}">
                <svg class="cv-svg" data-cv-svg width="4000" height="3000" viewBox="0 0 4000 3000"></svg>
                ${cvNodeHtml}
              </div>
              <div class="rw-canvas-hint muted">${escapeHtml(t("rtCanvasHint"))}</div>
            </div>
          </section>
        </div>
      </div>
    </div>`;
}

