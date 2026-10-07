"""The caravan's own time per proxy port, read from the proxy's journal
(ProxyLatencyDigest; the proxy measures it, caravan/proxy/request_clock.py)."""
import json
import math
import re
import threading
import time
from datetime import datetime

from caravan.admin.paths import AGENT_PROXY_LOG_DIR


class ProxyLatencyDigest:
    """Medians and 90th percentiles of one port's request timings.

    Each finished record carries `latency` since 1.3.437: the caravan's own
    work before the upstream, the connection, the upstream's answer, the
    processor time. This reads them back per port for the route window, over
    the window's range.

    The journal is read the way proxy_ports_last_seen reads it: a finished day
    once per process, today's file only past the bytes already read. And only
    whole lines — the proxy may be in the middle of writing the last one, and
    a half line parsed now would be a lost request later. Only the samples are
    kept, a few numbers per request. Requests before 1.3.437 have no `latency`
    and are not counted: they were not measured, and counting them as zero
    would draw a caravan faster than it is.
    """

    METRICS = ("prepMs", "connectMs", "headersMs", "firstChunkMs", "cpuMs")
    RANGES = {"1h": 3600, "12h": 12 * 3600, "24h": 24 * 3600}
    DAY_FILE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def __init__(self, log_dir=None, clock=time.time):
        self._log_dir = log_dir
        self._clock = clock
        self._days = {}          # day -> {"offset": bytes read, "samples": [...]}
        self._lock = threading.Lock()

    @property
    def log_dir(self):
        return self._log_dir if self._log_dir is not None else AGENT_PROXY_LOG_DIR

    @staticmethod
    def _sample(line):
        """(port, sample) from one journal line, or None when it holds no measured finish."""
        if b'"event":"finished"' not in line or b'"latency":' not in line:
            return None
        try:
            row = json.loads(line)
        except ValueError:
            return None
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        latency = item.get("latency")
        if row.get("event") != "finished" or not isinstance(latency, dict):
            return None
        try:
            port = int(item.get("port"))
        except (TypeError, ValueError):
            return None
        sample = {"t": row.get("time") or 0, "reused": latency.get("connReused")}
        for key in ProxyLatencyDigest.METRICS:
            value = latency.get(key)
            sample[key] = float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
        return port, sample

    def _read_day(self, day):
        path = self.log_dir / f"{day}.jsonl"
        try:
            size = path.stat().st_size
        except OSError:
            self._days.pop(day, None)
            return
        cached = self._days.get(day)
        if cached is None or cached["offset"] > size:
            cached = {"offset": 0, "samples": []}
            self._days[day] = cached
        if cached["offset"] == size:
            return
        with path.open("rb") as handle:
            handle.seek(cached["offset"])
            data = handle.read(size - cached["offset"])
        whole = data[:data.rfind(b"\n") + 1]
        for line in whole.splitlines():
            found = self._sample(line)
            if found:
                cached["samples"].append(found)
        cached["offset"] += len(whole)

    def _samples(self, port, since):
        every_day = sorted(p.stem for p in self.log_dir.glob("*.jsonl") if self.DAY_FILE.match(p.stem))
        first = datetime.fromtimestamp(since).strftime("%Y-%m-%d") if since else ""
        days = [day for day in every_day if day >= first]
        with self._lock:
            for day in list(self._days):
                if day not in every_day:
                    del self._days[day]       # the proxy's retention removed it
            for day in days:
                self._read_day(day)
            return [sample for day in days for p, sample in (self._days.get(day) or {}).get("samples", [])
                    if p == port and sample["t"] >= since]

    def cached_days(self):
        """The days whose samples are held — a day the proxy's retention removed must not stay."""
        with self._lock:
            return sorted(self._days)

    @staticmethod
    def _spread(values):
        """{n, p50, p90} by nearest rank, or None when nothing was measured."""
        values = sorted(values)
        if not values:
            return None

        def rank(q):
            return values[max(0, math.ceil(q * len(values)) - 1)]

        return {"n": len(values), "p50": rank(0.5), "p90": rank(0.9)}

    def summary(self, port, range_key="all"):
        """What the caravan's own time was on `port` over `range_key` (1h, 12h, 24h, else all)."""
        span = self.RANGES.get(range_key)
        since = int(self._clock() - span) if span else 0
        samples = self._samples(int(port), since)
        out = {"port": int(port), "range": range_key if span else "all", "requests": len(samples)}
        for key in self.METRICS:
            out[key] = self._spread([s[key] for s in samples if s[key] is not None])
        pooled = [s["reused"] for s in samples if isinstance(s["reused"], bool)]
        out["connReused"] = {"n": len(pooled), "reused": sum(pooled)} if pooled else None
        return out


proxy_latency = ProxyLatencyDigest()
