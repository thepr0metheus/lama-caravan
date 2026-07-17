# HTTP API

The admin server (`:8090`) dispatches from the route tables in
`caravan/admin/routes.py`. Everything is JSON unless noted; errors come back
as `{"error": "..."}` with the `AppError` status (or 500). Arguments travel
as query strings on GET/DELETE and as a JSON body on POST.

Dispatch semantics (kept bit-for-bit from the original monolith):

- Prefix routes are checked first, in order: `/api/monitor/<kind>`, `/js/<file>`, `/css/<file>`.
- POST parses the JSON body **before** the path lookup — a malformed body on an
  unknown path is a 500, not a 404.
- `do_DELETE` has no `AppError` handler, so validation errors surface as 500.
- Unknown paths → `{"error": "Not found"}` 404.

New routes register with `@_route(TABLE, "/path", …)`; duplicate registration
fails at import time.

## Dashboard & launch config

| Method & path | Purpose |
|---|---|
| `GET /api/state` | Composite dashboard state: parsed launch config, models, service status, backups, field help. |
| `POST /api/config` | Save launch config `{config, restart}` — rewrites the `# BEGIN/END LLAMA CONFIG` block (with backup), optional restart. |
| `POST /api/config/snapshot` | Save a named config snapshot into `var/server-backups/`. |
| `POST /api/config-favorites` | Persist the starred launch-form fields (Favorites tab). |
| `POST /api/llama-command-preview` | Build the llama-server command line for a config dict (GUI diff preview). |
| `POST /api/parse-extra-args` | Hoist recognized flags out of a raw `EXTRA_ARGS` string into structured fields. |
| `POST /api/action` | Service action `{action: start\|stop\|restart}` on the managed llama service. |
| `POST /api/revert` | Restore the newest `start-server.sh.bak.*`. |
| `GET /api/backup?path=` | Read one backup's parsed config. |
| `POST /api/backup/delete` | Delete a named backup. |
| `POST /api/repair/user-service` | Rewrite/repair the `systemd --user` unit for the managed service. |
| `GET /api/raw/start-server` | Raw text of `start-server.sh`. |
| `GET /api/llamacpp` | llama.cpp build/version info (`?fetch_remote=1` compares upstream). |
| `POST /api/llamacpp/update` | Pull + rebuild llama.cpp from git (background job). |
| `GET /api/llamacpp/update-status` | Progress/log stream of the running build job. |
| `GET /api/llamacpp/builds` | Archived controller builds (rollback points). |
| `POST /api/llamacpp/restore` | Restore an archived build over the current binary. |
| `POST /api/llamacpp/suspect-dismiss` | Dismiss the crash-watchdog "suspect build" banner (server-side, survives reloads). |
| `GET /api/vllm` / `POST /api/vllm/update` | vLLM venv version/pip history / update or roll back the pinned version. |
| `GET /api/controller-info` | System page payload: services, cells, git, python, models-disk numbers. |
| `GET /api/script-preview?host=&port=` | Rendered start.sh preview for a cell (read-only, $HOME-scoped, 64 KB cap). |

## Models & HuggingFace browser

| Method & path | Purpose |
|---|---|
| `GET /api/models` | Local GGUF catalog (families, sizes, metadata). |
| `GET /api/models/download?path=` | Stream a local GGUF file to the browser. |
| `GET /api/models/disk` | Models-disk tree with per-directory size rollups (the `/models` page). |
| `GET /api/models/unused` | GGUFs no cell/config references (multi-part groups counted as one). |
| `POST /api/models/gc` | Delete selected unreferenced model files (server re-checks references). |
| `GET /api/hf/model-tree?repo=` | Quantizations/siblings of a repo via the HF model-tree filter. |
| `GET /api/hf/search?q=&limit=` | HuggingFace model search. |
| `GET /api/hf/files?repo=` | GGUF file listing of a repo (classified by quant/type). |
| `GET /api/hf/local-check?repo=` | Which files of the repo already exist locally. |
| `DELETE /api/hf/local-file?repo=&name=` | Delete a local copy of a repo file. |
| `POST /api/hf/download` | Start a background download job `{repo, files[]}`; answers `{jobId}`. |
| `GET /api/hf/download/status?job=` | One job's progress. |
| `GET /api/hf/download/jobs` | All running/errored jobs (page-reload recovery). |
| `GET /api/hf/token` / `POST /api/hf/token` | Masked HF token status / save token (clears the HF cache). |
| `GET /api/hf/favorites` / `POST /api/hf/favorites` | Starred repos for the HF browser. |
| `GET /api/hf/benchmarks?repo=&force=` | Benchmark metadata for a repo (leaderboards + AA). |
| `GET /api/hf/benchmarks/status` | Open-LLM-Leaderboard cache warm-up status. |
| `GET /api/hf/bench-search?q=` | Search cached benchmark results by model name. |
| `GET /api/hf/reference-models?force=` | Frontier reference table with AA Intelligence Index. |
| `POST /api/aa-scores` | Batch-resolve Artificial Analysis scores for model names. |

