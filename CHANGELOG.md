# Changelog

## 1.3.11 — 2026-07-07

- Route Activity now colours each request by where it actually went,
  not by the entry port's static type. A client wired to a local
  ("llama") port that a schedule / router graph forwards to a cloud
  model was painted as "running (local)" — it now shows the cloud
  colours, and a genuinely local request stays local. The realized
  upstream type and provider id also ride through to the diagnostics
  API (`?slim=1`), so the request log tells you the true destination.

## 1.3.10 — 2026-07-07

- The board lane is called "Model Servers" now — it has hosted vLLM
  and faster-whisper cells alongside llama.cpp for a while. The
  heading, its (?) tip and the client-GPU "available for …" line are
  properly localized in all 20 languages (they were English-only).

## 1.3.9 — 2026-07-06

- The cloud model-list toggle is a full-width "Show all N models ⌄" /
  "Hide models ⌃" row at the bottom of the provider card (20
  languages) — the tiny header count chip it replaces was easy to
  miss.

## 1.3.8 — 2026-07-06

- The idle board stops redrawing itself: the daily-stats fetch after
  every topology poll triggered an unconditional full render (measured
  9 rebuilds per 10 polls with nothing happening) — it now renders
  only when the counts actually changed. Focused fields already defer
  rebuilds since 1.3.7; together the board is finally still under the
  pointer.
- Cloud provider model lists open on CLICK of the count chip (⌄/⌃)
  instead of hover/focus-within — no more lists springing open when
  the pointer crosses a card and snapping shut on re-renders.
- Provider-card controls (model rows, edit/fetch, bridge mint/copy/
  delete, flyout toggle) moved to a delegated listener on the lane
  container: usage-fetch re-renders replaced the buttons without
  re-binding, leaving them dead once the per-tick rebuilds stopped.
- Bridge ports answer GET /health themselves ({"status":"ok"}) —
  forwarding it to a cloud API returned 405 and painted the route's
  activity strip red on every probe from an external consumer.

## 1.3.7 — 2026-07-06

- Cell notes: every cell card can carry a free-form user comment —
  drill into the cell (the model block) and edit NOTE in the detail
  modal; the card shows it under the body (💬, two lines max, stored
  on the slot, 20 languages).
- Bridge minting now looks like the Reserve-cell control: a dashed
  ghost button with the actual next port ("＋ Bridge port :8015").
- One fleet-wide port pool, enforced both ways: cells now refuse ports
  held by proxy routes (reserve guess + backend check include routes),
  so a Reserve-cell can no longer collide with a bridge or agent port.
- Copy buttons in the cell detail modal use the same plain-http
  clipboard fallback as the bridge rows.
- The board's poll-tick rebuild no longer fights the user: a focused
  select/text field defers the rebuild (the deferred render lands on
  focusout), and the bridge model choice is kept in UI state — picking
  a model in a dropdown that used to redraw every ~3 s now works.

## 1.3.6 — 2026-07-06

- Bridge ports: one-click OpenAI-compatible entry points for EXTERNAL
  consumers (e.g. a voice-translation app), minted on the Cloud Providers card — pick a
  model block, get the next free port relayed to that cloud model with
  the account's credentials (streaming, OAuth refresh, spend metering
  and request logs included; /v1/models answers the pinned model, so
  clients label themselves). Route kind="service": router-free by
  construction, invisible to the kanban/agent machinery (OpenClaw sync,
  ↑☁ eligibility, auto-attach all skip it); the port registry shows a
  "bridge" badge with the pinned model instead of a router select.
  Full-rebuild saves preserve the new fields; 20 languages.

## 1.3.5 — 2026-07-06

- Docker as the entry door: a controller-only image (admin UI + proxy
  router, stdlib-only, ~150 MB) with a `docker compose up -d --build`
  quick start. `CARAVAN_CONTAINER=1` swaps systemd for an in-process
  proxy supervisor (crash watchdog + on-demand respawn, log in
  /data/logs/proxy.log); `CARAVAN_DATA_DIR` rebases all mutable state
  under one volume — also handy for local dev. Local cells, the legacy
  unit and repair answer with a clear 400 — models run on caravan-scout
  hosts; the board swaps the reserve-cell card for a scout hint on the
  containerized controller (20 languages), the System modal shows
  container service chips, the version chip reads the commit baked at
  build. Native systemd deployment unchanged and remains primary.

