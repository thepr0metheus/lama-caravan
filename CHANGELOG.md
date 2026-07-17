# Changelog

## Unreleased

- The whisper cell honors an optional `task=translate` multipart field
  (whisper's built-in any→English translation) — a voice-translation app's
  speak-for-me and interview-trainer flows use it for single-hop RU speech
  → EN text. Servers that don't know the field keep ignoring it.

## 1.3.44 — 2026-07-17

- Dead agents got a visible home: a red dashed strip at the bottom of the
  kanban CLIENTS block lists assignments whose agent the host no longer
  reports (agent · client, the ports they still hold) with a ✕ that deletes
  the assignment and frees the ports. Rendered only when there is something
  to clean; the delete lost its UI when the registry modal was retired.
- Orphaned agents are part of the board's structure fingerprint, so the
  strip appears and disappears live on the main board's workspace.

## 1.3.43 — 2026-07-17

- Parked cells (stopped / reserved / error) show a dashed ≈VRAM badge next
  to the model name: the weights-on-disk size (multi-part GGUFs sum their
  parts; client cells resolve by basename in the controller models tree).
  The tooltip notes that real VRAM adds context/KV overhead on top.
- The dead Proxy-ports registry modal is gone along with its unreachable
  wiring — both of its openers had died in earlier redesigns; the ✎ on the
  kanban client port rows is the living entry to the route form.

## 1.3.42 — 2026-07-16

- A re-pointed queue cable keeps its admit/spill role: dragging the endpoint
  moves the role pointer onto the replacement edge and prunes stale pointers
  — no more phantom roleless cables left behind.
- Kanban canvas interactions (pan, zoom, node/port/cable drag, the ✕ delete)
  survive background re-renders: cable grab and ✕ moved to document-level
  delegation, and a rebind observer rewires the rest whenever a re-render
  rebuilds the canvas DOM.

## 1.3.41 — 2026-07-16

- The device chip and the memory figure split: the chip in the state row
  now carries only WHERE (⚡ GPU0), while HOW MUCH lives in a bold green
  badge next to the model name — live VRAM held by the cell's processes,
  multi-GPU sums up with the per-GPU split in the tooltip. CPU cells and
  stopped cells (which hold nothing) show no memory badge.

## 1.3.40 — 2026-07-16

- Reassign a parked cell's port: the RESERVED :port lifecycle step turns
  into a button on stopped cells and opens a fleet-wide port picker —
  a grid of the shared pool where occupied tiles are colored by owner
  (cell / agent port / bridge, owner in the tooltip) and free ones are
  one click away. Server-side the slot record, its config PORT, the
  controller start.sh artifacts and every router reference to
  srv:<old> (graph cables, rules, embeddings/audio outputs) follow the
  cell to the new number.
- The Custom command tab got the same design language as the llama.cpp
  form: preset chips instead of a dropdown, the Device pin as three
  Compute-target-style tiles (auto probe / GPU / CPU — CPU glows blue
  to match the cards), and the HTTP health-check as a switch (off =
  plain TCP port probe).
- README leads with the backronym; the GitHub repo description carries
  it too.

## 1.3.39 — 2026-07-16

- Every non-reserved cell card now wears a device chip: running cells
  show the FACT (⚡ GPU0 2.5G / 🧮 CPU from unit pids vs nvidia
  compute-apps), stopped cells show the CONFIGURED target — ⚡ GPU for
  GPU-natured runners (llama with offload, vLLM, whisper) and pins,
  🧮 CPU for CPU pins, ⚙ auto for bare custom commands that probe VRAM
  at start. Pins are read from COMMAND and ENV.
- CPU cells (running on CPU or stopped with a CPU pin) wear a blue card
  accent — stripe, background, lifecycle steps, chip — instead of
  green/amber, so the GPU-vs-CPU split reads at a glance.
- The cell form grew a Device selector (auto / GPU pin / CPU pin) for
  command, whisper and vLLM cells — pure sugar over ENV
  (TTS_DEVICE=cpu|cuda; empty CUDA_VISIBLE_DEVICES as the hard,
  runner-agnostic CPU pin), so both launch renderers — the controller
  and caravan-scout on client hosts — work unchanged. Hand-typed ENV
  pins sync back into the selector. Live-verified on both a controller
  and a client cell: CPU pin loads the model on CPU with the GPU idle,
  GPU pin takes CUDA.
- The /models page tree sorts every level largest-first (was top-level
  only); provider-card model lists and kanban checklists sort by price.

## 1.3.38 — 2026-07-16

- "＋ App port" at the bottom of the kanban CLIENTS block: mints a
  router-routed entry port for an EXTERNAL APP (a UI, a voice tool, …) —
  traffic flows through the default router's graph/queue exactly like
  agent traffic, but the port carries its own generated data-plane API
  key (URL + key land in the clipboard; the key stays readable in the
  route form's Advanced section). Apps no longer borrow agent keys —
  born from a live incident: a container on a fleet host hammered an
  agent's route with a stale shared key, 1.5k 401s/day.

## 1.3.37 — 2026-07-16

- Provider cards grew a "Cloud request errors (24h)" block: data-plane
  failures of actually ROUTED traffic (completions that came back
  4xx/5xx or died — e.g. a provider answering 400 to every call on a
  retired model), aggregated per account/model/code from the proxy event
  logs. The runtime twin of the API-issues breaker panel, which covers
  only our helper calls (model lists, usage, costs).
- The autostart button on cell cards no longer wears the dead-chrome
  "muted" look while OFF: off-but-clickable is a toggle state, so it
  renders raised like delete, with a green hover hint (genuinely
  unavailable — client cells, busy — stays muted+disabled).

## 1.3.36 — 2026-07-16

Model-block lifecycle hardening — everything the live delete/re-add drill
uncovered, in one release:

- **Delete preflight.** The delete-block confirm now lists everything that
  references the block (bridge ports, queue admit/spill roles, router rules,
  graph cables) via GET /api/cloud-blocks/refs — deleting stops being a
  silent wire-cutter. An unlisted (provider-retired) model is called out
  right in the dialog.
- **Wiring survives deletion.** Graph cables to cloud outputs are now
  preserved like local srv: ones when the target vanishes (block deleted) —
  the cable doesn't render, the walker falls back to legacy rules, and the
  moment a block with the same id returns, cables AND queue roles reconnect
  themselves. rules.default gets the same treatment via a dormantDefault
  stash (an explicit user pick clears it).
- **Honest bridge /health.** A bridge whose providerId dangles or whose
  account has no stored credential answers 503 {status:"degraded", reason}
  instead of {"ok"} — external consumers see the truth without sending a
  paid completion.
- **Model catalog on the server.** Per-account model lists are cached for
  1h (state/model-catalog.json), refreshed in a background thread, and
  blocks whose model left the provider's list carry `unlisted: true` in
  topology — the red ⚠ marks now show on the kanban outputs checklist,
  output rows, bridge rows and dropdowns, the block modal options, and the
  queue node warns when its main/overflow target is dead or delisted.
- **Endpoint circuit breaker.** Upstream helper calls (model lists,
  subscription usage, costs, openrouter limits, npm version probe) that fail
  3× in a row are disabled with exponential backoff (6h→48h) and reported in
  an "API issues" panel on the provider card with a retry button — we stop
  hammering a broken endpoint, and nothing fails silently anymore.
- **codex client_version self-updates.** The chatgpt.com model-list version
  is now env override (CARAVAN_CODEX_CLIENT_VERSION) → the newest of npm
  "@openai/codex" latest (cached a day) and a built-in floor (0.160.0). The
  floor matters: gating references versions ABOVE the published CLI (5.6
  unlocks at 0.150.0 while npm latest was 0.144.5). The effective version
  and its source are shown on the subscription card.
- **Cloud model lists sort by price**, expensive → cheap (checklists, output
  rows, provider-card flyout); unknown-price models sink to the bottom.
- **Block modal:** edit view shows the read-only Block ID; changing an
  existing block's model asks for confirmation (that silent rewire is
  exactly how terra once became a second sol); adding a duplicate model
  warns; new blocks get an "Expose as router output" checkbox (on by
  default) so exposing no longer needs a trip to the kanban checklist.
- **"Fetch models" skips non-chat junk** (tts/whisper/embeddings/moderation/
  image/video/audio/realtime/legacy bases) — no more 60 unusable blocks on
  an API account; the toast reports how many were skipped.

## 1.3.35 — 2026-07-16

- Model blocks the provider no longer serves are painted red in the
  provider card's model list, with a "⚠ not listed by provider" tag —
  the fetched model list is treated as the provider's current truth
  (no marks while a list hasn't loaded, so a failed fetch can't
  false-flag anything).
- The chatgpt.com model-list client_version pin is bumped 0.132.0 →
  0.160.0: the old pin hid the gpt-5.6 family, which would have made
  the new stale-marks lie (working 5.6 blocks would show as retired).
  Verified upstream: retired models (gpt-5.2, gpt-5.3-codex) are absent
  from the list at EVERY client_version and also refuse completions
  ("model is not supported when using Codex with a ChatGPT account"),
  so red = really dead, not just delisted.

## 1.3.34 — 2026-07-16

- The Cloud Providers card renders the "＋ Add Model Block" button it
  always had a handler for — until now a model block could only appear
  via "Fetch models" or auto-create, never be added by hand.
- The Add/Edit Model Block dialog grew a free-text "Custom model ID"
  field that overrides the dropdown on save. Closes the trap where a
  model retired from the pinned client_version list became impossible
  to re-add the moment its last block was deleted (gpt-5.2 today).
- Verified the full block delete → re-add cycle on a live fleet: bridges
  and graph cables referencing `cb:<blockId>` reconnect by themselves
  when the re-added model yields the same slug id. Two sharp edges
  remain (documented, not yet fixed): a routers write that happens while
  a referenced block is missing prunes the graph edge for good
  (normalize_router_graph drops dangling refs — the queue's spill role
  had to be re-wired by hand), and a re-added model whose slug is
  already taken by another account's block gets a "-2" suffixed id, so
  external references don't reattach.

## 1.3.33 — 2026-07-12

- The via-proxy spend rows show each model's $/1M rate next to the name
  (case-insensitive lookup — spend rows carry display-cased names).
- The Edit Model Block dialog's model dropdown is no longer limited to
  what chatgpt.com returns for the pinned client_version: it unions the
  live endpoint list with every model the account's blocks already use,
  so the 5.6 family (and anything added manually) is always pickable.

## 1.3.32 — 2026-07-11

- Cloud output rows on the kanban servers block (and the Outputs panel)
  show the model's $in/$out per-1M price tag right next to the name;
  ":free" OpenRouter models get a FREE chip.
- Manual price overrides (📊 Statistics → per-model $/1M) now overlay the
  LiteLLM table in the DISPLAYED pricing map too, not only in spend
  accounting — a hand-entered price shows up on the cards and the kanban.
  Entered the official gpt-5.6 rates (sol $5/$30, terra $2.5/$15,
  luna $1/$6) as overrides until LiteLLM's table catches up.

## 1.3.31 — 2026-07-11

- Canvas nodes refuse to overlap: on drop, a node that lands on another
  (or on the clients/servers blocks) is pushed out along the smallest
  axis, cascading until clear — neighbours stay put. A 48px minimum
  spacing is enforced too, so blocks can't be parked flush against
  each other (port dots overhang and cables need runway).
- Hovering a cable dims every other cable (and the junction dots) to a
  ghost, so the highlighted path is easy to trace through a dense
  harness; the dimming survives the live redraw ticks.

## 1.3.30 — 2026-07-11

- Port dots on the canvas servers/inputs blocks sit centered on their
  rows again: the sync code placed the dot's TOP edge at the row center
  (while zeroing the class's self-centering margin), so every dot — and
  its cable end — hung 8px low. Applies to output rows, folded group
  headers and the inputs block.

## 1.3.29 — 2026-07-11

- The cable-delete ✕ on the kanban canvas is actually reachable now: it
  sits on the wire itself (midpoint measured along the polyline, not
  between the endpoints, where it used to float in empty space), and an
  invisible 18px-wide hover corridor follows the cable, so moving the
  mouse from wire to ✕ no longer makes it vanish. Dragging anywhere in
  the corridor re-points the cable too. Tooltip translated (20 langs).
- The servers block on the canvas got foldable groups: every local host
  and every cloud provider header has a ▾/▸ fold; folded rows hide and
  their cables converge on the group header instead of disappearing.
  The provider header click still toggles the model checklist as before.

## 1.3.28 — 2026-07-11

- Subscription usage cleanup after OpenAI dropped the 5h Codex window:
  limits are labeled by window duration (the weekly window landed in the
  "primary" slot and rendered as a baffling "168h limit" — now "Weekly
  limit"), the two speculative fallback endpoints (codex/usage,
  agentic_usage) are gone, and the Costs API probe fires only for real
  api.openai.com accounts — Ollama/Anthropic/generic cards no longer show
  a pointless "spend: HTTP 404" (the local proxy spend-meter covers them).

## 1.3.27 — 2026-07-11

- The command-cell editor's aside gains a Script panel: when COMMAND (or
  the whisper runner's baked-in exec line) points at a .sh/.bash/.py
  file, the controller reads it (home-directory only, 64 KB cap) and
  shows a scrollable read-only preview — "bash ~/run_tts.sh" is no
  longer a black box. Client-cell scripts show a note until
  caravan-scout grows a matching endpoint. The aside titles (New
  command / Current command / History) are now translated too.

## 1.3.26 — 2026-07-11

- The Kanban Board card on the main board is compact again: instead of
  one row + cable anchor per output (29 rows on a busy fleet) it shows
  the default route, a "{n} local · {m} cloud" tally and ONE shared
  output anchor — every router→server/cloud cable now fans out of that
  single point, keeping per-cable activity colors. The full per-output
  list still lives inside the kanban workspace.
- Voice-clone TTS cells are provisioned like whisper now: `tts/` ships
  `tts_server.py` + `run_tts.sh` (XTTS-v2 / F5-TTS / CosyVoice2 behind one
  HTTP contract — POST `/v1/audio/speech-clone`, health with load phases),
  `scripts/install-tts.sh` drops them into `$HOME` and installs the system
  ffmpeg torchcodec needs (engine venvs self-install on first cell start,
  or pre-warm with `--prewarm "xtts f5 cosyvoice"`), and the Command form
  gains three `tts · …` presets next to the whisper one.

## 1.3.25 — 2026-07-11

- Picking the "Custom command" runner now dims the MODEL_FILE block
  (picker, badges, HF link): a command cell launches COMMAND with $PORT
  only, so the selected model is not part of its config — the UI no
  longer suggests otherwise. whisper and vLLM keep the picker active
  (they consume it).

## 1.3.24 — 2026-07-11

- The router canvas speaks all 20 languages: node tooltips, drag hints,
  palette (node names are translated labels now), the queue node's live
  block (waiting/idle/switch-in countdowns), empty states and the canvas
  footer — 31 cv* keys plus a codebase-wide sweep that keyed ~130 more
  hardcoded strings across cloud provider cards, history filters, charts,
  usage stats, topology modals/nodes/proxies, favorites, autostart
  buttons, "updated" stamp and "+ Add Cloud Provider". Port names
  (small/default/embeddings/main/spill) and OAuth field names stay latin
  by design.
- Switching the language re-translates the OPEN cell editor in place:
  tab captions, the composed title, Apply/Start/Restart button, runner
  picker with its trade-off tooltips, compute-target cards, on/off toggle
  labels, weekday chips and the command placeholder — driven by a new
  caravan:langchange event dispatched from applyLanguage(); unsaved
  edits survive.
- check_messages_i18n.py now rejects UNTRANSLATED content, not just
  missing keys: english-phrase detection for non-latin locales (after
  stripping genuine identifiers) and verbatim en-copy detection for
  latin ones. A future tooltip added without real translations fails CI.

## 1.3.23 — 2026-07-10

- Switching the UI language now updates the OPEN cell-config editor
  fully. Section headers (Cache/Vision/Reasoning/…), field (?) tooltips,
  the help lines and the LOCAL badge were built once with t()/fieldHelp()
  at render time and were NOT tagged data-i18n, so they froze at the
  language active when the modal was first built (e.g. Japanese tooltips
  under a later-selected Urdu UI). They now carry data-fieldhelp /
  data-fieldhelp-text / data-i18n-tip / data-i18n markers that
  applyLanguage() refreshes in place — no input is lost. This was the
  real cause of the earlier "tooltips in the wrong language" report
  (not browser cache). Known separate gap: the router-canvas node
  tooltips are still hardcoded English.

## 1.3.22 — 2026-07-10

- Russian field-help tooltips are properly translated: 39 of the 95
  cell-config (?) tips were Russian grammar with English noun phrases
  left inline ("размер batch для prompt processing", "built-in chat
  template", "continuous batching"…). They are now clean Russian,
  keeping only genuine identifiers latin (flag names, GGUF, JSON,
  /props, RoPE, VRAM). Audited all 20 languages: the other non-Latin
  locales were already clean (only the ML terms "flash attention" and
  "repo id" remain by design). Tooltips render solely from i18n
  fieldHelp — a pure-English tooltip at a non-English UI means a stale
  cached bundle; hard-refresh (Cmd/Ctrl+Shift+R) after a deploy.

## 1.3.21 — 2026-07-10

- The cell config panel gains the b9947 switches as proper fields with
  (?) help in all 20 languages, laid out into sections: CONTEXT_SHIFT
  (Inference), KV_UNIFIED (Hardware), and on the Server tab two NEW
  sections — Cache (CACHE_RAM, CACHE_IDLE_SLOTS alongside the existing
  prompt-cache toggles) and Network & TLS (API_KEY, SSL_CERT_FILE,
  SSL_KEY_FILE) — plus SLEEP_IDLE_SECONDS (idle VRAM release),
  REASONING_PRESERVE (Reasoning), MMPROJ_AUTO (Vision). All wired both
  ways through the EXTRA_ARGS hoister. Fixes 1.3.20 where CACHE_RAM /
  REASONING_PRESERVE / CONTEXT_SHIFT reached the command builder but had
  no panel field. Any other llama-server flag is still passable verbatim
  via EXTRA_ARGS.

## 1.3.20 — 2026-07-10

- Three new b9947 llama-server switches join the cell config panel (and
  the EXTRA_ARGS hoister recognizes them): CACHE_RAM (--cache-ram,
  prompt-cache RAM cap — b9947 defaults to 8 GiB, worth lowering on
  RAM-tight hosts), REASONING_PRESERVE (--reasoning-preserve — keep the
  reasoning trace across the whole history; Qwen3.6's template suggests
  it at startup), CONTEXT_SHIFT (--context-shift — slide the window on
  endless generation). Field help in all 20 languages. The webui
  MCP/agent/tools toggles (--agent, --ui-mcp-proxy, --tools) were
  already on the panel.

## 1.3.19 — 2026-07-10

- vLLM gets the same lifecycle story as llama.cpp, sized to its pip
  nature: first-time provisioning now installs a PINNED version
  (`VLLM_DEFAULT_VERSION`, override with the VLLM_VERSION env) instead
  of "whatever PyPI had that day"; System → llama.cpp shows the
  installed vLLM version with an update-to-latest button and a small
  version history — installing any pin is the rollback, running as the
  same shared background job with the streamed log. PyPI keeps every
  release, so no local snapshots are needed. Running vLLM cells keep
  their loaded version until restarted.

## 1.3.18 — 2026-07-10

- The crash-watchdog verdict is sticky: an incident is persisted
  server-side, so the banner is still there when the board is opened
  hours after the crash storm ended — and it survives admin restarts.
  It clears automatically when the binary changes (restore/update) or
  when explicitly dismissed; the dismissal is also persisted, per
  build, so a new build starts with a clean slate. The banner shows
  the time of the last crash marker.

## 1.3.17 — 2026-07-10

- The build-restore confirmation now says exactly what will happen
  (current build → target build; running cells keep their binary until
  restarted) and what the escape hatches are if the restored build
  misbehaves too: the replaced build stays in the archive, any release
  rebuilds from source via Update Build, and the same restore works
  over ssh (`scripts/install-llama.sh --restore <id>`). The crash
  watchdog banner routes through this same confirmation instead of its
  own inline two-step button.

## 1.3.16 — 2026-07-10

- Crash watchdog: when model cells start crashing within hours of a
  fresh llama.cpp build (crash markers in the cells' journal, 15-min
  window), the board shows a prominent banner offering to restore the
  previous archived build. The restore fires only after an explicit
  second confirmation click — never automatically. Thresholds:
  `LLAMA_SUSPECT_MIN_CRASHES` (3) / `LLAMA_SUSPECT_BUILD_AGE_H` (6).
- Client build archives default to keeping 2 snapshots (current + one
  undo) instead of 5 — client snapshots are large and a client rollback
  is never urgent since running cells keep serving their old binary;
  `llamaBuildsKeep` in the scout config overrides.

## 1.3.15 — 2026-07-10

- Build archive + one-click rollback: every successful llama.cpp build
  is snapshotted (binary + libs + metadata; the last 5 are kept,
  `LLAMA_BUILDS_KEEP` to change) into
  `~/.local/share/lama-caravan/llama-builds/`. System → llama.cpp gains
  an "Archived builds" list with a Restore button — restoring copies
  the snapshot back and checks the clone out at its commit, streaming
  into the same job log. The script grows `--list-builds`,
  `--restore <id|commit>` and `--archive-current` for the CLI path, and
  clients get the same ability via caravan-scout
  (`GET /api/llama-node/builds`, `POST /api/llama-node/restore`,
  proxied as `/api/fleet/llama-builds` / `/api/fleet/llama-restore`).
  Running model servers keep their current binary until restarted.

## 1.3.14 — 2026-07-10

- Fleet llama.cpp updates land on client hosts too: a ⇪ button on each
  client node chip converges that client onto the controller's exact
  commit via caravan-scout v1.1.0 (`POST /api/llama-node/update`, a
  background job whose slim status rides every heartbeat — the chip
  turns into a pulsing "building…" indicator while it runs). The
  controller proxies via `POST /api/fleet/llama-update {hostId, tag}`.
- Client node chips gain a "stale binary" badge when a running server
  started before the last llama.cpp rebuild on that host — the visual
  cue that a restart is needed to apply the new build (restarts stay
  manual by design).

## 1.3.13 — 2026-07-10

- The System-modal "Update llama.cpp" button now runs the update as a
  background job wrapping `scripts/install-llama.sh --force --no-restart`
  (fetch/checkout of the release tag, probe-gated Blackwell workaround,
  cmake build, UI-asset fallback — one battle-tested pipeline instead of
  the old raw fetch + ff-merge that 409'd on any tracked local change and
  died with the HTTP request on long builds). The UI polls
  `/api/llamacpp/update-status` and streams the build log live; an
  optional `tag` in the POST body pins a specific `bNNNN` release.
  Running cells keep serving the old binary until restarted by hand.
- The board no longer flags an in-sync client as outdated (yellow ⬆):
  llama.cpp version hashes are short git abbrevs whose length varies per
  clone (7 vs 9 chars for the same commit) — the comparison is now
  prefix-based instead of strict equality.
- The controller's "→ bNNNN ⬆" upstream arrow (and the System-modal
  "upstream build" chip) compare the release tag's COMMIT against the
  local head instead of tag number vs local build number — the local
  build is a clone-local commit count (a shallow clone reports b731
  while sitting exactly on b9947), so the numeric comparison showed a
  false "update available" forever.
- GPU detection in install-llama.sh / install-whisper.sh no longer
  flakes to "No NVIDIA GPU" on a 5090 box: `lspci | grep -q` under
  `set -o pipefail` dies of grep's early-exit SIGPIPE; detection now
  goes through `nvidia-smi -L` with a -q-less lspci fallback.
- install-llama.sh wipes a stale `build/` automatically when its cached
  CUDA compiler version doesn't match the live `nvcc`: a dir configured
  under one toolkit and incrementally rebuilt under another mixes
  objects with different `cudaDeviceProp` layouts — the cause of the
  June smpbo corruption AND of `llama_decode: invalid argument` crashes
  seen during today's rollout (initially misattributed to b9947).

## 1.3.12 — 2026-07-10

- The Blackwell (`sm_120`) smpbo workaround is retired to a probe-gate:
  `install-llama.sh` now compiles a 20-line CUDA probe and applies the
  single-file patch **only if** the direct `sharedMemPerBlockOptin` read
  actually returns garbage. Verified on the incident host (RTX 5090,
  driver 595.71, CUDA 13.2): a fully unpatched build serves both
  production models cleanly — the 2026-06 corruption was an artifact of
  early/mixed Blackwell driver+toolkit stacks (upstream closed the
  equivalent PRs as unreproducible). Healthy hosts now build vanilla
  upstream and the llama.cpp clone stays pristine, unblocking clean
  git-based updates. Postmortem gained a §9 with the re-verification;
  the never-filed upstream MR draft is archived.

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
