"""What clients of the entry asked and were answered with an error, over the journal's days.

The owner, 2026-10-12: "keep for 30 days the endpoints a client called and got an error — to
see, say, that it asked /api/show". Read from the proxy's journal, logs/proxy-events/<day>.jsonl,
which the proxy itself keeps 30 days (AGENT_PROXY_LOG_RETENTION_DAYS): the entry's refusals
("blocked") and the requests that finished with 4xx or 5xx ("finished"). Kept per client by its
port — the number a client keeps through a rename — one line per method, path and status, with
how many times and when last. A record from before 1.3.495 has no method: said as none, not
guessed.

A day is read once; today's file only for the whole lines added since, as proxy_stats reads the
days it counts. One reader for the board (`CLIENT_MISSES`), its cache its own.
"""
import json
import time
from datetime import datetime, timedelta

from caravan.admin.paths import AGENT_PROXY_LOG_DIR
from caravan.common.key_entry import KeyEntry


class ClientMisses:
    """The errors each client was answered with, by its port."""

    DAYS = 30
    #: The lines a card shows; the rest are counted.
    SHOWN = 8

    def __init__(self, log_dir=None, clock=time.time, days=DAYS):
        self.log_dir = log_dir or AGENT_PROXY_LOG_DIR
        self.clock = clock
        self.days = days
        self._read = {}   # day → {"offset": bytes read, "misses": {(port, method, path, status): {count, last, reason}}}

    @staticmethod
    def miss_of(row):
        """(port, method, path, status, reason, when) of a journal row that told a client an
        error, or None: a refusal of the entry or a request finished with 4xx/5xx, under a port —
        not the kanban's test of the client, whose answers are the test's (KeyEntry.PROBE_CLIENT)."""
        if not isinstance(row, dict):
            return None
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        if item.get("client") == KeyEntry.PROBE_CLIENT:
            return None
        if row.get("event") == "blocked":
            status = item.get("status")
        elif row.get("event") == "finished":
            status = row.get("status", item.get("status"))
        else:
            return None
        try:
            status, port = int(status), int(item.get("port"))
        except (TypeError, ValueError):
            return None
        if status < 400 or port <= 0:
            return None
        return (port, str(item.get("method") or ""), str(item.get("path") or ""), status,
                str(item.get("reason") or row.get("errorKind") or ""), int(row.get("time") or 0))

    def _day(self, day):
        """The misses of one day's file, read on from where the last reading stopped — at a
        whole line: a line being written is read when it is whole. None for a day not there."""
        path = self.log_dir / f"{day}.jsonl"
        try:
            size = path.stat().st_size
        except OSError:
            self._read.pop(day, None)
            return None
        seen = self._read.get(day) or {"offset": 0, "misses": {}}
        if seen["offset"] > size:
            seen = {"offset": 0, "misses": {}}
        if seen["offset"] < size:
            with path.open("rb") as fh:
                fh.seek(seen["offset"])
                chunk = fh.read(size - seen["offset"])
            whole = chunk[:chunk.rfind(b"\n") + 1]
            misses = dict(seen["misses"])
            for line in whole.splitlines():
                try:
                    found = self.miss_of(json.loads(line))
                except ValueError:
                    continue
                if found is None:
                    continue
                port, method, where, status, reason, when = found
                key = (port, method, where, status)
                was = misses.get(key) or {"count": 0, "last": 0, "reason": ""}
                misses[key] = {"count": was["count"] + 1, "last": max(was["last"], when),
                               "reason": reason if when >= was["last"] else was["reason"]}
            seen = {"offset": seen["offset"] + len(whole), "misses": misses}
        self._read[day] = seen
        return seen

    def of(self, ports):
        """{port: {"items": the newest SHOWN lines, "more": how many more}} over the last DAYS
        days — every port asked for, with no lines when it had no error. None when the journal's
        folder cannot be read: not known is not "no errors"."""
        if not self.log_dir.is_dir():
            return None
        today = datetime.fromtimestamp(self.clock()).date()
        days = [(today - timedelta(days=back)).isoformat() for back in range(self.days)]
        for day in list(self._read):
            if day not in days:
                self._read.pop(day)
        wanted = {int(port) for port in ports}
        total = {}
        for day in days:
            seen = self._day(day)
            for (port, method, where, status), line in (seen or {}).get("misses", {}).items():
                if port not in wanted:
                    continue
                key = (port, method, where, status)
                was = total.get(key)
                if was is None or line["last"] >= was["last"]:
                    total[key] = {"count": line["count"] + (was["count"] if was else 0), "last": line["last"],
                                  "reason": line["reason"]}
                else:
                    total[key] = {**was, "count": was["count"] + line["count"]}
        out = {port: [] for port in wanted}
        for (port, method, where, status), line in total.items():
            out[port].append({"method": method, "path": where, "status": status, **line})
        return {port: {"items": sorted(lines, key=lambda x: (-x["last"], x["path"]))[:self.SHOWN],
                       "more": max(0, len(lines) - self.SHOWN)} for port, lines in out.items()}


CLIENT_MISSES = ClientMisses()
