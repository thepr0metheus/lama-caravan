// Request history modal: tables, filters, detail popup.
import { option } from "./form.js";
import { messages } from "./i18n-data.js";
import { action } from "./polling.js";
import { topology, ui } from "./state.js";
import { renderTopologyLogDetail, topologyLogSummary } from "./topology-modals.js";
import { $, api, escapeHtml, pill, toast } from "./utils.js";
import { t } from "./i18n.js";

// ── Request History modal ──────────────────────────────────────────────────
export let historyRows = [];          // finished events (Requests tab)
export let historyEventRows = [];     // all raw events (Events tab)
export let historyCurrentDate = "";
export let historyEventDateLoaded = "";  // which date we last fully loaded event rows for
export let historyTab = "requests";   // "requests" | "events"
export let historyClientFilter = "";
export let historyViaFilter = "";
export let historyStatusFilter = "";

export function openRequestHistory() {
  if (!$("requestHistoryOverlay")) {
    const div = document.createElement("div");
    div.id = "requestHistoryOverlay";
    div.className = "topology-policy-overlay history-overlay";
    div.setAttribute("hidden", "");
    div.innerHTML = `
      <div class="topology-policy-modal history-modal" role="dialog" aria-modal="true" aria-label="Request History">
        <div class="topology-card-head history-modal-head">
          <strong>Request History</strong>
          <button class="icon-action compact" type="button" id="historyCloseBtn" aria-label="Close" title="Close">×</button>
        </div>
        <div class="history-filters">
          <select id="historyDateSelect" class="history-date-select"></select>
          <input id="historyClientInput" type="text" placeholder="filter client…" class="history-filter-input">
          <select id="historyViaSelect" class="history-date-select">
            <option value="">via: all</option>
            <option value="llama">llama</option>
            <option value="cloud">cloud</option>
          </select>
          <select id="historyStatusSelect" class="history-date-select">
            <option value="">status: all</option>
            <option value="ok">OK (2xx)</option>
            <option value="error">${escapeHtml(t("historyErrorOpt"))}</option>
          </select>
        </div>
        <div id="historyTableWrap" class="history-table-wrap">
          <div class="history-loading">${escapeHtml(t("historyLoading"))}</div>
        </div>
      </div>`;
    document.body.appendChild(div);

    $("historyCloseBtn").addEventListener("click", closeRequestHistory);
    div.addEventListener("click", (e) => { if (e.target === div) closeRequestHistory(); });
    $("historyDateSelect").addEventListener("change", () => {
      historyCurrentDate = $("historyDateSelect").value;
      loadRequestHistory();
    });
    $("historyClientInput").addEventListener("input", () => {
      historyClientFilter = $("historyClientInput").value.toLowerCase();
      renderHistoryTable();
    });
    $("historyViaSelect").addEventListener("change", () => {
      historyViaFilter = $("historyViaSelect").value;
      renderHistoryTable();
    });
    $("historyStatusSelect").addEventListener("change", () => {
      historyStatusFilter = $("historyStatusSelect").value;
      renderHistoryTable();
    });
  }

  $("requestHistoryOverlay").removeAttribute("hidden");
  loadRequestHistory();
}

export function closeRequestHistory() {
  const el = $("requestHistoryOverlay");
  if (el) el.setAttribute("hidden", "");
}

export async function loadRequestHistory() {
  const wrap = $("historyTableWrap");
  if (!wrap) return;
  wrap.innerHTML = `<div class="history-loading">${escapeHtml(t("historyLoading"))}</div>`;
  try {
    const params = new URLSearchParams({ limit: 500, event: "finished" });
    if (historyCurrentDate) params.set("date", historyCurrentDate);
    const data = await api(`/api/agent-proxy-logs?${params}`);
    _syncHistoryDateSelect(data);
    historyRows = data.rows || [];
    historyClientFilter = $("historyClientInput")?.value?.toLowerCase() || "";
    renderHistoryTable();
  } catch (err) {
    if (wrap) wrap.innerHTML = `<div class="history-loading history-error">${escapeHtml(err.message)}</div>`;
  }
}

