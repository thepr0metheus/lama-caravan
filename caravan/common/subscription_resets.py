"""Durable reset attempts and confirmed quota invalidations, shared by both daemons."""
import fcntl
import json
from contextlib import contextmanager
from caravan.common.fsio import atomic_write_text


class SubscriptionResetJournal:
    def __init__(self, path):
        self.path = path

    def read(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"attempts": {}, "resets": {}}

    def reset_at(self, account_id):
        try:
            return float(self.read().get("resets", {}).get(account_id) or 0)
        except (OSError, ValueError, TypeError):
            return 0

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield self.read()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def write(self, data):
        # Keep unresolved attempts, even when trimming the completed journal.
        rows = data["attempts"]
        completed = sorted((k for k in rows if rows[k].get("outcome")),
                           key=lambda k: rows[k]["at"])
        for key in completed[:-100]:
            rows.pop(key)
        atomic_write_text(self.path, json.dumps(data), mkdir=True, chmod=0o600)
