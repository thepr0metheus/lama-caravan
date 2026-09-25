# Admin server module reference (`caravan/admin/`)

The admin server is the control plane of lama-caravan: a single stdlib-only Python process serving
the dashboard UI and the whole `/api/*` surface — launch-config editing for the controller's
llama-server and its server cells, GGUF catalog and HuggingFace downloads, systemd control, fleet
clients (route-agents on other hosts), the proxy/router configuration the proxy daemon consumes,
cloud provider accounts, and the 1-second system monitor. It was refactored from a 9,438-line
`app.py` monolith into the modules below; `app.py` remains as a 20-line launcher. Entry chain:
`app.py` → `caravan/admin/main.py:main()` → background threads (monitor sampler, OpenClaw threshold
refresh, one-shot bootstraps) + a `ThreadingHTTPServer` serving `routes.Handler` on
`LLAMACPP_ADMIN_HOST:PORT` (default `0.0.0.0:7990`).

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
| `model_artifacts` | Which folders are models in their own right — a whisper HF cache, a safetensors checkpoint. Outermost only: a snapshot directory inside a cache matches the rule too, but naming it as well would let one move carry half a model off. `folder_weight` counts what a COPY weighs — real files once, links never (a cache holds every blob under a link as well). The probe child in `model_stores.py` imports nothing of ours, so it carries this module's own source text: the models disk and a library are walked by the same lines. | `artifact_kind`, `artifact_dirs`, `folder_weight`, `hidden`, `relative` |
| `ttl_cache` | `(timestamp, value)` TTL cache with an internal lock. `get()` returns the `MISS` sentinel so falsy values are cacheable. No single-flight by design: concurrent misses may both fetch, same as the pre-refactor call sites. | `TtlCache`, `MISS` |

## `paths.py`

Environment-driven constants and every repo-relative path, all anchored to `PROJECT_ROOT =
Path(__file__).resolve().parents[2]` (the repo root, where `app.py` lives). No other module may
derive paths from its own `__file__` — it would point into `caravan/`. Covers the llama.cpp install
(`LLAMA_HOME`, `START_SCRIPT`, `DEFAULT_MODELS_DIR`), the two service names, the config-backup dir
(`var/server-backups`), the shared JSON files (`agent-proxies.json`,
`agent-proxy-state.json`, `cloud-providers.json`, `token-history.json`), per-user state
(`admin.json`, monitor history, incident log), secrets (`provider-secrets.json` — outside the repo,
0600), and tunables (monitor interval/retention, token-history caps,
`SERVER_CELL_BASE_PORT`, default 22001 via `CARAVAN_CELL_BASE_PORT`). NOTE: `PORT` was once inside the cell numbering
that starts at `SERVER_CELL_BASE_PORT`, so `used_server_cell_ports()` adds it to
the taken set — otherwise a cell could be assigned the controller's own port.
(`var/server-cells`, the controller's own cells' launch files, went with those cells in step 6.9;
so did `client-labels.json`, the monitor's labels for the clients of the controller's own server.)
Owns: — (constants only; the single source of path truth).
Key functions: — (no functions; import the constants).

## `state.py`

Persistent admin-panel state (`admin.json`), the single shared mutable store. `admin_state` is
created exactly once at import (loaded from disk, defaults seeded: monitor retention, topology
sub-maps, `localPricing`/`apiPricing`, `hfToken`, `hfFavorites`, `favFields`); every other module
imports the object, mutates it in place, then calls `save_admin_state()` — never rebinds it.
`topology_store()` returns `admin_state["topology"]` after ensuring its sub-keys exist (`clients`,
`assignments`, `clientAliases`, `layout`, `serverSlots` — the persistent host:port declarations that
keep proxy cables attached across restarts). On load it drops, once, what scout reports and
adoption left in the document (`AdminStore.SCOUT_WORDS`, the `deletedAgents` tombstones).
Owns: `admin_state` (in-memory), `admin.json` on disk.
Key functions: `load_admin_state` (tolerant read), `save_admin_state` (atomic write of the live
object), `topology_store` (defaults-ensured topology sub-store).

## `auth.py`

Accounts, sessions and the fleet token — stdlib `sqlite3`, one `auth.db` next to `admin.json`
(0600, `LLAMA_ADMIN_AUTH_DB` to override). Auth is OFF until the first user exists (open homelab
default); creating one (Security panel or `python3 -m caravan.admin.auth create-user`) turns the
guard on for every route except the login page, the auth bootstrap endpoints and the machine
endpoints (heartbeats, `/metrics`), which switch to the **fleet token** — a shared machine secret
scouts carry in their config. Passwords are PBKDF2 (per-user salt, constant-ish-time compare with
a timing pad on unknown users, per-IP lockout after 5 failures); sessions are random tokens stored
as SHA-256 hashes with a TTL and a 5 s in-process cache. A CLI (`python3 -m caravan.admin.auth …`)
covers create-user / set-password / fleet-token for headless bootstrap.
Owns: `auth.db`, the session cache, `_LOGIN_FAILS`.
Key functions: `auth_enabled`, `create_user`/`set_password`/`delete_user`/`list_users`,
`verify_login`, `create_session`/`validate_session`/`delete_session`, `list_sessions`,
`revoke_other_sessions`, `fleet_token_get`/`fleet_token_regenerate`/`fleet_token_verify`,
`session_from_handler`, `session_cookie_header`.

