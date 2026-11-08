# Operations

Day-2 runbook for a production deployment. Assumes the layout from
[architecture.md](architecture.md): a controller in a container, its release as files
beside the image, its state in one data folder, and a scout on each machine with
hardware to share. A controller outside a container differs only in what keeps it
running. Paths below are under the data folder (`CARAVAN_DATA_DIR`) unless they say
otherwise.

## Services

| Process | Runs | Notes |
|---|---|---|
| `caravan-admin` | the container's main process (`:7990` by default) | Admin UI + API. Its words go to `docker logs`. |
| `caravan-proxy` | a child of `caravan-admin`, no unit of its own | The entry for keys. Route/config edits do NOT need a restart: it looks at the files' stamps on each request. Its words go to `logs/rust-proxy.log`. |
| `caravan-scout` | `caravan-scout.service` (systemd --user) on each machine with a scout | Runs that machine's cells. |
| `llamacpp-current.service` | `~/llama.cpp/start-server.sh` (`:8080`), on an older machine | Legacy single managed server. |

```sh
docker logs --tail 50 <container>
tail -n 50 <data>/logs/rust-proxy.log
curl -s http://127.0.0.1:<admin port>/healthz                   # names the commit that runs

# on a machine with a scout
systemctl --user status caravan-scout.service
journalctl --user -u caravan-scout.service -n 50 --no-pager
```

Firewall, once per machine: the entry's port must be let in, unless a reverse proxy on
the same machine is the way in. `sudo ufw allow 23001:23999/tcp` lets the proxy range in,
the entry's default port among it. The controller never touches the firewall itself.

Boot-time autostart: the container's restart policy, and on a machine with a scout
linger, which the scout's installer enables.

## Deploy

A release is one folder: the two programs, the board's files, the cell servers, `VERSION`
and the scout the controller hands out, each from one commit. The image is the system
alone. A new version needs no password and no new image.

