// Router node canvas: nodes, connectors, pan/zoom, schedule grid painting.
import { appConfirm, appPrompt } from "./dialogs.js";
import { option } from "./form.js";
import { helpTip, t } from "./i18n.js";
import { closeConfirmModal } from "./llama-edit.js";
import { action } from "./polling.js";
import { deleteOrphanAgent } from "./remote-cells.js";
import {
  renderServersBlockHtml,
  routerById,
  saveRouters,
  topologyRouterOutputLabel,
} from "./routers.js";
import { state, topology, ui, setTopology } from "./state.js";
import {
  _proxyUpstreamStr,
  ensureStickyBarTicker,
  proxyEffectiveWaitTimeout,
  stickySlotAnims,
  topologyDurationMs,
  topologyFormatDuration,
  topologyItemGroup,
  topologyQueueRuntime,
  topologyRuntimeOverview,
} from "./topology-activity.js";
import {
  _cvProxyIsStale,
  _cvProxyIsTombstoned,
  editTopologyProxy,
  topologyMutedProxyIds,
  topologyProxyOwner,
  canvasBoardClients,
} from "./topology-proxies.js";
import { refreshTopology, renderTopology, topologyStructureFingerprint } from "./topology-render.js";
import { $, api, copyText, escapeHtml, toast } from "./utils.js";

export let _cvQueueHistOpen = {};                 // nodeId -> bool: history pane open?
export let _cvQueueHistData = {};                 // nodeId -> { rows, ts } cached log data
export let _cvSchedHistOpen = {};                 // nodeId -> bool: schedule history pane open?
export let _cvSchedHistData = {};                 // nodeId -> { rows, ts } cached log data
export let _cvSchedPainting = false;             // pointer is held down on a schedule grid (mirror of board.paint.painting)
// ── Router canvas (Phase 3: interactive node graph) ───────────────────────
// Client naming lives on InputsBlock; these faces stay for topology-proxies and the graph.
export function _cvAgentGroup(p) { return InputsBlock.agentGroup(p); }
export function _cvPrimaryPort(p) { return InputsBlock.primaryPort(p); }
export function _cvProxyToAgent() { return InputsBlock.proxyToAgent(); }
export function canvasClientKey(p) { return InputsBlock.clientKey(p); }
export function canvasClientName(p) { return InputsBlock.clientName(p); }

export let _cvView = { tx: 24, ty: 24, scale: 1 };   // world transform (mirror of board.view)
export let _cvPos = {};                               // nodeId -> {x,y} (mirror of board.pos)
export let _cvDrag = null;                            // active drag (mirror of board.drag)










// ── Canvas schedule node helpers ──────────────────────────────────────────────
// ── Weekly schedule (paint days×hours → router outputs) ───────────────────────
export const SCHEDULE_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const SCHEDULE_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const SCHEDULE_COLORS = ["#60a5fa", "#f59e0b", "#22c55e", "#ef4444", "#a78bfa", "#ec4899", "#14b8a6", "#eab308"];
export const CV_SCHED_COLORS = SCHEDULE_COLORS;
export const CV_SCHED_DAY_LABELS = SCHEDULE_DAY_LABELS;





function cvPortIn() { return `<span class="cv-port in" data-cv-port="in" title="${escapeHtml(t("cvDropHere"))}"></span>`; }
function cvPortOut() { return `<span class="cv-port out" data-cv-port="out" title="${escapeHtml(t("cvDragConnect"))}"></span>`; }


