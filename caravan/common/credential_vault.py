"""One OAuth renewal owner across the controller and proxy processes, and the
one writer of the credential document.

Refresh tokens rotate: copying one into a test account or letting both services
renew it at once destroys the other copy. Per-account file locks serialize
renewal, and a short document lock merges writes for unrelated accounts.

Every write re-reads the document under that lock. A writer that read it,
changed one entry and wrote all of it back without the lock put a spent refresh
token back whenever a renewal landed in between, and the subscription needed a
new login: the board's "set key" did that until 2026-10-07.
scripts/check_oauth_owner.py keeps the document to this one writer.
"""
import contextlib
import fcntl
import json
import time
import urllib.parse
import urllib.request

from caravan.common.fsio import atomic_write_text


class CredentialVault:
    def __init__(self, path, clock=time.time, request=urllib.request.urlopen):
        self.path, self.clock, self.request = path, clock, request

    def read(self):
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("credential document must be an object")
        return raw

    def entry(self, account_id):
        entry = self.read().get(str(account_id))
        return {"apiKey": entry} if isinstance(entry, str) else dict(entry or {})

    @contextlib.contextmanager
    def locked(self, suffix):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        path = self.path.with_name(self.path.name + suffix + ".lock")
        with path.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def put_oauth(self, account_id, oauth):
        with self.locked("." + str(account_id)):
            return self._put_oauth(account_id, oauth)

    def put_api_key(self, account_id, key):
        """Set one account's API key. Every other entry, and this account's
        OAuth tokens, stay as the file holds them at the moment of the write.

        Only the document lock: the account lock is the renewal's, held across
        a token request, and a key write has no reason to wait one out. The
        renewal re-reads under the document lock, so it keeps this key.
        """
        account_id = str(account_id)
        with self.locked(".write"):
            data = self.read()
            entry = data.get(account_id)
            entry = dict(entry) if isinstance(entry, dict) else {}
            entry["apiKey"] = key
            data[account_id] = entry
            self._write(data)

    def replace(self, document):
        """Write a whole document (a settings restore) under the document lock.

        A renewal waiting on its token request when the restore lands writes its
        fresh token into the restored document: the restored copy of that token
        is older, so it is spent already. An account the restored document lacks
        comes back then, holding only that token.
        """
        if not isinstance(document, dict):
            raise ValueError("credential document must be an object")
        with self.locked(".write"):
            self._write(document)

    def delete(self, account_id):
        """Remove this registration, never revoke other logins of its identity.

        Use the renewal lock and merge under the write lock: a refresh must
        not put a deleted credential back or lose a different account's update.
        Answers the entry it removed — the tokens a sign-out at the provider
        ends, as they were at the last renewal — or None when none was stored.
        """
        account_id = str(account_id)
        with self.locked("." + account_id):
            with self.locked(".write"):
                data = self.read()
                if account_id not in data:
                    return None
                removed = data.pop(account_id)
                self._write(data)
                return removed

    def _put_oauth(self, account_id, oauth):
        with self.locked(".write"):
            data = self.read()
            entry = data.get(account_id)
            entry = dict(entry) if isinstance(entry, dict) else {}
            entry["oauth"] = oauth
            data[account_id] = entry
            self._write(data)
        return oauth

    def _write(self, data):
        """The one shape of the file on disk: whole or not at all, 0600 from the
        first byte it holds under its own name. Callers hold the document lock."""
        atomic_write_text(self.path, json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                          chmod=0o600, mkdir=True)

    def oauth(self, account_id, config, force=False):
        with self.locked("." + str(account_id)):
            oauth = dict(self.entry(account_id).get("oauth") or {})
            expires = int(oauth.get("expiresAt") or 0)
            if not force and (not expires or expires - self.clock() >= 60):
                return oauth
            if not oauth.get("refreshToken") or not config.get("tokenUrl"):
                return oauth
            request = urllib.request.Request(config["tokenUrl"], data=urllib.parse.urlencode({
                "grant_type": "refresh_token", "refresh_token": oauth["refreshToken"],
                "client_id": config.get("clientId") or ""}).encode("ascii"),
                headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
            with self.request(request, timeout=15) as response:
                tokens = json.loads(response.read().decode("utf-8"))
            if not tokens.get("access_token"):
                raise ValueError("OAuth renewal returned no access token")
            oauth["accessToken"] = tokens["access_token"]
            oauth["refreshToken"] = tokens.get("refresh_token") or oauth["refreshToken"]
            oauth["obtainedAt"] = int(self.clock())
            if tokens.get("expires_in"):
                oauth["expiresAt"] = int(self.clock()) + int(tokens["expires_in"])
            return self._put_oauth(account_id, oauth)
