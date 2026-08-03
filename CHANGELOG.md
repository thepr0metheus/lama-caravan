# Changelog

## Unreleased

- One address per page. The board is `/board`; `/` and `/index.html` redirect
  to it. The kanban is `/kanban`; `/router` redirects to it, carrying its
  `?id=` along. Nothing is removed — every old bookmark still lands — but the
  address bar now holds exactly one answer to "which page is this", which is
  the whole point: a URL is only a reliable identifier when a page has one.

  302 and not 301, deliberately: a permanent redirect is cached hard by
  browsers and unpleasant to take back if this proves wrong.

  Every internal link points at the canonical address — the back-links on
  `/system`, `/models`, `/hf` and the kanban, and both places the sign-in page
  sends you after it succeeds — so following one lands directly instead of
  bouncing. The docs that listed the old addresses are updated, including the
  paragraph in `docs/testability.md` that justified `data-t-page` partly by
  "the URL has aliases". That argument is now false and says so; what
  `data-t-page` still adds over the URL is *when* it can be read — before any
  script, while the loading screen is up.

- Every page says which page it is: `data-t-page` on `<body>`, alongside the
  `data-t-state` readiness flag that was already there. `board`, `kanban`,
  `models`, `system`, `hf`, `login`, `setup`.

  It is in the HTML, so it is true from the first byte — before any script,
  while the loading screen still covers everything, which is exactly when
  nothing else can be asked. Nothing else answers this reliably either: the
  URL now has aliases (`/` and `/board`, `/kanban` and `/router`), the title
  is English everywhere, and the header subtitle deliberately follows the
  interface language.

  **The loading screen deliberately gets no name of its own.** `#appLoader` is
  a `<div>` in the same document, hidden once the app paints — same URL, same
  title, same page. Naming it would report a navigation that never happened.
  It is a state, and `data-t-state="loading"` already says so.

- The board says which page it is. Its browser tab read `LAMA CARAVAN` while
  every other page followed `<page> — Lama Caravan`, so with five tabs open it
  was the only one that named the product instead of itself. It is `Board —
  Lama Caravan` now. The name is not new: `sysBackToBoard` has said "Board"
  all along, and it is what the back-link on `/system`, `/models` and
  `/kanban` already reads.

  It also answers at `/board`. `/` stays canonical — bookmarks, every
  back-link, the sign-in redirect and the E2E suite all point there — this is
  the same alias arrangement `/kanban` already has with `/router`.

- Thirteen panels and lanes become named landmark regions, and the repeated
  cards and buttons say which one they are. The containers a test reaches for
  are the same ones a keyboard user needs to jump between, and every one of
  them was an anonymous `div` — measured, not assumed: of the forty hooks the
  external suite uses, twenty-one had no role at all.

  Nine of the thirteen borrow the heading already beside them
  (`aria-labelledby`) rather than carrying a second string: the name then
  follows the interface language for free and cannot drift from what a sighted
  user reads. Only four — the GPU lane, the model tree, the disk summary and
  the routing graph — had no heading to point at and needed a string of their
  own, translated into all twenty languages.

  The repeated elements are the part with a user behind them. A `cell-card` is
  an `<article>` whose accessible name was everything inside it concatenated
  ("▶Start⏹Stop↟Autostart✕Delete reserved:8001configured…") — identical for all
  twenty-two. Its twenty-two Configure buttons announced the single word
  "configured", so someone tabbing the board heard it twenty-two times with no
  way to know which cell each opened. Both now carry the identity `data-t-id`
  already held.

  One finding of our own while measuring: the two **Reserve cell** buttons were
  announced identically — "＋ Reserve cell :8024" on both hosts, because the
  next free port is chosen fleet-wide. Nothing said which machine the cell
  would land on. They now name the host.

  Two items on the list were left alone, both after measuring. The eight
  kanban palette buttons are already distinct by their own text. And
  `board-gpus-lane` sits on an element `nodes.css` hides on purpose — a GPU
  mini-summary redundant with the node card's own GPU rows — so a landmark
  there would be one nobody can reach; the reason is recorded next to the
  markup and in the contract's never-visible table.

- The CosyVoice cell works on Blackwell — for the first time ever. The engine
  venv installed CosyVoice's own torch pin, 2.3.1+cu121, whose kernels stop at
  `sm_90`; the RTX 5090 is `sm_120`, so every CUDA kernel launch died with
  "no kernel image is available" — masked until 1.3.173 by the swallowed
  exception, and layered under an unrelated VRAM shortage that blocked even
  initialisation. The venv now runs torch 2.7.1+cu128, whose wheels carry
  `sm_75…sm_120` — one venv serves both the RTX 3090 and the RTX 5090.

  The recipe is fixed at the source: `run_tts.sh` installs the cu128 torch
  FIRST (so neither whisper nor CosyVoice's requirements pull their own) and
  filters the stale pins out of requirements.txt, the same treatment grpcio
  already got. Verified live: a real Russian synthesis on the 5090 answers
  HTTP 200 with a 24 kHz WAV in under a second, through the primary path API
  — the tensor fallback never fires.

- The CosyVoice cell reports the real reason synthesis fails. Its synth path
  tries the current API (a file path) and falls back to the pre-2026 one (a
  16 kHz tensor) — with a bare `except` between them that discarded the first
  exception unlogged. On a current checkout the path API is the RIGHT one, so
  when it breaks the fallback breaks too (`Invalid file: tensor(...)` out of
  soundfile, which wants a path), and that derivative error was the only thing
  the caller ever saw. It cost a debugging session on both sides of the fleet:
  the voice app proved the sample format innocent and read our cell server
  line by line to find the swallowed exception.

  Both failures are logged now, and the FIRST one is what propagates — to the
  journal and to the caller's `{"error": ...}` body alike.

- A cell whose health path answers with an error stops rendering as a healthy
  green RUNNING cell. The probe classified ANY response without a loading
  marker as "ok" — so a command cell whose engine died at initialisation (a
  CosyVoice cell answered `/health` with HTTP 500 and a full ONNX diagnosis
  for a day) stayed green: the wrapper process is alive, and "alive" was all
  the probe asked. The same defect class as the unlit cable — an error
  response rendered as normality — and the third consumer bitten by it: the
  external LAN scanner had to patch around the same lie on its side.

  There is a new phase for it, `broken`, distinct from `error` on purpose:
  `error` means the unit is down and behaves like stopped (Start offered),
  while a broken cell is a running process — Stop works, Start does not. The
  card shows the cell's own diagnosis (💔 + the health body's error, full
  text in the tooltip, hook `cell-broken-error`), the lifecycle chain parks
  at RUNNING in error colouring — it did start, and it is not well — and the
  status pill says failed. Works for controller and client cells alike; the
  probe runs from the controller, so no scout release is needed.

