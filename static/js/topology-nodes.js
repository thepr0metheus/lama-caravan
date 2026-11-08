// Host-centric nodes view: server cards, telemetry mounts, incidents, models bar.
import { drawTopologyCables } from "./cables.js";
import { BoardView } from "./board-view.js";
import { CARD_FOLD, CardFold } from "./card-fold.js";
import { CellEye, CellFilter, CellRow, EngineStrip, FoldSlot, ShelfLine } from "./card-rows.js";
import { CellMemory } from "./cell-memory.js";
import { CellFit, MACHINE_PICK, MachineHead, MachineMap, MachineSide } from "./machine-head.js";
import { MACHINE_PLAN } from "./machine-plan.js";
import { MACHINE_BUILD, MachineBuild } from "./machine-build.js";
import { MACHINE_MODELS } from "./machine-models.js";
import { CardPin } from "./placement.js";
import { CellSpeed } from "./cell-speed.js";
import { CELL_CHAT, CellChat } from "./cell-chat.js";
import { CELL_LOG } from "./cell-log.js";
import { CELL_SETTINGS } from "./cell-settings.js";
import { CellWindow } from "./cell-window.js";
import { runnerDeviceCaps, shortGpuName, VllmPlacement } from "./memory.js";
import { SplitMode } from "./split-mode.js";
import { ClientLlamaUpdate } from "./client-llama-update.js";
import { nodeTelemetryRowsHtml, renderTopologyIncidents, systemSamples, topologyIncidentItems } from "./charts.js";
import { badge, mbadge, modelsByPath } from "./form.js";
import { t } from "./i18n.js";
import {
  _modelBenchKey,
  fetchServerBenchIfNeeded,
  parseModelName,
  serverBenchCache,
  topologyModelIcon,
} from "./model-meta.js";
import { formatCtxTokens, formatTps } from "./polling.js";
import { SERVER_ORDER, ServerOrder } from "./server-order.js";
import {
  _deletingSlots,
  _newReservedCells,
  _reservingCells,
  _pendingCellActions,
  _stoppingCells,
  _stoppingHosts,
} from "./remote-cells.js";
import { state, topology, ui } from "./state.js";
import {
  topologyLlamaActivity,
  topologyRuntimePanelHtml,
  topologyServerGroup,
  topologyStatusPill,
} from "./topology-activity.js";
import { topologyServerUpstreamHost } from "./topology-proxies.js";
import { refreshTopology, renderTopology } from "./topology-render.js";
import { LibraryPath } from "./library-path.js";
import { ModelRating } from "./model-rating.js";
import { runnerAvailability, runnerContextField, runnerFixedVramGb, runnerRegistry, usesLlamaConfig } from "./llama-edit.js";
import { ModelCacheLine } from "./model-cache.js";
import { ModelDisk } from "./model-disk.js";
import { ModelCopy, ModelLoad } from "./model-copy.js";
import { StartStrip } from "./start-strip.js";
import { TalkCell } from "./voice-talk.js";
import { LiveCell } from "./voice-live.js";
import { PageCell } from "./cell-page.js";
import { JOB_LABELS, JOB_MARKS, cellJobs, cellRunnerId, jobsFromKinds } from "./model-jobs.js";
// The record rule lives beside the vocabulary (model-jobs.js); the card's modules import it from here.
export { cellJobs, cellRunnerId };
import { $, api, copyText, escapeHtml, toast } from "./utils.js";
import { CellDraft, CellFields } from "./cell-plan.js";

// ── Host-centric node view (Stage 3a) ────────────────────────────────────────
// Known safetensors format folder names (mirror of _ST_FORMAT_HINTS in
// rust/crates/admin/src/models/mod.rs) — used to read <Model>/<author>/<FORMAT> paths.
// NOT "ST": that is the badge the backend shows when it recognises none of
// these, never a directory anyone writes. Listing it here made the mirror
// strip a segment the backend would have kept, so the two would have disagreed
// about the model's own name. check_command_mirrors keeps the lists equal.
const _ST_FMT = new Set(["NVFP4", "MXFP4", "AWQ", "GPTQ", "AUTOROUND", "FP8",
                         "INT4", "W4A16", "BNB", "BF16", "FP16", "FP32"]);

// What a start's port is called before the scout leases one (rust/crates/admin/src/config/args.rs LlamaArgs::LEASED_PORT): a cell
// holds a port only while it runs, so the command its details preview carries the placeholder the scout fills, never a number.
const LEASED_PORT = "{{PORT}}";

// What a scout's last failed attempt died of, by its kind: the card's ⚠ and the window's log say it alike. Any other kind is a crash.
const PREV_ERROR_WORDS = { oom: "cellErrOom", exec: "cellErrExec", model: "cellErrModel", port: "cellErrPort" };

// [icon, name] of a runner, or null for one nobody names: the chip and the window's line of facts say it alike.
function runnerLabel(runnerId) {
  const known = { "llama-server": ["🦙", "llama.cpp"], "vllm": ["⚡", "vLLM"],
                  "whisper": ["🎙", "whisper"], "moonshine": ["🌙", "moonshine"],
                  "transcribe": ["📝", "transcribe.cpp"],
                  "seamless": ["🌐", "seamless"],
                  "translate": ["🔄", "nllb"],
                  "custom": ["🛠", "command"] }[runnerId];
  // A runner this table does not name speaks for itself, from the registry:
  // its icon and its name (the engine runners — 🟠 Ollama, 🟣 LM Studio).
  const row = known ? null : runnerRegistry().find((r) => r.id === runnerId && r.labelKey);
  return known || (row ? [String(row.icon || ""), t(row.labelKey)] : null);
}

// Runner identity chip shown IN the model-name row of every cell card —
// replaces the generic "chip" svg so the engine is readable at a glance.
function runnerChipHtml(runnerId) {
  const meta = runnerLabel(runnerId);
  if (!meta) return "";
  return `<span class="mbadge mbadge-cmd node-runner-chip">${escapeHtml(meta[0])} ${escapeHtml(meta[1])}</span>`;
}

//: Spelled out, not composed — see the same table in form.js.
const JOB_HOOKS = { llm: "cell-job-llm", embed: "cell-job-embed", asr: "cell-job-asr", tts: "cell-job-tts",
                    translate: "cell-job-translate",
                    "speech-translate": "cell-job-speech-translate",
                    "voice-chat": "cell-job-voice-chat",
                    "robot-policy": "cell-job-robot-policy" };

// What the cell DOES, beside the chip that says what RUNS it.
function jobChipsHtml(runnerId, cellMeta, cfg) {
  return cellJobs(runnerId, cellMeta, cfg).map((job) => {
    const key = JOB_LABELS[job];
    if (!key) return "";
    return `<span class="mbadge mbadge-job node-job-chip" data-t="${JOB_HOOKS[job]}">${
      JOB_MARKS[job] || ""} ${escapeHtml(t(key))}</span>`;
  }).join("");
}

// A cell explicitly pinned to the GPU — TTS_DEVICE/DEVICE=cuda|gpu or
// --device cuda in its ENV/COMMAND. The pin is authoritative even when the cell
// currently holds no VRAM: with an explicit pin the launcher either lands on the
// GPU or fails outright, it never quietly falls back. Measured VRAM alone is not
// enough to call a cell "CPU" — a model reads its weights off disk for the first
// 13-18s and allocates nothing on the card in that window, and the host's
// GPU→process mapping refreshes on its own beat after that.
function cellPinnedToGpu(srv) {
  const cfg = (srv && srv.slotConfig) || {};
  const envCmd = `${String(cfg.ENV || "")}\n${String(cfg.COMMAND || "")}`;
  return /(?:^|[\s;,])(?:TTS_DEVICE|DEVICE)=(?:cuda|gpu)\b|--device[=\s]+(?:cuda|gpu)\b/i.test(envCmd);
}

// Compact age for status lines: 45s / 12m / 5h / 3d.
function _ageShort(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds)));
  if (s < 90) return s + "s";
  const m = Math.floor(s / 60);
  if (m < 90) return m + "m";
  const h = Math.floor(m / 60);
  if (h < 36) return h + "h";
  return Math.floor(h / 24) + "d";
}
// What a host's banner says about its scout's silence. ONE function for the
// node builder and the board's live patcher: the same fact spelled in two
// places drifts apart, and a fix in one of them lasts a single poll tick
// (check_board_live_patch.py). The age is the controller's — time since the
// last report it received — and a record with no report at all says so rather
// than "0s ago".
export function hostAgeText(node) {
  const age = node?.ageSeconds;
  if (age === null || age === undefined || !Number.isFinite(Number(age))) return t("nodeScoutNeverReported");
  return t("nodeScoutLastReport", { ago: _ageShort(age) });
}

// The banner of a host whose scout stopped answering. It lives on the node —
// the machine — and not in the clients lane, since the scout reports the
// machine and nothing about the clients on it (docs/scout-split.md). What the
// operator can do about it is the machine's one ✕, in the node's header.
// A 1.x scout names no version. It still reports the agents on its machine,
// which the controller stopped reading — the chip says the scout is due for an
// update rather than leaving an old one to look current. The controller and a
// scout that names its version get nothing.
export function scoutOldChipHtml(node) {
  if (!node || node.role !== "host" || String(node.scoutVersion || "").trim()) return "";
  return `<span class="node-scout-old" data-t="node-scout-old" data-t-id="${escapeHtml(String(node.id || ""))}"
      title="${escapeHtml(t("nodeScoutOldTitle"))}">⚠ ${escapeHtml(t("nodeScoutOld"))}</span>`;
}

export function hostSilenceHtml(node) {
  if (!node || node.role !== "host" || node.online) return "";
  const id = escapeHtml(String(node.id || ""));
  return `
        <div class="node-scout-silent" data-t="node-scout-silent" data-t-id="${id}">
          <span>⚠ ${escapeHtml(t("nodeScoutSilent"))} · <span data-live-hostage>${escapeHtml(hostAgeText(node))}</span></span>
        </div>`;
}

// A machine's one ✕: let go of its scout — it forgets this controller and the
// machine leaves the board — or, when the scout is silent, forget the machine
// here. One button for both; its dialog says which of the two will happen.
// The controller's own node has none: it is not a scout.
export function scoutDisconnectBtnHtml(node) {
  if (!node || node.role !== "host") return "";
  const id = escapeHtml(String(node.id || ""));
  return `<button class="node-disconnect-btn" type="button" data-t="node-disconnect" data-t-id="${id}"
      data-scout-disconnect="${id}" title="${escapeHtml(t("nodeDisconnectScoutTitle"))}"
      aria-label="${escapeHtml(t("nodeDisconnectScoutTitle"))}">✕</button>`;
}

export const topologyNodesViewOn = true;  // node view is the only mode (flat list retired)
export const _collapsedNodes = new Set(
  (() => { try { return JSON.parse(localStorage.getItem("topologyCollapsedNodes") || "[]"); } catch { return []; } })()
);
export function persistCollapsedNodes() {
  localStorage.setItem("topologyCollapsedNodes", JSON.stringify([..._collapsedNodes]));
}
export function toggleNodeCollapsed(nodeId) {
  if (_collapsedNodes.has(nodeId)) _collapsedNodes.delete(nodeId);
  else _collapsedNodes.add(nodeId);
  persistCollapsedNodes();
  renderTopology();
  requestAnimationFrame(drawTopologyCables); // anchors moved (card ↔ rail)
}

export function applyNodesViewMode() {
  // Node view renders INTO the Llama Servers lane (so the Proxy column + SVG
  // cables stay intact). Here we only reflect the toggle's pressed state.
  const lane = $("topologyLlamaServers");
  if (lane) lane.classList.toggle("nodes-mode", topologyNodesViewOn);
  // Widen the servers lane over the stats column (col3+col4) in node mode.
  const lanes = document.querySelector(".topology-lanes");
  if (lanes) lanes.classList.toggle("nodes-on", topologyNodesViewOn);
}

// Tiny inline SVG sparkline from history rows [t, mem, util, power].
export function nodeSparklineSvg(history, idx, color, max) {
  const pts = (history || []).map((r) => r[idx]).filter((v) => v !== null && v !== undefined);
  if (pts.length < 2) return "";
  const w = 120, h = 28;
  const hi = max || Math.max(...pts, 1);
  const step = w / (pts.length - 1);
  const d = pts.map((v, i) => `${(i * step).toFixed(1)},${(h - (v / hi) * h).toFixed(1)}`).join(" ");
  return `<svg class="node-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${d}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
}

// VRAM a card holds for something that is NOT a fleet cell, by who holds it:
// the backend's `outside` — an engine of the machine (Ollama, LM Studio: its
// processes, as the scout names them), else the process's own name, else ""
// (nvidia-smi could not name it). Below a small floor an owner is driver or
// context overhead, not a job, and the card still reads "idle"; above it,
// "idle" was a lie: the card is busy, just not with us. A card without the
// split (a backend before it) has one unnamed owner: the whole nonFleet.
const OUTSIDE_FLOOR_MIB = 64;
export function gpuOutsideOwners(g) {
  const rows = Array.isArray(g?.outside) ? g.outside
    : (Number(g?.nonFleetUsedMiB || 0) > 0 ? [{ name: "", engine: "", mib: Number(g.nonFleetUsedMiB) }] : []);
  return rows
    .filter((r) => Number(r?.mib || 0) >= OUTSIDE_FLOOR_MIB)
    .map((r) => ({ name: String(r.name || ""), engine: String(r.engine || ""), mib: Number(r.mib) }));
}

function _outsideLabel(o) {
  return `${o.name || t("topologyGpuOutside")} · ${(o.mib / 1024).toFixed(1)} GB`;
}

// The cells of machine `n` whose processes hold card `g`, as the controller bound them (each server's gpuIndexes), in the order
// the machine lists its cells — the order they were made.
export function gpuCellsOn(n, g) {
  const index = Number(g?.index);
  return (n?.servers || []).filter((s) => (Array.isArray(s?.gpuIndexes) ? s.gpuIndexes : []).some((i) => Number(i) === index));
}

// Who holds the card, in words: the fleet's cells by name (CellName), then everyone else by name — both when both are there (the
// cells used to hide an outside job). The cells were said by their ports until a cell held a port only while it runs (2026-11-08).
// The first render and the live update both write this, so they cannot say two things.
export function gpuWhoHtml(n, g) {
  const cells = gpuCellsOn(n, g);
  const parts = cells.length
    ? [`<span class="node-gpu-ports">▶ ${cells.map((s) => escapeHtml(new CellName(s).title)).join(", ")}</span>`] : [];
  for (const o of gpuOutsideOwners(g)) {
    const hint = o.engine ? t("topologyGpuOutsideEngineHint") : t("topologyGpuOutsideHint");
    parts.push(`<span class="node-gpu-outside${o.engine ? " engine" : ""}" title="${escapeHtml(hint)}">▶ ${escapeHtml(_outsideLabel(o))}</span>`);
  }
  return parts.length ? parts.join(" ") : `<span class="topology-muted">${escapeHtml(t("topologyGpuIdle"))}</span>`;
}

// The outside owners on the VRAM bar: hatched bands laid after the fleet's
// share — the cells' own hover slices stack from zero in the order the machine
// lists its cells (remote-cells.js), so the two never cover each other. Returns [html, key]: the key lets the live update
// skip a rewrite the browser would otherwise re-serialize every tick.
export function gpuOutsideBar(g) {
  const total = Number(g?.memoryTotalMiB || 0);
  const owners = total > 0 ? gpuOutsideOwners(g) : [];
  let at = Number(g?.fleetUsedMiB || 0);
  const html = owners.map((o) => {
    const left = Math.min(100, (at / total) * 100);
    const width = Math.max(0, Math.min(100 - left, (o.mib / total) * 100));
    at += o.mib;
    return `<i class="node-vram-outside${o.engine ? " engine" : ""}" style="left:${left.toFixed(1)}%;width:${width.toFixed(1)}%" title="${escapeHtml(_outsideLabel(o))}"></i>`;
  }).join("");
  return [html, `${total}|${Number(g?.fleetUsedMiB || 0)}|${owners.map((o) => `${o.name}:${o.engine}:${o.mib}`).join(",")}`];
}

// A card's name with its maker's words apart ("NVIDIA GeForce" | "RTX 5090"): the main board's glance
// shows the model alone (topology-board.css), the machine's window the whole name.
export function gpuNameHtml(name) {
  const full = String(name || "GPU");
  const maker = (full.match(/^(NVIDIA(?:\s+GeForce)?|AMD(?:\s+Radeon)?|Intel(?:\s+Arc)?)\s+(?=\S)/i) || [""])[0];
  return maker ? `<span class="node-gpu-maker">${escapeHtml(maker)}</span>${escapeHtml(full.slice(maker.length))}` : escapeHtml(full);
}

export function nodeGpuRowHtml(node, g) {
  const used = Number(g.memoryUsedMiB || 0), total = Number(g.memoryTotalMiB || 0);
  const pct = total > 0 ? Math.min(100, Math.round((used / total) * 100)) : 0;
  const usedGb = (used / 1024).toFixed(1), totalGb = (total / 1024).toFixed(1);
  const util = g.utilizationGpuPct ?? "?", temp = g.temperatureC ?? "?", power = g.powerDrawW ?? "?";
  const [outsideBar, outsideKey] = gpuOutsideBar(g);
  return `
    <div class="node-gpu-row" data-gpu-row="${escapeHtml(`${node.id}:${g.index}`)}">
      <div class="node-gpu-head">
        <strong>GPU ${escapeHtml(String(g.index ?? "?"))}</strong>
        <span class="node-gpu-name">${gpuNameHtml(g.name)}</span>
        <span class="node-gpu-util" data-live-gpuutil>${escapeHtml(String(util))}% · ${escapeHtml(String(temp))}°C · ${escapeHtml(String(power))}W</span>
      </div>
      <div class="node-vram-bar" data-live-gpuvrambar data-vram-total="${escapeHtml(String(total))}"
           title="${usedGb} / ${totalGb} GB"><span style="width:${pct}%"></span><b class="node-vram-outsides" data-live-gpuoutside data-key="${escapeHtml(outsideKey)}">${outsideBar}</b><i class="node-vram-slice" hidden></i></div>
      <div class="node-gpu-meta">
        <span data-live-gpuvram>VRAM ${usedGb} / ${totalGb} GB</span>
        <span data-live-gpuwho>${gpuWhoHtml(node, g)}</span>
        <span data-live-gpuspark>${nodeSparklineSvg(g.history, 1, "var(--accent,#6ea8fe)", total)}</span>
      </div>
    </div>`;
}

// Engines on a machine that are not its cells — Ollama, LM Studio — as its
// scout finds them (scout 2.12+): a strip each over the machine's chips, and a
// shelf of an engine's models under the cells while its chip is pressed. None
// (an older scout, which cannot look) and [] (it looked, none) draw nothing.
// Installed-but-not-loaded models shown before "+N more installed".
const ENGINE_IDLE_SHOWN = 6;
// The caravan's shelf shows as many, then "+N more".
// Ollama's keep_alive -1 is an expiry decades away: "stays loaded".
const ENGINE_FOREVER_SEC = 365 * 86400;

// Memory as its size reads: gigabytes from one, megabytes below — an engine's
// 20 MB process written "0.0 GB" read as holding nothing. Also the sizes the
// start of an engine cell that would not fit asks about (remote-cells.js).
export function engineSizeText(bytes) {
  const n = Number(bytes);
  return n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(1)} GB` : `${Math.round(n / 1024 ** 2)} MB`;
}

// What an engine's processes hold, as its strip and the live patch write it.
export function engineRamText(e) {
  return e?.ramBytes != null ? `RAM ${engineSizeText(e.ramBytes)}` : "";
}

// What an engine holds on its machine's cards: the owners the GPU bars name
// (the controller joins nvidia-smi with the engine's processes), summed over
// the cards — LM Studio says nothing of it per model, so its card showed
// "RAM" alone while the bar said "LM Studio · 1.2 GB". "" when no card names it.
export function engineVramText(n, e) {
  const mib = (Array.isArray(n?.gpus) ? n.gpus : []).flatMap((g) => gpuOutsideOwners(g))
    .filter((o) => o.engine === e?.kind).reduce((sum, o) => sum + o.mib, 0);
  return mib > 0 ? `VRAM ${engineSizeText(mib * 1024 ** 2)}` : "";
}

// What an engine's model DOES, as the engine types it (LM Studio: llm, vlm,
// embedding) — the cells' job chip, in the same words. An engine that does not
// type its models (Ollama) draws none rather than a guessed one.
// `skip`: jobs a line leaves unsaid — a model in an engine is a chat model
// unless it says otherwise, and a chip on every line would say only that.
function engineJobChipsHtml(m, { skip = [] } = {}) {
  return jobsFromKinds(m?.type ? [m.type] : []).filter((job) => !skip.includes(job)).map((job) => `<span class="mbadge mbadge-job node-job-chip"
      data-t="node-engine-job" data-t-id="${escapeHtml(job)}">${JOB_MARKS[job] || ""} ${escapeHtml(t(JOB_LABELS[job]))}</span>`).join("");
}

// A model made a router output directly (step 2, docs/foreign-engines.md) can
// only be turned off from the board now: an engine's model is reached through
// a cell in it (2026-09-26, the operator's choice — no new outputs here; the
// controller's API still takes one). No switch on any other model.
function engineExposeBtnHtml(n, e, m) {
  if (m.remote || !m.outputId || m.exposed !== true) return "";
  return `<button class="node-engine-expose on" type="button" data-t="node-engine-expose"
      data-t-id="${escapeHtml(m.outputId)}" data-engine-expose="${escapeHtml(String(n.id))}"
      data-engine-kind="${escapeHtml(String(e.kind || ""))}" data-engine-model="${escapeHtml(m.name)}"
      data-engine-exposed="1" aria-pressed="true"
      title="${escapeHtml(t("nodeEngineUnexposeTitle"))}">⇄ ${escapeHtml(t("nodeEngineExposed"))}</button>`;
}

