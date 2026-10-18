# Operations

Day-2 runbook for a production deployment. Assumes the layout from
[architecture.md](architecture.md): repo at `~/lama-caravan`,
`systemd --user` units, venv at `.venv` (stdlib only — the venv exists just to
pin the interpreter).

## Services

| Unit (systemd --user on the controller) | Runs | Notes |
|---|---|---|
| `lama-caravan.service` | `.venv/bin/python app.py` (`:7990` by default) | Admin UI + API. Restart after Python changes. |
| `lama-caravan-proxies.service` | `.venv/bin/python agent-proxies.py` | The entry for keys and the proxy ports of agents of the older kind. Restart after Python changes; route/config edits do NOT need a restart (2 s mtime watcher). |
| `llamacpp-current.service` | `~/llama.cpp/start-server.sh` (`:8080`) | Legacy single managed server. |

```sh
systemctl --user status lama-caravan.service lama-caravan-proxies.service
journalctl --user -u lama-caravan.service -n 50 --no-pager
journalctl --user -u lama-caravan-proxies.service -n 50 --no-pager
```

Firewall, once per machine: `sudo ufw allow 23001:23999/tcp` lets the proxy
range in. The caravan never touches the firewall itself.

Boot-time autostart needs linger (`loginctl enable-linger $USER`). Do not
also keep a crontab `@reboot` launcher — two launchers fight for port 7990.

## Deploy

One command wraps the whole flow — refuse-if-dirty, push, pull on the
controller, byte-compile, restart the admin (and the proxy only when the code it
runs changed — see the restart rules), then verify `/health` serves the exact
version+commit that were shipped and the proxy runs what it should (mismatch =
non-zero exit):

```sh
CARAVAN_DEPLOY_HOST=<controller-ssh-host> bash scripts/deploy.sh
# CARAVAN_DEPLOY_PATH overrides the checkout (default ~/projects/lama-caravan)
# --no-restart for static-only changes
```

The same steps by hand (source moves through git only; no scp except explicit
emergency recovery):

```sh
# locally
git commit … && git checkout main && git merge --no-ff <branch> && git push

# on the controller
cd ~/lama-caravan && git pull --ff-only
.venv/bin/python -m py_compile app.py agent-proxies.py $(find caravan -name '*.py')
.venv/bin/python scripts/test_queue_node.py           # ALL PASS expected
systemctl --user restart lama-caravan.service lama-caravan-proxies.service
```

Restart rules:

- The admin restarts on every deploy: the board is gone for a second, and no
  agent's traffic goes through it.
- The proxy restarts only when `agent-proxies.py`, `caravan/proxy/` or
  `caravan/common/` changed since the commit the proxy RUNS. The proxy writes
  that commit and its pid into its state file when it starts
  (`caravan/proxy/started.py`); the deploy reads them and decides with
  `scripts/proxy_restart.py`, which prints why either way. A dead proxy, a
  missing record or one left by another pid restarts it.
  `scripts/check_proxy_sources.py` fails when the proxy imports a module outside
  that list. By hand, restart `lama-caravan-proxies.service` only on the same
  condition — every restart drops the agents' open connections.
- `static/` only → **no restart**: `send_file` reads from disk per request and
  sends `ETag` + `Cache-Control: no-cache`, so browsers revalidate on reload.
- `var/`, config JSONs → runtime state, never deployed via git.

Post-deploy smoke:

```sh
for p in /board /api/state /api/topology /api/models /js/main.js /css/base.css /routing /hf; do   # / answers 302 -> /board
  printf '%-16s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' localhost:7990$p)"
done
curl -s -o /dev/null -w '%{http_code}\n' localhost:<entry port>/v1/models   # the entry: 401 without a key is the healthy answer
```

## Rollback

```sh
git log --oneline -10                  # find the last good commit / tag
git reset --hard <commit-or-tag>
systemctl --user restart lama-caravan.service lama-caravan-proxies.service
```

On-disk state files are kept forward/backward compatible, so rolling code
back does not normally require touching `agent-proxies.json` /
`agent-proxy-state.json`.

## Backups & recovery

| What | Where | Created |
|---|---|---|
| Router (Routing) config | `agent-proxies.json.bak-graph-<stamp>` (repo root, gitignored) | automatically on **every** admin write of `agent-proxies.json` |
| Launch configs per node | `var/server-backups/<hostId>/<gpu-model-or-CPU>/<stamp>-<name>.json` | UI snapshots (controller + clients; survive the client host) |
| Every setting, before a settings import | `var/settings-backups/<YYYYMMDD-HHMMSS-micros>-before-import.json` (`/data/settings-backups/` in the container) | automatically before every `POST /api/settings/import`: the whole file, secrets and accounts included, so it is written 0600 in a 0700 directory — importing that copy undoes the import. One file per import, never written over: two imports in one second keep both |