export async function loadHistoryEvents() {
  const wrap = $("historyTableWrap");
  if (!wrap) return;
  // Use cached rows if already loaded for this date
  if (historyEventDateLoaded === historyCurrentDate && historyEventRows.length) {
    renderHistoryEvents();
    return;
  }
  wrap.innerHTML = `<div class="history-loading">${escapeHtml(t("historyLoading"))}</div>`;
  try {
    const params = new URLSearchParams({ limit: 500 });
    if (historyCurrentDate) params.set("date", historyCurrentDate);
    const data = await api(`/api/agent-proxy-logs?${params}`);
    _syncHistoryDateSelect(data);
    historyEventRows = data.rows || [];
    historyEventDateLoaded = historyCurrentDate;
    renderHistoryEvents();
  } catch (err) {
    if (wrap) wrap.innerHTML = `<div class="history-loading history-error">${escapeHtml(err.message)}</div>`;
  }
}

export function _syncHistoryDateSelect(data) {
  const dateSelect = $("historyDateSelect");
  if (dateSelect && data.dates?.length) {
    const current = historyCurrentDate || data.date;
    dateSelect.innerHTML = data.dates.map((d) =>
      `<option value="${escapeHtml(d)}"${d === current ? " selected" : ""}>${escapeHtml(d)}</option>`
    ).join("");
    historyCurrentDate = current;
  }
}

export let _historyFilteredRows = []; // kept for row-click detail lookup