- The welcome tour stops stealing clicks from someone already working. Its
  auto-start waits for the board to be ready — up to 20 seconds — and then
  opened its overlay regardless of what the operator was doing by that point,
  landing on top of their next click. Now the first real interaction (a
  pointerdown or keydown anywhere) cancels the pending auto-start and records
  the seen-flag: a person confidently driving the page has answered the
  question the welcome tour exists to ask, and interrupting them on the NEXT
  visit would be the same mistake later. The pulsing ? button remains the
  standing invitation, and a genuinely idle first visit still gets the tour.

  The cell editor's first-open nudge gets the same treatment for its 900 ms
  render-wait: start editing inside that window and the nudge yields. The
  listeners arm only after the editor opens, so the click that opened it
  cannot cancel its own nudge.

  Surfaced by the external Playwright suite: parallel runs slowed the board
  just enough for the auto-start to fire mid-test, and the overlay swallowed
  a click on a cell's Configure button — the same theft a human experiences,
  just reproducible.

- The two auth forms get their own URLs. `/login` is the sign-in form;
  `/setup` is the first-run wizard, token box included. The server redirects
  between them by state: a fresh controller bounces `/login` to `/setup` —
  a sign-in form on a controller with no accounts is a form nobody can
  possibly get through — and an enabled controller bounces `/setup` back.
  The URL you land on now tells you which mode the controller is in, and
  neither document ever contains a control that cannot be used on it.

  Named `/setup`, not `/signup`, on purpose: nobody self-registers here. The
  wizard works exactly once, on a controller with no accounts; every later
  account is created by an admin from the Security panel. A URL that promised
  open registration would be promising something the system deliberately
  refuses to do.

  Both pages share one shell — styles, language select, the 20-language
  script — so this is a routing change, not a second page to maintain. For
  the test suite: every label on each page is now unique by construction,
  `getByLabel` and `getByRole` recipes resolve to one element with no form
  scope, and `docs/testability.md` records the redirect matrix.

- The sign-in page carries one form instead of two. It shipped both — the
  sign-in form and the first-run account wizard — with the wrong one
  `display:none`, and a fetch of `/api/auth/me` deciding client-side which to
  reveal. The server already knows; it is the same module. The round trip
  bought nothing and cost three things: every visitor to a controller with
  sign-in already on downloaded the first-run wizard including its note
  ("Sign-in is not enabled yet…"), which is untrue for them and none of their
  business; the duplicate labels made the page ambiguous to anything addressing
  it by name; and a fresh install showed a flash of the sign-in form before the
  fetch came back and swapped it.

  Now the server picks, and the absent form is absent rather than hidden. The
  page script guards both submit handlers, so whichever form is missing has
  nothing to bind.

  Worth stating precisely, because the report that prompted this got it half
  right: **role locators were never affected.** `display:none` keeps an element
  out of the accessibility tree, so `getByRole('textbox', { name: 'Username' })`
  matched exactly one element before this change too — measured on the live
  page. What matched two was `getByLabel`, which ignores visibility. So the
  cure was never to rename the hidden form's labels; it was to stop sending a
  form nobody on that page can use.

- Switching the interface language stops throwing on `/models` and `/system`,
  and starts actually repainting them. `setLang()` ran the **board's**
  `renderAll()` on every page, deciding from one global which pages were
  different. On the two pages that have no board that reads `state`, which they
  never populate — so it threw at the fifth call and everything after it was
  skipped. It looked harmless because `applyLanguage()` is the *first* call, so
  the attribute text did update; what silently did not was anything those pages
  build with `t()` into `innerHTML`. `/system`'s hero tiles and llama.cpp panel
  kept the old language until the next 30-second poll, and `/models` kept it
  until the next refresh.

  A module every page imports should not know what any page contains, so the
  dependency is inverted: pages register what to repaint with `onLangChange()`,
  and `i18n.js` no longer imports the board's renderer at all — which also ends
  a circular import between the two.

  Two rules are now enforced in CI, both proven to fail on a deliberate break:
  `i18n.js` may not import a page renderer, and a page offering the language
  picker must register a repaint. The second one is the quiet failure — forget
  it and the page still *looks* translated, because the attribute pass runs
  regardless.

- The four controls the test team's expanded sweep found, and thirty more they
  could not reach. Theirs first: the two mirrored `HEALTH_PATH` boxes had a
  label-row whose `for=` names the *toggle* beside them, so every other field in
  that editor was named by its label and these two were not; `/hf`'s
  results-count select was named by a hardcoded English `title`, and the sort
  select by nothing at all.

  Then we repeated the sweep from the source instead of the browser, which
  reaches what a live session cannot: every runner tab including `moonshine` and
  `transcribe`, and every control built inside a template string. Thirty more,
  each verified by a second pass whose job was to refute it. The pattern
  underneath is one shape repeated: **the name exists, and points at the wrong
  element.**

  - The model picker replaces a `<select>` with a focusable `<div>` and then
    hides the select — taking the `<label for>` with it. The visible widget, the
    one you tab to and click, had no name. It now borrows that same label rather
    than inventing a second string.
  - Two companion checkboxes announced "Enabled" / "Disabled" and nothing else:
    their wrapping label contains only the span that holds the state word, while
    "MMPROJ" belongs to the select beside them and "offload to GPU" sits outside
    the label entirely.
  - Eleven help tips in the graph editor were hand-written copies of `helpTip()`
    minus its `aria-label` — eleven silent tab stops. They go through the helper
    now.
  - Six `✕` buttons in the security panel, one per user and per session, were
    all announced identically.
  - The confirm dialog's prompt field is named by the question it is asking
    (`aria-labelledby` at the title), which is better than any label we could
    have written for it.

  Twenty-five new strings across all twenty languages, plus seven places where a
  translated string already existed and something hardcoded was shadowing it —
  including `aria-label="Language"` on three more pages after the sign-in page
  was fixed for exactly that in 1.3.165.