// ── History pane: the request log under a queue or schedule card ──────────────
// One log fetch feeds both panes; the caches are keyed per node, so each pane
// refreshes on its own clock.
export class History {
  // ── Queue history helpers ────────────────────────────────────────────────────
  static fmt(ms) {
    if (ms == null || ms < 0) return "—";
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const m = Math.floor(ms / 60000), s = Math.round((ms % 60000) / 1000);
    return `${m}m${s > 0 ? ` ${s}s` : ""}`;
  }
  static model(item) {
    // Overflow to cloud — return amber indicator + cloud model name
    if (item.queue?.cloudFallback || item.upstreamType === "cloud") {
      const m = String(item.model || "cloud");
      return { text: m, overflow: true };  // CSS text-overflow handles display
    }
    // Local model — shorten gguf name: "Qwen_Qwen3.6-27B-Q5_K_L.gguf" → "Qwen3.6-27B"
    const m = item.stream?.model || item.model || "";
    if (!m) return { text: "?", overflow: false };
    const base = m.replace(/.*\//, "").replace(/\.gguf$/i, "");
    const parts = base.split(/[-_]/);
    // Find size token like "27B", "3.6", combine with preceding family name
    let short = base;
    for (let i = 0; i < parts.length; i++) {
      if (/^\d+(\.\d+)?[BbMm]?$/.test(parts[i]) && parts[i].length > 1) {
        const family = parts.slice(0, i).filter(Boolean).pop() || parts[0];
        short = `${family}-${parts[i]}`;
        break;
      }
    }
    // No JS length limit — CSS text-overflow:ellipsis handles display, title shows full name
    return { text: short, overflow: false };
  }
  static route(raw) {
    const item = raw.item || {};
    if (item.port) return InputsBlock.portName(item.port, { short: true });
    // Fallback when port missing: strip suffix from route label
    const r = String(raw.route || item.route || "");
    let name = r.replace(/ (?:primary|fallback)$/i, "").trim();
    if (name.includes("·")) name = name.split("·").pop().trim();
    return name.slice(0, 8) || ":?";
  }
  // One log fetch feeds both history panes (queue and schedule nodes); the cache is
  // keyed per node, so each pane refreshes on its own clock.
  static fetch(cache, nodeId) {
    fetch("/api/agent-proxy-logs?event=finished&limit=40")
      .then((r) => r.json())
      .then((data) => { cache[nodeId] = { rows: data.rows || [], ts: Date.now() }; renderTopology(); })
      .catch(() => { cache[nodeId] = { rows: [], ts: Date.now(), err: true }; renderTopology(); });
  }
  static queueHtml(nodeId) {
    const cache = _cvQueueHistData[nodeId];
    if (!cache) return `<div class="cv-q-hist-loading">${t("loadingEllipsis")}</div>`;
    if (cache.err) return `<div class="cv-q-hist-loading">${t("cvFailedLoad")}</div>`;
    if (!cache.rows.length) return `<div class="cv-q-hist-loading">${t("cvNoHistory")}</div>`;

    const batch = cache.rows.slice(0, 25);
    // Pre-compute max processing time for relative bar scaling
    const procMsList = batch.map((raw) => {
      const item = raw.item || {};
      return Math.max(0, (item.durationMs || 0) - (item.queue?.queuedMs || 0));
    });
    const maxProc = Math.max(1, ...procMsList);

    const rows = batch.map((raw, idx) => {
      const item = raw.item || {};
      const ok = !item.errorKind && (item.status || 200) < 500;
      const route = escapeHtml(History.route(raw));
      const startTime = item.startedAt
        ? new Date(item.startedAt * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
        : "—";
      const waitMs = item.queue?.queuedMs ?? 0;
      const procMs = procMsList[idx];
      const barPct = Math.round((procMs / maxProc) * 100);
      const model = History.model(item);
      const statusCls = ok ? "cv-q-hist-ok" : "cv-q-hist-err";
      const statusGlyph = ok ? "✓" : "✗";
      const errTitle = item.errorKind ? item.errorKind.replace(/_/g, " ") : "";
      const waitHtml = waitMs > 0
        ? `<span class="cv-q-hist-wait" title="queued ${History.fmt(waitMs)}">W:${History.fmt(waitMs)}</span>`
        : `<span class="cv-q-hist-wait muted">—</span>`;
      return `<div class="cv-q-hist-row" title="${escapeHtml(item.route || "")}${errTitle ? " · " + errTitle : ""}">
        <span class="cv-q-hist-route">${route}</span>
        <span class="cv-q-hist-time">${startTime}</span>
        ${waitHtml}
        <span class="cv-q-hist-bar-wrap">
          <span class="cv-q-hist-track"><span class="cv-q-hist-fill" style="width:${barPct}%"></span></span>
          <span class="cv-q-hist-dur">${History.fmt(procMs)}</span>
        </span>
        <span class="cv-q-hist-model${model.overflow ? " overflow" : ""}" title="${escapeHtml(model.text)}">${model.overflow ? "↗ " : ""}${escapeHtml(model.text)}</span>
        <span class="${statusCls}" title="${errTitle}">${statusGlyph}</span>
      </div>`;
    }).join("");

    const age = Math.round((Date.now() - cache.ts) / 1000);
    return rows + `<div class="cv-q-hist-age">${age}s ago · <button class="cv-q-hist-refresh" type="button" data-cv-q-hist-refresh="${escapeHtml(nodeId)}">↻ refresh</button></div>`;
  }
  // Render schedule history: only requests from ports wired into this schedule node.
  static scheduleHtml(nodeId, outputs, grid, inputPorts) {
    const cache = _cvSchedHistData[nodeId];
    if (!cache) return `<div class="cv-q-hist-loading">${t("loadingEllipsis")}</div>`;
    if (cache.err) return `<div class="cv-q-hist-loading">${t("cvFailedLoad")}</div>`;

    if (inputPorts && inputPorts.size === 0) {
      return `<div class="cv-q-hist-loading">${t("cvNoInputs")}</div>`;
    }

    // Filter to only rows from ports wired into this schedule node
    const filtered = (cache.rows || []).filter((raw) => {
      const port = raw.item?.port;
      return !inputPorts || !port || inputPorts.has(Number(port));
    }).slice(0, 20);

    if (!filtered.length) return `<div class="cv-q-hist-loading">${t("cvNoHistory")}</div>`;

    const rows = filtered.map((raw) => {
      const item = raw.item || {};
      const ok = !item.errorKind && (item.status || 200) < 500;
      const ts = item.startedAt ? new Date(item.startedAt * 1000) : null;
      const d = ts ? (ts.getDay() + 6) % 7 : -1;   // Mon=0
      const h = ts ? ts.getHours() : -1;
      const savedOutId = item.routedOutputId;
      const savedOutName = item.routedOutputName;
      let outName, outColor;
      if (savedOutId) {
        const savedOut = outputs.find((o) => o.id === savedOutId);
        outName = savedOutName || (savedOut ? savedOut.name : "default");
        outColor = savedOut ? ScheduleNode.color(outputs, savedOut.id) : "";
      } else {
        const activeOutId = (d >= 0 && grid[d]?.[h]) || null;
        const activeOut = activeOutId ? outputs.find((o) => o.id === activeOutId) : null;
        outName = activeOut ? activeOut.name : "default";
        outColor = activeOut ? ScheduleNode.color(outputs, activeOut.id) : "";
      }
      const dayLabel = d >= 0 ? CV_SCHED_DAY_LABELS[d] : "?";
      const timeStr = ts ? ts.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
      const route = escapeHtml(History.route(raw));
      const model = History.model(item);
      const statusCls = ok ? "cv-q-hist-ok" : "cv-q-hist-err";
      const dotStyle = outColor ? `background:${outColor}` : "background:var(--muted)";
      return `<div class="cv-sched-hist-row" title="${dayLabel} ${h >= 0 ? h + ":00" : "?"} → ${escapeHtml(outName)}${item.errorKind ? " · " + item.errorKind.replace(/_/g, " ") : ""}">
        <span class="cv-q-hist-route">${route}</span>
        <span class="cv-q-hist-time">${timeStr}</span>
        <span class="cv-sched-hist-out"><i class="cv-sched-dot" style="${dotStyle}"></i>${escapeHtml(outName)}</span>
        <span class="cv-sched-hist-when">${dayLabel} ${h >= 0 ? h + "h" : "?"}</span>
        <span class="cv-q-hist-model${model.overflow ? " overflow" : ""}" title="${escapeHtml(model.text)}">${model.overflow ? "↗ " : ""}${escapeHtml(model.text)}</span>
        <span class="${statusCls}">${ok ? "✓" : "✗"}</span>
      </div>`;
    }).join("");

    const age = Math.round((Date.now() - cache.ts) / 1000);
    return rows + `<div class="cv-q-hist-age">${age}s ago · <button class="cv-q-hist-refresh" type="button" data-cv-sched-hist-refresh="${escapeHtml(nodeId)}">↻ refresh</button></div>`;
  }
}

// ── Rule nodes: one class per kind ────────────────────────────────────────────
// A record of router.graph.nodes wrapped for rendering: the card on the canvas, the
// ⚙ panel body, the one-line summary. Kinds differ in what the card shows and where
// its out-ports live; the base class holds the shared frame (head, ×, in-port).
export class RuleNode {
  static KINDS = {};
  static from(rec, router) { const K = RuleNode.KINDS[rec.type] || RuleNode; return new K(rec, router); }
  // Localized display label for a rule-node type (palette buttons + card heads).
  static typeLabel(type) {
    const key = { schedule: "cvNodeSchedule", weighted: "cvNodeWeighted", roundRobin: "cvNodeRoundRobin",
      failover: "cvNodeFailover", queue: "cvNodeQueue", requestType: "cvNodeByType", requestSize: "cvNodeBySize",
      onError: "cvNodeOnError" }[type];
    return key ? t(key) : type;
  }
  constructor(rec, router) { this.rec = rec; this.router = router || {}; }
  get id() { return this.rec.id; }
  get type() { return this.rec.type; }
  get config() { return this.rec.config || {}; }
  get outEdges() { return new Graph(this.router).outEdges(this.id); }
  get cls() { return ""; }
  // Cards that carry their OWN out-ports inside the body skip the generic one.
  get ownPorts() { return false; }
  get glyph() { return NODE_GLYPH[this.type] || "•"; }
  get label() { return RuleNode.typeLabel(this.type); }
  get fixed() { return { x: this.rec.x || 0, y: this.rec.y || 0 }; }
  summary() { return ""; }
  // Setup control in the head: a gear opens the ⚙ panel; cards with inline fields
  // show a ? tooltip instead.
  cfgControl() { return `<button class="cv-act cv-rule-cfg" type="button" data-cv-cfgnode="${escapeHtml(this.id)}" title="${escapeHtml(t("cvConfigureNode"))}">⚙</button>`; }
  head() {
    return `<span class="cv-rule-head"><strong>${this.glyph} ${escapeHtml(this.label)}</strong>`
      + `<span class="cv-rule-btns">${this.cfgControl()}`
      + `<button class="cv-act cv-rule-del" type="button" data-cv-delnode="${escapeHtml(this.id)}" title="${escapeHtml(t("cvTitleDeleteNode"))}">×</button></span></span>`;
  }
  body() { return `<span class="cv-sub">${escapeHtml(this.summary())}</span>`; }
  cardHtml() { return this.head() + this.body() + cvPortIn() + (this.ownPorts ? "" : cvPortOut()); }
  descriptor() { return { id: `rule:${this.id}`, type: "rule", cls: this.cls, fixed: this.fixed, html: this.cardHtml() }; }
  targetLabel(edge) { return edge ? Edge.targetLabel(this.router, edge) : "drag a cable →"; }
  // A destination row of the card: coloured dot, name, target, and the row's OWN
  // out-port (drag a cable from it). Unwired ports pulse so you know they must be
  // connected. portAttr names the port for the edge plumbing — data-cv-qrole for a
  // role cable, data-cv-sched-port for a tagged one.
  // `lead` goes before the role dot, `extra` after the target label: the backup
  // node puts its ▶ and its health dot there; queue rows pass neither.
  destRow({ cls, name, label, wired, portAttr, hint, lead = "", extra = "" }) {
    return `<div class="cv-q-dest ${cls}${wired ? "" : " unset"}">`
      + lead
      + `<span class="cv-q-dot ${cls}"></span>`
      + `<span class="cv-q-dl">${name}</span>`
      + `<span class="cv-q-dt" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`
      + extra
      + `<span class="cv-port out${wired ? "" : " unset"}" data-cv-port="out" ${portAttr} title="${escapeHtml(hint)}"></span>`
      + `</div>`;
  }
  // ⚙ panel body; nothing to configure until a cable leaves the node.
  panelNeedsEdges() { return true; }
  panelBody(edges) { return `<div class="rw-cfg-hint">${t("cvHintRoundRobin", { n: edges.length })}</div>`; }
}

export class WeightedNode extends RuleNode {
  summary() { return (this.config.weights || []).map((w) => `${w.pct}%`).join(" / ") || t("cvSumNoWeights"); }
  panelBody(edges) {
    return `<div class="rw-cfg-hint">${t("cvHintWeighted")}</div>`
      + edges.map((e) => {
        const w = (this.config.weights || []).find((x) => x.edge === e.id);
        return `<label class="rw-cfg-row"><span class="rw-cfg-tgt" title="${escapeHtml(this.targetLabel(e))}">${escapeHtml(this.targetLabel(e))}</span><input class="rw-cfg-in rw-cfg-num" type="number" min="0" max="100" data-cfg-weight="${escapeHtml(e.id)}" value="${w ? w.pct : 0}"><span class="rw-cfg-unit">%</span></label>`;
      }).join("");
  }
}

export class FailoverNode extends RuleNode {
  summary() { return t("cvSumInOrder", { n: (this.config.order || []).length }); }
  panelBody(edges) {
    const cfg = this.config;
    const order = (cfg.order && cfg.order.length ? cfg.order.filter((id) => edges.some((e) => e.id === id)) : edges.map((e) => e.id));
    return `<div class="rw-cfg-hint">${t("cvHintFailover")}</div><ol class="rw-cfg-order">`
      + order.map((id, i) => {
        const e = edges.find((x) => x.id === id);
        return `<li data-cfg-ord-id="${escapeHtml(id)}"><span class="rw-cfg-tgt">${escapeHtml(this.targetLabel(e))}</span><span class="rw-cfg-ord"><button class="icon-action compact" type="button" data-cfg-up="${escapeHtml(id)}" ${i === 0 ? "disabled" : ""}>↑</button><button class="icon-action compact" type="button" data-cfg-down="${escapeHtml(id)}" ${i === order.length - 1 ? "disabled" : ""}>↓</button></span></li>`;
      }).join("") + `</ol>`;
  }
}

export class RoundRobinNode extends RuleNode {
  summary() { return t("cvSumRotate"); }
}

// Weekly schedule: outputs are painted onto a 7×24 grid; each output (and the
// default branch) is a row with its own out-port. Collapsed, only the ports stay.
export class ScheduleNode extends RuleNode {
  get cls() { return "cv-rule-sched"; }
  // Walk edges backwards from schedNodeId to find all proxy port numbers that reach it.
  static inputPorts(router, schedNodeId) {
    const edges = (router?.graph?.edges || []);
    const target = `rule:${schedNodeId}`;
    const reachable = new Set([target]);
    let changed = true;
    while (changed) {
      changed = false;
      for (const e of edges) {
        const t = String(e.to || ""), f = String(e.from || "");
        if (reachable.has(t) && !reachable.has(f)) { reachable.add(f); changed = true; }
      }
    }
    const ports = new Set();
    for (const ref of reachable) {
      const m = ref.match(/:(\d+)$/);
      if (m && ref.startsWith("in:")) ports.add(Number(m[1]));
    }
    return ports;
  }
  static color(outputs, outId) {
    const i = (outputs || []).findIndex((o) => o.id === outId);
    return i < 0 ? "" : CV_SCHED_COLORS[i % CV_SCHED_COLORS.length];
  }
  static makeGrid(cfg) {
    const raw = cfg.grid || [];
    return Array.from({ length: 7 }, (_, d) =>
      Array.from({ length: 24 }, (_, h) => { const row = raw[d]; return (Array.isArray(row) ? row[h] : null) || null; })
    );
  }
  static now() {
    const now = new Date();
    return {
      d: (now.getDay() + 6) % 7,   // Mon=0 … Sun=6
      h: now.getHours(),
      timeStr: String(now.getHours()).padStart(2, "0") + ":" + String(now.getMinutes()).padStart(2, "0"),
    };
  }
  // Lightweight ticker — updates clock text and "now" markers without full re-render
  static tickNow() {
    const { d: nowD, h: nowH, timeStr } = ScheduleNode.now();

    // Update clock text in all rendered schedule nodes
    document.querySelectorAll("[data-cv-sched-clock]").forEach((el) => { el.textContent = timeStr; });

    // Move now-row class
    document.querySelectorAll(".cv-sched-gcal-row--now").forEach((r) => r.classList.remove("cv-sched-gcal-row--now"));
    document.querySelectorAll(`[data-cv-sched-row-h="${nowH}"]`).forEach((r) => r.classList.add("cv-sched-gcal-row--now"));

    // Move now-day column highlight + now-cell marker
    document.querySelectorAll(".cv-sched-cell--now, .cv-sched-cell--now-d").forEach((c) => {
      c.classList.remove("cv-sched-cell--now", "cv-sched-cell--now-d");
    });
    document.querySelectorAll("[data-cv-sched-cell]").forEach((cell) => {
      const d = +cell.dataset.schedD, h = +cell.dataset.schedH;
      if (d === nowD && h === nowH) cell.classList.add("cv-sched-cell--now");
      else if (d === nowD)          cell.classList.add("cv-sched-cell--now-d");
    });

    // Move now-day header highlight
    document.querySelectorAll(".cv-sched-gcal-dh--now").forEach((el) => el.classList.remove("cv-sched-gcal-dh--now"));
    document.querySelectorAll(".cv-sched-gcal-dh").forEach((el, i) => {
      if (i % 7 === nowD) el.classList.add("cv-sched-gcal-dh--now");
    });

    // Update "now active" output rows — read painted cell to find active outId
    document.querySelectorAll(".cv-sched-row--now-active").forEach((r) => r.classList.remove("cv-sched-row--now-active"));
    // For each schedule node, find the now cell and resolve which chip is active
    const nowCells = document.querySelectorAll(`[data-cv-sched-cell][data-sched-d="${nowD}"][data-sched-h="${nowH}"]`);
    nowCells.forEach((cell) => {
      const nid = cell.dataset.cvSchedCell;
      // painted cell → find matching chip row; unpainted → default row
      if (cell.classList.contains("painted")) {
        const color = cell.style.background;
        // Find the chip row whose dot matches this color
        const rows = document.querySelectorAll(`[data-cv-sched-chip^="${CSS.escape(nid)}:"]`);
        rows.forEach((row) => {
          const dot = row.querySelector(".cv-sched-dot");
          if (dot && dot.style.background === color) row.classList.add("cv-sched-row--now-active");
        });
      } else {
        // default row
        const defRow = document.querySelector(`[data-cv-sched-chip="${CSS.escape(nid)}:__default__"]`);
        if (defRow) defRow.classList.add("cv-sched-row--now-active");
      }
    });
  }
  static outputColor(router, outputId) {
    const i = (router?.outputs || []).findIndex((o) => o.id === outputId);
    return i < 0 ? "" : SCHEDULE_COLORS[i % SCHEDULE_COLORS.length];
  }
  summary() { return t("cvSumWindows", { n: (this.config.windows || []).length }); }
  panelBody() { return `<div class="rw-cfg-hint">${t("cvHintSchedule")}</div>`; }
  // Inline expanded/collapsed body with own ports — no generic out-port.
  cardHtml() { return this.html() + cvPortIn(); }
  html() {
  const n = this.rec, router = this.router, nid = this.id, cfg = this.config;
  const outputs = cfg.outputs || [];
  const grid = ScheduleNode.makeGrid(cfg);
  const inputPorts = ScheduleNode.inputPorts(router, nid);  // ports that enter this node
  const paintId = _cvSchedPaintIds[nid] ?? (outputs[0]?.id || "");
  const collapsed = _cvSchedCollapsed.has(nid);
  const { d: nowD, h: nowH, timeStr: nowTimeStr } = ScheduleNode.now();
  const activeNowId = grid[nowD]?.[nowH] || null;   // null → "default" is active

  const toggleBtn = `<button class="cv-act cv-sched-toggle" type="button" data-cv-sched-toggle="${escapeHtml(nid)}" title="${escapeHtml(collapsed ? t("expand") : t("collapse"))}">${collapsed ? "+" : "−"}</button>`;
  const head = `<span class="cv-rule-head"><strong>⏱ ${escapeHtml(t("cvNodeSchedule"))}</strong><span class="cv-sched-now-clock" data-cv-sched-clock="${escapeHtml(nid)}">${nowTimeStr}</span><span class="cv-rule-btns">${toggleBtn}<button class="cv-act cv-rule-del" type="button" data-cv-delnode="${escapeHtml(nid)}" title="${escapeHtml(t("cvTitleDeleteNode"))}">×</button></span></span>`;

  if (collapsed) {
    const activeName = activeNowId ? (outputs.find((o) => o.id === activeNowId)?.name || t("cvLabelOutput")) : (cfg.defaultName || "default");
    const ports = [...outputs.map((o) =>
      `<div class="cv-sched-chip-stub"><span class="cv-port out" data-cv-port="out" data-cv-sched-port="${escapeHtml(o.id)}" title="${escapeHtml(o.name)} →"></span></div>`
    ), `<div class="cv-sched-chip-stub"><span class="cv-port out" data-cv-port="out" data-cv-sched-port="__default__" title="default →"></span></div>`].join("");
    return head
      + `<span class="cv-sub">${escapeHtml(t("cvSchedOutputsNow", { n: outputs.length, name: activeName }))}</span>`
      + ports;
  }

  // ── Output rows (full-width, like queue rows) ──────────────────────────────
  const rows = [
    ...outputs.map((o, i) => {
      const color = CV_SCHED_COLORS[i % CV_SCHED_COLORS.length];
      const active = paintId === o.id;
      const nowActive = o.id === activeNowId;
      return `<div class="cv-sched-row${active ? " cv-sched-row--active" : ""}${nowActive ? " cv-sched-row--now-active" : ""}" data-cv-sched-chip="${escapeHtml(nid)}:${escapeHtml(o.id)}">`
        + `<i class="cv-sched-dot" style="background:${color}"></i>`
        + `<span class="cv-sched-name" data-cv-sched-rename="${escapeHtml(nid)}:${escapeHtml(o.id)}" spellcheck="false" aria-label="${escapeHtml(t("a11yScheduleOutputName"))}">${escapeHtml(o.name)}</span>`
        + `<button class="cv-sched-rm" type="button" data-cv-sched-rmout="${escapeHtml(nid)}:${escapeHtml(o.id)}" title="${escapeHtml(t("cvTitleRemove"))}">×</button>`
        + `<span class="cv-port out" data-cv-port="out" data-cv-sched-port="${escapeHtml(o.id)}" title="${escapeHtml(t("cvDragConnect"))}"></span>`
        + `</div>`;
    }),
    `<div class="cv-sched-row cv-sched-row--default${paintId === "__default__" ? " cv-sched-row--active" : ""}${activeNowId === null ? " cv-sched-row--now-active" : ""}" data-cv-sched-chip="${escapeHtml(nid)}:__default__">`
      + `<i class="cv-sched-dot cv-sched-dot--default"></i>`
      + `<span class="cv-sched-name" data-cv-sched-rename-default="${escapeHtml(nid)}" spellcheck="false" aria-label="${escapeHtml(t("a11yDefaultBranchName"))}">${escapeHtml(cfg.defaultName || "default")}</span>`
      + `<span class="cv-port out" data-cv-port="out" data-cv-sched-port="__default__" title="${escapeHtml(t("cvDragConnect"))}"></span>`
      + `</div>`,
    `<button class="cv-sched-addrow" type="button" data-cv-sched-addout="${escapeHtml(nid)}">+ output</button>`,
  ].join("");

  // ── GCal grid: hours as rows (0→23), days as columns (Mon→Sun) ────────────
  const gcalHdr = `<div class="cv-sched-gcal-hdr">`
    + `<div class="cv-sched-gcal-corner"></div>`
    + CV_SCHED_DAY_LABELS.map((dl, d) => `<div class="cv-sched-gcal-dh${d === nowD ? " cv-sched-gcal-dh--now" : ""}">${dl}</div>`).join("")
    + `</div>`;

  const gcalRows = Array.from({ length: 24 }, (_, h) =>
    `<div class="cv-sched-gcal-row${h === nowH ? " cv-sched-gcal-row--now" : ""}" data-cv-sched-row-h="${h}">`
    + `<div class="cv-sched-gcal-hl">${h % 3 === 0 ? h : ""}</div>`
    + CV_SCHED_DAY_LABELS.map((_, d) => {
        const outId = grid[d][h];
        const color = outId ? ScheduleNode.color(outputs, outId) : "";
        const isNowCell = (d === nowD && h === nowH);
        const isNowCol  = (d === nowD && h !== nowH);
        return `<div class="cv-sched-cell${outId ? " painted" : ""}${isNowCell ? " cv-sched-cell--now" : ""}${isNowCol ? " cv-sched-cell--now-d" : ""}" data-cv-sched-cell="${escapeHtml(nid)}" data-sched-d="${d}" data-sched-h="${h}"${color ? ` style="background:${color}"` : ""}></div>`;
      }).join("")
    + `</div>`
  ).join("");

  // ── History pane ──────────────────────────────────────────────────────────
  const histOpen = !!_cvSchedHistOpen[nid];
  const histCache = _cvSchedHistData[nid];
  if (histOpen && histCache && Date.now() - histCache.ts > 15000) {
    setTimeout(() => History.fetch(_cvSchedHistData, nid), 0);
  }
  const histSection = `<div class="cv-q-hist${histOpen ? " open" : ""}">
    <button class="cv-act cv-q-hist-toggle" type="button" data-cv-sched-hist-toggle="${escapeHtml(nid)}">
      🕐 history ${histOpen ? "▴" : "▾"}
    </button>
    ${histOpen ? `<div class="cv-q-hist-body">${History.scheduleHtml(nid, outputs, grid, inputPorts)}</div>` : ""}
  </div>`;

  return head
    + `<div class="cv-sched-rows">${rows}</div>`
    + `<div class="cv-sched-gcal">${gcalHdr}${gcalRows}</div>`
    + histSection;
  }
}

// Rich, self-explanatory queue node card: live "now processing" (client → upstream),
// the waiting queue with per-request expiring bars (spill + abort markers), a slot
// meter, and admit/spill destination rows each carrying their OWN output port.
export class QueueNode extends RuleNode {
  get cls() { return "cv-rule-queue"; }
  get ownPorts() { return true; }
  // Inline config fields live on the card — a ? tooltip instead of a gear.
  cfgControl() { return helpTip("cvTipQueueNode"); }
  // Re-patch the live region of every canvas queue node card on the background tick.
  // Queue node cards are only (re)built by a full renderTopology(); steady traffic
  // doesn't change topologyStructureFingerprint(), so without this the now-processing /
  // waiting lists stay frozen at their last full-render snapshot. Mirrors how the
  // Main SLOTS panel is kept live — replace only the inner .cv-q-live region so the
  // node's cables, out-ports, param inputs and history pane are untouched.
  static syncLive() {
    if (!topology) return;
    const liveEls = document.querySelectorAll("[data-cv-q-live]");
    if (!liveEls.length) return;
    const byId = {};
    (topology.routers || []).forEach((r) => {
      ((r.graph && r.graph.nodes) || []).forEach((nd) => {
        if (nd.type === "queue") byId[nd.id] = { router: r, node: nd };
      });
    });
    liveEls.forEach((el) => {
      const ent = byId[el.getAttribute("data-cv-q-live")];
      if (!ent) return;
      const html = new QueueNode(ent.node, ent.router).liveHtml();
      if (el.innerHTML !== html) el.innerHTML = html;  // skip churn (keeps CSS anims) when unchanged
    });
  }
  // Anchor a sticky-reservation bar's drain to an absolute clock (mirrors the classic
  // slot view) so periodic re-renders never restart/rescale it. Shared rAF ticker
  // (ensureStickyBarTicker) reads stickySlotAnims[group] every frame.
  static stickyAnim(group, stickyData, totalSec) {
    const rem = Math.max(0, Number(stickyData.remainingSec));
    const port = Number(stickyData.port);
    const totalMs = Math.max(1, Math.round(totalSec * 1000));
    const nowMs = Date.now();
    const elapsedPollMs = Math.max(0, totalMs - rem * 1000);
    const prev = stickySlotAnims[group];
    const drift = prev ? Math.abs((nowMs - prev.startMs) - elapsedPollMs) : Infinity;
    if (!prev || prev.port !== port || prev.durationMs !== totalMs || drift > 1500) {
      stickySlotAnims[group] = { port, startMs: nowMs - elapsedPollMs, durationMs: totalMs };
    }
    return stickySlotAnims[group];
  }
  // Human name for a runtime item in the queue. The raw route label is often just
  // "OpenClaw" for every host, which makes queue rows ambiguous — you can't tell
  // one host's OpenClaw from another's. Resolve the item → proxy → owner
  // and reuse the proxy-panel title (host name for the host OpenClaw agent, agent name
  // otherwise) so each row is distinguishable. Fall back to the bare label.
  static clientName(it) {
    // Port is the source of truth; show "alias :port" or ":port"
    if (it.port) return InputsBlock.portName(it.port);
    // Fallback: strip role suffix from label
    const label = String(it.label || it.route || "");
    return label.replace(/\s+(primary|fallback)$/i, "").trim() || `:${it.port || "?"}`;
  }
  summary() {
    const c = this.config;
    const slots = c.maxSlots ? t("cvSumSlots", { n: c.maxSlots }) : t("cvSumAutoSlots");
    return `${slots} · spill ${c.spillPct ?? 20}%`;
  }
  panelNeedsEdges() { return false; }
  panelBody() {
    const cfg = this.config;
    const num = (key, val, min, max, ph) =>
      `<input class="rw-cfg-in rw-cfg-num" type="number" min="${min}" max="${max}" data-cfg-q="${key}" value="${val === null || val === undefined ? "" : val}" placeholder="${ph || ""}">`;
    return `<div class="rw-cfg-hint">${t("cvHintQueueCfg")}</div>`
      + `<label class="rw-cfg-row"><span class="rw-cfg-tgt" title="${escapeHtml(t("cvTitleOverflowAt"))}">${escapeHtml(t("cvLabelOverflowAt"))}</span>${num("spillPct", cfg.spillPct ?? 20, 0, 100)}<span class="rw-cfg-unit">%</span></label>`
      + `<label class="rw-cfg-row"><span class="rw-cfg-tgt" title="${escapeHtml(t("cvTitleReserve"))}">${escapeHtml(t("cvLabelReserveForAgent"))}</span>${num("stickySlotSec", cfg.stickySlotSec ?? 20, 0, 120)}<span class="rw-cfg-unit">s</span></label>`;
  }
  // Live queue state: resolve the admit edge → guarded llama output, then count
  // running/queued requests on that upstream group (matches the backend's
  // route_group_key). Null for a cloud/unwired admit (no slot queue there).
  liveStats() {
  const router = this.router, cfg = this.config;
  const edges = this.outEdges;
  const admit = edges.find((e) => e.id === cfg.admitEdge) || edges[0];
  if (!admit || !String(admit.to).startsWith("out:")) return null;
  const out = (router.outputs || []).find((o) => o.id === String(admit.to).slice(4));
  if (!out || String(out.upstreamType || "") === "cloud") return null;
  const group = `${out.upstreamHost || "127.0.0.1"}:${out.upstreamPort || 8080}`;
  const overview = topologyRuntimeOverview();
  const running = overview.running.filter((it) => topologyItemGroup(it) === group).length;
  const qItems = overview.queued.filter((it) => topologyItemGroup(it) === group);
  const slotTotals = ui.latestSystemMonitor?.latest?.agentProxies?.slotTotals || {};
  const slots = Number(cfg.maxSlots) || Number(slotTotals[group] || 0) || 0;
  // Longest waiter's progress as a % of the FULL client wait-timeout (the gauge span).
  // queue.timeoutSec = the abort point = abortPct% of wait-timeout, so scale back up.
  const abortPct = Math.max(1, Number(cfg.abortPct ?? 85));
  let waitPct = 0;
  for (const it of qItems) {
    const ms = Number(it.queue?.queuedMs || 0);
    const abortSec = Number(it.queue?.timeoutSec || 0);
    const fullWait = abortSec > 0 ? abortSec / (abortPct / 100) : 0;
    if (fullWait > 0) waitPct = Math.max(waitPct, Math.min(100, (ms / 1000 / fullWait) * 100));
  }
  return { group, running, queued: qItems.length, slots, waitPct };
  }
  // Live region of the card: slot meter + now-processing + channel-reserve + waiting
  // queue. Split out from body() so QueueNode.syncLive() can re-render JUST this
  // region on every monitor tick — the surrounding card (routing destinations,
  // editable params, history pane) stays put, keeping cables/inputs/focus intact.
  // Without this the lists froze at load time (the canvas queue node showed "queue
  // empty / no active request" while a request streamed through it).
  liveHtml() {
  const cfg = this.config;
  const live = this.liveStats();
  const edges = this.outEdges;
  const spillEdge = edges.find((e) => e.id === cfg.spillEdge);
  const spillPct = Math.max(0, Math.min(100, Number(cfg.spillPct ?? 20)));
  const running = live?.running || 0, slots = live?.slots || 0;
  // ── slot meter ──
  let pips = "";
  if (slots > 0) {
    const cap = Math.min(slots, 8);
    for (let i = 0; i < cap; i++) pips += `<span class="cv-q-pip${i < running ? " on" : ""}"></span>`;
    if (slots > 8) pips += `<span class="cv-q-pip-more">+${slots - 8}</span>`;
  } else {
    pips = `<span class="cv-q-pip${running ? " on" : ""}"></span>`;
  }
  const slotText = slots > 0 ? `${running}/${slots}` : `${running}/<span class="cv-q-auto">${t("cvAuto")}</span>`;
  // ── live lists for this admit upstream ──
  const group = live?.group || "";
  const ov = topologyRuntimeOverview();
  const inG = (it) => group && topologyItemGroup(it) === group;
  // Show both main-admitted and cloud-overflow running items so the user can see
  // where each request actually went. Cloud items are filtered by same proxy port.
  const admitPort = (topology?.proxies || []).find((p) => group === _proxyUpstreamStr(p))?.port;
  const overflowItems = admitPort
    ? ov.running.filter((it) => {
        const itPort = Number(it.port || 0);
        return itPort === Number(admitPort) && (it.upstreamType === "cloud" || it.queue?.cloudFallback);
      })
    : [];
  const runningItems = ov.running.filter(inG).slice(0, 4);
  const allRunning = [
    ...runningItems.map((it) => ({ it, isCloud: false })),
    ...overflowItems.filter((it) => !runningItems.includes(it)).map((it) => ({ it, isCloud: true })),
  ];
  const waitingItems = ov.queued.filter(inG).sort((a, b) => (a.queue?.position ?? 99) - (b.queue?.position ?? 99));
  // now processing — animated chevrons + elapsed seconds + route indicator
  const chevrons = `<span class="cv-q-chevrons" aria-hidden="true"><i></i><i></i><i></i></span>`;
  const nowRows = allRunning.length
    ? allRunning.map(({ it, isCloud }) => {
        const el = topologyFormatDuration(it.elapsedMs || topologyDurationMs(it.startedAt));
        const routeTag = isCloud
          ? `<span class="cv-q-route cloud" title="${escapeHtml(it.model || t("cvTitleCloudOverflow"))}">↗ cloud</span>`
          : `<span class="cv-q-route main" title="${escapeHtml(t("cvTitleMainUpstream"))}">→ main</span>`;
        return `<div class="cv-q-now-row running">${chevrons}<span class="cv-q-cli">${escapeHtml(QueueNode.clientName(it))}</span>${routeTag}<span class="cv-q-elapsed">${escapeHtml(el)}</span></div>`;
      }).join("")
    : `<div class="cv-q-empty">— ${t("cvQNoActive")} —</div>`;
  // channel reservation (sticky) bar — driven by the shared rAF ticker (ensureStickyBarTicker)
  const stickyData = group ? (ui.latestSystemMonitor?.latest?.agentProxies?.stickySlots || {})[group] : null;
  let reserveRow = "";
  if (stickyData && Number(stickyData.remainingSec) > 0) {
    const totalSec = Math.max(1, Number(cfg.stickySlotSec ?? 20));
    const anim = QueueNode.stickyAnim(group, stickyData, totalSec);
    const remMs = Math.max(0, anim.durationMs - (Date.now() - anim.startMs));
    const startPct = anim.durationMs > 0 ? (remMs / anim.durationMs) * 100 : 0;
    reserveRow = `<div class="cv-q-reserve">`
      + `<span class="cv-q-rlabel">⏱ ${escapeHtml(t("cvQChannelReserved"))} · <span data-sticky-secs>${Math.ceil(remMs / 1000)}s</span></span>`
      + `<span class="topology-sticky-bar" data-sticky-group="${escapeHtml(group)}" aria-hidden="true"><i style="clip-path:inset(0 ${(100 - startPct).toFixed(3)}% 0 0)"></i></span>`
    + `</div>`;
  }
  // waiting queue with expiring bars
  // spillRel = spill marker position on the bar (bar spans full clientTimeoutSeconds)
  const spillRel = spillPct; // spillPct% of full timeout = spillPct% of bar width
  const waitRows = waitingItems.slice(0, 5).map((it) => {
    const rt = topologyQueueRuntime(it);
    const totalMs = Math.max(1, rt.timeoutSec * 1000);
    const fill = Math.min(100, (rt.queuedMs / totalMs) * 100);
    const leftLabel = topologyFormatDuration(rt.leftMs);
    // overflow countdown: how long until this client spills (from backend cloudAt threshold)
    const overflowInMs = rt.cloudAt > 0 ? Math.max(0, rt.cloudAt * 1000 - rt.queuedMs) : null;
    const switchLine = spillEdge && overflowInMs !== null
      ? `<div class="cv-q-wait-sub${overflowInMs === 0 ? " now" : ""}">`
          + (overflowInMs > 0 ? `↗ ${escapeHtml(t("cvQSwitchIn", { t: topologyFormatDuration(overflowInMs) }))}` : `↗ ${escapeHtml(t("cvQSwitchingNow"))}`)
        + `</div>`
      : `<div class="cv-q-wait-sub muted">—</div>`;
    return `<div class="cv-q-wait-row">`
      + `<div class="cv-q-wait-top">`
        + `<span class="cv-q-cli">${escapeHtml(QueueNode.clientName(it))}</span>`
        + `<span class="cv-q-left">${escapeHtml(leftLabel)}</span>`
      + `</div>`
      + `<span class="cv-q-bar">`
        + `<span class="cv-q-bar-fill" style="width:${fill}%"></span>`
        + (spillEdge && spillRel > 0 && spillRel < 100 ? `<span class="cv-q-bar-mk spill" style="left:${spillRel}%" title="${escapeHtml(t("cvTitleSpillsAt", { n: spillPct }))}"></span>` : "")
      + `</span>`
      + switchLine
    + `</div>`;
  }).join("");
  const moreWaiting = waitingItems.length > 5 ? `<div class="cv-q-empty">${escapeHtml(t("cvQMoreWaiting", { n: waitingItems.length - 5 }))}</div>` : "";
  const waitBlock = waitingItems.length
    ? `<div class="cv-q-sec-h">${escapeHtml(t("cvQWaitingHead", { n: waitingItems.length }))}</div>${waitRows}${moreWaiting}`
    : `<div class="cv-q-empty muted">${t("cvQEmpty")}</div>`;
  return `<div class="cv-q-meter${slots > 0 && running >= slots ? " full" : ""}">`
      + `<span class="cv-q-pips">${pips}</span><span class="cv-q-slotnum">${slotText}</span>`
      + (waitingItems.length ? `<span class="cv-q-qd waiting">⏳ ${waitingItems.length}</span>` : `<span class="cv-q-qd idle">${t("cvQIdle")}</span>`)
    + `</div>`
    + `<div class="cv-q-now">${nowRows}</div>`
    + reserveRow
    + `<div class="cv-q-waitwrap">${waitBlock}</div>`;
  }
  body() {
  const n = this.rec, router = this.router, cfg = this.config;
  const edges = this.outEdges;
  const spillEdge = edges.find((e) => e.id === cfg.spillEdge);
  // admit falls back to the first non-spill edge (matches the engine + heals old graphs).
  const admitEdge = edges.find((e) => e.id === cfg.admitEdge) || edges.find((e) => e.id !== cfg.spillEdge);
  const admitLabel = this.targetLabel(admitEdge), spillLabel = this.targetLabel(spillEdge);
  const spillPct = Math.max(0, Math.min(100, Number(cfg.spillPct ?? 20)));
  // main (admit) / overflow (spill) destination rows, each with its own out-port —
  // role = internal data role (admit/spill); the visible label is main / overflow.
  // Inherited default when this queue node says nothing: the global policy.
  // Showing the inherited number (rather than a blank) is the difference
  // between "not set" and "set to nothing", which for a retry window is the
  // difference between 60 seconds and never retrying.
  const _policyLoadWait = () =>
    Number((topology?.proxyPolicy || {}).loadingModelWaitSec ?? 60);
  // ── inline, editable parameters (also in the ⚙ panel) ──
  const qnum = (key, val, min, max, ph) =>
    `<input class="cv-q-cfg-in" type="number" min="${min}" max="${max}" data-cv-q="${key}" value="${val === null || val === undefined ? "" : val}" placeholder="${ph || ""}" title="${escapeHtml(ph || key)}">`;
  const paramsGrid = `<div class="cv-q-cfg">`
    + `<label class="cv-q-cfg-row"><span>${escapeHtml(t("cvLabelOverflowAt"))} ${helpTip("cvTipOverflowAt")}</span>${qnum("spillPct", cfg.spillPct ?? 20, 0, 100, "% of wait")}<span class="cv-q-u">%</span></label>`
    + `<label class="cv-q-cfg-row"><span>${escapeHtml(t("cvLabelReserve"))} ${helpTip("cvTipReserve")}</span>${qnum("stickySlotSec", cfg.stickySlotSec ?? 20, 0, 120, "reserve for agent")}<span class="cv-q-u">s</span></label>`
    + `<label class="cv-q-cfg-row"><span>${escapeHtml(t("cvLabelLoadWait"))} ${helpTip("cvTipLoadWait")}</span>${qnum("loadingModelWaitSec", cfg.loadingModelWaitSec ?? _policyLoadWait(), 0, 900, "sec")}<span class="cv-q-cfg-unit">s</span></label>`
    + `</div>`;
  // History pane — auto-refresh if stale while open
  const histOpen = !!_cvQueueHistOpen[n.id];
  const histCache = _cvQueueHistData[n.id];
  if (histOpen && histCache && Date.now() - histCache.ts > 15000) {
    // stale — kick a silent refresh; next render will pick up new data
    setTimeout(() => History.fetch(_cvQueueHistData, n.id), 0);
  }
  const histSection = `<div class="cv-q-hist${histOpen ? " open" : ""}">
    <button class="cv-act cv-q-hist-toggle" type="button" data-cv-q-hist-toggle="${escapeHtml(n.id)}">
      🕐 history ${histOpen ? "▴" : "▾"}
    </button>
    ${histOpen ? `<div class="cv-q-hist-body">${History.queueHtml(n.id)}</div>` : ""}
  </div>`;

  // Dead-target warnings: the cable exists, but its output vanished (block
  // deleted — edge preserved for auto-restore) or the block's model is no
  // longer listed by the provider (requests will 400 upstream).
  const edgeTargetIssue = (edge) => {
    const to = String(edge?.to || "");
    if (!to.startsWith("out:")) return "";
    const outId = to.slice(4);
    const out = (router.outputs || []).find((o) => o.id === outId);
    if (!out) return t("cvQTargetMissing");
    if (outId.startsWith("cb:")) {
      const blk = (topology?.cloudProviders || []).find((b) => b.id === String(out.providerId || outId.slice(3)));
      if (blk?.unlisted) return t("cloudModelUnlisted");
    }
    return "";
  };
  const warnRow = (name, edge) => {
    const issue = edge ? edgeTargetIssue(edge) : "";
    return issue ? `<div class="cv-q-warn">⚠ ${name}: ${escapeHtml(issue)}</div>` : "";
  };
  return `<div class="cv-q-body">`
    // routing first: main / overflow destinations (point 4 — above the live lists)
    + this.destRow({ cls: "admit", name: "main", label: admitLabel, wired: !!admitEdge, portAttr: 'data-cv-qrole="admit"', hint: t("cvDragToMain") })
    + this.destRow({ cls: "spill", name: "overflow", label: spillLabel, wired: !!spillEdge, portAttr: 'data-cv-qrole="spill"', hint: t("cvDragToOverflow") })
    + warnRow("main", admitEdge)
    + warnRow("overflow", spillEdge)
    + paramsGrid
    // live state below — wrapped in a stable container so QueueNode.syncLive() can
    // re-patch just this region every monitor tick (the rest of the card stays put).
    + `<div class="cv-q-live" data-cv-q-live="${escapeHtml(n.id)}">${this.liveHtml()}</div>`
    + histSection
    + `</div>`;
  }
}

// Two exits: main (the normal path) and backup. The proxy replays the request down
// backup only when the MAIN upstream failed (connect error / HTTP >= 400) before a
// single response byte reached the client — redundancy, not load management.
// Reuses the queue card's dest-row classes: admit = main styling, spill = backup.
//
// The rows are live: the proxy remembers each exit's verdict (alive, or down with
// the status that said so, for five minutes) and says which exit the NEXT request
// takes — both arrive in its state file (outputHealth / onErrorNext) and are drawn
// as they are. ▶ marks the next exit; the dot after the target is the exit's health.
// The board never re-derives the rule, so it can never disagree with the proxy.
export class OnErrorNode extends RuleNode {
  get cls() { return "cv-rule-queue cv-rule-onerr"; }
  get ownPorts() { return true; }
  cfgControl() { return helpTip("cvTipOnErrorNode"); }
  body() {
    return `<span class="cv-sub">${escapeHtml(t("cvOnErrSub"))}</span>`
      + `<div class="cv-oe-live" data-cv-oe-live="${escapeHtml(this.id)}">${this.liveHtml()}</div>`;
  }
  liveHtml() {
    const cfg = this.config;
    const edges = this.outEdges;
    const rescueEdge = edges.find((e) => e.id === cfg.rescueEdge);
    const mainEdge = edges.find((e) => e.id === cfg.mainEdge) || edges.find((e) => e.id !== cfg.rescueEdge);
    const live = OnErrorNode.live(this.id, mainEdge, rescueEdge);
    live.mainVia = this.viaName(live.nx, "main");
    live.backupVia = this.viaName(live.nx, "backup");
    OnErrorNode.ensureTicker();
    return this.destRow({ cls: "admit", name: "main", wired: !!mainEdge,
                          label: OnErrorNode.exitLabel(this.targetLabel(mainEdge), live.mainVia),
                          portAttr: 'data-cv-qrole="main"', hint: t("cvDragToMain"),
                          lead: OnErrorNode.nextHtml(live.next === "main"),
                          extra: OnErrorNode.stateHtml(live.main) + OnErrorNode.countdownHtml(live.main) })
      + this.destRow({ cls: "spill", name: "backup", wired: !!rescueEdge,
                       label: OnErrorNode.exitLabel(this.targetLabel(rescueEdge), live.backupVia),
                       portAttr: 'data-cv-qrole="rescue"', hint: t("cvDragToRescue"),
                       lead: OnErrorNode.nextHtml(live.next === "backup"),
                       extra: OnErrorNode.stateHtml(live.backup) + OnErrorNode.countdownHtml(live.backup) });
  }
  // When this exit's verdict expires — checkedAt plus the TTL, which the
  // snapshot carries as age + time-to-retry — the idle probe asks it again
  // (within its 30 s pass) and the next request may take it again. A real
  // request refreshes the verdict on its own, so an exit in use counts down
  // from the full TTL after every answer.
  static deadlineOf(row) {
    if (!row || !(Number(row.checkedAt) > 0)) return 0;
    return Number(row.checkedAt) + Number(row.ageSec || 0) + Number(row.retryInSec || 0);
  }
  static countdownText(deadline) {
    if (!(deadline > 0)) return "";
    const left = Math.round(deadline - Date.now() / 1000);
    if (left <= 0) return "0:00";
    return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  }
  static countdownHtml(row) {
    const deadline = OnErrorNode.deadlineOf(row);
    if (!deadline) return "";
    return `<span class="cv-oe-cd" data-cv-oe-deadline="${deadline}" title="${escapeHtml(t("cvOeCountdownTip"))}">${OnErrorNode.countdownText(deadline)}</span>`;
  }
  // One ticker for every countdown on the canvas; the text is patched in
  // place, the rows are not rebuilt (that is syncLive's job, on the monitor tick).
  static ensureTicker() {
    if (OnErrorNode._ticker) return;
    OnErrorNode._ticker = setInterval(() => OnErrorNode.tick(), 1000);
  }
  static tick() {
    document.querySelectorAll("[data-cv-oe-deadline]").forEach((el) => {
      const text = OnErrorNode.countdownText(Number(el.dataset.cvOeDeadline));
      if (el.textContent !== text) el.textContent = text;
    });
  }
  static outputIdOf(edge) {
    const to = String(edge?.to || "");
    return to.startsWith("out:") ? to.slice(4) : "";
  }
  // What the proxy last said: verdicts per output id and the next exit per node.
  // Without a report the next exit is main — that IS the proxy's rule when it
  // knows nothing, so the default is the truth, not a guess.
  //
  // An exit may lead into ANOTHER node (on production the main exit goes into a
  // queue), and then the model is at the end of that chain. Which output that
  // is, the proxy resolves — it is the same walk a request makes — and the
  // board reads the answer from the report instead of walking the graph a
  // second time and risking a different one. The edge's own target is the
  // fallback for a report that has not arrived yet.
  static live(nid, mainEdge, rescueEdge) {
    const ap = ui.latestSystemMonitor?.latest?.agentProxies || {};
    const health = ap.outputHealth || {};
    const nx = (ap.onErrorNext || {})[nid] || null;
    const idOf = (side, edge) => (nx && nx[side]) || OnErrorNode.outputIdOf(edge);
    return {
      next: nx?.next === "backup" ? "backup" : "main",
      main: health[idOf("main", mainEdge)] || null,
      backup: health[idOf("backup", rescueEdge)] || null,
      nx,
    };
  }
  // The model at the end of a chained exit, when the chain has one and the
  // proxy could name it. Empty for a direct exit (the row already names it) and
  // for a chain nobody can predict — a guess there would be worse than silence.
  //
  // The WORDING is the board's own: an output is named here exactly as it is
  // named where a cable ends on it, so one model does not read as two things on
  // one screen. The proxy's name is the fallback for an output this board does
  // not have in its router record.
  viaName(nx, side) {
    const chain = (nx && nx[`${side}Chain`]) || [];
    const id = (nx && nx[side]) || "";
    if (!chain.length || !id) return "";
    const out = ((this.router || {}).outputs || []).find((o) => o && o.id === id);
    return out ? topologyRouterOutputLabel(out) : String((nx && nx[`${side}Name`]) || id);
  }
  static exitLabel(label, via) {
    return via ? `${label} → ${via}` : label;
  }
  static ago(sec) {
    const n = Math.max(0, Math.round(Number(sec) || 0));
    if (n < 60) return `${n}s`;
    if (n < 3600) return `${Math.round(n / 60)}m`;
    return `${Math.round(n / 3600)}h`;
  }
  static stateHtml(row) {
    let cls = "unknown";
    let tip = t("cvOeUnknown");
    if (row && (row.state === "ok" || row.state === "error")) {
      const reason = row.state === "ok" ? "ok" : [row.kind, row.message].filter(Boolean).join(": ");
      const ago = OnErrorNode.ago(row.ageSec);
      if (!row.fresh) {
        cls = "stale";
        tip = t("cvOeStale", { reason, ago });
      } else if (row.state === "ok") {
        cls = "ok";
        tip = t("cvOeAlive", { ago });
      } else {
        cls = "error";
        tip = t("cvOeDead", { reason, ago, retry: OnErrorNode.ago(row.retryInSec) });
      }
    }
    return `<span class="cv-oe-state ${cls}" title="${escapeHtml(tip)}"></span>`;
  }
  static nextHtml(isNext) {
    return isNext
      ? `<span class="cv-oe-next" title="${escapeHtml(t("cvOeNextTip"))}">▶</span>`
      : `<span class="cv-oe-next off"></span>`;
  }
  // Re-patch every backup node's rows on the monitor tick — same contract as
  // QueueNode.syncLive: only the inner live region, so cables and ports stay put.
  static syncLive() {
    if (!topology) return;
    const liveEls = document.querySelectorAll("[data-cv-oe-live]");
    if (!liveEls.length) return;
    const byId = {};
    (topology.routers || []).forEach((r) => {
      ((r.graph && r.graph.nodes) || []).forEach((nd) => {
        if (nd.type === "onError") byId[nd.id] = { router: r, node: nd };
      });
    });
    liveEls.forEach((el) => {
      const ent = byId[el.getAttribute("data-cv-oe-live")];
      if (!ent) return;
      const html = new OnErrorNode(ent.node, ent.router).liveHtml();
      if (el.innerHTML !== html) el.innerHTML = html;
    });
  }
}

// "By request-type": two dest rows, each with its own out-port. Ports are tagged
// with data-cv-sched-port so they reuse the schedule node's edge plumbing
// (connect/draw/rewire/persist all key off schedPortId). The backend _eval_rule_node
// "requestType" branch reads the same tags: embeddings → "embed", else "__default__".
// Role drives the cv-q-* colour classes: embeddings reuses the "spill" (diverted)
// accent, default reuses the "admit" (main) accent.
export class RequestTypeNode extends RuleNode {
  get cls() { return "cv-rule-reqtype"; }
  get ownPorts() { return true; }
  cfgControl() { return helpTip("cvTipRequestTypeNode"); }
  body() {
    const edges = this.outEdges;
    const embedEdge = edges.find((e) => e.schedPortId === "embed");
    // default = the explicitly-tagged port; fall back to any non-embed edge (heals graphs).
    const defaultEdge = edges.find((e) => e.schedPortId === "__default__")
      || edges.find((e) => e.schedPortId !== "embed");
    // The clients-panel EMBEDDINGS selector (rules.embeddingsOutput) is checked
    // BEFORE the graph — when it is set, this node's embed port never fires.
    const globalEmbed = (this.router.rules || {}).embeddingsOutput;
    const globalNote = globalEmbed
      ? `<div class="cv-q-note">${escapeHtml(t("cvReqTypeGlobalNote"))}</div>` : "";
    return `<div class="cv-q-body">` + globalNote
      + this.destRow({ cls: "spill", name: "embeddings", label: this.targetLabel(embedEdge), wired: !!embedEdge, portAttr: 'data-cv-sched-port="embed"', hint: t("cvDragEmbedTarget") })
      + this.destRow({ cls: "admit", name: "default", label: this.targetLabel(defaultEdge), wired: !!defaultEdge, portAttr: 'data-cv-sched-port="__default__"', hint: t("cvDragDefaultTarget") })
      + `</div>`;
  }
}

// "By size": small requests (max_tokens ≤ threshold — heartbeat-scale asks) leave
// the "small" port; everything bigger or unspecified takes "__default__". Same
// schedPortId edge plumbing as requestType/schedule; the threshold input reuses the
// generic cv-q-cfg-in config handler.
export class RequestSizeNode extends RuleNode {
  get cls() { return "cv-rule-reqtype"; }
  get ownPorts() { return true; }
  cfgControl() { return helpTip("cvTipRequestSizeNode"); }
  body() {
    const cfg = this.config;
    const thr = Math.max(1, Math.min(100000, Number(cfg.maxTokensAt ?? 300)));
    const edges = this.outEdges;
    const smallEdge = edges.find((e) => e.schedPortId === "small");
    const defaultEdge = edges.find((e) => e.schedPortId === "__default__")
      || edges.find((e) => e.schedPortId !== "small");
    const thrRow = `<div class="cv-q-cfg">`
      + `<label class="cv-q-cfg-row"><span>${escapeHtml(t("cvLabelSmallLe"))} ${helpTip("cvTipRequestSizeSmall")}</span>`
      + `<input class="cv-q-cfg-in" type="number" min="1" max="100000" data-cv-q="maxTokensAt" value="${thr}" title="${escapeHtml(t("cvTitleMaxTokensThr"))}"><span class="cv-q-u">tok</span></label>`
      + `</div>`;
    return `<div class="cv-q-body">`
      + thrRow
      + this.destRow({ cls: "spill", name: "small", label: this.targetLabel(smallEdge), wired: !!smallEdge, portAttr: 'data-cv-sched-port="small"', hint: t("cvDragSmallTarget") })
      + this.destRow({ cls: "admit", name: "default", label: this.targetLabel(defaultEdge), wired: !!defaultEdge, portAttr: 'data-cv-sched-port="__default__"', hint: t("cvDragDefaultTarget") })
      + `</div>`;
  }
}

RuleNode.KINDS = { schedule: ScheduleNode, weighted: WeightedNode, roundRobin: RoundRobinNode, failover: FailoverNode,
  queue: QueueNode, requestType: RequestTypeNode, requestSize: RequestSizeNode, onError: OnErrorNode };

// Function faces kept for the callers and the snapshot; the classes above do the work.
export function queueNodeLiveStats(router, node) { return new QueueNode(node, router).liveStats(); }
export function queueNodeLiveHtml(router, n) { return new QueueNode(n, router).liveHtml(); }
export function queueNodeBodyHtml(router, n) { return new QueueNode(n, router).body(); }
export function onErrorNodeBodyHtml(router, n) { return new OnErrorNode(n, router).body(); }
export function requestTypeNodeBodyHtml(router, n) { return new RequestTypeNode(n, router).body(); }
export function requestSizeNodeBodyHtml(router, n) { return new RequestSizeNode(n, router).body(); }
export function renderSchedNodeHtml(n, router) { return new ScheduleNode(n, router).html(); }
export function _ruleNodeSummary(n) { return RuleNode.from(n).summary(); }



if (typeof window !== "undefined" && !window._cvSchedNowTimer) {
  window._cvSchedNowTimer = setInterval(() => ScheduleNode.tickNow(), 30_000);
}

// ── CLIENTS block: one canvas node listing every client wired into the router ──
// One row per AGENT = (host, agent-name), holding BOTH its primary and fallback
// ports. The agent name comes from the route label minus its "primary"/"fallback"
// suffix (kept correct by the backend reconcile); clientId disambiguates the same
// agent name living on different hosts.
export class InputsBlock {
  // proxyId → {agentId, hostId} from topology.assignments (cached per topology snapshot).
  static agentMapCache = { topo: null, map: null };
  static proxyToAgent() {
    const cache = InputsBlock.agentMapCache;
    if (cache.topo === topology && cache.map) return cache.map;
    const map = new Map();
    for (const [hostId, entry] of Object.entries(topology?.assignments || {})) {
      for (const ag of (entry.assignments || [])) {
        for (const r of (ag.routes || [])) {
          if (r.proxyId) map.set(String(r.proxyId), { agentId: String(ag.agentId || ""), hostId });
        }
      }
    }
    InputsBlock.agentMapCache = { topo: topology, map };
    return map;
  }
  static agentGroup(p) { return String(p.label || "").replace(/\s+(primary|fallback)$/i, "").trim(); }
  // Normalize port to primary of its pair (odd=primary, even=primary's fallback → port-1).
  static primaryPort(p) {
    const port = Number(p.port || 0);
    return port > 0 ? (port % 2 === 0 ? port - 1 : port) : 0;
  }
  // Group primary+fallback pair by the primary (odd) port — label-independent.
  static clientKey(p) {
    const host = String(p.clientId || "");
    const primary = InputsBlock.primaryPort(p);
    return host || primary ? `${host}::${primary || p.id}` : String(p.id);
  }
  static clientName(p) {
    const info = InputsBlock.proxyToAgent().get(String(p.id));
    if (info?.agentId) {
      const short = info.agentId.replace(/^agent-/, "");
      // Qualify with host when the same agent name exists on >1 host.
      const dupHosts = [...InputsBlock.proxyToAgent().values()]
        .filter((i) => i.agentId === info.agentId && i.hostId !== info.hostId);
      return dupHosts.length ? `${short} · ${info.hostId}` : short;
    }
    // Fallback: label (stripped), or host:port when label equals host (ambiguous).
    const label = InputsBlock.agentGroup(p);
    const host = String(p.clientId || "");
    if (label && label !== host) return label;
    const primary = InputsBlock.primaryPort(p);
    return host ? (primary ? `${host}:${primary}` : host) : String(p.id);
  }
  static roleOf(p) { return p.role || (String(p.label || "").match(/(primary|fallback)$/i)?.[1]?.toLowerCase()) || ""; }
  // Port-based display name for a proxy port.
  // opts.short → use last-2 port digits as tag (:01); default → full port (:8101)
  // opts.nameOnly → return just the alias without port tag
  // Returns "host:01" (named+short), "host :8101" (named), ":8101" (unnamed)
  static portName(port, opts = {}) {
    const p = Number(port);
    if (!p) return opts.short ? ":??" : ":????"  ;
    const proxy = (topology?.proxies || []).find((q) => Number(q.port) === p);
    const owner = proxy ? topologyProxyOwner(proxy.id) : null;
    // title = agent name or host name for openclaw agents
    const name = owner?.title && owner.title !== String(proxy?.id) ? owner.title : "";
    const portTag = opts.short ? `:${String(p).slice(-2)}` : ` :${p}`;
    if (name) return opts.nameOnly ? name : `${name}${portTag}`;
    return opts.short ? `:${String(p).slice(-2)}` : `:${p}`;
  }

  constructor(router) {
    this.router = router;
    const inputs = router.inputs || [];
    // The main board decides who is listed. The kanban used to group PORTS, and
    // rows appeared here that the main board never had, named by a port label.
    // Unclaimed inputs do not vanish — they are named separately.
    this.proxies = (topology?.proxies || []).filter((p) => inputs.includes(p.id) && !_cvProxyIsTombstoned(p));
    this.board = canvasBoardClients(this.proxies);
    const graph = router.graph || { nodes: [], edges: [] };
    // Single source of truth = the canvas. Only inputs WIRED into the graph (≥1 outgoing
    // edge) count as routed; everything unwired falls through to the default output.
    this.wiredProxyIds = new Set((graph.edges || []).map((e) => String(e.from)).filter((r) => r.startsWith("in:")).map((r) => r.slice(3)));
    this.graphInputs = graph.inputs || {};
    this.muted = topologyMutedProxyIds();
  }
  // A port row of a client. Port dots are NOT inline — syncPortDots() creates them as
  // direct children of the block so they straddle the RIGHT border correctly even
  // when the body is scrolled.
  portRow(role, p, wired) {
    return p ? `
    <div class="cv-in-row ${role}${wired ? "" : " unwired"}" data-cv-in-row="in:${escapeHtml(p.id)}">
      <span class="cv-in-role">${role === "primary" ? "P" : "F"}</span>
      <span class="cv-in-port-num">:${escapeHtml(String(p.port))}</span>
      ${role === "fallback" && !wired ? `<span class="cv-in-follow">↳ ${escapeHtml(t("cvInFollows"))}</span>` : ""}
      <button class="cv-in-edit" type="button" data-cv-port-edit="${escapeHtml(p.id)}" title="${escapeHtml(t("cvPortEditTitle"))}">✎</button>
    </div>` : "";
  }
  // The wait budget is a REFERENCE here. It is edited on the client card of the
  // main board, where everything else about the route lives; a field here was a
  // second home for one fact, and the card showed a different number meanwhile.
  waitRow(p) {
    if (!p) return "";
    const override = Number(this.graphInputs[p.id]?.clientTimeoutSeconds || 0);
    const shown = override || proxyEffectiveWaitTimeout(p);
    if (!shown) return "";
    return `<span class="cv-in-wait${override ? " own" : ""}" title="${escapeHtml(t("cvTitleWaitBudget"))}"`
      + ` data-t="kanban-input-wait" data-t-id="${escapeHtml(p.id)}">`
      + `${escapeHtml(t("routeWaitLabel", { sec: String(shown) }))}</span>`;
  }
  clientRow(c) {
    const wired = this.wiredProxyIds;
    const prim = c.proxies.find((p) => InputsBlock.roleOf(p) === "primary") || c.proxies[0];
    const fb = c.proxies.find((p) => InputsBlock.roleOf(p) === "fallback" && p !== prim && !this.muted.has(p.id));
    const anyWired = c.proxies.some((p) => wired.has(p.id));
    const isStale = c.proxies.some((p) => _cvProxyIsStale(p));
    const cls = `${anyWired ? "routed" : "unrouted"}${isStale ? " stale" : ""}`;
    return `<div class="cv-inputs-client ${cls}">`
      + `<span class="cv-in-name">${escapeHtml(InputsBlock.clientName(c.proxies[0]))}</span>`
      // Two lines, not three: name, P port and wait budget on the first, the
      // fallback on the second (it has its own port dot, which needs its own height).
      + this.portRow("primary", prim, wired.has(prim.id))
      + this.waitRow(prim)
      + this.portRow("fallback", fb, fb && wired.has(fb.id))
      + `</div>`;
  }
  // The grouped rows — one block for all clients — plus the ports nobody claims.
  bodyHtml() {
    const byClient = new Map(this.board.rows.map((r) => [r.key, r]));
    const unclaimed = this.board.unclaimed;
    return [...byClient.values()].map((c) => this.clientRow(c)).join("")
      + (unclaimed.length ? `<div class="cv-inputs-client unclaimed" data-t="kanban-unclaimed">`
        + `<span class="cv-in-name">${escapeHtml(t("cvInputsUnclaimed", { count: String(unclaimed.length) }))}</span>`
        + unclaimed.map((p) => `<div class="cv-in-row"><span class="cv-in-port-num">:${escapeHtml(String(p.port))}</span></div>`).join("")
        + `</div>` : "");
  }
  // Embeddings slot — one global target for EVERY client's /v1/embeddings (Variant 1).
  // Pick a local embed-model server; empty ⇒ embeddings can't be served (warned).
  embedSlotHtml() {
    const embedOutId = this.router.rules?.embeddingsOutput || "";
    const localLlamaOuts = (this.router.outputs || []).filter((o) => String(o.upstreamType || "llama") !== "cloud");
    const embedOut = localLlamaOuts.find((o) => o.id === embedOutId);
    const embedOpts = localLlamaOuts.map((o) =>
      `<option value="${escapeHtml(o.id)}"${o.id === embedOutId ? " selected" : ""}>${escapeHtml(topologyRouterOutputLabel(o))}</option>`).join("");
    return `<div class="cv-embed-slot ${embedOut ? "assigned" : "unassigned"}">`
      + `<div class="cv-embed-head">🧬 embeddings ${helpTip("cvTipEmbeddings")}</div>`
      + `<select class="cv-embed-select" data-cv-embed-out aria-label="${escapeHtml(t("a11yEmbeddingsTarget"))}"><option value="">— ${escapeHtml(t("cvNotAssigned"))} —</option>${embedOpts}</select>`
      + `<div class="cv-embed-note">${embedOut ? escapeHtml(t("cvEmbedAllTo", { name: topologyRouterOutputLabel(embedOut) })) : t("cvEmbedNotSet")}</div>`
      + `</div>`;
  }
  // Ports are no longer created here: the kanban is about routing, not about the
  // existence of inputs. A port is created where its owner lives — on the client
  // card of the main board; otherwise a port appears that no card shows.
  // Reconcile deletes routes. It had no button at all — it ran only from curl,
  // and the first time it ran after service bridges existed it deleted three
  // live ones. Here it asks first, and shows exactly what it would remove.
  toolsHtml() {
    return `<div class="cv-app-port-row">`
      + `<button class="cv-app-port-btn reconcile" type="button" data-cv-reconcile title="${escapeHtml(t("cvReconcileHint"))}">⟳ ${escapeHtml(t("cvReconcileBtn"))}</button>`
      + `</div>`;
  }
  // Dead agents — assignments whose agent the host no longer reports. Their
  // delete (which frees the ports they still hold) lived in the retired
  // Proxy-ports registry modal; this strip is its new home. Renders only when
  // there is something to clean up.
  orphansHtml() {
    const orphanAgents = topology?.orphanedAgents || [];
    return !orphanAgents.length ? "" : `<div class="cv-orphan-agents">`
      + `<div class="cv-orphan-head" title="${escapeHtml(t("deadAgentsHint"))}">☠ ${escapeHtml(t("cvOrphanAgentsHead"))}</div>`
      + orphanAgents.map((o) => {
          const ports = (o.ports && o.ports.length) ? o.ports.map((p) => ":" + p).join(" ") : "—";
          return `<div class="cv-orphan-row" title="${escapeHtml(t("deadAgentTitle"))}">`
            + `<span class="cv-orphan-name">${escapeHtml(o.agentId)} · ${escapeHtml(o.clientName || o.clientId)}</span>`
            + `<span class="cv-orphan-ports">${escapeHtml(ports)}</span>`
            + `<button class="cv-orphan-del" type="button" data-cv-orphan-agent="${escapeHtml(o.agentId)}" data-cv-orphan-client="${escapeHtml(o.clientId)}" title="${escapeHtml(t("deleteDeadAgent"))}">✕</button>`
            + `</div>`;
        }).join("")
      + `</div>`;
  }
  descriptor() {
    const body = this.bodyHtml();
    return {
      id: "inputs:block", type: "inputs", cls: "cv-inputs-block", fixed: { x: 20, y: 20 },
      // The empty message was a single-quoted string inside the template, so a
      // router without ports printed the literal "${escapeHtml(...)}" instead of
      // the sentence — absence rendered as garbage. A nested template renders it.
      html: `<div class="cv-inputs-head">${escapeHtml(t("cvLabelClients"))} ${helpTip("cvTipClients")}</div><div class="cv-inputs-body">${body || `<span class="router-cfg-muted" style="font-size:11px;padding:6px 0;display:block">${escapeHtml(t("cvNoProxyPorts"))}</span>`}</div>${this.orphansHtml()}${this.embedSlotHtml()}${this.toolsHtml()}`,
    };
  }
  // Sync port dots on the block (mirror of ServersBlock.syncPortDots). Dots are
  // direct children of the block (position:absolute, right:-9px) so they straddle
  // the RIGHT border just like .cv-port.out on regular nodes. Y is computed from
  // getBoundingClientRect() so it tracks correctly when scrolled.
  static syncPortDots() {
  const world = document.querySelector("[data-cv-world]");
  if (!world) return;
  const block = world.querySelector(".cv-inputs-block");
  if (!block) return;
  const blockRect = block.getBoundingClientRect();
  const scale = _cvView.scale || 1;
  const seen = new Set();
  block.querySelectorAll("[data-cv-in-row]").forEach((row) => {
    const ref = row.dataset.cvInRow;
    if (!ref) return;
    const rowRect = row.getBoundingClientRect();
    if (rowRect.height < 1) return;
    seen.add(ref);
    let dot = block.querySelector(`:scope > .cv-port.out[data-cv-ref="${CSS.escape(ref)}"]`);
    if (!dot) {
      dot = document.createElement("span");
      dot.className = "cv-port out";
      dot.dataset.cvRef = ref;
      dot.title = t("cvDragPort");
      block.appendChild(dot);
    }
    const yBlock = (rowRect.top - blockRect.top + rowRect.height / 2) / scale;
    dot.style.top = (yBlock - 8) + "px";
    dot.style.marginTop = "0";
  });
  block.querySelectorAll(":scope > .cv-port.out[data-cv-ref]").forEach((dot) => {
    if (!seen.has(dot.dataset.cvRef)) dot.remove();
  });
  }
}

// ── SERVERS block: stationary canvas node (draggable, no delete button) ────────
// Each output row inside it carries data-cv-out-port="out:<id>" as its input port.
export class ServersBlock {
  constructor(router) { this.router = router; }
  descriptor() {
    return {
      id: "outputs:block", type: "outputs", cls: "cv-servers-block", fixed: { x: 700, y: 20 },
      html: `<div class="cv-servers-head">${escapeHtml(t("topologyServersHead"))} ${helpTip("cvTipServersHead")}</div><div class="cv-servers-body">${renderServersBlockHtml(this.router)}</div>`,
    };
  }
  // Sync port dots on the block. Dots are direct children of the block
  // (position:absolute, left:-9px) so they straddle the left border just like
  // .cv-port.in on regular nodes. Y is computed from getBoundingClientRect() divided
  // by scale so it stays correct when the body is scrolled or the canvas is zoomed.
  static syncPortDots() {
  const world = document.querySelector("[data-cv-world]");
  if (!world) return;
  const block = world.querySelector(".cv-servers-block");
  if (!block) return;
  const blockRect = block.getBoundingClientRect();
  const scale = _cvView.scale || 1;
  const seen = new Set();
  block.querySelectorAll("[data-router-out-row]").forEach((row) => {
    const id = row.dataset.routerOutRow;
    if (!id) return;
    const rowRect = row.getBoundingClientRect();
    if (rowRect.height < 1) return;      // collapsed / hidden accordion row
    seen.add(id);
    const key = `out:${id}`;
    // Find existing dot or create one as a direct child of the block.
    let dot = block.querySelector(`:scope > [data-cv-out-port="${CSS.escape(key)}"]`);
    if (!dot) {
      dot = document.createElement("span");
      dot.className = "cv-port in";
      dot.dataset.cvNode = key;
      dot.dataset.cvOutPort = key;
      dot.title = t("cvDropCable");
      block.appendChild(dot);
    }
    // Position in block's coordinate space (world units = CSS px at scale 1).
    // `top` places the dot's TOP edge, so subtract half its 16px height to put
    // its CENTER on the row center (margin-top is zeroed to keep the rendered
    // rect equal to the top-based math the cable anchors use).
    const yBlock = (rowRect.top - blockRect.top + rowRect.height / 2) / scale;
    dot.style.top = (yBlock - 8) + "px";
    dot.style.marginTop = "0";
  });
  // Folded host/provider groups: rows are hidden, so give every hidden output
  // a dot AT THE GROUP HEADER — its cables converge there instead of vanishing.
  block.querySelectorAll("[data-cv-group-outs].folded").forEach((grp) => {
    const head = grp.querySelector("[data-router-group-fold]") || grp;
    const headRect = head.getBoundingClientRect();
    if (headRect.height < 1) return;
    (grp.dataset.cvGroupOuts || "").split(",").forEach((rawId) => {
      const id = rawId.trim();
      if (!id || seen.has(id)) return;
      seen.add(id);
      const key = `out:${id}`;
      let dot = block.querySelector(`:scope > [data-cv-out-port="${CSS.escape(key)}"]`);
      if (!dot) {
        dot = document.createElement("span");
        dot.className = "cv-port in";
        dot.dataset.cvNode = key;
        dot.dataset.cvOutPort = key;
        dot.title = t("cvDropCable");
        block.appendChild(dot);
      }
      dot.style.top = ((headRect.top - blockRect.top + headRect.height / 2) / scale - 8) + "px";
      dot.style.marginTop = "0";
    });
  });
  // Remove stale dots (output no longer in list or accordion is fully collapsed).
  block.querySelectorAll(":scope > [data-cv-out-port]").forEach((dot) => {
    const id = dot.dataset.cvOutPort?.replace(/^out:/, "");
    if (id && !seen.has(id)) dot.remove();
  });
  }
}


export function _cvSyncServersPortDots() { ServersBlock.syncPortDots(); }
export function _cvSyncInputsBlockPortDots() { InputsBlock.syncPortDots(); }


// ── Graph editing: the router's node graph as an object ───────────────────────
export function _newId(prefix) { return prefix + Date.now().toString(36) + Math.random().toString(36).slice(2, 5); }

// One glyph per rule-node type, shared by the palette cards, the ⚙ panel and
// edge labels — a queue target reads "⏳ queue", not a generic "▢ queue" box.
export const NODE_GLYPH = { schedule: "⏱", weighted: "⚖", roundRobin: "🔁", failover: "⚡", queue: "⏳", requestType: "🔀", requestSize: "📏", onError: "🛟" };

// A cable of the graph. Refs: "in:<proxyId>" — a client port, which may have only ONE
// outgoing connection (a fresh wire replaces its existing one); "rule:<nodeId>" — a
// rule node, fans out to many; "out:<outputId>" — a server or cloud block;
// "inc:<clientKey>" — every port of a client at once (a drag source only).
export class Edge {
  static isSingleOut(ref) { return String(ref).startsWith("in:"); }

  // What the cable points at, for a card row: an output's label, a node's glyph +
  // type, or the bare id when the target vanished.
  static targetLabel(router, edge) {
    const to = String(edge.to || "");
    if (to.startsWith("out:")) {
      const o = (router.outputs || []).find((x) => x.id === to.slice(4));
      return o ? topologyRouterOutputLabel(o) : to.slice(4);
    }
    if (to.startsWith("rule:")) {
      const n = new Graph(router).node(to.slice(5));
      return n ? `${NODE_GLYPH[n.type] || "▢"} ${n.type}` : to.slice(5);
    }
    return to;
  }
}

// The node graph of one router: rule nodes + cables. Every method mutates the router
// record it was given and returns — persisting is the caller's job (saveRouters hands
// the wrappers below a copy, and they save it). Reads never create a missing graph.
export class Graph {
  // Per node kind, the config keys holding the [main, side] role cable ids.
  static ROLE_KEYS = { queue: ["admitEdge", "spillEdge"], onError: ["mainEdge", "rescueEdge"] };
  // Per drag role, [its own key, the other role's key].
  static ROLE_PAIRS = { admit: ["admitEdge", "spillEdge"], spill: ["spillEdge", "admitEdge"],
                        main: ["mainEdge", "rescueEdge"], rescue: ["rescueEdge", "mainEdge"] };

  constructor(router) { this.router = router; }
  get nodes() { return this.router.graph?.nodes || []; }
  get edges() { return this.router.graph?.edges || []; }
  set edges(list) { this.ensure(); this.router.graph.edges = list; }
  ensure() {
    const r = this.router;
    r.graph = r.graph || { nodes: [], edges: [] };
    r.graph.nodes = r.graph.nodes || [];
    r.graph.edges = r.graph.edges || [];
    return r.graph;
  }
  node(nid) { return this.nodes.find((n) => n.id === nid); }
  outEdges(nid) { return this.edges.filter((e) => e.from === `rule:${nid}`); }
  // The queue/onError node a "rule:" ref names — only those kinds carry role cables.
  roleNode(ref) { return this.nodes.find((n) => `rule:${n.id}` === ref && Graph.ROLE_KEYS[n.type]); }
  // Proxy input refs for a client key (the engine keys inputs per proxy/port).
  clientInputRefs(clientKey) {
    return (topology?.proxies || [])
      .filter((p) => (this.router.inputs || []).includes(p.id) && canvasClientKey(p) === clientKey)
      .map((p) => `in:${p.id}`);
  }
  expand(ref) { return ref.startsWith("inc:") ? this.clientInputRefs(ref.slice(4)) : [ref]; }

  // A schedule node is born with two named outputs and an empty week; every other
  // kind starts from an empty config.
  addNode(type, at) {
    const cfg = type === "schedule"
      ? { outputs: [{ id: _newId("sout"), name: "output 1" }, { id: _newId("sout"), name: "output 2" }], grid: Array.from({ length: 7 }, () => Array(24).fill(null)) }
      : {};
    this.ensure().nodes.push({ id: _newId("n"), type, x: at.x, y: at.y, config: cfg });
  }
  removeNode(nid) {
    const g = this.ensure();
    g.nodes = g.nodes.filter((n) => n.id !== nid);
    g.edges = g.edges.filter((e) => e.from !== `rule:${nid}` && e.to !== `rule:${nid}`);
  }

  // fromRef may be "inc:<clientKey>" (expands to one edge per proxy) or a concrete ref.
  // queueRole ("admit"|"spill"|"main"|"rescue") wires a role port: single-out per role
  // (replaces that role's existing edge) and records the new edge id in the node's
  // config. schedPortId tags a schedule/by-type/by-size port: exactly one edge per port.
  addEdge(fromRef, toRef, queueRole, schedPortId) {
    const g = this.ensure();
    if (schedPortId && fromRef.startsWith("rule:")) {
      g.edges = g.edges.filter((e) => !(e.from === fromRef && e.schedPortId === schedPortId));
      g.edges.push({ id: _newId("e"), from: fromRef, to: toRef, schedPortId });
      return;
    }
    if (queueRole && fromRef.startsWith("rule:")) {
      const node = this.roleNode(fromRef);
      if (!node) return;
      node.config = node.config || {};
      const pair = Graph.ROLE_PAIRS[queueRole];
      if (!pair) return;
      const [roleKey, otherKey] = pair;
      // Drop this role's previous edge (single-out per role). Keep the other role's edge.
      g.edges = g.edges.filter((e) => e.id !== node.config[roleKey]);
      // Reuse an existing from→to edge if present (the other role pointing there is
      // disallowed by dedupe, so this only matches a stale same-role edge).
      let edge = g.edges.find((e) => e.from === fromRef && e.to === toRef && e.id !== node.config[otherKey]);
      if (!edge) { edge = { id: _newId("e"), from: fromRef, to: toRef }; g.edges.push(edge); }
      node.config[roleKey] = edge.id;
      return;
    }
    this.expand(fromRef).forEach((f) => {
      if (Edge.isSingleOut(f)) g.edges = g.edges.filter((e) => e.from !== f);   // replace existing
      if (f !== toRef && !g.edges.some((e) => e.from === f && e.to === toRef)) {
        g.edges.push({ id: _newId("e"), from: f, to: toRef });
      }
    });
  }

  // Re-point an existing edge (drag its endpoint to a new target).
  rewire(fromRef, oldTo, newTo) {
    const g = this.ensure();
    // Preserve schedPortId from the old edge so rewired schedule cables stay tagged.
    const oldEdge = g.edges.find((e) => e.from === fromRef && e.to === oldTo);
    const inherited = oldEdge?.schedPortId ? { schedPortId: oldEdge.schedPortId } : {};
    g.edges = g.edges.filter((e) => !(e.from === fromRef && e.to === oldTo));
    let edge = null;
    if (fromRef !== newTo) {
      edge = g.edges.find((e) => e.from === fromRef && e.to === newTo) || null;
      if (!edge) { edge = { id: _newId("e"), from: fromRef, to: newTo, ...inherited }; g.edges.push(edge); }
    }
    // A queue role cable keeps its role when re-pointed: move the admitEdge/spillEdge
    // pointer from the deleted edge onto its replacement — otherwise the pointer dangles
    // and the new edge is drawn roleless (a stray cable the walker ignores).
    const qnode = this.roleNode(fromRef);
    if (qnode?.config && oldEdge) {
      const [mainKey, sideKey] = Graph.ROLE_KEYS[qnode.type];
      for (const [k, other] of [[mainKey, sideKey], [sideKey, mainKey]]) {
        if (qnode.config[k] === oldEdge.id) qnode.config[k] = (edge && edge.id !== qnode.config[other]) ? edge.id : "";
      }
    }
    this.prunePointers();
  }

  deleteBetween(domFrom, domTo) {
    const g = this.ensure();
    const froms = new Set(this.expand(domFrom)), tos = new Set(this.expand(domTo));
    g.edges = g.edges.filter((e) => !(froms.has(e.from) && tos.has(e.to)));
    this.prunePointers();
  }

  // Queue role pointers must reference live edges; clear any left dangling by an edge
  // delete or re-point (heal() may then re-adopt a stray one as admit).
  prunePointers() {
    const ids = new Set(this.edges.map((e) => e.id));
    for (const n of this.nodes) {
      const keys = Graph.ROLE_KEYS[n.type];
      if (!keys || !n.config) continue;
      for (const k of keys) {
        if (n.config[k] && !ids.has(n.config[k])) n.config[k] = "";
      }
    }
  }

  // Queue/onError nodes authored before role-ports existed (or left with a stray
  // edge): the main role points at nothing, yet a non-side cable leaves the node.
  needsHeal() {
    return this.nodes.some((n) => {
      const pair = Graph.ROLE_KEYS[n.type];
      if (!pair) return false;
      const c = n.config || {};
      const outs = this.outEdges(n.id);
      const mainOk = c[pair[0]] && outs.some((e) => e.id === c[pair[0]]);
      return !mainOk && outs.some((e) => e.id !== c[pair[1]]);
    });
  }
  // Adopt the first unassigned outgoing edge as the MAIN role so it anchors at the
  // main port and the row shows its target. Converges: a healthy node is untouched.
  heal() {
    this.nodes.forEach((n) => {
      const pair = Graph.ROLE_KEYS[n.type];
      if (!pair) return;
      n.config = n.config || {};
      const outs = this.outEdges(n.id);
      const mainOk = n.config[pair[0]] && outs.some((e) => e.id === n.config[pair[0]]);
      if (mainOk) return;
      const free = outs.find((e) => e.id !== n.config[pair[1]]);
      if (free) n.config[pair[0]] = free.id;
    });
  }

  // Which cable carries which role, for colouring and anchoring: edgeRole[edgeId] →
  // admit/spill/main/rescue; mainRoleOf[ruleRef] → the main-path role, so an untagged
  // stray queue edge still anchors at the main port instead of the node centre. admit
  // falls back to the first non-spill edge (matches the engine + heals pre-role graphs).
  edgeRoles() {
    const edgeRole = {};
    const mainRoleOf = new Map();
    this.nodes.forEach((n) => {
      const keys = Graph.ROLE_KEYS[n.type];
      if (!keys) return;
      const isQ = n.type === "queue";
      const ref = `rule:${n.id}`;
      mainRoleOf.set(ref, isQ ? "admit" : "main");
      const c = n.config || {};
      const outs = this.outEdges(n.id);
      const [mainKey, sideKey] = keys;
      let mainId = (c[mainKey] && outs.some((e) => e.id === c[mainKey])) ? c[mainKey] : null;
      if (!mainId) { const f = outs.find((e) => e.id !== c[sideKey]); if (f) mainId = f.id; }
      if (mainId) edgeRole[mainId] = isQ ? "admit" : "main";
      if (c[sideKey]) edgeRole[c[sideKey]] = isQ ? "spill" : "rescue";
    });
    return { edgeRole, mainRoleOf };
  }
}




export function clientProxyInputRefs(router, clientKey) { return new Graph(router).clientInputRefs(clientKey); }
export function _isSingleOut(ref) { return Edge.isSingleOut(ref); }






export function graphOutEdges(router, nodeId) { return new Graph(router).outEdges(nodeId); }
export function edgeTargetLabel(router, edge) { return Edge.targetLabel(router, edge); }



// ── The board: viewport, node positions, drags, cables, bindings ──────────────
// Free-form node view: input clients (left) → rule nodes (centre) → outputs (right).
// Drag nodes (rule positions persist in the graph, block positions in localStorage),
// drag the background to pan, wheel to zoom toward the cursor. One board per page;
// the exported _cvView / _cvPos / _cvDrag bindings mirror its state for the modules
// that read them (routers, topology-dnd, topology-render).
export class Board {
  constructor() {
    this.view = _cvView;                 // world transform {tx, ty, scale}
    this.pos = _cvPos;                   // nodeId → {x, y} for the open router
    this._drag = null;                   // active node / pan / connect / rewire / panelwire drag
    // Edge under the mouse (edgeKey) — while set, all OTHER cables dim so the hovered
    // path stands out. Lives here because drawConnectors() rewrites svg.innerHTML on
    // every tick and would otherwise drop the classes.
    this.hoverEdge = null;
    this.windowBound = false;
    // Schedule-grid paint session: collapsed cards, the brush chosen per node, the
    // stroke in progress, and the last painted grid per node (survives between
    // strokes so mid-save strokes don't lose changes).
    this.paint = { collapsed: new Set(), ids: {}, painting: false, nid: null, pending: null, working: {} };
    // Per-node save queue for the schedule grid: one HTTP request per node in flight;
    // strokes arriving meanwhile keep only the LATEST grid as `pending`, fired when the
    // current request settles — no out-of-order writes.
    this.schedSaveQueue = {};
  }
  get drag() { return this._drag; }
  set drag(v) { this._drag = v; _cvDrag = v; }
  get painting() { return this.paint.painting; }
  set painting(v) { this.paint.painting = v; _cvSchedPainting = v; }
  get router() { return (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId); }

  // ── graph edits of the open router ──
  // Persist one edit of the open router's graph; a missing router is a no-op save.
  editGraph(mutate) {
    return saveRouters((routers) => {
      const s = routerById(routers, ui.topologyCanvasRouterId);
      if (!s) return;
      mutate(new Graph(s), s);
    }).catch((e) => toast(e.message));
  }
  addNode(type) {
    const c = this.viewCentre();
    this.editGraph((g) => g.addNode(type, c));
  }
  async deleteNode(nid) {
    const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
    const g = new Graph(router || {});
    const node = g.node(nid);
    const kind = node ? node.type : "node";
    const nEdges = g.edges.filter((e) => e.from === `rule:${nid}` || e.to === `rule:${nid}`).length;
    const extra = nEdges ? t("dlgNodeEdges", { n: nEdges }) : "";
    if (!(await appConfirm(t("dlgDeleteNode", { kind, extra }), { confirmLabel: t("deleteAction") }))) return;
    this.editGraph((graph) => graph.removeNode(nid));
  }
  addEdge(fromRef, toRef, queueRole, schedPortId) {
    if (!fromRef || !toRef || fromRef === toRef) return;
    this.editGraph((g) => g.addEdge(fromRef, toRef, queueRole, schedPortId));
  }
  // One-off on bind: adopt stray queue edges as the main role. Persists only when
  // something changes (converges, no loop).
  healQueueEdges() {
    const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
    if (!router?.graph?.nodes?.length) return;
    if (!new Graph(router).needsHeal()) return;
    saveRouters((routers) => {
      const s = routerById(routers, ui.topologyCanvasRouterId);
      if (!s?.graph) return;
      new Graph(s).heal();
    }).catch(() => {});
  }
  rewireEdge(fromRef, oldTo, newTo) {
    if (!fromRef || !newTo || newTo === oldTo) return;
    this.editGraph((g) => g.rewire(fromRef, oldTo, newTo));
  }
  // Ask before removing a cable. Uses the shared confirm modal; raised above the
  // router-workspace overlay via #confirmOverlay's z-index in CSS.
  confirmDeleteEdge(domFrom, domTo) {
    $("confirmTitle").textContent = t("deleteCableTitle");
    $("confirmText").textContent = t("deleteCableText");
    $("confirmMeta").hidden = true;
    $("confirmPath").textContent = "";
    $("confirmDelete").textContent = t("deleteAction");
    $("confirmDelete").classList.add("danger");
    ui.pendingConfirm = () => { closeConfirmModal(); this.deleteEdgesBetween(domFrom, domTo); };
    $("confirmOverlay").hidden = false;
  }
  deleteEdgesBetween(domFrom, domTo) {
    this.editGraph((g) => g.deleteBetween(domFrom, domTo));
  }
  // Merge a patch into a rule node's config and persist (auto-save).
  saveNodeConfig(nid, patchFn) {
    this.editGraph((g) => { const n = g.node(nid); if (n) { n.config = n.config || {}; patchFn(n.config); } });
  }
  renderNodeConfig(router) {
    if (!ui.topologyRouterNodeCfgId) return "";
    const rec = new Graph(router).node(ui.topologyRouterNodeCfgId);
    if (!rec) return "";
    const node = RuleNode.from(rec, router);
    const edges = node.outEdges;
    const body = (!edges.length && node.panelNeedsEdges())
      ? `<div class="rw-cfg-hint">${t("cvHintConnectFirst")}</div>`
      : node.panelBody(edges);
    return `
      <div class="rw-node-cfg" data-rw-node-cfg>
        <div class="rw-node-cfg-head"><strong>${node.glyph} ${escapeHtml(node.label)}</strong><button class="icon-action compact" type="button" data-cfg-close aria-label="Close">×</button></div>
        <div class="rw-node-cfg-body">${body}</div>
      </div>`;
  }
  // Build the node descriptors for a router: the CLIENTS block, every rule node at its
  // stored position, the SERVERS block.
  nodes(router) {
    const ruleNodes = router.graph?.nodes || [];
    return [
      new InputsBlock(router).descriptor(),
      ...ruleNodes.map((n) => RuleNode.from(n, router).descriptor()),
      new ServersBlock(router).descriptor(),
    ];
  }

  // Rebinding an imported let throws — foreign modules (main, topology-dnd) reset the
  // viewport through this setter instead.
  setViewport(pos, view) { this.pos = pos; this.view = view; _cvPos = pos; _cvView = view; }
  static posKey(routerId) { return `cvpos:${routerId}`; }
  loadPositions(routerId) {
    try { return JSON.parse(localStorage.getItem(Board.posKey(routerId)) || "{}") || {}; } catch { return {}; }
  }
  savePositions(routerId) {
    try { localStorage.setItem(Board.posKey(routerId), JSON.stringify(this.pos)); } catch {}
  }
  // World-space point at the centre of the current viewport (for placing new nodes).
  viewCentre() {
  const vp = document.querySelector("[data-cv-viewport]");
  const w = vp ? vp.clientWidth : 800, h = vp ? vp.clientHeight : 600;
  return { x: Math.round((w / 2 - this.view.tx) / this.view.scale), y: Math.round((h / 2 - this.view.ty) / this.view.scale) };
  }

  renderModal() {
  if (!ui.topologyCanvasRouterId) return "";
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
  if (!router) return "";
  const nodes = this.nodes(router);
  const nodeHtml = nodes.map((n) => {
    const pos = this.pos[n.id] || n.fixed || { x: n.dx, y: n.dy };
    return `<div class="cv-node cv-${n.type} ${n.cls || ""}" data-cv-node="${escapeHtml(n.id)}" style="left:${pos.x}px;top:${pos.y}px">${n.html}</div>`;
  }).join("");
  const tf = `translate(${this.view.tx}px, ${this.view.ty}px) scale(${this.view.scale})`;
  return `
    <div class="topology-policy-overlay" data-topology-canvas-overlay>
      <div class="topology-policy-modal canvas-modal">
        <div class="topology-policy-head">
          <strong>⤢ ${escapeHtml(t("topologyRouterTitle"))} — canvas</strong>
          <span class="muted" style="font-size:11px">drag nodes · scroll = zoom · drag background = pan</span>
          <span class="topology-policy-head-actions">
            <button class="icon-action compact" type="button" data-topology-canvas-close aria-label="${escapeHtml(t("close"))}" title="${escapeHtml(t("close"))}">×</button>
          </span>
        </div>
        <div class="cv-viewport" data-cv-viewport>
          <div class="cv-world" data-cv-world style="transform:${tf}">
            <svg class="cv-svg" data-cv-svg width="4000" height="3000" viewBox="0 0 4000 3000"></svg>
            ${nodeHtml}
          </div>
        </div>
      </div>
    </div>`;
  }

  // ── cables ──
  // World-space point at an element's left/right/center edge (sums offsets up to
  // cv-world, so it works for ports nested inside nodes too).
  static worldPoint(el, side) {
  let x = 0, y = 0, e = el;
  while (e && !(e.classList && e.classList.contains("cv-world"))) { x += e.offsetLeft; y += e.offsetTop; e = e.offsetParent; }
  if (side === "right")  return { x: x + el.offsetWidth, y: y + el.offsetHeight / 2 };
  if (side === "center") return { x: x + el.offsetWidth / 2, y: y + el.offsetHeight / 2 };
  return { x, y: y + el.offsetHeight / 2 }; // "left"
  }
  // World point of an edge's source (out) / target (in) anchor, by ref. Shared by the
  // connector renderer and the rewire/connect drags.
  anchorFrom(ref) {
  const world = document.querySelector("[data-cv-world]");
  if (!world) return null;
  if (ref.startsWith("in:")) {
    // Dots are created by _cvSyncInputsBlockPortDots as direct children of the inputs block.
    const port = world.querySelector(`.cv-port.out[data-cv-ref="${CSS.escape(ref)}"]`);
    return port ? Board.worldPoint(port, "right") : null;
  }
  const node = world.querySelector(`[data-cv-node="${CSS.escape(ref)}"]`);
  return node ? Board.worldPoint(node, "right") : null;
  }
  anchorTo(ref) {
  const world = document.querySelector("[data-cv-world]");
  if (!world) return null;
  if (ref.startsWith("out:")) {
    // Output ports live inside the Servers canvas block as [data-cv-out-port] spans.
    const port = world.querySelector(`[data-cv-out-port="${CSS.escape(ref)}"]`);
    return port ? Board.worldPoint(port, "center") : null;
  }
  const node = world.querySelector(`[data-cv-node="${CSS.escape(ref)}"]`);
  return node ? Board.worldPoint(node.querySelector(".cv-port.in") || node, "left") : null;
  }
  static pathD(a, b) {
  const dx = Math.max(48, Math.abs(b.x - a.x) * 0.48);
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
  }
  drawConnectors() {
  // Always sync block port dots before drawing — ensures they exist and
  // are correctly positioned even if the initial bind ran before layout was ready.
  InputsBlock.syncPortDots();
  ServersBlock.syncPortDots();
  const world = document.querySelector("[data-cv-world]");
  const svg = document.querySelector("[data-cv-svg]");
  if (!world || !svg) return;
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
  if (!router) { svg.innerHTML = ""; return; }
  const graph = router.graph || { nodes: [], edges: [] };
  const { edgeRole: qRole, mainRoleOf: roleFroms } = new Graph(router).edgeRoles();
  // Schedule nodes: map ref → outputs so we can distribute untagged edges by index.
  const schedOutputsMap = {}; // `rule:${nid}` -> outputs[]
  (graph.nodes || []).forEach((n) => {
    if (n.type === "schedule") schedOutputsMap[`rule:${n.id}`] = (n.config?.outputs || []);
  });
  // First pass: resolve each edge's two anchor points + its CSS class.
  const cables = [];
  const seen = new Set();
  (graph.edges || []).forEach((e) => {
    const from = String(e.from), to = String(e.to);
    const k = `${from}->${to}`;
    if (seen.has(k)) return;
    seen.add(k);
    // Queue admit/spill edges anchor at their dedicated role port.
    // Schedule node edges anchor at their per-output port (data-cv-sched-port).
    let a = null;
    const role = qRole[e.id] || roleFroms.get(from) || null;
    if (role) {
      const p = world.querySelector(`[data-cv-node="${CSS.escape(from)}"] .cv-port.out[data-cv-qrole="${role}"]`);
      if (p) a = Board.worldPoint(p, "right");
    }
    if (!a && e.schedPortId) {
      const p = world.querySelector(`[data-cv-node="${CSS.escape(from)}"] [data-cv-sched-port="${CSS.escape(e.schedPortId)}"]`);
      if (p) a = Board.worldPoint(p, "right");
    }
    // Fallback for schedule edges that predate schedPortId: distribute untagged edges
    // across chip ports by index so cables fan out from distinct points.
    if (!a && schedOutputsMap[from]) {
      const nodeEl = world.querySelector(`[data-cv-node="${CSS.escape(from)}"]`);
      if (nodeEl) {
        const untagged = (graph.edges || []).filter((e2) => String(e2.from) === from && !e2.schedPortId);
        const idx = untagged.findIndex((e2) => e2.id === e.id);
        const ports = [...nodeEl.querySelectorAll("[data-cv-sched-port]")];
        const p = ports[idx >= 0 ? idx : 0] || ports[0];
        if (p) a = Board.worldPoint(p, "right");
      }
    }
    if (!a) a = this.anchorFrom(from);
    // anchorTo handles "out:" refs by finding [data-cv-out-port] inside the Servers block.
    const b = this.anchorTo(to);
    if (!a || !b) return;
    let cls = "cv-cable";
    if (qRole[e.id]) cls += ` cv-cable-${qRole[e.id]}`;
    if (this.drag && this.drag.kind === "rewire" && from === this.drag.id && to === this.drag.oldTo) cls += " removing";
    else if (this.drag && this.drag.kind === "connect" && this.drag.replaceFrom && from === this.drag.replaceFrom) cls += " removing";
    cables.push({ a, b, cls, from, to, edgeKey: `${escapeHtml(from)}|${escapeHtml(to)}` });
  });
  // Smooth cables — the same cubic the main board draws, at the kanban's
  // full stroke width. Curves fan out on their own, so the orthogonal
  // machinery they replace (lane buses, hop arcs, junction dots) is gone
  // with the pipes it decorated.
  const paths = [];
  cables.forEach((c) => {
    const dx = Math.max(48, Math.abs(c.b.x - c.a.x) * 0.48);
    const d = `M ${c.a.x} ${c.a.y} C ${c.a.x + dx} ${c.a.y}, ${c.b.x - dx} ${c.b.y}, ${c.b.x} ${c.b.y}`;
    // cubic midpoint (t = 0.5) — where the ✕ delete puck sits
    const mx = (c.a.x + 3 * (c.a.x + dx) + 3 * (c.b.x - dx) + c.b.x) / 8;
    const my = (c.a.y + 3 * c.a.y + 3 * c.b.y + c.b.y) / 8;
    // ONE hooked element per connection. Counting `path` inside the cable layer
    // does not count connections: each edge draws an invisible fat hit-path, the
    // visible cable, and the ✕ puck's two strokes, so five nodes rendered
    // fifty-four paths and the number meant nothing. This <g> is the connection.
    // data-t-id is `from->to` using the same node ids kanban-node carries, so a
    // test can assert the graph's actual wiring rather than that something was
    // drawn.
    paths.push(`<g class="cv-edge-grp" data-t="kanban-cable" data-t-id="${escapeHtml(c.from)}-&gt;${escapeHtml(c.to)}">`
      + `<title>${escapeHtml(t("cvTitleEdge"))}</title>`
      + `<path class="cv-edge-hit" data-cv-edge="${c.edgeKey}" d="${d}" fill="none"></path>`
      + `<path data-cv-edge="${c.edgeKey}" d="${d}" class="${c.cls}" fill="none"></path>`
      + `<g class="cv-edge-x" data-cv-edge-del="${c.edgeKey}" transform="translate(${Math.round(mx * 10) / 10},${Math.round(my * 10) / 10})">`
      + `<circle r="8"></circle><path d="M -3.2 -3.2 L 3.2 3.2 M 3.2 -3.2 L -3.2 3.2"></path>`
      + `</g></g>`);
  });
  if (this.drag && (this.drag.kind === "connect" || this.drag.kind === "rewire") && this.drag.cur) {
    paths.push(`<path d="${Board.pathD(this.drag.from, this.drag.cur)}" class="cv-cable connecting" fill="none"></path>`);
  }
  svg.innerHTML = paths.filter(Boolean).join("");
  if (this.hoverEdge) {
    const grp = svg.querySelector(`[data-cv-edge-del="${CSS.escape(this.hoverEdge)}"]`)?.closest(".cv-edge-grp");
    svg.classList.toggle("edge-focus", !!grp);
    if (grp) grp.classList.add("focus");
  } else {
    svg.classList.remove("edge-focus");
  }
  }

  // ── viewport ──
  applyView() {
  const world = document.querySelector("[data-cv-world]");
  if (world) world.style.transform = `translate(${this.view.tx}px, ${this.view.ty}px) scale(${this.view.scale})`;
  }
  clientToWorld(cx, cy) {
  const vp = document.querySelector("[data-cv-viewport]");
  const r = vp ? vp.getBoundingClientRect() : { left: 0, top: 0 };
  return { x: (cx - r.left - this.view.tx) / this.view.scale, y: (cy - r.top - this.view.ty) / this.view.scale };
  }

  // ── drags ──
  onMove(e) {
  if (!this.drag) return;
  if (this.drag.kind === "node") {
    const x = this.drag.ox + (e.clientX - this.drag.sx) / this.view.scale;
    const y = this.drag.oy + (e.clientY - this.drag.sy) / this.view.scale;
    this.drag.node.style.left = `${x}px`;
    this.drag.node.style.top = `${y}px`;
    this.pos[this.drag.id] = { x: Math.round(x), y: Math.round(y) };
    this.drawConnectors();
  } else if (this.drag.kind === "pan") {
    this.view.tx = this.drag.tx + (e.clientX - this.drag.sx);
    this.view.ty = this.drag.ty + (e.clientY - this.drag.sy);
    this.applyView();
  } else if (this.drag.kind === "connect" || this.drag.kind === "rewire") {
    this.drag.cur = this.clientToWorld(e.clientX, e.clientY);
    const over = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    document.querySelectorAll(".cv-drop-ok").forEach((n) => { if (n !== over) n.classList.remove("cv-drop-ok"); });
    if (over && /^(rule:|out:)/.test(over.dataset.cvNode || "")) over.classList.add("cv-drop-ok");
    this.drawConnectors();
  } else if (this.drag.kind === "panelwire") {
    this.showGhost(e.clientX, e.clientY, this.drag.label);
    const over = document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    document.querySelectorAll(".cv-drop-ok").forEach((n) => { if (n !== over) n.classList.remove("cv-drop-ok"); });
    if (over && /^(rule:|out:)/.test(over.dataset.cvNode || "")) over.classList.add("cv-drop-ok");
  }
  }
  showGhost(x, y, label) {
  let g = document.getElementById("cvGhost");
  if (!g) { g = document.createElement("div"); g.id = "cvGhost"; g.className = "cv-ghost"; document.body.appendChild(g); }
  g.textContent = `⠿ ${label}`;
  g.style.left = `${x}px`; g.style.top = `${y}px`;
  }
  hideGhost() { document.getElementById("cvGhost")?.remove(); }
  // Push a just-dropped node out of any overlaps AND enforce a minimum spacing
  // (smallest-axis translation, cascades until clean or the iteration cap).
  // Only the dragged node moves — neighbours stay where the user put them.
  // 48px: port dots overhang the borders by ~9-20px and cables need runway,
  // so anything tighter reads as clutter.
  resolveOverlap(node) {
  const world = node?.parentElement;
  if (!world) return;
  const GAP = 48;
  const others = [...world.querySelectorAll(".cv-node")].filter((n) => n !== node && n.offsetWidth > 0);
  let x = node.offsetLeft, y = node.offsetTop;
  const w = node.offsetWidth, h = node.offsetHeight;
  for (let iter = 0; iter < 80; iter++) {
    let bumped = false;
    for (const o of others) {
      const ox = o.offsetLeft, oy = o.offsetTop, ow = o.offsetWidth, oh = o.offsetHeight;
      const dx = Math.min(x + w + GAP - ox, ox + ow + GAP - x);
      const dy = Math.min(y + h + GAP - oy, oy + oh + GAP - y);
      if (dx <= 0 || dy <= 0) continue;            // no overlap (incl. gap)
      if (dx <= dy) x += (x + w / 2 < ox + ow / 2) ? -dx : dx;
      else          y += (y + h / 2 < oy + oh / 2) ? -dy : dy;
      bumped = true;
    }
    if (!bumped) break;
  }
  // No clamping to 0: canvas nodes legitimately live at negative world
  // coordinates (the view pans), and clamping dragged them back into overlap.
  x = Math.round(x);
  y = Math.round(y);
  if (x !== node.offsetLeft || y !== node.offsetTop) {
    node.style.left = `${x}px`;
    node.style.top = `${y}px`;
    const id = node.dataset.cvNode;
    if (id) this.pos[id] = { x, y };
    this.drawConnectors();
  }
  }
  onUp(e) {
  if (!this.drag) return;
  if (this.drag.kind === "node") {
    this.drag.node.classList.remove("dragging");
    this.resolveOverlap(this.drag.node);
    if (String(this.drag.id).startsWith("rule:")) {
      // Rule-node position is real data → persist to router.graph.
      const nid = this.drag.id.slice(5), pos = this.pos[this.drag.id];
      if (pos) saveRouters((routers) => {
        const n = (routerById(routers, ui.topologyCanvasRouterId)?.graph?.nodes || []).find((x) => x.id === nid);
        if (n) { n.x = pos.x; n.y = pos.y; }
      }).catch(() => {});
    } else {
      this.savePositions(ui.topologyCanvasRouterId);
    }
  } else if (this.drag.kind === "connect") {
    document.querySelectorAll(".cv-node.cv-drop-ok").forEach((n) => n.classList.remove("cv-drop-ok"));
    const tgt = e && document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    if (tgt && /^(rule:|out:)/.test(tgt.dataset.cvNode || "") && tgt.dataset.cvNode !== this.drag.id) this.addEdge(this.drag.id, tgt.dataset.cvNode, this.drag.qrole, this.drag.schedPortId);
    this.drag = null;
    this.drawConnectors();
    return;
  } else if (this.drag.kind === "rewire") {
    document.querySelectorAll(".cv-node.cv-drop-ok").forEach((n) => n.classList.remove("cv-drop-ok"));
    const tgt = e && document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    if (tgt && /^(rule:|out:)/.test(tgt.dataset.cvNode || "")) this.rewireEdge(this.drag.id, this.drag.oldTo, tgt.dataset.cvNode);
    this.drag = null;
    this.drawConnectors();
    return;
  } else if (this.drag.kind === "panelwire") {
    this.hideGhost();
    document.querySelectorAll(".cv-node.cv-drop-ok").forEach((n) => n.classList.remove("cv-drop-ok"));
    const tgt = e && document.elementFromPoint(e.clientX, e.clientY)?.closest("[data-cv-node]");
    if (tgt && /^(rule:|out:)/.test(tgt.dataset.cvNode || "")) this.addEdge(this.drag.ref, tgt.dataset.cvNode);
    this.drag = null;
    return;
  }
  document.querySelector("[data-cv-viewport]")?.classList.remove("panning");
  this.drag = null;
  }
  // A grab completes through onMove/onUp — bound once per page, at module load too,
  // or a cable grabbed on a page where bind() never ran would never drop.
  bindWindow() {
    if (this.windowBound) return;
    this.windowBound = true;
    window.addEventListener("pointermove", (e) => this.onMove(e));
    window.addEventListener("pointerup", (e) => this.onUp(e));
  }

  // ── bindings: pan/zoom, node drag, port drag, card controls, schedule grid ──
  bind() {
  const viewport = document.querySelector("[data-cv-viewport]");
  const world = document.querySelector("[data-cv-world]");
  if (!viewport || !world) return;
  // One wiring per world generation: the module-load rebind observer and the rAF
  // after renderTopology may both land on the same fresh DOM — double-bound click
  // handlers would double-fire saveRouters.
  if (world.dataset.cvBound) return;
  world.dataset.cvBound = "1";
  this.bindWindow();
  // Edit-in-canvas controls (stop pointerdown so they don't start a node drag).
  world.querySelectorAll(".cv-act").forEach((el) => el.addEventListener("pointerdown", (e) => e.stopPropagation()));
  // Stage D: drag a proxy from the left panel onto a canvas node to route it.
  document.querySelectorAll(".rw-proxy-drag").forEach((h) => {
    h.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault(); e.stopPropagation();
      this.drag = { kind: "panelwire", ref: h.dataset.wireRef, label: h.dataset.wireLabel || h.dataset.wireRef };
      this.showGhost(e.clientX, e.clientY, this.drag.label);
    });
  });
  // Stage C graph editing: palette add, node delete, port-drag connect, edge delete.
  // These buttons live in the standalone page's static header — they survive world
  // rebuilds, so guard against stacking a listener per rebind.
  document.querySelectorAll("[data-cv-add]").forEach((b) => {
    if (b.dataset.cvAddBound) return;
    b.dataset.cvAddBound = "1";
    b.addEventListener("click", () => this.addNode(b.dataset.cvAdd));
  });
  world.querySelectorAll("[data-cv-delnode]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); this.deleteNode(b.dataset.cvDelnode); }));
  // Editing the wait budget moved to the client card: one fact, one place. Only
  // the reference stays here, so there is no handler any more either.
  // Embeddings slot — the one global /v1/embeddings target. Don't start a node drag.
  world.querySelectorAll("[data-cv-embed-out]").forEach((sel) => {
    sel.addEventListener("pointerdown", (e) => e.stopPropagation());
    sel.addEventListener("change", () => {
      const val = sel.value;
      saveRouters((routers) => {
        const s = routerById(routers, ui.topologyCanvasRouterId);
        if (!s) return;
        s.rules = s.rules || {};
        s.rules.embeddingsOutput = val;
      }).catch((e) => toast(e.message));
    });
  });
  // Inline queue-node param inputs (on the card itself). Don't let them start a node drag.
  world.querySelectorAll(".cv-q-cfg-in[data-cv-q]").forEach((inp) => {
    inp.addEventListener("pointerdown", (e) => e.stopPropagation());
    inp.addEventListener("change", () => {
      const nodeEl = inp.closest("[data-cv-node]");
      const nid = nodeEl && String(nodeEl.dataset.cvNode || "").startsWith("rule:") ? nodeEl.dataset.cvNode.slice(5) : "";
      if (!nid) return;
      const key = inp.dataset.cvQ, raw = inp.value.trim();
      this.saveNodeConfig(nid, (cfg) => {
        if (key === "maxSlots") { cfg.maxSlots = raw === "" ? null : Math.max(1, Math.min(64, parseInt(raw, 10) || 1)); return; }
        const lo = Number(inp.min || 0), hi = Number(inp.max || 100);
        cfg[key] = Math.max(lo, Math.min(hi, parseInt(raw, 10) || 0));
      });
    });
  });
  // Delegated port drag: covers both static inline ports AND dynamically-created dots
  // from _cvSyncInputsBlockPortDots / _cvSyncServersPortDots that are appended after bind.
  world.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    const port = e.target.closest(".cv-port.out");
    if (!port) return;
    e.stopPropagation(); e.preventDefault();
    const nodeEl = port.closest("[data-cv-node]");
    if (!nodeEl) return;
    const ref = port.dataset.cvRef || nodeEl.dataset.cvNode;   // per-port (in:<proxyId>) or node id
    const qrole = port.dataset.cvQrole || null;
    const schedPortId = port.dataset.cvSchedPort || null;
    const from = Board.worldPoint(port, "right");
    this.drag = { kind: "connect", id: ref, qrole, schedPortId, from, cur: from, replaceFrom: _isSingleOut(ref) ? ref : null };
  });
  // Cable re-point and ✕ delete moved to document-level delegation at module load
  // (see the block after the Board) — svg-bound listeners died with
  // every background-tick rebuild of the svg.

