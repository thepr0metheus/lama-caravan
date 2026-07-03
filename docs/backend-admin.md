# Admin server module reference (`caravan/admin/`)

The admin server is the control plane of lama-caravan: a single stdlib-only Python process serving
the dashboard UI and the whole `/api/*` surface — launch-config editing for the controller's
llama-server and its server cells, GGUF catalog and HuggingFace downloads, systemd control, fleet
clients (route-agents on other hosts), the proxy/router configuration the proxy daemon consumes,
cloud provider accounts, and the 1-second system monitor. It was refactored from a 9,438-line
`app.py` monolith into the modules below; `app.py` remains as a 20-line launcher. Entry chain:
`app.py` → `caravan/admin/main.py:main()` → background threads (monitor sampler, OpenClaw threshold
refresh, one-shot bootstraps) + a `ThreadingHTTPServer` serving `routes.Handler` on
`LLAMACPP_ADMIN_HOST:PORT` (default `0.0.0.0:8090`).

Import layering is strict and cycle-free. Each layer may import only from layers to its left:

```
common ← paths ← state ← domain modules ← aggregators (topology, status) ← ops (proxy_ops, cell_ops) ← routes ← main
```

Nothing imports the launchers (`app.py`, `agent-proxies.py`); they import `main` and re-export a few
symbols for `scripts/test_queue_node.py`.

Two rules govern shared state. (1) **Rebind co-location**: a module global that is ever *rebound*
(`_token_history`, `_frontier_cache`, `monitor_last_*`, …) lives in the same module as every
function that rebinds it; other modules import *functions* over that state, never the variable (a
from-import would freeze the old object). (2) **Mutate in place**: never-rebound mutable objects —
`admin_state`, locks, deques, `TtlCache`s, history rings — are imported by name and mutated in
place, never reassigned.

## Shared helpers (`caravan/common`)

| Module | Purpose | Key exports |
|---|---|---|
| `errors` | Shared exception type; carries an HTTP status (default 400). Route dispatch maps it to a JSON error response. | `AppError(message, status)` |
| `procs` | Subprocess wrappers that never raise — always return `{ok, code, stdout, stderr}` (exceptions become `code:-1`). | `run(cmd, timeout, env)`, `run_in(..., cwd)` |
| `fsio` | File I/O. `atomic_write_text` writes to a per-process/thread temp name (`name.<pid>.<tid>.tmp`) then `os.replace`, so readers never see a partial file and concurrent writers never clobber each other's temp. Optional `chmod`/`mkdir`. | `read_text`, `atomic_write_text` |
| `fetch` | urllib HTTP helpers. `fetch_json` returns `{ok:False, error}` on failure, `fetch_text` returns an `"ERROR: …"` string; `post_json` is the one that raises. | `fetch_json`, `fetch_text`, `post_json` |
| `jsonx` | JSON encoding for responders. `json_bytes` tries `allow_nan=False` first; only on `ValueError` does it walk the tree replacing inf/nan with `None` (browser `JSON.parse` rejects them). | `json_bytes` |
| `ttl_cache` | `(timestamp, value)` TTL cache with an internal lock. `get()` returns the `MISS` sentinel so falsy values are cacheable. No single-flight by design: concurrent misses may both fetch, same as the pre-refactor call sites. | `TtlCache`, `MISS` |

## `paths.py`

Environment-driven constants and every repo-relative path, all anchored to `PROJECT_ROOT =
Path(__file__).resolve().parents[2]` (the repo root, where `app.py` lives). No other module may
derive paths from its own `__file__` — it would point into `caravan/`. Covers the llama.cpp install
(`LLAMA_HOME`, `START_SCRIPT`, `DEFAULT_MODELS_DIR`), the two service names, cell/backup dirs
(`var/server-cells`, `var/server-backups`), the shared JSON files (`agent-proxies.json`,
`agent-proxy-state.json`, `cloud-providers.json`, `token-history.json`), per-user state
(`admin.json`, monitor history, incident log), secrets (`provider-secrets.json` and the OpenClaw
config cache — outside the repo, 0600), the OpenClaw config-manager URLs (OPENCLAW_CONFIG_MANAGERS), the
fleet-registry URL, and tunables (monitor interval/retention, token-history caps,
`SERVER_CELL_BASE_PORT` 8001).
Owns: — (constants only; the single source of path truth).
Key functions: — (no functions; import the constants).

## `state.py`

