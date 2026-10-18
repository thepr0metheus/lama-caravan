# Proxy daemon module reference (`caravan/proxy/`)

The proxy daemon is the traffic half of lama-caravan. `agent-proxies.py` at the
repo root is a 25-line launcher (kept at that name and path because systemd
`ExecStart` runs it directly and `scripts/test_queue_node.py` loads it by
path); the real code lives in `caravan/proxy/`, refactored out of a 3,030-line
monolith. The daemon binds one HTTP listener per enabled route port (CARAVAN_PROXY_BASE_PORT,
default 23001+, on
the live system), forwards OpenAI-compatible requests to upstream
llama-servers or cloud providers, and enforces queueing and admission on the
way through. It is stdlib-only.

At runtime it shares **no code paths** with the admin server. The two talk
exclusively through files:

- The proxy **reads** `agent-proxies.json` (routes, routers, policy,
  stopRequests) — written by the admin, picked up via mtime checks every ~2s.
  It also reads `cloud-providers.json` and
  `~/.config/llamacpp-easy-admin/provider-secrets.json` for cloud upstreams.
- The proxy **writes** `agent-proxy-state.json` (atomic unique-temp writes)
  and `logs/proxy-events/<date>.jsonl`, which the admin reads. Its one write
  into the admin-owned config file is appending `stopRequests` entries during
  preemption, done atomically.

Module layering (each layer imports only to its left):

```
paths ← runtime ← {config, events, cloud_auth, translate, summarize}
      ← capacity ← graph ← state ← queue_admission ← handler ← listeners ← main
```

`graph` sits below `state` because `state.sync_agents_state` calls
`apply_router` to resolve each route's effective upstream URL.
`request_clock` and `upstream_pool` are stdlib-only leaves that only `handler`
imports; `request_body` is one too, imported by `handler` and `entry`.

## Request lifecycle

What happens to one `POST /v1/chat/completions` arriving on a proxy port:

1. **Port listener.** `listeners.py` has already bound a `ThreadingHTTPServer`
   on this route's port, with the route dict stapled to the server object.
   On the entry for keys (`entry.py`) the request's key names the route
   instead, and from then on it is that route's request.
   `ProxyHandler.do_POST` dispatches into `ProxyHandler.proxy()`, which runs
   the entire lifecycle on the connection's thread. A request id is minted as
   `<time_ns>-<thread_ident>`, the body is read whole — by its length or its
   chunks (`request_body.py`) — and `request_summary` extracts
   model, message counts, and a text preview for telemetry. (`GET /v1/models`
   never reaches this path — `_send_models_fast` answers it locally without
   touching the upstream.)

2. **Route resolution.** The handler calls `live_route_for_port(port)` so
   config edits apply to the very next request, then `apply_router(route,
   current_config(), ctx={model, audio, embeddings})` overlays the
   router-chosen upstream onto the route. `apply_router` short-circuits audio
   uploads to `rules.audioOutput` and embeddings to the fleet-wide
   `rules.embeddingsOutput`, then walks the router's node graph via
   `resolve_graph` from the request's input node (a fallback proxy with no
   wiring of its own inherits its primary sibling's input). If the graph path
   crosses a legacy `queue` node or reaches a local output with an active
   model-owned queue, its spec (slots, spill %, sticky, keepalive, spill
   target ref) is stashed on the route as `queuePlan.spec`. `SharedQueuePolicy`
   supplies spill %, reservation and loading retry duration from the global
   policy for every queue. Old node overrides are ignored and removed on save. An unwired input
   falls back to legacy `pick_router_output` (bySource pin > schedule window >
   capacity-aware failover chain > default). A proxy that is unassigned, bound
   to a missing router, or resolves to no output is marked `unrouted` and gets
   an immediate 503 — no queue, no upstream — with a `blocked` event. Every
   `blocked` record carries the status the client got (this one 503, a port's
   wrong key 401): the history's Requests tab shows a refusal by it.

3. **Intake bookkeeping.** The request is registered with
   `add_active(port, item)` (phase `queued`) and a `received` event is
   appended. For a *streaming* request bound for a llama upstream, the handler
   sends `200` + SSE headers **immediately** and builds a `keepalive_writer`:
   while the request waits in queue, `keepalive_sse_bytes` chunks (a real
   `reasoning_content: " "` delta — clients ignore bare `: comment` lines)
   reset the client's read-timeout without polluting the visible answer.

