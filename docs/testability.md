# Testability contract

An E2E suite drives this UI from outside, through a browser, as a user does.
That only works if a few things about the page are promises rather than
accidents. This document is the list of promises.

The previous suite, `lama-caravan-playwright`, was removed on 2026-10-07. New
tests will be written from scratch against this same contract.

## `data-t` is public API

An element carrying `data-t` is one an automated test depends on. Renaming or
removing one is a decision, not a side effect of a refactor, and it belongs in
`CHANGELOG.md` like any other breaking change.

The cost of getting this wrong is asymmetric and easy to underestimate: a silent
rename breaks a test without a single line changing in the test, and the failure
reads as "the tests broke by themselves" — which is how a suite loses the trust
that made it worth writing.

**Naming.** `<section>-<object>-<action>`, lowercase latin, hyphens:

```html
<button data-t="models-path-save">…</button>
<button data-t="system-tab-security" role="tab">…</button>
<div    data-t="kanban-node" data-t-id="node-42">…</div>
```

Repeated elements — board nodes, list rows — share one `data-t` and carry
`data-t-id` with the entity's own id, so a test can ask for *all* of them or for
*that* one.

**`data-t` is added alongside** existing `id`, `class` and `aria-*`. Nothing is
removed to make room; the other attributes have their own jobs.

**Priority: elements with `data-i18n`.** Their text changes with the interface
language, so a locator that matches on text passes in English and fails in
Russian — and every translation edit becomes a test failure in a working
application. `data-t` does not move when the words do.

## The header is the same on every page

Left to right, on all five:

```
[← back] [brand] [version] · [page title h1] · [page actions] [account] [brook] [tour] [language]
```

`/board` has no back-link (it is where back goes). `/models` and `/system` have
no Tour button because those two pages have no tour — the others do. Everything
else is present everywhere, in that order.

The brook switch (1.3.527, `static/js/river.js`) is put into the header by
script, the same on all five pages, in a group of its own (`.river-switch`):
`data-t="header-river-toggle"`, with `data-t-state` `off` or `on` and
`aria-pressed` to match. It is off until a viewer turns it on, and the choice is
kept in the browser's localStorage (`riverOn`, `riverLevel`, `riverPaused`).
While it is on, a ▾ joins it in the group, `data-t="header-river-settings"`
(`data-t-state` `closed` or `open`, `aria-expanded` to match), and opens the
dock under it: `data-t="river-dock"`, its buttons `river-level` (with
`data-t-id` `bright`, `soft` or `dim` and `aria-pressed` on the chosen one),
`river-pause` and `river-sound`. A press outside the dock or Escape closes it.

It was not so until 1.3.180: `/hf` and `/kanban` had bespoke headers with no
brand, **no account menu and no language picker at all** — the only way to
change language on `/hf` was a picker buried inside its tour — `/models` had no
version chip, and the back-link sat on the right on two pages and the left on
two others.

`/hf` keeps its own dictionary (it does not load the shared one), so its
language picker is built from that table and reloads the page on change;
its version chip reads `/health` rather than the fleet state it never fetches,
so it shows the version without the branch.

## One `<h1>` per page, and it names the page

Every page has exactly one `<h1>`, and it is the page's own name — `Main board`,
`Models on disk`, `System & settings`, `Kanban board`, `HuggingFace Browser`.
The product name in the banner is **not** a heading; it is a plain container
with the same class, so nothing moved visually.

It was the other way round until 1.3.179: the banner's `LAMA CARAVAN` was the
`<h1>` on every page, so navigating by heading told you the product's name
wherever you were. `/models` and `/system` had a *second* `<h1>` in their hero
(now `<h2>`, since the topbar names the page), and `/kanban` and `/hf` had none
at all.

```ts
page.getByRole('heading', { level: 1 })   // exactly one, on every page
```

**Do not assert on its NAME to identify the page.** It is translated, like
everything else visible — under `?lang=ru` it reads `Доска`, not `Main board`. For
"which page am I on", use `data-t-page` or the URL; both are language-
independent. The heading is for people, and for `getByRole` by role rather
than by name.

The `header-page-title` hook is on it, on all five pages.

## Which page: `data-t-page` on `<body>`

```html
<body data-t-page="board" data-t-state="loading">
```

| value | page |
|---|---|
| `board` | `/board` |
| `kanban` | `/kanban` |
| `models` | `/models` |
| `system` | `/system` |
| `hf` | `/hf` |
| `login` | `/login` |
| `setup` | `/setup` |

It sits in the HTML, so it is true **from the first byte** — before any script,
while the loading screen is still covering the page. That is precisely the
moment nothing else can be asked.

The **URL** is the other honest answer, and since 1.3.178 it is unambiguous:
one address per page, with the old ones redirecting (`/` and `/index.html` →
`/board`, `/router` → `/kanban`). Assert on either; they cannot disagree.

The two that do NOT work: the **title** is English on every page and always
will be, and the **header subtitle** is the opposite problem — it follows the
interface language, reading `Models on disk` or `Модели на диске` depending on
who is looking.

What `data-t-page` still adds over the URL is *when*: it is readable at
`waitUntil: 'commit'`, before any script has run, while the loading screen
covers the page — and after a client-side redirect it says where you ended up
without parsing anything.

**It pairs with `data-t-state`, and the pair is the point.** They answer
different questions and a test usually wants both:

```ts
await expect(page.locator('body')).toHaveAttribute('data-t-page', 'models');   // where
await page.waitForFunction(() => document.body.dataset.tState === 'ready');    // how far along
```

**The loading screen is not a page.** `#appLoader` is a `<div>` in the same
document, hidden by `window.__plHide()` once the app paints — same URL, same
title, same `data-t-page`. It has no name of its own on purpose: naming it would
say a navigation happened when none did. It is a *state*, and
`data-t-state="loading"` is what reports it.

## Page readiness: `data-t-state` on `<body>`

