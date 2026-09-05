"""The accounts database: who may drive the fleet, and what proves it.

A SQLite file at mode 0600 holding three tables — users, sessions, and a small
meta table for the fleet token the scouts authenticate with. The class exists
because these are not three independent stores: a user's rows and their sessions
have to die together, the caches have to be invalidated by the same operations
that write, and the schema has to be brought forward on open.

What is deliberate here, and would be easy to "simplify" away:

* **Passwords are never stored, and never compared as bytes by ==.** Each user
  has their own salt, so two accounts with one password share nothing on disk,
  and the comparison is constant-time.
* **An unknown user costs the same as a wrong password.** The lookup that finds
  nothing still runs a hash, because a login form that answers faster for names
  that do not exist is a way to enumerate the ones that do.
* **Sessions are stored as a hash of the token.** Reading the database does not
  hand anyone a live session.
* **The last admin cannot be demoted or deleted.** Not paternalism: there is no
  other way back in, and the UI offers no "disable auth".
* **The caches are short and invalidated by writes.** `enabled` for three
  seconds, sessions for five — long enough to spare a per-request query, short
  enough that a revoked session cannot outlive it by much. Every mutation clears
  what it invalidates rather than waiting for the clock.
"""
import hashlib
import hmac
import os
import secrets
import sqlite3
import time


class AuthStore:
    """The accounts database, its schema, its caches and its rate limiter."""

    #: How long a session lives without being renewed.
    session_ttl = 30 * 24 * 3600
    #: PBKDF2 rounds for a NEW password. Stored per user alongside the hash, so
    #: raising this does not invalidate anybody — their rows keep the count they
    #: were written with until the next password change.
    iterations = 200_000
    #: Wrong passwords from one address before it is made to wait.
    max_fails = 5
    lockout_seconds = 60
    enabled_ttl = 3
    session_ttl_cache = 5

    def __init__(self, path):
        self.path = path
        self.login_fails = {}       # ip -> [fails, locked_until]
        self.session_cache = {}     # token_hash -> (info, cached_until)
        self.enabled_cache = [None, 0.0]

    # ── the file ─────────────────────────────────────────────────────────────
    def connect(self):
        """A connection with the schema present and brought forward.

        Cheap enough to do per call: SQLite parses these DDL statements against
        an existing schema in microseconds, and the alternative — a connection
        held open across threads — is a class of bug this does not need.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fresh = not self.path.exists()
        conn = sqlite3.connect(str(self.path), timeout=5)
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
        # Roles arrived after the first accounts did; existing rows default to
        # admin, which is what they effectively were.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if "role" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        if fresh:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        return conn

    # ── passwords ────────────────────────────────────────────────────────────
    def hash_password(self, password, salt, iters=None):
        return hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                                   salt, iters or self.iterations)

    def new_salt(self):
        return secrets.token_bytes(16)

    def password_matches(self, password, salt, digest, iters):
        """Constant-time, and the caller must not shortcut it for a missing user
        — see `absorb_timing`."""
        return hmac.compare_digest(self.hash_password(password, salt, iters), digest)

    def absorb_timing(self, password):
        """Spend the time a real check would have, for a user who does not exist.

        Without it the form answers measurably faster for names that were never
        registered, which turns the login page into a list of the ones that were.
        """
        self.hash_password(password, b"caravan-timing-pad")

    # ── rate limiting ────────────────────────────────────────────────────────
    def locked_until(self, ip):
        return self.login_fails.get(ip or "?", [0, 0])[1]

    def note_failure(self, ip, now):
        fails = self.login_fails.get(ip or "?", [0, 0])
        fails[0] += 1
        if fails[0] >= self.max_fails:
            fails[:] = [0, now + self.lockout_seconds]
        self.login_fails[ip or "?"] = fails

    def note_success(self, ip):
        self.login_fails.pop(ip or "?", None)

    # ── sessions ─────────────────────────────────────────────────────────────
    @staticmethod
    def token_hash(token):
        return hashlib.sha256((token or "").encode()).hexdigest()

    def new_token(self):
        return secrets.token_urlsafe(32)

    def cache_session(self, token_hash, info, now):
        self.session_cache[token_hash] = (info, now + self.session_ttl_cache)

    def cached_session(self, token_hash, now):
        hit = self.session_cache.get(token_hash)
        return hit[0] if hit and now < hit[1] else None

    def forget_session(self, token_hash):
        self.session_cache.pop(token_hash, None)

    # ── whether authentication is on at all ──────────────────────────────────
    def invalidate(self):
        """After anything that changes who exists or what they may do.

        Both caches, because a role change alters what a LIVE session may do and
        a deletion alters whether auth is on at all — waiting out the clock would
        leave a demoted admin with admin rights for the rest of the window.
        """
        self.enabled_cache[0] = None
        self.enabled_cache[1] = 0.0
        self.session_cache.clear()

    def fleet_token_value(self):
        return "caravan-" + secrets.token_urlsafe(24)

    @staticmethod
    def tokens_match(candidate, token):
        return bool(token) and hmac.compare_digest(str(candidate or ""), token)

    @staticmethod
    def now():
        return time.time()
