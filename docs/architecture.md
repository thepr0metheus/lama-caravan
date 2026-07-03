# Architecture

LAMA CARAVAN is a control plane for a fleet of `llama.cpp` servers: one
controller host runs the admin UI and the routing proxy, client
hosts run their own llama servers behind a small route-agent, and coding
agents (OpenClaw) consume everything through per-agent proxy ports. Cloud
providers (OpenAI, OpenRouter, Anthropic-compatible, Ollama, ...) plug in as
additional routable outputs.

Everything is intentionally dependency-light: two stdlib-only Python daemons,
static HTML/CSS/JS with native ES modules, JSON files as the only IPC, and
`systemd --user` units for process management. There is no database, no
message broker, no build step.

## Components

```text
                 ┌────────────────────────────── Controller (:8090)  ─────────────────────────┐
                 │                                                                             │
 browser ──────► │  lama-caravan.service            lama-caravan-proxies.service              │
 (UI :8090)      │  app.py → caravan/admin/         agent-proxies.py → caravan/proxy/         │
                 │  · serves UI + HTTP API          · one listener per route port (:8101+)    │
                 │  · fleet topology & heartbeats   · queue admission / preemption            │
                 │  · writes agent-proxies.json ──► · router DAG (queue/schedule/rules)       │
                 │  · reads  proxy state/events ◄── · llama or cloud upstreams + translation  │
                 │                                                                             │
                 │  lama-cell@<port>.service         llamacpp-current.service (legacy)         │
                 │  var/server-cells/<port>/start.sh llama.cpp/start-server.sh (:8080)         │
                 └─────────────────────────────────────────────────────────────────────────────┘
                        ▲ heartbeats / node control (HTTP)                 ▲ proxied traffic
                        │                                                  │
        ┌── client hosts (your machines)    ──┐            OpenClaw agents (per host)      
        │ llm-easy-route-agent (:8092)        │            → their local proxy port :81xx
        │ · local llama cells / model cache   │
        │ · POSTs /api/topology/client-heartbeat
        │ whisper_server.py (command cells)   │
        └─────────────────────────────────────┘
```

| Component | Where | What it does |
|---|---|---|
| Admin server (`caravan/admin`) | controller `:8090` | UI + API: fleet topology, launch configs, HF model browser, monitors, cloud accounts, queue thresholds. See [backend-admin.md](backend-admin.md). |
| Proxy daemon (`caravan/proxy`) | controller `:8101+` (one port per route) | OpenAI-compatible reverse proxy per agent: admission queue, priority preemption, router DAG, cloud fallback, protocol translation. See [backend-proxy.md](backend-proxy.md). |
| Server cells | controller + clients | Per-port llama-server instances. Controller cells run under `lama-cell@<port>.service` from generated `var/server-cells/<port>/start.sh`; client cells are managed remotely through the route-agent. |
| Route-agent (`llm-easy-route-agent`, separate repo) | each client `:8092` | Publishes the host's llama nodes/GPUs to the admin (heartbeat) and executes start/stop/config/cache commands on behalf of the admin. |
| Whisper server (`whisper/whisper_server.py`) | any host | Example "command cell": an arbitrary server managed like a llama cell, with a health endpoint that reports download/load progress. |
| Frontend (`static/`) | served by admin | Topology board, standalone kanban/router canvas, HF browser. Native ES modules. See [frontend.md](frontend.md). |
| OpenClaw config managers | your hosts `:5005` | External agents' config source; the admin syncs per-agent `wait_timeout` from them and computes queue thresholds. |
| Fleet registry | `:8011` (optional) | Single source of truth for agent identity; discovered clients are registered by POSTing there. |

## Processes and entry points

Both daemons keep their historical entry filenames — systemd units exec them
directly and `scripts/test_queue_node.py` loads them by path:

```text
app.py            → caravan/admin/main.py:main()   (thin launcher, ~20 lines)
agent-proxies.py  → caravan/proxy/main.py:main()   (thin launcher, ~25 lines)
```

`caravan/admin/main.py` starts the monitor sampler (1 s loop), a one-shot
cloud-fallback bootstrap, the queue-thresholds refresher (6 h loop), then a
`ThreadingHTTPServer` with the route tables from `caravan/admin/routes.py`.

`caravan/proxy/main.py` starts the stop-request watcher, binds one
`ThreadingHTTPServer` per enabled route, and re-reconciles the listener set
every ~2 s as `agent-proxies.json` changes — route edits in the UI take
effect without restarting the daemon.

## File contract (the only IPC)