Pages paint first and fill from `/api/*` after. Without a signal, anything
driving the UI has to guess which of those two moments it is looking at, and a
guess is how a suite starts failing one run in ten.

```html
<body data-t-state="loading" aria-busy="true">   <!-- in the HTML, before any script -->
<body data-t-state="ready"   aria-busy="false">  <!-- first load arrived and rendered -->
<body data-t-state="error"   aria-busy="false" data-t-state-detail="…">
```

One flag on `<body>`, not one per container: each page has a single first load
that fills it, so per-container flags would be more moving parts saying the same
thing.

**`error` matters as much as `ready`.** A page stuck at `loading` forever makes a
waiter time out slowly with nothing to show for the wait; `error` fails it
immediately and puts the cause in `data-t-state-detail`.

Where it is set:

| page | ready when | file |
|---|---|---|
| `/board` | the topology rendered for the first time | `static/js/topology-render.js` |
| `/kanban` | topology fetched and the router rendered | `static/js/main.js` |
| `/models` | the model tree is drawn | `static/js/models-page.js` |
| `/system` | `/api/state` + `/api/controller-info` settled | `static/js/system-page.js` |
| `/hf` | token status, favourites and download jobs settled; the detail counts the start-up loads that got nothing | `static/js/hf-page.js` |

Helper: `markPageState(state, detail)` in `static/js/utils.js`.

## `/health`

Open, unauthenticated, cheap. It is what a CI run asks before it has
credentials — or when the question is precisely whether credentials can be
checked at all.

```
GET /health        (also /api/health)
200 {"ok": true, "service": "lama-caravan", "version": "1.3.453",
     "commit": "5ff3bbe", "authRequired": true, "setupRequired": false,
     "time": 1785342505}
```

The shape is **stable**: a monitor polls it forever, so fields can be added and
never taken away. It touches no fleet state — no host probes, no config — so the
liveness check can never itself become the slow or flaky thing.

`authRequired` is `true` on every install since 1.3.453, when a fresh one
stopped being open; `setupRequired` says the first account is still to be made
at `/setup`, so a suite learns it before it tries to sign in to nobody.

## `/openapi.json`

The API a suite drives, described as OpenAPI 3.1 — open, like `/health`, and
built from the route tables and the handlers' docstrings when the controller
starts, so it cannot fall behind the code (the hand-written list had). The same
list, for people, is [http-api.md](http-api.md).

```
GET /openapi.json
200 {"openapi": "3.1.0", "info": {"version": "78adf78b", "x-release": "1.3.459"}, "paths": {…}}
```

`info.version` is the commit `/healthz` names; the release number is `info.x-release`.

Level 1: every path and method with `summary` (and `description`), the query
parameters and top-level body fields the handler's code reads, the content
types it answers with, and who may call it — `security` plus `x-caravan-roles`
(`["admin", "viewer"]` or `["admin"]`). Types and answer shapes are not
described yet, and the document says so rather than drawing empty ones. Where
a handler passes its query or body on whole, `x-caravan-query-complete` /
`x-caravan-fields-complete` is `false`: it may read more than is listed.
`x-caravan-handler` names the function behind each operation.

## `/api/packages`

What the running controller is made of, named as osv.dev names it — open, like
`/healthz`, for the vulnerability check of the home network. `version` is the
commit `/healthz` names. In the image the system's packages go by their Debian
SOURCE package; a system the controller cannot read says `"listed": false`, one
it cannot tell is `"os": null`.

```
GET /api/packages
200 {"version": "78adf78b", "runtime": {"name": "python", "version": "3.12.12"},
     "os": {"name": "debian", "version": "13", "listed": true},
     "packages": [{"ecosystem": "PyPI", "name": "pip", "version": "25.2"},
                  {"ecosystem": "Debian:13", "name": "openssl", "version": "3.5.1-1"}, …]}
```

## Read-only account

Roles are `admin` and `viewer`. `viewer` is enforced **server-side**, in the auth
guard: every `GET` passes, everything else answers `403`, logout excepted. It is
not a UI convention that a crafted request can step around.

```sh
.venv/bin/python -m caravan.admin.auth create-user --role viewer <name>
.venv/bin/python -m caravan.admin.auth list
```

Run the read-only half of a suite as a `viewer`. A test is code that clicks
faster than a person and never hesitates; under `admin` a wrong locator is a
wrong button, and the blast radius is the whole fleet.

## Labels

Every input has a programmatic label — `<label for>`, `aria-label` or
`aria-labelledby` — so `getByLabel` works. This is the most readable locator
there is, and the same change is what lets a screen reader name the field. The
sign-in form already does this.

## The names, as they stand

Generated from the source, not from memory — 567 values. Regenerate with
`python3 scripts/testability_names.py`; `--check` fails when this list and the
source disagree. Fifty-two of them are composed at runtime (`…-picker`,
`…-runner-tab`, `cell-source-stale`) and a plain grep will not find them —
that is why there is a script and not a one-liner.

