# LAMA CARAVAN

Repository/service slug: `lama-caravan`.

Local control plane for LAMA CARAVAN: controller topology, proxy routing, and
per-host `llama.cpp` server cells.

The app is intentionally dependency-light: it uses Python standard library
HTTP handling and static HTML/CSS/JS.

## Documentation

| Doc | Covers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Components, data flow, the file contract between the daemons, deployment topology |
| [docs/backend-admin.md](docs/backend-admin.md) | `caravan/admin/` module reference (the admin server) |
| [docs/backend-proxy.md](docs/backend-proxy.md) | `caravan/proxy/` module reference + the request lifecycle |
| [docs/frontend.md](docs/frontend.md) | `static/js/` ES-module reference, state model, render/polling pipeline |
| [docs/http-api.md](docs/http-api.md) | Every HTTP endpoint of the admin and the proxy surface |
| [docs/operations.md](docs/operations.md) | Runbook: services, deploy, rollback, backups, local dev, quirks |

Legacy single-server mode edits the marked config block in:

```text
~/llama.cpp/start-server.sh
```

The long-term server-cell path uses generated launch artifacts instead:

```text
<project>/var/server-cells/<port>/cell.json
<project>/var/server-cells/<port>/start.sh
```

The structured cell config is the source of truth; `start.sh` is the runnable
artifact used by `lama-cell@<port>.service`.

## Runtime Layout

On the controller the admin service is `lama-caravan.service`; the legacy single
managed llama.cpp server remains `llamacpp-current.service` while server cells
move toward per-port launch scripts.

```text
~/.config/systemd/user/llamacpp-current.service
  -> ~/llama.cpp/start-server.sh
     -> ~/llama.cpp/build/bin/llama-server

~/.config/systemd/user/lama-caravan.service
  -> ~/lama-caravan/.venv/bin/python app.py

~/.config/systemd/user/lama-cell@8001.service
  -> ~/lama-caravan/var/server-cells/8001/start.sh
```

For boot-time autostart without waiting for an interactive SSH or
desktop session, enable linger for your user and install the user
services. Do not also keep a crontab `@reboot` launcher for this admin: two
launchers will fight for port `8090`.

```text
loginctl enable-linger $USER
```

Default URL:

```text
http://<controller-ip>:8090
```

## Code Layout

`app.py` and `agent-proxies.py` are thin launchers (systemd entry points and
the load target for `scripts/test_queue_node.py`); the code lives in the
`caravan/` package:

```text
caravan/
├── common/   shared stdlib helpers: errors, procs, fsio (atomic writes),
│             fetch, jsonx, ttl_cache
├── admin/    the admin server (app.py): paths, state, config_builder, launch,
│             models, systemd_ctl, llama_metrics, hf, downloads, benchmarks,
│             terminal, router_dsl, proxies_config, cloud, token_history,
│             proxy_stats, monitoring, openclaw, oauth, cloud_api, pricing,
│             telemetry, server_cells, fleet_clients, topology, proxy_ops,
│             backups, status, cell_ops, routes (HTTP tables + Handler), main
└── proxy/    the proxy daemon (agent-proxies.py): paths, runtime (shared
              mutable state), config, events, capacity, graph (router DAG),
              state, cloud_auth, translate, summarize, queue_admission,
              handler, listeners, main
```

Import layering is strict and cycle-free: `common` ← `paths` ← `state` ←
domain modules ← aggregators (`topology`, `status`) ← ops/`routes` ← `main`.
Rebindable module globals live in the same module as every function that
rebinds them.

## Deployment Rule

Source changes are deployed through git only:

```text
local commit -> push to your remote -> git pull on the controller/client hosts
```

Do not deploy project code by direct `scp` or hand-copying files, except for an
explicit emergency recovery. Generated runtime files under `var/` are local host
state and are not the source deployment path.

## Features

- Show `llamacpp-current.service` status, PID, uptime, and command line.
- Read the `BEGIN LLAMA CONFIG` block from `start-server.sh`.
- Edit model, mmproj, context, port, threads, batch, cache, CPU/GPU placement,
  RoPE, server HTTP, vision, reasoning, and custom chat template flags.
