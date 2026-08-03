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

## The header is the same on every page

Left to right, on all five:

```
[← back] [brand] [version] · [page title h1] · [page actions] [account] [tour] [language]
```

`/board` has no back-link (it is where back goes). `/models` and `/system` have
no Tour button because those two pages have no tour — the others do. Everything
else is present everywhere, in that order.

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

Every page has exactly one `<h1>`, and it is the page's own name — `Board`,
`Models on disk`, `System & settings`, `Kanban Board`, `HuggingFace Browser`.
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
everything else visible — under `?lang=ru` it reads `Доска`, not `Board`. For
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

Generated from the source, not from memory — 162 values. Regenerate with
`python3 scripts/testability_names.py`; `--check` fails when this list and the
source disagree. Fourteen of them are composed at runtime (`…-picker`,
`…-runner-tab`, `cell-source-stale`) and a plain grep will not find them —
that is why there is a script and not a one-liner.

**app** — `app-toast`
**board** — `board-cell-add`, `board-client-card`, `board-clients-lane`, `board-cloud-lane`, `board-gpus-lane`, `board-incidents-list`, `board-llama-suspect-banner`, `board-models-bar`, `board-nodes-lane`, `board-processes-list`, `board-router-lane`, `board-system-open`
**cell** — `cell-broken-error`, `cell-card`, `cell-configure`, `cell-delete`, `cell-edit-apply`, `cell-edit-cancel`, `cell-edit-command`, `cell-edit-command-preview`, `cell-edit-compute`, `cell-edit-env`, `cell-edit-fields`, `cell-edit-health-path`, `cell-edit-max-model-len`, `cell-edit-mmproj`, `cell-edit-modal`, `cell-edit-model`, `cell-edit-model-picker`, `cell-edit-moonshine-model`, `cell-edit-moonshine-model-picker`, `cell-edit-runner`, `cell-edit-runner-tab`, `cell-edit-vllm-model`, `cell-edit-vllm-model-picker`, `cell-edit-whisper-model`, `cell-edit-whisper-model-picker`, `cell-edit-workdir`, `cell-remote-apply`, `cell-remote-cancel`, `cell-remote-command`, `cell-remote-command-preview`, `cell-remote-compute`, `cell-remote-env`, `cell-remote-fields`, `cell-remote-health-path`, `cell-remote-max-model-len`, `cell-remote-mmproj`, `cell-remote-modal`, `cell-remote-model`, `cell-remote-model-picker`, `cell-remote-moonshine-model`, `cell-remote-moonshine-model-picker`, `cell-remote-runner`, `cell-remote-runner-tab`, `cell-remote-vllm-model`, `cell-remote-vllm-model-picker`, `cell-remote-whisper-model`, `cell-remote-whisper-model-picker`, `cell-remote-workdir`, `cell-source-stale`, `cell-start`, `cell-stop`
**confirm** — `confirm-accept`, `confirm-cancel`, `confirm-input`, `confirm-meta`, `confirm-overlay`, `confirm-path`, `confirm-text`, `confirm-title`
**header** — `header`, `header-app-title`, `header-lang-current`, `header-lang-menu`, `header-lang-open`, `header-page-subtitle`, `header-page-title`, `header-user-chip`, `header-user-logout`, `header-user-menu`, `header-user-menu-open`, `header-user-name`, `header-user-security`, `header-version-branch`
**hf** — `hf-capability-filter`, `hf-download-job`, `hf-limit`, `hf-mask`, `hf-on-disk`, `hf-result`, `hf-search-input`, `hf-search-submit`, `hf-size-filter`, `hf-sort`, `hf-token-clear`, `hf-token-edit`, `hf-token-input`, `hf-token-save`
**kanban** — `kanban-back-link`, `kanban-cable`, `kanban-cables`, `kanban-canvas`, `kanban-input-wait`, `kanban-node`, `kanban-palette-add`, `kanban-save-status`
**login** — `login-error`, `login-form`, `login-lang`, `login-password`, `login-submit`, `login-username`
**models** — `models-delete-selected`, `models-hero-stats`, `models-model-select`, `models-path-cancel`, `models-path-edit`, `models-path-edit-row`, `models-path-input`, `models-path-save`, `models-path-value`, `models-picked-summary`, `models-tree`, `models-tree-group`, `models-tree-group-toggle`, `models-unused-select-all`
**node** — `node-poweroff`, `node-reboot`
**setup** — `setup-form`, `setup-go-board`, `setup-password`, `setup-password-repeat`, `setup-submit`, `setup-token`, `setup-token-box`, `setup-username`
**system** — `system-controller-info`, `system-diag-checks`, `system-diag-service-repair`, `system-gc-close`, `system-gc-delete`, `system-gc-list`, `system-gc-modal`, `system-gc-open`, `system-gc-select-all`, `system-gc-selected`, `system-gc-summary`, `system-hero-stats`, `system-llama-build-update`, `system-llama-builds`, `system-llama-summary`, `system-llama-update-log`, `system-llama-versions-check`, `system-security-info`, `system-security-logout`, `system-tab-controller`, `system-tab-diag`, `system-tab-llama`, `system-tab-security`, `system-vllm-list`

Repeated elements carry `data-t-id`: `cell-card` and the cell lifecycle buttons
use `host:port` (the `slotKey` the board already computes), `kanban-node` uses
the node id (`rule:…`, `inputs:block`), `kanban-input-wait` uses the input
port's id (`skynet:proxy:<port>` — `skynet` is the controller's internal id in
the data model, not a hostname), `kanban-palette-add` mirrors its `data-cv-add`.

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
| `board-gpus-lane` | a GPU mini-summary `nodes.css` hides on purpose — redundant with the node card's own GPU rows | read the values; it has no landmark role for the same reason |