// What a model's line says while an act on it runs, by the act — the
// engine's own acts (step 3); a cell's load is its cell's, on its line.
const ENGINE_ACT_BUSY = { unload: "nodeEngineUnloading", delete: "nodeEngineDeleting" };
// And what it says the engine refused.
const ENGINE_ACT_FAILED = { unload: "nodeEngineUnloadFailed", delete: "nodeEngineDeleteFailed" };

// The engine's server itself (step 3г, scout 2.16+) is its strip's switch:
// on while it runs. The scout offers the one act that makes sense now — stop
// a running server, start a stopped one — and the switch does that act; with
// none on offer (an older scout, another user's service) it is off-limits and
// says why. While an act runs, "starting…" / "stopping…" beside it.
function engineLeverHtml(n, e) {
  const id = escapeHtml(`${n.id}:${e.kind}:${e.port}`);
  const controls = Array.isArray(e.controls) ? e.controls : [];
  const op = controls.includes("stop") ? "stop" : (controls.includes("start") ? "start" : "");
  const on = op ? op === "stop" : e.state === "ok";
  const knob = '<span class="fr-knob" aria-hidden="true"></span>';
  if (e.serverAction?.op) {
    const busy = escapeHtml(t(e.serverAction.op === "start" ? "nodeEngineStarting" : "nodeEngineStopping"));
    return `<button type="button" class="fr-switch" role="switch" aria-checked="${on}" disabled title="${busy}" aria-label="${busy}">${knob}</button>`
      + `<span class="node-engine-busy" data-t="node-engine-server-busy" data-t-id="${id}"><span class="topology-spinner" aria-hidden="true"></span> ${busy}</span>`;
  }
  const why = escapeHtml(op ? t(op === "start" ? "nodeEngineStartTitle" : "nodeEngineStopTitle")
    : t(e.runBy === "other" ? "nodeEngineRunByOther" : "engineServerFixed"));
  const attrs = op
    ? `data-t="${op === "start" ? "node-engine-start" : "node-engine-stop"}" data-t-id="${id}" data-engine-serve="${op}"`
      + ` data-engine-host="${escapeHtml(String(n.id))}" data-engine-kind="${escapeHtml(String(e.kind || ""))}"`
      + ` data-engine-label="${escapeHtml(String(e.label || e.kind || ""))}" data-engine-machine="${escapeHtml(String(n.name || n.id))}"`
    : "disabled";
  return `<button type="button" class="fr-switch" role="switch" aria-checked="${on}" ${attrs} title="${why}" aria-label="${why}">${knob}</button>`;
}

// Nothing is downloaded into an engine from the board (the operator's call,
// 2026-09-27): a model gets into Ollama or LM Studio by the engine's own
// means, and the strip shows what is there. A scout that still offers "pull"
// among its controls is not taken up on it.

// Where it listens: on 127.0.0.1 only — the isolation its cells rely on —
// or on the network, with its port's firewall badge, as a cell's port has.
function engineWhereHtml(e) {
  const port = escapeHtml(String(e.port));
  if (e.listen === "loopback") {
    return `<span class="node-engine-listen" title="${escapeHtml(t("nodeEngineLoopbackHint"))}">${escapeHtml(t("nodeEngineLoopback"))}</span>`
      + `<code class="es-addr">127.0.0.1:${port}</code>`;
  }
  return `<code class="es-addr">:${port}</code>${e.listen === "network" ? firewallBadge(e.firewall) : ""}`;
}

// Under the strip's first line: how the engine answered when not as it
// should, what the server refused last, in its words, that another user runs
// it (a system service — the operator's to stop), and a model it serves as a
// router output with no cell, with the switch that turns that output off.
function engineNotesHtml(n, e) {
  const bits = [];
  if (e.state === "stopped") bits.push(`<span class="node-engine-state">${escapeHtml(t("nodeEngineStopped"))}</span>`);
  else if (e.state === "auth") bits.push(`<span class="node-engine-state warn">${escapeHtml(t("nodeEngineAuth"))}</span>`);
  else if (e.state === "unreachable") bits.push(`<span class="node-engine-state err">${escapeHtml(t("nodeEngineUnreachable"))}</span>`);
  const err = e.serverError;
  if (err?.op) {
    const text = t(err.op === "start" ? "nodeEngineStartFailed" : "nodeEngineStopFailed", { error: err.error || "" });
    bits.push(`<span class="node-engine-act-error" title="${escapeHtml(err.error || "")}">⚠ ${escapeHtml(text)}</span>`);
  }
  if (e.runBy === "other") bits.push(`<span class="node-engine-note">${escapeHtml(t("nodeEngineRunByOther"))}</span>`);
  (Array.isArray(e.models) ? e.models : []).filter((m) => m && m.exposed === true && m.outputId).forEach((m) => {
    bits.push(`<span class="node-engine-note es-output">${escapeHtml(t("engineOutputNote", { model: m.name }))}</span>${engineExposeBtnHtml(n, e, m)}`);
  });
  return bits.join("");
}

// An engine's server as a strip over the machine's chips (2026-09-26, the
// operator's choice B, in place of the engine's card).
export function nodeEngineStripHtml(n, e) {
  const ram = e.ramBytes != null
    ? `<span class="node-engine-ram" data-live-engine-ram title="${escapeHtml(t("nodeEngineRamTitle"))}">${escapeHtml(engineRamText(e))}</span>` : "";
  // Always the slot, so the live patch can fill it when the engine takes the
  // card and empty it when it lets go — without rebuilding the strip.
  const vram = `<span class="node-engine-ram" data-t="node-engine-vram" data-live-engine-vram title="${escapeHtml(t("nodeEngineVramTitle"))}">${escapeHtml(engineVramText(n, e))}</span>`;
  const boot = e.autostart === true
    ? `<span class="es-boot" title="${escapeHtml(t("nodeEngineAutostart"))}">↟</span>` : "";
  return new EngineStrip({
    key: `${n.id}:${e.kind}:${e.port}`, engine: String(e.kind || ""), state: String(e.state || ""),
    label: String(e.label || e.kind || ""), version: String(e.version || ""), lever: engineLeverHtml(n, e), boot,
    memory: vram + ram, where: engineWhereHtml(e), notes: engineNotesHtml(n, e),
    title: t("nodeEngineOnDemandHint"),
  }).html();
}

function engineActErrorHtml(m) {
  const err = m.actionError;
  if (!err?.op) return "";
  const text = t(ENGINE_ACT_FAILED[err.op] || "nodeEngineUnloadFailed", { error: err.error || "" });
  return `<span class="node-engine-act-error" title="${escapeHtml(err.error || "")}">⚠ ${escapeHtml(text)}</span>`;
}

// What a model the engine holds takes, as its line's chip says it on hover:
// its video memory, the part in RAM from 64 MiB, its window, and when
// keep_alive lets it go — a clock time, which a line rebuilt only when
// something changes cannot let go stale the way "in 4 min" would.
function engineHeldBits(m) {
  const bits = [];
  if (m.vramBytes != null) bits.push(`VRAM ${engineSizeText(m.vramBytes)}`);
  if (m.memBytes != null && m.vramBytes != null && m.memBytes - m.vramBytes >= 64 * 1024 ** 2) {
    bits.push(`RAM ${engineSizeText(m.memBytes - m.vramBytes)}`);
  }
  if (m.contextLength != null) bits.push(`🪟 ${formatCtxTokens(m.contextLength)}`);
  const at = m.expiresAt ? Date.parse(m.expiresAt) : NaN;
  // Kept until unloaded: LM Studio says it (staysLoaded, scout 2.15), Ollama
  // by an expiry decades away.
  if (m.staysLoaded === true || at - Date.now() > ENGINE_FOREVER_SEC * 1000) bits.push(t("nodeEngineStaysLoaded"));
  else if (at > Date.now()) {
    bits.push(t("nodeEngineUnloadsAt", { t: new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) }));
  }
  return bits;
}

// The acts on a model with no cell: while one runs, its words instead; a
// model held outside any cell can be unloaded, one lying on the disk deleted
// where the engine offers it (Ollama) — the delete waits under the pointer.
// Loading is not among them: a model is reached through a cell, and its "+".
function shelfActsHtml(n, e, m) {
  const key = escapeHtml(`${n.id}:${e.kind}:${m.name}`);
  if (m.action?.op) {
    const busy = escapeHtml(t(ENGINE_ACT_BUSY[m.action.op] || "nodeEngineUnloading"));
    return `<span class="node-engine-busy" data-t="node-engine-busy" data-t-id="${key}"><span class="topology-spinner" aria-hidden="true"></span> ${busy}</span>`;
  }
  const controls = Array.isArray(e.controls) ? e.controls : [];
  const common = `data-engine-host="${escapeHtml(String(n.id))}" data-engine-kind="${escapeHtml(String(e.kind || ""))}"`
    + ` data-engine-label="${escapeHtml(String(e.label || e.kind || ""))}" data-engine-model="${escapeHtml(m.name)}"`;
  if (m.loaded === true && controls.includes("unload")) {
    const why = escapeHtml(t("nodeEngineUnloadTitle"));
    return `<button class="node-engine-act unload" type="button" data-t="node-engine-unload" data-t-id="${key}"`
      + ` data-engine-act="unload" ${common} title="${why}" aria-label="${why}">⏏</button>`;
  }
  if (m.loaded === false && controls.includes("delete")) {
    const why = escapeHtml(t("nodeEngineDeleteTitle"));
    return `<button class="node-engine-act delete sl-del" type="button" data-t="node-engine-delete" data-t-id="${key}"`
      + ` data-engine-act="delete" ${common}`
      + ` data-engine-machine="${escapeHtml(String(n.name || n.id))}" title="${why}" aria-label="${why}">🗑</button>`;
  }
  return "";
}

function shelfLineHtml(n, e, m) {
  const kind = String(e.kind || "");
  const key = `${n.id}:${kind}:${m.name}`;
  // One reserve at a time on a machine (remote-cells.js keeps it by the
  // machine: the cell has no id until the controller answers): a second "+"
  // before the first cell came back would make a second cell.
  const reserving = _reservingCells.has(String(n.id));
  const busyOp = m.action?.op || "";
  const reserve = reserving || busyOp ? ""
    : `data-engine-reserve="${escapeHtml(String(n.id))}" data-engine-kind="${escapeHtml(kind)}"`
      + ` data-engine-model="${escapeHtml(m.name)}"`;
  const why = reserving ? t("shelfReserveBusy")
    : busyOp ? t(ENGINE_ACT_BUSY[busyOp] || "nodeEngineUnloading") : t("shelfReserveTitle", { model: m.name });
  const held = m.loaded === true ? (m.vramBytes ?? m.memBytes ?? null) : null;
  const memory = held != null
    ? mbadge("vram", `${escapeHtml((Number(held) / 2 ** 30).toFixed(1))}G`, engineHeldBits(m).join(" · "))
    : (m.fileBytes != null && !m.remote
      ? mbadge("vram-est", `≈${escapeHtml((Number(m.fileBytes) / 2 ** 30).toFixed(1))}G`, t("vramEstChipTitle")) : "");
  const remote = m.remote
    ? `<span class="node-engine-cloud" title="${escapeHtml(t("nodeEngineCloudModelHint"))}">☁</span>` : "";
  return new ShelfLine({
    key, engine: kind, name: m.name, remote, job: engineJobChipsHtml(m, { skip: ["llm"] }), params: m.params || "",
    memory, reserve, why, acts: shelfActsHtml(n, e, m), error: engineActErrorHtml(m), loaded: m.loaded === true,
  }).html();
}

// The models an engine holds that no cell serves (2026-09-26, variant B):
// dashed lines under its server's strip, each with "+" to make one. Held outside any
// cell first (they take memory now), then a model still a router output, then
// the rest up to six and "+N more installed" — every model is still in the
// reserve dialog. An engine that is not answering has no list to show: its
// strip says why. When every model has a cell, that is said, not left blank.
export function nodeEngineShelfHtml(n, e, servers = []) {
  if (e.state !== "ok" || !Array.isArray(e.models)) return "";
  const kind = String(e.kind || "");
  const label = String(e.label || kind);
  const served = new Set(servers.filter((srv) => engineRunnerOf(srv)?.id === kind)
    .map((srv) => String(srv?.slotConfig?.ENGINE_MODEL || "").trim()));
  const free = e.models.filter((m) => m && !served.has(m.name));
  const loaded = free.filter((m) => m.loaded === true);
  const idle = free.filter((m) => m.loaded !== true);
  const outputs = idle.filter((m) => m.exposed === true);
  const rest = idle.filter((m) => m.exposed !== true);
  const shown = [...outputs, ...rest.slice(0, Math.max(0, ENGINE_IDLE_SHOWN - outputs.length))];
  const lines = [...loaded, ...shown].map((m) => shelfLineHtml(n, e, m)).join("");
  const caption = free.length
    ? `<div class="engine-shelf-caption"><span class="ncf-dot up" aria-hidden="true"></span>${escapeHtml(t("shelfCaption", { engine: label }))}`
      + `<span class="ncf-count">${free.length}</span></div>` : "";
  const more = idle.length > shown.length
    ? `<div class="node-engine-more topology-muted">${escapeHtml(t("nodeEngineMoreInstalled", { n: idle.length - shown.length }))}</div>` : "";
  const unknown = e.installedKnown === false
    ? `<div class="node-engine-state">${escapeHtml(t("nodeEngineInstalledUnknown"))}</div>` : "";
  const said = !e.models.length
    ? (e.installedKnown !== false ? `<div class="node-engine-state topology-muted">${escapeHtml(t("nodeEngineNoModels"))}</div>` : "")
    : (!free.length ? `<div class="node-engine-state topology-muted">${escapeHtml(t("shelfAllHaveCells", { engine: label }))}</div>` : "");
  const colour = CellRow.launcher(kind);
  return `<div class="engine-shelf${colour ? ` engine-${colour}` : ""}" data-t="engine-shelf" data-t-id="${escapeHtml(`${n.id}:${kind}`)}">`
    + `${caption}${lines}${more}${unknown}${said}</div>`;
}

// Every engine the machine's chips offer, as a group each (the operator's
// choice, 2026-09-26, twice): its server's strip and right under it the shelf
// of the models it holds that no cell serves — an engine's server is the
// machine's, and a model waiting for a cell is seen without looking for it. An
// engine the machine does not report, offered because a cell of the machine
// runs in it, is named so — its cells cannot start — not left as an empty space.
export function nodeEngineGroupsHtml(n, servers) {
  const reported = Array.isArray(n?.engines) ? n.engines : [];
  return offeredEngineRunners(n, servers).map((r) => {
    const e = reported.find((x) => String(x.kind || "") === r.id);
    if (e) return `<div class="node-launcher-group">${nodeEngineStripHtml(n, e)}${nodeEngineShelfHtml(n, e, servers)}</div>`;
    const colour = CellRow.launcher(r.id);
    return `<div class="node-launcher-group"><div class="engine-strip missing${colour ? ` engine-${colour}` : ""}" data-t="node-engine-missing"`
      + ` data-t-id="${escapeHtml(`${n.id}:${r.id}`)}">${escapeHtml(t("engineNotReported", { engine: t(r.labelKey || "") || r.id }))}</div></div>`;
  }).join("");
}

// The caravan's own models with no cell on this machine: the ones the cell
// editor offers — this controller's and its libraries' (state.models): any
// machine runs any of them, its scout fetches the file — less the ones a cell
// of this machine already names. Newest first. None when the list has not
// come yet; a list that came empty is said so. "+ Add model" counts them.
export function caravanModelsWithoutCell(n, servers = [], models = state.models) {
  if (!Array.isArray(models)) return null;
  const named = new Set(servers.map((srv) => String(srv?.slotConfig?.MODEL_FILE || "").trim()).filter(Boolean));
  return models.filter((m) => m && m.kind === "model" && m.path && !named.has(String(m.path)))
    .sort((a, b) => (Number(b.mtime) || 0) - (Number(a.mtime) || 0) || String(a.path).localeCompare(String(b.path)));
}

// A machine's llama.cpp build, as the caravan's strip shows it (2026-09-27:
// the operator moved it there from the machine's header): the build and its
// date, ⬆ when it is not the controller's commit, ⇪ that converges it (⏳
// while the scout builds), and ⟳ when a running cell started before the binary
// on disk was rebuilt. Nothing when the machine reports no build.
export function llamaBuildChipHtml(n) {
  // The controller's llama.cpp build is the fleet's reference: a machine on
  // another commit is "outdated", and its ⇪ converges it onto this one.
  const ctrlBuild = parseLlamaBuildVersion(state.llamaCpp?.version || "");
  const nodeVerStr = n.llamaBinaryVersion || "";
  const nodeMtime = n.llamaBinaryMtime || "";
  const nodeBuild = parseLlamaBuildVersion(nodeVerStr);
  const verLabel = nodeBuild ? `b${nodeBuild.build}` : "";
  // Build date: keep only the date part (first 10 ISO characters, no time)
  const verDate = nodeMtime ? nodeMtime.slice(0, 10) : "";
  // Outdated = different commit hash (most reliable) OR lower build number when
  // commits are unavailable. Same commit hash → in sync regardless of build number
  // (happens when one clone is shallow and the other is full). Hashes are short
  // git abbrevs whose LENGTH varies per clone (7 vs 9 chars for the same commit),
  // so equality is prefix-based — strict !== flagged in-sync fleets as outdated.
  const sameCommit = (a, b) => !!a && !!b && (a.startsWith(b) || b.startsWith(a));
  const verOutdated = nodeBuild && ctrlBuild && (
    (nodeBuild.commit && ctrlBuild.commit)
      ? !sameCommit(nodeBuild.commit, ctrlBuild.commit)
      : nodeBuild.build < ctrlBuild.build       // fallback: numeric comparison
  );
  const verChipTitle = [nodeVerStr, nodeMtime].filter(Boolean).join(" · ");
  // One-click llama.cpp update (converges the machine onto the controller's
  // commit via its scout's background job — or onto the latest release when
  // the controller has no commit, and then the words on the button say so:
  // client-llama-update.js); while the scout reports a running job the button
  // gives way to a building indicator. No button until the controller has said
  // what it runs.
  const upd = n.llamaUpdate || {};
  const update = ClientLlamaUpdate.of(state.llamaCpp);
  const updateTitle = escapeHtml(t(update.titleKey));
  const updateBtn = nodeVerStr
    ? (upd.running
      ? `<span class="llama-ver-building" title="${escapeHtml(String(upd.lastLine || ""))}">⏳ ${escapeHtml(t("clientLlamaBuilding"))}</span>`
      : update.offered
        ? `<button class="llama-ver-refresh" type="button" data-update-client-llama="${escapeHtml(String(n.id))}" title="${updateTitle}" aria-label="${updateTitle}">⇪</button>`
        : "")
    : "";
  // Stale binary: a server that started BEFORE the binary on disk was last
  // rebuilt still runs the old build — restart it to apply.
  const nodeMtimeEpoch = nodeMtime ? Date.parse(nodeMtime) / 1000 : 0;
  const staleBinary = nodeMtimeEpoch > 0 && (n.servers || []).some((s) => {
    const upSec = Number(s.uptimeSec || 0);
    return upSec > 0 && (Date.now() / 1000 - upSec) < nodeMtimeEpoch;
  });
  const staleBadge = staleBinary
    ? `<span class="llama-ver-stale" title="${escapeHtml(t("staleBinaryTitle"))}">⟳ ${escapeHtml(t("staleBinaryBadge"))}</span>`
    : "";
  return verLabel
    ? `<span class="llama-ver-chip${verOutdated ? " outdated" : ""}" title="${escapeHtml(verChipTitle)}">${escapeHtml(verLabel)}`
      + `${verDate ? `<span class="llama-ver-date"> ${escapeHtml(verDate)}</span>` : ""}${verOutdated ? " ⬆" : ""}</span>${updateBtn}${staleBadge}`
    : "";
}

// The caravan on a machine's card (2026-09-27, round 10: the operator chose
// A): its strip (its two model pages left its second line for the header of every page, 2026-10-24), under it the
// model cache's line (model-cache.js, 1.3.576: how many of the last
// models the machine's disk keeps), and then not the list of its models but one line, "+ Add
// model". It opens the new cell's settings with the model list already open; the
// cell is made on Apply — the controller names it then — and a change of mind
// leaves nothing made. A cell holds a port only while it runs, so the title names
// none (until 2026-11-07 it named the next free one). The line counts the models
// with no cell here; none at all, or none left without a cell, is said under it.
// Shut while a reserve on this machine is on its way.
export function nodeCaravanGroupHtml(n, servers = [], models = state.models) {
  const strip = nodeCaravanStripHtml(n);
  const rows = caravanModelsWithoutCell(n, servers, models);
  const id = escapeHtml(String(n.id));
  const reserving = _reservingCells.has(String(n.id));
  const why = reserving ? t("shelfReserveBusy") : t("caravanAddTitle");
  const count = rows && rows.length
    ? `<span class="caravan-add-count">${escapeHtml(t("caravanAddCount", { n: rows.length }))}</span>` : "";
  const add = `<button type="button" class="caravan-add" data-t="node-caravan-add" data-t-id="${id}"`
    + (reserving ? " disabled" : ` data-caravan-add="${id}"`) + ` title="${escapeHtml(why)}">`
    + `<span class="caravan-add-plus" aria-hidden="true">+</span><span class="caravan-add-label">${escapeHtml(t("caravanAddModel"))}</span>`
    + `${count}</button>`;
  const said = rows === null ? ""
    : !models.some((m) => m && m.kind === "model")
      ? `<div class="node-engine-state topology-muted">${escapeHtml(t("shelfCaravanNoModels"))}</div>`
      : (!rows.length ? `<div class="node-engine-state topology-muted">${escapeHtml(t("shelfCaravanAllHaveCells"))}</div>` : "");
  return `<div class="node-launcher-group">${strip}${ModelCacheLine.of(n).html()}${add}${said}</div>`;
}

// The caravan's strip on a machine: llama.cpp's build there and the update that converges it (llamaBuildChipHtml) — at the head of
// the caravan's group on the board's card, and among the engines of the machine's own page (machineSideHtml).
export function nodeCaravanStripHtml(n) {
  const build = llamaBuildChipHtml(n);
  return new EngineStrip({ key: `${n.id}:caravan`, engine: "caravan", hook: "node-caravan", state: "ok",
                           label: t("launcherCaravan"), version: build ? "llama.cpp" : "", build }).html();
}