Persistent admin-panel state (`admin.json`), the single shared mutable store. `admin_state` is
created exactly once at import (loaded from disk, defaults seeded: monitor retention, topology
sub-maps, `localPricing`/`apiPricing`, `hfToken`, `hfFavorites`, `favFields`); every other module
imports the object, mutates it in place, then calls `save_admin_state()` — never rebinds it.
`topology_store()` returns `admin_state["topology"]` after ensuring its sub-keys exist (`clients`,
`assignments`, `clientAliases`, `layout`, `serverSlots` — the persistent host:port declarations that
keep proxy cables attached across restarts — and `deletedAgents` tombstones).
Owns: `admin_state` (in-memory), `admin.json` on disk.
Key functions: `load_admin_state` (tolerant read), `save_admin_state` (atomic write of the live
object), `topology_store` (defaults-ensured topology sub-store).

## `config_builder.py`

The launch-config contract. `CONFIG_FIELDS` (~90 keys, including the command-cell keys
`CELL_KIND`/`COMMAND`/`HEALTH_PATH`/`ENV`/`WORKDIR`) and the `# BEGIN/END LLAMA CONFIG` marker lines
are a contract with `scripts/start-server.sh` — never rename them here alone. `build_llama_args` is
the **single config→CLI source of truth**: the local start-server.sh, server cells (same generator),
remote clients (args shipped with `{{MODEL_PATH}}`/`{{MMPROJ_PATH}}`/`{{SPEC_PATH}}` placeholders
the route-agent substitutes after download), and the GUI preview (`POST /api/llama-command-preview`)
all funnel through it — adding a flag means editing it and nothing else. Safety nets live here too:
embeddings mode drops speculative decoding and `--jinja`; `ENABLE_THINKING` merges into
`--chat-template-kwargs`. `parse_extra_args` is the inverse — it hoists recognized raw flags out of
`EXTRA_ARGS` into their form fields.
Owns: `CONFIG_FIELDS`/`FIELD_HELP` and the config-block markers.
Key functions: `parse_config` (read start-server.sh), `parse_config_from_text`/`split_config`,
`build_config_block` (validates MODEL_FILE/PORT/numerics), `build_llama_args`,
`build_remote_llama_args` (placeholders, no host-local flags), `build_local_llama_command` (absolute
paths + binary), `parse_extra_args`, `is_command_cell`, `models_dir_from_config`.

## `launch.py`