The two daemons never import each other; every interaction goes through files
in the project root. All JSON writes use unique-temp-name atomic replace
(`caravan/common/fsio.atomic_write_text`), so readers never see partial files
and concurrent writers cannot clobber each other.

| File | Written by | Read by | Purpose |
|---|---|---|---|
| `agent-proxies.json` | admin (`write_agent_proxy_payload`) and proxy (`append_stop_request` only) | proxy (mtime-watched, ~2 s), admin | Routes, routers/graph, policy, stop requests. Every admin write drops a `agent-proxies.json.bak-graph-<stamp>` autobackup next to it. |
| `agent-proxy-state.json` | proxy (`write_state`) | admin | Live active/recent requests, per-agent runtime — feeds the dashboard. |
| `logs/proxy-events/<date>.jsonl` | proxy (append) | admin | Per-request telemetry events (received/queued/admitted/completed/error); retention-trimmed by the proxy. |
| `cloud-providers.json` | admin | proxy, admin | Cloud accounts and model blocks. |
| `~/.config/llamacpp-easy-admin/provider-secrets.json` | admin, proxy (OAuth refresh) | both | API keys / OAuth tokens, mode 0600, outside the repo tree. |
| `~/.local/state/llamacpp-easy-admin/admin.json` | admin | admin | Persistent admin state: topology store, pricing, HF token/favorites, starred fields. |
| `client-labels.json`, `token-history.json` | admin | admin | Monitor labels; token-rate history (14 d). |
| `~/.config/llamacpp-easy-admin/openclaw-config-cache.json` | admin | admin | Last-known-good OpenClaw configs (may contain credentials → 0600, outside repo). |
| `var/server-cells/<port>/{cell.json,start.sh}` | admin | `lama-cell@.service` | Generated launch artifacts; `cell.json` is the source of truth, `start.sh` the runnable. |
| `var/server-backups/<host>/<gpu-or-CPU>/…` | admin | admin | Named launch-config snapshots for every node, kept on the controller so they survive the client. |
| `.bench_cache/`, `logs/model-pricing-cache.json` | admin | admin | HF benchmark and LiteLLM pricing caches. |

## Request path (agent traffic)

An OpenClaw agent talks to `http://<controller>:<its port>/v1/...`. The proxy
resolves the route, walks the router DAG (schedule / rule / queue nodes) to
pick an output, waits for a slot (FIFO queue with SSE keepalive, deadline
aborts, priority preemption, spill-to-overflow), then forwards to either a
local/remote llama-server or a cloud provider — rewriting the model name and
translating the protocol (Responses API, Anthropic Messages) when needed.
Full walk-through: [backend-proxy.md](backend-proxy.md#request-lifecycle).

The admin server is not on this path — if it is down, agent traffic keeps
flowing; only the UI and fleet orchestration stop.

## Configuration flow (UI edits)

1. The browser edits routes/routers/policy → `POST /api/agent-proxies/…`.
2. `caravan/admin/proxies_config.py` normalizes (via `router_dsl.py`) and
   atomically rewrites `agent-proxies.json` (+ autobackup).
3. The proxy's listener watcher notices the mtime within ~2 s, rebinds
   listeners if ports changed, and applies the new graph to subsequent
   requests. No restarts anywhere.

Launch-config edits for the legacy single server rewrite only the
`# BEGIN/END LLAMA CONFIG` block of `start-server.sh` (with a timestamped
backup); server cells regenerate `var/server-cells/<port>/` artifacts and
restart just that `lama-cell@<port>` unit.

## Code layout

```text
app.py, agent-proxies.py   thin launchers (do not rename/move)
caravan/
├── common/                stdlib helpers shared by both daemons
├── admin/                 admin server (30 modules)   → docs/backend-admin.md
└── proxy/                 proxy daemon (14 modules)   → docs/backend-proxy.md
static/
├── js/                    29 ES modules (entry main.js) → docs/frontend.md
├── css/                   9 cascade-ordered stylesheets
└── index.html / kanban.html / hf.html / hf.js
scripts/                   install/start scripts, queue-node unit tests, refactor tooling
systemd/                   unit files installed on Skynet
whisper/                   faster-whisper command-cell example
docs/                      this documentation + postmortems
```

Import layering inside `caravan/` is strict and cycle-free (see the backend
references); the frontend has an equivalent rule set around ES-module live
bindings. The HTTP surface is listed in [http-api.md](http-api.md); day-2
operations live in [operations.md](operations.md). Client hosts run the
companion `llm-easy-route-agent` sidecar (published separately), which
manages local llama cells and reports heartbeats to this controller.