## Monitors & telemetry

| Method & path | Purpose |
|---|---|
| `GET /api/monitor/<kind>` | Terminal-style snapshot: `nvidia-smi`, `btop`, service logs… |
| `GET /api/system-monitor` | CPU/RAM/disk/net/GPU sample history + llama activity. |
| `POST /api/system-monitor/settings` | Set monitor retention seconds. |
| `POST /api/system-monitor/client-label` | Label a client IP in the monitors. |
| `GET /api/token-history?client=&range=` | Token-rate history (14 d ring). |
| `GET /api/usage-stats?days=` | Usage & spend aggregation over proxy event logs. |
| `GET /api/proxy-daily-stats?date=` | Per-route request/failure counts for a day. |
| `GET /api/agent-proxy-logs?date=&limit=&event=&port=&route=&client=&errors=&slim=&summary=` | Proxy event log rows, filterable per route. `port` — proxy route port (the stable per-agent id), `route` — label substring, `client` — exact IP, `errors=1` — only failed rows, `slim=1` — drop the bulky queue/active snapshots, `summary=1` — per-port terminal counters `{total, errors, byKind}` instead of rows. See [operations.md](operations.md#request-log-diagnostics-api) for curl recipes. |

## Fleet topology & cells

| Method & path | Purpose |
|---|---|
| `GET /api/topology` | The full fleet tree: clients, agents, servers, GPUs, proxies, routers, cloud. |
| `POST /api/topology/client-heartbeat` | Route-agent heartbeat: llama nodes, GPUs, cache state. |
| `POST /api/topology/assignments` | Store client→router assignments (cable drops). |
| `POST /api/topology/client-alias` | Rename a client in the UI. |
| `POST /api/topology/discover/add` | Register a discovered candidate into the fleet registry. |
| `POST /api/topology/client/delete` | Unregister a client. |
| `POST /api/topology/client/agent/delete` | Remove one agent under a client (suppressed on refresh). |
| `POST /api/topology/orphan-assignment/delete` | Clean a stale assignment. |
| `GET /api/topology/client-monitor?hostId=&kind=` | Proxy a client's monitor snapshot through its route-agent. |
| `GET /api/topology/client-llama/configs?hostId=` | Remote llama-node config list. |
| `POST /api/topology/client-llama/configs/save` / `…/delete` | Manage remote configs. |
| `GET /api/topology/client-llama/list-cache?hostId=` | Remote model cache contents. |
| `POST /api/topology/client-llama/start` / `…/stop` | Start/stop a llama node on a client via its route-agent. |
| `POST /api/topology/client-llama/purge-cache` | Clear a client's model cache. |
| `POST /api/topology/server-slot/add` / `…/delete` | Declare/remove a persistent host:port server slot. |
| `POST /api/topology/server-cell/action` | Cell lifecycle `{action: start\|stop\|restart\|delete}` (controller systemd or client via agent). |
| `POST /api/topology/server-cell/save-config` | Save a cell's config without starting it. |
| `POST /api/topology/server-cell/schedule` | Save a cell's start/stop window (`{enabled, start, stop, days[]}`). |
| `POST /api/topology/server-cell/reassign-port` | Move a parked cell to a free port (fleet-wide check; router refs remapped `srv:old→srv:new`). |
| `POST /api/topology/server-slot/note` | Save the free-text note on a cell card. |
| `POST /api/fleet/llama-update` / `…/llama-restore` | Build/update llama.cpp on a client host via its scout / restore an archived client build. |
| `GET /api/fleet/llama-update-status?hostId=` / `GET /api/fleet/llama-builds?hostId=` | Client build-job progress / archived builds on a client. |
| `GET /api/topology/agent-openclaw?client=&agent=` | Fetch one agent's OpenClaw state through the route-agent. |
| `GET /api/openclaw-config?client=&refresh=` | Cached OpenClaw config snapshot per manager. |
| `GET /api/queue-thresholds` / `POST /api/queue-thresholds/recalc` | Computed queue wait thresholds / force resync from OpenClaw. |

## Agent proxies & routers

| Method & path | Purpose |
|---|---|
| `GET /api/agent-proxies/raw` | Raw `agent-proxies.json` text (viewer modal). |
| `POST /api/agent-proxies/config` | Save the full routes list. |
| `POST /api/agent-proxies/policy` | Save the global queue/preemption policy. |
| `POST /api/agent-proxies/route-policy` | Patch one route's policy overrides. |
| `POST /api/agent-proxies/routers` (alias `…/switchboards`) | Save routers incl. the kanban graph (nodes/edges). |
| `POST /api/agent-proxies/reconcile` | Pull proxy-daemon runtime metadata back into the config. |
| `POST /api/agent-proxies/stop` | Stop a route's in-flight request (writes a stopRequest). |

## Cloud accounts & pricing

| Method & path | Purpose |
|---|---|
| `POST /api/cloud-accounts/save` / `…/delete` | Upsert / delete a provider account. |
| `POST /api/cloud-accounts/key` / `…/key-delete` | Store / remove an API key (0600 secrets file). |
| `POST /api/cloud-accounts/oauth/start` / `GET …/oauth/status?state=` | PKCE OAuth login flow. |
| `GET /api/cloud-accounts/models?id=` | Live model list from the provider API. |
| `GET /api/cloud-accounts/subscription-models?id=` / `…/subscription-usage?id=` | Subscription-plan models / usage+reset info. |
| `GET /api/cloud-accounts/api-costs?id=` | Official spend report (where the provider offers one). |
| `GET /api/cloud-accounts/openrouter-limits?id=` | OpenRouter key limits/credits. |
| `GET /api/cloud-accounts/proxy-spend` | Spend summary accumulated by the proxy per account. |
| `POST /api/cloud-blocks/save` / `…/delete` / `…/expose` | Manage model blocks; `expose` toggles routability as a router output. |
| `GET /api/cloud-blocks/refs?id=` | Everything referencing a block (bridges, queue roles, rules, cables) — the delete-confirm preflight. |
| `POST /api/cloud-accounts/auto-create-blocks` | Discover models and create blocks in bulk (non-chat artifacts filtered). |
| `POST /api/cloud-accounts/bridge-port` / `…/bridge-port-delete` | Mint / remove a `kind=service` bridge port that pins one cloud block for an external consumer. |
| `POST /api/app-port` | Mint a router-routed entry port with its own data-plane API key for an external app (`{name}` → `{port, key}`). |
| `GET /api/cloud-upstream-errors?hours=` | Data-plane cloud failures aggregated per account → (model, code) from proxy event logs. |
| `POST /api/cloud-api-health/retry` | Reset a circuit-broken provider endpoint and retry it now. |
| `GET /api/model-pricing` | LiteLLM price table (24 h cache). |
| `GET/POST /api/local-pricing`, `GET/POST /api/api-pricing` | Manual $/1M-token prices for local models / per-model API overrides. |

## Auth & fleet security

Sign-in is OFF until the first account exists (see [security.md](security.md)).
Once on, every route except the login page, the auth bootstrap endpoints and
the machine endpoints (scout heartbeats, `/metrics` — those switch to the
fleet token) requires the `caravan_session` cookie.

| Method & path | Purpose |
|---|---|
| `GET /login` | Sign-in page (all other pages redirect here when auth is on). |
| `POST /api/auth/setup` | Create the FIRST account (only works while no users exist) — turns the guard on. |
| `POST /api/auth/login` / `POST /api/auth/logout` | Session cookie issue / revoke (rate-limited per IP). |
| `GET /api/auth/me` | Current session's user/role (the UI header). |
| `GET /api/auth/overview` | Users + live sessions + fleet-token status (Security panel). |
| `POST /api/auth/users` | Create/delete accounts, set passwords. |
| `POST /api/auth/sessions/revoke` | Revoke other sessions. |
| `POST /api/auth/fleet-token` | Rotate the machine token scouts use. |
| `GET /metrics` | Prometheus exposition (routes, queues, cells, GPUs, models disk); wants the fleet token when auth is on. |

## Pages & static

| Method & path | Purpose |
|---|---|
| `GET /`, `/index.html` | Topology board UI. |
| `GET /kanban`, `/router` | Standalone router canvas (`?id=router:<id>`). |
| `GET /hf` | HuggingFace browser page. |
| `GET /models` | Models-disk page: GGUF tree, size rollups, unreferenced-file cleanup. |
| `GET /system` | System page: Controller / llama.cpp / Security / Diagnostics tabs. |
| `GET /js/<name>.js`, `/css/<name>.css` | ES modules / stylesheets (traversal-safe name class, ETag + no-cache). |
| `GET /hf.js`, `/favicon.svg`, `/favicon.ico` | Remaining whitelisted static files. |

## Proxy daemon surface (per route port)

Each enabled route binds its own port (`:8101+`). The daemon is not a REST
API — it forwards whatever OpenAI-compatible traffic arrives:

| Method & path | Purpose |
|---|---|
| `GET /v1/models` | Fast path: answered from the upstream's cached model list. |
| anything else | Proxied through the full lifecycle (queue → route → upstream → relay). See [backend-proxy.md](backend-proxy.md#request-lifecycle). |