// What the lane shows right over a machine's chips, whichever chip is pressed:
// a group for each launcher of its cells — the caravan first, then the engines.
export function nodeLaunchersHtml(n, servers, models = state.models) {
  const groups = nodeCaravanGroupHtml(n, servers, models) + nodeEngineGroupsHtml(n, servers);
  return `<div class="node-launchers">${groups}</div>`;
}

// What the machine's next boot does to its NVIDIA card, said before the reboot
// (2026-09-26: a kernel the automatic updates had installed came up without its
// signed driver, and nothing had said so). The controller draws the conclusion
// from the scout's facts (rust/crates/admin/src/domain/driver_outlook.rs); here it is only
// worded — at the head of the Compute column, where the card would be missed.
const DRIVER_NEXT_BOOT = { missing: "driverNextBootMissing", unsigned: "driverNextBootUnsigned",
                           "untrusted-key": "driverNextBootUntrusted" };

export function nodeDriverWarningsHtml(n) {
  const list = Array.isArray(n?.driverWarnings) ? n.driverWarnings : [];
  return list.map((w) => {
    let text = "";
    if (w?.kind === "nextBootNoDriver" && DRIVER_NEXT_BOOT[w.reason]) {
      const fix = w.package ? t("driverInstallPackage", { package: String(w.package) }) : t("driverInstallGeneric");
      text = `${t(DRIVER_NEXT_BOOT[w.reason], { kernel: String(w.kernel || "") })} ${fix}`;
    } else if (w?.kind === "rebootForDriver") {
      text = t("driverRebootNeeded", { installed: String(w.installed || ""), loaded: String(w.loaded || "") });
    }
    if (!text) return "";
    return `<div class="node-driver-warning" role="status" data-t="node-driver-warning"`
      + ` data-t-id="${escapeHtml(`${n.id}:${w.kind}`)}"><span aria-hidden="true">⚠</span> ${escapeHtml(text)}</div>`;
  }).join("");
}

// The handles of a machine's engine models made router outputs: their cables
// land at the machine's chips, always drawn — the shelf line that names one is
// gone while its engine does not answer.
function engineOutputAnchorsHtml(n) {
  return (Array.isArray(n?.engines) ? n.engines : []).flatMap((e) => (Array.isArray(e.models) ? e.models : [])
    .filter((m) => m && m.exposed === true && m.outputId)
    .map((m) => `<span class="topology-handle server-input engine-input" data-topology-engine-input="1"`
      + ` data-output-id="${escapeHtml(m.outputId)}" title="${escapeHtml(`${m.name} · ${e.label || e.kind}`)}"></span>`)).join("");
}

// Small firewall-access badge (icon + tooltip) for an engine's port: who reaches it, by its machine's firewall — the scout's word,
// Machine.ufw_access (1.3.656). Only an engine listens on the network now: Ollama and LM Studio bind their own address. A cell
// listens on its machine's loopback since step 7 of the owner's plan (2026-11-08), and the controller reaches it through the
// scout's door: a cell's card says nothing of its port's firewall, links no page of its own, and names no rule to run.
export function firewallBadge(fw) {
  if (!fw || !fw.state || fw.state === "unknown") return "";
  const from = (fw.allowedFrom || []).join(", ");
  const map = {
    all:        ["🌐", "Port open to all (Anywhere)"],
    open:       ["🔓", "ufw inactive — port open to all"],
    restricted: ["🔒", `Restricted: ${from} + localhost`],
    blocked:    ["⛔", "Blocked — no firewall rule allows this port"],
  };
  const [icon, tip] = map[fw.state] || ["", ""];
  if (!icon) return "";
  return `<span class="node-fw-badge fw-${escapeHtml(fw.state)}" title="${escapeHtml(tip)}">${icon}</span>`;
}

