# Pools

A pool is what a client's requests go to (the owner, 2026-10-12): built in Routing, an ordered
list of **rows**. Each row is an output, cabled to a model in Routing's right column — a
subscription's or a key's model (an account and one model), a model of a machine — "machine + model"
by name, `mm:<id>` (1.3.506; every row of a machine's cells since 1.3.655) — or an engine's model
(`eng:<id>`). A cell is no row of its own since 2026-11-07: it holds a port only while it runs, and its machine's model
reaches it (Papyrus `caravan-scout-port-lease`); a row of before that named `srv:<port>` is cabled to that cell's model. A row
with no cable yet is open. The proxy tries the rows
from the top. One pool may mix a cell and a subscription. A pool's name is the model id its clients
see in `/v1/models`, so two pools cannot share a name, compared without case: the board refuses a
name another pool carries, and "＋ New pool" names a new pool "Pool", "Pool 2"… until the operator
types one.

A client of the entry sees **every pool and every model that runs**, but what is blocked for it (1.3.675; the owner,
2026-10-27: "every client we make has every model and every pool; the pools pass for models of their own; sets seem not to be
needed; on a client we set which models or pools it may NOT have"). The client's `GET /v1/models` lists the pools by name, then
each model that runs under its own name — a machine model one of whose copies runs, a model added to an account that can be
called; one name in two places is two models, with the place in brackets — and a request's `model` picks one, as OpenAI's API
does. A model under a pool's name is the pool's: the pool's name wins. A request with no model is 400, a name the caravan does
not have is 404 `model_not_found`, a model it knows that does not run is 503 `model_unavailable`, and a pool or a model blocked
for the client is 403 `model_not_allowed` (`rust/crates/rules/src/client_deny.rs`, `ClientDeny`; operations.md "What a client sees"). A
model blocked for a client that one of its pools calls is still reached through that pool: the pool works whole (the owner's
choice).

What is blocked for a client is a list of keys: a pool, a model (a machine's or an account's), or a whole source — an account or
a machine. A new client blocks nothing ("everything, at once"); at the move to this form every client dropped its set and started
with nothing blocked, and Routing showed the move once, offering to delete the pools that became twins of their model. The
built-in clients, Open WebUI and opencode (the owner, 2026-10-27), are clients like any other: made at install, they stand first on
the main board and in Routing (`rust/crates/admin/src/common/entry.rs`, `BuiltinClient`; `rust/crates/rules/src/entry_models.rs`, `LiveEntry`).

## In Routing

Routing (`/routing`, pool-board.js) is three columns (1.3.675; of the mockups the owner chose В2): the clients, the
pools ("ID (Pools)": a pool's name is the id of a model that a client puts in `model`, and its card says `id:` before the name; only
the pools' column and cards carry the word, 1.3.591) with **«Напрямую»** (Direct) on their top, and the models. The cables show only
for a card pinned by a click, for a cable being drawn, and while requests run (the owner, 2026-10-27: "the cables only when we draw
them, OR when a block is selected, OR when requests run"), with drops running along them; none crosses a column. A card says its name and what is news about it (a client refused, a row serving,
a cell off) and no more: the rest stands in **the strip** under the columns (1.3.531–538; the owner,
2026-10-13: "crowded and motley", and of three mockups he chose "details in a strip below"). The strip
says what the pointer is on — or the card pinned by a click: its name, its route across the columns (the clients that called
it, its pools, its models) and its details. It is there only
while a card is pointed at or pinned; with none it is hidden (2026-10-14: "do not show the bottom strip
when nothing is pointed at or selected"). Pointed at, it is for reading and lets the pointer through, so
a card under it can still be pinned; pinned, it is for using, and Esc or a click on the card lets it go.

- **A client's card** is its name, the tail of its key, how many models it sees ("Sees all 20", "Sees 17 of 20"), a badge
  "⚠ N" — how many times it was refused in the last 30 days —, a chip "⊘ name" for each thing blocked for it and "＋ Block". "＋
  Block" opens the window of what can be blocked for the client: each source — an account, a machine — with a box that blocks all
  of it and its models under it, then the pools; listed at once are the models that run and the ones blocked already, a search
  finds the rest (a stopped model can be blocked before it runs); a model blocked for the client that a pool still calls says so;
  each tick is saved at once. A model or a source blocked for some clients says for whom on its own card ("⊘ Bot"). The entry's
  address stands once under the Clients head, with ⧉. A click on a client's card draws its cables to what it called over the last
  three days. Its strip has the links to what the client gets there by GET — `/v1/models` and the model chosen beside it —
  asked by the controller with the client's key (a browser opening the entry's address itself has no
  key and is refused), the buttons that send a short test as the client for each kind of work by POST —
  chat, responses, speech to text, text to speech, pictures, embeddings; a window shows what went out
  and what came back, and a picture asks first, it may cost money — and the client's errors of the last
  30 days: what it asked, the answer's status, how many times and when.
- **A pool's strip** has its rows as the proxy says them — the rank, the model and where it stands,
  the state in words, and under a row when the pool goes on to the next one — then "＋ row", "Pool
  settings" and "Switch history" (below). An empty pool keeps its "＋" on its card.
- **«Напрямую»** stands on the top of the pools' column and stays there while the pools scroll: a row for each model a client
  calls by its own name, without a pool, while such a request runs — all of them, however many (the owner: "let all be seen") —
  with who calls it, and, while a client or a model is pinned, the models called straight over the last three days. A client's
  cable runs to the row, the row's on to its model, so no cable crosses the pools.
- **A model's strip** has its levels (below) and, for a machine's cell, its state in words.

"＋ New pool" makes an empty pool, its name chosen in the field; "＋ row" (in the pool's strip) adds an
open row; a row's output is cabled by dragging from its dot onto a model on the right. A cable pulled out of the strip comes out
of its top edge. A click on a row's cable cuts it after one question that names both ends; a client's cables are what it called,
not links to cut.
⠿ carries a row to another place (the order is the pool's order); ✕ removes a row or deletes the pool —
when old cables or rules on a router still lead to the pool, the window asks where they go, onto
another pool or disconnected. ⧉ (1.3.682) copies a pool: its rows in their order and its settings, right
under it, named after it with " copy" (" copy 2"… when taken), the name chosen in its field to type over. A pool's name is what
clients call it by, so no client asks for the copy until it is named.

**Where the cables go** (1.3.503; the owner, 2026-10-12: "it is hard to see where the cables go; a
cable cannot be drawn to a cell off the screen; pools of one model and of several look the same"):

- The pointer over a card lights its path — up to the clients that called it and down to the models it
  reaches, never sideways — and takes nothing away. A click on a card's free place pins the path: the
  rest of the board steps back and the path's cables are drawn; a click on it again, or Esc, lets it go.
  Until 1.3.676 pointing dimmed the rest too (the owner, 2026-10-27: "do not make the other blocks
  transparent when I only point at a block — only when I chose one").
- The cables and the frames are one quiet colour, and only the lit path has the accent. Pools had a
  colour of their own from 1.3.503 to 1.3.530 (the owner, 2026-10-12: "to see where the cables go"); on
  an eleven-pool board three of them shared one, and the lit path shows it better (2026-10-13: "motley").
  A card's tools — ✕, a row's ✕, the grips ⠿ — show while the pointer is on the card.
- A click on an output — a dot, a "＋" row, a model's ⠿ — opens a list of the places its cable can go,
  with a search: a row's models (every account's models on their cards
  and every machine's cells), a model's pools. A place a cable goes to now is ticked and cannot be
  picked again — for a row, every model its pool holds. A press that travels more than 5 px is a cable,
  as before.
- A cable carried near the board's top or bottom edge (or its sides) scrolls the board under it.
- A model's ⠿ carried onto a pool adds it as the pool's last row; carried onto the Pools column, off any
  pool, it makes a pool of its own, named after the model. A pool still under the board's name
  ("Pool", "Pool 2"…) takes the name of the model its first cable reaches (" 2" when the name is
  taken); a name the operator typed is never taken over, and a pool once cabled keeps its name.
- A pool of one row is drawn as one line under its name, with no box and no rank (1.3.543). A pool of two rows and
  more is a ladder of rows in boxes, "N in turn" in its head, each row a number, the model, where it stands and how
  it is. When the pool goes on from a row to the next one stands in the pool's strip, under the row: a
  subscription's model when its switch level is left in a window ("next when 30% (5h) is left"), a cell when it is
  busy or silent, anything else when it refuses.
- A row says its state by a dot and a word, in the state's colour, only when the state is news — serving (green), a level
  reached, closed, off (amber), missing (red), a sign-in asked for, a proxy that is silent. A row that is fit and waits
  its turn, or that the proxy has not asked yet, is a bare dot (filled, hollow), with the words in its title and, in
  full, in the strip. A silent proxy and a reason nobody knows keep their word: they are not "no news". The row's
  grip and ✕ take no room until the row is pointed at, so the model's name and place are not cut for them.
- "⇅ Arrange" puts each account's models in the order the pools' rows name them: the cables then run alongside one another more
  than across.
- The cards of Clients and Pools are carried to another place by the ⠿ in their head (Alt+↑/↓
  moves a focused one a place). The pools' order is the file's own; the clients' is kept
  in the board's layout, beside the server cards' order, and the main board's clients follow it.

**Pool settings** in the pool's strip set the window the pool states to its clients in
`GET /v1/models` (`context_length`): a number, or blank for "not stated", and the switch "use the
smallest window its steps' models report" — then the smallest window the enabled rows name: a
provider's for its model, a machine's cell's the window it serves (since 1.3.502, from its router
output); when one of them names none, the number written stands, or nothing (the rule is
`CloudPools.window`, the proxy's and the board's). Under them the pool says what it states now: "The pool states 272K to its
clients", or that it states none. Nothing stated is the default: a client then keeps its own idea
of the window. The figure in the "＋ model" list beside each model is the provider's own window
for that model, read from its catalogue — not the pool's.

Beside the pool's name stands what its rows do together (1.3.502, `rust/crates/rules/src/model_kind.rs`):
💬 a chat, 🖼 beside it when every row takes pictures, 🎧 speech to text, 🎧🌐 speech to a
translation, 🔊 speech, 🧬 embeddings — the languages in the hint — and ⚠ when the rows do different
work. It is what `GET /v1/models` tells the
pool's clients: OpenRouter's `architecture` (`modality`, `input_modalities`, `output_modalities`) and
the caravan's `caravan` (`jobs`, an ear's `languages`, its longest recording `max_audio_ms`). A pool
advertises only what every row that may serve does; a row that says nothing of itself makes the kind
unknown, and a mixed pool tells its clients nothing. That is the advertised promise, not the served
one: a request is answered by one row, so an image goes to a row that reads images even when the pool's
advertised kind is text alone. A request for work no row does — a chat to an ear, a recording to a chat
model — is refused 400 before it is sent.
Image parts have a separate content-based refusal when no row that may serve takes them; an unknown promise is not a refusal. Routing has one reader setting for the whole board, below Direct, even with no pools. Drag its output to a model to name it; click its cable to clear it. The board checks the model's image-input promise, but requests do not call the reader yet. The rule and future describe-node design are in [Images for text-only models](vision-describe.md).

**Subscriptions with a key** (1.3.687; the owner, 2026-10-31: "popular variants with subscriptions, the Chinese ones too"). Beside the ChatGPT subscription, which signs
in, the provider picker has a group of plans that sell a flat month and give a key: Kimi Code, GLM Coding Plan, MiniMax M Plan, Qwen Token Plan and OpenCode Go
(`CloudSources.PLANS`, addresses from their documentation on that day). To the proxy each is a key account at an OpenAI-compatible address, the plan's own and not the
provider's pay-per-use one: a plan's key works nowhere else. The window says a plan's rules before its key is typed and links its page, because none of their documentation
names an address that reports the limits, so there are no meters. The rules are the providers' own (1.3.692; the window says them: `cloudNoteKimi` and its neighbours in `static/js/i18n/`), and they bind the
owner, not the proxy: Kimi and Qwen are for interactive use only, with no scripts or batch runs; GLM only in its listed tools, and the caravan is not one of them; MiniMax
designs its plan for individual interactive use. Its spend reads as
what it would cost at API prices, and no dollar credit is asked. DeepSeek is not among them: it sells no subscription, and stands with the keys, saying its balance.

**What a provider hears** (1.3.692, `rust/crates/rules/src/client_name.rs`). By default, each client as the client named itself: its `User-Agent` and session headers go on as they
came, and one that names itself nothing stays unnamed. The head of Routing's Clients column can set one name for all of them (`clientName` in the proxy's policy, `rust/crates/rules/src/client_name.rs`; the
owner, 2026-10-31: "let us present ourselves as one; it is purely for the home, and if they ban us, let them"). It replaces the `User-Agent` and the headers that name a client (`HTTP-Referer`, `X-Title`,
`X-OpenRouter-Title`), on the requests and on the caravan's own calls, and no more than that: a session header stays, and so does what a client's library sends of itself. It is off unless set, because
Kimi calls altering a client's name a violation that may suspend the membership, while several tools on one account are normal to it. The ChatGPT subscription's `originator: pi` stays what it was: whether
ChatGPT takes a request without it can be tried only on a real subscription. The calls to `auth.openai.com` keep what they had, since a failed renewal would stop the subscription: sign-in by code and sign-out say
`lama-caravan/<version>`, while trading a code and renewing a token name no `User-Agent` (until 2026-11-02 they went as urllib's own `Python-urllib/3.x`), and all of them carry the `client_id` of OpenAI's Codex. Nothing of the home goes to a provider, with a
name or without one: not `X-Forwarded-For`, `X-Real-IP` and `X-Forwarded-Proto`, which the NAS's nginx adds and the caravan reads (`KEPT_OUT`, `rust/crates/proxy/src/provider_request.rs`), and not the client's label on its route.

An account's row says what its model does (1.3.631). A ChatGPT subscription's, an Anthropic key's and a DeepSeek key's
models chat: their type serves nothing else. A key of another type — OpenAI, OpenRouter, Ollama, a
custom one — serves a chat, an ear and a voice at one address, and its list says nothing of a model's
work, so the operator says it: **What it does** in the model's strip — 💬 a chat, 🧬 embeddings, 🎧
speech to text, 🎧🌐 speech to a translation, 🔊 speech, or "not said". It holds in every pool whose row
names the model, and its card wears the marks. A key's model nobody said a word of wears a quiet "?":
its pool's kind is unknown, the list says nothing of its work, and the provider decides what it
serves. Until 1.3.631 every account's row was a chat, and a pool of one key row with a recogniser
behind it was refused every recording.

Each row says the proxy's word on it, never a guess: serving now, switch level reached, stop level
reached, limit reached, payment needed, sign-in refused or missing, model not listed, chat only,
limits unknown, switched off, a cell that is off, a model that is gone, busy (giving way), failed
(next row). A row whose model or cell is gone says so in red and has no cable. A row whose cell does
not run now says so before the proxy's word (1.3.504): "cell off", starting or stopping — and failed,
in red — as the controller sees the cell at this moment; its cable stays.

The right column's cards — the accounts and the machines, in one list — change places by their ⠿ (1.3.683); a machine may stand above
a subscription. The order is one for every browser, kept on the controller with the machines' places (`layout.serverOrder`), and while it
names none of them the accounts stand first.

The right column lists each account's models — only the ones added to it (the owner, 2026-10-12:
"only the ones I added"), never its whole catalogue. "＋ model" in an account's head (quiet until the card is
pointed at) opens the account's list in its card, searched as it is typed; a press puts a model on the card, and an id the
search does not find can be added as it is typed. A model a row is cabled to is added with the cable
and stays when the cable goes; ✕ (on hover) takes a model no row names off the card, and its levels
stay for when it comes back. The models the rows named before 1.3.491 were added once, at the first
start. The column also lists each machine's cells, the stopped ones no row names folded under one
button. A machine's head says how many of its cells are in which state ("3 running · 5 stopped").
A model's card is a line — its name and, at the right, what is news: what a key's model does (its marks, or "?" while
nobody said it), its switch level ("switch 20% (7d)"),
a chip when its pool has stepped aside ("↓ yielding") or stopped it ("■ stopped"), its ⏱ while a schedule is on,
"in no pool" when none uses it; its ⠿, ✕ and a quiet ⏱ show when the line is pointed at. The pools that use it are its
route in the strip. An account's card in Routing sets nothing of the account up (the owner, 2026-10-12): it says the
account's state, its limits once — the provider's word when a limit is reached, and each window as one small
bar with what is left, a red tick where a model of the card stops (when the window resets: in the bar's hover
and in the strip) — its tripped endpoints and the last day's routed errors. The account's window
⚙ and its saved resets (`↺ N`, below) stand on the main board, in its provider's block.

## The levels: on the model

A subscription's model has **two levels** on each of its account's windows (the owner, 2026-10-12: the
levels stand on the models, not in a pool), two triangle handles to drag (a red one up for the stop, a
yellow one down for the switch). The account's card draws the 5H and WEEKLY windows once, small; the same bars
with the model's own handles stand in the **model's strip** (1.3.534), and a model whose pool has stepped
aside or stopped it wears a chip on its card:

- ▲ **stop**, red, under the bar: the share of the window the model never spends. When only that much is left, its rows
  do not serve until the window resets; with no other row, the caravan answers 429 itself.
- ▼ **switch**, yellow, over the bar, never below the stop: from that share on, a pool sends requests to its next rows
  first, and the model still serves when none of them can.

A model's levels hold in every pool whose row names it. A model nobody set levels for stops and
switches at 10% on each window — what a subscription spent to its end before anyone moved a handle
would otherwise have cost. A level dragged to 0 is lifted, and a lifted level is kept as a choice.
Dragging the stop past the switch takes the switch along; the switch rests on the stop.

## When a model is open: its schedule

Each model in Routing's right column has a ⏱ beside its name (the owner, 2026-10-12, visumap
scheme caravan-model-schedule): a click opens a window with a switch, a week of hours painted with
the pointer, as the schedule node of the old router canvas had them, and the same hours as windows with exact
times. A window is days of the week and a time from–to; one that runs past midnight belongs to the
day it starts on (Friday 22:00–08:00 is Friday night), and from equal to to is a whole day. The
hours are the caravan's own — the zone the controller runs in, named in the window — not the
browser's. While a schedule is on and none of its windows is open, the model is **closed**: the ⏱
says until when, and so does every pool's row of it. A schedule switched off keeps its windows, and
the model is open at any time; a model with no schedule is open at any time, as before 1.3.498.

A schedule is the model's, the same in every pool whose row names it — a model of an account
(`acc:<account>/<model>`) or a machine's model (`out:mm:<id>`). A pool needs no schedule of its
own: it passes over the row of a model closed now and takes its next row (below). A pool whose every
row is closed answers 503 with the time the first of them opens. Step 1 of the scheme: a cell's
server is not started or stopped by its schedule yet — the pools keep to it, and the window says so
on a cell. A cell that changes its port takes its schedule along, as it takes its rows (below); a
cell deleted takes it away; an account deleted takes its models'. A model taken off the column keeps
its schedule, as its levels.

## The rules the proxy keeps

The proxy chooses per request (`rust/crates/proxy/src/pool_steps/mod.rs`). A row is passed by when it is switched
off or open, or when its model is closed by its schedule (no connection is tried); a subscription's or key's row when its account has no sign-in or key, cannot speak a
Responses request (an OpenAI-compatible key provider speaks chat only), is asked for anything but a
chat while it is a subscription (a recording, a text to embed: 1.3.501 — a pool of subscriptions alone
answers such a request 400, not a wait), rests after the provider
refused it for a limit (429 quota, 402 payment, 401 sign-in), is not listed by its provider any more,
or — a subscription — is at its stop level, out of its limit, or with limits that cannot be read now
(a failed reading is never zero usage); a local row when its cell is off (the output's health
verdict), its output is gone, or its cell is busy while a later row is free — a lone busy cell keeps
the request waiting in its queue. The pool takes the **first** row that fits: when an earlier row fits
again, the next request goes back to it. A row below its switch level still fits but gives way.

A request moves on to the next row that can take it when a row fails it before the first byte: a
limit (429, 402, 401), a connect error, a 5xx. A client's own error (4xx) is relayed as it came; a
response already streaming never changes rows; with no next row able to take the request, the client
gets the last row's own error. At most 16 rows are tried for one request. With no row fitting, the
proxy answers itself — 429 when every row is held by a limit or switched off by the operator, 503
otherwise — and names each row's reason and the earliest reset or opening; a pool with no row says
"add one". A client of the entry gets the same status in OpenAI's shape, with a `Retry-After` until
the earliest reset or opening and without the rows and accounts behind the pool
(`rust/crates/rules/src/openai_error.rs`). A pool whose every row is closed by its schedule tells the client
when it opens: "The model `Chat` is closed by its schedule until 2026-10-17 19:00 UTC+04:00". A Responses
request that refers to an earlier response (`previous_response_id`) is refused with 400 before a row is
chosen when the pool has more than one row: the conversation lives with one account.

The proxy publishes its last choice per pool, every row's reason and the last 50 switches in `pools`
in its state file; switches also enter the proxy's event journal. A restart clears the choices and
the rests; the next request reads the limits and chooses again.

## The file

`cloud-providers.json` keeps `accounts`, `pools`, `levels`, `schedules` and the board-wide `reader` (a model name or null) — every key beside the
accounts and pools named in one table for its readers and writers (`CloudFileKeys`, `rust/crates/admin/src/common/misc.rs`:
until 1.3.498 three lists named them, and a key one list lacked was dropped by the next save). A pool is `id`, `name`, `steps` (the
rows, kept under their old name: each `id` and `enabled`, and `accountId` with `model`, or `output`,
or neither for an open row), `contextAuto` and an optional `contextLength`. `levels` keeps the models'
pairs by account and model: `{"<accountId>": {"<model>": {"stopAt": {"<seconds>": pct}, "switchAt":
{…}}}}`. `schedules` keeps them by model key: `{"<key>": {"enabled": bool, "windows": [{"days":
[0..6], "from": "HH:MM", "to": "HH:MM"}]}}`, Monday 0, no days every day. A pool's id is its first name's slug; a row's id is its account's (`-2`, `-3` for the same
account again), or `r1`, `r2`… for a row made open. What is blocked for a client is `deny` on its route in
`agent-proxies.json` (`pool:<id>`, `model:<place>`, `account:<id>`, `host:<hostId>`); a route written before 1.3.675 kept `set`,
`pool` or `models`, which the controller drops once at its start (operations.md, "What a client sees"). Credentials stay in
`provider-secrets.json`, outside the topology and the logs.

A row may name a model of a machine's entry (`mm:<id>`, 1.3.506): the machine's scout serves its
models at one address by OpenAI's API and picks a running copy of the model a request names
(`rust/crates/admin/src/fleet/machine_models.rs`). The id holds no port, so a cell moved to another port, or a second
copy started, leaves such a row as it is. A model with no running copy answers 503 at once, and the
pool goes on to its next row; a busy one gives way like a cell, by the places its scout says
(docs/backend-proxy.md). A model none of whose copies runs or starts is marked as standing still on its
output, and a pool passes its row by without asking (1.3.655, as a stopped cell's since 1.3.645). In
Routing a machine's card lists its models, by name — no port — with the state its scout says and how
many copies serve it (×2); a cell has no row of its own since 2026-11-07. A model's name there is
its cell's `MODEL_NAME` — the cell editor's row under the runner, for every runner (1.3.507) — else the
cell's `ALIAS`, else one made of its model; two cells with one name on one runner are one model's copies,
and one name on two runners is two models, `<name>@<runner>` each (scout 2.39). A new name applies at the
cell's next start, when its scout learns it. "＋ Add model" does not say the port it takes: a model is
called by its name, and its cell's port stands in the cell's window (1.3.655).

Step 3 of the owner's plan (Papyrus caravan-scout-openai, 2026-10-26): the rows name the machines' models,
not their cells' ports (`rust/crates/admin/src/fleet/machine_rows.rs`). At the controller's start and on each machine's
report, a row cabled to a cell whose port one machine's entry lists moves to that machine's model; two rows
of one pool that come to name one model — its two copies — become one, switched on when either was; a
schedule kept for the cell moves with it. A row whose port no machine lists (a machine with no entry, a
scout older than 2.37) or two machines list stays on the port. The file is copied before each rewrite
(`cloud-providers.json.bak-machine-rows-<stamp>`, the newest 10 kept) and the log names each row moved. A
renamed model is followed: a model the entry no longer lists whose every port now carries one other name
is the same cells under another name — its rows and schedule move to it. A model gone with its cells, or
split between two names, is followed nowhere, and its row says its model is gone.

A machine's model goes through its machine's entry, and when the entry does not take the request — the
scout restarting, its update — the proxy waits for it, 15 s at the most, before the pool's next row
(`EntryWait`, the proxy's event `machine_entry_wait`). A refusal of the entry (404, 503) is its answer. Until
2026-11-08 the request went straight to a running copy on its own port instead (the owner's decision 3 of
2026-10-12, `machine_entry_spare`): the cells listen on their machine's loopback now, and the machine shows the
network one port, its scout's.

Until 2026-11-07 a row could name a cell by its port (`srv:<port>`) and followed it when it moved to another port or swapped
ports with another cell (`rust/crates/admin/src/fleet/cell_outputs.rs`, 1.3.499). A cell holds a port only while it runs now, a
row names its machine's model, and a cell that starts again on another port changes nothing for the row: the model's running
copies come with their ports (`copyPorts`), which say that a copy runs. A deleted cell that was its model's only copy takes the rows of the model: they lose
their cable and stay in their place, open; a cell of two copies leaves the rows to the other (1.3.655).

Until 1.3.486 a step kept its own levels, and a client kept the pools it might call (`models`). The
controller moves them once at start: the steps' levels onto their models (`PoolDesk.migrate_rows`,
stamped `pools-of-rows-2026-10`; a model two steps named with different levels keeps the stricter
of each), and a client's list onto one pool (`ConsumerDesk.migrate`: of "all", the first pool of the
board; of a list, the first id a pool still has). The proxy reads both forms meanwhile. Until 1.3.462
the file kept model blocks and pools of subscriptions: the controller rewrote them once into pools
(`PoolDesk.migrate`, stamped `pools-of-steps-2026-10`).

Legacy test aliases (`testAliasOf`) keep resolving to their original's sign-in and limits; there is no
button that makes new ones. Two registrations that report the same ChatGPT quota identity share their
limits: connecting the same subscription twice adds no budget. Deleting an account takes its rows
out of every pool and ends that registration's own sign-in at OpenAI; the board says whether OpenAI
confirmed.

The shared credential vault serializes renewal across processes per account and merges token writes
under a document lock. Controller and proxy use the same renewal implementation. The vault is also
the file's one writer (`scripts/check_oauth_owner.py`).

Admin APIs: `POST /api/pools/create`, `/api/pools/add-row`, `/api/pools/connect-row`,
`/api/pools/remove-step`, `/api/pools/save`, `/api/pools/level`, `/api/models/schedule`, `/api/pools/delete`,
`/api/board/reader`, `/api/consumers/deny`, `/api/entry-move/seen`, `GET /api/pools/refs` and `GET /api/cloud-accounts/catalogue`; see
[HTTP API](http-api.md) for fields and errors. A pool has no port of its own since 1.3.487: every
client comes in through the entry with its own key, and a file that still had such a port loses it
at the controller's start (`rust/crates/admin/src/cloud/pool_ports.rs`).

## Saved usage-limit resets

Each real subscription displays OpenAI’s available banked reset count, details
and expiry dates. This uses the same read-only `/wham/rate-limit-reset-credits`
endpoint as the [official Codex client](https://github.com/openai/codex/blob/main/codex-rs/backend-client/src/client/rate_limit_resets.rs).
**Use reset** asks for confirmation naming the account and expiry before consuming
that selected credit. Routing and failover never consume a reset automatically.
A legacy TEST account displays its original account’s credits, not another balance.

One door leads to the spend (since 1.3.464; the rows under a step's fold that drew the same list
are gone — the operator, 2026-10-11). On the subscription's row of the main board (since 1.3.492;
before, in the head of its card in Routing, and until 1.3.486 in a pool step's head on the main
board), the number of saved resets (`↺ 3`) — read by the counter itself, at most once a minute,
`↺ ?` with the reason when the read failed — is a
button: it opens one window that lists the resets that can be spent —
the one that ends first leading and pressed — and asks which; the window's own **Use reset**
button is the confirmation, and its Cancel is focused. Opening it, or choosing in it, spends
nothing; the list is read again first when it is older than a minute. While an earlier
attempt is unresolved the window offers that reset only, says why, and the button retries it
with the same id. There is no refresh icon beside it any more (1.3.491): the limits are read when
the page loads and again when it is come back to after a minute.

POST consumption includes the selected `credit_id` and a UUID `redeem_request_id`.
A shared, locked `subscription-resets.json` journal records the attempt before the
request. An uncertain result survives reloads/restarts and must be retried with
the same id; another reset is blocked until it is resolved. `reset` and
`already_redeemed` invalidate quota readings in the proxy and refresh the board.
`nothing_to_reset` and `no_credit` are displayed explicitly. A failure to fetch
details is shown as unavailable, never as zero resets. Local tests use fake
provider responses; a real reset is consumed only when the operator confirms it.

The journal defaults to `var/subscription-resets.json` beside the repository,
or `state/subscription-resets.json` under `CARAVAN_DATA_DIR`;
`CARAVAN_SUBSCRIPTION_RESETS_FILE` overrides it for both daemons.