Renders launch artifacts from configs. `render_launch_script` produces a complete start script: env
header, the config block (so the GUI can reload values via `parse_config`), file-existence guards,
and a generated `# BEGIN/END LLAMA COMMAND` `exec llama-server …` block — regenerated from the
config so block and command never drift. CPU-only configs (`N_GPU_LAYERS=0`) export
`CUDA_VISIBLE_DEVICES=""` because a CUDA build still initializes the backend at `-ngl 0` and can
abort on a full GPU. `render_command_cell_script` does the same for command cells (arbitrary managed
process, `exec`'d so systemd/the agent tracks the real PID; `ENV` rendered as exports, optional `cd
WORKDIR`). `write_server_cell_artifacts` writes `var/server-cells/<port>/start.sh` + `cell.json`
(temp+replace). Snapshots are manual-only (`snapshot_config` — named
`start-server.sh.bak.<stamp>-<name>` files, rendered from the live form config when given so
cell-specific values are captured); `save_config` rewrites the whole start-server.sh with no
auto-backup.
Owns: the `# BEGIN/END LLAMA COMMAND` markers; `var/server-cells/<port>/` contents.
Key functions: `render_launch_script`, `render_command_cell_script`, `write_server_cell_artifacts`,
`server_cell_dir`, `snapshot_config`, `save_config`.

## `models.py`

GGUF model catalog. `read_gguf_metadata` parses the binary GGUF (v2+) header directly for a wanted
key set (architecture, block/context/embedding sizes, attention heads, `pooling_type`);
`extract_runtime_meta` normalizes it (pooling read presence-aware since 0 is valid). `list_models`
scans the models dir, classifies files (model / mmproj / draft; vocab skipped), suggests
same-directory companions (plus the sibling `default/` folder HF downloads land in), detects the
family (`gemma-4-…` → `gemma4`) and applies `FAMILY_DEFAULTS`; embedding models (name hints or a
GGUF pooling type) get `embedding_family_defaults` instead — `--embeddings`, the right `--pooling`,
chat-only flags cleared, CTX right-sized to the trained context. `serve_model_file` streams a GGUF
over HTTP (traversal-guarded) — this is what client route-agents download models from.
Owns: `FAMILY_DEFAULTS`.
Key functions: `read_gguf_metadata`, `extract_runtime_meta`, `detect_family`,
`embedding_family_defaults`, `list_models`, `list_chat_templates`, `serve_model_file` (GET
`/api/models/download`), `list_gguf_models` (grouped listing for remote start).

## `systemd_ctl.py`

`systemctl --user` control. `user_systemd_env` supplies `XDG_RUNTIME_DIR` and the session bus
address so the admin (itself a service) can talk to the user manager. Handles both the legacy single
service (`llamacpp-current.service`) and per-port cell services (`lama-cell@<port>.service`):
`ensure_cell_service_template` installs/updates the unit from `systemd/lama-cell@.service` into
`~/.config/systemd/user` (+ daemon-reload) and `cell_service_action` additionally opens the port in
ufw before start/restart/enable. `user_service_diagnostics` produces the bus/service/HTTP checklist
shown in the UI.
Owns: the installed `lama-cell@.service` user unit copy.
Key functions: `systemctl`, `service_status`, `cell_service_name`, `cell_service_status`,
`cell_service_action`, `ensure_cell_service_template`, `user_service_diagnostics`, `logs` (journal
tail), `read_cmdline`, `repair_user_service` (daemon-reload + restart).

## `llama_metrics.py`

llama-server telemetry primitives. `parse_llamacpp_metrics` extracts a fixed set from the Prometheus
text: live gauges (requests processing/deferred, KV usage, lifetime-average t/s) plus the cumulative
token/second counters — those advance only at request completion, which is what per-request
throughput is later derived from. `runtime_metrics_sample` scrapes `127.0.0.1:<port>/metrics` (3s
timeout; a failed scrape is `ok:False`, never a fake zero). `runtime_phase` folds systemd state +
`/health` + `/props` + `/v1/models` into one phase: unknown / failed / stopped / running / loading
(503 while the model loads) / starting.
Owns: —.
Key functions: `parse_llamacpp_metrics`, `runtime_metrics_sample`, `runtime_phase`.

## `hf.py`

HuggingFace REST browser over the public API, with a 5-minute `TtlCache` and optional bearer auth
from `admin_state["hfToken"]` (token participates in the cache key). `hf_search` returns
GGUF-filtered repos sorted by downloads with modality hints (pipeline_tag/tags) straight from the
search response; a query containing `/` is treated as a direct repo id. `hf_list_files` lists a repo
tree, classifying `.gguf` files (model/mmproj/mtp/vocab) and extracting the quant from the filename.
`hf_local_check` / `hf_local_delete` inspect and remove local copies under
`<models>/<model>/<author>/…` (delete is traversal-guarded and prunes emptied directories).
Owns: `_hf_cache` (TtlCache 300s).
Key functions: `hf_search`, `hf_list_files`, `hf_local_check`, `hf_local_delete`, `_hf_request`
(shared by benchmarks).

## `downloads.py`

Background HuggingFace GGUF downloads. `start_hf_download` registers a job (id, repo, per-file and
total byte counters) and spawns one daemon thread per job; the thread streams each file in 1 MiB
chunks into `<models>/<destDir>/`, updating progress under the jobs lock. A silently truncated
stream (HF CDN closing early) is detected by byte count, the partial file deleted, and the job
marked `error` — so a short GGUF is never served as a valid model. Finished job records are pruned
300s after completion by the `/api/hf/download/jobs` handler.
Owns: `_download_jobs` + `_download_jobs_lock`; job worker threads.
Key functions: `start_hf_download` (returns job id; status polled via `/api/hf/download/status`).

## `benchmarks.py`

Model quality metadata for the HF browser. Three sources: Artificial Analysis Intelligence Index
(regex-scraped from score/detailsUrl pairs embedded in AA model pages — one page carries ~a dozen
models; 1h HTML cache plus a persistent slug→score map with a negative cache), the Open LLM
Leaderboard v2 (the whole `open-llm-leaderboard/contents` dataset paged through datasets-server by a
**lazy background thread** — `_ensure_llm_lb` starts it on first use, 24h TTL), and arena ELO.
`hf_get_reference_models` serves a curated frontier-model list: hardcoded scores instantly, live AA
refresh only on explicit force (12h cache). `hf_get_benchmarks` combines the sources per repo
(inferring base models for GGUF repos) and persists results as JSON under `.bench_cache/`.
Owns: `_bench_url_cache`, `_aa_html_cache`, the AA slug map + negative cache, `_frontier_cache`
(rebound here), `_llm_lb` index + loader thread, `.bench_cache/` files.
Key functions: `hf_get_benchmarks`, `hf_get_aa_scores`, `hf_get_reference_models`,
`hf_bench_search`, `_ensure_llm_lb`/`_llm_lb_status` (used by the status route).

## `terminal.py`

Pure ANSI terminal-frame renderer used for btop snapshots in the monitor panel. Emulates a rows×cols
screen: cursor addressing (`CSI H/f`), screen/line erase, SGR reset/bold/39 and 24-bit foreground
colors; everything else is dropped. Produces either HTML spans or plain text of the final frame.
Owns: —.
Key functions: `terminal_frame_to_html`, `terminal_frame_to_text`.

## `router_dsl.py`

Router/graph normalization — pure validation, no file I/O. Defines the default router
(`router:default`) that always exists and the default output (the controller's llama-server at
`127.0.0.1:8080`). `normalize_router` validates outputs (llama or cloud; cloud outputs carry
`accountId` and have unlimited concurrency), legacy rules (`default`, `schedule`, `bySource`,
`failover` chain, fleet-wide `audioOutput`/`embeddingsOutput` short-circuits) and the optional
n8n-style DAG (node types byModel / schedule / weighted / roundRobin / failover / queue /
requestType; edges reference `in:<proxy>` / `rule:<node>` / `out:<output>`, with port-keyed
`out:srv:<port>` edges kept even while the server is offline). Garbage in a graph is dropped, never
raised — a malformed graph degrades to legacy rules. Router `inputs` are never trusted from disk;
they are derived from the routes.
Owns: `DEFAULT_ROUTER_ID`, `ROUTER_NODE_TYPES`.
Key functions: `normalize_router`, `normalize_router_output`, `normalize_router_graph`,
`normalize_schedule_rule`, `normalize_by_source_rule`, `normalize_agent_proxy_route`,
`normalize_agent_proxy_policy`, `recompute_cloud_fallback_eligibility` (keeps ↑☁ flags consistent
with graph connections).

## `proxies_config.py`

`agent-proxies.json` I/O and mutation — routes, routers, policy. The admin **owns** this file; the
proxy daemon only reads it (by mtime, ~2s). Every write funnels through `write_agent_proxy_payload`,
the single choke point: it recomputes cloud-fallback eligibility, re-normalizes routers against the
routes, and enforces graph protection — whenever the on-disk file has router-graph nodes it
snapshots an autobackup (`agent-proxies.json.bak-graph-<stamp>`) before every write, and if the
incoming payload would lose a non-empty graph it restores the old graph into the new payload. Reads
migrate the legacy pre-rename schema (`switchboards`/`sb:default` → routers) idempotently.
`sync_router_outputs` auto-derives every router's outputs: one `srv:<port>` per live local llama
server + one `cb:<blockId>` per **exposed** cloud block (with a one-time migration from legacy
`cloud:<accountId>` outputs), keeping `rules.default` pointed at a local server.
`save_agent_proxy_config` validates + dedupes routes by port, writes, and restarts the proxy
service; `set_routers` and the policy setters write without restart (the daemon re-reads live).
Owns: `agent-proxies.json` and its `.bak-graph-*` autobackups; `DEFAULT_AGENT_PROXY_ROUTES`.
Key functions: `read_agent_proxy_payload`, `write_agent_proxy_payload`, `load_agent_proxy_config`,
`save_agent_proxy_config`, `normalize_routers` (default router always exists, orphan routes
re-pointed — `""` stays deliberately unassigned, inputs derived), `sync_router_outputs`,
`set_agent_proxy_policy`, `set_agent_proxy_route_policy`
(label/mode/priority/preemptible/upstream/routerId/threshold overrides), `set_routers`.

## `cloud.py`

Cloud provider data layer — pure data, no OAuth flows and no router logic. Two stores: accounts +
model-blocks in `cloud-providers.json` (with migration from the legacy flat `providers[]` shape),
and credentials in `provider-secrets.json` written 0600. `CLOUD_PROVIDER_PRESETS` defines the known
account types (openai-subscription with its PKCE OAuth config, openai, ollama, anthropic,
openrouter, custom) including auth header/prefix and test path. `account_auth_headers` builds
request headers from either an API key or the stored OAuth access token. Blocks carry `exposed`,
which is what turns them into router outputs.
Owns: `cloud-providers.json`, `provider-secrets.json`, `CLOUD_PROVIDER_PRESETS`.
Key functions: `load_cloud_data`/`save_cloud_data`, `load_provider_secrets`/`save_provider_secrets`,
`account_secret_entry`, `upsert_cloud_account`/`upsert_cloud_block` + deletes,
`set_cloud_block_exposed`, `account_auth_headers`, `account_credential_summary`,
`cloud_accounts_state`/`cloud_blocks_state` (secret-free views for the UI).

## `token_history.py`

Token-rate history (`token-history.json`) and controller-side TPS counters. `_token_history` and the
controller counters are rebound here — every rebinding function stays in this module.
`record_token_history` appends one entry per **completed** proxy request from llama.cpp's exact
per-request `timings` on the proxy's recent items, attributed by proxy port, deduped by request id,
trimmed to 14 days / 12,000 entries on save — the authoritative per-request source, no
time-correlation guesswork. `controller_token_metrics` scrapes every controller llama port
(skynet-tagged slots + the legacy PORT) and sums the gauges; since llama.cpp's `*_seconds` gauges
hold their last value while idle, "generating right now" is detected by cumulative-counter deltas,
which also yield the finished request's real size, duration and Δtokens/Δsec throughput.
`record_controller_gen_tps` keeps the last 600 completed-request points for the Token Speed chart
(idle ticks add nothing — no plateau).
Owns: `_token_history` (+lock), `_controller_token_counters`, `_controller_gen_tps` (+lock),
`token-history.json`.
Key functions: `load_token_history`, `save_token_history`, `record_token_history`,
`token_history_query`, `controller_llama_ports`, `controller_token_metrics`,
`record_controller_gen_tps`, `controller_gen_tps_samples`.

## `proxy_stats.py`

Read-only views over the **proxy daemon's** artifacts: `agent-proxy-state.json` and
`logs/proxy-events/*.jsonl`. The admin never writes these — the proxy owns them.
`agent_proxy_sample` loads the live state file; `summarize_proxy_item` normalizes an active/recent
request record (upstream host/port recovery, usage tokens, phase) for the dashboard.
`load_agent_proxy_logs` reads one date's JSONL (filterable, capped at 2000 rows);
`proxy_daily_stats` folds a day's `received`/`blocked`/`finished` events into per-route
total/failed/paused counts (paused = blocked by route mode, not a real failure). `nearest_event`
matches journal timing/context events to requests within ±20s.
Owns: — (reader only).
Key functions: `agent_proxy_sample`, `summarize_proxy_item`, `proxy_usage_tokens`,
`proxy_item_timestamp`, `requests_by_client`, `list_agent_proxy_log_dates`, `load_agent_proxy_logs`,
`proxy_daily_stats`, `iso_seconds`, `nearest_event`.

## `monitoring.py`

The local system monitor. `monitor_sampler_loop` — a daemon thread started by `main()` — collects
one sample per second (`MONITOR_SAMPLE_INTERVAL`): CPU from `/proc/stat` deltas, loadavg, GPU
(`nvidia-smi`), connected llama clients (`ss`), llama activity (journal parse + `/slots`, cached
3s), the proxy state file and config, controller token metrics (recording per-request TPS points and
token history as a side effect), memory, disk/net rates, and top processes; `correlate_activity`
then joins active proxy requests to processing llama slots and recent ones to journal timing/context
events. `append_incidents_from_sample` derives incidents (failed / client_disconnected /
upstream_timeout / slow first byte ≥30s / slow request ≥120s, each with a cause) and appends deduped
records to `incident-log.jsonl` (30-day retention). The sample ring is trimmed to the configurable
retention and persisted to `monitor-history.json` at most every 10s, reloaded on startup. Also hosts
the dashboard hardware state, client labels, and on-demand `monitor_snapshot` (nvidia-smi, or a btop
frame rendered via `terminal.py` with a `top` fallback).
Owns: `monitor_history` deque + `monitor_lock`, the rebound `monitor_last_cpu/_disk/_net/ _persist`,
`incident_lock` + `incident_logged_keys`, `llama_activity_cache`, `monitor-history.json`,
`incident-log.jsonl`, `client-labels.json`.
Key functions: `monitor_sampler_loop`, `collect_monitor_sample`, `system_monitor_state` (the
`/api/system-monitor` payload), `correlate_activity`, `append_incidents_from_sample`,
`llama_activity_sample`, `gpu_state`/`cpu_state`/`memory_state`, `runtime_api`, `monitor_snapshot`,
`set_monitor_retention`.

## `openclaw.py`

Sync with the configured OpenClaw config managers. `fetch_openclaw_config_for` pulls an agent
host's config (300s TTL); on failure it keeps serving the last-known-good copy marked `stale`, and
good fetches persist 0600 to a cache file outside the repo (configs can carry provider credentials)
that `load_openclaw_cache` warms at startup. `sync_wait_timeouts_from_openclaw` builds a proxy-port
→ timeoutSeconds map (per-provider timeouts by baseUrl port, falling back to each host's
`agents.defaults` across its topology assignments) and updates `clientTimeoutSeconds` on routes when
changed. `compute_queue_thresholds` turns policy percentages (with per-route overrides) ×
`clientTimeoutSeconds` into per-proxy queue-abort / priority-preempt / cloud-fallback seconds,
cached and mirrored into the file as `computedThresholds` — a readable mirror, not the source of
truth. `_queue_thresholds_refresh_loop` re-syncs both every **6 hours** in a background thread;
`notify_openclaw_config_managers` POSTs the configured model to both managers' auto-apply endpoint
after a service start/restart.
Owns: `_openclaw_config_cache` (+lock), `_queue_thresholds_cache` (+lock), the on-disk OpenClaw
config cache.
Key functions: `fetch_openclaw_config_for`, `openclaw_configs_snapshot`,
`load_openclaw_cache`/`save_openclaw_cache`, `sync_wait_timeouts_from_openclaw`,
`compute_queue_thresholds`, `notify_openclaw_config_managers`, `openclaw_config_manager_state`.

## `oauth.py`

OAuth2 authorization-code + PKCE login for cloud accounts. `start_oauth_login` generates the
verifier/challenge and state, binds a loopback `ThreadingHTTPServer` on the account's preset
redirect port (e.g. 1455 for OpenAI), registers a session (shutting down any previous attempt for
the same account), starts the server thread plus a 300s watchdog thread, and returns the authorize
URL. `_OAuthCallbackHandler` exchanges the callback code, stores tokens (access/refresh/expiry +
email decoded from the id_token) into `provider-secrets.json`, records the result, and shuts the
listener down. `oauth_login_status` is what the UI polls. `refresh_oauth_token` runs the
refresh-token grant (keeping the old refresh token when the response omits one); `cloud_api` calls
it before authenticated requests.
Owns: `_oauth_sessions` + `_oauth_lock`; the transient callback server + watchdog threads.
Key functions: `start_oauth_login`, `oauth_login_status`, `refresh_oauth_token`.

## `cloud_api.py`

Live calls against the provider APIs. `test_account_key` probes the preset test path (401/403 =
rejected; 404/405 counts as validated); `set_account_key` stores a key only after it passes.
`fetch_account_models` handles OpenAI- and Ollama-shaped listings with an OAuth pre-refresh;
`fetch_subscription_models`/`fetch_subscription_usage` talk to the ChatGPT backend for subscription
accounts; `fetch_account_costs` and `fetch_openrouter_limits` read spend/credit endpoints;
`auto_create_blocks` creates one block per fetched model. `usage_stats` is the statistics panel: a
single pass over the last N days of proxy event logs' `finished` events — cloud requests priced from
LiteLLM pricing (manual `apiPricing` overrides win), local requests counted in tokens plus a "would
have cost" estimate from `localPricing` — aggregated per account, model, and day; capped by log
retention.
Owns: — (reads proxy logs, writes secrets/blocks via `cloud.py`).
Key functions: `test_account_key`, `set_account_key`, `fetch_account_models`,
`fetch_subscription_models`, `fetch_subscription_usage`, `fetch_account_costs`,
`fetch_openrouter_limits`, `auto_create_blocks`, `cloud_spend_summary`, `usage_stats`.

## `pricing.py`

The LiteLLM model-pricing table (`model_prices_and_context_window.json` from GitHub raw), reduced to
`{model: {inputPer1M, outputPer1M, provider}}` and cached on disk for 24h at
`logs/model-pricing-cache.json`. Returns `{}` on any error — pricing is a non-critical feature.
Owns: the pricing cache file.
Key functions: `fetch_model_pricing`.

## `telemetry.py`

Remote-node probes and the in-memory telemetry rings behind topology cards. Probes, each behind its
own `TtlCache`: `firewall_port_access` (ufw view of who may reach a controller port, 30s),
`probe_remote_port` (TCP connect, 15s), `remote_llama_health` (`/health` → ok / loading — llama.cpp
answers 503 while loading into VRAM — / down, 3s), `remote_llama_modalities` (`/props`, the
authoritative vision/audio source, 300s), and `command_cell_health` (HEALTH_PATH JSON with
download/load progress bytes, or a bare TCP probe when unset). The three history rings —
`_gpu_history` (mem/util/power per `node:gpuIndex`), `_cpu_history` (load/RAM per node),
`_tps_history` (prompt/gen t/s per `node:port`) — are appended on every topology build, same-second
samples collapsed, 600s retention / 300 rows kept / 150 emitted, all guarded by `_history_lock`.
Owns: the four probe caches, the three history rings, `_history_lock`.
Key functions: `firewall_port_access`, `probe_remote_port`, `remote_llama_health`,
`command_cell_health`, `remote_llama_modalities`, the `_record_*_history` feeders used by topology.

## `server_cells.py`

Server slot/cell bookkeeping — pure data layer; the start/stop actions live in `cell_ops.py`. Slots
are persistent `"hostId:port"` records in `topology_store()["serverSlots"]` so a proxy cable stays
attached while a server is stopped or its model changes. Port allocation starts at 8001 and
collisions raise 409. `upsert_server_slot` deliberately keeps empty-string config values (an empty
field is a *removed* flag — dropping it would make the edit form re-inherit the controller default),
keeps a ≤10-entry command history for command cells (one-click revert), and regenerates on-disk cell
artifacts for controller (`skynet`) slots.
Owns: the `serverSlots` records inside admin state.
Key functions: `server_slot_key`, `next_server_cell_port`, `used_server_cell_ports`,
`assert_server_cell_port_available`, `upsert_server_slot`, `reserve_server_cell`,
`move_server_cell`, `delete_server_slot`, `normalize_topology_agent`.

## `fleet_clients.py`

Client fleet management over the route-agent HTTP API. `client_llama_start` implements Variant 2 —
the controller is the single command builder: it ships the resolved `build_remote_llama_args` list
(path placeholders substituted by the agent after download) or, for command cells, the raw command +
health path; slot moves/reservations happen first. `update_topology_client` /
`topology_client_from_heartbeat` normalize incoming heartbeats into the topology store;
`refresh_topology_clients_from_agents` pulls each agent's `/api/state` on demand so the Topology
view is current without waiting for a heartbeat (clients are `online` within `TOPOLOGY_CLIENT_TTL`,
45s, else `stale`). `auto_provision_agent_proxies` creates proxy port pairs (odd primary / even
fallback) for unprovisioned agents, wires them to the default router, writes the config and restarts
the proxy daemon. The controller also hosts every node's named launch-config backups under
`var/server-backups/<host>/<gpu-model-or-CPU>/<stamp>-<name>.json` (path-safety enforced) so a
client's backups survive the client; deletion uses `deletedAgents` tombstones so heartbeats don't
resurrect removed agents.
Owns: the `clients`/`assignments`/`deletedAgents` sections of admin state; the `var/server-backups/`
store.
Key functions: `client_llama_start`, `client_llama_stop`, `client_monitor`,
`client_llama_configs`/`_save`/`_delete`, `client_llama_list_cache`/`client_llama_purge_cache`,
`update_topology_client`, `topology_clients`, `refresh_topology_clients_from_agents`,
`auto_provision_agent_proxies`, `topology_discover_add` (fleet-registry registration),
`topology_client_delete`/`topology_client_agent_delete`, `set_topology_client_alias`.

## `topology.py`

Assembly of the `/api/topology` tree — the first aggregator layer. `topology_server` builds the
controller node: service + runtime phase, GPUs, and every controller cell with its systemd status,
health, live metrics, context usage, modalities and TPS history. `topology_nodes` produces the
host-centric spine (one node per machine, servers bound to GPUs via compute apps). `topology_state`
pulls it together: refreshes clients from their agents (skippable via `refresh_clients=False`),
auto-syncs the policy's `maxSlots` to the fleet's total llama slots, resolves each proxy's *actual*
upstream through its router's default output (the route's own upstreamPort is a legacy placeholder),
auto-syncs router outputs to the available providers (persisting once, via a fresh read-modify-write
to avoid clobbering concurrent edits), and returns servers, nodes, proxies, routers, policy,
clients, assignments, orphaned agents, aliases, layout, OpenClaw configs and cloud state.
`apply_topology_assignments` validates and stores agent→proxy assignments and pushes them to the
client agents.
Owns: — (aggregates; writes only via `proxies_config`/`state`).
Key functions: `topology_state`, `topology_server`, `topology_nodes`,
`normalize_topology_assignment`, `apply_topology_assignments`.

