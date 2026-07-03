"""A small (timestamp, value) TTL cache with an internal lock.

Replaces the hand-rolled `lock + {key: (ts, value)}` pattern. get() returns
the MISS sentinel on absent/expired entries so falsy values are cacheable.
Current double-fetch behavior is preserved: concurrent misses may both fetch
(no single-flight) — same as every call site did before.
"""
import threading
import time

MISS = object()


class TtlCache:
    def __init__(self, ttl):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._data = {}

    def get(self, key, ttl=None):
        limit = self.ttl if ttl is None else ttl
        with self._lock:
            hit = self._data.get(key)
        if hit is not None and time.time() - hit[0] < limit:
            return hit[1]
        return MISS

    def put(self, key, value):
        with self._lock:
            self._data[key] = (time.time(), value)

    def clear(self):
        with self._lock:
            self._data.clear()