**agent** — `agent-bind-menu`, `agent-bind-taken`, `agent-no-route`, `agent-proxy-bind`, `agent-remove`, `agent-rename`, `agent-row`
**app** — `app-toast`
**board** — `board-agent-card`, `board-client-caption`, `board-clients-lane`, `board-consumer-card`, `board-density`, `board-gpus-lane`, `board-hf-open`, `board-incidents-list`, `board-incidents-open`, `board-kanban-card`, `board-kanban-counts`, `board-llama-suspect-banner`, `board-llama-suspect-row`, `board-machine-cards`, `board-models-open`, `board-nodes-lane`, `board-pages`, `board-processes-list`, `board-provider-cards`, `board-router-lane`, `board-scout-add`, `board-system-open`
**cell** — `cell-broken-error`, `cell-card`, `cell-config-search-hit`, `cell-config-search-results`, `cell-config-search`, `cell-configure`, `cell-crashed`, `cell-delete`, `cell-engine-model`, `cell-job-asr`, `cell-job-embed`, `cell-job-llm`, `cell-job-robot-policy`, `cell-job-speech-translate`, `cell-job-translate`, `cell-job-tts`, `cell-model-disk-newer`, `cell-model-in-library`, `cell-model-stale`, `cell-remote-apply`, `cell-remote-cancel`, `cell-remote-command-preview`, `cell-remote-command`, `cell-remote-compute`, `cell-remote-env`, `cell-remote-fields`, `cell-remote-health-path`, `cell-remote-max-model-len`, `cell-remote-mmproj`, `cell-remote-modal`, `cell-remote-model-name`, `cell-remote-model-picker`, `cell-remote-model`, `cell-remote-moonshine-model-picker`, `cell-remote-moonshine-model`, `cell-remote-offload-slider`, `cell-remote-offload`, `cell-remote-runner-tab`, `cell-remote-runner`, `cell-remote-seamless-lang`, `cell-remote-split`, `cell-remote-translate-model`, `cell-remote-translate-src`, `cell-remote-translate-tgt`, `cell-remote-vllm-model-picker`, `cell-remote-vllm-model`, `cell-remote-whisper-model-picker`, `cell-remote-whisper-model`, `cell-remote-workdir`, `cell-row`, `cell-row-start`, `cell-row-stop`, `cell-source-stale`, `cell-start`, `cell-stop`, `cell-window`, `cell-window-close`, `cell-window-via`, `cell-remote-cache`, `cell-remote-strata-context`, `cell-remote-strata-draft`, `cell-remote-strata-fields`, `cell-remote-strata-kv`, `cell-remote-strata-reserve`, `cell-remote-strata-vocab`, `cell-remote-gr00t-backbone`, `cell-remote-gr00t-embodiment`, `cell-remote-gr00t-fields`, `cell-remote-gr00t-steps`

**client** — `client-add`

**consumer** — `consumer-activity`, `consumer-delete`, `consumer-key`, `consumer-new-key`, `consumer-rename`, `consumer-set`

**fold** — `fold-pin`, `fold-unpin`

**cloud** — `cloud-account-plan`, `cloud-account-pools`, `cloud-account-status`, `cloud-account-window`, `cloud-connected`, `cloud-device-code`, `cloud-device-login`, `cloud-device-open`, `cloud-done`, `cloud-new-code`, `cloud-pick`, `cloud-picker`, `cloud-provider-word`, `cloud-sign-in`, `cloud-sign-in-ended`, `cloud-sign-in-wait`

**pool** — `pool-add-step`, `pool-card`, `pool-delete`, `pool-empty`, `pool-levels-legend`, `pool-loose`, `pool-loose-account`, `pool-name`, `pool-new-first`, `pool-none`, `pool-settings`, `pool-step`, `pool-step-account`, `pool-step-cancel`, `pool-step-check`, `pool-step-connect`, `pool-step-custom`, `pool-step-list-state`, `pool-step-model`, `pool-step-name`, `pool-step-query`, `pool-step-remove`, `pool-step-submit`, `pool-step-window`, `pool-stop`, `pool-switch`

**route** — `route-caller`, `route-context`, `route-context-line`, `route-context-model`, `route-context-prefer`, `route-detail-delete`, `route-detail-edit`, `route-detail-tab`, `route-latency`, `route-latency-row`, `route-model`, `route-model-card-link`, `route-model-lock`, `route-state`, `route-wait`

