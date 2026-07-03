// Canvas chart rendering: metric charts, GPU/token history, chart modals.
import { t } from "./i18n.js";
import { formatTps } from "./polling.js";
import { state, topology, ui } from "./state.js";
import {
  topologyIncidentCause,
  topologyIncidentForItem,
  topologyIsQueuedItem,
} from "./topology-activity.js";
import { groupedTopologyProxies } from "./topology-proxies.js";
import { $, escapeHtml, formatMemoryMiB } from "./utils.js";

export function formatRate(bytesPerSecond) {
  const n = Number(bytesPerSecond || 0);
  if (!Number.isFinite(n)) return "0 B/s";
  if (n >= 1024 ** 3) return `${(n / (1024 ** 3)).toFixed(2)} GB/s`;
  if (n >= 1024 ** 2) return `${(n / (1024 ** 2)).toFixed(2)} MB/s`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB/s`;
  return `${Math.round(n)} B/s`;
}

export function systemSamples(data) {
  return Array.isArray(data?.samples) ? data.samples : [];
}

export function chartSize(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(320, Math.round(rect.width * dpr));
  const height = Math.max(120, Math.round(rect.height * dpr));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  return { width, height, dpr };
}

export function drawMetricChart(canvas, samples, series, options = {}) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const { width, height } = chartSize(canvas);
  const hasGridLabels = !!options.gridLabels;
  const max = options.max || Math.max(1, ...samples.flatMap((sample) => series.map((row) => Number(row.value(sample) || 0))));
  const fontSize = Math.max(10, Math.round(width / 96));
  ctx.font = `${fontSize}px ui-monospace, Menlo, monospace`;

  // Y-axis grid labels (e.g. the Power chart). Compute them before the gutter
  // so the gutter can be sized to the widest label: the font scales with the
  // canvas width, so a fixed gutter clipped the leading digits in the wide
  // expanded modal ("30W" rendered as "0W").
  const gridDivisions = options.gridDivisions || 4;
  const gridSuffix = options.gridLabelSuffix || "";
  const fmtAxis = (val, suffix) => (val >= 1000 ? `${(val / 1000).toFixed(1)}k` : `${Math.round(val)}`) + suffix;
  const gridLabel = (i) => fmtAxis(max * (gridDivisions - i) / gridDivisions, gridSuffix);
  // Optional second Y axis on the right edge: the Token Speed chart plots two
  // series at independent scales (prompt left, gen right), so each edge shows
  // its own series' scale instead of one shared — and misleading — axis.
  const hasRightLabels = !!options.rightLabels;
  const rightMax = options.rightMax || max;
  const rightSuffix = options.rightLabelSuffix || "";
  const rightLabel = (i) => fmtAxis(rightMax * (gridDivisions - i) / gridDivisions, rightSuffix);
  const widestLabel = (fn) => {
    let w = 0;
    for (let i = 0; i <= gridDivisions; i += 1) w = Math.max(w, ctx.measureText(fn(i)).width);
    return Math.ceil(w) + 10;  // 5px breathing room on each side
  };
  const pad = {
    left: hasGridLabels ? widestLabel(gridLabel) : 10,
    right: hasRightLabels ? widestLabel(rightLabel) : 10,
    top: 14, bottom: 18,
  };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#050607";
  ctx.fillRect(0, 0, width, height);

  // Grid lines + optional Y-axis labels (left, and an optional right axis)
  ctx.strokeStyle = "rgba(160, 180, 185, 0.13)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= gridDivisions; i += 1) {
    const y = pad.top + (plotH * i / gridDivisions);
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    const edgeColor = i === 0 || i === gridDivisions
      ? "rgba(220, 233, 233, 0.45)" : "rgba(220, 233, 233, 0.30)";
    if (hasGridLabels) {
      ctx.fillStyle = options.gridLabelColor || edgeColor;
      ctx.textAlign = "right";
      ctx.fillText(gridLabel(i), pad.left - 5, y + fontSize * 0.35);
    }
    // Skip the bottom label on the right axis so it can't collide with "now".
    if (hasRightLabels && i !== gridDivisions) {
      ctx.fillStyle = options.rightLabelColor || edgeColor;
      ctx.textAlign = "right";
      ctx.fillText(rightLabel(i), width - 5, y + fontSize * 0.35);
    }
  }

  ctx.fillStyle = "rgba(220, 233, 233, 0.58)";
  ctx.textAlign = "right";
  // Top-anchor the max label so it can't clip off the top edge when the font
  // scales up in the wide expanded modal (a fixed baseline y=12 was < ascent).
  if (options.maxLabel && !hasGridLabels) {
    ctx.textBaseline = "top";
    ctx.fillText(options.maxLabel, width - 10, 4);
    ctx.textBaseline = "alphabetic";
  }
  ctx.fillText("now", width - 10, height - 5);
  ctx.textAlign = "left";

  if (!samples.length) return;
  const columns = Math.max(1, Math.floor(plotW));
  const bucketSize = Math.max(1, Math.ceil(samples.length / columns));
  const visible = [];
  for (let i = 0; i < samples.length; i += bucketSize) {
    visible.push(samples.slice(i, i + bucketSize));
  }
  const barW = Math.max(1, plotW / visible.length);
  series.forEach((row, rowIndex) => {
    ctx.fillStyle = row.color;
    ctx.strokeStyle = row.color;
    const offset = series.length > 1 ? (barW / series.length) * rowIndex : 0;
    const actualBarW = Math.max(1, (barW / series.length) - 1);
    if (row.mode === "line") {
      // Per-series scale: a row may carry its own max so e.g. prompt-processing
      // (~700 t/s) and generation (~100 t/s) each use the full chart height
      // instead of sharing one axis that flattens the slower line.
      const smax = row.max || max;
      ctx.beginPath();
      const pts = [];
      visible.forEach((bucket, index) => {
        const value = Math.max(0, Math.min(smax, bucket.reduce((sum, sample) => sum + Number(row.value(sample) || 0), 0) / bucket.length));
        const x = pad.left + index * barW + barW / 2;
        const y = pad.top + plotH - (value / smax) * plotH;
        pts.push([x, y]);
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.lineWidth = 2;
      ctx.stroke();
      // Optional dots at each vertex — makes discrete points (e.g. one per
      // completed request on the token chart) visible instead of a flat line.
      if (options.markers && pts.length <= 240) {
        pts.forEach(([x, y]) => {
          ctx.beginPath();
          ctx.arc(x, y, 2.4, 0, Math.PI * 2);
          ctx.fill();
        });
      }
      return;
    }
    visible.forEach((bucket, index) => {
      const value = Math.max(0, Math.min(max, Math.max(...bucket.map((sample) => Number(row.value(sample) || 0)))));
      const x = pad.left + index * barW + offset;
      const h = Math.max(value > 0 ? 2 : 0, (value / max) * plotH);
      const y = pad.top + plotH - h;
      ctx.fillRect(x, y, actualBarW, h);
    });
  });
}

export function drawTopologyGpuHistoryOnCanvas(samples, canvas) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const { width, height } = chartSize(canvas);
  const pad = { left: 8, right: 8, top: 12, bottom: 14 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#050607";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(160, 180, 185, 0.12)";
  ctx.lineWidth = 1;
  [0.25, 0.5, 0.75, 1].forEach((pct) => {
    const y = pad.top + plotH - plotH * pct;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
  });
  ctx.fillStyle = "rgba(220, 233, 233, 0.58)";
  ctx.font = `${Math.max(9, Math.round(width / 120))}px ui-monospace, Menlo, monospace`;
  ctx.textAlign = "right";
  // Top-anchor "100%" so it isn't clipped at the top edge when the font scales
  // up in the wide expanded modal (a fixed baseline y=10 was < the ascent).
  ctx.textBaseline = "top";
  ctx.fillText("100%", width - 8, 4);
  ctx.textBaseline = "alphabetic";
  ctx.fillText("now", width - 8, height - 4);
  if (!samples.length) return;
  const columns = Math.max(1, Math.min(Math.floor(plotW), 600));
  const bucketSize = Math.max(1, Math.ceil(samples.length / columns));
  const buckets = [];
  for (let i = 0; i < samples.length; i += bucketSize) {
    buckets.push(samples.slice(i, i + bucketSize));
  }
  const barW = Math.max(1, plotW / buckets.length);
  buckets.forEach((bucket, index) => {
    const gpuValue = Math.max(...bucket.map((sample) => Number(sample.gpu?.utilPct || 0)));
    const x = pad.left + index * barW;
    const h = Math.max(gpuValue > 0 ? 2 : 0, (Math.min(gpuValue, 100) / 100) * plotH);
    const y = pad.top + plotH - h;
    ctx.fillStyle = "rgba(105, 208, 144, 0.72)";
    ctx.fillRect(x, y, Math.max(1, barW - 1), h);
  });
}

export function drawTopologyGpuHistory() {
  const canvas = $("topologyGpuHistoryChart");
  if (!canvas) return;
  const samples = systemSamples(ui.latestSystemMonitor).slice(-600);
  const meta = $("topologyGpuHistoryMeta");
  const legend = $("topologyGpuHistoryLegend");
  drawTopologyGpuHistoryOnCanvas(samples, canvas);
  if (!samples.length) {
    if (meta) meta.textContent = "waiting";
    if (legend) legend.textContent = "";
    return;
  }
  const latest = samples[samples.length - 1] || {};
  const activeRoutes = latest.correlatedActivity?.gpu?.activeRoutes || [];
  if (meta) {
    const retention = ui.latestSystemMonitor?.retentionSeconds || 600;
    meta.textContent = `${samples.length} samples · ${Math.round(retention / 60)} min`;
  }
  const latestUtil = latest.gpu?.utilPct ?? "n/a";
  const latestTemp = latest.gpu?.temperatureC ?? "n/a";
  const latestPower = latest.gpu?.powerW ?? "n/a";
  canvas.title = [
    `GPU ${latestUtil}%`,
    `${latestTemp}C`,
    `${latestPower}W`,
    activeRoutes.length ? `active: ${activeRoutes.join(", ")}` : "no active routes now",
  ].join(" · ");
  const columns = Math.max(1, Math.min(220, Math.floor((canvas.width || 320) - 16)));
  const bucketSize = Math.max(1, Math.ceil(samples.length / columns));
  const buckets = [];
  for (let i = 0; i < samples.length; i += bucketSize) buckets.push(samples.slice(i, i + bucketSize));
  const barW = Math.max(1, ((canvas.width || 320) - 16) / buckets.length);
  drawTopologyRouteHistory(samples, buckets, barW);
  drawRouteActivityModal();
  // Token Speed draws generation-only points (gated server-side by counter
  // advance), so idle never paints the held-gauge plateau.
  drawTopologyTokenSpeedHistory(controllerTokenGenSamples());
  drawTopologyVramHistory(samples);
  drawTopologyPowerHistory(samples);
  drawChartModal();
  drawTopologyServerStats(samples);
  renderTopologyIncidents(samples);
  drawGpuMetricSparklines(samples);
  drawNodeTelemetry();
}

// Per-node telemetry — built with the SAME markup + classes + canvases as the
// controller's widget (so it looks/behaves identically: collapsed rows with a
// sparkline, hover reveals the chart, click opens it fullscreen via the shared
// modal). Canvases are driven by drawNodeTelemetry(); data-open-chart carries a
// "node:<id>:<key>" token the modal understands.
// Proxy-route labels that actually drive THIS node's GPU — i.e. routes whose
// llama upstream points at one of the node's llama-server endpoints. (Grouping
// by "agents hosted here" was misleading: an agent's route can go to the cloud
// or another GPU. This view matches the node's GPU/Token panels.)
export function nodeRouteLabels(nodeId) {
  const node = (topology?.nodes || []).find((n) => String(n.id) === String(nodeId));
  if (!node) return [];
  const endpoints = new Set();
  (node.servers || []).forEach((s) => {
    const host = s.clientIp || node.ip;
    if (host && s.port != null) {
      endpoints.add(`${host}:${s.port}`);
      if (node.role === "controller") endpoints.add(`127.0.0.1:${s.port}`);
    }
  });
  const out = [];
  (topology?.proxies || []).forEach((p) => {
    if (String(p.upstreamType || "llama") === "cloud") return;       // cloud routes don't use a GPU
    if (!endpoints.has(`${p.upstreamHost}:${p.upstreamPort}`)) return;
    const lbl = String(p.label || "").trim();
    if (lbl && !out.includes(lbl)) out.push(lbl);
  });
  return out;
}

// Time-bucket samples to a canvas width (mirrors the controller's bucketing).
export function _routeBuckets(samples, canvas) {
  const cssW = canvas.offsetWidth || canvas.width || 320;
  const dpr = window.devicePixelRatio || 1;
  const columns = Math.max(1, Math.min(600, Math.floor(cssW)));
  const bucketSize = Math.max(1, Math.ceil((samples.length || 1) / columns));
  const buckets = [];
  for (let i = 0; i < samples.length; i += bucketSize) buckets.push(samples.slice(i, i + bucketSize));
  const barW = Math.max(1, (cssW * dpr - 16) / Math.max(1, buckets.length));
  return { buckets, barW };
}

export function nodeTelemetryRowsHtml(n) {
  const g0 = (n.gpus || [])[0];
  const srv = (n.servers || []).find((s) => s.port);
  const id = String(n.id);
  const hasRoutes = nodeRouteLabels(id).length > 0;
  if (!g0 && !srv && !hasRoutes) return "";
  const oc = (key) => `data-open-chart="${escapeHtml(`node:${id}:${key}`)}"`;
  const spark = (key) => `<span class="gpu-metric-spark" data-node-metric-spark="${escapeHtml(`${id}:${key}`)}"></span>`;
  const val = (key) => `<span class="topology-history-meta" data-node-metric-val="${escapeHtml(`${id}:${key}`)}">—</span>`;
  const cv = (key, cls, h) => `<canvas class="${cls}" ${oc(key)} data-node-canvas="${escapeHtml(`${id}:${key}`)}" width="320" height="${h}"></canvas>`;
  const metric = (key, label, descriptor, chartCls, h) => `
    <div class="gpu-metric">
      <div class="topology-history-subhead topology-history-subhead--expand" ${oc(key)}>${escapeHtml(label)} <span class="topology-expand-hint">⤢</span></div>
      <div class="topology-card-head compact">
        <span class="topology-history-meta">${escapeHtml(descriptor)}</span>
        ${val(key)}${spark(key)}
      </div>
      ${cv(key, chartCls, h)}
    </div>`;
  const routeBlock = hasRoutes ? `
    <div class="topology-history-subhead topology-history-subhead--expand" data-open-route-activity data-route-node="${escapeHtml(id)}">${escapeHtml(t("topologyRouteActivity"))} <span class="topology-expand-hint">⤢</span></div>
    <canvas class="topology-route-history-chart" data-node-route-canvas="${escapeHtml(id)}" data-open-route-activity data-route-node="${escapeHtml(id)}" width="320" height="74"></canvas>` : "";
  return `<div class="node-ctrl-gpu-telemetry node-telemetry">
    ${g0 ? metric("gpu", t("topologyGpuHistoryHead"), t("util"), "topology-gpu-history-chart", 86) : ""}
    ${srv ? metric("tokens", t("topologyTokenSpeedHead"), t("topologyPromptGen"), "topology-token-speed-chart", 74) : ""}
    ${g0 ? metric("vram", t("vram"), t("topologyUsedTotal"), "topology-stat-chart", 56) : ""}
    ${g0 ? metric("power", t("power"), t("topologyGpuPowerDraw"), "topology-stat-chart topology-power-chart", 160) : ""}
    ${routeBlock}
  </div>`;
}

// Tiny inline sparkline for the COLLAPSED GPU metric rows (shown only when the
// row isn't hovered; CSS hides them in the expanded/full-chart state). Same
// idea as the old node-header sparklines we removed.
export function miniSparklineSvg(values, color, max) {
  const pts = (values || []).map(Number).filter((v) => Number.isFinite(v));
  if (pts.length < 2) return "";
  const w = 72, h = 14;
  const hi = max || Math.max(...pts, 1);
  const step = w / (pts.length - 1);
  const d = pts.map((v, i) => `${(i * step).toFixed(1)},${(h - Math.min(Math.max(v, 0), hi) / hi * h).toFixed(1)}`).join(" ");
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${d}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
}

// Per-node pseudo-samples shaped like the system-monitor samples the chart
// renderers expect, so client nodes reuse the EXACT same canvas renderers (and
// modal) as the controller — guaranteeing identical look + behaviour.
export function _nodeGpuSamples(node) {
  const g0 = (node.gpus || [])[0] || {};
  const total = Number(g0.memoryTotalMiB || 0);
  return (g0.history || []).map((r) => ({ gpu: {
    utilPct: r[2], memoryUsedMiB: r[1], memoryTotalMiB: total,
    memoryPct: total ? (r[1] / total * 100) : 0, powerW: r[3],
  } }));
}
export function _nodeTokenSamples(node) {
  const srv = (node.servers || []).find((s) => (s.tpsHistory || []).length) || {};
  return (srv.tpsHistory || []).map((r) => ({ tokens: {
    promptTokensPerSecond: r[1], predictedTokensPerSecond: r[2],
  } }));
}

// Draw the per-node telemetry canvases (client nodes) with the shared renderers
// + fill value labels and the collapsed-row sparklines. Runs each monitor tick.
export function drawNodeTelemetry() {
  (topology?.nodes || []).forEach((n) => {
    if (n.role === "controller") return;  // controller keeps the singleton widget
    const id = String(n.id);
    const cv = (key) => document.querySelector(`[data-node-canvas="${CSS.escape(`${id}:${key}`)}"]`);
    const setVal = (key, txt) => {
      const e = document.querySelector(`[data-node-metric-val="${CSS.escape(`${id}:${key}`)}"]`);
      if (e && e.textContent !== txt) e.textContent = txt;
    };
    const setSpark = (key, values, color, max) => {
      const e = document.querySelector(`[data-node-metric-spark="${CSS.escape(`${id}:${key}`)}"]`);
      if (e) e.innerHTML = miniSparklineSvg(values, color, max);
    };
    const g0 = (n.gpus || [])[0];
    if (g0) {
      const gpuS = _nodeGpuSamples(n);
      drawTopologyGpuHistoryOnCanvas(gpuS, cv("gpu"));
      drawTopologyVramHistory(gpuS, cv("vram"));
      drawTopologyPowerHistory(gpuS, cv("power"));
      const total = Number(g0.memoryTotalMiB || 0);
      setVal("gpu", `${Math.round(Number(g0.utilizationGpuPct || 0))}%`);
      setSpark("gpu", gpuS.map((s) => s.gpu.utilPct), "rgba(105, 208, 144, 0.9)", 100);
      setVal("vram", `${(Number(g0.memoryUsedMiB || 0) / 1024).toFixed(1)} / ${(total / 1024).toFixed(1)} GB`);
      setSpark("vram", gpuS.map((s) => s.gpu.memoryUsedMiB), "rgba(125, 211, 252, 0.9)", total || 1);
      const pw = gpuS.map((s) => s.gpu.powerW);
      setVal("power", `${Number(g0.powerDrawW || 0).toFixed(1)} W`);
      setSpark("power", pw, "rgba(45, 212, 191, 0.9)", Math.max(50, ...pw));
    }
    const srv = (n.servers || []).find((s) => s.port);
    if (srv) {
      const tokS = _nodeTokenSamples(n);
      drawTopologyTokenSpeedHistory(tokS, cv("tokens"));
      setVal("tokens", `prompt ${formatTps(srv.promptTps || 0)} / gen ${formatTps(srv.genTps || 0)} t/s`);
      setSpark("tokens", tokS.map((s) => s.tokens.predictedTokensPerSecond), "rgba(105, 208, 144, 0.95)",
        Math.max(10, ...tokS.map((s) => s.tokens.predictedTokensPerSecond)));
    }
    const routeCv = document.querySelector(`[data-node-route-canvas="${CSS.escape(id)}"]`);
    if (routeCv) {
      const labels = nodeRouteLabels(id);
      const sm = systemSamples(ui.latestSystemMonitor).slice(-600);
      const { buckets, barW } = _routeBuckets(sm, routeCv);
      drawTopologyRouteHistory(sm, buckets, barW, routeCv, { routes: labels });
    }
  });
}

export function drawGpuMetricSparklines(samples) {
  const set = (key, values, color, max) => {
    document.querySelectorAll(`[data-metric-spark="${key}"]`).forEach((el) => {
      el.innerHTML = miniSparklineSvg(values, color, max);
    });
  };
  const gpu = samples.map((s) => Number(s.gpu?.utilPct || 0));
  // Use the per-request completed-token samples (same source as the expanded
  // chart), not the system-monitor gauge: the gauge holds the last request's
  // t/s across many samples, so the mini sparkline drew a flat line while the
  // big chart showed real per-request variation.
  const tok = controllerTokenGenSamples().map(topologyEvalTps);
  const vram = samples.map((s) => Number(s.gpu?.memoryPct ?? s.gpu?.memoryUtilPct ?? 0));
  const pow = samples.map((s) => Number(s.gpu?.powerW || 0));
  set("gpu", gpu, "rgba(105, 208, 144, 0.9)", 100);
  set("tokens", tok, "rgba(105, 208, 144, 0.95)", Math.max(10, ...tok));
  set("vram", vram, "rgba(125, 211, 252, 0.9)", 100);
  set("power", pow, "rgba(45, 212, 191, 0.9)", Math.max(50, ...pow));
}

export function topologyPromptTps(sample) {
  return Number(sample?.llamaActivity?.lastTiming?.promptTps
    ?? sample?.correlatedActivity?.llamaServer?.lastTiming?.promptTps
    ?? sample?.tokens?.promptTokensPerSecond
    ?? 0);
}

export function topologyEvalTps(sample) {
  return Number(sample?.llamaActivity?.lastTiming?.evalTps
    ?? sample?.correlatedActivity?.llamaServer?.lastTiming?.evalTps
    ?? sample?.tokens?.predictedTokensPerSecond
    ?? 0);
}

// Controller generation-only token series. llama.cpp updates its token metrics
// atomically when a request COMPLETES (counter jumps once at the end, even for
// long streams), so each entry here is one finished request's reported t/s.
// Nothing is added while idle, so the chart never paints a held-gauge plateau.
// Shaped like monitor samples so the chart renderer consumes it unchanged.
export function controllerTokenGenSamples() {
  return ui.latestSystemMonitor?.tokenGenSamples || [];
}

// Shared floating tooltip for chart point hover.
export function ensureChartHoverTip() {
  let tip = document.getElementById("chartHoverTip");
  if (!tip) {
    tip = document.createElement("div");
    tip.id = "chartHoverTip";
    tip.style.cssText = "position:fixed;z-index:9999;display:none;pointer-events:none;"
      + "background:rgba(10,12,14,0.96);border:1px solid rgba(140,160,165,0.3);"
      + "border-radius:6px;padding:6px 8px;font:11px ui-monospace,Menlo,monospace;"
      + "color:#dce9e9;white-space:nowrap;box-shadow:0 4px 14px rgba(0,0,0,0.5)";
    document.body.appendChild(tip);
  }
  return tip;
}

export function _fmtMs(ms) {
  ms = Number(ms || 0);
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

// Default accessor for the controller chart's {time, tokens:{...}} samples.
export function _mainTokenInfo(s) {
  const tk = s.tokens || {};
  return { genTps: tk.predictedTokensPerSecond, genTokens: tk.genTokens, genMs: tk.genMs,
           promptTps: tk.promptTokensPerSecond, promptTokens: tk.promptTokens, promptMs: tk.promptMs,
           cacheTokens: tk.cacheTokens, time: s.time };
}

// Per-request hover tooltip for a token chart: maps cursor X to the nearest
// recorded request and shows its real throughput, size, duration and cache
// reuse. getInfo adapts different sample shapes to a common field set.
export function attachTokenChartHover(canvas, samples, getInfo) {
  canvas._tokenSamples = samples;
  canvas._tokenGetInfo = getInfo || _mainTokenInfo;
  if (canvas._tokenHoverBound) return;
  canvas._tokenHoverBound = true;
  const tip = ensureChartHoverTip();
  canvas.addEventListener("mousemove", (e) => {
    const arr = canvas._tokenSamples || [];
    if (!arr.length) { tip.style.display = "none"; return; }
    const frac = Math.max(0, Math.min(1, e.offsetX / (canvas.offsetWidth || 1)));
    const s = arr[Math.round(frac * (arr.length - 1))];
    if (!s) { tip.style.display = "none"; return; }
    const info = (canvas._tokenGetInfo || _mainTokenInfo)(s);
    const finishLine = info.finish
      ? (info.finish === "length"
          ? `<span style="color:rgba(245,170,90,0.95)">finish: length (cut at max_tokens)</span>`
          : `<span style="opacity:0.6">finish: ${escapeHtml(String(info.finish))}</span>`)
      : "";
    tip.innerHTML = [
      `<b style="color:rgba(105,208,144,0.95)">gen</b> ${formatTps(info.genTps)} t/s · ${info.genTokens || 0} tok · ${_fmtMs(info.genMs)}`,
      `<b style="color:rgba(96,165,250,0.95)">prompt</b> ${formatTps(info.promptTps)} t/s · ${info.promptTokens || 0} tok · ${_fmtMs(info.promptMs)}`,
      info.cacheTokens ? `<span style="opacity:0.6">cache ${info.cacheTokens} tok reused</span>` : "",
      finishLine,
      info.time ? `<span style="opacity:0.6">${new Date(info.time * 1000).toLocaleTimeString()}</span>` : "",
    ].filter(Boolean).join("<br>");
    tip.style.display = "block";
    // Keep the tooltip on-screen: flip to the other side of the cursor when it
    // would overflow the right/bottom edge (it was clipped near the modal edge).
    const margin = 8;
    let left = e.clientX + 12;
    let top = e.clientY + 12;
    if (left + tip.offsetWidth > window.innerWidth - margin) left = e.clientX - 12 - tip.offsetWidth;
    if (top + tip.offsetHeight > window.innerHeight - margin) top = e.clientY - 12 - tip.offsetHeight;
    tip.style.left = `${Math.max(margin, left)}px`;
    tip.style.top = `${Math.max(margin, top)}px`;
  });
  canvas.addEventListener("mouseleave", () => { tip.style.display = "none"; });
}

export function drawTopologyTokenSpeedHistory(samples, overrideCanvas) {
  const canvas = overrideCanvas || $("topologyTokenSpeedChart");
  if (!canvas) return;
  const meta = overrideCanvas ? null : $("topologyTokenSpeedMeta");
  const legend = overrideCanvas ? null : $("topologyTokenSpeedLegend");
  // Independent scales: prompt-processing (~hundreds t/s) and generation
  // (~tens t/s) each get their own max so neither line is flattened.
  const roundMax = (vals) => Math.max(10, Math.ceil(Math.max(...vals, 0) / 10) * 10);
  const promptMax = roundMax(samples.map(topologyPromptTps).filter((v) => v > 0));
  const genMax = roundMax(samples.map(topologyEvalTps).filter((v) => v > 0));
  drawMetricChart(canvas, samples, [
    { color: "rgba(96, 165, 250, 0.9)", mode: "line", value: topologyPromptTps, max: promptMax },
    { color: "rgba(105, 208, 144, 0.95)", mode: "line", value: topologyEvalTps, max: genMax },
  ], {
    max: promptMax, markers: true,
    // Dual axis: prompt (blue) scale on the left, gen (green) on the right,
    // each color-matched to its line. Suffix "" keeps ticks compact (the
    // legend already spells out the units).
    gridLabels: true, gridLabelColor: "rgba(96, 165, 250, 0.75)",
    rightLabels: true, rightMax: genMax, rightLabelColor: "rgba(105, 208, 144, 0.8)",
  });
  attachTokenChartHover(canvas, samples);
  const latest = samples[samples.length - 1] || {};
  const prompt = topologyPromptTps(latest);
  const evalSpeed = topologyEvalTps(latest);
  if (meta) meta.textContent = samples.length ? `prompt ${formatTps(prompt)} / gen ${formatTps(evalSpeed)} t/s` : "waiting";
  if (legend) {
    legend.innerHTML = [
      `<span class="topology-history-route" style="--route-color: rgba(96, 165, 250, 0.95)">prompt ≤${promptMax}</span>`,
      `<span class="topology-history-route" style="--route-color: rgba(105, 208, 144, 0.95)">gen ≤${genMax}</span>`,
    ].join("");
  }
  canvas.title = "";
  // Returned so the expanded modal can show the per-series scale in its legend
  // (each line is normalized to its own max, so there is no single Y axis).
  return { promptMax, genMax };
}

export function drawTopologyVramHistory(samples, overrideCanvas) {
  const canvas = overrideCanvas || $("topologyVramChart");
  if (!canvas) return;
  const meta = overrideCanvas ? null : $("topologyVramMeta");
  drawMetricChart(canvas, samples, [
    { value: (s) => s.gpu?.memoryPct || s.gpu?.memoryUtilPct || 0, color: "rgba(125, 211, 252, 0.85)", mode: "line" },
  ], { max: 100, maxLabel: "100%" });
  const latest = samples[samples.length - 1] || {};
  if (meta) {
    const used = latest.gpu?.memoryUsedMiB;
    const total = latest.gpu?.memoryTotalMiB;
    const pct = latest.gpu?.memoryPct ?? latest.gpu?.memoryUtilPct;
    meta.textContent = used != null ? `${formatMemoryMiB(used)} / ${formatMemoryMiB(total)}` : (pct != null ? `${pct}%` : "—");
  }
}

export function drawTopologyPowerHistory(samples, overrideCanvas) {
  const canvas = overrideCanvas || $("topologyPowerChart");
  if (!canvas) return;
  const meta = overrideCanvas ? null : $("topologyPowerMeta");
  const maxPower = Math.max(50, ...samples.map((s) => Number(s.gpu?.powerW || 0)));
  drawMetricChart(canvas, samples, [
    { value: (s) => s.gpu?.powerW || 0, color: "rgba(45, 212, 191, 0.85)", mode: "line" },
  ], { max: maxPower, gridLabels: true, gridLabelSuffix: "W", gridDivisions: 6 });
  const latest = samples[samples.length - 1] || {};
  if (meta) meta.textContent = latest.gpu?.powerW != null ? `${Number(latest.gpu.powerW).toFixed(1)} W` : "—";
}

export function drawTopologyServerStats(samples) {
  if (!samples.length) return;
  const latest = samples[samples.length - 1] || {};

  // CPU
  const cpuEl = $("topologyCpuValue");
  if (cpuEl) cpuEl.textContent = latest.cpu?.total != null ? `${latest.cpu.total}%` : "—";
  drawMetricChart($("topologyCpuChart"), samples, [
    { value: (s) => s.cpu?.total || 0, color: "rgba(244, 191, 79, 0.85)" },
  ], { max: 100, maxLabel: "100%" });

  // RAM
  const memEl = $("topologyMemValue");
  if (memEl) memEl.textContent = latest.memory?.ok
    ? `${latest.memory.usedPct || 0}% · ${formatMemoryMiB(latest.memory.availableMiB)} free`
    : "—";
  drawMetricChart($("topologyMemChart"), samples, [
    { value: (s) => s.memory?.usedPct || 0, color: "rgba(251, 146, 60, 0.85)", mode: "line" },
  ], { max: 100, maxLabel: "100%" });

  // Network
  const rx = latest.net?.rxBytesPerSec || 0;
  const tx = latest.net?.txBytesPerSec || 0;
  const netEl = $("topologyNetValue");
  if (netEl) netEl.textContent = `↓ ${formatRate(rx)} / ↑ ${formatRate(tx)}`;
  const maxNet = Math.max(1024, ...samples.flatMap((s) => [s.net?.rxBytesPerSec || 0, s.net?.txBytesPerSec || 0]));
  drawMetricChart($("topologyNetChart"), samples, [
    { value: (s) => s.net?.rxBytesPerSec || 0, color: "rgba(139, 140, 246, 0.85)" },
    { value: (s) => s.net?.txBytesPerSec || 0, color: "rgba(217, 133, 216, 0.85)" },
  ], { max: maxNet, maxLabel: formatRate(maxNet) });

  // Disk
  const read = latest.disk?.readBytesPerSec || 0;
  const write = latest.disk?.writeBytesPerSec || 0;
  const diskEl = $("topologyDiskValue");
  if (diskEl) diskEl.textContent = `R ${formatRate(read)} / W ${formatRate(write)}`;
  const maxDisk = Math.max(1024, ...samples.flatMap((s) => [s.disk?.readBytesPerSec || 0, s.disk?.writeBytesPerSec || 0]));
  drawMetricChart($("topologyDiskChart"), samples, [
    { value: (s) => s.disk?.readBytesPerSec || 0, color: "rgba(163, 230, 53, 0.85)" },
    { value: (s) => s.disk?.writeBytesPerSec || 0, color: "rgba(255, 133, 133, 0.85)" },
  ], { max: maxDisk, maxLabel: formatRate(maxDisk) });

  // Processes
  const procEl = $("topologyProcessValue");
  if (procEl) procEl.textContent = latest.processes?.[0]
    ? `${latest.processes[0].name} ${Number(latest.processes[0].cpuPct || 0).toFixed(1)}%`
    : "—";
  const procList = $("topologyProcesses");
  if (procList) {
    procList.innerHTML = (latest.processes || []).slice(0, 10).map((row) => `
      <div class="topology-process-row">
        <span>${escapeHtml(row.name || "")}</span>
        <code>${escapeHtml(String(row.pid || ""))}</code>
        <strong>${Number(row.cpuPct || 0).toFixed(1)}%</strong>
        <span>${formatMemoryMiB(row.rssMiB)}</span>
      </div>
    `).join("") || `<div class="topology-muted" style="padding:6px 0">no data</div>`;
  }

  // Meta
  const metaEl = $("topologyServerStatsMeta");
  if (metaEl) metaEl.textContent = `${samples.length} samples`;
}

export function renderLlamaClientsInnerHtml() {
  const llamaClients = ui.latestSystemMonitor?.latest?.llamaClients || {};
  const clients = llamaClients.clients || [];
  if (!llamaClients.ok && !clients.length) return `<span class="topology-muted" style="font-size:11px">—</span>`;
  if (!clients.length) return `<span class="topology-muted" style="font-size:11px">no active clients</span>`;
  return clients.map((row) => `
    <div class="topology-client-row">
      <strong>${escapeHtml(row.clientName || row.clientIp || "?")}</strong>
      <code>${escapeHtml(row.clientIp || "")}${row.clientPort ? `:${row.clientPort}` : ""}</code>
      <span class="topology-muted">${escapeHtml(row.state || "ESTAB")}</span>
    </div>
  `).join("");
}

export function topologyIncidentItems(samples) {
  const persisted = Array.isArray(ui.latestSystemMonitor?.incidents) ? ui.latestSystemMonitor.incidents : [];
  if (persisted.length) {
    const cutoff = Date.now() / 1000 - 86400;
    return persisted
      .filter((row) => row.kind !== "fallback_active" && (row.time || row.finishedAt || row.startedAt || 0) >= cutoff)
      .slice(0, 8)
      .map((row) => ({
      ...row,
      incident: {
        kind: row.kind || "incident",
        title: row.title || "route incident",
        summary: row.summary || "",
        cause: row.cause || topologyIncidentCause(row, row.kind || "incident"),
      },
    }));
  }
  const items = [];
  const seen = new Set();
  const add = (item) => {
    const incident = topologyIncidentForItem(item);
    if (!incident) return;
    if (incident.kind === "fallback" || incident.kind === "fallback_active") return;
    const key = `${item.id || item.label}:${item.startedAt || ""}:${item.finishedAt || ""}:${incident.title}`;
    if (seen.has(key)) return;
    seen.add(key);
    items.push({ ...item, incident });
  };
  samples.slice(-600).forEach((sample) => {
    const correlated = sample.correlatedActivity || {};
    (correlated.activeRequests || []).forEach(add);
    (correlated.recentRequests || []).slice(0, 10).forEach(add);
  });
  return items
    .sort((a, b) => Number(b.finishedAt || b.startedAt || 0) - Number(a.finishedAt || a.startedAt || 0))
    .slice(0, 8);
}

export function renderTopologyIncidents(samples = systemSamples(ui.latestSystemMonitor)) {
  const panel = $("topologyIncidents");
  const meta = $("topologyIncidentsMeta");
  if (!panel) return;
  const incidents = topologyIncidentItems(samples || []);
  if (meta) meta.textContent = incidents.length ? `${incidents.length} recent` : "clear";
  // Reflect the count on the controller node's header button.
  document.querySelectorAll("[data-ctrl-incidents-count]").forEach((el) => {
    el.textContent = String(incidents.length);
  });
  document.querySelectorAll("[data-ctrl-incidents]").forEach((btn) => {
    btn.classList.toggle("has-incidents", incidents.length > 0);
  });
  if (!incidents.length) {
    panel.innerHTML = `<div class="topology-incident-empty">No slow or failed proxy incidents in the visible history.</div>`;
    return;
  }
  panel.innerHTML = incidents.map((item) => {
    const incident = item.incident;
    const eventTime = item.finishedAt || item.startedAt || item.time;
    const time = eventTime
      ? new Date(Number(eventTime) * 1000).toLocaleTimeString()
      : "";
    const detail = [
      time,
      item.client || "",
      item.status ? `status ${item.status}` : "",
      item.port ? `:${item.port}` : "",
      item.correlation || "",
    ].filter(Boolean).join(" · ");
    return `
      <div class="topology-incident-row ${["failed", "upstream_timeout"].includes(incident.kind) ? "failed" : ""}">
        <strong>${escapeHtml(incident.title)}</strong>
        <span>${escapeHtml(incident.summary)}</span>
        ${incident.cause ? `<span>${escapeHtml(`likely: ${incident.cause}`)}</span>` : ""}
        <small>${escapeHtml(detail)}</small>
      </div>
    `;
  }).join("");
}

export let _routeActivityDrawState = null;

// Maps a route-activity state to an i18n key (resolved through t() at render).
export const ROUTE_ACTIVITY_STATE_LABELS = {
  active:             "ratActive",
  cloud_active:       "ratCloudActive",
  queued:             "ratQueued",
  recent:             "ratRecent",
  cloud_recent:       "ratCloudRecent",
  preempting:         "ratPreempting",
  slow:               "ratSlow",
  degraded:           "ratDegraded",
  client_disconnected:"ratClientLeft",
  failed:             "ratFailed",
};

export function initRouteActivityCanvasHover() {
  const canvas = $("routeActivityModalCanvas");
  const tooltip = $("routeActivityTooltip");
  if (!canvas || !tooltip) return;
  canvas.addEventListener("mousemove", (e) => {
    const s = _routeActivityDrawState;
    if (!s) { tooltip.hidden = true; return; }
    const rect = canvas.getBoundingClientRect();
    const cssX = e.clientX - rect.left;
    const cssY = e.clientY - rect.top;
    const rowIndex = Math.floor((cssY - s.padTop) / (s.rowH + s.rowGap));
    if (rowIndex < 0 || rowIndex >= s.routes.length) { tooltip.hidden = true; return; }
    const bucketIndex = Math.floor((cssX * s.dpr - 8) / s.barW);
    if (bucketIndex < 0 || bucketIndex >= s.buckets.length) { tooltip.hidden = true; return; }
    const route = s.routes[rowIndex];
    const bucket = s.buckets[bucketIndex];
    const state = topologyRouteActivityForBucket(bucket, route);
    const retentionSec = ui.latestSystemMonitor?.retentionSeconds || 600;
    const secsAgo = Math.round((s.buckets.length - 1 - bucketIndex) * retentionSec / s.buckets.length);
    const timeLabel = secsAgo < 5 ? t("ratNow") : secsAgo < 60 ? t("ratSecsAgo", { s: secsAgo }) : t("ratMinsAgo", { m: Math.round(secsAgo / 60) });
    const color = state ? topologyRouteActivityColor(null, state) : "rgba(150,162,168,0.2)";
    const border = "";
    const stateLabel = t(ROUTE_ACTIVITY_STATE_LABELS[state] || "topologyNoActivity");
    tooltip.innerHTML =
      `<span class="rat-route">${escapeHtml(route)}</span>` +
      `<span class="rat-state"><i style="background:${color}${border}"></i>${escapeHtml(stateLabel)}</span>` +
      `<span class="rat-time">${escapeHtml(timeLabel)}</span>`;
    tooltip.hidden = false;
    const tx = Math.min(e.clientX + 16, window.innerWidth - 210);
    const ty = Math.max(8, Math.min(e.clientY - 12, window.innerHeight - 90));
    tooltip.style.left = `${tx}px`;
    tooltip.style.top = `${ty}px`;
  });
  canvas.addEventListener("mouseleave", () => { tooltip.hidden = true; });
}

export function buildRouteActivityLegendHtml() {
  const items = [
    { color: "rgba(37,99,235,0.92)",   label: "выполняется (локально)" },
    { color: "rgba(186,230,253,0.92)", label: "☁ облако (активно)" },
    { color: "rgba(96,165,250,0.60)",  label: "в очереди" },
    { color: "rgba(52,211,153,0.75)",  label: "завершился OK" },
    { color: "rgba(99,102,241,0.82)",  label: "☁ облако (завершено)" },
    { color: "rgba(45,212,191,0.82)",  label: "медленно (успех)" },
    { color: "rgba(167,139,250,0.88)", label: "вытесняется" },
    { color: "rgba(228,173,83,0.88)",  label: "инцидент (не фатальный)" },
    { color: "rgba(250,204,21,0.82)",  label: "клиент ушёл" },
    { color: "rgba(255,120,120,0.90)", label: "ошибка / таймаут" },
  ];
  return items.map(({ color, label, border }) =>
    `<span class="ral-item"><i style="background:${color}${border ? `;outline:${border}` : ""}"></i>${escapeHtml(label)}</span>`
  ).join("");
}

export const CHART_EXPAND_CONFIGS = {
  gpu:    { title: "GPU History",  height: 200 },
  tokens: { title: "Token Speed",  height: 200 },
  vram:   { title: "VRAM",         height: 180 },
  power:  { title: "Power",        height: 260 },
};

export let _chartExpandType = null;

export function openChartModal(type) {
  _chartExpandType = type;
  const overlay = $("chartExpandOverlay");
  if (!overlay) return;
  let config = CHART_EXPAND_CONFIGS[type] || {};
  if (String(type).startsWith("node:")) {
    const [, id, key] = String(type).split(":");
    const node = (topology?.nodes || []).find((nd) => String(nd.id) === id);
    const base = CHART_EXPAND_CONFIGS[key] || {};
    config = { title: `${node?.name || id} · ${base.title || key}`, height: base.height || 200 };
  }
  const titleEl = $("chartExpandTitle");
  if (titleEl) titleEl.textContent = config.title || type;
  const canvas = $("chartExpandCanvas");
  if (canvas) canvas.style.height = `${config.height || 200}px`;
  overlay.hidden = false;
  drawChartModal();
}

export function closeChartModal() {
  const overlay = $("chartExpandOverlay");
  if (overlay) overlay.hidden = true;
  _chartExpandType = null;
}

export function drawChartModal() {
  const overlay = $("chartExpandOverlay");
  if (!overlay || overlay.hidden) return;
  const canvas = $("chartExpandCanvas");
  if (!canvas) return;
  const legendEl = $("chartExpandLegend");
  // Per-node chart: draw the node's own history instead of the controller's.
  if (String(_chartExpandType).startsWith("node:")) {
    const [, id, key] = String(_chartExpandType).split(":");
    const node = (topology?.nodes || []).find((nd) => String(nd.id) === id);
    if (!node) return;
    if (key === "gpu") drawTopologyGpuHistoryOnCanvas(_nodeGpuSamples(node), canvas);
    else if (key === "vram") drawTopologyVramHistory(_nodeGpuSamples(node), canvas);
    else if (key === "power") drawTopologyPowerHistory(_nodeGpuSamples(node), canvas);
    else if (key === "tokens") {
      const tmax = drawTopologyTokenSpeedHistory(_nodeTokenSamples(node), canvas) || {};
      if (legendEl) legendEl.innerHTML = [
        `<span class="ral-item"><i style="background:rgba(96,165,250,0.95)"></i>prompt ≤${tmax.promptMax ?? "—"} t/s</span>`,
        `<span class="ral-item"><i style="background:rgba(105,208,144,0.95)"></i>gen ≤${tmax.genMax ?? "—"} t/s</span>`,
      ].join("");
      return;
    }
    if (legendEl) legendEl.innerHTML = "";
    return;
  }
  const samples = systemSamples(ui.latestSystemMonitor).slice(-600);
  if (_chartExpandType === "gpu") {
    drawTopologyGpuHistoryOnCanvas(samples, canvas);
    if (legendEl) legendEl.innerHTML = "";
  } else if (_chartExpandType === "tokens") {
    const tmax = drawTopologyTokenSpeedHistory(controllerTokenGenSamples(), canvas) || {};
    if (legendEl) legendEl.innerHTML = [
      `<span class="ral-item"><i style="background:rgba(96,165,250,0.95)"></i>prompt ≤${tmax.promptMax ?? "—"} t/s</span>`,
      `<span class="ral-item"><i style="background:rgba(105,208,144,0.95)"></i>gen ≤${tmax.genMax ?? "—"} t/s</span>`,
    ].join("");
  } else if (_chartExpandType === "vram") {
    drawTopologyVramHistory(samples, canvas);
    if (legendEl) legendEl.innerHTML = "";
  } else if (_chartExpandType === "power") {
    drawTopologyPowerHistory(samples, canvas);
    if (legendEl) legendEl.innerHTML = "";
  }
}

export let _routeActivityHoverBound = false;
export let _routeActivityNode = null;  // when set, the modal shows only this node's routes
export function openRouteActivityModal(nodeId) {
  _routeActivityNode = (typeof nodeId === "string" && nodeId) ? nodeId : null;
  const overlay = $("routeActivityOverlay");
  if (!overlay) return;
  const titleEl = overlay.querySelector(".modal-head-row strong");
  if (titleEl) {
    const node = (topology?.nodes || []).find((nd) => String(nd.id) === _routeActivityNode);
    titleEl.textContent = node ? `Route Activity · ${node.name || node.id}` : "Route Activity";
  }
  overlay.hidden = false;
  if (!_routeActivityHoverBound) { _routeActivityHoverBound = true; initRouteActivityCanvasHover(); }
  drawRouteActivityModal();
}

export function closeRouteActivityModal() {
  const overlay = $("routeActivityOverlay");
  if (overlay) overlay.hidden = true;
  const tt = $("routeActivityTooltip");
  if (tt) tt.hidden = true;
}

export function drawRouteActivityModal() {
  const overlay = $("routeActivityOverlay");
  if (!overlay || overlay.hidden) return;
  const canvas = $("routeActivityModalCanvas");
  if (!canvas) return;
  const samples = systemSamples(ui.latestSystemMonitor).slice(-600);
  const cssW = canvas.offsetWidth || 800;
  const dpr = window.devicePixelRatio || 1;
  const columns = Math.max(1, Math.min(600, Math.floor(cssW)));
  const bucketSize = Math.max(1, Math.ceil((samples.length || 1) / columns));
  const buckets = [];
  for (let i = 0; i < samples.length; i += bucketSize) buckets.push(samples.slice(i, i + bucketSize));
  const plotW = cssW * dpr - 16;
  const barW = Math.max(1, plotW / Math.max(1, buckets.length));
  drawTopologyRouteHistory(samples, buckets, barW, canvas, {
    rowH: 28, rowGap: 5,
    routes: _routeActivityNode ? nodeRouteLabels(_routeActivityNode) : undefined,
  });
  const legendEl = $("routeActivityLegend");
  if (legendEl) legendEl.innerHTML = buildRouteActivityLegendHtml();
}

export function drawTopologyRouteHistory(samples, buckets, barW, overrideCanvas, opts = {}) {
  const canvas = overrideCanvas || $("topologyRouteHistoryChart");
  const legend = overrideCanvas ? null : $("topologyGpuHistoryLegend");
  if (!canvas) return;
  // Build route order from Proxy Ports grouping (same order as the column).
  const sortedProxies = (topology?.proxies || []).slice().sort((a, b) => Number(a.port || 0) - Number(b.port || 0));
  const routes = [];
  if (Array.isArray(opts.routes)) {
    // Caller restricted the rows (e.g. a per-node Route Activity).
    opts.routes.forEach((name) => { if (name && !routes.includes(name)) routes.push(name); });
  } else {
    groupedTopologyProxies(sortedProxies).forEach((group) => {
      group.proxies.forEach((proxy) => {
        const name = String(proxy.label || "").trim();
        if (name && !routes.includes(name)) routes.push(name);
      });
    });
  }
  if (!routes.length && !Array.isArray(opts.routes)) {
    // Fallback to any observed routes if proxies aren't loaded yet.
    const seen = new Map();
    samples.forEach((sample) => {
      topologyRouteActivityForSample(sample).forEach((_state, route) => {
        if (route && !seen.has(route)) seen.set(route, true);
      });
    });
    seen.forEach((_v, route) => routes.push(route));
  }
  // Resize canvas vertically so every row has a readable height.
  const rowH = opts.rowH ?? 14;
  const rowGap = opts.rowGap ?? 3;
  const padTop = 6;
  const padBottom = 6;
  if (routes.length) {
    const targetCssH = padTop + padBottom + routes.length * rowH + Math.max(0, routes.length - 1) * rowGap;
    canvas.style.height = `${targetCssH}px`;
  }
  const ctx = canvas.getContext("2d");
  const { width, height, dpr } = chartSize(canvas);
  const pad = { left: 8, right: 8, top: padTop * dpr, bottom: padBottom * dpr };
  const plotW = width - pad.left - pad.right;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#050607";
  ctx.fillRect(0, 0, width, height);
  if (!routes.length) {
    ctx.fillStyle = "rgba(220, 233, 233, 0.5)";
    ctx.font = `${11 * dpr}px system-ui, sans-serif`;
    ctx.fillText("no route activity samples", pad.left, Math.round(height / 2));
    if (legend) legend.innerHTML = "";
    return;
  }
  const rowHpx = rowH * dpr;
  const rowGapPx = rowGap * dpr;
  routes.forEach((route, rowIndex) => {
    const y = pad.top + rowIndex * (rowHpx + rowGapPx);
    ctx.fillStyle = "rgba(160, 180, 185, 0.08)";
    ctx.fillRect(pad.left, y, plotW, rowHpx);
    buckets.forEach((bucket, index) => {
      const state = topologyRouteActivityForBucket(bucket, route);
      if (!state) return;
      const x = pad.left + index * barW;
      ctx.fillStyle = topologyRouteActivityColor(route, state);
      ctx.fillRect(x, y, Math.max(1, barW - 1), rowHpx);
    });
  });
  // Row labels on top of bars, with a dark halo for contrast against colored fills.
  ctx.font = `${10 * dpr}px ui-monospace, Menlo, monospace`;
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  routes.forEach((route, rowIndex) => {
    const y = pad.top + rowIndex * (rowHpx + rowGapPx) + rowHpx / 2;
    ctx.shadowColor = "rgba(0,0,0,0.85)";
    ctx.shadowBlur = 3 * dpr;
    ctx.fillStyle = "rgba(232, 240, 240, 0.92)";
    ctx.fillText(route, pad.left + 6 * dpr, y);
  });
  ctx.shadowColor = "transparent";
  ctx.shadowBlur = 0;
  const latest = samples[samples.length - 1] || {};
  const latestRoutes = [...topologyRouteActivityForSample(latest).keys()];
  if (legend) legend.innerHTML = "";
  // Native title only on the small chart; modal uses the custom hover tooltip
  if (!overrideCanvas) {
    canvas.title = latestRoutes.length
      ? `routes now: ${latestRoutes.join(", ")}`
      : `recent routes: ${routes.join(", ")}`;
  } else {
    canvas.title = "";
    _routeActivityDrawState = { routes, buckets, barW, rowH, rowGap, padTop, dpr };
  }
}

export function topologyRouteActivityPriority(state) {
  return { failed: 8, client_disconnected: 7, preempting: 6, degraded: 5, active: 4, cloud_active: 4, slow: 3, recent: 2, cloud_recent: 2, queued: 1 }[state] || 0;
}

export function topologyRouteActivitySet(map, route, state) {
  if (!route) return;
  const current = map.get(route);
  if (!current || topologyRouteActivityPriority(state) > topologyRouteActivityPriority(current)) {
    map.set(route, state);
  }
}

export function topologyRouteActivityForSample(sample) {
  const activity = new Map();
  const correlated = sample?.correlatedActivity || {};
  const sampleTime = Number(sample?.time || 0);
  (correlated.gpu?.activeRoutes || []).forEach((route) => topologyRouteActivitySet(activity, route, "active"));
  (correlated.gpu?.cloudActiveRoutes || []).forEach((route) => topologyRouteActivitySet(activity, route, "cloud_active"));
  (correlated.llamaServer?.activeRoutes || []).forEach((route) => topologyRouteActivitySet(activity, route, "active"));
  (correlated.activeRequests || []).forEach((item) => {
    const incident = topologyIncidentForItem(item);
    const isQueued = topologyIsQueuedItem(item);
    const isPreempting = String(item.phase || "") === "preempting";
    let state;
    if (incident?.kind === "failed" || incident?.kind === "upstream_timeout") state = "failed";
    else if (incident?.kind === "client_disconnected") state = "client_disconnected";
    else if (isPreempting) state = "preempting";
    else if (isQueued) state = "queued";
    else state = item.isCloud ? "cloud_active" : "active";
    topologyRouteActivitySet(activity, item.label, state);
  });
  (correlated.recentRequests || []).forEach((item) => {
    const eventTime = Number(item.finishedAt || item.startedAt || 0);
    if (!sampleTime || !eventTime || Math.abs(sampleTime - eventTime) > 3) return;
    const incident = topologyIncidentForItem(item);
    let state;
    if (incident?.kind === "failed" || incident?.kind === "upstream_timeout") state = "failed";
    else if (incident?.kind === "client_disconnected") state = "client_disconnected";
    else if (incident?.kind === "slow") state = "slow";
    else if (incident) state = "degraded";
    else state = item.isCloud ? "cloud_recent" : "recent";
    topologyRouteActivitySet(activity, item.label, state);
  });
  return activity;
}

export function topologyRouteActivityForBucket(bucket, route) {
  let state = "";
  bucket.forEach((sample) => {
    const next = topologyRouteActivityForSample(sample).get(route);
    if (next && topologyRouteActivityPriority(next) > topologyRouteActivityPriority(state)) {
      state = next;
    }
  });
  return state;
}

export function topologyRouteActivityColor(_route, state) {
  if (state === "failed")             return "rgba(255, 120, 120, 0.90)"; // красный — hard error / timeout
  if (state === "client_disconnected") return "rgba(250, 204,  21, 0.82)"; // жёлтый — клиент ушёл сам
  if (state === "preempting")         return "rgba(167, 139, 250, 0.88)"; // фиолетовый — вытесняется
  if (state === "slow")               return "rgba( 45, 212, 191, 0.82)"; // бирюзовый — медленно, но успех
  if (state === "degraded")           return "rgba(228, 173,  83, 0.88)"; // оранжевый — инцидент (не фатальный)
  if (state === "active")             return "rgba( 37,  99, 235, 0.92)"; // тёмно-синий — выполняется локально
  if (state === "cloud_active")       return "rgba(186, 230, 253, 0.92)"; // светло-облачный — обрабатывается облаком
  if (state === "recent")             return "rgba( 52, 211, 153, 0.75)"; // зелёный — только что завершился нормально
  if (state === "cloud_recent")       return "rgba( 99, 102, 241, 0.82)"; // индиго — облако завершило нормально
  if (state === "queued")             return "rgba( 96, 165, 250, 0.60)"; // голубой — ждёт в очереди
  return "rgba(150, 162, 168, 0.48)";
}

export function latestSample(samples) {
  return samples.length ? samples[samples.length - 1] : {};
}

export function formatEventTime(value) {
  if (!value) return "";
  if (typeof value === "number") {
    return new Date(value * 1000).toLocaleString();
  }
  return String(value);
}

