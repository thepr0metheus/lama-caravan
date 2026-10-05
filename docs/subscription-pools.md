# OpenAI subscription pools

A pool is a virtual cloud source with ordered account members, not a credential.
Create one from a subscription card. Use **Connect another subscription** inside
the pool for any additional real account, or select an account already connected
through Add Cloud Provider. A new member stays disabled with `pendingLogin` until
OAuth completes. Signing in enables only that pending member; a deliberately
excluded account stays excluded on re-login. There is no two-account cap.

When the board and browser are on different machines, OpenAI returns to localhost
on the browser machine. Copy that full returned address into **Returned login
address** and choose **Finish signing in**. The controller verifies its origin,
path, state and five-minute lifetime and uses the original PKCE verifier. The
returned address contains a one-use login code; it is not put in logs. The pool card offers manual selection, automatic priority,
per-member exclusion and manual-only membership, order, and optional return to
primary. Manual selection may expire after one or five hours.

The card is a ladder: members stand in priority order, one numbered rung each, and the
rung the proxy last chose is ringed and marked "Serving now". The pool's name is the card's
title — click it to rename it — and the Automatic / Manual switch sits beside it. Between
the rungs the card says what the order means — the next member takes over when this one
reaches its reserve or limit — and under the last rung it says whether the pool returns to
the first eligible member and offers to connect another subscription as an empty place on the
ladder. A rung shows its two limit bars, one under the other, its status (the proxy's own
reason, never a guess), and in its head only numbers: saved resets and the 30-day cost at API
prices, with the button that re-reads its limits. The toggles, the saved resets and the spend
open under the rung's fold. The order changes by dragging a rung by its grip, or with the
↑ ↓ buttons under the fold. A reset whose outcome is uncertain opens its rung and is
flagged in its head.

The automatic policy keeps its current eligible member. Both quota windows and
per-account reserves are checked before each request; missing or stale usage is
refreshed before admitting traffic. A failed refresh does not become zero usage.
All blocked members give an explicit 429/503 with member reasons and reset times.
A response already streaming never changes accounts. Upstream 401/429 can select
another member before output; other errors keep the existing router rescue policy.
A pool requires full conversation history per HTTP request. Account-bound
`previous_response_id` requests receive a clear 400 before selection.

`cloud-providers.json` stores separate `accounts`, `blocks`, and `pools`. A pool
contains `id`, `name`, ordered `members` (`accountId`, `enabled`, `automatic`, optional `pendingLogin`),
`mode`, `manualAccountId`, `manualUntil` (Unix seconds; 0 means until cancelled),
and `returnToPrimary`. Blocks still use `accountId` as a source reference; it may
name a pool. Adopting an account's blocks preserves their ids, ports and graph
references and records `usageOriginAccountId` for historical spend attribution.

Test duplicates store only `testAliasOf`; authorization, quota and reserve resolve
to the original. No refresh token is copied and a real quota refusal blocks both.
For a routing check, manually select the duplicate or exclude the original.
Independent five-hour/weekly failover is tested with two fake subscriptions over
loopback HTTP. Two OAuth registrations reporting the same ChatGPT quota identity
also share the quota owner; connecting the same subscription twice adds no budget.

The board's **Connect another subscription** always creates a separate OAuth
registration, including when the operator signs into the same OpenAI account.
There is no test-duplicate creation button in the normal UI. Legacy aliases are
kept readable for compatibility; they are not independent registrations.
Deleting one real registration removes only its own credential and memberships,
not another registration of the same OpenAI identity. Nonempty pools keep their
models, ports and cables. Deleting their manual choice returns them to automatic
mode. A pool's last member cannot be deleted until the pool is removed or another
subscription is connected. Removing a member with × only detaches it; deleting
the saved registration is a separate, confirmed action in its account editor.

The shared credential vault serializes renewal across processes per account and
merges token writes under a document lock. Controller and proxy use the same
renewal implementation. Credentials remain outside topology and logs.

The proxy publishes its last selection, eligibility readings and 50 recent
switches in `subscriptionPools` in the state file. Switches also enter the normal
proxy event journal. A restart clears selection/cooldown state; the next request
refreshes quota and selects again. Percentages are shown separately, never summed.
Paid API/local-model fallback remains an explicit router policy.

Admin APIs: POST `/api/cloud-pools/save`, `/api/cloud-pools/test-alias`, and
`/api/cloud-pools/delete`; see [HTTP API](http-api.md) for fields and errors.

## Saved usage-limit resets

Each real subscription displays OpenAI’s available banked reset count, details
and expiry dates. This uses the same read-only `/wham/rate-limit-reset-credits`
endpoint as the [official Codex client](https://github.com/openai/codex/blob/main/codex-rs/backend-client/src/client/rate_limit_resets.rs).
**Use reset** asks for confirmation naming the account and expiry before consuming
that selected credit. Routing and failover never consume a reset automatically.
A TEST member displays its original account’s credits, not another balance.

A reset can be reached by two doors, and both end in the same spend. Under a rung's fold,
each saved reset has its own **Use reset** row. In the rung's head, the number of saved
resets (`↺ 3`) is a button: it opens one window that lists the resets that can be spent —
the one that ends first leading and pressed — and asks which; the window's own **Use reset**
button is the confirmation, and its Cancel is focused. Opening it, or choosing in it, spends
nothing; the list is read again first when it is older than a minute. While an earlier
attempt is unresolved the window offers that reset only, says why, and the button retries it
with the same id. The refresh icon beside the number is a different thing: it re-reads the
limits from OpenAI (a plain read) and changes nothing.

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