  // Sync block port dots after initial render and on body scroll. Also schedule a rAF
  // pass in case getBoundingClientRect() returned zeros before layout was complete.
  InputsBlock.syncPortDots();
  ServersBlock.syncPortDots();
  requestAnimationFrame(() => { InputsBlock.syncPortDots(); ServersBlock.syncPortDots(); this.drawConnectors(); });
  // First-open de-overlap: a rule node's stored position can end up UNDER the
  // CLIENTS/SERVERS blocks as those grow over time (more cells, more models) —
  // the node hides until dragged. Run the same resolver a drag-end uses, for
  // every rule node, top-to-bottom for a deterministic cascade. Visual only
  // (nothing persists — no config write on mere open); it converges, so extra
  // runs after rebuilds are no-ops when nothing overlaps.
  requestAnimationFrame(() => {
    if (this.drag) return;
    [...world.querySelectorAll('.cv-node[data-cv-node^="rule:"]')]
      .sort((a, b) => a.offsetTop - b.offsetTop)
      .forEach((n) => this.resolveOverlap(n));
  });
  const serversBody = document.querySelector(".cv-servers-body");
  if (serversBody && !serversBody._cvPortSyncBound) {
    serversBody._cvPortSyncBound = true;
    serversBody.addEventListener("scroll", () => ServersBlock.syncPortDots(), { passive: true });
  }
  const inputsBody = document.querySelector(".cv-inputs-body");
  if (inputsBody && !inputsBody._cvPortSyncBound) {
    inputsBody._cvPortSyncBound = true;
    inputsBody.addEventListener("scroll", () => InputsBlock.syncPortDots(), { passive: true });
  }