## 1.3.4 — 2026-07-06

- Runner tabs carry a (?) with the full trade-off story (benefits plus
  honest downsides), and every field on the static panels (custom /
  vLLM / whisper) got the same (?) tip the llama fields have — texts
  from the existing fieldHelp translations, 20 languages.
- One model picker everywhere: whisper sizes appear on client cell
  forms too (their rows never dim — the controller can't see a client
  cache); the dedicated WHISPER_MODEL select is hidden on all forms.
- Client cells fixed for command-path runners: Apply no longer dies
  with "Select a model" on whisper/vLLM cells, and Start no longer
  demands a COMMAND from a whisper cell — the full client whisper
  cycle (configure → scout start → /health → card) verified live.

## 1.3.3 — 2026-07-06

- Running vLLM cells show live engine metrics on the card: ▶ active
  (+ ⏳ queued) requests and the rolling generation t/s, scraped from
  vLLM's own Prometheus /metrics — the same treatment llama cells get.
  Their token speeds also feed the standard promptTps/genTps fields.

## 1.3.2 — 2026-07-06

- /models manages EVERYTHING under the models root: whisper HF-cache
  dirs and safetensors checkpoint folders join the list as single
  entries (size, age, kind) with honest "who uses it" — vLLM cells
  reference their VLLM_MODEL path, whisper cells their size — and can
  be deleted when unreferenced (folder-wise, same guards as gguf).
- The whisper size picker marks sizes already on disk with ✓
  (state.whisperOnDisk).

## 1.3.1 — 2026-07-06