## `proxy_ops.py`

Cross-domain proxy actions sitting above the domain modules. `reconcile_agent_proxies` cleans up
drift after re-provisioning: for every **online** agent it rewrites the stored assignment to the
proxy the agent live-reports (+ the contiguous P+1 fallback when that port exists), leaves offline
agents untouched (except tombstoned ones), then deletes proxy routes no assignment references
anymore — via `save_agent_proxy_config`, which also restarts the daemon. `stop_agent_proxy_route`
appends `stopRequests` entries (by request id, or every active request on a port) to
`agent-proxies.json`; the proxy daemon's stop-watcher kills the in-flight requests.
Owns: —.
Key functions: `reconcile_agent_proxies`, `stop_agent_proxy_route`.

## `backups.py`

Controller `start-server.sh` backups (the `*.bak.*` files written by `snapshot_config`). `backups()`
lists the newest 20 with labels enriched by the parsed model/ctx; `resolve_backup_path` rejects
anything outside the launcher directory or not matching the backup name prefix. `revert_latest`
copies the newest backup over `start-server.sh` and re-chmods it. (Client/cell config backups are a
different store — see `fleet_clients.py`.)
Owns: — (operates on `START_SCRIPT.bak.*` files).
Key functions: `backups`, `resolve_backup_path`, `backup_config` (parsed + raw text),
`delete_backup`, `revert_latest`.