export function renderHistoryTable() {
  const wrap = $("historyTableWrap");
  if (!wrap) return;
  const filter = historyClientFilter;
  const rows = historyRows.filter((r) => {
    const item = r.item || {};
    if (filter) {
      const route = String(item.route || r.route || "").toLowerCase();
      const client = String(item.client || "").toLowerCase();
      if (!route.includes(filter) && !client.includes(filter)) return false;
    }
    if (historyViaFilter) {
      const via = item.upstreamType || "llama";
      if (via !== historyViaFilter) return false;
    }
    if (historyStatusFilter) {
      const st = item.status || 0;
      if (historyStatusFilter === "ok" && !(st >= 200 && st < 300)) return false;
      if (historyStatusFilter === "error" && !(st >= 400)) return false;
    }
    return true;
  });

  if (!rows.length) {
    _historyFilteredRows = [];
    wrap.innerHTML = `<div class="history-loading">${escapeHtml(filter ? "No matching requests" : "No requests found")}</div>`;
    return;
  }

  _historyFilteredRows = rows;
  const clientLabels = ui.latestSystemMonitor?.clientLabels || {};
  const now = Date.now() / 1000;

  const tableRows = rows.map((r, idx) => {
    const item = r.item || {};
    const startedAt = item.startedAt || r.time || 0;
    const ago = now - startedAt;
    const agoStr = ago < 60 ? `${Math.round(ago)}s ago`
      : ago < 3600 ? `${Math.round(ago / 60)}m ago`
      : ago < 86400 ? `${Math.round(ago / 3600)}h ago`
      : `${Math.round(ago / 86400)}d ago`;
    const timeStr = new Date(startedAt * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

    const route = item.route || r.route || "—";
    const clientRaw = item.client || "";
    const clientLabel = clientLabels[clientRaw] || "";
    const clientSub = clientLabel
      ? `<span class="history-sub">${escapeHtml(clientRaw)}</span>`
      : clientRaw ? `<span class="history-sub">${escapeHtml(clientRaw)}</span>` : "";

    const model = item.request?.model || "";
    const modelShort = model.length > 24 ? model.slice(0, 22) + "…" : model;

    const upstreamType = item.upstreamType || "llama";
    const handlerTag = upstreamType === "cloud"
      ? `<span class="history-tag history-tag-cloud">cloud</span>`
      : `<span class="history-tag history-tag-llama">llama</span>`;

    const durationMs = item.durationMs || 0;
    const durationStr = durationMs >= 60000 ? `${(durationMs / 60000).toFixed(1)}m`
      : durationMs >= 1000 ? `${(durationMs / 1000).toFixed(1)}s`
      : `${durationMs}ms`;

    const usage = item.stream?.usage || item.response?.usage || {};
    const promptTok = Number(usage.prompt_tokens || 0);
    const completionTok = Number(usage.completion_tokens || 0);
    const totalTok = promptTok + completionTok;
    const tokStr = totalTok ? String(totalTok) : "—";
    const tokTitle = totalTok ? ` title="${promptTok}p + ${completionTok}c"` : "";

    const tps = completionTok > 0 && durationMs > 100
      ? (completionTok / (durationMs / 1000)).toFixed(1)
      : null;
    const tpsStr = tps ? `${tps}` : "—";

    const status = item.status || 0;
    const statusClass = status >= 200 && status < 300 ? "history-status-ok"
      : status >= 400 ? "history-status-err" : "";
    const error = item.error || item.errorKind || "";
    const rowClass = error ? " history-row-error" : "";

    return `<tr class="history-data-row${rowClass}" data-history-row-idx="${idx}">
      <td class="history-td-time" title="${escapeHtml(new Date(startedAt * 1000).toLocaleString())}">${escapeHtml(timeStr)}<br><span class="history-sub">${escapeHtml(agoStr)}</span></td>
      <td class="history-td-client"><b>${escapeHtml(route)}</b>${clientSub}</td>
      <td class="history-td-model" title="${escapeHtml(model)}">${escapeHtml(modelShort || "—")}</td>
      <td class="history-td-handler">${handlerTag}</td>
      <td class="history-td-dur">${escapeHtml(durationStr)}</td>
      <td class="history-td-tok"${tokTitle}>${escapeHtml(tokStr)}</td>
      <td class="history-td-tps">${escapeHtml(tpsStr)}</td>
      <td class="history-td-status"><span class="${statusClass}">${escapeHtml(status ? String(status) : "—")}</span></td>
    </tr>`;
  }).join("");

  wrap.innerHTML = `
    <table class="history-table">
      <thead><tr>
        <th>Time</th><th>Client</th><th>Model</th><th>Via</th>
        <th>Duration</th><th>Tokens</th><th>TPS</th><th>Status</th>
      </tr></thead>
      <tbody>${tableRows}</tbody>
    </table>`;

  // row-click: open detail popup
  wrap.querySelector("tbody").addEventListener("click", (e) => {
    const tr = e.target.closest("[data-history-row-idx]");
    if (!tr) return;
    const idx = Number(tr.dataset.historyRowIdx);
    const row = _historyFilteredRows[idx];
    if (row) openHistoryDetailPopup(row);
  });
}

export function openHistoryDetailPopup(row) {
  let panel = $("historyDetailPanel");
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "historyDetailPanel";
    panel.className = "history-detail-overlay";
    document.body.appendChild(panel);
    panel.addEventListener("click", (e) => { if (e.target === panel) closeHistoryDetailPopup(); });
  }
  panel.innerHTML = `
    <div class="history-detail-popup">
      <div class="topology-card-head history-detail-popup-head">
        <span class="history-detail-popup-title">${escapeHtml(topologyLogSummary(row))}</span>
        <button class="icon-action compact history-curl-btn" id="historyDetailCurlBtn"
                title="Copy a diagnostics curl for this route (last errors via /api/agent-proxy-logs)">⧉ curl</button>
        <button class="icon-action compact" id="historyDetailCloseBtn" aria-label="Close" title="Close">×</button>
      </div>
      <div class="history-detail-popup-body">
        ${renderHistoryDetailFull(row)}
      </div>
    </div>`;
  panel.removeAttribute("hidden");
  panel.querySelector("#historyDetailCloseBtn").addEventListener("click", closeHistoryDetailPopup);
  panel.querySelector("#historyDetailCurlBtn").addEventListener("click", () => {
    const port = (row.item || {}).port || row.port || "";
    const day = historyCurrentDate ? `&date=${historyCurrentDate}` : "";
    const cmd = `curl '${location.origin}/api/agent-proxy-logs?port=${port}&event=finished&errors=1&slim=1&limit=20${day}'`;
    // navigator.clipboard needs a secure context; the LAN UI runs on plain
    // http, so fall back to the legacy textarea + execCommand copy.
    const legacyCopy = () => {
      const ta = document.createElement("textarea");
      ta.value = cmd;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (_) { /* fall through */ }
      ta.remove();
      toast(ok ? "curl copied" : cmd);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(cmd).then(() => toast("curl copied")).catch(legacyCopy);
    } else {
      legacyCopy();
    }
  });
}

export function closeHistoryDetailPopup() {
  const panel = $("historyDetailPanel");
  if (panel) panel.setAttribute("hidden", "");
}