- The i18n guard now checks the two lookup routes it never covered. It read
  `t("…")` in JS and stopped there, so `[data-i18n*]` in the HTML and `hfT("…")`
  against `/hf`'s own table went unverified — 132 lookups nobody was checking.
  That gap is worse than it sounds for `data-i18n-aria`, added one release ago:
  a mistyped key there produces an `aria-label` whose value is the key, which a
  screen reader then reads aloud. A missed `[data-i18n]` is at least visible on
  screen; a missed name is audible only to the people least able to work around
  it. All three branches were verified by breaking a key on purpose.

- Five controls a screen reader could not name now have names. The worst was
  `/models`: fifty-nine catalogue checkboxes announced as "checkbox, not
  checked", identical, with **Delete selected** as the next control after the
  list — so a keyboard user could pick files for deletion with no way to hear
  which ones. The name existed all along in `data-t-id`; it simply was not
  exposed. `/hf`'s search and filter boxes were named by their placeholder,
  which is the last-resort source and disappears once the field has content —
  named while empty, anonymous while in use. The models-directory field had
  nothing at all.

  The kanban wait field had neither a name nor a test id: its visible caption is
  a `<span>`, which the accessibility tree treats as decoration. It now says
  what it is and which port it belongs to, and carries `kanban-input-wait`.

  Three new strings across all twenty languages, plus `data-i18n-aria` for the
  case of a name with no visible label to borrow from — `data-title-i18n` would
  have planted a hover tooltip too.

- The sign-in page translates its one untranslated name. The language selector
  carried `aria-label="Language"` hardcoded while the other twelve strings on
  that page followed the interface language — so a page fully in Russian
  announced its own language control in English to anyone using a screen reader.
  `apply()` now translates `aria-label` as well as text, since a `<select>` holds
  options and cannot carry its name in `textContent`, and `langLabel` is
  translated into all twenty.

- The board stops shrinking instead of falling apart. Below ~1330px it used to
  stack its two columns into one — and stacking throws the board away rather
  than adapting it, because the cables are drawn in the gap BETWEEN the columns
  and that gap is the whole idea. Stacked, every cable ran from a card to the
  card directly beneath it, the divider lane was hidden, and what was left was
  two lists that no longer showed which route reaches which cell.

  It now holds its layout at a `--board-min` of 1128px and the page scrolls
  sideways. A narrow window means panning across an intact board instead of
  reading a broken one — the right trade for a dense control panel that lives on
  a desktop beside other windows. The sticky header spans the same scrollable
  width, or scrolling right would strand the title over the middle of the board;
  that rule is scoped to pages that actually have a board, so `/models` and
  `/system` are untouched.

  A browser window cannot be given a minimum size from a page — no API does
  that — so this is the shape the request takes.

- The sign-in page announces its two silent moments. The failure message is an
  empty `<p>` that script fills after a rejected attempt — so a screen reader
  learned nothing: the text appeared, and the only feedback was that nothing
  happened. It is `role="alert"` now, which interrupts because it answers an
  action the user just took. The fleet token shown once after the first account
  is created is `role="status"`, announced without interrupting because it
  follows a success.

  These are the only two roles written by hand on that page. Everything else
  already had one from its tag — `<button>`, `<input>`, `<select>`, `<h1>` —
  and repeating those as attributes would add nothing. A role is what the
  browser derives, not something to sprinkle.

- A host can be powered off from the board, next to the reboot that was already
  there. This module said "reboot only, never shutdown" on purpose, and the
  reason has not changed — **nothing here can switch a machine back on** — so
  poweroff was added by treating it as the one-way door it is rather than by
  relaxing the rule:

  its own endpoint on both sides (`/api/host/poweroff`, and the same on the
  scout) so it cannot be reached by getting a field wrong, and so a scout too old
  to know it answers 404 instead of doing the other one; the action comes from
  the ROUTE, never from the request body; the confirmation makes the operator
  **type the host's name**, the gate model deletion uses, and says in the dialog
  that the board cannot undo it; a name that does not match cancels silently
  rather than erroring; and the button is dimmer at rest than reboot and sits
  after it, because reboot is the one almost always wanted.

  Powering off the controller kills the request that asked for it — a transport
  error there is the expected shape of success, exactly as for reboot.

- `/hf` has test hooks. It had none — `[data-t]` matched zero elements there,
  reported from outside, and the page still appeared in the readiness list, so a
  green suite looked like a covered page. Fourteen names now: the search field and
  its submit, the result limit, sort and filename mask, the on-disk view, the four
  token controls, and the two repeated families that matter — `hf-result` carrying
  the repository id and `hf-download-job` carrying the job id.

  The size buckets are addressed by the values the page filters on (`0-9`, not
  `≤9B`) so a label change cannot move them. `hf-token-clear` deletes a credential
  and a download job writes to disk: both are named to be asserted present, not
  clicked — the same rule the destructive controls on `/system` follow.

- The deploy prints a link to the test run it started. The dispatch answers with
  an empty body — 201 and 204 both carry nothing and the API declares no response
  at all — so the run is fetched separately, from a URL derived from the dispatch
  one rather than configured again. Neither `limit` nor `event` is honoured by
  that endpoint and the list comes back oldest-first, so it walks from the end and
  matches on the commit just sent, which is the only thing that tells our run
  apart from a concurrent one. Three tries over about two seconds, then it gives
  up quietly: a convenience line must not hold up a deploy.

- The sign-in page is compressed like everything else. It is built from a string
  rather than read from a file, so it went through neither `send_json` nor
  `send_file` and stayed the one uncompressed response — 22 KB, served before
  anyone is signed in, which makes it the first thing a new visitor waits for.

- `scripts/deploy.sh` performs the deploy that was written down and done by hand:
  push, pull, compile on the target, restart, then ask `/health` what it is now
  serving and FAIL when that is not what was just shipped. A deploy that reports
  success while the previous process keeps answering has no other symptom. It
  also refuses a dirty tree or a branch other than main, and ends by telling the
  external suite a release happened — the step easiest to skip, because skipping
  it breaks nothing visible: the tests just never run.