4. **Admission.** Cloud routes skip the queue entirely (a `paused`/`drain`
   route mode raises `ProxyRequestBlocked` 503 first). Llama routes enter the
   queue + spill loop around `wait_for_proxy_slot(route, request_id,
   keepalive_writer, spec)`:
   - **Capacity.** The queue is partitioned per upstream llama-server:
     `route_group_key` is `"upstreamHost:upstreamPort"`. `upstream_slot_total`
     probes the upstream's `/slots` (5s TTL cache, last-known-good preserved)
     to learn its `--parallel` count; the spec/policy `maxSlots` is the
     fallback. A request is admitted when its FIFO `position == 0` within the
     group **and** `active_count(group) < max_slots` **and** no sticky-slot
     reservation for a different port blocks the group.
   - **FIFO.** The request appends an entry to `pending_requests` under
     `queue_condition`, stamped with a monotonically increasing `queue_seq`.
     `queue_position` ranks by `seq` within the group. The loop wakes every
     0.25s (or on `notify_all`) and re-checks; `update_active` publishes phase
     `queued` with live position and queued-ms.
   - **Keepalive / client disconnect.** Every `keepaliveSec` (spec or policy,
     default 20) the keepalive writer fires; a broken pipe there raises
     `ProxyClientDisconnected` — the only way a queued client's disappearance
     is detected — and the handler records the outcome without writing a
     response.
   - **Deadline budget.** Thresholds are percentages of the route's
     `clientTimeoutSeconds` (synced from OpenClaw by the admin; overridable
     per graph input node): `prio_at = wait × priorityPreemptPct/100`,
     `cloud_at = wait × spillPct/100`. When a spill chains into another queue
     node, `deadline_epoch` (absolute epoch seconds) rides along on the route
     so the next queue works off the *remaining* budget, never a fresh full
     timeout. There is no hard in-loop abort timer; the exits are admission,
     spill, client disconnect, and the paused/drain check.
   - **Preemption.** Only for routes with `priority > 0` on the implicit
     default queue (explicit queue nodes are pure FIFO + spill — no crowns).
     After `prio_at`, `choose_preemption_victim` picks the lowest-priority,
     oldest non-queued request on the same upstream group, skipping crowned
     (priority > 0) and `preemptible: false` requests. The victim's id is
     appended to `stopRequests` in `agent-proxies.json` via
     `append_stop_request` (atomic write under `config_lock`, cache mtime
     reset), its upstream socket is severed by `close_active_request`, and the
     preemptor polls for up to `preemptGraceSec` to take the freed slot
     (`proxy_or_llama_has_capacity` with `prefer_llama=True` consults the
     upstream's live `is_processing` count).
   - **Spill.** At `cloud_at`, a graph queue node raises
     `ProxyQueueSpill(spill_ref, queued_ms, deadline_epoch)`; the legacy
     default queue raises `ProxyCloudFallback(provider_id, queued_ms)` when
     `cloudFallbackProviderId` is set. The handler catches the spill,
     re-resolves the route from the spill edge's target via
     `apply_router_spill` (which may surface *another* queue node — chained
     queues), propagates the deadline, and loops; after 8 spills or an
     unroutable target it raises `ProxyRequestBlocked(503, …,
     "queue_timeout")`. A `ProxyCloudFallback` exits the loop with the
     provider id and the request proceeds as a cloud request.
   - On admission the entry moves from `pending_requests` to
     `admitted_requests`, an `admitted` event is written, and the handler sets
     phase `received` (after which the id is discarded from
     `admitted_requests` — `active_count` counts it via its non-`queued`
     phase from then on).

5. **Upstream connect.**
   - *Llama:* plain `http.client.HTTPConnection(upstreamHost, upstreamPort,
     timeout=600)`. Hop-by-hop headers are stripped; `X-Agent-Proxy`,
     `X-Agent-Proxy-Request-Id` and `X-Forwarded-For` are added; the path is
     forwarded untouched. The client named there and in the journal is the
     sender (`ProxyHandler._client`, `ClientAddress`): behind the DSM's proxy on
     the NAS the address it names, not its own 127.0.0.1 (2026-10-11).
   - *Cloud:* the effective provider is resolved — `providerId` (a model
     block: fixed model + `modelMode`) via `load_cloud_provider`, else
     `cloudAccountId` (account passthrough: client's model forwarded) via
     `load_cloud_account` — and `load_provider_secret` returns the auth header
     pair, refreshing an OAuth access token in place when it expires within
     60s (written back through `CredentialVault`, the file's one writer). Three shapes follow:
     an **openai-subscription** account (or a `chatgpt.com` baseUrl) gets the
     request translated by `_chat_to_responses_body` and posted to
     `/backend-api/codex/responses` with JWT-derived `chatgpt-account-id`
     headers — unless the client already speaks the Responses API
     (`/v1/responses`, or a body with `input` and no `messages`, as Codex CLI
     sends): then `_responses_passthrough_body` forwards it as written, with
     only the step's model, `store: false` and `stream: true` imposed; an
     **anthropic** provider on `/chat/completions` gets
     `_chat_to_anthropic_body` and the `/messages` path; any other provider
     gets a base-path rewrite plus `model_named` when
     `modelMode == "rewrite"` — the step's model set in the body, added when
     the client named none (a key of the entry need not name one).
   - *A pool's step.* A cable's cloud end is a pool (`load_cloud_provider`,
     `cb:<pool id>`); `pool_steps.resolve` picks the step that serves this
     request — the first one fit now — and the provider is that step's account
     with the step's model (`modelMode: rewrite`), its id kept as the pool's.
     With no step fit, the pool answers itself: a `PoolRefusal` — 429 when
     every step is held by a limit or the operator's switch, 503 otherwise,
     with each step's reason and the earliest reset — takes the way a
     provider's answer takes (the exit's verdict, a 🛟 backup, the journal row,
     `errorKind: pool_unavailable`) without a connection. A provider that
     refuses the step for its limit before any output — 429, 402, 401 — rests
     the step's account (`pool_steps.failed`) and the request goes on to the
     next step; anything else is not the pool's to handle.
   - *The connection.* A provider's comes from `upstream_pool`: a kept one
     from an earlier request when one is open and quiet, else a new one. A
     cell's is opened for the request. A kept connection the provider closed
     in the instant before the request gets the request again on a fresh
     connection, once (`upstream_reconnect` in the journal).
   - Either way the connection is put in `active_controls` via
     `register_active_control` so a stop request can sever it mid-flight. A
     llama upstream answering 503 with "Loading model" is retried every 3s for
     up to `loadingModelWaitSec` (default 60s). The attempt is logged as
     `upstream_started`, the answer as `upstream_response`.

6. **Response relay.** Subscription and Anthropic SSE streams are translated
   chunk-by-chunk back into chat-completions SSE (`_iter_responses_…`,
   `_iter_anthropic_…`); a Responses client gets the subscription stream
   untranslated (`iter_responses_passthrough`, which still tallies delta text
   and usage for the journal), or the final `response` object as JSON when it
   asked for `stream: false`; a buffered Anthropic response is converted whole by
   `_anthropic_to_completions_json`. Native llama/OpenAI SSE is passed through
   line-by-line until `data: [DONE]`; non-streaming bodies are relayed with
   the first 1 MiB captured for `response_summary`. Every chunk updates byte/
   chunk counters and `stream_summary_from_line` accumulates delta chars,
   usage, timings and finish reasons; `stop_requested` is checked per chunk
   and raises `ProxyRequestStopped`. A background heartbeat thread covers the
   *forwarding* phase the queue keepalive doesn't: if the client has seen no
   bytes for `queueKeepaliveSec` (clamped 5–30s) during slow prompt
   processing, it writes a keepalive delta under a shared write lock so it
   never splits a real chunk. If the SSE stream is already open when an error
   hits, the error is encoded as an SSE `error` event + `[DONE]` instead of an
   HTTP status.

7. **Bookkeeping.** The `finally` block always runs: unregister the control
   handle, close the upstream (a provider's connection is kept instead when
   the relay ended cleanly, see `upstream_pool.py`), assemble the result row
   (status, duration, bytes, first-byte latency, queue info, where the time
   went as `latency` (`request_clock.py`), usage tokens for the spend meter,
   llama `timings` for per-consumer TPS history, provider/model attribution,
   the governing queue node's `stickySlotSec` if any). `finish_active` moves
   the row from `active` to `recent` (last 20 kept), sets the upstream group's
   sticky slot for llama routes (per-block value wins over policy) so the same
   agent's follow-up tool calls are preferred, and notifies the queue. Every
   `add_active`/`update_active`/`finish_active` triggers `write_state`
   (atomic snapshot to `agent-proxy-state.json`), and a terminal `finished`
   event lands in the day's JSONL log.

## caravan/proxy/paths.py

Environment-driven constants and repo-relative paths — the daemon's only
configuration surface besides `agent-proxies.json` itself. `PROJECT_ROOT` is
derived from the module location so the file contracts land next to the
launcher. Everything is overridable via `AGENT_PROXY_*` environment variables.

- Owns: `CONFIG_FILE`, `STATE_FILE`, `LOG_DIR`, `CLOUD_PROVIDERS_FILE`,
  `PROVIDER_SECRETS_FILE`, `HOST`, `UPSTREAM_HOST`/`UPSTREAM_PORT`,
  `DEFAULT_ROUTES`, `DEFAULT_POLICY` (maxSlots, threshold percentages,
  preempt/sticky knobs), `HOP_HEADERS`, `STREAM_DONE_MARKER`,
  `BODY_CAPTURE_LIMIT`, `TEXT_PREVIEW_LIMIT`, `LOG_RETENTION_DAYS`.
- Key functions: none (constants only).

## caravan/proxy/runtime.py

Every cross-domain mutable global lives here, so higher layers share state
without import cycles. The objects are mutated in place and **never rebound**
— import the objects, don't copy them. (The two rebound globals in the
package deliberately live elsewhere, next to their writers: `queue_seq` in
`queue_admission.py`, `_pending_rebind` in `listeners.py`.) Alongside the
globals sit the trivial read accessors over them.

- Owns: `lock` (guards `state`), `config_lock`, `active_controls_lock`,
  `log_lock`, `state_write_lock`, `queue_condition`, `config_cache`,
  `active_controls`, `pending_requests`, `admitted_requests`, `state` (the
  agents/active/recent dict behind `agent-proxy-state.json`), `sticky_slots`
  (per upstream group), `slot_total_cache` + `slot_total_lock`.
- Key functions: `set_sticky_slot`, `clear_sticky_slot`, `sticky_slot_blocks`,
  `sticky_slot_snapshot`, `all_active_items`, `queue_snapshot`,
  `queue_position`.

## caravan/proxy/config.py

Loads `agent-proxies.json` with mtime caching — `current_config` re-reads only
when the file's mtime changes (checked on every call; the listener watcher
polls every ~2s) and hands out copies so callers never mutate the cache. It
normalizes the policy into clamped integers, keeps only the last 100
`stopRequests`, and transparently reads the pre-rename `switchboards` /
`sb:default` / `switchboardId` field names. `normalize_route` defines the
canonical route shape (label, port, upstream, mode, priority, preemptible,
`clientTimeoutSeconds`, per-route threshold overrides, `routerId`,
`portClosed`). The config's `entry` (`{port, publicUrl}`, `{}` when off) is
cleaned by `KeyEntry.clean` and handed out with the rest.

- Owns: config parsing, route normalization, policy clamping, legacy-key
  back-compat.
- Key functions: `current_config`, `load_config`, `load_routes`,
  `load_enabled_routes`, `live_route_for_port`, `normalize_route`.

## caravan/proxy/events.py

Append-only JSONL event log under `logs/proxy-events/<date>.jsonl` — the
proxy's flight recorder, read (never written) by the admin. Each row embeds a
snapshot of all active items and the pending queue at the moment of the
event, so a single line is enough to reconstruct contention. Appends are
serialized by `log_lock` and old dated files beyond `LOG_RETENTION_DAYS`
(default 30) are unlinked opportunistically after each write. `write_proxy_event`
never raises — logging must not fail a live request.

- Owns: the event-log file format and retention.
- Key functions: `write_proxy_event`, `trim_proxy_event_logs`,
  `safe_json_value`.

## caravan/proxy/capacity.py

Slot capacity accounting for admission. A queue group is one upstream
llama-server (`"host:port"`), matching the `upstream` field stamped on active
items so the admin can group requests per server. `upstream_slot_total` asks
the upstream's `/slots` for its true `--parallel` count with a 5s TTL cache
and last-known-good semantics (a flapping probe never clobbers a discovered
count back to "auto"). `active_count` counts requests occupying a slot: those
in `admitted_requests` or past the `queued` phase. An engine next to the cells
(an output of kind `engine`: Ollama, LM Studio) has no `/slots` — it is not
asked, neither on admission nor by the background probe, and its queue group
takes the policy's slot count.

- Owns: `slot_total_cache` contents (the cache object itself lives in
  runtime), the has-capacity predicate.
- Key functions: `route_group_key`, `upstream_slot_total`,
  `slot_totals_snapshot`, `active_count`, `llama_processing_count`,
  `proxy_or_llama_has_capacity`.

## caravan/proxy/graph.py

The router DAG engine — the canonical routing logic, pure over the config
dict. `resolve_graph` walks a router's node graph from a request's input node
to an output, evaluating `byModel` (fnmatch on the requested model),
`requestType` (embeddings port), `schedule` (weekday×hour grid or legacy
windows), `weighted`, `roundRobin`, `failover` (capacity-aware via the slot
cache) and `queue` nodes; the first queue node crossed has its spec + resolved
spill ref recorded for the handler. `apply_router` overlays the chosen output
onto the route (marking `unrouted` when unassigned/missing/no-output) after
short-circuiting audio and embeddings outputs; `apply_router_spill`
re-resolves from a queue node's spill edge. An output of kind `engine` (a
model of an engine next to the cells) or `machine` (a model of a machine's
entry, its scout — 1.3.506) overlays `upstreamModel`, the model's name there;
the overlay drops it first, so a route re-resolved onto a cell never carries an
engine's name. The kinds are one table, `caravan/common/upstream_types.py`
(`UpstreamType`). It sits *below* `state` because
`sync_agents_state` calls `apply_router`. Unit-tested by
`scripts/test_queue_node.py`, which loads `agent-proxies.py` by path and uses
the launcher's re-exports.

