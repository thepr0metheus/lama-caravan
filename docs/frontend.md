# Frontend module reference

The UI is 46 native ES modules under `static/js/`; six of them (`hf-*.js`) are the `/hf` page.
There is no bundler, no framework, no npm and no build step: the browser loads `/js/main.js` as a
`type="module"` script and follows real `import` statements from there. The core was split out
of a single 26,720-line `static/app.js` (the split tooling survives in `scripts/refactor/`).

Five pages share the code:

| page | route(s) | entry | notes |
|---|---|---|---|
| `static/index.html` | `/board` (`/` and `/index.html` redirect) | `/js/main.js` | the topology board (main app) |
| `static/kanban.html` | `/kanban` (`/router` redirects) | `/js/main.js` | standalone router workspace; an inline classic script sets `window.ROUTER_STANDALONE = true` — it runs immediately, before the (deferred) module executes, so `main.js` sees the flag. Deep-link a router with `?id=<routerId>` (default `router:default`) |
| `static/hf.html` | `/hf` | `/js/hf-page.js` | HuggingFace model browser: search and filters over the list on the left, the repository on the right, the selection and downloads in a dock along the bottom; imports only `utils.js` and `onboarding.js` from the shared code |
| `static/models.html` | `/models` | `/js/models-page.js` | places (this disk, libraries), filters and the model tree in columns: sizes here and in the library, cells, downloads, moves, cleanup |
| `static/system.html` | `/system` | `/js/system-page.js` | Controller / llama.cpp / Security / Diagnostics tabs (the former System modal) |