Restore a broken router config:

```sh
ls -t agent-proxies.json.bak-graph-* | head -3
cp agent-proxies.json.bak-graph-<stamp> agent-proxies.json   # proxy picks it up in ~2 s
```

The bak-graph files accumulate (one per write); prune with
`ls -t agent-proxies.json.bak-graph-* | tail -n +200 | xargs rm` when needed.

## Local development (macOS or any host)

### Moving the admin port

`LLAMACPP_ADMIN_PORT` is the only lever — no code change. What makes this a
fleet operation rather than a restart is that **nothing rediscovers the new
address**: each scout keeps `controllerUrl` in its own `config.json`, and a
scout that cannot reach the controller still ANSWERS the controller's polls, so
the board keeps looking healthy while heartbeats, model pulls and cell-asset
syncs are all dead.

Order that survives it, with no shim needed — a scout tolerates an unreachable
controller and reconnects by itself:

1. Open the new port in the firewall FIRST. On the controller the inference
   range (default 22001–22999; legacy installs 8001–8099) is already open; anything outside it needs its own rule, and
   a forgotten rule is the one failure that looks like the app being broken.
2. Re-point every scout while the controller is still on the old port —
   `POST http://<client>:8092/api/controller-url` with `{"url", "token"}`. It
   rewrites config.json and applies live; no restart, no ssh.
3. Change `Environment=LLAMACPP_ADMIN_PORT=` in the unit, `daemon-reload`,
   restart. Heartbeats resume within one interval.
4. Verify each client's `lastSeen` on the board before touching anything else.
5. Sweep the leftovers: bookmarks, and any
   `config.json.bak-*` that would resurrect the old address on a restore.

Run the admin against scratch state so you don't touch `~/.local/state` or
spam autobackups into the working tree:

```sh
export LLAMACPP_ADMIN_PORT=7991
export LLAMA_ADMIN_STATE=/tmp/caravan-dev/admin.json
export AGENT_PROXY_CONFIG_FILE=/tmp/caravan-dev/agent-proxies.json   # cp the real one for data
export AGENT_PROXY_STATE_FILE=/tmp/caravan-dev/proxy-state.json
export TOKEN_HISTORY_FILE=/tmp/caravan-dev/token-history.json
export CLOUD_PROVIDERS_FILE=/tmp/caravan-dev/cloud-providers.json
export LLAMA_MONITOR_HISTORY=/tmp/caravan-dev/monitor-history.json
export LLAMA_INCIDENT_LOG=/tmp/caravan-dev/incidents.jsonl
python3 app.py
```

Hardware probes (`nvidia-smi`, `systemctl`) degrade gracefully — `run()`
never raises, so the server works on a laptop with empty panels. The monitor
sampler also runs on macOS: memory comes from `vm_stat`/`sysctl`, processes
from `ps -r`; per-core CPU% stays 0 (no `/proc`), loadavg is real.

Shorthand for the same isolation: `CARAVAN_DATA_DIR=/tmp/caravan-dev python3
app.py` rebases every mutable default (state/, config/, logs/, secrets/,
models/, server-backups/, settings-backups/) under one directory; the individual
env vars above still win when set.

Quick checks while developing:

```sh
python3 -m py_compile app.py agent-proxies.py $(find caravan -name '*.py')
python3 scripts/test_queue_node.py
node --check <(cat static/js/<module>.js)        # ES-module syntax (or copy to .mjs)
```

## Docker (controller-only)

**Evaluation / GPU-less-controller mode — native systemd stays the primary
deployment.** Neither runs cells: they run on machines with a scout.
`docker compose up -d --build` runs the admin + proxy in one container (see
the README quick start). What changes inside (`CARAVAN_CONTAINER=1`):

- Two settings are required, and the container refuses to start without
  them (exit code 2, the reason on stderr): `TZ`, the controller's time zone —
  every schedule runs by it, and a container would otherwise run in UTC
  silently — and `LLAMA_TOPOLOGY_SERVER_IP`, the address agents and scouts
  reach it at. `docker-compose.yml` asks for both; the image carries the zone
  data (`tzdata`).
