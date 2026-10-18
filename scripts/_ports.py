"""Free ports for the tests: each handed out ONCE per process, never twice.

A test asks the kernel for a free port (bind to port 0, read the number, close the socket) and starts its server on that port a moment
later. test_proxy_forward.py asked about 60 times BEFORE any of its servers bound, and a port the kernel had just taken back is the one it
may hand out next: two servers got the same number and the second died with `OSError: [Errno 98] Address already in use` (GitLab
pipeline 30 of MR !130 failed on it once and went green on the retry; the clean clone on a Mac never showed it). Twelve other test files
carried a copy of the same eight lines.

The pool remembers what it gave and draws again on a repeat. It does not make the number safe against another PROCESS taking it between
the ask and the bind: that race is a different, rarer one, and a test that cannot live with it binds to port 0 itself and reads the port
off its own server. What it removes is the one a test makes against itself.

Import `free_port` from here; check_test_ports.py refuses a new copy of the eight lines in scripts/.
"""
import socket


class PortPool:
    """Free TCP ports on 127.0.0.1, each given once."""

    #: Draws before giving up: the kernel hands out from a range of tens of thousands, a repeat is rare, and a run of them is a sign
    #: the machine has no free ports left — said, not looped on for ever.
    ATTEMPTS = 200

    def __init__(self, make_socket=socket.socket):
        self.make_socket = make_socket
        self.given = set()

    def take(self):
        for _ in range(self.ATTEMPTS):
            sock = self.make_socket()
            try:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            finally:
                sock.close()
            if port not in self.given:
                self.given.add(port)
                return port
        raise RuntimeError(f"no port the kernel has not already given in {self.ATTEMPTS} draws")


#: The one pool of the process: every call in every test file draws from it. Why a function and not `PORTS.take` at the call sites: the
#: name is what twelve files import and what their call sites already say (`free_port()`); it only hands over to the pool.
PORTS = PortPool()


def free_port():
    return PORTS.take()
