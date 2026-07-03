# Operations

Day-2 runbook for a production deployment. Assumes the layout from
[architecture.md](architecture.md): repo at `~/lama-caravan`,
`systemd --user` units, venv at `.venv` (stdlib only — the venv exists just to
pin the interpreter).

## Services

| Unit (systemd --user on the controller) | Runs | Notes |
|---|---|---|
| `lama-caravan.service` | `.venv/bin/python app.py` (`:8090`) | Admin UI + API. Restart after Python changes. |
| `lama-caravan-proxies.service` | `.venv/bin/python agent-proxies.py` | Per-agent proxy ports. Restart after Python changes; route/config edits do NOT need a restart (2 s mtime watcher). |
| `lama-cell@<port>.service` | `var/server-cells/<port>/start.sh` | One llama-server cell per port. Managed from the UI (reserve/start/stop). |
| `llamacpp-current.service` | `~/llama.cpp/start-server.sh` (`:8080`) | Legacy single managed server. |

```sh
systemctl --user status lama-caravan.service lama-caravan-proxies.service
journalctl --user -u lama-caravan.service -n 50 --no-pager
journalctl --user -u lama-caravan-proxies.service -n 50 --no-pager
```

Boot-time autostart needs linger (`loginctl enable-linger $USER`). Do not
also keep a crontab `@reboot` launcher — two launchers fight for port 8090.

## Deploy

Source moves through git only (no scp except explicit emergency recovery):

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
for p in / /api/state /api/topology /api/models /js/main.js /css/base.css /kanban /hf; do
  printf '%-16s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' localhost:8090$p)"
done
curl -s -o /dev/null -w '%{http_code}\n' localhost:8101/v1/models   # any live route port
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

Run the admin against scratch state so you don't touch `~/.local/state` or
spam autobackups into the working tree:

```sh
export LLAMACPP_ADMIN_PORT=8099
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

Quick checks while developing:

```sh
python3 -m py_compile app.py agent-proxies.py $(find caravan -name '*.py')
python3 scripts/test_queue_node.py
node --check <(cat static/js/<module>.js)        # ES-module syntax (or copy to .mjs)
```

## Request-log diagnostics (API)

Every request through the proxy lands in `logs/proxy-events/<date>.jsonl` on
the controller, and `GET /api/agent-proxy-logs` serves those rows filtered —
enough to root-cause a route problem from any LAN host without ssh:

```sh
# last errors on one route, by its proxy port (slim rows, newest first)
curl -s 'http://<controller-ip>:8090/api/agent-proxy-logs?port=8117&event=finished&errors=1&slim=1&limit=20'

# today's failed requests fleet-wide / for one route label / for one client IP
curl -s 'http://<controller-ip>:8090/api/agent-proxy-logs?event=finished&errors=1&slim=1'
curl -s 'http://<controller-ip>:8090/api/agent-proxy-logs?route=<label>&errors=1&slim=1'
curl -s 'http://<controller-ip>:8090/api/agent-proxy-logs?client=<client-ip>&event=finished&slim=1&limit=50'

# the cheap health check: per-port terminal counters {total, errors, byKind}
curl -s 'http://<controller-ip>:8090/api/agent-proxy-logs?summary=1'
curl -s 'http://<controller-ip>:8090/api/agent-proxy-logs?summary=1&port=8117'
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
