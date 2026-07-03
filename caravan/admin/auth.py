"""Accounts, sessions and the fleet token (SQLite, stdlib-only).

Auth is OFF until the first user exists (open homelab default). Creating the
first account (UI Security panel or `python3 -m caravan.admin.auth
create-user`) turns the guard on for every route except the login page, the
auth bootstrap endpoints and the machine endpoints, which switch to the
fleet token (scouts put it into config.json as `controllerToken`).

The DB lives next to admin.json (LLAMA_ADMIN_AUTH_DB to override), chmod 0600.
The fleet token is stored in plaintext there — the controller must SEND it to
scouts, so a hash would not do; same trust model as provider-secrets.json.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from http import cookies as http_cookies
from pathlib import Path

from caravan.admin.paths import ADMIN_STATE_FILE
from caravan.common.errors import AppError

AUTH_DB = Path(os.environ.get("LLAMA_ADMIN_AUTH_DB",
    str(ADMIN_STATE_FILE.parent / "auth.db")))

SESSION_COOKIE = "caravan_session"
SESSION_TTL = 30 * 24 * 3600          # 30 days
PBKDF2_ITERS = 200_000
_LOGIN_FAILS: dict = {}               # ip -> [fails, lock_until]
_SESSION_CACHE: dict = {}             # token_hash -> (username, cached_until)
_ENABLED_CACHE = [None, 0.0]          # [bool, cached_until]


def _db():
    AUTH_DB.parent.mkdir(parents=True, exist_ok=True)
    fresh = not AUTH_DB.exists()
    conn = sqlite3.connect(str(AUTH_DB), timeout=5)
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
        salt BLOB NOT NULL, hash BLOB NOT NULL, iters INTEGER NOT NULL,
        created_at INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        last_seen INTEGER NOT NULL, ip TEXT, ua TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    if "role" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
    if fresh:
        try:
            os.chmod(AUTH_DB, 0o600)
        except OSError:
            pass
    return conn


def auth_enabled() -> bool:
    now = time.time()
    if _ENABLED_CACHE[0] is not None and now < _ENABLED_CACHE[1]:
        return _ENABLED_CACHE[0]
    with _db() as conn:
        enabled = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    _ENABLED_CACHE[0] = enabled
    _ENABLED_CACHE[1] = now + 3
    return enabled


def _hash_password(password: str, salt: bytes, iters: int = PBKDF2_ITERS) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)


def create_user(username: str, password: str, role: str = "admin") -> dict:
    username = str(username or "").strip()
    role = str(role or "admin").strip().lower()
    if role not in ("admin", "viewer"):
        raise AppError("role must be admin or viewer")
    if not username or len(username) > 64:
        raise AppError("username is required (max 64 chars)")
    if len(password or "") < 8:
        raise AppError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = _hash_password(password, salt)
    try:
        with _db() as conn:
            conn.execute(
                "INSERT INTO users (username, salt, hash, iters, created_at, role) VALUES (?,?,?,?,?,?)",
                (username, salt, digest, PBKDF2_ITERS, int(time.time()), role))
    except sqlite3.IntegrityError:
        raise AppError(f"user {username} already exists", 409)
    _ENABLED_CACHE[0] = None
    return {"username": username, "role": role}

def set_role(username: str, role: str) -> None:
    role = str(role or "").strip().lower()
    if role not in ("admin", "viewer"):
        raise AppError("role must be admin or viewer")
    with _db() as conn:
        if role == "viewer":
            admins = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND username != ?",
                (username,)).fetchone()[0]
            if admins == 0:
                raise AppError("cannot demote the last admin", 400)
        cur = conn.execute("UPDATE users SET role=? WHERE username=?", (role, username))
        if cur.rowcount == 0:
            raise AppError(f"no such user: {username}", 404)
    _SESSION_CACHE.clear()


def set_password(username: str, password: str) -> None:
    if len(password or "") < 8:
        raise AppError("password must be at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = _hash_password(password, salt)
    with _db() as conn:
        cur = conn.execute("UPDATE users SET salt=?, hash=?, iters=? WHERE username=?",
                           (salt, digest, PBKDF2_ITERS, username))
        if cur.rowcount == 0:
            raise AppError(f"no such user: {username}", 404)


def delete_user(username: str) -> None:
    with _db() as conn:
        row = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if not row:
            raise AppError(f"no such user: {username}", 404)
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count <= 1:
            raise AppError("cannot delete the last user — disable auth is not supported from the UI", 400)
        conn.execute("DELETE FROM sessions WHERE user_id=?", (row[0],))
        conn.execute("DELETE FROM users WHERE id=?", (row[0],))
    _ENABLED_CACHE[0] = None
    _SESSION_CACHE.clear()


def list_users() -> list:
    with _db() as conn:
        rows = conn.execute("SELECT username, created_at, role FROM users ORDER BY id").fetchall()
    return [{"username": r[0], "createdAt": r[1], "role": r[2] or "admin"} for r in rows]


def verify_login(username: str, password: str, ip: str = "") -> dict:
    now = time.time()
    fails = _LOGIN_FAILS.get(ip or "?", [0, 0])
    if now < fails[1]:
        raise AppError("too many attempts — try again in a minute", 429)
    with _db() as conn:
        row = conn.execute(
            "SELECT id, username, salt, hash, iters FROM users WHERE username=?",
            (str(username or "").strip(),)).fetchone()  # role resolved per-session
    ok = False
    if row:
        ok = hmac.compare_digest(_hash_password(password or "", row[2], row[4]), row[3])
    else:
        _hash_password(password or "", b"caravan-timing-pad")  # constant-ish time
    if not ok:
        fails[0] += 1
        if fails[0] >= 5:
            fails[:] = [0, now + 60]
        _LOGIN_FAILS[ip or "?"] = fails
        raise AppError("invalid username or password", 401)
    _LOGIN_FAILS.pop(ip or "?", None)
    return {"id": row[0], "username": row[1]}


def create_session(user_id: int, ip: str = "", ua: str = "") -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen, ip, ua) VALUES (?,?,?,?,?,?,?)",
            (token_hash, user_id, now, now + SESSION_TTL, now, ip[:64], ua[:160]))
    return token


def validate_session(token: str) -> dict:
    """Return {'user': name, 'role': role} for a live session, or {} if invalid."""
    if not token:
        return {}
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.time()
    cached = _SESSION_CACHE.get(token_hash)
    if cached and now < cached[1]:
        return cached[0]
    with _db() as conn:
        row = conn.execute(
            """SELECT s.last_seen, s.expires_at, u.username, u.role FROM sessions s
               JOIN users u ON u.id = s.user_id WHERE s.token_hash=?""",
            (token_hash,)).fetchone()
        if not row or row[1] < now:
            _SESSION_CACHE.pop(token_hash, None)
            return {}
        if now - row[0] > 60:
            conn.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",
                         (int(now), token_hash))
    info = {"user": row[2], "role": row[3] or "admin"}
    _SESSION_CACHE[token_hash] = (info, now + 5)
    return info


def delete_session(token: str) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
    _SESSION_CACHE.pop(token_hash, None)


def list_sessions() -> list:
    now = int(time.time())
    with _db() as conn:
        rows = conn.execute(
            """SELECT s.token_hash, u.username, s.created_at, s.last_seen, s.ip, s.ua
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.expires_at >= ? ORDER BY s.last_seen DESC""", (now,)).fetchall()
    return [{"id": r[0][:12], "username": r[1], "createdAt": r[2],
             "lastSeen": r[3], "ip": r[4] or "", "ua": (r[5] or "")[:60]} for r in rows]


def revoke_other_sessions(current_token: str) -> int:
    """Kill every session except the caller's own; returns how many died."""
    keep = hashlib.sha256(current_token.encode()).hexdigest() if current_token else ""
    with _db() as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
        killed = 0
        for (th,) in rows:
            if th == keep:
                continue
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
            _SESSION_CACHE.pop(th, None)
            killed += 1
    return killed