- Dropdown model and mmproj lists scanned from `~/llama.cpp/models`.
- Save with timestamped backup.
- Save only or save and restart.
- Revert to the latest backup.
- Show recent journal logs.
- Show `/v1/models`, `/props`, and `/metrics` summary.
- Show CPU, RAM, NVIDIA GPU memory, PCIe link, utilization, temperature, and power.
- Estimate runtime memory and warn when it is close to or over VRAM/RAM limits.
- Explain what each parameter controls.
- Show local llama.cpp version/build metadata and guarded update/build actions.
- Switch between light, dark, and black LLM-focused themes.
- Show Gemma 4 MTP/speculative decoding state in the Runtime panel.
- Reserve globally numbered server cells starting at port `8001`.
- Generate per-cell `cell.json` and `start.sh` launch artifacts.
- Start/stop the controller cells via `systemd --user` template units
  (`lama-cell@<port>.service`).
- Keep reserved/stopped cells visible as stable proxy/router upstream targets.

## Gemma 4 MTP Text Boost

Gemma 4 can use a small `gemma4_assistant` GGUF as an MTP/speculative draft
head. On the controller this is configured as a text-generation boost for the existing
Gemma 4 model route:

```text
MODEL_FILE="gemma-4-31b-it/q4-k-m/google_gemma-4-31B-it-Q4_K_M.gguf"
SPEC_DRAFT_MODEL_FILE="gemma-4-31b-it/assistant/gemma-4-31B-it-assistant.Q4_K_M.gguf"
SPEC_TYPE="mtp"
SPEC_DRAFT_BLOCK_SIZE="3"
```

When these fields are set and `MODEL_FILE` contains `gemma-4`, the launcher uses
the AtomicChat `atomic-llama-cpp-turboquant` runtime and starts `llama-server`
with:

```text
--mtp-head <assistant.gguf> --spec-type mtp --draft-block-size 3
```

For non-Gemma-4 models the draft setting is ignored, so Qwen and other models
continue to use the normal llama.cpp runtime. If `MMPROJ_FILE` is set, the
server can run vision, but MTP does not accelerate those multimodal slots.

The Config panel has two Gemma 4 mode buttons:

- `Gemma Text MTP` clears `MMPROJ_FILE`, keeps the assistant draft head enabled,
  saves the config, and restarts `llamacpp-current.service`.
- `Gemma Vision` selects the Gemma 4 projector, keeps the same model route,
  saves the config, and restarts `llamacpp-current.service`.

Agents keep using the same `http://<controller-ip>:8080/v1` endpoint. Text-only
Gemma 4 requests get the MTP boost automatically while the text mode is active;
image requests need the vision mode. The Runtime panel shows `Speculative: MTP
text boost` for the boosted mode and `Speculative: MTP paused by vision` when
the projector is enabled. The llama.cpp response timings also expose draft
counters such as `draft_n` and `draft_n_accepted`, and logs include
`statistics mtp`.

## Safety Model

The app only rewrites lines between:

```bash
# BEGIN LLAMA CONFIG
# END LLAMA CONFIG
```

Before saving, it creates:

```text
~/llama.cpp/start-server.sh.bak.YYYYMMDD-HHMMSS
```

It does not delete models or old profiles.

## API

- `GET /api/state` - dashboard state, parsed config, models, health, logs.
- `GET /api/topology` - topology view data: the controller host, GPUs, llama servers,
  proxy routes, registered clients, and desired assignments.
- `POST /api/config` - save config. Body: `{ "config": {...}, "restart": false }`.
- `POST /api/action` - service action. Body: `{ "action": "start|stop|restart" }`.
- `POST /api/revert` - restore the latest `start-server.sh.bak.*`.
- `POST /api/topology/client-heartbeat` - receive heartbeat from
  `caravan-scout` (formerly `llm-easy-route-agent`) on client hosts.
- `POST /api/topology/assignments` - store desired `agent -> proxy` routes and
  push them to the registered client route agent when available.

## Topology GUI

The web UI has two views:

- `Classic` - the existing single-server editor and monitor.
- `Topology` - a first read-only topology map for clients, proxy ports, the
  current llama-server instance, and GPUs.

Topology state is stored in the admin state file:

```text
~/.local/state/llamacpp-easy-admin/admin.json
```

Client hosts run `caravan-scout` and heartbeat into:

```text
POST http://<controller-ip>:8090/api/topology/client-heartbeat
```

The initial graph model is:

```text
client host -> local agent -> proxy route -> llama-server instance -> GPU(s)
```

Assignments are owned by the admin server. Client route agents act as local
executors and report applied state.

In the `Topology` view, set the connection role to `Primary` or `Fallback`, then
drag a client agent card onto a proxy port card. The UI stores the desired
assignment in the admin state and immediately calls the registered
`caravan-scout` on that client host. Holding Shift while dropping forces
the dropped route to `Fallback`.