**sub-usage** — `sub-usage-banner`, `sub-usage-loading`
**confirm** — `confirm-accept`, `confirm-cancel`, `confirm-check`, `confirm-check-all`, `confirm-choice`, `confirm-input`, `confirm-meta`, `confirm-overlay`, `confirm-path`, `confirm-text`, `confirm-title`
**header** — `header`, `header-app-title`, `header-lang-current`, `header-lang-menu`, `header-lang-open`, `header-page-subtitle`, `header-page-title`, `header-user-chip`, `header-user-logout`, `header-user-menu`, `header-user-menu-open`, `header-user-name`, `header-user-security`, `header-version-branch`
**hf** — `hf-bench-panel`, `hf-bench-refresh`, `hf-bench-toggle`, `hf-capability-filter`, `hf-checkpoint`, `hf-checkpoint-download`, `hf-checkpoint-verified`, `hf-confirm`, `hf-confirm-cancel`, `hf-confirm-ok`, `hf-dock`, `hf-download-cancel`, `hf-download-dismiss`, `hf-download-interrupted`, `hf-download-job`, `hf-download-resume`, `hf-download-start`, `hf-downloads`, `hf-downloads-toggle`, `hf-file`, `hf-file-check`, `hf-file-delete`, `hf-file-in-library`, `hf-frontier`, `hf-frontier-open`, `hf-frontier-refresh`, `hf-in-library`, `hf-limit`, `hf-load-progress`, `hf-low-toggle`, `hf-mask`, `hf-on-disk`, `hf-other-toggle`, `hf-quant`, `hf-repo`, `hf-repo-star`, `hf-result`, `hf-search-input`, `hf-search-submit`, `hf-selection-clear`, `hf-selection-plan`, `hf-selection-remove`, `hf-selection-toggle`, `hf-size-filter`, `hf-sort`, `hf-sort-dir`, `hf-star`, `hf-tab`, `hf-token-clear`, `hf-token-edit`, `hf-token-input`, `hf-token-menu`, `hf-token-save`, `hf-tree-repo`, `hf-tree-toggle`, `hf-verify`
**kanban** — `kanban-back-link`, `kanban-cable`, `kanban-cables`, `kanban-canvas`, `kanban-consumer-close`, `kanban-consumer-give-key`, `kanban-consumer-key`, `kanban-consumer-reopen`, `kanban-entry`, `kanban-entry-copy`, `kanban-entry-off`, `kanban-entry-port`, `kanban-entry-setup`, `kanban-entry-why`, `kanban-fit`, `kanban-input-wait`, `kanban-model-queue`, `kanban-model-queue-toggle`, `kanban-node`, `kanban-onerror-same`, `kanban-out-state`, `kanban-palette-add`, `kanban-queue-setting`, `kanban-queue-settings`, `kanban-queue-settings-toggle`, `kanban-quiet-cells`, `kanban-save-status`, `kanban-unassigned`, `kanban-unclaimed`
**pb** (the kanban's pools board, pool-board.js) — `pb-account`, `pb-account-issues`, `pb-add-model`, `pb-add-pool`, `pb-add-row`, `pb-add-set`, `pb-arrange`, `pb-cables`, `pb-choice`, `pb-choose-close`, `pb-choose-note`, `pb-choose-query`, `pb-chooser`, `pb-client`, `pb-client-ask`, `pb-client-copy`, `pb-client-links`, `pb-client-miss`, `pb-client-misses`, `pb-client-misses-badge`, `pb-client-probe`, `pb-client-probe-model`, `pb-client-tests`, `pb-clients`, `pb-dock`, `pb-dock-body`, `pb-dock-cell`, `pb-dock-client`, `pb-dock-foot`, `pb-dock-id`, `pb-dock-levels`, `pb-dock-model`, `pb-dock-pool`, `pb-dock-set`, `pb-dock-step`, `pb-entry`, `pb-history`, `pb-history-toggle`, `pb-kind`, `pb-limits`, `pb-machine`, `pb-machine-cells`, `pb-model`, `pb-model-grab`, `pb-model-level`, `pb-model-remove`, `pb-model-unused`, `pb-models`, `pb-models-none`, `pb-no-clients`, `pb-no-models`, `pb-no-pools`, `pb-no-sets`, `pb-pick-close`, `pb-pick-model`, `pb-pick-note`, `pb-pick-query`, `pb-pick-typed`, `pb-picker`, `pb-pool`, `pb-pool-delete`, `pb-pool-name`, `pb-pool-turns`, `pb-pool-window`, `pb-pool-window-auto`, `pb-pool-window-stated`, `pb-pools`, `pb-probe`, `pb-probe-close`, `pb-probe-status`, `pb-route`, `pb-row`, `pb-row-remove`, `pb-set`, `pb-set-add`, `pb-set-delete`, `pb-set-model`, `pb-set-name`, `pb-sets`, `pb-settings`, `pb-settings-panel`, `pb-turn`, `pool-board`
**pb-schedule** (when a model is open: its ⏱ on the kanban and the window that sets it, model-schedule.js) — `pb-model-schedule`, `pb-schedule`, `pb-schedule-add`, `pb-schedule-cell-note`, `pb-schedule-close`, `pb-schedule-enabled`, `pb-schedule-grid`, `pb-schedule-needs-window`, `pb-schedule-no-windows`, `pb-schedule-now`, `pb-schedule-save`, `pb-schedule-window`, `pb-schedule-zone`
**login** — `login-error`, `login-form`, `login-lang`, `login-password`, `login-submit`, `login-username`
**model** — `model-file-stale`, `model-in-library`, `model-job-asr`, `model-job-embed`, `model-job-llm`, `model-job-robot-policy`, `model-job-speech-translate`, `model-job-translate`, `model-job-tts`

**models** — `models-delete-selected`, `models-filter`, `models-filter-clear`, `models-filter-empty`, `models-filters`, `models-folder-item`, `models-fresh-at`, `models-fresh-auto`, `models-fresh-check`, `models-fresh-get`, `models-fresh-keep`, `models-fresh-stamp`, `models-hf-open`, `models-library-file`, `models-model-select`, `models-move-branch`, `models-move-dest`, `models-move-dismiss`, `models-move-menu`, `models-move-open`, `models-move-progress`, `models-move-selected`, `models-move-stayed`, `models-move-stop`, `models-move-target`, `models-moves-summary`, `models-path-cancel`, `models-path-edit`, `models-path-edit-row`, `models-path-input`, `models-path-save`, `models-path-value`, `models-picked-summary`, `models-place-all`, `models-place-card`, `models-place-open`, `models-search`, `models-selection`, `models-staged-download`, `models-staged-progress`, `models-staged-revert`, `models-store`, `models-store-add`, `models-store-add-cancel`, `models-store-add-open`, `models-store-add-path`, `models-store-add-row`, `models-store-files`, `models-store-meta`, `models-store-remove`, `models-store-repath`, `models-store-repath-cancel`, `models-store-repath-input`, `models-store-repath-row`, `models-store-repath-save`, `models-store-state`, `models-store-why`, `models-store-why-command`, `models-stores`, `models-stores-error`, `models-summary`, `models-summary-bar`, `models-summary-facts`, `models-tree`, `models-tree-group`, `models-tree-group-toggle`, `models-tree-head`, `models-unused-select-all`, `models-unused-summary`
**engine** — `engine-model`, `engine-model-reserve`, `engine-shelf`
**node** — `node-caravan`, `node-caravan-add`, `node-caravan-hf`, `node-caravan-models`, `node-cell-filter`, `node-disconnect`, `node-driver-warning`, `node-engine`, `node-engine-busy`, `node-engine-delete`, `node-engine-expose`, `node-engine-job`, `node-engine-missing`, `node-engine-server-busy`, `node-engine-start`, `node-engine-stop`, `node-engine-unload`, `node-engine-vram`, `node-hide-idle`, `node-poweroff`, `node-power-schedule`, `node-reboot`, `node-scout-old`, `node-scout-silent`
**host-power-schedule** — `host-power-schedule-at`, `host-power-schedule-cancel`, `host-power-schedule-daily`, `host-power-schedule-enabled`, `host-power-schedule-modal`, `host-power-schedule-next`, `cell-ctx-native`, `cell-ctx-yarn-hint`, `cell-yarn-chip`, `cell-config-tab`, `host-power-schedule-save`
**machine** — `machine-glance`, `machine-missing`, `machine-missing-back`, `machine-open`
**provider** (the cloud providers on the main board, provider-glances.js) — `provider-add`, `provider-edit`, `provider-glance`, `provider-group`, `provider-group-add`, `provider-group-empty`, `provider-group-remove`, `provider-none`, `provider-resets`, `provider-state`
**scout** — `scout-add-address`, `scout-add-connect`, `scout-add-find`, `scout-add-open`, `scout-add-port`, `scout-add-status`, `scout-find`, `scout-find-connect`, `scout-find-list`, `scout-find-networks`, `scout-find-row`, `scout-find-run`
**server** — `server-step-down`, `server-step-up`
**setup** — `setup-form`, `setup-password`, `setup-password-repeat`, `setup-submit`, `setup-username`
**system** — `system-controller-info`, `system-diag-checks`, `system-diag-service-repair`, `system-driver-auto-check`, `system-driver-auto-install`, `system-driver-check`, `system-driver-log`, `system-driver-summary`, `system-driver-update`, `system-gc-close`, `system-gc-delete`, `system-gc-list`, `system-gc-modal`, `system-gc-open`, `system-gc-select-all`, `system-gc-selected`, `system-gc-summary`, `system-hero-stats`, `system-llama-build-update`, `system-llama-builds`, `system-llama-summary`, `system-llama-update-log`, `system-llama-versions-check`, `system-security-info`, `system-security-logout`, `system-tab-controller`, `system-tab-diag`, `system-tab-driver`, `system-tab-llama`, `system-tab-security`, `system-settings-export`, `system-settings-file`, `system-settings-import`, `system-settings-info`, `system-settings-passphrase`, `system-settings-secrets`, `system-tab-settings`, `system-vllm-list`, `system-vllm-machine`

Repeated elements carry `data-t-id`: `cell-card` and the cell lifecycle buttons
use `host:port` (the `slotKey` the board already computes), `kanban-node` uses
the node id (`rule:…`) — or, for the two side panels, `inputs:block` and
`outputs:block` — `kanban-input-wait` uses the input
port's id (`skynet:proxy:<port>` — `skynet` is the controller's internal id in
the data model, not a hostname), `kanban-palette-add` mirrors its `data-cv-add`.

