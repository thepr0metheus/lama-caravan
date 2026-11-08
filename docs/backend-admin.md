# Controller reference (`rust/crates/admin`)

> The behaviour described here stands unless a sentence says otherwise. Names of Python
> functions below (`snake_case`, and some classes) are from before 2026-11-02 and can be
> read in git at `4c53bc92`, as in `git show 4c53bc92:caravan/admin/hf.py`. A section's
> heading names the Rust file. Paths are relative to `rust/crates/admin/src/` unless they
> name a crate.

The controller is the control plane of lama-caravan: one Rust program, `caravan-admin`, serving
the dashboard UI and the whole `/api/*` surface — launch-config editing for its server cells,
GGUF catalog and HuggingFace downloads, the fleet (a scout on each machine with hardware), the
proxy/router configuration the proxy consumes, cloud provider accounts, and the 1-second system
monitor. Entry chain: `main.rs` (`Program::run`) → `startup.rs` (`Startup::run`: the proxy as a
child, migrations, background threads) → `web/server.rs` (`AdminServer::serve`, one thread to a
connection) on `LLAMACPP_ADMIN_HOST:PORT` (default `0.0.0.0:7990`).

A subsystem is a view over one object, `App` (`app.rs`): `PoolDesk::of(&app)`. What a subsystem
remembers between calls stands in `App` under its own name, behind its own lock, and nothing lives
in a global (`scripts/check_rust_contract.py`). The world comes in as parameters too: `Outside`
holds the clock, the machine's tools and the environment, and a test says each.

## Where things are