## `config_builder.py`

The launch-config contract. `CONFIG_FIELDS` (~135 keys, including the command-cell keys
`CELL_KIND`/`COMMAND`/`HEALTH_PATH`/`ENV`/`WORKDIR`) and the `# BEGIN/END LLAMA CONFIG` marker lines
are a contract with `scripts/start-server.sh` — never rename them here alone. `build_llama_args` is
the **single config→CLI source of truth**: the local start-server.sh, server cells (same generator),
remote clients (args shipped with `{{MODEL_PATH}}`/`{{MMPROJ_PATH}}`/`{{SPEC_PATH}}` placeholders
the route-agent substitutes after download — it has no builder of its own and refuses a start
without them), and the GUI preview (`POST /api/llama-command-preview`)
all funnel through it — adding a flag means editing it and nothing else. Safety nets live here too:
embeddings mode drops speculative decoding and `--jinja`; `ENABLE_THINKING` merges into
`--chat-template-kwargs`. `parse_extra_args` is the inverse — it hoists recognized raw flags out of
`EXTRA_ARGS` into their form fields.
`model_paths` answers where this host reads the cell's three model files: without a `locations`
snapshot every one is on the models disk (the answer from before libraries existed, and the right
one for a command that is only being shown), with one a file that lives in a library is read from
there. A file read over the network is never mapped — llama.cpp keeps the input layer on the CPU
and reads it from the file per token, so a share that blinks takes a running cell down. `--mmap`
asked for in the fields is overruled and `--load-mode` loses only its mapping (`no_mmap_mode`:
mmap+mlock → mlock, mmap → none, dio and mlock untouched). One file over the wire is enough:
`--no-mmap` is a property of the process, not of a file.
Owns: `CONFIG_FIELDS`/`FIELD_HELP` and the config-block markers.
Key functions: `parse_config` (read start-server.sh), `parse_config_from_text`/`split_config`,
`build_config_block` (validates MODEL_FILE/PORT/numerics), `build_llama_args`,
`build_remote_llama_args` (placeholders, no host-local flags; the auto-YaRN recipe from the header
of the copy this controller has — `header_path`), `build_local_llama_command` (absolute
paths + binary), `model_paths` (the three files and a runner's own model folder — vLLM's `VLLM_MODEL` under the models root), `run_config` (a start's config with that folder where it is now), `no_mmap_mode`, `parse_extra_args`, `is_command_cell`,
`models_dir_from_config`.

## `runners.py`

Runner registry: which inference engines a cell can launch and which model formats each accepts.
The cell config carries the flavour in `RUNNER` (`llama-server` 🦙 / `vllm` ⚡ / `whisper` 🎙 /
`custom` 🛠); legacy configs predate the field and map from `CELL_KIND` (`command` → custom, else
llama-server) so every saved config/snapshot/backup keeps working. Non-llama runners resolve to the
command path: `build_vllm_command` (self-provisioned `~/vllm-venv`, format gates like
nvfp4 ≥ CC 10.0 / fp8 ≥ 8.9 against the host GPU) and `build_whisper_command` render the managed
command a cell runs; `effective_command`/`effective_health_path` are what launch/probing consume.
Owns: the runner table and format requirements.
Key functions: `runner_id`, `uses_command_path`, `build_vllm_command`, `build_whisper_command`,
`effective_command`, `effective_health_path`.

## `launch.py`

Renders launch scripts from configs. `render_launch_script` produces the controller's
start-server.sh — whose config block is what every new cell inherits — and the same script for any
config the goldens pin: env header, the config block (so the GUI can reload values via
`parse_config`), file-existence guards,
and a generated `# BEGIN/END LLAMA COMMAND` `exec llama-server …` block — regenerated from the
config so block and command never drift. The engine's environment is the runner's
(`Runner.launch_env`): CPU-only llama configs (`N_GPU_LAYERS=0`) export `CUDA_VISIBLE_DEVICES=""`
because a CUDA build still initializes the backend at `-ngl 0` and can abort on a full GPU; a
scout's start carries the same environment (`env`, since scout 2.8.1). `render_command_cell_script` does the same for command cells (arbitrary managed
process, `exec`'d so whoever starts it tracks the real PID; `ENV` rendered as exports, optional `cd
WORKDIR`), and `render_command_cell_shell_line` renders that same cell as one `bash -lc` sentence
— how a scout runs it, as a child process — shipped as `payload["shellLine"]`. The two share
`command_cell_env_exports`: the agent used to parse `ENV`
itself and had already lost `set -euo pipefail`, so one config behaved differently per host. They
share the runner's bootstrap too (`runner.bootstrap_lines`, vLLM's venv provisioning): the script
has it as lines, the sentence as the same lines joined by `one_line_statements`. vLLM once had a
one-line copy of its own — it installed an unpinned vLLM, and the `exec` meant for the command stood
in front of the whole chain, so bash was replaced by `[` and a vLLM cell on a scout never served
(`scripts/test_vllm_shell_line.py` now runs the sentence in bash). Both are pinned by the goldens:
`tests/golden/commands/*.sh` and, for command cells, `tests/golden/shell-lines/*.txt`.
A file in a library brings one guard more, before the file tests and once per library: its mark
in the library's root. Without the mark the share did not mount, and what sits under the mount point
is the local disk — the file test alone would report the model missing and send whoever reads the
log looking for a deleted file. (The per-cell `var/server-cells/<port>/start.sh` + `cell.json`
went with the controller's own cells in step 6.9: a cell runs through the scout of its machine,
which gets its line from the controller at every start.) `save_config` rewrites the whole
start-server.sh — the controller's own config: its models directory and the defaults a new cell
starts from. (Its named `.bak` snapshots, their list and the revert went with the controller's own
cells in step 6.9; a cell's snapshots live with its slot.)
Owns: the `# BEGIN/END LLAMA COMMAND` markers.
Key functions: `render_launch_script`, `render_command_cell_script`,
`render_command_cell_shell_line`, `command_cell_env_exports`, `save_config`.

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
`list_models` also lists the files only a usable library holds (`model_locator.py`), in their places
and marked `libraryOnly` with their `store`; their header facts come from `library_meta.py`, never
from reading the NAS.

## `model_locator.py`

Where a model file lives right now: on this disk (a local `stat`), in a library, or nowhere. A
library's files come from the registry's last look (`model_stores.py`) — this process never touches
the NAS, since a dead NFS server makes `stat()` wait. A library counts only while it is really there
(`ok`, `low-space`, `read-only`). The board and the picker read the snapshot without waiting
(`current_locations()`); a start asks for a fresh one (`wait=True`).
`Locations.library_file(path)` answers the same for a path as this host reads it — the size a
library's last look gave it, all parts of a multi-part GGUF; a path under a library that is not
usable now is unknown, and nothing may look there.
Key functions: `Locations.locate`, `Locations.library_entries`, `Locations.library_size`,
`Locations.library_file`, `current_locations`.

`MountFacts` answers what the card shows when a store is NOT ok: what this host has mounted at
that path (`/proc/self/mountinfo`, the last mount wins — that is the one a reader gets), whether the
machine the source names answers a knock on its port (2049 for NFS, 445 for SMB; a device names
nobody and the answer is "not known", never "silent"), and whether `/etc/fstab` carries a line for
the mount point. All of it is this host's own files plus one connect with its own deadline — none of
it can wait on a dead share the way a `stat()` on the mount point does. `StoreRegistry.repath`
points a library at another path when the share or its mount point moved: a library is its mark, not
its path, so the new folder must carry the same mark (`other-library` otherwise), and the rest of
the refusals are Add's.

## `library_meta.py`

A GGUF header's runtime facts for the files that live in a library: read from the local copy just
before a move deletes it (`store_moves.py` → `remember_header`) and kept in
`state/library-meta.json` by library, path and size — a different size under the same name is
another file and gets nothing.
Key functions: `LibraryMeta.lookup`, `LibraryMeta.remember_file`, `library_meta`.

## `model_gc.py`

Models-disk garbage collection (the `/models` page backend). "Referenced" = mentioned by any
server slot's saved config (`MODEL_FILE`/`MMPROJ_FILE`/`SPEC_DRAFT_MODEL_FILE`) or by the legacy
start-server.sh; multi-part GGUFs (`…-00001-of-00004.gguf`) are grouped — if any part is
referenced, every part is. `list_unused_models` reports unreferenced files with sizes;
`delete_models` re-checks references server-side before removing (the UI cannot talk it into
deleting a referenced file) and prunes emptied directories. Named by a cell and READ by one are two
different facts: `holders` answers the second (only the cells that name the very files asked about
are questioned, and a client's cell counts as reading — it cannot be asked from here), and a move
goes by it, because a stopped cell's model may travel and its start brings it back. Deletion keeps
going by the first. Each listed file carries both: `referencedBy` and `readBy`.
Owns: —.
Key functions: `list_unused_models`, `delete_models`, `holders`, `running_owners`.

## `systemd_ctl.py`

`systemctl --user` control. `user_systemd_env` supplies `XDG_RUNTIME_DIR` and the session bus
address so the admin (itself a service) can talk to the user manager. What is left: bouncing the
proxy daemon after a routes save (`restart_agent_proxy` — a supervised child in the container), the
legacy single service (`llamacpp-current.service`: status, journal tail, repair), and who listens
on a port. `user_service_diagnostics` produces the bus/service/HTTP checklist shown in the UI. The
per-port cell units (`lama-cell@<port>.service`) and their template went with the controller's own
cells in step 6.9: its machine's cells run through that machine's scout.
Owns: —.
Key functions: `systemctl`, `restart_agent_proxy`, `service_status`, `listening_pid`,
`user_service_diagnostics`, `logs` (journal tail), `read_cmdline`, `repair_user_service`
(daemon-reload + restart).

## `cell_words.py`

`CellWords` — one vocabulary for the words a cell writes, whoever carries them to the board: why
it would not start (`failure_kind`: exec, oom, model, port — or crash), where its start is
(`progress_note`, from the last line that names a stage), and what killed it (`crash_kind`:
gpu-hang, gpu-oom, assert, killed — or crash). A scout carries the words (the crash note with its
last lines, the lines written while the port did not listen yet); the tables are matched in order,
the first hit wins, and every entry says why it stands where it does. It read the journal of the
controller's own cells too, until those moved to its machine's scout — which is why it outlived
`systemd_ctl`'s cell half.
Owns: —.
Key functions: `CellWords.failure_kind`, `CellWords.progress_note`, `CellWords.crash_kind`.

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
A cancel (`cancel_hf_download`, from `POST /api/hf/download/cancel`) raises a flag the thread
checks before each file and after each chunk: the job ends `cancelled`, is never retried, and the
bytes already fetched stay as a partial with its manifest — listed as interrupted and resumable at
once (the scan cache is dropped); a partial with no bytes is removed.
Owns: `_download_jobs` + `_download_jobs_lock`; job worker threads.
Key functions: `start_hf_download` (returns job id; status polled via `/api/hf/download/status`),
`cancel_hf_download`, `scan_interrupted_downloads`, `resume_interrupted_download`.

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

## `engine_actions.py`

`EngineActions` — a model of an engine next to a machine's cells loaded or
unloaded from the board: the engine's port comes from the machine's host
record, the act goes to its scout (`POST /api/engines/<op>`, 15 s — the scout
answers before the engine does), and the engines the scout answers with,
the model marked as being acted on, go into the host record at once. What the
act came to arrives with the reports after it (`action`, `actionError`). A load
that would not fit into the cards' free memory comes back as `short` (scout
2.15+) — `EngineReport.short` keeps its numbers — and `force` loads it anyway;
`hold` says how long the model stays unused. `EngineActions.serve` starts or
stops the engine's server itself (scout 2.16+) the same way; `EngineReport`
keeps who runs it (`runBy`), whether it starts with the machine (`autostart`),
its start or stop under way or refused (`serverAction`, `serverError`), and a
stopped engine (`state: "stopped"`).
`EngineActions.pull` downloads a model into an engine (scout 2.17+); `delete` is
one more model act, as a load is. `EngineReport` keeps the download under way
(`downloading`) and the last one refused (`downloadError`).
Key functions: `EngineActions.act`, `EngineActions.serve`, `EngineActions.pull`;
`POST /api/engines/load|unload|delete|pull|start|stop`.

## `engine_outputs.py`

The models of engines next to the cells (Ollama, LM Studio — found by the
machines' scouts, kept by `EngineReport`) that the operator made router
outputs: `EngineOutputs`. An output is `eng:<hash>` of (machine, engine kind,
model name) — no `:` or `/` of a model name in an id read by prefix, and no
port, so an engine that moves keeps its edges. An exposed model whose machine
is on the board is always an output, even when it cannot work (engine stopped,
model removed, engine on 127.0.0.1 of another machine): its probe says so, and
the router's default is not rewritten each time an engine blinks. The proxy
reaches the engine at the machine's address, or at 127.0.0.1 when the engine
listens only there and the machine is the controller's own. `set` refuses a
model the machine's report does not list and a model Ollama runs on its own
cloud. `annotate` gives the board each model's output id, whether it is one,
and whether the proxy can reach its engine — and why not (`blockedBy`):
`loopback` (127.0.0.1 of another machine) or `firewall` (its ufw lets no one
in on the port, or only sources the controller's address is not among — scout
2.13+ reports the reading). On the controller's own machine neither applies;
an unread firewall, or a controller whose own address was never set, is no
verdict.
Owns: `topology.engineOutputs` (`{output id: {hostId, kind, model, port}}`).
Key functions: `EngineOutputs.output_id`, `set`, `outputs`, `annotate`;
`POST /api/engine-outputs/expose`.

## `proxies_config.py`

`agent-proxies.json` I/O and mutation — routes, routers, policy. The admin **owns** this file; the
proxy daemon only reads it (by mtime, ~2s). Every write funnels through `write_agent_proxy_payload`,
the single choke point: it recomputes cloud-fallback eligibility, re-normalizes routers against the
routes, and enforces graph protection — whenever the on-disk file has router-graph nodes it
snapshots an autobackup (`agent-proxies.json.bak-graph-<stamp>`) before every write, and if the
incoming payload would lose a non-empty graph it restores the old graph into the new payload. The
newest 20 of those copies are kept (`ProxyStore.backups_kept`) and older ones are removed on the
next write — there was no limit, and a copy per save left 13 678 of them beside the file (2026-09-20). Reads
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

Token-rate history (`token-history.json`), fed by the proxy's own records. `_token_history` is
rebound here — every rebinding function stays in this module.
`record_token_history` appends one entry per **completed** proxy request from llama.cpp's exact
per-request `timings` on the proxy's recent items, attributed by proxy port, deduped by request id,
trimmed to 14 days / 12,000 entries on save — the authoritative per-request source, no
time-correlation guesswork. (The controller-side counters that scraped the controller's own
llama-servers every second, and fed a Token Speed series of their own, went with its cells in
step 6.9: a cell's rates now come from its machine's scout.)
Owns: `_token_history` (+lock), `token-history.json`.
Key functions: `load_token_history`, `save_token_history`, `record_token_history`,
`token_history_query`.

## `proxy_stats.py`

Read-only views over the **proxy daemon's** artifacts: `agent-proxy-state.json` and
`logs/proxy-events/*.jsonl`. The admin never writes these — the proxy owns them.
`agent_proxy_sample` loads the live state file; `summarize_proxy_item` normalizes an active/recent
request record (upstream host/port recovery, usage tokens, phase) for the dashboard.
`load_agent_proxy_logs` reads one date's JSONL (filterable, capped at 2000 rows);
`proxy_daily_stats` folds a day's `received`/`blocked`/`finished` events into per-route
total/failed/paused counts (paused = blocked by route mode, not a real failure). (Matching the
journal of the controller's own single server to requests by time went with that server in
step 6.9.)
Owns: — (reader only).
Key functions: `agent_proxy_sample`, `summarize_proxy_item`, `proxy_usage_tokens`,
`list_agent_proxy_log_dates`, `load_agent_proxy_logs`, `proxy_daily_stats`.

## `monitoring.py`

The local system monitor. `monitor_sampler_loop` — a daemon thread started by `main()` — collects
one sample per second (`MONITOR_SAMPLE_INTERVAL`): CPU from `/proc/stat` deltas, loadavg, GPU
(`nvidia-smi`), the proxy state file and config (recording token history as a side effect), memory,
disk/net rates, and top processes; `correlate_activity` then groups the proxy's active and recent
requests by route and counts the local and cloud ones in flight. (Until step 6.9 the sample also
carried the controller's own single server — its connected clients via `ss`, its slots and journal,
its token counters — and `correlate_activity` matched requests to its busy slots and, by time, to
its journal timings, whichever server had served them.) `append_incidents_from_sample` derives incidents (failed / client_disconnected /
upstream_timeout / slow first byte ≥30s / slow request ≥120s, each with a cause) and appends deduped
records to `incident-log.jsonl` (30-day retention). The sample ring is trimmed to the configurable
retention and persisted to `monitor-history.json` at most every 10s, reloaded on startup. Also hosts
the dashboard hardware state and on-demand `monitor_snapshot` (nvidia-smi, or a btop
frame rendered via `terminal.py` with a `top` fallback).
Owns: `monitor_history` deque + `monitor_lock`, the rebound `monitor_last_cpu/_disk/_net/ _persist`,
`incident_lock` + `incident_logged_keys`, `monitor-history.json`, `incident-log.jsonl`.
Key functions: `monitor_sampler_loop`, `collect_monitor_sample`, `system_monitor_state` (the
`/api/system-monitor` payload), `correlate_activity`, `append_incidents_from_sample`,
`gpu_state`/`cpu_state`/`memory_state`, `runtime_api`, `monitor_snapshot`,
`set_monitor_retention`.

## `metrics.py`

Prometheus text exposition for `GET /metrics` — cheap reads only, no probes: the proxy daemon's
live state file (route activity/queues), today's proxy log (request counters), the topology store
(hosts, cells), the cached `gpu_state()` and models-disk usage. A machine's online gauge uses the
board's own rule (`HostRecord.liveness` over `HOST_REPORT_TTL`), so the two cannot disagree. When sign-in is enabled the
endpoint authenticates with the **fleet token** (`X-Caravan-Token` or `Authorization: Bearer`), so
an external Prometheus can scrape without a browser session.
Owns: —.
Key functions: `build_metrics_text`.

## `queue_thresholds.py`

Queue-wait thresholds per proxy port. `QueueThresholds.compute` turns the policy percentages (with
per-route overrides) × each route's `clientTimeoutSeconds` — the operator's wait budget on the port
— into queue-abort / priority-preempt / cloud-fallback seconds, keeps them, and mirrors them into
`agent-proxies.json` as `computedThresholds` (a readable mirror, not the source of truth).
`refresh_forever` recomputes every **6 hours**; `latest()` is the one reader. The budget used to be
synced first from each agent's own OpenClaw config, fetched from OpenClaw config managers on the
client machines (`openclaw.py`); the managers went on 2026-09-24.
Owns: the `QUEUE_THRESHOLDS` object (last result + its lock).
Key functions: `QueueThresholds.compute`, `latest`, `refresh_forever`; `compute_queue_thresholds`
(the callers' name).

## `scout_poll.py`

`ScoutPoller` pulls the scouts' state off the board's request path. `GET /api/topology` only kicks
it: at most one pull runs at a time, at most one starts per `MIN_INTERVAL` (5 s), and the read
returns what the store already holds — the next read sees what the pull brought. It used to be a
synchronous loop inside the read, two seconds of timeout per scout, so one machine switched off
added two seconds to every board poll.
Owns: the `SCOUT_POLLER` instance (in `fleet_clients.py`) — its running flag and last start.
Key functions: `ScoutPoller.kick`.

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

## `model_catalog.py`

Provider model-catalog cache + upstream endpoint health, one small state file
(`state/model-catalog.json`; legacy installs land it at the repo root). Three jobs: (1) per-account
model lists with a 1 h TTL refreshed by a background thread (`kick_refresh` + a guarded fetcher) —
blocks whose model fell out of the list paint "unlisted" in the UI; (2) a circuit breaker around
every provider endpoint (`guarded_call(key, fn)`: 3 consecutive failures open the breaker with
exponential 6 h→48 h backoff; `endpoints_report` feeds the "API issues" panel and
`retry_endpoint` the panel's retry button — 401/403 on spend/limit endpoints stay soft); (3) the
codex `client_version`: `CARAVAN_CODEX_CLIENT_VERSION` env verbatim, else
max(npm `@openai/codex` latest cached 24 h, floor 0.160.0) — the floor matters because npm lags
behind the version gate newer subscription models require.
Owns: `state/model-catalog.json`, the refresh thread, breaker state.
Key functions: `guarded_call`, `record_ok`/`record_fail`, `endpoint_blocked`, `endpoints_report`,
`retry_endpoint`, `effective_codex_client_version`, `cached_model_ids`, `store_models`,
`models_stale`, `kick_refresh`.

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

## `cell_assets.py`

The cell servers themselves — the launchers and HTTP servers a command cell runs (moonshine,
whisper, tts). `cells/` in this repo is their one home, and this module is how they reach every
host: `cell_assets_manifest()` hashes them, `cell_asset_bytes()` serves one, and
`materialize_local_assets()` copies what a runner needs into the controller's own `$HOME` before a
local cell starts — the same destination a scout writes to, so one command string works everywhere.
The served set is an explicit allowlist (`CELL_ASSETS`, `RUNNER_ASSETS`) rather than a directory
listing, because these endpoints hand files to the whole fleet and a stray file dropped into
`cells/` must not become fleet-readable by accident. Writes go through temp+replace, and a failure
never blocks a start: an out-of-date cell beats no cell.
Before this, each host obtained these files independently — clients from their caravan-scout clone,
the controller from somebody copying one in by hand — and the copies drifted for months with no
error anywhere.
Owns: `cells/` and what `/api/cell-assets` exposes.
Key functions: `cell_assets_manifest`, `cell_asset_bytes`, `materialize_local_assets`,
`assets_for_runner`.

## `server_cells.py`

Server slot/cell bookkeeping — pure data layer; the start/stop actions live in `cell_ops.py`. Slots
are persistent `"hostId:port"` records in `topology_store()["serverSlots"]` so a proxy cable stays
attached while a server is stopped or its model changes. Port allocation starts at the configured base (default 22001; `CARAVAN_CELL_BASE_PORT`) and
collisions raise 409. `upsert_server_slot` deliberately keeps empty-string config values (an empty
field is a *removed* flag — dropping it would make the edit form re-inherit the controller default),
and keeps a ≤10-entry command history for command cells (one-click revert). A cell of the
controller's own host id is refused (`refuse_controller_host`, `CONTROLLER_RUNS_NO_CELLS`): since
step 6.8 the controller's machine runs its cells through its scout.
Owns: the `serverSlots` records inside admin state.
Key functions: `server_slot_key`, `next_server_cell_port`, `used_server_cell_ports`,
`assert_server_cell_port_available`, `upsert_server_slot`, `reserve_server_cell`,
`move_server_cell`, `delete_server_slot`, `refuse_controller_host`, `reassign_server_slot_port`
(fleet-wide free check, remaps router refs `srv:old→srv:new`).

## `cell_schedule.py`

Per-cell start/stop schedule. A slot may carry `schedule = {enabled, start "HH:MM", stop "HH:MM",
days [0..6]}` (empty days = daily); a background tick (1/min, started by `main()`) acts only on
window **edges** — so a manual stop inside a window sticks until the next window opens
(`schedState` on the slot remembers the last applied edge). Start/stop go through the same
`server_cell_action` path the buttons use. The same tick also brings a model home before its window
opens (`PREFETCH_MIN` minutes, once per window — the window it was done for is remembered on the
slot), so a scheduled cell starts from this disk instead of reading over the network; the cell is
NOT started then, and a disk with no room simply keeps the model where it is.
Owns: the scheduler thread, `schedState` and `schedFetch` on slots.
Key functions: `normalize_schedule`, `set_cell_schedule`, `in_window`, `minutes_to_window`,
`prefetch_tick`, `scheduler_tick`, `start_scheduler_thread`.

## `fleet_clients.py`

Client fleet management over the route-agent HTTP API. `client_llama_start` implements Variant 2 —
the controller is the single command builder: it ships the resolved `build_remote_llama_args` list
(path placeholders substituted by the agent after download; YaRN flags when the controller can read
the model's header) with the engine's environment (`env`), or, for command cells, the raw command +
health path; slot moves/reservations happen first. A machine is two records under one id
(`HostRecord`, since 2026-09-24): its HOST record in `topology.hosts` is what its scout reports —
GPUs, compute apps (with the process's name, scout 2.12+), the engines next to its cells (Ollama,
LM Studio — `EngineReport` in `caravan/domain/engine.py` keeps them typed, and None for a scout
that cannot look, never "none"), CPU/RAM, cells, build versions, address — and `record_host_report` /
`host_from_report` replace it with each report; its CLIENT record in `topology.clients` is the
operator's — name, agents — and no report touches it (old scouts still send agents; they are not
read). `topology_hosts` computes a host's liveness on read (`online` within `HOST_REPORT_TTL`,
180 s — three scout heartbeats — else `stale`; never stored) and returns the machines in the
board's order, by address as a number (`HostRecord.board_order`; a silent machine keeps its place,
one without an IP goes last); `topology_clients` has none — a
client's agents' traffic shows whether it works. `client_vllm` / `client_vllm_update` answer the System
page's vLLM section per machine through its scout (2.9+): the machines, this controller's own by
default (`ControllerMachine`), and a legible refusal for an older scout.
`refresh_hosts_from_scouts` pulls each scout's
`/api/state` so the board stays current between heartbeats; it runs in the background
(`SCOUT_POLLER`, see `scout_poll.py`), never inside a board read, and `scout_payload_from_state`
turns what it reads into the shape of a heartbeat. Which fields a report carries is one sample for both
repos: the scout's `docs/report-sample.json`, copied byte for byte to `scripts/fixtures/`, where
`test_scout_report_sample.py` requires every field to reach the host record (or be listed as not read,
with the reason) and the pull and the beat to make the same record. Agents and their ports are made by hand; removing an agent takes its
assignment row and leaves its ports free. Deleting a client leaves the host record alone. A machine
joins and leaves through `SCOUT_PAIRING` (`scout_pairing.py`, below). The controller also hosts every node's
named launch-config backups under `var/server-backups/<host>/<gpu-model-or-CPU>/<stamp>-<name>.json`
(path-safety enforced) so a client's backups survive the client.
Owns: the `clients`/`hosts`/`assignments` sections of admin state; the `var/server-backups/`
store.
Key functions: `client_llama_start`, `client_llama_stop`, `client_monitor`,
`client_llama_configs`/`_save`/`_delete`, `client_llama_list_cache`/`client_llama_purge_cache`,
`record_host_report`, `topology_hosts`, `topology_clients`, `refresh_hosts_from_scouts`,
`topology_client_delete`/`topology_client_agent_delete`, `set_topology_client_alias`; `SCOUT_PAIRING`.

## `scout_pairing.py`

`ScoutPairing` — the one way a machine joins the fleet as a scout host. The machine only installs
its scout (caravan-scout `./install.sh`); the operator enters its address on the board, and
`connect` reads the scout's open `/api/pairing`, hands it the controller's address and the fleet
token (`POST /api/controller-url`) and returns once the scout's first heartbeat has made the host
record. `controller_url_for` picks the address the scout will reach: 127.0.0.1 for a scout on the
controller's machine, else `LLAMA_TOPOLOGY_SERVER_IP`, else the interface that routes towards it.
`disconnect` asks the scout to let go (`/api/unpair`) and forgets the host record — a silent scout's
machine only forgotten, a refusing scout's kept. Every failure is worded with what to do. The network
comes in through `http_get`/`http_post` parameters, which the snapshot (`test_scout_pairing.py`)
replaces with a fake scout.

## `launch_files.py`

`LaunchFiles` — the files a cell's launch uses, each under its role on the card (`MODEL_FILE` →
model, `MMPROJ_FILE` → mmproj, `SPEC_DRAFT_MODEL_FILE` → draft), and how they stand against
Hugging Face: `fresh(report, models_dir)` reads the model watcher's report (keyed by the path
relative to the models directory; an absolute path inside it is brought to that key, one outside
is not checked) and keeps only what differs (`size`, `date`) or was not checked (`unknown`) — a
"matches" is never drawn. `disk_newer(reported)` keeps the roles a scout names as changed on disk
since its cell started (scout 2.11+; an older scout says nothing, which is not "unchanged").
`topology_server` puts both on every cell's card (`launchFresh` running and stopped,
`launchDiskNewer` running only) — the ⇪ and ⟳ chips the controller's own cells had until step 6.9.

## `topology.py`

Assembly of the `/api/topology` tree — the first aggregator layer. `topology_server` builds the
fleet's cells: every cell a scout reports (running or starting — health, live metrics, context
usage, modalities, crash note read with `CellWords`, TPS history) and every stored slot that is not live, as a parked card
(its trained window from the GGUF header, ≈VRAM from the file's size), plus the controller's own GPU
read for its machine's node. Since step 6.9 there is one kind of cell: the controller's own cells,
their unit status, journal errors, load progress and freshness chips went with them. `topology_nodes` produces the
host-centric spine: one node per machine with a scout, servers bound to GPUs via compute apps, and
the rest of each card's memory named by who holds it (`outside`, from `GpuOwners` in
`caravan/domain/engine.py`: an engine of the machine by the processes its scout names, else the
process's own name); a node carries its machine's `engines` as the host record keeps them. The
controller has no node of its own since step 6.9 — its machine is its scout's host node, marked
`controllerMachine` (with the controller's own `gpuError` for it). `topology_state`
pulls it together: refreshes clients from their agents (skippable via `refresh_clients=False`),
resolves each proxy's *actual*
upstream through its router's default output (the route's own upstreamPort is a legacy placeholder),
auto-syncs router outputs to the available providers (persisting once, via a fresh read-modify-write
to avoid clobbering concurrent edits), and returns servers, nodes, proxies, routers, policy,
clients, assignments, aliases, layout and cloud state.
`apply_topology_assignments` validates and stores agent→proxy assignments; nothing is sent to the
machine (the scout's apply went with its word about agents — an agent is pointed at its port by hand).
Owns: — (aggregates; writes only via `proxies_config`/`state`).
Key functions: `topology_state`, `topology_server`, `topology_nodes`,
`normalize_topology_assignment`, `apply_topology_assignments`.

## `proxy_ops.py`

Cross-domain proxy actions sitting above the domain modules. `stop_agent_proxy_route` appends
`stopRequests` entries (by request id, or every active request on a port) to `agent-proxies.json`;
the proxy daemon's stop-watcher kills the in-flight requests. (Reconciling the stored assignments
with the scouts' live reports went with the reports, 2026-09-24: the stored rows are the truth, and
a port no row claims stays until the operator deletes it.)
Owns: —.
Key functions: `stop_agent_proxy_route`.

## `proxy_supervisor.py`

Container-mode supervision of the proxy daemon. Native deployments run `agent-proxies.py` as its
own `systemd --user` unit; inside the Docker image (`CARAVAN_CONTAINER`) there is no systemd, so
the admin owns the proxy as a child process instead: spawned at startup, respawned by a watchdog
when it dies, restarted in place when a config save asks for it. `tail` serves the child's recent
output for diagnostics. On native installs this module is inert.
Owns: the child process handle + watchdog thread (container mode only).
Key functions: `start`, `restart`, `status`, `tail`.

## `controller_machine.py`

`ControllerMachine` — which scout's machine is the one this controller runs on: its scout reports
the machine's hostname, and the controller knows its own (short name, any case). Since step 6.8
that machine's cells run through its scout like any other's; it is still the machine to show
first and the one whose panels the controller fills from its own monitor. `name()` is the computer's
short hostname, case kept — `topology.server.hostname`, the name the board gives the controller's
machine when no scout reports from it (a scout reports the same name). It replaced the
controller's own display name (`LLAMA_TOPOLOGY_SERVER_NAME`, no longer read), which the kanban
had put over that machine's cells.

## `status.py`

The composite dashboard state. `state()` is the `/api/state` payload: parsed config + field
metadata, paths, model catalog, chat templates, service status, runtime (with phase), diagnostics,
CPU/GPU/memory, llama.cpp build info, journal logs and the project's own git info. (Starting and
stopping `llamacpp-current.service` and its start-server.sh backups went with the controller's own
cells in step 6.9.) `llama_cpp_info` reports the binary
version and feature support plus the llama.cpp checkout's git state (optionally checking upstream
for the newest `bNNNN` build tag); `update_llama_cpp` refuses when tracked files are dirty, then
fetch + ff-only merge + cmake-builds `llama-server`.
Owns: —.
Key functions: `state`, `llama_cpp_info`, `update_llama_cpp`, `llama_server_path`,
`project_git_info`.

## `cell_ops.py`

Server-cell lifecycle actions, each through the scout of the cell's machine; sits above `status`
because its handlers return the composite `state()`. `client_server_slot_add` declares a persistent
slot (reserving the next free port when none is given); `client_server_slot_delete` removes the slot
and also tells the scout to stop/clear the node — otherwise the cell keeps coming back with the next
report. `server_cell_save_config` saves without starting (and refreshes the request the scout keeps
for an autostart cell). `server_cell_action` forwards start/restart (from the saved slot config;
command cells must have a COMMAND, llama cells a model), stop, and enable/disable (the scout's
autostart) to the scout; the controller's own host id is refused — it runs no cells since step 6.8.
`bring_home` brings a scheduled cell's model home from a library before its window opens, when there
is room; when there is not, the cell reads it where it lies — the move planner's `no-room` refusal
IS that answer. `script_preview` shows a script a command names, from this machine's home.
Owns: —.
Key functions: `client_server_slot_add`, `client_server_slot_delete`, `server_cell_save_config`,
`server_cell_action`, `bring_home`, `script_preview`.

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
Roughly 63 GET, 69 POST and one DELETE route (`/api/hf/local-file`); static pages `/`, `/hf`,
`/board` (`/` redirects here), `/kanban` (`/router` redirects), `/models`, `/system` and `/login` come from `static/`. When sign-in
is enabled (`auth.py`), dispatch guards every route except the login page, auth bootstrap and the
machine endpoints (heartbeats, `/metrics` — fleet token).
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