On the kanban, a model's queue is a lane under the model's row: `kanban-model-queue`
carries the model's output id in `data-t-id` and what the queue is doing in
`data-t-state` — `idle`, `running` or `waiting` (a request standing in line beats one
running). The lane is shut until `kanban-model-queue-toggle` is clicked; the overflow
port is on its line either way. The queue policy — overflow point, reserve, loading
wait — is one line at the head of the SERVERS panel, `kanban-queue-settings`; its three
`kanban-queue-setting` fields (`data-t-id` = the field's key) are in the DOM but hidden
until `kanban-queue-settings-toggle` is clicked, so a test types into them after that.

A SERVERS row whose cell is not serving says so: `kanban-out-state` stands at the row's end
with the state in `data-t-state` — `stopped`, `starting`, `stopping`, `failed` or `unknown`
(no record of the cell, or a phase the board does not know); a running row has none, and the
row itself carries `data-cell-state`. A machine's stopped cells that nothing leads to are
under one row, `kanban-quiet-cells` (`data-t-id` = the machine's key), folded until clicked —
their rows are not in the DOM while it is folded. `kanban-unassigned` is the head's badge of
ports that could feed this kanban and do not (a `<details>`: its list opens on a click, and a
port joins on a click on its row). `kanban-fit` is the
canvas's ⤢ Show all, and `kanban-onerror-same` is the line a 🛟 node shows when main and
backup end on one output.

On the main board each cloud provider is a block, `provider-group` (`data-t-id` = the provider's kind:
`openai-subscription`, `openrouter`, `openai`, `anthropic`, `ollama`, `custom`), its accounts rows of it,
each a `provider-glance` (`data-t-id` = the account) with `provider-state`, a subscription's
`provider-resets` (`data-t-state` `some`, `none` or `unknown`; a button only while one can be spent) and
`provider-edit` (⚙). `provider-group-add` adds an account to the block — a subscription opens its
sign-in code at once — and `provider-group-remove` stands only on an empty block, `provider-group-empty`
saying it is empty. `provider-add` opens the picker (`cloud-picker`), where a provider already on the
board is a `cloud-pick` tile that is `disabled`; pressing another puts it on the board as an empty block.

On the kanban's MODELS column an account's card (`pb-account`, `data-t-id` = the account) holds
only the models added to it, each a `pb-model` (`data-t-id` = `acc:<account>/<model>`); none
added — `pb-models-none`. `pb-add-model` opens `pb-picker` in its place: type into
`pb-pick-query`, then press a `pb-pick-model` (`data-t-id` = the model) or `pb-pick-typed` (the
typed id, offered when the search finds nothing); `pb-pick-note` says what the list holds when
it shows nothing (being read, unread, no chat model, all added, no match) and `pb-pick-close`
closes it. `pb-model-remove` stands only on a model no pool's row names; it shows on hover, so
a test presses it by its hook, not by a pointer over it. Enter in `pb-pick-query` adds the first
model found and Escape closes.

On `/models` the places carry the store's id — `models-store`,
`models-place-card` and `models-place-open` use `local` or the library's
`lib-…` id — and the chosen place is the one with `aria-current="true"`;
`models-summary` says which place it summarises in its own `data-t-id` (`all`
or a store id). `models-filter` uses `moving`, `unused`, `used` or `newer`, and
the filter that is on has `aria-pressed="true"`; a filter that would keep
nothing is `disabled`. Two hooks exist only after a step: `models-store-add-row`
(its path box and buttons) after `models-store-add-open` is clicked, and the
selection bar `models-selection` is `hidden` while nothing is picked.

On the board, every engine next to a machine's cells that its chips offer
(Ollama, LM Studio — scout 2.12+) has a strip between the list's title and the
chips, always: `node-engine` with `data-t-id` `<node>:<kind>:<port>` and
`data-t-state` for how it answered — `ok`, `stopped`, `auth` (it wants a token)
or `unreachable` (its port is silent). An engine the machine does not report,
offered because a cell of the machine runs in it, is a line
`node-engine-missing` (`<node>:<kind>`) instead of the strip. The strip's
switch starts or stops the engine's server (scout 2.16+): `node-engine-start` /
`node-engine-stop`, `data-t-id` `<node>:<kind>:<port>`, beside
`node-engine-server-busy` while it runs; a switch the scout offers no act for is
`disabled`. Nothing is downloaded into an engine from the board (2026-09-27):
there is no `node-engine-pull` and no `node-engine-downloading` any more.
`node-engine-vram` says what the engine holds on the machine's cards (empty
when nothing).

What a machine's next boot does to its NVIDIA card is said at the head of its
Compute column, `node-driver-warning` (`data-t-id` `<node>:<kind>`:
`nextBootNoDriver` — a new kernel will boot without a driver Secure Boot
accepts; `rebootForDriver` — the driver installed is not the one loaded). One
line each, `role="status"`; none when there is nothing to say.

The caravan's own strip comes first over the chips, `node-caravan` (`data-t-id`
`<node>:caravan`); its second line holds `node-caravan-models` and `node-caravan-hf`
(links to the models page and the Hugging Face page, `data-t-id` the node — the bar
that stood over the machines, `board-models-bar` with `board-models-open` and
`board-hf-open`, is gone). Under it, `node-caravan-add` (`data-t-id` the node) is
«＋ Add model»: it opens the cell editor on the next free port with the model
list open (`data-caravan-add` the node; absent, and the button disabled, while a
reserve on the machine is under way) and makes nothing until Apply.