- whisper models live under the SAME root as everything else: the cell
  command points HUGGINGFACE_HUB_CACHE at <models root>/whisper (the
  scout's model cache on clients) instead of ~/.cache/huggingface —
  no more model files scattered outside the configured models folder.

## 1.3.0 — 2026-07-06

- whisper is a first-class runner (Э4): a 🎙 tab in the cell editor with
  a WHISPER_MODEL size picker (tiny…large-v3-turbo) instead of a raw
  command line. Compiles to `run_whisper.sh "$PORT" <size>` through the
  command-cell machinery — health on /health, same preview pane, same
  lifecycle on controller and clients (the agent installer provisions
  the ~/wsr venv). Cards show 🎙 whisper + the size; language stays a
  per-request API field (whisper_server.py takes only port+model).
  20 languages.

## 1.2.9 — 2026-07-05

- VRAM gate before vLLM cell starts: when the GPU cannot host the
  requested reservation (utilization × total), the start fails
  instantly with a human message naming the cells holding VRAM —
  instead of a minute-long systemd crash loop. Single-GPU cells only;
  silent when nvidia-smi is unavailable.
- NVFP4/MXFP4 are recognised quants now: downloads land in
  <model>/<author>/NVFP4/ (not default/) and cards badge them.

## 1.2.8 — 2026-07-05

- Cell cards: the runner chip (🦙 llama.cpp / ⚡ vLLM / 🛠 command) moved
  INTO the model-name row, replacing the generic chip icon — the engine
  reads at a glance, and the badge row lost the duplicate.
- The form's VLLM_MODEL is now derived from the picked model for gguf
  too (file path), not only for safetensors artifacts — the field is
  hand-edited only for HF repo ids with no local copy.
- Picking a GGUF while the vLLM tab is active shows an explicit note:
  GGUF via vLLM is experimental, llama.cpp is the native engine.

## 1.2.7 — 2026-07-05

- Fleet runnability gate in the cell form: picking an artifact whose
  format has a CUDA compute requirement (NVFP4 ≥10, FP8 ≥8.9) renders a
  per-host line under the runner tabs — controller ✓ · client ✗ — from the
  fleet GPU map and a marketing-name→compute table. 20 languages.
- vLLM cells no longer land in the "cells on CPU" section: the GPU
  binder now matches every PID in the cell unit's cgroup (vLLM holds
  the GPU in a forked worker, not the unit's MainPID).
- /hf repo list: an artifact-format chip (GGUF / ⚡NVFP4 / MLX …) in
  each row's badges, derived from HF tags, the loaded file panel or the
  repo name.

## 1.2.6 — 2026-07-05

- Failed cells say WHEN they died: the card's "Start failed …" line now
  carries the crash age (· 45s / 12m / 5h / 3d, from the unit's
  ExecMainExitTimestamp) — an hours-old failure no longer reads as "it
  just fell again".
- Saving a new config over a failed cell clears the unit's failed state
  (systemctl reset-failed): the red card belonged to a config that no
  longer exists.

## 1.2.5 — 2026-07-05

- Cell cards state their engine: every llama card carries a 🦙 llama.cpp
  chip, vLLM cards use the same body layout as llama ones — model icon +
  model NAME (derived from the local artifact or the VLLM_MODEL path),
  then ⚡ vLLM / 🎛 format / ❤ /v1/models / 🪟 max-len chips.
- Reopening a vLLM cell puts its artifact back into the MODEL_FILE
  picker (the config stores only VLLM_MODEL), so the form always shows
  which model the cell serves and the runner tabs gate correctly.

## 1.2.4 — 2026-07-05

- Form model picker knows safetensors artifacts: downloaded checkpoints
  (<model>/<author>/<FORMAT>/ in the models tree) appear in the MODEL
  combobox with a ⚡format badge. Picking one flips the form to the vLLM
  runner (llama.cpp greys out — needs GGUF), prefills VLLM_MODEL with
  the local path and the alias follows the model folder name.
  Controller cells only for now — the scout syncs gguf, not folders.

## 1.2.3 — 2026-07-05

- /hf model tree: opening a repo now shows its quantized descendants
  and — when the repo is itself a quant — the base model's other quants
  (GGUF/NVFP4/AWQ/MLX… badges, downloads/likes), one click from repo to
  repo. Data comes from the HF `base_model:quantized:` tag filter, the
  same source as the model-tree panel on huggingface.co. 20 languages.

## 1.2.2 — 2026-07-05

- vLLM runner hardening after the live NVFP4 campaign: the bootstrap
  installs ninja and puts the venv on PATH, caps compile parallelism
  (MAX_JOBS=4 — parallel cicc workers once peaked at 57.6G RAM and froze
  the controller) and sets the expandable-segments allocator; the cell
  unit now carries MemoryHigh/MemoryMax/MemorySwapMax so a runaway cell
  is oom-killed instead of the host.
- Starting cells show WHERE they are (provisioning venv / downloading /
  loading weights / compiling kernels / CUDA graphs / starting API) —
  classified from the unit journal, right on the card.
- Runner tabs got icons (🦙 ⚡ 🛠️ — our own, no third-party logos) and
  the benefits line lost its stray 78px gap.
- /hf multi-format step 1: safetensors repos render as ONE downloadable
  artifact (format from the repo name or config.json) landing in the
  same models tree as gguf quants; every other repo file is visible in
  a grey collapsed list.

## 1.2.1 — 2026-07-04

- vLLM runner (stage 2): a third tab in the cell editor. Fields
  (VLLM_MODEL, MAX_MODEL_LEN, GPU_MEMORY_UTILIZATION, QUANTIZATION,
  DTYPE, TENSOR_PARALLEL) compile into the command-cell machinery at
  launch — the controller renders a self-provisioning start.sh
  (~/vllm-venv bootstraps on first start) and clients receive one
  bootstrap+serve line, so the scout needs no changes. Health rides
  /v1/models; the OpenAI-compatible port plugs into routers as-is.
  All 20 languages covered.

## 1.2.0 — 2026-07-04

- Multi-engine groundwork (stage 1): the cell editor is now
  "Model -> Runner -> Params" — the model artifact comes first and the
  old Cell type toggle became runner tabs rendered from a backend
  registry (llama.cpp / Custom command today, vLLM next), with an
  advantages line and per-format availability. Configs carry RUNNER
  alongside legacy CELL_KIND, so every old backup, snapshot and the
  scout keep working untouched. Command-cell fields finally have "?"
  help tips; the config tour step teaches the new flow. All 20
  languages covered.

## 1.1.6 — 2026-07-04

- i18n: full 20-language coverage. A repo-wide audit wired ~90 more
  hardcoded strings into t()/data-i18n (board tooltips, modal headings,
  Route Activity legend and titles, validation toasts, empty states, the
  /hf page via its own light dict) and translated the whole 241-key
  backlog — everything that previously existed only in en+ru — into the
  remaining 18 languages (~4800 strings), plus 4 missing fieldHelp
  entries and a lost ru key. New CI guard (check_messages_i18n.py) fails
  the build if any language misses a key from now on.
- Config editor: the manual EXTRA_ARGS box is full-width again — the Ф2
  CSS split had cut a comment across two files and silently voided the
  rule.

## 1.1.5 — 2026-07-04

- i18n: hardcoded Russian strings now follow the selected language — the
  Apply/Cancel buttons of both llama editors, the Route Activity legend,
  the default-output confirm, agent-remove tooltips, cell-action errors,
  the freed-ports toast and the port-picker tooltip (new keys in en+ru,
  other languages fall back to English).

## 1.1.4 — 2026-07-03

- Start scene v2: a night launch — crescent moon, 10 frames, the rocket
  climbs out of the frame and a fresh one rolls onto the pad (static
  scenery moved to a separate sky layer so the slide-in moves only the
  rocket).
- Saved configs: the list now shows the name you typed (it was saved but
  never displayed); Cyrillic and other unicode names no longer collapse
  to an empty string and fail with 400.

## 1.1.3 — 2026-07-03

- Fix: the classic form's model-change handler did not pass aliasFollow
  (the 1.1.2 edit silently missed the wrapper), so picking a model there
  kept the old alias. All three forms now rewrite it.

## 1.1.2 — 2026-07-03

- ALIAS now always follows an explicit model selection, replacing whatever
  was in the field; saved aliases are still kept on form open and when
  loading a backup (no model change happened).

## 1.1.1 — 2026-07-03

- Config editor: ALIAS auto-fills from the model file name when the field is
  empty (shards/extension stripped, lowercased); a custom alias is never
  overwritten and re-selecting a model refreshes only auto-filled values.
- Confirm dialogs: the start scene is now a rocket launch — the llama presses
  the button, the rocket ignites, lifts off and leaves smoke on the pad.

## 1.1.0 — 2026-07-03

- Sign-in: SQLite accounts (admin/viewer), sessions, fleet token for scouts,
  first-account wizard on /login with all 20 UI languages; account chip in
  the header.
- /system page (replaces the System modal): Controller / llama.cpp /
  Security / Diagnostics tabs, hero stats, deep links.
- Cell schedules: start/stop windows per cell (edge-driven, overnight-aware).
- Models disk GC: list unused GGUFs, free space from the UI.
- Prometheus /metrics endpoint (clients, cells, GPU, routes).
- Onboarding tours translated into all 20 UI languages (+ CI guard);
  the /hf tour language picker offers the full list.
- Seamless scout deploys: running cells are adopted, not killed.
- Cell start reliability: the lama-cell@ unit template renders from the
  actual checkout path; start failures are classified (out-of-memory /
  exec / model / port / crash) and shown on the card, including the
  previous attempt while systemd retries; retries stop after 3 failures
  in 10 minutes instead of reloading a 20 GB model forever.
- TRAFFIC (route activity) on client cards; ⚠ failed-requests badge;
  request-log diagnostics API.

## 1.0.0 — 2026-07-03

First public release.

- Fleet topology board: controller, clients (via caravan-scout), llama server
  cells, cloud providers; live traffic on the cables.
- Per-agent proxy ports with queueing/priorities and visual routing pipelines
  (kanban): schedule, weighted, round-robin, failover, request-size fork.
- Remote server cells on client hosts: reserve → configure (memory estimate,
  exact command preview, backups) → start; command cells for non-llama
  workloads (whisper, embeddings).
- HuggingFace GGUF browser with multi-part downloads.
- Usage & spend statistics, request history, incident badges, GPU/CPU/token
  monitors, System panel (llama.cpp build, controller services, models disk).
- Onboarding tours (? Tour) with an interface-language picker; EN/RU + 18
  more UI languages.
- Stdlib-only Python backend (admin + routing proxy), native ES-module
  frontend, no build step.
