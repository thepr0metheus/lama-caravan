#!/usr/bin/env python3
"""What the authentication store does, pinned before it becomes a class.

This is the code that decides who may drive the fleet, and it had no test at
all. Every property below is one a rewrite could weaken without anything going
red — a session that outlives its revocation, a password check that answers on a
missing user faster than on a present one, a last admin demoted to viewer and
nobody left who can promote them back.

Each case runs in its own process against its own SQLite file, because the
module caches: `_ENABLED_CACHE` for three seconds and `_SESSION_CACHE` for five,
and a test that shared them with its neighbours would pass on a stale answer.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


def run(body):
    """A snippet with the auth database pointed at a throwaway file."""
    script = ("import json, sys\n"
              "from caravan.admin import auth\n"
              "from caravan.common.errors import AppError\n"
              "def attempt(fn, *a, **k):\n"
              "    try: return {'ok': fn(*a, **k)}\n"
              "    except AppError as exc: return {'refused': str(exc)}\n"
              + body)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, LLAMA_ADMIN_AUTH_DB=str(Path(tmp) / "auth.db"),
                   LLAMA_ADMIN_STATE=str(Path(tmp) / "admin.json"), PYTHONPATH=str(ROOT))
        out = subprocess.run([sys.executable, "-c", script], env=env, cwd=ROOT,
                             capture_output=True, text=True)
        db = Path(tmp) / "auth.db"
        mode = oct(db.stat().st_mode & 0o777) if db.exists() else ""
        return out, mode


def main():
    # ── the panel is open until somebody creates an account ──────────────────
    out, mode = run('''
before = auth.auth_enabled()
auth.create_user("ann", "correct horse battery")
auth._ENABLED_CACHE[0] = None            # the cache is 3s; this is not what we test
after = auth.auth_enabled()
print(json.dumps({"before": before, "after": after}))
''')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("no accounts means auth is off", got["before"] is False, str(got))
        check("the first account turns it on", got["after"] is True, str(got))
        check("the database is readable only by its owner", mode == "0o600", mode)
    else:
        check("auth_enabled", False, out.stderr.strip()[-300:])

    # ── passwords ────────────────────────────────────────────────────────────
    out, _ = run('''
auth.create_user("ann", "correct horse battery")
print(json.dumps({
  "right password": attempt(auth.verify_login, "ann", "correct horse battery"),
  "wrong password": attempt(auth.verify_login, "ann", "correct horse batteru"),
  "no such user": attempt(auth.verify_login, "bob", "correct horse battery"),
  "empty password": attempt(auth.verify_login, "ann", ""),
  "too short at creation": attempt(auth.create_user, "cy", "short"),
  "duplicate name": attempt(auth.create_user, "ann", "another long one"),
}, default=str))
''')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("the right password logs in", got["right password"].get("ok", {}).get("username") == "ann",
              str(got["right password"]))
        check("one wrong character does not", "refused" in got["wrong password"], str(got["wrong password"]))
        check("an unknown user is refused the same way as a wrong password",
              got["no such user"].get("refused") == got["wrong password"].get("refused"),
              f'{got["no such user"]} vs {got["wrong password"]}')
        check("an empty password is refused", "refused" in got["empty password"])
        check("a short password is refused at creation",
              "8 characters" in str(got["too short at creation"].get("refused")), str(got["too short at creation"]))
        check("a duplicate username is refused",
              "already exists" in str(got["duplicate name"].get("refused")), str(got["duplicate name"]))
    else:
        check("passwords", False, out.stderr.strip()[-300:])

    # ── the stored form of a password ────────────────────────────────────────
    out, _ = run('''
import sqlite3
auth.create_user("ann", "correct horse battery")
auth.create_user("bob", "correct horse battery")     # the SAME password
with auth._db() as c:
    rows = c.execute("SELECT username, salt, hash, iters FROM users ORDER BY username").fetchall()
by = {r[0]: r for r in rows}
print(json.dumps({
  "same password, different salt": by["ann"][1] != by["bob"][1],
  "same password, different hash": by["ann"][2] != by["bob"][2],
  "plaintext is nowhere": all(b"correct horse battery" not in bytes(r[2]) for r in rows),
  "iterations recorded": by["ann"][3],
}))
''')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("two accounts with one password get different salts", got["same password, different salt"])
        check("…and therefore different hashes", got["same password, different hash"])
        check("the password itself is not stored", got["plaintext is nowhere"])
        check("the iteration count is stored with the hash, so it can be raised later",
              isinstance(got["iterations recorded"], int) and got["iterations recorded"] >= 100000,
              str(got["iterations recorded"]))
    else:
        check("password storage", False, out.stderr.strip()[-300:])

    # ── sessions ─────────────────────────────────────────────────────────────
    out, _ = run('''
import sqlite3
u = auth.create_user("ann", "correct horse battery")
uid = auth.verify_login("ann", "correct horse battery")["id"]
tok = auth.create_session(uid, ip="10.0.0.1", ua="curl")
live = auth.validate_session(tok)
with auth._db() as c:
    stored = [r[0] for r in c.execute("SELECT token_hash FROM sessions")]
auth._SESSION_CACHE.clear()
auth.delete_session(tok)
auth._SESSION_CACHE.clear()
print(json.dumps({
  "a fresh session validates": live,
  "the token itself is not stored": tok not in stored,
  "after delete": auth.validate_session(tok),
  "garbage token": auth.validate_session("nonsense"),
  "empty token": auth.validate_session(""),
}))
''')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("a fresh session names its user and role",
              got["a fresh session validates"] == {"user": "ann", "role": "admin"},
              str(got["a fresh session validates"]))
        check("the database keeps a hash, not the token",
              got["the token itself is not stored"] is True)
        check("a deleted session stops validating", got["after delete"] == {})
        check("a made-up token validates to nothing", got["garbage token"] == {})
        check("no token validates to nothing", got["empty token"] == {})
    else:
        check("sessions", False, out.stderr.strip()[-300:])

    # ── expiry and revocation ────────────────────────────────────────────────
    out, _ = run('''
import time
auth.create_user("ann", "correct horse battery")
uid = auth.verify_login("ann", "correct horse battery")["id"]
mine = auth.create_session(uid)
other = auth.create_session(uid)
stale = auth.create_session(uid)
with auth._db() as c:                      # age one session past its expiry
    import hashlib
    th = hashlib.sha256(stale.encode()).hexdigest()
    c.execute("UPDATE sessions SET expires_at=? WHERE token_hash=?", (int(time.time()) - 1, th))
auth._SESSION_CACHE.clear()
expired = auth.validate_session(stale)
listed_before = len(auth.list_sessions())
killed = auth.revoke_other_sessions(mine)
auth._SESSION_CACHE.clear()
print(json.dumps({
  "an expired session is not valid": expired,
  "an expired session is not listed": listed_before,
  "killed": killed,
  "mine survives": auth.validate_session(mine),
  "the other one does not": auth.validate_session(other),
}))
''')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("an expired session validates to nothing", got["an expired session is not valid"] == {})
        check("an expired session is not offered in the list",
              got["an expired session is not listed"] == 2, str(got["an expired session is not listed"]))
        check("revoking the others keeps the caller signed in",
              got["mine survives"] == {"user": "ann", "role": "admin"}, str(got))
        check("…and signs the others out", got["the other one does not"] == {}, str(got))
    else:
        check("expiry and revocation", False, out.stderr.strip()[-300:])

    # ── roles ────────────────────────────────────────────────────────────────
    out, _ = run('''
auth.create_user("ann", "correct horse battery")
r = {"demote the only admin": attempt(auth.set_role, "ann", "viewer")}
auth.create_user("bob", "another long password", role="viewer")
r["a viewer can be created"] = [u for u in auth.list_users() if u["username"] == "bob"]
r["promote the viewer"] = attempt(auth.set_role, "bob", "admin")
r["now ann can be demoted"] = attempt(auth.set_role, "ann", "viewer")
r["unknown role"] = attempt(auth.set_role, "bob", "wizard")
r["no such user"] = attempt(auth.set_role, "zoe", "admin")
r["delete the last user"] = attempt(auth.delete_user, "ann")
print(json.dumps(r, default=str))
''')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("the last admin cannot be demoted",
              "last admin" in str(got["demote the only admin"].get("refused")),
              str(got["demote the only admin"]))
        check("a viewer account can be created",
              got["a viewer can be created"] and got["a viewer can be created"][0]["role"] == "viewer",
              str(got["a viewer can be created"]))
        check("once there are two admins the first may step down",
              "refused" not in got["now ann can be demoted"], str(got["now ann can be demoted"]))
        check("an unknown role is refused",
              "admin or viewer" in str(got["unknown role"].get("refused")), str(got["unknown role"]))
        check("a role change for a user who is not there is a 404",
              "no such user" in str(got["no such user"].get("refused")), str(got["no such user"]))
    else:
        check("roles", False, out.stderr.strip()[-300:])

    # ── deleting a user takes their sessions with them ───────────────────────
    out, _ = run('''
auth.create_user("ann", "correct horse battery")
auth.create_user("bob", "another long password")
uid = auth.verify_login("bob", "another long password")["id"]
tok = auth.create_session(uid)
auth.delete_user("bob")
auth._SESSION_CACHE.clear()
print(json.dumps({"session after the user is gone": auth.validate_session(tok),
                  "users left": [u["username"] for u in auth.list_users()]}))
''')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("deleting a user signs their sessions out",
              got["session after the user is gone"] == {}, str(got))
        check("and leaves the others alone", got["users left"] == ["ann"], str(got))
    else:
        check("user deletion", False, out.stderr.strip()[-300:])

    # ── the fleet token (scouts ↔ controller) ────────────────────────────────
    out, _ = run('''
first = auth.fleet_token_ensure()
again = auth.fleet_token_ensure()
rolled = auth.fleet_token_regenerate()
print(json.dumps({
  "ensure is idempotent": first == again,
  "it is prefixed": first.startswith("caravan-"),
  "long enough to be a secret": len(first) >= 24,
  "regenerate changes it": rolled != first,
  "the old one stops working": auth.fleet_token_verify(first),
  "the new one works": auth.fleet_token_verify(rolled),
  "empty is never accepted": auth.fleet_token_verify(""),
  "a wrong one is not": auth.fleet_token_verify("caravan-nope"),
}))
''')
    if out.returncode == 0:
        got = json.loads(out.stdout)
        check("asking twice returns the same fleet token", got["ensure is idempotent"])
        check("the fleet token is recognisable and long", got["it is prefixed"] and got["long enough to be a secret"])
        check("regenerating replaces it", got["regenerate changes it"])
        check("the replaced token stops working", got["the old one stops working"] is False)
        check("the new token works", got["the new one works"] is True)
        check("an empty token is never accepted", got["empty is never accepted"] is False)
        check("a wrong token is not accepted", got["a wrong one is not"] is False)
    else:
        check("fleet token", False, out.stderr.strip()[-300:])

    print(f"\n  {len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