export function formatUptime(sec) {
  const s = Math.floor(sec || 0);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

// How a scout words a process's end when the log gave no reason (its
// Watchdog.how): by a signal, an exit code, or a code it cannot know. That is
// a death with no reason in the log — "Model loading failed" said of a cell
// that had served for hours.
const SCOUT_EXIT_WORDS = /^(died of SIG[A-Z0-9]+|exited \(code -?\d+\)|ended with an unknown exit code)/;

// Parse lastError string from llama-server log into a friendly human-readable message.
// Returns { friendly, hint, raw } where friendly is the short translated reason.
export function classifyLlamaError(raw, tail = "") {
  // The cause is often NOT the line the scout picked: llama.cpp says it, then ends with "exiting due
  // to model loading error", and that last line is what a card showed. The crashed run's last lines
  // (scout 2.6+) hold the cause, and a cause named outranks every guess made from the other line.
  if (String(tail || "").toLowerCase().includes("quantized v cache requires flash_attn")) {
    return { friendly: t("llamaErrKvCache"), hint: t("llamaErrKvCacheHint"), raw: raw || "" };
  }
  // MTP asked of a model that has none (a draft-mtp type with no draft file, on weights without MTP layers): llama.cpp warns
  // of it a few lines before the one it dies on, so the card named only "exiting due to model loading error" (2026-10-17, :22025).
  if (/model doesn't contain mtp layers|failed to create mtp context/i.test(`${tail || ""}\n${raw || ""}`)) {
    return { friendly: t("llamaErrMtp"), hint: t("llamaErrMtpHint"), raw: raw || "" };
  }
  // A split by rows that this llama.cpp build cannot do: "device CUDA0 does not support split buffers" stood a few lines above
  // "exiting due to model loading error", and the card said only that (2026-10-17, :22027). It was the first choice the cell
  // form made for two cards — "Tensor" was its default — on the machine with a 3090 and a 5090 (llama.cpp b1141).
  if (/does not support split buffers/i.test(`${tail || ""}\n${raw || ""}`)) {
    return { friendly: t("llamaErrSplitRow"), raw: raw || "",
             hint: t("llamaErrSplitRowHint", { group: t("splitMode"), row: t("splitRow"), layer: t("splitLayer"), tensor: t("splitTensor") }) };
  }
  // No reason at all is itself a fact worth stating. The log reader now returns
  // "" rather than blaming a harmless warning line, so a crash whose cause is
  // not in the log reaches here empty — and the card used to render red with no
  // panel, which reads as "we know something and won't say". Say "unknown" and
  // point at the log instead.
  if (!raw) return { friendly: t("llamaErrUnknown"), hint: t("llamaErrUnknownHint"), raw: "" };
  if (SCOUT_EXIT_WORDS.test(raw)) return { friendly: t("llamaErrUnknown"), hint: t("llamaErrUnknownHint"), raw };
  const r = raw.toLowerCase();
  if (r.includes("invalid ggml type") || r.includes("unsupported quantization")) {
    return { friendly: t("llamaErrUnsupportedQuant"), hint: t("llamaErrUnsupportedQuantHint"), raw };
  }
  // Corrupted / incomplete file
  if (r.includes("not within the file bounds") || r.includes("corrupted or incomplete") || r.includes("unexpected end of file")) {
    return { friendly: t("llamaErrCorrupted"), hint: t("llamaErrCorruptedHint"), raw };
  }
  // VRAM / memory OOM
  if (r.includes("out of memory") || r.includes("cudaerroromemoryallocation") || r.includes("failed to allocate") || r.includes("not enough memory")) {
    return { friendly: t("llamaErrOOM"), hint: t("llamaErrOOMHint"), raw };
  }
  // Wrong mmproj: the projector says it is not this model's
  if (r.includes("mismatch between text model") || r.includes("wrong mmproj")) {
    return { friendly: t("llamaErrMmproj"), hint: t("llamaErrMmprojHint"), raw };
  }
  // A file given as mmproj that could not be read as a vision projector at all — damaged, not a projector, or of a newer
  // kind than this llama.cpp knows. It was told as "embedding size does not match", which is a different fault (:22011,
  // whose "projector" file was a part of a speech pipeline, 2026-10-17).
  if (r.includes("failed to load clip model") || r.includes("mtmd_init_from_file")) {
    return { friendly: t("llamaErrClip"), hint: t("llamaErrClipHint"), raw };
  }
  // Model file not found
  if (r.includes("no such file") || r.includes("failed to open") || r.includes("failed to load model")) {
    return { friendly: t("llamaErrNotFound"), hint: "", raw };
  }
  // Generic
  return { friendly: t("llamaErrGeneric"), hint: "", raw };
}

// What the error block says on hover: the reason, then the last lines of the
// crashed run's log when the cell's scout sent them (scout 2.6+). No lines, no
// change.
function errorBlockTitle(s) {
  const tail = s.crash?.tail || "";
  return tail ? `${s.lastError || ""}\n\n${tail}`.trim() : s.lastError;
}

// Shared lifecycle breadcrumb bar used by real server cards and the ghost "no server" card.
// lcIdx: 0=reserved, 1=stopped, 2=starting, 3=running; -1 = all future (ghost card)
// lcActiveStep: key for CSS colour class on the active dot (stopped/error/loading/running)
// The reserved step carried the cell's :port and moved the cell to another one while it was parked, until a cell held a port only
// while it runs (2026-11-08, Papyrus caravan-scout-port-lease): no step is a port's button any more; the configured one is the cell's ⚙.
export function serverLifecycleBar(lcIdx, lcActiveStep, uptimeTxt = "", cfgAttrs = "") {
  const steps = ["reserved", "configured", "starting", "running"];
  const stepLabels = { reserved: t("lcReserved"), configured: t("lcConfigured"), starting: t("lcStarting"), running: t("lcRunning") };
  return `<div class="node-server-lc">${
    steps.map((lbl, i) => {
      const nodeState = i < lcIdx ? "done" : i === lcIdx ? "active" : "future";
      const railCls   = i > 0 ? (i <= lcIdx ? "done" : "future") : "";
      const colorKey  = i === lcIdx ? lcActiveStep : (i < lcIdx ? "done" : "future");
      // Once the "configured" step is behind us, tint it green like the AUTOSTART
      // button: pulsing while the server is still coming up (lcIdx 2 = starting),
      // solid green once running (lcIdx ≥ 3).
      const cfgLive = (i === 1 && nodeState === "done")
        ? (lcIdx < 3 ? " lc-cfg-live lc-cfg-starting" : " lc-cfg-live")
        : "";
      const label = escapeHtml(stepLabels[lbl] || lbl)
        + (i === 2 && uptimeTxt ? `<span class="lc-uptime">${escapeHtml(uptimeTxt)}</span>` : "");
      const inner = `<span class="lc-dot"></span><span class="lc-lbl">${label}</span>`;
      const node = (i === 1 && cfgAttrs)
        ? `<button class="lc-node lc-cfg-btn ${nodeState} lc-${colorKey}${cfgLive}" type="button" ${cfgAttrs} title="${escapeHtml(t("nodeConfigure"))}">${inner}</button>`
        : `<span class="lc-node ${nodeState} lc-${colorKey}${cfgLive}">${inner}</span>`;
      return `${i > 0 ? `<span class="lc-rail ${railCls}"></span>` : ""}${node}`;
    }).join("")
  }</div>`;
}

// Launch file roles — in the operator's words, not the config's field names.
function roleName(role) {
  if (role === "mmproj") return t("cellLaunchFileMmproj");
  if (role === "draft") return t("cellLaunchFileDraft");
  return t("cellLaunchFileModel");
}

function launchRoleNames(roles) {
  return roles.map(roleName).join(", ");
}

// A suffix on the chip — only when it's NOT the weights: "⇪ model re-issued"
// on a card with no further detail reads as "the model has been updated",
// and the operator goes looking for one.
function launchFilesSuffix(roles) {
  const others = roles.filter((r) => r !== "model");
  if (!others.length) return "";
  return ` · ${escapeHtml(launchRoleNames(others))}`;
}

// `fold` asks for the lane's folding: a quiet cell becomes a line whose full
// card floats open on hover (card-fold.js). Without it — the tests, the
// detail views — the card is drawn exactly as it always was.
// A machine's chips over its cells (2026-09-25): all of them, the caravan's
// own, or each engine next to it that can hold a cell — offered when there is
// a choice to make: the machine reports such an engine, or has a cell in one.
// A launcher chosen once that the machine no longer offers shows them all, so
// no list can stay narrowed to nothing with no chip to widen it.
export function nodeCellFilter(n, servers = []) {
  const launcher = (srv) => engineRunnerOf(srv)?.id || "caravan";
  const reported = Array.isArray(n?.engines) ? n.engines : [];
  const offered = offeredEngineRunners(n, servers);
  if (!offered.length) return new CellFilter({ hostId: n?.id });
  const count = (id) => servers.filter((srv) => launcher(srv) === id).length;
  const caravan = t("launcherCaravan");
  const options = [
    { id: "", label: t("cellsFilterAll"), count: servers.length, title: t("cellsFilterAllTitle") },
    { id: "caravan", label: caravan, count: count("caravan"), title: t("cellsFilterOnly", { launcher: caravan }) },
    ...offered.map((r) => {
      const e = reported.find((x) => String(x.kind || "") === r.id) || null;
      const name = String(e?.label || t(r.labelKey || "") || r.id);
      const up = e ? e.state === "ok" : null;
      const state = up === null ? "" : `\n${t(up ? "cellsFilterEngineUp" : "cellsFilterEngineDown", { engine: name })}`;
      return { id: r.id, label: name, count: count(r.id), up, title: `${t("cellsFilterOnly", { launcher: name })}${state}` };
    }),
  ];
  const want = CARD_FOLD.launcherOf(n?.id);
  return new CellFilter({ hostId: n?.id, chosen: options.some((o) => o.id === want) ? want : "", options,
                          anchors: engineOutputAnchorsHtml(n) });
}

// The engines next to a machine that can hold its cells and are offered on
// its chips: the registry's runners of engine cells (engineCell) that the
// machine reports, or that one of its cells runs in. The chips and the strips
// over the cells ask this one question.
function offeredEngineRunners(n, servers = []) {
  const reported = Array.isArray(n?.engines) ? n.engines : [];
  return runnerRegistry().filter((r) => r.engineCell === true
    && (reported.some((e) => String(e.kind || "") === r.id) || servers.some((srv) => engineRunnerOf(srv)?.id === r.id)));
}

// The runner of a cell whose model runs inside an engine next to it (Ollama,
// LM Studio; 2026-09-25) — the registry says which runners those are — or
// null for a cell the caravan runs itself. The card, the machine's CPU line
// and its chips all ask this one question.
export function engineRunnerOf(srv) {
  const id = String(srv?.slotConfig?.RUNNER || "").trim().toLowerCase();
  return id ? runnerRegistry().find((r) => r.id === id && r.engineCell === true) || null : null;
}

/**
 * What the board calls a cell, by what it runs: the model as its engine names it, the model's own name, a vLLM checkpoint's, a
 * whisper size, a moonshine language, a command line — "" for a cell that names none yet (a reserved one). The card's blocks, its
 * folded line, its window and the confirms of its start and stop take their name here, and so do the GPU and CPU rows of its
 * machine, which said a cell by its port until a cell held a port only while it runs (2026-11-08, Papyrus
 * caravan-scout-port-lease): one reading, so a row and a card cannot call one cell two names. Where nothing names it, the cell's
 * own id does (`title`), as its window is titled (cell-window.js).
 */
export class CellName {
  constructor(s = {}) {
    const cfg = s?.slotConfig || {};
    const runner = String(cfg.RUNNER || "").toLowerCase();
    this.cellId = String(s?.cellId || "");
    // A cell whose model runs inside an engine next to it: its model as the engine names it, verbatim.
    this.engine = engineRunnerOf(s);
    this.engineModel = this.engine ? String(cfg.ENGINE_MODEL || "").trim() : "";
    this.model = String(s?.model || "");
    this.parsed = parseModelName(s?.model) || {};
    // A command cell: the line it runs, without its exec.
    this.command = String(cfg.CELL_KIND || "").toLowerCase() === "command";
    this.commandText = String(cfg.COMMAND || "").replace(/^\s*exec\s+/, "").trim();
    // A vLLM cell has no MODEL_FILE — the artifact lives in VLLM_MODEL: the library's row for it, else <…>/<Model>/<author>/<FORMAT>
    // read as Model, else a bare HF repo id's last part, else its ALIAS, else the runner's own name.
    this.vllm = runner === "vllm";
    this.vllmModel = String(cfg.VLLM_MODEL || "").trim().replace(/\/+$/, "");
    this.vllmAlias = String(cfg.ALIAS || "").trim();
    this.vllmArt = this.vllmModel
      ? (state.artifacts || []).find((a) => this.vllmModel === a.path || this.vllmModel.endsWith("/" + a.path)) || null : null;
    this.vllmName = this.vllmArt?.name || "";
    this.vllmFmt = this.vllmArt?.format || "";
    if (!this.vllmName && this.vllmModel) {
      const segs = this.vllmModel.split("/").filter(Boolean);
      const last = segs[segs.length - 1] || "";
      if (_ST_FMT.has(last.toUpperCase()) && segs.length >= 3) {
        this.vllmFmt = last.toUpperCase();
        this.vllmName = segs[segs.length - 3];
      } else {
        this.vllmName = last;
      }
    }
    if (!this.vllmName) this.vllmName = this.vllmAlias || "vLLM";
    // whisper: the "model" is a faster-whisper size name; moonshine: a language code.
    this.whisper = runner === "whisper";
    this.whisperSize = String(cfg.WHISPER_MODEL || "").trim() || "large-v3";
    this.moonshine = runner === "moonshine";
    this.moonshineLang = String(cfg.MOONSHINE_MODEL || "").trim().toLowerCase() || "en";
  }

  /** The cell's name, by the precedence of the card's blocks; "" for a cell that names none. */
  get shown() {
    return this.engine ? this.engineModel : this.model ? (this.parsed.label || this.model)
      : this.vllm ? this.vllmName
        : this.whisper ? this.whisperSize
          : this.moonshine ? this.moonshineLang
            : this.command ? (this.commandText || t("commandCellFallback")) : "";
  }

  /** The name, else the cell's id: what a place that names every cell says. */
  get title() {
    return this.shown || this.cellId;
  }
}

/** How a cell is laid, by its runner — one rule for a cell of the list and the launch being built: the way CellFit lays it, its family
 *  of runners (where the rack may lay it, machine-plan.js CellMove) and how it lies on a card. An engine's own cell has none. */
export class CellWay {
  static how({ runner, engine = false, cpu = false, vllm = null, row = {} }) {
    if (engine) return "";
    if (cpu) return "ram";
    return usesLlamaConfig(runner) ? "spread" : vllm ? "asks" : row.vramPlan?.takesFree ? "free" : "card";
  }

  static family({ runner, engine = false }) {
    return engine ? "" : usesLlamaConfig(runner) ? "llama" : runner === "vllm" ? "vllm" : "pinned";
  }

  static onCard(row = {}) {
    return row.vramPlan?.takesFree ? "free" : "card";
  }
}

/** What the board's builder says of the launch being built on a machine's page (machine-build.js): a cell that is not made yet, standing
 *  under the builder's own key (MachineBuild.KEY) — it has no cellId until its Start makes it, and no port until it runs — told by the
 *  same CellFit.facts the stopped cells below are told by, from its engine's registry row, its file and its settings, so the map's
 *  drag, places, plan and Start lay it as they lay any stopped cell. It names no model of the list (`listed` empty) and is marked
 *  `virtual`: the list of models has no row for a cell that does not exist. */
export class LaunchFacts {
  static GIB = 2 ** 30;

  static of(launch, node) {
    const row = runnerRegistry().find((r) => r.id === launch.runner) || {};
    const config = MachineBuild.config(launch);
    const llama = usesLlamaConfig(launch.runner);
    const fixedGb = Number(row.vramPlan?.fixedMiB || 0) / 1024;
    const vllmAt = (cfg) => VllmPlacement.from(cfg, node.gpus || [], launch.sizeGb, {});
    const vllm = !llama && launch.runner === "vllm" ? vllmAt(config) : null;
    const how = CellWay.how({ runner: launch.runner, vllm, row });
    const bytes = fixedGb > 0 ? fixedGb * LaunchFacts.GIB : launch.sizeGb > 0 ? launch.sizeGb * LaunchFacts.GIB : null;
    return {
      host: String(node.id), key: MachineBuild.KEY, name: launch.name, window: false, group: "bench", stop: "", launch: "1",
      reason: "", crashed: 0, jobs: [], runner: t(row.labelKey || launch.runner), ctx: null, repo: "",
      model: "", quant: "", listed: "", rating: "", virtual: true,
      fit: CellFit.facts({ how, bytes, planned: fixedGb > 0, config, defaults: state.config || {}, row, vllm,
                           mode: new SplitMode(config.SPLIT_MODE).value === "tensor" ? "tensor" : "layer",
                           models: llama ? modelsByPath() : null, family: CellWay.family({ runner: launch.runner }),
                           caps: runnerDeviceCaps(launch.runner), onCard: CellWay.onCard(row),
                           asksFor: vllm ? (fields) => { const at = vllmAt({ ...config, ...fields });
                             return { asks: CellFit.asksOf(at), over: at.weightsOver, ridesGb: at.ridesGb, offloadNeededGb: at.offloadNeededGb, weightsGb: at.weightsGb / at.tp, speed: at.speed }; } : null }),
    };
  }
}

// `only`: the launcher the machine's chips narrow its cells to ("caravan" or
// an engine runner's id), "" for all — the lane decides it (nodesLaneHtml).
export function nodeServerCardHtml(node, s, { fold = false, only = "", picks = null } = {}) {
  const isStopping = _stoppingHosts.has(node.id);
  // A cell is known by its own id and by nothing else (2026-11-08): it holds a port only while it runs — its scout leases one at
  // the start (Papyrus caravan-scout-port-lease) — so its card, its line, its window, its controls (data-cell-id) and the states of
  // what is being done to it (remote-cells.js) all go by the id, and no part of the card names a port.
  const cellId = String(s.cellId || "");
  const slotHostId = node.id;
  const isDeleting = _deletingSlots.has(cellId);
  const pendingCellAction = _pendingCellActions.get(cellId) || "";
  const isCellStopping = (s.isSlot && _stoppingCells.has(cellId)) || pendingCellAction === "stop";
  const isNewReserved = _newReservedCells.has(cellId);
  // What the card calls the cell, read once (CellName): its blocks, its line, its window and its confirms say it alike.
  const named = new CellName(s);
  const shownName = named.shown;
  // What a place that must name the cell says when nothing else names it: the cell's id (its aria label, its window's title).
  const cellTitle = named.title;
  // What opens the cell's full details (openNodeServerDetail): the card's model block and the window's "⋯" alike.
  const detailAttrs = `data-node-detail="${escapeHtml(cellId)}" data-cell-id="${escapeHtml(cellId)}"`;
  // If a start was just submitted for this cell and it still shows "stopped", treat it as "starting" so the user can't accidentally
  // click Start again. The cell's own pending action says it (cellServiceAction): the machine-wide record of a pending remote start
  // went (2026-11-08) — it kept every stopped cell of its machine reading "starting", and nothing registers one any more.
  const hasPendingStart = pendingCellAction === "start";
  const rawPhase = isStopping ? "stopping" : (s.phase || (s.status && s.status.phase) || "stopped");
  const phase = (rawPhase === "stopped" && hasPendingStart) ? "starting" : rawPhase;
  const running = phase === "running";
  const isReserved = phase === "reserved";
  const isError = phase === "error";
  // Broken = the wrapper process is up and its health path answers WITH AN
  // ERROR (engine never initialised). Deliberately not lumped into isError:
  // error behaves like stopped (Start available), while a broken cell is a
  // running process — Stop must work and Start must not.
  const isBroken = phase === "broken";
  const isStopped = phase === "stopped" || isReserved || isError;  // error behaves like stopped for controls
  const isDownloading = phase === "downloading";
  const isWarming = phase === "warming";  // process up, model still loading into VRAM
  // Transient status (stopping / downloading / warming / starting) renders as a
  // compact line INSIDE the model block, replacing the chips row — the card
  // keeps its height instead of growing extra rows at the bottom.
  const _msl = (cls, inner) => `<div class="node-model-row2 model-status-line${cls ? " " + cls : ""}">${inner}</div>`;
  const _mslSpin = (stop) => `<span class="topology-spinner${stop ? " stopping-spinner" : ""}" aria-hidden="true"></span>`;
  // While a scout's watchdog brings a crashing cell back the card mostly shows
  // "loading …" — this ⚠ carries what the PREVIOUS attempt died of (hover for
  // its last lines).
  const _prevErrChip = (srv) => {
    const err = srv.status?.lastError;
    if (!err) return "";
    const kindKey = PREV_ERROR_WORDS[err.kind] || "cellErrCrash";
    const tip = `${t("cellPrevAttempt")} ${t(kindKey)}\n\n${err.tail || err.detail || ""}`.trim();
    return `<span class="msl-prev-err" title="${escapeHtml(tip)}">⚠</span>`;
  };
  // The bar of a cell on its way: at the share of its load while its scout measures one, looping while it does not.
  const _loadBar = (srv) => {
    const load = ModelLoad.now(srv);
    return load?.pct != null ? `<span class="msl-bar"><span style="width:${load.pct}%"></span></span>`
      : `<span class="msl-bar indeterminate"><span></span></span>`;
  };
  let statusRow = "";
  // The same status for the folded line (start-strip.js): the copy's own figures, or the words of the card's line while the cell
  // loads or warms up. The line carries the model's name already, so the strip leaves it out.
  let startCopy = null;
  let startLabel = "";
  let startInner = "";
  if (isDeleting) {
    statusRow = _msl("msl-stop", `${_mslSpin(true)}<span class="msl-bar indeterminate msl-bar-stop"><span></span></span><span class="msl-text">${escapeHtml(t("removingSlotLabel"))}</span>`);
  } else if (isStopping || isCellStopping) {
    statusRow = _msl("msl-stop", `${_mslSpin(true)}<span class="msl-bar indeterminate msl-bar-stop"><span></span></span><span class="msl-text">${escapeHtml(t("stoppingLabel"))}</span>`);
  } else if (isDownloading) {
    // The whole model's copy, in the pages' own gigabytes (model-copy.js): not the one file the scout is on, in decimal ones.
    const copy = ModelCopy.now(s);
    const dlLine = ModelCopy.line(copy, s.downloadingFile || t("topologyRemoteDownloading"));
    statusRow = _msl("", `<span class="msl-bar"><span style="width:${copy.pct ?? 0}%"></span></span><span class="msl-text" data-live-dl>${escapeHtml(dlLine)}</span>`);
    startCopy = copy;
    startLabel = s.downloadingFile || t("topologyRemoteDownloading");
  } else if (isWarming) {
    // "into VRAM" is a lie on a CPU cell — it loads into RAM: the words are ModelLoad.label's, read off the cell's config. While
    // its scout measures the reading (2.43), the line says how far, how fast and how long (ModelLoad), over a bar at the share;
    // the live patch moves both (topology-render.js).
    startInner = `${_mslSpin(false)}${_loadBar(s)}<span class="msl-text" data-live-load>${escapeHtml(ModelLoad.words(s, "warming"))}</span>${_prevErrChip(s)}`;
    statusRow = _msl("", startInner);
  } else if (isBroken) {
    // The diagnosis is the cell's own health body, a string.
    const bErr = String(s.status?.error || "");
    statusRow = _msl("msl-err", `<span class="msl-err-icon" aria-hidden="true">💔</span>`
      + `<span class="msl-text" data-t="cell-broken-error" data-t-id="${escapeHtml(cellId)}"`
      + ` title="${escapeHtml(bErr)}">${escapeHtml(t("failed"))}: ${escapeHtml(bErr.slice(0, 140))}${bErr.length > 140 ? "…" : ""}</span>`);
  } else if (!running && !isStopped) {
    // progressNote (from the lines the cell wrote while starting, carried by
    // its scout) says WHERE a long start currently is — vLLM downloads/compiles
    // for minutes and a bare spinner reads as a hang. Log-derived, so shown
    // as-is (same policy as error details).
    // A process that already reads its model (Strata's engine before its port listens) says how far, as a warming one does.
    startInner = `${_mslSpin(false)}${_loadBar(s)}<span class="msl-text" data-live-load>${escapeHtml(ModelLoad.words(s, phase))}</span>${_prevErrChip(s)}`;
    statusRow = _msl("", startInner);
  }
  const healthCls = running ? "running" : (isBroken ? "error" : (isStopped ? "" : "loading"));
  // Compact model block (name + quant/size/vision chips) — click to drill in.
  const parsed = named.parsed;
  const hasVision = !!s.mmproj;
  // Authoritative input modalities from the running server's /props, when known.
  const mods = s.modalities || null;
  // For configured (stopped) slot cells pull key params from slotConfig as fallback chips
  const _scfg = s.slotConfig || {};
  // ⚡ mtp: the cell drafts — a draft file its start loads, or its model's own MTP head — by the builder's rule (cell-plan.js
  // CellDraft), over the type and the file it was started with (its config's while it stands). The chip lit for any draft file
  // named, a switched-off one ("none") included, and for a model whose name says -mtp that runs no head (2026-11-07).
  const hasMtp = cellDrafts(s);
  // A speech cell's window is an AUDIO length, not a token count. Its config
  // still carries a llama CTX_SIZE it will never use, and rendering that as
  // "🪟 100k" put a confident, precise, entirely fictional number on the card.
  // The cell reports the real one on its health path, so prefer that and show
  // nothing rather than the fiction when it is unavailable.
  const _audioMs = Number((s.cellMeta || {}).maxAudioMs || 0);
  // Only llama and vLLM measure their work in tokens. Every other runner keeps
  // an inherited CTX_SIZE in its saved config that it will never read, so an
  // allow-list of token cells is the safe direction: a runner added later gets
  // no window chip until someone decides it has one, instead of silently
  // inheriting a precise, fictional "🪟 100k".
  const _runner = cellRunnerId(_scfg);
  // The allow-list moved to the runner classes on the controller and arrives
  // in state.runners; keeping a copy here is how the two came to disagree.
  const _isTokenCell = !_runner
    || !!runnerRegistry().find((r) => r.id === _runner)?.tokenContext;
  const _isSpeechCell = _audioMs > 0
    || ["transcribe", "whisper", "moonshine", "seamless"].includes(_runner);
  // A cell whose model runs inside an engine next to it (Ollama, LM Studio;
  // 2026-09-25): the registry says which runners those are, and the machine's
  // report on that engine says the rest — the model's job, the memory it
  // holds, its size. The cell's own process holds no model: it is no CPU cell.
  const engineRunner = named.engine;
  const engineModelName = named.engineModel;
  const engineRep = engineRunner
    ? (Array.isArray(node.engines) ? node.engines : []).find((e) => String(e.kind || "") === engineRunner.id) || null
    : null;
  const engineModel = engineRep && Array.isArray(engineRep.models)
    ? engineRep.models.find((m) => m && m.name === engineModelName) || null : null;
  const engineName = engineRunner ? String(engineRep?.label || t(engineRunner.labelKey || "") || engineRunner.id) : "";
  const ctxChip = _isSpeechCell
    ? (_audioMs > 0 ? mbadge("ctx", `🪟 ${Math.round(_audioMs / 1000)} s`, t("audioWindowChipTitle")) : "")
    : (s.ctxMax
        ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(s.ctxMax || 0))}`, t("topologyCtxUsageTip") || "Context window")
        : "");
  // What the weights were trained with, right after the model's name: a fact
  // about the model, not about this cell — the cell's own window is the 🪟
  // chip below, and the two differ on this fleet (131k trained, 60k served).
  // Never a substitute for 🪟: a card with no served window shows none.
  const trainedChip = (_isTokenCell && !_isSpeechCell && Number(s.ctxTrained) > 0)
    ? mbadge("trained", `🎓 ${escapeHtml(formatCtxTokens(Number(s.ctxTrained)))}`, t("trainedCtxChipTitle"))
    : "";
  const _slotCtx = _scfg[runnerContextField(_runner)];
  const slotCtxChip = (_isTokenCell && !_isSpeechCell && !s.ctxMax && _slotCtx)
    ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(Number(_slotCtx)))}`) : "";
  const _benchKey = s.model ? (_modelBenchKey(s.model) || "") : "";
  const _bdata = _benchKey ? serverBenchCache.get(_benchKey) : null;
  const _aaScore = _bdata?.scores?.aa_intelligence;
  const benchChip = _aaScore != null ? mbadge("bench", `🧠 ${_aaScore}`) : "";
  if (s.model) fetchServerBenchIfNeeded(s.model);
  // What language a translating cell WRITES. The card carried no language at
  // all, so two cells serving different languages off the same checkpoint were
  // indistinguishable — and the one fact that tells them apart is the one the
  // cell already reports. Taken from the live report first, falling back to the
  // saved config so a stopped cell still says what it is configured for.
  const _tgtLang = String((s.cellMeta || {}).targetLang || "").trim();
  const langChip = _tgtLang
    ? mbadge("it", `🌐 ${escapeHtml(_tgtLang)}`, t("targetLangChipTitle"))
    : "";
  const chips = [
    langChip,
    parsed.quant && _isTokenCell ? mbadge("quant", `🎛 ${escapeHtml(parsed.quant)}`) : "",
    parsed.size ? mbadge("size", `⚖ ${escapeHtml(parsed.size)}`) : "",
    parsed.variant && _isTokenCell ? mbadge("it", `🤖 ${escapeHtml(parsed.variant)}`) : "",
    // Prefer real /props modalities; fall back to the mmproj-presence heuristic.
    mods ? [
      mods.vision ? mbadge("vision", "👁 vision") : "",
      mods.audio ? mbadge("audio", "🎙 audio") : "",
      mods.video ? mbadge("video", "🎬 video") : "",
    ].join("") : (hasVision && _isTokenCell ? mbadge("mmproj", "📷 mmproj") : ""),
    hasMtp && _isTokenCell ? mbadge("mtp", "⚡ mtp") : "",
    ctxChip || slotCtxChip,
    benchChip,
  ].filter(Boolean).join("");
  // Schedule chip: the cell is started/stopped by a time window.
  const schedChip = (s.schedule && s.schedule.enabled)
    ? mbadge("sched", `⏱ ${escapeHtml(s.schedule.start)}–${escapeHtml(s.schedule.stop)}`,
             t("schedChipTitle"))
    : "";
  // The running process is older than the cell server the controller ships. The
  // file next to it is already current — a restart is what picks it up — so no
  // other chip on this card can show the gap. Command cells only: a llama or
  // vLLM cell runs a binary, whose staleness has its own banner.
  // The cell HAS CRASHED. systemd brings it back up, and a minute later the
  // card is "running" again — an evening with three crashes looked like
  // smooth operation (2026-09-06: Xid 8, "CUDA error: the launch timed
  // out"). The count is kept since the last MANUAL start: restart it
  // yourself and the counter resets, which is honest.
  const crash = s.crash && Number(s.crash.count) > 0 ? s.crash : null;
  const crashChip = crash
    ? mbadge("crashed", `💥 ${escapeHtml(t("cellCrashedChip", { count: String(crash.count) }))}`,
             t("cellCrashedTip", { count: String(crash.count),
                                   at: String(crash.at || "?"),
                                   reason: String(crash.reason || "?") })
               + (crash.tail ? `\n\n${crash.tail}` : ""), "cell-crashed")
    : "";
  const staleSrcChip = (s.cellMeta || {}).sourceState === "stale"
    ? mbadge("stale-src", `⇪ ${escapeHtml(t("cellSourceStaleChip"))}`,
             t("cellSourceStaleTip"), "cell-source-stale")
    : "";
  // The same ⇪ as the stale-binary chip, but about the WEIGHTS: a different
  // file sits under this name on HF now. An empty field means "not
  // checked", and it stays silent: a "matches" icon over an unchecked file
  // would be exactly the defect the watcher exists to fix.
  // The file on disk has already been swapped, but the process is still
  // running the old weights — it holds the INODE, not the name. This isn't
  // "broken", it's "restart whenever convenient", and that has to be said
  // plainly: silence here reads as "already updated".
  // A launch involves not one file but up to three: the weights, mmproj, and
  // the draft. All of them come from HF and all get re-issued, so the chip
  // speaks about ANY of them and names which one — otherwise the operator
  // goes looking for an update that isn't there.
  const launchNewer = Array.isArray(s.launchDiskNewer) ? s.launchDiskNewer : [];
  const diskNewerFiles = launchNewer.length ? launchNewer : (s.modelDiskNewer ? ["model"] : []);
  const diskNewerChip = diskNewerFiles.length
    ? mbadge("disk-newer",
             `⟳ ${escapeHtml(t("cellModelDiskNewerChip"))}${launchFilesSuffix(diskNewerFiles)}`,
             `${t("cellModelDiskNewerTip")}\n${t("cellLaunchFilesLine", { files: launchRoleNames(diskNewerFiles) })}`,
             "cell-model-disk-newer")
    : "";
  const staleRows = (Array.isArray(s.launchFresh) ? s.launchFresh : [])
    .filter((r) => r && (r.state === "size" || r.state === "date"));
  // A fallback for a source that doesn't yet report a list: the card must
  // not go blind just because that field hasn't arrived.
  const staleRoles = staleRows.length
    ? staleRows.map((r) => r.role)
    : ((s.modelFresh === "size" || s.modelFresh === "date") ? ["model"] : []);
  const staleModelChip = staleRoles.length
    ? mbadge("stale-model",
             `⇪ ${escapeHtml(t("cellModelStaleChip"))}${launchFilesSuffix(staleRoles)}`,
             `${t("cellModelStaleTip")}\n${t("cellLaunchFilesLine", {
               files: staleRows.length
                 ? staleRows.map((r) => `${roleName(r.role)} — ${r.file}`).join(", ")
                 : launchRoleNames(staleRoles),
             })}`,
             "cell-model-stale")
    : "";
  // Only a library holds this cell's files — they were moved off this disk.
  // The cell still starts, from there; the card says so and names which
  // files, instead of looking like a cell whose weights are right here.
  const libRoles = Array.isArray((s.modelStore || {}).roles) ? s.modelStore.roles : [];
  const libName = ((s.modelStore || {}).stores || []).map((x) => String((x || {}).name || "")).join(", ");
  const libraryChip = libRoles.length
    ? mbadge("lib", `📚 ${escapeHtml(libName)}${launchFilesSuffix(libRoles)}`,
             `${t("mdlInLibrary", { name: libName })}\n${t("cellLaunchFilesLine", { files: launchRoleNames(libRoles) })}`,
             "cell-model-in-library")
    : "";
  // Device chip — every non-reserved cell wears one. Runtime truth first: a
  // RUNNING cell shows its actual device (unit pids vs nvidia compute-apps;
  // command cells included). A STOPPED cell shows the CONFIGURED target —
  // pins are scanned in COMMAND *and* ENV (the Device selector writes
  // TTS_DEVICE=cpu|cuda there; empty CUDA_VISIBLE_DEVICES = hard CPU).
  const _envStr = String(_scfg.ENV || "");
  const _envCmd = `${_envStr}\n${String(_scfg.COMMAND || "")}`;
  const cfgSaysCpu = String(_scfg.N_GPU_LAYERS ?? "").trim() === "0"
    || /(?:^|[\s;,])(?:TTS_DEVICE|DEVICE)=cpu\b|--device[=\s]+cpu\b/i.test(_envCmd)
    || /(?:^|[\n,;\s])CUDA_VISIBLE_DEVICES=(?:""|'')?(?:[\n,;\s]|$)/.test(_envStr);
  const cfgSaysGpu = cellPinnedToGpu(s);
  // Device chip carries WHERE (⚡ GPU0); the memory badge carries HOW MUCH and
  // sits next to the model name — live VRAM held by the cell's processes
  // (multi-GPU sums up, the per-GPU split lives in the tooltip).
  // What its processes hold is read off its report once, by the class the live patch reads it with (cell-memory.js).
  const _measured = CellMemory.measured(s, node);
  const _gpuList = _measured.cards;
  const devGpuTxt = _gpuList.map((g) => `GPU${g.i}`).join(" · ");
  // Hovering the card lights up this cell's slice of the node's VRAM bar. The
  // bar knows only the node-wide total in use, so the card has to carry its own
  // per-GPU claim ("<gpuIndex>:<MiB>") for the hover handler to size the band.
  const _vramClaim = running
    ? _gpuList.filter((g) => g.mib > 0).map((g) => `${g.i}:${g.mib}`).join(",")
    : "";
  // An engine cell's memory is its engine's for this model: what the engine says it holds while the cell runs, split into what is on the
  // card and what is not.
  const engineLive = running && engineModel?.loaded === true;
  // A runner whose start takes a measured amount whatever the model file weighs says so in the registry: a
  // stopped cell wears that figure, not the file's size (llama.cpp-omni's GGUF is 4.7 GB, its cell takes 12.5).
  const plannedVramGb = runnerFixedVramGb(_runner);
  // One truth for the chip AND the card accent (.cpu-cell → blue instead of
  // green/amber): running with no GPU memory AND no GPU pin, or stopped with
  // CPU pinned in the config. The pin has to count — measuring VRAM alone
  // labeled a GPU-pinned cell "CPU" for the whole window before it allocates,
  // which reads as the Device setting having been ignored.
  // Stopped without a pin: llama (with offload) and vLLM are GPU by nature,
  // whisper's launcher is CUDA-first; moonshine is CPU-only by design (its ONNX
  // models have no GPU build), so it deliberately stays OUT of
  // runnerDefaultsGpu AND counts as a CPU cell even without a TTS_DEVICE=cpu
  // pin; a bare custom command resolves its device at start (VRAM probe) → "auto".
  // Strata has no CPU mode at all: its engine streams experts to a card.
  const runnerDefaultsGpu = usesLlamaConfig(_runner) || _runner === "vllm" || _runner === "whisper"
    || _runner === "transcribe" || _runner === "seamless" || !!runnerRegistry().find((r) => r.id === _runner)?.gpuOnly;
  // A runner that runs on one card says which while it stands, as a running cell does (⚡ GPU0): its pin, else card 0, where the
  // start lands (placement.js CardPin; 2026-10-27, "the 3090 seems chosen but is not shown"). seamless takes CUDA whenever it sees
  // a card (cells/seamless_server.py), so it is no "auto" either.
  const oneCardPin = runnerRegistry().find((r) => r.id === _runner)?.oneCard ? CardPin.card(_scfg.ENV) : "";
  const runnerCpuOnly = _runner === "moonshine";
  const isCpuCell = !engineRunner && ((running && !devGpuTxt && !cfgSaysGpu)
    || (!running && (cfgSaysCpu || runnerCpuOnly) && !isReserved)
    || (running && runnerCpuOnly));
  // A runner that takes its card's free memory (Strata) is expected to hold what the bench lays it at (CellFit "free"): its card's free
  // room less its reserve, while the card has its floor — the bench and the badges say one figure.
  const _runnerRow = runnerRegistry().find((r) => r.id === _runner) || {};
  const takesFree = !engineRunner && !isCpuCell && !!_runnerRow.vramPlan?.takesFree;
  const freePlace = takesFree
    ? CellFit.of(CellFit.facts({ how: "free", config: _scfg, defaults: state.config || {}, row: _runnerRow })).place(node) : null;
  // The two badges of the memory it holds (cell-memory.js): the RAM and the video memory, each measured, expected, none or not told. An engine
  // cell says what its engine says: the card's share, and what is left of the total in RAM.
  const engineVram = Number.isFinite(Number(engineModel?.vramBytes)) && engineModel?.vramBytes != null ? Number(engineModel.vramBytes) : null;
  const engineTotal = Number.isFinite(Number(engineModel?.memBytes)) && engineModel?.memBytes != null ? Number(engineModel.memBytes) : null;
  const memory = engineRunner
    ? CellMemory.of({ live: engineLive, reserved: isReserved, gpuKnown: engineVram !== null, vramBytes: engineVram, heldTitle: t("cellEngineMemTitle", { engine: engineName }),
                      ramBytes: engineVram !== null && engineTotal !== null ? Math.max(0, engineTotal - engineVram) : null })
    : CellMemory.of({ live: CellMemory.holds(phase), reserved: isReserved, cpu: isCpuCell, ..._measured,
                      plannedGb: plannedVramGb, fileBytes: Number(s.modelSizeBytes) || 0,
                      takesFree, everyCard: !!_runnerRow.vramPlan?.everyCard, freeBytes: freePlace?.verdict === "free" ? freePlace.needGb * 2 ** 30 : null });
  const memBadge = memory.html();
  // Where an engine computes is the engine's to say: its cell names the engine
  // (the runner chip) and the memory it holds, not a device of its own.
  // Where the cell computes, said once: the card's chip and the window's line of where the model is placed.
  const device = engineRunner ? null : (running && devGpuTxt)
    ? { kind: "gpu", icon: "⚡", word: devGpuTxt, tip: "" }
    : (isCpuCell
        ? { kind: "cpu", icon: "🧮", word: "CPU", tip: t("topologyCpuCellsHint") }
        : ((!running && !isReserved)
            ? ((cfgSaysGpu || runnerDefaultsGpu)
                ? { kind: "gpu", icon: "⚡", word: oneCardPin ? `GPU${oneCardPin}` : "GPU", tip: t("topologyDeviceCfgGpuHint") }
                : { kind: "dev", icon: "⚙", word: "auto", tip: t("topologyDeviceAutoHint") })
            : null));
  const deviceChip = device ? mbadge(device.kind, `${device.icon} ${escapeHtml(device.word)}`, device.tip) : "";
  // The model as the engine names it, verbatim — "google/gemma-4-e4b", not a
  // file name parsed out of it; what it is from the engine's report.
  const engineBlock = engineRunner ? `
    <div class="node-model-block" role="button" tabindex="0" data-t="cell-engine-model" data-t-id="${escapeHtml(cellId)}"
         ${detailAttrs} title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-ident">
        <strong class="node-model-name" title="${escapeHtml(engineModelName)}"><span>${escapeHtml(engineModelName)}</span></strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml(_runner, s.cellMeta, _scfg) || engineJobChipsHtml(engineModel)}${runnerChipHtml(_runner)}${memBadge}${engineModel?.params ? mbadge("size", `⚖ ${escapeHtml(engineModel.params)}`) : ""}${engineModel?.quant ? mbadge("quant", `🎛 ${escapeHtml(engineModel.quant)}`) : ""}${running && engineModel?.contextLength ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(Number(engineModel.contextLength)))}`) : ""}${schedChip}${staleSrcChip}${crashChip}</span></div>`}
    </div>` : "";
  const modelBlock = s.model ? `
    <div class="node-model-block" role="button" tabindex="0"
         ${detailAttrs} title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      ${/* The NAME owns this line. It used to share row 1 with three chips and
             was left 38-72px wide: on a 31-card board 20 names wrapped to two
             ragged lines. The name is what the operator is scanning for; the
             chips describe it and belong beneath it. The trained-context number
             stays pinned right as a fixed anchor — one thing that can run, one
             thing that never moves. */""}
      <div class="node-model-ident">
        <strong class="node-model-name" title="${escapeHtml(s.modelPath || s.model)}"><span>${escapeHtml(parsed.label || s.model)}</span></strong>${trainedChip}
      </div>
      ${/* One ordered row, always the same sequence: what it DOES, what RUNS it,
             WHERE it computes, how MUCH it takes, then the file's own facts, and
             warnings last. Two cards of the same kind now read in the same
             order, which is what makes a board scannable at all. */""}
      ${statusRow || (jobChipsHtml(_runner, s.cellMeta, _scfg) || deviceChip || memBadge || chips || schedChip || diskNewerChip || staleModelChip || libraryChip || crashChip ? `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml(_runner, s.cellMeta, _scfg)}${runnerChipHtml(_runner)}${deviceChip}${memBadge}${chips}${schedChip}${diskNewerChip}${staleModelChip}${libraryChip}${crashChip}</span></div>` : "")}
    </div>` : "";
  const emptyCellBlock = isReserved ? `
    <div class="node-model-block node-model-block-empty">
      <div class="node-model-ident">
        ${topologyModelIcon()}
        <strong class="node-model-name"><span>${escapeHtml(cellId)}</span></strong>
        <span class="node-reserved-tag">${escapeHtml(t("topologyReservedCellLabel"))}</span>${schedChip}
      </div>
      ${statusRow}
    </div>` : "";
  const isCmdCell = named.command;
  const cmdText = named.commandText;
  const commandBlock = isCmdCell ? `
    <div class="node-model-block" role="button" tabindex="0"
         ${detailAttrs} title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      ${/* A typed command is the longest text on the board and was the most
             squeezed of all; here it gets the whole line, and the rest of it
             runs past on hover. */""}
      <div class="node-model-ident">
        <strong class="node-model-name" title="${escapeHtml(cmdText)}"><span>${escapeHtml(cmdText || t("commandCellFallback"))}</span></strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml("custom", s.cellMeta, _scfg)}${runnerChipHtml("custom")}${deviceChip}${memBadge}${_scfg.HEALTH_PATH ? mbadge("cmd", `❤ ${escapeHtml(_scfg.HEALTH_PATH)}`) : ""}${schedChip}${staleSrcChip}${crashChip}</span></div>`}
    </div>` : "";
  // vLLM runner cell: no MODEL_FILE — the artifact lives in VLLM_MODEL (CellName reads it). Same
  // body layout as a llama cell: model icon + model NAME, then runner chips.
  const { vllm: isVllmCell, vllmModel, vllmArt, vllmName, vllmFmt, vllmAlias } = named;
  const vllmBlock = (isVllmCell && !s.model) ? `
    <div class="node-model-block" role="button" tabindex="0"
         ${detailAttrs} title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-ident">
        <strong class="node-model-name" title="${escapeHtml(vllmModel || vllmName)}${vllmAlias ? escapeHtml(` · served as ${vllmAlias}`) : ""}"><span>${escapeHtml(vllmName)}</span></strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml("vllm", s.cellMeta, _scfg)}${runnerChipHtml("vllm")}${deviceChip}${memBadge}${vllmFmt ? mbadge("quant", `🎛 ${escapeHtml(vllmFmt)}`) : ""}${s.vllmStats ? mbadge("cmd", `▶ ${s.vllmStats.requestsRunning}${s.vllmStats.requestsWaiting ? " ⏳" + s.vllmStats.requestsWaiting : ""}`, "running / queued requests") : ""}${s.vllmStats && s.vllmStats.genTps != null ? mbadge("bench", `${formatTps(s.vllmStats.genTps)} t/s`) : ""}${mbadge("cmd", "❤ /v1/models")}${_scfg.MAX_MODEL_LEN ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(Number(_scfg.MAX_MODEL_LEN)))}`) : ""}${schedChip}${staleSrcChip}${crashChip}</span></div>`}
    </div>` : "";
  // whisper runner cell: the "model" is a faster-whisper size name.
  const { whisper: isWhisperCell, whisperSize } = named;
  const whisperBlock = (isWhisperCell && !s.model) ? `
    <div class="node-model-block" role="button" tabindex="0"
         ${detailAttrs} title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-ident">
        <strong class="node-model-name" title="faster-whisper ${escapeHtml(whisperSize)}"><span>${escapeHtml(whisperSize)}</span></strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml("whisper", s.cellMeta, _scfg)}${runnerChipHtml("whisper")}${deviceChip}${memBadge}${mbadge("cmd", "❤ /health")}${schedChip}${staleSrcChip}${crashChip}</span></div>`}
    </div>` : "";
  // moonshine runner cell: the "model" is a language code, CPU-only.
  const { moonshine: isMoonshineCell, moonshineLang } = named;
  const moonshineBlock = (isMoonshineCell && !s.model) ? `
    <div class="node-model-block" role="button" tabindex="0"
         ${detailAttrs} title="${escapeHtml(t("topologyLlamaDetailOpen") || "Show details")}">
      <div class="node-model-ident">
        <strong class="node-model-name" title="moonshine ${escapeHtml(moonshineLang)}"><span>${escapeHtml(moonshineLang)}</span></strong>
      </div>
      ${statusRow || `<div class="node-model-row2"><span class="model-chips">${jobChipsHtml("moonshine", s.cellMeta, _scfg)}${runnerChipHtml("moonshine")}${deviceChip}${memBadge}${mbadge("cmd", "❤ /health")}${schedChip}${staleSrcChip}${crashChip}</span></div>`}
    </div>` : "";
  const bodyBlock = engineBlock || modelBlock || vllmBlock || whisperBlock || moonshineBlock || commandBlock || emptyCellBlock;
  // No model/command block to host the status (e.g. a bare stopped server) —
  // fall back to the old below-the-body progress panel.
  const progressPanel = (!bodyBlock && statusRow)
    ? `<div class="topology-runtime-panel node-progress-panel">${statusRow}</div>`
    : "";
  const isConfiguredCell = phase === "stopped" && !isReserved && !isError;
  const cardCls = [
    isStopping ? "stopping" : (isDeleting ? "deleting" : (running ? "running" : ((isError || isBroken) ? "error" : (isStopped ? (isConfiguredCell ? "configured-cell" : "stopped") : "loading")))),
    isReserved ? "reserved-cell" : "",
    isNewReserved ? "reserved-new" : "",
    isCpuCell ? "cpu-cell" : "",
    engineRunner ? `engine-cell engine-${CellRow.launcher(engineRunner.id)}` : "",
  ].filter(Boolean).join(" ");
  const pillPhase = isStopping ? "stopping" : (running ? "running" : ((isError || isBroken) ? "failed" : (phase === "stopped" ? "stopped" : (isWarming ? "warming" : "loading"))));
  // Lifecycle breadcrumb — reserved(0) → configured(1) → starting(2) → running(3)
  const lcIdx = (running || isStopping || isBroken) ? 3 : (isReserved ? 0 : (isStopped || isError ? 1 : 2));
  const lcActiveStep = isStopping ? "stopping" : ((isError || isBroken) ? "error" : (running ? "running" : (isReserved ? "reserved" : (phase === "stopped" ? "configured" : "loading"))));
  // Every cell is a scout's machine's (the controller's own went in step
  // 6.9): one card, the same for every machine. Its config lives with the
  // cell's slot, so the ▶ button opens the cell form on its machine.
  const cellHostId = slotHostId;
  // The card's own controls count a live cell's stop too, not only a slot's.
  const isCtlStopping = _stoppingCells.has(cellId) || pendingCellAction === "stop";
  const isCellBusy = isCtlStopping || !!pendingCellAction;
  // What opens the cell's form, once — the lifecycle's ⚙ adds its own hook and words; the window's buttons, theirs.
  const cfgCore = `data-node-cell-start="${escapeHtml(node.id)}" data-cell-id="${escapeHtml(cellId)}" data-node-role="${escapeHtml(node.role)}"`;
  const cfgAttrs = `data-t="cell-configure" data-t-id="${escapeHtml(cellId)}" aria-label="${escapeHtml(t("nodeConfigure"))}: ${escapeHtml(cellTitle)}" ${cfgCore}`;
  // The name the card's body shows travels with the ▶, ⏹ and ✕ attributes — the line's switch has no card around it to read the
  // name from, and a confirm that said only a port would say nothing now.
  const nameAttr = shownName ? ` data-node-cell-model="${escapeHtml(shownName)}"` : "";

  // ✕ delete — active only when reserved / stopped / error.
  const canDelete = (isReserved || phase === "stopped" || isError) && !isDeleting && !isCellBusy;
  const delWhy = canDelete ? t("nodeRemoveCell") : t("nodeCannotRemoveActive");
  const delBtn = isDeleting
    ? `<button class="node-action-btn muted" type="button" disabled title="${escapeHtml(t("removingSlotLabel"))}"><span class="topology-spinner stopping-spinner" aria-hidden="true"></span><span class="nab-lbl">${escapeHtml(t("deleteAction"))}</span></button>`
    : `<button class="node-action-btn ${canDelete ? "del" : "muted"}" type="button"
         ${canDelete ? `data-t="cell-delete" data-t-id="${escapeHtml(cellId)}" data-node-slot-del="${escapeHtml(cellId)}" data-cell-id="${escapeHtml(cellId)}"${nameAttr}` : "disabled"}
         title="${escapeHtml(delWhy)}">✕<span class="nab-lbl">${escapeHtml(t("deleteAction"))}</span></button>`;

  // ⚙ Configure — disabled only during starting / stopping / deleting. An
  // engine cell has no editor: it is made at the reserve step, engine and
  // model chosen there, and the editor's forms are the caravan's own runners'.
  const canConfigure = !engineRunner && !isDeleting && !isCellBusy && phase !== "starting";
  // No step of the bar moves the cell to another port: it has one only while it runs, the one its scout leased for that run.
  const lifecycleBar = serverLifecycleBar(lcIdx, lcActiveStep, "", canConfigure ? cfgAttrs : "");

  // ▶ start — active when stopped or error (model already configured).
  // Launches the saved slot directly; server-cell/action handles both
  // controller and client hosts (for a client it forwards to the route-agent
  // via client_llama_start). Reserved cells (no model yet) are configured via
  // the lifecycle-bar ⚙ (cfgAttrs → remote form for clients), not this button.
  const canPlay = (phase === "stopped" || isError) && !isCellBusy && !isDeleting;
  // The confirm has to know what it is starting: a command-path cell runs a
  // command, and its "model name" row holds that command line — only the
  // render knows the runner, so hand it to the click handler.
  const cellRunner = engineRunner ? engineRunner.id : isCmdCell ? "custom"
    : (String(_scfg.RUNNER || "").toLowerCase() || "llama-server");
  // What a start needs to know, once: the card's ▶ and the folded line's ▶
  // are the same start, and two copies of these attributes would drift. A
  // model in a library asks nothing more: the scout reads it where it is.
  const launchAttrs = `data-node-cell-launch="${escapeHtml(cellHostId)}" data-cell-id="${escapeHtml(cellId)}" data-node-cell-runner="${escapeHtml(cellRunner)}"${nameAttr}`;
  // Why the start is on or off, once: the card's ▶ and the line's switch say it alike.
  const playTitle = canPlay ? t("nodeStartServer") : (isReserved ? t("nodeConfigureFirst") : t("nodeNotStopped"));
  const playBtn = `<button class="node-action-btn ${canPlay ? "ok" : "muted"}" type="button"
      ${canPlay ? `data-t="cell-start" data-t-id="${escapeHtml(cellId)}" ${launchAttrs}` : "disabled"}
      title="${escapeHtml(playTitle)}">▶<span class="nab-lbl">${escapeHtml(t("start"))}</span></button>`;

  // ⏹ stop — active when starting or running; spinner while stopping
  const canStop = !isStopped && !isDeleting && !isCellBusy;
  // What a stop needs to know, once — for the same reason as launchAttrs: the
  // card's ⏹ and the line's switch are the same stop.
  const stopAttrs = `data-node-cell-stop="${escapeHtml(cellHostId)}" data-cell-id="${escapeHtml(cellId)}"${nameAttr}`;
  const stopTitle = canStop ? t("nodeStopServer") : t("nodeNotRunning");
  const stopBtn = isCtlStopping
    ? `<button class="node-action-btn muted" type="button" disabled title="${escapeHtml(t("nodeStoppingTitle"))}"><span class="topology-spinner stopping-spinner" aria-hidden="true"></span><span class="nab-lbl">${escapeHtml(t("stop"))}</span></button>`
    : `<button class="node-action-btn ${canStop ? "warn" : "muted"}" type="button"
         ${canStop ? `data-t="cell-stop" data-t-id="${escapeHtml(cellId)}" ${stopAttrs}` : "disabled"}
         title="${escapeHtml(stopTitle)}">⏹<span class="nab-lbl">${escapeHtml(t("stop"))}</span></button>`;

  // 🎙 Talk — the voice window over a running cell whose runner talks (voice-talk.js): what it can do is its
  // runner's to say; a cell that hears says so on its /props (`modalities.audio`), and not said is not yes.
  const talkBtn = new TalkCell({ cellId, name: shownName, runner: cellRunner,
                                 hears: s.modalities ? s.modalities.audio : null }).buttonHtml(running);
  // 📞 Live — a talk both ways at once over the cell's own WebSocket (voice-live.js), for a runner that says it talks live.
  const liveBtn = new LiveCell({ cellId, name: shownName, runner: cellRunner }).buttonHtml(running);
  // 🌐 Page — the page the cell serves itself, at the https address its config names (cell-page.js), for a runner
  // that says it serves one.
  const pageBtn = new PageCell({ cellId, runner: cellRunner, config: _scfg }).buttonHtml(running);

  // ↑ autostart — a scout keeps the cell's start and runs it when its machine
  // boots (2.4+; the server says whether it can, bootSupported). Three looks:
  // ok = enabled, off = disabled but CLICKABLE (it's a toggle — muted here read
  // as dead chrome), muted = genuinely unavailable (an older scout, or busy). A cell that failed to start counts as stopped here, as for
  // every other control: its autostart would bring it back at the next boot, and there was no way to take that off (2026-11-01).
  const bootSupported = !!s.bootSupported;
  const canBoot = bootSupported && (phase === "stopped" || running || isError) && !isDeleting && !isCellBusy;
  // The toggle's attributes and words, once: the card's ↥ and the window's "⋯" item are the same switch.
  const bootAttrs = canBoot
    ? `data-node-cell-boot="${escapeHtml(cellHostId)}" data-cell-id="${escapeHtml(cellId)}" data-node-cell-boot-action="${s.bootEnabled ? "disable" : "enable"}"`
    : "";
  const bootTitle = bootSupported ? (s.bootEnabled ? t("tnBootDisable") : t("tnBootEnable")) : t("tnBootUnsupported");
  const bootBtn = `<button class="node-action-btn${bootSupported && s.bootEnabled ? " ok" : (canBoot ? " off" : " muted")}" type="button"
      ${bootAttrs || "disabled"}
      title="${escapeHtml(bootTitle)}">${bootSupported && s.bootEnabled ? "↟" : "↥"}<span class="nab-lbl">${escapeHtml(t("topologyAutostart"))}</span></button>`;

  // The cable's handle. Exactly one element may carry it: cables and drops
  // find it by querySelector and read its position, and a copy inside a
  // hidden card would hand them a rectangle of zeros — a cable drawn to the
  // board's corner. While the card is folded, the line owns it.
  const anchorHtml = `<span class="topology-handle server-input ${healthCls}" data-topology-llama-input="1"
            data-cell-id="${escapeHtml(cellId)}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, node))}" title="${escapeHtml(t("tnTitleProxyUpstream"))}"></span>`;
  // What a failed cell has to say. The full card carries it at its foot; a failed cell folded into its red line
  // (card-fold.js cellFailed) shows it FIRST in its window, over the card, and the card inside leaves it out. A broken
  // cell (a live process around a dead engine) says its own health body, whole — the card's status row cuts it at 140.
  const errorBlockHtml = isError ? (() => {
    const err = classifyLlamaError(s.lastError, s.crash?.tail);
    return `<div class="topology-remote-unreachable llama-err-block" title="${escapeHtml(errorBlockTitle(s))}">
          <span class="llama-err-icon">⚠</span>
          <span class="llama-err-body">
            <span class="llama-err-friendly">${escapeHtml(err.friendly)}</span>
            ${err.hint ? `<span class="llama-err-hint">${escapeHtml(err.hint)}</span>` : ""}
            ${s.lastError ? `<span class="llama-err-raw">${escapeHtml(s.lastError)}</span>` : ""}
          </span>
        </div>`;
  })() : "";
  const brokenText = isBroken ? String(s.status?.error || "") : "";
  const brokenBlockHtml = isBroken ? `<div class="topology-remote-unreachable llama-err-block" title="${escapeHtml(brokenText)}">
          <span class="llama-err-icon">💔</span>
          <span class="llama-err-body">
            <span class="llama-err-friendly">${escapeHtml(t("failed"))}</span>
            ${brokenText ? `<span class="llama-err-raw">${escapeHtml(brokenText)}</span>` : ""}
          </span>
        </div>` : "";
  // The cell's own note and its model's (written on /models), under the card's body and in the window's overview: one place.
  const notesHtml = (() => {
    const note = (topology?.cellNotes || {})[cellId];
    // The comment on the cell's model, one for all its quants (written on /models), stands under the cell's own note. The same words on
    // both are said once, as the cell's own.
    const model = (topology?.cellModelNotes || {})[cellId];
    return (note ? `<div class="node-server-note" title="${escapeHtml(note)}">💬 ${escapeHtml(note)}</div>` : "")
      + (model && model !== note
        ? `<div class="node-server-note model" data-t="cell-model-note" data-t-id="${escapeHtml(cellId)}"`
          + ` title="${escapeHtml(t("cellModelNoteTip"))}&#10;&#10;${escapeHtml(model)}">📖 ${escapeHtml(model)}</div>` : "");
  })();
  // Where the cell's model is in the caravan's own pages — the models page on its folder, our HF page on its repository (the
  // owner, 2026-10-26: "a link to the model in our storage, and to our page on HF"), by its path in the library as its runner's
  // model field names it (LibraryPath). Only a runner whose model is picked from the library has one: whisper's is a size name,
  // a voice clone's an engine, vLLM's an id or a folder — a link made of those would be a guess. An engine's cell, a command and
  // a cell with no model have none.
  // The same path names the repository the machine's page writes on the cell's card (the owner, 2026-10-27: "on the cells
  // themselves, in small print, ISTA-DASLab and Qwen3.8-Flash-Next-GSQ-RCO-Coder-GGUF"): one reading for the link and the words.
  const linkRow = runnerRegistry().find((r) => r.id === _runner);
  const libraryRef = engineRunner || isCmdCell || isReserved || !(usesLlamaConfig(_runner) || linkRow?.sharedPicker === "source") ? null
    : new LibraryPath(_scfg[linkRow?.modelField || "MODEL_FILE"]);
  const modelLinks = libraryRef ? libraryRef.links() : {};
  const cardHtml = (anchor) => `
    <article class="node-server ${cardCls}"
             data-t="cell-card" data-t-id="${escapeHtml(cellId)}" aria-label="${escapeHtml(t("a11yCell"))} ${escapeHtml(cellTitle)}" data-topology-llama="1" data-cell-id="${escapeHtml(cellId)}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, node))}"
             ${_vramClaim ? `data-cell-node="${escapeHtml(String(node.id))}" data-cell-vram="${escapeHtml(_vramClaim)}"` : ""}>
      ${running ? '<span class="cell-beam" aria-hidden="true"></span>' : ""}
      ${anchor}
      <div class="node-ctrl-row">
        ${playBtn}${stopBtn}${bootBtn}${talkBtn}${liveBtn}${pageBtn}${delBtn}
      </div>
      ${lifecycleBar}
      ${bodyBlock
        ? (isReserved
            ? `<div class="node-server-body">${bodyBlock}${(() => `<div class="topology-runtime-panel llama ghost-slots"><div class="topology-runtime-slots-head"><strong>${escapeHtml(t("topologySlots"))} <span class="topology-muted">1</span></strong></div><div class="topology-runtime-slots slot-chips-row"><span class="slot-chip idle"></span></div></div>`)()}</div>${progressPanel}`
            : `<div class="node-server-body">${bodyBlock}${topologyRuntimePanelHtml(topologyServerGroup(s))}</div>${progressPanel}`)
        : progressPanel}
      ${notesHtml}
      ${errorBlockHtml}
    </article>`;
  // The start said in the folded line: the copy under the name, or the card's own words while the cell loads. A cell that is being
  // stopped, deleted or has failed says that its own way (the line's spinner, its red) and has no strip.
  // A start just asked for, or the scout's first "starting", already shows in the line: its switch is locked and spins. The strip is
  // for what the full card used to open for — the copy, the load, the warm-up. A cell being stopped, deleted or failed has no start
  // words to give: each of those has a status of its own above, and the branches are exclusive.
  const startingMotion = (hasPendingStart || phase === "starting") && !isDownloading && !isWarming;
  const startStrip = startingMotion ? ""
    : startCopy ? StartStrip.download(startCopy, startLabel, shownName) : StartStrip.status(startInner);
  // How settled the cell is, once — the fold and the machine's eye both ask.
  const settle = {
    phase,
    // The line can say how the start goes (the strip under it), so the full card need not open for it (card-fold.js).
    progress: !!startStrip,
    motion: isStopping || isCtlStopping || phase === "stopping" ? "stop"
      : startingMotion ? "start" : "",
    deleting: isDeleting,
    failed: isError || isBroken,
    transient: isDeleting || isStopping || isCtlStopping || !!pendingCellAction || !!statusRow,
    crashed: !!crash,
  };
  // The machine's page folds every cell whatever the board's density says: its cells are on the map and the bench, its list draws no
  // line (machine.css), and the panel opens each one's window — a cell in trouble's too, whose window says the trouble (its band, its
  // log, its overview's alerts) and whose panel says it on the page (MachinePick.panel: crashed). Until 1.3.653 a cell in
  // trouble stayed a full card there, with no window at all: a Strata cell the scout's watchdog brought back after a crash ran with
  // no way to its Talk tab (2026-10-26). On the board trouble still does not fold away.
  const foldMode = !fold ? "full" : picks ? "line" : CARD_FOLD.mode("cells", cellId, CardFold.cellFoldable(settle));
  // The machine's page shows every cell on its map or its bench and chooses one there (machine-head.js): what it draws and what its
  // panel acts with — the cell's name, its window, its start and stop, what it does, the repository its model comes from, what it
  // weighs and how its runner lays it — as this card has them, said once. The size is the one the card's memory badge expects (its runner's measured figure, else its
  // files); the way it is laid, its runner's (CellFit): a CPU cell in RAM, llama.cpp over its cards — by the cell window's own plan
  // when the library knows its model (its weights, its cache and its buffers), else by its files — vLLM by its share of each card
  // it takes (the form's rule, read off the stored config), Strata on its card's free room, any other runner on its one card; an
  // engine's cell where its engine puts it, which nobody here can say.
  // The window the cell is set to (served while it runs, the config's while parked) and the most its model was trained for: the
  // line, the window's tile and the bench of the machine's page say them alike (card-rows.js CellContext). Token cells only, as on
  // the card — a speech cell's window is a length of audio.
  const ctxSet = Number(s.ctxMax || _slotCtx) || 0;
  const ctxTrained = Number(s.ctxTrained) || 0;
  const ctxFacts = _isTokenCell && !_isSpeechCell ? { set: ctxSet, max: ctxTrained } : null;
  if (picks) {
    const heldRef = libraryRef || (vllmArt && _runner === "vllm" ? new LibraryPath(vllmArt.path) : null);
    const expected = memory.gpu?.kind === "expected" ? memory.gpu : memory.ram?.kind === "expected" ? memory.ram : null;
    // What a working cell holds is what a plan to move it must find room for, where no plan of its own says more: gigaam read "place
    // not known" on the rack with 0.6 GB measured on its card (2026-11-01).
    const held = memory.gpu?.kind === "held" ? memory.gpu : memory.ram?.kind === "held" ? memory.ram : null;
    // A checkpoint is a folder: the parked cell's file size (s.modelSizeBytes) knows only a file, the library's row knows the folder.
    const vllmWeightsGb = (Number(s.modelSizeBytes) || 0) / 2 ** 30 || Number(vllmArt?.sizeGb) || 0;
    const vllmAt = (config) => VllmPlacement.from(config, node.gpus || [], vllmWeightsGb, vllmArt || {});
    const vllm = !engineRunner && !isCpuCell && _runner === "vllm" ? vllmAt(_scfg) : null;
    const how = CellWay.how({ runner: _runner, engine: !!engineRunner, cpu: isCpuCell, vllm, row: _runnerRow });
    picks.set(cellId, {
      host: cellHostId,
      key: cellId, name: isReserved ? t("topologyReservedCellLabel") : shownName, window: foldMode !== "full",
      group: MachineMap.groupOf(MachineMap.phase(s)), stop: canStop ? stopAttrs : "", stopTitle,
      launch: canPlay ? launchAttrs : "", playTitle, reason: isError ? errorBlockTitle(s) : "",
      crashed: crash ? Number(crash.count) : 0,
      jobs: cellJobs(_runner, s.cellMeta, _scfg), runner: engineRunner ? engineName : (runnerLabel(isCmdCell ? "custom" : _runner) || [])[1] || "",
      ctx: ctxFacts, repo: libraryRef ? libraryRef.hfRepo() : "",
      // The model it runs and the owner's mark on it (topology.modelRatings, one for all its quants): its row in the list of models says them.
      // A vLLM cell names its checkpoint by a path of its machine: the library's row it found (vllmArt) says which model that is.
      model: heldRef ? heldRef.model() : "",
      quant: heldRef ? heldRef.quant() : "",
      listed: heldRef ? heldRef.listed() : "",
      rating: heldRef ? ModelRating.of(topology?.modelRatings, heldRef.model()) : "",
      fit: CellFit.facts({ how, bytes: expected ? expected.bytes : held ? held.bytes : null, planned: plannedVramGb > 0 && !isCpuCell, measured: !!held, config: _scfg,
                           defaults: state.config || {}, row: _runnerRow, vllm,
                           mode: new SplitMode(_scfg.SPLIT_MODE).value === "tensor" ? "tensor" : "layer",
                           models: !engineRunner && usesLlamaConfig(_runner) ? modelsByPath() : null,
                           family: CellWay.family({ runner: _runner, engine: !!engineRunner }),
                           caps: runnerDeviceCaps(_runner), onCard: CellWay.onCard(_runnerRow),
                           asksFor: vllm ? (fields) => { const at = vllmAt({ ..._scfg, ...fields });
                             return { asks: CellFit.asksOf(at), over: at.weightsOver, ridesGb: at.ridesGb, offloadNeededGb: at.offloadNeededGb, weightsGb: at.weightsGb / at.tp, speed: at.speed }; } : null }),
    });
  }
  // The machine's eye hides what is not running. The cell being worked on
  // stays: one just reserved, and the one whose window is open. A hidden cell
  // leaves a mark, not nothing: a cable looks for its handle, and must learn
  // the cell was put away, not lost (cables.js).
  // The machine's chips hide the cells another launcher runs, on the same
  // terms. The mark says which rule hid the cell: the eye counts only its own.
  // The machine's own page hides none: its map and its list of models show every cell,
  // and each needs its window in the page (variant В, 1.3.634).
  const kept = isNewReserved || CARD_FOLD.openKey === cellId || !!picks;
  const hiddenBy = !fold || kept ? ""
    : (only && only !== (engineRunner ? engineRunner.id : "caravan")) ? "launcher"
      : (CARD_FOLD.hidesIdle(node.id) && CardFold.cellIdle(settle)) ? "idle" : "";
  if (hiddenBy) {
    return `<span hidden data-cell-hidden="${escapeHtml(cellId)}" data-cell-hidden-by="${hiddenBy}"></span>`;
  }
  if (foldMode === "full") return cardHtml(anchorHtml);
  const failedLine = CardFold.cellFailed(settle);
  // The line breathes while the cell answers a request, and a speed it only holds is the last one: one rule (cell-speed.js), also for the live patch.
  const speed = new CellSpeed(s, running);
  // Why the switch is what it is, once: the line's switch and the window's main button say it alike.
  const switchWhy = settle.motion === "stop" ? t("nodeStoppingTitle") : settle.motion === "start" ? t("topologyRemoteStarting") : running ? stopTitle : playTitle;
  const row = new CellRow({
    cellId, name: shownName, title: s.model ? (s.modelPath || s.model) : shownName,
    // A broken cell's process is alive: its switch is ON (flipping it stops it), as red as the line.
    state: running || isBroken ? "running" : (isReserved ? "reserved" : "parked"),
    failed: failedLine, reason: failedLine ? (isError ? errorBlockTitle(s) : brokenText) : "",
    cpu: isCpuCell, engine: engineRunner ? engineRunner.id : "", chip: memBadge || deviceChip,
    launch: canPlay ? launchAttrs : "",
    stop: canStop ? stopAttrs : "", why: switchWhy,
    motion: settle.motion,
    warn: !!(staleSrcChip || staleModelChip || diskNewerChip),
    tps: speed.words(formatTps), held: speed.held, tpsHint: speed.hint(),
    busy: speed.working, anchor: anchorHtml, strip: startStrip,
    ctx: ctxFacts,
  });
  // A click on the line opens the cell's window over the board (cell-window.js — variant Г, the owner's choice of
  // 2026-10-24). It is drawn from the facts above, the ones the full card draws: the band's button and the "⋯" items carry
  // the card's own attributes, and the lane binds them where it binds the card's. The window is titled with the line's own
  // name, and names no address of the cell: a cell holds a port only while it runs, and its requests come to it through its
  // machine's model. A cell in an engine names where its requests go: the engine's loopback port, which only this cell leads to.
  const enginePort = engineRunner ? String(_scfg.ENGINE_PORT || "").trim() : "";
  const isLlamaCfg = !engineRunner && !isCmdCell && usesLlamaConfig(_runner);
  // A failed start in words, once: the band's second line and the log's entry.
  const failure = isError ? classifyLlamaError(s.lastError, s.crash?.tail) : null;
  const winState = isDeleting ? "deleting"
    : (isStopping || isCtlStopping || phase === "stopping") ? "stopping"
      : isBroken ? "broken" : isError ? "failed" : isReserved ? "reserved" : isDownloading ? "downloading"
        : isWarming ? "warming" : running ? "running" : phase === "stopped" ? "stopped" : "starting";
  // The band's second line: what the cell does now. A start, a copy, a warm-up, a stop and a broken engine say it in the
  // card's own status line (its live bar and words included); a running cell says whether it answers, by the line's rule.
  const winSub = winState === "running" ? `<span data-live-cwband>${escapeHtml(CellWindow.speedWords(speed, formatTps))}</span>`
    : winState === "stopped" ? escapeHtml(t("cwSubStopped"))
      : winState === "reserved" ? escapeHtml(t("cwSubReserved"))
        : winState === "failed" ? escapeHtml(failure.friendly)
          : statusRow;
  const jobIds = cellJobs(_runner, s.cellMeta, _scfg);
  const jobWords = jobIds.map((job) => (JOB_LABELS[job] ? t(JOB_LABELS[job]) : "")).filter(Boolean);
  const winFacts = [
    ...jobWords,
    engineRunner ? engineName : (runnerLabel(isCmdCell ? "custom" : _runner) || [])[1] || "",
    engineRunner ? String(engineModel?.quant || "") : isVllmCell ? vllmFmt : (_isTokenCell ? String(parsed.quant || "") : ""),
    engineRunner ? String(engineModel?.params || "") : String(parsed.size || ""),
    _tgtLang ? `→ ${_tgtLang}` : "",
    Number(s.modelSizeBytes) > 0 ? `${(Number(s.modelSizeBytes) / 2 ** 30).toFixed(1)} GB` : "",
  ];
  const winPlace = [
    isLlamaCfg && _scfg.SPLIT_MODE ? new SplitMode(_scfg.SPLIT_MODE).label() : "",
    device ? device.word : "",
    bootSupported ? t("cwAutostartWord", { state: t(s.bootEnabled ? "cwOn" : "cwOff") }) : "",
    s.schedule?.enabled ? `⏱ ${s.schedule.start}–${s.schedule.stop}` : "",
  ];
  // The overview's four figures: speed, window, and what the cell holds — each says "—" with the reason when it is not known. A cell
  // with no model has none of them: its overview says so in words instead of a row of dashes. Only a cell that generates tokens says a
  // speed — an embedding server returns vectors and a transcriber text from sound, neither says one; another cell gets the tile when a
  // speed did come. "No request measured yet" under them would be said for ever (an embedding cell on the live board, 2026-10-25).
  // The memory's two tiles and its cards' figures are the class's, as its badges are: the live patch writes them all again.
  const speedTile = !isReserved && ((_isTokenCell && !_isSpeechCell && !jobIds.includes("embed")) || speed.speed > 0);
  const winTiles = [
    !speedTile ? null : { id: "speed", label: t("cwTileSpeed"), value: speed.words(formatTps), live: "data-live-cwtps",
      sub: CellWindow.speedSub(speed, s.promptTps, formatTps), liveSub: "data-live-cwtpssub" },
    _isSpeechCell
      ? (_audioMs > 0 ? { id: "window", label: t("cwTileAudio"), value: `${Math.round(_audioMs / 1000)} s`, sub: t("cwAudioSub") } : null)
      : (_isTokenCell && (ctxSet || ctxTrained)
        ? { id: "context", label: t("cwTileContext"), sub: t("cwContextSub"),
            value: `${ctxSet ? formatCtxTokens(ctxSet) : "—"} / ${ctxTrained ? formatCtxTokens(ctxTrained) : "—"}` } : null),
    memory.reserved ? null : memory.tile("gpu", t("cwTileGpu")),
    memory.reserved ? null : memory.tile("ram", t("cwTileRam")),
  ].filter(Boolean);
  const cardOf = (i) => (node.gpus || []).find((g) => Number(g.index) === Number(i)) || null;
  const winCards = running ? _gpuList.map((g) => {
    const card = cardOf(g.i);
    const total = card ? Number(card.memoryTotalMiB || 0) / 1024 : 0;
    return { name: `GPU${g.i}${card?.name ? ` · ${shortGpuName(card.name)}` : ""}`, figure: CellMemory.cardFigure(g.mib),
             live: `${CellMemory.CARD_HOOK}="${escapeHtml(String(g.i))}"`, sub: total ? t("cwOfTotal", { total: total.toFixed(1) }) : "" };
  }) : [];
  const flagWord = (v) => (String(v ?? "").trim() === "" ? "" : t(String(v).trim() === "0" ? "cwOff" : "cwOn"));
  const kvWhere = String(_scfg.KV_OFFLOAD ?? "").trim();
  const placeRows = isLlamaCfg ? [
    { k: t("splitMode"), v: _scfg.SPLIT_MODE ? new SplitMode(_scfg.SPLIT_MODE).label() : "" },
    { k: t("cwRowDevice"), v: _scfg.DEVICE || "" },
    { k: t("cwRowLayers"), v: _scfg.N_GPU_LAYERS || "" },
    { k: t("cwRowFit"), v: flagWord(_scfg.FIT) },
    { k: t("cwRowFitTarget"), v: _scfg.FIT_TARGET || "" },
    { k: t("cwRowTensorSplit"), v: _scfg.TENSOR_SPLIT || "" },
    { k: t("placeKv"), v: kvWhere === "0" ? t("placeKvRam") : kvWhere === "1" ? t("placeKvCards") : "" },
    { k: t("cwRowCpuMoe"), v: _scfg.N_CPU_MOE || (String(_scfg.CPU_MOE ?? "").trim() === "1" ? t("cwAllExperts") : "") },
  ] : [];
  const settingsRows = isLlamaCfg ? [
    { k: t("cwRowContext"), v: _scfg.CTX_SIZE || "" },
    { k: t("cwRowSlots"), v: _scfg.PARALLEL || "" },
    { k: t("cwRowCache"), v: _scfg.CACHE_TYPE_K || _scfg.CACHE_TYPE_V
      ? `K ${_scfg.CACHE_TYPE_K || t("cwDefault")} · V ${_scfg.CACHE_TYPE_V || t("cwDefault")}` : "" },
    { k: t("cwRowThreads"), v: _scfg.THREADS || "" },
    { k: t("cwRowBatch"), v: _scfg.BATCH_SIZE || _scfg.UBATCH_SIZE ? `${_scfg.BATCH_SIZE || t("cwDefault")} / ${_scfg.UBATCH_SIZE || t("cwDefault")}` : "" },
    { k: t("cwRowAlias"), v: _scfg.ALIAS || "" },
  ] : [];
  // What the cell has reported going wrong, newest first: the start that failed, the engine that broke, the attempt the
  // scout's watchdog retried, the crashes since the last start by hand. Nothing reported is said so, not drawn as calm.
  const prevErr = s.status?.lastError || null;
  const winLog = [
    failure ? { tone: "bad", title: t("cwLogFailed"), detail: failure.friendly, hint: failure.hint || "", raw: String(s.lastError || "") } : null,
    isBroken ? { tone: "bad", title: t("cwStateBroken"), detail: "", raw: brokenText } : null,
    prevErr ? { tone: "bad", title: t("cellPrevAttempt"), detail: t(PREV_ERROR_WORDS[prevErr.kind] || "cellErrCrash"),
                raw: String(prevErr.tail || prevErr.detail || "") } : null,
    crash ? { tone: "bad", title: t("cellCrashedChip", { count: String(crash.count) }),
              detail: t("cwCrashDetail", { at: String(crash.at || "?"), reason: String(crash.reason || "?") }), raw: String(crash.tail || "") } : null,
  ].filter(Boolean);
  // A chat cell is asked in text from the Talk tab (cell-chat.js): its runner answers text-chat and its job is a chat. Until
  // 2026-11-08 llama.cpp's own page stood beside it, a link to the port the run leased: a cell listens on its machine's loopback
  // now, and a browser has no way to that port (the controller reaches the cell through its machine's scout).
  const talkSpec = runnerRegistry().find((r) => r.id === cellRunner)?.talk || null;
  // A llama.cpp cell's settings are edited in its window while they may be changed (cell-settings.js): the fields in the
  // Settings tab, the map in the Memory tab, what is not applied at the foot. A cell with no model has none yet: its model is
  // picked first, in the dialog. A cell whose process serves keeps the settings it started with until it restarts — the
  // dialog's own rule (memory.js cellHolds) — and the foot says so.
  const editsHere = isLlamaCfg && canConfigure && !isReserved;
  const cellSettings = { llama: isLlamaCfg, editable: canConfigure && !isReserved };
  const cellWindow = new CellWindow({
    key: cellId, name: row.shownName(),
    via: enginePort ? `127.0.0.1:${enginePort}` : "",
    viaTitle: enginePort ? t("cellWindowViaTitle", { engine: engineName }) : "",
    engine: engineRunner ? engineRunner.id : "", tab: CARD_FOLD.windowTab(cellId),
    facts: winFacts, place: winPlace, state: winState, sub: winSub,
    actions: { start: canPlay ? launchAttrs : "", stop: canStop ? stopAttrs : "", configure: canConfigure ? cfgCore : "", why: switchWhy },
    menu: { boot: { attrs: bootAttrs, on: !!s.bootEnabled, supported: bootSupported, title: bootTitle },
            detail: detailAttrs,
            del: canDelete ? `data-node-slot-del="${escapeHtml(cellId)}" data-cell-id="${escapeHtml(cellId)}"${nameAttr}` : "",
            delTitle: delWhy },
    overview: { notice: isError ? errorBlockHtml : isBroken ? brokenBlockHtml : "", tiles: winTiles,
                alerts: `${diskNewerChip}${staleModelChip}${staleSrcChip}${libraryChip}${crashChip}${schedChip}`,
                notes: notesHtml, links: modelLinks, slots: running ? topologyRuntimePanelHtml(topologyServerGroup(s)) : "",
                empty: isReserved ? t("cwOverviewNoModel") : "" },
    memory: { badges: `${memBadge}${deviceChip}`, cards: winCards, rows: placeRows, configure: canConfigure ? cfgCore : "",
              place: CELL_SETTINGS.placeHtml(cellId, cellSettings) },
    settings: { rows: settingsRows, configure: canConfigure ? cfgCore : "", detail: detailAttrs,
                editor: CELL_SETTINGS.html(cellId, cellSettings) },
    foot: editsHere ? CELL_SETTINGS.footHtml(cellId, { running: running || isWarming }) : "", footSlot: editsHere,
    running: running || isWarming,
    log: winLog, talk: `${talkBtn}${liveBtn}${pageBtn}`,
    // The server's own log, read from its machine (cell-log.js): not for a cell with no model, nor for a cell in an engine,
    // whose model's log is the engine's.
    logTail: isReserved || engineRunner ? "" : CELL_LOG.html(cellId, { live: running }),
    chat: CellChat.offered(talkSpec, jobIds)
      // The talk is held with the cell's model (cell-chat.js heldWith): a cell in an engine names it only in its config — its
      // record's model and path are empty, and its talk outlived the cell on the port (live check, 2026-10-26).
      ? CELL_CHAT.html(cellId, { running, carried: talkSpec.turns, format: formatTps,
                                 model: s.modelPath || s.model || engineModelName || "" })
      : "",
  });
  return new FoldSlot({ key: cellId, lane: "cells", mode: "line", line: row.html(), card: cellWindow.html(),
                        open: CARD_FOLD.openKey === cellId }).html();
}