## `status.py`

The composite dashboard state and service actions. `state()` is the `/api/state` payload: parsed
config + field metadata, paths, model catalog, chat templates, service status, runtime (with phase),
diagnostics, CPU/GPU/memory, llama.cpp build info, journal logs, backups, OpenClaw manager state,
and the project's own git info. `do_action` starts/stops/restarts `llamacpp-current.service` and
notifies the OpenClaw config managers after start/restart. `llama_cpp_info` reports the binary
version and feature support plus the llama.cpp checkout's git state (optionally checking upstream
for the newest `bNNNN` build tag); `update_llama_cpp` refuses when tracked files are dirty, then
fetch + ff-only merge + cmake-builds `llama-server`.
Owns: —.
Key functions: `state`, `do_action`, `llama_cpp_info`, `update_llama_cpp`, `llama_server_path`,
`project_git_info`.

## `cell_ops.py`

Server-cell lifecycle actions across both kinds of hosts; sits above `status` because its handlers
return the composite `state()`. `client_server_slot_add` declares a persistent slot (reserving the
next free port when none is given); `client_server_slot_delete` removes the slot and, for client
hosts, also tells the agent to stop/clear the node — otherwise the cell keeps coming back with the
next heartbeat. `server_cell_save_config` saves without starting. `server_cell_action` dispatches:
on `skynet` it ensures the start.sh artifact exists and drives systemd `lama-cell@<port>`
(start/stop/restart/enable/disable); on a client it forwards start/restart (from the saved slot
config; command cells must have a COMMAND, llama cells a model) or stop to the route-agent.
Owns: —.
Key functions: `client_server_slot_add`, `client_server_slot_delete`, `server_cell_save_config`,
`server_cell_action`.

