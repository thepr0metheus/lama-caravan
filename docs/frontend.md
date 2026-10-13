# Frontend module reference

The UI is 46 native ES modules under `static/js/`; six of them (`hf-*.js`) are the `/hf` page.
There is no bundler, no framework, no npm and no build step: the browser loads `/js/main.js` as a
`type="module"` script and follows real `import` statements from there. The core was split out
of a single 26,720-line `static/app.js` (the split tooling survives in `scripts/refactor/`).

Six pages share the code:

| page | route(s) | entry | notes |
|---|---|---|---|
| `static/index.html` | `/board` (`/` and `/index.html` redirect) | `/js/main.js` | the topology board (main app) |
| `static/index.html` | `/machine?host=<id>` | `/js/main.js` | one machine's window: the same page, which shows that machine's whole card alone (board-view.js) |
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
history filters in history, the account window's busy flag in cloud.

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
GPUs, proxies, the pools with their steps and ports, the stamp of the models list the page holds,
view mode, open modals).
It deliberately **excludes** fast-moving numbers. Any phase transition (`downloading` → `loading`
→ `running`) is structural and forces a full rebuild; the numbers inside a phase are live-patched.
Around rebuilds, `parkLaneStats()` / `mountNodeTelemetry()` (topology-nodes) move the live chart
elements out of and back into the board so their canvases are never destroyed by `innerHTML`.

Poll cadences:

| endpoint | cadence | driver |
|---|---|---|
| `/api/state` | once, when the page opens | `polling.js` `loadState()` |
| `/api/project-git` | 1.5 s — the live beat (self-rescheduling timeout) | `polling.js` `scheduleLiveRefresh()` |
| `/api/topology` | piggybacks each live beat on the main board; also refetched after most POSTs | `refreshLiveState()` → `refreshTopology()` |
| `/api/models/rows` | only when the topology's `modelsStamp` differs from the page's — a model downloaded, moved or deleted since the page opened | `model-list.js` `MODEL_LIST.follow()` in `refreshTopology()` |
| `/api/topology` (start watch) | every 2 s while a remote server is resolving/downloading/loading; stops itself | `remote-cells.js` `startRemoteStartWatch()` |
| `/api/system-monitor` | 1 s while a monitor runs; feeds `ui.latestSystemMonitor`; the standalone kanban's only recurring poll (drives its live stats) | `polling.js` `startTopologyMonitor()` / `startSystemMonitor()` |
| `/api/monitor/nvidia-smi` | user-set 1–30 s, only while the drawer tab is hovered/focused | `polling.js` `startMonitor()` |
| `/api/proxy-daily-stats` | once at boot, then 60 s | `main.js` / `model-meta.js` |
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
- Both send the version of the list they were built from (`topology.proxyRevisions.routers` /
  `.routes`). A list built from an older version than the controller's is refused with 409, `stale`
  and the current topology (`isStaleCopy(err)` in `utils.js`; `api()` errors carry `status` and the
  whole answer as `data`): `saveRouters` runs its mutator again on that topology and
  `saveProxyRoutes(build)` builds the list again, once, with the toast `staleCopyRetried`; a second
  refusal goes to the caller. A tab left open since the morning wrote its copy over the
  afternoon's with its first click — on the NAS it put back a deleted port's cable (2026-10-08).
  The port form of a port deleted in another tab saves nothing (`staleCopyPortGone`): saving
  would bring the port back.

