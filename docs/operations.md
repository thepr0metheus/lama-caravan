# Operations

Day-2 runbook for a production deployment. Assumes the layout from
[architecture.md](architecture.md): repo at `~/lama-caravan`,
`systemd --user` units, venv at `.venv` (stdlib only — the venv exists just to
pin the interpreter).

## Services

| Unit (systemd --user on the controller) | Runs | Notes |
|---|---|---|
| `lama-caravan.service` | `.venv/bin/python app.py` (`:7990` by default) | Admin UI + API. Restart after Python changes. |
| `lama-caravan-proxies.service` | `.venv/bin/python agent-proxies.py` | Per-agent proxy ports. Restart after Python changes; route/config edits do NOT need a restart (2 s mtime watcher). |
| `lama-cell@<port>.service` | `var/server-cells/<port>/start.sh` | One llama-server cell per port. Managed from the UI (reserve/start/stop). |
| `llamacpp-current.service` | `~/llama.cpp/start-server.sh` (`:8080`) | Legacy single managed server. |

```sh
systemctl --user status lama-caravan.service lama-caravan-proxies.service
journalctl --user -u lama-caravan.service -n 50 --no-pager
journalctl --user -u lama-caravan-proxies.service -n 50 --no-pager
```

Boot-time autostart needs linger (`loginctl enable-linger $USER`). Do not
also keep a crontab `@reboot` launcher — two launchers fight for port 7990.

## Deploy

One command wraps the whole flow — refuse-if-dirty, push, pull on the
controller, byte-compile, restart both services, then verify `/health` serves
the exact version+commit that were shipped (mismatch = non-zero exit):

```sh
CARAVAN_DEPLOY_HOST=<controller-ssh-host> bash scripts/deploy.sh
# CARAVAN_DEPLOY_PATH overrides the checkout (default ~/projects/lama-caravan)
# --no-restart for static-only changes; notifies CI via notify-ci.sh when configured
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

- `caravan/` or launcher changes → restart both services.
- `static/` only → **no restart**: `send_file` reads from disk per request and
  sends `ETag` + `Cache-Control: no-cache`, so browsers revalidate on reload.
- `var/`, config JSONs → runtime state, never deployed via git.

Post-deploy smoke:

```sh
for p in /board /api/state /api/topology /api/models /js/main.js /css/base.css /kanban /hf; do   # / answers 302 -> /board
  printf '%-16s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' localhost:7990$p)"
done
curl -s -o /dev/null -w '%{http_code}\n' localhost:8101/v1/models   # any live route port
```

### Telling an external test suite

The E2E suite lives in its own repository and runs against a DEPLOYMENT rather
than a commit, so nothing tells it a release happened. Left to a schedule, the
answer to "did that break anything" can be a day late.

```sh
bash scripts/notify-ci.sh          # last step, after the remote restart
```

**Run it from the machine you deploy FROM, not from the controller.** The
controller sits on the fleet subnet and may have no route to wherever CI lives —
here it does not, and the call simply times out. The deploy workstation pushed
the commit and therefore has the same checkout that was just pulled, so the
version and commit it reports are the ones now running.

That direction is worth checking once before wiring it up, because a missing
route looks exactly like a wrong token from the outside:

```sh
curl -s -o /dev/null -w '%{http_code}\n' --max-time 6 <ci-host>/
```

It reads `CARAVAN_CI_DISPATCH_URL` and `CARAVAN_CI_TOKEN` from the environment
and **exits silently when either is unset**, so a deployment with no CI attached
is unaffected. It never fails a deploy either: an unreachable CI host prints one
line and returns 0. The tests report on a release; they do not gate it.

The credential belongs in the deploy shell, never in this repository. That is
also why the script names no vendor and no address — those live with the token,
and it works with any CI that starts a run from an authenticated POST.

It sends the version read from `caravan.__version__` and the short commit, which
is what makes the far side able to catch the deploy that reports success and
leaves the old process running: `/health` already answers with both, and a
mismatch between what was shipped and what is serving has no other symptom —
every test passes, and the fix simply is not there.

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
| Router/kanban config | `agent-proxies.json.bak-graph-<stamp>` (repo root, gitignored) | automatically on **every** admin write of `agent-proxies.json` |
| Launch configs per node | `var/server-backups/<hostId>/<gpu-model-or-CPU>/<stamp>-<name>.json` | UI snapshots (controller + clients; survive the client host) |
| Legacy start script | `~/llama.cpp/start-server.sh.bak.<stamp>` | before every config save |

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
5. Sweep the leftovers: OpenClaw config-manager URLs, bookmarks, and any
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
export LLAMA_CLIENT_LABELS_FILE=/tmp/caravan-dev/client-labels.json
export LLAMA_INCIDENT_LOG=/tmp/caravan-dev/incidents.jsonl
python3 app.py
```

Hardware probes (`nvidia-smi`, `systemctl`) degrade gracefully — `run()`
never raises, so the server works on a laptop with empty panels. The monitor
sampler also runs on macOS: memory comes from `vm_stat`/`sysctl`, processes
from `ps -r`; per-core CPU% stays 0 (no `/proc`), loadavg is real.

Shorthand for the same isolation: `CARAVAN_DATA_DIR=/tmp/caravan-dev python3
app.py` rebases every mutable default (state/, config/, logs/, secrets/,
models/, server-cells/, server-backups/) under one directory; the individual
env vars above still win when set.

Quick checks while developing:

```sh
python3 -m py_compile app.py agent-proxies.py $(find caravan -name '*.py')
python3 scripts/test_queue_node.py
node --check <(cat static/js/<module>.js)        # ES-module syntax (or copy to .mjs)
```

## Docker (controller-only)

**Evaluation / GPU-less-controller mode — native systemd stays the primary
deployment** (only it can host `lama-cell@` cells on the controller box).
`docker compose up -d --build` runs the admin + proxy in one container (see
the README quick start). What changes inside (`CARAVAN_CONTAINER=1`):

- No systemd: the proxy is a **supervised child** of the admin
  (`caravan/admin/proxy_supervisor.py`) — respawned by a watchdog on crash,
  respawned in place when a routes/cabling save asks for a restart. Its output
  goes to `/data/logs/proxy.log`; `docker logs` carries the admin.
- Local `lama-cell@` cells, the legacy single-server unit and "Repair user
  service" are disabled with a clear 400 — models run on caravan-scout hosts
  (attach the Docker host itself with scout if it has the GPU).
- All mutable state lives under the `/data` volume (`CARAVAN_DATA_DIR`);
  the System modal shows synthetic service chips (`lama-caravan (container)`,
  `agent-proxies (child)`) and hides systemd diagnostics.
- The version chip reads `CARAVAN_GIT_HEAD` (baked at build) because the
  image ships without `.git`.

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
(`received | queued | admitted | upstream_started | upstream_response | finished | blocked`),
`port` (proxy route port — the stable per-agent identifier), `route`
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
- **Client cell crashed** — the root cause is on the client, in
  `~/llama-model-cache/llama-server.log` (the route-agent rotates it).
- **Ghost proxy processes** — if ports stay bound after a unit stop, look for
  an orphaned `python agent-proxies.py` (historic gotcha: a manually started
  copy fighting the unit) and kill it before restarting the service.
- **Whisper/command cells** show `downloading N% / loading` in the cell UI —
  that is the health endpoint reporting model download progress, not a hang.
- **UFW**: new proxy ports must be allowed (`8101:8199` range is open); a
  route on an unopened port answers locally but not from the LAN.