## `routes.py`

HTTP route tables and the request handler. Every route body moved verbatim from the monolith's
if/elif chains. Routes register into the `GET_ROUTES` / `POST_ROUTES` / `DELETE_ROUTES` dicts via
the `@_route(table, *paths)` decorator, which **raises on duplicate registration** at import time.
`GET_PREFIX_ROUTES` holds the only prefix matches — `/api/monitor/` plus the `/js/` and `/css/`
static subdirs (filename-class regex, no traversal) — checked before the exact-match dict. Dispatch
quirks are preserved exactly: `do_POST` parses the JSON body **before** the path lookup, so a bad
body on an unknown path is a 500, not a 404; `do_DELETE` has no `AppError` clause, so an `AppError`
from a DELETE handler surfaces as 500 (GET/POST map it to its status). `Handler` provides
`send_json` (via `json_bytes`), `send_file` (mtime+size ETag with `Cache-Control: no-cache` —
redeploys show up immediately, unchanged files answer 304) and `read_body` (empty body → `{}`).
Roughly 60 GET, 55 POST and one DELETE route (`/api/hf/local-file`); static pages `/`, `/hf`,
`/kanban` (alias `/router`) come from `static/`.
Owns: the four route tables; `Handler`.
Key functions: `_route`, `Handler.do_GET`/`do_POST`/`do_DELETE`,
`Handler.send_json`/`send_file`/`read_body`.