  // Stage C.2: open / edit the per-node config panel.
  world.querySelectorAll("[data-cv-cfgnode]").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation(); ui.topologyRouterNodeCfgId = b.dataset.cvCfgnode; renderTopology();
  }));
  const cfgPanel = document.querySelector("[data-rw-node-cfg]");
  if (cfgPanel) {
    const cid = ui.topologyRouterNodeCfgId;
    cfgPanel.querySelector("[data-cfg-close]")?.addEventListener("click", () => { ui.topologyRouterNodeCfgId = ""; renderTopology(); });
    cfgPanel.querySelectorAll("[data-cfg-weight]").forEach((inp) => inp.addEventListener("change", () => {
      const weights = [...cfgPanel.querySelectorAll("[data-cfg-weight]")].map((i) => ({ edge: i.dataset.cfgWeight, pct: Math.max(0, Math.min(100, parseInt(i.value, 10) || 0)) }));
      this.saveNodeConfig(cid, (cfg) => { cfg.weights = weights; });
    }));
    const moveOrder = (id, dir) => {
      const ids = [...cfgPanel.querySelectorAll("[data-cfg-ord-id]")].map((el) => el.dataset.cfgOrdId);
      const i = ids.indexOf(id), j = i + dir;
      if (i < 0 || j < 0 || j >= ids.length) return;
      [ids[i], ids[j]] = [ids[j], ids[i]];
      this.saveNodeConfig(cid, (cfg) => { cfg.order = ids; });
    };
    cfgPanel.querySelectorAll("[data-cfg-up]").forEach((b) => b.addEventListener("click", () => moveOrder(b.dataset.cfgUp, -1)));
    cfgPanel.querySelectorAll("[data-cfg-down]").forEach((b) => b.addEventListener("click", () => moveOrder(b.dataset.cfgDown, 1)));
    // ── queue node (admit/spill are wired via the node's ports, not here) ──
    cfgPanel.querySelectorAll("[data-cfg-q]").forEach((inp) => inp.addEventListener("change", () => {
      const key = inp.dataset.cfgQ;
      const raw = inp.value.trim();
      this.saveNodeConfig(cid, (cfg) => {
        if (key === "maxSlots") { cfg.maxSlots = raw === "" ? null : Math.max(1, Math.min(64, parseInt(raw, 10) || 1)); return; }
        const lo = Number(inp.min || 0), hi = Number(inp.max || 100);
        cfg[key] = Math.max(lo, Math.min(hi, parseInt(raw, 10) || 0));
      });
    }));
  }
  // Node drag: world coords = client delta / current scale.
  world.querySelectorAll("[data-cv-node]").forEach((node) => {
    node.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest(".cv-act") || e.target.closest(".cv-port") || e.target.closest(".cv-q-cfg") || e.target.closest(".cv-in-wait") || e.target.closest(".cv-servers-body") || e.target.closest(".cv-inputs-body") || e.target.closest("[data-cv-sched-cell]") || e.target.closest(".cv-sched-row") || e.target.closest(".cv-sched-addrow")) return;   // control/port/inline-input/servers-body/inputs-body/schedule, not a drag
      e.stopPropagation();
      this.drag = { kind: "node", node, id: node.dataset.cvNode, sx: e.clientX, sy: e.clientY, ox: node.offsetLeft, oy: node.offsetTop };
      node.classList.add("dragging");
      e.preventDefault();
    });
  });
  // Pan when dragging the empty background.
  viewport.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest("[data-cv-node]")) return;
    this.drag = { kind: "pan", sx: e.clientX, sy: e.clientY, tx: this.view.tx, ty: this.view.ty };
    viewport.classList.add("panning");
  });
  // Wheel = zoom toward the cursor.
  viewport.addEventListener("wheel", (e) => {
    if (e.target.closest(".cv-servers-body, .cv-inputs-body, .router-prov-models")) return;
    e.preventDefault();
    const rect = viewport.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    const old = this.view.scale;
    const next = Math.min(2.2, Math.max(0.35, old * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
    this.view.tx = cx - (cx - this.view.tx) * (next / old);
    this.view.ty = cy - (cy - this.view.ty) * (next / old);
    this.view.scale = next;
    this.applyView();
  }, { passive: false });
  // One-off: adopt stray queue edges as `admit` (heals pre-role-port graphs). Converges.
  this.healQueueEdges();
  // Drive queue-node channel-reservation bars (shared with the classic slot view).
  ensureStickyBarTicker();

  // ── Canvas schedule node interactions ─────────────────────────────────────
  // Collapse/expand toggle
  world.querySelectorAll("[data-cv-sched-toggle]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const nid = btn.dataset.cvSchedToggle;
      if (this.paint.collapsed.has(nid)) this.paint.collapsed.delete(nid); else this.paint.collapsed.add(nid);
      renderTopology();
      requestAnimationFrame(() => { this.drawConnectors(); this.bind(); });
    });
  });

  // Chip click — select paint colour
  world.querySelectorAll("[data-cv-sched-chip]").forEach((chip) => {
    chip.addEventListener("click", (e) => {
      if (e.target.closest(".cv-sched-rm") || e.target.closest("[contenteditable]") || e.target.closest(".cv-port")) return;
      e.stopPropagation();
      const [nid, outId] = chip.dataset.cvSchedChip.split(":");
      this.paint.ids[nid] = outId;
      renderTopology();
      requestAnimationFrame(() => { this.drawConnectors(); this.bind(); });
    });
  });

  // Add output
  world.querySelectorAll("[data-cv-sched-addout]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const nid = btn.dataset.cvSchedAddout;
      this.saveNodeConfig(nid, (cfg) => {
        cfg.outputs = cfg.outputs || [];
        const n = cfg.outputs.length + 1;
        cfg.outputs.push({ id: _newId("sout"), name: `output ${n}` });
        if (!cfg.grid) cfg.grid = Array.from({ length: 7 }, () => Array(24).fill(null));
      });
    });
  });

  // Remove output — single saveRouters call to avoid race condition
  world.querySelectorAll("[data-cv-sched-rmout]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const parts = btn.dataset.cvSchedRmout.split(":");
      const nid = parts[0], outId = parts.slice(1).join(":");
      saveRouters((routers) => {
        const s = routerById(routers, ui.topologyCanvasRouterId);
        if (!s) return;
        // Patch node config
        const n = (s.graph?.nodes || []).find((x) => x.id === nid);
        if (n) {
          n.config = n.config || {};
          n.config.outputs = (n.config.outputs || []).filter((o) => o.id !== outId);
          n.config.grid = (n.config.grid || []).map((row) => row.map((c) => (c === outId ? null : c)));
        }
        // Clean up edges in same transaction
        if (s.graph) s.graph.edges = (s.graph.edges || []).filter((e) => !(e.from === `rule:${nid}` && e.schedPortId === outId));
      }).catch((e) => toast(e.message));
    });
  });

  // Rename output — double-click activates editing, blur/Enter saves
  function _cvSchedActivateEdit(span) {
    span.contentEditable = "true";
    span.focus();
    const sel = window.getSelection(), range = document.createRange();
    range.selectNodeContents(span); sel.removeAllRanges(); sel.addRange(range);
  }
  world.querySelectorAll("[data-cv-sched-rename]").forEach((span) => {
    span.addEventListener("pointerdown", (e) => e.stopPropagation());
    span.addEventListener("dblclick", (e) => { e.stopPropagation(); _cvSchedActivateEdit(span); });
    span.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); span.blur(); } });
    span.addEventListener("blur", () => {
      if (span.contentEditable !== "true") return;
      span.removeAttribute("contenteditable");
      const parts = span.dataset.cvSchedRename.split(":");
      const nid = parts[0], outId = parts.slice(1).join(":");
      const name = span.textContent.trim().slice(0, 40) || "output";
      this.saveNodeConfig(nid, (cfg) => {
        const o = (cfg.outputs || []).find((x) => x.id === outId);
        if (o) o.name = name;
      });
    });
  });

  // Rename default label — double-click activates editing, blur/Enter saves
  world.querySelectorAll("[data-cv-sched-rename-default]").forEach((span) => {
    span.addEventListener("pointerdown", (e) => e.stopPropagation());
    span.addEventListener("dblclick", (e) => { e.stopPropagation(); _cvSchedActivateEdit(span); });
    span.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") { e.preventDefault(); span.blur(); } });
    span.addEventListener("blur", () => {
      if (span.contentEditable !== "true") return;
      span.removeAttribute("contenteditable");
      const nid = span.dataset.cvSchedRenameDefault;
      const name = span.textContent.trim().slice(0, 40) || "default";
      this.saveNodeConfig(nid, (cfg) => { cfg.defaultName = name; });
    });
  });

  // Grid painting: pointerdown/over paint cells; pointerup saves
  world.querySelectorAll("[data-cv-sched-cell]").forEach((cell) => {
    cell.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.stopPropagation(); e.preventDefault();
      const nid = cell.dataset.cvSchedCell;
      this.painting = true;
      this.paint.nid = nid;
      const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
      const node = (router?.graph?.nodes || []).find((n) => n.id === nid);
      const _wg = this.paint.working[nid];
      this.paint.pending = { nid, grid: _wg ? _wg.map((r) => [...r]) : ScheduleNode.makeGrid(node?.config || {}) };
      this.paintCell(nid, parseInt(cell.dataset.schedD, 10), parseInt(cell.dataset.schedH, 10));
    });
    cell.addEventListener("pointerover", (e) => {
      if (!this.paint.painting || this.paint.nid !== cell.dataset.cvSchedCell) return;
      this.paintCell(cell.dataset.cvSchedCell, parseInt(cell.dataset.schedD, 10), parseInt(cell.dataset.schedH, 10));
    });
  });
  }

  // ── schedule grid painting ──
  paintCell(nid, d, h) {
  if (!this.paint.pending || this.paint.pending.nid !== nid) return;
  const router = (topology?.routers || []).find((s) => s.id === ui.topologyCanvasRouterId);
  const node = (router?.graph?.nodes || []).find((n) => n.id === nid);
  const outputs = node?.config?.outputs || [];
  // Default to first output if not explicitly chosen yet
  const paintId = this.paint.ids[nid] ?? (outputs[0]?.id || "");
  const grid = this.paint.pending.grid;
  grid[d][h] = (paintId === "" || paintId === "__default__") ? null : paintId;
  // Update DOM immediately (optimistic paint)
  const cell = document.querySelector(`[data-cv-sched-cell="${CSS.escape(nid)}"][data-sched-d="${d}"][data-sched-h="${h}"]`);
  if (cell) {
    const color = grid[d][h] ? ScheduleNode.color(outputs, grid[d][h]) : "";
    cell.style.background = color;
    cell.classList.toggle("painted", !!color);
  }
  }
  endPaint() {
    const paint = this.paint;
    if (!paint.painting || !paint.pending) return;
    this.painting = false;
    const { nid, grid } = paint.pending;
    paint.working[nid] = grid;
    paint.pending = null;
    paint.nid = null;
    this.saveGrid(nid, grid);
  }
  saveGrid(nid, grid) {
  const q = this.schedSaveQueue[nid] || (this.schedSaveQueue[nid] = { inFlight: false, pending: null });
  if (q.inFlight) { q.pending = grid; return; }
  q.inFlight = true;
  saveRouters((routers) => {
    const n = (routerById(routers, ui.topologyCanvasRouterId)?.graph?.nodes || []).find((x) => x.id === nid);
    if (n) { n.config = n.config || {}; n.config.grid = grid; }
  }).catch((e) => toast(e.message)).finally(() => {
    q.inFlight = false;
    if (q.pending !== null) { const next = q.pending; q.pending = null; this.saveGrid(nid, next); }
  });
  }
}