Serving: the Python backend (`caravan/admin/routes.py`) serves every static file through
`Handler.send_file`, which sets an mtime+size `ETag` and `Cache-Control: no-cache` — the browser
revalidates every load and gets a 304 when unchanged, so a redeploy is picked up immediately and
**no cache-busting `?v=` params are needed** (the favicon's `?v=2` is the one deliberate holdout).
`/js/<name>` and `/css/<name>` are prefix routes; adding a module is just adding a file.

CSS is 10 cascade-ordered files under `static/css/`, linked in this exact order on every page:
`base`, `topology-board`, `canvas`, `modals`, `cards`, `form`, `monitor`, `nodes`, `hf`,
`onboarding` (models/system skip `hf`, the only page-specific slice) — plus `hf-page.css`,
linked last and only on `/hf`: the page's own layout, written for it rather than sliced. They are
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

- `renderAll()` — language/theme, the header git chip, the System sections this page has, and
  `renderTopology()`. Runs on load and on a language switch. (The classic single-server view and
  its panels went with the controller's own cells in step 6.9.)
- `renderTopology()` — a **full `innerHTML` rebuild** of the board: the clients column, the router
  stack plus every modal shell, the nodes lane, GPU cards. It then re-binds all delegated handlers
  (`bindTopologyDragAndDrop()`) and per-render buttons. A full rebuild resets CSS animations and
  drops an in-progress drag, so it must not run on every background tick.
- `refreshTopology()` — `GET /api/topology` → `setTopology()` → `applyTopologyUpdate()`, which decides:
  1. user mid-interaction (`topologyPointerDrag`, proxy form open, canvas drag) → set
     `_topologyRenderPending` and do nothing; `flushPendingTopologyRender()` runs when the
     interaction ends;
  2. `topologyStructureFingerprint(topology)` differs from the last render → full `renderTopology()`;
  3. otherwise → `syncTopologyLive()` patches only the volatile numbers in place (a silent
     scout's report age on its node, CPU/RAM, t/s, ctx, download %, GPU util/VRAM bars,
     sparklines) and redraws cables — DOM, animations and drags survive.

The fingerprint covers graph identity only: which cards/handles/cables exist and how they connect
(clients and their agents, hosts and whether their scouts answer, servers with their **phase**,
GPUs, proxies, cloud providers, view mode, open modals).
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
- `/api/agent-proxies/config` (proxy-port form) returns `{ok, config, monitor}`
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

Launch-form field definitions for the cell editor (the `tr-` form): field lists, tab layouts and
optional-toggle defaults. Pure data plus one mutable Set. (The controller's host-id sentinel and the
Gemma-4 companion defaults of the classic form went in step 6.9.)

- Owns: the field taxonomy; `dirtyOptionalToggles` (cleared by `loadState`).
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
`caravanTourSeen:<page>` in localStorage, single active tour) — the /hf page
reuses it without pulling i18n-data. The welcome step embeds an interface-language
picker (`setLang` from i18n.js; on /hf the page's own list of all twenty). `onboarding-tours.js` declares the board, config
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
byte/MiB formatters, tooltip positioning. The /hf modules import from it (`escapeHtml`,
`markPageState`) — keep it i18n-free so the HF page never pulls the translations module.

- Owns: nothing mutable.
- Key exports: `$`, `escapeHtml`, `api`, `toast`, `pill`, `formatMemoryMiB`, `bindTooltips`.

## dialogs.js

Styled in-app replacements for `window.confirm()`/`window.prompt()`: Promise wrappers over the
shared `#confirmOverlay` dialog. Native dialogs block the renderer (they froze CDP evaluation
during a live audit once) and look foreign — nothing in the app should call them directly.

(`appChoose`, the same dialog with more than two answers, served one question — where a
controller cell's start reads its model from — and went with it in step 6.9.)

- Owns: the pending-dialog resolver.
- Key exports: `appConfirm`, `appPrompt`.

## dialog-llamas.js

Animated pixel llamas for the shared confirm dialog: scene kinds match the action being confirmed
("delete" stomps a crate flat, "change" nose-flips a toggle, "start" launches a rocket, "stop" lies
down to sleep, "create" stacks crates, "move" — a pack llama carries a kraft parcel to a library
cabinet, tips it into the hatch over its own bowed head, a spark says it is checked, the hatch shuts
and the next parcel comes down). Frames are pure data (`sceneFrames`, `sceneSky`), so a snapshot
holds a scene to its story without a browser: the move scene's arc never passes through the llama,
its loop is seamless, and its pack is never the colour of the llama carrying it.

- Owns: the scene timers.
- Key exports: `initDialogLlamas` (scene selection is internal — it keys off the confirm text).
- Kept as functions by decision (OOP rewrite, decision 19, 2026-09-05): pixel lists and stateless
  timelines, no caller that depends on a result, no defect history — classes would add nothing,
  and a value snapshot would only pin the drawing's coordinates. `check_oop_contract.py` reads
  this line as the module's reason to stay off the class rule.

## main.js

The entry point for both board pages. On `DOMContentLoaded` it applies language/theme, then either
runs `initRouterStandalonePage()` (when `window.ROUTER_STANDALONE` is set) or wires the full
board: modal buttons, the Escape/Ctrl+Enter keymap, the global `pointermove`/`pointerup` handlers
that drive cable drags (hit-testing via topology-dnd), resize/scroll/ResizeObserver cable
redraws, then `loadState()` and the 60 s / 24 h stats intervals. The cell editor's own form
listeners are bound by remote-cells.js when it opens; the classic form's and the controller cell
editor's went with the controller's own cells in step 6.9.

- Owns: the DOMContentLoaded wiring only.
- Key exports: none (side-effect module; both pages load it as the module entry).

## models-page.js

`/models` page entry: every model this controller can serve, wherever it lies — the tree of model
files (model → author → quant → files) with which cells use each file, downloads, moves and
deletion of the unreferenced ones. Data: `/api/models/unused` (this disk), `/api/model-stores/files`
(the libraries), `/api/models/freshness`, `/api/hf/download/jobs`; deletion goes through
`/api/models/gc`, which refuses referenced files server-side too. A model branch and an author
branch carry 🤗 to `/hf`: an author branch is a repository (`/hf?q=<author>/<model>` opens it), a
model branch searches its name; folders not laid out as `<model>/<author>/<quant>` have none.

The page is a side column and a main column. The side steers the list: the PLACES (drawn by
`model-stores.js` — "All models", this disk, each library, with what it holds and its room), the
FILTERS (on their way, unused, used by cells, newer on Hugging Face — each with the count of what it
would keep in the chosen place), and the Hugging Face check with its settings in one box. The main
column is the chosen place's summary (also `model-stores.js`), a line with how much lies unused
beside the button that picks exactly those, everything on its way and the name filter, then the tree
in columns — name, status, size here and in the library (one size column once a single place is
chosen), age, ⇢. Nesting is indentation inside the name cell, so every size stays under its header.
The selection bar floats over the list only while something is picked.

- Owns: the last answers (so another place, filter or name redraws the list without asking the
  server), the filter and the name (`view`), and the branches that were open before a filter or a
  name narrowed the list — narrowed, the list opens every branch it keeps, and clearing it gives back
  what was open.
- Key exports: none (page entry).
- `refresh()` fetches and `draw()` renders; markup is replaced only when it changed (`paint`), because
  markup replaced under a pressed mouse button swallows the click, and the page draws itself after
  every answer.
- Mounts the places panel (`model-stores.js`) into `#mdlStores` with `#mdlSummary`, and the move
  tracker (`model-moves.js`) on the tree, the line `#mdlMovesSum` and the button, and connects them:
  the button and every ⇢ read the libraries off the panel (a changed set of libraries redraws the
  tree), a file that arrived redraws the tree and re-measures the stores, a chosen place redraws the
  list (`onScope`), and the line "⇢ N files on their way" first shows exactly those — every place,
  the "On their way" filter, no name (`onReveal`). What a move says sits on the rows: a travelling
  file shows its bar instead of a checkbox and the download buttons, a note from a finished move sits
  in its status, ⇢ sits in the last column of every file and branch that can move, and a folded
  branch carries its progress. The selection survives a redraw.
- Everything that moves, deletes or writes over a model asks first: Delete selected, every move
  (the button, ⇢ on a file, a branch or a library row, the list of libraries, Stop), "fetch new"
  (it says whether the current build is kept) and "revert" (the newer file is deleted). A declined
  question sends nothing.
- Hands the panel what this disk holds and the model families of every place (`holds`): the tree
  already counted them, and a second measurement would be a second number that can disagree.
- Draws the libraries' files in the same tree: a file only a library holds takes its place marked
  "📚 <library>" and has no checkbox (it is not here to delete); a file here that a library holds too
  gets a 📚 and its bytes in both size columns. It carries ⇢ like any other row, with its library as
  the source — back to this disk, or on to another library.

## model-stores.js

The places panel on `/models`: every place models live — this controller's own directory and the
libraries the operator added (a NAS share mounted over NFS, for instance) — in two drawings. The
list in the side column: "All models" with every place's bytes together (once this disk is counted),
then each place with its state (a dot when available, a word otherwise: low on space, read-only,
another library here, not mounted, folder not found, not answering), what it holds, how full it is
and its free space, and "Add library". The summary over the tree: under "All models" one bar with a
segment per place, a legend with each place's bytes and files, and a card per place with its room and
"Open"; for one place, its state, path (✎ for this disk's models directory, "remove" for a library),
files, bytes and model families, what is inside a library, and its room. Data: `/api/model-stores`;
adding and removing: `/api/model-stores/add` and `/api/model-stores/remove`. A library that is not
mounted draws no numbers: they would be the local disk's, under the bare mount point. The page never
looks inside a store itself — the server does, from a child process with a deadline
(`caravan/admin/model_stores.py`).

- Owns: the panel's copy of the last answer (`null` until the first one arrives), the chosen place
  (`scope`: `all` or a store id; a place that disappears hands the list back to `all`), the open
  editors, and the markup it last drew (unchanged markup is left in place, and what is typed survives
  a redraw).
- Key exports: `StoresPanel` (class), `mountStores(root, opts)` (the page's face; `opts.summary` is
  the summary's element, `opts.onChange` hears every answer — the move button needs the libraries —
  `opts.onScope` hears a chosen place, `opts.onSavePath` saves a new models directory).

`MountHint` (same module) turns the `mount` facts into the line a place shows when it does not
answer — what it is mounted from, whether that machine replies — and the one command that takes the
next step (`sudo mount …` when fstab names it, `umount -l && mount` when the machine went silent,
nothing at all when there is nothing to run). No facts means no line: the server sends them only for
a store that is not ok, so the page holds no second rule about which states deserve an explanation.
✎ beside a library's path edits it in place and posts `/api/model-stores/repath`; a refusal is shown
as it came and the box stays open.

## model-moves.js

Moves into a library on `/models`, drawn where the files are — there is no panel of jobs. A file on
its way carries its bar on its own row of the tree: where to, the pass (first the copy, then the
check — the copy is read back from the library and compared before the local file is deleted), the
speed and the time left (from the work done between two answers, smoothed; worded by `pace.js`), and Stop. A checked
copy counts down the wait before the copy here is deleted (`removeIn`, counted by the server, so
another clock does not matter). A pass the library holds up turns red and says why. A folded branch says how many of its files travel and how
far; one line over the list counts everything on its way and, asked, lets the page show exactly those
files (`opts.onReveal`) before it opens their branches and brings the first bar into view. A
finished move shows in the tree itself — the file becomes a 📚 row; a move that left a file here says
why on that row until the note is hidden (per browser, in `localStorage`). ⇢ on a row or a branch
moves just those files — straight to the one place they can go, or through a short list with free
space when there are several; a library's row carries its store, so its ⇢ sends the file back to
this disk or on to another library. The "Move to <library>" button in the selection bar, next to
"Delete selected", moves the picked ones, and only this disk's files carry a checkbox.
A model that is a whole folder — a whisper HF cache, a safetensors checkpoint — is one row like any
other, marked 📁, and travels as one item: the server walks it, copies every file inside, plants the
links back as links and deletes the folder only once all of it is proven. The confirm says how many
of the picked items are folders, since one row can be thousands of files on the wire.
Data: `/api/model-stores/moves`, polled every 1.2 s while something moves; starting:
`/api/model-stores/move`; stopping: `/api/model-stores/moves/cancel`. Starting and stopping ask
first, and Stop says so when the move carries more than its own file. The job runs on the server
(`caravan/admin/store_moves.py`), so its progress survives a reload and shows in a second tab.

- Owns: the last answer (`null` until the first one), each open job's speed, the hidden notes, and
  the shape it last drew — bytes move the bars in place; a file arriving or staying redraws the tree.
- Key exports: `MoveTracker` (class), `mountMoves(opts)` (the page's face).

A model a cell NAMES and one a cell READS are different things on this page: the checkbox (delete)
goes by named, since removing a stopped cell's model breaks it silently, while ⇢ only needs that
nobody has the file open — a stopped cell's model travels and its start brings it back. Such a row
keeps its ✓, muted, and says so in its tooltip.

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
recommendations, Qwen template autofill. `readConfigForm(pfx)` reads the DOM back into a config
object — the read path of the cell editor (`tr-`). The prefix stays a parameter, so tests drive the
same code with any prefix; the classic form's Gemma modes, raw view and static fields went in 6.9.

- Owns: no cross-module state (form state lives in the DOM).
- Key exports: `readConfigForm`, `renderFields`, `renderModelSelects`, `makeModelCombobox`, `modelsByPath`, `renderChatTemplateOptions`, `syncToggleLabel`.
- A file only a library holds is offered like any other picker row, in its place among the files
  of this disk, marked `📚 <library>` (`model-in-library`).

## memory.js

VRAM/RAM estimation for the launch form: KV-cache size per cache type, batch buffers, total
runtime estimate, and fit checks. Sizing is done against **free** VRAM (`gpuFreeMiB` prefers
nvidia-smi's `memory.free`, falls back to total−used), not total. Also resolves the compute target
(which GPUs, or CPU cores/RAM) for a form prefix. Pure functions over `state`/`topology`.

The GPU tile also offers, under the card chips and **only while two cards or more are actually
picked**, how the model is divided between them (`split-mode.js`). With one card there is nothing
to divide, so the row is absent rather than inert.

- Owns: `_computeGpuDdOpen` (the multi-GPU dropdown's open state across re-renders).
- Key exports: `estimateKvCacheGb`, `estimateRuntimeMemoryGb`, `gpuFreeMiB`, `vramFit`, `ramFit`, `applyComputeTarget`, `refreshComputeTarget`.

## card-fold.js

Which cards on the board fold into a line, and which one floats open now. The two long
lanes — model cells and client agents — drew every card at full height: on 2026-09-23 the
controller had 24 cells of which 6 ran, and 14 client routes of which one had a fallback.
`CardFold` holds the operator's per-lane choice (`compact` or `full`, the lane-header switch
`board-density`), the cards pinned open, and the one rule for what is quiet enough to fold:
`cellQuiet` (running with nothing to report, or parked) and `agentQuiet` (has a route, not
stale, no incident). A card in motion or in trouble never folds. Automation
(`navigator.webdriver`) sees full cards by default. `FoldPeek` is the pointer and keyboard
side: the full card floats over the lane after the pointer rests 300 ms on its line (at once
on keyboard focus), a click on the line or 📌 pins it, ▴ folds it back, Escape closes; no card
floats while a cable is dragged. Delegated on the document once — the lanes are repainted
wholesale.

- Owns: `CARD_FOLD` (densities, pinned set, `peekKey` so a float survives a repaint); both
  persisted in `localStorage` (`boardCardDensity`, `boardCardPinned`) as a per-browser
  convenience.
- Key exports: `CardFold` (`density`, `toggleDensity`, `togglePin`, `mode`, `syncSwitches`,
  `cellQuiet`, `agentQuiet`), `FoldPeek` (`bind`), `CARD_FOLD`.

## card-rows.js

The folded line of a board card, and the slot that holds the line and the card. `CellRow` and
`AgentRow` only lay out facts the card computed — the name, the memory chip, the ▶ start
attributes, the route values — so the line and the card cannot disagree. The line owns the
cable's handle while folded: cables and drops find handles by `querySelector` and read their
rectangle, and a copy inside a hidden card would hand them zeros. `FoldSlot` holds the line
(which never moves) and the full card (which floats over the lane); pinned, it holds the card
in place with ▴. An agent's line shows only what is set — no dash placeholders, no empty
fallback. Values are still changed on the full card, where they always were.

`nodeServerCardHtml(node, s, { fold })` and `topologyAgentCard(…, { fold })` take the lane's
request; without it the card is drawn byte for byte as before. Styles: `static/css/fold.css`.

- Owns: nothing mutable.
- Key exports: `CellRow`, `AgentRow`, `FoldSlot`.

## split-mode.js

One value of llama-server's `-sm/--split-mode`, and what it means to say it: the labels, the
one-line hint, and the value a fresh multi-card selection gets. The four legal values live in
`constants.js` with every other field's value set (`fieldChoices.SPLIT_MODE`, which also fills the
Devices field's datalist); this module owns their meaning, so a fifth mode llama.cpp adds is named
in one place. `layer` hands whole layers to each card, which then take turns; `row` and `tensor`
cut every weight between the cards so they work at once — `SplitMode.PARALLEL`.

`SplitMode.DEFAULT` is `row`: two cards default to working at the same time. Not the newer
`tensor`, which llama.cpp itself marks EXPERIMENTAL — a default is what an operator gets without
asking for it. A mode already chosen survives re-picking a card; only a blank or an unknown value
is filled in. A value llama-server does not know is said out loud under the buttons with none of
them lit, rather than drawn as a fourth mode that simply is not highlighted.

- Owns: nothing mutable.
- Key exports: `SplitMode` (`known`, `parallel`, `label()`, `hint()`, `forCards(n)`, `html(hook)`).

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
then LCS-diffs the returned tokens against a baseline — the cell's own current command set
through `setEditCurrentCommand()`; a form that set none diffs against nothing. Changed tokens
highlight, removed flags strike through, and the editor's Apply button gets `cmd-dirty`.

- Owns: `_cmdPreviewTimers`, `_cmdPreviewSeq`, `_cmdBaselineTokens` (per-prefix).
- Key exports: `renderCommandPreview`, `renderPreviewTokens`, `splitCommand`, `lcsPreviewIndexes`, `effectiveModelsDir`.

**Board**

## topology-render.js

The render orchestrator — see "Render & polling pipeline" above for the full mechanics.
Everything that redraws the board goes through this module; nothing else should rebuild whole
lanes with raw `innerHTML`.

- Owns: `activeView`, `_topologyRenderPending` (setter `markTopologyRenderPending`), `_lastStructureFingerprint`, `_lastRuntimePanelHtml`.
- Key exports: `renderAll`, `renderTopology`, `refreshTopology`, `applyTopologyUpdate`, `syncTopologyLive`, `topologyStructureFingerprint`, `topologyInteractionActive`, `flushPendingTopologyRender`.

## suspect-banner.js

The banner over the board when a fresh llama.cpp build crashes cells: `LlamaSuspectBanner`,
one row per machine whose scout says so (`topology.hostSuspects`, scout 2.6+). The controller's
own row went with its cells in step 6.9: its machine's verdict comes from that machine's scout,
as one of these rows. A row offers the
newest archived build of another commit through the System page's confirmation
(`openRestoreBuildModal(id, build, host)` — with `host`, the machine's scout restores it) and a
dismissal the machine remembers for that build. A row the operator acted on goes at once and
stays gone while its incident is the same (machine, build, candidate, minute of the last crash);
the same rows are not redrawn on the next poll.

- Owns: `SUSPECT_BANNER` (the one instance); `applyTopologyUpdate()` calls its `render()`.

## topology-activity.js

Derives per-card activity/health classes from `topology` + `ui.latestSystemMonitor` and patches
them onto the existing DOM. `refreshTopologyActivityState()` is fingerprinted
(`buildActivityFingerprint()` against `ui._lastActivityFingerprint`) so the class walk only runs
when something actually started/stopped/errored. Also renders the live runtime panels (cached per
group in `_lastRuntimePanelHtml`), the sticky-bar slot animations, and queue/duration helpers.
Everything here reads the proxy's own records: a server card lights from the routes pointing at its
port, the GPU card from the requests in flight, slot pips fill in request order, and a request's
one-line summary has no speed or context size (its exact speed is in the route's token history).
Until step 6.9 the controller's own single server was read too — its busy slots, context, prompt
cache and last timings — and drawn onto whichever card or request matched it by port or by time.

- Owns: `stickySlotAnims`, `_stickyBarRaf`, the activity/health class lists.
- Key exports: `refreshTopologyActivityState`, `setTopologyActivityClass`, `updateTopologyRuntimePanels`, `topologyStatusPill`, `sortedTopologyAgents`, `topologyQueueRuntime`.

## topology-proxies.js

Agent cards in the clients lane (every agent of a client its own card, with its primary/fallback
routes) and the proxy-port registry: the route form (render/read/save via `/api/agent-proxies/config`), route
sorting, connect actions (proxy→llama, proxy→cloud), the per-group cloud-fallback toggle.
Stateless — its open/editing flags live in `ui` (`topologyProxyFormOpen`, `topologyProxyEditingId`).

- Owns: nothing mutable.
- Key exports: `topologyAgentCard`, `clientLaneAgentCards`, `topologyAssignmentsForHost`, `renderTopologyProxyForm`, `saveTopologyProxyForm`, `sortedTopologyRoutes`.
- An agent card makes no claim about whether the agent runs: no report says so any more (the
  scout knows hardware only). Every agent carries its ✕ (`agent-remove`); the dialog names the
  ports it leaves free (`savedAgentPorts` in remote-cells.js).
- The clients lane holds clients only — the operator's records. A client is one card: the lane's
  ＋ creates the client with its one agent under the same name, and the card is that agent's. No
  ＋ adds a second agent — it did, nobody used it, and the operator asked what it was (2026-09-24).
  A client with several agents from older data still shows a caption row with ✎
  (`clientNeedsCaption`). There is no "delete client" on the board: a card's own × removes that
  card, and the client goes with its last agent. The machine a scout reports is a node, not a
  card here.

## topology-nodes.js

The host-centric nodes view: per-node cards with server cards (lifecycle bar, error
classification, uptime), GPU rows with VRAM bars and sparklines, the incidents modal, and the
models bar — two ways in, to `/models` and to `/hf`, both in a new tab. `parkLaneStats()` / `mountNodeTelemetry()` move the live Server
stats card (CPU, RAM, network, disk, processes of the machine the controller runs on) out of and back
into the node of that machine (`controllerMachine`) around `innerHTML` rebuilds so its canvases
survive. The controller has no node of its own since step 6.9: its machine is its scout's host node,
and `isControllerMachine` / `hostPowerTextKey` give that node's reboot, poweroff and schedule the
words for the machine the board runs on. Collapsed nodes persist to localStorage.

- Owns: `topologyNodesViewOn`, `_collapsedNodes`, `_incidentsModalOpen`.
- Key exports: `nodesLaneHtml`, `nodeServerCardHtml`, `applyNodesViewMode`, `mountNodeTelemetry`, `parkLaneStats`, `classifyLlamaError`, `renderModelsBar`, `hostAgeText`, `hostSilenceHtml`, `isControllerMachine`, `hostPowerTextKey`, `gpuOutsideOwners`, `gpuWhoHtml`, `gpuOutsideBar`, `nodeEnginesHtml`, `nodeEngineCardHtml`, `engineRamText`.
- A GPU row names who holds the memory that is no cell's (`outside` from the backend): an engine of
  the machine («Ollama 5.9 GB»), else the process's name, else «outside»; each owner from 64 MiB is a
  hatched band laid after the fleet's share of the bar, and the «who» line lists the cells' ports AND
  the owners (the ports used to hide an outside job). The first render and the live patcher write
  both from one function each (`gpuWhoHtml`, `gpuOutsideBar` — the latter with a key, so the bands are
  rewritten only when they change).
- The engines next to a machine's cells (Ollama, LM Studio — scout 2.12+) are read-only cards under
  its cells (`nodeEnginesHtml`, `node-engines` / `node-engine`): version, port, «this machine only»
  with how to open it when it listens on 127.0.0.1, the RAM its processes hold (patched live),
  loaded models with their VRAM, RAM part, window and when keep_alive unloads them (a clock time),
  then up to six installed ones and «+N more installed»; «wants a token» and «does not answer»
  instead of a list. None (an older scout) and [] (none found) draw no block. An engine's state and
  what it has loaded are in the board's structure fingerprint; its memory is not.
- A model's switch (`node-engine-expose`) makes it a router output (`POST /api/engine-outputs/expose`,
  `setEngineModelExposed` in routers.js); an output's row carries the anchor the router's cable lands
  on (`data-topology-engine-input` by output id — one engine port serves many models), and an
  exposed idle model is listed first so its cable has a row to land on. An engine the proxy cannot
  reach (127.0.0.1 of another machine, or its machine's firewall — the switch's title then gives the
  ufw rule that would let the controller in) offers no switch to turn on; an output made already can
  be turned off. An engine open to the network wears its port's firewall badge, as a cell's port does. On the kanban an engine's output is labelled «model · engine» and is lit by the output
  a request was routed to (`routedOutputId`), not by its engine's host:port.
- A model is loaded or unloaded from its row (`node-engine-load` / `node-engine-unload`, only what the
  engine's `controls` offer, scout 2.14+): the load asks for a window — empty keeps the engine's own —
  and the unload is confirmed like stopping a cell (`actOnEngineModel` in remote-cells.js). While the
  act runs the row says «loading…» instead of offering another; what the engine refused last stays on
  the row in its own words. Where the engine can be told how long to hold the model (`holds`, scout
  2.15+) the same dialog offers 15 min / 1 h / 4 h / until unloaded (`appPromptChoice` in dialogs.js,
  `ENGINE_HOLDS`). A load that would not fit into the cards' free memory comes back as `short` and is
  asked about — «≥» when the need is the file alone, «≈» when it is an estimate — and loaded with
  `force` only on «load anyway». LM Studio's «stays loaded» comes from the scout (`staysLoaded`),
  Ollama's from an expiry centuries away.
- `machineAt(address)` — the machine behind an address its cells answer at, `{ key, name }`: its node and
  the node's name (the computer's hostname, from its scout); loopback and the controller's own address
  are the controller's machine (its node, else `topology.server.hostname`); an unknown address is said
  as the address. The one place the kanban's server groups and the nvidia-smi sources take a
  machine's name from.
- A host whose scout names no version (1.x) carries «scout 1.x — update» in its header
  (`scoutOldChipHtml`, `node-scout-old`).
- Every machine with a scout is a node (role `host`), with or without GPUs — the ＋ that reserves a
  first cell lives here. A host whose scout stopped answering is dimmed and gets a banner under its
  header: the age of the last report (`hostAgeText`, the same text the live patcher writes). A host
  node's one ✕ is in its header (`scoutDisconnectBtnHtml`, `node-disconnect` →
  `disconnectScout` → `POST /api/topology/scout/disconnect`); its dialog says «disconnect» for a
  scout that answers and «forget» for a silent one. Hardware readers —
  the remote cell form, stop, the nvidia-smi sources, the GPU lane — take the machine from
  `topology.hosts` (`topologyHost` in remote-cells.js), never from a client row.
- A cell whose files only a library holds wears `📚 <library>` (`cell-model-in-library`, from
  `modelStore`), naming the file when it is not the weights (`· mmproj`); a parked cell's ≈VRAM
  badge counts moved weights by the library's measure.
- A starting cell shows a looping line with the stage its scout read from the cell's own lines
  (`status.progressNote`), and ⚠ with what the previous attempt died of while the scout brings a
  crashed cell back (`status.lastError`). The measured load of the controller's own cells
  (`cell-load.js`, `loadProgress`) and their journal-classified start failure (`status.error`,
  `errorAt`) went with those cells in step 6.9.

## pace.js

`Pace` holds the one wording of speed and time left, used by the moves on `/models`.

- Owns: nothing mutable.
- Key exports: `Pace.speed`, `Pace.eta`.

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

- Owns: the drag state `topologyPointerDrag` (+ `clearTopologyPointerDrag`), the schedule-paint state (`topologyScheduleRouterId`, `topologySchedulePaintOutput`, `topologyScheduleGrid`, `_schedulePainting`), and several modal flags: `topologyProxySummaryOpen`, `topologyRouteDetail`. (The flags of the controller's own server's detail and GPU-logs modals went in step 6.9.)
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
`rebindProxyRouter()` is the drop handler for dragging a proxy onto a router. The local outputs
are grouped by the machine that serves them — `localOutputGroups()`, one grouping for the outputs
panel and the kanban's servers block, which each held a copy — and each group is named by
`machineAt()` (topology-nodes.js): the kanban named the controller's machine by the controller's
old display name and every other machine by its bare address.

- Owns: `_routersSaving` counter, `topologyOutputsCloudExpanded`, the cloud-expose chain/timer.
- Key exports: `saveRouters`, `renderTopologyRouterCard`, `renderTopologyRouterDetail`, `renderRouterOutputsPanel`, `localOutputGroups`, `rebindProxyRouter`, `routerById`.

**Modals & panels**

## topology-modals.js

The detail/config modal renderers: the client detail, the raw-config viewer, the priority and
queue-priority modals (threshold timelines, per-proxy edits), and the weekly schedule modal with
grid↔rules conversion. Renderers return HTML strings that `renderTopology()` injects;
topology-dnd wires their buttons.

- Owns: the modal flags and edit buffers: `topologyPriorityModalOpen`, `topologyQueuePriorityEdits`, `topologyRawConfig*`, `topologyAgentConfig*`, `queueThresholds`, `topologyClientDetailFor`.
- Key exports: `renderTopologyClientDetail`, `openClientDetail`, `openQueuePriorityModal`, `openRawConfigViewer`. (The controller's own server's detail and GPU logs/raw-API modals went with its cells in step 6.9.)

## llama-edit.js

The cell editor's shared parts (the `tr-` form; its opening and saving live in remote-cells.js):
applying a saved config to the form, the runner tabs and what each runner can launch, command
presets, the command-cell preview and the script it names, the running-cell beam, and the
preview baseline via `setEditCurrentCommand()` so the diff compares against the cell's own
command. Also closes the shared confirm modal (`closeConfirmModal`, resolving through
`ui.pendingConfirm`). The controller's own cell editor (`te-`), its start-server.sh backups and
snapshots, and the classic single-server confirmations went with its cells in step 6.9.

- Owns: `_editCmdSeq`, `COMMAND_PRESETS`.
- Key exports: `applyConfigToForm`, `applyCellKindUI`, `wireCellKindToggle`, `renderRunnerTabs`, `closeConfirmModal`, `setEditCurrentCommand`.

## remote-cells.js

Remote cell lifecycle on client hosts: reserve cells, start/stop via `/api/topology/client-llama/*`,
the `tr-` remote edit form (per-host model caches, GPU pickers, nvidia-smi source buttons), remote
backups and snapshots, model-cache purge, and client/agent/slot deletion. Optimistic
pending-start placeholders drive `startRemoteStartWatch()` — a 2 s `refreshTopology()` loop that
stops itself when nothing is starting, with a 240 s timeout turning placeholders terminal.
`formOnControllerMachine(pfx)` says whether the cell form's machine is the controller's own (its
node's `controllerMachine`), whose cells run through its scout since step 6.8: then its files are
the controller's — the models tree it lists and the home it reads scripts from. Only there does the
form offer what only that tree backs: a safetensors folder in the picker, the seamless runner and
its language, a vLLM path derived from the picked folder, and the content of a script its command
names; any other machine keeps them held back.

- Owns: the pending-op collections — `_pendingRemoteStarts` (Map), `_stoppingHosts`, `_deletingSlots`, `_reservingCells`, `_newReservedCells`, `_stoppingCells`, `_expandedCellCfgs` — plus `_remoteStartWatchTimer`, `_nvidiaSmiSource`, the `_tr*` form state.
- Key exports: `reserveServerCell`, `submitRemoteLlamaStart`, `submitLlamaStop`, `startRemoteStartWatch`, `remoteStartupInFlight`, `openLlamaRemoteEdit`, `bindServerSlotControls`, `formOnControllerMachine`.

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

- A row's client cell is the address the proxy recorded. (The monitor's client labels are gone
  since step 6.9 — both arms of the old "labelled?" choice drew the address anyway.)
- Owns: `historyRows`, `historyEventRows`, `historyTab`, `historyCurrentDate`, the filter values.
- Key exports: `openRequestHistory`, `closeRequestHistory`, `loadRequestHistory`, `renderHistoryTable`, `openHistoryDetailPopup`.

## system-panels.js

The System page's sections: section tips, project git branch, Known Problems, controller info,
the llama.cpp check/update and archived builds, and the repair-user-service flow. (The
controller's own service/runtime/CPU/GPU summaries and the start-server.sh revert went with its
cells in step 6.9.) The vLLM section picks a machine (`#vllmHost` — its value is the machine
shown; empty asks for the controller's own) and shows, updates and rolls back the vLLM in that
machine's venv through its scout (`/api/fleet/vllm*`).

- Owns: nothing mutable.
- Key exports: `openSystemInfoModal`, `checkLlamaCpp`, `openUpdateLlamaModal`, `loadVllmPanel`, `pollVllmUpdate`, `renderKnownProblems`, `renderProjectGitBranch`.

## polling.js

State loading and every polling loop: `loadState()` against `/api/state`; the self-rescheduling
live-refresh chain (every `LIVE_REFRESH_MS`, 1.5 s — the git chip from `/api/project-git`, then
the board; it fetched the whole `/api/state` for that chip until step 6.9); the
hover-driven monitor drawer (nvidia-smi with a localStorage-persisted interval, routable to a
remote client); and the 1 s system/topology monitors that feed `ui.latestSystemMonitor` (which in
turn drives activity classes, runtime panels and the kanban queue nodes). A partial monitor answer
is appended to the samples, the incidents and the scouts' rows (`hosts`); the controller's own
token-speed series (`tokenGenSamples`) went with its cells in step 6.9.

- Owns: every timer and inflight guard — `liveRefreshTimer`, `liveRefreshInflight`, `monitorState`, `systemMonitorTimer`, `topologyMonitorTimer`.
- Key exports: `loadState`, `scheduleLiveRefresh`, `LIVE_REFRESH_MS`, `startTopologyMonitor`, `startSystemMonitor`, `bindMonitorDrawer`, `formatTps`, `formatCtxTokens`.

## charts.js

Canvas 2D chart rendering: metric charts, GPU/token-speed/VRAM/power history drawn per node, node
telemetry rows with mini sparklines, the chart expand modal (node charts), route-activity drawing
and hover tooltips. Charts are redrawn by the monitor tick and once per full render (canvases have
zero size while their `<details>` card is closed — the toggle handler in main.js redraws on
open). A node's route activity counts the requests its cells served (`nodeEndpointSet`); the
controller's own machine (`controllerMachine`) also answers on 127.0.0.1 — the proxy on it reaches
its cells over loopback. The monitor's correlations (every local route with a request in flight,
whichever machine serves it) belong to the fleet-wide picture only.
The controller's own GPU/token/VRAM/power widget, its token series and the llama-clients panel went
with its cells in step 6.9. A token-speed point is `{tokens: {promptTokensPerSecond,
predictedTokensPerSecond}}` built from a cell's `tpsHistory` (`topologyPromptTps`/`topologyEvalTps`
read nothing else).

- Owns: `_routeActivityDrawState`, `CHART_EXPAND_CONFIGS`, `_chartExpandType`, hover-binding flags.
- Key exports: `drawMetricChart`, `drawTopologyGpuHistory` (the per-sample redraw of everything above), `drawTopologyTokenSpeedHistory`, `drawTopologyServerStats`, `nodeEndpointSet`, `nodeActivityFilter`, `miniSparklineSvg`, `systemSamples`.

## model-meta.js

Model-name parsing (`parseModelName`), model/projector icons, per-server bench fetches, and the
Artificial-Analysis score queue (batched, self-pumping). Fetches `/api/proxy-daily-stats` and
`/api/model-pricing` into module caches that renderers read synchronously.

- Owns: `proxyDailyStats`, `modelPricing`, `aaScores`, `serverBenchCache`, the AA queue internals.
- Key exports: `parseModelName`, `topologyModelIcon`, `fetchProxyDailyStats`, `fetchModelPricing`, `fetchServerBenchIfNeeded`, `aaBadgeHtml`.

**HF page**

## hf-page.js / hf-catalog.js / hf-bench.js / hf-repo-view.js / hf-downloads.js / hf-text.js

The HuggingFace browser at `/hf`, as classes. Two columns and a dock: on the left the search, its
filters, the HF token and the list with two tabs (results, ★ favorites); on the right the
repository; along the bottom the selection plan and the downloads. The header is the shared one.

- **hf-page.js** — the entry (`HfPage.boot` on `DOMContentLoaded`) and `HfDialog`, the page's own
  question. Clicks are delegated to containers that never change; `paint()` rewrites a container
  only when its markup changed and puts focus back; the list is not redrawn while a pointer is
  held over it (a row replaced between mousedown and mouseup swallowed the click). A repository's
  file list and on-disk check are one request pair however many callers ask. Loads the token,
  the favorites and the jobs at start and marks the page ready with how many got nothing.
- **hf-catalog.js** — `HfRepoFacts` (one repository: size read off the name as a whole token,
  capabilities, format, date, what is on disk) and `HfCatalog` (results, server-kept favorites,
  filters, faceted chip counts, a stable sort by downloads/likes/size/date/AA/Open LLM). A filter
  that cannot tell yet does not count as a match, and the list says how many it hid. No DOM.
- **hf-bench.js** — `HfBench`: benchmarks per repository (one request each, a background queue a
  newer queue replaces), the frontier list, and the AA Intelligence score drawn on the frontier's
  scale — ticks in the list rows, the model between its two neighbours in the repository header,
  the full panel with group names and descriptions in the page's language.
- **hf-repo-view.js** — `HfQuant` (rank, bits, low quants, the quant in a file name) and
  `HfRepoView`: quants grouped by bit depth with the low groups folded, a split quant as one row,
  companions (every mmproj, the MTP nearest the chosen quant), our copy against Hugging Face
  (✓ same / ⇪ another build / ? cannot tell, sha256 when verified), the safetensors checkpoint,
  the model tree and the other files. What we have of a file is shown for this disk (✓ ⇪ ?, 🗑,
  Verify) and for every library holding a copy (📚 with the same comparison, a violet row when only a
  library has it) — from `libraryFiles` of `/api/hf/local-check`.
- **hf-downloads.js** — `HfDownloads`: a selection across repositories and its plan (where each
  file lands as `<model>/<author>/<quant>/`, whether it fits with room to assemble a split file,
  what it would write over); one job per repository; jobs polled while they run or retry, Cancel
  on the server, interrupted partials with Resume; jobs survive a reload through the server's list,
  with this browser's copy as the fallback.
- **hf-text.js** — the page's words: `HF_LANGS` (a mirror of `LANGS`), the twenty-language `HFS`
  table, `HF_TOUR`, `HfText` (`t`, `ago`, `tour`) and `HfFormat`. The page does not load the shared
  dictionary. `check_i18n_calls.py` holds the table to the shared rules (every key in every
  language, same placeholders, actually translated); `check_tour_i18n.py` the tour and the mirror.

Nothing on disk is deleted or written over without a question: 🗑 asks, clearing the token asks, a
download larger than the free space asks, and a download that would land on a file already there
is refused by the server (`code: "exists"`) until the page has asked and resent it with
`replace: true`. Snapshots: `scripts/test_js_hf_{catalog,repo_view,bench,downloads,page}.py`.

## Invariants for contributors

1. **Never rebind an imported binding** — it throws `TypeError` at runtime under ES modules.
   Rebind through the owning module's setter: `setState`/`setTopology` (state.js), `cvSetViewport`
   (canvas.js), `markTopologyRenderPending` (topology-render.js). Before shipping, audit for
   `importedName =` assignments (the check that caught the fourteen sites fixed in `9de2510`).
2. **New cross-feature flags go into `ui`** in state.js — property writes need no setters. A
   mutable that is written by exactly one module stays a module-local exported `let` there.
3. **utils.js stays i18n-free and app-state-free.** The /hf modules import it (with
   `onboarding.js`) and nothing else shared; an `i18n-data` (or `state`) dependency here would
   pull the translations into the HF page.
4. **CSS files are cascade-ordered contiguous slices** of the old `styles.css`. Keep the `<link>`
   order identical on every page, add rules in the file they belong to, and never regroup
   rules across files — equal-specificity rules depend on their order.
5. **Function names stay unique across all modules.** The split was verified by a census: 572
   functions, each defined exactly once. Keeping names unique keeps cross-module imports
   unambiguous and greps trustworthy.
6. One-line-body functions (`function f(x) { return y; }`) are fine — the splitter bug that once
   swallowed them into the preceding item is fixed. The split tooling in `scripts/refactor/`
   (`list_top.py`, `extract_leaves.py`, `split_modules.py`, `split_css.py`) documents exactly how
   the original file was sliced; it ran once and is not meant to run again.