| Where | What it holds |
|---|---|
| `main.rs`, `startup.rs` | The program's start: what it refuses to start without, then what it does before it listens. |
| `app.rs` | `App`: the controller's parts, made once and handed to every route. |
| `paths.rs` | Every path and port, read from the environment once. |
| `routes/` | What the controller answers, by topic: `auth`, `cells`, `cloud`, `fleet`, `health`, `hf`, `models`, `pages`, `pools`, `proxies`, `system`, `topology`. `openapi.json` describes it. |
| `web/` | The board's server: `server.rs` (listener, sign-in guard), `table.rs` (route tables), `exchange.rs` (one request and its answer), `access.rs` (who may call what), `parsed.rs`, `gzip.rs`, the two pages of the sign-in. |
| `store/` | The documents on disk: `admin.rs`, `topology.rs`, `cell_ids.rs` (the slots keyed by their cells' ids, moved once by content), `auth.rs` and `auth/`, `proxies.rs`, `cached.rs`, `base.rs`, `sqlite.rs`. |
| `domain/` | What the records are: `runner/` (a runner as an object, one file per family), `client.rs`, `client_proxy.rs`, `host.rs`, `engine.rs`, `driver_outlook.rs`. |
| `config/` | A cell's launch config: `fields.rs`, `text.rs`, `builder.rs`, `args.rs` and `args/`, `extra.rs`, `shell.rs`, `draft_file.rs`. |
| `fleet/` | The machines with a scout and their cells: `scout.rs`, `scout_pairing.rs`, `scout_poll.rs`, `scout_scan.rs`, `scout_bundle.rs`, `reports.rs` and `reports/`, `clients.rs`, `server_cells.rs` and `server_cells/`, `start.rs`, `launch.rs`, `launch_files.rs`, `cell_ops.rs`, `cell_outputs.rs`, `cell_schedule.rs`, `cell_assets.rs`, `cell_talk.rs` and `cell_talk/`, `cell_doorway.rs`, `cell_live.rs`, `cell_words.rs`, `remote_cells.rs`, `llama_metrics.rs`, `llama_node.rs`, `machine_cells.rs`, `machine_models.rs`, `machine_rows.rs`, `machine_scout.rs`, `controller_machine.rs`, `model_cache.rs`, `model_card.rs`, `engine_actions.rs`, `engine_cells.rs`, `engine_outputs.rs`, `gpu_driver.rs`, `host_power.rs`, `host_telemetry.rs`, `default_cells_retired.rs`, `listen_address_retired.rs`, `backups.rs`, `terminal.rs`. |
| `models/` | What is on the disk and in the libraries, what the headers say, where models come from: `listing.rs`, `model_list.rs`, `headers.rs`, `gguf_header.rs`, `memory.rs`, `locator.rs`, `stores.rs` and `stores/`, `store_probe.rs`, `moves/`, `gc.rs`, `folder.rs`, `checkpoints.rs`, `walk.rs`, `hf.rs` and `hf/`, `hub.rs`, `downloads.rs` and `downloads/`, `verify.rs` and `verify/`, `staging.rs`, `watch.rs`, `notes.rs`. |
| `cloud/` | The cloud accounts, their pools and clients: `data.rs`, `presets.rs`, `oauth.rs` and `oauth/`, `api.rs`, `call.rs`, `catalog.rs`, `subscription.rs`, `reports.rs`, `pricing.rs`, `spend.rs`, `usage_stats.rs`, `upstream_errors.rs`, `resets.rs`, `pools.rs`, `pool_edits.rs` and `pool_edits/`, `pool_state.rs`, `pool_ports.rs`, `refs.rs`, `schedules.rs`, `consumers.rs`, `entry_move.rs`, `misses.rs`, `board_providers.rs`. |
| `proxies/` | The proxy's document and the proxy itself: `config.rs` and `config/`, `dsl.rs` and `dsl/`, `output_refs.rs`, `queues.rs`, `queue_thresholds.rs`, `entry_settings.rs`, `as_consumer.rs`, `ops.rs`, `stats.rs` and `stats/`, `latency.rs`, `token_history.rs`, `service.rs` and `service/`. |
| `topology/` | The board's picture of the fleet: `mod.rs`, `nodes.rs`, `server.rs` and `server/`, `assignments.rs`, `board_proxy.rs`, `windows.rs`. |
| `monitoring/` | The system monitor: `sampler.rs`, `machine.rs`, `activity.rs`, `incidents.rs`. |
| `benchmarks/` | Model quality metadata: `mod.rs`, `quality.rs`, `tables.rs`. |
| `common/` | The rules the controller reads and the proxy does not need: `account_credit.rs`, `artifacts.rs`, `checkout.rs`, `cloud_file.rs` and `cloud_file/`, `cloud_pools.rs`, `cloud_sources.rs`, `daytime.rs`, `draft.rs`, `entry.rs`, `freshness.rs`, `misc.rs`, `model_jobs.rs`, `model_kinds.rs`, `model_prices.rs`, `window.rs`, `zone.rs`. |
| `board_layout.rs`, `data_tree.rs`, `metrics.rs`, `packages.rs`, `settings.rs` and `settings/`, `status.rs` and `status/` | The order of the board's cards; the data folder's subfolders; `/metrics`; `/api/packages`; the settings file, out and in; `/api/state` and llama.cpp's own version. |

Below it stand the library crates, `rules`, `files`, `net`, `plumbing`, `wire` and `os`: [architecture.md](architecture.md#components).

## Shared helpers

| Rust home | Purpose | Key names |
|---|---|---|
| `rust/crates/rules/src/app_error.rs` | The one kind of refusal; carries an HTTP status (default 400). The server maps it to a JSON error response. | `AppError` |
| `rust/crates/plumbing/src/commands.rs` | A question to the machine's tools, as a parameter. A tool that did not run is an answer (`NoAnswer`), never a crash; `ToolAnswer` (`proxies/service.rs`) says it as `{ok, code, stdout, stderr}`, with `code: -1`. | `Commands`, `SystemCommands`, `Ran`, `NoAnswer` |
| `rust/crates/files/src/atomic.rs` | A file replaced whole: a temporary file beside the target (`name.<pid>.tmp`), then a rename, so readers never see a partial file. Optional 0600 from the first byte. | `AtomicFile` (`write`, `write_private`, `narrow`) |
| `rust/crates/plumbing/src/http_client.rs` | A program asking over HTTP: the controller, a scout, a cell, an engine, the hub. One request on one connection. | `HttpClient`, `HttpError` |
| `rust/crates/rules/src/python_json.rs` | A JSON value as Python's `json.dumps` writes it, to the byte: the files stay as they were, and the arguments of a tool call go inside a string a model reads. | `PythonJson` |
| `common/artifacts.rs` | Which folders are models in their own right — a whisper or translator (NLLB) HF cache, a safetensors checkpoint. Outermost only: a snapshot directory inside a cache matches the rule too, but naming it as well would let one move carry half a model off. What a COPY weighs counts real files once, links never (a cache holds every blob under a link as well). A store's look (`models/store_probe.rs`) is this same program as a child process, so the models disk and a library are walked by the same lines. | `ModelArtifacts` |
| `common/checkout.rs` | Which commit a checkout's code is: `git rev-parse` of the checkout, else the commit an image build baked into `CARAVAN_GIT_HEAD`, else the commit `git archive` wrote into `VERSION` (a release's one witness), else `""` — never a guessed number. The admin's `/health` and version chip read it. | `CheckoutCommit` (`commit`, `from_git`, `baked`, `error`) |
| `common/zone.rs` | What a container must be told before it starts. In a container (`CARAVAN_CONTAINER=1`) the controller refuses to start, with exit code 2 and the reason, unless `TZ` names a time zone (by name AND by effect: the C library's offset must equal the zone's, or the image has no zone data) and `LLAMA_TOPOLOGY_SERVER_IP` is an address the fleet reaches (not loopback, not `0.0.0.0`). Natively nothing is asked: the machine knows both. | `ContainerPreflight` (`problems`, `in_container`) |
| `common/misc.rs` | When the admin stops trusting the proxy's state file (30 s). The proxy rewrites it every 5 s whatever happened, and at once when something did (`rust/crates/proxy/src/proxy.rs`). It used to be written on requests only: a cloud-only controller probed no cells, and its pool card fell back to "Not measured yet" 30 s after each (2026-10-08). | `ProxyHeartbeat` (`STALE_SECONDS`, `fresh`) |
| `common/draft.rs`, `config/draft_file.rs` | Which speculative type a draft file is for, from its path: the first word of its name (`mtp`, `dflash`, `dspark`, `eagle3`, followed by `-`, `_` or `.`, any case), else `draft-mtp` for a file under a folder named `mtp` (the layout before upstream's `mtp-` names), else no sidecar (`""`) — launched as `draft-simple`. The model scanner files exactly the sidecars as drafts, and the builder launches a cell with an empty type by it. Twin of `static/js/draft-file.js`, both run against one table (`contract/draft_file.json`): until 2026-10-11 the rule was read five ways, and a head in a model's `mtp/` folder was offered with the model and launched as `draft-simple`. | `DraftFile` (`sidecar_type`, `launch_type`) |
| `rust/crates/rules/src/cell_config.rs` (`KvCache`) | Which pair of flash attention and V cache type llama.cpp starts with: a quantized V cache (q8_0, q4_0 …) needs flash attention ON, and with it stated OFF the server exits at once with `quantized V cache requires flash_attn to be enabled` (a new cell's form offered that pair, 2026-10-14: four crashes in ten minutes). `KvCache.refused_type(config)` is the quantized type the pair is refused for, `""` when it starts — flash attention left unstated is not refused (llama.cpp decides), nor is a K cache, the draft's cache types (saved, not passed) or a V cache of plain numbers (`f32`, `f16`, `bf16`). `KvCache.check` raises the refusal, with the cause and both ways out, from `preflight_start` of the llama.cpp and PrismML runners. Twin of `static/js/kv-cache.js`, both run against one table (`contract/kv_cache.json`). | `KvCache` (`refused_type`, `check`) |
| `rust/crates/rules/src/cell_config.rs` (`AskedWindow`) | The window a cell is started with: the number its context field says (`CTX_SIZE`, vLLM's `MAX_MODEL_LEN`, Strata's `STRATA_CONTEXT`), and for a field left empty — or `"0"`, llama.cpp's own "from the model" — the window its model was trained for (the owner, 2026-10-26: "if the context size was not entered by hand, put in exactly the largest the model was trained on"). `AskedWindow.of(field, trained)` is that number, `None` when neither is known or the field is not a number; `AskedWindow.empty(field)` says whether the field asks for the trained one. The llama.cpp builder passes it as `--ctx-size` (left unset, llama.cpp's `--fit` shrinks the window to fit the cards), the Strata runner as `--context`, the board shows it as a stored cell's window; the trained window of a file is read in one place, `config_builder.model_trained_window`. Twin of `static/js/asked-window.js`, both run against one table (`contract/asked_window.json`). | `AskedWindow` (`of`, `empty`) |
| `common/misc.rs` (`TtlCache`) | `(timestamp, value)` TTL cache with an internal lock. A falsy value is cacheable. No single-flight by design: concurrent misses may both fetch. | `TtlCache` |

## `paths.rs`

Environment-driven constants and every path, read once by `AdminPaths::from_env` and handed to
every other module as a parameter (`app.paths`). `project_root` is the release (`CARAVAN_ROOT`,
`main.rs`); no other module derives a path from where it stands. `data_dir` is the data folder
(`CARAVAN_DATA_DIR`): every mutable default goes under it, and a variable of its own still wins for
one file. Covers the llama.cpp install (`LLAMA_HOME`, `start_script` — the controller's config
script, `config/start-server.sh` under the data folder — `default_models_dir`), the AA scores cache
(`aa_scores_cache`), the two service names, the config-backup dir (`server-backups`), the
settings-backup dir (`settings-backups` — the copy taken before each settings import), the shared
JSON files (`config/agent-proxies.json`, `state/agent-proxy-state.json`,
`config/cloud-providers.json`, `state/token-history.json`), the state (`state/admin.json`, monitor
history, incident log, `gguf_headers_file` — what the models' headers said,
`state/gguf-headers.json`, `models/memory.rs`), secrets (`secrets/provider-secrets.json`, 0600), and
tunables (monitor interval/retention, token-history caps, `cell_ports`, from 22001 via
`CARAVAN_CELL_BASE_PORT`). `proxy_ports` (`PortRange`, 23001–23999 from `CARAVAN_PROXY_BASE_PORT` and
`CARAVAN_PROXY_PORT_SPAN`) is the block of proxy ports the machine's firewall lets in with ONE rule
the operator makes once; the caravan never runs ufw, so every port it hands out lies inside the
block. `check_port_ranges` refuses, at startup, a proxy range that overlaps the cells or the
controller's port or reaches 30000, and a controller's port inside either range: the allocator would
hand it out, and this exact bug forced the 8090→7990 move.
Without `CARAVAN_DATA_DIR` the older places stand here (the project root,
`~/.local/state/llamacpp-easy-admin/`, `~/.config/llamacpp-easy-admin/`), but the proxy does not start
without it.
(`var/server-cells`, the controller's own cells' launch files, went with those cells in step 6.9;
so did `client-labels.json`, the monitor's labels for the clients of the controller's own server.)
Owns: — (constants; the single source of path truth).
Key names: `AdminPaths`, `Environment`, `PortRange`, `HostIds`, `CONTROLLER_HOST_ID`.

## `store/admin.rs`, `store/base.rs`, `store/topology.rs`

Persistent admin-panel state (`state/admin.json`), the single shared mutable store. `AdminStore` is
opened once, in `App::new` (loaded from disk, defaults seeded: monitor retention, topology
sub-maps, `localPricing`/`apiPricing`, `hfToken`, `hfFavorites`, `favFields`). A document held in memory
stands behind a lock, and a change is a closure (`app.admin.change(|doc| …)`): nothing can hold it
across a call to the network.
`Topology::of(doc)` is a view of its `topology` section, with its sub-keys ensured (`clients`,
`assignments`, `clientAliases`, `layout` — the order of the server cards (pools and machines), see
`board_layout.rs` — and `serverSlots`, the cells the board keeps, each under its own id (`rules::CellId`): `c<port>` for a cell
made before 2026-11-07, `c` and eight hex digits for a new one. A slot holds no port: its scout leases one when the cell starts and
gives it back at the stop (Papyrus `caravan-scout-port-lease`, step 2). `store/cell_ids.rs` moves a document of before once, when
it is opened: a slot under `<host>:<port>` goes under `c<port>` without its port and its config's `PORT`, and so do the machines'
`autostart` and `autostartRequests`; the scout comes to the same names on its own (`cells/migration.rs`). On load it drops, once, what scout reports and
adoption left in the document (`AdminStore.SCOUT_WORDS`, the `deletedAgents` tombstones).
A change is saved by its caller: `saving` saves at once; `save_later` marks a change that can wait — a scout's
report, live in memory at once — and the file takes it with the next save of anything or once it has waited
`FleetReads::REPORT_SAVE_WITHIN` (300 s), which every report and the `admin-save-later` tick (a minute) check
(`save_if_waited`); a release saves what waits before its process ends. Until 2026-11-03 every heartbeat rewrote the
whole file, 526 KB, 11 times a minute, on the NAS's disks.
Owns: `admin_state` (in-memory), `admin.json` on disk.
Key names: `AdminStore` (`open`, `read`, `change`, `save`, `saving`, `save_later`, `save_if_waited`), `Store`,
`Unreadable` (a file that cannot be used is copied aside once before anything overwrites it), `Topology`.

## `board_layout.rs`

The order of the server cards — the machines and the pools in one list (2026-10-04; until then the
machines always stood above the cloud). Since 2026-10-11 the board shows the machines apart, under
Machines, and since 2026-10-12 the pools stand in Routing in their own order; no page reads the
pools' places here any more, and the machines' places stay. Since 1.3.683 Routing's Models column stands in
this list, its accounts and machines carried by their grips. `ServerOrder` keeps it
in the admin document's `topology.layout`: `serverOrder`, a list of card keys (`node:<machine id>`,
`cloud:<account id>`), and `serverOrderRev`, which grows by one with every save. `save(order)` checks
the list whole and stores it whole — a list with one bad key, a key twice or more than 500 keys is
refused with 400, never trimmed into a shorter one — and answers `{ok, order, rev}`. `keys()` reads a
hand-edited document as the keys that are keys, once each; anything else there is no order at all.
Reading writes nothing. GET /api/topology carries `layout` (`ServerOrder(section=…).layout()`, read
from the same document as the rest of the answer); the board places its cards by it
(static/js/server-order.js), and Routing's Servers panel follows.
Owns: `topology.layout` in `admin.json`. Key functions: `ServerOrder.save`, `keys`, `revision`,
`layout`; `SERVER_ORDER` is the route's instance (`POST /api/topology/server-order`).

`ClientOrder` (1.3.503; the owner, 2026-10-12: "the order of the blocks in Clients, Sets and Pools
changed by dragging") keeps the clients' order beside it, in the same section: `clientOrder`, the
clients' ports, and `clientOrderRev`. A client is a route of `agent-proxies.json`, which the proxy reads
and a page's save writes whole, so its place is kept here, not there; the pools' order is
their own order in `cloud-providers.json` (`PoolDesk.order`; the sets went in 1.3.675). `save(order)` refuses a
list with anything but distinct ports, whole (400), and an empty list returns the clients to their order
by name; `ports()` reads a hand-edited document as the ports there are, once each. GET /api/topology
carries both orders under `layout`; the board places the clients by it (static/js/consumers.js
`ConsumerCards.of`), the ones it does not name after them by name. `CLIENT_ORDER` is the route's
instance (`POST /api/consumers/order`).

## `store/auth.rs`, `store/auth/`, `store/sqlite.rs`, `routes/auth.rs`

Accounts, sessions and the fleet token — one JSON document, `state/auth.json` (0600), next to
`state/admin.json`. An `auth.db` the Python controller left beside it is read once, at the first start
(`store/sqlite.rs`, a reader of its pages and no library), and stays as it was. A document that does
not read is no empty file: it would read as "no accounts yet" and anyone could make the first one, so
every request is answered 503 instead. A fresh controller is not open: until the first user
exists the guard answers only the public routes — every page leads to `/setup`, every other API
call is a 401 naming it (since 2026-10-07; before, it was open to anyone until somebody made an
account). The first account comes from `/setup`.
Then every route needs a session except the login and setup pages, the auth bootstrap endpoints and
the machine endpoints (heartbeats, `/metrics`), which take the **fleet token** — a shared machine
secret scouts carry in their config. Passwords are PBKDF2 (per-user salt, constant-time compare with
a timing pad on unknown users, per-IP lockout after 5 failures); sessions are random tokens stored
as SHA-256 hashes with a TTL; the last sight the panel lists is written at most once in 10 minutes (`SEEN_EVERY`;
once a minute until 2026-11-03, the whole file for every open board). There is no command line any more: `POST /api/auth/users`
(the System page's Security panel) makes an account, changes its role or its password, and deletes it,
and `POST /api/auth/fleet-token` gives or regenerates the token. The panel lists a session
under the first 12 characters of its hash and ends one by exactly that id: an empty
or partial id ends nothing (400 / 404). A request whose session cannot be read because the store
does not answer is NOT a request from nobody: the answer is 503 — never 401,
which every page takes for a sign-out (2026-10-17: a poll answered 401 with a good cookie while the
NAS was busy, and the board threw the owner to `/login`). A cookie that is missing or does not
parse, a token the store does not know or has expired stay no session.
Owns: `state/auth.json`, the login failures.
Key names: `AuthStore` (`enabled`, `create_user`, `set_role`, `set_password`, `delete_user`, `list_users`,
`verify_login`, `create_session`, `validate_session`, `delete_session`, `list_sessions`,
`revoke_session`, `revoke_other_sessions`, `fleet_token`, `fleet_token_ensure`, `fleet_token_regenerate`,
`fleet_token_verify`, `cookie_header`).

## `config/builder.rs`, `config/args.rs`, `config/extra.rs`, `config/fields.rs`, `config/text.rs`

The launch-config contract. `CONFIG_FIELDS` (~135 keys, including the command-cell keys
`CELL_KIND`/`COMMAND`/`HEALTH_PATH`/`ENV`/`WORKDIR`) and the `# BEGIN/END LLAMA CONFIG` marker lines
are a contract with `scripts/start-server.sh` — never rename them here alone. `build_llama_args` is
the **single config→CLI source of truth**: the local start-server.sh, server cells (same generator),
remote clients (args shipped with `{{MODEL_PATH}}`/`{{MMPROJ_PATH}}`/`{{SPEC_PATH}}` placeholders
the route-agent substitutes after download — it has no builder of its own and refuses a start
without them), and the GUI preview (`POST /api/llama-command-preview`, which also shows the environment
the start sets, before the binary)
all funnel through it — adding a flag means editing it and nothing else. Safety nets live here too:
embeddings mode drops speculative decoding and `--jinja`; `ENABLE_THINKING` merges into
`--chat-template-kwargs`. `parse_extra_args` is the inverse — it hoists recognized raw flags out of
`EXTRA_ARGS` into their form fields.
A cell with a draft file and no type is launched with the type its file is for (`DraftFile`,
common/draft.rs), read off `SPEC_DRAFT_MODEL_FILE` as the config names it, never off
the path emitted: for a scout's cell that is the `{{SPEC_PATH}}` placeholder, and until 2026-10-11
every such cell ran its draft as `draft-simple`.
The placeholders also tell the scout which files the command reads: it copies, counts and reports a
projector or a draft only when its placeholder is in the args (`SentArgs`,
rust/crates/scout/src/starts/llama/sent_args.rs), not because the config names one. A draft switched
off stays named beside `SPEC_TYPE` `none`, and until 2026-11-07 a scout still copied it (gigabytes
for a big draft) and counted it in the start's weight, for a command that never read it.
`model_paths` answers where this host reads the cell's three model files: without a `locations`
snapshot every one is on the models disk (the answer from before libraries existed, and the right
one for a command that is only being shown), with one a file that lives in a library is read from
there. A file read over the network is never mapped — llama.cpp keeps the input layer on the CPU
and reads it from the file per token, so a share that blinks takes a running cell down. The
`--load-mode` it starts with loses its mapping (`no_mmap_mode`: mmap+mlock → mlock, mmap → none, dio
and mlock untouched), and says `none` when nothing was asked. One file over the wire is enough: it is
a property of the process, not of a file. The old switches MMAP and ENABLE_MLOCK are read into the
same flag: llama.cpp took `--mmap`, `--no-mmap` and `--mlock` away.
Owns: `CONFIG_FIELDS`/`FIELD_HELP` and the config-block markers.
Key functions: `parse_config` (read start-server.sh), `parse_config_from_text`/`split_config`,
`build_config_block` (validates MODEL_FILE/PORT/numerics), `build_llama_args`,
`build_remote_llama_args` (placeholders, no host-local flags; the auto-YaRN recipe from the header
of the copy this controller has — `header_path`), `build_local_llama_command` (absolute
paths + binary), `model_paths` (the three files and a runner's own model folder — vLLM's `VLLM_MODEL` under the models root, or named by its place among the models), `placed_model` (that place when it is found there: the scout brings it, and an HF repo id of the same shape stays vLLM's to fetch), `run_config` (a start's config with that folder where it is now), `no_mmap_mode`, `parse_extra_args`, `is_command_cell`,
`models_dir_from_config`.

## `domain/runner/`

Runner registry: which inference engines a cell can launch and which model formats each accepts.
The cell config carries the flavour in `RUNNER` (`llama-server` 🦙 / `vllm` ⚡ / `whisper` 🎙 /
`custom` 🛠); legacy configs predate the field and map from `CELL_KIND` (`command` → custom, else
llama-server) so every saved config/snapshot/backup keeps working. Non-llama runners resolve to the
command path: `build_vllm_command` (self-provisioned `~/vllm-venv`, format gates like
nvfp4 ≥ CC 10.0 / fp8 ≥ 8.9 against the host GPU) and `build_whisper_command` render the managed
command a cell runs; `effective_command`/`effective_health_path` are what launch/probing consume.
The runners themselves are objects in `domain/runner/` (`RunnerRegistry`, `mod.rs`). Two of them,
`ollama` 🟠 and `lmstudio` 🟣 (2026-09-25), are cells whose model runs inside an engine next to
them: they share `EngineCellMixin` (a mixin, since every `*Runner` class is a registry row), keep
the model as the engine names it in `ENGINE_MODEL` and the engine's loopback port in `ENGINE_PORT`
(its own 11434 / 1234 when empty; a non-port is refused, 0 included), and launch
`bash $HOME/run_engine.sh "$PORT" <engine> <port> <model>` with the model quoted for the shell. They have no tab in the cell editor (`editor_tab = False`, sent as `editorTab`): an engine
cell is made on the reserve step, choosing the engine and its model.
Owns: the runner table and format requirements.
Key functions: `runner_id`, `uses_command_path`, `build_vllm_command`, `build_whisper_command`,
`effective_command`, `effective_health_path`.

## `fleet/launch.rs`

Renders launch scripts from configs. `render_launch_script` produces the controller's
start-server.sh — whose config block is what every new cell inherits — and the same script for any
config the goldens pin: env header, the config block (so the GUI can reload values via
`parse_config`), file-existence guards,
and a generated `# BEGIN/END LLAMA COMMAND` `exec llama-server …` block — regenerated from the
config so block and command never drift. The engine's environment is the runner's
(`Runner.launch_env`): every engine exports `CUDA_DEVICE_ORDER=PCI_BUS_ID` (`Runner.CUDA_ORDER`), so
that card N is the card the board and `nvidia-smi` call GPU N — CUDA's own order is fastest first, and on
a machine with an RTX 3090 and an RTX 5090 `CUDA_VISIBLE_DEVICES=1` once named the other card than the
board did; CPU-only llama configs (`N_GPU_LAYERS=0`) add `CUDA_VISIBLE_DEVICES=""`
because a CUDA build still initializes the backend at `-ngl 0` and can abort on a full GPU; a
llama config that picks cards (`DEVICE`, such as `CUDA1`) hides the others the same way, for the same
reason: llama-server asks EVERY card it sees for its memory when it starts, whatever `--device` names, and
the cell of 2026-10-19 that picked an RTX 3090 with 20 GB free died on the full RTX 5090 beside it. The
pick stays in the board's numbers in the config; the start writes it for the process — `CUDA_VISIBLE_DEVICES=1`
and `--device CUDA0 --main-gpu 0` for a cell on the second card — and `CudaCards`
(rust/crates/rules/src/cell_config.rs) is the one place that reads it, for the environment and for the flags, so the
two cannot disagree. A field it does not read as a clean list of CUDA cards (`none`, `Vulkan0`, a card
twice, a space after the comma — llama.cpp trims nothing) hides nothing and passes the flags as typed. A
scout's start carries the same environment (`env`, since scout 2.8.1) and the same flags. The order is exported BEFORE the
cell's own `ENV`, so a row of the operator's can still say otherwise. `render_command_cell_script` does the same for command cells (arbitrary managed
process, `exec`'d so whoever starts it tracks the real PID; `ENV` rendered as exports, optional `cd
WORKDIR`), and `render_command_cell_shell_line` renders that same cell as one `bash -lc` sentence
— how a scout runs it, as a child process — shipped as `payload["shellLine"]`. The two share
`command_cell_env_exports`: the agent used to parse `ENV`
itself and had already lost `set -euo pipefail`, so one config behaved differently per host. They
share the runner's bootstrap too (`runner.bootstrap_lines`, vLLM's venv provisioning): the script
has it as lines, the sentence as the same lines joined by `one_line_statements`. vLLM once had a
one-line copy of its own — it installed an unpinned vLLM, and the `exec` meant for the command stood
in front of the whole chain, so bash was replaced by `[` and a vLLM cell on a scout never served
(`contract/runner_lines.json` now holds the sentence). That bootstrap also settles the
venv's FlashInfer pair: a `flashinfer-cubin` whose version differs from `flashinfer-python` (an older
install left it behind when vLLM moved to 0.30.0; FlashInfer then refuses to start with "flashinfer-cubin
version … does not match flashinfer version …", on every model that reaches it) is uninstalled before the
start, and FlashInfer fetches the kernels it needs. A vLLM cell also takes `TRUST_REMOTE_CODE` (`"1"`:
`--trust-remote-code`, for models that ship their own Python code, MiniCPM-o and Nemotron Omni among
them), the three flags a model's recipe asks for — `MAX_NUM_SEQS` (`--max-num-seqs`), `KV_CACHE_DTYPE`
(`--kv-cache-dtype`; empty or `auto`: no flag) and `REASONING_PARSER` (`--reasoning-parser`) — and exports its
`ENV` like any command cell: the form shows the ENV block for vLLM as for a custom command. Only the SHAPE of
the three values is checked (`VllmRunner.flag_value`: a number from 1 to 999999, a type name, a parser name; anything else is refused
with a 400 that names the field): vLLM's own sets move with its versions (`--kv-cache-dtype` has eighteen
values in 0.30.0, the reasoning parsers are registered by name and by plugin), so a value it does not know is
refused by vLLM, in the cell's log. Both are pinned by the goldens:
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

## `models/listing.rs`, `models/headers.rs`, `models/model_list.rs`

GGUF model catalog. `read_gguf_metadata` gives the facts a GGUF (v2+) header states for a wanted
key set (architecture, block/context/embedding sizes, attention heads, `pooling_type`) — it is
`GgufHeader.read` (`models/gguf_header.rs`); `read_gguf_metadata_cached` asks `HeaderMemory` first
(`models/memory.rs`: path, second written and size) and reads the file only when the memory has nothing
for it; `extract_runtime_meta` normalizes it (pooling read presence-aware since 0 is valid; a key that has
one item for each layer — Gemma 4's KV heads, 8 or 1 — stands as its widest layer in `headCountKv` and whole in
`headCountKvLayers`, beside the window and the flags of the windowed layers, which the form's estimate of the cache
reads). `list_models`
scans the models dir, classifies files (model / mmproj / draft — a draft by `DraftFile`, the rule its
type is read by; vocab skipped; a projector by the header's architecture first, `_gguf_kind`: `clip` is one
whatever the name, a file named `…projector…` whose header says another architecture is none — MiniCPM-o's
speech `…-projector-F16.gguf` was offered as the mmproj and its cell died on "Failed to load CLIP model",
while its real `…-vision-F16.gguf` (`clip`) was a "model", 2026-10-17 — and the name alone judges a file
with no header, one only a library holds; and no model at all a file `LoadsAlone` refuses: its header read through
(`headerKeys`, the reader's count of a header's keys) and naming neither a window (`<arch>.context_length`, which
llama.cpp's loader requires) nor speech (`stt.*`) — an importance matrix, LFM2.5-Audio's vocoder, the audio encoder,
flow, hifigan and prompt cache of MiniCPM-o, all eight offered as LLMs with a window "not known" until 2026-10-26; a
later part of a split model, an architecture a runner claims and a header nobody read stay), suggests
companions (the model's own quant folder, then the sibling `default/` folder HF downloads land in, then the
repository's other quant folders — and, for a draft, then every draft made for the model's architecture wherever the
library keeps it: `DraftPairing` reads the draft's header, whose architecture is the model's with `-mtp` after it
(Strata's one draft layer, `qwen4exp-mtp`, serves every `qwen4exp` pack, and no repository of the Coder's, Swift's or
Unsloth's ships it); `compatibleMmprojs` and `compatibleDrafts` hold up to five each, the first is
`suggestedMmproj` / `suggestedDraft`, and the cell form offers exactly those lists), detects the
family (`gemma-4-…` → `gemma4`) and applies `FAMILY_DEFAULTS`; embedding models (name hints or a
GGUF pooling type) get `embedding_family_defaults` instead — `--embeddings`, the right `--pooling`,
chat-only flags cleared, CTX right-sized to the trained context. `serve_model_file` streams a GGUF
over HTTP (traversal-guarded) — this is what client route-agents download models from. It and
`list_gguf_models` read the CONFIGURED models directory (`models_dir_from_config`, the one the picker
lists), so that every row offered can be downloaded; they once read `LLAMA_HOME/models`, which a
container does not fill. `scripts/check_models_dir_source.py` keeps the directory derived in one place.
Owns: `FAMILY_DEFAULTS`.
Key functions: `read_gguf_metadata`, `extract_runtime_meta`, `detect_family`,
`embedding_family_defaults`, `list_models`, `list_chat_templates`, `serve_model_file` (GET
`/api/models/download`), `list_gguf_models` (grouped listing for remote start).
`list_models` also lists the files only a usable library holds (`models/locator.rs`), in their places
and marked `libraryOnly` with their `store`; their header facts come from `LibraryMeta` (`models/memory.rs`), never
from reading the NAS.
The FIRST part of a split model (`…-00001-of-00003.gguf`, `Locations.split_part`) is the row the picker
offers for the whole model, so its `size` / `sizeGb` is the size of all the parts the list finds (here or in a
library), plus `parts` (how many the name says) and `partsFound` (how many were found); the later parts keep
their own sizes and no such fields, and a whole file has neither. Until 1.3.565 the row said the first part's
own size — `0.01 GB` for a 93 GB model whose first part holds the header only, so the form's estimate said it
fits anywhere — against the rule the models page and the ≈VRAM badge follow. The header lookup of a library
file still keys on the file's own size.
`ModelList` (one instance, `MODEL_LIST`) is the list the board follows: `/api/state`'s `models`,
`/api/models/rows` and the topology's `modelsStamp` all read it. It keeps `list_models()` for 5 s
(a beat per open board asks for the stamp; the walk is 4 ms warm on the controller) and
`current()` gives the rows and the stamp of the same walk. `stamp_of(rows)` is 16 hex characters of
the sorted path, kind, size, mtime and `libraryOnly` of each row.
One walk at a time (1.3.544): everyone who asks before the first list exists waits for the one walk, and
a list gone stale is made anew by one caller while the others are given the old rows. The controller
makes that first walk itself, in a background thread, when it starts (`startup.rs`), and `list_models`
writes the header memory out at its end. Before 1.3.544 the first `/api/state` after each start read
every header and waited 51 s for the 56 models of the NAS — the board's red "did not finish loading".

## `models/locator.rs`, `models/stores.rs`, `models/stores/`

Where a model file lives right now: on this disk (a local `stat`), in a library, or nowhere. A
library's files come from the registry's last look (`models/stores.rs`) — this process never touches
the NAS, since a dead NFS server makes `stat()` wait. A library counts only while it is really there
(`ok`, `low-space`, `read-only`). The board and the picker read the snapshot without waiting
(`current_locations()`); a start asks for a fresh one (`wait=True`).
`Locations.library_file(path)` answers the same for a path as this host reads it — the size a
library's last look gave it, all parts of a multi-part GGUF; a path under a library that is not
usable now is unknown, and nothing may look there.
Key functions: `Locations.locate`, `Locations.library_entries`, `Locations.library_size`,
`Locations.library_file`, `current_locations`.

`MountFacts` (`models/stores/mount.rs`) answers what the card shows when a store is NOT ok: what this host has mounted at
that path (`/proc/self/mountinfo`, the last mount wins — that is the one a reader gets), whether the
machine the source names answers a knock on its port (2049 for NFS, 445 for SMB; a device names
nobody and the answer is "not known", never "silent"), and whether `/etc/fstab` carries a line for
the mount point. All of it is this host's own files plus one connect with its own deadline — none of
it can wait on a dead share the way a `stat()` on the mount point does. `StoreRegistry.repath`
points a library at another path when the share or its mount point moved: a library is its mark, not
its path, so the new folder must carry the same mark (`other-library` otherwise), and the rest of
the refusals are Add's.

## `models/memory.rs`: `LibraryMeta`

A GGUF header's runtime facts for the files that live in a library: read from the local copy just
before a move deletes it (`models/moves/` → `remember_header`) and kept in
`state/library-meta.json` by library, path and size — a different size under the same name is
another file and gets nothing.
Key functions: `LibraryMeta.lookup`, `LibraryMeta.remember_file`, `library_meta`.

## `models/gguf_header.rs`

What a GGUF header says, out of its key-value block: `GgufHeader.read(path, limit_keys=256)`. A header is mostly
the tokenizer — tokens and merges, a hundred thousand strings and more, and as many scores and token types — and
the controller wants a dozen facts of it (the keys of `WANTED` and the ends of `SUFFIXES`). Those are read, the arrays that
have one item for each layer (`PER_LAYER`: the KV and query heads, the flags of the windowed layers) up to `LAYERS` (1024)
items, any other up to `KEPT` (32); every
other value is passed over: a number array by its length, a string array by the lengths in front of its strings, in
one loop that unpacks nothing else. The old reader unpacked every item, one by one (51 s for the 56 models of
the NAS; 7–9 s now, 0 files that say anything different, 16 MB the longest header). The file is read from its start
in blocks of `BLOCK` and never mapped: a mapped file that is cut short while it is read kills the process (SIGBUS),
and a download or a move may do exactly that. A header cut short, a version below 2, a file that is no GGUF, a
length no header has (past `LIMIT`) all say `{}`; a half-read header says nothing rather than half of it.
`contract/gguf_meta.json` holds what it reads.
Key functions: `GgufHeader.read`, `GgufHeader.facts`, `GgufHeader.skip_strings`.

## `models/memory.rs`: `HeaderMemory`

What the headers of GGUF files said, kept in the process and across starts: `HeaderMemory.recall(path, mtime,
size)` and `remember(...)`, written by `flush()` to `state/gguf-headers.json` (`gguf_headers_file`, `{"format": 5,
"files": {path: {mtime, size, meta}}}`). A file counts as the same only when its second and size are the same.
A header that said nothing is kept in the process but never written: the next start reads it again, and by then
it may say something. A file the code did not write (another format, wrong shapes) is read as no file — the format moves when
the facts grow (first at 1.3.601), so the first start after it reads every header again, once (7–9 s for the NAS's library); past
`CAP` (4000) files the ones remembered longest ago leave the disk; a disk that cannot be written to is said once
and does not stop the walk. `list_models` flushes at its end; `read_gguf_metadata_cached` is the one reader.
Key functions: `HeaderMemory.recall`, `HeaderMemory.remember`, `HeaderMemory.flush`, `header_memory`.

## `models/gc.rs`

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

## `models/defaults.rs`

What a model's maker stated once, kept as a table a guard can read: 12 folders, 34 values. `modelParams` is prose
for a person, and 28 of the 59 cards name a value twice — once for the mode with reasoning, once without, or as the
model's trained context and once as an example in a command — so a number read out of prose is a choice, not a fact.
Only what a card states once, in a sentence that names no mode or use, is here; `contract/model_defaults.json` keeps
the sentence each value came from, and `scripts/check_model_defaults.py` reads every number back out of its own
sentence, holds the field to the name the program gives it (`ConfigFields::ALL` and the flag in `config/args.rs`), and
refuses a sentence that names a mode or a use ("для текста", "картинка") without saying the value holds for all of
them — the word is read at the start of a word, so that "Контекст" is not a sentence about a use. A penalty is not a
row: the cards name presence_penalty and repetition_penalty, but the caravan writes no flag for a penalty, so a cell
cannot say it; and the port, a key, a path and a runner are the cell's facts, not the model's. `answer()` sends the
table to the page under the key `defaults` (the model texts) and to the launch builder under `makers`
(`RunnerPresets::list`): the preset a model's default cell became on 2026-11-07. `values(model)` is what the retirement
of the default cells holds a slot to (`fleet/default_cells_retired.rs`).
Owns: the maker's numbers. The sentences are the other half of the same fact, in the contract file.
Key functions: `ModelDefaults::TABLE`, `ModelDefaults::FIELDS`, `ModelDefaults::values`, `ModelDefaults::answer`, `ModelDefaults::rows`.

## `proxies/service.rs`, `proxies/service/units.rs`

`systemctl --user`, for what is left of systemd around the controller, and never in a container.
What is left: the legacy single service (`llamacpp-current.service`: status and repair), the chip of the
controller's own unit outside a container (`unit_brief`), and who listens on a port (`ListeningPorts`,
`proxies/service/ports.rs`). The proxy is no unit: it is the controller's child (below), and a routes save
does not bounce it: it reads the file by its stamp, and a restart cut every request in flight on every
port. `diagnostics` produces the bus/service/HTTP checklist shown in the UI; it asks the service's port
(the probe `status.rs` hands it, `/props`) only while the unit is active — asked always, any other server
on that port read as the legacy server "ready" — and an active unit nobody probed reads "not asked". The
service's journal tail (`logs`) went in 1.3.485: no page showed it. The per-port cell units
(`lama-cell@<port>.service`) and their template went with the controller's own cells in step 6.9: its
machine's cells run through that machine's scout.
Owns: —.
Key names: `Services` (`systemctl`, `service_status`, `unit_brief`, `diagnostics`, `repair_user_service`).

## `proxies/entry_settings.rs`, `proxies/as_consumer.rs`, `common/entry.rs`

`EntrySettings` — where the entry for keys listens and the address consumers are given
(`rust/crates/proxy/src/front.rs`, visumap `caravan-single-entry`). `write` takes `{port, publicUrl}`:
the port must be nobody's — not a route's, a cell's or an excluded one (`_all_taken_ports`),
and nothing else may listen there (409); null or 0 closes the entry, refused while any
route's port is closed, since its agent would have no way in. A client of the entry
(`kind: "consumer"`) is refused by name ("client X calls the caravan only through the entry:
delete it…"): its number is a record's, never a port to open. The controller's watchdog
(`proxies/service.rs`) reads the config and starts the proxy on that port, moves it or ends it. `publicUrl`
(`https://caravan-api.example.org/v1`) is words for the board; the proxy never reads it.
`proxies_config.KeyAudit` refuses on every save a key two routes share and a closed port
without a key; the entry's port is in `_all_taken_ports`, so no route is minted onto it,
and `load_agent_proxy_config` carries `entry` through every writer that starts from it.
`ConsumerAddress(config, host)` is the one rule for where a consumer calls the caravan: its
route's own port while it is open, the entry once it is closed (the public name, else the entry's
port on the controller's machine); a closed port whose entry is off keeps its port's address.
The board's proxy rows (`endpoint`, plus `keyTail` — a key's last four characters), the agents'
cards (`_assignments_at_current_address`) and the topology's `entry` (`{url, port, publicUrl}`) read
it. `PortDoor` reads the proxy's own word on where its ports listen (`listenHost` in its state file,
fresh by `ProxyHeartbeat`): on a loopback address — the NAS, whose ports have no door — only this
machine reaches them, so `ConsumerAddress(config, host, door=False)` gives an open port no address
(`""`) and the entry only its public name; the topology hands the door to the board
(`portsReachable`: true, false, or null while the proxy has said nothing fresh). The board handed out
`http://<NAS>:23001/v1` for a new port there (2026-10-08).
A route's own port does not listen since 2026-11-02, and the entry answers the key of a route that is no consumer 403
(`entry:not-a-consumer`). Reopening a closed port answers 410 (`ProxiesConfig::own_ports_gone`); the ways to make a port and to give
one a key (`POST /api/agent-port`, `/api/agent-proxies/route-key`) left the program.
`AsConsumer` asks the entry as a client, with its key, for the client's card in Routing: its two
questions by GET (`ask`) and one test per kind of work by POST (`probe`, the table `PROBES` of
`ClientProbe`s — the shortest standard request of each kind). Speech is the one test that names a
voice (`voiced`): `ProbeVoice` (1.3.615) takes it from the pool the client calls — the first row
switched on, a cell no machine runs passed by, then the cell's first voice (its runner's own,
LFM2.5-Audio's; else the first its server lists, the model's own before the kept ones, as the voice
window lists them) — and the test asks WAV. An account's row, an engine's, a cell that speaks no text
and a model the client does not call get OpenAI's `alloy`; a cell with no voice refuses the test
(409) before anything is sent. Until 1.3.615 the test asked `alloy` as mp3 everywhere, and every
speaking cell of the caravan refused it.

## `cloud/consumers.rs`, `cloud/entry_move.rs`

`ConsumerDesk` — a consumer of the entry as the board makes it (the owner, 2026-10-11: the caravan
speaks the OpenAI API as a company's gateway does). A consumer is a name and its own key; since 1.3.675 (the owner,
2026-10-27: "every client we make has every model and every pool … sets seem not to be needed") it sees every pool and
every model that runs, but what is blocked for it (`deny`, a list of keys — `pool:<id>`, `model:<place>`, `account:<id>`,
`host:<hostId>`: `ClientDeny`, rust/crates/rules/src/entry_models.rs) — kept as a route of kind `"consumer"`: the journal, the
queue and the board know a route, and the route's number is its name in all of them. The number comes from the proxy range
(`next_free_proxy_port`) and never listens: the route is `portClosed`, and the entry is the consumer's
only way in, so `create(name)` is refused while the entry is off (409). A new consumer blocks nothing (`deny: []`; the
owner: "everything, at once"). A name another consumer has is
refused (409, compared without case: `clean_name`, which the route's door asks too when a consumer is
renamed — until 2026-10-11 a rename took any name); an empty name is 400. `set_deny(port, deny)` (`POST /api/consumers/deny`)
replaces what is blocked for it: a key of a kind `ClientDeny` does not know, or one naming a pool, a model or a source the
board does not have, is 400 — refused, not dropped; a key the client already had stays even when what it names is gone, so a
save does not fail on it, and the board shows it as gone. `new_key(port)` replaces its key in the same write, so the
old one stops working at once. A key is answered once, by `create` and `new_key`; the board gets only
its last four characters (`topology._board_proxy` drops a consumer's `apiKey`), what is blocked for it and the models
its key calls (`annotate_consumers` → `deny`, `models`, read by `rust/crates/rules/src/entry_models.rs`, the rule the proxy routes
by; `models` is null when the models a client calls without a pool could not be read), and what it called over three days
(`annotate_consumer_calls` → `calls`, cloud/misses.rs `ClientCalls`), which Routing draws its cables by. What
every client is read against is read once for all of them (`topology.entry_reading`: `entryModels`, the names a client
blocked for nothing calls; `denyChoices`, what can be blocked; `liveCatalog`, every model the board knows with its pool of
one row and whether it runs — all null when the reading failed, never `[]`). A save from the page keeps a consumer's key and
refusals it does not carry (`proxies_config.PolicyOwnedFields`). Rename and delete go through the
route's own doors (`route-policy` with `label`, `route-delete`). A consumer feeds no router:
`router_dsl.normalize_agent_proxy_route` keeps its `routerId` empty, `normalize_routers` does so for a
raw route too, and `route-policy` with `routerId` is 400 for it. `migrate()` runs once at the
controller's start (`entry-sets-gone-2026-10` in the cloud file's `migrations`): every consumer drops what said what it saw —
its set (1.3.497–1.3.674), its one pool (1.3.486–1.3.496) or the pools it might call (before 1.3.486) — and starts with nothing
blocked (the owner: "start with empty denies"); the sets leave the cloud file. It answers what each client had and the sets
that went, which `EntryMove` keeps for Routing's window of the move. The ↑☁ rule leaves a consumer alone.

The built-in client, Open WebUI (the owner, 2026-10-27: made at install, first on both boards; it sees what any client sees —
`rust/crates/rules/src/entry_models.rs`, `BuiltinClient`, `LiveModels`). A consumer
whose route says `builtin: "open-webui"` — never its name, which the operator may change. `ensure_builtin`
runs at every start (`entry: the built-in client … made` in the log) and makes it when the caravan has none:
an entry that is off is opened first on `KeyEntry.DEFAULT_PORT` (23999; the owner: "the install opens the
entry itself"), and one that cannot be opened leaves the client made, the reason said. Its key was shown to
nobody: its card gives one (`new_key`). It is not deleted and has no off switch: the one writer of the routes
refuses a write that loses it or makes a second one (`write_agent_proxy_payload` → `BuiltinClient.audit`,
409 — a ✕, a page's whole list, any door), and `EntrySettings.write` keeps the entry on while it is there
(409).

A second built-in client, opencode (1.3.673; the owner, 2026-10-27: "let it work the same way"), is a kind of
the same table (`BuiltinClient.KINDS`, in the order they stand: its name, and whether it writes its models down):
`builtin: "opencode"`. Made at start as Open WebUI is (`ensure_builtin(kind=…)`, one per kind, "opencode 2" when a client has
the name), not deleted, one of its kind (`audit` per kind). opencode reads no /v1/models — its models are written in
opencode.json — so the board gets the list it is configured with (`annotate_consumers` → `offer`, `EntryModels.offer`): every
pool not blocked for it, each named with the models it tries in turn (`chain`), then every model the board knows, running or
not (the owner: "all known": a stopped one answers 503), but one blocked for it and one that does not chat
(`LiveModels.chats`: an ear, a voice, an embedding; one that says nothing is offered).
Owns: nothing in memory; the consumers live in `agent-proxies.json`.
Key names: `ConsumerDesk` (`create`, `set_deny`, `new_key`, `migrate`, `ensure_builtin`).

`EntryMove` (`cloud/entry_move.rs`, 1.3.675) — the move to clients without sets, as Routing shows it once. What each
client had is in no file after the move, so `ConsumerDesk.migrate`'s answer is kept in the board's state (`entryMove`:
`record(moved)`), and `state(entry_models)` says what the window shows until the operator answers it (`seen()`, `POST
/api/entry-move/seen`): each client with what it had, the sets that went, how many models a client blocked for nothing sees now,
and the twins as they stand now — the pools of one enabled row named as that row's model (`twins`, compared as names are) that a
client now calls straight by the same name; a pool whose row is off, names a model the board cannot read, or names one that is
in two places (each called with its place in brackets) is no twin: deleting it would change what the name reaches. The window
deletes the ticked ones through `POST /api/pools/delete` (the owner: "delete them"; a pool goes only through a window).
Key names: `EntryMove` (`record`, `seen`, `state`, `twins`).
Owns: `entryMove` in the board's state (`admin.json`).

The entry's own settings — owns: nothing (the entry lives in `agent-proxies.json`).
Key names: `EntrySettings` (`read`, `write`), `entry_settings`, `ConsumerAddress`, `PortDoor`; `KeyAudit`,
`RouteKeys`, `PolicyOwnedFields` in `proxies/config.rs` and `proxies/config/`.

## `fleet/machine_scout.rs`

`MachineScout` — the scout on the controller's own machine, which does there what the controller
once did itself: powering the machine (`fleet/host_power.rs`, the reserved id `controller`), its GPU
driver (`fleet/gpu_driver.rs`: the scout reads the facts — `GET /api/host/driver` — and runs the install;
the controller decides what to offer, the two reboot reasons and the watcher's schedule), the
monitor's GPU reading (the scout's second-by-second telemetry), the list of its cards (`gpu_state`:
the scout's last report, `host()`, with `gpuError` — nvidia-smi's words when it named no card,
scout 2.25+), the busiest processes and the nvidia-smi and btop snapshots (`monitoring/`; a btop
frame is still drawn here). One way natively and in a container: a controller in a container has
no machine to ask, and the controller runs no machine program of its own any more — the journal
tail and the user-service repair, its own, ask `paths.is_container` (`proxies/service/units.rs`);
`scripts/check_container_answers.py` holds every program the code runs to a decision. `ControllerMachine` names the
scout by the machine's name. A machine with no scout says so (`NO_SCOUT`: 409 for an action, the
reason in the panel for a reading); a scout that refuses or does not answer says that in its own
words (`fleet/scout.rs`). After a read of a path fails, that path is not asked again for
`FAIL_PAUSE` (10 s) — the monitor reads every second — per path, since an older scout lacks some
paths and answers the others. Needs scout 2.24+ for the driver, the processes and btop.
Owns: the per-path failure pause.
Key names: `MachineScout` (`host_id`, `host`, `scout`, `read`, `post`, `NO_SCOUT`), `machine_scout`.

## `proxies/service/ports.rs`

Which local TCP ports are listening, and whose, read once from the kernel's own table
(`/proc/net/tcp` and `tcp6`) instead of `ss -ltnp` run per port: the scan of the cell range ran
`ss` a thousand times, and the container image has no `ss`, so there every port read as free.
A container on the host's network reads the host's table. The owner is found the way `ss` finds
it, by the socket's inode among the open files of the processes this user may see; anyone else's
socket is busy with an unknown owner, `(0, "?")`. Where there is no table (not Linux), `known` is
False and the cell-range scan reports the machine as not scanned rather than clean.
Owns: —.
Key names: `ListeningPorts` (`known`, `busy`, `owner`, `ports`).

## `fleet/cell_words.rs`

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

## `fleet/llama_metrics.rs`

llama-server telemetry primitives. `parse_llamacpp_metrics` extracts a fixed set from the Prometheus
text: live gauges (requests processing/deferred, KV usage, lifetime-average t/s) plus the cumulative
token/second counters — those advance only at request completion, which is what per-request
throughput is later derived from. `runtime_metrics_sample` scrapes `127.0.0.1:<port>/metrics` (3s
timeout; a failed scrape is `ok:False`, never a fake zero). (`runtime_phase`, the legacy single
server's phase from its unit and four probes of its port, went in 1.3.485 with the `runtime` it
filled: no page read it.)
Owns: —.
Key functions: `parse_llamacpp_metrics`, `runtime_metrics_sample`.

## `models/hf.rs`, `models/hf/local.rs`

HuggingFace REST browser over the public API, with a 5-minute `TtlCache` and optional bearer auth
from `admin_state["hfToken"]` (token participates in the cache key). Every read of the hub takes its
headers from `_hf_headers`, `config.json` of a repository (`_fetch_repo_config`, the checkpoint's label comes
from it) included: a gated repository refuses any file to a request with no token whose owner has the terms. `hf_search` returns
GGUF-filtered repos sorted by downloads with modality hints (pipeline_tag/tags) straight from the
search response; a query containing `/` is treated as a direct repo id. `hf_list_files` lists a repo
tree (read to its end, page by page: `HubPages`), classifying `.gguf` files (model/mmproj/mtp/vocab) and extracting the quant from the filename (the
`-00003-of-00006` tail of a split model's parts is cut off first: the parts of one model share one quant, and the quant names the folder a download lands in);
the rest of a repo with safetensors weights is the `safetensors` plan the page downloads as one
artifact (the weights, configs, tokenizer, a repository folder kept as a folder — not the README,
pictures, licences or the weights again as `.bin`/`.pt`). Every file entry, GGUF or not, carries what
the hub says of its bytes, read once by `HubHash`: `oid` (the LFS sha256, empty when none),
`gitOid` (the git blob id of an ordinary file) and `hashHidden` (a gated repo's mask).
`hf_local_check` / `hf_local_delete` inspect and remove local GGUF copies under
`<models>/<model>/<author>/…` (delete is traversal-guarded and prunes emptied directories);
`hf_local_check` also names `checkpointFolders` — the folders there that hold safetensors weights —
which is all the page needs to offer the verify for a repo with no GGUF file.
Owns: `_hf_cache` (TtlCache 300s).
Key functions: `hf_search`, `hf_list_files`, `hf_local_check`, `hf_local_delete`, `_hf_request`
(shared by benchmarks).

## `models/hub.rs`: `HubHash`

What the hub says about the bytes of one file, said once. A tree entry's `oid` means three things: the
sha256 of the content in an LFS entry (`lfs.oid`), the git blob id (a sha1) in an ordinary entry, and
64 asterisks where a gated repository's terms have not been accepted. `HubHash` reads an entry into
one of four kinds — `sha256`, `git-sha1`, `hidden`, `none` — and writes them into the listing as
`oid` / `gitOid` / `hashHidden`; `from_entry` reads those back, so a mask that reached `oid` is no
hash. The mask used to read as a hash, and every file of a gated repo "differed".
Owns: —.
Key functions: `HubHash.from_tree_item`, `HubHash.from_entry`, `HubHash.fields`.

## `models/hub.rs`: `HubPages`

A list the hub sends in pages, read to its end. A repository's tree with file details comes 50 entries
to a page, and the hub names the next page in the `Link: <url>; rel="next"` header. The first page was
taken for the repository: `openbmb/MiniCPM-o-4_5-awq` (75 files) listed the folder `assets/` first, the
weights after it, and its checkpoint row read "34 files · 1.4 GB". `HubPages.read` asks for 100 to a page
(the most the hub allows with `expand`), follows only a next page of the hub's own API (the request carries
the operator's token) and fails when the list cannot be read to its end, instead of handing back the pages
read so far. `hf._hf_request(path, all_pages=True)` is its one caller; a search is read one page.
Owns: —.
Key functions: `HubPages.read`, `HubPages.next_url`, `HubPages.sized`.

## `models/hub.rs`: `HubAccess`

Why the hub shut the door on a download, and the page where a person opens it. A gated repository lists
its files and refuses them (401, 403) until the owner of the token accepts its terms on its page.
`HubAccess.is_wall` names the refusal — the same answer every time, so `models/downloads.rs` does not retry it —
and `HubAccess.after` reads the repository's record once: a wall at a gated repository becomes the job's
`access` (`{kind: "gated", url, repo, status, tokenSet}`), a wall at an open one, an unreadable record and
every other failure name no page.
Owns: —.
Key functions: `HubAccess.is_wall`, `HubAccess.after`, `HubAccess.page`.

## `models/verify/copy.rs`

A safetensors repository on the models disk, for the verify. `CheckpointLayout` is the server's twin
of the page's rule (`<model>/<author>/<label>/`, each file keeping its folder of the repository —
`HfDownloads.checkpointDir` / `checkpointFileDir`), held against it by one table of cases
(`scripts/test_hf_checkpoint_layout.py`). `CheckpointFinder` finds the copies: every folder under
`<model>/<author>/` that holds a file of the plan, whatever its label (the label comes from the repo
name and config.json at download time and a gated repo's cannot be read, so today's label may not be
the one the copy was filed under); it looks and stats, and reads nothing. `CheckpointFile` decides a
file's row — `same`, `differs`, `wrong-size`, `missing`, `size-only` (the hub gave no hash: checked by
size only, and the row says so) or `unreadable` — and says which rows need the hash computed.
`CheckpointResult` is what a job knows of one copy as its rows come in, with a `summary` that counts
what is still `pending`.
Owns: —.
Key functions: `CheckpointFinder.copies`, `CheckpointFile.settled`, `CheckpointFile.judged`.

## `models/verify.rs`

Checking local files against Hugging Face by content, on a button press. A job runs in a thread with
progress in bytes; one job per repository. GGUF files are hashed against the LFS sha256 (`files`, by
name: `same`, `differs`, `unknown`, `unreadable`, each with the `hash` kind the hub gave). A
safetensors repository answers in `checkpoints`, one entry per folder holding a copy: a missing file
is named, a file of another size is named without being read, a file whose hash the hub gave is
compared (the sha256 of an LFS file, the git blob id of an ordinary one), and one whose hash is
hidden or absent is `size-only`. Rows that need no reading are settled when the job starts; the
digest cache is keyed by (kind, path, size, mtime in ns) and lives in process memory.
Owns: `_jobs`, `_hash_cache`.
Key functions: `start_verify`, `verify_status`, `file_digest`, `file_sha256`.

## `models/downloads.rs`, `models/downloads/interrupted.rs`

Background HuggingFace GGUF downloads. `start_hf_download` registers a job (id, repo, per-file and
total byte counters) and spawns one thread per job; the thread streams each file in 1 MiB
chunks into `<models>/<destDir>/`, updating progress under the jobs lock. A silently truncated
stream (HF CDN closing early) is detected by byte count and retried from the bytes on disk; when the
retries give up, the job is marked `error` and the partial stays, never under the model's name — so a
short GGUF is never served as a valid model. Finished job records are pruned
300s after completion by the `/api/hf/download/jobs` handler.
The job lives in memory; on the disk, beside the file in progress, its partial `<name>.part` and the
manifest `<name>.part.json` (repo, path, size) also name the files of the job after it (`rest`, since
2026-11-03). A restart leaves only the disk: the interrupted row is the job the partial was part of —
its file and the files after it that are neither on disk nor written by a running job — and Resume
starts that one job (`InterruptedJob`). Before, the row was the partial alone, and the resume of a
five-file set brought one file. A manifest whose list of the other files cannot be read is refused,
not guessed.
A cancel (`cancel_hf_download`, from `POST /api/hf/download/cancel`) raises a flag the thread
checks before each file and after each chunk: the job ends `cancelled`, is never retried, and the
bytes already fetched stay as a partial with its manifest — listed as interrupted and resumable at
once (the scan cache is dropped); a partial with no bytes is removed.
The hub's own wall (401, 403) is not retried and, at a gated repository, puts `access` on the failed job
(`HubAccess`): the page the /hf page opens so the terms can be accepted.
Owns: `_download_jobs` + `_download_jobs_lock`; job worker threads.
Key functions: `start_hf_download` (returns job id; status polled via `/api/hf/download/status`),
`cancel_hf_download`, `scan_interrupted_downloads`, `resume_interrupted_download`.

## `benchmarks/`

Model quality metadata for the HF browser. Three sources: Artificial Analysis Intelligence Index
(regex-scraped from score/detailsUrl pairs embedded in AA model pages — one page carries ~a dozen
models; 1h HTML cache plus a persistent slug→score map with a negative cache), the Open LLM
Leaderboard v2 (the whole `open-llm-leaderboard/contents` dataset paged through datasets-server by a
**lazy background thread** — `_ensure_llm_lb` starts it on first use, 24h TTL), and arena ELO.
`hf_get_reference_models` serves a curated frontier-model list: hardcoded scores instantly, live AA
refresh only on explicit force (12h cache). `hf_get_benchmarks` combines the sources per repo
(inferring base models for GGUF repos) and persists results as JSON under `state/bench-cache/`.
Owns: `BenchMemory` in `App` (the fetched pages, the AA slug map + negative cache, the frontier list, the leaderboard's
index + its loader thread), `state/bench-cache/` files.
Key functions: `hf_get_benchmarks`, `hf_get_aa_scores`, `hf_get_reference_models`,
`hf_bench_search`, `_ensure_llm_lb`/`_llm_lb_status` (used by the status route).

## `fleet/terminal.rs`

Pure ANSI terminal-frame renderer used for btop snapshots in the monitor panel. Emulates a rows×cols
screen: cursor addressing (`CSI H/f`), screen/line erase, SGR reset/bold/39 and 24-bit foreground
colors; everything else is dropped. Produces either HTML spans or plain text of the final frame.
Owns: —.
Key functions: `terminal_frame_to_html`, `terminal_frame_to_text`.

## `proxies/dsl.rs`, `proxies/dsl/graph.rs`

Router/graph normalization — pure validation, no file I/O. The proxy decides by no graph since
2026-11-02: the routes keep theirs, for the board and for a way back, and a client's pool's rows decide. Defines the default router
(`router:default`) that always exists and the default output (the controller's llama-server at
`127.0.0.1:8080`). `normalize_router` validates outputs (llama or cloud; cloud outputs carry
`accountId` and have unlimited concurrency), legacy rules (`default`, `schedule`, `bySource`,
`failover` chain, fleet-wide `audioOutput`/`embeddingsOutput` short-circuits) and the optional
n8n-style DAG (node types byModel / schedule / weighted / roundRobin / failover / queue /
requestType; edges reference `in:<proxy>` / `rule:<node>` / `out:<output>`, an edge to an output of a kind
it knows — `srv:`, `cb:`, `eng:`, `mm:` — kept even while that output is not there; no output is named `srv:<port>` since
2026-11-07, and such an edge of before leads nowhere). Garbage in a graph is dropped, never
raised — a malformed graph degrades to legacy rules. Router `inputs` are never trusted from disk;
they are derived from the routes.
Owns: `DEFAULT_ROUTER_ID`, `ROUTER_NODE_TYPES`.
Key functions: `normalize_router`, `normalize_router_output`, `normalize_router_graph`,
`normalize_schedule_rule`, `normalize_by_source_rule`, `normalize_agent_proxy_route`,
`normalize_agent_proxy_policy`, `recompute_cloud_fallback_eligibility` (keeps ↑☁ flags consistent
with graph connections).

## `fleet/engine_actions.rs`

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
`EngineActions.pull` downloads a model into an engine (scout 2.17+); `act` unloads a
model or deletes it. No model is loaded from here since 2026-09-26: a cell in its
engine loads it when it starts, and `EngineReport` keeps no load — not the control,
not a mark of one, not how long a load would hold the model. `EngineReport` keeps
the download under way (`downloading`) and the last one refused (`downloadError`).
Key functions: `EngineActions.act`, `EngineActions.serve`, `EngineActions.pull`;
`POST /api/engines/unload|delete|pull|start|stop`.

## `fleet/engine_cells.rs`

`EngineCellPlan` — a cell reserved to run inside an engine next to it (2026-09-25). The operator
says where a new cell runs: the caravan itself, Ollama, or LM Studio on that machine; for an engine
the reserve takes the model too, and the slot is born with `{RUNNER, CELL_KIND: "command",
ENGINE_MODEL, ENGINE_PORT}` — the runner, the model as the engine names it, and the engine's port
from the machine's report. The engines a cell can run in are the runners with `engine_cell`
(`EngineCellMixin`); the registry sends it as `engineCell`. Refused in words, before a port is
taken: an engine no runner serves, a machine with no report, a scout older than 2.12, an engine not
reported, an engine not ready (each state its own words: stopped, not answering, asks for a token),
an engine that did not list its models or has none, no model, a model it does not have. The engine
is asked about before the model: a board that found nothing to choose from sends no model and hears
why. No slot `model` is written — the engine's model name is not a file (the garbage collector and
the start read that field).
`EngineCellFit` — whether the model of a cell in an engine fits into its machine's cards, asked
before the cell starts it (2026-09-26: the question the board's load asked moved to the start of the
cell that loads the model now). "At least": the model's file (`fileBytes` in the engine's report)
against the free memory of all the machine's cards together (`memoryFreeMiB`); `short()` is
`{model, needBytes, freeBytes, basis: "weights"}` when it would not fit, None when it would — and
None when a side is not known (no size, a card that does not say, no card), when the model is loaded
already, or when it runs on the engine's cloud. `server_cell_action` answers a `start` or `restart`
of such a cell with `{ok: false, …, short}` unless the request says `force: true` (a JSON true);
an autostart has nobody to ask and is not checked.
Key functions: `EngineCellPlan.from_body`, `EngineCellPlan.config`, `EngineCellPlan.kinds`,
`EngineCellFit.short`.

## `fleet/engine_outputs.rs`

The models of engines next to the cells (Ollama, LM Studio — found by the
machines' scouts, kept by `EngineReport`) that the operator made router
outputs: `EngineOutputs`. An output is `eng:<hash>` of (machine, engine kind,
model name) — no `:` or `/` of a model name in an id read by prefix, and no
port, so an engine that moves keeps its edges. An exposed model whose machine
is on the board is always an output, even when it cannot work (engine stopped,
model removed, engine on 127.0.0.1 of another machine): traffic says so (`OutputHealth`), and
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

## `fleet/machine_models.rs`

The models of a machine as its scout's entry lists them, and the router outputs
they become (1.3.506; step 2 of visumap caravan-scout-openai: the machine is a
provider, a pool's row names "machine + model"). The scout serves the machine's
models at one address by OpenAI's API (scout 2.27); both its reports carry the
list, `entryModels` (scout 2.28), with each model's places (scout 2.29).

`MachineModels.clean` keeps each model's name, state (running, starting,
failed, stopped; another word is `unknown`), places (`slots`, `busy`) and copies
(`{port, state, slots, busy}`) on the machine's record — None when the scout
does not say (older than 2.28), [] when it says the machine has none.
OpenAI's wrapper of each model (`object`, `created`, `owned_by`) is not kept.

`MachineOutputs.outputs` makes each listed model an output, `mm:<hash>` of
(machine, model name): no `:` or `/` of a name in an id read by prefix, and no
port — a cell moved to another port, or a copy added, touches no pool row that
names the model. The output's address is the machine's entry, its scout's
`agentUrl`; `upstreamType: "machine"`, `upstreamModel` the model's name, which
the proxy puts into every request, `hostId` its machine. What the model does and
the window it serves are its copies' (`ModelKind.cell_facts` of the cells the
controller knows by their ids): the first copy's jobs and inputs, the
smallest window — a request may land on any copy. A copy the controller has no
record of says nothing; a model none of whose copies says anything carries no
facts, and its pool's kind and window are not known. A machine whose scout gives
no address or no list has no such outputs, and its cells none either: since
2026-11-07 a cell is no output of its own (`srv:<port>` named the port it held
whether it ran or not; now it holds one only while it runs, Papyrus
`caravan-scout-port-lease`), and a pool reaches it through its machine's model —
the running copies' ports ride the output as `copyPorts`. `topology_nodes` gives each node its `entryModels`, as its record
keeps them: the board reads a model's state and copies there. Since 1.3.655 the
output also carries `copyPorts` — its running copies' ports: the model list reads
from it that a copy runs; nobody dials them from outside the machine since its cells
listen on its loopback (2026-11-08), and the proxy waits for an entry that does not
answer instead — and `stopped` when none of its copies runs or
starts, so a pool passes its row by (as a stopped cell's). A report that changes
what the entry lists rewrites the routers' outputs in the background
(`fleet_clients.CellsFollow.models`).
Key functions: `MachineModels.clean`, `MachineOutputs.output_id`, `entry_address`, `outputs`.

## `fleet/machine_rows.rs`

Step 3 of the owner's plan (1.3.655): the pools' rows name a machine's models, not
its cells' ports. `MachineRows.run(hosts)` — at the controller's start and on each
machine's report (`record_host_report`, `heard`) — moves every row and schedule
naming a cell whose port one machine's entry lists to that machine's model
(`mm:<hash>`); two rows of one pool that come to name one model merge into the
first, switched on when either was (`recable`); a port no machine lists, or two
list, stays. `renames(before, after)` follows a model renamed between two reports
of its machine: one the entry no longer lists whose every port now carries one
other name. The file is copied before each rewrite (`.bak-machine-rows-<stamp>`,
the newest 10 kept) and the log names each row moved. `sole_model(host, port)` is
the model whose only copy a cell is: `CellOutputs.drop` takes its rows' cables with
the cell's. `MachineCells.of` tells the scout each cell's runner as this controller
names it (`runner_id`): copies are cells of one runner (scout 2.39).
Key functions: `listed`, `owners`, `renames`, `recable`, `run`, `heard`, `sole_model`.

## `fleet/machine_cells.rs`

The cells the controller keeps for a machine, as the machine's scout is told them (1.3.629, scout 2.37; step 3 of
Papyrus caravan-scout-openai). Until then the scout's entry listed only the cells it had started since its own start
or kept a start for: on 2026-10-25 it named 8 of the 17 ports the pools' rows led to. The answer to every heartbeat
(`POST /api/topology/client-heartbeat`) now carries `cells: [{id, modelPath, config}]` — the machine's configured
cells by their ids (by port until 2026-11-07: a cell holds a port only while it runs), `config` holding only the fields a model's name is made of (`MachineCells.NAME_FIELDS`: MODEL_NAME,
ALIAS, RUNNER, WHISPER_MODEL, MOONSHINE_MODEL, MODEL_FILE); a cell's key or any other setting never leaves the
controller. The scout names the models itself (its `entry.ModelName`), so the rule has one copy.

`SlotModel` is what a kept cell has to serve: its model as its runner names it (`cell_model_ref`), else the saved
`model`; a command cell's launch line (`effective_command`, "" when the builder fails). A cell with neither is
reserved. The board draws `stopped` vs `reserved` by the same rule (`topology/server.rs`), so a cell is configured in one place.
Key functions: `SlotModel.path`, `command`, `configured`; `MachineCells.of`.

## `fleet/model_cache.rs`

A machine's model cache as its scout reports it, and what the board asks of it (1.3.576; the owner,
2026-10-18, when a disk was 94 % full of model copies and a start died with "No space left on device": keep the
last models only, 1 to 5, 1 by default, the setting in a noticeable place, the older ones deleted by themselves).
The scout (2.34+, `rust/crates/scout/src/models/keeper.rs`) does the keeping and owns the rules; both its reports carry
`modelCache`.