An `onError` (🛟 backup) node picks its exit from the output verdicts in
`output_health.py`, and the request kind decides how. A request takes main
until a FRESH verdict says main is dead (`next_exit`): if it fails there, the
handler replays it on the backup. A client's question to the port
(`ctx.discovery`: `/v1/models`, `/props`, `/api/*` — anything that is not
inference, `caravan/common/request_kind.py`) is never replayed. It goes to the
exit that answers (`discovery_exit`): the exit whose last word was an answer
wins over a silent one, and a silent one over a failing one, however old
those words are. Of two failing exits, the one that answered more recently
wins (`lastOkAt`). With both answering, main wins. `PORT_QUESTION_CTX` is that
question's ctx. `answer_port_question(route, config)` applies it, and
`port_question_reaches(resolved)` names what the question reaches: `cloud`,
`llama`, `engine`, or `""` for an unrouted port. Three readers call these two:
the proxy's `/v1/models`, the board's advertised window (`admin/topology.py`)
and the Model card's window links (`admin/model_card.py`), so none of them can
resolve a port differently.

- Owns: node evaluation, output picking, the queue-node spec
  (`_queue_spec_from_node`), fallback-inherits-primary input resolution,
  per-input `clientTimeoutSeconds` overrides.
- Key functions: `resolve_graph`, `apply_router`, `apply_router_spill`,
  `answer_port_question`, `port_question_reaches`, `pick_router_output`,
  `_queue_spec_from_node`; constants `PLAIN_REQUEST_CTX`, `PORT_QUESTION_CTX`.

## caravan/proxy/state.py

Maintains `agent-proxy-state.json` — the live snapshot the admin dashboard
polls — and the per-port active/recent bookkeeping behind it. `write_state`
serializes the runtime `state` dict plus sticky-slot and slot-total snapshots,
writing atomically via a **unique** temp file per write
(`<name>.<pid>.<tid>.tmp` + `replace`) under `state_write_lock`; a shared
temp path used to race between threads. `finish_active` also arms the sticky
slot for the finished llama route so the same port wins the next admission
window.

