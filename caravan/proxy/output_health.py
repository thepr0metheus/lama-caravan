"""What the proxy knows about each output's health, and which exit a backup node takes next.

A backup (onError) node used to learn that its main exit was dead the hard
way, on every request: send, fail, replay on the backup. A cloud account whose
quota had run out failed like that for hours — every request paid a doomed
round trip before it reached the exit that worked. Now the proxy REMEMBERS.
A verdict about an output — alive, or dead with the status that said so —
comes from traffic (the handler notes every upstream answer) and, while an
exit sees no traffic, from the idle probe (caravan/proxy/output_probe.py),
once the last verdict is older than VERDICT_TTL_SECONDS. A fresh "dead" sends
the next request straight down the backup exit; an expired one is re-checked
by the next request, or by the probe.

Not every failure is the OUTPUT's failure. A 400 — an oversized prompt, a
bad parameter — is this request's problem: the output answered, and it must
not divert five minutes of everyone's traffic. DEAD_STATUSES lists what
unusable looks like; the rest of 4xx counts as alive.

A client's QUESTION to the port is not a request, and it does not take the
next request's exit. /v1/models, /props, /api/tags, /api/show — what kind of
server is this, which model — is never replayed on the other exit, so a wrong
first choice is not a round trip but an error the client sees and a row on
the incident panel. The backup node sends it to the exit that answers
(discovery_exit). On 2026-09-28 at 03:34 a client restarting after its update
asked ten such questions; all ten went to a cell that had been off for
seventeen days, while the real requests through the same port had been
skipping that cell all along.
"""
import re
import threading
import time

# How long a verdict holds before it is re-checked — the "five minutes of idle".
VERDICT_TTL_SECONDS = 300
# Statuses that mean the output cannot serve anyone right now: no credentials,
# no such model, exhausted quota or rate limit, and every server-side failure.
DEAD_STATUSES = frozenset({401, 402, 403, 404, 408, 429, 500, 502, 503, 504})


def output_id_of_ref(ref):
    """The output id behind a graph edge target, or None for a rule node.

    Health is kept per OUTPUT (`routedOutputId`, the id a resolved route
    carries); an edge that leads to another rule node has no single output
    behind it, so nothing is known about it here — and nothing is skipped.
    """
    text = str(ref or "")
    return text[4:] if text.startswith("out:") and len(text) > 4 else None


