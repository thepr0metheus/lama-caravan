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
imports.

## Request lifecycle

What happens to one `POST /v1/chat/completions` arriving on a proxy port:

1. **Port listener.** `listeners.py` has already bound a `ThreadingHTTPServer`
   on this route's port, with the route dict stapled to the server object.
   `ProxyHandler.do_POST` dispatches into `ProxyHandler.proxy()`, which runs
   the entire lifecycle on the connection's thread. A request id is minted as
   `<time_ns>-<thread_ident>`, the body is read, and `request_summary` extracts
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
   an immediate 503 — no queue, no upstream — with a `blocked` event.

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
     forwarded untouched.
   - *Cloud:* the effective provider is resolved — `providerId` (a model
     block: fixed model + `modelMode`) via `load_cloud_provider`, else
     `cloudAccountId` (account passthrough: client's model forwarded) via
     `load_cloud_account` — and `load_provider_secret` returns the auth header
     pair, refreshing an OAuth access token in place when it expires within
     60s (atomic 0600 write-back of the secrets file). Three shapes follow:
     an **openai-subscription** account (or a `chatgpt.com` baseUrl) gets the
     request translated by `_chat_to_responses_body` and posted to
     `/backend-api/codex/responses` with JWT-derived `chatgpt-account-id`
     headers — unless the client already speaks the Responses API
     (`/v1/responses`, or a body with `input` and no `messages`, as Codex CLI
     sends): then `_responses_passthrough_body` forwards it as written, with
     only the block's model, `store: false` and `stream: true` imposed; an
     **anthropic** provider on `/chat/completions` gets
     `_chat_to_anthropic_body` and the `/messages` path; any other provider
     gets a base-path rewrite plus `rewrite_model_in_body` when
     `modelMode == "rewrite"`.
   - *A subscription's reserve.* A ChatGPT subscription states its limit
     windows on every answer, a 429 included; `subscription_usage` keeps the
     last reading per account. Before sending, the account's reserve
     (`usageReserve`: the share of each window the operator keeps) is checked
     against that reading (`reserve_gate`). While a window has no more left
     than the reserve, nothing is sent: a `ReserveRefusal` answers in the
     provider's place — 429 `usage_limit_reached`, `Retry-After` and
     `resets_at` up to the window's reset — and takes the way a provider's
     429 takes: the exit's verdict, a 🛟 backup, the journal row
     (`errorKind: usage_reserve`).
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
`clientTimeoutSeconds`, per-route threshold overrides, `routerId`).

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
model of an engine next to the cells) overlays `upstreamModel`, the model's
name in the engine; the overlay drops it first, so a route re-resolved onto a
cell never carries an engine's name. It sits *below* `state` because
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
reading of its limit windows — which the admin reads for the card's reserve
banner.

- Owns: the state-file format, active/recent lists (recent capped at 20),
  sticky-slot arming on finish.
- Key functions: `sync_agents_state`, `write_state`, `add_active`,
  `update_active`, `finish_active`, `add_recent`.

## caravan/proxy/cloud_auth.py

Resolves cloud credentials for proxied requests from two admin-maintained
files: `cloud-providers.json` (accounts + model blocks) and the 0600
`provider-secrets.json`. A `providerId` (block) yields a provider dict with a
fixed model and `modelMode`; a bare account yields passthrough. OAuth tokens
that expire within 60s are refreshed in place against the account's
`tokenUrl`, and the updated secrets file is written back atomically with 0600
perms.

Both shapes carry the account's `accountType` (whether it is a ChatGPT
subscription is the account's fact, not its address's) and its
`usageReserve`: every model of an account draws on one pool.

- Owns: `CLOUD_PROVIDER_AUTH` (per-provider auth header/prefix/extra-headers
  table), OAuth refresh.
- Key functions: `load_cloud_provider`, `load_cloud_account`,
  `load_provider_secret`.

## caravan/proxy/subscription_usage.py