def revoke_session(short_id: str) -> None:
    with _db() as conn:
        rows = conn.execute("SELECT token_hash FROM sessions").fetchall()
        for (th,) in rows:
            if th.startswith(short_id):
                conn.execute("DELETE FROM sessions WHERE token_hash=?", (th,))
                _SESSION_CACHE.pop(th, None)
                return
    raise AppError("session not found", 404)


# ── fleet token (machine endpoints: scouts <-> controller) ──────────────────

def fleet_token_get() -> str:
    with _db() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='fleet_token'").fetchone()
    return row[0] if row else ""


def fleet_token_ensure() -> str:
    token = fleet_token_get()
    if token:
        return token
    token = "caravan-" + secrets.token_urlsafe(24)
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('fleet_token', ?)", (token,))
    return token


def fleet_token_regenerate() -> str:
    token = "caravan-" + secrets.token_urlsafe(24)
    with _db() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('fleet_token', ?)", (token,))
    return token


def fleet_token_verify(candidate: str) -> bool:
    token = fleet_token_get()
    return bool(token) and hmac.compare_digest(str(candidate or ""), token)


# ── request-side helpers (used by the dispatcher) ────────────────────────────

def session_from_handler(handler) -> dict:
    """{'user','role'} for the request's cookie session, or {}."""
    raw = handler.headers.get("Cookie") or ""
    try:
        jar = http_cookies.SimpleCookie(raw)
        morsel = jar.get(SESSION_COOKIE)
        return validate_session(morsel.value) if morsel else {}
    except Exception:
        return {}