1. Build the programs from the merged commit, in the image CI checks with (a program
   built on Debian's older release runs on the newer one, not the other way round).
2. Bring the files into a folder of their own, `rust-bin/releases/<commit>/`, which the
   container sees read-only, each checked against what was built.
3. Move the link `rust-bin/current`, last. Moving the link is the delivery.
4. Wait until `/healthz` names that commit.

The home deployment does all four with one command, `python3 deploy/nas/release_ship.py`
(it names its machines, and `deploy/nas/` stays out of the public mirror). The running
release and the two before it stay; the older go.

Then a machine's scout takes that release by itself when the scout in it changed: the
controller hands it at the machine's next report (rust/crates/admin/src/fleet/scout_follow.rs),
compares the two releases by `content` in `scout-bundle.json` (the program and its scripts),
asks a busy scout again 2 minutes on, and says each step in its log (`[scout-release]`).
`CARAVAN_SCOUT_FOLLOW=off` in its environment turns that off. The machine's ⋯ menu on the
board, **Update the scout**, does the same by hand, and a busy machine is asked again in
the same cycle. Cells outlive the restart. A copy of a
model, a move of its model folders and a build do not, so a machine in the middle of one refuses
and nothing changes. A
request through the machine's entry does not refuse it: the scout puts the release in place,
answers what it waits for (`waitsFor`), and ends once nothing passes through it, ten minutes
at the most, as the controller waits for its proxy (`rules::ReleasePatience`). A
new machine takes it with the command of ＋ Add scout.

What restarts what:

- The controller sees the link move (it looks every 5 s), ends once no request runs on the
  proxy, the old or the new, ten minutes at the most, and the container's restart policy
  starts the new one. The board is gone for a few seconds.
- A new file of the proxy is started beside the running one, within half a second. The old
  one lets the port go and answers what it has, and the controller's wait above counts it
  too: a release cuts a stream only past the ten minutes.
- The proxy is respawned when it dies, within half a second. A move of the entry to
  another port replaces it at once: the requests it holds are cut.
- A machine's scout that took a release ends at its first look (every quarter of a second)
  at which no connection is answered — a request through the machine's entry, a stream
  among them, or a call of the controller — and no work of its own runs: a cell on its way
  up, a build, a move of its model folders. It serves new requests meanwhile, and waits for them too. The connections are
  waited for ten minutes at the most from the release; past them it cuts what runs and its
  log says what (`[release]`). Its own work, begun after the release came, is waited for to
  its end: nothing would finish it. The service starts the new scout 3 s after the end
  (`RestartSec`); a request that comes in those seconds finds the entry refusing, and the
  proxy waits for it, 15 s at the most (`machine_entry_wait`).
- The image changes only with the system under the programs. Then it is built again and the
  container started anew, which takes the host's password and ends what runs.
- `static/` needs no restart of its own: every file is read from the release per request
  and sent with `ETag` + `Cache-Control: no-cache`, so browsers revalidate on reload.
- The data folder is runtime state, never deployed.

Post-deploy smoke, with no session (only the public routes answer):

```sh
curl -s localhost:7990/healthz                                                  # the commit just shipped
curl -s -o /dev/null -w '%{http_code}\n' localhost:7990/openapi.json             # 200
curl -s -o /dev/null -w '%{http_code}\n' localhost:<entry port>/v1/models        # the entry: 401 without a key is the healthy answer
```

## Rollback

```sh
python3 deploy/nas/release_ship.py --back     # the link to the release before this one
```

By hand: point the link `current` at another folder of `releases/`. The controller restarts
onto it once no request runs. There is no way back to the Python controller: it left the
repository on 2026-11-02 (its last commit is `4c53bc92`).

On-disk state files are kept forward/backward compatible, so rolling code
back does not normally require touching `config/agent-proxies.json` /
`state/agent-proxy-state.json`.

## Backups & recovery

| What | Where | Created |
|---|---|---|
| Router (Routing) config | `config/agent-proxies.json.bak-graph-<stamp>` | automatically on an admin write of `agent-proxies.json` while the file still holds graph nodes; the newest 20 stay |
| Launch configs per node | `server-backups/<hostId>/<gpu-model-or-CPU>/<stamp>-<name>.json` | UI snapshots (survive the machine) |
| Every setting, before a settings import | `settings-backups/<YYYYMMDD-HHMMSS-micros>-before-import.json` | automatically before every `POST /api/settings/import`: the whole file, secrets and accounts included, so it is written 0600 — importing that copy undoes the import. One file per import, never written over: two imports in one second keep both |

Restore a broken router config:

```sh
ls -t config/agent-proxies.json.bak-graph-* | head -3
cp config/agent-proxies.json.bak-graph-<stamp> config/agent-proxies.json   # the next request goes by it
```

## Local development (macOS or any host)

A whole caravan on one laptop, with stand-ins for the cards and the engines:
[stand.md](stand.md).

### Moving the admin port

`LLAMACPP_ADMIN_PORT` is the only lever — no code change. What makes this a
fleet operation rather than a restart is that **nothing rediscovers the new
address**: each scout keeps `controllerUrl` in its own `config.json`, and a
scout that cannot reach the controller still ANSWERS the controller's polls, so
the board keeps looking healthy while heartbeats, model pulls and cell-asset
syncs are all dead.

Order that survives it, with no shim needed — a scout tolerates an unreachable
controller and reconnects by itself:

1. Open the new port in the firewall FIRST. Anything outside the rules the machine already has needs its own rule, and
   a forgotten rule is the one failure that looks like the app being broken. (The cells' range, 22001–22999, needs none
   since 2026-11-08: a cell listens on its machine's loopback, and the scout's port, 8092, is the machine's one port of
   the caravan.)
2. Re-point every scout while the controller is still on the old port —
   `POST http://<client>:8092/api/controller-url` with `{"url", "token"}`. It
   rewrites config.json and applies live; no restart, no ssh.
3. Change `LLAMACPP_ADMIN_PORT` in the container's environment and start it anew.
   Heartbeats resume within one interval.
4. Verify each client's `lastSeen` on the board before touching anything else.
5. Sweep the leftovers: bookmarks, and any
   `config.json.bak-*` that would resurrect the old address on a restore.

Run the controller alone against scratch state, from a release folder ([the README's
quick start](../README.md#quick-start) makes one):

```sh
CARAVAN_ROOT=<release> CARAVAN_DATA_DIR=/tmp/caravan-dev LLAMACPP_ADMIN_PORT=7991 <release>/caravan-admin
```

`CARAVAN_DATA_DIR` rebases every mutable default (state/, config/, logs/, secrets/,
models/, server-backups/, settings-backups/) under one directory, and the proxy does not
start without it; a variable of its own (`AGENT_PROXY_CONFIG_FILE`, `LLAMA_ADMIN_STATE` …,
`rust/crates/admin/src/paths.rs`) still wins for one file.

Hardware probes (`nvidia-smi`, `systemctl`) degrade gracefully — a tool that does not
run is an answer, never a crash — so the server works on a laptop with empty panels. The
monitor sampler also runs on macOS: memory comes from `vm_stat`/`sysctl`; per-core CPU%
stays 0 (no `/proc`), loadavg is real.

Quick checks while developing:

```sh
(cd rust && cargo test --locked --workspace)
(cd rust && cargo clippy --locked --workspace --all-targets -- -D warnings)
python3 scripts/check_rust_contract.py
node --check <(cat static/js/<module>.js)        # ES-module syntax (or copy to .mjs)
```

cargo starts every test binary through `scripts/rust_test_runner.py` (the root `.cargo/config.toml`, held by
`scripts/check_rust_test_start.py`): a binary gets 300 seconds and is stopped with everything it started when it runs
longer, when the run that started it is gone, or when the runner is told to stop. A stopped binary fails the run with exit
124 and a line that names it; the hung test is the one libtest named "has been running for over 60 seconds". A run that is
long on purpose sets `CARAVAN_TEST_LIMIT=<seconds>`; there is no "no limit". The runner needs Python 3.11 or newer.

## Controller in a container

Neither a container nor a bare machine runs cells: they run on machines with a scout. The
image is the system under the programs and nothing of them: `debian:bookworm-slim`, its
updates, `tzdata` and `ca-certificates`, no Python.

```dockerfile
ENV CARAVAN_CONTAINER=1 CARAVAN_DATA_DIR=/data CARAVAN_ROOT=/app/bin/current
VOLUME /data
HEALTHCHECK CMD ["/app/bin/current/caravan-admin", "--health"]
CMD ["/app/bin/current/caravan-admin"]
```

The release's folder is mounted read-only at `/app/bin` (`current` in it is the link), the
data at `/data`, and the restart policy is `unless-stopped`: a new release relies on it.
The `Dockerfile` at the root of the tree is the other way: it builds the programs, the board's
files, the cell servers and the scout into one image, and `docker-compose.yml` runs it read-only with
no capabilities and its two ports published. A new version is then a new build, `docker compose up -d --build`.
What changes inside (`CARAVAN_CONTAINER=1`):

- Two settings are required, and the container refuses to start without
  them (exit code 2, the reason on stderr): `TZ`, the controller's time zone —
  every schedule runs by it, and a container would otherwise run in UTC
  silently — and `LLAMA_TOPOLOGY_SERVER_IP`, the address agents and scouts
  reach it at. The image carries the zone data (`tzdata`).
- Behind a reverse proxy, with the controller listening on loopback only (a NAS),
  `LLAMA_TOPOLOGY_SERVER_URL` names the controller as the fleet reaches it, e.g.
  `https://caravan.example.org`: "Add scout" hands every scout that name instead
  of the address and port, which answer nobody else there. The scout's machine must
  trust the certificate. `LLAMACPP_ADMIN_HOST` and `AGENT_PROXY_HOST` are `127.0.0.1` then,
  and the reverse proxy leads one name to the board and one to the entry.
- To find the scouts of the network without typing addresses, press 🔍 Find on the Add
  scout row: it scans the networks typed there (`10.0.30.0/24`; empty — the
  controller's own /24) for caravan-scout on its port and lists each one: free (with
  Connect), already on the board, or held by another caravan. A container on the host
  network (`network_mode: host`, the NAS) reaches the other networks of the house as the
  machine does; a scout's machine must let the port in through its firewall.
- A locked-down container runs as is: `security_opt: [no-new-privileges:true]`,
  `cap_drop: [ALL]`, `read_only: true` with `tmpfs: [/tmp]`. The controller writes only
  under `/data`, each file through a temp file beside it (`rust/crates/files/src/atomic.rs`),
  and binds ports above 1024, so it needs no capability. Then a
  setuid program inside (`su`, `passwd`, `mount`) gives no rights, and nothing can be
  planted outside `/data`. To check it:
  `docker inspect --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.SecurityOpt}} {{.HostConfig.CapDrop}}' <container>`
  prints `true [no-new-privileges:true] [ALL]`.
- The data folder must be one this user can write. A folder with a Synology ACL
  (`ls -ld` shows `+`) lets its owner write over ssh and refuses a container, which runs as
  that uid without its groups: the start stops and says so
  (`rust/crates/admin/src/data_tree.rs`), and `chmod 755` on the host cures it. A models share
  with an ACL of its own is mounted at `/data/models`, with its group added by `group_add`. A
  scout takes a model from the controller (`GET /api/models/download`), never from the share.
- The proxy is the controller's child, as everywhere
  (`rust/crates/admin/src/proxies/service.rs`) — respawned by a watchdog on a crash,
  replaced when its file changes. Its output goes to `/data/logs/rust-proxy.log`;
  `docker logs` carries the controller.
- The legacy single-server unit and "Repair user service" are disabled with
  a clear 400 — models run on caravan-scout hosts (attach the Docker host
  itself with scout if it has the GPU).
- The machine is asked through its scout (1.3.439–1.3.440, scout 2.24+):
  powering the controller's machine, its GPU driver and its update, the list
  of its cards, the monitor's GPU and busiest processes, the nvidia-smi and
  btop snapshots — the same way as on the machine. Put a scout on the Docker
  host (Machines → Add scout); without one each of these says "there is
  no scout on the controller's machine" (409 for an action) instead of failing
  inside or reporting nothing as if it were a fact. The journal tail, the
  controller's own, points at `docker logs`.
  Listening ports are read from the host's own table (`/proc/net/tcp`), which
  a container on the host's network sees as well.
  `scripts/check_container_answers.py` holds every program the code runs to
  such a decision.
- All mutable state lives under the `/data` volume (`CARAVAN_DATA_DIR`) — the
  controller's own config script too (`config/start-server.sh`: the models
  directory and the defaults for new cells, the `controller-config` of a settings
  file), and the scores cache (`logs/aa-scores-cache.json`);
  the System modal shows synthetic service chips (`lama-caravan (container)`,
  `agent-proxies (child)`) and hides systemd diagnostics.
- The version chip reads the commit `git archive` wrote into the release's `VERSION`:
  a release has no `.git`.
- A release carries the cell servers (`cells/`): the controller hands them to
  the scouts (`/api/cell-assets`). `scripts/check_image_contents.py` keeps every
  folder the running code reads in the release's list.
- Never start a second controller on a copy of this data: the same fleet token would let
  two controllers command the same scouts, and the same OAuth tokens would refresh each
  other out.

## One entry with keys: the OpenAI API for clients

Clients reach the caravan the way they reach OpenAI or any company's model gateway:
one address and a key each (visumap `caravan-single-entry`). A client's key reaches every
pool and every model that runs, but what is blocked for it (since 1.3.675): `GET /v1/models`
lists them by name, and a request's `model` picks one, as on OpenAI ("What a client sees"
below). The client sees a pool or a model by its name and never the providers, accounts or
cells behind it.

1. Open the entry on a free port: on the board, "Set up the entry" at the top of the
   clients column asks the public address, then the port; by API —
   `POST /api/agent-proxy-entry {"port": 23999, "publicUrl": "https://caravan-api.example.org/v1"}`.
   On a machine with a firewall, pick a port the firewall already lets in. The proxy
   starts listening within seconds; `GET /api/agent-proxy-entry` says `listening: true`.
2. Give the name: a DNS record for `caravan-api.<your domain>` and a reverse proxy
   rule to the entry's port (on the home network: visumap `lan-app-name`). Long
   model answers pass through it: set the rule's read timeout well above the
   longest answer. Streams already ask the proxy in front not to buffer them
   (`X-Accel-Buffering: no`).
3. Make a client: ＋ in the clients column — its name. The window shows the address and
   the key once; copy them. Afterwards the card shows the key's last four characters;
   "New key" replaces a lost key (the old one stops working at once). By API:
   `POST /api/consumers/create {"name": "Hermes"}`, `POST /api/consumers/key {"port": …}`.
4. The client sees every pool and every model that runs at once (the owner, 2026-10-27:
   "everything, at once"). To keep something from it, "＋ Block" on its card in Routing
   (`/routing`) opens what can be blocked: an account or a machine whole, a model, a pool —
   each tick is saved at once, and a request for what is blocked is refused (403
   `model_not_allowed`). By API: `POST /api/consumers/deny {"port": …, "deny": ["pool:<id>",
   "model:<place>", "account:<id>", "host:<hostId>"]}` — the list replaces the one it had, and
   `[]` blocks nothing.
5. Configure the client as for OpenAI: base URL `https://caravan-api.<your domain>/v1`,
   API key — its key, model — a pool's or a model's name as `/v1/models` lists it. For example:

   ```python
   from openai import OpenAI
   client = OpenAI(base_url="https://caravan-api.example.org/v1", api_key="lcv1_…")
   print([m.id for m in client.models.list()])          # the pools, then the models that run
   client.chat.completions.create(model="Standart", messages=[{"role": "user", "content": "hi"}])
   ```

   The home network's HTTPS needs the home root certificate on the client's machine
   (visumap `lan-root-ca`); for Python, `SSL_CERT_FILE`, for Node, `NODE_EXTRA_CA_CERTS`.

**Open WebUI is already there** (since 1.3.667; the owner, 2026-10-27). The caravan makes it itself
at its first start — and opens the entry on port 23999 for it when the entry is off: a client named
"Open WebUI", first in the clients column, under it a line and then the other clients. It sees what
every client sees: every pool, then every model that runs — each machine model with a running copy and
each model added to an account that can be called. One model in two places (two
accounts, two machines) is two models, with the place in brackets: `gpt-6-luna (chatgpt-subscription)`.
A model that stops leaves its list; asked for all the same, it answers 503 "is not running now". To
connect it: in Open WebUI, Admin Panel → Settings → Connections → OpenAI API → ＋, the entry's address
and the key "Give a key" on its card shows once; voice and document search take the same address and
key. It cannot be deleted and the entry stays on while it is there.

**opencode is there too** (since 1.3.673; the owner, 2026-10-27: "let it work the same way"): a second
built-in client, made the same way and standing after Open WebUI. It sees what every client sees — the
pools first, a pool whose rows go on to the next model when one is out among them. opencode does not read
the entry's model list: its models are written in its own config. Its card
gives the key once — in opencode: `/connect` → Other → `caravan` → the key — and "Copy opencode.json":
the provider `caravan` at the entry's address with every model the caravan knows that chats (a stopped one
answers 503 "is not running now"), each pool named with the models it tries in turn; put it in
`~/.config/opencode/opencode.json` and restart opencode, and copy it again when a new model appears. A
client made for opencode before is moved in from its card (`{"port": …, "kind": "opencode"}`): it keeps its
key and what is blocked for it.

