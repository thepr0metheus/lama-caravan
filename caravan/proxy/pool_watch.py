"""A pool that was edited is decided again at once, with no request to ask for it.

Which step a pool serves with is the proxy's word (caravan/proxy/pool_steps.py), and the board's "Serving now" and its
lit cable say that word and nothing else. The proxy chooses when a request comes, or when the idle probe asks
(caravan/proxy/output_probe.py: at most every five minutes, and only for a pool a backup node leads to). An edit
sends no request. So a step carried to the top of its pool changed what the next request will meet and not what the
card said: the owner put luna above sol on 2026-10-14 and the card went on saying that sol serves — true of the
request before, not of the next one. Here the proxy looks at the files the controller writes and, when a pool's
reading is not the one it last decided by, decides that pool again, as a request would. The state it writes
follows, and the board takes the word at its next poll.

What this leaves alone. The first look at the files, when the proxy has just started, decides nothing: a restarted
proxy says nothing until it is asked, as before. A decision made here sends nothing to a provider, takes no slot and
tries no step (it may read a subscription's limit windows, as the decision of a request does). The word of a pool
that nothing changed stays what the last request or probe made it.
"""
import json
import threading
import time


class PoolWatch:
    """What each pool looked like when it was last decided by, and which pools the files have changed since."""

    #: How often the files are looked at. A look is two stats unless a file changed.
    INTERVAL_SECONDS = 1

    def __init__(self, read, decide, stamp):
        self.read = read        # () -> {pool id: the pool as the proxy routes it} (cloud_auth.load_cloud_provider)
        self.decide = decide    # (that pool) -> None: the proxy's choice of a step, as a request makes it
        self.stamp = stamp      # () -> what the files read look like: the same stamp, nothing to read again
        self.stamped = None
        self.seen = None        # {pool id: its reading as text}; None until the first look

    @staticmethod
    def mtime(path):
        """When a file last changed, or 0 for one that is not there: a file that appears is a change too."""
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0

    @classmethod
    def standard(cls):
        """The watch over the files the proxy reads its pools from, deciding with the proxy's own selector."""
        from caravan.proxy.cloud_auth import load_cloud_pools, load_cloud_provider
        from caravan.proxy.paths import CLOUD_PROVIDERS_FILE, PROVIDER_SECRETS_FILE
        from caravan.proxy.pool_steps import pool_steps

        def read():
            sources = {}
            for pool in load_cloud_pools():
                source = load_cloud_provider(pool["id"])
                if source:
                    sources[pool["id"]] = source
            return sources

        def stamp():
            return tuple(cls.mtime(path) for path in (CLOUD_PROVIDERS_FILE, PROVIDER_SECRETS_FILE))

        return cls(read, pool_steps.resolve, stamp)

    def sweep(self):
        """The ids of the pools decided again by this look: those whose reading is not the one last seen, a new pool
        among them. The first look decides none and only writes down what the files say."""
        stamp = self.stamp()
        if stamp == self.stamped:
            return []
        sources = self.read()
        self.stamped = stamp          # only after a reading that worked: a failed one is looked at again
        readings = {pool_id: json.dumps(source, sort_keys=True, default=str) for pool_id, source in sources.items()}
        before, self.seen = self.seen, readings
        if before is None:
            return []
        decided = []
        for pool_id, reading in readings.items():
            if before.get(pool_id) == reading:
                continue
            try:
                self.decide(sources[pool_id])
            except Exception as err:  # noqa: BLE001 — one pool that cannot be decided must not keep the others waiting
                print(f"agent-proxy: pool {pool_id} not decided again after its edit: {err}", flush=True)
                continue
            decided.append(pool_id)
        return decided

    def run(self, write_state, sleep=time.sleep):
        """Daemon: a look every INTERVAL_SECONDS; the state file is rewritten when a pool was decided again. A look
        that keeps failing for one reason says so once, not every second: the log is not a clock."""
        said = None
        while True:
            try:
                if self.sweep():
                    write_state()
                said = None
            except Exception as err:  # noqa: BLE001 — the watch must outlive one bad look
                if str(err) != said:
                    print(f"agent-proxy: pool watch look failed: {err}", flush=True)
                    said = str(err)
            sleep(self.INTERVAL_SECONDS)

    @classmethod
    def start(cls):
        """The standard watch, running in a thread of its own: a decision may wait for a provider's answer to a
        usage question, and must not hold up the state writer or a request."""
        from caravan.proxy.state import write_state
        watch = cls.standard()
        threading.Thread(target=watch.run, args=(write_state,), name="pool-watch", daemon=True).start()
        return watch