def session_cookie_header(token: str, clear: bool = False) -> str:
    if clear:
        return f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
    return f"{SESSION_COOKIE}={token}; Path=/; Max-Age={SESSION_TTL}; HttpOnly; SameSite=Lax"


LOGIN_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LAMA CARAVAN — sign in</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: flex; align-items: center;
         justify-content: center; background: #0e1116; color: #e6e6ea;
         font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
  .card { width: 100%; max-width: 360px; background: #171a22;
          border: 1px solid #2a2e3b; border-radius: 14px; padding: 26px 28px; }
  h1 { font-size: 19px; margin: 0 0 2px; }
  .sub { color: #8b8b96; font-size: 12.5px; margin: 0 0 18px; }
  label { display: block; font-size: 12px; color: #9aa3b2; margin: 12px 0 4px;
          text-transform: uppercase; letter-spacing: .05em; }
  input { width: 100%; background: #0e1116; color: #e6e6ea;
          border: 1px solid #2a2e3b; border-radius: 8px; padding: 10px 12px;
          font-size: 14px; }
  input:focus { outline: none; border-color: #4a7dbd; }
  button { width: 100%; margin-top: 18px; background: #2e6bb0; color: #fff;
           border: 0; border-radius: 8px; padding: 11px; font-size: 14px;
           font-weight: 600; cursor: pointer; }
  button:hover { background: #3a7cc4; }
  .err { color: #ec7063; font-size: 13px; margin: 10px 0 0; min-height: 18px; }
</style>
</head>
<body>
  <form class="card" id="f">
    <h1>&#129433; LAMA CARAVAN</h1>
    <p class="sub">Sign in to the fleet controller</p>
    <label for="u">Username</label>
    <input id="u" autocomplete="username" autofocus>
    <label for="p">Password</label>
    <input id="p" type="password" autocomplete="current-password">
    <button type="submit">Sign in</button>
    <p class="err" id="e"></p>
  </form>
<script>
document.getElementById("f").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var e = document.getElementById("e");
  e.textContent = "";
  fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: document.getElementById("u").value.trim(),
      password: document.getElementById("p").value
    })
  }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
    .then(function (res) {
      if (res.ok && res.j.ok) { window.location = "/"; }
      else { e.textContent = res.j.error || "login failed"; }
    }).catch(function (err) { e.textContent = String(err); });
});
</script>
</body>
</html>
"""


def main(argv=None):
    """CLI for prod ops: create-user / set-password / list / fleet-token."""
    import argparse
    import getpass
    parser = argparse.ArgumentParser(prog="python3 -m caravan.admin.auth")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_create = sub.add_parser("create-user"); p_create.add_argument("username")
    p_create.add_argument("--role", choices=["admin", "viewer"], default="admin")
    p_pass = sub.add_parser("set-password"); p_pass.add_argument("username")
    sub.add_parser("list")
    sub.add_parser("fleet-token")
    args = parser.parse_args(argv)
    if args.cmd == "create-user":
        password = getpass.getpass("Password (min 8 chars): ")
        create_user(args.username, password, role=args.role)
        print(f"user {args.username} ({args.role}) created; auth is now ON")
        print(f"fleet token (put into each scout's config as controllerToken): {fleet_token_ensure()}")
    elif args.cmd == "set-password":
        set_password(args.username, getpass.getpass("New password: "))
        print("password updated")
    elif args.cmd == "list":
        for u in list_users():
            print(u["username"], "·", u["role"])
        print(f"auth enabled: {auth_enabled()}")
    elif args.cmd == "fleet-token":
        print(fleet_token_ensure())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
