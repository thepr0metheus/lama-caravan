# Proxy reference (`rust/crates/proxy`)

> The behaviour described here stands unless a sentence says otherwise. Names of Python
> functions below (`snake_case`, and some classes) are from before 2026-11-02 and can be
> read in git at `4c53bc92`, as in `git show 4c53bc92:caravan/proxy/handler.py`. A section's
> heading names the Rust file. Paths are relative to `rust/crates/proxy/src/` unless they
> name a crate.

The proxy is the traffic half of lama-caravan: one Rust program, `caravan-proxy`, a child of the
controller (`rust/crates/admin/src/proxies/service.rs`). It binds one HTTP listener, on the entry's
port, finds the client by its key, forwards OpenAI-compatible requests to a machine's models or to
cloud providers, and queues and admits them on the way. One thread to a connection, no async
runtime.

At runtime it shares **no code paths** with the controller but the library crates. The two talk
exclusively through files under the data folder:

- The proxy **reads** `config/agent-proxies.json` (routes, routers' outputs, policy,
  stopRequests) — written by the controller, looked at by its stamp on each request.
  It also reads `config/cloud-providers.json`, `secrets/provider-secrets.json`,
  `state/model-catalog.json` and `state/subscription-resets.json`.
- The proxy **writes** `state/agent-proxy-state.json` (replaced whole)
  and `logs/proxy-events/<date>.jsonl`, which the controller reads. Its one write
  into a file of the controller's is a renewed OAuth token, through `CredentialVault`. It no
  longer writes into `agent-proxies.json`: nothing appends a stop request but the board.

## Where things are

| File | What it holds |
|---|---|
| `main.rs` | The start: the settings, the listener, the state writer and the two watches. |
| `config.rs` | `ProxyConfig`: where it listens and where its files are, from the environment, once. |
| `proxy.rs` | `Proxy`: the parts together, what every request shares; the state file's one writer. |
| `listener.rs` | The entry's socket: a thread for each connection, the look-out for a new version. |
| `drain.rs` | `Drain`: the way out for a version that has been replaced. |
| `connection.rs` | One client's connection: its request read, the decision taken, the request served or refused. |
| `front.rs` | `Front`: what the entry decides of a request. Only values go in and out. |
| `exchange/` | `Exchange`: one request from its coming to its record, down its pool's rows (`mod.rs`); a row of a machine (`machine.rs`), of a provider (`cloud.rs`), what comes back (`answers.rs`). |
| `pool_steps/` | `PoolSteps`: which row serves (`mod.rs`), why a row is fit or not (`rows.rs`). |
| `pool_watch.rs` | `PoolWatch`: a pool that was edited is decided again at once. |
| `output_health.rs` | `OutputHealth`: what each output's answers said of it. |
| `subscription_usage.rs` | `SubscriptionUsage`: what each subscription account last said of its windows. |
| `admission.rs`, `queue.rs` | `Admission`: one request's wait. `ModelQueue`, `Seat`, `Slot`: the queue of each model, a place as an object. |
| `places.rs` | `MachinePlaces`, `PlacesWatch`: how many requests a model takes at once. |
| `upstream.rs`, `entry_wait.rs` | `UpstreamCall`: a request on its way to a machine's model or a cell. `EntryWait`: the wait for a machine's entry that does not take the request. |
| `provider_request.rs`, `provider_call.rs`, `provider_access.rs` | What goes out to a provider, the call itself, and what it takes outside a request: trust, a renewed token, the usage page. |
| `relay.rs` | An answer on its way to the client: `StreamRelay`, `WholeRelay`, `TranslatedRelay`, `ResponsesRelay`, `WholeRead`. |
| `client.rs` | `ClientSide`: everything written to the client goes through here. |
| `watch.rs` | `Watch`: what a request looks at while it waits: its client, a keepalive, a stop from the board. |
| `stop.rs` | `Ending`: why a request's work ends before its answer does. |
| `board.rs` | `Board`: the running and the recent requests, behind one lock. |
| `record.rs`, `recorder.rs` | What is said of one request; a journal's row. |
| `clock.rs` | The clocks as parameters, and `RequestClock`: where one request's time went. |
| `log.rs` | The process's own log: its standard error, `logs/rust-proxy.log`. |

Below it: `rust/crates/rules` (the entry's models, pools, limits, translation for providers, the errors: no input or
output), `rust/crates/files` (the settings as read, the journal, the credential document, a file replaced whole),
`rust/crates/net` (TLS, kept connections, dialing), `rust/crates/wire` (HTTP on a socket), `rust/crates/os`.

What left with the Python and has no home in Rust, by the owner's word of 2026-11-02 and because no client used it (all
the routes on the live caravan were clients of the entry, with their ports closed and no graph nodes): a route's own
port and its listener, and with them `GET /v1/models`, `/props` and every other answer on a port; the router graph
(`byModel`, `schedule`, `weighted`, `roundRobin`, `failover`, `queue` nodes, 🛟 `onError` backup nodes) and the idle probe
that served it; a queue's spill and the fallback to the cloud; priority preemption; sticky slots. The key of a route that
is no client of the entry gets a 403.

## Request lifecycle

What happens to one `POST /v1/chat/completions` arriving on the entry:

1. **The connection.** `Listener` has bound the entry's port, and each connection gets a thread.
   `Connection::serve` reads the request's head (`wire::RequestHead`) and cleans its target
   (`Front::plain_target`: an address before the path and a fragment after it come off; slashes at
   its start are one). `SettingsFiles::current` gives the settings as the files say them now, so
   edits apply to the very next request. One request to a connection: every answer closes it.

2. **The key and the path.** `Front::before_body`. Settings that do not read: 503 with `Retry-After`. The
   presented key (`Authorization: Bearer`, else `x-api-key`) finds the route that carries it
   (`KeyEntry::route_for`); none, an unknown one or a key two routes carry: 401. A route that is no
   consumer: 403. `GET /v1/models` and `GET /v1/models/<id>` are answered here, from what the settings
   say. A POST that is not inference, and `OPTIONS`: 404 `Invalid URL`. Any other method: 501. Every refusal
   has a `blocked` event under the client's name once it is known, with the status the client got: the
   history's Requests tab shows a refusal by it.

3. **The body and the model.** The body is read whole — by its length or its chunks
   (`rust/crates/wire/src/body.rs`), and an `Expect: 100-continue` is answered first. `Front::with_body` reads
   the model from a JSON object, or from a form's field, and `EntryModels::for_request` says what it means: a pool,
   a model that runs as a pool of one row, or a refusal.

4. **Intake bookkeeping.** `RequestRecord` holds who asked what, with a request id of the time and a number of this
   process, and `RequestSummary` model, message counts and a text preview for telemetry. `Exchange::run` registers it
   (`Board::add_active`) and appends a `received` event. A client paused on the board goes no further: a `blocked`
   record and a 503.