## Landmark regions

The panels and lanes carry `role="region"` with a name, so they can be reached
as `getByRole('region', { name })` and a keyboard user can jump between them:

| page | region name | source of the name |
|---|---|---|
| `/` | Model Servers, Clients with caravan-scout, Cloud Providers | the section's own `<h2>` |
| `/system` | Controller, llama.cpp, Archived builds, vLLM runner, Security, Diagnostics | the panel's own `<h2>`/`<h3>` |
| `/models` | Model files, Disk summary | their own string (no heading exists) |
| `/kanban` | Routing graph | its own string |

Nine of the twelve are named by `aria-labelledby` pointing at the heading a
sighted user already reads, so the name follows the interface language — under
`?lang=ru` the region is `Модельные серверы`, not `Model Servers`. Locate by
role+name only when the language is pinned; otherwise the `data-t` hook is
still the stable address.

**`/system` regions live on tabs.** Only the active tab's panel is in the
accessibility tree — `getByRole('region', { name: 'Security' })` is 0 until
that tab is selected, and 1 after. That is correct behaviour, not a defect.

## Repeated elements carry their own name

`cell-card`, `cell-configure` and `board-cell-add` each expose the identity
their `data-t-id` carries — `Cell controller:8001`, `Configure:
controller:8001`, `Reserve cell :8024 — skynet`. Before this they were
announced identically 22, 22 and 2 times over.

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
redirects. The wizard's post-submit token box (`setup-token-box`, `setup-token`,
`setup-go-board`) lives on `/setup` too.

**`cell-*-fields` is not a collapsed section.** It holds the llama.cpp flags and
is hidden whenever the runner is not `llama-server`:

```js
llamaFields.style.display = nonLlama ? "none" : "";
```

So on a whisper or vLLM cell every llama field reports hidden — correctly. There
is no expander to click; switching the runner is what changes the field set, and
`cell-*-runner-tab` is how a test drives that.

## `node-poweroff` is the one control that cannot be undone

`node-reboot` and `node-poweroff` sit next to each other in every node header,
both carrying `data-t-id` with the host id. They are not equivalent and should
not be treated as a pair in a test.

Reboot asks a yes/no dialog. **Power off asks the operator to TYPE the host's
name**, because nothing on this board can switch a machine back on — a wrong
click there ends with someone walking to the rack. An inexact answer cancels; it
does not error.

Assert both are present. Press neither. `node-poweroff` belongs with
`cell-*-apply`, `system-gc-delete` and `hf-token-clear` — named so a test can see
them, not so it can use them.

## `/hf` stands apart

It is the one page that does not use the shared header, so none of the `header-*`
hooks exist there — it has its own back link. It also loads no shared JS: `hf.js`
deliberately imports nothing from `js/`, which is why the 1.9 MB translation
table never reached it even before that was split. Expect a smaller vocabulary,
not a missing one.

Its two repeated families carry the identity the page already works in:

| hook | `data-t-id` |
|---|---|
| `hf-result` | the repository id, e.g. `unsloth/gemma-4-31B-it-GGUF` |
| `hf-download-job` | the job id from the server, falling back to the local uid before one is assigned |
| `hf-size-filter` | `all`, `0-9`, `10-19`, `20-29`, `30-39`, `40-74`, `75+` |
| `hf-capability-filter` | the type as the API names it (`it`, `mmproj`, `mtp`, `vision`, …) |

The size buckets are the values the page filters on, not their labels — `0-9`
rather than `≤9B`, so a translated label cannot move them.

**`hf-token-clear` deletes a credential** and `hf-download-job` writes to disk.
Both are named so they can be asserted present; neither should be clicked, the
same rule as `cell-*-apply` and the destructive controls on `/system`.

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

Rules are nodes and appear as themselves. The inputs and outputs blocks are each
one node (`inputs:block`, `outputs:block`) holding many ports, and an edge
attaches to a **port** — which is the useful thing, since "some input reaches
this rule" is weaker than "port 8101 reaches it". To assert a path end to end,
match the prefix (`in:` / `out:`) rather than expecting a node id.

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

Reserved is where a cell begins. `board-cell-add` (the ＋ button on a host, one
per host, `data-t-id` = host id) reserves the next free port; `cell-configure` on
that card opens the editor in add mode. So "a card offers exactly one of
start/stop" is the wrong assertion — it is right for the two states a configured
cell can be in, and reserved is neither of them.

## Host id and display name are different strings

Cards are addressed by **host id**: `controller:8005`, `<client-id>:8004`. The
board shows the **display name**, which is set per host and is usually not the
id — the controller and each client both render under a name of their own. Same
machine, two strings, and the models path shown on `/models` uses the display
name too.

They are joinable now: `board-client-card` carries `data-t-id` with the host id
and the heading with the name. Without that the clients lane looks unrelated to
the cards it owns — a lane showing a display name beside cards prefixed with an
id reads as a lane with nothing in it.

The controller is a node like any other but is not a *client*: it runs no
caravan-scout, so it never appears in `board-clients-lane`. A fleet of one
controller and two clients renders three nodes and two client cards.

## Not in scope

- `<canvas>` charts (`charts.js`, `topology-activity.js`). Canvas content is
  unreachable to a DOM test by construction; that the element rendered is all
  there is to assert, and that is enough.
- Markup restructuring. This contract adds attributes; it does not move
  anything.