export const board = new Board();
// Shared board state under its old names — the snapshot and foreign modules read them.
export const _cvSchedCollapsed = board.paint.collapsed;
export const _cvSchedPaintIds = board.paint.ids;
export const _cvSchedWorkingGrids = board.paint.working;
export const _cvSchedSaveQueue = board.schedSaveQueue;
export function cvSetViewport(pos, view) { board.setViewport(pos, view); }
export function canvasPosKey(routerId) { return Board.posKey(routerId); }
export function canvasLoadPositions(routerId) { return board.loadPositions(routerId); }
export function canvasSavePositions(routerId) { board.savePositions(routerId); }
export function renderTopologyCanvasModal() { return board.renderModal(); }
export function drawCanvasConnectors() { board.drawConnectors(); }
export function bindCanvasInteractions() { board.bind(); }
export function _cvWorldPoint(el, side) { return Board.worldPoint(el, side); }
export function _cvPathD(a, b) { return Board.pathD(a, b); }
export function _cvClientToWorld(cx, cy) { return board.clientToWorld(cx, cy); }
export function _cvResolveOverlap(node) { board.resolveOverlap(node); }
export function _cvSchedSaveGrid(nid, grid) { board.saveGrid(nid, grid); }


if (typeof window !== "undefined" && !window._cvSchedUpBound) {
  window._cvSchedUpBound = true;
  window.addEventListener("pointerup", () => board.endPaint());
}