`ModelCacheFacts.clean` keeps it on the machine's record: the setting `keep`, what the scout holds
(`managedBytes`), the files of the cache folder that it did not download (`foreign`: `files`, `bytes` and
the eight biggest `folders`) and the disk (`disk`: `totalBytes`, `freeBytes`). None when the scout does not
say (older than 2.34) or says a setting that is no setting; a part it said in a form that cannot be read
is None inside — never a made-up zero (a disk with 0 bytes free and a disk nobody measured are two different
things on a screen). A folder row that cannot be read is dropped and does not take a place of the eight.
The pull (`/api/state`) and the heartbeat carry the same block, so the record does not blink between them.

`ModelCache` carries the operator's word to the scout: `keep(host, n)` →
`POST /api/topology/client-llama/cache-keep` (the scout trims at once) and `delete_foreign(host, bytes)` →
`POST /api/topology/client-llama/cache-delete-foreign` (the scout deletes the files it did not download, only
when their size is still the size the operator was shown; it refuses with 409 otherwise, and nothing is
deleted). The number is checked here (a whole number), nothing else: the range and the refusals are the
scout's, and its words reach the caller unchanged (`Scout.post`). After an answer the machine's figures are
asked again and stored in its record, so a board read a moment later shows them and does not wait for the next
report. `topology_nodes` gives each node its `modelCache` (`static/js/model-cache.js` draws it).

