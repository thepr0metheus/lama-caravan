# Testability contract

An E2E suite drives this UI from outside, through a browser, as a user does.
That only works if a few things about the page are promises rather than
accidents. This document is the list of promises.

The previous suite, `lama-caravan-playwright`, was removed on 2026-10-07. New
tests will be written from scratch against this same contract.

## The page is called Routing; its names are still `routing`

Since 1.3.575 the UI calls the page that joins the clients, their sets, the pools and the models **Routing** (it was
"Routing board": the owner, 2026-10-18, wanted a name for what it does). Only what a person reads changed: the
`<title>`, the `<h1>`, the strings in every language and the prose docs. The address is still `/routing`, the page's
`data-t-page` is still `routing`, and every `data-t` name below that starts with `routing-` keeps it: a test finds the
page by those, never by its words, and renaming a name is a breaking change (below).

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
<div    data-t="routing-node" data-t-id="node-42">…</div>
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

Left to right, on every page:

```
[← main board] [brand] [version] · [page title h1] · [page actions] [account] [brook] [tour] [language]
```

It is ONE template (`scripts/gen_header.py`, class `AppHeader`), written into each page between two
marker comments, and `scripts/check_header.py` fails CI when a page's bar is not what the template
renders: a page is never edited by hand there. What a page may do differently is one table in that
file, and nothing else differs: its title; the product's long name under the brand (the board only);
the Tour button (none on `/models` and `/system`, which have no tour); the account menu's «Security»
entry (the board and Routing, whose script wires it); and what the page adds before the account
(a link on `/models`; the disk badge and a link on `/hf`).

The way back is `data-t="header-back"` (1.3.552; Routing's own `routing-back-link` is gone), in the
bar of EVERY page. `index.html` is two pages — `/board` and `/machine?host=…`, told apart by
`data-board-view` on `<html>` (`board-view.js`) — and the link is hidden on the main board alone, by one
rule of `base.css`: the board is where back goes. A machine's window shows it. Until 1.3.552 that window
had no way back to the board, because the bar was a copy written by hand into five pages.

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

It was not so until 1.3.180: `/hf` and `/routing` had bespoke headers with no
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
`Models on disk`, `System & settings`, `Routing`, `HuggingFace Browser`.
The product name in the banner is **not** a heading; it is a plain container
with the same class, so nothing moved visually.

It was the other way round until 1.3.179: the banner's `LAMA CARAVAN` was the
`<h1>` on every page, so navigating by heading told you the product's name
wherever you were. `/models` and `/system` had a *second* `<h1>` in their hero
(now `<h2>`, since the topbar names the page), and `/routing` and `/hf` had none
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
| `routing` | `/routing` |
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
`/board`, `/router` → `/routing`). Assert on either; they cannot disagree.

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

The cause is the same words the page shows in its red banner (`boot-error`, with a Reload button), put there by the
inline guard at the top of every page's body — the one script that cannot fail to arrive. It names a file that did not
load (`assets did not load: /js/main.js`), the first words of a script that threw or of a module that could not be
linked (`scripts did not initialise: …`, with `(+N more)` when there were more), and where the boot stood
(`(the boot was waiting for: /api/state)`; `(no step reported)` when it had said nothing). A module that cannot be linked
fails the page at once; any other trouble waits for the guard's 20 s. A page that was slow and not dead says `ready` when it
is done, and the banner goes (`data-t-state` turns `ready` again — a waiter that gave up at `error` can look once more).

Where it is set:

| page | ready when | file |
|---|---|---|
| `/board` | the topology rendered for the first time | `static/js/topology-render.js` |
| `/routing` | topology fetched and the router rendered | `static/js/main.js` |
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