Right under an engine's strip, over the chips and whichever of them is pressed,
the models it holds that no cell serves stand on a shelf, `engine-shelf`
(`<node>:<kind>`), one line each, `engine-model` with
`data-t-id` `<node>:<kind>:<model>`. A line's `engine-model-reserve` ("+", the
same id) reserves a cell with that model on the next free port, with no dialog;
when the pressed chip would hide the new cell, the engine's chip is pressed
instead (`node-cell-filter` `<node>:<kind>`, `aria-pressed="true"`). "+" is
`disabled` while a cell is being reserved on the machine or an act runs on
the model. A model held outside any cell has `node-engine-unload`; an Ollama
model that is not loaded has `node-engine-delete`, asked through a danger dialog;
both with the line's id, replaced by `node-engine-busy` while the act runs. A
model the engine types other than a chat model has its job, `node-engine-job`,
`data-t-id` the job (`embed`). No model is loaded from the board: a cell in its
engine loads it when it starts. A model made a router output before that keeps
its switch `node-engine-expose` on the strip (`data-t-id` the output's id
`eng:<hash>`, `aria-pressed="true"`) to turn it off.

## Hooks that carry a value but are never visible

Some controls are a hidden native `<input>`/`<select>` under a custom widget, or
a container the current runner does not use. Their hook still reports the value
— `inputValue()` works on a hidden select — but **a visibility assertion on them
can never pass**, and that is not a defect to chase.

| hook | what it is | how to use it |
|---|---|---|
| `cell-remote-model` | native `<select>` under the model picker | read the value |
| `cell-remote-model-picker` | the visible widget above it | click this |
| `cell-remote-runner` | hidden input holding the chosen runner | read the value |
| `cell-remote-runner-tab` (+`data-t-id`) | the visible tabs | click these |
| `cell-remote-whisper-model`, `cell-remote-moonshine-model` | hidden carriers — the size / language is chosen in the SHARED model picker | read the value |
| `board-gpus-lane` | a GPU mini-summary `nodes.css` hides on purpose — redundant with the node card's own GPU rows | read the values; it has no landmark role for the same reason |

## Landmark regions

The panels and lanes carry `role="region"` with a name, so they can be reached
as `getByRole('region', { name })` and a keyboard user can jump between them:

| page | region name | source of the name |
|---|---|---|
| `/` | Pools, Machines, Clients | the section's own `<h2>` |
| `/system` | Controller, llama.cpp, Archived builds, vLLM runner, Security, Diagnostics | the panel's own `<h2>`/`<h3>` |
| `/models` | Model files; the side column's `navigation` landmarks Model stores and List filters | their own string (no heading exists) |
| `/kanban` | Routing graph | its own string |

Eight of the eleven are named by `aria-labelledby` pointing at the heading a
sighted user already reads, so the name follows the interface language — under
`?lang=ru` the region is `Пулы`, not `Pools`. Locate by
role+name only when the language is pinned; otherwise the `data-t` hook is
still the stable address.

**`/system` regions live on tabs.** Only the active tab's panel is in the
accessibility tree — `getByRole('region', { name: 'Security' })` is 0 until
that tab is selected, and 1 after. That is correct behaviour, not a defect.