// Bound at module load (not in board.bind()): the standalone kanban
// page reaches that bind late or never on a fresh load, and the svg itself is
// rebuilt on every render — document-level delegation is the only stable home.
document.addEventListener("pointerover", (e) => {
  const grp = e.target.closest && e.target.closest(".cv-edge-grp");
  if (!grp) return;
  const svg = grp.closest("svg");
  if (!svg) return;
  board.hoverEdge = grp.querySelector("[data-cv-edge-del]")?.dataset.cvEdgeDel || null;
  svg.classList.add("edge-focus");
  svg.querySelectorAll(".cv-edge-grp.focus").forEach((g) => g.classList.remove("focus"));
  grp.classList.add("focus");
});
document.addEventListener("pointerout", (e) => {
  const grp = e.target.closest && e.target.closest(".cv-edge-grp");
  if (!grp || (e.relatedTarget && grp.contains(e.relatedTarget))) return;
  board.hoverEdge = null;
  grp.classList.remove("focus");
  grp.closest("svg")?.classList.remove("edge-focus");
});
// Cable grab (re-point) and its midpoint ✕ (delete) — document-level for the same
// reason as the hover pair above: background ticks tear down and rebuild the svg,
// and any listener bound to the svg dies with it (the first grab after a tick went
// dead). Capture phase: the world's pan/node-drag pointerdown must never see a
// grab that starts on a cable (the old svg-bound handler cut the bubble before it
// reached the world; capture cuts it earlier still).
document.addEventListener("pointerdown", (e) => {
  if (e.button !== 0 || !e.target.closest) return;
  if (e.target.closest("[data-cv-edge-del]")) return;    // the ✕ acts on click, not grab
  const path = e.target.closest("[data-cv-edge]");
  if (!path || !path.closest("[data-cv-svg]")) return;
  e.stopPropagation(); e.preventDefault();
  const [from, to] = (path.dataset.cvEdge || "").split("|");
  if (!from || !to) return;
  const cur = board.clientToWorld(e.clientX, e.clientY);
  board.drag = { kind: "rewire", id: from, oldTo: to, from: board.anchorFrom(from) || cur, cur };
  board.drawConnectors();
}, true);
document.addEventListener("click", (e) => {
  const del = e.target.closest && e.target.closest("[data-cv-edge-del]");
  if (!del) return;
  e.stopPropagation();
  const [a, b] = (del.dataset.cvEdgeDel || "").split("|");
  if (a && b) board.confirmDeleteEdge(a, b);
}, true);
// The grab completes through board.onMove/onUp — bind them here too, or a cable
// grabbed on a page where board.bind() never ran would never drop.
board.bindWindow();
// Pan/zoom, node drag and port drag bind to the viewport/world elements in
// board.bind() — and died whenever a re-render path rebuilt the canvas
// DOM without renderTopology's rAF rebind (the memo-keyed cloud re-render on the
// standalone kanban does exactly that, leaving the board view-only). Watch for a
// fresh world element and rewire it; the per-generation guard inside
// board.bind() makes overlapping calls harmless, and per-tick svg
// innerHTML rewrites keep element identity so quiet frames no-op.
new MutationObserver(() => board.bind())
  .observe(document.documentElement, { childList: true, subtree: true });
