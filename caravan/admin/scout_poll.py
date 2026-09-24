"""The scouts' state, pulled off the board's request path.

The board used to call every scout's /api/state inside GET /api/topology, one
after another, two seconds of timeout each: a machine switched off added two
seconds to every board poll for as long as it stayed off. The pull is a
freshness nicety — a cell's startup progress between two heartbeats — and not
something the board may wait for.

Now a board read only KICKS a pull. At most one runs at a time and at most one
starts per MIN_INTERVAL; the read returns what the store already holds, and the
next read sees what the pull brought.
"""
import threading
import time


class ScoutPoller:
    """Starts background pulls of the scouts' state, never more than one at a
    time and never more often than MIN_INTERVAL seconds."""

    MIN_INTERVAL = 5.0

    def __init__(self, pull, clock=time.monotonic, start=None):
        self._pull = pull
        self._clock = clock
        self._start = start or self._start_thread
        self._lock = threading.Lock()
        self._running = False
        self._last_start = None

    def kick(self):
        """Start a pull unless one is running or one started less than
        MIN_INTERVAL ago. Never waits for it; True when it started one."""
        with self._lock:
            now = self._clock()
            if self._running:
                return False
            if self._last_start is not None and now - self._last_start < self.MIN_INTERVAL:
                return False
            self._running = True
            self._last_start = now
        try:
            self._start(self._run)
        except Exception:
            # A pull that never started must not hold the gate shut forever.
            with self._lock:
                self._running = False
            raise
        return True

    def _run(self):
        try:
            self._pull()
        except Exception:  # noqa: BLE001 — a failed pull leaves the reports as they were
            pass
        finally:
            with self._lock:
                self._running = False

    @staticmethod
    def _start_thread(target):
        threading.Thread(target=target, name="scout-poll", daemon=True).start()