5. **A row.** `Proxy::choose_row` asks `PoolSteps::resolve` for the first row fit now (`pool_steps/`, below). No row
   fit: the pool answers itself, a `PoolRefusal` — 429 when every row is held by a limit or the operator's switch, 503
   otherwise, 400 when none does this work, with each row's reason and the earliest reset — that takes the way a
   provider's answer takes (the journal row, `errorKind: pool_unavailable`) without a connection. A change of row is a
   `pool_switch` event.

6. **A row of a machine: its queue.** For a *streaming* request `client.open_stream` sends `200` + SSE
   headers **immediately**. Then `Admission::wait`:
   - **Capacity.** The queue is partitioned per model: `MachineOutput::group` is `host:port/model` for a
     model of a machine's entry (the port is its scout's) and `host:port` for an engine; a cell is reached through its machine's
     model since 2026-11-07. `MachinePlaces::of` says how many
     requests it takes at once (`places.rs`), the policy's `maxSlots` being the fallback. A request is admitted when
     it is first in its line **and** fewer than that many places are taken (`Seat::try_take`). A place is an object,
     `Slot`: it goes back when it is dropped, on any way out of a request, a thread's panic included.
   - **FIFO.** `ModelQueue::enter` stamps the request with a growing number, and `Seat::position` counts who stands
     before it. The loop wakes every 0.25 s (or when anything changes) and re-checks; `update_active` publishes phase
     `queued` with live position and queued-ms.
   - **Keepalive / client disconnect.** Every 20 s (`Policy::KEEPALIVE_SEC`) the keepalive fires
     (`rust/crates/rules/src/keepalive.rs`: a real `reasoning_content: " "` delta — clients ignore bare `: comment`
     lines); it resets the client's read-timeout without polluting the visible answer. `ClientSide::has_left` looks at
     the socket each turn, and a gone client ends the wait: the outcome is recorded with nothing written back.
   - **The client's wait.** Each request's record says when its client gives up on it, counted from the
     receipt (`clientDeadline`, `connection.rs`): its route's `clientTimeoutSeconds`, else everyone's — the policy's
     `clientTimeoutSec`, 60 min unless said (`ModelQueuePolicy::client_timeout`, 1.3.666; before, a hidden 3600 nobody
     could see). The board shows how long a running request's client still waits. The proxy does not act on it: the
     exits are admission, client disconnect and the model's leave.
   - **The model's leave** (1.3.663, `rust/crates/rules/src/model_queue.rs`: the owner, 2026-10-26, "the queue is the
     model's, not a pool's"). A request comes with `leave` — when it leaves this model's queue and where to
     (`QueueLeave`), which its pool decided at admission. Waited its patience (`queueYieldSec`, one for every model)
     with a ready row further on (`way_on`, asked again at that moment), it ends with `Ending::Yielded` and the walk
     leaves the row for the pool's next one (`pool_retry`, reason `yield`); with nowhere to go any more the limit holds,
     counted from the start of the wait. Waited its limit (`queueLimitSec`; 0 is none), it ends with
     `Ending::Blocked` (503, `queue_timeout`) — the pool's next row if one became fit meanwhile, else the client's 503.
     The record says it each pass (`queue.since`, `leaveAt`, `leaveTo`) and when it got its slot (`slotAt`): the board
     draws the model's queue from them (static/js/model-queue.js).
   - On admission an `admitted` event is written, and the place is held until the answer has gone out.

7. **Upstream connect.**
   - *A machine's model or a cell:* `UpstreamCall`, plain TCP, opened for the request. The client's key and its
     hop-by-hop headers stay here (`KEPT_OUT`); `X-Agent-Proxy`, `X-Agent-Proxy-Request-Id` and `X-Forwarded-For` are
     added; the path goes untouched, the body with the model's own name in it (`RequestFields::model_named`) and "no
     thinking" said as a cell's template takes it (`ChatLevers::for_cell`). The client named there and in the journal
     is the sender (`ClientAddress`): behind the DSM's proxy on the NAS the address it names, not its own 127.0.0.1
     (2026-10-11). An answer of 503 with "Loading model" is retried every 3 s for up to `loadingModelWaitSec` (default
     60 s). When the machine's entry does not answer before the first byte, the request goes to a running copy on its
     own port (below).
   - *A provider:* `ProviderRequest::build`. A client's own headers go on, under one name if the operator set one
     (`ClientName`), and nothing of the home goes out: not nginx's headers, and no `X-Agent-Proxy` (1.3.692,
     `docs/pools.md`). The row's account gives the field a request goes with (`ProviderAccess::field_for`), an OAuth
     access token that expires within 60 s renewed first through `CredentialVault`, the file's one writer. Three shapes
     follow: a **subscription** gets the request translated by `ChatToResponses` and posted to
     `/backend-api/codex/responses` with JWT-derived `chatgpt-account-id` headers — unless the client already speaks the
     Responses API (`/v1/responses`, or a body with `input` and no `messages`, as Codex CLI sends): then
     `ResponsesPassthrough` forwards it as written, with only the row's model, `store: false` and `stream: true` imposed;
     an **anthropic** provider on `/chat/completions` gets `ChatToAnthropic` and the `/messages` path; any other provider
     gets a base-path rewrite and the row's model set in the body, added when the client named none.
   - *The connection.* A provider's comes from `KeptConnections`: a kept one from an earlier request when one is open
     and quiet, else a new one. A kept connection the provider closed in the instant before the request gets the request
     again on a fresh connection, once (`upstream_reconnect` in the journal).
   - *A row that fails.* A provider that refuses the row for its limit before any output — 429, 402, 401 — rests the
     row's account (`PoolSteps::failed`) and the request goes on to the next row. A failed connection or a 5xx before the
     first byte goes on too, while a row could still serve (`pool_retry`). With none left the client is told the failure it
     met. Anything else is not the pool's to handle.
   - The attempt is logged as `upstream_started`, the answer as `upstream_response` (an error's body, up to 4 KB, as
     `upstreamErrorBody`). The reason a provider gives for an error it answered goes into the request's record too —
     `item.error` and `item.errorKind` of `finished`, which every panel reads (1.3.642: before, only the line of
     `finished` held it). A socket read comes back every 2 s, and the same thread looks around (`Watch`): whether the
     client is there, whether the board stopped it, and at 600 s of silence the upstream counts as gone.