- `/api/topology` stops re-parsing the cloud config five hundred times per
  request. `account_credential_summary()` calls `load_cloud_data()`, which reads
  and parses a 99 KB JSON file, and `cloud_blocks_state()` called it once per
  block — with 502 blocks that is ~500 reads and parses of the same file to
  produce one topology payload, about 100 MB of parsing per request. Profiled on
  the controller: 287 ms of a 732 ms build, `json.loads` alone at 185 ms across
  2546 calls.

  Concurrency is what made it the ceiling rather than merely wasteful: each parse
  holds the GIL, so tabs polling in parallel queued behind one another instead of
  building in parallel. Measured from outside, topology's time-to-first-byte rose
  from 750 ms at one browser to 4.5 s at eight while the bytes themselves still
  arrived in 30 ms — server thinking, not transfer.

  `load_cloud_data()` and `load_provider_secrets()` are now cached on the file's
  own (mtime, size), exactly as `read_gguf_metadata_cached` already was for the
  same reason after a live incident in July; and the credential summary is
  resolved once per ACCOUNT (there are four) instead of once per block.

- JSON and text responses are compressed. Nothing was, and these payloads are
  long runs of repeated keys — the shape gzip is best at. Measured on a real
  monitor response: 85 KB to 10 KB, 8.7x, in 0.6 ms at level 6 (level 9 buys
  0.1x for twice the CPU, on a box that is also serving models). Applied to
  `send_json` and to text/JS/CSS/SVG in `send_file`, only when the client
  advertises gzip and the body clears 1400 bytes, with `Vary: Accept-Encoding`
  so an ETag cannot hand a gzipped body to a client that never asked. A client
  without the header gets exactly the bytes it got before.

- `scripts/testability_names.py --check` catches a composed hook that nothing
  builds. The composed list is declared by hand, so deleting the code that emits
  a hook left the list still claiming it, the doc still publishing it, and the
  check still passing — the doc is generated FROM that list, so it could not
  notice. A suite would then locate a name the page never emits and read the
  empty result as a broken application. Reported from outside, exactly that way.

- The monitor poll asks for what it does not have. `/api/system-monitor` is
  ~3.4 MB — ten minutes of samples at 1.8 MB plus the token-speed points at
  ~1.4 MB — and the board polls it once a SECOND, per open tab, to learn one new
  sample. `?since=<epoch>` returns only what is newer and the client appends;
  four browsers were pulling ~13 MB/s of JSON the server built to tell them what
  they already knew. That is what made page-load time climb with the number of
  tabs, and what took the process to a 1.5 GB peak. The incident log gets the
  same treatment, and there it saves more than bytes — the file was re-read from
  disk and parsed on every poll to resend 133 KB that had not changed. Measured
  on a live tab: the first request is 3962 KB and every one after it is 55 KB.
  A request without `since` still gets everything, so an older client and a curl
  by hand are unaffected.

- Hooks inside the model catalogue, the graph, and the compute-target row.
  `models-tree-group` / `models-tree-group-toggle` on each `<details>` level and
  `models-model-select` on each checkbox (`data-t-id` is the model's PATH — two
  quantisations share a display name, and the path is what the delete call
  sends). `kanban-cable` on the `<g>` that is one connection, `data-t-id` as
  `from->to`: counting `path` inside the cable layer counted 54 elements for 5
  nodes, because every edge draws a hit-path, a visible cable and a two-stroke
  ✕. `cell-edit-compute` / `cell-remote-compute` on the CPU/GPU/auto tiles with
  `data-t-id` and the real `disabled` attribute, the same shape the runner tabs
  got. `board-cell-add` on each host's ＋ button, and `board-client-card`
  carrying the host id.

  That last one answers a question rather than a request: cards are addressed by
  host id (`foreman:8004`) while the lane shows the display name (`atlas`), so
  the clients lane read as unrelated to the cards it owns. Both are now on the
  same element. Documented alongside the third cell state — `reserved`, a held
  port with nothing configured, which offers neither start nor stop and is where
  every cell begins.

- The board reuses its connections. The admin server answered HTTP/1.0, so every
  static module and every API call opened its own TCP connection — 46 modules
  plus the API on a cold load, which is how a second browser overflowed a
  five-deep accept queue. It speaks HTTP/1.1 now and a browser reuses at most
  six sockets per origin, so the same page costs roughly six connections instead
  of sixty.

  What made it safe to flip, each verified rather than assumed: `serve_model_file`
  sends `Content-Length: 0` on its bare 400/403/404 instead of a bodiless header
  block; `read_body` refuses a chunked body and a malformed Content-Length,
  closing rather than leaving the socket pointed into the middle of one; and
  every rejection in `_auth_guard` closes, because `do_POST` answers 401/403/302
  BEFORE reading the body and the leftover bytes are otherwise parsed as the next
  request line. That last one was reproduced exactly:
  `501 Unsupported method ('{"username":"a","password":"bcde"}GET')`, with the
  real following request never answered.

  `timeout = 30` on the handler, because the inherited value is None and
  `StreamRequestHandler.setup()` only arms a socket timeout when it is not — an
  idle kept-alive connection would otherwise hold its thread until the client
  chose to close. The oauth callback server keeps HTTP/1.0 deliberately; it
  writes bodies with no length, and the setting is on our handler, not on
  `BaseHTTPRequestHandler`.

- The page downloads the language it renders, not all twenty. `i18n-data.js` was
  1.95 MB — 62% of the JavaScript on the board and the largest thing on a cold
  load — because it held every translation table in one module, and the page
  paints one of them. The tables now live in `static/js/i18n/<code>.js` and load
  on demand; `i18n-data.js` is 3 KB of loader. English stays a static import
  because `t()` falls back to it synchronously for any key a translation lacks,
  so an English UI fetches exactly one table and any other fetches two. Same
  number of requests either way.

  Two things had to move with it. The onboarding tours merged their strings into
  every language at import, which now happens before the language exists — they
  register through `onLanguageLoaded` instead, so a tour in Japanese is not
  quietly a tour in English. And the CI guard reads all twenty through
  `allMessages()`, the one caller allowed to pull the full 1.9 MB.

- The board stops asking for things it already has. Three requests went out on
  every load or every tick for no reachable reason: `/api/proxy-daily-stats`
  rode the 1.5-5s topology tick (a DAILY total, fetched up to forty times a
  minute, and a second time in the same boot tick besides), a GET
  `/api/queue-thresholds` ran immediately before the POST that recomputes and
  returns the same value, and `/api/llama-command-preview` was POSTed on every
  full render to paint a `<pre>` inside `<main id="classicView" hidden>` — the
  retired view. Measured on a live tab: 63 API req/min before, and the trio
  `/api/state` + `/api/topology` + `/api/proxy-daily-stats` was 52 of 54
  requests in the window.