// The "+ App port" button is gone: the kanban is about routing, not about the
// existence of inputs. A port is created where its owner lives — on the client
// card of the main board — and its handlers left with the button, so no live
// path remains to a control that does not exist.
document.addEventListener("click", (e) => {
  const btn = e.target.closest && e.target.closest("[data-cv-port-edit]");
  if (!btn) return;
  e.stopPropagation();
  editTopologyProxy(btn.dataset.cvPortEdit);
});
// ✕ on a dead-agent row (CLIENTS block strip): delete the orphaned assignment
// and free its ports. Same document-level home as the other strip controls.
document.addEventListener("click", (e) => {
  const btn = e.target.closest && e.target.closest("[data-cv-orphan-agent]");
  if (!btn) return;
  e.stopPropagation();
  deleteOrphanAgent(btn.dataset.cvOrphanClient, btn.dataset.cvOrphanAgent);
});
// ⟳ Reconcile — dry-run first, show what it would remove, then ask.
document.addEventListener("click", async (e) => {
  const btn = e.target.closest && e.target.closest("[data-cv-reconcile]");
  if (!btn || btn.disabled) return;
  e.stopPropagation();
  btn.disabled = true;
  try {
    const plan = await api("/api/agent-proxies/reconcile", {
      method: "POST", body: JSON.stringify({ dryRun: true }),
    });
    const changes = plan.result?.changes || [];
    if (!changes.length) { toast(t("cvReconcileNothing")); btn.disabled = false; return; }
    const lines = changes.map((c) => c.kind === "delete"
      ? `✕ :${c.port} ${c.label || ""} — ${c.why}`
      : `→ ${c.agentId}: ${c.from || "—"} ⇒ ${c.to || "—"} — ${c.why}`);
    const ok = await appConfirm(t("cvReconcileConfirm", { count: String(changes.length) }),
      { detail: lines.join("\n"), danger: changes.some((c) => c.kind === "delete") });
    if (!ok) { btn.disabled = false; return; }
    const res = await api("/api/agent-proxies/reconcile", {
      method: "POST", body: JSON.stringify({}),
    });
    if (res.topology) setTopology(res.topology);
    renderTopology();
    toast(t("cvReconcileDone", { count: String((res.result?.deletedPorts || []).length) }));
  } catch (err) { toast(err.message); }
  btn.disabled = false;
});