Standalone kanban init (`main.js` `initRouterStandalonePage()`), in order: `refreshTopology()` →
set the ui canvas ids (`ui.topologyRouterDetailId`, `ui.topologyCanvasRouterId`,
`ui.topologyRouterNodeCfgId = ""`) →
`cvSetViewport(canvasOpenPositions(routerId), canvasInitialView(routerId))` → `renderTopology()` →
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
- Key exports: `LANGS`, `messages`, `loadLanguage`, `translate` (the one lookup rule: the word in a
  language, else in English, else the key — `t()` and the brook's switch both ask it),
  `storedLanguage` and `LANG_KEY` (where the chosen language is kept).

## i18n.js

Language and theme. `lang`/`theme` are module-local lets persisted in localStorage
(`llamacppAdminLang`/`llamacppAdminTheme`) and only written here (the dropdown handler sets `lang`
then calls `renderAll()`). `applyLanguage()` walks the `data-i18n` attribute family. It sets an element's
text whole (`data-i18n` replaces `textContent`), so a label with a bold part and a note takes one element
and one key per part. Text in the HTML without such an attribute is never translated: for the cell
editor `scripts/check_cell_form_text.py` finds it.

- Owns: `lang`, `theme`, the language dropdown.
- Key exports: `t` (a face over `translate` in i18n-data.js), `fieldHelp`, `labelWithTip`, `helpTip`,
  `applyLanguage`, `applyTheme`, `setupLangSelect`.

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

`appConfirmChoice` is a confirm that also asks one of several choices (`opts.choices`, pressed
first `opts.choice`, `opts.list` for a long list shown as a scrolling column) and resolves the
pressed value as a string, or null on cancel — where a new cell runs, an engine cell's model, and
the "new model" window. `opts.cancelLabel` names what not answering means ("Not now"); every
settle puts "Cancel" back, because legacy openers write the other fields but not that one.

`appConfirmChecks` is a confirm that asks which of several things are meant, any number ticked —
the pools a consumer of the entry may call. `opts.allLabel` puts a first box that stands for all
of them, the ones added later too; ticked, it greys the others out. `opts.checked` is `"all"` or
the values ticked first, `opts.emptyLabel` says what an empty list means. It resolves `"all"`,
the ticked values in the dialog's order (not the order of the clicks), or null on cancel.

- Owns: the pending-dialog resolver, the pressed choice and the ticks of the open dialog.
- Key exports: `appConfirm`, `appConfirmChoice`, `appConfirmChecks`, `appPrompt`.

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
runs `initRouterStandalonePage()` (when `window.ROUTER_STANDALONE` is set — the kanban page: it reads
the topology, draws the pools' board, pool-board.js, and starts the monitor) or wires the full
board: modal buttons, the Escape/Ctrl+Enter keymap, the global `pointermove`/`pointerup` handlers
that drive cable drags (hit-testing via topology-dnd), resize/scroll/ResizeObserver cable
redraws, then `loadState()` and the 60 s / 24 h stats intervals. The cell editor's own form
listeners are bound by remote-cells.js when it opens; the classic form's and the controller cell
editor's went with the controller's own cells in step 6.9.

The board marks which board it is first (`BOARD_VIEW.mark()`, board-view.js), binds the click on a
machine's glance once on the static machines lane — the card itself opens the machine's window, no
"↗ Open" since 2026-10-12, a window a machine; a history chart and a button on it keep their own
click, a click with a modifier and a window the browser refuses follow the machine's name, which is
the card's link — and hides the loader when the page says it is ready
or why it is not (`body[data-t-state]`, set by refreshTopology's first render). It waited for a
cell's card, and a board without cells — a first run, and the main board since the machines' windows
(2026-10-11) — kept the loader up for the whole 15 s.

- Owns: the DOMContentLoaded wiring only.
- Key exports: none (side-effect module; both pages load it as the module entry).

## board-view.js

Which board a page is (the owner, 2026-10-11): the main board — clients, pools, and each machine at
a glance — or one machine in a window of its own, opened by a click on that glance: its servers,
engines, models and cells, the card the main board used to show whole. Both are index.html, at
`/board` and at `/machine?host=<id>` (the admin server sends the same file): the window needs every
dialog, form and listener the card had. `BoardView` reads the path and the machine (`""` when the
window names none — a window for nothing, said so, not the main board in disguise), gives a
machine's window its address (`url`) and its name (`windowName`, one window a machine, so the next
click brings it forward), opens it (`open`, a popup; false when the browser refuses), and marks
`<html data-board-view="main|machine">` for the styles (topology-board.css). In a machine's window
the page shows the card alone: the clients, the kanban's node, the pools, Add scout and the monitor
stay in the page, hidden; no cable is drawn (cables.js); the tab and the page's head take the
machine's name.

- Owns: `BOARD_VIEW` (the page's own reading).
- Key exports: `BoardView`, `BOARD_VIEW`.

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
- A model pick writes more than `MODEL_FILE`: the runner follows the artifact (a listener of
  llama-edit.js), then `maybeAutofillModelHelpersPfx` writes `ALIAS`, the projector and the draft.
  The same function runs on a form opening and on a backup load, and it ends with
  `renderCellPreviews` (llama-edit.js), after every write — so a command preview is never drawn
  from the values the pick replaces. It was: on the live board (v1.3.515) GR00T's "New command" named
  the alias of the model the list showed first until another field was edited.

## model-list.js

The models the cell editor offers (`state.models`), kept current on an open board.
`/api/state` brings them once, when the page opens, and the live beat reads only the
topology: until 2026-09-26 the caravan's shelf on a machine's card never showed a model
downloaded after the page opened. The topology carries the list's stamp (`modelsStamp`,
`ModelList` in `caravan/admin/models.py`); `ModelListFollower.follow(stamp)` fetches
`/api/models/rows` when the page's stamp differs — once, however many beats ask while the rows
are on their way — and puts the rows and the reply's stamp on the page. Nothing is fetched while
the page has no state yet (the router page never loads `/api/state`) or when the topology has no
stamp. A failed fetch leaves the page's list as it was; the next beat asks again.
`refreshTopology()` awaits it before deciding the render, and the stamp is in the structure
fingerprint, so the new list rebuilds the cards.

- Owns: the fetch in flight.
- Key exports: `ModelListFollower`, `MODEL_LIST` (over `state.js`'s state and `api()`).

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

Which cards on the board fold into a line, and how a folded one opens. The two long
lanes — model cells and client agents — drew every card at full height: on 2026-09-23 the
controller had 24 cells of which 6 ran, and 14 client routes of which one had a fallback.
`CardFold` holds the operator's per-lane choice (`compact` or `full`, the lane-header switch
`board-density`), the cards pinned open, and the one rule for what is quiet enough to fold:
`cellQuiet` (running with nothing to report, or parked) and `agentQuiet` (has a route, not
stale, no incident). A card in motion or in trouble never folds. A card the operator is setting
up stays open for the visit (`hold` — a client just added, by the prefix `agentKey(hostId)`; an
agent just given a port, by its key `agentKey(hostId, agentId)`): it is drawn as if pinned, the
first ▴ folds it, and nothing is stored (2026-10-08 — a new card folded the moment its first
port came, taking the fallback "+" with it). The lane switches hide over a lane with no cards
(`syncSwitches(doc, counts)`, counted by the board's paint). Automation
(`navigator.webdriver`) sees full cards by default. How a folded card opens is one table,
`CardFold.OPENS`: a cell opens as a window over the dimmed board on a click on its line
(since 2026-09-25, the operator's choice — no float, no pin), an agent floats. `FoldPeek` is
the pointer and keyboard side: an agent's full card floats over the lane after the pointer
rests 300 ms on its line (at once on keyboard focus), a click on the line or 📌 pins it, ▴
folds it back; a cell's line opens its window on a click (Enter, Space), and ✕, a click on the
dimmed board or Escape closes it, giving the keyboard back to the line. Nothing floats or
opens while a cable is dragged. Delegated on the document once — the lanes are repainted
wholesale.

The machine's eye over its list of cells lives here too: `hidesIdle(hostId)` is a choice
per machine, and `cellIdle` the one rule for what it may hide — quiet and not running (parked,
or reserved with no model). What moves or is in trouble never hides, for the reason it never
folds. `nodeServerCardHtml` leaves a hidden mark in place of a hidden cell (`data-cell-hidden`,
`data-cell-hidden-port`, and `data-cell-hidden-by` — which rule hid it), and `drawTopologyCables`
puts that cell's cable away without reporting it lost; the eye (`CellEye`) says how many it hid.
A machine's chips (`CellFilter`, 2026-09-25) narrow its cells to one launcher — the caravan or an
engine — and `launcherOf(hostId)` / `setLauncher(hostId, launcher)` keep that choice per machine;
their marks say `launcher`, the eye's `idle`, and the eye counts only its own. `reveal(hostId,
launcher)` lets a new cell of `launcher` be seen as it comes: the «+» of an engine's model stands
over the chips, under any of them, and a chip that would hide the new cell gives way to that
engine's; «all» shows it already and stays.

- Owns: `CARD_FOLD` (densities, pinned set, `peekKey` so a float survives a repaint,
  `openKey` so an open window does, the machines whose eye is shut, each machine's chosen
  launcher); densities, pins, eyes and chips persisted in `localStorage` (`boardCardDensity`,
  `boardCardPinned`, `boardCellsHideIdle`, `boardCellsLauncher`)
  as a per-browser convenience — a cell's pin saved before the window came is ignored.
- Key exports: `CardFold` (`OPENS`, `density`, `toggleDensity`, `togglePin`, `hidesIdle`,
  `toggleHideIdle`, `launcherOf`, `setLauncher`, `reveal`, `opensInWindow`, `mode`, `syncSwitches`, `cellQuiet`, `cellIdle`,
  `agentQuiet`), `FoldPeek` (`bind`, `openWindow`,
  `closeWindow`), `CARD_FOLD`.

## card-rows.js

The folded line of a board card, the slot that holds the line and the card, and the window a
cell's card opens in. `CellRow` and
`AgentRow` only lay out facts the card computed — the name, the memory chip, the ▶ start and
⏹ stop attributes with the words saying why, the route values — so the line and the card
cannot disagree. A cell's line carries a switch in place of ▶ and a dot: on while the cell
runs, off while it is parked, disabled with its reason when neither is possible. The line owns the
cable's handle while folded: cables and drops find handles by `querySelector` and read their
rectangle, and a copy inside a hidden card would hand them zeros. `FoldSlot` holds the line
(which never moves) and the full card — an agent's floats over the lane, and pinned it stands
in place with ▴; a cell's sits in a `CellWindow`: the card itself under a title bar (the
line's own name from `CellRow.shownName`, :port, the machine's address when the report has
one) and a ✕, over a dimmed board, shown only while the slot is open. An agent's line shows
only what is set — no dash placeholders, no empty fallback. The dot before an agent's name
(`AgentRow.dot`, on the line and on the full card alike) is lit with the time of the last request
through its ports, hollow while none has come — it was lit for every agent (2026-10-08). In an
agent's lane card the float covers the whole card, its padding and frame too (fold.css). Values are still changed on the
full card, where they always were. A cell whose model runs inside an engine gives its line and
its window the class `engine-<runner>` (`CellRow.launcher` admits only a lowercase word), so
they wear the launcher's colour; its window adds where the requests go — the engine's
`127.0.0.1:<port>` (`cell-window-via`).

`nodeServerCardHtml(node, s, { fold })` and `topologyAgentCard(…, { fold })` take the lane's
request; without it the card is drawn byte for byte as before. Styles: `static/css/fold.css`.

- Owns: nothing mutable.
`CellFilter` draws a machine's chips over its cells: each says how many cells it holds, an
engine's wears its colour and a dot while its server answers (none when the machine did not
report it), and the pressed one is the list shown; with nothing to choose it draws nothing. The
row starts with the anchors of the engine models made router outputs.

`EngineStrip` is an engine's server over the machine's chips, one per engine, always
(2026-09-26, the operator's choice B) — and the caravan's own strip, the same strip with its own
hook (`hook`), no switch, the machine's llama.cpp build as a chip with its buttons (`build`) and
the caravan's pages on its second line (`links`, 2026-09-27) — the switch that starts or
stops it, its name and version,
↟ when it starts with the machine, what it holds, ⤓; under them where it listens and what it has
to say. Right under its strip, whichever chip is pressed, each model it holds that no cell serves
is a `ShelfLine`: the cells' line, dashed, with «+» where a cell's switch stands. «+»
makes a cell with that model; it is `disabled` with its reason when no cell can be made now, and
keeps its test hook. Both only lay out what topology-nodes.js computed.

- Key exports: `CellRow`, `AgentRow`, `CellWindow`, `CellEye`, `CellFilter`, `EngineStrip`, `ShelfLine`, `FoldSlot`.

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

## draft-file.js

Which speculative type a draft file is for, read from its path — the twin of
`caravan/common/draft_file.py`; `scripts/test_draft_file.py` runs both against one table of cases.
`DraftFile(path).sidecarType` is the type the first word of the name says (`mtp`, `dflash`,
`dspark`, `eagle3`), else `draft-mtp` for a file under a folder named `mtp`, else `""` — no sidecar,
said rather than guessed; `launchType` adds the `draft-simple` a plain second model runs as.
`DraftFile.cellType(draft, familyType)` is what the cell editor writes into `SPEC_TYPE`: the draft's
own type, or with no draft the family's type for a model with an MTP head inside (else `draft-mtp`).
Picking a model (form.js) and switching speculation on (remote-cells.js) both write it — the switch
wrote the family's type over a DFlash sidecar until 2026-10-11 — and the cell window's command
(topology-nodes.js) names a cell's empty type by `launchType`, as the server's builder launches it.

- Key exports: `DraftFile` (`sidecarType`, `launchType`, `cellType`).

**Board**

## topology-render.js

The render orchestrator — see "Render & polling pipeline" above for the full mechanics.
Everything that redraws the board goes through this module; nothing else should rebuild whole
lanes with raw `innerHTML`.

The kanban a port feeds (`routerId`) is part of the structure: binding a port from the kanban's
"unassigned" list changed only that, and the kanban kept its old clients and its old badge. So are the
cloud accounts the main board's provider cards draw (`providers`): one added, signed in or tripped
redraws them.

The main board is three columns of one width (the owner, 2026-10-12): the clients, the kanban's card,
the machines with the cloud providers under them, and gutters between them wide enough for the
cables (96 px, 64 px below 1480). topology-board.css gives the server column and its lanes up to the
board's grid (`display: contents`), so the kanban's lane and the machines' lane are its second and
third columns; a machine's own window keeps its one column. The machines' and the providers' heads put
their buttons on a line under the title, as the clients' column puts its ＋.

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
when something actually started/stopped/errored or a port's last request changed. Also renders
the live runtime panels (cached per group in `_lastRuntimePanelHtml`), the sticky-bar slot
animations, and queue/duration helpers.
Everything here reads the proxy's own records: a server card lights from the routes pointing at its
port, the GPU card from the requests in flight, slot pips fill in request order, and a request's
one-line summary has no speed or context size (its exact speed is in the route's token history).
Until step 6.9 the controller's own single server was read too — its busy slots, context, prompt
cache and last timings — and drawn onto whichever card or request matched it by port or by time.
The route window's Model card (`routeModelCardHtml`) links every path on which the port states its
window, as the controller lists them (`windowLinks`): the model list, retrieve-model on a cloud
port, `/props` and `/v1/props` on a cell's. `MODEL_CARD_LINK_TIPS` gives each question its tooltip.
On the route row, the model's window figure (🪟) is a button: it opens that window on the Model card.
A port's address is the controller's (the row's `endpoint`, ConsumerAddress): where the ports have
no door it is empty, and `routeAddressTip` says why instead of a bare ":23001". `announceNewPort`
copies the new port's row address — the page's own name was copied before, and a board opened by a
name in front of another machine handed over that machine's port — and where there is no address
copies nothing and says how the client gets in: a key through the entry (2026-10-08, the NAS).
`keepAgentCardOpen` holds an agent's card open after a port is given (CardFold.hold). The wait chip
says whose number it shows: the route's own, or the port's (`routeWaitPortTip`) — it claimed a sync
from the client's config that no code does any more.
Under the token history, the Details tab shows the caravan's own time on the port over the same
range (`routeLatencyHtml`, `GET /api/agent-proxy-latency`): its work before the model, the
connection with the share of kept connections, the processor, and the model's first bytes on a row
of its own — the model's time is never added to the caravan's. Loading, failed and "no
measurements" are three states of their own (`data-t-state`); a measurement the port has no sample
of reads "not measured", not 0. An answer for a window since moved to another port or range is
dropped (`loadRouteLatency`).
A route row shows "⚠ N" from three failed requests in the hour (`routeErrBadgeHtml`, from
`ui.routeErrHour`, the proxy's summary keyed by port). Once a minute `refreshRouteErrBadges` reloads
the summary and redraws each row's badge with that same function and the row's own port
(`routeRowPort`, the rule the row is drawn with). It used to look the summary up by the chip's text
— an address — so every badge vanished each minute until the next full render.

`topologyItemsActivity(matches)` is one reading of how lively a set of the monitor's requests is —
active while one is served (a queued one is not yet), recent for 8 s after one finished, else idle —
given the port each request came in by (its own, else its row's). A kanban's output and a client's
cable to a pool are both lit by it.

A finished request keeps its ALARM — the red or yellow border, the route row's incident line, the
fold that stays open — only as long as the strip under the clients can show it
(`topologyAlarmIsOver`): the monitor's retention, `ui.latestSystemMonitor.retentionSeconds`, 600 s
unless the operator set another. After that the request is still the card's last one (its label and
title, which then says how long ago) and the card is as calm as after any old request; a request
with no finishing time has no age and its alarm stands. `topologyActivityIncident` is the one place
that says which incident a card shows now, for the incident line, the fold and the route's flag.
Nothing starts or stops when an alarm ages out, so `buildActivityFingerprint` carries each port's last
finished request and a "!" after it once its alarm is over (`topologyFinishedRequestKey`): that change is
what repaints the cards. Until 2026-10-13 a card stayed red as long as nothing else was asked of its port,
under a strip saying "no requests in 10 min".

The key is built from what the painter reads. A finished card follows its port's LAST request, which
is in no `active` row, and a request that starts and ends between two polls (the entry's instant 422,
a refused connection) is never seen running: with the key made of running requests alone, the open
board kept the card calm until some other full render (found live 2026-10-13: still calm at 47 s,
red by 111 s). So the key holds the last request of every port — its own id, else its two times —
beside the running ones. The same request on the next poll changes nothing, and another request
with the same classes still repaints, because its title and incident line are its own.

- Owns: `stickySlotAnims`, `_stickyBarRaf`, the activity/health class lists.
- Key exports: `refreshTopologyActivityState`, `setTopologyActivityClass`, `updateTopologyRuntimePanels`, `topologyStatusPill`, `sortedTopologyAgents`, `topologyQueueRuntime`, `topologyItemsActivity`, `topologyAlarmIsOver`, `topologyActivityIncident`, `topologyFinishedRequestKey`.

## topology-proxies.js

Agent cards in the clients lane (every agent of a client its own card, with its primary/fallback
routes) and the proxy-port registry: the route form (render/read/save via `/api/agent-proxies/config`), route
sorting, connect actions (proxy→llama, proxy→cloud), the per-group cloud-fallback toggle.
Stateless — its open/editing flags live in `ui` (`topologyProxyFormOpen`, `topologyProxyEditingId`).

- Owns: nothing mutable.
- Key exports: `topologyAgentCard`, `clientLaneAgentCards`, `topologyAssignmentsForHost`, `renderTopologyProxyForm`, `saveTopologyProxyForm`, `saveProxyRoutes` (every whole-list port save: the form, a move to a llama server — sent with `topology.proxyRevisions.routes`, built again once on a stale refusal), `sortedTopologyRoutes`, `feedsRouters` (a client of the entry never feeds a router — its cable leads to a set of models, since 2026-10-12: the route rebuild sends it unbound, and the kanban never counts it as a client), `isEntryClient` (kind `consumer`: free until a kanban takes it — the rebuild sends its binding as it is, and an absent one free, never the default kanban).
- A route rebuild (`topologyProxyRoutes`) keeps an explicit empty binding — a port detached from every
  kanban on purpose — and only a port with no binding at all gets the default. The port form changes
  only what it shows (`PROXY_FORM_FIELDS`: name, port, upstream address, mode, key); the rest of an
  edited route — kanban, owner and role, window, wait budget, upstream kind, on/off — stays as it was.
- An agent card makes no claim about whether the agent runs: no report says so any more (the
  scout knows hardware only). Every agent carries its ✕ (`agent-remove`); the dialog names the
  ports it leaves free (`savedAgentPorts` in remote-cells.js).
- The clients lane holds clients only — the operator's records. Since 1.3.466 the lane's ＋ makes
  a client of the entry (consumers.js), whose card stands first, under the entry's address. An
  agent of the older kind is one card too, its own agent's under the same name; no ＋ adds a second
  agent — it did, nobody used it, and the operator asked what it was (2026-09-24).
  A client with several agents from older data still shows a caption row with ✎
  (`clientNeedsCaption`). There is no "delete client" on the board: a card's own × removes that
  card, and the client goes with its last agent. The machine a scout reports is a node, not a
  card here.

## topology-nodes.js

The host-centric nodes view: per-node cards with server cards (lifecycle bar, error
classification, uptime), GPU rows with VRAM bars and sparklines, and the incidents modal. The ways
in to `/models` and to `/hf` are on each machine's caravan strip (2026-09-27; they were a bar over
the machines), both in a new tab. `parkLaneStats()` / `mountNodeTelemetry()` move the live Server
stats card (CPU, RAM, network, disk, processes of the machine the controller runs on) out of and back
into the node of that machine (`controllerMachine`) around `innerHTML` rebuilds so its canvases
survive. The controller has no node of its own since step 6.9: its machine is its scout's host node,
and `isControllerMachine` / `hostPowerTextKey` give that node's reboot, poweroff and schedule the
words for the machine the board runs on. Collapsed nodes persist to localStorage.
The main board draws each machine at a glance (`machinesLaneHtml`; the owner, 2026-10-11): its head
(name and address — the name on one line; the system word is the machine's window's, since in a column
of the board's one width it broke the name in two, 2026-10-12) — the whole card opens the machine's own
window, and its name is the link to it (main.js; no "↗ Open" and no scout's ✕ on the glance since
2026-10-12: a machine is let go in its window) — and its Compute panel, laid out compact there (topology-board.css; the owner, 2026-10-12: smaller
and nicer, nothing lost): no "Compute" title, the CPU's load and RAM on one line over its bar, a card's
model without its maker's words (`gpuNameHtml` sets them apart), each history chart on one line — name,
value, sparkline, its descriptor the hover word — opening under it on hover and whole on a click —
the CPU and its RAM, each GPU, the history charts (`nodeComputeHtml`, the one drawing for both cards,
which the live patch finds in either). The machine's window draws the whole card of that machine
alone (`nodesLaneHtml(id)`), or says the board does not have it (`machineMissingHtml`), with the way
back. `nodeRoleWord` / `nodeGroupName` are the head's role word and the card's name for a screen
reader, one reading for both cards.

- Owns: `topologyNodesViewOn`, `_collapsedNodes`, `_incidentsModalOpen`.
- Key exports: `nodesLaneHtml`, `machinesLaneHtml`, `nodeComputeHtml`, `machineMissingHtml`, `nodeServerCardHtml`, `applyNodesViewMode`, `mountNodeTelemetry`, `parkLaneStats`, `classifyLlamaError`, `llamaBuildChipHtml`, `hostAgeText`, `hostSilenceHtml`, `isControllerMachine`, `hostPowerTextKey`, `engineRunnerOf`, `nodeCellFilter`, `gpuOutsideOwners`, `gpuWhoHtml`, `gpuOutsideBar`, `nodeLaunchersHtml`, `nodeCaravanGroupHtml`, `caravanModelsWithoutCell`, `nodeDriverWarningsHtml`, `nodeEngineGroupsHtml`, `nodeEngineStripHtml`, `nodeEngineShelfHtml`, `engineRamText`.
- A GPU row names who holds the memory that is no cell's (`outside` from the backend): an engine of
  the machine («Ollama 5.9 GB»), else the process's name, else «outside»; each owner from 64 MiB is a
  hatched band laid after the fleet's share of the bar, and the «who» line lists the cells' ports AND
  the owners (the ports used to hide an outside job). The first render and the live patcher write
  both from one function each (`gpuWhoHtml`, `gpuOutsideBar` — the latter with a key, so the bands are
  rewritten only when they change).
- A cell whose model runs inside an engine (a runner with `engineCell` in the registry — Ollama, LM
  Studio; reserved with its model, see remote-cells.js) has a body of its own (`cell-engine-model`):
  the model's name verbatim as the engine names it (`ENGINE_MODEL`), its job from the engine's report
  when the cell does not say it, the runner chip from the registry (🟠 Ollama, 🟣 LM Studio — the
  chip table falls back to the registry for any runner it does not name), the memory the engine holds
  for the model while the cell runs (≈ the file's size while it does not), the model's parameters,
  quant and window. It is never a CPU cell and has no device chip (its process holds no model), it
  has no ⚙ (no editor tab), its ▶ confirms a model's start, and card, line and window wear the
  launcher's colour (`engine-ollama` orange, `engine-lmstudio` violet — one rule in nodes.css). An
  engine the report does not carry leaves the card naming its engine and nothing it would have to
  guess. `engineRunnerOf(srv)` asks the question once for the card, the machine's CPU line (a cell
  in an engine is not a cell on the CPU) and its chips.
- A machine's chips (`nodeCellFilter`): all its cells, the caravan's, and each engine a cell can run
  in that the machine reports or has a cell in — offered only when there is such an engine. The
  lane passes the chosen launcher to each card (`only`); a launcher the machine no longer offers
  shows all, so no list stays narrowed with no chip to widen it.
- The engines next to a machine's cells (Ollama, LM Studio — scout 2.12+; the operator's choice B,
  2026-09-26, in place of an engine card and its ▾ panel): every engine the machine's chips offer
  (`offeredEngineRunners` — the chips and the strips ask this one question) has a strip between
  the list's title and the chips, always, whichever chip is pressed — an engine's server is the
  machine's. `nodeLaunchersHtml(n, servers)` gives the lane, over the chips, one group per
  launcher (`node-launcher-group`): the caravan first (`nodeCaravanGroupHtml`), then each engine in
  the chips' order (`nodeEngineGroupsHtml`) — its strip (`nodeEngineStripHtml`, `node-engine`) and
  right under it its shelf (`nodeEngineShelfHtml`, `engine-shelf`) — so a model waiting for a cell
  is seen without pressing anything (the operator, 2026-09-26); an engine the machine does not
  report, offered because a cell of the machine runs in it, is a line saying so
  (`node-engine-missing`) — its cells cannot start.
- What a machine's next boot does to its NVIDIA card is said at the head of its Compute column
  (`nodeDriverWarningsHtml`, `node-driver-warning`): the node's `driverWarnings`, concluded by the
  controller, only worded here — the card that will not come back after a reboot and the package
  that brings it, or the driver installed but not yet loaded. A warning coming or going is in the
  board's structure fingerprint.
- The caravan's group (round 10's A, 2026-09-27): a strip without a switch — the caravan starts its
  cells, not a server (`node-caravan`). Its first line: «llama.cpp» and the machine's build chip
  (`llamaBuildChipHtml`, moved from the machine's header on 2026-09-27, the operator's move): the build
  and its date, ⬆ when it is not the controller's commit (commits compared by prefix — clones
  abbreviate differently), ⇪ to converge it (⏳ while the scout builds), ⟳ when a running cell
  predates the binary on disk; nothing when the machine reports no build. Its second line: 📦 Models
  and 🤗 Hugging Face (`node-caravan-models`, `node-caravan-hf`), the bar that stood over the
  machines — Hugging Face took the strip's «download»; the header keeps only the machine's power.
  Under all the machine's launcher groups a divider, «Cells» (`node-cells-divider`, 2026-09-27,
  the operator's ask), parts what can be started from what is made — the chips and the cells.
  Under the strip not the list of its models
  but one line, «＋ Add model» (`node-caravan-add`). It opens the cell editor on the next free port
  with the model list already open (`openCaravanModelEditor`), shut while a reserve on the machine
  is taking the port the editor would offer, and counts the models the cell editor offers
  (`state.models`: this controller's and its libraries' — any machine runs any of them, its scout
  fetches the file) less the ones a cell of this machine names (`caravanModelsWithoutCell`). An empty
  list, or one whose every model has a cell here, is said under it; a list that has not come says
  nothing. An engine's strip wears the engine's colour: the switch
  (the scout's `controls`: stop a running server, start a stopped one; with neither it is off-limits
  and says why — another user's service, or a scout that cannot), name, version, ↟ «starts with the
  machine», VRAM on the machine's cards (`engineVramText`: the owners the GPU bars name, summed,
  patched live) and the RAM its processes hold (patched live), ⤓ download; under them where it
  listens — «this machine only» and `127.0.0.1:<port>` (the isolation the cells rely on — the hint
  says a cell in the engine is the way in), or `:<port>` with its firewall badge — then «stopped»,
  «wants a token» or «does not answer», what the server or a download refused last in its words, a
  download under way (`engineDownloadText`, patched live), «run by another user». An engine's state
  and what it has loaded are in the board's structure fingerprint; its memory is not.
- The shelf lists the models the engine holds that no cell of this engine serves (a cell's
  `ENGINE_MODEL`): held outside any cell first (they take memory now), then a model still a router
  output, then up to six others and «+N more installed»; the caption counts them all. A line: «+»,
  the name verbatim, ☁ for an Ollama cloud model, a job chip only when it is not chat (embeddings),
  the parameters, what it holds while loaded (its window and when keep_alive lets it go in the
  chip's hint — a clock time; LM Studio's «stays loaded» from the scout, Ollama's from an expiry
  centuries away) or ≈ the file's size. «+» reserves a cell with the model on the next free port,
  no dialog (`reserveEngineCell` in remote-cells.js); it waits while a cell is being reserved on the
  machine or an act runs on the model. A model held outside any cell can be unloaded (⏏, confirmed
  like stopping a cell); an Ollama model that is not loaded deleted (🗑, under the pointer, through a
  danger dialog naming the model, the engine and the machine; LM Studio offers no delete). No model
  is loaded from the board: a cell in its engine loads it when it starts. An engine that does not
  answer has no shelf — its strip says why; one whose list did not answer, or that has no models,
  or whose every model has a cell, says so.
- A model is no longer made a router output from the board (the operator's choice, 2026-09-26: a cell
  in the engine is the way to its model; `POST /api/engine-outputs/expose` still takes one). A model
  made one already is named on its engine's strip with its switch (`node-engine-expose`, pressed) to
  turn it off, and stands first among the idle ones on the shelf; the anchor its router cable lands
  on (`data-topology-engine-input` by output id) sits at the edge of its machine's chips, so the
  cable is drawn whichever chip is pressed. On the kanban an engine's output is labelled
  «model · engine» and is lit by the output a request was routed to (`routedOutputId`), not by its
  engine's host:port.
- An engine's server is started or stopped with its strip's switch (`node-engine-start` /
  `node-engine-stop`, scout 2.16+, `serveEngine` in remote-cells.js): the stop is confirmed like
  stopping a cell, the start is not. Nothing is downloaded into an engine from the board (the
  operator's call, 2026-09-27): a model gets into Ollama or LM Studio by the engine's own means, and
  a scout that still offers "pull", or reports a download, is not taken up on it.
- `machineAt(address)` — the machine behind an address its cells answer at, `{ key, name }`: its node and
  the node's name (the computer's hostname, from its scout); loopback and the controller's own address
  are the controller's machine (its node, else `topology.server.hostname`); an unknown address is said
  as the address. The one place the kanban's server groups and the nvidia-smi sources take a
  machine's name from.
- `cellRunnerId(cfg)` — the runner that launches a cell (its RUNNER, a command cell's `custom`, or
  llama-server) — and `cellJobs(runner, cellMeta, cfg)` — what the cell does (an embedding server
  first, then the live kinds over the runner table). Both live in model-jobs.js since 1.3.502, beside
  the vocabulary, and topology-nodes.js re-exports them: the controller tells the proxy what each cell
  does by their Python twins (`cell_runner_id`, `cell_jobs`), one table of cases for both in
  scripts/test_model_jobs.py. The card, its detail window and the
  kanban's rows (output-cells.js) read these two; the card and the window each held a copy of the first.
  A cell this controller holds no settings for (made by the controller that ran on the machine before)
  has no runner on record: its jobs are only its own live kinds — the controller asks the cell's
  /health then (`telemetry.remote_cell_about`), and its model name comes from there too — and with
  none, no job: the runner id's default, llama-server, made every such cell a chat model (2026-10-12).
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
layer). A cable that cannot be drawn is named in `cableDrops` with the reason, and warned once.
Since the machines' windows (2026-10-11) a router's output to a cell or to an engine's model is put
away on the main board — the cells live in their machine's window — not drawn and not named lost; a
pool's output without its card still is. A machine's window draws no cable at all: its card has no
other end on that page.

A client of the entry has a cable too (the owner, 2026-10-11: a client's activity on the cables, as
the agents' was; 2026-10-12: one cable goes on from a client, to its set of models, and the sets and
pools stand on the kanban). It leaves from the handle on its card (`data-topology-proxy-output`,
consumers.js) and comes into the kanban's card, when the client has a set (`set`, the controller's
reading); it lights with any request of the client (`topologyItemsActivity` on the client's port) —
whichever pool of its set and row of the pool serves it, a cell's too. A client with no set has no cable. An idle one is dimmed as an agent's is.

From the kanban's card (its output, `data-topology-router-output`) cables go to the machines and the
cloud providers its pools lead to (the owner, 2026-10-12): to a machine one of whose cells is a pool's
row, to an account a pool's row calls (`PoolReach`, provider-glances.js) — a row switched off leads
nowhere. The rows themselves stay on the kanban; here a cable says only that requests can go there. It
ends at the card's head and lights while a request runs there: a cell's leg names its output
(`routedOutputId`), a provider's its account (`cloudAccountId`, caravan/proxy/handler.py). No pool, no
such cable; one whose card is missing is named in `cableDrops`.

- Owns: `_cableHighlightClearTimer`.
- Key exports: `drawTopologyCables`, `drawLiveTopologyCable`, `topologyCablePath`, `topologyAccentStyle`, `highlightTopologyCable`.

## server-order.js

The server cards — the machines and the pools — are one list in the operator's order (2026-10-04;
until then the machines always stood above the cloud). Since 2026-10-11 the main board shows the
machines apart, under Machines (board-view.js), and since 2026-10-12 the pools stand on the kanban
(pool-board.js) in their own order: the main board has no list under Pools, and nothing binds this
class on it any more. What follows about the pools' cards, `#topologyCloudProviders` and
`#boardServerCards` describes code no page draws until it is removed with the old kanban. `ServerOrder`
keeps that order and places by it. The order lives on the controller (`POST
/api/topology/server-order`, read back as `topology.layout` — `serverOrder` and `serverOrderRev`,
caravan/admin/board_layout.py), so every browser and account sees the same board.

A card alone has nowhere to go: `apply` hides its ↑ ↓ (`.server-order`) — two dead arrows in the
corner of the only card read as a broken control (2026-10-08).

- One rule places everything: `rank(key)` is a card's index in the stored order, and a card the order
  does not name stands after the named ones, in the order the lanes draw it (the machines as their
  scouts came, then the cloud). Nothing stored — every card ranks the same, and the board looks as it
  did before. The board's cards and the kanban's Servers groups (`renderServersBlockHtml`, routers.js)
  are both placed by it; a pool's row on the kanban stands where its card stands (the key is
  `cloud:<pool id>`).
- The two lanes stay two containers (`#topologyLlamaServers`, `#topologyCloudProviders`): their
  listeners, delegates and tests address them. The list is `#boardServerCards`, a flex column over
  both with `display: contents` on the lanes; a card's place is its inline `order`
  (`attrs(key)` — `data-server-card` and `style="order:N"`, stamped by the renderers; `apply()` moves
  the cards a new order names without a repaint). What is not a card — the "no pool yet" card,
  the strip of accounts in no pool — stands after the cards (`PoolCards.LAST`; "+ New pool" is in
  the lane's head, the lane's main action). Named deviation: Tab and a
  screen reader follow the DOM (the machines, then the cloud), not the order on screen.
- A card moves by the ↑ and ↓ buttons first in its head (`controls(key, name)`), one place a click,
  and the page scrolls with the card so the button stays under the pointer for the next click. There
  is no drag: the operator could not reach a place a screen away (neither a wheel nor a trackpad
  scrolls while the browser drags) and said the arrows are enough (2026-10-04). `apply()` disables the
  first card's ↑ and the last card's ↓, and a lane drawn on its own asks for it again. A step saves
  the whole list as it will stand. A save shows the order at once and sends it; while one is on its
  way the newest order waits for it; a refusal (a viewer account) is said in a toast and the cards go
  back to what the controller holds. The revision keeps a poll that left before a save from putting
  the old order back.
- The order is part of the board's structure fingerprint, so a new order rebuilds the kanban's
  panel.
- Owns: `SERVER_ORDER` (held order and revision, the order on screen ahead of the controller). Bound
  once in main.js on the static list.
- Key exports: `ServerOrder` (`key`, `clean`, `moved`, `stepped`, `rank`, `sorted`, `attrs`, `controls`,
  `apply`, `save`, `step`, `bind`), `SERVER_ORDER`.

## topology-dnd.js

The one big delegated pointer/click router for the whole board. `bindTopologyDragAndDrop()` is
**re-bound onto the fresh DOM after every `renderTopology()`** and wires every click target:
modal open/close, registry edits, schedule-grid painting, cloud/usage/history modals, canvas
hand-offs, and the cable drag start points. The hit-testing helpers (`topologyLlamaAtPoint`,
`topologyRouterInputAtPoint`, `topologyCloudAtPoint`) are consumed by `main.js`'s global
pointermove/pointerup. A route row opens the route window; its 🪟 button opens it on the Model card
and asks the port when no card is there yet. The row answers only its own keys: Enter on a button
inside it is that button's click.

- Owns: the drag state `topologyPointerDrag` (+ `clearTopologyPointerDrag`), the schedule-paint state (`topologyScheduleRouterId`, `topologySchedulePaintOutput`, `topologyScheduleGrid`, `_schedulePainting`), and several modal flags: `topologyProxySummaryOpen`, `topologyRouteDetail`. (The flags of the controller's own server's detail and GPU-logs modals went in step 6.9.)
- Key exports: `bindTopologyDragAndDrop`, `clearTopologyPointerDrag`, `topologyLlamaAtPoint`, `topologyRouterInputAtPoint`, `topologyCloudAtPoint`.

**Router canvas**

## canvas.js

The router workspace: the CLIENTS panel on the left, the canvas of rule nodes in the middle, the
SERVERS panel on the right. The two panels (`InputsBlock.panelHtml()`, `ServersBlock.panelHtml()`,
both from `canvasPanels(router)`) are `<aside class="rw-side">` panes as tall as the board, each
with a head that stays, a body that scrolls by itself (`.rw-side-body`) and, for CLIENTS, a foot
with the embeddings slot. The heads (SERVERS' with its queue line, `.rw-side-top`) and the palette
share the board grid's first row (subgrid), as tall as the tallest of them, so the rows of both
panels start where the canvas starts: a client's dot beside the palette stood above the canvas, and
the canvas cut its cable off at its edge (2026-10-04). They are not nodes of the canvas — they neither pan nor zoom — and keep
their old `kanban-node` hooks (`inputs:block`, `outputs:block`). The canvas (`canvasNodes(router)`)
holds only the rule nodes. A rule node's place has one home: the router's graph on the server
(`graph.nodes[].x/y`), where every drop is saved. The browser's old copy (`cvpos:<router>` in
localStorage) won on every open and undid the operator's drags on reload; `canvasOpenPositions` drops
it, and `_cvPos` holds only a drop whose save has not landed yet (the operator chose the server,
2026-10-04). An overlap nudge on open is drawn only. The canvas pans/zooms via `_cvView`
(foreign writers must use `cvSetViewport`; a router opens at `canvasInitialView(routerId)` — its rule
nodes' corner 24 px in from the canvas's own), draws
connectors, renders queue and schedule node bodies with history panes, and paints weekly schedule
grids. Queue-node live stats are computed from `ui.latestSystemMonitor` — this is what the
standalone kanban's 1 s poll drives.

**Cables across the panels.** A port of a panel is a dot, a child of the panel itself (not of its
scrolling body, which would clip the half that sticks out over the border and carry the dot away
with its row): `PanelPorts` places it from its row's rectangle and clamps it into the body's visible
span, so a row scrolled out of sight keeps its cables, ending at the panel's edge with the dot dimmed
(`.clamped`). CLIENTS' dots are on its right border (`.cv-port.out[data-cv-ref="in:…"]`, cables leave
to the right); SERVERS' in-ports on its left (`[data-cv-out-port="out:…"]`); and each model's overflow
port is a dot there too (`.cv-port.out[data-cv-node="rule:…"][data-cv-qrole="spill"]`, level with its
lane's line), whose cable leaves to the LEFT (`dir: -1` on the anchor), round into the canvas and back
to its target. The panels stand outside the canvas's world, so a dot's anchor is its place on the
screen carried through the view (`Board.panelPoint`); pan and zoom therefore redraw the cables
(`drawConnectors({ sync: false })` — the dots themselves did not move), a scroll of a panel redraws
once per frame (`scheduleDraw`), and the handlers that reach into the panels (the dot drag, the lane
toggle, the embeddings select) are bound on the workspace around all three (`[data-cv-cols]`), not on
the world. `Board.curve` is the one formula for a cable's cubic, drawn or dragged. The cables lie
under the nodes; where one runs under a node it does not touch, that stretch is drawn again above
the nodes, dashed (`Board.underRuns`, the `[data-cv-over]` layer) — a client's cable passing beneath
the backup node came out at the node's exit and read as the node's own (2026-10-08). The embeddings
slot, unset, is red only when a client asked for /v1/embeddings in the last 7 days
(`topology.embeddingsCalledAt`); otherwise it is grey, with the reason in its tip.

`ModelQueueNode` draws an active local model's queue as a lane immediately below
its output row inside `ServersBlock` — a rail on the left, one line, no box. The
line holds the slot meter (pips, `running/slots`, how many wait or `idle`) on the
left and the overflow target on the right; a click on the line
opens the live lists and the history under it, in place (`ModelQueueNode.toggle`,
one delegated listener in `Board.bind()`; the rows below move, so the dots and cables are
placed again). What the lane is doing is `data-t-state` — `idle`,
`running` or `waiting` — and the rail's colour keys on that same attribute. A dead
or unlisted overflow target is flagged with a ⚠ on the line itself, not only inside
the opened lane. Open lanes are remembered in `ModelQueueNode.open` (queue node ids),
so a render does not shut them. Queue ownership and activation come from the
server's `ModelQueues` normalization (`modelOutputId`, `modelQueueActive`). The
palette does not create queues. Main is a fixed internal edge, omitted from the
canvas cables and from the lane (the model's own row is right above it); overflow
remains an editable role cable. An inactive queue keeps its routing and capacity
but has no lane. Old local queues retain their ids and overflow paths.
`QueueNode.liveParts()` is the one place the live region is computed — the meter, the
lists and the state — and `liveHtml()` (a queue node card), the lane's builder and
`QueueNode.syncLive()` (the background tick) all read it.
The three operator settings are global and appear once, as a line at the head of
the SERVERS panel (`QueueSettings`, below).

**⤢ Show all** (`kanban-fit`) stands in the viewport's lower right corner: `Board.fitAll()` measures
the rule nodes as they are drawn (`Board.boxOf` of their offsets) and `Board.fitView(box, w, h)`
centres that box with 32 px around it — never zoomed in past 1:1, never out past the wheel's 0.35. The
view changes in place, so the next render keeps it. **A cable into a cell that is not serving** —
stopped, starting, failed or unknown (`OutputCells.state`, output-cells.js) — gets `cv-cable-down`
after its role classes and is drawn broken and faint; only a direct `out:` cable knows its output.
**A 🛟 node whose main and backup end on one output** shows a ⚠ line (`OnErrorNode.sameExitHtml`,
`kanban-onerror-same`): one cable in both roles, two cables into one output, or two chains the proxy
resolved to one model. An end nobody can name (a rule node with no report yet) says nothing.

- Owns: the `_cv*` family — viewport (`_cvView`, `_cvPos`), drag (`_cvDrag`), queue/schedule history panes and caches, schedule paint state, agent-map caches.
- Key exports: `cvSetViewport`, `canvasOpenPositions`, `canvasInitialView`, `drawCanvasConnectors`, `bindCanvasInteractions`, `queueNodeLiveStats`, `syncQueueNodesLive`.

The clients panel (`InputsBlock`) lists the ports that feed this kanban. A client of the entry is
none of them: since 2026-10-12 its one cable leads to a set of models, and no router decides for it.
`InputsBlock.portName` names a client by its name — the history panes said `:05`, the tail of its
record number, which it never called.

## output-cells.js

`OutputCells` answers, for the kanban's SERVERS panel and its cables, what stands behind a local
output (2026-10-04, after a look at the live kanban: 24 of 30 rows were stopped and drew the same
grey "idle" dot as the six that ran; a moonshine cell read "en"; two cells of one model read the same).
- `cellOf(out)` — the cell record: the machine at the output's address (`machineAt`, the same rule that
  names the panel's groups), then the port. An engine's model is found by its machine and its engine.
- `state(out)` — `running | stopped | starting | stopping | failed | unknown` from the record's phase
  (an engine's model from its engine's state); a record the board does not have, or a phase this table
  does not know, is `unknown` — never stopped, never idle. A cloud output has none (`""`).
- `name(out)` — the server's own phrase for what the cell runs (`cellLabel` = `cell_artifact_label`),
  else the model's short name as the cell card says it, else the output's label without its port.
  `topologyRouterOutputLabel` (routers.js) adds the port, so every caption of an output reads the same.
- `marks(out)` — the cell's jobs as marks, the list the cell card's chips draw (`cellJobs`).
- `reached()` / `split(outs)` — what something of the kanban leads to (a cable, the default, the audio
  and embeddings outputs, the older rule lists), and a machine's rows split into the shown ones and the
  stopped cells nothing leads to, folded while there are two or more of them.
- `twins(outs)` — rows of one machine with one name: each says the values of the settings that differ
  (`SEAMLESS_TGT_LANG=eng` beside `=rus`), a setting that may hold a secret by its name alone, and twins
  that differ only in the port say whose copy they are (`= :22004`). No settings known — no note.

## queue-settings.js

`QueueSettings` owns the single editor for all queue timings. It is a line under the
Servers head — "overflow at 20% · reserve 0s · Loading wait 60s" (`summary()`, the
fields' own labels) — and its pencil opens the three fields in place (`editing`
survives a render; the panel's dots and the cables are placed again when it changes height). It
reads `topology.proxyPolicy`, sends one field to the policy endpoint, uses the saved
response as its state and unlocks controls on every exit. Queue cards use its
values for spill markers and reservation bars; no node owns timing overrides.

## routers.js

The kanban's card on the main board (`renderTopologyRouterCard`, 2026-10-12): the clients' cables come
into it on its left; from its output on its right, cables go to the machines and the cloud providers its
pools lead to (cables.js). It is small (the owner, 2026-10-13: "without listing everything inside"): its name,
a help tip, and "Clients 4/4 · Pools 11" — how many of the clients have a set, how many pools there are. It
does not name the pools: they stand on the kanban, which a click on the card opens. It lights while a
client's request runs. Under the card stand the caravan's two model pages, as quiet links
(`renderBoardPageLinks`, 1.3.537; the owner, 2026-10-14: "move these two buttons somewhere more fitting"):
📦 Models (the models in its folder) and 🤗 Hugging Face (to download more), each opening in a new tab. They
stood in the head of Machines among the board's tools until 1.3.536; a model belongs to the caravan, not to a
machine, and the card is the caravan's own place on the board. A machine's own window has them on its
caravan strip instead. `scripts/test_board_model_pages.py` keeps the two pages reachable from the board. The router detail popover and the router's
outputs below were the old kanban's: no page draws them since the kanban became the pools' board
(pool-board.js). The Servers
panel on the kanban (`renderServersBlockHtml`; the old right-rail panel that drew the same list was
dropped on 2026-09-27, nothing called it): local llama servers plus the pools, each routable target
carrying one shared default radio. The groups — a machine's, a pool's — stand in the order of the
server cards (server-order.js), one list with no Local and Cloud headings;
a kind with no group says so after them ("no pools"). A pool is one output, `cb:<pool id>`, on the
kanban for as long as the pool is (caravan/admin/proxies_config.py, `pool_output`): there is nothing
to tick and nothing to fold. Its row says the pool's name and how many
steps it has — "steps: 3", their names in order in the hint (`_poolMarks`) — and a ⚠ when a request
to it cannot be served as drawn: no step enabled (it is refused, "add one"), or an enabled step whose
model its provider no longer lists. An output whose pool the page does not know keeps its row, after
the known ones, so no cable loses its end.
`saveRouters(mutator)` deep-copies `topology.routers`, applies the mutation, POSTs to
`/api/agent-proxies/routers` with the version it copied (`topology.proxyRevisions.routers`),
applies the returned topology when present and re-renders — with a marching-ants "saving"
indicator (`_setRoutersSaving`) since the workspace auto-persists. Refused as an old copy (409,
`stale`), it takes the topology from the answer and runs the mutator again on it, once.
`rebindProxyRouter()` is the drop handler for dragging a proxy onto a router. The local outputs
are grouped by the machine that serves them — `localOutputGroups()`, one grouping (the old panel
and the Servers block each held a copy) — and each group is named by
`machineAt()` (topology-nodes.js): the kanban named the controller's machine by the controller's
old display name and every other machine by its bare address.
A local row says its cell (output-cells.js): a serving cell's dot is its traffic; a cell that is not
serving has a ring instead and its state in words at the row's end (`kanban-out-state`); the name is the
cell's own, led by its job marks; twins say what sets them apart. A machine's stopped cells that nothing
leads to stand under one row, "N stopped, no cables" (`kanban-quiet-cells`, folded until opened —
`topologyQuietShown`), which names their outputs (`data-cv-group-outs`) so a cable that comes to one
before the next render still has an end. The head's "N unassigned" badge counts only ports that can feed a router
(`feedsRouters`: a client of the entry cannot — its cable leads to a set of models). It
is a `<details>` (`kanban-unassigned`) whose list names the ports and binds one on a click.
`topologyOutputActivity(out, router)` — an output's traffic: with the router, only the requests its own
ports brought (`router.inputs`) count. A pool also serves the entry's clients directly, and their
requests carry the pool's id too: until 2026-10-11 the kanban's cable to that pool, and its dot on the
kanban, lit for traffic that never passed the kanban.

- Owns: `_routersSaving` counter, `topologyOutputsFolded`, `topologyQuietShown`.
- Key exports: `saveRouters`, `renderTopologyRouterCard`, `renderTopologyRouterDetail`, `renderServersBlockHtml`, `localOutputGroups`, `rebindProxyRouter`, `routerById`.

**Modals & panels**

The kanban's "not on this kanban" list (`rw-unassigned`) holds ports only: a client of the entry feeds
no router (`feedsRouters`, the server's normalizer keeps the same rule).

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

What the form shows of a field's words is decided in the markup and two places of code. A **note** is
`<p class="field-note" data-i18n="…">` and is shown, compact, under its field; the editor's CSS
(`monitor.css`, `.topo-edit-form .field p:not(.field-note)`) hides every other paragraph of a field —
the **descriptions**, whose words are the (?) tips'. A field written as a bare label and input gets
its tip by id from `_STATIC_TIP_FIELDS`; a value only the shared picker sets has a carrier `.field` of
its own, which `applyCellKindUI` hides without the panel around it. `scripts/check_cell_form_text.py`
holds all of it: prose without a key, a hidden paragraph with no tip, a carrier that takes its panel
with it. It has no known exception now. The model-cache panel was the last: its note is three
parts with keys (the words before the path, `<code>`, the words after) and what `purgeRemoteModelCache`
writes goes to a status line of its own (`tr-purgeCacheStatus`, cleared when the form opens), so the
note is never rewritten and every number is said by a key with `{n}` and `{gb}` (`topologyPurgeCacheResult`,
`cacheTotal`).

- Owns: `_editCmdSeq`, `COMMAND_PRESETS`.
- Key exports: `applyConfigToForm`, `applyCellKindUI`, `wireCellKindToggle`, `renderRunnerTabs`, `closeConfirmModal`, `setEditCurrentCommand`, `renderCellPreviews`.
- `renderCellPreviews(pfx)` draws every preview of the form from its fields as they stand: the
  controller's line for a llama.cpp cell, the page's own line for any other runner, and Strata's draft
  line. Whoever writes fields a preview reads ends with it; `scripts/test_js_cell_previews.py` pins a
  pick, a pick that keeps the runner, a form opening, a backup load and a typed edit on the page's real
  listeners. A typed or chosen edit of ANY field reaches it through the form's own `input` and `change`
  listeners (remote-cells.js): nothing keeps a list of the fields a runner's command reads. A list
  of that kind, in `wireCellKindToggle`, had no `ALIAS`, no draft file, no language field and no port,
  so typing there left "New command" on the old text; it is gone.

## remote-cells.js

Remote cell lifecycle on client hosts: reserve cells, start/stop via `/api/topology/client-llama/*`,
the `tr-` remote edit form (per-host model caches, GPU pickers, nvidia-smi source buttons — `nvidiaSmiSources`
lists the controller's machine only while it can read its GPU, and with no source the monitor drawer
on the board's edge hides, 2026-10-08), remote
backups and snapshots, model-cache purge, and client/agent/slot deletion. Optimistic
pending-start placeholders drive `startRemoteStartWatch()` — a 2 s `refreshTopology()` loop that
stops itself when nothing is starting, with a 240 s timeout turning placeholders terminal.
`formOnControllerMachine(pfx)` says whether the cell form's machine is the controller's own (its
node's `controllerMachine`), whose cells run through its scout since step 6.8: then its files are
the controller's — the models tree it lists and the home it reads scripts from. Only there does the
form offer what only that tree backs: a safetensors folder in the picker, the seamless runner and
its language, a vLLM path derived from the picked folder, and the content of a script its command
names; any other machine keeps them held back.

`reserveEngineCell(hostId, kind, model)` is the «+» on a model's line under an engine's cells:
nothing is asked — the line names the engine and the model — and the port is the next free one;
one reserve at a time on a machine. It sends through `postReserve` (the machine's spinner until the
new cell is on the board, its flash, the controller's refusal as the toast —
`caravan/admin/engine_cells.py` holds the words). The Reserve-cell stub under a machine's cells,
with its "where does the new cell run" dialog (`reserveServerCell`, `reserveEngines`), left in
1.3.393 (the operator's call): a caravan cell begins at «＋ Add model», an engine's at its shelf. `actOnEngineModel`
unloads a model (confirmed like a stop) or deletes it (the danger look, the machine named); it sends
no other act — no model is loaded from the board. `cellServiceAction` asks when a start comes back
`short` — a cell in an engine whose model would not fit into the cards' free memory: the numbers
("≥" when the need is the model's file alone), and on "start anyway" the same start with `force`.

`openCaravanModelEditor(hostId)` is «＋ Add model» on a machine's card (2026-09-27, the operator's
choice A of round 10): the `tr-` editor opens on the next free port, and once the dialog is on
screen its model list opens (`mcOpen` in form.js, a click on the field as a hand makes it), so the
model is the first thing picked; the field's own change listeners bring the projector, the MTP
draft, the runner and the insight. Until then the pick is awaited (`mcAwaitPick`): the field is
empty, and `modelChoiceOf` — the form's one word on what is chosen, which the selects' redraw and
memory.js's `selectedModelRows` both ask — answers "no model" for the model, projector and draft
while the mark stands, so neither the machine's cached list arriving nor the estimate brings the
config's model back; the hidden select keeps an empty option selected (a browser picks the first
option of a list rebuilt with none selected), and the memory bar says "select a model". The first
model picked lifts the mark; Apply without one says so before any confirm. Its Apply makes the cell — `save-config` creates a cell that
does not exist yet, checking its port as a reserve does; the button alone makes nothing. A saved
cell reveals the caravan's cells on its machine's chips (`CARD_FOLD.reveal`), so the new cell is
not saved out of sight.

- Owns: the pending-op collections — `_pendingRemoteStarts` (Map), `_stoppingHosts`, `_deletingSlots`, `_reservingCells`, `_newReservedCells`, `_stoppingCells`, `_expandedCellCfgs` — plus `_remoteStartWatchTimer`, `_nvidiaSmiSource`, the `_tr*` form state.
- Key exports: `reserveEngineCell`, `reserveEngineButton`, `openCaravanModelEditor`, `preselectModel`, `actOnEngineModel`, `serveEngine`, `submitRemoteLlamaStart`, `submitLlamaStop`, `startRemoteStartWatch`, `remoteStartupInFlight`, `openLlamaRemoteEdit`, `bindServerSlotControls`, `formOnControllerMachine`.

## cloud.js

The cloud under Pools: the pools' lane (drawn by `PoolCards`, pools.js), the window that adds
a step or a pool (`PoolStepDialog`, pool-step-dialog.js), and the accounts their steps stand on — the
provider picker, the account window and the sign-in by a one-time code. Since 2026-10-12 the main
board has no Pools lane: `renderTopologyCloudProviders` finds no lane and draws nothing, and no page
opens the step window. The provider picker and the account window serve the main board's providers
(provider-glances.js): "＋ Add cloud provider" opens the picker, whose tile puts a provider on the board
as an empty block (`pickCloudProvider` → `addBoardProvider`, `POST /api/board-providers/add`); the
"＋" in a block connects an account of it (`connectAccount`: a subscription goes straight to its
sign-in code — the account is saved and the code asked for at once, named "ChatGPT subscription N"
until renamed — a key provider opens the new key's window); an empty block's ✕ takes it off
(`removeBoardProvider`, 409 while an account stands under it); ⚙ opens an account's window. The kanban
sets no account up (2026-10-12).

`renderTopologyCloudProviders` hands the pools, accounts, the proxy's word (`topology.poolsRuntime`)
and the ports to `POOL_CARDS`, and wires the pieces only this module reads: a step's limit bars with
the step's own switch levels (`subscriptionUsageHtml(owner, { step })`, usage-stats.js), the saved
resets (`SubscriptionResetCards`), the step model's share of the spend (`cloudStepSpend` — the cost
at API prices, `cloudMoney`, or the request count, never "$0"), what a key account's provider says
about it (OpenRouter its key's limits, the OpenAI API its spend), the breaker's tripped endpoints and
the routed errors. The lane redraws when its key moves: the accounts, the pools, the readings, the
ports — and the proxy's word as `poolsRuntimeKey` says it, which drops the second a choice was made
(a lane redrawn on every request took the tooltip from under the pointer). Live sync calls it on
every tick (topology-render.js), so "Serving now" and the reasons follow the proxy between full
renders. It waits while a switch-level slider (`switchDrag`) or a rung (`POOL_CARDS.inFlight()`) is
in the operator's hand, and while the pool's name or window field has the focus. Its clicks and
changes are delegated from the lane's permanent container (`bindCloudCardDelegates`), once.

"+ New pool" in the head of Pools opened the step window for a pool that did not exist yet, and
"+ Add step" on a card for that pool; both went with the lane (2026-10-12). Connecting a new
account from that window opens the picker (`openCloudPicker(after)`); `ACCOUNT_RETURN`
(`AccountWindowReturn`) holds who waits for the account window to close and is emptied on every
exit: "Done" after a sign-in and Save of a new account give the account back
(`finishCloudAccountWindow`), × / Cancel / the backdrop / deletion give back nothing
(`closeCloudProviderModal`). "Done" is bound so that the click event is never taken for an account
id. A new account is saved before its key, and from then on the window edits it: a key the provider
refuses no longer makes a second account on the next Save. A new account stands in no pool by itself
— a step names it.
The picker stands in two groups — a subscription that signs in, then the providers that take a key —
and every tile's name and line come from the language tables (`CLOUD_PICKER_META`,
`cloudProviderName`; the lines used to be English in every language). Its tiles are one height, the
provider's colour on its sign alone and its line on one line — the group says "API key" once for all
(the owner, 2026-10-12: "the windows are not pretty"). From the main board a provider already on the
board is a pale tile not to press, "already on the board"; a window waiting for an account (the step
window) marks nothing and opens the new account's window, as before. The windows' × is a quiet icon:
the window's rule for buttons had made it a framed 32px box. A subscription's window names the plan
its limits' last reading named (Plus, Pro; none read — no word), and a key's window carries its
provider's word — OpenRouter its key's limits, the OpenAI API its costs — which stood under the
kanban's ⋯ until 2026-10-12. The account window is one of
nine plain states, a pure function of the form and the account (`cloudAccountWindowState`, pinned
by value; `data-t="cloud-account-window"` carries it in `data-t-state`): `connect` (a new
subscription: a name and **Sign in with ChatGPT**), `waiting` (the code, which copies on its own click
and on Enter or Space; one **Copy code and open OpenAI ↗** link that copies it too; three steps, until
when it works, **Get a new code**; a refused clipboard says the code is not copied, rather than leave the
operator to paste what the clipboard held before), `ended` (why the sign-in ended
without a login — a newer code, an expired one, a controller that forgot it, a deleted account — and
the one way on, `CLOUD_ENDINGS`), `connected` (who, and what comes next: from the step window "choose
its model for the step", from anywhere else "add it to a pool with + Add step"; one **Done**),
`subscription` (signed in or not, **Sign in again**), `newKey` / `newNoKey`, `keyAccount` (the key's
last four, a field for a new one) and `noKey`. An address field shows only for a provider whose
address is the operator's (`custom`, `ollama`). A new subscription is named as its block and its tile
name it, with its count ("ChatGPT subscription 2"; until 1.3.494 "OpenAI subscription 2"): two windows
named alike made "which one is out of limits" a guess.
`startCloudOauthLogin` saves a new account with `POST /api/cloud-accounts/save` before its code. The
window of an existing account lists the pools its steps stand in (`usedIn`), or that it stands in
none. `cloudDeleteWords(acct)` is what the delete confirmation says: its steps leave their pools
(each pool named once), the pools keep their other steps; the sign-out at OpenAI is said only where
the server says so. The sign-in is by code only (`startCloudOauthLogin`
→ `/oauth/device-start`, `pollCloudOauth` every 2 s up to `DEVICE_LOGIN_POLLS`): the return through
localhost:1455 is gone. A poll of a code this window no longer shows stops quietly. ×, Cancel and
the backdrop go through `cancelCloudAccountWindow`, which takes back an account the window made for a
sign-in that never finished; it used to stay on the board as a subscription that "needs key".
Deleting an account whose sign-in the server will end at OpenAI (`signOutOnDelete`) says so in the
confirmation, and the toast after it says whether OpenAI confirmed. The
account modal's open/form state lives in `ui` (`topologyCloudModalOpen`, `topologyCloudPickerOpen`,
`topologyCloudForm`).
The codex `client_version` the caravan sends to chatgpt.com (and where it came from) is shown under
⚙ — in a subscription account's window (`codexVersionHtml`), not on the card (variant A); no line
when it is unknown. `isSubscriptionAccount` is the one test for a ChatGPT subscription account.

- Owns: `topologyCloudBusy`, `ACCOUNT_RETURN`, `POOL_CARDS`, `POOL_STEPS`, the reset cards.
- Key exports: `renderTopologyCloudProviders`, `renderPoolStepDialog`, `poolsRuntimeKey`, `POOL_CARDS`, `POOL_STEPS`, `ACCOUNT_RETURN`, `AccountWindowReturn`, `openCloudPicker`, `openCloudAccountModal`, `finishCloudAccountWindow`, `closeCloudProviderModal`, `cloudAccountWindowState`, `cloudProviderName`, `cloudAccountIconHtml`, `cloudDeleteWords`, `cloudPrice`, `cloudMoney`, `cloudStepSpend`, `saveCloudAccount`, `startCloudOauthLogin`, `pollCloudOauth`, `cancelCloudAccountWindow`, `deleteCloudAccount`, `isSubscriptionAccount`, `codexVersionHtml`.

## provider-glances.js

The cloud providers on the main board (the owner, 2026-10-12): under the machines, in the board's third
column, each provider a block of its accounts — ChatGPT subscriptions, OpenRouter, the OpenAI API…
"＋ Add cloud provider" opens the picker, which puts a provider on the board as an empty block
(cloud.js); the "＋" at the foot of a block adds an account to it — "＋ subscription" goes straight to
the sign-in code, "＋ API key" (an address, for a custom provider) opens the new key's window — and the
same sign-in may be added twice. An empty block says so and has a ✕ that takes it off; a block with
accounts has none. Which provider an account stands under, and in what order the providers stand, is
the controller's word (`topology.boardProviders`, caravan/admin/board_providers.py); the board works
none of it out. `ProviderGlances` draws each block: the provider's sign in its colour, its name, how
many accounts; each account a row — its name and whether it can serve, a signed-in subscription's
small "↺ N" (`SubscriptionResetCards.chipHtml`, a button while a saved reset can be spent: the window
of choice is the one place one is spent) and ⚙, then its windows as last read — no ⟳: they are read
when the page loads and again when it is come back to after a minute — or an API key's spend through
the caravan, and a tripped endpoint when there is one. The rest about an account stands in its window
(cloud.js). Never its models: the kanban has them. No provider — the line that says so.
`mount(container)` draws into `#boardProviderCards`, binds the "＋"s, ✕, ↺ and ⚙ once on the column,
and registers once on `READING_LANDED`: a reading that lands draws the blocks again, then the cables
(their ends moved when a block grew).

`PoolReach.of(topology)` is where the kanban's pools lead — the accounts their rows call and the
machines whose cells they call (a row's output → the router's output → `machineAt` its address, the
rule the kanban's machine rows go by). A row switched off and an output gone lead nowhere: no cable
says a request can go there. cables.js draws the kanban's card's cables by it.

- Owns: the column it draws into (`container`), the topology it drew (`top`) and the subscriptions'
  saved resets (`resets`, read at most once a minute each).
- Key exports: `PoolReach`, `ProviderGlances`, `PROVIDER_GLANCES`.

## pool-board.js

The kanban page (the owner, 2026-10-12): clients, sets, pools and models in four columns — the sets a
little narrower, the clients 30% narrower than a pool (1.3.500: "the whole scene on a laptop's screen",
1395px of board in the narrowest window) — their heads on one line, joined by cables; the mockup the owner approved had three,
the sets came the same day (step 2 of the visumap scheme caravan-model-sets). In a column that width an account's head puts its note on a second line and a
subscription model's row its pools under its name, so the bars keep their room. `PoolBoard` draws the controller's reading and works out
nothing of its own; `POOL_BOARD` is the page's one board, drawn by `renderTopology` into
`#topologyProxies` in place of the router's workspace (`html(topology)`, then `mount(container)`).

- **Clients** — the clients of the entry (`ConsumerCards.of`), in the operator's order (1.3.503,
  `topology.layout.clientOrder`; the clients it does not name after them, by name): the name, the key's
  last four characters, and one output dot. A client's cable leads to its set (`set`); a client with none
  says "no set", its dot a dashed ring. Clients are made on the main board, and the column has no ＋
  of its own (the owner, 2026-10-12); with none, it says where they are made. Under the name, what
  the client calls and what it gets there (`linksHtml`; the owner, 2026-10-12): the entry's address
  without its scheme — the hint names it whole — with ⧉ (`copyUrl`, the whole address), then its questions by GET — `/v1/models` and `/v1/models/<model>` for each model of
  its set (`models`) — each
  a link to `GET /api/consumers/ask`, where the controller asks the entry with the client's key and
  hands on the answer as it came (caravan/admin/proxy_entry.py `AsConsumer`). A link to the entry
  itself would only be refused for want of the key, and the page never holds one. No entry, no links;
  no set, no model to ask about. Then the client's work by POST, folded under one line, "Test as the
  client", until it is opened (`probesHtml`, the open ones in `tests`; 1.3.500 — six buttons were four
  lines of the narrow card), one button per kind
  (`topology.clientProbes`, the controller's table that sends them — chat, responses, speech to
  text, text to speech, pictures, embeddings): a press sends the shortest standard request of that
  kind as the client (`runProbe`, `POST /api/consumers/probe`) — naming the model chosen beside the
  buttons when the set holds more than one (`probeModelOf`) — and a window over the board
  (`probeHtml`) shows what went out and what came back — status, type, time, size, the body laid
  out, or a player for speech; ✕ or Escape closes it, and an answer for a window already closed
  lands nowhere. A picture may cost money: its button asks first. Under the links, the client's
  errors of the last 30 days (`missesHtml`, `misses` from caravan/admin/client_misses.py): method
  and path, status, how many times and when last, the reason in the hover, the rest counted — a
  record from before 1.3.495 has no method and shows its path alone. No errors — no list.
- **Sets** — the sets of models (`topology.sets`, caravan/admin/model_sets.py; the owner, 2026-10-12:
  «Набор»): what clients see as their models. A client's cable comes into a set's card; its rows are
  its pools by name, in its order — each one model the client sees — each with a cable on to its pool;
  the "＋ model" row carries a new cable onto a pool, pressed on its dashed dot or anywhere
  else on it (`newOutHtml`; the owner, 2026-10-12) (`POST /api/sets/add-pool`) — in the set's strip, and
  on its card only while the set has no model (1.3.533) —, a click on a
  set's cable takes the pool out of it after a question (`POST /api/sets/remove-pool`). The name is
  edited in place (`POST /api/sets/rename`), ✕ deletes the set after a question that names the clients
  it leaves without models (`POST /api/sets/delete`), "＋ New set" makes an empty one, its name chosen
  in the field (`POST /api/sets/create`). One set may serve several clients.
- **What a model does** (1.3.502) — beside a pool's name and beside each set row that names it
  (`kindHtml`), the controller's word on what the pool's rows do together (`pool.kind`,
  caravan/common/model_kinds.py — what GET /v1/models tells the clients): the jobs' marks (model-jobs.js
  `JOB_MARKS`), 🖼 for a chat that takes pictures, the jobs, pictures and languages in the hint; ⚠ when
  the rows do different work — the list then says nothing of the model. Unknown, nothing is drawn.
- **Pools** — each pool a card: its name in place (saved on change, the pool cards' `save`), ✕ for its
  deletion (the pool cards' `remove`: what holds it, where it goes); its last switches (🕘 until 1.3.532),
  its settings and its "＋ row" are in its strip (1.3.533, `poolDetailsHtml`). Its rows in order (`pool-ladder`, carried by ⠿ — StepCarry, the order saved by the
  pool cards' `sort`), each of three kinds: a subscription's model with its account, a machine's cell
  with its machine and port (`srv:<port>`, `eng:<id>`), or a row with no cable. Each says the proxy's
  word on it (`status`, `PoolCards.REASONS`: serving, the levels reached, a cell off or busy, a
  sign-in missing…), the serving one lit; a target that is gone is said in red, with no cable. A row
  whose cell does not run now says so first, in the controller's word of the moment (`cellWord`,
  `CELL_LOOKS`, 1.3.504): "cell off", starting, stopping, failed in red — the proxy's last word may be
  from before the cell stopped. The
  "＋ row" row, in the pool's strip (and on a pool with no row), is the sets' "＋ model" row (`newOutHtml`,
  1.3.500 — a button added an open row until then): carried from any point of it onto a model, it adds the
  row with its cable in one write
  (`POST /api/pools/add-row` with `target`); dropped elsewhere it adds nothing, and a click does nothing.
  A row with no cable comes only from a cell deleted under it. ✕ removes a row after a question
  (`POST /api/pools/remove-step`). "＋ New pool" makes an empty one, its name chosen in the field.
  **Pool settings** in the pool's strip, shut until opened (`settingsHtml`; the owner, 2026-10-12 — they had
  left with the main board's pool cards in 1.3.486; under the rows until 1.3.532): the window the pool states to its clients, blank for
  "not stated", and "use the smallest window its steps' models report" (`contextAuto`), both saved
  together by the pool cards' `save` (`saveWindow`), a refusal putting back what the controller keeps.
  Under them, what the pool states now: the controller's word, `window` (topology.py
  `annotate_pool_windows`, the proxy's own rule), "states no window" when it states none, and no line at
  all when the reading lacks the word. While a pool's name or window is typed, the board's own drawing
  waits for the field to let go (`typing`, landed on `focusout`).
- **Models** — each account: the models added to it (the owner, 2026-10-12: "only the ones I added",
  `topology.addedModels`, caravan/admin/added_models.py), in their order, then any a pool's row names
  that the list lacks (`PoolBoard.shown`) — never the account's whole catalogue. "＋ model" opens the
  account's list in its card (`pickerHtml`): a search field and the chat models it finds there
  (`PoolBoard.candidates`, the catalogue read when it opens — `GET /api/cloud-accounts/catalogue`, read
  again if it failed or was never fetched), at most 60 with the rest counted — and when the search finds
  none, the typed id offered as it is; a press adds one (`POST /api/pools/add-model`), Enter the first found,
  Escape closes. What is typed redraws the found models alone (`find`), and a drawing that lands while
  the field is typed in keeps it and its caret (`redraw`); a model of the list is pressed with the field
  keeping the focus, so the page's deferred drawing cannot replace the button between press and click.
  When the list shows nothing it says why: no sign-in, being read, unreadable, never read, no chat
  model, all added, no match. A model no row names has ✕ on hover (`POST /api/pools/remove-model`); a
  model a row is cabled to stays — the controller adds it with the cable. A subscription's
  model's own two levels on the 5H and WEEKLY bars (usage-stats.js, the handles keyed by the
  model: `data-level-account`, `data-level-model`, saved by `POST /api/pools/level`), its pair or the
  controller's default (`topology.modelLevels`) — no reading, no handles — stand in the model's strip
  (1.3.534, `levelsHtml`); the card draws the account's limits once (`limitsHtml`: the provider's word
  when the limit is reached, and each window with what is left and when it resets) and a model is a line:
  its handle, name and ⏱, a pill when its pool has stepped aside or stopped it (`levelTagHtml`, from the
  proxy's last word on the row: the stop first), and "in no pool" when none uses it. The pools that
  use a model are its strip's route. Each machine: its cells and
  the engines' models (`localOutputGroups` of the router's outputs) with their lamp and state, and in its
  head how many cells are in which state ("3 running · 5 stopped", `cellsSummary`: a failed cell is not a
  stopped one, a state nobody expected is "unknown", so the numbers add up to the cells there are); the
  stopped cells no row names fold under one button (`PoolBoard.foldCells`). Subscriptions are added on the main board (provider-glances.js), so the column's head
  has no ＋: an account's own "＋ model" adds its models.
  An account's card sets nothing of
  the account up (the owner, 2026-10-12: "no settings of subscriptions on the kanban"): its window ⚙,
  its saved resets and its provider's word are the main board's (provider-glances.js, cloud.js), and
  the spend line under ⋯ is gone — it said little. The card says the account's state, its limits with when
  its windows reset (`limitsHtml`), and its tripped endpoints with Retry and the routed errors of the last day, where the
  rows that call it stand. The readings say when they land (`READING_LANDED`, usage-stats.js), and the
  board draws itself anew then; a read the cache skips lands nothing.

The cables (`drawCables`) are measured from dot to dot after each drawing, in an SVG under the
columns, 1px as the main board's (1.3.504; the serving row's and the lit path's 1.5px); the cable in the
hand has an SVG of its own above them (`data-pb-live-layer`, 1.3.533: under the cards it would show in
the gutters only, and a cable that leaves the strip starts under a column); each has a wide
invisible twin the pointer finds, the key of its path (`data-pb-cable-key`)
and, to a pool and from it, the pool's colour. A press on an output's dot that travels more than 5 px
(`SLOP`) carries a new cable (`press`, `follow`, `release`; one that leaves the strip comes out of its
top edge, `track`): a client's lands on a set
(`POST /api/consumers/set`), a set's — from its "＋ model" row, in its strip — on a pool (`POST /api/sets/add-pool`),
a row's on a model (`POST /api/pools/connect-row`), a pool's "＋ row" — in its strip — on a model
(`POST /api/pools/add-row`), a model's — from its ⠿, drawn from the model's input — on a pool
(`POST /api/pools/add-row`) or on the Pools column off any pool (`POST /api/pools/create` with its
`target`). What each kind lands on is one table (`ONTO`), and what joining an output to a place asks of
the controller one rule (`PoolBoard.ask`), the same for a cable and for the chooser; the model's name
goes along as `nameAfter` — a pool under the board's name takes it (caravan/admin/pools.py). A "＋" row
(`data-pb-grab`) is pressed anywhere: its cable leaves from its dot all the same. Near an edge of the
board's box the cable leans on it (`edgeLean`, 56 px) and the board scrolls under it frame by frame
(`lean`, `scrollStep`), the page when the board is at its end. Dropped elsewhere, cancelled or let go
by Esc, it sends nothing; the click that ends a carried cable is swallowed (`swallowClick`). A press
that does not travel is a click: a click on an output opens **the chooser** (`openChooser`) — the
places its cable can go (`choices`: a client's sets, a set's pools, a row's models — `targets`, the
accounts' models on their cards and every machine's cells — a model's own new pool first, then the
pools), each with its line; where a cable goes now — for a row, every model its pool holds — ticked and
disabled; a search over them (`found`,
at most 60, the rest counted); Enter picks the first, Esc or a click elsewhere closes it. It stands
under the output in the board's scrolled box (upward when there is more room above), put in without
drawing the board anew (`showChooser`). A click on a cable cuts it after one question that names both
ends. A cable that cannot be placed is named in `drops`.

The strip below (1.3.532, `pool-dock.js`, `PoolDock`; of three mockups the owner chose "details in a
strip below", 2026-10-13): the last thing in the board's box, `position: sticky; bottom: 0`, 156 px high,
so pointing at a card moves nothing. It reads the board's trace — the card under the
pointer, or the pinned one: `PoolDock.aim(key)` says which card, `dockReader` gives its name, the route
lit across the columns (`routeOf`, in names, a model two accounts offer told by its account) and its
details (`dockDetailsHtml`); `paintDock` draws it anew in place with every `lightPath`, and a strip that
would read the same is left alone, so a field typed in it keeps its focus. It shows only while a card is
pointed at or pinned (1.3.538; the owner, 2026-10-14: "do not show the bottom strip when nothing is pointed
at or selected"): with no trace it is `data-t-state="empty"`, which hides it (`visibility: hidden`, a
quarter of a second late so that a pointer crossing the gap between two cards does not flash it) and draws
nothing new — it keeps what it said last, and keeps its place, so nothing moves when it shows and a board
scrolled to its end does not jump when it goes. Only a pinned strip takes the pointer: pointed at, it is
`inert`, the pointer passes through it, and a card under it can still be pointed at and pinned. To use a
control in it, click the card first (it pins; Esc lets go). A client's details are its two GET questions, "Test as the client" and
its errors, in one wrapper that carries its port (`display: contents`), so every handler finds the client
by `closest("[data-pb-client]")` as it did on its card. A pool's (1.3.533, `poolDetailsHtml`) are its rows
as the proxy says them — the rank, the model and where it stands, the state in words (also the quiet
ones), and under a row when the pool goes on to the next one (`turnText`) — then "＋ row", whose dot is
pulled onto a model, "Pool settings" and "Switch history", all in a wrapper that carries the pool
(`data-pb-pool`, `data-pool-id`). A set's (`setDetailsHtml`) are the models it gives its clients and
"＋ model". An empty pool or set keeps its "＋" on its card: it is all it needs there. A model's
(1.3.534, `modelDetailsHtml`) are, for a subscription's, the account's two limit bars with the model's own
levels and their handles — pressing a handle in the strip holds the board still as it did on the card
(`switchDrag`) — and for an account with no limits to read, its state in words; for a cell, its state in
words, "running" too, which its card says by its lamp alone. A client's card is a name, a key, "Models: N"
and a badge "⚠ N" (`missBadge`: how many times the lines it keeps say it was refused, "+" when lines were
cut off); the entry's address stands once under the column's head (`entryHtml`, with its ⧉).

The path through a card (`PoolBoard.path`, 1.3.503): from a card's key — `client:<port>`,
`set:<id>`, `setpool:<set>/<pool>`, `pool:<id>`, `row:<pool>/<row>`, `model:<key>` — up to the clients
that reach it and down to the models it reaches, never sideways. The pointer over a card lights it
(`hover`, `lightPath`: `tracing` on the board, `on-path` on its cards and cables); a click on a card's
free place pins it (`pin`, `traced`), a click on it again or Esc lets it go (`escape`, bound on the
window: the chooser closes first). The cables and the frames are one quiet colour, and the lit path
is the only place with the accent: pools had a colour of their own from 1.3.503 to 1.3.530 (`hueOf`),
and three of the eleven shared theirs with another. The calm look (1.3.531, the owner: "crowded and
motley"): a card's tools — the ✕ of its head, a row's ✕, a client's ⧉ — and the grips show
while the pointer is on the card or the keyboard in it (`--pb-quiet` is their opacity at rest, .8
where there is no hover), the marks of jobs and the key are grey, and a row's pill has a frame only
when its state is news. A row says its state by a pill only when the state is news (`statusHtml`):
serving, closed, off, missing, a sign-in asked for, a silent proxy, an unknown reason. The two states that
are no news (`quiet`, `status`: the row is fit and waits its turn, the proxy has not asked it yet) are a bare
dot, filled or hollow, with the words in its title and, in full, in the strip. A pool of one row is one
line (`single`: "=" for its rank); of two rows and more a ladder (`turns`: "N in turn"); what the pool does
between its rows (`turnText` — a subscription's model at its switch levels, `levelsText`, a cell when busy
or silent, else when it refuses) stands in its strip, with its settings, its history and its "＋ row". "⇅ Arrange" asks `POST /api/pools/arrange`. The cards of Clients, Sets and Pools stand in
seats (`seat`, `data-pb-seat`) in their columns (`data-pb-list`), carried by the ⠿ in their head
(`cardCarry`, StepCarry with `CARDS`); the order a carry leaves is saved by its column's door
(`ORDERS`: `POST /api/pools/order`, `/api/sets/order`, `/api/consumers/order`), and a refusal draws
the board again from what the controller keeps once the carry has let go (`redrawAfterCarry`; the
rows' order the same, `sortRows`). While a cable, a row or a level's handle is held, the page is
not drawn anew (`busy`, read by `topologyInteractionActive`); the drawing it waited for lands on the
release (`settled`). Opening a machine's "more", a pool's history or "＋ model" redraws the board
alone (`redraw`). The page draws the board whole after an action (a model added, a cable drawn), the
scrolled box with it: `html` reads where the old box stood scrolled and `mount` gives it to the new
one, so the columns do not jump back to the top.

Each model of the right column has a ⏱ beside its name (`schedule`, model-schedule.js): quiet while
the model has no schedule or one switched off, "until 19:00" while one is open, "closed until 19:00"
while one is closed. A pool's row of a model closed now says so before the proxy's last word, which
may be from before the window closed (`status`). While the pointer paints the schedule's hours, the
board is not drawn anew either.

- Owns: `POOL_BOARD` — what the operator opened (`expanded`, `history`, `picking` — the
  account whose "＋ model" is open and what is typed, `tests` — the clients whose tests are open),
  the catalogues read, the cable being carried.
- Key exports: `PoolBoard`, `POOL_BOARD`.

## model-schedule.js

When a model is open (1.3.498; the owner, 2026-10-12, visumap scheme caravan-model-schedule): the ⏱ on
each model of the kanban's right column and the window it opens over the board. The window has a
switch, a week of hours painted with the pointer — an hour open, part open or closed; a press on an
open hour closes it and every hour the pointer passes, a press on a closed one opens them — and the
same hours as windows with exact times, each with its days. The hours are the caravan's own: the zone
the controller names (`modelSchedules.zone`) by name, or by its offset when this browser does not know
the name, and UTC said as not known when the controller does not know its zone (`ScheduleClock`).
What a model is now — open until…, closed until… — is the controller's word (`modelSchedules.models`),
never worked out on the page. Save is held back while a schedule switched on has no window; a cell's
window says that its server is not started or stopped by the schedule yet (step 1). Save posts
`POST /api/models/schedule` and the board is drawn from the answer; a refusal is said in the
controller's words, and the window keeps what was edited.

- Owns: the window's draft (`form`) and the stroke being painted (`painting`).
- Key exports: `ModelScheduleEditor` (`chipHtml`, `closedWord`, `open`, `html`, `click`, `change`, `press`,
  `over`, `release`, `save`), `ScheduleClock`.

## week-windows.js

The browser's twin of caravan/common/week_windows.py: a window's days and times read as minutes of the
week (`runs`, `mask`) by the same rule, held to one table of cases with the server
(scripts/test_week_windows.py). The week the window paints is written back as windows one way for one
week (`fromMask`): an open stretch of a day or less is one window, overnight if it crosses midnight, a
longer one is cut at its midnights, and stretches with the same times are one window of their days.

- Owns: nothing.
- Key exports: `WeekWindows` (`runs`, `mask`, `share`, `paint`, `fromMask`, `minutes`, `hhmm`).

## pools.js

A pool is what an agent's cable goes to (the operator, 2026-10-10): an ordered chain of steps, each
one account with ONE model and, on a ChatGPT subscription, its own switch levels on the 5H and WEEKLY
windows. The proxy takes the first step that fits and moves on for limits only — the step's level,
429, 402, 401 (caravan/proxy/pool_steps.py); a 500 or a timeout is the backup node's work. Another
model is another pool. `PoolCards` draws each pool as its own card under Pools and acts on it.

The card owns its whole top (`head()`): the card's ↑ ↓ in the list under Pools and the pool's mark
(stacked layers — a pool is not one provider), the pool's **name as the title itself** (an input that
reads as text, saved on change), and beside it on the same line the last request (`lastHtml`:
"Last request: <account> · <model> · HH:MM"; the pool's own refusal with its time, "refused — no step fits"; "No request yet" when the
proxy has no word for the pool; "The proxy is silent" without its fresh word). There is no mode
switch — the pool serves by its order alone — and no fold: the card is always open (the operator,
2026-10-11, both). Then the steps: one `rung()` per step, a card of its own ringed when it serves,
joined by a slim line "Next, when this step reaches its switch level or a limit". A rung's head is
its number (inside the step: the column of numbered circles on a spine beside the cards went the
same day, for room), the grip, the account (its icon, name and the status pill), the model on its own line with its price, a ⚠ when the
provider no longer lists it, the account's mailbox; and the tools: the saved resets as a button
(`chooseReset` — the one door to a spend; `↺ ?` with the reason when the count could not be read,
`meta()`), the step model's spend, the limits' ↻ and the fold. A subscription with a sign-in draws
its limit bars under the head with the step's own levels; one without reads nothing — a read would
only draw "unavailable". A step shows its bars — the serving one too — only while the pointer is
on it, a control in it has focus or it is opened (a CSS rule in modals.css, pinned by
test_js_pools.py; the operator, 2026-10-11). Under the fold: Enabled (off takes the step out of the
order), ↑ ↓, ⚙ (the account's window — the original's for a legacy TEST alias) and ✕ (`removeStep`,
asked first; the account stays connected), then what a key's provider says, the account's 30-day
spend line and its errors. The saved resets are no longer listed there (1.3.464): the counter's
window lists them.

The status pill (`status()`): serving only on the proxy's word; an account without its sign-in or key
says so before the proxy does;
otherwise the proxy's reason through `REASONS` — every reason pool_steps.py gives has its words, and
an unknown one is "unavailable", never a guess.

The foot (`foot()`): "+ Add step" across the card, dashed — an empty place at the end of the order —
then one bar with the switches of two parts shut until opened (`partHead`, `shown`) — **Pool settings**
and, once the proxy has switched the pool's steps, **Switch history** — each opening as a panel under
the bar: the window the pool states to its clients, blank for "not stated", "use the smallest window
its steps' models report" (`contextAuto`) and **Delete pool**; the last five switches (`events()`).
These cards are not drawn since 1.3.486: the kanban's pool card opens the same settings (pool-board.js). An empty pool draws only what it is and its two ways on:
"+ Add a step" and "Delete pool". No pool at all: one card that says what a pool is, with "+ New
pool". Accounts that stand in no step are listed after the pools (`looseHtml`) with their ⚙ — never
out of sight.

`remove(poolId)` reads what leads to the pool from the controller (`GET /api/pools/refs`); when it
cannot say, the pool stays. With nothing leading there the question is plain; with cables or rules
it asks where they go — onto another pool, or disconnected (`PoolCards.CUT`) — and names a router's
default among them. A pool has no port of its own since 1.3.487 (the owner, 2026-10-12: every client
comes in through one address with its own key), so there is none to name. The clients of the entry that
call the pool by name are named too (`clients`, the controller's reading): they lose the model with
it, and the deletion takes its id out of the lists that ticked it. Every write of the pool is
`POST /api/pools/save` with only what the pool keeps (`PoolCards.payload`: the level reached, the
ports, the reading's time stay on the board). The order changes by carrying a step by its grip
(step-carry.js; `sort(poolId, ids)` saves the order it leaves behind, `PoolCards.ordered()` is the
pure rule — each step once, or nothing) or by ↑ ↓; while a step is carried, lands or its order is
saved, the lane is not rebuilt (`inFlight()` asks the carrier). The lane's own pieces — the lead, a
provider's icon, the bars, resets, the spend — are callbacks set by cloud.js, so the card does not
know where they are read. The card's CSS (modals.css, `.subscription-pool`, `.pool-*`) sets every
size itself: the global control sizes made the earlier card heavy.

- Owns: the open steps (`open`), the open parts (`shown`); `carry` is the lane's StepCarry.
- Key exports: `PoolCards`.

## step-carry.js

Carrying a pool's step to another place in its order, the way the home start page carries its cards
(the home portal's sort.js; the operator, 2026-10-11). `StepCarry` binds one lane container: a press on
a step's grip that travels more than 5 px lifts the step — the card follows the pointer by a
transform, its list item stays in the flow as the dashed empty place (`carried`, `--hole-h` is the
card's height), the list is marked `sorting`, the body `step-carrying` (grabbing cursor, no
selection). The empty place goes before the first step whose middle — read from the layout
(`offsetTop`, counted from the list itself when the list is positioned, `within`), not from what is
seen mid-slide — is below the pointer; the others slide aside (`Slide`: first, change, play, 220 ms).
Near the top or bottom of what scrolls — the window, or the element `scroller` gives (the kanban's
board) — it scrolls. What a seat, its list, the grip, an id and the card that travels are is
`STEPS` for a pool's steps and is told otherwise by `parts`: the kanban carries its clients', sets'
and pools' cards with the same carrier (1.3.503), and `onMove` is told each step of a carry (the
kanban draws its cables again). Letting go
glides the card into its place (180 ms; a timer lands it if the tab is not painted) and hands the
new order to `onSort(poolId, ids)`; Esc puts the steps back and saves nothing; a carry whose list was
drawn over lands nothing. Alt+↑/↓ on a focused grip moves the step one place and saves once, 700 ms
after the last press. `busy` holds the lane from the lift until the save answers — a refusal too,
named in the console.

- Owns: the carrier's phase (`idle`, `pending`, `carrying`, `landing`, `saving`) and the keyboard's
  unsaved moves.
- Key exports: `StepCarry`, `Slide`.

## pool-step-dialog.js

"+ Add step" and "+ New pool": one window, two errands (`PoolStepDialog`). First the account — one
already connected (each says how it signs in, or that it does not), or "+ Connect a new account",
which steps the window aside (`away`) while the account window is open and brings it back with the
new account chosen (`connectNew` / `back`). Then ONE model, from the list the controller last fetched
(`GET /api/cloud-accounts/catalogue`): chat models first, the rest under their own line, a window
size and a price where known, a search that redraws only the rows (the field keeps its caret), at
most `ROWS` (120) rows with "N more — narrow the search". A list never fetched is fetched first
(`POST /api/cloud-accounts/check-models`) when the account was never checked; the window says what it
knows about the list — read when, never read, being read, or the provider's refusal — and never
draws an unread list as "no models". An account without a sign-in shows no search: only why it
waits and the field for a typed model id. A typed id is the operator's last word over a picked row.
A new pool also takes its name (the model's by default). `submit()` sends `POST /api/pools/add-step`
or `/api/pools/create`; a refusal keeps the window and what was chosen. It listens on the board's
permanent container (`bind`, once) — the window inside is drawn over with every render.

- Owns: `form`, the lists read in this window (`catalogues`).
- Key exports: `PoolStepDialog`.

## cloud-ref-words.js

`CloudRefWords` says what still points at a pool, in the words its deletion lists it, from
`GET /api/pools/refs`: its ports, agent routes, cloud fallbacks, queue and rescue roles, rules and the
count of cables (`lines(refs)`), and the line under the question — those lines, or that nothing
points there (`detail(lines)`). "Delete pool" (pools.js) reads it. It imports only `t`, so the pool
card's snapshot loads it with `utils` stubbed.

- Owns: nothing.
- Key exports: `CloudRefWords`.

## consumer-access.js

How a consumer reaches the caravan, as the kanban's clients panel shows it (2026-10-07). Every
consumer calls one address — the entry — with its own key; `ConsumerAccess.lineHtml(proxy)` draws
a route's line in place of its port number: the key's last four characters (`keyTail`), "entry
only" once the port is closed (↺ reopens it), "port :N open" with "Close port" for a consumer that
had a key already, or "no key" with "Give a key" — which closes the port in the same step;
and when the consumer last called. `entryHtml(topology.entry)` is the panel's line with the
entry's address and a copy button, or "The entry is off". The actions ask first and call the
controller: `giveKey` (`POST /api/agent-proxies/route-key`; the window shows the key once beside
the address, and copies it on the operator's word), `closePort` (names the address the consumer
must already call), `reopenPort`, `copyEntry`. The address is the controller's (`ConsumerAddress`),
never built here. canvas.js draws the lines and binds the clicks in one document listener.
The entry is set up here (2026-10-08; it was settable only through the API, and "The entry is off"
led nowhere): `setupEntry` asks the public address (the board's own name with `-api` offered,
`suggestedAddress`), then the port (23999 offered; empty turns the entry off), and calls
`POST /api/agent-proxy-entry`; "Set up the entry" stands on the off line and ✎ on the address line.
The address line names the port too ("port 23999", `data-t="kanban-entry-port"`), unless the address
says it already: the reverse proxy must lead the public name to it, and it used to be seen only in
the second window of ✎ (the owner, 2026-10-11). ✕ (`turnOffEntry`, `data-t="kanban-entry-off"`)
turns the entry off after a question that names the port: `{port: 0, publicUrl: ""}`. The controller
refuses while a client of the entry exists and names it; the board does not count the clients itself.
`giveKey` with no entry address sets the entry up first and goes on with the key. "No address"
is two cases: the entry is off, or it listens where only this machine reaches it and has no public
name (`data-t-state="nameless"`). "no key" is red only where the ports have no door
(`topology.portsReachable === false`): elsewhere an open port without a key is how consumers have
always called. A port no client claims keeps its row (`InputsBlock.unclaimedRow`): its dot draws the
cable the proxy still routes by, and ✎ opens its window, where it is deleted. A client's wait budget
stands at the end of its name's line.

- Owns: nothing (the instance `CONSUMER_ACCESS` holds only its collaborators).
- Key exports: `ConsumerAccess`, `CONSUMER_ACCESS`.

## consumers.js

The consumers of the entry on the board (the owner, 2026-10-11: the caravan speaks the OpenAI API
as a company's gateway does). A consumer is a route of kind `"consumer"`: a name, its own key and
the set of models a cable on the kanban leads it to (`caravan/admin/consumers.py`; 2026-10-12). The
clients column draws them first, under the entry's address line (`ConsumerAccess.entryHtml`), and
the client records of the old kind with their ports after them. A card says the name, the key's last
four characters and when it last called, on one line with its three actions at the end — a new key,
✎, ✕ — quiet until the card is pointed at or holds the focus (`.consumer-acts`; the owner, 2026-10-12:
as clean as the kanban's card); and — when a cable leads it to a set — its recent requests under that
line, one row of the activity chart (`activityHtml`, `data-t="consumer-activity"`; charts.js draws
it): its set's name is not on the card, the kanban's card names the sets. With no cable it says so in the alarm
colour, with the words to draw one on the kanban; "not known" when the controller said nothing
(`setHtml`, `data-t="consumer-set"`, `data-t-state` none or unknown). A click on the row opens every
client's activity, ⤢.

＋ in the column's head is `create()`: the entry first when it is off (`setupEntry`), then the
name, then `POST /api/consumers/create`, and the key shown once beside the address and the models —
its set's, or the words that it has none yet. "Copy the key" copies it, "Done" loses it for
good. `newKey` says first that the old key stops working at once (`POST /api/consumers/key`);
`rename` and `remove` go through the route's own doors (`route-policy` with `label`,
`route-delete`). `bind(lane)` catches the column's buttons — the entry's copy and setup among them —
with one listener, bound once: the cards are drawn anew on every render.

A card lights while its client's request runs, as an agent's route row does: it carries
`data-topology-proxy` and the client's proxy id, so the activity walk (topology-activity.js) sets its
classes and a hover lights its cable. Its handle on the right is where its cable leaves from, to its
pool (cables.js); a client with no pool has no handle.

- Owns: nothing (the instance `CONSUMER_CARDS` holds only its collaborators; the entry's desk is
  read when it is used, since this module, consumer-access.js and the renderer import one another).
- Key exports: `ConsumerCards`, `CONSUMER_CARDS`.

## scout-add.js

The Add scout box under the Machines head: the one way a machine that lends its GPU or CPU joins the
fleet. `ScoutAddForm` takes the address the scout's `./install.sh` printed and pairs it
(`POST /api/topology/scout/connect`); the box is static markup beside the lane, so a typed address
survives the lane's repaints. Its state is on the block (`data-t-state` idle, working, ok, error).
It is closed until one of two buttons in the Machines head opens it — the section's main action
(the owner, 2026-10-11): ＋ Add scout (`open`, again to close; the scan closes with it) and
🔍 Find, which opens the box with the scan. A page without the head buttons keeps the box open.
`ScoutFinder` is that 🔍 Find (the owner, 2026-10-11): it opens a field for the networks to
scan — empty means the controller's own — and asks the controller to look
(`POST /api/topology/scout/scan`, caravan/admin/scout_scan.py). Each found scout is a row with its
machine, address, version and state: free (with Connect, which fills the form and pairs it as if
typed), already on the board, or held by another caravan. The networks typed last are remembered in
this browser as a convenience; the panel's state is on it (`data-t-state` idle, working, found, none,
error). A page without the panel gets the form alone.

- Owns: nothing (each instance holds its row's elements).
- Key exports: `ScoutAddForm`, `ScoutFinder`, `mountScoutAdd`.

## usage-stats.js

The usage & spend modal: overview/account/local scopes (scope, expanded row and day range live in
`ui.usageStats*`), model tables, pricing edits (`saveApiPrice`, `saveLocalPricing`) and provider
cost fetches — API costs, OpenRouter limits, proxy spend, subscription usage — cached with no TTL:
read once, then again only by the ↻ button, a spent reset or a return to the tab after a minute
(`refreshUsageReading`, `refreshUsageOnReturn`) — no timer, the operator's choice. A read again keeps
the bars as last read and marks them as being read — a light runs along them, `refreshing` and
`aria-busy` on the panel — until the answer lands; it is forced past the "good data held" refusal but
never past a read in flight. The first read, with nothing to show, draws a spinner and "loading
limits…" (`sub-usage-loading`). Until 1.3.463 a refresh forgot the reading first, and the bars
vanished from the card until the answer came. A step's fold carries its account's "⇄ 30 days via the caravan" line
(`proxySpendHtml`): requests, tokens and the total at API prices, its hover saying on a
subscription that the subscription covers it. The step's own model share stands in the step's head
(`proxySpendOf` → `cloudStepSpend`, cloud.js).

A subscription step's limit bars carry the step's two levels (`subscriptionLimitRowHtml(id, lim,
step)`; the operator, 2026-10-11): ▲ the stop under the bar, red, and ▼ the switch over it, yellow
(the owner, 2026-10-12, in place of the emoji of the day before) — each a triangle pointing at the bar,
worn as a range input's thumb (an SVG in modals.css, filled with the level's colour — `--level-stop`,
`--level-switch`, which the hatching, the names and the legend's signs read too), keyed by
the window's length, ranging to the server's ceiling
(`step.switchMax`) and spanning that share of the bar, so a flag stands where its hatching ends — red
under the stop, amber between the stop and the switch. Only a flag's thumb takes the pointer, so the
two can stand on one mark and both be grabbed. Each level is named beside its own flag, on the flag's
side of the bar (`LEVEL_MARKS`: the switch only above the stop, the stop only when there is one) —
right of it, or left of it past the middle, where the name would run into the reset time; `place`
reads the flag's width from `--level-thumb` (modals.css), the one place it is said. A pool step's
bar is one line: the window's name left of it, when it resets and what is left right of it (the
owner, 2026-10-11: compacter; the names used to stand in a line of their own). The step's bars share
the panel's grid (subgrid): the names stand in one column, every bar starts and ends at the same
place, and the reset times end at one edge; the level names are in a softened hue of their handle. The hooks and hovers come from
`LEVEL_HANDLES`, which also holds each level's sign, and one line under the bars says what ▼ and ▲
mean — the same signs in every language, in their handles' colours (`levelsLegendHtml`; pinned by
test_js_usage_stats.py). A bar outside a step, a window
without a length and a reading without the ceiling get no flags: a setting that does nothing is not
drawn. Each step has its own levels — one subscription may stand in two pools and leave one earlier.
While a flag moves (`previewSwitchLevel`) the stop pushes the switch up and the switch rests on the
stop, as the server keeps them. Letting go saves that level (`saveSwitchLevel` → `POST
/api/pools/level` with `level`, the board drawn from the answer); a failed save is said in a toast and
the flag goes back to the saved level. While the pointer holds a flag the lane is not rebuilt
(`switchDrag`); it is redrawn on release. When the step's stop is reached (`step.stopReached`), a red
banner says the step does not serve until the reset; below its switch (`step.switchReached`), a banner
says until when the pool sends requests to its next steps first — the controller's reading by the
proxy's rule. OpenAI's own limit banner comes first.

- Owns: `usageStatsData`, `apiCostsCache`, `openrouterLimitsCache`, `proxySpendData`, `subscriptionUsageCache`, `usageStatsApiPriceEdit`, `switchDrag`.
- Key exports: `openUsageStatsModal`, `renderUsageStatsModal`, `fetchUsageStats`, `fetchApiCosts`, `saveApiPrice`, `saveLocalPricing`, `proxySpendHtml`, `proxySpendOf`, `subscriptionLimitRowHtml`, `saveSwitchLevel`, `previewSwitchLevel`, `switchDrag`.

## history.js

The request-history modal over `/api/agent-proxy-logs`: a Requests tab (finished and refused
requests, `event=finished,blocked`) and an Events tab (raw), date selection, client/via/status
filters, and a per-row detail popup. A request the caravan turned away before any model answered
(no key, a wrong one, a paused or unrouted route, a full queue) ends as `blocked`, and until
2026-10-11 it left no row in the Requests tab. Its row says "refused" with the reason
(`historyVia(row)` — one reading for the tag and the via filter, which offers it), its status as an
error, and "—" for a duration it never had, not "0ms".

- A row's client cell is the address the proxy recorded. (The monitor's client labels are gone
  since step 6.9 — both arms of the old "labelled?" choice drew the address anyway.)
- Owns: `historyRows`, `historyEventRows`, `historyTab`, `historyCurrentDate`, the filter values.
- Key exports: `openRequestHistory`, `closeRequestHistory`, `loadRequestHistory`, `renderHistoryTable`, `openHistoryDetailPopup`.

## system-panels.js

The System page's sections: section tips, project git branch (an image build has none: the chip
names its commit, `projectGit.baked` — it read "git: docker"), Known Problems, controller info,
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

A client's recent requests stand on its own card (`drawClientActivity`; the owner, 2026-10-11 for
the strip under the clients, 2026-10-12 for its rows on the cards): every request the client made over
the monitor's window, the cloud's too — a machine's strip shows only what its cells served. Each
`canvas[data-consumer-activity]` gets its client's one row, without its name (the card's head has it),
drawn as the strip was: a mark per moment a request ran, on the dark ground (the owner, 2026-10-12: a
grey bar on the card's own ground said nothing). A row with no mark says so in words, with the
window's length (`idle`, "no requests in N min"); no sample yet — "no data". Either way, not an empty
row that would read as a quiet client. A
click opens the activity window whole, titled "Client activity", its rows `clientActivityLabels()`: the
clients of the entry as their cards stand (`ConsumerCards.of`: the operator's order, then by name),
then the older clients' routes in their cards' order. A strip of rows is drawn at its own height (`chartSize` with `minHeight`): with
the floor of 120 a two-row strip was drawn 120 high and squeezed into 43. Only the window sets
`_routeActivityDrawState` (`hover`): the strips drawn after it on every sample took it over, and the
window's tooltip named another chart's rows.

- Owns: `_routeActivityDrawState`, `CHART_EXPAND_CONFIGS`, `_chartExpandType`, hover-binding flags.
- Key exports: `drawMetricChart`, `drawTopologyGpuHistory` (the per-sample redraw of everything above), `drawTopologyTokenSpeedHistory`, `drawTopologyServerStats`, `nodeEndpointSet`, `nodeActivityFilter`, `miniSparklineSvg`, `systemSamples`, `drawClientActivity`, `clientActivityLabels`.

## model-meta.js

Model-name parsing (`parseModelName`), model/projector icons, per-server bench fetches, and the
Artificial-Analysis score queue (batched, self-pumping). Fetches `/api/proxy-daily-stats` and
`/api/model-pricing` into module caches that renderers read synchronously.

- Owns: `proxyDailyStats`, `modelPricing`, `aaScores`, `serverBenchCache`, the AA queue internals.
- Key exports: `parseModelName`, `topologyModelIcon`, `fetchProxyDailyStats`, `fetchModelPricing`, `fetchServerBenchIfNeeded`, `aaBadgeHtml`.

**HF page**

## river.js / river-prefs.js / river-background.js / river-dock.js / river-*.js

The brook behind the pages (1.3.527): a living stream seen from above, WebGL water with trout,
leaves and ripples, under every page. Every page loads `river.js`; it puts one switch in the
header, before the tour (before the language picker on a page without a tour), and the switch is
**off by default**: off loads nothing — no canvas, no WebGL, no sound, not even the brook's code.
The viewer's choice (on, the brightness, paused) is kept in localStorage by `river-prefs.js`, so the
brook is there, or not, on every page alike; a refused store reads as the defaults.

On, the switch brings in `river-background.js`: the stage (`river-core.js`) under everything the page
draws, a shade over it for the brightness, and the dock (`river-dock.js`: brighter / softer / darker,
pause, sound). The dock hangs under the switch and opens from a ▾ that joins the switch while the
brook runs; a dock fixed at the bottom of the window covered the end of the lists on /hf and
/kanban and sat on /hf's own dock. While the brook runs `html.river-on` is set, and only then does
`river.css` make the page's ground give way and its panels let a little water through; text that
stands on the ground with no card under it gets a dark halo, and /hf's two columns get a pane
(the repository column only while it shows a repository). The pointer stays the page's: movement
ripples the water, and a press on open space (no control, no painted card under it) drops a fly.
Sound is synthesized (`river-sound.js`), a calm brook only, and off on every load: a browser starts
sound only from a click. The scene is `river-scene.js` over `river-world.js`, `river-water.js`
(WebGL, `river-gl.js`), `river-life.js`, `river-fish.js` and `river-art.js`.

Words come from the shared dictionary through `i18n-data.js` (`translate`), not `i18n.js`: `i18n.js`
imports form.js and with it half of the board. That makes `river.js` the one shared module /hf loads
besides utils.js and onboarding.js, and it brings the shared tables to /hf lazily, after the page is
up, for its own fifteen words; the HF page's own text stays on `hf-text.js`.

The banks (1.3.536; the owner, 2026-10-13: "the fish and the striders go under the bank"): the bank is
drawn over the water's edge, so nothing alive may cross it. `Channel.inward` says how far a point must
move across the stream to stand a margin inside the edge; a fish keeps every point of its body — snout,
middle, tail — inside (`Swimmer.stayInWater`, `BANK_ROOM` 0.2 of its length) and a strider its legs'
reach (`Strider.BANK_ROOM`, 1.8 body lengths), and what carried them into the bank is lost. A scare — a
fast pointer over a trout, a minnow or a strider, or a double click — sends the animal along the stream
only (`Channel.away`: downstream or up, whichever lies away from the danger; level with it, downstream).
A double click makes a big ring and, 0.16 s later, a smaller one (`Echoes`); it threw drops into the air
before (`Specks.splash` still serves a trout's rise to a fly). Pinned by `test_js_river.py`: the geometry,
a trout pressed at either bank, a fish turned away from a bank with its tail across the edge, the scares,
a strider, the rings.

- Owns: the switch (`RiverSwitch`), the brook while it runs (`RiverBackground`), its dock
  (`RiverDock`), the stored choice.
- Key exports: `RiverSwitch`, `RiverPrefs`, `RIVER_LEVELS`, `RiverBackground`, `RiverDock`, `Stage`,
  `BrookScene`.
- Pinned by `scripts/test_js_river.py`.

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
  capabilities, format, date, what is on disk: GGUF files and checkpoint folders) and `HfCatalog` (results, server-kept favorites,
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
  library has it) — from `libraryFiles` of `/api/hf/local-check`. A checkpoint folder on this disk
  (`checkpointFolders`) gives a repository with no GGUF file the Verify button too, and the answer
  for it is one line per copy under the checkpoint row — counts of what matched by hash, differs, is
  missing, has the wrong size, or was held by size only because the hub gave no hash (a gated
  repository hides it: that copy is "?", not "✓"); the file names are in its tooltip, not on the page.
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
