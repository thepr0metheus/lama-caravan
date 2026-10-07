"""Connections to cloud providers kept open between requests (UpstreamPool)."""
import http.client
import select
import ssl
import threading
import time


class UpstreamPool:
    """Open connections to cloud providers, kept between requests.

    The proxy used to open a new connection for every request and close it
    after one answer. To a provider that is a TCP and a TLS handshake every
    time: about 52 ms from the controller's machine to OpenAI and 91–122 ms
    from the NAS, measured 2026-10-07. A cell is not pooled: its connection
    costs a fraction of a millisecond on the home network, and the proxy
    cancels a cell's generation by tearing its socket down.

    A connection comes back here only when its answer was read to the end and
    neither side asked to close it. One idle longer than idle_sec, or one the
    provider has closed meanwhile (its socket turns readable: FIN or a TLS
    close_notify), is dropped instead of handed out. Should the provider close
    it in the instant between that check and the request, the request fails
    before a single byte of answer: the handler retries it once on a fresh
    connection (`is_stale`). Idle connections are swept on every take and give
    back; with no traffic at all a few sockets wait for the next request.
    """

    # Errors of a kept connection the provider closed while it sat idle: the
    # request never got an answer, so sending it again is safe.
    STALE_ERRORS = (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError,
                    ConnectionAbortedError, ssl.SSLEOFError, ssl.SSLZeroReturnError)

    def __init__(self, idle_sec=60.0, per_host=8, drain_sec=1.0, drain_bytes=65536, clock=time.monotonic):
        self.idle_sec = idle_sec
        self.per_host = per_host
        self.drain_sec = drain_sec
        self.drain_bytes = drain_bytes
        self._clock = clock
        self._idle = {}          # (scheme, host, port) -> [(conn, idle since), ...], newest last
        self._lock = threading.Lock()

    @staticmethod
    def _key(conn):
        scheme = "https" if isinstance(conn, http.client.HTTPSConnection) else "http"
        return scheme, conn.host, conn.port

    @staticmethod
    def _open(key, timeout):
        scheme, host, port = key
        kind = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        return kind(host, port, timeout=timeout)

    @staticmethod
    def _close(conn):
        try:
            conn.close()
        except Exception:
            pass

    @staticmethod
    def _alive(conn):
        """Still open and quiet: an idle connection that turned readable was closed by the provider."""
        sock = conn.sock
        if sock is None:
            return False
        try:
            if isinstance(sock, ssl.SSLSocket) and sock.pending():
                return False
            readable, _, _ = select.select([sock], [], [], 0)
        except (OSError, ValueError):
            return False
        return not readable

    @classmethod
    def is_stale(cls, exc):
        return isinstance(exc, cls.STALE_ERRORS)

    def _sweep_locked(self, now):
        """Take the expired connections out; the caller closes them outside the lock."""
        expired = []
        for key in list(self._idle):
            kept = []
            for conn, since in self._idle[key]:
                (kept if now - since <= self.idle_sec else expired).append((conn, since))
            if kept:
                self._idle[key] = kept
            else:
                del self._idle[key]
        return [conn for conn, _ in expired]

    def take(self, tls, host, port, timeout):
        """A connection to host:port, and whether it is a kept one."""
        key = ("https" if tls else "http", host, port)
        found = None
        with self._lock:
            dropped = self._sweep_locked(self._clock())
            idle = self._idle.get(key) or []
            while idle and found is None:
                conn, _ = idle.pop()
                if self._alive(conn):
                    found = conn
                else:
                    dropped.append(conn)
            if not idle:
                self._idle.pop(key, None)
        for conn in dropped:
            self._close(conn)
        if found is None:
            return self._open(key, timeout), False
        found.timeout = timeout
        found.sock.settimeout(timeout)
        return found, True

    def reopen(self, conn, timeout):
        """A fresh connection to where `conn` went; `conn` itself is closed."""
        self._close(conn)
        return self._open(self._key(conn), timeout)

    def _drained(self, conn, response):
        """Read what is left of the answer — the stream's closing bytes — within drain_sec."""
        if response.isclosed():
            return True
        try:
            conn.sock.settimeout(self.drain_sec)
            left = self.drain_bytes
            while left > 0:
                chunk = response.read(min(left, 16384))
                if not chunk:
                    break
                left -= len(chunk)
        except (OSError, ValueError, http.client.HTTPException):
            return False
        return response.isclosed()

    def give_back(self, conn, response=None):
        """Keep `conn` for the next request to the same place, or close it.

        `response` is the answer read on it in this request (None when the
        caravan answered by itself and the connection carried nothing). An
        answer that says it closes the connection (`will_close`) has already
        taken the socket from `conn` — http.client hands it to the response —
        so such a connection is never kept. Returns whether it was kept.
        """
        reusable = conn.sock is not None and (response is None or self._drained(conn, response))
        if not reusable:
            self._close(conn)
            return False
        key = self._key(conn)
        with self._lock:
            dropped = self._sweep_locked(self._clock())
            idle = self._idle.setdefault(key, [])
            idle.append((conn, self._clock()))
            while len(idle) > self.per_host:
                dropped.append(idle.pop(0)[0])
        for old in dropped:
            self._close(old)
        return True

    def release(self, conn, response=None):
        """give_back, without anyone waiting for a stream's closing bytes.

        The handler closes its client's connection only when it returns: an
        answer delimited by that close (a relayed stream) would wait for the
        drain, up to drain_sec. An answer already read to the end goes back at
        once; one with bytes still to come is drained on a thread of its own.
        """
        if response is None or response.isclosed():
            self.give_back(conn, response)
            return
        threading.Thread(target=self.give_back, args=(conn, response), daemon=True,
                         name="upstream-pool-drain").start()

    def idle_count(self):
        with self._lock:
            return sum(len(rows) for rows in self._idle.values())


upstream_pool = UpstreamPool()