class OutputHealth:
    """Per-output verdicts with an expiry, shared by the router, the handler and the probe."""

    #: An exit's LAST word, for a client's question (discovery_exit): it
    #: answered, it has said nothing yet, it failed. Ranked, not weighed.
    ANSWERED, SILENT, FAILED = 2, 1, 0

    def __init__(self, ttl_seconds=VERDICT_TTL_SECONDS):
        self.ttl_seconds = int(ttl_seconds)
        self._rows = {}
        self._lock = threading.Lock()

    def _put(self, output_id, row):
        key = str(output_id or "").strip()
        if not key:
            return
        with self._lock:
            if "lastOkAt" not in row:
                # A failure does not erase WHEN the output last answered: two
                # failing exits are told apart by it (discovery_exit).
                row["lastOkAt"] = (self._rows.get(key) or {}).get("lastOkAt")
            self._rows[key] = row

    def note_ok(self, output_id, source="traffic", now=None):
        """The output answered usefully: alive, from this moment."""
        checked_at = float(now if now is not None else time.time())
        self._put(output_id, {"state": "ok", "status": None, "kind": "", "message": "",
                              "checkedAt": checked_at, "lastOkAt": checked_at,
                              "source": str(source)})

    def note_error(self, output_id, status=None, kind="", message="", source="traffic", now=None):
        """The output could not serve: dead, from this moment, with the reason kept."""
        kind = str(kind or (f"http {int(status)}" if status else "error"))
        # The kind names the status; a message that repeats it ("http 429: …") is trimmed.
        message = re.sub(r"^\s*http\s+\d{3}\s*:\s*", "", str(message or ""))[:200]
        self._put(output_id, {"state": "error", "status": (int(status) if status else None),
                              "kind": kind,
                              "message": message,
                              "checkedAt": float(now if now is not None else time.time()),
                              "source": str(source)})

    def note_status(self, output_id, status, message="", source="traffic", now=None):
        """Read an HTTP answer as a verdict: a request-specific 4xx is ALIVE."""
        try:
            code = int(status)
        except (TypeError, ValueError):
            return
        if code in DEAD_STATUSES:
            self.note_error(output_id, status=code, message=message, source=source, now=now)
        else:
            self.note_ok(output_id, source=source, now=now)

    def row(self, output_id):
        with self._lock:
            found = self._rows.get(str(output_id or ""))
            return dict(found) if found else None

    def is_fresh(self, row, now=None):
        if not row:
            return False
        now = float(now if now is not None else time.time())
        return now - float(row.get("checkedAt") or 0) < self.ttl_seconds

    def is_dead(self, output_id, now=None):
        """Dead means a FRESH error verdict; an expired one is only a memory."""
        found = self.row(output_id)
        return bool(found and found.get("state") == "error" and self.is_fresh(found, now))

    def stale_ids(self, output_ids, now=None):
        """Outputs whose verdict is missing or older than the TTL — the probe's list."""
        now = float(now if now is not None else time.time())
        stale = []
        for output_id in output_ids:
            key = str(output_id or "").strip()
            if not key:
                continue
            found = self.row(key)
            if not found or not self.is_fresh(found, now):
                stale.append(key)
        return stale

    def next_exit(self, main_id, backup_id, now=None):
        """Which exit of a backup node the next request takes: ("main"|"backup", reason).

        Backup only while main is known dead AND backup is not: two dead exits
        go down main, the original order — the handler's replay still follows.
        """
        if not main_id or not backup_id:
            return "main", ""
        if self.is_dead(main_id, now) and not self.is_dead(backup_id, now):
            found = self.row(main_id) or {}
            return "backup", f"main is down: {found.get('kind') or 'error'}"
        return "main", ""

    def _last_word(self, output_id):
        """(rank of the exit's last word, when it last answered or None)."""
        found = self.row(output_id)
        if not found:
            return self.SILENT, None
        return (self.ANSWERED if found.get("state") == "ok" else self.FAILED), found.get("lastOkAt")

    def discovery_exit(self, main_id, backup_id):
        """Which exit of a backup node a client's QUESTION takes: ("main"|"backup", reason).

        next_exit keeps main until a FRESH verdict says it is dead: a request
        that fails there is replayed on the backup, so optimism costs one
        round trip. A question is never replayed (caravan/common/request_kind.py),
        so the same optimism costs the client an error. It goes to the exit
        whose last word was an answer, over one that has said nothing yet,
        over one whose last word was a failure — however old the word: the
        probe renews both exits' words every five minutes, and a verdict that
        expired half a minute ago is still the last thing known. Between two
        failing exits, the one that answered more recently. Anything else
        equal — both answering, both silent — main, where requests go too.
        """
        if not main_id or not backup_id:
            return "main", ""
        main_word, main_ok_at = self._last_word(main_id)
        backup_word, backup_ok_at = self._last_word(backup_id)
        if backup_word > main_word:
            if main_word == self.FAILED:
                found = self.row(main_id) or {}
                return "backup", f"main is not answering: {found.get('kind') or 'error'}"
            return "backup", "main has not answered yet"
        if (main_word == backup_word == self.FAILED and backup_ok_at is not None
                and (main_ok_at is None or backup_ok_at > main_ok_at)):
            return "backup", "backup answered more recently"
        return "main", ""

    def snapshot(self, now=None):
        """Every verdict, with what a reader needs to show it without re-deriving."""
        now = float(now if now is not None else time.time())
        with self._lock:
            rows = {key: dict(row) for key, row in self._rows.items()}
        out = {}
        for key, row in rows.items():
            age = max(0, int(now - float(row.get("checkedAt") or 0)))
            row["ageSec"] = age
            row["fresh"] = age < self.ttl_seconds
            row["retryInSec"] = max(0, self.ttl_seconds - age)
            out[key] = row
        return out

    def load_snapshot(self, rows):
        """Mirror another process's verdicts — the whole set, replacing this one.

        The controller resolves routes with the same graph code as the proxy,
        but in its own process, where nothing ever noted an answer; fed the
        proxy's snapshot from the state file first, it resolves the exit the
        proxy would take, and the board shows that exit's window.
        """
        fresh = {}
        for output_id, row in (rows or {}).items():
            if not isinstance(row, dict) or row.get("state") not in ("ok", "error"):
                continue
            try:
                checked_at = float(row.get("checkedAt") or 0)
            except (TypeError, ValueError):
                continue
            if checked_at <= 0:
                continue
            try:
                last_ok_at = float(row.get("lastOkAt") or 0)
            except (TypeError, ValueError):
                last_ok_at = 0.0
            if row.get("state") == "ok":
                # An "ok" verdict IS an answer at checkedAt; a file written
                # before lastOkAt existed still says that much.
                last_ok_at = max(last_ok_at, checked_at)
            fresh[str(output_id)] = {
                "state": row.get("state"),
                "status": (int(row["status"]) if row.get("status") else None),
                "kind": str(row.get("kind") or ""),
                "message": str(row.get("message") or "")[:200],
                "checkedAt": checked_at,
                "lastOkAt": last_ok_at if last_ok_at > 0 else None,
                "source": str(row.get("source") or "proxy"),
            }
        with self._lock:
            self._rows = fresh

    def clear(self):
        with self._lock:
            self._rows.clear()


output_health = OutputHealth()
