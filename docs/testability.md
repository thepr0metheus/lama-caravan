# Testability contract

The E2E suite (`lama-caravan-playwright`) drives this UI from outside, through a
browser, as a user does. That only works if a few things about the page are
promises rather than accidents. This document is the list of promises.

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
| `/` board | the topology rendered for the first time | `static/js/topology-render.js` |
| `/kanban` | topology fetched and the router rendered | `static/js/main.js` |
| `/models` | the model tree is drawn | `static/js/models-page.js` |
| `/system` | `/api/state` + `/api/controller-info` settled | `static/js/system-page.js` |
| `/hf` | token status, favourites and download jobs settled | `static/hf.js` |

Helper: `markPageState(state, detail)` in `static/js/utils.js`.

## `/health`

Open, unauthenticated, cheap. It is what a CI run asks before it has
credentials — or when the question is precisely whether credentials can be
checked at all.

```
GET /health        (also /api/health)
200 {"ok": true, "service": "lama-caravan", "version": "1.3.137",
     "commit": "5ff3bbe", "authRequired": true, "time": 1785342505}
```

The shape is **stable**: a monitor polls it forever, so fields can be added and
never taken away. It touches no fleet state — no host probes, no config — so the
liveness check can never itself become the slow or flaky thing.

`authRequired` earns its place: a fresh install answers `false`, and a suite that
expects to log in can learn that before spending a browser on it.

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

Generated from the source, not from memory — 135 values. Regenerate with
`python3 scripts/testability_names.py`; `--check` fails when this list and the
source disagree. Eleven of them are composed at runtime (`…-picker`,
`…-runner-tab`, `cell-source-stale`) and a plain grep will not find them —
that is why there is a script and not a one-liner.

**app** — `app-toast`
**board** — `board-clients-lane`, `board-cloud-lane`, `board-gpus-lane`, `board-incidents-list`, `board-llama-suspect-banner`, `board-models-bar`, `board-nodes-lane`, `board-processes-list`, `board-router-lane`, `board-system-open`
**cell** — `cell-card`, `cell-configure`, `cell-delete`, `cell-edit-apply`, `cell-edit-cancel`, `cell-edit-command`, `cell-edit-command-preview`, `cell-edit-env`, `cell-edit-fields`, `cell-edit-health-path`, `cell-edit-max-model-len`, `cell-edit-mmproj`, `cell-edit-modal`, `cell-edit-model`, `cell-edit-model-picker`, `cell-edit-moonshine-model`, `cell-edit-moonshine-model-picker`, `cell-edit-runner`, `cell-edit-runner-tab`, `cell-edit-vllm-model`, `cell-edit-vllm-model-picker`, `cell-edit-whisper-model`, `cell-edit-whisper-model-picker`, `cell-edit-workdir`, `cell-remote-apply`, `cell-remote-cancel`, `cell-remote-command`, `cell-remote-command-preview`, `cell-remote-env`, `cell-remote-fields`, `cell-remote-health-path`, `cell-remote-max-model-len`, `cell-remote-mmproj`, `cell-remote-modal`, `cell-remote-model`, `cell-remote-model-picker`, `cell-remote-moonshine-model`, `cell-remote-moonshine-model-picker`, `cell-remote-runner`, `cell-remote-runner-tab`, `cell-remote-vllm-model`, `cell-remote-vllm-model-picker`, `cell-remote-whisper-model`, `cell-remote-whisper-model-picker`, `cell-remote-workdir`, `cell-source-stale`, `cell-start`, `cell-stop`
**confirm** — `confirm-accept`, `confirm-cancel`, `confirm-input`, `confirm-meta`, `confirm-overlay`, `confirm-path`, `confirm-text`, `confirm-title`
**header** — `header`, `header-app-title`, `header-lang-current`, `header-lang-menu`, `header-lang-open`, `header-page-subtitle`, `header-user-chip`, `header-user-logout`, `header-user-menu`, `header-user-menu-open`, `header-user-name`, `header-user-security`, `header-version-branch`
**kanban** — `kanban-back-link`, `kanban-cables`, `kanban-canvas`, `kanban-node`, `kanban-palette-add`, `kanban-save-status`
**login** — `login-error`, `login-form`, `login-lang`, `login-password`, `login-submit`, `login-username`
**models** — `models-delete-selected`, `models-hero-stats`, `models-path-cancel`, `models-path-edit`, `models-path-edit-row`, `models-path-input`, `models-path-save`, `models-path-value`, `models-picked-summary`, `models-tree`, `models-unused-select-all`
**setup** — `setup-form`, `setup-go-board`, `setup-password`, `setup-password-repeat`, `setup-submit`, `setup-token`, `setup-token-box`, `setup-username`
**system** — `system-controller-info`, `system-diag-checks`, `system-diag-service-repair`, `system-gc-close`, `system-gc-delete`, `system-gc-list`, `system-gc-modal`, `system-gc-open`, `system-gc-select-all`, `system-gc-selected`, `system-gc-summary`, `system-hero-stats`, `system-llama-build-update`, `system-llama-builds`, `system-llama-summary`, `system-llama-update-log`, `system-llama-versions-check`, `system-security-info`, `system-security-logout`, `system-tab-controller`, `system-tab-diag`, `system-tab-llama`, `system-tab-security`, `system-vllm-list`

Repeated elements carry `data-t-id`: `cell-card` and the cell lifecycle buttons
use `host:port` (the `slotKey` the board already computes), `kanban-node` uses
the node id (`rule:…`, `inputs:block`), `kanban-palette-add` mirrors its
`data-cv-add`.

## Hooks that carry a value but are never visible

Some controls are a hidden native `<input>`/`<select>` under a custom widget, or
a container the current runner does not use. Their hook still reports the value
— `inputValue()` works on a hidden select — but **a visibility assertion on them
can never pass**, and that is not a defect to chase.

| hook | what it is | how to use it |
|---|---|---|
| `cell-*-model` | native `<select>` under the model picker | read the value |
| `cell-*-model-picker` | the visible widget above it | click this |
| `cell-*-runner` | hidden input holding the chosen runner | read the value |
| `cell-*-runner-tab` (+`data-t-id`) | the visible tabs | click these |
| `cell-*-whisper-model`, `cell-*-moonshine-model` | hidden carriers — the size / language is chosen in the SHARED model picker | read the value |

**`cell-*-fields` is not a collapsed section.** It holds the llama.cpp flags and
is hidden whenever the runner is not `llama-server`:

```js
llamaFields.style.display = nonLlama ? "none" : "";
```

So on a whisper or vLLM cell every llama field reports hidden — correctly. There
is no expander to click; switching the runner is what changes the field set, and
`cell-*-runner-tab` is how a test drives that.

## Not in scope

- `<canvas>` charts (`charts.js`, `topology-activity.js`). Canvas content is
  unreachable to a DOM test by construction; that the element rendered is all
  there is to assert, and that is enough.
- Markup restructuring. This contract adds attributes; it does not move
  anything.
