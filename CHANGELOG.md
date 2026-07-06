# Changelog

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
