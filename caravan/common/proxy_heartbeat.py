"""How often the proxy rewrites its state file, and when the admin stops trusting it.

The admin reads the proxy's state file (agent-proxy-state.json) for what only
the proxy knows — which subscription a pool chose, each account's limit
windows — and takes a file older than STALE_SECONDS for a proxy that is gone.
So the proxy rewrites the file every BEAT_SECONDS whether anything happened or
not. It used to write it on requests and after probing a cell's slots: a
cloud-only controller (the NAS, 2026-10-08) probes no cells, and its pool card
fell back to "Not measured yet" 30 s after each request.
"""


class ProxyHeartbeat:
    """The beat of the proxy's state file, one rule for the proxy and the admin."""

    BEAT_SECONDS = 10
    #: Three beats missed: the proxy is gone, or stuck.
    STALE_SECONDS = 30

    @classmethod
    def fresh(cls, written_at, now):
        """True while a state file written at `written_at` (epoch seconds) still
        speaks for the proxy. A file with no time says nothing; a zero is the epoch,
        long stale."""
        try:
            written = float(written_at)
        except (TypeError, ValueError):
            return False
        return now - written <= cls.STALE_SECONDS
