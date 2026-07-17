# Frontend module reference

The UI is 36 native ES modules under `static/js/` plus one page-scoped module at `static/hf.js`.
There is no bundler, no framework, no npm and no build step: the browser loads `/js/main.js` as a
`type="module"` script and follows real `import` statements from there. The core was split out
of a single 26,720-line `static/app.js` (the split tooling survives in `scripts/refactor/`).

Five pages share the code:

| page | route(s) | entry | notes |
|---|---|---|---|
| `static/index.html` | `/`, `/index.html` | `/js/main.js` | the topology board (main app) |
| `static/kanban.html` | `/kanban`, `/router` | `/js/main.js` | standalone router workspace; an inline classic script sets `window.ROUTER_STANDALONE = true` — it runs immediately, before the (deferred) module executes, so `main.js` sees the flag. Deep-link a router with `?id=<routerId>` (default `router:default`) |
| `static/hf.html` | `/hf` | `/hf.js` | HuggingFace model browser; imports only from `/js/utils.js` |
| `static/models.html` | `/models` | `/js/models-page.js` | models-disk tree with size rollups and unreferenced-file cleanup |
| `static/system.html` | `/system` | `/js/system-page.js` | Controller / llama.cpp / Security / Diagnostics tabs (the former System modal) |

Serving: the Python backend (`caravan/admin/routes.py`) serves every static file through
`Handler.send_file`, which sets an mtime+size `ETag` and `Cache-Control: no-cache` — the browser
revalidates every load and gets a 304 when unchanged, so a redeploy is picked up immediately and
**no cache-busting `?v=` params are needed** (the favicon's `?v=2` is the one deliberate holdout).
`/js/<name>` and `/css/<name>` are prefix routes; adding a module is just adding a file.

CSS is 9 cascade-ordered files under `static/css/`, linked in this exact order on all three pages:
`base`, `topology-board`, `canvas`, `modals`, `cards`, `form`, `monitor`, `nodes`, `hf`. They are
**contiguous slices** of the old `styles.css` — class families interleave heavily, so regrouping
rules across files would reorder equal-specificity rules and change the cascade. Add new rules to
the file whose range they belong to; never move existing rules between files (some slices even
start mid-topic — `form.css` opens with a comment referring to a rule in the previous slice).

## State model

`static/js/state.js` (35 lines) carries the two central objects:

- `state` — the `/api/state` payload (controller service, runtime, CPU/GPU, config).
- `topology` — the `/api/topology` payload (clients, nodes, servers, proxies, routers, cloud).

Both are exported **live bindings** (`export let`). Importers always see the current value, but
only `state.js` may rebind them — writers go through `setState(value)` / `setTopology(value)`.
Under ES modules, assigning to an imported binding is a runtime `TypeError`:

```js
import { topology, setTopology } from "./state.js";

topology = await api("/api/topology");    // WRONG — TypeError: assignment to imported binding
setTopology(await api("/api/topology"));  // right — rebinds inside state.js, every importer sees it

ui.usageStatsModalOpen = true;            // fine — property write on an imported object, no setter needed
```

This bug class actually shipped once: after the module split, fourteen sites still rebound imports
(`topology = ...` in topology-dnd/cloud/routers, `state = ...` in llama-edit, `_cvPos`/`_cvView`,
`_topologyRenderPending`) and were fixed in commit `9de2510` by converting them to setters. The
repo audit for this greps for `importedName =` assignments — keep it clean.

Setters that exist for exactly this reason:

- `setState()` / `setTopology()` — `state.js`.
- `cvSetViewport(pos, view)` — `canvas.js`; rebinds the module-local `_cvPos` (node positions) and
  `_cvView` (pan/zoom transform) for foreign writers (`main.js`, `topology-dnd.js`).
- `markTopologyRenderPending()` — `topology-render.js`; foreign modules (model-meta, remote-cells)
  defer a render during user interaction through it.

The `ui` object (also in `state.js`) holds ~20 flags historically rebound from several features:
modal open/close flags (`usageStatsModalOpen`, `topologyCloudModalOpen`, `topologyProxyFormOpen`,
...), the canvas router ids (`topologyCanvasRouterId`, `topologyRouterDetailId`), usage-stats
scope/days/edits, `pendingConfirm`, `latestSystemMonitor`, and the per-tick fingerprint caches
(`_lastActivityFingerprint`, `_lastCloudProvidersKey`). Property writes need no setters. **New
flags written from more than one module go here.**

Everything else follows one convention: module-local mutable state lives in the module of its
**only writer** and is exported for readers. Examples: `activeView` / `_lastStructureFingerprint`
in topology-render, the `_cv*` canvas state in canvas, the pending-op Sets in remote-cells, the
monitor timers in polling, the drag state and several modal flags owned by topology-dnd, the
history filters in history, the cloud-block modal flags in cloud.

## Render & polling pipeline

`topology-render.js` orchestrates everything:

- `renderAll()` — language/theme + all classic panels + `renderTopology()`. Runs on load,
  language switch, and config saves.
- `renderTopology()` — a **full `innerHTML` rebuild** of the board: the clients column, the router
  stack plus every modal shell, the nodes lane, GPU cards. It then re-binds all delegated handlers
  (`bindTopologyDragAndDrop()`) and per-render buttons. A full rebuild resets CSS animations and
  drops an in-progress drag, so it must not run on every background tick.
- `refreshTopology()` — `GET /api/topology` → `setTopology()` → `applyTopologyUpdate()`, which decides:
  1. user mid-interaction (`topologyPointerDrag`, proxy form open, canvas drag) → set
     `_topologyRenderPending` and do nothing; `flushPendingTopologyRender()` runs when the
     interaction ends;
  2. `topologyStructureFingerprint(topology)` differs from the last render → full `renderTopology()`;
  3. otherwise → `syncTopologyLive()` patches only the volatile numbers in place (heartbeat age,
     CPU/RAM meta, t/s, ctx, download %, GPU util/VRAM bars, sparklines) and redraws cables — DOM,
     animations and drags survive.

The fingerprint covers graph identity only: which cards/handles/cables exist and how they connect
(clients, servers with their **phase**, GPUs, proxies, cloud providers, view mode, open modals).
It deliberately **excludes** fast-moving numbers. Any phase transition (`downloading` → `loading`
→ `running`) is structural and forces a full rebuild; the numbers inside a phase are live-patched.
Around rebuilds, `parkLaneStats()` / `mountNodeTelemetry()` (topology-nodes) move the live chart
elements out of and back into the board so their canvases are never destroyed by `innerHTML`.

Poll cadences:

| endpoint | cadence | driver |
|---|---|---|
| `/api/state` | 1.5 s idle / 5 s while the controller service runs (self-rescheduling timeout) | `polling.js` `scheduleLiveRefresh()` |
| `/api/topology` | piggybacks each live-refresh tick — ≈2 s on the main board; also refetched after most POSTs | `refreshLiveState()` → `refreshTopology()` |
| `/api/topology` (start watch) | every 2 s while a remote server is resolving/downloading/loading; stops itself | `remote-cells.js` `startRemoteStartWatch()` |
| `/api/system-monitor` | 1 s while a monitor runs; feeds `ui.latestSystemMonitor`; the standalone kanban's only recurring poll (drives its live stats) | `polling.js` `startTopologyMonitor()` / `startSystemMonitor()` |
| `/api/monitor/nvidia-smi` | user-set 1–30 s, only while the drawer tab is hovered/focused | `polling.js` `startMonitor()` |
| `/api/proxy-daily-stats` | 60 s, plus once per `refreshTopology()` | `main.js` / `model-meta.js` |
| `/api/model-pricing` | 24 h | `main.js` |

How a config save becomes visible: POST responses may carry fresh state, and callers tolerate
both shapes.

- `/api/config` and `/api/action` return `{state}` → `setState()` + `renderAll()`.
- `/api/topology/assignments` returns a full `topology` → applied immediately.
- `/api/agent-proxies/routers` (`saveRouters()`) deep-copies `topology.routers`, runs the mutator,
  POSTs, and applies the returned topology snapshot guarded by `if (data.topology)` — if a
  response arrives without one, the change simply lands on the next poll tick.
- `/api/agent-proxies/config` (proxy-port form, route list editor) returns `{ok, config, monitor}`
  with **no** topology — callers either `await refreshTopology()` explicitly
  (`saveTopologyProxyForm()`) or rely on the next poll.

Standalone kanban init (`main.js` `initRouterStandalonePage()`), in order: `refreshTopology()` →
set the ui canvas ids (`ui.topologyRouterDetailId`, `ui.topologyCanvasRouterId`,
`ui.topologyRouterNodeCfgId = ""`, `ui.topologyRouterInputsExpanded = true`) →
`cvSetViewport(canvasLoadPositions(routerId), {tx: 24, ty: 24, scale: 1})` → `renderTopology()` →
`startTopologyMonitor()`. This page never calls `loadState()` — topology loads once and the 1 s
system-monitor poll keeps the queue/schedule nodes live.

**Core**

## constants.js

Launch-form field definitions shared by the config form and both edit modals (`te-`/`tr-`
prefixes): field lists, tab layouts, optional-toggle defaults and the Gemma-4 companion defaults.
Pure data plus one mutable Set.

- Owns: the field taxonomy; `dirtyOptionalToggles` (cleared by `loadState`/`saveConfig`).
- Key exports: `numericFields`, `toggleFields`, `advancedGroups`, `advancedTabDefs`, `modelFields`, `memoryEstimateFields`.

## i18n-data.js

The translation payload: `LANGS` (the 20 most-spoken languages, each with a country-flavoured
emoji glyph) and the `messages` dict. At 11.7k lines this is 44% of the old `app.js`, kept as one
module on purpose — it is data, and splitting it buys nothing. Strings missing from a language
fall back to English via `t()`.

- Owns: nothing mutable.
- Key exports: `LANGS`, `messages`.

## i18n.js

Language and theme. `lang`/`theme` are module-local lets persisted in localStorage
(`llamacppAdminLang`/`llamacppAdminTheme`) and only written here (the dropdown handler sets `lang`
then calls `renderAll()`). `applyLanguage()` walks the `data-i18n` attribute family.

- Owns: `lang`, `theme`, the language dropdown.
- Key exports: `t`, `fieldHelp`, `labelWithTip`, `helpTip`, `applyLanguage`, `applyTheme`, `setupLangSelect`.

## onboarding.js / onboarding-tours.js / onboarding-strings.js

Onboarding tours behind the `? Tour` header button (marked `data-ob-tour`;
static HTML on index/hf, part of the standalone header template in routers.js
on the kanban — a document-level click delegation survives re-renders, with a
floating fallback if no header button exists). `onboarding.js` is the
dependency-free engine (spotlight overlay + card, keyboard nav, skips steps
whose anchor is missing/hidden, auto-start once per page via
`caravanTourSeen:<page>` in localStorage, single active tour) — hf.js reuses
it without pulling i18n-data. The welcome step embeds an interface-language
picker (`setLang` from i18n.js; en/ru toggle on hf). `onboarding-tours.js` declares the board, config
editor (te-/tr- modal, picked automatically when one is open) and kanban
tours; `onboarding-strings.js` holds the EN/RU texts and is merged into
`messages` at import (other languages fall back to English via `t()`).

- Key exports: `createTour`, `mountTourButton`, `autoStartOnce` (engine); `initOnboarding` (tours).

## state.js

See "State model" above. 35 lines; read them.

- Owns: `state`, `topology`, `ui`.
- Key exports: `state`, `topology`, `setState`, `setTopology`, `ui`.

## utils.js

DOM/format/HTTP helpers with zero app-state and **zero i18n** dependencies: `$` (getElementById),
`escapeHtml`, `api()` (fetch wrapper that throws `data.error` on non-OK), `toast`, `pill`,
byte/MiB formatters, tooltip positioning. This is the entire import surface of `hf.js` — keep it
i18n-free so the HF page never pulls the 11.7k-line translations module.

- Owns: nothing mutable.
- Key exports: `$`, `escapeHtml`, `api`, `toast`, `pill`, `formatMemoryMiB`, `bindTooltips`.

## dialogs.js

Styled in-app replacements for `window.confirm()`/`window.prompt()`: Promise wrappers over the
shared `#confirmOverlay` dialog. Native dialogs block the renderer (they froze CDP evaluation
during a live audit once) and look foreign — nothing in the app should call them directly.

- Owns: the pending-dialog resolver.
- Key exports: `appConfirm`, `appPrompt`.

## dialog-llamas.js

Animated pixel llamas for the shared confirm dialog: scene kinds match the action being confirmed
("delete" stomps a crate flat, "change" nose-flips a toggle, "start" launches a rocket, a neutral
idle for the rest). Pure presentation over the dialog markup.

- Owns: the scene timers.
- Key exports: `initDialogLlamas` (scene selection is internal — it keys off the confirm text).

## main.js

The entry point for both board pages. On `DOMContentLoaded` it applies language/theme, then either
runs `initRouterStandalonePage()` (when `window.ROUTER_STANDALONE` is set) or wires the full
board: modal buttons, the Escape/Ctrl+Enter keymap, the global `pointermove`/`pointerup` handlers
that drive cable drags (hit-testing via topology-dnd), resize/scroll/ResizeObserver cable
redraws, all launch-form input listeners (main and `te-` prefixed), then `loadState()` and the
60 s / 24 h stats intervals.

- Owns: the DOMContentLoaded wiring only.
- Key exports: none (side-effect module; both pages load it as the module entry).

## models-page.js

`/models` page entry: the tree of downloaded GGUFs (model → author → quant → files) with size
rollups, which cells reference each file, and deletion of the unreferenced ones. Data:
`/api/models/unused` + `/api/models/disk`; deletion goes through `/api/models/gc`, which refuses
referenced files server-side too.

- Owns: the page's selection state.
- Key exports: none (page entry).

## system-page.js

`/system` page entry: tabs over the Controller / llama.cpp / Security / Diagnostics panels (the
former System modal) plus a hero strip with the numbers an operator checks first. The section
renderers are shared with `system-panels.js` — this file only orchestrates the page.

- Owns: the tab state.
- Key exports: none (page entry).

**Launch form**

## form.js

The launch-config form: renders field groups from the constants definitions, model comboboxes
(`makeModelCombobox` + `mc*` helpers), chat-template options and hints, model insight with family
recommendations, Gemma-4/Qwen autofill. `readConfigForm(pfx)` reads the DOM back into a config
object and is the shared read path for the main form and the `te-`/`tr-` modals.

- Owns: no cross-module state (form state lives in the DOM).
- Key exports: `readConfigForm`, `renderFields`, `renderModelSelects`, `makeModelCombobox`, `modelsByPath`, `renderChatTemplateOptions`, `syncToggleLabel`.

## memory.js

VRAM/RAM estimation for the launch form: KV-cache size per cache type, batch buffers, total
runtime estimate, and fit checks. Sizing is done against **free** VRAM (`gpuFreeMiB` prefers
nvidia-smi's `memory.free`, falls back to total−used), not total. Also resolves the compute target
(which GPUs, or CPU cores/RAM) for a form prefix. Pure functions over `state`/`topology`.

- Owns: nothing mutable.
- Key exports: `estimateKvCacheGb`, `estimateRuntimeMemoryGb`, `gpuFreeMiB`, `vramFit`, `ramFit`, `applyComputeTarget`, `refreshComputeTarget`.

## favorites.js

Starred launch-form fields: a global set persisted server-side via `/api/config-favorites`.
Canonical inputs stay in their home tabs (they are what `readConfigForm`/preview read); the
Favorites tab shows lightweight proxy controls that two-way-sync with the canonical input by
dispatching its events. Drag-to-reorder included.

- Owns: the favorites set (module-local, server-persisted).
- Key exports: `getFavFields`, `toggleFavorite`, `attachFavStar`, `renderFavoriteMirror`, `refreshFavoritesPanel`, `wireFavoriteDnd`.

## command-preview.js

Live llama-server command preview. The command is built by the single source of truth on the
controller (`build_llama_args`): `renderCommandPreview(pfx)` debounces 160 ms, POSTs the current
form to `/api/llama-command-preview`, discards stale responses via a per-prefix sequence counter,
then LCS-diffs the returned tokens against a baseline — the running controller service's cmdline,
or (for `te-`/`tr-` modals) the cell's own current command set through `setEditCurrentCommand()`.
Changed tokens highlight, removed flags strike through, and save buttons get `cmd-dirty`.

- Owns: `_cmdPreviewTimers`, `_cmdPreviewSeq`, `_cmdBaselineTokens` (per-prefix).
- Key exports: `renderCommandPreview`, `renderPreviewTokens`, `splitCommand`, `lcsPreviewIndexes`, `effectiveModelsDir`.

**Board**

## topology-render.js

The render orchestrator — see "Render & polling pipeline" above for the full mechanics.
Everything that redraws the board goes through this module; nothing else should rebuild whole
lanes with raw `innerHTML`.

- Owns: `activeView`, `_topologyRenderPending` (setter `markTopologyRenderPending`), `_lastStructureFingerprint`, `_lastRuntimePanelHtml`.
- Key exports: `renderAll`, `renderTopology`, `refreshTopology`, `applyTopologyUpdate`, `syncTopologyLive`, `topologyStructureFingerprint`, `topologyInteractionActive`, `flushPendingTopologyRender`.

## topology-activity.js

Derives per-card activity/health classes from `topology` + `ui.latestSystemMonitor` and patches
them onto the existing DOM. `refreshTopologyActivityState()` is fingerprinted
(`buildActivityFingerprint()` against `ui._lastActivityFingerprint`) so the class walk only runs
when something actually started/stopped/errored. Also renders the live runtime panels (cached per
group in `_lastRuntimePanelHtml`), the sticky-bar slot animations, and queue/duration helpers.

- Owns: `stickySlotAnims`, `_stickyBarRaf`, the activity/health class lists.
- Key exports: `refreshTopologyActivityState`, `setTopologyActivityClass`, `updateTopologyRuntimePanels`, `topologyStatusPill`, `sortedTopologyAgents`, `topologyQueueRuntime`.

## topology-proxies.js

Agent cards on the client hosts (agents grouped per host with their primary/fallback routes) and
the proxy-port registry: the route form (render/read/save via `/api/agent-proxies/config`), route
sorting, connect actions (proxy→llama, proxy→cloud), the per-group cloud-fallback toggle.
Stateless — its open/editing flags live in `ui` (`topologyProxyFormOpen`, `topologyProxyEditingId`).

- Owns: nothing mutable.
- Key exports: `topologyAgentCard`, `topologyGroupedAgents`, `topologyAssignmentsForHost`, `renderTopologyProxyForm`, `saveTopologyProxyForm`, `sortedTopologyRoutes`.

## topology-nodes.js

The host-centric nodes view: per-node cards with server cards (lifecycle bar, error
classification, uptime), GPU rows with VRAM bars and sparklines, the incidents modal, and the
models bar (models-dir edit). `parkLaneStats()` / `mountNodeTelemetry()` move the live chart
elements out of and back into the controller node around `innerHTML` rebuilds so their canvases
survive. Collapsed nodes persist to localStorage.

- Owns: `topologyNodesViewOn`, `_collapsedNodes`, `_incidentsModalOpen`, `_modelsDirEditing`.
- Key exports: `nodesLaneHtml`, `nodeServerCardHtml`, `applyNodesViewMode`, `mountNodeTelemetry`, `parkLaneStats`, `classifyLlamaError`, `renderModelsBar`.

## cables.js

SVG cable drawing between board cards: board-space rect/point helpers, bezier path builders,
per-id accent colors, status classes, hover highlight with a timed clear, `drawLiveTopologyCable()`
(follows the pointer during a drag) and `drawTopologyCables()` (full redraw into the board's SVG
layer).

- Owns: `_cableHighlightClearTimer`.
- Key exports: `drawTopologyCables`, `drawLiveTopologyCable`, `topologyCablePath`, `topologyAccentStyle`, `highlightTopologyCable`.

## topology-dnd.js

The one big delegated pointer/click router for the whole board. `bindTopologyDragAndDrop()` is
**re-bound onto the fresh DOM after every `renderTopology()`** and wires every click target:
modal open/close, registry edits, schedule-grid painting, cloud/usage/history modals, canvas
hand-offs, and the cable drag start points. The hit-testing helpers (`topologyLlamaAtPoint`,
`topologyRouterInputAtPoint`, `topologyCloudAtPoint`) are consumed by `main.js`'s global
pointermove/pointerup.

- Owns: the drag state `topologyPointerDrag` (+ `clearTopologyPointerDrag`), the schedule-paint state (`topologyScheduleRouterId`, `topologySchedulePaintOutput`, `topologyScheduleGrid`, `_schedulePainting`), and several modal flags: `topologyProxySummaryOpen`, `topologyLlamaDetailOpen`, `topologyGpuModalOpen`, `topologyRouteDetail`.
- Key exports: `bindTopologyDragAndDrop`, `clearTopologyPointerDrag`, `topologyLlamaAtPoint`, `topologyRouterInputAtPoint`, `topologyCloudAtPoint`.

**Router canvas**

## canvas.js

The router workspace canvas: free-form node graph with input clients (left), router rules
(centre), outputs (right). Groups an agent's primary+fallback proxy ports into one block, persists
node positions per router in localStorage, pans/zooms via `_cvView`/`_cvPos` (foreign writers must
use `cvSetViewport`), draws connectors, renders queue and schedule node bodies with history panes,
and paints weekly schedule grids. Queue-node live stats are computed from `ui.latestSystemMonitor`
— this is what the standalone kanban's 1 s poll drives.

- Owns: the `_cv*` family — viewport (`_cvView`, `_cvPos`), drag (`_cvDrag`), queue/schedule history panes and caches, schedule paint state, agent-map caches.
- Key exports: `cvSetViewport`, `canvasLoadPositions`, `canvasSavePositions`, `drawCanvasConnectors`, `bindCanvasInteractions`, `queueNodeLiveStats`, `syncQueueNodesLive`.

## routers.js

The router card on the board, the router detail popover, and the outputs panel (right rail):
local llama servers plus cloud providers, each routable target carrying one shared default radio.
`saveRouters(mutator)` deep-copies `topology.routers`, applies the mutation, POSTs to
`/api/agent-proxies/routers`, applies the returned topology when present and re-renders — with a
marching-ants "saving" indicator (`_setRoutersSaving`) since the workspace auto-persists.
`rebindProxyRouter()` is the drop handler for dragging a proxy onto a router.

- Owns: `_routersSaving` counter, `topologyOutputsCloudExpanded`, the cloud-expose chain/timer.
- Key exports: `saveRouters`, `renderTopologyRouterCard`, `renderTopologyRouterDetail`, `renderRouterOutputsPanel`, `rebindProxyRouter`, `routerById`.

**Modals & panels**

## topology-modals.js

The detail/config modal renderers: llama server detail, client detail (open/refresh), the GPU
logs/raw-API modal, the raw-config viewer, the agent openclaw-config modal, the priority and
queue-priority modals (threshold timelines, per-proxy edits), and the weekly schedule modal with
grid↔rules conversion. Renderers return HTML strings that `renderTopology()` injects;
topology-dnd wires their buttons.

- Owns: the modal flags and edit buffers: `topologyPriorityModalOpen`, `topologyQueuePriorityEdits`, `topologyRawConfig*`, `topologyAgentConfig*`, `queueThresholds`, `topologyClientDetailFor`.
- Key exports: `renderTopologyLlamaDetail`, `renderTopologyClientDetail`, `openClientDetail`, `renderTopologyGpuModal`, `openQueuePriorityModal`, `openRawConfigViewer`.

## llama-edit.js

The `te-` (controller cell) edit modal: applies the saved config to the `te-` form, command
presets, the backups list (load/delete with confirmation), snapshots, the cell-kind overlay, and
`saveTopologyLlamaConfig(restart)`. Sets the preview baseline via `setEditCurrentCommand()` so the
diff compares against the cell's own command, not the controller service. Also owns the shared
confirm modal (`openActionModal`, `openToolbarConfirm`, `closeConfirmModal`, resolving through
`ui.pendingConfirm`).

- Owns: `teLlamaFormReady`, `_teCellPort` (which cell the modal edits), `pendingBackupDelete`, `_editCmdSeq`, `COMMAND_PRESETS`.
- Key exports: `openTopologyLlamaEdit`, `closeTopologyLlamaEdit`, `saveTopologyLlamaConfig`, `renderBackups`, `openActionModal`, `closeConfirmModal`, `setEditCurrentCommand`.

## remote-cells.js

Remote cell lifecycle on client hosts: reserve cells, start/stop via `/api/topology/client-llama/*`,
the `tr-` remote edit form (per-host model caches, GPU pickers, nvidia-smi source buttons), remote
backups and snapshots, model-cache purge, discovery add, and client/agent/slot deletion. Optimistic
pending-start placeholders drive `startRemoteStartWatch()` — a 2 s `refreshTopology()` loop that
stops itself when nothing is starting, with a 240 s timeout turning placeholders terminal.

- Owns: the pending-op collections — `_pendingRemoteStarts` (Map), `_stoppingHosts`, `_deletingSlots`, `_reservingCells`, `_newReservedCells`, `_stoppingCells`, `_expandedCellCfgs` — plus `_remoteStartWatchTimer`, `_nvidiaSmiSource`, the `_tr*` form state.
- Key exports: `reserveServerCell`, `submitRemoteLlamaStart`, `submitLlamaStop`, `startRemoteStartWatch`, `remoteStartupInFlight`, `openLlamaRemoteEdit`, `bindServerSlotControls`.

## cloud.js

Cloud provider accounts and blocks: the provider picker (`CLOUD_PICKER_META` presets), the account
modal (API key or OAuth subscription — `startCloudOauthLogin` + `pollCloudOauth` at 2 s), the
block modal (model selection per account), model-list fetches with caching, save/delete. The
account modal's open/form state lives in `ui` (`topologyCloudModalOpen`, `topologyCloudPickerOpen`,
`topologyCloudForm`); the block modal's flags are module-local because only cloud.js writes them.

- Owns: `topologyCloudBlockModalOpen`, `topologyCloudBlockForm`, `topologyCloudBusy`, `topologyCloudModelCache`.
- Key exports: `renderTopologyCloudProviders`, `openCloudProviderModal`, `openCloudAccountModal`, `saveCloudAccount`, `saveCloudBlock`, `startCloudOauthLogin`, `prefetchAllSubscriptionModels`.

## usage-stats.js

The usage & spend modal: overview/account/local scopes (scope, expanded row and day range live in
`ui.usageStats*`), model tables, pricing edits (`saveApiPrice`, `saveLocalPricing`) and provider
cost fetches — API costs, OpenRouter limits, proxy spend, subscription usage — cached with no TTL
(fetched once, refreshed via button).

- Owns: `usageStatsData`, `apiCostsCache`, `openrouterLimitsCache`, `proxySpendData`, `subscriptionUsageCache`, `usageStatsApiPriceEdit`.
- Key exports: `openUsageStatsModal`, `renderUsageStatsModal`, `fetchUsageStats`, `fetchApiCosts`, `saveApiPrice`, `saveLocalPricing`.

## history.js

The request-history modal over `/api/agent-proxy-logs`: a Requests tab (finished events) and an
Events tab (raw), date selection, client/via/status filters, and a per-row detail popup.

- Owns: `historyRows`, `historyEventRows`, `historyTab`, `historyCurrentDate`, the filter values.
- Key exports: `openRequestHistory`, `closeRequestHistory`, `loadRequestHistory`, `renderHistoryTable`, `openHistoryDetailPopup`.

## system-panels.js

Controller-level panels: service summary, runtime, CPU/GPU, section tips, OpenClaw links, project
git branch, Known Problems, and the System info modal (where the llama.cpp build panel and Known
Problems moved when the Classic view was retired), plus the llama.cpp check/update/revert and
repair-user-service flows. Stateless.

- Owns: nothing mutable.
- Key exports: `renderService`, `renderRuntime`, `renderCpu`, `renderGpu`, `openSystemInfoModal`, `checkLlamaCpp`, `openUpdateLlamaModal`, `revertLatest`.

## proxy-routes.js

The flat agent-proxy route list editor (the row-based add/edit/toggle/delete UI, reading and
saving the same `/api/agent-proxies/config` route list that the board's proxy form writes).

- Owns: `editingAgentProxyRouteIndex`.
- Key exports: `renderAgentProxyRoutes`, `addAgentProxyRoute`, `saveAgentProxyRoute`, `toggleAgentProxyRoute`, `deleteAgentProxyRoute`.

**Data & charts**

## polling.js

State loading and every polling loop: `loadState()`/`saveConfig()`/`action()` against
`/api/state`, `/api/config`, `/api/action`; the self-rescheduling live-refresh chain; the
hover-driven monitor drawer (nvidia-smi with a localStorage-persisted interval, routable to a
remote client); and the 1 s system/topology monitors that feed `ui.latestSystemMonitor` (which in
turn drives activity classes, runtime panels and the kanban queue nodes).

- Owns: every timer and inflight guard — `liveRefreshTimer`, `liveRefreshInflight`, `monitorState`, `systemMonitorTimer`, `topologyMonitorTimer` — plus `tokenSpeedState`.
- Key exports: `loadState`, `saveConfig`, `action`, `scheduleLiveRefresh`, `startTopologyMonitor`, `startSystemMonitor`, `bindMonitorDrawer`, `formatTps`, `formatCtxTokens`.

## charts.js

Canvas 2D chart rendering: metric charts, GPU/token-speed/VRAM/power history, node telemetry rows
with mini sparklines, the chart expand modal, route-activity drawing and hover tooltips. Charts
are redrawn by the monitor tick and once per full render (canvases have zero size while their
`<details>` card is closed — the toggle handler in main.js redraws on open).

- Owns: `_routeActivityDrawState`, `CHART_EXPAND_CONFIGS`, `_chartExpandType`, hover-binding flags.
- Key exports: `drawMetricChart`, `drawTopologyGpuHistory`, `drawTopologyTokenSpeedHistory`, `drawTopologyServerStats`, `miniSparklineSvg`, `systemSamples`.

## model-meta.js

Model-name parsing (`parseModelName`), model/projector icons, per-server bench fetches, and the
Artificial-Analysis score queue (batched, self-pumping). Fetches `/api/proxy-daily-stats` and
`/api/model-pricing` into module caches that renderers read synchronously.

- Owns: `proxyDailyStats`, `modelPricing`, `aaScores`, `serverBenchCache`, the AA queue internals.
- Key exports: `parseModelName`, `topologyModelIcon`, `fetchProxyDailyStats`, `fetchModelPricing`, `fetchServerBenchIfNeeded`, `aaBadgeHtml`.

**HF page**

## ../hf.js

The entire HuggingFace browser page (`static/hf.js`, served at `/hf.js`): token status/save, repo
search with filters, sort and inferred badges (params/instruct/vision/audio/uncensored),
server-persisted favorites, per-repo GGUF file lists with local-presence checks, background
benchmark loads, a download queue with progress, and local-file deletion — all against the
`/api/hf/*` endpoints. It imports exactly two names — `$` and `escapeHtml` from `/js/utils.js` —
and must stay that way: anything more risks dragging app state or the translations payload into a
page that needs neither. Functions are file-local; nothing is exported.

- Owns: all its page state (module-scope consts/lets).
- Key exports: none (page-scope module).

## Invariants for contributors

1. **Never rebind an imported binding** — it throws `TypeError` at runtime under ES modules.
   Rebind through the owning module's setter: `setState`/`setTopology` (state.js), `cvSetViewport`
   (canvas.js), `markTopologyRenderPending` (topology-render.js). Before shipping, audit for
   `importedName =` assignments (the check that caught the fourteen sites fixed in `9de2510`).
2. **New cross-feature flags go into `ui`** in state.js — property writes need no setters. A
   mutable that is written by exactly one module stays a module-local exported `let` there.
3. **utils.js stays i18n-free and app-state-free.** It is hf.js's only import; adding an
   `i18n-data` (or `state`) dependency would pull 11.7k lines of translations into the HF page.
4. **CSS files are cascade-ordered contiguous slices** of the old `styles.css`. Keep the `<link>`
   order identical on all three pages, add rules in the file they belong to, and never regroup
   rules across files — equal-specificity rules depend on their order.
5. **Function names stay unique across all modules.** The split was verified by a census: 572
   functions, each defined exactly once. Keeping names unique keeps cross-module imports
   unambiguous and greps trustworthy.
6. One-line-body functions (`function f(x) { return y; }`) are fine — the splitter bug that once
   swallowed them into the preceding item is fixed. The split tooling in `scripts/refactor/`
   (`list_top.py`, `extract_leaves.py`, `split_modules.py`, `split_css.py`) documents exactly how
   the original file was sliced; it ran once and is not meant to run again.