## `main.py`

Entry point. `main()` chdirs to `PROJECT_ROOT` (the same directory systemd's `WorkingDirectory`
points at, so `var/`, `logs/` and git commands work when launched by hand), warms the OpenClaw
config cache from disk, then starts the daemon threads: the monitor sampler loop (1s cadence), a
one-shot bootstrap that recomputes cloud-fallback eligibility from current graph connections
(writing `agent-proxies.json` only when something changed), a one-shot wait-timeout sync +
queue-threshold compute, and the 6-hour threshold refresh loop. Finally it binds
`ThreadingHTTPServer((HOST, PORT), Handler)` and serves forever.
Owns: thread startup order.
Key functions: `main`.

## Invariants for contributors

- **Layering.** `common ← paths ← state ← domain modules ← aggregators (topology, status) ←
  ops (proxy_ops, cell_ops) ← routes ← main`. Imports only point left; no cycles; nothing
  imports the launchers.
- **Rebind co-location.** If a module global is ever rebound, every function that rebinds it
  lives in the same module; other modules call functions instead of importing the variable.
  Never-rebound mutable objects (`admin_state`, locks, deques, caches, rings) are imported
  by name and mutated in place — never rebound, never copied.
- **Atomic writes.** Config/state files go through `fsio.atomic_write_text` (unique pid/tid
  temp name + `os.replace`); never write shared JSON files directly.
- **Paths.** Every path and env-driven constant comes from `paths.py` (anchored to
  `PROJECT_ROOT`). Do not derive paths from `__file__` in any other module.
- **File ownership.** The admin writes `agent-proxies.json` — always through
  `write_agent_proxy_payload` (normalizes, protects the router graph, fires the `.bak-graph`
  autobackup). It only *reads* `agent-proxy-state.json` and `logs/proxy-events/*.jsonl`; the
  proxy daemon owns those.
- **Routes.** Register handlers with `@_route`; duplicates raise at import. Only
  `/api/monitor/`, `/js/`, `/css/` may be prefix-matched. Keep the dispatch quirks (POST
  body-parse before lookup; DELETE without an `AppError` clause) — preserved monolith
  behavior.
- **stdlib only.** No third-party dependencies anywhere in `caravan/`.
- **Entry filenames are frozen.** `app.py` (and `agent-proxies.py`) must keep their names
  and locations: systemd `ExecStart` runs them directly and `scripts/test_queue_node.py`
  loads them by path via `spec_from_file_location` (`app.py` re-exports
  `normalize_router_graph` for that test).