8. **Response relay.** Subscription and Anthropic SSE streams are translated chunk-by-chunk back into chat-completions
   SSE (`ResponsesToChat`, `AnthropicToChat`, `TranslatedRelay`); a Responses client gets the subscription stream
   untranslated (`ResponsesRelay`, which still tallies delta text and usage for the journal), or the final `response`
   object as JSON when it asked for `stream: false`; a client that did not ask for a stream gets one chat completion
   (`ChunkFold`); a buffered Anthropic response is converted whole by `AnthropicToChat::whole`. Native llama/OpenAI SSE is
   passed through line-by-line until `data: [DONE]` (`StreamRelay`); non-streaming bodies are relayed with the first 1 MiB
   captured for the summary (`WholeRelay`). Lines are read whole, up to `Lines::LIMIT` (1 MiB): the event that ends a stream is the
   biggest one, and a 64 KB read used to split it, so a long answer reached the client with no last chunk and the journal had no word for
   what it missed. A line past the cap still goes to the client, but as pieces and never as an event, and `StreamFold` counts what it
   could not read as `linesPastCap`: a stream read in pieces does not present itself as whole, and `done` stays what the provider said, not
   the `[DONE]` the caravan writes to end its own client's stream. Every chunk updates byte/chunk counters and `StreamFold` accumulates delta
   chars, usage, timings and finish reasons; the board's stop is looked at between chunks and ends with `Ending::Stopped`.
   A client that speaks the Messages API is answered in that shape, so `StreamFold` reads it too: the text is the block's delta, the end word is
   `stop_reason`, and the provider's own word that the stream is complete is `message_stop` — `[DONE]` is never in a Messages stream.
   Where those words sit in an event is said once, in `MessagesWords`, which the translation reads as well; a tool argument being built
   (`input_json_delta`) is no text said, so the fold's letters are text only. Before this the journal counted the events of such a stream and said
   nothing about what they said: `deltaTextChars: 0`, no finish reason, and `done: false` for an answer the provider ended. Pinned by
   `contract/summaries.json`.
   The keepalive also covers the *forwarding* phase: if the client has seen no bytes for 20 s during slow prompt
   processing, the same thread writes one, so there is no second writer to split a real chunk. If the SSE stream is
   already open when an error hits, the error is encoded as an SSE `error` event + `[DONE]` instead of an HTTP status; a
   stream cut mid-word gets the same, with `upstream_disconnected`, where the Python left a client with no `[DONE]` and a
   clean 200 in the journal.

9. **Bookkeeping.** `Exchange::finish` always runs, a panic inside the request included (`Ending::guarded`): the place
   and the connection go back by `Drop`, a provider's connection is kept when the relay ended cleanly
   (`keep_connection`), and the result row is assembled (status, duration, bytes, first-byte latency, queue info, where
   the time went as `latency` (`RequestClock`), usage tokens for the spend meter, llama `timings` for per-consumer TPS
   history, provider/model attribution). `Board::finish_active` moves the row from `active` to `recent` (last 20 kept),
   and a terminal `finished` event lands in the day's JSONL log. The state file follows within 250 ms
   (`Proxy::state_writer_loop`).

## `config.rs`

The environment, read once at the start — the process's only configuration surface besides the settings files.
Without the entry's port (`CARAVAN_RUST_ENTRY_PORT`, which the controller sets) or the data folder
(`CARAVAN_DATA_DIR`) it says so and does not start: it has no default to guess, and an entry nobody asked for would
listen.

- Owns: `ProxyConfig`: `AGENT_PROXY_HOST` (`0.0.0.0` by default), each file's path under the data folder with a variable
  of its own to overrule it (`AGENT_PROXY_CONFIG_FILE`, `CLOUD_PROVIDERS_FILE`, `PROVIDER_SECRETS_FILE`,
  `MODEL_CATALOG_FILE`, `CARAVAN_SUBSCRIPTION_RESETS_FILE`, `AGENT_PROXY_LOG_DIR`, `AGENT_PROXY_STATE_FILE`),
  `SSL_CERT_FILE`, `AGENT_PROXY_LOG_RETENTION_DAYS` (30), and the commit it was built from.

## `proxy.rs`, `board.rs`

Everything a request changes is a field of `Proxy`: nothing lives in a global. `Board` keeps the per-client
active/recent bookkeeping behind one lock, and changing a request there costs a lock and no disk.
`state/agent-proxy-state.json` is the live snapshot the controller's board polls. One thread writes it
(`Proxy::write_state`, by `files::AtomicFile`), so no two writers can race.
It is written whenever the board changes and every 5 s besides, so on the NAS it lives in memory, `/tmp` of the container
(`AGENT_PROXY_STATE_FILE` in `deploy/nas/compose.yaml`, 2026-11-03): on the disk it was the caravan's most frequent write.

