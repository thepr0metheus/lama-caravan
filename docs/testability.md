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
| `/` board | `loadState()` resolved and `renderAll()` ran | `static/js/main.js` |
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

## Not in scope

- `<canvas>` charts (`charts.js`, `topology-activity.js`). Canvas content is
  unreachable to a DOM test by construction; that the element rendered is all
  there is to assert, and that is enough.
- Markup restructuring. This contract adds attributes; it does not move
  anything.