Since scout 2.38 (1.3.649; the owner, 2026-10-26: «in GB, not in models», and «a folder of my choosing — an
HDD, not the SSD's writes») the block also says the budget (`budgetBytes`: bytes, or null while none is
chosen) and the folder (`dir`). The record keeps `budgetBytes` only when the scout said it — an older scout
says nothing, and "this scout cannot" stays apart from "none chosen" — and `dir` only as an absolute path.
`off(host, off, library)` → `POST /api/topology/client-llama/cache-off` (the owner, 2026-11-02: no copies on this machine's disk; a model is read where
`library` lies there, a start that cannot read it so is refused in words, and a cell started there is not mapped, as any read over the network) and
`clear(host)` → `POST /api/topology/client-llama/cache-clear` (the copies go, but for what a running cell holds).
`budget(host, bytes)` → `POST /api/topology/client-llama/cache-budget` (a whole number of bytes, or None to
take it off; the scout trims at once) and `move(host, path)` → `POST /api/topology/client-llama/cache-dir`
(the scout deletes what it downloaded into the folder it leaves — this controller's copies, which a start
brings into the new folder — and refuses while a cell is bringing its model; 300 s for a long deletion).
Key functions: `ModelCacheFacts.clean`, `foreign`, `disk`; `ModelCache.keep`, `budget`, `move`, `delete_foreign`, `refresh`.