A subscription's limit windows as the proxy last read them, and the answer
the proxy gives in the provider's place. `SubscriptionUsage.note(account,
headers)` reads the Codex backend's `x-codex-{primary,secondary}-*` headers
(used percent, window length in minutes, reset time) into `{seconds, usedPct,
resetAt}` per window. An answer without them leaves the reading as it was:
absence is not a reading. `ReserveRefusal` is a local response shaped like
`http.client.HTTPResponse` (status, headers, `read`), so the handler relays it
on the path a real answer takes. Its body is OpenAI's own
`usage_limit_reached` error plus `caravan_reserve` (`window_seconds`,
`remaining_pct`, `reserve_pct`), and its message names the caravan, not the
provider.

The rule is `caravan/common/usage_reserve.py` (`UsageReserve`): a window
closes while its remaining share is at or below the reserve and its reset is
still ahead. Without a reset time nothing closes — a door shut with no known
opening would stay shut. Of several closed windows, the one that reopens last
is named. The reserve is 1–90% per window; 0 means none. The admin computes
the card's banner with the same class from the proxy's reading, so the card
says what the proxy does.

`ReserveGate` is the one question the handler and `output_probe.py` both
ask before sending anything to a subscription: is the door shut now? While
it is shut nothing is sent, so no answer brings a new reading, and a reset
that came early (a banked or bought one) would stay unseen until the old
reset time — up to a week on the weekly window. So while shut, a reading
older than five minutes is refreshed from the account's usage page
(`GET /backend-api/wham/usage` with the account's own sign-in), which spends
no share of any window. A page that does not answer is not asked again for
five minutes, and the door stays as the last reading says. An open door never
asks: its reading rides on the answers. The page's parser reads the same two
windows the headers carry; OpenAI's extra `gpt-reserve` window is left out,
since it shares the weekly length.

The probe keeps the reserve too: a subscription exit whose window is down to
it is recorded as the proxy would answer (429 `usage_reserve`) without
spending the operator's share, and a real probe's headers update the reading.

- Owns: `subscription_usage` (per-account readings under a lock),
  `reserve_gate` (when each account's page was last asked).
- Key names: `SubscriptionUsage`, `ReserveGate`, `ReserveRefusal`; the rule
  `UsageReserve`.

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
body that is not a JSON object goes as the same bytes.

- Key functions: `rewrite_model_in_body`, `model_named`, `classify_proxy_error`,
  `_chat_to_responses_body`, `_iter_responses_as_completions_sse`,
  `is_responses_request`, `_responses_passthrough_body`, `iter_responses_passthrough`,
  `_chat_to_anthropic_body`, `_iter_anthropic_as_completions_sse`,
  `_anthropic_to_completions_json`, `_extract_chatgpt_account_id`.

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
route object on survivors — so adding or removing a client in the Kanban
graph opens/closes its port with **no daemon restart**. `listener_watcher`
re-runs the reconcile whenever `agent-proxies.json`'s mtime changes (polled
every 2s) or a previous bind failed (`_pending_rebind`, rebound here — keep
its writers in this module). Each pass also calls `sync_agents_state` +
`write_state`.

- Owns: the `serving` port→server registry, `_pending_rebind`.
- Key functions: `reconcile_listeners`, `listener_watcher`.

## caravan/proxy/main.py

The entry point: ensure the state directory exists, record which code this
process runs, start the `stop_request_watcher` thread, bind the current
config's ports via `reconcile_listeners`, start the `listener_watcher` thread,
then park the main thread. All work happens on daemon threads.

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
  `cloud-providers.json` / `provider-secrets.json` (admin-owned, proxy reads;
  the OAuth refresh write-back is the exception). Shared helpers go in
  `caravan/common/` (the proxy uses `fsio.atomic_write_text`).
- **`runtime.py` globals are mutated in place, never rebound.** Import the
  objects, don't copy them, don't reassign them. Anything that must be
  rebound lives next to its writers: `queue_seq` in `queue_admission.py`,
  `_pending_rebind` in `listeners.py`.
- **Atomic writes everywhere a reader races.** The state file uses a unique
  temp name per write (`<name>.<pid>.<tid>.tmp` + `replace`) under
  `state_write_lock`; `agent-proxies.json` mutations go through
  `atomic_write_text` under `config_lock` with the cache mtime reset;
  provider secrets are rewritten atomically with 0600.
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
