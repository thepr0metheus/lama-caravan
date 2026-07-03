# Security: accounts, sessions and the fleet token

Out of the box the caravan is **open** — the homelab default: anyone who can
reach `:8090` has full control, anyone who can reach a proxy port can use the
models. For anything beyond a trusted LAN, enable sign-in.

## Enabling sign-in

Two ways to create the first account:

- **UI**: System (🛠) → **Security** → create the first account. You are
  signed in immediately and the panel shows the generated **fleet token** —
  copy it right away.
- **CLI** (also the lost-password path):

```sh
python3 -m caravan.admin.auth create-user admin
python3 -m caravan.admin.auth set-password admin
python3 -m caravan.admin.auth fleet-token     # print the machine token
```

The moment at least one user exists, every route requires a session except
the login page and the machine endpoints below. Accounts and sessions live in
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

Distribute it to each scout — pairing page (`http://host:8092/`, the token
field) or `config.json`:

```json
{ "controllerUrl": "http://controller:8090", "controllerToken": "caravan-…" }
```

Until a scout has the token, its heartbeats are rejected (401) and the client
shows offline on the board. On the scout side, once `controllerToken` is set
its own API requires the same header too (the pairing page and `/api/health`
stay open).

Regenerating (Security panel) invalidates the old token immediately — update
every scout after.

## Prometheus

`GET /metrics` works with the fleet token when sign-in is on:

```yaml
scrape_configs:
  - job_name: caravan
    static_configs: [{ targets: ["controller:8090"] }]
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