`info.version` is the commit `/healthz` names (the controller's version when none is known); the release number is `info.x-release`.

Level 1: every path and method with `summary` (and `description`), the query
parameters and top-level body fields the handler's code reads, the content
types it answers with, and who may call it — `security` plus `x-caravan-roles`
(`["admin", "viewer"]` or `["admin"]`). Types and answer shapes are not
described yet, and the document says so rather than drawing empty ones. Where
a handler passes its query or body on whole, `x-caravan-query-complete` /
`x-caravan-fields-complete` is `false`: it may read more than is listed.
The document is a file, `rust/crates/admin/src/routes/openapi.json`, held to the
route tables by a test.

## `/api/packages`

What the running controller is made of, named as osv.dev names it — open, like
`/healthz`, for the vulnerability check of the home network. `version` is the
commit `/healthz` names. The crates go by what the release's build wrote; in the image the
system's packages go by their Debian SOURCE package; a system the controller cannot read says
`"listed": false`, one it cannot tell is `"os": null`.

```
GET /api/packages
200 {"version": "78adf78b", "runtime": {"name": "rust", "version": "2.0.0"},
     "os": {"name": "debian", "version": "12", "listed": true},
     "packages": [{"ecosystem": "crates.io", "name": "rustls", "version": "0.23.46"},
                  {"ecosystem": "Debian:12", "name": "glibc", "version": "…"}, …]}
```

## Read-only account

Roles are `admin` and `viewer`. `viewer` is enforced **server-side**, in the auth
guard: every `GET` passes, everything else answers `403`, logout excepted. It is
not a UI convention that a crafted request can step around.

```sh
# as an admin; the Security panel of /system does the same
curl -b <session cookie> -d '{"action": "create", "username": "<name>", "password": "<password>", "role": "viewer"}' \
     http://<controller>/api/auth/users
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

Generated from the source, not from memory — 881 values. Regenerate with
`python3 scripts/testability_names.py`; `--check` fails when this list and the
source disagree. A hundred and twenty-five of them are composed at runtime (`…-picker`,
`…-runner-tab`, `cell-source-stale`, `pb-reader`) and a plain grep will not find them —
that is why there is a script and not a one-liner.

**agent** — `agent-no-route`, `agent-remove`, `agent-rename`, `agent-row`
**app** — `app-toast`
**board** — `board-agent-card`, `board-client-caption`, `board-clients-lane`, `board-consumer-card`, `board-density`, `board-gpus-lane`, `board-incidents-list`, `board-incidents-open`, `board-routing-card`, `board-routing-counts`, `board-llama-suspect-banner`, `board-llama-suspect-row`, `board-machine-cards`, `board-nodes-lane`, `board-processes-list`, `board-provider-cards`, `board-router-lane`, `board-scout-add`, `board-system-open`
**boot** (the inline guard's banner, shown when the page did not boot, and taken away when it did after all) — `boot-error`
**cell** — `cell-broken-error`, `cell-card`, `cell-chat`, `cell-chat-clear`, `cell-chat-draft`, `cell-chat-send`, `cell-chat-turn`, `cell-config-search`, `cell-config-search-hit`, `cell-config-search-results`, `cell-configure`, `cell-crashed`, `cell-delete`, `cell-engine-model`, `cell-gpu`, `cell-job-asr`, `cell-job-embed`, `cell-job-llm`, `cell-job-robot-policy`, `cell-job-speech-translate`, `cell-job-translate`, `cell-job-tts`, `cell-job-voice-chat`, `cell-live`, `cell-log`, `cell-log-lines`, `cell-log-refresh`, `cell-log-run`, `cell-log-show`, `cell-model-disk-newer`, `cell-model-in-library`, `cell-model-note`, `cell-model-note-full`, `cell-model-stale`, `cell-page`, `cell-ram`, `cell-remote-apply`, `cell-remote-cache`, `cell-remote-cache-folder`, `cell-remote-cancel`, `cell-remote-card`, `cell-remote-command`, `cell-remote-command-preview`, `cell-remote-compute`, `cell-remote-cpu-offload-gb`, `cell-remote-draft`, `cell-remote-env`, `cell-remote-fields`, `cell-remote-gr00t-backbone`, `cell-remote-gr00t-embodiment`, `cell-remote-gr00t-fields`, `cell-remote-gr00t-steps`, `cell-remote-health-path`, `cell-remote-kv-cache-dtype`, `cell-remote-max-model-len`, `cell-remote-max-num-seqs`, `cell-remote-mmproj`, `cell-remote-modal`, `cell-remote-model`, `cell-remote-model-name`, `cell-remote-model-picker`, `cell-remote-moonshine-model`, `cell-remote-moonshine-model-picker`, `cell-remote-page-fields`, `cell-remote-page-url`, `cell-remote-placement`, `cell-remote-placement-all`, `cell-remote-placement-card`, `cell-remote-placement-fit`, `cell-remote-placement-held`, `cell-remote-placement-kv`, `cell-remote-placement-limit`, `cell-remote-placement-none`, `cell-remote-placement-ram`, `cell-remote-placement-threads`, `cell-remote-placement-verdict`, `cell-remote-reasoning-parser`, `cell-remote-runner`, `cell-remote-runner-tab`, `cell-remote-seamless-lang`, `cell-remote-split`, `cell-remote-split-about`, `cell-remote-split-compare`, `cell-remote-strata-context`, `cell-remote-strata-draft`, `cell-remote-strata-ds-files`, `cell-remote-strata-engram`, `cell-remote-strata-fields`, `cell-remote-strata-kv`, `cell-remote-strata-meta`, `cell-remote-strata-qwen-only`, `cell-remote-strata-reserve`, `cell-remote-strata-vocab`, `cell-remote-translate-model`, `cell-remote-translate-src`, `cell-remote-translate-tgt`, `cell-remote-trust-remote-code`, `cell-remote-tts-engine`, `cell-remote-vllm-model`, `cell-remote-vllm-model-picker`, `cell-remote-voice-clone-fields`, `cell-remote-whisper-model`, `cell-remote-whisper-model-picker`, `cell-remote-workdir`, `cell-row`, `cell-row-ctx`, `cell-row-failed`, `cell-row-start`, `cell-row-stop`, `cell-row-strip`, `cell-settings`, `cell-settings-field`, `cell-settings-group`, `cell-settings-only`, `cell-settings-open`, `cell-settings-query`, `cell-settings-star`, `cell-source-stale`, `cell-start`, `cell-stop`, `cell-talk`, `cell-window`, `cell-window-action`, `cell-window-apply`, `cell-window-band`, `cell-window-button`, `cell-window-close`, `cell-window-copy`, `cell-window-dirty`, `cell-window-discard`, `cell-window-item`, `cell-window-menu`, `cell-window-more`, `cell-window-panel`, `cell-window-place`, `cell-window-tab`, `cell-window-tile`, `cell-window-via`

**talk** (the voice window over a running cell, voice-talk.js: the window carries the cell as its id and its state ready, recording or waiting; each turn its index and user, assistant or failed; the cell's own list of voices its state asking, failed or none; the sample of a voice its state none, recording or recorded, and the line under it used or consent) — `talk-clear`, `talk-close`, `talk-consent`, `talk-keep`, `talk-keep-name`, `talk-memory`, `talk-mode`, `talk-notice`, `talk-record`, `talk-sample`, `talk-sample-forget`, `talk-sample-record`, `talk-sample-text`, `talk-sample-use`, `talk-say`, `talk-system`, `talk-text`, `talk-timing`, `talk-turn`, `talk-turns`, `talk-voice`, `talk-voices`, `talk-window`

**live** (the live window over a running cell, voice-live.js: the window carries the cell as its id and its state — idle, checking, connecting, loading, live, muted, ready, recording, waiting, ended or failed; each line of the talk its index) — `live-close`, `live-hangup`, `live-line`, `live-lines`, `live-mode`, `live-mute`, `live-speak`, `live-start`, `live-status`, `live-window`

**client** — `client-add`, `client-add-kind`

**consumer** — `consumer-activity`, `consumer-block`, `consumer-block-count`, `consumer-builtin`, `consumer-connect`, `consumer-connect-copy`, `consumer-delete`, `consumer-divider`, `consumer-give-key`, `consumer-howto`, `consumer-key`, `consumer-live`, `consumer-new-key`, `consumer-oc-config`, `consumer-others-none`, `consumer-rename`

**fold** — `fold-pin`, `fold-unpin`

**cloud** — `cloud-account-plan`, `cloud-account-pools`, `cloud-account-status`, `cloud-account-window`, `cloud-connected`, `cloud-deepseek-balance`, `cloud-device-code`, `cloud-device-login`, `cloud-device-open`, `cloud-done`, `cloud-new-code`, `cloud-pick`, `cloud-provider-note`, `cloud-picker`, `cloud-provider-word`, `cloud-sign-in`, `cloud-sign-in-ended`, `cloud-sign-in-wait`

**pool** — `pool-add-step`, `pool-card`, `pool-delete`, `pool-empty`, `pool-levels-legend`, `pool-loose`, `pool-loose-account`, `pool-name`, `pool-new-first`, `pool-none`, `pool-settings`, `pool-step`, `pool-step-account`, `pool-step-cancel`, `pool-step-check`, `pool-step-connect`, `pool-step-custom`, `pool-step-list-state`, `pool-step-model`, `pool-step-name`, `pool-step-query`, `pool-step-remove`, `pool-step-submit`, `pool-step-window`, `pool-stop`, `pool-switch`

**route** — `route-caller`, `route-context`, `route-context-line`, `route-context-model`, `route-context-prefer`, `route-detail-delete`, `route-detail-tab`, `route-latency`, `route-latency-row`, `route-model`, `route-model-card-link`, `route-model-lock`, `route-state`, `route-wait`

**sub-usage** — `sub-usage-banner`, `sub-usage-loading`
**sub-meter** (the account card's limits drawn small in Routing, usage-stats.js) — `sub-meter`, `sub-meter-stop`, `sub-meters`
**confirm** — `confirm-accept`, `confirm-cancel`, `confirm-check`, `confirm-check-all`, `confirm-choice`, `confirm-field`, `confirm-input`, `confirm-meta`, `confirm-overlay`, `confirm-path`, `confirm-text`, `confirm-title`
**header** — `header`, `header-app-title`, `header-back`, `header-hf`, `header-lang-current`, `header-lang-menu`, `header-lang-open`, `header-machine`, `header-machines`, `header-machines-menu`, `header-machines-note`, `header-machines-open`, `header-models`, `header-page-subtitle`, `header-page-title`, `header-pages`, `header-routing`, `header-user-chip`, `header-user-logout`, `header-user-menu`, `header-user-menu-open`, `header-user-name`, `header-user-security`, `header-version-branch`
**hf** — `hf-bench-panel`, `hf-bench-refresh`, `hf-bench-toggle`, `hf-capability-filter`, `hf-checkpoint`, `hf-checkpoint-download`, `hf-checkpoint-verified`, `hf-confirm`, `hf-confirm-cancel`, `hf-confirm-ok`, `hf-dock`, `hf-download-cancel`, `hf-download-discard`, `hf-download-dismiss`, `hf-download-interrupted`, `hf-download-job`, `hf-download-open-page`, `hf-download-resume`, `hf-download-start`, `hf-downloads`, `hf-downloads-toggle`, `hf-file`, `hf-file-check`, `hf-file-delete`, `hf-file-in-library`, `hf-frontier`, `hf-frontier-open`, `hf-frontier-refresh`, `hf-in-library`, `hf-limit`, `hf-load-progress`, `hf-low-toggle`, `hf-mask`, `hf-other-toggle`, `hf-quant`, `hf-repo`, `hf-repo-star`, `hf-result`, `hf-search-input`, `hf-search-submit`, `hf-selection-clear`, `hf-selection-plan`, `hf-selection-remove`, `hf-selection-toggle`, `hf-size-filter`, `hf-sort`, `hf-sort-dir`, `hf-star`, `hf-tab`, `hf-token-clear`, `hf-token-edit`, `hf-token-input`, `hf-token-menu`, `hf-token-save`, `hf-tree-repo`, `hf-tree-toggle`, `hf-verify`
**Routing** — `routing-cable`, `routing-cables`, `routing-canvas`, `routing-consumer-key`, `routing-entry`, `routing-entry-copy`, `routing-entry-off`, `routing-entry-port`, `routing-entry-setup`, `routing-entry-why`, `routing-fit`, `routing-input-wait`, `routing-model-queue`, `routing-model-queue-toggle`, `routing-node`, `routing-onerror-same`, `routing-out-state`, `routing-palette-add`, `routing-queue-setting`, `routing-queue-settings`, `routing-queue-settings-toggle`, `routing-quiet-cells`, `routing-save-status`, `routing-unassigned`, `routing-unclaimed`
**pb** (Routing's pools board, pool-board.js) — `pb-account`, `pb-account-issues`, `pb-account-state`, `pb-add-model`, `pb-add-pool`, `pb-add-row`, `pb-arrange`, `pb-cables`, `pb-choice`, `pb-choose-close`, `pb-choose-note`, `pb-choose-query`, `pb-chooser`, `pb-client`, `pb-client-ask`, `pb-client-builtin`, `pb-client-copy`, `pb-client-count`, `pb-client-deny`, `pb-client-links`, `pb-client-miss`, `pb-client-misses`, `pb-client-misses-badge`, `pb-client-name`, `pb-client-name-open`, `pb-client-name-panel`, `pb-client-probe`, `pb-client-probe-model`, `pb-client-tests`, `pb-clients`, `pb-deny`, `pb-deny-by-source`, `pb-deny-chip`, `pb-deny-close`, `pb-deny-done`, `pb-deny-group`, `pb-deny-item`, `pb-deny-more`, `pb-deny-none`, `pb-deny-open`, `pb-deny-query`, `pb-deny-still`, `pb-deny-unread`, `pb-direct`, `pb-direct-count`, `pb-direct-row`, `pb-dock`, `pb-dock-body`, `pb-dock-cell`, `pb-dock-client`, `pb-dock-foot`, `pb-dock-id`, `pb-dock-levels`, `pb-dock-pool`, `pb-dock-step`, `pb-dock-work`, `pb-entry`, `pb-history`, `pb-history-toggle`, `pb-kind`, `pb-limits`, `pb-machine`, `pb-machine-cells`, `pb-model`, `pb-model-closed`, `pb-model-grab`, `pb-model-level`, `pb-model-remove`, `pb-model-switch`, `pb-model-unused`, `pb-model-work`, `pb-models`, `pb-models-none`, `pb-move`, `pb-move-client`, `pb-move-delete`, `pb-move-done`, `pb-move-keep`, `pb-move-sets`, `pb-move-twin`, `pb-no-clients`, `pb-no-models`, `pb-no-pools`, `pb-pick-close`, `pb-pick-model`, `pb-pick-note`, `pb-pick-query`, `pb-pick-typed`, `pb-picker`, `pb-pool`, `pb-pool-copy`, `pb-pool-delete`, `pb-pool-name`, `pb-pool-turns`, `pb-pool-window`, `pb-pool-window-auto`, `pb-pool-window-stated`, `pb-pools`, `pb-probe`, `pb-probe-close`, `pb-probe-status`, `pb-pull-model`, `pb-queue`, `pb-queue-chip`, `pb-queue-edit`, `pb-queue-field`, `pb-queue-panel`, `pb-queue-settings`, `pb-queue-side`, `pb-queue-slot`, `pb-queue-wait`, `pb-reader`, `pb-reader-block`, `pb-route`, `pb-row`, `pb-row-remove`, `pb-row-wait`, `pb-settings`, `pb-settings-panel`, `pb-turn`, `pool-board`
**pb-schedule** (when a model is open: its ⏱ in Routing and the window that sets it, model-schedule.js) — `pb-model-schedule`, `pb-schedule`, `pb-schedule-add`, `pb-schedule-cell-note`, `pb-schedule-close`, `pb-schedule-enabled`, `pb-schedule-grid`, `pb-schedule-needs-window`, `pb-schedule-no-windows`, `pb-schedule-now`, `pb-schedule-save`, `pb-schedule-window`, `pb-schedule-zone`
**login** — `login-error`, `login-form`, `login-lang`, `login-password`, `login-submit`, `login-username`
**model** — `model-file-stale`, `model-in-library`, `model-job-asr`, `model-job-embed`, `model-job-llm`, `model-job-robot-policy`, `model-job-speech-translate`, `model-job-translate`, `model-job-voice-chat`, `model-job-tts`

**models** — `model-rating`, `models-comment`, `models-comment-add`, `models-comment-cancel`, `models-comment-edit`, `models-comment-input`, `models-comment-save`, `models-delete-selected`, `models-filter`, `models-filter-clear`, `models-filter-empty`, `models-filters`, `models-folder-item`, `models-fresh-auto`, `models-fresh-check`, `models-fresh-get`, `models-fresh-keep`, `models-fresh-stamp`, `models-hf-open`, `models-job-filter`, `models-jobs`, `models-library-file`, `models-model-select`, `models-move-branch`, `models-move-dest`, `models-move-dismiss`, `models-move-menu`, `models-move-open`, `models-move-progress`, `models-move-selected`, `models-move-stayed`, `models-move-stop`, `models-move-target`, `models-moves-summary`, `models-note`, `models-note-add`, `models-note-cancel`, `models-note-chip`, `models-note-edit`, `models-note-input`, `models-note-save`, `models-notes-unknown`, `models-params`, `models-params-add`, `models-params-cancel`, `models-params-edit`, `models-params-input`, `models-params-save`, `models-path-cancel`, `models-path-edit`, `models-path-edit-row`, `models-path-input`, `models-path-save`, `models-path-value`, `models-picked-summary`, `models-place-all`, `models-place-card`, `models-place-open`, `models-rate`, `models-row-jobs`, `models-row-window`, `models-search`, `models-selection`, `models-staged-download`, `models-staged-progress`, `models-staged-revert`, `models-store`, `models-store-add`, `models-store-add-cancel`, `models-store-add-open`, `models-store-add-path`, `models-store-add-row`, `models-store-files`, `models-store-meta`, `models-store-remove`, `models-store-repath`, `models-store-repath-cancel`, `models-store-repath-input`, `models-store-repath-row`, `models-store-repath-save`, `models-store-state`, `models-store-why`, `models-store-why-command`, `models-stores`, `models-stores-error`, `models-summary`, `models-summary-bar`, `models-summary-facts`, `models-tree`, `models-tree-group`, `models-tree-group-toggle`, `models-tree-head`, `models-unused-select-all`, `models-unused-summary`, `models-window-filter`, `models-windows`
**engine** — `engine-model`, `engine-model-reserve`, `engine-shelf`
**node** — `node-cache`, `node-cache-budget`, `node-cache-clear`, `node-cache-delete`, `node-cache-dir`, `node-cache-dir-change`, `node-cache-dir-remove`, `node-cache-figures`, `node-cache-foreign`, `node-cache-keep`, `node-cache-library`, `node-cache-library-set`, `node-cache-move-error`, `node-cache-moving`, `node-cache-off`, `node-cache-on`, `node-cache-through`, `node-cache-work`, `node-cache-work-apart`, `node-cache-work-budget`, `node-cache-work-fast`, `node-cache-work-hdd`, `node-cache-work-remove`, `node-cache-work-set`, `node-cache-work-short`, `node-cache-work-wear`, `node-caravan`, `node-caravan-add`, `node-cell-filter`, `node-disconnect`, `node-disk-low`, `node-driver-warning`, `node-engine`, `node-engine-busy`, `node-engine-delete`, `node-engine-expose`, `node-engine-job`, `node-engine-missing`, `node-engine-server-busy`, `node-engine-start`, `node-engine-stop`, `node-engine-unload`, `node-engine-vram`, `node-gpu-card`, `node-gpu-cards`, `node-hide-idle`, `node-power-schedule`, `node-poweroff`, `node-reboot`, `node-scout-old`, `node-scout-silent`, `node-scout-update`, `node-strata`
**host-power-schedule** — `host-power-schedule-at`, `host-power-schedule-cancel`, `host-power-schedule-daily`, `host-power-schedule-enabled`, `host-power-schedule-modal`, `host-power-schedule-next`, `cell-ctx-native`, `cell-ctx-yarn-hint`, `cell-yarn-chip`, `cell-config-tab`, `host-power-schedule-save`
**machine** — `machine-add`, `machine-band`, `machine-build`, `machine-build-card`, `machine-build-empty`, `machine-build-none`, `machine-build-port`, `machine-build-shelf`, `machine-build-slot`, `machine-build-slots`, `machine-build-step`, `machine-build-strip`, `machine-chosen`, `machine-chosen-cells`, `machine-chosen-line`, `machine-chosen-none`, `machine-glance`, `machine-head`, `machine-incidents-count`, `machine-incidents-open`, `machine-map`, `machine-map-block`, `machine-map-grip`, `machine-map-lane`, `machine-map-legend`, `machine-map-legend-other`, `machine-map-metric`, `machine-map-total`, `machine-menu`, `machine-missing`, `machine-missing-back`, `machine-model`, `machine-model-cell`, `machine-model-choose`, `machine-model-context`, `machine-model-ctx`, `machine-model-launch`, `machine-model-new`, `machine-model-note`, `machine-model-note-add`, `machine-model-rate`, `machine-model-repo`, `machine-model-said`, `machine-model-start`, `machine-model-stated`, `machine-model-stop`, `machine-model-window`, `machine-models`, `machine-models-filter`, `machine-models-find`, `machine-models-job`, `machine-models-none`, `machine-models-outside`, `machine-open`, `machine-pick`, `machine-place`, `machine-plan-cancel`, `machine-plan-start`, `machine-side`, `machine-side-activity`, `machine-side-disk`, `machine-side-engines`, `machine-side-incidents`
**add-model** (the new-cell wizard, add-model.js) — `add-model`, `add-model-ability`, `add-model-all`, `add-model-back`, `add-model-cache`, `add-model-close`, `add-model-create`, `add-model-create-start`, `add-model-ctx`, `add-model-ctx-own`, `add-model-draft`, `add-model-empty`, `add-model-flash`, `add-model-full`, `add-model-hf`, `add-model-job`, `add-model-keep`, `add-model-keep-folder`, `add-model-mmproj`, `add-model-name`, `add-model-next`, `add-model-parallel`, `add-model-place`, `add-model-row`, `add-model-runner`, `add-model-search`, `add-model-starred`, `add-model-starred-none`, `add-model-step`, `add-model-temp`, `add-model-thinking`, `add-model-tip`, `add-model-where`
**provider** (the cloud providers on the main board, provider-glances.js) — `provider-add`, `provider-edit`, `provider-glance`, `provider-group`, `provider-group-add`, `provider-group-empty`, `provider-group-remove`, `provider-none`, `provider-resets`, `provider-state`
**credit** (a key account's credit left, on the main board's card and in the account's window, credit-left.js) — `credit-left`, `credit-since`, `credit-warn`
**scout** — `scout-add-address`, `scout-add-connect`, `scout-add-find`, `scout-add-open`, `scout-add-port`, `scout-add-status`, `scout-find`, `scout-find-connect`, `scout-find-list`, `scout-find-networks`, `scout-find-row`, `scout-find-run`, `scout-install`, `scout-install-command`, `scout-install-copy`, `scout-install-note`
**server** — `server-step-down`, `server-step-up`
**setup** — `setup-form`, `setup-password`, `setup-password-repeat`, `setup-submit`, `setup-username`
**system** — `system-controller-info`, `system-diag-checks`, `system-diag-service-repair`, `system-driver-auto-check`, `system-driver-auto-install`, `system-driver-check`, `system-driver-log`, `system-driver-summary`, `system-driver-update`, `system-gc-close`, `system-gc-delete`, `system-gc-list`, `system-gc-modal`, `system-gc-open`, `system-gc-select-all`, `system-gc-selected`, `system-gc-summary`, `system-hero-stats`, `system-llama-build-update`, `system-llama-builds`, `system-llama-summary`, `system-llama-update-log`, `system-llama-versions-check`, `system-security-info`, `system-security-logout`, `system-tab-controller`, `system-tab-diag`, `system-tab-driver`, `system-tab-llama`, `system-tab-security`, `system-settings-export`, `system-settings-file`, `system-settings-import`, `system-settings-info`, `system-settings-passphrase`, `system-settings-secrets`, `system-tab-settings`, `system-vllm-list`, `system-vllm-machine`

Repeated elements carry `data-t-id`: `cell-card` and the cell lifecycle buttons
use the cell's id (`cellId`: `c<port>` for a cell made before 2026-11-08, `c` and eight hex digits for a new one; `host:port`
until then), `routing-node` uses
the node id (`rule:…`) — or, for the two side panels, `inputs:block` and
`outputs:block` — `routing-input-wait` uses the input
port's id (`skynet:proxy:<port>` — `skynet` is the controller's internal id in
the data model, not a hostname), `routing-palette-add` mirrors its `data-cv-add`.

The placement map of a llama.cpp cell (`cell-remote-placement`, 2026-10-24) says its plan in `data-t-state`: `fitted`
(llama.cpp fits by the handles), `held` (something set stops it from fitting — the note `cell-remote-placement-held`
names it in its own `data-t-state`: `off`, `layers`, `split` or `moe`), `tensor` or `unknown`. A card's lane, handle
and buttons (`-card`, `-limit`, `-all`, `-none`) carry the card's index in `data-t-id`, the KV buttons `cards` or
`ram`, and the verdict pill `cell-remote-placement-verdict` its verdict in `data-t-state`: `fits`, `spill`, `kvRam`,
`ramShort`, `over` or `unknown`. `cell-remote-placement-threads` is the RAM lane's «Use N», drawn while the cell computes
its part in RAM with fewer threads than the machine has cores.

The speculative draft a llama.cpp cell loads (2026-11-07) is its own part of the form's estimate line, `cell-remote-draft`,
drawn only while the start loads a draft file (none for `SPEC_TYPE` none, ngram-*, an embeddings cell or no file). Its
`data-t-state` says where its weights live: `cards`, `ram` (`SPEC_DRAFT_N_GPU_LAYERS` 0), `split` (its experts in RAM by
`CPU_MOE_DRAFT`), `unknown` (its place cannot be said here, and it is counted on the cards) or `unsized` (the library has not its
file: its figure is "—", and it is in no sum).

A cell's line says the window it is set to and the most its model was trained for: `cell-row-ctx`, with `data-t-state`
`both`, `over` (set past the training — stretched), `set` or `max` (only one is known); with neither it is not drawn.

A model's comment on /models (one for all its quants, 2026-10-19) hangs on the model's own first-level row: `models-note-chip` (a 💬 on the folded row, the comment in
its tooltip) and, once the model is opened, `models-note` (the description, with `models-note-edit`) or `models-note-add` (a model with none); `models-params` and `models-comment` (the developer's recommended parameters and the owner's own comment, 1.3.688) have the same parts, and `models-rate` (`data-t-id` `<model>:like` or `:dislike`) sets its mark, which `model-rating` shows on its row, in the pickers and on /hf. The box is
`models-note-input` with `models-note-save` and `models-note-cancel`; all of them carry the model's folder in `data-t-id`, and a page that could not read the comments
draws none of them but says `models-notes-unknown` under the list. On a cell's card the comment on its model is `cell-model-note` (`data-t-id` = the cell's id) under
the cell's own note, and the cell's window shows it whole as `cell-model-note-full`.

In Routing, a model's queue is a lane under the model's row: `routing-model-queue`
carries the model's output id in `data-t-id` and what the queue is doing in
`data-t-state` — `idle`, `running` or `waiting` (a request standing in line beats one
running). The lane is shut until `routing-model-queue-toggle` is clicked; the overflow
port is on its line either way. The queue policy — overflow point, reserve, loading
wait — is one line at the head of the SERVERS panel, `routing-queue-settings`; its three
`routing-queue-setting` fields (`data-t-id` = the field's key) are in the DOM but hidden
until `routing-queue-settings-toggle` is clicked, so a test types into them after that.

A SERVERS row whose cell is not serving says so: `routing-out-state` stands at the row's end
with the state in `data-t-state` — `stopped`, `starting`, `stopping`, `failed` or `unknown`
(no record of the cell, or a phase the board does not know); a running row has none, and the
row itself carries `data-cell-state`. A machine's stopped cells that nothing leads to are
under one row, `routing-quiet-cells` (`data-t-id` = the machine's key), folded until clicked —
their rows are not in the DOM while it is folded. `routing-unassigned` is the head's badge of
ports that could feed this router and do not (a `<details>`: its list opens on a click, and a
port joins on a click on its row). `routing-fit` is the
canvas's ⤢ Show all, and `routing-onerror-same` is the line a 🛟 node shows when main and
backup end on one output.

On the main board each cloud provider is a block, `provider-group` (`data-t-id` = the provider's kind:
`openai-subscription`, `openrouter`, `openai`, `anthropic`, `ollama`, `custom`), its accounts rows of it,
each a `provider-glance` (`data-t-id` = the account) with `provider-state`, a subscription's
`provider-resets` (`data-t-state` `some`, `none` or `unknown`; a button only while one can be spent) and
`provider-edit` (⚙). `provider-group-add` adds an account to the block — a subscription opens its
sign-in code at once — and `provider-group-remove` stands only on an empty block, `provider-group-empty`
saying it is empty. `provider-add` opens the picker (`cloud-picker`), where a provider already on the
board is a `cloud-pick` tile that is `disabled`; pressing another puts it on the board as an empty block.
A key account whose operator typed a credit (⚙, "Credit left on the account") shows it under its spend line as `credit-left`
(`data-t-id` = the account; `data-t-state` `known` — a bar, "≈ $183 left of $200", with `credit-since` saying it is an estimate and
from when — or `unread` while the spend reading is not there: the figure alone, no bar), and a `credit-warn` line for each reason
the figure is too high (requests with no price; logs that do not reach back). The same line stands in the account's window.

On Routing's MODELS column an account's card (`pb-account`, `data-t-id` = the account) holds
only the models added to it, each a `pb-model` (`data-t-id` = `acc:<account>/<model>`); none
added — `pb-models-none`. The card's head says what the account says of itself: `pb-account-state`
(`data-t-state` = `connected` or `waiting` for a sign-in or a key). Its limits stand once, in `pb-limits`, as
`sub-meters`: a `sub-meter` for each window (`data-t-id` = its label, `data-t-state` = `known` or
`unknown` — a reading that gave no number draws a dash, not 0%), and a `sub-meter-stop` tick on it for
each level at which a model of the card stops. On a model's line: `pb-model-work` (what a key's model does,
1.3.631: `data-t-state` = `said`, its jobs' marks, or `unsaid`, a "?" — none for a subscription's or an
Anthropic key's model, whose type says it; in the model's strip `pb-dock-work` holds its "What it does"
select, in the same two states), `pb-model-switch` (its switch level),
`pb-model-level` (its pool has stepped aside, `data-t-state` = `reserve`, or stopped it, `stop`),
`pb-model-schedule`, `pb-model-unused`. `pb-add-model` stands in the card's head and is quiet until the
card is pointed at (a card with no model shows it at rest): it opens `pb-picker` in its place: type into
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

What a model does and how long a context it takes (1.3.637, `model-facts.js`): the side column's `models-jobs` and `models-windows` hold the buttons `models-job-filter` (data-t-id = the job: `llm`, `embed`, `asr`, `tts`, `translate`, `speech-translate`, `voice-chat`, `robot-policy`) and `models-window-filter` (data-t-id = the least window: `131072`, `262144`, `1048576`), each with `aria-pressed`; every row of the tree carries `models-row-jobs` and `models-row-window` (data-t-id = the file's path or the branch's chain), the latter with data-t-state `known`, `unknown` (a model that takes a window in tokens and states none) or `none` (no model in the row, or a job with no window in tokens).

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
`<node>:caravan`). The caravan's two model pages are in the bar of every page since
2026-10-24: `header-pages` holds `header-models` (/models), `header-hf` (/hf) and, since 1.3.684, `header-routing` (/routing) and the
list of machines, `header-machines`: `header-machines-open` opens `header-machines-menu`, read when it opens, with a `header-machine`
(`data-t-id` the machine) for each or a `header-machines-note` saying why there is none. On
its own page a link carries `aria-current="page"` (the strip's `node-caravan-models` and
`node-caravan-hf`, the board's `board-pages` with `board-models-open` and `board-hf-open`,
and /hf's `hf-on-disk` are gone). Under the strip, `node-caravan-add` (`data-t-id` the node) is
«＋ Add model»: it opens the cell editor for a new cell (its id comes with the first Apply) with the model
list open (`data-caravan-add` the node; absent, and the button disabled, while a
reserve on the machine is under way) and makes nothing until Apply.

Between the strip and «＋ Add model» stands the machine's model cache, `node-cache`
(`data-t-id` the node; scout 2.34+ — a machine whose scout reports no cache has no
such line): `node-cache-keep` is the box that says how many of the last models the
cache keeps, `1` to `5` (`data-cache-keep` the node; a change goes to the scout at
once and it deletes the older models' files) — on a scout of 2.38, `node-cache-budget`
in its place, the number box of GB (`data-cache-budget` the node; empty while none is
chosen) — `node-cache-figures` what the cache holds and what the disk has left (empty
when the scout measured neither), and on a scout of 2.38 `node-cache-dir`, the folder
the cache is in, with `node-cache-dir-change` (`data-cache-dir` the node), which asks
the new folder in the prompt window and then confirms in the confirm window. When the
cache folder holds files that the scout did not download — copied by hand, or there
before the scout kept a record; it never deletes them by itself — a second line,
`node-cache-foreign`, says how many and how big, and `node-cache-delete`
(`data-cache-delete-foreign` the node) asks, in the board's confirm window, and
deletes them only if they are still the size the window named.

`node-disk-low` (`data-t-id` the node) is the sign in a machine's head — on the main board's glance and
on the machine's own card, right after the scout-old chip — that the disk of its model cache is used
90 % or more: «⚠ disk 94% full» (scout 2.34+; none when the scout did not measure the disk). Its tip
holds the rule, not the figures; the percent is patched in place.

Right under an engine's strip, over the chips and whichever of them is pressed,
the models it holds that no cell serves stand on a shelf, `engine-shelf`
(`<node>:<kind>`), one line each, `engine-model` with
`data-t-id` `<node>:<kind>:<model>`. A line's `engine-model-reserve` ("+", the
same id) reserves a new cell with that model, with no dialog;
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
| `cell-remote-card` (+`data-t-id` = the card's number) | the one-card chips under the compute tile, on a machine with two cards or more, for a runner that runs on one card (`oneCard` in the registry) | click one: it writes `CUDA_VISIBLE_DEVICES=<n>` into the cell's ENV (the box itself stays hidden for these runners); the chip lit is the pinned card |
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
| `/routing` | Routing graph | its own string |

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
the dimmed board or Escape. The window (variant Г, 1.3.621) is a header, a band
and tabs; every hook in it carries the cell's id as `data-t-id`, and a
part that repeats adds `:<its id>`. The band `cell-window-band` says the cell's
state in `data-t-state` (`running`, `starting`, `warming`, `downloading`,
`stopping`, `deleting`, `stopped`, `reserved`, `failed`,
`broken`) and holds the one main button `cell-window-action`, whose
`data-t-state` says what it does: `start`, `stop`, `configure` (a port with no
model), `busy` (shut and spinning while the cell stops or is deleted) or `shut`
(a Start or Stop that may not be pressed now, the line's reason on hover). The tabs are
`cell-window-tab` (`:overview`, `:memory`, `:settings`, `:log`, `:talk` — the
last only for a cell that talks), `aria-selected` on the chosen one; each opens
its `cell-window-panel` (same ids), the others are `hidden`. The chosen tab
survives the board's repaint. The overview's figures are `cell-window-tile`
(`:speed`, `:context` or `:window` for a speech model, `:gpu`, `:ram`); the
buttons inside the tabs are `cell-window-button` (`:placement`, `:configure`,
`:port`, `:detail`). Under what is said of the model, the overview's
`cell-window-link` (`:models` — the models page on the model's quant folder,
`:hf` — our Hugging Face page on its repository; 1.3.660) opens in this tab, as
everything of the caravan, and only the links the model's path in the library
gives are drawn.
`cell-window-more` (⋯, `aria-expanded`) opens
`cell-window-menu` with `cell-window-item` (`:boot`, a switch with
`aria-checked`; `:copy`; `:port`; `:detail`; `:delete`), an item that cannot act
now is `disabled`. The address under the name is `cell-window-copy`: a click
copies it and says so for a moment.
Under the reported events, the Log tab of a cell with a process of its own (not
a port with no model, not a cell in an engine) shows the server's own log,
`cell-log` (1.3.623, `data-t-state` idle, loading, ok or error): it is read from
the machine when the tab opens (`cell-log-show` reads it, or again after a
refusal), `cell-log-run` picks a run — the present one or an earlier one the
scout kept — `cell-log-refresh` reads the chosen run again, and `cell-log-lines`
holds the lines. While the cell runs and its present run is shown, the poll
reads it again every five seconds.
A chat cell (its runner answers a text chat and its job is a chat — not an
embedding server; a model in Ollama or LM Studio too since 1.3.643, while its
cell runs and has said it is a chat) has a text chat in its Talk tab, `cell-chat` (1.3.624,
`data-t-state` idle, busy while an answer is awaited, off while the cell does
not run): `cell-chat-draft` is the message box (Enter sends, Shift+Enter is a
new line), `cell-chat-send` and `cell-chat-clear` its buttons, and each message
is a `cell-chat-turn` with `data-t-state` user, answer or error. The talk and
the typed draft survive the board's repaint.
A llama.cpp cell with a model that may be configured now has its settings
edited in its window (1.3.625; a port with no model picks one in the dialog). The Settings tab holds `cell-settings` (`data-t-state` idle
until the form is filled for this cell — `cell-settings-open`, or a click on the
Settings or Memory tab — then open): `cell-settings-query` searches the fields
by name and help, `cell-settings-only` keeps to the fields set (on by default),
`cell-settings-group` (`:<the dialog's tab>`, `aria-current` on the chosen one)
picks a group, and each field is a `cell-settings-field` (`:<FIELD>`,
`data-t-state` set, unset or changed). The Memory tab draws the placement map
in `cell-window-place` (`data-t-state` idle, open, or none for a cell with no
map; its open button is `cell-settings-open` with `:memory`). While a field
differs from what the form was filled with, the window's foot shows
`cell-window-dirty` (`data-t-state` dirty, or busy while saving) with
`cell-window-discard` and `cell-window-apply` — the dialog's own Apply, with its
question. Edits not applied ask before the form is filled for another cell.
A browser driven by automation (`navigator.webdriver`) sees every card in full
by default, so a suite written against full cards keeps working unchanged. To
test the folded view, click `board-density` (`data-t-id` = `cells` or
`clients`) — the choice sticks in that browser's `localStorage`. A folded agent
is pinned open with `fold-pin` and folded back with `fold-unpin` (a cell has
no pin: its window replaced it). A cell's line carries a switch — the card's
▶ and ⏹ in one: `cell-row-start` while it is parked, `cell-row-stop` while it
runs, disabled (and hook-less) when it can do neither. A cell's line and its card say the memory it holds in
two badges, `cell-ram` and `cell-gpu` (1.3.583, the owner: "how much on RAM and how much on the GPU, as separate badges, even if one is not
occupied"), each with `data-t-state`: `held` (what the cell holds now), `expected` (what it should hold when it runs, "≈"), `none` (a measured
zero, or a CPU cell's GPU), `unknown` (a running cell the scout or the cards did not tell: a dash) or `idle` (a parked cell with nothing to
expect: a dash); a port with no model has neither. A cell that failed (its start
ended in an error, or its process lives around a dead engine) is a red line, not a
big card (2026-10-17): its `cell-row` carries `data-t-state="failed"` and a
`cell-row-failed` word with the reason on hover, its switch still starts (parked) or
stops (broken), and the reason in full is the first thing its window shows. A cell that is
being started stays a line too (2026-10-18, the owner: "when I start a cell, do not widen it by itself"):
while its model is copied, loaded or warmed up, a thin strip `cell-row-strip` stands under
the line's name — the bar and the card's own status words (the copy: the file without the
model's name, the whole model's gigabytes and the share) — and the full card waits in the
window. A start just asked for (the switch locked and spinning) has no strip. A machine's eye over its
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
names its model in `cell-engine-model` (`data-t-id` = the cell's id), and its
window says where its requests go in `cell-window-via` (the engine's
`127.0.0.1:<port>`). A card in trouble (crash, start in progress, an agent with no
route — that one also carries `agent-no-route`) never folds; a cell that failed is the
red line described above. On a machine with two cards or more, each GPU metric of its
panel (`gpu`, `vram`, `power`, not the token speed) carries a line per card: `node-gpu-cards`
(`data-t-id` = `<machine>:<metric>`) holds one `node-gpu-card` per card (`data-t-id` =
`<machine>:<metric>:<card number>`, the number the board gives the card), with its own value
and sparkline in `data-node-metric-val` / `data-node-metric-spark` under the same id.

## Repeated elements carry their own name

`cell-card` and `cell-configure` each expose the identity their `data-t-id`
carries, by the cell's name or else its id — `Cell Qwen3-Embedding-0.6B`, `Configure: c3f9a02b1`. Before this
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

## A machine's page: the map and the cell chosen on it

A machine's page (variant В «Карта памяти», 1.3.632) leads with `machine-head`; in its line stand `machine-band`
(`data-t-state` = `good`, `busy`, `idle` or `bad`), `machine-menu` and `machine-add`. Under it is `machine-map`: a
`machine-map-lane` per card (`data-t-id` = `gpu-<index>`) and one for the RAM (`ram`). Each cell that holds memory is a
`machine-map-block` (`data-t-id` = its cell's id) on every lane it holds, `aria-pressed` saying whether it is the chosen one, and
beside the lanes it has one list, `machine-map-legend` (the same `data-t-id`, the same `aria-pressed`): a row for every cell the
machine has — the ones that hold memory and the ones on their way — with its name, how much it holds in all, where it lies, and
what it is doing. The last column is words, not a figure: a cell on its way has no speed to show, and a cell whose memory nobody
measured has nothing measured to show, so the absence is said in words. The cells on their way stand first, then the cells the
largest first, then other processes of 1 GB or more (`machine-map-legend-other`, no button). The row over the columns is words over
them, not a row of data: it has no `data-t`, and the patch that keeps the list current writes only the rows that have one. A row of
the list is the only place a cell is picked on this page, and the block under its legend shows the model that pick names. A pointer on a block or a row
lights that holder's pieces on every lane (`.machine-rack` says `is-lighting`, its blocks and row `is-lit`). The rack stands across the whole page, and at the end of each lane's row are its `machine-map-metric`s (`data-t-id` = `gpu-<index>:load`, `:memory`, `:power`, or `ram:load`, `ram:memory`): the value and little chart the monitor's tick writes under `data-node-metric-val` and `data-node-metric-spark` (`<machine>:gpu:<index>`, `mem`, `power`; `<machine>:cpu`, `ram`). `machine-map-total` (`data-t-id` = `gpu`, `vram`, `power`) is all the cards together, in the page's head after the map's legend; a press on either opens the machine's chart of it; which part of the cell a piece is, its layers and its
runner are in the hovers of its block and its row. A cell's `machine-model-launch`, a block or a row of the list can be dragged onto a lane: that lays a plan, and the lane under the
pointer says `data-machine-drop` = `ok` or `no`. With a plan in hand the cell's `machine-pick`, the last line of its `machine-model-launch`, has `data-t-state` = `planned`, its buttons are
`machine-plan-start` and `machine-plan-cancel`, and a chosen llama.cpp cell has a `machine-map-grip` on each lane (`data-t-id` = the card's index, or
`ram`), `is-on` where it holds a piece: `data-machine-grip-holds` says how much, in GB. That line's `machine-place` buttons (`data-t-id` = the card's
index, or `ram`) lay the same plan without a pointer. Nothing changes on the machine before `machine-plan-start`. While a cell is carried every lane
says `data-machine-target` = `ok` or `no`, whether it may lie there.

Under the map is the launch builder, `machine-build` (`data-t-id` = the model it builds for; `data-t-state` = `building`, `whole`, or `none` when no
model is picked — said by `machine-build-none` with `data-t-id` = `model`). It is two rows (the owner's choice Б, 2026-11-08): the rail of three
places on top, and under it the shelf. The places are the steps: each `machine-build-slot` (`data-t-id` = `engine`, `quant` or `params`,
`data-t-state` = `full` or `empty`) holds its `machine-build-step` (a tab of its own, `data-t-id` = the step; the one shown has `aria-selected="true"`),
which shows its cards on the one `machine-build-shelf` (`data-t-id` = the step shown): `machine-build-card`s (`data-t-id` = `engine:<runner>`, `quant:<file>` or `params:maker` / `params:set:<name>` / `params:cell:<cell id>` —
`params:maker` is what the model's maker stated once, first on its step; `data-t-state` =
`ok`, `on` or `dim`, a dim one's reason in its hover); a step with none says why by `machine-build-none` (`data-t-id` = the step). A card is put by a
press or carried up onto the rail, and the shelf goes on to the next step. While the launch is not whole the rail is `machine-build-slots`, and its
end names the builder and holds the model's `machine-model-new`; a full place has its `machine-build-empty` (✕, `data-t-id` = the step). Whole, the
rail is one `machine-build-strip` (`data-t-id` = `new`: the cell is not made until its Start, which makes it and
answers its id) with its `machine-build-port` (the "new cell" chip; the hook keeps its name), carried onto a lane as a cell's
row is, and the map's last line for that launch — its `machine-place` buttons, and with a plan
its `machine-plan-start`, which makes the cell and starts it.

Inside «What lies where», under its legend and on the map's whole width, is the block of the model picked (the owner's choice, 2026-11-05; its place
— variant А of the mockups, the owner's choice of 2026-11-06, so the map keeps its block and the pane that scrolls is the list): `machine-chosen`
(`data-t-id` = the model it shows, `data-t-state` = `chosen`, or `none` when nothing is picked) — and the absence is said in words by `machine-chosen-none`,
not drawn as an empty block. It holds the model's parts (`machine-chosen-line`), a `machine-model-launch` row per cell of that
model (`machine-chosen-cells`), the cells whose model has no row here to pick, and the button that makes a new cell from it. The texts its makers
recommend are not in it: they are read on the row of the list that is picked. The block is drawn for one model, so a pick that moves it draws the page
again; the list is shown in place.
The list the page puts under the map (2026-11-02; the bench of cards went on the same day, and `machine-bench`, `machine-bench-cell`, `machine-bench-ctx`,
`machine-bench-job`, `machine-bench-repo` and `machine-bench-rate` with it) is `machine-models` (`data-t-state` = `models`, or `empty` when neither the library nor a cell
names one): a `machine-model` per model's folder (`data-t-id` = the folder, `data-t-state` = `cells` or `none`), those with a cell here first, then by name,
and `machine-model-choose` (`aria-pressed`) is the press that picks which model the block shows — `machine-model-open`, `aria-expanded`, is gone with the row that used to
open. A row of the list is a press and nothing else: its buttons are in the block, and a cell whose model is not picked has no row on the page until its model is picked; what its makers said stands under the row that is picked, and a row that is not picked says nothing but its parts. Under the name, `machine-model-repo`
(`data-t-id` = the folder) is the repository on Hugging Face its first cell's path names (`author/repo`, the cell window's /hf link reads the same path); a model whose cells name
none has no such line. Its count of cells is a `[role="img"]` `.machine-model-cells`, its `aria-label` the words. `machine-model-rate` (`data-t-id` = `<model>:like` or `<model>:dislike`,
1.3.688) is the owner's mark on that model: `aria-pressed` says which stands; a press keeps it (`POST /api/model-rating`), shows at once and chooses nothing, and it works for a
model with no cell. `machine-models-filter` (`data-t-id` = `all`, `cells`, `like`), the `machine-models-job` pills (`data-t-id` = the work) and `machine-models-find` narrow the list
in place, together, and `machine-models-none` says nothing stayed. The block holds each cell of the model it shows as a `machine-model-launch` (`data-t-id` = the
cell's id), `hidden` while it does not do the work chosen and is not the chosen cell: a click anywhere on it chooses the cell, as `machine-model-cell` does (its name chip, a button, with `aria-pressed`).
The cells stand in the order this machine gave them; no row says where its values came from (a model's default cell is the launch builder's maker's set since 2026-11-07). Its size is the
span `[data-machine-bench-size="<cell id>"]` (what a working cell holds, what another weighs), and its verdict the span `[data-machine-bench-fit="<cell id>"]`: a working cell's
`data-t-state` is `running`, `warming` or `broken`, `crashed` once its scout's watchdog had to bring it back (`unreachable`, when the controller did not reach its port, went 2026-11-08: it reaches every cell through the scout), one on its way says its phase (`downloading`, `starting`, `loading`, `resolving`, `stopping`), and a standing one where it would go
now: `cards`, `card`, `free`, `spill`, `kvRam` (its layers on the cards, its cache in RAM), `ram`, `none`, `unknown` — or `failed` and `reserved`, which no estimate overwrites; a failed
cell's reason is in its `title`, and whole on its `machine-pick` line. A llama.cpp cell whose model the library knows is laid by the cell window's own plan (1.3.635), its size "with the cache"; any other by what its runner
takes, or by its files "without the cache". A token cell's row says its context with the line's own chip (1.3.648): `machine-model-ctx` (`data-t-id` = the cell's id), `data-t-state` `both`,
`set`, `max` or `over` as the line's `cell-row-ctx`; a cell whose context nobody said has none. `machine-model-window`, `machine-model-start` and `machine-model-stop` carry the attributes of the card's own buttons: the same question, the same stop or start, and press them only on a cell the test made itself. They
do and choose nothing. `machine-models-outside` names by their ids the cells that have no model's row; each of them, and a cell with no model, has a `machine-model-launch` of its own, in
`[data-machine-models-rest]` inside `machine-chosen-cells`, gone while the list is searched by words or 👍. `machine-model-said` (`data-t-state` = `said`, or `unread` when the texts could not be read) is what its
makers recommend; `machine-model-stated` (`data-t-state` = `stated`, `data-t-id` = the folder) is what a maker stated once — the numbers the launch builder offers
as the model's own set, each naming the field it belongs to; both stand on the row that is picked, never in the block, and a model the table does not name draws neither line, and that is not the same as a text that could not be read; `machine-model-new` opens the new-cell wizard on the model; `machine-model-context` (`data-t-id` = the model, `data-t-state` `known`, `unknown` or `none`) is the longest context it was trained for. A choice shows that
cell's `machine-pick` line (`data-t-id` = the cell's id; the others are `hidden`), and with nothing chosen — or a cell the
machine does not have — none; the chosen cell's row stands whatever the list is narrowed to; a chosen cell that stands is drawn dashed on the lanes where it would go
(`ui-lane-blk--estimate`, and its cache and buffers in `ui-lane-blk--estimate-cache` where the plan tells them apart). The
machine's page draws no cell lines of its own: they stay in the page, hidden, so the windows open from there.

At the right of the list stands `machine-side` (1.3.636), in four parts: `machine-side-engines` (the caravan's strip,
`node-caravan`, and each engine's group, as on the board's card), `machine-side-disk` (the model cache's line, `node-cache`, or the
words that its scout does not report it), `machine-side-incidents` and `machine-side-activity` (what is the machine's as a whole: the token speed and the routes; each
card's figures stand on its row of the rack). `machine-incidents-count` is the board's own incident counter (`data-t-state` = `some`, `none`, or `unknown` with a dash
while the monitor has not answered), and `machine-incidents-open` opens the incidents as the bar's "⚠" does.

The new-cell wizard (1.3.638, `add-model.js`) is `add-model`, its data-t-id the cell it makes (`new:<machine>` until the first Apply names it) and its data-t-state the step: `pick`, `runner` or `place`. Its parts: `add-model-close`; `add-model-step` (data-t-id 0–2, `disabled` until a model is picked); the first step's `add-model-job` (data-t-id the job, `aria-pressed`), `add-model-ability` (`projector`, `long`, `cell`), `add-model-search`, `add-model-hf`, `add-model-row` (data-t-id the model's value, `aria-pressed` on the one picked) and `add-model-empty`; the runner's `add-model-runner` (data-t-id a runner that can run the model), `add-model-mmproj`, `add-model-draft` and `add-model-full` (the full form); the third step's `add-model-ctx` (data-t-id a window), `add-model-ctx-own`, `add-model-parallel`, `add-model-cache`, `add-model-where` (`all`, a card's index, `cpu`), `add-model-flash`, `add-model-thinking`, `add-model-temp`, `add-model-name`, `add-model-starred` (data-t-id the field) or `add-model-starred-none`, `add-model-place`, `add-model-tip`, `add-model-all` and `add-model-keep`; the foot's `add-model-back`, `add-model-next`, `add-model-create` and `add-model-create-start`. The cell window's editor of the settings draws a `cell-settings-star` on each row (`aria-pressed`; data-t-id `<cell>:<FIELD>`).

## `node-poweroff` is the one control that cannot be undone

`node-reboot` and `node-poweroff` are items of the "⋯" menu of a machine's page (`machine-menu`, 1.3.630: they
stood next to each other in the machine card's header until then), both carrying `data-t-id` with the host id — the
menu's list is `hidden` until its button opens it (`data-ui-menu-toggle`, ui-menus.js). They are not equivalent and
should not be treated as a pair in a test.

Reboot, power off and disconnect (`node-disconnect`) all ask the operator to TYPE the host's name
(1.3.545; before it only power off did): the dialog's `confirm-input` is shown and `confirm-accept` stays
`disabled` until the typed text is the name (trimmed, exactly). Nothing else gets past it — not Enter, not a
call of the dialog's settle. Power off is the heaviest of the three, because nothing on this board can switch a
machine back on — a wrong click there ends with someone walking to the rack.

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
| `hf-download-job`, `hf-download-cancel`, `hf-download-open-page` | the job id from the server, falling back to the local uid before one is assigned |
| `hf-download-interrupted`, `hf-download-resume`, `hf-download-discard` | the name of the partial file |
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

## `routing-cable` endpoints are ports, not always nodes

One `routing-cable` per connection, `data-t-id` = `from->to`. On the live graph
that is 18 connections where counting `path` inside `routing-cables` returns 54 —
each edge draws an invisible hit-path, the visible cable and the ✕ puck's two
strokes, so the raw count was never a number about the graph.

The two ends are not all `routing-node` ids, and a test that assumes they are will
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
neither. The third state is `reserved`: the cell is kept, nothing is configured
to run in it, so there is nothing to start. Such a card offers only
`cell-configure` and `cell-delete`.

```
running   → cell-stop
stopped   → cell-start
reserved  → neither; configure it first
```

A caravan cell begins at `node-caravan-add` («＋ Add model», one per machine,
`data-t-id` = host id): the editor opens on a new cell, and Apply makes a configured cell, its id the controller's answer — there is no reserved step
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

`node-disconnect` is the last item of a host's "⋯" menu (`machine-menu`; never on the controller's node), on the
machine's own page — the main board's `machine-glance` has none since 2026-10-12; until 1.3.630 it was the card's ✕. There the whole glance
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
