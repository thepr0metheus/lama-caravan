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

## What this does NOT cover

- **Proxy ports** (`:81xx`) stay open: they are the data plane your agents
  talk to. Keep them LAN-only (firewall) — per-route API keys are a possible
  future addition.
- **TLS**: the admin speaks plain HTTP. If you expose it beyond the LAN, put
  a reverse proxy with TLS in front (the session cookie is not marked Secure,
  so terminate TLS before the browser).