## `proxies/config.rs`, `proxies/config/`, `store/proxies.rs`

`agent-proxies.json` I/O and mutation — routes, routers, policy. The controller **owns** this file; the
proxy only reads it (by its stamp, on each request). Every write funnels through `write_agent_proxy_payload`,
the single choke point: it recomputes cloud-fallback eligibility, re-normalizes routers against the
routes, and enforces graph protection — whenever the on-disk file has router-graph nodes it
snapshots an autobackup (`agent-proxies.json.bak-graph-<stamp>`) before every write, and if the
incoming payload would lose a non-empty graph it restores the old graph into the new payload. The
newest 20 of those copies are kept (`ProxyStore.backups_kept`) and older ones are removed on the
next write — there was no limit, and a copy per save left 13 678 of them beside the file (2026-09-20). Reads
migrate the legacy pre-rename schema (`switchboards`/`sb:default` → routers) idempotently.
`sync_router_outputs` auto-derives every router's outputs: one per engine model the operator made an output, one
`mm:<hash>` per model of each machine's entry (`MachineOutputs`), and one `cb:<pool id>` per pool
(`pool_output`: a pool is in Routing for as long as it is; with a one-time migration from legacy
`cloud:<accountId>` outputs), keeping `rules.default` pointed at a local output. A machine's model output
carries what its model does (1.3.502, `ModelKind.cell_facts`, common/model_kinds.rs) from its copies' cells: its
`jobs` by the record rule (`model_jobs.cell_jobs`, the twin of the board's `cellJobs`), a chat
cell's `inputs` by llama.cpp's own `/props`, the `languages` and `maxAudioMs` it says on its health
path, the `contextLength` it serves — each only when known, kept by `normalize_router_output`
through `ModelKind.clean_facts`. Until 2026-11-07 a cell that stood still carried `stopped: true` (`STANDING_PHASES`, 1.3.645) and a
pool passed its row by; a cell is no output now, and a machine's model none of whose copies runs says so by its state. The outputs are rewritten by every board read
(`topology.RouterOutputs.sync`) and, with no board open, by a machine's report — heartbeat or pull — that changed
what its cells do (`fleet_clients.CellsFollow`, 1.3.647): in the background, one rewrite at a time and one more for a
report that came during it (`scout_poll.Rerun`), so a cell its machine started by itself loses its mark within a
report. The proxy tells the entry's clients a model's kind from them, and
counts a cell's window in its pool's; the topology build marks each pool with its `kind`
(`annotate_pool_kinds`: jobs and a chat's inputs, `{"mixed": true}`, or None) for Routing.
`save_agent_proxy_config` validates + dedupes routes by port, refuses a NEW port outside the proxy
range the firewall lets in (`proxy_ports` in `paths.rs`, 400 before anything is written; a port
already in the file keeps working) and writes. It never restarts the proxy: the proxy reads the
file live, and a restart cut every request in flight. The caravan never
runs ufw: the operator opens the range once (`check_firewall_untouched.py`). The allocators
(`_next_agent_port`, `next_free_proxy_port`) stop at the range's ceiling with a 500 that names it. `set_routers` and the policy setters write the same way.
`ProxyRevisions` names the version of `routes` and `routers` as stored (a digest per list, read
by `topology_state` from the same reading it draws from, `proxyRevisions` in `/api/topology`).
`save_agent_proxy_config(..., revision)` and `set_routers(..., revision)` check it under one lock
with the write and refuse a list built from an older version (`StaleCopy`, 409): a tab left open
since the morning saved its copy over the afternoon's and put back a deleted port's cable on the
NAS (2026-10-08). No version given — a script's save — passes; background writers take no lock.
Owns: `agent-proxies.json` and its `.bak-graph-*` autobackups; `DEFAULT_AGENT_PROXY_ROUTES`.
Key functions: `read_agent_proxy_payload`, `write_agent_proxy_payload`, `load_agent_proxy_config`,
`save_agent_proxy_config`, `normalize_routers` (default router always exists, orphan routes
re-pointed — `""` stays deliberately unassigned, a client of the entry whose router is gone goes free, inputs derived; through `PortInputs` a graph keeps
no cable and no wait budget of a port no route has, on every read and write and before the graph
is normalised, so a model's queue does not count such a cable — the graph names a port by its
number, and a stale page once wrote a deleted port's cable back for the next port of that number;
an unassigned port keeps its cables, unassigning deletes nothing), `sync_router_outputs`,
`set_agent_proxy_policy`, `set_agent_proxy_route_policy`
(label/mode/priority/preemptible/upstream/routerId/threshold overrides), `set_routers`,
`remap_router_output_refs` (a cell moved to another port) and `swap_router_output_refs` (two cells
swapped ports, one pass) — both rewrite through `proxies/output_refs.rs`.

## `proxies/output_refs.rs`

`RouterOutputRefs` — every place a router names one of its outputs, in one table: the rules
(`default`, the `dormantDefault` kept while its output is away, `audioOutput`, `embeddingsOutput`),
the rule lists (`schedule`, `bySource`), `failover`, and graph edges whose end is `out:<output id>`.
`rewrite(new_id_of)` changes them in place — an edge keeps its id, so the roles a queue or a 🛟
backup node holds by edge id stay — and returns how many places changed; `rules_naming` and
`edges_touching` read the same table, and `drop` removes every place naming an output (a pool
deleted with its cables disconnected; the default goes too, and the router's save takes
its first output). Remap, swap, the legacy cloud-output upgrade, the list of what
points at a pool (`cloud/refs.rs`) and the move of a pool's cables all go through it: four
copies of the list had drifted, and the legacy upgrade never looked at the reserve default, audio
or embeddings.
Owns: —.
Key names: `RouterOutputRefs`.

## `cloud/data.rs`, `cloud/presets.rs`, `common/cloud_file.rs`, `common/cloud_sources.rs`

Cloud provider data layer — pure data, no OAuth flows and no router logic. Two stores: accounts and
pools in `cloud-providers.json` (with migration from the legacy flat `providers[]` shape; the pools
themselves are `cloud/pools.rs`'s), and credentials in `provider-secrets.json` written 0600.
`CLOUD_PROVIDER_PRESETS` defines the known account types (openai-subscription with its sign-in by
code — token, client and revoke addresses — openai, ollama, anthropic, openrouter, custom) including
auth header/prefix and test path. Only a plan that signs in by code may use OAuth
(`device_login_preset(accountType)`): the first subscriptions were made as type `openai` with
accountType `openai-subscription` and keep it, while a new `openai` account takes a key.
`account_auth_headers` builds request headers from either an API key or the stored OAuth access
token. An account stands in no pool by itself: a pool's step names it (`upsert_cloud_account` keeps
no reserve of its own any more — the levels are the steps'). `delete_cloud_account` takes every step
that names the account out of its pool (`PoolDesk.remove_account`), ends the account's sign-in in
progress (`oauth.end_pending_logins`), and once the account is gone ends its own sign-in at the
provider (`oauth.SignOut`); it answers how that went. `cloud_accounts_state` tells the board which
accounts that is (`signOutOnDelete`), whether an account is a subscription, and the steps of the
pools that name it (`usedIn`) — what its deletion takes.
The keys the file keeps beside accounts and pools — the models' levels, Routing's added models,
the board's providers, the models' schedules, what the operator said key models do — are one table, `CloudFileKeys`
(common/misc.rs), read and written by this module and read by the proxy: until
1.3.498 three lists named them, and a key one of them lacked was dropped by the next save.
Owns: `cloud-providers.json`, `provider-secrets.json`, `CLOUD_PROVIDER_PRESETS`.
Key functions: `load_cloud_data`/`save_cloud_data`, `load_provider_secrets` (read-only: the secrets
file is written only through `CredentialVault`, rust/crates/files/src/credential_vault.rs),
`account_secret_entry`, `upsert_cloud_account` + `delete_cloud_account`, `account_auth_headers`,
`account_credential_summary`, `cloud_accounts_state` (a secret-free view for the UI).

## `proxies/token_history.rs`

Token-rate history (`state/token-history.json`), fed by the proxy's own records.
`record_token_history` appends one entry per **completed** proxy request from llama.cpp's exact
per-request `timings` on the proxy's recent items, attributed by proxy port, deduped by request id,
trimmed to 14 days / 12,000 entries on save — the authoritative per-request source, no
time-correlation guesswork. (The controller-side counters that scraped the controller's own
llama-servers every second, and fed a Token Speed series of their own, went with its cells in
step 6.9: a cell's rates now come from its machine's scout.)
Owns: `TokenHistoryMemory` in `App`, `state/token-history.json`.
Key functions: `load_token_history`, `save_token_history`, `record_token_history`,
`token_history_query`.

## `proxies/stats.rs`, `proxies/stats/logs.rs`

Read-only views over the **proxy's** artifacts: `state/agent-proxy-state.json` and
`logs/proxy-events/*.jsonl`. The controller never writes these — the proxy owns them.
`agent_proxy_sample` loads the live state file; `summarize_proxy_item` normalizes an active/recent
request record (upstream host/port recovery, usage tokens, phase) for the dashboard.
`load_agent_proxy_logs` reads one date's JSONL (filterable, capped at 2000 rows; `event` names one event or several, comma-separated — the history's Requests tab reads `finished,blocked`);
`proxy_daily_stats` folds a day's `received`/`blocked`/`finished` events into per-route
total/failed/paused counts (paused = blocked by route mode, not a real failure). (Matching the
journal of the controller's own single server to requests by time went with that server in
step 6.9.) One reading of each day file (`_day_seen`: a finished day once, today's file only for
its added bytes) serves two answers: `proxy_ports_last_seen` — each port's last successful request,
the board's proof that a route is used — and `embeddings_last_called` — the last call for
/v1/embeddings whatever came of it, 0 for none in 7 days: Routing's unset embeddings slot is
red only then (2026-10-08).
Owns: — (reader only).
Key functions: `agent_proxy_sample`, `summarize_proxy_item`, `proxy_usage_tokens`,
`list_agent_proxy_log_dates`, `load_agent_proxy_logs`, `proxy_daily_stats`, `proxy_ports_last_seen`,
`embeddings_last_called`.

## `proxies/latency.rs`

The caravan's own time per proxy port, read back from the proxy's journal for the route window
(`GET /api/agent-proxy-latency`). Each finished record carries `latency` since 1.3.437
(`rust/crates/proxy/src/clock.rs`); `ProxyLatencyDigest.summary(port, range)` answers the median
and the 90th percentile (nearest rank) of `prepMs`, `connectMs`, `headersMs`, `firstChunkMs` and
`cpuMs`, each with its count and `null` when nothing was measured, and `connReused` as `{n,
reused}` over the provider requests. A day file is read once per process, today's only past the
bytes already read and only up to its last whole line — the proxy may be mid-write; a file that
shrank is read again, a removed one forgotten. Only the samples are kept. Requests from before
1.3.437 have no `latency` and are not counted: they were not measured, and zero would draw a
caravan faster than it is.
Owns: the per-day sample cache, `proxy_latency` (the process's one digest).
Key functions: `ProxyLatencyDigest.summary`.

## `monitoring/`

The local system monitor. `MonitorSampler` (`monitoring/sampler.rs`) — a thread started at the controller's start — collects
one sample per second (`MONITOR_SAMPLE_INTERVAL`): CPU from `/proc/stat` deltas, loadavg, GPU (the
last sample of the machine's scout — `gpu_sample` maps it to the names the charts draw), the proxy
state file and config (recording token history as a side effect), memory, disk/net rates, and the
busiest processes (listed by the scout); `correlate_activity` then groups the proxy's active and recent
requests by route and counts the local and cloud ones in flight. (Until step 6.9 the sample also
carried the controller's own single server — its connected clients via `ss`, its slots and journal,
its token counters — and `correlate_activity` matched requests to its busy slots and, by time, to
its journal timings, whichever server had served them.) `append_incidents_from_sample` derives incidents (failed / client_disconnected /
upstream_timeout / slow first byte ≥30s / slow request ≥120s, each with a cause) and appends deduped
records to `state/incident-log.jsonl` (30-day retention). The sample ring is trimmed to the configurable
retention and persisted to `state/monitor-history.json` at most every 10 min (`PERSIST_EVERY`; every 10 s until
2026-11-03, an hour of samples, 420 KB, each time) and when a release ends the process (`persist_now`), reloaded on
startup: a restart that is no release starts without the last minutes. Also hosts
the dashboard hardware state (`gpu_state`: the cards its scout last reported, with the reason when
there are none) and on-demand `monitor_snapshot` (taken by the scout: nvidia-smi, or a btop frame
rendered here via `fleet/terminal.rs` with the scout's `top` as the fallback).
Owns: `MonitorMemory` and `IncidentMemory` in `App`, `state/monitor-history.json`, `state/incident-log.jsonl`.
Key functions: `monitor_sampler_loop`, `collect_monitor_sample`, `system_monitor_state` (the
`/api/system-monitor` payload), `correlate_activity`, `append_incidents_from_sample`,
`gpu_state`/`cpu_state`/`memory_state`, `monitor_snapshot`,
`set_monitor_retention`.

## `metrics.rs`

Prometheus text exposition for `GET /metrics` — cheap reads only, no probes: the proxy's
live state file (route activity/queues), today's proxy log (request counters), the topology store
(hosts, cells), the cached `gpu_state()` and models-disk usage. A machine's online gauge uses the
board's own rule (`HostRecord.liveness` over `HOST_REPORT_TTL`), so the two cannot disagree. When sign-in is enabled the
endpoint authenticates with the **fleet token** (`X-Caravan-Token` or `Authorization: Bearer`), so
an external Prometheus can scrape without a browser session.
Owns: —.
Key functions: `build_metrics_text`.

## `proxies/queue_thresholds.rs`

Queue-wait thresholds per proxy port. `QueueThresholds.compute` turns the policy percentages (with
per-route overrides) × each route's `clientTimeoutSeconds` — the operator's wait budget on the port
— into queue-abort / priority-preempt / cloud-fallback seconds, keeps them, and mirrors them into
`agent-proxies.json` as `computedThresholds` (a readable mirror, not the source of truth).
`refresh_forever` recomputes every **6 hours**; `latest()` is the one reader. The proxy goes by none of them since 2026-11-02: the entry has no
preemption and no spill. The budget used to be
synced first from each agent's own OpenClaw config, fetched from OpenClaw config managers on the
client machines; the managers went on 2026-09-24.
Owns: the `QUEUE_THRESHOLDS` object (last result + its lock).
Key functions: `QueueThresholds.compute`, `latest`, `refresh_forever`; `compute_queue_thresholds`
(the callers' name).

## `fleet/scout_poll.rs`

`ScoutPoller` pulls the scouts' state off the board's request path. `GET /api/topology` only kicks
it: at most one pull runs at a time, at most one starts per `MIN_INTERVAL` (5 s), and the read
returns what the store already holds — the next read sees what the pull brought. It used to be a
synchronous loop inside the read, two seconds of timeout per scout, so one machine switched off
added two seconds to every board poll.
`Rerun` runs work off the request path that may not drop a kick: one run at a time, and a kick during a
run makes one more run after it (1.3.647) — the routers' outputs rewritten when a report changed a cell.
Owns: its memory in `App` — the running flag and the last start.
Key functions: `ScoutPoller.kick`, `Rerun.kick`.

## `cloud/oauth.rs`, `cloud/oauth/device.rs`

Signing a cloud account in and out. A ChatGPT subscription signs in by a one-time code
(`DeviceLogin`, OpenAI's device authorization for the Codex app — `codex login --device-auth`):
`start_device_login` asks OpenAI for a code, the board shows OpenAI's page and the code, the
operator enters it on any computer, and the login's thread asks OpenAI every `interval` seconds
(403 = not entered yet) until it gets the authorization code with its PKCE verifier, trades it at
the account's token URL with the device redirect, and ends with `_finish_login` (tokens stored with
the email from the id_token, and the account's model list fetched — the next thing "+ Add step" asks
for is a model) — unless its account was deleted meanwhile. Nothing returns to localhost, so a controller on a NAS or in a container finishes it by
itself. Which accounts have it is `cloud.device_login_spec` (by accountType). The device paths need
a named User-Agent: Cloudflare in front of auth.openai.com refuses urllib's own. A failed step says
its reason through `LoginFailure` — the HTTP status and the protocol's error word, never the
provider's free text, which can quote the code.

The other way, a return to `http://localhost:1455`, is gone since 1.3.455: it finished only in a
browser on the controller's own machine, which a NAS or a container does not have.

One login per account at a time: a new start ends the pending one, and so does deleting the
account. `oauth_login_status` is what the board polls; a login it does not hold is `unknown`.
`EndedLogins` keeps, for 30 minutes, why a login ended without a login — `replaced` by a newer start
or `removed` with its account — so a window still waiting on that code says so instead of waiting
15 minutes. A login that already ended on its own keeps its own answer. `refresh_oauth_token`
renews through the credential vault's per-account lock; `cloud_api` calls it before authenticated
requests.

`SignOut` ends a deleted account's sign-in at the provider — the request `codex logout` sends: the
refresh token with the client it was issued to (`token_type_hint: refresh_token`), or the access
token when there is none, POSTed as JSON to the plan's `revokeUrl` (`https://auth.openai.com/oauth/revoke`),
10 s at most. Only the account's own tokens, as the vault removed them, and only to its plan's
address: a test alias signs in through its original and a pool has none of its own. The account is
deleted first either way; a provider that refuses or does not answer is reported as `{ok: false, error}`.
Owns: `_oauth_sessions` + `_oauth_lock`, `ENDED`; one thread per sign-in by code.
Key names: `DeviceLogin`, `SignOut`, `EndedLogins`, `start_device_login`, `oauth_login_status`,
`end_pending_logins`, `refresh_oauth_token`.

## `cloud/api.rs`, `cloud/subscription.rs`, `cloud/reports.rs`, `cloud/spend.rs`, `cloud/upstream_errors.rs`, `cloud/usage_stats.rs`

Live calls against the provider APIs. `test_account_key` probes the preset test path (401/403 =
rejected; 404/405 counts as validated); `set_account_key` stores a key only after it passes, through
`CredentialVault.put_api_key` under the lock a token renewal takes (a read and a write-back of the
whole file here put a spent refresh token back when the proxy renewed in between — until 2026-10-07).
`fetch_account_models` handles OpenAI- and Ollama-shaped listings with an OAuth pre-refresh;
`fetch_subscription_models`/`fetch_subscription_usage` talk to the ChatGPT backend for subscription
accounts (each limit carries `windowSeconds`, the length a step's switch level is keyed by). Both model fetchers
narrow an entry through `_catalogue_entry`: id, name, and `contextLength` only when the provider names
a window (`declared_window`) — the subscription's `context_window`, not its `max_context_window`. A
pool's window, when it takes the providers' figure, is the smallest one its enabled steps' models
name, and none when one names none (`CloudPools.window`, rust/crates/rules/src/cloud_pools.rs). `fetch_account_costs` and `fetch_openrouter_limits` read spend/credit endpoints.
`check_account_models` is "↻ Check now" in the step window: the account's list into the catalogue at
once, with how many chat models it has (`ChatModels`, `cloud/catalog.rs`) and how many it left out —
nothing else follows from a list: no model is created, shown or removed by it.
`annotate_cloud_topology` marks the pools' steps whose model the provider no longer lists (`unlisted`,
only when a fetched list exists — no list, no verdict) and the accounts' `modelsCheckedAt`, and kicks
stale lists' refreshes. `CloudLeg` reads which account and which model a finished cloud request went
to: the record names the step's account and the model sent; an older record names the account and
the client's model, and the pool the model block became knows the model; a pool's own refusal that
names no account went to none (until 2026-10-11 the pool's first step took it as its own request).
`cloud_spend_summary` (the 30 days per account and model) and `cloud_upstream_errors` (24 h of
refused or failed requests per account, the caravan's own refusals as their own rows) read through it.
`cloud_spend_summary` prices a request by `ModelPrices` (common/model_prices.rs: the operator's own
price, else the LiteLLM table, else none — `known` False, adds 0 and is COUNTED as `unpriced`): the same rule as
`usage_stats`, where it used to be the table alone. Since 1.3.585 both price the cache too: the journal row's `usage` holds `prompt` (ALL the
input, the cached and the written parts in it — OpenAI's meaning), `completion`, and, where the answer had them, `cacheRead` and `cacheWrite`;
`ModelPrices.cost(model, prompt, completion, cache_read, cache_write)` prices the plain rest of the prompt at the input price, what was read at the
cache-read price and what was written at the cache-write price — the table's own (`cacheReadPer1M`, `cacheWritePer1M`), or the row's input price
where it names none (the operator's own row never does). A count above its prompt is cut to it. An account the operator gave a credit
(common/account_credit.rs: `credit` `{amountUsd, asOf}` on the account, from `creditUsd` of
`/api/cloud-accounts/save`; the provider tells no balance) also gets `sinceCredit` — what went through the caravan from the
moment the figure was typed, read back as far as that takes (`partial` when the proxy's logs, kept
`LOG_RETENTION_DAYS`, do not reach so far) — and always has a row, even with no traffic, so "nothing spent" is an answer
of the reading (named for the figure it counts from) and not the absence of one.
`usage_stats` is the statistics panel: a single pass over the last N days of proxy event logs'
`finished` events — cloud requests priced from LiteLLM pricing (manual `apiPricing` overrides win),
local requests counted in tokens plus a "would have cost" estimate from `localPricing` — aggregated
per account, model, and day; capped by log retention.
Owns: — (reads proxy logs, writes secrets via `cloud/data.rs`).
Key functions: `test_account_key`, `set_account_key`, `fetch_account_models`,
`fetch_subscription_models`, `fetch_subscription_usage`, `fetch_account_costs`,
`fetch_openrouter_limits`, `check_account_models`, `annotate_cloud_topology`, `CloudLeg`,
`cloud_spend_summary`, `cloud_upstream_errors`, `usage_stats`.

## `cloud/pools.rs`, `cloud/pool_edits.rs`, `cloud/pool_edits/accounts.rs`, `cloud/pool_state.rs`

`PoolDesk` — the pools on the controller's files (the operator, 2026-10-10): a pool is what an
agent's cable goes to, an ordered chain of steps, each one account with ONE model and its own switch
levels (`CloudPools`, rust/crates/rules/src/cloud_pools.rs, read the same way by the proxy). The proxy
chooses the step per request (rust/crates/proxy/src/pool_steps/mod.rs); this desk never routes. `create(name,
account, model)` makes a pool with its first step (its id from its name, the model's name by
default). A pool's name is the model id a consumer of the entry calls it by
(rust/crates/rules/src/entry_models.rs), so no two pools share a name, compared without case: a name the
operator gave that another pool carries is refused (409) — on `create` and on a rename by
`save_pool` — and the default name gets a number instead (`gpt-6-sol 2`); `add_step` puts a step at the end — the same account may stand twice; `remove_step`;
`save_pool` takes the pool as the board edits it — name, the window (`contextLength`,
`contextAuto`), the steps in their new order with their switches, levels and models (no hand pick:
the pool goes by its order, the operator 2026-10-11) — and refuses a step the pool does not have (a new one comes by `add_step`); `set_level` sets
one window's level of one step, `stop` or `switch` (`LEVELS`; 0 lifts it; only a subscription's step
takes one — elsewhere it would be a setting that does nothing). The switch is kept at or above the
stop (`CloudPools.levels`): a stop raised past it takes it along. A subscription's new step starts with
10% of each window as both (`UsageReserve.NEW_STEP`). `delete(pool, resolution)`: when cables
or rules lead to it, `resolution` says where they go: `{moveTo}` another pool (`CloudModelRewire`) or
`{cut: true}`; without one, 409. `remove_account` takes an account's steps out of every pool. `state()` is every pool as the board draws it: each
step with the levels its subscription has reached now — the proxy's last reading, judged by the rule
the proxy enforces (`stopReached`, `switchReached`) — what holds it in Routing (`held`,
`inUse`) and the levels' ceiling; `runtime()` is the proxy's word on each pool while the proxy is
alive to say it. `migrate()` rewrites a file of the old form once (stamped `pools-of-steps-2026-10`):
a model block in Routing or pointed at becomes a pool with the block's id — so its `cb:<id>`
cables and rules stay — its steps the members of the subscription pool it belonged to, or its
one account, each with the block's model and the account's reserve as its levels; the other blocks
were copies of a provider's list and go. `clone_test` keeps the legacy routing-test aliases.

In Routing (1.3.503): `create` also takes its first row as a row takes it (`target`: an account's
model or a local output — a model carried onto the Pools column), named after `name_after`, the board's
word for the model, else the model id. A pool still under the board's name ("Pool", "Pool 2"…,
`default_named`) whose first cable `add_row` or `connect_row` draws takes that word as its name
(`_named_after`; " 2" when taken): a pool's name is what its clients call, so only a pool no row of
which was cabled before is renamed, and a name the operator typed never is. `order(ids)` is the pools'
order a carried card leaves, refused 409 unless `ids` names every pool once. `arrange()` — "⇅ Arrange"
— puts each account's added models in the order the pools' rows name them (`AddedModels.put_first`), the pools in the
operator's order, then the rest (until 1.3.675 the pools went in the order the clients' sets named them).

What a key's model does (1.3.631): `set_jobs(account, model, jobs)` keeps the operator's word
(`AccountModelJobs`, rust/crates/rules/src/cloud_models.rs, under `modelJobs`) — the jobs a provider
serves behind a key (`OFFERED`: `llm`, `embed`, `asr`, `speech-translate`, `tts`); an empty list takes
it back. A subscription's, an Anthropic key's and a DeepSeek key's models take no word (`ModelKind.fixed`: their type
says it), a word not offered is refused, and neither touches the file. `model_jobs()` is what Routing's
strip draws (`offered`, `set`, `fixed` by account), `said_jobs()` the store the board reads its pools'
kinds with (`annotate_pool_kinds`), by the rule the entry reads them (`cloud_auth.load_pool_kind`);
`remove_account` forgets an account's words with its levels and schedules.
Owns: nothing in memory; the pools live in `cloud-providers.json`.
Key names: `PoolDesk` (`create`, `add_step`, `add_row`, `connect_row`, `remove_step`, `save_pool`, `set_level`,
`set_jobs`, `model_jobs`, `said_jobs`, `order`, `arrange`, `default_named`, `delete`, `remove_account`, `state`,
`runtime`, `migrate`, `clone_test`).

## `cloud/refs.rs`

`CloudModelRefs` — everything that points at a pool, from one snapshot of `agent-proxies.json`: an
agent's own cloud route (`providerId`), ↑☁ fallbacks (`cloudFallbackProviderId`),
graph cables with the queue's (admit/spill) and a 🛟 backup node's (main/backup) roles, and every rule
including `dormantDefault`. `of(pool)` feeds the delete confirm (`GET /api/pools/refs`), `in_use(pool)`
is what the board reads. `held(pool)` counts what would stop reaching it if it went — cables and the
rules default, schedule, by source, failover, audio, embeddings; not a stashed `dormantDefault`, which
waits for its output by design — and `cut(pool)` drops them all, in the routers of the snapshot,
through `proxies/output_refs.rs`. The same preflight names the clients of the entry cabled to the pool
(`EntryModels.callers`, the entry's own reading asked the other way round), and `PoolDesk.delete`
takes their cable away (`uncabled`): pool ids come from their names, and a later pool of the same
name would have opened to them unasked. `CloudModelRewire(cfg).move(from, to, output)` — a pool's deletion with
`{moveTo}`: everything that pointed at one pool points at another, through `proxies/output_refs.rs` (edges keep
their ids, so a queue's and a 🛟 backup's roles stay) plus the ↑☁ fallbacks; the other pool's router
output goes into every router first, because saving a router drops a rule naming an output it lacks.
Owns: —.
Key names: `CloudModelRefs`, `CloudModelRewire`.

## `cloud/pool_ports.rs`

A pool's own ports are gone (the owner, 2026-10-12: every client comes in through one address with its
own key). Such a port was a route of kind `service`, open without a key, straight into one pool; its
"+ port" button went with the main board's pools column in 1.3.486. `PoolPortsRetired().migrate()`
runs first among the start-up steps (`startup.rs`): it takes every such route out of
`agent-proxies.json` and answers `[{port, label, pool}]` for the log line, or None when there was none
(nothing is written then). The controller refuses the kind on a save (`router_dsl`, 400 — an old tab
cannot bring one back) and passes it by on a reading; the proxy reads no route of that kind
(`rust/crates/rules/src/route.rs`).
Owns: —.
Key names: `PoolPortsRetired`.

## `cloud/catalog.rs`

Provider model-catalog cache + upstream endpoint health, one small state file
(`state/model-catalog.json`). Three jobs: (1) per-account
model lists with a 10-minute TTL refreshed by a background thread whenever the board reads the
topology (`kick_refresh` + a guarded fetcher) — what "+ Add step" offers (`GET
/api/cloud-accounts/catalogue`, chat models first by `ChatModels`) and what a step's model is checked
against: a step whose model fell out of the list paints "unlisted"; (2) a circuit breaker around
every provider endpoint (`guarded_call(key, fn)`: 3 consecutive failures of the PROVIDER open the breaker with
exponential 6 h→48 h backoff; a failure of the road to it — no route, no name, a refused or timed-out
connection, `is_network_failure`, 1.3.584 — is shown (the count and the error in the panel) but does not count and never blocks,
and the next success clears it: on 2026-10-18 twenty minutes of "Network is unreachable" turned the Anthropic model list off
for six hours, after the network was back. The two counts are kept apart (`failCount` for the card, `hardFails` for the breaker);
`endpoints_report` feeds the "API issues" panel and
`retry_endpoint` the panel's retry button — 401/403 on spend/limit endpoints stay soft); (3) the
codex `client_version`: `CARAVAN_CODEX_CLIENT_VERSION` env verbatim, else
max(npm `@openai/codex` latest cached 24 h, floor 0.160.0) — the floor matters because npm lags
behind the version gate newer subscription models require.
Owns: `state/model-catalog.json`, the refresh thread, breaker state.
Key functions: `guarded_call`, `record_ok`/`record_fail`, `endpoint_blocked`, `endpoints_report`,
`retry_endpoint`, `effective_codex_client_version`, `cached_model_ids`, `store_models`,
`models_stale`, `kick_refresh`.

## `cloud/pricing.rs`

The LiteLLM model-pricing table (`model_prices_and_context_window.json` from GitHub raw), reduced to
`{model: {inputPer1M, outputPer1M, provider[, cacheReadPer1M, cacheWritePer1M]}}` and cached on disk for 24h at
`logs/model-pricing-cache.json`. The cache prices are the table's `cache_read_input_token_cost` and `cache_creation_input_token_cost` (1.3.585); a row
that names none has none, and a price that is text, negative or a boolean is no price. The file says its `shape` (`PRICING_SHAPE`, 2): a file of any
other shape is refetched even inside its day, because a table of the older shape would price every cached token as a plain one. When the fetch fails
the old table is returned (an old price is better than none — no price reads as a spend of nothing), and `{}` only where there is none — pricing is a
non-critical feature.
Owns: the pricing cache file.
Key functions: `fetch_model_pricing`, `per_million`.

## `fleet/remote_cells.rs`

Remote-node probes and the in-memory telemetry rings behind topology cards. Probes, each behind its
own `TtlCache` and each through the cell's machine's scout (`cell_doorway.rs`, since 2026-11-08 — a cell listens on its
machine's loopback): `llama_health` (`/health` → ok / loading — llama.cpp
answers 503 while loading into VRAM — / down, 3s), `llama_modalities` (`/props`, the
authoritative vision/audio source, 300s), and `command_cell_health` (HEALTH_PATH JSON with
download/load progress bytes, or, when unset, whether its port listens as its scout sees it on the loopback — `listening`
of its report; `unknown` when the scout could not read its listeners), and `cell_about` (what a cell
this controller holds no settings for says it is: engine, model, kinds — and since 1.3.502 its
`langs`, `maxAudioMs` and `targetLang`, which the entry tells its clients of an ear, 30s). A 401 or 403 on a health path is
`broken` — "the cell refuses the caravan": a server started with a key of its own, which the
proxy's requests meet as well — not the `ok` any answer below 500 used to be (2026-09-26). The three history rings —
`_gpu_history` (mem/util/power per `node:gpuIndex`), `_cpu_history` (load/RAM per node),
`_tps_history` (prompt/gen t/s per `node:port`) — are appended on every topology build, same-second
samples collapsed, 600s retention / 300 rows kept / 150 emitted, all guarded by `_history_lock`. A cell that says it answers no
request (`requestsProcessing` 0 on its entry) records zeros in `_tps_history`, not the rates its scout keeps while it is idle (`TokenRates`, 1.3.590):
a cell that says no count is recorded as it reports.
Owns: the three probe caches, the three history rings, `_history_lock`. (The TCP probe of a cell's port from here,
`probe_port`, and the "closed long enough to say so" memory behind `reachable`, `port_answers.rs`, went 2026-11-08 with the
direct way.)
Key functions: `llama_health`, `command_cell_health`, `llama_modalities`, `cell_about`, the `_record_*_history` feeders used by
topology.

## `fleet/cell_assets.rs`

The cell servers themselves — the launchers and HTTP servers a command cell runs (moonshine,
whisper, tts). `cells/` in this repo is their one home, and this module is how they reach every
host: `CellAssets::manifest` hashes them and `CellAssets::bytes` serves one, and a scout writes what a
runner needs into its `$HOME` before the cell starts (`rust/crates/scout/src/starts/assets.rs`), so one
command string works everywhere. The controller runs no cell, so it keeps no copy of its own there.
The served set is an explicit allowlist (`CELL_ASSETS`, `RUNNER_ASSETS`) rather than a directory
listing, because these endpoints hand files to the whole fleet and a stray file dropped into
`cells/` must not become fleet-readable by accident. On the scout writes go through temp+replace, and a
failure never blocks a start: an out-of-date cell beats no cell.
Before this, each host obtained these files independently — clients from their caravan-scout clone,
the controller from somebody copying one in by hand — and the copies drifted for months with no
error anywhere.

`engine_cell_server.py` (2026-09-25) is the cell whose model runs inside an engine next to it —
Ollama or LM Studio, listening on 127.0.0.1 only. The cell is the way in: it binds the cell's port,
forwards what it is sent to the engine with the cell's model named in every request (a caller need
not know what the engine calls it, and `/v1/models` lists only that model), and streams a reply
through as it arrives. Starting it loads the model and holds it (Ollama: keep_alive -1, set again
after each request on an OpenAI-style path, which resets Ollama's timer; LM Studio: the REST load,
which has no idle limit); stopping unloads it. `/health` asks the engine every 5 s whether the model
is still there and reports an error with the reason when it is not; while the cell waits for the
engine (up to 90 s — the machine may be bringing both up) it says what it waits on. Standard
library only; `run_engine.sh` only starts it, and exists because a scout brings a cell's files into
$HOME by the `run_<name>.sh` its command names — a bare `python3 …server.py` would name none, and
the server would never reach the machine. Runners `ollama` and `lmstudio` get the launcher,
`cell_base.py` and this.

The voice models — the ones that ANSWER IN A VOICE (1.3.551 as custom commands with presets; 1.3.553 as runners) —
are runners of their own: `personaplex`, `lfm-audio`, `step-audio2`, `qwen3-omni` and `minicpm-omni`
(`LauncherCellMixin`, `domain/runner/launcher.rs`), and their files are the groups of `RUNNER_ASSETS` named after the runner's id.
`lfm-audio` carries `run_lfm_audio.sh`, `cell_base.py` and `lfm_audio_server.py`, the one cell server of the five: the
HTTP front of LFM2.5-Audio. The others are the launcher alone: NVIDIA's `moshi.server`, `vllm serve --omni` (one launcher
under both vLLM-Omni runners, each with its recipe) and `llama-omni-server` (built by its launcher) serve themselves. A
scout asks the manifest which group the cell's runner names and fetches it, so a new voice server needs no scout release;
`group_for_command` reads the launcher out of a command and still serves a custom command that names one of these
launchers (the cells made from the 1.3.551 presets). The board's ⇪ stale-source check (`cell_source_state`) compares the
cell's stamp with the group of ITS launcher, not with the runner id `custom`, which stands for the TTS server alone; a cell
that serves itself reports no stamp, and its state is "unknown", never "stale". Each launcher installs its engine into a
folder of its own at the first start and writes a completion marker only when the install is DONE: a start that stopped
halfway is finished by the next one. `scripts/test_voice_launchers.py` runs the four launchers against stand-in `uv`, `git`,
`cmake` and `python`; `contract/runner_lines.json` and `contract/runner_cards.json` hold the runners (the line a start runs, what
the board's cards are told). How a server is added:
[adding-a-runner.md](adding-a-runner.md).
Owns: `cells/` and what `/api/cell-assets` exposes.
Key names: `CellAssets` (`manifest`, `bytes`, `server_stamp`, `source_state`, `group_for_command`).

## `fleet/server_cells.rs`, `fleet/server_cells/kept.rs`

Server slot/cell bookkeeping — pure data layer; the start/stop actions live in `fleet/cell_ops.rs`. Slots
are persistent `"hostId:port"` records in `topology_store()["serverSlots"]` so a proxy cable stays
attached while a server is stopped or its model changes. Port allocation starts at the configured base (default 22001; `CARAVAN_CELL_BASE_PORT`) and
collisions raise 409. `upsert_server_slot` deliberately keeps empty-string config values (an empty
field is a *removed* flag — dropping it would make the edit form re-inherit the controller default),
and keeps a ≤10-entry command history for command cells (one-click revert). A cell of the
controller's own host id is refused (`refuse_controller_host`, `CONTROLLER_RUNS_NO_CELLS`): since
step 6.8 the controller's machine runs its cells through its scout. A reserve that names an engine
(`{hostId, engine, model}`) is a cell in that engine: `reserve_server_cell` checks its plan
(`fleet/engine_cells.rs`) before it takes a port, and the slot is born configured.
Owns: the `serverSlots` records inside admin state.
Key functions: `server_slot_key`, `next_server_cell_port`, `used_server_cell_ports`,
`assert_server_cell_port_available`, `upsert_server_slot`, `reserve_server_cell`,
`move_server_cell`, `delete_server_slot`, `refuse_controller_host`, `reassign_server_slot_port`
(fleet-wide free check). Every name of a cell — the routers' references, the pools' rows, its
schedule — follows it on a port move, a swap and a start on another port (`move_server_cell`), and a
deleted cell's rows lose their cable and its schedule goes (`fleet/cell_outputs.rs`).

`KeptCells` (1.3.504, `fleet/server_cells/kept.rs`) makes a slot of each cell a scout keeps that the controller lacks. A stopped cell
is drawn from its slot alone — the scout drops a stopped cell from its report — and a controller that
did not start a cell had none: on 2026-10-12 the controller moved to the NAS had no slot of a machine's
cells, and each went off the board as it was stopped, with its switch and Routing's cable to it.
The scout reports the start request it keeps for each autostart cell (`autostartRequests`, scout
2.26); `adopt(host, requests)` — run on every report, the heartbeat's and the pull's
(`record_host_report`) — makes a slot from each it lacks, the settings whole (an empty value too), the
model and the cache switch, marked `adoptedFrom: "scout"`. A slot that exists is never touched. A port
another slot holds, or one no cell may take (the controller's own, an excluded one), makes none — it
would point one cell's cables at another server — and the log says so. `KEPT_CELLS` is the reports'
instance.

## `fleet/cell_outputs.rs`

What a deleted cell takes with it. Until 2026-11-07 a machine's cell was named by its output id, `srv:<port>`, in the routers'
outputs, the pools' rows and the models' schedules, and `CellOutputs` followed a cell that moved to another port or swapped
ports with another (`move`, `swap`, 1.3.499). A cell has a port only while it runs since then (Papyrus `caravan-scout-port-lease`,
steps 2–3): it is no output, there is nothing to move or swap, and the port picker is gone. A pool's row names the machine's
model (`mm:<hash>`) instead; a row of before that named `srv:<port>` names the cell `c<port>`, and `MachineRows` cables it to that
cell's model (`fleet/machine_rows.rs`).
`dropped(id, host_id)` — a cell deleted — takes the rows and the schedule of its machine's model when it was that model's only
copy (1.3.655, `MachineRows.sole_model`): a row still naming the model would wait for a model that is gone. Each file is followed
on its own; one that cannot be written is named in the answer (`notFollowed`) and in the log. An engine's model (`eng:<id>`) is
named by its machine, engine and model, and is not followed.
Owns: nothing in memory.
Key names: `CellOutputs` (`dropped`).

## `cloud/schedules.rs`

When each model is open (1.3.498, step 1 of the visumap scheme caravan-model-schedule; the owner,
2026-10-12: the schedule is the model's, not a pool's or a set's). `ModelScheduleDesk.set(key,
{enabled, windows})` is the door Routing's ⏱ calls (`POST /api/models/schedule`): the key is the
Routing's — `acc:<account>/<model>`, `out:mm:<hash>` (a machine's model) or `out:eng:<id>` (`ModelKey`; an `out:srv:<port>`
of before names an output no longer there); the windows are
read strictly (`WeekWindows.parse`, rust/crates/rules/src/model_schedules.rs: what is wrong with which window,
400); an unknown account is 404, and a schedule switched on with no window is 400 — it would close
the model for good. The schedules live in `cloud-providers.json` under `schedules` (`ModelSchedules`,
rust/crates/rules/src/model_schedules.rs), where the proxy reads them with each pool and passes over the
row of a model closed now. A cell's schedule goes with the cell's other names (`fleet/cell_outputs.rs`);
`PoolDesk.remove_account` forgets an account's models' schedules,
and a model taken out of Routing keeps its own, as its levels. `state()` is the board's
`modelSchedules`: the caravan's zone (`CaravanZone`, common/zone.rs — TZ, else the
machine's zone, else UTC said as not known), the moment, and each model's schedule with what it says
now (`open`, `until`, `opensAt`). Step 1 starts and stops no server: that is still `fleet/cell_schedule.rs`'s
older window on a slot, until the scheduler of step 3 takes it over.
Owns: nothing in memory; the schedules live in `cloud-providers.json`.
Key names: `ModelScheduleDesk` (`set`, `state`).

## `fleet/cell_schedule.rs`

Per-cell start/stop schedule. A slot may carry `schedule = {enabled, start "HH:MM", stop "HH:MM",
days [0..6]}` (empty days = daily); a background tick (1/min, started at the controller's start) acts only on
window **edges** — so a manual stop inside a window sticks until the next window opens
(`schedState` on the slot remembers the last applied edge). Start/stop go through the same
`server_cell_action` path the buttons use. The same tick also brings a model home before its window
opens (`PREFETCH_MIN` minutes, once per window — the window it was done for is remembered on the
slot), so a scheduled cell starts from this disk instead of reading over the network; the cell is
NOT started then, and a disk with no room simply keeps the model where it is.
Owns: the scheduler thread, `schedState` and `schedFetch` on slots.
Key functions: `normalize_schedule`, `set_cell_schedule`, `in_window`, `minutes_to_window`,
`prefetch_tick`, `scheduler_tick`, `start_scheduler_thread`.

## `fleet/clients.rs`, `fleet/reports.rs`, `fleet/reports/`, `fleet/scout.rs`, `fleet/start.rs`, `fleet/llama_node.rs`, `fleet/backups.rs`

Client fleet management over the route-agent HTTP API. `client_llama_start` implements Variant 2 —
the controller is the single command builder: it ships the resolved `build_remote_llama_args` list
(path placeholders substituted by the agent after download; YaRN flags when the controller can read
the model's header) with the engine's environment (`env`), or, for command cells, the raw command +
health path; slot moves/reservations happen first. A machine is two records under one id
(`HostRecord`, since 2026-09-24): its HOST record in `topology.hosts` is what its scout reports —
GPUs, compute apps (with the process's name, scout 2.12+), the engines next to its cells (Ollama,
LM Studio — `EngineReport` in `domain/engine.rs` keeps them typed, and None for a scout
that cannot look, never "none"), CPU/RAM, cells, build versions, address, and its NVIDIA driver as
the next boot will meet it (`driver`, scout 2.19+, kept in its own shapes by `DriverOutlook.clean`) —
and `record_host_report` /
`host_from_report` replace it with each report — in memory at once; the file takes a machine first heard of and a
change of its settings (`MachineSettings::remember` says) at once, and the rest within `REPORT_SAVE_WITHIN`
(`AdminStore::save_later`); its CLIENT record in `topology.clients` is the
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
(`ScoutPoller`, `fleet/scout_poll.rs`), never inside a board read, and `scout_payload_from_state`
turns what it reads into the shape of a heartbeat. The pull refreshes only the machines the board
holds (`record_host_report(..., only_known=True)` makes none) and skips a scout that holds no
controller: a ✕ on the NAS board was undone by a pull in flight, and the scout, let go and open to
anyone, kept the machine "online" through every next pull (2026-10-11). Which fields a report carries: the scout's
`rust/crates/scout/src/report.rs`, read here by `fleet/reports/record.rs`; `scripts/test_rust_whole.py` runs the
three programs together and holds that joint. Agents and their ports are made by hand; removing an agent takes its
assignment row and leaves its ports free. Deleting a client leaves the host record alone. A machine
joins and leaves through `ScoutPairing` (`fleet/scout_pairing.rs`, below). The controller also hosts every node's
named launch-config backups under `var/server-backups/<host>/<gpu-model-or-CPU>/<stamp>-<name>.json`
(path-safety enforced) so a client's backups survive the client.
Owns: the `clients`/`hosts`/`assignments` sections of admin state; the `var/server-backups/`
store.
Key functions: `client_llama_start`, `client_llama_stop`, `client_monitor`,
`client_llama_configs`/`_save`/`_delete`, `client_llama_list_cache`/`client_llama_purge_cache`,
`record_host_report`, `topology_hosts`, `topology_clients`, `refresh_hosts_from_scouts`,
`topology_client_delete`/`topology_client_agent_delete`, `set_topology_client_alias`; `SCOUT_PAIRING`.

## `fleet/scout_pairing.rs`

`ScoutPairing` — the one way a machine joins the fleet as a scout host. The machine only installs
its scout (the command of ＋ Add scout); the operator enters its address on the board, and
`connect` reads the scout's open `/api/pairing`, hands it the controller's address and the fleet
token (`POST /api/controller-url`) and returns once the scout's first heartbeat has made the host
record. `controller_url_for` picks the address the scout will reach: 127.0.0.1 for a scout on the
controller's machine, else the controller's name when it is reached by one through a reverse proxy
(`LLAMA_TOPOLOGY_SERVER_URL`, the NAS's `https://caravan.example.org` — its own port listens on
loopback only), else `LLAMA_TOPOLOGY_SERVER_IP`, else the interface that routes towards it. A name
that is not a plain `http(s)://host[:port]` is refused (500, naming the setting), not handed out: a
scout puts its own paths after it. A scout that took the name and cannot reach it is told to check
the name, the reverse proxy and the home certificate, not to open a port.
`disconnect` asks the scout to let go (`/api/unpair`) and forgets the host record — a silent scout's
machine only forgotten, a refusing scout's kept. Every failure is worded with what to do.
`scripts/test_rust_admin_conformance.py` stands a fake scout behind it.

## `fleet/scout_scan.rs`

`ScoutScan` — the 🔍 on the board's Add scout row (the owner, 2026-10-11): which machines of a private
network answer as a caravan-scout. `scan(networks, port)` knocks on every address of the networks asked
— networks or addresses typed by commas or spaces, or, when none, the controller's own /24s (the address
it reaches the network from and `LLAMA_TOPOLOGY_SERVER_IP`) — and asks those that take the connection
the scout's open `/api/pairing`. Only private IPv4 networks are scanned, at most 1024 addresses in one
scan; anything else is refused with 400. A found scout is `free`, `here` (its machine is on this board)
or `taken` (another controller holds it); nothing is changed — Connect on the board pairs a free one
through `ScoutPairing`. `POST /api/topology/scout/scan` answers `{networks, port, scanned, found}`.

## `fleet/launch_files.rs`

`LaunchFiles` — the files a cell's launch uses, each under its role on the card (`MODEL_FILE` →
model, `MMPROJ_FILE` → mmproj, `SPEC_DRAFT_MODEL_FILE` → draft), and how they stand against
Hugging Face: `fresh(report, models_dir)` reads the model watcher's report (keyed by the path
relative to the models directory; an absolute path inside it is brought to that key, one outside
is not checked) and keeps only what differs (`size`, `date`) or was not checked (`unknown`) — a
"matches" is never drawn. `disk_newer(reported)` keeps the roles a scout names as changed on disk
since its cell started (scout 2.11+; an older scout says nothing, which is not "unchanged").
`topology_server` puts both on every cell's card (`launchFresh` running and stopped,
`launchDiskNewer` running only) — the ⇪ and ⟳ chips the controller's own cells had until step 6.9.

## `topology/`

Assembly of the `/api/topology` tree — the first aggregator layer. `topology_server` builds the
fleet's cells: every cell a scout reports (running or starting — health, live metrics, context
usage, modalities, crash note read with `CellWords`, TPS history) and every stored slot that is not live, as a parked card
(its trained window from the GGUF header, ≈VRAM from the file's size), plus the controller's own GPU
read for its machine's node. Since step 6.9 there is one kind of cell: the controller's own cells,
their unit status, journal errors, load progress and freshness chips went with them. `topology_nodes` produces the
host-centric spine: one node per machine with a scout, servers bound to GPUs via compute apps, and
the rest of each card's memory named by who holds it (`outside`, from `GpuOwners` in
`domain/engine.rs`: an engine of the machine by the processes its scout names, else the
process's own name); a node carries its machine's `engines` as the host record keeps them. The
controller has no node of its own since step 6.9 — its machine is its scout's host node, marked
`controllerMachine` (with the controller's own `gpuError` for it). A node also carries
`driverWarnings` — `DriverOutlook` in `domain/driver_outlook.rs` reading its scout's
`driver` facts (2026-09-26: a kernel the automatic updates installed booted without its
Canonical-signed modules, and Secure Boot refused the DKMS build signed by the machine's unenrolled
key): `nextBootNoDriver` when a new kernel boots next and has no nvidia module (`missing`) or one
Secure Boot will refuse (`unsigned`, `untrusted-key` — signed by the DKMS key the firmware does not
know), with the `linux-modules-nvidia-<branch>[-open]-<kernel>` package that fixes it when the driver
package is known; `rebootForDriver` when the driver installed is not the one loaded. It says
nothing it cannot tell: Secure Boot unknown, a signer it does not know, a key whose enrolment is
unknown, the same kernel booting next. `topology_state`
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

## `fleet/cell_talk.rs`, `fleet/cell_talk/`

The voice window on the controller's side (1.3.606): a running cell asked by voice or by text on
the operator's behalf, `POST /api/cell-talk`. The page may not ask a cell itself — the board is
https, a cell plain http on its machine — so it records and sends here, as a client's card asks the
entry through `AsConsumer`. `TALK_MODES` is the one table of the window's ways of talking: what each
takes (a recording or a text), what comes back, the one path it asks and how it reads the answer —
`spoken-chat` and `heard-chat` (`/v1/chat/completions`, the recording as an `input_audio` part,
`modalities` text and audio for the first), `speech` (`/v1/audio/speech`, a wav back),
`transcription` and `speech-translation` (`/v1/audio/transcriptions` as a form). A runner names the
modes its server answers in `TalkSpec` (`domain/runner/specs.rs`), with its voices by mode, the
request field that names one (Qwen3-Omni's `speaker`), its system prompt and how many messages a
request carries, the cue that begins a spoken answer (Step-Audio 2's `<tts_start>`) and the model's
own tokens its words carry; `talk_modes_json` goes to the board in `/api/state`. `CellTalk.talk` finds the cell
in its machine's report (running, with a config — without one the board does not know what runs
there), refuses a mode its runner does not answer, reads the window's body (`TalkAsk`: base64,
sizes, roles) and asks through the cell's machine's scout (`cell_doorway.rs`), timing the answer until it began and in all. The cell's refusal is handed on
as an answer (`status`, its words in `error`); no answer at all is 502.

A cell that keeps voices (Qwen3-TTS, 1.3.608; the voice-clone runner's, 1.3.611, which speaks vLLM-Omni's
requests for it — `cells/tts_server.py`) says so in its `TalkSpec`: where its server lists them
(`voices_path`, vLLM-Omni's `GET /v1/audio/voices`) and that it speaks in the voice of a sample
(`clone`). `speech` then takes a sample (`sample`, a wav in base64, and `sampleText`, its words) and
asks with vLLM-Omni's `ref_audio` (a data URL) and `ref_text` — or `x_vector_only_mode` without
words; a sample to another mode or runner is refused, not dropped (the answer would come back in
another voice). `CellTalk.voices` reads the cell's list (`VoiceList`: the model's voices, and those
kept from a sample with their words; vLLM-Omni's `default` is no voice), and `CellTalk.store_voice`
keeps a voice under a name (`POST` of the same path as a form, `FormBody`), a name of
`TalkSpec.VOICE_NAME` — the rule the window reads from the runner row. Both a sample and a kept
voice need `consent: true`, the operator's word that the voice is theirs or its owner agreed
(`Consent`); a kept voice is stored with `Consent.ID`. Routes: `GET /api/cell-talk/voices`,
`POST /api/cell-talk/voice`.
Key classes: `TalkMode` and its five modes, `TalkAsk`, `CellTalk`, `VoiceList`, `FormBody`, `Consent`.

## `fleet/cell_doorway.rs`

The way from the controller to one cell: through its machine's scout. Since step 7 of the owner's plan (Papyrus
`caravan-scout-port-lease`, 2026-11-08) a cell listens on its machine's loopback alone (`rules::CellDoor::LISTEN`, which
the command builders write as `--host` and every cell server of `cells/` binds), and the machine shows the network one
port of the caravan, its scout's. `CellDoorway::of(app, host, cell)` is the scout's address as its machine reported it
(`agentUrl`), the fleet token's field, and the cell's name; `url(path)` is `<agentUrl>/api/cell/<cell><path>`, the scout's
door, which hands the request to the cell on the loopback as it came and every byte after it both ways (the scout's
`cells/door.rs`). Everything the controller asks a cell goes this way: the health and the `/props` the board's cell rows
read (`RemoteCells`), the voice and text questions of the Talk tab (`CellTalk`), and a live talk's WebSocket
(`CellLive`). A machine that reported no scout address with its port has no way to its cells: a row then says its health is
not known, never "down". Before, each of these asked `<machine ip>:<the cell's port>` straight over the network, and only
the owner's firewall rule kept anyone else out; the board drew whom the firewall let in (`firewall`), whether the
controller reached the port (`reachable`) and the rule to open it. Those words are gone with the way. A scout older than
2.48.0 has no door: a start on its machine is refused with "update the scout" (`ScoutStart::OPENS_ITS_CELLS`), and the
scout takes the release at its machine's next report. Every slot loses its `HOST` once, at the start
(`ListenAddressRetired`): the address is the caravan's word, not a setting of the cell, and EXTRA_ARGS cannot say
`--host` or `--port` again (`LlamaArgs::CARAVANS_OWN`).

## `fleet/cell_live.rs`

A live talk with a running cell over the cell's own WebSocket, through the controller (1.3.612): `GET /api/cell-live`
opened as a WebSocket. A runner says it talks live in its `LiveSpec` (`domain/runner/specs.rs`: the cell's path —
MiniCPM-o's `/backend` — and the protocol the board's window speaks there). `CellLive` finds the cell as the voice
window does (`CellTalk.cell`: running, with a config), opens its WebSocket through the scout's door (`cell_doorway.rs`) with the browser's own handshake (`LiveAsk`:
the key, the version, the extensions and the protocol go on; the page's Origin and the board's cookie do not), checks
the 101 and its accept (`CellAnswer`; anything else is 502 with the cell's line) and hands that answer to the browser.
From then on it passes the bytes both ways, unparsed — the client's masked frames one way, the server's frames the
other — until a side ends or both are silent for five minutes (`relay`: the bytes each way, and what ended it, go to
the log). A plain GET of the path answers what a talk would reach and the cell's answer to its health, so the window
can tell a door that drops WebSocket from a cell that is down. Admins only (`RouteAccess.ADMIN_GET`): a talk sets the
model talking, as the voice window's POST does; the session cookie is SameSite=Lax, which a browser does not send with
a WebSocket another site opens.
Key classes: `LiveAsk`, `CellAnswer`, `CellLive`.

## `fleet/model_card.rs`

What a port answers a client on `GET /v1/models`, asked on the operator's behalf
(`GET /api/agent-proxy-model-card?port=`). The controller asks the entry with the route's key: a client has no port of its own, and the key
never reaches the page. The answer is parsed (`entries`: every window name found, the one a client
reads first, the running server's `meta.n_ctx`, the trained window) and kept raw; a port that does
not answer is an answer too (`ok: false`, `status`, `error`). `windowLinks` lists every path on
which the port states its window: `Windows::paths` (`common/window.rs`), by what the port's question
reaches (`PortQuestion`, `topology/windows.rs`). Retrieve-model links use the ids the port itself just
named, so a port that did not answer gets none. Since 2026-11-02 no route's own port listens, so the
card of a port reads as one that did not answer.
Key functions: `proxy_model_card`.

## `proxies/ops.rs`

Cross-domain proxy actions sitting above the domain modules. `stop_agent_proxy_route` appends
`stopRequests` entries (by request id, or every active request on a port) to `agent-proxies.json`;
a running request looks there every 0.25 s (`Watch::check_stop`, `rust/crates/proxy/src/watch.rs`) and ends. (Reconciling the stored assignments
with the scouts' live reports went with the reports, 2026-09-24: the stored rows are the truth, and
a port no row claims stays until the operator deletes it.)
Owns: —.
Key functions: `stop_agent_proxy_route`.

## `proxies/service.rs`: the proxy, its child

The proxy is a child process of the controller, wherever the controller runs: there is no unit of its
own. `start_proxy` starts it at the controller's start, with a watchdog that looks every 500 ms
(`proxy_tick`): a dead child is respawned; a closed entry has no child; an entry that moved kills the old
child, so that its port is free now and not when its last request ends; a new file of the program
(`<root>/bin/caravan-proxy`, by its time and size) starts beside the running one, which sees its own file
change, lets the port go and finishes what it has (`rust/crates/proxy/src/drain.rs`). The child's output
goes to `logs/rust-proxy.log`, and it runs in a session of its own, so it is told who keeps it
(`CARAVAN_PROXY_KEEPER`, this process's id) and leaves when that one is gone. `proxy_status` is the System
modal's word on it.
Owns: the child process handle + watchdog thread.
Key names: `Services` (`start_proxy`, `proxy_status`, `proxy_brief`), `ServiceChildren`.

## `fleet/controller_machine.rs`

`ControllerMachine` — which scout's machine is the one this controller runs on: its scout reports
the machine's hostname, and the controller knows its own (short name, any case). Since step 6.8
that machine's cells run through its scout like any other's; it is still the machine to show
first and the one whose panels the controller fills from its own monitor. `name()` is the computer's
short hostname, case kept — `topology.server.hostname`, the name the board gives the controller's
machine when no scout reports from it (a scout reports the same name). It replaced the
controller's own display name (`LLAMA_TOPOLOGY_SERVER_NAME`, no longer read), which Routing
had put over that machine's cells.

## `status.rs`, `status/llama_build.rs`

The composite dashboard state. `state()` is the `/api/state` payload: parsed config + field
metadata, paths, model catalog, chat templates, the legacy single server's service status and
diagnostics (`legacy_port_props` is the probe of its port, asked only while its unit is active),
CPU/GPU/memory, llama.cpp build info and the project's own git info. That server's journal tail and
runtime summaries left the payload in 1.3.485: no page showed them, and each page load ran journalctl
and four HTTP probes for them. (Starting and
stopping `llamacpp-current.service` and its start-server.sh backups went with the controller's own
cells in step 6.9.) `llama_cpp_info` reports the binary
version and feature support plus the llama.cpp checkout's git state (optionally checking upstream
for the newest `bNNNN` build tag); `update_llama_cpp` refuses when tracked files are dirty, then
fetch + ff-only merge + cmake-builds `llama-server`. `project_git_info` of an image build (no
checkout) has no branch: `branch` is empty, `baked` true, `head` the baked commit — it named the
branch "docker", and the board's chip read "git: docker".
Owns: —.
Key functions: `state`, `legacy_port_props`, `llama_cpp_info`, `update_llama_cpp`, `llama_server_path`,
`project_git_info`.

## `fleet/cell_ops.rs`

Server-cell lifecycle actions, each through the scout of the cell's machine; sits above `status`
because its handlers return the composite `state()`. `client_server_slot_add` declares a persistent
slot (reserving the next free port when none is given); `client_server_slot_delete` removes the slot
and also tells the scout to stop/clear the node — otherwise the cell keeps coming back with the next
report. `CellAutostart` (1.3.504) keeps a cell's autostart with its slot: the scout's kept request
makes a slot again where the controller lacks one (`KeptCells`), so a deletion takes the request away
first (`forget`). A request is kept by the cell's id since 2026-11-07 (scout 2.46.0), and there is no port move or swap
to follow any more. A scout out of reach keeps its request, and the answer says so (`autostart: {ok, error?}`). `server_cell_save_config` saves without starting (and refreshes the request the scout keeps
for an autostart cell); a cell whose runner serves a page of its own (`PageSpec`, PersonaPlex's `PAGE_URL`) has the
page's address checked for its form first — https, a name, a port and a path or none — and is refused whole otherwise
(1.3.613): the form hears why, and a start never reads the address. `server_cell_action` forwards start/restart (from the saved slot config;
command cells must have a COMMAND, llama cells a model), stop, and enable/disable (the scout's
autostart) to the scout; the controller's own host id is refused — it runs no cells since step 6.8.
`bring_home` brings a scheduled cell's model home from a library before its window opens, when there
is room; when there is not, the cell reads it where it lies — the move planner's `no-room` refusal
IS that answer. `script_preview` shows a script a command names, from this machine's home.
Owns: —.
Key functions: `client_server_slot_add`, `client_server_slot_delete`, `server_cell_save_config`,
`server_cell_action`, `bring_home`, `script_preview`; `CellAutostart` (`CELL_AUTOSTART`: `forget`, `moved`).

## `fleet/default_cells_retired.rs`

The default cells of 2026-11-05, retired on 2026-11-07 (Papyrus `caravan-scout-port-lease`, step 1). From 2026-11-05 every
folder of the library got a cell on every machine at each start: a slot with a reserved port and one more fact,
`defaultFor`. On 2026-11-07 that was 51 of the 85 ports of the big machine, none ever started, and one took an `mmproj` file
for its model. The owner chose: a cell holds a port only while it runs, and a default cell becomes a preset — the
maker's numbers, offered by the launch builder as the model's own set (`makers` of `RunnerPresets::list`), with no slot
and no port until a launch of them is started. A step of the start's migrations looks at each marked slot once: one the
preset gives back whole — its config is `ModelDefaults::values` of its folder with at most a file, the names the pass
gave it, no note, schedule or command history — goes, kept as it was under `topology.defaultCellsRetired` (`at`,
`slots` by key) and its cables taken away as a deletion takes them (`CellOutputs::dropped`); one that holds more is the
operator's cell now and only loses the mark. `cacheModels` is not the operator's here: a start asks it again, and the
record keeps it. No code makes the mark any more, so the step finds nothing after the first start.
Owns: `defaultCellsRetired`.
Key functions: `DefaultCellsRetired::migrate`, `DefaultCellsRetired::given_back`.

## `routes/`, `web/server.rs`, `web/table.rs`, `web/exchange.rs`

HTTP route tables and the request handling. A topic's routes are a `Routes` table in `routes/<topic>.rs`:
`(path, function)` rows for GET, POST and DELETE. `AllRoutes::table` (`routes/mod.rs`) adds them, and a path
twice stops the program at the start. Prefix routes are the only prefix matches — `/api/monitor/` and the
`/js/`, `/css/` static subdirs (a name of letters, digits, `.`, `_`, `-`, no traversal) — checked before the
exact ones. A POST reads the body before the path lookup (empty → `{}`, anything but a JSON object → 400,
chunked → 411); every verb answers with the status an `AppError` carries. `Exchange` provides `send_json`,
`send_file` (mtime+size ETag with `Cache-Control: no-cache` — a new release shows up immediately, unchanged
files answer 304) and `read_body`. `AdminServer` serves HTTP/1.1 with connections kept, one thread to a
connection; a panic ends the one request it is in. One DELETE route (`/api/hf/local-file`); static pages `/hf`,
`/board` (`/` redirects here), `/machine`, `/routing` (`/router` redirects), `/models` and `/system` come from
`static/`, and `/login` and `/setup` from the program's own files (`web/page_shell.html` and the two forms).
`Guard` (`web/server.rs`) lets a request through by `RouteAccess`.
Owns: the route tables.
Key names: `AllRoutes`, `Routes`, `RouteTable`, `AdminServer`, `Exchange`, `Guard`.

## `web/access.rs`

`RouteAccess` — who may call a route: open (`/health`, `/api/health`, `/healthz`, `/openapi.json`, `/api/packages`,
the login and setup pages and their POSTs, `/api/auth/me`, the favicons, and the two files a new machine
takes, `/scout/install.sh` and `/scout/bundle.tar.gz`), the machine endpoints on
the fleet token
(`X-Caravan-Token`), `/metrics` on the fleet token as a header or a Bearer token or a session, and a
session for everything else — a viewer account may call every GET but `ADMIN_GET` (the raw routes
file, which holds the clients' keys, and a live talk with a cell) and log out. The guard that enforces it is
`Guard` (`web/server.rs`); the document that states it is `routes/openapi.json` (`security` and
`x-caravan-roles`), and `rust/crates/admin/tests/contract.rs` holds the file to the routes.
Owns: the open and machine path sets.
Key names: `RouteAccess` (`kind`, `viewer_may`), `Access`.

## `routes/openapi.json`

The admin API as OpenAPI 3.1, served at `GET /openapi.json` (open) — the home rule: every app serves its
API description there. It is a file: it was written out of the Python route tables and their docstrings
while they stood, and is edited by hand now. `rust/crates/admin/tests/contract.rs` holds that every route is
in it and nothing else is. What each handler's code did not show — a query or body passed on whole — is
marked "may read more" (`x-caravan-query-complete` / `x-caravan-fields-complete: false`), never drawn as
"reads nothing"; field types and answer shapes are said to be not described yet (level 1).
`scripts/check_api_spec.py --write` renders the same document into [http-api.md](http-api.md) between two
markers. `info.version` is the commit `/healthz` names — the home network's deploy check compares the two
(visumap apps-openapi.md) — the controller's version when none is known, and `info.x-release` the controller's
version.
Owns: nothing mutable.

## `packages.rs`

`GET /api/packages` (open, like `/healthz`): what the running controller is made of, named as osv.dev
names it, for the vulnerability check of the home network (visumap apps-packages.md) —
`{version, runtime, os, packages}`, each package `{ecosystem, name, version}`, `version` the commit
`/healthz` names. The list is the crates the programs were built with (`crates.io`, from
`bin/rust-packages.txt`, which the release's build writes with `cargo tree`) and, in the image, Debian's
installed packages (`Debian:<release>`) — by their SOURCE package and the source's version, the names Debian's
advisories use (libc6 is glibc, a rebuilt `+b1` binary is its source's version). A system whose packages it
cannot read (Ubuntu, Debian without a numbered release or without dpkg's status file) is `os.listed: false`;
one it cannot tell is `os: null`. A controller run from a build tree has no such file and lists no crates.
Owns: nothing.
Key names: `InstalledPackages` (`listing`, `system`, `crates`, `debian`).

## `main.rs`, `startup.rs`

Entry point. `Program::run` refuses a container without its two settings and a bad set of port ranges, makes
`App`, reads the route tables, runs `Startup::run` and only then binds `LLAMACPP_ADMIN_HOST:PORT` and serves
forever. Two flags are their own programs: `--health`, the container's check of itself (the image has no other
tool to ask with), and `StoreProbe::CHILD_FLAG`, a look inside a store as a child process.
`Startup::run`: a data folder this process cannot write stops the start; then the proxy and its watchdog, the
one-shot migrations (a step that fails says so and the rest go on; the last retires the models' default cells,
`fleet/default_cells_retired.rs`), the built-in clients, the pools' rows of the machines, and the background threads: the first walk of the models folder, the board's first read over the
journal, the monitor sampler loop (1s cadence), a one-shot bootstrap that recomputes cloud-fallback eligibility
from current graph connections (writing `agent-proxies.json` only when something changed), the 6-hour threshold
refresh loop, a minute's giving back of freed memory, the release watch, the GPU driver's watch and the cells'
schedule; last, moves of models left unfinished go on.
The release watch: when `CARAVAN_ROOT` is a link and comes to name another folder, the process ends once the
proxy's state file shows no request running, ten minutes at the most, and the container's restart starts the new one.
Owns: thread startup order.
Key names: `Program`, `Startup`.

## Invariants for contributors

- **Layering.** A crate depends only on the crates below it, and the compiler holds it so.
  `scripts/check_rust_contract.py` holds the rest of how the Rust is written: a function outside
  an `impl` needs a written reason, no global mutable state, no `unwrap_or_default` without one.
  The rules and their reasons: [rust-code.md](rust-code.md).
- **Atomic writes.** Config/state files go through `files::AtomicFile` (a temp name beside the
  file + a rename); never write shared JSON files directly.
- **Paths.** Every path and env-driven constant comes from `AdminPaths` (`paths.rs`), read once.
- **File ownership.** The controller writes `agent-proxies.json` — always through
  `ProxiesConfig::write_payload` (normalizes, protects the router graph, fires the `.bak-graph`
  autobackup). It only *reads* `state/agent-proxy-state.json` and `logs/proxy-events/*.jsonl`; the
  proxy owns those. The credential document has one writer in both programs,
  `files::CredentialVault`.
- **Routes.** A route is a row of a `Routes` table; a path twice stops the start. Only
  `/api/monitor/`, `/js/`, `/css/` may be prefix-matched. A new route needs its entry in
  `routes/openapi.json`, with a summary of one line: `scripts/check_api_spec.py`.
- **Crates.** Every third-party crate has its reason in `scripts/check_rust_contract.py`; a new
  one fails the guard until it does.