// Whether a cell drafts (cell-plan.js CellDraft.drafts) by the type and the draft file it started with — its config's while it
// stands — so the card's ⚡ mtp and its window's say what its command says. A face: the rule is CellDraft's.
function cellDrafts(s) {
  return CellDraft.drafts(CellFields.ofConfig({ ...(s.slotConfig || {}), SPEC_TYPE: s.specType ?? "" }), s.specDraft ?? "");
}

// Drill-in detail modal for a node server (full info that the compact card omits), of cell `cellId` — found by its id alone,
// which is unique across the fleet: a cell holds a port only while it runs. It names no address of the cell for the same reason:
// the address with the port of a run is no address of the cell, and its requests come to it through its machine's model.
export function openNodeServerDetail(cellId) {
  const id = String(cellId || "");
  const node = id ? (topology?.nodes || []).find((n) => (n.servers || []).some((x) => String(x.cellId || "") === id)) : null;
  const s = node ? (node.servers || []).find((x) => String(x.cellId || "") === id) : null;
  if (!s) return;
  document.getElementById("nodeServerDetailOverlay")?.remove();
  const phase = s.phase || (s.status && s.status.phase) || "stopped";
  const running = phase === "running";
  const parsed = parseModelName(s.model) || {};
  const activity = running ? (topologyLlamaActivity(id) || {}) : {};
  const hasMtp = cellDrafts(s);
  const _scfg = s.slotConfig || {};
  // ONE lookup, from the registry the backend derives from the runner classes.
  // This modal used to enumerate five runners by hand and draw everything else
  // as llama-server: a translate cell showed `llama-server --model … --ctx-size
  // 100000 --spec-type draft-mtp`, a command it has never run, plus a 🪟 100k
  // window for a translator that has no context window. Confidently wrong, and
  // nothing about it looked broken.
  const _runnerId = cellRunnerId(_scfg);
  const _runnerRow = runnerRegistry().find((r) => r.id === _runnerId) || null;
  const isCmd = _runnerId === "custom";
  const isLlama = usesLlamaConfig(_runnerId);
  // CTX_SIZE is inherited by every cell config, including the ones that will
  // never read it. Only a runner that says its work is measured in tokens gets
  // the chip; an unknown runner says nothing, so it gets none.
  const _hasCtx = !!(_runnerRow ? _runnerRow.tokenContext : isLlama);
  const nsdCtxChip = !_hasCtx ? ""
    : s.ctxMax
    ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(s.ctxMax))}`, t("topologyCtxUsageTip") || "Context window")
    : (_scfg[runnerContextField(_runnerId)]
        ? mbadge("ctx", `🪟 ${escapeHtml(formatCtxTokens(Number(_scfg[runnerContextField(_runnerId)])))}`) : "");
  // The cards and what the cell holds on each, read as its card reads them (cell-memory.js).
  const gpuLines = CellMemory.cards(s).map(({ i, mib }) => `GPU${i}${mib ? ` · ${(mib / 1024).toFixed(1)} GB` : ""}`).join(", ");

  // GPU badges for the status row
  const nodeGpusList = node.gpus || [];
  const statusGpuBadges = CellMemory.cards(s).map(({ i, mib }) => {
    const usedGb = mib ? (mib / 1024).toFixed(1) : null;
    const gpuMeta = nodeGpusList.find((g) => g.index === i);
    const totalMib = gpuMeta ? Number(gpuMeta.memoryTotalMiB || 0) : 0;
    const totalGb = totalMib > 0 ? Math.round(totalMib / 1024) : null;
    const memLabel = usedGb ? (totalGb ? `${usedGb}/${totalGb}G` : `${usedGb}G`) : "";
    return `<span class="node-gpu-badge">GPU${escapeHtml(String(i))}${memLabel ? " " + escapeHtml(memLabel) : ""}</span>`;
  }).join(" ");

  const row = (k, v) => v ? `<div class="nsd-row"><span class="nsd-k">${escapeHtml(k)}</span><span class="nsd-v">${v}</span></div>` : "";

  const cmdSection = (lines) => {
    const cmdText = lines.join("\n");
    const pre = lines.map((l) => `<span class="cmd-token">${escapeHtml(l)}</span>`).join("\n");
    return `<div class="nsd-cfg-section"><div class="nsd-cfg-head">COMMAND <button class="nsd-copy-btn" type="button" data-copy="${escapeHtml(cmdText)}" title="${escapeHtml(t("copyCommand"))}">⎘</button></div><pre class="command-preview nsd-cmd-pre">${pre}</pre></div>`;
  };

  // The command block. For everything except llama-server this is the line
  // start.sh actually holds, read off the file — not a mirror of the builder
  // rewritten in JS. There were four such mirrors here, one per runner someone
  // had remembered to add, and the two nobody added fell through to the llama
  // branch and were drawn as llama cells.
  const cmdBlockHtml = (() => {
    const cfg = s.slotConfig || {};
    if (!isLlama) {
      // The backend answers this for BOTH kinds of host: a controller cell from
      // its start.sh, a client cell from the same builder that hands the scout
      // its line. A custom cell's COMMAND is the last fallback — it IS the
      // config, so it is a fact and not a re-render.
      const saved = String(s.savedCommand || (isCmd ? cfg.COMMAND : "") || "")
        .trim().replace(/^\s*exec\s+/, "");
      if (!saved) {
        // Never applied, and nothing to read. Said plainly rather than guessed —
        // but only when it is TRUE: this line once appeared on client cells that
        // had been serving for hours, because it was asked for a start.sh that
        // only a controller host ever has.
        return `<div class="nsd-cfg-section"><div class="nsd-cfg-head">COMMAND</div>`
             + `<pre class="command-preview nsd-cmd-pre muted">${escapeHtml(t("cmdNotSavedYet"))}</pre></div>`;
      }
      // The port is the run's: the scout leases it at the start and fills the placeholder (LEASED_PORT) — no number is the cell's.
      const lines = [`export PORT=${LEASED_PORT}`];
      if (isCmd) {
        String(cfg.ENV || "").split(/[\n,]/).forEach((raw) => {
          const it = raw.trim(); if (!it || it.startsWith("#") || !it.includes("=")) return;
          const i = it.indexOf("="); const k = it.slice(0, i).trim();
          if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k)) return;
          lines.push(`export ${k}="${it.slice(i + 1).trim()}"`);
        });
        if (cfg.WORKDIR) lines.push(`cd ${cfg.WORKDIR}`);
      }
      lines.push(`exec ${saved}`);
      return cmdSection(lines);
    }
    if (!Object.keys(cfg).length) return "";
    const tokens = [];
    const add = (flag, val) => { if (val != null && String(val).trim() !== "") tokens.push(flag, String(val).trim()); };
    const llamaBin = _runnerId === "prism"
      ? (node.prismRuntime?.binary || "~/.local/share/caravan/prismml/current/llama-server")
      : (state?.paths?.llamaHome ? `${state.paths.llamaHome}/build/bin/llama-server` : null);
    if (llamaBin) tokens.push(llamaBin);
    add("--host", cfg.HOST);
    add("--port", LEASED_PORT);
    const modelPath = s.modelPath || [cfg.LLAMA_MODELS_DIR, cfg.MODEL_FILE].filter(Boolean).join("/");
    if (modelPath) add("--model", modelPath);
    add("--ctx-size", cfg.CTX_SIZE);
    add("--threads", cfg.THREADS);
    add("--threads-batch", cfg.THREADS_BATCH);
    add("--batch-size", cfg.BATCH_SIZE);
    add("--ubatch-size", cfg.UBATCH_SIZE);
    add("--parallel", cfg.PARALLEL);
    add("--n-gpu-layers", cfg.N_GPU_LAYERS);
    add("--cache-type-k", cfg.CACHE_TYPE_K);
    add("--cache-type-v", cfg.CACHE_TYPE_V);
    const mmproj = s.mmproj || [cfg.LLAMA_MODELS_DIR, cfg.MMPROJ_FILE].filter(Boolean).join("/");
    if (mmproj) {
      add("--mmproj", mmproj);
      if (String(cfg.OFFLOAD_MMPROJ || "").toLowerCase() === "true") tokens.push("--mmproj-offload");
    }
    // The builder's speculation, in its words: the rule it is held to (cell-plan.js CellDraft.start, contract/draft_load.json),
    // not a copy rewritten here. This preview printed --spec-type whenever the field was non-empty once, and --model-draft for a
    // draft switched off ("none") until 2026-11-07 — a command that was not the one being run, for the field that carries the
    // whole speculative story.
    const spec = CellDraft.start(CellFields.ofConfig(cfg));
    add("--spec-type", spec.spec);
    if (spec.loads) {
      add("--model-draft", [cfg.LLAMA_MODELS_DIR, String(cfg.SPEC_DRAFT_MODEL_FILE).trim()].filter(Boolean).join("/"));
      add("--gpu-layers-draft", spec.layers);
    }
    add("--spec-draft-n-max", spec.nMax);
    add("--spec-draft-n-min", spec.nMin);
    // Auto-YaRN mirror: CTX_SIZE above the model's native window makes the
    // builder emit the whole recipe — the preview must say so too.
    const yarnCtx = Number(cfg.CTX_SIZE || 0);
    const yarnMeta = modelsByPath().get(cfg.MODEL_FILE || "")?.ggufMeta || {};
    const yarnNative = Number(yarnMeta.contextLength || 0);
    if (yarnCtx > yarnNative && yarnNative > 0 && yarnMeta.architecture) {
      const extra = String(cfg.EXTRA_ARGS || "");
      if (!cfg.ROPE_SCALING) add("--rope-scaling", "yarn");
      if (!cfg.ROPE_SCALE) add("--rope-scale", String(Math.ceil((yarnCtx / yarnNative) * 100) / 100));
      if (!extra.includes("--yarn-orig-ctx")) add("--yarn-orig-ctx", String(yarnNative));
      if (!extra.includes("--override-kv"))
        add("--override-kv", `${yarnMeta.architecture}.context_length=int:${yarnCtx}`);
    }
    if (!tokens.length) return "";
    const parts = [];
    let ti = 0;
    while (ti < tokens.length) {
      const tok = tokens[ti];
      if (tok.startsWith("--") && ti + 1 < tokens.length && !tokens[ti + 1].startsWith("-")) {
        parts.push(`<span class="cmd-token">${escapeHtml(tok)} <span class="cmd-value">${escapeHtml(tokens[ti + 1])}</span></span>`);
        ti += 2;
      } else {
        parts.push(`<span class="cmd-token">${escapeHtml(tok)}</span>`);
        ti += 1;
      }
    }
    const cmdText = tokens.join(" ");
    return `<div class="nsd-cfg-section">
      <div class="nsd-cfg-head">COMMAND <button class="nsd-copy-btn" type="button" data-copy="${escapeHtml(cmdText)}" title="${escapeHtml(t("copyCommand"))}">⎘</button></div>
      <pre class="command-preview nsd-cmd-pre">${parts.join("\n")}</pre>
    </div>`;
  })();

  const html = `
    <div class="modal-overlay" id="nodeServerDetailOverlay">
      <div class="modal node-detail-modal" role="dialog" aria-modal="true">
        <div class="modal-head-row">
          <strong>${escapeHtml(node.name || node.id)}</strong>
          <button class="icon-action compact" id="nodeServerDetailClose" aria-label="Close">✕</button>
        </div>
        <div class="nsd-body">
          ${row("Status", `${topologyStatusPill(running ? "running" : (phase === "error" ? "failed" : phase))} ${statusGpuBadges || (running ? `<span class="node-gpu-badge node-cpu-badge" title="${escapeHtml(t("topologyCpuCellsHint"))}">CPU</span>` : "")}`)}
          ${isCmd
            ? row("Command", `<code class="nsd-cmd-inline">${escapeHtml(String(_scfg.COMMAND || "").replace(/^\s*exec\s+/, "") || "—")}</code>`)
            : _runnerRow && _runnerRow.modelField && !isLlama
            // Each runner keeps its model in its OWN field; reading MODEL_FILE
            // for all of them is what once labelled an NLLB cell "gemma".
            ? row("Model", `<code class="nsd-cmd-inline">${escapeHtml(String(_scfg[_runnerRow.modelField] || "") || "—")}</code>`)
            : row("Model", escapeHtml(parsed.label || s.model || ""))}
          ${(!isLlama && !isCmd && _runnerRow)
            ? row("Runner", `${mbadge("cmd", `${_runnerRow.icon || ""} ${t(_runnerRow.labelKey) || _runnerRow.id}`)}${_runnerRow.health ? mbadge("cmd", `❤ ${_runnerRow.health}`) : ""}`)
            : ""}
          ${_runnerId === "prism" && node.prismRuntime?.installed
            ? row("PrismML", `<code>${escapeHtml(node.prismRuntime.release || "")} · ${escapeHtml(node.prismRuntime.binary || "")}</code>`)
            : ""}
          ${isCmd
            ? (row("Health", _scfg.HEALTH_PATH ? `<code>${escapeHtml(_scfg.HEALTH_PATH)}</code>` : "") + row("Workdir", _scfg.WORKDIR ? `<code>${escapeHtml(_scfg.WORKDIR)}</code>` : ""))
            : (() => { const chips = [parsed.quant ? mbadge("quant", `🎛 ${escapeHtml(parsed.quant)}`) : "", parsed.size ? mbadge("size", `⚖ ${escapeHtml(parsed.size)}`) : "", parsed.variant ? mbadge("it", `🤖 ${escapeHtml(parsed.variant)}`) : "", s.mmproj ? mbadge("mmproj", "📷 mmproj") : "", (hasMtp && _hasCtx) ? mbadge("mtp", "⚡ mtp") : "", nsdCtxChip].filter(Boolean).join(""); return chips ? `<div class="nsd-row"><span class="nsd-k"></span><span class="nsd-v"><span class="model-chips">${chips}</span></span></div>` : ""; })()}
          ${row("GPU", gpuLines ? escapeHtml(gpuLines) : (running ? "CPU" : ""))}
          ${row(t("topologyTokenSpeedHead"), (s.promptTps != null || s.genTps != null) ? `${formatTps(s.promptTps || 0)} / ${formatTps(s.genTps || 0)} t/s (${t("topologyPromptGen")})` : "")}
          ${row("Context", s.ctxMax ? `${s.ctxUsed != null ? escapeHtml(formatCtxTokens(s.ctxUsed)) : "—"} / ${escapeHtml(formatCtxTokens(s.ctxMax))} ${escapeHtml(t("topologyLlamaContextWindow").toLowerCase())}` : "")}
          ${row("Activity", [activity.label, activity.summary].filter(Boolean).map(escapeHtml).join(" · "))}
          ${s.isSlot ? row("Service", escapeHtml([s.service, s.pid ? `PID ${s.pid}` : ""].filter(Boolean).join(" · "))) : ""}
          ${phase === "error" && s.lastError ? row("Error", `<code>${escapeHtml(s.lastError)}</code>`) : ""}
          ${cmdBlockHtml}
          <div class="nsd-cfg-section nsd-note-section">
            <div class="nsd-cfg-head">${escapeHtml(t("cellNoteHead"))}</div>
            <textarea class="nsd-note-input" maxlength="280" rows="2"
              placeholder="${escapeHtml(t("cellNotePlaceholder"))}">${escapeHtml((topology?.cellNotes || {})[id] || "")}</textarea>
            <button class="nsd-note-save" type="button">${escapeHtml(t("cellNoteSave"))}</button>
          </div>
          ${(() => {
            const model = (topology?.cellModelNotes || {})[id];
            return model ? `<div class="nsd-cfg-section nsd-model-note" data-t="cell-model-note-full">
            <div class="nsd-cfg-head" title="${escapeHtml(t("cellModelNoteTip"))}">📖 ${escapeHtml(t("cellModelNoteHead"))}</div>
            <div class="nsd-model-note-text">${escapeHtml(model)}</div>
          </div>` : "";
          })()}
        </div>
      </div>
    </div>`;
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  const overlay = tmp.firstElementChild;
  document.body.appendChild(overlay);
  // Escape closes it as its ✕ does: it stands over the cell's window, which leaves Escape to it (card-fold.js).
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };
  document.addEventListener("keydown", onKey);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  overlay.querySelector("#nodeServerDetailClose")?.addEventListener("click", close);
  overlay.querySelectorAll("[data-copy]").forEach((b) => {
    b.addEventListener("click", async () => {
      // copyText falls back to execCommand — the LAN UI runs on plain http
      // where navigator.clipboard does not exist.
      if (await copyText(b.dataset.copy)) {
        const orig = b.textContent;
        b.textContent = "✓";
        setTimeout(() => { b.textContent = orig; }, 1200);
      }
    });
  });
  overlay.querySelector(".nsd-note-save")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const note = overlay.querySelector(".nsd-note-input")?.value ?? "";
    btn.disabled = true;
    try {
      await api("/api/topology/server-slot/note", {
        method: "POST",
        body: JSON.stringify({ cellId: id, note }),
      });
      toast(t("cellNoteSaved"));
      await refreshTopology();
      renderTopology();
    } catch (err) {
      toast(err.message);
    } finally {
      btn.disabled = false;
    }
  });
}

// Parse "version: 362 (3ac3c20)" → { build: 362, commit: "3ac3c20" }
export function parseLlamaBuildVersion(vstr) {
  if (!vstr) return null;
  const m = String(vstr).match(/version:\s*(\d+)\s*\(([0-9a-f]+)\)/i);
  if (!m) return null;
  return { build: parseInt(m[1], 10), commit: m[2] };
}

// Whether this machine is the one the controller runs on (its scout says the
// hostname): rebooting or powering it off takes the board down with it, so
// its confirmations say so. The one reading of that fact on the page.
export function isControllerMachine(hostId) {
  return !!(topology?.nodes || []).find((n) => String(n.id) === String(hostId))?.controllerMachine;
}

const LOOPBACK = new Set(["127.0.0.1", "localhost", "::1"]);

// The machine behind an address its cells answer at: { key, name, address }.
// The name is its node's — what its scout reports, the computer's hostname — and
// the address is the node's too (where its cells are reached); the one place
// the board's node headers, Routing's server groups and the nvidia-smi
// sources name a machine from. Routing named the controller's machine by the
// controller's old display name (over its own machine's cells) and every
// other machine by its bare address. Loopback and the controller's own address
// are the controller's machine: its node, or the name of the computer the
// controller runs on when no scout reports from it. An address no node has is
// said as the address — a name is never guessed.
export function machineAt(address) {
  const addr = String(address || "").trim();
  const nodes = topology?.nodes || [];
  const own = !addr || LOOPBACK.has(addr) || addr === String(topology?.server?.ip || "");
  const node = own ? nodes.find((n) => n.controllerMachine) : nodes.find((n) => String(n.ip || "") === addr);
  if (node) return { key: String(node.id), name: String(node.name || node.id), address: String(node.ip || addr) };
  if (own) {
    const address = String(topology?.server?.ip || addr || "127.0.0.1");
    return { key: "controller", name: String(topology?.server?.hostname || address), address };
  }
  return { key: addr, name: addr, address: addr };
}

// The words a reboot, a poweroff or its schedule are confirmed with, as an i18n
// key: the controller's own machine takes the board down with it.
const HOST_POWER_TEXT = {
  reboot: ["hostRebootConfirmController", "hostRebootConfirmClient"],
  poweroff: ["hostPowerOffConfirmController", "hostPowerOffConfirmClient"],
  schedule: ["hostPowerSchedWarnController", "hostPowerSchedWarnClient"],
};
export function hostPowerTextKey(hostId, what) {
  const [own, other] = HOST_POWER_TEXT[what];
  return isControllerMachine(hostId) ? own : other;
}

// Returns the node-grouped HTML for the Llama Servers lane.
// A machine's Compute panel: the CPU and its RAM, each GPU, the history charts. One drawing for the
// machine's own window (nodesLaneHtml) and its glance on the main board (machinesLaneHtml); the live
// patch (topology-render.js, syncTopologyLive) finds its hooks in either.
export function nodeComputeHtml(n) {
  const cpu = n.cpu || {}, ram = cpu.ram || {};
  const servers = n.servers || [];
  // Cells that run on this host WITHOUT touching a GPU (n-gpu-layers 0,
  // command cells): they never appear in a GPU row's ▶ cells, so give
  // them their own CPU line — otherwise a running CPU cell looks missing.
  // Named as the GPU rows name theirs (CellName), not by a port: a cell holds
  // one only while it runs.
  const cpuCells = servers.filter((srv) => {
    const ph = srv.phase || (srv.status && srv.status.phase) || "";
    // Same rule as the card's chip: a GPU-pinned cell is never a CPU cell,
    // even in the window where it holds no VRAM yet.
    // Nor is a cell in an engine: its own process holds no model.
    return ph === "running" && !(srv.gpuIndexes || []).length && !cellPinnedToGpu(srv) && !engineRunnerOf(srv);
  }).map((srv) => new CellName(srv).title);
  // The CPU block mirrors a GPU row now: live load% in the head, RAM
  // used/total where a GPU shows VRAM — those two moved out of the node
  // header (which kept only the platform). The "cells on CPU" are a
  // sub-line when any exist. Always rendered, so a host's CPU/RAM is visible
  // even with no CPU cell running.
  const cpuLoadTxt = cpu.loadPct != null ? `${cpu.loadPct}%` : "";
  const ramUsedGb = Number(ram.usedGb || 0), ramTotalGb = Number(ram.totalGb || 0);
  const ramPct = ramTotalGb > 0 ? Math.min(100, Math.round((ramUsedGb / ramTotalGb) * 100)) : 0;
  const cpuRamTxt = ram.usedGb != null ? `RAM ${ram.usedGb}/${ram.totalGb} GB`
    : (ram.totalGb != null ? `RAM ${ram.totalGb} GB` : "");
  // Mirrors a GPU row: a used/total RAM bar where the GPU has its VRAM bar
  // (no per-cell slices — just the whole-host RAM), and the CPU-cell blue
  // accent so the block matches the cells that run on it.
  const cpuRowHtml = `
        <div class="node-gpu-row node-cpu-row" title="${escapeHtml(t("topologyCpuCellsHint"))}">
          <div class="node-gpu-head">
            <strong>CPU</strong>
            <span class="node-gpu-util" data-live-cpuload>${escapeHtml(cpuLoadTxt)}</span>
          </div>
          <div class="node-ram-bar" data-live-cpurambar title="${ramUsedGb.toFixed(1)} / ${ramTotalGb.toFixed(1)} GB"><span style="width:${ramPct}%"></span></div>
          <div class="node-gpu-meta">
            <span data-live-cpuram>${escapeHtml(cpuRamTxt)}</span>
            ${cpuCells.length ? `<span class="node-gpu-ports">▶ ${cpuCells.map((name) => escapeHtml(name)).join(", ")}</span>` : ""}
          </div>
        </div>`;
  // CPU first, then the GPUs (swapped on request — the CPU/RAM summary now
  // lives here, so it leads).
  const gpusHtml = cpuRowHtml + ((n.gpus || []).length
    ? n.gpus.map((g) => nodeGpuRowHtml(n, g)).join("")
    // The reason outranks a dash: "no cards" and "can't ask a card" are
    // different messages, and the second one names what to fix (after a
    // driver update, that's "needs a reboot", while the card is right
    // there).
    : `<div class="topology-muted" style="font-size:12px"${n.gpuError ? ` title="${escapeHtml(n.gpuError)}"` : ""}>${escapeHtml(n.gpuError || t("topologyNoGpu"))}</div>`);
  return `<div class="node-gpus"><div class="node-subtitle">${escapeHtml(t("topologyGpusSection"))}</div>${nodeDriverWarningsHtml(n)}${gpusHtml}${nodeTelemetryRowsHtml(n)}</div>`;
}

// What a machine is, in its head and for a screen reader: the role word (translated), its own
// name, and its address — one reading for the machine's card and its glance.
export function nodeRoleWord(n) {
  return n.role === "host" ? t("nodeRoleHost") : String(n.role || "");
}
export function nodeGroupName(n) {
  const role = nodeRoleWord(n);
  return `${role.charAt(0).toUpperCase()}${role.slice(1)} ${n.name || n.id}` + (n.ip ? ` · ${n.ip}` : "");
}

// A machine's window that has no machine to show: the board does not have this one (forgotten,
// never added), or the window names none. Said, with the way back — an empty window read as
// "still loading".
export function machineMissingHtml(id) {
  const said = String(id || "") ? t("machineNotOnBoard", { id: String(id) }) : t("machineNotNamed");
  return `<div class="machine-missing" data-t="machine-missing">${escapeHtml(said)}`
    + ` <a href="/board" data-t="machine-missing-back">${escapeHtml(t("machineBackToBoard"))}</a></div>`;
}

// The main board's machines (the owner, 2026-10-11): each one as its load at a glance — its head and
// its Compute panel. A click on the card opens the machine's own window (main.js; the owner,
// 2026-10-12: no "↗ Open" button, the card itself opens), which holds the rest: its servers,
// engines, models and cells, the card the main board used to show whole, the machine's system (in a
// column of the board's one width the head had no room for it) and the scout's ✕ — letting a machine
// go is done in its window, not on its glance. The machine's name is the card's link, for the
// keyboard and a click with a modifier.
export function machinesLaneHtml() {
  if (!topology) return "";
  return (topology.nodes || []).map((n) => {
    const name = String(n.name || n.id);
    const id = escapeHtml(String(n.id));
    const opens = escapeHtml(t("machineOpenTitle", { name }));
    return `
      <section class="node-card machine-glance ${n.online ? "online" : "offline"}" data-node-id="${id}" data-t="machine-glance" data-t-id="${id}"
               role="group" aria-label="${escapeHtml(nodeGroupName(n))}" title="${opens}">
        <header class="node-head">
          <span class="node-dot ${n.online ? "on" : "off"}"></span>
          <a class="machine-name" href="${escapeHtml(BoardView.url(n.id))}"
             data-machine-open="${id}" data-t="machine-open" data-t-id="${id}">${escapeHtml(name)}</a>
          <span class="node-role">${escapeHtml(nodeRoleWord(n))}</span>
          ${n.ip ? `<span class="topology-muted">${escapeHtml(n.ip)}</span>` : ""}
          ${scoutOldChipHtml(n)}
          ${ModelCacheLine.of(n).diskChipHtml()}
        </header>
        ${hostSilenceHtml(n)}
        <div class="node-body">${nodeComputeHtml(n)}</div>
      </section>`;
  }).join("");
}

/** The head of a machine's page (machine-head.js) with what only this module knows: who holds a card besides the cells, how long a
 *  silent machine has been silent, whether a cell is being reserved here. One place for both its drawings — the page's, with its
 *  side column (`side`, machineSideHtml), and the live patch's (topology-render.js), which keeps the column as drawn. */
export function machineHeadOf(n, { side = "" } = {}) {
  // The launch being built on this machine's page (machine-build.js), for the model picked there: a cell that stands under the builder's
  // key, laid by the map as one. No cell of the machine is under that key — a cell's id is the controller's, given when its Start makes
  // it — so it stands until the builder lets it go.
  MACHINE_BUILD.follow({ name: MACHINE_MODELS.picked }, n.id);
  const launch = MACHINE_BUILD.server();
  // A plan whose cell started, stopped or left since it was laid means nothing any more.
  if (MACHINE_PLAN.on && !MACHINE_PLAN.validFor(n, (s) => MachineMap.phase(s), launch)) MACHINE_PLAN.clear();
  return new MachineHead(n, {
    owners: gpuOutsideOwners, age: hostAgeText, reserving: _reservingCells.has(String(n.id)),
    addTitle: t("caravanAddTitle"), oldScout: scoutOldChipHtml(n),
    cells: MACHINE_PICK.cells, chosen: MACHINE_PICK.cellId, side, plan: MACHINE_PLAN, launch,
    // The launch builder's engines: the registry the runner tabs and the wizard read, and the rule they answer which file a runner takes by.
    runners: { rows: runnerRegistry(), takes: (row, file) => runnerAvailability(row, "", file) },
    library: { rows: state.models, artifacts: state.artifacts, ratings: topology?.modelRatings },
  });
}

/** What stands at the right of a machine's map on its own page (machine-head.js MachineSide, 1.3.636), drawn here as the board's
 *  card draws it: the caravan's strip and the engines' groups — each engine's strip and the models it holds that no cell serves —
 *  the model cache's line, how many incidents the caravan's ports had in the last day (not known while the monitor has not said),
 *  the machine's charts, and `stats`, the controller machine's own server stats with their switch. */
export function machineSideHtml(n, servers, stats = "") {
  const monitor = ui.latestSystemMonitor;
  return new MachineSide({
    warnings: nodeDriverWarningsHtml(n),
    engines: `<div class="node-launchers"><div class="node-launcher-group">${nodeCaravanStripHtml(n)}</div>${nodeEngineGroupsHtml(n, servers)}</div>`,
    disk: ModelDisk.of(n).html(),
    incidents: monitor ? topologyIncidentItems(systemSamples(monitor) || []).length : null,
    activity: nodeTelemetryRowsHtml(n, { cards: false }),
    stats,
    machine: n.name || n.id,
  }).html();
}

export function nodesLaneHtml(only = null) {
  if (!topology) return "";
  // Every machine with a scout, GPU or not. A GPU-less host used to be left to
  // the clients column, where the scout's card showed it; that card is gone
  // with the scout's word about clients (docs/scout-split.md), and a machine
  // this lane skipped would be on no screen at all — nor could its first cell
  // be reserved, the ＋ lives here. `only`: the one machine of its own window
  // (board-view.js) — a window for a machine the board does not have says so.
  const nodes = (topology.nodes || []).filter((n) => only === null || String(n.id) === String(only));
  if (only !== null && !nodes.length) return machineMissingHtml(only);

  // A machine's own page (the owner's choice of 2026-10-25: variant А with the memory map of В) leads with its head — the
  // passport, the band and where its memory goes (machine-head.js) — in place of the card's header and its compute column; the
  // charts of its activity stay on the right until their tab comes.
  const machinePage = only !== null;
  const sections = nodes.map((n) => {
    // Power-cycle this host. Some faults are not fixable in software — a host
    // drops a RAM stick on some boots and comes back with half its memory, which
    // starves cells until the machine is rebooted. Reboot only, never shutdown:
    // nothing on this board can switch a headless box back on.
    const rebootBtn = `<button class="llama-ver-refresh node-reboot" type="button" data-t="node-reboot" data-t-id="${escapeHtml(String(n.id))}" data-reboot-host="${escapeHtml(String(n.id))}" title="${escapeHtml(t("hostRebootTitle"))}" aria-label="${escapeHtml(t("hostRebootTitle"))}">⟳︎</button>`;
    // Power off. Deliberately NOT the same glyph as reboot and deliberately
    // last: the two sit side by side, and the one that cannot be undone should
    // not be the one under the thumb. Its confirmation asks for the host's name
    // to be typed — see topology-render.js.
    const powerOffBtn = `<button class="llama-ver-refresh node-poweroff" type="button" data-t="node-poweroff" data-t-id="${escapeHtml(String(n.id))}" data-poweroff-host="${escapeHtml(String(n.id))}" title="${escapeHtml(t("hostPowerOffTitle"))}" aria-label="${escapeHtml(t("hostPowerOffTitle"))}">⏻︎</button>`;
    // A schedule for that poweroff. The ⏰ lights up when one is armed and its
    // title shows the time, so an armed daily shutdown is visible at rest —
    // never a surprise. Opens the little editor in topology-render.js.
    const ps = n.powerSchedule || {};
    const psArmed = !!ps.enabled;
    const powerSchedBtn = `<button class="llama-ver-refresh node-power-sched${psArmed ? " armed" : ""}" type="button" data-t="node-power-schedule" data-t-id="${escapeHtml(String(n.id))}" data-power-schedule-host="${escapeHtml(String(n.id))}" title="${escapeHtml(psArmed ? t("hostPowerSchedArmedTitle", { at: ps.at || "", daily: ps.daily ? t("hostPowerSchedDaily") : t("hostPowerSchedOnce") }) : t("hostPowerSchedTitle"))}" aria-label="${escapeHtml(t("hostPowerSchedTitle"))}">⏰︎</button>`;
    // The machine's llama.cpp build left the header for the caravan's strip
    // (2026-09-27, the operator's move); its power stays here.
    const verChip = `<span class="node-power-ctl">${rebootBtn}${powerSchedBtn}${powerOffBtn}</span>`;
    const servers = (n.servers || []);
    // A page of one machine has nothing to fold it away for.
    const collapsed = !machinePage && _collapsedNodes.has(n.id);
    // When collapsed, keep a left-edge rail of cable anchors (one per server)
    // so proxy cables stay attached.
    let bodyHtml;
    let machineSide = "";
    if (collapsed) {
      // Each cell by its name (CellName) and its id, as its card has them: it was its port here until a cell held one only while
      // it runs.
      const rail = servers.map((s) => {
        const phase = s.phase || (s.status && s.status.phase) || "running";
        const cls = phase === "running" ? "running" : (phase === "stopped" || phase === "reserved" ? "" : "loading");
        const name = new CellName(s).title;
        return `<span class="node-rail-input" title="${escapeHtml(name)}">
            <span class="topology-handle server-input ${cls}" data-topology-llama-input="1" data-cell-id="${escapeHtml(String(s.cellId || ""))}" data-llama-host="${escapeHtml(topologyServerUpstreamHost(s, n))}"></span>
            <code>${escapeHtml(name)}</code></span>`;
      }).join("");
      bodyHtml = `<div class="node-rail">${rail || `<span class="topology-muted" style="font-size:11px">${escapeHtml(t("topologyNoServers"))}</span>`}</div>`;
    } else {
      const filter = nodeCellFilter(n, servers);
      const launchers = machinePage ? "" : nodeLaunchersHtml(n, servers);
      // A machine's page has the map of its memory over the list (machine-head.js): its builder hears what each card says of its
      // cell — its name, its window, its stop — for the panel of the cell chosen on the map.
      const picks = machinePage ? new Map() : null;
      const serversHtml = servers.length
        ? servers.map((s) => nodeServerCardHtml(n, s, { fold: true, only: machinePage ? "" : filter.chosen, picks })).join("")
        : "";
      if (picks) {
        // The launch being built on this page, for the model picked there, is told as a cell that stands, so the map lays it as it lays one
        // (machine-build.js).
        MACHINE_BUILD.follow({ name: MACHINE_MODELS.picked }, n.id);
        const launch = MACHINE_BUILD.launch();
        if (launch && !picks.has(MachineBuild.KEY)) picks.set(MachineBuild.KEY, LaunchFacts.of(launch, n));
        MACHINE_PICK.know(picks);
      }
      // The machine this controller runs on carries its Server stats (CPU,
      // RAM, network, disk, processes — the controller's own monitor, mounted,
      // not rebuilt) under a "Servers" toggle.
      const statsHere = !!n.controllerMachine;
      const statsOpen = localStorage.getItem("topologyCtrlServerStatsOpen") === "1";
      const serversSubtitle = statsHere
        ? `<button class="node-subtitle node-subtitle-toggle" type="button" data-ctrl-stats-toggle aria-expanded="${statsOpen ? "true" : "false"}">${escapeHtml(t("topologyServersHead"))} <span class="node-subtitle-caret">${statsOpen ? "▾" : "▸"}</span><span class="node-subtitle-hint">${escapeHtml(t("topologyNodeServerCharts"))}</span></button>`
        : `<div class="node-subtitle">${escapeHtml(t("topologyServersHead"))}</div>`;
      const serverStatsSlot = statsHere ? `<div class="node-ctrl-server-stats" data-ctrl-server-stats${statsOpen ? "" : " hidden"}></div>` : "";
      // The machine's eye over its cells, beside the list's title. The count is
      // read off the marks the cells left, so it is the rule's own answer.
      const eye = new CellEye({
        hostId: n.id, on: CARD_FOLD.hidesIdle(n.id), hidden: (serversHtml.match(/data-cell-hidden-by="idle"/g) || []).length,
      }).html();
      // Between what can be started and what is made (2026-09-27, the
      // operator's ask): the caravan, the engines and their shelves above,
      // the machine's cells — their chips and their lines — below.
      const divider = `<div class="node-cells-divider" role="separator"><span>${escapeHtml(t("cellsDividerLabel"))}</span></div>`;
      if (machinePage) {
        // The machine's own page (variant В): its map and its bench in its head, and at their right the column of its engines,
        // its model disk, the incidents and its activity (machineSideHtml, 1.3.636) — the controller machine's server stats
        // there too, under their switch. Its list of cells keeps only their windows — the lines are not drawn (machine.css), a cell
        // in trouble's neither (1.3.653) — and no title, chips, eye or engines of its own.
        const statsSwitch = statsHere
          ? `<button class="node-subtitle node-subtitle-toggle" type="button" data-ctrl-stats-toggle aria-expanded="${statsOpen ? "true" : "false"}">`
            + `${escapeHtml(t("topologyNodeServerCharts"))} <span class="node-subtitle-caret">${statsOpen ? "▾" : "▸"}</span></button>` : "";
        machineSide = machineSideHtml(n, servers, `${statsSwitch}${serverStatsSlot}`);
        bodyHtml = `<div class="node-body machine-cells"><div class="node-servers">${serversHtml}</div></div>`;
      } else {
        const serversHead = `<div class="node-servers-head">${serversSubtitle}${launchers}${divider}${filter.html()}${eye}</div>`;
        bodyHtml = `<div class="node-body">
          <div class="node-servers">${serversHead}${serversHtml}${serverStatsSlot}</div>
          ${nodeComputeHtml(n)}
        </div>`;
      }
    }
    // A machine card is a real grouping of controls that belong together, and
    // nothing said so: a screen reader user walked into two dozen buttons with
    // no announcement of which machine any of them acts on. role="group" and
    // not the <section>'s implicit region — a landmark per machine would bury
    // the five that describe the page itself, and these are repeated items
    // inside one of those, not sections of the page.
    //
    // The name is assembled from what the header already shows: the role word
    // (translated), the machine's own name, and its address. Capitalised
    // because it opens a phrase; harmless where a script has no case.
    const _roleWord = nodeRoleWord(n);
    const _groupName = nodeGroupName(n);
    // A machine's place in the operator's order (server-order.js) — Routing's Servers panel reads
    // it — and the controls that move it lead its head.
    const orderKey = ServerOrder.key("node", n.id);
    if (machinePage) {
      const head = machineHeadOf(n, { side: machineSide });
      return `
      <section class="node-card machine-page ${n.online ? "online" : "offline"}" data-node-id="${escapeHtml(n.id)}"
               role="group" aria-label="${escapeHtml(_groupName)}">
        ${head.html()}
        ${bodyHtml}
      </section>`;
    }
    return `
      <section class="node-card ${n.online ? "online" : "offline"} ${collapsed ? "collapsed" : ""}" data-node-id="${escapeHtml(n.id)}"${SERVER_ORDER.attrs(orderKey)}
               role="group" aria-label="${escapeHtml(_groupName)}">
        <header class="node-head">
          ${SERVER_ORDER.controls(orderKey, n.name || n.id)}
          <button class="node-collapse" type="button" data-node-collapse="${escapeHtml(n.id)}" title="${escapeHtml(collapsed ? t("expand") : t("collapse"))}" aria-expanded="${collapsed ? "false" : "true"}">${collapsed ? "▸" : "▾"}</button>
          <span class="node-dot ${n.online ? "on" : "off"}"></span>
          <strong>${escapeHtml(n.name || n.id)}</strong>
          <span class="node-role">${escapeHtml(_roleWord)}</span>
          ${n.ip ? `<span class="topology-muted">${escapeHtml(n.ip)}</span>` : ""}
          ${scoutOldChipHtml(n)}
          ${ModelCacheLine.of(n).diskChipHtml()}
          ${verChip}
          ${collapsed ? `<span class="node-meta">${servers.length} srv · ${(n.gpus||[]).length} GPU</span>` : ""}
          <span style="flex:1"></span>
          <span class="node-meta" data-live-nodemeta>${escapeHtml(n.platform || "")}</span>
          ${scoutDisconnectBtnHtml(n)}
        </header>
        ${hostSilenceHtml(n)}
        ${bodyHtml}
      </section>`;
  }).join("");

  // No machine yet: nothing is drawn — "+ Add scout" under the lane says what to do. A muted
  // "no nodes" above it read as leftover debug text (2026-10-08).
  return sections;
}

// Move the live controller stats/charts elements back to their home .lane-stats
// section (called before every lane rebuild so innerHTML doesn't destroy them).
export const _LANE_STATS_CARDS = ["topology-server-stats-card", "topology-gpu-history-card", "topology-incidents-card"];
export let _incidentsModalOpen = false;
export function parkLaneStats() {
  const home = document.querySelector(".lane-stats");
  if (!home) return;
  _LANE_STATS_CARDS.forEach((cls) => {
    // Keep the incidents card in its modal while it's open — don't yank it home.
    if (cls === "topology-incidents-card" && _incidentsModalOpen) return;
    const el = document.querySelector("." + cls);
    if (el && el.parentElement !== home) home.appendChild(el);
  });
}
// After a node-mode render, relocate the live Server stats card (canvases, so
// we move the DOM rather than rebuild it) into its slot in the controller
// machine's node, under its Servers toggle. The incidents card stays parked
// until its modal is opened.
export function mountNodeTelemetry() {
  const root = $("topologyLlamaServers");
  if (!root) return;
  const statsSlot = root.querySelector("[data-ctrl-server-stats]");
  const serverCard = document.querySelector(".topology-server-stats-card");
  if (statsSlot && serverCard) {
    if (serverCard.tagName === "DETAILS") serverCard.open = true;  // show charts, not just the summary
    statsSlot.appendChild(serverCard);
  }
}

// Show/hide the mounted Server-telemetry charts under the controller's
// "Servers" header (state persisted so it survives re-renders).
export function toggleCtrlServerStats(btn) {
  const slot = $("topologyLlamaServers")?.querySelector("[data-ctrl-server-stats]");
  if (!slot) return;
  const willOpen = slot.hasAttribute("hidden");
  if (willOpen) slot.removeAttribute("hidden"); else slot.setAttribute("hidden", "");
  btn.setAttribute("aria-expanded", willOpen ? "true" : "false");
  const caret = btn.querySelector(".node-subtitle-caret");
  if (caret) caret.textContent = willOpen ? "▾" : "▸";
  localStorage.setItem("topologyCtrlServerStatsOpen", willOpen ? "1" : "0");
  requestAnimationFrame(drawTopologyCables);  // node height changed → reattach cables
}

// Incidents open in a modal: relocate the live incidents card into the modal
// body (it keeps updating — renderTopologyIncidents targets it by id), park it
// back home on close.
export function openIncidentsModal() {
  const overlay = $("incidentsModalOverlay");
  const body = $("incidentsModalBody");
  const card = document.querySelector(".topology-incidents-card");
  if (!overlay || !body || !card) return;
  _incidentsModalOpen = true;
  body.appendChild(card);
  overlay.hidden = false;
  renderTopologyIncidents();
}
export function closeIncidentsModal() {
  _incidentsModalOpen = false;
  const overlay = $("incidentsModalOverlay");
  if (overlay) overlay.hidden = true;
  const home = document.querySelector(".lane-stats");
  const card = document.querySelector(".topology-incidents-card");
  if (home && card) home.appendChild(card);
}

// ── Models bar: two ways in ───────────────────────────────────────────────────
// The board no longer shows or edits where models live. It showed ONE path, and
// models now live in several stores (this disk, the libraries); the ✎ here was a
// second editor for what /models edits, with the stores next to it. What stays
// is the way to each page: what is on the disks, and what can be downloaded.
// Both open in a new tab — the board keeps running where it was.