- A request that fails halfway through its answer ends the connection instead of
  writing a second answer into the first. The catch-all at the bottom of each
  verb replied with `send_json`, which is right for a handler that fails before
  responding and wrong for one that fails mid-body: `serve_model_file` streams a
  GGUF under a Content-Length taken from `stat()`, and any error it does not
  catch itself put `HTTP/1.0 500 …` and a JSON error INTO the model. Reproduced:
  a client asking for a 4096-byte file received 2251 bytes with a second HTTP
  response starting at byte 2048 — which a scout would have written to disk as
  weights. The same path now counts what it sends and drops the connection on a
  short read, so a truncated transfer is something the receiver can notice
  rather than a file that merely looks downloaded.

- The proxy closes the connection when it answers an error before the upstream
  replied. It speaks HTTP/1.1 and every other response path sends
  `Connection: close`; this one branch did not, and the success path's
  `close_connection` is jumped over by the exception that led here. A client
  using keep-alive — the default in every modern SDK — left a listener thread
  parked in `readline()` with no socket timeout for as long as it held the
  socket.

- The listen queue fits a page load. Every Python listener in the fleet — the
  board, the twelve proxy routes, the cell servers — took socketserver's default
  `request_queue_size` of 5, so five connections could wait to be accepted and
  the kernel dropped the rest. Answering HTTP/1.0 the board gets one connection
  per request and a cold load is 46 static modules plus its API calls, so a
  second browser was already over the limit. Measured on the controller: `ss`
  reported Send-Q 5 against a somaxconn of 4096, and TcpExtListenOverflows stood
  at 4166. With tcp_abort_on_overflow=0 an overflow is not a refusal you can
  see — the kernel drops the SYN, the client retries at 1s, 3s, 7s, and the page
  simply sits there. A 74-second load was measured from outside while /health,
  one cheap request, answered green throughout. Now 128 for the board and the
  proxy routes, 64 for the cells. (llama-server, for scale, listens 512 deep.)

- Every page carries an inline boot guard, so a page that cannot start says so.
  `data-t-state` could reach `loading` and `error`, but never `error` in the one
  failure that mattered: when `/js/main.js` itself does not arrive, the code that
  would set `error` is the code that did not load, and the shell sits there
  forever with nothing on screen to explain it. The guard is inline because it is
  the only script that cannot fail to arrive. It names the assets that failed,
  flips the flag, and puts a reload banner on the page. `scripts/check_boot_guard.py`
  keeps the five copies identical.

- A runner tab greys out for every kind of model it cannot launch, not just the
  wrong file extension. The gate compared `.gguf` against everything else, which
  answered correctly for exactly one of the four artifact kinds: an LLM and a
  speech recognizer are both GGUF, so choosing GigaAM left llama.cpp offered and
  choosing Qwen left transcribe.cpp offered — and a whisper size left moonshine
  offered, and the other way round. Runners now declare the artifact KIND they
  take (`llm-gguf`, `asr-gguf`, `whisper-size`, `moonshine-lang`, or `*` for the
  two whose artifact does not live in MODEL_FILE at all), a GGUF is sorted into
  LLM or speech by its own `stt.*` metadata, and the tooltip on a greyed tab says
  which of the two it wanted. The model picker dims rows through the same table,
  so the two halves of the dialog can no longer disagree.

  An artifact we cannot classify — a path a remote form holds that the
  controller's model list has never seen — blocks nothing. Greying a runner the
  operator may well be right about is worse than letting the engine say so.

- A cell that is running an older copy of its own server says so. Each cell
  server hashes its source at import — the one moment it is certainly what the
  interpreter loaded — and reports it on the health path; the controller
  compares that to the file it ships and puts a `⇪ old server` chip on the card
  when they differ. The gap was invisible in both directions: the file beside a
  long-running process is refreshed at every start, so disk said "current" while
  the process answered with older behaviour, and the board, the health check and
  the consumer all read green. A cell that predates the stamp reports nothing
  and is marked unknown rather than stale — "nobody can tell" is the honest
  answer, not a guess.

- A client stops silently skipping runners the controller has but the scout
  does not. `caravan-scout` resolved a launcher to its runner from a table
  compiled into the client, and `transcribe` was never added to it: every
  transcribe cell fetched nothing, kept whatever was in `$HOME`, and logged not
  one line about it — for four days, on a green board. The scout now reads the
  mapping out of the controller's own manifest and falls back to the table only
  when the manifest is unreachable, so a runner added on the controller reaches
  every client without a scout release. An unresolvable launcher is logged
  instead of returning quietly.

- The transcribe.cpp cell answers in the format that was asked for —
  `response_format=verbose_json|text|srt|vtt` and `timestamp_granularities[]`,
  matching the whisper cell. Word times are derived from the engine's token
  times: GigaAM reports `max_timestamp_kind = token`, so a request for word
  timestamps was ACCEPTED and answered 200 with an empty word list, which reads
  as "this audio had no words". Chunk offsets are applied, so the times of a
  split recording stay on the recording's own clock instead of restarting at
  every seam. The default response is unchanged.

- The whisper cell honors an optional `task=translate` multipart field
  (whisper's built-in any→English translation) — a voice-translation app's
  speak-for-me and interview-trainer flows use it for single-hop RU speech
  → EN text. Servers that don't know the field keep ignoring it.

## 1.3.79 — 2026-07-19

- The node's compute block reads as one system. Its header is "Compute" (not
  "GPUs") now that CPU leads, the CPU row gains a used/total RAM bar mirroring a
  GPU row's VRAM bar (whole-host, no per-cell slices), and the whole CPU block
  wears the CPU-cell blue — accent stripe, bar fill, faint wash, blue ports — so
  it matches the cells that run on it, the way each GPU row reads green.

## 1.3.78 — 2026-07-19

- The node panel's CPU block leads and carries its own load. CPU and GPU swapped
  order (CPU first), and the CPU block now mirrors a GPU row — live load% in the
  head, RAM used/total where a GPU shows VRAM, with "cells on CPU" ports as a
  sub-line. Those two figures left the node header, which keeps only the platform.
- The unified compute-target tiles are compact — tighter padding, smaller type,
  a single-line detail row — roughly a third shorter, so the CPU/GPU/auto choice
  no longer dominates the form.

## 1.3.77 — 2026-07-19