A pool is listed by its name; two pools cannot share a name (the board refuses it). A
request without `stream` gets one JSON answer, with `stream: true` a stream of chunks,
whatever the provider behind the pool does. What a client is told:

| Status | `error.code` | When |
|---|---|---|
| 401 | `invalid_api_key` (or none, without a key) | no key, a key no client has, a key two clients share |
| 400 | — | the body is not a JSON object (or a form, where OpenAI's API takes a file); the body cannot be read as the request says it is sent — its length or its chunks ("The request body cannot be read: …", 1.3.505) |
| 403 | `model_not_allowed` | the pool or the model is blocked for this client in Routing |
| 403 | — | the key of a route of the old kind (below) |
| 404 | `model_not_found` | a name the caravan does not have; a key with nothing to call (nothing runs, or everything is blocked for it); `GET /v1/models/<id>` of another name |
| 404 | — | a path the entry does not serve: `Invalid URL (POST /v1/files)` |
| 429 | `rate_limit_exceeded` | every step of the pool is held by its limit; `Retry-After` says until when, and past 60 s `x-should-retry: false` stops the OpenAI client's own retries |
| 503 | `model_unavailable` | the pool has no step that can serve now for another reason (no sign-in, no step); a model the caravan knows that does not run now ("is not running now") |
| 502 | `upstream_auth`, `upstream_error` | the provider refused the caravan's sign-in, or failed; the client's key is fine |
| 503 | — | the caravan cannot read its settings now, with `Retry-After` |

The journal keeps the full reason of each refusal under the client's name.

### Routing: clients, pools, models

Routing (`/routing`) is three columns: the clients of the entry, the pools ("ID (Pools)") with
«Напрямую» on their top — the models clients call straight now —, and the models — the subscriptions with their models and the
machines with their cells. The cables show for a card pinned by a click, for a cable being drawn and while requests run. Under them a strip says the details of the card the pointer is on or a click pinned (and is
hidden while there is none): see [docs/pools.md](pools.md#in-routing).

1. "＋ New pool" makes an empty pool; its name stands in the field, chosen: type the
   name the clients will see in `/v1/models`.
2. "＋ row" (in the pool's strip: point at the pool, or pin it by a click) adds a row to the pool;
   drag from the row's dot onto a model on the right — a subscription's model or a machine's
   cell. One pool may mix both.
3. Order the rows by their ⠿: the pool tries them from the top. The next row takes the
   request when a row is at its limit (its ▲ stop level, or 429/402/401 from the provider),
   unavailable (a cell that is off or missing, a busy cell while a later row is free) or
   fails before the first byte (a connect error, a 5xx). A stream that has started is
   never switched, and a client's own error (4xx) is not tried again elsewhere.

A subscription model's ▲ stop and ▼ switch levels stand on the model — in its strip, on the account's two
bars — and hold in every pool that names it: ▲ keeps that share of the window back, ▼ sends requests
to the next rows first from that share on. A click on a row's cable cuts it after one
question; ✕ on a row removes the row, ✕ on a pool deletes the pool.

### What a client sees

A client sees every pool and every model that runs, but what is blocked for it (1.3.675; the owner,
2026-10-27: "every client we make has every model and every pool … on a client we set which models or
pools it may not have"). `GET /v1/models` lists the pools by name, then the models that run, each by its
own name — a name in two places is two models, with the place in brackets — and a request's `model`
picks one; a model under a pool's name is the pool's. A name the caravan does not have is 404 and a
request with no model is 400, as OpenAI answers them; a model it knows that does not run is 503, and
what is blocked for the client is 403 `model_not_allowed`. A model blocked for a client that one of its
pools calls is still reached through the pool: the pool works whole. No router decides for a client: a
pool's rows do — a subscription's model or a cell, in their order — and `route-policy` with `routerId` is
refused for it. At the move to this form, once at the controller's start, every client dropped its set (or
the pool or pools of the older forms) and starts with nothing blocked; the log says what each had (`entry:
every client sees every model now, the sets are gone — …`), and Routing shows it once in a window, which
offers to delete the pools that became twins of their model.

### Agents of the old kind

An agent with a port of its own (made before 1.3.466 in Routing) had its record on the
board and no way in: since 2026-11-02 (the owner: its own ports go) the proxy listens on
the entry alone and answers such a route's key 403 (`entry:not-a-consumer` in the journal).
Since 2026-11-07 a client is known by its record's id and has no number at all: the
controller's start gives every client its id once, keeps the number each one had in
`formerPorts` of `agent-proxies.json` (so that the journal's older rows stay that client's),
and retires the routes of the old kind, saying so in its log (`entry: every client is known by
its id …; routes of the old kind retired: …`). To bring one back: ＋ in the clients column
makes a client with a key of its own; set the agent's base URL to the entry and its API key to
that key. A client that cannot send a key cannot connect.

## Request-log diagnostics (API)

Every request through the proxy lands in `logs/proxy-events/<date>.jsonl` on
the controller, and `GET /api/agent-proxy-logs` serves those rows filtered —
enough to root-cause a route problem from any LAN host without ssh:

```sh
# last errors of one client, by its id — GET /api/topology `proxies[].id` (slim rows, newest first)
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?routeId=<client-id>&event=finished&errors=1&slim=1&limit=20'

# today's failed requests fleet-wide / for one route label / for one client IP
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?event=finished&errors=1&slim=1'
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?route=<label>&errors=1&slim=1'
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?client=<client-ip>&event=finished&slim=1&limit=50'

# the cheap health check: terminal counters per client {routeId, total, errors, byKind}
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?summary=1'
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?summary=1&routeId=<client-id>'
```

Params: `date` (`YYYY-MM-DD`, default — the latest log), `limit` (≤2000,
applied after the filters), `event`
(`received | queued | admitted | upstream_started | upstream_response | finished | blocked`;
several, comma-separated: `finished,blocked` is every request that ended, refusals included),
`routeId` (a client's record id; its rows written before 2026-11-07 under the number it had count as its own — a
`port` in its place is refused with 400), `route` (case-insensitive substring of the route label), `client` (the sender's exact IP),
`errors=1` (only rows carrying an error), `slim=1` (drops the per-row
`queue`/`policy` fleet snapshots, and `active` from rows written before 2026-11-02 — newer rows do not carry it; the request's own `item` is kept),
`summary=1` (no rows — per-client counters of terminal events instead, by the client's id, the entry's
refusals before a key named anyone under `entry`: `{"client-3f9a1c07": {routeId, route, total, errors, byKind: {client_disconnected: 1, …}}}`;
combines with the other filters), `since=60` (minutes — only rows newer than
now−N within the selected day; powers the per-hour ⚠ badges on route rows,
which light up from 3 failures/hour). The Request History detail popup has a
"⧉ curl" button that copies a ready-made errors query for that route.

Reading a `finished` row:

- `item.queue.queuedMs` — time spent in the admission queue (single-slot
  upstreams make this the usual suspect);
- `item.firstByteMs` — request start → first byte to the client, i.e. queue
  wait + prompt processing before the first token;
- `item.errorKind` — `client_disconnected` means the **agent** dropped the
  connection (its own timeout) while waiting; the upstream itself was fine.
  Example: this kind with `firstByteMs ≈ 33000` is
  an agent with a ~30 s client timeout that did not survive the queue.
- `item.latency` (since 1.3.437) — where the time went, in milliseconds:
  `prepMs` the time before the upstream (a machine's model's queue is in it),
  `connectMs` opening the upstream connection (`0` when a kept provider
  connection was taken, `connReused: true`), `headersMs` / `firstChunkMs` the
  upstream's answer from the request sent, `cpuMs` the processor time of the
  request. The route window's Details tab shows medians and the 90th
  percentile per client; `GET /api/agent-proxy-latency?routeId=<client-id>&range=24h`
  answers the same as JSON.

The proxy notices a vanished client at every phase and cancels the work: in
the admission queue (keep-alive write fails), and after admission via a 2 s
socket probe that tears the upstream connection down — llama.cpp then frees
the slot instead of generating into the void (error reads
`client disconnected (upstream generation aborted)`). Mid-prompt the slot is
released as soon as llama.cpp's batch loop checks the connection (typically
seconds, up to ~20 s on huge prompts).

## Known quirks

- **Every request answers 503 "cannot read its settings"** — `config/agent-proxies.json`
  or the cloud file does not read. There is no last good config in memory: the proxy reads
  what the file says, and the journal says `entry:settings-unreadable`. Restore the file
  (above).
- **A scout's cell crashed** — its card says why: 💥 with the reason, and on
  hover the last 8 lines of the crashed run's log (scout 2.6+, keys scrubbed
  by the scout); while the scout's watchdog brings it back, the ⚠ "previous
  attempt" says the same as for a cell of the controller. The whole log is on
  that machine: `<modelsBasePath>/llama-server.<port>.log`
  (`command-cell.<port>.log` for command cells), earlier runs kept aside.
- **The entry does not answer and `logs/rust-proxy.log` says `cannot bind`** — something
  else holds the entry's port. A new proxy waits 15 s for the port and then ends, and the
  watchdog starts another. Find who holds it, or move the entry on the board.
- **Whisper/command cells** show `downloading N% / loading` in the cell UI —
  that is the health endpoint reporting model download progress, not a hang.
- **UFW**: the proxy range is opened ONCE, by the operator, with one rule —
  `sudo ufw allow 23001:23999/tcp` (the range is `proxy_ports`,
  `CARAVAN_PROXY_BASE_PORT` + `CARAVAN_PROXY_PORT_SPAN`). The caravan never runs
  ufw (`scripts/check_firewall_untouched.py`), and it hands out no port there: a client has
  no port of its own (2026-11-07), the entry is the one port the proxy listens on. An entry
  on an unopened port answers locally but not from the LAN.


## Публичное зеркало

`scripts/sync-public.sh` переносит дерево в публичную копию и **готовит** коммит.
Пуш он не делает — печатает команду и останавливается: дважды приватная история
оказывалась в шаге от GitHub (посторонний remote в публичной копии, приватные
теги), и отправка осталась решением человека.

    scripts/sync-public.sh --dry-run   # всё, кроме коммита
    scripts/sync-public.sh             # коммит + напечатанная команда пуша

Отказывает, если: в публичной копии есть посторонний remote; приватное дерево не
закоммичено; лик-скан нашёл запретную строку в файле, который мог бы уехать
(смотрит отслеживаемые **и** неигнорируемые файлы — то есть всё, что взял бы
`git add -A`); гварды или тесты на публичном дереве красные.

Имена машин чинить **в приватном** дереве: rsync вернёт их обратно, если
править в копии.


### Пароль на учётные данные в файле настроек

Необязательный. Запирает **только** половину с учётками и ключами облаков —
ячейки, маршруты и топология остаются читаемыми при любом раскладе: к файлу
настроек тянутся, когда уже что-то сломано, и забытый пароль не должен утаскивать
за собой остальное.

Запирает сам караван: scrypt и AES-256-GCM (`rust/crates/net/src/sealed.rs`), ставить
ничего не надо, и поле пароля есть всегда.

Без пароля файл ведёт себя как раньше. С паролем и без него при загрузке
учётные данные пропускаются с явным сообщением — не молча.


### Инструменты переписывания

Сверка программ: `scripts/test_rust_conformance.py` (прокси),
`scripts/test_rust_admin_conformance.py` (контроллер), `scripts/test_rust_scout_conformance.py`
(скаут). Каждая задаёт программе вопросы и сравнивает ответ с тем, что записано в
`tests/frozen/`. Ответ поменяли намеренно — тот же скрипт с `--write`, и разницу покажет diff
файла в merge request. Пиши `--write` на Linux: `cpu` и скан портов машина о себе читает только там
(`LINUX_ONLY`), и на Mac `--write` запишет ответы Mac — обещание покраснеет на CI, где оно и читается.
Командные строки ячеек держат голдены: `tests/golden/`,
`rust/crates/admin/tests/golden.rs`.

`docs/why.md` хранит правила, выведенные из инцидентов; `scripts/check_why_refs.py`
следит, чтобы ссылки на код разрешались, — при переезде он и скажет, какое
правило вот-вот осиротеет.