**Board cards may be folded — but not for automation.** The board folds quiet
cells and agents into one line each (`cell-row`, `agent-row`); the full card
stays in the DOM behind the line, so its hooks (`cell-start`, `cell-configure`,
`route-model`…) exist but are not visible. An agent's card floats open on
hover; a cell's opens as a window on a click on its line (`cell-window`, with
the same `data-t-id` as the line), closed by `cell-window-close`, a click on
the dimmed board or Escape.
A browser driven by automation (`navigator.webdriver`) sees every card in full
by default, so a suite written against full cards keeps working unchanged. To
test the folded view, click `board-density` (`data-t-id` = `cells` or
`clients`) — the choice sticks in that browser's `localStorage`. A folded agent
is pinned open with `fold-pin` and folded back with `fold-unpin` (a cell has
no pin: its window replaced it). A cell's line carries a switch — the card's
▶ and ⏹ in one: `cell-row-start` while it is parked, `cell-row-stop` while it
runs, disabled (and hook-less) when it can do neither. A machine's eye over its
list of cells is `node-hide-idle` (`data-t-id` = the machine's id; the choice
sticks in `localStorage`): pressed, its cells that are not running are replaced
by a hidden mark (`data-cell-hidden`, `data-cell-hidden-by="idle"`) and their
cables are put away with them. A machine that has an engine a cell can run in
also offers chips over its cells, `node-cell-filter` (`data-t-id` =
`<machine>:all`, `:caravan`, `:ollama`, `:lmstudio`; `aria-pressed` on the
chosen one, the choice sticks in `localStorage`): the cells another launcher
runs are marked `data-cell-hidden-by="launcher"` —
a cell in trouble or in motion, one just reserved and one whose window is open
are never hidden. A cell whose model runs inside an engine (Ollama, LM Studio)
names its model in `cell-engine-model` (`data-t-id` = `host:port`), and its
window says where its requests go in `cell-window-via` (the engine's
`127.0.0.1:<port>`). A card in trouble (error, crash, start in progress, an
agent with no route — that one also carries `agent-no-route`) never folds.

## Repeated elements carry their own name

`cell-card` and `cell-configure` each expose the identity their `data-t-id`
carries — `Cell controller:22001`, `Configure: controller:22001`. Before this
they were announced identically 22 and 22 times over. (`board-cell-add`, the
Reserve-cell stub, did the same until it left in 1.3.393.)

## `login-*` and `setup-*` live on different pages

Each form has its own URL, and the server redirects to whichever matches the
controller's state:

| controller | `GET /login` | `GET /setup` |
|---|---|---|
| no accounts yet | 302 → `/setup` | the first-run wizard (`setup-*`) |
| accounts exist | the sign-in form (`login-*`) | 302 → `/login` |

Navigate to either URL and you land on the right page; the URL you end up on
tells you which mode the controller is in. Neither document ever contains the
other form — not hidden, absent — so every label on both pages is unique and
`getByLabel`/`getByRole` recipes resolve to one element without scoping.

History, since this bit the tests once: the two forms originally shared
`/login` with the inactive one `display:none`, which made `getByLabel`
ambiguous (`Username` × 2, `Password` × 3). Role locators were never affected —
`display:none` excludes an element from the accessibility tree — but the
form-scope workaround in the sign-in helper dates from that arrangement. It is
now harmless rather than load-bearing.

A test that wants the wizard still needs a controller with no accounts — the
URL does not conjure the state; `/setup` on an enabled controller just
redirects. After the account the page goes straight to `/board` (since 1.3.454);
the post-submit token box (`setup-token-box`, `setup-token`, `setup-go-board`) is gone —
the fleet token is in System → Security.

**`cell-remote-fields` is not a collapsed section.** It holds the llama.cpp flags and
is hidden whenever the runner is not `llama-server`:

```js
llamaFields.style.display = nonLlama ? "none" : "";
```

So on a whisper or vLLM cell every llama field reports hidden — correctly. There
is no expander to click; switching the runner is what changes the field set, and
`cell-remote-runner-tab` is how a test drives that.

## `node-poweroff` is the one control that cannot be undone

`node-reboot` and `node-poweroff` sit next to each other in every node header,
both carrying `data-t-id` with the host id. They are not equivalent and should
not be treated as a pair in a test.

Reboot asks a yes/no dialog. **Power off asks the operator to TYPE the host's
name**, because nothing on this board can switch a machine back on — a wrong
click there ends with someone walking to the rack. An inexact answer cancels; it
does not error.

Assert both are present. Press neither. `node-poweroff` belongs with
`cell-remote-apply`, `system-gc-delete` and `hf-token-clear` — named so a test can see
them, not so it can use them.

## `/hf` keeps its own words

It has the shared header, but not the shared dictionary: the page is six modules
(`static/js/hf-*.js`) that import only `utils.js` and `onboarding.js`, and its
words are the twenty-language table in `hf-text.js`. Expect a smaller
vocabulary, not a missing one.

Two columns and a dock, each a container that never changes: `hf-repo` holds
the repository, `hf-dock` the selection plan and the downloads, `hf-frontier`
the frontier panel. Clicks are delegated to them, so a hook inside is found
fresh after every redraw — never keep an element handle across one.

Repeated elements carry the identity the page already works in:

