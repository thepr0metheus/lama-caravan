# Security: accounts, sessions and the fleet token

Out of the box the caravan is **open** — the homelab default: anyone who can
reach `:7990` has full control, anyone who can reach a proxy port can use the
models. For anything beyond a trusted LAN, enable sign-in.

## Enabling sign-in

Three ways to create the first account:

- **`/setup`**: a fresh controller redirects `/login` to the first-run wizard —
  create the account there; you are signed in immediately and the page shows
  the generated **fleet token** once. Copy it right away. (Once auth is on,
  `/setup` redirects back to `/login` — the wizard works exactly once.)
- **UI**: System (🛠) → **Security** → create the first account — same effect,
  from inside an already-open controller.
- **CLI** (also the lost-password path):

```sh
python3 -m caravan.admin.auth create-user admin
python3 -m caravan.admin.auth set-password admin
python3 -m caravan.admin.auth fleet-token     # print the machine token
```

The moment at least one user exists, every route requires a session except
the login page and the machine endpoints below. Accounts have two roles:
**admin** (everything) and **viewer** — read-only, enforced server-side in the
auth guard (every `GET` passes, anything mutating answers 403, logout
excepted). Run monitors and test suites as a viewer. Accounts and sessions live in
SQLite (`auth.db` next to `admin.json`, chmod 0600) — no external database.

- Passwords: PBKDF2-HMAC-SHA256, 200k iterations, per-user salt.
- Sessions: HttpOnly SameSite=Lax cookie, 30-day TTL, revocable from the
  Security panel; 5 failed logins from one IP → 60 s lockout.

## The fleet token (machines)

Scouts can't type passwords. Machine-to-machine calls authenticate with a
shared **fleet token** instead (generated when the first account is created):

| Direction | What carries the token |
|---|---|
| scout → controller | heartbeats (`POST /api/topology/client-heartbeat`) and model downloads (`GET /api/models/download`) send `X-Caravan-Token` |
| controller → scout | every cell/routing/monitor call sends the same header |

Nobody copies it to a scout by hand: adding the scout on the board (Model
servers → ＋ Add scout) hands it over, together with the controller's address
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

## Data-plane API keys (proxy ports)

Each proxy port can demand its own key: open the route's edit form on the
board (pencil on the proxy card) → Advanced → **API key**, roll one with 🎲,
Save. From that moment requests to the port need
`Authorization: Bearer <key>` (or `x-api-key: <key>`); everything else gets
`401`. An empty field keeps the port open — nothing changes until you opt in.

Point the agent at the same key: in the agent's OpenClaw config the provider
entry already has an `apiKey` field (OpenAI-compatible clients send it as the
Bearer token) — replace its placeholder value with the route's key and restart
the gateway. Roll keys per route, not one shared secret, so revoking one agent
doesn't touch the rest. The proxy hot-reloads the config in ~2 s; no proxy
restart is needed when you change a key.

## What this does NOT cover

- **Proxy ports without a key** stay open: keys are opt-in per route. Keep
  the data plane LAN-only (firewall) either way.
- **TLS**: the admin speaks plain HTTP. If you expose it beyond the LAN, put
  a reverse proxy with TLS in front (the session cookie is not marked Secure,
  so terminate TLS before the browser).
