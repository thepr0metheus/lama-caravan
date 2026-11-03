# Security: accounts, sessions and the fleet token

A fresh caravan is **not** open. Until its first account exists it answers
only its public routes: every page leads to the first-run page `/setup`, and
every other API call answers 401 naming it. (Until 2026-10-07 a fresh caravan
let anyone in until somebody made an account — on a NAS that meant anyone on
the home network could take its subscriptions and give out its keys first,
and the first user was never asked to make one.) A client of the entry needs its
key; a cell answers on its own port with no key, so keep the cells' ports closed to
all but the controller ([operations.md](operations.md)).

## The first account

**`/setup`**: every page of a fresh controller leads here — create the
account; you are signed in and taken straight to the board. The **fleet
token** is made with the account and waits in System → Security: adding a
scout from the board hands it over, so it is copied only for a scout set up
by hand. (Once an account exists, `/setup` redirects to `/login` — the page
works exactly once.) Further accounts, their roles and their passwords are the
Security panel's (`POST /api/auth/users`).

There is no command line any more. A lost password of the only admin: stop the
controller and take `state/auth.json` away, with an `auth.db` left beside it. The next
`/setup` makes a new first account and a new fleet token, so add each scout again.

Every route requires a session except the login and setup pages, `/health`,
`/openapi.json` and the machine endpoints below.
`/openapi.json` is open for the reason `/health` is: it describes the API —
paths, what each does, who may call it — and holds nothing about the fleet. Accounts have two roles:
**admin** (everything) and **viewer** — read-only, enforced server-side in the
auth guard (every `GET` passes, anything mutating answers 403, logout
excepted). Run monitors and test suites as a viewer. Accounts and sessions live in
one JSON document (`state/auth.json` next to `state/admin.json`, chmod 0600) — no external
database. An `auth.db` of the Python controller beside it is read once, at the first start,
and stays as it was.

- Passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user salt.
- Sessions: HttpOnly SameSite=Lax cookie, 30-day TTL, revocable from the
  Security panel; 5 failed logins from one IP → 60 s lockout.
- The IP is the sender's (`rust/crates/rules/src/client_address.rs`): behind a proxy on
  this same host — the DSM's nginx on the NAS, which connects from 127.0.0.1 — the
  address that proxy names (the last `X-Forwarded-For` entry, which it appended,
  else `X-Real-IP`); from any other peer, the peer itself, whatever its headers
  say. Read from the connection alone, everyone behind the DSM was 127.0.0.1, and
  five wrong passwords from anyone locked out everyone (until 2026-10-11). The
  proxy's journal names a request's client by the same rule.

## The fleet token (machines)

Scouts can't type passwords. Machine-to-machine calls authenticate with a
shared **fleet token** instead (generated when the first account is created):

| Direction | What carries the token |
|---|---|
| scout → controller | heartbeats (`POST /api/topology/client-heartbeat`), model downloads (`GET /api/models/download`) and folder models' listings (`GET /api/models/folder`) send `X-Caravan-Token` |
| controller → scout | every cell/routing/monitor call sends the same header |

Nobody copies it to a scout by hand: adding the scout on the board (Machines
→ ＋ Add scout) hands it over, together with the controller's address
(`POST /api/controller-url` on the scout, `controllerToken` in its
`config.json`). A scout nobody has added yet is open on the LAN, like a fresh
install; once it holds the token, its own API requires the same header too
(its page, `/api/pairing` and `/api/health` stay open), including letting go
(`/api/unpair`, the ✕ on its node) — only its controller can do that.

Regenerating (Security panel) invalidates the old token immediately: every
scout's heartbeats are rejected (401) and its machine shows silent. Add each
scout again on the board — the scout takes the new token once the controller
accepts a heartbeat carrying it.

## Prometheus

`GET /metrics` works with the fleet token when sign-in is on:

```yaml
scrape_configs:
  - job_name: caravan
    static_configs: [{ targets: ["controller:7990"] }]
    authorization: { type: Bearer, credentials: "<fleet token>" }
```

## Data-plane API keys

A client of the entry always has a key (see the next section), and the entry is the one
way in: a proxy port of the older kind no longer listens, and the key of such a route
gets a 403 (`entry:not-a-consumer`). The proxy reads a changed key at the next request; no
restart is needed.

## Client keys of the entry

A client of the entry (＋ in the board's clients column, operations.md "One entry
with keys") gets its own key, `lcv1_` and 48 hex characters from the system's
randomness. The key is answered once, when it is made or replaced: the board
gets only its last four characters, a save from the page keeps the stored key,
and a lost key is replaced, not shown again — the old one stops working in the
same write. A key opens every pool and every model that runs, but what is blocked for its
client: a pool or a model blocked for it answers 403 `model_not_allowed`. Nothing behind a pool reaches the client: not
the provider's headers (its organisation, its limits, its cookies), not its
words about the caravan's own sign-in (a 502, never a 401 — the client's own key
is fine), not the steps or accounts of a pool at its limit.

No other answer carries a key. Until 2026-10-11 the system monitor did: every
second, to every open page, it sent the routes' config and the proxy's state
with every key in them, the entry's clients' too, though no page read them. The
monitor now sends neither the config nor a key — the proxy's state goes out with
`keyTail` in each key's place (`KeyEntry.public_route`) — and the routes' file as
stored (`GET /api/agent-proxies/raw`, the raw editor) answers an admin only.

A port of the old kind keeps its key in its route's form, and the board shows
that key in full there (and so to a viewer). That key opens nothing any more: make
each old agent a client of the entry, and delete its route.

## What this does NOT cover

- **Cells' own ports** answer with no key: keep them closed to all but the controller
  (firewall), and the data plane LAN-only.
- **TLS**: the controller speaks plain HTTP. If you expose it beyond the LAN, put
  a reverse proxy with TLS in front (the session cookie is not marked Secure,
  so terminate TLS before the browser).