| hook | `data-t-id` |
|---|---|
| `hf-result`, `hf-star`, `hf-in-library` | the repository id, e.g. `unsloth/gemma-4-31B-it-GGUF` |
| `hf-tab` | `results`, `favorites` |
| `hf-size-filter` | `all`, `0-9`, `10-19`, `20-29`, `30-39`, `40-74`, `75+` |
| `hf-capability-filter` | the type as the API names it (`it`, `vision`, `audio`, `mmproj`, `mtp`, `uncensored`) |
| `hf-quant` | the quant, e.g. `Q4_K_M` — one row for all parts of a split quant |
| `hf-low-toggle` | the bit depth of the folded group, e.g. `2` |
| `hf-file`, `hf-file-check` | the file path in the repository (a quant row's check names its first part) |
| `hf-file-delete` | the file name on disk (a quant row's deletes all its parts) |
| `hf-tree-repo` | the repository id the model tree points to |
| `hf-selection-remove` | the file path in the repository |
| `hf-download-job`, `hf-download-cancel` | the job id from the server, falling back to the local uid before one is assigned |
| `hf-download-interrupted`, `hf-download-resume` | the name of the partial file |
| `hf-checkpoint-verified` | the folder of the copy, e.g. `Cosmos-Reason2-2B/nvidia/BF16` |

What we have of a repository is marked twice on its list row, and the two are
told apart: ✓ N counts files on this controller's disk (no hook of its own),
`hf-in-library` (📚 N) files a library holds. On a file row the ON DISK cell
carries this disk's mark and `hf-file-in-library` for a library's copy. Only
this disk's files have `hf-file-delete` and count for `hf-verify`: a GGUF file,
or a checkpoint folder (a repository with only safetensors weights has the
button too). The answer for a checkpoint is one `hf-checkpoint-verified` line
per copy under its `hf-checkpoint` row — counts, not a row per file.

The size buckets are the values the page filters on, not their labels — `0-9`
rather than `≤9B`, so a translated label cannot move them.

**Every destructive or writing control asks first** in the page's own dialog,
`hf-confirm`: deleting files (`hf-file-delete`), clearing the token
(`hf-token-clear`), writing over files already on disk, downloading more than
the disk holds, and a safetensors checkpoint (`hf-checkpoint-download`).
`hf-confirm-cancel` always answers no and changes nothing, so a test may open
the question and cancel it. `hf-download-start`, `hf-download-cancel` and
`hf-download-resume` act without a question when there is nothing to warn
about — assert them present, do not press them.

## `kanban-cable` endpoints are ports, not always nodes

One `kanban-cable` per connection, `data-t-id` = `from->to`. On the live graph
that is 18 connections where counting `path` inside `kanban-cables` returns 54 —
each edge draws an invisible hit-path, the visible cable and the ✕ puck's two
strokes, so the raw count was never a number about the graph.

The two ends are not all `kanban-node` ids, and a test that assumes they are will
find nothing:

```
rule:nmrrahh3wbv1->rule:nmq6jdg3n31d      both ends are node ids
in:ctrl-host:proxy:8101->rule:nmrrahh3wbv1  left end is a PORT inside inputs:block
rule:nmq6jdg3n31d->out:cb:gpt-5-6-luna    the right end is a PORT inside outputs:block
```

Rules are nodes and appear as themselves. The inputs and outputs are each one
side panel (`inputs:block`, `outputs:block` — `<aside>` elements beside the
canvas, no longer nodes on it) holding many ports, and an edge attaches to a
**port** — which is the useful thing, since "some input reaches this rule" is
weaker than "port 8101 reaches it". To assert a path end to end, match the
prefix (`in:` / `out:`) rather than expecting a node id. A port of a panel is a
dot on the panel's border, and a row scrolled out of the panel's view keeps its
dot at the panel's edge (class `clamped`) with its cables.

Note the host segment in those port ids: it carries the controller's display
name, not its host id. See below.

## A cell has three lifecycle states, not two

A card offers `cell-start` **or** `cell-stop` — never both, and sometimes
neither. The third state is `reserved`: the port is held, nothing is configured
to run on it, so there is nothing to start. Such a card offers only
`cell-configure` and `cell-delete`.

```
running   → cell-stop
stopped   → cell-start
reserved  → neither; configure it first
```

A caravan cell begins at `node-caravan-add` («＋ Add model», one per machine,
`data-t-id` = host id): the editor opens on the next free port, named in the
button's `title`, and Apply makes a configured cell — there is no reserved step
in between any more (the Reserve-cell stub, `board-cell-add`, left in 1.3.393,
the operator's call). A cell can still be reserved: an engine shelf's
`engine-model-reserve` holds a port for a model in an engine. So "a card offers
exactly one of start/stop" is the wrong assertion — it is right for the two
states a configured cell can be in, and reserved is neither of them.

## Host id and display name are different strings

Cards are addressed by **host id**: `controller:8005`, `<client-id>:8004`. The
board shows the **display name**, which is set per host and is usually not the
id — the controller and each client both render under a name of their own. Same
machine, two strings, and the models path shown on `/models` uses the display
name too.

They are joinable: a node carries `data-node-id` with the host id and its
header shows the name; `board-client-caption` and `board-agent-card` carry
`data-t-id` with the client id. Without that the lanes look unrelated to the
cards they own — a lane showing a display name beside cards prefixed with an id
reads as a lane with nothing in it.

A machine and a client are two records (since 2026-09-24). A machine with
caravan-scout is a node in `board-nodes-lane` — the controller is a node too,
without a scout. A client is the operator's record in `board-clients-lane`: a
caption and its agent cards, never a node, and nothing about hardware. One
computer can be both, under the same id. A fleet of the controller and two scout
machines, one of which also holds a client with two agents, renders three nodes,
one `board-client-caption` and two `board-agent-card`. A client with exactly one
agent has no caption: that agent's card carries the client's ＋. No hook deletes a whole client:
`agent-remove` removes one card, and the client goes with its last agent.

## A scout is added and let go on the board

`board-scout-add` sits under the Machines head — static markup next to the
lane, not in it, so a repaint does not wipe a typed address. It is closed
(`hidden`) until `scout-add-open` (＋ Add scout) or `scout-add-find` (🔍 Find,
which opens the scan too) in that head opens it; both say `aria-expanded`. Its
`data-t-state` reads `idle`, `working`, `ok` or `error`; `scout-add-status`
holds the words. Type into `scout-add-address` (the port in
`scout-add-port` is 8092 unless changed) and press `scout-add-connect`
(`POST /api/topology/scout/connect`): on `ok` the machine's node appears with
the next board refresh. Connecting a scout that is already here is the
connection test.

`node-disconnect` is a host node's one ✕ (never on the controller's node), in the machine's own
window — the main board's `machine-glance` has none since 2026-10-12. There the whole glance
opens the window, and `machine-open` is its name, a link to `/machine?host=<id>`:
`POST /api/topology/scout/disconnect` asks the scout to forget the controller
(`/api/unpair`) and forgets the machine; a silent scout's machine is only
forgotten, and returns with its scout's next heartbeat if it still holds the
controller's address. Neither touches a client or a cell.

`node-scout-silent` appears on a host's node only while its scout does not
answer, with the age of the last report. Assert it is absent on every live
node. Press `node-disconnect` only on a test machine added for the purpose.

## Not in scope

- `<canvas>` charts (`charts.js`, `topology-activity.js`). Canvas content is
  unreachable to a DOM test by construction; that the element rendered is all
  there is to assert, and that is enough.
- Markup restructuring. This contract adds attributes; it does not move
  anything.
