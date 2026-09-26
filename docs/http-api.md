# HTTP API

The admin server (`:7990`) dispatches from the route tables in
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

The controller's own single server — `/api/action` (start/stop its service), `/api/revert`,
`/api/backup`, `/api/backup/delete`, `/api/config/snapshot`, `/api/raw/start-server` and
`/api/system-monitor/client-label` — went with its cells in step 6.9, together with the page parts
that called them.

| Method & path | Purpose |
|---|---|
| `GET /api/state` | Composite dashboard state: parsed launch config, models, service status, field help. Heavy (it runs llama-server and a dozen git/systemctl commands) — pages read it once, on load. |
| `GET /api/project-git` | The controller's own git branch, head and dirty count — what the board's live beat reads every 1.5 s (it read the whole `/api/state` for it until step 6.9). |
| `POST /api/config` | Save the controller's own config `{config}` — its models directory and the defaults a new cell starts from; rewrites `start-server.sh` from it. |
| `POST /api/config-favorites` | Persist the starred launch-form fields (Favorites tab). |
| `POST /api/llama-command-preview` | Build the llama-server command line for a config dict (GUI diff preview). |
| `POST /api/parse-extra-args` | Hoist recognized flags out of a raw `EXTRA_ARGS` string into structured fields. |
| `POST /api/repair/user-service` | Rewrite/repair the `systemd --user` unit for the managed service. |
| `GET /api/llamacpp` | llama.cpp build/version info (`?fetch_remote=1` compares upstream). |
| `POST /api/llamacpp/update` | Pull + rebuild llama.cpp from git (background job). |
| `GET /api/llamacpp/update-status` | Progress/log stream of the running build job. |
| `GET /api/llamacpp/builds` | Archived controller builds (rollback points). |
| `POST /api/llamacpp/restore` | Restore an archived build over the current binary. |
| `GET /api/fleet/vllm?hostId=` | vLLM on a machine with a scout (scout 2.9+): the machines to choose from (`machines: [{id, name, online, scoutVersion, controllerMachine}]`), the machine answered (`hostId` — this controller's own machine when none is named), the version its first vLLM start provisions (`pinnedDefault`) and that scout's `/api/vllm` (version, history, job). A scout older than 2.9.0, an unknown machine and no machines at all answer `ok: false` with the reason, without asking any scout. |
| `POST /api/fleet/vllm/update` · `GET /api/fleet/vllm/update-status?hostId=` | Install another vLLM on that machine (`{hostId, version?}` — empty is the latest release, a version pins it: a rollback) and follow the job. The controller keeps no vLLM venv of its own since its machine's cells run through its scout. |
| `GET /api/controller-info` | System page payload: services, git, python, models-disk numbers. (Its own cell counts went with its cells in step 6.9.) |
| `GET /api/script-preview?host=&port=` | Rendered start.sh preview for a cell (read-only, $HOME-scoped, 64 KB cap). |

## Models & HuggingFace browser

| Method & path | Purpose |
|---|---|
| `GET /api/models` | GGUF catalog (families, sizes, metadata): this disk's files, and the files only a library holds, marked `libraryOnly` with their `store` — their header facts are the ones remembered when a move read the local copy. Never waits for a NAS: the libraries come from their last measurement. |
| `GET /api/models/rows` | The rows `GET /api/state` gives as `models` — the cell editor's picker and the caravan's shelf — with their `stamp`: `{ok, models, stamp}`. What a board fetches when the topology's `modelsStamp` moved. Kept for 5 s. |
| `GET /api/models/download?path=` | Stream a local GGUF file — to the browser, and to a scout provisioning a client cell (fleet token). 404 if the controller does not have it: it never fetches a model on a client's behalf. |
| `GET /api/cell-assets` | Manifest of the cell servers this controller owns (`cells/`): sha256, size and exec bit per file, plus which files each runner needs. Fleet token. |
| `GET /api/cell-assets/file?name=` | One cell server or launcher, raw. Explicit allowlist — a file dropped into `cells/` is not served until it is listed in `cell_assets.py`. Fleet token. |
| `GET /api/models/disk` | Free and total space of the models directory's disk (`freeGb`, `totalGb`) — the `/hf` page's headroom badge. `/models` takes each place's room from `/api/model-stores`. |
| `GET /api/models/unused` | GGUFs no cell/config references (multi-part groups counted as one). |
| `POST /api/models/gc` | Delete selected unreferenced model files (server re-checks references). |
| `GET /api/model-stores[?force=1]` | Every model store — this controller's directory and the libraries — with its state in a word and, when it is really there, its numbers. A store that is NOT `ok` also carries `mount`: `{source, type, host, answers, inFstab}` — what this host has mounted at that path, whether the machine it comes from answers a knock on its port, and whether `/etc/fstab` names the mount point. Read from this host's own files; the path itself is never touched. Looks inside from a child process with an 8 s deadline; `force` measures again instead of reusing the last 15 s. |
| `POST /api/model-stores/add` | `{path, name, force}` — add a library; it is known by the mark in its root. A refusal is `{ok:false, error, code}`; a bare directory (`not-a-mount`) is refused unless `force`. |
| `POST /api/model-stores/remove` | `{id}` — take a library off the list; its files and its mark stay. |
| `POST /api/model-stores/repath` | `{id, path}` — point a library at another path on this host (the share moved, or its mount point did). A library is its mark, not its path: the new folder must carry the same one, else `other-library`; the rest of the refusals are Add's (`not-absolute`, `duplicate`, `nested`, `not-a-mount`, `unreachable`). |
| `POST /api/model-stores/move` | `{files, to, from}` — move unused models from one store to another: this disk into a library, a library back onto this disk, one library into another. An item is a GGUF (a picked part brings its whole group) or a whole model folder — a whisper cache, a checkpoint — which travels as one item, links planted back as links. `from` is the store they sit in now (the models disk when omitted), `to` where they go. Checked before a byte moves; a refusal is `{ok:false, error, code}` (`in-use`, `busy`, `no-room`, `target-<state>`…). The job copies, reads the copy back and compares sha256, and only then deletes the local copy; a folder is deleted only once every file in it is proven, and never if something appeared inside meanwhile (`folder-changed`). |
| `GET /api/model-stores/moves` | The move jobs, newest first, from memory: status (`queued`, `running`, `waiting` with the reason, `done`, `failed`, `cancelled`), totals and a row per file (phase, bytes, why it stayed, and for a checked copy `removeIn` — the seconds until the copy here is deleted, counted by the server). |
| `POST /api/model-stores/moves/cancel` | `{id}` — stop a move between blocks: the file in progress stays here, its unfinished copy in the library is deleted. A move still in line ends at once. |
| `GET /api/model-stores/files[?force=1]` | What each library holds — its GGUF files and its model folders (a whisper cache, a checkpoint, marked with `kind`), as path from the library's root, size, age in days, capped at 5000 with `more`, for the tree on `/models`. From the same look that counts them for the panel; a library that is not there names no files and says its state. |
| `GET /api/hf/model-tree?repo=` | Quantizations/siblings of a repo via the HF model-tree filter. |
| `GET /api/hf/search?q=&limit=` | HuggingFace model search (GGUF, by downloads, `limit` held to 5–100). An exact `author/repo` skips the search and answers that repository's own record; when Hugging Face cannot give it, the record is `{id}` alone — no counts, never zeros. |
| `GET /api/hf/files?repo=` | GGUF file listing of a repo (classified by quant/type). |
| `GET /api/hf/local-check?repo=` | What we have of the repo: `localNames`/`localFiles` on this disk (size, mtime), and `libraryFiles` — the same folder in every usable library, by name, one `{store, size, mtime}` per library. Libraries come from their last look (model_locator.py), never from the mount. |
| `DELETE /api/hf/local-file?repo=&name=` | Delete a local copy of a repo file. |
| `POST /api/hf/download` | Start a background download job `{repo, files[], replace?}`; answers `{jobId}`. A file whose destination already holds a file is written over only with `replace: true` — without it the answer is `{ok: false, code: "exists", files: [...]}` and nothing starts (the `/hf` page asks, then resends). A leftover `.part` does not count: it is where a download resumes. |
| `GET /api/hf/download/status?job=` | One job's progress. |
| `GET /api/hf/download/jobs` | All running/errored jobs (page-reload recovery), plus partials on disk no job owns as `status: "interrupted"` rows. A cancelled job is not listed: its partial is. |
| `POST /api/hf/download/cancel` | Stop a running job `{jobId}`. The transfer checks the flag before each file and after each MiB; the job ends `status: "cancelled"` (no error, not retried), the bytes already fetched stay as a resumable partial, and a partial with no bytes is removed. `{ok: false}` for a missing id or a job that is unknown or finished. |
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
| `GET /api/system-monitor` | CPU/RAM/disk/net/GPU sample history + the requests in flight by route (`latest.correlatedActivity`, from the proxy's records). `?since=` sends only newer samples. (Until step 6.9 it also carried the controller's own single server: `llamaActivity`, `llamaClients`, `tokens` in a sample, `tokenGenSamples` and `clientLabels` beside them.) `hosts` — the machines whose scout samples them second by second (scout 2.8+): `{hostId: [{t, gpus: [{index, memUsedMiB, memTotalMiB, utilPct, powerW, tempC}], cpuPct, ram}]}`, ten minutes by each scout's own clock, pulled in the background at most once a second while boards read this (HostTelemetry); `?hostsSince=id:t,id:t` names the newest row the board holds of each, and a machine it does not name comes back whole. |
| `POST /api/system-monitor/settings` | Set monitor retention seconds. |
| `GET /api/token-history?client=&range=` | Token-rate history (14 d ring). |
| `GET /api/usage-stats?days=` | Usage & spend aggregation over proxy event logs. |
| `GET /api/proxy-daily-stats?date=` | Per-route request/failure counts for a day. |
| `GET /api/agent-proxy-logs?date=&limit=&event=&port=&route=&client=&errors=&slim=&summary=` | Proxy event log rows, filterable per route. `port` — proxy route port (the stable per-agent id), `route` — label substring, `client` — exact IP, `errors=1` — only failed rows, `slim=1` — drop the bulky queue/active snapshots, `summary=1` — per-port terminal counters `{total, errors, byKind}` instead of rows. See [operations.md](operations.md#request-log-diagnostics-api) for curl recipes. |

## Fleet topology & cells

| Method & path | Purpose |
|---|---|
| `GET /api/topology` | The full fleet tree: hosts (machines with a scout, liveness computed on read), clients (made by hand) and their agents, servers, GPUs, proxies, routers, cloud. A machine's node has `role: "host"`, `ageSeconds` — seconds since its scout's last report (`null` when there was none) — and `scoutVersion`, empty for a 1.x scout. A client row is the operator's record only: a machine's report and liveness are in `hosts`, never merged into it. Every proxy carries `holders: [{hostId, agentId, role}]` — who holds the port, read by the same function `POST /api/topology/agent-proxy-bind` refuses by (one port, one owner, 409); empty when nobody holds it. `hostSuspects` — a row per machine whose scout (2.6+) says a fresh llama.cpp build crashes its cells: the verdict (`crashes15m`, `builtAt`, `currentCommit`, `firstSeenAt`, `lastSeenAt`, `restoreCandidate`) with `hostId`, `name` and the `llamaBinaryVersion` it runs. A scout's remote cell with a crash note carries its last log lines in `crash.tail` (2.6+), and while its watchdog brings it back, `status.lastError: {kind, detail, tail}` — what the attempt before died of. `modelsStamp` — 16 characters naming the controller's models list (`GET /api/models/rows`): a file coming, going, growing or rewritten changes it; `GET /api/state` carries the stamp of the list it gives. |
| `POST /api/topology/client-heartbeat` | Scout heartbeat: the machine only — GPUs, compute apps, CPU/RAM, llama nodes, build versions. Replaces the machine's host record (`topology.hosts`) and touches no client; agent fields from old scouts are not read. Replies `{ok, host}`. |
| `POST /api/topology/assignments` | Store client→router assignments (cable drops). |
| `POST /api/topology/agent-proxy-bind` | Point an agent at a proxy port for one role: `{hostId, agentId, port, role: primary\|fallback}`. 404 for a client or an agent the operator's record does not have, 400 without a port or for a port with no route, 409 when another agent holds the port. |
| `POST /api/topology/client-alias` | Rename a client in the UI. |
| `POST /api/topology/client/delete` | Delete a client — the operator's record — with its agents and assignment row. The machine's host record, if one shares the id, is not touched. |
| `POST /api/topology/scout/connect` | Add a machine's scout: `{address, port?}` (port 8092 by default; a scheme or a port inside the address is understood) → reads the scout's open `/api/pairing`, hands it the controller's address (127.0.0.1 for a scout on this machine, else `LLAMA_TOPOLOGY_SERVER_IP` or the interface facing it) and the fleet token, and returns once its first heartbeat arrived: `{ok, hostId, name, scoutVersion, scoutUrl, controllerUrl}`. 400 for an address or port that is none, 409 for a scout older than 2.0 or paired with another controller, 502 when nothing answers, something else answers, or the scout cannot reach the controller back — each with what to do. Adding a scout that is here already is the connection test. |
| `POST /api/topology/scout/disconnect` | Let go of a machine (`{hostId}` → `{ok, hostId, unpaired}`): asks its scout to forget the controller (`/api/unpair`), then forgets the host record. A silent scout's machine is only forgotten (`unpaired: false`) and returns with its next heartbeat if it still holds the address; a scout that refuses (502) keeps its record. Clients and cells are not touched; 404 for an unknown id. |
| `POST /api/topology/host/move-cells` | Move every cell configured on one machine to another: `{from, to}` → `{ok, from, to, ports}`. For a machine that comes back under another name — a scout names itself after its machine, so a reinstalled or renamed machine reports a new id. Ports are global, so routes and kanban edges (`srv:<port>`) stay as they are; each cell keeps its config, model, label, note and command history. 400 when a name is missing, both are the same, or either is the controller (its own cells never move); 404 when the old machine has no cells; 409 when the new one already holds one of those ports — nothing is moved then. |
| `POST /api/topology/client/agent/delete` | Remove one agent: its record and its assignment row. Its ports stay (`freedPorts` names those no agent claims now). The last agent takes its client with it (`clientRemoved: true`). |
| `GET /api/topology/client-monitor?hostId=&kind=` | Proxy a client's monitor snapshot through its route-agent. |
| `GET /api/topology/client-llama/configs?hostId=` | Remote llama-node config list. |
| `POST /api/topology/client-llama/configs/save` / `…/delete` | Manage remote configs. |
| `GET /api/topology/client-llama/list-cache?hostId=` | Remote model cache contents. |
| `POST /api/topology/client-llama/start` / `…/stop` | Start/stop a llama node on a client via its route-agent. |
| `POST /api/topology/client-llama/purge-cache` | Clear a client's model cache. |
| `POST /api/topology/server-slot/add` / `…/delete` | Declare/remove a persistent host:port server slot. |
| `POST /api/topology/server-cell/action` | Cell lifecycle `{action: start\|stop\|restart\|enable\|disable\|delete}`, through the scout of the cell's machine (the controller runs no cells; a cell on its id is refused, 400). `enable`/`disable` is autostart — on a scout's cell, 2.4+, it hands the scout the cell's start request, which it keeps and starts when its machine boots. A model in a library is read where it is: the scout gets its start line with the library path, built at every start from where the files are at that moment. (`modelFrom`, the controller's own cells' "disk or library" answer, went with those cells in step 6.9.) A cell in an engine (Ollama, LM Studio) whose model would not fit into the free memory of the machine's cards is not started: `start` and `restart` answer `{ok: false, hostId, port, action, short: {model, needBytes, freeBytes, basis}}` with status 200 — `basis: "weights"`, the model's file alone, at least that much — and the same request with `force: true` (a JSON true only) starts anyway (2026-09-26). |
| `POST /api/topology/server-cell/save-config` | Save a cell's config without starting it. A cell that does not exist yet is made — the caravan shelf's «+» opens the editor on a port nobody reserved — and its port is checked as a reserve checks it (409 when a cell, a route or an exclusion has it). A scout's cell with autostart on gets the new start request at once, or the next boot would bring back the old one; the answer carries `autostart: {ok, error?}` then. |
| `POST /api/topology/server-cell/schedule` | Save a cell's start/stop window (`{enabled, start, stop, days[]}`). |
| `POST /api/topology/server-cell/reassign-port` | Move a parked cell to a free port (fleet-wide check; router refs remapped `srv:old→srv:new`). |
| `POST /api/topology/server-slot/note` | Save the free-text note on a cell card. |
| `POST /api/fleet/llama-update` / `…/llama-restore` | Build/update llama.cpp on a client host via its scout / restore an archived client build. |
| `POST /api/fleet/llama-suspect-dismiss` | `{hostId}` — hide a machine's "fresh build, crashing cells" banner row for its current build; its scout remembers (scout 2.6+). The host record says "not suspect" at once. |
| `GET /api/fleet/llama-update-status?hostId=` / `GET /api/fleet/llama-builds?hostId=` | Client build-job progress / archived builds on a client. |
| `GET /api/queue-thresholds` / `POST /api/queue-thresholds/recalc` | Computed queue wait thresholds / force resync from OpenClaw. |

## Agent proxies & routers

| Method & path | Purpose |
|---|---|
| `GET /api/agent-proxies/raw` | Raw `agent-proxies.json` text (viewer modal). |
| `POST /api/agent-proxies/config` | Save the full routes list. |
| `POST /api/agent-proxies/policy` | Save the global queue/preemption policy. |
| `POST /api/agent-proxies/route-policy` | Patch one route's policy overrides. |
| `POST /api/agent-proxies/routers` (alias `…/switchboards`) | Save routers incl. the kanban graph (nodes/edges). |
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
| `POST /api/engines/pull` | `{hostId, kind, model}` — download a model into an engine next to a machine's cells, through its scout (2.17+): answered at once, the engine carrying `downloading` {model, since, doneBytes, totalBytes} on the next reads, `downloadError` in the engine's words if it failed. One download per engine at a time. |
| `POST /api/engines/start` · `POST /api/engines/stop` | `{hostId, kind}` — start or stop the server of an engine next to a machine's cells through its scout (2.16+): only what the engine's `controls` offer — a stop for a server the scout's user runs, a start for a stopped one (`state: "stopped"`). The scout answers at once and waits for the server on its own thread; the engines it answers with go into the host record, so the engine shows as starting or stopping on the next read (`serverAction`), and what it refused stays as `serverError`. Refused before the scout for an unknown action, a machine with no report, an engine the machine does not report. Answers `{ok, hostId, kind, op, topology}`. |
| `POST /api/engines/unload` · `POST /api/engines/delete` | `{hostId, kind, model}` — unload a model an engine next to a machine's cells holds, or (`delete`, scout 2.17+) remove an Ollama model's files — not a loaded one — through its scout (2.14+). The scout answers at once and acts on its own thread; the engines it answers with go into the host record, so the model shows as being acted on at the next read. Refused before the scout for an unknown action, a machine with no report, an engine the machine does not report; the scout's own refusal comes back in its words. Answers `{ok, hostId, kind, model, op, topology}`. There is no load (removed 2026-09-26): a cell in the engine loads its model when it starts. |
| `POST /api/engine-outputs/expose` | `{hostId, kind, model, exposed}` — a model of an engine next to a machine's cells (Ollama, LM Studio, as its scout reports it) becomes a router output `eng:<hash>`, or stops being one. Refuses a model the machine's report does not list (404) and a model the engine runs on its own cloud (400). Answers `{ok, id, exposed, topology}`. |
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
| `GET /login` | Sign-in page (all other pages redirect here when auth is on). On a fresh controller with no accounts it 302s to `/setup`. |
| `GET /setup` | First-run wizard: create the first account, shown the fleet token once. 302s to `/login` once auth is enabled. |
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
| `GET /board` | Topology board UI. `/` and `/index.html` 302 here. |
| `GET /kanban` | Standalone router canvas (`?id=router:<id>`). `/router` 302s here. |
| `GET /hf` | HuggingFace browser page. |
| `GET /models` | Models-disk page: GGUF tree, size rollups, unreferenced-file cleanup. |
| `GET /system` | System page: Controller / llama.cpp / Security / Diagnostics tabs. |
| `GET /js/<name>.js`, `/css/<name>.css` | ES modules / stylesheets (traversal-safe name class, ETag + no-cache). |
| `GET /favicon.svg`, `/favicon.ico` | Remaining whitelisted static files. |

## Proxy daemon surface (per route port)

Each enabled route binds its own port (`CARAVAN_PROXY_BASE_PORT`, default `:23001+`; this fleet's historical routes sit at `:8101+`). The daemon is not a REST
API — it forwards whatever OpenAI-compatible traffic arrives:

| Method & path | Purpose |
|---|---|
| `GET /v1/models` | Fast path: answered from the upstream's cached model list. |
| anything else | Proxied through the full lifecycle (queue → route → upstream → relay). See [backend-proxy.md](backend-proxy.md#request-lifecycle). |