// ── Function faces: the old names, kept for the callers and the snapshot ───────
export function _cvQHistFmt(ms) { return History.fmt(ms); }
export function _cvQHistModel(item) { return History.model(item); }
export function _cvQHistRoute(raw) { return History.route(raw); }
export function _fetchQueueHist(nodeId) { History.fetch(_cvQueueHistData, nodeId); }
export function _fetchSchedHist(nodeId) { History.fetch(_cvSchedHistData, nodeId); }
export function _portDisplayName(port, opts) { return InputsBlock.portName(port, opts); }
export function cvNodeTypeLabel(type) { return RuleNode.typeLabel(type); }
export function syncQueueNodesLive() { QueueNode.syncLive(); OnErrorNode.syncLive(); }
export function _cvSchedInputPorts(router, schedNodeId) { return ScheduleNode.inputPorts(router, schedNodeId); }
export function _cvSchedColor(outputs, outId) { return ScheduleNode.color(outputs, outId); }
export function _cvSchedMakeGrid(cfg) { return ScheduleNode.makeGrid(cfg); }
export function _cvSchedNow() { return ScheduleNode.now(); }
export function scheduleOutputColor(router, outputId) { return ScheduleNode.outputColor(router, outputId); }
export function canvasNodes(router) { return board.nodes(router); }
export function renderRouterNodeConfig(router) { return board.renderNodeConfig(router); }
export function addRuleNode(type) { board.addNode(type); }
export function deleteRuleNode(nid) { return board.deleteNode(nid); }
export function addGraphEdge(fromRef, toRef, queueRole, schedPortId) { board.addEdge(fromRef, toRef, queueRole, schedPortId); }
export function healQueueNodeEdges() { board.healQueueEdges(); }
export function rewireGraphEdge(fromRef, oldTo, newTo) { board.rewireEdge(fromRef, oldTo, newTo); }
export function confirmDeleteGraphEdge(domFrom, domTo) { board.confirmDeleteEdge(domFrom, domTo); }
export function deleteGraphEdgesBetween(domFrom, domTo) { board.deleteEdgesBetween(domFrom, domTo); }
export function saveNodeConfig(nid, patchFn) { board.saveNodeConfig(nid, patchFn); }
