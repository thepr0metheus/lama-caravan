"""The machines with a scout, second by second, for the board's charts."""
import collections
import threading
import time


class HostTelemetry:
    """Each scout's machine sampled a second apart, pulled while a board is open.

    The board draws this controller's machine from its own monitor, a sample
    a second; a scout's machine was drawn from its reports — a GPU reading a
    scout keeps ten seconds, a report every few seconds at best. A scout that
    says so in its report (`telemetry`, 2.8+) keeps ten minutes of its own
    samples; this pulls what is new from each such machine, at most once a
    second and never on the request path: the board's monitor read only
    KICKS a pull (like ScoutPoller) and gets what is already here. A machine
    that does not answer keeps what it had.

    Rows are the scout's own, stamped by its clock. The board says, per
    machine, the newest row it holds (`hostsSince=id:t,id:t`); a machine it
    does not name gets its whole ten minutes — one that came online after the
    board opened, or whose first pull finished a second later, keeps its
    history. Clocks a few seconds apart cost nothing: each machine's rows are
    compared only with its own.
    """

    MIN_INTERVAL = 1.0
    RETENTION = 600

    def __init__(self, hosts, scout_for, clock=time.monotonic, start=None):
        self._hosts = hosts            # () -> the host records to watch
        self._scout_for = scout_for    # host_id -> Scout
        self._clock = clock
        self._start = start or self._start_thread
        self._lock = threading.Lock()
        self._rows = {}                # host_id -> deque of rows
        self._busy = set()
        self._last = {}

    @staticmethod
    def sampled(host):
        """Whether a machine is worth asking: its scout says it samples, and
        it is online now."""
        return isinstance(host.get("telemetry"), dict) and host.get("state") == "online"

    def kick(self):
        """Start a pull of every sampled machine not pulled in the last
        second and not being pulled now. Never waits; the ids it started."""
        started = []
        now = self._clock()
        for host in self._hosts():
            host_id = str(host.get("id") or "")
            if not host_id or not self.sampled(host):
                continue
            with self._lock:
                if host_id in self._busy or now - self._last.get(host_id, -1e9) < self.MIN_INTERVAL:
                    continue
                self._busy.add(host_id)
                self._last[host_id] = now
            try:
                self._start(lambda h=host_id: self._pull(h))
            except Exception:
                with self._lock:
                    self._busy.discard(host_id)
                raise
            started.append(host_id)
        return started

    def newest(self, host_id):
        with self._lock:
            rows = self._rows.get(host_id)
            return rows[-1]["t"] if rows else 0

    def _pull(self, host_id):
        try:
            answer = self._scout_for(host_id).read(f"/api/telemetry?since={self.newest(host_id)}", timeout=2)
            if not isinstance(answer, dict) or not answer.get("ok"):
                return
            fresh = [r for r in answer.get("samples") or []
                     if isinstance(r, dict) and isinstance(r.get("t"), (int, float))]
            with self._lock:
                rows = self._rows.setdefault(host_id, collections.deque())
                for row in fresh:
                    if not rows or row["t"] > rows[-1]["t"]:
                        rows.append(row)
                while rows and rows[0]["t"] < rows[-1]["t"] - self.RETENTION:
                    rows.popleft()
        except Exception:  # noqa: BLE001 — a failed pull leaves the rows as they were
            pass
        finally:
            with self._lock:
                self._busy.discard(host_id)

    @staticmethod
    def held(raw):
        """The board's `hostsSince` — "id:t,id:t" — as {host_id: t}; what
        does not read as that is nothing held."""
        held = {}
        for part in str(raw or "").split(","):
            host_id, _, t = part.strip().rpartition(":")
            try:
                if host_id:
                    held[host_id] = int(float(t))
            except ValueError:
                continue
        return held

    def since(self, held=None):
        """{host_id: rows newer than what the board holds of it} for the
        machines that have such rows; a machine not in `held`, all of its."""
        held = held if isinstance(held, dict) else {}
        with self._lock:
            out = {host_id: [dict(r) for r in rows if r["t"] > held.get(host_id, 0)]
                   for host_id, rows in self._rows.items()}
        return {host_id: rows for host_id, rows in out.items() if rows}

    def watch(self, raw_held=""):
        """What the board's monitor read carries: the rows here now that it
        does not hold, and a pull started for the next read."""
        self.kick()
        return self.since(self.held(raw_held))

    @staticmethod
    def _start_thread(target):
        threading.Thread(target=target, name="host-telemetry", daemon=True).start()