export function renderHistoryDetailFull(row) {
  // Like renderTopologyLogDetail but with Raw JSON always expanded
  const item = row.item || {};
  const sections = [];

  const errBody = row.upstreamErrorBody;
  if (errBody) {
    let parsed = null;
    try { parsed = JSON.parse(errBody); } catch (_) {}
    sections.push(`<div class="log-detail-section log-detail-error">
      <div class="log-detail-label">Upstream error body</div>
      <pre class="log-detail-pre">${escapeHtml(parsed ? JSON.stringify(parsed, null, 2) : errBody)}</pre>
    </div>`);
  }

  const cm = row.cloudMeta;
  if (cm) {
    const pills = [
      cm.model ? `<span class="log-detail-pill">model: ${escapeHtml(cm.model)}</span>` : "",
      cm.toolCount != null ? `<span class="log-detail-pill">tools: ${cm.toolCount}</span>` : "",
      cm.inputCount != null ? `<span class="log-detail-pill">messages: ${cm.inputCount}</span>` : "",
    ].filter(Boolean).join("");
    if (pills) sections.push(`<div class="log-detail-section"><div class="log-detail-label">Cloud request</div><div class="log-detail-pills">${pills}</div></div>`);
  }

  const errMsg = item.error || row.error;
  if (errMsg && !errBody) {
    sections.push(`<div class="log-detail-section log-detail-error"><div class="log-detail-label">Error</div><div class="log-detail-value">${escapeHtml(errMsg)}</div></div>`);
  }

  const fields = [
    item.durationMs != null && ["Duration", `${item.durationMs} ms`],
    item.bytes != null && ["Bytes out", item.bytes],
    item.firstByteMs != null && ["First byte", `${item.firstByteMs} ms`],
    item.method && ["Method", item.method],
    item.path && ["Path", item.path],
    item.client && ["Client", item.client],
    item.upstream && ["Upstream", item.upstream],
  ].filter(Boolean);
  if (fields.length) {
    const fieldRows = fields.map(([k, v]) => `<tr><td class="log-detail-key">${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`).join("");
    sections.push(`<div class="log-detail-section"><table class="log-detail-table">${fieldRows}</table></div>`);
  }

  const st = item.stream;
  if (st && st.events) {
    const sr = [
      st.events && ["Events", st.events],
      st.deltaTextChars && ["Text chars", st.deltaTextChars],
      st.finishReasons?.length && ["Finish", st.finishReasons.join(", ")],
      st.usage?.total_tokens && ["Tokens", st.usage.total_tokens],
    ].filter(Boolean);
    if (sr.length) {
      const srRows = sr.map(([k, v]) => `<tr><td class="log-detail-key">${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`).join("");
      sections.push(`<div class="log-detail-section"><div class="log-detail-label">Stream</div><table class="log-detail-table">${srRows}</table></div>`);
    }
  }

  const q = item.queue || row.queue;
  if (q && q.queuedMs) {
    sections.push(`<div class="log-detail-section"><div class="log-detail-label">Queue</div><div class="log-detail-pills"><span class="log-detail-pill">waited: ${q.queuedMs} ms</span>${q.preempted ? `<span class="log-detail-pill">preempted: ${escapeHtml(q.preempted)}</span>` : ""}</div></div>`);
  }

  // Raw JSON always expanded (no <details> wrapper)
  sections.push(`<div class="log-detail-section"><div class="log-detail-label">Raw JSON</div><pre class="log-detail-pre">${escapeHtml(JSON.stringify(row, null, 2))}</pre></div>`);

  return `<div class="log-detail-body" style="border:none;padding:0">${sections.join("")}</div>`;
}

export function renderHistoryEvents() {
  const wrap = $("historyTableWrap");
  if (!wrap) return;
  const rows = historyEventRows;
  if (!rows.length) {
    wrap.innerHTML = `<div class="history-loading">No events found</div>`;
    return;
  }
  const items = rows.map((row) => {
    const s = row.item?.status || row.status || 0;
    const cls = s >= 400 || row.error || row.item?.error ? "failed" : "";
    return `<details class="topology-log-row history-event-row ${cls}">
      <summary>${escapeHtml(topologyLogSummary(row))}</summary>
      <div class="log-detail-body">${renderTopologyLogDetail(row)}</div>
    </details>`;
  }).join("");
  wrap.innerHTML = `<div class="history-event-list">${items}</div>`;
}