- Behind a reverse proxy, with the controller listening on loopback only (a NAS),
  `LLAMA_TOPOLOGY_SERVER_URL` names the controller as the fleet reaches it, e.g.
  `https://caravan.example.org`: "Add scout" hands every scout that name instead
  of the address and port, which answer nobody else there. The scout's machine must
  trust the certificate (on the home network, visumap `lan-root-ca`).
- To find the scouts of the network without typing addresses, press 🔍 Find on the Add
  scout row: it scans the networks typed there (`10.0.30.0/24`; empty — the
  controller's own /24) for caravan-scout on its port and lists each one: free (with
  Connect), already on the board, or held by another caravan. A container on the host
  network (`network_mode: host`, the NAS) reaches the other networks of the house as the
  machine does; a scout's machine must let the port in through its firewall.
- A locked-down container runs as is: `security_opt: [no-new-privileges:true]`,
  `cap_drop: [ALL]`, `read_only: true` with `tmpfs: [/tmp]`. The controller writes only
  under `/data`, each file through a temp file beside it (`caravan/common/fsio.py`), and
  binds ports above 1024, so it needs no capability. The NAS compose runs it so: then a
  setuid program inside (`su`, `passwd`, `mount`) gives no rights, and nothing can be
  planted outside `/data`.
- No systemd: the proxy is a **supervised child** of the admin
  (`caravan/admin/proxy_supervisor.py`) — respawned by a watchdog on crash,
  respawned in place when a routes/cabling save asks for a restart. Its output
  goes to `/data/logs/proxy.log`; `docker logs` carries the admin.
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
- The version chip reads `CARAVAN_GIT_HEAD` (baked at build) because the
  image ships without `.git`.
- The image carries the cell servers (`cells/`): the controller hands them to
  the scouts (`/api/cell-assets`). `scripts/check_image_contents.py` keeps every
  folder the running code reads in the image's COPY list.

## One entry with keys: the OpenAI API for clients

Clients reach the caravan the way they reach OpenAI or any company's model gateway:
one address and a key each (visumap `caravan-single-entry`). A client's key calls one
pool — the one a cable in Routing leads it to (since 1.3.486) — and every request of
the key goes there, whatever `model` it names. The client sees the pool by its name and
never the providers, accounts or cells behind it.

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
4. Give the client its models: in Routing (`/routing`), make a set (＋ New set) and drag
   from the dot at its foot onto each pool it should offer — a chat pool, a speech pool, an
   embeddings pool; then drag from the dot on the client's card onto the set. Until then its
   requests are refused (404 `model_not_found`). A click on a cable takes it away. By API:
   `POST /api/sets/create {"name": "Chat"}`, `POST /api/sets/add-pool {"id": "<set id>", "pool": "<pool id>"}`,
   `POST /api/consumers/set {"port": …, "set": "<set id>"}`; `"set": ""` takes the cable away.
5. Configure the client as for OpenAI: base URL `https://caravan-api.<your domain>/v1`,
   API key — its key, model — a pool's name of its set as the board shows it. For example:

   ```python
   from openai import OpenAI
   client = OpenAI(base_url="https://caravan-api.example.org/v1", api_key="lcv1_…")
   print([m.id for m in client.models.list()])          # the pools of this key's set
   client.chat.completions.create(model="Standart", messages=[{"role": "user", "content": "hi"}])
   ```

   The home network's HTTPS needs the home root certificate on the client's machine
   (visumap `lan-root-ca`); for Python, `SSL_CERT_FILE`, for Node, `NODE_EXTRA_CA_CERTS`.

A pool is listed by its name; two pools cannot share a name (the board refuses it). A
request without `stream` gets one JSON answer, with `stream: true` a stream of chunks,
whatever the provider behind the pool does. What a client is told:

| Status | `error.code` | When |
|---|---|---|
| 401 | `invalid_api_key` (or none, without a key) | no key, a key no client has, a key two clients share |
| 400 | — | the body is not a JSON object (or a form, where OpenAI's API takes a file); the body cannot be read as the request says it is sent — its length or its chunks ("The request body cannot be read: …", 1.3.505) |
| 404 | `model_not_found` | the key has no pool yet (no cable); `GET /v1/models/<id>` of another name |
| 404 | — | a path the entry does not serve: `Invalid URL (POST /v1/files)` |
| 429 | `rate_limit_exceeded` | every step of the pool is held by its limit; `Retry-After` says until when, and past 60 s `x-should-retry: false` stops the OpenAI client's own retries |
| 503 | `model_unavailable` | the pool has no step that can serve now for another reason (no sign-in, no step) |
| 502 | `upstream_auth`, `upstream_error` | the provider refused the caravan's sign-in, or failed; the client's key is fine |

The journal keeps the full reason of each refusal under the client's name.

### Routing: clients, pools, models

Routing (`/routing`) is four columns joined by cables: the clients of the entry, their sets of
models ("ID sets"), the pools ("ID (Pools)"), and the models — the subscriptions with their models and the machines with their
cells. Under them a strip says the details of the card the pointer is on or a click pinned (and is
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
4. Drag from a client's dot onto a set, and from the set's "＋ model" row onto the pool.

A subscription model's ▲ stop and ▼ switch levels stand on the model — in its strip, on the account's two
bars — and hold in every pool that names it: ▲ keeps that share of the window back, ▼ sends requests
to the next rows first from that share on. A click on any cable cuts it after one
question; ✕ on a row removes the row, ✕ on a pool deletes the pool.

### A client and its set

A client has one set, or none while no cable reaches it (the owner, 2026-10-12: "only one
cable goes on from a client", and a set between it and the pools). The set's pools are the
client's models: `GET /v1/models` lists them, a request's `model` picks one, a name the set
has not is 404 and a request with no model is 400, as OpenAI answers them. One set may serve
several clients. No router decides for a client: a pool's rows do — a subscription's model or
a cell, in their order — and `route-policy` with `routerId` is refused for it. A client cabled
to one pool (1.3.486–1.3.496) is cabled to a set of that pool once at start, shared by the
clients of that pool, and the controller says so in its log (`entry: clients cabled to sets: …`);
a client made before 1.3.486 first gets the first pool it might call (`entry: clients cabled to
one pool: …`).

### Agents of the old kind

An agent with a port of its own (made before 1.3.466 in Routing) can reach the
entry with its port's key; its request then goes through its port's router graph, as
before, and its `model` chooses nothing. To move one: in Routing's clients panel,
"Give a key" on its row (the key is made and the port closes in the same step), then
set the agent's base URL to the entry and its API key to the key. An agent whose port
had a key already shows "Close port" instead; ↺ reopens a closed port (it still demands
the key). By API: `POST /api/agent-proxies/route-key {"port": …}` and
`POST /api/agent-proxies/route-policy {"port": …, "portClosed": true}` — both refused
while the entry is off.

## Request-log diagnostics (API)

Every request through the proxy lands in `logs/proxy-events/<date>.jsonl` on
the controller, and `GET /api/agent-proxy-logs` serves those rows filtered —
enough to root-cause a route problem from any LAN host without ssh:

```sh
# last errors on one route, by its proxy port (slim rows, newest first)
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?port=8117&event=finished&errors=1&slim=1&limit=20'

# today's failed requests fleet-wide / for one route label / for one client IP
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?event=finished&errors=1&slim=1'
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?route=<label>&errors=1&slim=1'
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?client=<client-ip>&event=finished&slim=1&limit=50'

# the cheap health check: per-port terminal counters {total, errors, byKind}
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?summary=1'
curl -s 'http://<controller-ip>:7990/api/agent-proxy-logs?summary=1&port=8117'
```

Params: `date` (`YYYY-MM-DD`, default — the latest log), `limit` (≤2000,
applied after the filters), `event`
(`received | queued | admitted | upstream_started | upstream_response | finished | blocked`;
several, comma-separated: `finished,blocked` is every request that ended, refusals included),
`port` (the route's number — a port of the older kind, or a client of the entry's record, which never listens), `route`
(case-insensitive substring of the route label), `client` (exact IP),
`errors=1` (only rows carrying an error), `slim=1` (drops the per-row
`active`/`queue`/`policy` fleet snapshots; the request's own `item` is kept),
`summary=1` (no rows — per-port counters of terminal events instead:
`{"8117": {port, route, total, errors, byKind: {client_disconnected: 1, …}}}`;
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
  Example: the classic `[Errno 32] Broken pipe` with `firstByteMs ≈ 33000` is
  an agent with a ~30 s client timeout that did not survive the queue.
- `item.latency` (since 1.3.437) — where the time went, in milliseconds:
  `prepMs` the caravan's own work before the upstream (without the queue),
  `connectMs` opening the upstream connection (`0` when a kept provider
  connection was taken, `connReused: true`), `headersMs` / `firstChunkMs` the
  upstream's answer from the request sent, `cpuMs` the processor time of the
  request. The route window's Details tab shows medians and the 90th
  percentile per port; `GET /api/agent-proxy-latency?port=<port>&range=24h`
  answers the same as JSON.

### Load test of the proxy

`scripts/bench_proxy.py` measures what a machine's processor carries before
the caravan moves onto it: a fake provider, the real proxy in a process of its
own, and N parallel token streams through it and straight to the provider.
Nothing of the running caravan is touched — everything lives in a temporary
directory on free ports.

```sh
python3 scripts/bench_proxy.py --kind subscription --streams 1,8,32 --requests 32 --events 200 --gap-ms 10
```

Per level of parallel streams it prints the stream's time straight and
through the proxy (the difference is what the proxy adds), the first event,
the journal's `prepMs` and `cpuMs`, the proxy process's processor time per
request and the kept connections taken. `--kind subscription` translates a
Responses stream (the subscription's path, the heaviest), `openai` relays a
chat-completions stream as it is, `cell` goes to a local server without a
pool. CI runs `--quick`.

The proxy notices a vanished client at every phase and cancels the work: in
the admission queue (keep-alive write fails), and after admission via a 2 s
socket probe that tears the upstream connection down — llama.cpp then frees
the slot instead of generating into the void (error reads
`client disconnected (upstream generation aborted)`). Mid-prompt the slot is
released as soon as llama.cpp's batch loop checks the connection (typically
seconds, up to ~20 s on huge prompts).

## Known quirks

- **`BrokenPipeError` in the admin journal** — a browser/agent dropped a
  polling request mid-response. Pre-existing noise (hundreds/day), harmless.
- **Route edits look "stuck"** — check the proxy journal: the listener watcher
  logs every rebind; a malformed `agent-proxies.json` keeps the last good
  config in memory.
- **A scout's cell crashed** — its card says why: 💥 with the reason, and on
  hover the last 8 lines of the crashed run's log (scout 2.6+, keys scrubbed
  by the scout); while the scout's watchdog brings it back, the ⚠ "previous
  attempt" says the same as for a cell of the controller. The whole log is on
  that machine: `<modelsBasePath>/llama-server.<port>.log`
  (`command-cell.<port>.log` for command cells), earlier runs kept aside.
- **Ghost proxy processes** — if ports stay bound after a unit stop, look for
  an orphaned `python agent-proxies.py` (historic gotcha: a manually started
  copy fighting the unit) and kill it before restarting the service.
- **Whisper/command cells** show `downloading N% / loading` in the cell UI —
  that is the health endpoint reporting model download progress, not a hang.
- **UFW**: the proxy range is opened ONCE, by the operator, with one rule —
  `sudo ufw allow 23001:23999/tcp` (the range is `PROXY_PORTS`,
  `CARAVAN_PROXY_BASE_PORT` + `CARAVAN_PROXY_PORT_SPAN`). The caravan never runs
  ufw (`scripts/check_firewall_untouched.py`): it hands out ports only inside
  the range and refuses a new port outside it. An old port outside it (8022)
  keeps its own rule; delete that rule by hand when the port goes. A route on
  an unopened port answers locally but not from the LAN.


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

Каравану для этого нужен пакет `cryptography`, а проект намеренно живёт на одной
стандартной библиотеке. Поэтому возможность **объявляется**: где пакета нет,
поле пароля не показывается, и панель говорит почему. Включить:

    .venv/bin/pip install cryptography
    systemctl --user restart lama-caravan.service

Без пароля файл ведёт себя как раньше. С паролем и без него при загрузке
учётные данные пропускаются с явным сообщением — не молча.


### Инструменты переписывания

`scripts/capture_golden.py` снимает поведение (34 эталона, 120 флагов,
135/135 полей конфига), `scripts/test_golden.py` сверяет с ним — он первый в
`deploy.sh` и главный тест на всё переписывание.

`scripts/diff_behaviour.py` гоняет старую и новую реализацию рядом на тех же
33 фикстурах:

    scripts/diff_behaviour.py --old caravan.admin.runners:effective_command \
                              --new caravan.domain.runner:command_for

Падение одной из сторон показывается как расхождение (`ok → raised`), а не как
поломка прогона: реализация, которая бросает там, где прежняя отвечала, изменила
поведение ровно так же, как та, что вернула другое.

`docs/why.md` хранит правила, выведенные из инцидентов; `check_why_refs.py`
следит, чтобы ссылки на код разрешались, — при переезде он и скажет, какое
правило вот-вот осиротеет.