- One device selector for every runner, above MODEL_FILE. The launch device
  used to have two disconnected widgets — llama's CPU/GPU cards (writing
  N_GPU_LAYERS) and the command tab's auto/GPU/CPU tiles (writing ENV). They are
  one "Compute target" card now, in llama's richer styling (GPU tile names the
  card and its VRAM), sitting above MODEL_FILE where it governs the whole cell.
  What each runner can target differs, so unavailable tiles are DISABLED with a
  reason, not hidden: llama = CPU + GPU (no start-probe → no auto), vLLM and
  whisper = GPU only, moonshine = CPU only, custom = all three. A click writes
  the right field per runner (N_GPU_LAYERS for llama, TTS_DEVICE/CUDA_VISIBLE
  ENV pins for command-path); multi-GPU llama hosts keep their per-card pick.

## 1.3.76 — 2026-07-19

- A moonshine cell created from the tile actually starts. Two bugs made a
  freshly-configured moonshine cell un-launchable: the topology phase stayed
  `reserved` instead of `stopped` (the command-path stopped-check knew whisper
  but not moonshine), so the card never grew a Start button; and the device
  chip read "auto" on a not-blue card because moonshine was missing from the
  CPU-cell logic. Both fixed — moonshine reaches `stopped` with a Start button
  and reads as a CPU cell in every state (its ONNX models are CPU-only).
  Verified end-to-end through the UI on BOTH a controller cell (:8008) and a
  client cell (:8023 on foreman): reserve → pick the 🌙 tile → Apply → Start →
  health in 2 s → speech transcribed on the CPU, 0 VRAM.

## 1.3.75 — 2026-07-19

- A controller moonshine cell saves and starts. `write_server_cell_artifacts`
  demanded a raw COMMAND from every command-path cell except vllm/whisper, so
  saving a moonshine cell on the controller failed with "COMMAND is required" —
  the runner synthesizes its command from MOONSHINE_MODEL, exactly like
  whisper does from WHISPER_MODEL. The generated `start.sh` carries
  MOONSHINE_MODEL in its config block now. Verified on the controller
  end-to-end: cell saved from the tile, systemd unit started, health in 4 s,
  44 s of speech transcribed in 4.8 s on the CPU.

## 1.3.74 — 2026-07-19

- New runner: 🌙 **moonshine** — Moonshine v2 speech-to-text as a first-class
  tile next to llama.cpp/vLLM/whisper, not a hand-typed custom command.
  CPU-only by design: the EN model beats Whisper large-v3 accuracy at 250M
  params and runs sub-second on a CPU core, so a moonshine cell can live on
  any host — including one whose GPUs are fully booked by LLMs — and the card
  correctly reads as a blue CPU cell. The "model" is a LANGUAGE
  (en es zh ja ko vi uk ar) picked in the shared model picker, each row
  stating its license up front: en is MIT, the others ship under the free
  Moonshine Community License (registration + attribution, < $1M/yr revenue);
  no Russian — whisper stays the RU recognizer. Serving files live with the
  scout (`stt/` + `scripts/install-moonshine.sh`, caravan-scout ≥ 1.2.6),
  same cell contract as the whisper server.

## 1.3.73 — 2026-07-19

- Rescues are visible in Request History. A rescued request wears an amber
  🛟 badge next to its via tag — the tag names where the request ENDED, the
  badge confesses the exits it failed on first, with the full trail in the
  tooltip ("srv:8002 (400) → …"). The via filter gains a `rescued` option, so
  "show me everything that needed the backup today" is one dropdown away.

## 1.3.72 — 2026-07-19

- The finished summary confesses a rescue. The rescue itself was recorded only
  as `rescue_retry` events mid-journal, so the terminal `finished` record read
  as if the request went to its final upstream directly — diagnosing "why did
  this agent suddenly answer through the cloud" required scrolling back, an
  easy step to miss. The summary now carries
  `rescued: {hops, trail: [{from, status}]}` — the failed exits in order, with
  the status each one failed with.

## 1.3.71 — 2026-07-19

- New rule node: 🛟 **backup** (`onError`) — two exits, main and backup.
  Requests route down main; when that upstream FAILS — connection refused or
  any HTTP ≥ 400 — before a single response byte reached the client, the proxy
  re-resolves the route down the backup edge and replays the same request
  there. The SSE keepalive preamble does not count as output: the backup's
  stream continues into the same open pipe. Chained backup nodes rescue in
  encounter order (capped at 3 hops); every hop writes a `rescue_retry` event
  with the failed status and error body. This is redundancy, not load
  management, and it closes a real gap: the failover node picks by free
  capacity BEFORE sending and the queue's spill fires on wait time — neither
  ever sees the model's answer, so a 400 sailed through both. Live proof, the
  context-overflow incident replayed: a 105k-token request → local cell 400
  `exceed_context` → rescue → cloud 200 in ten seconds.
- The queue card names the agent, not just its port. The owner lookup searched
  only the client's LIVE report — partial by nature, a scout echoes just the
  agents it currently supervises — so the card showed a bare `:8121` for an
  agent the controller's stored assignments knew perfectly well. Stored rows
  now fill the gaps (live rows stay first — they are the drift truth); the
  queue history pane gets the same fix for free.

## 1.3.70 — 2026-07-19

- Orphan cells surface on the board. A live `lama-cell@` unit with no registry
  record renders as a red dashed strip on the controller node — port, what it
  runs, VRAM held, pid — with a stop button. The board renders the store, so
  such a cell used to be invisible by construction while holding its port and
  VRAM, with nothing left to stop it by.
- An orphan's port counts as taken: the port guard consults the live units
  too, so a new cell can no longer be handed a number something is still
  serving on. Safe to enforce now that orphans are visible with a stop
  button — enforced alone, this would have blocked ports nobody could free.