The file also carries `subscriptionUsage` — each subscription account's last
reading of its limit windows — which the controller judges for the rows' switch
levels, `pools` — the proxy's last choice per pool, every row's reason and
the last 50 switches (`PoolSteps::snapshot`) — `outputHealth`, `slotTotals`, and `listenHost`, where the
entry listens (the board's `PortDoor`). `pid` and `sourceCommit` say which process wrote it, and `counts` how many rows
of the journal and writes of this file failed: telemetry does not fail a request, but it is not silent.

The file is rewritten within 250 ms of a change and every 5 s whatever
happened (`Proxy::state_writer_loop`), and the controller takes a file older than `STALE_SECONDS` (30 s)
for a proxy that is gone (`ProxyHeartbeat`, `rust/crates/admin/src/common/misc.rs`). It used to be
written on requests and after a probe only: a cloud-only controller probes no
cells, and its pool card fell back to "Not measured yet" 30 s after each
request (the NAS, 2026-10-08).

- Owns: the state-file format, active/recent lists (recent capped at 20).
- Key names: `Proxy::write_state`, `Board` (`add_active`, `update_active`, `finish_active`, `add_pending`, `state_json`).

## `rust/crates/files/src/settings.rs`, `rust/crates/rules/src/route.rs`, `rust/crates/rules/src/policy.rs`

`SettingsFiles::current` hands a request the settings as the files say them now. A file is read again only when its
stamp (time and size) moved, so a request costs a few `stat` calls instead of a parse, and one reading is shared by
every request that came during it and never changed. `Policy` reads the policy into integers within their bounds,
`stops` keeps the last 100 `stopRequests`. `Route::normalize` defines the route as the proxy reads it (label, port, kind,
what is denied it, mode, its key, `clientTimeoutSeconds`, its window); a route of kind `service`, and one that does not
read, is no route. An `agent-proxies.json` that does not read is no empty one: `unread`, and every client hears 503, not
that its key is wrong.

- Owns: the reading of the settings.
- Key names: `Settings`, `SettingsFiles`, `Documents`, `Policy`, `Route`.

## `recorder.rs`, `rust/crates/files/src/journal.rs`

Append-only JSONL event log under `logs/proxy-events/<date>.jsonl` — the
proxy's flight recorder, read (never written) by the controller. Each row names the request's record
(`item`) and the pending queue at the moment of the event. Each row goes out in one write with `O_APPEND`, and
the file is opened for each row: a day's file replaced from outside (a key masked out of its rows, 2026-11) goes on being
written, and no row goes to a file nobody can read any more. Old dated files beyond `AGENT_PROXY_LOG_RETENTION_DAYS`
(default 30) are taken away once a day, when a row comes. A row that fails to write never fails a live request: the board
counts it (`journalFailures`), and the state file says how many.

- Owns: the event-log file format and retention.
- Key names: `Recorder::event`, `Journal` (`append`).

## `places.rs`

How many requests a model takes at once. A queue group is one server (`"host:port"`, an engine's), or one model of a machine's
entry (`"host:port/model"`, the scout's port), matching the `upstream` field stamped on active items so the controller can group requests.
`MachinePlaces::of` asks a cell's `/slots` for its true `--parallel` count, and a machine's entry
`GET /v1/models/<name>` for `caravan.slots`, each kept 5 s, with 800 ms of patience on a request's way and last-known-good
semantics (a flapping probe never clobbers a discovered count back to "auto"). An engine next to the cells (an output of
kind `engine`: Ollama, LM Studio) has no `/slots` — it is not asked, and its queue group takes the policy's slot count.
`PlacesWatch` asks every output that can be called and does not stand still, every 10 s on a thread of its own, with
3 s of patience, so that the board can say an idle model's places: an idle model's strip said "0 of ?" (the owner,
2026-10-26). The numbers go to the state file as `slotTotals`; the board finds a model's by its output's `slotGroup`
(`rust/crates/admin/src/topology/board_proxy.rs`, 1.3.664).

- Owns: the numbers said, each with when it was asked.
- Key names: `MachinePlaces` (`of`, `totals`), `PlacesWatch`, `Admission::has_room`.

## `provider_access.rs`, `rust/crates/files/src/credential_vault.rs`, `rust/crates/rules/src/cloud_accounts.rs`

Resolves cloud credentials for proxied requests from two files the controller keeps:
`config/cloud-providers.json` (accounts + pools) and the 0600
`secrets/provider-secrets.json`. `CloudPools` reads a pool with its rows and the window it stands for,
`CloudAccounts` an account, which is what a row goes to. Of the credentials the settings keep only who has one
(`Credentials`): a key is read when a request goes out. OAuth tokens that expire within 60s are refreshed in
place against the account's `tokenUrl` by `CredentialVault`
(`rust/crates/files/src/credential_vault.rs`): a lock per account serializes renewals
across both processes, and the write re-reads the file under a document lock
and writes it atomically, 0600. The vault is the file's one writer — the
controller's key writes and restores go through it too. An account carries its
`accountType` (whether it is a ChatGPT subscription is the account's fact, not
its address's) and the account whose limits it shares (`usageAccountId`).

- Owns: per-provider auth header and prefix (`CloudProvider::key_field`), OAuth refresh.
- Key names: `CredentialVault` (`field_for`, `renewed`), `ProviderAccess::field_for`, `CloudProvider`, `CloudAccounts`,
  `CloudPools`, `Credentials`.

## `subscription_usage.rs`, `rust/crates/rules/src/usage_limits.rs`

A subscription's limit windows as the proxy last read them. `AnswerWindows` (`provider_call.rs`) reads the Codex backend's
`x-codex-{primary,secondary}-*` headers (used percent, window length in minutes, reset time) into `{seconds, usedPct,
resetAt}` per window, and `SubscriptionUsage::keep` keeps them. An answer without them leaves the reading as it was:
absence is not a reading. `ProviderAccess` reads the account's usage page
(`GET /backend-api/wham/usage` with its own sign-in, which spends no share of
any window) for a row whose reading is stale: a row held at its stop level
gets no traffic, so no answer brings a new reading, and a reset that came
early — a banked one, or one bought — would stay unseen until the old reset
time. The page's parser reads the same two windows the headers carry;
OpenAI's extra `gpt-reserve` window is left out, since it shares the weekly
length.

- Owns: the per-account readings, under a lock.
- Key names: `SubscriptionUsage`, `AnswerWindows`, `UsagePages`, `UsageWindow` (`rust/crates/rules/src/usage_limits.rs`).

## `pool_steps/mod.rs`, `pool_steps/rows.rs`, `output_health.rs`

Which step of a pool serves a request, chosen at admission; a stream never
changes its step (the code says "row", the journal's fields "step"). `PoolSteps::resolve` walks the
pool's steps in order and answers the first one fit now, or the pool's own
refusal. Nothing picks a step by hand: the order is the only one (the
operator, 2026-10-11). A step is not fit while it is switched off, while
its model is closed by its schedule (reason `closed` with `opensAt`, the
epoch it opens: `ModelSchedules`, `rust/crates/rules/src/model_schedules.rs`, read in
the caravan's zone; no connection is tried), without a sign-in or key, unable to take a Responses request (a key provider
other than OpenAI's speaks chat only), a subscription asked for anything but a chat (a recording to
transcribe, a text to embed — `format_unsupported`, 1.3.501; a pool all of whose steps are so is 400
`unsupported`, the caller's to fix), resting after its provider refused it
(429 quota, 402 payment, 401 sign-in — for `Retry-After`, else 30 s, five
minutes for 402 and 401), no longer listed by its provider, or — a
subscription — with a limit window down to the step's stop level (the rule
`UsageReserve`, `rust/crates/rules/src/usage_limits.rs`, shared with the board), out of
its limit, or with limits that cannot be read now. Below its switch level a
step is fit but gives way (reason `switch`): the pool takes the first step fit
and above its own switch level, and the first one giving way only when there
is none. Both levels are read by `CloudPools.levels`, the controller's rule. A row of a local model
is passed by while the board knows its cell stands still (its router output says `stopped`, 1.3.645:
reason `stopped`, no connection tried — a stopped cell was asked again each time the last failure's
verdict ran out, and every such request drew a red 502), while traffic found it dead in the last
five minutes (`unavailable`), and it gives way while every slot is taken (`busy`) — at once, or, while the
models' queue has a patience (`queueYieldSec`, `rust/crates/rules/src/model_queue.rs`), after it: the busy row is then
chosen in its place among the ready rows, and the request carries its leave into the cell's queue (`queueLeave`:
on after the patience while another row is ready, a 503 after the limit while none is). A reading older than five
minutes is refreshed from the usage page, at most every 30 s; a failed read is
"limits unknown", never zero usage. The pool always takes the first fit step,
so it goes back up the chain as soon as an earlier step fits again. A
Responses request that refers to an earlier response (`previous_response_id`)
gets a refusal (`PoolRefusal::of_context`, 400, `pool_context_required`) before any step when more than one step is
enabled: the conversation lives with one account. A confirmed saved reset
(`SubscriptionResetJournal`) clears a quota rest and a stale reading at once.
Each choice is kept per pool with every step's reason (`snapshot`, into the
state file), and a change of step is a `pool_switch` event in the journal (the
last 50 are kept). A `PoolRefusal`'s Retry-After is the
first moment a step is fit again — a limit's reset or a schedule's opening; one
whose every step is `closed` is `closed`, with `opens_at` and `opens_text` (the
time in the caravan's zone with its offset), and the entry's dialect tells the
client so (`OpenAiError::closed`).

- Owns: the choices, rests, tried readings and the switch journal.
- Key names: `PoolSteps` (`resolve`, `can_go_on`, `failed`, `snapshot`), `RowChoice`, `MachineRow`, `CloudRow`, `PoolRefusal`
  (`rust/crates/rules/src/pool_refusal.rs`), `OutputHealth` (`output_health.rs`: a verdict comes from traffic, holds five minutes,
  and a 400 is that request's problem).

## `pool_watch.rs`

A pool edited on the board is decided again at once (1.3.547; the owner, 2026-10-14: he carried
luna above sol and the card went on saying that sol serves). The board's "Serving now" and its
lit cable are `PoolSteps`'s word about its last choice, and a choice is made when a request comes.
An edit sends no request, so the word stayed with the step that served before, which was no
longer the one that would serve next. `PoolWatch` looks every second at the settings
(`SettingsFiles::current`, a few stats unless a file changed); when they moved it reads every pool as a request reads it
(the pool, the models' levels, their schedules) and decides again, with
`PoolSteps::resolve`, each pool whose reading is not the one last decided by: a pool carried,
switched off or added, a level moved. The state file is rewritten after such a pass and the board
takes the word at its next poll (a second for the proxy, then the board's 1.5–5 s). The first look
decides nothing (a restarted proxy says nothing until it is asked, as before); a decision sends
nothing to a provider (it may read a subscription's limit windows, as a request's decision does).
It runs in a thread of its own (`PoolWatch::start`, from `main.rs`), since a
decision may wait for a usage answer. The decision is the selector's own, so the word is what the
next request does: a step carried first but below its switch level gives way, and the word stays
on the step that would serve. A switch it makes is a `pool_switch` event like any other, with no
reasons when nothing was wrong with the step it left.

- Owns: the readings of the pools last decided by.
- Key names: `PoolWatch` (`sweep`, `start`).

## `rust/crates/rules/src/`: `responses_api.rs`, `responses_stream.rs`, `anthropic_api.rs`, `anthropic_stream.rs`, `chunk_fold.rs`, `request_fields.rs`

Protocol translation between the OpenAI chat-completions dialect the clients
speak and what cloud upstreams accept: chat-completions → Responses API
(`chatgpt.com` codex backend) and chat-completions ↔ Anthropic Messages, in
both buffered and SSE-streaming forms (the streaming translators take the provider's events and give client-ready
`data:` chunks, including tool-call and usage mapping). The taxonomy that turns a socket's failure into
`client_disconnected` / `upstream_disconnected` / `upstream_timeout` / `proxy_error` kinds for events and incidents is
`UpstreamEnd` (`rust/crates/proxy/src/stop.rs`).

- Owns: request/response format conversion.

`model_named` puts an engine's own model name into a request (added when the
client sent none), since one engine serves many models behind one port. A form
(a recording to transcribe, multipart/form-data) says it in its text field
`model`: `RequestFields.with_field` replaces the value in place or adds the part
before the closing delimiter, the recording's bytes untouched (1.3.628 — until
then a form went with the pool's name, and a machine's entry looks a model up
by its exact name). Any other body goes as the same bytes. `ChunkFold` folds chat
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
client cuts off, or the provider drops, never reaches — so `AnthropicToChat` keeps an `AnthropicUsage` (`used`), and `Exchange`
keeps it for the journal: where no chunk carried the usage, what the provider had said by then — the input, billed all the same, and the output as
far as it was told — is what the journal row holds (1.3.586). Pinned by `contract/translate.json`.

- Key names: `RequestFields::model_named`, `ChatToResponses`, `ResponsesToChat`, `ResponsesPassthrough`, `ChatToAnthropic`,
  `AnthropicToChat`, `AnthropicUsage`, `MessagesWords`, `ChunkFold`.

## `rust/crates/rules/src/summaries.rs`

Compact request/response summaries for telemetry — what the events log and
state file carry instead of full bodies. `RequestSummary` extracts model,
message/role counts, prompt char counts, image parts, tool count and a
truncated last-text preview; `ResponseSummary` and `StreamFold`
pull usage, finish reasons and llama.cpp's exact per-request `timings` (the
authoritative TPS source) from buffered bodies and SSE tail chunks
respectively. `StreamFold` reads the two shapes a relay carries — the chat chunk, and the Messages event a client that speaks Messages
gets as it came — and both read the same words: `MessagesWords` says where an event's text, end word, usage and model are, and the
translation reads through it too, so the fold does not keep its own copy of where they live.

- Owns: preview truncation, usage/timings extraction.
- Key names: `RequestSummary`, `ResponseSummary`, `StreamFold`, `UsageWords`, `ProviderBodyWords`.

## `admission.rs`, `queue.rs`, `watch.rs`, `stop.rs`

Admission control. `Admission::wait` is the blocking loop described in the lifecycle above, for a row of a machine: the
model's places, its line, and the leave of its queue (`leave`, `way_on`: `rust/crates/rules/src/model_queue.rs`). `Ending` is
the control-flow protocol `Exchange` is written against: `ClientGone`, `Stopped`, `Blocked`, `Upstream`, `Yielded`,
`Inside`. A stop request is read by the request it is about: `Watch::check_stop` looks at most every 0.25 s for its id in the
settings' `stops`, between chunks and at each 2 s turn of a socket read, and the stream ends with `Ending::Stopped`; the
upstream's socket goes with it. The queue's own events are `queued`, `admitted`, `queue_keepalive`, `queue_yield`,
`queue_limit` and `client_disconnected_queued`.

- Owns: the admission loop, the places, stop-request handling, the flow-control enum.
- Key names: `Admission` (`wait`, `has_room`), `ModelQueue`, `Seat`, `Slot`, `Watch` (`turn`, `waited_for_upstream`,
  `check_stop`), `Ending`, `UpstreamEnd`.

## A model of a machine's entry (1.3.506)

An output of kind `machine` is a model of a machine's entry: its scout's
address (`agentUrl`), where the scout serves every model of the machine by
OpenAI's API, picking a running copy by the `model` a request names (scout
2.27). The controller makes one per model the scout lists
(`rust/crates/admin/src/fleet/machine_models.rs`); a pool's row names it as `mm:<hash>`.

- The request names the model: `UpstreamCall` puts `upstreamModel` into the body
  (`model_named`), as for an engine's model — a JSON body's `model`, or a recording's
  form field `model` (1.3.628).
- Each model has a queue of its own: `MachineOutput::group` is
  `host:port/model` — the `upstream` stamped on its requests — where an
  engine's is `host:port`. The scout's port serves every model of its
  machine, and one queue for all of them would hold a model back behind
  another's work.
- Its places are the scout's word (scout 2.29): `MachinePlaces`
  asks `GET /v1/models/<name>` of the entry — `caravan.slots`, how many
  requests its running copies take at once — as a cell's /slots are read. A number the scout
  does not say is the policy's. Zero places (no copy runs) is no number to
  wait for either: the request goes, and the entry answers 503
  `model_not_running` at once — the pool's next row then, and the output's
  verdict.
- A client's "no thinking" (`reasoning_effort` none or minimal) is said the way a
  cell's chat template takes it (`ChatLevers.for_cell`), as to a cell: the model is
  served by cells (1.3.655 — the pools' rows of the machines' cells became rows of
  their models, and Hermes's "none" to gemma had to keep working).
- A model none of whose copies runs or starts carries `stopped`: a pool passes its
  row by without asking (`pool_steps/rows.rs`, as a stopped cell's).
- A machine's entry that does not take the request — the connection refused, or
  dropped before the first byte of the answer, as while its scout restarts — is waited
  for (`EntryWait`, 2026-11-08): asked again every quarter of a second, 15 s at the most,
  then on as before (the pool's next row, or 502). The service starts a scout 3 s after it
  ended and the scout listens 45 ms later, so a restart's gap is about 3.3 s. The event
  `machine_entry_wait` names the output and says how long it waited, how many times it
  knocked and whether the entry took the request in the end. A machine that is off
  (no route, a connect that times out) is not waited for, nor is a server of another
  kind (an engine). A refusal of the entry (404, 503) is its answer.
  Until 2026-11-08 the request went straight to a running copy on its own port instead
  (`machine_entry_spare`, the owner's decision 3 of 2026-10-12). The cells listen on their
  machine's loopback since step 7 of Papyrus `caravan-scout-port-lease`, and that way is
  closed; `copyPorts` stays on the output as what says that a copy runs.

## `rust/crates/wire/src/body.rs`

A request's body, taken off the connection whole before the request goes on:
by its `Content-Length`, or chunk by chunk when the client sends it so
(`Transfer-Encoding: chunked` — curl uploading a pipe, a client streaming a
file it does not measure first). Until 1.3.505 the proxy read the length alone:
a body in chunks went upstream as none — a cell was asked an empty question, a
consumer of the entry was told its request was neither JSON nor a form — and
the chunks were left unread on a connection the answer then closed.

The body goes upstream with its own length: the client's framing stays behind
(`Transfer-Encoding` and `Trailer` are hop-by-hop), and a
cell's request carries the length of the body that goes, not the client's, which a body in chunks lies
about or lacks, and which a body the caravan rewrote (`ChatLevers::for_cell`, an
engine's model) no longer matches. A cloud request says its own too.

No limit on the size: a body by its length never had one, and one for chunks
alone would make the two ways answer differently. A body that cannot be read as
the request says it is sent — a chunk size that is not hex, a chunk that does
not end where its size says, a body that ends early, a `Content-Length` that is
not a number or is given twice differently, a transfer coding other than
`chunked` — is `BodyError::Malformed`: the entry answers 400 in OpenAI's words
(`OpenAiError::broken_body`); the journal has it as
`blocked` (`entry:broken-body`), the connection closes with
the answer, and the upstream is never asked.

- Owns: reading one request's body.
- Key names: `RequestBody::read`, `BodyError`.

## `clock.rs`

Where one request's time went. `durationMs` and `firstByteMs` mix the
caravan's own work with the model's and the network's; `RequestClock` splits
them, and the result row carries its `as_json()` as `latency`:

| Field | What |
|---|---|
| `prepMs` | the time before its first upstream attempt: routing, translating the body, the journal, and for a row of a machine its model's queue (a pool's route is admitted at once, and the wait is the leg's, `Exchange::serve`) |
| `connectMs` | opening the upstream connection (TCP, and TLS for a provider); `0` when a kept connection was taken |
| `connReused` | whether it was a kept one; `null` for a cell, where nothing is kept |
| `headersMs`, `firstChunkMs` | from the request sent to the answer's headers and to its first body bytes |
| `cpuMs` | processor time of the request's thread, the whole request |

Connect, headers and first chunk belong to the leg that answered. A mark that
never happened stays `null`: a request the caravan answered itself has no
connect time. A request refused before an upstream (blocked, gone while
queued) carries no `latency` at all. Both clocks are parameters: its tests move them by hand.

- Owns: the marks of one request.
- Key names: `RequestClock`, `Clock`, `SystemClock`.

## `rust/crates/net/src/kept.rs`, `exchange/answers.rs`

Connections to cloud providers kept between requests. Each request used to
open its own and close it after one answer: a TCP and a TLS handshake every
time, about 52 ms from the controller's machine to OpenAI and 91–122 ms from
the NAS (measured 2026-10-07). A cell is not pooled: its connection costs a
fraction of a millisecond, and the proxy cancels a cell's generation by
tearing its socket down.

`KeptConnections::take` hands out a kept connection to the same scheme, host and
port when one is open and quiet, else the caller opens a new one. A connection comes back
(`Exchange::keep_connection` → `give_back`) only after a clean relay — the client still there,
no stop from the board reached it — and only
when its answer was read to the end and neither side asked to close it. A
stream's closing bytes are drained on a thread of their own, for at most
1 s of silence and 64 KiB, so a client never waits for
them. A kept connection is dropped instead of handed out when it sat idle
longer than `IDLE_SEC` (60 s; Cloudflare, in front of chatgpt.com and
api.openai.com, closes an idle connection after 400 s, measured 2026-10-07) or
when the provider closed it meanwhile — its socket turns readable. At most
`PER_HOST` (8) idle connections are kept per provider; idle ones are swept on
every take and give back. `Stream::is_stale_error` names the failures of a kept
connection the provider closed under a request: `ProviderCall` sends the
request again on a fresh connection, once.

- Owns: the idle connections.
- Key names: `KeptConnections` (`take`, `give_back`), `Stream::is_stale_error`, `Exchange::keep_connection`.

## `exchange/`, `upstream.rs`, `provider_call.rs`, `provider_request.rs`, `relay.rs`

`Exchange` walks one request down its pool's rows: the lifecycle above, the queue + next-row loop (`Walk`: what it tried,
how many legs, at most 16), upstream forwarding (a machine's model or a cell by `UpstreamCall`; a provider with credential
resolution and protocol translation by `ProviderRequest` and `ProviderCall`), streaming relay with keepalives and stop
checks, error encoding (JSON or in-band SSE `error` event depending on whether headers already went out), and the
always-run `finish`. It also holds the "Loading model" 503 retry window. It takes the place of `proxy()`, the 1 170-line
function of the Python: each part is another object's, and this one says their order. The key a client presents to the
caravan (`Authorization` / `X-Api-Key`) opens its route and stays with the caravan: it reaches neither a cell nor an
engine nor a machine's entry (it used to reach a cell as it was, until 2026-09-26). A cell is reached at its machine's
address and port with no key of its own. A request routed to an engine's model (`upstreamType` `engine`) goes to the
engine like a cell's, with the model's name in the body (`model_named`).

- Owns: the request's walk, per-request phase transitions
  (`received → queued → upstream → streaming/reading → finished`), spend/timings attribution on the result row.
- Key names: `Exchange` (`run`, `machine_leg`, `cloud_leg`, `finish`), `Asked`, `UpstreamCall`, `ProviderRequest`, `ProviderCall`,
  `Flavor`, `Facts`.

## `listener.rs`, `drain.rs`

The entry's one socket: `Listener::bind` takes the port from the controller's word (`CARAVAN_RUST_ENTRY_PORT`), waiting up to
15 s when it is in use (it is the old version's until that one sees this one), and `serve` starts a thread for each
connection. `Drain` looks every 2 s at the program's own file and at its parent: when the file changes, or the process
named by `CARAVAN_PROXY_KEEPER` is its parent no more, this process stops taking connections,
lets the port go and answers what it has to the last byte, for two hours at the most, or until its container ends
([operations.md](operations.md#deploy)). Started by hand, with no keeper named, it has nobody to lose. The controller moves or closes the entry by replacing this process. The `portClosed` of a route means nothing here: no route has a port.

- Owns: the socket, the count of open connections.
- Key names: `Listener` (`bind`, `serve`), `Drain` (`why_leave`, `kept_by`, `program_changed`, `begin`, `connection`).

## `front.rs`, `connection.rs`, `rust/crates/rules/src/entry_models.rs`

The one entry for consumers with keys (visumap `caravan-single-entry`): one port
behind the DSM proxy, `caravan-api.example.org`, instead of a port per agent.
`Front::before_body` reads the presented key (`Authorization: Bearer`, else
`x-api-key`) and finds the route that carries it as `apiKey`
(`rust/crates/rules/src/key_entry.rs`).
No key, or a key no route carries: 401; a key two routes carry (a hand-edited
file — the board refuses it on save): 401 too, not 409, which an OpenAI client
retries. Every refusal is in OpenAI's shape (`rust/crates/rules/src/openai_error.rs`) with an
`X-Request-Id`, and a `blocked` event with the reason `entry:<why>` under the
consumer's name once it is known (`rust/crates/rules/src/entry_refusal.rs`).

- **A consumer of the entry** (a route of kind `"consumer"`, since 1.3.466) is
  served as a company's gateway serves its clients. Since 1.3.675 its key calls
  every pool and every model that runs, but what is blocked for it (`deny` on
  its route: a pool, a model, an account or a machine whole — `ClientDeny`,
  `rust/crates/rules/src/client_deny.rs`; the owner, 2026-10-27: "every client we make
  has every model and every pool") — and no router ever decides for it.
  `GET /v1/models` lists the pools by their names, in the board's order, then
  the models that run, each by its own name (`EntryModels.models`), in OpenAI's
  model shape (each window the pool's against the consumer's own limit, absent
  when neither is known). The models a client calls without a pool are
  read by `EntryModels` (`rust/crates/rules/src/entry_models.rs`) from the routers' outputs,
  the cloud file and the credentials: each machine model one of whose copies
  runs (`copyPorts`), then each model added to an account that can be called,
  all of them whatever they do; an engine's model and a cell's own output are
  not in it. A name in two places is two models, each with its place in
  brackets (`gpt-6-luna (chatgpt-subscription)`), read over every model known,
  so it does not change when the other place stops. Each is a pool of one row
  under an id no stored pool has (`live:mm:<hash>`, `live:acc:<account>/<model>`); a model under a
  pool's name is the pool's. `GET /v1/models/<id>` answers that model, the id
  compared decoded and spelled as the list spells it. A request's `model` picks
  the pool or the model, as OpenAI's API picks a model: a request naming none is
  400 (`you must provide a model parameter`); a pool or a model blocked for the
  client is 403 `model_not_allowed` ("it is closed to this client on the
  caravan's board"); a name it knows that does not run now is 503
  `model_unavailable` ("is not running now"); a key with nothing to call at all
  is 404 `model_not_found` with the words that the operator starts a model or
  unblocks one; any other name is 404 `model_not_found`. A model blocked for the
  client that one of its pools calls is reached through the pool: the pool works
  whole. A consumer of the forms before 1.3.675 (`set`, `pool`, `models`) is read
  as one that blocks nothing until the controller rewrites it
  (`ConsumerDesk.migrate`). The built-in clients, Open WebUI and opencode
  (2026-10-27; the route's `builtin`, `BuiltinClient`), call as any client does.
  The pool found, the request is served by `Exchange` with the consumer's dialect
  (`OpenAiDialect`). Only inference paths are routed
  (`rust/crates/rules/src/request_kind.rs`); any other path is 404
  `Invalid URL (METHOD /path)`. The `model` is read from a JSON object, or —
  where OpenAI's API takes a file, a recording to transcribe on
  `/v1/audio/transcriptions` — from a form's field (`multipart/form-data`,
  since 1.3.501; `rust/crates/rules/src/request_fields.rs`: its text fields found by
  the boundary, the file stepped over, never decoded; a part ends where CRLF +
  `--` + boundary begins, the same law as the cells' reader `Form` in
  `cells/cell_base.py`, and both are held to one table of forms,
  `scripts/_multipart_cases.py`, since 1.3.602), and the body goes on to
  the pool's row byte for byte. A body that is neither is 400 `unreadable`, its
  words naming both. The body comes by its length or in chunks
  (`rust/crates/wire/src/body.rs`, 1.3.505); one that cannot be read as it says it is sent
  is 400 "The request body cannot be read: <why>." A subscription's row serves a chat alone
  (`RequestKind::is_chat`, `PoolSteps`): a recording passes it by for
  the pool's next row, and a pool none of whose rows does the work is 400
  `unsupported` — "The model `X` does not serve POST /path" — never a wait.
  Since 1.3.502 each model of the list says what it does
  (`rust/crates/rules/src/model_kind.rs`): OpenRouter's
  `architecture` and the caravan's `caravan` — `jobs`, an ear's `languages`
  and `max_audio_ms` — from what every row of its pool that may serve does
  (a subscription's chat takes pictures; a cell's facts ride on its router
  output; since 1.3.631 an account's row does what its type fixes — a
  subscription, an Anthropic key and a DeepSeek key chat — or what the operator said of its
  model, `modelJobs` in the cloud file read by `AccountModelJobs`,
  `rust/crates/rules/src/cloud_models.rs`, and a key's model nobody said a word
  of says nothing). A pool of known kind refuses a request for other work before
  sending it, 400 `unsupported`; an unknown or mixed pool leaves it to its
  rows. A pool's window counts its cells' (`CloudPools.window` with the
  outputs' `contextLength`).
  One more question is answered (since 1.3.495): Ollama's `POST /api/show`,
  which Hermes asks for a model's window — the consumer's pool in Ollama's
  shape, the window under `model_info` `caravan.context_length` and as
  `num_ctx` in `parameters`, both absent when the pool states none. The
  entry's refusals carry the request's method in the journal: Routing's
  client card lists a client's errors of the last 30 days from it
  (`rust/crates/admin/src/cloud/misses.rs`). Routing's own tests of a client
  carry `X-Caravan-Probe` (`KeyEntry.PROBE_HEADER`); heard from this machine
  itself, not through the DSM's proxy, such a request is journaled under the
  client `routing-probe`, and the client's errors list leaves it out.
- **An agent of the old kind**, with its port's key, gets a 403 since 2026-11-02
  (`entry:not-a-consumer`): the graph that served it left with the Python. It takes a key of a client.

A streamed answer carries `X-Accel-Buffering: no`
(`ClientSide::open_stream`), so the DSM's nginx passes the tokens on
as they come instead of in batches.

- Owns: nothing (the route is per request).
- Key names: `Front` (`before_body`, `with_body`, `plain_target`), `Connection`, `KeyEntry`, `EntryRefusal`, `EntryModels`.

## `rust/crates/rules/src/dialect.rs`

How a request is told its failures. `OpenAiDialect` is a consumer of the entry's way: every failure in OpenAI's shape and
the caravan's words; of a provider's headers only `Content-Type`, `Content-Length` and `Cache-Control` pass, plus its own
`X-Request-Id`; a client that did not ask for a stream gets one JSON chat completion where the provider streams anyway.
`Exchange` asks it at each such point (`failure`, `stream_failure`, `header_ok`, `answer_error`). There is no other dialect:
a port's way left with the ports.

- Owns: nothing.
- Key names: `OpenAiDialect`, `Told`.

## `rust/crates/rules/src/openai_error.rs`

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
only a word is told (`OpenAiError::clean_code`: letters, digits, `_` `.` `-`,
64 at most), and a provider's code stays at the provider.

- Owns: nothing.
- Key names: `OpenAiError` (`no_key`, `wrong_key`, `shared_key`,
  `unknown_model`, `invalid_url`, `unreadable`, `no_pool`, `paused`,
  `limit`, `unavailable`, `unsupported`, `closed`, `upstream`, `duration`).

## `rust/crates/rules/src/upstream_type.rs`

The kinds of upstream a router output names, as one table (1.3.506):
`llama` — a cell, one model on its own port, its places its /slots; `engine` —
a model of an engine next to the cells (Ollama, LM Studio), many models on the
engine's port, the request naming its model, its places the policy's;
`machine` — a model of a machine's entry (its scout), many models on the
scout's port, the request naming its model, its places the scout's word and a
queue of its own; `cloud` — a pool or an account, no places counted. A type
outside the table is read as `llama`, as the file always was. The controller
writes the type (`RouterDsl`, `rust/crates/admin/src/proxies/dsl.rs`), and the proxy's
queue and places read it; the board's twin is
`OutputCells.NAMED` (static/js/output-cells.js).

- Owns: nothing.
- Key names: `UpstreamType` (`of`, `word`).

## `rust/crates/rules/src/chat_levers.rs`

The standard fields of a chat request that steer how a model answers —
OpenAI's `reasoning_effort`, `verbosity` and an image's `detail` — said to the
row that serves (1.3.501; the owner, 2026-10-12: a client keeps to OpenAI's
API). `ChatLevers::for_responses` gives the subscription's translator
(`ChatToResponses`) `reasoning.effort` when the client asked
for an effort and `text.verbosity` always ("low", as before, when it asked for
none or a word it does not know); `ChatLevers::detail` an image's `detail`
("auto" unsaid). `ChatLevers::for_cell` tells a llama.cpp cell "no thinking" —
`chat_template_kwargs.enable_thinking: false` — when a chat asks for the effort
"none" or "minimal" and the client has not set `enable_thinking` itself;
`UpstreamCall` applies it on every leg to a machine (an engine's leg names its model
too, `model_named`). Anything it does not change goes as the same bytes.
gemma-4 through the entry spent a short answer's every token on thinking
before it (2026-10-12).

`ChatLevers::EFFORTS` is OpenAI's scale of efforts, from "none" to "max", and
`ChatLevers::nearest_effort` the effort of a list nearest to the one asked on it
(of two as near, the lower; a word off the scale has none) — what
`EffortFit` reads a provider's list against.

- Owns: nothing.
- Key names: `ChatLevers` (`EFFORTS`, `effort`, `nearest_effort`, `verbosity`, `detail`, `for_responses`, `for_cell`).

## `rust/crates/rules/src/effort_fit.rs`

The reasoning effort a provider's model takes, learned from its refusal
(1.3.644). Hermes asks "none" for its short calls; the subscription's
gpt-6.1-sol takes low to max and refused each such request with a 400 that
lists them (`param: reasoning.effort`, "Supported values are: 'low', …").
`EffortFit::offered` reads such a refusal — a 400 whose error names the
effort's field (`reasoning.effort` or `reasoning_effort`) and lists values —
and `learn` keeps the list by provider host and model. `Exchange::cloud_leg` then asks
the same leg again, once a request and only before output, and `fit` sends
every later body to that model with the nearest effort of the list, in the
field the body said its own in (the Responses API's or Chat Completions').
The record says what was asked and what was sent (`effort: {asked, sent}`),
and the journal says when a refusal taught a list (`effort_retry`: host,
model, asked, sent, takes). Not swapped: a model whose list is not known, an
effort the list takes, a word off the scale, a body that is not JSON or says
no effort. The lists live in memory: a restarted proxy has forgotten them,
and the first refusal after it teaches them again.

- Owns: the lists by (host, model), under a lock.
- Key names: `EffortFit` (`offered`, `fit`, `learn`), `EffortSwap`, `EffortLesson`.

## `main.rs`

The entry point: the settings from the environment (`ProxyConfig`, exit code 2 when they do not read), the entry's port
(`Listener::bind`, exit code 1 when it cannot be had), then the state writer, the pool watch (`PoolWatch::start`) and the
places' watch (`PlacesWatch::start`), and `Listener::serve` on the main thread.

The process says which code it runs in the state file: `sourceCommit`, the commit it was built from
(`CARAVAN_BUILD_COMMIT` at the build), and `pid`. A new version is not decided by reading them: the controller starts what
the release's file is, and the old process sees its file change.

- Owns: thread startup order.

## Invariants for contributors

- **File contract, not linking.** `admin` and `proxy` never depend on each other — the programs only
  communicate via `config/agent-proxies.json` (the controller's; the proxy reads it),
  `state/agent-proxy-state.json` and `logs/proxy-events/*.jsonl` (the proxy's; the controller reads them), plus
  `config/cloud-providers.json` (the controller's, the proxy reads it) and `secrets/provider-secrets.json`,
  whose one writer in both programs is `CredentialVault`. Shared code goes in the library crates.
- **No global mutable state.** Everything a request changes is a field of `Proxy`
  (`scripts/check_rust_contract.py`), and `rules` takes its time and its input as parameters.
- **Atomic writes everywhere a reader races.** The state file has one writer and goes through
  `files::AtomicFile`; provider secrets are written by `CredentialVault` only, under its document
  lock, atomically with 0600. A journal's row is one write with `O_APPEND`.
- **A panic ends one request.** `Ending::guarded` and `panic = "unwind"` in `rust/Cargo.toml`: a bug ends the request it is
  in, which still gets its record, its answer and every place it held given back.
- **Few crates, no runtime.** Every third-party crate has its reason in `scripts/check_rust_contract.py`. Threads, no
  async: a thread does what is written, and a client's leaving is looked at, not cancelled from outside.
- **Telemetry must never break traffic.** `Recorder::event` and `Proxy::write_state` count their own
  failures instead of failing a request; keep new bookkeeping on that side of the line.
