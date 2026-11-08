# Architecture

> **Purpose.** LAMA CARAVAN routes AI agents' token traffic between local
> llama.cpp servers and cloud providers: one OpenAI-compatible entry where every
> client has a key of its own, pools of rows tried in order (queues, schedules,
> limits), remote server cells on machines via caravan-scout, an HF model browser,
> and usage/spend accounting. The "why" in detail: see README → *Why LAMA
> CARAVAN*.

> **Deployment model.** A scout goes only where there is hardware to share.
> We are moving away from the model in which every client machine runs
> caravan-scout: the scout is the sidecar of a host whose GPU or CPU joins
> the pool, and that host's cells are launched from the board. A machine that
> only runs agents installs nothing — each agent is a client of the entry, made
> on the board (a name, what is blocked for it, its key shown once), the
> controller owns it, and the agent calls the entry with its key. Better
> support (nothing to install unless you share a
> GPU) and expectations that match the feature. The last releases moved the
> architecture onto this: board-made records are the source of truth, a scout
> report cannot create, rewrite or delete them.

LAMA CARAVAN is a control plane for a fleet of `llama.cpp` servers: one
controller runs the admin UI and the routing proxy, hosts that share hardware
run their own llama servers behind a small program of theirs (caravan-scout), and
coding agents (OpenClaw, Hermes, anything speaking the OpenAI API) consume
everything through one entry, each with its own key. Cloud accounts (OpenAI
subscriptions and keys, OpenRouter, Anthropic-compatible, DeepSeek, Ollama, ...)
stand in pools of rows, which are routable outputs like the cells.

