# Images for text-only models: refusal and description

## Status and purpose

The caravan refuses a picture no row can read, and — when the board names a reader that reads pictures — has the picture read
for the row that serves the request and cannot read it itself (the owner, 2026-11-06: "даже если к модели без визора попал
запрос — как-то это обработать и послать на описание модели с виженом"). The board writes one shared `reader` in
`cloud-providers.json`, not one per pool, and the save checks the reader rule. [The reading](#the-reading) below is what
happens to such a request. The describe node, published metadata for read routes and a persisted cache are a **future
design**, and the sections that say so are not a deployed feature.

A chat endpoint alone does not promise that its model can see an image. Sending a picture to a text-only model can produce an answer that sounds as if the model saw it. The entry must not silently turn that into a successful-looking request.

## Step 1: refuse against a known promise

The entry examines the content of chat messages, not just the endpoint. `MediaParts` supplies the same vocabulary to the request reader, model-kind rules and journal. Message and part positions in a refusal are the client's, counted from one. The case table is `contract/media_parts.json`.

- If the row that serves the request promises image input, pass the image through unchanged. A pool is asked row by row: a picture goes to a row that promised pictures even when another row of the same pool said it reads text alone, and `pool_steps` keeps the text-only row out of that request's choice.
- If every row that may serve said its inputs exclude images and there is no reader wired, refuse before sending upstream: HTTP 400, `media_unsupported`, parameter `model`, with the first unsupported image's message and part numbers. The journal records `entry:media-unsupported`; the board's step pill says "No pictures". When the board's reader reads pictures, nothing is refused here: the row that serves has the picture read for it if it cannot read it ([The reading](#the-reading)).
- If the input promise is **not said**, it is unknown, not a promise that images are unsupported. Do not infer vision capability from a model name or refuse on that basis; leave the provider to decide. An unknown promise and an unwired reader are different absences.
- This rule decides images only. It does not introduce an audio refusal. Existing endpoint/job checks remain separate.

A pool **advertises** only what all rows that may serve can promise: that intersection is what `/v1/models` and Routing publish, and an unknown row cannot be turned into a text-only promise. A request is **served** by one row, so the promise a request is judged against is the serving row's, not the shared one. The two facts are kept apart: a mixed pool advertises text alone and still serves a picture from its vision row. A request may be refused only when no row that may serve reads the picture and no reader is wired; selection then has no candidate, and the pool refuses. See [Pools](pools.md).

The row-selection step (`pool_steps/rows.rs`) asks each row's own promise (with `Wired::Nothing`: the question is the row's, not the wiring's) and is told by the entry whether the board's reader reads for this request (`PoolQuestion::reads`). A row that cannot read the picture is then a candidate marked `read_first` (`readFirst` in the pool's state); without a reader it is no candidate.

## What a wiring says, and what it answers

The vocabulary of a wired reader lives in `rules/src/media_reader.rs`, and only there: `Wired` is what the operator named
(`Nothing`, `Unknown(name)`, `Named(reader, promise)`), `Reader` is what that says about one word, and `MediaReader` is the
reader itself. `Wired::promise(word)` is the only place a wiring is asked what it promises, and `EntryModels::wired` is the
only place that fills a promise — from `ModelKind`, never from a model's name. A model called `qwen3-vl-8b-instruct` whose
facts say `text` is a text model, whatever its name says: that case is in `contract/media_reader.json`.

`Carried::verdict` answers for a part with `Verdict::Reading(part, reader)`, and the words of the refusal are read from that
answer, never from a state named by hand. Each answer keeps its own code and its own journal reason, because the answers are
different absences and one sentence for all of them is wrong advice — "wire a reader" is wrong where a reader is already
wired, and wrong for a name the caravan cannot check:

| Answer | Code | Journal reason |
| --- | --- | --- |
| `Nothing` — the operator named nothing | `media_unsupported` | `entry:media-unsupported` |
| `Unknown(name)` — a name the caravan does not know | `media_reader_unknown` | `entry:media-reader-unknown` |
| `NotSaid(name)` — facts that name no inputs | `media_reader_unverified` | `entry:media-reader-unverified` |
| `CannotTake(name, word)` — other inputs promised | `media_reader_cannot` | `entry:media-reader-cannot` |
| `Reads` — this word promised | not refused: the reader reads the picture for a row that cannot ([The reading](#the-reading)) | — |
| `Itself` — the reader names the requesting pool | `media_reader_self` | `entry:media-reader-self` |

The same file says the caption's shape and the fields that tell two captions apart, so they cannot drift: the envelope
`<caravan-caption by="…" prompt_version="…">`, the five characters escaped (`& < > " '`), and the key as a JSON array of
`[part, reader, prompt_version]` — joined fields would let a name holding the separator share a key with a different reader.
The prompt version is `v1` and is said once, so changing the words changes the cache.

The rule is asked from a reading, and that reading is the board's: its pools, the models it knows, the routers that say which
name is a machine's model, the keys that say which account is signed in. It is built once, in `CloudData::board_names`
(`cloud/data/reading.rs`), and the save door and the reader block both ask it from there. What went wrong on the live board on
2026-11-06 was a reading of the pools alone: `gpt-6-luna` was refused with `media_reader_unknown`, although a subscription's
facts say it takes `image`, because the reading the door asked from held no models — so every model name answered `unknown`.
That is a fact about the reading, not about the model, and a table that only had `unknown` cases could not tell the two apart.
The rule asks what the board knows (`EntryModels::known_name`), not what a key can call this second (`pick`): a name the board
knows and cannot call still has facts to read against, and `pick` stays the answer for what a client may call now — the two
sets are held apart by one flag (`open_to`). `contract/media_reader.json` (`names`) holds a name the reading has facts about, a
name it has no facts about, and a name that writes.

This is held by `scripts/check_media_reader.py`: the vocabulary is said once, a wiring is built in one place and filled from
`ModelKind`, a caption built anywhere else is a second shape, every answer has one code, every case in
`contract/media_reader.json` says `why` — including the case where the name and the promise disagree, the case named as
nothing, and the cases that are not refused — and the rule is asked from one reading that is not cut down to part of the names.
Its negative test is in `scripts/test_guards_fail.py`.

Routing's Pools column carries one reader block (`static/js/reader-block.js`) for the whole board. Its single row shows the
name and the rule's answer, even when there are no pools. The row has an output dot and no input dot: the wiring is not a path a
request runs through. The block's state (`named` or `quiet`) describes the name, not the rule's answer. The board reads the
answer from `Reader::word()` through `cloud/pool_state.rs`; it never infers capability from the model's name.

Drag the output cable to name a reader. A click on the cable clears it after confirmation. The page sends
`POST /api/board/reader` with `{"reader":"name"}` or `{"reader":null}`. The name is the one the entry calls the model by
(`liveCatalog`, carried on each model row as `data-entry-name`): a model two accounts offer is called with its account after it,
`gpt-6-luna (chatgpt-subscription)`, so the model's bare id names neither — the live board refused the bare `gpt-6-luna` as a name
the caravan does not know on 2026-11-07. The cable is drawn to the row of that name. A model the entry offers under no name is
sent by its key, which the door refuses in the rule's words; the bare id could name another account's model — a guess. The save accepts a known reader that promises image
input, or absence; unknown, unverified and incompatible names are refused by `Reader::writes()`. The same vocabulary describes
request refusals, but the current row selector does not yet use the board's wiring.

The column is read top to bottom: Direct, the reader block, the pool cards. Direct is the first block and is not pinned there
(the owner, 2026-11-06: "просто пусть будет всегда самым верхним"), and the reader block stands directly below it. The order
is said once, in `poolsHtml`, and no part of the column has a `position:` of its own; `contract/media_reader_board.json`
(`column`) holds it, including the empty-pools case: the block stays, but there are no pool cards.

The reader's cable lights by what a request says it went through, never because a wiring is drawn: a request whose pictures
were read names the reader (`readerName`), and the reader's own request names the request it reads for (`readerFor`) and lights
the reader's cable alone — its client never named the reader's pool (`static/js/pool-flow.js`, `contract/media_reader_board.json`,
`flow`).

The block is held by `scripts/check_media_reader_board.py`: its words are the arms of `Reader::word()` in both directions, the
same words are defined in all six languages and coloured in `static/css/pool-board.css`, the input dot is named as an absence
in the module, in the table and in the pin, and the flow lights a reader cable only by what the request names.
`contract/media_reader_board.json` is run by the program (its `answers`: the word and whether the board may write it) and by
`scripts/test_js_reader_block.py`, which runs the real module in node. Its negative test is in `scripts/test_guards_fail.py`.

The rule is held by `scripts/check_media_parts.py`: the vocabulary is declared once, the readers read it instead of working it out again, both kinds of row — a provider's and a machine's — ask the same rule, and every case in `contract/media_parts.json` and in the pool section of `contract/model_kind.json` says `why`. Its negative test is in `scripts/test_guards_fail.py`.

## The reading

What happens to a request that carries a picture, once its pool is known (`EntryModels::media`, `rules/src/media_reader.rs`):

1. The entry asks the board's wiring, for this client and this pool, what it says about `image`. Only `Reads` names a reader to
   ask (`Wired::reads`). Then the request goes (`MediaAnswer::Readable`) with what the reader reads of it: the pictures, in the
   order they came, each with the client's message and part numbers and where its bytes are (`Reading::of`,
   `rules/src/media_reading.rs`). Any other answer keeps the refusals of step 1.
2. The pool chooses its row as it always does — in its own order, with its limits and its queues. The entry does not prefer a
   row that reads pictures: only the row that has to answer now is looked at (the owner, 2026-11-06: «Надо смотреть только на
   ту, что сейчас должна обработать»). A row that reads the picture gets it as it came; a row that cannot is chosen
   `read_first`.
3. Before a `read_first` row is asked — and before a machine's queue, so no place is held while the reader works
   (`exchange/machine.rs`, `exchange/cloud.rs`) — the pictures are read (`exchange/reading.rs`):
   - A picture must be inside the request: a `data:` URL, or base64 data said in a `source`. A link or a file a provider keeps
     is refused as what it is — HTTP 400, `media_reader_link`, journal `entry:media-reader-link` — before the reader is asked
     about any picture: the caravan does not fetch what a client points at for a reader (an address on its own network would
     be read by the caravan on a client's word), and a request is read whole or not at all.
   - Each picture is asked of the reader once: a chat, no stream, in the words of this version (`Wired::PROMPT`, beside
     `PROMPT_VERSION`), never with the client's own question. The reader's request is served like any request — its pool,
     its row, its queue, its account, its limits, its spend and its own record, under the client's name, with `readerFor`
     naming the request it reads for. Its answer comes back over a socket pair on the loopback, and the waiting request is
     watched meanwhile: a stop from the board or a streaming client gone ends the wait at once. The reader's request then
     leaves its model's queue if it is still waiting there; a description its model is already writing is finished and
     dropped.
   - What the reader said is kept in this process's memory (`captions.rs`): 256 captions at most, a day each, keyed by
     `MediaReader::key` — the digest of the `data:` URL as sent (the picture's bytes and the type they are said to be), the
     reader and the version of the words. A client sends its whole conversation again with every turn, so a screenshot is read
     once, not once per turn. Only a reading that gave words is kept; nothing is written to disk.
   - A picture the reader did not read — its status, a refusal it said, an answer with no words, a reader the caravan cannot
     call now — ends the request: HTTP 502, `media_reader_failed`, journal `entry:media-reader-failed`, in words that say who
     was asked, which part, why, and that nothing was sent to the pool. There is no silent switch to another model, and no
     caption of nothing. In a stream already open, the same words come as its error event.
4. The row gets the request with each picture replaced, where it stood, by the reader's caption in its envelope
   (`Reading::rewritten`), the rest as it came. A later row of the same request gets the same words: the reader is not asked
   twice for one request. The record of the request says `readerName`, `readerPictures` and `readerKept` (how many were taken
   from memory).

The values — pictures, question, words, the request rewritten, the refusals — are in `contract/media_reading.json`, run by
`rust/crates/rules/tests/contract.rs`; the board-reader cases of the entry are in `contract/entry_models.json` (`media`); row
selection is pinned in `rust/crates/proxy/src/pool_steps/tests.rs`. Held by `scripts/check_media_reading.py`, with its breakages
in `scripts/test_guards_fail.py`.

## Future: an explicit describe node

The operator may place a **describe** node in the routing graph. It has two distinct cables: a **reader** cable to an image-capable model or pool, and an **onward** cable to the text model or pool that will answer the client. The operator chooses both; the caravan never guesses a reader. Validate incomplete, missing, incompatible or cyclic routes visibly rather than treating them as working routes. The node is an explicit conversion, not an invisible fallback attached to every text model.

For a request entering that node, preserve the order and position of every message and part. The reader describes each image; replace that image at its original position with a marked text description, and send the resulting request onward only after all required descriptions succeed. Preserve the other text and request semantics. A native vision route without this node keeps the original image. No reader, failed reader, unreadable image, cancellation or incomplete description must yield a fabricated caption or silently drop an image: fail the request with a visible reason. A caption is a lossy interpretation, not the image itself.

The replacement text must identify its origin and be escaped as data, for example:

```xml
<caravan-caption by="reader-id" prompt_version="v1">A red bicycle beside a tree.</caravan-caption>
```

The exact envelope and prompt are versioned with the implementation. Reader output is untrusted content, not an instruction; XML escaping must prevent it from breaking the envelope. Do not claim the onward model saw the original image.

## Future: Captioner, cache and resources

What [The reading](#the-reading) built covers the call through the pools, the memory cache and the separate records; what
follows is the design it was cut from, and the parts not built yet: a persisted cache with its retention policy, and the
reader's usage linked in the onward record.

A Captioner owns the read-and-describe operation and its cache. Its cache key includes the SHA-256 of the **image bytes**, the identity of the chosen reader (including the effective model/version where known), and the prompt version. A URL alone is not image identity: its contents can change. A changed image, reader or prompt must miss the cache; failures and incomplete results must not become successful cache entries. Retention, size limits, privacy and deletion policy must be made explicit before persistence is shipped. Cache hits must be distinguishable from new reader calls.

Reader calls use the existing `PoolSteps` selection and `Places` capacity/queue machinery, including the same model availability, limits and VRAM constraints as other calls; they must not start a model or bypass admission to make room. Waiting, cancellation and failure release any acquired place. An unknown capacity is not a free slot. A downstream failure must not be reported as a successful client answer merely because captioning succeeded.

Account for the reader and the onward request separately: record reader identity, cache hit or miss, status and its actual usage when supplied, alongside the onward model's own usage. Link both to the client request without adding caption tokens to the onward model's reported usage or inventing token counts when absent. Reader failures and time spent waiting should be observable without exposing image bytes or captions in routine logs.

## Future: Routing and published metadata

Routing must show the describe node, both cable endpoints, incomplete wiring and active work; its details must identify the reader and onward destination. Operators need to add, connect, inspect and remove it without mistaking an unwired node for a working path. The client-facing metadata may promise image input for a route through this node only when the configured path is valid and the reader and onward destinations support their respective work. Unknown or missing capability stays unknown, not a positive promise. Metadata must make the conversion visible: image input is described for a text model, not native vision. Any wording and interaction are future UI work, not a current control.

## Acceptance before shipping the future node

Exercise native pass-through, known text-only refusal and unknown promises; multiple images and their positions; cache hit and each key component changing; reader and onward failures, cancellation and queue release; separate usage with absent usage; escaped hostile captions; invalid and cyclic wiring; and UI/metadata for complete, incomplete and unknown routes. Tests must also show that a failed caption is never forwarded as a successful one.