## Install llama.cpp

Run the install script on the target host (requires NVIDIA GPU + CUDA toolkit):

```sh
cd ~/lama-caravan
bash scripts/install-llama.sh
```

This will:
- Fetch the latest llama.cpp release tag from GitHub
- Clone or update `~/llama.cpp`
- Build `llama-server` with CUDA (auto-detects GPU architectures)
- Restart any running `lama-cell@*.service` units

Optional flags:

```sh
# Pin a specific release
bash scripts/install-llama.sh --llama-tag b9101

# Force rebuild even if the binary already exists
bash scripts/install-llama.sh --force

# Skip service restart
bash scripts/install-llama.sh --no-restart
```

To update llama.cpp to the latest release on an already-built host:

```sh
bash scripts/install-llama.sh --force
```

### Blackwell (RTX 5090 / `sm_120`) workaround

On Blackwell GPUs with CUDA 13.x, `llama-server` crashed on inference with
`SOFT_MAX failed: CUDA error: invalid argument` and entered a systemd restart
loop. The root cause was a `cudaDeviceProp` struct-layout mismatch that made
`prop.sharedMemPerBlockOptin` read a garbage ~4 GiB value, which the driver then
rejected when it was passed to `cudaFuncSetAttribute`.

`install-llama.sh` detects `sm_120` GPUs and **automatically applies the fix** — a
minimal single-file patch that queries `cudaDeviceGetAttribute` instead of the
bad struct field. No code change is needed in `caravan-scout` —
they don't run CUDA code; each Blackwell host just needs `llama.cpp` rebuilt via
this script.

The patch (`ggml/src/ggml-cuda/ggml-cuda.cu`, in `ggml_cuda_init()`):

```diff
-        info.devices[id].smpbo = prop.sharedMemPerBlockOptin;
         info.devices[id].cc = 100*prop.major + 10*prop.minor;
+        // Use cudaDeviceGetAttribute instead of prop.sharedMemPerBlockOptin to avoid
+        // struct layout mismatches between CUDA toolkit versions.
+        {
+            int smpbo_val = 0;
+            if (cudaDeviceGetAttribute(&smpbo_val, cudaDevAttrMaxSharedMemoryPerBlockOptin, id) == cudaSuccess && smpbo_val > 0) {
+                info.devices[id].smpbo = (size_t) smpbo_val;
+            } else {
+                info.devices[id].smpbo = prop.sharedMemPerBlockOptin;
+            }
+        }
```

**Quant caveat:** `IQ4_NL` (and likely other `IQ*` quants) produce garbage output
on the Blackwell GPU backend — the `sm_120` dequant kernel is broken (confirmed:
works on CPU, garbles on GPU regardless of build flags). This is independent of
the crash fix. **Use a K-quant** (`Q4_K_M`, `Q5_K_XL`, `Q6_K`) on Blackwell hosts.

Full write-up: [`docs/postmortem-blackwell-soft-max-crash.md`](docs/postmortem-blackwell-soft-max-crash.md).

## Install On the controller

Copy this directory to:

```text
~/lama-caravan
```

Install or update the launcher template if needed:

```sh
cp scripts/start-server.sh ~/llama.cpp/start-server.sh
chmod +x ~/llama.cpp/start-server.sh
```

Create the venv:

```sh
cd ~/lama-caravan
python3 -m venv .venv
.venv/bin/python -m py_compile app.py agent-proxies.py $(find caravan -name '*.py')
.venv/bin/python scripts/test_queue_node.py
```

Install the user services (the admin UI and the per-agent proxy daemon):

```sh
mkdir -p ~/.config/systemd/user
cp systemd/lama-caravan.service systemd/lama-caravan-proxies.service systemd/lama-cell@.service ~/.config/systemd/user/
loginctl enable-linger $USER
systemctl --user daemon-reload
systemctl --user enable --now lama-caravan.service lama-caravan-proxies.service
```

Make sure no legacy crontab launcher is still present:

```sh
crontab -l | grep -E 'llamacpp-easy-admin|lama-caravan'
```

The command above should print nothing. If it shows an `@reboot` loop for this
admin, remove that line before relying on the systemd user service.

Check:

```sh
systemctl --user status lama-caravan.service lama-caravan-proxies.service --no-pager -l
curl -fsS http://127.0.0.1:8090/api/state
```

## Notes

This service is intended for the trusted local network. It currently has no
authentication. If it is ever exposed outside the LAN, put it behind a reverse
proxy with authentication or add Basic Auth.