Everything is three Rust programs under `rust/crates`, static HTML/CSS/JS with
native ES modules, and JSON files as the only way the controller and its proxy
talk. There is no database server, no message broker and no async runtime: a
thread per connection. The board's files have no build step; the programs are
built by `cargo`. (Everything stays in JSON on purpose: the proxy sees a config
change by its file's stamp, files diff cleanly in git, and a backup is a copy.)
The cell servers in `cells/` stay in Python on purpose: they run on the machines
beside the models, under what those models need. So do the dev tools in `scripts/`.

The Python controller and proxy left the repository on 2026-11-02. How the Rust is
written: [rust-code.md](rust-code.md).

## Components

```text
                 ┌──────────────────────── Controller (a container, or a machine) ─────────────┐
                 │                                                                             │
 browser ──────► │  caravan-admin (:7990)                caravan-proxy (the entry's port)      │
 (the board)     │  rust/crates/admin                    rust/crates/proxy, its child          │
                 │  · serves the board + HTTP API        · a client found by its key           │
                 │  · fleet topology & heartbeats        · a pool's rows, tried in order       │
                 │  · writes the settings files ───────► · a model's queue, its places         │
                 │  · reads the proxy's state, journal ◄ · a machine's model or a provider     │
                 │  · keeps the proxy running            · translation for a provider          │
                 └─────────────────────────────────────────────────────────────────────────────┘
                        ▲ heartbeats / node control (HTTP)                 ▲ proxied traffic
                        │                                                  │
        ┌── machines with hardware to share ──┐            agents and apps, any host
        │ caravan-scout (:8092)               │            → the entry, by a reverse proxy
        │ rust/crates/scout                   │
        │ · local llama cells / model cache   │
        │ · heartbeats to the controller      │
        │ · /v1: the machine's models, by name│
        │ cell servers fetched from controller│
        └─────────────────────────────────────┘
```

| Component | Where | What it does |
|---|---|---|
| Controller (`caravan-admin`, `rust/crates/admin`) | controller `:7990` | UI + API: fleet topology, launch configs, HF model browser, monitors, cloud accounts, queue thresholds. See [backend-admin.md](backend-admin.md). |
| Proxy (`caravan-proxy`, `rust/crates/proxy`) | controller: the entry's port, one listener | The entry: OpenAI-compatible; it finds a client by its key, then a pool's rows, a model's queue, protocol translation. The controller keeps it as a child. There is no other entry, and a route's own port no longer listens. See [backend-proxy.md](backend-proxy.md). |
| Server cells | machines with a scout, the controller's own machine included | Per-port llama-server, vLLM and command-server instances, started and stopped by the machine's scout on the controller's word. The controller runs none itself: its own machine's cells run through a scout installed there, like any other machine's. Each listens on its machine's loopback alone (`rules::CellDoor::LISTEN`, since 2026-11-08): a client reaches a model through the scout's entry (`/v1`), the controller reaches one cell through the scout's door (`/api/cell/<cell><path>`), and the machine shows the network one port of the caravan, the scout's. |
| Scout (`caravan-scout`, `rust/crates/scout`) | each machine with hardware `:8092` | Publishes the machine's llama nodes/GPUs to the controller (heartbeat), executes start/stop/config/cache commands on its behalf, and serves the machine's models at one address (`/v1`). One static program, handed out by the controller; a machine takes it with the command of ＋ Add scout, and a new version from its ⋯ menu. |
| Cell servers (moonshine, whisper, TTS — `cells/`, in Python) | any machine with a scout | The programs a "command cell" actually runs: ordinary servers managed like llama cells, with a health endpoint reporting download/load progress. The controller owns them and serves them over `/api/cell-assets`; a scout materializes them into `$HOME` before it starts a cell, where the generated cell command looks for them. They used to live in the scout repo and were copied by hand into the controller, which is how the two copies drifted for months. |
| Frontend (`static/`) | served by the controller | Topology board, standalone Routing page (`routing.html`), HF browser, models-disk and System pages. Native ES modules. See [frontend.md](frontend.md). |

Library crates under the three programs. A dependency goes only downwards, and the
compiler holds it so:

| Crate | What it holds |
|---|---|
| `rules` | The caravan's rules with no input or output: entry models, pools, limits, translation for providers. No file, socket, clock or environment (`scripts/check_rust_contract.py`). Each rule is held by a table of cases, `contract/*.json`. |
| `files` | The files the proxy reads and writes: the settings, the journal, the credential document, a file replaced whole. |
| `net` | Connections to what the caravan calls: plain TCP, TLS to a provider, connections kept between requests, SHA-256, the lock on a settings file's credentials. |
| `plumbing` | What a program needs from its machine: asking over HTTP, running a tool, its own log, a pass that repeats. |
| `wire` | HTTP/1.1 on a socket. It knows nothing of the caravan. |
| `os` | What only the C library can say: the local time, a thread's processor time, a file lock. The one `unsafe`. |

## Processes and entry points

```text
rust/crates/admin/src/main.rs    → caravan-admin    (`Program::run`, then `Startup::run`)
rust/crates/proxy/src/main.rs    → caravan-proxy    (`Listener::bind`, then `Listener::serve`)
rust/crates/scout/src/main.rs    → caravan-scout    (`Scout::new`, then `Api::serve`)
```

`caravan-admin` first checks what a container must be told (`TZ`,
`LLAMA_TOPOLOGY_SERVER_IP`) and its port ranges, and that it can write the data
folder. `Startup::run` (`rust/crates/admin/src/startup.rs`) then starts the proxy and
its watchdog, runs the one-shot migrations, makes the built-in clients (opening the
entry when it is off) and starts the background threads: the first walk of the models
folder and the first read of the board, the monitor sampler (1 s loop), a one-shot
cloud-fallback bootstrap, the queue-thresholds refresher (6 h loop), the watch of the
release link, the GPU driver's watch and the cells' schedule. Only then does it listen,
one thread to a connection, with the route tables of `rust/crates/admin/src/routes/`.

The proxy is the controller's child (`rust/crates/admin/src/proxies/service.rs`),
wherever the controller runs. Its program is `<root>/bin/caravan-proxy`, its output goes
to `logs/rust-proxy.log`, and `CARAVAN_RUST_ENTRY_PORT` tells it the entry's port. A
watchdog looks every 500 ms: a dead child is started again; a closed entry has no child;
when the entry moves, the old child is killed, since the port is to be free now, not when
its last request ends. A controller that ends, even by `kill -9`, takes its proxy along:
`CARAVAN_PROXY_KEEPER` names the keeper, and within 2 s the proxy has another parent, lets
the port go and finishes its requests. A new file of the program is started beside the running one. The
old one sees its file change, lets the port go, finishes its requests and ends
(`rust/crates/proxy/src/drain.rs`). In a container the restart that a new release brings
ends it too: [operations.md](operations.md#deploy).

`caravan-proxy` reads its settings from the environment once and does not start without
the entry's port and `CARAVAN_DATA_DIR`. It binds the entry's port alone, and starts the
state writer, the pool watch (`PoolWatch`, 1 s) and the watch of the models' places
(`PlacesWatch`, 10 s). A route of `agent-proxies.json` is a client of the entry, or an
agent of the older kind: its own port no longer listens, and its key gets a 403 at the
entry. Reopening a port answers 410. Route edits on the board
take effect at the next request, with no restart.

A release is one folder, `<root>`: the two programs, `static/`, `cells/`, `VERSION`,
`bin/rust-packages.txt` and the scout the controller hands out (`scout-bundle.tar.gz`,
`scout-bundle.json`). `CARAVAN_ROOT` names it. When `CARAVAN_ROOT` is a link and comes to
name another folder, the controller ends once the proxy's state file shows no request
running, ten minutes at the most, and whatever keeps it running starts the new one: a
container's restart policy, with no new image (`Startup::release_watch`).

## File contract (the only IPC)

The controller and the proxy never link each other; every interaction goes through
files under the data folder (`CARAVAN_DATA_DIR`, `/data` in a container). All JSON
writes go through a temporary file beside the target and a rename
(`rust/crates/files/src/atomic.rs`, `AtomicFile`), so readers never see a partial file.
Where each file is: `rust/crates/admin/src/paths.rs`, and for the proxy
`rust/crates/proxy/src/config.rs`; an environment variable there can name another place
for any of them.

| File under the data folder | Written by | Read by | Purpose |
|---|---|---|---|
| `config/agent-proxies.json` | controller (`ProxiesConfig::write_payload`) | proxy (its stamp looked at on each request), controller | Routes, routers' outputs, policy, the entry, stop requests. While the file still holds router-graph nodes, a write first keeps a `agent-proxies.json.bak-graph-<stamp>` beside it, the newest 20. |
| `state/agent-proxy-state.json` | proxy (`Proxy::write_state`) | controller | Live active/recent requests, per-client runtime, pools, limits, places — feeds the dashboard. On the NAS it is `/tmp/agent-proxy-state.json`, in memory (`AGENT_PROXY_STATE_FILE`, `deploy/nas/compose.yaml`): it is rewritten every few seconds. |
| `logs/proxy-events/<date>.jsonl` | proxy (`files::Journal`, append) | controller | Per-request telemetry events (received/queued/admitted/finished/blocked …); days past `AGENT_PROXY_LOG_RETENTION_DAYS` (30) are taken away by the proxy. |
| `logs/rust-proxy.log` | the proxy's own output | a person | What the proxy says of itself. `docker logs` carries the controller's. |
| `config/cloud-providers.json` | controller | proxy, controller | Cloud accounts and pools of rows. |
| `secrets/provider-secrets.json` | controller and proxy, both through `files::CredentialVault` | both | API keys / OAuth tokens, mode 0600. The proxy writes when it renews a token, under the same per-account lock. |
| `state/model-catalog.json` | controller | proxy, controller | Provider model lists (10 min TTL), endpoint circuit-breaker state, cached codex client version. |
| `state/subscription-resets.json` | controller | proxy, controller | When each account's limits were last reset by hand. |
| `state/admin.json` | controller | controller | Persistent admin state: topology store, pricing, HF token/favorites, starred fields. |
| `state/auth.json` | controller | controller | Accounts, sessions and the fleet token, mode 0600. An `auth.db` of the Python controller beside it is read once, at the first start, and stays as it was. A fresh controller answers only its public routes until the first user exists. |
| `state/token-history.json` | controller | controller | Token-rate history (14 d). |
| `state/monitor-history.json`, `state/incident-log.jsonl` | controller | controller | The monitor's samples and the incidents. |
| `state/gguf-headers.json`, `state/library-meta.json`, `state/store-moves/` | controller | controller | What the models' headers said, the same for a library's files, one manifest per model move. |
| `server-backups/<host>/<gpu-or-CPU>/…` | controller | controller | Named launch-config snapshots for every node, kept on the controller so they survive the machine. |
| `settings-backups/<YYYYMMDD-HHMMSS-micros>-before-import.json` | controller | controller | The settings as they were before a settings import, secrets included, so the import can be undone. One file per import, named to the microsecond and never written over: two imports in one second keep both. |
| `state/bench-cache/`, `logs/model-pricing-cache.json`, `logs/aa-scores-cache.json` | controller | controller | HF benchmark, LiteLLM pricing and Artificial Analysis score caches. |
| `config/start-server.sh` | controller | controller | The controller's own config: its models directory and the defaults every new cell starts from. Rewritten whole by `POST /api/config`. |

The proxy's program does not start without `CARAVAN_DATA_DIR`. The older places the
controller's `paths.rs` still names for a controller without it (the checkout's root,
`~/.local/state/llamacpp-easy-admin/`) therefore serve no running caravan.

## Request path (agent traffic)

A client calls the entry — `https://<its name>/v1/...` through a reverse proxy,
with its key. The key names its route, and `model` names a pool, or a model that runs as
a pool of one row. The proxy takes the first row of that pool fit now. A row of a
machine's model waits for a place in that model's queue (FIFO, with SSE keepalive, until
its patience or its limit), then goes to the machine's entry, its scout, or a cell; a
row of a provider goes to the provider, its model name rewritten and the protocol
translated (Responses API, Anthropic Messages) when needed. A row that fails before its
first byte sends the request on to the next one.
Full walk-through: [backend-proxy.md](backend-proxy.md#request-lifecycle).

The controller is not on this path: the proxy asks it nothing, and a busy board does not
slow agent traffic. But the proxy is its child, so in a container the two end together:
when the container's main process ends, its other processes end with it, until the
restart.

## Configuration flow (UI edits)

1. The browser edits routes/routers/policy → `POST /api/agent-proxies/…`
   (`rust/crates/admin/src/routes/proxies.rs`).
2. `ProxiesConfig` (`rust/crates/admin/src/proxies/config.rs`) normalizes (via
   `RouterDsl`, `proxies/dsl.rs`) and atomically rewrites `config/agent-proxies.json`
   through its one door, `write_payload`.
3. The proxy looks at the settings files' stamps on each request
   (`rust/crates/files/src/settings.rs`) and reads a file again only when its stamp
   moved, so the next request goes by the new settings. Its pool watch looks every
   second and decides again a pool that was edited. No restart, but one: an entry moved
   to another port or closed is a new child of the controller, within half a second.

Saving the controller's own launch config rewrites its `start-server.sh`
whole, from the command builder that starts cells (no backup copy is kept: the
settings file carries it); a server cell's config is saved on the controller and goes to the
machine's scout on the next start (and at once, when the cell has autostart).

## Code layout

```text
rust/                      the Rust workspace (Cargo.toml, its lints; rust-toolchain.toml names the compiler)
└── crates/
    ├── admin/             the controller, caravan-admin  → docs/backend-admin.md
    ├── proxy/             the entry, caravan-proxy       → docs/backend-proxy.md
    ├── scout/             one machine's scout, caravan-scout, with install.sh and scripts/
    └── rules, files, net, plumbing, wire, os             the library crates, above
contract/                  tables of cases the Rust rules and the browser share
static/
├── js/                    ES modules + i18n/ (entries main.js, models-page.js, system-page.js, hf-page.js) → docs/frontend.md
├── css/                   the slices of the old styles.css, files written later, ui.css (the parts' tokens)
└── index.html / routing.html / hf.html / models.html / system.html
cells/                     cell servers served to the fleet (/api/cell-assets), in Python
scripts/                   guards, tests, install scripts and the stand, in Python and shell
tests/frozen/              what each program promised to answer (scripts/_frozen_answers.py)
docs/                      this documentation + postmortems
```

Dependencies go only downwards between the crates, and `scripts/check_rust_contract.py`
holds how the Rust is written (its rules: [rust-code.md](rust-code.md)). The
frontend has its own rule set around ES-module live bindings. The HTTP surface is listed
in [http-api.md](http-api.md); day-2 operations live in [operations.md](operations.md).