The file also carries `subscriptionUsage` — each subscription account's last
reading of its limit windows — which the admin judges for the steps' switch
levels, `pools` — the proxy's last choice per pool, every step's reason and
the last 50 switches (`pool_steps.snapshot`) — and `listenHost`, where the
ports listen (the board's `PortDoor`).

The file is rewritten every `ProxyHeartbeat.BEAT_SECONDS` (10 s) whatever
happened (`queue_admission.heartbeat_pass`, after the beat's probe of the
cells' slots), and the admin takes a file older than `STALE_SECONDS` (30 s)
for a proxy that is gone (caravan/common/proxy_heartbeat.py). It used to be
written on requests and after a probe only: a cloud-only controller probes no
cells, and its pool card fell back to "Not measured yet" 30 s after each
request (the NAS, 2026-10-08).

- Owns: the state-file format, active/recent lists (recent capped at 20),
  sticky-slot arming on finish.
- Key functions: `sync_agents_state`, `write_state`, `add_active`,
  `update_active`, `finish_active`, `add_recent`.

## caravan/proxy/cloud_auth.py

Resolves cloud credentials for proxied requests from two admin-maintained
files: `cloud-providers.json` (accounts + pools) and the 0600
`provider-secrets.json`. A `providerId` names a pool (`load_cloud_provider`): the
pool with its steps and the window it stands for, the model left empty until a
step is chosen; a bare account (`load_cloud_account`) is what a step goes to,
and what a route naming an account and no pool reaches, with the client's
model passed through. OAuth tokens that expire within 60s are refreshed in
place against the account's `tokenUrl` by `CredentialVault`
(caravan/common/credential_vault.py): a lock per account serializes renewals
across both processes, and the write re-reads the file under a document lock
and writes it atomically, 0600. The vault is the file's one writer — the
admin's key writes and restores go through it too. An account carries its
`accountType` (whether it is a ChatGPT subscription is the account's fact, not
its address's) and the account whose limits it shares (`usageAccountId`).

- Owns: `CLOUD_PROVIDER_AUTH` (per-provider auth header/prefix/extra-headers
  table), OAuth refresh.
- Key functions: `load_cloud_provider`, `load_cloud_account`, `load_cloud_pools`
  (every pool, what the entry publishes to its consumers), `load_provider_secret`.

## caravan/proxy/subscription_usage.py

A subscription's limit windows as the proxy last read them. `SubscriptionUsage.note(account,
headers)` reads the Codex backend's `x-codex-{primary,secondary}-*` headers
(used percent, window length in minutes, reset time) into `{seconds, usedPct,
resetAt}` per window. An answer without them leaves the reading as it was:
absence is not a reading. `UsagePage.fetch` reads the account's usage page
(`GET /backend-api/wham/usage` with its own sign-in, which spends no share of
any window) for a step whose reading is stale: a step held at its stop level
gets no traffic, so no answer brings a new reading, and a reset that came
early — a banked one, or one bought — would stay unseen until the old reset
time. The page's parser reads the same two windows the headers carry;
OpenAI's extra `gpt-reserve` window is left out, since it shares the weekly
length.

- Owns: `subscription_usage` (per-account readings under a lock).
- Key names: `SubscriptionUsage`, `UsagePage`.

## caravan/proxy/pool_steps.py

Which step of a pool serves a request, chosen at admission; a stream never
changes its step. `PoolSteps.resolve(source, body, excluded, path)` walks the
pool's steps in order and answers the first one fit now, or the pool's own
refusal. Nothing picks a step by hand: the order is the only one (the
operator, 2026-10-11). A step is not fit while it is switched off, while
its model is closed by its schedule (reason `closed` with `opensAt`, the
epoch it opens: `ModelSchedules`, caravan/common/model_schedules.py, read in
the caravan's zone, `CaravanZone`; no connection is tried), without a sign-in or key, unable to take a Responses request (a key provider
other than OpenAI's speaks chat only), a subscription asked for anything but a chat (a recording to
transcribe, a text to embed — `format_unsupported`, 1.3.501; a pool all of whose steps are so is 400
`unsupported`, the caller's to fix), resting after its provider refused it
(429 quota, 402 payment, 401 sign-in — for `Retry-After`, else 30 s, five
minutes for 402 and 401), no longer listed by its provider, or — a
subscription — with a limit window down to the step's stop level (the rule
`UsageReserve`, caravan/common/usage_reserve.py, shared with the board), out of
its limit, or with limits that cannot be read now. Below its switch level a
step is fit but gives way (reason `switch`): the pool takes the first step fit
and above its own switch level, and the first one giving way only when there
is none. Both levels are read by `CloudPools.levels`, the controller's rule. A reading older than five
minutes is refreshed from the usage page, at most every 30 s; a failed read is
"limits unknown", never zero usage. The pool always takes the first fit step,
so it goes back up the chain as soon as an earlier step fits again. A
Responses request that refers to an earlier response (`previous_response_id`)
gets a `PoolContextRefusal` (400) before any step when more than one step is
enabled: the conversation lives with one account. A confirmed saved reset
(`SubscriptionResetJournal`) clears a quota rest and a stale reading at once.
Each choice is kept per pool with every step's reason (`snapshot`, into the
state file), and a change of step is a `pool_switch` event in the journal (the
last 50 are kept). `OwnAnswer` is the shape of an answer the proxy gives itself
(status, headers, a body read in pieces). A `PoolRefusal`'s Retry-After is the
first moment a step is fit again — a limit's reset or a schedule's opening; one
whose every step is `closed` is `closed`, with `opens_at` and `opens_text` (the
time in the caravan's zone with its offset), and the entry's dialect tells the
client so (`OpenAIError.closed`). `PoolRefusal.POOL_KINDS` are the
kinds a pool's refusal is recorded under, `OWN_KINDS` with the names before
1.3.462 still in the logs the board reads.

- Owns: `pool_steps` (the choices, rests, tried readings and the switch journal).
- Key names: `PoolSteps` (`resolve`, `failed`, `snapshot`, `clear`), `OwnAnswer`,
  `PoolRefusal`, `PoolContextRefusal`.

## caravan/proxy/pool_watch.py

A pool edited on the board is decided again at once (1.3.547; the owner, 2026-10-14: he carried
luna above sol and the card went on saying that sol serves). The board's "Serving now" and its
lit cable are `pool_steps`'s word about its last choice, and a choice is made when a request comes
or when the idle probe asks (at most every five minutes, and only for a pool a backup node leads
to). An edit sends no request, so the word stayed with the step that served before, which was no
longer the one that would serve next. `PoolWatch` looks every second at the stamps (mtimes) of the
cloud file and of the vault — two stats; when one moved it reads every pool as `load_cloud_provider`
hands it to a request (the pool, the models' levels, their schedules) and decides again, with
`PoolSteps.resolve`, each pool whose reading is not the one last decided by: a pool carried,
switched off or added, a level moved. The state file is rewritten after such a pass and the board
takes the word at its next poll (a second for the proxy, then the board's 1.5–5 s). The first look
decides nothing (a restarted proxy says nothing until it is asked, as before); a decision sends
nothing to a provider (it may read a subscription's limit windows, as a request's decision does);
a pool that cannot be decided is named in the log and left until it changes again; a look that
fails is repeated. It runs in a thread of its own (`PoolWatch.start`, from `main`), since a
decision may wait for a usage answer. The decision is the selector's own, so the word is what the
next request does: a step carried first but below its switch level gives way, and the word stays
on the step that would serve. A switch it makes is a `pool_switch` event like any other, with no
reasons when nothing was wrong with the step it left.

- Owns: the readings of the pools last decided by.
- Key names: `PoolWatch` (`sweep`, `run`, `standard`, `start`, `mtime`).
- Pinned by `scripts/test_pool_watch.py`.

## caravan/proxy/translate.py

Protocol translation between the OpenAI chat-completions dialect the clients
speak and what cloud upstreams accept: chat-completions → Responses API
(`chatgpt.com` codex backend) and chat-completions ↔ Anthropic Messages, in
both buffered and SSE-streaming forms (the streaming translators are
generators yielding client-ready `data:` chunks, including tool-call and
usage mapping). Also home to `classify_proxy_error`, the taxonomy that turns
exceptions into `client_disconnected` / `upstream_timeout` / `proxy_error`
kinds for events and incidents.

- Owns: request/response format conversion, the error taxonomy.
`model_named` puts an engine's own model name into a request (added when the
client sent none), since one engine serves many models behind one port; any
body that is not a JSON object goes as the same bytes. `ChunkFold` folds chat
completion chunks into the one chat completion they stream — text, tool calls
by index with their arguments joined, finish reason, usage — for a client that
did not ask for a stream; `finished()` says whether the stream reached its last
word, and a stream cut before it is a failure, not half an answer handed out
as whole.

`AnthropicUsage` (1.3.585) gathers what an Anthropic answer says it used, from where it says it: the input — `input_tokens` (the part not served
from the cache), `cache_creation_input_tokens`, `cache_read_input_tokens` — in `message_start`, the output in `message_delta` (the newer API repeats
the input there), or all of it in a whole answer. The counts are cumulative, so a figure is taken only by being larger than the one before. It
answers in OpenAI's shape: `prompt_tokens` is ALL the input, the cached part is `prompt_tokens_details.cached_tokens`, the part written to the cache
`cache_creation_input_tokens`. Until 1.3.585 the stream's translation read only `message_delta` and wrote `prompt_tokens: 0`, and an answer that
was not streamed was never summarized for the journal: Anthropic's input was recorded as 0. The usage rides the LAST chunk, which a stream the
client cuts off, or the provider drops, never reaches — so the stream's translator takes the caller's `AnthropicUsage` (`used=`), and the handler
keeps it for the journal: where no chunk carried the usage, what the provider had said by then — the input, billed all the same, and the output as
far as it was told — is what the journal row holds (1.3.586). Pinned by `scripts/test_anthropic_usage.py` and `scripts/test_proxy_forward.py`.

- Key functions: `model_named`, `classify_proxy_error`,
  `_chat_to_responses_body`, `_iter_responses_as_completions_sse`,
  `is_responses_request`, `_responses_passthrough_body`, `iter_responses_passthrough`,
  `_chat_to_anthropic_body`, `_iter_anthropic_as_completions_sse`,
  `_anthropic_to_completions_json`, `_extract_chatgpt_account_id`; class `AnthropicUsage`.

## caravan/proxy/summarize.py

Compact request/response summaries for telemetry — what the events log and
state file carry instead of full bodies. `request_summary` extracts model,
message/role counts, prompt char counts, image parts, tool count and a
truncated last-text preview; `response_summary` and `stream_summary_from_line`
pull usage, finish reasons and llama.cpp's exact per-request `timings` (the
authoritative TPS source) from buffered bodies and SSE tail chunks
respectively.

- Owns: preview truncation (`TEXT_PREVIEW_LIMIT`), usage/timings extraction.
- Key functions: `request_summary`, `response_summary`,
  `stream_summary_from_line`, `parse_json_bytes`, `compact_text`.

## caravan/proxy/queue_admission.py

Admission control. `wait_for_proxy_slot` is the blocking loop described in the
lifecycle above, serving both the implicit default queue (thresholds from
policy + per-route fields, spill = legacy cloud fallback) and explicit graph
queue nodes (thresholds from the node spec, spill = any graph target, no
priority/preempt). The six `ProxyX` exception classes defined here are the
control-flow protocol `handler.py` is written against: `ProxyRequestStopped`,
`ProxyCloudError`, `ProxyRequestBlocked`, `ProxyCloudFallback`,
`ProxyQueueSpill`, `ProxyClientDisconnected`. Also here: the
`stop_request_watcher` daemon thread (scans `stopRequests` every 0.25s and
severs matching upstream connections; every ~10s probes every router output's
`/slots` and flushes `write_state` so the admin sees slot totals while idle),
preemption victim selection and the atomic `stopRequests` append, and the
`keepalive_sse_bytes` builder (a `reasoning_content` single-space delta —
clients ignore comment-only keepalives). `queue_seq` is rebound here — keep
every function that rebinds it in this module.

- Owns: `queue_seq`, the admission loop, preemption, stop-request handling,
  the flow-control exceptions, the SSE keepalive payload.
- Key functions: `wait_for_proxy_slot`, `choose_preemption_victim`,
  `append_stop_request`, `close_active_request`, `register_active_control` /
  `unregister_active_control`, `active_control_stop_reason`,
  `stop_requested`, `stop_requested_for_route`, `stop_request_watcher`,
  `keepalive_sse_bytes`, `remove_pending_request`.

## A model of a machine's entry (1.3.506)

An output of kind `machine` is a model of a machine's entry: its scout's
address (`agentUrl`), where the scout serves every model of the machine by
OpenAI's API, picking a running copy by the `model` a request names (scout
2.27). The controller makes one per model the scout lists
(caravan/admin/machine_models.py); a pool's row names it as `mm:<hash>`.

- The request names the model: the handler puts `upstreamModel` into the body
  (`model_named`), as for an engine's model.
- Each model has a queue of its own: `route_group_key` is
  `host:port/model` — the `upstream` stamped on its requests — where a cell's
  and an engine's is `host:port`. The scout's port serves every model of its
  machine, and one queue for all of them would hold a model back behind
  another's work.
- Its places are the scout's word (scout 2.29): `capacity.MachinePlaces`
  asks `GET /v1/models/<name>` of the entry — `caravan.slots`, how many
  requests its running copies take at once, and `caravan.busy`, how many they
  work on now — for `upstream_slot_total`, the heartbeat's probe and
  `llama_processing_count`, as a cell's /slots are read. A number the scout
  does not say is the policy's. Zero places (no copy runs) is no number to
  wait for either: the request goes, and the entry answers 503
  `model_not_running` at once — the pool's next row then, and the output's
  verdict.
- `GET /v1/models` on a port routed to such an output is the entry's list
  narrowed to the one model, as for an engine.
- The probe (onError exits) asks the one model: alive when its state is
  `running`, else 503 `model_not_running`; a model the entry does not have is
  404 (`_probe_machine`).

## caravan/proxy/request_body.py

A request's body, taken off the connection whole before the request goes on:
by its `Content-Length`, or chunk by chunk when the client sends it so
(`Transfer-Encoding: chunked` — curl uploading a pipe, a client streaming a
file it does not measure first). Until 1.3.505 the proxy read the length alone:
a body in chunks went upstream as none — a cell was asked an empty question, a
consumer of the entry was told its request was neither JSON nor a form — and
the chunks were left unread on a connection the answer then closed.

The body goes upstream with its own length: the client's framing stays behind
(`Transfer-Encoding` and `Trailer` are hop-by-hop, `paths.HOP_HEADERS`), and a
cell's request carries the length of the body that goes — http.client says it
for a request that names none — not the client's, which a body in chunks lies
about or lacks, and which a body the caravan rewrote (`ChatLevers.for_cell`, an
engine's model) no longer matches. A cloud request always said its own.

No limit on the size: a body by its length never had one, and one for chunks
alone would make the two ways answer differently. A body that cannot be read as
the request says it is sent — a chunk size that is not hex, a chunk that does
not end where its size says, a body that ends early, a `Content-Length` that is
not a number or is given twice differently, a transfer coding other than
`chunked` — is `RequestBody.Malformed`: a port answers 400 in its words
(`{"error": "the request body cannot be read: <why>", "kind": "bad_request"}`),
the entry 400 in OpenAI's (`OpenAIError.broken_body`); the journal has it as
`blocked` (`unreadable-body`, `entry:broken-body`), the connection closes with
the answer, and the upstream is never asked
(`scripts/test_proxy_body.py`).

- Owns: reading one request's body.
- Key names: `RequestBody.read`, `RequestBody.Malformed`.

## caravan/proxy/request_clock.py

Where one request's time went. `durationMs` and `firstByteMs` mix the
caravan's own work with the model's and the network's; `RequestClock` splits
them, and the result row carries its `as_dict()` as `latency`:

| Field | What |
|---|---|
| `prepMs` | the caravan's own work before its first upstream attempt: routing, translating the body, the journal. The queue wait is not in it (`queue.queuedMs`) |
| `connectMs` | opening the upstream connection (TCP, and TLS for a provider); `0` when a kept connection was taken |
| `connReused` | whether it was a kept one; `null` for a cell, where nothing is kept |
| `headersMs`, `firstChunkMs` | from the request sent to the answer's headers and to its first body bytes |
| `cpuMs` | processor time of the request's thread, the whole request |

Connect, headers and first chunk belong to the leg that answered. A mark that
never happened stays `null`: a request the caravan answered itself has no
connect time. A request refused before an upstream (blocked, gone while
queued) carries no `latency` at all. `TimedResponse` wraps the upstream answer
to note its first body bytes: the subscription translator yields a made-up
first chunk before it reads the provider, so the row's `firstByteMs` says when
the client got something, not when the provider answered. Both clocks are
parameters (`scripts/test_request_clock.py`).

- Owns: the marks of one request.
- Key names: `RequestClock`, `TimedResponse`.

## caravan/proxy/upstream_pool.py

Connections to cloud providers kept between requests. Each request used to
open its own and close it after one answer: a TCP and a TLS handshake every
time, about 52 ms from the controller's machine to OpenAI and 91–122 ms from
the NAS (measured 2026-10-07). A cell is not pooled: its connection costs a
fraction of a millisecond, and the proxy cancels a cell's generation by
tearing its socket down.

`UpstreamPool.take` hands out a kept connection to the same scheme, host and
port when one is open and quiet, else a new one. A connection comes back
(`release` → `give_back`) only after a clean relay — the client still there,
no stop from the board reached it, the idle heartbeat has stopped — and only
when its answer was read to the end and neither side asked to close it. A
stream's closing bytes are drained on a thread of their own, for at most
`drain_sec` (1 s) and `drain_bytes` (64 KiB), so a client never waits for
them. A kept connection is dropped instead of handed out when it sat idle
longer than `idle_sec` (60 s; Cloudflare, in front of chatgpt.com and
api.openai.com, closes an idle connection after 400 s, measured 2026-10-07) or
when the provider closed it meanwhile — its socket turns readable. At most
`per_host` (8) idle connections are kept per provider; idle ones are swept on
every take and give back. `STALE_ERRORS` are the failures of a kept
connection the provider closed under a request: the handler sends the
request again on a fresh connection, once.

- Owns: the idle connections, `upstream_pool` (the process's one pool).
- Key names: `UpstreamPool.take`, `reopen`, `release`, `give_back`,
  `is_stale`, `idle_count`.

## caravan/proxy/handler.py

`ProxyHandler(BaseHTTPRequestHandler)` — the per-port request handler whose
`proxy()` method is the full request lifecycle: route resolution, the
queue + spill loop, upstream forwarding (llama direct or cloud with credential
resolution and protocol translation), streaming relay with keepalives and
stop checks, error encoding (JSON or in-band SSE `error` event depending on
whether headers already went out), and the always-run `finally` bookkeeping.
It also implements the "Loading model" 503 retry window, the idle-forwarding
heartbeat thread, and the `GET /v1/models` fast path. The key a client
presents to the caravan (`Authorization` / `X-Api-Key`) opens one of its routes
and stays with the caravan: it reaches neither a cell nor an engine (it used to
reach a cell as it was, until 2026-09-26). A cell is reached at its machine's
address and port with no key of its own. A request routed to an
engine's model (`upstreamType` `engine`) goes to the engine like a cell's, with
the model's name in the body (`model_named`); `/v1/models` on such a port is the engine's list narrowed to
that one model (`_engine_model_entry`), or a 503 naming the model the engine
no longer lists. `output_probe.py` probes such an output with `GET /v1/models`
and the model in the list — a completion would load the model into the
engine's memory on every pass. The request's ctx is built once and reused by
the entry, a queue's spill and a rescue. A client's question whose exit
refuses the connection is not replayed, but the refusal is noted as that
exit's verdict. The rest of the client's questions then go to the exit that
answers. A cell's `GET /props` (and `/v1/props`) is relayed with the port's
window where llama.cpp states its own (`default_generation_settings.n_ctx`,
top-level `n_ctx` on older builds): the same `effective_window(limit, served)`
that `/v1/models` publishes, so a client reading either sees one figure
(`_publish_props_window`; the fields and the two paths, `PROPS_PATHS`, are
named in `caravan/common/context_window.py`). Without a limit the cell's number
is relayed as it is. `window_paths` there lists every path on which a port
states its window, by what the port reaches; `scripts/test_proxy_models.py`
asks each listed path on a real proxy and expects the port's figure. A cloud
port answers OpenAI's retrieve-model, `GET /v1/models/<id>`, from the entry
its list answers with (`_cloud_model_entry`), and compares the id DECODED
(`unquote`; a `+` stays a plus): a client sends a space as `%20`, and the raw
path once answered 404 to the very id the list had named. `output_probe.py` runs its first pass as soon as the proxy
starts, then every 30 seconds.

- Owns: the request lifecycle, per-request phase transitions
  (`queued → received → upstream → streaming/reading → finished`), spend/
  timings attribution on the result row.
- Key functions: `ProxyHandler.proxy`, `ProxyHandler._send_models_fast`,
  `do_GET` / `do_POST` / `do_OPTIONS`.

## caravan/proxy/listeners.py

Per-route listener lifecycle. `reconcile_listeners` diffs the set of bound
ports against `load_enabled_routes()`: it opens a `ThreadingHTTPServer` (one
daemon thread per listener) for new ports, shuts down listeners for removed
ports off-thread (shutdown joins the serve loop), and refreshes the fallback
route object on survivors — so adding or removing a client in the Routing
graph opens/closes its port with **no daemon restart**. `listener_watcher`
re-runs the reconcile whenever `agent-proxies.json`'s mtime changes (polled
every 2s) or a previous bind failed (`_pending_rebind`, rebound here — keep
its writers in this module). Each pass also calls `sync_agents_state` +
`write_state`.

A route whose port is closed (`portClosed`) is not bound: its agent comes in
through the entry by its key. `EntryListener` opens, moves or closes the
entry's listener as the config's `entry` says, in the same pass; an entry on a
route's port stays closed, the route keeps its port.

- Owns: the `serving` port→server registry, `_pending_rebind`, `entry_listener`.
- Key functions: `reconcile_listeners`, `listener_watcher`, `EntryListener.reconcile`.

## caravan/proxy/entry.py

The one entry for consumers with keys (visumap `caravan-single-entry`): one port
behind the DSM proxy, `caravan-api.example.org`, instead of a port per agent.
`EntryHandler` reads the presented key (`Authorization: Bearer`, else
`x-api-key`) and finds the route that carries it as `apiKey`
(`caravan/common/key_entry.py`, the one reading for the proxy and the board).
No key, or a key no route carries: 401; a key two routes carry (a hand-edited
file — the board refuses it on save): 401 too, not 409, which an OpenAI client
retries. Every refusal is in OpenAI's shape (`openai_errors.py`) with an
`X-Request-Id`, and a `blocked` event with the reason `entry:<why>` under the
consumer's name once it is known.

Then two kinds of consumer:

- **A consumer of the entry** (a route of kind `"consumer"`, since 1.3.466) is
  served as a company's gateway serves its clients. Its key calls the pools of
  the set a cable in Routing leads it to (`set`, since 1.3.497;
  `caravan/common/entry_models.py`, `caravan/admin/model_sets.py`) — and no
  router ever decides for it. `GET /v1/models` lists the set's pools by their
  names, in the set's order and OpenAI's model shape (each window the pool's
  against the consumer's own limit, absent when neither is known), or nothing
  for a key no cable reaches yet. `GET /v1/models/<id>` answers that model, the
  id compared decoded and spelled as the list spells it. A request's `model`
  picks the pool, as OpenAI's API picks a model: a request naming none is 400
  (`you must provide a model parameter`), a name the set has not is 404
  `model_not_found`, and a key with no model at all is 404 `model_not_found`
  with the words that the operator connects the key to a set of models. A
  consumer of the form before 1.3.497 (`pool`, its one pool) calls that pool
  until the controller rewrites it (`SetDesk.migrate`). A consumer of the form before 1.3.486 (`models`, the pools it might
  call) calls the first of them until the controller rewrites it
  (`ConsumerDesk.migrate`). The pool found, the request is the consumer's
  route overlaid onto the pool's output (`cb:<id>`, Routing's id for it)
  and served by `ProxyHandler.proxy` with the consumer's dialect
  (`dialect.OpenAIDialect`). Only inference paths are routed
  (`caravan/common/request_kind.py`); any other path is 404
  `Invalid URL (METHOD /path)`. The `model` is read from a JSON object, or —
  where OpenAI's API takes a file, a recording to transcribe on
  `/v1/audio/transcriptions` — from a form's field (`multipart/form-data`,
  since 1.3.501; `caravan/common/request_fields.py`: its text fields found by
  the boundary, the file stepped over, never decoded), and the body goes on to
  the pool's row byte for byte. A body that is neither is 400 `unreadable`, its
  words naming both. The body comes by its length or in chunks
  (`request_body.py`, 1.3.505); one that cannot be read as it says it is sent
  is 400 "The request body cannot be read: <why>." A subscription's row serves a chat alone
  (`request_kind.is_chat_request`, `PoolSteps`): a recording passes it by for
  the pool's next row, and a pool none of whose rows does the work is 400
  `unsupported` — "The model `X` does not serve POST /path" — never a wait.
  Since 1.3.502 each model of the list says what it does
  (`cloud_auth.load_pool_kind`, caravan/common/model_kinds.py): OpenRouter's
  `architecture` and the caravan's `caravan` — `jobs`, an ear's `languages`
  and `max_audio_ms` — from what every row of its pool that may serve does
  (a subscription's chat takes pictures; a cell's facts ride on its router
  output). A pool of known kind refuses a request for other work before
  sending it, 400 `unsupported`; an unknown or mixed pool leaves it to its
  rows. A pool's window counts its cells' (`CloudPools.window` with the
  outputs' `contextLength`).
  One more question is answered (since 1.3.495): Ollama's `POST /api/show`,
  which Hermes asks for a model's window — the consumer's pool in Ollama's
  shape, the window under `model_info` `caravan.context_length` and as
  `num_ctx` in `parameters`, both absent when the pool states none. The
  entry's refusals carry the request's method in the journal: Routing's
  client card lists a client's errors of the last 30 days from it
  (`caravan/admin/client_misses.py`). Routing's own tests of a client
  carry `X-Caravan-Probe` (`KeyEntry.PROBE_HEADER`); heard from this machine
  itself, not through the DSM's proxy, such a request is journaled under the
  client `routing-probe`, and the client's errors list leaves it out.
- **An agent of the old kind**, moved here with its port's key (1.3.442), is
  still its port's: its request goes through its Routing graph as if it had
  come to the port, because `ProxyHandler` reads the route only through its
  `route` property. Its `model` chooses nothing.

A streamed answer carries `X-Accel-Buffering: no`
(`ProxyHandler._send_stream_headers`), so the DSM's nginx passes the tokens on
as they come instead of in batches.

- Owns: nothing (the route is per request; the dialect is reset per request).
- Key names: `EntryHandler`, `EntryHandler.REFUSALS`, `EntryHandler.is_consumer`.

## caravan/proxy/dialect.py

How a request is routed and told its failures, chosen once the request is
known: `PortDialect` (a port's way — its router decides, the upstream's
status, headers and body pass as they came, the caravan's own failures as
`{"error", "kind"}`) or `OpenAIDialect` (a consumer of the entry — its pool
decides; every failure in OpenAI's shape and the caravan's words; of a
provider's headers only `Content-Type`, `Content-Length` and `Cache-Control`
pass, plus its own `X-Request-Id`; a client that did not ask for a stream gets
one JSON chat completion where the provider streams anyway). The handler asks
the dialect at each such point (`resolve`, `failure`, `stream_failure`,
`header_ok`, `answer_error`, `extra_headers`, `answers_whole`) instead of
branching on the kind of request.

- Owns: nothing (`PORT_DIALECT` is the default instance).
- Key names: `PortDialect`, `OpenAIDialect`, `PORT_DIALECT`.

## caravan/proxy/openai_errors.py

An error as an OpenAI client reads it: the status and `{"error": {message,
type, param, code}}`, with `type` from OpenAI's table (`invalid_request_error`,
`rate_limit_error`, `server_error`). A known wait travels as `Retry-After`;
past the 60 s an OpenAI client still takes from it, `x-should-retry: false`
too — a pool at its stop level for hours would only be asked again. The words
name nothing behind a model: a provider refusing the caravan's sign-in (401,
403) is a 502 to the consumer — a 401 would tell the client its own key is
wrong — and a provider's 5xx is a 502 without the provider's words; a 4xx
about the request (too long a context, a bad parameter) keeps them. A 4xx of
a local row — a cell, or a machine's model — keeps its `error.code` too
(`unsupported_robot_schema`), so a client branches on it as on OpenAI's own;
only a word is told (`OpenAIError.clean_code`: letters, digits, `_` `.` `-`,
64 at most), and a provider's code stays at the provider.

- Owns: nothing.
- Key names: `OpenAIError` (`no_key`, `wrong_key`, `shared_key`,
  `unknown_model`, `invalid_url`, `unreadable`, `no_pool`, `paused`,
  `limit`, `unavailable`, `unsupported`, `closed`, `upstream`, `masked`, `duration`).

## caravan/common/upstream_types.py

The kinds of upstream a router output names, as one table (1.3.506):
`llama` — a cell, one model on its own port, its places its /slots; `engine` —
a model of an engine next to the cells (Ollama, LM Studio), many models on the
engine's port, the request naming its model, its places the policy's;
`machine` — a model of a machine's entry (its scout), many models on the
scout's port, the request naming its model, its places the scout's word and a
queue of its own; `cloud` — a pool or an account, no places counted. A type
outside the table is read as `llama`, as the file always was. The controller
writes the type (`router_dsl.normalize_router_output`), and the proxy's
overlay, capacity and heartbeat read it; the board's twin is
`OutputCells.NAMED` (static/js/output-cells.js).

- Owns: nothing.
- Key names: `UpstreamType.of`, `UpstreamType.named`, `NAMED`.

## caravan/common/chat_levers.py

The standard fields of a chat request that steer how a model answers —
OpenAI's `reasoning_effort`, `verbosity` and an image's `detail` — said to the
row that serves (1.3.501; the owner, 2026-10-12: a client keeps to OpenAI's
API). `ChatLevers.for_responses` gives the subscription's translator
(`translate._chat_to_responses_body`) `reasoning.effort` when the client asked
for an effort and `text.verbosity` always ("low", as before, when it asked for
none or a word it does not know); `ChatLevers.detail` an image's `detail`
("auto" unsaid). `ChatLevers.for_cell` tells a llama.cpp cell "no thinking" —
`chat_template_kwargs.enable_thinking: false` — when a chat asks for the effort
"none" or "minimal" and the client has not set `enable_thinking` itself; the
handler applies it on every cell's leg (an engine's leg names its model
instead, `model_named`). Anything it does not change goes as the same bytes.
gemma-4 through the entry spent a short answer's every token on thinking
before it (2026-10-12).

- Owns: nothing.
- Key names: `ChatLevers` (`effort`, `verbosity`, `detail`, `for_responses`, `for_cell`).

## caravan/proxy/main.py

The entry point: ensure the state directory exists, record which code this
process runs, start the `stop_request_watcher` thread, bind the current
config's ports via `reconcile_listeners`, start the `listener_watcher` thread, the idle
probe (`start_probe_thread`) and the pool watch (`PoolWatch.start`), then park the main
thread. All work happens on daemon threads.

The record is `StartRecord` (`caravan/proxy/started.py`): the commit the
process started from and its pid, written into `agent-proxy-state.json` as
`sourceCommit` and `pid` before the first state write. `scripts/deploy.sh`
reads it on the controller and restarts the proxy only when the code it runs
changed (`scripts/proxy_restart.py`); a record whose pid is not the unit's
MainPID belongs to a dead process and does not count.

- Owns: thread startup order, the start record.
- Key functions: `main`; `StartRecord.at_start`, `StartRecord.read`.

## Invariants for contributors

- **File contract, not imports.** Never import across
  `caravan/admin` ↔ `caravan/proxy` — the daemons only communicate via
  `agent-proxies.json` (admin-owned; the proxy's sole write is the atomic
  `stopRequests` append in `append_stop_request`), `agent-proxy-state.json`
  and `logs/proxy-events/*.jsonl` (proxy-owned; admin read-only), plus
  `cloud-providers.json` (admin-owned, proxy reads) and `provider-secrets.json`,
  whose one writer in both processes is `CredentialVault`. Shared helpers go in
  `caravan/common/` (the proxy uses `fsio.atomic_write_text`).
- **`runtime.py` globals are mutated in place, never rebound.** Import the
  objects, don't copy them, don't reassign them. Anything that must be
  rebound lives next to its writers: `queue_seq` in `queue_admission.py`,
  `_pending_rebind` in `listeners.py`.
- **Atomic writes everywhere a reader races.** The state file uses a unique
  temp name per write (`<name>.<pid>.<tid>.tmp` + `replace`) under
  `state_write_lock`; `agent-proxies.json` mutations go through
  `atomic_write_text` under `config_lock` with the cache mtime reset;
  provider secrets are written by `CredentialVault` only, under its document
  lock, atomically with 0600.
- **Launcher re-exports are load-bearing.** `agent-proxies.py` must keep its
  name/path (systemd `ExecStart`, `scripts/test_queue_node.py` loads it via
  `spec_from_file_location`) and must keep re-exporting `resolve_graph`,
  `apply_router`, `apply_router_spill` and `_queue_spec_from_node` from
  `caravan.proxy.graph` — the tests resolve those names on the loaded module.
  Do not drop them.
- **Stdlib only.** The daemon has zero third-party dependencies
  (`http.client`, `http.server`, `threading`, `json`, `urllib`, …). Keep it
  that way — it runs as a bare systemd --user unit on every controller.
- **Telemetry must never break traffic.** `write_proxy_event` and
  `write_state` swallow their own failures by design; keep new bookkeeping on
  that side of the line.