- Starting a controller cell preflights its port and names the holder ("port
  8019 is already in use by python3 (pid …) — stop it first") instead of the
  bind error buried deep in llama.cpp's log.

## 1.3.69 — 2026-07-19

- The controller's stored host id is the role name `controller`, not a
  machine's name. Slot keys (and the notes and schedules living inside them)
  migrate on load, once and idempotently; the API keeps accepting the legacy
  spelling from stale cached frontends and maps it to the canonical id at the
  single choke point every slot lookup goes through, so one cell can never
  exist under two keys. The legacy id stays RESERVED against client heartbeats
  forever — an id that ever meant "the controller" may never come to mean one
  of its clients. The display name is unchanged and still comes from
  `LLAMA_TOPOLOGY_SERVER_NAME`. Proxy-route ids (`…:proxy:<port>`) are a
  separate wire-format namespace and deliberately keep their spelling — they
  are stored in client-side scout state, which a controller-side migration
  cannot reach.

## 1.3.68 — 2026-07-19

- Deleting a controller cell removes its artifacts too. `write_server_cell_artifacts()`
  lays down `var/server-cells/<port>/{cell.json,start.sh}` and delete left them
  behind, so every removed cell added to a pile. Not merely litter: the port
  outlives the cell and can be handed to a CLIENT next, while the stale
  `start.sh` still describes a CONTROLLER cell on that number — one
  `systemctl start lama-cell@<port>` away from putting two different cells on
  one port again, which is the failure that hid a running 27 GB model from the
  board. Eleven such directories had accumulated; four of them named ports that
  now belong to a client.

## 1.3.67 — 2026-07-18

- The controller's host id is reserved: a client heartbeat claiming it is
  refused. Slots are keyed `"<hostId>:<port>"`, and a client's id is whatever
  its own config says — so a client answering to the controller's id would
  write straight into the controller's namespace, putting two different cells
  under one key. That is not hypothetical: a controller cell and a client cell
  ended up sharing port 8011 today, and the running one vanished from the board
  entirely while holding 27 GB of VRAM. The check is case-insensitive so a
  fleet never holds two spellings of it, while `is_controller_host()`
  stays exact — it decides behaviour and must never mistake a client FOR the
  controller.

## 1.3.66 — 2026-07-18

- "Is this the controller?" is now a question the code asks, not a hostname it
  compares. A dozen checks read `host_id == "skynet"` — and those checks decide
  real behaviour: whether a delete stops a systemd unit, whether a start is
  forwarded to an agent, whether a cell's crash state gets cleared. Spelled that
  way they read like a hostname test, which is the wrong question on any fleet
  whose controller is not called that (or, worse, whose CLIENT is). They call
  `is_controller_host()` now, against a `CONTROLLER_HOST_ID` sentinel that stays
  "skynet" on purpose: slot keys, cell notes and schedules are all persisted
  with it, so the VALUE cannot change without migrating every stored key — but
  the meaning no longer hides behind a name.

## 1.3.65 — 2026-07-18

- Deleting a controller cell stops it. The delete handler told a CLIENT's agent
  to stop the cell but skipped the controller's own — `if host_id != "skynet"`
  guarded the whole stop — so removing a running controller cell dropped the
  slot from the store while `lama-cell@<port>.service` kept serving. The result
  is invisible by construction: the board renders what the store holds, so the
  cell disappears from the UI while its llama-server holds its VRAM, and there
  is no card left to stop it by. Found one on the controller sitting on 26.9 GB
  of a 31.8 GB card, healthy and routed to by nothing, while two other cells
  failed to start for want of that memory and the UI showed no model at all.

## 1.3.64 — 2026-07-18

- A cell that runs out of VRAM says so, instead of blaming the model file. The
  failure classifier matched its patterns in order, first hit wins, and `model`
  sat above `oom` — but llama.cpp reports an allocation failure by *also*
  logging "error loading model" / "failed to load model", so every card that
  simply did not fit read "model file missing or unreadable — re-download it or
  pick another" while the file sat there, 22 GB and perfectly readable. Two
  cells on the controller showed that today; the journal underneath said
  `cudaMalloc failed: out of memory`. `oom` is now matched first. The reverse
  mix-up cannot happen: a genuinely missing file fails at open, before a single
  allocation is attempted, so its log carries no oom wording.

## 1.3.63 — 2026-07-18

- A GPU-pinned cell is no longer labeled a CPU cell while it has yet to
  allocate. Both the card's device chip and the node's "cells on CPU" line
  decided by measured VRAM alone — running with no `gpuIndexes` meant CPU. But
  a model reads its weights off disk for the first 13-18 seconds and allocates
  nothing on the card in that window, and the host's GPU-to-process mapping
  refreshes on its own beat after that. So a cell carrying `TTS_DEVICE=cuda`
  came up as a blue CPU card right after starting, which reads as the Device
  setting having been ignored — while the process was in fact on the GPU. An
  explicit pin now counts for both: the launcher either lands on the GPU or
  fails outright, it never quietly falls back.

## 1.3.62 — 2026-07-18

- The router's server list says what a command cell runs. Only llama cells
  carry a MODEL_FILE, so every whisper/TTS/vLLM cell rendered as a bare
  `:8018` in the kanban SERVERS panel — a port with no clue what was behind it.
  Each cell now carries a short artifact label: whisper and vLLM take it from
  their own model field, a custom cell from its command with the boilerplate
  stripped, so `bash ~/run_tts.sh $PORT cosyvoice` reads as
  `run_tts.sh cosyvoice`. A vLLM path resolves to the model rather than the
  quantization folder — `<Model>/<author>/<FORMAT>` labeled one cell "BF16",
  which is true and useless.

## 1.3.61 — 2026-07-18

- The GPU half of a node block follows the scroll. On a node with a long cell
  list the VRAM bar scrolled away, so the hover highlight added in 1.3.59 had
  nothing visible left to point at. The panel is sticky under the topbar now,
  and stays inside its own node — it travels out with the block when that block
  ends rather than riding over the next one. Two things make it work: a grid
  item stretches by default and a full-height box has nowhere to stick, so the
  panel shrinks to its content; and it carries its own scroll, so pinning it
  never puts ROUTE ACTIVITY out of reach on a short window. Two-column body
  only — stacked, it would pin over the cells.

## 1.3.60 — 2026-07-18

- The board gives up its cable gutters before its columns. 1.3.59 fixed the
  right-hand overflow by stacking at 1479px, which threw away the two-column
  layout on every window between 1100 and 1480 — the wrong thing to sacrifice.
  The lane floors carry content and the divider column carries a 36px button,
  but the board's 72px gap and the lanes' 44px gaps are only the air the cables
  are drawn through, so those tighten to 28/20 first. Two columns now survive
  down to 1330px, and only below that does the board stack. Measured at 1330,
  1340, 1455 and 1480: no overflow, 24px of padding on both sides.
- The bundled command-cell servers (`tts/`, `whisper/`) live in ONE place now,
  the caravan-scout repo. They existed in both repos plus as the `$HOME` copies
  that actually run, and had already drifted — this repo's `tts_server.py` had
  the device fix and the scout's did not. The scout owns them because it is what
  installs them: `scripts/install-{tts,whisper}.sh` copy them into `$HOME` on
  the client. This repo installed them nowhere.

## 1.3.59 — 2026-07-18

- The board stacks into one column at 1479px instead of 1100px — the width
  where its two columns actually stop fitting. `.topology-lanes` is the binding
  constraint (four floors 210 + 36 + 390 + 260 plus three 44px gaps = 1028px,
  and the right board column only reaches that around 1480), so every viewport
  from 1101 to 1479 kept the column minimums and overflowed to the RIGHT: 254px
  of it at 1150. The left padding survived, the right one was eaten by the
  overflow, and the panels on that edge came out clipped — the page read as
  shifted, with an indent on one side only.
- Hovering a running cell lights up its own slice of the node's VRAM bar, so
  "how much of this card is that model?" is answerable at a glance. The bar
  knows only the node-wide total, so each card carries its per-GPU claim and
  the handler stacks the bands by port — two cells sharing a GPU read as
  adjacent segments instead of two overlapping ones both starting at zero.

## 1.3.58 — 2026-07-18

- The start confirm for a command cell says what actually happens. It used to
  ask "Start the server on :N?" — but a command cell starts a command, not a
  model server, so the dialog described a different thing than the button did.
- The same wording bug sat on the card's ▶ button, and worse: it filled the
  model slot from the card's model-name row, which on a command cell holds the
  command line. Starting the cosyvoice TTS cell asked "Start the server on
  :8018 (bash ~/run_tts.sh $PORT cosyvoice)? The model will load into memory" —
  a command announced as a model, plus a load that never happens. The render
  now hands the runner to the click handler instead of guessing from the DOM.
- The cosyvoice TTS loader asks `_pick_device()` like the xtts one already did.
  CosyVoice2 takes no device argument (its own code picks cuda whenever a GPU
  is visible), so a cell set to CPU only landed there via the
  `CUDA_VISIBLE_DEVICES=` the Device tile writes; auto mode ignored the
  free-VRAM guard entirely and `fp16=True` was requested even on CPU. The
  chosen device is now stated in the log — previously nothing recorded it.
- `tts/tts_server.py` in the repo had drifted behind the copies the clients
  actually run: `_pick_device` existed only on the clients, while the engine
  name in a ready `/health` existed only in the repo. Reconciled.

## 1.3.57 — 2026-07-18

- Apply on a cell's config no longer promises a start. It saves and returns
  (the start is the card's play button), but the confirm asked "Start the
  server on :N?" — so a save read as a failed start. It now asks the same
  "Apply the cell configuration changes?" the controller's Apply uses.

## 1.3.56 — 2026-07-18

- The t/s figure in the SLOTS head is labeled "last" — it's the generation
  speed of the last completed request (llama.cpp holds it while the slot is
  idle), not a live rate, so it no longer reads as current.

## 1.3.55 — 2026-07-18

- STOP stays amber on every cell again. It followed the cell hue (blue on CPU
  cells) after the button-color unification; a warm stop action reads better
  the same everywhere, so it's back to a constant amber. START/AUTOSTART still
  follow the cell accent, CONFIGURED/STARTING still follow the cell hue.

## 1.3.54 — 2026-07-18

- Port picker colors read right: cell tiles (the swappable ones) are now amber
  and agent-port tiles are red. Red was on the cells you CAN act on and amber
  on the ports you can't — swapped so red means hands-off. Bridges stay purple,
  the current cell green.

## 1.3.53 — 2026-07-18

- One coloring mechanism for every cell button and lifecycle step, driven by
  two per-cell hue tokens: the "go" family (START, AUTOSTART, done, reserved,
  running) follows --cell-accent, the "in-progress" family (STOP, CONFIGURED,
  STARTING) follows --cell-caution. On GPU cells that's green + amber; on CPU
  cells both are blue, so the whole card reads blue. Destructive (DELETE,
  error, stopping) stays red. Fixes buttons that used to each follow their own
  rule — the RESERVED step drew from the app's teal accent, and STARTING/STOP
  stayed amber on blue cells.

## 1.3.52 — 2026-07-17

- The cell's port button no longer hovers green on a blue CPU cell: it drew
  from the app's teal accent instead of the cell accent. Now it matches its
  cell — green on GPU cells, blue on CPU cells.

## 1.3.51 — 2026-07-17

- Swap ports between two stopped cells: in the port picker, a click on another
  stopped cell's tile trades the two cells' ports (with a confirm) — both slot
  records, config PORT, controller artifacts and every router reference follow
  each cell atomically. Running cells and proxy/bridge ports stay
  non-clickable; swappable tiles are dashed and hinted.

## 1.3.50 — 2026-07-17

- The bundled TTS command-cell server now advertises its engine in `/health`
  even when ready — it used to answer a bare `ok` (indistinguishable from any
  other healthy server), so a voice app's LAN discovery couldn't identify a
  running f5/cosyvoice cell and dropped it. Ready now returns
  `{"status":"ok","engine":<engine>}`; the caravan board reads it as running
  exactly as before.

## 1.3.49 — 2026-07-17

- Host cells keep their place when you start or stop them. They were ordered
  by state under the hood (live cells assembled ahead of stopped slots), so
  STARTING a cell made it jump up the list. Each host's cells now sort by
  port number only — the card stays put through every state change.

## 1.3.48 — 2026-07-17

- No more hidden rule nodes on first open: a stored node position can end up
  underneath the CLIENTS/SERVERS blocks as those grow (more cells, more
  models). The board now runs the same de-overlap resolver a drag-end uses
  for every rule node right after render — visual only, nothing is written
  until you actually drag the node.

## 1.3.47 — 2026-07-17

- The breathing ring is gone; the border comet now runs the whole time a
  cell is running. "Processing right now" already reads from the slot bar's
  agent chip — one constant motion beats two competing ones.
- Generation speed sits at the right edge of the SLOTS head (mono, tinted
  by the cell accent) whenever llama.cpp reports a non-zero rate — refreshed
  by the same per-second panel rebuild, no extra polling.

## 1.3.46 — 2026-07-17

- The running-cell breathing ring got noticeably stronger: a pulsing 1 px
  accent border plus a wider, brighter glow (peak opacity 1), breathing a
  touch faster. The slot bar and its agent-name display stay untouched.

## 1.3.45 — 2026-07-17

- Running cells came alive: a quiet breathing ring on every running cell, and
  a border comet that appears only while tokens actually flow (driven by the
  existing 1 s activity tick — no extra polling). Both take the cell's accent
  color, so CPU cells breathe blue; everything stops under
  `prefers-reduced-motion`, and the loops are seamless across board rebuilds.

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
