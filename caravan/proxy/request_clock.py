"""Where one proxied request's time went (RequestClock), and the upstream
answer that notes when its first body bytes arrived (TimedResponse)."""
import time


class TimedResponse:
    """An upstream answer that notes when its first body bytes arrived.

    The relay cannot tell this by itself: the subscription translator yields a
    made-up first chunk (the assistant's role) before it reads a single byte
    from the provider, so the record's firstByteMs says when the CLIENT got
    something, not when the provider answered. Every read the relay makes goes
    through here — read(), readline() and iteration — and everything else is
    the wrapped response's own.
    """

    def __init__(self, response, clock):
        self._response = response
        self._clock = clock
        self.first_bytes_at = None

    @property
    def raw(self):
        """The wrapped http.client response — what the connection pool judges."""
        return self._response

    def _noted(self, data):
        if data and self.first_bytes_at is None:
            self.first_bytes_at = self._clock()
        return data

    def read(self, *args):
        return self._noted(self._response.read(*args))

    def readline(self, *args):
        return self._noted(self._response.readline(*args))

    def __iter__(self):
        while True:
            line = self.readline()
            if not line:
                return
            yield line

    def __getattr__(self, name):
        return getattr(self._response, name)


class RequestClock:
    """Where one request's time went, in milliseconds.

    durationMs and firstByteMs mix the caravan's own work with the model's and
    the network's, so neither could say how much the caravan itself adds — the
    question to answer before the caravan moves onto the NAS's slower
    processor. The marks split a request into:

      prepMs        the caravan's own work before its first upstream attempt:
                    routing, translating the body, the journal. The wait in
                    the queue is not in it — that is queue.queuedMs;
      connectMs     opening the connection to the upstream: TCP, and TLS for
                    a provider. 0 when a kept connection was taken;
      connReused    whether the connection was a kept one. None where nothing
                    is kept (a cell): "not kept" would claim a choice;
      headersMs     from the request sent to the answer's headers;
      firstChunkMs  from the request sent to the answer's first body bytes;
      cpuMs         processor time the request's thread spent, all of it.

    Connect, headers and first chunk belong to the leg that answered: after a
    replay on a backup exit they are the backup's. A mark that never happened
    stays None — a request answered by the caravan itself never connected, and
    0 there would read as "instant". Both clocks are parameters, so a test
    drives them.
    """

    def __init__(self, clock=time.monotonic, cpu_clock=time.thread_time):
        self._clock = clock
        self._cpu_clock = cpu_clock
        self._cpu_started = cpu_clock()
        self._received = clock()
        self._queue_entered = None
        self._admitted = None
        self._leg_started = None
        self._connect_ms = None
        self._reused = None
        self._sent = None
        self._headers = None
        self._response = None

    def now(self):
        return self._clock()

    def queue_entered(self):
        self._queue_entered = self._clock()

    def admitted(self):
        self._admitted = self._clock()

    def leg_started(self):
        """Prep ends where the FIRST upstream attempt begins; later legs keep it."""
        if self._leg_started is None:
            self._leg_started = self._clock()

    def connected(self, began, reused):
        """A connection is ready: opened since `began`, or kept (reused=True)."""
        self._connect_ms = 0.0 if reused else (self._clock() - began) * 1000
        self._reused = reused

    def sent(self):
        self._sent = self._clock()
        self._headers = None
        self._response = None

    def answered(self, response):
        """Headers are in: the answer, wrapped so its first bytes get noted."""
        self._headers = self._clock()
        self._response = TimedResponse(response, self._clock)
        return self._response

    def as_dict(self):
        def since_sent(at):
            if self._sent is None or at is None:
                return None
            return round((at - self._sent) * 1000, 1)

        prep = None
        if self._leg_started is not None:
            if self._queue_entered is not None and self._admitted is not None:
                prep = (self._queue_entered - self._received) + (self._leg_started - self._admitted)
            else:
                prep = self._leg_started - self._received
            prep = round(max(0.0, prep) * 1000, 1)
        return {
            "prepMs": prep,
            "connectMs": None if self._connect_ms is None else round(self._connect_ms, 1),
            "connReused": self._reused,
            "headersMs": since_sent(self._headers),
            "firstChunkMs": since_sent(self._response.first_bytes_at if self._response else None),
            "cpuMs": round((self._cpu_clock() - self._cpu_started) * 1000, 1),
        }
